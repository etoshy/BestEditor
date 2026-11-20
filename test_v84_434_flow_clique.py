"""v84_434 — "Novo projeto" coberto por um aviso: o clique não trava, tenta de outros jeitos."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "toolkit"))
from googleflow import flow_direto as fd  # noqa: E402


class Loc:
    def __init__(self, falhas):
        self.falhas, self.cliques = falhas, []

    def click(self, timeout=0, force=False):
        self.cliques.append("forcado" if force else "normal")
        if len(self.cliques) <= self.falhas:
            raise Exception("Timeout 8000ms exceeded.\n  <div class=\"cdk-overlay-backdrop\"> intercepts pointer events")

    def evaluate(self, js):
        self.cliques.append("js")

    def scroll_into_view_if_needed(self, timeout=0):
        pass

    def count(self):
        return 0


class Page:
    keyboard = type("K", (), {"press": lambda self, k: None})()

    def locator(self, sel):
        return type("L", (), {"first": Loc(0)})()


def test_clique_forte(monkeypatch):
    monkeypatch.setattr(fd, "fechar_novidades", lambda *a, **k: False)
    assert fd.clicar_forte(Page(), Loc(0)) == "normal"
    assert fd.clicar_forte(Page(), Loc(1)) == "depois_de_fechar"
    assert fd.clicar_forte(Page(), Loc(2)) == "forcado"
    loc = Loc(9)
    assert fd.clicar_forte(Page(), loc) == "js" and loc.cliques == ["normal", "normal", "forcado", "js"]
