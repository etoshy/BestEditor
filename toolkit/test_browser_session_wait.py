"""
Teste automatizado de `ChromeSession._wait_for_element()` — resolve um
bug real relatado em produção: `driver.get(url)` + `page_source`
captura o HTML IMEDIATAMENTE após a navegação, sem esperar JavaScript
terminar de rodar. Em páginas que preenchem conteúdo dinamicamente
(como o player de vídeo do Mixkit, que só define o atributo `src` do
`<video>` depois de um controller JS conectar), isso fazia o scraping
nunca encontrar o vídeo — mesmo a tag existindo, só que vazia no
momento em que o HTML foi capturado.

Não dá pra testar contra um navegador Chrome de verdade neste ambiente
(sem chromedriver/rede) — esses testes usam o WebDriverWait REAL do
Selenium (que não precisa de navegador nenhum pra funcionar, só de um
objeto que aceite ser consultado repetidamente) com um "driver" falso
simulando os cenários reais.
"""
import time

import browser_session


def _bare_session():
    return browser_session.ChromeSession.__new__(browser_session.ChromeSession)


class TestWaitForElement:
    def test_returns_as_soon_as_attribute_becomes_populated(self):
        """O cenário real: o atributo 'src' começa vazio (JS ainda não
        rodou) e fica preenchido depois de um tempinho — a espera deve
        sair assim que isso acontece, não esperar o timeout inteiro."""
        session = _bare_session()
        call_count = {"n": 0}

        class FakeElement:
            def get_attribute(self, name):
                call_count["n"] += 1
                return "https://video.mp4" if call_count["n"] >= 3 else ""

        class FakeDriver:
            def find_element(self, by, selector):
                return FakeElement()

        session.driver = FakeDriver()

        t0 = time.time()
        session._wait_for_element("video", "src", wait_timeout=5)
        elapsed = time.time() - t0

        assert call_count["n"] >= 3
        assert elapsed < 5, "deveria ter saído assim que o atributo ficou preenchido, não esperado o timeout inteiro"

    def test_gives_up_gracefully_when_attribute_never_fills(self):
        """Se o atributo nunca for preenchido (layout mudou de verdade,
        ou a página não tem esse conteúdo), desiste depois do timeout —
        sem travar pra sempre nem levantar exceção (é melhor capturar o
        HTML do jeito que está do que quebrar a requisição inteira)."""
        session = _bare_session()

        class FakeElementNeverReady:
            def get_attribute(self, name):
                return ""

        class FakeDriver:
            def find_element(self, by, selector):
                return FakeElementNeverReady()

        session.driver = FakeDriver()

        t0 = time.time()
        session._wait_for_element("video", "src", wait_timeout=2)
        elapsed = time.time() - t0

        assert 1.5 < elapsed < 4, f"deveria esperar perto do timeout pedido (2s), esperou {elapsed:.2f}s"

    def test_gives_up_gracefully_when_element_never_exists(self):
        """Se o elemento nunca existir no DOM (find_element sempre
        falha), também desiste graciosamente, sem propagar a exceção."""
        session = _bare_session()

        class FakeDriver:
            def find_element(self, by, selector):
                raise Exception("no such element")

        session.driver = FakeDriver()

        # não deve levantar exceção nenhuma
        session._wait_for_element("video", "src", wait_timeout=1)

    def test_only_checks_presence_when_attr_not_given(self):
        """Sem `attr`, só espera o elemento EXISTIR (não checa nenhum
        atributo específico) — útil pra páginas onde a existência do
        elemento já é suficiente, sem precisar de um atributo preenchido."""
        session = _bare_session()
        find_calls = {"n": 0}

        class FakeElement:
            def get_attribute(self, name):
                raise AssertionError("não deveria checar atributo nenhum quando attr=None")

        class FakeDriver:
            def find_element(self, by, selector):
                find_calls["n"] += 1
                return FakeElement()

        session.driver = FakeDriver()
        session._wait_for_element("video", None, wait_timeout=2)
        assert find_calls["n"] >= 1
