"""
Miniaturas e prévias das galerias do Estúdio (como na biblioteca do DarkPlanner):

  assets/darkplanner/galeria/destaques/<id>.jpg   207 destaques com o texto de exemplo
  assets/darkplanner/galeria/filtros/<id>.jpg     74 filtros sobre a mesma foto
  assets/darkplanner/galeria/animacoes/<id>.mp4   37 entradas/saídas + 12 movimentos de câmera (+ .jpg)
  assets/darkplanner/galeria/overlays/<id>.mp4    16 overlays de atmosfera (+ .jpg)

Geradas uma vez (`python dp_galeria.py`) e enviadas junto com o site; a prévia
animada de um destaque é gerada na hora que a pessoa passa o mouse e fica guardada.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional

import dp_destaques
import dp_visual

_AQUI = os.path.dirname(os.path.abspath(__file__))
GALERIA_DIR = os.path.join(_AQUI, "assets", "darkplanner", "galeria")
W, H = 480, 270


def _ff(args: List[str]) -> None:
    r = subprocess.run(["ffmpeg", "-v", "error", "-y"] + args, capture_output=True, text=True, timeout=1800)
    if r.returncode:
        raise RuntimeError(r.stderr[-500:])


def foto_exemplo(destino: Optional[str] = None) -> str:
    """Uma 'foto' colorida (céu, sol, montanhas, água, pessoa) pra mostrar filtros e efeitos."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    destino = destino or os.path.join(GALERIA_DIR, "foto_exemplo.jpg")
    if os.path.exists(destino):
        return destino
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    w, h = 960, 540
    yy = np.linspace(0, 1, h)[:, None]
    ceu = np.dstack([40 + 200 * yy ** 1.2, 70 + 120 * yy, 140 - 40 * yy]) * np.ones((1, w, 1))
    im = Image.fromarray(np.clip(ceu, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    d.ellipse([600, 170, 720, 290], fill=(255, 214, 140))
    d.polygon([(0, 360), (180, 220), (330, 330), (480, 200), (700, 340), (960, 250), (960, 540), (0, 540)], fill=(46, 70, 72))
    d.polygon([(0, 420), (260, 330), (520, 410), (800, 320), (960, 380), (960, 540), (0, 540)], fill=(30, 48, 44))
    d.rectangle([0, 440, w, h], fill=(40, 90, 120))
    for k in range(18):
        d.line([0, 445 + k * 5, w, 445 + k * 5], fill=(70 + k * 3, 130 + k * 2, 160), width=1)
    d.ellipse([196, 300, 236, 340], fill=(230, 180, 150))
    d.polygon([(188, 340), (244, 340), (256, 440), (176, 440)], fill=(190, 40, 50))
    im = im.filter(ImageFilter.GaussianBlur(0.8))
    ruido = (np.random.default_rng(3).normal(0, 6, (h, w, 1))).astype(np.int16)
    arr = np.clip(np.array(im).astype(np.int16) + ruido, 0, 255).astype(np.uint8)
    Image.fromarray(arr).save(destino, quality=92)
    return destino


def gerar_destaques(ids: Optional[List[str]] = None) -> int:
    """Todos os destaques num passe só do ffmpeg, um frame de cada (já assentado)."""
    pasta = os.path.join(GALERIA_DIR, "destaques")
    os.makedirs(pasta, exist_ok=True)
    ids = ids or list(dp_destaques.catalogo())
    tmp = os.path.join(pasta, "_trab")
    os.makedirs(tmp, exist_ok=True)
    passo = 2.0
    base = os.path.join(tmp, "base.mp4")
    _ff(["-f", "lavfi", "-i", f"color=c=0x17181d:s={W}x{H}:r=10:d={passo * len(ids) + 0.5:.2f}", "-vf", "vignette=angle=PI/3",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", base])
    ds = []
    for k, eid in enumerate(ids):
        h = dp_destaques.estilo(eid) or {}
        campos = {c["id"]: "REF" for c in (h.get("texto") or {}).get("campos", []) if not c.get("principal") and c.get("required")}
        ds.append({"estilo": eid, "start": k * passo + 0.05, "end": k * passo + passo - 0.05, "texto": h.get("amostra") or h.get("label"), "campos": campos})
    todas = os.path.join(tmp, "todas.mp4")
    dp_destaques.aplicar_destaques(base, todas, ds, W, H, os.path.join(tmp, "w"))
    feitas = 0
    for k, eid in enumerate(ids):
        try:
            _ff(["-ss", f"{k * passo + 1.4:.2f}", "-i", todas, "-frames:v", "1", "-q:v", "4", os.path.join(pasta, f"{eid}.jpg")])
            feitas += 1
        except RuntimeError:
            pass
    shutil.rmtree(tmp, ignore_errors=True)
    return feitas


def gerar_filtros(so: Optional[List[str]] = None) -> int:
    pasta = os.path.join(GALERIA_DIR, "filtros")
    os.makedirs(pasta, exist_ok=True)
    foto = foto_exemplo()
    feitas = 0
    for f in dp_visual.filtros():
        if so is not None and f["id"] not in so:
            continue
        vf = f"scale={W}:{H}" + ("," + f["cadeia"] if f["cadeia"] else "")
        _ff(["-i", foto, "-vf", vf, "-frames:v", "1", "-q:v", "4", os.path.join(pasta, f"{f['id']}.jpg")])
        feitas += 1
    return feitas


def _clip_exemplo(pasta: str, dur: float = 2.2) -> str:
    destino = os.path.join(pasta, f"_base_{dur:.1f}.mp4")
    if not os.path.exists(destino):
        _ff(["-loop", "1", "-i", foto_exemplo(), "-t", f"{dur:.2f}", "-vf", f"scale={W * 2}:{H * 2},zoompan=z='1.05+0.0008*on':d={int(dur * 30)}:s={W}x{H}:fps=30",
             "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", destino])
    return destino


def gerar_animacoes(so: Optional[List[str]] = None) -> int:
    """Entradas (o gesto no começo) e movimentos de câmera — clipes curtos em loop."""
    import video_assembler as va
    pasta = os.path.join(GALERIA_DIR, "animacoes")
    os.makedirs(pasta, exist_ok=True)
    base = _clip_exemplo(pasta, 1.8)
    feitas = 0
    for g in dp_visual.entradas():
        if g["id"] == "none" or (so is not None and f"entrada_{g['id']}" not in so):
            continue
        out = os.path.join(pasta, f"entrada_{g['id']}.mp4")
        # clipe começa com 0,3s de preto pra dar pra ver o gesto entrando em loop
        dp_visual.pos_processar_clipe(base, out + ".tmp.mp4", 1.8, W, H, os.path.join(pasta, "_w"), entrada=g["id"])
        _ff(["-i", out + ".tmp.mp4", "-vf", "tpad=start_duration=0.3:start_mode=add:color=black", "-c:v", "libx264", "-preset", "veryfast",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", out])
        os.remove(out + ".tmp.mp4")
        _ff(["-ss", "0.55", "-i", out, "-frames:v", "1", "-q:v", "4", out[:-4] + ".jpg"])
        feitas += 1
    for eid, modo in dp_visual.EFEITO_PARA_ZOOM.items():
        if so is not None and f"camera_{eid}" not in so:
            continue
        out = os.path.join(pasta, f"camera_{eid}.mp4")
        va._render_image_with_ken_burns(foto_exemplo(), 2.0, out, W, H, zoom_direction=modo)
        _ff(["-ss", "1.0", "-i", out, "-frames:v", "1", "-q:v", "4", out[:-4] + ".jpg"])
        feitas += 1
    shutil.rmtree(os.path.join(pasta, "_w"), ignore_errors=True)
    for f in os.listdir(pasta):
        if f.startswith("_base_"):
            os.remove(os.path.join(pasta, f))
    return feitas


def gerar_overlays(so: Optional[List[str]] = None) -> int:
    pasta = os.path.join(GALERIA_DIR, "overlays")
    os.makedirs(pasta, exist_ok=True)
    base = _clip_exemplo(pasta, 2.2)
    feitas = 0
    for e in dp_visual.efeitos():
        if e["id"] == "none" or dp_visual.efeito_e_movimento(e["id"]) or (so is not None and e["id"] not in so):
            continue
        out = os.path.join(pasta, f"{e['id']}.mp4")
        dp_visual.pos_processar_clipe(base, out, 2.2, W, H, os.path.join(pasta, "_w"), efeito=e["id"])
        _ff(["-ss", "1.1", "-i", out, "-frames:v", "1", "-q:v", "4", out[:-4] + ".jpg"])
        feitas += 1
    shutil.rmtree(os.path.join(pasta, "_w"), ignore_errors=True)
    for f in os.listdir(pasta):
        if f.startswith("_base_"):
            os.remove(os.path.join(pasta, f))
    return feitas


def previa_destaque(eid: str, pasta: str, texto: Optional[str] = None, paleta: Optional[Dict[str, str]] = None) -> str:
    """Clipe curto do destaque animando (gerado na hora e guardado)."""
    h = dp_destaques.estilo(eid)
    if not h:
        raise ValueError(f"Estilo desconhecido: {eid!r}")
    chave = hashlib.md5(f"{eid}|{texto}|{json.dumps(paleta or {}, sort_keys=True)}".encode()).hexdigest()[:10]
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, f"{eid}_{chave}.mp4")
    if os.path.exists(destino):
        return destino
    tmp = destino + "_trab"
    os.makedirs(tmp, exist_ok=True)
    try:
        base = os.path.join(tmp, "base.mp4")
        _ff(["-f", "lavfi", "-i", f"color=c=0x17181d:s={W}x{H}:r=30:d=2.6", "-vf", "vignette=angle=PI/3", "-pix_fmt", "yuv420p",
             "-c:v", "libx264", "-preset", "ultrafast", base])
        d = {"estilo": eid, "start": 0.1, "end": 2.5, "texto": texto or h.get("amostra") or h.get("label"), "campos": {}}
        saida = os.path.join(tmp, "o.mp4")
        dp_destaques.aplicar_destaques(base, saida, [d], W, H, os.path.join(tmp, "w"), paleta=paleta)
        _ff(["-i", saida, "-c", "copy", "-movflags", "+faststart", destino])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return destino


def existe(tipo: str, nome: str) -> bool:
    return os.path.exists(os.path.join(GALERIA_DIR, tipo, nome))


if __name__ == "__main__":
    o_que = sys.argv[1:] or ["filtros", "overlays", "animacoes", "destaques", "editorial"]
    import dp_editorial
    for k in o_que:
        print(k, {"filtros": gerar_filtros, "overlays": gerar_overlays, "animacoes": gerar_animacoes, "destaques": gerar_destaques,
                  "editorial": lambda: dp_editorial.gerar_miniaturas(os.path.join(GALERIA_DIR, "editorial"), foto_exemplo())}[k](), flush=True)
