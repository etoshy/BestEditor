"""v84_84 — 🖼 imagem em pé (capa) respeita as bordas pretas/mosaico com câmera suave; 🎬 entradas que mudam o
tamanho (tv_on, zoom_in, stretch…) terminam na imagem INTEIRA (antes o "rotate" travava no tamanho do 1º quadro e a
imagem ficava pequena/uma linha o trecho todo)."""
import re
import subprocess

import pytest
from PIL import Image, ImageDraw

import dp_visual as dv
import video_assembler as va


def _caixa(video, t):
    r = subprocess.run(["ffmpeg", "-ss", str(t), "-i", video, "-frames:v", "1", "-vf", "cropdetect=24:2:0", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.findall(r"crop=(-?\d+):(-?\d+):(-?\d+):(-?\d+)", r.stderr)
    return tuple(int(x) for x in m[-1]) if m else None


def _quadro(video, t, destino):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", video, "-frames:v", "1", destino], check=True)
    return Image.open(destino).convert("RGB")


@pytest.fixture
def capa(tmp_path):
    p = tmp_path / "capa.png"
    im = Image.new("RGB", (600, 900), (90, 60, 140))
    ImageDraw.Draw(im).rectangle((100, 300, 500, 600), fill=(240, 200, 120))
    im.save(p)
    return str(p)


def test_capa_em_pe_aparece_inteira_nas_bordas_pretas_e_mosaico(capa, tmp_path):
    for modo in ("black", "mosaic"):
        out = str(tmp_path / f"{modo}.mp4")
        va._render_image_with_ken_burns(capa, 2.0, out, 640, 360, zoom_direction="in", aspect_fill=modo)
        f = _quadro(out, 1.9, str(tmp_path / f"{modo}.png"))
        topo, base = f.getpixel((320, 8)), f.getpixel((320, 352))
        assert abs(topo[0] - 90) < 30 and abs(topo[2] - 140) < 30, (modo, topo)   # a capa inteira cabe (o roxo de cima aparece)
        assert abs(base[2] - 140) < 30, (modo, base)
        lado = f.getpixel((15, 180))
        if modo == "black":
            assert max(lado) < 25
        else:
            assert max(lado) > 40  # mosaico desfocado, não preto
    out = str(tmp_path / "zoom.mp4")
    va._render_image_with_ken_burns(capa, 2.0, out, 640, 360, zoom_direction="in", aspect_fill="zoom")
    f = _quadro(out, 1.9, str(tmp_path / "zoom.png"))
    assert f.getpixel((320, 180))[0] > 200  # "zoom" continua preenchendo (corta)


def test_foto_deitada_continua_preenchendo(tmp_path):
    p = str(tmp_path / "deitada.png")
    Image.new("RGB", (1600, 900), (10, 120, 30)).save(p)
    assert va._compor_imagem_nas_bordas(p, 1280, 720, "mosaic") is None
    assert va._compor_imagem_nas_bordas(p, 1280, 720, "zoom") is None


@pytest.mark.parametrize("gesto", ["tv_on", "zoom_in", "stretch", "spin", "pop"])
def test_entrada_termina_com_a_imagem_inteira(capa, tmp_path, gesto):
    clipe = str(tmp_path / "c.mp4")
    va._render_image_with_ken_burns(capa, 2.5, clipe, 640, 360, zoom_direction="static", aspect_fill="zoom")
    out = str(tmp_path / f"{gesto}.mp4")
    assert dv.pos_processar_clipe(clipe, out, 2.5, 640, 360, str(tmp_path), entrada=gesto)
    w, h, x, y = _caixa(out, 1.6)
    assert w >= 636 and h >= 356, (gesto, w, h)  # a imagem inteira (±2 px de arredondamento), não um pedaço/linha
