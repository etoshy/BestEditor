"""v84_251: intro/final (cortes) a 48 kHz + o react com a música na taxa original (44,1 kHz) — emendados com "-c copy"
a música saía 8,8% mais rápida/aguda. Agora todos os pedaços saem na taxa do vídeo base."""
import subprocess

import numpy as np

import video_assembler as VA


def _video(caminho, freq, taxa, dur, cor="blue"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={cor}:s=320x180:d={dur}:r=30",
                    "-f", "lavfi", "-i", f"sine=f={freq}:d={dur}:sample_rate={taxa}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ar", str(taxa), "-shortest", caminho], check=True)
    return caminho


def _freq(caminho, ss, t):
    x = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-ss", str(ss), "-i", caminho, "-t", str(t), "-vn", "-ac", "1",
                                      "-ar", "48000", "-f", "f32le", "-"], capture_output=True).stdout, np.float32)
    esp = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / 48000)[int(np.argmax(esp))])


def test_intro_48k_nao_acelera_a_musica_44k(tmp_path):
    base = _video(str(tmp_path / "base.mp4"), 440, 44100, 6)
    intro = _video(str(tmp_path / "intro.mp4"), 1000, 48000, 2, "red")
    saida = str(tmp_path / "out.mp4")
    VA.insert_cutaways(base, [{"resolved_path": intro, "insertion_point": 0.0, "audio_mode": "pause"},
                              {"resolved_path": intro, "insertion_point": 6.0, "audio_mode": "pause"}],
                       saida, str(tmp_path), 320, 180)
    assert abs(_freq(saida, 3.0, 2.0) - 440) < 6      # a música do meio: o mesmo tom (antes: ~479 Hz)
    assert abs(_freq(saida, 0.3, 1.2) - 1000) < 12     # a intro também no tom dela
    assert abs(VA._probe_duration(saida) - 10.0) < 0.3


def test_assinatura_ve_o_audio(tmp_path):
    a = _video(str(tmp_path / "a.mp4"), 440, 44100, 1)
    b = _video(str(tmp_path / "b.mp4"), 440, 48000, 1)
    assert VA._assinatura_stream(a) != VA._assinatura_stream(b)
