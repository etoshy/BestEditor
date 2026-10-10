"""
Teste automatizado da renderização de texto na tela (`on_screen_text`)
em video_assembler.py: escape de caracteres perigosos pro filtro
drawtext, confirmação via pixel de que o texto realmente é desenhado, e
o fluxo completo via assemble_video().
"""
import os
import shutil
import subprocess

import pytest

from prompt_builder import VideoSegment
from video_assembler import _normalize_clip, assemble_video


def _sample_pixel(path, t, x_ratio, y_ratio):
    frame = path + "_frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(t), "-i", path, "-frames:v", "1", "-loglevel", "error", frame],
        check=True,
    )
    from PIL import Image
    img = Image.open(frame).convert("RGB")
    w, h = img.size
    return img.getpixel((int(w * x_ratio), int(h * y_ratio)))


class TestDrawtextRendering:
    def test_text_box_darkens_expected_region(self, tmp_path):
        src = str(tmp_path / "src.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x360:rate=25:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", src],
            check=True,
        )

        out_no_text = str(tmp_path / "no_text.mp4")
        out_with_text = str(tmp_path / "with_text.mp4")
        _normalize_clip(src, 3.0, out_no_text, 640, 360, on_screen_text=None)
        _normalize_clip(src, 3.0, out_with_text, 640, 360, on_screen_text="Bem-vindo ao vídeo")

        color_no_text = _sample_pixel(out_no_text, 1.5, 0.5, 0.8)
        color_with_text = _sample_pixel(out_with_text, 1.5, 0.5, 0.8)

        assert color_no_text[1] > 100 and color_no_text[0] < 30, "sem texto deveria ser verde puro"
        assert color_with_text[1] < color_no_text[1] - 30, "a caixa do texto deveria escurecer a região"

    @pytest.mark.parametrize("dangerous_text", [
        "Hora: 10:30",
        "It's amazing!",
        "100% garantido",
        "C:\\Users\\teste",
    ])
    def test_special_characters_do_not_break_ffmpeg(self, tmp_path, dangerous_text):
        src = str(tmp_path / "src.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=320x240:rate=25:duration=2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", src],
            check=True,
        )
        out = str(tmp_path / "out.mp4")
        _normalize_clip(src, 2.0, out, 320, 240, on_screen_text=dangerous_text)
        assert os.path.exists(out) and os.path.getsize(out) > 0


class TestOnScreenTextEndToEnd:
    def test_on_screen_text_appears_in_final_assembled_video(self, tmp_path, synthetic_audio):
        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x360:rate=25:duration=9.469",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip],
            check=True,
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

        segments = [VideoSegment(start=0.0, end=9.469, provider="pexels", query="x", on_screen_text="Texto de teste")]
        output_path = str(tmp_path / "out" / "final.mp4")

        assemble_video(
            segments, synthetic_audio, output_path, str(tmp_path / "job"),
            get_client_fn=lambda p: FakeClient(),
        )

        color = _sample_pixel(output_path, 4.0, 0.5, 0.8)
        assert color[1] < 90, "a caixa do texto deveria ter escurecido essa região do verde no vídeo final"
