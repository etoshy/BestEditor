from __future__ import annotations

from unittest.mock import patch

import buscadores_enrichment


def test_enrichment_reuses_one_worker_per_provider_and_falls_back():
    created = []
    closed = []
    searches = []

    class FakeWorker:
        def __init__(self, **kwargs):
            created.append(self)
        def close(self):
            closed.append(self)

    class Img:
        def __init__(self, desc):
            self.description = desc

    class Client:
        def __init__(self, browser_worker=None, **kwargs):
            self.worker = browser_worker
            self.session = type("S", (), {"close": lambda self: None})()
        def search_photos_all(self, query, max_images=1):
            searches.append((id(self.worker), query))
            if self.worker is created[0]:
                return [] if query == "termo A" else [Img("bing ok")]
            return [Img("brave ok")]

    with patch.object(buscadores_enrichment, "PersistentBrowserSearchWorker", FakeWorker), \
         patch.object(buscadores_enrichment, "_CLIENTES_BUSCADORES", {"bing": ("x", "Client"), "brave": ("x", "Client")}), \
         patch("importlib.import_module") as import_module:
        import_module.return_value.Client = Client
        result = buscadores_enrichment.buscar_confirmados_nos_buscadores(["termo A", "termo B"], ["bing", "brave"])

    assert len(created) == 2
    assert len(closed) == 2
    assert [x["provider"] for x in result] == ["brave", "bing"]
    assert searches[0][0] != searches[1][0]
    assert searches[0][0] == searches[2][0]
