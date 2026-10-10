"""
Teste automatizado da ClientFactory e do caminho "de verdade" (orientado
por site_config) do video_assembler.py: sessão compartilhada entre
provedores, uma sessão por provedor, modo close_each_download,
visibilidade do navegador, fallback automático da API do Pexels pro
navegador, fallback entre provedores por ordem de prioridade, filtro de
orientação na busca, e resolução de saída conforme a orientação.
"""
import os
import shutil
import subprocess
import threading

import pytest
from PIL import Image

from prompt_builder import VideoSegment
from video_assembler import ClientFactory, VideoAssemblyError, _download_segment_with_fallbacks, _orientation_filter_kwargs, _probe_duration, assemble_video


@pytest.fixture
def fake_chrome_session(monkeypatch):
    """Substitui browser_session.ChromeSession por uma versão falsa, que
    só registra quantas vezes/com quais argumentos foi criada.
    """
    import browser_session

    created = []

    class FakeChromeSession:
        def __init__(self, headless, headers=None):
            created.append(headless)
            self.closed = False

        def close(self):
            self.closed = True

    monkeypatch.setattr(browser_session, "ChromeSession", FakeChromeSession)
    return created


class TestOrientationFilters:
    def test_pexels_landscape_and_portrait(self):
        assert _orientation_filter_kwargs("pexels", "16:9") == {"orientation": "landscape"}
        assert _orientation_filter_kwargs("pexels", "9:16") == {"orientation": "portrait"}

    def test_pixabay_horizontal_and_vertical(self):
        assert _orientation_filter_kwargs("pixabay", "16:9") == {"orientation": "horizontal"}
        assert _orientation_filter_kwargs("pixabay", "9:16") == {"orientation": "vertical"}

    def test_vistacreate_has_no_orientation_support(self):
        assert _orientation_filter_kwargs("vistacreate", "16:9") == {}

    def test_no_orientation_given_returns_empty(self):
        assert _orientation_filter_kwargs("pexels", None) == {}


class TestClientFactoryBrowserModes:
    def test_shared_across_providers_uses_one_session_for_all(self, fake_chrome_session):
        cfg = {"browser_shared_across_providers": True, "browser_visible": False, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)
        factory._use_browser_for.add("pexels")  # pula a tentativa de API, direto pro navegador

        c1 = factory.get_client("pixabay")
        c2 = factory.get_client("magnific")
        c3 = factory.get_client("mixkit")

        assert len(fake_chrome_session) == 1, "deveria ter criado só 1 ChromeSession pra todos os provedores"
        assert c1.session is c2.session is c3.session

        factory.close_all()
        assert c1.session.closed

    def test_one_session_per_provider_when_not_shared(self, fake_chrome_session):
        cfg = {"browser_shared_across_providers": False, "browser_visible": True, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)
        factory._use_browser_for.add("pexels")

        c1 = factory.get_client("pixabay")
        c2 = factory.get_client("magnific")
        c1_again = factory.get_client("pixabay")

        assert len(fake_chrome_session) == 2, "deveria ter criado 1 sessão por provedor"
        assert c1 is c1_again, "deveria reaproveitar o cliente na segunda chamada pro mesmo provedor"
        assert fake_chrome_session == [False, False], "browser_visible=True deveria passar headless=False"

    def test_close_each_download_never_reuses(self, fake_chrome_session):
        cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "close_each_download"}
        factory = ClientFactory(cfg)
        factory._use_browser_for.add("pexels")

        c1 = factory.get_client("pixabay")
        c2 = factory.get_client("pixabay")

        assert len(fake_chrome_session) == 2, "close_each_download não deveria reaproveitar nunca"
        assert c1 is not c2


class TestPexelsApiFallback:
    def test_falls_back_to_browser_when_api_fails(self, fake_chrome_session, tmp_path, monkeypatch):
        downloads_dir = str(tmp_path / "downloads")
        os.makedirs(downloads_dir)
        source_clip = str(tmp_path / "source.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=320x240:rate=25:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", source_clip],
            check=True,
        )

        import pexels_api_client

        class FakeFailingAPIClient:
            def search_all(self, **kw):
                raise pexels_api_client.PexelsAPIClientError("chave inválida (simulado)")

        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", FakeFailingAPIClient)

        class FakeVideo:
            id = "v1"
            premium = False

        browser_calls = []

        class FakeBrowserPexelsClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, max_pages=1, **kw):
                browser_calls.append(query)
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "downloaded.mp4")
                shutil.copy(source_clip, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeBrowserPexelsClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)

        cfg = {"browser_shared_across_providers": False, "browser_visible": False,
               "browser_mode": "reuse_session", "pexels_api_fallback_to_browser": True}
        factory = ClientFactory(cfg)
        segment = VideoSegment(start=0.0, end=3.0, provider="pexels", query="dog")

        path = _download_segment_with_fallbacks(segment, downloads_dir, factory, ["pexels", "pixabay"], "16:9")[0]

        assert os.path.exists(path)
        assert browser_calls, "deveria ter usado o cliente de navegador depois que a API falhou"

        # o fallback é "pegajoso": a próxima chamada já vai direto pro navegador
        assert "pexels" in factory._use_browser_for
        assert isinstance(factory.get_client("pexels"), FakeBrowserPexelsClient)


class TestPixabayApiFallback:
    def test_falls_back_to_browser_when_api_fails(self, fake_chrome_session, tmp_path, monkeypatch):
        downloads_dir = str(tmp_path / "downloads")
        os.makedirs(downloads_dir)
        source_clip = str(tmp_path / "source.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=320x240:rate=25:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", source_clip],
            check=True,
        )

        import pixabay_api_client

        class FakeFailingAPIClient:
            def search_all(self, **kw):
                raise pixabay_api_client.PixabayAPIClientError("chave inválida (simulado)")

        monkeypatch.setattr(pixabay_api_client, "PixabayAPIClient", FakeFailingAPIClient)

        class FakeVideo:
            id = "v1"
            premium = False

        browser_calls = []

        class FakeBrowserPixabayClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, max_pages=1, **kw):
                browser_calls.append(query)
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "downloaded.mp4")
                shutil.copy(source_clip, dest)
                return dest

        import pixabay.pixabay_client as pixabay_mod
        monkeypatch.setattr(pixabay_mod, "PixabayClient", FakeBrowserPixabayClient)
        monkeypatch.setattr(pixabay_mod, "DEFAULT_HEADERS", {}, raising=False)

        cfg = {"browser_shared_across_providers": False, "browser_visible": False,
               "browser_mode": "reuse_session", "pixabay_api_fallback_to_browser": True}
        factory = ClientFactory(cfg)
        segment = VideoSegment(start=0.0, end=3.0, provider="pixabay", query="dog")

        path = _download_segment_with_fallbacks(segment, downloads_dir, factory, ["pixabay", "pexels"], "16:9")[0]

        assert os.path.exists(path)
        assert browser_calls, "deveria ter usado o cliente de navegador depois que a API do Pixabay falhou"
        assert "pixabay" in factory._use_browser_for
        assert isinstance(factory.get_client("pixabay"), FakeBrowserPixabayClient)


class TestProviderPriorityFallback:
    def test_falls_back_to_next_provider_when_original_finds_nothing(self, fake_chrome_session, tmp_path, monkeypatch):
        downloads_dir = str(tmp_path / "downloads")
        os.makedirs(downloads_dir)
        source_clip = str(tmp_path / "source.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=320x240:rate=25:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", source_clip],
            check=True,
        )

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeMagnificClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, max_pages=1, **kw):
                return []  # nunca acha nada

        class FakePixabayClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(source_clip, dest)
                return dest

        import magnific.magnific_client as magnific_mod
        import pixabay.pixabay_client as pixabay_mod
        monkeypatch.setattr(magnific_mod, "MagnificClient", FakeMagnificClient)
        monkeypatch.setattr(magnific_mod, "DEFAULT_HEADERS", {}, raising=False)
        monkeypatch.setattr(pixabay_mod, "PixabayClient", FakePixabayClient)
        monkeypatch.setattr(pixabay_mod, "DEFAULT_HEADERS", {}, raising=False)

        cfg = {"browser_shared_across_providers": False, "browser_visible": False,
               "browser_mode": "reuse_session", "pexels_api_fallback_to_browser": True}
        factory = ClientFactory(cfg)
        segment = VideoSegment(start=0.0, end=3.0, provider="magnific", query="algo bem específico")

        path = _download_segment_with_fallbacks(segment, downloads_dir, factory, ["magnific", "pixabay", "mixkit"], "16:9")[0]
        assert os.path.exists(path)


class TestOrientationAffectsOutputResolution:
    def _make_fake_client_and_clip(self, tmp_path):
        source_clip = str(tmp_path / "source.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=640x360:rate=25:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", source_clip],
            check=True,
        )

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeSession:
            def close(self):
                pass

        class FakeClient:
            session = FakeSession()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(source_clip, dest)
                return dest

        return FakeClient

    def _video_dimensions(self, path):
        import json
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_streams", "-print_format", "json", path],
            capture_output=True, text=True, check=True,
        )
        info = json.loads(probe.stdout)
        video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
        return video_stream["width"], video_stream["height"]

    def test_legacy_path_with_explicit_get_client_fn_stays_landscape(self, tmp_path, synthetic_audio):
        FakeClient = self._make_fake_client_and_clip(tmp_path)
        segments = [VideoSegment(start=0.0, end=3.0, provider="pexels", query="x")]
        output_path = str(tmp_path / "out" / "legacy.mp4")

        assemble_video(
            segments, synthetic_audio, output_path, str(tmp_path / "job_legacy"),
            get_client_fn=lambda p: FakeClient(),
        )

        assert self._video_dimensions(output_path) == (1920, 1080)

    def test_site_config_path_with_9_16_produces_vertical_video(self, tmp_path, synthetic_audio, fake_chrome_session, monkeypatch):
        FakeClient = self._make_fake_client_and_clip(tmp_path)

        import pexels_api_client

        class FakePexelsAPIClientNoArgs(FakeClient):
            pass

        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", FakePexelsAPIClientNoArgs)

        segments = [VideoSegment(start=0.0, end=3.0, provider="pexels", query="x")]
        output_path = str(tmp_path / "out" / "vertical.mp4")

        site_cfg = {
            "orientation": "9:16",
            "provider_priority": ["pexels", "pixabay", "magnific", "mixkit", "vistacreate"],
            "pexels_api_fallback_to_browser": True,
            "browser_visible": False,
            "browser_shared_across_providers": False,
            "browser_mode": "reuse_session",
        }

        assemble_video(segments, synthetic_audio, output_path, str(tmp_path / "job_vertical"), site_cfg=site_cfg)

        assert self._video_dimensions(output_path) == (1080, 1920)


class TestAssemblyFetchConcurrency:
    """Prova, com tempo de relógio real, que a montagem final também
    busca/baixa vários segmentos em PARALELO no caminho "de verdade"
    (site_cfg) — resolve o mesmo tipo de gargalo da pré-busca de
    prévias, mas na etapa de montagem propriamente dita (relevante pra
    qualquer segmento que precise buscar de novo em vez de reaproveitar
    a prévia: termo editado, ou prévia que falhou)."""

    def test_segments_are_processed_in_parallel_not_sequentially(self, tmp_path, synthetic_audio, fake_chrome_session, monkeypatch):
        """Confirma que as buscas realmente rodam sobrepostas no tempo,
        não uma depois da outra — em vez de comparar tempo total de
        parede (que numa máquina com poucos núcleos fica dominado pelo
        trabalho de CPU da normalização, mascarando o ganho real da
        parte de rede/busca).
        """
        import threading
        import time as _time

        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        SEARCH_DELAY = 0.4
        NUM_SEGMENTS = 4
        call_windows = []
        lock = threading.Lock()

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeSlowClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                start = _time.time()
                _time.sleep(SEARCH_DELAY)
                end = _time.time()
                with lock:
                    call_windows.append((start, end))
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeSlowClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)

        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))

        segments = [
            VideoSegment(start=float(i * 3), end=float((i + 1) * 3), provider="pexels", query=f"termo {i}")
            for i in range(NUM_SEGMENTS)
        ]
        site_cfg = {
            "orientation": "16:9", "export_quality": "480p",
            "provider_priority": ["pexels", "pixabay", "magnific", "mixkit", "vistacreate"],
            "pexels_api_fallback_to_browser": True, "magnific_only_free": True,
            "browser_visible": False, "browser_shared_across_providers": False,
            "browser_mode": "reuse_session", "assembly_fetch_concurrency": 4,
        }
        output_path = str(tmp_path / "out" / "final.mp4")

        assemble_video(segments, synthetic_audio, output_path, str(tmp_path / "job"), site_cfg=site_cfg)

        assert len(call_windows) == NUM_SEGMENTS
        # confirma que pelo menos duas buscas se sobrepuseram no tempo
        # (rodaram ao mesmo tempo) — prova de paralelismo de verdade,
        # independente de quantos núcleos de CPU a máquina que roda o
        # teste tem (o que afetaria só a etapa de normalização, não a
        # de busca em si).
        overlapping_pairs = 0
        for i in range(len(call_windows)):
            for j in range(i + 1, len(call_windows)):
                s1, e1 = call_windows[i]
                s2, e2 = call_windows[j]
                if s1 < e2 and s2 < e1:
                    overlapping_pairs += 1
        assert overlapping_pairs > 0, (
            f"nenhuma busca se sobrepôs no tempo — parecem ter rodado em sequência, não em paralelo. "
            f"Janelas: {call_windows}"
        )

    def test_default_assembly_concurrency_is_three(self):
        from site_config import DEFAULT_CONFIG
        assert DEFAULT_CONFIG["assembly_fetch_concurrency"] == 3

    def test_segment_order_is_preserved_regardless_of_completion_order(self, tmp_path, fake_chrome_session, monkeypatch):
        """Mesmo com conclusão fora de ordem (paralelo, no caminho "de
        verdade"), o vídeo final precisa ter os segmentos na ORDEM CERTA
        (por tempo), não na ordem em que cada busca terminou."""
        import random
        import time as _time

        # audio proprio com 12s (a fixture synthetic_audio tem ~9.47s
        # fixos, curto demais pros 3 segmentos de 4s = 12s deste teste —
        # usar ela cortaria o video final antes do terceiro segmento)
        audio_path = str(tmp_path / "audio.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=12", "-loglevel", "error", audio_path], check=True)

        colors = {"red": (254, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 254)}
        clips = {}
        for name in colors:
            path = str(tmp_path / f"{name}.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color={name}:size=320x240:rate=25:duration=4",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", path], check=True,
            )
            clips[name] = path

        class FakeVideo:
            def __init__(self, color):
                self.id = color
                self.premium = False

        class FakeClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                # cada cor "demora" um tempo diferente e ALEATORIO pra
                # embaralhar de propósito a ordem de conclusão
                _time.sleep(random.uniform(0.05, 0.3))
                return [FakeVideo(query)]

            def download_video(self, video, output_dir, **kw):
                # nome de arquivo baseado no ID (como os clientes reais do
                # toolkit fazem) — com downloads concorrentes escrevendo
                # na MESMA pasta compartilhada, um nome fixo faria vídeos
                # diferentes se sobrescreverem um ao outro.
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{video.id}.mp4")
                shutil.copy(clips[video.id], dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))

        segments = [
            VideoSegment(start=0.0, end=4.0, provider="pexels", query="red"),
            VideoSegment(start=4.0, end=8.0, provider="pexels", query="green"),
            VideoSegment(start=8.0, end=12.0, provider="pexels", query="blue"),
        ]
        site_cfg = {
            "orientation": "16:9", "export_quality": "480p",
            "provider_priority": ["pexels", "pixabay", "magnific", "mixkit", "vistacreate"],
            "pexels_api_fallback_to_browser": True, "magnific_only_free": True,
            "browser_visible": False, "browser_shared_across_providers": False,
            "browser_mode": "reuse_session", "assembly_fetch_concurrency": 3,
        }
        output_path = str(tmp_path / "out" / "final.mp4")
        assemble_video(segments, audio_path, output_path, str(tmp_path / "job"), site_cfg=site_cfg)

        def sample(path, t):
            frame = f"{path}_f{t}.png"
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("RGB")
            w, h = img.size
            return img.getpixel((w // 2, h // 2))

        def assert_close(actual, expected, tolerance=5):
            assert all(abs(a - e) <= tolerance for a, e in zip(actual, expected)), f"{actual} não é próximo de {expected}"

        assert_close(sample(output_path, 2.0), colors["red"])
        assert_close(sample(output_path, 6.0), colors["green"])
        assert_close(sample(output_path, 10.0), colors["blue"])


class TestCancelAssembly:
    """Cobre `cancel_check` de assemble_video() (caminho "de verdade") —
    permite cancelar um job em andamento em vez de precisar esperar
    terminar ou derrubar o servidor."""

    def test_cancel_check_true_from_start_raises_clear_error(self, tmp_path, synthetic_audio, fake_chrome_session, monkeypatch):
        import time as _time

        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeSlowClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                _time.sleep(0.3)
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeSlowClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", lambda: (_ for _ in ()).throw(ValueError("sem chave")))

        segments = [VideoSegment(start=float(i * 3), end=float((i + 1) * 3), provider="pexels", query=f"x{i}") for i in range(3)]
        site_cfg = {
            "orientation": "16:9", "export_quality": "480p",
            "provider_priority": ["pexels", "pixabay", "magnific", "mixkit", "vistacreate"],
            "pexels_api_fallback_to_browser": True, "magnific_only_free": True,
            "browser_visible": False, "browser_shared_across_providers": False,
            "browser_mode": "reuse_session", "assembly_fetch_concurrency": 2,
        }
        output_path = str(tmp_path / "out" / "final.mp4")

        with pytest.raises(VideoAssemblyError, match="cancelada"):
            assemble_video(
                segments, synthetic_audio, output_path, str(tmp_path / "job"),
                site_cfg=site_cfg, cancel_check=lambda: True,
            )
        assert not os.path.exists(output_path)

    def test_cancel_check_false_completes_normally(self, tmp_path, synthetic_audio, fake_chrome_session, monkeypatch):
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

        segments = [VideoSegment(start=0.0, end=9.469, provider="pexels", query="x")]
        site_cfg = {
            "orientation": "16:9", "export_quality": "480p",
            "provider_priority": ["pexels", "pixabay", "magnific", "mixkit", "vistacreate"],
            "pexels_api_fallback_to_browser": True, "magnific_only_free": True,
            "browser_visible": False, "browser_shared_across_providers": False,
            "browser_mode": "reuse_session", "assembly_fetch_concurrency": 2,
        }
        output_path = str(tmp_path / "out" / "final.mp4")

        assemble_video(
            segments, synthetic_audio, output_path, str(tmp_path / "job"),
            site_cfg=site_cfg, cancel_check=lambda: False,
        )
        assert os.path.exists(output_path)


class TestProviderAttemptTimeout:
    """Pedido explícito: "se um vídeo tiver demorando muito, usa outra
    fonte pra agilizar". Cobre `provider_attempt_timeout_seconds` —
    desiste de um provedor travado/lento e cai pro próximo da lista de
    prioridade, em vez de ficar esperando indefinidamente (limitado só
    pelos timeouts de rede/Selenium, que podem ser bem mais longos)."""

    def test_gives_up_on_stuck_provider_and_uses_next_in_priority(self, tmp_path, fake_chrome_session, monkeypatch):
        import time as _time

        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=orange:size=320x240:rate=25:duration=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeStuckClient:
            """Simula um banco travado -- nunca termina de responder
            dentro de um tempo razoável (bem mais que qualquer timeout
            configurado no teste)."""
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                _time.sleep(30)
                return [FakeVideo()]

        class FakeFastWorkingClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        class FakePexelsAPIClientRaisesOnInit:
            def __init__(self):
                raise ValueError("sem chave")

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeStuckClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", FakePexelsAPIClientRaisesOnInit)

        import pixabay.pixabay_client as pixabay_mod
        monkeypatch.setattr(pixabay_mod, "PixabayClient", FakeFastWorkingClient)

        segment = VideoSegment(start=0.0, end=4.0, provider="pexels", query="x")
        cfg = {
            "browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session",
            "provider_priority": ["pexels", "pixabay", "magnific", "mixkit", "vistacreate"],
            "pexels_api_fallback_to_browser": True, "magnific_only_free": True,
            "provider_attempt_timeout_seconds": 2,
        }
        factory = ClientFactory(cfg)

        t0 = _time.time()
        path = _download_segment_with_fallbacks(segment, str(tmp_path / "downloads"), factory, cfg["provider_priority"], orientation="16:9")[0]
        elapsed = _time.time() - t0

        assert elapsed < 10, f"deveria ter desistido do provedor travado rápido (timeout=2s), mas levou {elapsed:.2f}s"
        assert os.path.exists(path)

    def test_fast_provider_unaffected_by_timeout_setting(self, tmp_path, fake_chrome_session, monkeypatch):
        """O timeout não deveria interferir em nada quando o provedor
        responde normalmente, mesmo com um timeout curto configurado."""
        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=orange:size=320x240:rate=25:duration=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeFastClient:
            def __init__(self, session=None):
                self.session = session

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        class FakePexelsAPIClientRaisesOnInit:
            def __init__(self):
                raise ValueError("sem chave")

        import pexels.pexels_client as pexels_mod
        monkeypatch.setattr(pexels_mod, "PexelsClient", FakeFastClient)
        monkeypatch.setattr(pexels_mod, "DEFAULT_HEADERS", {}, raising=False)
        import pexels_api_client
        monkeypatch.setattr(pexels_api_client, "PexelsAPIClient", FakePexelsAPIClientRaisesOnInit)

        segment = VideoSegment(start=0.0, end=4.0, provider="pexels", query="x")
        cfg = {
            "browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session",
            "provider_priority": ["pexels", "pixabay", "magnific", "mixkit", "vistacreate"],
            "pexels_api_fallback_to_browser": True, "magnific_only_free": True,
            "provider_attempt_timeout_seconds": 25,
        }
        factory = ClientFactory(cfg)

        path = _download_segment_with_fallbacks(segment, str(tmp_path / "downloads"), factory, cfg["provider_priority"], orientation="16:9")[0]
        assert os.path.exists(path)


class TestFillDurationWithMultipleScenesInsteadOfLooping:
    """Pedido explícito: "se a cena for muito pequena não repita e sim
    ache chances de colocar além (cena extra) ou use o filtro de tempo
    pra buscar cenas mais adequadas". Cobre `_duration_filter_kwargs`
    (nunca pede vídeo mais curto que o segmento), e as duas funções
    novas: `_search_and_download_filling_duration` (busca cenas
    diferentes até completar o tempo) e `_normalize_multi_clip`
    (concatena as cenas encontradas num único segmento final)."""

    def test_duration_filter_never_requests_shorter_than_segment(self):
        from video_assembler import _duration_filter_kwargs
        kwargs = _duration_filter_kwargs("pexels", 6.0)
        assert kwargs["min_duration"] >= 6.0

    def test_duration_filter_empty_for_unsupported_provider(self):
        from video_assembler import _duration_filter_kwargs
        assert _duration_filter_kwargs("pixabay", 6.0) == {}

    def test_search_and_download_filling_duration_uses_multiple_clips_when_needed(self, tmp_path):
        from video_assembler import _search_and_download_filling_duration
        from prompt_builder import VideoSegment

        source_dir = tmp_path / "source"
        download_dir = tmp_path / "downloads"
        source_dir.mkdir()
        download_dir.mkdir()

        clips = {}
        for name in ("a", "b", "c"):
            path = str(source_dir / f"{name}.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=3",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", path], check=True,
            )
            clips[name] = path

        class FakeVideo:
            def __init__(self, name):
                self.id = name
                self.premium = False

        class FakeClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo("a"), FakeVideo("b"), FakeVideo("c")]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{video.id}.mp4")
                shutil.copy(clips[video.id], dest)
                return dest

        segment = VideoSegment(start=0.0, end=8.0, provider="pexels", query="x")
        paths = _search_and_download_filling_duration(segment, str(download_dir), FakeClient())
        assert len(paths) == 3, f"deveria ter usado os 3 clipes (3+3+3=9s >= 8s), usou {len(paths)}"

    def test_search_and_download_filling_duration_stops_as_soon_as_enough(self, tmp_path):
        """Quando o primeiro clipe já é suficiente sozinho, não deveria
        baixar nenhum extra à toa."""
        from video_assembler import _search_and_download_filling_duration
        from prompt_builder import VideoSegment

        source_dir = tmp_path / "source"
        download_dir = tmp_path / "downloads"
        source_dir.mkdir()
        download_dir.mkdir()

        path_a = str(source_dir / "a.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", path_a], check=True,
        )

        download_calls = []

        class FakeVideo:
            def __init__(self, name):
                self.id = name
                self.premium = False

        class FakeClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo("a"), FakeVideo("b"), FakeVideo("c")]

            def download_video(self, video, output_dir, **kw):
                download_calls.append(video.id)
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{video.id}.mp4")
                shutil.copy(path_a, dest)
                return dest

        segment = VideoSegment(start=0.0, end=2.0, provider="pexels", query="x")
        paths = _search_and_download_filling_duration(segment, str(download_dir), FakeClient())
        assert len(paths) == 1
        assert download_calls == ["a"], "não deveria ter baixado clipes extras quando o primeiro já bastava"

    def test_normalize_multi_clip_shows_both_different_scenes(self, tmp_path):
        """A prova visual mais importante: as DUAS cenas diferentes
        precisam aparecer no vídeo final, não uma repetida duas vezes."""
        from video_assembler import _normalize_multi_clip, _probe_duration
        from PIL import Image

        red = str(tmp_path / "red.mp4")
        blue = str(tmp_path / "blue.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", red], check=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=320x240:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", blue], check=True)

        output = str(tmp_path / "saida.mp4")
        _normalize_multi_clip([red, blue], target_duration=6.0, output_path=output, work_dir=str(tmp_path), target_width=320, target_height=240)

        duration = _probe_duration(output)
        assert abs(duration - 6.0) < 0.2

        def sample(path, t):
            frame = f"{path}_{t}.png"
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("RGB")
            w, h = img.size
            return img.getpixel((w // 2, h // 2))

        cor_inicio = sample(output, 1.0)
        cor_fim = sample(output, 5.0)
        assert cor_inicio[0] > 200 and cor_inicio[2] < 50, "deveria ser vermelho no início"
        assert cor_fim[2] > 200 and cor_fim[0] < 50, "deveria ser azul no fim"

    def test_normalize_multi_clip_single_clip_behaves_like_normalize_clip(self, tmp_path):
        from video_assembler import _normalize_multi_clip, _probe_duration

        red = str(tmp_path / "red.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", red], check=True)

        output = str(tmp_path / "saida.mp4")
        _normalize_multi_clip([red], target_duration=5.0, output_path=output, work_dir=str(tmp_path), target_width=320, target_height=240)
        assert abs(_probe_duration(output) - 5.0) < 0.2

    def test_normalize_multi_clip_loops_last_clip_when_still_short(self, tmp_path):
        """Último recurso: se mesmo somando todos os clipes disponíveis
        ainda faltar tempo, o último repete em loop pro resto."""
        from video_assembler import _normalize_multi_clip, _probe_duration

        red = str(tmp_path / "red.mp4")
        blue = str(tmp_path / "blue.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", red], check=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=320x240:rate=25:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", blue], check=True)

        output = str(tmp_path / "saida.mp4")
        _normalize_multi_clip([red, blue], target_duration=10.0, output_path=output, work_dir=str(tmp_path), target_width=320, target_height=240)
        assert abs(_probe_duration(output) - 10.0) < 0.2

    def test_intermediate_pieces_are_cleaned_up_after_concat(self, tmp_path):
        """Regressão: os arquivos intermediários de cada pedaço (cada um
        já recodificado na resolução final) nunca eram removidos depois
        da concatenação — um jeito NOVO de acumular lixo em disco que
        não existia antes dessa funcionalidade (antes, um segmento só
        gerava o próprio arquivo final, nada intermediário)."""
        import glob
        from video_assembler import _normalize_multi_clip, _probe_duration

        red = str(tmp_path / "red.mp4")
        blue = str(tmp_path / "blue.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", red], check=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=320x240:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", blue], check=True)

        output = str(tmp_path / "saida.mp4")
        _normalize_multi_clip([red, blue], target_duration=6.0, output_path=output, work_dir=str(tmp_path), target_width=320, target_height=240)

        assert os.path.exists(output)
        assert abs(_probe_duration(output) - 6.0) < 0.2

        leftover = glob.glob(str(tmp_path / "_multiclip_piece_*"))
        assert leftover == [], f"deveria ter limpo todos os pedaços intermediários, sobraram: {leftover}"


class TestUsedClipsTracker:
    """Pedido explícito, esclarecido em Q&A: "não repetir um clipe que
    meu sistema já puxou antes (histórico)" — a mesma cena não deveria
    aparecer em trechos DIFERENTES do vídeo final, não só evitar
    repetição dentro de um único trecho (isso já era coberto por
    `_search_and_download_filling_duration`)."""

    def test_claim_and_release_basic(self):
        from video_assembler import UsedClipsTracker

        tracker = UsedClipsTracker()
        assert tracker.try_claim("v1") is True
        assert tracker.try_claim("v1") is False
        assert tracker.try_claim("v2") is True

        tracker.release("v1")
        assert tracker.try_claim("v1") is True

    def test_concurrent_claims_on_same_id_only_one_succeeds(self):
        """Prova de ausência de condição de corrida: 20 threads
        disputando o MESMO vídeo ao mesmo tempo — só 1 pode vencer."""
        from video_assembler import UsedClipsTracker

        tracker = UsedClipsTracker()
        resultados = []

        def worker():
            resultados.append(tracker.try_claim("concorrido"))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert resultados.count(True) == 1
        assert resultados.count(False) == 19

    def test_different_segments_prefer_different_scenes_over_reusing(self, tmp_path):
        """O comportamento principal: dois segmentos com a MESMA busca
        deveriam pegar cenas DIFERENTES, não repetir a mesma."""
        from video_assembler import _search_and_download_filling_duration, UsedClipsTracker
        from prompt_builder import VideoSegment

        source_dir = tmp_path / "source"
        download_dir = tmp_path / "downloads"
        source_dir.mkdir()
        download_dir.mkdir()

        clips = {}
        for name in ("a", "b", "c"):
            path = str(source_dir / f"{name}.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=3",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", path], check=True,
            )
            clips[name] = path

        class FakeVideo:
            def __init__(self, name):
                self.id = name
                self.premium = False

        class FakeClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo("a"), FakeVideo("b"), FakeVideo("c")]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{video.id}.mp4")
                shutil.copy(clips[video.id], dest)
                return dest

        tracker = UsedClipsTracker()
        client = FakeClient()

        segment1 = VideoSegment(start=0.0, end=3.0, provider="pexels", query="x")
        paths1 = _search_and_download_filling_duration(segment1, str(download_dir), client, used_tracker=tracker)
        assert [os.path.basename(p) for p in paths1] == ["a.mp4"]

        segment2 = VideoSegment(start=3.0, end=6.0, provider="pexels", query="x")
        paths2 = _search_and_download_filling_duration(segment2, str(download_dir), client, used_tracker=tracker)
        assert [os.path.basename(p) for p in paths2] == ["b.mp4"], "deveria ter pulado 'a' (já usado) e pego 'b'"

    def test_falls_back_to_reuse_when_no_new_option_available(self, tmp_path):
        """Não deveria FALHAR o segmento só porque a única opção
        disponível já foi usada em outro lugar — reusar é melhor que
        não completar o trecho de jeito nenhum."""
        from video_assembler import _search_and_download_filling_duration, UsedClipsTracker
        from prompt_builder import VideoSegment

        source_dir = tmp_path / "source"
        download_dir = tmp_path / "downloads"
        source_dir.mkdir()
        download_dir.mkdir()

        path_a = str(source_dir / "a.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", path_a], check=True,
        )

        class FakeVideo:
            def __init__(self, name):
                self.id = name
                self.premium = False

        class FakeClientOnlyOneOption:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo("a")]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{video.id}.mp4")
                shutil.copy(path_a, dest)
                return dest

        tracker = UsedClipsTracker()
        client = FakeClientOnlyOneOption()

        segment1 = VideoSegment(start=0.0, end=3.0, provider="pexels", query="x")
        paths1 = _search_and_download_filling_duration(segment1, str(download_dir), client, used_tracker=tracker)
        assert [os.path.basename(p) for p in paths1] == ["a.mp4"]

        segment2 = VideoSegment(start=3.0, end=6.0, provider="pexels", query="x")
        paths2 = _search_and_download_filling_duration(segment2, str(download_dir), client, used_tracker=tracker)
        assert [os.path.basename(p) for p in paths2] == ["a.mp4"], "sem opção nova, deveria reusar em vez de falhar"

    def test_failed_download_releases_the_claim(self, tmp_path):
        """Se o download de um candidato reservado falhar, a reserva
        precisa ser liberada — senão aquele vídeo ficaria bloqueado pra
        sempre mesmo nunca tendo sido usado de verdade."""
        from video_assembler import _search_and_download_filling_duration, UsedClipsTracker
        from prompt_builder import VideoSegment

        source_dir = tmp_path / "source"
        download_dir = tmp_path / "downloads"
        source_dir.mkdir()
        download_dir.mkdir()

        path_b = str(source_dir / "b.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=320x240:rate=25:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", path_b], check=True,
        )

        class FakeVideo:
            def __init__(self, name):
                self.id = name
                self.premium = False

        class FakeClientAFails:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo("a"), FakeVideo("b")]

            def download_video(self, video, output_dir, **kw):
                if video.id == "a":
                    raise RuntimeError("link quebrado (simulado)")
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{video.id}.mp4")
                shutil.copy(path_b, dest)
                return dest

        tracker = UsedClipsTracker()
        segment = VideoSegment(start=0.0, end=3.0, provider="pexels", query="x")
        paths = _search_and_download_filling_duration(segment, str(download_dir), FakeClientAFails(), used_tracker=tracker)
        assert [os.path.basename(p) for p in paths] == ["b.mp4"]
        assert tracker.try_claim("a") is True, "a reserva de 'a' deveria ter sido liberada após o download falhar"



class TestApplyOverlays:
    """Pedido do usuário: sobrepor imagem/vídeo em cima do vídeo final,
    com posição, tamanho e janela de tempo próprios (podendo atravessar
    vários trechos, ou ficar restrito a uma janela específica)."""

    def test_no_overlays_just_copies_base_video(self, tmp_path):
        from video_assembler import apply_overlays, _probe_duration

        base = str(tmp_path / "base.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=320x240:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", base], check=True)
        output = str(tmp_path / "saida.mp4")

        apply_overlays(base, [], output, target_width=320)
        assert os.path.exists(output)
        assert abs(_probe_duration(output) - 3.0) < 0.2

    def test_image_overlay_appears_only_within_its_time_window(self, tmp_path):
        from video_assembler import apply_overlays, _probe_duration
        from PIL import Image

        base = str(tmp_path / "base.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x480:rate=25:duration=6", "-f", "lavfi", "-i", "sine=duration=6", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-loglevel", "error", base], check=True)

        logo = str(tmp_path / "logo.png")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=200x200", "-frames:v", "1", "-loglevel", "error", logo], check=True)

        output = str(tmp_path / "saida.mp4")
        overlays = [{"resolved_path": logo, "media_type": "image", "start": 2.0, "end": 4.0, "position": "top-right", "size_percent": 25}]
        apply_overlays(base, overlays, output, target_width=640)

        assert abs(_probe_duration(output) - 6.0) < 0.2

        def sample_top_right(t):
            frame = str(tmp_path / f"frame_{t}.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", output, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("RGB")
            # overlay de 25% de 640px = 160px, margem de 20px -> ocupa
            # x:[460,620] y:[20,180]. Amostra bem no meio dessa área.
            return img.getpixel((540, 100))

        antes = sample_top_right(1)
        dentro = sample_top_right(3)
        depois = sample_top_right(5)
        assert antes[0] < 100, "antes da janela, não deveria ter o logo vermelho"
        assert dentro[0] > 200 and dentro[1] < 50, "dentro da janela, deveria ter o logo vermelho"
        assert depois[0] < 100, "depois da janela, o logo não deveria mais aparecer"

    def test_video_overlay_loops_to_fill_its_window_and_multiple_overlays_together(self, tmp_path):
        from video_assembler import apply_overlays, _probe_duration
        from PIL import Image

        base = str(tmp_path / "base.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=640x480:rate=25:duration=8", "-f", "lavfi", "-i", "sine=duration=8", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-loglevel", "error", base], check=True)

        overlay_video = str(tmp_path / "overlay_video.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=yellow:size=100x100:rate=25:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", overlay_video], check=True)

        logo = str(tmp_path / "logo.png")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=white:size=80x80", "-frames:v", "1", "-loglevel", "error", logo], check=True)

        output = str(tmp_path / "saida.mp4")
        overlays = [
            {"resolved_path": overlay_video, "media_type": "video", "start": 0.0, "end": 6.0, "position": "bottom-left", "size_percent": 20},
            {"resolved_path": logo, "media_type": "image", "start": 0.0, "end": 8.0, "position": "top-right", "size_percent": 15},
        ]
        apply_overlays(base, overlays, output, target_width=640)

        assert abs(_probe_duration(output) - 8.0) < 0.2, "overlay de vídeo em loop não pode esticar a duração final"

        def sample_bottom_left(t):
            frame = str(tmp_path / f"bl_{t}.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", output, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("RGB")
            # overlay de 20% de 640px = 128px, margem de 20px -> ocupa
            # x:[20,148] y:[332,460] (em vídeo 640x480). Amostra bem no
            # meio dessa área.
            return img.getpixel((80, 395))

        # video overlay (janela 0-6s, clipe de 2s) -- deveria estar
        # amarelo em t=5 (dentro do 3o loop) e sumido em t=7 (fora da janela)
        assert sample_bottom_left(5)[2] < 50, "em t=5s (dentro da janela, no meio de um loop), deveria ser amarelo"
        assert sample_bottom_left(7)[0] < 100 and sample_bottom_left(7)[2] > 100, "em t=7s (fora da janela), deveria voltar a ser só o fundo azul"


class TestResolveOverlaySource:
    """Fonte de um overlay: upload, link direto, link de post específico
    (reaproveitado de _resolve_override_source), ou busca de verdade
    num banco (modo novo, "provider_search")."""

    def test_local_file_mode(self, tmp_path):
        from video_assembler import resolve_overlay_source

        clip = str(tmp_path / "meu_logo.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=100x100:rate=25:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)

        path, kind = resolve_overlay_source({"source": "local_file", "value": clip, "kind": "video"}, str(tmp_path), lambda p: None)
        assert path == clip
        assert kind == "video"

    def test_provider_search_mode_downloads_first_result(self, tmp_path):
        from video_assembler import resolve_overlay_source

        clip = str(tmp_path / "fonte.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=100x100:rate=25:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)

        class FakeVideo:
            id = "v1"

        class FakeClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                assert query == "logo animation"
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "baixado.mp4")
                shutil.copy(clip, dest)
                return dest

        path, kind = resolve_overlay_source(
            {"source": "provider_search", "provider": "pexels", "query": "logo animation"},
            str(tmp_path), lambda p: FakeClient(),
        )
        assert kind == "video"
        assert os.path.exists(path)

    def test_provider_search_missing_required_fields_raises_clear_error(self, tmp_path):
        from video_assembler import resolve_overlay_source, VideoAssemblyError

        with pytest.raises(VideoAssemblyError, match="query"):
            resolve_overlay_source({"source": "provider_search", "provider": "pexels"}, str(tmp_path), lambda p: None)

    def test_provider_search_no_results_raises_clear_error(self, tmp_path):
        from video_assembler import resolve_overlay_source, VideoAssemblyError

        class FakeClientEmpty:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return []

        with pytest.raises(VideoAssemblyError, match="Nenhum resultado"):
            resolve_overlay_source(
                {"source": "provider_search", "provider": "pexels", "query": "x"},
                str(tmp_path), lambda p: FakeClientEmpty(),
            )


class TestAssembleVideoWithOverlays:
    """assemble_video() de ponta a ponta, com overlay aplicado no vídeo
    final (já com áudio) — só no caminho real (site_cfg), não no
    legado (get_client_fn)."""

    def test_full_pipeline_with_overlay(self, tmp_path, monkeypatch):
        from video_assembler import assemble_video, _probe_duration
        from prompt_builder import VideoSegment
        from PIL import Image

        audio_path = str(tmp_path / "narracao.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=4", "-loglevel", "error", audio_path], check=True)

        clip = str(tmp_path / "fundo.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=320x240:rate=25:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)

        logo = str(tmp_path / "logo.png")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=yellow:size=100x100", "-frames:v", "1", "-loglevel", "error", logo], check=True)

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

        segments = [VideoSegment(start=0.0, end=4.0, provider="pexels", query="x")]
        output_path = str(tmp_path / "saida.mp4")
        overlays = [{"resolved_path": logo, "media_type": "image", "start": 1.0, "end": 3.0, "position": "bottom-right", "size_percent": 20}]

        cfg = {
            "orientation": "16:9", "export_quality": "1080p", "provider_priority": ["pexels"],
            "clip_trim_position": "start", "magnific_only_free": True, "assembly_fetch_concurrency": 1,
            "browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session",
            "pexels_api_fallback_to_browser": True, "provider_attempt_timeout_seconds": 25,
        }

        assemble_video(segments, audio_path, output_path, str(tmp_path), site_cfg=cfg, overlays=overlays)

        assert os.path.exists(output_path)
        assert abs(_probe_duration(output_path) - 4.0) < 0.2

        frame = str(tmp_path / "frame_2s.png")
        subprocess.run(["ffmpeg", "-y", "-ss", "2", "-i", output_path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
        img = Image.open(frame).convert("RGB")
        w, h = img.size
        pixel = img.getpixel((w - 30, h - 30))
        assert pixel[0] > 200 and pixel[1] > 200 and pixel[2] < 100, f"deveria ser amarelo (logo dentro da janela): {pixel}"

    def test_full_pipeline_without_overlays_unaffected(self, tmp_path, monkeypatch):
        """Sem overlays (parâmetro None ou lista vazia), o comportamento
        deveria ser idêntico ao de antes dessa funcionalidade existir."""
        from video_assembler import assemble_video, _probe_duration
        from prompt_builder import VideoSegment

        audio_path = str(tmp_path / "narracao.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=4", "-loglevel", "error", audio_path], check=True)

        clip = str(tmp_path / "fundo.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=320x240:rate=25:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)

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

        segments = [VideoSegment(start=0.0, end=4.0, provider="pexels", query="x")]
        output_path = str(tmp_path / "saida.mp4")

        cfg = {
            "orientation": "16:9", "export_quality": "1080p", "provider_priority": ["pexels"],
            "clip_trim_position": "start", "magnific_only_free": True, "assembly_fetch_concurrency": 1,
            "browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session",
            "pexels_api_fallback_to_browser": True, "provider_attempt_timeout_seconds": 25,
        }

        assemble_video(segments, audio_path, output_path, str(tmp_path), site_cfg=cfg, overlays=None)
        assert os.path.exists(output_path)
        assert abs(_probe_duration(output_path) - 4.0) < 0.2


class TestAspectFillModes:
    """`aspect_fill` ("black"/"zoom"/"mosaic") já estava implementado
    no código (schema, site_config, /settings) mas sem NENHUM teste
    cobrindo — adicionados aqui, confirmando visualmente cada um dos 3
    modos com um padrão de teste detalhado (não cor sólida, pra
    conseguir distinguir nítido de borrado de verdade)."""

    def _make_test_pattern_clip(self, tmp_path, name="xadrez.mp4", size="480x480", duration=2):
        path = str(tmp_path / name)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=25:duration={duration}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", path], check=True,
        )
        return path

    def test_black_mode_produces_valid_output(self, tmp_path):
        from video_assembler import _normalize_clip, _probe_duration

        clip = self._make_test_pattern_clip(tmp_path)
        output = str(tmp_path / "saida_black.mp4")
        _normalize_clip(clip, 2.0, output, target_width=640, target_height=360, aspect_fill="black")
        assert os.path.exists(output)
        assert abs(_probe_duration(output) - 2.0) < 0.2

    def test_zoom_mode_fills_frame_completely_no_black_bars(self, tmp_path):
        from video_assembler import _normalize_clip, _probe_duration
        from PIL import Image

        clip = self._make_test_pattern_clip(tmp_path)
        output = str(tmp_path / "saida_zoom.mp4")
        _normalize_clip(clip, 2.0, output, target_width=640, target_height=360, aspect_fill="zoom")
        assert abs(_probe_duration(output) - 2.0) < 0.2

        frame = str(tmp_path / "frame_zoom.png")
        subprocess.run(["ffmpeg", "-y", "-i", output, "-frames:v", "1", "-loglevel", "error", frame], check=True)
        img = Image.open(frame).convert("RGB")
        w, h = img.size
        # uma barra de letterbox de verdade é uma FAIXA LARGA e UNIFORME
        # de preto — o padrão de teste (testsrc) tem elementos pretos
        # ESTREITOS como parte do próprio desenho, então checar um único
        # pixel na borda pode pegar um falso positivo. Em vez disso,
        # confirma que a coluna/linha INTEIRA da borda não é toda preta.
        left_column = [img.getpixel((1, y)) for y in range(0, h, 10)]
        right_column = [img.getpixel((w - 2, y)) for y in range(0, h, 10)]
        top_row = [img.getpixel((x, 1)) for x in range(0, w, 10)]
        bottom_row = [img.getpixel((x, h - 2)) for x in range(0, w, 10)]
        for label, pixels in [("esquerda", left_column), ("direita", right_column), ("topo", top_row), ("base", bottom_row)]:
            assert any(sum(p) > 20 for p in pixels), f"toda a borda '{label}' está preta -- parece uma barra de letterbox, não devia existir no modo zoom"

    def test_mosaic_mode_has_sharp_center_and_blurred_edges(self, tmp_path):
        """A prova mais importante: o centro precisa ser NÍTIDO (o
        clipe original, sem alteração) e as bordas BORRADAS (o mosaico
        de fundo) -- não a mesma nitidez nos dois."""
        from video_assembler import _normalize_clip, _probe_duration
        from PIL import Image, ImageFilter
        import numpy as np

        clip = self._make_test_pattern_clip(tmp_path)
        output = str(tmp_path / "saida_mosaic.mp4")
        _normalize_clip(clip, 2.0, output, target_width=640, target_height=360, aspect_fill="mosaic")
        assert abs(_probe_duration(output) - 2.0) < 0.2

        frame = str(tmp_path / "frame_mosaic.png")
        subprocess.run(["ffmpeg", "-y", "-i", output, "-frames:v", "1", "-loglevel", "error", frame], check=True)
        img = Image.open(frame).convert("L")
        arr = np.asarray(img, dtype=float)

        def local_sharpness(x0, x1, y0, y1):
            # variância do gradiente horizontal -- alta em área nítida
            # com bordas de cor bem definidas, baixa em área borrada.
            region = arr[y0:y1, x0:x1]
            grad = np.abs(np.diff(region, axis=1))
            return grad.var()

        w, h = img.size
        center_sharpness = local_sharpness(w // 2 - 40, w // 2 + 40, h // 2 - 40, h // 2 + 40)
        edge_sharpness = local_sharpness(5, 85, h // 2 - 40, h // 2 + 40)

        assert center_sharpness > edge_sharpness * 2, (
            f"o centro (nitidez={center_sharpness:.1f}) deveria ser bem mais nítido "
            f"que a borda (nitidez={edge_sharpness:.1f}) no modo mosaic"
        )

    def test_invalid_aspect_fill_falls_back_to_black(self, tmp_path):
        from video_assembler import _normalize_clip, _probe_duration

        clip = self._make_test_pattern_clip(tmp_path)
        output = str(tmp_path / "saida_invalido.mp4")
        _normalize_clip(clip, 2.0, output, target_width=640, target_height=360, aspect_fill="modo_que_nao_existe")
        assert os.path.exists(output)
        assert abs(_probe_duration(output) - 2.0) < 0.2

    def test_site_config_validates_aspect_fill(self, tmp_path, monkeypatch):
        from site_config import save_site_config, SiteConfigError, load_site_config
        import site_config as site_config_mod

        config_path = str(tmp_path / "site_config.json")
        monkeypatch.setattr(site_config_mod, "CONFIG_PATH", config_path)

        with pytest.raises(SiteConfigError, match="aspect_fill"):
            save_site_config({"aspect_fill": "invalido"}, config_path)

        saved = save_site_config({"aspect_fill": "mosaic"}, config_path)
        assert saved["aspect_fill"] == "mosaic"


class TestTextOverlay:
    """Pedido do usuário: overlay de TEXTO puro (título/chamada
    independente de um trecho), com tempo/posição/estilo próprios —
    diferente do on_screen_text (preso a um segmento), esse pode
    atravessar vários trechos ou o vídeo inteiro."""

    def test_text_overlay_appears_only_within_its_time_window(self, tmp_path):
        from video_assembler import apply_overlays, _probe_duration
        from PIL import Image

        base = str(tmp_path / "base.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x480:rate=25:duration=6", "-f", "lavfi", "-i", "sine=duration=6", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-loglevel", "error", base], check=True)

        output = str(tmp_path / "saida.mp4")
        overlays = [{"media_type": "text", "text": "TITULO", "start": 2.0, "end": 4.0, "style": {"position": "top-center", "font_size": 60}}]
        apply_overlays(base, overlays, output, target_width=640, target_height=480)

        assert abs(_probe_duration(output) - 6.0) < 0.2

        def sample_top_center(t):
            frame = str(tmp_path / f"frame_{t}.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", output, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("L")
            # regiao onde o texto deveria estar (topo, centralizado)
            region = img.crop((img.width // 4, 0, img.width * 3 // 4, 80))
            return region.getextrema()[1]  # valor maximo de brilho na regiao

        antes = sample_top_center(1)
        dentro = sample_top_center(3)
        depois = sample_top_center(5)
        assert antes < 100, f"antes da janela, não deveria ter texto claro: brilho max={antes}"
        assert dentro > 200, f"dentro da janela, deveria ter texto branco: brilho max={dentro}"
        assert depois < 100, f"depois da janela, o texto não deveria mais aparecer: brilho max={depois}"

    def test_text_overlay_coexists_with_image_overlay_no_input_index_conflict(self, tmp_path):
        """Texto não consome nenhum input de ffmpeg -- precisa coexistir
        com overlays de imagem/vídeo sem embaralhar os índices."""
        from video_assembler import apply_overlays, _probe_duration
        from PIL import Image

        base = str(tmp_path / "base.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=640x480:rate=25:duration=6", "-f", "lavfi", "-i", "sine=duration=6", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-loglevel", "error", base], check=True)

        logo = str(tmp_path / "logo.png")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=yellow:size=100x100", "-frames:v", "1", "-loglevel", "error", logo], check=True)

        output = str(tmp_path / "saida.mp4")
        overlays = [
            {"media_type": "text", "text": "CHAMADA", "start": 0.0, "end": 6.0, "style": {"position": "bottom-center"}},
            {"media_type": "image", "resolved_path": logo, "start": 1.0, "end": 3.0, "position": "top-right", "size_percent": 15},
        ]
        apply_overlays(base, overlays, output, target_width=640, target_height=480)
        assert abs(_probe_duration(output) - 6.0) < 0.2

        frame = str(tmp_path / "frame_2s.png")
        subprocess.run(["ffmpeg", "-y", "-ss", "2", "-i", output, "-frames:v", "1", "-loglevel", "error", frame], check=True)
        img_rgb = Image.open(frame).convert("RGB")
        w, h = img_rgb.size

        # logo amarelo no topo direita
        logo_pixel = img_rgb.getpixel((w - 40, 40))
        assert logo_pixel[0] > 200 and logo_pixel[1] > 200 and logo_pixel[2] < 100, f"logo deveria estar visível: {logo_pixel}"

        # texto na base -- checa brilho (escala de cinza) na regiao esperada
        img_gray = img_rgb.convert("L")
        text_region = img_gray.crop((w // 4, h - 100, w * 3 // 4, h - 20))
        assert text_region.getextrema()[1] > 200, "texto deveria estar visível na base"

    def test_text_overlay_respects_style_position_and_size(self, tmp_path):
        from video_assembler import apply_overlays, _probe_duration
        from PIL import Image

        base = str(tmp_path / "base.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=black:size=640x480:rate=25:duration=2", "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-loglevel", "error", base], check=True)

        output = str(tmp_path / "saida.mp4")
        overlays = [{"media_type": "text", "text": "X", "start": 0.0, "end": 2.0, "style": {"position": "bottom-right", "background": False}}]
        apply_overlays(base, overlays, output, target_width=640, target_height=480)

        frame = str(tmp_path / "frame.png")
        subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", output, "-frames:v", "1", "-loglevel", "error", frame], check=True)
        img = Image.open(frame).convert("L")
        w, h = img.size
        # sem fundo, o unico branco na tela e o proprio texto -- confirma
        # que esta no canto INFERIOR DIREITO, nao no topo esquerdo
        top_left = img.crop((0, 0, w // 3, h // 3))
        bottom_right = img.crop((w - w // 3, h - h // 3, w, h))
        assert top_left.getextrema()[1] < 50, "não deveria ter nada no canto oposto"
        assert bottom_right.getextrema()[1] > 200, "o texto deveria estar no canto inferior direito"


class TestInsertCutaways:
    """Motor de CORTE REAL (não overlay — corta vídeo+áudio e insere um
    clipe inteiro num ponto, empurrando tudo depois pra frente). Cobre
    um bug real de FPS: os pedaços "antes/depois" do vídeo base
    mantinham o fps ORIGINAL, mas o corte normalizado forçava um fps
    diferente — o concat demuxer (usado com -c copy) não lida bem com
    fps inconsistente entre pedaços, causando timestamps incorretos
    (o corte aparecia deslocado no tempo, mesmo com a duração total
    batendo certo)."""

    def test_no_cutaways_just_copies_base_video(self, tmp_path):
        from video_assembler import insert_cutaways, _probe_duration

        base = str(tmp_path / "base.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=320x240:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", base], check=True)
        output = str(tmp_path / "saida.mp4")
        insert_cutaways(base, [], output, str(tmp_path), target_width=320, target_height=240)
        assert os.path.exists(output)
        assert abs(_probe_duration(output) - 3.0) < 0.2

    def test_single_cutaway_extends_duration_and_lands_at_right_position(self, tmp_path):
        from video_assembler import insert_cutaways, _probe_duration
        from PIL import Image

        base = str(tmp_path / "base.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x480:rate=25:duration=10", "-f", "lavfi", "-i", "sine=frequency=440:duration=10", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-loglevel", "error", base], check=True)
        cutaway = str(tmp_path / "cutaway.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=640x480:rate=25:duration=3", "-f", "lavfi", "-i", "sine=frequency=880:duration=3", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-loglevel", "error", cutaway], check=True)

        output = str(tmp_path / "saida.mp4")
        insert_cutaways(base, [{"resolved_path": cutaway, "insertion_point": 5.0, "audio_mode": "pause"}], output, str(tmp_path), target_width=640, target_height=480)

        assert abs(_probe_duration(output) - 13.0) < 0.3, "vídeo deveria ficar 3s mais longo (10 + 3)"

        def sample(t):
            frame = str(tmp_path / f"f_{t}.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", output, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("RGB")
            return img.getpixel((img.width // 2, img.height // 2))

        antes, dentro, depois = sample(2), sample(6.5), sample(11)
        assert antes[1] > 100 and antes[0] < 50, f"antes do corte deveria ser verde: {antes}"
        assert dentro[0] > 200 and dentro[1] < 50, f"dentro do corte deveria ser vermelho: {dentro}"
        assert depois[1] > 100 and depois[0] < 50, f"depois do corte deveria voltar a ser verde: {depois}"

    def test_cutaway_own_audio_plays_during_insertion_and_original_resumes_after(self, tmp_path):
        """Confirma o ÁUDIO de verdade via análise de frequência
        dominante — não só a duração/imagem."""
        from video_assembler import insert_cutaways
        import numpy as np

        base = str(tmp_path / "base.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x480:rate=25:duration=10", "-f", "lavfi", "-i", "sine=frequency=440:duration=10", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-loglevel", "error", base], check=True)
        cutaway = str(tmp_path / "cutaway.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=640x480:rate=25:duration=3", "-f", "lavfi", "-i", "sine=frequency=880:duration=3", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-loglevel", "error", cutaway], check=True)

        output = str(tmp_path / "saida.mp4")
        insert_cutaways(base, [{"resolved_path": cutaway, "insertion_point": 5.0, "audio_mode": "pause"}], output, str(tmp_path), target_width=640, target_height=480)

        def freq_dominante(t, duracao=0.5):
            raw = subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-t", str(duracao), "-i", output, "-f", "f32le", "-ac", "1", "-ar", "44100", "-"], capture_output=True).stdout
            audio = np.frombuffer(raw, dtype=np.float32)
            if len(audio) == 0:
                return 0
            fft = np.fft.rfft(audio)
            freqs = np.fft.rfftfreq(len(audio), 1 / 44100)
            return freqs[np.argmax(np.abs(fft))]

        assert abs(freq_dominante(2.0) - 440) < 20, "antes do corte deveria tocar o tom original (440Hz)"
        assert abs(freq_dominante(6.5) - 880) < 20, "dentro do corte deveria tocar o tom PRÓPRIO do clipe inserido (880Hz)"
        assert abs(freq_dominante(11.0) - 440) < 20, "depois do corte deveria voltar ao tom original (440Hz), sincronizado"

    def test_multiple_cutaways_land_at_correct_positions(self, tmp_path):
        """Regressão do bug de FPS: com 2 cortes, o segundo aparecia
        deslocado no tempo por causa da incompatibilidade de fps entre
        os pedaços "antes/depois" (fps original) e os cortes
        normalizados (fps diferente, hardcoded)."""
        from video_assembler import insert_cutaways, _probe_duration
        from PIL import Image

        base = str(tmp_path / "base.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=640x480:rate=25:duration=12", "-f", "lavfi", "-i", "sine=frequency=300:duration=12", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-loglevel", "error", base], check=True)
        corte1 = str(tmp_path / "corte1.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=yellow:size=640x480:rate=25:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", corte1], check=True)
        corte2 = str(tmp_path / "corte2.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=magenta:size=640x480:rate=25:duration=3", "-f", "lavfi", "-i", "sine=frequency=1000:duration=3", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-loglevel", "error", corte2], check=True)

        output = str(tmp_path / "saida.mp4")
        cutaways = [
            {"resolved_path": corte1, "insertion_point": 4.0, "audio_mode": "pause"},
            {"resolved_path": corte2, "insertion_point": 8.0, "audio_mode": "pause"},
        ]
        insert_cutaways(base, cutaways, output, str(tmp_path), target_width=640, target_height=480)

        assert abs(_probe_duration(output) - 17.0) < 0.3

        def sample(t):
            frame = str(tmp_path / f"m_{t}.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", output, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("RGB")
            return img.getpixel((img.width // 2, img.height // 2))

        cores_esperadas = {2: "azul", 5: "amarelo", 8: "azul", 11.5: "magenta", 16: "azul"}
        referencias = {"azul": (0, 0, 255), "amarelo": (255, 255, 0), "magenta": (255, 0, 255)}
        for t, cor in cores_esperadas.items():
            pixel = sample(t)
            ref = referencias[cor]
            assert all(abs(pixel[i] - ref[i]) < 40 for i in range(3)), f"em t={t}s esperava {cor}, veio {pixel}"

    def test_cutaway_without_own_audio_gets_silence(self, tmp_path):
        from video_assembler import insert_cutaways, _has_audio_stream, _probe_duration

        base = str(tmp_path / "base.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=320x240:rate=25:duration=4", "-f", "lavfi", "-i", "sine=duration=4", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-loglevel", "error", base], check=True)
        cutaway_silent = str(tmp_path / "cutaway_silent.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", cutaway_silent], check=True)
        assert not _has_audio_stream(cutaway_silent)

        output = str(tmp_path / "saida.mp4")
        insert_cutaways(base, [{"resolved_path": cutaway_silent, "insertion_point": 2.0, "audio_mode": "pause"}], output, str(tmp_path), target_width=320, target_height=240)
        assert os.path.exists(output)
        assert abs(_probe_duration(output) - 6.0) < 0.3
        assert _has_audio_stream(output), "mesmo com o corte silencioso, o vídeo final precisa ter faixa de áudio (gerada automaticamente)"


class TestCaptionStyle:
    """Personalização visual da legenda (cor, borda, sombra, brilho,
    fonte, tamanho, posição) — pedido do usuário: poder mudar o estilo
    de todas as legendas de uma vez."""

    def test_hex_to_ass_color_conversion(self):
        from video_assembler import _hex_to_ass_color

        assert _hex_to_ass_color("#FFFFFF") == "&H00FFFFFF"
        assert _hex_to_ass_color("#FF0000") == "&H000000FF"  # BGR invertido, não RGB
        assert _hex_to_ass_color("#FF0000", alpha=128) == "&H800000FF"

    def test_hex_to_ass_color_rejects_invalid_hex(self):
        from video_assembler import _hex_to_ass_color, VideoAssemblyError

        with pytest.raises(VideoAssemblyError):
            _hex_to_ass_color("#FFF")

    def test_custom_color_and_position_render_correctly(self, tmp_path):
        """Confirma visualmente: cor customizada, borda customizada, e
        posição no topo — tudo aplicado de verdade no vídeo final."""
        from video_assembler import generate_word_captions_ass, burn_captions
        from PIL import Image

        base = str(tmp_path / "base.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=black:size=640x480:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", base], check=True)

        words = [{"word": "OLA", "start": 0.5, "end": 2.5}]
        ass_path = str(tmp_path / "legenda.ass")
        generate_word_captions_ass(words, ass_path, video_width=640, video_height=480, style={
            "primary_color": "#FF0000", "border_color": "#0000FF", "border_width": 6,
            "position": "top", "font_size": 60,
        })
        output = str(tmp_path / "saida.mp4")
        burn_captions(base, ass_path, output)

        frame = str(tmp_path / "frame.png")
        subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", output, "-frames:v", "1", "-loglevel", "error", frame], check=True)
        img = Image.open(frame).convert("RGB")

        # o texto deveria estar perto do TOPO (nao da base, que e o padrao)
        top_region = img.crop((0, 0, img.width, img.height // 3))
        bottom_region = img.crop((0, img.height * 2 // 3, img.width, img.height))
        top_r, top_g, top_b = top_region.split()
        bottom_r, bottom_g, bottom_b = bottom_region.split()
        top_has_color = top_r.getextrema()[1] > 150 or top_b.getextrema()[1] > 150
        bottom_has_color = bottom_r.getextrema()[1] > 150 or bottom_b.getextrema()[1] > 150
        assert top_has_color, "deveria ter texto colorido (vermelho/azul) perto do topo"
        assert not bottom_has_color, "não deveria ter nada na base (posição customizada é 'top')"

    def test_glow_effect_uses_correct_ass_override_syntax(self, tmp_path):
        """Bug real encontrado: a tag \\blur precisa estar entre chaves
        {} pra ser interpretada como efeito -- sem isso, aparece como
        texto literal na tela."""
        from video_assembler import generate_word_captions_ass, burn_captions
        from PIL import Image

        base = str(tmp_path / "base.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=black:size=640x480:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", base], check=True)

        words = [{"word": "BRILHO", "start": 0.5, "end": 2.5}]
        ass_path = str(tmp_path / "legenda_glow.ass")
        generate_word_captions_ass(words, ass_path, video_width=640, video_height=480, style={
            "primary_color": "#FFFFFF", "border_color": "#00FFFF", "border_width": 3, "glow": 15, "font_size": 60,
        })

        # confere o arquivo .ass diretamente -- a tag de blur precisa
        # estar dentro de chaves, nunca solta como texto
        ass_content = open(ass_path, encoding="utf-8").read()
        assert "{\\blur15}" in ass_content
        assert "\\blur15BRILHO" not in ass_content  # sem chaves, viraria parte do texto

        output = str(tmp_path / "saida.mp4")
        burn_captions(base, ass_path, output)
        frame = str(tmp_path / "frame.png")
        subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", output, "-frames:v", "1", "-loglevel", "error", frame], check=True)
        img = Image.open(frame).convert("RGB")
        # a palavra "BRILHO" tem 6 letras -- se a tag "\blur15" tivesse
        # vazado como texto, a palavra renderizada seria bem mais larga
        # (13 caracteres). Confere que a região de texto não é larga demais.
        gray = img.convert("L")
        bright_columns = [x for x in range(gray.width) if max(gray.getpixel((x, y)) for y in range(gray.height)) > 200]
        if bright_columns:
            text_width = max(bright_columns) - min(bright_columns)
            assert text_width < img.width * 0.6, f"texto largo demais ({text_width}px) -- pode ser sinal de que a tag vazou como texto literal"

    def test_shadow_visible_against_light_background(self, tmp_path):
        """Sombra preta em fundo preto seria invisível mesmo funcionando
        -- testa contra fundo BRANCO pra confirmar o efeito de verdade."""
        from video_assembler import generate_word_captions_ass, burn_captions
        from PIL import Image

        base = str(tmp_path / "base_claro.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=white:size=640x480:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", base], check=True)

        words = [{"word": "SOMBRA", "start": 0.5, "end": 2.5}]
        ass_path = str(tmp_path / "legenda_sombra.ass")
        generate_word_captions_ass(words, ass_path, video_width=640, video_height=480, style={
            "primary_color": "#FFFFFF", "border_color": "#000000", "border_width": 0, "shadow_depth": 10, "font_size": 70,
        })
        output = str(tmp_path / "saida.mp4")
        burn_captions(base, ass_path, output)
        frame = str(tmp_path / "frame.png")
        subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", output, "-frames:v", "1", "-loglevel", "error", frame], check=True)
        img = Image.open(frame).convert("L")

        # com texto BRANCO (invisivel no fundo branco) e sombra PRETA
        # deslocada, deveria sobrar pixel escuro na regiao da legenda
        region = img.crop((0, img.height * 3 // 4, img.width, img.height))
        assert region.getextrema()[0] < 100, "deveria haver pixels escuros (a sombra) na região da legenda"

    def test_regular_font_uses_bold_flag_not_font_name_suffix(self, tmp_path):
        """Bug real encontrado: negrito/normal é uma FLAG do estilo ASS
        (Bold=-1 ou 0), não um nome de fonte diferente -- confirma que
        o .ass gerado usa o MESMO nome de fonte nos dois casos."""
        from video_assembler import generate_word_captions_ass

        words = [{"word": "X", "start": 0.0, "end": 1.0}]
        ass_bold = str(tmp_path / "bold.ass")
        ass_regular = str(tmp_path / "regular.ass")
        generate_word_captions_ass(words, ass_bold, style={"font": "bold"})
        generate_word_captions_ass(words, ass_regular, style={"font": "regular"})

        bold_style_line = [l for l in open(ass_bold).readlines() if l.startswith("Style:")][0]
        regular_style_line = [l for l in open(ass_regular).readlines() if l.startswith("Style:")][0]

        assert "DejaVu Sans," in bold_style_line
        assert "DejaVu Sans," in regular_style_line
        assert "DejaVu Sans Bold" not in bold_style_line  # não deveria existir esse nome de fonte
        # o campo Bold é o 8o campo (indice 7) da lista separada por virgula
        assert bold_style_line.split(",")[7] == "-1"
        assert regular_style_line.split(",")[7] == "0"

    def test_defaults_reproduce_original_visual_when_no_style_given(self, tmp_path):
        """Sem nenhum style, o resultado precisa ser idêntico ao
        comportamento de sempre (retrocompatibilidade)."""
        from video_assembler import generate_word_captions_ass

        words = [{"word": "X", "start": 0.0, "end": 1.0}]
        ass_path = str(tmp_path / "padrao.ass")
        generate_word_captions_ass(words, ass_path, video_width=1920, video_height=1080)

        style_line = [l for l in open(ass_path).readlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        assert fields[3] == "&H00FFFFFF"  # branco
        assert fields[7] == "-1"  # negrito
        assert fields[16] == "4"  # espessura de borda 4px
        assert fields[17] == "0"  # sem sombra


class TestShiftTimestampsForCutaways:
    """Bug real encontrado (via auditoria, não relatado pelo usuário):
    a legenda era gerada com os tempos ORIGINAIS da transcrição, sem
    ajustar pelo deslocamento que um corte real causa no vídeo final
    -- uma palavra dita DEPOIS de um corte aparecia adiantada, fora de
    sincronia com a fala de verdade."""

    def test_word_after_cutaway_shifts_by_cutaway_duration(self):
        from video_assembler import shift_timestamps_for_cutaways

        words = [
            {"word": "ANTES", "start": 1.0, "end": 2.0},
            {"word": "DEPOIS", "start": 8.0, "end": 9.0},
        ]
        cutaways = [{"insertion_point": 3.0, "duration": 5.0}]
        adjusted = shift_timestamps_for_cutaways(words, cutaways)
        assert adjusted[0]["start"] == 1.0 and adjusted[0]["end"] == 2.0  # antes do corte, fica igual
        assert adjusted[1]["start"] == 13.0 and adjusted[1]["end"] == 14.0  # depois, desloca +5s

    def test_multiple_cutaways_accumulate_shift(self):
        from video_assembler import shift_timestamps_for_cutaways

        cutaways = [{"insertion_point": 3.0, "duration": 5.0}, {"insertion_point": 10.0, "duration": 2.0}]
        words = [{"word": "X", "start": 15.0, "end": 16.0}]  # depois dos 2 cortes
        adjusted = shift_timestamps_for_cutaways(words, cutaways)
        assert adjusted[0]["start"] == 22.0  # 15 + 5 + 2

    def test_no_cutaways_leaves_timestamps_unchanged(self):
        from video_assembler import shift_timestamps_for_cutaways

        words = [{"word": "X", "start": 1.0, "end": 2.0}]
        assert shift_timestamps_for_cutaways(words, []) == words
