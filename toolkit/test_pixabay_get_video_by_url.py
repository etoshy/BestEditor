"""
Teste automatizado de `PixabayClient.get_video_by_url()`: confirma que
o caminho original (JSON-LD) continua funcionando sem regressão, e que
o novo FALLBACK (extrair direto da tag <video> do video.js quando não
há JSON-LD) resolve o bug real relatado em produção — a página de
`clapperboard-flap-greenscreen-movie-649` não tinha nenhum bloco
JSON-LD, e o site sempre falhava com "Não encontrei nenhum bloco
JSON-LD do tipo VideoObject", mesmo a página tendo um vídeo válido.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

import pixabay.pixabay_client as pixabay_mod
from pixabay.pixabay_client import PixabayClient, PixabayClientError

# Amostra real de página SEM JSON-LD, só com a tag <video> do video.js —
# exatamente o HTML colado pelo usuário quando reportou o erro.
_REAL_PAGE_WITHOUT_JSONLD = """
<div class="vjs-container">
<video tabindex="-1" role="application" id="vjs_video_3_html5_api"
    poster="https://cdn.pixabay.com/video/2015/09/02/649-138138774_tiny.jpg"
    class="vjs-tech" loop="" muted="muted" autoplay=""
    src="https://cdn.pixabay.com/video/2015/09/02/649-138138774_medium.mp4"></video>
</div>
"""

# Amostra real de página COM JSON-LD (caminho original, precisa continuar funcionando)
_REAL_PAGE_WITH_JSONLD = """
<script type="application/ld+json">{"@context":"http://schema.org","license":"https://pixabay.com/service/license-summary/","name":"Leopard, Cub, Small. Free Stock Video","description":"Download this free video of Leopard Cub Small from Pixabay's vast library of royalty-free stock images, videos and music.","creator":{"@type":"Person","name":"NickyPe"},"@type":"VideoObject","contentUrl":"https://cdn.pixabay.com/video/2022/02/01/106286-672600280_large.mp4","thumbnailUrl":"https://cdn.pixabay.com/video/2022/02/01/106286-672600280_tiny.jpg","width":"1920","height":"1080","duration":"PT0M40S"}</script>
"""


class FakeResp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


def _client_with_response(monkeypatch, resp):
    client = PixabayClient.__new__(PixabayClient)
    client.session = object()
    client.delay = 0
    monkeypatch.setattr(pixabay_mod, "_request_with_retry", lambda *a, **kw: resp)
    return client


class TestGetVideoByUrlJsonLdPath:
    """O caminho original — continua funcionando sem regressão."""

    def test_resolves_via_jsonld_when_present(self, monkeypatch):
        client = _client_with_response(monkeypatch, FakeResp(200, _REAL_PAGE_WITH_JSONLD))
        video = client.get_video_by_url("https://pixabay.com/videos/leopard-cub-small-wildcat-106286/")

        assert video.download_url == "https://cdn.pixabay.com/video/2022/02/01/106286-672600280_large.mp4"
        assert video.author == "NickyPe"
        assert video.width == 1920
        assert video.height == 1080


class TestGetVideoByUrlFallbackWithoutJsonLd:
    """Regressão: a página real que quebrou em produção não tem NENHUM
    bloco JSON-LD — o fallback precisa extrair direto da tag <video>
    do video.js."""

    def test_resolves_via_video_tag_fallback_when_no_jsonld(self, monkeypatch):
        client = _client_with_response(monkeypatch, FakeResp(200, _REAL_PAGE_WITHOUT_JSONLD))
        video = client.get_video_by_url("https://pixabay.com/videos/clapperboard-flap-greenscreen-movie-649/")

        assert video.id == "649"
        assert video.slug == "clapperboard-flap-greenscreen-movie-649"
        assert video.download_url == "https://cdn.pixabay.com/video/2015/09/02/649-138138774_medium.mp4"
        assert video.thumbnail == "https://cdn.pixabay.com/video/2015/09/02/649-138138774_tiny.jpg"

    def test_raises_clear_error_when_neither_jsonld_nor_video_tag_found(self, monkeypatch):
        client = _client_with_response(monkeypatch, FakeResp(200, "<html><body>página vazia, sem vídeo</body></html>"))
        with pytest.raises(PixabayClientError, match="Não encontrei nem"):
            client.get_video_by_url("https://pixabay.com/videos/algo-999/")

    def test_raises_clear_error_when_video_tag_has_no_src(self, monkeypatch):
        html = '<video poster="https://x/thumb.jpg"></video>'
        client = _client_with_response(monkeypatch, FakeResp(200, html))
        with pytest.raises(PixabayClientError, match="sem atributo 'src'"):
            client.get_video_by_url("https://pixabay.com/videos/algo-999/")

    def test_raises_clear_error_on_http_failure(self, monkeypatch):
        client = _client_with_response(monkeypatch, FakeResp(404, ""))
        with pytest.raises(PixabayClientError, match="404"):
            client.get_video_by_url("https://pixabay.com/videos/nao-existe-999/")

    def test_passes_wait_for_selector_to_request(self, monkeypatch):
        """Confirma que a requisição pede pro navegador esperar a tag
        <video> ter o atributo 'src' preenchido — sem isso, o HTML
        capturado viria com a tag vazia (JS ainda não rodou)."""
        captured_kwargs = {}

        def fake_request(session, method, url, **kwargs):
            captured_kwargs.update(kwargs)
            return FakeResp(200, _REAL_PAGE_WITHOUT_JSONLD)

        client = PixabayClient.__new__(PixabayClient)
        client.session = object()
        client.delay = 0
        monkeypatch.setattr(pixabay_mod, "_request_with_retry", fake_request)

        client.get_video_by_url("https://pixabay.com/videos/clapperboard-flap-greenscreen-movie-649/")

        assert captured_kwargs.get("wait_for_selector") == "video"
        assert captured_kwargs.get("wait_for_attr") == "src"
