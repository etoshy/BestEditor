"""
Teste de wikipedia_api_client.py contra a WIKIPEDIA DE VERDADE — sem
mock nenhum. Todos os outros testes do projeto (test_wikipedia_api_client.py,
test_wikipedia_enrichment.py) usam uma sessão HTTP falsa de propósito,
pra rodar rápido e sem depender de rede — o objetivo AQUI é o oposto:
confirmar que o cliente realmente conversa direito com a API pública da
Wikipedia/Wikimedia Commons tal como ela é hoje.

Como rodar
----------
    pytest test_wikipedia_live.py -v -s

Precisa de internet de verdade. Cada teste checa a conectividade antes
de rodar e é PULADO (não falha) se a rede não estiver disponível — é
assim que esses testes se comportam automaticamente num ambiente
sandbox/CI sem acesso à internet, sem quebrar a suíte principal.
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))

from wikipedia_api_client import WikipediaAPIClient, WikipediaAPIClientError  # noqa: E402


def _tem_internet() -> bool:
    """Uma checagem rápida (timeout curto) só pra decidir se pula os
    testes -- não usa isso pra validar nada, só pra evitar minutos de
    timeout quando não há rede nenhuma disponível. Faz uma requisição
    HTTP de verdade (não só resolução de DNS): em alguns ambientes
    restritos (ex: sandboxes com proxy de saída) o DNS resolve
    normalmente mas a conexão HTTP em si é bloqueada -- só uma
    checagem de DNS diria (erradamente) que "tem internet".
    """
    try:
        import requests
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php", params={"action": "query", "format": "json"}, timeout=5,
        )
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _tem_internet(), reason="sem internet disponível neste ambiente")


@pytest.fixture
def client():
    return WikipediaAPIClient()


def test_find_page_title_acha_pagina_real(client):
    titulo = client.find_page_title("Albert Einstein")
    assert titulo == "Albert Einstein"


def test_find_page_title_termo_em_portugues(client):
    # a Wikipedia inglesa (WIKIPEDIA_API aponta pra en.wikipedia.org)
    # ainda acha o artigo em inglês mesmo buscando um termo em
    # português, já que "search" é full-text, não por idioma exato.
    titulo = client.find_page_title("Torre Eiffel")
    assert "Eiffel" in titulo


def test_find_page_title_termo_inexistente_da_erro_claro(client):
    with pytest.raises(WikipediaAPIClientError):
        client.find_page_title("asdkjfhaksjdhfkasjhdfkajshdfxyz123456789naoexiste")


def test_get_page_devolve_texto_de_verdade(client):
    pagina = client.get_page("Albert Einstein")
    assert pagina.titulo == "Albert Einstein"
    assert pagina.pageid > 0
    assert len(pagina.texto) > 500  # o artigo de verdade tem muito mais que isso
    assert "physicist" in pagina.texto.lower() or "físico" in pagina.texto.lower()
    assert pagina.url.startswith("https://en.wikipedia.org/wiki/")


def test_list_image_titles_acha_imagens_de_verdade(client):
    imagens = client.list_image_titles("Albert Einstein")
    assert len(imagens) > 0
    assert all(nome.startswith("File:") for nome in imagens)
    # nenhuma delas deveria ser svg/ogg/ogv/webm (filtradas por padrão)
    assert not any(nome.lower().endswith((".svg", ".ogg", ".ogv", ".webm")) for nome in imagens)


def test_get_image_metadata_estrutura_real_da_extmetadata(client):
    """O teste mais importante pra confirmar que o parsing bate com a
    API de verdade -- não só com o formato que a gente ACHA que ela usa.
    """
    imagens = client.list_image_titles("Albert Einstein")
    assert imagens, "sem imagens pra testar -- a página mudou muito?"

    encontrou_uma_com_licenca = False
    for nome_imagem in imagens[:5]:
        meta = client.get_image_metadata(nome_imagem)
        if meta is None:
            continue
        assert meta.arquivo == nome_imagem
        assert meta.url_original.startswith("https://upload.wikimedia.org/")
        assert meta.url_pagina.startswith("https://commons.wikimedia.org/wiki/")
        assert meta.largura > 0 and meta.altura > 0
        assert meta.mime  # tipo MIME real (image/jpeg, image/png...)
        # nenhum campo de texto deveria ter sobrado tag HTML (a limpeza
        # de _limpar_html precisa ter funcionado)
        for campo in (meta.descricao, meta.autor, meta.licenca, meta.uso):
            assert "<" not in campo and ">" not in campo
        if meta.licenca:
            encontrou_uma_com_licenca = True

    assert encontrou_uma_com_licenca, "nenhuma das 5 primeiras imagens tinha LicenseShortName preenchido"


def test_search_all_fluxo_completo_de_ponta_a_ponta(client):
    """O fluxo inteiro que o site usa de verdade: termo de busca ->
    imagens com metadados, prontas pra download."""
    imagens = client.search_all("Torre Eiffel", max_images=3)
    assert 1 <= len(imagens) <= 3
    for img in imagens:
        assert img.url_original
        assert img.pagina_origem  # veio preenchido com o título real da página


def test_download_image_baixa_arquivo_de_verdade(client, tmp_path):
    imagens = client.search_all("Albert Einstein", max_images=1)
    assert imagens, "sem imagem pra testar o download"
    caminho = client.download_image(imagens[0], output_dir=str(tmp_path))
    assert os.path.exists(caminho)
    assert os.path.getsize(caminho) > 1000  # uma foto de verdade não é um arquivo de poucos bytes


def test_search_photos_all_alias_funciona_com_api_real(client):
    """O alias usado pelo resto do site (`search_photos_all`) pra
    tratar a Wikipedia como mais um provedor de FOTO, igual ao Pexels.
    """
    fotos = client.search_photos_all(query="Mona Lisa", max_pages=1)
    assert len(fotos) > 0
    # confere as propriedades de compatibilidade (id/sizes/description/author/url)
    primeira = fotos[0]
    assert primeira.id == primeira.arquivo
    assert isinstance(primeira.sizes, dict)
    assert primeira.url == primeira.url_pagina


def test_entidade_real_via_wikipedia_enrichment(tmp_path):
    """Fecha o ciclo: o módulo de enriquecimento (usado pelo modo
    "fontes da Wikipedia" do pipeline principal) encontra e confirma
    uma entidade real, contra a API de verdade, sem mock nenhum."""
    import wikipedia_enrichment as we

    segments = [{"text": "Albert Einstein nasceu na Alemanha em 1879 e revolucionou a física."}]
    confirmadas = we.identificar_entidades_wikipedia(segments, max_candidatos=5, max_verificacoes=5)
    assert any(c["termo"] == "Albert Einstein" for c in confirmadas)
    einstein = next(c for c in confirmadas if c["termo"] == "Albert Einstein")
    assert einstein["titulo_pagina"] == "Albert Einstein"
