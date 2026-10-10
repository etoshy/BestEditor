"""
wikipedia_api_client.py
========================

Cliente para buscar e baixar IMAGENS a partir da Wikipedia (para achar o
artigo certo) + Wikimedia Commons (para os metadados e o arquivo em si).
Segue o mesmo padrão dos outros clientes do toolkit (`pexels_api_client.py`,
`pixabay_api_client.py`): classe com `search_all` / `download_image` /
`download_many`, dataclass de resultado com `.to_dict()`, e uma CLI simples.

Diferente dos provedores de banco de imagem/vídeo (Pexels, Pixabay etc),
aqui o "provedor" é uma enciclopédia: serve para achar imagens de coisas
que **existem ou existiram de verdade** — pessoas, lugares, quadros/obras
de arte, objetos, eventos, espécies, prédios etc — e não fotos genéricas
de banco de imagem. Não precisa de chave de API (a API pública da
Wikipedia/Wikimedia é aberta).

Uso
----
    from wikipedia_api_client import WikipediaAPIClient

    client = WikipediaAPIClient()

    # Busca o artigo mais relevante para o termo e devolve as imagens dele
    imagens = client.search_all("Torre Eiffel", max_images=10)

    for img in imagens:
        print(img.arquivo, img.largura, "x", img.altura, img.licenca)

    client.download_image(imagens[0], output_dir="imagens")

    # Ou buscar em uma página já conhecida (sem passar pela busca):
    imagens2 = client.get_images_from_page("Mona Lisa")

Uso pela linha de comando
--------------------------
    python wikipedia_api_client.py search "Torre Eiffel" --max-images 10 --out resultado.json
    python wikipedia_api_client.py download "Torre Eiffel" --output-dir imagens --max-images 5

Observações importantes
------------------------
- Cada imagem carrega sua PRÓPRIA licença (`licenca`/`uso`) — vem do
  Wikimedia Commons e varia de arquivo para arquivo (domínio público,
  CC-BY, CC-BY-SA etc). Confira `licenca`/`uso`/`autor`/`fonte` antes de
  reaproveitar uma imagem e dê os créditos exigidos pela licença.
- Arquivos vetoriais e de áudio/vídeo (svg, ogg, ogv, webm) são ignorados
  por padrão — o foco aqui é fotografia/imagem raster.
- `rate limit`: a API pública da Wikimedia não exige chave, mas pede um
  `User-Agent` identificável e uso responsável (sem paralelismo agressivo).
  Este cliente já manda um `User-Agent` descritivo e um pequeno `delay`
  entre chamadas.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote

import requests

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# Extensões ignoradas por padrão na varredura de imagens de uma página
# (vetor / áudio / vídeo — não são "fotos").
_EXTENSOES_IGNORADAS = (".svg", ".ogg", ".ogv", ".webm")

_USER_AGENT = (
    "WikipediaImageToolkitClient/1.0 "
    "(uso em ferramenta de pesquisa de imagens de referência; "
    "https://www.mediawiki.org/wiki/API:Etiquette)"
)

_TAG_RE = re.compile(r"<[^>]+>")


class WikipediaAPIClientError(Exception):
    """Erro genérico do cliente (rede, parsing, página não encontrada etc.)."""


def _limpar_html(texto: Optional[str]) -> str:
    if not texto:
        return ""
    return _TAG_RE.sub("", texto).strip()


@dataclass
class WikipediaImage:
    """Uma imagem de uma página da Wikipedia, com metadados do Commons."""

    arquivo: str  # ex: "File:Eiffel Tower Vertical 1.jpg"
    url_original: str
    url_pagina: str
    mime: str = ""
    largura: int = 0
    altura: int = 0
    descricao: str = ""
    legenda: str = ""
    data: str = ""
    autor: str = ""
    fonte: str = ""
    localizacao: str = ""
    licenca: str = ""
    uso: str = ""
    categorias: str = ""
    pagina_origem: str = ""  # título do artigo da Wikipedia de onde veio
    thumb_url: str = ""  # versão redimensionada (iiurlwidth) — melhor pra preview/thumbnail
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    # -- Propriedades de compatibilidade --------------------------------- #
    # Espelham os nomes de atributo que `PexelsAPIPhoto` usa (id, sizes,
    # description, author, url) — assim o resto do site (o pipeline de
    # busca/prévia de FOTOS, que hoje só conhece o Pexels) consegue tratar
    # uma `WikipediaImage` do mesmo jeito que uma foto do Pexels, sem
    # precisar saber qual provedor devolveu o resultado. Ver
    # `search_photos_all` / `download_photo` mais abaixo, que existem pelo
    # mesmo motivo.

    @property
    def id(self) -> str:  # noqa: A003 - nome espelha PexelsAPIPhoto.id de propósito
        return self.arquivo

    @property
    def sizes(self) -> Dict[str, str]:
        sizes: Dict[str, str] = {}
        if self.thumb_url:
            sizes["thumb"] = self.thumb_url
            sizes["small"] = self.thumb_url
        if self.url_original:
            sizes["original"] = self.url_original
        return sizes

    @property
    def description(self) -> str:
        return self.descricao or self.legenda

    @property
    def author(self) -> str:
        return self.autor

    @property
    def url(self) -> str:
        return self.url_pagina

    def to_dict(self) -> Dict[str, Any]:
        return {
            "arquivo": self.arquivo,
            "url_original": self.url_original,
            "url_pagina": self.url_pagina,
            "mime": self.mime,
            "largura": self.largura,
            "altura": self.altura,
            "descricao": self.descricao,
            "legenda": self.legenda,
            "data": self.data,
            "autor": self.autor,
            "fonte": self.fonte,
            "localizacao": self.localizacao,
            "licenca": self.licenca,
            "uso": self.uso,
            "categorias": self.categorias,
            "pagina_origem": self.pagina_origem,
            "thumb_url": self.thumb_url,
        }


@dataclass
class WikipediaPage:
    titulo: str
    url: str
    texto: str
    pageid: int


class WikipediaAPIClient:
    def __init__(self, delay: float = 0.2, user_agent: str = _USER_AGENT):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    # ------------------------------------------------------------------ #
    # Requisição
    # ------------------------------------------------------------------ #

    def _get(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise WikipediaAPIClientError(f"Falha de rede em {url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise WikipediaAPIClientError(f"Resposta não é JSON válido de {url}: {exc}") from exc

    # ------------------------------------------------------------------ #
    # 1. Encontrar a página certa para um termo de busca
    # ------------------------------------------------------------------ #

    def find_page_title(self, termo: str) -> str:
        """Devolve o título do artigo mais relevante da Wikipedia para
        `termo` (qualquer coisa: pessoa, quadro, objeto, lugar, evento...).
        """
        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": termo,
            "srlimit": 5,
        }
        dados = self._get(WIKIPEDIA_API, params)
        resultados = dados.get("query", {}).get("search", [])
        if not resultados:
            raise WikipediaAPIClientError(f"Nenhuma página encontrada para {termo!r}.")
        return resultados[0]["title"]

    # ------------------------------------------------------------------ #
    # 2. Dados básicos da página
    # ------------------------------------------------------------------ #

    def get_page(self, titulo: str) -> WikipediaPage:
        params = {
            "action": "query",
            "format": "json",
            "prop": "extracts|info",
            "explaintext": 1,
            "inprop": "url",
            "titles": titulo,
        }
        dados = self._get(WIKIPEDIA_API, params)
        paginas = dados.get("query", {}).get("pages", {})
        pagina = next(iter(paginas.values()), {})
        if "missing" in pagina:
            raise WikipediaAPIClientError(f"Página {titulo!r} não existe.")
        return WikipediaPage(
            titulo=pagina.get("title", titulo),
            url=pagina.get("fullurl", ""),
            texto=pagina.get("extract", ""),
            pageid=pagina.get("pageid", 0),
        )

    # ------------------------------------------------------------------ #
    # 3. Listar os arquivos de imagem usados em uma página
    # ------------------------------------------------------------------ #

    def list_image_titles(
        self, titulo: str, ignorar_extensoes: tuple = _EXTENSOES_IGNORADAS
    ) -> List[str]:
        nomes: List[str] = []
        params: Dict[str, Any] = {
            "action": "query",
            "format": "json",
            "prop": "images",
            "titles": titulo,
            "imlimit": "max",
        }
        while True:
            dados = self._get(WIKIPEDIA_API, params)
            paginas = dados.get("query", {}).get("pages", {})
            for pagina in paginas.values():
                for imagem in pagina.get("images", []):
                    nome = imagem["title"]
                    if nome.lower().endswith(ignorar_extensoes):
                        continue
                    nomes.append(nome)
            if "continue" not in dados:
                break
            params.update(dados["continue"])
            time.sleep(self.delay)

        return list(dict.fromkeys(nomes))  # remove duplicados, preserva ordem

    # ------------------------------------------------------------------ #
    # 4. Metadados de um arquivo específico (via Commons)
    # ------------------------------------------------------------------ #

    def get_image_metadata(
        self, titulo_imagem: str, largura_max: int = 2000, pagina_origem: str = ""
    ) -> Optional[WikipediaImage]:
        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "titles": titulo_imagem,
            "iiprop": "url|size|mime|extmetadata",
            "iiextmetadatalanguage": "en",
            "iiurlwidth": largura_max,
        }
        dados = self._get(COMMONS_API, params)
        paginas = dados.get("query", {}).get("pages", {})
        pagina = next(iter(paginas.values()), {})
        infos = pagina.get("imageinfo", [])
        if not infos:
            return None

        info = infos[0]
        metadata = info.get("extmetadata", {})
        # Quando `iiurlwidth` é passado, a API devolve `thumburl` (versão
        # redimensionada) além de `url` (original, tamanho real) — usamos
        # a miniatura pra preview/thumbnail e o original pra download.
        thumb_url = info.get("thumburl", "")

        def campo(nome: str) -> str:
            valor = metadata.get(nome, {})
            if isinstance(valor, dict):
                valor = valor.get("value", "")
            return _limpar_html(valor)

        return WikipediaImage(
            arquivo=titulo_imagem,
            url_original=info.get("url", ""),
            url_pagina=(
                "https://commons.wikimedia.org/wiki/"
                + quote(titulo_imagem.replace(" ", "_"))
            ),
            mime=info.get("mime", ""),
            largura=info.get("width", 0) or 0,
            altura=info.get("height", 0) or 0,
            descricao=campo("ImageDescription"),
            legenda=campo("ObjectName"),
            data=campo("DateTimeOriginal"),
            autor=campo("Artist"),
            fonte=campo("Credit"),
            localizacao=campo("LocationCreated"),
            licenca=campo("LicenseShortName"),
            uso=campo("UsageTerms"),
            categorias=campo("Categories"),
            pagina_origem=pagina_origem,
            thumb_url=thumb_url,
            raw=info,
        )

    # ------------------------------------------------------------------ #
    # Fluxo completo: termo de busca -> lista de WikipediaImage
    # ------------------------------------------------------------------ #

    def get_images_from_page(
        self, titulo: str, max_images: Optional[int] = None
    ) -> List[WikipediaImage]:
        """Dado o título EXATO de um artigo, devolve os metadados de
        todas as imagens dele (ou até `max_images`, se informado).
        """
        arquivos = self.list_image_titles(titulo)
        if max_images:
            arquivos = arquivos[:max_images]

        imagens: List[WikipediaImage] = []
        for arquivo in arquivos:
            try:
                img = self.get_image_metadata(arquivo, pagina_origem=titulo)
                if img:
                    imagens.append(img)
            except WikipediaAPIClientError:
                continue  # melhor esforço: uma imagem com erro não derruba as outras
            time.sleep(self.delay)
        return imagens

    def search_all(
        self, termo: str, max_images: Optional[int] = None
    ) -> List[WikipediaImage]:
        """Busca o artigo mais relevante para `termo` (pessoa, quadro,
        objeto, lugar, evento, espécie etc.) e devolve os metadados de
        todas as imagens encontradas nele.
        """
        titulo = self.find_page_title(termo)
        return self.get_images_from_page(titulo, max_images=max_images)

    def search_photos_all(
        self, query: str, max_pages: int = 1, max_images: Optional[int] = None
    ) -> List[WikipediaImage]:
        """Mesmo nome/assinatura de `PexelsAPIClient.search_photos_all` —
        existe SÓ pra este cliente poder ser usado no lugar do cliente de
        fotos do Pexels em qualquer lugar do site que já espera essa
        interface (`media_type: "image"`), sem precisar de nenhuma
        checagem especial pra "qual provedor é esse". `max_pages` é
        ignorado (a Wikipedia não pagina por esse conceito, só tem UM
        artigo/UMA lista de imagens por termo); `max_images` limita
        quantas imagens do artigo são trazidas (padrão: todas).
        """
        return self.search_all(query, max_images=max_images)

    # ------------------------------------------------------------------ #
    # Download
    # ------------------------------------------------------------------ #

    def download_image(
        self,
        imagem: Union[WikipediaImage, Dict[str, Any]],
        output_dir: str = "imagens",
        filename: Optional[str] = None,
        overwrite: bool = False,
        chunk_size: int = 1024 * 1024,
    ) -> str:
        img = imagem if isinstance(imagem, WikipediaImage) else WikipediaImage(**imagem)
        if not img.url_original:
            raise WikipediaAPIClientError(f"Imagem sem URL para download: {img.arquivo}")

        os.makedirs(output_dir, exist_ok=True)
        if not filename:
            base = re.sub(r"^File:", "", img.arquivo)
            base = re.sub(r"[^\w.\-]+", "_", base).strip("_")
            filename = base or f"wikimedia_{abs(hash(img.url_original))}.jpg"
        filepath = os.path.join(output_dir, filename)

        if os.path.exists(filepath) and not overwrite:
            return filepath

        with self.session.get(img.url_original, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)

        time.sleep(self.delay)
        return filepath

    def download_photo(
        self,
        photo: Union[WikipediaImage, Dict[str, Any]],
        output_dir: str = "imagens",
        filename: Optional[str] = None,
        overwrite: bool = False,
    ) -> str:
        """Alias de `download_image` com o nome que `PexelsAPIClient` usa
        (`download_photo`) — mesmo motivo de `search_photos_all` acima:
        deixar este cliente intercambiável com o cliente de fotos do
        Pexels em qualquer lugar do site que já sabe baixar uma "foto".
        """
        return self.download_image(photo, output_dir=output_dir, filename=filename, overwrite=overwrite)

    def download_many(
        self,
        imagens: List[Union[WikipediaImage, Dict[str, Any]]],
        output_dir: str = "imagens",
        overwrite: bool = False,
        on_progress=None,
    ) -> List[str]:
        caminhos = []
        total = len(imagens)
        for i, img in enumerate(imagens, start=1):
            caminho = self.download_image(img, output_dir=output_dir, overwrite=overwrite)
            caminhos.append(caminho)
            if on_progress:
                on_progress(i, total, caminho)
        return caminhos


# --------------------------------------------------------------------------- #
# CLI simples
# --------------------------------------------------------------------------- #

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Cliente Wikipedia/Wikimedia Commons para buscar e baixar imagens de referência."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Busca o artigo mais relevante e salva um JSON com as imagens dele.")
    p_search.add_argument("termo", help='Termo de busca, ex: "Torre Eiffel", "Van Gogh", "Mona Lisa"')
    p_search.add_argument("--max-images", type=int, default=None)
    p_search.add_argument("--out", default=None)

    p_dl = sub.add_parser("download", help="Busca o artigo e baixa as imagens dele.")
    p_dl.add_argument("termo")
    p_dl.add_argument("--output-dir", default="imagens")
    p_dl.add_argument("--max-images", type=int, default=None)

    args = parser.parse_args()
    client = WikipediaAPIClient()

    if args.command == "search":
        imagens = client.search_all(args.termo, max_images=args.max_images)
        data = [img.to_dict() for img in imagens]
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"{len(data)} imagens salvas em {args.out}")
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))

    elif args.command == "download":
        imagens = client.search_all(args.termo, max_images=args.max_images)
        print(f"{len(imagens)} imagens encontradas. Baixando em {args.output_dir}...")
        caminhos = client.download_many(
            imagens,
            output_dir=args.output_dir,
            on_progress=lambda i, total, path: print(f"[{i}/{total}] {path}"),
        )
        print(f"Concluído: {len(caminhos)} arquivos baixados.")


if __name__ == "__main__":
    _cli()
