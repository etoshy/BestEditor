"""
Teste offline de brave_api_client.py: parsing dos resultados
(mockando `brave_image_api.search_images_browser`) e download por
streaming (mockando a sessão `requests`). Mesmo espírito de
`test_bing_api_client.py`.
"""
import pytest
import requests

import brave_image_api as brave_mod
from brave_api_client import BraveAPIClient, BraveAPIClientError, BraveImage


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


@pytest.fixture(autouse=True)
def restaurar_search_images_browser():
    original = brave_mod.search_images_browser
    yield
    brave_mod.search_images_browser = original


def _mockar_busca(payload=None, excecao=None):
    async def fake(*a, **k):
        if excecao:
            raise excecao
        return payload
    brave_mod.search_images_browser = fake


def test_search_photos_all_parseia_resultados_reais():
    _mockar_busca({"results": [
        {"title": "Gojo", "alt": "alt text", "source": "criticalhits.com.br",
         "source_page": "https://criticalhits.com.br/x", "proxy_url": "https://imgs.search.brave.com/proxy.jpg",
         "original_url": "https://criticalhits.com.br/img.jpg"},
    ]})
    client = BraveAPIClient()
    imagens = client.search_photos_all("gojo eye")
    assert len(imagens) == 1
    img = imagens[0]
    assert isinstance(img, BraveImage)
    assert img.description == "Gojo"  # sem description própria, cai pro title
    assert img.author == "criticalhits.com.br"
    assert img.url == "https://criticalhits.com.br/x"
    assert img.id == "https://criticalhits.com.br/img.jpg"


def test_click_details_desligado_por_padrao():
    capturado = {}

    async def fake(*, q, limit, click_details, **k):
        capturado["click_details"] = click_details
        return {"results": []}
    brave_mod.search_images_browser = fake
    BraveAPIClient().search_photos_all("x")
    assert capturado["click_details"] is False


def test_search_com_termo_vazio_da_erro():
    client = BraveAPIClient()
    with pytest.raises(BraveAPIClientError):
        client.search_photos_all("")


def test_falha_na_busca_vira_braveapiclienterror():
    _mockar_busca(excecao=RuntimeError("Nenhum resultado de imagem foi encontrado no Brave."))
    client = BraveAPIClient()
    with pytest.raises(BraveAPIClientError):
        client.search_photos_all("termo qualquer")


def test_download_cai_pro_proxy_url_quando_nao_tem_original(tmp_path):
    img = BraveImage(title="só proxy", proxy_url="https://imgs.search.brave.com/p.jpg")
    client = BraveAPIClient()
    fake_session = FakeSession(FakeResp())
    client.session = fake_session
    client.download_photo(img, output_dir=str(tmp_path))
    assert fake_session.calls[0]["url"] == "https://imgs.search.brave.com/p.jpg"


def test_download_usa_source_page_como_referer_quando_disponivel(tmp_path):
    img = BraveImage(title="x", original_url="https://x.com/a.jpg", source_page="https://x.com/pagina")
    client = BraveAPIClient()
    fake_session = FakeSession(FakeResp())
    client.session = fake_session
    client.download_photo(img, output_dir=str(tmp_path))
    assert fake_session.calls[0]["headers"]["Referer"] == "https://x.com/pagina"


def test_download_sem_source_page_usa_referer_padrao(tmp_path):
    img = BraveImage(title="x", original_url="https://x.com/a.jpg")
    client = BraveAPIClient()
    fake_session = FakeSession(FakeResp())
    client.session = fake_session
    client.download_photo(img, output_dir=str(tmp_path))
    assert fake_session.calls[0]["headers"]["Referer"] == "https://search.brave.com/"


def test_download_sem_url_da_erro(tmp_path):
    img = BraveImage(title="sem nada")
    client = BraveAPIClient()
    with pytest.raises(BraveAPIClientError):
        client.download_photo(img, output_dir=str(tmp_path))
