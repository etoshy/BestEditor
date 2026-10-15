"""v84_115 — ⚡ exportação em pedaços paralelos: os passes finais (destaques, legenda, filtro, qualidade) rodam em N
ffmpeg ao mesmo tempo e são emendados sem recodificar; o resultado é o mesmo vídeo do jeito de sempre."""
import subprocess

import pytest

import export_paralelo as ep


def _base(tmp_path, d=12):
    base = tmp_path / "b.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=320x180:d={d}:r=30", "-f", "lavfi", "-i", f"sine=d={d}",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(base)], check=True)
    return str(base)


def _info(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                        "stream=nb_read_frames:format=duration", "-of", "default=nw=1", p], capture_output=True, text=True)
    d = dict(x.split("=") for x in r.stdout.split())
    a = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", p],
                       capture_output=True, text=True).stdout
    return int(d["nb_read_frames"]), float(d["duration"]), "audio" in a


def _quadro(p, t, tmp_path, nome):
    out = tmp_path / f"{nome}.gray"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", p, "-frames:v", "1", "-vf", "scale=160:90,format=gray",
                    "-f", "rawvideo", str(out)], check=True)
    return out.read_bytes()


def _dif(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


@pytest.fixture
def quatro(monkeypatch):
    monkeypatch.setattr(ep, "escolher", lambda dur, *a, **k: (4, "teste"))
    monkeypatch.setattr(ep, "MIN_PEDACO_S", 1.0)


def test_escolher():
    ram = lambda: {"livre": 16.0, "total": 32.0}  # noqa: E731
    assert ep.escolher(3600, "1", ram, 16, None) == (1, "exportação em paralelo desligada")
    assert ep.escolher(30, "auto", ram, 16, None)[0] == 1  # curto
    n, motivo = ep.escolher(3600, "auto", ram, 16, None)
    assert n == 4 and "automático" in motivo
    assert ep.escolher(3600, "8", ram, 6, None)[0] == 3 and "CPU" in ep.escolher(3600, "8", ram, 6, None)[1]
    assert ep.escolher(3600, "8", lambda: {"livre": 3.0, "total": 8.0}, 16, None)[0] == 1
    assert ep.escolher(3600, "8", ram, 32, "h264_nvenc")[0] == ep.SESSOES_PLACA + 1
    js = ep.janelas(10.0, 3)
    assert sum(q for _i, q in js) == 300 and js[1][0] == pytest.approx(100 / 30)


def test_legenda_em_pedacos_igual_ao_jeito_de_sempre(tmp_path, quatro):
    import video_assembler as va
    base = _base(tmp_path)
    ass = tmp_path / "l.ass"
    ass.write_text("[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, "
                   "PrimaryColour, BackColour, Bold, Alignment, MarginV\nStyle: Default,Arial,40,&H00FFFFFF,&H00000000,1,2,10\n\n"
                   "[Events]\nFormat: Layer, Start, End, Style, Text\nDialogue: 0,0:00:08.00,0:00:10.00,Default,LEGENDA\n", encoding="utf-8")
    par = str(tmp_path / "par.mp4")
    va.burn_captions(base, str(ass), par)
    seq = str(tmp_path / "seq.mp4")
    va._run_ffmpeg(["-i", base, "-vf", f"ass={va._escape_path_for_ffmpeg_filter(str(ass))}", "-c:a", "copy", seq])
    fp, dp, ap = _info(par)
    fs, ds, _as = _info(seq)
    assert fp == fs == 360 and abs(dp - ds) < 0.1 and ap
    assert not list(tmp_path.glob("_pedacos_legenda/_legenda*.mp4"))
    # a legenda (em 8–10 s, no 3º pedaço) aparece igual nos dois; antes dela também
    for t in (2.0, 5.5, 9.0, 11.5):
        assert _dif(_quadro(par, t, tmp_path, f"p{t}"), _quadro(seq, t, tmp_path, f"s{t}")) < 6, t
    assert _dif(_quadro(par, 9.0, tmp_path, "p9"), _quadro(par, 7.0, tmp_path, "p7")) > 0  # sanity


def test_destaques_em_pedacos(tmp_path, quatro):
    import dp_destaques as dd
    base = _base(tmp_path)
    ds = [{"estilo": "selo_ano", "start": 1.0 + k * 2.5, "end": 2.8 + k * 2.5, "texto": f"ANO {1900 + k}", "fundo": "faixas"}
          for k in range(4)]
    par = dd.aplicar_destaques(base, str(tmp_path / "par.mp4"), ds, 320, 180, str(tmp_path / "wp"))
    ep.escolher = lambda dur, *a, **k: (1, "x")  # o fixture restaura
    seq = dd.aplicar_destaques(base, str(tmp_path / "seq.mp4"), ds, 320, 180, str(tmp_path / "ws"))
    fp, dp, ap = _info(par)
    fs, ds_, as_ = _info(seq)
    assert fp == fs == 360 and abs(dp - ds_) < 0.1 and ap and as_
    for t in (1.5, 4.2, 6.6, 9.3, 11.0):
        assert _dif(_quadro(par, t, tmp_path, f"p{t}"), _quadro(seq, t, tmp_path, f"s{t}")) < 6, t


def test_placa_falha_refaz_todos_na_cpu_e_erro_volta_pro_jeito_de_sempre(tmp_path, quatro, monkeypatch):
    import qualidade_export as qe
    base = _base(tmp_path, 6)
    monkeypatch.setattr(qe, "ajustar", lambda cmd: [("h264_nvenc" if c == "libx264" else c) for c in cmd])
    monkeypatch.setattr(qe, "usa_hw", lambda cmd: "h264_nvenc" in cmd)
    monkeypatch.setattr(ep, "MIN_PEDACO_S", 1.0)
    falas = []
    monkeypatch.setattr(ep, "print", lambda *a, **k: falas.append(" ".join(map(str, a))), raising=False)
    out = str(tmp_path / "o.mp4")
    assert ep.vf_em_pedacos(base, out, "hue=s=0", 6.0, str(tmp_path / "w"), "f", n=3)
    assert _info(out)[0] == 180
    assert any("refazendo os pedaços na CPU" in f for f in falas)
    # filtro inválido: falha → tentar devolve None (quem chamou faz do jeito de sempre)
    assert ep.tentar("teste", lambda: ep.vf_em_pedacos(base, out, "filtro_que_nao_existe", 6.0, str(tmp_path / "w"), "f", n=3)) is None


def test_modal_e_formulario(monkeypatch, tmp_path):
    import app as A
    import site_config
    monkeypatch.setattr(site_config, "CONFIG_PATH", str(tmp_path / "cfg.json"))
    assert site_config.load_site_config()["export_paralelo"] == "auto" and ep.modo_atual() == "auto"
    r = ep.recursos()
    assert r["nucleos"] >= 1 and ["1", "Desligado (um ffmpeg só)"] in r["modos"]
    ep.definir("3")
    assert ep.modo_atual() == "3"
    ep.limpar()
    src = open(A.__file__, encoding="utf-8").read()
    assert 'job["export_paralelo"] = request.form["export_paralelo"]' in src
    html = open("templates/estudio.html", encoding="utf-8").read()
    assert 'id="expPar"' in html and "['export_paralelo', $('expPar').value]" in html
