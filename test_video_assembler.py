"""
Teste offline de video_assembler.py — gera clipes sintéticos com ffmpeg
na hora (sem precisar baixar nada de verdade) e valida que o pipeline de
normalização/concatenação/sincronismo com áudio funciona corretamente:
duração final bate com o áudio, e cada segmento aparece no tempo certo.
"""
import os
import shutil
import subprocess

from prompt_builder import VideoSegment
from video_assembler import _probe_duration, assemble_video

WORK = "/tmp/_test_video_assembler"


def _make_synthetic_audio(path: str, duration: float = 9.469):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=duration={duration}", "-loglevel", "error", path],
        check=True,
    )


def _make_solid_clip(path: str, color: str, duration: float):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color={color}:size=640x360:rate=25:duration={duration}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", path],
        check=True,
    )


def _sample_color(video_path: str, at_seconds: float):
    frame_path = video_path + f"_frame_{at_seconds}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(at_seconds), "-i", video_path, "-frames:v", "1", "-loglevel", "error", frame_path],
        check=True,
    )
    from PIL import Image
    img = Image.open(frame_path).convert("RGB")
    w, h = img.size
    return img.getpixel((w // 2, h // 2))


def test_assemble_video_end_to_end_with_loop_and_trim():
    if os.path.exists(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)

    audio_path = os.path.join(WORK, "audio.wav")
    _make_synthetic_audio(audio_path, duration=9.469)

    clips_src = os.path.join(WORK, "src_clips")
    os.makedirs(clips_src)
    short_red = os.path.join(clips_src, "short_red.mp4")   # 2s, precisa de loop pro segmento de 3.2s
    long_blue = os.path.join(clips_src, "long_blue.mp4")   # 6s, precisa de corte pro segmento de 3.3s
    exact_green = os.path.join(clips_src, "exact_green.mp4")  # 3s, quase exato pro segmento de ~2.97s
    _make_solid_clip(short_red, "red", 2)
    _make_solid_clip(long_blue, "blue", 6)
    _make_solid_clip(exact_green, "green", 3)

    audio_duration = _probe_duration(audio_path)
    segments = [
        VideoSegment(start=0.0, end=3.2, provider="pexels", query="dummy"),
        VideoSegment(start=3.2, end=6.5, provider="pixabay", query="dummy"),
        VideoSegment(start=6.5, end=audio_duration, provider="mixkit", query="dummy"),
    ]

    clip_map = {"pexels": short_red, "pixabay": long_blue, "mixkit": exact_green}

    class FakeVideo:
        id = "v1"

    class FakeClient:
        def __init__(self, provider):
            self.provider = provider

        def search_all(self, query=None, category=None, max_pages=1):
            return [FakeVideo()]

        def download_video(self, video, output_dir):
            os.makedirs(output_dir, exist_ok=True)
            dest = os.path.join(output_dir, "clip.mp4")
            shutil.copy(clip_map[self.provider], dest)
            return dest

    output_path = os.path.join(WORK, "output", "final.mp4")
    progress_log = []

    final = assemble_video(
        segments, audio_path, output_path, os.path.join(WORK, "job"),
        get_client_fn=lambda p: FakeClient(p),
        on_progress=lambda stage, i, total: progress_log.append((stage, i, total)),
    )

    assert os.path.exists(final)
    final_duration = _probe_duration(final)
    assert abs(final_duration - audio_duration) < 0.15, (final_duration, audio_duration)
    print(f"OK: vídeo final gerado com duração {final_duration:.2f}s (áudio: {audio_duration:.2f}s).")

    # confirma que os segmentos aparecem na ordem/tempo certos (cores sólidas)
    assert _sample_color(final, 4.8) == (0, 0, 254), "esperava azul aos 4.8s (segmento 1, cortado de 6s pra 3.3s)"
    assert _sample_color(final, 8.0)[1] > 100 and _sample_color(final, 8.0)[0] < 50, "esperava verde aos 8.0s"
    print("OK: cada segmento aparece no tempo certo (loop e corte funcionaram corretamente).")

    assert progress_log[0] == ("buscando", 0, 3)
    assert progress_log[-1][0] == "sincronizando_audio"
    print("OK: callback de progresso é chamado nas etapas certas.")

    shutil.rmtree(WORK)


if __name__ == "__main__":
    test_assemble_video_end_to_end_with_loop_and_trim()
    print("\nTodos os testes de video_assembler.py passaram.")
