"""🎥 v84_292 — câmera virtual: segue o principal, larga ele pra seguir a bola em voo até a cesta, volta; começa aberta."""
import os
import subprocess

import pytest

import camera_virtual as CV


def _cena(cam):
    """1280x720: robô vermelho à esquerda, cesta azul à direita; a bola laranja sai da mão em 2 s e chega na cesta em 3 s."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x606060:s=1280x720:r=25:d=6",
                    "-f", "lavfi", "-i", "color=c=red:s=100x260:r=25:d=6", "-f", "lavfi", "-i", "color=c=orange:s=40x40:r=25:d=6",
                    "-f", "lavfi", "-i", "color=c=blue:s=120x80:r=25:d=6", "-f", "lavfi", "-i", "sine=f=300:d=6",
                    "-filter_complex", "[0:v][1:v]overlay=x=160:y=370[a];[a][3:v]overlay=x=1100:y=170[b];"
                    "[b][2:v]overlay=x='if(lt(t,2),265,if(lt(t,3),265+(1140-265)*(t-2),1140))':y='if(lt(t,2),400,if(lt(t,3),400-330*sin(PI*(t-2))+(190-400)*(t-2),190+200*min(1,t-3)))'[v]",
                    "-map", "[v]", "-map", "4:a", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cam],
                   check=True)


def _caixa_cor(img, f):
    from PIL import Image
    im = Image.open(img).convert("RGB")
    w, h = im.size
    pts = [(x, y) for x in range(0, w, 4) for y in range(0, h, 4) if f(im.getpixel((x, y)))]
    if not pts:
        return []
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [(min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h)]


class VisaoCores:
    erro = ""

    def achar(self, img, o):
        cor = {"robot": lambda p: p[0] > 200 and p[1] < 60 and p[2] < 60, "ball": lambda p: p[0] > 200 and 120 < p[1] < 200 and p[2] < 60,
               "hoop": lambda p: p[2] > 200 and p[0] < 60 and p[1] < 60}[o]
        return _caixa_cor(img, cor)


def _centro_x(img, f):
    from PIL import Image
    im = Image.open(img).convert("RGB")
    xs = [x for x in range(0, im.width, 6) for y in range(0, im.height, 12) if f(im.getpixel((x, y)))]
    return sum(xs) / len(xs) if xs else None


def test_camera_segue_a_bola_ate_a_cesta_e_volta(tmp_path):
    cena = str(tmp_path / "cena.mp4")
    _cena(cena)
    out = str(tmp_path / "v.mp4")
    r = CV.seguir(VisaoCores(), cena, cena, 0, 6, out, {"principal": "robot", "acao": ["ball"], "destino": ["hoop"]}, [])
    assert [e["tipo"] for e in r["eventos"]] == ["lancamento", "chegada"]
    assert 1.6 <= r["eventos"][0]["t"] <= 2.3 and 2.4 <= r["eventos"][1]["t"] <= 3.3
    assert r["foco"].get("ball + hoop", 0) > 0.3 and r["foco"]["principal"] > 2
    assert set(r["rastros"]) >= {"robot", "ball"}
    q = {}
    for t in (0.1, 1.6, 2.9, 5.6):
        f = str(tmp_path / f"q{t}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", out, "-frames:v", "1", f], check=True)
        q[t] = f
    vermelho = lambda p: p[0] > 200 and p[1] < 60 and p[2] < 60  # noqa: E731
    azul = lambda p: p[2] > 200 and p[0] < 60 and p[1] < 60  # noqa: E731
    from PIL import Image
    # começa ABERTO: o quadro inteiro aparece (com o fundo desfocado) — robô e cesta juntos
    assert _centro_x(q[0.1], vermelho) is not None and _centro_x(q[0.1], azul) is not None
    assert 300 < _centro_x(q[1.6], vermelho) < 780          # depois entra no robô (no meio)
    assert _centro_x(q[2.9], azul) is not None               # a bola chegando: a cesta aparece
    assert _centro_x(q[5.6], vermelho) is not None and _centro_x(q[5.6], azul) is None  # voltou pro robô
    assert Image.open(q[1.6]).size == (1080, 1920)


def test_sem_acao_so_segue_o_principal_e_o_zoom_acompanha_o_tamanho():
    tracks = {"robot": [(t / 2, (0.1, 0.2, 0.2, 0.9)) for t in range(10)]}
    p = CV.planejar(tracks, {"principal": "robot", "acao": [], "destino": []}, 4.5, [], 1920, 1080, abrir_inicio=False)
    assert not p["eventos"] and all(n == "principal" for _, n in p["foco"])
    cx, cy, vw = p["alvos"][20][1:]
    assert cx == pytest.approx(0.15 * 1920, abs=2) and vw >= 1080 * 0.7 * 1.3 * 9 / 16 * 0.99
    grande = {"robot": [(t / 2, (0.05, 0.0, 0.95, 1.0)) for t in range(10)]}  # assunto enorme (close) → abre
    assert CV.planejar(grande, {"principal": "robot"}, 4.5, [], 1920, 1080, abrir_inicio=False)["alvos"][20][3] == 1920


def test_destaque_usa_o_rastro_do_objeto_certo():
    import curtos_comentario as CC
    p = {"rastros": {"M1": {"red humanoid robot": [[0.5, 100, 500, 300, 900]], "basketball": [[1.0, 600, 700, 80, 80], [1.5, 700, 400, 80, 80]],
                            "basketball hoop": [[1.5, 650, 200, 200, 120]]}}}
    assert CC.objeto_rastreado(p, "M1", "the ball") == "basketball"
    assert CC.objeto_rastreado(p, "M1", "the hoop") == "basketball hoop"
    assert CC.objeto_rastreado(p, "M1", "robot's legs") == "red humanoid robot"
    assert CC.chaves_dos_rastros(p, "M1", 0.9, 2.0, "ball") == [{"t": 0.1, "caixa": [600, 700, 80, 80]}, {"t": 0.6, "caixa": [700, 400, 80, 80]}]
    assert CC.objeto_rastreado(p, "M2", "ball") is None


def test_som_do_evento_cai_no_segundo_certo_do_video(monkeypatch):
    import curtos as CT
    import dp_sons
    monkeypatch.setattr(CT, "escolher_som", lambda tipo, sem, ev=None, sons=None: f"som/{tipo}")
    monkeypatch.setattr(dp_sons, "evento", lambda som, t, vol: {"inicio": round(t - 0.1, 3), "volume": vol})
    p = {"id": "x", "eventos_som": [{"mid": "M1", "t": 4.2, "tipo": "whoosh", "o_que": "lancamento"},
                                    {"mid": "M1", "t": 9.0, "tipo": "impacto", "o_que": "chegada"}]}
    planos = [{"start": 0.0, "end": 3.0, "clipe": {"mid": "M1", "ini": 3.0, "fim": 6.0}},
              {"start": 3.0, "end": 5.0, "clipe": {"mid": "M2", "ini": 0.0, "fim": 2.0}}]
    out = CT.sons_dos_eventos(p, planos, 0.8, [])
    assert [(e["som"], e["start"], e["curto"]) for e in out] == [("som/whoosh", 1.1, "evento:lancamento")]  # 9.0 s não aparece no vídeo
