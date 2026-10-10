"""
Teste offline de startpage_api_client.py. Diferente dos outros três
clientes (Bing/Brave/Yandex, que têm uma função async autocontida), a
função original do Startpage recebe `page`/`context` já prontos -- quem
chama gerencia o navegador via `browser_session()`. Por isso o mock
aqui substitui tanto `browser_session` (por um gerenciador de contexto
assíncrono falso) quanto `search` (a função que de fato devolve os
resultados).
"""
import pytest
import requests

import startpage_image_api as startpage_mod
from startpage_api_client import StartpageAPIClient, StartpageAPIClientError, StartpageImage


class FakeResp:
    def __init__(self, status_code=200, content_chunks=None):
        self.status_code = status_code
        self._chunks = content_chunks or [b"fake-image-bytes"]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1024 * 1024):
        for chunk in self._chunks:
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, resposta):
        self.resposta = resposta
        self.calls = []

    def get(self, url, headers=None, stream=False, timeout=None):
        self.calls.append({"url": url, "headers": headers, "stream": stream})
        return self.resposta


class _FakeManager:
    def __init__(self):
        self.context = "fake-context"

    async def new_page(self):
        return "fake-page"


class _FakeBrowserSession:
    """Substitui `startpage_image_api.browser_session` -- um gerenciador
    de contexto assíncrono que devolve um `_FakeManager` (com `.context`
    e `.new_page()`), sem abrir navegador nenhum de verdade."""

    chamadas = []

    def __init__(self, *, headless=False, timeout_ms=30000):
        self.headless = headless

    async def __aenter__(self):
        _FakeBrowserSession.chamadas.append({"headless": self.headless})
        return _FakeManager()

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def restaurar_startpage():
    original_session = startpage_mod.browser_session
    original_search = startpage_mod.search
    _FakeBrowserSession.chamadas = []
    yield
    startpage_mod.browser_session = original_session
    startpage_mod.search = original_search


def _mockar_busca(payload=None, excecao=None):
    startpage_mod.browser_session = _FakeBrowserSession

    async def fake_search(page, context, **k):
        if excecao:
            raise excecao
        return payload
    startpage_mod.search = fake_search


def test_search_photos_all_parseia_resultados_reais():
    _mockar_busca({"results": [
        {"title": "Gojo", "description": "desc", "source_page": "https://x.com/a", "source_domain": "x.com",
         "original_url": "https://x.com/a.jpg", "thumbnail_url": "https://x.com/t.jpg", "width": 1920, "height": 1080},
    ]})
    client = StartpageAPIClient()
    imagens = client.search_photos_all("gojo eye")
    assert len(imagens) == 1
    img = imagens[0]
    assert isinstance(img, StartpageImage)
    assert img.url == "https://x.com/a"
    assert img.author == "x.com"


def test_usa_browser_session_com_headless_do_cliente():
    _mockar_busca({"results": []})
    StartpageAPIClient(headless=True).search_photos_all("x")
    assert _FakeBrowserSession.chamadas == [{"headless": True}]


def test_click_fica_true_por_padrao():
    # o próprio script original chama isso de "mecanismo comprovado" --
    # diferente do Brave/Yandex, aqui NÃO usamos o modo sem clique.
    capturado = {}

    async def fake_search(page, context, *, click, **k):
        capturado["click"] = click
        return {"results": []}
    startpage_mod.browser_session = _FakeBrowserSession
    startpage_mod.search = fake_search
    StartpageAPIClient().search_photos_all("x")
    assert capturado["click"] is True


def test_search_com_termo_vazio_da_erro_sem_abrir_navegador():
    client = StartpageAPIClient()
    with pytest.raises(StartpageAPIClientError):
        client.search_photos_all("")
    assert _FakeBrowserSession.chamadas == []  # nem chegou a tentar abrir o navegador


def test_falha_na_busca_vira_startpageapiclienterror():
    _mockar_busca(excecao=RuntimeError("erro simulado"))
    client = StartpageAPIClient()
    with pytest.raises(StartpageAPIClientError):
        client.search_photos_all("termo qualquer")


def test_download_sem_url_da_erro(tmp_path):
    img = StartpageImage(title="sem nada")
    client = StartpageAPIClient()
    with pytest.raises(StartpageAPIClientError):
        client.download_photo(img, output_dir=str(tmp_path))


def test_download_usa_referer_do_startpage(tmp_path):
    img = StartpageImage(title="x", original_url="https://x.com/a.jpg")
    client = StartpageAPIClient()
    fake_session = FakeSession(FakeResp())
    client.session = fake_session
    client.download_photo(img, output_dir=str(tmp_path))
    assert fake_session.calls[0]["headers"]["Referer"] == "https://www.startpage.com/"
