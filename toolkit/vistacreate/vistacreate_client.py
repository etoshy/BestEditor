"""
vistacreate_client.py
=======================

Cliente não-oficial para o VistaCreate (create.vista.com), feito para:
  1) Buscar vídeos usando a página pública de busca
     (https://create.vista.com/pt/videos/<termo>/), com os filtros de
     ordenação, isolamento de fundo e presença de pessoas;
  2) Rolar as páginas de resultado e devolver uma lista limpa e
     deduplicada de vídeos (id, título, thumbnail, se é premium, link da
     página quando disponível);
  3) Baixar um vídeo específico. Diferente dos outros clientes deste
     toolkit, aqui **não é preciso visitar nenhuma página extra**: o
     link de download já pode ser montado a partir dos dados que a
     própria listagem expõe.

Importante sobre a qualidade
------------------------------
O link de download que este cliente monta usa o endpoint
`cdn.create.vista.com/api/media/small/<id>/<slug>` — o mesmo usado para
a thumbnail da listagem, só que sem o parâmetro `videoStaticPreview=true`
(que faz o servidor devolver uma imagem estática em vez do vídeo). Esse
endpoint **sempre serve o vídeo em ~480p** ("small"), tanto para itens
grátis quanto para os marcados como "premium" (que aparecem com o selo de
diamante na listagem, indicando que a versão completa/HD exige assinatura
do VistaCreate Pro). Não existe, neste cliente, uma forma de obter
resolução maior — isso está fora do escopo do que é publicamente
acessível sem autenticação.

Uso rápido
----------
    from vistacreate_client import VistaCreateClient

    client = VistaCreateClient()

    # 1) Buscar (com filtros) e pegar várias páginas
    videos = client.search_all(
        query="animal nature",
        sort="popular",
        people="exclude",
        max_pages=3,
    )

    # 2) Baixar o primeiro resultado (sempre ~480p, "small")
    client.download_video(videos[0], output_dir="videos")

Também dá pra usar via linha de comando (veja `python vistacreate_client.py --help`).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote

import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from browser_session import ChromeSession, BrowserResponse


# --------------------------------------------------------------------------- #
# Configuração básica
# --------------------------------------------------------------------------- #

SEARCH_BASE_URL = "https://create.vista.com/pt/videos/"
CDN_MEDIA_BASE = "https://cdn.create.vista.com/api/media"

# Tamanhos de mídia conhecidos do endpoint da CDN. Só "small" foi
# CONFIRMADO (é o que a listagem usa para a thumbnail/preview). "medium"
# e "large" são uma hipótese razoável (padrão comum em CDNs de banco de
# imagem/vídeo) mas NÃO foram confirmados — por isso o cliente tenta e
# faz fallback automático para "small" se não existirem.
STANDARD_MEDIA_SIZES = ["large", "medium", "small"]
CONFIRMED_MEDIA_SIZES = {"small"}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://create.vista.com/",
}

VALID_SORT = {"newest", "popular"}
VALID_ISOLATED = {"include", "exclude"}
VALID_PEOPLE = {"include", "exclude"}

# Marca cada item da grade de resultados (mesmo os "premium", sem link clicável).
_ITEM_START_RE = re.compile(r'<div class="controlButtonWrapper-2fYDN[^"]*"')
_HREF_RE = re.compile(r'<a href="(?P<href>/pt/unlimited/stock-videos/[^"]+)"')
_IMG_RE = re.compile(
    r'<img[^>]*?src="https://cdn\.create\.vista\.com/api/media/small/'
    r"(?P<id>\d+)/(?P<slug>[^\"?]+)\?videoStaticPreview=true&amp;token=(?P<token>[^\"]*)\""
    r'[^>]*?alt="(?P<alt>[^"]*)"',
    re.DOTALL,
)
_DESC_RE = re.compile(
    r'<p class="typography-subheading-s description-2kEqo[^"]*"[^>]*>(?P<desc>.*?)</p>',
    re.DOTALL,
)
_PREMIUM_MARK = "premiumLabelWrapper"


class VistaCreateClientError(Exception):
    """Erro genérico do cliente (rede, parsing, filtro inválido etc.)."""


class MediaSizeNotFoundError(VistaCreateClientError):
    """Nenhum tamanho de mídia testado respondeu com sucesso."""


_MEDIA_SIZE_RE = re.compile(r"(/api/media/)(small|medium|large)(/)")


def _request_with_retry(
    session: ChromeSession,
    method: str,
    url: str,
    max_retries: int = 3,
    backoff_factor: float = 0.5,
    retry_statuses: tuple = (429, 500, 502, 503, 504),
    **kwargs: Any,
) -> BrowserResponse:
    """Faz uma requisição HTTP com retry automático (backoff exponencial)
    para erros transitórios. Erros "definitivos" (404, 403 etc.) são
    devolvidos imediatamente, sem retry — importante aqui porque o
    retry de tamanho de mídia (small/medium/large) já espera 404 como
    resposta normal para tamanhos inexistentes.
    """
    last_exc: Optional[Exception] = None
    resp: Optional[BrowserResponse] = None

    for attempt in range(max_retries + 1):
        try:
            resp = session.request(method, url, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(backoff_factor * (2 ** attempt))
                continue
            raise

        if resp.status_code in retry_statuses and attempt < max_retries:
            time.sleep(backoff_factor * (2 ** attempt))
            continue
        return resp

    if last_exc:
        raise last_exc
    return resp  # type: ignore[return-value]


def _clean_text(text: str) -> str:
    """Remove tags residuais, decodifica entidades HTML e normaliza espaços."""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    # Remove o sufixo " - Filmagem, Vídeo" (ou variações) que às vezes vem no alt.
    text = re.sub(r"\s*-\s*Filmagem,\s*V[íi]deo\s*$", "", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def _slugify(query: str) -> str:
    """Converte um termo de busca livre no slug de URL usado pelo site
    (ex: "animal nature" -> "animal-nature").
    """
    slug = query.strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    return quote(slug, safe="-")


# --------------------------------------------------------------------------- #
# Estrutura de dados de um vídeo
# --------------------------------------------------------------------------- #

@dataclass
class VistaCreateVideo:
    id: str
    title: str
    url: Optional[str] = None  # None para itens premium sem link direto
    thumbnail: Optional[str] = None  # preview estático (com videoStaticPreview=true)
    download_url: Optional[str] = None  # URL de download em "small" (~480p, confirmado)
    premium: bool = False
    resolved_quality: Optional[str] = None  # preenchido após um download bem-sucedido
    author: str = ""  # preenchido só depois de visitar a página do vídeo (ver nota abaixo)
    tags: List[str] = field(default_factory=list)  # idem — o site não tem descrição em prosa, só tags
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "thumbnail": self.thumbnail,
            "download_url": self.download_url,
            "premium": self.premium,
            "resolved_quality": self.resolved_quality,
            "author": self.author,
            "tags": self.tags,
        }


# --------------------------------------------------------------------------- #
# Cliente principal
# --------------------------------------------------------------------------- #

class VistaCreateClient:
    def __init__(self, session: Optional[ChromeSession] = None, delay: float = 0.5):
        """
        session: permite reaproveitar uma sessão Chrome já configurada.
        delay:   pausa (em segundos) entre requisições.
        """
        self.session = session or ChromeSession(headers=DEFAULT_HEADERS)
        self.delay = delay

    # ------------------------------------------------------------------ #
    # Busca
    # ------------------------------------------------------------------ #

    def search(
        self,
        query: str,
        page: int = 1,
        sort: Optional[str] = None,
        isolated: Optional[str] = None,
        people: Optional[str] = None,
    ) -> List[VistaCreateVideo]:
        """Busca UMA página de resultados e devolve a lista de
        VistaCreateVideo já parseada. Todos os filtros são opcionais.
        """
        url = f"{SEARCH_BASE_URL}{_slugify(query)}/"
        params = self._build_params(page=page, sort=sort, isolated=isolated, people=people)

        resp = _request_with_retry(self.session, "GET", url, params=params, timeout=20)
        if resp.status_code != 200:
            raise VistaCreateClientError(
                f"Falha na busca (status {resp.status_code}): {resp.text[:300]}"
            )

        return self._parse_listing_page(resp.text)

    def search_all(
        self,
        query: str,
        max_pages: int = 10,
        stop_when_empty: bool = True,
        **filters: Any,
    ) -> List[VistaCreateVideo]:
        """Rola várias páginas de resultado e devolve uma lista única,
        deduplicada por ID.

        max_pages:       teto de segurança de páginas a percorrer.
        stop_when_empty: para assim que uma página vier vazia.
        filters:         mesmos filtros aceitos por `search()`.
        """
        all_videos: Dict[str, VistaCreateVideo] = {}

        for page in range(1, max_pages + 1):
            videos = self.search(query=query, page=page, **filters)

            if not videos and stop_when_empty:
                break

            for v in videos:
                all_videos[v.id] = v

            time.sleep(self.delay)

        return list(all_videos.values())

    # ------------------------------------------------------------------ #
    # Download
    # ------------------------------------------------------------------ #

    def download_video(
        self,
        video: Union[VistaCreateVideo, Dict[str, Any]],
        output_dir: str = "videos",
        filename: Optional[str] = None,
        quality: str = "small",
        chunk_size: int = 1024 * 1024,
        overwrite: bool = False,
    ) -> str:
        """Baixa um vídeo para o disco.

        quality:
            "small"  -> (padrão, CONFIRMADO) o único tamanho garantido
                        de existir, ~480p.
            "medium" / "large" -> EXPERIMENTAL, não confirmado. O cliente
                        tenta esse tamanho e cai automaticamente para os
                        próximos melhores disponíveis (na ordem
                        large -> medium -> small) se não existir.
            "best"   -> tenta large, depois medium, depois small.
            "worst"  -> tenta small, depois medium, depois large.

        Como só "small" é confirmado, o comportamento padrão nunca muda:
        passar `quality="best"` ou `quality="large"` é uma tentativa
        experimental de conseguir uma resolução maior, sem garantia.

        Retorna o caminho completo do arquivo salvo.
        """
        vv = self._resolve_video(video)

        if not vv.download_url:
            raise VistaCreateClientError(f"Vídeo {vv.id} não tem link de download.")

        if not vv.tags and vv.url:
            vv.author, vv.tags = self._fetch_author_and_tags(vv.url)

        candidates = self._build_media_size_candidates(vv.download_url, quality)

        os.makedirs(output_dir, exist_ok=True)
        if not filename:
            filename = f"{vv.id}.mp4"
        filepath = os.path.join(output_dir, filename)

        if os.path.exists(filepath) and not overwrite:
            return filepath

        last_error = None
        for url, size_label in candidates:
            try:
                self.session.download(url, filepath, timeout=120)
                vv.download_url = url
                vv.resolved_quality = size_label
                time.sleep(self.delay)
                return filepath
            except Exception as exc:
                last_error = f"{exc} em {url}"
                continue

        raise MediaSizeNotFoundError(
            f"Nenhum tamanho de mídia funcionou para o vídeo {vv.id}. "
            f"Tentativas: {[c[0] for c in candidates]}. Último erro: {last_error}"
        )

    def download_many(
        self,
        videos: List[Union[VistaCreateVideo, Dict[str, Any]]],
        output_dir: str = "videos",
        quality: str = "small",
        overwrite: bool = False,
        skip_errors: bool = True,
        on_progress=None,
    ) -> List[str]:
        """Baixa uma lista de vídeos em sequência. Por padrão, pula (com
        aviso) vídeos cuja nenhum tamanho de mídia respondeu, em vez de
        interromper o lote inteiro.
        """
        paths = []
        total = len(videos)
        for i, v in enumerate(videos, start=1):
            try:
                path = self.download_video(
                    v, output_dir=output_dir, quality=quality, overwrite=overwrite
                )
                paths.append(path)
                if on_progress:
                    on_progress(i, total, path)
            except MediaSizeNotFoundError as exc:
                if not skip_errors:
                    raise
                if on_progress:
                    on_progress(i, total, None)
                print(f"[aviso] pulado: {exc}")
        return paths

    # ------------------------------------------------------------------ #
    # Helpers internos
    # ------------------------------------------------------------------ #

    # ATENÇÃO: este regex de tags é uma tentativa BEST-EFFORT — extraído
    # da estrutura observada em páginas de outras seções do site
    # (links pra "/videos/<tag>/"), mas eu não consegui confirmar a marcação
    # exata da página de detalhe de um vídeo específico (só o texto
    # renderizado, sem o HTML bruto). Se não encontrar nada, devolve tags
    # vazias silenciosamente — não quebra o download. Se você notar que
    # isso nunca captura tags de verdade, me avisa com um trecho do HTML
    # real da página de um vídeo que eu ajusto o regex.
    _TAG_LINK_RE = re.compile(
        r'<a[^>]+href="https://create\.vista\.com/videos/([a-z0-9-]+)/?"[^>]*>([^<]{1,40})</a>',
        re.IGNORECASE,
    )
    _AUTHOR_RE = re.compile(r'>By\s+([A-Za-z0-9_.\- ]{2,60})<', re.IGNORECASE)

    def _fetch_author_and_tags(self, video_url: str, timeout: int = 20):
        """Busca autor e tags na página do vídeo (melhor esforço — ver
        nota no regex acima). O VistaCreate não expõe uma descrição em
        prosa em nenhum lugar do site; as tags são o mais próximo disso
        que conseguimos capturar. Nunca levanta exceção.
        """
        if not video_url:
            return "", []
        try:
            resp = _request_with_retry(self.session, "GET", video_url, timeout=timeout, max_retries=1)
            if resp.status_code != 200:
                return "", []
            author_match = self._AUTHOR_RE.search(resp.text)
            author = html.unescape(author_match.group(1)).strip() if author_match else ""
            tags = []
            seen = set()
            for _, text in self._TAG_LINK_RE.findall(resp.text):
                tag = html.unescape(text).strip()
                if tag and tag.lower() not in seen:
                    seen.add(tag.lower())
                    tags.append(tag)
            return author, tags
        except Exception:  # noqa: BLE001 - melhor esforço, nunca quebra o download
            return "", []

    def _resolve_video(self, video: Union[VistaCreateVideo, Dict[str, Any]]) -> VistaCreateVideo:
        if isinstance(video, VistaCreateVideo):
            return video
        if isinstance(video, dict):
            return VistaCreateVideo(
                id=str(video["id"]),
                title=video.get("title", ""),
                url=video.get("url"),
                thumbnail=video.get("thumbnail"),
                download_url=video.get("download_url"),
                premium=bool(video.get("premium", False)),
                author=video.get("author", ""),
                tags=list(video.get("tags", [])),
            )
        raise VistaCreateClientError(f"Tipo de vídeo não suportado: {type(video)}")

    @staticmethod
    def _build_params(**kwargs: Any) -> Dict[str, Any]:
        params: Dict[str, Any] = {}

        page = kwargs.get("page", 1)
        if page and page > 1:
            params["page"] = page

        sort = kwargs.get("sort")
        if sort:
            if sort not in VALID_SORT:
                raise VistaCreateClientError(f"sort inválido: {sort!r} (use {VALID_SORT})")
            params["sort"] = sort

        isolated = kwargs.get("isolated")
        if isolated:
            if isolated not in VALID_ISOLATED:
                raise VistaCreateClientError(
                    f"isolated inválido: {isolated!r} (use {VALID_ISOLATED})"
                )
            params["isolated"] = isolated

        people = kwargs.get("people")
        if people:
            if people not in VALID_PEOPLE:
                raise VistaCreateClientError(f"people inválido: {people!r} (use {VALID_PEOPLE})")
            params["people"] = people

        return params

    @staticmethod
    def _build_media_size_candidates(download_url: str, quality: str):
        """Devolve uma lista de tuplas (url, tamanho) em ordem de
        tentativa, a partir da URL de download conhecida (que usa
        "small"). "medium" e "large" são experimentais (ver docstring de
        download_video).
        """
        match = _MEDIA_SIZE_RE.search(download_url)
        if not match:
            # URL não segue o padrão esperado — só uma opção possível.
            return [(download_url, None)]

        if quality == "best":
            order = list(STANDARD_MEDIA_SIZES)
        elif quality == "worst":
            order = list(reversed(STANDARD_MEDIA_SIZES))
        elif quality in STANDARD_MEDIA_SIZES:
            order = [quality] + [s for s in STANDARD_MEDIA_SIZES if s != quality]
        else:
            raise VistaCreateClientError(
                f"quality inválida: {quality!r} (use 'small', 'medium', 'large', 'best' ou 'worst')"
            )

        seen = set()
        candidates = []
        for size in order:
            if size in seen:
                continue
            seen.add(size)
            new_url = _MEDIA_SIZE_RE.sub(rf"\g<1>{size}\g<3>", download_url)
            candidates.append((new_url, size))
        return candidates

    @classmethod
    def _parse_listing_page(cls, html_text: str) -> List[VistaCreateVideo]:
        matches = list(_ITEM_START_RE.finditer(html_text))
        videos: List[VistaCreateVideo] = []

        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(html_text)
            chunk = html_text[start:end]

            img_match = _IMG_RE.search(chunk)
            if not img_match:
                # Bloco sem imagem de vídeo reconhecível (ex: algum outro
                # tipo de card) — pula.
                continue

            vid_id = img_match.group("id")
            slug = img_match.group("slug")
            token = img_match.group("token")
            alt_title = _clean_text(img_match.group("alt"))

            desc_match = _DESC_RE.search(chunk)
            title = _clean_text(desc_match.group("desc")) if desc_match else alt_title

            href_match = _HREF_RE.search(chunk)
            url = f"https://create.vista.com{href_match.group('href')}" if href_match else None

            premium = _PREMIUM_MARK in chunk

            thumbnail = (
                f"{CDN_MEDIA_BASE}/small/{vid_id}/{slug}?videoStaticPreview=true&token={token}"
            )
            download_url = f"{CDN_MEDIA_BASE}/small/{vid_id}/{slug}?token={token}"

            videos.append(
                VistaCreateVideo(
                    id=vid_id,
                    title=title or alt_title,
                    url=url,
                    thumbnail=thumbnail,
                    download_url=download_url,
                    premium=premium,
                    raw={"chunk_preview": chunk[:200]},
                )
            )

        return videos


# --------------------------------------------------------------------------- #
# CLI simples (opcional) — útil para testar rapidamente pelo terminal
# --------------------------------------------------------------------------- #

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Buscar e baixar vídeos do VistaCreate (sem chave de API)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- search ---
    p_search = sub.add_parser("search", help="Buscar vídeos e listar resultados (JSON).")
    p_search.add_argument("query", help='Termo de busca, ex: "animal nature"')
    p_search.add_argument("--pages", type=int, default=1, help="Quantidade de páginas a buscar.")
    p_search.add_argument("--sort", choices=sorted(VALID_SORT))
    p_search.add_argument("--isolated", choices=sorted(VALID_ISOLATED))
    p_search.add_argument("--people", choices=sorted(VALID_PEOPLE))
    p_search.add_argument("--out", help="Salvar resultado em um arquivo .json")

    # --- download ---
    p_dl = sub.add_parser("download", help="Baixar um vídeo específico (por id+slug ou via busca).")
    p_dl.add_argument("query", help="Termo de busca para localizar o vídeo (necessário para achar o slug).")
    p_dl.add_argument("video_id", help="ID numérico do vídeo (visto no campo 'id' da busca).")
    p_dl.add_argument("--output-dir", default="videos")
    p_dl.add_argument(
        "--quality",
        default="small",
        choices=["small", "medium", "large", "best", "worst"],
        help='"small" é o único tamanho CONFIRMADO. "medium"/"large"/"best" são experimentais.',
    )

    args = parser.parse_args()
    client = VistaCreateClient()

    if args.command == "search":
        filters = dict(sort=args.sort, isolated=args.isolated, people=args.people)
        filters = {k: v for k, v in filters.items() if v}

        videos = client.search_all(query=args.query, max_pages=args.pages, **filters)
        result = [v.to_dict() for v in videos]

        print(f"{len(result)} vídeos encontrados.")
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"Salvo em {args.out}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "download":
        videos = client.search_all(query=args.query, max_pages=5)
        match = next((v for v in videos if v.id == str(args.video_id)), None)
        if not match:
            raise VistaCreateClientError(
                f"Não achei o vídeo id={args.video_id} buscando por {args.query!r}."
            )
        path = client.download_video(match, output_dir=args.output_dir, quality=args.quality)
        print(f"Baixado em: {path}")


if __name__ == "__main__":
    _cli()
