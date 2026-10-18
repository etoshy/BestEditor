"""
🎭 Perfil do canal (v84_173) — personagens, lore, continuidade e histórico de um canal com personagens fixos.

Vem no pacote do canal (marcas/<slug>/), tudo opcional:
  personagens.json   narrador + personagens (personalidade, como fala, função, QUANDO aparece e quando NÃO, motivação,
                     ferida/segredo, emoções da voz, voz sugerida, desenho) + relação + regras de diálogo
  lore.md            a bíblia da lore (a IA consulta o PORQUÊ de cada dinâmica antes de escrever)
  continuidade.json  as pistas (clue_id, símbolo, pergunta de longo prazo, estado planned/used/paid_off, usos)
  docs/*.md          manuais do canal (formatos, prompt do roteirista, roteiro exemplo, análise)
Fica só no seu PC (não vem nem sai no pacote, e importar de novo não apaga):
  lore_historico.json  episódio a episódio: pistas usadas, o que cada personagem fez/revelou, novidades de lore, notas
                       suas e as versões anteriores da bíblia quando você edita.

No roteiro (🕵️ Modelos de vídeo com o modelo do canal), o prompt leva os personagens, a bíblia, a continuidade e o
histórico; a resposta traz "lore_registro", que entra no histórico. Na voz, as tags [mira|curiosa] viram a voz que você
escolheu pra cada personagem, com a emoção do Chatterbox daquela fala.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

_TRAVA = threading.Lock()
HIST_MAX = 400


def _slug(s: Any) -> str:
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:30]


def _dir(base: str, marca: str) -> str:
    if not re.fullmatch(r"[a-z0-9_]{2,40}", str(marca or "")):
        raise ValueError("marca inválida")
    return os.path.join(base, "marcas", marca)


def _json(cam: str, padrao: Any = None) -> Any:
    try:
        with open(cam, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def _gravar(cam: str, dados: Any) -> None:
    os.makedirs(os.path.dirname(cam), exist_ok=True)
    tmp = cam + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    os.replace(tmp, cam)


def _texto(cam: str) -> str:
    try:
        with open(cam, encoding="utf-8-sig") as f:
            return f.read()
    except OSError:
        return ""


# ------------------------------------------------------------------ carregar
def tem_perfil(base: str, marca: str) -> bool:
    try:
        return os.path.isfile(os.path.join(_dir(base, marca), "personagens.json"))
    except ValueError:
        return False


def _normalizar_personagem(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(p, dict):
        return None
    slug = _slug(p.get("slug") or p.get("nome"))
    if not slug:
        return None
    emo = {}
    for nome, v in (p.get("emocoes") or {}).items():
        if isinstance(v, dict):
            emo[_slug(nome)] = {k: v[k] for k in ("exag", "cfg", "vel", "descricao") if k in v}
    return {**p, "slug": slug, "nome": str(p.get("nome") or slug), "emocoes": emo}


def carregar(base: str, marca: str) -> Optional[Dict[str, Any]]:
    """O perfil do canal (None se o pacote não tem personagens.json)."""
    d = _dir(base, marca)
    pj = _json(os.path.join(d, "personagens.json"))
    if not isinstance(pj, dict):
        return None
    pers = [x for x in (_normalizar_personagem(p) for p in pj.get("personagens") or []) if x]
    narr = pj.get("narrador") if isinstance(pj.get("narrador"), dict) else {}
    narr = _normalizar_personagem({"slug": "narrador", "nome": "Narrador", **narr}) or {"slug": "narrador", "nome": "Narrador"}
    docs = {}
    pdocs = os.path.join(d, "docs")
    if os.path.isdir(pdocs):
        for n in sorted(os.listdir(pdocs)):
            if n.lower().endswith((".md", ".txt")):
                docs[n] = _texto(os.path.join(pdocs, n))
    guia = _json(os.path.join(d, "brand_guide.json"), {}) or {}
    return {"marca": marca, "nome": (guia.get("project") or {}).get("name") or marca, "narrador": narr, "personagens": pers,
            "relacao": pj.get("relacao") or {}, "regras_dialogo": [str(x) for x in pj.get("regras_dialogo") or []],
            "ferramentas_narrativas": [str(x) for x in pj.get("ferramentas_narrativas") or []],
            "lore": _texto(os.path.join(d, "lore.md")),
            "continuidade": _json(os.path.join(d, "continuidade.json"), {}) or {},
            "docs": docs, "historico": historico(base, marca)}


def falantes(perfil: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Narrador + personagens (a ordem das vozes na tela)."""
    if not perfil:
        return []
    return [perfil["narrador"]] + list(perfil["personagens"])


# ------------------------------------------------------------------ histórico da lore
def _arq_hist(base: str, marca: str) -> str:
    return os.path.join(_dir(base, marca), "lore_historico.json")


def historico(base: str, marca: str) -> List[Dict[str, Any]]:
    h = _json(_arq_hist(base, marca), [])
    return h if isinstance(h, list) else []


def _salvar_hist(base: str, marca: str, h: List[Dict[str, Any]]) -> None:
    _gravar(_arq_hist(base, marca), h[-HIST_MAX:])


def registrar_episodio(base: str, marca: str, dossie_id: str, titulo: str, registro: Any) -> Optional[Dict[str, Any]]:
    """O "lore_registro" que a IA devolveu com o roteiro vira (ou atualiza) a entrada daquele vídeo no histórico, e as
    pistas usadas mudam de estado na continuidade."""
    if not isinstance(registro, dict):
        return None
    pistas = []
    for x in registro.get("pistas") or []:
        if isinstance(x, dict) and x.get("clue_id"):
            pistas.append({"clue_id": str(x["clue_id"])[:40], "o_que_aparece": str(x.get("o_que_aparece") or "")[:300],
                           "estado": x.get("estado") if x.get("estado") in ("planned", "used", "paid_off") else "used"})
    ent = {"tipo": "episodio", "dossie": dossie_id, "titulo": str(titulo or "")[:160], "quando": time.time(),
           "pistas": pistas,
           "personagens": {(_slug(k) or k): str(v)[:600] for k, v in (registro.get("personagens") or {}).items()}
           if isinstance(registro.get("personagens"), dict) else {},
           "dinamica": str(registro.get("dinamica") or "")[:800],
           "novidades_lore": str(registro.get("novidades_lore") or "")[:1200],
           "por_que": str(registro.get("por_que") or "")[:1200],
           "callbacks": [str(x)[:200] for x in registro.get("callbacks") or []][:10],
           "proximos_videos": [str(x)[:200] for x in registro.get("proximos_videos") or []][:10]}  # 🎯 v84_178
    with _TRAVA:
        h = [e for e in historico(base, marca) if not (e.get("tipo") == "episodio" and e.get("dossie") == dossie_id)]
        h.append(ent)
        _salvar_hist(base, marca, h)
        if pistas:
            cam = os.path.join(_dir(base, marca), "continuidade.json")
            c = _json(cam, {}) or {}
            por_id = {str(p.get("clue_id")): p for p in c.get("pistas") or [] if isinstance(p, dict)}
            for pi in pistas:
                alvo = por_id.get(pi["clue_id"])
                if alvo is None:
                    continue
                ordem = {"planned": 0, "used": 1, "paid_off": 2}
                if ordem.get(pi["estado"], 1) >= ordem.get(alvo.get("estado") or "planned", 0):
                    alvo["estado"] = pi["estado"]
                usos = [u for u in alvo.get("usos") or [] if u.get("dossie") != dossie_id]
                usos.append({"dossie": dossie_id, "titulo": ent["titulo"], "o_que_aparece": pi["o_que_aparece"]})
                alvo["usos"] = usos[-20:]
            _gravar(cam, c)
    return ent


def adicionar_nota(base: str, marca: str, texto: str, tipo: str = "nota") -> Dict[str, Any]:
    texto = str(texto or "").strip()[:4000]
    if not texto:
        raise ValueError("Escreva a nota.")
    ent = {"tipo": tipo if tipo in ("nota", "decisao") else "nota", "texto": texto, "quando": time.time()}
    with _TRAVA:
        h = historico(base, marca)
        h.append(ent)
        _salvar_hist(base, marca, h)
    return ent


def salvar_lore(base: str, marca: str, novo: str, motivo: str = "") -> None:
    """Edita a bíblia guardando a versão anterior no histórico (dá pra ver por que mudou e voltar)."""
    cam = os.path.join(_dir(base, marca), "lore.md")
    antes = _texto(cam)
    if antes == novo:
        return
    with _TRAVA:
        with open(cam, "w", encoding="utf-8") as f:
            f.write(novo)
        h = historico(base, marca)
        h.append({"tipo": "mudanca", "arquivo": "lore.md", "motivo": str(motivo or "")[:600], "antes": antes[:60000],
                  "quando": time.time()})
        _salvar_hist(base, marca, h)


def apagar_entrada(base: str, marca: str, quando: float) -> bool:
    with _TRAVA:
        h = historico(base, marca)
        novo = [e for e in h if abs(float(e.get("quando") or 0) - float(quando)) > 1e-6]
        _salvar_hist(base, marca, novo)
        return len(novo) != len(h)


# ------------------------------------------------------------------ pro prompt do roteiro
def _linhas_personagem(p: Dict[str, Any], completo: bool = True) -> List[str]:
    L = [f"### [{p['slug']}] {p['nome']}" + (f" — {p['epiteto']}" if p.get("epiteto") else "") + (f": {p['papel']}" if p.get("papel") else "")]
    for rot, k in (("Personalidade", "personalidade"), ("Como fala", "fala"), ("Função no vídeo", "funcao_no_video"),
                   ("QUANDO APARECE", "quando_aparece"), ("QUANDO NÃO APARECE", "quando_nao_aparece"),
                   ("Motivação", "motivacao"), ("Ferida / segredo (pra coerência — NÃO revelar à toa)", "segredo"),
                   ("Contradição", "contradicao"), ("Hábitos", "habitos"), ("Arco", "arco")):
        v = p.get(k)
        if not v or (not completo and k in ("habitos", "arco", "contradicao")):
            continue
        L.append(f"- {rot}: " + ("; ".join(map(str, v)) if isinstance(v, list) else str(v)))
    return L


def bloco_roteiro(perfil: Dict[str, Any], ia_emocao: bool = True, curto: bool = False, n_hist: int = 10) -> str:
    """O bloco que entra no prompt do roteiro: falantes, emoção por fala, personagens, relação, ferramentas narrativas,
    bíblia, continuidade, histórico e o pedido do "lore_registro"."""
    fal = falantes(perfil)
    L = [f"## 🎭 VÍDEO COM PERSONAGENS — {perfil['nome']} (roteiro MULTI VOZ)",
         "O texto é falado por estas vozes. Antes de cada fala, a tag da voz entre colchetes (a tag não é lida; a voz continua "
         "até a próxima tag): " + ", ".join(f"[{f['slug']}] = {f['nome']}" for f in fal) + ".",
         f"Exemplo:\n[{fal[0]['slug']}] Frase do narrador.\n" + "".join(f"[{f['slug']}] Fala de {f['nome']}.\n" for f in fal[1:3]),
         "Não use colchetes pra mais nada além das tags de voz e das marcas de imagem [I3]; não escreva o nome antes da fala.",
         "Use as tags EXATAMENTE como estão (" + ", ".join(f"[{f['slug']}]" for f in fal) + ") e as emoções exatamente como nos "
         "presets — nada de traduzir ([narrator], [neutral]) nem abreviar. Toda tag tem a fala logo depois: tag sem texto não "
         "existe (se a personagem não tem o que dizer ali, ela não aparece)."]
    if ia_emocao:
        emo = []
        for f in fal:
            if f.get("emocoes"):
                emo.append(f"  [{f['slug']}|…]: " + ", ".join(f"{k}" + (f" ({v['descricao']})" if v.get("descricao") else "")
                                                         for k, v in f["emocoes"].items()))
        L += ["🎚 EMOÇÃO DA VOZ POR FALA (Chatterbox) — você controla: depois do nome, ponha a emoção daquela fala. "
              "Ou um preset do personagem, ex.: [mira|curiosa], ou números: [vanta|exag=0.35|cfg=0.5|vel=0.95] "
              "(exag 0.25–1.0 = intensidade emocional; cfg 0.2–0.7 = mais baixo = fala mais lenta e expressiva, mais alto = "
              "mais contido; vel 0.85–1.15 = velocidade). Sem nada depois do nome = a voz no padrão dela. Mude a emoção "
              "quando a fala pedir (susto, empolgação, ironia, tristeza), não em toda frase."]
        if emo:
            L.append("Presets:\n" + "\n".join(emo))
    else:
        L.append("Não ponha emoção nas tags: só [nome] (as vozes já têm a configuração delas).")
    L.append("")
    for f in fal:
        L += _linhas_personagem(f, not curto)
    rel = perfil.get("relacao") or {}
    if rel:
        L.append("### A relação")
        L += [f"- {k.replace('_', ' ')}: " + ("; ".join(map(str, v)) if isinstance(v, list) else str(v)) for k, v in rel.items() if v]
    if perfil.get("regras_dialogo"):
        L.append("### Regras de diálogo")
        L += [f"- {r}" for r in perfil["regras_dialogo"]]
    L.append("### Ferramentas narrativas (use como quiser — não é uma fórmula fixa)")
    L += [f"- {r}" for r in (perfil.get("ferramentas_narrativas") or [
        "Narração explicando, pergunta de uma personagem, contestação de outra, reação curta, um trecho SÓ de diálogo entre "
        "elas, uma pista de lore no fim — são ferramentas: entram quando servem à pergunta do título, na ordem que fizer sentido.",
        "Nem todo bloco precisa de fala de personagem; um trecho só de conversa também vale, se fizer o vídeo avançar.",
        "O foco é responder (ou explicar) a pergunta do título; diálogo que não acrescenta pergunta, contraste, clareza ou "
        "ritmo sai."])]
    L.append("- SEM indicações visuais no roteiro (nada de “VISUAL:”, câmera ou descrição de imagem): as imagens são feitas "
             "na edição. Se o roteiro exemplo tiver blocos VISUAL, ignore esses blocos.")
    lore = (perfil.get("lore") or "").strip()
    if lore:
        L += ["", "## 📖 BÍBLIA DA LORE — antes de escrever cada fala e cada dinâmica, confira aqui o PORQUÊ (motivação, ferida, "
                  "segredo, regras de revelação) e mantenha tudo coerente. A lore é FICÇÃO: nunca explica um fenômeno real.",
              lore[:(6000 if curto else 14000)]]
    pistas = [p for p in (perfil.get("continuidade") or {}).get("pistas") or [] if isinstance(p, dict)]
    if pistas:
        L += ["", "## 🧩 CONTINUIDADE — pistas (use pouco; cada uma responde parcialmente e abre uma pergunta mais específica)"]
        for p in pistas:
            usos = "; ".join(f"“{u.get('titulo')}”: {u.get('o_que_aparece')}" for u in (p.get("usos") or [])[-3:])
            L.append(f"- {p.get('clue_id')} · {p.get('simbolo')} · estado {p.get('estado') or 'planned'}"
                     + (f" · pergunta: {p.get('pergunta')}" if p.get("pergunta") else "") + (f" · já usado: {usos}" if usos else ""))
    hist = [e for e in perfil.get("historico") or [] if e.get("tipo") in ("episodio", "nota", "decisao")][-n_hist:]
    if hist:
        L += ["", "## 🕘 HISTÓRICO DO CANAL (o que já aconteceu — não contradiga; retome com callbacks quando fizer sentido)"]
        for e in hist:
            if e["tipo"] == "episodio":
                L.append(f"- Vídeo “{e.get('titulo')}”: " + "; ".join(x for x in [
                    e.get("dinamica"), e.get("novidades_lore"),
                    ", ".join(f"{k}: {v}" for k, v in (e.get("personagens") or {}).items()),
                    ("pistas " + ", ".join(f"{p['clue_id']}({p['estado']})" for p in e.get("pistas") or [])) if e.get("pistas") else ""] if x))
            else:
                L.append(f"- Nota do autor: {e.get('texto')}")
    prom = [(e.get("titulo"), t) for e in perfil.get("historico") or [] if e.get("tipo") == "episodio"
            for t in e.get("proximos_videos") or []][-12:]
    if prom and not curto:  # 🎯 v84_178: o que o canal já disse que vai mostrar noutro vídeo
        L += ["", "## 🎬 PROMETIDO PRA OUTROS VÍDEOS (o canal já disse ao público que vai mostrar — se o tema de agora É um deles, "
                  "pode lembrar “como prometido”; se não, não puxe o assunto)"]
        L += [f"- {t} (adiado em “{tit}”)" for tit, t in prom]
    return "\n".join(L)


# ------------------------------------------------------------------ 🎭 conferir as tags que a IA escreveu (v84_178)
_ALIAS_NARRADOR = {"narrator", "narrador", "narradora", "erzaehler", "erzähler", "erzahler", "sprecher", "narrateur", "narratore",
                   "voz", "voice", "off", "locutor", "narracao", "narração"}
_RX_TAG_FALA = re.compile(r"\[\s*([A-Za-zÀ-ÿ0-9_ -]{1,30})\s*(?:\|\s*([^\[\]\n]{0,80}?))?\s*\]")


def _sem_acento(t: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower().strip()


def normalizar_falas(texto: str, perfil: Optional[Dict[str, Any]]) -> Tuple[str, List[str]]:
    """Conserta as tags de voz: [narrator|contemplativ] → [narrador|contemplativo], [vanta|neutral] → [vanta|neutra],
    emoção que não existe sai (fica a voz no padrão), números (exag=…) ficam; e tira a tag SEM fala depois.
    Marcas que não são de voz ([I3], [[INSCREVA]]) ficam como estão. → (texto, consertos feitos)."""
    import difflib
    fal = falantes(perfil)
    if not fal or not texto:
        return texto, []
    slugs = {f["slug"]: f for f in fal}
    narr = fal[0]["slug"]
    consertos: List[str] = []

    def slug_de(nome: str) -> Optional[str]:
        n = _sem_acento(nome).replace(" ", "_")
        if n in slugs:
            return n
        if n in _ALIAS_NARRADOR:
            return narr
        for f in fal:  # pelo nome da personagem ("Mira" → mira)
            if _sem_acento(f.get("nome")) == n.replace("_", " "):
                return f["slug"]
        perto = difflib.get_close_matches(n, list(slugs), n=1, cutoff=0.75)
        return perto[0] if perto else None

    def emo_de(slug: str, emo: str) -> str:
        e = _sem_acento(emo)
        if not e or "=" in e:
            return emo.strip()  # números (exag=…) ficam como vieram
        opcoes = list((slugs[slug].get("emocoes") or {}).keys())
        mapa = {_sem_acento(o): o for o in opcoes}
        if e in mapa:
            return mapa[e]
        perto = difflib.get_close_matches(e, list(mapa), n=1, cutoff=0.6)
        if not perto and e in ("neutral", "normal", "neutro", "neutra"):
            perto = [x for x in mapa if x.startswith("neutr")][:1]
        return mapa[perto[0]] if perto else ""

    def trocar(m: "re.Match[str]") -> str:
        bruto, nome, emo = m.group(0), m.group(1), m.group(2)
        if re.fullmatch(r"[A-Za-z]{1,2}\d+", nome.strip()):  # [I3], [F2]: marca de mídia
            return bruto
        sl = slug_de(nome)
        if not sl:
            return bruto
        novo_emo = emo_de(sl, emo) if emo is not None else ""
        novo = f"[{sl}|{novo_emo}]" if novo_emo else f"[{sl}]"
        if novo != bruto:
            consertos.append(f"{bruto} → {novo}")
        return novo

    out = _RX_TAG_FALA.sub(lambda m: m.group(0) if m.start() > 0 and texto[m.start() - 1] == "[" else trocar(m), texto)
    # tag de voz sem fala: seguida de outra tag de voz, de linha em branco/marca [[…]] ou do fim
    rx_voz = r"\[(?:" + "|".join(re.escape(x) for x in slugs) + r")(?:\|[^\[\]\n]*)?\]"
    vazia = re.compile(rf"{rx_voz}[ \t]*(?=\s*(?:{rx_voz}|\[\[|\n\s*\n|\Z))")
    n_vazias = len(vazia.findall(out))
    if n_vazias:
        out = vazia.sub("", out)
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r"\n[ \t]+\n", "\n\n", out)
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
        consertos.append(f"{n_vazias} tag(s) sem fala tirada(s)")
    return out, consertos


EXEMPLO_REGISTRO = {
    "pistas": [{"clue_id": "id da pista usada (da lista de continuidade)", "o_que_aparece": "o que aparece e em que momento",
                "estado": "used | paid_off"}],
    "personagens": {"mira": "o que ela fez/sentiu/perguntou de importante neste vídeo",
                    "vanta": "o que ela fez/escondeu/revelou"},
    "dinamica": "como a relação apareceu neste vídeo (1-2 frases)",
    "novidades_lore": "o que este vídeo ACRESCENTOU à lore (vazio se nada)",
    "por_que": "por que as personagens agiram assim, segundo a bíblia (pra conferir a coerência depois)",
    "callbacks": ["coisas deste vídeo que dá pra retomar depois"],
}


def bloco_registro() -> str:
    return ("\"lore_registro\" (obrigatório neste canal): o que este vídeo usou/acrescentou da lore — vai pro histórico do "
            "canal e os próximos roteiros leem. " + json.dumps(EXEMPLO_REGISTRO, ensure_ascii=False))


# ------------------------------------------------------------------ voz: [mira|curiosa] → a voz escolhida
_RE_TAG = re.compile(r"\[\s*([^\[\]\n]{1,60}?)\s*\]")


def vozes_padrao(perfil: Optional[Dict[str, Any]], cfg_vozes: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{personagem: {"voz": slug da voz cadastrada, "exag", "cfg", "vel", "emocoes": {...}}} — o que você escolheu na
    página do Modelo de vídeo, por cima do que o pacote sugere."""
    out: Dict[str, Dict[str, Any]] = {}
    for f in falantes(perfil):
        sug = f.get("voz_sugerida") or {}
        c = (cfg_vozes or {}).get(f["slug"]) or {}
        item = {"voz": str(c.get("voz") or "").strip(), "emocoes": dict(f.get("emocoes") or {})}
        for k in ("exag", "cfg", "vel"):
            v = c.get(k, sug.get(k))
            if v not in (None, ""):
                try:
                    item[k] = float(v)
                except (TypeError, ValueError):
                    pass
        for nome, v in (c.get("emocoes") or {}).items():  # emoções que você ajustou na página
            if isinstance(v, dict):
                item["emocoes"][_slug(nome)] = {**item["emocoes"].get(_slug(nome), {}), **v}
        out[f["slug"]] = item
    return out


def converter_para_vozes(texto: str, perfil: Optional[Dict[str, Any]], cfg_vozes: Optional[Dict[str, Any]],
                         usar_emocao: bool = True) -> Tuple[str, List[str]]:
    """[mira|curiosa] / [mira|exag=0.7] / [mira] → [<voz da Mira>|exag=..|cfg=..|vel=..] (o padrão da personagem + o
    preset + os números da fala). → (texto, personagens sem voz escolhida)."""
    if not perfil:
        return texto, []
    texto, _ = normalizar_falas(texto, perfil)  # 🎭 v84_178: [narrator|neutral] de roteiros antigos também vira a voz certa
    vz = vozes_padrao(perfil, cfg_vozes)
    faltam: List[str] = []

    def troca(m):
        bruto = m.group(1)
        base, _, mods = bruto.partition("|")
        s = _slug(base)
        if s not in vz:
            return m.group(0)
        item = vz[s]
        if not item.get("voz"):
            if s not in faltam:
                faltam.append(s)
            return m.group(0)
        aj = {k: item[k] for k in ("exag", "cfg", "vel") if k in item}
        if usar_emocao:
            for parte in [x.strip() for x in mods.split("|") if x.strip()]:
                if "=" in parte:
                    import multivoz
                    aj.update(multivoz.ler_ajustes(parte))
                else:
                    pre = item["emocoes"].get(_slug(parte)) or {}
                    aj.update({k: float(pre[k]) for k in ("exag", "cfg", "vel") if k in pre})
        mod = "|".join(f"{k}={round(v, 2)}" for k, v in aj.items())
        return f"[{item['voz']}" + (f"|{mod}" if mod else "") + "]"
    return _RE_TAG.sub(troca, texto or ""), faltam
