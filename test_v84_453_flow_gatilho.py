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


def test_painel_do_agente_fecha_html_real():
    """HTML real (nov/2026): janela larga abre o PAINEL do agente; o X dele perdeu a classe header-action."""
    import os
    from playwright.sync_api import sync_playwright
    html = open(os.path.join(os.path.dirname(__file__), "testes_dados", "flow_painel_agente_2026-11.html"), encoding="utf-8").read()
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1400, "height": 900})
        page.set_content(html)
        page.evaluate("""() => { const x = document.querySelector('flow-agent-panel button[aria-label="Fechar"]');
          x.addEventListener('click', () => document.querySelector('flow-agent-panel').remove()); }""")
        assert fd._primeiro(page, fd.S["painel_sessao"], 1) is not None
        fd.ligar_agente(page, False)  # antes: 'não achei o X ("Fechar") do painel do agente'
        assert page.locator("flow-agent-panel").count() == 0
        b.close()


def test_config_do_agente_dentro_do_painel_html_real():
    """HTML real (nov/2026): "Configurações do agente" aberta DENTRO do painel — só tem "Voltar", sem o X."""
    import os
    from playwright.sync_api import sync_playwright
    html = open(os.path.join(os.path.dirname(__file__), "testes_dados", "flow_painel_agente_config_2026-11.html"), encoding="utf-8").read()
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1400, "height": 900})
        page.set_content(html)
        page.evaluate("""() => {
          const painel = document.querySelector('flow-agent-panel');
          const conteudo = painel.querySelector('.agent-panel-content').innerHTML, esq = painel.querySelector('.header-left').innerHTML;
          const ligar = () => {
            document.querySelectorAll('flow-unified-settings-view button[role="radio"]').forEach(r => r.addEventListener('click', () => {
              document.querySelectorAll('flow-unified-settings-view button[role="radio"]').forEach(o => o.setAttribute('aria-checked', 'false'));
              r.setAttribute('aria-checked', 'true'); }));
            painel.querySelector('button[aria-label="Voltar"]').addEventListener('click', voltar); };
          const voltar = () => {
            painel.querySelector('.agent-panel-content').innerHTML = '<p>chat</p>';
            painel.querySelector('.header-left').innerHTML = '<h2>Sessão sem título</h2>';
            const dir = painel.querySelector('.header-right'); dir.innerHTML = '';
            const cfg = document.createElement('button'); cfg.setAttribute('aria-label', 'Configurações do agente'); cfg.textContent = 'settings_2';
            cfg.addEventListener('click', () => { painel.querySelector('.agent-panel-content').innerHTML = conteudo;
              painel.querySelector('.header-left').innerHTML = esq; dir.innerHTML = ''; ligar(); });
            const x = document.createElement('button'); x.setAttribute('aria-label', 'Fechar'); x.textContent = 'right_panel_close';
            x.addEventListener('click', () => painel.remove());
            dir.appendChild(cfg); dir.appendChild(x); };
          ligar(); }""")
        fd._configurar_agente(page, "config_agente", "16:9", "x1", "", "16:9", "x1", "")
        assert page.locator("flow-unified-settings-view").count() == 0  # marcou "Nunca" e voltou
        fd.ligar_agente(page, False)  # antes: 'não achei o X ("Fechar") do painel do agente'
        assert page.locator("flow-agent-panel").count() == 0
        b.close()


def test_com_recuperacao(monkeypatch):
    limpou, recarregou, depois = [], [], []
    monkeypatch.setattr(fd, "limpar_tela", lambda page, on_passo=None: limpou.append(1))
    monkeypatch.setattr(fd, "recarregar_projeto", lambda page, on_passo=None: recarregou.append(1))
    n = {"k": 0}

    def passo():
        n["k"] += 1
        if n["k"] < 3:
            raise fd.FlowPassoErro("x", "botão sumiu")
        return "ok"
    assert fd.com_recuperacao(object(), "x", passo, depois_de_recarregar=lambda: depois.append(1)) == "ok"
    assert (len(limpou), len(recarregou), len(depois)) == (1, 1, 1)
    n["k"] = 0  # sem recarregar: 2 tentativas só
    with pytest.raises(fd.FlowPassoErro):
        fd.com_recuperacao(object(), "x", passo, recarregar=False)

    def limite():
        raise fd.FlowLimite("x", "sem créditos")
    limpou.clear()
    with pytest.raises(fd.FlowLimite):
        fd.com_recuperacao(object(), "x", limite)
    assert not limpou  # limite/sem crédito não é imprevisto de tela: não fica tentando
