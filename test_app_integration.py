"""
Teste automatizado do pipeline Flask completo, de ponta a ponta:
upload -> transcrição (mockada) -> prompt -> colar JSON -> montagem
(com clipes sintéticos) -> download do vídeo final.

Também cobre os caminhos de erro (JSON inválido, incompleto) e as
validações de entrada adicionadas depois (interval_seconds,
provedores).
"""
import json
import os
import shutil
import subprocess
import time

import pytest


@pytest.fixture
def app_module(monkeypatch):
    """Importa o módulo Flask uma vez (sem `importlib.reload` e sem
    limpar `_JOBS` entre testes) — cada job usa um UUID único, então não
    há colisão entre testes. Evitamos limpar o dicionário porque uma
    thread de background de um teste anterior pode ainda estar no
    `finally: _save_state(job_id)` quando o próximo teste começaria a
    limpar, causando uma KeyError inofensiva mas barulhenta nos logs.

    Por padrão, `fetch_segment_preview_lightweight` (usado pela
    pré-busca de prévias, que roda em background logo após colar o
    JSON) é mockada pra nunca tocar rede/Chrome de verdade — devolve
    "sem prévia" pra todo segmento. Testes que precisam de uma prévia
    de verdade sobrescrevem isso explicitamente via
    `monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", ...)`.
    """
    import app as _app_module

    def _default_fake_fetch_preview_lightweight(segment, **kwargs):
        return {"ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mockado em teste: sem prévia"}

    monkeypatch.setattr(_app_module, "fetch_segment_preview_lightweight", _default_fake_fetch_preview_lightweight)
    yield _app_module


@pytest.fixture
def flask_client(app_module):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _wait_for_status(app_module, job_id, target_statuses, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = app_module._JOBS[job_id]["status"]
        if status in target_statuses:
            return status
        time.sleep(0.1)
    raise TimeoutError(f"job {job_id} não chegou a {target_statuses} em {timeout}s (ficou em {status!r})")


def _confirm_all_segments_auto(app_module, flask_client, job_id):
    """Espera a pré-busca de prévias terminar, e confirma o editor de
    segmentos sem nenhuma edição — mantém tudo 'automático', usando os
    valores que já vieram da resposta da IA (submit-json agora passa
    pela pré-busca + editor em vez de montar direto)."""
    _wait_for_status(app_module, job_id, {"pronto_para_editar", "erro"})
    return flask_client.post(f"/job/{job_id}/confirm-segments", data={})


class TestFullPipeline:
    def test_end_to_end_happy_path(self, app_module, flask_client, synthetic_audio, synthetic_clips, sample_pt_segments, monkeypatch):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        clip_map = {
            "pexels": synthetic_clips["short_red"],
            "pixabay": synthetic_clips["long_blue"],
            "mixkit": synthetic_clips["exact_green"],
        }

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            def __init__(self, provider):
                self.provider = provider
                class FakeSession:
                    def close(inner_self):
                        pass
                self.session = FakeSession()

            def search_all(self, query=None, category=None, max_pages=1):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "clip.mp4")
                shutil.copy(clip_map[self.provider], dest)
                return dest

        import video_assembler
        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeClient(p)
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        # 1) GET / -> página de upload
        r = flask_client.get("/")
        assert r.status_code == 200
        assert "Envie a narra".encode() in r.data

        # 2) POST /transcribe -> deve responder rápido (redirect), não travar
        t0 = time.time()
        with open(synthetic_audio, "rb") as f:
            r = flask_client.post(
                "/transcribe",
                data={
                    "audio": (f, "narracao.wav"),
                    "interval_seconds": "7",
                    "language": "pt",
                    "providers": ["pexels", "pixabay", "mixkit"],
                    "extra_instructions": "",
                },
                content_type="multipart/form-data",
            )
        assert time.time() - t0 < 1.0, "POST /transcribe deveria retornar rápido (trabalho em background)"
        assert r.status_code == 302

        job_id = list(app_module._JOBS.keys())[-1]
        assert app_module._JOBS[job_id]["status"] in ("transcrevendo", "aguardando_json"), (
            "logo após o POST, o status deveria ser 'transcrevendo' (ou já ter avançado, "
            "já que o mock de transcrição é instantâneo)"
        )

        # 3) espera a transcrição (mockada) terminar
        status = _wait_for_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        assert status == "aguardando_json"
        assert "Bem-vindos ao vídeo" in app_module._JOBS[job_id]["prompt"]

        # 4) GET da página do prompt
        r = flask_client.get(f"/job/{job_id}/prompt")
        assert r.status_code == 200
        assert "Copie o prompt".encode() in r.data

        # 5) POST do JSON válido
        ai_response = json.dumps([
            {"start": 0.0, "end": 3.2, "provider": "pexels", "query": "sunrise over mountains"},
            {"start": 3.2, "end": 6.5, "provider": "pixabay", "query": "busy city street"},
            {"start": 6.5, "end": 9.469, "provider": "mixkit", "query": "animal-nature"},
        ])
        r = flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _confirm_all_segments_auto(app_module, flask_client, job_id)
        assert r.status_code == 302

        # 6) espera a montagem terminar
        status = _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=60)
        assert status == "concluido", app_module._JOBS[job_id].get("error")

        # 7) download do vídeo final
        r = flask_client.get(f"/job/{job_id}/download")
        assert r.status_code == 200
        assert r.content_type == "video/mp4"

    def test_invalid_json_shows_friendly_error_not_500(self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        r = flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": "isso não é json"})
        assert r.status_code == 200
        assert b"JSON" in r.data

        incomplete = json.dumps([{"start": 0.0, "end": 3.0, "provider": "pexels", "query": "x"}])
        r2 = flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": incomplete})
        assert r2.status_code == 200
        assert "áudio".encode() in r2.data


class TestInputValidation:
    def test_non_numeric_interval_seconds(self, flask_client, synthetic_audio):
        with open(synthetic_audio, "rb") as f:
            r = flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "abc", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        assert r.status_code == 200
        assert "número".encode() in r.data

    def test_out_of_range_interval_seconds(self, flask_client, synthetic_audio):
        with open(synthetic_audio, "rb") as f:
            r = flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "-5", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        assert r.status_code == 200
        assert b"entre 1 e 120" in r.data

    def test_missing_audio_file(self, flask_client):
        r = flask_client.post("/transcribe", data={"interval_seconds": "7"}, content_type="multipart/form-data")
        assert r.status_code == 200
        assert "Selecione um arquivo".encode() in r.data

    def test_invalid_provider_filtered_out(self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch):
        from prompt_builder import DEFAULT_PROVIDERS
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels", "provedor-inventado"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        assert "provedor-inventado" not in app_module._JOBS[job_id]["providers"]
        assert set(app_module._JOBS[job_id]["providers"]).issubset(set(DEFAULT_PROVIDERS))

    def test_unknown_job_id_returns_404(self, flask_client):
        assert flask_client.get("/job/nao-existe/prompt").status_code == 404
        assert flask_client.get("/job/nao-existe/status").status_code == 404
        assert flask_client.get("/job/nao-existe/download").status_code == 404
        assert flask_client.get("/job/nao-existe/transcribing").status_code == 404
        assert flask_client.get("/job/nao-existe/transcribing-status").status_code == 404
        assert flask_client.get("/job/nao-existe/status-page").status_code == 404


class TestAtualizarProvidersSemRetranscrever:
    """`/job/<id>/atualizar-providers` -- trocar os bancos marcados DEPOIS
    de já ter transcrito, remontando só o texto do prompt (passo 2) com a
    transcrição que já está guardada em `job["segments"]`, sem chamar o
    Whisper de novo."""

    def _job_pronto(self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch, providers=("pexels",)):
        chamadas_transcricao = []

        def transcricao_contada(*a, **k):
            chamadas_transcricao.append(1)
            return sample_pt_segments

        monkeypatch.setattr(app_module, "transcribe_audio", transcricao_contada)
        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": list(providers), "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})
        assert len(chamadas_transcricao) == 1  # confirma que transcreveu exatamente uma vez até aqui
        return job_id, chamadas_transcricao

    def test_troca_os_providers_do_job(self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch):
        job_id, _ = self._job_pronto(app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch, providers=["pexels"])
        r = flask_client.post(f"/job/{job_id}/atualizar-providers", data={"providers": ["pixabay", "mixkit"]})
        assert r.status_code == 302
        assert app_module._JOBS[job_id]["providers"] == ["pixabay", "mixkit"]

    def test_remonta_o_prompt_sem_chamar_o_whisper_de_novo(self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch):
        job_id, chamadas_transcricao = self._job_pronto(app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch, providers=["pexels"])
        prompt_antes = app_module._JOBS[job_id]["prompt"]

        flask_client.post(f"/job/{job_id}/atualizar-providers", data={"providers": ["magnific", "vistacreate"]})

        assert len(chamadas_transcricao) == 1  # continua em 1 -- não transcreveu de novo
        prompt_depois = app_module._JOBS[job_id]["prompt"]
        assert prompt_depois != prompt_antes  # o prompt mudou (bancos novos aparecem nele)
        assert "magnific" in prompt_depois.lower() or "vistacreate" in prompt_depois.lower()

    def test_filtra_provider_invalido_da_lista_nova(self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch):
        job_id, _ = self._job_pronto(app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch, providers=["pexels"])
        flask_client.post(f"/job/{job_id}/atualizar-providers", data={"providers": ["pixabay", "provedor-inventado"]})
        assert app_module._JOBS[job_id]["providers"] == ["pixabay"]

    def test_nenhum_provider_marcado_mantem_o_que_tinha(self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch):
        job_id, _ = self._job_pronto(app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch, providers=["pexels", "pixabay"])
        r = flask_client.post(f"/job/{job_id}/atualizar-providers", data={})  # nada marcado
        assert r.status_code == 302
        assert app_module._JOBS[job_id]["providers"] == ["pexels", "pixabay"]  # não mexeu

    def test_job_sem_transcricao_pronta_da_erro_amigavel(self, app_module, flask_client):
        job_id = "job-sem-segments"
        app_module._JOBS[job_id] = {"job_id": job_id, "status": "transcrevendo"}  # sem "segments"
        r = flask_client.post(f"/job/{job_id}/atualizar-providers", data={"providers": ["pexels"]})
        assert r.status_code == 400
        assert "transcri" in r.data.decode("utf-8").lower()

    def test_job_inexistente_retorna_404(self, flask_client):
        r = flask_client.post("/job/nao-existe/atualizar-providers", data={"providers": ["pexels"]})
        assert r.status_code == 404

    def test_pagina_do_prompt_mostra_a_secao_de_trocar_providers(self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch):
        job_id, _ = self._job_pronto(app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch, providers=["pexels"])
        r = flask_client.get(f"/job/{job_id}/prompt")
        html = r.data.decode("utf-8")
        assert "atualizar-providers" in html
        assert "pixabay" in html  # os outros bancos aparecem como opção, mesmo não marcados


class TestStatusPagesAndApis:
    """Cobre as páginas/endpoints de progresso que a happy-path não passa
    diretamente por (ela vai só até a página do prompt e depois direto
    pro download, sem parar nas páginas intermediárias de status)."""

    def test_transcribing_page_and_api(self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch):
        # transcrição deliberadamente lenta, pra dar tempo de checar as
        # páginas de status ENQUANTO ainda está "transcrevendo".
        def slow_transcribe(*a, **k):
            time.sleep(0.5)
            return sample_pt_segments
        monkeypatch.setattr(app_module, "transcribe_audio", slow_transcribe)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]

        r = flask_client.get(f"/job/{job_id}/transcribing")
        assert r.status_code == 200
        assert b"Transcrevendo" in r.data

        r_api = flask_client.get(f"/job/{job_id}/transcribing-status")
        assert r_api.status_code == 200
        assert r_api.get_json()["status"] in ("transcrevendo", "aguardando_json")

        _wait_for_status(app_module, job_id, {"aguardando_json"})

    def test_result_status_page_and_api(self, app_module, flask_client, synthetic_audio, synthetic_clips, sample_pt_segments, monkeypatch):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            def __init__(self, provider):
                class FakeSession:
                    def close(inner_self):
                        pass
                self.session = FakeSession()

            def search_all(self, query=None, category=None, max_pages=1):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "clip.mp4")
                shutil.copy(synthetic_clips["exact_green"], dest)
                return dest

        import video_assembler
        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeClient(p)
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "x"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _confirm_all_segments_auto(app_module, flask_client, job_id)

        # página e API de status durante/depois da montagem
        r = flask_client.get(f"/job/{job_id}/status-page")
        assert r.status_code == 200
        assert "Montando o v".encode() in r.data

        r_api = flask_client.get(f"/job/{job_id}/status")
        assert r_api.status_code == 200
        assert "status" in r_api.get_json()

        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido"

        r_final = flask_client.get(f"/job/{job_id}/status")
        assert r_final.get_json()["status"] == "concluido"

    def test_download_before_ready_returns_404(self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        # ainda nao submeteu o JSON -> vídeo nao existe -> 404
        r = flask_client.get(f"/job/{job_id}/download")
        assert r.status_code == 404


class TestErrorPaths:
    """Cobre os caminhos de erro que interrompem o pipeline no meio —
    transcrição falhando de verdade, e montagem de vídeo falhando de
    verdade (não só JSON inválido, que já é coberto em TestFullPipeline).
    """

    def test_transcription_failure_sets_error_status(self, app_module, flask_client, synthetic_audio, monkeypatch):
        from whisper_transcribe import TranscriptionError

        def failing_transcribe(*a, **k):
            raise TranscriptionError("simulado: áudio corrompido")
        monkeypatch.setattr(app_module, "transcribe_audio", failing_transcribe)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"erro_transcricao"})

        assert "corrompido" in app_module._JOBS[job_id]["error"]

        r = flask_client.get(f"/job/{job_id}/transcribing-status")
        assert r.get_json()["status"] == "erro_transcricao"

    def test_video_assembly_failure_returns_to_editor_with_clear_message(self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch):
        """Comportamento novo: em vez de travar num status "erro" sem
        saída, uma falha de montagem volta pro editor (pronto_para_editar)
        com uma mensagem clara — a pessoa pode trocar a fonte do trecho
        problemático e mandar montar de novo, sem precisar recomeçar o
        processo inteiro."""
        from video_assembler import VideoAssemblyError

        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        def failing_assemble(*a, **k):
            raise VideoAssemblyError("Trecho 1: nenhum vídeo encontrado")
        monkeypatch.setattr(app_module, "assemble_video", failing_assemble)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "x"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _confirm_all_segments_auto(app_module, flask_client, job_id)

        _wait_for_status(app_module, job_id, {"pronto_para_editar"}, timeout=15)
        assert "Trecho 1" in app_module._JOBS[job_id]["assembly_error"]
        assert "status" not in app_module._JOBS[job_id] or app_module._JOBS[job_id]["status"] != "erro"

        r = flask_client.get(f"/job/{job_id}/status")
        data = r.get_json()
        assert data["status"] == "pronto_para_editar"
        assert "Trecho 1" in data["assembly_error"]

        # a pagina do editor mostra o aviso, com o trecho especifico
        r2 = flask_client.get(f"/job/{job_id}/edit-segments?modo=classico")
        assert r2.status_code == 200
        assert "montagem anterior falhou".encode() in r2.data
        assert "Trecho 1".encode() in r2.data

    def test_assembly_error_cleared_on_successful_retry(self, app_module, flask_client, synthetic_audio, synthetic_clips, sample_pt_segments, monkeypatch):
        """Depois de uma falha, se a pessoa trocar a fonte e confirmar de
        novo com sucesso, a mensagem de erro antiga não deve continuar
        aparecendo."""
        from video_assembler import VideoAssemblyError

        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock"
        })

        call_count = {"n": 0}

        def flaky_assemble(*a, **k):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise VideoAssemblyError("Trecho 1: falha simulada")
            # segunda tentativa: sucesso de verdade, usando o caminho legado
            k["get_client_fn"] = lambda p: _FakeWorkingClient()
            return _original_assemble(*a, **k)

        class FakeVideo:
            id = "v1"
            premium = False

        class _FakeWorkingClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(synthetic_clips["exact_green"], dest)
                return dest

        import video_assembler
        _original_assemble = video_assembler.assemble_video
        monkeypatch.setattr(app_module, "assemble_video", flaky_assemble)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "x"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"}, timeout=15)
        assert "assembly_error" in app_module._JOBS[job_id]
        assert app_module._JOBS[job_id]["assembly_error"]

        # segunda tentativa -- confirma de novo
        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=15)
        assert app_module._JOBS[job_id]["status"] == "concluido"
        assert not app_module._JOBS[job_id].get("assembly_error")


class TestSettingsPage:
    def test_get_settings_shows_current_config(self, flask_client, tmp_path, monkeypatch):
        import site_config
        monkeypatch.setattr(site_config, "CONFIG_PATH", str(tmp_path / "site_config.json"))

        r = flask_client.get("/settings")
        assert r.status_code == 200
        assert "Configura".encode() in r.data
        assert b"16:9" in r.data

    def test_save_valid_settings_persists_and_shows_success(self, flask_client, tmp_path, monkeypatch):
        import site_config
        config_path = str(tmp_path / "site_config.json")
        monkeypatch.setattr(site_config, "CONFIG_PATH", config_path)

        r = flask_client.post("/settings", data={
            "orientation": "9:16",
            "export_quality": "720p",
            "clip_trim_position": "middle",
            "provider_priority": ["mixkit", "pexels", "pixabay", "magnific", "vistacreate", "animepexels", "wikipedia"],
            "pexels_api_fallback_to_browser": "on",
            "magnific_only_free": "on",
            "browser_visible": "on",
            "browser_mode": "close_each_download",
        })
        assert r.status_code == 200
        assert "salva".encode() in r.data

        saved = site_config.load_site_config(config_path)
        assert saved["orientation"] == "9:16"
        assert saved["export_quality"] == "720p"
        assert saved["clip_trim_position"] == "middle"
        assert saved["provider_priority"][0] == "mixkit"
        assert saved["browser_mode"] == "close_each_download"
        assert saved["browser_visible"] is True
        assert saved["browser_shared_across_providers"] is False

    def test_save_settings_evitar_repeticao_clipes(self, flask_client, tmp_path, monkeypatch):
        import site_config
        config_path = str(tmp_path / "site_config.json")
        monkeypatch.setattr(site_config, "CONFIG_PATH", config_path)

        r = flask_client.post("/settings", data={"evitar_repeticao_clipes": "on"})
        assert r.status_code == 200
        assert site_config.load_site_config(config_path)["evitar_repeticao_clipes"] is True

        r2 = flask_client.post("/settings", data={})  # checkbox desmarcada -- não vem no form
        assert r2.status_code == 200
        assert site_config.load_site_config(config_path)["evitar_repeticao_clipes"] is False

    def test_conflicting_shared_browser_and_close_each_download_shows_error(self, flask_client, tmp_path, monkeypatch):
        import site_config
        monkeypatch.setattr(site_config, "CONFIG_PATH", str(tmp_path / "site_config.json"))

        r = flask_client.post("/settings", data={
            "orientation": "16:9",
            "provider_priority": ["pexels", "pixabay", "magnific", "mixkit", "vistacreate", "animepexels", "wikipedia"],
            "browser_shared_across_providers": "on",
            "browser_mode": "close_each_download",
        })
        assert r.status_code == 200
        assert "compartilhado".encode() in r.data

    def test_unchecked_checkboxes_save_as_false(self, flask_client, tmp_path, monkeypatch):
        import site_config
        config_path = str(tmp_path / "site_config.json")
        monkeypatch.setattr(site_config, "CONFIG_PATH", config_path)

        # nenhum checkbox marcado -> navegadores HTML não enviam o campo
        # no form data quando desmarcado; a rota precisa tratar isso como False.
        r = flask_client.post("/settings", data={
            "orientation": "16:9",
            "provider_priority": ["pexels", "pixabay", "magnific", "mixkit", "vistacreate", "animepexels", "wikipedia"],
            "browser_mode": "reuse_session",
        })
        assert r.status_code == 200
        saved = site_config.load_site_config(config_path)
        assert saved["browser_visible"] is False
        assert saved["pexels_api_fallback_to_browser"] is False
        assert saved["browser_shared_across_providers"] is False

    def test_invalid_settings_shows_error_not_500(self, flask_client, tmp_path, monkeypatch):
        import site_config
        monkeypatch.setattr(site_config, "CONFIG_PATH", str(tmp_path / "site_config.json"))

        r = flask_client.post("/settings", data={
            "orientation": "16:9",
            "provider_priority": ["pexels", "pixabay"],  # incompleto de propósito
            "browser_mode": "reuse_session",
        })
        assert r.status_code == 200
        assert b"faltando" in r.data


class TestExtendedJsonSchema:
    """Cobre o schema novo do JSON (envelope com segments + on_screen_text
    por segmento + soundtrack_suggestion no nível raiz), de ponta a ponta
    pela rota real do Flask."""

    def test_new_envelope_format_with_on_screen_text_and_soundtrack(
        self, app_module, flask_client, synthetic_audio, synthetic_clips, sample_pt_segments, monkeypatch
    ):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(synthetic_clips["exact_green"], dest)
                return dest

        import video_assembler
        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeClient()
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps({
            "segments": [{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "sunrise", "on_screen_text": "Bem-vindo"}],
            "soundtrack_suggestion": "instrumental calmo",
        })
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _confirm_all_segments_auto(app_module, flask_client, job_id)

        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")
        assert app_module._JOBS[job_id]["soundtrack_suggestion"] == "instrumental calmo"
        assert app_module._JOBS[job_id]["video_segments"][0]["on_screen_text"] == "Bem-vindo"

        r = flask_client.get(f"/job/{job_id}/status-page")
        assert "instrumental calmo".encode() in r.data

    def test_legacy_bare_list_format_still_works(
        self, app_module, flask_client, synthetic_audio, synthetic_clips, sample_pt_segments, monkeypatch
    ):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(synthetic_clips["exact_green"], dest)
                return dest

        import video_assembler
        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeClient()
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        # formato ANTIGO: lista direto, sem envelope -- ainda precisa funcionar
        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "sunrise"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _confirm_all_segments_auto(app_module, flask_client, job_id)

        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")
        assert app_module._JOBS[job_id].get("soundtrack_suggestion") is None


class TestMusicUpload:
    def test_uploaded_music_is_mixed_into_final_video(self, app_module, flask_client, sample_pt_segments, monkeypatch, tmp_path):
        import re

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=duration=9.469", "-loglevel", "error", audio_path], check=True)
        music_path = str(tmp_path / "music.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=9.469", "-loglevel", "error", music_path], check=True)
        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=9.469",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import video_assembler
        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeClient()
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(audio_path, "rb") as f_audio, open(music_path, "rb") as f_music:
            flask_client.post(
                "/transcribe",
                data={"audio": (f_audio, "a.wav"), "music": (f_music, "m.wav"), "music_volume": "0.5",
                      "interval_seconds": "7", "language": "pt", "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        assert app_module._JOBS[job_id]["music_path"] is not None
        assert app_module._JOBS[job_id]["music_volume"] == 0.5

        _wait_for_status(app_module, job_id, {"aguardando_json"})
        ai_response = json.dumps({"segments": [{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "x"}]})
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _confirm_all_segments_auto(app_module, flask_client, job_id)

        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")

        output_path = app_module._JOBS[job_id]["output_path"]
        result = subprocess.run(["ffmpeg", "-i", output_path, "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
        match = re.search(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", result.stderr)
        assert match and float(match.group(1)) > -50, "narração era silenciosa; se o final também está silencioso, a trilha não foi mixada"

    def test_no_music_uploaded_does_not_break_pipeline(self, app_module, flask_client, synthetic_audio, synthetic_clips, sample_pt_segments, monkeypatch):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(synthetic_clips["exact_green"], dest)
                return dest

        import video_assembler
        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeClient()
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        assert app_module._JOBS[job_id]["music_path"] is None
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "x"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _confirm_all_segments_auto(app_module, flask_client, job_id)
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")


class TestSegmentEditor:
    """Cobre o editor de segmentos: a página aparece entre 'colar JSON' e
    'montar', preservando on_screen_text quando não editado, e as trocas
    manuais de fonte (upload de arquivo, colar link) realmente mudam o
    que é usado na montagem — não só o texto/provedor.
    """

    def test_submit_json_redirects_to_editor_instead_of_assembling_directly(
        self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch
    ):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "sunrise"}])
        r = flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        assert r.status_code == 302
        assert "fetching-previews" in r.headers["Location"]
        assert app_module._JOBS[job_id]["status"] != "montando", "não deveria ter começado a montar antes de confirmar o editor"

        _wait_for_status(app_module, job_id, {"pronto_para_editar", "erro"})

        r2 = flask_client.get(f"/job/{job_id}/edit-segments?modo=classico")
        assert r2.status_code == 200
        assert "Timeline".encode() in r2.data

    def test_manual_local_file_override_is_used_instead_of_search(
        self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch, tmp_path
    ):
        """Confirma que, ao escolher 'usar um arquivo do meu computador'
        pra um segmento, o conteúdo do arquivo enviado é o que aparece
        no vídeo final — não o resultado de uma busca."""
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        # clipe VERMELHO que NUNCA deveria aparecer (representaria o resultado da busca automática)
        search_result_clip = str(tmp_path / "search_result.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=9.469",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", search_result_clip], check=True,
        )

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(search_result_clip, dest)
                return dest

        import video_assembler
        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeClient()
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "sunrise"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})

        # arquivo VERDE que o usuário está subindo manualmente pra esse segmento
        my_own_video = str(tmp_path / "meu_video.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=320x240:rate=25:duration=9.469",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", my_own_video], check=True,
        )

        with open(my_own_video, "rb") as f_video:
            flask_client.post(
                f"/job/{job_id}/confirm-segments",
                data={"seg_0_source_mode": "upload", "seg_0_file": (f_video, "meu_video.mp4")},
                content_type="multipart/form-data",
            )

        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")

        output_path = app_module._JOBS[job_id]["output_path"]
        frame = output_path + "_check.png"
        subprocess.run(["ffmpeg", "-y", "-ss", "4", "-i", output_path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
        from PIL import Image
        img = Image.open(frame).convert("RGB")
        w, h = img.size
        r, g, b = img.getpixel((w // 2, h // 2))
        assert g > 100 and r < 50, f"deveria ser o vídeo VERDE que o usuário subiu, não o vermelho da busca (RGB={r},{g},{b})"

    def test_manual_url_override_is_used_instead_of_search(
        self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch, tmp_path
    ):
        """O mesmo teste acima, mas colando um link direto em vez de
        subir um arquivo."""
        import http.server
        import threading

        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        my_video_path = tmp_path / "meu_video.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=320x240:rate=25:duration=9.469",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", str(my_video_path)], check=True,
        )
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp_path), **k)
        server = http.server.HTTPServer(("localhost", 0), handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            search_result_clip = str(tmp_path / "search_result.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=9.469",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", search_result_clip], check=True,
            )

            class FakeVideo:
                id = "v1"
                premium = False

            class FakeClient:
                session = type("S", (), {"close": lambda self: None})()

                def search_all(self, query=None, category=None, max_pages=1, **kw):
                    return [FakeVideo()]

                def download_video(self, video, output_dir, **kw):
                    os.makedirs(output_dir, exist_ok=True)
                    dest = os.path.join(output_dir, "d.mp4")
                    shutil.copy(search_result_clip, dest)
                    return dest

            import video_assembler
            original_assemble = video_assembler.assemble_video

            def patched_assemble(*a, **k):
                k["get_client_fn"] = lambda p: FakeClient()
                return original_assemble(*a, **k)

            monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

            with open(synthetic_audio, "rb") as f:
                flask_client.post(
                    "/transcribe",
                    data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                          "providers": ["pexels"], "extra_instructions": ""},
                    content_type="multipart/form-data",
                )
            job_id = list(app_module._JOBS.keys())[-1]
            _wait_for_status(app_module, job_id, {"aguardando_json"})

            ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "sunrise"}])
            flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})

            flask_client.post(
                f"/job/{job_id}/confirm-segments",
                data={"seg_0_source_mode": "url", "seg_0_url": f"http://localhost:{port}/meu_video.mp4"},
            )

            _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
            assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")

            output_path = app_module._JOBS[job_id]["output_path"]
            frame = output_path + "_check.png"
            subprocess.run(["ffmpeg", "-y", "-ss", "4", "-i", output_path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            from PIL import Image
            img = Image.open(frame).convert("RGB")
            w, h = img.size
            r, g, b = img.getpixel((w // 2, h // 2))
            assert b > 100 and r < 50, f"deveria ser o vídeo AZUL do link colado, não o vermelho da busca (RGB={r},{g},{b})"
        finally:
            server.shutdown()

    def test_on_screen_text_preserved_when_not_edited(
        self, app_module, flask_client, synthetic_audio, synthetic_clips, sample_pt_segments, monkeypatch
    ):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(synthetic_clips["exact_green"], dest)
                return dest

        import video_assembler
        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeClient()
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps({
            "segments": [{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "x", "on_screen_text": "Texto original"}],
        })
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})

        # confirma sem editar nada (form vazio) -- on_screen_text deveria ser preservado
        flask_client.post(f"/job/{job_id}/confirm-segments", data={})

        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")
        assert app_module._JOBS[job_id]["video_segments"][0]["on_screen_text"] == "Texto original"


class TestTimelineWithRealPreviews:
    """Cobre o fluxo da prévia RÁPIDA (busca sem baixar nada, usando o
    thumbnail do próprio provedor): a página da timeline renderiza com
    a URL remota, a forma de onda real é servida, e a montagem final
    "fixa" o resultado exato visto na prévia pra vídeo (via link de
    post) — pra foto, sem suporte a fixar por URL, a montagem faz uma
    busca nova."""

    def test_full_flow_shows_thumbnail_url_and_waveform(
        self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch
    ):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        search_calls = {"count": 0}

        def fake_fetch_preview_lightweight(segment, **kwargs):
            search_calls["count"] += 1
            return {
                "ok": True, "thumbnail_url": "https://images.pexels.com/videos/123/tiny.jpg",
                "result_url": "https://www.pexels.com/video/sunrise-123/", "label": "Sunrise", "error": None,
            }

        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", fake_fetch_preview_lightweight)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "sunrise"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        assert search_calls["count"] == 1, "deveria ter buscado a prévia exatamente 1 vez pro único segmento"

        r = flask_client.get(f"/job/{job_id}/edit-segments?modo=classico")
        assert r.status_code == 200
        assert b"https://images.pexels.com/videos/123/tiny.jpg" in r.data, "deveria usar a URL remota direto, sem rota de thumbnail propria"

        r_wave = flask_client.get(f"/job/{job_id}/waveform-image")
        assert r_wave.status_code == 200
        assert r_wave.content_type.startswith("image/")

    def test_video_segment_unchanged_runs_a_real_search_not_a_pin(
        self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch, tmp_path
    ):
        """Sem editar nada, o trecho precisa passar pela busca DE
        VERDADE na montagem (com direito a completar a duração com
        cenas extras, e evitar cenas já usadas em outros trechos) — não
        fixar cegamente o mesmo resultado da prévia via link, o que
        pulava por completo essas duas melhorias pra praticamente todo
        trecho não editado manualmente (a maioria, numa narração normal)."""
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        real_clip = str(tmp_path / "real_clip.mp4")  # AZUL — o que a busca de verdade encontra
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=320x240:rate=25:duration=9.469",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", real_clip], check=True,
        )

        def fake_fetch_preview_lightweight(segment, **kwargs):
            return {
                "ok": True, "thumbnail_url": "https://images.pexels.com/videos/999/tiny.jpg",
                "result_url": "https://www.pexels.com/video/algo-999/", "label": "x", "error": None,
                "video_preview_url": None, "provider": "pexels",
            }

        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", fake_fetch_preview_lightweight)

        search_calls = []

        class FakeVideoFound:
            id = "999"
            premium = False

        class FakeFinalClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                search_calls.append(query)
                return [FakeVideoFound()]

            def get_video_by_url(self, url):
                raise AssertionError("não deveria mais fixar por link — deveria buscar de verdade")

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(real_clip, dest)
                return dest

        import video_assembler
        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeFinalClient()
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "sunrise"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")
        assert search_calls == ["sunrise"], "deveria ter feito uma busca de verdade com o termo do segmento, não fixado um link"

        output_path = app_module._JOBS[job_id]["output_path"]
        frame = output_path + "_check.png"
        subprocess.run(["ffmpeg", "-y", "-ss", "4", "-i", output_path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
        from PIL import Image
        img = Image.open(frame).convert("RGB")
        w, h = img.size
        r, g, b = img.getpixel((w // 2, h // 2))
        assert b > 150 and r < 50, f"deveria ser o clipe encontrado pela busca de verdade (RGB={r},{g},{b})"

    def test_image_segment_always_does_fresh_search_at_confirm(
        self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch, tmp_path
    ):
        """Foto não tem mecanismo de "fixar por link" (só vídeo tem) —
        mesmo sem editar nada, a montagem faz uma busca de foto nova."""
        from PIL import Image as PILImage

        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)
        # este teste usa o caminho LEGADO (get_client_fn) pra injetar seu
        # próprio cliente de foto — a checagem antecipada de
        # PEXELS_API_KEYS não sabe disso, então precisa ser dispensada
        # aqui pra não bloquear o que o teste está de fato testando.
        monkeypatch.setattr(app_module, "photo_api_configuration_error", lambda **kwargs: None)

        final_photo = str(tmp_path / "final_photo.jpg")
        PILImage.new("RGB", (400, 300), (0, 200, 0)).save(final_photo)  # VERDE

        def fake_fetch_preview_lightweight(segment, **kwargs):
            return {
                "ok": True, "thumbnail_url": "https://images.pexels.com/photos/1/tiny.jpg",
                "result_url": "https://www.pexels.com/photo/algo-1/", "label": "x", "error": None,
            }

        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", fake_fetch_preview_lightweight)

        photo_search_calls = []

        class FakePhoto:
            id = "1"

        class FakeFinalClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_photos_all(self, query=None, max_pages=1, **kw):
                photo_search_calls.append(query)
                return [FakePhoto()]

            def download_photo(self, photo, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "p.jpg")
                shutil.copy(final_photo, dest)
                return dest

        import video_assembler
        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeFinalClient()
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps({"segments": [
            {"start": 0.0, "end": 9.469, "provider": "pexels", "query": "vintage camera", "media_type": "image"},
        ]})
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")
        assert photo_search_calls == ["vintage camera"], "deveria ter buscado foto de novo (sem suporte a fixar por link)"



class TestWordCaptions:
    """Cobre o fluxo de legendas 'uma palavra por vez', de ponta a
    ponta: checkbox liga timestamps por palavra na transcrição, a
    montagem gera as DUAS versões (com e sem legenda), e as duas rotas
    de download servem arquivos de fato diferentes."""

    def test_full_flow_generates_both_versions_and_they_differ_visually(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        import hashlib
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=6", "-loglevel", "error", audio_path], check=True)

        def fake_transcribe(path, model_size="base", language=None, word_timestamps=False, device="auto"):
            segs = [{"start": 0.0, "end": 6.0, "text": "Olá mundo bonito"}]
            if word_timestamps:
                segs[0]["words"] = [
                    {"word": "Olá", "start": 0.5, "end": 1.2},
                    {"word": "mundo", "start": 1.5, "end": 2.3},
                    {"word": "bonito", "start": 3.0, "end": 4.0},
                ]
            return segs

        monkeypatch.setattr(app_module, "transcribe_audio", fake_transcribe)

        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=640x360:rate=25:duration=6",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import video_assembler
        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeClient()
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": "", "add_word_captions": "on"},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})
        assert "word_timestamps" in app_module._JOBS[job_id]

        ai_response = json.dumps([{"start": 0.0, "end": 6.0, "provider": "pexels", "query": "x"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})
        flask_client.post(f"/job/{job_id}/confirm-segments", data={})

        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=40)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")
        assert "captioned_output_path" in app_module._JOBS[job_id]

        r1 = flask_client.get(f"/job/{job_id}/download")
        r2 = flask_client.get(f"/job/{job_id}/download-captioned")
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.data != r2.data

        def _frame_hash_from_bytes(data, t, tag):
            path = str(tmp_path / f"dl_{tag}.mp4")
            with open(path, "wb") as f:
                f.write(data)
            frame = str(tmp_path / f"dl_{tag}_frame.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            return hashlib.md5(Image.open(frame).convert("RGB").tobytes()).hexdigest()

        hash_normal = _frame_hash_from_bytes(r1.data, 1.0, "normal")
        hash_captioned = _frame_hash_from_bytes(r2.data, 1.0, "captioned")
        assert hash_normal != hash_captioned, "durante a palavra 'Olá', a versão legendada deveria diferir visualmente da normal"

    def test_without_checkbox_no_captioned_version_is_generated(
        self, app_module, flask_client, synthetic_audio, synthetic_clips, sample_pt_segments, monkeypatch
    ):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(synthetic_clips["exact_green"], dest)
                return dest

        import video_assembler
        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeClient()
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},  # sem add_word_captions
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        assert app_module._JOBS[job_id]["add_word_captions"] is False
        _wait_for_status(app_module, job_id, {"aguardando_json"})
        assert "word_timestamps" not in app_module._JOBS[job_id]

        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "x"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})
        flask_client.post(f"/job/{job_id}/confirm-segments", data={})

        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido"
        assert "captioned_output_path" not in app_module._JOBS[job_id]

        r = flask_client.get(f"/job/{job_id}/download-captioned")
        assert r.status_code == 404


class TestMediaTypeSurvivesEditorRoundTrip:
    """Regressão: `media_type='image'` sugerido pela IA precisa
    sobreviver tanto à pré-busca de prévias quanto à reconstrução dos
    segmentos no editor (`confirm_segments`) — um bug real descartava
    esse campo silenciosamente em ambos os pontos, fazendo o site tratar
    segmentos de FOTO como se fossem de vídeo sem avisar ninguém."""

    def test_image_segment_uses_photo_search_in_preview_and_survives_editor(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=8", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 8.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "photo_api_configuration_error", lambda **kwargs: None)

        final_photo = str(tmp_path / "foto.jpg")
        Image.new("RGB", (800, 600), (255, 0, 0)).save(final_photo)
        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x360:rate=25:duration=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        video_search_calls = []
        photo_search_calls = []

        class FakeVideo:
            id = "v1"
            premium = False
            def to_dict(self):
                return {"id": "v1", "title": "dog", "thumbnail": "https://img/v1.jpg", "url": "https://x/v1"}

        class FakePhoto:
            id = "p1"
            description = "vintage camera"
            author = "someone"
            url = "https://www.pexels.com/photo/p1/"
            sizes = {"tiny": "https://img/p1_tiny.jpg"}

        class FakeClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                video_search_calls.append(query)
                return [FakeVideo()]

            def get_video_by_url(self, url):
                return FakeVideo()

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

            def search_photos_all(self, query=None, max_pages=1, **kw):
                photo_search_calls.append(query)
                return [FakePhoto()]

            def download_photo(self, photo, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "p.jpg")
                shutil.copy(final_photo, dest)
                return dest

        import video_assembler

        def fake_fetch_preview_lightweight(segment, **kwargs):
            return video_assembler.fetch_segment_preview_lightweight(segment, client_factory=_FakeFactory(FakeClient()))

        class _FakeFactory:
            """Fábrica mínima que sempre devolve o mesmo FakeClient, tanto
            pra vídeo quanto pra foto (get_photo_client)."""
            def __init__(self, client):
                self._client = client
            def get_client(self, provider):
                return self._client
            def get_photo_client(self, provider="pexels"):
                return self._client
            def close_all(self):
                pass

        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", fake_fetch_preview_lightweight)

        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeClient()
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps({"segments": [
            {"start": 0.0, "end": 4.0, "provider": "pexels", "query": "dog"},
            {"start": 4.0, "end": 8.0, "provider": "pexels", "query": "vintage camera", "media_type": "image"},
        ]})
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        # a PRÉVIA do segmento de imagem precisa ter usado busca de FOTO, não vídeo
        assert photo_search_calls == ["vintage camera"], (
            f"a pré-busca deveria ter usado search_photos_all pro segmento de imagem, "
            f"chamadas de vídeo={video_search_calls} chamadas de foto={photo_search_calls}"
        )
        assert app_module._JOBS[job_id]["segment_previews"][1]["ok"] is True

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")
        # a montagem faz uma busca de foto NOVA (sem suporte a fixar por link) -> mais uma chamada
        assert photo_search_calls.count("vintage camera") == 2

        # media_type precisa ter sobrevivido à reconstrução do editor
        final_segments = app_module._JOBS[job_id]["video_segments"]
        assert final_segments[0]["media_type"] == "video"
        assert final_segments[1]["media_type"] == "image", "media_type='image' deveria ter sobrevivido ao confirm-segments"

    def test_timeline_shows_photo_indicator_for_image_segments(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        """A auditoria da reconstrução do editor também revelou que a UI
        não mostrava de nenhum jeito quando um segmento era uma foto —
        o dropdown de banco parecia normal mesmo pra segmentos onde só
        Pexels funciona de verdade. Confirma que o aviso aparece."""
        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=4", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 4.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview", lambda segment, downloads_dir, **kw: {
            "ok": False, "raw_path": None, "kind": None, "error": "mock"
        })

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps({"segments": [
            {"start": 0.0, "end": 4.0, "provider": "pexels", "query": "vintage camera", "media_type": "image"},
        ]})
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        r = flask_client.get(f"/job/{job_id}/edit-segments?modo=classico")
        assert r.status_code == 200
        assert "A IA sugeriu uma FOTO".encode() in r.data
        assert "📷".encode() in r.data

    def test_provider_incompatible_with_image_is_normalized_back_to_pexels(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        """Se alguém trocar o banco de um segmento de foto pra algo sem
        suporte a fotos (via o dropdown do editor, sem perceber que é um
        segmento de imagem), o site corrige de volta pra Pexels em vez
        de salvar uma combinação impossível."""
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=4", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 4.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "photo_api_configuration_error", lambda **kwargs: None)
        monkeypatch.setattr(app_module, "fetch_segment_preview", lambda segment, downloads_dir, **kw: {
            "ok": False, "raw_path": None, "kind": None, "error": "mock"
        })

        image_path = str(tmp_path / "foto.jpg")
        Image.new("RGB", (400, 300), (0, 0, 255)).save(image_path)

        photo_calls = []

        class FakePhoto:
            id = "p1"

        class FakeClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_photos_all(self, query=None, max_pages=1, **kw):
                photo_calls.append(query)
                return [FakePhoto()]

            def download_photo(self, photo, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "p.jpg")
                shutil.copy(image_path, dest)
                return dest

        import video_assembler
        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeClient()
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps({"segments": [
            {"start": 0.0, "end": 4.0, "provider": "pexels", "query": "vintage camera", "media_type": "image"},
        ]})
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        # usuario troca o banco pra pixabay sem perceber que e um segmento de foto
        flask_client.post(f"/job/{job_id}/confirm-segments", data={"seg_0_provider": "pixabay", "seg_0_source_mode": "auto"})
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)

        final_segments = app_module._JOBS[job_id]["video_segments"]
        assert final_segments[0]["provider"] == "pexels", "deveria ter sido normalizado de volta pra pexels"
        assert final_segments[0]["media_type"] == "image"
        assert photo_calls == ["vintage camera"], "a busca de foto deveria ter sido chamada mesmo com pixabay selecionado por engano"


class TestProgressivePreviewFetching:
    """A página de "buscando prévias" deve mostrar cada thumbnail assim
    que ela fica pronta, não só uma barra de porcentagem sem nenhum
    conteúdo visual até tudo terminar de uma vez."""

    def test_previews_become_visible_incrementally_not_only_at_the_end(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        import time as _time
        import site_config as site_config_module

        # forca concorrencia=1 pra esse teste especifico: ele testa o
        # MECANISMO de revelacao progressiva (uma previa aparece antes da
        # outra terminar), nao a paralelizacao em si (que tem seu proprio
        # teste dedicado, TestPreviewFetchingConcurrency).
        config_path = str(tmp_path / "site_config.json")
        monkeypatch.setattr(site_config_module, "CONFIG_PATH", config_path)
        site_config_module.save_site_config({"preview_fetch_concurrency": 1}, config_path)

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=6", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 6.0, "text": "teste"}])

        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        class FakeVideo:
            id = "v1"
            premium = False
            def to_dict(self):
                return {"id": "v1", "title": "x", "thumbnail": "https://img/v1.jpg", "url": "https://x"}

        class FakeSlowClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                _time.sleep(0.5)  # simula uma busca demorada
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "toolkit"))
        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeSlowClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        class FakeChromeSession:
            def __init__(self, headless, headers=None):
                pass
            def close(self):
                pass
        monkeypatch.setattr(browser_session, "ChromeSession", FakeChromeSession)

        # a fixture app_module já mocka fetch_segment_preview_lightweight
        # pra devolver "sem prévia" instantaneamente (proteção padrão
        # contra rede/Chrome de verdade) — esse teste PRECISA da função
        # real de verdade (só com os clientes de nível mais baixo
        # mockados acima) pra medir o timing de forma significativa.
        import video_assembler
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", video_assembler.fetch_segment_preview_lightweight)

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps({"segments": [
            {"start": 0.0, "end": 3.0, "provider": "pexels", "query": "a"},
            {"start": 3.0, "end": 6.0, "provider": "pexels", "query": "b"},
        ]})
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})

        # espera menos que o tempo total das duas buscas (2 x 0.5s) —
        # nesse ponto, só a primeira prévia deveria estar pronta
        _time.sleep(0.7)
        r = flask_client.get(f"/job/{job_id}/fetching-previews-status")
        data = r.get_json()
        assert data["status"] == "buscando_previas"
        assert len(data["previews"]) == 1, f"esperava exatamente 1 prévia pronta nesse ponto, tinha {len(data['previews'])}"
        assert data["previews"][0]["ok"] is True

        _wait_for_status(app_module, job_id, {"pronto_para_editar"}, timeout=10)
        r2 = flask_client.get(f"/job/{job_id}/fetching-previews-status")
        assert len(r2.get_json()["previews"]) == 2

    def test_fetching_previews_page_renders_thumbnail_grid(
        self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch
    ):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "x"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})

        r = flask_client.get(f"/job/{job_id}/fetching-previews")
        assert r.status_code == 200
        assert b"thumbs-grid" in r.data
        assert b"addThumb" in r.data


class TestPreviewFetchingConcurrency:
    """Prova, com tempo de relógio real, que a busca de prévias roda em
    PARALELO — isso resolve o gargalo relatado de "3 minutos pra começar
    a editar" com narrações de muitos trechos, já que antes cada trecho
    era buscado um de cada vez, em sequência."""

    def test_multiple_segments_are_fetched_in_parallel_not_sequentially(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        import time as _time
        import site_config as site_config_module

        config_path = str(tmp_path / "site_config.json")
        monkeypatch.setattr(site_config_module, "CONFIG_PATH", config_path)
        site_config_module.save_site_config({"preview_fetch_concurrency": 4}, config_path)

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=16", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 16.0, "text": "teste"}])

        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        SEARCH_DELAY = 0.6
        NUM_SEGMENTS = 4  # igual à concorrência configurada -> todos deveriam rodar juntos

        class FakeVideo:
            id = "v1"
            premium = False
            def to_dict(self):
                return {"id": "v1", "title": "x", "thumbnail": "https://img/v1.jpg", "url": "https://x"}

        class FakeSlowClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                _time.sleep(SEARCH_DELAY)
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "toolkit"))
        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeSlowClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        class FakeChromeSession:
            def __init__(self, headless, headers=None):
                pass
            def close(self):
                pass
        monkeypatch.setattr(browser_session, "ChromeSession", FakeChromeSession)

        import video_assembler
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", video_assembler.fetch_segment_preview_lightweight)

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "4", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        segments_json = [
            {"start": float(i * 4), "end": float((i + 1) * 4), "provider": "pexels", "query": f"termo {i}"}
            for i in range(NUM_SEGMENTS)
        ]
        t0 = _time.time()
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({"segments": segments_json})})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"}, timeout=10)
        elapsed = _time.time() - t0

        # sequencial seria ~= NUM_SEGMENTS * SEARCH_DELAY (2.4s); em
        # paralelo (concorrência >= NUM_SEGMENTS) deveria ficar perto de
        # 1x SEARCH_DELAY. Usa uma margem folgada (2x o delay de uma
        # busca) pra não ficar frágil por variação de máquina/CI.
        sequential_estimate = NUM_SEGMENTS * SEARCH_DELAY
        assert elapsed < sequential_estimate * 0.7, (
            f"buscar {NUM_SEGMENTS} segmentos levou {elapsed:.2f}s — esperava bem menos que "
            f"{sequential_estimate:.2f}s (tempo sequencial) já que devem rodar em paralelo"
        )
        assert app_module._JOBS[job_id]["status"] == "pronto_para_editar"
        assert len(app_module._JOBS[job_id]["segment_previews"]) == NUM_SEGMENTS
        assert all(p is not None and p["ok"] for p in app_module._JOBS[job_id]["segment_previews"])

    def test_default_concurrency_is_three(self):
        from site_config import DEFAULT_CONFIG
        assert DEFAULT_CONFIG["preview_fetch_concurrency"] == 3

    def test_none_placeholders_in_preview_list_do_not_crash_status_api(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        """Regressão: a lista de prévias é pré-alocada com `None` nas
        posições ainda não prontas (busca paralela conclui fora de
        ordem) — a rota de status, o editor, e a lógica de reaproveitar
        prévia no confirm precisam lidar com isso sem quebrar."""
        import time as _time

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=8", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 8.0, "text": "teste"}])

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeSlowClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                _time.sleep(1.0)  # deliberadamente lento, pra pegar o estado com None no meio
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                raise AssertionError("não deveria chegar aqui nesse teste")

        import video_assembler

        def fake_fetch_preview(segment, downloads_dir, **kwargs):
            return video_assembler.fetch_segment_preview(segment, downloads_dir, get_client_fn=lambda p: FakeSlowClient())

        monkeypatch.setattr(app_module, "fetch_segment_preview", fake_fetch_preview)

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "4", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({"segments": [
            {"start": 0.0, "end": 4.0, "provider": "pexels", "query": "a"},
            {"start": 4.0, "end": 8.0, "provider": "pexels", "query": "b"},
        ]})})

        # nesse ponto, ainda buscando (1s de delay) -> a lista tem None
        r = flask_client.get(f"/job/{job_id}/fetching-previews-status")
        assert r.status_code == 200, "a rota de status nao deveria quebrar com None na lista"

        r2 = flask_client.get(f"/job/{job_id}/thumbnail/1")
        assert r2.status_code == 404, "pedir thumbnail de um indice ainda nao pronto deveria dar 404, nao quebrar"


class TestPerfLogEndToEnd:
    """Confirma que o log de tempo por job (`timing_log.json`, pedido
    explicitamente pra ajudar a identificar gargalos) fica completo de
    ponta a ponta, pela rota Flask real e pelo caminho REAL de produção
    (site_cfg, não get_client_fn) — cobrindo transcrição, prompt, prévia
    de cada segmento, e cada etapa da montagem final."""

    def test_timing_log_has_all_pipeline_stages(self, app_module, flask_client, monkeypatch, tmp_path):
        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=6", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 6.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock"
        })

        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "3", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps({"segments": [
            {"start": 0.0, "end": 3.0, "provider": "pexels", "query": "a"},
            {"start": 3.0, "end": 6.0, "provider": "pexels", "query": "b"},
        ]})
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        log_path = os.path.join(app_module._job_dir(job_id), "timing_log.json")
        assert os.path.exists(log_path), "log deveria existir depois da pré-busca de prévias"
        data = json.load(open(log_path))
        totals = data["totals_by_category_ordered_by_time"]
        assert "transcricao" in totals
        assert "montar_prompt" in totals
        assert "previa:segmento_N:busca" in totals
        assert totals["previa:segmento_N:busca"]["count"] == 2

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")

        data2 = json.load(open(log_path))
        totals2 = data2["totals_by_category_ordered_by_time"]
        assert "montagem:segmento_N:busca_download" in totals2
        assert "montagem:segmento_N:normalizar" in totals2
        assert "montagem:concatenar" in totals2
        assert "montagem:mux_audio" in totals2
        assert totals2["montagem:segmento_N:busca_download"]["count"] == 2
        # os totais da etapa anterior (transcricao, montar_prompt, previa)
        # continuam presentes -- salvar de novo nao apaga o que ja tinha
        assert "transcricao" in totals2
        assert "previa:segmento_N:busca" in totals2

    def test_timing_log_is_fully_written_before_status_becomes_concluido(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        """Regressão de uma condição de corrida real: `job["status"]`
        virava "concluido" ANTES de `perf.save()` rodar (só no
        `finally`) — um observador externo (este teste, ou a própria
        pessoa clicando em "baixar log de tempo" assim que vê
        "concluído" na tela) podia ler o arquivo antes dele refletir a
        montagem inteira. Este teste checa a garantia de ORDEM
        diretamente: no exato instante em que o status vira "concluido"
        (checado a cada 10ms, bem mais fino que o polling normal), o
        log já precisa ter as categorias da montagem.

        Usa o caminho REAL (site_cfg, mockando o cliente do Pexels) —
        não o legado (get_client_fn), que não tem essas categorias de
        tempo conectadas.
        """
        import time as _time

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=4", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 4.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None, "provider": None
        })

        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "4", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        log_path = os.path.join(app_module._job_dir(job_id), "timing_log.json")
        flask_client.post(f"/job/{job_id}/confirm-segments", data={})

        deadline = _time.time() + 15
        seen_concluido = False
        while _time.time() < deadline:
            if app_module._JOBS[job_id]["status"] == "concluido":
                seen_concluido = True
                # NO EXATO INSTANTE em que o status vira "concluido", o
                # log ja precisa refletir a montagem inteira.
                data = json.load(open(log_path))
                totals = data["totals_by_category_ordered_by_time"]
                assert "montagem:concatenar" in totals, (
                    "log de tempo incompleto no momento em que o status virou "
                    "'concluido' -- a condição de corrida entre perf.save() e "
                    "job['status'] voltou a existir"
                )
                break
            _time.sleep(0.01)
        assert seen_concluido, "job nunca chegou a 'concluido' dentro do tempo esperado"

    def test_job_id_download_route_serves_timing_log(self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock"
        })

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "x"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        r = flask_client.get(f"/job/{job_id}/download-timing-log")
        assert r.status_code == 200
        assert r.mimetype == "application/json"


class TestAssemblyErrorSegmentPositioning:
    """A pessoa pediu explicitamente: quando a montagem falhar num
    trecho específico, a timeline deve já vir posicionada/destacada
    nesse trecho, não só mostrar uma mensagem de erro genérica."""

    def test_failed_segment_index_is_saved_and_rendered_in_editor(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        from video_assembler import VideoAssemblyError

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=12", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 12.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock"
        })

        def failing_assemble(*a, **k):
            err = VideoAssemblyError("Trecho 3: falha simulada no mixkit")
            err.segment_index = 2  # trecho 3 (exibido pra pessoa) = índice 2 (interno)
            raise err

        monkeypatch.setattr(app_module, "assemble_video", failing_assemble)

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "4", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps({"segments": [
            {"start": 0.0, "end": 4.0, "provider": "pexels", "query": "a"},
            {"start": 4.0, "end": 8.0, "provider": "pexels", "query": "b"},
            {"start": 8.0, "end": 12.0, "provider": "pexels", "query": "c"},
        ]})
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"}, timeout=15)

        assert app_module._JOBS[job_id]["assembly_error_segment_index"] == 2

        r = flask_client.get(f"/job/{job_id}/status")
        data = r.get_json()
        assert data["assembly_error_segment_index"] == 2

        r2 = flask_client.get(f"/job/{job_id}/edit-segments?modo=classico")
        assert r2.status_code == 200
        assert b'class="block has-error"' in r2.data
        assert b"errorSegmentIndex = 2" in r2.data
        assert "trecho problem\u00e1tico j\u00e1 est\u00e1 selecionado".encode() in r2.data

    def test_no_error_index_defaults_to_first_segment_selected(
        self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch
    ):
        """Quando não há erro de montagem nenhum (fluxo normal), a
        página continua selecionando o primeiro trecho por padrão."""
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock"
        })

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "x"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        r = flask_client.get(f"/job/{job_id}/edit-segments?modo=classico")
        assert r.status_code == 200
        assert b"errorSegmentIndex = null" in r.data
        assert b'class="block has-error"' not in r.data


class TestProgramMonitor:
    """"Monitor de Programa": a página de resultado tem um player de
    vídeo de verdade tocando o resultado montado, não só um link de
    download — com suporte a seek (requisições Range) e alternância
    entre a versão com/sem legenda."""

    def test_stream_route_serves_video_inline_with_range_support(
        self, app_module, flask_client, synthetic_audio, synthetic_clips, sample_pt_segments, monkeypatch
    ):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None
        })

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(synthetic_clips["exact_green"], dest)
                return dest

        import video_assembler
        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            k["get_client_fn"] = lambda p: FakeClient()
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "x"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})
        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")

        r = flask_client.get(f"/job/{job_id}/status-page")
        assert b"program-monitor-video" in r.data
        assert b"switchProgramMonitorVersion" in r.data

        r2 = flask_client.get(f"/job/{job_id}/stream")
        assert r2.status_code == 200
        assert r2.mimetype == "video/mp4"
        assert "attachment" not in (r2.headers.get("Content-Disposition") or "")

        r3 = flask_client.get(f"/job/{job_id}/stream", headers={"Range": "bytes=0-100"})
        assert r3.status_code == 206

    def test_stream_route_404s_before_job_completes(self, app_module, flask_client):
        app_module._JOBS["job-nao-pronto"] = {"job_id": "job-nao-pronto", "status": "montando"}
        r = flask_client.get("/job/job-nao-pronto/stream")
        assert r.status_code == 404

    def test_stream_captioned_route_404s_without_captioned_version(self, app_module, flask_client):
        app_module._JOBS["job-sem-legenda"] = {"job_id": "job-sem-legenda", "status": "concluido"}
        r = flask_client.get("/job/job-sem-legenda/stream-captioned")
        assert r.status_code == 404


class TestSourceMonitorFallback:
    """Regressão: quando um provedor não fornece vídeo tocável na busca
    (hoje, Pixabay), o Monitor de Origem escondia o player mas não
    mostrava NADA no lugar — o rótulo "Monitor de Origem" aparecia com
    uma área vazia embaixo, sem explicar por quê (apesar do comentário
    no código dizer que mostraria a imagem estática)."""

    def test_edit_segments_page_includes_fallback_elements(
        self, app_module, flask_client, synthetic_audio, sample_pt_segments, monkeypatch
    ):
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: sample_pt_segments)
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None
        })

        with open(synthetic_audio, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 9.469, "provider": "pexels", "query": "x"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        r = flask_client.get(f"/job/{job_id}/edit-segments?modo=classico")
        assert r.status_code == 200
        assert b"source_monitor_fallback_0" in r.data
        assert b"source_monitor_fallback_img_0" in r.data
        assert "n\u00e3o fornece pr\u00e9via em v\u00eddeo".encode() in r.data


class TestPreviewFallsBackAcrossProviders:
    """Bug real de inconsistência corrigido: a prévia leve só variava o
    termo de busca no MESMO provedor — se o banco original estivesse
    fora do ar/bloqueado, a timeline mostrava "sem prévia" mesmo quando
    a montagem final (que sempre tentou os outros bancos) daria certo.
    Agora a prévia também cai pro próximo banco da prioridade, igual a
    montagem já fazia."""

    def test_preview_falls_back_to_next_provider_and_pin_uses_correct_one(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=4", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 4.0, "text": "teste"}])

        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=magenta:size=320x240:rate=25:duration=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        class FakeVideoOk:
            id = "v99"
            premium = False

            def to_dict(self):
                return {"id": "v99", "title": "x", "thumbnail": "https://img/v99.jpg", "url": "https://pixabay.com/videos/x-v99/"}

        search_calls = []

        class FakePixabayClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                search_calls.append(query)
                return [FakeVideoOk()]

            def get_video_by_url(self, url):
                raise AssertionError("não deveria mais fixar por link — deveria buscar de verdade, começando pelo banco que a prévia já sabe que funciona")

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        class FakePexelsFailingClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                raise RuntimeError("pexels fora do ar (simulado)")

        import video_assembler

        def fake_fetch_preview(segment, downloads_dir=None, **kw):
            cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session",
                   "provider_priority": ["pexels", "pixabay", "magnific", "mixkit", "vistacreate", "animepexels", "wikipedia"]}
            factory = video_assembler.ClientFactory(cfg)
            factory._clients["pexels"] = FakePexelsFailingClient()
            factory._clients["pixabay"] = FakePixabayClient()
            return video_assembler.fetch_segment_preview_lightweight(segment, site_cfg=cfg, client_factory=factory)

        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", fake_fetch_preview)

        original_assemble = video_assembler.assemble_video

        def patched_assemble(*a, **k):
            def get_client(p):
                return FakePixabayClient() if p == "pixabay" else FakePexelsFailingClient()
            k["get_client_fn"] = get_client
            return original_assemble(*a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "4", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        preview = app_module._JOBS[job_id]["segment_previews"][0]
        assert preview["ok"] is True
        assert preview["provider"] == "pixabay"
        assert preview["original_provider"] == "pexels"

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=15)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")
        assert search_calls and set(search_calls) == {"x"}, "deveria ter buscado de verdade (via pixabay, o banco que a prévia já sabia que funciona), não fixado um link"
        assert app_module._JOBS[job_id]["video_segments"][0]["provider"] == "pixabay"


class TestJobsHistoryPage:
    """Página de histórico (`/jobs`) — antes não existia nenhuma forma
    de listar jobs passados, só quem guardou a URL conseguia voltar."""

    def test_lists_jobs_most_recent_first_with_correct_continue_link(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        import time as _time

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=4", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 4.0, "text": "teste"}])

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao_1.wav"), "interval_seconds": "4", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id_1 = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id_1, {"aguardando_json"})

        _time.sleep(0.1)

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "narracao_2.wav"), "interval_seconds": "4", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id_2 = list(app_module._JOBS.keys())[-1]

        r = flask_client.get("/jobs")
        assert r.status_code == 200
        assert b"narracao_1.wav" in r.data
        assert b"narracao_2.wav" in r.data

        pos1 = r.data.find(b"narracao_1.wav")
        pos2 = r.data.find(b"narracao_2.wav")
        assert pos2 < pos1, "job mais recente deveria aparecer primeiro na lista"
        assert b"Ver prompt" in r.data

        # a pagina nao deveria ter mutado o dicionario original do job
        assert "created_at_display" not in app_module._JOBS[job_id_1]

    def test_empty_history_shows_friendly_message(self, app_module, flask_client, monkeypatch):
        # NUNCA usar _JOBS.clear() aqui — isso destruiria de verdade os
        # jobs de OUTROS testes rodando em paralelo (mesmo motivo já
        # documentado nas fixtures: threads de background de testes
        # anteriores ainda podem estar escrevendo neles). Troca por um
        # dicionário vazio TEMPORÁRIO via monkeypatch, que é desfeito
        # automaticamente no final do teste.
        monkeypatch.setattr(app_module, "_JOBS", {})
        r = flask_client.get("/jobs")
        assert r.status_code == 200
        assert "Nenhum job ainda".encode() in r.data


class TestSourceMonitorShowsAutomatically:
    """Corrige um problema real relatado: o Monitor de Origem só
    aparecia depois de clicar em "Buscar e ver opções" — mas a prévia
    inicial de cada segmento já tem os dados necessários (thumbnail e,
    quando disponível, vídeo tocável), então clicar no bloco da
    timeline já deveria mostrar alguma coisa, sem precisar de um passo
    extra."""

    def test_initial_previews_data_available_to_javascript(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=4", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 4.0, "text": "x"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": True, "thumbnail_url": "https://img/x.jpg", "result_url": "https://x",
            "label": "teste", "error": None, "video_preview_url": "https://v/x.mp4", "provider": "pexels",
        })

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "4", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps([{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x"}])
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        r = flask_client.get(f"/job/{job_id}/edit-segments?modo=classico")
        assert r.status_code == 200
        assert b"initialPreviews" in r.data
        assert b"https://v/x.mp4" in r.data
        assert b"showInSourceMonitor(i, {" in r.data


class TestFixPersistsAcrossMultipleRetries:
    """Bug real relatado em produção: com mais de um trecho falhando,
    corrigir o PRIMEIRO trecho e depois a montagem falhar num trecho
    DIFERENTE fazia a correção do primeiro se PERDER — a próxima
    tentativa voltava a usar a fonte original quebrada, não a corrigida.
    Causa raiz: `pending_segments` (a base usada pra reconstruir os
    segmentos a cada confirmação) nunca era atualizado com os valores
    recém-confirmados."""

    def _setup_job_with_two_segments(self, app_module, flask_client, tmp_path):
        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=8", "-loglevel", "error", audio_path], check=True)
        app_module.transcribe_audio = lambda *a, **k: [{"start": 0.0, "end": 8.0, "text": "teste"}]
        app_module.fetch_segment_preview_lightweight = lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None,
            "error": "mock", "video_preview_url": None, "provider": None,
        }
        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "4", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"transcrevendo"}, timeout=0.001) if False else None
        for _ in range(20):
            if app_module._JOBS[job_id]["status"] != "transcrevendo":
                break
            import time as _t
            _t.sleep(0.2)
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({"segments": [
            {"start": 0.0, "end": 4.0, "provider": "pexels", "query": "termo_16"},
            {"start": 4.0, "end": 8.0, "provider": "pexels", "query": "termo_21"},
        ]})})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})
        return job_id

    def test_upload_fix_survives_a_later_failure_on_a_different_segment(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        from video_assembler import VideoAssemblyError

        job_id = self._setup_job_with_two_segments(app_module, flask_client, tmp_path)

        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=cyan:size=320x240:rate=25:duration=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        # Tentativa 2: corrige o trecho 1 com upload; falha no trecho 2 dessa vez.
        seen = []

        def assemble_fails_segment_1(segments, *a, **k):
            seen.append(segments[0].override_source)
            err = VideoAssemblyError("Trecho 2: falha simulada")
            err.segment_index = 1
            raise err

        monkeypatch.setattr(app_module, "assemble_video", assemble_fails_segment_1)

        with open(clip, "rb") as f:
            flask_client.post(f"/job/{job_id}/confirm-segments", data={
                "seg_0_query": "termo_16", "seg_0_provider": "pexels", "seg_0_source_mode": "upload",
                "seg_0_file": (f, "meu_video.mp4"),
                "seg_1_query": "termo_21", "seg_1_provider": "pexels", "seg_1_source_mode": "auto",
            }, content_type="multipart/form-data")
        _wait_for_status(app_module, job_id, {"pronto_para_editar"}, timeout=15)
        assert app_module._JOBS[job_id]["assembly_error_segment_index"] == 1
        assert seen[0]["source"] == "local_file"

        # pending_segments já deveria refletir o upload do trecho 1 imediatamente
        assert app_module._JOBS[job_id]["pending_segments"][0]["override_source"]["source"] == "local_file"

        # Tentativa 3: corrige o trecho 2, SEM reenviar arquivo pro trecho 1.
        seen.clear()

        def assemble_succeeds(segments, *a, **k):
            seen.append(segments[0].override_source)
            return "/caminho/falso/saida.mp4"

        monkeypatch.setattr(app_module, "assemble_video", assemble_succeeds)

        flask_client.post(f"/job/{job_id}/confirm-segments", data={
            "seg_0_query": "termo_16", "seg_0_provider": "pexels", "seg_0_source_mode": "upload",
            "seg_1_query": "termo_novo_que_funciona", "seg_1_provider": "pixabay", "seg_1_source_mode": "auto",
        })
        for _ in range(20):
            if seen:
                break
            import time as _t
            _t.sleep(0.2)

        assert seen, "assemble_video não foi chamado na 3a tentativa"
        assert seen[0] is not None, "O UPLOAD DO TRECHO 1 SE PERDEU na 3a tentativa"
        assert seen[0]["source"] == "local_file"
        assert "meu_video.mp4" in seen[0]["value"]

    def test_edit_segments_page_reflects_latest_confirmed_values_after_failure(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        """Mesmo sem chegar a reenviar o form: depois de uma falha, a
        própria PÁGINA do editor (ao recarregar) já deveria mostrar o
        termo/banco mais recentemente confirmado, não o original da IA."""
        from video_assembler import VideoAssemblyError

        job_id = self._setup_job_with_two_segments(app_module, flask_client, tmp_path)

        def assemble_fails_segment_1(segments, *a, **k):
            err = VideoAssemblyError("Trecho 2: falha simulada")
            err.segment_index = 1
            raise err

        monkeypatch.setattr(app_module, "assemble_video", assemble_fails_segment_1)

        flask_client.post(f"/job/{job_id}/confirm-segments", data={
            "seg_0_query": "termo_16_CORRIGIDO", "seg_0_provider": "pixabay", "seg_0_source_mode": "auto",
            "seg_1_query": "termo_21", "seg_1_provider": "pexels", "seg_1_source_mode": "auto",
        })
        _wait_for_status(app_module, job_id, {"pronto_para_editar"}, timeout=15)

        r = flask_client.get(f"/job/{job_id}/edit-segments?modo=classico")
        assert r.status_code == 200
        assert b"termo_16_CORRIGIDO" in r.data
        # o termo ORIGINAL nao deveria mais aparecer pre-preenchido no campo (a prévia
        # guarda com que busca foi achada — v84 —, então o texto pode existir no JSON dela)
        assert b'value="termo_16"' not in r.data


class TestAnimePexelsProviderIntegration:
    """Testa de ponta a ponta o novo 6º provedor ("animepexels" — acervo
    LOCAL de clipes de anime) através do pipeline completo: prompt
    gerado, prévia da timeline (com vídeo tocável no Monitor de
    Origem), fixação automática do candidato, e montagem final."""

    def test_full_pipeline_with_animepexels_segment(self, app_module, flask_client, monkeypatch, tmp_path):
        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=4", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 4.0, "text": "teste anime"}])

        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=purple:size=320x240:rate=25:duration=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        import sys
        sys.path.insert(0, "toolkit")
        from animepexels.animepexels_client import AnimePexelsVideo

        fake_video = AnimePexelsVideo(
            id="ninja-1", title="ninja running", description="x", url="animepexels://clip/ninja-1",
            clip_url="http://localhost:5000/storage/clips/ninja-1.mp4",
            thumbnail_url="http://localhost:5000/storage/thumbs/ninja-1.jpg",
        )

        class FakeAnimePexelsClient:
            def __init__(self, base_url=None):
                pass

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [fake_video]

            def get_video_by_url(self, video_url):
                return fake_video

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import animepexels.animepexels_client as animepexels_mod
        monkeypatch.setattr(animepexels_mod, "AnimePexelsClient", FakeAnimePexelsClient)

        # a fixture app_module mocka fetch_segment_preview_lightweight por
        # padrão (sem tocar rede) — esse teste precisa do fluxo REAL, já
        # que o objetivo é verificar que ele resolve via AnimePexelsClient.
        import video_assembler

        def real_fetch_preview_lightweight(segment, **kwargs):
            return video_assembler.fetch_segment_preview_lightweight(segment, **kwargs)

        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", real_fetch_preview_lightweight)

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "4", "language": "pt",
                      "providers": ["pexels", "animepexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        # o prompt gerado deveria mencionar o animepexels, já que foi selecionado
        assert "animepexels" in app_module._JOBS[job_id]["prompt"]

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({"segments": [
            {"start": 0.0, "end": 4.0, "provider": "animepexels", "query": "ninja running forest"},
        ]})})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        preview = app_module._JOBS[job_id]["segment_previews"][0]
        assert preview["ok"] is True, preview.get("error")
        assert preview["thumbnail_url"] == "http://localhost:5000/storage/thumbs/ninja-1.jpg"
        assert preview["video_preview_url"] == "http://localhost:5000/storage/clips/ninja-1.mp4"

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=15)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")

    def test_animepexels_checkbox_unchecked_by_default_on_index_page(self, flask_client):
        """Diferente dos outros 5 (marcados por padrão), o animepexels
        não deveria vir marcado — é um banco de nicho, só faz sentido
        quando o conteúdo combina e o servidor local está rodando."""
        r = flask_client.get("/")
        assert r.status_code == 200
        idx = r.data.find(b'value="animepexels"')
        assert idx != -1, "checkbox do animepexels não encontrado na página inicial"
        # verifica que "checked" NÃO aparece entre o value="animepexels" e o fechamento da tag
        tag_end = r.data.find(b">", idx)
        assert b"checked" not in r.data[idx:tag_end]


class TestMultiClipFillsDurationInsteadOfLooping:
    """Pedido explícito: "se a cena for muito pequena não repita e sim
    ache chances de colocar além (cena extra)". Cobre o pipeline
    completo (upload -> prompt -> JSON -> prévia -> montagem final)
    confirmando que, quando o clipe encontrado vem mais curto que o
    segmento, o site busca uma cena DIFERENTE pra completar o tempo em
    vez de repetir a mesma cena em loop."""

    def test_full_pipeline_uses_two_different_scenes_to_fill_one_segment(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=8", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 8.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None, "provider": None
        })

        # 2 clipes CURTOS (4s cada) de cores diferentes -- juntos cobrem
        # os 8s pedidos pelo segmento; nenhum sozinho seria suficiente.
        red = str(tmp_path / "red.mp4")
        green = str(tmp_path / "green.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", red], check=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=320x240:rate=25:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", green], check=True)

        class FakeVideo:
            def __init__(self, vid):
                self.id = vid
                self.premium = False

        class FakeClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo("red"), FakeVideo("green")]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{video.id}.mp4")
                shutil.copy(red if video.id == "red" else green, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))

        # sem isso, _create_client() tentaria abrir um Chrome de VERDADE
        # via Selenium pro caminho de navegador do pexels (ja que a API
        # esta mockada pra falhar) -- precisa simular a sessao tambem.
        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "8", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({"segments": [
            {"start": 0.0, "end": 8.0, "provider": "pexels", "query": "x"},
        ]})})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")

        output_path = app_module._JOBS[job_id]["output_path"]

        def sample(path, t):
            frame = f"{path}_{t}.png"
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("RGB")
            w, h = img.size
            return img.getpixel((w // 2, h // 2))

        cor_inicio = sample(output_path, 1.0)
        cor_fim = sample(output_path, 6.0)
        assert cor_inicio[0] > 200, "deveria ser vermelho no início (primeira cena)"
        assert cor_fim[1] > 100, "deveria ser verde no fim (segunda cena DIFERENTE, não a mesma repetida)"


class TestUsedClipsTrackerEndToEnd:
    def test_three_segments_same_search_get_three_different_scenes(self, app_module, flask_client, monkeypatch, tmp_path):
        """Ponta a ponta pela rota Flask real: 3 trechos fazendo a MESMA
        busca (mesmos 3 candidatos disponíveis) deveriam terminar com 3
        cenas DIFERENTES no vídeo final, não a mesma repetida 3 vezes."""
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=9", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 9.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None, "provider": None
        })

        cores = ["red", "green", "blue"]
        clips = {}
        for nome in cores:
            path = str(tmp_path / f"{nome}.mp4")
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color={nome}:size=320x240:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", path], check=True)
            clips[nome] = path

        class FakeVideo:
            def __init__(self, vid):
                self.id = vid
                self.premium = False

        class FakeClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo("red"), FakeVideo("green"), FakeVideo("blue")]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{video.id}.mp4")
                shutil.copy(clips[video.id], dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "3", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({"segments": [
            {"start": 0.0, "end": 3.0, "provider": "pexels", "query": "x"},
            {"start": 3.0, "end": 6.0, "provider": "pexels", "query": "x"},
            {"start": 6.0, "end": 9.0, "provider": "pexels", "query": "x"},
        ]})})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")

        output_path = app_module._JOBS[job_id]["output_path"]

        def sample(path, t):
            frame = f"{path}_{t}.png"
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("RGB")
            w, h = img.size
            return img.getpixel((w // 2, h // 2))

        cor_seg1 = sample(output_path, 1.0)
        cor_seg2 = sample(output_path, 4.0)
        cor_seg3 = sample(output_path, 7.0)

        vistas = {cor_seg1, cor_seg2, cor_seg3}
        assert len(vistas) == 3, f"os 3 segmentos deveriam ter cores diferentes entre si, só {len(vistas)} distintas apareceram"


class TestUnchangedSegmentStillFillsDuration:
    """Bug real relatado: mesmo depois de implementar o preenchimento
    com cenas extras, o vídeo continuava repetindo um trecho — a causa
    era que TODO trecho não editado (a maioria, numa narração normal)
    passava por uma "fixação automática" do resultado exato da prévia
    via link direto, o que pulava por completo a lógica de preencher
    duração e evitar cenas repetidas entre trechos (tratada como
    escolha deliberada, igual um upload manual). Removida a fixação
    automática — agora todo trecho, editado ou não, passa pela busca
    de verdade na montagem."""

    def test_unchanged_segment_fills_duration_with_extra_scene_not_a_loop(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=8", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 8.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": True, "thumbnail_url": "https://x/thumb.jpg", "result_url": "https://x",
            "label": "x", "error": None, "video_preview_url": None, "provider": "pexels",
        })

        red = str(tmp_path / "red.mp4")
        green = str(tmp_path / "green.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", red], check=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=320x240:rate=25:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", green], check=True)

        class FakeVideo:
            def __init__(self, vid):
                self.id = vid
                self.premium = False

        class FakeClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo("red"), FakeVideo("green")]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{video.id}.mp4")
                shutil.copy(red if video.id == "red" else green, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "8", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({"segments": [
            {"start": 0.0, "end": 8.0, "provider": "pexels", "query": "x"},
        ]})})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        # confirma SEM editar nenhum campo -- o fluxo mais comum de todos
        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")

        output_path = app_module._JOBS[job_id]["output_path"]

        def sample(path, t):
            frame = f"{path}_{t}.png"
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("RGB")
            w, h = img.size
            return img.getpixel((w // 2, h // 2))

        cor_inicio = sample(output_path, 1.0)
        cor_fim = sample(output_path, 6.0)
        assert cor_inicio[0] > 200, "deveria ser vermelho no início"
        assert cor_fim[1] > 100, "deveria ser verde no fim (cena DIFERENTE, não a mesma repetida) mesmo sem editar nada"


class TestUploadSizeLimit:
    """Bug real relatado: "Request Entity Too Large" (413) ao confirmar
    segmentos — o limite de 200MB era pensado pra UM único áudio, mas o
    formulário de confirmar pode ter VÁRIOS vídeos enviados manualmente
    ao mesmo tempo (um por trecho), somando bem mais que isso com
    facilidade em vídeos de boa qualidade.

    Correção evoluiu em duas camadas: primeiro subir o limite (200MB ->
    2GB), depois remover o limite global de vez e, principalmente,
    neutralizar os limites PRÓPRIOS do parser multipart do Werkzeug
    3.1+ (MAX_FORM_MEMORY_SIZE=500KB / MAX_FORM_PARTS=1000, defaults
    baixos e independentes do MAX_CONTENT_LENGTH) — esses é que
    causavam 413 mesmo em upload normal de vídeo."""

    def test_no_global_content_length_limit(self, app_module):
        assert app_module.app.config["MAX_CONTENT_LENGTH"] is None

    def test_multipart_limits_also_relaxed(self, app_module):
        assert app_module.app.config["MAX_FORM_MEMORY_SIZE"] is None
        assert app_module.app.config["MAX_FORM_PARTS"] is None

    def test_413_shows_friendly_message_not_raw_flask_page(self, app_module, flask_client, monkeypatch):
        original_limit = app_module.app.config["MAX_CONTENT_LENGTH"]
        try:
            app_module.app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1MB, fácil de estourar no teste
            app_module._JOBS["job-teste-413"] = {
                "job_id": "job-teste-413",
                "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                       "on_screen_text": None, "media_type": "video", "override_source": None}],
            }

            dados_grandes = b"x" * (3 * 1024 * 1024)  # 3MB, maior que o limite de 1MB
            r = flask_client.post("/job/job-teste-413/confirm-segments", data={"campo_grande": dados_grandes})

            assert r.status_code == 413
            body = r.get_data(as_text=True)
            assert body.strip(), "a resposta de erro não deveria vir vazia"
            assert "<html" not in body.lower(), "deveria ser uma mensagem simples, não a página crua de erro do Flask"
        finally:
            app_module.app.config["MAX_CONTENT_LENGTH"] = original_limit


class TestAnimePexelsDedicatedPromptSelection:
    """Pedido do usuário: quando SÓ o animepexels estiver marcado, usar
    o prompt dedicado (com orientação sobre queries concretas e os
    campos keyword_weight/semantic_weight) em vez do prompt genérico
    pensado pra stock footage real."""

    def test_only_animepexels_uses_dedicated_prompt(self, app_module, flask_client, monkeypatch, tmp_path):
        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=6", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 6.0, "text": "teste sobre naruto"}])

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "5", "language": "pt",
                      "providers": ["animepexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        prompt = app_module._JOBS[job_id]["prompt"]
        assert "keyword_weight" in prompt
        assert "CENA CONCRETA" in prompt

    def test_animepexels_mixed_with_other_provider_uses_generic_prompt(self, app_module, flask_client, monkeypatch, tmp_path):
        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=6", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 6.0, "text": "teste"}])

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "5", "language": "pt",
                      "providers": ["pexels", "animepexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        prompt = app_module._JOBS[job_id]["prompt"]
        assert "keyword_weight" not in prompt
        assert "acervo LOCAL de clipes de" in prompt


class TestOnScreenTextStyleCustomization:
    """Pedido do usuário: personalizar posição, tamanho, borda, fundo e
    fonte do texto na tela. Cobre a distinção entre "checkbox
    desmarcada de propósito" e "campo nem existia" (chamada antiga sem
    o marcador oculto seg_{i}_text_style_submitted)."""

    def test_without_marker_preserves_previous_style_unchanged(self, app_module, monkeypatch):
        """Chamada antiga (sem o marcador) não deveria alterar o estilo
        já salvo — nem zerar campos que a checkbox ausente sugeriria
        estarem desmarcados."""
        app_module._JOBS["job-teste-compat"] = {
            "job_id": "job-teste-compat",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": "oi", "on_screen_text_style": None,
                                   "media_type": "video", "override_source": None}],
        }
        monkeypatch.setattr(app_module, "_start_assembly", lambda *a, **k: None)
        client = app_module.app.test_client()
        client.post("/job/job-teste-compat/confirm-segments", data={})

        style = app_module._JOBS["job-teste-compat"]["pending_segments"][0]["on_screen_text_style"]
        assert style is None

    def test_with_marker_respects_unchecked_checkbox_as_false(self, app_module, monkeypatch):
        """Com o marcador presente, uma checkbox ausente do form É uma
        escolha real de "desmarcado", não um campo esquecido."""
        app_module._JOBS["job-teste-custom"] = {
            "job_id": "job-teste-custom",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": "oi", "on_screen_text_style": None,
                                   "media_type": "video", "override_source": None}],
        }
        monkeypatch.setattr(app_module, "_start_assembly", lambda *a, **k: None)
        client = app_module.app.test_client()
        client.post("/job/job-teste-custom/confirm-segments", data={
            "seg_0_on_screen_text": "oi",
            "seg_0_text_style_submitted": "1",
            "seg_0_text_position": "top-right",
            "seg_0_text_size": "90",
            "seg_0_text_font": "regular",
            "seg_0_text_border": "on",
            # seg_0_text_background propositalmente ausente
        })

        style = app_module._JOBS["job-teste-custom"]["pending_segments"][0]["on_screen_text_style"]
        assert style["position"] == "top-right"
        assert style["font_size"] == 90
        assert style["font"] == "regular"
        assert style["border"] is True
        assert style["background"] is False


class TestOnScreenTextStyleEndToEnd:
    """Confirma visualmente, no vídeo final renderizado pela rota Flask
    real, que a personalização do texto (posição, fonte, borda, fundo)
    aparece de fato — não só que os campos são salvos corretamente."""

    def test_custom_text_style_appears_in_final_video(self, app_module, flask_client, monkeypatch, tmp_path):
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=4", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 4.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None, "provider": None
        })

        clip = str(tmp_path / "fundo.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=640x480:rate=25:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            def __init__(self, session=None):
                pass

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "4", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({"segments": [
            {"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x", "on_screen_text": "OI"},
        ]})})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        flask_client.post(f"/job/{job_id}/confirm-segments", data={
            "seg_0_on_screen_text": "OI",
            "seg_0_text_style_submitted": "1",
            "seg_0_text_position": "top-left",
            "seg_0_text_x": "8",
            "seg_0_text_y": "8",
            "seg_0_text_size": "60",
            "seg_0_text_font": "regular",
            "seg_0_text_border": "on",
        })
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")

        output_path = app_module._JOBS[job_id]["output_path"]
        frame = output_path + "_check.png"
        subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", output_path, "-frames:v", "1", "-loglevel", "error", frame], check=True)

        img = Image.open(frame).convert("L")  # escala de cinza -- so precisa achar pixels claros (texto branco)
        w, h = img.size
        # o texto deveria estar no canto SUPERIOR ESQUERDO -- confirma que
        # ha pixels claros (texto) nessa regiao e NAO no canto oposto
        top_left_region = img.crop((0, 0, w // 4, h // 4))
        bottom_right_region = img.crop((w - w // 4, h - h // 4, w, h))
        assert top_left_region.getextrema()[1] > 200, "deveria ter texto claro no canto superior esquerdo"
        assert bottom_right_region.getextrema()[1] < 100, "canto inferior direito deveria estar vazio (sem texto lá)"


class TestOverlayRoutes:
    """Rotas de adicionar/remover overlay (imagem/vídeo sobreposto ao
    vídeo final, com tempo/posição/tamanho próprios)."""

    def test_add_overlay_via_upload(self, app_module):
        import io
        app_module._JOBS["job-overlay-teste-upload"] = {
            "job_id": "job-overlay-teste-upload",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "on_screen_text_style": None,
                                   "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        r = client.post("/job/job-overlay-teste-upload/add-overlay", data={
            "start": "1.0", "end": "3.0", "position": "bottom-left", "size_percent": "15",
            "source_mode": "upload",
            "overlay_file": (io.BytesIO(b"fake video bytes"), "logo.mp4"),
        }, content_type="multipart/form-data")

        overlays = app_module._JOBS["job-overlay-teste-upload"]["overlays"]
        assert len(overlays) == 1
        assert overlays[0]["source"]["source"] == "local_file"
        assert overlays[0]["start"] == 1.0
        assert overlays[0]["end"] == 3.0
        assert overlays[0]["position"] == "bottom-left"
        assert overlays[0]["size_percent"] == 15.0

    def test_add_overlay_via_search(self, app_module):
        app_module._JOBS["job-overlay-teste-search"] = {
            "job_id": "job-overlay-teste-search",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "on_screen_text_style": None,
                                   "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        client.post("/job/job-overlay-teste-search/add-overlay", data={
            "start": "5.0", "end": "8.0", "position": "top-right", "size_percent": "20",
            "source_mode": "search", "overlay_provider": "pexels", "overlay_query": "logo animation",
        })
        overlays = app_module._JOBS["job-overlay-teste-search"]["overlays"]
        assert len(overlays) == 1
        assert overlays[0]["source"] == {"source": "provider_search", "provider": "pexels", "query": "logo animation"}

    def test_remove_overlay_removes_only_the_target(self, app_module):
        app_module._JOBS["job-overlay-teste-remove"] = {
            "job_id": "job-overlay-teste-remove",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "on_screen_text_style": None,
                                   "media_type": "video", "override_source": None}],
            "overlays": [
                {"id": "aaa", "source": {"source": "url", "value": "https://x/a.mp4"}, "start": 0.0, "end": 2.0, "position": "top-left", "size_percent": 10},
                {"id": "bbb", "source": {"source": "url", "value": "https://x/b.mp4"}, "start": 2.0, "end": 4.0, "position": "top-right", "size_percent": 10},
            ],
        }
        client = app_module.app.test_client()
        client.post("/job/job-overlay-teste-remove/remove-overlay/aaa")
        overlays = app_module._JOBS["job-overlay-teste-remove"]["overlays"]
        assert len(overlays) == 1
        assert overlays[0]["id"] == "bbb"

    def test_add_overlay_rejects_end_before_start(self, app_module):
        app_module._JOBS["job-overlay-teste-validacao"] = {
            "job_id": "job-overlay-teste-validacao",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "on_screen_text_style": None,
                                   "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        r = client.post("/job/job-overlay-teste-validacao/add-overlay", data={
            "start": "5.0", "end": "2.0", "source_mode": "url", "overlay_url": "https://x/a.mp4",
        })
        assert r.status_code == 400
        assert "overlays" not in app_module._JOBS["job-overlay-teste-validacao"]


class TestOverlaySectionRendersInEditor:
    """A página do editor de segmentos precisa mostrar a seção de
    overlays corretamente, com e sem overlays já cadastrados."""

    def test_renders_existing_overlays(self, app_module):
        app_module._JOBS["job-ui-teste"] = {
            "job_id": "job-ui-teste",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "on_screen_text_style": None,
                                   "media_type": "video", "override_source": None}],
            "overlays": [
                {"id": "aaa", "source": {"source": "url", "value": "https://x.com/logo.png"}, "start": 0.0, "end": 5.0, "position": "top-right", "size_percent": 20},
                {"id": "bbb", "source": {"source": "provider_search", "provider": "pexels", "query": "particles"}, "start": 2.0, "end": 8.0, "position": "bottom-left", "size_percent": 15},
            ],
        }
        client = app_module.app.test_client()
        r = client.get("/job/job-ui-teste/edit-segments?modo=classico")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "Overlays" in body
        assert "particles" in body
        assert "https://x.com/logo.png" in body
        assert "Adicionar overlay" in body

    def test_renders_fine_with_no_overlays_yet(self, app_module):
        app_module._JOBS["job-ui-vazio"] = {
            "job_id": "job-ui-vazio",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "on_screen_text_style": None,
                                   "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        r = client.get("/job/job-ui-vazio/edit-segments?modo=classico")
        assert r.status_code == 200
        assert "Adicionar overlay" in r.get_data(as_text=True)


class TestOverlayEndToEnd:
    """Pipeline COMPLETO pela rota Flask real: upload de overlay ->
    montagem -> confirma que aparece no vídeo final, na janela de tempo
    e posição certas."""

    def test_uploaded_overlay_appears_in_final_video(self, app_module, flask_client, monkeypatch, tmp_path):
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=6", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 6.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None, "provider": None
        })

        clip = str(tmp_path / "fundo.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x480:rate=25:duration=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)

        logo_path = str(tmp_path / "logo.png")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=magenta:size=100x100", "-frames:v", "1", "-loglevel", "error", logo_path], check=True)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            def __init__(self, session=None):
                pass

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "6", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({"segments": [
            {"start": 0.0, "end": 6.0, "provider": "pexels", "query": "x"},
        ]})})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        with open(logo_path, "rb") as logo_f:
            flask_client.post(f"/job/{job_id}/add-overlay", data={
                "start": "2.0", "end": "4.0", "position": "bottom-right", "size_percent": "20",
                "source_mode": "upload",
                "overlay_file": (logo_f, "logo.png"),
            }, content_type="multipart/form-data")
        assert len(app_module._JOBS[job_id]["overlays"]) == 1

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")
        assert app_module._JOBS[job_id].get("overlay_errors") == []

        output_path = app_module._JOBS[job_id]["output_path"]

        # descobre a resolução real (a exportação pode não ser a mesma
        # do vídeo de origem de teste — evita amostrar coordenadas
        # fixas que podem cair fora da área real do overlay).
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", output_path],
            capture_output=True, text=True,
        )
        real_w, real_h = (int(v) for v in probe.stdout.strip().split(","))

        def sample(t, x, y):
            frame = str(tmp_path / f"frame_{t}_{x}_{y}.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", output_path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("RGB")
            return img.getpixel((x, y))

        # ponto bem no MEIO da área esperada do overlay (20% da largura,
        # canto inferior direito, margem de 20px) -- evita cair na borda.
        overlay_w = round(real_w * 0.20)
        cx = real_w - (overlay_w // 2) - 20
        cy = real_h - (overlay_w // 2) - 20

        dentro = sample(3, cx, cy)
        fora = sample(5, cx, cy)
        assert dentro[0] > 200 and dentro[2] > 200 and dentro[1] < 100, f"deveria ser magenta (overlay dentro da janela 2s-4s): {dentro}"
        assert not (fora[0] > 200 and fora[2] > 200), f"depois da janela, o overlay não deveria mais aparecer: {fora}"


class TestTextOverlayRoutes:
    """Rotas de adicionar overlay de texto puro (título/chamada) --
    reaproveita a mesma lista/rota de remoção dos overlays de imagem/
    vídeo, distinguido por media_type: 'text'."""

    def test_add_text_overlay(self, app_module):
        app_module._JOBS["job-text-overlay-teste"] = {
            "job_id": "job-text-overlay-teste",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        r = client.post("/job/job-text-overlay-teste/add-text-overlay", data={
            "text": "MEU TITULO", "start": "1.0", "end": "3.0", "position": "top-center",
            "x_percent": "50", "y_percent": "10", "font_size": "70", "border": "on",
        })
        assert r.status_code == 302

        overlays = app_module._JOBS["job-text-overlay-teste"]["overlays"]
        assert len(overlays) == 1
        assert overlays[0]["media_type"] == "text"
        assert overlays[0]["text"] == "MEU TITULO"
        assert overlays[0]["start"] == 1.0
        assert overlays[0]["end"] == 3.0
        assert overlays[0]["style"]["font_size"] == 70
        assert overlays[0]["style"]["border"] is True
        assert overlays[0]["style"]["background"] is False  # checkbox não marcada

    def test_generic_remove_overlay_route_works_for_text_type_too(self, app_module):
        app_module._JOBS["job-text-overlay-remove"] = {
            "job_id": "job-text-overlay-remove",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "overlays": [{"id": "txt1", "media_type": "text", "text": "X", "start": 0.0, "end": 2.0, "style": {}}],
        }
        client = app_module.app.test_client()
        client.post("/job/job-text-overlay-remove/remove-overlay/txt1")
        assert app_module._JOBS["job-text-overlay-remove"]["overlays"] == []

    def test_add_text_overlay_rejects_empty_text(self, app_module):
        app_module._JOBS["job-text-overlay-validacao"] = {
            "job_id": "job-text-overlay-validacao",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        r = client.post("/job/job-text-overlay-validacao/add-text-overlay", data={"text": "", "start": "0", "end": "3"})
        assert r.status_code == 400

    def test_add_text_overlay_rejects_end_before_start(self, app_module):
        app_module._JOBS["job-text-overlay-validacao2"] = {
            "job_id": "job-text-overlay-validacao2",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        r = client.post("/job/job-text-overlay-validacao2/add-text-overlay", data={"text": "X", "start": "5", "end": "2"})
        assert r.status_code == 400


class TestOverlaySectionRendersMixedTypes:
    def test_renders_text_and_media_overlays_together(self, app_module):
        app_module._JOBS["job-ui-misto"] = {
            "job_id": "job-ui-misto",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "overlays": [
                {"id": "aaa", "source": {"source": "url", "value": "https://x.com/logo.png"}, "start": 0.0, "end": 5.0, "position": "top-right", "size_percent": 20},
                {"id": "txt1", "media_type": "text", "text": "Inscreva-se", "start": 2.0, "end": 8.0, "style": {"position": "bottom-center"}},
            ],
        }
        client = app_module.app.test_client()
        r = client.get("/job/job-ui-misto/edit-segments?modo=classico")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "Inscreva-se" in body
        assert "https://x.com/logo.png" in body
        assert "Adicionar overlay de TEXTO" in body
        assert "Adicionar overlay de imagem/vídeo" in body


class TestTextOverlayFullEndToEnd:
    """Pipeline COMPLETO pela rota Flask real: criar overlay de texto ->
    montar vídeo -> confirma que aparece no vídeo final, na janela de
    tempo certa."""

    def test_text_overlay_appears_in_final_video(self, app_module, flask_client, monkeypatch, tmp_path):
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=6", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 6.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None, "provider": None
        })

        clip = str(tmp_path / "fundo.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x480:rate=25:duration=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            def __init__(self, session=None):
                pass

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "6", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({"segments": [
            {"start": 0.0, "end": 6.0, "provider": "pexels", "query": "x"},
        ]})})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        flask_client.post(f"/job/{job_id}/add-text-overlay", data={
            "text": "CHAMADA", "start": "2.0", "end": "4.0", "position": "top-center",
            "x_percent": "50", "y_percent": "10", "font_size": "60",
        })
        assert len(app_module._JOBS[job_id]["overlays"]) == 1

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")
        assert app_module._JOBS[job_id].get("overlay_errors") == []

        output_path = app_module._JOBS[job_id]["output_path"]

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", output_path],
            capture_output=True, text=True,
        )
        real_w, real_h = (int(v) for v in probe.stdout.strip().split(","))

        def sample_top(t):
            frame = str(tmp_path / f"frame_{t}.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", output_path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("L")
            # y_percent=10 posiciona o TOPO do texto a ~10% do espaço
            # disponível (não simplesmente 10% da altura total) -- usa
            # uma faixa generosa (até 25% da altura) pra cobrir com
            # folga onde o texto de fato cai, em qualquer resolução real.
            region = img.crop((real_w // 4, 0, real_w * 3 // 4, round(real_h * 0.25)))
            return region.getextrema()[1]

        antes = sample_top(1)
        dentro = sample_top(3)
        depois = sample_top(5)
        assert antes < 100, f"antes da janela (2s-4s), não deveria ter texto: brilho={antes}"
        assert dentro > 200, f"dentro da janela, deveria ter o texto CHAMADA: brilho={dentro}"
        assert depois < 100, f"depois da janela, o texto não deveria mais aparecer: brilho={depois}"


class TestUpfrontPhotoApiValidation:
    """Bug real relatado: um trecho com media_type='image' sem
    PEXELS_API_KEYS configurado só descobria isso DEPOIS de rodar a
    montagem inteira (minutos, em vídeos longos). Agora checa ANTES de
    começar, respondendo quase instantaneamente com o mesmo aviso e
    destaque de trecho de sempre."""

    def test_blocks_immediately_without_running_assembly(self, app_module, monkeypatch):
        import time

        monkeypatch.setattr(app_module, "photo_api_configuration_error", lambda **kwargs: "chave não configurada (simulado)")
        start_assembly_called = []
        monkeypatch.setattr(app_module, "_start_assembly", lambda *a, **k: start_assembly_called.append(True))

        app_module._JOBS["job-foto-bloqueio"] = {
            "job_id": "job-foto-bloqueio",
            "pending_segments": [
                {"start": 0.0, "end": 4.0, "provider": "pexels", "query": "video normal", "on_screen_text": None,
                 "on_screen_text_style": None, "media_type": "video", "override_source": None},
                {"start": 4.0, "end": 8.0, "provider": "pexels", "query": "foto sem api", "on_screen_text": None,
                 "on_screen_text_style": None, "media_type": "image", "override_source": None},
            ],
            "status": "pronto_para_editar",
        }

        client = app_module.app.test_client()
        inicio = time.time()
        client.post("/job/job-foto-bloqueio/confirm-segments", data={})
        duracao = time.time() - inicio

        assert duracao < 2.0, f"deveria responder quase instantaneamente, levou {duracao:.2f}s"
        assert not start_assembly_called, "não deveria ter iniciado a montagem"

        job = app_module._JOBS["job-foto-bloqueio"]
        assert job["status"] == "pronto_para_editar"
        assert job["assembly_error_segment_index"] == 1
        assert "Trecho 2" in job["assembly_error"]
        assert "chave não configurada (simulado)" in job["assembly_error"]

    def test_does_not_block_when_photo_api_is_configured(self, app_module, monkeypatch):
        monkeypatch.setattr(app_module, "photo_api_configuration_error", lambda **kwargs: None)
        start_assembly_called = []
        monkeypatch.setattr(app_module, "_start_assembly", lambda *a, **k: start_assembly_called.append(True))

        app_module._JOBS["job-foto-ok"] = {
            "job_id": "job-foto-ok",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "foto normal",
                                   "on_screen_text": None, "on_screen_text_style": None,
                                   "media_type": "image", "override_source": None}],
            "status": "pronto_para_editar",
        }
        client = app_module.app.test_client()
        client.post("/job/job-foto-ok/confirm-segments", data={})
        assert start_assembly_called, "com a API configurada, deveria seguir pra montagem normal"

    def test_does_not_block_when_image_segment_has_override_source(self, app_module, monkeypatch):
        """Upload/link direto não dependem da API do Pexels — não faz
        sentido bloquear esses trechos por causa dessa checagem."""
        monkeypatch.setattr(app_module, "photo_api_configuration_error", lambda **kwargs: "chave não configurada (simulado)")
        start_assembly_called = []
        monkeypatch.setattr(app_module, "_start_assembly", lambda *a, **k: start_assembly_called.append(True))

        app_module._JOBS["job-foto-override-teste"] = {
            "job_id": "job-foto-override-teste",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "foto com upload",
                                   "on_screen_text": None, "on_screen_text_style": None, "media_type": "image",
                                   "override_source": {"source": "local_file", "value": "/tmp/fake.jpg", "kind": "image"}}],
            "status": "pronto_para_editar",
        }
        client = app_module.app.test_client()
        client.post("/job/job-foto-override-teste/confirm-segments", data={"seg_0_source_mode": "upload"})
        assert start_assembly_called, "override_source (upload) não depende da API do Pexels, não deveria bloquear"


class TestCutawayRoutes:
    """Rotas de upload/remoção de corte real (vídeo+áudio, não camada)
    sugerido pela IA."""

    def test_upload_cutaway_sets_resolved_path_and_audio_mode(self, app_module):
        import io
        app_module._JOBS["job-cutaway-upload"] = {
            "job_id": "job-cutaway-upload",
            "pending_segments": [{"start": 0.0, "end": 50.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "cutaway_suggestions": [
                {"id": "cut1", "insertion_point": 45.2, "description": "Coletiva de imprensa real",
                 "audio_mode": "pause", "resolved_path": None},
            ],
        }
        client = app_module.app.test_client()
        r = client.post("/job/job-cutaway-upload/upload-cutaway/cut1", data={
            "cutaway_file": (io.BytesIO(b"fake video bytes"), "coletiva.mp4"),
            "audio_mode": "continue",
        }, content_type="multipart/form-data")
        assert r.status_code == 302

        cutaway = app_module._JOBS["job-cutaway-upload"]["cutaway_suggestions"][0]
        assert cutaway["resolved_path"] is not None
        assert cutaway["audio_mode"] == "continue"

    def test_remove_cutaway(self, app_module):
        app_module._JOBS["job-cutaway-remove"] = {
            "job_id": "job-cutaway-remove",
            "pending_segments": [{"start": 0.0, "end": 50.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "cutaway_suggestions": [{"id": "cut1", "insertion_point": 5.0, "description": "x",
                                      "audio_mode": "pause", "resolved_path": None}],
        }
        client = app_module.app.test_client()
        client.post("/job/job-cutaway-remove/remove-cutaway/cut1")
        assert app_module._JOBS["job-cutaway-remove"]["cutaway_suggestions"] == []

    def test_upload_cutaway_rejects_unknown_id(self, app_module):
        import io
        app_module._JOBS["job-cutaway-404"] = {
            "job_id": "job-cutaway-404",
            "pending_segments": [{"start": 0.0, "end": 50.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "cutaway_suggestions": [],
        }
        client = app_module.app.test_client()
        r = client.post("/job/job-cutaway-404/upload-cutaway/nao-existe", data={
            "cutaway_file": (io.BytesIO(b"x"), "a.mp4"),
        }, content_type="multipart/form-data")
        assert r.status_code == 404

    def test_upload_cutaway_rejects_missing_file(self, app_module):
        app_module._JOBS["job-cutaway-sem-arquivo"] = {
            "job_id": "job-cutaway-sem-arquivo",
            "pending_segments": [{"start": 0.0, "end": 50.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "cutaway_suggestions": [{"id": "cut1", "insertion_point": 5.0, "description": "x",
                                      "audio_mode": "pause", "resolved_path": None}],
        }
        client = app_module.app.test_client()
        r = client.post("/job/job-cutaway-sem-arquivo/upload-cutaway/cut1", data={})
        assert r.status_code == 400


class TestCutawayYoutubeRoutes:
    """Buscar no YouTube um clipe pra um corte sugerido pela IA, e
    baixar+cortar só o trecho escolhido direto de dentro do editor --
    reaproveita buscar_videos_youtube/baixar_video/cortar_trecho, que já
    têm sua própria suíte em test_youtube_clipper.py; aqui o foco é a
    integração: as rotas escopadas ao job/corte, e o job de background
    que deixa o cutaway pronto (ou marca erro) sem travar a request."""

    def _job_com_cutaway(self, app_module, job_id="job-cutaway-yt", cutaway_id="cut1"):
        app_module._JOBS[job_id] = {
            "job_id": job_id,
            "pending_segments": [{"start": 0.0, "end": 50.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "cutaway_suggestions": [
                {"id": cutaway_id, "insertion_point": 45.2, "description": "Gojo usando Expansão de Domínio",
                 "audio_mode": "pause", "resolved_path": None},
            ],
        }
        return job_id, cutaway_id

    def _esperar_yt_job(self, app_module, yt_job_id, alvo=("pronto", "erro"), timeout=10):
        deadline = time.time() + timeout
        status = None
        while time.time() < deadline:
            status = app_module._CUTAWAY_YT_JOBS[yt_job_id]["status"]
            if status in alvo:
                return app_module._CUTAWAY_YT_JOBS[yt_job_id]
            time.sleep(0.05)
        raise TimeoutError(f"yt_job {yt_job_id} não chegou a {alvo} em {timeout}s (ficou em {status!r})")

    def test_buscar_encaminha_pro_buscar_videos_youtube(self, app_module, monkeypatch):
        job_id, cutaway_id = self._job_com_cutaway(app_module)
        chamadas = []

        def fake_buscar(termo, quantidade=15):
            chamadas.append((termo, quantidade))
            return [{"id": "abc123", "titulo": "Gojo Domain Expansion", "url": "https://youtube.com/watch?v=abc123",
                      "duracao_segundos": 42, "duracao_formatada": "0:42", "miniatura_url": "https://img/t.jpg",
                      "descricao": "", "canal": "Fã Clips"}]
        monkeypatch.setattr(app_module, "buscar_videos_youtube", fake_buscar)

        client = app_module.app.test_client()
        r = client.get(f"/job/{job_id}/cutaway/{cutaway_id}/youtube-buscar?termo=gojo+expans%C3%A3o+de+dom%C3%ADnio")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["resultados"][0]["titulo"] == "Gojo Domain Expansion"
        assert chamadas == [("gojo expansão de domínio", 15)]

    def test_buscar_termo_vazio_da_erro_400(self, app_module):
        job_id, cutaway_id = self._job_com_cutaway(app_module)
        client = app_module.app.test_client()
        r = client.get(f"/job/{job_id}/cutaway/{cutaway_id}/youtube-buscar?termo=")
        assert r.status_code == 400

    def test_buscar_job_inexistente_404(self, app_module):
        client = app_module.app.test_client()
        r = client.get("/job/nao-existe/cutaway/cut1/youtube-buscar?termo=x")
        assert r.status_code == 404

    def test_baixar_e_cortar_com_sucesso_atualiza_resolved_path(self, app_module, monkeypatch, tmp_path):
        job_id, cutaway_id = self._job_com_cutaway(app_module)
        chamadas_baixar, chamadas_cortar = [], []

        def fake_baixar(url, output_dir, **k):
            chamadas_baixar.append(url)
            os.makedirs(output_dir, exist_ok=True)
            caminho = os.path.join(output_dir, "video_completo.mp4")
            with open(caminho, "wb") as f:
                f.write(b"video completo fake")
            return {"caminho": caminho, "titulo": "Gojo Domain Expansion", "duracao_segundos": 42, "url": url, "id": "abc123"}

        def fake_cortar(video_path, inicio, fim, output_path):
            chamadas_cortar.append((video_path, inicio, fim))
            with open(output_path, "wb") as f:
                f.write(b"trecho cortado fake")
            return output_path

        monkeypatch.setattr(app_module, "yt_baixar_video", fake_baixar)
        monkeypatch.setattr(app_module, "yt_cortar_trecho", fake_cortar)

        client = app_module.app.test_client()
        r = client.post(f"/job/{job_id}/cutaway/{cutaway_id}/youtube", json={
            "url": "https://youtube.com/watch?v=abc123", "inicio": 5.0, "fim": 15.0,
        })
        assert r.status_code == 200
        yt_job_id = r.get_json()["yt_job_id"]

        status = self._esperar_yt_job(app_module, yt_job_id)
        assert status["status"] == "pronto", status.get("erro")
        assert chamadas_baixar == ["https://youtube.com/watch?v=abc123"]
        assert chamadas_cortar[0][1:] == (5.0, 15.0)

        cutaway = app_module._JOBS[job_id]["cutaway_suggestions"][0]
        assert cutaway["resolved_path"] is not None
        assert os.path.exists(cutaway["resolved_path"])
        with open(cutaway["resolved_path"], "rb") as f:
            assert f.read() == b"trecho cortado fake"

    def test_baixar_propaga_erro_do_youtube_clipper_pro_status(self, app_module, monkeypatch):
        job_id, cutaway_id = self._job_com_cutaway(app_module)

        def fake_baixar_que_falha(url, output_dir, **k):
            raise app_module.YoutubeClipperError("vídeo indisponível ou privado")
        monkeypatch.setattr(app_module, "yt_baixar_video", fake_baixar_que_falha)

        client = app_module.app.test_client()
        r = client.post(f"/job/{job_id}/cutaway/{cutaway_id}/youtube", json={
            "url": "https://youtube.com/watch?v=xyz", "inicio": 0.0, "fim": 10.0,
        })
        yt_job_id = r.get_json()["yt_job_id"]

        status = self._esperar_yt_job(app_module, yt_job_id)
        assert status["status"] == "erro"
        assert "vídeo indisponível" in status["erro"]
        # o cutaway não deve ter sido marcado como resolvido quando falha
        assert app_module._JOBS[job_id]["cutaway_suggestions"][0]["resolved_path"] is None

    def test_baixar_sem_url_da_erro_400_sem_iniciar_job(self, app_module):
        job_id, cutaway_id = self._job_com_cutaway(app_module)
        client = app_module.app.test_client()
        r = client.post(f"/job/{job_id}/cutaway/{cutaway_id}/youtube", json={"inicio": 0.0, "fim": 10.0})
        assert r.status_code == 400
        assert "URL" in r.get_json()["erro"]

    def test_baixar_fim_menor_ou_igual_ao_inicio_da_erro_400(self, app_module):
        job_id, cutaway_id = self._job_com_cutaway(app_module)
        client = app_module.app.test_client()
        r = client.post(f"/job/{job_id}/cutaway/{cutaway_id}/youtube", json={
            "url": "https://youtube.com/watch?v=x", "inicio": 10.0, "fim": 5.0,
        })
        assert r.status_code == 400

    def test_baixar_fim_exatamente_igual_ao_inicio_tambem_da_erro_400(self, app_module):
        # fronteira: fim == início (não só fim < início) -- um corte de
        # duração zero não faz sentido nenhum, tem que ser rejeitado.
        job_id, cutaway_id = self._job_com_cutaway(app_module)
        client = app_module.app.test_client()
        r = client.post(f"/job/{job_id}/cutaway/{cutaway_id}/youtube", json={
            "url": "https://youtube.com/watch?v=x", "inicio": 5.0, "fim": 5.0,
        })
        assert r.status_code == 400

    def test_baixar_cutaway_inexistente_404(self, app_module):
        job_id, _ = self._job_com_cutaway(app_module)
        client = app_module.app.test_client()
        r = client.post(f"/job/{job_id}/cutaway/nao-existe/youtube", json={
            "url": "https://youtube.com/watch?v=x", "inicio": 0.0, "fim": 10.0,
        })
        assert r.status_code == 404

    def test_status_de_yt_job_inexistente_404(self, app_module):
        client = app_module.app.test_client()
        r = client.get("/cutaway-youtube-status/nao-existe")
        assert r.status_code == 404

    def test_status_reflete_o_progresso_do_job(self, app_module, monkeypatch):
        job_id, cutaway_id = self._job_com_cutaway(app_module)
        monkeypatch.setattr(app_module, "yt_baixar_video", lambda url, output_dir, **k: {
            "caminho": "/tmp/fake.mp4", "titulo": "x", "duracao_segundos": 10, "url": url, "id": "x",
        })
        # arquivo "baixado" fake não existe de verdade -- cortar_trecho real
        # vai falhar ao tentar rodar o ffmpeg nele, o que já serve pra
        # confirmar que o status reporta "erro" com uma mensagem, sem travar.
        client = app_module.app.test_client()
        r = client.post(f"/job/{job_id}/cutaway/{cutaway_id}/youtube", json={
            "url": "https://youtube.com/watch?v=x", "inicio": 0.0, "fim": 5.0,
        })
        yt_job_id = r.get_json()["yt_job_id"]
        status = self._esperar_yt_job(app_module, yt_job_id)
        assert status["status"] == "erro"

        r2 = client.get(f"/cutaway-youtube-status/{yt_job_id}")
        assert r2.status_code == 200
        assert r2.get_json()["status"] == "erro"


class TestAiSuggestedOverlaysAndCutawaysWiredIntoJob:
    """Bug real encontrado: overlays sugeridos pela IA eram validados
    por parse_ai_response mas NUNCA chegavam a ser salvos no job —
    corrigido junto com a conexão das sugestões de corte."""

    def test_ai_suggested_overlay_and_cutaway_land_in_job_with_ids(self, app_module, monkeypatch):
        import json

        app_module._JOBS["job-ia-overlay-cutaway"] = {
            "job_id": "job-ia-overlay-cutaway",
            "providers": ["pexels"],
            "total_duration": 50.0,
            "status": "aguardando_json",
        }
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock",
            "video_preview_url": None, "provider": None,
        })

        resposta = json.dumps({
            "segments": [{"start": 0.0, "end": 50.0, "provider": "pexels", "query": "x"}],
            "overlays": [{"media_type": "text", "text": "CHAMADA", "start": 5.0, "end": 8.0}],
            "cutaway_suggestions": [{"insertion_point": 45.2, "description": "Coletiva real", "audio_mode": "pause"}],
        })
        client = app_module.app.test_client()
        client.post("/job/job-ia-overlay-cutaway/submit-json", data={"ai_response": resposta})

        job = app_module._JOBS["job-ia-overlay-cutaway"]
        assert len(job["overlays"]) == 1
        assert job["overlays"][0]["text"] == "CHAMADA"
        assert "id" in job["overlays"][0]
        assert len(job["cutaway_suggestions"]) == 1
        assert job["cutaway_suggestions"][0]["description"] == "Coletiva real"
        assert job["cutaway_suggestions"][0]["resolved_path"] is None
        assert "id" in job["cutaway_suggestions"][0]


class TestCutawaySectionRendersInEditor:
    def test_renders_pending_and_resolved_cutaways(self, app_module):
        app_module._JOBS["job-ui-cutaway"] = {
            "job_id": "job-ui-cutaway",
            "pending_segments": [{"start": 0.0, "end": 50.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "cutaway_suggestions": [
                {"id": "cut1", "insertion_point": 45.2, "description": "Coletiva de imprensa real do prefeito",
                 "audio_mode": "pause", "resolved_path": None},
                {"id": "cut2", "insertion_point": 10.0, "description": "Ja tem arquivo",
                 "audio_mode": "continue", "resolved_path": "/tmp/fake.mp4"},
            ],
        }
        client = app_module.app.test_client()
        r = client.get("/job/job-ui-cutaway/edit-segments?modo=classico")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "Cortes reais sugeridos pela IA" in body
        assert "Coletiva de imprensa real do prefeito" in body
        assert "Ja tem arquivo" in body
        assert "Arquivo enviado" in body

    def test_section_absent_when_no_cutaways(self, app_module):
        app_module._JOBS["job-sem-cortes"] = {
            "job_id": "job-sem-cortes",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        r = client.get("/job/job-sem-cortes/edit-segments?modo=classico")
        assert "Cortes reais sugeridos pela IA" not in r.get_data(as_text=True)


class TestCutawayFullEndToEnd:
    """Pipeline COMPLETO pela rota Flask real: IA sugere corte -> upload
    do clipe real -> montagem -> confirma que o corte real aparece no
    vídeo final, com o vídeo ficando mais longo."""

    def test_ai_suggested_cutaway_uploaded_and_applied(self, app_module, flask_client, monkeypatch, tmp_path):
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=6", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 6.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None, "provider": None
        })

        clip = str(tmp_path / "fundo.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x480:rate=25:duration=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)

        cutaway_clip = str(tmp_path / "corte_real.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=640x480:rate=25:duration=2", "-f", "lavfi", "-i", "sine=frequency=880:duration=2", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-loglevel", "error", cutaway_clip], check=True)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            def __init__(self, session=None):
                pass

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "6", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({
            "segments": [{"start": 0.0, "end": 6.0, "provider": "pexels", "query": "x"}],
            "cutaway_suggestions": [{"insertion_point": 3.0, "description": "corte de teste", "audio_mode": "pause"}],
        })})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        cutaway_id = app_module._JOBS[job_id]["cutaway_suggestions"][0]["id"]
        with open(cutaway_clip, "rb") as cf:
            flask_client.post(f"/job/{job_id}/upload-cutaway/{cutaway_id}", data={
                "cutaway_file": (cf, "corte.mp4"), "audio_mode": "pause",
            }, content_type="multipart/form-data")

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=40)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")

        output_path = app_module._JOBS[job_id]["output_path"]
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", output_path], capture_output=True, text=True)
        duracao = float(result.stdout.strip())
        assert abs(duracao - 8.0) < 0.5, f"vídeo deveria ficar 2s mais longo por causa do corte real: {duracao:.2f}s"

        frame = str(tmp_path / "check_cut.png")
        subprocess.run(["ffmpeg", "-y", "-ss", "4", "-i", output_path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
        img = Image.open(frame).convert("RGB")
        pixel = img.getpixel((img.width // 2, img.height // 2))
        assert pixel[0] > 200 and pixel[1] < 50, f"deveria ser vermelho (o corte real inserido): {pixel}"


class TestMediaLibraryRoutes:
    """Biblioteca de mídia: uma área pra enviar arquivos a qualquer
    momento no editor, guardando pra usar depois (arrastar) em
    trechos, overlays, ou cortes -- sem precisar reenviar o mesmo
    arquivo em cada lugar separadamente."""

    def test_upload_to_library_detects_video_type(self, app_module):
        import io
        app_module._JOBS["job-lib-video"] = {
            "job_id": "job-lib-video",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        r = client.post("/job/job-lib-video/upload-to-library", data={
            "library_file": (io.BytesIO(b"fake video bytes"), "meu_clipe.mp4"),
        }, content_type="multipart/form-data")
        assert r.status_code == 302

        lib = app_module._JOBS["job-lib-video"]["media_library"]
        assert len(lib) == 1
        assert lib[0]["filename"] == "meu_clipe.mp4"
        assert lib[0]["media_type"] == "video"

    def test_upload_to_library_detects_image_type(self, app_module):
        import io
        app_module._JOBS["job-lib-imagem"] = {
            "job_id": "job-lib-imagem",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        client.post("/job/job-lib-imagem/upload-to-library", data={
            "library_file": (io.BytesIO(b"fake image bytes"), "minha_foto.png"),
        }, content_type="multipart/form-data")
        lib = app_module._JOBS["job-lib-imagem"]["media_library"]
        assert lib[0]["media_type"] == "image"

    def test_serve_library_file_returns_correct_content(self, app_module):
        import io
        app_module._JOBS["job-lib-serve"] = {
            "job_id": "job-lib-serve",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        client.post("/job/job-lib-serve/upload-to-library", data={
            "library_file": (io.BytesIO(b"conteudo exato"), "arquivo.mp4"),
        }, content_type="multipart/form-data")
        item_id = app_module._JOBS["job-lib-serve"]["media_library"][0]["id"]

        r = client.get(f"/job/job-lib-serve/library-file/{item_id}")
        assert r.status_code == 200
        assert r.data == b"conteudo exato"

    def test_remove_from_library_removes_only_target(self, app_module):
        import io
        app_module._JOBS["job-lib-remove"] = {
            "job_id": "job-lib-remove",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        client.post("/job/job-lib-remove/upload-to-library", data={
            "library_file": (io.BytesIO(b"a"), "a.mp4"),
        }, content_type="multipart/form-data")
        client.post("/job/job-lib-remove/upload-to-library", data={
            "library_file": (io.BytesIO(b"b"), "b.mp4"),
        }, content_type="multipart/form-data")
        lib = app_module._JOBS["job-lib-remove"]["media_library"]
        assert len(lib) == 2

        client.post(f"/job/job-lib-remove/remove-from-library/{lib[0]['id']}")
        remaining = app_module._JOBS["job-lib-remove"]["media_library"]
        assert len(remaining) == 1
        assert remaining[0]["filename"] == "b.mp4"

    def test_upload_to_library_rejects_missing_file(self, app_module):
        app_module._JOBS["job-lib-sem-arquivo"] = {
            "job_id": "job-lib-sem-arquivo",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        r = client.post("/job/job-lib-sem-arquivo/upload-to-library", data={})
        assert r.status_code == 400


class TestLibraryAssignmentRoutes:
    """Atribuir um arquivo já na biblioteca a um destino (trecho,
    overlay, ou corte) sem reenviar — usado pelo arrastar-e-soltar."""

    def test_assign_to_segment_sets_override_source(self, app_module):
        import io
        app_module._JOBS["job-assign-segmento"] = {
            "job_id": "job-assign-segmento",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        client.post("/job/job-assign-segmento/upload-to-library", data={
            "library_file": (io.BytesIO(b"video"), "clip.mp4"),
        }, content_type="multipart/form-data")
        item_id = app_module._JOBS["job-assign-segmento"]["media_library"][0]["id"]

        r = client.post("/job/job-assign-segmento/assign-library-to-segment/0", data={"item_id": item_id})
        assert r.status_code == 302

        seg = app_module._JOBS["job-assign-segmento"]["pending_segments"][0]
        assert seg["override_source"]["source"] == "local_file"
        assert seg["override_source"]["kind"] == "video"
        assert seg["media_type"] == "video"

    def test_assign_to_overlay_creates_new_overlay(self, app_module):
        import io
        app_module._JOBS["job-assign-overlay"] = {
            "job_id": "job-assign-overlay",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        client.post("/job/job-assign-overlay/upload-to-library", data={
            "library_file": (io.BytesIO(b"video"), "clip.mp4"),
        }, content_type="multipart/form-data")
        item = app_module._JOBS["job-assign-overlay"]["media_library"][0]

        r = client.post("/job/job-assign-overlay/assign-library-to-overlay", data={"item_id": item["id"]})
        assert r.status_code == 302

        overlays = app_module._JOBS["job-assign-overlay"]["overlays"]
        assert len(overlays) == 1
        assert overlays[0]["source"]["value"] == item["path"]

    def test_assign_to_cutaway_sets_resolved_path(self, app_module):
        import io
        app_module._JOBS["job-assign-cutaway"] = {
            "job_id": "job-assign-cutaway",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "cutaway_suggestions": [{"id": "cut1", "insertion_point": 5.0, "description": "x",
                                      "audio_mode": "pause", "resolved_path": None}],
        }
        client = app_module.app.test_client()
        client.post("/job/job-assign-cutaway/upload-to-library", data={
            "library_file": (io.BytesIO(b"video"), "clip.mp4"),
        }, content_type="multipart/form-data")
        item = app_module._JOBS["job-assign-cutaway"]["media_library"][0]

        r = client.post("/job/job-assign-cutaway/assign-library-to-cutaway/cut1", data={"item_id": item["id"]})
        assert r.status_code == 302

        cutaway = app_module._JOBS["job-assign-cutaway"]["cutaway_suggestions"][0]
        assert cutaway["resolved_path"] == item["path"]

    def test_assign_rejects_unknown_item_id(self, app_module):
        app_module._JOBS["job-assign-404"] = {
            "job_id": "job-assign-404",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        r = client.post("/job/job-assign-404/assign-library-to-segment/0", data={"item_id": "nao-existe"})
        assert r.status_code == 404

    def test_assign_to_segment_rejects_invalid_index(self, app_module):
        import io
        app_module._JOBS["job-assign-indice-invalido"] = {
            "job_id": "job-assign-indice-invalido",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        client.post("/job/job-assign-indice-invalido/upload-to-library", data={
            "library_file": (io.BytesIO(b"video"), "clip.mp4"),
        }, content_type="multipart/form-data")
        item_id = app_module._JOBS["job-assign-indice-invalido"]["media_library"][0]["id"]

        r = client.post("/job/job-assign-indice-invalido/assign-library-to-segment/99", data={"item_id": item_id})
        assert r.status_code == 400


class TestNovasAnimacoesNoEditor:
    """Confirma que os campos novos do editor (desfoque, novas direções
    de câmera pra foto, novas animações de texto) sobrevivem ao
    confirm-segments e chegam até o VideoSegment final."""

    def _monta_job_com_segmento_de_imagem(self, app_module, flask_client, monkeypatch, tmp_path):
        from PIL import Image
        import video_assembler

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=4", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 4.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "photo_api_configuration_error", lambda **kwargs: None)
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock",
        })

        image_path = str(tmp_path / "foto.jpg")
        Image.new("RGB", (400, 300), (0, 0, 255)).save(image_path)

        class FakePhoto:
            id = "p1"

        class FakeClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_photos_all(self, query=None, max_pages=1, **kw):
                return [FakePhoto()]

            def download_photo(self, photo, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "p.jpg")
                shutil.copy(image_path, dest)
                return dest

        segmentos_recebidos_pela_montagem = []
        original_assemble = video_assembler.assemble_video

        def patched_assemble(segments, *a, **k):
            segmentos_recebidos_pela_montagem.extend(segments)
            k["get_client_fn"] = lambda p: FakeClient()
            return original_assemble(segments, *a, **k)

        monkeypatch.setattr(app_module, "assemble_video", patched_assemble)

        with open(audio_path, "rb") as f:
            flask_client.post(
                "/transcribe",
                data={"audio": (f, "a.wav"), "interval_seconds": "7", "language": "pt",
                      "providers": ["pexels"], "extra_instructions": ""},
                content_type="multipart/form-data",
            )
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        ai_response = json.dumps({"segments": [
            {"start": 0.0, "end": 4.0, "provider": "pexels", "query": "paisagem", "media_type": "image"},
        ]})
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": ai_response})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        return job_id, segmentos_recebidos_pela_montagem

    def test_blur_sigma_e_zoom_direction_novo_chegam_no_segmento_final(self, app_module, flask_client, monkeypatch, tmp_path):
        job_id, segmentos = self._monta_job_com_segmento_de_imagem(app_module, flask_client, monkeypatch, tmp_path)

        flask_client.post(f"/job/{job_id}/confirm-segments", data={
            "seg_0_blur_sigma": "12", "seg_0_zoom_direction": "pan_left",
            "seg_0_focus_x": "0.3", "seg_0_focus_y": "0.7",
        })
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("error")

        assert len(segmentos) == 1
        seg = segmentos[0]
        assert seg.blur_sigma == 12.0
        assert seg.zoom_direction == "pan_left"
        assert seg.focus_x == 0.3
        assert seg.focus_y == 0.7

    def test_zoom_direction_invalido_no_form_cai_pro_padrao(self, app_module, flask_client, monkeypatch, tmp_path):
        job_id, segmentos = self._monta_job_com_segmento_de_imagem(app_module, flask_client, monkeypatch, tmp_path)
        flask_client.post(f"/job/{job_id}/confirm-segments", data={"seg_0_zoom_direction": "diagonal-impossivel"})
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert segmentos[0].zoom_direction == "in"

    def test_blur_sigma_negativo_no_form_vira_zero(self, app_module, flask_client, monkeypatch, tmp_path):
        job_id, segmentos = self._monta_job_com_segmento_de_imagem(app_module, flask_client, monkeypatch, tmp_path)
        flask_client.post(f"/job/{job_id}/confirm-segments", data={"seg_0_blur_sigma": "-5"})
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert segmentos[0].blur_sigma == 0.0

    def test_animacao_de_texto_slide_com_direcao_chega_no_estilo(self, app_module, flask_client, monkeypatch, tmp_path):
        job_id, segmentos = self._monta_job_com_segmento_de_imagem(app_module, flask_client, monkeypatch, tmp_path)
        flask_client.post(f"/job/{job_id}/confirm-segments", data={
            "seg_0_on_screen_text": "Olá mundo", "seg_0_text_style_submitted": "1",
            "seg_0_text_animation": "slide", "seg_0_text_slide_direction": "left",
            "seg_0_text_animation_duration": "0.6",
        })
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        style = segmentos[0].on_screen_text_style
        assert style["animation"] == "slide"
        assert style["slide_direction"] == "left"
        assert style["animation_duration"] == 0.6

    def test_animacao_de_texto_zoom_chega_no_estilo(self, app_module, flask_client, monkeypatch, tmp_path):
        job_id, segmentos = self._monta_job_com_segmento_de_imagem(app_module, flask_client, monkeypatch, tmp_path)
        flask_client.post(f"/job/{job_id}/confirm-segments", data={
            "seg_0_on_screen_text": "Olá mundo", "seg_0_text_style_submitted": "1", "seg_0_text_animation": "zoom",
        })
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        assert segmentos[0].on_screen_text_style["animation"] == "zoom"

    def test_video_final_de_ponta_a_ponta_com_blur_e_animacao_nova(self, app_module, flask_client, monkeypatch, tmp_path):
        """O teste mais importante dessa classe: confirma que o VÍDEO
        FINAL é gerado de verdade (não só que os campos chegaram no
        objeto Python) com blur + uma animação de câmera nova juntos."""
        job_id, segmentos = self._monta_job_com_segmento_de_imagem(app_module, flask_client, monkeypatch, tmp_path)
        flask_client.post(f"/job/{job_id}/confirm-segments", data={
            "seg_0_blur_sigma": "10", "seg_0_zoom_direction": "static",
            "seg_0_on_screen_text": "Texto de teste", "seg_0_text_style_submitted": "1", "seg_0_text_animation": "zoom",
        })
        _wait_for_status(app_module, job_id, {"concluido", "erro"}, timeout=30)
        job = app_module._JOBS[job_id]
        assert job["status"] == "concluido", job.get("error")
        assert os.path.exists(job["output_path"])
        assert os.path.getsize(job["output_path"]) > 1000



    """Importar direto pra biblioteca de mídia do job a partir de um
    clipe já gerado em Capturar página ou Cortar do YouTube — sem
    precisar baixar e reenviar na mão."""

    def _cria_job_video(self, app_module, job_id="job-importar-teste"):
        app_module._JOBS[job_id] = {
            "job_id": job_id,
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        return job_id

    def _cria_captura_com_clipe(self, app_module, captura_id="captura-importar-teste"):
        import subprocess
        import tempfile
        pasta = tempfile.mkdtemp()
        os.makedirs(os.path.join(pasta, "clipes"), exist_ok=True)
        caminho_clipe = os.path.join(pasta, "clipes", "clipe_x.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:duration=2", caminho_clipe], capture_output=True, check=True)
        app_module._CAPTURAS_PAGINA[captura_id] = {
            "id": captura_id, "status": "pronto", "titulo": "Página de Teste", "url": "http://x.com", "pasta": pasta,
            "clipes_gerados": [{"id": "clipe_x.mp4", "arquivo": "clipe_x.mp4", "caminho": caminho_clipe,
                                 "modo": "scroll", "duracao": 2, "descricao": "modo: scroll", "criado_em": 0}],
        }
        return captura_id

    def test_pagina_de_importacao_lista_clipe_da_captura(self, app_module):
        job_id = self._cria_job_video(app_module)
        self._cria_captura_com_clipe(app_module)
        client = app_module.app.test_client()
        r = client.get(f"/job/{job_id}/importar-biblioteca")
        assert r.status_code == 200
        assert b"P\xc3\xa1gina de Teste" in r.data

    def test_pagina_de_importacao_sem_clipes_disponiveis(self, app_module, monkeypatch):
        # isola dos outros testes desta classe -- _CAPTURAS_PAGINA/_YT_CLIPPER_JOBS
        # são dicts globais do processo, não por-job, então sem isolar
        # aqui um teste anterior que já gerou algum clipe faria esse
        # teste falhar (a lista não estaria mais vazia de verdade).
        monkeypatch.setattr(app_module, "_CAPTURAS_PAGINA", {})
        monkeypatch.setattr(app_module, "_YT_CLIPPER_JOBS", {})
        job_id = self._cria_job_video(app_module, "job-importar-vazio")
        client = app_module.app.test_client()
        r = client.get(f"/job/{job_id}/importar-biblioteca")
        assert r.status_code == 200
        assert "Nenhum clipe dispon\u00edvel".encode() in r.data

    def test_pagina_de_importacao_job_inexistente_404(self, app_module):
        client = app_module.app.test_client()
        r = client.get("/job/nao-existe/importar-biblioteca")
        assert r.status_code == 404

    def test_importar_clipe_de_captura_copia_pra_biblioteca(self, app_module):
        job_id = self._cria_job_video(app_module)
        captura_id = self._cria_captura_com_clipe(app_module)
        client = app_module.app.test_client()

        r = client.post(f"/job/{job_id}/importar-biblioteca", data={
            "origem": "captura_pagina", "origem_id": captura_id, "arquivo": "clipe_x.mp4",
        })
        assert r.status_code == 302

        lib = app_module._JOBS[job_id]["media_library"]
        assert len(lib) == 1
        assert lib[0]["media_type"] == "video"
        assert lib[0]["origem"] == "captura_pagina"
        assert os.path.exists(lib[0]["path"])

    def test_importar_clipe_de_youtube_copia_pra_biblioteca(self, app_module):
        import subprocess
        job_id = self._cria_job_video(app_module, "job-importar-yt")
        pasta_clipes = os.path.join(app_module.YT_CLIPPER_DIR, "yt-job-teste", "clipes")
        os.makedirs(pasta_clipes, exist_ok=True)
        caminho_clipe = os.path.join(pasta_clipes, "clipe_yt.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=320x240:duration=2", caminho_clipe], capture_output=True, check=True)
        app_module._YT_CLIPPER_JOBS["yt-job-teste"] = {
            "id": "yt-job-teste", "status": "pronto",
            "info": {"videos": [{
                "titulo_original": "Vídeo YouTube Teste", "url": "https://youtube.com/x",
                "clipes": [{"arquivo": "clipe_yt.mp4", "inicio": "00:00:05", "fim": "00:00:10", "descricao": "trecho"}],
            }]},
        }
        client = app_module.app.test_client()

        r = client.post(f"/job/{job_id}/importar-biblioteca", data={
            "origem": "youtube", "origem_id": "yt-job-teste", "arquivo": "clipe_yt.mp4",
        })
        assert r.status_code == 302
        lib = app_module._JOBS[job_id]["media_library"]
        assert len(lib) == 1
        assert lib[0]["origem"] == "youtube"
        assert os.path.exists(lib[0]["path"])

    def test_importar_arquivo_nao_listado_e_rejeitado(self, app_module):
        """Segurança: um caminho/arquivo que não está na listagem de
        verdade (ex: manipulado na mão, tentativa de path traversal) é
        rejeitado, mesmo com origem/origem_id válidos de outro item."""
        job_id = self._cria_job_video(app_module, "job-importar-seguranca")
        captura_id = self._cria_captura_com_clipe(app_module, "captura-seguranca")
        client = app_module.app.test_client()

        r = client.post(f"/job/{job_id}/importar-biblioteca", data={
            "origem": "captura_pagina", "origem_id": captura_id, "arquivo": "../../../etc/passwd",
        })
        assert r.status_code == 404
        assert app_module._JOBS[job_id].get("media_library", []) == []

    def test_importar_origem_id_inexistente_404(self, app_module):
        job_id = self._cria_job_video(app_module, "job-importar-origem-invalida")
        client = app_module.app.test_client()
        r = client.post(f"/job/{job_id}/importar-biblioteca", data={
            "origem": "captura_pagina", "origem_id": "nao-existe", "arquivo": "x.mp4",
        })
        assert r.status_code == 404

    def test_importar_pra_job_inexistente_404(self, app_module):
        self._cria_captura_com_clipe(app_module, "captura-para-job-invalido")
        client = app_module.app.test_client()
        r = client.post("/job/nao-existe/importar-biblioteca", data={
            "origem": "captura_pagina", "origem_id": "captura-para-job-invalido", "arquivo": "clipe_x.mp4",
        })
        assert r.status_code == 404

    def test_clipe_importado_pode_ser_atribuido_a_um_segmento(self, app_module):
        """Ponta a ponta: importa da captura E confirma que o item
        importado funciona no mecanismo de atribuição a segmento que já
        existia (assign-library-to-segment) -- a importação não é um
        caminho especial, é o MESMO item de biblioteca de sempre."""
        job_id = self._cria_job_video(app_module, "job-importar-e-atribuir")
        captura_id = self._cria_captura_com_clipe(app_module, "captura-e-atribuir")
        client = app_module.app.test_client()

        client.post(f"/job/{job_id}/importar-biblioteca", data={
            "origem": "captura_pagina", "origem_id": captura_id, "arquivo": "clipe_x.mp4",
        })
        item_id = app_module._JOBS[job_id]["media_library"][0]["id"]

        r = client.post(f"/job/{job_id}/assign-library-to-segment/0", data={"item_id": item_id})
        assert r.status_code == 302
        seg = app_module._JOBS[job_id]["pending_segments"][0]
        assert seg["override_source"]["source"] == "local_file"


class TestMediaLibraryUIRenders:
    def test_renders_with_library_segments_overlays_and_cutaways_together(self, app_module):
        app_module._JOBS["job-ui-completo"] = {
            "job_id": "job-ui-completo",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "media_library": [
                {"id": "lib1", "filename": "meu_video.mp4", "path": "/tmp/x.mp4", "media_type": "video"},
                {"id": "lib2", "filename": "minha_foto.png", "path": "/tmp/x.png", "media_type": "image"},
            ],
            "overlays": [],
            "cutaway_suggestions": [{"id": "cut1", "insertion_point": 5.0, "description": "teste",
                                      "audio_mode": "pause", "resolved_path": None}],
        }
        client = app_module.app.test_client()
        r = client.get("/job/job-ui-completo/edit-segments?modo=classico")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "Biblioteca de mídia" in body
        assert "meu_video.mp4" in body
        assert "minha_foto.png" in body
        assert 'draggable="true"' in body
        assert "handleDropOnSegment" in body
        assert "handleDropOnOverlayArea" in body
        assert "handleDropOnCutaway" in body
        assert 'data-segment-index="0"' in body

    def test_renders_fine_with_empty_library(self, app_module):
        app_module._JOBS["job-ui-lib-vazia"] = {
            "job_id": "job-ui-lib-vazia",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        r = client.get("/job/job-ui-lib-vazia/edit-segments?modo=classico")
        assert r.status_code == 200
        assert "Nenhum arquivo na biblioteca ainda" in r.get_data(as_text=True)


class TestCaptionStyleFormParsing:
    """Estilo de legenda enviado pelo formulário chega corretamente no
    job -- testado nos dois pontos de entrada (upload inicial e
    reaproveitar JSON)."""

    def test_upload_flow_parses_all_style_fields(self, app_module, monkeypatch, tmp_path):
        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=2", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 2.0, "text": "teste"}])

        client = app_module.app.test_client()
        with open(audio_path, "rb") as f:
            client.post("/transcribe", data={
                "audio": (f, "a.wav"), "interval_seconds": "2", "language": "pt",
                "providers": ["pexels"], "extra_instructions": "", "add_word_captions": "on",
                "caption_primary_color": "#FF0000", "caption_border_color": "#0000FF",
                "caption_border_width": "6", "caption_glow": "10", "caption_position": "top",
                "caption_font": "regular", "caption_font_size": "50",
            }, content_type="multipart/form-data")

        job_id = list(app_module._JOBS.keys())[-1]
        style = app_module._JOBS[job_id]["caption_style"]
        assert style["primary_color"] == "#FF0000"
        assert style["border_color"] == "#0000FF"
        assert style["border_width"] == 6
        assert style["glow"] == 10
        assert style["position"] == "top"
        assert style["font"] == "regular"
        assert style["font_size"] == 50

    def test_upload_flow_empty_style_fields_produce_empty_style(self, app_module, monkeypatch, tmp_path):
        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=2", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 2.0, "text": "teste"}])

        client = app_module.app.test_client()
        with open(audio_path, "rb") as f:
            client.post("/transcribe", data={
                "audio": (f, "a.wav"), "interval_seconds": "2", "language": "pt",
                "providers": ["pexels"], "extra_instructions": "", "add_word_captions": "on",
            }, content_type="multipart/form-data")

        job_id = list(app_module._JOBS.keys())[-1]
        assert app_module._JOBS[job_id]["caption_style"] == {}

    def test_index_page_renders_style_controls_for_both_forms(self, app_module):
        client = app_module.app.test_client()
        r = client.get("/")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "caption_style_box" in body
        assert "caption_style_box_reuse" in body
        assert body.count('name="caption_font"') == 1
        assert body.count('name="caption_font_reuse"') == 1


class TestManualCaptionEditing:
    """Edição manual de cada palavra da legenda -- texto e tempo
    (início/fim) individualmente."""

    def test_page_renders_all_words(self, app_module):
        app_module._JOBS["job-legenda-render"] = {
            "job_id": "job-legenda-render",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "word_timestamps": [
                {"word": "OLA", "start": 0.0, "end": 0.5},
                {"word": "MUNDO", "start": 0.5, "end": 1.0},
            ],
        }
        client = app_module.app.test_client()
        r = client.get("/job/job-legenda-render/edit-captions")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "OLA" in body
        assert "MUNDO" in body

    def test_link_appears_in_segments_editor_when_captions_exist(self, app_module):
        app_module._JOBS["job-legenda-link"] = {
            "job_id": "job-legenda-link",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "word_timestamps": [{"word": "X", "start": 0.0, "end": 0.5}],
        }
        client = app_module.app.test_client()
        r = client.get("/job/job-legenda-link/edit-segments?modo=classico")
        assert r.status_code == 200
        assert "Editar legendas manualmente" in r.get_data(as_text=True)

    def test_link_absent_when_no_captions(self, app_module):
        app_module._JOBS["job-sem-legenda-link"] = {
            "job_id": "job-sem-legenda-link",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        r = client.get("/job/job-sem-legenda-link/edit-segments?modo=classico")
        assert "Editar legendas manualmente" not in r.get_data(as_text=True)

    def test_edit_captions_page_404_without_word_timestamps(self, app_module):
        app_module._JOBS["job-sem-legenda-404"] = {"job_id": "job-sem-legenda-404", "pending_segments": []}
        client = app_module.app.test_client()
        r = client.get("/job/job-sem-legenda-404/edit-captions")
        assert r.status_code == 404

    def test_save_captions_edits_text_and_time(self, app_module):
        app_module._JOBS["job-legenda-salvar"] = {
            "job_id": "job-legenda-salvar",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "word_timestamps": [
                {"word": "OLA", "start": 0.0, "end": 0.5},
                {"word": "MUNDO", "start": 0.5, "end": 1.0},
            ],
        }
        client = app_module.app.test_client()
        r = client.post("/job/job-legenda-salvar/save-captions", data={
            "word_0_text": "OLA", "word_0_start": "0.0", "word_0_end": "0.6",
            "word_1_text": "MUDADO", "word_1_start": "0.5", "word_1_end": "1.0",
        })
        assert r.status_code == 302
        words = app_module._JOBS["job-legenda-salvar"]["word_timestamps"]
        assert words[0]["end"] == 0.6
        assert words[1]["word"] == "MUDADO"

    def test_save_captions_empty_text_removes_word(self, app_module):
        app_module._JOBS["job-legenda-remover"] = {
            "job_id": "job-legenda-remover",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "word_timestamps": [
                {"word": "OLA", "start": 0.0, "end": 0.5},
                {"word": "MUNDO", "start": 0.5, "end": 1.0},
                {"word": "TESTE", "start": 1.0, "end": 1.5},
            ],
        }
        client = app_module.app.test_client()
        client.post("/job/job-legenda-remover/save-captions", data={
            "word_0_text": "OLA", "word_0_start": "0.0", "word_0_end": "0.5",
            "word_1_text": "", "word_1_start": "0.5", "word_1_end": "1.0",
            "word_2_text": "TESTE", "word_2_start": "1.0", "word_2_end": "1.5",
        })
        words = app_module._JOBS["job-legenda-remover"]["word_timestamps"]
        assert len(words) == 2
        assert [w["word"] for w in words] == ["OLA", "TESTE"]

    def test_save_captions_rejects_end_before_start(self, app_module):
        app_module._JOBS["job-legenda-validacao"] = {
            "job_id": "job-legenda-validacao",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "word_timestamps": [{"word": "X", "start": 0.0, "end": 0.5}, {"word": "Y", "start": 0.5, "end": 1.0}],
        }
        client = app_module.app.test_client()
        r = client.post("/job/job-legenda-validacao/save-captions", data={
            "word_0_text": "X", "word_0_start": "5", "word_0_end": "2",
            "word_1_text": "Y", "word_1_start": "0", "word_1_end": "1",
        })
        assert r.status_code == 400

    def test_save_captions_rejects_deleting_all_words(self, app_module):
        app_module._JOBS["job-legenda-tudo-vazio"] = {
            "job_id": "job-legenda-tudo-vazio",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "word_timestamps": [{"word": "X", "start": 0.0, "end": 0.5}],
        }
        client = app_module.app.test_client()
        r = client.post("/job/job-legenda-tudo-vazio/save-captions", data={
            "word_0_text": "", "word_0_start": "0", "word_0_end": "0.5",
        })
        assert r.status_code == 400


class TestCaptionTimelineLayer:
    """Camada própria de legenda na timeline visual do editor -- cada
    palavra vira um pequeno bloco posicionado no tempo certo, clicável
    pra ir pra edição manual."""

    def test_caption_track_renders_one_block_per_word(self, app_module):
        app_module._JOBS["job-timeline-legenda"] = {
            "job_id": "job-timeline-legenda",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
            "word_timestamps": [
                {"word": "OLA", "start": 0.0, "end": 0.5},
                {"word": "MUNDO", "start": 0.5, "end": 1.0},
            ],
        }
        client = app_module.app.test_client()
        r = client.get("/job/job-timeline-legenda/edit-segments?modo=classico")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "caption-track" in body
        assert body.count('class="block caption-block"') == 2
        assert 'data-start="0.0"' in body
        assert 'title="OLA"' in body
        assert 'title="MUNDO"' in body

    def test_caption_track_absent_without_captions(self, app_module):
        app_module._JOBS["job-sem-legenda-timeline"] = {
            "job_id": "job-sem-legenda-timeline",
            "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x",
                                   "on_screen_text": None, "media_type": "video", "override_source": None}],
        }
        client = app_module.app.test_client()
        r = client.get("/job/job-sem-legenda-timeline/edit-segments?modo=classico")
        assert "caption-track" not in r.get_data(as_text=True)


class TestCaptionCutawaySync:
    """Bug real encontrado numa auditoria (não relatado pelo usuário):
    a legenda era gerada com os tempos ORIGINAIS da transcrição, sem
    ajustar pelo deslocamento que um corte real causa no vídeo final —
    uma palavra dita DEPOIS de um corte aparecia adiantada, fora de
    sincronia com a fala de verdade."""

    def test_caption_stays_synced_after_cutaway(self, app_module, flask_client, monkeypatch, tmp_path):
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=10", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 10.0, "text": "teste", "words": [
            {"word": "ANTES", "start": 1.0, "end": 2.0},
            {"word": "DEPOIS", "start": 8.0, "end": 9.0},
        ]}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None, "provider": None
        })

        clip = str(tmp_path / "fundo.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x480:rate=25:duration=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)
        cutaway_clip = str(tmp_path / "corte.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=640x480:rate=25:duration=5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", cutaway_clip], check=True)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            def __init__(self, session=None):
                pass

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        with open(audio_path, "rb") as f:
            flask_client.post("/transcribe", data={
                "audio": (f, "a.wav"), "interval_seconds": "10", "language": "pt",
                "providers": ["pexels"], "extra_instructions": "", "add_word_captions": "on",
            }, content_type="multipart/form-data")
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({
            "segments": [{"start": 0.0, "end": 10.0, "provider": "pexels", "query": "x"}],
            "cutaway_suggestions": [{"insertion_point": 3.0, "description": "corte de teste", "audio_mode": "pause"}],
        })})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        cutaway_id = app_module._JOBS[job_id]["cutaway_suggestions"][0]["id"]
        with open(cutaway_clip, "rb") as cf:
            flask_client.post(f"/job/{job_id}/upload-cutaway/{cutaway_id}", data={
                "cutaway_file": (cf, "corte.mp4"), "audio_mode": "pause",
            }, content_type="multipart/form-data")

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=40)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")

        captioned = app_module._JOBS[job_id]["captioned_output_path"]

        def sample(t):
            frame = str(tmp_path / f"frame_{t}.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", captioned, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("L")
            region = img.crop((img.width // 4, img.height // 2, img.width * 3 // 4, img.height))
            return region.getextrema()[1]

        # t=8.3s: onde a legenda apareceria SEM o ajuste (bug) -- nao deveria ter texto
        errado = sample(8.3)
        # t=13.3s: onde deveria aparecer de verdade, apos o corte de 5s
        certo = sample(13.3)
        assert errado < 150, f"legenda 'DEPOIS' NÃO deveria aparecer em t=8.3s (fora de sincronia): brilho={errado}"
        assert certo > 200, f"legenda 'DEPOIS' deveria aparecer em t=13.3s (sincronizada): brilho={certo}"


class TestOverlayCutawaySync:
    """Verificação (não um bug -- confirma comportamento CORRETO):
    diferente das legendas, um overlay continua sincronizado
    corretamente mesmo com um corte real na mesma região de tempo,
    porque overlays são queimados no vídeo ANTES dos cortes (viajam
    junto com o trecho que estavam destacando quando ele é deslocado)."""

    def test_overlay_after_cutaway_stays_synced(self, app_module, flask_client, monkeypatch, tmp_path):
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=10", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 10.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None, "provider": None
        })

        clip = str(tmp_path / "fundo.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x480:rate=25:duration=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)
        cutaway_clip = str(tmp_path / "corte.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=640x480:rate=25:duration=5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", cutaway_clip], check=True)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            def __init__(self, session=None):
                pass

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        with open(audio_path, "rb") as f:
            flask_client.post("/transcribe", data={
                "audio": (f, "a.wav"), "interval_seconds": "10", "language": "pt",
                "providers": ["pexels"], "extra_instructions": "",
            }, content_type="multipart/form-data")
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        # overlay marcado pra t=8-9s (absoluto, no áudio ORIGINAL) --
        # um corte de 5s entra em t=3.0s, empurrando tudo depois +5s
        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({
            "segments": [{"start": 0.0, "end": 10.0, "provider": "pexels", "query": "x"}],
            "overlays": [{"media_type": "text", "text": "OVERLAY", "start": 8.0, "end": 9.0}],
            "cutaway_suggestions": [{"insertion_point": 3.0, "description": "corte de teste", "audio_mode": "pause"}],
        })})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        cutaway_id = app_module._JOBS[job_id]["cutaway_suggestions"][0]["id"]
        with open(cutaway_clip, "rb") as cf:
            flask_client.post(f"/job/{job_id}/upload-cutaway/{cutaway_id}", data={
                "cutaway_file": (cf, "corte.mp4"), "audio_mode": "pause",
            }, content_type="multipart/form-data")

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=40)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")
        assert app_module._JOBS[job_id].get("overlay_errors") == []

        output_path = app_module._JOBS[job_id]["output_path"]

        def sample(t):
            frame = str(tmp_path / f"frame_{t}.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", output_path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("L")
            region = img.crop((img.width // 4, img.height // 2, img.width * 3 // 4, img.height))
            return region.getextrema()[1]

        antes_do_esperado = sample(8.3)  # onde apareceria se estivesse fora de sincronia
        depois_ajustado = sample(13.3)   # onde deveria aparecer, corretamente deslocado
        assert antes_do_esperado < 150, f"overlay não deveria aparecer em t=8.3s: brilho={antes_do_esperado}"
        assert depois_ajustado > 150, f"overlay deveria aparecer em t=13.3s (sincronizado com o corte): brilho={depois_ajustado}"


class TestAiSuggestedOverlayFailureDoesNotBlockVideo:
    """Verificação: um overlay sugerido pela IA que falha na resolução
    (busca sem resultado) não deveria travar o vídeo inteiro -- só
    aquele overlay é pulado, com o erro registrado e visível."""

    def test_ai_overlay_search_failure_still_completes_video(self, app_module, flask_client, monkeypatch, tmp_path):
        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=4", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 4.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None, "provider": None
        })

        clip = str(tmp_path / "fundo.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x480:rate=25:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClientSegmento:
            def __init__(self, session=None):
                pass

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        class FakeClientOverlayFalha:
            def __init__(self, session=None):
                pass

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return []  # nenhum resultado -- simula a falha real

            def download_video(self, video, output_dir, **kw):
                raise Exception("não deveria chegar aqui")

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClientSegmento)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pixabay.pixabay_client as pixabay_mod
        monkeypatch.setattr(pixabay_mod, "PixabayClient", FakeClientOverlayFalha)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        with open(audio_path, "rb") as f:
            flask_client.post("/transcribe", data={
                "audio": (f, "a.wav"), "interval_seconds": "4", "language": "pt",
                "providers": ["pexels", "pixabay"], "extra_instructions": "",
            }, content_type="multipart/form-data")
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({
            "segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x"}],
            "overlays": [{"media_type": "image", "provider": "pixabay", "query": "algo que nao existe", "start": 1.0, "end": 2.0}],
        })})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=40)

        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")
        assert len(app_module._JOBS[job_id].get("overlay_errors", [])) == 1


class TestMultipleCutawaysCaptionSyncFullPipeline:
    """Confirma no pipeline REAL (não só a função isolada) que múltiplos
    cortes acumulam o deslocamento corretamente na legenda -- 3 palavras
    em pontos diferentes da narração, 2 cortes reais entre elas."""

    def test_three_words_shift_correctly_across_two_cutaways(self, app_module, flask_client, monkeypatch, tmp_path):
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=20", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 20.0, "text": "teste", "words": [
            {"word": "PRIMEIRA", "start": 1.0, "end": 2.0},
            {"word": "SEGUNDA", "start": 7.0, "end": 8.0},
            {"word": "TERCEIRA", "start": 15.0, "end": 16.0},
        ]}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None, "provider": None
        })

        clip = str(tmp_path / "fundo.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x480:rate=25:duration=20", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)
        corte1 = str(tmp_path / "corte1.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=640x480:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", corte1], check=True)
        corte2 = str(tmp_path / "corte2.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=640x480:rate=25:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", corte2], check=True)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            def __init__(self, session=None):
                pass

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        with open(audio_path, "rb") as f:
            flask_client.post("/transcribe", data={
                "audio": (f, "a.wav"), "interval_seconds": "20", "language": "pt",
                "providers": ["pexels"], "extra_instructions": "", "add_word_captions": "on",
            }, content_type="multipart/form-data")
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({
            "segments": [{"start": 0.0, "end": 20.0, "provider": "pexels", "query": "x"}],
            "cutaway_suggestions": [
                {"insertion_point": 3.0, "description": "corte 1", "audio_mode": "pause"},
                {"insertion_point": 10.0, "description": "corte 2", "audio_mode": "pause"},
            ],
        })})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        cuts = app_module._JOBS[job_id]["cutaway_suggestions"]
        with open(corte1, "rb") as cf:
            flask_client.post(f"/job/{job_id}/upload-cutaway/{cuts[0]['id']}", data={
                "cutaway_file": (cf, "c1.mp4"), "audio_mode": "pause",
            }, content_type="multipart/form-data")
        with open(corte2, "rb") as cf:
            flask_client.post(f"/job/{job_id}/upload-cutaway/{cuts[1]['id']}", data={
                "cutaway_file": (cf, "c2.mp4"), "audio_mode": "pause",
            }, content_type="multipart/form-data")

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=60)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")

        captioned = app_module._JOBS[job_id]["captioned_output_path"]

        def sample(t):
            frame = str(tmp_path / f"frame_{t}.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", captioned, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("L")
            region = img.crop((img.width // 4, img.height // 2, img.width * 3 // 4, img.height))
            return region.getextrema()[1]

        # PRIMEIRA (orig 1-2s): antes de qualquer corte, fica igual
        # SEGUNDA (orig 7-8s): passou pelo corte1 (3s) -> 10-11s
        # TERCEIRA (orig 15-16s): passou pelos 2 cortes (3+4=7s) -> 22-23s
        assert sample(1.5) > 150, "PRIMEIRA deveria aparecer em t=1.5s"
        assert sample(10.5) > 150, "SEGUNDA deveria aparecer em t=10.5s (deslocada +3s)"
        assert sample(22.5) > 150, "TERCEIRA deveria aparecer em t=22.5s (deslocada +7s, 2 cortes acumulados)"


class TestRetryDoesNotDuplicateCutaway:
    """Verificação: uma montagem que falha (checagem antecipada da API
    de foto) seguida de retry bem-sucedido não deveria aplicar o corte
    real duas vezes (nem deixar de aplicar) -- confirma que o fluxo é
    idempotente entre tentativas."""

    def test_cutaway_applied_exactly_once_after_failed_then_successful_retry(
        self, app_module, flask_client, monkeypatch, tmp_path
    ):
        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=10", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 10.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None, "provider": None
        })

        clip = str(tmp_path / "fundo.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x480:rate=25:duration=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)
        cutaway_clip = str(tmp_path / "corte.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=640x480:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", cutaway_clip], check=True)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            def __init__(self, session=None):
                pass

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        class FakePhotoClient:
            def search_photos_all(self, query=None, **kw):
                return [FakeVideo()]

            def download_photo(self, photo, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "foto.jpg")
                subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=yellow:size=640x480", "-frames:v", "1", dest], check=True, capture_output=True)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        with open(audio_path, "rb") as f:
            flask_client.post("/transcribe", data={
                "audio": (f, "a.wav"), "interval_seconds": "10", "language": "pt",
                "providers": ["pexels"], "extra_instructions": "",
            }, content_type="multipart/form-data")
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({
            "segments": [{"start": 0.0, "end": 10.0, "provider": "pexels", "query": "x", "media_type": "image"}],
            "cutaway_suggestions": [{"insertion_point": 3.0, "description": "corte de teste", "audio_mode": "pause"}],
        })})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        cutaway_id = app_module._JOBS[job_id]["cutaway_suggestions"][0]["id"]
        with open(cutaway_clip, "rb") as cf:
            flask_client.post(f"/job/{job_id}/upload-cutaway/{cutaway_id}", data={
                "cutaway_file": (cf, "corte.mp4"), "audio_mode": "pause",
            }, content_type="multipart/form-data")

        # 1a tentativa: falha genuína (API de foto não configurada, checagem antecipada)
        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        assert app_module._JOBS[job_id]["status"] == "pronto_para_editar"
        # o erro do cliente de foto (aqui, o falso "sem chave") vem na mensagem do trecho
        assert "sem chave" in app_module._JOBS[job_id]["assembly_error"]

        # "corrige" o problema e faz retry
        monkeypatch.setattr(app_module, "photo_api_configuration_error", lambda **kwargs: None)
        monkeypatch.setattr("video_assembler.ClientFactory.get_photo_client", lambda self, provider="pexels": FakePhotoClient())

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=40)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")

        output_path = app_module._JOBS[job_id]["output_path"]
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", output_path], capture_output=True, text=True)
        duracao = float(result.stdout.strip())
        assert abs(duracao - 13.0) < 0.5, f"corte deveria ser aplicado exatamente 1 vez (10+3=13s), veio {duracao:.2f}s"


class TestImageOverlayCutawaySync:
    """Verificação: overlay de IMAGEM/VÍDEO (não texto -- caminho de
    código diferente no apply_overlays, usa arquivo real + filtro
    overlay em vez de drawtext) também fica sincronizado corretamente
    com um corte real na mesma região de tempo."""

    def test_image_overlay_after_cutaway_stays_synced(self, app_module, flask_client, monkeypatch, tmp_path):
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=10", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 10.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None, "provider": None
        })

        clip = str(tmp_path / "fundo.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x480:rate=25:duration=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)
        cutaway_clip = str(tmp_path / "corte.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=640x480:rate=25:duration=5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", cutaway_clip], check=True)
        overlay_img = str(tmp_path / "logo.png")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=yellow:size=100x100", "-frames:v", "1", "-loglevel", "error", overlay_img], check=True)

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            def __init__(self, session=None):
                pass

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))
        import browser_session
        monkeypatch.setattr(browser_session, "ChromeSession", lambda headless, headers=None: type(
            "FakeSession", (), {"close": lambda self: None}
        )())

        with open(audio_path, "rb") as f:
            flask_client.post("/transcribe", data={
                "audio": (f, "a.wav"), "interval_seconds": "10", "language": "pt",
                "providers": ["pexels"], "extra_instructions": "",
            }, content_type="multipart/form-data")
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({
            "segments": [{"start": 0.0, "end": 10.0, "provider": "pexels", "query": "x"}],
            "cutaway_suggestions": [{"insertion_point": 3.0, "description": "corte de teste", "audio_mode": "pause"}],
        })})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        with open(overlay_img, "rb") as imgf:
            flask_client.post(f"/job/{job_id}/add-overlay", data={
                "start": "8.0", "end": "9.0", "position": "top-right", "size_percent": "20",
                "source_mode": "upload", "overlay_file": (imgf, "logo.png"),
            }, content_type="multipart/form-data")

        cutaway_id = app_module._JOBS[job_id]["cutaway_suggestions"][0]["id"]
        with open(cutaway_clip, "rb") as cf:
            flask_client.post(f"/job/{job_id}/upload-cutaway/{cutaway_id}", data={
                "cutaway_file": (cf, "corte.mp4"), "audio_mode": "pause",
            }, content_type="multipart/form-data")

        flask_client.post(f"/job/{job_id}/confirm-segments", data={})
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=40)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")
        assert app_module._JOBS[job_id].get("overlay_errors") == []

        output_path = app_module._JOBS[job_id]["output_path"]

        def sample_top_right(t):
            frame = str(tmp_path / f"frame_{t}.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", output_path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("RGB")
            return img.getpixel((img.width - 40, 40))

        antes = sample_top_right(8.3)
        depois = sample_top_right(13.3)
        assert not (antes[0] > 200 and antes[1] > 200 and antes[2] < 100), f"overlay não deveria aparecer em t=8.3s: {antes}"
        assert depois[0] > 200 and depois[1] > 200 and depois[2] < 100, f"overlay (amarelo) deveria aparecer em t=13.3s: {depois}"


class TestMediaLibraryFullAssemblyPipeline:
    """Confirma de ponta a ponta que um arquivo atribuído da biblioteca
    de mídia (simulando arrastar-e-soltar) chega de verdade no vídeo
    final montado -- não só que a atribuição em si funciona."""

    def test_library_assigned_segment_appears_in_final_video(self, app_module, flask_client, monkeypatch, tmp_path):
        from PIL import Image

        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=4", "-loglevel", "error", audio_path], check=True)
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 4.0, "text": "teste"}])
        monkeypatch.setattr(app_module, "fetch_segment_preview_lightweight", lambda segment, **kw: {
            "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mock", "video_preview_url": None, "provider": None
        })

        meu_video = str(tmp_path / "meu_video.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=640x480:rate=25:duration=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", meu_video], check=True)

        with open(audio_path, "rb") as f:
            flask_client.post("/transcribe", data={
                "audio": (f, "a.wav"), "interval_seconds": "4", "language": "pt",
                "providers": ["pexels"], "extra_instructions": "",
            }, content_type="multipart/form-data")
        job_id = list(app_module._JOBS.keys())[-1]
        _wait_for_status(app_module, job_id, {"aguardando_json"})

        flask_client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps({
            "segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "x"}],
        })})
        _wait_for_status(app_module, job_id, {"pronto_para_editar"})

        with open(meu_video, "rb") as vf:
            flask_client.post(f"/job/{job_id}/upload-to-library", data={
                "library_file": (vf, "meu_video.mp4"),
            }, content_type="multipart/form-data")
        item_id = app_module._JOBS[job_id]["media_library"][0]["id"]

        flask_client.post(f"/job/{job_id}/assign-library-to-segment/0", data={"item_id": item_id})
        assert app_module._JOBS[job_id]["pending_segments"][0]["override_source"]["source"] == "local_file"

        flask_client.post(f"/job/{job_id}/confirm-segments", data={"seg_0_source_mode": "upload"})
        _wait_for_status(app_module, job_id, {"concluido", "erro", "pronto_para_editar"}, timeout=40)
        assert app_module._JOBS[job_id]["status"] == "concluido", app_module._JOBS[job_id].get("assembly_error")

        output_path = app_module._JOBS[job_id]["output_path"]
        frame = str(tmp_path / "frame.png")
        subprocess.run(["ffmpeg", "-y", "-ss", "2", "-i", output_path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
        img = Image.open(frame).convert("RGB")
        pixel = img.getpixel((img.width // 2, img.height // 2))
        assert pixel[2] > 200 and pixel[0] < 50, f"vídeo final deveria mostrar o AZUL da biblioteca: {pixel}"


class TestPadroesExcluidosDoReloader:
    """Pastas de dados/saída (modelos baixados, áudios/vídeos gerados,
    states de job) ficam excluídas do reloader do modo debug -- sem
    isso, o Werkzeug escaneava tudo isso a cada checagem, ficando mais
    lento conforme o site é usado (bug real relatado: site demorando
    pra carregar/travando no navegador depois de uso)."""

    def test_padroes_cobrem_as_pastas_de_dados_que_crescem_com_o_uso(self, app_module):
        padroes = app_module._padroes_excluidos_do_reloader()
        base = app_module.BASE_DIR
        esperados = {
            os.path.join(base, "outputs", "*"),
            os.path.join(base, "jobs", "*"),
            os.path.join(base, "narracoes", "*"),
            os.path.join(base, "conversas", "*"),
            os.path.join(base, "toolkit", "tts", "models", "*"),
        }
        assert esperados.issubset(set(padroes))

    def test_padroes_batem_com_arquivos_fundo_dentro_dessas_pastas(self, app_module):
        """Confirma que o padrão (fnmatch) realmente exclui arquivos em
        qualquer profundidade dentro da pasta, não só no primeiro nível."""
        import fnmatch
        padroes = app_module._padroes_excluidos_do_reloader()
        caminho_fundo = os.path.join(app_module.BASE_DIR, "toolkit", "tts", "models", "xtts", "checkpoint_v1", "model.pth")
        bate = any(fnmatch.fnmatch(caminho_fundo, p) for p in padroes)
        assert bate, f"{caminho_fundo!r} deveria bater com algum dos padrões excluídos"

    def test_padroes_nao_excluem_codigo_fonte(self, app_module):
        import fnmatch
        padroes = app_module._padroes_excluidos_do_reloader()
        arquivo_codigo = os.path.join(app_module.BASE_DIR, "video_assembler.py")
        bate = any(fnmatch.fnmatch(arquivo_codigo, p) for p in padroes)
        assert not bate, "código-fonte não deveria bater com nenhum padrão de exclusão"
