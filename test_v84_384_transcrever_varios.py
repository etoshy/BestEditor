"""v84_384: Transcrever — vários arquivos em fila, sem cópia dupla, e apaga o vídeo deixando só a transcrição."""
import io
import os
import sys
import threading
import time
import types

import transcrever_avulso as ta


def _whisper_falso(monkeypatch):
    monkeypatch.setitem(sys.modules, "whisper_transcribe",
                        types.SimpleNamespace(transcribe_audio=lambda *a, **k: [{"start": 0, "end": 1, "text": "olá mundo"}]))
    monkeypatch.setattr(ta, "_extrair_audio", lambda v, a: open(a, "wb").write(b"RIFF"))
    monkeypatch.setattr(ta, "_dimensoes_do_video", lambda v: (1920, 1080))


def test_move_e_apaga(tmp_path, monkeypatch):
    _whisper_falso(monkeypatch)
    enviado = tmp_path / "enviado_a.mp4"
    enviado.write_bytes(b"x" * 1000)
    r = ta.processar(str(tmp_path), arquivo_path=str(enviado), apagar_video=True)
    assert r["video_apagado"] and r["video"] is None
    assert sorted(os.listdir(tmp_path)) == ["transcricao.json", "transcricao.srt", "transcricao.txt"]


def test_sem_apagar_fica_uma_copia_so(tmp_path, monkeypatch):
    _whisper_falso(monkeypatch)
    enviado = tmp_path / "enviado_a.mp4"
    enviado.write_bytes(b"x" * 1000)
    ta.processar(str(tmp_path), arquivo_path=str(enviado))
    assert "video.mp4" in os.listdir(tmp_path) and "enviado_a.mp4" not in os.listdir(tmp_path)


def test_varios_em_fila_um_de_cada_vez(monkeypatch):
    import app as A
    rodando, maximo = [0], [0]
    trava = threading.Lock()

    def falso(pasta, **kw):
        with trava:
            rodando[0] += 1
            maximo[0] = max(maximo[0], rodando[0])
        time.sleep(0.2)
        with trava:
            rodando[0] -= 1
        assert kw["apagar_video"] is True
        return {"modo": "transcrever", "video": None, "video_apagado": True}
    monkeypatch.setattr(A.ta_avulso, "processar", falso)
    c = A.app.test_client()
    ids = []
    for k in range(3):
        r = c.post("/transcrever", data={"modo": "transcrever", "apagar_video": "1",
                                         "arquivo": (io.BytesIO(b"v" * 100), f"v{k}.mp4")}, content_type="multipart/form-data")
        ids.append(r.get_json()["job_id"])
    for _ in range(100):
        if all(A._TRANSCRICOES_AVULSAS_JOBS[i]["status"] == "pronto" for i in ids):
            break
        time.sleep(0.05)
    assert all(A._TRANSCRICOES_AVULSAS_JOBS[i]["status"] == "pronto" for i in ids) and maximo[0] == 1
    assert A._TRANSCRICOES_AVULSAS_JOBS[ids[0]]["nome"] == "v0.mp4"
    assert 'id="chk-apagar"' in c.get("/transcrever").get_data(as_text=True)
