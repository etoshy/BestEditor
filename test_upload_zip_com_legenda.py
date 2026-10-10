"""
Teste de integração do upload de .zip (áudio + legenda .srt) no lugar
do áudio avulso em /transcribe -- pensado pro caso de já ter baixado o
.zip do Gerador de Voz (que tem áudio + legenda.srt juntos) e não
precisar pagar o custo de transcrever tudo de novo.
"""
import io
import time
import zipfile

import pytest


@pytest.fixture
def app_module(monkeypatch):
    import app as _app_module

    def _sem_previa(segment, **kwargs):
        return {"ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mockado"}

    monkeypatch.setattr(_app_module, "fetch_segment_preview_lightweight", _sem_previa)
    yield _app_module


@pytest.fixture
def client(app_module):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _wait_status(app_module, job_id, alvo, timeout=15):
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        status = app_module._JOBS[job_id]["status"]
        if status in alvo:
            return status
        time.sleep(0.05)
    raise TimeoutError(f"job {job_id} não chegou a {alvo} em {timeout}s (ficou em {status!r})")


_SRT_VALIDO = (
    "1\n00:00:00,000 --> 00:00:02,500\nOlá mundo, esse é um teste.\n\n"
    "2\n00:00:02,500 --> 00:00:05,000\nSegunda linha da legenda.\n"
)


def _zip_bytes(nome_audio="narracao.wav", conteudo_audio=b"conteudo fake de audio",
                nome_srt="legenda.srt", conteudo_srt=_SRT_VALIDO, arquivos_extras=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if nome_audio is not None:
            zf.writestr(nome_audio, conteudo_audio)
        if nome_srt is not None:
            zf.writestr(nome_srt, conteudo_srt)
        for nome, conteudo in (arquivos_extras or {}).items():
            zf.writestr(nome, conteudo)
    buf.seek(0)
    return buf.read()


def _upload_zip(client, zip_bytes, filename="narracao_e_legenda.zip", **campos_extra):
    dados = {"interval_seconds": "7", "providers": ["pexels"]}
    dados.update(campos_extra)
    dados["audio"] = (io.BytesIO(zip_bytes), filename)
    return client.post("/transcribe", data=dados, content_type="multipart/form-data")


class TestUploadDeZipComAudioELegenda:
    def test_zip_valido_pula_a_transcricao_e_usa_os_segmentos_do_srt(self, app_module, client, monkeypatch):
        def transcribe_nao_deveria_ser_chamada(*a, **k):
            raise AssertionError("transcribe_audio não deveria ser chamado quando o .zip já tem o .srt")
        monkeypatch.setattr(app_module, "transcribe_audio", transcribe_nao_deveria_ser_chamada)

        r = _upload_zip(client, _zip_bytes())
        assert r.status_code == 302
        job_id = r.headers["Location"].rstrip("/").rsplit("/", 2)[-2]

        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        job = app_module._JOBS[job_id]
        assert job["status"] == "aguardando_json", job.get("error")
        assert job["segments"] == [
            {"start": 0.0, "end": 2.5, "text": "Olá mundo, esse é um teste."},
            {"start": 2.5, "end": 5.0, "text": "Segunda linha da legenda."},
        ]
        assert job["total_duration"] == 5.0
        assert "Olá mundo" in job["prompt"]

    def test_audio_extraido_do_zip_fica_salvo_no_disco(self, app_module, client, monkeypatch):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não deveria transcrever")))
        r = _upload_zip(client, _zip_bytes(conteudo_audio=b"BYTES-DE-AUDIO-UNICOS-12345"))
        job_id = r.headers["Location"].rstrip("/").rsplit("/", 2)[-2]
        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        job = app_module._JOBS[job_id]
        assert job["status"] == "aguardando_json", job.get("error")
        with open(job["audio_path"], "rb") as f:
            assert f.read() == b"BYTES-DE-AUDIO-UNICOS-12345"

    def test_zip_sem_audio_mostra_erro_sem_criar_job(self, app_module, client):
        jobs_antes = set(app_module._JOBS.keys())
        r = _upload_zip(client, _zip_bytes(nome_audio=None))
        assert r.status_code == 200  # re-renderiza index.html com erro, não redireciona
        assert "não encontrei nenhum arquivo de áudio".encode() in r.data
        assert set(app_module._JOBS.keys()) == jobs_antes  # nenhum job novo foi criado

    def test_zip_sem_srt_mostra_erro_sem_criar_job(self, app_module, client):
        jobs_antes = set(app_module._JOBS.keys())
        r = _upload_zip(client, _zip_bytes(nome_srt=None))
        assert r.status_code == 200
        assert "não encontrei nenhum arquivo .srt".encode() in r.data
        assert set(app_module._JOBS.keys()) == jobs_antes

    def test_srt_invalido_dentro_do_zip_mostra_erro_claro(self, app_module, client):
        r = _upload_zip(client, _zip_bytes(conteudo_srt="isso não é um srt de jeito nenhum"))
        assert r.status_code == 200
        assert "Não encontrei nenhum bloco válido".encode() in r.data

    def test_zip_corrompido_mostra_erro_claro(self, app_module, client):
        r = _upload_zip(client, b"isso nao e um zip de verdade, so bytes aleatorios")
        assert r.status_code == 200
        assert "não é um .zip válido".encode() in r.data

    def test_zip_com_add_word_captions_desliga_e_avisa(self, app_module, client, monkeypatch):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não deveria transcrever")))
        r = _upload_zip(client, _zip_bytes(), add_word_captions="on")
        job_id = r.headers["Location"].rstrip("/").rsplit("/", 2)[-2]
        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        job = app_module._JOBS[job_id]
        assert job["status"] == "aguardando_json", job.get("error")
        assert job["add_word_captions"] is False
        assert "timestamp por palavra" in job["aviso_legenda_palavra_desligada"]

    def test_zip_escolhe_primeiro_arquivo_de_audio_reconhecido_ignorando_outros(self, app_module, client, monkeypatch):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não deveria transcrever")))
        zip_bytes = _zip_bytes(arquivos_extras={"leia-me.txt": "não é áudio nem srt, deve ser ignorado"})
        r = _upload_zip(client, zip_bytes)
        job_id = r.headers["Location"].rstrip("/").rsplit("/", 2)[-2]
        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        assert app_module._JOBS[job_id]["status"] == "aguardando_json"

    def test_audio_normal_sem_zip_continua_funcionando_como_antes(self, app_module, client, synthetic_audio, monkeypatch):
        segments = [{"start": 0.0, "end": 3.0, "text": "transcrição normal", "words": []}]
        chamadas = []
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: (chamadas.append(1), segments)[1])
        with open(synthetic_audio, "rb") as f:
            r = client.post("/transcribe", data={
                "interval_seconds": "7", "providers": ["pexels"], "audio": (f, "narracao.wav"),
            }, content_type="multipart/form-data")
        job_id = r.headers["Location"].rstrip("/").rsplit("/", 2)[-2]
        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        job = app_module._JOBS[job_id]
        assert job["status"] == "aguardando_json", job.get("error")
        assert chamadas == [1]  # transcreveu normalmente -- fluxo de sempre intacto
        assert job["segments"] == segments
