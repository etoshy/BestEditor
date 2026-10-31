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


def test_buscar_no_navegador_envia_o_arquivo_e_clica_em_exatas(tmp_path, monkeypatch):
    """O navegador do site abre a página do buscador, acha o campo de upload (clicando na câmera) e clica em 'Correspondências exatas'."""
    import time as _t
    monkeypatch.setenv("FONTES_VIDEO_DIR", str(tmp_path / "fv"))
    monkeypatch.setenv("FONTE_NAVEGADOR_OCULTO", "1")
    pagina = tmp_path / "lens.html"
    pagina.write_text("""<!doctype html><html><body>
<div role="button" aria-label="Pesquisar por imagem" onclick="document.getElementById('up').style.display='block'">cam</div>
<div id="up" style="display:none"><input type="file" name="encoded_image" id="f"></div>
<script>document.getElementById('f').addEventListener('change', e => { const n = e.target.files[0]; document.title = 'enviado:' + n.name;
setTimeout(() => { const a = document.createElement('a'); a.href = '#x'; a.textContent = 'Correspondências exatas';
a.onclick = () => { document.title = 'EXATAS:' + n.name; }; document.body.appendChild(a); }, 800); });</script></body></html>""", encoding="utf-8")
    monkeypatch.setitem(AF.MOTORES, "lens", dict(AF.MOTORES["lens"], url=pagina.as_uri()))
    b = str(tmp_path)
    p = AF.novo(b, "", "t")
    _video(os.path.join(AF.pasta(b, p["id"]), "video.mp4"))
    p["video"] = "video.mp4"
    AF.salvar(b, p)
    p = AF.analisar(b, p["id"])
    bid = AF.buscar_no_navegador(b, p["id"], p["cenas"][0]["prints"][0]["arq"], "lens", inverter=True)
    for _ in range(150):
        if AF._BUSCAS[bid]["estado"] in ("ok", "erro"):
            break
        _t.sleep(0.2)
    assert AF._BUSCAS[bid]["estado"] == "ok", AF._BUSCAS[bid]
    assert "Correspondências exatas" in AF._BUSCAS[bid]["msg"]
