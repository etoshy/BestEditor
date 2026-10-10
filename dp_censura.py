"""
Censura / blur — faixa "Censura" do Estúdio.

Cada item cobre um intervalo de tempo e é de um destes tipos:

  VÍDEO (uma área da tela; aplicada na imagem ANTES dos textos/gráficos,
  então legendas e destaques continuam legíveis por cima):
    blur      desfoque (rosto, placa, documento)
    pixel     mosaico/pixelado
    tarja     tarja sólida (cor escolhida), com um rótulo opcional ("CENSURADO")
  ÁUDIO (o trecho da narração+efeitos; a trilha de fundo continua):
    bip       "piiii" por cima, com a fala silenciada
    mudo      só silencia

Área em frações da tela (x, y = canto superior esquerdo; w, h = tamanho),
forma "retangulo" ou "elipse". Se tiver x2/y2, a área desliza em linha reta
do ponto inicial ao final ao longo do intervalo (acompanhar algo que se mexe
devagar). `tela_toda`: true = a tela inteira (ex.: cena sensível).
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

TIPOS_VIDEO = {"blur": "Desfoque (blur)", "pixel": "Pixelado (mosaico)", "tarja": "Tarja sólida"}
TIPOS_AUDIO = {"bip": "Bip (som de censura)", "mudo": "Silenciar"}
TIPOS = {**TIPOS_VIDEO, **TIPOS_AUDIO}
FORMAS = {"retangulo": "Retângulo", "elipse": "Elipse (rosto)"}
FONTES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts", "dp")


def _num(v: Any, padrao: float, lo: float, hi: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return padrao
    if f != f:  # NaN
        return padrao
    return max(lo, min(hi, f))


def normalizar(lista: Any, duracao: Optional[float] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for k, c in enumerate(lista if isinstance(lista, list) else []):
        if not isinstance(c, dict):
            continue
        tipo = c.get("tipo") if c.get("tipo") in TIPOS else "blur"
        ini = _num(c.get("start"), -1, 0, 1e7)
        fim = _num(c.get("end"), -1, 0, 1e7)
        if ini < 0 or fim <= ini:
            continue
        if duracao:
            fim = min(fim, float(duracao))
            if fim - ini < 0.05:
                continue
        item: Dict[str, Any] = {"id": str(c.get("id") or f"cz{k}")[:16], "tipo": tipo, "start": round(ini, 3), "end": round(fim, 3)}
        if tipo in TIPOS_VIDEO:
            item["tela_toda"] = bool(c.get("tela_toda"))
            w = _num(c.get("w"), 0.25, 0.02, 1.0)
            h = _num(c.get("h"), 0.25, 0.02, 1.0)
            x = _num(c.get("x"), 0.375, 0.0, 1.0 - w)
            y = _num(c.get("y"), 0.3, 0.0, 1.0 - h)
            item.update({"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)})
            if c.get("x2") is not None or c.get("y2") is not None:
                item["x2"] = round(_num(c.get("x2"), x, 0.0, 1.0 - w), 4)
                item["y2"] = round(_num(c.get("y2"), y, 0.0, 1.0 - h), 4)
                if item["x2"] == x and item["y2"] == y:
                    item.pop("x2"), item.pop("y2")
            item["forma"] = c.get("forma") if c.get("forma") in FORMAS else "retangulo"
            item["intensidade"] = int(_num(c.get("intensidade"), 6, 1, 10))
            if tipo == "tarja":
                cor = str(c.get("cor") or "#000000")
                item["cor"] = cor.upper() if re.fullmatch(r"#[0-9a-fA-F]{6}", cor) else "#000000"
                rot = str(c.get("rotulo") or "").strip()[:40]
                if rot:
                    item["rotulo"] = rot
        else:
            item["volume"] = round(_num(c.get("volume"), 0.35, 0.05, 1.0), 2)
            item["freq"] = int(_num(c.get("freq"), 1000, 200, 4000))
        out.append(item)
    out.sort(key=lambda c: c["start"])
    return out


def de_video(itens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [c for c in itens if c.get("tipo") in TIPOS_VIDEO]


def de_audio(itens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [c for c in itens if c.get("tipo") in TIPOS_AUDIO]


# ------------------------------------------------------------------ vídeo
def _caixa(c: Dict[str, Any], W: int, H: int) -> Tuple[int, int, int, int]:
    if c.get("tela_toda"):
        return 0, 0, W, H
    w = max(4, int(round(c["w"] * W)) // 2 * 2)
    h = max(4, int(round(c["h"] * H)) // 2 * 2)
    x = int(round(c["x"] * W))
    y = int(round(c["y"] * H))
    return min(x, W - w), min(y, H - h), w, h


def _expr_pos(c: Dict[str, Any], eixo: str, W: int, H: int, w: int, h: int) -> str:
    """Posição (px) como expressão do tempo — fixa, ou deslizando até x2/y2."""
    total = W if eixo == "x" else H
    tam = w if eixo == "x" else h
    p0 = min(int(round(c[eixo] * total)), total - tam)
    if c.get("tela_toda") or f"{eixo}2" not in c:
        return str(p0)
    p1 = min(int(round(c[f"{eixo}2"] * total)), total - tam)
    if p1 == p0:
        return str(p0)
    d = max(0.05, c["end"] - c["start"])
    return f"{p0}+({p1 - p0})*clip((t-{c['start']:.3f})/{d:.3f}\\,0\\,1)"


def _mascara_elipse(pasta: str, nome: str, w: int, h: int) -> str:
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.new("L", (w, h), 0)
    ImageDraw.Draw(im).ellipse([0, 0, w - 1, h - 1], fill=255)
    im = im.filter(ImageFilter.GaussianBlur(max(1, min(w, h) // 40)))  # borda suave
    caminho = os.path.join(pasta, nome)
    im.save(caminho)
    return caminho


def _png_tarja(pasta: str, nome: str, c: Dict[str, Any], w: int, h: int) -> str:
    from PIL import Image, ImageDraw, ImageFont
    cor = tuple(int(c.get("cor", "#000000")[i:i + 2], 16) for i in (1, 3, 5))
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if c.get("forma") == "elipse":
        d.ellipse([0, 0, w - 1, h - 1], fill=cor + (255,))
    else:
        d.rectangle([0, 0, w - 1, h - 1], fill=cor + (255,))
    rot = c.get("rotulo")
    if rot:
        claro = (0.299 * cor[0] + 0.587 * cor[1] + 0.114 * cor[2]) > 140
        tam = max(10, int(h * 0.42))
        try:
            fonte = ImageFont.truetype(os.path.join(FONTES, "anton-Bold.ttf"), tam)
        except OSError:
            try:
                fonte = ImageFont.truetype(os.path.join(FONTES, "inter-Bold.ttf"), tam)
            except OSError:
                fonte = ImageFont.load_default()
        while tam > 10 and d.textlength(rot, font=fonte) > w * 0.86:
            tam = int(tam * 0.88)
            try:
                fonte = fonte.font_variant(size=tam)
            except Exception:  # noqa: BLE001
                break
        bb = d.textbbox((0, 0), rot, font=fonte)
        d.text(((w - (bb[2] - bb[0])) / 2 - bb[0], (h - (bb[3] - bb[1])) / 2 - bb[1]), rot, font=fonte,
               fill=(20, 20, 20, 255) if claro else (255, 255, 255, 255))
    caminho = os.path.join(pasta, nome)
    im.save(caminho)
    return caminho


def montar_filtro(itens: List[Dict[str, Any]], W: int, H: int, pasta: str, duracao: float) -> Tuple[List[str], str, str]:
    """Devolve (entradas extras do ffmpeg, filter_complex, rótulo da saída)."""
    os.makedirs(pasta, exist_ok=True)
    entradas: List[str] = []
    partes: List[str] = []
    atual = "[0:v]"
    n_in = 1
    for k, c in enumerate(de_video(itens)):
        x, y, w, h = _caixa(c, W, H)
        ex, ey = _expr_pos(c, "x", W, H, w, h), _expr_pos(c, "y", W, H, w, h)
        en = f"between(t\\,{c['start']:.3f}\\,{c['end']:.3f})"
        dur = f"{duracao + 1:.2f}"
        if c["tipo"] == "tarja":
            png = _png_tarja(pasta, f"tarja_{k}.png", c, w, h)
            entradas += ["-loop", "1", "-framerate", "30", "-t", dur, "-i", png]
            partes.append(f"{atual}[{n_in}:v]overlay=x='{ex}':y='{ey}':enable='{en}':eval=frame[cz{k}]")
            n_in += 1
        else:
            ii = c["intensidade"]
            if c["tipo"] == "blur":
                efeito = f"gblur=sigma={4 + ii * 4}:steps=2"
            else:
                bloco = max(4, int(min(w, h) * (0.02 + ii * 0.012)))
                efeito = f"scale={max(1, w // bloco)}:{max(1, h // bloco)}:flags=area,scale={w}:{h}:flags=neighbor"
            partes.append(f"{atual}split=2[czb{k}][czs{k}]")
            partes.append(f"[czs{k}]crop={w}:{h}:x='{ex}':y='{ey}',{efeito},format=yuva420p[czr{k}]")
            fonte = f"[czr{k}]"
            if c.get("forma") == "elipse" and not c.get("tela_toda"):
                m = _mascara_elipse(pasta, f"mask_{k}.png", w, h)
                entradas += ["-loop", "1", "-framerate", "30", "-t", dur, "-i", m]
                partes.append(f"[{n_in}:v]format=gray,scale={w}:{h}[czm{k}]")
                partes.append(f"[czr{k}][czm{k}]alphamerge[cza{k}]")
                fonte = f"[cza{k}]"
                n_in += 1
            partes.append(f"[czb{k}]{fonte}overlay=x='{ex}':y='{ey}':enable='{en}':eval=frame:shortest=1[cz{k}]")
        atual = f"[cz{k}]"
    partes.append(f"{atual}format=yuv420p[czout]")
    return entradas, ";".join(partes), "[czout]"


def aplicar_video(entrada: str, saida: str, itens: List[Dict[str, Any]], W: int, H: int, pasta: str,
                  duracao: float, run=None) -> bool:
    """Aplica as áreas de censura no vídeo (sem áudio). False = nada a fazer."""
    if not de_video(itens):
        return False
    entradas, fc, rot = montar_filtro(itens, W, H, pasta, duracao)
    cmd = ["-i", entrada] + entradas + ["-filter_complex", fc, "-map", rot, "-c:v", "libx264", "-preset", "veryfast",
                                       "-pix_fmt", "yuv420p", "-r", "30", "-an", saida]
    if run:
        run(cmd)
    else:
        r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-800:])
    return True


# ------------------------------------------------------------------ áudio
def _soma(intervalos: List[Dict[str, Any]]) -> str:
    return "+".join(f"between(t\\,{c['start']:.3f}\\,{c['end']:.3f})" for c in intervalos)


def filtro_audio(itens: List[Dict[str, Any]], duracao: float) -> Optional[str]:
    aud = de_audio(itens)
    if not aud:
        return None
    partes = [f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0:enable='{_soma(aud)}'[czmudo]"]
    bips = [c for c in aud if c["tipo"] == "bip"]
    if not bips:
        return partes[0].replace("[czmudo]", "[czaout]")
    for k, c in enumerate(bips):
        dur = max(0.05, c["end"] - c["start"])
        partes.append(f"sine=frequency={c['freq']}:sample_rate=48000:duration={dur:.3f},volume={c['volume'] * 6:.2f},"  # o sine nasce em -18 dB
                      f"afade=t=in:d=0.01,afade=t=out:st={max(0.0, dur - 0.015):.3f}:d=0.015,"
                      f"adelay={int(c['start'] * 1000)}:all=1,aformat=channel_layouts=stereo[czbip{k}]")
    entradas = "[czmudo]" + "".join(f"[czbip{k}]" for k in range(len(bips)))
    partes.append(f"{entradas}amix=inputs={len(bips) + 1}:duration=first:normalize=0[czaout]")
    return ";".join(partes)


def aplicar_audio(entrada: str, saida: str, itens: List[Dict[str, Any]], duracao: float) -> bool:
    fc = filtro_audio(itens, duracao)
    if not fc:
        return False
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", entrada, "-filter_complex", fc,
                        "-map", "[czaout]", "-ar", "48000", "-ac", "2", saida], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])
    return True
