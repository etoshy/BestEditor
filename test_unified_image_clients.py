import asyncio
import sys
import types
from pathlib import Path


def test_unified_package_is_bundled():
    root = Path(__file__).resolve().parent / "toolkit" / "unified_images" / "engines"
    assert all((root / f).exists() for f in (
        "bing_image_api.py", "brave_image_api.py", "yandex_image_api.py", "startpage_image_api.py"
    ))


def test_new_editor_path_uses_supplied_engine_and_limits_to_first_result(monkeypatch):
    import unified_browser_image_client as core

    class FakePage:
        url = "https://example/search"
        async def goto(self, *a, **k):
            self.url = a[0]
        async def wait_for_timeout(self, *_a):
            return None

    class Worker:
        def __init__(self): self.calls = 0
        def run(self, op, timeout=None):
            self.calls += 1
            async def go():
                mod = sys.modules["fake_unified_bing"]
                page = FakePage()
                return await op(page, object())
            return asyncio.run(go())

    async def scrape(*args, **kwargs):
        return ([
            {"title": "primeira", "original_url": "https://img/1.jpg"},
            {"title": "segunda", "original_url": "https://img/2.jpg"},
        ][:kwargs["limit"]], {})

    fake = types.ModuleType("fake_unified_bing")
    fake.DEFAULT_TIMEOUT_MS = 1000
    fake.build_qft = lambda **kwargs: ""
    fake.build_search_url = lambda q, **kwargs: f"https://example/search?q={q}"
    async def submit_new_search(*args, **kwargs): return "searchbox:enter"
    fake.submit_new_search = submit_new_search
    fake.scrape_current_page = scrape
    async def ensure(*args, **kwargs): return True
    fake.ensure_qft_in_url = ensure
    monkeypatch.setitem(sys.modules, "fake_unified_bing", fake)
    monkeypatch.setitem(core._ENGINE_IMPORTS, "bing", "fake_unified_bing")

    worker = Worker()
    client = core.UnifiedBrowserImageClient("bing", browser_worker=worker)
    photos = client.search_photos_all("gojo", max_images=1)
    assert worker.calls == 1
    assert [p.original_url for p in photos] == ["https://img/1.jpg"]


def test_download_can_try_thumbnail_of_same_first_result(monkeypatch, tmp_path):
    from unified_browser_image_client import UnifiedBrowserImageClient, UnifiedPhoto

    class Resp:
        def __init__(self, status_code, data=b"fake-image-bytes"):
            self.status_code = status_code
            self._chunks = [data]
            self.headers = {"content-type": "image/jpeg"}
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")
        def iter_content(self, chunk_size=1024 * 1024):
            yield from self._chunks

    client = UnifiedBrowserImageClient("bing", browser_worker=object())
    responses = iter([Resp(403), Resp(200)])
    monkeypatch.setattr(client.session, "get", lambda *a, **k: next(responses))
    photo = UnifiedPhoto(provider="bing", title="Gojo", original_url="https://img/original.jpg", thumbnail_url="https://img/thumb.jpg")
    path = client.download_photo(photo, output_dir=str(tmp_path))
    assert Path(path).exists()
