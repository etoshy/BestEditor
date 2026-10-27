"""🧽 v84_240 — Remover fundo: zip → o mesmo zip com PNG transparente; imagem → PNG."""
import io
import json
import zipfile
from urllib.parse import unquote

from PIL import Image, ImageDraw

import remover_fundo as RF


def _fig(fundo, cor=(200, 40, 40), tam=(300, 400), branco_dentro=False):
    im = Image.new("RGB", tam, fundo)
    d = ImageDraw.Draw(im)
    d.ellipse([80, 60, 220, 360], fill=cor)
    if branco_dentro:
        d.ellipse([130, 150, 170, 190], fill=(255, 255, 255))  # o "olho" branco dentro da figura
    return im


def _b(im, fmt="PNG"):
    b = io.BytesIO()
    im.save(b, fmt)
    return b.getvalue()


def test_verde_branco_e_cor_lisa():
    for fundo, modo in (((0, 255, 0), "verde"), ((255, 255, 255), "branco"), ((40, 90, 160), "cor")):
        im = _fig(fundo, branco_dentro=True)
        assert RF.detectar(im) == modo
        out, info = RF.remover(im)
        assert out.mode == "RGBA" and info["modo"] == modo
        assert out.getpixel((5, 5))[3] == 0 and out.getpixel((150, 300))[3] == 255
        assert out.getpixel((150, 170))[3] == 255  # o branco DENTRO da figura fica
    out, _ = RF.remover(_fig((0, 255, 0)), recortar=True, margem=10)
    assert out.size == (140 + 21, 300 + 21) or abs(out.width - 161) <= 4
    out, _ = RF.remover(_fig((0, 255, 0), tam=(1200, 1600)), lado_max=400)
    assert max(out.size) == 400
    # sem verde nenhum no modo verde → avisa
    _o, info = RF.remover(_fig((255, 255, 255)), "verde")
    assert "aviso" in info


def test_zip_volta_igual_so_que_em_png():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("akemi/poses/akemi_feliz.jpg", _b(_fig((0, 255, 0)), "JPEG"))
        z.writestr("akemi/poses/akemi_bravo.png", _b(_fig((0, 255, 0), (40, 40, 200))))
        z.writestr("akemi/ficha.txt", "Akemi")
        z.writestr("__MACOSX/._lixo", b"x")
    dados, rel = RF.processar_zip(buf.getvalue())
    z = zipfile.ZipFile(io.BytesIO(dados))
    assert sorted(z.namelist()) == ["akemi/ficha.txt", "akemi/poses/akemi_bravo.png", "akemi/poses/akemi_feliz.png"]
    assert z.read("akemi/ficha.txt") == b"Akemi" and rel["imagens"] == 2 and rel["copiados"] == 1 and rel["modos"] == {"verde": 2}
    im = Image.open(io.BytesIO(z.read("akemi/poses/akemi_feliz.png")))
    assert im.mode == "RGBA" and im.getpixel((3, 3))[3] == 0
    # mesmo nome com extensões diferentes não se sobrescreve
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z2:
        z2.writestr("a.jpg", _b(_fig((0, 255, 0)), "JPEG"))
        z2.writestr("a.webp", _b(_fig((0, 255, 0)), "WEBP"))
    assert sorted(zipfile.ZipFile(io.BytesIO(RF.processar_zip(buf.getvalue())[0])).namelist()) == ["a.png", "a_2.png"]


def test_rotas():
    import app as A
    c = A.app.test_client()
    assert "Remover fundo" in c.get("/remover-fundo").get_data(as_text=True)
    r = c.post("/remover-fundo/imagens", data={"arquivos": (io.BytesIO(_b(_fig((0, 255, 0)))), "x.png"), "recortar": "1"},
               content_type="multipart/form-data")
    assert r.status_code == 200 and r.mimetype == "image/png" and Image.open(io.BytesIO(r.data)).mode == "RGBA"
    assert json.loads(unquote(r.headers["X-Relatorio"]))["imagens"] == 1
    r = c.post("/remover-fundo/imagens", data={"arquivos": [(io.BytesIO(_b(_fig((0, 255, 0)))), "x.png"), (io.BytesIO(_b(_fig((255, 255, 255)))), "y.jpg")]},
               content_type="multipart/form-data")
    assert r.mimetype == "application/zip" and sorted(zipfile.ZipFile(io.BytesIO(r.data)).namelist()) == ["x.png", "y.png"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("p/a.png", _b(_fig((0, 255, 0))))
    r = c.post("/remover-fundo/zip", data={"arquivo": (io.BytesIO(buf.getvalue()), "poses.zip")}, content_type="multipart/form-data")
    assert r.status_code == 200 and unquote(r.headers["X-Nome"]) == "poses_png.zip"
    assert c.post("/remover-fundo/zip", data={"arquivo": (io.BytesIO(b"nao zip"), "x.zip")}, content_type="multipart/form-data").status_code == 400
