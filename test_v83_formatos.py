"""v83 — vídeo horizontal (16:9), vertical (9:16) e quadrado (1:1) por vídeo."""
import json
import os

import pytest

import cenas_dp
import dp_graficos
from prompt_builder import build_prompt
from site_config import SiteConfigError, resolution_for_orientation, save_site_config


def test_resolucoes():
    assert resolution_for_orientation("16:9", "1080p") == (1920, 1080)
    assert resolution_for_orientation("9:16", "720p") == (720, 1280)
    assert resolution_for_orientation("1:1", "1080p") == (1080, 1080)


def test_config_aceita_quadrado(tmp_path):
    cfg = str(tmp_path / "c.json")
    assert save_site_config({"orientation": "1:1"}, cfg)["orientation"] == "1:1"
    with pytest.raises(SiteConfigError):
        save_site_config({"orientation": "4:3"}, cfg)


def test_layout_vertical_empilha_e_texto_embaixo():
    lay = cenas_dp.adaptar_layout(cenas_dp._ARRANJOS["lado_a_lado"] | {"arranjo": "lado_a_lado"}, 1080, 1920)
    (x1, y1, w1, h1), (x2, y2, w2, h2) = lay["janelas"]
    assert y2 > y1 + h1 - 0.01            # um embaixo do outro
    assert w1 > 0.5 and w2 > 0.5          # largos
    assert max(y1 + h1, y2 + h2) < lay["texto"][1]  # texto não cobre as janelas
    cheia = cenas_dp.adaptar_layout(cenas_dp._ARRANJOS["tela_cheia"] | {"arranjo": "tela_cheia"}, 1080, 1920)
    assert cheia["janelas"] == [(0, 0, 1, 1)]
    # 16:9 e 1:1 ficam como estão
    orig = cenas_dp.layout("MULTITAKE_06")
    assert cenas_dp.adaptar_layout(orig, 1920, 1080) is orig and cenas_dp.adaptar_layout(orig, 1080, 1080) is orig
    ed = next(c for c in cenas_dp.catalogo_para_editor() if c["id"] == "MULTITAKE_06")
    assert ed["janelas_v"] and ed["texto_v"]


def test_grafico_no_vertical_ocupa_a_largura():
    g = {"posicao": "esquerda"}
    x, y, w, h = dp_graficos.caixa(g, 1080, 1920)
    assert w >= 1080 * 0.85
    x, y, w, h = dp_graficos.caixa({"posicao": "centro"}, 1920, 1080)
    assert (x, w) == (int(1920 * 0.18), int(1920 * 0.64))  # 16:9 igual a antes


def test_regra_no_prompt():
    trans = [{"start": 0, "end": 5, "text": "oi"}]
    assert "VERTICAL (9:16" in build_prompt(trans, providers=["pexels"], formato="9:16")
    assert "QUADRADO (1:1" in build_prompt(trans, providers=["pexels"], formato="1:1")
    assert "VERTICAL (9:16" not in build_prompt(trans, providers=["pexels"], formato="16:9")


@pytest.fixture
def app_module(monkeypatch):
    import app
    monkeypatch.setattr(app, "_start_assembly", lambda *a, **k: None)
    app.app.config["TESTING"] = True
    return app


def test_formato_por_video_e_troca_no_estudio(app_module):
    a = app_module
    jid = "fmtteste0001"
    os.makedirs(a._job_dir(jid), exist_ok=True)
    a._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "total_duration": 10.0, "providers": ["pexels"],
                    "pending_segments": [{"start": 0, "end": 10, "provider": "pexels", "query": "x", "media_type": "video"}],
                    "segments": [{"start": 0, "end": 10, "text": "oi"}], "orientation": "9:16"}
    assert a._job_site_cfg(a._JOBS[jid])["orientation"] == "9:16"
    c = a.app.test_client()
    html = c.get(f"/job/{jid}/edit-segments").get_data(as_text=True)
    assert 'id="gFormato"' in html and "let ALVO_W = 1080, ALVO_H = 1920" in html.replace("  ", " ")
    c.post(f"/job/{jid}/confirm-segments", data={"acao": "salvar", "orientacao": "1:1", "seg_0_start": "0", "seg_0_end": "10",
                                                   "seg_0_query": "x", "seg_0_provider": "pexels", "seg_0_source_mode": "auto"})
    assert a._JOBS[jid]["orientation"] == "1:1"
    # prévia do gráfico respeita o formato pedido
    r = c.post(f"/job/{jid}/grafico/previa", json={"grafico": {"tipo": "barras", "dados": [["a", 1], ["b", 2]], "start": 0, "end": 4}, "orientacao": "9:16"})
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(r.data)).size == (540, 960)
    a._JOBS.pop(jid, None)


def test_pagina_inicial_tem_o_formato(app_module):
    html = app_module.app.test_client().get("/").get_data(as_text=True)
    assert 'name="formato"' in html and 'name="formato_reuse"' in html and "Quadrado 1:1" in html


def test_sem_escolha_usa_o_das_configuracoes(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "load_site_config", lambda: {"orientation": "9:16"})
    assert app_module._orientacao_do_job({}) == "9:16"
    assert app_module._orientacao_do_job({"orientation": "1:1"}) == "1:1"
    assert app_module._orientacao_do_job({"orientation": "lixo"}) == "9:16"
