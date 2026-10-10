"""
Teste automatizado das peças de suporte à timeline visual do editor:
geração de forma de onda do áudio, extração de thumbnail (vídeo ou
imagem), e a pré-busca de prévia de um segmento (com falha graciosa).
"""
import os
import shutil
import subprocess

from PIL import Image

from prompt_builder import VideoSegment
from video_assembler import fetch_segment_preview, generate_thumbnail, generate_waveform_image


class TestGenerateWaveformImage:
    def test_generates_image_with_requested_dimensions(self, tmp_path, synthetic_audio):
        out = str(tmp_path / "waveform.png")
        generate_waveform_image(synthetic_audio, out, width=800, height=100)
        assert os.path.exists(out)
        assert Image.open(out).size == (800, 100)


class TestGenerateThumbnail:
    def test_extracts_real_frame_from_video(self, tmp_path):
        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=640x360:rate=25:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )
        out = str(tmp_path / "thumb.jpg")
        generate_thumbnail(clip, out, width=200)

        assert os.path.exists(out)
        img = Image.open(out)
        assert img.size[0] == 200
        r, g, b = img.getpixel((img.size[0] // 2, img.size[1] // 2))
        assert r > 150 and g < 50, "thumbnail deveria mostrar a cor vermelha do clipe fonte"

    def test_resizes_image_source_instead_of_extracting_frame(self, tmp_path):
        image_path = str(tmp_path / "foto.jpg")
        Image.new("RGB", (800, 600), (0, 200, 0)).save(image_path)
        out = str(tmp_path / "thumb.jpg")
        generate_thumbnail(image_path, out, width=200)

        img = Image.open(out)
        assert img.size[0] == 200
        r, g, b = img.getpixel((img.size[0] // 2, img.size[1] // 2))
        assert g > 150 and r < 50


class TestFetchSegmentPreview:
    def test_successful_fetch_returns_raw_path_and_kind(self, tmp_path):
        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=320x240:rate=25:duration=3",
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

        segment = VideoSegment(start=0.0, end=3.0, provider="pexels", query="x")
        result = fetch_segment_preview(segment, str(tmp_path), get_client_fn=lambda p: FakeClient())

        assert result["ok"] is True
        assert result["kind"] == "video"
        assert os.path.exists(result["raw_path"])
        assert result["error"] is None

    def test_failed_fetch_returns_ok_false_with_error_message_not_exception(self, tmp_path):
        class FakeFailingClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return []

        segment = VideoSegment(start=0.0, end=3.0, provider="pexels", query="x")
        result = fetch_segment_preview(segment, str(tmp_path), get_client_fn=lambda p: FakeFailingClient())

        assert result["ok"] is False
        assert result["raw_path"] is None
        assert result["error"] is not None
