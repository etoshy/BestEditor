"""
pixabay_client.py
==================

Cliente não-oficial para o Pixabay, feito para:
  1) Buscar vídeos usando a mesma URL de busca pública que o site usa
     (https://pixabay.com/videos/search/<termo>/), com todos os filtros da
     busca avançada (orientação, efeitos, resolução, data, tipo de conteúdo);
  2) Rolar as páginas de resultado (parâmetro `pagi`) e devolver uma lista
     limpa e deduplicada de vídeos, extraída dos blocos JSON-LD
     (`<script type="application/ld+json">`) que o Pixabay já embute em
     cada card de resultado;
  3) Baixar um vídeo específico: como a listagem só expõe um preview
     (`..._tiny.mp4`), o cliente abre a página de detalhe do vídeo
     (`/videos/<slug>-<id>/`) e extrai o link real de download
     (`..._large.mp4`) do JSON-LD daquela página.

Não usa a API oficial do Pixabay (que exige chave e é mais limitada em
filtros); replica a navegação normal do site. Por isso, assim como o
cliente do Pexels, está sujeito a mudanças de layout e aos Termos de Uso
do Pixabay — use com moderação.

Uso rápido
----------
    from pixabay_client import PixabayClient

    client = PixabayClient()

    # 1) Buscar (com filtros) e pegar várias páginas
    videos = client.search_all(
        query="gato cachorro",
        orientation="horizontal",
        content_type="authentic",
        max_pages=3,
    )

    # 2) Baixar um vídeo específico (resolve o link real na página de detalhe)
    client.download_video(videos[0], output_dir="videos")

    # 3) Baixar direto por URL da página do vídeo
    client.download_video(
        "https://pixabay.com/videos/leopard-cub-small-wildcat-106286/",
        output_dir="videos",
    )

Também dá pra usar via linha de comando (veja `python pixabay_client.py --help`).
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

import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from browser_session import ChromeSession, BrowserResponse


# --------------------------------------------------------------------------- #
# Configuração básica
# --------------------------------------------------------------------------- #

SEARCH_BASE_URL = "https://pixabay.com/videos/search/"
VIDEO_PAGE_BASE = "https://pixabay.com/videos/"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
    "Referer": "https://pixabay.com/",
}

# Valores aceitos pelos filtros da busca avançada do Pixabay
VALID_ORIENTATIONS = {"vertical", "horizontal"}
VALID_DATE_FROM = {"1d", "3d", "1w", "6m", "1y"}
VALID_CONTENT_TYPE = {"authentic", "ai"}

# Regex para extrair TODOS os blocos JSON-LD de uma página (listagem ou detalhe)
_LDJSON_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL
)

# Regex para casar qualidade + duração + id do vídeo, na mesma ordem em que
# aparecem no card de resultado da busca (usa o link "Edit video" da Canva,
# que sempre carrega "external-id=video%3A<ID>", como âncora confiável).
_QUALITY_BLOCK_RE = re.compile(
    r'<span class="h4--eMLrj">(?P<quality>4K|HD|SD)</span>'
    r'<div class="text--ifigj default--ariTz">(?P<duration_text>\d+:\d+)</div>'
    r'.*?video%3A(?P<vid_id>\d+)',
    re.DOTALL,
)

# Regex para extrair id + slug de um path tipo "/videos/leopard-cub-small-wildcat-106286/"
_ID_SLUG_RE = re.compile(r"/videos/([\w-]+)/?$")

# Fallback quando a página não tem JSON-LD (ou o layout mudou): extrai
# direto da tag <video> renderizada pelo video.js — o mesmo princípio
# usado pro Mixkit. A tag inteira é extraída primeiro (pra não assumir
# uma ordem fixa de atributos), depois procura src=/poster= dentro dela.
_VIDEO_TAG_RE = re.compile(r"<video\b[^>]*>", re.IGNORECASE | re.DOTALL)
_ATTR_SRC_RE = re.compile(r'\bsrc="([^"]+)"')
_ATTR_POSTER_RE = re.compile(r'\bposter="([^"]+)"')
_TRAILING_ID_RE = re.compile(r"-(\d+)/?(?:[?#].*)?$")


class PixabayClientError(Exception):
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
    para erros transitórios: falhas de conexão/timeout, ou respostas com
    status 429/5xx. Erros "definitivos" (404, 403 etc.) são devolvidos
    imediatamente, sem retry.
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


# --------------------------------------------------------------------------- #
# Estrutura de dados de um vídeo
# --------------------------------------------------------------------------- #

@dataclass
class PixabayVideo:
    id: str
    slug: str
    title: str
    description: str
    url: str  # link da página do vídeo no pixabay.com
    duration: Optional[int] = None  # em segundos
    duration_text: Optional[str] = None  # ex: "0:06" (só vem da listagem)
    quality_label: Optional[str] = None  # "SD" | "HD" | "4K" (só vem da listagem)
    thumbnail: Optional[str] = None
    license: Optional[str] = None
    author: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    download_url: Optional[str] = None  # só preenchido após abrir a página de detalhe
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "duration": self.duration,
            "duration_text": self.duration_text,
            "quality_label": self.quality_label,
            "thumbnail": self.thumbnail,
            "license": self.license,
            "author": self.author,
            "width": self.width,
            "height": self.height,
            "download_url": self.download_url,
        }


# --------------------------------------------------------------------------- #
# Cliente principal
# --------------------------------------------------------------------------- #

class PixabayClient:
    def __init__(self, session: Optional[ChromeSession] = None, delay: float = 0.5):
        """
        session: permite reaproveitar uma sessão Chrome já configurada.
        delay:   pausa (em segundos) entre requisições, para não martelar o servidor.
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
        orientation: Optional[str] = None,
        animation: bool = False,
        slow_motion: bool = False,
        time_lapse: bool = False,
        resolution_hd: bool = False,
        resolution_4k: bool = False,
        date_from: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> List[PixabayVideo]:
        """Busca UMA página de resultados e devolve a lista de PixabayVideo
        já parseada. Todos os filtros são opcionais e replicam exatamente
        os parâmetros da busca avançada do site.
        """
        url = f"{SEARCH_BASE_URL}{quote(query, safe='')}/"
        params = self._build_params(
            page=page,
            orientation=orientation,
            animation=animation,
            slow_motion=slow_motion,
            time_lapse=time_lapse,
            resolution_hd=resolution_hd,
            resolution_4k=resolution_4k,
            date_from=date_from,
            content_type=content_type,
        )

        resp = _request_with_retry(self.session, "GET", url, params=params, timeout=20)
        if resp.status_code != 200:
            raise PixabayClientError(
                f"Falha na busca (status {resp.status_code}): {resp.text[:300]}"
            )

        return self._parse_search_page(resp.text)

    def search_all(
        self,
        query: str,
        max_pages: int = 10,
        stop_when_empty: bool = True,
        **filters: Any,
    ) -> List[PixabayVideo]:
        """Rola várias páginas de resultado (via o parâmetro `pagi`) e
        devolve uma lista única, deduplicada por ID.

        max_pages:       teto de segurança de páginas a percorrer.
        stop_when_empty: para assim que uma página vier vazia.
        filters:         mesmos filtros aceitos por `search()`.
        """
        all_videos: Dict[str, PixabayVideo] = {}

        for page in range(1, max_pages + 1):
            videos = self.search(query=query, page=page, **filters)

            if not videos and stop_when_empty:
                break

            for v in videos:
                all_videos[v.id] = v

            time.sleep(self.delay)

        return list(all_videos.values())

    # ------------------------------------------------------------------ #
    # Detalhe de um vídeo (a partir da URL da página)
    # ------------------------------------------------------------------ #

    def get_video_by_url(self, video_url: str) -> PixabayVideo:
        """Abre a página de um vídeo específico e resolve o link real de
        download. Tenta, em ordem:

        1. O bloco JSON-LD do tipo VideoObject (quando existe, é a fonte
           mais rica — já vem com autor, dimensões, licença prontos).
        2. Se não tiver JSON-LD (ou o layout mudou), extrai direto da
           tag <video> que o video.js renderiza na página — pede pro
           navegador esperar essa tag ter o atributo `src` preenchido
           antes de capturar o HTML, já que o player só define isso
           depois de conectar via JavaScript (sem essa espera, o HTML
           capturado vem com a tag vazia, mesmo que ela exista).
        """
        resp = _request_with_retry(
            self.session, "GET", video_url, timeout=20,
            wait_for_selector="video", wait_for_attr="src", wait_timeout=8,
        )
        if resp.status_code != 200:
            raise PixabayClientError(
                f"Falha ao abrir a página do vídeo (status {resp.status_code}): {video_url}"
            )

        video_objects = self._extract_video_objects(resp.text)
        if video_objects:
            # Na página de detalhe normalmente só existe UM VideoObject: o do
            # próprio vídeo. Pegamos o primeiro que tiver um contentUrl "grande"
            # (não terminando em _tiny.mp4), com fallback pro primeiro item.
            data = next(
                (v for v in video_objects if not v.get("contentUrl", "").endswith("_tiny.mp4")),
                video_objects[0],
            )
            video = self._parse_video_object(data, fallback_url=video_url)
            video.download_url = data.get("contentUrl")
            return video

        # sem JSON-LD -- cai pro fallback: extrai direto da tag <video>
        # renderizada (video.js) que o navegador acabou de esperar ficar pronta.
        video_tag_match = _VIDEO_TAG_RE.search(resp.text)
        if not video_tag_match:
            raise PixabayClientError(
                "Não encontrei nem um bloco JSON-LD nem uma tag <video> na página: "
                f"{video_url} (o layout do site pode ter mudado)."
            )
        video_tag = video_tag_match.group(0)

        src_match = _ATTR_SRC_RE.search(video_tag)
        if not src_match:
            raise PixabayClientError(
                f"Encontrei uma tag <video> mas sem atributo 'src' preenchido em: {video_url} "
                "(o player pode não ter terminado de carregar)."
            )
        download_url = src_match.group(1)

        poster_match = _ATTR_POSTER_RE.search(video_tag)
        thumbnail = poster_match.group(1) if poster_match else None

        id_slug_match = _ID_SLUG_RE.search(video_url.rstrip("/"))
        slug = id_slug_match.group(1) if id_slug_match else "video"
        id_match = _TRAILING_ID_RE.search(video_url.rstrip("/"))
        video_id = id_match.group(1) if id_match else slug

        return PixabayVideo(
            id=video_id, slug=slug, title=slug.replace("-", " "), description="",
            url=video_url, thumbnail=thumbnail, download_url=download_url,
        )

    def get_video_by_id(self, video_id: Union[str, int], slug: str = "video") -> PixabayVideo:
        """Monta a URL padrão /videos/<slug>-<id>/ e delega para get_video_by_url.

        Se você só tem o ID (sem slug), tenta com um slug genérico — igual
        ao Pexels, o Pixabay costuma aceitar qualquer texto de slug desde
        que o ID no final esteja certo, mas isso não é garantido; se falhar,
        use a URL completa retornada pela busca.
        """
        url = f"{VIDEO_PAGE_BASE}{slug}-{video_id}/"
        return self.get_video_by_url(url)

    # ------------------------------------------------------------------ #
    # Download
    # ------------------------------------------------------------------ #

    def download_video(
        self,
        video: Union[PixabayVideo, str, Dict[str, Any]],
        output_dir: str = "videos",
        filename: Optional[str] = None,
        chunk_size: int = 1024 * 1024,
        overwrite: bool = False,
    ) -> str:
        """Baixa um vídeo para o disco.

        video: pode ser
            - um PixabayVideo (retornado por search_all / get_video_by_url)
            - uma URL da página do vídeo
            - um dict cru (ex: vindo de to_dict())
        filename: nome do arquivo final; se None, usa "<slug>-<id>.mp4"

        Se o objeto ainda não tiver `download_url` (por ter vindo só da
        listagem de busca), o cliente automaticamente visita a página do
        vídeo para pegar o link real antes de baixar.

        Retorna o caminho completo do arquivo salvo.
        """
        pv = self._resolve_video(video)

        if not pv.download_url:
            pv = self.get_video_by_url(pv.url)

        if not pv.download_url:
            raise PixabayClientError(f"Não encontrei link de download para {pv.url}")

        os.makedirs(output_dir, exist_ok=True)

        if not filename:
            filename = f"{pv.slug}-{pv.id}.mp4"
        filepath = os.path.join(output_dir, filename)

        if os.path.exists(filepath) and not overwrite:
            return filepath

        self.session.download(pv.download_url, filepath, timeout=120)

        time.sleep(self.delay)
        return filepath

    def download_many(
        self,
        videos: List[Union[PixabayVideo, str, Dict[str, Any]]],
        output_dir: str = "videos",
        overwrite: bool = False,
        on_progress=None,
    ) -> List[str]:
        """Baixa uma lista de vídeos em sequência. `on_progress(i, total, path)`
        é chamado (se fornecido) após cada download.
        """
        paths = []
        total = len(videos)
        for i, v in enumerate(videos, start=1):
            path = self.download_video(v, output_dir=output_dir, overwrite=overwrite)
            paths.append(path)
            if on_progress:
                on_progress(i, total, path)
        return paths

    # ------------------------------------------------------------------ #
    # Helpers internos
    # ------------------------------------------------------------------ #

    def _resolve_video(self, video: Union[PixabayVideo, str, Dict[str, Any]]) -> PixabayVideo:
        if isinstance(video, PixabayVideo):
            return video
        if isinstance(video, str):
            # Pode já ser a página do vídeo; nesse caso get_video_by_url
            # já preenche o download_url, então retorne direto.
            return self.get_video_by_url(video)
        if isinstance(video, dict):
            return PixabayVideo(
                id=str(video["id"]),
                slug=video.get("slug", "video"),
                title=video.get("title", ""),
                description=video.get("description", ""),
                url=video.get("url") or f"{VIDEO_PAGE_BASE}{video.get('slug','video')}-{video['id']}/",
                duration=video.get("duration"),
                duration_text=video.get("duration_text"),
                quality_label=video.get("quality_label"),
                thumbnail=video.get("thumbnail"),
                license=video.get("license"),
                author=video.get("author"),
                width=video.get("width"),
                height=video.get("height"),
                download_url=video.get("download_url"),
            )
        raise PixabayClientError(f"Tipo de vídeo não suportado: {type(video)}")

    @staticmethod
    def _build_params(**kwargs: Any) -> Dict[str, Any]:
        params: Dict[str, Any] = {}

        page = kwargs.get("page", 1)
        if page and page > 1:
            params["pagi"] = page
        elif page == 1:
            # Incluir pagi=1 não quebra nada e deixa explícito.
            params["pagi"] = 1

        orientation = kwargs.get("orientation")
        if orientation:
            if orientation not in VALID_ORIENTATIONS:
                raise PixabayClientError(
                    f"orientation inválido: {orientation!r} (use {VALID_ORIENTATIONS})"
                )
            params["orientation"] = orientation

        if kwargs.get("animation"):
            params["animation"] = "true"
        if kwargs.get("slow_motion"):
            params["slow_motion"] = "true"
        if kwargs.get("time_lapse"):
            params["time_lapse"] = "true"

        if kwargs.get("resolution_hd"):
            params["resolution_hd"] = 1
        if kwargs.get("resolution_4k"):
            params["resolution_4k"] = 1

        date_from = kwargs.get("date_from")
        if date_from:
            if date_from not in VALID_DATE_FROM:
                raise PixabayClientError(
                    f"date_from inválido: {date_from!r} (use {VALID_DATE_FROM})"
                )
            params["date"] = date_from

        content_type = kwargs.get("content_type")
        if content_type:
            if content_type not in VALID_CONTENT_TYPE:
                raise PixabayClientError(
                    f"content_type inválido: {content_type!r} (use {VALID_CONTENT_TYPE})"
                )
            params["content_type"] = content_type

        return params

    @staticmethod
    def _extract_video_objects(html: str) -> List[Dict[str, Any]]:
        """Extrai todos os blocos <script type="application/ld+json"> da
        página que sejam do tipo VideoObject.
        """
        objects: List[Dict[str, Any]] = []
        for match in _LDJSON_RE.finditer(html):
            raw = match.group(1)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("@type") == "VideoObject":
                objects.append(data)
        return objects

    @classmethod
    def _parse_search_page(cls, html: str) -> List[PixabayVideo]:
        video_objects = cls._extract_video_objects(html)

        # Mapa id -> (quality, duration_text), usando o link "Edit video"
        # da Canva (external-id=video%3A<ID>) como âncora.
        quality_map: Dict[str, Dict[str, str]] = {}
        for m in _QUALITY_BLOCK_RE.finditer(html):
            quality_map[m.group("vid_id")] = {
                "quality": m.group("quality"),
                "duration_text": m.group("duration_text"),
            }

        videos: List[PixabayVideo] = []
        for data in video_objects:
            video = cls._parse_video_object(data)
            if video is None:
                continue
            extra = quality_map.get(video.id)
            if extra:
                video.quality_label = extra["quality"]
                video.duration_text = extra["duration_text"]
            videos.append(video)

        return videos

    @classmethod
    def _parse_video_object(
        cls, data: Dict[str, Any], fallback_url: Optional[str] = None
    ) -> Optional[PixabayVideo]:
        """Converte um dict JSON-LD (@type: VideoObject) em PixabayVideo."""
        page_path = data.get("acquireLicensePage") or fallback_url or ""
        vid_id, slug = cls._parse_id_slug(page_path, fallback_url)
        if vid_id is None:
            return None

        url = f"{VIDEO_PAGE_BASE}{slug}-{vid_id}/"

        creator = data.get("creator") or {}
        author = creator.get("name") if isinstance(creator, dict) else None

        thumb = data.get("thumbnailUrl")
        if isinstance(thumb, dict):
            thumb = thumb.get("url")

        return PixabayVideo(
            id=vid_id,
            slug=slug,
            title=data.get("name", ""),
            description=data.get("description", ""),
            url=url,
            duration=cls._parse_duration(data.get("duration")),
            thumbnail=thumb,
            license=data.get("license"),
            author=author,
            width=int(data["width"]) if str(data.get("width", "")).isdigit() else None,
            height=int(data["height"]) if str(data.get("height", "")).isdigit() else None,
            raw=data,
        )

    @staticmethod
    def _parse_id_slug(page_path: str, fallback_url: Optional[str] = None):
        """Extrai (id, slug) de algo como '/videos/leopard-cub-small-wildcat-106286/'
        ou de uma URL completa equivalente. slug retornado NÃO inclui o id.
        """
        candidates = [page_path, fallback_url or ""]
        for candidate in candidates:
            if not candidate:
                continue
            match = _ID_SLUG_RE.search(candidate.rstrip("/"))
            if not match:
                continue
            full_slug = match.group(1)  # ex: "leopard-cub-small-wildcat-106286"
            if "-" not in full_slug:
                continue
            slug, _, maybe_id = full_slug.rpartition("-")
            if maybe_id.isdigit():
                return maybe_id, slug
        return None, None

    @staticmethod
    def _parse_duration(duration_str: Optional[str]) -> Optional[int]:
        """Converte 'PT0M40S' ou 'T0M6S' (variações vistas no site) em segundos."""
        if not duration_str:
            return None
        match = re.match(
            r"^P?T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?$", duration_str
        )
        if not match:
            return None
        h = int(match.group("h") or 0)
        m = int(match.group("m") or 0)
        s = int(match.group("s") or 0)
        return h * 3600 + m * 60 + s


# --------------------------------------------------------------------------- #
# CLI simples (opcional) — útil para testar rapidamente pelo terminal
# --------------------------------------------------------------------------- #

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Buscar e baixar vídeos do Pixabay (scraping HTML, sem chave)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- search ---
    p_search = sub.add_parser("search", help="Buscar vídeos e listar resultados (JSON).")
    p_search.add_argument("query", help='Termo de busca, ex: "gato cachorro"')
    p_search.add_argument("--pages", type=int, default=1, help="Quantidade de páginas a buscar.")
    p_search.add_argument("--orientation", choices=sorted(VALID_ORIENTATIONS))
    p_search.add_argument("--animation", action="store_true")
    p_search.add_argument("--slow-motion", action="store_true")
    p_search.add_argument("--time-lapse", action="store_true")
    p_search.add_argument("--resolution-hd", action="store_true")
    p_search.add_argument("--resolution-4k", action="store_true")
    p_search.add_argument("--date-from", choices=sorted(VALID_DATE_FROM))
    p_search.add_argument("--content-type", choices=sorted(VALID_CONTENT_TYPE))
    p_search.add_argument("--out", help="Salvar resultado em um arquivo .json")

    # --- download ---
    p_dl = sub.add_parser("download", help="Baixar um vídeo específico.")
    p_dl.add_argument("target", help="URL da página do vídeo.")
    p_dl.add_argument("--output-dir", default="videos")

    args = parser.parse_args()
    client = PixabayClient()

    if args.command == "search":
        filters = dict(
            orientation=args.orientation,
            animation=args.animation,
            slow_motion=args.slow_motion,
            time_lapse=args.time_lapse,
            resolution_hd=args.resolution_hd,
            resolution_4k=args.resolution_4k,
            date_from=args.date_from,
            content_type=args.content_type,
        )
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
        path = client.download_video(args.target, output_dir=args.output_dir)
        print(f"Baixado em: {path}")


if __name__ == "__main__":
    _cli()
