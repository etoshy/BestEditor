"""v84_412 — 🔄 Reiniciar em Meus vídeos: refaz a transcrição com o áudio salvo (sem enviar de novo)."""
import os
import time

import pytest


@pytest.fixture
def A():
    import app as m
    m.app.config["TESTING"] = True
    return m


def _esperar(A, jid, alvo, t=10):
    fim = time.time() + t
    while time.time() < fim and A._JOBS[jid]["status"] not in alvo:
        time.sleep(0.05)
    return A._JOBS[jid]["status"]


def test_reiniciar_refaz_a_transcricao(A, monkeypatch, tmp_path):
    jid = "reini0000001"
    d = A._job_dir(jid)
    os.makedirs(d, exist_ok=True)
    audio = os.path.join(d, "narracao.wav")
    open(audio, "wb").write(b"x")
    A._JOBS[jid] = {"job_id": jid, "status": "erro_transcricao", "error": "O servidor reiniciou no meio da transcrição",
                    "audio_path": audio, "original_filename": "voz.wav", "created_at": 1.0, "providers": ["pexels"],
                    "add_word_captions": False, "interval_seconds": 7, "ritmo_cenas": "livre", "language": "pt",
                    "language_pedido": "pt"}
    pedidos = []
    monkeypatch.setattr(A, "transcribe_audio", lambda p, **kw: pedidos.append((p, kw.get("language"))) or
                        [{"start": 0.0, "end": 2.0, "text": "olá mundo"}])
    monkeypatch.setattr(A, "_auto_ia_montar", lambda *a, **k: None)
    c = A.app.test_client()
    h = c.get("/jobs").get_data(as_text=True)
    assert f"/job/{jid}/reiniciar" in h and "🔄 Reiniciar" in h
    r = c.post(f"/job/{jid}/reiniciar")
    assert r.status_code == 302 and "/transcribing" in r.headers["Location"]
    assert _esperar(A, jid, {"aguardando_json", "erro_transcricao"}) == "aguardando_json", A._JOBS[jid].get("error")
    assert pedidos == [(audio, "pt")]
    # já não está parado: reiniciar de novo avisa
    r = c.post(f"/job/{jid}/reiniciar", headers={"Accept": "application/json"})
    assert r.status_code == 400
    A._JOBS.pop(jid, None)


def test_sem_audio_avisa(A):
    jid = "reini0000002"
    A._JOBS[jid] = {"job_id": jid, "status": "erro_transcricao", "audio_path": "/nao/existe.wav", "created_at": 1.0}
    r = A.app.test_client().post(f"/job/{jid}/reiniciar", headers={"Accept": "application/json"})
    assert r.status_code == 400 and "envie de novo" in r.get_json()["erro"]
    A._JOBS.pop(jid, None)
