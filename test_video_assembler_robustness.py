"""
Teste offline das correções de robustez em video_assembler.py:
reaproveitamento de cliente por provedor (não um por segmento), fallback
de busca quando o termo original não acha nada, tratamento automático de
vídeo premium do Magnific, e fechamento de sessão garantido mesmo com
erro.
"""
import os
import shutil

from prompt_builder import VideoSegment
from video_assembler import VideoAssemblyError, _probe_duration, assemble_video

WORK = "/tmp/_test_assembler_robustness"


class _FakeSession:
    def __init__(self, tracker):
        self._tracker = tracker

    def close(self):
        self._tracker["closed"] = True


def _make_audio(path, duration=9.469):
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=duration={duration}", "-loglevel", "error", path],
        check=True,
    )


def _make_clip(path, color="green", duration=3):
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color={color}:size=640x360:rate=25:duration={duration}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", path],
        check=True,
    )


def _setup():
    if os.path.exists(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    audio_path = os.path.join(WORK, "audio.wav")
    _make_audio(audio_path)
    clip_path = os.path.join(WORK, "clip.mp4")
    _make_clip(clip_path)
    return audio_path, clip_path


def test_reuses_one_client_per_provider_and_closes_it():
    audio_path, clip_path = _setup()
    audio_duration = _probe_duration(audio_path)

    segments = [
        VideoSegment(start=0.0, end=4.5, provider="pexels", query="a"),
        VideoSegment(start=4.5, end=audio_duration, provider="pexels", query="b"),
    ]

    clients_created = []

    class FakeVideo:
        id = "v1"
        premium = False

    class FakeClient:
        def __init__(self, provider):
            self.tracker = {"closed": False}
            self.session = _FakeSession(self.tracker)
            clients_created.append(self)

        def search_all(self, query=None, category=None, max_pages=1):
            return [FakeVideo()]

        def download_video(self, video, output_dir, **kw):
            os.makedirs(output_dir, exist_ok=True)
            dest = os.path.join(output_dir, "clip.mp4")
            shutil.copy(clip_path, dest)
            return dest

    output_path = os.path.join(WORK, "out", "final.mp4")
    assemble_video(segments, audio_path, output_path, os.path.join(WORK, "job1"), get_client_fn=lambda p: FakeClient(p))

    assert len(clients_created) == 1, f"esperava 1 cliente reaproveitado, criou {len(clients_created)}"
    assert clients_created[0].tracker["closed"], "cliente deveria ter sido fechado ao final"
    print("OK: reaproveita 1 único cliente para múltiplos segmentos do mesmo provedor, e fecha ao final.")


def test_falls_back_to_generic_query_when_original_finds_nothing():
    audio_path, clip_path = _setup()
    audio_duration = _probe_duration(audio_path)
    segments = [VideoSegment(start=0.0, end=audio_duration, provider="pexels", query="termo muito especifico")]

    class FakeVideo:
        id = "v1"
        premium = False

    class FakeClient:
        def __init__(self, provider):
            self.session = _FakeSession({})

        def search_all(self, query=None, category=None, max_pages=1):
            return [] if "especifico" in (query or "") else [FakeVideo()]

        def download_video(self, video, output_dir, **kw):
            os.makedirs(output_dir, exist_ok=True)
            dest = os.path.join(output_dir, "clip.mp4")
            shutil.copy(clip_path, dest)
            return dest

    output_path = os.path.join(WORK, "out2", "final.mp4")
    final = assemble_video(segments, audio_path, output_path, os.path.join(WORK, "job2"), get_client_fn=lambda p: FakeClient(p))
    assert os.path.exists(final)
    print("OK: cai automaticamente para termo de busca mais genérico quando o original não acha nada.")


def test_magnific_premium_downloads_with_watermark_instead_of_failing():
    audio_path, clip_path = _setup()
    audio_duration = _probe_duration(audio_path)
    segments = [VideoSegment(start=0.0, end=audio_duration, provider="magnific", query="algo")]

    class FakePremiumVideo:
        id = "v1"
        premium = True
        watermarked = True

    download_calls = []

    class FakeMagnificClient:
        def __init__(self, provider):
            self.session = _FakeSession({})

        def search_all(self, query=None, category=None, max_pages=1):
            return [FakePremiumVideo()]

        def download_video(self, video, output_dir, **kw):
            download_calls.append(kw)
            if video.premium and not kw.get("allow_watermarked"):
                raise Exception("WatermarkedDownloadError")
            os.makedirs(output_dir, exist_ok=True)
            dest = os.path.join(output_dir, "clip.mp4")
            shutil.copy(clip_path, dest)
            return dest

    output_path = os.path.join(WORK, "out3", "final.mp4")
    final = assemble_video(segments, audio_path, output_path, os.path.join(WORK, "job3"), get_client_fn=lambda p: FakeMagnificClient(p))
    assert os.path.exists(final)
    assert download_calls[0].get("allow_watermarked") is True
    print("OK: vídeo premium do Magnific é baixado automaticamente com allow_watermarked=True.")


def test_client_is_closed_even_when_everything_fails():
    audio_path, _ = _setup()
    audio_duration = _probe_duration(audio_path)
    segments = [VideoSegment(start=0.0, end=audio_duration, provider="pexels", query="nada disso existe")]

    tracker = {"closed": False}

    class FakeClientAllFail:
        def __init__(self, provider):
            self.session = _FakeSession(tracker)

        def search_all(self, query=None, category=None, max_pages=1):
            return []

        def download_video(self, video, output_dir, **kw):
            raise RuntimeError("nunca deveria chegar aqui")

    output_path = os.path.join(WORK, "out4", "final.mp4")
    try:
        assemble_video(segments, audio_path, output_path, os.path.join(WORK, "job4"), get_client_fn=lambda p: FakeClientAllFail(p))
        raise AssertionError("deveria ter levantado VideoAssemblyError")
    except VideoAssemblyError:
        pass

    assert tracker["closed"], "cliente deveria ter sido fechado mesmo com a montagem falhando"
    print("OK: cliente é fechado mesmo quando a montagem falha por completo.")


if __name__ == "__main__":
    test_reuses_one_client_per_provider_and_closes_it()
    test_falls_back_to_generic_query_when_original_finds_nothing()
    test_magnific_premium_downloads_with_watermark_instead_of_failing()
    test_client_is_closed_even_when_everything_fails()
    shutil.rmtree(WORK, ignore_errors=True)
    print("\nTodos os testes de robustez do video_assembler.py passaram.")
