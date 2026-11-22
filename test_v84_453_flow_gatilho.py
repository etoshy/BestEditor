import pytest

from toolkit.googleflow import flow_direto as fd

_LIGAR, _ESPERAR, _NOVIDADES = fd.ligar_agente, fd._esperar, fd.fechar_novidades


class _Loc:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel

    def count(self):
        return 1 if self.page.tem(self.sel) else 0

    def nth(self, k):
        return self

    def is_visible(self):
        return True


class _Page:
    def __init__(self, aparece_apos_reload=True):
        self.recarregou = False
        self.aparece = aparece_apos_reload
        self.keyboard = self
        self.mouse = self

    def tem(self, sel):
        return ("settings" in sel and self.recarregou and self.aparece) or (sel == "flow-prompt-box" and self.recarregou)

    def locator(self, sel):
        return _Loc(self, sel)

    def press(self, *a):
        pass

    def click(self, *a):
        pass

    def reload(self, **k):
        self.recarregou = True


@pytest.fixture
def _rapido(monkeypatch):
    monkeypatch.setattr(fd, "_esperar", lambda cond, t, passo_s=0.25: cond())
    monkeypatch.setattr(fd, "ligar_agente", lambda page, ligado: None)
    monkeypatch.setattr(fd, "fechar_novidades", lambda page, on_passo=None, esperar_s=0.0: False)


def test_recarrega_e_acha(_rapido):
    p = _Page()
    fd.desligar_agente(p)
    assert p.recarregou


def test_erro_se_nunca_aparece(_rapido):
    with pytest.raises(fd.FlowPassoErro):
        fd.desligar_agente(_Page(aparece_apos_reload=False))


def test_interruptor_novo_do_agente_html_real():
    """HTML real (nov/2026): o Agente é um interruptor; com ele ligado o "modelo · x1" fica [hidden]."""
    import os
    from playwright.sync_api import sync_playwright
    html = open(os.path.join(os.path.dirname(__file__), "testes_dados", "flow_caixa_agente_switch_2026-11.html"), encoding="utf-8").read()
    js = """<script>
    document.querySelector('flow-agent-mode-switch button').addEventListener('click', e => {
      const b = e.currentTarget, on = b.getAttribute('aria-pressed') !== 'true';
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      const g = document.querySelector('button.settings-trigger-button');
      if (on) g.setAttribute('hidden', ''); else { g.removeAttribute('hidden'); g.querySelector('span').textContent = 'Nano Banana · x1'; }
    });</script>"""
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1400, "height": 900})
        page.set_content("<html><body>" + html + js + "</body></html>")
        assert fd._primeiro(page, fd.S["gatilho"], 0.5) is None  # agente ligado: o "modelo · x1" está escondido
        fd.desligar_agente(page)  # antes: não achava o interruptor e dava erro
        assert page.get_attribute('flow-agent-mode-switch button', 'aria-pressed') == 'false'
        assert fd._primeiro(page, fd.S["gatilho"], 2) is not None
        b.close()
