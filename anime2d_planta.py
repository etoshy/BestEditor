"""📐 Animação 2D — a PLANTA de cada cenário (o "layout" de anime, v84_238f).

Num anime adaptado de mangá, cada lugar é pensado como um PALCO antes de desenhar: de onde a câmera olha, o que fica em
cada parede, onde está cada objeto (e de que tamanho), o que é móvel separado (camada) e o que fica FORA do quadro. A
planta guarda isso e vira:
- 🗺 um ESBOÇO DE LAYOUT (blocos coloridos numa caixa cinza = o cômodo), mandado como 1ª referência pro Flow gerar o
  fundo com cada coisa no lugar certo — e o texto do pedido diz que bloco é o quê;
- o texto de layout no pedido do fundo (posição em palavras: terço, % da largura, altura, parede);
- as posições iniciais dos móveis (camadas) — o mesmo x/y da planta;
- o que a IA diretora lê pra decidir o que o público vê em cada momento.

Formato (local["planta"]):
    {"camera": "de onde a câmera geral olha (pt)", "camera_en": "...", "luz_en": "...",
     "fora_de_quadro": "o que existe mas não aparece no plano geral (pt)", "fora_de_quadro_en": "...",
     "elementos": [{"nome": "Fornalha", "en": "a big round cast-iron furnace…", "onde": "direita",
                    "x": 0.8, "y": 0.92, "w": 0.3, "h": 0.55, "camada": "fundo" | "movel", "visivel": true}]}
x = o CENTRO na largura do quadro (0 = esquerda, 1 = direita); y = a BASE (onde encosta no chão / a parte de baixo);
w, h = largura e altura (frações do quadro). camada "movel" = é um 🪑 móvel separado (o fundo deixa o espaço vazio).

Ângulos: um local com "angulo_de" = outro local é o MESMO cômodo visto de outra câmera (contraplano, o canto da
fornalha de perto…) — tem a sua planta, os seus lugares e o seu chão; o fundo sai com o original como referência de
objetos, materiais e cores. Um momento usa um ângulo com momento["angulo"] = o id/nome desse local.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional

ONDE = ("fundo", "esquerda", "direita", "chao", "teto", "frente")
CORES = [("RED", (215, 45, 45)), ("BLUE", (45, 95, 225)), ("GREEN", (40, 170, 75)), ("YELLOW", (240, 205, 35)),
         ("PURPLE", (140, 60, 195)), ("ORANGE", (245, 135, 25)), ("CYAN", (35, 195, 215)), ("PINK", (240, 115, 185)),
         ("BROWN", (125, 80, 40)), ("LIME", (150, 215, 45)), ("NAVY", (25, 35, 120)), ("TEAL", (20, 130, 120))]
SCHEMA_PLANTA = {
    "type": "object", "additionalProperties": False,
    "required": ["camera", "camera_en", "fora_de_quadro", "fora_de_quadro_en", "elementos"],
    "properties": {
        "camera": {"type": "string"}, "camera_en": {"type": "string"},
        "fora_de_quadro": {"type": "string"}, "fora_de_quadro_en": {"type": "string"},
        "elementos": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["nome", "en", "onde", "x", "y", "w", "h", "camada", "forma"],
            "properties": {"nome": {"type": "string"}, "en": {"type": "string"},
                           "onde": {"type": "string", "enum": list(ONDE)},
                           "x": {"type": "number"}, "y": {"type": "number"}, "w": {"type": "number"}, "h": {"type": "number"},
                           "camada": {"type": "string", "enum": ["fundo", "movel"]},
                           "forma": {"type": "string", "enum": ["retangulo", "redondo"]}}}}}}

INSTRUCOES_IA = (
    "- 📐 PLANTA de cada local (pense como o LAYOUT de um anime, antes de desenhar): o lugar é um palco. 'camera' = de "
    "onde a câmera do plano geral olha e pra qual parede (ex.: \"da porta, olhando a parede da janela\"); 'elementos' = "
    "TUDO o que aparece no plano geral, cada um com: 'onde' (parede do fundo/esquerda/direita, chão, teto, frente), 'x' = "
    "o centro na largura do quadro (0 = borda esquerda, 1 = borda direita), 'y' = a BASE dele (onde encosta no chão ou a "
    "parte de baixo; 0 = topo, 1 = base do quadro; o chão do fundo fica por volta de 0,72 e o da frente perto de 1), "
    "'w'/'h' = largura e altura em frações do quadro (pense no tamanho REAL: porta ~2 m, pessoa ~1,6 m, poltrona ~1 m), "
    "'en' = descrição em inglês, 'camada' = 'movel' se é um dos móveis separados (props) e 'fundo' se vai pintado no "
    "fundo, 'forma' = 'redondo' pra coisas redondas (janela redonda, fornalha, relógio) senão 'retangulo'. Deixe ESPAÇO LIVRE no chão onde os personagens andam e ficam. 'fora_de_quadro' = o que existe no lugar mas "
    "NÃO aparece no plano geral (atrás da câmera, a outra parede). Coerência: o mesmo objeto fica sempre no mesmo lugar "
    "em todas as cenas.\n"
    "- 🎥 ÂNGULOS: a câmera troca de ângulo sozinha a cada ~10 s (pode repetir) — então todo lugar onde a ação dura "
    "mais de ~20 s precisa de 1–2 ÂNGULOS além da câmera principal (contraplano, a parede atrás da câmera, o canto onde "
    "a ação acontece de perto), cada um com os LUGARES de quem fica ali (os mesmos nomes de lugar da câmera principal "
    "quando é o mesmo ponto). Se alguma cena precisa ver OUTRO lado do lugar, crie um local a mais com 'angulo_de' = o nome do local principal e 'angulo_en' = onde a câmera está agora "
    "(em inglês), com a planta DESSE ângulo (mesmos objetos, mesmas cores, outra vista). 'variante_de' = o MESMO "
    "enquadramento em outro estado (cheio de fumaça, de noite, destruído) — sem planta própria. Os dois \"\" se não "
    "for o caso.\n")


def _f(v: Any, padrao: float, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return round(max(lo, min(hi, float(v))), 4)
    except (TypeError, ValueError):
        return padrao


def _t(v: Any, n: int = 400) -> str:
    return " ".join(str(v or "").split())[:n]


def normalizar(x: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(x, dict):
        return None
    els = []
    for e in x.get("elementos") or []:
        if not isinstance(e, dict) or not _t(e.get("nome")):
            continue
        els.append({"nome": _t(e["nome"], 60), "en": _t(e.get("en") or e.get("prompt_en"), 300),
                    "onde": e.get("onde") if e.get("onde") in ONDE else "fundo",
                    "x": _f(e.get("x"), 0.5), "y": _f(e.get("y"), 0.9), "w": _f(e.get("w"), 0.2, 0.01), "h": _f(e.get("h"), 0.3, 0.01),
                    "camada": "movel" if e.get("camada") == "movel" else "fundo",
                    "forma": "redondo" if e.get("forma") == "redondo" else "retangulo",
                    "visivel": e.get("visivel") is not False})
    out = {k: _t(x.get(k), 400) for k in ("camera", "camera_en", "fora_de_quadro", "fora_de_quadro_en", "luz_en")}
    out["elementos"] = els[:24]
    return out if els or out["camera"] or out["camera_en"] else None


def _onde_en(e: Dict[str, Any]) -> str:
    x = e["x"]
    terco = "in the LEFT third" if x < 0.34 else "in the CENTER" if x < 0.66 else "in the RIGHT third"
    parede = {"fundo": "against the back wall", "esquerda": "on the left side wall", "direita": "on the right side wall",
              "chao": "on the floor", "teto": "hanging from the ceiling", "frente": "in the foreground, close to the camera"}[e["onde"]]
    return (f"{terco} (its center at {round(x * 100)}% from the left edge), {parede}, about {round(e['w'] * 100)}% of the "
            f"frame width and {round(e['h'] * 100)}% of its height, its bottom at {round(e['y'] * 100)}% of the frame height")


def visiveis(pl: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [e for e in (pl or {}).get("elementos") or [] if e.get("visivel", True)]


def texto_en(pl: Optional[Dict[str, Any]], com_esboco: bool = True) -> str:
    """O pedaço do pedido do fundo que diz ONDE fica cada coisa."""
    els = visiveis(pl)
    if not pl or not (els or pl.get("camera_en")):
        return ""
    L = []
    if pl.get("camera_en"):
        L.append(f"CAMERA: {pl['camera_en']}.")
    if els:
        if com_esboco:
            L.append("LAYOUT — the FIRST reference image is a flat LAYOUT SKETCH of this exact shot (the gray box is the room: "
                     "back wall, side walls, floor). Put every element exactly where its colored block is and at that size; the "
                     "sketch is only a map — do NOT copy its flat colors, blocks or gray look.")
        else:
            L.append("LAYOUT (follow exactly):")
        k = 0
        moveis = []
        for e in els:
            if e["camada"] == "movel":
                moveis.append(e)
                continue
            cor = CORES[k % len(CORES)][0]
            k += 1
            bloco = (cor + (" circle = " if e.get("forma") == "redondo" else " block = ")) if com_esboco else "- "
            L.append(f"{bloco}{e['en'] or e['nome']}: {_onde_en(e)}.")
        if moveis:
            L.append(("The WHITE DASHED boxes" if com_esboco else "The areas of") + " " +
                     "; ".join(f"{e['en'] or e['nome']} ({_onde_en(e)})" for e in moveis) +
                     " — keep those areas EMPTY wall/floor: that furniture is a separate layer added later.")
    if pl.get("fora_de_quadro_en"):
        L.append(f"NOT in this shot (out of frame, behind the camera): {pl['fora_de_quadro_en']}.")
    if pl.get("luz_en"):
        L.append(f"LIGHT: {pl['luz_en']}.")
    return " ".join(L)


def descricao_pt(pl: Optional[Dict[str, Any]]) -> str:
    """A planta em português (pra IA diretora e pra tela)."""
    if not pl:
        return ""
    L = []
    if pl.get("camera"):
        L.append(f"câmera: {pl['camera']}")
    for e in pl.get("elementos") or []:
        lado = "esquerda" if e["x"] < 0.34 else "centro" if e["x"] < 0.66 else "direita"
        L.append(f"{e['nome']} ({'🪑 móvel' if e['camada'] == 'movel' else e['onde']}, {lado}, x={e['x']:.2f}"
                 + ("" if e.get("visivel", True) else ", fora do quadro") + ")")
    if pl.get("fora_de_quadro"):
        L.append(f"fora do quadro: {pl['fora_de_quadro']}")
    return "; ".join(L)


def esboco(pl: Optional[Dict[str, Any]], destino_dir: str, W: int, H: int, chao_fundo: float = 0.72) -> Optional[str]:
    """🗺 O esboço de layout (sem texto nenhum): o cômodo em caixa cinza e cada elemento num bloco colorido — os móveis
    separados em caixa branca tracejada (= deixe vazio)."""
    els = visiveis(pl)
    if not els:
        return None
    from PIL import Image, ImageDraw
    esc = 1024 / max(W, H)
    w, h = int(W * esc), int(H * esc)
    chave = hashlib.sha1(json.dumps([els, w, h, round(chao_fundo, 3)], sort_keys=True).encode()).hexdigest()[:12]
    os.makedirs(destino_dir, exist_ok=True)
    dst = os.path.join(destino_dir, f"_planta_{chave}.png")
    if os.path.isfile(dst):
        return dst
    im = Image.new("RGB", (w, h), (120, 120, 120))
    d = ImageDraw.Draw(im)
    yf = max(0.3, min(0.95, chao_fundo)) * h
    xl, xr = 0.1 * w, 0.9 * w
    d.polygon([(xl, 0), (xr, 0), (xr, yf), (xl, yf)], fill=(178, 178, 178), outline=(60, 60, 60))   # parede do fundo
    d.polygon([(0, 0), (xl, 0), (xl, yf), (0, h)], fill=(150, 150, 150), outline=(60, 60, 60))       # parede esquerda
    d.polygon([(xr, 0), (w, 0), (w, h), (xr, yf)], fill=(150, 150, 150), outline=(60, 60, 60))       # parede direita
    d.polygon([(0, h), (xl, yf), (xr, yf), (w, h)], fill=(110, 110, 110), outline=(60, 60, 60))      # chão
    k = 0
    for e in els:
        x0, x1 = (e["x"] - e["w"] / 2) * w, (e["x"] + e["w"] / 2) * w
        y0, y1 = (e["y"] - e["h"]) * h, e["y"] * h
        if e["camada"] == "movel":
            for i in range(int(x0), int(x1), 14):  # tracejado
                d.line([(i, y0), (min(i + 7, x1), y0)], fill=(255, 255, 255), width=3)
                d.line([(i, y1), (min(i + 7, x1), y1)], fill=(255, 255, 255), width=3)
            for j in range(int(y0), int(y1), 14):
                d.line([(x0, j), (x0, min(j + 7, y1))], fill=(255, 255, 255), width=3)
                d.line([(x1, j), (x1, min(j + 7, y1))], fill=(255, 255, 255), width=3)
            continue
        cor = CORES[k % len(CORES)][1]
        k += 1
        if e.get("forma") == "redondo":
            d.ellipse([x0, y0, x1, y1], fill=cor, outline=(20, 20, 20), width=2)
        else:
            d.rectangle([x0, y0, x1, y1], fill=cor, outline=(20, 20, 20), width=2)
    im.save(dst)
    return dst


def sincronizar_moveis(lo: Dict[str, Any]) -> None:
    """Os 🪑 móveis da planta → a posição inicial do móvel (camada) de mesmo nome, se ele ainda não tem uma."""
    import react_personagens as R
    for e in (lo.get("planta") or {}).get("elementos") or []:
        if e.get("camada") != "movel":
            continue
        pr = next((z for z in lo.get("props") or [] if R._norm(z["nome"]) == R._norm(e["nome"])), None)
        if pr is None:
            continue
        pr.setdefault("x", e["x"])
        pr.setdefault("y", e["y"])
        if not pr.get("real") and not pr.get("w_manual"):
            pr.setdefault("w", e["w"])
