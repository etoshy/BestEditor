"""v84: imagem trocada no meio de vídeos não pode "cortar" o export, e os
gestos de entrada/saída não podem mostrar quadros pretos entre as cenas."""
import os
import subprocess

import video_assembler as va


def _clipe(path, cor, dur=2.0, tb=None, sar=None):
    vf = "format=yuv420p"
    if sar:
        vf += f",setsar={sar}"
    args = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={cor}:s=320x240:r=30:d={dur}",
            "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "30"]
    if tb:
        args += ["-video_track_timescale", str(tb)]
    subprocess.run(args + [path], check=True)
    return path


def test_concat_com_parametros_diferentes_mantem_duracao_total(tmp_path):
    a = _clipe(str(tmp_path / "a.mp4"), "red")
    b = _clipe(str(tmp_path / "b.mp4"), "blue", tb=15360, sar="4/3")  # "imagem" com SAR/timebase diferentes
    c = _clipe(str(tmp_path / "c.mp4"), "green")
    assert len({va._assinatura_stream(p) for p in (a, b, c)}) > 1
    out = va._concat_clips([a, b, c], str(tmp_path / "out.mp4"), str(tmp_path))
    assert abs(va._probe_duration(out) - 6.0) < 0.3


def test_concat_igual_continua_sem_recodificar(tmp_path, monkeypatch):
    a = _clipe(str(tmp_path / "a.mp4"), "red")
    b = _clipe(str(tmp_path / "b.mp4"), "blue")
    chamado = []
    monkeypatch.setattr(va, "_concat_recodificando", lambda *x: chamado.append(x))
    out = va._concat_clips([a, b], str(tmp_path / "out.mp4"), str(tmp_path))
    assert not chamado
    assert abs(va._probe_duration(out) - 4.0) < 0.3


def test_quadro_vizinho_extrai_primeiro_e_ultimo(tmp_path):
    a = _clipe(str(tmp_path / "a.mp4"), "red")
    ini = va._quadro(a, str(tmp_path / "ini.jpg"), ultimo=False)
    fim = va._quadro(a, str(tmp_path / "fim.jpg"), ultimo=True)
    assert ini and os.path.getsize(ini) > 0
    assert fim and os.path.getsize(fim) > 0


def test_pedaco_curto_ou_longo_fica_com_a_duracao_do_plano(tmp_path):
    curto = _clipe(str(tmp_path / "c.mp4"), "red", dur=1.0)
    longo = _clipe(str(tmp_path / "l.mp4"), "blue", dur=4.0)
    certo = _clipe(str(tmp_path / "k.mp4"), "green", dur=2.0)
    out = va._garantir_duracoes([curto, longo, certo], [2.0, 2.0, 2.0], str(tmp_path))
    assert out[2] == certo and out[0] != curto and out[1] != longo
    assert all(abs(va._probe_duration(p) - 2.0) < 0.1 for p in out)
