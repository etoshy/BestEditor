"""v84_91 — 🖼️ buscador de imagem "google": Google Imagens pelo Modo IA do Google (app ia_google/, API POST /api/imagens).

Entra ao lado de Bing/Brave/Yandex/Startpage: mesma interface (cliente + lote com troca entre buscadores), link da
imagem ORIGINAL com largura/altura, as grandes e na proporção certa primeiro, e — sem a lista de provedores do
vídeo — só quando marcado ou pedido pelo próprio trecho (é mais lento e liga outro app)."""
import http.server
import json
import os
import socket
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "toolkit"))

import buscador_imagens_unificado as bu  # noqa: E402
import ia_google_rotas as igr  # noqa: E402
import video_assembler as va  # noqa: E402
from prompt_builder import (BROWSER_IMAGE_SEARCH_PROVIDERS, DEFAULT_PROVIDERS, PHOTO_SEARCH_PROVIDERS,  # noqa: E402
                            build_prompt, parse_ai_response)
from video_assembler import VideoSegment  # noqa: E402


def _im(url, w, h, pagina="https://site.com/p", titulo="foto"):
    return {"titulo": titulo, "site": "site.com", "pagina": pagina, "imagem": url, "miniatura": url + "?thumb",
            "largura": w, "altura": h}


class _ClienteFalso:
    """Imita o módulo ia_google_rotas (imagens / no_ar / min_lado_imagens)."""

    def __init__(self, tabela, no_ar=True, erro=None, min_lado=800):
        self.tabela, self._no_ar, self.erro, self._min = tabela, no_ar, erro, min_lado
        self.pedidos = []

    def imagens(self, termo, quantidade=10, timeout=300, **_):
        self.pedidos.append((termo, quantidade))
        if self.erro:
            raise igr.IAGoogleErro(self.erro)
        return {"termo": termo, "imagens": list(self.tabela.get(termo, [])), "aviso": None}

    def no_ar(self):
        return self._no_ar

    def min_lado_imagens(self):
        return self._min


def test_listas_de_provedores_tem_o_google():
    assert "google" in DEFAULT_PROVIDERS and "google" in PHOTO_SEARCH_PROVIDERS
    assert BROWSER_IMAGE_SEARCH_PROVIDERS[-1] == "google" and "google" in bu.ENGINES
    assert bu.ENGINES_PADRAO == ("bing", "brave", "yandex", "startpage")
    assert va._PHOTO_PROVIDER_MODULES["google"] == ("google_api_client", "GoogleAPIClient")
    import buscadores_enrichment as be
    import mix_midia
    assert "google" in be._CLIENTES_BUSCADORES and "google" in mix_midia.SO_FOTO


def test_lote_google_mapeia_ordena_e_tira_marca_dagua():
    g = _ClienteFalso({"torre eiffel": [
        _im("https://a.com/pequena.jpg", 500, 300),
        _im("https://b.com/em_pe.jpg", 1200, 2000),
        _im("https://c.com/grande.jpg", 3000, 2000, titulo="Torre Eiffel à noite"),
        _im("https://www.alamy.com/x.jpg", 4000, 3000),
    ]})
    r = bu._buscar_lote_google(["torre eiffel", "nada"], limit=3, orientation="horizontal", cliente=g)
    imgs = r["por_termo"]["torre eiffel"]
    assert [i.original_url for i in imgs] == ["https://c.com/grande.jpg", "https://b.com/em_pe.jpg", "https://a.com/pequena.jpg"]
    assert imgs[0].engine == "google" and imgs[0].width == 3000 and imgs[0].source_page == "https://site.com/p"
    assert imgs[0].title == "Torre Eiffel à noite" and imgs[0].thumbnail_url.endswith("?thumb")
    assert r["por_termo"]["nada"] == [] and r["erros"]["nada"] == "nenhuma imagem encontrada" and r["erro_geral"] is None
    assert g.pedidos[0] == ("torre eiffel", 8)  # folga de candidatos: limit + 4, no mínimo 8


def test_lote_google_so_marca_dagua_vira_erro_claro():
    g = _ClienteFalso({"x": [_im("https://www.shutterstock.com/a.jpg", 2000, 1000)]})
    r = bu._buscar_lote_google(["x"], limit=1, cliente=g)
    assert r["por_termo"]["x"] == [] and "marca d'água" in r["erros"]["x"]


def test_app_fora_do_ar_passa_os_termos_pro_proximo_buscador():
    g = _ClienteFalso({}, no_ar=False, erro="não deu pra ligar a IA do Google")
    r = bu._buscar_lote_google(["a", "b", "c"], limit=1, cliente=g)
    assert len(g.pedidos) == 1  # não insiste nos outros termos
    assert "IA do Google" in r["erro_geral"] and set(r["erros"]) == {"a", "b", "c"}


def test_buscar_lote_roteia_pro_google_e_proporcao_faz_uma_busca_so(monkeypatch):
    g = _ClienteFalso({"gato": [_im("https://a.com/q.jpg", 1000, 1000), _im("https://a.com/h.jpg", 1920, 1080)]})
    monkeypatch.setattr(bu, "_cliente_ia_google", lambda: g)
    r = bu.buscar_lote("google", ["gato"], limit=2)
    assert len(r["por_termo"]["gato"]) == 2
    g.pedidos.clear()
    r = bu.buscar_lote_proporcao("google", ["gato"], limit=1, proporcao="horizontal_quadrada")
    assert len(g.pedidos) == 1  # sem uma busca por orientação: o Modo IA não tem filtro e cada busca é lenta
    assert r["por_termo"]["gato"][0].original_url == "https://a.com/h.jpg"


def test_cliente_do_site_igual_aos_outros_buscadores(monkeypatch):
    from google_api_client import GoogleAPIClient, GoogleAPIClientError
    g = _ClienteFalso({"lua": [_im("https://a.com/lua.jpg", 1600, 900)]})
    monkeypatch.setattr(bu, "_cliente_ia_google", lambda: g)
    c = GoogleAPIClient(headless=True, proporcao="horizontal_quadrada")
    assert c.search_photos_all("lua")[0].original_url == "https://a.com/lua.jpg"
    assert c.search_photos_batch(["lua", "sol"], max_images=1) == {"lua": c.search_photos_all("lua")[:1], "sol": []}
    monkeypatch.setattr(bu, "_cliente_ia_google", lambda: _ClienteFalso({}, no_ar=False, erro="fora do ar"))
    with pytest.raises(GoogleAPIClientError):
        c.search_photos_all("lua")


def test_troca_entre_buscadores_com_google_preferido(tmp_path):
    chamadas = []

    def buscar(engine, termos):
        chamadas.append(engine)
        achou = engine == "bing"
        return {"por_termo": {t: [bu.ImagemBuscador(original_url=f"https://{engine}/{t}.jpg", engine=engine)] if achou else []
                              for t in termos}, "erros": {t: "nada" for t in termos if not achou}, "erro_geral": None}
    res = bu.buscar_e_baixar_primeira([{"query": "gojo", "engine": "google"}], str(tmp_path), paralelo=False,
                                      buscar_fn=buscar, baixar_fn=lambda img, pasta, stem: None, baixar=False)
    assert chamadas == ["google", "bing"] and res["gojo"]["ok"] and res["gojo"]["engine"] == "bing"


def test_montagem_so_usa_o_google_quando_marcado_ou_pedido(tmp_path):
    usados = {}

    def lote(itens, pasta, engines=None, **kw):
        usados["engines"] = list(engines)
        return {}
    bing = [(0, VideoSegment(start=0.0, end=4.0, provider="bing", query="torre", media_type="image"))]
    goog = [(0, VideoSegment(start=0.0, end=4.0, provider="google", query="torre", media_type="image"))]
    va.prefetch_browser_images(bing, str(tmp_path), {}, cache={}, lote_fn=lote)
    assert usados["engines"] == ["bing", "brave", "yandex", "startpage"]
    va.prefetch_browser_images(goog, str(tmp_path), {}, cache={}, lote_fn=lote)
    assert usados["engines"] == ["bing", "brave", "yandex", "startpage", "google"]
    va.prefetch_browser_images(bing, str(tmp_path), {"provedores_do_job": ["bing", "google"]}, cache={}, lote_fn=lote)
    assert usados["engines"] == ["bing", "google"]
    va.prefetch_browser_images(goog, str(tmp_path), {"provedores_do_job": ["pexels"]}, cache={}, lote_fn=lote)
    assert usados["engines"] == ["google"]


def test_prompt_e_json_da_ia_aceitam_foto_do_google():
    segs = [{"start": 0.0, "end": 4.0, "text": "A Torre Eiffel foi inaugurada em 1889."}]
    p = build_prompt(segs, providers=["pexels", "google"])
    assert '"google"' in p and "Google Images" in p
    r = parse_ai_response(json.dumps([{"start": 0.0, "end": 4.0, "provider": "google", "query": "Torre Eiffel 1889",
                                       "media_type": "image"}]), valid_providers=["pexels", "google"], total_duration=4.0)
    seg = r.segments[0]
    assert getattr(seg, "provider", None) == "google" and getattr(seg, "media_type", None) == "image"


def test_config_tamanho_minimo(tmp_path, monkeypatch):
    import site_config
    assert site_config.DEFAULT_CONFIG["ia_google_imagens_min_lado"] == 800
    monkeypatch.setattr(igr, "_cfg", lambda: {"ia_google_imagens_min_lado": 1920})
    assert igr.min_lado_imagens() == 1920
    monkeypatch.setattr(igr, "_cfg", lambda: {"ia_google_imagens_min_lado": "abc"})
    assert igr.min_lado_imagens() == 800
    monkeypatch.setattr(igr, "_cfg", lambda: {"ia_google_imagens_min_lado": 0})
    assert igr.min_lado_imagens() == 0


def test_pagina_de_configuracoes_tem_o_seletor():
    import app as A
    h = A.app.test_client().get("/settings").get_data(as_text=True)
    assert 'name="ia_google_imagens_min_lado"' in h
    h = A.app.test_client().get("/").get_data(as_text=True)
    assert 'value="google"' in h and "Google Imagens pelo Modo IA" in h


@pytest.fixture
def api_falsa(monkeypatch):
    """Servidor no formato da API do app ia_google (POST /api/imagens)."""
    pedidos = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def do_POST(self):  # noqa: N802
            corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            pedidos.append((self.path, corpo))
            d = {"termo": corpo["termo"], "total": 1, "imagens": [_im("https://a.com/o.jpg", 3579, 2684)], "aviso": None}
            b = json.dumps(d).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(igr, "porta", lambda: srv.server_address[1])
    yield pedidos
    srv.shutdown()


def test_cliente_segue_a_api_documentada(api_falsa):
    r = igr.imagens("  Satoru  Gojo ", quantidade=500, min_lado=1280)
    assert r["imagens"][0]["largura"] == 3579
    assert api_falsa[0] == ("/api/imagens", {"termo": "Satoru Gojo", "quantidade": 80, "min_lado": 1280,
                                             "verificar": False, "relacionadas": False})
    with pytest.raises(igr.IAGoogleErro):
        igr.imagens("   ")


def test_de_ponta_a_ponta_pela_api(api_falsa, monkeypatch):
    monkeypatch.setattr(igr, "_cfg", lambda: {"ia_google_imagens_min_lado": 800})
    r = bu.buscar_lote("google", ["gojo"], limit=1)
    assert r["por_termo"]["gojo"][0].original_url == "https://a.com/o.jpg" and r["erro_geral"] is None


def _porta_livre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_app_ia_google_atualizado_tem_imagens_e_mantem_o_olhar_de_novo(monkeypatch):
    """Sobe o ia_google/app.py de verdade (sem abrir navegador) e confere as rotas novas e as do site."""
    pytest.importorskip("playwright")
    p = _porta_livre()
    monkeypatch.setattr(igr, "porta", lambda: p)
    monkeypatch.setitem(igr._PROC, "proc", None)
    import requests
    try:
        igr.garantir(espera_s=40)
        base = f"http://127.0.0.1:{p}"
        r = requests.post(base + "/api/imagens", json={"termo": ""}, timeout=10)
        assert r.status_code == 400 and "termo" in r.json()["erro"]
        assert requests.get(base + "/api/imagens/baixar?url=ftp://x", timeout=10).status_code == 400
        assert requests.post(base + "/api/imagens/zip", json={"imagens": []}, timeout=10).status_code == 400
        st = requests.get(base + "/api/status", timeout=10).json()
        assert st["captcha"] is False and st["navegador_aberto"] is False
        h = requests.get(base + "/", timeout=10).text
        assert "telaImagens" in h
    finally:
        proc = igr._PROC.get("proc")
        if proc is not None:
            proc.terminate()
            proc.wait(10)
    pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ia_google")
    with open(os.path.join(pasta, "youtube.py"), encoding="utf-8") as f:
        assert "def consulta_olhar_de_novo" in f.read()
    with open(os.path.join(pasta, "static", "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert 'data-a="denovo"' in js and "#formImagens" in js
    with open(os.path.join(pasta, "ia_google.py"), encoding="utf-8") as f:
        assert "def _reabrir_visivel" in f.read()
