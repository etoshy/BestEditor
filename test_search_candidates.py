"""
Teste automatizado de `search_candidates()` — a busca ao vivo (sem
baixar nada) que devolve thumbnail + label de alguns resultados reais,
usada pelo editor de segmentos pra deixar a pessoa VER opções antes de
escolher, em vez de trocar o termo às cegas.
"""
import pytest

from video_assembler import ClientFactory, VideoAssemblyError, search_candidates


class TestSearchCandidatesVideo:
    def test_extracts_video_preview_url_for_pexels(self):
        """"Monitor de Origem": Pexels traz um vídeo TOCÁVEL direto na
        busca (video_files), sem precisar baixar nada — usado pra
        mostrar a prévia em movimento no editor, não só uma imagem
        parada."""
        class FakeVideo:
            def to_dict(self):
                return {"id": "123", "title": "Dog running", "thumbnail": "https://img/123.jpg", "url": "https://x",
                        "video_files": [{"quality": "hd", "link": "https://v/123_hd.mp4"}]}

        class FakeClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

        cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)
        factory._clients["pexels"] = FakeClient()

        candidates = search_candidates("pexels", "dog", client_factory=factory)
        assert candidates[0]["video_preview_url"] == "https://v/123_hd.mp4"

    def test_extracts_video_preview_url_for_mixkit(self):
        class FakeVideo:
            def to_dict(self):
                return {"id": "456", "title": "Cat", "thumbnail": "https://img/456.jpg", "url": "https://x",
                        "preview_url": "https://assets.mixkit.co/videos/456/456-preview.mp4"}

        class FakeClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

        cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)
        factory._clients["mixkit"] = FakeClient()

        candidates = search_candidates("mixkit", "cat", client_factory=factory)
        assert candidates[0]["video_preview_url"] == "https://assets.mixkit.co/videos/456/456-preview.mp4"

    def test_pixabay_has_no_video_preview_url_from_search(self):
        """Pixabay não expõe um vídeo tocável na busca (só depois de
        abrir a página de detalhe) — o Monitor de Origem cai pro
        thumbnail estático nesse caso, honestamente, em vez de fingir
        um preview que não existe."""
        class FakeVideo:
            def to_dict(self):
                return {"id": "789", "title": "Bird", "thumbnail": "https://img/789.jpg", "url": "https://x"}

        class FakeClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

        cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)
        factory._clients["pixabay"] = FakeClient()

        candidates = search_candidates("pixabay", "bird", client_factory=factory)
        assert candidates[0]["video_preview_url"] == ""

    def test_closes_internally_created_factory_after_search(self, monkeypatch):
        """Regressão: search_candidates() criava uma ClientFactory nova
        a cada chamada sem client_factory explícito (o caso da rota do
        Flask, chamada a cada clique em 'Buscar' no editor) mas nunca
        fechava a sessão/navegador depois — um vazamento de recurso
        real, que abriria um Chrome novo a cada clique sem nunca
        liberá-lo.
        """
        import video_assembler

        closed_factories = []

        class FakeVideo:
            def to_dict(self):
                return {"id": "1", "title": "x", "thumbnail": "https://img/1.jpg"}

        class FakeClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

        class FakeFactory:
            def __init__(self, cfg):
                self.closed = False

            def get_client(self, provider):
                return FakeClient()

            def close_all(self):
                self.closed = True
                closed_factories.append(self)

        monkeypatch.setattr(video_assembler, "ClientFactory", FakeFactory)

        search_candidates("pexels", "dog")
        assert len(closed_factories) == 1 and closed_factories[0].closed, (
            "a fábrica criada internamente por search_candidates() deveria ter sido fechada"
        )

    def test_does_not_close_explicitly_passed_factory(self):
        """O oposto do teste acima: quando o chamador passa a própria
        `client_factory` (pra reaproveitar entre várias buscas), ela não
        deve ser fechada automaticamente — isso quebraria o reuso."""
        class FakeVideo:
            def to_dict(self):
                return {"id": "1", "title": "x", "thumbnail": "https://img/1.jpg"}

        class FakeClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

        class FakeFactory:
            def __init__(self):
                self.closed = False

            def get_client(self, provider):
                return FakeClient()

            def close_all(self):
                self.closed = True

        my_factory = FakeFactory()
        search_candidates("pexels", "dog", client_factory=my_factory)
        assert my_factory.closed is False

    def test_returns_thumbnail_and_label_from_video_search(self):
        class FakeVideo:
            def to_dict(self):
                return {"id": "123", "title": "Dog running", "thumbnail": "https://img/123.jpg"}

        class FakeClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo(), FakeVideo()]

        cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)
        factory._clients["pexels"] = FakeClient()

        candidates = search_candidates("pexels", "dog", client_factory=factory)
        assert len(candidates) == 2
        assert candidates[0]["thumbnail"] == "https://img/123.jpg"
        assert candidates[0]["label"] == "Dog running"

    def test_respects_max_results(self):
        class FakeVideo:
            def to_dict(self):
                return {"id": "1", "title": "x", "thumbnail": "https://img/1.jpg"}

        class FakeClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo() for _ in range(10)]

        cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)
        factory._clients["pexels"] = FakeClient()

        candidates = search_candidates("pexels", "dog", max_results=3, client_factory=factory)
        assert len(candidates) == 3

    def test_mixkit_uses_category_param(self):
        calls = []

        class FakeVideo:
            def to_dict(self):
                return {"id": "1", "title": "x", "thumbnail": "https://img/1.jpg"}

        class FakeClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                calls.append({"query": query, "category": category})
                return [FakeVideo()]

        cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)
        factory._clients["mixkit"] = FakeClient()

        search_candidates("mixkit", "animal-nature", client_factory=factory)
        assert calls[0]["category"] == "animal-nature"

    def test_search_failure_becomes_clear_video_assembly_error(self):
        class FakeFailingClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                raise RuntimeError("rede fora do ar")

        cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)
        factory._clients["pexels"] = FakeFailingClient()

        with pytest.raises(VideoAssemblyError, match="Busca falhou"):
            search_candidates("pexels", "dog", client_factory=factory)


class TestSearchCandidatesPhoto:
    def test_returns_thumbnail_and_description_from_photo_search(self):
        class FakePhoto:
            id = "p1"
            description = "Vintage camera on table"
            author = "Someone"
            url = "https://www.pexels.com/photo/vintage-camera-p1/"
            sizes = {"tiny": "https://img/tiny.jpg", "large": "https://img/large.jpg"}

        class FakePhotoClient:
            def search_photos_all(self, query=None, max_pages=1, **kw):
                return [FakePhoto()]

        cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)
        factory._clients["pexels_photos"] = FakePhotoClient()

        candidates = search_candidates("pexels", "vintage camera", media_type="image", client_factory=factory)
        assert candidates[0]["thumbnail"] == "https://img/tiny.jpg"
        assert candidates[0]["label"] == "Vintage camera on table"

    def test_unsupported_provider_raises_clear_error(self):
        cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)

        with pytest.raises(VideoAssemblyError, match="não suporta busca de fotos"):
            search_candidates("pixabay", "x", media_type="image", client_factory=factory)


class TestFetchSegmentPreviewLightweight:
    """A prévia RÁPIDA da timeline: busca sem baixar nada, usando a URL
    de thumbnail que o próprio provedor já entrega na busca — resolve o
    gargalo de "buscando prévias" demorar minutos (antes baixava o
    vídeo inteiro só pra tirar um frame)."""

    def test_returns_cdn_thumbnail_url_without_downloading_anything(self):
        from video_assembler import ClientFactory, fetch_segment_preview_lightweight
        from prompt_builder import VideoSegment

        class FakeVideo:
            def to_dict(self):
                return {
                    "id": "123", "title": "Dog running",
                    "thumbnail": "https://img.pexels.com/videos/123/tiny.jpg",
                    "url": "https://www.pexels.com/video/dog-running-123/",
                }

        class FakeClient:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

        cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)
        factory._clients["pexels"] = FakeClient()

        segment = VideoSegment(start=0.0, end=3.0, provider="pexels", query="dog")
        result = fetch_segment_preview_lightweight(segment, client_factory=factory)

        assert result["ok"] is True
        assert result["thumbnail_url"] == "https://img.pexels.com/videos/123/tiny.jpg"
        assert result["result_url"] == "https://www.pexels.com/video/dog-running-123/"

    def test_falls_back_to_generic_query_when_original_finds_nothing(self):
        from video_assembler import ClientFactory, fetch_segment_preview_lightweight
        from prompt_builder import VideoSegment

        class FakeVideo:
            def to_dict(self):
                return {"id": "1", "title": "x", "thumbnail": "https://img/1.jpg", "url": "https://x"}

        class FakeClientFallback:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [] if "muito especifico" in (query or "") else [FakeVideo()]

        cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)
        factory._clients["pexels"] = FakeClientFallback()

        segment = VideoSegment(start=0.0, end=3.0, provider="pexels", query="termo muito especifico")
        result = fetch_segment_preview_lightweight(segment, client_factory=factory)
        assert result["ok"] is True

    def test_returns_ok_false_with_error_when_no_query_works(self):
        from video_assembler import ClientFactory, fetch_segment_preview_lightweight
        from prompt_builder import VideoSegment

        class FakeClientAllFail:
            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return []

        cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)
        factory._clients["pexels"] = FakeClientAllFail()

        segment = VideoSegment(start=0.0, end=3.0, provider="pexels", query="x")
        result = fetch_segment_preview_lightweight(segment, client_factory=factory)
        assert result["ok"] is False
        assert result["error"] is not None
