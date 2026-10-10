"""
Catálogo visual do DarkPlanner (darkplanner.json -> "catalogs"), recriado com ffmpeg:

  * 74 FILTROS de cor   -> cadeia de filtros do ffmpeg (identidade GLOBAL: 1 por vídeo)
  * 28 EFEITOS          -> movimento de câmera (só foto, Ken Burns) ou atmosfera
                           (luz vazando, poeira, neblina, scanlines, bokeh…) por trecho
  * 37 ENTRADAS/SAÍDAS  -> gesto no começo/fim do trecho (pop, punch, spin, tv_on…)
  * 201 TRANSIÇÕES      -> xfade nativo do ffmpeg ou expressão própria (film burn,
                           light leak, glitch, splash, estática, coração, estrela…)

O JSON traz só nome/família/intensidade/energia; o visual é uma recriação.
"""
from __future__ import annotations

import json
import math
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

_AQUI = os.path.dirname(os.path.abspath(__file__))
DP_JSON = os.path.join(_AQUI, "assets", "darkplanner", "darkplanner.json")


@lru_cache(maxsize=1)
def dp() -> Dict[str, Any]:
    with open(DP_JSON, encoding="utf-8") as f:
        return json.load(f)


def _catalogo(nome: str) -> List[Dict[str, Any]]:
    v = dp()["catalogs"].get(nome)
    if nome == "exits":
        v = dp()["catalogs"]["entrances"]  # "same ids and profiles as entrances"
    return list(v or [])


def _humano(s: str) -> str:
    s = re.sub(r"^(gl_oss_|gl_|ft_pk2_|ft_pk_|ft_|cb_|ov_|fv_)", "", s)
    s = s.replace("_", " ").strip()
    return s[:1].upper() + s[1:]


# =============================================================== FILTROS (74)
_F = {
    "original": ("Original", ""),
    "bw": ("Preto e branco", "hue=s=0"),
    "noir": ("Noir", "hue=s=0,eq=contrast=1.35:brightness=-0.03,vignette=angle=PI/5"),
    "soft": ("Suave", "eq=contrast=0.92:saturation=0.9:brightness=0.02,gblur=sigma=0.6"),
    "fade": ("Desbotado", "curves=all='0/0.08 1/0.95',eq=saturation=0.82"),
    "sepia": ("Sépia", "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131"),
    "vintage": ("Vintage", "curves=preset=vintage,eq=saturation=0.85"),
    "vhs": ("VHS", "eq=saturation=1.3:contrast=1.1,rgbashift=rh=3:bh=-3,noise=alls=12:allf=t,gblur=sigma=0.7:sigmaV=0.1"),
    "old_film": ("Filme antigo", "hue=s=0.2,curves=preset=vintage,noise=alls=18:allf=t,vignette=angle=PI/4"),
    "cinematic": ("Cinematográfico", "eq=contrast=1.1:saturation=0.9,colorbalance=rs=-0.05:bs=0.08:rh=0.08:bh=-0.06,vignette=angle=PI/5"),
    "teal_orange": ("Teal & Orange", "colorbalance=rs=-0.15:gs=-0.05:bs=0.2:rh=0.18:gh=0.05:bh=-0.18,eq=contrast=1.08"),
    "blockbuster": ("Blockbuster", "colorbalance=rs=-0.15:bs=0.2:rh=0.18:bh=-0.18,eq=contrast=1.2:saturation=1.1"),
    "thriller": ("Suspense", "eq=saturation=0.6:contrast=1.2,colorbalance=gs=0.06:gm=0.05"),
    "documentary": ("Documentário", "eq=saturation=0.85:contrast=1.05,curves=all='0/0.03 1/0.97'"),
    "warm": ("Quente", "colorbalance=rm=0.08:gm=0.02:bm=-0.08"),
    "cold": ("Frio", "colorbalance=rm=-0.06:bm=0.1"),
    "dramatic": ("Dramático", "eq=contrast=1.35:saturation=1.15,vignette=angle=PI/4"),
    "dreamy": ("Sonho", "eq=brightness=0.05:saturation=1.1,gblur=sigma=1.2"),
    "moonlight": ("Luar", "hue=s=0.4,colorbalance=bs=0.2:bm=0.15:rh=-0.05,eq=brightness=-0.05"),
    "sunset": ("Pôr do sol", "colorbalance=rs=0.15:rm=0.12:bm=-0.12:bh=-0.1,eq=saturation=1.15"),
    "golden_hour": ("Hora dourada", "colorbalance=rm=0.1:gm=0.04:bm=-0.12:rh=0.06,eq=saturation=1.1:brightness=0.02"),
    "vivid": ("Vívido", "eq=saturation=1.45:contrast=1.08"),
    "punch": ("Punch", "eq=saturation=1.3:contrast=1.25"),
    "neon": ("Neon", "eq=saturation=1.7:contrast=1.2,colorbalance=rh=0.1:bh=0.15"),
    "cyberpunk": ("Cyberpunk", "colorbalance=rs=0.1:bs=0.25:gm=-0.12:rh=0.18:bh=0.2,eq=saturation=1.3:contrast=1.15"),
    "pastel": ("Pastel", "eq=saturation=0.65:brightness=0.06:contrast=0.9"),
    "matte": ("Fosco", "curves=all='0/0.1 0.5/0.5 1/0.9',eq=saturation=0.9"),
    "bleach": ("Bleach bypass", "eq=saturation=0.45:contrast=1.3"),
    "emerald": ("Esmeralda", "colorbalance=gs=0.1:gm=0.12:rm=-0.06,eq=saturation=1.1"),
    "crimson": ("Carmim", "colorbalance=rs=0.12:rm=0.15:gm=-0.06,eq=saturation=1.1"),
    "midnight": ("Meia-noite", "colorbalance=bs=0.2:bm=0.12,eq=brightness=-0.08:saturation=0.8"),
    "sunbleach": ("Sol desbotado", "eq=brightness=0.08:saturation=0.7:contrast=0.9,colorbalance=rh=0.06"),
    "tape": ("Fita", "noise=alls=8:allf=t,eq=saturation=0.9,rgbashift=rh=2"),
    "noir_soft": ("Noir suave", "hue=s=0,eq=contrast=1.15,curves=all='0/0.05 1/0.95'"),
    "clarendon": ("Clarendon", "eq=contrast=1.2:saturation=1.35,colorbalance=bs=0.05"),
    "gingham": ("Gingham", "eq=brightness=0.05:saturation=0.85:contrast=0.9,hue=h=-10"),
    "moon": ("Moon", "hue=s=0,eq=contrast=1.1:brightness=0.08"),
    "lark": ("Lark", "eq=brightness=0.08:saturation=0.9,colorbalance=bs=0.05:rs=-0.03"),
    "reyes": ("Reyes", "eq=brightness=0.1:contrast=0.85:saturation=0.75"),
    "juno": ("Juno", "eq=saturation=1.35:contrast=1.15,colorbalance=rh=0.06"),
    "slumber": ("Slumber", "eq=saturation=0.66:brightness=0.05,colorbalance=rs=0.05:bm=-0.05"),
    "crema": ("Crema", "eq=saturation=0.85:contrast=0.9,colorbalance=rm=0.04"),
    "ludwig": ("Ludwig", "eq=contrast=1.05:saturation=0.85,colorbalance=rh=0.04"),
    "aden": ("Aden", "hue=h=-20,eq=saturation=0.85:brightness=0.06:contrast=0.9"),
    "perpetua": ("Perpetua", "colorbalance=gs=0.05:bs=0.05,eq=brightness=0.04"),
    "amaro": ("Amaro", "eq=contrast=0.9:brightness=0.08:saturation=1.3,hue=h=-10"),
    "mayfair": ("Mayfair", "eq=contrast=1.1:saturation=1.1,colorbalance=rh=0.06"),
    "rise": ("Rise", "eq=brightness=0.06:contrast=0.9:saturation=0.9,colorbalance=rm=0.05"),
    "hudson": ("Hudson", "eq=contrast=0.9:brightness=0.05:saturation=1.1,colorbalance=bs=0.08"),
    "valencia": ("Valencia", "eq=contrast=1.08:brightness=0.06,colorbalance=rm=0.06:bs=-0.04"),
    "xpro2": ("X-Pro II", "curves=preset=cross_process"),
    "sierra": ("Sierra", "eq=contrast=0.85:brightness=0.05:saturation=0.8"),
    "willow": ("Willow", "hue=s=0.05,eq=contrast=0.95:brightness=0.05"),
    "lofi": ("Lo-Fi", "eq=saturation=1.1:contrast=1.5"),
    "inkwell": ("Inkwell", "hue=s=0,eq=contrast=1.1:brightness=0.03"),
    "hefe": ("Hefe", "eq=contrast=1.2:saturation=1.3,vignette=angle=PI/5"),
    "nashville": ("Nashville", "colorbalance=rs=0.08:bh=0.1:rh=0.06,eq=contrast=1.1:brightness=0.03"),
    "stinson": ("Stinson", "eq=contrast=0.75:saturation=0.85:brightness=0.06"),
    "earlybird": ("Earlybird", "curves=preset=vintage,eq=contrast=0.9,vignette=angle=PI/5"),
    "brannan": ("Brannan", "eq=contrast=1.4:saturation=0.8,colorbalance=rh=0.05"),
    "toaster": ("Toaster", "eq=contrast=1.4:brightness=-0.05,colorbalance=rs=0.1:rm=0.1,vignette=angle=PI/4"),
    "walden": ("Walden", "eq=brightness=0.1:saturation=1.3,hue=h=-10,colorbalance=bs=0.05"),
    "f1977": ("1977", "eq=contrast=1.1:brightness=0.06:saturation=1.3,colorbalance=rs=0.08"),
    "kelvin": ("Kelvin", "colorbalance=rm=0.15:rh=0.1:bm=-0.15,eq=saturation=1.5"),
    "noite_gelada": ("Noite gelada", "colorbalance=bs=0.2:bm=0.1,eq=brightness=-0.05:saturation=0.75"),
    "verao_brilha": ("Verão brilha", "eq=saturation=1.3:brightness=0.06,colorbalance=rm=0.06"),
    "azul_ilha": ("Azul ilha", "colorbalance=bm=0.12:gm=0.04:bs=0.1"),
    "ceu_coral": ("Céu coral", "colorbalance=rm=0.12:rh=0.06:bm=0.04"),
    "pele_avelud": ("Pele aveludada", "eq=saturation=0.95:contrast=0.92:brightness=0.03,colorbalance=rm=0.05"),
    "preto_frio": ("Preto frio", "hue=s=0,colorbalance=bs=0.08:bm=0.06"),
    "violeta_suave": ("Violeta suave", "colorbalance=rm=0.06:bm=0.12:gm=-0.05"),
    "negativo": ("Negativo", "negate"),
    "laranja_fresca": ("Laranja fresca", "colorbalance=rm=0.12:gm=0.04:bm=-0.1:bs=0.05"),
    "azul_isolado": ("Azul isolado", "eq=saturation=0.4,colorbalance=bs=0.18:bm=0.1"),
}


def filtros() -> List[Dict[str, Any]]:
    out = []
    for item in _catalogo("filters"):
        fid = item["id"]
        rot, cadeia = _F.get(fid, (_humano(fid), ""))
        out.append({"id": fid, "rotulo": rot, "grupo": item.get("group"), "cadeia": cadeia})
    return out


def cadeia_filtro(fid: Optional[str]) -> str:
    if not fid or fid == "original":
        return ""
    return _F.get(fid, ("", ""))[1]


# =============================================================== EFEITOS (28)
# movimento (só foto): vira um modo do Ken Burns do montador
EFEITO_PARA_ZOOM = {
    "zoom_in": "in", "zoom_out": "out", "pan_esq": "pan_left", "pan_dir": "pan_right",
    "pan_cima": "pan_up", "pan_baixo": "pan_down", "zoom_rapido": "rapido",
    "zoom_pan_esq": "zoom_pan_left", "zoom_pan_dir": "zoom_pan_right", "zoom_pan_cima": "zoom_pan_up",
    "zoom_giro": "giro", "zoom_respiro": "respiro",
}
_ROT_EFEITO = {
    "none": "Nenhum", "zoom_in": "Zoom in", "zoom_out": "Zoom out", "zoom_rapido": "Zoom rápido",
    "pan_esq": "Pan ← esquerda", "pan_dir": "Pan → direita", "pan_cima": "Pan ↑ cima", "pan_baixo": "Pan ↓ baixo",
    "zoom_pan_esq": "Zoom + pan esquerda", "zoom_pan_dir": "Zoom + pan direita", "zoom_pan_cima": "Zoom + pan cima",
    "zoom_giro": "Zoom com giro", "zoom_respiro": "Zoom respirando", "fv_galaxy": "Galáxia (estrelas)",
    "ov_leak": "Luz vazando", "ov_vinheta_pulso": "Vinheta pulsando", "ov_scanlines": "Scanlines (TV)",
    "ov_sujeira": "Sujeira de película", "ov_flash_borda": "Flash nas bordas", "ov_poeira": "Poeira no ar",
    "ov_neblina": "Neblina", "ov_bokeh_suave": "Bokeh suave", "ov_facho_suave": "Facho de luz",
    "ov_fumaca_rasteira": "Fumaça rasteira", "ov_veu_dourado": "Véu dourado", "ov_particulas_lentas": "Partículas lentas",
    "chroma": "Aberração cromática", "flicker": "Tremulação de luz",
}


def efeitos() -> List[Dict[str, Any]]:
    return [{"id": e["id"], "rotulo": _ROT_EFEITO.get(e["id"], _humano(e["id"])), "familia": e.get("familia"),
             "so_foto": bool(e.get("precisaImagem")), "int": e.get("int"), "energia": e.get("energia")} for e in _catalogo("effects")]


def efeito_e_movimento(eid: Optional[str]) -> bool:
    return bool(eid) and eid in EFEITO_PARA_ZOOM


# ---- texturas geradas (PNG com transparência) pros efeitos de atmosfera
def _png_textura(tipo: str, W: int, H: int, pasta: str) -> str:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, f"tex_{tipo}_{W}x{H}.png")
    if os.path.exists(caminho):
        return caminho
    rng = np.random.default_rng(abs(hash((tipo, W, H))) % (2 ** 32))
    if tipo == "leak":
        w, h = int(W * 1.8), H
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        g = np.exp(-(((xx - w * 0.35) / (w * 0.16)) ** 2 + ((yy - h * 0.4) / (h * 0.7)) ** 2))
        g2 = np.exp(-(((xx - w * 0.68) / (w * 0.1)) ** 2 + ((yy - h * 0.7) / (h * 0.5)) ** 2))
        a = np.clip(g * 0.55 + g2 * 0.4, 0, 1)
        img = np.dstack([np.full((h, w), 255), 120 + 80 * g2, 40 + 40 * g, a * 255]).astype(np.uint8)
        Image.fromarray(img, "RGBA").save(caminho)
    elif tipo == "scanlines":
        a = np.zeros((H + 8, W), np.uint8)
        a[::4, :] = 55
        a[1::4, :] = 25
        img = np.dstack([np.zeros_like(a)] * 3 + [a])
        Image.fromarray(img, "RGBA").save(caminho)
    elif tipo in ("sujeira", "poeira", "particulas", "estrelas"):
        larg, alt = int(W * 1.2), int(H * (2.0 if tipo != "sujeira" else 1.2))
        im = Image.new("RGBA", (larg, alt), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        n = {"sujeira": 140, "poeira": 220, "particulas": 70, "estrelas": 420}[tipo]
        for _ in range(n):
            x, y = rng.integers(0, larg), rng.integers(0, alt)
            if tipo == "sujeira":
                r = rng.integers(1, max(2, H // 200) + 3)
                cor = (20, 18, 15, int(rng.integers(90, 200))) if rng.random() < 0.6 else (240, 236, 220, int(rng.integers(80, 170)))
                if rng.random() < 0.15:
                    d.line([x, y, x + rng.integers(-3, 4), y + rng.integers(H // 20, H // 6)], fill=cor, width=1)
                else:
                    d.ellipse([x - r, y - r, x + r, y + r], fill=cor)
            else:
                r = {"poeira": rng.uniform(0.6, 2.2), "particulas": rng.uniform(2, 5), "estrelas": rng.uniform(0.5, 2.0)}[tipo] * max(1, H / 720)
                alfa = int(rng.integers(70, 200))
                d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 246, 225, alfa))
        if tipo in ("particulas", "poeira"):
            im = im.filter(ImageFilter.GaussianBlur(1.2 * max(1, H / 720)))
        im.save(caminho)
    elif tipo in ("neblina", "fumaca"):
        w, h = int(W * 2), H
        base = rng.random((h // 24 + 2, w // 24 + 2))
        n = np.array(Image.fromarray((base * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(H / 30)), np.float32) / 255
        if tipo == "fumaca":
            yy = np.mgrid[0:h, 0:w][0].astype(np.float32) / h
            n = n * np.clip((yy - 0.45) / 0.55, 0, 1) * 1.4
        a = np.clip((n - 0.25) * 1.1, 0, 1) * (150 if tipo == "neblina" else 200)
        img = np.dstack([np.full((h, w), 225), np.full((h, w), 228), np.full((h, w), 232), a]).astype(np.uint8)
        Image.fromarray(img, "RGBA").save(caminho)
    elif tipo == "bokeh":
        larg, alt = int(W * 1.4), H
        im = Image.new("RGBA", (larg, alt), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for _ in range(26):
            x, y = rng.integers(0, larg), rng.integers(0, alt)
            r = rng.uniform(0.02, 0.07) * H
            cor = [(255, 214, 140), (255, 180, 120), (180, 220, 255), (255, 240, 200)][rng.integers(0, 4)]
            d.ellipse([x - r, y - r, x + r, y + r], fill=cor + (int(rng.integers(40, 95)),))
        im.filter(ImageFilter.GaussianBlur(H / 160)).save(caminho)
    elif tipo == "facho":
        w, h = int(W * 1.6), H
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d_ = (xx - w * 0.4) * 0.8 - (yy - h * 0.0) * 0.6
        a = np.exp(-(d_ / (w * 0.07)) ** 2) * np.clip(1 - yy / h * 0.7, 0, 1)
        img = np.dstack([np.full((h, w), 255), np.full((h, w), 240), np.full((h, w), 205), a * 120]).astype(np.uint8)
        Image.fromarray(img, "RGBA").save(caminho)
    elif tipo == "veu":
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        g = np.clip(1 - np.hypot((xx - W * 0.3) / W, (yy - H * 0.2) / H) * 1.3, 0, 1)
        img = np.dstack([np.full((H, W), 255), np.full((H, W), 200), np.full((H, W), 90), g * 80]).astype(np.uint8)
        Image.fromarray(img, "RGBA").save(caminho)
    elif tipo == "borda":
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        dd = np.minimum(np.minimum(xx, W - xx) / W, np.minimum(yy, H - yy) / H)
        a = np.clip(1 - dd / 0.12, 0, 1) ** 2
        img = np.dstack([np.full((H, W), 255), np.full((H, W), 250), np.full((H, W), 235), a * 200]).astype(np.uint8)
        Image.fromarray(img, "RGBA").save(caminho)
    return caminho


def atmosfera(eid: str, W: int, H: int, dur: float, pasta: str) -> Tuple[List[str], List[str]]:
    """(entradas extras do ffmpeg, filtros) pra um efeito de atmosfera. Os
    filtros recebem [base] e devem terminar em [base] de novo (cadeia)."""
    if eid == "chroma":
        return [], [f"[base]rgbashift=rh={max(2, W // 320)}:bh=-{max(2, W // 320)}:gv={max(1, W // 640)}[base]"]
    if eid == "flicker":
        return [], ["[base]eq=brightness='0.05*sin(37*t)*sin(11*t)+0.02*sin(91*t)':eval=frame[base]"]
    if eid == "ov_vinheta_pulso":
        return [], ["[base]vignette=angle='PI/4.2+0.12*sin(2*PI*t/1.8)':eval=frame[base]"]
    tex = {"ov_leak": "leak", "ov_scanlines": "scanlines", "ov_sujeira": "sujeira", "ov_poeira": "poeira",
           "ov_neblina": "neblina", "ov_bokeh_suave": "bokeh", "ov_facho_suave": "facho", "ov_fumaca_rasteira": "fumaca",
           "ov_veu_dourado": "veu", "ov_particulas_lentas": "particulas", "fv_galaxy": "estrelas", "ov_flash_borda": "borda"}.get(eid)
    if not tex:
        return [], []
    png = _png_textura(tex, W, H, pasta)
    ent = ["-loop", "1", "-framerate", "30", "-t", f"{dur + 0.5:.3f}", "-i", png]
    pos = {
        "leak": ("'-w*0.45+(w-W)*0.0+W*0.35*sin(t*0.6)'", "0"),
        "scanlines": ("0", "'-mod(t*24,4)'"),
        "sujeira": ("'-mod(n*7919,97)/97*W*0.18'", "'-mod(n*104729,89)/89*H*0.18'"),
        "poeira": ("'-W*0.1+W*0.04*sin(t*0.5)'", "'-mod(t*H*0.05,h-H)'"),
        "particulas": ("'-W*0.1+W*0.05*sin(t*0.3)'", "'-mod(t*H*0.03,h-H)'"),
        "estrelas": ("'-W*0.1+t*W*0.01'", "'-h*0.25'"),
        "neblina": ("'-mod(t*W*0.03,w-W)'", "0"),
        "fumaca": ("'-mod(t*W*0.05,w-W)'", "0"),
        "bokeh": ("'-(w-W)/2+(w-W)/2*sin(t*0.25)'", "'H*0.02*sin(t*0.4)'"),
        "facho": ("'-(w-W)/2+(w-W)/2*sin(t*0.35)'", "0"),
        "veu": ("'W*0.03*sin(t*0.5)'", "0"),
        "borda": ("0", "0"),
    }[tex]
    extra = ""
    if tex == "borda":
        extra = ":enable='lt(mod(t,1.7),0.18)'"
    if tex == "estrelas":
        return ent, [f"[{{i}}:v]format=rgba[tx];[base][tx]overlay=x={pos[0]}:y={pos[1]}:eval=frame:shortest=1[base]",
                     "[base]eq=brightness='0.015*sin(9*t)':eval=frame[base]"]
    return ent, [f"[{{i}}:v]format=rgba[tx];[base][tx]overlay=x={pos[0]}:y={pos[1]}:eval=frame:shortest=1{extra}[base]"]


# =============================================================== ENTRADAS / SAÍDAS (37)
_ROT_ENTRADA = {
    "none": "Nenhuma", "fade": "Fade", "zoom_in": "Zoom in", "zoom_out": "Zoom out", "slide_up": "Desliza ↑",
    "slide_down": "Desliza ↓", "slide_left": "Desliza ←", "slide_right": "Desliza →", "pop": "Pop", "blur_in": "Desfoque",
    "focus": "Foco", "flash": "Flash", "spin": "Giro", "drop": "Queda", "shake": "Tremor", "vibration": "Vibração",
    "wobble": "Balanço", "swing": "Pêndulo", "stretch": "Estica", "flip_3d": "Virada 3D", "tv_on": "TV ligando",
    "zoom_soft": "Zoom suave", "punch_in": "Punch in", "shockwave": "Onda de choque", "slingshot": "Estilingue",
    "spring_in": "Mola", "ghost_trail": "Rastro fantasma", "soft_land": "Pouso suave", "smoke": "Fumaça",
    "assenta": "Assenta", "desliza_suave": "Desliza suave", "ergue_suave": "Ergue suave", "revela_esq": "Revela ←",
    "revela_cima": "Revela ↑", "revela_diag": "Revela diagonal", "dissolve_foco": "Dissolve com foco", "escala_entra": "Escala",
}


def entradas() -> List[Dict[str, Any]]:
    return [{"id": e["id"], "rotulo": _ROT_ENTRADA.get(e["id"], _humano(e["id"])), "familia": e.get("familia"),
             "dur": e.get("durAlvoS"), "int": e.get("int"), "energia": e.get("energia")} for e in _catalogo("entrances")]


def _dur_gesto(gid: str, dur_cena: float) -> float:
    alvo = next((e.get("durAlvoS") for e in _catalogo("entrances") if e["id"] == gid), 0.5) or 0.5
    return max(0.2, min(1.2, float(alvo), dur_cena * 0.35))


def _gesto(gid: str, p: str, W: int, H: int) -> Dict[str, str]:
    """Parâmetros do gesto em função de p (0 = começo do gesto, 1 = assentado).
    Saída = o mesmo gesto com p invertido. Devolve expressões pra escala (s),
    deslocamento (dx, dy, em px), rotação (r, rad), e flags."""
    e = f"(1-pow(1-{p},3))"  # ease-out
    inv = f"(1-{e})"
    g: Dict[str, str] = {"s": "1", "sx": "", "sy": "", "dx": "0", "dy": "0", "r": "0", "fade": "1", "flash": "", "blur": "", "lag": ""}
    if gid == "fade":
        pass
    elif gid in ("zoom_in", "escala_entra"):
        g["s"] = f"(0.6+0.4*{e})"
    elif gid == "zoom_out":
        g["s"] = f"(1.35-0.35*{e})"
    elif gid == "zoom_soft":
        g["s"] = f"(1.08-0.08*{e})"
    elif gid in ("slide_up", "ergue_suave"):
        g["dy"] = f"({H * (1.0 if gid == 'slide_up' else 0.08):.0f}*{inv})"
    elif gid in ("slide_down", "soft_land", "drop"):
        g["dy"] = f"(-{H * {'slide_down': 1.0, 'soft_land': 0.06, 'drop': 0.5}[gid]:.0f}*{inv})"
        if gid == "drop":
            g["dy"] = f"(-{H * 0.6:.0f}*pow(1-{p},2)*abs(cos({p}*PI*1.5)))"
    elif gid in ("slide_left", "desliza_suave"):
        g["dx"] = f"({W * (1.0 if gid == 'slide_left' else 0.08):.0f}*{inv})"
    elif gid == "slide_right":
        g["dx"] = f"(-{W:.0f}*{inv})"
    elif gid == "revela_esq":
        g["dx"] = f"(-{W * 0.1:.0f}*{inv})"
    elif gid == "revela_cima":
        g["dy"] = f"(-{H * 0.1:.0f}*{inv})"
    elif gid == "revela_diag":
        g["dx"] = f"(-{W * 0.08:.0f}*{inv})"
        g["dy"] = f"(-{H * 0.08:.0f}*{inv})"
    elif gid == "assenta":
        g["dy"] = f"({H * 0.04:.0f}*{inv})"
        g["s"] = f"(1.03-0.03*{e})"
    elif gid == "pop":
        g["s"] = f"(0.5+0.5*{p}+0.18*sin({p}*PI))"
    elif gid == "punch_in":
        g["s"] = f"(1.45-0.45*{e})"
        g["flash"] = "0.35"
    elif gid == "spring_in":
        g["s"] = f"(1-exp(-6*{p})*cos(12*{p}))"
    elif gid == "slingshot":
        g["dx"] = f"(-{W:.0f}*(1-{p})*cos({p}*PI*1.3))"
    elif gid == "spin":
        g["r"] = f"(2*PI*{inv})"
        g["s"] = f"(0.4+0.6*{e})"
    elif gid in ("shake", "vibration"):
        amp = 0.025 if gid == "shake" else 0.01
        fr = 40 if gid == "shake" else 90
        g["dx"] = f"({W * amp:.1f}*sin({fr}*t)*(1-{p}))"
        g["dy"] = f"({H * amp:.1f}*cos({fr * 0.8}*t)*(1-{p}))"
        g["s"] = "1.05"
        g["fade"] = ""
    elif gid in ("wobble", "swing"):
        g["r"] = f"({0.08 if gid == 'wobble' else 0.18}*sin({p}*PI*4)*(1-{p}))"
        g["s"] = "1.12"
    elif gid == "stretch":
        g["sx"] = f"(0.3+0.7*{e}+0.08*sin({p}*PI))"
        g["sy"] = f"(1.15-0.15*{e})"
    elif gid == "flip_3d":
        g["sx"] = f"max(0.02,abs(cos({inv}*PI/2)))"
    elif gid == "tv_on":
        g["sy"] = f"max(0.01,pow({p},2))"
        g["sx"] = f"min(1,0.15+{p}*3)"
        g["flash"] = "0.6"
    elif gid == "shockwave":
        g["s"] = f"(1+0.12*sin({p}*PI)*(1-{p}))"
        g["flash"] = "0.5"
    elif gid in ("blur_in", "focus", "dissolve_foco", "smoke"):
        g["blur"] = "1"
        if gid == "smoke":
            g["s"] = f"(1.06-0.06*{e})"
    elif gid == "flash":
        g["flash"] = "0.9"
        g["fade"] = ""
    elif gid == "ghost_trail":
        g["lag"] = "1"
        g["dx"] = f"({W * 0.15:.0f}*{inv})"
    return g


def cadeia_gesto(entrada: Optional[str], saida: Optional[str], dur: float, W: int, H: int) -> List[str]:
    """Filtros pra aplicar entrada/saída num clipe W×H de `dur` segundos.
    Recebe [base] e devolve [base]. Vazio = nada a fazer."""
    if (not entrada or entrada == "none") and (not saida or saida == "none"):
        return []
    partes: List[str] = []
    gestos = []
    if entrada and entrada != "none":
        d = _dur_gesto(entrada, dur)
        gestos.append(("in", entrada, d, f"clip(t/{d:.3f},0,1)", f"lt(t,{d:.3f})"))
    if saida and saida != "none":
        d = _dur_gesto(saida, dur)
        gestos.append(("out", saida, d, f"clip(({dur:.3f}-t)/{d:.3f},0,1)", f"gt(t,{dur - d:.3f})"))
    # combina: fora da janela de cada gesto, p=1 (parado)
    def comb(campo, neutro):
        exprs = []
        for (_k, gid, _d, p, _jan) in gestos:
            v = _gesto(gid, p, W, H)[campo]
            if v:
                exprs.append(v)
        if not exprs:
            return neutro
        if campo in ("s", "sx", "sy"):
            return "*".join(f"({x})" for x in exprs)
        return "+".join(f"({x})" for x in exprs)

    s = comb("s", "1")
    sx = comb("sx", "")
    sy = comb("sy", "")
    sxe = f"({s})*({sx})" if sx else s
    sye = f"({s})*({sy})" if sy else s
    dx, dy, r = comb("dx", "0"), comb("dy", "0"), comb("r", "0")
    geo = any(x not in ("1", "0") for x in (s, dx, dy, r)) or sx or sy
    partes.append("[base]split=2[gesto][gfundo]")
    cadeia = "[gesto]"
    filtros_g: List[str] = []
    for (k, gid, d, p, jan) in gestos:
        g = _gesto(gid, p, W, H)
        if g["blur"]:
            st = 0 if k == "in" else dur - d
            tipo = "out" if k == "in" else "in"
            filtros_g.append(f"split=2[nb{k}][bb{k}];[bb{k}]gblur=sigma={max(8, H // 40)},format=yuva420p,fade=t={tipo}:st={st:.3f}:d={d:.3f}:alpha=1[bb{k}2];[nb{k}][bb{k}2]overlay=format=auto")
        if g["lag"]:
            filtros_g.append(f"lagfun=decay=0.93:enable='{jan}'")
    if geo:
        filtros_g.append(
            f"scale=w='max(2,trunc({W}*({sxe})/2)*2)':h='max(2,trunc({H}*({sye})/2)*2)':eval=frame"
        )
        if r != "0":
            filtros_g.append(f"rotate=a='{r}':c=black@0:ow='iw':oh='ih'")
    filtros_g.append("format=yuva420p")
    for (k, gid, d, p, jan) in gestos:
        if _gesto(gid, p, W, H)["fade"]:
            if k == "in":
                filtros_g.append(f"fade=t=in:st=0:d={min(d, 0.45):.3f}:alpha=1")
            else:
                filtros_g.append(f"fade=t=out:st={dur - min(d, 0.45):.3f}:d={min(d, 0.45):.3f}:alpha=1")
    partes.append(cadeia + ",".join(filtros_g) + "[gesto2]")
    partes.append(f"color=c=black:s={W}x{H}:r=30:d={dur + 0.2:.3f}[gpreto]")
    partes.append("[gfundo]nullsink")
    partes.append(f"[gpreto][gesto2]overlay=x='(W-w)/2+({dx})':y='(H-h)/2+({dy})':eval=frame:shortest=1[base]")
    for (k, gid, d, p, jan) in gestos:
        f = _gesto(gid, p, W, H)["flash"]
        if f:
            st = 0 if k == "in" else max(0, dur - d)
            partes.append(f"color=c=white:s={W}x{H}:r=30:d={min(d, 0.5):.3f},format=yuva420p,colorchannelmixer=aa={f},fade=t=out:st=0:d={min(d, 0.5):.3f}:alpha=1,setpts=PTS+{st:.3f}/TB[fl{k}]")
            partes.append(f"[base][fl{k}]overlay=eof_action=pass[base]")
    return partes


# =============================================================== TRANSIÇÕES (201)
_BRANCO = "if(eq(PLANE,0),235,128)"
_PRETO = "if(eq(PLANE,0),16,128)"
_MIX = "(A*(1-P)+B*P)"
_BUMP = "max(0,1-abs(2*P-1)*1.4)"
_RND = "(sin(X*12.9898+Y*78.233)*43758.5453-floor(sin(X*12.9898+Y*78.233)*43758.5453))"
_RNDT = "(sin(X*12.9898+Y*78.233+floor(P*24)*7.13)*43758.5453-floor(sin(X*12.9898+Y*78.233+floor(P*24)*7.13)*43758.5453))"


def _cor_plano(dy, du, dv):
    return f"if(eq(PLANE,0),{dy},if(eq(PLANE,1),{du},{dv}))"


_CORES_LUZ = {
    "laranja": (70, -35, 45), "vermelho": (40, -20, 60), "dourado": (80, -45, 25), "rosa": (60, 10, 45),
    "azul": (50, 40, -25), "branco": (90, 0, 0), "magenta": (45, 35, 50), "ambar": (75, -40, 35),
}


def _leak(cor="laranja", cy=0.4, larg=0.18, k=1.0):
    dy, du, dv = _CORES_LUZ[cor] if isinstance(cor, str) else cor
    forma = f"exp(-(pow(X/W-(-0.2+1.4*P),2)/{larg * larg:.4f}+pow(Y/H-{cy},2)/0.35))"
    return f"clip({_MIX}+{k:.2f}*{_BUMP}*{forma}*{_cor_plano(dy * 1.6, du * 1.6, dv * 1.6)},0,255)"


def _burn(fx=7, fy=3, cor="laranja", modo="ruido"):
    cor_yuv = _CORES_LUZ[cor] if isinstance(cor, str) else cor
    if modo == "varre":
        n = "(X/W+0.08*sin(Y/H*12)+0.04*sin(Y/H*31))"
    elif modo == "iris":
        n = "(hypot(X-W/2,Y-H/2)/hypot(W/2,H/2)+0.06*sin(atan2(Y-H/2,X-W/2)*7))"
    else:
        n = f"(0.5+0.25*sin(X/W*{fx}+Y/H*{fy})+0.25*sin(Y/H*{fx + 2}-X/W*{fy - 1}))"
    lim = "(P*1.25-0.12)"
    dy, du, dv = cor_yuv
    borda = f"max(0,1-abs({n}-{lim})/0.07)"
    return f"clip(if(lt({n},{lim}),B,A)+{borda}*{_cor_plano(dy * 2.2, du * 2, dv * 2)},0,255)"


def _splash(a=5, b=4, c=9):
    n = f"(0.5+0.3*sin(X/W*{a}+1.3)*cos(Y/H*{b})+0.2*sin(hypot(X-W/2,Y-H/2)/H*{c}))"
    return f"if(lt({n},P*1.35-0.17),B,A)"


def _glitch(bandas=18, fino=False):
    banda = f"floor(Y/(H/{bandas}))" if not fino else f"(floor(Y/(H/{bandas}))+floor(X/(W/6))*31)"
    r = f"(sin({banda}*12.9898)*43758.5453-floor(sin({banda}*12.9898)*43758.5453))"
    desloc = "if(eq(PLANE,0),0,if(eq(PLANE,1),0.12,-0.12))"
    return f"if(lt({r}+{desloc}*{_BUMP},P),B,A)"


def _blocos(cx=16, cy=9):
    cel = f"(floor(X/(W/{cx}))+floor(Y/(H/{cy}))*{cx})"
    r = f"(sin({cel}*12.9898)*43758.5453-floor(sin({cel}*12.9898)*43758.5453))"
    return f"if(lt({r},P),B,A)"


_ESPECIAIS: Dict[str, str] = {
    "glow_fade": f"clip({_MIX}*(1-0.75*{_BUMP})+{_BRANCO}*0.75*{_BUMP},0,255)",
    "glow_sweep": _leak("branco", 0.5, 0.25),
    "grain_fade": f"if(lt({_RND}*0.85+0.08,P),B,A)",
    "respiro": f"if(eq(PLANE,0),{_MIX}*(1-0.4*{_BUMP})+16*0.4*{_BUMP},{_MIX})",
    "flash": f"clip(if(lt(P,0.5),A,B)*(1-max(0,1-abs(P-0.5)*4))+{_BRANCO}*max(0,1-abs(P-0.5)*4),0,255)",
    "punch": f"clip(if(lt(P,0.35),A,B)*(1-max(0,1-abs(P-0.35)*5))+{_BRANCO}*max(0,1-abs(P-0.35)*5),0,255)",
    "rainbow": f"clip({_MIX}+{_BUMP}*{_cor_plano('30', '70*sin(X/W*12.57+P*6)', '70*cos(X/W*12.57+P*6)')},0,255)",
    "prism": f"clip({_MIX}+{_BUMP}*{_cor_plano('40', '80*sin((X+Y)/W*9)', '80*cos((X-Y)/W*9)')},0,255)",
    "dust": f"clip(if(lt({_RND},P),B,A)+{_BUMP}*if(gt({_RNDT},0.985),{_cor_plano(120, 0, 0)},0),0,255)",
    "film_flash": f"clip({_MIX}*(1-0.6*{_BUMP})+{_BUMP}*0.6*if(lt(mod(X,W/7),W/90),{_PRETO},{_BRANCO}),0,255)",
    "scratch": f"clip(if(lt({_RND},P),B,A)+{_BUMP}*if(lt(abs(sin(X*0.37+floor(P*12)*3.1)),0.015),{_cor_plano(110, 0, 0)},0),0,255)",
    "doom": "if(lt(Y,H*(P*1.6-(sin(floor(X/(W/40))*78.233)*43758.5453-floor(sin(floor(X/(W/40))*78.233)*43758.5453))*0.6)),B,A)",
    "grid_flip": _blocos(8, 6),
    "puzzle": "if(lt((floor(X/(W/10))+(sin(floor(Y/(H/6))*45.1)*43758.5453-floor(sin(floor(Y/(H/6))*45.1)*43758.5453))*2)/12,P),B,A)",
    "polka": "if(lt(hypot(mod(X,W/16)-W/32,mod(Y,W/16)-W/32),P*W/16*0.75),B,A)",
    "star": "if(lt(hypot(X-W/2,Y-H/2),P*hypot(W/2,H/2)*1.6*(0.62+0.38*cos(5*atan2(Y-H/2,X-W/2)))),B,A)",
    "heart": "if(lte(pow(pow((X-W/2)/(H*0.4*P*2.4+1),2)+pow(-(Y-H*0.45)/(H*0.4*P*2.4+1),2)-1,3)-pow((X-W/2)/(H*0.4*P*2.4+1),2)*pow(-(Y-H*0.45)/(H*0.4*P*2.4+1),3),0),B,A)",
    "static": f"clip({_MIX}*(1-{_BUMP})+{_BUMP}*if(eq(PLANE,0),{_RNDT}*235,128),0,255)",
    "static_wipe": f"if(lt(X/W,P-0.08),B,if(gt(X/W,P+0.08),A,if(eq(PLANE,0),{_RNDT}*235,128)))",
    "tileswave": "if(lt(floor(X/(W/12))/12+0.12*sin(floor(Y/(H/7))*1.7),P*1.25-0.1),B,A)",
    "colorphase": "if(eq(PLANE,0),A*(1-clip((P-0.3)*2.5,0,1))+B*clip((P-0.3)*2.5,0,1),if(eq(PLANE,1),if(lt(P,0.3),A,B),if(lt(P,0.7),A,B)))",
    "crosshatch": "if(lt(abs(sin((X+Y)*0.05))*abs(sin((X-Y)*0.05)),P*P),B,A)",
    "lummelt": f"if(eq(PLANE,0),if(lt(A,P*255),B,A),{_MIX})",
    "multiply": f"clip({_MIX}*(1-{_BUMP})+if(eq(PLANE,0),A*B/235,{_MIX})*{_BUMP},0,255)",
    "flicker": "if(lt(sin(floor(P*20)*91.3)*437.5-floor(sin(floor(P*20)*91.3)*437.5),P),B,A)",
    "glitch": _glitch(18), "glitch2": _glitch(40, True), "blocks": _blocos(16, 9),
}
for _n, (_c, _cy, _l) in enumerate([("laranja", 0.4, 0.18), ("vermelho", 0.6, 0.22), ("dourado", 0.3, 0.16), ("rosa", 0.5, 0.25),
                                    ("ambar", 0.7, 0.2), ("magenta", 0.35, 0.2), ("azul", 0.5, 0.22), ("branco", 0.45, 0.3)], start=1):
    _ESPECIAIS[f"leak{_n}"] = _leak(_c, _cy, _l)
for _n, (_fx, _fy, _c, _m) in enumerate([(7, 3, "laranja", "ruido"), (11, 5, "vermelho", "ruido"), (5, 8, "ambar", "ruido"),
                                         (9, 2, "dourado", "ruido"), (0, 0, "laranja", "varre"), (0, 0, "vermelho", "iris"),
                                         (13, 7, "laranja", "ruido"), (6, 11, "branco", "ruido"), (8, 4, "ambar", "varre")], start=1):
    _ESPECIAIS[f"burn{_n}"] = _burn(_fx, _fy, _c, _m)
for _n, (_a, _b, _c) in enumerate([(5, 4, 9), (8, 3, 6), (3, 7, 12), (11, 5, 4), (6, 9, 15)], start=1):
    _ESPECIAIS[f"splash{_n}"] = _splash(_a, _b, _c)

# id do DarkPlanner -> xfade nativo (nome), transição nossa, ou "@especial"
_MAPA_TR = """
none:none fade:fade slide_left:slideleft slide_right:slideright slide_up:slideup slide_down:slidedown
wipe_left:wipeleft wipe_right:wiperight wipe_up:wipeup wipe_down:wipedown wipe_diag_tlbr:diagbr wipe_diag_trbl:diagbl
flip:squeezeh clock_wipe:radial iris:circleopen dissolve:dissolve film_burn:@burn1 film_roll:slideup linear_blur:hblur
zoom_in_out:zoomin book_flip:coverleft camera_shutter:dp_shutter camera_flash:@flash camera_focus:distance
film_fire_sweep:@burn5 film_burn_aperture:@burn6
gl_fade_escuro:fadeblack gl_fade_claro:fadewhite gl_fade_suave:fadeslow gl_fade_grao:@grain_fade gl_fade_brilho:@glow_fade
cb_sobe:smoothup cb_desce:smoothdown cb_esquerda:smoothleft cb_direita:smoothright cb_zoom:zoomin cb_foco:distance
cb_respiro:@respiro cb_mergulho:circleclose gl_woosh:smoothleft gl_brilho:@glow_fade gl_brilho2:@glow_sweep
ft_prisma:@prism ft_fogo:@burn2 ft_filmburn2:@burn3 ft_filmburn4:@burn4 ft_filmburn5:@burn5 ft_filmburn6:@burn6
ft_filmburn7:@burn7 ft_filmburn9:@burn9 ft_arcoiris:@rainbow ft_dourado:@leak3 ft_poeira:@dust
ft_pk_leak1:@leak1 ft_pk_leak2:@leak2 ft_pk_leak3:@leak3 ft_pk_leak4:@leak4 ft_pk_leak5:@leak5 ft_pk_leak6:@leak6
ft_pk_burn1:@burn1 ft_pk_burn2:@burn2 ft_pk_burn3:@burn3 ft_pk_burn4:@burn4 ft_pk_glitch:@glitch ft_pk_film:@film_flash
ft_pk2_leak1:@leak7 ft_pk2_leak2:@leak8 ft_pk2_leak3:@leak2 ft_pk2_leak4:@leak4 ft_pk2_leak5:@leak5 ft_pk2_leak6:@leak6
ft_pk2_leak7:@leak1 ft_pk2_burn1:@burn7 ft_pk2_burn2:@burn8 ft_pk2_burn3:@burn9 ft_pk2_riscado:@scratch
ft_pk2_suave:@leak8 ft_pk2_glitch:@glitch2 ft_splash_1:@splash1 ft_splash_2:@splash2 ft_splash_3:@splash3
ft_splash_4:@splash4 ft_splash_5:@splash5
gl_arcoiris:@rainbow gl_kaleido:pinwheel gl_pull_up:coverup gl_pull_down:coverdown gl_pull_left:coverleft
gl_pull_right:coverright gl_mirror_v:vertopen gl_flash:@flash gl_punch:@punch gl_spin:radial gl_circle:circleopen
gl_crosswarp:smoothright gl_radial:radial gl_doorway:horzopen gl_zoom_cross:zoomin gl_ripple:wave_wipe
gl_pixel_cross:pixelize gl_dreamy:@glow_fade gl_windowslice:hlslice gl_pinwheel:pinwheel gl_squeeze:squeezev gl_glitch:@glitch
gl_oss_advancedmosaic:pixelize gl_oss_blockdissolve:@blocks gl_oss_bounce:slidedown gl_oss_bowtiehorizontal:horzopen
gl_oss_bowtievertical:vertopen gl_oss_bowtiewithparameter:horzclose gl_oss_box:rectcrop gl_oss_butterflywavescrawler:wave_wipe
gl_oss_circlecrop:circlecrop gl_oss_colourdistance:distance gl_oss_crazyparametricfun:pinwheel gl_oss_defocusblur:hblur
gl_oss_directionalscaled:smoothleft gl_oss_doomscreentransition:@doom gl_oss_dreamyzoom:zoomin gl_oss_dropzoneflicker:@flicker
gl_oss_edgetransition:distance gl_oss_fold:squeezeh gl_oss_glitchdisplace:@glitch gl_oss_glitchmemories:@glitch2
gl_oss_gridflip:@grid_flip gl_oss_hsvfade:fade gl_oss_horizontalclose:horzclose gl_oss_horizontalopen:horzopen
gl_oss_leftright:wipeleft gl_oss_mosaic:@blocks gl_oss_overexposure:@glow_fade gl_oss_polkadotscurtain:@polka
gl_oss_puzzleright:@puzzle gl_oss_radial:radial gl_oss_rectangle:rectcrop gl_oss_rectanglecrop:rectcrop
gl_oss_revolveleft:coverleft gl_oss_rolls:slideright gl_oss_rotatescalevanish:zoomin gl_oss_simplezoom:zoomin
gl_oss_simplezoomout:fadeslow gl_oss_slides:slideleft gl_oss_starwipe:@star gl_oss_staticfade:@static
gl_oss_stripdatamoshglitch:@glitch2 gl_oss_swirl:pinwheel gl_oss_tvstatic:@static gl_oss_tileswave:@tileswave
gl_oss_topbottom:wipedown gl_oss_verticalclose:vertclose gl_oss_verticalopen:vertopen gl_oss_waterdrop:circleopen
gl_oss_zoomincircles:circleopen gl_oss_zoomleftwipe:smoothleft gl_oss_zoomrigthwipe:smoothright gl_oss_burn0:@burn1
gl_oss_cannabisleaf:diamond_iris gl_oss_chessboard:checkerboard gl_oss_colorphase:@colorphase gl_oss_coordfromin:zoomin
gl_oss_crosshatch:@crosshatch gl_oss_cube:slideleft gl_oss_directionaleasing:smoothleft gl_oss_directionalwarp:smoothright
gl_oss_dissolve:dissolve gl_oss_fadecolor:fadeblack gl_oss_fadegrayscale:fadegrays gl_oss_flyeye:pixelize
gl_oss_fragment:@blocks gl_oss_heart:@heart gl_oss_hexagonalize:pixelize gl_oss_luminancemelt:@lummelt gl_oss_morph:dissolve
gl_oss_mosaictransition:@grid_flip gl_oss_multiplyblend:@multiply gl_oss_oldtvlostsignal:@static gl_oss_parametricglitch:@glitch
gl_oss_perlin:noise_dissolve gl_oss_polarfunction:pinwheel gl_oss_powerkaleido:pinwheel gl_oss_randomnoisex:noise_dissolve
gl_oss_randomsquares:@blocks gl_oss_rotatetransition:radial gl_oss_rotatescalefade:zoomin gl_oss_scalein:zoomin
gl_oss_splitslideinhorizontal:horzclose gl_oss_splitslideinouthorizontal:horzopen gl_oss_splitslideinoutvertical:vertopen
gl_oss_splitslideinvertical:vertclose gl_oss_splitslideouthorizontal:horzopen gl_oss_splitslideoutvertical:vertopen
gl_oss_squeeze:squeezev gl_oss_staticwipe:@static_wipe gl_oss_swap:slideright gl_oss_tangentmotionblur:hlwind
gl_oss_undulatingburnout:@burn7 gl_oss_wind:hlwind gl_oss_windowblinds:blinds_h gl_oss_xaxistranslation:slideleft
gl_oss_zoominout:zoomin
"""
MAPA_TRANSICOES: Dict[str, str] = dict(par.split(":", 1) for par in _MAPA_TR.split())

_FAM_EMOJI = {"forma": "🔷", "luz": "💡", "varredura": "🧹", "fade": "🌗", "impacto": "💥", "glitch": "📺",
              "combo": "🎬", "splash": "💦", "corte": "✂️"}
_ROT_TR = {
    "slide_left": "Desliza ←", "slide_right": "Desliza →", "slide_up": "Desliza ↑", "slide_down": "Desliza ↓",
    "wipe_left": "Varre ←", "wipe_right": "Varre →", "wipe_up": "Varre ↑", "wipe_down": "Varre ↓",
    "wipe_diag_tlbr": "Varre diagonal ↘", "wipe_diag_trbl": "Varre diagonal ↙", "flip": "Virada",
    "clock_wipe": "Relógio", "iris": "Íris", "film_burn": "Filme queimando", "film_roll": "Rolo de filme",
    "linear_blur": "Desfoque linear", "zoom_in_out": "Zoom in/out", "book_flip": "Página de livro",
    "camera_shutter": "Obturador", "camera_flash": "Flash de câmera", "camera_focus": "Foco de câmera",
    "film_fire_sweep": "Fogo varrendo", "film_burn_aperture": "Queima em íris",
    "gl_fade_escuro": "Fade escuro", "gl_fade_claro": "Fade claro", "gl_fade_suave": "Fade suave",
    "gl_fade_grao": "Fade com grão", "gl_fade_brilho": "Fade com brilho", "cb_sobe": "Câmera sobe",
    "cb_desce": "Câmera desce", "cb_esquerda": "Câmera ←", "cb_direita": "Câmera →", "cb_zoom": "Câmera zoom",
    "cb_foco": "Câmera foco", "cb_respiro": "Câmera respiro", "cb_mergulho": "Câmera mergulho",
}


def _rotulo_tr(tid: str, familia: Optional[str]) -> str:
    base = _ROT_TR.get(tid)
    if not base:
        if tid.startswith("ft_pk2_"):
            base = "Película II · " + _humano(tid)
        elif tid.startswith("ft_pk_"):
            base = "Película · " + _humano(tid)
        elif tid.startswith("ft_"):
            base = "Película · " + _humano(tid)
        elif tid.startswith("gl_oss_"):
            base = "GL · " + _humano(tid)
        else:
            base = _humano(tid)
    return f"{_FAM_EMOJI.get(familia or '', '🎞️')} DP {base}"


def transicoes() -> List[Dict[str, Any]]:
    out = []
    for t in _catalogo("transitions"):
        tid = t["id"]
        if tid == "none":
            continue
        out.append({"id": "dp:" + tid, "dp_id": tid, "rotulo": _rotulo_tr(tid, t.get("familia")), "familia": t.get("familia"),
                    "int": t.get("int"), "energia": t.get("energia"), "ritmo": t.get("ritmo")})
    return out


def valor_transicao(dp_id: str) -> str:
    """id do catálogo do DarkPlanner -> valor de transição usado no site."""
    if dp_id == "none" or dp_id.startswith("dp:"):
        return dp_id
    if dp_id in MAPA_TRANSICOES:
        return "dp:" + dp_id
    return dp_id  # transição do próprio site (fade, blinds_h, dp_shutter…)


_LEAK_PARAMS = {1: (0.4, 0.18), 2: (0.6, 0.22), 3: (0.3, 0.16), 4: (0.5, 0.25), 5: (0.7, 0.2), 6: (0.35, 0.2), 7: (0.5, 0.22), 8: (0.45, 0.3)}
_BURN_PARAMS = {1: (7, 3, "ruido"), 2: (11, 5, "ruido"), 3: (5, 8, "ruido"), 4: (9, 2, "ruido"), 5: (0, 0, "varre"), 6: (0, 0, "iris"),
                7: (13, 7, "ruido"), 8: (6, 11, "ruido"), 9: (8, 4, "varre")}


def _com_paleta(chave: str, paleta: Optional[Dict[str, Any]]) -> Optional[str]:
    """Transições de LUZ (leak, burn, brilho) tingidas com a paleta do projeto."""
    import dp_cores
    if not dp_cores.vale_para(paleta, "transicoes"):
        return None
    pal = dp_cores.normalizar(paleta)
    m = re.fullmatch(r"(leak|burn)(\d)", chave)
    if m:
        n = int(m.group(2))
        cor = pal["primaria"] if n % 2 else pal["secundaria"]
        if dp_cores.neutra(cor):
            return None
        d = dp_cores.deltas_yuv(cor, 1.0 if m.group(1) == "leak" else 0.8)
        d = (d[0] / 1.6, d[1] / 1.6, d[2] / 1.6) if m.group(1) == "leak" else (d[0] / 2.2, d[1] / 2, d[2] / 2)
        if m.group(1) == "leak":
            cy, larg = _LEAK_PARAMS.get(n, (0.4, 0.2))
            return _leak(d, cy, larg)
        fx, fy, modo = _BURN_PARAMS.get(n, (7, 3, "ruido"))
        return _burn(fx, fy, d, modo)
    if chave == "glow_sweep" and not dp_cores.neutra(pal["primaria"]):
        d = dp_cores.deltas_yuv(pal["primaria"])
        return _leak((d[0] / 1.6, d[1] / 1.6, d[2] / 1.6), 0.5, 0.25)
    return None


def resolver_transicao(tipo: str, paleta: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """("nativa", nome_xfade) | ("nossa", chave em TRANSICOES_CUSTOMIZADAS) | ("expr", expressão com P 0→1)."""
    if tipo.startswith("dp:"):
        alvo = MAPA_TRANSICOES.get(tipo[3:], "fade")
        if alvo.startswith("@"):
            return "expr", (_com_paleta(alvo[1:], paleta) or _ESPECIAIS[alvo[1:]])
        tipo = alvo
    return ("nossa", tipo) if _e_nossa(tipo) else ("nativa", tipo)


def _e_nossa(tipo: str) -> bool:
    try:
        from video_assembler import TRANSICOES_CUSTOMIZADAS
    except Exception:  # noqa: BLE001
        return False
    return tipo in TRANSICOES_CUSTOMIZADAS




def rotulos_transicoes() -> List[Tuple[str, str]]:
    return [(t["id"], t["rotulo"]) for t in transicoes()]


# =============================================================== pós-processamento de um trecho
def _encadear(etapas: List[str]) -> List[str]:
    """As etapas usam o rótulo genérico [base]: no FIM da etapa é a saída
    (ganha um rótulo novo), em qualquer outro lugar é a entrada (o rótulo
    atual). Assim dá pra empilhar atmosfera + gesto + flash sem conflito."""
    final, atual, n = [], None, 0
    for etapa in etapas:
        sai = etapa.endswith("[base]")
        corpo = etapa[: -len("[base]")] if sai else etapa
        if atual is not None:
            corpo = corpo.replace("[base]", f"[{atual}]")
        if sai:
            n += 1
            atual = f"b{n}"
            corpo += f"[{atual}]"
        final.append(corpo)
    return final


def pos_processar_clipe(entrada_path: str, saida_path: str, dur: float, W: int, H: int, pasta: str,
                        efeito: Optional[str] = None, entrada: Optional[str] = None, saida: Optional[str] = None,
                        run=None, fundo_entrada: Optional[str] = None, fundo_saida: Optional[str] = None) -> bool:
    """Aplica atmosfera + entrada/saída num clipe já normalizado. Devolve
    False se não havia nada a fazer (clipe intacto).

    fundo_entrada / fundo_saida: imagem que fica ATRÁS do clipe enquanto ele
    entra / sai — o último quadro da cena anterior e o primeiro da seguinte.
    Sem isso o gesto acontecia sobre PRETO e, num corte seco, cada emenda
    piscava preto por alguns quadros."""
    import subprocess
    args = ["-i", entrada_path]
    grafo = ["[0:v]setpts=PTS-STARTPTS,format=yuv420p[base]"]
    idx = 1
    if efeito and efeito != "none" and not efeito_e_movimento(efeito):
        ent, filt = atmosfera(efeito, W, H, dur, pasta)
        if ent:
            args += ent
        for f in filt:
            grafo.append(f.replace("{i}", str(idx)))
        idx += sum(1 for a in (ent or []) if a == "-i")
    gest = cadeia_gesto(entrada, saida, dur, W, H)
    if gest:
        fundos = []
        for img, tipo, gid in ((fundo_entrada, "in", entrada), (fundo_saida, "out", saida)):
            if img and gid and gid != "none" and os.path.exists(img):
                args += ["-loop", "1", "-t", f"{dur + 0.2:.3f}", "-i", img]
                d = _dur_gesto(gid, dur)
                janela = f"lt(t,{d + 0.05:.3f})" if tipo == "in" else f"gt(t,{dur - d - 0.05:.3f})"
                fundos.append((idx, janela))
                idx += 1
        if fundos:
            # o fundo preto do gesto vira: quadro vizinho na janela do gesto
            k = next(n for n, linha in enumerate(gest) if linha.endswith("[gpreto]"))
            linhas = [gest[k].replace("[gpreto]", "[gpreto0]")]
            atual = "[gpreto0]"
            for n, (ii, janela) in enumerate(fundos):
                linhas.append(f"[{ii}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,format=yuv420p[gfd{n}]")
                prox = "[gpreto]" if n == len(fundos) - 1 else f"[gpreto{n + 1}]"
                linhas.append(f"{atual}[gfd{n}]overlay=0:0:enable='{janela}':shortest=1{prox}")
                atual = prox
            gest = gest[:k] + linhas + gest[k + 1:]
    grafo += gest
    if len(grafo) == 1:
        return False
    grafo.append("[base]format=yuv420p[vout]")
    final = _encadear(grafo)
    script = os.path.join(pasta, f"_pos_{os.getpid()}_{abs(hash(saida_path)) % 99999}.txt")
    os.makedirs(pasta, exist_ok=True)
    with open(script, "w", encoding="utf-8") as f:
        f.write(";\n".join(final))
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args + [
        "-filter_complex_script", script, "-map", "[vout]", "-t", f"{dur:.3f}", "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an", saida_path,
    ]
    try:
        if run:
            run(cmd)
        else:
            import qualidade_export
            cmd_cpu = qualidade_export._ajustar_cpu(cmd)
            cmd = qualidade_export.ajustar(cmd)
            r = qualidade_export.executar(cmd, timeout=1800, _original=cmd_cpu)
            if r.returncode != 0 and "filter_complex_script" in r.stderr and ("nrecognized" in r.stderr or "not found" in r.stderr):
                k = cmd.index("-filter_complex_script")
                r = subprocess.run(cmd[:k] + ["-/filter_complex"] + cmd[k + 1:], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip()[-800:])
    finally:
        try:
            os.remove(script)
        except OSError:
            pass
    return True
