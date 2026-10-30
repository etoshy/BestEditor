"""🔗 v84_282 — aba Juntar vídeos: sem recodificar quando o formato é igual, recodifica quando é diferente."""
import io
import os
import subprocess

import pytest
from flask import Flask

import juntar_videos as J


def _video(cam, w=320, h=180, fps=30, dur=1.0, som=True, cor="red"):
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color={cor}:s={w}x{h}:r={fps}:d={dur}"]
    if som:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={dur}", "-c:a", "aac", "-ac", "2"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", cam]
    subprocess.run(cmd, check=True)
    return cam


@pytest.fixture()
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("JUNTAR_DIR", str(tmp_path / "juntar"))
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))
    J.registrar(app, str(tmp_path))
    return app.test_client(), tmp_path


def _esperar(c, pid):
    import time
    for _ in range(300):
        j = c.get(f"/juntar/{pid}/estado").get_json()
        if j["tarefa"] and not j["tarefa"]["rodando"]:
            return j
        time.sleep(0.1)
    raise AssertionError("não terminou")


def _enviar(c, pid, cam, nome):
    with open(cam, "rb") as f:
        return c.post(f"/juntar/{pid}/enviar", data={"arquivos": (io.BytesIO(f.read()), nome)}, content_type="multipart/form-data").get_json()


def test_junta_sem_recodificar_e_na_ordem(cli):
    c, tmp = cli
    a = _video(str(tmp / "a.mp4"), dur=1.0, cor="red")
    b = _video(str(tmp / "b.mp4"), dur=2.0, cor="blue")
    p = J.novo(str(tmp), "Teste junto")
    _enviar(c, p["id"], a, "parte 1.mp4")
    j = _enviar(c, p["id"], b, "parte 2.mp4")
    assert [v["arq"] for v in j["projeto"]["videos"]] == ["parte_1.mp4", "parte_2.mp4"]
    assert j["compat"]["copia"] is True
    j = c.post(f"/juntar/{p['id']}/ordem", json={"ordem": ["parte_2.mp4", "parte_1.mp4"]}).get_json()
    assert j["ok"] and j["projeto"]["videos"][0]["arq"] == "parte_2.mp4"
    assert c.post(f"/juntar/{p['id']}/juntar", json={}).get_json()["ok"]
    j = _esperar(c, p["id"])
    assert not j["tarefa"]["erro"], j["tarefa"]["erro"]
    s = j["projeto"]["saida"]
    assert s["copia"] and s["dur"] == pytest.approx(3.0, abs=0.15) and j["saida_atual"]
    r = c.get(f"/juntar/{p['id']}/baixar")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"] and len(r.data) > 1000
    # o primeiro quadro é o azul (a ordem foi trocada)
    out = os.path.join(J.pasta(p["id"], str(tmp)), "saida", s["arq"])
    px = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    assert px[2] > 150 and px[0] < 80
    # mudou a ordem depois → saída antiga
    j = c.post(f"/juntar/{p['id']}/ordem", json={"ordem": ["parte_1.mp4", "parte_2.mp4"]}).get_json()
    assert j["saida_atual"] is False


def test_formatos_diferentes_recodifica_no_maior(cli):
    c, tmp = cli
    a = _video(str(tmp / "a.mp4"), 640, 360, 30, 1.0, som=True)
    b = _video(str(tmp / "b.mp4"), 320, 240, 25, 1.0, som=False)
    p = J.novo(str(tmp), "mix")
    _enviar(c, p["id"], a, "a.mp4")
    j = _enviar(c, p["id"], b, "b.mp4")
    assert j["compat"]["copia"] is False and "resolução" in j["compat"]["motivo"]
    assert j["destino"] == {"w": 640, "h": 360, "fps": 30}
    c.post(f"/juntar/{p['id']}/juntar", json={"qualidade": "rapido"})
    j = _esperar(c, p["id"])
    assert not j["tarefa"]["erro"], j["tarefa"]["erro"]
    s = j["projeto"]["saida"]
    assert not s["copia"] and (s["w"], s["h"]) == (640, 360) and s["dur"] == pytest.approx(2.0, abs=0.15)
    i = J.info(os.path.join(J.pasta(p["id"], str(tmp)), "saida", s["arq"]))
    assert i["audio"]


def test_paginas_e_remover(cli):
    c, tmp = cli
    p = J.novo(str(tmp), "x")
    a = _video(str(tmp / "a.mp4"))
    _enviar(c, p["id"], a, "a.mp4")
    j = _enviar(c, p["id"], a, "a.mp4")
    assert [v["arq"] for v in j["projeto"]["videos"]] == ["a.mp4", "a_2.mp4"]
    j = c.post(f"/juntar/{p['id']}/remover", json={"arq": "a.mp4"}).get_json()
    assert [v["arq"] for v in j["projeto"]["videos"]] == ["a_2.mp4"]
    assert c.post(f"/juntar/{p['id']}/juntar", json={}).status_code == 400
    j = c.post(f"/juntar/{p['id']}/enviar", data={"arquivos": (io.BytesIO(b"xx"), "nota.txt")}, content_type="multipart/form-data").get_json()
    assert j["erros"]
    assert c.get("/juntar/zz/estado").status_code == 404
