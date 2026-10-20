"""v84_193: personagem animada — pose → Flow (Início = Fim = a pose sobre verde) → verde sai aqui → WebM com alfa →
guardado no projeto pra reusar; entra na aparição e no render."""
import json
import os
import subprocess
import threading

import numpy as np
import pytest
from PIL import Image, ImageDraw

import personagens_animar as PA
import video_assembler as va


def _pose(path):
    im = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle([60, 40, 140, 300], fill=(200, 30, 40, 255))
    im.save(path)
    return str(path)


def _video_verde(path, n=24):
    """Um 'clipe do Flow': fundo verde 3:4 e o boneco vermelho mexendo."""
    pasta = os.path.dirname(path)
    for k in range(n):
        im = Image.new("RGB", (180, 320), (0, 255, 0))  # 9:16 como o Flow devolve
        ImageDraw.Draw(im).rectangle([50 + (k % 6), 80, 130 + (k % 6), 300], fill=(200, 30, 40))
        im.save(os.path.join(pasta, f"v_{k:03d}.png"))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "24", "-i", os.path.join(pasta, "v_%03d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", path], check=True)
    return path


class _LoteFalso:
    def __init__(self):
        self.fila, self.trava, self.pedidos = [], threading.RLock(), []

    def adicionar(self, itens, proporcao="16:9", **kw):
        out = []
        for it in itens:
            j = {"id": f"j{len(self.fila)}", "estado": "pendente", "resultados": [], **it, "proporcao": proporcao}
            self.fila.append(j)
            out.append(j)
        self.pedidos.extend(itens)
        return out

    def iniciar(self):
        pass


def test_prompt_e_frame(tmp_path):
    p = PA.prompt_animacao("Mira", "curiosa", "fala", "Was ist das?")
    assert "#00FF00" in p and "static" in p and "same pose as the first frame" in p and "mouth" in p
    assert "mouth opens" not in PA.prompt_animacao("Mira", "", "parada")
    fr = PA.frame_verde(_pose(tmp_path / "p.png"), str(tmp_path / "f.png"))
    im = Image.open(fr)
    assert abs(im.size[0] / im.size[1] - 9 / 16) < 0.01 and im.size[0] == 200  # 9:16, a pose inteira (nada cortado)
    px = im.getpixel((2, 2))
    assert px[1] > 240 and px[0] < 20 and px[2] < 20


def test_processar_tira_o_verde(tmp_path):
    v = _video_verde(str(tmp_path / "v.mp4"))
    r = PA.processar(v, str(tmp_path / "out.webm"))
    assert r["quadros"] == 46  # ida (24) + volta (22): termina na pose
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-c:v", "libvpx-vp9", "-i", r["webm"], "-frames:v", "1",
                    str(tmp_path / "q.png")], check=True)
    q = Image.open(tmp_path / "q.png").convert("RGBA")
    assert q.size[0] / q.size[1] == pytest.approx(2 / 3, abs=0.02)
    a = np.asarray(q)
    assert a[5, 5, 3] < 20 and a[q.size[1] - 5, q.size[0] // 2, 3] > 230  # canto transparente, boneco opaco


def test_pedir_reusa_e_aplica(tmp_path, monkeypatch):
    """v84_205: o Flow faz UM quadro intermediário (foto com a pose de referência); aqui ele é recortado igual às poses
    e alterna com a pose num WebM em loop."""
    import personagens_pod as pp
    import flow_estudio as FE
    monkeypatch.setattr(pp, "pasta_raiz", lambda base=None: str(tmp_path / "pp"))
    lote = _LoteFalso()
    monkeypatch.setattr(PA, "_lote", lambda: lote)
    gal = tmp_path / "gal"
    gal.mkdir()
    monkeypatch.setattr(FE, "pasta_galeria", lambda: str(gal))
    pose = _pose(tmp_path / "mira_curiosa_dir.png")
    it = PA.pedir("b", "abc123", {"caminho": pose, "arquivo": "mira_curiosa_dir.png"}, "fala", "Mira", "Was?")
    ped = lote.pedidos[0]
    assert it["estado"] == "fila" and ped["tipo"] == "imagem" and ped["referencia_arquivo"].endswith("_ref.jpg")
    assert lote.fila[0]["proporcao"] == "3:4" and "IN-BETWEEN" in ped["prompt"] and "mouth clearly OPEN" in ped["prompt"]
    PA.pedir("b", "abc123", {"caminho": pose}, "fala")
    assert len(lote.fila) == 1  # a mesma pose + tipo não vai duas vezes
    q = Image.new("RGB", (300, 400), (0, 255, 0))  # o "quadro 2" do Flow: o boneco um pouco mexido, fundo verde
    ImageDraw.Draw(q).rectangle([100, 60, 190, 400], fill=(200, 30, 40))
    q.save(gal / "q2.png")
    lote.fila[0].update(estado="ok", resultados=[{"tipo": "imagem", "arquivo": "q2.png"}])
    d = PA.sincronizar("abc123", "b")
    k = PA.chave(pose, "fala")
    assert d[k]["estado"] == "pronto" and os.path.isfile(d[k]["webm"]) and os.path.isfile(d[k]["quadro2"]), d[k]
    assert d[k]["duracao"] < 1.0  # fala: alterna rápido
    jd = tmp_path / "job"
    (jd / "personagens").mkdir(parents=True)
    copia = jd / "personagens" / "mira_curiosa_dir.png"
    copia.write_bytes(open(pose, "rb").read())
    ov = {"id": "o1", "origem": "personagem", "projeto_id": "abc123", "source": {"value": str(copia)},
          "boca_janelas": [[1, 2]], "anim_pedida": True}
    job = {"overlays": [ov]}
    assert PA.aplicar_prontas(job, "b", str(jd)) >= 1 and os.path.isfile(ov["anim_video"])
    import personagens_editor as pe
    r = pe.para_render(ov)
    assert r["anim_video"] == ov["anim_video"] and r["boca_path"] is None


def test_render_com_clipe(tmp_path):
    v = _video_verde(str(tmp_path / "v.mp4"))
    webm = PA.processar(v, str(tmp_path / "a.webm"))["webm"]
    base = str(tmp_path / "base.mp4")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x3050a0:s=640x360:d=4:r=25", "-f", "lavfi",
                    "-i", "anullsrc=r=24000:cl=mono", "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", base], check=True)
    png = _pose(tmp_path / "p.png")
    for modo in ("repetir", "uma_vez"):
        ov = {"resolved_path": png, "media_type": "image", "start": 0.5, "end": 3.5, "size_percent": 25, "personagem": "mira",
              "x_percent": 50, "y_percent": 50, "ancora": "centro", "anim_in": "nenhuma", "anim_out": "aparecer",
              "anim_dur": 0.3, "lado": "esquerda", "anim_video": webm, "anim_modo": modo}
        out = str(tmp_path / f"out_{modo}.mp4")
        va.apply_overlays(base, [ov], out, 640, 360)

        def verm(t):
            f = str(tmp_path / "f.png")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(t), "-i", out, "-frames:v", "1", f], check=True)
            a = np.asarray(Image.open(f).convert("RGB")).astype(int)
            return ((a[..., 0] > 150) & (a[..., 1] < 90) & (a[..., 2] < 110)).sum()
        assert verm(0.2) == 0 and verm(2.9) > 500 and verm(3.8) == 0  # clipe de 1 s: "uma vez" segura a pose até o fim


def test_flow_lote_guarda_fim(tmp_path, monkeypatch):
    import flow_lote
    monkeypatch.setattr(flow_lote.Lote, "_salvar", lambda self: None)
    L = flow_lote.Lote.__new__(flow_lote.Lote)
    L.fila, L.trava = [], threading.RLock()
    L.log = lambda *a, **k: None
    fr = _pose(tmp_path / "f.png")
    j = L.adicionar([{"prompt": "x", "tipo": "video", "inicio_arquivo": fr, "fim_arquivo": fr}], proporcao="3:4")[0]
    assert j["inicio_arquivo"] == j["fim_arquivo"] == os.path.abspath(fr)
