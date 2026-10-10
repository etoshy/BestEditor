"""v81 — Bing/Brave/Yandex/Startpage buscam na proporção do vídeo (16:9 -> horizontal/quadrada)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "toolkit"))

import buscador_imagens_unificado as bu  # noqa: E402
import video_assembler as va  # noqa: E402
from site_config import SiteConfigError, save_site_config  # noqa: E402


def _img(url, w=None, h=None):
    return bu.ImagemBuscador(original_url=url, thumbnail_url=url, width=w, height=h)


class _Fake:
    """Simula `buscar_lote`: devolve por (orientação, termo) o que estiver em `tabela`."""

    def __init__(self, tabela):
        self.tabela = tabela
        self.chamadas = []

    def __call__(self, engine, termos, limit=1, headless=True, orientation="any", engine_options=None, **_):
        self.chamadas.append((orientation, list(termos), dict(engine_options or {})))
        por = {t: list(self.tabela.get((orientation, t), [])) for t in termos}
        return {"por_termo": por, "erros": {t: "nada" for t in termos if not por[t]}, "erro_geral": None}


def test_auto_segue_a_orientacao_do_video():
    assert va.proporcao_dos_buscadores({}) == "horizontal_quadrada"
    assert va.proporcao_dos_buscadores({"orientation": "9:16"}) == "vertical_quadrada"
    assert va.proporcao_dos_buscadores({"orientation": "16:9", "search_orientation": "mixed"}) == "qualquer"
    assert va.proporcao_dos_buscadores({"orientation": "9:16", "search_orientation": "16:9"}) == "horizontal_quadrada"
    assert va.proporcao_dos_buscadores({"buscadores_proporcao": "horizontal"}) == "horizontal"
    assert va.proporcao_dos_buscadores({"buscadores_proporcao": "lixo"}) == "horizontal_quadrada"


def test_horizontal_primeiro_quadrada_se_faltar_e_reserva_sem_filtro():
    fake = _Fake({
        ("horizontal", "gojo"): [_img("h1", 1600, 900)],
        ("square", "geto"): [_img("q1", 800, 800)],
        ("any", "sukuna"): [_img("v1", 600, 1200), _img("h9", 1200, 700)],
    })
    res = bu.buscar_lote_proporcao("brave", ["gojo", "geto", "sukuna"], limit=1, proporcao="horizontal_quadrada", buscar=fake)
    assert [c[0] for c in fake.chamadas] == ["horizontal", "square", "any"]
    assert fake.chamadas[1][1] == ["geto", "sukuna"]       # quadrada só pra quem faltou
    assert fake.chamadas[2][1] == ["sukuna"]               # sem filtro só pra quem não achou nada
    assert res["por_termo"]["gojo"][0].original_url == "h1"
    assert res["por_termo"]["geto"][0].original_url == "q1"
    # reserva: a horizontal vem antes da vertical mesmo o buscador tendo mandado a vertical primeiro
    assert [i.original_url for i in res["por_termo"]["sukuna"]] == ["h9", "v1"]
    assert res["erros"] == {}


def test_bing_usa_o_filtro_nativo_de_aspecto():
    fake = _Fake({("horizontal", "x"): [_img("h", 1920, 1080)]})
    bu.buscar_lote_proporcao("bing", ["x"], proporcao="horizontal_quadrada", buscar=fake)
    assert fake.chamadas[0][2] == {"aspect": "wide"}
    fake2 = _Fake({("square", "x"): [_img("q", 500, 500)]})
    bu.buscar_lote_proporcao("bing", ["x"], proporcao="quadrada", buscar=fake2)
    assert fake2.chamadas[0][2] == {"aspect": "square"}
    fake3 = _Fake({("horizontal", "x"): [_img("h", 1920, 1080)]})
    bu.buscar_lote_proporcao("yandex", ["x"], proporcao="horizontal", buscar=fake3)
    assert fake3.chamadas[0][2] == {}  # só o Bing tem esse filtro próprio


def test_nada_em_lugar_nenhum_vira_erro():
    res = bu.buscar_lote_proporcao("brave", ["zzz"], proporcao="horizontal", buscar=_Fake({}))
    assert res["por_termo"]["zzz"] == [] and res["erros"]["zzz"]


def test_cliente_usa_a_proporcao(monkeypatch):
    fake = _Fake({("horizontal", "gato"): [_img("h", 1000, 600)]})
    monkeypatch.setattr(bu, "buscar_lote", fake)
    from bing_api_client import BingAPIClient
    cli = BingAPIClient(headless=True, proporcao="horizontal_quadrada")
    assert cli.search_images("gato", max_images=1)[0].original_url == "h"
    assert fake.chamadas[0][0] == "horizontal"
    BingAPIClient(headless=True).search_images("gato", max_images=1)  # padrão: sem filtro, como antes
    assert fake.chamadas[-1][0] == "any"


def test_fabrica_do_site_passa_a_proporcao():
    cli = va.ClientFactory({"orientation": "9:16"}).get_photo_client("startpage")
    assert cli.proporcao == "vertical_quadrada"
    cli2 = va.ClientFactory({"orientation": "16:9", "buscadores_proporcao": "qualquer"}).get_photo_client("bing")
    assert cli2.proporcao == "qualquer"


def test_lote_da_montagem_recebe_a_proporcao(tmp_path):
    recebido = {}

    def lote(pedidos, pasta, **kw):
        recebido.update(kw)
        return {}
    seg = va.VideoSegment(start=0, end=2, provider="bing", query="gojo", media_type="image")
    va.prefetch_browser_images([(0, seg)], str(tmp_path), {"orientation": "16:9"}, cache={}, lote_fn=lote)
    assert recebido["proporcao"] == "horizontal_quadrada"


def test_lote_baixar_primeira_pega_a_da_proporcao(monkeypatch, tmp_path):
    fake = _Fake({("horizontal", "gojo"): [_img("h1", 1600, 900)]})
    monkeypatch.setattr(bu, "buscar_lote", fake)
    baixadas = []
    out = bu.buscar_e_baixar_primeira(["gojo"], str(tmp_path), engines=["brave"], paralelo=False, proporcao="horizontal_quadrada",
                                      baixar_fn=lambda img, pasta, stem: (baixadas.append(img.original_url), str(tmp_path / "a.jpg"))[1])
    assert baixadas == ["h1"] and out["gojo"]["ok"]


def test_configuracao(tmp_path):
    cfg = str(tmp_path / "c.json")
    assert save_site_config({"buscadores_proporcao": "horizontal"}, cfg)["buscadores_proporcao"] == "horizontal"
    with pytest.raises(SiteConfigError, match="buscadores_proporcao"):
        save_site_config({"buscadores_proporcao": "diagonal"}, cfg)


def test_pagina_de_configuracoes_tem_o_seletor():
    import app as app_module
    html = app_module.app.test_client().get("/settings").get_data(as_text=True)
    assert 'name="buscadores_proporcao"' in html and "Horizontal, e quadrada se faltar" in html
