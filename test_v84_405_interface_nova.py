"""v84_405: 🧭 interface nova (padrão) — menu por objetivo, tela inicial, Ctrl+K, Configurações em abas — com a clássica
selecionável em ⚙ Configurações → Aparência."""
import json
import re

import pytest

import ui_catalogo as U


@pytest.fixture
def A(monkeypatch, tmp_path):
    import app as _app
    import site_config
    _app.app.config["TESTING"] = True
    monkeypatch.setattr(site_config, "CONFIG_PATH", str(tmp_path / "cfg.json"))
    return _app


def _nova(A, monkeypatch):
    monkeypatch.setattr(A, "_ui_interface", lambda: "nova")


def test_catalogo_sem_repetir_e_com_texto():
    urls = [it["url"] for it in U.todos()]
    assert len(urls) == len(set(urls)) >= 50
    for it in U.todos():
        assert it["nome"] and len(it["desc"]) > 15 and it["icone"]
    assert all(U.item(u) for u in U.ATALHOS_INICIO)
    assert U.atual("/curtos/link")["url"] == "/curtos/link" and U.atual("/curtos/canal/abc")["url"] == "/curtos"
    assert U.atual("/estudio/x")["url"] == "/jobs" and U.atual("/") is None


def test_toda_pagina_do_menu_abre(A, monkeypatch):
    _nova(A, monkeypatch)
    c = A.app.test_client()
    ruins = []
    for it in U.todos():
        try:
            r = c.get(it["url"])
        except Exception as exc:  # noqa: BLE001
            ruins.append((it["url"], repr(exc)[:300]))
            continue
        if r.status_code not in (200, 302):
            ruins.append((it["url"], r.status_code))
    assert not ruins, ruins


def test_inicio_e_novo_video(A, monkeypatch):
    _nova(A, monkeypatch)
    c = A.app.test_client()
    h = c.get("/").get_data(as_text=True)
    assert "O que vamos fazer hoje?" in h and 'id="nvFiltro"' in h and "Tudo o que dá pra fazer" in h
    for g in U.GRUPOS:
        assert f'id="g-{g["id"]}"' in h
    assert 'id="formNovoVideo"' not in h
    assert 'id="formNovoVideo"' in c.get("/novo-video").get_data(as_text=True)
    # a casca nova: menu agrupado, busca, trilha e a faixa "o que é esta página"
    v = c.get("/gerar-voz").get_data(as_text=True)
    assert 'class="ui-nova"' in v and "nvPaleta" in v and "nv-trilha" in v and "Voz e áudio" in v
    assert 'class="nv-sobre"' in v and "Gerar narração" in v and 'href="/settings#fish"' in v
    idx = json.loads(re.search(r'<script id="nvIndice" type="application/json">(.*?)</script>', v, re.S).group(1))
    assert len(idx) == len(U.todos())


def test_classica_continua_igual(A, monkeypatch):
    monkeypatch.setattr(A, "_ui_interface", lambda: "classica")
    c = A.app.test_client()
    h = c.get("/").get_data(as_text=True)
    assert 'id="formNovoVideo"' in h and "ui-nova" not in h and "Início — novo vídeo" in h
    assert "Início — novo vídeo" in c.get("/gerar-voz").get_data(as_text=True)


def test_trocar_interface(A):
    c = A.app.test_client()
    assert c.post("/ui/interface", json={"interface": "x"}).status_code == 400
    c.post("/ui/interface", json={"interface": "nova"})
    assert A._ui_interface() == "nova" and "O que vamos fazer hoje?" in c.get("/").get_data(as_text=True)
    c.post("/ui/interface", json={"interface": "classica"})
    assert A._ui_interface() == "classica" and 'id="formNovoVideo"' in c.get("/").get_data(as_text=True)


def test_configuracoes_em_abas(A, monkeypatch):
    _nova(A, monkeypatch)
    h = A.app.test_client().get("/settings").get_data(as_text=True)
    assert 'id="aparencia"' in h and 'name="ui_interface"' in h and "nova_ajustes.js" in h
    aj = json.loads(re.search(r'<script id="nvAjustes" type="application/json">(.*?)</script>', h, re.S).group(1))
    titulos = [re.sub(r"<[^>]+>", "", t) for t in re.findall(r"<h2[^>]*>(.*?)</h2>", h, re.S)]
    import unicodedata

    def sem(t):
        return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    for t in titulos:  # toda seção cai numa aba de verdade (não sobra nada no "geral" por engano)
        m = next((s for s in aj["secoes"] if sem(s["t"]) in sem(t)), None)
        assert m, t
    assert "Public Endpoints" not in h and "Endpoints públicos" in h
