"""v84_108 — ⏸ pausar / ▶ retomar a busca de prévias: as prontas ficam, o retomar busca só as que faltam."""
import threading
import time
import uuid

import pytest


@pytest.fixture
def app_mod(monkeypatch, tmp_path):
    import app as a
    monkeypatch.setattr(a, "_save_state", lambda job_id: None)
    monkeypatch.setattr(a, "_ia_preparar_buscas", lambda *x, **k: None)
    monkeypatch.setattr(a, "_prebaixar_iniciar", lambda *x, **k: None)
    monkeypatch.setattr(a, "_avisar_fim", lambda *x, **k: None)
    monkeypatch.setattr(a, "generate_waveform_image", lambda *x, **k: None)
    monkeypatch.setattr(a, "_job_dir", lambda job_id: str(tmp_path / job_id))
    monkeypatch.setattr(a, "_job_site_cfg", lambda job: {"preview_fetch_concurrency": 1, "evitar_repeticao_clipes": False})
    return a


def _esperar(a, jid, alvos, t=10):
    fim = time.time() + t
    while time.time() < fim:
        if a._JOBS[jid]["status"] in alvos:
            return a._JOBS[jid]["status"]
        time.sleep(0.05)
    raise TimeoutError(a._JOBS[jid]["status"])


def test_pausa_e_retoma_so_o_que_falta(app_mod, monkeypatch):
    a = app_mod
    buscados = []
    liberar = threading.Event()

    def falso(segment, **k):
        buscados.append(segment.query)
        if len(buscados) == 1:
            liberar.wait(5)  # o 1º trecho demora: dá tempo de pausar
        return {"ok": True, "thumbnail_url": "x", "result_url": "u", "label": segment.query, "error": None}

    monkeypatch.setattr(a, "fetch_segment_preview_lightweight", falso)
    jid = "t-" + uuid.uuid4().hex[:8]
    segs = [{"start": i * 3.0, "end": i * 3.0 + 3, "provider": "pexels", "query": f"q{i}"} for i in range(4)]
    a._JOBS[jid] = {"job_id": jid, "status": "x", "pending_segments": segs, "audio_path": "a.wav"}
    c = a.app.test_client()
    a._fetch_previews(jid, a._JOBS[jid], [a._segmento_obj(d) for d in segs])
    time.sleep(0.2)
    r = c.post(f"/job/{jid}/previas/pausar")
    assert r.status_code == 200
    assert c.get(f"/job/{jid}/fetching-previews-status").get_json()["pausando"] is True
    liberar.set()
    assert _esperar(a, jid, {"previas_pausadas", "pronto_para_editar"}) == "previas_pausadas"
    assert buscados == ["q0"]
    pv = a._JOBS[jid]["segment_previews"]
    assert pv[0]["ok"] and pv[1:] == [None, None, None]
    assert a._JOBS[jid]["preview_progress"] == {"current": 1, "total": 4}
    # a página mostra os botões
    h = c.get(f"/job/{jid}/fetching-previews").get_data(as_text=True)
    assert "⏸ Pausar" in h and "▶ Retomar" in h and "previas_pausadas" in h
    # ▶ retomar: busca só q1..q3
    assert c.post(f"/job/{jid}/previas/retomar").status_code == 200
    assert _esperar(a, jid, {"pronto_para_editar"}) == "pronto_para_editar"
    assert buscados == ["q0", "q1", "q2", "q3"]
    assert all(p and p["ok"] for p in a._JOBS[jid]["segment_previews"])
    assert c.post(f"/job/{jid}/previas/retomar").status_code == 400
    assert c.post(f"/job/{jid}/previas/pausar").status_code == 400


def test_servidor_reiniciou_no_meio_vira_pausado(app_mod, monkeypatch, tmp_path):
    import json
    import os
    a = app_mod
    jid = "r-" + uuid.uuid4().hex[:8]
    os.makedirs(tmp_path / "jobs" / jid)
    with open(tmp_path / "jobs" / jid / "state.json", "w", encoding="utf-8") as f:
        json.dump({"job_id": jid, "status": "buscando_previas", "pending_segments": [{"start": 0, "end": 3}],
                   "segment_previews": [None]}, f)
    monkeypatch.setattr(a, "JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.delenv("NARRATION_SITE_NAO_CARREGAR_PROJETOS", raising=False)
    try:
        a._carregar_projetos_salvos()
        assert a._JOBS[jid]["status"] == "previas_pausadas"
    finally:
        a._JOBS.pop(jid, None)


def test_projeto_interrompido_antes_continua_pelo_editor(app_mod, monkeypatch):
    """Projeto que já abriu no editor com trechos sem prévia (servidor fechou no meio, antes da v84_108):
    o editor mostra ▶ Continuar e o retomar busca só os que faltam."""
    a = app_mod
    buscados = []
    monkeypatch.setattr(a, "fetch_segment_preview_lightweight", lambda seg, **k: buscados.append(seg.query) or
                        {"ok": True, "thumbnail_url": "x", "result_url": "u", "label": seg.query, "error": None})
    jid = "i-" + uuid.uuid4().hex[:8]
    segs = [{"start": i * 3.0, "end": i * 3.0 + 3, "provider": "pexels", "query": f"q{i}", "media_type": "video"} for i in range(3)]
    pronta = {"index": 0, "ok": True, "thumbnail_url": "x", "result_url": "u", "label": "q0", "error": None}
    a._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "pending_segments": segs, "audio_path": "a.wav",
                    "duration": 9.0, "segment_previews": [pronta]}  # lista mais curta que os trechos
    assert a.previas_faltando(a._JOBS[jid]) == 2
    c = a.app.test_client()
    for modo in ("estudio", "classico"):
        h = c.get(f"/job/{jid}/edit-segments?modo={modo}").get_data(as_text=True)
        assert "▶ Continuar a busca de prévias" in h and "<b>2</b> trecho(s)" in h
    assert c.post(f"/job/{jid}/previas/retomar").status_code == 200
    assert _esperar(a, jid, {"pronto_para_editar"}) == "pronto_para_editar"
    time.sleep(0.1)
    assert buscados == ["q1", "q2"] and a._JOBS[jid]["segment_previews"][0] is pronta or a._JOBS[jid]["segment_previews"][0] == pronta
    assert a.previas_faltando(a._JOBS[jid]) == 0
    h = c.get(f"/job/{jid}/edit-segments?modo=estudio").get_data(as_text=True)
    assert "▶ Continuar a busca de prévias" not in h
    assert c.post(f"/job/{jid}/previas/retomar").status_code == 400
