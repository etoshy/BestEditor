"""v84_252: 🎯 Rastrear objeto — o objeto é seguido (pra frente e pra trás da caixa), a caixa nova corrige o trajeto,
o vídeo sai com o desenho e o som, e volta pro trecho do Estúdio."""
import os
import subprocess

import numpy as np
import pytest

import rastreio as RT


def _video_objeto(caminho, n=90, fps=30, W=480, H=270):
    import cv2
    rng = np.random.default_rng(3)
    fundo = cv2.GaussianBlur((rng.random((H, W, 3)) * 120).astype(np.uint8), (0, 0), 2)
    verdade = []
    tmp = caminho + ".avi"
    out = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"MJPG"), fps, (W, H))
    for i in range(n):
        fr = fundo.copy()
        x, y, s = int(30 + i * 3), int(40 + i * 1.5), 44
        cv2.rectangle(fr, (x, y), (x + s, y + s), (30, 200, 255), -1)
        cv2.circle(fr, (x + s // 2, y + s // 2), 10, (255, 255, 255), -1)
        verdade.append((x, y, s, s))
        out.write(fr)
    out.release()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-f", "lavfi", "-i", f"sine=f=440:d={n / fps}", "-shortest",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", caminho], check=True)
    os.remove(tmp)
    return caminho, verdade


def _erro_medio(res, verdade):
    e = []
    for k, c in enumerate(res["caixas"]):
        q = res["q0"] + k
        if c and q < len(verdade):
            v = verdade[q]
            e.append(np.hypot(c[0] + c[2] / 2 - v[0] - v[2] / 2, c[1] + c[3] / 2 - v[1] - v[3] / 2))
    return float(np.mean(e)), len(e)


@pytest.mark.parametrize("preferir", ["auto", "fluxo"])
def test_segue_o_objeto_pra_frente_e_pra_tras(tmp_path, preferir):
    v, verdade = _video_objeto(str(tmp_path / "v.mp4"))
    res = RT.rastrear(v, [{"t": 45 / 30, "caixa": list(verdade[45])}], 0, 3, 30, preferir=preferir)
    erro, n = _erro_medio(res, verdade)
    assert n >= 85 and erro < 6, (erro, n, res["rastreador"])


def test_caixa_nova_corrige(tmp_path):
    v, verdade = _video_objeto(str(tmp_path / "v.mp4"))
    errada = list(verdade[10])
    errada[1] += 25  # a 1ª caixa foi desenhada torta…
    res = RT.rastrear(v, [{"t": 10 / 30, "caixa": errada}, {"t": 60 / 30, "caixa": list(verdade[60])}], 0, 3, 30, preferir="fluxo")
    c = res["caixas"][60 - res["q0"]]
    assert c == [round(x, 1) for x in verdade[60]]  # a sua caixa manda naquele quadro
    depois = [res["caixas"][k] for k in range(61, 88)]
    assert all(abs(b[1] - verdade[61 + j][1]) < 6 for j, b in enumerate(depois) if b)  # dali pra frente segue certo


def test_suavizar_preenche_buraco_e_tira_tremedeira():
    cx = [(10.0 + i, 10.0 + (3 if i % 2 else -3), 20.0, 20.0) for i in range(20)]
    cx[8] = cx[9] = None
    s = RT.suavizar(cx)
    assert s[8] and s[9]
    tremor = np.std([b[1] for b in s[3:17]])
    assert tremor < 2.0


def test_gerar_todos_os_tipos(tmp_path, monkeypatch):
    monkeypatch.setenv("RASTREIO_DIR", str(tmp_path / "r"))
    v, verdade = _video_objeto(str(tmp_path / "v.mp4"), n=45)
    r = RT.criar(str(tmp_path), v, "teste")
    r["caixas"] = RT.rastrear(RT.caminho_video(str(tmp_path), r), [{"t": 0.5, "caixa": list(verdade[15])}], 0, 1.5, 30)
    for tipo in RT.TIPOS:
        r["estilo"] = dict(RT.estilo_padrao(), tipo=tipo, texto="OLHA ISSO")
        RT.salvar(str(tmp_path), r)
        s = RT.gerar(str(tmp_path), r["id"])
        info = RT.sondar(s)
        assert abs(info["dur"] - 1.5) < 0.2 and info["largura"] == 480
        r = RT.carregar(str(tmp_path), r["id"])
    a = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", s],
                       capture_output=True, text=True).stdout
    assert "audio" in a  # o som original veio junto
    # o desenho está lá: no quadro 30, o vermelho perto do objeto
    import cv2
    cap = cv2.VideoCapture(s)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 30)
    _ok, fr = cap.read()
    x, y, w, h = verdade[30]
    regiao = fr[max(0, y - 40):y + h + 40, max(0, x - 40):x + w + 40]
    vermelho = ((regiao[:, :, 2] > 180) & (regiao[:, :, 1] < 90) & (regiao[:, :, 0] < 90)).sum()
    assert vermelho > 50


def test_estudio_ida_e_volta(tmp_path, monkeypatch):
    monkeypatch.setenv("RASTREIO_DIR", str(tmp_path / "r"))
    import app as A
    monkeypatch.setattr(A, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(A, "_job_dir", lambda j: str(tmp_path / "jobs" / j))
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    v, verdade = _video_objeto(str(tmp_path / "clip.mp4"), n=45)
    A._JOBS["jrast1"] = {"job_id": "jrast1", "pending_segments": [
        {"start": 0, "end": 1.5, "provider": "pexels", "query": "x", "media_type": "video",
         "override_source": {"source": "local_file", "value": v, "kind": "video"}}],
        "segment_previews": [{"ok": True}], "providers": ["pexels"], "status": "pronto_para_editar"}
    cl = A.app.test_client()
    r = cl.get("/rastrear/do-editor?job=jrast1&trecho=0")
    rid = r.headers["Location"].rsplit("/", 1)[1]
    assert cl.get(f"/rastrear/{rid}").status_code == 200
    assert cl.post(f"/rastrear/{rid}/salvar", json={"chaves": [{"t": 0.5, "caixa": list(verdade[15])}], "faixa": [0, 1.5],
                                                     "estilo": {"tipo": "seta", "texto": "aqui"}}).get_json()["ok"]
    import time
    import rastreio_rotas as RR
    for acao in ("rastrear", "gerar"):
        assert cl.post(f"/rastrear/{rid}/{acao}", json={}).get_json()["ok"]
        for _ in range(400):
            t = RR.TAREFAS.get(rid) or {}
            if t.get("fim"):
                break
            time.sleep(0.05)
        assert not t["erro"], t["erro"]
    assert cl.get(f"/rastrear/{rid}/saida.mp4").status_code == 200
    d = cl.post(f"/rastrear/{rid}/aplicar", json={}).get_json()
    assert d["ok"]
    seg = A._JOBS["jrast1"]["pending_segments"][0]
    assert seg["override_source"]["value"] != v and os.path.isfile(seg["override_source"]["value"])
    assert seg["_antes_rastreio"]["value"] == v and seg["rastreio"]
    # abrir de novo do editor: o mesmo rastreio
    assert cl.get("/rastrear/do-editor?job=jrast1&trecho=0").headers["Location"].endswith(rid)
    assert cl.get("/rastrear").status_code == 200
    A._JOBS.pop("jrast1", None)


def test_para_na_troca_de_cena(tmp_path):
    import cv2
    v, verdade = _video_objeto(str(tmp_path / "v.mp4"), n=60)
    # emenda um plano totalmente diferente depois do quadro 30
    cap = cv2.VideoCapture(v)
    frames = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        frames.append(fr)
    outro = np.full_like(frames[0], 230)
    tmp = str(tmp_path / "c.avi")
    o = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"MJPG"), 30, (frames[0].shape[1], frames[0].shape[0]))
    for i, fr in enumerate(frames):
        o.write(fr if i < 30 else outro)
    o.release()
    res = RT.rastrear(tmp, [{"t": 10 / 30, "caixa": list(verdade[10])}], 0, 2, 30, preferir="fluxo")
    assert res["cortes"] and abs(res["cortes"][0] - 1.0) < 0.05
    assert all(c is None for c in res["caixas"][31:])  # não inventa o objeto no plano novo
    assert res["caixas"][29] is not None
