"""v84_304: menos efeitos sonoros e círculo só quando a IA tem certeza do objeto."""
import os

import curtos as CT
import curtos_comentario as CC


def test_poucos_sons_limita_e_prioriza_eventos():
    sons = [{"_t": float(t), "curto": f"B{t}:corte"} for t in range(0, 30, 1)]
    sons.append({"_t": 12.5, "curto": "evento:lancamento"})
    out = CT.poucos_sons(sons, 30.0)
    assert len(out) <= 3
    assert any(e["curto"] == "evento:lancamento" for e in out)
    ts = sorted(e["_t"] for e in out)
    assert all(b - a >= 1.2 for a, b in zip(ts, ts[1:]))


def test_acabamento_sons_nivel():
    assert CT.ACABAMENTO_PADRAO["sons_nivel"] == "poucos"
    p = {"config": {}}
    CT.aplicar_acabamento(p, dict(CT.ACABAMENTO_PADRAO, sons_nivel="nenhum"))
    assert p["config"]["sons_nivel"] == "nenhum"


def test_caixa_sem_certeza_e_descartada(tmp_path, monkeypatch):
    import subprocess
    v = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x240:d=1", "-pix_fmt", "yuv420p", str(v)], check=True)
    duvida = lambda *a, **k: {"achou": True, "certeza": 0.3, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}  # noqa: E731
    assert CC.achar_objeto(str(v), 0.2, "dog", str(tmp_path), duvida) is None
    certo = lambda *a, **k: {"achou": True, "certeza": 0.95, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}  # noqa: E731
    assert CC.achar_objeto(str(v), 0.2, "dog", str(tmp_path), certo)


def test_editor_tira_o_rastreio_do_curto(tmp_path, monkeypatch):
    """🎯 o destaque que veio do curto: o trecho sabe do rastreio e 🚫 volta pro vídeo limpo."""
    import subprocess
    import app as A
    import rastreio as RT
    base = str(tmp_path)
    monkeypatch.setattr(A, "BASE_DIR", base)
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    monkeypatch.setattr(A, "_job_dir", lambda j: os.path.join(base, "jobs", j))
    monkeypatch.setattr(A, "_save_state", lambda *a, **k: None)
    v = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x240:d=1", "-pix_fmt", "yuv420p", str(v)], check=True)
    r = RT.criar(base, str(v), "teste")
    s = {"start": 0, "end": 1, "provider": "material", "query": "R1", "override_source": None}
    A._JOBS["jx"] = {"pending_segments": [s], "segment_previews": [None]}
    A._curto_ligar_rastreio("jx", s, 0, r["id"])
    assert s["rastreio"] and s["_antes_rastreio"]["value"] == RT.caminho_video(base, r)
    assert RT.carregar(base, r["id"])["job"] == "jx" and RT.carregar(base, r["id"])["trecho"] == 0
    cl = A.app.test_client()
    assert cl.post("/job/jx/segmento/0/tirar-rastreio").get_json()["ok"]
    assert s["override_source"]["value"] == RT.caminho_video(base, r) and not s["rastreio"]
    assert cl.post("/job/jx/segmento/0/tirar-rastreio").status_code == 400
    A._JOBS.pop("jx", None)
