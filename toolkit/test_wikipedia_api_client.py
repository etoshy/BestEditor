"""
Teste offline de wikipedia_api_client.py: encontrar a página certa pra
um termo, listar/filtrar as imagens dela, montar os metadados de cada
uma a partir do Commons (extmetadata + thumburl), baixar por streaming,
e os aliases de compatibilidade (`search_photos_all`/`download_photo`)
que deixam este cliente intercambiável com o `PexelsAPIClient` no resto
do site. Nada aqui toca a rede de verdade — tudo via uma sessão HTTP
falsa, no mesmo espírito de `test_pexels_api_client.py`.
"""
import os
import shutil

import requests

from wikipedia_api_client import (
    WikipediaAPIClient,
    WikipediaAPIClientError,
    WikipediaImage,
)


class FakeResp:
    def __init__(self, status_code=200, json_data=None, content_chunks=None):
        self.status_code = status_code
        self._json = json_data
        self._chunks = content_chunks or []

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            # precisa ser um requests.RequestException de verdade -- é
            # a exceção que o `_get()` do cliente sabe capturar e
            # converter em WikipediaAPIClientError.
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1024 * 1024):
        for chunk in self._chunks:
            yield chunk

    # suporte a "with session.get(...) as resp:" (usado no download)
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    """Fila de respostas: cada chamada a `.get()` consome a próxima da
    lista, na ordem em que o código do cliente as dispara.
    """

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None, stream=False):
        self.calls.append({"url": url, "params": params, "stream": stream})
        if not self.respostas:
            raise AssertionError(f"FakeSession sem resposta programada pra chamada #{len(self.calls)} ({url})")
        return self.respostas.pop(0)


def _client_com_respostas(respostas, delay=0.0):
    client = WikipediaAPIClient(delay=delay)
    client.session = FakeSession(respostas)
    return client


# --------------------------------------------------------------------------- #
# find_page_title / get_page
# --------------------------------------------------------------------------- #

def test_find_page_title_devolve_primeiro_resultado():
    resp = FakeResp(json_data={"query": {"search": [{"title": "Torre Eiffel"}, {"title": "Outra coisa"}]}})
    client = _client_com_respostas([resp])
    assert client.find_page_title("torre eiffel") == "Torre Eiffel"


def test_find_page_title_sem_resultado_levanta_erro():
    resp = FakeResp(json_data={"query": {"search": []}})
    client = _client_com_respostas([resp])
    try:
        client.find_page_title("coisa-que-nao-existe-123456")
        assert False, "deveria ter levantado WikipediaAPIClientError"
    except WikipediaAPIClientError as exc:
        assert "Nenhuma página encontrada" in str(exc)


def test_get_page_retorna_dados_da_pagina():
    resp = FakeResp(json_data={"query": {"pages": {"123": {
        "title": "Torre Eiffel", "fullurl": "https://en.wikipedia.org/wiki/Eiffel_Tower",
        "extract": "A Torre Eiffel é...", "pageid": 123,
    }}}})
    client = _client_com_respostas([resp])
    pagina = client.get_page("Torre Eiffel")
    assert pagina.titulo == "Torre Eiffel"
    assert pagina.pageid == 123
    assert "Torre Eiffel" in pagina.texto


def test_get_page_inexistente_levanta_erro():
    resp = FakeResp(json_data={"query": {"pages": {"-1": {"title": "Xyzzy123", "missing": ""}}}})
    client = _client_com_respostas([resp])
    try:
        client.get_page("Xyzzy123")
        assert False, "deveria ter levantado WikipediaAPIClientError"
    except WikipediaAPIClientError:
        pass


# --------------------------------------------------------------------------- #
# list_image_titles
# --------------------------------------------------------------------------- #

def test_list_image_titles_filtra_extensoes_ignoradas_e_remove_duplicados():
    resp = FakeResp(json_data={"query": {"pages": {"1": {"images": [
        {"title": "File:Foo.jpg"},
        {"title": "File:Icon.svg"},         # ignorado (svg)
        {"title": "File:Sound.ogg"},        # ignorado (ogg)
        {"title": "File:Foo.jpg"},          # duplicado
        {"title": "File:Bar.PNG"},          # extensão maiúscula ainda é filtrada certo (não é uma ignorada)
    ]}}}})
    client = _client_com_respostas([resp])
    nomes = client.list_image_titles("Alguma Página")
    assert nomes == ["File:Foo.jpg", "File:Bar.PNG"]


def test_list_image_titles_pagina_com_continue():
    resp1 = FakeResp(json_data={
        "query": {"pages": {"1": {"images": [{"title": "File:A.jpg"}]}}},
        "continue": {"imcontinue": "1|2"},
    })
    resp2 = FakeResp(json_data={"query": {"pages": {"1": {"images": [{"title": "File:B.jpg"}]}}}})
    client = _client_com_respostas([resp1, resp2])
    nomes = client.list_image_titles("Alguma Página")
    assert nomes == ["File:A.jpg", "File:B.jpg"]
    # a segunda chamada precisa ter herdado o parâmetro de continuação
    assert client.session.calls[1]["params"].get("imcontinue") == "1|2"


# --------------------------------------------------------------------------- #
# get_image_metadata
# --------------------------------------------------------------------------- #

def _resp_metadata(**extmetadata_overrides):
    extmetadata = {
        "ImageDescription": {"value": "Uma <b>foto</b> de teste"},
        "ObjectName": {"value": "Legenda"},
        "Artist": {"value": "Fulano de Tal"},
        "LicenseShortName": {"value": "CC BY-SA 4.0"},
        "UsageTerms": {"value": "Creative Commons"},
        "Categories": {"value": "Fotos de teste"},
    }
    extmetadata.update(extmetadata_overrides)
    return FakeResp(json_data={"query": {"pages": {"1": {"imageinfo": [{
        "url": "https://upload.wikimedia.org/original.jpg",
        "thumburl": "https://upload.wikimedia.org/thumb/original.jpg",
        "mime": "image/jpeg", "width": 4000, "height": 3000,
        "extmetadata": extmetadata,
    }]}}}})


def test_get_image_metadata_parseia_campos_e_limpa_html():
    resp = _resp_metadata()
    client = _client_com_respostas([resp])
    img = client.get_image_metadata("File:Foo.jpg", pagina_origem="Torre Eiffel")
    assert img is not None
    assert img.arquivo == "File:Foo.jpg"
    assert img.url_original == "https://upload.wikimedia.org/original.jpg"
    assert img.thumb_url == "https://upload.wikimedia.org/thumb/original.jpg"
    assert img.largura == 4000 and img.altura == 3000
    assert img.descricao == "Uma foto de teste"  # <b> removido
    assert img.autor == "Fulano de Tal"
    assert img.licenca == "CC BY-SA 4.0"
    assert img.pagina_origem == "Torre Eiffel"
    assert img.url_pagina == "https://commons.wikimedia.org/wiki/File%3AFoo.jpg"


def test_get_image_metadata_sem_imageinfo_devolve_none():
    resp = FakeResp(json_data={"query": {"pages": {"1": {}}}})
    client = _client_com_respostas([resp])
    assert client.get_image_metadata("File:Sumiu.jpg") is None


# --------------------------------------------------------------------------- #
# Propriedades de compatibilidade (espelham PexelsAPIPhoto)
# --------------------------------------------------------------------------- #

def test_wikipedia_image_propriedades_de_compatibilidade():
    img = WikipediaImage(
        arquivo="File:Foo.jpg", url_original="https://x/original.jpg",
        url_pagina="https://commons.wikimedia.org/wiki/File:Foo.jpg",
        thumb_url="https://x/thumb.jpg", descricao="Descrição", autor="Fulano",
    )
    assert img.id == "File:Foo.jpg"
    assert img.description == "Descrição"
    assert img.author == "Fulano"
    assert img.url == "https://commons.wikimedia.org/wiki/File:Foo.jpg"
    assert img.sizes == {
        "thumb": "https://x/thumb.jpg", "small": "https://x/thumb.jpg",
        "original": "https://x/original.jpg",
    }


def test_wikipedia_image_description_cai_pra_legenda_sem_descricao():
    img = WikipediaImage(
        arquivo="File:Foo.jpg", url_original="", url_pagina="", legenda="Só legenda mesmo",
    )
    assert img.description == "Só legenda mesmo"


def test_wikipedia_image_sizes_vazio_sem_urls():
    img = WikipediaImage(arquivo="File:Foo.jpg", url_original="", url_pagina="")
    assert img.sizes == {}


# --------------------------------------------------------------------------- #
# search_all / get_images_from_page (fluxo completo, ainda offline)
# --------------------------------------------------------------------------- #

def test_search_all_encadeia_busca_listagem_e_metadados():
    resp_busca = FakeResp(json_data={"query": {"search": [{"title": "Mona Lisa"}]}})
    resp_imagens = FakeResp(json_data={"query": {"pages": {"1": {"images": [
        {"title": "File:MonaLisa.jpg"}, {"title": "File:Icon.svg"},
    ]}}}})
    resp_meta = _resp_metadata()
    client = _client_com_respostas([resp_busca, resp_imagens, resp_meta])

    imagens = client.search_all("mona lisa")
    assert len(imagens) == 1
    assert imagens[0].arquivo == "File:MonaLisa.jpg"
    assert imagens[0].pagina_origem == "Mona Lisa"


def test_get_images_from_page_respeita_max_images():
    resp_imagens = FakeResp(json_data={"query": {"pages": {"1": {"images": [
        {"title": "File:A.jpg"}, {"title": "File:B.jpg"}, {"title": "File:C.jpg"},
    ]}}}})
    meta_a = _resp_metadata()
    client = _client_com_respostas([resp_imagens, meta_a])
    imagens = client.get_images_from_page("Alguma Página", max_images=1)
    assert len(imagens) == 1
    # só UMA chamada de metadados deveria ter sido feita (a segunda e
    # terceira imagem nem chegam a ser consultadas)
    assert len(client.session.calls) == 2  # 1 de listagem + 1 de metadados


def test_get_images_from_page_uma_imagem_com_erro_nao_derruba_as_outras():
    resp_imagens = FakeResp(json_data={"query": {"pages": {"1": {"images": [
        {"title": "File:Quebrada.jpg"}, {"title": "File:Boa.jpg"},
    ]}}}})
    resp_erro = FakeResp(status_code=500, json_data=None)
    resp_boa = _resp_metadata()
    client = _client_com_respostas([resp_imagens, resp_erro, resp_boa], delay=0)
    imagens = client.get_images_from_page("Alguma Página")
    assert len(imagens) == 1
    assert imagens[0].arquivo == "File:Boa.jpg"


# --------------------------------------------------------------------------- #
# search_photos_all / download_photo (aliases de compatibilidade)
# --------------------------------------------------------------------------- #

def test_search_photos_all_e_um_alias_de_search_all():
    resp_busca = FakeResp(json_data={"query": {"search": [{"title": "Van Gogh"}]}})
    resp_imagens = FakeResp(json_data={"query": {"pages": {"1": {"images": [{"title": "File:VanGogh.jpg"}]}}}})
    resp_meta = _resp_metadata()
    client = _client_com_respostas([resp_busca, resp_imagens, resp_meta])
    fotos = client.search_photos_all(query="van gogh", max_pages=3)  # max_pages é ignorado, só não pode quebrar
    assert len(fotos) == 1
    assert isinstance(fotos[0], WikipediaImage)


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #

def test_download_image_grava_arquivo_em_streaming(tmp_path):
    img = WikipediaImage(
        arquivo="File:Foo Bar.jpg", url_original="https://x/original.jpg", url_pagina="",
    )
    resp_download = FakeResp(content_chunks=[b"parte1", b"parte2"])
    client = _client_com_respostas([resp_download])

    caminho = client.download_image(img, output_dir=str(tmp_path))
    assert os.path.exists(caminho)
    with open(caminho, "rb") as f:
        assert f.read() == b"parte1parte2"
    # nome de arquivo sanitizado (sem "File:", espaço virou "_")
    assert os.path.basename(caminho) == "Foo_Bar.jpg"


def test_download_image_sem_url_levanta_erro(tmp_path):
    img = WikipediaImage(arquivo="File:SemURL.jpg", url_original="", url_pagina="")
    client = _client_com_respostas([])
    try:
        client.download_image(img, output_dir=str(tmp_path))
        assert False, "deveria ter levantado WikipediaAPIClientError"
    except WikipediaAPIClientError:
        pass


def test_download_image_nao_baixa_de_novo_se_ja_existe(tmp_path):
    img = WikipediaImage(arquivo="File:Existe.jpg", url_original="https://x/original.jpg", url_pagina="")
    destino = tmp_path / "Existe.jpg"
    destino.write_bytes(b"ja tinha isso aqui")
    client = _client_com_respostas([])  # nenhuma resposta programada -> quebraria se tentasse baixar
    caminho = client.download_image(img, output_dir=str(tmp_path))
    assert caminho == str(destino)
    assert destino.read_bytes() == b"ja tinha isso aqui"


def test_download_photo_e_alias_de_download_image(tmp_path):
    img = WikipediaImage(arquivo="File:Alias.jpg", url_original="https://x/original.jpg", url_pagina="")
    resp_download = FakeResp(content_chunks=[b"conteudo"])
    client = _client_com_respostas([resp_download])
    caminho = client.download_photo(img, output_dir=str(tmp_path))
    assert os.path.exists(caminho)


def test_download_many_baixa_em_sequencia_e_chama_on_progress(tmp_path):
    imagens = [
        WikipediaImage(arquivo=f"File:Img{i}.jpg", url_original=f"https://x/{i}.jpg", url_pagina="")
        for i in range(3)
    ]
    respostas = [FakeResp(content_chunks=[b"x"]) for _ in imagens]
    client = _client_com_respostas(respostas)

    progresso = []
    caminhos = client.download_many(
        imagens, output_dir=str(tmp_path),
        on_progress=lambda i, total, path: progresso.append((i, total)),
    )
    assert len(caminhos) == 3
    assert progresso == [(1, 3), (2, 3), (3, 3)]
