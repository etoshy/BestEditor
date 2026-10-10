"""Selo/cartão com caixa na cor do projeto: o texto tem que aparecer mesmo com
cor escura (antes a telinha usava texto #111 fixo — caixa vermelho-escura
escondia o "1979" do Selo de ano)."""
import os
import re

import dp_destaques


def test_video_exportado_texto_branco_e_enfase_sublinhada_em_caixa_escura(tmp_path):
    pal = dict(dp_destaques.paleta_padrao(), primaria="#7F1D1D")
    d = {"id": "a", "estilo": "selo_ano", "start": 1.0, "end": 4.0, "texto": "1979", "enfase": ["1979"]}
    ass = open(dp_destaques.gerar_ass([d], 1280, 720, str(tmp_path / "h.ass"), pal), encoding="utf-8").read()
    # máquina de escrever: uma letra por vez — nenhuma pode vir pintada da cor da caixa
    texto = [l for l in ass.splitlines() if l.startswith("Dialogue: 2")]
    assert texto
    for l in texto:
        assert "\\1c&H00FFFFFF&" in l          # branco em cima da caixa escura
        assert "\\u1" in l                     # ênfase vira sublinhado
        assert "\\1c&H001D1D7F&" not in l.split("}", 1)[1]


def test_telinha_calcula_a_cor_do_texto_pela_caixa():
    html = open(os.path.join(os.path.dirname(dp_destaques.__file__), "templates", "estudio.html"), encoding="utf-8").read()
    assert "function sobreCor(hex)" in html
    assert not re.search(r"background:\$\{corDestaque\(\)\};color:#111", html)
