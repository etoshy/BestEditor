"""
Teste automatizado de animepexels_client.py — cobre busca, paginação
automática, download, resolução por URL sintética, e o erro claro
quando o servidor local (app.py) não está rodando.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
import requests

from animepexels_client import AnimePexelsClient, AnimePexelsClientError, AnimePexelsVideo


class FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json


class FakeStreamResp:
    status_code = 200

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield b"conteudo de video fake" * 50


class FakeSession:
    def __init__(self, responses=None):
        self.responses = list(responses) if responses else []
        self.calls = []

    def get(self, url, params=None, timeout=None, stream=False):
        self.calls.append({"url": url, "params": params, "stream": stream})
        if stream:
            return FakeStreamResp()
        return self.responses.pop(0)


class TestSearchAll:
    def test_resolves_relative_urls_with_base_url(self):
        sample_response = {
            "results": [{
                "id": "abc-123", "description": "A ninja running through the forest",
                "human_caption": "ninja running through forest", "tags": ["action", "ninja"],
                "clip_url": "/storage/clips/abc-123.mp4", "thumbnail_url": "/storage/thumbs/abc-123.jpg",
                "duration_seconds": 3.5, "orientation": "horizontal", "resolution_name": "1080p",
                "anime_name": "Naruto", "episode_number": 5,
            }],
            "total": 1, "offset": 0, "limit": 20, "has_more": False,
        }
        client = AnimePexelsClient(base_url="http://localhost:5000")
        client.session = FakeSession([FakeResp(200, sample_response)])

        results = client.search_all(query="ninja fight")
        assert len(results) == 1
        v = results[0]
        assert v.clip_url == "http://localhost:5000/storage/clips/abc-123.mp4"
        assert v.thumbnail_url == "http://localhost:5000/storage/thumbs/abc-123.jpg"
        assert v.anime_name == "Naruto"
        assert client.session.calls[0]["url"] == "http://localhost:5000/api/search"
        assert client.session.calls[0]["params"]["q"] == "ninja fight"

    def test_paginates_automatically_via_has_more_and_offset(self):
        page1 = {"results": [{"id": "1", "clip_url": "/c/1.mp4"}, {"id": "2", "clip_url": "/c/2.mp4"}], "has_more": True}
        page2 = {"results": [{"id": "3", "clip_url": "/c/3.mp4"}], "has_more": False}

        client = AnimePexelsClient()
        client.session = FakeSession([FakeResp(200, page1), FakeResp(200, page2)])

        results = client.search_all(query="fight", per_page=2)
        assert [r.id for r in results] == ["1", "2", "3"]
        assert client.session.calls[0]["params"]["offset"] == 0
        assert client.session.calls[1]["params"]["offset"] == 2

    def test_tags_list_converted_to_comma_separated_string(self):
        client = AnimePexelsClient()
        client.session = FakeSession([FakeResp(200, {"results": [], "has_more": False})])
        client.search(query="x", tags=["luta", "espada"])
        assert client.session.calls[0]["params"]["tags"] == "luta,espada"

    def test_no_query_uses_gallery_endpoint(self):
        client = AnimePexelsClient()
        client.session = FakeSession([FakeResp(200, {"results": [], "has_more": False})])
        client.search(anime="Naruto")
        assert client.session.calls[0]["url"] == "http://localhost:5000/api/gallery"

    def test_search_all_accepts_category_as_query_synonym(self):
        """Compatibilidade com o resto do toolkit, que às vezes chama
        search_all(category=...) pra provedores baseados em categoria
        (como o Mixkit)."""
        client = AnimePexelsClient()
        client.session = FakeSession([FakeResp(200, {"results": [], "has_more": False})])
        client.search_all(category="ninja fight")
        assert client.session.calls[0]["params"]["q"] == "ninja fight"


class TestDownloadAndResolve:
    def test_download_video_from_object(self):
        work_dir = tempfile.mkdtemp()
        try:
            client = AnimePexelsClient(base_url="http://localhost:5000")
            client.session = FakeSession()
            video = AnimePexelsVideo(
                id="xyz-789", title="x", description="x", url="animepexels://clip/xyz-789",
                clip_url="http://localhost:5000/storage/clips/xyz-789.mp4",
            )
            path = client.download_video(video, output_dir=work_dir)
            assert os.path.exists(path)
            assert path.endswith("xyz-789.mp4")
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_get_video_by_url_resolves_via_synthetic_identifier(self):
        client = AnimePexelsClient(base_url="http://localhost:5000")
        client.session = FakeSession([FakeResp(200, {"id": "xyz-789", "clip_url": "/storage/clips/xyz-789.mp4"})])
        resolved = client.get_video_by_url("animepexels://clip/xyz-789")
        assert resolved.id == "xyz-789"
        assert client.session.calls[-1]["url"] == "http://localhost:5000/api/clips/xyz-789"

    def test_get_video_by_url_raises_clear_error_for_unrecognized_url(self):
        client = AnimePexelsClient()
        with pytest.raises(AnimePexelsClientError, match="não reconhecida"):
            client.get_video_by_url("https://algum-lugar/video")

    def test_download_raises_clear_error_when_no_clip_url(self):
        client = AnimePexelsClient()
        video = AnimePexelsVideo(id="1", title="x", description="x", url="x", clip_url="")
        with pytest.raises(AnimePexelsClientError, match="não tem clip_url"):
            client.download_video(video, output_dir=tempfile.mkdtemp())


class TestConnectionErrors:
    def test_raises_clear_error_when_local_server_not_running(self):
        class FakeSessionConnectionRefused:
            def get(self, url, params=None, timeout=None, stream=False):
                raise requests.exceptions.ConnectionError("Connection refused")

        client = AnimePexelsClient(base_url="http://localhost:5000")
        client.session = FakeSessionConnectionRefused()

        with pytest.raises(AnimePexelsClientError, match="app.py"):
            client.search_all(query="ninja")

    def test_raises_clear_error_on_404(self):
        client = AnimePexelsClient()
        client.session = FakeSession([FakeResp(404, {"error": "não encontrado"})])
        with pytest.raises(AnimePexelsClientError, match="404"):
            client.get_video_by_url("animepexels://clip/nao-existe")

    def test_raises_clear_error_on_invalid_json(self):
        class FakeRespBadJson:
            status_code = 200

            def json(self):
                raise ValueError("not json")

        client = AnimePexelsClient()
        client.session = FakeSession([FakeRespBadJson()])
        with pytest.raises(AnimePexelsClientError, match="JSON válido"):
            client.search_all(query="x")


class TestKeywordAndSemanticWeight:
    """Pedido do usuário: um prompt dedicado pro animepexels introduz os
    campos opcionais `keyword_weight`/`semantic_weight` por segmento —
    confirma que chegam corretamente até a chamada HTTP real."""

    def test_search_forwards_weight_params_to_api_call(self):
        client = AnimePexelsClient()
        client.session = FakeSession([FakeResp(200, {"results": [], "has_more": False})])
        client.search_all(query="ninja training alone forest", keyword_weight=2, semantic_weight=0.5)
        assert client.session.calls[0]["params"]["keyword_weight"] == 2
        assert client.session.calls[0]["params"]["semantic_weight"] == 0.5

    def test_search_omits_weight_params_when_not_given(self):
        client = AnimePexelsClient()
        client.session = FakeSession([FakeResp(200, {"results": [], "has_more": False})])
        client.search_all(query="x")
        assert "keyword_weight" not in client.session.calls[0]["params"]
        assert "semantic_weight" not in client.session.calls[0]["params"]
