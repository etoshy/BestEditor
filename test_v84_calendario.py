"""v84_93 — 📅 quadros de calendário e lista à mão no 🗞 Editorial: mês com dia circulado / X / marca-texto / riscando até
o dia, ano inteiro, folhinha arrancando páginas, placar de aeroporto virando datas e lista escrita à mão e riscada."""
import datetime as dt

import pytest

import dp_calendario as C
import dp_editorial as E

NOVOS = ["calendario_mes", "calendario_ano", "folhinha", "placar_datas", "lista_riscar"]


def test_registrados_no_editorial():
    for t in NOVOS:
        assert t in E.TIPOS and t in E._DESENHOS and t in E.EXEMPLOS
    ed = E.para_editor()
    assert all(t in str(ed) for t in NOVOS)
    assert "calendario_mes" in E.bloco_para_prompt()


def test_listas_de_dias_e_meses():
    assert C._lista_num("18", 31) == [18]
    assert C._lista_num("4, 18", 31) == [4, 18]
    assert C._lista_num("10-16", 31) == list(range(10, 17))
    assert C._lista_num("40", 31) == []
    assert C._lista_num("3-7", 12, C._mes_ou_none) == [3, 4, 5, 6, 7]
    assert C._lista_num("mar, jun", 12, C._mes_ou_none) == [3, 6]


def test_datas_e_passos():
    assert C._data("12/03/2019") == ("dia", dt.date(2019, 3, 12))
    assert C._data("03/2019")[0] == "mes" and C._data("2019") == ("ano", dt.date(2019, 1, 1))
    un, p = C._passos("01/2019", "03/2020", 100)
    assert un == "mes" and len(p) == 15 and p[0] == dt.date(2019, 1, 1) and p[-1] == dt.date(2020, 3, 1)
    un, p = C._passos("1900", "2026", 20)
    assert un == "ano" and len(p) <= 20 and p[0].year == 1900 and p[-1].year == 2026
    un, p = C._passos("01/03/2020", "21/03/2020", 100)
    assert un == "dia" and len(p) == 21
    i0, _ = C._indice_no_tempo(0.0, 0.4, 3.0, 10)
    i1, _ = C._indice_no_tempo(5.0, 0.4, 3.0, 10)
    assert i0 == 0 and i1 == 9


VARIANTES = [
    {"tipo": "calendario_mes", "mes": "setembro", "ano": 2001, "dias": "11", "marca": "x", "anotacao": "o dia", "idioma": "en"},
    {"tipo": "calendario_mes", "mes": 7, "ano": 2026, "dias": "6-12", "marca": "marca_texto", "anotacao": "a semana"},
    {"tipo": "calendario_mes", "mes": 3, "ano": 2026, "dias": "18", "marca": "riscar_ate", "anotacao": "o dia do assalto"},
    {"tipo": "calendario_ano", "ano": 2020, "meses": "mar, jun", "marca": "circulo", "anotacao": "duas vezes"},
    {"tipo": "calendario_ano", "ano": 2020, "meses": "3-11", "marca": "riscar_ate", "rotulo": "a pandemia"},
    {"tipo": "calendario_ano", "ano": 2020, "meses": "3-7", "marca": "marca_texto"},
    {"tipo": "folhinha", "de": "01/03/2020", "ate": "21/03/2020", "rotulo": "três semanas"},
    {"tipo": "folhinha", "de": "01/2019", "ate": "03/2020"},
    {"tipo": "folhinha", "de": "1990", "ate": "2026", "circular": "nao"},
    {"tipo": "placar_datas", "de": "04/2015", "ate": "06/2026", "rotulo": "onze anos"},
    {"tipo": "placar_datas", "de": "1969", "ate": "2026"},
    {"tipo": "lista_riscar", "titulo": "Plano", "itens": "x alugar\nv cavar\n! entrar no cofre", "estilo": "caderno"},
    {"tipo": "lista_riscar", "titulo": "Hoje", "itens": "x a\n! uma frase bem comprida que precisa caber no post-it", "estilo": "postit"},
    {"tipo": "lista_riscar", "titulo": "Suspeitos", "itens": "x o mordomo\n! o jardineiro", "estilo": "quadro"},
]


@pytest.mark.parametrize("v", VARIANTES)
def test_desenha_horizontal_e_vertical(v):
    it = E.normalizar(dict(v, start=0, end=6))
    assert it and it["tipo"] == v["tipo"]
    for W, H in ((640, 360), (360, 640)):
        ctx = E.novo_ctx()
        for t in (0.0, 1.0, 3.0, 4.6, 5.9):
            q = E.desenhar(it, t, W, H, ctx)
            assert q.size == (W, H) and q.mode == "RGBA"
        meio = E.desenhar(it, 3.5, W, H, ctx)
        assert meio.getchannel("A").getextrema()[1] == 255  # tela cheia no meio do quadro


def test_marca_texto_nao_tampa_os_numeros():
    """O marca-texto multiplica a cor: o número continua escuro por cima do amarelo (antes ficava um bloco opaco)."""
    from PIL import Image
    p = C._Pincel(Image.new("RGBA", (40, 20), (250, 250, 250, 255)))
    p.d.rectangle([10, 5, 14, 15], fill=(20, 20, 20, 255))  # "o número"
    p.realce([0, 0, 40, 20], 2, C.AMARELO_MARCA, 1.0)
    num, fundo = p.im.getpixel((12, 10)), p.im.getpixel((30, 10))
    assert num[0] < 40 and fundo[2] < 120 and fundo[0] > 200  # número escuro, fundo amarelo


def test_traco_translucido_nao_fura_a_folha():
    from PIL import Image
    im = Image.new("RGBA", (50, 50), (255, 255, 255, 255))
    C._traco(C._pincel(im), [(5, 25), (45, 25)], 1.0, (200, 0, 0, 120), 6)
    px = im.getpixel((25, 25))
    assert px[3] == 255 and 200 < px[0] and px[1] < 200  # misturou (vermelho claro), sem buraco


def test_lista_itens():
    assert C._itens_lista({"itens": "x a\nv b\n! c\nd\n\n"}) == [("riscar", "a"), ("check", "b"), ("circular", "c"), ("", "d")]


def test_sons():
    for t in NOVOS:
        it = E.exemplo(t)
        b = E.batidas(it)
        dur = it["end"] - it["start"]
        assert b and all(0 <= x[0] <= dur for x in b) and all(x[1] in E.SONS.values() for x in b)
    assert E.batidas(dict(E.exemplo("lista_riscar"), som="nenhum")) == []


def test_miniaturas(tmp_path):
    assert E.gerar_miniaturas(str(tmp_path), so=NOVOS, W=160, H=90) == 5
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(f"{t}.jpg" for t in NOVOS)
