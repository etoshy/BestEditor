"""Montagem mais rápida: encoder da placa (com volta pra CPU) e qualidade ⚡ Rápida."""
import subprocess

import qualidade_export as q


def test_troca_libx264_pelo_nvenc_com_qualidade_parecida():
    cmd = ["ffmpeg", "-i", "a.mp4", "-c:v", "libx264", "-crf", "17", "-preset", "veryfast", "-pix_fmt", "yuv420p", "o.mp4"]
    out = q._para_hw(cmd, "h264_nvenc")
    assert "libx264" not in out and "-crf" not in out
    i = out.index("h264_nvenc")
    assert out[i + 1:i + 9] == ["-preset", "p4", "-rc", "vbr", "-cq", "17", "-b:v", "0"]
    assert out[-1] == "o.mp4" and "-pix_fmt" in out


def test_rapida_usa_ultrafast(monkeypatch):
    monkeypatch.setattr(q, "encoder_hw", lambda: None)
    q.definir("rapida")
    try:
        assert q.ajustar(["ffmpeg", "-c:v", "libx264", "-preset", "veryfast", "o.mp4"])[3:5] == ["-preset", "ultrafast"]
    finally:
        q.limpar()
    assert q.ajustar(["ffmpeg", "-c:v", "libx264", "-preset", "veryfast", "o.mp4"])[4] == "veryfast"


def test_placa_falhou_refaz_na_cpu(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "encoder_hw", lambda: "h264_nvenc")
    saida = str(tmp_path / "o.mp4")
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=red:s=64x64:d=0.3", "-c:v", "libx264", "-preset", "veryfast",
           "-pix_fmt", "yuv420p", saida]
    r = q.rodar(cmd, timeout=60)  # aqui não tem NVIDIA: o nvenc falha e o mesmo passo roda no libx264
    assert r.returncode == 0
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0", saida],
                       capture_output=True, text=True).stdout.strip()
    assert p == "h264"


def test_run_ffmpeg_do_montador_tambem_volta_pra_cpu(tmp_path, monkeypatch):
    import video_assembler as V
    monkeypatch.setattr(q, "encoder_hw", lambda: "h264_nvenc")
    saida = str(tmp_path / "o.mp4")
    V._run_ffmpeg(["-f", "lavfi", "-i", "color=blue:s=64x64:d=0.3", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", saida])
    assert subprocess.run(["ffprobe", "-v", "error", saida]).returncode == 0


def test_sem_gpu_nao_troca(monkeypatch):
    monkeypatch.setenv("NARRATION_SITE_SEM_GPU", "1")
    q._hw.update(testado=False)
    assert q.encoder_hw() is None
    assert "libx264" in q.ajustar(["ffmpeg", "-c:v", "libx264", "o.mp4"])
