"""
Teste automatizado da trilha sonora de fundo em video_assembler.py:
duração final sempre bate com a narração (seja a música mais curta,
precisando de loop, ou mais longa, precisando de corte), a trilha está
de fato presente no áudio final (medido via volume, não só duração), e
o fluxo completo via assemble_video().
"""
import os
import re
import shutil
import subprocess

from prompt_builder import VideoSegment
from video_assembler import _mux_audio_with_music, _probe_duration, assemble_video


def _mean_volume_db(path: str) -> float:
    result = subprocess.run(
        ["ffmpeg", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    match = re.search(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", result.stderr)
    assert match, f"não encontrou mean_volume na saída do ffmpeg: {result.stderr[-500:]}"
    return float(match.group(1))


class TestMuxAudioWithMusic:
    def test_output_duration_matches_narration_when_music_is_shorter(self, tmp_path):
        video_only = str(tmp_path / "video_only.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=8",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", video_only], check=True,
        )
        narration = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=8", "-loglevel", "error", narration], check=True)
        short_music = str(tmp_path / "music_short.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=3", "-loglevel", "error", short_music], check=True)

        out = str(tmp_path / "out.mp4")
        _mux_audio_with_music(video_only, narration, short_music, out, music_volume=0.2)
        assert abs(_probe_duration(out) - 8.0) < 0.2

    def test_output_duration_matches_narration_when_music_is_longer(self, tmp_path):
        video_only = str(tmp_path / "video_only.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=8",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", video_only], check=True,
        )
        narration = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=8", "-loglevel", "error", narration], check=True)
        long_music = str(tmp_path / "music_long.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=15", "-loglevel", "error", long_music], check=True)

        out = str(tmp_path / "out.mp4")
        _mux_audio_with_music(video_only, narration, long_music, out, music_volume=0.2)
        assert abs(_probe_duration(out) - 8.0) < 0.2

    def test_music_is_actually_audible_in_mixed_output(self, tmp_path):
        video_only = str(tmp_path / "video_only.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=5",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", video_only], check=True,
        )
        silent_narration = str(tmp_path / "silent.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=duration=5", "-loglevel", "error", silent_narration], check=True)
        loud_music = str(tmp_path / "loud_music.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5", "-loglevel", "error", loud_music], check=True)

        out = str(tmp_path / "out.mp4")
        _mux_audio_with_music(video_only, silent_narration, loud_music, out, music_volume=0.5)

        mean_volume = _mean_volume_db(out)
        assert mean_volume > -50, (
            f"narração era silenciosa; se a saída também está silenciosa ({mean_volume} dB), "
            "a música não está sendo mixada de verdade"
        )


class TestMusicEndToEnd:
    def test_assemble_video_with_music_path(self, tmp_path):
        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=duration=5", "-loglevel", "error", audio_path], check=True)
        music_path = str(tmp_path / "music.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5", "-loglevel", "error", music_path], check=True)
        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=5",
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

        segments = [VideoSegment(start=0.0, end=5.0, provider="pexels", query="x")]
        output_path = str(tmp_path / "out" / "final.mp4")

        assemble_video(
            segments, audio_path, output_path, str(tmp_path / "job"),
            get_client_fn=lambda p: FakeClient(),
            music_path=music_path, music_volume=0.4,
        )

        assert abs(_probe_duration(output_path) - 5.0) < 0.2
        assert _mean_volume_db(output_path) > -50

    def test_missing_music_file_falls_back_to_plain_mux(self, tmp_path):
        """Se music_path apontar pra um arquivo que não existe, não deve
        quebrar — só monta sem trilha, normalmente."""
        audio_path = str(tmp_path / "narration.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=3", "-loglevel", "error", audio_path], check=True)
        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=3",
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

        segments = [VideoSegment(start=0.0, end=3.0, provider="pexels", query="x")]
        output_path = str(tmp_path / "out" / "final.mp4")

        assemble_video(
            segments, audio_path, output_path, str(tmp_path / "job"),
            get_client_fn=lambda p: FakeClient(),
            music_path="/tmp/isso_nao_existe_de_verdade.mp3",
        )

        assert os.path.exists(output_path)
