"""
Teste offline de yandex_api_client.py: parsing dos resultados
(mockando `yandex_image_api.search_images`) e download por streaming
(mockando a sessão `requests`). Mesmo espírito de
`test_bing_api_client.py`.
"""
import pytest
import requests

import yandex_image_api as yandex_mod
from yandex_api_client import YandexAPIClient, YandexAPIClientError, YandexImage


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
def restaurar_search_images():
    original = yandex_mod.search_images
    yield
    yandex_mod.search_images = original


def _mockar_busca(payload=None, excecao=None):
    async def fake(*a, **k):
        if excecao:
            raise excecao
        return payload
    yandex_mod.search_images = fake


def test_search_photos_all_parseia_resultados_reais():
    _mockar_busca({"results": [
        {"title": "Gojo", "alt": "alt", "source_page": "https://x.com/a", "source_domain": "x.com",
         "original_url": "https://x.com/a.jpg", "thumbnail_url": "https://x.com/t.jpg",
         "width": 1920.0, "height": 1080.0},
    ]})
    client = YandexAPIClient()
    imagens = client.search_photos_all("gojo eye")
    assert len(imagens) == 1
    img = imagens[0]
    assert isinstance(img, YandexImage)
    assert img.author == "x.com"
    assert img.width == 1920.0


def test_inspect_sources_desligado_por_padrao():
    capturado = {}

    async def fake(*, query, limit, inspect_sources, **k):
        capturado["inspect_sources"] = inspect_sources
        return {"results": []}
    yandex_mod.search_images = fake
    YandexAPIClient().search_photos_all("x")
    assert capturado["inspect_sources"] is False


def test_search_com_termo_vazio_da_erro():
    client = YandexAPIClient()
    with pytest.raises(YandexAPIClientError):
        client.search_photos_all("   ")


def test_falha_na_busca_vira_yandexapiclienterror():
    _mockar_busca(excecao=RuntimeError("erro simulado"))
    client = YandexAPIClient()
    with pytest.raises(YandexAPIClientError):
        client.search_photos_all("termo qualquer")


def test_download_sem_url_da_erro(tmp_path):
    img = YandexImage(title="sem nada")
    client = YandexAPIClient()
    with pytest.raises(YandexAPIClientError):
        client.download_photo(img, output_dir=str(tmp_path))


def test_download_usa_referer_do_yandex(tmp_path):
    img = YandexImage(title="x", original_url="https://x.com/a.jpg")
    client = YandexAPIClient()
    fake_session = FakeSession(FakeResp())
    client.session = fake_session
    client.download_photo(img, output_dir=str(tmp_path))
    assert fake_session.calls[0]["headers"]["Referer"] == "https://yandex.com/"
