"""
Testes das correções feitas nesta sessão:

1. `_search_and_download_filling_duration(initial_duration=...)`: permite
   "continuar de onde parou" numa busca de complemento, em vez de sempre
   começar do zero.

2. Clipe escolhido manualmente no editor (override_source) que vem mais
   curto que o trecho agora é complementado com uma busca de verdade
   (em vez de só repetir/segurar esse clipe sozinho até o fim).

3. Texto na tela com janela de tempo PRÓPRIA dentro do trecho
   (start_offset/end_offset) — tanto o filtro `drawtext` do ffmpeg
   (`enable='between(t,...)'`) quanto o parsing dos campos do form em
   `/confirm-segments`.

4. A página do editor (`/job/<id>/edit-segments`) manda pro front-end a
   resolução REAL de saída do vídeo (`video_target_width/height`),
   usada pra escalar o texto do monitor de composição no mesmo tamanho
   relativo que ele sai no vídeo final.

5. O 413 ao confirmar segmentos: os limites novos do Flask/Werkzeug
   (MAX_FORM_MEMORY_SIZE / MAX_FORM_PARTS) não podem mais barrar um
   envio grande.
"""
import os
import shutil
import subprocess

import pytest

from prompt_builder import VideoSegment
from video_assembler import (
    VideoAssemblyError,
    _build_drawtext_filter,
    _search_and_download_filling_duration,
    assemble_video,
)

WORK = "/tmp/_test_recent_editor_fixes"


@pytest.fixture
def app_module(monkeypatch):
    """Mesma fixture de test_app_integration.py, duplicada aqui porque
    fixtures definidas dentro de um arquivo de teste não são
    compartilhadas automaticamente com outros arquivos (só as que
    ficam em conftest.py são)."""
    import app as _app_module

    def _default_fake_fetch_preview_lightweight(segment, **kwargs):
        return {"ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mockado em teste: sem prévia"}

    monkeypatch.setattr(_app_module, "fetch_segment_preview_lightweight", _default_fake_fetch_preview_lightweight)
    yield _app_module


@pytest.fixture
def flask_client(app_module):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _make_clip(path, color="red", duration=2):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color={color}:size=640x360:rate=25:duration={duration}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", path],
        check=True,
    )
    return path


def _make_audio(path, duration=9.469):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=duration={duration}", "-loglevel", "error", path],
        check=True,
    )
    return path


def _setup_dir(name):
    d = os.path.join(WORK, name)
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    return d


class _FakeSession:
    def close(self):
        pass


class _FakeVideo:
    def __init__(self, vid):
        self.id = vid
        self.premium = False


class TestInitialDurationParameter:
    """`_search_and_download_filling_duration` precisa buscar só o que
    falta quando já existe uma duração "garantida" de fora (o clipe
    manual do editor), em vez de sempre completar a duração inteira do
    zero.
    """

    def test_without_initial_duration_downloads_as_many_as_needed(self, tmp_path):
        clip = _make_clip(str(tmp_path / "src.mp4"), duration=3)
        download_dir = str(tmp_path / "downloads")

        class FakeClient:
            session = _FakeSession()
            download_calls = 0

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [_FakeVideo("v1"), _FakeVideo("v2"), _FakeVideo("v3")]

            def download_video(self, video, output_dir, **kw):
                self.download_calls += 1
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{video.id}.mp4")
                shutil.copy(clip, dest)
                return dest

        client = FakeClient()
        segment = VideoSegment(start=0.0, end=9.0, provider="pexels", query="x")  # precisa de ~9s
        result = _search_and_download_filling_duration(segment, download_dir, client)

        # cada clipe fake tem 3s -> precisa dos 3 pra fechar ~9s
        assert len(result) == 3
        assert client.download_calls == 3

    def test_with_initial_duration_downloads_only_the_remainder(self, tmp_path):
        clip = _make_clip(str(tmp_path / "src.mp4"), duration=3)
        download_dir = str(tmp_path / "downloads")

        class FakeClient:
            session = _FakeSession()
            download_calls = 0

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [_FakeVideo("v1"), _FakeVideo("v2"), _FakeVideo("v3")]

            def download_video(self, video, output_dir, **kw):
                self.download_calls += 1
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{video.id}.mp4")
                shutil.copy(clip, dest)
                return dest

        client = FakeClient()
        # mesmo trecho de 9s, mas já tem 7s "garantidos" de fora
        # (o clipe manual do editor) -- só falta ~2s, 1 clipe já resolve.
        segment = VideoSegment(start=0.0, end=9.0, provider="pexels", query="x")
        result = _search_and_download_filling_duration(
            segment, download_dir, client, initial_duration=7.0,
        )

        assert len(result) == 1
        assert client.download_calls == 1

    def test_initial_duration_defaults_to_zero_backward_compatible(self, tmp_path):
        """Chamada antiga (sem passar initial_duration) continua se
        comportando exatamente como antes."""
        clip = _make_clip(str(tmp_path / "src.mp4"), duration=5)
        download_dir = str(tmp_path / "downloads")

        class FakeClient:
            session = _FakeSession()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [_FakeVideo("v1")]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        segment = VideoSegment(start=0.0, end=4.0, provider="pexels", query="x")
        result = _search_and_download_filling_duration(segment, download_dir, FakeClient())
        assert len(result) == 1  # 1 clipe de 5s já cobre um trecho de 4s


class TestManualOverrideClipGetsSupplemented:
    """Pedido do usuário: um clipe escolhido manualmente no editor que
    vier mais curto que o trecho deve ser complementado com uma busca
    de verdade, em vez de só repetir/pausar sozinho até acabar o
    tempo."""

    def test_short_override_clip_triggers_supplement_search(self, tmp_path, synthetic_audio, monkeypatch):
        import pexels_api_client

        short_override = _make_clip(str(tmp_path / "override_short.mp4"), color="red", duration=1.5)
        supplement_clip = _make_clip(str(tmp_path / "supplement.mp4"), color="blue", duration=3)

        download_calls = []

        class FakeApiClient:
            session = _FakeSession()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [_FakeVideo("v1"), _FakeVideo("v2"), _FakeVideo("v3")]

            def download_video(self, video, output_dir, **kw):
                download_calls.append(video.id)
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{video.id}.mp4")
                shutil.copy(supplement_clip, dest)
                return dest

        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", FakeApiClient)

        # trecho de 6s, mas o clipe manual só tem 1.5s -> precisa de
        # complemento pra fechar os ~6s.
        segments = [VideoSegment(
            start=0.0, end=6.0, provider="pexels", query="qualquer coisa",
            override_source={"source": "local_file", "value": short_override, "kind": "video"},
        )]

        output_path = str(tmp_path / "out" / "final.mp4")
        site_cfg = {
            "orientation": "16:9",
            "provider_priority": ["pexels"],
            "pexels_api_fallback_to_browser": False,
            "browser_visible": False,
            "browser_shared_across_providers": False,
            "browser_mode": "reuse_session",
        }
        final = assemble_video(
            segments, synthetic_audio, output_path, str(tmp_path / "job"), site_cfg=site_cfg,
        )

        assert os.path.exists(final)
        # a busca de complemento tem que ter sido chamada pelo menos
        # uma vez -- o override sozinho NUNCA chama client.download_video,
        # então qualquer chamada aqui só pode ter vindo do complemento.
        assert len(download_calls) >= 1, "deveria ter buscado complemento pro clipe manual curto"

    def test_long_enough_override_clip_does_not_trigger_supplement(self, tmp_path, synthetic_audio, monkeypatch):
        """Se o clipe manual já é longo o bastante, não deveria buscar
        complemento nenhum (comportamento de antes preservado)."""
        import pexels_api_client

        long_override = _make_clip(str(tmp_path / "override_long.mp4"), color="green", duration=8)

        download_calls = []

        class FakeApiClient:
            session = _FakeSession()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [_FakeVideo("v1")]

            def download_video(self, video, output_dir, **kw):
                download_calls.append(video.id)
                raise AssertionError("não deveria ter buscado complemento -- o clipe manual já era longo o bastante")

        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", FakeApiClient)

        segments = [VideoSegment(
            start=0.0, end=4.0, provider="pexels", query="x",
            override_source={"source": "local_file", "value": long_override, "kind": "video"},
        )]
        output_path = str(tmp_path / "out" / "final.mp4")
        site_cfg = {"orientation": "16:9", "provider_priority": ["pexels"], "browser_visible": False}
        final = assemble_video(segments, synthetic_audio, output_path, str(tmp_path / "job"), site_cfg=site_cfg)

        assert os.path.exists(final)
        assert download_calls == []

    def test_supplement_search_failure_falls_back_to_single_clip(self, tmp_path, synthetic_audio, monkeypatch):
        """Se a busca de complemento falhar por qualquer motivo, a
        montagem não pode quebrar -- só segue com o clipe manual
        sozinho, como era antes dessa mudança."""
        import pexels_api_client

        short_override = _make_clip(str(tmp_path / "override_short.mp4"), duration=1.5)

        class FailingApiClient:
            session = _FakeSession()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                raise VideoAssemblyError("busca de complemento falhou de propósito, pro teste")

        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", FailingApiClient)

        segments = [VideoSegment(
            start=0.0, end=6.0, provider="pexels", query="x",
            override_source={"source": "local_file", "value": short_override, "kind": "video"},
        )]
        output_path = str(tmp_path / "out" / "final.mp4")
        site_cfg = {"orientation": "16:9", "provider_priority": ["pexels"], "browser_visible": False}
        # não deveria levantar exceção nenhuma -- cai de volta pro
        # clipe único (que o _normalize_clip resolve com loop, como
        # sempre foi).
        final = assemble_video(segments, synthetic_audio, output_path, str(tmp_path / "job"), site_cfg=site_cfg)
        assert os.path.exists(final)


class TestDrawtextTimeWindow:
    """O filtro `drawtext` só deve restringir a exibição a uma janela
    de tempo quando start_offset/end_offset forem passados e válidos
    -- sem eles, continua cobrindo o trecho inteiro (comportamento de
    sempre)."""

    def test_no_window_means_always_visible(self):
        f = _build_drawtext_filter("oi", 1080, {})
        assert "enable=" not in f

    def test_valid_window_adds_enable_between_clause(self):
        f = _build_drawtext_filter("oi", 1080, {"start_offset": 1.5, "end_offset": 4.0})
        assert "enable='between(t,1.500,4.000)'" in f

    def test_invalid_window_end_before_start_is_ignored(self):
        f = _build_drawtext_filter("oi", 1080, {"start_offset": 5.0, "end_offset": 2.0})
        assert "enable=" not in f

    def test_only_one_of_the_two_fields_is_ignored(self):
        f1 = _build_drawtext_filter("oi", 1080, {"start_offset": 1.0})
        f2 = _build_drawtext_filter("oi", 1080, {"end_offset": 4.0})
        assert "enable=" not in f1
        assert "enable=" not in f2


class TestConfirmSegmentsTextWindowForm:
    """Parsing dos campos seg_{i}_text_start_offset / _end_offset em
    /confirm-segments -- mesmo padrão dos testes existentes de estilo
    de texto (TestOnScreenTextStyleCustomization)."""

    def _base_job(self, job_id):
        return {
            "job_id": job_id,
            "pending_segments": [{
                "start": 0.0, "end": 10.0, "provider": "pexels", "query": "x",
                "on_screen_text": "oi", "on_screen_text_style": None,
                "media_type": "video", "override_source": None,
            }],
        }

    def test_valid_window_is_saved(self, app_module, flask_client, monkeypatch):
        job_id = "job-text-window-ok"
        app_module._JOBS[job_id] = self._base_job(job_id)
        monkeypatch.setattr(app_module, "_start_assembly", lambda *a, **k: None)

        flask_client.post(f"/job/{job_id}/confirm-segments", data={
            "seg_0_on_screen_text": "oi",
            "seg_0_text_style_submitted": "1",
            "seg_0_text_start_offset": "2.0",
            "seg_0_text_end_offset": "6.5",
        })

        style = app_module._JOBS[job_id]["pending_segments"][0]["on_screen_text_style"]
        assert style["start_offset"] == 2.0
        assert style["end_offset"] == 6.5

    def test_invalid_window_end_before_start_is_dropped(self, app_module, flask_client, monkeypatch):
        job_id = "job-text-window-invalid"
        app_module._JOBS[job_id] = self._base_job(job_id)
        monkeypatch.setattr(app_module, "_start_assembly", lambda *a, **k: None)

        flask_client.post(f"/job/{job_id}/confirm-segments", data={
            "seg_0_on_screen_text": "oi",
            "seg_0_text_style_submitted": "1",
            "seg_0_text_start_offset": "8.0",
            "seg_0_text_end_offset": "1.0",
        })

        style = app_module._JOBS[job_id]["pending_segments"][0]["on_screen_text_style"]
        assert "start_offset" not in style
        assert "end_offset" not in style

    def test_blank_fields_mean_whole_segment_as_before(self, app_module, flask_client, monkeypatch):
        job_id = "job-text-window-blank"
        app_module._JOBS[job_id] = self._base_job(job_id)
        monkeypatch.setattr(app_module, "_start_assembly", lambda *a, **k: None)

        flask_client.post(f"/job/{job_id}/confirm-segments", data={
            "seg_0_on_screen_text": "oi",
            "seg_0_text_style_submitted": "1",
        })

        style = app_module._JOBS[job_id]["pending_segments"][0]["on_screen_text_style"]
        assert "start_offset" not in style
        assert "end_offset" not in style


class TestEditSegmentsPageResolution:
    """A página do editor precisa mandar a resolução real de saída
    (largura/altura) pro JS, pra ele escalar o texto do monitor do
    mesmo jeito que sai no vídeo final -- e a proporção do palco tem
    que bater com a orientação (retrato x paisagem)."""

    def _job(self, job_id, orientation, export_quality="1080p"):
        return {
            "job_id": job_id, "orientation": orientation, "export_quality": export_quality,
            "pending_segments": [{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "x"}],
            "segment_previews": [], "overlays": [], "assembly_error_segment_index": None,
        }

    def test_vertical_orientation_produces_portrait_resolution(self, app_module, flask_client):
        job_id = "job-res-vertical"
        app_module._JOBS[job_id] = self._job(job_id, "9:16")
        resp = flask_client.get(f"/job/{job_id}/edit-segments?modo=classico")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "VIDEO_TARGET_WIDTH = 1080" in html
        assert "VIDEO_TARGET_HEIGHT = 1920" in html

    def test_horizontal_orientation_produces_landscape_resolution(self, app_module, flask_client):
        job_id = "job-res-horizontal"
        app_module._JOBS[job_id] = self._job(job_id, "16:9", export_quality="720p")
        resp = flask_client.get(f"/job/{job_id}/edit-segments?modo=classico")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "VIDEO_TARGET_WIDTH = 1280" in html
        assert "VIDEO_TARGET_HEIGHT = 720" in html


class TestMultipartSizeLimitsFix:
    """O 413 ao confirmar segmentos: os limites novos do Flask/Werkzeug
    (MAX_FORM_MEMORY_SIZE / MAX_FORM_PARTS, ~500KB / 1000 campos por
    padrão) não podem mais barrar um envio grande."""

    def test_config_disables_form_memory_and_parts_limits(self, app_module):
        assert app_module.app.config["MAX_CONTENT_LENGTH"] is None
        assert app_module.app.config["MAX_FORM_MEMORY_SIZE"] is None
        assert app_module.app.config["MAX_FORM_PARTS"] is None

    def test_large_multipart_upload_does_not_get_413(self, app_module, flask_client):
        """~700KB de conteúdo num único campo de arquivo -- mais que o
        antigo limite padrão de 500KB do Werkzeug -- não pode dar 413."""
        job_id = "job-multipart-size"
        app_module._JOBS[job_id] = {"job_id": job_id, "pending_segments": [], "overlays": []}

        big_content = b"A" * (700 * 1024)
        data = {
            "source_mode": "upload",
            "overlay_file": (io_bytes(big_content), "big.bin"),
            "start": "0", "end": "5",
        }
        resp = flask_client.post(f"/job/{job_id}/add-overlay", data=data, content_type="multipart/form-data")
        assert resp.status_code != 413

    def test_many_form_fields_does_not_get_413(self, app_module, flask_client):
        """Mais de 1000 campos de formulário (o antigo limite padrão de
        MAX_FORM_PARTS) num único POST não pode dar 413."""
        job_id = "job-multipart-fields"
        app_module._JOBS[job_id] = {"job_id": job_id, "pending_segments": [], "overlays": []}

        data = {f"campo_{i}": "x" for i in range(1500)}
        data.update({"source_mode": "url", "overlay_url": "https://example.com/x.png", "start": "0", "end": "5"})
        resp = flask_client.post(f"/job/{job_id}/add-overlay", data=data)
        assert resp.status_code != 413


def io_bytes(content: bytes):
    import io
    return io.BytesIO(content)


class TestReuseJsonAsPastedText:
    """Pedido do usuário: no modo "usar áudio + JSON existente", também
    dá pra colar o texto do JSON direto, sem precisar de um arquivo
    .json."""

    def _make_audio_file(self, tmp_path, duration=5.0):
        path = str(tmp_path / "audio.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=duration={duration}", "-loglevel", "error", path],
            check=True,
        )
        return path

    def test_pasted_json_text_without_file_creates_job(self, app_module, flask_client, tmp_path):
        import json as jsonlib
        audio_path = self._make_audio_file(tmp_path)
        json_text = jsonlib.dumps({"segments": [{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "praia"}]})

        with open(audio_path, "rb") as af:
            resp = flask_client.post("/reuse-json", data={
                "audio_reuse": (af, "narracao.wav"),
                "json_reuse_text": json_text,
                "providers_reuse": ["pexels"],
            }, content_type="multipart/form-data")

        assert resp.status_code == 302
        job_id = resp.headers["Location"].split("/job/")[1].split("/")[0]
        assert app_module._JOBS[job_id]["reused_json_filename"] == "colado manualmente"

    def test_neither_file_nor_text_gives_clear_error(self, app_module, flask_client, tmp_path):
        audio_path = self._make_audio_file(tmp_path)
        with open(audio_path, "rb") as af:
            resp = flask_client.post("/reuse-json", data={
                "audio_reuse": (af, "narracao.wav"),
            }, content_type="multipart/form-data")

        assert resp.status_code == 200  # renderiza a página de novo com erro, não redireciona
        html = resp.get_data(as_text=True)
        assert "selecione o arquivo JSON ou cole o texto do JSON" in html

    def test_invalid_pasted_json_text_gives_clear_error_not_crash(self, app_module, flask_client, tmp_path):
        audio_path = self._make_audio_file(tmp_path)
        with open(audio_path, "rb") as af:
            resp = flask_client.post("/reuse-json", data={
                "audio_reuse": (af, "narracao.wav"),
                "json_reuse_text": "{isso nao e json valido",
            }, content_type="multipart/form-data")

        assert resp.status_code == 200
        assert "JSON inválido" in resp.get_data(as_text=True)

    def test_uploaded_file_still_works_as_before(self, app_module, flask_client, tmp_path):
        """O modo antigo (upload de arquivo .json) continua funcionando
        exatamente como era, sem precisar do campo de texto."""
        import json as jsonlib
        audio_path = self._make_audio_file(tmp_path)
        json_bytes = jsonlib.dumps({"segments": [{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "praia"}]}).encode()

        with open(audio_path, "rb") as af:
            resp = flask_client.post("/reuse-json", data={
                "audio_reuse": (af, "narracao.wav"),
                "json_reuse": (io_bytes(json_bytes), "meu_json_antigo.json"),
                "providers_reuse": ["pexels"],
            }, content_type="multipart/form-data")

        assert resp.status_code == 302
        job_id = resp.headers["Location"].split("/job/")[1].split("/")[0]
        assert app_module._JOBS[job_id]["reused_json_filename"] == "meu_json_antigo.json"

    def test_file_takes_priority_when_both_are_sent(self, app_module, flask_client, tmp_path):
        """Se por algum motivo os dois vierem preenchidos, o arquivo
        ganha prioridade (mesma prioridade que já existia implicitamente
        antes, já que só o arquivo era aceito)."""
        import json as jsonlib
        audio_path = self._make_audio_file(tmp_path)
        file_json = jsonlib.dumps({"segments": [{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "do arquivo"}]}).encode()
        text_json = jsonlib.dumps({"segments": [{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "do texto"}]})

        with open(audio_path, "rb") as af:
            resp = flask_client.post("/reuse-json", data={
                "audio_reuse": (af, "narracao.wav"),
                "json_reuse": (io_bytes(file_json), "arquivo.json"),
                "json_reuse_text": text_json,
                "providers_reuse": ["pexels"],
            }, content_type="multipart/form-data")

        assert resp.status_code == 302
        job_id = resp.headers["Location"].split("/job/")[1].split("/")[0]
        job = app_module._JOBS[job_id]
        assert job["reused_json_filename"] == "arquivo.json"
        assert job["pending_segments"][0]["query"] == "do arquivo"
