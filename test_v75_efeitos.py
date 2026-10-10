"""v75: o que faltava do JSON nos efeitos — entradas específicas dos destaques,
saídas slide/wipe/riscar, movimento interno (brilho/flutua), palavra por batida
com o sabor do estilo, tratamentos v2 que faltavam e sons por batida/tipagem."""
import json
import os
import re
import subprocess

import dp_destaques as dd
import dp_fundos as df
import dp_sons
import dp_visual


def _hl():
    return dp_visual.dp()["highlights"]


def test_nenhuma_entrada_cai_no_fade_generico():
    falta = sorted({(h.get("coreografia") or {}).get("entrada") for h in _hl().values()
                    if dd._anim((h.get("coreografia") or {}).get("entrada")) == "fade" and (h.get("coreografia") or {}).get("entrada") != "fade"})
    assert falta == [], falta


def _ass_de(eid, texto="Roma vs Cartago 1945", dur=3.0, palavras=None):
    d = {"estilo": eid, "start": 1.0, "end": 1.0 + dur, "texto": texto, "campos": {}}
    return dd._eventos_de_um(d, 1280, 720, dd.paleta_padrao(), palavras or [])


def _por(chave, valor):
    return next(k for k, h in _hl().items() if (h.get("coreografia") or {}).get(chave) == valor)


def test_entradas_novas_geram_desenho():
    assert sum("\\p1" in l and "\\move(" in l for l in _ass_de(_por("entrada", "doc_mira"))) == 4      # 4 cantoneiras
    assert any("\\move(" in l and "\\blur2" in l for l in _ass_de(_por("entrada", "doc_scanner")))     # linha que varre
    vs = _ass_de(_por("entrada", "doc_vs"))
    assert any(l.endswith("}VS") for l in vs) and sum("\\move(" in l for l in vs if l.startswith("Dialogue: 2")) == 2
    assert any("\\p1" in l for l in _ass_de(_por("entrada", "v2_pino_mapa")))
    assert sum(l.startswith("Dialogue: 0") for l in _ass_de(_por("entrada", "v2_grade_cinema"))) >= 8  # linhas da grade


def test_saidas_e_interna():
    sl = [l for l in _ass_de(_por("saida", "slide")) if l.startswith("Dialogue: 2")]
    assert any(re.search(r"\\move\(\d+,\d+,\d+,\d+,\d+,3000\)", l) for l in sl)
    wp = [l for l in _ass_de(_por("saida", "wipe")) if l.startswith("Dialogue: 2")]
    assert any(re.search(r"\\t\(\d+,3000,\\clip", l) for l in wp)
    assert any(l.startswith("Dialogue: 4") for l in _ass_de(_por("saida", "riscar")))
    assert any(l.startswith("Dialogue: 1") and "\\1a&HFF&" in l for l in _ass_de("ouro"))
    assert any("\\org(" in l for l in _ass_de("marca_3d_azul"))


def test_palavra_por_batida_com_sabor_do_estilo():
    ws = [{"word": w, "start": 1.1 + k * 0.4, "end": 1.4 + k * 0.4} for k, w in enumerate("isso mudou tudo".split())]
    linhas = _ass_de("sfx_cruzado", "isso mudou tudo", palavras=ws)
    assert any("\\fscx160" in l for l in linhas)


def test_todos_os_207_renderizam(tmp_path):
    ds = [{"estilo": eid, "start": k * 0.5, "end": k * 0.5 + 0.45, "texto": "Teste 1945 vs 30%", "campos": {}} for k, eid in enumerate(dd.catalogo())]
    ass = dd.gerar_ass(ds, 320, 180, str(tmp_path / "a.ass"))
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s=320x180:r=5:d={len(ds) * 0.5:.1f}",
                        "-vf", f"ass={ass}:fontsdir={dd.FONTES_DIR}", "-f", "null", "-"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]


def test_tratamentos_v2_todos_tem_fundo(tmp_path):
    for t in dp_visual.dp()["v2"]["tratamentos"]:
        if t["id"] == "none":
            continue
        fid, _cor = df.do_estilo({"tratamento": t["id"]})
        assert fid in df.IDS_DESTAQUE and fid != "nenhum", t
        et, png = df.etapas_destaque(fid, "#3E8EFF", 1.0, 0.0, 1.0, 160, 90, str(tmp_path))
        assert et or png, fid


def test_sons_por_batida_e_tipagem():
    eid = next(k for k, h in _hl().items() if (h.get("audio") or {}).get("evento") == "porBatida")
    ws = [{"word": w, "start": 1.1 + k * 0.4, "end": 1.4 + k * 0.4} for k, w in enumerate("um dois tres".split())]
    ev = dp_sons.eventos_automaticos([], [], [], [{"estilo": eid, "start": 1.0, "end": 3.0, "texto": "um dois tres"}],
                                     {"transicoes": False, "cenas": False, "palavras": ws})
    assert len(ev) == 3
    eid = next(k for k, h in _hl().items() if (h.get("audio") or {}).get("evento") == "tipagem")
    ev = dp_sons.eventos_automaticos([], [], [], [{"estilo": eid, "start": 1.0, "end": 3.0, "texto": "abc"}], {"transicoes": False, "cenas": False})
    assert len(ev) == 1
