"""
criador_personagens.py — 🧬 Criador de personagens (v84_239)
=============================================================

Um sistema À PARTE pra criar personagens VERDADEIRAMENTE únicos no 🚀 Google Flow:

  1. 📥 Entrada — do jeito que quiser (dá pra misturar):
     • 🧬 clonar: uma imagem de um personagem + o que mudar ("igual, mas com cabelo azul e cicatriz");
     • 🧩 misturar: várias imagens e, em cada uma, o que pegar dela (rosto da 1, cabelo da 2, roupa da 5, corpo da 3…);
     • ✍ descrever: só o texto;
     • 💡 inspirações: personagens famosos pra pegar um aspecto (a personalidade do X, o jeito de falar do Y);
     • 🎨 o estilo de arte (lista grande + “outro” escrito à mão: expressionismo, vitral, …) e detalhes (gênero, idade,
       corpo/estatura, paleta, marcas que SEMPRE aparecem, o que evitar, “bem original”).
  2. 📝 Ficha (🤖 IA, ou à mão): ideias de NOMES (com o porquê), aparência travada em inglês (vai em todo pedido),
     personalidade, jeito de falar, bordões, história, gostos/medos, voz, paleta e o que veio de cada referência — e um
     aviso se ficou parecido demais com alguém que já existe.
  3. 🎨 Design no Flow: N variações (corpo inteiro, fundo verde → PNG transparente); ✔ aprovar uma, 🔁 refazer com
     correção ou 🎯 variar a partir de uma.
  4. 🧍 Poses: o aprovado vira a ⭐ mestre de um projeto da aba 🧍 Personagens (o mesmo motor de poses do site) e os
     pacotes escolhidos vão pro Flow — giro (frente/lado/costas), expressões, ação, sentado pro React — + poses suas.
  5. ⬇ zip: o design, as poses aprovadas e a ficha (.json e .txt).

Tudo fica em criador_personagens/<id>/ (projeto.json, refs/, design/).
"""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import shutil
import threading
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple

_BASE = os.path.dirname(os.path.abspath(__file__))
_TRAVA = threading.RLock()
RE_ID = re.compile(r"^cp[0-9a-f]{10}$")
MAX_REFS = 6
MAX_VARIACOES = 4
ESPERA = ("fila", "gerando")


class CriadorErro(Exception):
    pass


# ------------------------------------------------------------------ 🎨 estilos de arte (+ "outro", escrito à mão)
ESTILOS: Dict[str, Tuple[str, str]] = {
    # anime / mangá
    "anime": ("🌸 Anime moderno", "modern anime illustration, clean line art, cel shading, vibrant colors"),
    "anime90": ("📼 Anime anos 90", "1990s retro anime style, hand-painted cel look, soft film grain, muted retro palette"),
    "manga": ("📖 Mangá (preto e branco)", "black and white manga art, ink line work, screentone shading, no color"),
    "shonen": ("🔥 Shōnen de ação", "dynamic shonen anime style, bold thick lines, dramatic shading, intense eyes"),
    "shoujo": ("💐 Shōjo", "shoujo manga style, big sparkling eyes, delicate thin lines, soft pastel colors, flowers and sparkles"),
    "seinen": ("🗡 Seinen realista", "seinen manga style, detailed realistic proportions, gritty cross-hatching"),
    "chibi": ("🍡 Chibi / kawaii", "super-deformed chibi style, big head small body, cute rounded shapes"),
    "ghibli": ("🍃 Filme de animação japonês pintado à mão", "hand-painted Japanese animated film look, soft watercolor colors, gentle warm lighting, simple expressive faces"),
    "gacha": ("🎀 Gacha Life / avatar 2D", "Gacha-style 2D avatar, simple clean shapes, flat colors, big anime eyes"),
    "webtoon": ("📱 Webtoon / manhwa", "Korean webtoon manhwa style, clean digital coloring, soft gradients, glossy hair"),
    "donghua": ("🐉 Donghua (animação chinesa)", "Chinese donghua animation style, elegant flowing clothes, refined faces, soft glow"),
    # desenho / cartoon / jogos
    "cartoon": ("📺 Cartoon americano", "western TV cartoon style, bold outlines, simple shapes, flat bright colors"),
    "rubberhose": ("🎩 Cartoon anos 30 (rubber hose)", "1930s rubber hose cartoon, pie-cut eyes, noodle limbs, white gloves, vintage black and white"),
    "comics": ("💥 Quadrinhos de super-herói", "American superhero comic book art, heavy inks, dynamic anatomy, halftone dots"),
    "franco": ("🖋 Quadrinho franco-belga (linha clara)", "Franco-Belgian ligne claire comic style, clean uniform outlines, flat colors"),
    "pixar3d": ("🧸 Animação 3D de cinema", "3D animated feature film style, soft subsurface skin, expressive big eyes, cinematic lighting"),
    "clay": ("🧱 Massinha (stop-motion)", "claymation stop-motion look, plasticine textures, fingerprints, handmade charm"),
    "pixel": ("👾 Pixel art", "detailed 32-bit pixel art sprite, limited palette, crisp pixels"),
    "lowpoly": ("🔺 Low-poly / PS1", "low-poly PS1-era 3D render, blurry textures, flat shading"),
    "jogo_cel": ("🎮 Jogo com cel-shading", "cel-shaded video game character render, bold outlines, toon shading"),
    "vetor": ("📐 Vetor flat", "flat vector illustration, geometric shapes, no outlines, limited palette"),
    "papercut": ("✂ Recorte de papel", "layered paper cutout craft style, visible paper texture and shadows"),
    "sketch": ("✏ Rabisco / esboço", "rough pencil sketch, loose construction lines, graphite shading"),
    "paint": ("🖱 Desenho de Paint", "crude MS Paint drawing, wobbly mouse lines, flat bucket-fill colors"),
    # realismo
    "realista": ("📷 Realista (foto)", "photorealistic, real photograph, natural light, high detail"),
    "semireal": ("🎭 Semi-realista", "semi-realistic digital painting, realistic proportions with stylized rendering"),
    "conceito": ("🗺 Arte conceitual de jogo/filme", "polished concept art for a game or film, painterly details, dramatic light"),
    "fantasia": ("🧙 Fantasia sombria", "dark fantasy illustration, moody lighting, rich textures, gothic atmosphere"),
    # movimentos e técnicas de arte
    "aquarela": ("💧 Aquarela", "watercolor painting, soft bleeding edges, paper texture"),
    "oleo": ("🖼 Pintura a óleo", "classic oil painting, visible brush strokes, rich glazes"),
    "renascenca": ("🏛 Renascentista", "Renaissance oil portrait style, chiaroscuro, classical composition"),
    "barroco": ("🕯 Barroco", "Baroque painting, dramatic tenebrism, ornate details"),
    "impressionismo": ("🌅 Impressionismo", "impressionist painting, broken color dabs, vibrant natural light"),
    "expressionismo": ("😱 Expressionismo", "expressionist painting, distorted forms, intense emotional colors, bold brush strokes"),
    "cubismo": ("🧊 Cubismo", "cubist painting, fragmented geometric planes, multiple viewpoints"),
    "surrealismo": ("🫠 Surrealismo", "surrealist painting, dreamlike impossible details, smooth rendering"),
    "artnouveau": ("🌿 Art nouveau", "Art Nouveau poster style, flowing organic lines, decorative frames, muted gold palette"),
    "artdeco": ("🏙 Art déco", "Art Deco style, geometric elegance, gold and black, streamlined shapes"),
    "popart": ("🟡 Pop art", "pop art, bold Ben-Day dots, thick outlines, saturated primary colors"),
    "ukiyoe": ("🌊 Ukiyo-e (xilogravura japonesa)", "ukiyo-e woodblock print, flat colors, elegant outlines, washi paper texture"),
    "sumie": ("🖌 Sumi-e (tinta nanquim)", "sumi-e ink wash painting, expressive brush strokes, minimal color"),
    "vitral": ("⛪ Vitral", "stained glass window style, bold lead lines, glowing jewel colors"),
    "graffiti": ("🎨 Grafite / street art", "graffiti street art, spray paint, drips, bold colors"),
    # estéticas
    "cyberpunk": ("🌃 Cyberpunk neon", "cyberpunk aesthetic, neon rim lights, high-tech details"),
    "steampunk": ("⚙ Steampunk", "steampunk aesthetic, brass gears, Victorian details, sepia tones"),
    "vaporwave": ("🌴 Vaporwave", "vaporwave aesthetic, pastel pink and cyan, retro 80s glow"),
    "tarot": ("🔮 Carta de tarô", "tarot card illustration, ornate symbolic details, gold linework"),
}
ESTILO_OUTRO = "outro"

# 🕰 época (do personagem e do lugar) — a roupa, a tecnologia e a arquitetura seguem a época
EPOCAS: Dict[str, Tuple[str, str]] = {
    "": ("— sem época definida", ""),
    "pre_historia": ("🦴 Pré-história", "prehistoric era, stone tools, furs and hides"),
    "antiguidade": ("🏛 Antiguidade (Egito, Grécia, Roma)", "ancient era, classical antiquity clothing and architecture"),
    "medieval": ("🏰 Idade Média", "medieval era, castles, tunics, cloaks and armor"),
    "feudal_japao": ("⛩ Japão feudal", "feudal Japan, Edo-period clothing and architecture"),
    "renascimento": ("🎨 Renascimento", "Renaissance era, 15th–16th century European fashion and architecture"),
    "colonial": ("⛵ Era colonial / das navegações", "17th–18th century colonial era, sailing ships, tricorn hats"),
    "vitoriana": ("🎩 Era vitoriana (séc. XIX)", "Victorian era, 19th century fashion, gas lamps, industrial revolution"),
    "velho_oeste": ("🤠 Velho Oeste", "American Old West, 1870s frontier town, cowboys"),
    "anos20": ("🎷 Anos 20", "1920s, art deco, flapper dresses, suits and fedoras"),
    "anos50": ("🚗 Anos 50", "1950s, retro diners, classic cars"),
    "anos80": ("📼 Anos 80", "1980s, neon, retro tech, big hair"),
    "atual": ("📱 Atual", "present day, modern clothing and technology"),
    "futuro_proximo": ("🤖 Futuro próximo", "near future, sleek smart tech, subtle holograms"),
    "futuro_distante": ("🚀 Futuro distante", "far future, advanced sci-fi technology and architecture"),
    "pos_apocalipse": ("☢ Pós-apocalipse", "post-apocalyptic world, ruins, scavenged gear"),
    "fantasia": ("🧙 Fantasia (fora do tempo)", "timeless high fantasy world, magic"),
}
EPOCA_OUTRO = "outro"


def epoca_en(e: Dict[str, Any]) -> str:
    if e.get("epoca") == EPOCA_OUTRO:
        return e.get("epoca_livre") or ""
    return EPOCAS.get(e.get("epoca") or "", ("", ""))[1]


def epoca_nome(e: Dict[str, Any]) -> str:
    if e.get("epoca") == EPOCA_OUTRO:
        return "✍ " + (e.get("epoca_livre") or "outra")
    return EPOCAS.get(e.get("epoca") or "", ("", ""))[0] if e.get("epoca") else ""

# 🧩 o que pegar de cada imagem de referência
ASPECTOS: Dict[str, Tuple[str, str]] = {
    "tudo": ("🧬 tudo (clonar)", "the WHOLE character (identity, face, hair, outfit, colors) — keep it recognizable"),
    "rosto": ("🙂 rosto", "the FACE shape and facial features"),
    "olhos": ("👁 olhos", "the EYES (shape, color, look)"),
    "cabelo": ("💇 cabelo", "the HAIRSTYLE and hair color"),
    "corpo": ("🧍 corpo / estatura", "the BODY TYPE, height and proportions"),
    "roupa": ("👕 roupa", "the OUTFIT and clothing pieces"),
    "cores": ("🎨 cores", "the COLOR PALETTE"),
    "cores_reais": ("🌈 cores reais (é a versão colorida)", "ONLY the REAL COLORS — this panel is a COLORED version of the character "
                    "(hair, eyes, skin, outfit, accessories colors); ignore its art style and pose; these colors win over any "
                    "color written in the text"),
    "acessorios": ("💍 acessórios", "the ACCESSORIES (jewelry, glasses, weapons, props)"),
    "expressao": ("😏 expressão / jeito", "the attitude, expression and body language"),
    "traco": ("✒ traço / estilo", "the ART STYLE and line work of the drawing"),
}

# 🧍 os pacotes de poses (depois do design aprovado)
_FUNDO = "flat solid chroma-key green background (#00FF00)"
PACOTES: Dict[str, Tuple[str, List[Tuple[str, str, str]]]] = {
    "giro": ("🔄 Giro (frente, ¾, lado, costas)", [
        ("frente", "de frente", "standing straight in a neutral relaxed pose, FRONT view, arms relaxed, full body"),
        ("tres_quartos", "três-quartos", "standing in a neutral pose, three-quarter view turned to the viewer's right, full body"),
        ("lado", "de lado", "standing in a neutral pose, strict SIDE profile view facing the viewer's right, full body"),
        ("costas", "de costas", "standing in a neutral pose seen from BEHIND (back view), full body"),
    ]),
    "expressoes": ("😀 Expressões", [
        ("feliz", "feliz", "upper body from the waist up, a warm happy smile"),
        ("rindo", "rindo", "upper body from the waist up, laughing out loud, eyes squinting"),
        ("bravo", "bravo", "upper body from the waist up, angry, furrowed brows, gritted teeth"),
        ("triste", "triste", "upper body from the waist up, sad, teary eyes"),
        ("surpreso", "surpreso", "upper body from the waist up, shocked, eyes wide, mouth open"),
        ("envergonhado", "envergonhado", "upper body from the waist up, embarrassed, blushing, looking away"),
        ("pensativo", "pensativo", "upper body from the waist up, thinking, hand on chin"),
        ("determinado", "determinado", "upper body from the waist up, determined confident look, clenched fist"),
    ]),
    "acao": ("🏃 Poses de ação e do dia a dia", [
        ("acenando", "acenando", "full body, waving hello with one hand, friendly"),
        ("apontando", "apontando", "full body, pointing forward at the viewer"),
        ("bracos_cruzados", "braços cruzados", "full body, arms crossed, confident stance"),
        ("correndo", "correndo", "full body, running fast, dynamic pose"),
        ("pulando", "pulando de alegria", "full body, jumping in the air with joy"),
        ("luta", "pose de luta", "full body, fighting stance, ready for battle"),
        ("sentado", "sentado", "full body, sitting on an invisible chair, relaxed (do NOT draw the chair)"),
        ("olhando_ombro", "olhando por cima do ombro", "full body seen from behind, looking back over the shoulder"),
    ]),
    "idades": ("👶🧓 Outras idades (criança, adolescente, adulto, idoso)", [
        ("idade_crianca", "criança", "the SAME character as a young CHILD (about 7 years old) — same face traits, hair and color palette, an outfit in the same style sized for a child, full body"),
        ("idade_adolescente", "adolescente", "the SAME character as a TEENAGER (about 15) — same face traits, hair and palette, full body"),
        ("idade_adulto", "adulto", "the SAME character as a grown ADULT (about 35) — same face traits, hair and palette, full body"),
        ("idade_idoso", "idoso", "the SAME character as an ELDERLY person (about 75) — same face traits, grey/white version of the hair, wrinkles, same palette, full body"),
    ]),
    "react": ("🎭 Sentado pro React (¾ olhando pra TV)", [
        ("react_neutro", "React — neutro", "SITTING on an invisible seat, turned three-quarters toward the viewer's RIGHT as if watching a TV, calm, cropped at the knees (no seat drawn)"),
        ("react_feliz", "React — rindo", "SITTING on an invisible seat, turned three-quarters toward the viewer's RIGHT, laughing, cropped at the knees (no seat drawn)"),
        ("react_chocado", "React — chocado", "SITTING on an invisible seat, turned three-quarters toward the viewer's RIGHT, shocked, leaning back, cropped at the knees (no seat drawn)"),
        ("react_bravo", "React — bravo", "SITTING on an invisible seat, turned three-quarters toward the viewer's RIGHT, angry, cropped at the knees (no seat drawn)"),
    ]),
}


# ------------------------------------------------------------------ guardar
def pasta_raiz(base: str = _BASE) -> str:
    return os.environ.get("CRIADOR_PERSONAGENS_DIR") or os.path.join(base, "criador_personagens")


def pasta(pid: str, base: str = _BASE) -> str:
    if not RE_ID.match(pid or ""):
        raise CriadorErro("Projeto inválido.")
    return os.path.join(pasta_raiz(base), pid)


def _completar(p: Dict[str, Any]) -> Dict[str, Any]:
    e = p.setdefault("entrada", {})
    for k, v in (("descricao", ""), ("inspiracoes", ""), ("estilo", "anime"), ("estilo_livre", ""), ("genero", ""),
                 ("idade", ""), ("corpo", ""), ("paleta", ""), ("travas", ""), ("evitar", ""), ("original", True),
                 ("nomes_ideia", ""), ("epoca", ""), ("epoca_livre", ""), ("lugar", "")):
        e.setdefault(k, v)
    e.setdefault("refs", [])
    p.setdefault("ficha", {})
    p.setdefault("design", {"variacoes": [], "aprovado": None})
    p.setdefault("poses", {"pod": None, "pacotes": [], "fase": None})
    p.setdefault("log", [])
    return p


def criar(nome: str = "", base: str = _BASE) -> Dict[str, Any]:
    p = _completar({"id": "cp" + secrets.token_hex(5), "nome": " ".join(str(nome or "").split())[:80] or "Personagem novo",
                    "criado": time.time()})
    salvar(p, base)
    return p


def carregar(pid: str, base: str = _BASE) -> Dict[str, Any]:
    try:
        with open(os.path.join(pasta(pid, base), "projeto.json"), encoding="utf-8") as f:
            return _completar(json.load(f))
    except FileNotFoundError:
        raise CriadorErro("Projeto não encontrado.")


def salvar(p: Dict[str, Any], base: str = _BASE) -> None:
    d = pasta(p["id"], base)
    os.makedirs(d, exist_ok=True)
    p["atualizado"] = time.time()
    tmp = os.path.join(d, f"projeto.json.{secrets.token_hex(3)}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(d, "projeto.json"))


def listar(base: str = _BASE) -> List[Dict[str, Any]]:
    raiz = pasta_raiz(base)
    out = []
    for n in sorted(os.listdir(raiz)) if os.path.isdir(raiz) else []:
        if not RE_ID.match(n):
            continue
        try:
            p = carregar(n, base)
        except Exception:  # noqa: BLE001
            continue
        ap = aprovada(p)
        out.append({"id": n, "nome": p["nome"], "atualizado": p.get("atualizado") or 0,
                    "miniatura": ap.get("arquivo") if ap else None,
                    "fase": "🧍 poses" if p["poses"].get("pod") else "✔ aprovado" if ap else
                            "🎨 design" if p["design"]["variacoes"] else "📝 ficha" if p["ficha"].get("aparencia_en") else "📥 começo"})
    return sorted(out, key=lambda x: -x["atualizado"])


def excluir(pid: str, base: str = _BASE) -> None:
    shutil.rmtree(pasta(pid, base), ignore_errors=True)


def log(p: Dict[str, Any], msg: str) -> None:
    p["log"] = (p.get("log") or [])[-60:] + [{"t": time.time(), "msg": msg}]


def _txt(v: Any, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


# ------------------------------------------------------------------ 📥 entrada
CAMPOS_ENTRADA = {"epoca_livre": 200, "descricao": 3000, "inspiracoes": 1500, "estilo_livre": 300, "genero": 80, "idade": 80, "corpo": 300,
                  "paleta": 300, "travas": 800, "evitar": 800, "nomes_ideia": 400}


def editar_entrada(p: Dict[str, Any], dados: Dict[str, Any]) -> None:
    e = p["entrada"]
    for k, n in CAMPOS_ENTRADA.items():
        if k in dados:
            e[k] = str(dados[k] or "").strip()[:n]
    if "estilo" in dados:
        e["estilo"] = dados["estilo"] if dados["estilo"] in ESTILOS or dados["estilo"] == ESTILO_OUTRO else "anime"
    if "original" in dados:
        e["original"] = bool(dados["original"])
    if "epoca" in dados:
        e["epoca"] = dados["epoca"] if dados["epoca"] in EPOCAS or dados["epoca"] == EPOCA_OUTRO else ""
    if "lugar" in dados:
        e["lugar"] = str(dados["lugar"] or "") if re.match(r"^(lg[0-9a-f]{10})?$", str(dados["lugar"] or "")) else ""
    if "nome" in dados:
        p["nome"] = _txt(dados["nome"], 80) or p["nome"]


def guardar_ref(p: Dict[str, Any], img, pegar: Optional[List[str]] = None, nota: str = "", base: str = _BASE) -> Dict[str, Any]:
    """🧩 Uma imagem de referência (até 6) e o que pegar dela."""
    if len(p["entrada"]["refs"]) >= MAX_REFS:
        raise CriadorErro(f"No máximo {MAX_REFS} imagens de referência.")
    d = os.path.join(pasta(p["id"], base), "refs")
    os.makedirs(d, exist_ok=True)
    im = img.convert("RGB")
    im.thumbnail((1600, 1600))
    arq = f"ref_{secrets.token_hex(3)}.jpg"
    im.save(os.path.join(d, arq), quality=92)
    r = {"arquivo": arq, "pegar": [a for a in (pegar or ["tudo"]) if a in ASPECTOS] or ["tudo"], "nota": _txt(nota, 300)}
    p["entrada"]["refs"].append(r)
    return r


def editar_ref(p: Dict[str, Any], arquivo: str, dados: Dict[str, Any], base: str = _BASE) -> None:
    refs = p["entrada"]["refs"]
    r = next((x for x in refs if x["arquivo"] == arquivo), None)
    if not r:
        raise CriadorErro("Imagem não encontrada.")
    if dados.get("apagar"):
        refs.remove(r)
        try:
            os.remove(os.path.join(pasta(p["id"], base), "refs", arquivo))
        except OSError:
            pass
        return
    if "pegar" in dados:
        r["pegar"] = [a for a in dados["pegar"] or [] if a in ASPECTOS] or ["tudo"]
    if "nota" in dados:
        r["nota"] = _txt(dados["nota"], 300)
    if dados.get("mover") in (-1, 1):
        i = refs.index(r)
        j = i + int(dados["mover"])
        if 0 <= j < len(refs):
            refs[i], refs[j] = refs[j], refs[i]


def estilo_en(p: Dict[str, Any]) -> str:
    e = p["entrada"]
    if e.get("estilo") == ESTILO_OUTRO and e.get("estilo_livre"):
        return f"{e['estilo_livre']} art style (render the WHOLE character in this style)"
    return ESTILOS.get(e.get("estilo") or "anime", ESTILOS["anime"])[1]


def estilo_nome(p: Dict[str, Any]) -> str:
    e = p["entrada"]
    if e.get("estilo") == ESTILO_OUTRO:
        return "✍ " + (e.get("estilo_livre") or "outro")
    return ESTILOS.get(e.get("estilo") or "anime", ESTILOS["anime"])[0]


def mapa_refs(p: Dict[str, Any]) -> List[str]:
    """'panel 1: take the face and the hair (nota)' — o que pegar de cada imagem numerada."""
    out = []
    for k, r in enumerate(p["entrada"]["refs"]):
        pegar = r.get("pegar") or ["tudo"]
        oque = "; ".join(ASPECTOS[a][1] for a in pegar if a in ASPECTOS)
        out.append(f"panel {k + 1}: take ONLY {oque}" + (f" (note: {r['nota']})" if r.get("nota") else ""))
    return out


def colagem_numerada(p: Dict[str, Any], base: str = _BASE) -> Optional[str]:
    """As imagens de referência numa imagem só (o Flow aceita UMA referência), cada uma com o NÚMERO grande no canto."""
    refs = p["entrada"]["refs"]
    if not refs:
        return None
    d = os.path.join(pasta(p["id"], base), "refs")
    return colagem_de([os.path.join(d, r["arquivo"]) for r in refs], os.path.join(pasta(p["id"], base), "flow_refs"))


def colagem_de(caminhos: List[str], pasta_destino: str) -> Optional[str]:
    """As imagens numa colagem numerada (1, 2, 3… em amarelo no canto) — o nome vem do conteúdo (o Flow reusa a mídia)."""
    from PIL import Image, ImageDraw, ImageFont
    if not caminhos:
        return None
    ims = []
    for c in caminhos:
        try:
            ims.append(Image.open(c).convert("RGB"))
        except Exception:  # noqa: BLE001
            ims.append(Image.new("RGB", (600, 800), (128, 128, 128)))
    alt = 720 if len(ims) <= 3 else 560
    cols = len(ims) if len(ims) <= 3 else 3
    linhas = (len(ims) + cols - 1) // cols
    esc = [i.resize((max(1, round(i.width * alt / i.height)), alt)) for i in ims]
    larg = max(sum(e.width for e in esc[r * cols:(r + 1) * cols]) + 20 * (cols - 1) for r in range(linhas))
    out = Image.new("RGB", (larg, linhas * alt + 20 * (linhas - 1)), (128, 128, 128))
    dr = ImageDraw.Draw(out)
    try:
        fonte = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
    except Exception:  # noqa: BLE001
        fonte = ImageFont.load_default()
    for r in range(linhas):
        x = 0
        y = r * (alt + 20)
        for k, e in enumerate(esc[r * cols:(r + 1) * cols]):
            out.paste(e, (x, y))
            n = str(r * cols + k + 1)
            dr.rectangle([x + 8, y + 8, x + 96, y + 96], fill=(0, 0, 0))
            dr.text((x + 30, y + 14), n, fill=(255, 255, 0), font=fonte)
            x += e.width + 20
    if out.width > 2048:
        out = out.resize((2048, max(1, round(out.height * 2048 / out.width))))
    import hashlib
    cam_d = pasta_destino
    os.makedirs(cam_d, exist_ok=True)
    buf = io.BytesIO()
    out.save(buf, "PNG")
    cam = os.path.join(cam_d, f"refs_{hashlib.md5(buf.getvalue()).hexdigest()[:10]}.png")
    if not os.path.isfile(cam):
        with open(cam, "wb") as f:
            f.write(buf.getvalue())
    return cam


# ------------------------------------------------------------------ 📝 ficha (IA ou à mão)
CAMPOS_FICHA = {
    "nome": 80, "aparencia_en": 2500, "aparencia_pt": 2000, "personalidade": 1500, "jeito_de_falar": 800, "bordoes": 600,
    "historia": 2500, "gostos": 800, "medos": 600, "voz": 600, "paleta": 300, "mistura": 1200, "originalidade": 800,
}
SCHEMA_FICHA = {
    "type": "object", "additionalProperties": False,
    "required": ["nomes", "aparencia_en", "aparencia_pt", "personalidade", "jeito_de_falar", "bordoes", "historia",
                 "gostos", "medos", "voz", "paleta", "mistura", "originalidade"],
    "properties": {
        "nomes": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["nome", "porque"],
                                             "properties": {"nome": {"type": "string"}, "porque": {"type": "string"}}}},
        "aparencia_en": {"type": "string"}, "aparencia_pt": {"type": "string"}, "personalidade": {"type": "string"},
        "jeito_de_falar": {"type": "string"}, "bordoes": {"type": "string"}, "historia": {"type": "string"},
        "gostos": {"type": "string"}, "medos": {"type": "string"}, "voz": {"type": "string"},
        "paleta": {"type": "string"}, "mistura": {"type": "string"}, "originalidade": {"type": "string"},
    },
}
SYS_FICHA = (
    "Você é DIRETOR DE ARTE e ROTEIRISTA criando um personagem ORIGINAL e único (não uma cópia de um que já existe). "
    "Você recebe o pedido do usuário: o texto, imagens de referência NUMERADAS (com o que pegar de cada uma), "
    "personagens famosos de inspiração (só pra pegar um ASPECTO — personalidade, jeito de falar, atitude — nunca o "
    "personagem inteiro), o estilo de arte e detalhes. Monte a FICHA:\n"
    "- nomes: 5 ideias de nome que combinam com o personagem (e com as ideias do usuário, se ele deu), cada uma com o "
    "porquê curto (significado, sonoridade, origem); o 1º é o seu favorito.\n"
    "- aparencia_en: em INGLÊS, a descrição VISUAL completa e TRAVADA pra desenhar sempre igual: tipo de corpo e altura, "
    "rosto, olhos (cor/forma), cabelo (corte/cor), pele, roupa peça por peça com as cores, acessórios, marcas que sempre "
    "aparecem — juntando o que vem de cada imagem (rosto da 1, cabelo da 2…) e o texto. Sem nomes de obras/personagens "
    "existentes. 70–150 palavras.\n"
    "- aparencia_pt: a mesma em português, curta.\n"
    "- personalidade, jeito_de_falar, bordoes (2–4 frases típicas), historia (origem/passado em 3–6 frases), gostos, "
    "medos, voz (como soa a voz, pra escolher/descrever no TTS: grave/aguda, ritmo, sotaque, energia), paleta (4–6 "
    "cores em HEX com o nome, ex.: #1E2A44 azul-noite).\n"
    "- mistura: o que veio de cada imagem e de cada inspiração (ex.: 'rosto: imagem 1; cabelo: imagem 2; personalidade: "
    "o sarcasmo do X').\n"
    "- originalidade: se o resultado ficou parecido DEMAIS com algum personagem conhecido, diga qual e o que mudar; senão "
    "'ok — original'.\n"
    "Use o português do Brasil nos campos em português. Respeite tudo que o usuário travou (marcas, o que evitar)."
)


def _pedido_txt(p: Dict[str, Any]) -> str:
    e = p["entrada"]
    L = [f"NOME (se já tiver): {p['nome']}" if p["nome"] != "Personagem novo" else "NOME: (sugira)"]
    if e.get("nomes_ideia"):
        L.append(f"IDEIAS DE NOME DO USUÁRIO: {e['nomes_ideia']}")
    if e.get("descricao"):
        L.append(f"O QUE O USUÁRIO QUER: {e['descricao']}")
    for k, r in enumerate(e["refs"]):
        L.append(f"IMAGEM {k + 1}: pegar " + ", ".join(ASPECTOS[a][0] for a in r.get("pegar") or ["tudo"] if a in ASPECTOS)
                 + (f" — {r['nota']}" if r.get("nota") else ""))
    if e.get("inspiracoes"):
        L.append(f"INSPIRAÇÕES (pegar só o aspecto dito): {e['inspiracoes']}")
    L.append(f"ESTILO DE ARTE: {estilo_nome(p)} ({estilo_en(p)})")
    if epoca_en(e):
        L.append(f"ÉPOCA: {epoca_nome(e)} ({epoca_en(e)}) — a roupa e os objetos combinam com a época")
    lg = lugar_resumo(e.get("lugar") or "", _BASE_ATUAL[0])
    if lg:
        L.append(f"DE ONDE VEM: {lg}")
    for k, rot in (("genero", "GÊNERO"), ("idade", "IDADE"), ("corpo", "CORPO/ESTATURA"), ("paleta", "PALETA"),
                   ("travas", "SEMPRE TEM (marcas travadas)"), ("evitar", "EVITAR")):
        if e.get(k):
            L.append(f"{rot}: {e[k]}")
    if e.get("original"):
        L.append("QUER UM PERSONAGEM BEM ORIGINAL (nada de cópia).")
    return "\n".join(L)


_BASE_ATUAL = [_BASE]


def lugar_resumo(lid: str, base: str = _BASE, ingles: bool = False) -> str:
    """O lugar de origem do personagem (do 🗺 Lugares e mundos), curto."""
    if not lid:
        return ""
    try:
        import criador_lugares as CL
        lg = CL.carregar(lid, base)
    except Exception:  # noqa: BLE001
        return ""
    f = lg.get("ficha") or {}
    desc = (f.get("descricao_en") if ingles else f.get("descricao_pt")) or lg["entrada"].get("descricao") or ""
    return f"{lg['nome']} ({CL.ESCALAS.get(lg['escala'], ('',))[0]}" + (f", {epoca_nome(lg['entrada'])}" if epoca_nome(lg['entrada']) else "") + f"): {desc[:400]}"


def ficha_sem_ia(p: Dict[str, Any]) -> Dict[str, Any]:
    """Sem a IA: a aparência sai dos campos (o Flow entende português)."""
    e = p["entrada"]
    partes = [e.get("descricao") or ""]
    for k in ("genero", "idade", "corpo"):
        if e.get(k):
            partes.append(e[k])
    if e.get("paleta"):
        partes.append("colors: " + e["paleta"])
    return {"aparencia_en": _txt(". ".join(x for x in partes if x), 2500), "paleta": e.get("paleta") or ""}


def aplicar_ficha(p: Dict[str, Any], r: Dict[str, Any]) -> None:
    f = p["ficha"]
    for k, n in CAMPOS_FICHA.items():
        if k in r and r[k] is not None:
            f[k] = str(r[k]).strip()[:n]
    if isinstance(r.get("nomes"), list):
        f["nomes"] = [{"nome": _txt(x.get("nome"), 60), "porque": _txt(x.get("porque"), 200)}
                      for x in r["nomes"] if isinstance(x, dict) and x.get("nome")][:8]
        if f["nomes"] and p["nome"] == "Personagem novo":
            p["nome"] = f["nomes"][0]["nome"]
    if f.get("nome"):
        p["nome"] = f["nome"]


def _ia():
    import ia_servico
    return ia_servico


def ia_ligada() -> bool:
    try:
        return _ia().ativo("criador")
    except Exception:  # noqa: BLE001
        return False


def montar_ficha(pid: str, base: str = _BASE) -> str:
    """🤖 A IA olha as imagens numeradas + o pedido e escreve a ficha (nomes, aparência travada, personalidade…)."""
    p = carregar(pid, base)
    _BASE_ATUAL[0] = base
    if not ia_ligada():
        with _TRAVA:
            p = carregar(pid, base)
            aplicar_ficha(p, ficha_sem_ia(p))
            log(p, "📝 ficha montada dos campos (a 🤖 IA está desligada — dá pra escrever o resto à mão)")
            salvar(p, base)
        return "sem IA: a aparência veio dos campos"
    conteudo: List[Dict[str, Any]] = [{"type": "text", "text": _pedido_txt(p)}]
    for k, r in enumerate(p["entrada"]["refs"]):
        b = _ia().imagem_bloco(os.path.join(pasta(pid, base), "refs", r["arquivo"]), 512)
        if b:
            conteudo += [{"type": "text", "text": f"IMAGEM {k + 1}:"}, b]
    r = _ia().chamar("criador", SYS_FICHA, conteudo, schema=SCHEMA_FICHA, max_tokens=3000, effort="medium", timeout=150)
    if not isinstance(r, dict):
        raise CriadorErro("A IA não respondeu — tente de novo (ou escreva a ficha à mão).")
    with _TRAVA:
        p = carregar(pid, base)
        aplicar_ficha(p, r)
        log(p, "🤖 ficha montada pela IA")
        salvar(p, base)
    return "ficha pronta"


def editar_ficha(p: Dict[str, Any], dados: Dict[str, Any]) -> None:
    aplicar_ficha(p, {k: v for k, v in dados.items() if k in CAMPOS_FICHA})


# ------------------------------------------------------------------ 🎨 design no Flow
def prompt_design(p: Dict[str, Any], k: int = 0, n: int = 1, correcao: str = "", a_partir: bool = False) -> str:
    e, f = p["entrada"], p["ficha"]
    L: List[str] = []
    refs = e["refs"]
    if a_partir:
        L.append("The reference image is a previous design of this character. Keep it as the base — same identity and "
                 "overall design — and apply the changes asked below.")
    elif refs:
        clone = len(refs) == 1 and "tudo" in (refs[0].get("pegar") or [])
        if clone:
            L.append("The reference image (panel 1) shows a character to use as the BASE: keep it recognizable, but apply "
                     "the changes described below" + (" and redesign it enough to be a NEW original character" if e.get("original") else "") + ".")
        else:
            L.append(f"The reference image is a collage of {len(refs)} NUMBERED panels (big yellow number in the corner of "
                     "each). Build ONE new character by combining exactly these parts: " + "; ".join(mapa_refs(p)) + ". "
                     "Everything not listed comes from the description below, NOT from the panels.")
    L.append("Character design of " + ("an ORIGINAL character (not an existing one)" if e.get("original") else "the character")
             + (f" named {p['nome']}" if p["nome"] and p["nome"] != "Personagem novo" else "") + ".")
    aparencia = f.get("aparencia_en") or ficha_sem_ia(p)["aparencia_en"]
    if aparencia:
        L.append(f"Appearance: {aparencia}")
    if e.get("descricao") and not f.get("aparencia_en"):
        pass  # (já vai na aparência montada dos campos)
    for kk, rot in (("genero", "Gender"), ("idade", "Age"), ("corpo", "Body / height")):
        if e.get(kk) and not f.get("aparencia_en"):
            L.append(f"{rot}: {e[kk]}.")
    if f.get("paleta") or e.get("paleta"):
        L.append(f"Color palette: {f.get('paleta') or e.get('paleta')}.")
    if e.get("travas"):
        L.append(f"ALWAYS keep these marks: {e['travas']}.")
    if e.get("evitar"):
        L.append(f"Avoid: {e['evitar']}.")
    if f.get("personalidade"):
        L.append(f"Let the personality show in the pose and face: {f['personalidade'][:300]}")
    if epoca_en(e):
        L.append(f"Era: {epoca_en(e)} — the outfit, hair and props fit this era.")
    lg = lugar_resumo(e.get("lugar") or "", _BASE_ATUAL[0], ingles=True)
    if lg:
        L.append(f"Comes from: {lg}")
    L.append(f"ART STYLE: {estilo_en(p)}.")
    L.append("Framing: ONE single figure, FULL BODY from head to feet with margin, standing in a relaxed natural pose, "
             "facing the viewer (slight three-quarter), the whole outfit clearly visible; " + _FUNDO + ", no shadow on the "
             "background, no text, no panels, no character sheet, no other characters.")
    if n > 1 and not a_partir:
        L.append(f"Variation {k + 1} of {n}: explore a different take on the details that were NOT specified (keep "
                 "everything that was).")
    if correcao:
        L.append(f"CHANGES FOR THIS ATTEMPT: {correcao}")
    return " ".join(" ".join(L).split())[:3900]


def variacao(p: Dict[str, Any], vid: str) -> Dict[str, Any]:
    v = next((x for x in p["design"]["variacoes"] if x["id"] == vid), None)
    if not v:
        raise CriadorErro("Variação não encontrada.")
    return v


def aprovada(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    a = p["design"].get("aprovado")
    return next((x for x in p["design"]["variacoes"] if x["id"] == a and x.get("arquivo")), None)


def gerar_design(pid: str, base: str = _BASE, n: int = 4, correcao: str = "", a_partir: str = "") -> Dict[str, Any]:
    """🚀 N variações do design pro Flow (com a colagem numerada das referências — ou uma variação de base)."""
    import flow_lote
    n = max(1, min(MAX_VARIACOES, int(n or 1)))
    _BASE_ATUAL[0] = base
    with _TRAVA:
        p = carregar(pid, base)
        if not (p["ficha"].get("aparencia_en") or p["entrada"].get("descricao") or p["entrada"]["refs"]):
            raise CriadorErro("Descreva o personagem ou mande pelo menos uma imagem de referência.")
        ref = None
        if a_partir:
            v0 = variacao(p, a_partir)
            ref = os.path.join(pasta(pid, base), "design", v0.get("bruto") or "")
            if not v0.get("bruto") or not os.path.isfile(ref):
                raise CriadorErro("Essa variação ainda não tem imagem.")
            n = max(1, min(n, 2))
        else:
            ref = colagem_numerada(p, base)
        itens = []
        for k in range(n):
            it = {"prompt": prompt_design(p, k, n, _txt(correcao, 800), bool(a_partir)), "tipo": "imagem", "origem": "criador"}
            if ref:
                it["referencia_arquivo"] = ref
            itens.append(it)
        lote = flow_lote.lote()
        try:
            novos = lote.adicionar(itens, proporcao="3:4", quantidade="x1")
        except ValueError as exc:
            raise CriadorErro(str(exc))
        for it, j in zip(itens, novos):
            p["design"]["variacoes"].append({"id": "v" + secrets.token_hex(3), "estado": "fila", "job": j["id"], "erro": None,
                                             "msg": "⏳ na fila do Flow", "prompt": it["prompt"], "correcao": _txt(correcao, 300),
                                             "de": a_partir or None, "criado": time.time()})
        log(p, f"🎨 {n} variação(ões) do design pro Flow" + (f" (a partir de {a_partir})" if a_partir else "")
            + (f" · {correcao[:60]}" if correcao else ""))
        salvar(p, base)
    aviso = ""
    try:
        lote.iniciar()
    except Exception as exc:  # noqa: BLE001
        aviso = f"o Flow em massa não ligou agora ({str(exc)[:160]}) — ▶ Continuar na aba Flow"
    return {"enviadas": n, "aviso": aviso}


def guardar_design(p: Dict[str, Any], v: Dict[str, Any], img, base: str = _BASE) -> None:
    """A imagem do Flow (fundo verde) → o bruto + o PNG transparente."""
    import personagens_limpeza as L
    d = os.path.join(pasta(p["id"], base), "design")
    os.makedirs(d, exist_ok=True)
    bruto = f"{v['id']}_bruto.png"
    img.convert("RGB").save(os.path.join(d, bruto))
    try:
        final, info = L.recortar(img.convert("RGB"), (1200, 1800), 0.95, corpo_inteiro=True)
        aviso = info.get("aviso")
    except Exception as exc:  # noqa: BLE001
        final, aviso = img.convert("RGBA"), f"o recorte falhou ({str(exc)[:80]}) — ficou com o fundo"
    arq = f"{v['id']}.png"
    final.save(os.path.join(d, arq), optimize=True)
    v.update(estado="pronta", arquivo=arq, bruto=bruto, erro=None, msg=None, aviso=aviso)


def enviar_imagem_design(pid: str, img, base: str = _BASE) -> Dict[str, Any]:
    """📤 Uma imagem sua como variação (ex.: o design que você mesmo desenhou/ajustou)."""
    with _TRAVA:
        p = carregar(pid, base)
        v = {"id": "v" + secrets.token_hex(3), "estado": "fila", "job": None, "origem": "upload", "criado": time.time()}
        p["design"]["variacoes"].append(v)
        guardar_design(p, v, img, base)
        log(p, "📤 design enviado por você")
        salvar(p, base)
        return v


def aprovar(pid: str, vid: str, base: str = _BASE) -> None:
    with _TRAVA:
        p = carregar(pid, base)
        v = variacao(p, vid)
        if not v.get("arquivo"):
            raise CriadorErro("Essa variação ainda não tem imagem.")
        p["design"]["aprovado"] = vid
        log(p, f"✔ design aprovado ({vid})")
        salvar(p, base)


def apagar_variacao(pid: str, vid: str, base: str = _BASE) -> None:
    with _TRAVA:
        p = carregar(pid, base)
        v = variacao(p, vid)
        p["design"]["variacoes"].remove(v)
        if p["design"].get("aprovado") == vid:
            p["design"]["aprovado"] = None
        salvar(p, base)


# ------------------------------------------------------------------ 🧍 poses (um projeto da aba 🧍 Personagens)
def _slug(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:40] or "personagem"


def poses_json(p: Dict[str, Any], pacotes: List[str], extras: Optional[List[str]] = None) -> Dict[str, Any]:
    sl = _slug(p["nome"])
    f, e = p["ficha"], p["entrada"]
    aparencia = f.get("aparencia_en") or ficha_sem_ia(p)["aparencia_en"] or p["nome"]
    trava = (f"CHARACTER LOCK: {p['nome']}. Appearance: {aparencia}"
             + (f" Era: {epoca_en(e)}." if epoca_en(e) else "")
             + (f" ALWAYS: {e['travas']}." if e.get("travas") else "")
             + " Keep exactly the same face, hairstyle, eye color, body proportions, outfit and colors in every image.")
    regras = ("ONE single figure, no text, no panels, whole figure inside the image with margin, on a " + _FUNDO
              + ", no shadow on the background. Do not draw furniture or props unless the pose asks for one.")
    poses = [{"arquivo": f"{sl}_design.png", "tipo": "pose", "mestre": True, "grupo": "design", "prioridade": 1,
              "descricao_pt": "⭐ o design aprovado", "prompt": "standing in a relaxed natural pose, facing the viewer, full body."}]
    vistos = {poses[0]["arquivo"]}
    for pk in pacotes:
        if pk not in PACOTES:
            continue
        for suf, pt, en in PACOTES[pk][1]:
            a = f"{sl}_{suf}.png"
            if a in vistos:
                continue
            vistos.add(a)
            poses.append({"arquivo": a, "tipo": "pose", "grupo": pk, "prioridade": 1 if pk == "giro" else 2,
                          "descricao_pt": f"{PACOTES[pk][0].split(' ')[0]} {pt}", "prompt": en + "."})
    for k, x in enumerate(extras or []):
        x = _txt(x, 300)
        if not x:
            continue
        a = f"{sl}_extra{k + 1}.png"
        poses.append({"arquivo": a, "tipo": "pose", "grupo": "extra", "prioridade": 2, "descricao_pt": f"✍ {x[:60]}",
                      "prompt": x})
    return {"formato": "personagens_pod_v1", "personagem": sl, "nome": p["nome"], "criador": p["id"],
            "descricoes_referencias": {"design.png": "the APPROVED character design (the character to keep)"},
            "texto_fixo": {"trava": trava, "estilo": "ART STYLE: " + estilo_en(p) + ".", "regras": regras},
            "fundo": "verde", "canvas": [1200, 1800], "altura_personagem": 0.95, "corpo_inteiro": True,
            "boca_auto": False, "flow": {"proporcao": "3:4"}, "poses": poses}


def criar_poses(pid: str, pacotes: List[str], extras: Optional[List[str]] = None, base: str = _BASE) -> Dict[str, Any]:
    """🧍 O design aprovado vira a ⭐ mestre de um projeto da aba 🧍 Personagens (já aprovado) e as poses escolhidas
    vão pro Flow. Rodar de novo com pacotes novos: as que já existem ficam, as novas entram e vão pro Flow."""
    import personagens_pod as pp
    p = carregar(pid, base)
    ap = aprovada(p)
    if not ap:
        raise CriadorErro("Aprove um design primeiro (✔ na variação que ficou melhor).")
    pacotes = [k for k in pacotes or [] if k in PACOTES]
    extras = [x for x in (extras or []) if _txt(x, 300)]
    if not pacotes and not extras:
        raise CriadorErro("Escolha pelo menos um pacote de poses (ou escreva uma pose).")
    dados = poses_json(p, pacotes, extras)
    d_des = os.path.join(pasta(pid, base), "design")
    with open(os.path.join(d_des, ap["bruto"]), "rb") as f:
        bruto_bytes = f.read()
    ppid = p["poses"].get("pod")
    proj = None
    if ppid:
        try:
            proj = pp.carregar(ppid, base)
        except pp.PersErro:
            proj = None
    if proj is None:
        proj = pp.criar(f"🧬 {p['nome']}", json.dumps(dados, ensure_ascii=False), [("design.png", bruto_bytes)], base=base,
                        motor="flow")
        ppid = proj["id"]
    else:  # ♻ as poses que já existem continuam; as novas entram
        velhas = {x["arquivo"] for x in proj["dados"]["poses"]}
        dados["poses"] = proj["dados"]["poses"] + [x for x in dados["poses"] if x["arquivo"] not in velhas]
        proj = pp.trocar_json(ppid, json.dumps(dados, ensure_ascii=False), base)
    # ⭐ o design aprovado entra pronto como a mestre (não precisa gerar de novo)
    mestre = dados["poses"][0]["arquivo"]
    with pp._TRAVA:
        proj = pp.carregar(ppid, base)
        d_pp = pp._pasta(ppid, base)
        os.makedirs(os.path.join(d_pp, "brutos"), exist_ok=True)
        os.makedirs(os.path.join(d_pp, "imagens"), exist_ok=True)
        it = proj["imagens"].setdefault(mestre, {"estado": "nova", "versoes": [], "atual": -1, "erro": None, "job": None})
        if not it.get("versoes") or (proj.get("mestre") or {}).get("criador_v") != ap["id"]:
            local = f"{mestre[:-4]}_v{len(it['versoes']) + 1}_{secrets.token_hex(2)}.png"
            bruto = local[:-4] + "_flow.png"
            shutil.copyfile(os.path.join(d_des, ap["arquivo"]), os.path.join(d_pp, "imagens", local))
            shutil.copyfile(os.path.join(d_des, ap["bruto"]), os.path.join(d_pp, "brutos", bruto))
            it["versoes"].append({"local": local, "bruto": bruto, "job": None, "motor": "criador", "quando": time.time()})
            it.update(atual=len(it["versoes"]) - 1, estado="aprovada", erro=None)
            proj["mestre"] = {"arquivo": mestre, "local": local, "quando": time.time(), "bruto": bruto, "criador_v": ap["id"]}
            pp.salvar(proj, base)
    proj = pp.carregar(ppid, base)
    faltam = [x["arquivo"] for x in proj["dados"]["poses"]
              if x["arquivo"] != mestre and not pp.arquivo_atual(proj, x["arquivo"], base)
              and (proj["imagens"].get(x["arquivo"]) or {}).get("estado") not in ("fila", "gerando")]
    r = pp.enviar(ppid, faltam, base=base) if faltam else {"enviadas": 0, "aviso": ""}
    with _TRAVA:
        p = carregar(pid, base)
        p["poses"].update(pod=ppid, pacotes=sorted(set(p["poses"].get("pacotes") or []) | set(pacotes)))
        log(p, f"🧍 {len(faltam)} pose(s) pro Flow (projeto 🧍 {ppid})")
        salvar(p, base)
    return {"pod": ppid, "enviadas": int(r.get("enviadas") or 0), "aviso": r.get("aviso") or ""}


def estado_poses(p: Dict[str, Any], base: str = _BASE) -> Dict[str, Any]:
    import personagens_pod as pp
    ppid = p["poses"].get("pod")
    if not ppid:
        return {"tem": False}
    try:
        proj = pp.carregar(ppid, base)
    except pp.PersErro:
        return {"tem": False, "erro": "o projeto 🧍 foi apagado"}
    itens = []
    for x in proj["dados"]["poses"]:
        it = proj["imagens"].get(x["arquivo"]) or {}
        cam = pp.arquivo_atual(proj, x["arquivo"], base)
        itens.append({"arquivo": x["arquivo"], "descricao": x.get("descricao_pt") or x["arquivo"], "estado": it.get("estado"),
                      "erro": it.get("erro"), "img": os.path.basename(cam) if cam else None})
    return {"tem": True, "pid": ppid, "itens": itens}


# ------------------------------------------------------------------ ⏱ acompanhar o Flow
def acompanhar(pid: str, base: str = _BASE) -> bool:
    """Puxa da fila do Flow as variações do design que ficaram prontas; sincroniza o projeto 🧍 das poses."""
    mudou = False
    p = carregar(pid, base)
    if any(v.get("estado") in ESPERA for v in p["design"]["variacoes"]):
        import flow_lote
        lote = flow_lote.lote()
        with lote.trava:
            fila = {j["id"]: dict(j) for j in lote.fila}
            rodando = lote.rodando
        with _TRAVA:
            p = carregar(pid, base)
            for v in p["design"]["variacoes"]:
                if v.get("estado") not in ESPERA or not v.get("job"):
                    continue
                fj = fila.get(v["job"])
                antes = (v.get("estado"), v.get("msg"))
                if fj is None:
                    v.update(estado="erro", erro="o pedido sumiu da fila do 🚀 Flow em massa — gere de novo")
                elif fj["estado"] == "ok":
                    ok = False
                    for r in fj.get("resultados") or []:
                        try:
                            import flow_estudio as FE
                            from PIL import Image
                            orig = os.path.join(FE.pasta_galeria(), r.get("arquivo") or "")
                            if r.get("tipo") == "imagem" and os.path.isfile(orig):
                                guardar_design(p, v, Image.open(orig), base)
                                ok = True
                                break
                        except Exception as exc:  # noqa: BLE001
                            v.update(estado="erro", erro=f"a imagem chegou mas não deu pra guardar: {str(exc)[:160]}")
                    if ok:
                        log(p, f"🎨 variação {v['id']} pronta")
                    elif v.get("estado") != "erro":
                        v.update(estado="erro", erro="o Flow terminou sem imagem")
                elif fj["estado"] == "erro":
                    v.update(estado="erro", erro=str(fj.get("erro") or "o Flow falhou")[:300])
                elif fj["estado"] in ("rodando", "convertendo"):
                    v.update(estado="gerando", msg=f"🎨 gerando no Flow (conta “{fj.get('conta')}”)")
                elif not rodando:
                    v.update(msg="⏸ o Flow em massa está parado — ▶ Continuar na aba Flow")
                else:
                    v.update(msg="⏳ na fila do Flow")
                mudou = mudou or antes != (v.get("estado"), v.get("msg"))
            if mudou:
                salvar(p, base)
    if p["poses"].get("pod"):
        try:
            import personagens_pod as pp
            pp.sincronizar(p["poses"]["pod"], base)
        except Exception:  # noqa: BLE001
            pass
    return mudou


# ------------------------------------------------------------------ ⬇ zip / ficha em texto / tela
def ficha_txt(p: Dict[str, Any]) -> str:
    f, e = p["ficha"], p["entrada"]
    L = [f"🧬 {p['nome']}", f"Estilo: {estilo_nome(p)}" + (f" · Época: {epoca_nome(e)}" if epoca_nome(e) else ""),
         (f"De onde vem: {lugar_resumo(e.get('lugar') or '', _BASE_ATUAL[0])}" if e.get("lugar") else ""), ""]
    for k, rot in (("aparencia_pt", "Aparência"), ("personalidade", "Personalidade"), ("jeito_de_falar", "Jeito de falar"),
                   ("bordoes", "Bordões"), ("historia", "História"), ("gostos", "Gostos"), ("medos", "Medos"),
                   ("voz", "Voz"), ("paleta", "Paleta"), ("mistura", "De onde veio cada coisa"),
                   ("originalidade", "Originalidade"), ("aparencia_en", "Aparência (inglês, pros prompts)")):
        if f.get(k):
            L += [f"{rot}:", f[k], ""]
    if f.get("nomes"):
        L += ["Ideias de nome:"] + [f"- {x['nome']}: {x['porque']}" for x in f["nomes"]] + [""]
    if e.get("travas"):
        L += ["Sempre tem:", e["travas"], ""]
    return "\n".join(L).strip() + "\n"


def zip_personagem(pid: str, base: str = _BASE) -> bytes:
    p = carregar(pid, base)
    buf = io.BytesIO()
    sl = _slug(p["nome"])
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{sl}/ficha.txt", ficha_txt(p))
        z.writestr(f"{sl}/ficha.json", json.dumps({"nome": p["nome"], "estilo": estilo_nome(p), "estilo_en": estilo_en(p),
                                                    "ficha": p["ficha"], "entrada": {k: v for k, v in p["entrada"].items() if k != "refs"}},
                                                   ensure_ascii=False, indent=1))
        ap = aprovada(p)
        if ap:
            z.write(os.path.join(pasta(pid, base), "design", ap["arquivo"]), f"{sl}/{sl}_design.png")
        if p["poses"].get("pod"):
            try:
                import personagens_pod as pp
                proj = pp.carregar(p["poses"]["pod"], base)
                for x in proj["dados"]["poses"]:
                    cam = pp.arquivo_atual(proj, x["arquivo"], base)
                    if cam and (proj["imagens"].get(x["arquivo"]) or {}).get("estado") in ("aprovada", "pronta"):
                        z.write(cam, f"{sl}/poses/{x['arquivo']}")
            except Exception:  # noqa: BLE001
                pass
    return buf.getvalue()


def para_tela(p: Dict[str, Any], base: str = _BASE) -> Dict[str, Any]:
    out = dict(p)
    out["estilo_en"] = estilo_en(p)
    out["estilo_nome"] = estilo_nome(p)
    out["epoca_nome"] = epoca_nome(p["entrada"])
    out["ia"] = ia_ligada()
    out["mapa_refs"] = mapa_refs(p)
    out["poses_estado"] = estado_poses(p, base)
    ap = aprovada(p)
    out["aprovada"] = ap["id"] if ap else None
    return out
