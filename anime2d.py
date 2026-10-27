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
    "manga_cor": ("🖋🎨 Anime colorido com o traço do mangá", "colored anime adaptation that keeps the ORIGINAL MANGA ARTIST'S "
                  "drawing style exactly: the same hand-drawn loose ink linework with varied, slightly rough line weight, "
                  "hatching kept as texture in the shadows, the same character proportions and face shapes (as in the manga "
                  "references), flat muted colors laid under the black ink lines like a hand-colored manga page, soft limited "
                  "shading, subtle paper grain — NOT generic glossy anime"),
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
# 🚫🔤 nenhuma imagem gerada leva texto — principalmente na adaptação de mangá, em que as referências (recortes das
# páginas) têm balões, onomatopeias e caixas de narração: o texto fica na legenda/voz, nunca desenhado na imagem
SEM_TEXTO = ("ABSOLUTELY NO TEXT in the image: no letters, no words, no speech balloons, no thought bubbles, no sound-effect "
             "onomatopoeia lettering, no captions, no narration boxes, no signs or labels with writing, no watermark. If the "
             "reference images contain speech balloons, lettering or sound effects, do NOT copy them.")


def regra_texto(texto: str = "") -> str:
    """🔤 v84_238: o texto que FAZ PARTE da cena (a etiqueta da pasta, o bilhete) é escrito — exatamente; o resto não."""
    texto = " ".join(str(texto or "").split())
    if not texto:
        return SEM_TEXTO
    return (f"The ONLY writing in the image is this text, spelled EXACTLY like this, clearly legible, drawn as part of the "
            f"scene (on the paper / label / sign): {texto}. No speech balloons, no thought bubbles, no sound-effect "
            "lettering, no captions, no other words. If the reference images contain speech balloons or lettering, do NOT "
            "copy them.")
TIPOS_MOMENTO = ("fala", "narracao", "acao", "destaque")
# 🎥 v84_238: enquadramento de cada momento (o "plano" da câmera, como num anime): geral = o cenário todo; medio = da
# cintura pra cima de quem está em foco; close = o rosto (usa o 🙂 busto do personagem); reacao = o rosto num fundo
# abstrato (linhas de velocidade, brilho, sombrio, impacto) pras reações cômicas
PLANOS = {"geral": "🏞 geral", "medio": "🧍 médio", "close": "🙂 close", "reacao": "💥 reação"}
FUNDOS_REACAO = {"linhas": "⚡ linhas de velocidade", "brilho": "✨ brilho", "sombrio": "🌧 sombrio", "impacto": "💥 impacto"}
POSES_MOVIMENTO = ("andando", "correndo", "pulando")  # sem o quadro "piscando" (o personagem está em movimento)
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
    p.setdefault("cobertura", True)
    p.setdefault("troca_angulo_s", 10)  # 🎥 troca de ângulo sozinha depois de N s no mesmo (0 = não troca)  # 🎬 fala longa vira cortes (quem fala / quem escuta / aberto)
    p.setdefault("motor_perfil", "xtts")
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
    if (p.get("manga") or {}).get("paginas") and (p.get("estilo") or "anime") in ("anime", "manga_cor", "manga_pb", "manga_tinta"):
        # 📖 adaptação de mangá: o traço é o do autor (rosto, olhos, proporções), não um anime genérico
        e += ("; FAITHFUL TO THE MANGA: copy the original artist's line art and character drawing style from the manga "
              "references (face shape, eye shape and pupils, nose, hair silhouette, body proportions)")
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
TIPOS_REF = {"personagem": "🧑 personagem", "cores": "🌈 cores reais (a versão COLORIDA de um personagem do mangá)",
             "local": "🏞 local", "item": "📦 item", "estilo": "🎨 estilo (o jeito de desenhar)"}


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
        if r["tipo"] == "cores":  # 🌈 a foto colorida: só as cores reais (não vira referência de forma)
            x = achar(p["personagens"], r.get("nome") or "") if r.get("nome") else None
            if x is not None:
                x["cor_ref"] = r["arquivo"]
            continue
        lista = {"personagem": p["personagens"], "local": p["locais"], "item": p["itens"]}.get(r["tipo"])
        if lista is None or not r.get("nome"):
            continue
        x = achar(lista, r["nome"])
        if x is not None and r["arquivo"] not in (x.setdefault("refs", [])):
            x["refs"].append(r["arquivo"])


def refs_de(p: Dict[str, Any], x: Dict[str, Any], base: str = _BASE) -> List[str]:
    return [os.path.join(pasta(p["id"], base), "refs", a) for a in x.get("refs") or []
            if os.path.isfile(os.path.join(pasta(p["id"], base), "refs", a))]


def cor_ref(p: Dict[str, Any], c: Dict[str, Any], base: str = _BASE) -> Optional[str]:
    """🌈 A foto colorida do personagem (opcional — pras cores reais quando a referência é mangá P&B)."""
    a = c.get("cor_ref")
    cam = os.path.join(pasta(p["id"], base), "refs", a) if a else None
    return cam if cam and os.path.isfile(cam) else None


def guardar_cor_ref(p: Dict[str, Any], c: Dict[str, Any], nome_arq: str, dados: bytes, base: str = _BASE) -> Dict[str, Any]:
    """🌈 Troca a foto colorida do personagem (a anterior sai)."""
    tirar_cor_ref(p, c, base)
    r = guardar_referencia(p, nome_arq, dados, "cores", c["nome"], "a versão colorida (só as cores)", base)
    c["cor_ref"] = r["arquivo"]
    return r


def tirar_cor_ref(p: Dict[str, Any], c: Dict[str, Any], base: str = _BASE) -> None:
    a = c.pop("cor_ref", None)
    if not a:
        return
    p["referencias"] = [r for r in p["referencias"] if r["arquivo"] != a]
    try:
        os.remove(os.path.join(pasta(p["id"], base), "refs", a))
    except OSError:
        pass


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


# 🪑 v84_238: os MÓVEIS em que os personagens sentam/se apoiam são camadas separadas (props) — o fundo vem sem eles —
# pra dar profundidade (cadeira ATRÁS do personagem, mesa NA FRENTE) e não mudarem de cena pra cena; e os LUGARES do
# cenário (onde cada um fica em pé ou sentado)
import anime2d_planta as _PL  # noqa: E402 — 📐 a planta do cenário (layout)

SCHEMA_LOCAL = {
    "type": "object", "additionalProperties": False,
    "required": ["nome", "descricao", "prompt_en", "frente_en", "props", "lugares", "planta", "angulo_de", "angulo_en", "variante_de"],
    "properties": {"nome": {"type": "string"}, "descricao": {"type": "string"}, "prompt_en": {"type": "string"},
                   "frente_en": {"type": "string"},
                   "planta": _PL.SCHEMA_PLANTA, "angulo_de": {"type": "string"}, "angulo_en": {"type": "string"},
                   "variante_de": {"type": "string"},
                   "props": {"type": "array", "items": {
                       "type": "object", "additionalProperties": False, "required": ["nome", "prompt_en", "camada"],
                       "properties": {"nome": {"type": "string"}, "prompt_en": {"type": "string"},
                                      "camada": {"type": "string", "enum": ["atras", "frente"]}}}},
                   "lugares": {"type": "array", "items": {
                       "type": "object", "additionalProperties": False, "required": ["nome", "sentado", "corpo", "descricao"],
                       "properties": {"nome": {"type": "string"}, "sentado": {"type": "boolean"},
                                      "corpo": {"type": "string", "enum": ["inteiro", "cintura"]},
                                      "descricao": {"type": "string"}}}}}}
# 🌟 itens: quem aparece neles (a referência dos designs vai junto) e o texto ESCRITO que faz parte da piada
SCHEMA_ITEM = {
    "type": "object", "additionalProperties": False, "required": ["nome", "tipo", "prompt_en", "personagens", "texto", "onde"],
    "properties": {"nome": {"type": "string"}, "tipo": {"type": "string", "enum": ["objeto", "destaque"]},
                   "prompt_en": {"type": "string"}, "personagens": {"type": "array", "items": {"type": "string"}},
                   "texto": {"type": "string"}, "onde": {"type": "string"}}}

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
        "locais": {"type": "array", "items": SCHEMA_LOCAL},
        "itens": {"type": "array", "items": SCHEMA_ITEM},
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
        "- locais.props: os MÓVEIS/objetos grandes em que os personagens sentam, se apoiam ou ficam atrás (mesa, cadeira, "
        "balcão, sofá) — cada um uma imagem separada ('prompt_en' em inglês, o objeto inteiro sozinho) com a 'camada': "
        "'atras' (atrás de quem está ali: cadeira, encosto) ou 'frente' (na frente: mesa, balcão); o 'prompt_en' descreve o "
        "LADO QUE A CÂMERA VÊ (a mesa de quem senta de frente pra câmera mostra o painel da FRENTE — gavetas e o vão das "
        "pernas ficam do outro lado, escondidos). Esses móveis NÃO vão no "
        "'prompt_en' do fundo (diga no fundo que aquele espaço está livre). locais.lugares: onde os personagens ficam (ex.: "
        "\"atrás da mesa\" sentado=true corpo=cintura, \"na porta\", \"perto da janela\") — além dos padrões "
        "esquerda/centro/direita; 'corpo' = 'cintura' quando um móvel da frente esconde as pernas.\n"
        + _PL.INSTRUCOES_IA +
        "- itens: 'personagens' = os NOMES de quem aparece na imagem (a referência do design deles vai junto, pra não mudar "
        "cabelo/cores); 'texto' = o texto ESCRITO que faz parte da cena e da piada (o que está numa placa, etiqueta, "
        "bilhete, quadro, tela — exatamente como deve aparecer; \"\" se nenhum); 'onde' (objeto) = em cima de qual móvel ou "
        "em qual lugar ele fica (\"\" = no chão perto de quem está em foco). Nunca balões nem onomatopeias.\n"
        "- 🎞 itens 'destaque' de EXEMPLO (cutaways, como num anime de comédia): quando alguém descreve uma situação ou "
        "conta algo (\"sou baixinho e todo mundo me ignora\"), crie um destaque que MOSTRA isso, mesmo que não esteja na "
        "história (o personagem minúsculo no meio de alunos gigantes na aula de educação física); e imagens "
        "CINEMATOGRÁFICAS pros momentos fortes (a saída decidida, a revelação).\n"
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


def _txt(v: Any, n: int = 900) -> str:
    return " ".join(str(v or "").split())[:n]


def aplicar_props_lugares(lo: Dict[str, Any], x: Dict[str, Any]) -> None:
    """🪑 Os móveis (camadas separadas) e os lugares do cenário que vieram da IA/zip — junta pelo nome."""
    if x.get("variante_de") is not None:  # 🌫 o mesmo cenário em outro estado (usa o fundo e os móveis do original)
        lo["variante_de"] = _txt(x.get("variante_de"), 80)
    if x.get("angulo_de") is not None:  # 🎥 o mesmo cômodo visto de OUTRA câmera (planta, lugares e chão próprios)
        lo["angulo_de"] = _txt(x.get("angulo_de"), 80)
    for k in ("angulo_en", "angulo"):
        if x.get(k) is not None:
            lo[k] = _txt(x.get(k), 300)
    if isinstance(x.get("planta"), dict):  # 📐 o layout do cenário (onde fica cada coisa)
        import anime2d_planta as PL
        pl = PL.normalizar(x["planta"])
        if pl:
            lo["planta"] = pl
    props = lo.setdefault("props", [])
    for y in x.get("props") or []:
        if not isinstance(y, dict) or not _txt(y.get("nome")):
            continue
        pr = next((z for z in props if R._norm(z["nome"]) == R._norm(y["nome"])), None)
        if pr is None:
            pr = {"id": _id("p"), "nome": _txt(y["nome"], 60), "img": {}, "camada": "frente"}
            props.append(pr)
        if _txt(y.get("prompt_en")):
            pr["prompt_en"] = _txt(y["prompt_en"])
        if y.get("camada") in ("atras", "frente"):
            pr["camada"] = y["camada"]
        for k in ("x", "y", "w", "real"):
            if isinstance(y.get(k), (int, float)):
                pr[k] = round(float(y[k]), 4)
        if isinstance(y.get("w"), (int, float)):
            pr["w_manual"] = True
    lug = lo.setdefault("lugares", [])
    for y in x.get("lugares") or []:
        if not isinstance(y, dict) or not _txt(y.get("nome")):
            continue
        lg = next((z for z in lug if R._norm(z["nome"]) == R._norm(y["nome"])), None)
        if lg is None:
            lg = {"nome": _txt(y["nome"], 40)}
            lug.append(lg)
        if "sentado" in y:
            lg["sentado"] = bool(y["sentado"])
        if _txt(y.get("descricao")):
            lg["descricao"] = _txt(y["descricao"], 200)
        for k in ("x", "y", "escala"):
            if isinstance(y.get(k), (int, float)):
                lg[k] = round(float(y[k]), 4)
        if y.get("corpo") in ("inteiro", "cintura"):
            lg["corpo"] = y["corpo"]
        if y.get("prop"):
            lg["prop"] = _txt(y["prop"], 60)
    if isinstance(x.get("chao"), dict):
        ch = {k: round(float(v), 4) for k, v in x["chao"].items() if k in ("y", "alt", "y_fundo", "esc_fundo") and isinstance(v, (int, float))}
        area = x["chao"].get("area")
        if isinstance(area, list) and len(area) >= 3:
            ch["area"] = [[round(float(q[0]), 4), round(float(q[1]), 4)] for q in area if isinstance(q, (list, tuple)) and len(q) == 2][:10]
        lo["chao"] = ch
    if lo.get("planta"):
        import anime2d_planta as PL
        PL.sincronizar_moveis(lo)


def aplicar_item_extras(p: Dict[str, Any], it: Dict[str, Any], x: Dict[str, Any]) -> None:
    """🌟 Quem aparece no item (os nomes) e o texto escrito que faz parte da cena."""
    if isinstance(x.get("personagens"), list):
        it["personagens"] = [c["nome"] for c in (achar(p["personagens"], n) for n in x["personagens"]) if c] or \
            [_txt(n, 60) for n in x["personagens"] if _txt(n)]
    if x.get("texto") is not None:
        it["texto"] = _txt(x.get("texto"), 300)
    if x.get("onde") is not None:  # 📦 o objeto fica em cima de qual móvel / em qual lugar
        it["onde"] = _txt(x.get("onde"), 60)
    if x.get("painel") is not None:
        it["painel"] = bool(x.get("painel"))


def escala_em(lo: Optional[Dict[str, Any]], y: float) -> float:
    """📏 A escala pela PERSPECTIVA do chão: 1 no chão da frente (chao.y), esc_fundo no fundo (chao.y_fundo)."""
    ch = (lo or {}).get("chao") or {}
    yf, y0 = ch.get("y_fundo"), float(ch.get("y") or 0.97)
    if yf is None or y0 - float(yf) < 0.02:
        return 1.0
    t = max(0.0, min(1.2, (float(y) - float(yf)) / (y0 - float(yf))))
    return round(float(ch.get("esc_fundo") or 0.6) + (1 - float(ch.get("esc_fundo") or 0.6)) * t, 4)


def area_livre(lo: Optional[Dict[str, Any]]) -> Optional[List[List[float]]]:
    a = ((lo or {}).get("chao") or {}).get("area")
    return a if isinstance(a, list) and len(a) >= 3 else None


def dentro(area: List[List[float]], x: float, y: float) -> bool:
    d = False
    for i in range(len(area)):
        (x1, y1), (x2, y2) = area[i], area[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-9) + x1:
            d = not d
    return d


def lugares_do_local(p: Dict[str, Any], lo: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """nome → {x, y (onde ficam os pés; na 'cintura' = a linha da cintura), escala, sentado, corpo}: os 5 padrões
    (espalhados DENTRO da área livre do chão, se houver) + os do cenário (📐 Montar o cenário). A escala vem da
    perspectiva do chão quando o lugar não tem uma escolhida."""
    lo = layout_do_local(p, lo)  # 🌫 variante → os lugares do original
    chao = (lo or {}).get("chao") or {}
    y0 = float(chao.get("y") or 0.97)
    area = area_livre(lo)
    pad = {}
    for k, v in POSICOES.items():
        x, y = v, y0
        if area:  # 👣 os padrões ficam no chão livre (perto da frente), não em cima de armário/mesa
            ys = [q[1] for q in area]
            y = max(ys) - (max(ys) - min(ys)) * 0.12
            xs = [q[0] for q in area]
            x = min(xs) + (max(xs) - min(xs)) * (0.08 + 0.84 * (v - 0.16) / 0.68)
            for _ in range(12):
                if dentro(area, x, y):
                    break
                y -= (max(ys) - min(ys)) * 0.06
        pad[k] = {"nome": k, "x": round(x, 4), "y": round(y, 4), "escala": escala_em(lo, y), "sentado": False, "padrao": True,
                  "corpo": "inteiro"}
    out = dict(pad)
    tem_frente = any(pr.get("camada") != "atras" for pr in (lo or {}).get("props") or [])
    for lg in (lo or {}).get("lugares") or []:
        k = lg.get("nome")
        if not k:
            continue
        base = out.get(k, {"x": 0.5, "y": y0 if not lg.get("sentado") else y0 - 0.12, "sentado": False})
        y = float(lg.get("y", base["y"]))
        sent = bool(lg.get("sentado", base.get("sentado")))
        corpo = lg.get("corpo") or ("cintura" if sent and tem_frente else "inteiro")
        esc = lg.get("escala")
        out[k] = {"nome": k, "x": float(lg.get("x", base["x"])), "y": y,
                  "escala": float(esc) if isinstance(esc, (int, float)) else (1.0 if corpo == "cintura" else escala_em(lo, y)),
                  "sentado": sent, "corpo": corpo, "descricao": lg.get("descricao") or "", "prop": lg.get("prop") or "",
                  "padrao": k in POSICOES}
    return out


def chave_pose(lug: Dict[str, Any], e: Dict[str, Any], po: Optional[str] = None, en: Optional[str] = None) -> str:
    """O nome da imagem da pose: atrás da mesa/balcão (lugar 'cintura') usa a versão DA CINTURA PRA CIMA ('meio_…') — a
    mesa esconde as pernas e o Flow não inventa ninguém sentado no chão."""
    k = nome_pose(e["pose"] if po is None else po, (e.get("pose_en") or "") if en is None else en)
    v = lug.get(e.get("posicao")) or {}
    if v.get("corpo") == "cintura" and not k.startswith(("busto_", "meio_")) and k not in POSES_MOVIMENTO:
        return "meio_" + k
    return k


SCHEMA_LAYOUT = {
    "type": "object", "additionalProperties": False,
    "required": ["chao_y", "altura_em_pe", "chao_fundo_y", "escala_fundo", "area_livre", "lugares", "props"],
    "properties": {
        "chao_y": {"type": "number"}, "altura_em_pe": {"type": "number"},
        "chao_fundo_y": {"type": "number"}, "escala_fundo": {"type": "number"},
        "area_livre": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
        "lugares": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                               "required": ["nome", "x", "y", "escala", "sentado", "corpo"],
                                               "properties": {"nome": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"},
                                                              "escala": {"type": "number"}, "sentado": {"type": "boolean"},
                                                              "corpo": {"type": "string", "enum": ["inteiro", "cintura"]}}}},
        "props": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["nome", "x", "y", "largura_m"],
                                             "properties": {"nome": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"},
                                                            "largura_m": {"type": "number"}}}}}}


def ajustar_cenario(pid: str, lid: str, base: str = _BASE) -> str:
    """📐 A IA olha o fundo e diz onde fica o chão, a altura de uma pessoa em pé ali (perspectiva), onde cada LUGAR fica
    (x/y dos pés, escala, sentado) e onde vai cada MÓVEL — tudo em frações da tela. Você ajusta no 📐 depois."""
    import base64
    import io
    from PIL import Image
    p = carregar(pid, base)
    lo = next((x for x in p["locais"] if x["id"] == lid), None)
    if not lo:
        raise AnimeErro("Local não encontrado.")
    cam = arquivo_img(p, lo.get("img") or {}, base)
    if not cam:
        raise AnimeErro("Gere (ou envie) o fundo deste local antes.")
    im = Image.open(cam).convert("RGB")
    im.thumbnail((1280, 1280))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    lug = lugares_do_local(p, lo)
    props = lo.get("props") or []
    txt = (f"FUNDO do lugar “{lo['nome']}” ({lo.get('descricao') or ''}). Proporção do vídeo: {p.get('proporcao')}.\n"
           "LUGARES (onde os personagens ficam): " + "; ".join(f"{n}" + (" [SENTADO]" if v["sentado"] else "") + (f" — {v['descricao']}" if v.get("descricao") else "")
                                                               for n, v in lug.items()) + "\n"
           "MÓVEIS (camadas separadas que vão por cima do fundo): " + ("; ".join(f"{x['nome']} ({'atrás' if x.get('camada') == 'atras' else 'na frente'} do personagem)"
                                                                                 for x in props) or "(nenhum)"))
    sis = ("Você posiciona as camadas de um anime 2D montado com recortes. Olhe o fundo e responda em FRAÇÕES da imagem "
           "(x: 0 = esquerda, 1 = direita; y: 0 = topo, 1 = base). chao_y = a linha do chão mais perto da câmera (onde pisam "
           "os pés de quem está na frente); altura_em_pe = a altura (fração da altura da imagem) de um adulto em pé nesse "
           "chão da frente, coerente com a perspectiva (portas ~2 m, janelas, móveis); chao_fundo_y = a linha onde o chão "
           "encontra a parede do fundo e escala_fundo = o tamanho de uma pessoa lá (fração da da frente). area_livre = o "
           "polígono (4–6 pontos [x,y]) do CHÃO LIVRE onde dá pra ficar em pé e andar — sem armários, estantes, mesas, "
           "paredes. Pra CADA lugar: x e y = onde ficam os PÉS (dentro da área livre), escala (pela distância), sentado, "
           "corpo ('cintura' = atrás de uma mesa/balcão: y = a linha da cintura, logo abaixo do tampo da mesa; 'inteiro' = "
           "o resto). Os padrões (esquerda, centro_esq, centro, centro_dir, direita) espalhados DENTRO da área livre. Pra "
           "cada MÓVEL: x = o centro, y = a BASE (onde ele toca o chão), largura_m = a largura real em metros (mesa ~1.4, "
           "cadeira ~0.6) — a cadeira atrás e a mesa na frente de quem senta ali.")
    conteudo = [{"type": "text", "text": txt},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b.getvalue()).decode()}}]
    r = _ia().chamar("anime2d", sis, conteudo, schema=SCHEMA_LAYOUT, max_tokens=2500, effort="medium", timeout=180, cache_local=False)
    if not isinstance(r, dict):
        raise AnimeErro("A IA não respondeu — arraste os lugares e os móveis à mão no 📐 Montar o cenário.")
    with _TRAVA:
        p = carregar(pid, base)
        lo = next((x for x in p["locais"] if x["id"] == lid), None)
        lo["chao"] = {"y": max(0.4, min(1.05, float(r.get("chao_y") or 0.97))), "alt": max(0.15, min(1.2, float(r.get("altura_em_pe") or 0.62))),
                      "y_fundo": max(0.2, min(1.0, float(r.get("chao_fundo_y") or 0.7))), "esc_fundo": max(0.2, min(1.0, float(r.get("escala_fundo") or 0.6)))}
        if isinstance(r.get("area_livre"), list) and len(r["area_livre"]) >= 3:
            lo["chao"]["area"] = [[round(max(0.0, min(1.0, float(q[0]))), 4), round(max(0.0, min(1.1, float(q[1]))), 4)]
                                  for q in r["area_livre"] if isinstance(q, list) and len(q) == 2][:10]
        lgs = []
        for y in r.get("lugares") or []:
            if isinstance(y, dict) and _txt(y.get("nome")):
                lgs.append({"nome": _txt(y["nome"], 40), "x": max(0.0, min(1.0, float(y.get("x") or 0.5))),
                            "y": max(0.2, min(1.1, float(y.get("y") or 0.97))), "escala": max(0.2, min(2.0, float(y.get("escala") or 1))),
                            "sentado": bool(y.get("sentado")), "corpo": y.get("corpo") if y.get("corpo") in ("inteiro", "cintura") else "inteiro",
                            "descricao": (next((z for z in lo.get("lugares") or [] if R._norm(z.get("nome")) == R._norm(y["nome"])), {}) or {}).get("descricao", "")})
        if lgs:
            lo["lugares"] = lgs
        for y in r.get("props") or []:
            pr = next((z for z in lo.get("props") or [] if isinstance(y, dict) and R._norm(z["nome"]) == R._norm(y.get("nome"))), None)
            if pr:
                pr.update(x=round(float(y.get("x") or 0.5), 4), y=round(float(y.get("y") or 1.0), 4))
                if isinstance(y.get("largura_m"), (int, float)) and y["largura_m"] > 0:
                    pr["real"] = round(float(y["largura_m"]), 3)
                    pr.pop("w_manual", None)
        log(p, f"📐 {lo['nome']}: a IA posicionou {len(lgs)} lugar(es) e {len(r.get('props') or [])} móvel(is)")
        salvar(p, base)
    return f"{len(lgs)} lugar(es)"


def local_da_cena(p: Dict[str, Any], s: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return next((x for x in p["locais"] if x["id"] == s.get("local")), None)


def base_do_local(p: Dict[str, Any], lo: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """🌫 v84_238e: o local é uma VARIANTE de outro (o mesmo quarto cheio de fumaça, de noite, destruído…) → o original."""
    n = R._norm((lo or {}).get("variante_de") or "")
    if not n:
        return None
    return next((x for x in p["locais"] if x is not lo and (R._norm(x["nome"]) == n or x["id"] == lo.get("variante_de"))), None)


def angulo_base(p: Dict[str, Any], lo: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """🎥 o local é um ÂNGULO de outro (o mesmo cômodo, outra câmera) → o principal."""
    n = R._norm((lo or {}).get("angulo_de") or "")
    if not n:
        return None
    return next((x for x in p["locais"] if x is not lo and (R._norm(x["nome"]) == n or x["id"] == lo.get("angulo_de"))), None)


def familia_do_local(p: Dict[str, Any], lo: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """O local, os ângulos e as variantes dele (o mesmo cômodo) — o que um momento pode usar como 'angulo'."""
    if not lo:
        return []
    raiz = lo
    for _ in range(4):
        b = base_do_local(p, raiz) or angulo_base(p, raiz)
        if not b:
            break
        raiz = b
    fam, novos = [raiz], [raiz]
    while novos:
        n = novos.pop()
        for x in p["locais"]:
            if x not in fam and (base_do_local(p, x) is n or angulo_base(p, x) is n):
                fam.append(x)
                novos.append(x)
    return fam


def local_do_momento(p: Dict[str, Any], s: Dict[str, Any], m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """🎥 O cenário do momento: o da cena, ou o 'angulo' escolhido (outro local do mesmo cômodo)."""
    lo = local_da_cena(p, s)
    a = m.get("angulo")
    if a:
        x = next((y for y in p["locais"] if y["id"] == a), None) or achar(p["locais"], a)
        if x:
            return x
    return lo


def layout_do_local(p: Dict[str, Any], lo: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """O local com o arranjo (móveis, lugares, chão) do original quando é uma variante — o mesmo cômodo, os mesmos
    móveis no mesmo lugar; só o fundo muda."""
    b = base_do_local(p, lo)
    if not b:
        return lo
    return dict(lo, props=b.get("props") or [], lugares=b.get("lugares") or [], chao=b.get("chao") or lo.get("chao") or {},
                planta=b.get("planta") or lo.get("planta"))


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
        aplicar_props_lugares(lo, x)
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
        aplicar_item_extras(p, it, x)
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
            "required": ["tipo", "quem", "texto", "pose", "pose_en", "em_cena", "camera", "plano", "foco", "fundo_reacao",
                         "destaque", "objeto", "duracao", "tempo", "som", "visao", "angulo"],
            "properties": {
                "tipo": {"type": "string", "enum": list(TIPOS_MOMENTO)}, "quem": {"type": "string"},
                "texto": {"type": "string"}, "pose": {"type": "string", "enum": poses}, "pose_en": {"type": "string"},
                "em_cena": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                       "required": ["personagem", "posicao", "pose", "pose_en", "olha", "poses_seguintes"],
                                                       "properties": {"personagem": {"type": "string"},
                                                                      "posicao": {"type": "string"},
                                                                      "pose": {"type": "string", "enum": poses},
                                                                      "pose_en": {"type": "string"},
                                                                      "olha": {"type": "string", "enum": ["direita", "esquerda"]},
                                                                      "poses_seguintes": {"type": "array", "items": {"type": "string"}}}}},
                "camera": {"type": "string", "enum": list(CAMERAS)}, "plano": {"type": "string", "enum": list(PLANOS)},
                "foco": {"type": "string"}, "fundo_reacao": {"type": "string", "enum": list(FUNDOS_REACAO) + [""]},
                "destaque": {"type": "string"},
                "objeto": {"type": "string"}, "duracao": {"type": "number"}, "tempo": {"type": "number"},
                "som": {"type": "string"}, "visao": {"type": "string"}, "angulo": {"type": "string"}}}}},
    }


def sys_cena(p: Dict[str, Any]) -> str:
    return (
        "Você é diretor de ANIME e escreve UMA CENA de um anime 2D montado com imagens (como uma série de TV de comédia, "
        "tipo Jashin-chan Dropkick): personagens recortados em poses sobre os cenários, com móveis em camadas, câmera que "
        "CORTA entre planos (geral, médio, close, reação), poses que mudam com a emoção, boca que mexe na fala. A cena vira "
        "uma lista de MOMENTOS (cada momento = um corte de câmera), em ordem. RITMO de comédia de TV: cortes curtos "
        "(~2 s; nenhum plano parado mais de ~3 s — fala comprida vira 2 momentos, e a reação de quem escuta ganha o seu "
        "corte), exagero nas reações (pose nova + plano 'reacao' ou câmera 'tremida' no susto/impacto), gente ENTRANDO e "
        "SAINDO de cena andando, e um momento de 'destaque' (cutaway/imagem hipotética) quando a fala descreve algo que "
        "dá pra mostrar. Pense como LAYOUT de anime: a PLANTA do cenário (abaixo) diz onde fica cada coisa; pra cada "
        "momento decida o que o PÚBLICO VÊ — 'visao' = o que está no quadro e o que fica de fora (ex.: \"médio dela na "
        "poltrona; a fornalha fora de quadro à direita, só a fumaça entrando pelo canto\") — e se precisa de OUTRO ÂNGULO "
        "do cômodo ('angulo' = o nome de um dos ângulos listados; \"\" = a câmera principal — sem 'angulo' a câmera já troca "
        "sozinha a cada ~10 s pra um ângulo que condiz; use 'angulo' quando o momento PRECISA de um, ex.: a ação no canto da "
        "fornalha). Os personagens ficam nos "
        "LUGARES do ângulo usado e nunca atravessam um objeto da planta:\n"
        "- tipo 'fala' (um personagem fala — 'quem' = o nome EXATO dele, 'texto' = só o que ele diz, curto: até ~25 "
        "palavras), 'narracao' (o narrador conta — 'quem' = \"Narrador\"; use só quando a história precisa), 'acao' (algo "
        "acontece sem fala: alguém entra correndo, cai, sai; 'texto' = descrição curta pro editor, 'duracao' em segundos "
        "1–4) e 'destaque' (uma imagem de destaque em TELA CHEIA por uns segundos — close de reação exagerada, plano "
        "detalhe, flashback; 'destaque' = o NOME do item 'destaque' da lista; 'duracao' 1.5–4).\n"
        "- 'em_cena' = TODOS que estão no cenário nesse momento (mesmo que o plano mostre só um), cada um com 'posicao' = "
        "um dos LUGARES do cenário (a lista vem com a cena; os 'sentado' são onde se senta — atrás da mesa, no sofá — e aí "
        "a pose tem que ser sentada: 'sentado' ou 'outra' com pose_en de alguém sentado; não ponha dois no mesmo lugar), "
        "'pose' e pra onde 'olha' (normalmente pra quem fala). Quem muda de lugar ANDA até lá sozinho (a animação faz); "
        "quem entra no meio da cena entra andando. 'poses_seguintes' = poses em sequência DENTRO do momento (a ação "
        "acontecendo: [\"raising the paper\", \"slamming the paper on the desk\"]; catálogo ou inglês curto; [] se não "
        "muda). 'pose' do momento = a pose de quem fala/age.\n"
        "- 🎥 'plano': 'geral' (o cenário todo — abre a cena, entradas, quem anda), 'medio' (da cintura pra cima de quem "
        "está em 'foco' — o diálogo normal), 'close' (o rosto do 'foco' — emoção, fala importante), 'reacao' (o rosto do "
        "'foco' num fundo abstrato — 'fundo_reacao': linhas = susto/empolgação, brilho = fofo/feliz, sombrio = deprê/"
        "vergonha, impacto = choque/grito). 'foco' = o NOME do personagem que a câmera enquadra (normalmente quem fala). "
        "CORTE como num anime: varie os planos, close nas reações, reacao nos momentos cômicos, geral pra situar — "
        "nunca a cena inteira no mesmo plano.\n"
        f"- 'pose': use o catálogo ({', '.join(POSES)}); poses de movimento (andando, correndo, acenando, rindo, pulando, "
        "comendo, bravo, assustado) já têm 2 quadros. Use 'outra' + 'pose_en' (em inglês, curta) SÓ se precisar de uma "
        "pose específica que não está no catálogo. Varie as poses conforme a emoção — é o que dá vida. Nada de móveis "
        "na pose (a cadeira e a mesa são do cenário).\n"
        "- 'camera': fixa, zoom_in (tensão/revelação), zoom_out, pan_esq, pan_dir, tremida (susto/impacto).\n"
        "- 'objeto': o nome de um item 'objeto' que aparece em cena nesse momento (\"\" se nenhum).\n"
        "- 'destaque' também vale numa 'fala'/'narracao': a imagem em tela cheia aparece ENQUANTO a voz fala (a "
        "imagem cinematográfica durante a narração, o exemplo/cutaway enquanto o personagem descreve a situação). Use os "
        "destaques de exemplo da lista sempre que alguém descreve algo.\n"
        "- Humor de timing: reações, silêncio constrangedor (acao com duracao), quebra de expectativa com destaque.\n"
        "- 'som': o efeito sonoro do momento, curto, em português (ex.: \"porta rangendo\", \"soco\", \"mastigando\") ou \"\" "
        "— por enquanto só anotado (a busca de efeitos vem depois).\n"
        "- 📖 Se vierem PÁGINAS DE MANGÁ: adapte ESSAS páginas, na ordem de leitura do mangá (quadros da DIREITA pra "
        "esquerda, de cima pra baixo; balões na mesma ordem). Cada balão = uma 'fala' de quem fala (texto do balão, sem "
        "inventar); caixas de texto/narração = 'narracao'; quadro sem fala = 'acao' ou 'destaque'; onomatopeias "
        "(SFX desenhados) = 'som'. Um close dramático/impacto do quadro = 'camera' zoom_in/tremida. Mantenha o ritmo do mangá.\n"
        "- 🎬 Se vierem QUADROS DE UM VÍDEO de referência (com o segundo de cada um): recrie a cena do vídeo com os "
        "PERSONAGENS DO PROJETO (siga as instruções do usuário sobre quem é quem): cada corte/enquadramento do vídeo vira um "
        "momento com o 'plano' parecido (aberto = geral, da cintura = medio, rosto = close), a mesma ação, pose, direção do "
        "olhar, quem entra/sai e onde cada um está; as falas vêm da transcrição (modo áudio: 'tempo' = o segundo).\n"
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
    L.append("ITENS: " + ("; ".join(f"{i['nome']} ({i.get('tipo')}" + (f", escrito: “{i['texto']}”" if i.get("texto") else "") + ")"
                                    for i in p["itens"]) or "(nenhum)"))
    lug = lugares_do_local(p, lo)
    pl_txt = _PL.descricao_pt((layout_do_local(p, lo) or {}).get("planta") or (lo or {}).get("planta"))
    angs = [x for x in familia_do_local(p, lo) if x is not lo and angulo_base(p, x) is not None]
    L += ["", f"## CENA {k + 1} DE {len(p['cenas'])}: {s['titulo']}", f"Local: {lo['nome'] if lo else '?'} — {(lo or {}).get('descricao') or ''}",
          "📐 PLANTA (câmera principal): " + (pl_txt or "(sem planta — use a descrição)"),
          "🎥 ÂNGULOS deste cômodo (use em 'angulo'): " + ("; ".join(
              f"{x['nome']} — {x.get('angulo') or x.get('angulo_en') or ''}; lugares: " + ", ".join(lugares_do_local(p, x))
              + (f"; planta: {_PL.descricao_pt(x.get('planta'))}" if x.get("planta") else "") for x in angs) or "(só a câmera principal)"),
          "LUGARES deste cenário (posicao): " + "; ".join(f"{n}" + (" [SENTADO]" if v["sentado"] else "") + (f" — {v['descricao']}" if v.get("descricao") else "")
                                                         for n, v in lug.items()),
          "Móveis (camadas): " + (", ".join(f"{x['nome']} ({'atrás' if x.get('camada') == 'atras' else 'na frente'} de quem está ali)"
                                            for x in (lo or {}).get("props") or []) or "(nenhum)"),
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
        if e_video(p):
            L.append(f"\n🎬 ESTA CENA RECRIA OS QUADROS {', '.join(rotulo_pagina(p, int(n))[2:] for n in s['paginas'])} DO VÍDEO DE "
                     "REFERÊNCIA (anexados, nessa ordem) — com OS PERSONAGENS DO PROJETO no lugar das pessoas do vídeo.")
        else:
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
    lug = lugares_do_local(p, local_da_cena(p, s))
    for x in r["momentos"]:
        m = limpar_momento(p, x, lug)
        if m:
            ms.append(m)
    if not ms:
        raise AnimeErro("Nenhum momento aproveitável (confira os nomes).")
    s["momentos"] = ms
    s["quando"] = time.time()
    log(p, f"🎬 cena {k + 1} ({s['titulo']}): {len(ms)} momento(s)")
    return len(ms)


def _pose_item(v: Any) -> Optional[Dict[str, str]]:
    """Uma pose de 'poses_seguintes' (catálogo, {"pose","pose_en"} ou um texto livre em inglês) → {"pose","pose_en"}."""
    if isinstance(v, dict):
        po = v.get("pose") if v.get("pose") in POSES or v.get("pose") == "outra" else ""
        en = _txt(v.get("pose_en"), 200)
        if po == "outra" and not en:
            return None
        return {"pose": po or ("outra" if en else "neutro"), "pose_en": en if (po or "outra") == "outra" else ""}
    t = _txt(v, 200)
    if not t:
        return None
    n = R._norm(t).replace(" ", "_")
    if n in POSES:
        return {"pose": n, "pose_en": ""}
    return {"pose": "outra", "pose_en": t}


def limpar_momento(p: Dict[str, Any], x: Any, lugares: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Um momento da IA/colado/editado → o formato do projeto (ids no lugar dos nomes). `lugares` = os do cenário."""
    if not isinstance(x, dict):
        return None
    ang = (next((y for y in p.get("locais") or [] if y["id"] == x.get("angulo")), None) or achar(p.get("locais") or [], x.get("angulo"))
           ) if x.get("angulo") else None
    if ang:  # 🎥 o momento usa outro ângulo do cômodo: os lugares são os dele
        lugares = lugares_do_local(p, ang)
    lugares = lugares or {k: {"sentado": False} for k in POSICOES}
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
        pos = y.get("posicao")
        if pos not in lugares:
            pos = next((q for q in lugares if R._norm(q) == R._norm(pos)), None) or next((q for q in POSICOES if q not in usadas), "centro")
        usadas.add(pos)
        po = y.get("pose") if y.get("pose") in POSES or y.get("pose") == "outra" else "neutro"
        seg = [z for z in (_pose_item(v) for v in (y.get("poses_seguintes") or y.get("poses") or [])[:6]) if z]
        em.append({"cid": c["id"], "posicao": pos, "pose": po, "pose_en": str(y.get("pose_en") or (pose_en if c["id"] == quem else ""))[:200],
                   "olha": "esquerda" if y.get("olha") == "esquerda" else "direita", "poses": seg})
    # quem fala/age está em cena com a pose do momento
    if quem not in ("", "narrador"):
        e = next((e for e in em if e["cid"] == quem), None)
        if e:
            if pose != "neutro" or e["pose"] == "neutro":
                e["pose"], e["pose_en"] = pose, pose_en or e.get("pose_en", "")
    dur = R.segundos(x.get("duracao")) or 0.0
    return {"id": str(x.get("id") or _id("m"))[:12], "tipo": tipo, "quem": quem, "texto": texto, "pose": pose, "pose_en": pose_en,
            "em_cena": em, "camera": x.get("camera") if x.get("camera") in CAMERAS else "fixa",
            "plano": x.get("plano") if x.get("plano") in PLANOS else "geral",
            "foco": (achar(p["personagens"], x.get("foco")) or {}).get("id", "") if x.get("foco") else "",
            "fundo_reacao": x.get("fundo_reacao") if x.get("fundo_reacao") in FUNDOS_REACAO else "",
            "destaque": (achar([i for i in p["itens"] if i.get("tipo") == "destaque"], x.get("destaque")) or {}).get("id", ""),
            "objeto": (achar([i for i in p["itens"] if i.get("tipo") == "objeto"], x.get("objeto")) or {}).get("id", ""),
            "duracao": round(max(0.0, min(15.0, dur)), 2), "som": " ".join(str(x.get("som") or "").split())[:200],
            "visao": " ".join(str(x.get("visao") or "").split())[:400], "angulo": ang["id"] if ang else "",
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
EXPRESSOES_BUSTO = ("neutro", "feliz", "rindo", "bravo", "triste", "chocado", "assustado", "pensativo", "envergonhado",
                    "convencido", "dormindo", "comendo")


def expressao_busto(pose: str) -> str:
    """O busto (close/reação) usa a expressão da pose (as de corpo — andando, sentado… — viram o rosto neutro)."""
    return pose if pose in EXPRESSOES_BUSTO else "neutro"


def foco_do_momento(m: Dict[str, Any]) -> str:
    em = [e["cid"] for e in m.get("em_cena") or []]
    if m.get("foco") and m["foco"] in em:
        return m["foco"]
    if m.get("quem") in em:
        return m["quem"]
    return em[0] if em else ""


def _sentado(p: Dict[str, Any], lug: Dict[str, Any], e: Dict[str, Any]) -> bool:
    v = lug.get(e.get("posicao")) or {}
    return bool(v.get("sentado")) or e.get("pose") == "sentado" or bool(re.search(r"\b(sit|sitting|seated)\b", e.get("pose_en") or "", re.I))


def poses_usadas(p: Dict[str, Any], cid: str) -> Dict[str, str]:
    """pose → prompt (em inglês) de tudo o que o roteiro pede pra esse personagem (+ neutro, a mestre): as poses do
    momento, as 'poses_seguintes', o 🙂 busto (close/reação) e 'andando' se ele muda de lugar/entra andando."""
    out: Dict[str, str] = {"neutro": POSES["neutro"][1]}

    def por(po: str, en: str, meio: bool = False) -> None:
        if po == "outra":
            en = (en or "").strip()
            if en:
                k, d = "x_" + R._slug(en)[:24], en
            else:
                return
        elif po in POSES:
            k, d = po, POSES[po][1]
        else:
            return
        out[("meio_" + k) if meio and k not in POSES_MOVIMENTO else k] = d
    for s in p["cenas"]:
        lug = lugares_do_local(p, local_da_cena(p, s))
        antes: Dict[str, str] = {}
        for j, m in enumerate(s.get("momentos") or []):
            agora = {}
            for e in m.get("em_cena") or []:
                agora[e["cid"]] = e["posicao"]
                if e["cid"] != cid:
                    continue
                meio = (lug.get(e.get("posicao")) or {}).get("corpo") == "cintura"
                por(e["pose"], e.get("pose_en") or "", meio)
                for z in e.get("poses") or []:
                    por(z.get("pose"), z.get("pose_en") or "", meio)
                if m.get("plano") in ("close", "reacao") and foco_do_momento(m) == cid:
                    ex = expressao_busto(e["pose"])
                    out["busto_" + ex] = POSES[ex][1]
                if m.get("tipo") != "destaque" and not _sentado(p, lug, e) and ((cid in antes and antes[cid] != e["posicao"])
                                                                                 or (cid not in antes and j > 0)):
                    out["andando"] = POSES["andando"][1]
            antes = agora
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


def e_video(p: Dict[str, Any]) -> bool:
    return (p.get("manga") or {}).get("fonte") == "video"


def rotulo_pagina(p: Dict[str, Any], n: int) -> str:
    """“📖 Página 3” (mangá) ou “🎬 Quadro 3 — 12.4 s” (os quadros de um vídeo de referência)."""
    if e_video(p):
        ts = (p.get("manga") or {}).get("tempos") or []
        return f"🎬 Quadro {n}" + (f" — {float(ts[n - 1]):.1f} s do vídeo" if 0 < n <= len(ts) else "")
    return f"📖 Página {n}"


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
        out.append({"type": "text", "text": rotulo_pagina(p, int(n))})
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


PROMPT_PISCA = ("Exactly the same image — same character, same pose, same framing, same size, same colors, same mouth — "
                "on a flat solid chroma-key green background (#00FF00). Change ONLY the eyes: CLOSED, in the middle of a blink.")


def poses_json(p: Dict[str, Any], c: Dict[str, Any]) -> Dict[str, Any]:
    sl = R._slug(c["nome"])
    aparencia = c.get("aparencia_en") or f"the character {c['nome']}"
    trava = (f"CHARACTER LOCK: {c['nome']}. Appearance: {aparencia}. Keep exactly the same face, hairstyle, hair color, eye "
             "color, body, outfit and colors in every image (follow the approved design reference).")
    estilo = "ART STYLE: " + estilo_en(p) + "."
    regras = ("ONE single figure, framed as the pose says, seen in a 3/4 view turned to the RIGHT side of the image, the "
              "whole figure inside the image with margin. NO furniture, NO chair, NO table, NO desk, NO floor, NO background "
              "objects (a sitting pose sits on NOTHING — an invisible CHAIR-HEIGHT seat: hips at knee height, thighs level, lower "
              "legs down to the feet; NEVER sitting on the floor or kneeling unless the pose says so; the furniture is a "
              "separate layer); a small "
              "handheld object only if the pose needs it. No panels, on a flat solid chroma-key green background (#00FF00), "
              "no shadow on the background. " + SEM_TEXTO)
    corpo = "FULL BODY from head to feet, feet at the bottom of the figure."
    poses = []
    for k, (nome, en) in enumerate(poses_usadas(p, c["id"]).items()):
        busto = nome.startswith("busto_")
        meio = nome.startswith("meio_")
        if busto:
            quadro = ("BUST SHOT: head, shoulders and chest only (cropped at mid-chest), big and detailed, facing the viewer "
                      "in 3/4 turned to the RIGHT. Expression: " + en + ".")
        elif meio:  # 🪑 atrás da mesa: da cintura pra cima, sentada numa cadeira (a mesa e a cadeira são do cenário)
            quadro = ("WAIST-UP SHOT, cropped at the waist: the character is SEATED on an office chair behind a desk, upper "
                      "body upright, facing the viewer (3/4 turned slightly to the RIGHT), arms and hands as described; do NOT "
                      f"draw the desk, the chair or the legs. Pose: {en}.")
        else:
            quadro = f"{en}. {corpo}"
        bnome = nome[6:] if busto else nome[5:] if meio else nome
        desc = (("🙂 busto " if busto else "🪑 da cintura pra cima — " if meio else "") +
                (POSES[bnome][0] if bnome in POSES else en))
        poses.append({"arquivo": f"{sl}_{nome}.png", "tipo": "pose", "prioridade": 1 if k < 5 else 2, "grupo": "anime2d",
                      "mestre": nome == "neutro", "descricao_pt": desc, "prompt": quadro})
        if nome in QUADRO_B:
            poses.append({"arquivo": f"{sl}_{nome}_b.png", "tipo": "pose", "prioridade": 2, "grupo": "anime2d",
                          "descricao_pt": desc + " — 2º quadro",
                          "prompt": f"Draw the NEXT FRAME of this motion: {QUADRO_B[nome]}. Same character, same framing and size.",
                          "pose_base": f"{sl}_{nome}.png", "edita_base": True})
        if nome not in POSES_MOVIMENTO:  # 😑 o quadro piscando (a animação pisca de vez em quando — sem loop)
            poses.append({"arquivo": f"{sl}_{nome}_pisca.png", "tipo": "pose", "prioridade": 3, "grupo": "anime2d",
                          "descricao_pt": desc + " — piscando", "prompt": PROMPT_PISCA, "pose_base": f"{sl}_{nome}.png",
                          "edita_base": True})
    refs = {os.path.basename(r): f"a reference picture of {c['nome']}" for r in c.get("refs") or []}
    if c.get("cor_ref"):
        refs[os.path.basename(c["cor_ref"])] = _pp().COR_REF_EN
        trava += " Use the COLORED reference for the exact real colors."
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
        cor = cor_ref(p, c, base)
        if cor:  # 🌈 a colorida logo depois do design (as cores reais)
            with open(cor, "rb") as f:
                refs.append((os.path.basename(cor), f.read()))
        for cam in refs_de(p, c, base)[:max(0, 3 - len(refs))]:
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
        so = [x["arquivo"] for x in proj["dados"]["poses"] if x.get("tipo") == "pose" and not x["arquivo"].endswith(("_b.png", "_pisca.png"))]
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
        if x.get("tipo") != "pose" or x["arquivo"].endswith(("_b.png", "_pisca.png")):
            continue
        cam = pp.arquivo_atual(proj, x["arquivo"], base)
        if not cam:
            continue
        nome = x["arquivo"][len(sl):-4] if x["arquivo"].startswith(sl) else x["arquivo"][:-4]
        b = pp.arquivo_atual(proj, x["arquivo"][:-4] + "_b.png", base)
        boca = next((y["arquivo"] for y in proj["dados"]["poses"] if y.get("tipo") == "boca" and y.get("base") == x["arquivo"]), None)
        out[nome] = {"pose": cam, "b": b, "boca": pp.arquivo_atual(proj, boca, base) if boca else None,
                     "pisca": pp.arquivo_atual(proj, x["arquivo"][:-4] + "_pisca.png", base)}
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
                      "img": (it["versoes"][it["atual"]]["local"] if it.get("atual", -1) >= 0 and it.get("versoes") else None),
                      "nver": len(it.get("versoes") or []), "atual": it.get("atual", -1)})
    poses = [i for i in itens if i["tipo"] == "pose"]
    return {"tem": True, "pid": pod["pid"], "mestre": bool(proj.get("mestre")), "prontas": sum(1 for i in poses if i["img"]),
            "total": len(poses), "bocas": sum(1 for i in itens if i["tipo"] == "boca" and i["img"]),
            "esperando": sum(1 for i in itens if i["estado"] in ("fila", "gerando")),
            "erros": sum(1 for i in itens if i["estado"] == "erro"), "itens": itens}


# ------------------------------------------------------------------ 🏞 4 · locais e itens (Flow em massa ou suas imagens)
def personagens_do_item(p: Dict[str, Any], it: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Quem aparece no item/destaque: os nomes da ficha, os citados no prompt e (destaque) quem está em cena no momento
    em que ele entra — pra a imagem vir com o MESMO design (cabelo, cores) dos personagens."""
    nomes: List[Dict[str, Any]] = []

    def add(c: Optional[Dict[str, Any]]) -> None:
        if c and c not in nomes:
            nomes.append(c)
    for n in it.get("personagens") or []:
        add(achar(p["personagens"], n))
    txt = R._norm((it.get("prompt_en") or "") + " " + it["nome"])
    for c in p["personagens"]:
        if R._norm(c["nome"]) and R._norm(c["nome"]) in txt:
            add(c)
    if it.get("tipo") == "destaque" and not it.get("personagens"):
        for s in p["cenas"]:
            ms = s.get("momentos") or []
            for j, m in enumerate(ms):
                if m.get("destaque") == it["id"]:
                    viz = [x for x in (ms[j - 1] if j else None, ms[j + 1] if j + 1 < len(ms) else None) if x]
                    for v in viz:
                        add(next((c for c in p["personagens"] if c["id"] == foco_do_momento(v)), None))
    return nomes[:3]


def local_do_item(p: Dict[str, Any], it: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """O cenário da 1ª cena em que o item aparece (o destaque acontece ali — mesma sala, mesmos móveis)."""
    for s in p["cenas"]:
        if any(m.get("destaque") == it["id"] or m.get("objeto") == it["id"] for m in s.get("momentos") or []):
            return local_da_cena(p, s)
    return None


def ref_personagem(p: Dict[str, Any], c: Dict[str, Any], base: str = _BASE) -> Optional[str]:
    """A melhor imagem do personagem: o 🎨 design aprovado → a ⭐ neutra → a 1ª referência."""
    d = design_aprovado(p, c, base)
    if d:
        return d
    pr = poses_prontas(c, base).get("neutro")
    if pr and pr.get("pose"):
        return pr["pose"]
    r = refs_de(p, c, base)
    return r[0] if r else None


def prompt_imagem(p: Dict[str, Any], tipo: str, x: Dict[str, Any], camada: str = "fundo") -> str:
    W, H = tamanho(p)
    est = estilo_en(p)
    import anime2d_planta as PL
    if tipo == "local" and camada == "fundo" and x.get("angulo_de"):
        lay = PL.texto_en(x.get("planta"), com_esboco=bool(PL.visiveis(x.get("planta"))))
        return (f"Background of a 2D anime TV series, {'wide 16:9' if W > H else 'vertical 9:16'}: the SAME room as the "
                f"room picture in the references (same objects, materials, colors, light and line art), now seen from ANOTHER "
                f"CAMERA ANGLE: {x.get('angulo_en') or x.get('angulo') or ''}. {x.get('prompt_en') or ''} {lay} EMPTY: no "
                f"people, no characters. {SEM_TEXTO} ART STYLE: {est}.")[:3900]
    if tipo == "local" and camada == "fundo" and x.get("variante_de"):
        return (f"EDIT the reference image: it is the background of this 2D anime. Keep EXACTLY the same room, the same camera "
                f"angle and framing, the same walls, window, objects and their positions, the same line art and colors — and "
                f"change ONLY this: {x.get('prompt_en') or x['nome']}. EMPTY: no people, no characters. {SEM_TEXTO} "
                f"ART STYLE: {est}.")[:3900]
    if tipo == "local" and camada == "fundo":
        props = [pr["nome"] + (f" ({pr['prompt_en']})" if pr.get("prompt_en") else "") for pr in x.get("props") or []]
        livre = (f" The furniture {'; '.join(props)} is NOT in this image (it is a separate layer): leave that space EMPTY "
                 "floor/wall." if props else "")
        lay = PL.texto_en(x.get("planta"), com_esboco=bool(PL.visiveis(x.get("planta"))))
        return (f"Background of a 2D anime TV series, {'wide 16:9' if W > H else 'vertical 9:16'}: {x.get('prompt_en') or x['nome']}. "
                "Seen from the front at eye level; the lower part is floor/ground where characters will stand." + livre +
                (" " + lay if lay else "") +
                f" EMPTY: no people, no characters, no animals. {SEM_TEXTO} ART STYLE: {est}.")[:3900]
    if tipo == "local":  # a camada da frente
        return (f"{x.get('frente_en')}, a foreground prop for a 2D anime seen from the front, the whole object visible "
                "with margin, isolated on a flat solid chroma-key green background (#00FF00), no shadow, no people. " + SEM_TEXTO + " "
                f"ART STYLE: {est}.")[:3900]
    if tipo == "prop":  # 🪑 um móvel do cenário (camada)
        lado = ""
        if re.search(r"\b(desk|table|counter|mesa|balc)", (x.get("prompt_en") or "") + " " + x["nome"], re.I) and x.get("camada") != "atras":
            lado = (" Seen from the VISITOR'S side, facing the camera: we see the solid FRONT panel of the desk; the drawers "
                    "and the knee space are on the far side (hidden); the top seen slightly from above.")
        elif re.search(r"\b(chair|cadeira|poltrona|armchair|stool)", (x.get("prompt_en") or "") + " " + x["nome"], re.I):
            lado = " Seen from the front, facing the camera (a person would sit facing the viewer), empty."
        return (f"{x.get('prompt_en') or x['nome']}, a single piece of furniture/prop for a 2D anime, the SAME camera angle as "
                f"the background reference (eye level, frontal).{lado} The whole object visible with margin, isolated on a "
                "flat solid chroma-key green background (#00FF00), no shadow, no people. " + SEM_TEXTO + f" ART STYLE: {est}.")[:3900]
    pers = personagens_do_item(p, x)
    quem = (" CHARACTERS IN THIS IMAGE (match the reference designs EXACTLY — same face, hairstyle, hair color, eye color, "
            "outfit and colors): " + "; ".join(f"{c['nome']}: {c.get('aparencia_en') or ''}" for c in pers) + ".") if pers else ""
    lo = local_do_item(p, x)
    onde = (f" SETTING: {lo.get('prompt_en') or lo['nome']}" + ("." if x.get("painel") else " (the same place as the reference background).")
            if lo and x.get("tipo") == "destaque" else "")
    comp = (" THIS IS AN ADAPTATION OF A MANGA PANEL: the FIRST (largest) reference image IS that panel. Redraw it as the "
            "colored anime frame keeping EXACTLY its composition — the same camera angle and distance, the same framing/crop, "
            "the same pose and gesture of each character (hands, head tilt, where they look), the same position of every "
            "element in the frame, the same foreground objects and the same motion/impact lines; do NOT invent a different "
            "shot. The other references only give the colors and the designs. Ignore balloons, sound-effect lettering and "
            "panel borders." if x.get("painel") else "")
    if x.get("tipo") == "destaque":
        return (f"Full-frame key image for a 2D anime TV series: {x.get('prompt_en') or x['nome']}.{quem}{onde}{comp} Dramatic, "
                f"expressive composition. {regra_texto(x.get('texto'))} ART STYLE: {est}.")[:3900]
    return (f"{x.get('prompt_en') or x['nome']}, a single prop/object for a 2D anime, the whole object visible with "
            f"margin, isolated on a flat solid chroma-key green background (#00FF00), no shadow.{quem} " + regra_texto(x.get("texto")) + " "
            f"ART STYLE: {est}.")[:3900]


def _ref_flow(p: Dict[str, Any], x: Dict[str, Any], base: str, extra: Optional[List[str]] = None) -> Optional[str]:
    """A referência que vai pro Flow: as fotos do próprio local/item + as de estilo (e personagens), lado a lado."""
    from PIL import Image
    if x.get("painel"):  # 📖 o quadro do mangá primeiro e GRANDE (a composição a recriar) + só o design de quem aparece
        cams = refs_de(p, x, base)[:1] + (extra or [])[:1]
    else:
        cams = (extra or [])[:4] + refs_de(p, x, base)[:2] + refs_estilo(p, base)[:1]  # os personagens/o cenário primeiro
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
    if x.get("painel") and len(ims) > 1:  # 📖 o quadro grande à esquerda; o design pequeno (45% da altura) embaixo à direita
        alt = 1024
        q = ims[0].resize((max(1, round(ims[0].width * alt / ims[0].height)), alt), Image.LANCZOS)
        dz = ims[1].resize((max(1, round(ims[1].width * alt * 0.45 / ims[1].height)), round(alt * 0.45)), Image.LANCZOS)
        col = Image.new("RGB", (q.width + 24 + dz.width, alt), (128, 128, 128))
        col.paste(q, (0, 0))
        col.paste(dz, (q.width + 24, alt - dz.height))
    else:
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
        esperando: List[str] = []
        for lo in p["locais"]:
            b_ = base_do_local(p, lo)
            if b_ is not None:  # 🌫 variante: o fundo sai EDITANDO o do original (precisa dele pronto); os móveis são os dele
                chave = f"{lo['id']}:fundo"
                st = lo.get("img") or {}
                if (alvos and chave in alvos) or (not alvos and not arquivo_img(p, st, base) and st.get("estado") not in ("fila", "gerando")):
                    fb = arquivo_img(p, b_.get("img") or {}, base)
                    if fb:
                        lo["_refs_extra"] = [fb]
                        lista.append(("local", lo, "fundo"))
                    else:
                        esperando.append(lo["nome"])
                continue
            ab = angulo_base(p, lo)
            for camada in ("fundo", "frente"):
                if camada == "frente" and not (lo.get("frente_en") or "").strip():
                    continue
                chave = f"{lo['id']}:{camada}"
                st = lo.get("img" if camada == "fundo" else "frente") or {}
                if (alvos and chave in alvos) or (not alvos and not arquivo_img(p, st, base) and st.get("estado") not in ("fila", "gerando")):
                    extra = []
                    if camada == "fundo":  # 📐 o esboço da planta primeiro (onde fica cada coisa)
                        import anime2d_planta as PL
                        Wq, Hq = tamanho(p)
                        esb = PL.esboco(lo.get("planta"), os.path.join(pasta(p["id"], base), "imagens"), Wq, Hq,
                                        float((lo.get("chao") or {}).get("y_fundo") or 0.72))
                        extra = [esb] if esb else []
                        if ab is not None:  # 🎥 outro ângulo: o fundo principal mostra os objetos/cores do cômodo
                            fb = arquivo_img(p, ab.get("img") or {}, base)
                            if not fb:
                                esperando.append(lo["nome"])
                                continue
                            extra.append(fb)
                        lo["_refs_extra"] = extra
                    lista.append(("local", lo, camada))
            for pr in lo.get("props") or []:  # 🪑 os móveis (camadas)
                if ab is not None and any(R._norm(q["nome"]) == R._norm(pr["nome"]) and arquivo_img(p, q.get("img") or {}, base)
                                          for q in ab.get("props") or []):
                    continue  # 🎥 o mesmo móvel do ângulo principal (a mesma imagem)
                st = pr.get("img") or {}
                chave = f"{lo['id']}:{pr['id']}"
                if (alvos and chave in alvos) or (not alvos and not arquivo_img(p, st, base) and st.get("estado") not in ("fila", "gerando")):
                    pr["_local"] = lo
                    lista.append(("prop", pr, "prop"))
        for it in p["itens"]:
            st = it.get("img") or {}
            if (alvos and it["id"] in alvos) or (not alvos and not arquivo_img(p, st, base) and st.get("estado") not in ("fila", "gerando")):
                # 🧍 v84_238: quem aparece vai com o design aprovado (mesmo cabelo e cores) e o destaque com o cenário dele
                extra = [x for x in (ref_personagem(p, c, base) for c in personagens_do_item(p, it)) if x]
                lo = local_do_item(p, it)
                fundo = arquivo_img(p, (lo or {}).get("img") or {}, base) if lo and it.get("tipo") == "destaque" else None
                lista.append(("item", it, "destaque" if it.get("tipo") == "destaque" else "objeto"))
                it["_refs_extra"] = extra[:3] + ([fundo] if fundo else [])
        if not lista:
            raise AnimeErro("Nada pra gerar (tudo já tem imagem ou está na fila)." + (
                f" 🌫 {', '.join(esperando)}: gere antes o cenário principal (a variante/o ângulo sai a partir dele)." if esperando else ""))
        W, H = tamanho(p)
        lote = flow_lote.lote()
        por_prop: Dict[str, List[int]] = {}
        itens = []
        for k, (tipo, x, camada) in enumerate(lista):
            pr = prompt_imagem(p, tipo, x, camada)
            if pedido:
                pr = (pr + " " + pedido)[:3990]
            it = {"prompt": pr, "tipo": "imagem", "origem": "anime2d"}
            if tipo == "prop":  # o móvel no estilo do fundo do cenário dele
                lo_ = x.pop("_local", None)
                f_ = arquivo_img(p, (lo_ or {}).get("img") or {}, base) if lo_ else None
                x["_refs_extra"] = [f_] if f_ else []
            if tipo == "local" and base_do_local(p, x) is not None:  # 🌫 a variante: SÓ o fundo original como referência
                ref = (x.pop("_refs_extra", None) or [None])[0]
            else:
                ref = _ref_flow(p, x, base, x.pop("_refs_extra", None))
            if ref:
                it["referencia_arquivo"] = ref
            itens.append(it)
            prop = ("16:9" if W > H else "9:16") if camada in ("fundo", "destaque") else "4:3" if camada == "prop" else "1:1"
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
            st.update(estado="fila", job=jobs[k]["id"], erro=None, msg="⏳ na fila do Flow", recortar=camada in ("frente", "objeto", "prop"))
        log(p, f"🚀 {len(lista)} imagem(ns) pro Flow (locais/itens)" + (f" · 🌫 esperando o principal: {', '.join(esperando)}" if esperando else ""))
        salvar(p, base)
    aviso = (f"🌫 {', '.join(esperando)}: gere de novo quando o cenário principal ficar pronto (a variante/o ângulo sai a partir dele). "
             if esperando else "")
    try:
        lote.iniciar()
    except Exception as exc:  # noqa: BLE001
        aviso += f"o Flow em massa não ligou agora ({str(exc)[:160]}) — ▶ Continuar na aba Flow"
    return {"enviadas": len(lista), "aviso": aviso.strip()}


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
    for lo in p["locais"]:  # 🪑 os móveis do cenário (recortados do verde)
        for pr in lo.get("props") or []:
            out.append((pr.setdefault("img", {}), True, False))
    for lo in p["locais"]:  # 🎬 o storyboard do cenário (os personagens/móveis desenhados no fundo)
        if lo.get("story"):
            out.append((lo["story"], False, True))
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
                sem_boca = [x for x in proj["dados"]["poses"] if x.get("tipo") == "pose" and not x["arquivo"].endswith(("_b.png", "_pisca.png"))
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
          f"new characters. {SEM_TEXTO} {pedido}".strip())[:3900]
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
MOTORES_PERFIL = ("xtts", "chatterbox", "chatterbox_turbo", "fish_s2")  # os motores que clonam um 🗣️ perfil de voz


def vozes_disponiveis(motor_perfil: str = "xtts") -> List[Dict[str, Any]]:
    """🎙 v84_238: TODAS as vozes do site — as do 🎭 multi voice e cada 🗣️ perfil de voz (clonado, no motor escolhido
    pros perfis); antes só apareciam as do multi voice."""
    out: List[Dict[str, Any]] = []
    try:
        import multivoz
        out += [{"slug": v["slug"], "nome": v["nome"], "resumo": multivoz.resumo(v), "genero": v.get("genero") or "",
                 "grupo": "🎭 multi voice"} for v in multivoz.listar()]
    except Exception:  # noqa: BLE001
        pass
    try:
        import perfis_info
        from tts.voice_generator import listar_perfis_de_voz
        info = perfis_info.todos()
        for nome in listar_perfis_de_voz():
            i = info.get(nome) or {}
            out.append({"slug": "perfil:" + nome, "nome": nome, "resumo": f"🗣️ perfil · {motor_perfil}" + (f" · {i['descricao'][:60]}" if i.get("descricao") else ""),
                        "genero": i.get("genero") or "", "grupo": "🗣️ perfis de voz"})
    except Exception:  # noqa: BLE001
        pass
    return out


def voz_por_slug(slug: str, motor_perfil: str = "xtts") -> Optional[Dict[str, Any]]:
    """A voz (como o multivoz guarda) — o perfil vira uma voz do motor escolhido usando aquele perfil."""
    if not slug:
        return None
    if slug.startswith("perfil:"):
        return {"slug": slug, "nome": slug[7:], "motor": motor_perfil if motor_perfil in MOTORES_PERFIL else "xtts",
                "config": {"vozPerfil": slug[7:]}}
    try:
        import multivoz
        return multivoz.por_slug().get(slug)
    except Exception:  # noqa: BLE001
        return None


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
    p = carregar(pid, base)
    mp = p.get("motor_perfil") or "xtts"
    if audio_ok(p, base):
        raise AnimeErro("Este episódio usa o 🎧 áudio que você enviou — não precisa gerar vozes.")
    d = os.path.join(pasta(pid, base), "vozes")
    os.makedirs(d, exist_ok=True)
    feitas, sem_voz, erros = 0, 0, []
    def slug_de(m: Dict[str, Any]) -> str:
        return ((p.get("narrador") or {}).get("voz") if m["quem"] == "narrador" else
                (next((c for c in p["personagens"] if c["id"] == m["quem"]), {}) or {}).get("voz")) or ""
    todos = [(k, j) for k, s in enumerate(p["cenas"]) for j, m in enumerate(s.get("momentos") or []) if m["tipo"] in ("fala", "narracao") and m.get("texto")]
    # ⚡ v84_238: todas as falas de UMA voz em seguida (o motor carrega a voz/o perfil uma vez só), depois a próxima voz
    ordem_vozes: List[str] = []
    for k, j in todos:
        sl = slug_de(p["cenas"][k]["momentos"][j])
        if sl not in ordem_vozes:
            ordem_vozes.append(sl)
    todos.sort(key=lambda kj: ordem_vozes.index(slug_de(p["cenas"][kj[0]]["momentos"][kj[1]])))
    vozes = {sl: voz_por_slug(sl, mp) for sl in ordem_vozes if sl}
    for n, (k, j) in enumerate(todos, 1):
        p = carregar(pid, base)
        m = p["cenas"][k]["momentos"][j]
        slug = slug_de(m)
        chave = f"{slug}|{m['texto']}"
        if so_faltando and (m.get("audio") or {}).get("chave") == chave and os.path.isfile(os.path.join(d, (m.get("audio") or {}).get("arquivo") or "_")):
            continue
        if not slug or not vozes.get(slug):
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
    """O que vai em cada tempo — 🎬 v84_238: o motor de planos (anime2d_cena): cortes de câmera, móveis em camadas,
    lugares, sombra, andar, poses em sequência e piscadas."""
    import anime2d_cena
    return anime2d_cena.plano(p, base)


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
        if m.get("resp"):  # 🫁 respirando
            if a <= t <= b:
                y += H * float(m["resp"]) * math.sin(t * 2 * 3.14159265 / 2.6 + float(m.get("f") or 0))
            continue
        if m.get("pulo"):  # 🦘 pulinho de reação
            if a <= t <= b:
                y -= H * float(m["pulo"]) * math.sin(math.pi * (t - a) / max(0.001, b - a))
            continue
        if "de" in m:  # 🚶 andar: de `de` até `para` (fração da largura) entre a e b, e fica até z
            z = float(m.get("z") or b)
            if not (a <= t <= z):
                continue
            k = min(1.0, max(0.0, (t - a) / max(0.001, b - a)))
            x += W * (float(m["de"]) + (float(m.get("para") or 0) - float(m["de"])) * k)
            continue
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
    """Tudo pro Estúdio: o áudio do episódio, um trecho de fundo por plano (momento) e as camadas posicionadas."""
    import anime2d_cena
    return anime2d_cena.montar_editor(p, base, job_dir)


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
    """Uma imagem do episódio no segundo t — as mesmas camadas do editor."""
    import anime2d_cena
    return anime2d_cena.previa(p, base, destino, t, legenda)


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
    out["vozes_disponiveis"] = vozes_disponiveis(p.get("motor_perfil") or "xtts")
    out["motores_perfil"] = list(MOTORES_PERFIL)
    out["planos"], out["fundos_reacao"] = PLANOS, FUNDOS_REACAO
    out["lugares"] = {lo["id"]: list(lugares_do_local(p, lo)) for lo in p["locais"]}
    # 📐 a planta (texto) e 🎥 os ângulos/variantes de cada cômodo (o que um momento pode usar)
    out["plantas"] = {lo["id"]: _PL.descricao_pt((layout_do_local(p, lo) or {}).get("planta")) for lo in p["locais"]}
    out["familias"] = {lo["id"]: [[x["id"], ("🎥 " if angulo_base(p, x) else "🌫 " if base_do_local(p, x) else "🏞 ") + x["nome"]]
                                  for x in familia_do_local(p, lo)] for lo in p["locais"]}
    out["origem_local"] = {lo["id"]: (f"🎥 ângulo de {angulo_base(p, lo)['nome']}" if angulo_base(p, lo) else
                                      f"🌫 variante de {base_do_local(p, lo)['nome']}" if base_do_local(p, lo) else "") for lo in p["locais"]}
    out["itens"] = [dict(it, personagens_txt=", ".join(it.get("personagens") or [])) for it in p["itens"]]
    out["layout"] = {lo["id"]: {"lugares": list(lugares_do_local(p, lo).values()), "chao": lo.get("chao") or {},
                                "alt": float((lo.get("chao") or {}).get("alt") or (0.62 if tamanho(p)[0] > tamanho(p)[1] else 0.40))}
                     for lo in p["locais"]}
    falas = [m for s in p["cenas"] for m in s.get("momentos") or [] if m["tipo"] in ("fala", "narracao")]
    out["vozes_estado"] = {"falas": len(falas), "com_audio": sum(1 for m in falas if (m.get("audio") or {}).get("arquivo"))}
    out["modo_audio"] = audio_ok(p, base)
    out["duracao_planejada"] = duracao_planejada(p)
    out["n_paginas"] = len(paginas_manga(p))
    return out
