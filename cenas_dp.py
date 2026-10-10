"""
Cenas e takes no estilo do DarkPlanner Studio.

O catálogo (assets/darkplanner/cenas_catalogo.json) veio do message.json do
DarkPlanner: nome, número de slots, durações mínima/ideal/máxima, fundos,
movimentos, campos de texto e quando usar/não usar cada template. O JSON não
traz o visual em si — aqui cada template é RECRIADO com ffmpeg a partir da
família dele (moldura, retrato, frente & fundo, lado a lado, tríade, mosaico…).

Como funciona (igual à regra do DarkPlanner):
  * "slots" = quantos TRECHOS SEGUIDOS a cena cobre. Um template de 2 slots
    aplicado no trecho 5 usa a mídia do trecho 5 e do 6; cada take ENTRA no
    próprio tempo da fala e os anteriores continuam na tela.
  * Campos "speech" (legenda, legenda:1…) mostram a fala do take e COBREM a
    legenda normal naquele intervalo (a legenda queimada some ali).
  * Campos fixos ("TÓPICO", "CAPÍTULO", "ANTES"…) são espaços pro texto do
    roteiro — rótulo de fábrica não aparece (só os que fazem sentido sozinhos,
    como ANTES/DEPOIS, VS, 01/02/03).
  * Os "Shutter" do DarkPlanner viram TRANSIÇÕES (ver `SHUTTERS`).
  * Templates de Avatar não entram (o site não tem avatar).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import uuid
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

_AQUI = os.path.dirname(os.path.abspath(__file__))
CATALOGO_PATH = os.path.join(_AQUI, "assets", "darkplanner", "cenas_catalogo.json")
_FONT_DIR = os.path.join(_AQUI, "assets", "fonts")
_FONTE_NEGRITO = os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")
_FONTE_NORMAL = os.path.join(_FONT_DIR, "DejaVuSans.ttf")
FPS = 30


class CenaError(Exception):
    pass


# ---------------------------------------------------------------- shutters -> transições
# Expressões do xfade "custom" com P indo de 0 (só o trecho A) a 1 (só o B) —
# o montador converte pro sentido do ffmpeg (que vai de 1 a 0).
_PRETO = "if(eq(PLANE,0),16,128)"
_BRANCO = "if(eq(PLANE,0),235,128)"
SHUTTERS: Dict[str, Tuple[str, str, float]] = {
    # id do DarkPlanner: (valor da transição, rótulo, duração padrão)
    "SHUTTER_0": ("dp_shutter", "📸 Shutter — Match Cut", 0.5),
    "SHUTTER_1_LAMINAS": ("dp_shutter_laminas", "📸 Shutter — Lâminas", 0.6),
    "SHUTTER_2_FILME": ("dp_shutter_filme", "📸 Shutter — Filme de contato", 0.6),
    "SHUTTER_3_DOSSIE": ("dp_shutter_dossie", "📸 Shutter — Dossiê", 0.6),
    "SHUTTER_4_FOCO": ("dp_shutter_foco", "📸 Shutter — Foco óptico", 0.6),
    "SHUTTER_5_FINALE": ("dp_shutter_finale", "📸 Shutter — Final de impacto", 0.7),
    "SHUTTER_6_DESLIZE": ("dp_shutter_deslize", "📸 Shutter — Deslocamento lateral", 0.6),
    "SHUTTER_7_REFOCO": ("dp_shutter_refoco", "📸 Shutter — Foco revelado", 0.6),
    "SHUTTER_8_PULSO": ("dp_shutter_pulso", "📸 Shutter — Pulso de aproximação", 0.6),
}


def _fecha_abre(mascara_a: str, mascara_b: str, fundo: str = _PRETO) -> str:
    """1ª metade: A some atrás da 'lâmina' (mascara_a com q=1-2P); 2ª metade:
    B aparece (mascara_b com q=2P-1). As máscaras usam a variável Q."""
    a = mascara_a.replace("Q", "(1-2*P)")
    b = mascara_b.replace("Q", "(2*P-1)")
    return f"if(lt(P,0.5),if({a},A,{fundo}),if({b},B,{fundo}))"


_FLASH = "*(1-0.85*max(0,1-abs(P-0.5)*6))+{b}*0.85*max(0,1-abs(P-0.5)*6)".format(b=_BRANCO)
TRANSICOES_SHUTTER: Dict[str, str] = {
    # obturador: barras pretas fecham de cima e de baixo e abrem no próximo take
    "dp_shutter": "(" + _fecha_abre("lt(abs(Y-H/2),H/2*Q)", "lt(abs(Y-H/2),H/2*Q)") + ")" + _FLASH,
    # 8 lâminas horizontais
    "dp_shutter_laminas": _fecha_abre("lt(mod(Y,H/8)/(H/8),Q)", "lt(mod(Y,H/8)/(H/8),Q)"),
    # fotogramas verticais (filme de contato)
    "dp_shutter_filme": _fecha_abre("lt(mod(X,W/6)/(W/6),Q)", "gt(mod(X,W/6)/(W/6),1-Q)"),
    # lâminas diagonais
    "dp_shutter_dossie": _fecha_abre("lt(mod(X+Y,H/4)/(H/4),Q)", "lt(mod(X+Y,H/4)/(H/4),Q)"),
    # íris fechando e abrindo
    "dp_shutter_foco": _fecha_abre("lt(hypot(X-W/2,Y-H/2),hypot(W/2,H/2)*Q)", "lt(hypot(X-W/2,Y-H/2),hypot(W/2,H/2)*Q)"),
    # íris + clarão branco no meio
    "dp_shutter_finale": "(" + _fecha_abre("lt(hypot(X-W/2,Y-H/2),hypot(W/2,H/2)*Q)", "lt(hypot(X-W/2,Y-H/2),hypot(W/2,H/2)*Q)") + ")" + _FLASH,
    # cortina lateral passa da esquerda pra direita
    "dp_shutter_deslize": "if(lt(P,0.5),if(gt(X,W*2*P),A," + _PRETO + "),if(gt(X,W*(2*P-1)),B," + _PRETO + "))",
    # losango fechando/abrindo
    "dp_shutter_refoco": _fecha_abre("lt((abs(X-W/2)/W+abs(Y-H/2)/H),Q)", "lt((abs(X-W/2)/W+abs(Y-H/2)/H),Q)"),
    # anéis concêntricos
    "dp_shutter_pulso": _fecha_abre("lt(mod(hypot(X-W/2,Y-H/2),H/5)/(H/5),Q)", "lt(mod(hypot(X-W/2,Y-H/2),H/5)/(H/5),Q)"),
}
ROTULOS_SHUTTER = [(v, r) for v, r, _d in SHUTTERS.values()]


# ---------------------------------------------------------------- catálogo
@lru_cache(maxsize=1)
def _catalogo_bruto() -> Dict[str, Any]:
    with open(CATALOGO_PATH, encoding="utf-8") as f:
        return json.load(f)


def catalogo() -> Dict[str, Dict[str, Any]]:
    """Só os templates de CENA (sem shutters, que viraram transições)."""
    return {k: v for k, v in _catalogo_bruto()["templates"].items() if k not in SHUTTERS}


def regras_templates() -> Dict[str, str]:
    return dict(_catalogo_bruto().get("regras") or {})


def template(tid: Optional[str]) -> Optional[Dict[str, Any]]:
    if not tid:
        return None
    return catalogo().get(tid)


def slots_do_template(tid: str) -> int:
    t = template(tid)
    if not t:
        return 1
    return max(1, int(t.get("slots") or 1))


# ---------------------------------------------------------------- fundos
_PALETA = [  # (escuro, claro) — fundos coloridos "Auto" dos C30/C50
    ((14, 32, 40), (36, 96, 108)), ((38, 14, 22), (112, 38, 52)), ((14, 18, 42), (44, 62, 128)),
    ((28, 30, 14), (92, 98, 40)), ((30, 16, 40), (92, 52, 120)), ((40, 24, 10), (132, 82, 30)),
    ((12, 34, 24), (36, 110, 74)), ((34, 34, 38), (96, 96, 108)),
]

_FUNDO_POR_NOME = {
    "grao": "escuro", "concreto": "concreto", "concreto_pack": "concreto", "manchas_grunge": "concreto",
    "lino_escuro": "concreto", "metal_escovado": "concreto", "registro": "registro", "placa_tecnica": "registro",
    "grade_tecnica": "grade_pontos", "borda_queimada": "borda_queimada", "grade_pontos": "grade_pontos",
    "grade_pack": "grade_pontos", "grid_assinatura": "grade_pontos", "tatico_giz": "grade_pontos",
    "painel_regua": "grade_pontos", "painel_regua_dir": "grade_pontos", "divisoria_v": "grade_pontos",
    "barra_lateral": "grade_pontos", "veu_esq": "vidro", "veu_dir": "vidro", "vinheta_off": "vidro",
    "nevoa": "vidro", "difusor": "vidro", "vidro_fosco": "vidro", "vidro_lateral": "vidro",
    "luz": "clarao", "luz_esq": "clarao", "luz_cinematica": "clarao", "clarao": "clarao",
    "placas": "luz", "planos_translucidos": "luz", "blocos_offset": "luz", "gradiente_diag": "luz",
    "gradiente": "luz", "filete_duplo": "cantoneiras", "cantoneiras": "cantoneiras",
    "papel_arquivo": "papel", "papel_antigo": "papel",
}
NOMES_FUNDO = {
    "escuro": "Escuro com grão", "concreto": "Concreto", "registro": "Marcas de registro", "borda_queimada": "Borda queimada",
    "grade_pontos": "Grade de pontos", "vidro": "Vidro (a própria mídia desfocada)", "clarao": "Clarão de luz",
    "luz": "Luz diagonal", "cantoneiras": "Cantoneiras", "papel": "Papel de arquivo", "filme": "Película",
    "midia": "A própria mídia",
}
_SOLO_PAPEL = {51, 52, 53, 54, 59, 60, 61, 69}


def estilo_do_fundo(nome: str) -> str:
    if nome in _FUNDO_POR_NOME:
        return _FUNDO_POR_NOME[nome]
    m = re.match(r"C50SOLO_BG_(\d+)", nome or "")
    if m:
        return "papel" if int(m.group(1)) in _SOLO_PAPEL else f"cor{int(m.group(1)) % len(_PALETA)}"
    m = re.match(r"C50V2_BG_(\d+)", nome or "")
    if m:
        return f"cor{int(m.group(1)) % len(_PALETA)}"
    return "escuro"


def fundos_do_template(tid: str) -> List[str]:
    """Estilos de fundo disponíveis pra esse template (sem repetição, na ordem do DarkPlanner)."""
    lay = layout(tid)
    if lay.get("fundo_fixo"):
        return [lay["fundo_fixo"]]
    vistos: List[str] = []
    for f in (template(tid) or {}).get("fundos") or []:
        e = estilo_do_fundo(f)
        if e not in vistos:
            vistos.append(e)
    return vistos or ["escuro"]


_FUNDOS_DESENHO = {"linhas", "grade", "ondas", "grade_ondulada", "grade_3d", "cor_solida", "cor_gradiente"}


def _fundo_desenhado(tipo: str, W: int, H: int, pasta: str, cor: str) -> str:
    """Linhas/grades/ondas/cor (dp_fundos) achatados sobre preto, com um pouco de grão."""
    import dp_fundos
    from PIL import Image
    rgba = dp_fundos.padrao_png(tipo, W, H, pasta, cor, 1.0, cobre=True)
    destino = rgba[:-4] + "_rgb.png"
    if not os.path.exists(destino):
        base = Image.new("RGBA", (W, H), (10, 10, 12, 255))
        Image.alpha_composite(base, Image.open(rgba).convert("RGBA")).convert("RGB").save(destino)
    return destino


def _ruido(np, h, w, rng, escala=1.0):
    return rng.normal(0, 1, (h, w)) * escala


def gerar_fundo(estilo: str, W: int, H: int, destino_dir: str, janelas_px: Sequence[Tuple[int, int, int, int]] = (),
                tom: Optional[str] = None) -> str:
    """PNG W×H do fundo (gerado uma vez e reaproveitado). `tom` = cor primária
    da paleta do projeto: tinge os fundos coloridos, o clarão e a luz."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    chave = hashlib.md5(f"{estilo}|{W}|{H}|{list(janelas_px)}|{tom}".encode()).hexdigest()[:10]
    os.makedirs(destino_dir, exist_ok=True)
    caminho = os.path.join(destino_dir, f"fundo_{estilo}_{chave}.png")
    if os.path.exists(caminho):
        return caminho
    rng = np.random.default_rng(int(chave, 16) % (2 ** 32))
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    cx, cy = W / 2, H / 2
    dist = np.sqrt(((xx - cx) / W) ** 2 + ((yy - cy) / H) ** 2) / 0.7071
    vinheta = np.clip(1 - dist ** 2 * 0.75, 0, 1)

    def rgb(base, var=1.0):
        return np.stack([np.full((H, W), c, np.float32) for c in base], -1)

    if estilo == "papel":
        img = rgb((233, 225, 206))
        manchas = np.array(Image.fromarray((rng.random((H // 8 + 1, W // 8 + 1)) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC), np.float32)
        img -= (manchas[..., None] / 255.0) * 18
        img += _ruido(np, H, W, rng, 6)[..., None]
        img *= (0.82 + 0.18 * vinheta)[..., None]
    elif estilo == "concreto":
        manchas = np.array(Image.fromarray((rng.random((H // 6 + 1, W // 6 + 1)) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(3)), np.float32)
        img = rgb((52, 52, 55)) + (manchas[..., None] - 128) * 0.18 + _ruido(np, H, W, rng, 9)[..., None]
        img *= (0.55 + 0.45 * vinheta)[..., None]
    elif estilo == "clarao":
        luz = np.exp(-(((xx - W * 0.5) / (W * 0.33)) ** 2 + ((yy - H * 0.42) / (H * 0.42)) ** 2))
        cor_luz = np.array([120, 104, 82], np.float32)
        if tom:
            import dp_cores
            cor_luz = np.array(dp_cores.rgb(dp_cores.tons_da_paleta(tom)["medio"]), np.float32) * 0.85
        img = rgb((10, 10, 12)) + luz[..., None] * cor_luz + _ruido(np, H, W, rng, 5)[..., None]
    elif estilo == "luz":
        g = (xx / W * 0.6 + (1 - yy / H) * 0.4)
        cor_luz = np.array([70, 64, 58], np.float32)
        if tom:
            import dp_cores
            cor_luz = np.array(dp_cores.rgb(dp_cores.tons_da_paleta(tom)["medio"]), np.float32) * 0.6
        img = rgb((12, 12, 15)) + (g ** 2)[..., None] * cor_luz + _ruido(np, H, W, rng, 5)[..., None]
    elif estilo == "borda_queimada":
        img = rgb((48, 30, 20)) * (vinheta ** 1.6)[..., None] + _ruido(np, H, W, rng, 8)[..., None]
    elif re.fullmatch(r"cor\d+", estilo):
        esc, cla = _PALETA[int(estilo[3:]) % len(_PALETA)]
        if tom:  # tom sobre tom da paleta do projeto
            import dp_cores
            t = dp_cores.tons_da_paleta(tom)
            esc, cla = dp_cores.rgb(t["escuro"]), dp_cores.rgb(t["medio"])
        g = np.clip(1 - dist, 0, 1)[..., None]
        img = np.array(esc, np.float32) * (1 - g) + np.array(cla, np.float32) * g + _ruido(np, H, W, rng, 5)[..., None]
    elif estilo == "filme":
        img = rgb((8, 8, 8)) + _ruido(np, H, W, rng, 3)[..., None]
    else:  # escuro, registro, grade_pontos, cantoneiras
        img = rgb((17, 17, 20)) + _ruido(np, H, W, rng, 7)[..., None]
        img *= (0.6 + 0.4 * vinheta)[..., None]
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(im)
    u = max(2, H // 360)
    if estilo == "grade_pontos":
        passo = max(16, H // 30)
        for y in range(passo // 2, H, passo):
            for x in range(passo // 2, W, passo):
                d.ellipse([x - u, y - u, x + u, y + u], fill=(58, 58, 64))
    if estilo == "filme":
        fh, fw = max(10, H // 36), max(14, W // 60)
        for x in range(fw, W, fw * 3):
            for y in (H // 40, H - H // 40 - fh):
                d.rounded_rectangle([x, y, x + fw, y + fh], radius=u, fill=(205, 200, 190))
    if estilo in ("registro", "cantoneiras"):
        cor = (150, 150, 158) if estilo == "registro" else (220, 214, 200)
        for (x, y, w, h) in janelas_px:
            if w >= W - 4 and h >= H - 4:
                continue
            k = max(14, min(w, h) // 9)
            g = 3 * u
            for (px, py, sx, sy) in ((x - g, y - g, 1, 1), (x + w + g, y - g, -1, 1), (x - g, y + h + g, 1, -1), (x + w + g, y + h + g, -1, -1)):
                d.line([px, py, px + sx * k, py], fill=cor, width=u)
                d.line([px, py, px, py + sy * k], fill=cor, width=u)
        if estilo == "registro":
            for (px, py) in ((W * 0.05, H * 0.08), (W * 0.95, H * 0.92)):
                d.line([px - 12 * u, py, px + 12 * u, py], fill=(120, 120, 128), width=u)
                d.line([px, py - 12 * u, px, py + 12 * u], fill=(120, 120, 128), width=u)
                d.ellipse([px - 5 * u, py - 5 * u, px + 5 * u, py + 5 * u], outline=(120, 120, 128), width=u)
    im.save(caminho)
    return caminho


# ---------------------------------------------------------------- arranjos (janelas em fração da tela)
J = Tuple[float, float, float, float]
_ARRANJOS: Dict[str, Dict[str, Any]] = {
    "tela_cheia": {"janelas": [(0, 0, 1, 1)], "texto": (0.06, 0.78, 0.88, 0.16)},
    "moldura": {"janelas": [(0.15, 0.10, 0.70, 0.74)], "texto": (0.12, 0.86, 0.76, 0.12), "rotulo": (0.15, 0.03)},
    "moldura_larga": {"janelas": [(0.07, 0.10, 0.86, 0.74)], "texto": (0.1, 0.86, 0.8, 0.12), "rotulo": (0.07, 0.03)},
    "retrato_dir": {"janelas": [(0.58, 0.07, 0.33, 0.86)], "texto": (0.07, 0.38, 0.45, 0.4), "rotulo": (0.07, 0.30)},
    "retrato_esq": {"janelas": [(0.09, 0.07, 0.33, 0.86)], "texto": (0.48, 0.38, 0.45, 0.4), "rotulo": (0.48, 0.30)},
    "barra_esq": {"janelas": [(0.37, 0.09, 0.58, 0.82)], "texto": (0.04, 0.38, 0.30, 0.45), "rotulo": (0.04, 0.30)},
    "barra_dir": {"janelas": [(0.05, 0.09, 0.58, 0.82)], "texto": (0.66, 0.38, 0.30, 0.45), "rotulo": (0.66, 0.30)},
    "citacao": {"janelas": [(0.64, 0.14, 0.30, 0.72)], "texto": (0.08, 0.30, 0.50, 0.5), "aspas": (0.07, 0.10)},
    "nome": {"janelas": [(0, 0, 1, 1)], "texto": (0.04, 0.76, 0.5, 0.14), "rotulo": (0.04, 0.70)},
    "cartao": {"janelas": [(0.22, 0.10, 0.56, 0.70)], "texto": (0.14, 0.85, 0.72, 0.12), "borda": 0.022},
    "lado_a_lado": {"janelas": [(0.05, 0.12, 0.43, 0.64), (0.52, 0.12, 0.43, 0.64)], "texto": (0.06, 0.81, 0.88, 0.15)},
    "diagonal": {"janelas": [(0.05, 0.06, 0.50, 0.52), (0.45, 0.32, 0.50, 0.52)], "texto": (0.05, 0.86, 0.9, 0.12)},
    "sobreposicao": {"janelas": [(0.06, 0.08, 0.54, 0.58), (0.40, 0.26, 0.54, 0.58)], "texto": (0.05, 0.86, 0.9, 0.12)},
    "confronto": {"janelas": [(0, 0, 0.5, 1), (0.5, 0, 0.5, 1)], "texto": (0.06, 0.80, 0.88, 0.15), "borda": 0.0},
    "antes_depois": {"janelas": [(0, 0, 1, 1), (0, 0, 1, 1)], "texto": (0.06, 0.80, 0.88, 0.15), "borda": 0.0, "revela_ultimo": True},
    "ff_dir": {"janelas": [(0, 0, 1, 1), (0.50, 0.15, 0.44, 0.60)], "texto": (0.06, 0.80, 0.88, 0.15), "fundo_take0": True},
    "ff_esq": {"janelas": [(0, 0, 1, 1), (0.06, 0.15, 0.44, 0.60)], "texto": (0.06, 0.80, 0.88, 0.15), "fundo_take0": True},
    "ff_zoom": {"janelas": [(0, 0, 1, 1), (0.22, 0.12, 0.56, 0.62)], "texto": (0.06, 0.80, 0.88, 0.15), "fundo_take0": True},
    "ff_vertical": {"janelas": [(0.08, 0.04, 0.84, 0.44), (0.08, 0.52, 0.84, 0.44)], "texto": (0.1, 0.43, 0.8, 0.12)},
    "painel_dir": {"janelas": [(0.04, 0.08, 0.60, 0.74), (0.67, 0.24, 0.29, 0.44)], "texto": (0.05, 0.85, 0.9, 0.12)},
    "painel_esq": {"janelas": [(0.36, 0.08, 0.60, 0.74), (0.04, 0.24, 0.29, 0.44)], "texto": (0.05, 0.85, 0.9, 0.12)},
    "triade": {"janelas": [(0.04, 0.14, 0.29, 0.58), (0.355, 0.14, 0.29, 0.58), (0.67, 0.14, 0.29, 0.58)], "texto": (0.06, 0.80, 0.88, 0.15)},
    "cascata": {"janelas": [(0.05, 0.05, 0.46, 0.46), (0.27, 0.24, 0.46, 0.46), (0.49, 0.43, 0.46, 0.46)], "texto": (0.04, 0.62, 0.36, 0.3)},
    "leque": {"janelas": [(0.03, 0.20, 0.29, 0.50), (0.68, 0.20, 0.29, 0.50), (0.29, 0.08, 0.42, 0.68)], "texto": (0.08, 0.82, 0.84, 0.14)},
    "escada": {"janelas": [(0.04, 0.50, 0.30, 0.40), (0.35, 0.30, 0.30, 0.40), (0.66, 0.10, 0.30, 0.40)], "texto": (0.04, 0.08, 0.5, 0.2)},
    "pilha": {"janelas": [(0.10, 0.06, 0.56, 0.58), (0.20, 0.15, 0.56, 0.58), (0.30, 0.24, 0.56, 0.58)], "texto": (0.06, 0.86, 0.88, 0.12)},
    "linha_tempo": {"janelas": [(0.04, 0.16, 0.28, 0.46), (0.36, 0.16, 0.28, 0.46), (0.68, 0.16, 0.28, 0.46)], "texto": (0.06, 0.80, 0.88, 0.15), "linha": True},
    "mosaico": {"janelas": [(0.05, 0.03, 0.44, 0.37), (0.51, 0.03, 0.44, 0.37), (0.05, 0.43, 0.44, 0.37), (0.51, 0.43, 0.44, 0.37)], "texto": (0.06, 0.83, 0.88, 0.14)},
    "sequencia4": {"janelas": [(0.02 + i * 0.245, 0.18, 0.225, 0.50) for i in range(4)], "texto": (0.06, 0.78, 0.88, 0.15), "linha": True},
    "sequencia_tela_cheia": {"janelas": [(0, 0, 1, 1)] * 6, "texto": (0.08, 0.40, 0.84, 0.2), "borda": 0.0, "titulo_por_take": True},
}

# deslocamento inicial da entrada (fração de W, fração de H)
_MOVIMENTOS = {
    "assenta": (0, 0.04), "soft_land": (0, -0.05), "desliza_suave": (0.06, 0), "ergue_suave": (0, 0.08),
    "revela_cima": (0, -0.08), "revela_esq": (-0.08, 0), "revela_diag": (-0.05, -0.05), "slide_left": (0.25, 0),
    "slide_right": (-0.25, 0), "fade": (0, 0), "dissolve_foco": (0, 0), "zoom_soft": (0, 0.02),
    "queda": (0, -0.35), "trilho": (0.35, 0), "sobe": (0, 0.3), "": (0, 0.04),
}

# ids específicos -> (arranjo, opções)
_MAPA: Dict[str, Tuple[str, Dict[str, Any]]] = {
    "INTRO_DOC_0": ("sequencia_tela_cheia", {"fundo_fixo": "escuro"}),
    "TEXT_MATCH_CUT_0": ("tela_cheia", {"texto_estilo": "matchcut", "escurecer": 0.45}),
    "WHOOSH_STUDIO_0": ("tela_cheia", {"texto_estilo": "whoosh", "escurecer": 0.35}),
    "MOLDURA_07": ("moldura", {}), "MOLDURA_10": ("moldura", {"fundo_fixo": "cor2"}),
    "MOLDURA_11": ("moldura", {"fundo_fixo": "vidro"}), "MOLDURA_12": ("moldura_larga", {"fundo_fixo": "vidro", "escurecer": 0.25}),
    "MULTITAKE_01": ("sobreposicao", {}), "MULTITAKE_02": ("confronto", {}), "MULTITAKE_03": ("antes_depois", {}),
    "MULTITAKE_04": ("triade", {}), "MULTITAKE_05": ("pilha", {}), "MULTITAKE_06": ("lado_a_lado", {}),
    "MULTITAKE_07": ("diagonal", {}), "MULTITAKE_08": ("leque", {}), "MULTITAKE_09": ("escada", {}),
    "MULTIGRADE_01": ("lado_a_lado", {}), "MULTIGRADE_02": ("sobreposicao", {"fundo_fixo": "vidro"}),
    "MULTIGRADE_11": ("diagonal", {"fundo_fixo": "vidro"}), "MULTIGRADE_12": ("lado_a_lado", {}),
    "MULTIGRADE_03": ("sobreposicao", {}), "MULTIGRADE_04": ("lado_a_lado", {}), "MULTIGRADE_05": ("escada", {}),
    "MULTIGRADE_06": ("triade", {}), "MULTIGRADE_07": ("cascata", {}), "MULTIGRADE_08": ("leque", {}),
    "MULTIGRADE_09": ("painel_dir", {}), "MULTIGRADE_10": ("painel_esq", {}),
    "PREMIUM_10": ("ff_dir", {}), "FRENTEFUNDO_05": ("ff_dir", {}), "FRENTEFUNDO_04": ("ff_esq", {}),
    "FRENTEFUNDO_06": ("ff_esq", {}), "FRENTEFUNDO_02": ("ff_vertical", {}), "FRENTEFUNDO_07": ("ff_vertical", {}),
    "FRENTEFUNDO_03": ("ff_zoom", {}), "FRENTEFUNDO_08": ("ff_zoom", {}), "VIDEO_2": ("lado_a_lado", {}),
    "RETRATO_01": ("retrato_dir", {}), "RETRATO_02": ("retrato_esq", {}), "RETRATO_03": ("retrato_dir", {}),
    "RETRATO_04": ("retrato_esq", {}),
    "tpl_cine_focus": ("moldura_larga", {"foco": True}), "tpl_editorial_left": ("barra_esq", {}),
    "tpl_editorial_right": ("lado_a_lado", {}), "tpl_focus_window": ("moldura", {"fundo_fixo": "vidro", "foco": True}),
    "tpl_film_frame": ("cartao", {}), "tpl_archive_slide": ("painel_dir", {}), "tpl_technical_scan": ("moldura", {"fundo_fixo": "registro"}),
    "tpl_profile_scene": ("retrato_esq", {}), "tpl_split_duplicate": ("barra_dir", {"fundo_fixo": "grade_pontos"}),
    "tpl_dual_take": ("sequencia4", {}), "tpl_triple_sequence": ("triade", {}), "tpl_mosaic_dynamic": ("mosaico", {}),
    "tpl_depth_layer": ("ff_zoom", {"foco": True}), "tpl_epic_break": ("linha_tempo", {}),
    "ED_CITACAO": ("citacao", {}), "ED_LOWER_NOME": ("nome", {}), "ED_COMPARACAO": ("confronto", {}),
    "ED_TRIPLO_DOC": ("linha_tempo", {}), "ED_FICHA_ARQUIVO": ("retrato_dir", {"fundo_fixo": "papel"}),
    "ED_PERFIL": ("retrato_esq", {}), "ED_MOSAICO": ("mosaico", {}), "ED_ARTIGO": ("barra_dir", {"fundo_fixo": "papel"}),
    "REF_FLASH_PUSH": ("tela_cheia", {"flash": True, "fundo_fixo": "escuro"}),
    "REF_FILM_SLIDE": ("moldura", {"fundo_fixo": "filme", "movimento": "trilho"}),
    "REF_CAMERA_FOCUS": ("tela_cheia", {"foco": True, "fundo_fixo": "escuro"}),
    "REF_FILM_ROLL_IN": ("moldura", {"fundo_fixo": "filme", "movimento": "sobe"}),
    # C30 / C50 (cinema50) — 1 slot
    "C30_GATE_RESPIRA": ("moldura_larga", {}), "C30_FENDA_TRAVELLING": ("moldura", {"movimento": "trilho"}),
    "C30_MARGEM_MUTANTE": ("barra_esq", {}), "C30_IRIS_EXCENTRICA": ("moldura", {"foco": True}),
    "C30_LUZ_ARQUITETONICA": ("moldura", {"fundo_fixo": "clarao"}), "C30_PAPEL_DESDOBRA": ("cartao", {"fundo_fixo": "papel"}),
    "C30_MATTE_ORGANICO": ("moldura", {"fundo_fixo": "vidro"}), "C30_PROJETOR": ("moldura", {"fundo_fixo": "clarao", "flash": True}),
    "C30_PANORAMA_INTEGRO": ("moldura_larga", {}), "C30_LUPA_VINCULADA": ("retrato_dir", {}),
    "C50_SOCIAL_BALAO": ("citacao", {}), "C50_SOCIAL_BILHETE": ("cartao", {"fundo_fixo": "papel"}),
    "C50_CINTA_CURVA": ("moldura_larga", {}), "C50_JANELA_DEGRAUS": ("moldura", {}),
    "C50_ANEL_IMAGEM": ("moldura", {"fundo_fixo": "vidro"}), "C50_VENEZIANAS_IMAGEM": ("moldura", {"fundo_fixo": "vidro"}),
    "C50_SOLO_51_PAPER_DROP": ("cartao", {"movimento": "queda"}), "C50_SOLO_52_FOLDER_TRACK": ("cartao", {"movimento": "trilho"}),
    "C50_SOLO_53_CONTACT_PRINT": ("cartao", {}), "C50_SOLO_54_ESSAY_SPREAD": ("barra_dir", {}),
    "C50_SOLO_55_RAIL_LAUNCH": ("moldura", {"movimento": "trilho"}), "C50_SOLO_56_HORIZON_DOLLY": ("moldura_larga", {"movimento": "zoom_soft"}),
    "C50_SOLO_57_ISOMETRIC_ARC": ("moldura", {"movimento": "revela_diag"}), "C50_SOLO_58_POLAR_ORBIT": ("moldura", {"movimento": "slide_right"}),
    "C50_SOLO_59_HEADLINE_TRACK": ("barra_esq", {"movimento": "trilho"}), "C50_SOLO_60_COLUMN_RISE": ("retrato_dir", {"movimento": "sobe"}),
    "C50_SOLO_61_MAGAZINE_PIVOT": ("cartao", {"movimento": "slide_left"}), "C50_SOLO_62_POSTER_ARRIVE": ("retrato_esq", {"movimento": "queda"}),
    "C50_SOLO_63_LIGHT_TRAVEL": ("moldura", {"movimento": "trilho", "flash": True}), "C50_SOLO_64_FOCUS_DISSOLVE": ("moldura_larga", {"foco": True}),
    "C50_SOLO_65_SUSPENDED_RISE": ("moldura", {"movimento": "sobe"}), "C50_SOLO_66_RIMLIGHT_DROP": ("moldura", {"movimento": "queda", "fundo_fixo": "clarao"}),
    "C50_SOLO_67_MAP_TRAVEL": ("moldura_larga", {"movimento": "trilho"}), "C50_SOLO_68_ROUTE_ARC": ("moldura", {"movimento": "revela_diag"}),
    "C50_SOLO_69_RESEARCH_LAND": ("cartao", {"movimento": "soft_land"}), "C50_SOLO_70_HORIZON_LIFT": ("moldura_larga", {"movimento": "ergue_suave"}),
    "C50_SOLO_71_HALFTONE_BLOOM": ("moldura", {"movimento": "zoom_soft"}), "C50_SOLO_72_PARALLEL_PASS": ("moldura", {"movimento": "slide_left"}),
    "C50_SOLO_73_VERTEX_CURVE": ("retrato_dir", {"movimento": "revela_diag"}), "C50_SOLO_74_QUIET_REVEAL": ("moldura", {"movimento": "fade"}),
    # 2 slots
    "C30_SEPTO_VIVO": ("lado_a_lado", {}), "C30_LAMINA_OBLIQUA": ("diagonal", {"movimento": "queda"}),
    "C30_FAIXAS_ENTRELACADAS": ("ff_vertical", {}), "C30_ARCOS_GEMEOS": ("lado_a_lado", {}),
    "C30_ORBITAS_TANGENTES": ("diagonal", {}), "C30_DIALOGO_RESPONSIVO": ("confronto", {}),
    "C30_VARREDURA_REGISTRADA": ("lado_a_lado", {"movimento": "trilho"}), "C30_DOBRA_CENTRAL": ("lado_a_lado", {}),
    "C30_CONTEXTO_E_MACRO": ("ff_dir", {}), "C30_DIPTICO_INTEGRO": ("lado_a_lado", {}),
    "C30_JANELA_DESACOPLA": ("sobreposicao", {}), "C30_GALERIA_PERSPECTIVA": ("painel_dir", {}),
    "C50_DUPLA_CHEVRONS": ("diagonal", {}), "C50_DUPLA_FAIXA_PASSANTE": ("ff_vertical", {"movimento": "trilho"}),
    "C50_DUPLA_CAPSULAS": ("lado_a_lado", {}), "C50_DUPLA_BRUMA": ("sobreposicao", {"fundo_fixo": "vidro"}),
    "C50_DUPLA_ENCAIXES": ("painel_esq", {}), "C50_DUPLA_SOBREIMPRESSAO": ("ff_zoom", {}),
    # 3 slots
    "C30_TRIPTICO_DOMINANCIA": ("leque", {}), "C30_PERCURSO_L": ("escada", {}), "C30_ATLAS_HEXAGONAL": ("triade", {}),
    "C30_OCUSAO_CONTINUA": ("cascata", {}), "C30_ESTEIRA_FOTOGRAMAS": ("linha_tempo", {"fundo_fixo": "filme"}),
    "C30_CONSTELACAO": ("escada", {}), "C30_MESA_LUZ": ("pilha", {"fundo_fixo": "clarao"}), "C30_CADENCIA_TRES_ATOS": ("triade", {}),
    "C50_GRID_SERRA": ("escada", {}), "C50_GRID_PILAR_OCULOS": ("leque", {}), "C50_GRID_TRAMA_FLUIDA": ("cascata", {}),
    # 4 slots
    "C50_GRID_CATAVENTO": ("mosaico", {}), "C50_GRID_JUNTAS": ("mosaico", {}), "C50_GRID_CANAIS": ("sequencia4", {}),
    "C50_GRID_ROSACEA": ("mosaico", {}), "C50_GRID_DIAGONAIS": ("mosaico", {}),
}
_PADRAO_POR_SLOTS = {1: "moldura", 2: "lado_a_lado", 3: "triade", 4: "mosaico", 6: "sequencia_tela_cheia"}


def layout(tid: str) -> Dict[str, Any]:
    t = template(tid) or {}
    nome_arr, opc = _MAPA.get(tid, (None, {}))
    if not nome_arr:
        familia = t.get("familia") or ""
        nome_arr = "moldura_larga" if familia == "moldura" and "PREMIUM" in tid else _PADRAO_POR_SLOTS.get(int(t.get("slots") or 1), "mosaico")
    arr = dict(_ARRANJOS[nome_arr])
    arr["arranjo"] = nome_arr
    arr.update(opc)
    return arr


_ARRANJOS_TELA_CHEIA = {"tela_cheia", "nome", "sequencia_tela_cheia", "antes_depois"}


def adaptar_layout(lay: Dict[str, Any], W: int, H: int) -> Dict[str, Any]:
    """Arranjo pensado em 16:9 -> vídeo VERTICAL (9:16). As janelas são
    "transpostas" (lado a lado vira um em cima do outro) e espremidas na parte
    de cima; o texto vai pra faixa de baixo, largo. Tela cheia continua tela
    cheia. Quadrado (1:1) usa o arranjo original (já cabe bem)."""
    if H <= W * 1.2:
        return lay
    novo = dict(lay)
    if lay.get("arranjo") in _ARRANJOS_TELA_CHEIA:
        tx, ty, tw, th = lay.get("texto", (0.06, 0.8, 0.88, 0.15))
        novo["texto"] = (min(tx, 0.06), ty, max(tw, 0.88), th)
        if "rotulo" in lay:
            novo["rotulo"] = (min(lay["rotulo"][0], 0.06), lay["rotulo"][1])
        return novo
    topo, alt = 0.04, 0.68
    jan = []
    for (x, y, w, h) in lay["janelas"]:
        if w >= 0.999 and h >= 0.999:
            jan.append((x, y, w, h))
            continue
        # transpõe (x<->y, w<->h) e encaixa na faixa de cima
        jan.append((round(y, 4), round(topo + x * alt, 4), round(h, 4), round(w * alt, 4)))
    novo["janelas"] = jan
    novo["texto"] = (0.06, 0.765, 0.88, 0.17)
    if "rotulo" in lay:
        novo["rotulo"] = (0.06, 0.735)
    if "aspas" in lay:
        novo["aspas"] = (0.05, 0.70)
    novo["vertical"] = True
    return novo


def layout_para(tid: str, W: int, H: int) -> Dict[str, Any]:
    return adaptar_layout(layout(tid), W, H)


def _movimento_do_take(tid: str, k: int, lay: Dict[str, Any]) -> str:
    if lay.get("movimento"):
        return lay["movimento"]
    mov = (template(tid) or {}).get("motion") or []
    return mov[k % len(mov)] if mov else "assenta"


# ---------------------------------------------------------------- textos
_ROTULOS_QUE_FICAM = {"ANTES", "DEPOIS", "VS", "“", "01", "02", "03"}


def campos_de_texto(tid: str) -> List[Dict[str, Any]]:
    """Campos editáveis (pro editor e pra IA). A fala ("speech") vem sozinha."""
    out = []
    for f in (template(tid) or {}).get("textFields") or []:
        out.append({
            "key": f["key"], "source": f["source"], "maxChars": f.get("maxChars") or 60,
            "default": f.get("default") if f["key"] in _ROTULOS_QUE_FICAM else "",
            "instrucao": f.get("instruction") or "", "take": f.get("take"),
        })
    return out


def tem_fala(tid: str) -> bool:
    lay = layout(tid)
    if lay.get("texto_estilo"):
        return True
    return any(f["source"] == "speech" for f in (template(tid) or {}).get("textFields") or [])


def cobre_legenda(tid: str) -> bool:
    return tem_fala(tid)


def _quebrar(texto: str, max_chars_linha: int, max_linhas: int = 3) -> List[str]:
    palavras = (texto or "").split()
    linhas: List[str] = []
    atual = ""
    for p in palavras:
        if len(atual) + len(p) + (1 if atual else 0) <= max_chars_linha:
            atual = (atual + " " + p).strip()
        else:
            if atual:
                linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas]
        linhas[-1] = linhas[-1].rstrip(".,;:") + "…"
    return linhas


def _pedacos_da_fala(texto: str, palavras: Optional[List[Dict[str, Any]]], ini: float, fim: float, max_chars: int) -> List[Tuple[float, float, str]]:
    """Divide a fala de um take em pedaços que cabem no campo, cada um no
    tempo em que é dito (usa os tempos das palavras quando existem)."""
    texto = (texto or "").strip()
    if not texto:
        return []
    if palavras:
        pedacos, atual, t0 = [], [], None
        for w in palavras:
            pal = str(w.get("word", "")).strip()
            if not pal:
                continue
            if t0 is None:
                t0 = float(w.get("start", ini))
            if atual and len(" ".join(atual + [pal])) > max_chars:
                pedacos.append([t0, " ".join(atual)])
                atual, t0 = [], float(w.get("start", ini))
            atual.append(pal)
        if atual:
            pedacos.append([t0, " ".join(atual)])
        if pedacos:
            out = []
            for j, (t, txt) in enumerate(pedacos):
                a = max(ini, min(t, fim)) if j else ini
                b = pedacos[j + 1][0] if j + 1 < len(pedacos) else fim
                out.append((a, max(a + 0.2, min(b, fim)), txt))
            return out
    # sem tempos: divide por tamanho, igualmente no tempo do take
    partes, atual = [], ""
    for p in texto.split():
        if atual and len(atual) + 1 + len(p) > max_chars:
            partes.append(atual)
            atual = p
        else:
            atual = (atual + " " + p).strip()
    if atual:
        partes.append(atual)
    dur = (fim - ini) / max(1, len(partes))
    return [(ini + j * dur, ini + (j + 1) * dur, txt) for j, txt in enumerate(partes)]


# ---------------------------------------------------------------- render
def _clara(c: str) -> bool:
    import dp_cores
    r, g, b = dp_cores.rgb(c)
    return (0.299 * r + 0.587 * g + 0.114 * b) > 140


def _par(v: float) -> int:
    return max(2, int(round(v / 2.0)) * 2)


def _esc_caminho(p: str) -> str:
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _drawtext(arquivo: str, fonte: str, tam: int, cor: str, x: str, y: str, ini: float, fim: float,
              caixa: Optional[str] = None, borda: int = 0, anim: str = "fade", desloc_x: float = 0) -> str:
    alpha = f"clip((t-{ini:.3f})/0.35,0,1)*clip(({fim:.3f}-t)/0.25,0,1)" if anim != "corte" else "1"
    if desloc_x:
        x = f"({x})+{desloc_x:.1f}*pow(1-clip((t-{ini:.3f})/0.45,0,1),3)"
    partes = [
        f"drawtext=fontfile='{_esc_caminho(fonte)}':textfile='{_esc_caminho(arquivo)}':expansion=none",
        f"fontsize={tam}:fontcolor={cor}:x='{x}':y='{y}'",
        f"enable='between(t,{ini:.3f},{fim:.3f})':alpha='{alpha}'",
    ]
    if caixa:
        partes.append(f"box=1:boxcolor={caixa}:boxborderw={max(4, tam // 3)}")
    if borda:
        partes.append(f"borderw={borda}:bordercolor=black@0.85")
    return ":".join(partes)


def _eq_mult(k: float) -> str:
    """Multiplica a luz por k (= CSS brightness(k) da telinha). Antes era um brilho
    negativo fixo, que afunda mais as cenas escuras do que a telinha mostra."""
    return f"eq=contrast={k:.3f}:brightness={(k - 1) * 0.38:.4f}:saturation={k:.3f}"


def fundo_tom(tid: str, estilo: str, cor_fundo: Optional[str], pal: Optional[Dict[str, Any]]) -> Optional[str]:
    """Cor que tinge o fundo da cena — a MESMA regra da telinha do Estúdio: o fundo
    próprio do template (ex.: "cor3", vinho) fica com a cor dele; a cor escolhida no
    trecho sempre vale; a cor primária da paleta só tinge os fundos que não são do
    template (os da galeria de fundos). Antes a paleta pintava também os fundos do
    template: a telinha mostrava vinho e o vídeo saía amarelo."""
    import dp_cores
    if cor_fundo:
        return cor_fundo
    if estilo in fundos_do_template(tid):
        return None
    return pal["primaria"] if pal and not dp_cores.neutra(pal["primaria"]) else None


def renderizar_cena(
    tid: str,
    clips: List[str],
    inicios: List[float],
    duracao: float,
    saida: str,
    W: int,
    H: int,
    work_dir: str,
    campos: Optional[Dict[str, Any]] = None,
    falas: Optional[List[str]] = None,
    palavras: Optional[List[Optional[List[Dict[str, Any]]]]] = None,
    run=None,
    paleta: Optional[Dict[str, Any]] = None,
) -> str:
    """Compõe a cena: `clips[k]` (clipe já normalizado W×H do take k, longo o
    bastante pra ir do início dele até o fim da cena), `inicios[k]` (segundo
    em que o take k entra, relativo ao começo da cena), `duracao` total.
    `campos` = textos dos campos fixos + "_fundo" (estilo) + "_fala" (False
    esconde a fala). `falas[k]` = o que é dito no take k; `palavras[k]` =
    tempos das palavras (relativos ao começo da cena), se houver."""
    t = template(tid)
    if not t:
        raise CenaError(f"Template de cena desconhecido: {tid!r}")
    if not clips:
        raise CenaError("Cena sem nenhum take.")
    campos = dict(campos or {})
    falas = list(falas or [])
    palavras = list(palavras or [])
    lay = layout_para(tid, W, H)
    HT = min(W, H)  # tamanho de letra: igual em 16:9, 9:16 e 1:1
    n = len(clips)
    janelas = list(lay["janelas"])
    if lay["arranjo"] == "sequencia_tela_cheia":
        janelas = [(0, 0, 1, 1)] * n
    elif n > len(janelas):
        janelas = janelas + [janelas[-1]] * (n - len(janelas))
    elif n < len(janelas) and not lay.get("revela_ultimo"):
        # menos takes que slots (fim do vídeo): usa só as primeiras janelas
        janelas = janelas[:n]
    if lay.get("revela_ultimo") and n == 1:
        janelas = [(0, 0, 1, 1)]
    os.makedirs(work_dir, exist_ok=True)

    import dp_cores
    usa_paleta = dp_cores.vale_para(paleta, "cenas")
    pal = dp_cores.normalizar(paleta) if usa_paleta else None
    COR_DESTAQUE = dp_cores.para_ffmpeg(pal["primaria"]) if pal else "0xE8C46A"
    COR_LINHA = dp_cores.para_ffmpeg(dp_cores.tons_da_paleta(pal["primaria"])["claro"]) + "@0.8" if pal else "0xEEEAE0@0.7"
    estilos = fundos_do_template(tid)
    import dp_fundos
    estilo = campos.get("_fundo") if campos.get("_fundo") in (estilos + sorted(dp_fundos.IDS_CENA)) else estilos[0]
    cor_fundo = campos.get("_fundo_cor") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(campos.get("_fundo_cor") or "")) else None
    papel = estilo == "papel"
    cor_texto = "0x1b1a17" if papel else "white"
    caixa_texto = None if papel else "black@0.55"
    borda_frac = lay.get("borda", 0.006)
    janelas_px = []
    for (x, y, w, h) in janelas:
        cheia = w >= 0.999 and h >= 0.999 or (w >= 0.499 and h >= 0.999)
        b = 0 if cheia else _par(H * borda_frac) if borda_frac else 0
        janelas_px.append((int(W * x), int(H * y), _par(W * w - 2 * b), _par(H * h - 2 * b), b, cheia))

    args: List[str] = []
    grafo: List[str] = []
    # ---- fundo
    fundo_midia = estilo in ("vidro", "vidro_cor", "midia") or lay.get("fundo_take0")
    if fundo_midia:
        args += ["-i", clips[0]]
        base = "[0:v]"
        if (lay.get("fundo_take0") and estilo not in ("vidro", "vidro_cor")) or estilo == "midia":
            grafo.append(f"{base}setpts=PTS-STARTPTS,fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,{_eq_mult(0.85 if estilo != 'midia' else 0.6)},format=yuv420p[fundo]")
        else:
            tinge = ""
            if estilo == "vidro_cor":
                r_, g_, b_ = dp_cores.rgb(cor_fundo or (pal["primaria"] if pal else "#3E8EFF"))
                tinge = f",drawbox=x=0:y=0:w=iw:h=ih:color=0x{r_:02X}{g_:02X}{b_:02X}@0.38:t=fill"
            grafo.append(f"{base}setpts=PTS-STARTPTS,fps={FPS},scale={max(2, W // 4)}:{max(2, H // 4)}:force_original_aspect_ratio=increase,crop={max(2, W // 4)}:{max(2, H // 4)},gblur=sigma=6,scale={W}:{H},setsar=1,{_eq_mult(0.7)}{tinge},format=yuv420p[fundo]")
    else:
        tom = fundo_tom(tid, estilo, cor_fundo, pal)
        if estilo in _FUNDOS_DESENHO or (estilo == "grade_pontos" and cor_fundo):
            png = _fundo_desenhado("pontos" if estilo == "grade_pontos" else estilo, W, H, os.path.join(work_dir, "_fundos"), tom or "#3C4658")
        else:
            png = gerar_fundo(estilo, W, H, os.path.join(work_dir, "_fundos"), [(x, y, w + 2 * b, h + 2 * b) for (x, y, w, h, b, _c) in janelas_px],
                              tom=tom)
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{duracao + 0.5:.3f}", "-i", png]
        grafo.append(f"[0:v]fps={FPS},scale={W}:{H},setsar=1,format=yuv420p[fundo]")
    atual = "fundo"
    escurecer = float(lay.get("escurecer") or 0)

    cor_borda = "0x1d1d1d" if papel else "0xEEEAE0"
    if lay["arranjo"] == "cartao":
        cor_borda = "0xF7F4EC"
    for k, clip in enumerate(clips):
        idx = len([a for a in args if a == "-i"])
        args += ["-i", clip]
        x, y, w, h, b, cheia = janelas_px[k]
        st = max(0.0, float(inicios[k] if k < len(inicios) else 0.0))
        mov = _movimento_do_take(tid, k, lay)
        if lay.get("revela_ultimo") and k == n - 1 and n > 1:
            dx, dy = -1.0, 0.0
            dur_mov = 0.9
        else:
            dx, dy = _MOVIMENTOS.get(mov, (0, 0.04))
            dur_mov = 0.75 if mov not in ("queda", "trilho", "sobe") else 0.9
        if cheia and k == 0 and not lay.get("revela_ultimo"):
            dx = dy = 0.0  # o primeiro take em tela cheia não "entra" (senão mostra o fundo)
        cadeia = (f"[{idx}:v]setpts=PTS-STARTPTS,fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,"
                  f"crop={w}:{h},setsar=1")
        if escurecer and cheia:
            cadeia += f",eq=brightness=-{escurecer:.2f}"
        if lay.get("fundo_take0") and k == 0:
            cadeia += ",eq=brightness=-0.05"
        cadeia += ",format=yuva420p"
        if lay.get("foco") or mov == "dissolve_foco":
            cadeia += f",split=2[nit{k}][bor{k}];[bor{k}]gblur=sigma=18,fade=t=out:st=0.15:d=0.9:alpha=1[bor{k}b];[nit{k}][bor{k}b]overlay=format=auto,format=yuva420p"
        if b:
            cadeia += f",pad={w + 2 * b}:{h + 2 * b}:{b}:{b}:color={cor_borda}"
        primeiro_cheio = cheia and k == 0 and not lay.get("revela_ultimo")
        if not primeiro_cheio:
            cadeia += ",fade=t=in:st=0:d=0.45:alpha=1"
        cadeia += f",setpts=PTS+{st:.3f}/TB[t{k}]"
        grafo.append(cadeia)
        # sombra suave atrás das janelas que não ocupam a tela toda
        if not cheia:
            m = max(6, H // 60)
            sw, sh = w + 2 * b, h + 2 * b
            grafo.append(
                f"color=c=black@0.55:s={sw}x{sh}:r={FPS}:d={max(0.1, duracao - st + 0.5):.3f},format=yuva420p,"
                f"pad={sw + 4 * m}:{sh + 4 * m}:{2 * m}:{2 * m}:color=black@0,boxblur={m}:1,"
                f"fade=t=in:st=0:d=0.45:alpha=1,setpts=PTS+{st:.3f}/TB[s{k}]"
            )
        mdx, mdy = dx * W, dy * H
        ease = f"pow(1-clip((t-{st:.3f})/{dur_mov:.2f},0,1),3)"
        xe = f"{x}+({mdx:.1f})*{ease}" if mdx else str(x)
        ye = f"{y}+({mdy:.1f})*{ease}" if mdy else str(y)
        if not cheia:
            m = max(6, H // 60)
            off = max(4, H // 90)
            grafo.append(f"[{atual}][s{k}]overlay=x='{xe}-{2 * m}+{off}':y='{ye}-{2 * m}+{off * 2}':eval=frame:eof_action=pass:enable='gte(t,{st:.3f})'[c{k}s]")
            atual = f"c{k}s"
        grafo.append(f"[{atual}][t{k}]overlay=x='{xe}':y='{ye}':eval=frame:eof_action=pass:enable='gte(t,{st:.3f})'[c{k}]")
        atual = f"c{k}"
        if lay.get("flash"):
            grafo.append(f"color=c=white:s={W}x{H}:r={FPS}:d=0.5,format=yuva420p,fade=t=out:st=0:d=0.45:alpha=1,setpts=PTS+{st:.3f}/TB[f{k}]")
            grafo.append(f"[{atual}][f{k}]overlay=eof_action=pass:enable='between(t,{st:.3f},{st + 0.5:.3f})'[c{k}f]")
            atual = f"c{k}f"

    # ---- linha da "linha do tempo"
    textos: List[str] = []
    if lay.get("linha") and n > 1:
        yl = _par(max(y + h + 2 * b for (x, y, w, h, b, _c) in janelas_px) + H * 0.035)
        cor_l = "0x1b1a17" if papel else COR_LINHA
        textos.append(f"drawbox=x={int(W * 0.04)}:y={yl}:w={int(W * 0.92)}:h={max(2, H // 360)}:color={cor_l}:t=fill:enable='gte(t,{inicios[0]:.3f})'")
        for k in range(n):
            x, y, w, h, b, _c = janelas_px[k]
            r = max(4, H // 120)
            textos.append(f"drawbox=x={x + (w + 2 * b) // 2 - r}:y={yl - r + 1}:w={2 * r}:h={2 * r}:color={cor_l}:t=fill:enable='gte(t,{inicios[k]:.3f})'")

    def arquivo_txt(conteudo: str) -> str:
        p = os.path.join(work_dir, f"_txt_{uuid.uuid4().hex[:8]}.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(conteudo)
        return p

    fim_cena = duracao
    tz = lay.get("texto", (0.06, 0.8, 0.88, 0.15))
    zx, zy, zw, zh = tz
    # ---- campos fixos
    fixos = [f for f in campos_de_texto(tid) if f["source"] == "fixed"]
    for f in fixos:
        key = f["key"]
        valor = campos.get(key)
        valor = (valor if valor is not None else f.get("default") or "").strip()
        if not valor:
            continue
        take = f.get("take")
        ini = inicios[take] if isinstance(take, int) and take < n else inicios[0]
        if key == "“":
            ax, ay = lay.get("aspas", (zx, zy - 0.12))
            tam = _par(HT * 0.16)
            textos.append(_drawtext(arquivo_txt("“"), _FONTE_NEGRITO, tam, COR_DESTAQUE, str(int(W * ax)), str(int(H * ay)), ini, fim_cena))
            continue
        if key in ("ANTES", "DEPOIS"):
            j = 0 if key == "ANTES" else min(1, n - 1)
            if lay.get("revela_ultimo"):
                px_, py_ = (int(W * 0.04), int(H * 0.05)) if key == "ANTES" else (None, int(H * 0.05))
                tam = _par(HT * 0.05)
                xexpr = str(px_) if px_ is not None else f"w-text_w-{int(W * 0.04)}"
                ini_k = inicios[0] if key == "ANTES" else inicios[min(1, n - 1)]
                fim_k = (inicios[1] if (key == "ANTES" and n > 1) else fim_cena)
                textos.append(_drawtext(arquivo_txt(valor.upper()), _FONTE_NEGRITO, tam, "white", xexpr, str(py_), ini_k, fim_k, caixa="black@0.6"))
                continue
            x, y, w, h, b, _c = janelas_px[j]
            tam = _par(HT * 0.042)
            textos.append(_drawtext(arquivo_txt(valor.upper()), _FONTE_NEGRITO, tam, "white", str(x + b + tam // 2), str(y + b + tam // 2), inicios[j] if j < n else ini, fim_cena, caixa="black@0.6"))
            continue
        if key == "VS":
            tam = _par(HT * 0.11)
            textos.append(_drawtext(arquivo_txt(valor), _FONTE_NEGRITO, tam, COR_DESTAQUE, "(w-text_w)/2", "(h-text_h)/2", inicios[min(1, n - 1)], fim_cena, borda=max(2, H // 200)))
            continue
        if key in ("01", "02", "03") and isinstance(take, int) and take < n:
            x, y, w, h, b, _c = janelas_px[take]
            tam = _par(HT * 0.045)
            textos.append(_drawtext(arquivo_txt(valor), _FONTE_NEGRITO, tam, COR_DESTAQUE, str(x), str(y + h + 2 * b + int(H * 0.055)), inicios[take], fim_cena))
            continue
        if lay.get("titulo_por_take"):
            continue  # tratado abaixo
        # rótulo (TÓPICO, CAPÍTULO, PERFIL, ARQUIVO…)
        rx, ry = lay.get("rotulo", (zx, max(0.02, zy - 0.07)))
        tam = _par(HT * 0.034)
        textos.append(_drawtext(arquivo_txt(valor.upper()[: f["maxChars"]]), _FONTE_NEGRITO, tam, ("0x111111" if not pal or _clara(pal["primaria"]) else "0xFFFFFF") if not papel else "0xF4EFE2", str(int(W * rx)), str(int(H * ry)), ini, fim_cena, caixa=(COR_DESTAQUE if not papel else "0x1b1a17")))

    # ---- INTRO: um título por take, no centro
    if lay.get("titulo_por_take"):
        titulos = [str(campos.get(f["key"]) or "").strip() for f in fixos]
        titulos = [x for x in titulos if x]
        for k in range(n):
            if k >= len(titulos):
                break
            fim_k = inicios[k + 1] if k + 1 < n else fim_cena
            tam = _par(HT * (0.085 if len(titulos[k]) < 26 else 0.06))
            linhas = _quebrar(titulos[k], max(8, int(W * 0.84 / (tam * 0.6))), 3)
            for li, linha in enumerate(linhas):
                yv = int(H * 0.5 - (len(linhas) * tam * 1.25) / 2 + li * tam * 1.25)
                textos.append(_drawtext(arquivo_txt(linha), _FONTE_NEGRITO, tam, "white", "(w-text_w)/2", str(yv), inicios[k] + 0.15, fim_k, borda=max(2, H // 300)))

    # ---- fala dos takes (cobre a legenda normal)
    if tem_fala(tid) and campos.get("_fala", True) is not False:
        estilo_txt = lay.get("texto_estilo")
        maxc = 120
        for f in (template(tid) or {}).get("textFields") or []:
            if f.get("source") == "speech":
                maxc = min(maxc, int(f.get("maxChars") or 120))
        for k in range(n):
            ini = inicios[k]
            fim = inicios[k + 1] if k + 1 < n else fim_cena
            chave_campo = "legenda" if k == 0 else f"legenda:{k}"
            fala = campos.get(chave_campo)
            fala = (fala if fala is not None else (falas[k] if k < len(falas) else "")) or ""
            pal = None if campos.get(chave_campo) is not None else (palavras[k] if k < len(palavras) else None)
            if estilo_txt == "matchcut":
                pedacos = _pedacos_da_fala(fala, pal, ini, fim, 14)
                for (a, bb, txt) in pedacos:
                    tam = _par(HT * 0.12)
                    textos.append(_drawtext(arquivo_txt(txt.upper()), _FONTE_NEGRITO, tam, "white", "(w-text_w)/2", "(h-text_h)/2", a, bb, borda=max(2, H // 250), anim="corte"))
                continue
            if estilo_txt == "whoosh":
                pedacos = _pedacos_da_fala(fala, pal, ini, fim, 34)
                for (a, bb, txt) in pedacos:
                    tam = _par(HT * 0.075)
                    textos.append(_drawtext(arquivo_txt(txt), _FONTE_NEGRITO, tam, "white", "(w-text_w)/2", "(h-text_h)/2", a, bb, borda=max(2, H // 250), desloc_x=-W * 0.35))
                continue
            tam = _par(HT * (0.05 if zw > 0.6 else 0.042))
            por_linha = max(8, int(W * zw / (tam * 0.58)))
            pedacos = _pedacos_da_fala(fala, pal, ini, fim, min(maxc, por_linha * (3 if zh >= 0.3 else 2)))
            for (a, bb, txt) in pedacos:
                linhas = _quebrar(txt, por_linha, 3 if zh >= 0.3 else 2)
                alt = len(linhas) * tam * 1.3
                y0 = H * (zy + zh / 2) - alt / 2
                for li, linha in enumerate(linhas):
                    textos.append(_drawtext(arquivo_txt(linha), _FONTE_NEGRITO, tam, cor_texto, str(int(W * zx)), str(int(y0 + li * tam * 1.3)), a, bb, caixa=caixa_texto))

    if textos:
        grafo.append(f"[{atual}]" + ",".join(textos) + "[txt]")
        atual = "txt"
    grafo.append(f"[{atual}]format=yuv420p[vout]")

    script = os.path.join(work_dir, f"_cena_{uuid.uuid4().hex[:8]}.txt")
    with open(script, "w", encoding="utf-8") as f:
        f.write(";\n".join(grafo))
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args + [
        "-filter_complex_script", script, "-map", "[vout]", "-t", f"{duracao:.3f}", "-r", str(FPS),
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an", saida,
    ]
    try:
        _rodar(cmd, run)
    finally:
        for p in os.listdir(work_dir):
            if p.startswith("_txt_") or p == os.path.basename(script):
                try:
                    os.remove(os.path.join(work_dir, p))
                except OSError:
                    pass
    return saida


def _rodar(cmd: List[str], run=None) -> None:
    if run:
        return run(cmd)
    import qualidade_export
    cmd_cpu = qualidade_export._ajustar_cpu(cmd)
    cmd = qualidade_export.ajustar(cmd)
    r = qualidade_export.executar(cmd, timeout=1800, _original=cmd_cpu)
    if r.returncode != 0 and "filter_complex_script" in (r.stderr or "") and ("nrecognized" in r.stderr or "not found" in r.stderr):
        k = cmd.index("-filter_complex_script")
        r = subprocess.run(cmd[:k] + ["-/filter_complex"] + cmd[k + 1:], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    if r.returncode != 0:
        raise CenaError(f"ffmpeg falhou ao montar a cena: {(r.stderr or '').strip()[-900:]}")


# ---------------------------------------------------------------- grupos (quais trechos cada cena cobre)
def planejar_grupos(templates_por_trecho: Sequence[Optional[str]]) -> List[Tuple[int, int, Optional[str]]]:
    """[(primeiro, último, template)] cobrindo todos os trechos, na ordem.
    Um template de N slots no trecho i cobre i..i+N-1 (corta no fim do vídeo
    e não engole o trecho que começa outro template)."""
    grupos = []
    i, total = 0, len(templates_por_trecho)
    while i < total:
        tid = templates_por_trecho[i]
        if tid and template(tid):
            n = slots_do_template(tid)
            j = i
            while j + 1 < total and j + 1 < i + n and not (templates_por_trecho[j + 1] and template(templates_por_trecho[j + 1])):
                j += 1
            grupos.append((i, j, tid))
            i = j + 1
        else:
            grupos.append((i, i, None))
            i += 1
    return grupos


# ---------------------------------------------------------------- pro editor e pra IA
def _categoria(tid: str, t: Dict[str, Any]) -> str:
    if tid in ("INTRO_DOC_0", "TEXT_MATCH_CUT_0", "WHOOSH_STUDIO_0"):
        return "Abertura e legenda"
    if tid.startswith("ED_"):
        return "Editorial (com texto)"
    if tid.startswith("REF_"):
        return "Referência (manual)"
    if tid.startswith("C30_") or tid.startswith("C50_"):
        return "Cinema 50 — " + ("Cenas" if int(t.get("slots") or 1) == 1 else f"Takes de {t['slots']}")
    fam = t.get("familia") or ""
    return {"moldura": "Molduras", "retrato": "Retratos", "frentefundo": "Frente & Fundo"}.get(fam, "Takes" if int(t.get("slots") or 1) > 1 else "Cenas")


def catalogo_para_editor() -> List[Dict[str, Any]]:
    out = []
    for tid, t in catalogo().items():
        lay = layout(tid)
        n = int(t.get("slots") or 1)
        jan = lay["janelas"] if lay["arranjo"] != "sequencia_tela_cheia" else [(0, 0, 1, 1)]
        out.append({
            "id": tid, "nome": t["nome"], "slots": n, "categoria": _categoria(tid, t),
            "dur_min": t.get("durMinS"), "dur_ideal": t.get("durIdealS") or t.get("durS"), "dur_max": t.get("durMaxS"),
            "quando": (t.get("whenToUse") or [""])[0], "evitar": (t.get("whenNotToUse") or [""])[0],
            "campos": [c for c in campos_de_texto(tid) if c["source"] == "fixed"],
            "fala": tem_fala(tid),
            "fundos": [[e, NOMES_FUNDO.get(e, ("Cor " + e[3:]) if re.fullmatch(r"cor\d+", e) else e), _css_fundo(e)] for e in fundos_do_template(tid)],
            "fundo_take0": bool(lay.get("fundo_take0")), "revela_ultimo": bool(lay.get("revela_ultimo")),
            "janelas": [list(j) for j in jan[: max(1, n if lay["arranjo"] != "sequencia_tela_cheia" else 1)]],
            "texto": list(lay.get("texto") or []), "arranjo": lay["arranjo"], "auto": bool(t.get("autoEligible")),
            # o mesmo arranjo adaptado pro vídeo vertical (9:16) — o monitor do Estúdio usa quando o formato é vertical
            "janelas_v": [list(j) for j in (adaptar_layout(lay, 1080, 1920)["janelas"] if lay["arranjo"] != "sequencia_tela_cheia" else [(0, 0, 1, 1)])[: max(1, n if lay["arranjo"] != "sequencia_tela_cheia" else 1)]],
            "texto_v": list(adaptar_layout(lay, 1080, 1920).get("texto") or []),
            "fundo_css": _css_fundo(fundos_do_template(tid)[0]),
        })
    ordem = ["Molduras", "Cenas", "Retratos", "Takes", "Frente & Fundo", "Editorial (com texto)", "Abertura e legenda", "Referência (manual)"]
    out.sort(key=lambda c: (ordem.index(c["categoria"]) if c["categoria"] in ordem else 50 + (len(c["categoria"])), c["categoria"], c["slots"], c["nome"]))
    return out


def _css_fundo(estilo: str) -> str:
    if re.fullmatch(r"cor\d+", estilo):
        esc, cla = _PALETA[int(estilo[3:]) % len(_PALETA)]
        return f"radial-gradient(circle,rgb{cla},rgb{esc})"
    return {
        "papel": "#e9e2d0", "concreto": "#3a3a3d", "clarao": "radial-gradient(circle at 50% 40%,#7a6a55,#0b0b0d 70%)",
        "luz": "linear-gradient(135deg,#0c0c0f,#4a443e)", "borda_queimada": "radial-gradient(circle,#4a2e1e,#0a0705)",
        "vidro": "linear-gradient(135deg,#335,#223)", "filme": "#080808",
    }.get(estilo, "#141417")


def bloco_para_prompt(max_itens: int = 60) -> str:
    """Resumo dos templates automáticos pra IA escolher (o prompt fica enxuto)."""
    linhas = []
    for tid, t in catalogo().items():
        if not t.get("autoEligible") or t.get("manualOnly"):
            continue
        fixos = [f["key"] for f in campos_de_texto(tid) if f["source"] == "fixed" and f["key"] not in ("“",)]
        q = (t.get("whenToUse") or [""])[0][:110]
        linhas.append(
            f"- {tid} | {t['nome']} | trechos={int(t.get('slots') or 1)} | dur {t.get('durMinS') or 2.5}-{t.get('durMaxS') or 24}s"
            + (f" | campos: {', '.join(fixos)}" if fixos else "") + (" | mostra a fala" if tem_fala(tid) else "") + f" | quando: {q}"
        )
    # prioriza famílias variadas
    return "\n".join(linhas[:max_itens])
