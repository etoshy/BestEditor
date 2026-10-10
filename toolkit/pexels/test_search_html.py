"""
Teste offline do caminho de busca do Pexels via HTML (search_html), que
substituiu a navegação direta à API JSON como padrão — mais confiável,
porque é exatamente a navegação que um usuário de verdade faz.

O HTML usado aqui é uma amostra real, com os cards de vídeo, um anúncio do
Canva AI e um bloco patrocinado (iStock) — os dois últimos devem ser
ignorados pelo parser.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pexels_client import PexelsClient, BrowserResponse

FIXTURE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_fixtures", "search_page_sample.html")


def _load_fixture():
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return f.read()


def test_parse_search_html_ignores_ads():
    client = PexelsClient.__new__(PexelsClient)
    videos = client._parse_search_html(_load_fixture())

    assert len(videos) == 3, f"esperava 3 vídeos reais, achou {len(videos)}"
    ids = {v.id for v in videos}
    assert ids == {"36445059", "36371047", "29691053"}, ids

    v0 = next(v for v in videos if v.id == "36445059")
    assert v0.slug == "rustic-scene-with-dog-and-cat-by-tractor"
    assert v0.url == "https://www.pexels.com/video/rustic-scene-with-dog-and-cat-by-tractor-36445059/"
    assert v0.video_files[0]["link"] == "https://videos.pexels.com/video-files/36445059/15453954_360_640_30fps.mp4"
    assert v0.thumbnail.startswith("https://images.pexels.com/videos/36445059/")
    assert v0.raw["source"] == "html_search"
    print("OK: parseia os 3 cards de vídeo reais e ignora o anúncio Canva e o bloco patrocinado.")


def test_parse_video_page_html_fallback():
    client = PexelsClient.__new__(PexelsClient)
    detail_html = (
        '<h1 title="A dog and cat navigate a rustic farm setting near a tractor wheel.">x</h1>'
        '<video src="https://videos.pexels.com/video-files/36445059/15453957_1080_1920_30fps.mp4"></video>'
    )
    video_url = "https://www.pexels.com/video/rustic-scene-with-dog-and-cat-by-tractor-36445059/"
    pv = client._parse_video_page_html(detail_html, video_url)

    assert pv.id == "36445059"
    assert pv.description == "A dog and cat navigate a rustic farm setting near a tractor wheel."
    assert pv.width == 1080 and pv.height == 1920
    assert pv.video_files[0]["link"].endswith("15453957_1080_1920_30fps.mp4")
    print("OK: fallback de página de detalhe (sem __NEXT_DATA__) extrai descrição e vídeo em alta resolução.")


def test_search_html_navigates_to_normal_page_not_api():
    client = PexelsClient.__new__(PexelsClient)
    client.delay = 0

    class FakeSession:
        def __init__(self):
            self.requested_urls = []

        def request(self, method, url, params=None, timeout=20):
            full_url = url
            if params:
                from urllib.parse import urlencode
                full_url += "?" + urlencode(params)
            self.requested_urls.append(full_url)
            return BrowserResponse(200, _load_fixture(), full_url)

    client.session = FakeSession()
    videos = client.search_html(query="dog and cats", page=1)

    assert len(videos) == 3
    assert "search/videos/dog%20and%20cats/" in client.session.requested_urls[0]
    assert "api/v3" not in client.session.requested_urls[0]
    print("OK: search_html navega para a página normal de busca, nunca para a API.")


def test_search_all_falls_back_to_api_when_html_fails():
    import json

    api_response = json.dumps({"data": []})

    class FakeSessionHtmlFails:
        def __init__(self):
            self.calls = []

        def request(self, method, url, params=None, timeout=20):
            self.calls.append(url)
            if "search/videos" in url:
                return BrowserResponse(403, "Forbidden", url)
            return BrowserResponse(200, api_response, url)

        def fetch_api(self, url, params=None, timeout=20):
            self.calls.append(("fetch_api", url))
            return BrowserResponse(200, api_response, url)

    client = PexelsClient.__new__(PexelsClient)
    client.session = FakeSessionHtmlFails()
    client.delay = 0

    client.search_all(query="dog and cats", max_pages=1)
    assert any(isinstance(c, tuple) and c[0] == "fetch_api" for c in client.session.calls), (
        "deveria ter caído para o fallback da API quando a página HTML falha"
    )
    print("OK: search_all cai para a API JSON só quando a página HTML falha de verdade.")


def test_download_video_upgrades_quality_automatically():
    detail_html = (
        '<h1 title="A dog and cat navigate a rustic farm setting near a tractor wheel.">x</h1>'
        '<video src="https://videos.pexels.com/video-files/36445059/15453957_1080_1920_30fps.mp4"></video>'
    )
    downloads = []

    class FakeSession:
        def request(self, method, url, params=None, timeout=20):
            if "search/videos" in url:
                return BrowserResponse(200, _load_fixture(), url)
            if "/video/rustic-scene" in url:
                return BrowserResponse(200, detail_html, url)
            return BrowserResponse(404, "", url)

        def download(self, url, filepath, timeout=120):
            downloads.append(url)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            open(filepath, "w").close()
            return filepath

    client = PexelsClient.__new__(PexelsClient)
    client.session = FakeSession()
    client.delay = 0

    out_dir = "/tmp/_pexels_test_download"
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)

    videos = client.search_all(query="dog and cats", max_pages=1)
    v = next(x for x in videos if x.id == "36445059")
    assert v.video_files[0]["link"].endswith("360_640_30fps.mp4"), "deveria começar com o preview de baixa resolução"

    client.download_video(v, output_dir=out_dir)
    assert downloads[-1].endswith("15453957_1080_1920_30fps.mp4"), (
        "deveria ter feito upgrade automático para a qualidade real (1080p) na hora de baixar"
    )
    shutil.rmtree(out_dir)
    print("OK: download_video faz upgrade automático de preview (360p) para qualidade real (1080p).")


if __name__ == "__main__":
    test_parse_search_html_ignores_ads()
    test_parse_video_page_html_fallback()
    test_search_html_navigates_to_normal_page_not_api()
    test_search_all_falls_back_to_api_when_html_fails()
    test_download_video_upgrades_quality_automatically()
    print("\nTodos os testes de busca via HTML do Pexels passaram.")
