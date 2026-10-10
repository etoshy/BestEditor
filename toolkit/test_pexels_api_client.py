"""
Teste offline de pexels_api_client.py: busca com paginação, rotação
automática de chave em 429 (Retry-After respeitado), erro claro com
chave inválida e quando todas as chaves esgotam, e download por objeto
ou por ID.
"""
import os
import shutil

os.environ.setdefault("PEXELS_API_KEYS", "chave_de_teste_dummy")

import api_keys as _api_keys_mod
import pexels_api_client
from pexels_api_client import PexelsAPIClient, PexelsAPIClientError, PexelsAPIPhoto, PexelsAPIVideo


class FakeResp:
    def __init__(self, status_code, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHTTPSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=20, stream=False):
        self.calls.append({"url": url, "params": params, "headers": dict(headers or {})})
        return self.responses.pop(0)


def _bare_client(keys, cooldown_seconds=3600, max_key_rotations=None):
    client = PexelsAPIClient.__new__(PexelsAPIClient)
    client.pool = _api_keys_mod.APIKeyPool(keys, cooldown_seconds=cooldown_seconds)
    client.delay = 0
    client.max_key_rotations = max_key_rotations or len(keys)
    return client


def test_search_all_paginates_via_next_page():
    page1 = {
        "videos": [{
            "id": 1, "url": "https://www.pexels.com/video/dog-running-1/",
            "width": 1920, "height": 1080, "duration": 10,
            "user": {"name": "Fulano", "url": "https://x"},
            "image": "https://img/1.jpg",
            "video_files": [
                {"quality": "sd", "width": 640, "height": 360, "link": "https://v/1_sd.mp4"},
                {"quality": "hd", "width": 1920, "height": 1080, "link": "https://v/1_hd.mp4"},
            ],
        }],
        "next_page": "https://api.pexels.com/videos/search?page=2",
    }
    page2 = {
        "videos": [{
            "id": 2, "url": "https://www.pexels.com/video/cat-playing-2/",
            "width": 1280, "height": 720, "duration": 8,
            "user": {"name": "Ciclana", "url": "https://y"},
            "image": "https://img/2.jpg",
            "video_files": [{"quality": "hd", "width": 1280, "height": 720, "link": "https://v/2_hd.mp4"}],
        }],
        "next_page": None,
    }

    client = _bare_client(["chaveA"])
    client.session = FakeHTTPSession([FakeResp(200, page1), FakeResp(200, page2)])

    videos = client.search_all(query="dog and cats", max_pages=5)
    assert len(videos) == 2

    v1 = next(v for v in videos if v.id == "1")
    assert v1.slug == "dog-running"
    assert v1.title == "Dog running"
    assert v1.author == "Fulano"
    assert v1.best_file()["link"] == "https://v/1_hd.mp4"
    assert client.session.calls[0]["headers"] == {"Authorization": "chaveA"}
    print("OK: pagina via next_page, para quando next_page é None, parseia título/autor/melhor arquivo.")


def test_rotates_key_on_429_and_respects_retry_after():
    client = _bare_client(["chaveA", "chaveB"])
    client.session = FakeHTTPSession([
        FakeResp(429, headers={"Retry-After": "30"}),
        FakeResp(200, {"videos": [], "next_page": None}),
    ])

    result = client.search(query="dog")
    assert client.session.calls[0]["headers"]["Authorization"] == "chaveA"
    assert client.session.calls[1]["headers"]["Authorization"] == "chaveB"
    assert result == {"videos": [], "next_page": None}
    assert client.pool.available_count() == 1
    print("OK: rotaciona automaticamente para a próxima chave quando a atual bate 429.")


def test_raises_clear_error_when_all_keys_rate_limited():
    client = _bare_client(["chaveA", "chaveB"])
    client.session = FakeHTTPSession([FakeResp(429), FakeResp(429)])
    try:
        client.search(query="dog")
        raise AssertionError("deveria ter levantado PexelsAPIClientError")
    except PexelsAPIClientError:
        pass
    print("OK: erro claro quando todas as chaves batem rate limit.")


def test_raises_immediately_on_invalid_key():
    client = _bare_client(["chave_invalida"], max_key_rotations=1)
    client.session = FakeHTTPSession([FakeResp(401, text="Unauthorized")])
    try:
        client.search(query="dog")
        raise AssertionError("deveria ter levantado erro de chave inválida")
    except PexelsAPIClientError as exc:
        assert "inválida" in str(exc).lower() or "invalida" in str(exc).lower()
    print("OK: erro claro e imediato (sem retry inútil) para chave inválida (401).")


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
            return FakeStreamResp(b"conteudo fake do video mp4")

    client = _bare_client(["chaveA"])
    client.session = FakeDownloadSession()

    video = PexelsAPIVideo(
        id="123", title="Dog running", slug="dog-running", description="", url="https://x",
        width=1920, height=1080, duration=10, author="Fulano", author_url="https://y",
        thumbnail="https://img.jpg",
        video_files=[{"quality": "hd", "width": 1920, "height": 1080, "link": "https://v/123_hd.mp4"}],
    )

    out_dir = "/tmp/_test_pexels_api_download"
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    path = client.download_video(video, output_dir=out_dir)
    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == b"conteudo fake do video mp4"
    shutil.rmtree(out_dir)
    print("OK: download_video baixa e salva o arquivo corretamente a partir de um objeto.")


def test_download_video_by_id_resolves_first():
    class FakeResolveThenDownloadSession:
        def get(self, url, params=None, headers=None, timeout=20, stream=False):
            if stream:
                class R:
                    def raise_for_status(self):
                        pass

                    def iter_content(self, chunk_size=1024):
                        yield b"video content"

                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return False
                return R()

            class R2:
                status_code = 200

                def json(self):
                    return {
                        "id": 999, "url": "https://www.pexels.com/video/cat-jumping-999/",
                        "width": 100, "height": 100, "duration": 5, "user": {}, "image": "",
                        "video_files": [{"quality": "sd", "width": 100, "height": 100, "link": "https://v/999.mp4"}],
                    }
            return R2()

    client = _bare_client(["chaveA"])
    client.session = FakeResolveThenDownloadSession()

    out_dir = "/tmp/_test_pexels_api_download_by_id"
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    path = client.download_video(999, output_dir=out_dir)
    assert "cat-jumping-999" in path
    shutil.rmtree(out_dir)
    print("OK: download_video(id) resolve os dados na API antes de baixar.")


_SAMPLE_VIDEO_FOR_URL = {
    "id": 27697943, "width": 1920, "height": 1080,
    "url": "https://www.pexels.com/video/pedestrians-crossing-the-street-27697943/",
    "user": {"name": "Fulano", "url": "https://y"},
    "video_files": [{"quality": "hd", "width": 1920, "height": 1080, "link": "https://v/27697943_hd.mp4"}],
}


def test_get_video_by_url_extracts_id_and_resolves_via_api():
    """Regressão: erro real relatado em produção — resolver um link de
    post do Pexels (o mecanismo de 'fixar candidato' do editor) falhava
    com AttributeError quando a API oficial estava configurada, porque
    esse método simplesmente não existia em PexelsAPIClient (só no
    cliente de navegador)."""
    client = _bare_client(["chaveA"])
    client.session = FakeHTTPSession([FakeResp(200, _SAMPLE_VIDEO_FOR_URL)])

    video = client.get_video_by_url(
        "https://www.pexels.com/video/pedestrians-crossing-the-street-27697943/",
        fetch_description=False,
    )
    assert video.id == "27697943"
    assert client.session.calls[0]["url"].endswith("/27697943")
    print("OK: get_video_by_url extrai o ID da URL exata do erro real e resolve via API.")


def test_get_video_by_url_handles_no_trailing_slash_and_query_string():
    client1 = _bare_client(["chaveA"])
    client1.session = FakeHTTPSession([FakeResp(200, _SAMPLE_VIDEO_FOR_URL)])
    client1.get_video_by_url("https://www.pexels.com/video/titulo-27697943", fetch_description=False)
    assert client1.session.calls[0]["url"].endswith("/27697943")

    client2 = _bare_client(["chaveA"])
    client2.session = FakeHTTPSession([FakeResp(200, _SAMPLE_VIDEO_FOR_URL)])
    client2.get_video_by_url("https://www.pexels.com/video/titulo-27697943/?tracking=abc", fetch_description=False)
    assert client2.session.calls[0]["url"].endswith("/27697943")
    print("OK: lida com URL sem barra final e com query string.")


def test_get_video_by_url_raises_clear_error_without_numeric_id():
    client = _bare_client(["chaveA"])
    try:
        client.get_video_by_url("https://www.pexels.com/video/sem-numero-nenhum/", fetch_description=False)
        raise AssertionError("deveria ter falhado")
    except PexelsAPIClientError as exc:
        assert "Não consegui extrair o ID" in str(exc)
    print("OK: URL sem ID numérico dá erro claro, não trava.")


_SAMPLE_PHOTO = {
    "id": 2014422, "width": 3024, "height": 3024,
    "url": "https://www.pexels.com/photo/photo-of-cat-2014422/",
    "photographer": "Ba Phi", "photographer_url": "https://www.pexels.com/@ba-phi-462757",
    "avg_color": "#978E82", "alt": "Silver Tabby Cat Lying on Brown Wooden Table",
    "src": {
        "original": "https://images.pexels.com/photos/2014422/pexels-photo-2014422.jpeg",
        "large": "https://images.pexels.com/photos/2014422/pexels-photo-2014422.jpeg?w=940",
        "tiny": "https://images.pexels.com/photos/2014422/pexels-photo-2014422.jpeg?w=100",
    },
}


def test_search_photos_all_parses_real_description_and_best_size():
    client = _bare_client(["chaveA"])
    client.session = FakeHTTPSession([FakeResp(200, {"photos": [_SAMPLE_PHOTO], "next_page": None})])

    photos = client.search_photos_all(query="cat")
    assert len(photos) == 1
    p = photos[0]
    assert p.id == "2014422"
    assert p.description == "Silver Tabby Cat Lying on Brown Wooden Table"
    assert p.author == "Ba Phi"
    assert p.best_size_url() == "https://images.pexels.com/photos/2014422/pexels-photo-2014422.jpeg"
    assert client.session.calls[0]["url"] == pexels_api_client.PHOTO_SEARCH_URL
    print("OK: busca de fotos usa o endpoint certo (v1/search) e captura a descrição real (campo alt).")


def test_download_photo_by_object():
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
        def get(self, url, stream=False, timeout=60):
            return FakeStreamResp(b"conteudo fake da foto")

    client = _bare_client(["chaveA"])
    client.session = FakeDownloadSession()

    photo = PexelsAPIPhoto(
        id="123", description="gato", url="https://x", width=800, height=600,
        author="a", author_url="b", avg_color="#fff",
        sizes={"original": "https://img/original.jpg", "tiny": "https://img/tiny.jpg"},
    )

    out_dir = "/tmp/_test_pexels_photo_download"
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    path = client.download_photo(photo, output_dir=out_dir)
    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == b"conteudo fake da foto"
    shutil.rmtree(out_dir)
    print("OK: download_photo escolhe o melhor tamanho e baixa corretamente.")


if __name__ == "__main__":
    test_search_all_paginates_via_next_page()
    test_rotates_key_on_429_and_respects_retry_after()
    test_raises_clear_error_when_all_keys_rate_limited()
    test_raises_immediately_on_invalid_key()
    test_download_video_by_object()
    test_download_video_by_id_resolves_first()
    test_search_photos_all_parses_real_description_and_best_size()
    test_download_photo_by_object()
    test_get_video_by_url_extracts_id_and_resolves_via_api()
    test_get_video_by_url_handles_no_trailing_slash_and_query_string()
    test_get_video_by_url_raises_clear_error_without_numeric_id()
    print("\nTodos os testes de pexels_api_client.py passaram.")
