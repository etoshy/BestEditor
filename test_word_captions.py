"""
Teste automatizado das legendas "uma palavra por vez" (estilo Shorts/
TikTok, diferente do karaokê clássico de linha inteira): geração do
arquivo .ass, formatação de timestamp, e confirmação visual real (via
hash de frame) de que cada palavra aparece só na sua janela de tempo.
"""
import hashlib
import os
import shutil
import subprocess

import pytest
from PIL import Image

from video_assembler import (
    VideoAssemblyError,
    _seconds_to_ass_timestamp,
    burn_captions,
    generate_word_captions_ass,
    _probe_duration,
)


def _extract_frame(path, t):
    frame = f"{path}_{t}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(t), "-i", path, "-frames:v", "1", "-loglevel", "error", frame],
        check=True,
    )
    return Image.open(frame).convert("RGB")


def _frame_hash(img):
    return hashlib.md5(img.tobytes()).hexdigest()


class TestAssTimestampFormatting:
    def test_zero_seconds(self):
        assert _seconds_to_ass_timestamp(0.0) == "0:00:00.00"

    def test_minutes_and_centiseconds(self):
        assert _seconds_to_ass_timestamp(65.5) == "0:01:05.50"

    def test_hours(self):
        assert _seconds_to_ass_timestamp(3661.25) == "1:01:01.25"


class TestGenerateWordCaptionsAss:
    def test_generates_file_with_correct_words_and_timestamps(self, tmp_path):
        words = [
            {"word": "Bem-vindos", "start": 0.5, "end": 1.3},
            {"word": "ao", "start": 1.4, "end": 1.6},
        ]
        out = str(tmp_path / "captions.ass")
        generate_word_captions_ass(words, out, video_width=640, video_height=360)

        content = open(out).read()
        assert "Bem-vindos" in content
        assert "Dialogue: 0,0:00:00.50,0:00:01.30" in content
        assert "Dialogue: 0,0:00:01.40,0:00:01.60" in content

    def test_rejects_empty_word_list(self, tmp_path):
        with pytest.raises(VideoAssemblyError, match="vazia"):
            generate_word_captions_ass([], str(tmp_path / "x.ass"))

    def test_escapes_special_ass_characters(self, tmp_path):
        words = [{"word": "{teste}\\palavra", "start": 0.0, "end": 1.0}]
        out = str(tmp_path / "captions.ass")
        generate_word_captions_ass(words, out)
        content = open(out).read()
        assert "{teste}" not in content  # chaves removidas (teriam significado de tag no .ass)


class TestBurnCaptionsVisual:
    def test_each_word_appears_only_in_its_own_time_window(self, tmp_path):
        src = str(tmp_path / "src.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=640x360:rate=25:duration=6",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", src], check=True,
        )

        words = [
            {"word": "PRIMEIRA", "start": 0.5, "end": 1.5},
            {"word": "SEGUNDA", "start": 2.5, "end": 3.5},
        ]
        ass_path = str(tmp_path / "captions.ass")
        generate_word_captions_ass(words, ass_path, video_width=640, video_height=360)

        out = str(tmp_path / "out.mp4")
        burn_captions(src, ass_path, out)

        assert abs(_probe_duration(out) - 6.0) < 0.2

        hash_no_word = _frame_hash(_extract_frame(out, 2.0))   # entre as duas janelas
        hash_word1 = _frame_hash(_extract_frame(out, 1.0))     # durante "PRIMEIRA"
        hash_word2 = _frame_hash(_extract_frame(out, 3.0))     # durante "SEGUNDA"

        assert hash_word1 != hash_no_word, "deveria mostrar 'PRIMEIRA' nesse momento"
        assert hash_word2 != hash_no_word, "deveria mostrar 'SEGUNDA' nesse momento"
        assert hash_word1 != hash_word2, "palavras diferentes deveriam gerar frames diferentes"
