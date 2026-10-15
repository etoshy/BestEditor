"""v84_117 — fundos dos destaques numa FAIXA só: 200 destaques = 1 sobreposição (antes eram 200 entradas rodando o vídeo
inteiro cada — a etapa levava horas)."""
import subprocess

import dp_destaques as dd


def test_muitos_destaques_viram_uma_faixa(tmp_path):
    ds = [{"estilo": "selo_ano", "start": k * 2.0, "end": k * 2.0 + 1.5, "texto": "x", "fundo": ["faixas", "grade"][k % 2]}
          for k in range(200)]
    ent, etapas = dd.filtros_de_tratamento(ds, 320, 180, str(tmp_path))
    assert ent.count("-i") == 1 and sum("overlay" in e for e in etapas) == 1
    lista = open(ent[ent.index("-i") + 1], encoding="utf-8").read()
    assert lista.count("duration") >= 400 and "vazio_320x180.png" in lista
    # dois ao mesmo tempo: outra faixa
    ent2, _e = dd.filtros_de_tratamento(ds[:2] + [dict(ds[0], start=0.5, end=1.0)], 320, 180, str(tmp_path))
    assert ent2.count("-i") == 2


def _px(p, ts, y):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(ts), "-i", p, "-frames:v", "1", "-vf", f"crop=1:1:160:{y},format=gray",
                        "-f", "rawvideo", "-"], capture_output=True)
    return r.stdout[0]


def test_fundo_aparece_so_no_tempo_do_destaque(tmp_path):
    base = str(tmp_path / "b.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x808080:s=320x180:d=8:r=30", "-f", "lavfi", "-i", "sine=d=8",
                    "-pix_fmt", "yuv420p", "-shortest", base], check=True)
    ds = [{"estilo": "selo_ano", "start": 2.0, "end": 3.5, "texto": "", "fundo": "faixas"},
          {"estilo": "selo_ano", "start": 5.0, "end": 6.0, "texto": "", "fundo": "faixas"}]
    out = dd.aplicar_destaques(base, str(tmp_path / "o.mp4"), ds, 320, 180, str(tmp_path / "w"))
    assert _px(out, 1.0, 3) > 100 and _px(out, 2.5, 3) < 20 and _px(out, 4.2, 3) > 100 and _px(out, 5.5, 3) < 20 and _px(out, 7.0, 3) > 100
