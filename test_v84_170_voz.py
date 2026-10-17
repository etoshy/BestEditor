"""v84_170: 🎙 botão "Gerar voz" no topo dos projetos e seletor de projeto no Gerador de voz."""
import numpy  # noqa: F401 — o /gerar-voz dispara o diagnóstico de GPU numa thread que importa o numpy; importado antes, sem corrida

import app as a
import dossies as ds


def test_gerar_voz_com_projeto():
    c = a.app.test_client()
    p = ds.criar(a.BASE_DIR, "Projeto voz teste")
    try:
        assert 'topo-btn voz' not in c.get(f"/modelos-video/{p['id']}").get_data(as_text=True)  # sem roteiro: sem botão
        p["resultado"] = {"roteiro": "Hallo Welt.", "roteiro_final": "Hallo Welt."}
        ds.salvar(a.BASE_DIR, p)
        h = c.get(f"/modelos-video/{p['id']}").get_data(as_text=True)
        assert f'href="/gerar-voz?dossie={p["id"]}"' in h
        g = c.get("/gerar-voz").get_data(as_text=True)
        assert 'id="projVoz"' in g and f'value="dossie:{p["id"]}"' in g and "Projeto voz teste" in g
        g = c.get(f"/gerar-voz?dossie={p['id']}").get_data(as_text=True)
        assert f'value="dossie:{p["id"]}" selected' in g and "Hallo Welt." in g
    finally:
        ds.excluir(a.BASE_DIR, p["id"])
