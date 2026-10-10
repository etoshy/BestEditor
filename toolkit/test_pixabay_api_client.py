"""
Teste offline de pixabay_api_client.py: busca com paginação manual,
rotação automática de chave em 429, parsing de tags/autor/arquivos, e
download por objeto.
"""
import os
import shutil

os.environ.setdefault("PIXABAY_API_KEYS", "chave_de_teste_dummy")

import api_keys as _api_keys_mod
from pixabay_api_client import PixabayAPIClient, PixabayAPIClientError, PixabayAPIVideo


class FakeResp:
    def __init__(self, status_code, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json


class FakeHTTPSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=20, stream=False):
        self.calls.append({"url": url, "params": dict(params or {})})
        return self.responses.pop(0)


def _bare_client(keys, cooldown_seconds=3600, max_key_rotations=None):
    client = PixabayAPIClient.__new__(PixabayAPIClient)
    client.pool = _api_keys_mod.APIKeyPool(keys, cooldown_seconds=cooldown_seconds)
    client.delay = 0
    client.max_key_rotations = max_key_rotations or len(keys)
    return client


_SAMPLE_HIT = {
    "id": 125, "pageURL": "https://pixabay.com/videos/id-125/", "tags": "flowers, yellow, blossom",
    "duration": 12, "user": "Coverr-Free-Footage",
    "videos": {
        "large": {"url": "https://v/large.mp4", "width": 1920, "height": 1080, "size": 6615235},
        "tiny": {"url": "https://v/tiny.mp4", "width": 640, "height": 360, "size": 1055449},
    },
}


def test_search_all_parses_tags_author_and_files():
    client = _bare_client(["chaveA"])
    client.session = FakeHTTPSession([FakeResp(200, {"total": 1, "totalHits": 1, "hits": [_SAMPLE_HIT]})])

    videos = client.search_all(query="flowers", max_pages=5, fetch_descriptions=False)
    assert len(videos) == 1
    v = videos[0]
    assert v.id == "125"
    assert v.tags == ["flowers", "yellow", "blossom"]
    assert v.author == "Coverr-Free-Footage"
    assert v.best_file()["url"] == "https://v/large.mp4"
    assert v.worst_file()["url"] == "https://v/tiny.mp4"
    assert client.session.calls[0]["params"]["key"] == "chaveA"
    print("OK: parseia tags/autor/arquivos e envia a chave como parâmetro de URL.")


def test_search_all_stops_pagination_when_page_smaller_than_per_page():
    client = _bare_client(["chaveA"])
    client.session = FakeHTTPSession([FakeResp(200, {"total": 1, "totalHits": 1, "hits": [_SAMPLE_HIT]})])
    client.search_all(query="flowers", max_pages=5, per_page=20, fetch_descriptions=False)
    assert len(client.session.calls) == 1
    print("OK: para de paginar quando a página vem incompleta (menos que per_page).")


def test_rotates_key_on_429():
    client = _bare_client(["chaveA", "chaveB"])
    client.session = FakeHTTPSession([
        FakeResp(429, headers={"Retry-After": "30"}),
        FakeResp(200, {"hits": [], "totalHits": 0}),
    ])
    client.search(query="dog")
    assert client.session.calls[0]["params"]["key"] == "chaveA"
    assert client.session.calls[1]["params"]["key"] == "chaveB"
    print("OK: rotaciona para a próxima chave quando a atual bate 429.")


def test_raises_immediately_on_invalid_key():
    client = _bare_client(["chave_invalida"], max_key_rotations=1)
    client.session = FakeHTTPSession([FakeResp(401, text="Unauthorized")])
    try:
        client.search(query="dog")
        raise AssertionError("deveria ter levantado PixabayAPIClientError")
    except PixabayAPIClientError:
        pass
    print("OK: erro claro e imediato para chave inválida (401), sem retry inútil.")


def test_download_video_by_object():
    class FakeStreamResp:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=1024):
            yield self.content

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class FakeDownloadSession:
        def get(self, url, stream=False, timeout=120):
            return FakeStreamResp(b"conteudo fake do video")

    client = _bare_client(["chaveA"])
    client.session = FakeDownloadSession()

    video = PixabayAPIVideo(
        id="125", title="t", tags=[], description="", url="https://x", duration=10, author="a", thumbnail="",
        video_files=[{"quality": "large", "url": "https://v/large.mp4", "width": 1920, "height": 1080}],
    )

    out_dir = "/tmp/_test_pixabay_api_download"
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    path = client.download_video(video, output_dir=out_dir)
    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == b"conteudo fake do video"
    shutil.rmtree(out_dir)
    print("OK: download_video baixa e salva o arquivo corretamente.")


if __name__ == "__main__":
    test_search_all_parses_tags_author_and_files()
    test_search_all_stops_pagination_when_page_smaller_than_per_page()
    test_rotates_key_on_429()
    test_raises_immediately_on_invalid_key()
    test_download_video_by_object()
    print("\nTodos os testes de pixabay_api_client.py passaram.")
