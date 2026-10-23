"""
🎞 anime2d.py — o modelo de vídeo "Animação 2D" (aba 🕵️ Modelos de vídeo, v84_237)
===================================================================================

Desenho animado 2D do jeito simples (estilo Shin-chan): em vez de gerar VÍDEO com IA, o episódio é MONTADO com
imagens — fundo do lugar, personagens em poses (com quadros A/B que se alternam pra dar sensação de movimento e a boca
que abre e fecha quando falam), objetos na frente, imagens de destaque em tela cheia — e câmera (zoom/pan). Tudo vai pro
editor posicionado, com as vozes (uma por personagem + narrador) e as legendas.

Etapas:
  1. premissa + estilo (anime, cartoon, pintura a óleo, Paint, realista…) + referências (fotos de personagens/lugares);
  2. 🤖 plano: a IA cria os personagens (aparência pro desenho), os locais, os itens e a lista de cenas;
  3. 🤖 cenas: cada cena vira "momentos" (fala / narração / ação / destaque) com quem está em cena, onde, em que pose,
     a câmera; dá pra editar tudo;
  4. 🧍 personagens: um projeto 🧍 (motor Flow) por personagem com SÓ as poses que o roteiro usa (+ quadros B e bocas);
  5. 🏞 locais e itens no 🚀 Flow em massa (ou suas imagens);
  6. 🎙 vozes: cada personagem com uma voz do site (🎭 Vozes / multi voice) + narrador → as durações viram a linha do tempo;
  7. 👁 prévia e 🎬 editor.
Fica em anime2d/<id>/ (projeto.json, refs/, imagens/, vozes/). Env ANIME2D_DIR muda a pasta.
"""
from __future__ import annotations

import json
import math
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import react_personagens as R

_BASE = os.path.dirname(os.path.abspath(__file__))
_TRAVA = threading.RLock()
RE_ID = re.compile(r"^an[0-9a-f]{10}$")


class AnimeErro(Exception):
    pass


# ------------------------------------------------------------------ catálogos
ESTILOS = {
    "anime": ("🎌 Anime", "2D anime TV-series style, clean line art, flat cel shading, vibrant colors"),
    "cartoon": ("🖍 Cartoon simples (tipo Shin-chan)", "simple 2D cartoon style like Crayon Shin-chan: very simple shapes, thick wobbly outlines, "
                "flat bright colors, minimal shading, cute simplified proportions"),
    "chibi": ("🍡 Chibi", "cute chibi 2D style, big heads, small bodies, pastel colors, clean outlines"),
    "oleo": ("🖼 Pintura a óleo", "classical oil painting, visible brush strokes, rich textured colors, dramatic light"),
    "aquarela": ("💧 Aquarela", "soft watercolor illustration, paper texture, gentle washes of color, light ink lines"),
    "paint": ("✏ Desenho no Paint", "deliberately crude MS Paint drawing, wobbly mouse lines, flat bucket-fill colors, funny low-effort meme look"),
    "manga_pb": ("📖 Mangá P&B", "black and white manga style, screentones, ink lines, high contrast"),
    "manga_tinta": ("🖋 Mangá em tinta P&B (tipo o anime Uzumaki)", "monochrome black-and-white anime that looks like a moving horror manga: "
                    "NO color at all, only black, white and soft gray gradients; detailed pen ink linework with fine "
                    "cross-hatching and hatched shadows, smooth painterly gray shading and soft diffuse light, realistic "
                    "proportions, intense wide-eyed expressive faces, very detailed hand-drawn backgrounds, subtle film "
                    "grain, eerie unsettling atmosphere"),
    "pixel": ("👾 Pixel art", "16-bit pixel art, limited palette, crisp pixels"),
    "realista": ("📷 Realista", "photorealistic, cinematic photo, natural light"),
    "3d_tosco": ("🧊 3D tosco (PS1)", "low-poly PS1-era 3D render, blurry textures, awkward stiff look"),
}
# poses do catálogo (os personagens ficam virados pra DIREITA, de 3/4; olhar pra esquerda = espelhar)
POSES: Dict[str, Tuple[str, str]] = {
    "neutro": ("😐 em pé, neutro", "standing, relaxed neutral expression, arms down"),
    "feliz": ("😄 feliz", "standing, big happy smile"),
    "rindo": ("🤣 rindo", "laughing hard, eyes closed, hand on belly"),
    "bravo": ("😠 bravo", "angry, furrowed brows, clenched fists, leaning forward"),
    "triste": ("😢 triste", "sad, teary eyes, shoulders down"),
    "chocado": ("😱 chocado", "shocked, eyes wide open, jaw dropped, hands up"),
    "assustado": ("😨 assustado", "scared, trembling, sweat drops, hands near the face"),
    "pensativo": ("🤔 pensativo", "thinking, hand on chin, one eyebrow raised"),
    "envergonhado": ("😳 envergonhado", "embarrassed, blushing, scratching the back of the head"),
    "convencido": ("😏 convencido", "smug smirk, arms crossed, chin up"),
    "apontando": ("👉 apontando", "pointing forward with one arm, determined"),
    "acenando": ("👋 acenando", "waving one hand, friendly smile"),
    "andando": ("🚶 andando", "walking, mid-stride"),
    "correndo": ("🏃 correndo", "running fast, leaning forward, motion"),
    "pulando": ("🤸 pulando", "jumping in the air with joy, arms up"),
    "sentado": ("🪑 sentado", "sitting on an invisible seat, relaxed"),
    "deitado": ("🛌 deitado", "lying down on the side, relaxed"),
    "costas": ("🔙 de costas", "seen from behind, standing"),
    "comendo": ("🍙 comendo", "eating with chopsticks / a snack, cheeks full"),
    "dormindo": ("😴 dormindo", "sleeping standing up, eyes closed, snot bubble"),
}
# poses que ganham um 2º quadro (B) — alternam pra parecer movimento
QUADRO_B = {
    "andando": "walking, the OTHER leg forward (next step of the same walk cycle)",
    "correndo": "running, the OTHER leg forward (next frame of the same run cycle)",
    "acenando": "waving, the hand on the other side of the wave",
    "rindo": "laughing, body bent slightly more, the next frame of the laugh",
    "pulando": "landing from the jump, knees bent",
    "comendo": "chewing, mouth closed, cheeks full",
    "bravo": "angry, stomping one foot, steam from the head",
    "assustado": "scared, jumping back slightly, the next frame",
}
POSICOES = {"esquerda": 0.16, "centro_esq": 0.33, "centro": 0.5, "centro_dir": 0.67, "direita": 0.84}
CAMERAS = {"fixa": "static", "zoom_in": "in", "zoom_out": "out", "pan_esq": "pan_left", "pan_dir": "pan_right",
           "tremida": "rapido"}
# 🌄 parallax: com a câmera andando, cada camada anda numa velocidade — o fundo (longe) devagar, personagens e objetos
# (meio) um pouco mais, a camada da frente (perto) bem mais. Frações da largura/altura do vídeo na cena inteira.
# O fundo no pan do editor anda ~0,15 da largura; no zoom ele cresce 1→1,4 (as camadas abrem do centro / a frente desce).
PARALAXE = {"personagem": 0.20, "objeto": 0.20, "frente": 0.32}
PARALAXE_ZOOM = {"personagem": 0.10, "objeto": 0.10, "frente": 0.16}  # quanto abrem pros lados (x) no zoom
PARALAXE_ZOOM_Y = {"personagem": 0.03, "objeto": 0.03, "frente": 0.12}  # quanto descem (zoom in) / sobem (zoom out)
TREMOR = {"personagem": 0.006, "objeto": 0.006, "frente": 0.014}  # câmera tremida: a frente treme mais
TIPOS_MOMENTO = ("fala", "narracao", "acao", "destaque")
PROPORCOES = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
CORES = ["#ffd54a", "#4fc3ff", "#ff5c5c", "#7cff8a", "#ff8ad8", "#c49bff", "#ffa64d", "#5effe0"]


EXEMPLO_INSTRUCOES = """HISTÓRIA / PREMISSA: Um garoto de 5 anos, Kenta, tenta esconder da mãe que quebrou o vaso favorito dela antes que ela volte do mercado. O cachorro dele, Bolinha, só atrapalha.

PERSONAGENS:
- Kenta (5 anos): sapeca, mente mal, faz caretas quando está nervoso; fala rápido e inventa desculpas absurdas. Cabelo preto espetado, camiseta vermelha, short azul.
- Mãe (Yumi, 35): carinhosa mas assustadora quando brava; fala "KENTAAA!". Avental verde, cabelo castanho preso.
- Bolinha: cachorro branco gordinho, late nas horas erradas.
- Narrador: tom de documentário sério, como se fosse um drama épico (contraste com a besteira da situação).

LOCAIS: a sala da casa (sofá, vaso quebrado no chão, janela), a porta de entrada, o quintal.

ESTILO E TOM: cartoon simples tipo Shin-chan; humor de situação e caretas; nada de violência; final com reviravolta (a mãe também quebrou algo).

DURAÇÃO: ~3 minutos (ou deixe automático).

EXTRAS: um destaque em tela cheia do rosto da mãe gigante e assustador quando ela abre a porta; o vaso aparece como objeto em cena."""


# ------------------------------------------------------------------ guardar
def pasta_raiz(base: str = _BASE) -> str:
    return os.environ.get("ANIME2D_DIR") or os.path.join(base, "anime2d")


def pasta(pid: str, base: str = _BASE) -> str:
    if not RE_ID.match(str(pid or "")):
        raise AnimeErro("Projeto inválido.")
    return os.path.join(pasta_raiz(base), pid)


def _completar(p: Dict[str, Any]) -> Dict[str, Any]:
    p.setdefault("titulo", "Animação sem título")
    p.setdefault("premissa", "")
    p.setdefault("estilo", "anime")
    p.setdefault("estilo_extra", "")
    p.setdefault("proporcao", "16:9")
    p.setdefault("duracao_alvo", 0.0)  # 0 = a IA escolhe pela história
    p.setdefault("idioma", "português do Brasil")
    p.setdefault("narrador", {"ativo": True, "voz": ""})
    p.setdefault("legendas", True)
    p.setdefault("paralaxe", True)
    p.setdefault("audio", {})  # 🎧 modo áudio: {"arquivo", "dur", "transcricao": [{ini, fim, texto}]}
    p.setdefault("referencias", [])
    p.setdefault("personagens", [])
    p.setdefault("locais", [])
    p.setdefault("itens", [])
    p.setdefault("plano", {})
    p.setdefault("cenas", [])
    p.setdefault("editor", {})
    p.setdefault("manga", {})  # 📖 {"paginas": [arquivos em manga/], "adaptacao": {...}}
    p.setdefault("log", [])
    return p


def log(p: Dict[str, Any], msg: str) -> None:
    p.setdefault("log", []).append(f"{time.strftime('%d/%m %H:%M:%S')} {msg}")
    p["log"] = p["log"][-120:]


def carregar(pid: str, base: str = _BASE) -> Dict[str, Any]:
    try:
        with open(os.path.join(pasta(pid, base), "projeto.json"), encoding="utf-8") as f:
            return _completar(json.load(f))
    except (OSError, ValueError):
        raise AnimeErro("Projeto não encontrado.")


def salvar(p: Dict[str, Any], base: str = _BASE) -> None:
    d = pasta(p["id"], base)
    os.makedirs(d, exist_ok=True)
    p["atualizado"] = time.time()
    tmp = os.path.join(d, f"projeto.json.{secrets.token_hex(3)}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(d, "projeto.json"))


def criar(titulo: str, premissa: str = "", estilo: str = "anime", base: str = _BASE, **extra: Any) -> Dict[str, Any]:
    pid = "an" + secrets.token_hex(5)
    for sub in ("refs", "imagens", "vozes"):
        os.makedirs(os.path.join(pasta(pid, base), sub), exist_ok=True)
    p = _completar({"id": pid, "titulo": (titulo or "").strip()[:200] or "Animação sem título",
                    "premissa": str(premissa or "").strip()[:6000], "estilo": estilo if estilo in ESTILOS else "anime",
                    "criado": time.time()})
    for k in ("proporcao", "idioma"):
        if extra.get(k):
            p[k] = extra[k]
    if extra.get("duracao_alvo") not in (None, ""):
        v = float(extra["duracao_alvo"])
        p["duracao_alvo"] = 0.0 if v <= 0 else max(0.5, min(40.0, v))
    log(p, "projeto criado")
    salvar(p, base)
    return p


def listar(base: str = _BASE) -> List[Dict[str, Any]]:
    raiz = pasta_raiz(base)
    out = []
    for n in os.listdir(raiz) if os.path.isdir(raiz) else []:
        if not RE_ID.match(n):
            continue
        try:
            p = carregar(n, base)
        except AnimeErro:
            continue
        out.append({"id": n, "titulo": p["titulo"], "estilo": ESTILOS.get(p["estilo"], ("?",))[0],
                    "personagens": len(p["personagens"]), "cenas": len(p["cenas"]),
                    "momentos": sum(len(c.get("momentos") or []) for c in p["cenas"]),
                    "job": (p.get("editor") or {}).get("job_id"), "atualizado": p.get("atualizado", 0)})
    return sorted(out, key=lambda x: -x["atualizado"])


def excluir(pid: str, base: str = _BASE) -> None:
    shutil.rmtree(pasta(pid, base), ignore_errors=True)


def tamanho(p: Dict[str, Any]) -> Tuple[int, int]:
    return PROPORCOES.get(p.get("proporcao") or "16:9", PROPORCOES["16:9"])


def estilo_en(p: Dict[str, Any]) -> str:
    e = ESTILOS.get(p.get("estilo") or "anime", ESTILOS["anime"])[1]
    return e + (f", {p['estilo_extra']}" if p.get("estilo_extra") else "")


def _id(prefixo: str) -> str:
    return prefixo + secrets.token_hex(3)


def achar(lista: List[Dict[str, Any]], nome_ou_id: Any) -> Optional[Dict[str, Any]]:
    n = R._norm(nome_ou_id)
    if not n:
        return None
    return (next((x for x in lista if x["id"] == nome_ou_id), None)
            or next((x for x in lista if R._norm(x["nome"]) == n), None)
            or next((x for x in lista if n in R._norm(x["nome"]) or R._norm(x["nome"]) in n), None))


# ------------------------------------------------------------------ 📎 referências (personagens, locais, estilo, itens)
TIPOS_REF = {"personagem": "🧑 personagem", "local": "🏞 local", "item": "📦 item", "estilo": "🎨 estilo (o jeito de desenhar)"}


def guardar_referencia(p: Dict[str, Any], nome_arq: str, dados: bytes, tipo: str, nome: str = "", nota: str = "",
                       base: str = _BASE) -> Dict[str, Any]:
    from PIL import Image
    import io
    try:
        im = Image.open(io.BytesIO(dados))
        im.load()
    except Exception:  # noqa: BLE001
        raise AnimeErro("Não consegui abrir essa imagem.")
    arq = f"ref_{secrets.token_hex(4)}.png"
    im.convert("RGBA").save(os.path.join(pasta(p["id"], base), "refs", arq))
    r = {"id": _id("r"), "arquivo": arq, "tipo": tipo if tipo in TIPOS_REF else "personagem",
         "nome": " ".join(str(nome or "").split())[:80], "nota": " ".join(str(nota or "").split())[:300]}
    p["referencias"].append(r)
    vincular_referencias(p)
    return r


def vincular_referencias(p: Dict[str, Any]) -> None:
    """A referência com o nome de um personagem/local/item vai pra ficha dele."""
    for r in p["referencias"]:
        lista = {"personagem": p["personagens"], "local": p["locais"], "item": p["itens"]}.get(r["tipo"])
        if lista is None or not r.get("nome"):
            continue
        x = achar(lista, r["nome"])
        if x is not None and r["arquivo"] not in (x.setdefault("refs", [])):
            x["refs"].append(r["arquivo"])


def refs_de(p: Dict[str, Any], x: Dict[str, Any], base: str = _BASE) -> List[str]:
    return [os.path.join(pasta(p["id"], base), "refs", a) for a in x.get("refs") or []
            if os.path.isfile(os.path.join(pasta(p["id"], base), "refs", a))]


def refs_estilo(p: Dict[str, Any], base: str = _BASE) -> List[str]:
    return [os.path.join(pasta(p["id"], base), "refs", r["arquivo"]) for r in p["referencias"]
            if r["tipo"] == "estilo" and os.path.isfile(os.path.join(pasta(p["id"], base), "refs", r["arquivo"]))]


# ------------------------------------------------------------------ 🤖 1 · o plano (personagens, locais, itens, cenas)
def _ia():
    import ia_servico
    return ia_servico


def ia_ligada() -> bool:
    try:
        return _ia().ativo("anime2d")
    except Exception:  # noqa: BLE001
        return False


SCHEMA_PLANO = {
    "type": "object", "additionalProperties": False,
    "required": ["titulo", "sinopse", "duracao_min", "personagens", "locais", "itens", "cenas"],
    "properties": {
        "titulo": {"type": "string"}, "sinopse": {"type": "string"}, "duracao_min": {"type": "number"},
        "personagens": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["nome", "descricao", "personalidade", "jeito_de_falar", "aparencia_en", "genero", "idade"],
            "properties": {"nome": {"type": "string"}, "descricao": {"type": "string"}, "personalidade": {"type": "string"},
                           "jeito_de_falar": {"type": "string"}, "aparencia_en": {"type": "string"},
                           "genero": {"type": "string", "enum": ["masculino", "feminino", "neutro"]},
                           "idade": {"type": "string", "enum": ["crianca", "jovem", "adulto", "idoso"]}}}},
        "locais": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["nome", "descricao", "prompt_en", "frente_en"],
            "properties": {"nome": {"type": "string"}, "descricao": {"type": "string"}, "prompt_en": {"type": "string"},
                           "frente_en": {"type": "string"}}}},
        "itens": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["nome", "tipo", "prompt_en"],
            "properties": {"nome": {"type": "string"}, "tipo": {"type": "string", "enum": ["objeto", "destaque"]},
                           "prompt_en": {"type": "string"}}}},
        "cenas": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["titulo", "local", "resumo", "personagens", "inicio_audio"],
            "properties": {"titulo": {"type": "string"}, "local": {"type": "string"}, "resumo": {"type": "string"},
                           "inicio_audio": {"type": "number"},
                           "personagens": {"type": "array", "items": {"type": "string"}}}}},
    },
}


def sys_plano(p: Dict[str, Any]) -> str:
    return (
        "Você é roteirista e diretor de arte de DESENHO ANIMADO 2D feito do jeito simples (como Crayon Shin-chan): o "
        "episódio é montado com IMAGENS — o fundo de cada lugar, os personagens em poses recortadas (com 2 quadros que se "
        "alternam pra dar movimento e a boca que abre quando falam), objetos na frente e imagens de destaque em tela cheia "
        "— mais câmera (zoom/pan). NÃO é vídeo gerado por IA: pense em cenas que funcionam com poucas poses, com humor de "
        "timing, reação e diálogo.\n"
        + (f"Agora faça o PLANO do episódio (duração alvo: ~{float(p['duracao_alvo']):.0f} min):\n" if float(p.get("duracao_alvo") or 0) > 0 else
           "Agora faça o PLANO do episódio. A DURAÇÃO é você que decide pelo tamanho da história (uma esquete curta: 1–3 min; "
           "uma história com várias situações: 5–10 min; uma aventura completa: 15+ min) — diga em 'duracao_min' e "
           "planeje as cenas pra isso (umas 30–60 s por cena).\n") +
        "- personagens: os que a história precisa (normalmente 2 a 6). 'descricao' (quem é, 1 frase), personalidade, "
        "jeito_de_falar (bordões), 'aparencia_en' EM INGLÊS: aparência concreta pra desenhar (corpo, cabelo, olhos, roupa "
        "marcante, cores, acessórios) — sempre a mesma em todas as imagens; genero e idade (pra escolher a voz).\n"
        "- locais: os lugares onde as cenas acontecem (poucos — repita lugares). 'prompt_en': o FUNDO em inglês, VAZIO de "
        "pessoas, visto de frente na altura dos olhos, com o chão na parte de baixo (onde os personagens vão ficar em pé); "
        "'frente_en': um objeto de PRIMEIRO PLANO opcional que fica na frente dos personagens (balcão, arbusto, mesa) — "
        "\"\" se não tiver.\n"
        "- itens: 'objeto' = coisa que aparece na cena (recortada, ex.: um bolo, uma placa); 'destaque' = imagem em tela "
        "cheia pra um momento forte (close de reação exagerada, plano detalhe, cena de impacto, flashback). 'prompt_en' em inglês.\n"
        "- cenas: em ordem, cada uma com o local (nome exato da lista), um resumo do que acontece e quem está nela.\n"
        "- Se vierem REFERÊNCIAS (personagens/locais com foto), use os nomes delas e descreva a aparência de acordo.\n"
        "- 🎧 Se vier um ÁUDIO (a transcrição com tempos): a história É o áudio — descubra os personagens pelas falas "
        "(quem fala com quem, os nomes citados, vozes descritas nas instruções), divida em cenas e marque em cada uma "
        "'inicio_audio' (o segundo do áudio em que a cena começa, a 1ª em 0); a duração é a do áudio. Sem áudio: "
        "'inicio_audio' = 0.\n"
        f"- Escreva em {p.get('idioma') or 'português do Brasil'} (menos os campos _en)."
    )


def prompt_plano(p: Dict[str, Any]) -> str:
    L = [f"TÍTULO: {p.get('titulo') or ''}", f"PREMISSA:\n{p.get('premissa') or '(sem premissa)'}",
         f"ESTILO VISUAL: {ESTILOS.get(p['estilo'], ESTILOS['anime'])[0]} — {estilo_en(p)}",
         f"FORMATO: {p.get('proporcao')}", f"NARRADOR: {'sim, quando a história precisar' if (p.get('narrador') or {}).get('ativo') else 'não'}"]
    au = p.get("audio") or {}
    if au.get("transcricao"):
        L.append(f"\n🎧 ÁUDIO ENVIADO ({R.mmss(au.get('dur'))}) — TRANSCRIÇÃO (segundo · texto):")
        L += [f"- {x['ini']:.1f} · {x['texto']}" for x in au["transcricao"]][:900]
    refs = [r for r in p["referencias"] if r.get("nome") or r.get("nota")]
    if refs:
        L.append("REFERÊNCIAS ENVIADAS (com foto): " + "; ".join(f"{TIPOS_REF[r['tipo']]} {r.get('nome') or ''} {('— ' + r['nota']) if r.get('nota') else ''}" for r in refs))
    ja = [c["nome"] for c in p["personagens"]]
    if ja:
        L.append("PERSONAGENS QUE JÁ EXISTEM (mantenha, pode completar): " + ", ".join(ja))
    return "\n".join(L)


def aplicar_plano(p: Dict[str, Any], r: Any) -> Dict[str, Any]:
    if not isinstance(r, dict) or not isinstance(r.get("cenas"), list):
        raise AnimeErro("A resposta precisa ter \"personagens\", \"locais\", \"itens\" e \"cenas\".")
    for i, x in enumerate(r.get("personagens") or []):
        if not isinstance(x, dict) or not str(x.get("nome") or "").strip():
            continue
        c = achar(p["personagens"], x["nome"])
        if c is None:
            c = {"id": _id("c"), "nome": " ".join(str(x["nome"]).split())[:60], "refs": [], "voz": "", "pod": {},
                 "cor": CORES[len(p["personagens"]) % len(CORES)]}
            p["personagens"].append(c)
        for k in ("descricao", "personalidade", "jeito_de_falar", "aparencia_en"):
            if x.get(k) and not str(c.get(k) or "").strip():
                c[k] = " ".join(str(x[k]).split())[:800]
        for k in ("genero", "idade"):
            if x.get(k):
                c[k] = x[k]
    for x in r.get("locais") or []:
        if not isinstance(x, dict) or not str(x.get("nome") or "").strip():
            continue
        lo = achar(p["locais"], x["nome"])
        if lo is None:
            lo = {"id": _id("l"), "nome": " ".join(str(x["nome"]).split())[:60], "refs": [], "img": {}, "frente": {}}
            p["locais"].append(lo)
        for k in ("descricao", "prompt_en", "frente_en"):
            if x.get(k) is not None and not str(lo.get(k) or "").strip():
                lo[k] = " ".join(str(x[k]).split())[:900]
    for x in r.get("itens") or []:
        if not isinstance(x, dict) or not str(x.get("nome") or "").strip():
            continue
        it = achar(p["itens"], x["nome"])
        if it is None:
            it = {"id": _id("i"), "nome": " ".join(str(x["nome"]).split())[:60], "refs": [], "img": {}}
            p["itens"].append(it)
        it["tipo"] = x.get("tipo") if x.get("tipo") in ("objeto", "destaque") else it.get("tipo") or "objeto"
        if x.get("prompt_en") and not it.get("prompt_en"):
            it["prompt_en"] = " ".join(str(x["prompt_en"]).split())[:900]
    cenas = []
    for x in r.get("cenas") or []:
        if not isinstance(x, dict):
            continue
        lo = achar(p["locais"], x.get("local"))
        ia_ = R.segundos(x.get("inicio_audio")) if (p.get("audio") or {}).get("arquivo") else None
        cenas.append({"id": _id("s"), "titulo": " ".join(str(x.get("titulo") or "").split())[:120], "audio_ini": ia_,
                      "local": lo["id"] if lo else (p["locais"][0]["id"] if p["locais"] else ""),
                      "resumo": " ".join(str(x.get("resumo") or "").split())[:1200],
                      "personagens": [c["id"] for c in (achar(p["personagens"], n) for n in x.get("personagens") or []) if c],
                      "camera": "fixa", "momentos": []})
    if not cenas:
        raise AnimeErro("A IA não mandou nenhuma cena.")
    p["cenas"] = cenas
    if (p.get("audio") or {}).get("arquivo") and cenas:
        cenas[0]["audio_ini"] = 0.0
        if any(c.get("audio_ini") is None for c in cenas):
            for c in cenas:
                c["audio_ini"] = None
    p["plano"] = {"titulo": str(r.get("titulo") or "")[:200], "sinopse": str(r.get("sinopse") or "")[:2000], "quando": time.time(),
                  "duracao_min": max(0.5, min(60.0, float(R.segundos(r.get("duracao_min")) or 0) or float(p.get("duracao_alvo") or 3)))}
    vincular_referencias(p)
    log(p, f"🤖 plano: {len(p['personagens'])} personagem(ns), {len(p['locais'])} local(is), {len(p['itens'])} item(ns), {len(cenas)} cena(s)")
    return p["plano"]


def planejar(pid: str, base: str = _BASE) -> Dict[str, Any]:
    p = carregar(pid, base)
    if not str(p.get("premissa") or "").strip():
        raise AnimeErro("Escreva a premissa antes.")
    conteudo: List[Dict[str, Any]] = [{"type": "text", "text": prompt_plano(p)}]
    conteudo += _blocos_refs(p, base)
    r = _ia().chamar("anime2d", sys_plano(p), conteudo, schema=SCHEMA_PLANO, max_tokens=6000, effort="medium",
                     timeout=240, cache_local=False)
    if r is None:
        raise AnimeErro("A IA não respondeu (desligada, sem crédito ou erro) — copie o prompt e cole a resposta de outra IA.")
    with _TRAVA:
        p = carregar(pid, base)
        aplicar_plano(p, r)
        salvar(p, base)
    return p["plano"]


def _blocos_refs(p: Dict[str, Any], base: str, maximo: int = 6) -> List[Dict[str, Any]]:
    """As fotos de referência (pequenas) pra IA ver."""
    import base64
    import io
    from PIL import Image
    out = []
    for r in p["referencias"][:maximo]:
        cam = os.path.join(pasta(p["id"], base), "refs", r["arquivo"])
        try:
            im = Image.open(cam).convert("RGB")
            im.thumbnail((512, 512))
            b = io.BytesIO()
            im.save(b, "JPEG", quality=80)
        except Exception:  # noqa: BLE001
            continue
        out.append({"type": "text", "text": f"Referência — {TIPOS_REF[r['tipo']]}: {r.get('nome') or '(sem nome)'} {r.get('nota') or ''}"})
        out.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b.getvalue()).decode()}})
    return out


# ------------------------------------------------------------------ 🤖 2 · as cenas (os momentos)
def _schema_cena() -> Dict[str, Any]:
    poses = list(POSES) + ["outra"]
    return {
        "type": "object", "additionalProperties": False, "required": ["momentos"],
        "properties": {"momentos": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["tipo", "quem", "texto", "pose", "pose_en", "em_cena", "camera", "destaque", "objeto", "duracao", "tempo", "som"],
            "properties": {
                "tipo": {"type": "string", "enum": list(TIPOS_MOMENTO)}, "quem": {"type": "string"},
                "texto": {"type": "string"}, "pose": {"type": "string", "enum": poses}, "pose_en": {"type": "string"},
                "em_cena": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                       "required": ["personagem", "posicao", "pose", "olha"],
                                                       "properties": {"personagem": {"type": "string"},
                                                                      "posicao": {"type": "string", "enum": list(POSICOES)},
                                                                      "pose": {"type": "string", "enum": poses},
                                                                      "olha": {"type": "string", "enum": ["direita", "esquerda"]}}}},
                "camera": {"type": "string", "enum": list(CAMERAS)}, "destaque": {"type": "string"},
                "objeto": {"type": "string"}, "duracao": {"type": "number"}, "tempo": {"type": "number"},
                "som": {"type": "string"}}}}},
    }


def sys_cena(p: Dict[str, Any]) -> str:
    return (
        "Você escreve UMA CENA de um desenho animado 2D montado com imagens (estilo Crayon Shin-chan — poses recortadas "
        "sobre o fundo, quadros A/B que alternam, boca que abre quando fala, câmera simples). A cena vira uma lista de "
        "MOMENTOS, em ordem:\n"
        "- tipo 'fala' (um personagem fala — 'quem' = o nome EXATO dele, 'texto' = só o que ele diz, curto: até ~25 "
        "palavras), 'narracao' (o narrador conta — 'quem' = \"Narrador\"; use só quando a história precisa), 'acao' (algo "
        "acontece sem fala: alguém entra correndo, cai, sai; 'texto' = descrição curta pro editor, 'duracao' em segundos "
        "1–4) e 'destaque' (uma imagem de destaque em TELA CHEIA por uns segundos — close de reação exagerada, plano "
        "detalhe, flashback; 'destaque' = o NOME do item 'destaque' da lista; 'duracao' 1.5–4).\n"
        "- 'em_cena' = TODOS que estão visíveis nesse momento, cada um com 'posicao' (esquerda, centro_esq, centro, "
        "centro_dir, direita — não ponha dois no mesmo lugar), 'pose' e pra onde 'olha' (normalmente pra quem fala). "
        "Quem entra/sai de cena: inclua/tire da lista. 'pose' do momento = a pose de quem fala/age.\n"
        f"- 'pose': use o catálogo ({', '.join(POSES)}); poses de movimento (andando, correndo, acenando, rindo, pulando, "
        "comendo, bravo, assustado) já têm 2 quadros. Use 'outra' + 'pose_en' (em inglês, curta) SÓ se precisar de uma "
        "pose específica que não está no catálogo. Varie as poses conforme a emoção — é o que dá vida.\n"
        "- 'camera': fixa, zoom_in (tensão/revelação), zoom_out, pan_esq, pan_dir, tremida (susto/impacto).\n"
        "- 'objeto': o nome de um item 'objeto' que aparece em cena nesse momento (\"\" se nenhum).\n"
        "- Humor de timing: reações, silêncio constrangedor (acao com duracao), quebra de expectativa com destaque.\n"
        "- 'som': o efeito sonoro do momento, curto, em português (ex.: \"porta rangendo\", \"soco\", \"mastigando\") ou \"\" "
        "— por enquanto só anotado (a busca de efeitos vem depois).\n"
        "- 📖 Se vierem PÁGINAS DE MANGÁ: adapte ESSAS páginas, na ordem de leitura do mangá (quadros da DIREITA pra "
        "esquerda, de cima pra baixo; balões na mesma ordem). Cada balão = uma 'fala' de quem fala (texto do balão, sem "
        "inventar); caixas de texto/narração = 'narracao'; quadro sem fala = 'acao' ou 'destaque'; onomatopeias "
        "(SFX desenhados) = 'som'. Um close dramático/impacto do quadro = 'camera' zoom_in/tremida. Mantenha o ritmo do mangá.\n"
        + ("- 🎧 MODO ÁUDIO: o episódio segue um ÁUDIO pronto (a transcrição com os tempos vem abaixo). Cada fala/narração "
           "do áudio vira UM momento com o 'texto' IGUAL ao trecho da transcrição e 'tempo' = o segundo em que começa no "
           "áudio; descubra QUEM fala cada trecho (pela voz descrita, pelo contexto e pelos nomes). Ações e destaques "
           "também ganham 'tempo' (entre as falas). 'duracao': 0. Não invente falas que não estão no áudio.\n"
           if (p.get("audio") or {}).get("arquivo") else
           "- 'duracao' nas falas/narração: 0 (a voz decide). 'tempo': 0.\n")
        + f"- Falas em {p.get('idioma') or 'português do Brasil'}."
    )


def prompt_cena(p: Dict[str, Any], k: int) -> str:
    if not 0 <= k < len(p["cenas"]):
        raise AnimeErro("Cena inexistente.")
    s = p["cenas"][k]
    lo = next((x for x in p["locais"] if x["id"] == s.get("local")), None)
    L = [f"EPISÓDIO: {p['titulo']}", f"PREMISSA: {p.get('premissa') or ''}"]
    if (p.get("plano") or {}).get("sinopse"):
        L.append(f"SINOPSE: {p['plano']['sinopse']}")
    alvo = duracao_planejada(p)
    L.append(f"DURAÇÃO DO EPISÓDIO: ~{alvo:.0f} min, em {len(p['cenas'])} cena(s) — "
             f"esta cena deve ter uns {max(4, int(alvo * 60 / max(1, len(p['cenas'])) / 4.5))} momentos.")
    L.append("PERSONAGENS:")
    for c in p["personagens"]:
        L.append(f"- {c['nome']}: {c.get('descricao') or ''} | personalidade: {c.get('personalidade') or ''} | fala: {c.get('jeito_de_falar') or ''}"
                 + (" | poses já desenhadas (use pose \"outra\" com pose_en EXATAMENTE assim): " + "; ".join(c["poses_zip"]) if c.get("poses_zip") else ""))
    if (p.get("narrador") or {}).get("ativo"):
        L.append("- Narrador (voz que conta a história; use com moderação)")
    L.append("ITENS: " + ("; ".join(f"{i['nome']} ({i.get('tipo')})" for i in p["itens"]) or "(nenhum)"))
    L += ["", f"## CENA {k + 1} DE {len(p['cenas'])}: {s['titulo']}", f"Local: {lo['nome'] if lo else '?'} — {(lo or {}).get('descricao') or ''}",
          f"O que acontece: {s.get('resumo') or ''}",
          "Quem está: " + ", ".join(c["nome"] for c in p["personagens"] if c["id"] in s.get("personagens", []))]
    if k > 0:
        ant = p["cenas"][k - 1]
        falas = [m for m in ant.get("momentos") or [] if m.get("texto")][-6:]
        if falas:
            L += ["", "FIM DA CENA ANTERIOR (continue dali, não repita):"]
            L += [f"- {nome_de(p, m.get('quem'))}: {m['texto']}" for m in falas]
    if k + 1 < len(p["cenas"]):
        L.append(f"\nA PRÓXIMA CENA: {p['cenas'][k + 1]['titulo']} — {p['cenas'][k + 1].get('resumo') or ''}")
    if s.get("paginas") and paginas_manga(p):
        L.append(f"\n📖 ESTA CENA ADAPTA AS PÁGINAS {', '.join(str(n) for n in s['paginas'])} DO MANGÁ (as imagens vêm anexadas, "
                 "nessa ordem) — adapte fielmente, balão por balão.")
        if s.get("nota_adaptacao"):
            L.append(f"Nota de adaptação: {s['nota_adaptacao']}")
    au = p.get("audio") or {}
    if au.get("transcricao"):
        a, b = janela_audio_cena(p, k)
        linhas = [x for x in au["transcricao"] if a - 0.5 <= x["ini"] < b]
        L += ["", f"🎧 ESTA CENA COBRE O ÁUDIO DE {R.mmss(a)} A {R.mmss(b)} — TRANSCRIÇÃO (segundo · texto):"]
        L += [f"- {x['ini']:.1f} · {x['texto']}" for x in linhas] or ["(sem fala nesse trecho)"]
    return "\n".join(L)


def janela_audio_cena(p: Dict[str, Any], k: int) -> Tuple[float, float]:
    """No modo áudio, o trecho do áudio de cada cena (o plano marca 'inicio' em cada cena; senão divide igual)."""
    au = p.get("audio") or {}
    dur = float(au.get("dur") or 0)
    n = max(1, len(p["cenas"]))
    inis = [R.segundos(s.get("audio_ini")) for s in p["cenas"]]
    if all(x is not None for x in inis):
        a = inis[k]
        b = inis[k + 1] if k + 1 < n else dur
        return float(a), float(max(a, b))
    return dur * k / n, dur * (k + 1) / n


def duracao_planejada(p: Dict[str, Any]) -> float:
    """Os minutos do episódio: o que você escolheu, ou o que a IA decidiu no plano (automático)."""
    return float(p.get("duracao_alvo") or 0) or float((p.get("plano") or {}).get("duracao_min") or 3)


def nome_de(p: Dict[str, Any], quem: Any) -> str:
    if quem == "narrador":
        return "Narrador"
    c = next((x for x in p["personagens"] if x["id"] == quem), None)
    return c["nome"] if c else str(quem or "")


def aplicar_cena(p: Dict[str, Any], k: int, r: Any) -> int:
    if isinstance(r, list):
        r = {"momentos": r}
    if not isinstance(r, dict) or not isinstance(r.get("momentos"), list):
        raise AnimeErro("A resposta precisa ter a lista \"momentos\".")
    s = p["cenas"][k]
    ms = []
    for x in r["momentos"]:
        m = limpar_momento(p, x)
        if m:
            ms.append(m)
    if not ms:
        raise AnimeErro("Nenhum momento aproveitável (confira os nomes).")
    s["momentos"] = ms
    s["quando"] = time.time()
    log(p, f"🎬 cena {k + 1} ({s['titulo']}): {len(ms)} momento(s)")
    return len(ms)


def limpar_momento(p: Dict[str, Any], x: Any) -> Optional[Dict[str, Any]]:
    """Um momento da IA/colado/editado → o formato do projeto (ids no lugar dos nomes)."""
    if not isinstance(x, dict):
        return None
    tipo = x.get("tipo") if x.get("tipo") in TIPOS_MOMENTO else "fala"
    quem_n = str(x.get("quem") or "").strip()
    if tipo == "narracao" or R._norm(quem_n) == "narrador":
        quem = "narrador"
        tipo = "narracao" if tipo in ("fala", "narracao") else tipo
    else:
        c = achar(p["personagens"], x.get("quem"))
        quem = c["id"] if c else ""
    texto = R.limpar_texto_fala(x.get("texto"), nome_de(p, quem))[:400] if tipo in ("fala", "narracao") else " ".join(str(x.get("texto") or "").split())[:300]
    if tipo == "fala" and (not quem or not texto):
        return None
    if tipo == "narracao" and not texto:
        return None
    pose = x.get("pose") if x.get("pose") in POSES or x.get("pose") == "outra" else "neutro"
    pose_en = " ".join(str(x.get("pose_en") or "").split())[:200]
    em = []
    usadas = set()
    for y in x.get("em_cena") or []:
        if not isinstance(y, dict):
            continue
        c = achar(p["personagens"], y.get("personagem") or y.get("cid"))
        if not c or c["id"] in [e["cid"] for e in em]:
            continue
        pos = y.get("posicao") if y.get("posicao") in POSICOES else next((q for q in POSICOES if q not in usadas), "centro")
        usadas.add(pos)
        po = y.get("pose") if y.get("pose") in POSES or y.get("pose") == "outra" else "neutro"
        em.append({"cid": c["id"], "posicao": pos, "pose": po, "pose_en": str(y.get("pose_en") or (pose_en if c["id"] == quem else ""))[:200],
                   "olha": "esquerda" if y.get("olha") == "esquerda" else "direita"})
    # quem fala/age está em cena com a pose do momento
    if quem not in ("", "narrador"):
        e = next((e for e in em if e["cid"] == quem), None)
        if e:
            if pose != "neutro" or e["pose"] == "neutro":
                e["pose"], e["pose_en"] = pose, pose_en or e.get("pose_en", "")
    dur = R.segundos(x.get("duracao")) or 0.0
    return {"id": str(x.get("id") or _id("m"))[:12], "tipo": tipo, "quem": quem, "texto": texto, "pose": pose, "pose_en": pose_en,
            "em_cena": em, "camera": x.get("camera") if x.get("camera") in CAMERAS else "fixa",
            "destaque": (achar([i for i in p["itens"] if i.get("tipo") == "destaque"], x.get("destaque")) or {}).get("id", ""),
            "objeto": (achar([i for i in p["itens"] if i.get("tipo") == "objeto"], x.get("objeto")) or {}).get("id", ""),
            "duracao": round(max(0.0, min(15.0, dur)), 2), "som": " ".join(str(x.get("som") or "").split())[:200],
            "tempo": (round(float(R.segundos(x.get("tempo"))), 2) if R.segundos(x.get("tempo")) is not None and (p.get("audio") or {}).get("arquivo") else None)}


def escrever_cenas(pid: str, base: str = _BASE, ks: Optional[List[int]] = None, so_vazias: bool = False,
                   on_log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    p = carregar(pid, base)
    if not p["cenas"]:
        raise AnimeErro("Faça o plano antes (as cenas vêm dele).")
    alvo = ks if ks is not None else [k for k, s in enumerate(p["cenas"]) if not so_vazias or not s.get("momentos")]
    feitas, erros = 0, []
    for n, k in enumerate(alvo, 1):
        on_log(f"cena {n} de {len(alvo)}…")
        p = carregar(pid, base)
        conteudo: Any = prompt_cena(p, k)
        pags = blocos_paginas(p, p["cenas"][k].get("paginas") or [], base)
        if pags:
            conteudo = [{"type": "text", "text": conteudo}] + pags
        r = _ia().chamar("anime2d", sys_cena(p), conteudo, schema=_schema_cena(), max_tokens=8000,
                         effort="medium", timeout=300, cache_local=False)
        if r is None:
            erros.append(str(k + 1))
            continue
        with _TRAVA:
            p = carregar(pid, base)
            try:
                aplicar_cena(p, k, r)
                feitas += 1
            except AnimeErro as exc:
                erros.append(f"{k + 1} ({exc})")
            salvar(p, base)
    if not feitas and erros:
        raise AnimeErro("A IA não respondeu — copie o prompt de cada cena e cole a resposta de outra IA.")
    return {"feitas": feitas, "erros": erros}


def prompt_copiar(p: Dict[str, Any], tipo: str, k: Optional[int] = None) -> str:
    if tipo == "plano":
        sis, txt, sch = sys_plano(p), prompt_plano(p), SCHEMA_PLANO
    else:
        sis, txt, sch = sys_cena(p), prompt_cena(p, int(k or 0)), _schema_cena()
    return sis + "\n\n" + txt + "\n\nResponda SÓ com um JSON neste formato (JSON Schema):\n" + json.dumps(sch, ensure_ascii=False)


# ------------------------------------------------------------------ 🧍 3 · personagens (as poses que o roteiro usa)
def poses_usadas(p: Dict[str, Any], cid: str) -> Dict[str, str]:
    """pose → prompt (em inglês) de tudo o que o roteiro pede pra esse personagem (+ neutro, a mestre)."""
    out: Dict[str, str] = {"neutro": POSES["neutro"][1]}
    for s in p["cenas"]:
        for m in s.get("momentos") or []:
            for e in m.get("em_cena") or []:
                if e["cid"] != cid:
                    continue
                if e["pose"] == "outra":
                    en = (e.get("pose_en") or "").strip()
                    if en:
                        out["x_" + R._slug(en)[:24]] = en
                elif e["pose"] in POSES:
                    out[e["pose"]] = POSES[e["pose"]][1]
    return out


def nome_pose(m_pose: str, pose_en: str = "") -> str:
    return "x_" + R._slug(pose_en)[:24] if m_pose == "outra" and pose_en else (m_pose if m_pose in POSES else "neutro")


# ------------------------------------------------------------------ 📖 mangá → anime: páginas e o 🎨 design aprovado
def paginas_manga(p: Dict[str, Any]) -> List[str]:
    return list(((p.get("manga") or {}).get("paginas")) or [])


def arquivo_pagina(p: Dict[str, Any], n: int, base: str = _BASE) -> Optional[str]:
    """A página n (1, 2, …) do mangá."""
    pg = paginas_manga(p)
    if not 1 <= int(n) <= len(pg):
        return None
    cam = os.path.join(pasta(p["id"], base), "manga", pg[int(n) - 1])
    return cam if os.path.isfile(cam) else None


def blocos_paginas(p: Dict[str, Any], ns: List[Any], base: str = _BASE, lado: int = 1400, maximo: int = 12) -> List[Dict[str, Any]]:
    """As páginas (em ordem) pra IA ler — JPEG até `lado` px."""
    import base64
    import io
    from PIL import Image
    out: List[Dict[str, Any]] = []
    for n in list(ns)[:maximo]:
        try:
            cam = arquivo_pagina(p, int(n), base)
        except (TypeError, ValueError):
            continue
        if not cam:
            continue
        im = Image.open(cam).convert("RGB")
        im.thumbnail((lado, lado))
        b = io.BytesIO()
        im.save(b, "JPEG", quality=82)
        out.append({"type": "text", "text": f"📖 Página {int(n)}"})
        out.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b.getvalue()).decode()}})
    return out


def precisa_aprovar(c: Dict[str, Any]) -> bool:
    """O personagem tem a etapa do 🎨 design anime (veio de uma adaptação de mangá) e ela ainda não foi aprovada."""
    d = c.get("design")
    return bool(d is not None and (c.get("design_en") or d.get("arquivo")) and not d.get("aprovado"))


def design_aprovado(p: Dict[str, Any], c: Dict[str, Any], base: str = _BASE) -> Optional[str]:
    d = c.get("design") or {}
    if not d.get("aprovado"):
        return None
    cam = os.path.join(pasta(p["id"], base), "imagens", d["aprovado"])
    return cam if os.path.isfile(cam) else None


def poses_json(p: Dict[str, Any], c: Dict[str, Any]) -> Dict[str, Any]:
    sl = R._slug(c["nome"])
    aparencia = c.get("aparencia_en") or f"the character {c['nome']}"
    trava = (f"CHARACTER LOCK: {c['nome']}. Appearance: {aparencia}. Keep exactly the same face, hairstyle, body, outfit and "
             "colors in every image.")
    estilo = "ART STYLE: " + estilo_en(p) + "."
    regras = ("Framing: FULL BODY from head to feet, the character seen in a 3/4 view turned to the RIGHT side of the image, "
              "whole figure inside the image with margin, feet at the bottom. ONE single figure, no props unless the pose "
              "needs it, no text, no panels, on a flat solid chroma-key green background (#00FF00), no shadow on the background.")
    poses = []
    for k, (nome, en) in enumerate(poses_usadas(p, c["id"]).items()):
        poses.append({"arquivo": f"{sl}_{nome}.png", "tipo": "pose", "prioridade": 1 if k < 5 else 2, "grupo": "anime2d",
                      "mestre": nome == "neutro", "descricao_pt": POSES[nome][0] if nome in POSES else en,
                      "prompt": f"{en}."})
        if nome in QUADRO_B:
            poses.append({"arquivo": f"{sl}_{nome}_b.png", "tipo": "pose", "prioridade": 2, "grupo": "anime2d",
                          "descricao_pt": (POSES[nome][0] if nome in POSES else en) + " — 2º quadro",
                          "prompt": f"{QUADRO_B[nome]}. Same character, same framing and size as the first frame.",
                          "pose_base": f"{sl}_{nome}.png"})
    refs = {os.path.basename(r): f"a reference picture of {c['nome']}" for r in c.get("refs") or []}
    return {"formato": "personagens_pod_v1", "personagem": sl, "nome": c["nome"], "anime2d": True,
            "descricoes_referencias": refs, "texto_fixo": {"trava": trava, "estilo": estilo, "regras": regras},
            "fundo": "verde", "canvas": [1200, 1800], "altura_personagem": 0.95, "corpo_inteiro": True, "boca_auto": True,
            "flow": {"proporcao": "3:4"}, "poses": poses}


def _pp():
    import personagens_pod as pp
    return pp


def criar_poses(pid: str, cid: str, base: str = _BASE) -> Dict[str, Any]:
    """Cria (ou atualiza) o projeto 🧍 do personagem com as poses do roteiro e manda pro Flow (a ⭐ neutra primeiro;
    quando ela fica pronta, `acompanhar` manda o resto e as bocas)."""
    pp = _pp()
    with _TRAVA:
        p = carregar(pid, base)
        c = next((x for x in p["personagens"] if x["id"] == cid), None)
        if not c:
            raise AnimeErro("Personagem não encontrado.")
        if precisa_aprovar(c):
            raise AnimeErro(f"Aprove o 🎨 design anime de {c['nome']} antes de gerar as poses.")
        dados = poses_json(p, c)
        refs = []
        dz = design_aprovado(p, c, base)
        if dz:  # o design aprovado é A referência (as fotos do mangá vêm depois)
            with open(dz, "rb") as f:
                refs.append(("design_anime_aprovado.png", f.read()))
            dados["descricoes_referencias"]["design_anime_aprovado.png"] = (
                f"the APPROVED anime character design of {c['nome']} — follow it exactly (face, hair, outfit, colors)")
        for cam in refs_de(p, c, base)[:2]:
            with open(cam, "rb") as f:
                refs.append((os.path.basename(cam), f.read()))
        if not (c.get("pod") or {}).get("pid"):
            reaproveitar_personagem(p, c, base)  # ♻ o mesmo personagem (mesmo estilo) de outro episódio
        pod = c.get("pod") or {}
        existe = None
        if pod.get("pid"):
            try:
                existe = pp.carregar(pod["pid"], base)
            except pp.PersErro:
                existe = None
        if existe is None:
            np_ = pp.criar(f"🎞 {c['nome']} ({p['titulo'][:30]})", json.dumps(dados, ensure_ascii=False), refs, base=base, motor="flow")
            c["pod"] = {"pid": np_["id"], "fase": "mestre", "criado": time.time()}
        else:
            novos = {x["arquivo"] for x in dados["poses"]}
            dados["poses"] += [x for x in existe["dados"].get("poses") or [] if x["arquivo"] not in novos]
            pp.trocar_json(pod["pid"], json.dumps(dados, ensure_ascii=False), base)
        ppid = c["pod"]["pid"]
        log(p, f"🧍 {c['nome']}: {len(dados['poses'])} pose(s) no Flow")
        salvar(p, base)
    proj = pp.carregar(ppid, base)
    mestre = next(x["arquivo"] for x in dados["poses"] if x.get("mestre"))
    if proj.get("mestre"):
        r = _mandar_resto(ppid, base)
        fase = "resto"
    else:
        it = proj["imagens"].get(mestre) or {}
        r = pp.enviar(ppid, [mestre], "", base) if it.get("estado") not in ("fila", "gerando") and not pp.arquivo_atual(proj, mestre, base) else {"ok": True}
        fase = "mestre"
    with _TRAVA:
        p = carregar(pid, base)
        next(x for x in p["personagens"] if x["id"] == cid)["pod"]["fase"] = fase
        salvar(p, base)
    return {"ok": True, "pod": ppid, "aviso": (r or {}).get("aviso") or ""}


def _outros(p: Dict[str, Any], base: str) -> List[Dict[str, Any]]:
    out = []
    raiz = pasta_raiz(base)
    for n in os.listdir(raiz) if os.path.isdir(raiz) else []:
        if n == p["id"] or not RE_ID.match(n):
            continue
        try:
            out.append(carregar(n, base))
        except AnimeErro:
            continue
    return out


def reaproveitar_personagem(p: Dict[str, Any], c: Dict[str, Any], base: str = _BASE) -> bool:
    """♻ O personagem já existe em outro episódio NO MESMO ESTILO: usa o mesmo projeto 🧍 (as poses prontas não são
    geradas de novo; só as poses novas que este roteiro pede)."""
    for q in _outros(p, base):
        if q.get("estilo") != p.get("estilo"):
            continue
        o = next((x for x in q["personagens"] if R._norm(x["nome"]) == R._norm(c["nome"]) and (x.get("pod") or {}).get("pid")), None)
        if o:
            c["pod"] = {"pid": o["pod"]["pid"], "fase": o["pod"].get("fase") or "mestre", "reaproveitado": q["titulo"]}
            for k in ("aparencia_en", "personalidade", "jeito_de_falar", "voz"):
                if o.get(k) and not c.get(k):
                    c[k] = o[k]
            log(p, f"♻ {c['nome']}: reaproveitado de “{q['titulo']}” (as poses prontas não são geradas de novo)")
            return True
    return False


def reaproveitar_imagens(pid: str, base: str = _BASE) -> int:
    """♻ Locais e itens sem imagem que já foram feitos em outro episódio (mesmo nome, mesmo estilo e formato) — copia."""
    with _TRAVA:
        p = carregar(pid, base)
        n = 0
        outros = [q for q in _outros(p, base) if q.get("estilo") == p.get("estilo") and q.get("proporcao") == p.get("proporcao")]
        for lista, campos in (("locais", ("img", "frente")), ("itens", ("img",))):
            for x in p[lista]:
                for campo in campos:
                    if arquivo_img(p, x.get(campo) or {}, base):
                        continue
                    for q in outros:
                        o = next((y for y in q[lista] if R._norm(y["nome"]) == R._norm(x["nome"])), None)
                        cam = arquivo_img(q, (o or {}).get(campo) or {}, base) if o else None
                        if cam:
                            arq = f"img_{secrets.token_hex(4)}.png"
                            shutil.copyfile(cam, os.path.join(pasta(pid, base), "imagens", arq))
                            x[campo] = {"arquivo": arq, "estado": "pronta", "origem": f"♻ {q['titulo']}", "versoes": [arq]}
                            n += 1
                            break
        if n:
            log(p, f"♻ {n} imagem(ns) reaproveitada(s) de outros episódios")
            salvar(p, base)
    return n


def _mandar_resto(ppid: str, base: str) -> Dict[str, Any]:
    pp = _pp()
    proj = pp.carregar(ppid, base)
    faltam = [x["arquivo"] for x in proj["dados"]["poses"] if x.get("tipo") == "pose"
              and (proj["imagens"].get(x["arquivo"]) or {}).get("estado") in ("nova", "erro", None)
              and not pp.arquivo_atual(proj, x["arquivo"], base)]
    if not faltam:
        # bocas só das poses de expressão (os 2ºs quadros de movimento não falam)
        so = [x["arquivo"] for x in proj["dados"]["poses"] if x.get("tipo") == "pose" and not x["arquivo"].endswith("_b.png")]
        pp.criar_bocas(ppid, base, so)
        return pp.animar_todas(ppid, base)
    return pp.enviar(ppid, faltam, "", base)


def poses_prontas(c: Dict[str, Any], base: str = _BASE) -> Dict[str, Dict[str, Optional[str]]]:
    """nome da pose (sem o slug) → {"pose": png, "b": png do 2º quadro, "boca": png da boca}."""
    pod = c.get("pod") or {}
    if not pod.get("pid"):
        return {}
    pp = _pp()
    try:
        proj = pp.carregar(pod["pid"], base)
    except pp.PersErro:
        return {}
    sl = R._slug(c["nome"]) + "_"
    out: Dict[str, Dict[str, Optional[str]]] = {}
    for x in proj["dados"]["poses"]:
        if x.get("tipo") != "pose" or x["arquivo"].endswith("_b.png"):
            continue
        cam = pp.arquivo_atual(proj, x["arquivo"], base)
        if not cam:
            continue
        nome = x["arquivo"][len(sl):-4] if x["arquivo"].startswith(sl) else x["arquivo"][:-4]
        b = pp.arquivo_atual(proj, x["arquivo"][:-4] + "_b.png", base)
        boca = next((y["arquivo"] for y in proj["dados"]["poses"] if y.get("tipo") == "boca" and y.get("base") == x["arquivo"]), None)
        out[nome] = {"pose": cam, "b": b, "boca": pp.arquivo_atual(proj, boca, base) if boca else None}
    return out


def estado_poses(c: Dict[str, Any], base: str = _BASE) -> Dict[str, Any]:
    pod = c.get("pod") or {}
    if not pod.get("pid"):
        return {"tem": False}
    pp = _pp()
    try:
        proj = pp.carregar(pod["pid"], base)
    except pp.PersErro:
        return {"tem": False, "erro": "o projeto 🧍 foi apagado"}
    itens = []
    for x in proj["dados"]["poses"]:
        it = proj["imagens"].get(x["arquivo"]) or {}
        itens.append({"arquivo": x["arquivo"], "tipo": x.get("tipo"), "estado": it.get("estado"),
                      "img": (it["versoes"][it["atual"]]["local"] if it.get("atual", -1) >= 0 and it.get("versoes") else None)})
    poses = [i for i in itens if i["tipo"] == "pose"]
    return {"tem": True, "pid": pod["pid"], "mestre": bool(proj.get("mestre")), "prontas": sum(1 for i in poses if i["img"]),
            "total": len(poses), "bocas": sum(1 for i in itens if i["tipo"] == "boca" and i["img"]),
            "esperando": sum(1 for i in itens if i["estado"] in ("fila", "gerando")),
            "erros": sum(1 for i in itens if i["estado"] == "erro"), "itens": itens}


# ------------------------------------------------------------------ 🏞 4 · locais e itens (Flow em massa ou suas imagens)
def prompt_imagem(p: Dict[str, Any], tipo: str, x: Dict[str, Any], camada: str = "fundo") -> str:
    W, H = tamanho(p)
    est = estilo_en(p)
    if tipo == "local" and camada == "fundo":
        return (f"Background of a 2D animated show, {'wide 16:9' if W > H else 'vertical 9:16'}: {x.get('prompt_en') or x['nome']}. "
                "Seen from the front at eye level; the lower part is floor/ground where characters will stand. EMPTY: no "
                f"people, no characters, no animals, no text. ART STYLE: {est}.")[:3900]
    if tipo == "local":  # a camada da frente
        return (f"{x.get('frente_en')}, a foreground prop for a 2D animated show seen from the front, the whole object visible "
                "with margin, isolated on a flat solid chroma-key green background (#00FF00), no shadow, no people, no text. "
                f"ART STYLE: {est}.")[:3900]
    if x.get("tipo") == "destaque":
        return (f"Full-frame key image for a 2D animated show: {x.get('prompt_en') or x['nome']}. Dramatic composition, "
                f"expressive, no text, no captions. ART STYLE: {est}.")[:3900]
    return (f"{x.get('prompt_en') or x['nome']}, a single prop/object for a 2D animated show, the whole object visible with "
            "margin, isolated on a flat solid chroma-key green background (#00FF00), no shadow, no text. "
            f"ART STYLE: {est}.")[:3900]


def _ref_flow(p: Dict[str, Any], x: Dict[str, Any], base: str, extra: Optional[List[str]] = None) -> Optional[str]:
    """A referência que vai pro Flow: as fotos do próprio local/item + as de estilo (e personagens), lado a lado."""
    from PIL import Image
    cams = refs_de(p, x, base)[:2] + refs_estilo(p, base)[:1] + (extra or [])[:3]
    if not cams:
        return None
    ims = []
    for c in cams:
        try:
            im = Image.open(c).convert("RGBA")
            fundo = Image.new("RGBA", im.size, (128, 128, 128, 255))
            fundo.alpha_composite(im)
            ims.append(fundo.convert("RGB"))
        except Exception:  # noqa: BLE001
            continue
    if not ims:
        return None
    import personagens_limpeza as L
    col = L.colagem(ims) if len(ims) > 1 else ims[0]
    d = os.path.join(pasta(p["id"], base), "imagens")
    os.makedirs(d, exist_ok=True)
    cam = os.path.join(d, f"_ref_{x['id']}_{secrets.token_hex(2)}.png")
    col.save(cam)
    return cam


def gerar_imagens(pid: str, base: str = _BASE, alvos: Optional[List[str]] = None, pedido: str = "") -> Dict[str, Any]:
    """🚀 Locais (fundo e a camada da frente) e itens pro Flow em massa. alvos = ["l…:fundo", "l…:frente", "i…"]; sem
    alvos = tudo o que ainda não tem imagem."""
    import flow_lote
    with _TRAVA:
        p = carregar(pid, base)
        lista: List[Tuple[str, Dict[str, Any], str]] = []
        for lo in p["locais"]:
            for camada in ("fundo", "frente"):
                if camada == "frente" and not (lo.get("frente_en") or "").strip():
                    continue
                chave = f"{lo['id']}:{camada}"
                st = lo.get("img" if camada == "fundo" else "frente") or {}
                if (alvos and chave in alvos) or (not alvos and not arquivo_img(p, st, base) and st.get("estado") not in ("fila", "gerando")):
                    lista.append(("local", lo, camada))
        for it in p["itens"]:
            st = it.get("img") or {}
            if (alvos and it["id"] in alvos) or (not alvos and not arquivo_img(p, st, base) and st.get("estado") not in ("fila", "gerando")):
                personagens_ref = []
                if it.get("tipo") == "destaque":  # o destaque costuma mostrar personagens: as mestres deles de referência
                    for c in p["personagens"]:
                        if R._norm(c["nome"]) and R._norm(c["nome"]) in R._norm(it.get("prompt_en") or "") + R._norm(it["nome"]):
                            pr = poses_prontas(c, base).get("neutro")
                            if pr:
                                personagens_ref.append(pr["pose"])
                lista.append(("item", it, "destaque" if it.get("tipo") == "destaque" else "objeto"))
                it["_refs_extra"] = personagens_ref
        if not lista:
            raise AnimeErro("Nada pra gerar (tudo já tem imagem ou está na fila).")
        W, H = tamanho(p)
        lote = flow_lote.lote()
        por_prop: Dict[str, List[int]] = {}
        itens = []
        for k, (tipo, x, camada) in enumerate(lista):
            pr = prompt_imagem(p, tipo, x, camada)
            if pedido:
                pr = (pr + " " + pedido)[:3990]
            it = {"prompt": pr, "tipo": "imagem", "origem": "anime2d"}
            ref = _ref_flow(p, x, base, x.pop("_refs_extra", None))
            if ref:
                it["referencia_arquivo"] = ref
            itens.append(it)
            prop = ("16:9" if W > H else "9:16") if camada in ("fundo", "destaque") else "1:1"
            por_prop.setdefault(prop, []).append(k)
        jobs: Dict[int, Dict[str, Any]] = {}
        for prop, ks in por_prop.items():
            try:
                feitos = lote.adicionar([itens[k] for k in ks], proporcao=prop, quantidade="x1")
            except ValueError as exc:
                raise AnimeErro(str(exc))
            for k, j in zip(ks, feitos):
                jobs[k] = j
        for k, (tipo, x, camada) in enumerate(lista):
            campo = "frente" if camada == "frente" else "img"
            st = x.setdefault(campo, {})
            st.update(estado="fila", job=jobs[k]["id"], erro=None, msg="⏳ na fila do Flow", recortar=camada in ("frente", "objeto"))
        log(p, f"🚀 {len(lista)} imagem(ns) pro Flow (locais/itens)")
        salvar(p, base)
    aviso = ""
    try:
        lote.iniciar()
    except Exception as exc:  # noqa: BLE001
        aviso = f"o Flow em massa não ligou agora ({str(exc)[:160]}) — ▶ Continuar na aba Flow"
    return {"enviadas": len(lista), "aviso": aviso}


def arquivo_img(p: Dict[str, Any], st: Dict[str, Any], base: str = _BASE) -> Optional[str]:
    arq = (st or {}).get("arquivo")
    cam = os.path.join(pasta(p["id"], base), "imagens", arq) if arq else ""
    return cam if arq and os.path.isfile(cam) else None


def guardar_img(p: Dict[str, Any], st: Dict[str, Any], img, recortar: bool, base: str = _BASE, origem: str = "flow",
                tela_cheia: bool = False) -> str:
    from PIL import Image
    d = os.path.join(pasta(p["id"], base), "imagens")
    os.makedirs(d, exist_ok=True)
    if tela_cheia:
        W, H = tamanho(p)
        im = img.convert("RGB")
        k = max(W / im.width, H / im.height)
        im = im.resize((max(W, round(im.width * k)), max(H, round(im.height * k))), Image.LANCZOS)
        x, y = (im.width - W) // 2, (im.height - H) // 2
        im = im.crop((x, y, x + W, y + H))
    elif recortar:
        tem_alfa = img.mode in ("RGBA", "LA") and img.getchannel("A").getextrema()[0] < 250
        if tem_alfa:
            im = img.convert("RGBA")
            bb = im.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
            im = im.crop(bb) if bb else im
        else:
            try:
                im = R.recortar_verde(img.convert("RGB"))
            except R.ReactErro:
                im = img.convert("RGBA")
    else:
        im = img.convert("RGBA")
    arq = f"img_{secrets.token_hex(4)}.png"
    im.save(os.path.join(d, arq))
    st.update(arquivo=arq, estado="pronta", erro=None, msg=None, origem=origem,
              versoes=([arq] + [v for v in st.get("versoes") or [] if v != arq])[:6])
    return arq


def _todas_imgs(p: Dict[str, Any]) -> List[Tuple[Dict[str, Any], bool, bool]]:
    """(estado, recortar, tela_cheia) de cada imagem de local/item."""
    out = []
    for lo in p["locais"]:
        out.append((lo.setdefault("img", {}), False, True))
        if lo.get("frente_en") or (lo.get("frente") or {}).get("arquivo"):
            out.append((lo.setdefault("frente", {}), True, False))
    for it in p["itens"]:
        out.append((it.setdefault("img", {}), it.get("tipo") != "destaque", it.get("tipo") == "destaque"))
    for c in p["personagens"]:  # 🎨 o design anime (adaptação de mangá) — entra sozinho quando o Flow termina
        if c.get("design"):
            out.append((c["design"], False, False))
    return out


def acompanhar(pid: str, base: str = _BASE) -> Dict[str, Any]:
    """⏱ Chamado pela página: a ⭐ neutra pronta vira a mestre e manda o resto; as imagens do Flow entram."""
    pp = _pp()
    p = carregar(pid, base)
    avisos = []
    for c in p["personagens"]:
        pod = c.get("pod") or {}
        if not pod.get("pid"):
            continue
        try:
            r = pp.sincronizar(pod["pid"], base)
            if r.get("aviso"):
                avisos.append(f"{c['nome']}: {r['aviso']}")
            proj = pp.carregar(pod["pid"], base)
        except pp.PersErro as exc:
            avisos.append(f"{c['nome']}: {exc}")
            continue
        if pod.get("fase") == "mestre" and not proj.get("mestre"):
            mestre = next((x["arquivo"] for x in proj["dados"]["poses"] if x.get("mestre")), None)
            if mestre and pp.arquivo_atual(proj, mestre, base) and (proj["imagens"].get(mestre) or {}).get("estado") == "pronta":
                try:
                    pp.usar_como_mestre(pod["pid"], mestre, base)
                    _mandar_resto(pod["pid"], base)
                    with _TRAVA:
                        q = carregar(pid, base)
                        next(x for x in q["personagens"] if x["id"] == c["id"])["pod"]["fase"] = "resto"
                        log(q, f"⭐ {c['nome']}: a neutra virou a mestre — o resto das poses foi pro Flow")
                        salvar(q, base)
                except Exception as exc:  # noqa: BLE001
                    avisos.append(f"{c['nome']}: {str(exc)[:160]}")
        elif pod.get("fase") == "resto" and proj.get("mestre"):
            # quando as poses ficam prontas, as bocas (e os 2ºs quadros) que faltam seguem sozinhas
            if not any((proj["imagens"].get(x["arquivo"]) or {}).get("estado") in ("fila", "gerando") for x in proj["dados"]["poses"]):
                faltam = [x for x in proj["dados"]["poses"] if not pp.arquivo_atual(proj, x["arquivo"], base)
                          and (proj["imagens"].get(x["arquivo"]) or {}).get("estado") in ("nova", None)]
                sem_boca = [x for x in proj["dados"]["poses"] if x.get("tipo") == "pose" and not x["arquivo"].endswith("_b.png")
                            and not any(y.get("tipo") == "boca" and y.get("base") == x["arquivo"] for y in proj["dados"]["poses"])]
                if faltam or sem_boca:
                    try:
                        _mandar_resto(pod["pid"], base)
                    except Exception as exc:  # noqa: BLE001
                        avisos.append(f"{c['nome']}: {str(exc)[:160]}")
    try:
        _acompanhar_imagens(pid, base)
    except Exception as exc:  # noqa: BLE001
        avisos.append(f"imagens: {str(exc)[:160]}")
    try:
        _acompanhar_videos(pid, base)
    except Exception as exc:  # noqa: BLE001
        avisos.append(f"vídeos: {str(exc)[:160]}")
    return {"avisos": avisos}


def _acompanhar_imagens(pid: str, base: str) -> bool:
    import flow_lote
    p = carregar(pid, base)
    if not any(st.get("estado") in ("fila", "gerando") for st, _r, _t in _todas_imgs(p)):
        return False
    lote = flow_lote.lote()
    with lote.trava:
        fila = {j["id"]: dict(j) for j in lote.fila}
        rodando = lote.rodando
    mudou = False
    with _TRAVA:
        p = carregar(pid, base)
        for st, recortar, tela in _todas_imgs(p):
            if st.get("estado") not in ("fila", "gerando") or not st.get("job"):
                continue
            fj = fila.get(st["job"])
            antes = (st.get("estado"), st.get("msg"))
            if fj is None:
                st.update(estado="erro", erro="o pedido sumiu da fila do 🚀 Flow em massa — gere de novo")
            elif fj["estado"] == "ok":
                ok = False
                for r in fj.get("resultados") or []:
                    try:
                        import flow_estudio as FE
                        from PIL import Image
                        orig = os.path.join(FE.pasta_galeria(), r.get("arquivo") or "")
                        if r.get("tipo") == "imagem" and os.path.isfile(orig):
                            guardar_img(p, st, Image.open(orig), recortar, base, tela_cheia=tela)
                            ok = True
                            break
                    except Exception as exc:  # noqa: BLE001
                        st.update(estado="erro", erro=f"a imagem chegou mas não deu pra guardar: {str(exc)[:160]}")
                if not ok and st.get("estado") != "erro":
                    st.update(estado="erro", erro="o Flow terminou sem imagem")
            elif fj["estado"] == "erro":
                st.update(estado="erro", erro=str(fj.get("erro") or "o Flow falhou")[:300])
            elif fj["estado"] in ("rodando", "convertendo"):
                st.update(estado="gerando", msg=f"🎨 gerando no Flow (conta “{fj.get('conta')}”)")
            elif not rodando:
                st.update(msg="⏸ o Flow em massa está parado — ▶ Continuar na aba Flow")
            if (st.get("estado"), st.get("msg")) != antes:
                mudou = True
        if mudou:
            salvar(p, base)
    return mudou


# ------------------------------------------------------------------ 🎞 opcional: animar UM momento no Flow (vídeo)
def momento(p: Dict[str, Any], mid: str) -> Tuple[int, int, Dict[str, Any]]:
    for k, s in enumerate(p["cenas"]):
        for j, m in enumerate(s.get("momentos") or []):
            if m["id"] == mid:
                return k, j, m
    raise AnimeErro("Momento não encontrado.")


def animar_momento(pid: str, mid: str, pedido: str = "", base: str = _BASE) -> Dict[str, Any]:
    """🎞 Só quando você pede: o quadro desse momento (sem legenda) vai pro Flow virar um vídeo curto, que entra no
    lugar dele em tela cheia. O resto continua montado com imagens."""
    import flow_lote
    p = carregar(pid, base)
    k, j, m = momento(p, mid)
    tl = linha_do_tempo(p, base)
    mm = tl["cenas"][k]["momentos"][j]
    d = os.path.join(pasta(pid, base), "imagens")
    quadro = os.path.join(d, f"_quadro_{mid}.jpg")
    previa(p, base, quadro, (mm["ini"] + mm["fim"]) / 2, legenda=False)
    acao = m.get("texto") if m["tipo"] in ("acao", "destaque") else f"{nome_de(p, m['quem'])} talking: {m['texto']}"
    pr = (f"Animate this frame of a 2D animated show, keep the exact same drawing style, characters and background: {acao}. "
          "Subtle natural motion (characters move and gesture, mouths move when talking), static camera unless needed, no "
          f"new characters, no text. {pedido}".strip())[:3900]
    lote = flow_lote.lote()
    try:
        jb = lote.adicionar([{"prompt": pr, "tipo": "video", "inicio_arquivo": quadro, "origem": "anime2d"}],
                            proporcao="16:9" if tamanho(p)[0] > tamanho(p)[1] else "9:16", quantidade="x1")[0]
    except ValueError as exc:
        raise AnimeErro(str(exc))
    with _TRAVA:
        p = carregar(pid, base)
        _k, _j, m = momento(p, mid)
        m["video"] = {"estado": "fila", "job": jb["id"], "erro": None, "msg": "⏳ na fila do Flow (vídeo)"}
        log(p, f"🎞 momento {mid} pro Flow (vídeo)")
        salvar(p, base)
    aviso = ""
    try:
        lote.iniciar()
    except Exception as exc:  # noqa: BLE001
        aviso = f"o Flow em massa não ligou agora ({str(exc)[:160]})"
    return {"aviso": aviso}


def _acompanhar_videos(pid: str, base: str) -> None:
    import flow_lote
    p = carregar(pid, base)
    abertos = [m for s in p["cenas"] for m in s.get("momentos") or [] if (m.get("video") or {}).get("estado") in ("fila", "gerando")]
    if not abertos:
        return
    lote = flow_lote.lote()
    with lote.trava:
        fila = {j["id"]: dict(j) for j in lote.fila}
    with _TRAVA:
        p = carregar(pid, base)
        mudou = False
        for s in p["cenas"]:
            for m in s.get("momentos") or []:
                v = m.get("video") or {}
                if v.get("estado") not in ("fila", "gerando"):
                    continue
                fj = fila.get(v.get("job"))
                if fj is None:
                    v.update(estado="erro", erro="o pedido sumiu da fila do Flow")
                elif fj["estado"] == "ok":
                    import flow_estudio as FE
                    r = next((r for r in fj.get("resultados") or [] if r.get("tipo") == "video"
                              and os.path.isfile(os.path.join(FE.pasta_galeria(), r.get("arquivo") or ""))), None)
                    if r:
                        arq = f"video_{m['id']}_{secrets.token_hex(2)}{os.path.splitext(r['arquivo'])[1] or '.mp4'}"
                        shutil.copyfile(os.path.join(FE.pasta_galeria(), r["arquivo"]), os.path.join(pasta(pid, base), "imagens", arq))
                        v.update(estado="pronta", arquivo=arq, erro=None, msg=None)
                    else:
                        v.update(estado="erro", erro="o Flow terminou sem vídeo")
                elif fj["estado"] == "erro":
                    v.update(estado="erro", erro=str(fj.get("erro") or "o Flow falhou")[:300])
                elif fj["estado"] in ("rodando", "convertendo"):
                    v.update(estado="gerando", msg="🎨 gerando o vídeo no Flow")
                m["video"] = v
                mudou = True
        if mudou:
            salvar(p, base)


# ------------------------------------------------------------------ 🎙 5 · vozes
def vozes_disponiveis() -> List[Dict[str, Any]]:
    try:
        import multivoz
        return [{"slug": v["slug"], "nome": v["nome"], "resumo": multivoz.resumo(v), "genero": v.get("genero") or ""} for v in multivoz.listar()]
    except Exception:  # noqa: BLE001
        return []


def duracao_wav(cam: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", cam],
                           capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip() or 0)
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


def gerar_vozes(pid: str, base: str, tts: Callable[..., Any], limpar: Callable[[str, str], str],
                so_faltando: bool = True, on_log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """🎙 Uma fala = um áudio (a voz do personagem; a do narrador na narração). A duração de cada um vira a linha do tempo.
    Sem voz escolhida: fica em silêncio pelo tempo de leitura (a legenda aparece)."""
    import multivoz
    vozes = multivoz.por_slug()
    p = carregar(pid, base)
    if audio_ok(p, base):
        raise AnimeErro("Este episódio usa o 🎧 áudio que você enviou — não precisa gerar vozes.")
    d = os.path.join(pasta(pid, base), "vozes")
    os.makedirs(d, exist_ok=True)
    feitas, sem_voz, erros = 0, 0, []
    todos = [(k, j) for k, s in enumerate(p["cenas"]) for j, m in enumerate(s.get("momentos") or []) if m["tipo"] in ("fala", "narracao") and m.get("texto")]
    for n, (k, j) in enumerate(todos, 1):
        p = carregar(pid, base)
        m = p["cenas"][k]["momentos"][j]
        slug = (p.get("narrador") or {}).get("voz") if m["quem"] == "narrador" else (next((c for c in p["personagens"] if c["id"] == m["quem"]), {}) or {}).get("voz")
        chave = f"{slug}|{m['texto']}"
        if so_faltando and (m.get("audio") or {}).get("chave") == chave and os.path.isfile(os.path.join(d, (m.get("audio") or {}).get("arquivo") or "_")):
            continue
        if not slug or slug not in vozes:
            sem_voz += 1
            with _TRAVA:
                p = carregar(pid, base)
                p["cenas"][k]["momentos"][j]["audio"] = {}
                salvar(p, base)
            continue
        on_log(f"🎙 {n}/{len(todos)} {nome_de(p, m['quem'])}: “{m['texto'][:40]}”")
        motor, kw = multivoz.kwargs_da_voz(vozes[slug])
        arq = f"{m['id']}_{secrets.token_hex(2)}.wav"
        bruto = os.path.join(d, "_" + arq)
        try:
            tts(motor, limpar(m["texto"], motor), bruto, **kw)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", bruto, "-ar", "44100", "-ac", "2", os.path.join(d, arq)],
                           check=True, capture_output=True, timeout=120)
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{nome_de(p, m['quem'])}: {str(exc)[:120]}")
            continue
        finally:
            try:
                os.remove(bruto)
            except OSError:
                pass
        dur = duracao_wav(os.path.join(d, arq))
        with _TRAVA:
            p = carregar(pid, base)
            mm = p["cenas"][k]["momentos"][j]
            antigo = (mm.get("audio") or {}).get("arquivo")
            mm["audio"] = {"arquivo": arq, "dur": round(dur, 3), "chave": chave}
            salvar(p, base)
        if antigo and antigo != arq:
            try:
                os.remove(os.path.join(d, antigo))
            except OSError:
                pass
        feitas += 1
    with _TRAVA:
        p = carregar(pid, base)
        log(p, f"🎙 vozes: {feitas} nova(s)" + (f" · {sem_voz} sem voz escolhida (ficam em silêncio com a legenda)" if sem_voz else "")
            + (f" · ❌ {len(erros)} erro(s)" if erros else ""))
        salvar(p, base)
    return {"feitas": feitas, "sem_voz": sem_voz, "erros": erros}


# ------------------------------------------------------------------ ⏱ 6 · linha do tempo
def duracao_leitura(texto: str) -> float:
    n = len(str(texto or "").split())
    return round(max(1.6, min(9.0, 0.9 + 0.38 * n)), 2)


def linha_do_tempo(p: Dict[str, Any], base: str = _BASE) -> Dict[str, Any]:
    """Cada momento em sequência: começa onde o anterior acabou (+ uma pausa curta). → {"cenas": [{ini, fim, momentos:
    [{…, ini, fim, fala: [ini, fim]}]}], "duracao"}. 🎧 Modo áudio: os tempos vêm do áudio."""
    if audio_ok(p, base):
        return _linha_do_tempo_audio(p)
    t = 0.0
    out = []
    d = os.path.join(pasta(p["id"], base), "vozes")
    for s in p["cenas"]:
        ini_s = t
        ms = []
        for m in s.get("momentos") or []:
            au = m.get("audio") or {}
            tem_audio = bool(au.get("arquivo")) and os.path.isfile(os.path.join(d, au["arquivo"]))
            if m["tipo"] in ("fala", "narracao"):
                dur = float(au.get("dur") or 0) if tem_audio else duracao_leitura(m["texto"])
                dur = max(dur, 0.8)
                pausa = 0.3
            else:
                dur = float(m.get("duracao") or (2.5 if m["tipo"] == "destaque" else 2.0))
                pausa = 0.0
            ms.append(dict(m, ini=round(t, 3), fim=round(t + dur, 3), audio_ok=tem_audio))
            t += dur + pausa
        if not ms:  # cena vazia: 2 s do lugar
            t += 2.0
        out.append({"id": s["id"], "ini": round(ini_s, 3), "fim": round(t, 3), "momentos": ms})
    return {"cenas": out, "duracao": round(t, 3)}


def audio_ok(p: Dict[str, Any], base: str = _BASE) -> bool:
    au = p.get("audio") or {}
    return bool(au.get("arquivo")) and os.path.isfile(os.path.join(pasta(p["id"], base), au["arquivo"]))


def _linha_do_tempo_audio(p: Dict[str, Any]) -> Dict[str, Any]:
    """🎧 Cada momento começa no 'tempo' dele no áudio e vai até o próximo; a boca mexe enquanto o trecho da
    transcrição dura. Momentos sem tempo ficam logo depois do anterior."""
    dur = float((p.get("audio") or {}).get("dur") or 0)
    trans = (p.get("audio") or {}).get("transcricao") or []
    todos = []
    for k, s in enumerate(p["cenas"]):
        a, _b = janela_audio_cena(p, k)
        ult = a
        for m in s.get("momentos") or []:
            t = m.get("tempo")
            t = float(t) if t is not None else ult
            t = max(ult, min(t, dur))
            todos.append((k, m, t))
            ult = t + 0.01
    out = [{"id": s["id"], "ini": None, "fim": None, "momentos": []} for s in p["cenas"]]
    for i, (k, m, t) in enumerate(todos):
        fim = todos[i + 1][2] if i + 1 < len(todos) else dur
        fim = max(fim, t + 0.4)
        x = dict(m, ini=round(t, 3), fim=round(fim, 3), audio_ok=False)
        if m["tipo"] in ("fala", "narracao"):
            tr = next((y for y in trans if abs(y["ini"] - t) < 1.2), None)
            x["fala_fim"] = round(min(fim, tr["fim"] if tr else t + duracao_leitura(m["texto"])), 3)
        out[k]["momentos"].append(x)
    for k, c in enumerate(out):
        a, b = janela_audio_cena(p, k)
        c["ini"] = round(min([a] + [m["ini"] for m in c["momentos"]]), 3) if c["momentos"] else round(a, 3)
        c["fim"] = round(b, 3)
    # as cenas encostam uma na outra
    for k in range(len(out) - 1):
        nxt = out[k + 1]["momentos"][0]["ini"] if out[k + 1]["momentos"] else out[k + 1]["ini"]
        out[k]["fim"] = round(max(out[k]["ini"] + 0.5, nxt), 3)
        out[k + 1]["ini"] = out[k]["fim"]
    if out:
        out[0]["ini"] = 0.0
        out[-1]["fim"] = round(max(dur, out[-1]["ini"] + 0.5), 3)
    return {"cenas": out, "duracao": round(max(dur, out[-1]["fim"] if out else dur), 3)}


def guardar_audio(p: Dict[str, Any], nome: str, dados: bytes, base: str = _BASE) -> Dict[str, Any]:
    """🎧 O áudio pronto do episódio (diálogo, narração, podcast): vira o áudio do vídeo e a IA monta a animação em volta."""
    d = pasta(p["id"], base)
    bruto = os.path.join(d, "_audio_up" + (os.path.splitext(nome)[1] or ".bin"))
    with open(bruto, "wb") as f:
        f.write(dados)
    destino = os.path.join(d, "audio.wav")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", bruto, "-vn", "-ar", "44100", "-ac", "2", destino],
                       capture_output=True, text=True, timeout=600)
    try:
        os.remove(bruto)
    except OSError:
        pass
    if r.returncode != 0 or not os.path.isfile(destino):
        raise AnimeErro("Não consegui ler esse áudio.")
    p["audio"] = {"arquivo": "audio.wav", "nome": os.path.basename(nome)[:120], "dur": round(duracao_wav(destino), 3), "transcricao": []}
    log(p, f"🎧 áudio: {p['audio']['nome']} ({R.mmss(p['audio']['dur'])})")
    return p["audio"]


def transcrever_audio(pid: str, base: str = _BASE) -> int:
    """🎙 O Whisper transcreve o áudio (com os tempos) — a IA usa isso pra montar personagens, cenas e falas."""
    p = carregar(pid, base)
    if not audio_ok(p, base):
        raise AnimeErro("Envie o áudio antes.")
    from whisper_transcribe import transcribe_audio
    segs = transcribe_audio(os.path.join(pasta(pid, base), p["audio"]["arquivo"]))
    linhas = [{"ini": round(float(s["start"]), 2), "fim": round(float(s["end"]), 2), "texto": " ".join(str(s["text"]).split())}
              for s in segs if str(s.get("text") or "").strip()]
    with _TRAVA:
        p = carregar(pid, base)
        p["audio"]["transcricao"] = linhas
        log(p, f"🎙 áudio transcrito: {len(linhas)} trecho(s)")
        salvar(p, base)
    return len(linhas)


def definir_transcricao_audio(p: Dict[str, Any], texto: str) -> int:
    """A transcrição do áudio colada/corrigida por você ("0:13 texto" por linha)."""
    linhas = []
    for e in R.parse_transcricao(str(texto or "")):
        if e.get("ini") is not None and str(e.get("texto") or "").strip():
            linhas.append({"ini": round(float(e["ini"]), 2), "fim": round(float(e.get("fim") or e["ini"] + 3), 2), "texto": e["texto"]})
    for a, b in zip(linhas, linhas[1:]):
        a["fim"] = min(a["fim"], b["ini"]) if a["fim"] > a["ini"] else b["ini"]
    p.setdefault("audio", {})["transcricao"] = linhas
    return len(linhas)


def montar_audio(p: Dict[str, Any], tl: Dict[str, Any], destino: str, base: str = _BASE) -> str:
    """Os áudios das falas nos tempos certos (silêncio no resto) → um wav do episódio inteiro. 🎧 Modo áudio: o seu."""
    if audio_ok(p, base):
        shutil.copyfile(os.path.join(pasta(p["id"], base), p["audio"]["arquivo"]), destino)
        return destino
    d = os.path.join(pasta(p["id"], base), "vozes")
    dur = max(1.0, tl["duracao"])
    entradas = ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    filtros, rot = [], ["[0:a]"]
    k = 1
    for s in tl["cenas"]:
        for m in s["momentos"]:
            if not m.get("audio_ok"):
                continue
            entradas += ["-i", os.path.join(d, m["audio"]["arquivo"])]
            ms = int(round(m["ini"] * 1000))
            filtros.append(f"[{k}:a]adelay={ms}|{ms}[a{k}]")
            rot.append(f"[a{k}]")
            k += 1
    if k == 1:
        subprocess.run(["ffmpeg", "-y", "-v", "error"] + entradas + ["-c:a", "pcm_s16le", destino], check=True, capture_output=True, timeout=300)
        return destino
    filtro = ";".join(filtros) + ";" + "".join(rot) + f"amix=inputs={len(rot)}:normalize=0:duration=first[out]"
    script = destino + ".filtro.txt"
    with open(script, "w", encoding="utf-8") as f:
        f.write(filtro)
    try:
        r = subprocess.run(["ffmpeg", "-y", "-v", "error"] + entradas + ["-filter_complex_script", script, "-map", "[out]",
                                                                         "-c:a", "pcm_s16le", destino], capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            r = subprocess.run(["ffmpeg", "-y", "-v", "error"] + entradas + ["-/filter_complex", script, "-map", "[out]",
                                                                             "-c:a", "pcm_s16le", destino], capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise AnimeErro(f"não consegui juntar os áudios: {r.stderr[-300:]}")
    finally:
        try:
            os.remove(script)
        except OSError:
            pass
    return destino


# ------------------------------------------------------------------ 🎬 7 · montar (editor e prévia)
def _estados_personagens(cena: Dict[str, Any]) -> List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    """Por momento, quem está em cena (um momento sem 'em_cena' herda o anterior)."""
    atual: List[Dict[str, Any]] = []
    out = []
    for m in cena["momentos"]:
        if m.get("em_cena"):
            atual = m["em_cena"]
        out.append((m, atual))
    return out


def _figura(p: Dict[str, Any], W: int, H: int, posicao: str) -> Tuple[float, float, float]:
    """(cx, base_y, altura) do personagem na posição."""
    alt = H * (0.74 if W > H else 0.46)
    return W * POSICOES.get(posicao, 0.5), H * 0.97, alt


def plano_de_camadas(p: Dict[str, Any], base: str = _BASE) -> Dict[str, Any]:
    """O que vai em cada tempo: fundos por cena, personagens (com quadros A/B e boca), objetos, frente, destaques e
    legendas — em px do vídeo. É o que o editor e a prévia usam."""
    W, H = tamanho(p)
    tl = linha_do_tempo(p, base)
    poses = {c["id"]: poses_prontas(c, base) for c in p["personagens"]}
    fundos, figs, objs, frentes, destaques, legendas, avisos, videos = [], [], [], [], [], [], [], []
    tremidas: List[Dict[str, float]] = []
    faltando: Dict[str, set] = {}
    for s, ts in zip(p["cenas"], tl["cenas"]):
        lo = next((x for x in p["locais"] if x["id"] == s.get("local")), None)
        fundo = arquivo_img(p, (lo or {}).get("img") or {}, base) if lo else None
        cam_ = next((m.get("camera") for m in ts["momentos"] if m.get("camera") and m.get("camera") != "fixa"), "fixa")
        fundos.append({"cena": s["id"], "ini": ts["ini"], "fim": ts["fim"], "arquivo": fundo, "camera": cam_,
                       "nome": (lo or {}).get("nome") or "?"})
        if lo and not fundo:
            avisos.append(f"🏞 {lo['nome']}: sem a imagem do fundo — usei um degradê")
        fr = arquivo_img(p, (lo or {}).get("frente") or {}, base) if lo else None
        if fr:
            frentes.append({"ini": ts["ini"], "fim": ts["fim"], "arquivo": fr})
        for m, presentes in _estados_personagens(dict(s, momentos=ts["momentos"])):
            ini, fim = m["ini"], m["fim"] + (0.3 if m["tipo"] in ("fala", "narracao") else 0.0)
            fim = min(fim, ts["fim"])
            for e in presentes:
                c = next((x for x in p["personagens"] if x["id"] == e["cid"]), None)
                if not c:
                    continue
                nome = nome_pose(e["pose"], e.get("pose_en") or "")
                pc = poses.get(c["id"], {})
                x = pc.get(nome) or pc.get("neutro") or (next(iter(pc.values())) if pc else None)
                if not x:
                    faltando.setdefault(c["nome"], set()).add("todas")
                    continue
                if nome not in pc:
                    faltando.setdefault(c["nome"], set()).add(nome)
                cx, by, alt = _figura(p, W, H, e["posicao"])
                falando = m["tipo"] == "fala" and m["quem"] == c["id"]
                figs.append({"cid": c["id"], "nome": c["nome"], "ini": ini, "fim": fim, "pose": x["pose"], "b": x.get("b"),
                             "boca": x.get("boca") if falando else None, "fala": [m["ini"], m.get("fala_fim") or m["fim"]] if falando else None,
                             "cx": cx, "base_y": by, "alt": alt, "espelhar": e.get("olha") == "esquerda", "pose_nome": nome})
            if m.get("objeto"):
                it = next((i for i in p["itens"] if i["id"] == m["objeto"]), None)
                cam = arquivo_img(p, (it or {}).get("img") or {}, base) if it else None
                if cam:
                    objs.append({"ini": ini, "fim": fim, "arquivo": cam, "cx": W * 0.5, "base_y": H * 0.95, "w": W * 0.18})
            if m["tipo"] == "destaque" and m.get("destaque"):
                it = next((i for i in p["itens"] if i["id"] == m["destaque"]), None)
                cam = arquivo_img(p, (it or {}).get("img") or {}, base) if it else None
                if cam:
                    destaques.append({"ini": m["ini"], "fim": m["fim"], "arquivo": cam})
                elif it:
                    avisos.append(f"🌟 {it['nome']}: sem imagem — o destaque ficou de fora")
            if m.get("camera") == "tremida":
                tremidas.append({"ini": m["ini"], "fim": m["fim"]})
            v = m.get("video") or {}
            if v.get("estado") == "pronta" and v.get("arquivo") and os.path.isfile(os.path.join(pasta(p["id"], base), "imagens", v["arquivo"])):
                videos.append({"ini": m["ini"], "fim": m["fim"], "arquivo": os.path.join(pasta(p["id"], base), "imagens", v["arquivo"])})
            if m["tipo"] in ("fala", "narracao") and p.get("legendas", True):
                quem = nome_de(p, m["quem"])
                c = next((x for x in p["personagens"] if x["id"] == m["quem"]), None)
                legendas.append({"ini": m["ini"], "fim": (m.get("fala_fim") or m["fim"]) + 0.2, "nome": quem, "texto": m["texto"],
                                 "cor": (c or {}).get("cor") or "#ffffff"})
    for nome, f in faltando.items():
        avisos.append(f"🧍 {nome}: " + ("ainda sem poses (🚀 Gerar)" if "todas" in f else f"sem a pose {', '.join(sorted(f))} — usei a neutra"))
    return {"W": W, "H": H, "duracao": tl["duracao"], "tl": tl, "fundos": fundos, "figs": figs, "objetos": objs,
            "frentes": frentes, "destaques": destaques, "legendas": legendas, "avisos": avisos, "videos": videos,
            "tremidas": tremidas, "paralaxe": bool(p.get("paralaxe", True))}


def movimento(plano: Dict[str, Any], camada: str, ini: float, fim: float, cx: float = 0.5) -> List[Dict[str, float]]:
    """🌄 Como a camada anda (parallax) nas cenas que cruzam [ini, fim] — pro render (video_assembler) e pra prévia.
    Cada item: {"a", "b", "dx", "dy"} = deslocamento total na cena (fração de W/H; vai de -d/2 a +d/2, então no meio
    da cena a camada está onde você pôs) ou {"a", "b", "tremor"} = a câmera tremida (some em ~0,8 s). cx = o centro
    da camada (0–1), pro zoom abrir pros lados."""
    if not plano.get("paralaxe", True) or camada not in PARALAXE:
        return []
    out: List[Dict[str, float]] = []
    for f in plano["fundos"]:
        if f["fim"] <= ini or f["ini"] >= fim:
            continue
        cam, dx, dy = f.get("camera") or "fixa", 0.0, 0.0
        if cam == "pan_esq":  # o fundo desliza pra direita na tela → quem está mais perto desliza mais
            dx = PARALAXE[camada]
        elif cam == "pan_dir":
            dx = -PARALAXE[camada]
        elif cam in ("zoom_in", "zoom_out"):
            sinal = 1 if cam == "zoom_in" else -1
            dx = sinal * PARALAXE_ZOOM[camada] * (cx - 0.5) * 2
            dy = sinal * PARALAXE_ZOOM_Y[camada]
        if dx or dy:
            out.append({"a": round(f["ini"], 3), "b": round(f["fim"], 3), "dx": round(dx, 4), "dy": round(dy, 4)})
    for tr in plano.get("tremidas") or []:
        if tr["fim"] > ini and tr["ini"] < fim:
            out.append({"a": round(tr["ini"], 3), "b": round(tr["fim"], 3), "tremor": TREMOR[camada]})
    return out


def deslocamento(movs: List[Dict[str, float]], t: float, W: int, H: int) -> Tuple[float, float]:
    """(dx, dy) em px no segundo t — a mesma conta do video_assembler._mov_expr."""
    import math
    x = y = 0.0
    for m in movs or []:
        a, b = float(m["a"]), float(m["b"])
        if not (a <= t <= b):
            continue
        if m.get("tremor"):
            amp = float(m["tremor"]) * max(0.0, 1 - (t - a) / 0.8)
            x += W * amp * math.sin(t * 47)
            y += W * amp * 0.6 * math.sin(t * 31 + 1)
        else:
            k = (t - a) / max(0.001, b - a) - 0.5
            x += W * float(m.get("dx") or 0) * k
            y += H * float(m.get("dy") or 0) * k
    return x, y


def _fundo_degrade(destino: str, W: int, H: int) -> str:
    from PIL import Image
    im = Image.new("RGB", (W, H))
    for y in range(H):
        t = y / H
        im.paste((int(120 + 80 * t), int(170 + 40 * t), int(220 - 60 * t)), (0, y, W, y + 1))
    im.save(destino)
    return destino


def _tam_frente(cam: str, W: int, H: int) -> Tuple[float, float]:
    """A camada da frente (balcão, arbusto, mesa): embaixo, no meio, sem cobrir os personagens inteiros."""
    iw, ih = R._tam(cam, (4, 1))
    w = W * (0.62 if W > H else 0.9)
    h = w * ih / iw
    if h > H * (0.28 if W > H else 0.2):
        h = H * (0.28 if W > H else 0.2)
        w = h * iw / ih
    return w, h


def _quadros(f: Dict[str, Any]) -> List[Tuple[float, float, str]]:
    """Os pedaços (ini, fim, imagem) de um personagem nesse momento: a pose e o 2º quadro alternando a cada 0,25 s."""
    if not f.get("b"):
        return [(f["ini"], f["fim"], f["pose"])]
    out, t, k = [], f["ini"], 0
    while t < f["fim"] - 0.02:
        fim = min(f["fim"], t + 0.25)
        out.append((t, fim, f["pose"] if k % 2 == 0 else f["b"]))
        t, k = fim, k + 1
    return out


def montar_editor(p: Dict[str, Any], base: str, job_dir: str) -> Dict[str, Any]:
    """Tudo pro Estúdio: o áudio do episódio, um trecho de fundo por cena (com a câmera) e as camadas posicionadas."""
    from PIL import Image
    if not any(s.get("momentos") for s in p["cenas"]):
        raise AnimeErro("Escreva as cenas primeiro.")
    plano = plano_de_camadas(p, base)
    W, H = plano["W"], plano["H"]
    dur = plano["duracao"]
    d = os.path.join(job_dir, "anime2d")
    os.makedirs(d, exist_ok=True)
    audio = montar_audio(p, plano["tl"], os.path.join(job_dir, "narracao.wav"), base)
    copiados: Dict[str, str] = {}

    def copiar(cam: str) -> str:
        if cam not in copiados:
            dst = os.path.join(d, f"{len(copiados):03d}_{os.path.basename(cam)}")
            shutil.copyfile(cam, dst)
            copiados[cam] = dst
        return copiados[cam]

    segs = []
    for k, f in enumerate(plano["fundos"]):
        cam = copiar(f["arquivo"]) if f["arquivo"] else _fundo_degrade(os.path.join(d, f"degrade_{k}.png"), W, H)
        segs.append({"start": f["ini"], "end": f["fim"], "provider": "material", "query": f"🎞 {f['nome']}"[:150],
                     "on_screen_text": None, "media_type": "image", "zoom_direction": CAMERAS.get(f["camera"], "static"),
                     "efeito": None, "override_source": {"source": "local_file", "value": cam, "kind": "image",
                                                         "zoom_direction": CAMERAS.get(f["camera"], "static"),
                                                         "focus_x": 0.5, "focus_y": 0.5}})
    overlays: List[Dict[str, Any]] = []

    def png(oid: str, nome: str, cam: str, cx: float, cy: float, w: float, ini: float, fim: float, camada: str, **extra: Any) -> None:
        ov = {"id": oid, "origem": "react", "camada": camada, "personagem": f"anime2d_{camada}", "nome_personagem": nome,
              "source": {"source": "local_file", "value": cam, "kind": "image"}, "media_type": "image",
              "start": round(ini, 3), "end": round(fim, 3), "position": "bottom-left", "ancora": "centro",
              "size_percent": R._pct(w, W), "x_percent": R._pct(cx, W), "y_percent": R._pct(cy, H),
              "anim_in": "nenhuma", "anim_out": "nenhuma", "anim_dur": 0.2, "espelhar": False, "boca_path": None,
              "boca_janelas": [], "manual": True}
        ov.update(extra)
        overlays.append(ov)

    # personagens (de trás pra frente: a ordem da lista) — cada um uma trilha contínua no render
    for c in p["personagens"]:
        for k, f in enumerate([f for f in plano["figs"] if f["cid"] == c["id"]]):
            for j, (a, b, img) in enumerate(_quadros(f)):
                iw, ih = R._tam(img, (2, 3))
                w = f["alt"] * iw / ih
                jan = []
                if f.get("boca") and f.get("fala") and img == f["pose"]:
                    jan = [[max(x, a), min(y, b)] for x, y in R._boca_janelas(f["fala"][0], f["fala"][1]) if min(y, b) - max(x, a) > 0.05]
                png(f"a{c['id']}_{k}_{j}", c["nome"], copiar(img), f["cx"], f["base_y"] - f["alt"] / 2, w, a, b, "personagem",
                    mov=movimento(plano, "personagem", a, b, f["cx"] / W), espelhar=f["espelhar"], cid=c["id"], expressao=f["pose_nome"], trilha=f"p:{c['id']}:{round(f['cx'])}:{f['espelhar']}",
                    boca_path=copiar(f["boca"]) if jan else None, boca_janelas=jan)
    for k, o in enumerate(plano["objetos"]):
        iw, ih = R._tam(o["arquivo"], (1, 1))
        h = o["w"] * ih / iw
        png(f"aobj{k}", "📦 objeto", copiar(o["arquivo"]), o["cx"], o["base_y"] - h / 2, o["w"], o["ini"], o["fim"], "objeto",
            mov=movimento(plano, "objeto", o["ini"], o["fim"], o["cx"] / W))
    for k, fr in enumerate(plano["frentes"]):
        w, h = _tam_frente(fr["arquivo"], W, H)
        png(f"afrente{k}", "🌿 frente", copiar(fr["arquivo"]), W / 2, H - h / 2 + H * 0.01, w, fr["ini"], fr["fim"], "frente",
            mov=movimento(plano, "frente", fr["ini"], fr["fim"]))
    for k, ds in enumerate(plano["destaques"]):
        png(f"adest{k}", "🌟 destaque", copiar(ds["arquivo"]), W / 2, H / 2, W, ds["ini"], ds["fim"], "destaque", trilha="destaque")
    for k, v in enumerate(plano["videos"]):  # 🎞 os momentos animados no Flow: o vídeo em tela cheia no lugar deles
        overlays.append({"id": f"avid{k}", "origem": "react_tela", "camada": "video", "nome_personagem": "🎞 momento animado",
                         "source": {"source": "local_file", "value": copiar(v["arquivo"]), "kind": "video"}, "media_type": "video",
                         "start": round(v["ini"], 3), "end": round(v["fim"], 3), "position": "top-right", "ancora": "centro",
                         "size_percent": 100.0, "x_percent": 50.0, "y_percent": 50.0})
    lw = int(W * (0.82 if W > H else 0.9))
    for k, lg in enumerate(plano["legendas"]):
        cam, w_, h_ = R.desenhar_legenda(lg["nome"], lg["texto"], lg["cor"], lw, os.path.join(d, f"legenda_{k:03d}.png"),
                                         tam=36 if W > H else 44)
        cam, w_, h_ = R._legenda_na_tela(cam, lw)
        topo = H * (0.80 if W > H else 0.72)
        png(f"aleg{k:03d}", f"💬 {lg['nome']}", cam, W / 2, topo + h_ / 2, w_, lg["ini"], lg["fim"], "legenda",
            fala=lg["texto"], trilha="legenda")
    falas = [{"start": lg["ini"], "end": lg["fim"], "text": f"{lg['nome']}: {lg['texto']}"} for lg in plano["legendas"]]
    return {"audio": audio, "duracao": dur, "segmentos": segs, "overlays": overlays, "avisos": plano["avisos"], "falas": falas}


def _fundo_com_camera(cam: str, W: int, H: int, camera: str, prog: float):
    """O fundo como o editor mostra nesse ponto da cena (zoom 1→1,4 / pan com zoom 1,15) — pra prévia bater com o
    parallax das outras camadas."""
    from PIL import Image
    im = Image.open(cam).convert("RGBA")
    esc = max(W / im.width, H / im.height)
    im = im.resize((max(W, round(im.width * esc)), max(H, round(im.height * esc))), Image.LANCZOS)
    im = im.crop(((im.width - W) // 2, (im.height - H) // 2, (im.width - W) // 2 + W, (im.height - H) // 2 + H))
    prog = max(0.0, min(1.0, prog))
    z, fx = 1.0, 0.5
    if camera == "zoom_in":
        z = 1 + 0.4 * prog
    elif camera == "zoom_out":
        z = 1.4 - 0.4 * prog
    elif camera in ("pan_esq", "pan_dir"):
        z, fx = 1.15, (1 - prog) if camera == "pan_esq" else prog
    if z == 1.0:
        return im
    cw, ch = W / z, H / z
    x0, y0 = (W - cw) * fx, (H - ch) * 0.5
    return im.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch))).resize((W, H), Image.LANCZOS)


def previa(p: Dict[str, Any], base: str, destino: str, t: float, legenda: bool = True) -> str:
    """Uma imagem do episódio no segundo t (o fundo da cena, quem está em cena, o objeto, a frente, o destaque, a legenda)."""
    from PIL import Image, ImageOps
    plano = plano_de_camadas(p, base)
    W, H = plano["W"], plano["H"]
    f = next((x for x in plano["fundos"] if x["ini"] <= t < x["fim"]), plano["fundos"][-1] if plano["fundos"] else None)
    if f and f["arquivo"]:
        tela = _fundo_com_camera(f["arquivo"], W, H, f.get("camera") or "fixa", (t - f["ini"]) / max(0.001, f["fim"] - f["ini"]))
    else:
        tela = Image.open(_fundo_degrade(destino + ".fundo.png", W, H)).convert("RGBA")
        os.remove(destino + ".fundo.png")

    def colar(cam: str, cx: float, cy: float, w: float, esp: bool = False, camada: str = "", ini: float = 0, fim: float = 0) -> None:
        if camada:  # 🌄 onde a camada está nesse segundo (parallax / tremida)
            ox, oy = deslocamento(movimento(plano, camada, ini, fim, cx / W), t, W, H)
            cx, cy = cx + ox, cy + oy
        im = Image.open(cam).convert("RGBA")
        h = w * im.height / im.width
        im = im.resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS)
        if esp:
            im = ImageOps.mirror(im)
        R._colar_cortando(tela, im, int(cx - w / 2), int(cy - h / 2))

    for c in p["personagens"]:
        for fg in plano["figs"]:
            if fg["cid"] != c["id"] or not (fg["ini"] <= t < fg["fim"]):
                continue
            img = next((im for a, b, im in _quadros(fg) if a <= t < b), fg["pose"])
            if fg.get("boca") and fg.get("fala") and fg["fala"][0] <= t < fg["fala"][1] and int((t - fg["ini"]) / 0.12) % 2:
                img = fg["boca"]
            iw, ih = R._tam(img, (2, 3))
            colar(img, fg["cx"], fg["base_y"] - fg["alt"] / 2, fg["alt"] * iw / ih, fg["espelhar"], "personagem", fg["ini"], fg["fim"])
    for o in plano["objetos"]:
        if o["ini"] <= t < o["fim"]:
            iw, ih = R._tam(o["arquivo"], (1, 1))
            colar(o["arquivo"], o["cx"], o["base_y"] - o["w"] * ih / iw / 2, o["w"], False, "objeto", o["ini"], o["fim"])
    for fr in plano["frentes"]:
        if fr["ini"] <= t < fr["fim"]:
            w, h = _tam_frente(fr["arquivo"], W, H)
            colar(fr["arquivo"], W / 2, H - h / 2 + H * 0.01, w, False, "frente", fr["ini"], fr["fim"])
    for ds in plano["destaques"]:
        if ds["ini"] <= t < ds["fim"]:
            colar(ds["arquivo"], W / 2, H / 2, W)
    lg = next((x for x in plano["legendas"] if x["ini"] <= t < x["fim"]), None) if legenda else None
    if lg:
        lw = int(W * (0.82 if W > H else 0.9))
        cam, w_, h_ = R.desenhar_legenda(lg["nome"], lg["texto"], lg["cor"], lw, destino + ".leg.png", tam=36 if W > H else 44)
        colar(cam, W / 2, H * (0.80 if W > H else 0.72) + h_ / 2, w_)
        os.remove(cam)
    tela.convert("RGB").save(destino, "JPEG", quality=88)
    return destino


# ------------------------------------------------------------------ pra página
def para_tela(p: Dict[str, Any], base: str = _BASE) -> Dict[str, Any]:
    out = dict(p)
    out["personagens"] = [dict(c, poses=estado_poses(c, base), usadas=list(poses_usadas(p, c["id"])), aprovar=precisa_aprovar(c))
                          for c in p["personagens"]]
    tl = linha_do_tempo(p, base)
    out["duracao"] = tl["duracao"]
    out["tl"] = [{"id": s["id"], "ini": s["ini"], "fim": s["fim"],
                  "momentos": {m["id"]: [m["ini"], m["fim"]] for m in s["momentos"]}} for s in tl["cenas"]]
    out["ia"] = ia_ligada()
    out["vozes_disponiveis"] = vozes_disponiveis()
    falas = [m for s in p["cenas"] for m in s.get("momentos") or [] if m["tipo"] in ("fala", "narracao")]
    out["vozes_estado"] = {"falas": len(falas), "com_audio": sum(1 for m in falas if (m.get("audio") or {}).get("arquivo"))}
    out["modo_audio"] = audio_ok(p, base)
    out["duracao_planejada"] = duracao_planejada(p)
    out["n_paginas"] = len(paginas_manga(p))
    return out
