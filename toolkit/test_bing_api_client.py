"""
Teste offline de bing_api_client.py: parsing dos resultados da busca
(mockando `bing_image_api.search_images_browser`, sem navegador/rede de
verdade) e o download por streaming (mockando a sessão `requests`, no
mesmo espírito de `test_wikipedia_api_client.py`).
"""
import asyncio

import pytest
import requests

import bing_api_client as bac
import bing_image_api as bing_mod
from bing_api_client import BingAPIClient, BingAPIClientError, BingImage


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
    original = bing_mod.search_images_browser
    yield
    bing_mod.search_images_browser = original


def _mockar_busca(payload=None, excecao=None):
    async def fake(*a, **k):
        if excecao:
            raise excecao
        return payload
    bing_mod.search_images_browser = fake


# --------------------------------------------------------------------------- #
# busca
# --------------------------------------------------------------------------- #

def test_search_photos_all_parseia_resultados_reais():
    _mockar_busca({"results": [
        {"title": "Gojo eyes", "description": "desc", "source_page": "https://x.com/a",
         "original_url": "https://x.com/a.jpg", "thumbnail_url": "https://x.com/a_thumb.jpg",
         "width": 1920, "height": 1080},
    ]})
    client = BingAPIClient()
    imagens = client.search_photos_all("gojo eyes")
    assert len(imagens) == 1
    img = imagens[0]
    assert isinstance(img, BingImage)
    assert img.title == "Gojo eyes"
    assert img.url == "https://x.com/a"  # propriedade .url espelha source_page
    assert img.id == "https://x.com/a.jpg"  # propriedade .id espelha original_url
    assert img.sizes == {"tiny": "https://x.com/a_thumb.jpg", "small": "https://x.com/a_thumb.jpg", "original": "https://x.com/a.jpg"}


def test_search_com_termo_vazio_da_erro_sem_chamar_a_busca():
    client = BingAPIClient()
    with pytest.raises(BingAPIClientError):
        client.search_photos_all("   ")


def test_falha_na_busca_vira_bingapiclienterror():
    _mockar_busca(excecao=RuntimeError("Nenhum resultado .iusc com murl foi encontrado."))
    client = BingAPIClient()
    with pytest.raises(BingAPIClientError):
        client.search_photos_all("termo qualquer")


def test_max_images_none_usa_padrao_de_5():
    capturado = {}

    async def fake(*, q, limit, **k):
        capturado["limit"] = limit
        return {"results": []}
    bing_mod.search_images_browser = fake
    BingAPIClient().search_photos_all("x", max_images=None)
    assert capturado["limit"] == 5


# --------------------------------------------------------------------------- #
# download
# --------------------------------------------------------------------------- #

def test_download_photo_usa_referer_do_bing(tmp_path):
    img = BingImage(title="Gojo", original_url="https://x.com/a.jpg")
    client = BingAPIClient()
    fake_session = FakeSession(FakeResp())
    client.session = fake_session

    caminho = client.download_photo(img, output_dir=str(tmp_path))
    assert caminho.endswith(".jpg")
    assert fake_session.calls[0]["headers"]["Referer"] == "https://www.bing.com/"


def test_download_sem_url_da_erro(tmp_path):
    img = BingImage(title="sem url")
    client = BingAPIClient()
    with pytest.raises(BingAPIClientError):
        client.download_photo(img, output_dir=str(tmp_path))


def test_download_cai_pro_thumbnail_quando_nao_tem_original(tmp_path):
    img = BingImage(title="só thumb", thumbnail_url="https://x.com/t.jpg")
    client = BingAPIClient()
    fake_session = FakeSession(FakeResp())
    client.session = fake_session
    client.download_photo(img, output_dir=str(tmp_path))
    assert fake_session.calls[0]["url"] == "https://x.com/t.jpg"


def test_download_existente_nao_baixa_de_novo(tmp_path):
    img = BingImage(title="existe", original_url="https://x.com/a.jpg")
    client = BingAPIClient()
    fake_session = FakeSession(FakeResp())
    client.session = fake_session

    caminho1 = client.download_photo(img, output_dir=str(tmp_path), filename="a.jpg")
    assert len(fake_session.calls) == 1
    caminho2 = client.download_photo(img, output_dir=str(tmp_path), filename="a.jpg", overwrite=False)
    assert len(fake_session.calls) == 1  # não chamou de novo
    assert caminho1 == caminho2
