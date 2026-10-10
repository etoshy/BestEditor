"""v82 — Censura: blur/pixelado/tarja numa área (com movimento) e bip/mudo no áudio."""
import json
import os
import subprocess

import pytest
from PIL import Image

import dp_censura as cz
import video_assembler as va


def _video_listrado(path, dur=3, W=640, H=360):
    # metade esquerda branca, direita preta (dá pra medir o desfoque na borda)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=black:s={W}x{H}:d={dur}:r=30",
                    "-vf", f"drawbox=x=0:y=0:w={W // 2}:h={H}:color=white:t=fill", "-pix_fmt", "yuv420p", path], check=True)


def _frame(path, t, destino):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", path, "-frames:v", "1", destino], check=True)
    return Image.open(destino).convert("RGB")


def _vol_max(path, ini, dur):
    r = subprocess.run(["ffmpeg", "-ss", str(ini), "-t", str(dur), "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    return float(r.stderr.split("max_volume:")[1].split("dB")[0])


def test_normalizar():
    it = cz.normalizar([
        {"tipo": "blur", "start": 1, "end": 2, "x": 0.9, "w": 0.3},           # x é puxado pra caber
        {"tipo": "tarja", "start": 0, "end": 1, "cor": "vermelho", "rotulo": "X" * 99},
        {"tipo": "bip", "start": 3, "end": 2},                                 # fim antes do início: fora
        {"tipo": "??", "start": 0, "end": 5, "x2": 0.5, "y2": 0.2},           # tipo desconhecido vira blur
        {"tipo": "mudo", "start": 9, "end": 20},
    ], duracao=10)
    assert [c["tipo"] for c in it] == ["tarja", "blur", "blur", "mudo"]
    assert it[2]["x"] == pytest.approx(0.7) and it[0]["cor"] == "#000000" and len(it[0]["rotulo"]) == 40
    assert it[1]["x2"] == 0.5 and it[3]["end"] == 10


def test_blur_so_na_area_e_so_no_tempo(tmp_path):
    src, out = str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")
    _video_listrado(src)
    itens = cz.normalizar([{"tipo": "blur", "start": 1, "end": 2, "x": 0.35, "y": 0.3, "w": 0.3, "h": 0.4, "intensidade": 10}])
    assert cz.aplicar_video(src, out, itens, 640, 360, str(tmp_path / "cz"), 3)
    f_dentro = _frame(out, 1.5, str(tmp_path / "f1.png"))
    f_fora = _frame(out, 0.5, str(tmp_path / "f2.png"))
    # na borda branco|preto, dentro da área: cinza (desfocado); fora do tempo: nítido
    assert 40 < f_dentro.getpixel((318, 180))[0] < 215
    assert f_fora.getpixel((318, 180))[0] > 230
    # fora da área continua nítido mesmo no tempo
    assert f_dentro.getpixel((318, 20))[0] > 230


def test_tarja_com_movimento_e_elipse(tmp_path):
    src, out = str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")
    _video_listrado(src, dur=4)
    itens = cz.normalizar([
        {"tipo": "tarja", "start": 0, "end": 4, "x": 0.0, "y": 0.0, "w": 0.2, "h": 0.2, "x2": 0.8, "y2": 0.0, "cor": "#FF0000"},
        {"tipo": "pixel", "start": 0, "end": 4, "x": 0.3, "y": 0.6, "w": 0.4, "h": 0.3, "forma": "elipse"},
    ])
    cz.aplicar_video(src, out, itens, 640, 360, str(tmp_path / "cz"), 4)
    ini = _frame(out, 0.1, str(tmp_path / "i.png"))
    fim = _frame(out, 3.9, str(tmp_path / "f.png"))
    vermelho = lambda p: p[0] > 180 and p[1] < 80 and p[2] < 80  # noqa: E731
    assert vermelho(ini.getpixel((40, 30))) and not vermelho(ini.getpixel((600, 30)))
    assert vermelho(fim.getpixel((600, 30))) and not vermelho(fim.getpixel((40, 30)))


def test_bip_e_mudo(tmp_path):
    a, b = str(tmp_path / "a.wav"), str(tmp_path / "b.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=6", a], check=True)
    itens = cz.normalizar([{"tipo": "bip", "start": 1, "end": 2, "volume": 0.5, "freq": 1000}, {"tipo": "mudo", "start": 4, "end": 5}])
    assert cz.aplicar_audio(a, b, itens, 6)
    assert _vol_max(b, 4.2, 0.6) < -60          # mudo
    assert _vol_max(b, 1.2, 0.6) > -25          # bip audível
    assert _vol_max(b, 2.5, 1.0) > -25          # fora: fala normal
    # o bip é o 1 kHz, não a fala de 300 Hz (que foi silenciada)
    r = subprocess.run(["ffmpeg", "-ss", "1.2", "-t", "0.6", "-i", b, "-af", "highpass=f=700,volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    assert float(r.stderr.split("max_volume:")[1].split("dB")[0]) > -25
    assert cz.aplicar_audio(a, b, cz.normalizar([{"tipo": "blur", "start": 0, "end": 1}]), 6) is False


def test_montagem_aplica_censura(tmp_path):
    W, H = 640, 360
    clip = str(tmp_path / "c.mp4")
    _video_listrado(clip, dur=5, W=W, H=H)
    audio = str(tmp_path / "n.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=4", audio], check=True)
    segs = [va.VideoSegment(start=0, end=2, provider="pexels", query="x", override_source={"source": "local_file", "value": clip, "kind": "video"}),
            va.VideoSegment(start=2, end=4, provider="pexels", query="y", override_source={"source": "local_file", "value": clip, "kind": "video"})]
    cfg = dict(va.load_site_config(), export_quality="480p", orientation="16:9", transition_type="none", filtro_cor="original",
               sons_auto={"transicoes": False, "cenas": False, "destaques": False})
    out = str(tmp_path / "out.mp4")
    va.assemble_video(segs, audio, out, str(tmp_path / "w"), site_cfg=cfg,
                      censura=[{"tipo": "tarja", "start": 1, "end": 3, "x": 0.0, "y": 0.0, "w": 0.3, "h": 0.3, "cor": "#00FF00"},
                               {"tipo": "mudo", "start": 1, "end": 2}])
    f = _frame(out, 1.5, str(tmp_path / "f.png"))
    p = f.getpixel((20, 20))
    assert p[1] > 180 and p[0] < 90  # tarja verde no canto
    assert _vol_max(out, 1.2, 0.6) < -50
    assert _vol_max(out, 2.5, 1.0) > -30


def test_estudio_tem_a_faixa_e_salva(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "_start_assembly", lambda *a, **k: None)
    jid = "cztestejob01"
    os.makedirs(app_module._job_dir(jid), exist_ok=True)
    app_module._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "total_duration": 10.0, "providers": ["pexels"],
                             "pending_segments": [{"start": 0, "end": 10, "provider": "pexels", "query": "x", "media_type": "video"}],
                             "segments": [{"start": 0, "end": 10, "text": "oi"}]}
    c = app_module.app.test_client()
    html = c.get(f"/job/{jid}/edit-segments").get_data(as_text=True)
    assert 'id="btnCensura"' in html and "censura_tipos" in html and 'id="layerCz"' in html
    r = c.post(f"/job/{jid}/confirm-segments", data={
        "acao": "salvar", "censura_json": json.dumps([{"tipo": "pixel", "start": 1, "end": 3, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}]),
        "seg_0_start": "0", "seg_0_end": "10", "seg_0_query": "x", "seg_0_provider": "pexels", "seg_0_source_mode": "auto"})
    assert r.status_code in (200, 302)
    assert app_module._JOBS[jid]["censura"][0]["tipo"] == "pixel"
    app_module._JOBS.pop(jid, None)


def test_graficos_da_ia_guardam_origem_pra_nao_duplicar():
    import dp_graficos
    g = dp_graficos.normalizar({"tipo": "barras", "dados": [["a", 1], ["b", 2]], "start": 0, "end": 4, "origem": "ia"})
    assert g["origem"] == "ia"
    assert "origem" not in dp_graficos.normalizar({"tipo": "barras", "dados": [["a", 1], ["b", 2]], "start": 0, "end": 4})
