"""🔎 v84_289 — achar a fonte: trocas de cena, prints, inverter/recortar, marcar a fonte."""
import io
import os
import subprocess

import pytest

import achar_fonte as AF


def _video(cam):
    # 3 cenas bem diferentes (3 s cada) + uma piscada preta de transição
    f = ("[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc=s=640x360:r=30:d=3",
                    "-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=0.1",
                    "-f", "lavfi", "-i", "rgbtestsrc=s=640x360:r=30:d=3",
                    "-f", "lavfi", "-i", "smptebars=s=640x360:r=30:d=3",
                    "-filter_complex", f.replace("[3:v]concat=n=4", "[3:v]concat=n=4"), "-map", "[v]", "-t", "9.1", "-pix_fmt", "yuv420p", cam], check=True)


def test_analisar_inverter_marcar(tmp_path, monkeypatch):
    monkeypatch.setenv("FONTES_VIDEO_DIR", str(tmp_path / "fv"))
    b = str(tmp_path)
    p = AF.novo(b, "", "teste")
    _video(os.path.join(AF.pasta(b, p["id"]), "video.mp4"))
    p["video"] = "video.mp4"
    AF.salvar(b, p)
    p = AF.analisar(b, p["id"])
    assert len(p["cenas"]) == 3, [(c["t0"], c["t1"]) for c in p["cenas"]]  # o preto da transição não vira cena
    assert [round(c["t0"]) for c in p["cenas"]] == [0, 3, 6]
    assert all(1 <= len(c["prints"]) <= 2 for c in p["cenas"]) and len(p["cenas"][0]["prints"]) == 2
    arq = p["cenas"][0]["prints"][0]["arq"]
    from PIL import Image
    a = Image.open(io.BytesIO(AF.imagem(b, p["id"], arq)))
    inv = Image.open(io.BytesIO(AF.imagem(b, p["id"], arq, inverter=True)))
    assert a.size == inv.size and a.getpixel((5, 180)) != inv.getpixel((5, 180))
    assert inv.getpixel((5, 180)) == pytest.approx(a.getpixel((a.width - 6, 180)), abs=30)  # espelhou
    meio = Image.open(io.BytesIO(AF.imagem(b, p["id"], arq, recorte="meio")))
    assert meio.size[1] < a.size[1] * 0.7
    c = AF.marcar(b, p["id"], 2, "https://www.pexels.com/video/123", "Pexels")
    assert c["fonte"].startswith("https://www.pexels")
    txt = AF.lista_texto(AF.carregar(b, p["id"]))
    assert "Cena   2  0:03-0:06  https://www.pexels.com/video/123  — Pexels" in txt and "(não achada)" in txt
    p = AF.analisar(b, p["id"])  # refazer mantém a fonte marcada
    assert p["cenas"][1]["fonte"].startswith("https://www.pexels")
    assert AF.listar(b)[0]["achadas"] == 1
