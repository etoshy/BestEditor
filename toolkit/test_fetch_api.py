"""
Teste offline de ChromeSession.fetch_api() — sem precisar de um Chrome de
verdade instalado (usa um driver falso pra simular o comportamento do
navegador).

Cobre o fix aplicado para Pexels/Magnific: em vez de `driver.get(url_da_api)`
(navegação de nível superior pra uma URL de API, que pode disparar bloqueio
anti-bot), o fetch_api() garante que a chamada seja feita via `fetch()` de
dentro de uma página já carregada do mesmo domínio.
"""
import browser_session


def _install_fake_driver(behavior):
    browser_session.webdriver.Chrome = lambda options=None: behavior
    return browser_session.ChromeSession(headless=True, download_dir="/tmp/_fetch_api_test")


class _RecordingDriver:
    def __init__(self, async_result):
        self.current_origin = None
        self.gets = []
        self.async_calls = []
        self._async_result = async_result

    def set_page_load_timeout(self, t):
        pass

    def get(self, url):
        self.gets.append(url)
        from urllib.parse import urlparse
        p = urlparse(url)
        self.current_origin = f"{p.scheme}://{p.netloc}"

    def execute_script(self, script, *args):
        if "window.location.origin" in script:
            return self.current_origin
        return ""

    def execute_async_script(self, script, *args):
        self.async_calls.append((script, args))
        return self._async_result

    def execute_cdp_cmd(self, *a, **k):
        pass


def test_navigates_to_domain_root_when_origin_differs():
    driver = _RecordingDriver({"status": 200, "text": '{"data": [1, 2, 3]}'})
    session = _install_fake_driver(driver)

    resp = session.fetch_api("https://www.pexels.com/en-us/api/v3/search/videos", params={"query": "dog", "page": 1})

    assert driver.gets == ["https://www.pexels.com/"], driver.gets
    assert resp.status_code == 200
    assert resp.json() == {"data": [1, 2, 3]}
    script, args = driver.async_calls[0]
    assert "fetch(url" in script
    assert "query=dog" in args[0] and "page=1" in args[0]
    print("OK: navega pra raiz do domínio quando a origem é diferente, e faz fetch() com os params corretos.")


def test_does_not_renavigate_when_already_on_domain():
    driver = _RecordingDriver({"status": 200, "text": "{}"})
    session = _install_fake_driver(driver)

    session.fetch_api("https://www.pexels.com/en-us/api/v3/search/videos", params={"query": "dog"})
    driver.gets.clear()
    session.fetch_api("https://www.pexels.com/en-us/api/v3/search/videos", params={"query": "cat"})

    assert driver.gets == [], driver.gets
    print("OK: não re-navega quando a aba já está no mesmo domínio da API.")


def test_propagates_error_status_without_raising():
    driver = _RecordingDriver({"status": 403, "text": "Forbidden"})
    driver.current_origin = "https://www.pexels.com"
    session = _install_fake_driver(driver)

    resp = session.fetch_api("https://www.pexels.com/en-us/api/v3/search/videos")
    assert resp.status_code == 403
    assert resp.text == "Forbidden"
    print("OK: status de erro (403) é devolvido normalmente, sem lançar exceção.")


class _CrashingDriver(_RecordingDriver):
    def execute_async_script(self, script, *args):
        raise RuntimeError("timeout do script")


def test_internal_exception_becomes_status_599():
    driver = _CrashingDriver({})
    driver.current_origin = "https://www.pexels.com"
    session = _install_fake_driver(driver)

    resp = session.fetch_api("https://www.pexels.com/en-us/api/v3/search/videos")
    assert resp.status_code == 599
    print("OK: exceção interna (ex: timeout do fetch) vira status 599 em vez de propagar.")


if __name__ == "__main__":
    test_navigates_to_domain_root_when_origin_differs()
    test_does_not_renavigate_when_already_on_domain()
    test_propagates_error_status_without_raising()
    test_internal_exception_becomes_status_599()
    print("\nTodos os testes de fetch_api passaram.")
