"""
💬 VÍDEOS CURTOS DE COMENTÁRIO (v84_253) — o jeito dos tutoriais "How I edit commentary shorts":

  clipe → roteiro → voz → edição.

  1. CLIPE: o vídeo cru (M1, M2…) + o que acontece nele: a transcrição dele, uma descrição com os segundos, a transcrição
     de OUTRO vídeo que fala dele, ou um vídeo comentando (transcrito aqui). Sem texto? o Whisper transcreve o clipe, ou a
     IA OLHA o vídeo (2 quadros por segundo) e descreve o que acontece segundo a segundo.
  2. ROTEIRO em INGLÊS + tradução em português: mesmo tamanho/ritmo/fluxo da história, um parágrafo só, gancho forte e um
     final com PERGUNTA que puxa comentário (de preferência o ponto em que as pessoas discordam). Vêm 5 ganchos e 5 finais
     pra escolher, e “➕ mais 5”. As tags de emoção do Chatterbox Turbo ([gasp], [surprised]…) já vêm na fala.
  3. VOZ: Chatterbox Turbo (inglês) — 3 TAKES da mesma fala (cada um sai um pouco diferente), você escolhe o melhor.
  4. EDIÇÃO: tira os silêncios; cada frase mostra o pedaço do vídeo cru que ela conta; 1º plano < 3 s com zoom + whoosh;
     algo muda a cada 3-4 s (corte, zoom, legenda, rastreio, som); corta no fim da fala. 🎯 DESTAQUES: quando a fala aponta
     algo ("the cardboard sign"), a IA acha o objeto no quadro e o rastreio põe o círculo/seta seguindo ele.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any, Callable, Dict, List, Optional

import curtos as CT

TAGS_VOZ = ("gasp", "laugh", "chuckle", "sigh", "groan", "sniff", "surprised", "sarcastic", "dramatic", "whispering", "happy",
            "angry", "fear", "crying", "narration")


# ------------------------------------------------------------------ o que acontece no clipe (linhas com tempo)
_RE_LINHA = re.compile(r"^\s*[\[(]?\s*(\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)\s*s?\s*(?:[-–—>]+\s*(\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)\s*s?)?\s*[\])]?\s*[-–—:]?\s*(.+)$")


def _seg(v: str) -> Optional[float]:
    v = (v or "").strip()
    if not v:
        return None
    try:
        if ":" in v:
            m, s = v.split(":", 1)
            return int(m) * 60 + float(s)
        return float(v)
    except ValueError:
        return None


def ler_linhas(texto: str, mid: str = "M1", tipo: str = "texto") -> List[Dict[str, Any]]:
    """“0:12 ele pega a placa”, “[00:12] …”, “12s - …”, “0:12-0:15 …”, SRT/YouTube (tempo numa linha, texto na outra)
    → [{mid, t0, t1, texto, tipo}]. Linha sem tempo junta na anterior (ou vira uma linha solta sem tempo)."""
    out: List[Dict[str, Any]] = []
    pend_t: Optional[float] = None
    for bruta in str(texto or "").replace("\r", "").split("\n"):
        linha = bruta.strip()
        if not linha or re.fullmatch(r"\d+", linha):
            continue
        srt = re.match(r"^(\d{1,2}:)?(\d{1,2}):(\d{2})[,.](\d+)\s*-->\s*", linha)
        if srt:  # 00:00:12,500 --> 00:00:15,000
            h = int((srt.group(1) or "0:")[:-1] or 0)
            pend_t = h * 3600 + int(srt.group(2)) * 60 + int(srt.group(3)) + float("0." + srt.group(4))
            continue
        if re.fullmatch(r"\d{1,2}:\d{2}(?:\.\d+)?", linha):  # YouTube: o tempo sozinho na linha
            pend_t = _seg(linha)
            continue
        m = _RE_LINHA.match(linha)
        if m and _seg(m.group(1)) is not None and m.group(3).strip():
            out.append({"mid": mid, "t0": _seg(m.group(1)), "t1": _seg(m.group(2) or ""), "texto": m.group(3).strip()[:400], "tipo": tipo})
            pend_t = None
        elif pend_t is not None:
            out.append({"mid": mid, "t0": pend_t, "t1": None, "texto": linha[:400], "tipo": tipo})
            pend_t = None
        elif out:
            out[-1]["texto"] = (out[-1]["texto"] + " " + linha)[:600]
        else:
            out.append({"mid": mid, "t0": None, "t1": None, "texto": linha[:400], "tipo": tipo})
    for i, l in enumerate(out):  # fim de cada linha = começo da próxima
        if l["t1"] is None and l["t0"] is not None:
            prox = next((x["t0"] for x in out[i + 1:] if x["t0"] is not None and x["mid"] == l["mid"]), None)
            l["t1"] = prox
    return out


def dados(p: Dict[str, Any]) -> Dict[str, Any]:
    c = p.setdefault("comentario", {})
    c.setdefault("linhas", [])
    c.setdefault("referencia", "")
    c.setdefault("idioma", "en")  # "en" = narra no idioma da POSTAGEM (lingua_post); "pt" = narra em português
    c.setdefault("lingua_post", "en")
    c.setdefault("ganchos", [])
    c.setdefault("finais", [])
    return c


def lingua_post(p: Dict[str, Any]) -> str:
    lp = dados(p).get("lingua_post") or "en"
    return lp if lp in CT.LINGUAS else "en"


def nome_lingua(lp: str) -> str:
    return {"en": "ENGLISH", "pt": "BRAZILIAN PORTUGUESE", "es": "SPANISH", "it": "ITALIAN", "fr": "FRENCH", "de": "GERMAN"}.get(lp, "ENGLISH")


def explicativo(p: Dict[str, Any]) -> bool:
    return p.get("modelo") == "explicativo"


def salvar_texto_do_clipe(base: str, pid: str, texto: str, mid: str = "M1", tipo: str = "texto") -> int:
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        c = dados(p)
        c["linhas"] = [l for l in c["linhas"] if not (l.get("mid") == mid and l.get("tipo") == tipo)] + ler_linhas(texto, mid, tipo)
        c["linhas"].sort(key=lambda l: (l.get("mid") or "", l.get("t0") if l.get("t0") is not None else -1))
        CT.salvar(base, p)
        return len(c["linhas"])


def tem_tempos(texto: str) -> bool:
    """O texto tem segundos marcados (dá pra virar linha do tempo) ou é só a transcrição/descrição corrida?"""
    return any(l.get("t0") is not None for l in ler_linhas(texto))


def salvar_o_que_acontece(base: str, pid: str, texto: str, mid: str = "M1") -> Dict[str, Any]:
    """O que você colou: COM tempos → a linha do tempo do clipe; SEM tempos (a transcrição corrida que alguns shorts têm, com
    [music], letra de música, a descrição repetida…) → vira a REFERÊNCIA do roteiro (a IA separa a história do ruído) e a
    linha do tempo sai da IA olhando o vídeo (👁)."""
    texto = str(texto or "").strip()
    if not texto:
        return {"linhas": 0, "referencia": False}
    if tem_tempos(texto):
        return {"linhas": salvar_texto_do_clipe(base, pid, texto, mid, "texto"), "referencia": False}
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        c = dados(p)
        if texto not in (c.get("referencia") or ""):
            c["referencia"] = ((c.get("referencia") or "").strip() + "\n\n" + texto).strip()[:20000]
        CT.salvar(base, p)
    return {"linhas": 0, "referencia": True}


def sem_linha_do_tempo(p: Dict[str, Any], mid: str) -> bool:
    return not any(l.get("mid") == mid and l.get("t0") is not None for l in dados(p)["linhas"])


def _baixador_padrao(url: str, pasta_dest: str) -> str:
    """YouTube (Shorts) pelo cortador do YouTube; TikTok, Instagram, Kwai, X… pelo 📱 baixar de outras redes."""
    import sys
    raiz = os.path.dirname(os.path.abspath(__file__))
    if os.path.join(raiz, "toolkit") not in sys.path:
        sys.path.insert(0, os.path.join(raiz, "toolkit"))
    if re.search(r"(youtube\.com|youtu\.be)/", url):
        import youtube_clipper
        return (youtube_clipper.baixar_video(url, pasta_dest, qualidade="720p") or {}).get("caminho") or ""
    import pathlib
    import redes_sociais
    return redes_sociais.baixar_video(url, pathlib.Path(pasta_dest))


def baixar_link(url: str, destino_dir: str, baixador: Optional[Callable[[str, str], str]] = None) -> str:
    url = str(url or "").strip()
    if not re.match(r"https?://", url):
        raise CT.CurtoErro("Link inválido.")
    os.makedirs(destino_dir, exist_ok=True)
    cam = (baixador or _baixador_padrao)(url, destino_dir)
    if not cam or not os.path.isfile(cam):
        raise CT.CurtoErro("Não consegui baixar o vídeo desse link.")
    return cam


def baixar_clipe(base: str, pid: str, url: str, baixador: Optional[Callable[[str, str], str]] = None,
                 on_log: Callable[[str], None] = lambda _m: None) -> str:
    """⬇ O link do vídeo original (Shorts, TikTok, Reels…) vira o clipe M1, M2…"""
    import tempfile
    on_log("⬇ baixando o vídeo do link…")
    d = tempfile.mkdtemp(prefix="curto_link_")
    cam = baixar_link(url, d, baixador)
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        if any(m.get("origem") == url for m in p["midias"]):
            return next(m["id"] for m in p["midias"] if m.get("origem") == url)
        m = CT.adicionar_midia(base, p, cam, "video", "vídeo do link", "M", origem=url)
        CT.salvar(base, p)
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    return m["id"]


def clipes(base: str, p: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(m, caminho=CT.caminho_midia(base, p, m)) for m in p.get("midias") or []
            if m.get("tipo") == "video" and m["id"].startswith("M") and CT.caminho_midia(base, p, m)]


def transcrever_clipe(base: str, pid: str, mid: str, transcrever: Callable[..., Any],
                      on_log: Callable[[str], None] = lambda _m: None) -> int:
    """🎙 A fala do clipe (Whisper) vira as linhas com tempo."""
    p = CT.carregar(base, pid)
    m = next((x for x in clipes(base, p) if x["id"] == mid), None)
    if not m:
        raise CT.CurtoErro("Clipe não encontrado.")
    on_log(f"🎙 transcrevendo {mid}…")
    wav = os.path.join(CT.pasta(base, pid), "voz", f"_clipe_{mid}.wav")
    os.makedirs(os.path.dirname(wav), exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", m["caminho"], "-vn", "-ac", "1", "-ar", "16000", wav], capture_output=True, timeout=600)
    segs = transcrever(wav, language=None, word_timestamps=False, info={})
    texto = "\n".join(f"{float(s['start']):.1f} - {float(s['end']):.1f} {s['text'].strip()}" for s in segs if s.get("text", "").strip())
    return salvar_texto_do_clipe(base, pid, texto, mid, "fala")


DESCRICAO_SCHEMA = CT._o({"momentos": {"type": "array", "items": CT._o({"de": CT._n(), "ate": CT._n(), "o_que": CT._s()})},
                          "resumo": CT._s()})
DESCRICAO_SYS = ("Você descreve um vídeo curto (clipe viral) pra um roteirista de vídeos de comentário que NÃO vê o vídeo. Você recebe "
                 "folhas com o vídeo a 2 quadros por segundo, em ordem (esquerda→direita, linha a linha), com o relógio no canto. "
                 "Divida em momentos de 1 a 4 s e diga, concreto e curto, o que ACONTECE (quem, a ação, o objeto, a reação do público, "
                 "o texto que aparece na tela). Não invente nome de pessoa nem lugar que não esteja escrito no vídeo. Em português.")


DESCRICAO_FONTE_SYS = ("Você descreve um vídeo-FONTE pra um roteirista de shorts explicativos (curiosidades) que NÃO vê o vídeo e vai "
                       "escolher pedaços dele pra ilustrar cada frase. Você recebe folhas com o vídeo em ordem (esquerda→direita, linha a "
                       "linha), com o relógio no canto. Divida em momentos de 1 a 5 s (um por plano/ângulo) e diga, concreto e curto, o que "
                       "se VÊ (o objeto, o lugar, a ação, close ou plano aberto, se é animação/desenho/imagem de IA, texto/logo na tela). "
                       "No 'resumo', o assunto do vídeo em uma frase. Não invente nome de pessoa nem lugar. Em português.")


def descrever_clipe(base: str, pid: str, mid: str, chamar: Optional[Callable[..., Any]] = None,
                    on_log: Callable[[str], None] = lambda _m: None) -> int:
    """👁 A IA olha o clipe e escreve o que acontece em cada momento (pra vídeo sem fala, ou pra completar a transcrição)."""
    p = CT.carregar(base, pid)
    m = next((x for x in clipes(base, p) if x["id"] == mid), None)
    if not m:
        raise CT.CurtoErro("Clipe não encontrado.")
    on_log(f"👁 a IA está olhando o {mid}…")
    dur = CT.duracao_audio(m["caminho"])
    fonte = explicativo(p)  # 📚 muitas fontes: 1 quadro/s basta pra saber o que cada pedaço mostra
    folhas = CT.folhas_densas(m["caminho"], os.path.join(CT.pasta(base, pid), "quadros", mid), dur, fps=1.0 if fonte else 2.0,
                              max_folhas=3 if fonte else 6)
    import ia_servico
    blocos: List[Dict[str, Any]] = []
    for k, f in enumerate(folhas):
        b = ia_servico.imagem_bloco(f, largura=1080)
        if b:
            blocos += [{"type": "text", "text": f"FOLHA {k + 1}:"}, b]
    if not blocos:
        raise CT.CurtoErro("Não consegui tirar quadros do clipe.")
    blocos.append({"type": "text", "text": f"Duração do clipe: {dur:.1f} s. " + (f"O que já se sabe: {m.get('descricao')}" if m.get("descricao") else "")})
    r = (chamar or ia_servico.chamar)("curtos", DESCRICAO_FONTE_SYS if fonte else DESCRICAO_SYS, blocos, schema=DESCRICAO_SCHEMA,
                                      max_tokens=2500, job=pid)
    if not r:
        raise CT.CurtoErro(CT.motivo_ia())
    texto = "\n".join(f"{float(x['de']):.1f} - {float(x['ate']):.1f} {x['o_que']}" for x in r.get("momentos") or [])
    if r.get("resumo"):
        with CT._TRAVA:
            q = CT.carregar(base, pid)
            for mm in q["midias"]:
                if mm["id"] == mid and not mm.get("descricao"):
                    mm["descricao"] = r["resumo"][:400]
            CT.salvar(base, q)
    return salvar_texto_do_clipe(base, pid, texto, mid, "visual")


def transcrever_referencia(base: str, pid: str, caminho: str, transcrever: Callable[..., Any]) -> str:
    """📺 Um vídeo comentando o clipe (ou o short viral que você quer recriar): a transcrição vira a REFERÊNCIA do roteiro."""
    wav = caminho + ".16k.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", caminho, "-vn", "-ac", "1", "-ar", "16000", wav], capture_output=True, timeout=900)
    segs = transcrever(wav, language=None, word_timestamps=False, info={})
    texto = "\n".join(f"{float(s['start']):.1f} {s['text'].strip()}" for s in segs if s.get("text", "").strip())
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        dados(p)["referencia"] = texto[:20000]
        CT.salvar(base, p)
    try:
        os.remove(wav)
    except OSError:
        pass
    return texto


def duracao_da_referencia(texto: str) -> Optional[float]:
    """Os tempos da transcrição de referência → quanto ela dura (o roteiro novo tem o MESMO tamanho)."""
    ts = [_seg(m.group(1)) for m in re.finditer(r"(?m)^\s*[\[(]?(\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)\b", texto or "")]
    ts = [t for t in ts if t is not None]
    if len(ts) < 2:
        return None
    return round(max(ts) - min(ts) + 2.5, 1)


# ------------------------------------------------------------------ roteiro (inglês + português)
OPCAO = CT._o({"en": CT._s(), "pt": CT._s()})
ROTEIRO_SCHEMA = CT._o({
    "titulo_video": CT._s(), "descricao": CT._s(), "hashtags": CT._ls(),
    "roteiro_en": CT._s(), "roteiro_pt": CT._s(),
    "ganchos": {"type": "array", "items": OPCAO}, "finais": {"type": "array", "items": OPCAO}, "titulos": {"type": "array", "items": OPCAO},
    "blocos": {"type": "array", "items": CT._o({
        "funcao": {"type": "string", "enum": list(CT.FUNCOES_BLOCO)},
        "fala_en": CT._s(), "fala_pt": CT._s(),
        "cenas": {"type": "array", "items": CT._o({
            "layout": {"type": "string", "enum": ["clipe", "video", "foto", "ia", "ia_video"]}, "query": CT._s(),
            "material": CT._s(), "de": CT._n(), "ate": CT._n(), "palavra": CT._s(), "foco": CT._s(),
            "efeito": {"type": "string", "enum": list(CT.EFEITOS_CURTOS) + [""]},
            "entrada": {"type": "string", "enum": list(CT.ENTRADAS_CURTOS)},
            "destaque": CT._o({"alvo": CT._s(), "tipo": {"type": "string", "enum": ["", "circulo", "seta", "quadrado", "mira", "holofote"]},
                               "texto": CT._s()}),
            "sugestao": CT._o({"layout": {"type": "string", "enum": ["", "foto_real", "clipe_real", "ia", "ia_video"]}, "query": CT._s(),
                               "por_que": CT._s()})})},
        "sfx": {"type": "array", "items": CT._o({"tipo": {"type": "string", "enum": list(CT.TIPOS_SFX)}, "palavra": CT._s(), "busca": CT._s()})},
    })},
})


def roteiro_schema(p: Dict[str, Any]) -> Dict[str, Any]:
    """🎥 v84_322: com a câmera experimental, a cena ganha 'zoom_detalhe' e 'congelar' (sem ela: o schema de antes)."""
    import camera_exp
    if explicativo(p) or not camera_exp.ligada(p):
        return ROTEIRO_SCHEMA
    import copy
    sc = copy.deepcopy(ROTEIRO_SCHEMA)
    cena = sc["properties"]["blocos"]["items"]["properties"]["cenas"]["items"]
    cena["properties"].update(camera_exp.schema_cena_extra(CT))
    cena["required"] = list(cena["properties"])
    return sc

ROTEIRO_SYS = (
    "You write COMMENTARY SHORTS (YouTube Shorts / TikTok / Reels): a narrator retells and comments a viral clip while the clip plays. "
    "Follow this proven workflow:\n"
    "1. The LENGTH is whatever THIS story needs (a 6-second clip with one twist ≠ a 40-second clip with three moments) — when there "
    "is a reference transcript, stay close to its length, pacing and storytelling flow, but rewrite EVERYTHING in your own, more "
    "engaging words — never copy sentences. Take the idea, improve it, make it original and transformative.\n"
    "2. One single flowing paragraph when read aloud (no lists, no headings). Short spoken sentences.\n"
    "3. A STRONGER HOOK in the first sentence (curiosity, contradiction or a surprising claim — e.g. 'Everyone thought this young "
    "cyclist was being rude…'), landing fast on the first moment of the clip.\n"
    "4. Usually: what people thought / what happened → the twist nobody noticed → the payoff. Only facts the inputs support.\n"
    "5. END with ONE engaging QUESTION that makes people comment — ideally the point people would argue about.\n"
    "6. {REGRA_LINGUA}\n"
    "7. Split the paragraph into 'blocos' (one per sentence or two). In each block, 'cenas' = the moments of the clip that show "
    "EXACTLY what that line says ('material' = clip id like M1; 'de'/'ate' = seconds in that clip — use the timeline you were given; "
    "the narrator talks about a dog → show the dog immediately). CUTS follow the story, not a timer: a new cena when the narration "
    "moves to another moment of the clip (each one after the first starts at 'palavra', a word of that line); a long moment that "
    "speaks for itself stays on screen. 'efeito' = camera move chosen by what the moment needs: zoom_in to point at a detail or an "
    "emotion, zoom_out to reveal, zoom_rapido for a shock, '' when the image already works — not alternating by habit. 'entrada' = "
    "punch_in/flash only on an impact or a turn (usually the first cena and the twist), otherwise none.\n"
    "8. 'destaque' = when the line POINTS at something on screen (the sign he grabbed, the fan, the dessert), describe that object in "
    "ENGLISH in 'alvo' so it can be found and tracked in the frame, with 'tipo' circulo (object) or seta (person/where to look) and an "
    "optional 1-3 word 'texto'; otherwise alvo ''. Use 1 to 3 per video, on the key moments.\n"
    "9. 'sfx' = sound cues ONLY where something happens in that moment and fits ITS context (a fast move → whoosh, a hit/fall → "
    "impacto, the circle appearing → pop, a reveal → boom, a laugh → the matching type) with a 'busca' (Pixabay search in English) "
    "describing that exact sound; many moments have NO sound; never repeat the same pattern in every video.\n"
    "10. {REGRA_OPCOES}")

REGRA_OPCOES = ("'ganchos' = 5 alternative HOOKS and 'finais' = 5 alternative endings (each with 'en' = in {LINGUA}, the language of the "
                "post, and 'pt' = Brazilian Portuguese); the first of each is the one you used. 'titulos' = 5 post TITLES (short, "
                "curiosity, no clickbait lies) with 'en' in {LINGUA} and 'pt' in Brazilian Portuguese. 'roteiro_en' = the whole "
                "paragraph in {LINGUA}, 'roteiro_pt' in Portuguese. Also 'titulo_video' (= your best title, in {LINGUA}), 'descricao' "
                "(short, in {LINGUA}) and 3-6 'hashtags'.")

EXPLICATIVO_SYS = (
    "You write EXPLAINER / CURIOSITY SHORTS (YouTube Shorts / TikTok / Reels): a narrator explains one surprising thing (why an object "
    "has that shape, how an animal survives, the secret behind an invention) over a FAST collage of real videos. Rules:\n"
    "1. LENGTH: what the topic needs — usually 25-55 s; never pad.\n"
    "2. One flowing paragraph when read aloud, short spoken sentences, simple words, concrete facts and numbers (only facts from "
    "the topic notes / articles or well-established knowledge — never invent numbers or names).\n"
    "3. Structure (fixed): HOOK = a surprising question or claim about the object/animal on screen ('Why is the farmer's scythe "
    "the symbol of death?') → the common belief / what it looks like → the explanation step by step → the twist or the most "
    "surprising detail → a short ending (a curious last fact or a question for the comments).\n"
    "4. {REGRA_LINGUA}\n"
    "5. Split the paragraph into 'blocos' (one per sentence). In each block, 'cenas' = WHAT THE VIEWER SEES while that line is said, "
    "matching it LITERALLY (talks about waves destroying a house → the house being hit). {REGRA_FONTES} Each cena after the first "
    "starts at 'palavra' (a word of that line). 'efeito': slow zoom_in on most shots, zoom_out to reveal, zoom_rapido for a shock, '' when the motion is already strong; "
    "'entrada': flash only when the topic turns (1-3 per video), punch_in on the hook, otherwise none.\n"
    "6. 'destaque' = point at the key object the hook talks about (usually 1 in the first 2 s, 0-2 more later): 'alvo' = the object "
    "in English (it will be found and tracked in the frame), 'tipo' seta (arrow, the channel's signature) or circulo, 'texto' "
    "usually ''. Only on 'clipe' cenas.\n"
    "7. 'sfx' = only where something happens on screen and fits it (a fast move → whoosh, a crash → impacto, the arrow appearing "
    "→ pop, a reveal → boom); many lines have no sound; 'busca' = an English Pixabay search for that exact sound.\n"
    "8. {REGRA_OPCOES}")


REGRA_SO_FONTES = (
    "Build the WHOLE video ONLY from the creator's VIDEO SOURCES: every cena is layout 'clipe' + 'material' (M1, M2…) + 'de'/'ate' "
    "(seconds in that source, from its timeline) — even with few sources (e.g. 5 videos), use their different moments, angles and "
    "details (cutting twice in a row inside the same source is normal, coming back to a source is fine; this channel changes the "
    "picture about every 2-3 seconds). When a line REALLY needs something no source shows, still pick the closest source moment, "
    "and add a 'sugestao' the creator may accept: layout 'foto_real' (a real photo to find with an image search — 'query' = what to "
    "search), 'clipe_real' (a YouTube clip — 'query' = YouTube search) or 'ia' (an image to generate, e.g. a character or a scene "
    "that cannot be filmed — 'query' = an English image prompt), with a short 'por_que' in Portuguese. 0-4 suggestions per video; "
    "otherwise sugestao.layout ''.")
REGRA_FONTES_LIVRES = (
    "Use the creator's VIDEO SOURCES first: layout 'clipe' + 'material' (M1, M2…) + 'de'/'ate' (seconds in that source, from its "
    "timeline). This channel changes source about every 2-3 seconds (~16 different videos in a 40 s short) — cutting twice in a row "
    "inside the SAME source is normal, and coming back to a source is fine. When no source shows the line, use layout 'video' (stock "
    "video search, 'query' = 2-5 literal English words) or 'foto', or 'ia' for what cannot be filmed (an angel, the reaper, a "
    "historical scene) with 'query' = an English image prompt. sugestao.layout ''.")


REGRA_FLOW = (
    "There are NO source videos: EVERY cena is GENERATED with AI (Google Flow) and must look like REAL footage. Layout 'ia' = a "
    "generated PHOTO (the default — it gets a slow zoom) or 'ia_video' = a generated ~8 s VIDEO, only when MOTION is the point "
    "(waves crashing, an animal running, a machine working, something falling) — at most 1 in 3 cenas. 'query' = a detailed, "
    "concrete, REALISTIC shot description in English: the subject, what it is doing, where, the camera (extreme close-up / wide / "
    "aerial / handheld / macro), the light and time of day — like a frame from a documentary; never an illustration, cartoon, "
    "diagram or text on screen; no real famous people or brands. Keep the look CONSISTENT: describe the same object/animal/place "
    "the same way every time it appears. Change the picture about every 2-3 s (a line can have 1-2 cenas). No 'destaque' (it only "
    "works on real clips); sugestao.layout ''.")
REGRA_MISTO = (
    "Mix freely: the creator's VIDEO SOURCES when they show the line (layout 'clipe' + 'material' + 'de'/'ate'), stock video "
    "('video', 'query' = 2-5 literal English words) and AI generation that looks like real footage ('ia' photo / 'ia_video' ~8 s "
    "video when motion matters, 'query' = a detailed realistic shot description in English). Change the picture about every 2-3 s. "
    "sugestao.layout ''.")
MODOS_MIDIA = {"minhas": "🎞 só com os meus vídeos (o que faltar vira 💡 sugestão)",
               "flow": "✨ gerar tudo no Flow (realista: fotos e vídeos)",
               "misto": "🔀 misto (meus vídeos + banco + Flow)"}


def _tem_fontes(p: Dict[str, Any]) -> bool:
    return any(m.get("tipo") == "video" and m["id"].startswith("M") for m in p.get("midias") or [])


def modo_midia(p: Dict[str, Any]) -> str:
    """📚 De onde vem a imagem: dos seus vídeos, toda gerada no Flow, ou misto. Sem escolha: com vídeos → só eles; sem → Flow."""
    cfg = p.get("config") or {}
    if cfg.get("midia") in MODOS_MIDIA:
        return cfg["midia"]
    if not _tem_fontes(p):
        return "flow"
    return "minhas" if cfg.get("so_fontes", True) is not False else "misto"


def so_fontes(p: Dict[str, Any]) -> bool:
    """📚 Só com os vídeos que você mandou (o resto vira SUGESTÃO)?"""
    return modo_midia(p) == "minhas" and _tem_fontes(p)


def regra_lingua(p: Dict[str, Any]) -> str:
    lp = lingua_post(p)
    lingua = nome_lingua(lp)
    tags = (f" and add 1 to 4 voice tags at natural moments, from: {', '.join(f'[{t}]' for t in TAGS_VOZ)} (e.g. '[gasp] But what no one "
            "realized…') — it will be read by Chatterbox Turbo. Never other brackets." if lp == "en" else " (no brackets/tags).")
    return (f"Write 'fala_en' in {lingua} — the language of the POST{tags} 'fala_pt' = the same line in natural Brazilian Portuguese "
            "(no tags)" + (" (the same as fala_en)." if lp == "pt" else "."))


def _regra_video_flow(p: Dict[str, Any]) -> str:
    v = (p.get("config") or {}).get("flow_video")
    if v is True:
        return (" VIDEO MODE: prefer 'ia_video' for MOST cenas (2 of every 3 or more) — when the Flow video credits run out they "
                "automatically become generated photos, so describe each shot so it also works as a still.")
    if v is False:
        return " PHOTO MODE: use ONLY layout 'ia' (generated photos) — no 'ia_video'."
    return ""


def _regra_fontes(p: Dict[str, Any]) -> str:
    m = modo_midia(p)
    if m == "flow":
        return REGRA_FLOW + _regra_video_flow(p)
    if m == "misto":
        return REGRA_MISTO if _tem_fontes(p) else REGRA_FLOW
    return REGRA_SO_FONTES if _tem_fontes(p) else REGRA_FONTES_LIVRES


# ------------------------------------------------------------------ ✨ v84_321: roteiro AUTÊNTICO (o padrão)
# Fatos + opinião em vez de narrar o que já está na tela; gancho e final de um TIPO sorteado por vídeo (o lote não sai tudo igual).
# O estilo antigo continua como opção ("classico"), desligada: só vale se você marcar.
ESTILOS_ROTEIRO = {"personalidade": "🎭 personalidade (experimental: persona do canal, opinião forte, sem repetir os vídeos anteriores)",
                   "autentico": "✨ autêntico (fatos + opinião, gancho e final variados)",
                   "classico": "📜 clássico (narra o que acontece — o jeito antigo)"}

TIPOS_GANCHO = {  # 🧩 v84_348: os moldes são SEM assunto (antes um exemplo de preguiça vazava pra vídeos de uva…)
    "fato": "a SURPRISING FACT about THIS clip's subject that makes the clip special or rare (shape: '<surprising fact about the "
            "subject>. So what you're about to see is <why it is rare>.')",
    "contradicao": "a CONTRADICTION — what people get wrong about what they see (shape: 'This looks like <what it seems>. It's "
                   "actually <what it really is>.')",
    "opiniao": "a BOLD but honest OPINION the narrator will defend (shape: '<strong claim about the subject>, and this clip proves it.')",
    "pergunta": "a SPECIFIC question the viewer can't answer yet and the video answers (shape: 'Why would <subject> <surprising "
                "action>?') — never a vague 'Did you know…?'",
    "detalhe": "point at the DETAIL most people miss, specifically (shape: 'Ignore <the obvious part>. Look at <the detail>.')",
    "aposta": "a STAKES / tension setup — something could go wrong, or there is a reason this is harder than it looks (honest, no fake danger)",
}
TIPOS_FINAL = {
    "debate": "a SPECIFIC either/or question about THIS clip that splits people in the comments (not a generic 'Would you ever…?')",
    "fato_final": "keep the most surprising fact for the LAST line — the payoff that makes people rewatch or share",
    "loop": "a last line that flows straight back into the first sentence, so the short loops seamlessly when it restarts",
    "opiniao": "a strong, honest take + an invite to disagree ('Agree, or am I wrong?')",
    "comentario": "ask for something concrete in the comments tied to the clip (guess, name it, tag the friend who…)",
}

REGRA_AUTENTICA = (
    "\n\n✨ AUTHENTIC MODE — these rules OVERRIDE points 3, 4 and 5 above (the platforms demonetize narration that only describes the "
    "clip, and templated, mass-produced scripts):\n"
    "A. NO PLAY-BY-PLAY. Never just say what the viewer can already see ('it is moving… now it stretches… now it bends its neck'). "
    "EVERY sentence must add something the image does NOT show: a fact, the context, the WHY/HOW, a comparison, the narrator's "
    "opinion or a joke. You may name the moment in a few words to sync with the clip, but always add value in the same sentence.\n"
    "B. At least 2 CONCRETE, well-established facts or pieces of context about the subject (the species and its behavior, the "
    "technique, the place, the rule, the record…). Only what you are sure of or what the inputs support; if unsure say 'probably'; "
    "never invent numbers, names or places.\n"
    "C. At least 1 genuine first-person line from the narrator (an opinion, a reaction, a small self-deprecating joke) — a real "
    "person talking, not a documentary voice.\n"
    "D. HOOK (first sentence, under ~14 words, lands in the first 2 seconds): use the HOOK TYPE given in the content. It must be "
    "SPECIFIC to this clip — click-worthy through curiosity, never through lies or fake claims.\n"
    "E. ENDING: use the ENDING TYPE given in the content.\n"
    "F. BANNED template phrases (they mark the video as mass-produced): 'Everyone thought', 'But look closer', 'You won't believe', "
    "'Wait for it', 'Watch till the end', 'This is why…', 'so hard to forget', 'completely at peace', 'all the time in the world', "
    "'Would you ever…?', 'What would you do?', 'Nobody expected', 'little did they know'. No empty dramatic adjectives.\n"
    "G. 'ganchos': 5 hooks of 5 DIFFERENT hook types; 'finais': 5 endings of 5 DIFFERENT ending types (the first of each = the one "
    "you used). 'titulos': curiosity + a concrete detail of the clip, honest.\n"
    "I. The facts and context are told OVER THE CLIP: every cena stays on the clip (layout 'clipe' with material/de/ate) — "
    "never a stock/bank video for a fact. If other footage would really help, put it in that cena's 'sugestao' (it stays only a "
    "suggestion).\n"
    "H. 'descricao': 1-2 sentences with the most interesting fact + credit the original creator by @ when you know it (keep any [COMMENTARY]/[EXPLAIN]/[ART] tag the APPROACH asks for at the very start).")


REGRA_PERSONALIDADE = (
    "\n\n🎭 PERSONALITY MODE (on top of the authentic rules — this is what makes the channel NOT look mass-produced):\n"
    "P1. ONE NARRATOR, ONE VOICE: follow the CHANNEL PERSONA given in the content (tastes, humor, what they care about, how they "
    "talk). Same person in every video of the channel — talking to ONE viewer, like a friend sending a clip with their take.\n"
    "P2. A REAL TAKE: give a clear opinion or verdict about this clip (what impressed you, what you doubt, what you would or would "
    "never do) and back it with a fact or a reason. You may respectfully disagree with the comments or with the creator.\n"
    "P3. A PERSONAL ANGLE, HONEST: relate it to an everyday feeling or a comparison anyone has lived ('same energy as…', 'it's like "
    "when…'), as opinion or hypothetical. NEVER invent biography or experiences (no 'when I worked at a winery', no fake memories).\n"
    "P4. ONE INSIGHT THE CLIP DOESN'T GIVE: a non-obvious detail, why it works, a common misconception corrected, or what the "
    "comments got right/wrong.\n"
    "P5. IT MUST SOUND SPOKEN: contractions, short sentences mixed with one longer, one aside in the middle; at most one "
    "exclamation; no announcer voice.\n"
    "P6. NO TEMPLATE: do NOT reuse openings, punchlines, catchphrases, sentence structures or the ending style of this channel's "
    "RECENT SCRIPTS (listed in the content). The persona is constant, the wording is new every time.\n"
    "P7. The ending invites a genuine opinion about ONE specific point of this video (never a generic 'what do you think?').\n"
    "P8. Same length.\n"
    "P9. FACT DISCIPLINE (stricter than the authentic mode): never give a reason or a purpose that only SOUNDS plausible "
    "(e.g. 'the aprons keep them from slipping', 'they do it at night because it is cooler') — every why/how/what-for must be a "
    "well-established fact. If you are not sure, CUT the claim instead of hedging with 'probably'. Fewer facts, all solid.\n"
    "P10. DEPTH OF THE TAKE: the opinion needs a REASON and a CONTRAST — why the narrator thinks so, against what most people "
    "assume or against the modern/industrial/usual way (e.g. 'machines do this faster, but…'). One elaborated take beats two "
    "shallow ones.\n"
    "P11. MAKE IT RELEVANT: when well-established, add one 'still today / where / who' fact (where it is still done, who does it, "
    "how common or rare it is now) — it turns a curiosity into information.\n"
    "P12. TIE EACH FACT TO THE IMAGE: every fact or explanation line points at something VISIBLE at that moment (the skins "
    "breaking, the press, the juice in the channel…), so the edit can cut/zoom/highlight right then — and set that cena's "
    "material/de/ate and zoom/destaque fields to that moment.")


REGRA_COMPOSTO = (
    "\n\n🧩 COMPOSITE VIDEO — you have {N} clips (M1…M{N}) from DIFFERENT creators about the same theme. Build ONE NEW, "
    "informative video out of them (this is the original value: nobody else made this video):\n"
    "C1. NOT A LIST OR RANKING: no 'number one/two', no 'first video… next video', no 'here are 3…', no 'top'. The viewer must "
    "feel one story, not a compilation.\n"
    "C2. Choose the FORMAT that fits THIS material best and follow it all the way: (a) GUIDING QUESTION — one specific question "
    "opens the video, the clips are the evidence and the answer builds until the end; (b) MINI-DOCUMENTARY — each clip shows a "
    "different ANGLE of the same subject (what it is, the secret behind it, what nobody tells you); (c) STORY ARC — "
    "beginning/middle/end, the clips ordered by the story (not by the order of the links); (d) THESIS — 'everyone thinks X, "
    "but…': the clips support an argument the narrator defends.\n"
    "C3. INTERCUT: the cenas jump between the clips (material M1/M2/M3…) wherever the narration needs it, using the BEST seconds "
    "of each (de/ate) — never one clip played whole and then the next. Every clip appears at least once; the strongest image "
    "opens the video.\n"
    "C4. ONE THREAD: transitions are about the IDEA ('and this is where it gets strange', 'the reason is right here'), never about "
    "the source ('in this other video').\n"
    "C5. Places, people and names only when the inputs (captions/comments) make them clear — never invent where a clip was shot.\n"
    "C6. LENGTH: 60 seconds or more (at least ≈160 words of narration), as long as the material honestly supports — usually "
    "70-100 s, never above 170 s, never padded.\n"
    "C7. 'descricao' credits ALL the creators (by @ when known). If the clips really do not share a theme, still build the best "
    "honest thread you can and start 'descricao' with '⚠ as fontes não têm um tema claro em comum'.")


PUBLICO_DA_LINGUA = {"en": "an English-speaking audience (mostly US/UK)", "pt": "a Brazilian audience", "es": "a Spanish-speaking audience",
                     "it": "an Italian audience", "fr": "a French-speaking audience", "de": "a German-speaking audience"}


def regra_localizar(p: Dict[str, Any]) -> str:
    """🌍 v84_352: o roteiro pensa em QUEM vai assistir (o público da língua do post): explica o que é típico de outro lugar,
    onde é comum, e converte medidas — sem explicar o óbvio pro público local."""
    publico = PUBLICO_DA_LINGUA.get(lingua_post(p), PUBLICO_DA_LINGUA["en"])
    return (
        f"\n\n🌍 LOCALIZE FOR THE AUDIENCE — this video is for {publico}:\n"
        "L1. Anything culture-specific they may not know (a dish, a festival, a slang word, a local sport, a brand, a tradition, a "
        "place): keep the ORIGINAL name and explain it in a few words with a comparison they already know (e.g. 'pamonha — "
        "basically a sweet corn tamale wrapped in the husk'). Once, the first time it appears; never a lecture.\n"
        "L2. WHERE and WHEN it is common, when it is well-established (e.g. 'a staple at Brazil's June festivals'). Never invent "
        "a region, a date or a custom — if unsure, leave it out.\n"
        "L3. Numbers in the audience's system when it helps understanding (°F/°C, lb/kg, miles/km, feet/meters) — e.g. "
        "'500 grams, about a pound'. Money: keep the original currency with the country ('20 reais in Brazil'); add an "
        "approximate conversion ONLY if you are sure of the order of magnitude ('about four dollars').\n"
        "L4. Do NOT explain what the audience already knows (for a Brazilian audience, never explain what pamonha is; for an "
        "American audience, never explain a hot dog).\n"
        "L5. The explanation counts as one of your facts — keep the same total length.")


def composto(p: Dict[str, Any]) -> int:
    """🧩 v84_349: quantas fontes o vídeo composto tem (0 = vídeo de um link só)."""
    try:
        n = int((p.get("config") or {}).get("composto") or 0)
    except (TypeError, ValueError):
        n = 0
    return n if n >= 2 else 0


def autentico_ou_mais(p: Dict[str, Any]) -> bool:
    return estilo_roteiro(p) in ("autentico", "personalidade")


def persona_do_canal(c: Optional[Dict[str, Any]]) -> str:
    """🎭 a personalidade do narrador do canal (o que você escreveu; sem ela, uma deduzida da descrição do canal)."""
    c = c or {}
    t = str(c.get("persona") or "").strip()
    if t:
        return t[:1500]
    d = str(c.get("descricao") or "").strip()
    nome = str(c.get("nome") or "the channel").strip()
    return (f"(not written by the creator — build ONE consistent narrator for '{nome}' from the channel description"
            + (f": {d[:600]}" if d else "") + ". Curious, a bit opinionated, warm, dry humor; and keep it consistent.)")


def roteiros_recentes(base: str, p: Dict[str, Any], n: int = 6) -> List[str]:
    """Os começos e os fins dos últimos roteiros DO MESMO CANAL (pra não repetir fórmula)."""
    cid = p.get("canal_id") or ""
    if not cid:
        return []
    d = os.path.join(CT.raiz(base), "projetos")
    cands = []
    for pid in os.listdir(d) if os.path.isdir(d) else []:
        if pid == p.get("id"):
            continue
        cam = os.path.join(d, pid, "projeto.json")
        try:
            cands.append((os.stat(cam).st_mtime, pid))
        except OSError:
            continue
    out = []
    for _mt, pid in sorted(cands, reverse=True)[:80]:
        try:
            q = CT.carregar(base, pid)
        except Exception:  # noqa: BLE001  (projeto.json vazio/corrompido ou sendo gravado: pula — nunca derruba o roteiro)
            continue
        bl = (q.get("roteiro") or {}).get("blocos") or []
        if q.get("canal_id") != cid or not bl:
            continue
        ini = CT.sem_tags(bl[0].get("fala_en") or bl[0].get("fala") or "")[:160]
        fim = CT.sem_tags(bl[-1].get("fala_en") or bl[-1].get("fala") or "")[-160:] if len(bl) > 1 else ""
        out.append(f"- starts: \"{ini}\"" + (f" | ends: \"{fim}\"" if fim else ""))
        if len(out) >= n:
            break
    return out


def estilo_roteiro(p: Dict[str, Any]) -> str:
    """✨ v84_321: 'autentico' é o padrão (inclusive em projetos antigos); 'classico' só se você escolher."""
    v = (p.get("config") or {}).get("estilo_roteiro") or "autentico"
    return v if v in ESTILOS_ROTEIRO else "autentico"


def tipos_do_video(p: Dict[str, Any]) -> tuple:
    """🎲 o tipo de gancho e de final deste vídeo — sorteado pelo id (fixo pro mesmo vídeo, variado no lote)."""
    import hashlib
    h = int(hashlib.md5(str(p.get("id") or "").encode("utf-8")).hexdigest(), 16)
    g = list(TIPOS_GANCHO)[h % len(TIPOS_GANCHO)]
    if final_loop(p):  # 🔁 v84_354: final em loop só se você ligar (aí é sempre loop)
        return g, "loop"
    finais = [k for k in TIPOS_FINAL if k != "loop"]
    f = finais[(h // 7) % len(finais)]
    return g, f


def final_loop(p: Dict[str, Any]) -> bool:
    return bool((p.get("config") or {}).get("final_loop"))


def retencao(p: Dict[str, Any]) -> bool:
    """🧲 v84_354: modo retenção (gatilhos mentais honestos) — ligado por padrão; config.retencao = False desliga."""
    return (p.get("config") or {}).get("retencao", True) is not False


REGRA_RETENCAO = (
    "\n\n🧲 MAXIMUM RETENTION (attention psychology — every trigger must be HONEST: a fake promise makes people leave and the "
    "platform punishes it):\n"
    "R1. FIRST WORD = HOOK. No intro, no 'so', 'hey guys', 'in this video', 'let me tell you'. The first cena opens on the "
    "most striking seconds of the clip (choose its de/ate for that), not on the slow start.\n"
    "R2. CURIOSITY GAP: the first sentence opens a specific question in the viewer's head; the full answer comes only in the "
    "last 20% of the script. Never resolve it early.\n"
    "R3. RE-HOOK at 30-50%: one honest 'open loop' line that promises something still coming ('but that's not even the "
    "strangest part', 'and the reason is right here') — and you MUST deliver it later.\n"
    "R4. PATTERN INTERRUPT every ~5-7 seconds of narration: a turn ('but', 'here's the thing'), a contrast, a concrete number, "
    "a direct question, a change of focus — never a flat stretch of description.\n"
    "R5. SPECIFIC beats vague: numbers, names, exact details (credibility + curiosity). Cut empty adjectives.\n"
    "R6. STAKES / TENSION when real: what could go wrong, what it costs, why it is harder than it looks.\n"
    "R7. DIRECT ADDRESS: talk to ONE viewer ('look at her left hand', 'you'd think…') and point their eyes to what matters.\n"
    "R8. SOCIAL PROOF / DEBATE from the inputs only: 'half the comments swear that…' — never invented.\n"
    "R9. RHYTHM: mostly short sentences (4-10 words), one idea each; delete every sentence that adds neither information nor "
    "tension; no filler words.\n"
    "R10. END ON THE PAYOFF: the last line is the answer/twist or a sharp, specific question — then stop. No 'follow for more', "
    "no summary, no goodbye.")
REGRA_SEM_LOOP = "\nR11. Do NOT write a loop ending (the last line must NOT flow back into the first one) — the creator does not want loops."
REGRA_LOOP = ("\nR11. LOOP ENDING (asked by the creator): the last line flows straight into the first sentence, so when the short "
              "restarts it feels like one continuous thought.")


def regra_retencao(p: Dict[str, Any]) -> str:
    if not retencao(p):
        return REGRA_LOOP.replace("\nR11. ", "\n\n🔁 ") if final_loop(p) else ""
    return REGRA_RETENCAO + (REGRA_LOOP if final_loop(p) else REGRA_SEM_LOOP)


def regra_tipos(p: Dict[str, Any]) -> str:
    if explicativo(p) or not autentico_ou_mais(p):
        return ""
    g, f = tipos_do_video(p)
    return (f"## HOOK TYPE for this video: {TIPOS_GANCHO[g]}\n## ENDING TYPE for this video: {TIPOS_FINAL[f]}\n"
            "(The shapes only show the STRUCTURE: fill every <…> with THIS clip's own subject and details. Never mention an animal, "
            "object or topic that is not in this clip, and never reuse a shape word for word.)")


def sistema(p: Dict[str, Any]) -> str:
    base_ = EXPLICATIVO_SYS if explicativo(p) else ROTEIRO_SYS
    extra = REGRA_AUTENTICA if (not explicativo(p) and autentico_ou_mais(p)) else ""
    if not explicativo(p) and estilo_roteiro(p) == "personalidade":  # 🎭 v84_345
        extra += REGRA_PERSONALIDADE
    if not explicativo(p) and composto(p):  # 🧩 v84_349
        extra += REGRA_COMPOSTO.replace("{N}", str(composto(p)))
    extra += regra_localizar(p)  # 🌍 v84_352: em todos os estilos (e no explicativo)
    extra += regra_retencao(p)  # 🧲 v84_354: gatilhos de atenção (e o 🔁 loop só se você ligar)
    import camera_exp
    if not explicativo(p) and camera_exp.ligada(p):  # 🎥 v84_322
        narrada = "Brazilian Portuguese" if dados(p).get("idioma") == "pt" else nome_lingua(lingua_post(p))
        extra += camera_exp.REGRA_CAMERA.replace("{LINGUA}", narrada + " (the NARRATED language)")
    return (base_.replace("{REGRA_LINGUA}", regra_lingua(p)).replace("{REGRA_OPCOES}", REGRA_OPCOES)
            .replace("{REGRA_FONTES}", _regra_fontes(p))
            .replace("{LINGUA}", nome_lingua(lingua_post(p)))) + extra + regra_destaques(p)


REGRA_DESTAQUE = {  # 🎯 v84_308: círculo/seta só quando precisa
    "precisa": ("\n\nDESTAQUE (círculo/seta) — ONLY WHEN NEEDED: use 'destaque' only if the viewer could MISS what the line talks "
                "about (small, far away, in a crowd, partly hidden, off to the side) AND the line points right at it. If the subject "
                "is big, centered and obvious (most clips), leave alvo ''. Most videos need 0; never more than 1 per ~20 s."),
    "nunca": "\n\nDESTAQUE: do NOT use 'destaque' in this video — alvo '' everywhere.",
    "livre": "",
}


def nivel_destaques(p: Dict[str, Any]) -> str:
    v = (p.get("config") or {}).get("destaques") or "livre"  # (projetos antigos: como era)
    return v if v in REGRA_DESTAQUE else "livre"


def regra_destaques(p: Dict[str, Any]) -> str:
    return REGRA_DESTAQUE[nivel_destaques(p)]


def _texto_linhas(base: str, p: Dict[str, Any]) -> str:
    c = dados(p)
    L = []
    for m in clipes(base, p):
        L.append(f"### {m['id']} — {m.get('descricao') or 'clip'} ({float(m.get('dur') or CT.duracao_audio(m['caminho'])):.1f} s)")
        for l in [x for x in c["linhas"] if x.get("mid") == m["id"]]:
            t = (f"[{l['t0']:.1f}s" + (f"-{l['t1']:.1f}s" if l.get("t1") is not None else "") + "]") if l.get("t0") is not None else "[?]"
            L.append(f"{t} ({'speech' if l.get('tipo') == 'fala' else 'what you see' if l.get('tipo') == 'visual' else 'note'}) {l['texto']}")
    soltas = [x for x in c["linhas"] if x.get("mid") not in {m["id"] for m in clipes(base, p)}]
    for l in soltas:
        L.append(f"[{l.get('t0') or '?'}] {l['texto']}")
    return "\n".join(L)


def conteudo_explicativo(base: str, p: Dict[str, Any]) -> str:
    perfil = CT.perfil_do(base, p)
    pedido = float((p.get("config") or {}).get("duracao_alvo_s") or 0)
    L = [f"LENGTH: about {int(pedido)} seconds ≈ {int(pedido * 2.6)} words (asked by the creator)." if pedido else
         "LENGTH: what the topic needs (usually 25-55 s).", f"POST LANGUAGE: {nome_lingua(lingua_post(p))}."]
    if CT.proporcao_do(p) == "1:1":
        L.append(CT.TEXTO_QUADRADO_EN)
    n = (p.get("noticia") or {})
    L += ["", "## THE TOPIC (from the creator)", (n.get("texto") or "(see the sources)")[:4000], ""]
    for f in n.get("fontes") or []:
        if f.get("texto"):
            L += [f"## ARTICLE: {f.get('titulo') or f.get('url')}", f["texto"][:3500], ""]
    ref = (dados(p).get("referencia") or "").strip()
    if ref:
        L += ["## REFERENCE (a short about the same topic — rewrite, never copy; ignore [music] and song lyrics)", ref[:5000], ""]
    if modo_midia(p) != "flow":
        L += ["## YOUR VIDEO SOURCES (seconds of each source)", _texto_linhas(base, p) or "(none — use 'video'/'foto'/'ia' cenas)", ""]
    if (p.get("config") or {}).get("extra"):
        L += ["## EXTRA REQUEST", p["config"]["extra"], ""]
    ni = perfil.get("nicho") if isinstance(perfil.get("nicho"), dict) else {}
    if ni.get("tema"):
        L += ["## CHANNEL NICHE", f"{ni['tema']}" + (f" — typical shots: {ni['visual']}" if ni.get("visual") else "")
              + (f" — hashtags: {' '.join(ni.get('hashtags') or [])}" if ni.get("hashtags") else ""), ""]
    estilo = CT.texto_do_perfil(perfil)
    if estilo:
        L += ["## CHANNEL STYLE", estilo]
    return "\n".join(L)


def conteudo_roteiro(base: str, p: Dict[str, Any]) -> str:
    if explicativo(p):
        return conteudo_explicativo(base, p)
    c = dados(p)
    perfil = CT.perfil_do(base, p)
    ref = (c.get("referencia") or "").strip()
    dur_ref = duracao_da_referencia(ref) if ref else None
    pedido = float((p.get("config") or {}).get("duracao_alvo_s") or 0)
    dur_clipes = sum(float(m.get("dur") or 0) for m in clipes(base, p))
    if pedido:
        alvo = f"LENGTH: about {int(pedido)} seconds of narration ≈ {int(pedido * 2.6)} words (asked by the creator)."
    elif composto(p):  # 🧩 v84_349: 60+ — o que o material sustenta
        alvo = (f"LENGTH: 60+ seconds — what the {composto(p)} clips honestly support (they last {dur_clipes:.0f} s together): at least "
                "60 s ≈ 160 words, usually 70-100 s, never above 170 s.")
    elif dur_ref:
        alvo = f"LENGTH: close to the reference — about {int(dur_ref)} seconds ≈ {int(dur_ref * 2.6)} words."
    else:
        alvo = (f"LENGTH: what this story needs — the clip(s) last {dur_clipes:.0f} s in total; usually the narration covers the clip "
                f"once (roughly {max(8, int(dur_clipes * 0.8))}-{max(15, int(dur_clipes * 1.4))} s), shorter if there is little to tell.")
    L = [alvo, f"POST LANGUAGE: {nome_lingua(lingua_post(p))}.", *([CT.TEXTO_QUADRADO_EN] if CT.proporcao_do(p) == "1:1" else []), "",
         "## THE CLIP(S) — timeline (seconds of each clip)", _texto_linhas(base, p) or "(no timeline — use the notes)", ""]
    if ref:
        L += ["## REFERENCE — transcript of the original short / a video talking about this clip (rewrite it, don't copy). It may be "
              "messy: an uploader's description, the same story told twice, '[music]' marks and the LYRICS of the background song "
              "mixed in. Keep only the story (what happens, the twist, the payoff) and ignore the noise; the seconds of each moment "
              "come from the clip timeline above, not from here.", ref[:6000], ""]
    if (p.get("noticia") or {}).get("texto"):
        L += ["## NOTES FROM THE CREATOR", p["noticia"]["texto"][:4000], ""]
    dica = str((p.get("link_rapido") or {}).get("dica") or "").strip()
    if dica:  # 💡 v84_353: o que você escreveu antes do link ('Eclipse com skate: https://…')
        L += ["## WHAT THE CREATOR SAYS THIS VIDEO IS ABOUT (written next to the link — trust it as the topic; it may be short or "
              "in Portuguese)", dica[:300], ""]
    if c.get("info_link") or c.get("modo_link"):  # 🔗 v84_286: a legenda do post original e o que o público comenta
        import curtos_link as CL
        infos_ = c.get("info_links") or []
        if infos_:  # 🧩 v84_349: cada fonte com a sua legenda, o seu criador e os comentários
            mid_de = {m.get("origem"): m["id"] for m in clipes(base, p)}
            for i in infos_:
                inf, u = i.get("info") or {}, i.get("url") or ""
                quem = CL.criador(u, inf)
                L.append(f"## SOURCE {mid_de.get(u, '?')} — by @{quem.lstrip('@')}" if quem else f"## SOURCE {mid_de.get(u, '?')}")
                b_ = CL.texto_para_ia(dict(inf, comentarios=(inf.get("comentarios") or [])[:25]))
                L += [b_.replace("## THE ORIGINAL POST", "### its post").replace("## WHAT VIEWERS SAY", "### what viewers say") if b_ else "(no caption/comments)", ""]
        else:
            bloco = CL.texto_para_ia(c.get("info_link") or {})
            if bloco:
                L += [bloco, ""]
        lr_ = p.get("link_rapido") or {}
        if lr_.get("local") or lr_.get("musica"):  # 📍🎵 v84_351: o que VOCÊ escreveu no cartão vale mais que o do post
            L += [x for x in (f"Location (written by the creator of this video — trust it): {lr_['local']}" if lr_.get("local") else "",
                              f"Song on the post (context only): {lr_['musica']}" if lr_.get("musica") else "") if x] + [""]
        if c.get("modo_link"):
            L += ["## " + CL.regra_modo(c["modo_link"]), ""]
            link = (p.get("link_rapido") or {}).get("link") or ""
            quem = CL.criador(link, c.get("info_link") or {})
            if quem and c["modo_link"] in ("arte", "auto"):  # 🎨 v84_309: o artista é o @ do link
                L += [f"## THE CREATOR / ARTIST of this clip: @{quem.lstrip('@')}" + (f" ({CL.plataforma(link)})" if CL.plataforma(link) else "")
                      + " — name them when you present the work (say it so it reads well aloud).", ""]
    tipos = regra_tipos(p)  # ✨ v84_321
    if tipos:
        L += [tipos, ""]
    if (p.get("config") or {}).get("extra"):
        L += ["## EXTRA REQUEST (the creator's request wins over the hook/ending type)", p["config"]["extra"], ""]
    canal_ = CT.canal_do(base, p) or {}
    desc_canal = str(canal_.get("descricao") or "").strip()  # 📝 a descrição do canal (escrita por você)
    if desc_canal:
        L += ["## WHAT THIS CHANNEL IS ABOUT (the creator's own description — follow it)", desc_canal, ""]
    if not explicativo(p) and estilo_roteiro(p) == "personalidade":  # 🎭 v84_345: a persona + o que NÃO repetir
        L += ["## CHANNEL PERSONA (the narrator)", persona_do_canal(canal_), ""]
        rec = roteiros_recentes(base, p)
        if rec:
            L += ["## RECENT SCRIPTS OF THIS CHANNEL — do NOT repeat their openings, punchlines or structure", *rec, ""]
    estilo = CT.texto_do_perfil(perfil)
    if estilo:
        L += ["## CHANNEL STYLE", estilo]
    return "\n".join(L)


def prompt_roteiro(base: str, p: Dict[str, Any]) -> str:
    return (sistema(p) + "\n\n" + conteudo_roteiro(base, p) + "\n\nAnswer ONLY with JSON in this format (no ```):\n"
            + json.dumps(CT._exemplo_schema(roteiro_schema(p)), ensure_ascii=False, indent=1))


def ler_roteiro(resp: Any, p: Dict[str, Any], idioma: str = "en") -> Dict[str, Any]:
    """Resposta da IA → o roteiro do curto (a "fala" é a do idioma narrado; a outra fica do lado)."""
    if isinstance(resp, str):
        import json_ia
        try:
            resp = json_ia.carregar(resp)
        except Exception as exc:  # noqa: BLE001
            raise CT.CurtoErro(f"Não entendi o JSON do roteiro: {exc}") from exc
    if not isinstance(resp, dict):
        raise CT.CurtoErro("O roteiro precisa ser um objeto JSON.")
    blocos = []
    for b in resp.get("blocos") or []:
        if not isinstance(b, dict):
            continue
        en, pt = str(b.get("fala_en") or b.get("fala") or "").strip(), str(b.get("fala_pt") or "").strip()
        fala = en if idioma == "en" or not pt else pt
        cenas = []
        for cn in b.get("cenas") or []:
            if not isinstance(cn, dict):
                continue
            lay = cn.get("layout") or ("clipe" if cn.get("material") else "video")
            if lay == "clipe" or (cn.get("material") and lay not in ("video", "foto", "ia", "ia_video")):
                cenas.append(dict(cn, layout="materia", query="", visual=cn.get("visual") or ""))
            else:  # 📚 nenhuma fonte mostra: banco de vídeo / foto / imagem de IA
                q = str(cn.get("query") or cn.get("visual") or "").strip()
                if q:
                    cenas.append({"layout": lay if lay in ("video", "foto", "ia", "ia_video") else "ia", "query": q, "visual": q,
                                  "alternativas": [], "material": "", "palavra": cn.get("palavra") or "", "efeito": cn.get("efeito") or "",
                                  "entrada": cn.get("entrada") or "none", "composicao": ""})
        blocos.append(dict(b, fala=fala, fala_en=en, fala_pt=pt, cenas=cenas))
    if not explicativo(p) and so_fontes(p):  # 🎞 v84_330: "só com os meus vídeos" — nenhuma cena sai do clipe
        segurar_no_clipe(p, blocos)
    import camera_exp
    if not explicativo(p) and camera_exp.ligada(p):  # 🎥 v84_322: o teto de efeitos
        camera_exp.aplicar_teto({"blocos": blocos})
    r = CT.ler_roteiro(dict(resp, blocos=blocos), p)
    for k in ("ganchos", "finais", "titulos"):
        r[k] = [{"en": str(o.get("en") or "")[:400], "pt": str(o.get("pt") or "")[:400]} for o in resp.get(k) or []
                if isinstance(o, dict) and (o.get("en") or o.get("pt"))][:20]
    r["idioma"] = idioma
    return r


_SUGESTAO_DE = {"video": "clipe_real", "foto": "foto_real", "ia": "ia", "ia_video": "ia_video"}


def segurar_no_clipe(p: Dict[str, Any], blocos: List[Dict[str, Any]]) -> int:
    """🎞 v84_330: num curto de comentário "só com os meus vídeos", a cena que a IA mandou buscar FORA do clipe (banco
    de vídeo, foto, imagem gerada) volta pro clipe — o pedaço logo depois da cena anterior — e a ideia dela fica como
    💡 sugestão (você aceita na página do curto, se quiser). Antes ela ia pros bancos e, sem achar, travava a exportação."""
    clips = [m for m in p.get("midias") or [] if m.get("tipo") == "video" and str(m.get("id") or "").startswith("M")]
    if not clips:
        return 0
    durs = {m["id"]: float(m.get("dur") or 0) for m in clips}
    ultimo: Optional[Dict[str, Any]] = None
    n = 0
    for b in blocos:
        novas = []
        for cn in b.get("cenas") or []:
            if cn.get("layout") == "materia" and cn.get("material"):
                ultimo = cn
                novas.append(cn)
                continue
            if cn.get("layout") not in _SUGESTAO_DE:  # cartão de texto etc.: fica como está
                novas.append(cn)
                continue
            if ultimo:
                mid = ultimo["material"]
                total = durs.get(mid) or 0
                try:
                    de = float(ultimo.get("ate") if ultimo.get("ate") not in (None, "") else ultimo.get("de") or 0)
                except (TypeError, ValueError):
                    de = 0.0
                if total and de >= total - 0.8:
                    de = max(0.0, total - 2.5)
                ate = min(total, de + 2.5) if total else de + 2.5
            else:
                mid, de = clips[0]["id"], 0.0
                ate = min(durs.get(mid) or 3.0, 3.0)
            q = str(cn.get("query") or cn.get("visual") or "").strip()
            nova = {"layout": "materia", "query": "", "visual": cn.get("visual") or q, "alternativas": [], "material": mid,
                    "de": round(de, 2), "ate": round(max(de, ate), 2), "palavra": cn.get("palavra") or "", "efeito": cn.get("efeito") or "",
                    "entrada": cn.get("entrada") or "none", "composicao": ""}
            if q:
                nova["sugestao"] = {"layout": _SUGESTAO_DE.get(cn.get("layout"), "clipe_real"), "query": q[:160],
                                    "por_que": "a IA quis mostrar isto fora do clipe (o vídeo segue no clipe; aceite se quiser)"}
            novas.append(nova)
            ultimo = nova
            n += 1
        b["cenas"] = novas
    return n


def gerar_roteiro(base: str, pid: str, chamar: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    p = CT.carregar(base, pid)
    if explicativo(p):
        n = p.get("noticia") or {}
        if not (n.get("texto") or any(f.get("texto") for f in n.get("fontes") or []) or dados(p).get("referencia") or p.get("titulo")):
            raise CT.CurtoErro("Diga o assunto (o que o vídeo explica) ou cole o link de uma matéria sobre ele.")
    elif not clipes(base, p):
        raise CT.CurtoErro("Suba o vídeo cru (o clipe) antes.")
    elif not dados(p)["linhas"] and not dados(p).get("referencia") and not (p.get("noticia") or {}).get("texto"):
        raise CT.CurtoErro("Diga o que acontece no clipe: a transcrição, uma descrição com os segundos, ou use 🎙/👁 pra tirar sozinho.")
    import ia_servico
    r = (chamar or ia_servico.chamar)("curtos", sistema(p), conteudo_roteiro(base, p), schema=roteiro_schema(p), max_tokens=12000,
                                      **({} if chamar else {"timeout": 240.0}),
                                      effort="medium", job=pid, cache_local=False)
    if not r:
        raise CT.CurtoErro(CT.motivo_ia() + " Use o 📋 prompt numa outra IA e cole a resposta.")
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        p["roteiro"] = ler_roteiro(r, p, dados(p).get("idioma") or "en")
        p["tts"] = None
        CT.salvar(base, p)
    return p["roteiro"]


def _guardar_versao(p: Dict[str, Any]) -> None:
    if (p.get("roteiro") or {}).get("blocos"):
        h = p.setdefault("roteiro_historico", [])
        h.append(p["roteiro"])
        del h[:-5]  # (as 5 últimas)


def revisar_roteiro(base: str, pid: str, pedido: str, chamar: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """✍ v84_343: reescreve o roteiro com os SEUS comentários/sugestões (mesmo prompt, mesmas regras do canal + o roteiro de
    antes e o que mudar). O de antes vai pro histórico (↶ desfazer). A voz/edição ficam pra refazer com o roteiro novo."""
    import copy
    p = CT.carregar(base, pid)
    r0 = p.get("roteiro") or {}
    if not r0.get("blocos"):
        raise CT.CurtoErro("Faça o roteiro antes.")
    antes = "\n".join(f"{b.get('id') or k}: {b.get('fala_en') or b.get('fala') or ''}" for k, b in enumerate(r0["blocos"], 1))
    p2 = copy.deepcopy(p)
    extra = str((p2.get("config") or {}).get("extra") or "")
    p2.setdefault("config", {})["extra"] = (extra + "\n\n" if extra else "") + (
        "## REVISION — the creator reviewed the PREVIOUS SCRIPT below and wants changes. Rewrite the script applying EVERY "
        "request, keep what they did not ask to change (same facts, structure and length unless asked), and still follow all "
        "the rules above.\n### CREATOR'S CHANGES (may be in Portuguese)\n" + str(pedido)[:3000] + "\n### PREVIOUS SCRIPT\n" + antes)
    import ia_servico
    r = (chamar or ia_servico.chamar)("curtos", sistema(p2), conteudo_roteiro(base, p2), schema=roteiro_schema(p2), max_tokens=12000,
                                      **({} if chamar else {"timeout": 240.0}), effort="medium", job=pid, cache_local=False)
    if not r:
        raise CT.CurtoErro(CT.motivo_ia())
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        _guardar_versao(p)
        p["roteiro"] = ler_roteiro(r, p, (p.get("roteiro") or {}).get("idioma") or dados(p).get("idioma") or "en")
        p["roteiro"]["pedido_revisao"] = str(pedido)[:3000]
        p["tts"] = None
        CT.salvar(base, p)
    return p["roteiro"]


def desfazer_roteiro(base: str, pid: str) -> Dict[str, Any]:
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        h = p.get("roteiro_historico") or []
        if not h:
            raise CT.CurtoErro("Não tem versão anterior do roteiro.")
        p["roteiro"] = h.pop()
        p["roteiro_historico"] = h
        p["tts"] = None
        CT.salvar(base, p)
    return p["roteiro"]


_TRAD_SCHEMA = CT._o({"blocos": {"type": "array", "items": CT._o({"id": CT._s(), "pt": CT._s()})}})


def traduzir_roteiro(base: str, pid: str, chamar: Optional[Callable[..., Any]] = None) -> int:
    """🇧🇷 v84_343: a tradução pro português dos blocos que não têm (roteiros antigos ou ajustados à mão)."""
    p = CT.carregar(base, pid)
    bl = (p.get("roteiro") or {}).get("blocos") or []
    falta = [b for b in bl if CT.sem_tags(b.get("fala") or "").strip() and not str(b.get("fala_pt") or "").strip()]
    if not falta:
        return 0
    import ia_servico
    corpo = json.dumps([{"id": str(b.get("id")), "texto": CT.sem_tags(b.get("fala") or "")} for b in falta], ensure_ascii=False)
    r = (chamar or ia_servico.chamar)("curtos", "Translate each line to natural Brazilian Portuguese (meaning, not word by word). "
                                      "Return every id.", corpo, schema=_TRAD_SCHEMA, max_tokens=4000)
    if not r:
        raise CT.CurtoErro(CT.motivo_ia())
    tr = {str(x.get("id")): str(x.get("pt") or "").strip() for x in (r.get("blocos") or []) if isinstance(x, dict)}
    n = 0
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        for b in (p.get("roteiro") or {}).get("blocos") or []:
            if tr.get(str(b.get("id"))) and not str(b.get("fala_pt") or "").strip():
                b["fala_pt"] = tr[str(b.get("id"))]
                n += 1
        CT.salvar(base, p)
    return n


MAIS_SCHEMA = CT._o({"opcoes": {"type": "array", "items": OPCAO}})


DIRECOES_TITULO = {  # 🏷 v84_305: direções prontas pros títulos novos
    "curiosidade": ("🤔 curiosidade", "create a curiosity gap — make people NEED to watch to find out"),
    "pergunta": ("❓ pergunta", "phrase it as a question people want to answer in the comments"),
    "polemico": ("🔥 polêmico", "a bold, debatable take people will argue about (still honest, no fake claims)"),
    "engracado": ("😂 engraçado", "funny, witty, playful"),
    "emocao": ("🥹 emoção", "emotional / heartwarming / awe"),
    "curto": ("✂ bem curto", "very short: 2 to 5 words"),
    "numero": ("🔢 com número", "include a number, a stat or a concrete detail"),
    "seo": ("🔎 SEO / busca", "clear searchable keywords of what happens (what people would type in search)"),
    "emoji": ("✨ com emoji", "include 1 or 2 fitting emojis"),
}


def mais_opcoes(base: str, pid: str, qual: str, chamar: Optional[Callable[..., Any]] = None, direcao: str = "",
                comentario: str = "") -> List[Dict[str, str]]:
    """➕ mais 5 ganchos (ou 5 finais/títulos), diferentes dos que já tem. Títulos: com uma direção pronta e/ou o seu pedido."""
    if qual not in ("ganchos", "finais", "titulos"):
        raise CT.CurtoErro("Pedido inválido.")
    p = CT.carregar(base, pid)
    r = p.get("roteiro") or {}
    if not r.get("blocos"):
        raise CT.CurtoErro("Faça o roteiro antes.")
    corpo = " ".join(CT.sem_tags(b.get("fala_en") or b["fala"]) for b in r["blocos"])
    ja = "\n".join(f"- {o['en']}" for o in r.get(qual) or [])
    tipo = "explainer/curiosity short" if explicativo(p) else "commentary short"
    lingua = nome_lingua(lingua_post(p))
    pedido = {"ganchos": f"Write 5 NEW, stronger HOOKS (first sentence) for this {tipo} — curiosity, contradiction, surprising claim; under 15 words.",
              "finais": f"Write 5 NEW engaging ENDINGS for this {tipo} — a question people argue about in the comments, or a last curious fact; one sentence.",
              "titulos": f"Write 5 NEW post TITLES for this {tipo} — short, curiosity, honest (no fake claims)."}[qual]
    tag = " (may use one voice tag like [gasp])" if lingua_post(p) == "en" and qual != "titulos" else ""
    guia = ""
    if qual in ("ganchos", "finais") and not explicativo(p) and autentico_ou_mais(p):  # ✨ v84_321
        tipos = TIPOS_GANCHO if qual == "ganchos" else TIPOS_FINAL
        guia += ("\nEach one a DIFFERENT type from: " + "; ".join(f"{k} = {v}" for k, v in tipos.items())
                 + "\nSpecific to this clip, click-worthy through curiosity, honest. Never: 'Everyone thought', 'But look closer', "
                 "'You won't believe', 'Would you ever…?', 'What would you do?'.")
    if qual == "titulos":
        if direcao in DIRECOES_TITULO:
            guia += f"\nSTYLE: {DIRECOES_TITULO[direcao][1]}."
        comentario = " ".join(str(comentario or "").split())[:600]
        if comentario:
            guia += f"\nTHE CREATOR'S DIRECTION (follow it; it may be in Portuguese): {comentario}"
    txt = (f"{pedido}{guia}\nDifferent from these:\n{ja or '(none)'}\n\nSCRIPT:\n{corpo}\n\n"
           f"Each with 'en' (in {lingua}{tag}) and 'pt' (Brazilian Portuguese).")
    import ia_servico
    resp = (chamar or ia_servico.chamar)("curtos", sistema(p), txt, schema=MAIS_SCHEMA, max_tokens=1200, job=pid, cache_local=False)
    if not resp:
        raise CT.CurtoErro(CT.motivo_ia())
    novas = [{"en": str(o.get("en") or "")[:400], "pt": str(o.get("pt") or "")[:400]} for o in resp.get("opcoes") or [] if o.get("en")]
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        if qual == "titulos" and (direcao or comentario):  # os pedidos agora aparecem primeiro na lista
            p["roteiro"][qual] = novas + (p["roteiro"].get(qual) or [])
        else:
            p["roteiro"][qual] = (p["roteiro"].get(qual) or []) + novas
        CT.salvar(base, p)
    return novas


def escolher(base: str, pid: str, qual: str, i: int) -> Dict[str, Any]:
    """O gancho (1º bloco) ou o final (último bloco) passa a ser a opção i — nas duas línguas."""
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        r = p.get("roteiro") or {}
        ops = r.get(qual) or []
        if not (0 <= i < len(ops)) or not r.get("blocos"):
            raise CT.CurtoErro("Opção não encontrada.")
        o = ops[i]
        if qual == "titulos":  # 🏷 o título da postagem (não mexe na fala)
            r["titulo_video"], r["titulo_pt"], r["titulos_escolhido"] = o["en"], o["pt"], i
            CT.salvar(base, p)
            return r
        b = r["blocos"][0] if qual == "ganchos" else r["blocos"][-1]
        b["fala_en"], b["fala_pt"] = o["en"], o["pt"]
        b["fala"] = o["en"] if (r.get("idioma") or "en") == "en" or not o["pt"] else o["pt"]
        r[f"{qual}_escolhido"] = i
        CT.salvar(base, p)
    CT.realinhar(base, pid)
    return p["roteiro"]


def trocar_idioma(base: str, pid: str, idioma: str) -> None:
    """🇺🇸/🇧🇷 qual das duas versões é NARRADA (a outra fica do lado pra conferir)."""
    if idioma not in ("en", "pt"):
        raise CT.CurtoErro("Idioma inválido.")
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        dados(p)["idioma"] = idioma
        narrada = "pt" if idioma == "pt" else lingua_post(p)  # 🎙 Chatterbox Turbo só fala inglês (com as tags); o resto vai no multilíngue
        p["config"]["motor_perfil"] = "chatterbox_turbo" if narrada == "en" else "chatterbox"
        r = p.get("roteiro") or {}
        for b in r.get("blocos") or []:
            alvo = b.get("fala_en") if idioma == "en" else b.get("fala_pt")
            if alvo:
                b["fala"] = alvo
        r["idioma"] = idioma
        CT.salvar(base, p)


def sugestoes(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    """💡 As mídias que a IA sugeriu buscar (quando seus vídeos não mostram a frase)."""
    out = []
    for bi, b in enumerate((p.get("roteiro") or {}).get("blocos") or []):
        for ci, c in enumerate(b.get("cenas") or []):
            sg = c.get("sugestao") or {}
            if sg.get("layout") and sg.get("query"):
                out.append({"bloco": bi, "id": b["id"], "cena": ci, "fala": CT.sem_tags(b.get("fala_pt") or b["fala"])[:160],
                            "layout": sg["layout"], "query": sg["query"], "por_que": sg.get("por_que") or "",
                            "usada": c.get("layout") == sg["layout"],
                            "fonte": c.get("material") or (c.get("reserva") or {}).get("material") or ""})
    return out


def usar_sugestao(base: str, pid: str, bloco: int, cena: int, usar: bool = True) -> Dict[str, Any]:
    """✔ A cena passa a buscar a mídia sugerida (buscador de imagem / YouTube / imagem gerada) — ou volta pro seu vídeo."""
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        try:
            c = p["roteiro"]["blocos"][bloco]["cenas"][cena]
        except (KeyError, IndexError, TypeError):
            raise CT.CurtoErro("Cena não encontrada.")
        sg = c.get("sugestao") or {}
        if not sg.get("layout"):
            raise CT.CurtoErro("Essa cena não tem sugestão.")
        if usar and c.get("layout") != sg["layout"]:
            c["reserva"] = {k: c.get(k) for k in ("layout", "material", "de", "ate", "destaque") if c.get(k) is not None}
            c.update(layout=sg["layout"], query=sg["query"], visual=sg["query"], material="")
            for k in ("de", "ate", "destaque"):
                c.pop(k, None)
        elif not usar and c.get("reserva"):
            c.update(c.pop("reserva"))
            c["query"] = ""
        CT.salvar(base, p)
        return c


def definir_lingua_post(base: str, pid: str, lp: str) -> None:
    """🌍 Em que idioma o vídeo é POSTADO (o roteiro sai nele + a tradução em português). Vale pro próximo roteiro."""
    if lp not in CT.LINGUAS:
        raise CT.CurtoErro("Idioma inválido.")
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        dados(p)["lingua_post"] = lp
        if dados(p).get("idioma") != "pt":
            p["config"]["motor_perfil"] = "chatterbox_turbo" if lp == "en" else "chatterbox"
        CT.salvar(base, p)


# ------------------------------------------------------------------ voz: 3 takes
def gerar_takes(base: str, pid: str, tts, limpar, voz: Dict[str, Any], n: int = 3, on_log: Callable[[str], None] = lambda _m: None) -> List[Dict[str, Any]]:
    """🎙 A mesma fala n vezes (o Chatterbox sai um pouco diferente a cada vez) — escolha o take com a melhor pronúncia."""
    takes = []
    for k in range(1, max(1, min(5, n)) + 1):
        on_log(f"🎙 take {k}/{n}")
        info = CT.gerar_voz_guia(base, pid, tts, limpar, voz, on_log=lambda m, k=k: on_log(f"🎙 take {k}/{n} — {m}"),
                                 sub=f"takes/t{k}", guardar=False)
        takes.append(dict(info, take=k))
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        p["takes"] = takes
        p["tts"] = dict(takes[0])
        CT.salvar(base, p)
    return takes


def usar_take(base: str, pid: str, k: int, transcrever, opcoes: Optional[Dict[str, Any]] = None,
              on_log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    p = CT.carregar(base, pid)
    t = next((x for x in p.get("takes") or [] if int(x.get("take") or 0) == int(k)), None)
    if not t:
        raise CT.CurtoErro("Take não encontrado.")
    with CT._TRAVA:
        q = CT.carregar(base, pid)
        q["tts"] = dict(t)
        q["take_escolhido"] = int(k)
        CT.salvar(base, q)
    return CT.processar_gravacao(base, pid, transcrever, os.path.join(CT.pasta(base, pid), t["arquivo"]), opcoes or {}, on_log, fonte="guia")


# ------------------------------------------------------------------ 🎯 destaques (a IA acha o objeto, o rastreio segue)
CAIXA_SCHEMA = CT._o({"achou": CT._b(), "certeza": CT._n(), "x": CT._n(), "y": CT._n(), "w": CT._n(), "h": CT._n()})
CAIXA_SYS = ("You locate an object in a video frame for an automatic tracker that will draw a circle/arrow on it. The image has a light "
             "grid every 10% of the width/height. Return the bounding box of the requested object as FRACTIONS of the image (x,y = "
             "top-left, w,h = size, all 0..1), tight around it. 'certeza' 0..1 = how sure you are this box is THAT object (a small "
             "dog in a crowd of sheep, a person far away: look carefully; 0.9+ only when you clearly see it). If it is not clearly "
             "visible, achou=false. A wrong box is much worse than none.")


def _quadro(video: str, t: float, destino: str) -> Optional[str]:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", video, "-frames:v", "1", "-vf",
                    "drawgrid=w=iw/10:h=ih/10:t=1:c=white@0.25", destino], capture_output=True, timeout=60)
    return destino if os.path.isfile(destino) else None


def achar_com_moondream(base: str, video: str, t: float, alvo: str, pasta_tmp: str) -> Optional[List[float]]:
    """🎯 v84_302: o Moondream (se estiver ligado em 🔥 Momentos → 👁) acha o objeto bem mais justo que o Claude na grade."""
    try:
        import momentos_yt as MY
        if MY.config_visao(base).get("backend") != "hf":
            return None
        import rastreio
        info = rastreio.sondar(video)
        img = os.path.join(pasta_tmp, "quadro_md.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", video, "-frames:v", "1", img], capture_output=True, timeout=60)
        if not os.path.isfile(img):
            return None
        cs = MY.Visao(base).achar(img, alvo)
        if not cs or len(cs) > 1:  # 🎯 v84_304: vários parecidos (cão no meio das ovelhas) = ambíguo → o Claude decide qual é
            return None
        x0, y0, x1, y1 = cs[0]
        if (x1 - x0) * (y1 - y0) > 0.6:  # "achou" o quadro inteiro: não é o objeto
            return None
        W, H = info["largura"], info["altura"]
        return [round(x0 * W, 1), round(y0 * H, 1), round((x1 - x0) * W, 1), round((y1 - y0) * H, 1)]
    except Exception:  # noqa: BLE001
        return None


def achar_objeto(video: str, t: float, alvo: str, pasta_tmp: str, chamar: Optional[Callable[..., Any]] = None,
                 base: Optional[str] = None) -> Optional[List[float]]:
    """[x, y, w, h] em px do vídeo, ou None. Com o Moondream ligado, ele acha primeiro; senão (ou não achou), o Claude."""
    if base:
        cx = achar_com_moondream(base, video, t, alvo, pasta_tmp)
        if cx:
            return cx
    import ia_servico
    import rastreio
    info = rastreio.sondar(video)
    q = _quadro(video, t, os.path.join(pasta_tmp, "quadro_alvo.jpg"))
    if not q:
        return None
    b = ia_servico.imagem_bloco(q, largura=1280)  # 🎯 v84_304: mais resolução (objeto pequeno no meio de muita coisa)
    if not b:
        return None
    r = (chamar or ia_servico.chamar)("curtos", CAIXA_SYS, [b, {"type": "text", "text": f"Object: {alvo}"}], schema=CAIXA_SCHEMA,
                                      max_tokens=200)
    if not r or not r.get("achou"):
        return None
    try:
        if float(r.get("certeza", 1)) < 0.6:  # sem certeza: melhor sem círculo do que círculo no lugar errado
            return None
    except (TypeError, ValueError):
        pass
    try:
        x, y, w, h = (max(0.0, min(1.0, float(r[k]))) for k in ("x", "y", "w", "h"))
    except (TypeError, ValueError, KeyError):
        return None
    if w < 0.01 or h < 0.01:
        return None
    W, H = info["largura"], info["altura"]
    return [round(x * W, 1), round(y * H, 1), round(min(w, 1 - x) * W, 1), round(min(h, 1 - y) * H, 1)]


_VAZIAS = {"the", "a", "an", "of", "in", "on", "with", "and", "his", "her", "its", "o", "a", "do", "da", "de"}


def _palavras(t: str) -> set:
    return {w for w in re.findall(r"[a-zà-ú0-9]+", str(t or "").lower()) if w not in _VAZIAS and len(w) > 1}


def objeto_rastreado(p: Dict[str, Any], mid: str, alvo: str) -> Optional[str]:
    """O objeto que a câmera virtual já rastreou que bate com o alvo do destaque ("the ball" → "basketball")."""
    rs = (p.get("rastros") or {}).get(mid) or {}
    A = _palavras(alvo)
    melhor, nota = None, 0.0
    for nome in rs:
        N = _palavras(nome)
        comum = len(A & N) + 0.6 * sum(1 for a in A for n in N if a != n and (a in n or n in a))
        if comum > nota:
            melhor, nota = nome, comum
    return melhor


def chaves_dos_rastros(p: Dict[str, Any], mid: str, ini: float, fim: float, alvo: str) -> List[Dict[str, Any]]:
    """As caixas que a câmera virtual mediu (px do vídeo vertical) dentro de [ini, fim] → chaves do 🎯 rastreio (tempo do pedaço)."""
    nome = objeto_rastreado(p, mid, alvo)
    if not nome:
        return []
    return [{"t": round(float(t) - ini, 3), "caixa": [x, y, w, h]} for t, x, y, w, h in p["rastros"][mid][nome]
            if ini - 0.05 <= float(t) <= fim + 0.05 and w > 2 and h > 2]


def enquadrar_planos(base: str, pid: str, on_log: Callable[[str], None] = lambda _m: None) -> int:
    """🎥 v84_296: os clipes DEITADOS (com o mapa de objetos que a análise fez) viram pedaços VERTICAIS — um por plano, focando
    o objeto da fala daquela cena ('foco' do roteiro; vazio = o assunto principal). Sem detectar de novo: usa o mapa.
    Os pedaços entram como V1, V2… e o plano passa a usar eles (curtos.montar_dados_editor). Devolve quantos fez."""
    import camera_virtual as CV
    p = CT.carregar(base, pid)
    rh = p.get("rastros_h") or {}
    if not rh:
        return 0
    perfil = CT.perfil_do(base, p)
    planos_v = CT.planos_do_video(p, (p.get("config") or {}).get("providers") or CT.PROVIDERS_PADRAO, perfil)
    CT.fixar_trechos_do_clipe(planos_v, {m["id"]: float(m.get("dur") or 0) for m in p.get("midias") or []})
    feitos = dict(p.get("enquadrados") or {})
    novos = 0
    alvo = [x for x in planos_v if (x.get("clipe") or {}).get("mid") in rh and CT.chave_enquadrado(x) not in feitos]
    for k, x in enumerate(alvo, 1):
        c = x["clipe"]
        mapa = rh[c["mid"]]
        m = next((mm for mm in clipes(base, p) if mm["id"] == c["mid"]), None)
        if not m:
            continue
        foco = objeto_no_mapa(mapa, c.get("foco") or "") or mapa.get("principal") or ""
        on_log(f"🎥 vertical {k}/{len(alvo)}: {c['mid']} {c['ini']:.1f}-{c['fim']:.1f}s focando “{foco or 'o meio'}”…")
        tmp = os.path.join(CT.pasta(base, pid), "_enquadrar")
        os.makedirs(tmp, exist_ok=True)
        saida = os.path.join(tmp, "v.mp4")
        try:
            r = CV.enquadrar_pedaco(m["caminho"], float(c["ini"]), float(c["fim"]), saida, mapa.get("tracks") or {}, foco,
                                    mapa.get("principal") or "", mapa.get("cenas") or [])
        except Exception as exc:  # noqa: BLE001  (um pedaço ruim fica com o clipe como estava)
            on_log(f"🎥 não deu pra enquadrar esse pedaço: {str(exc)[:120]}")
            continue
        with CT._TRAVA:
            q = CT.carregar(base, pid)
            mm = CT.adicionar_midia(base, q, saida, "video", f"🎥 {foco or 'meio'} ({c['mid']} {c['ini']:.1f}-{c['fim']:.1f}s)", "V")
            q.setdefault("enquadrados", {})[CT.chave_enquadrado(x)] = {"mid": mm["id"], "rastros": r["rastros"], "foco": foco}
            CT.salvar(base, q)
            feitos = q["enquadrados"]
        novos += 1
    return novos


def objeto_no_mapa(mapa: Dict[str, Any], nome: str) -> Optional[str]:
    """O objeto do mapa que bate com o nome que o roteiro usou ("the ball" → "basketball")."""
    if not nome:
        return None
    tr = mapa.get("tracks") or {}
    if nome in tr:
        return nome
    A = _palavras(nome)
    melhor, nota = None, 0.0
    for o in tr:
        N = _palavras(o)
        comum = len(A & N) + 0.6 * sum(1 for a in A for n in N if a != n and (a in n or n in a))
        if comum > nota:
            melhor, nota = o, comum
    return melhor


def preparar_destaques(base: str, pid: str, providers: Optional[List[str]] = None, chamar: Optional[Callable[..., Any]] = None,
                       on_log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """Pra cada plano com destaque: recorta o pedaço do clipe, a IA acha o objeto, o rastreio segue e desenha → a mídia
    R1, R2… (o plano passa a usar ela). Sem IA / não achou: fica como PENDENTE (dá pra fazer no 🎯 Rastrear objeto)."""
    import rastreio
    p = CT.carregar(base, pid)
    perfil = CT.perfil_do(base, p)
    providers = providers or (p.get("config") or {}).get("providers") or CT.PROVIDERS_PADRAO
    planos_v = CT.planos_do_video(p, providers, perfil)
    CT.fixar_trechos_do_clipe(planos_v, {m["id"]: float(m.get("dur") or 0) for m in p.get("midias") or []})
    feitos, pendentes = [], []
    prontos = dict(p.get("destaques_prontos") or {})
    nivel = nivel_destaques(p)
    dur = float((p.get("gravacao") or {}).get("dur") or 0) or max([float(x.get("end") or 0) for x in planos_v] + [20.0])
    cota = 0 if nivel == "nunca" else (max(1, int(dur // 20)) if nivel == "precisa" else 99)
    import camera_exp
    if camera_exp.ligada(p) and nivel != "nunca":  # 🎥 v84_322: até 2, amarrados aos fatos (o teto do roteiro já filtrou)
        cota = camera_exp.MAX_DESTAQUES
    for x in planos_v:
        k = CT.chave_destaque(x)
        if not k:
            continue
        if cota <= 0:  # 🎯 v84_308: só os que precisam (o roteiro já pede pouco; aqui é o teto)
            continue
        cota -= 1
        if k in prontos and any(m["id"] == prontos[k] for m in p.get("midias") or []):
            feitos.append(prontos[k])
            continue
        c, d = x["clipe"], x["destaque"]
        enq = (p.get("enquadrados") or {}).get(CT.chave_enquadrado(x)) or {}
        if enq.get("mid"):  # 🎥 o pedaço já vertical: o círculo vai em cima dele, com o rastro medido nele
            mv = next((mm for mm in p.get("midias") or [] if mm["id"] == enq["mid"]), None)
            cam_v = CT.caminho_midia(base, p, mv) if mv else None
            if cam_v:
                m = {"id": enq["mid"], "caminho": cam_v}
                c = dict(c, mid=enq["mid"], ini=0.0, fim=float(mv.get("dur") or (c["fim"] - c["ini"])))
                p = dict(p, rastros=dict(p.get("rastros") or {}, **{enq["mid"]: enq.get("rastros") or {}}))
            else:
                m = None
        else:
            m = next((mm for mm in clipes(base, p) if mm["id"] == c["mid"]), None)
        if not m:
            continue
        tmp = os.path.join(CT.pasta(base, pid), "_destaque")
        os.makedirs(tmp, exist_ok=True)
        pedaco = os.path.join(tmp, "pedaco.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{c['ini']:.3f}", "-i", m["caminho"], "-t", f"{c['fim'] - c['ini']:.3f}",
                        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", pedaco],
                       capture_output=True, timeout=600)
        if not os.path.isfile(pedaco):
            pendentes.append({"chave": k, "alvo": d["alvo"], "motivo": "não consegui recortar o pedaço"})
            continue
        chaves = chaves_dos_rastros(p, c["mid"], c["ini"], c["fim"], d["alvo"])  # 🎥 v84_292: o rastro que a câmera já mediu
        caixa = chaves[0]["caixa"] if chaves else None
        if not chaves:
            on_log(f"🎯 procurando “{d['alvo']}”…")
            dur_p = max(0.6, float(c["fim"]) - float(c["ini"]))
            for tq in sorted({0.25, round(dur_p / 2, 2), round(max(0.3, dur_p - 0.3), 2)}):  # 3 momentos do pedaço, não 1
                try:
                    cx = achar_objeto(pedaco, tq, d["alvo"], tmp, chamar, base=base)
                except Exception:  # noqa: BLE001
                    cx = None
                if cx:
                    chaves.append({"t": tq, "caixa": cx})
            caixa = chaves[0]["caixa"] if chaves else None
        if not caixa:
            pendentes.append({"chave": k, "alvo": d["alvo"], "bloco": x["bloco"], "mid": c["mid"], "ini": c["ini"], "fim": c["fim"],
                              "motivo": "a IA não achou (ou está desligada) — faça no 🎯 Rastrear objeto"})
            continue
        on_log(f"🎯 rastreando “{d['alvo']}”…")
        try:
            r = rastreio.criar(base, pedaco, f"{p.get('titulo') or 'curto'} · {d['alvo']}")
            info = r["info"]
            r["caixas"] = rastreio.rastrear(rastreio.caminho_video(base, r), chaves, 0, info["dur"], info["fps"])
            r["estilo"] = rastreio.normalizar_estilo({"tipo": d.get("tipo") or "circulo", "texto": d.get("texto") or "", "cor": "#FF2D2D",
                                                       "direcao": "cima_esquerda", "entrada": "desenhar"})
            rastreio.salvar(base, r)
            saida = rastreio.gerar(base, r["id"])
        except Exception as exc:  # noqa: BLE001
            pendentes.append({"chave": k, "alvo": d["alvo"], "motivo": f"rastreio falhou: {str(exc)[:120]}"})
            continue
        with CT._TRAVA:
            q = CT.carregar(base, pid)
            novo = os.path.join(tmp, "r.mp4")
            import shutil
            shutil.copy(saida, novo)
            mm = CT.adicionar_midia(base, q, novo, "video", f"🎯 {d['alvo']} ({c['mid']} {c['ini']:.1f}-{c['fim']:.1f}s)", "R")
            q.setdefault("destaques_prontos", {})[k] = mm["id"]
            q.setdefault("destaques_rastreio", {})[k] = r["id"]  # 🎯 v84_304: no editor dá pra tirar/mudar o texto (o rastreio guarda o vídeo limpo)
            CT.salvar(base, q)
            prontos[k] = mm["id"]
            feitos.append(mm["id"])
    with CT._TRAVA:
        q = CT.carregar(base, pid)
        q["destaques_pendentes"] = pendentes
        CT.salvar(base, q)
    try:  # 🧹 o Moondream (se usado pros destaques) sai da memória antes do editor/exportar
        import momentos_yt as MY
        MY.liberar_moondream()  # (quem estiver usando agora segura a referência dele; o próximo carrega de novo)
    except Exception:  # noqa: BLE001
        pass
    return {"feitos": feitos, "pendentes": pendentes}
