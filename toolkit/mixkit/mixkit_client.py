"""
mixkit_client.py
==================

Cliente não-oficial para o Mixkit (mixkit.co), feito para:
  1) Percorrer as páginas de "descoberta por categoria"
     (https://mixkit.co/free-stock-video/discover/<categoria>/), com os
     filtros de orientação, resolução, duração e ordenação disponíveis;
  2) Extrair a lista de vídeos de cada página (id, título, descrição,
     thumbnail, link da página e o preview em 360p que sempre aparece no
     HTML) — ignorando automaticamente o bloco de banner promocional da
     Envato Elements que aparece no meio da grade (ele não tem os
     atributos `data-algolia-analytics-object-id="video-..."` que
     identificam um vídeo de verdade, então nunca é capturado);
  3) Baixar um vídeo específico **resolvendo a qualidade real**: o HTML
     só expõe o preview em 360p (`.../videos/<id>/<id>-360.mp4`), mas o
     arquivo de verdade pode existir em 720/1080/2160 — ou não. Como isso
     varia vídeo a vídeo, o cliente tenta as variações em ordem de
     preferência e usa a primeira que responder com sucesso (retry
     automático), salvando o arquivo já na mesma requisição que confirmou
     a qualidade (sem baixar duas vezes).

Importante sobre o "termo de busca"
-------------------------------------
Diferente do Pexels/Pixabay/Magnific, o Mixkit (pelo menos na página que
foi usada de referência) não parece ter uma busca por palavra-chave livre
com esse endpoint — a navegação é por **categoria de descoberta**
(o "animal-nature" do exemplo é o slug da categoria, não uma palavra
pesquisada). Por isso os métodos daqui usam `category` em vez de `query`.
Se o Mixkit tiver um endpoint de busca livre separado, ele não foi
mapeado aqui.

Uso rápido
----------
    from mixkit_client import MixkitClient

    client = MixkitClient()

    # 1) Buscar (com filtros) e pegar várias páginas de uma categoria
    videos = client.search_all(
        category="animal-nature",
        orientation="horizontal",
        duration="10-20s",
        max_pages=3,
    )

    # 2) Baixar o primeiro resultado, tentando a melhor qualidade disponível
    client.download_video(videos[0], output_dir="videos")

Também dá pra usar via linha de comando (veja `python mixkit_client.py --help`).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from browser_session import ChromeSession, BrowserResponse


# --------------------------------------------------------------------------- #
# Configuração básica
# --------------------------------------------------------------------------- #

DISCOVER_BASE_URL = "https://mixkit.co/free-stock-video/discover/"
SITE_BASE = "https://mixkit.co"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
    "Referer": "https://mixkit.co/",
}

VALID_ORIENTATIONS = {"horizontal", "vertical"}
# Único valor confirmado no material de referência. Outros valores (ex:
# "1080p", "720p") podem funcionar no site mas não foram testados aqui.
KNOWN_RESOLUTIONS = {"4k"}
# Tokens de duração confirmados no material de referência.
KNOWN_DURATIONS = {"0-5s", "5-10s", "10-20s", "20s-"}
KNOWN_SORTS = {"newest"}

# As qualidades de arquivo que o Mixkit costuma servir para cada vídeo.
# Nem todo vídeo tem todas — por isso o retry.
STANDARD_QUALITIES = [2160, 1080, 720, 360]

_ITEM_ID_RE = re.compile(r'data-algolia-analytics-object-id="video-(\d+)"')
_TITLE_HREF_RE = re.compile(
    r'<a href="(?P<href>/free-stock-video/[^"]+)" class="item-grid-video-player__overlay-link">'
    r'(?P<title>.*?)</a>',
    re.DOTALL,
)
_DESCRIPTION_RE = re.compile(
    r'<p class="item-grid-card__description">(?P<desc>.*?)</p>', re.DOTALL
)
_THUMB_RE = re.compile(r'<img src="(?P<thumb>[^"]+)" class="item-grid-video-player__thumb"')
_PREVIEW_SRC_RE = re.compile(r'<video src="(?P<src>[^"]+)"')
_RES_SUFFIX_RE = re.compile(r"^(?P<prefix>.*-)(?P<res>\d+)\.mp4(?P<query>\?.*)?$")

# Página de DETALHE (não a listagem) — o layout é diferente: a tag
# <video> tem vários atributos ANTES de "src" (class, data-controller,
# poster, etc), então não dá pra assumir que src vem logo depois de
# "<video ", como acontece na listagem (_PREVIEW_SRC_RE acima).
_DETAIL_VIDEO_TAG_RE = re.compile(r"<video\b[^>]*>", re.IGNORECASE | re.DOTALL)
_ATTR_SRC_RE = re.compile(r'\bsrc="([^"]+)"')
_ATTR_POSTER_RE = re.compile(r'\bposter="([^"]+)"')
_TITLE_TAG_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
_TRAILING_ID_RE = re.compile(r"-(\d+)/?(?:[?#].*)?$")
_ASSET_ID_RE = re.compile(r"/videos/(\d+)/")


class MixkitClientError(Exception):
    """Erro genérico do cliente (rede, parsing, filtro inválido etc.)."""


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
    devolvidos imediatamente, sem retry — importante aqui especialmente
    porque o teste de qualidade do Mixkit já espera 404 como resposta
    normal para variações de resolução inexistentes.
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


class QualityNotFoundError(MixkitClientError):
    """Nenhuma variação de qualidade testada respondeu com sucesso."""


def _clean_text(text: str) -> str:
    """Remove tags residuais/espaços múltiplos de um trecho de texto simples."""
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())


# --------------------------------------------------------------------------- #
# Estrutura de dados de um vídeo
# --------------------------------------------------------------------------- #

@dataclass
class MixkitVideo:
    id: str
    title: str
    description: str
    url: str  # link da página do vídeo no mixkit.co
    thumbnail: Optional[str] = None
    preview_url: Optional[str] = None  # o "-360.mp4" que sempre vem na listagem
    has_4k_badge: bool = False  # indício visual na listagem, não garantia
    download_url: Optional[str] = None  # preenchido após resolver a qualidade
    resolved_quality: Optional[int] = None  # em pixels de altura (360/720/1080/2160)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "thumbnail": self.thumbnail,
            "preview_url": self.preview_url,
            "has_4k_badge": self.has_4k_badge,
            "download_url": self.download_url,
            "resolved_quality": self.resolved_quality,
        }


# --------------------------------------------------------------------------- #
# Cliente principal
# --------------------------------------------------------------------------- #

class MixkitClient:
    def __init__(self, session: Optional[ChromeSession] = None, delay: float = 0.5):
        """
        session: permite reaproveitar uma sessão Chrome já configurada.
        delay:   pausa (em segundos) entre requisições de busca.
        """
        self.session = session or ChromeSession(headers=DEFAULT_HEADERS)
        self.delay = delay

    # ------------------------------------------------------------------ #
    # Busca
    # ------------------------------------------------------------------ #

    def search(
        self,
        category: str,
        page: int = 1,
        orientation: Optional[str] = None,
        resolution: Optional[str] = None,
        duration: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> List[MixkitVideo]:
        """Busca UMA página de resultados de uma categoria e devolve a
        lista de MixkitVideo já parseada. Todos os filtros são opcionais.
        """
        url = f"{DISCOVER_BASE_URL}{category}/"
        params = self._build_params(
            page=page,
            orientation=orientation,
            resolution=resolution,
            duration=duration,
            sort=sort,
        )

        resp = _request_with_retry(self.session, "GET", url, params=params, timeout=20)
        if resp.status_code != 200:
            raise MixkitClientError(
                f"Falha na busca (status {resp.status_code}): {resp.text[:300]}"
            )

        return self._parse_listing_page(resp.text)

    def search_all(
        self,
        category: str,
        max_pages: int = 10,
        stop_when_empty: bool = True,
        **filters: Any,
    ) -> List[MixkitVideo]:
        """Rola várias páginas de uma categoria e devolve uma lista única,
        deduplicada por ID.

        max_pages:       teto de segurança de páginas a percorrer.
        stop_when_empty: para assim que uma página vier vazia.
        filters:         mesmos filtros aceitos por `search()`.
        """
        all_videos: Dict[str, MixkitVideo] = {}

        for page in range(1, max_pages + 1):
            videos = self.search(category=category, page=page, **filters)

            if not videos and stop_when_empty:
                break

            for v in videos:
                all_videos[v.id] = v

            time.sleep(self.delay)

        return list(all_videos.values())

    # ------------------------------------------------------------------ #
    # Detalhe de um vídeo (melhor esforço — ver observação no README)
    # ------------------------------------------------------------------ #

    def get_video_by_url(self, video_url: str) -> MixkitVideo:
        """Resolve um vídeo a partir do link da PÁGINA DE DETALHE (ex:
        "https://mixkit.co/free-stock-video/lizard-over-a-trunk-at-nature-closeup-1473/").

        Diferente da listagem (busca), a página de detalhe tem a tag
        `<video>` com vários atributos antes de `src` (class,
        data-controller, poster, etc) — então a regex extrai a tag
        `<video ...>` inteira primeiro, e procura `src=`/`poster=`
        dentro dela, em qualquer ordem, em vez de assumir uma ordem fixa
        de atributos.
        """
        resp = _request_with_retry(
            self.session, "GET", video_url, timeout=20,
            wait_for_selector="video", wait_for_attr="src", wait_timeout=10,
        )
        if resp.status_code != 200:
            raise MixkitClientError(
                f"Falha ao abrir a página do vídeo (status {resp.status_code}): {video_url}"
            )

        video_tag_match = _DETAIL_VIDEO_TAG_RE.search(resp.text)
        if not video_tag_match:
            raise MixkitClientError(
                f"Não encontrei nenhuma tag <video> na página de detalhe: {video_url} "
                "(o layout da página pode ter mudado)."
            )
        video_tag = video_tag_match.group(0)

        src_match = _ATTR_SRC_RE.search(video_tag)
        if not src_match:
            raise MixkitClientError(
                f"A tag <video> encontrada não tem atributo 'src' em: {video_url}"
            )
        preview_url = src_match.group(1)

        poster_match = _ATTR_POSTER_RE.search(video_tag)
        thumbnail = poster_match.group(1) if poster_match else None

        # ID: primeiro tenta o número no final da URL da página (padrão
        # "...-1473/"); se não achar, cai pro ID embutido na própria URL
        # do arquivo de vídeo (".../videos/1473/1473-720.mp4").
        id_match = _TRAILING_ID_RE.search(video_url.rstrip("/"))
        if id_match:
            video_id = id_match.group(1)
        else:
            asset_match = _ASSET_ID_RE.search(preview_url)
            video_id = asset_match.group(1) if asset_match else "desconhecido"

        title_match = _TITLE_TAG_RE.search(resp.text)
        title = title_match.group(1).strip() if title_match else video_id

        return MixkitVideo(
            id=video_id,
            title=title,
            description="",
            url=video_url,
            thumbnail=thumbnail,
            preview_url=preview_url,
        )

    # ------------------------------------------------------------------ #
    # Download (com retry de qualidade)
    # ------------------------------------------------------------------ #

    def download_video(
        self,
        video: Union[MixkitVideo, Dict[str, Any]],
        output_dir: str = "videos",
        filename: Optional[str] = None,
        quality: Union[str, int] = "best",
        chunk_size: int = 1024 * 1024,
        overwrite: bool = False,
    ) -> str:
        """Baixa um vídeo, testando as variações de qualidade disponíveis.

        quality:
            "best"  -> tenta 2160, depois 1080, 720, 360 (padrão)
            "worst" -> tenta 360, depois 720, 1080, 2160
            360 / 720 / 1080 / 2160 (int ou string) -> tenta essa primeiro,
                depois cai para as próximas melhores disponíveis

        Se o link do vídeo não seguir o padrão "<algo>-<numero>.mp4" (alguns
        vídeos mais novos usam um nome de arquivo tipo hash, sem sufixo de
        resolução), o cliente baixa direto o único link que existe, sem
        tentar variações.

        Retorna o caminho completo do arquivo salvo.
        """
        mv = self._resolve_video(video)
        if not mv.preview_url:
            raise MixkitClientError(f"Vídeo {mv.id} não tem nenhum link de preview.")

        candidates = self._build_quality_candidates(mv.preview_url, quality)

        os.makedirs(output_dir, exist_ok=True)
        if not filename:
            filename = f"{mv.id}.mp4"
        filepath = os.path.join(output_dir, filename)

        if os.path.exists(filepath) and not overwrite:
            return filepath

        last_error = None
        for url, res_label in candidates:
            try:
                self.session.download(url, filepath, timeout=120)
                mv.download_url = url
                mv.resolved_quality = res_label
                time.sleep(self.delay)
                return filepath
            except Exception as exc:
                last_error = f"{exc} em {url}"
                continue

        raise QualityNotFoundError(
            f"Nenhuma variação de qualidade funcionou para o vídeo {mv.id}. "
            f"Tentativas: {[c[0] for c in candidates]}. Último erro: {last_error}"
        )

    def download_many(
        self,
        videos: List[Union[MixkitVideo, Dict[str, Any]]],
        output_dir: str = "videos",
        quality: Union[str, int] = "best",
        overwrite: bool = False,
        skip_errors: bool = True,
        on_progress=None,
    ) -> List[str]:
        """Baixa uma lista de vídeos em sequência. Por padrão, pula (com
        aviso) vídeos cuja nenhuma qualidade respondeu, em vez de
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
            except QualityNotFoundError as exc:
                if not skip_errors:
                    raise
                if on_progress:
                    on_progress(i, total, None)
                print(f"[aviso] pulado: {exc}")
        return paths

    # ------------------------------------------------------------------ #
    # Helpers internos
    # ------------------------------------------------------------------ #

    def _resolve_video(self, video: Union[MixkitVideo, Dict[str, Any]]) -> MixkitVideo:
        if isinstance(video, MixkitVideo):
            return video
        if isinstance(video, dict):
            return MixkitVideo(
                id=str(video["id"]),
                title=video.get("title", ""),
                description=video.get("description", ""),
                url=video.get("url", ""),
                thumbnail=video.get("thumbnail"),
                preview_url=video.get("preview_url"),
                has_4k_badge=bool(video.get("has_4k_badge", False)),
                download_url=video.get("download_url"),
                resolved_quality=video.get("resolved_quality"),
            )
        raise MixkitClientError(f"Tipo de vídeo não suportado: {type(video)}")

    @staticmethod
    def _build_params(**kwargs: Any) -> Dict[str, Any]:
        params: Dict[str, Any] = {}

        page = kwargs.get("page", 1)
        if page and page > 1:
            params["page"] = page

        orientation = kwargs.get("orientation")
        if orientation:
            if orientation not in VALID_ORIENTATIONS:
                raise MixkitClientError(
                    f"orientation inválida: {orientation!r} (use {VALID_ORIENTATIONS})"
                )
            params["orientation"] = orientation

        resolution = kwargs.get("resolution")
        if resolution:
            if resolution not in KNOWN_RESOLUTIONS:
                # Não bloqueia — só o valor "4k" foi confirmado, mas o site
                # pode aceitar outros. Deixa passar, avisando via docstring.
                pass
            params["resolution"] = resolution

        duration = kwargs.get("duration")
        if duration:
            if duration not in KNOWN_DURATIONS:
                pass  # idem: só os 4 tokens do material de referência são garantidos
            params["duration"] = duration

        sort = kwargs.get("sort")
        if sort:
            params["sort"] = sort

        return params

    @staticmethod
    def _build_quality_candidates(preview_url: str, quality: Union[str, int]):
        """Devolve uma lista de tuplas (url, rótulo_de_qualidade) em ordem
        de tentativa, a partir do preview em 360p.
        """
        match = _RES_SUFFIX_RE.match(preview_url)
        if not match:
            # Nome de arquivo tipo hash, sem sufixo de resolução conhecido —
            # só existe uma opção.
            return [(preview_url, None)]

        prefix = match.group("prefix")
        query = match.group("query") or ""

        if quality == "best":
            order = list(STANDARD_QUALITIES)
        elif quality == "worst":
            order = list(reversed(STANDARD_QUALITIES))
        else:
            requested = int(quality)
            order = [requested] + [q for q in STANDARD_QUALITIES if q != requested]

        seen = set()
        candidates = []
        for res in order:
            if res in seen:
                continue
            seen.add(res)
            candidates.append((f"{prefix}{res}.mp4{query}", res))
        return candidates

    @classmethod
    def _parse_listing_page(cls, html: str) -> List[MixkitVideo]:
        matches = list(_ITEM_ID_RE.finditer(html))
        videos: List[MixkitVideo] = []

        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(html)
            chunk = html[start:end]
            vid_id = m.group(1)

            title_match = _TITLE_HREF_RE.search(chunk)
            if not title_match:
                # Sem link/título reconhecível — não é um card de vídeo válido
                # (ex: algum bloco inesperado); pula.
                continue

            href = title_match.group("href")
            if "elements.envato.com" in href:
                # Proteção extra: nunca inclui itens que apontem para a Envato.
                continue

            title = _clean_text(title_match.group("title"))

            desc_match = _DESCRIPTION_RE.search(chunk)
            description = _clean_text(desc_match.group("desc")) if desc_match else ""

            thumb_match = _THUMB_RE.search(chunk)
            thumbnail = thumb_match.group("thumb") if thumb_match else None

            preview_match = _PREVIEW_SRC_RE.search(chunk)
            preview_url = preview_match.group("src") if preview_match else None

            has_4k_badge = "item-grid-video-player--4k" in chunk

            videos.append(
                MixkitVideo(
                    id=vid_id,
                    title=title,
                    description=description,
                    url=f"{SITE_BASE}{href}",
                    thumbnail=thumbnail,
                    preview_url=preview_url,
                    has_4k_badge=has_4k_badge,
                    raw={"chunk_preview": chunk[:200]},
                )
            )

        return videos


# --------------------------------------------------------------------------- #
# CLI simples (opcional) — útil para testar rapidamente pelo terminal
# --------------------------------------------------------------------------- #

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Buscar e baixar vídeos do Mixkit por categoria (sem chave de API)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- search ---
    p_search = sub.add_parser("search", help="Buscar vídeos de uma categoria e listar (JSON).")
    p_search.add_argument("category", help='Slug da categoria, ex: "animal-nature"')
    p_search.add_argument("--pages", type=int, default=1, help="Quantidade de páginas a buscar.")
    p_search.add_argument("--orientation", choices=sorted(VALID_ORIENTATIONS))
    p_search.add_argument("--resolution", help='Ex: "4k" (único valor confirmado)')
    p_search.add_argument("--duration", help='Ex: "0-5s", "5-10s", "10-20s", "20s-"')
    p_search.add_argument("--sort", help='Ex: "newest"')
    p_search.add_argument("--out", help="Salvar resultado em um arquivo .json")

    # --- download ---
    p_dl = sub.add_parser("download", help="Baixar um vídeo específico pela URL da página.")
    p_dl.add_argument("target", help="URL da página do vídeo.")
    p_dl.add_argument("--output-dir", default="videos")
    p_dl.add_argument("--quality", default="best", help='"best", "worst", ou 360/720/1080/2160')

    args = parser.parse_args()
    client = MixkitClient()

    if args.command == "search":
        filters = dict(
            orientation=args.orientation,
            resolution=args.resolution,
            duration=args.duration,
            sort=args.sort,
        )
        filters = {k: v for k, v in filters.items() if v}

        videos = client.search_all(category=args.category, max_pages=args.pages, **filters)
        result = [v.to_dict() for v in videos]

        print(f"{len(result)} vídeos encontrados.")
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"Salvo em {args.out}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "download":
        video = client.get_video_by_url(args.target)
        quality = args.quality
        if quality.isdigit():
            quality = int(quality)
        path = client.download_video(video, output_dir=args.output_dir, quality=quality)
        print(f"Baixado em: {path}")


if __name__ == "__main__":
    _cli()
