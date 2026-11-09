"""
🎨 Identidade visual do canal (v84_168) — imagens 100% IA que seguem um Brand Kit à risca.

O Brand Kit (ex.: marcas/dinge_erklaeren/) tem:
  brand_guide.json   a especificação principal (schema channel_visual_identity_spec) — NUNCA é reescrita
  assets/            as imagens oficiais (painel, mascote original, logo, banner, marca-d'água)
  referencias/       recortes derivados das oficiais (as 8 poses do painel, silhuetas, mascote em alta, colagens de estilo)
  folha_mestra/      a folha mestra do mascote: v0 (montada das referências) e as versões geradas/aprovadas célula a célula
  projetos/<id>/     cada vídeo: batidas da narração, prompts, referências, parâmetros, imagens, paleta, QA (fora do Git)

O fluxo segue o recommended_pipeline do JSON:
  1-2 batidas da narração + tipo de imagem (IA ou prompt pra colar)  →  3 prompt = template + style_lock + prompt_lock
  (+ negativo como "Avoid:", porque o FLUX.2 klein e o Z-Image não têm prompt negativo)  →  4 referências (até 4 no
  klein do pod; 1 no Flow)  →  5 gerar e registrar (modelo, seed, versões)  →  6 validar a paleta e corrigir (grading
  noir + vermelho seletivo)  →  7 textos no idioma do canal por cima (nunca gerados pela IA)  →  8 QA (automático + IA + você)
  →  9 exportar (masters sem texto + versões com texto + metadados).
"""
from __future__ import annotations

import colorsys
import hashlib
import io
import json
import math
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from typing import Any, Dict, Iterable, List, Optional, Tuple

PASTA = "marcas"
SCHEMA = "channel_visual_identity_spec"
_TRAVA = threading.Lock()
FONTES = {"manchete": "assets/fonts/dp/alfa-slab-one-Bold.ttf", "etiqueta": "assets/fonts/dp/special-elite-Bold.ttf",
          "rotulo": "assets/fonts/dp/roboto-condensed-Bold.ttf"}

# 🧍 poses do mascote: as 8 do painel oficial + as variações permitidas no JSON (allowed_variations)
POSES: Dict[str, Dict[str, Any]] = {
    "normal": {"nome": "Normal (pose canônica)", "ref": "normal",
               "en": "the canonical pose: leaning forward, torso curved, one long arm stretched out, attentive eyes"},
    "curioso": {"nome": "Curioso", "ref": "curioso", "en": "hunched forward with curiosity, head tilted toward the subject"},
    "surpreso": {"nome": "Surpreso", "ref": "surpreso", "en": "startled by a surprising fact, recoiling with raised hands"},
    "investigando": {"nome": "Investigando (lupa)", "ref": "investigando", "en": "examining a clue closely with a magnifying glass"},
    "explicando": {"nome": "Explicando / apontando", "ref": "explicando", "en": "pointing firmly at the subject as if explaining it"},
    "estudando": {"nome": "Estudando (livro)", "ref": "estudando", "en": "sitting cross-legged reading an old book, stacked books beside it"},
    "sem_ideia": {"nome": "Sem ideia", "ref": "sem_ideia", "en": "shrugging with both long arms open, puzzled"},
    "ideia": {"nome": "Ideia", "ref": "ideia", "en": "one finger raised, struck by an idea, an old light bulb glowing above"},
    "olhando_cima": {"nome": "Olhando pra cima", "ref": "curioso", "en": "looking upward in wonder at something large above"},
    "foto": {"nome": "Investigando uma fotografia", "ref": "investigando", "en": "holding and inspecting an old photograph"},
    "observando": {"nome": "Observando um objeto", "ref": "curioso", "en": "observing a sphere, fossil or diagram up close"},
    "espiando": {"nome": "Espiando da borda", "ref": "normal", "en": "peeking in from the edge of the frame, only part of the body visible"},
}
# 🗂 folha mestra: vistas + silhueta + ≥ 6 expressões/poses (consistency_protocol do JSON)
CELULAS_FOLHA: List[Dict[str, str]] = [
    {"id": "frente", "nome": "Frente", "ref": "explicando", "en": "full-body FRONT view, standing neutral, arms relaxed at the sides, facing the viewer"},
    {"id": "perfil", "nome": "Perfil", "ref": "normal", "en": "full-body SIDE PROFILE view facing right, standing, the curved body clearly readable"},
    {"id": "tres_quartos", "nome": "Três quartos", "ref": "curioso", "en": "full-body THREE-QUARTER view, turned slightly to the right, standing"},
    {"id": "silhueta", "nome": "Silhueta", "ref": "normal", "en": "the canonical leaning pose as a SOLID FLAT BLACK SILHOUETTE on plain aged cream paper, no inner details"},
] + [{"id": k, "nome": v["nome"], "ref": v["ref"], "en": v["en"]} for k, v in POSES.items()
     if k in ("normal", "curioso", "surpreso", "investigando", "explicando", "estudando", "sem_ideia", "ideia", "olhando_cima")]
TIPOS_IMAGEM = {
    "arquivo": "fotografia de arquivo monocromática",
    "ilustracao": "ilustração explicativa",
    "close": "close-up simbólico",
    "ambiente": "ambiente / lugar",
    "diagrama": "gráfico / diagrama",
    "mascote": "cena com o mascote",
}
MOTORES = {"pod": "Pod (FLUX.2 klein com referências / Z-Image)", "flow": "Google Flow (1 referência)"}
# como cada tipo de imagem entra no prompt (em inglês) — o brand_guide pode trocar (generation_system.image_types_en)
TIPOS_IMAGEM_EN = {"arquivo": "monochrome archival photograph",
                   "ilustracao": "explanatory vintage illustration without any lettering",
                   "close": "symbolic close-up", "ambiente": "establishing environment shot",
                   "diagrama": "symbolic still life of the concept made only of real objects (no chart, no letters, no numbers)"}


def tipos_imagem_da_marca(m: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """🖼 v84_367: os tipos de imagem que a marca usa — generation_system.allowed_image_types no brand_guide limita a lista
    (ex.: canal realista sem "arquivo" monocromático nem "ilustracao"); sem o campo, todos."""
    perm = ((m or {}).get("guia", {}).get("generation_system") or {}).get("allowed_image_types")
    if isinstance(perm, list) and perm:
        filtrado = {k: v for k, v in TIPOS_IMAGEM.items() if k in perm or k == "mascote"}
        if any(k != "mascote" for k in filtrado):
            return filtrado
    return dict(TIPOS_IMAGEM)
PRESET_GRADING = "noir_vermelho_v1"


class MarcaErro(Exception):
    pass


# ------------------------------------------------------------------ marcas (Brand Kits)
def _pasta(base: str, slug: str = "") -> str:
    if slug and not re.fullmatch(r"[a-z0-9_]{2,40}", slug):
        raise MarcaErro("Identidade visual inválida.")
    return os.path.join(base, PASTA, slug) if slug else os.path.join(base, PASTA)


def _json(caminho: str, padrao: Any = None) -> Any:
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def _gravar(caminho: str, dados: Any) -> None:
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def _hash(v: Any) -> str:
    return hashlib.sha1(json.dumps(v, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:8]


def listar(base: str) -> List[Dict[str, Any]]:
    out = []
    raiz = _pasta(base)
    if not os.path.isdir(raiz):
        return out
    for slug in sorted(os.listdir(raiz)):
        try:
            m = carregar(base, slug)
        except MarcaErro:
            continue
        p = m["guia"].get("project") or {}
        out.append({"slug": slug, "nome": p.get("name") or slug, "slogan": p.get("brand_slogan_de") or "",
                    "idioma": p.get("channel_language") or "", "folha_aprovada": bool(m["estado"].get("folha_aprovada"))})
    return out


def carregar(base: str, slug: str) -> Dict[str, Any]:
    d = _pasta(base, slug)
    guia = _json(os.path.join(d, "brand_guide.json"))
    if not isinstance(guia, dict) or guia.get("schema") != SCHEMA:
        raise MarcaErro("Identidade visual não encontrada (falta o brand_guide.json).")
    estado = _json(os.path.join(d, "estado.json"), {}) or {}
    return {"slug": slug, "dir": d, "guia": guia, "estado": estado, "versoes": versoes(guia)}


def salvar_estado(m: Dict[str, Any]) -> None:
    _gravar(os.path.join(m["dir"], "estado.json"), m["estado"])


def versoes(guia: Dict[str, Any]) -> Dict[str, str]:
    """As versões que vão no registro de cada imagem (consistency_metadata_to_log)."""
    ds = guia.get("design_system") or {}
    gs = guia.get("generation_system") or {}
    ms = guia.get("mascot") or {}
    return {"style_lock_version": "sl-" + _hash(gs.get("style_lock_en")),
            "palette_version": "pal-" + _hash(ds.get("palette")),
            "prompt_version": "pr-" + _hash([gs.get("base_prompt_template_en"), gs.get("scene_prompt_template_en"),
                                            gs.get("thumbnail_prompt_template_en"), ms.get("prompt_lock_en"), "mv1"]),
            "postprocess_preset": PRESET_GRADING}


FORMATO_PACOTE = "besteditor_pacote_canal"
VERSAO_PACOTE = 1
_IMG = (".png", ".jpg", ".jpeg", ".webp", ".gif")
# o que o pacote pode ter (caminho relativo à raiz do pacote) → nível, o que é
ESTRUTURA_PACOTE: List[Tuple[str, str, str]] = [
    ("pacote.json", "recomendado", "a etiqueta do pacote: formato, versão, slug, nome do canal, idioma — e \"producao_pod\" (% de "
                                   "cenas no pod, personagens, fotos do roteiro): como a 🏭 Produção no pod gera os vídeos do canal"),
    ("brand_guide.json", "obrigatório", "a especificação da marca (schema channel_visual_identity_spec) — nunca é reescrita"),
    ("assets/", "obrigatório", "as imagens oficiais da marca (mascote, painel, logo, banner…)"),
    ("referencias/poses/pose_<id>.png", "recomendado", "um recorte do mascote por pose oficial: normal, curioso, surpreso, investigando, explicando, estudando, sem_ideia, ideia"),
    ("referencias/mascote_proporcoes.png", "recomendado", "o mascote inteiro em vários quadros lado a lado — a proporção de verdade (vai em toda geração)"),
    ("referencias/silhuetas/silhueta_<id>.png", "opcional", "silhuetas pretas das poses"),
    ("referencias/animacao_original/*.png", "opcional", "quadros do desenho original do mascote"),
    ("referencias/mascote_alta_res_tronco.png", "opcional", "o mascote em alta resolução (traço e textura)"),
    ("referencias/estilo_colagem_*.png", "opcional", "amostras de estilo/paleta SEM texto"),
    ("folha_mestra/folha_mestra_v0_limpa.png", "opcional", "a folha mestra inicial sem texto (o site monta se faltar)"),
    ("exemplos_alvo/*.png", "opcional", "exemplos do visual desejado (podem ter texto — só pra humanos, nunca vão pra IA)"),
    ("referencias_rejeitadas/*.png", "opcional", "o que NÃO é o personagem (nunca vai pra IA)"),
    ("reforcos.json", "recomendado", "{\"mascote_en\", \"evitar_en\", \"qa_pt\"}: a trava de proporção/o que a IA costuma errar"),
    ("poses_sugeridas.json", "opcional", "{\"poses\": [\"com lupa\", …]}: sugestões de poses novas"),
    ("modelo_roteiro.json", "recomendado", "o modelo de roteiro do canal (entra nos 🕵️ Modelos de vídeo, falando o nome do canal)"),
    ("personagens.json", "opcional", "🎭 canal com PERSONAGENS fixos: narrador + cada personagem (personalidade, como fala, quando "
                                     "aparece e quando não, segredo, emoções da voz, voz sugerida, desenho e fichas) — vira roteiro multi voz"),
    ("personagens/<slug>.json", "opcional", "🧍 as POSES PNG de cada personagem (formato personagens_pod_v1: a trava do desenho, "
                                           "o estilo e a lista de poses/reações/objetos/_boca) — na aba 🧍 Personagens você escolhe "
                                           "a personagem do canal e gera os PNG transparentes que o editor põe por cima do vídeo "
                                           "nos melhores momentos. A personagem NÃO é desenhada nas cenas"),
    ("personagens/<slug>_ficha.png", "opcional", "🧍 a ficha da personagem (1 a 3 imagens: _ficha.png, _ficha_2.png…) — só pra gerar "
                                                 "as poses na aba 🧍 Personagens (nunca vai pras cenas do vídeo)"),
    ("lore.md", "opcional", "🎭 a bíblia da lore (a IA consulta o porquê de cada dinâmica antes de escrever)"),
    ("continuidade.json", "opcional", "🎭 as pistas da lore (clue_id, símbolo, pergunta, estado) — o site marca o uso a cada roteiro"),
    ("docs/*.md", "opcional", "manuais do canal (formatos, prompt do roteirista, roteiro exemplo, análise) — o roteiro exemplo pode "
                              "virar o 📐 do modelo (\"roteiro_exemplo\" no modelo_roteiro.json)"),
    ("direcao.json", "opcional", "o estilo de direção do canal no editor (cor, filtros, movimentos, transições, entradas, quadros, "
                                 "destaques) — vira a direção “🎨 <canal>” e é sugerida sozinha nos vídeos desse modelo"),
    ("LEIA-ME.txt", "opcional", "notas pra humanos"),
]
_JSON_PERMITIDOS = {"pacote.json", "brand_guide.json", "reforcos.json", "poses_sugeridas.json", "modelo_roteiro.json", "manifest.json",
                    "personagens.json", "continuidade.json", "lore.md",
                    "direcao.json"}
_PASTAS_PERMITIDAS = ("assets/", "referencias/", "folha_mestra/", "exemplos_alvo/", "referencias_rejeitadas/")
_PASTAS_TEXTO = ("docs/", "fonte/")  # 🎭 v84_173: manuais do canal (.md/.txt) e o JSON original da marca (.json)
_PASTA_PERSONAGENS = "personagens/"  # 🧍 v84_185: personagens/<slug>.json = as poses PNG de cada personagem
# o que é seu e o import nunca apaga (🧍 personagens_ligados.json: qual projeto da aba Personagens é de cada personagem)
_LOCAIS = ("projetos", "estado.json", "lore_historico.json", "vozes_escolhidas.json", "personagens_ligados.json")


def _slugificar(nome: str) -> str:
    import unicodedata
    return re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode().lower()).strip("_")[:40] or "marca"


def importar_zip(base: str, dados: bytes) -> str:
    """📦 Um pacote de canal (.zip no formato besteditor_pacote_canal) — ou só o Brand Kit (o JSON + assets/) — vira
    marcas/<slug>/. Os arquivos vêm como estão (o JSON da marca nunca é reescrito). Se a marca já existe, as
    referências são trocadas e os seus projetos/aprovações ficam. Falta folha mestra → o site monta a v0."""
    try:
        z = zipfile.ZipFile(io.BytesIO(dados))
    except zipfile.BadZipFile as exc:
        raise MarcaErro("Esse arquivo não é um .zip.") from exc
    nomes = [n for n in z.namelist() if not n.endswith("/") and "__MACOSX" not in n and not os.path.basename(n).startswith(".")]
    guia_nome, guia = None, None
    for n in sorted(nomes, key=lambda x: (os.path.basename(x) != "brand_guide.json", x.count("/"))):
        if n.lower().endswith(".json"):
            try:
                g = json.loads(z.read(n).decode("utf-8-sig"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(g, dict) and g.get("schema") == SCHEMA:
                guia_nome, guia = n, g
                break
    if not guia_nome:
        raise MarcaErro(f"Não achei no .zip o JSON da marca (com \"schema\": \"{SCHEMA}\"). Veja 📘 Como montar o pacote.")
    raiz = os.path.dirname(guia_nome)
    pac = {}
    pn = (raiz + "/" if raiz else "") + "pacote.json"
    if pn in nomes:
        try:
            pac = json.loads(z.read(pn).decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise MarcaErro(f"pacote.json inválido: {exc}") from exc
        if pac.get("formato") not in (None, FORMATO_PACOTE):
            raise MarcaErro(f"pacote.json: \"formato\" deve ser \"{FORMATO_PACOTE}\".")
    slug = _slugificar(pac.get("slug") or (guia.get("project") or {}).get("name") or "marca")
    d = _pasta(base, slug)
    cont_antes = _json(os.path.join(d, "continuidade.json"), {}) or {}  # 🧩 o estado das pistas é seu: sobrevive ao import
    lore_antes = ""
    try:
        with open(os.path.join(d, "lore.md"), encoding="utf-8") as f:
            lore_antes = f.read()
    except OSError:
        pass
    if os.path.isdir(d):  # troca as referências, mantém os seus projetos, aprovações e o histórico da lore
        for item in os.listdir(d):
            if item not in _LOCAIS and not (item == "folha_mestra"):
                cam = os.path.join(d, item)
                shutil.rmtree(cam) if os.path.isdir(cam) else os.remove(cam)
        fm = os.path.join(d, "folha_mestra")
        if os.path.isdir(fm):
            for item in os.listdir(fm):
                if item.startswith("folha_mestra_v0"):
                    os.remove(os.path.join(fm, item))
    os.makedirs(d, exist_ok=True)
    copiados = 0
    for n in nomes:
        rel = os.path.relpath(n, raiz).replace("\\", "/") if raiz else n
        if rel.startswith("../"):
            continue
        if n == guia_nome:
            rel = "brand_guide.json"
        ext = os.path.splitext(rel)[1].lower()
        ok = (rel in _JSON_PERMITIDOS or (rel.upper().startswith("LEIA") and ext == ".txt")
              or (rel.startswith(_PASTAS_PERMITIDAS) and ext in _IMG)
              or (rel.startswith(_PASTAS_TEXTO) and ext in (".md", ".txt", ".json"))
              or (rel.startswith(_PASTA_PERSONAGENS) and rel.count("/") == 1 and ext in (".json", ".png", ".jpg", ".jpeg", ".webp")))
        if not ok:
            continue
        if rel in ("reforcos.json", "poses_sugeridas.json", "modelo_roteiro.json", "pacote.json", "manifest.json", "direcao.json",
                   "personagens.json", "continuidade.json") or (rel.startswith(_PASTA_PERSONAGENS) and ext == ".json"):
            try:
                json.loads(z.read(n).decode("utf-8-sig"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise MarcaErro(f"{rel} não é um JSON válido: {exc}") from exc
        alvo = os.path.abspath(os.path.join(d, os.path.normpath(rel)))
        if not alvo.startswith(os.path.abspath(d) + os.sep):
            continue
        os.makedirs(os.path.dirname(alvo), exist_ok=True)
        with open(alvo, "wb") as f:
            f.write(z.read(n))
        copiados += 1
    if not os.path.isdir(os.path.join(d, "assets")):
        raise MarcaErro("O pacote precisa da pasta assets/ com as imagens oficiais da marca.")
    _juntar_estado_do_canal(base, slug, d, cont_antes, lore_antes)
    try:  # 🧍 v84_188: as poses das personagens que vieram no zip (📦 Zip do canal de outro PC) → os projetos, já conectados
        import personagens_pod as _pp
        _pp.importar_do_pacote(z, raiz, slug, base)
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
    m = carregar(base, slug)
    if not folha_atual(m):
        montar_folha_v0(m, base)
    registrar_modelos(base)
    return slug


def _juntar_estado_do_canal(base: str, slug: str, d: str, cont_antes: Dict[str, Any], lore_antes: str) -> None:
    """🎭 Import de novo: as pistas mantêm o estado/os usos que você já tem; a sua bíblia editada vai pro histórico."""
    cam = os.path.join(d, "continuidade.json")
    nova = _json(cam, None)
    if isinstance(nova, dict) and cont_antes.get("pistas"):
        velhas = {str(p.get("clue_id")): p for p in cont_antes.get("pistas") or [] if isinstance(p, dict)}
        for p in nova.get("pistas") or []:
            v = velhas.get(str(p.get("clue_id")))
            if v:
                for k in ("estado", "usos"):
                    if v.get(k):
                        p[k] = v[k]
        _gravar(cam, nova)
    try:
        with open(os.path.join(d, "lore.md"), encoding="utf-8") as f:
            lore_nova = f.read()
    except OSError:
        lore_nova = ""
    if lore_antes and lore_nova and lore_antes != lore_nova:
        import canal_perfil
        h = canal_perfil.historico(base, slug)
        h.append({"tipo": "mudanca", "arquivo": "lore.md", "motivo": "o pacote importado trouxe outra bíblia (esta era a de antes)",
                  "antes": lore_antes[:60000], "quando": time.time()})
        canal_perfil._salvar_hist(base, slug, h)


def montar_folha_v0(m: Dict[str, Any], base: str = ".") -> Optional[str]:
    """A folha mestra v0 com o que o pacote tem: quadros do original, poses, silhuetas (ou as imagens de assets/)."""
    R = os.path.join(m["dir"], "referencias")
    cel: List[Tuple[str, str]] = []
    ani = os.path.join(R, "animacao_original")
    if os.path.isdir(ani):
        cel += [("Original", os.path.join(ani, f)) for f in sorted(os.listdir(ani)) if f.lower().endswith(_IMG)][:4]
    for k in POSES:
        cam = os.path.join(R, "poses", f"pose_{k}.png")
        if os.path.isfile(cam):
            cel.append((POSES[k]["nome"], cam))
    sil = os.path.join(R, "silhuetas")
    if os.path.isdir(sil):
        cel += [("Silhueta", os.path.join(sil, f)) for f in sorted(os.listdir(sil)) if f.lower().endswith(_IMG)][:2]
    if not cel:  # 🎭 canal com personagens: a ficha de cada uma
        pj = _json(os.path.join(m["dir"], "personagens.json"), {}) or {}
        for p in pj.get("personagens") or []:
            for rel in (p.get("referencias") or [])[:1]:
                cam = os.path.join(m["dir"], os.path.normpath(rel))
                if os.path.isfile(cam):
                    cel.append((str(p.get("nome") or p.get("slug")), cam))
        for rel in (pj.get("referencias_dupla") or [])[:1]:
            cam = os.path.join(m["dir"], os.path.normpath(rel))
            if os.path.isfile(cam):
                cel.append(("Juntas", cam))
    if not cel:  # pacote só com o Brand Kit: os arquivos canônicos do mascote que o JSON aponta
        for rel in ((m["guia"].get("mascot") or {}).get("canonical_reference_files") or []):
            cam = os.path.join(m["dir"], os.path.normpath(rel))
            if os.path.isfile(cam) and "painel" not in rel:
                cel.append((os.path.splitext(os.path.basename(rel))[0], cam))
    if not cel:
        return None
    nome = (m["guia"].get("project") or {}).get("name") or m["slug"]
    fm = os.path.join(m["dir"], "folha_mestra")
    montar_folha(m, cel, os.path.join(fm, "folha_mestra_v0_limpa.png"), False, base)
    montar_folha(m, cel, os.path.join(fm, "folha_mestra_v0_rotulada.png"), True, base, titulo=f"{nome} — folha mestra v0")
    return os.path.join(fm, "folha_mestra_v0_limpa.png")


def conferir_pacote(m: Dict[str, Any]) -> List[Dict[str, Any]]:
    """✅ O que o pacote tem e o que falta (pra página e pro import)."""
    import glob
    out = []
    tem_pers = os.path.isfile(os.path.join(m["dir"], "personagens.json")) or os.path.isdir(os.path.join(m["dir"], "personagens"))
    so_mascote = ("referencias/poses/", "referencias/mascote_", "referencias/silhuetas/", "referencias/animacao_original/",
                  "reforcos.json", "poses_sugeridas.json")
    for rel, nivel, oque in ESTRUTURA_PACOTE:
        if tem_pers and rel.startswith(so_mascote):
            continue  # 🎭 canal com personagens: as coisas do mascote único não se aplicam
        padrao = rel.replace("<id>", "*").replace("<slug>", "*")
        if padrao.endswith("/"):
            achados = [x for x in glob.glob(os.path.join(m["dir"], padrao, "*")) if x.lower().endswith(_IMG)]
        else:
            achados = glob.glob(os.path.join(m["dir"], padrao))
        out.append({"item": rel, "nivel": nivel, "oque": oque, "ok": bool(achados), "n": len(achados)})
    poses = [k for k in POSES if os.path.isfile(os.path.join(m["dir"], "referencias", "poses", f"pose_{k}.png"))]
    if tem_pers:
        return out
    out.append({"item": "poses oficiais recortadas", "nivel": "recomendado", "oque": f"{len(poses)} de 8: {', '.join(poses) or '—'}",
                "ok": len(poses) >= 6, "n": len(poses)})
    return out


def modelo_roteiro(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    d = _json(os.path.join(m["dir"], "modelo_roteiro.json"))
    if not isinstance(d, dict) or not isinstance(d.get("formatos"), dict) or not d["formatos"]:
        return None
    return d


def registrar_modelos(base: str) -> List[str]:
    """🕵️ Cada pacote com modelo_roteiro.json vira um modelo nos Modelos de vídeo (com a identidade visual ligada e o
    nome do canal da marca). Nada de canal embutido no código: sem pacote, sem modelo."""
    try:
        import dossies as ds
    except Exception:  # noqa: BLE001
        return []
    feitos = []
    for x in listar(base):
        m = carregar(base, x["slug"])
        d = modelo_roteiro(m)
        if not d:
            continue
        chave = "marca_" + _slugificar(d.get("chave") or x["slug"])[:30]
        formatos = {}
        for fk, fv in d["formatos"].items():
            if isinstance(fv, dict) and fv.get("estrutura"):
                formatos[_slugificar(fk)[:30]] = {"nome": str(fv.get("nome") or fk)[:80],
                                                   "minutos": float(fv.get("minutos") or 10),
                                                   "estrutura": [str(e)[:400] for e in fv["estrutura"]][:30]}
        if not formatos:
            continue
        nome_canal = str(d.get("nome_canal") or (m["guia"].get("project") or {}).get("name") or "")[:80]
        # 🎬 v84_171: a direção do editor — a do pacote (direcao.json) ou uma do sistema que o modelo aponta
        direcao = ("marca_" + x["slug"]) if os.path.isfile(os.path.join(m["dir"], "direcao.json")) else str(d.get("direcao_sugerida") or "")[:60]
        ds.MODELOS[chave] = {"nome": str(d.get("nome") or f"🎨 {x['nome']}")[:100], "descricao": str(d.get("descricao") or "")[:600],
                             "identidade_visual": x["slug"], "nome_canal": nome_canal, "formatos": formatos,
                             "regras": [str(r)[:500] for r in d.get("regras") or []][:40],  # v84_218: eram 20 (as últimas sumiam)
                             # 📣 v84_218: quantas chamadas o canal quer ({"inscreva": 1})
                             **({"chamadas": {k: int(v) for k, v in d["chamadas"].items() if k in ("inscreva", "venda") and str(v).isdigit()}}
                                if isinstance(d.get("chamadas"), dict) else {}),
                             **({"palavras_por_minuto": int(d["palavras_por_minuto"])} if d.get("palavras_por_minuto") else {}),
                             # 🎯 v84_367: vídeo explicativo (menos fatos por capítulo, sem ler a fonte em voz alta)
                             **({"escopo_enxuto": bool(d["escopo_enxuto"])} if "escopo_enxuto" in d else {}),
                             **({"direcao_sugerida": direcao} if direcao else {}),
                             # 🎭 v84_173: canal com personagens (falas multi voz, lore, histórico) e o roteiro exemplo do canal
                             **({"perfil_canal": x["slug"]} if os.path.isfile(os.path.join(m["dir"], "personagens.json")) else {}),
                             **_exemplo_do_modelo(m, d),
                             "do_pacote": True}
        feitos.append(chave)
    return feitos


def _exemplo_do_modelo(m: Dict[str, Any], d: Dict[str, Any]) -> Dict[str, Any]:
    """"roteiro_exemplo": "docs/roteiro_exemplo.md" no modelo_roteiro.json → o 📐 Roteiro exemplo já vem preenchido."""
    rel = str(d.get("roteiro_exemplo") or "").strip()
    if not rel:
        return {}
    try:
        with open(arquivo(m, rel), encoding="utf-8-sig") as f:
            texto = f.read()[:60000]
    except (OSError, MarcaErro):
        return {}
    modo = d.get("roteiro_exemplo_modo") if d.get("roteiro_exemplo_modo") in ("modelar", "inspirar") else "modelar"
    return {"referencia_padrao": texto, "referencia_modo_padrao": modo}


def exportar_pacote(m: Dict[str, Any], personagens: str = "aprovadas") -> bytes:
    """📦 A marca de volta em .zip no formato do pacote (sem os seus projetos e sem as células geradas).
    🧍 v84_188 `personagens`: "aprovadas" (padrão) leva junto as poses ✔ aprovadas (e a ⭐ mestre) das personagens
    conectadas na aba 🧍 Personagens — em outro PC, importar o zip recria os projetos já conectados; "tudo" leva
    também as que estão pra revisar; "nao" = só o pacote."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if personagens in ("aprovadas", "tudo"):
            try:
                import personagens_pod as _pp
                _pp.exportar_para_pacote(z, m, os.path.dirname(os.path.dirname(os.path.abspath(m["dir"]))),
                                         so_aprovadas=personagens == "aprovadas")
            except Exception:  # noqa: BLE001 — sem as personagens, o pacote sai igual
                pass
        tem_pacote = False
        for raiz, _dirs, fs in os.walk(m["dir"]):
            for f in sorted(fs):
                cam = os.path.join(raiz, f)
                rel = os.path.relpath(cam, m["dir"]).replace("\\", "/")
                if rel.startswith(("projetos/", "folha_mestra/celulas/")) or rel in ("estado.json", "lore_historico.json", "vozes_escolhidas.json", "personagens_ligados.json") or rel.endswith(".tmp"):
                    continue
                tem_pacote = tem_pacote or rel == "pacote.json"
                z.write(cam, f"{m['slug']}/{rel}")
        if not tem_pacote:
            p = m["guia"].get("project") or {}
            z.writestr(f"{m['slug']}/pacote.json", json.dumps({"formato": FORMATO_PACOTE, "versao": VERSAO_PACOTE, "slug": m["slug"],
                                                               "nome": p.get("name"), "idioma": p.get("channel_language")},
                                                              ensure_ascii=False, indent=1))
    return buf.getvalue()


# ------------------------------------------------------------------ 🧍 v84_185: as personagens PNG do canal
def personagens_png(m: Dict[str, Any]) -> List[Dict[str, Any]]:
    """As personagens do canal que têm JSON de poses (personagens/<slug>.json, apontado ou não pelo personagens.json)
    → [{slug, nome, arquivo (rel), poses, projeto (o id do projeto ligado na aba 🧍 Personagens ou None)}]."""
    pj = _json(os.path.join(m["dir"], "personagens.json"), {}) or {}
    por_slug = {str(p.get("slug") or ""): p for p in pj.get("personagens") or [] if isinstance(p, dict)}
    ligados = ligacoes_personagens(m)
    vistos, out = set(), []
    cand = [(str(p.get("poses_json") or ""), s) for s, p in por_slug.items() if p.get("poses_json")]
    pasta = os.path.join(m["dir"], "personagens")
    if os.path.isdir(pasta):
        cand += [("personagens/" + f, os.path.splitext(f)[0]) for f in sorted(os.listdir(pasta)) if f.lower().endswith(".json")]
    for rel, slug in cand:
        rel = rel.replace("\\", "/")
        if not rel or rel in vistos:
            continue
        try:
            cam = arquivo(m, rel)
        except MarcaErro:
            continue
        d = _json(cam)
        if not isinstance(d, dict) or not isinstance(d.get("poses"), list):
            continue
        vistos.add(rel)
        slug = _slugificar(d.get("personagem") or slug)
        info = por_slug.get(slug) or {}
        fichas = sorted(os.path.join(pasta, f) for f in (os.listdir(pasta) if os.path.isdir(pasta) else [])
                        if f.lower().startswith(slug + "_ficha") and f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")))
        out.append({"slug": slug, "nome": str(d.get("nome") or info.get("nome") or slug)[:60], "arquivo": rel,
                    "poses": len(d["poses"]), "projeto": ligados.get(slug), "fichas": fichas[:3]})
    return out


def ligacoes_personagens(m: Dict[str, Any]) -> Dict[str, str]:
    d = _json(os.path.join(m["dir"], "personagens_ligados.json"), {}) or {}
    return {str(k): str(v) for k, v in d.items() if isinstance(v, str)} if isinstance(d, dict) else {}


def ligar_personagem(m: Dict[str, Any], slug: str, projeto: Optional[str]) -> None:
    """Qual projeto da aba 🧍 Personagens é desta personagem do canal (None = desliga). Fica só neste PC."""
    d = ligacoes_personagens(m)
    slug = _slugificar(slug)
    if projeto:
        d[slug] = projeto
    else:
        d.pop(slug, None)
    _gravar(os.path.join(m["dir"], "personagens_ligados.json"), d)


def arquivo(m: Dict[str, Any], rel: str) -> str:
    """Caminho absoluto de um arquivo da marca (só dentro da pasta dela)."""
    alvo = os.path.abspath(os.path.join(m["dir"], os.path.normpath(rel)))
    if not alvo.startswith(os.path.abspath(m["dir"]) + os.sep):
        raise MarcaErro("Caminho fora da identidade visual.")
    return alvo


# ------------------------------------------------------------------ referências
def ref_pose(m: Dict[str, Any], pose: str) -> Optional[str]:
    """A melhor referência de uma pose: a célula APROVADA da folha mestra; senão o recorte do painel oficial."""
    cel = ((m["estado"].get("folha") or {}).get("celulas") or {})
    p = pose_info(m, pose)
    for cid in (pose, p["ref"]):
        c = cel.get(cid) or {}
        if c.get("status") == "aprovada" and c.get("arquivo") and os.path.isfile(arquivo(m, c["arquivo"])):
            return arquivo(m, c["arquivo"])
    cam = os.path.join(m["dir"], "referencias", "poses", f"pose_{p['ref']}.png")
    return cam if os.path.isfile(cam) else None


def folha_atual(m: Dict[str, Any], com_rotulos: bool = False) -> Optional[str]:
    f = m["estado"].get("folha_aprovada") or {}
    nome = f.get("rotulada" if com_rotulos else "limpa")
    if nome and os.path.isfile(arquivo(m, nome)):
        return arquivo(m, nome)
    v0 = os.path.join(m["dir"], "folha_mestra", "folha_mestra_v0_rotulada.png" if com_rotulos else "folha_mestra_v0_limpa.png")
    return v0 if os.path.isfile(v0) else None


def reforcos(m: Dict[str, Any]) -> Dict[str, str]:
    """reforcos.json da marca: o que a IA costuma errar, derivado do JSON e do desenho original (opcional)."""
    r = _json(os.path.join(m["dir"], "reforcos.json"), {}) or {}
    return {k: v for k, v in r.items() if isinstance(v, str)}


def poses_sugeridas(m: Dict[str, Any]) -> List[str]:
    r = _json(os.path.join(m["dir"], "poses_sugeridas.json"), {}) or {}
    return [str(x) for x in r.get("poses") or []][:200]


def referencias_para(m: Dict[str, Any], cena: Dict[str, Any], motor: str = "pod") -> List[Tuple[str, str]]:
    """[(papel, caminho)] na ordem em que vão pro gerador. Klein: até 4. Flow: 1 (a mais importante)."""
    refs: List[Tuple[str, str]] = []
    if cena.get("mascote"):
        rp = ref_pose(m, cena["mascote"])
        if rp:
            refs.append(("mascote_pose", rp))
        prop = os.path.join(m["dir"], "referencias", "mascote_proporcoes.png")
        if os.path.isfile(prop):  # quadros do desenho original: a proporção de verdade (pernas compridas, cabeça pequena)
            refs.append(("mascote_proporcoes", prop))
        fl = folha_atual(m)
        if fl:
            refs.append(("folha_mestra", fl))
        if not os.path.isfile(prop):
            alta = os.path.join(m["dir"], "referencias", "mascote_alta_res_tronco.png")
            if os.path.isfile(alta):
                refs.append(("mascote_alta_res", alta))
    for papel, cam in refs_personagens(m, cena.get("personagens")):  # 🎭 v84_173: cada personagem com a ficha dela
        refs.append((papel, cam))
    for k, extra in enumerate(cena.get("refs_extras") or []):  # 📷 fotos suas: pessoa/objeto real da história
        if extra and os.path.isfile(extra):
            refs.append((f"foto_{k + 1}", extra))
    if cena.get("ref_estilo") and len(refs) < 4:
        est = os.path.join(m["dir"], "referencias", "estilo_colagem_dir.png")
        if os.path.isfile(est):
            refs.append(("estilo", est))
    if motor == "flow":  # 1 referência só: a sua foto quando a cena é sobre ela; senão a pose do mascote / a dupla
        fotos = [r for r in refs if r[0].startswith("foto_")]
        if fotos and (cena.get("tipo_imagem") != "mascote" or not cena.get("mascote")) and not cena.get("personagens"):
            return fotos[:1]
        dupla = [r for r in refs if r[0] == "personagens_dupla"]
        return (dupla or refs)[:1]
    # o klein aceita 4: as fotos suas têm prioridade sobre a 2ª/3ª referência do mascote
    if len(refs) > 4:
        fotos = [r for r in refs if r[0].startswith("foto_")]
        resto = [r for r in refs if not r[0].startswith("foto_")]
        refs = resto[:max(1, 4 - len(fotos))] + fotos
    return refs[:4]


def perfil_de(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        import canal_perfil
        return canal_perfil.carregar(os.path.dirname(os.path.dirname(os.path.abspath(m["dir"]))), m["slug"])
    except Exception:  # noqa: BLE001
        return None


def _slugs_personagens(lista: Any) -> List[Dict[str, str]]:
    out = []
    for x in lista or []:
        if isinstance(x, str):
            x = {"slug": x}
        if isinstance(x, dict) and x.get("slug"):
            import canal_perfil
            out.append({"slug": canal_perfil._slug(x["slug"]), "acao_en": str(x.get("acao_en") or x.get("acao") or "")[:300]})
    return out[:3]


def refs_personagens(m: Dict[str, Any], lista: Any) -> List[Tuple[str, str]]:
    """As fichas das personagens da cena (a 1ª referência de cada uma) + a ficha da dupla quando são 2+."""
    pers = _slugs_personagens(lista)
    if not pers:
        return []
    perfil = perfil_de(m) or {}
    por = {p["slug"]: p for p in perfil.get("personagens") or []}
    refs: List[Tuple[str, str]] = []
    for x in pers:
        p = por.get(x["slug"])
        for rel in (p or {}).get("referencias") or []:
            try:
                cam = arquivo(m, rel)
            except MarcaErro:
                continue
            if os.path.isfile(cam):
                refs.append((f"personagem_{x['slug']}", cam))
                break
    if len(pers) >= 2:
        import json as _j
        pj = _json(os.path.join(m["dir"], "personagens.json"), {}) or {}
        for rel in pj.get("referencias_dupla") or []:
            try:
                cam = arquivo(m, rel)
            except MarcaErro:
                continue
            if os.path.isfile(cam):
                refs.append(("personagens_dupla", cam))
                break
    return refs


def texto_personagens(m: Dict[str, Any], lista: Any) -> Tuple[str, str]:
    """(o bloco "MASCOT/CHARACTERS" do prompt, o que evitar) pras personagens da cena — o lock de cada uma + o estilo
    simplificado das personagens do canal."""
    pers = _slugs_personagens(lista)
    if not pers:
        return "", ""
    perfil = perfil_de(m) or {}
    pj = _json(os.path.join(m["dir"], "personagens.json"), {}) or {}
    por = {p["slug"]: p for p in perfil.get("personagens") or []}
    partes, evitar = [], []
    for x in pers:
        p = por.get(x["slug"]) or {}
        nome = p.get("nome") or x["slug"]
        partes.append(f"{nome.upper()}: {p.get('visual_en') or nome}" + (f" Action: {x['acao_en']}." if x.get("acao_en") else ""))
        if p.get("evitar_en"):
            evitar.append(p["evitar_en"])
    so = "exactly ONE character" if len(pers) == 1 else f"exactly {len(pers)} characters, clearly separated silhouettes, do not merge features or outfits"
    estilo = pj.get("estilo_personagens_en") or ""
    return (f"include {so}. " + " ".join(partes) + (f" {estilo}" if estilo else ""), ", ".join(evitar))


_DESC_REF = {"mascote_pose": "the recurring mascot in the target pose (copy its exact design)",
             "folha_mestra": "the mascot master character sheet (canonical design: silhouette, eyes, cream body, outline)",
             "mascote_alta_res": "a high-resolution close view of the same mascot (linework and texture)",
             "mascote_proporcoes": "frames from the ORIGINAL vintage cartoon showing the mascot's true proportions (tiny head, thin curved body, extremely long rubber-hose legs, big shoes) — match these proportions exactly",
             "silhueta": "the mascot's canonical silhouette shape",
             "personagens_dupla": "the canonical sheet of the recurring characters together (relationship and body language)",
             "estilo": "a brand style sample (palette, paper texture and collage language only — do not copy its objects)"}


# ------------------------------------------------------------------ prompt (templates do JSON)
def _preencher(template: str, valores: Dict[str, str]) -> str:
    """Troca "RÓTULO: [instrução]" do template pelo valor (os templates do JSON usam colchetes)."""
    out = template
    for rotulo, valor in valores.items():
        out = re.sub(re.escape(rotulo) + r":\s*\[[^\]]*\]", lambda _m, v=valor: f"{rotulo}: {v}", out)
    return out


def _desc_ref(m: Dict[str, Any], papel: str) -> str:
    if papel.startswith("personagem_"):
        slug = papel[len("personagem_"):]
        p = next((x for x in (perfil_de(m) or {}).get("personagens") or [] if x["slug"] == slug), {})
        return f"the canonical character sheet of {p.get('nome') or slug} (copy this exact design: face, hair, eyes, marks, outfit, accessories)"
    return _DESC_REF.get(papel, "a photo of the real subject of this scene")


SEM_TEXTO = ("No words and no letters in the image: no captions, no titles, no questions, no labels, no arrows, no numbers, "
             "no watermark, no logo (real printed text only on an object of the scene, like a book page, a poster or a sign).")


def montar_prompt(m: Dict[str, Any], cena: Dict[str, Any], refs: Optional[List[Tuple[str, str]]] = None) -> str:
    """O prompt final (passo 3 do pipeline): template + style_lock + prompt_lock do mascote + cores + "Avoid:"."""
    g = m["guia"]
    gs = g.get("generation_system") or {}
    ms = g.get("mascot") or {}
    tipo = cena.get("tipo") or "cena"
    estilo = gs.get("style_lock_en") or ""
    mascote = cena.get("mascote") or ""
    acao = (cena.get("acao_mascote_en") or (pose_info(m, mascote).get("en") if mascote else "") or "").strip()
    if tipo == "folha":
        p = (f"Character model sheet cell for the channel mascot: {cena.get('assunto_en') or acao}. One single mascot, full body, "
             f"centered, on a plain dark charcoal paper background with subtle aged texture and soft vignette, generous empty space "
             f"around it. {ms.get('prompt_lock_en', '')} {reforcos(m).get('mascote_en', '')} Vintage 2D rubber-hose cartoon linework, flat cream body, black outline, "
             f"subtle print speckles. Restricted palette: near-black, charcoal, aged cream #E8DDC5. No text, no labels, no frame, no other objects.")
    elif tipo == "thumbnail":
        p = _preencher(gs.get("thumbnail_prompt_template_en") or "", {})
        p = p.replace("[topic]", cena.get("assunto_en") or "").replace(
            "[one surprising object, contrast or phenomenon]", cena.get("pergunta_visual_en") or cena.get("assunto_en") or "")
        if mascote:
            p += f" Mascot action: {acao}. {ms.get('prompt_lock_en', '')} {reforcos(m).get('mascote_en', '')}"
    else:
        # a trava do mascote vem cedo no prompt (o klein/Z-Image leem ~512 tokens; o "Avoid:" do fim pode ser cortado)
        evitar = reforcos(m).get("evitar_en")
        mascote_txt = (f"include the recurring mascot ({acao}). {ms.get('prompt_lock_en', '')} {reforcos(m).get('mascote_en', '')}"
                       f"{' The mascot is never: ' + evitar + '.' if evitar else ''}" if mascote else "no mascot in this frame")
        pers_txt, pers_evitar = texto_personagens(m, cena.get("personagens"))
        if pers_txt:  # 🎭 v84_173: as personagens do canal nesta cena (com a ficha de cada uma como referência)
            mascote_txt = pers_txt if not mascote else f"{mascote_txt} Also {pers_txt}"

        # 🖼 v84_191: o prompt em PROSA, sem rótulos ("VISUAL QUESTION:", "BRAND STYLE:", "MASCOT:") — o gerador desenhava
        # esses rótulos e a pergunta como texto na imagem, e "no mascot" fazia aparecer um mascote
        assunto = (cena.get("assunto_en") or cena.get("narracao") or "").strip().rstrip(".")
        compo = (cena.get("composicao_en") or gs.get("default_composition_en") or "one clear focal point, quiet negative space").strip().rstrip(".")
        partes_p = [f"A single 16:9 still image: {assunto}.", f"Framing: {compo}."]
        if mascote or pers_txt:
            partes_p.append(mascote_txt.strip().rstrip(".") + ".")
        partes_p.append(estilo)
        partes_p.append(SEM_TEXTO)
        p = " ".join(x for x in partes_p if x)
        tipo_img = cena.get("tipo_imagem") or ""
        tipos_en = dict(TIPOS_IMAGEM_EN, **{k: str(v) for k, v in (gs.get("image_types_en") or {}).items()
                                            if k in TIPOS_IMAGEM_EN and str(v or "").strip()})
        if tipo_img and tipo_img in tipos_imagem_da_marca(m) and tipo_img != "mascote":
            p += f" Image type: {tipos_en[tipo_img]}."
        infos = cena.get("fotos_info") or [{} for _ in cena.get("refs_extras") or []]
        for k, fi in enumerate(infos, 1):  # 📷 a pessoa/animal/estátua/objeto real: as características + como desenhar
            desc = (fi.get("descricao_en") or "").strip()
            # v84_367: o brand_guide pode dizer como a pessoa/objeto real da foto entra (ex.: canal realista em cores)
            como = (str(gs.get("real_subject_render_en")).strip().rstrip(".") if str(gs.get("real_subject_render_en") or "").strip() else
                    "redrawn as a vintage hand-inked editorial illustration in the brand style, keeping every recognizable feature"
                    if fi.get("estilo") == "ilustracao" or tipo_img == "ilustracao" else
                    "rendered as a grayscale archival photograph with film grain, keeping every recognizable feature")
            idx = next((i + 1 for i, (papel, _c) in enumerate(refs or []) if papel == f"foto_{k}"), 0)
            onde = f"image {idx}" if idx else "the real subject"
            if fi.get("frase"):
                p += f" For {onde}: {fi['frase']}; {como}, matching the brand palette."
            else:
                p += f" Real subject {k}{' (' + desc + ')' if desc else ''} from the photo reference, {como}, matching the brand palette."
    if refs:
        p = " ".join(f"Image {k + 1} is {_desc_ref(m, papel)}."
                     for k, (papel, _c) in enumerate(refs)) + " " + p
    neg = gs.get("negative_prompt_global_en") or ""
    if mascote or tipo == "folha":
        neg = ", ".join(x for x in (neg, ms.get("negative_prompt_en") or "", reforcos(m).get("evitar_en") or "") if x)
    if tipo not in ("folha", "thumbnail") and cena.get("personagens"):
        _t, pe = texto_personagens(m, cena.get("personagens"))
        neg = ", ".join(x for x in (neg, pe) if x)
    if neg:
        p += f" Avoid: {neg}."
    return " ".join(p.split())


# ------------------------------------------------------------------ paleta: validar e corrigir
def _hex(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def paleta(m: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(c, rgb=_hex(c["hex"])) for c in (m["guia"].get("design_system") or {}).get("palette") or []]


_PAPEIS = ("ink_black", "charcoal", "archive_gray", "aged_paper", "chalk_white", "signal_red", "deep_red")


def _pal(m: Optional[Dict[str, Any]]) -> Dict[str, Tuple[int, int, int]]:
    """As cores da marca por PAPEL (fundo mais escuro, carvão, cinza, papel claro, branco, acento e acento escuro).
    Com os tokens do guia quando ele usa esses nomes; senão, pela luminância/saturação de cada cor da paleta."""
    if not m:
        return {}
    cores = paleta(m)
    por_token = {c["token"]: c["rgb"] for c in cores if c.get("token")}
    if all(k in por_token for k in _PAPEIS[:4]) and "signal_red" in por_token:
        return {**{k: v for k, v in por_token.items() if k in _PAPEIS}, **por_token}

    def hsv(rgb):
        return colorsys.rgb_to_hsv(*(x / 255 for x in rgb))
    neutras = sorted([c["rgb"] for c in cores if hsv(c["rgb"])[1] < 0.3], key=lambda c: sum(c))
    acentos = sorted([c["rgb"] for c in cores if hsv(c["rgb"])[1] >= 0.3], key=lambda c: -sum(c))
    out: Dict[str, Tuple[int, int, int]] = {}
    if neutras:
        out["ink_black"] = neutras[0]
        out["charcoal"] = neutras[1] if len(neutras) > 2 else neutras[0]
        out["archive_gray"] = neutras[len(neutras) // 2]
        out["aged_paper"] = neutras[-2] if len(neutras) > 2 else neutras[-1]
        out["chalk_white"] = neutras[-1]
    if acentos:
        out["signal_red"] = acentos[0]
        out["deep_red"] = acentos[-1]
    return out


def _matiz_acento(m: Optional[Dict[str, Any]]) -> float:
    c = _pal(m).get("signal_red")
    return colorsys.rgb_to_hsv(*(x / 255 for x in c))[0] * 360 if c else 357.0


def _cores_permitidas(m: Optional[Dict[str, Any]]) -> List[Tuple[float, Tuple[int, int, int], float]]:
    """As cores SATURADAS da paleta (matiz, rgb, luminância): no Dinge erklären só os vermelhos; numa marca com azul e
    dourado (ex.: ASTRANEBEL), esses também. Sem paleta: o vermelho."""
    out = []
    for c in paleta(m) if m else []:
        hh, ss, vv = colorsys.rgb_to_hsv(*(x / 255 for x in c["rgb"]))
        if ss >= 0.25 and vv >= 0.2:
            out.append((hh * 360, tuple(c["rgb"]), 0.2126 * c["rgb"][0] / 255 + 0.7152 * c["rgb"][1] / 255 + 0.0722 * c["rgb"][2] / 255))
    return out or [(357.0, (197, 31, 39), 0.25)]


def _dist_matiz(h, alvo: float):
    import numpy as np
    d = np.abs(h - alvo)
    return np.minimum(d, 360 - d)


def validar_paleta(caminho_ou_img: Any, m: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Confere as palette_rules do JSON: só preto/carvão/cinza/creme + vermelho de sinalização.
    Mede (numa miniatura): % de pixels de cor proibida (azul, verde, roxo, amarelo vivo), % de vermelho, % de escuro,
    saturação média fora do vermelho. Devolve score 0–100, status (aprovada/revisar/reprovar) e os problemas."""
    import numpy as np
    from PIL import Image
    im = caminho_ou_img if hasattr(caminho_ou_img, "convert") else Image.open(caminho_ou_img)
    im = im.convert("RGB")
    im.thumbnail((200, 200))
    a = np.asarray(im).astype("float32") / 255.0
    mx, mn = a.max(axis=2), a.min(axis=2)
    v = mx
    s = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    d = np.maximum(mx - mn, 1e-6)
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60.0
    colorido = (s > 0.32) & (v > 0.22)
    ha = _matiz_acento(m)  # a cor de sinalização da marca (no Dinge erklären, o vermelho)
    vermelho = colorido & (_dist_matiz(h, ha) < 30)
    perto_paleta = np.zeros_like(colorido)
    for hp, _rgb, _l in _cores_permitidas(m):  # 🎨 v84_173: as cores saturadas DA marca valem (azul, dourado…)
        perto_paleta |= _dist_matiz(h, hp) < 25
    laranja_creme = (s <= 0.42) & (h >= 18) & (h <= 65)  # creme/sépia/papel (permitido)
    proibido = colorido & ~vermelho & ~perto_paleta & ~(laranja_creme)
    frio = ~((h >= 18) & (h <= 65)) & (v > 0.2) & ~vermelho & ~perto_paleta  # fora das cores da marca: deveria ser neutro
    total = float(a.shape[0] * a.shape[1])
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    met = {"proibida_pct": round(float(proibido.sum()) / total * 100, 1), "vermelho_pct": round(float(vermelho.sum()) / total * 100, 1),
           "escuro_pct": round(float((lum < 0.18).sum()) / total * 100, 1),
           "creme_pct": round(float(((lum > 0.62) & (s < 0.3)).sum()) / total * 100, 1),
           "saturacao_fora_vermelho": round(float(s[frio].mean()) if frio.any() else 0.0, 3)}
    problemas, pontos = [], 100.0
    if met["proibida_pct"] > 1.5:
        pontos -= min(60, met["proibida_pct"] * 6)
        problemas.append(f"{met['proibida_pct']}% de cor fora da paleta da marca")
    if met["vermelho_pct"] > 22:
        pontos -= min(30, (met["vermelho_pct"] - 22) * 2)
        problemas.append(f"cor de destaque demais ({met['vermelho_pct']}% — é cor de sinalização, pouca área)")
    if met["escuro_pct"] < 30:
        pontos -= min(30, (30 - met["escuro_pct"]) * 1.2)
        problemas.append(f"pouco escuro ({met['escuro_pct']}% — a paleta da marca é dominada pelos tons escuros)")
    if met["saturacao_fora_vermelho"] > 0.28:
        pontos -= 15
        problemas.append("imagem colorida demais fora das cores da marca (o resto deve ficar neutro/dessaturado)")
    pontos = max(0, round(pontos))
    status = "aprovada" if pontos >= 80 and not met["proibida_pct"] > 4 else ("revisar" if pontos >= 50 else "reprovar")
    return {"score": pontos, "status": status, "problemas": problemas, "metricas": met}


def gradear(origem: str, destino: str, m: Optional[Dict[str, Any]] = None, grao: float = 0.04) -> str:
    """🎞 Preset noir_vermelho_v1 (passo 6): tons mapeados na escala da paleta (preto → carvão → cinza → creme), só o
    vermelho que já existia fica (puxado pro #C51F27 / #74171B), grão de filme leve e vinheta. Sobre o original, nunca
    no lugar dele."""
    import numpy as np
    from PIL import Image
    pal = _pal(m)
    escala = [pal.get("ink_black", (8, 8, 7)), pal.get("charcoal", (33, 30, 27)), pal.get("archive_gray", (119, 113, 106)),
              pal.get("aged_paper", (232, 221, 197)), pal.get("chalk_white", (243, 235, 221))]
    pontos = [0.0, 0.22, 0.52, 0.86, 1.0]
    sinal = np.array(pal.get("signal_red", (197, 31, 39)), "float32")
    fundo = np.array(pal.get("deep_red", (116, 23, 27)), "float32")
    im = Image.open(origem).convert("RGB")
    a = np.asarray(im).astype("float32") / 255.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    # contraste levemente mais alto (luz de alto contraste do guia)
    lum = np.clip((lum - 0.5) * 1.12 + 0.5, 0, 1)
    out = np.zeros_like(a)
    for c in range(3):
        out[..., c] = np.interp(lum, pontos, [e[c] / 255.0 for e in escala])
    mx, mn = a.max(axis=2), a.min(axis=2)
    s = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0)
    d = np.maximum(mx - mn, 1e-6)
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60.0
    # 🎨 v84_173: as cores saturadas DA marca ficam, puxadas pra cor mais parecida da paleta (no Dinge: só os vermelhos)
    cores = _cores_permitidas(m)
    dist = np.stack([_dist_matiz(h, hp) for hp, _c, _l in cores])                      # (n, H, W)
    score = dist + np.stack([np.abs(lum - lc) * 60 for _h, _c, lc in cores])           # matiz + luminância
    score = np.where(dist < 25, score, 1e9)
    idx = np.argmin(score, axis=0)
    perto = (dist.min(axis=0) < 22).astype("float32")
    peso = np.clip((s - 0.3) / 0.25, 0, 1) * perto * np.clip((mx - 0.18) / 0.2, 0, 1)
    paleta_rgb = np.array([c for _h, c, _l in cores], "float32") / 255.0
    alvo = paleta_rgb[idx]
    del sinal, fundo
    out = out * (1 - peso[..., None]) + alvo * peso[..., None]
    hh, ww = lum.shape
    yy, xx = np.mgrid[0:hh, 0:ww]
    vinheta = 1 - 0.35 * (((xx - ww / 2) / (ww / 2)) ** 2 + ((yy - hh / 2) / (hh / 2)) ** 2) / 2
    out *= np.clip(vinheta, 0.6, 1)[..., None]
    if grao:
        rng = np.random.default_rng(7)
        out += rng.normal(0, grao, size=(hh, ww, 1)).astype("float32")
    Image.fromarray((np.clip(out, 0, 1) * 255).astype("uint8")).save(destino)
    return destino


# ------------------------------------------------------------------ textos no idioma do canal (pós-produção)
def _fonte(base: str, tipo: str, tamanho: int):
    from PIL import ImageFont
    for cam in (os.path.join(base, FONTES.get(tipo, FONTES["etiqueta"])), os.path.join(base, "assets/fonts/DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(cam, tamanho)
        except OSError:
            continue
    return ImageFont.load_default()


def _tira_de_papel(draw_img, caixa, cor, seed: int):
    """Recorte de papel com bordas rasgadas (polígono irregular)."""
    import random
    from PIL import ImageDraw
    rnd = random.Random(seed)
    x0, y0, x1, y1 = caixa
    pts = []
    passo = 9
    x = x0
    while x <= x1:
        pts.append((x, y0 + rnd.uniform(-3, 3)))
        x += passo
    y = y0
    while y <= y1:
        pts.append((x1 + rnd.uniform(-3, 3), y))
        y += passo
    x = x1
    while x >= x0:
        pts.append((x, y1 + rnd.uniform(-3, 3)))
        x -= passo
    y = y1
    while y >= y0:
        pts.append((x0 + rnd.uniform(-3, 3), y))
        y -= passo
    ImageDraw.Draw(draw_img).polygon(pts, fill=cor)


def aplicar_textos(origem: str, destino: str, elementos: List[Dict[str, Any]], m: Optional[Dict[str, Any]] = None,
                   base: str = ".") -> str:
    """✍️ Passo 7: títulos e anotações em ALEMÃO por cima da imagem limpa, no estilo do guia — tiras de papel creme
    rasgado com letra de máquina de escrever (etiquetas) ou slab pesada (manchete); *palavra* = palavra-chave em
    vermelho; círculos e setas vermelhos à mão. Elementos:
      {"tipo": "manchete"|"etiquetas", "linhas": ["Keine", "*eindeutigen*", "Spuren"], "pos": "direita"|"esquerda"|"centro"|"baixo"|[x, y]}
      {"tipo": "circulo", "x": 0.6, "y": 0.4, "r": 0.08}      {"tipo": "seta", "de": [0.3, 0.5], "para": [0.55, 0.45]}"""
    import math as _m
    import random
    from PIL import Image, ImageDraw, ImageFilter
    pal = _pal(m)
    creme = pal.get("aged_paper", (232, 221, 197))
    preto = pal.get("ink_black", (8, 8, 7))
    vermelho = pal.get("signal_red", (197, 31, 39))
    im = Image.open(origem).convert("RGBA")
    W, H = im.size
    camada = Image.new("RGBA", im.size, (0, 0, 0, 0))
    for k, el in enumerate(elementos or []):
        tipo = el.get("tipo") or "etiquetas"
        if tipo in ("manchete", "etiquetas"):
            linhas = [str(x) for x in (el.get("linhas") or []) if str(x).strip()][:6]
            if not linhas:
                continue
            tam = int(H * (0.085 if tipo == "manchete" else 0.05) * float(el.get("escala") or 1))
            fonte = _fonte(base, "manchete" if tipo == "manchete" else "etiqueta", tam)
            medidas = []
            for ln in linhas:
                txt = ln.replace("*", "")
                bb = fonte.getbbox(txt)
                larg_txt = sum(fonte.getlength(pt.strip("*") if pt.startswith("*") and pt.endswith("*") else pt)
                               for pt in re.split(r"(\*[^*]+\*)", ln) if pt)
                medidas.append((ln, txt, int(math.ceil(larg_txt)) + 2, bb[3] - bb[1], bb))
            pad_x, pad_y, gap = int(tam * 0.45), int(tam * 0.28), int(tam * 0.22)
            alt_total = sum(md[3] + 2 * pad_y for md in medidas) + gap * (len(medidas) - 1)
            larg_max = max(md[2] for md in medidas) + 2 * pad_x
            pos = el.get("pos") or "direita"
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                x0, y0 = int(float(pos[0]) * W), int(float(pos[1]) * H)
            else:
                x0 = {"esquerda": int(W * 0.06), "centro": (W - larg_max) // 2, "baixo": (W - larg_max) // 2}.get(pos, int(W * 0.94) - larg_max)
                y0 = {"baixo": int(H * 0.92) - alt_total}.get(pos, (H - alt_total) // 2)
            y = y0
            rnd = random.Random(k * 31 + 7)
            for j, (ln, txt, tw, th, bb) in enumerate(medidas):
                tira = Image.new("RGBA", (tw + 2 * pad_x + 12, th + 2 * pad_y + 12), (0, 0, 0, 0))
                destaque_inteiro = ln.startswith("*") and ln.endswith("*") and ln.count("*") == 2 and el.get("destaque_em_tira")
                _tira_de_papel(tira, (6, 6, tw + 2 * pad_x + 6, th + 2 * pad_y + 6), (*(vermelho if destaque_inteiro else creme), 255), k * 97 + j)
                dt = ImageDraw.Draw(tira)
                cx = 6 + pad_x
                partes = re.split(r"(\*[^*]+\*)", ln)
                for parte in partes:
                    if not parte:
                        continue
                    red = parte.startswith("*") and parte.endswith("*") and len(parte) > 2
                    t = parte[1:-1] if red else parte
                    cor = creme if destaque_inteiro else (vermelho if red else preto)
                    dt.text((cx, 6 + pad_y - bb[1]), t, font=fonte, fill=(*cor, 255))
                    cx += fonte.getlength(t)
                ang = rnd.uniform(-2.2, 2.2)
                tira = tira.rotate(ang, resample=Image.BICUBIC, expand=True)
                sombra = Image.new("RGBA", tira.size, (0, 0, 0, 0))
                sombra.putalpha(tira.getchannel("A").point(lambda a: int(a * 0.55)))
                sombra = sombra.filter(ImageFilter.GaussianBlur(5))
                desloc = rnd.randint(-int(tam * 0.15), int(tam * 0.15)) if tipo == "etiquetas" else 0
                camada.alpha_composite(sombra, (max(0, x0 + desloc + 4), max(0, y + 6)))
                camada.alpha_composite(tira, (max(0, x0 + desloc), max(0, y)))
                y += th + 2 * pad_y + gap
        elif tipo == "circulo":
            d = ImageDraw.Draw(camada)
            cx, cy, rr = float(el.get("x", .5)) * W, float(el.get("y", .5)) * H, float(el.get("r", .08)) * H
            larg = max(3, int(H * 0.0075))
            rnd = random.Random(k)
            pts = [(cx + rr * (1 + rnd.uniform(-.04, .04)) * _m.cos(t / 40 * 2 * _m.pi * 1.06),
                    cy + rr * 0.92 * (1 + rnd.uniform(-.04, .04)) * _m.sin(t / 40 * 2 * _m.pi * 1.06)) for t in range(41)]
            d.line(pts, fill=(*vermelho, 235), width=larg, joint="curve")
        elif tipo == "seta":
            d = ImageDraw.Draw(camada)
            (xa, ya), (xb, yb) = el.get("de") or (.3, .5), el.get("para") or (.5, .5)
            xa, ya, xb, yb = xa * W, ya * H, xb * W, yb * H
            larg = max(3, int(H * 0.0075))
            mxp, myp = (xa + xb) / 2, (ya + yb) / 2 - abs(xb - xa) * 0.15
            pts = [((1 - t) ** 2 * xa + 2 * (1 - t) * t * mxp + t ** 2 * xb, (1 - t) ** 2 * ya + 2 * (1 - t) * t * myp + t ** 2 * yb)
                   for t in [i / 24 for i in range(25)]]
            d.line(pts, fill=(*vermelho, 235), width=larg, joint="curve")
            ang = _m.atan2(yb - pts[-3][1], xb - pts[-3][0])
            ponta = H * 0.03
            for lado in (2.6, -2.6):
                d.line([(xb, yb), (xb + ponta * _m.cos(ang + lado), yb + ponta * _m.sin(ang + lado))], fill=(*vermelho, 235), width=larg)
    im.alpha_composite(camada)
    im.convert("RGB").save(destino)
    return destino


# ------------------------------------------------------------------ folha mestra
def montar_folha(m: Dict[str, Any], celulas: List[Tuple[str, str]], destino: str, rotulos: bool, base: str = ".",
                 titulo: str = "") -> str:
    """Junta as células [(rótulo, caminho)] numa folha 16:9 sobre o preto do guia. A versão SEM rótulos é a que vai
    como referência pra IA (texto na referência vaza pra imagem gerada)."""
    from PIL import Image, ImageDraw
    pal = _pal(m)
    W, H = 2400, 1350
    folha = Image.new("RGB", (W, H), pal.get("ink_black", (8, 8, 7)))
    d = ImageDraw.Draw(folha)
    n = len(celulas)
    cols = min(6, max(3, math.ceil(math.sqrt(n * 16 / 9))))
    linhas = math.ceil(n / cols)
    topo = 90 if (rotulos and titulo) else 30
    rot_h = 46 if rotulos else 0
    cw, ch = (W - 40) // cols, (H - topo - 20) // linhas
    fonte = _fonte(base, "etiqueta", 30)
    if rotulos and titulo:
        d.text((30, 25), titulo, font=_fonte(base, "manchete", 46), fill=pal.get("aged_paper", (232, 221, 197)))
    for k, (rot, cam) in enumerate(celulas):
        col, lin = k % cols, k // cols
        x, y = 20 + col * cw, topo + lin * ch
        d.rectangle((x + 6, y + 6, x + cw - 6, y + ch - 6), fill=pal.get("charcoal", (33, 30, 27)))
        try:
            c = Image.open(cam).convert("RGB")
        except OSError:
            continue
        esc = min((cw - 24) / c.width, (ch - 24 - rot_h) / c.height)
        c = c.resize((max(1, int(c.width * esc)), max(1, int(c.height * esc))), Image.LANCZOS)
        folha.paste(c, (x + (cw - c.width) // 2, y + 12 + (ch - 24 - rot_h - c.height) // 2))
        if rotulos:
            bb = fonte.getbbox(rot.upper())
            d.text((x + (cw - (bb[2] - bb[0])) // 2, y + ch - 12 - rot_h + 6), rot.upper(), font=fonte,
                   fill=pal.get("aged_paper", (232, 221, 197)))
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    folha.save(destino)
    return destino


def estado_folha(m: Dict[str, Any]) -> Dict[str, Any]:
    f = m["estado"].setdefault("folha", {})
    f.setdefault("celulas", {})
    f.setdefault("versao", 0)
    return f


def compor_folha_aprovada(m: Dict[str, Any], base: str = ".") -> Dict[str, Any]:
    """Quando as células estão aprovadas: monta a folha mestra vN (limpa + rotulada) e passa a usá-la como referência."""
    f = estado_folha(m)
    aprovadas = [(c["nome"], arquivo(m, f["celulas"][c["id"]]["arquivo"])) for c in CELULAS_FOLHA
                 if (f["celulas"].get(c["id"]) or {}).get("status") == "aprovada"]
    vistas = sum(1 for c in CELULAS_FOLHA[:4] if (f["celulas"].get(c["id"]) or {}).get("status") == "aprovada")
    poses = len(aprovadas) - vistas
    if vistas < 3 or poses < 6:
        raise MarcaErro(f"Faltam células aprovadas: {vistas} de 3+ vistas (frente, perfil, três quartos, silhueta) e "
                        f"{poses} de 6+ poses/expressões (o protocolo de consistência do guia pede isso).")
    v = int(f.get("versao") or 0) + 1
    nome = (m["guia"].get("project") or {}).get("name") or m["slug"]
    limpa = montar_folha(m, aprovadas, os.path.join(m["dir"], "folha_mestra", f"folha_mestra_v{v}_limpa.png"), False, base)
    rot = montar_folha(m, aprovadas, os.path.join(m["dir"], "folha_mestra", f"folha_mestra_v{v}_rotulada.png"), True, base,
                       titulo=f"{nome} — folha mestra do mascote v{v}")
    f["versao"] = v
    m["estado"]["folha_aprovada"] = {"versao": v, "limpa": os.path.relpath(limpa, m["dir"]), "rotulada": os.path.relpath(rot, m["dir"]),
                                     "quando": time.time(), "celulas": [c for c, _ in aprovadas]}
    salvar_estado(m)
    return m["estado"]["folha_aprovada"]


# ------------------------------------------------------------------ projetos (um vídeo = batidas da narração)
def _pasta_proj(m: Dict[str, Any], pid: str = "") -> str:
    if pid and not re.fullmatch(r"[0-9a-f]{10}", pid):
        raise MarcaErro("Projeto inválido.")
    return os.path.join(m["dir"], "projetos", pid) if pid else os.path.join(m["dir"], "projetos")


def criar_projeto(m: Dict[str, Any], titulo: str, narracao: str, origem: Optional[Dict[str, str]] = None,
                  motor: str = "pod", proporcao: str = "16:9") -> Dict[str, Any]:
    pid = uuid.uuid4().hex[:10]
    p = {"id": pid, "titulo": " ".join(str(titulo or "").split())[:160] or "Vídeo", "criado": time.time(), "atualizado": time.time(),
         "narracao": str(narracao or "")[:200000], "origem": origem or {}, "motor": motor if motor in MOTORES else "pod",
         "proporcao": proporcao if proporcao in ("16:9", "9:16", "1:1") else "16:9", "batidas": [], "fotos": [],
         "sem_mascote_no_zimage": True, "versoes": m["versoes"]}
    salvar_projeto(m, p)
    return p


def carregar_projeto(m: Dict[str, Any], pid: str) -> Dict[str, Any]:
    p = _json(os.path.join(_pasta_proj(m, pid), "projeto.json"))
    if not isinstance(p, dict):
        raise MarcaErro("Projeto não encontrado.")
    return p


def salvar_projeto(m: Dict[str, Any], p: Dict[str, Any]) -> None:
    p["atualizado"] = time.time()
    _gravar(os.path.join(_pasta_proj(m, p["id"]), "projeto.json"), p)


def listar_projetos(m: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    raiz = _pasta_proj(m)
    if os.path.isdir(raiz):
        for pid in os.listdir(raiz):
            try:
                p = carregar_projeto(m, pid)
            except MarcaErro:
                continue
            bs = p.get("batidas") or []
            out.append({"id": pid, "titulo": p["titulo"], "atualizado": p.get("atualizado") or 0, "batidas": len(bs),
                        "aprovadas": sum(1 for b in bs if b.get("qa_status") == "approved"),
                        "geradas": sum(1 for b in bs if b.get("arquivo_master"))})
    return sorted(out, key=lambda x: -x["atualizado"])


def prompt_batidas(m: Dict[str, Any], narracao: str, alvo: int = 0, elenco: Optional[Dict[str, Any]] = None) -> str:
    """Passos 1–2: a IA divide a narração em batidas visuais e escolhe o tipo de imagem, o mascote e os textos alemães."""
    g = m["guia"]
    p = g.get("project") or {}
    ms = g.get("mascot") or {}
    poses = "; ".join(f"{k} = {v['en']}" for k, v in todas_poses(m).items())
    n_alvo = alvo or max(6, min(80, round(len(narracao.split()) / 28)))
    _pp = _bloco_personagens_batidas(m)
    return f"""Você é diretor de arte do canal “{p.get('name')}” ({p.get('channel_language')}). Posicionamento: {p.get('positioning')}
Regra editorial: {p.get('editorial_rule')}

Divida a NARRAÇÃO abaixo em cerca de {n_alvo} batidas visuais (uma imagem 16:9 por batida, na ordem, cobrindo o texto
inteiro sem pular nada). Para cada batida decida (pipeline do guia, passos 1 e 2):
- "narracao": o trecho EXATO da narração (copiado sem mudar uma palavra);
- "intencao_visual": em português, o que a imagem precisa mostrar e por quê (ideia central + função no argumento);
- "emocao": curiosidade, surpresa, suspense, humor, revelação, reflexão…;
- "objeto": o objeto/fenômeno concreto da cena;
- "tipo_imagem": um de {list(tipos_imagem_da_marca(m))} ({'; '.join(f'{k} = {v}' for k, v in tipos_imagem_da_marca(m).items())});
- "mascote": uma das poses abaixo OU null. O mascote é o guia curioso: aparece em ~1 de cada 3 batidas, sempre que a
  narração faz pergunta, reage a um fato surpreendente, explica, investiga ou volta ao gancho. Poses: {poses}.
  Nunca mais de UM mascote por imagem. {ms.get('role', '')}
- "acao_mascote_en": se houver mascote, a ação específica dele nesta cena, em inglês (ex.: "pointing at the burnt stones in the brazier");
- "assunto_en": SUBJECT do prompt, em inglês, concreto e factual (o que está na imagem; pessoas reais da história como
  fotografias de arquivo em preto e branco);
- "pergunta_visual_en": a pergunta que o quadro faz o espectador se perguntar, em inglês;
- "composicao_en": primeiro plano, plano médio, fundo, ângulo e o ponto focal, em inglês (varie plano aberto, médio e detalhe);
- "texto_de": 0 a 4 linhas CURTAS no idioma do canal ({p.get('channel_language')}) pra pôr por cima (manchete ou etiquetas de papel; marque a palavra-chave com
  *asteriscos* — ela fica vermelha). Só quando ajuda (datas, lugares, nomes, uma pergunta). Escrita correta nesse idioma.
- "anotacao": null ou "circulo" ou "seta" (marcação vermelha à mão no ponto que a narração destaca).
Nada de gore; estética documental vintage. Pessoas reais: representação neutra e respeitosa.
{_bloco_elenco(elenco)}{_pp}
Responda SÓ com JSON: {{"batidas": [{{"narracao": "...", "intencao_visual": "...", "emocao": "...", "objeto": "...",
"tipo_imagem": "arquivo", "mascote": null, "acao_mascote_en": "", "assunto_en": "...", "pergunta_visual_en": "...",
"composicao_en": "...", "texto_de": ["..."], "anotacao": null, "pessoas": [], "ano": 0, "lugar": ""{', "personagens": []' if _pp else ''}}}]}}

NARRAÇÃO:
{narracao.strip()}"""


def _bloco_personagens_batidas(m: Dict[str, Any]) -> str:
    """🎭 v84_173: canal com personagens — em que batidas elas aparecem na IMAGEM (e fazendo o quê)."""
    perfil = perfil_de(m)
    if not perfil or not perfil.get("personagens"):
        return ""
    L = ["", "PERSONAGENS DO CANAL (aparecem na imagem desenhadas no estilo delas, mais simples, com a ficha como referência):"]
    for p in perfil["personagens"]:
        L.append(f"- {p['slug']} = {p['nome']}" + (f" ({p.get('epiteto')})" if p.get("epiteto") else "")
                 + (f" · aparece: {p['quando_aparece']}" if p.get("quando_aparece") else "")
                 + (f" · NÃO aparece: {p['quando_nao_aparece']}" if p.get("quando_nao_aparece") else ""))
    L += ["- \"personagens\": [{\"slug\": \"mira\", \"acao_en\": \"what she does/feels in this frame, in English\"}] — quem aparece na "
          "imagem desta batida (0, 1 ou 2). Ponha quando a batida é uma fala/reação delas (as tags [mira], [vanta] na narração) "
          "ou um momento de relação/lore; as batidas que explicam o fenômeno em si ficam SEM personagens (imagem científica). "
          "Não use \"mascote\" pra elas.",
          "- A narração tem tags de voz ([narrador], [mira|curiosa]…): copie a narração da batida COM as tags, sem mudar nada."]
    return "\n".join(L) + "\n"


def _bloco_elenco(elenco: Optional[Dict[str, Any]]) -> str:
    """🎭 O elenco do Modelo de vídeo (pessoas, animais, estátuas, lugares com foto) — igual ao do true crime."""
    try:
        import elenco as _el
        bloco = _el.bloco_para_cenas(elenco or {})
    except Exception:  # noqa: BLE001
        bloco = ""
    if not bloco:
        return '- "pessoas": [], "ano": 0, "lugar": "" (não há elenco com foto neste vídeo).\n'
    return f"""
{bloco}
Para CADA batida diga também (o site põe o rosto/a forma real pela FOTO, no estilo da marca):
- "pessoas": quem do ELENCO aparece na imagem: [{{"nome": "nome exato do elenco", "idade": idade NAQUELE momento da
  história}}] — pense na linha do tempo (a cena de 1930 mostra a pessoa com a idade de 1930). Vazio se não aparece ninguém.
- "ano": o ano em que a cena se passa (0 se não dá pra saber).
- "lugar": o nome exato de um dos LOCAIS quando a cena se passa ali (vazio se não).
Com alguém do elenco: nada de violência, morte ou humilhação; descreva a pessoa no "assunto_en" pela idade, roupa e época,
sem o nome (o site cuida do rosto).
"""


def _int0(v: Any) -> int:
    try:
        return max(0, min(3000, int(float(v))))
    except (TypeError, ValueError):
        return 0


def _pessoas(v: Any) -> List[Dict[str, Any]]:
    """[{"nome", "idade"}] — aceita lista de dicts, de nomes, ou o texto "Nome:idade; Nome2:idade"."""
    out = []
    if isinstance(v, str):
        v = [x for x in re.split(r"[;\n]", v) if x.strip()]
    for x in v or []:
        if isinstance(x, dict):
            nome, idade = str(x.get("nome") or "").strip(), _int0(x.get("idade"))
        else:
            nome, _, idade = str(x).partition(":")
            nome, idade = nome.strip(), _int0(idade)
        if nome:
            out.append({"nome": nome[:80], "idade": idade})
    return out[:3]


def ler_batidas(texto: str, m: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    import json_ia
    d = json_ia.carregar(texto)
    lista = d.get("batidas") if isinstance(d, dict) else d
    if not isinstance(lista, list) or not lista:
        raise MarcaErro("A resposta não tem a lista \"batidas\".")
    out = []
    for k, b in enumerate(lista, 1):
        if not isinstance(b, dict):
            continue
        pose = b.get("mascote")
        catalogo = todas_poses(m) if m else POSES
        acao_livre = ""
        if isinstance(pose, str) and pose.strip() and pose not in catalogo and pose.lower() not in ("null", "none", "nenhum"):
            acao_livre, pose = pose.strip(), pose_mais_proxima(pose)  # 🆕 pose que não está no catálogo: vira ação livre
        pose = pose if isinstance(pose, str) and pose in catalogo else ""
        _tipos = tipos_imagem_da_marca(m)
        tipo = b.get("tipo_imagem") if b.get("tipo_imagem") in _tipos else ("mascote" if pose else ("arquivo" if "arquivo" in _tipos else next(iter(_tipos))))
        txt = b.get("texto_de") or []
        if isinstance(txt, str):
            txt = [x for x in txt.split("\n") if x.strip()]
        out.append({"id": f"c{k:03d}", "narracao": str(b.get("narracao") or "").strip()[:2000],
                    "intencao_visual": str(b.get("intencao_visual") or "")[:600], "emocao": str(b.get("emocao") or "")[:60],
                    "objeto": str(b.get("objeto") or "")[:200], "tipo_imagem": tipo, "mascote": pose,
                    "acao_mascote_en": str(b.get("acao_mascote_en") or acao_livre or "")[:300], "assunto_en": str(b.get("assunto_en") or "")[:800],
                    "pergunta_visual_en": str(b.get("pergunta_visual_en") or "")[:300],
                    "composicao_en": str(b.get("composicao_en") or "")[:400],
                    "texto_de": [str(x)[:80] for x in txt][:4],
                    "anotacao": b.get("anotacao") if b.get("anotacao") in ("circulo", "seta") else None,
                    "pessoas": _pessoas(b.get("pessoas")), "ano": _int0(b.get("ano")), "lugar": str(b.get("lugar") or "")[:120],
                    "personagens": _slugs_personagens(b.get("personagens")),
                    "qa_status": "", "qa_notas": "", "geracoes": []})
    if not out:
        raise MarcaErro("Nenhuma batida válida na resposta.")
    return out


def batidas_sem_ia(narracao: str, a_cada: int = 3, m: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Sem IA: corta por frases (~28 palavras por batida) e põe o mascote a cada `a_cada` batidas (pose curioso/explicando)."""
    frases = re.split(r"(?<=[.!?…])\s+", " ".join(str(narracao or "").split()))
    blocos, atual = [], []
    for f in frases:
        atual.append(f)
        if len(" ".join(atual).split()) >= 28:
            blocos.append(" ".join(atual))
            atual = []
    if atual:
        blocos.append(" ".join(atual))
    out = []
    perfil = perfil_de(m) if m else None
    slugs = {p["slug"] for p in (perfil or {}).get("personagens") or []}
    for k, t in enumerate(blocos, 1):
        pers = []
        if perfil:  # 🎭 canal com personagens: aparece quem fala nesta batida (pela tag de voz); sem mascote
            import canal_perfil
            for tag in re.findall(r"\[\s*([^\]|]+)", t):
                sl = canal_perfil._slug(tag)
                if sl in slugs and sl not in [x["slug"] for x in pers]:
                    pers.append({"slug": sl, "acao_en": ""})
            pose = ""
        else:
            pose = ("curioso" if "?" in t else "explicando") if k % a_cada == 1 else ""
        out.append({"id": f"c{k:03d}", "narracao": t, "intencao_visual": "", "emocao": "", "objeto": "",
                    "tipo_imagem": "mascote" if pose else ("ilustracao" if perfil else "arquivo"), "mascote": pose, "acao_mascote_en": "",
                    "assunto_en": re.sub(r"\[[^\]]*\]", "", t)[:400].strip(), "pergunta_visual_en": "", "composicao_en": "",
                    "texto_de": [], "anotacao": None, "personagens": pers[:2],
                    "qa_status": "", "qa_notas": "", "geracoes": []})
    return out


def registro_da_cena(m: Dict[str, Any], p: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """O expected_output_per_scene do guia + os consistency_metadata_to_log."""
    ultima = (b.get("geracoes") or [{}])[-1]
    return {"scene_id": b["id"], "narration_excerpt": b.get("narracao"), "visual_intent": b.get("intencao_visual"),
            "prompt_final": ultima.get("prompt") or b.get("prompt_final"), "reference_assets": ultima.get("referencias") or [],
            "model_metadata": {k: ultima.get(k) for k in ("motor", "model_name", "model_version", "seed", "passos", "largura", "altura")},
            "output_file": b.get("arquivo_master"), "output_file_graded": b.get("arquivo_corrigido"),
            "output_file_with_text": b.get("arquivo_texto"), "qa_status": b.get("qa_status") or "pending",
            "qa_notes": b.get("qa_notas") or "", "palette_check": b.get("paleta"),
            **{k: (ultima.get(k) or m["versoes"].get(k)) for k in ("style_lock_version", "palette_version", "prompt_version", "postprocess_preset")},
            "aspect_ratio": p.get("proporcao"), "mascot_reference_files": [r for r in ultima.get("referencias") or [] if "mascote" in r or "folha" in r],
            "approved_or_rejected": {"approved": "approved", "reject": "rejected"}.get(b.get("qa_status") or "", "pending"),
            "reason_for_rejection": b.get("qa_notas") if b.get("qa_status") in ("reject", "revise") else ""}


DIMS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1024, 1024)}


# ------------------------------------------------------------------ 🧍 biblioteca de poses (catálogo + as que você cria)
PALAVRAS_POSE = {
    "investigando": ["lupa", "investig", "procur", "examin", "pista", "detetive", "magnif", "clue", "inspect", "search"],
    "explicando": ["apont", "explic", "mostr", "ensin", "apresent", "point", "explain", "present", "teach"],
    "surpreso": ["surpre", "susto", "assust", "choc", "espant", "medo", "pavor", "grit", "shock", "surpris", "scare", "startl", "afraid"],
    "estudando": ["livro", "ler ", "lendo", "estud", "sentad", "book", "read", "sit", "study"],
    "sem_ideia": ["não sei", "nao sei", "dúvid", "duvid", "confus", "ombro", "perdid", "shrug", "puzzl", "confus", "lost"],
    "ideia": ["ideia", "lâmpada", "lampada", "eureka", "descobr", "idea", "bulb", "discover"],
    "curioso": ["curios", "olhand", "observ", "espi", "admir", "curious", "look", "peek", "watch", "wonder"],
}


def todas_poses(m: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    extras = ((m or {}).get("estado") or {}).get("poses_extras") or {}
    return {**POSES, **{k: v for k, v in extras.items() if isinstance(v, dict) and v.get("en")}}


def pose_info(m: Optional[Dict[str, Any]], pose: str) -> Dict[str, Any]:
    return todas_poses(m).get(pose or "") or POSES["normal"]


def pose_mais_proxima(texto: str) -> str:
    """Qual das 8 poses oficiais do painel serve de referência pra uma pose/emoção nova (pelo jeito do corpo)."""
    t = f" {str(texto or '').lower()} "
    melhor, pontos = "normal", 0
    for pose, palavras in PALAVRAS_POSE.items():
        n = sum(1 for p in palavras if p in t)
        if n > pontos:
            melhor, pontos = pose, n
    return melhor


def traduzir_pose(descricao: str) -> Dict[str, str]:
    """Pose/emoção em português → {"nome", "en"} (instrução em inglês pro gerador). Sem a IA: o próprio texto
    (o klein do pod entende português também, só fica menos preciso)."""
    descricao = " ".join(str(descricao or "").split())[:300]
    if not descricao:
        raise MarcaErro("Descreva a pose ou emoção.")
    try:
        import ia_servico
        with ia_servico.rotulo("Identidade visual: pose nova"):
            r = ia_servico.chamar(
                "marca",
                "You turn a pose/emotion description (Portuguese) for a vintage rubber-hose cartoon mascot into a short, concrete "
                "English action phrase for an image model: body posture, arms, head tilt, eyes and the one prop if any. Keep "
                "the mascot design unchanged (do not describe its design). Max 30 words. Also give a short Portuguese name (2-4 words).",
                descricao, schema={"type": "object", "properties": {"nome": {"type": "string"}, "en": {"type": "string"}},
                                   "required": ["nome", "en"], "additionalProperties": False}, max_tokens=200)
        if isinstance(r, dict) and r.get("en"):
            return {"nome": str(r.get("nome") or descricao)[:60], "en": str(r["en"])[:300]}
    except Exception:  # noqa: BLE001
        pass
    return {"nome": descricao[:60], "en": descricao}


def nova_pose(m: Dict[str, Any], descricao: str, en: str = "", nome: str = "") -> str:
    """🆕 Uma pose/emoção nova pro mascote. Ela vira uma célula da folha mestra: gere, aprove, e ela entra na
    biblioteca (dá pra usar nas batidas e vira referência das próximas)."""
    import unicodedata
    if not en:
        t = traduzir_pose(descricao)
        en, nome = t["en"], nome or t["nome"]
    nome = (nome or descricao)[:60]
    slug = re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()).strip("_")[:24] or "pose"
    pid = "x_" + slug
    extras = m["estado"].setdefault("poses_extras", {})
    k = 2
    while pid in extras or pid in POSES:
        pid = f"x_{slug}_{k}"
        k += 1
    extras[pid] = {"nome": nome, "en": " ".join(en.split())[:300], "ref": pose_mais_proxima(f"{descricao} {en}"),
                   "descricao": descricao[:300], "criado": time.time()}
    salvar_estado(m)
    return pid


def excluir_pose(m: Dict[str, Any], pid: str) -> None:
    if not pid.startswith("x_"):
        raise MarcaErro("As poses do painel oficial não se apagam.")
    (m["estado"].get("poses_extras") or {}).pop(pid, None)
    (estado_folha(m)["celulas"]).pop(pid, None)
    salvar_estado(m)


def celulas_folha(m: Dict[str, Any]) -> List[Dict[str, str]]:
    extras = m["estado"].get("poses_extras") or {}
    return CELULAS_FOLHA + [{"id": k, "nome": v["nome"], "ref": v.get("ref") or "normal", "en": v["en"], "extra": "1"}
                            for k, v in extras.items()]


# ------------------------------------------------------------------ 🖼 gerar (pod ou Flow) com tudo registrado
def _nome_ref(papel: str, cam: str) -> str:
    return f"{papel}_{hashlib.sha1(os.path.abspath(cam).encode()).hexdigest()[:8]}{os.path.splitext(cam)[1].lower() or '.png'}"


def gerar(pedidos: List[Dict[str, Any]], motor: str = "pod", cfg: Optional[Dict[str, Any]] = None, on_passo=None,
          nome_lote: str = "marca") -> List[Dict[str, Any]]:
    """pedidos = [{"nome", "prompt", "refs": [(papel, caminho)], "seed"?, "destino", "largura", "altura"}] →
    [{"nome", "arquivo"|None, "erro", "motor", "model_name", "model_version", "seed", "passos", "largura", "altura"}].
    Pod: com referência = FLUX.2 [klein] 4B (até 4 refs, 4 passos); sem = Z-Image Turbo (9 passos). Flow: 1 ref."""
    import random
    out: List[Dict[str, Any]] = []
    if motor == "flow":
        import flow_estudio
        for k, pd in enumerate(pedidos):
            if on_passo:
                on_passo(f"Flow: {k + 1}/{len(pedidos)}")
            r = {"nome": pd["nome"], "arquivo": None, "erro": "", "motor": "flow", "model_name": "google-flow",
                 "model_version": (cfg or {}).get("flow_modelo") or "padrão do Flow", "seed": None, "passos": None,
                 "largura": pd.get("largura"), "altura": pd.get("altura")}
            try:
                prop = "9:16" if pd.get("altura", 0) > pd.get("largura", 0) else ("1:1" if pd.get("altura") == pd.get("largura") else "16:9")
                saidas = flow_estudio.gerar_imagem_e_esperar(pd["prompt"], referencia=(pd.get("refs") or [(None, None)])[0][1],
                                                             proporcao=prop, modelo=(cfg or {}).get("flow_modelo") or "")
                os.makedirs(os.path.dirname(pd["destino"]), exist_ok=True)
                from PIL import Image
                Image.open(saidas[0]).convert("RGB").save(pd["destino"])
                r["arquivo"] = pd["destino"]
            except Exception as exc:  # noqa: BLE001
                r["erro"] = str(exc)[:300]
            out.append(r)
        return out
    import pod_studio
    grupos: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    for pd in pedidos:
        grupos.setdefault((int(pd.get("largura") or 1280), int(pd.get("altura") or 720)), []).append(pd)
    for (w, h), lista in grupos.items():
        itens, por_nome = [], {}
        for pd in lista:
            seed = pd.get("seed") if pd.get("seed") is not None else random.randint(0, 2 ** 31 - 1)
            it = {"prompt": pd["prompt"], "nome": pd["nome"], "seed": int(seed)}
            if pd.get("refs"):
                it["referencias"] = [[_nome_ref(papel, cam), cam] for papel, cam in pd["refs"][:4]]
            itens.append(it)
            por_nome[pd["nome"]] = (pd, it)
        jid, sem_refs = pod_studio.enviar_imagens_com_refs(itens, largura=w, altura=h, nome=nome_lote, cfg=cfg)
        st = {}
        try:
            st = pod_studio.esperar(jid, cfg, timeout_s=3600, on_passo=on_passo)
            erro_geral = ""
        except Exception as exc:  # noqa: BLE001 — pode ter gerado parte
            erro_geral = str(exc)[:300]
            try:
                st = pod_studio.job(jid, cfg)
            except Exception:  # noqa: BLE001
                st = {}
        meta = {}
        if "metadados.json" in (st.get("arquivos") or []):
            try:
                import tempfile
                tmp = os.path.join(tempfile.gettempdir(), f"meta_{jid}.json")
                pod_studio.baixar(jid, "metadados.json", tmp, cfg)
                meta = {x.get("nome"): x for x in _json(tmp, []) or []}
                os.remove(tmp)
            except Exception:  # noqa: BLE001
                meta = {}
        erros = {e.get("item"): e.get("erro") for e in st.get("erros") or []}
        for nome, (pd, it) in por_nome.items():
            mt = meta.get(nome) or {}
            klein = bool(it.get("referencias")) and not sem_refs
            r = {"nome": nome, "arquivo": None, "erro": "", "motor": "pod", "job": jid,
                 "model_name": "FLUX.2 [klein] 4B" if klein else "Z-Image Turbo",
                 "model_version": "black-forest-labs/FLUX.2-klein-4B" if klein else "Tongyi-MAI/Z-Image-Turbo",
                 "seed": mt.get("seed", it["seed"]), "passos": mt.get("passos") or (4 if klein else 9), "largura": w, "altura": h,
                 "referencias_ignoradas": bool(sem_refs and it.get("referencias")),
                 "reference_strength_if_supported": "n/a (klein: referência por imagem, guidance 1.0)" if klein else None}
            arq = f"{nome}.png"
            if arq in (st.get("arquivos") or []):
                try:
                    pod_studio.baixar(jid, arq, pd["destino"], cfg)
                    r["arquivo"] = pd["destino"]
                except Exception as exc:  # noqa: BLE001
                    r["erro"] = f"não baixou: {exc}"[:300]
            else:
                r["erro"] = erros.get(nome) or erro_geral or "o pod não gerou essa imagem"
            out.append(r)
    return out


# ------------------------------------------------------------------ 🗂 folha mestra: gerar, aprovar, reprovar células
def gerar_celulas(m: Dict[str, Any], ids: Iterable[str], motor: str = "pod", cfg: Optional[Dict[str, Any]] = None,
                  variacoes: int = 2, on_passo=None) -> Dict[str, Any]:
    """Gera `variacoes` candidatas de cada célula (vista/pose/emoção), com a pose do painel + a folha v0/atual + o
    mascote em alta como referências. Você aprova a melhor (ou reprova com o motivo e gera de novo)."""
    cels = {c["id"]: c for c in celulas_folha(m)}
    ids = [i for i in ids if i in cels]
    if not ids:
        raise MarcaErro("Escolha ao menos uma célula.")
    f = estado_folha(m)
    pasta = os.path.join(m["dir"], "folha_mestra", "celulas")
    pedidos, quem = [], {}
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for cid in ids:
        c = cels[cid]
        refs: List[Tuple[str, str]] = []
        rp = os.path.join(m["dir"], "referencias", "poses", f"pose_{c['ref']}.png")
        if os.path.isfile(rp):
            refs.append(("mascote_pose", rp))
        if cid == "silhueta":
            sil = os.path.join(m["dir"], "referencias", "silhuetas", "silhueta_normal.png")
            if os.path.isfile(sil):
                refs.append(("silhueta", sil))
        prop = os.path.join(m["dir"], "referencias", "mascote_proporcoes.png")
        if os.path.isfile(prop):
            refs.append(("mascote_proporcoes", prop))
        fl = folha_atual(m)
        if fl:
            refs.append(("folha_mestra", fl))
        if not os.path.isfile(prop):
            alta = os.path.join(m["dir"], "referencias", "mascote_alta_res_tronco.png")
            if os.path.isfile(alta):
                refs.append(("mascote_alta_res", alta))
        refs = refs[:4]
        prompt = montar_prompt(m, {"tipo": "folha", "assunto_en": c["en"]}, refs)
        for k in range(max(1, min(4, int(variacoes)))):
            nome = f"{cid}_{stamp}_{k + 1}"
            pedidos.append({"nome": nome, "prompt": prompt, "refs": refs, "destino": os.path.join(pasta, nome + ".png"),
                            "largura": 1024, "altura": 1024})
            quem[nome] = (cid, prompt, refs)
    res = gerar(pedidos, motor, cfg, on_passo, nome_lote=f"folha_{m['slug']}")
    for r in res:
        cid, prompt, refs = quem[r["nome"]]
        cel = f["celulas"].setdefault(cid, {"status": "", "candidatas": []})
        if r.get("arquivo"):
            cel.setdefault("candidatas", []).append({
                "arquivo": os.path.relpath(r["arquivo"], m["dir"]), "prompt": prompt,
                "referencias": [os.path.relpath(c, m["dir"]) for _p, c in refs], "paleta": validar_paleta(r["arquivo"], m),
                "quando": time.time(), **{k: r.get(k) for k in ("motor", "model_name", "model_version", "seed", "passos")},
                **m["versoes"]})
            if cel.get("status") != "aprovada":
                cel["status"] = "candidatas"
        else:
            cel["erro"] = r.get("erro")
    salvar_estado(m)
    return {"geradas": sum(1 for r in res if r.get("arquivo")), "erros": [r["erro"] for r in res if r.get("erro")][:5]}


def aprovar_celula(m: Dict[str, Any], cid: str, arquivo_rel: str) -> None:
    cel = estado_folha(m)["celulas"].get(cid) or {}
    cand = next((c for c in cel.get("candidatas") or [] if c["arquivo"] == arquivo_rel), None)
    if not cand:
        raise MarcaErro("Essa candidata não existe.")
    cel.update(status="aprovada", arquivo=arquivo_rel, aprovada_em=time.time(), motivo="")
    for c in cel["candidatas"]:
        c["qa"] = "approved" if c is cand else c.get("qa") or ""
    estado_folha(m)["celulas"][cid] = cel
    salvar_estado(m)


def reprovar_celula(m: Dict[str, Any], cid: str, arquivo_rel: str, motivo: str) -> None:
    cel = estado_folha(m)["celulas"].get(cid) or {}
    for c in cel.get("candidatas") or []:
        if c["arquivo"] == arquivo_rel:
            c.update(qa="rejected", motivo=str(motivo or "")[:300])
            if cel.get("arquivo") == arquivo_rel:
                cel.update(status="candidatas", arquivo=None)
    salvar_estado(m)


# ------------------------------------------------------------------ 🎬 batidas: gerar, corrigir, texto, QA
def _foto_proj(m: Dict[str, Any], p: Dict[str, Any], fid: str) -> Optional[str]:
    f = next((x for x in p.get("fotos") or [] if x.get("id") == fid), None)
    if not f:
        return None
    cam = os.path.join(_pasta_proj(m, p["id"]), "fotos", f["arquivo"])
    return cam if os.path.isfile(cam) else None


def _base_do_site(m: Dict[str, Any]) -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(m["dir"])))


def elenco_de(m: Dict[str, Any], p: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """🎭 (o Modelo de vídeo de origem, o elenco dele) — o mesmo das 📸 Fotos para o roteiro e do 🎭 Elenco do true crime."""
    o = p.get("origem") or {}
    if o.get("tipo") != "dossie" or not o.get("id"):
        return None, {}
    try:
        import dossies as ds
        d = ds.carregar(_base_do_site(m), o["id"])
    except Exception:  # noqa: BLE001
        return None, {}
    return d, d.get("elenco") or {}


def _refs_do_elenco(m: Dict[str, Any], p: Dict[str, Any], b: Dict[str, Any]) -> List[Tuple[str, Dict[str, str]]]:
    """Fotos do elenco pra esta batida: o rosto de cada pessoa na idade da cena (a foto mais perto da idade, com o
    aviso de envelhecer/rejuvenescer) e o lugar. → [(caminho, {"frase", "descricao_en"})]."""
    if not b.get("pessoas") and not b.get("lugar"):
        return []
    d, el = elenco_de(m, p)
    if not d or not el:
        return []
    import dossies as ds
    import elenco as _el
    base = _base_do_site(m)
    out: List[Tuple[str, Dict[str, str]]] = []
    por_nome = {x["nome"].lower(): x for x in el.get("pessoas") or [] if x.get("usar", True)}
    for pc in b.get("pessoas") or []:
        x = por_nome.get(str(pc.get("nome") or "").strip().lower())
        if not x:
            continue
        idade = int(pc.get("idade") or 0)
        if not idade and b.get("ano") and x.get("nascimento"):
            idade = max(0, int(b["ano"]) - int(x["nascimento"]))
        f = _el._melhor_foto(x, idade)
        md = ds.midia(d, f["midia"]) if f else None
        cam = ds.caminho_midia(base, d, md) if md else None
        if not cam:
            continue
        quem = f.get("quem_na_foto") if not f.get("so_ele", True) and f.get("quem_na_foto") else "the person"
        dif = (idade - f["idade"]) if idade and f.get("idade") else 0
        frase = (f"use the face and identity of {quem} in this photo{f', about {idade} years old' if idade else ''}"
                 f"{_el._envelhecer(idade, dif) if idade else ''}{' (' + x['aparencia'] + ')' if x.get('aparencia') else ''}")
        out.append((cam, {"frase": frase, "descricao_en": x.get("aparencia") or "", "estilo": "foto"}))
    lugar = str(b.get("lugar") or "").strip().lower()
    loc = next((x for x in el.get("locais") or [] if x.get("usar", True) and lugar and x["nome"].lower() == lugar), None)
    if loc and loc.get("fotos"):
        md = ds.midia(d, loc["fotos"][0])
        cam = ds.caminho_midia(base, d, md) if md else None
        if cam:
            out.append((cam, {"frase": "the location is the place in this photo (same architecture and surroundings"
                                       + (f": {loc['descricao']}" if loc.get("descricao") else "") + ")", "estilo": "foto"}))
    return out


def cena_da_batida(m: Dict[str, Any], p: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    c = dict(b, tipo="thumbnail" if b.get("tipo_imagem") == "thumbnail" else "cena")
    c["refs_extras"], c["fotos_info"] = [], []
    for cam, info in _refs_do_elenco(m, p, b):  # 🎭 elenco primeiro (rosto certo na idade certa), depois as fotos marcadas
        if cam not in c["refs_extras"]:
            c["refs_extras"].append(cam)
            c["fotos_info"].append(info)
    if b.get("lugar") and not any("location" in (i.get("frase") or "") for i in c["fotos_info"]):
        _d, el = elenco_de(m, p)
        loc = next((x for x in (el or {}).get("locais") or [] if x["nome"].lower() == str(b["lugar"]).lower()), None)
        if loc and loc.get("descricao"):  # 📍 lugar sem foto: a descrição fiel às fontes, igual em todas as cenas
            c["assunto_en"] = f"{c.get('assunto_en') or ''} Location: {loc['descricao']}".strip()
    for fid in b.get("fotos") or []:
        cam = _foto_proj(m, p, fid)
        if cam and cam not in c["refs_extras"]:
            f = next((x for x in p.get("fotos") or [] if x.get("id") == fid), {})
            c["refs_extras"].append(cam)
            c["fotos_info"].append({"descricao_en": f.get("descricao_en") or "", "estilo": f.get("estilo") or "foto"})
    c["ref_estilo"] = bool(p.get("ref_estilo_sempre"))
    return c


def descrever_foto(cam: str, nome: str = "") -> Optional[str]:
    """📷 A IA olha a foto (pessoa, animal, estátua, objeto, lugar) e escreve as características que precisam
    aparecer na imagem gerada — em inglês, curto. None sem a IA (a foto ainda vai como referência no klein)."""
    import ia_servico
    bl = ia_servico.imagem_bloco(cam, largura=768)
    if not bl:
        return None
    with ia_servico.rotulo("Identidade visual: características da foto"):
        r = ia_servico.chamar(
            "marca",
            "Describe the main subject of this photo so an image model can redraw it recognizably in another art style. "
            "One English sentence, max 45 words: what it is (species/breed, statue material, object, building), shape, "
            "distinctive features, colors/patterns, pose; for a person: approximate age, build, hair, facial hair, glasses, "
            "clothing and era — never guess the person's name or identity. No style words.",
            [bl, {"type": "text", "text": f"Label given by the user: {nome}" if nome else "No label."}], max_tokens=200)
    return " ".join(str(r).split())[:400] if r else None


def previa_prompt(m: Dict[str, Any], p: Dict[str, Any], b: Dict[str, Any], motor: str = "") -> Dict[str, Any]:
    cena = cena_da_batida(m, p, b)
    refs = referencias_para(m, cena, motor or p.get("motor") or "pod")
    return {"prompt": b.get("prompt_manual") or montar_prompt(m, cena, refs),
            "referencias": [{"papel": papel, "arquivo": os.path.relpath(c, m["dir"])} for papel, c in refs],
            "modelo": ("FLUX.2 [klein] 4B" if refs else "Z-Image Turbo") if (motor or p.get("motor")) != "flow" else "Google Flow"}


def gerar_batidas(m: Dict[str, Any], pid: str, ids: Iterable[str], motor: str = "", cfg: Optional[Dict[str, Any]] = None,
                  on_passo=None) -> Dict[str, Any]:
    """Passos 3–6 + o QA automático da paleta: gera, registra, valida a paleta e (se precisar) corrige com o grading."""
    with _TRAVA:
        p = carregar_projeto(m, pid)
    motor = motor or p.get("motor") or "pod"
    ids = set(ids)
    W, H = DIMS.get(p.get("proporcao") or "16:9", (1280, 720))
    pasta = os.path.join(_pasta_proj(m, pid), "master")
    pedidos, quem = [], {}
    for b in p["batidas"]:
        if b["id"] not in ids:
            continue
        cena = cena_da_batida(m, p, b)
        refs = referencias_para(m, cena, motor)
        prompt = b.get("prompt_manual") or montar_prompt(m, cena, refs)
        n = len(b.get("geracoes") or []) + 1
        nome = f"{b['id']}_v{n}"
        seed = b.get("seed_fixa")
        pedidos.append({"nome": nome, "prompt": prompt, "refs": refs, "seed": seed, "destino": os.path.join(pasta, nome + ".png"),
                        "largura": W, "altura": H})
        quem[nome] = (b["id"], prompt, refs)
    if not pedidos:
        raise MarcaErro("Nenhuma batida escolhida.")
    res = gerar(pedidos, motor, cfg, on_passo, nome_lote=f"{m['slug']}_{pid}")
    with _TRAVA:
        p = carregar_projeto(m, pid)
        por_id = {b["id"]: b for b in p["batidas"]}
        for r in res:
            bid, prompt, refs = quem[r["nome"]]
            b = por_id.get(bid)
            if not b:
                continue
            g = {"prompt": prompt, "referencias": [os.path.relpath(c, m["dir"]) for _p, c in refs], "quando": time.time(),
                 "erro": r.get("erro") or "", **{k: r.get(k) for k in ("motor", "model_name", "model_version", "seed", "passos",
                                                                     "largura", "altura", "reference_strength_if_supported")},
                 **m["versoes"]}
            if r.get("arquivo"):
                g["arquivo"] = os.path.relpath(r["arquivo"], m["dir"])
                b["arquivo_master"] = g["arquivo"]
                b["arquivo_texto"] = None
                b["paleta"] = validar_paleta(r["arquivo"], m)
                b["arquivo_corrigido"] = None
                if b["paleta"]["status"] != "aprovada" or p.get("corrigir_sempre"):
                    corr = os.path.join(_pasta_proj(m, pid), "corrigidas", os.path.basename(r["arquivo"]))
                    os.makedirs(os.path.dirname(corr), exist_ok=True)
                    gradear(r["arquivo"], corr, m)
                    b["arquivo_corrigido"] = os.path.relpath(corr, m["dir"])
                    b["paleta_corrigida"] = validar_paleta(corr, m)
                st = (b.get("paleta_corrigida") if b.get("arquivo_corrigido") else b["paleta"]) or {}
                b["qa_status"] = "revise" if st.get("status") == "reprovar" else ""
                b["qa_notas"] = ("Paleta: " + "; ".join(st.get("problemas") or [])) if st.get("status") == "reprovar" else ""
                if r.get("referencias_ignoradas"):
                    b["qa_notas"] = (b["qa_notas"] + " · o pod é antigo e gerou SEM as referências do mascote").strip(" ·")
            b.setdefault("geracoes", []).append(g)
        salvar_projeto(m, p)
    return {"geradas": sum(1 for r in res if r.get("arquivo")), "erros": [r["erro"] for r in res if r.get("erro")][:5]}


def imagem_final_da_batida(m: Dict[str, Any], b: Dict[str, Any], com_texto: bool = True) -> Optional[str]:
    for chave in (["arquivo_texto"] if com_texto else []) + ["arquivo_corrigido" if b.get("usar_corrigida", True) else "", "arquivo_master"]:
        if chave and b.get(chave) and os.path.isfile(arquivo(m, b[chave])):
            return arquivo(m, b[chave])
    return None


def elementos_padrao(b: Dict[str, Any], indice: int = 0) -> List[Dict[str, Any]]:
    """Textos e anotações automáticos da batida: etiquetas de papel no lado oposto ao mascote, marcação vermelha."""
    els: List[Dict[str, Any]] = []
    linhas = [x for x in b.get("texto_de") or [] if str(x).strip()]
    if linhas:
        tipo = "manchete" if len(linhas) <= 2 and max(len(x) for x in linhas) <= 22 and not b.get("mascote") else "etiquetas"
        els.append({"tipo": tipo, "linhas": linhas, "pos": "esquerda" if b.get("mascote") else ("direita" if indice % 2 == 0 else "esquerda")})
    if b.get("anotacao") == "circulo":
        els.append({"tipo": "circulo", "x": 0.5, "y": 0.45, "r": 0.12})
    elif b.get("anotacao") == "seta":
        els.append({"tipo": "seta", "de": [0.3, 0.75], "para": [0.47, 0.5]})
    return els


def aplicar_texto_batida(base: str, m: Dict[str, Any], pid: str, bid: str, elementos: Optional[List[Dict[str, Any]]] = None) -> str:
    with _TRAVA:
        p = carregar_projeto(m, pid)
        k, b = next(((k, b) for k, b in enumerate(p["batidas"]) if b["id"] == bid), (0, None))
        if not b:
            raise MarcaErro("Batida não encontrada.")
        src = imagem_final_da_batida(m, b, com_texto=False)
        if not src:
            raise MarcaErro("Gere a imagem dessa batida primeiro.")
        els = elementos if elementos is not None else (b.get("elementos") or elementos_padrao(b, k))
        b["elementos"] = els
        if not els:
            b["arquivo_texto"] = None
            salvar_projeto(m, p)
            return src
        dst = os.path.join(_pasta_proj(m, pid), "com_texto", f"{bid}.png")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        aplicar_textos(src, dst, els, m, base)
        b["arquivo_texto"] = os.path.relpath(dst, m["dir"])
        salvar_projeto(m, p)
        return dst


def revisar_ia(m: Dict[str, Any], img: str, cena: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """👁 Passo 8 com a IA: olha a imagem (e a referência do mascote) contra o quality_checklist do guia."""
    import ia_servico
    blocos: List[Dict[str, Any]] = []
    if cena.get("mascote"):
        rp = ref_pose(m, cena["mascote"])
        if rp:
            b = ia_servico.imagem_bloco(rp, largura=384)
            if b:
                blocos += [{"type": "text", "text": "REFERENCE — the official mascot:"}, b]
        prop = os.path.join(m["dir"], "referencias", "mascote_proporcoes.png")
        if os.path.isfile(prop):
            b = ia_servico.imagem_bloco(prop, largura=900)
            if b:
                blocos += [{"type": "text", "text": "REFERENCE — frames of the ORIGINAL cartoon (true proportions):"}, b]
    b = ia_servico.imagem_bloco(img, largura=768)
    if not b:
        return None
    blocos += [{"type": "text", "text": "GENERATED IMAGE:"}, b,
               {"type": "text", "text": f"Scene intent: {cena.get('intencao_visual') or cena.get('assunto_en') or ''}\n"
                                        f"Mascot expected: {'yes, ' + (cena.get('acao_mascote_en') or pose_info(m, cena['mascote'])['en']) if cena.get('mascote') else 'no'}"}]
    chk = "\n".join(f"- {x}" for x in (m["guia"].get("quality_checklist") or []))
    with ia_servico.rotulo("Identidade visual: revisão"):
        return ia_servico.chamar(
            "marca",
            "You are the art director QA for a YouTube channel with a strict brand guide. Check the generated image against "
            "this checklist and the reference mascot (if given). Fail it if: the mascot design differs from the reference "
            "(silhouette, eyes, cream body, black outline, no extra limbs), there is more than one mascot, there is any text, "
            "letters or watermark, colors outside near-black/charcoal/gray/cream + a little signal red, or the scene does not "
            f"show the intent. Proportions are critical: {reforcos(m).get('mascote_en', '')} Fail (reject) a mascot that is "
            f"chubby, stubby, short-legged, symmetric like a child's bedsheet ghost, or has a mouth/eyebrows in a neutral pose."
            f"\nChecklist:\n{chk}\nAnswer in Portuguese (notas).",
            blocos, schema={"type": "object", "properties": {
                "status": {"type": "string", "enum": ["approved", "revise", "reject"]},
                "mascote_igual": {"type": "boolean"}, "tem_texto": {"type": "boolean"}, "paleta_ok": {"type": "boolean"},
                "notas": {"type": "string"}}, "required": ["status", "mascote_igual", "tem_texto", "paleta_ok", "notas"],
                "additionalProperties": False}, max_tokens=400)


def exportar(m: Dict[str, Any], pid: str) -> bytes:
    """📦 Passo 9: masters sem texto + corrigidas + versões com texto + registro (expected_output_per_scene) + prompts."""
    p = carregar_projeto(m, pid)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        registro = []
        for k, b in enumerate(p["batidas"], 1):
            for chave, pasta in (("arquivo_master", "1_masters_sem_texto"), ("arquivo_corrigido", "2_corrigidas_paleta"),
                                 ("arquivo_texto", "3_com_texto")):
                if b.get(chave) and os.path.isfile(arquivo(m, b[chave])):
                    z.write(arquivo(m, b[chave]), f"{pasta}/{k:03d}_{b['id']}.png")
            final = imagem_final_da_batida(m, b)
            if final:
                z.write(final, f"4_finais_na_ordem/{k:03d}_{b['id']}.png")
            registro.append(registro_da_cena(m, p, b))
        z.writestr("registro_cenas.json", json.dumps({"marca": m["slug"], "projeto": p["titulo"], "versoes": m["versoes"],
                                                       "cenas": registro}, ensure_ascii=False, indent=1))
        z.writestr("prompts.txt", "\n\n".join(f"[{r['scene_id']}] {r['prompt_final'] or ''}" for r in registro))
        z.writestr("narracao_por_cena.txt", "\n\n".join(f"[{k:03d}] {b.get('narracao')}" for k, b in enumerate(p["batidas"], 1)))
    return buf.getvalue()


# ------------------------------------------------------------------ 📘 como montar um pacote (página + prompt pra IA)
EXEMPLO_PACOTE = {"formato": FORMATO_PACOTE, "versao": VERSAO_PACOTE, "slug": "meu_canal", "nome": "Meu Canal", "idioma": "de",
                  "descricao": "Uma frase sobre o canal.",
                  # 🏭 v84_181: como a Produção no pod gera os vídeos deste canal (canal_pod.py)
                  "producao_pod": {"_sobre": "pct = % das cenas geradas no pod (100 = canal 100% IA); personagens = pessoa genérica "
                                             "vira personagem do canal e personagem falando aparece; fotos_do_roteiro = "
                                             "\"referencia\" (redesenha as fotos marcadas [I3] no estilo do canal) ou \"real\" (usa "
                                             "a foto como está); estilo_fotos = \"foto\" ou \"ilustracao\" (vazio = pela estética); "
                                             "ref_estilo = manda a amostra de estilo como referência em toda cena; "
                                             "intervalo/intervalo_min/intervalo_max = segundos por imagem (null = o do lote)",
                                   "pct": 100, "personagens": False, "fotos_do_roteiro": "referencia", "estilo_fotos": "",
                                   "ref_estilo": False, "intervalo": None, "intervalo_min": None, "intervalo_max": None},
                  # 🧍 v84_186: as personagens por cima do vídeo (aba 🧍 Personagens do Estúdio / projetos novos)
                  "personagens_editor": {"_sobre": "ativo = já põe as personagens nos projetos novos do canal; frequencia = quanto "
                                                   "dos momentos possíveis viram aparição (0.6 = os melhores ~60%; 1 = toda fala); "
                                                   "narrador_personagem = o slug do mascote que ILUSTRA frases da narração (canal sem "
                                                   "personagens que falam); lados/altura/entrada/saida/boca = o jeito delas na tela; "
                                                   "a 🤖 IA escolhe os momentos, a pose e a animação (ia: false = só a regra)",
                                         "ativo": True, "frequencia": 0.6, "min_intervalo": 6, "ia": True,
                                         "lados": {"mira": "esquerda", "vanta": "direita"}, "altura": 0.72,
                                         "entrada": "deslizar", "saida": "deslizar", "boca": True, "narrador_personagem": ""}}
EXEMPLO_REFORCOS = {
    "_sobre": "O que a IA de imagem costuma errar no mascote — DERIVADO do brand_guide.json e das imagens oficiais (não invente traços novos).",
    "mascote_en": "PROPORTION LOCK (match image references exactly): <cabeça, corpo, braços, pernas, pés, olhos, boca — proporções exatas, em inglês>",
    "evitar_en": "<o que o mascote NUNCA é, em inglês, separado por vírgula: chubby body, short legs, …>",
    "qa_pt": "<em português: quando reprovar o mascote na revisão>"}
EXEMPLO_POSES = {"poses": ["com lupa", "apontando", "lendo livro", "surpreso", "com ideia", "comemorando"]}
EXEMPLO_MODELO = {
    "chave": "meu_canal", "nome": "🎨 Meu Canal — curiosidade explicada", "descricao": "Que tipo de vídeo o canal faz.",
    "nome_canal": "Meu Canal", "palavras_por_minuto": 150, "chamadas": {"inscreva": 1, "venda": 0}, "escopo_enxuto": True,
    "formatos": {"longo": {"nome": "Vídeo longo", "minutos": 12, "estrutura": ["GANCHO: …", "VIRADA: …", "…", "FECHAMENTO: …"]},
                 "curto": {"nome": "Shorts", "minutos": 1, "estrutura": ["Fato estranho", "Explicação", "Pergunta final"]}},
    "regras": ["Falar o nome do canal no momento certo, sempre.", "Só fatos das fontes; lenda dita como lenda."]}
EXEMPLO_DIRECAO = {
    "_sobre": "Estilo de direção do canal no editor. Os ids vêm do catálogo do editor (veja a lista na página 📘 Como montar o "
              "pacote); id que não existe nesta instalação é ignorado. pct = em quantos % das cenas o eixo aparece; peso = chance.",
    "nome": "🎨 Meu Canal — colagem noir", "descricao": "Uma frase sobre o estilo.", "ritmo": "equilibrado",
    "cores": {"ativa": True, "modo": "predef", "primaria": "#E8DDC5", "secundaria": "#080807", "acento": "#C51F27"},
    "filtros": {"pct": 30, "itens": [{"id": "noir_soft", "peso": 2}]},
    "efeitos": {"pct": 70, "itens": [{"id": "zoom_respiro", "peso": 4}, {"id": "ov_poeira", "peso": 2}]},
    "transicoes": {"pct": 30, "itens": [{"id": "book_flip", "peso": 2}, {"id": "corte_pro_preto_doc", "peso": 2}]},
    "entradas": {"pct": 20, "itens": [{"id": "recorte_cai", "peso": 3}]},
    "templates": {"pct": 5, "itens": [{"id": "ED_ARTIGO", "peso": 1}]},
    "destaques": {"ativo": True, "densidade": "equilibrado", "estilos": ["recorte", "dossie_maquina_escrever", "selo_ano"]},
    "editoriais": {"ativo": True, "densidade": "equilibrado", "tipos": ["recortes", "pagina", "numero"]}}
EXEMPLO_PERSONAGENS = {
    "_sobre": "Canal com personagens fixos (opcional). O roteiro sai multi voz: [narrador] … [mira|curiosa] … [vanta] …",
    "narrador": {"nome": "Narrador", "papel": "explica e organiza a evidência", "fala": "claro, contemplativo",
                 "voz_sugerida": {"genero": "neutro", "idade": "adulto", "motor": "chatterbox", "descricao": "voz calma de documentário",
                                  "exag": 0.45, "cfg": 0.5, "vel": 0.95},
                 "emocoes": {"neutro": {"exag": 0.45, "cfg": 0.5}, "tenso": {"exag": 0.6, "cfg": 0.45, "descricao": "virada"}}},
    "personagens": [{"slug": "mira", "nome": "Mira", "epiteto": "Die Sternensucherin", "papel": "abre a curiosidade do público",
                     "personalidade": ["curiosa", "melancólica"], "fala": "perguntas sinceras e curtas",
                     "funcao_no_video": "faz a pergunta leiga", "quando_aparece": "abre perguntas, reage à escala",
                     "quando_nao_aparece": "no meio da explicação do mecanismo; nunca como fonte do dado científico",
                     "motivacao": "entender o Universo", "segredo": "lacunas de memória (não revelar à toa)",
                     "voz_sugerida": {"genero": "feminino", "idade": "jovem adulta", "motor": "chatterbox", "exag": 0.55, "cfg": 0.45},
                     "emocoes": {"curiosa": {"exag": 0.6, "cfg": 0.45, "descricao": "pergunta"}, "triste": {"exag": 0.4, "cfg": 0.35}},
                     "visual_en": "Mira: pale young woman, long straight black hair with blunt bangs, crescent moon ornament …",
                     "evitar_en": "different hair color, missing crescent ornament",
                     "poses_json": "personagens/mira.json"}],
    "estilo_personagens_en": "characters simpler and less detailed than the backgrounds, clean line art, flat cel shading",
    "relacao": {"dinamica": "Mira pergunta, Vanta contesta", "regra": "a lore nunca é necessária pra entender a ciência"},
    "regras_dialogo": ["Cada fala acrescenta pergunta, contraste, clareza ou ritmo; diálogo decorativo sai."],
    "ferramentas_narrativas": ["Narração, pergunta, contestação, trecho só de diálogo, pista de lore — usadas quando servem."]}
EXEMPLO_POSES_PERSONAGEM = {
    "formato": "personagens_pod_v1", "personagem": "mira", "nome": "Mira",
    "texto_fixo": {"trava": "MIRA — CHARACTER LOCK: young woman, long straight deep-black hair, blunt bangs, navy headband, gold "
                            "crescent moon on the right side, two blue tear marks under each eye, black gothic dress with ivory ruffles. "
                            "NEVER: short hair, other hair color, missing tear marks.",
                   "estilo": "ART STYLE: original 2D anime illustration, crisp dark ink outlines, cel shading, flat clean colors.",
                   "regras": "FRAMING: one character alone, half-body from the top of the head to the hips, the whole head inside the "
                             "image with green space above, margin on both sides. Flat chroma-key GREEN background (#00FF00). "
                             "No text."},
    "fundo": "verde", "flow": {"proporcao": "3:4"}, "canvas": [1200, 1800], "altura_personagem": 0.95,
    "poses": [{"arquivo": "mira_neutra_esq.png", "tipo": "pose", "grupo": "reacao", "prioridade": 1, "mestre": True,
               "descricao_pt": "neutra, mãos juntas", "prompt": "neutral, hands gently clasped; 3/4 view toward image-LEFT; half-body."},
              {"arquivo": "mira_neutra_esq_boca.png", "tipo": "boca", "base": "mira_neutra_esq.png", "grupo": "boca", "prioridade": 1,
               "prompt": "Keep everything identical; change ONLY the mouth: slightly open, as if speaking."},
              {"arquivo": "mira_lupa_esq.png", "tipo": "pose", "grupo": "objeto", "prioridade": 2,
               "descricao_pt": "olhando com uma lupa", "prompt": "holding an antique brass magnifying glass, curious; toward image-LEFT; half-body."}]}
EXEMPLO_CONTINUIDADE = {"regras": ["uma pista por vez; respostas parciais"],
                        "pistas": [{"clue_id": "estrela_riscada", "simbolo": "Estrela riscada numa foto antiga",
                                    "pergunta": "quem tentou apagá-la?", "estado": "planned"}]}
CHAVES_GUIA = {
    "schema": f'"{SCHEMA}" (obrigatório, exatamente assim)',
    "project": "name, channel_language, positioning, editorial_rule, brand_slogan_* (o nome do canal sai daqui)",
    "design_system.palette": '[{"token", "hex", "role", "share_guideline"}] — preto/escuros, claros e a cor de sinalização',
    "design_system.palette_rules / typography": "regras de cor e as fontes (manchete e etiquetas)",
    "mascot": "role, design_bible (silhouette, face, body_color, outline, canonical_pose, allowed_variations, invariants, never_change), "
              "consistency_protocol, prompt_lock_en, negative_prompt_en, canonical_reference_files",
    "generation_system": "style_lock_en, negative_prompt_global_en, base_prompt_template_en (com SUBJECT: [..] VISUAL QUESTION: [..] "
                         "COMPOSITION: [..] MASCOT: [..] BRAND STYLE: [..]), scene_prompt_template_en, thumbnail_prompt_template_en "
                         "([topic]), quality_checklist; opcionais (v84_367): allowed_image_types (ex.: [\"ambiente\", \"close\"]), "
                         "image_types_en ({tipo: texto em inglês}), real_subject_render_en (como a pessoa/objeto da sua foto entra)",
}


def _ids_catalogo() -> Dict[str, List[str]]:
    """Os ids do editor que uma direcao.json pode usar (por eixo) — vai no pedido pra IA e na página."""
    out: Dict[str, List[str]] = {}
    try:
        import dp_destaques
        import dp_direcao
        import dp_visual
        for e in ("filtros", "transicoes", "entradas", "templates"):
            out[e] = sorted(dp_direcao._ids_validos(e))
        out["efeitos"] = sorted(set(dp_visual.EFEITO_PARA_ZOOM) | {x["id"] for x in dp_visual.efeitos()})
        out["destaques"] = sorted(dp_destaques.catalogo())
    except Exception:  # noqa: BLE001
        pass
    out["editoriais"] = ["ficha", "linha_tempo", "pagina", "nome", "numero", "mural", "recortes", "bilhetes", "post",
                         "reescrita", "titulo_video", "terminal"]
    return out


def direcoes_do_editor() -> List[Dict[str, str]]:
    try:
        import dp_direcao
        return [{"id": d["id"], "nome": d["nome"]} for d in dp_direcao.direcoes(False)]
    except Exception:  # noqa: BLE001
        return []


def prompt_montar_pacote(tem_brand_kit: bool = True) -> str:
    """O pedido pra colar no Claude (ou outra IA com arquivos) junto com as imagens/Brand Kit → o .zip do pacote."""
    estrutura = "\n".join(f"- {rel}  [{nivel}] — {oque}" for rel, nivel, oque in ESTRUTURA_PACOTE)
    chaves = "\n".join(f"  - {k}: {v}" for k, v in CHAVES_GUIA.items())
    passo_guia = ("Use o brand_guide.json que vai em anexo COMO ESTÁ (não reescreva nem \"melhore\" — é a especificação principal)."
                  if tem_brand_kit else
                  "Ainda não tenho o brand_guide.json: crie um a partir das imagens e da descrição do canal que mando, com estas chaves "
                  f"(os textos *_en em inglês):\n{chaves}\n  Descreva só o que está nas imagens — não invente uma identidade nova.")
    return f"""Monte um PACOTE DE CANAL pro meu editor de vídeo (BestEditor), em um arquivo .zip, seguindo à risca o formato abaixo.
Os arquivos que mando em anexo: o Brand Kit do canal (JSON + imagens) e/ou imagens do mascote e do estilo.

1. {passo_guia}
2. Leia o JSON inteiro e examine TODAS as imagens. Não invente identidade visual: tudo sai do JSON e das imagens oficiais.
3. Organize em uma pasta <slug>/ (slug = nome do canal em minúsculas, sem acento, com _ ), com esta estrutura:
{estrutura}

Regras de cada parte:
- pacote.json: {json.dumps(EXEMPLO_PACOTE, ensure_ascii=False)}
- assets/: as imagens oficiais, com os nomes originais, sem mexer nelas.
- referencias/poses/pose_<id>.png: RECORTE (não redesenhe) o mascote de cada pose do painel oficial, com uma margem pequena,
  ids: normal, curioso, surpreso, investigando, explicando, estudando, sem_ideia, ideia (o que existir). Sem texto/rótulo no recorte.
- referencias/mascote_proporcoes.png: vários quadros do mascote INTEIRO (da cabeça aos pés) lado a lado sobre fundo escuro,
  tirados das imagens oficiais/do desenho original — é a referência de PROPORÇÃO que vai em toda geração. Sem texto.
- referencias/silhuetas/: a forma do mascote em preto sólido sobre o papel claro da paleta (opcional).
- referencias/estilo_colagem_*.png: recortes do banner/painel que mostram o estilo e a paleta, SEM nenhum texto.
- Nenhuma imagem de referencias/ ou folha_mestra/ pode ter texto (texto em referência vaza pra imagem gerada).
  Imagens com texto só em exemplos_alvo/. Versões erradas do personagem (de outra IA) em referencias_rejeitadas/.
- reforcos.json: {json.dumps(EXEMPLO_REFORCOS, ensure_ascii=False)}
  Escreva a trava de proporção olhando as imagens oficiais (tamanho da cabeça, comprimento das pernas, boca/sem boca…)
  e o design_bible do JSON. É o que impede a IA de desenhar um mascote "parecido" mas errado.
- poses_sugeridas.json: {json.dumps(EXEMPLO_POSES, ensure_ascii=False)} (20 a 100 poses que combinam com o canal).
- modelo_roteiro.json (o roteiro do canal): {json.dumps(EXEMPLO_MODELO, ensure_ascii=False)}
  Se eu mandar um roteiro de exemplo, modele a estrutura dele (gancho, viradas, ritmo, humor, final) nos "formatos".
  As regras seguem o editorial_rule do JSON; "nome_canal" é o nome falado no vídeo. Opcional: "direcao_sugerida" com o id de
  uma direção do editor (ex.: "sys_true_crime", "sys_dossie_papel", "sys_mistere") quando o pacote não trouxer direcao.json.
- personagens.json, lore.md, continuidade.json, docs/ (OPCIONAIS — só se o canal tem PERSONAGENS fixos que falam):
  personagens.json: {json.dumps(EXEMPLO_PERSONAGENS, ensure_ascii=False)}
  Para cada personagem: QUANDO aparece e QUANDO NÃO aparece, como fala, motivação/segredo (vindos da lore), emoções da voz
  (Chatterbox: exag 0.25–1.0 intensidade, cfg 0.2–0.7, vel 0.85–1.15), voz sugerida, visual_en (o lock do desenho) e
  "poses_json": "personagens/<slug>.json". As personagens NÃO são desenhadas nas cenas e nada de character sheet / pose sheet
  junto das referências de vídeo: elas viram PNG transparentes por cima do vídeo (nos melhores momentos em que falam),
  geradas na aba 🧍 Personagens a partir do JSON de poses + a ficha em personagens/<slug>_ficha.png (um recorte limpo, sem
  texto; até 3: _ficha.png, _ficha_2.png). Canal com UM mascote apresentador (sem personagens.json): o mesmo
  personagens/<slug>.json e, no pacote.json, "personagens_editor": {{"ativo": true, "narrador_personagem": "<slug>",
  "frequencia": 0.3, "boca": false}} — ele ilustra algumas frases da narração. A cena fica só com o ESTILO do canal (fotos
  realistas ou a estética única dele); o personagem PNG é desenhado nesse mesmo estilo. personagens/<slug>.json (um por personagem): {json.dumps(EXEMPLO_POSES_PERSONAGEM, ensure_ascii=False)}
  — "texto_fixo.trava" = a trava do desenho em inglês (cabelo, olhos, roupa, acessórios, o que NUNCA muda), "estilo" = o estilo
  de desenho, "regras" = enquadramento (meio corpo, da cabeça ao quadril, cabeça inteira e margem dos lados) + fundo verde
  chroma key; "poses" = 30 a 100 poses (reações, segurando objetos do canal, cada uma _esq/_dir, e as "_boca" das principais),
  uma com "mestre": true. lore.md = a bíblia da lore; continuidade.json:
  {json.dumps(EXEMPLO_CONTINUIDADE, ensure_ascii=False)}; docs/ = manuais e roteiro exemplo (.md). No modelo_roteiro.json,
  "roteiro_exemplo": "docs/<arquivo>.md" faz o 📐 do modelo vir preenchido. O roteiro sai só com narração e falas (sem VISUAL).
- direcao.json (OPCIONAL — o estilo de edição do canal no editor): {json.dumps(EXEMPLO_DIRECAO, ensure_ascii=False)}
  Monte a partir do JSON da marca (cores, textura, iluminação, composição, ritmo) e dos exemplos de vídeo: cor = paleta da marca,
  movimentos/transições/entradas que combinem com o material (colagem de papel → páginas e recortes; documentário → corte
  seco e corte pro preto), textos na tela no tipo da tipografia da marca. Use SÓ ids desta lista (os que não existirem são
  ignorados): {", ".join(f"{k}: {', '.join(v)}" for k, v in _ids_catalogo().items())}
- Só PNG/JPG/WEBP/GIF e os JSON acima; JSON em UTF-8 válido.
4. No fim, me diga em uma lista o que ficou faltando (o que é [recomendado] e não deu pra fazer) e me entregue o .zip.
Eu importo o .zip na aba 🎨 Identidade visual → Importar pacote."""


def zip_modelo_vazio() -> bytes:
    """📦 Um pacote de exemplo vazio (as pastas, os JSON de exemplo e o LEIA-ME) pra você ou a IA preencher."""
    buf = io.BytesIO()
    r = "meu_canal/"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(r + "pacote.json", json.dumps(EXEMPLO_PACOTE, ensure_ascii=False, indent=1))
        z.writestr(r + "reforcos.json", json.dumps(EXEMPLO_REFORCOS, ensure_ascii=False, indent=1))
        z.writestr(r + "poses_sugeridas.json", json.dumps(EXEMPLO_POSES, ensure_ascii=False, indent=1))
        z.writestr(r + "modelo_roteiro.json", json.dumps(EXEMPLO_MODELO, ensure_ascii=False, indent=1))
        z.writestr(r + "direcao.json", json.dumps(EXEMPLO_DIRECAO, ensure_ascii=False, indent=1))
        z.writestr(r + "personagens.json", json.dumps(EXEMPLO_PERSONAGENS, ensure_ascii=False, indent=1))
        z.writestr(r + "continuidade.json", json.dumps(EXEMPLO_CONTINUIDADE, ensure_ascii=False, indent=1))
        z.writestr(r + "lore.md", "# Bíblia da lore (opcional)\n\nPremissa, personagens, relação, lugares, pistas, regras de revelação.\n")
        z.writestr(r + "docs/COLOQUE_AQUI.txt", "manuais do canal e roteiro exemplo (.md)")
        z.writestr(r + "personagens/mira.json", json.dumps(EXEMPLO_POSES_PERSONAGEM, ensure_ascii=False, indent=1))
        z.writestr(r + "brand_guide.json.LEIA.txt", "Coloque aqui o brand_guide.json da marca (schema " + SCHEMA + ").\nChaves usadas:\n"
                   + "\n".join(f"- {k}: {v}" for k, v in CHAVES_GUIA.items()))
        for pasta in ("assets", "referencias/poses", "referencias/silhuetas", "referencias/animacao_original", "folha_mestra",
                      "exemplos_alvo", "referencias_rejeitadas"):
            oque = next((o for rel, _n, o in ESTRUTURA_PACOTE if rel.startswith(pasta)), "")
            z.writestr(f"{r}{pasta}/COLOQUE_AQUI.txt", oque or "imagens")
        z.writestr(r + "LEIA-ME.txt", "Pacote de canal do BestEditor — estrutura:\n\n"
                   + "\n".join(f"{rel}  [{nivel}]  {oque}" for rel, nivel, oque in ESTRUTURA_PACOTE)
                   + "\n\nPedido pronto pra IA montar:\n\n" + prompt_montar_pacote())
    return buf.getvalue()
