"""
modelados.py
=============

🎞️ VÍDEOS MODELADOS — um vídeo curto (Short, 9:16 por padrão) feito de cenas
geradas por IA num ESTILO fixo (ex.: Kamishibai), com narração e diálogos.

Fluxo (cada etapa grava em `modelados/<id>/projeto.json`):

  1. TEMA -> PROMPT MASTER. O site junta o estilo (instruções de roteiro, o
     molde do prompt da imagem e o da animação), as VOZES cadastradas (slug,
     nome, gênero, descrição, se aceitam tags do Chatterbox Turbo) e o formato
     JSON pedido. Você cola na IA e cola a resposta de volta.
  2. ROTEIRO (JSON) -> ÁUDIO. Cada fala é gerada com a voz do slug (motor da
     voz cadastrada), as pontas de silêncio são cortadas e as falas são
     juntadas com a pausa pedida. Como cada fala é gerada separada, o tempo de
     início/fim de cada uma é EXATO -> .srt perfeito (um com nome do
     personagem, um limpo pra legenda) e a linha do tempo das falas.
  3. AJUSTE DE TEMPOS. Um 2º prompt manda pra IA os tempos REAIS das falas +
     as cenas planejadas; ela devolve as cenas com início/fim (pode juntar,
     dividir, criar ou cortar cenas e corrigir a animação). Também dá pra
     distribuir sem IA (⚡ automático).
  4. FRAMES (Flow, imagem) -> 5. ANIMAÇÃO (Flow, vídeo com frame inicial).
  6. EDITOR: vira um projeto normal do Estúdio — cada cena é um trecho com o
     vídeo animado no tempo certo, o áudio completo é a narração e a legenda
     (estilo escolhido) já vem ligada.

Os moldes de prompt de um estilo usam {cena} (descrição da imagem, em inglês),
{movimento} (câmera/animação, em inglês) e {ar} (proporção: 9:16, 16:9, 1:1).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_AQUI = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_ESTILOS = os.path.join(_AQUI, "estilos_modelados.json")
_TRAVA = threading.Lock()

FORMATOS = ("9:16", "16:9", "1:1")
DURACOES_VIDEO = ("4s", "6s", "8s", "10s")
RESOLUCOES_VIDEO = ("360p", "720p")
TIPOS_FALA = ("narracao", "dialogo", "pensamento")
PALAVRAS_POR_SEGUNDO = 2.5  # ritmo médio de narração em português

ESTILO_KAMISHIBAI: Dict[str, Any] = {
    "id": "kamishibai",
    "nome": "Kamishibai — terror retrô",
    "embutido": True,
    "descricao": "Teatro de papel japonês: ilustração recortada em papel envelhecido, horror anime retrô, "
                 "sombras profundas, animação de bonecos de papel a 8 fps.",
    "instrucoes_roteiro": (
        "Conte como um contador de kamishibai de rua: um narrador que prende a atenção desde a primeira frase, "
        "frases curtas, suspense crescente, pausas dramáticas e um final arrepiante (ou uma reviravolta). "
        "Diálogos curtos e marcantes entre os personagens quando fizer sentido. Lendas e contos de terror "
        "japoneses (yokai, yurei, onryo) combinam muito com o estilo, mas siga o tema pedido."
    ),
    "prompt_imagem": (
        "{cena}, Japanese kamishibai paper theater style, traditional paper cutout illustration, retro horror "
        "anime aesthetic, textured aged paper grain, muted colors, deep creepy shadows, full frame, edge-to-edge "
        "illustration, no frame, no borders, no margins, no wooden frame, no text --ar {ar}"
    ),
    "prompt_animacao": (
        "{movimento}, low frame rate 2D cutout animation, paper puppet style movement, choppy frame-by-frame "
        "motion, no smooth interpolation, retro Japanese horror aesthetic, 8fps."
    ),
    "exemplos_movimento": [
        "Camera panning slowly from left to right",
        "Slow push-in on the character's face while the paper lantern flickers",
        "The ghost paper puppet slides in from the right edge, swaying",
        "Paper layers shift with parallax, fog drifts across the foreground",
    ],
    "formato": "9:16",
    "duracao_cena": 4,
    "duracao_alvo": 60,
    "idioma": "English",
    "flow": {"modelo_imagem": "Nano Banana 2.1", "modelo_video": "Omni 1.1 Flash",
             "resolucao": "720p", "duracao_video": "4s"},
    "legenda": "classico",
}
_EMBUTIDOS = {"kamishibai": ESTILO_KAMISHIBAI}


class ModeladoError(Exception):
    """Erro de uso (JSON inválido, voz sem cadastro, etapa fora de ordem...)."""


# ===================================================================== estilos
def _ler_estilos() -> Dict[str, Dict[str, Any]]:
    try:
        with open(ARQUIVO_ESTILOS, encoding="utf-8") as f:
            d = json.load(f)
        lista = d.get("estilos") if isinstance(d, dict) else d
        return {e["id"]: e for e in lista or [] if isinstance(e, dict) and e.get("id")}
    except (OSError, ValueError):
        return {}


def _gravar_estilos(estilos: Dict[str, Dict[str, Any]]) -> None:
    tmp = ARQUIVO_ESTILOS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"estilos": list(estilos.values())}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ARQUIVO_ESTILOS)


def _slug(t: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:40]


def _mesclar_padrao(e: Dict[str, Any]) -> Dict[str, Any]:
    base = json.loads(json.dumps(ESTILO_KAMISHIBAI))
    base.update({"embutido": False, "exemplos_movimento": []})
    out = {**base, **{k: v for k, v in e.items() if v is not None}}
    out["flow"] = {**base["flow"], **(e.get("flow") or {})}
    return out


def listar_estilos() -> List[Dict[str, Any]]:
    salvos = _ler_estilos()
    out = []
    for eid, padrao in _EMBUTIDOS.items():
        e = dict(padrao)
        if eid in salvos:  # versão editada do embutido
            e = {**e, **salvos[eid], "embutido": True, "editado": True}
            e["flow"] = {**padrao["flow"], **(salvos[eid].get("flow") or {})}
        out.append(e)
    out += [_mesclar_padrao(e) for eid, e in salvos.items() if eid not in _EMBUTIDOS]
    return out


def obter_estilo(estilo_id: str) -> Dict[str, Any]:
    for e in listar_estilos():
        if e["id"] == estilo_id:
            return e
    raise ModeladoError(f"Estilo {estilo_id!r} não encontrado.")


def salvar_estilo(d: Dict[str, Any], id_antigo: Optional[str] = None) -> Dict[str, Any]:
    nome = str(d.get("nome") or "").strip()[:60]
    if not nome:
        raise ModeladoError("Dê um nome pro estilo.")
    eid = _slug(d.get("id") or id_antigo or nome)
    if not eid:
        raise ModeladoError("Nome do estilo inválido.")
    pi = str(d.get("prompt_imagem") or "").strip()
    pa = str(d.get("prompt_animacao") or "").strip()
    if "{cena}" not in pi:
        raise ModeladoError("O molde do prompt da IMAGEM precisa ter {cena} (onde entra a descrição de cada cena).")
    if "{movimento}" not in pa:
        raise ModeladoError("O molde do prompt da ANIMAÇÃO precisa ter {movimento} (onde entra o movimento de cada cena).")
    formato = d.get("formato") if d.get("formato") in FORMATOS else "9:16"
    try:
        duracao_cena = max(2.0, min(10.0, float(d.get("duracao_cena") or 4)))
        duracao_alvo = max(10, min(600, int(float(d.get("duracao_alvo") or 60))))
    except (TypeError, ValueError) as exc:
        raise ModeladoError("Duração da cena / do vídeo precisa ser um número.") from exc
    fl = d.get("flow") if isinstance(d.get("flow"), dict) else {}
    flow = {
        "modelo_imagem": str(fl.get("modelo_imagem") or "").strip()[:60],
        "modelo_video": str(fl.get("modelo_video") or "Omni 1.1 Flash").strip()[:60],
        "resolucao": fl.get("resolucao") if fl.get("resolucao") in RESOLUCOES_VIDEO else "720p",
        "duracao_video": fl.get("duracao_video") if fl.get("duracao_video") in DURACOES_VIDEO + ("auto",) else "4s",
    }
    exemplos = d.get("exemplos_movimento") or []
    if isinstance(exemplos, str):
        exemplos = [x.strip() for x in exemplos.splitlines() if x.strip()]
    estilo = {
        "id": eid, "nome": nome, "descricao": str(d.get("descricao") or "").strip()[:400],
        "instrucoes_roteiro": str(d.get("instrucoes_roteiro") or "").strip()[:4000],
        "prompt_imagem": pi[:2000], "prompt_animacao": pa[:2000],
        "exemplos_movimento": [str(x)[:200] for x in exemplos][:12],
        "formato": formato, "duracao_cena": duracao_cena, "duracao_alvo": duracao_alvo,
        "idioma": str(d.get("idioma") or "português do Brasil").strip()[:60],
        "flow": flow, "legenda": str(d.get("legenda") or "classico")[:30],
    }
    with _TRAVA:
        estilos = _ler_estilos()
        if id_antigo and id_antigo != eid:
            if id_antigo in _EMBUTIDOS:
                raise ModeladoError("O id do estilo embutido não pode mudar — salve como um estilo novo.")
            estilos.pop(id_antigo, None)
        if eid in estilos and eid != id_antigo and not d.get("_sobrescrever"):
            raise ModeladoError(f"Já existe um estilo com o id {eid!r}.")
        if eid in _EMBUTIDOS and not id_antigo and not d.get("_sobrescrever"):
            raise ModeladoError(f"{eid!r} é um estilo embutido — edite ele em vez de criar outro com o mesmo nome.")
        estilos[eid] = estilo
        _gravar_estilos(estilos)
    return obter_estilo(eid)


def apagar_estilo(estilo_id: str) -> bool:
    """Estilo do usuário: apaga. Estilo embutido: volta ao padrão de fábrica."""
    with _TRAVA:
        estilos = _ler_estilos()
        if estilo_id not in estilos:
            return False
        estilos.pop(estilo_id)
        _gravar_estilos(estilos)
    return True


# ===================================================================== projetos
def pasta_raiz(base_dir: str) -> Path:
    p = Path(base_dir) / "modelados"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _id_seguro(pid: str) -> str:
    s = "".join(c for c in str(pid or "") if c.isalnum() or c in "_-")
    if not s:
        raise ModeladoError("Projeto inválido.")
    return s


def pasta_projeto(base_dir: str, pid: str) -> Path:
    return pasta_raiz(base_dir) / _id_seguro(pid)


def criar_projeto(base_dir: str, nome: str, estilo_id: str, tema: str, duracao_alvo: Optional[float] = None,
                  formato: Optional[str] = None, idioma: Optional[str] = None, instrucoes_extra: str = "") -> Dict[str, Any]:
    estilo = obter_estilo(estilo_id)
    tema = str(tema or "").strip()
    if not tema:
        raise ModeladoError("Escreva o tema (ou a lenda) do vídeo.")
    pid = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:5]
    try:
        alvo = int(float(duracao_alvo)) if duracao_alvo not in (None, "") else int(estilo["duracao_alvo"])
    except (TypeError, ValueError):
        alvo = int(estilo["duracao_alvo"])
    proj = {
        "id": pid, "nome": (str(nome or "").strip() or tema[:50])[:80], "criado": time.time(),
        "estilo_id": estilo["id"], "tema": tema[:4000], "duracao_alvo": max(10, min(600, alvo)),
        "formato": formato if formato in FORMATOS else estilo.get("formato") or "9:16",
        "idioma": (str(idioma or "").strip() or estilo.get("idioma") or "português do Brasil")[:60],
        "instrucoes_extra": str(instrucoes_extra or "").strip()[:3000],
        "etapa": "roteiro", "roteiro": None, "audio": None, "cenas": [], "job_id": None, "avisos": [],
    }
    pasta = pasta_projeto(base_dir, pid)
    for sub in ("", "falas", "frames", "videos"):
        (pasta / sub).mkdir(parents=True, exist_ok=True)
    salvar_projeto(base_dir, proj)
    return proj


def carregar_projeto(base_dir: str, pid: str) -> Dict[str, Any]:
    caminho = pasta_projeto(base_dir, pid) / "projeto.json"
    if not caminho.exists():
        raise ModeladoError("Projeto não encontrado.")
    return json.loads(caminho.read_text(encoding="utf-8"))


def salvar_projeto(base_dir: str, proj: Dict[str, Any]) -> None:
    pasta = pasta_projeto(base_dir, proj["id"])
    pasta.mkdir(parents=True, exist_ok=True)
    tmp = pasta / "projeto.json.tmp"
    tmp.write_text(json.dumps(proj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, pasta / "projeto.json")


def listar_projetos(base_dir: str) -> List[Dict[str, Any]]:
    out = []
    for p in sorted(pasta_raiz(base_dir).iterdir(), reverse=True):
        try:
            d = json.loads((p / "projeto.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cenas = d.get("cenas") or []
        out.append({"id": d["id"], "nome": d.get("nome"), "estilo_id": d.get("estilo_id"), "etapa": d.get("etapa"),
                    "criado": d.get("criado"), "formato": d.get("formato"), "cenas": len(cenas),
                    "videos": sum(1 for c in cenas if c.get("video")), "job_id": d.get("job_id"),
                    "duracao": (d.get("audio") or {}).get("duracao")})
    return out


def excluir_projeto(base_dir: str, pid: str) -> None:
    shutil.rmtree(pasta_projeto(base_dir, pid), ignore_errors=True)


# ===================================================================== vozes
# Motor padrão dos Vídeos modelados: Chatterbox Turbo — fala INGLÊS e é o único
# que transforma as tags ([whispering], [gasp]...) em som/estilo.
MOTOR_PADRAO = "chatterbox_turbo"
VOZ_PADRAO: Dict[str, Any] = {
    "slug": "narrator", "nome": "Narrator (voz embutida)", "motor": MOTOR_PADRAO, "config": {}, "cor": "#7c3aed",
    "genero": "", "idade": "", "descricao": "voz embutida do Chatterbox Turbo (inglês, aceita tags)", "virtual": True,
}


def _perfis_salvos() -> List[str]:
    """Os perfis de voz (🗣️ Perfis de voz) — cada um vira uma voz Chatterbox Turbo."""
    try:
        from tts.voice_generator import listar_perfis_de_voz
        return list(listar_perfis_de_voz())
    except Exception:  # noqa: BLE001
        return []


def vozes_efetivas(cadastradas: Optional[List[Dict[str, Any]]] = None,
                   perfis: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Vozes que o roteiro pode usar:
      1. as vozes com slug cadastradas;
      2. cada PERFIL DE VOZ que ainda não tem voz com slug vira uma voz Chatterbox
         Turbo automática (slug = nome do perfil, gênero/idade do perfil);
      3. a voz embutida do Chatterbox Turbo como [narrator], se não houver outra com esse slug."""
    import multivoz
    import perfis_info
    vozes = [dict(v) for v in (multivoz.listar() if cadastradas is None else cadastradas)]
    perfis = _perfis_salvos() if perfis is None else perfis
    slugs = {v["slug"] for v in vozes}
    usados = {(v.get("config") or {}).get("vozPerfil") for v in vozes}
    for k, nome in enumerate(perfis):
        if nome in usados:
            continue
        slug = multivoz.slugify(nome)
        if not slug or slug in slugs:
            continue
        info = perfis_info.obter(nome)
        vozes.append({"slug": slug, "nome": nome, "motor": MOTOR_PADRAO, "config": {"vozPerfil": nome},
                      "cor": multivoz.CORES[(len(vozes) + k) % len(multivoz.CORES)],
                      "genero": info.get("genero") or "", "idade": info.get("idade") or "",
                      "descricao": info.get("descricao") or "perfil de voz (Chatterbox Turbo, inglês)",
                      "virtual": True, "do_perfil": True, "perfil": nome})
        slugs.add(slug)
    if "narrator" not in slugs:
        vozes.append(dict(VOZ_PADRAO))
    return vozes


def criar_vozes_padrao(perfis: List[str]) -> List[Dict[str, Any]]:
    """Cadastra vozes Chatterbox Turbo com slug: a voz embutida ("narrator") e
    uma por perfil de voz salvo (clonagem). Não mexe nas que já existem."""
    import multivoz
    existentes = multivoz.por_slug()
    criadas = []
    pedidos = [("Narrator", "narrator", {}, VOZ_PADRAO["descricao"])]
    pedidos += [(p, multivoz.slugify(p), {"vozPerfil": p}, f"perfil de voz \"{p}\" no Chatterbox Turbo (inglês)") for p in perfis]
    for nome, slug, config, desc in pedidos:
        if not slug or slug in existentes:
            continue
        criadas.append(multivoz.salvar({"nome": nome[:40], "slug": slug, "motor": MOTOR_PADRAO, "config": config,
                                        "descricao": desc, "genero": ""}))
        existentes[slug] = criadas[-1]
    return criadas


def vozes_para_prompt(vozes: List[Dict[str, Any]], tags_turbo: Optional[set] = None) -> List[Dict[str, Any]]:
    import multivoz
    out = []
    for v in vozes:
        out.append({"slug": v["slug"], "nome": v.get("nome") or v["slug"],
                    "genero": v.get("genero") or "", "idade": v.get("idade") or "",
                    "genero_rotulo": multivoz.rotulo_genero(v),
                    "descricao": v.get("descricao") or "", "motor": v.get("motor"),
                    "aceita_tags": v.get("motor") == "chatterbox_turbo",
                    "idioma": "inglês" if v.get("motor") == "chatterbox_turbo" else ((v.get("config") or {}).get("idioma") or "")})
    return out


def _tags_turbo() -> set:
    try:
        import multivoz
        return set(multivoz._tags_extras())
    except Exception:  # noqa: BLE001
        return set()


# ===================================================================== prompts
def _n_cenas(duracao: float, duracao_cena: float) -> int:
    return max(2, int(round(float(duracao) / max(1.0, float(duracao_cena)))))


def prompt_roteiro(proj: Dict[str, Any], estilo: Dict[str, Any], vozes: List[Dict[str, Any]],
                   tags: Optional[set] = None) -> str:
    """PROMPT MASTER: tema + estilo + vozes -> pede o roteiro completo em JSON."""
    vozes = vozes_efetivas(vozes)
    tags = sorted(_tags_turbo() if tags is None else tags)
    vp = vozes_para_prompt(vozes)
    alvo = float(proj.get("duracao_alvo") or estilo.get("duracao_alvo") or 60)
    dc = float(estilo.get("duracao_cena") or 4)
    n = _n_cenas(alvo, dc)
    palavras = int(alvo * PALAVRAS_POR_SEGUNDO)
    linhas_vozes = "\n".join(
        f'- "{v["slug"]}" = {v["nome"]} — {v["genero_rotulo"]}' + (f' — {v["descricao"]}' if v["descricao"] else "")
        + (" — ACEITA tags de áudio (Chatterbox Turbo, fala em INGLÊS)" if v["aceita_tags"] else "")
        for v in vp)
    sem_genero = [v["slug"] for v in vp if not v["genero"] and v["slug"] != "narrator"]
    exemplos = estilo.get("exemplos_movimento") or []
    ex_mov = ("\nExemplos de movimento nesse estilo: " + "; ".join(f'"{e}"' for e in exemplos[:6])) if exemplos else ""
    tem_turbo = any(v["aceita_tags"] for v in vp)
    so_turbo = all(v["aceita_tags"] for v in vp)
    so_padrao = len(vp) == 1 and vozes[0].get("virtual") and not vozes[0].get("do_perfil")
    bloco_tags = (
        f"\nTAGS DE ÁUDIO (Chatterbox, em inglês): {', '.join(tags)}.\n"
        "- Coloque as tags no campo \"tags\" da fala (lista), escolhendo só dessa lista — ex.: [\"whispering\"], [\"fear\", \"gasp\"].\n"
        "- Tags de SOM (laugh, chuckle, gasp, cough, sigh, groan, sniff, shush, clear throat) também podem ir NO MEIO do texto, "
        "entre colchetes, onde o som acontece: \"Eu vi... [gasp] ela estava lá.\"\n"
        "- Elas só viram som/estilo nas vozes que ACEITAM tags; nas outras o site tira as tags e usa \"emocao\" (0 a 1) pra "
        "dar intensidade. Mesmo assim, preencha as tags: elas documentam a interpretação.\n"
        if tags else "")
    return f"""Você é roteirista e diretor de animação de vídeos curtos (Shorts/Reels/TikTok).

TAREFA: escreva o roteiro COMPLETO de um vídeo no estilo "{estilo['nome']}" sobre o tema abaixo, já com a narração, os diálogos, a voz de cada fala, as tags de áudio e o plano de CENAS (uma imagem inicial + uma animação por cena). Responda SÓ com um JSON válido, sem texto antes ou depois, sem ```.

TEMA / LENDA:
{proj['tema']}
{('INSTRUÇÕES EXTRAS: ' + proj['instrucoes_extra']) if proj.get('instrucoes_extra') else ''}

ESTILO "{estilo['nome']}": {estilo.get('descricao') or ''}
Como contar: {estilo.get('instrucoes_roteiro') or 'livre'}

DURAÇÃO E RITMO
- Vídeo de ~{int(alvo)} segundos, formato {proj.get('formato', '9:16')} (vertical = enquadramentos pensados pra tela em pé, assunto centralizado).
- Idioma da narração e dos diálogos: {'ENGLISH (todas as vozes são Chatterbox Turbo, que só fala inglês — escreva TODAS as falas em inglês)' if so_turbo else (proj.get('idioma') or estilo.get('idioma')) + (' (as vozes marcadas como INGLÊS falam em inglês: se usar uma delas, escreva as falas dela em inglês)' if tem_turbo else '')}.
- ~{palavras} palavras faladas no total (~{PALAVRAS_POR_SEGUNDO:g} palavras por segundo).
- Os primeiros 3 segundos precisam de um gancho forte.

VOZES DISPONÍVEIS (use SÓ estes slugs no campo "voz"; respeite o GÊNERO e a IDADE: personagem feminina = voz feminina, criança = voz de criança, idoso = voz idosa; se não houver voz da idade certa, use a mais próxima):
{linhas_vozes}
{('ATENÇÃO: estas vozes não têm gênero definido, evite usá-las em personagens de gênero marcado: ' + ', '.join(sem_genero)) if sem_genero else ''}
{'- Só existe UMA voz: conte a história com o narrador (os diálogos, se houver, são lidos por ele mesmo — use "tipo": "dialogo" e o nome do personagem, sempre com essa voz).' if so_padrao else '- Uma voz pode fazer o narrador e outra os personagens; o mesmo personagem sempre com a mesma voz.'}
{bloco_tags}
FALAS ("falas", em ordem):
- "tipo": "narracao" (narrador), "dialogo" (personagem falando) ou "pensamento".
- "texto": exatamente o que será dito (sem nome do personagem, sem aspas, sem descrição de cena). Falas curtas: no máximo ~25 palavras cada; quebre falas longas.
- "emocao": 0.0 a 1.0 (0.3 = contido, 0.5 = normal, 0.8 = intenso).
- "pausa_depois": segundos de silêncio depois da fala (0.15 a 1.5) — use pausas maiores pra suspense.

CENAS ("cenas", em ordem) — cerca de {n} cenas de ~{dc:g}s cada (uma cena nova a cada ~{dc:g} segundos de fala):
- "falas": ids das falas que acontecem durante a cena (toda fala precisa estar em alguma cena; uma fala longa pode ocupar 2 cenas seguidas, repetindo o id).
- "cena": descrição da IMAGEM INICIAL da cena, em INGLÊS, concreta e visual (quem, onde, ação congelada, luz, enquadramento). NÃO escreva o estilo (ele é acrescentado pelo site), NÃO peça texto escrito na imagem. Repita a aparência fixa dos personagens (roupa, cabelo, idade) em toda cena em que aparecem, porque cada imagem é gerada separada.
- "movimento": como ANIMAR a imagem, em INGLÊS: movimento de câmera + o que se mexe na cena (curto, 1 frase), pensado pra ~{dc:g}s.{ex_mov}
- "duracao": segundos estimados da cena.

{__import__("metodo_roteiro").bloco("curto" if alvo <= 60 else "longo")}

{__import__("metodo_roteiro").bloco_titulos(1)}

Molde que o site usa na imagem: "{estilo['prompt_imagem']}"
Molde que o site usa na animação: "{estilo['prompt_animacao']}"

FORMATO EXATO DA RESPOSTA:
{{
  "titulo": "título do vídeo numa das fórmulas de título (até ~60 caracteres)",
  "sinopse": "1 frase",
  "personagens": [
    {{"nome": "Narrador", "voz": "{vp[0]['slug']}", "genero": "{vp[0]['genero'] or 'masculino'}", "idade": "{vp[0]['idade'] or 'adulto'}", "aparencia": ""}},
    {{"nome": "Nome do personagem", "voz": "slug", "genero": "feminino", "idade": "crianca | jovem | adulto | idoso", "aparencia": "in English: fixed visual description (age included)"}}
  ],
  "falas": [
    {{"id": 1, "tipo": "narracao", "personagem": "Narrador", "voz": "{vp[0]['slug']}", "texto": "...", "tags": ["narration"], "emocao": 0.5, "pausa_depois": 0.4}},
    {{"id": 2, "tipo": "dialogo", "personagem": "Nome do personagem", "voz": "slug", "texto": "...", "tags": ["whispering"], "emocao": 0.7, "pausa_depois": 0.6}}
  ],
  "cenas": [
    {{"id": 1, "falas": [1], "cena": "in English ...", "movimento": "in English ...", "duracao": {dc:g}}}
  ]
}}"""


def _bloco_falas_com_tempos(proj: Dict[str, Any]) -> str:
    audio = proj.get("audio") or {}
    linhas = []
    for f in audio.get("falas") or []:
        linhas.append(f'{f["id"]}: {f["inicio"]:.2f}s → {f["fim"]:.2f}s [{f.get("personagem") or f.get("voz")}] {f["texto"]}')
    return "\n".join(linhas)


def prompt_ajuste(proj: Dict[str, Any], estilo: Dict[str, Any]) -> str:
    """2º prompt: os tempos REAIS do áudio -> a IA devolve as cenas com início/fim."""
    audio = proj.get("audio") or {}
    if not audio.get("falas"):
        raise ModeladoError("Gere o áudio antes (o ajuste usa os tempos reais das falas).")
    total = float(audio.get("duracao") or 0)
    dmax = duracao_max_clipe(estilo)
    roteiro = proj.get("roteiro") or {}
    cenas = [{"id": c.get("id"), "falas": c.get("falas"), "cena": c.get("cena"), "movimento": c.get("movimento")}
             for c in (proj.get("cenas") or roteiro.get("cenas") or [])]
    personagens = roteiro.get("personagens") or []
    return f"""Você dirigiu o roteiro abaixo (estilo "{estilo['nome']}"). O áudio JÁ FOI GERADO: estes são os tempos REAIS de cada fala no áudio final (total {total:.2f}s).

FALAS (id: início → fim [quem] texto):
{_bloco_falas_com_tempos(proj)}

PERSONAGENS (aparência fixa — mantenha nas descrições):
{json.dumps(personagens, ensure_ascii=False)}

CENAS PLANEJADAS:
{json.dumps(cenas, ensure_ascii=False, indent=1)}

TAREFA: devolva as cenas FINAIS sincronizadas com o áudio real.
- Cada cena tem "inicio" e "fim" em segundos. A 1ª começa em 0, a última termina em {total:.2f}, sem buracos nem sobreposição (o "fim" de uma = o "inicio" da próxima).
- Cada cena dura no MÁXIMO {dmax:g}s (é o tamanho do vídeo gerado por cena) e no mínimo 1.5s. Se uma parte da fala ficou longa, DIVIDA em mais cenas (novos ângulos/momentos da mesma ação); se sobrou cena demais, junte ou corte.
- A troca de cena deve cair em momentos naturais (início de fala, pausa, virada da história). Uma cena de reação pode cobrir uma pausa.
- Corrija "movimento" pra caber no tempo da cena (cena curta = movimento simples) e combine o movimento com o que é dito naquele momento.
- "cena" e "movimento" continuam em INGLÊS, sem o texto do estilo (o site acrescenta) e sem pedir texto escrito na imagem.
- "falas": ids das falas que tocam durante a cena.

Responda SÓ com JSON válido, sem ```:
{{"cenas": [{{"id": 1, "inicio": 0.0, "fim": 3.8, "falas": [1], "cena": "...", "movimento": "..."}}]}}"""


# ===================================================================== JSON da IA
def extrair_json(texto: str) -> Any:
    """Acha o JSON na resposta da IA (aceita ```json, texto antes/depois e
    conserta o que o copiar/colar estraga — ver json_ia.py)."""
    import json_ia
    try:
        return json_ia.carregar(texto)
    except ValueError as exc:
        raise ModeladoError(str(exc)) from exc


_RE_TAG_INLINE = re.compile(r"\[\s*([^\[\]\n]{1,30}?)\s*\]")


def _float(v: Any, padrao: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return padrao


def validar_roteiro(dados: Any, vozes: List[Dict[str, Any]], tags: Optional[set] = None) -> Tuple[Dict[str, Any], List[str]]:
    """Normaliza o roteiro da IA. Erro se faltar fala/cena ou se usar voz que
    não existe (senão a fala sairia com a voz errada)."""
    import multivoz
    tags = _tags_turbo() if tags is None else set(tags)
    vozes = vozes_efetivas(vozes)
    if not isinstance(dados, dict):
        raise ModeladoError("A resposta precisa ser um objeto JSON com \"falas\" e \"cenas\".")
    por_slug = {v["slug"]: v for v in vozes}
    por_nome = {multivoz.slugify(v.get("nome") or ""): v["slug"] for v in vozes}
    avisos: List[str] = []
    personagens = [p for p in dados.get("personagens") or [] if isinstance(p, dict)]
    voz_do_personagem = {}
    for p in personagens:
        s = multivoz.slugify(p.get("voz") or "")
        if s in por_slug:
            voz_do_personagem[multivoz.slugify(p.get("nome") or "")] = s
    falas_in = dados.get("falas")
    if not isinstance(falas_in, list) or not falas_in:
        raise ModeladoError("O JSON não tem a lista \"falas\".")
    falas, ids, desconhecidas = [], set(), []
    for k, f in enumerate(falas_in, start=1):
        if not isinstance(f, dict):
            continue
        texto_bruto = str(f.get("texto") or "").strip()
        if not texto_bruto:
            continue
        fid = f.get("id")
        try:
            fid = int(fid)
        except (TypeError, ValueError):
            fid = k
        if fid in ids:
            fid = max(ids) + 1
        ids.add(fid)
        slug = multivoz.slugify(f.get("voz") or "")
        if slug not in por_slug:
            slug = por_nome.get(slug) or voz_do_personagem.get(multivoz.slugify(f.get("personagem") or "")) or ""
        if not slug:
            desconhecidas.append(str(f.get("voz") or f.get("personagem") or f"fala {fid}"))
        ftags = [str(t).strip().lower() for t in (f.get("tags") or []) if str(t).strip()] if isinstance(f.get("tags"), list) else []
        ruins = [t for t in ftags if t not in tags]
        ftags = [t for t in ftags if t in tags]
        inline_ruins = [m.group(1) for m in _RE_TAG_INLINE.finditer(texto_bruto) if m.group(1).strip().lower() not in tags]
        texto = _RE_TAG_INLINE.sub(lambda m: m.group(0) if m.group(1).strip().lower() in tags else "", texto_bruto)
        texto = re.sub(r"\s{2,}", " ", texto).strip()
        if ruins or inline_ruins:
            avisos.append(f"Fala {fid}: tag(s) desconhecida(s) ignorada(s): {', '.join(ruins + inline_ruins)}")
        tipo = f.get("tipo") if f.get("tipo") in TIPOS_FALA else ("dialogo" if f.get("personagem") and str(f.get("personagem")).lower() not in ("narrador", "narrator") else "narracao")
        falas.append({"id": fid, "tipo": tipo, "personagem": str(f.get("personagem") or ("Narrador" if tipo == "narracao" else ""))[:60],
                      "voz": slug, "texto": texto[:1200], "tags": ftags,
                      "emocao": _float(f.get("emocao"), 0.5, 0.0, 1.0),
                      "pausa_depois": _float(f.get("pausa_depois"), 0.35, 0.0, 3.0)})
    if desconhecidas:
        raise ModeladoError("A IA usou voz(es) que não existem: " + ", ".join(sorted(set(desconhecidas)))
                            + ". Use só os slugs cadastrados (" + ", ".join(por_slug) + ") — corrija no JSON ou peça de novo.")
    if not falas:
        raise ModeladoError("Nenhuma fala com texto no JSON.")
    ids_validos = {f["id"] for f in falas}
    cenas_in = dados.get("cenas")
    if not isinstance(cenas_in, list) or not cenas_in:
        raise ModeladoError("O JSON não tem a lista \"cenas\".")
    cenas = _normalizar_cenas(cenas_in, ids_validos, avisos)
    sem_cena = sorted(ids_validos - {i for c in cenas for i in c["falas"]})
    if sem_cena:
        avisos.append("Fala(s) sem cena: " + ", ".join(map(str, sem_cena)) + " — o ajuste de tempos (ou o ⚡ automático) cobre isso.")
    roteiro = {"titulo": str(dados.get("titulo") or "")[:120], "sinopse": str(dados.get("sinopse") or "")[:400],
               "personagens": [{"nome": str(p.get("nome") or "")[:60], "voz": multivoz.slugify(p.get("voz") or ""),
                                "genero": str(p.get("genero") or "")[:20], "idade": multivoz.normalizar_idade(p.get("idade")),
                                "aparencia": str(p.get("aparencia") or "")[:500]}
                               for p in personagens],
               "falas": falas, "cenas": cenas}
    for p in roteiro["personagens"]:
        v = por_slug.get(p["voz"])
        g = multivoz.normalizar_genero(p["genero"])
        if v and g and v.get("genero") and v["genero"] != g and g != "neutro":
            avisos.append(f"{p['nome'] or 'Personagem'} é {g}, mas a voz [{p['voz']}] está cadastrada como {v['genero']}.")
        if v and p.get("idade") and v.get("idade") and v["idade"] != p["idade"]:
            import perfis_info
            avisos.append(f"{p['nome'] or 'Personagem'} é {perfis_info.IDADES_ROTULO[p['idade']]}, mas a voz [{p['voz']}] "
                          f"é {perfis_info.IDADES_ROTULO[v['idade']]}.")
    return roteiro, avisos


def _normalizar_cenas(cenas_in: List[Any], ids_validos: set, avisos: List[str], com_tempo: bool = False) -> List[Dict[str, Any]]:
    cenas = []
    for k, c in enumerate(cenas_in, start=1):
        if not isinstance(c, dict):
            continue
        desc = str(c.get("cena") or c.get("imagem") or c.get("prompt_imagem") or "").strip()
        mov = str(c.get("movimento") or c.get("animacao") or c.get("prompt_animacao") or "").strip()
        if not desc:
            avisos.append(f"Cena {c.get('id', k)} sem descrição — ignorada.")
            continue
        fl = c.get("falas") if isinstance(c.get("falas"), list) else ([c["falas"]] if c.get("falas") not in (None, "") else [])
        fls = []
        for x in fl:
            try:
                x = int(x)
            except (TypeError, ValueError):
                continue
            if x in ids_validos and x not in fls:
                fls.append(x)
        cena = {"id": len(cenas) + 1, "falas": fls, "cena": desc[:1500], "movimento": (mov or "Slow camera push-in")[:600],
                "duracao": _float(c.get("duracao"), 0.0, 0.0, 60.0)}
        if com_tempo:
            cena["inicio"] = _float(c.get("inicio", c.get("start")), -1.0, -1.0, 100000.0)
            cena["fim"] = _float(c.get("fim", c.get("end")), -1.0, -1.0, 100000.0)
        cenas.append(cena)
    if not cenas:
        raise ModeladoError("Nenhuma cena válida no JSON (cada cena precisa de \"cena\" e \"movimento\").")
    return cenas


# ===================================================================== áudio
def texto_para_tts(fala: Dict[str, Any], motor: str) -> str:
    """O que vai pro motor: no Chatterbox Turbo as tags viram som/estilo (as do
    campo "tags" entram no começo); nos outros motores as tags saem."""
    import narracoes
    texto = fala.get("texto") or ""
    if motor == "chatterbox_turbo":
        prefixo = " ".join(f"[{t}]" for t in fala.get("tags") or [] if f"[{t}]" not in texto)
        texto = (prefixo + " " + texto).strip()
        return narracoes.limpar_texto_para_tts(texto, preservar_tags_chatterbox_turbo=True)
    texto = _RE_TAG_INLINE.sub(" ", texto)
    return narracoes.limpar_texto_para_tts(re.sub(r"\s{2,}", " ", texto).strip())


def _duracao(caminho: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                        "default=noprint_wrappers=1:nokey=1", caminho], capture_output=True, text=True, timeout=30)
    try:
        return float(r.stdout.strip())
    except ValueError as exc:
        raise ModeladoError(f"Não consegui medir a duração de {os.path.basename(caminho)}.") from exc


def _ffmpeg(args: List[str], erro: str, timeout: int = 600) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise ModeladoError(f"{erro}: {r.stderr[-300:]}")


def _cortar_pontas(origem: str, destino: str) -> None:
    # start_duration pequeno + start_silence: corta o silêncio mas deixa 40 ms de respiro em cada ponta
    # (com start_duration=0.05 o filtro comia o começo/fim da própria fala — consoantes cortadas)
    um = "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB:start_silence=0.04:detection=peak"
    filtro = f"{um},areverse,{um},areverse"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", origem, "-af", filtro, "-ar", "24000", "-ac", "1", destino],
                       capture_output=True, timeout=120)
    if r.returncode != 0 or not os.path.exists(destino) or os.path.getsize(destino) < 2000:
        _ffmpeg(["-i", origem, "-ar", "24000", "-ac", "1", destino], "ffmpeg não conseguiu preparar a fala")


def _chave_fala(fala: Dict[str, Any], voz: Dict[str, Any], texto_tts: str) -> str:
    base = json.dumps({"t": texto_tts, "m": voz.get("motor"), "c": voz.get("config"), "e": fala.get("emocao")}, sort_keys=True)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _gerar_fn_padrao(motor: str, texto: str, saida: str, **kw: Any) -> None:
    from tts.voice_generator import gerar_audio_isolado
    gerar_audio_isolado(motor, texto, saida, **kw)


def gerar_audio(base_dir: str, pid: str, gerar_fn: Optional[Callable[..., Any]] = None,
                on_log: Optional[Callable[[str], None]] = None, vozes: Optional[Dict[str, Dict[str, Any]]] = None,
                normalizar: bool = True) -> Dict[str, Any]:
    """Gera cada fala com a voz dela, corta o silêncio das pontas e junta com as
    pausas pedidas. Guarda os tempos exatos de cada fala e os .srt. Falas que
    não mudaram (mesmo texto + mesma voz) reaproveitam o áudio já gerado."""
    import multivoz
    log = on_log or (lambda _m: None)
    proj = carregar_projeto(base_dir, pid)
    roteiro = proj.get("roteiro") or {}
    falas = roteiro.get("falas") or []
    if not falas:
        raise ModeladoError("Cole o roteiro (JSON) antes de gerar o áudio.")
    vozes = {v["slug"]: v for v in vozes_efetivas()} if vozes is None else vozes
    faltando = sorted({f["voz"] for f in falas if f["voz"] not in vozes})
    if faltando:
        raise ModeladoError("Voz(es) não cadastrada(s): " + ", ".join(f"[{s}]" for s in faltando))
    pasta = pasta_projeto(base_dir, pid)
    dir_falas = pasta / "falas"
    dir_falas.mkdir(parents=True, exist_ok=True)
    # 1) o que cada fala precisa (voz, motor, texto, arquivo)
    plano, usados = [], set()
    for f in falas:
        voz = vozes[f["voz"]]
        motor, kw = multivoz.kwargs_da_voz(voz)
        if motor == "chatterbox":
            kw = dict(kw, exaggeration=round(0.25 + 0.6 * float(f.get("emocao", 0.5)), 2))
        texto = texto_para_tts(f, motor)
        if not texto:
            continue
        wav = dir_falas / f"f_{_chave_fala(f, voz, texto)}.wav"
        usados.add(wav.name)
        plano.append({"fala": f, "voz": voz, "motor": motor, "kw": kw, "texto": texto, "wav": wav})
    if not plano:
        raise ModeladoError("Nenhuma fala com texto pra narrar.")
    # 2) gera as que faltam AGRUPADAS POR PERSONAGEM (todas as falas de uma voz, depois a próxima):
    #    um processo por motor, o modelo e o perfil de voz carregam uma vez e ficam ativos.
    faltam = [x for x in plano if not (x["wav"].exists() and x["wav"].stat().st_size > 2000)]
    reaproveitadas = len(plano) - len(faltam)
    if reaproveitadas:
        log(f"♻ {reaproveitadas} fala(s) sem mudança: reaproveitadas.")
    ordem_voz: Dict[str, int] = {}
    for x in faltam:
        ordem_voz.setdefault(x["voz"]["slug"], len(ordem_voz))
    faltam.sort(key=lambda x: ordem_voz[x["voz"]["slug"]])  # sort estável: mantém a ordem das falas dentro da voz
    por_motor: Dict[str, List[Dict[str, Any]]] = {}
    for x in faltam:
        por_motor.setdefault(x["motor"], []).append(x)
    feitas = [0]

    def _pronta(x: Dict[str, Any]) -> None:
        bruto = x["wav"].with_name(x["wav"].stem + "_bruto.wav")
        _cortar_pontas(str(bruto), str(x["wav"]))
        bruto.unlink(missing_ok=True)

    for motor, grupo in por_motor.items():
        vozes_grupo = []
        for x in grupo:
            if x["voz"]["nome"] not in vozes_grupo:
                vozes_grupo.append(x["voz"]["nome"])
        log(f"🎙️ {motor}: {len(grupo)} fala(s) — " + " → ".join(
            f"{n} ({sum(1 for x in grupo if x['voz']['nome'] == n)})" for n in vozes_grupo) + " · modelo carregado uma vez")
        if gerar_fn is not None:  # (testes) gera uma por uma, na mesma ordem agrupada
            for x in grupo:
                feitas[0] += 1
                log(f"[{feitas[0]}/{len(faltam)}] {x['voz'].get('nome')}: \"{x['fala']['texto'][:60]}\"")
                try:
                    gerar_fn(motor, x["texto"], str(x["wav"].with_name(x["wav"].stem + "_bruto.wav")), **x["kw"])
                except Exception as exc:  # noqa: BLE001
                    raise ModeladoError(f"Falha na fala {x['fala']['id']} ({x['voz'].get('nome')}): {exc}") from exc
                _pronta(x)
            continue
        from tts.voice_generator import gerar_audio_isolado_lote

        def _progresso(i: int, erro: Optional[str], grupo=grupo) -> None:
            feitas[0] += 1
            x = grupo[i]
            log(f"[{feitas[0]}/{len(faltam)}] {'✖' if erro else '✔'} {x['voz'].get('nome')}: \"{x['fala']['texto'][:60]}\""
                + (f" — {erro}" if erro else ""))
        erros = gerar_audio_isolado_lote(
            [(motor, x["texto"], str(x["wav"].with_name(x["wav"].stem + "_bruto.wav")), x["kw"]) for x in grupo],
            on_progresso=_progresso)
        for i, x in enumerate(grupo):
            if i not in erros:
                _pronta(x)
        if erros:
            i = min(erros)
            raise ModeladoError(f"Falha na fala {grupo[i]['fala']['id']} ({grupo[i]['voz'].get('nome')}): {erros[i]}"
                                + (f" (+{len(erros) - 1} outra(s))" if len(erros) > 1 else "")
                                + " — as falas que deram certo ficaram salvas; gere de novo pra refazer só as que faltam.")
    # 3) mescla NA ORDEM DO ROTEIRO com as pausas pedidas -> tempos exatos
    arquivos, tempos, cursor = [], [], 0.0
    for x in plano:
        f, voz = x["fala"], x["voz"]
        dur = _duracao(str(x["wav"]))
        arquivos.append(str(x["wav"]))
        tempos.append({"id": f["id"], "tipo": f["tipo"], "personagem": f["personagem"], "voz": f["voz"],
                       "voz_nome": voz.get("nome"), "texto": f["texto"], "inicio": round(cursor, 3),
                       "fim": round(cursor + dur, 3), "cor": voz.get("cor")})
        cursor += dur + float(f.get("pausa_depois", 0.35))
    if not arquivos:
        raise ModeladoError("Nenhuma fala com texto pra narrar.")
    log(f"Juntando {len(arquivos)} falas...")
    pausas = [0.0] + [float(falas_por_id(falas)[t["id"]].get("pausa_depois", 0.35)) for t in tempos[:-1]]
    juntado = pasta / "audio_juntado.wav"
    multivoz.concatenar(arquivos, str(juntado), pausas, str(dir_falas))
    final_wav = pasta / "audio_final.wav"
    final_wav.unlink(missing_ok=True)
    if normalizar:
        log("Normalizando o volume...")
        norm = pasta / "audio_norm.wav"
        try:
            import narracoes
            narracoes.normalizar_volume_wav(juntado, norm)
            if norm.exists() and norm.stat().st_size > 1000:  # loudnorm sai em 192 kHz: volta pra 44.1 kHz
                _ffmpeg(["-i", str(norm), "-ar", "44100", "-ac", "1", str(final_wav)], "ffmpeg não conseguiu converter o áudio")
        except Exception:  # noqa: BLE001
            final_wav.unlink(missing_ok=True)
        norm.unlink(missing_ok=True)
    if not final_wav.exists() or final_wav.stat().st_size < 1000:
        _ffmpeg(["-i", str(juntado), "-ar", "44100", "-ac", "1", str(final_wav)], "ffmpeg não conseguiu salvar o áudio")
    juntado.unlink(missing_ok=True)
    _ffmpeg(["-i", str(final_wav), "-c:a", "libmp3lame", "-b:a", "192k", str(pasta / "audio_final.mp3")],
            "ffmpeg não conseguiu exportar o .mp3")
    duracao = _duracao(str(final_wav))
    # a duração real (depois de normalizar/juntar) manda: corrige o fim arredondado
    if tempos and tempos[-1]["fim"] > duracao:
        tempos[-1]["fim"] = round(duracao, 3)
    (pasta / "legenda.srt").write_text(montar_srt(tempos, com_personagem=False), encoding="utf-8")
    (pasta / "legenda_personagens.srt").write_text(montar_srt(tempos, com_personagem=True), encoding="utf-8")
    for velho in dir_falas.glob("f_*.wav"):  # falas que saíram do roteiro
        if velho.name not in usados:
            velho.unlink(missing_ok=True)
    proj = carregar_projeto(base_dir, pid)
    proj["audio_desatualizado"] = False
    proj["audio"] = {"arquivo": "audio_final.mp3", "wav": "audio_final.wav", "duracao": round(duracao, 3),
                     "falas": tempos, "gerado_em": time.time()}
    if proj.get("etapa") in ("roteiro", "audio"):
        proj["etapa"] = "ajuste"
    salvar_projeto(base_dir, proj)
    log(f"Pronto! Áudio de {duracao:.1f}s com {len(tempos)} falas.")
    return proj["audio"]


def _chave_papel(fala: Dict[str, Any]) -> str:
    """Quem fala: o nome do personagem (narração sem nome = Narrador)."""
    nome = (fala.get("personagem") or "").strip()
    if not nome and fala.get("tipo") == "narracao":
        nome = "Narrador"
    return nome or f"(voz {fala.get('voz')})"


def personagens_do_roteiro(roteiro: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Os papéis do roteiro, na ordem em que aparecem: nome, voz (a mais usada
    nas falas dele), gênero/idade que a IA deu e quantas falas tem."""
    falas = roteiro.get("falas") or []
    info = {(p.get("nome") or "").strip().lower(): p for p in roteiro.get("personagens") or []}
    papeis: Dict[str, Dict[str, Any]] = {}
    for f in falas:
        nome = _chave_papel(f)
        p = papeis.setdefault(nome.lower(), {"nome": nome, "falas": 0, "vozes": {}})
        p["falas"] += 1
        p["vozes"][f.get("voz")] = p["vozes"].get(f.get("voz"), 0) + 1
    out = []
    for chave, p in papeis.items():
        extra = info.get(chave) or {}
        vozes = sorted(p["vozes"].items(), key=lambda kv: -kv[1])
        out.append({"nome": p["nome"], "falas": p["falas"], "voz": vozes[0][0] if vozes else "",
                    "misturado": len(vozes) > 1, "genero": extra.get("genero") or "", "idade": extra.get("idade") or ""})
    return out


def definir_voz_do_personagem(base_dir: str, pid: str, nome: str, voz: str,
                              vozes_validas: Optional[set] = None) -> Dict[str, Any]:
    """Troca a voz de UM papel: todas as falas dele (e o cadastro do personagem) passam a usar `voz`."""
    proj = carregar_projeto(base_dir, pid)
    roteiro = proj.get("roteiro") or {}
    if vozes_validas is not None and voz not in vozes_validas:
        raise ModeladoError(f"Voz [{voz}] não existe.")
    alvo = (nome or "").strip().lower()
    n = 0
    for f in roteiro.get("falas") or []:
        if _chave_papel(f).lower() == alvo:
            if f.get("voz") != voz:
                f["voz"] = voz
                n += 1
    if not any(_chave_papel(f).lower() == alvo for f in roteiro.get("falas") or []):
        raise ModeladoError(f"Personagem {nome!r} não encontrado no roteiro.")
    achou = False
    for p in roteiro.get("personagens") or []:
        if (p.get("nome") or "").strip().lower() == alvo:
            p["voz"], achou = voz, True
    if not achou:
        roteiro.setdefault("personagens", []).append({"nome": nome, "voz": voz, "genero": "", "idade": "", "aparencia": ""})
    if n and proj.get("audio"):
        proj["audio_desatualizado"] = True
    salvar_projeto(base_dir, proj)
    return {"alteradas": n}


def falas_por_id(falas: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    return {f["id"]: f for f in falas}


# ===================================================================== legenda
def _tempo_srt(s: float) -> str:
    ms = round(max(0.0, s) * 1000)
    h, r = divmod(ms, 3_600_000)
    m, r = divmod(r, 60_000)
    sec, ms = divmod(r, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def dividir_texto(texto: str, inicio: float, fim: float, max_chars: int = 84) -> List[Dict[str, Any]]:
    """Quebra uma fala longa em blocos de legenda (no fim de frase/vírgula), com
    o tempo dividido pelo tamanho de cada pedaço."""
    texto = re.sub(r"\s+", " ", _RE_TAG_INLINE.sub("", texto or "")).strip()
    if not texto:
        return []
    if len(texto) <= max_chars:
        return [{"start": inicio, "end": fim, "text": texto}]
    pedacos, atual = [], ""
    for parte in re.split(r"(?<=[.!?…;,])\s+", texto):
        if atual and len(atual) + 1 + len(parte) > max_chars:
            pedacos.append(atual)
            atual = parte
        else:
            atual = (atual + " " + parte).strip()
        while len(atual) > max_chars:  # frase sem pontuação: corta na palavra
            corte = atual.rfind(" ", 0, max_chars)
            corte = corte if corte > 10 else max_chars
            pedacos.append(atual[:corte].strip())
            atual = atual[corte:].strip()
    if atual:
        pedacos.append(atual)
    total = sum(len(p) for p in pedacos) or 1
    out, t = [], inicio
    for p in pedacos:
        d = (fim - inicio) * len(p) / total
        out.append({"start": round(t, 3), "end": round(t + d, 3), "text": p})
        t += d
    out[-1]["end"] = fim
    return out


def blocos_legenda(tempos: List[Dict[str, Any]], com_personagem: bool = False) -> List[Dict[str, Any]]:
    blocos = []
    for f in tempos:
        for b in dividir_texto(f["texto"], float(f["inicio"]), float(f["fim"])):
            if com_personagem:
                quem = (f.get("personagem") or f.get("voz_nome") or "").strip()
                rotulo = {"narracao": "NARRADOR" if not quem or quem.lower() in ("narrador", "narrator") else quem.upper(),
                          "pensamento": f"{quem.upper()} (pensando)" if quem else "(pensando)"}.get(f.get("tipo"), quem.upper())
                b["text"] = f"{rotulo}: {b['text']}" if rotulo else b["text"]
            elif f.get("tipo") == "dialogo":
                b["text"] = "— " + b["text"]
            b.update({"fala_id": f["id"], "tipo": f.get("tipo"), "personagem": f.get("personagem")})
            blocos.append(b)
    return blocos


def montar_srt(tempos: List[Dict[str, Any]], com_personagem: bool = False) -> str:
    linhas = []
    for k, b in enumerate(blocos_legenda(tempos, com_personagem), start=1):
        linhas.append(f"{k}\n{_tempo_srt(b['start'])} --> {_tempo_srt(b['end'])}\n{b['text']}\n")
    return "\n".join(linhas)


# ===================================================================== cenas / tempos
def duracao_max_clipe(estilo: Dict[str, Any]) -> float:
    d = (estilo.get("flow") or {}).get("duracao_video") or "4s"
    if d == "auto":
        return 10.0
    try:
        return float(str(d).rstrip("s"))
    except ValueError:
        return 4.0


def duracao_clipe_para(estilo: Dict[str, Any], dur_cena: float) -> str:
    """Duração do vídeo pedida ao Flow pra uma cena (\"auto\" = a menor que cobre a cena)."""
    d = (estilo.get("flow") or {}).get("duracao_video") or "4s"
    if d != "auto":
        return d
    for op in DURACOES_VIDEO:
        if float(op.rstrip("s")) >= dur_cena - 0.05:
            return op
    return DURACOES_VIDEO[-1]


def normalizar_tempos(cenas: List[Dict[str, Any]], total: float, dmax: float,
                      tempos_falas: Optional[Dict[int, Dict[str, Any]]] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Ordena, tira buraco/sobreposição, começa em 0 e termina no fim do áudio.
    Cena sem tempo usa o início da 1ª fala dela; sem nada, divide o que sobra."""
    avisos: List[str] = []
    tempos_falas = tempos_falas or {}
    for c in cenas:
        if c.get("inicio", -1) < 0 and c.get("falas") and c["falas"][0] in tempos_falas:
            c["inicio"] = float(tempos_falas[c["falas"][0]]["inicio"])
    com = [c for c in cenas if c.get("inicio", -1) >= 0]
    sem = [c for c in cenas if c.get("inicio", -1) < 0]
    if sem and com:  # encaixa as sem tempo pela ordem original, entre as vizinhas
        ordem = {id(c): k for k, c in enumerate(cenas)}
        seq = sorted(cenas, key=lambda c: ordem[id(c)])
        for k, c in enumerate(seq):
            if c.get("inicio", -1) < 0:
                ant = next((x["inicio"] for x in reversed(seq[:k]) if x.get("inicio", -1) >= 0), 0.0)
                prox = next((x["inicio"] for x in seq[k + 1:] if x.get("inicio", -1) >= 0), total)
                c["inicio"] = (ant + prox) / 2
    elif sem:
        passo = total / len(cenas)
        for k, c in enumerate(cenas):
            c["inicio"] = k * passo
    cenas = sorted(cenas, key=lambda c: c["inicio"])
    cenas[0]["inicio"] = 0.0
    for k, c in enumerate(cenas):
        c["fim"] = cenas[k + 1]["inicio"] if k + 1 < len(cenas) else total
    # junta cena de menos de 0.6s na anterior (não dá tempo de ver)
    limpas: List[Dict[str, Any]] = []
    for c in cenas:
        if limpas and c["fim"] - c["inicio"] < 0.6:
            limpas[-1]["fim"] = c["fim"]
            avisos.append(f"Cena \"{c['cena'][:40]}…\" tinha menos de 0.6s e foi juntada à anterior.")
            continue
        limpas.append(c)
    if len(limpas) > 1 and limpas[0]["fim"] - limpas[0]["inicio"] < 0.6:
        limpas[1]["inicio"] = 0.0
        limpas.pop(0)
    for k, c in enumerate(limpas, start=1):
        c["id"] = k
        c["inicio"], c["fim"] = round(c["inicio"], 3), round(c["fim"], 3)
        c["duracao"] = round(c["fim"] - c["inicio"], 3)
        if c["duracao"] > dmax + 0.05:
            avisos.append(f"Cena {k} tem {c['duracao']:.1f}s (o vídeo gerado tem {dmax:g}s): o vídeo será desacelerado"
                          + (" e repetido" if c["duracao"] > dmax * 2 else "") + " pra cobrir.")
    return limpas, avisos


def distribuir_automatico(proj: Dict[str, Any], estilo: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Sem IA: cada cena começa no início da 1ª fala dela; cena longa é dividida
    (a 2ª metade repete a imagem com outro movimento)."""
    audio = proj.get("audio") or {}
    if not audio.get("falas"):
        raise ModeladoError("Gere o áudio antes.")
    total = float(audio["duracao"])
    tf = {f["id"]: f for f in audio["falas"]}
    dmax = duracao_max_clipe(estilo)
    base = [dict(c) for c in (proj.get("roteiro") or {}).get("cenas") or []]
    for c in base:
        c["inicio"] = -1
    cenas, avisos = normalizar_tempos(base, total, dmax, tf)
    out: List[Dict[str, Any]] = []
    for c in cenas:
        partes = max(1, int((c["duracao"] - 0.05) // dmax) + 1) if c["duracao"] > dmax + 0.05 else 1
        passo = c["duracao"] / partes
        for p in range(partes):
            n = dict(c, inicio=round(c["inicio"] + p * passo, 3), fim=round(c["inicio"] + (p + 1) * passo, 3))
            if p:
                n["movimento"] = "Slow push-in, subtle continuation of the previous motion"
                n["continuacao"] = True
            out.append(n)
    out, av2 = normalizar_tempos(out, total, dmax)
    return out, [a for a in avisos if "desacelerado" not in a] + av2


def aplicar_cenas(base_dir: str, pid: str, cenas: List[Dict[str, Any]], avisos: List[str]) -> Dict[str, Any]:
    """Grava as cenas finais, mantendo frame/vídeo de cenas que não mudaram."""
    proj = carregar_projeto(base_dir, pid)
    antigas = {(c.get("cena"), c.get("movimento")): c for c in proj.get("cenas") or []}
    antigas_img = {c.get("cena"): c for c in proj.get("cenas") or [] if c.get("imagem")}
    finais = []
    for c in cenas:
        n = {"id": c["id"], "inicio": c["inicio"], "fim": c["fim"], "duracao": c["duracao"], "falas": c.get("falas") or [],
             "cena": c["cena"], "movimento": c["movimento"], "continuacao": bool(c.get("continuacao")),
             "imagem": None, "video": None, "status": "", "erro": None}
        igual = antigas.get((c["cena"], c["movimento"]))
        mesma_img = antigas_img.get(c["cena"])
        if igual:
            n.update({k: igual.get(k) for k in ("imagem", "video", "status", "video_duracao_pedida")})
        elif mesma_img:
            n["imagem"] = mesma_img.get("imagem")
            n["status"] = "frame"
        finais.append(n)
    proj["cenas"] = finais
    proj["avisos"] = avisos
    proj["etapa"] = "frames"
    salvar_projeto(base_dir, proj)
    return proj


def aplicar_ajuste(base_dir: str, pid: str, texto_json: str) -> Dict[str, Any]:
    proj = carregar_projeto(base_dir, pid)
    estilo = obter_estilo(proj["estilo_id"])
    audio = proj.get("audio") or {}
    if not audio.get("falas"):
        raise ModeladoError("Gere o áudio antes.")
    dados = extrair_json(texto_json)
    lista = dados.get("cenas") if isinstance(dados, dict) else dados
    if not isinstance(lista, list):
        raise ModeladoError("O JSON do ajuste precisa ter a lista \"cenas\".")
    avisos: List[str] = []
    cenas = _normalizar_cenas(lista, {f["id"] for f in audio["falas"]}, avisos, com_tempo=True)
    cenas, av2 = normalizar_tempos(cenas, float(audio["duracao"]), duracao_max_clipe(estilo), {f["id"]: f for f in audio["falas"]})
    return aplicar_cenas(base_dir, pid, cenas, avisos + av2)


def aplicar_roteiro(base_dir: str, pid: str, texto_json: str, vozes: List[Dict[str, Any]],
                    tags: Optional[set] = None) -> Dict[str, Any]:
    proj = carregar_projeto(base_dir, pid)
    roteiro, avisos = validar_roteiro(extrair_json(texto_json), vozes, tags)
    proj["roteiro"] = roteiro
    proj["audio_desatualizado"] = bool(proj.get("audio"))
    proj["roteiro_bruto"] = texto_json[:200000]
    if roteiro.get("titulo") and (not proj.get("nome") or proj["nome"] == proj["tema"][:50]):
        proj["nome"] = roteiro["titulo"][:80]
    proj["avisos"] = avisos
    proj["etapa"] = "audio"
    salvar_projeto(base_dir, proj)
    return proj


# ===================================================================== prompts do Flow
def prompt_imagem_final(estilo: Dict[str, Any], cena: Dict[str, Any], formato: str) -> str:
    return (estilo.get("prompt_imagem") or "{cena}").replace("{cena}", cena["cena"].strip().rstrip(".,")) \
        .replace("{ar}", formato or "9:16")


def prompt_animacao_final(estilo: Dict[str, Any], cena: Dict[str, Any]) -> str:
    return (estilo.get("prompt_animacao") or "{movimento}").replace("{movimento}", cena["movimento"].strip().rstrip(".,"))


def cfg_flow(site_cfg: Dict[str, Any], estilo: Dict[str, Any], formato: str, visivel: bool = True,
             compacta: bool = True) -> Dict[str, Any]:
    """Config do Flow pra este projeto: proporção e modelo de imagem do estilo,
    proporção de vídeo do formato. (orientation decide o \"proporção 9x16\".)"""
    cfg = dict(site_cfg)
    fl = estilo.get("flow") or {}
    cfg["orientation"] = formato
    cfg["flow_proporcao_imagem"] = formato
    cfg["flow_proporcao_video"] = formato if formato in ("16:9", "9:16") else ""
    if fl.get("modelo_imagem"):
        cfg["flow_modelo_imagem"] = fl["modelo_imagem"]
    cfg["browser_visible"] = bool(visivel)  # Vídeos modelados: por padrão você VÊ o navegador trabalhando
    cfg["flow_janela_compacta"] = bool(compacta)  # layout estreito do Flow (o que funcionou)
    return cfg


# ---- Flow em lote: várias abas, fila que cresce, frame -> animação encadeados
COOLDOWN_PADRAO = (2.0, 9.0)
ABAS_PADRAO = 2


def trabalho_frame(proj: Dict[str, Any], estilo: Dict[str, Any], cena: Dict[str, Any], forcar: bool = False) -> Dict[str, Any]:
    return {"id": f"frame:{cena['id']}", "tipo": "imagem", "cena": cena["id"], "etapa": "frame",
            "rotulo": f"cena {cena['id']} · frame", "prompt": prompt_imagem_final(estilo, cena, proj["formato"]),
            "modelo": (estilo.get("flow") or {}).get("modelo_imagem") or "", "proporcao": proj["formato"], "forcar": forcar}


def trabalho_animacao(proj: Dict[str, Any], estilo: Dict[str, Any], cena: Dict[str, Any], forcar: bool = False) -> Dict[str, Any]:
    fl = estilo.get("flow") or {}
    return {"id": f"anim:{cena['id']}", "tipo": "animar", "cena": cena["id"], "etapa": "animacao",
            "rotulo": f"cena {cena['id']} · animação", "imagem": cena["imagem"], "prompt": prompt_animacao_final(estilo, cena),
            # frame gerado no Flow: escolhe a própria imagem do projeto em vez de enviar o arquivo
            "media_id": cena.get("flow_media_id") or "",
            "modelo": fl.get("modelo_video") or "Omni 1.1 Flash", "resolucao": fl.get("resolucao") or "720p",
            "duracao": duracao_clipe_para(estilo, float(cena.get("duracao") or 4)),
            "proporcao": proj["formato"] if proj["formato"] in ("16:9", "9:16") else "9:16", "forcar": forcar}


def enfileirar(base_dir: str, pid: str, cliente: Any, fila: Any, etapa: str, indices: Optional[List[int]] = None,
               forcar: bool = False, encadear: Optional[set] = None, on_log: Optional[Callable[[str], None]] = None) -> int:
    """Põe na fila do Flow os frames/animações pedidos. `etapa`: frames, animar ou
    tudo (no \"tudo\", a animação de uma cena entra na fila assim que o frame dela fica pronto)."""
    log = on_log or (lambda _m: None)
    proj = carregar_projeto(base_dir, pid)
    estilo = obter_estilo(proj["estilo_id"])
    na_fila = {t.get("id") for t in list(fila)}
    novos = 0
    for c in proj.get("cenas") or []:
        escolhida = indices is None or c["id"] in indices
        if not escolhida:
            continue
        trab = None
        if etapa in ("frames", "tudo") and (forcar or not c.get("imagem") or (etapa == "frames" and indices is not None)):
            trab = trabalho_frame(proj, estilo, c, forcar or indices is not None)
            if etapa == "tudo" and encadear is not None:
                encadear.add(c["id"])
        elif etapa in ("animar", "tudo") and c.get("imagem") and (forcar or not c.get("video") or indices is not None):
            trab = trabalho_animacao(proj, estilo, c, forcar or (indices is not None and etapa == "animar"))
        if trab is None or trab["id"] in na_fila:
            continue
        try:
            fila.append(cliente.preparar_trabalho(trab))
        except Exception as exc:  # noqa: BLE001
            _marcar(base_dir, pid, c["id"], status="erro", erro=str(exc))
            log(f"✖ cena {c['id']}: {exc}")
            continue
        _marcar(base_dir, pid, c["id"], status="fila_frame" if trab["tipo"] == "imagem" else "fila_animacao",
                erro=None, na_fila_desde=time.time(), aba=None)
        novos += 1
    return novos


def gerar_flow(base_dir: str, pid: str, cliente: Any, etapa: str, indices: Optional[List[int]] = None, forcar: bool = False,
               abas: int = ABAS_PADRAO, cooldown: Tuple[float, float] = COOLDOWN_PADRAO,
               on_log: Optional[Callable[[str], None]] = None, cancelar: Optional[Callable[[], bool]] = None,
               on_estado: Optional[Callable[[Dict[str, Any]], None]] = None, fila: Any = None,
               encadear: Optional[set] = None) -> Dict[str, Any]:
    """Gera frames e/ou animações no Flow com várias abas em paralelo. A `fila`
    (collections.deque) pode receber mais trabalhos enquanto roda (botões de cena)."""
    import collections
    log = on_log or (lambda _m: None)
    estado = on_estado or (lambda _d: None)
    fila = collections.deque() if fila is None else fila
    encadear = set() if encadear is None else encadear
    n = enfileirar(base_dir, pid, cliente, fila, etapa, indices, forcar, encadear, log)
    if not fila:
        log("Nada pra gerar (" + ("gere os frames primeiro" if etapa == "animar" else "tudo já está pronto") + ").")
        return carregar_projeto(base_dir, pid)
    log(f"▶ {n} pedido(s) na fila do Flow · {abas} aba(s) em paralelo · intervalo de {cooldown[0]:g}–{cooldown[1]:g}s entre envios")
    pasta = pasta_projeto(base_dir, pid)

    def evento(d: Dict[str, Any]) -> None:
        tipo, trab = d.get("tipo"), d.get("trab") or {}
        cid = trab.get("cena")
        if tipo == "aba":
            estado({"aba": d.get("aba"), "estado": d.get("estado")})
        elif tipo == "cooldown":
            estado({"cooldown_ate": time.time() + float(d.get("segundos") or 0)})
        elif tipo == "inicio":
            _marcar(base_dir, pid, cid, status="gerando_frame" if trab["tipo"] == "imagem" else "animando",
                    aba=d.get("aba"), gerando_desde=time.time(), erro=None)  # NÃO usar "inicio": é o tempo da cena no vídeo
            log(f"{'🖼' if trab['tipo'] == 'imagem' else '🎬'} aba {d.get('aba')}: enviando {trab.get('rotulo')}")
        elif tipo == "fim":
            origem = d.get("arquivo")
            if not origem or not os.path.isfile(origem):
                _marcar(base_dir, pid, cid, status="erro", erro="O Flow terminou mas o arquivo não foi baixado.")
                return
            if trab["tipo"] == "imagem":
                destino = pasta / "frames" / f"cena_{cid:03d}_{int(time.time() * 1000)}{os.path.splitext(origem)[1] or '.png'}"
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(origem, destino)
                _marcar(base_dir, pid, cid, imagem=str(destino), video=None, status="frame", erro=None,
                        prompt_imagem=trab["prompt"], aba=None, flow_media_id=d.get("media_id") or "")
                log(f"✔ cena {cid}: frame pronto" + (" (do cache)" if d.get("cache") else f" em {d.get('segundos')}s · aba {d.get('aba')}"))
                if cid in encadear:
                    encadear.discard(cid)
                    p2 = carregar_projeto(base_dir, pid)
                    c2 = next((c for c in p2["cenas"] if c["id"] == cid), None)
                    if c2 and c2.get("imagem"):
                        try:
                            fila.append(cliente.preparar_trabalho(trabalho_animacao(p2, obter_estilo(p2["estilo_id"]), c2)))
                            _marcar(base_dir, pid, cid, status="fila_animacao", na_fila_desde=time.time())
                        except Exception as exc:  # noqa: BLE001
                            _marcar(base_dir, pid, cid, status="erro", erro=f"Animação: {exc}")
            else:
                destino = pasta / "videos" / f"cena_{cid:03d}_{int(time.time() * 1000)}.mp4"
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(origem, destino)
                _marcar(base_dir, pid, cid, video=str(destino), status="video", erro=None, prompt_animacao=trab["prompt"],
                        video_duracao_pedida=trab.get("duracao"), aba=None)
                log(f"✔ cena {cid}: animação pronta" + (" (do cache)" if d.get("cache") else f" em {d.get('segundos')}s · aba {d.get('aba')}")
                    + (" · usou o frame que já estava no projeto" if d.get("reaproveitou_frame") else ""))
        elif tipo == "erro":
            encadear.discard(cid)
            _marcar(base_dir, pid, cid, status="erro", aba=None,
                    erro=("Frame: " if trab.get("tipo") == "imagem" else "Animação: ") + str(d.get("erro")))
            log(f"✖ cena {cid}: {d.get('erro')}")
        elif tipo == "limite":
            log("⛔ " + str(d.get("erro")))

    try:
        cliente.gerar_lote(fila, abas=abas, cooldown=cooldown, on_evento=evento, cancelar=cancelar)
    finally:
        # o que ficou na fila (parado/erro geral) volta ao estado de antes
        restantes = {t.get("cena") for t in list(fila)}
        fila.clear()
        proj = carregar_projeto(base_dir, pid)
        mudou = False
        for c in proj.get("cenas") or []:
            if c.get("status") in ("fila_frame", "fila_animacao", "gerando_frame", "animando") or c["id"] in restantes:
                c["status"] = "video" if c.get("video") else "frame" if c.get("imagem") else ""
                c["aba"] = None
                mudou = True
        cenas = proj.get("cenas") or []
        if cenas and all(c.get("video") for c in cenas):
            proj["etapa"], mudou = "pronto", True
        elif cenas and all(c.get("imagem") for c in cenas) and proj.get("etapa") == "frames":
            proj["etapa"], mudou = "animacao", True
        if mudou:
            salvar_projeto(base_dir, proj)
    return carregar_projeto(base_dir, pid)


def gerar_frames(base_dir: str, pid: str, cliente: Any, indices: Optional[List[int]] = None, forcar: bool = False,
                 on_log: Optional[Callable[[str], None]] = None, cancelar: Optional[Callable[[], bool]] = None, **kw: Any) -> Dict[str, Any]:
    return gerar_flow(base_dir, pid, cliente, "frames", indices, forcar, on_log=on_log, cancelar=cancelar, **kw)


def gerar_animacoes(base_dir: str, pid: str, cliente: Any, indices: Optional[List[int]] = None, forcar: bool = False,
                    on_log: Optional[Callable[[str], None]] = None, cancelar: Optional[Callable[[], bool]] = None, **kw: Any) -> Dict[str, Any]:
    return gerar_flow(base_dir, pid, cliente, "animar", indices, forcar, on_log=on_log, cancelar=cancelar, **kw)


def _marcar(base_dir: str, pid: str, cena_id: int, **campos: Any) -> None:
    with _TRAVA:
        proj = carregar_projeto(base_dir, pid)
        for c in proj.get("cenas") or []:
            if c["id"] == cena_id:
                c.update(campos)
        salvar_projeto(base_dir, proj)


def editar_cena(base_dir: str, pid: str, cena_id: int, cena: Optional[str] = None, movimento: Optional[str] = None) -> Dict[str, Any]:
    proj = carregar_projeto(base_dir, pid)
    for c in proj.get("cenas") or []:
        if c["id"] == cena_id:
            if cena is not None and cena.strip() and cena.strip() != c["cena"]:
                c["cena"] = cena.strip()[:1500]
                c["imagem"], c["video"], c["status"] = None, None, ""
            if movimento is not None and movimento.strip() and movimento.strip() != c["movimento"]:
                c["movimento"] = movimento.strip()[:600]
                c["video"] = None
                c["status"] = "frame" if c.get("imagem") else ""
            salvar_projeto(base_dir, proj)
            return c
    raise ModeladoError("Cena não encontrada.")


def usar_arquivo_na_cena(base_dir: str, pid: str, cena_id: int, origem: str, tipo: str) -> Dict[str, Any]:
    """Troca o frame (tipo=\"imagem\") ou o vídeo (tipo=\"video\") de uma cena por um arquivo seu."""
    pasta = pasta_projeto(base_dir, pid) / ("frames" if tipo == "imagem" else "videos")
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"cena_{cena_id:03d}_manual_{int(time.time())}{os.path.splitext(origem)[1].lower()}"
    shutil.copyfile(origem, destino)
    campos = ({"imagem": str(destino), "video": None, "status": "frame", "flow_media_id": ""} if tipo == "imagem"
              else {"video": str(destino), "status": "video"})
    _marcar(base_dir, pid, cena_id, erro=None, **campos)
    return carregar_projeto(base_dir, pid)


# ===================================================================== editor
def _ajustar_clipe(origem: str, destino: str, alvo_s: float) -> str:
    """Vídeo mais curto que a cena: desacelera (até 2x) pra cobrir — no estilo de
    animação quadro a quadro isso não aparece. Mais que 2x: o montador repete."""
    try:
        dur = _duracao(origem)
    except ModeladoError:
        return origem
    if dur <= 0 or dur >= alvo_s - 0.05:
        return origem
    fator = min(2.0, alvo_s / dur)
    _ffmpeg(["-i", origem, "-an", "-vf", f"setpts={fator:.4f}*PTS", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", "-pix_fmt", "yuv420p", destino], "ffmpeg não conseguiu ajustar o vídeo da cena")
    return destino


def pacote_para_editor(base_dir: str, pid: str, pasta_job: str) -> Dict[str, Any]:
    """Copia áudio e vídeos pra pasta do job e devolve o que o Estúdio precisa
    (segments da fala, pending_segments das cenas, legenda)."""
    import dp_legendas
    proj = carregar_projeto(base_dir, pid)
    estilo = obter_estilo(proj["estilo_id"])
    audio = proj.get("audio") or {}
    if not audio.get("falas"):
        raise ModeladoError("Gere o áudio antes.")
    if proj.get("audio_desatualizado"):
        raise ModeladoError("O roteiro mudou depois do áudio: gere o áudio de novo (etapa 2) — só as falas alteradas são refeitas.")
    cenas = proj.get("cenas") or []
    if not cenas:
        raise ModeladoError("Defina as cenas (ajuste de tempos) antes.")
    if not any(c.get("video") or c.get("imagem") for c in cenas):
        raise ModeladoError("Nenhuma cena tem vídeo nem imagem ainda.")
    pasta = pasta_projeto(base_dir, pid)
    os.makedirs(pasta_job, exist_ok=True)
    midia = os.path.join(pasta_job, "modelado_midia")
    os.makedirs(midia, exist_ok=True)
    audio_path = os.path.join(pasta_job, "narracao.wav")
    shutil.copyfile(pasta / (audio.get("wav") or "audio_final.wav"), audio_path)
    for nome in ("legenda.srt", "legenda_personagens.srt"):
        if (pasta / nome).exists():
            shutil.copyfile(pasta / nome, os.path.join(pasta_job, nome))
    blocos = blocos_legenda(audio["falas"], com_personagem=False)
    segments = [{"start": b["start"], "end": b["end"], "text": b["text"].lstrip("— ").strip()} for b in blocos]
    pendentes, faltando = [], []
    for c in cenas:
        seg = {"start": float(c["inicio"]), "end": float(c["fim"]), "provider": "flow", "query": c["cena"][:300],
               "on_screen_text": None, "on_screen_text_style": None, "media_type": "video", "override_source": None,
               "keyword_weight": None, "semantic_weight": None, "trim_start_frames": 0, "transition": "none",
               "modelado_cena": c["id"]}
        if c.get("video") and os.path.isfile(c["video"]):
            dst = os.path.join(midia, f"cena_{c['id']:03d}.mp4")
            shutil.copyfile(c["video"], dst)
            final = _ajustar_clipe(dst, os.path.join(midia, f"cena_{c['id']:03d}_ajustado.mp4"), float(c["duracao"]))
            seg["override_source"] = {"source": "local_file", "value": final, "kind": "video"}
        elif c.get("imagem") and os.path.isfile(c["imagem"]):
            dst = os.path.join(midia, f"cena_{c['id']:03d}{os.path.splitext(c['imagem'])[1]}")
            shutil.copyfile(c["imagem"], dst)
            seg.update({"media_type": "image", "zoom_direction": "in",
                        "override_source": {"source": "local_file", "value": dst, "kind": "image"}})
            faltando.append(c["id"])
        else:
            faltando.append(c["id"])
        pendentes.append(seg)
    legenda = dp_legendas.normalizar({"ativa": True, "estilo": estilo.get("legenda") or "classico", "posicao": "base",
                                      "maiusculas": False, "max_palavras": 4})
    import idiomas
    idioma = (idiomas.detectar_do_texto(" ".join(f["texto"] for f in audio["falas"]))
              or idiomas.normalizar(proj.get("idioma")) or "pt")
    return {"idioma": idioma, "audio_path": audio_path, "segments": segments, "total_duration": float(audio["duracao"]),
            "pending_segments": pendentes, "legendas": legenda, "orientation": proj["formato"],
            "nome": proj.get("nome") or proj.get("tema", "")[:60], "sem_video": faltando}
