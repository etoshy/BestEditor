"""v84_85 — 🪧 Bordas "Cartão sobre fundo": imagem de outro formato vira cartão (sombra, cantos arredondados) sobre um
fundo em movimento (gerado OU clipe de vídeo); fotos seguidas passam sobre o MESMO fundo; direção "Propaganda"."""
import json
import subprocess

import pytest
from PIL import Image, ImageDraw

import video_assembler as va
from prompt_builder import VideoSegment


def _capa(p, cor=(240, 200, 120)):
    im = Image.new("RGB", (600, 900), (90, 60, 140))
    ImageDraw.Draw(im).rectangle((100, 300, 500, 600), fill=cor)
    im.save(p)
    return str(p)


def _quadro(video, t, destino):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", video, "-frames:v", "1", destino], check=True)
    return Image.open(destino).convert("RGB")


def _audio(tmp_path, seg):
    a = str(tmp_path / "a.wav")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(seg), a], capture_output=True, check=True)
    return a


def test_cartao_sobre_fundo_gerado_na_montagem(tmp_path):
    capas = [_capa(tmp_path / "c1.png"), _capa(tmp_path / "c2.png", (60, 200, 90))]
    deitada = str(tmp_path / "deitada.png")
    Image.new("RGB", (1280, 720), (200, 30, 30)).save(deitada)
    segs = [VideoSegment(start=float(a), end=float(a + 2), provider="pexels", query="x", media_type="image", aspect_fill="cartao",
                         override_source={"kind": "image", "source": "local_file", "value": v})
            for a, v in ((0, capas[0]), (2, capas[1]), (4, deitada))]
    saida = str(tmp_path / "final.mp4")
    va.assemble_video(segs, _audio(tmp_path, 6), saida, work_dir=str(tmp_path / "w"), site_cfg={
        "orientation": "16:9", "export_quality": "480p",
        "cartao_fundo": {"modo": "gerado", "estilo": "cor_gradiente", "cor": "#2E7D32"}})
    f = _quadro(saida, 1.2, str(tmp_path / "f1.png"))
    W, H = f.size
    centro, canto = f.getpixel((W // 2, H // 2)), f.getpixel((8, H // 2))
    assert centro[0] > 200 and centro[1] > 170  # a capa inteira (o miolo amarelo) no centro
    assert canto[1] > canto[0] and canto != (0, 0, 0)  # fundo verde do gradiente, não preto
    deit = _quadro(saida, 5.0, str(tmp_path / "f3.png"))
    assert deit.getpixel((8, H // 2))[0] > 150  # a foto deitada continua ocupando a tela (não vira cartão)


def test_fundo_em_video_baixado_uma_vez_e_cai_pro_gerado_se_falhar(tmp_path):
    bg = str(tmp_path / "bg.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x1565C0:s=640x360:r=30:d=3", "-pix_fmt", "yuv420p", bg], check=True)
    chamadas = []
    f = va.preparar_fundo_cartao({"modo": "video", "busca": "abstract bokeh"}, 640, 360, str(tmp_path / "p"),
                                 lambda q: chamadas.append(q) or bg)
    assert f["tipo"] == "video" and chamadas == ["abstract bokeh"]
    out = str(tmp_path / "c.mp4")
    va._render_imagem_cartao(_capa(tmp_path / "c.png"), 2.0, out, 640, 360, f, t0=7.3)
    q = _quadro(out, 1.5, str(tmp_path / "q.png"))
    assert q.getpixel((5, 180))[2] > 120  # o clipe azul aparece atrás
    ruim = va.preparar_fundo_cartao({"modo": "video", "busca": "x"}, 640, 360, str(tmp_path / "p"), lambda q: None)
    assert ruim["tipo"] == "gerado"


def test_form_do_estudio_valida_e_vai_pra_config_da_montagem(monkeypatch, tmp_path):
    import app as A
    cf = A._cartao_fundo_do_form(json.dumps({"modo": "video", "estilo": "x", "cor": "javascript:", "biblioteca": "ab/../c",
                                             "busca": "  bokeh   lights ", "desfocar": 99, "escurecer": "0.3"}))
    assert cf == {"modo": "video", "estilo": "cor_gradiente", "cor": "", "biblioteca": "abc", "busca": "bokeh lights",
                  "desfocar": 30.0, "escurecer": 0.3}
    assert A._cartao_fundo_do_form("nada") is None
    vid = tmp_path / "meu_fundo.mp4"
    vid.write_bytes(b"x")
    job = {"editor_defaults": {"cartao_fundo": {"modo": "video", "biblioteca": "b1"}, "paleta": {"primaria": "#112233"}},
           "media_library": [{"id": "b1", "path": str(vid), "media_type": "video"}]}
    cfg = A._job_site_cfg(job)
    assert cfg["cartao_fundo"]["video_path"] == str(vid) and cfg["cartao_fundo"]["cor"] == "#112233"


def test_direcao_propaganda_liga_o_cartao():
    import dp_direcao
    p = dp_direcao.planejar([{"start": 0, "end": 3, "foto": True}, {"start": 3, "end": 6, "foto": True}], "sys_propaganda", semente=3)
    assert p["bordas"] == "cartao" and p["cartao_fundo"]["modo"] == "gerado"
    assert dp_direcao.planejar([{"start": 0, "end": 3, "foto": True}], "sys_tudo")["bordas"] is None


def test_editor_tem_a_opcao_e_o_painel():
    import os
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "estudio.html"), encoding="utf-8") as f:
        h = f.read()
    assert 'value="cartao"' in h and 'id="cfModo"' in h and "global_cartao_fundo" in h and "fill-cartao" in h
