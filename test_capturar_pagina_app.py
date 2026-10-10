"""
Teste de integração da aba "Capturar página" (/capturar-pagina) — usa
um Chromium de verdade (Playwright) contra uma página de teste servida
localmente numa thread, e ffmpeg de verdade pra renderizar o clipe.
Pulado automaticamente se o Playwright/Chromium não estiver disponível.
"""
import http.server
import threading
import time

import pytest

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as _p:
        _b = _p.chromium.launch(headless=True)
        _b.close()
    _PLAYWRIGHT_OK = True
except Exception:  # noqa: BLE001
    _PLAYWRIGHT_OK = False

pytestmark = pytest.mark.skipif(not _PLAYWRIGHT_OK, reason="Playwright/Chromium não disponível neste ambiente")

_PAGINA_TESTE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Teste App</title></head>
<body><article>
  <h1>Titulo de Teste</h1>
  <p>Um paragrafo qualquer aqui, com conteudo suficiente pra formar um bloco.</p>
  <p>Segundo paragrafo, pra ter mais de um bloco disponivel pra focar.</p>
</article></body></html>"""


@pytest.fixture(scope="module")
def servidor_local():
    import tempfile
    from pathlib import Path
    pasta = Path(tempfile.mkdtemp(prefix="capturar_pagina_app_teste_"))
    (pasta / "index.html").write_text(_PAGINA_TESTE, encoding="utf-8")

    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(pasta), **kw)
    servidor = http.server.ThreadingHTTPServer(("localhost", 0), handler)
    porta = servidor.server_port
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{porta}/index.html"
    servidor.shutdown()


@pytest.fixture
def app_module():
    import app as _app_module
    yield _app_module


@pytest.fixture
def client(app_module):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _espera_captura(app_module, captura_id, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        estado = app_module._CAPTURAS_PAGINA[captura_id]
        if estado["status"] != "capturando":
            return estado
        time.sleep(0.2)
    raise TimeoutError(f"captura {captura_id} não terminou em {timeout}s")


class TestPaginaInicial:
    def test_pagina_carrega(self, client):
        r = client.get("/capturar-pagina")
        assert r.status_code == 200
        assert "Capturar p\u00e1gina".encode() in r.data

    def test_submit_sem_url_400(self, client):
        r = client.post("/capturar-pagina", data={})
        assert r.status_code == 400

    def test_submit_url_sem_esquema_400(self, client):
        r = client.post("/capturar-pagina", data={"url": "exemplo.com/pagina"})
        assert r.status_code == 400


class TestFluxoCompleto:
    def test_captura_e_encontra_blocos(self, app_module, client, servidor_local):
        r = client.post("/capturar-pagina", data={"url": servidor_local})
        assert r.status_code == 200
        captura_id = r.get_json()["captura_id"]

        estado = _espera_captura(app_module, captura_id)
        assert estado["status"] == "pronto", estado.get("erro")
        assert any("Titulo de Teste" in b["texto"] for b in estado["blocos"])

    def test_pagina_de_detalhe_mostra_conteudo(self, app_module, client, servidor_local):
        r = client.post("/capturar-pagina", data={"url": servidor_local})
        captura_id = r.get_json()["captura_id"]
        _espera_captura(app_module, captura_id)

        r2 = client.get(f"/capturar-pagina/{captura_id}")
        assert r2.status_code == 200
        assert b"Titulo de Teste" in r2.data

    def test_detalhe_de_captura_inexistente_404(self, client):
        r = client.get("/capturar-pagina/nao-existe/")
        assert r.status_code in (404, 308)  # 308 se o Flask redirecionar por causa da barra -- também aceitável
        r2 = client.get("/capturar-pagina/nao-existe")
        assert r2.status_code == 404

    def test_screenshot_acessivel(self, app_module, client, servidor_local):
        r = client.post("/capturar-pagina", data={"url": servidor_local})
        captura_id = r.get_json()["captura_id"]
        _espera_captura(app_module, captura_id)

        r2 = client.get(f"/capturar-pagina/{captura_id}/screenshot")
        assert r2.status_code == 200
        assert len(r2.data) > 500

    def test_status_reflete_progresso(self, app_module, client, servidor_local):
        r = client.post("/capturar-pagina", data={"url": servidor_local})
        captura_id = r.get_json()["captura_id"]
        _espera_captura(app_module, captura_id)

        r2 = client.get(f"/capturar-pagina/{captura_id}/status")
        assert r2.status_code == 200
        data = r2.get_json()
        assert data["status"] == "pronto"
        assert data["quantidade_blocos"] >= 1

    def test_status_de_captura_inexistente_404(self, client):
        r = client.get("/capturar-pagina/nao-existe/status")
        assert r.status_code == 404


class TestGerarClipe:
    def _captura_pronta(self, app_module, client, servidor_local):
        r = client.post("/capturar-pagina", data={"url": servidor_local})
        captura_id = r.get_json()["captura_id"]
        estado = _espera_captura(app_module, captura_id)
        assert estado["status"] == "pronto", estado.get("erro")
        return captura_id, estado

    def test_gerar_clipe_modo_scroll(self, app_module, client, servidor_local):
        captura_id, _ = self._captura_pronta(app_module, client, servidor_local)
        r = client.post(f"/capturar-pagina/{captura_id}/renderizar", data={
            "modo": "scroll", "direcao_scroll": "baixo", "duracao": "3",
        })
        assert r.status_code == 200, r.data
        clipe_url = r.get_json()["clipe_url"]
        r2 = client.get(clipe_url)
        assert r2.status_code == 200
        assert len(r2.data) > 500

    def test_clipes_gerados_ficam_persistidos_no_estado(self, app_module, client, servidor_local):
        """Bug real corrigido: antes só o clipe recém-gerado era
        devolvido na resposta (nunca guardado) -- gerar um segundo
        clipe fazia o primeiro "sumir" da interface, mesmo o arquivo
        continuando no disco. Agora fica numa lista persistente."""
        captura_id, _ = self._captura_pronta(app_module, client, servidor_local)
        client.post(f"/capturar-pagina/{captura_id}/renderizar", data={"modo": "scroll", "duracao": "3"})
        client.post(f"/capturar-pagina/{captura_id}/renderizar", data={"modo": "scroll", "duracao": "3", "direcao_scroll": "cima"})

        estado = app_module._CAPTURAS_PAGINA[captura_id]
        assert len(estado["clipes_gerados"]) == 2  # os DOIS continuam listados, não só o último

        r = client.get(f"/capturar-pagina/{captura_id}")
        assert r.status_code == 200
        assert b"Clipes j\xc3\xa1 gerados (2)" in r.data

    def test_gerar_clipe_modo_foco(self, app_module, client, servidor_local):
        captura_id, estado = self._captura_pronta(app_module, client, servidor_local)
        bloco_id = estado["blocos"][0]["id"]
        r = client.post(f"/capturar-pagina/{captura_id}/renderizar", data={
            "modo": "foco", "bloco_id": bloco_id, "duracao": "3", "efeito": "highlight",
        })
        assert r.status_code == 200, r.data
        clipe_url = r.get_json()["clipe_url"]
        r2 = client.get(clipe_url)
        assert r2.status_code == 200
        assert len(r2.data) > 500

    def test_gerar_clipe_foco_bloco_inexistente_400(self, app_module, client, servidor_local):
        captura_id, _ = self._captura_pronta(app_module, client, servidor_local)
        r = client.post(f"/capturar-pagina/{captura_id}/renderizar", data={
            "modo": "foco", "bloco_id": "bloco_nao_existe", "duracao": "3",
        })
        assert r.status_code == 400

    def test_gerar_clipe_captura_inexistente_404(self, client):
        r = client.post("/capturar-pagina/nao-existe/renderizar", data={"modo": "scroll", "duracao": "3"})
        assert r.status_code == 404

    def test_clipe_inexistente_404(self, app_module, client, servidor_local):
        captura_id, _ = self._captura_pronta(app_module, client, servidor_local)
        r = client.get(f"/capturar-pagina/{captura_id}/clipe/nao-existe.mp4")
        assert r.status_code == 404
