"""
Teste offline do enriquecimento de descrição/tags que complementa fontes
sem dados ricos de busca:

  - Pexels (via API oficial): a API não devolve descrição curada, então
    o cliente busca a meta-tag `description` da página pública do vídeo.
  - Magnific: o site não tem descrição autoral, mas a meta-tag da página
    tem uma frase gerada automaticamente ("Download this free video of
    <nome>...") — mais informação do que só o nome.
  - VistaCreate: não tem descrição em prosa em lugar nenhum; captura
    tags e autor da página do vídeo como substituto (melhor esforço, não
    verificado contra o HTML bruto real — ver aviso no próprio código).

Todos os três usam HTML real (Pexels e Magnific, confirmados via fetch
de página real) ou uma estrutura observada em outras seções do site
(VistaCreate, ver ressalva).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "magnific"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vistacreate"))

os.environ.setdefault("PEXELS_API_KEYS", "chave_de_teste_dummy")


def test_pexels_api_fetches_real_meta_description():
    import api_keys as _api_keys_mod
    from pexels_api_client import PexelsAPIClient

    # HTML real da página https://www.pexels.com/video/dogs-playing-3045714/
    real_html = (
        '<meta application-name="Pexels">'
        '<meta name="description" content="Two puppies playing joyfully on a sunny meadow, '
        'showcasing their playful nature.">'
        '<meta property="og:description" content="Download this video by Gram Film for free on Pexels">'
    )

    class FakeResp:
        status_code = 200
        text = real_html

    class FakeSession:
        def get(self, url, headers=None, timeout=10, **kw):
            return FakeResp()

    client = PexelsAPIClient.__new__(PexelsAPIClient)
    client.pool = _api_keys_mod.APIKeyPool(["chaveA"])
    client.delay = 0
    client.session = FakeSession()

    desc = client._fetch_description("https://www.pexels.com/video/dogs-playing-3045714/")
    assert desc == "Two puppies playing joyfully on a sunny meadow, showcasing their playful nature."
    print("OK: Pexels (API) extrai a meta description real da página pública do vídeo.")


def test_pexels_api_description_fetch_never_raises():
    import api_keys as _api_keys_mod
    from pexels_api_client import PexelsAPIClient

    class FakeSessionFail:
        def get(self, *a, **k):
            raise TimeoutError("timeout de rede")

    client = PexelsAPIClient.__new__(PexelsAPIClient)
    client.pool = _api_keys_mod.APIKeyPool(["chaveA"])
    client.delay = 0
    client.session = FakeSessionFail()

    assert client._fetch_description("https://x") == ""
    print("OK: Pexels (API) degrada para vazio sem quebrar quando a página não responde.")


def test_magnific_fetches_real_meta_description():
    from magnific_client import MagnificClient, BrowserResponse

    # HTML real da página de um vídeo grátis do Magnific
    real_html = (
        '<meta name="description" content="Download this free video of Excited shopaholic '
        'holding shopping bags and staring at shop window and explore millions of professional '
        'stock videos on Magnific.">'
    )

    class FakeSession:
        def request(self, method, url, timeout=20, **kw):
            return BrowserResponse(200, real_html, url)

    client = MagnificClient.__new__(MagnificClient)
    client.session = FakeSession()

    desc = client._fetch_description(
        "https://www.magnific.com/free-video/excited-shopaholic-holding-shopping-bags-staring-shop-window_472521"
    )
    assert desc == (
        "Download this free video of Excited shopaholic holding shopping bags and staring at "
        "shop window and explore millions of professional stock videos on Magnific."
    )
    print("OK: Magnific extrai a meta description real da página do vídeo (frase gerada pelo site).")


def test_magnific_description_fetch_never_raises():
    from magnific_client import MagnificClient

    class FakeSessionFail:
        def request(self, *a, **k):
            raise RuntimeError("timeout")

    client = MagnificClient.__new__(MagnificClient)
    client.session = FakeSessionFail()
    assert client._fetch_description("https://x") == ""
    print("OK: Magnific degrada para vazio sem quebrar quando a página não responde.")


def test_vistacreate_extracts_tags_and_author_best_effort():
    from vistacreate_client import VistaCreateClient, BrowserResponse

    # Estrutura observada em OUTRAS seções do site (links /videos/<tag>/);
    # não confirmado contra o HTML bruto real da página de detalhe — ver
    # aviso no código-fonte de vistacreate_client.py.
    fake_html = (
        "<div>By AntonLozovoy</div>"
        '<a href="https://create.vista.com/videos/computer/">Computer</a>'
        '<a href="https://create.vista.com/videos/business/">Business</a>'
        '<a href="https://create.vista.com/videos/man/">Man</a>'
    )

    class FakeSession:
        def request(self, method, url, timeout=20, **kw):
            return BrowserResponse(200, fake_html, url)

    client = VistaCreateClient.__new__(VistaCreateClient)
    client.session = FakeSession()

    author, tags = client._fetch_author_and_tags("https://create.vista.com/unlimited/stock-videos/252408056/x/")
    assert author == "AntonLozovoy"
    assert tags == ["Computer", "Business", "Man"]
    print("OK: VistaCreate extrai autor e tags com o padrão de link observado no site (melhor esforço).")


def test_vistacreate_degrades_gracefully_on_unexpected_layout():
    from vistacreate_client import VistaCreateClient, BrowserResponse

    class FakeSessionNoMatch:
        def request(self, method, url, timeout=20, **kw):
            return BrowserResponse(200, "<html>sem nada reconhecível aqui</html>", url)

    client = VistaCreateClient.__new__(VistaCreateClient)
    client.session = FakeSessionNoMatch()
    author, tags = client._fetch_author_and_tags("https://x")
    assert author == "" and tags == []
    print("OK: VistaCreate degrada para vazio se o layout real for diferente do esperado (não quebra).")


def test_vistacreate_description_fetch_never_raises():
    from vistacreate_client import VistaCreateClient

    class FakeSessionFail:
        def request(self, *a, **k):
            raise RuntimeError("timeout")

    client = VistaCreateClient.__new__(VistaCreateClient)
    client.session = FakeSessionFail()
    author, tags = client._fetch_author_and_tags("https://x")
    assert author == "" and tags == []
    print("OK: VistaCreate degrada para vazio sem quebrar quando a página não responde.")


if __name__ == "__main__":
    test_pexels_api_fetches_real_meta_description()
    test_pexels_api_description_fetch_never_raises()
    test_magnific_fetches_real_meta_description()
    test_magnific_description_fetch_never_raises()
    test_vistacreate_extracts_tags_and_author_best_effort()
    test_vistacreate_degrades_gracefully_on_unexpected_layout()
    test_vistacreate_description_fetch_never_raises()
    print("\nTodos os testes de enriquecimento de descrição passaram.")
