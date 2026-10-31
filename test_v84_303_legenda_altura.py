"""📐 v84_303: altura exata da legenda, margem livre dos lados (padrão 10%) e a palavra comprida cabendo no "palavra única"."""
import re

import dp_legendas as L


def _ass(tmp_path, cfg, palavras):
    cam = str(tmp_path / "l.ass")
    L.gerar_ass(palavras, L.normalizar(dict({"ativa": True}, **cfg)), 1080, 1920, cam)
    return open(cam, encoding="utf-8").read()


def test_altura_exata_e_margem(tmp_path):
    ws = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.35} for i, w in enumerate("o robo arremessou".split())]
    a = _ass(tmp_path, {"estilo": "seguir", "altura": 0.30}, ws)
    assert "\\an5\\pos(540,576)" in a  # centro em 30% da altura (1920 × 0,30)
    assert re.search(r"Style: Leg,[^\n]*,5,108,108,0,1", a)  # margem de 10% de cada lado (108 px)
    b = _ass(tmp_path, {"estilo": "seguir", "posicao": "base"}, ws)
    assert "\\an2\\pos(540,1785)" in b  # sem altura: vale a posição de sempre
    assert L.normalizar({"altura": "auto"})["altura"] is None and L.normalizar({"altura": 2})["altura"] == 0.95
    assert L.normalizar({})["margem"] == 0.10 and L.normalizar({"margem": 0.5})["margem"] == 0.25


def test_palavra_comprida_nao_passa_da_margem(tmp_path):
    ws = [{"word": "apresentação", "start": 0, "end": 0.6}]
    a = _ass(tmp_path, {"estilo": "palavra_unica", "tamanho": 0.075, "maiusculas": True}, ws)
    fs = int(re.search(r"\\fs(\d+)", a).group(1))
    fam = L.normalizar({})["fonte"]
    assert L.largura("APRESENTAÇÃO", fam, fs) * 1.08 <= 1080 * 0.8 + 2  # cabe entre as margens de 10%
    curta = _ass(tmp_path, {"estilo": "palavra_unica", "tamanho": 0.075}, [{"word": "oi", "start": 0, "end": 0.5}])
    assert int(re.search(r"\\fs(\d+)", curta).group(1)) > fs  # palavra curta continua grande
