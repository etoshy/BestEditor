"""
pexels_client.py
=================

Cliente não-oficial para o Pexels, feito para:
  1) Buscar vídeos usando a API interna que o próprio site pexels.com usa
     (endpoint /en-us/api/v3/search/videos), com todos os filtros disponíveis
     na busca avançada (orientação, nº de pessoas, idade, duração, fps,
     resolução, data);
  2) Rolar todas as páginas de resultado e devolver uma lista limpa e
     deduplicada de vídeos (id, título, tags, thumbnail, links de download
     por qualidade, autor, duração, etc.);
  3) Baixar um vídeo específico (por ID, por URL da página do vídeo, ou a
     partir de um item já retornado pela busca), escolhendo a qualidade
     desejada.

Não usa nenhuma chave de API oficial: replica exatamente as chamadas que o
navegador faz quando você usa a busca do site, e faz o parsing do JSON
embutido (__NEXT_DATA__) quando é necessário abrir a página de um vídeo
específico.

Uso rápido
----------
    from pexels_client import PexelsClient

    client = PexelsClient()

    # 1) Buscar (com filtros) e pegar todas as páginas
    videos = client.search_all(
        query="dog and cats",
        orientation="landscape",
        people_count=2,
        max_pages=5,
    )

    # 2) Baixar o primeiro resultado na melhor qualidade
    client.download_video(videos[0], output_dir="videos")

    # 3) Baixar direto por URL da página do vídeo
    client.download_video(
        "https://www.pexels.com/video/breathtaking-view-of-massive-waterfall-38233454/",
        output_dir="videos",
        quality="hd",
    )

Também dá pra usar via linha de comando (veja `python pexels_client.py --help`).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from browser_session import ChromeSession, BrowserResponse


# --------------------------------------------------------------------------- #
# Configuração básica
# --------------------------------------------------------------------------- #

BASE_SEARCH_URL = "https://www.pexels.com/en-us/api/v3/search/videos"
SEARCH_PAGE_BASE = "https://www.pexels.com/search/videos/"
VIDEO_PAGE_BASE = "https://www.pexels.com/video/"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
    "Referer": "https://www.pexels.com/",
}

# Valores aceitos pelos filtros da busca avançada do Pexels
VALID_ORIENTATIONS = {"landscape", "portrait", "square"}
VALID_PEOPLE_COUNT = {"0", "1", "2", "3_plus"}
VALID_PEOPLE_AGE = {"baby", "child", "teenager", "adult", "senior_adult"}
VALID_FRAME_RATE = {"24", "25", "30", "50", "60_plus"}
VALID_RESOLUTION = {"1080p", "4K", "8K"}
VALID_DATE_FROM = {"last_24_hours", "last_week", "last_month", "last_year"}

# Ordem de preferência de qualidade quando pedimos "best"/"worst"
QUALITY_RANK = {"sd": 0, "hd": 1, "uhd": 2}


class PexelsClientError(Exception):
    """Erro genérico do cliente (rede, parsing, filtro inválido etc.)."""


def _request_with_retry(
    session: ChromeSession,
    method: str,
    url: str,
    max_retries: int = 3,
    backoff_factor: float = 0.5,
    retry_statuses: tuple = (429, 500, 502, 503, 504),
    use_fetch: bool = False,
    **kwargs: Any,
) -> BrowserResponse:
    """Faz uma requisição HTTP com retry automático (backoff exponencial)
    para erros transitórios: falhas de conexão/timeout, ou respostas com
    status 429/5xx. Erros "definitivos" (404, 403 etc.) são devolvidos
    imediatamente, sem retry — não adianta tentar de novo.

    use_fetch=True: usa `session.fetch_api()` em vez de `session.request()`
    — importante para endpoints de API JSON, onde navegar a aba inteira
    pra lá (`driver.get`) é bem diferente de como o site de verdade busca
    esses dados (via `fetch()` de dentro da página), e pode disparar
    bloqueio anti-bot que uma chamada `fetch()` normal não dispara.
    """
    last_exc: Optional[Exception] = None
    resp: Optional[BrowserResponse] = None

    for attempt in range(max_retries + 1):
        try:
            if use_fetch:
                resp = session.fetch_api(url, **kwargs)
            else:
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
# Estrutura de dados de um vídeo (já "limpa", pronta para consumo)
# --------------------------------------------------------------------------- #

@dataclass
class PexelsVideo:
    id: str
    title: str
    slug: str
    description: str
    url: str  # link da página do vídeo no pexels.com
    width: int
    height: int
    aspect_ratio: float
    duration: int
    fps: float
    author: str
    author_url: str
    tags: List[str]
    thumbnail: str
    thumbnail_large: str
    video_files: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def best_file(self, max_quality: Optional[str] = None) -> Dict[str, Any]:
        """Retorna o arquivo de vídeo de maior resolução disponível.

        max_quality: 'sd' | 'hd' | 'uhd' -> limita o teto de qualidade.
        """
        files = self._sorted_files()
        if max_quality:
            files = [f for f in files if f.get("quality") in (None,) or
                     QUALITY_RANK.get(f.get("quality", "sd"), 0)
                     <= QUALITY_RANK.get(max_quality, 2)]
        if not files:
            raise PexelsClientError(f"Nenhum arquivo de vídeo encontrado para {self.id}")
        return files[-1]

    def worst_file(self) -> Dict[str, Any]:
        files = self._sorted_files()
        if not files:
            raise PexelsClientError(f"Nenhum arquivo de vídeo encontrado para {self.id}")
        return files[0]

    def file_by_quality(self, quality: str) -> Dict[str, Any]:
        """Pega o maior arquivo dentro de uma qualidade específica (sd/hd/uhd)."""
        candidates = [f for f in self.video_files if f.get("quality") == quality]
        if not candidates:
            raise PexelsClientError(
                f"Qualidade '{quality}' não disponível para o vídeo {self.id}. "
                f"Disponíveis: {sorted({f.get('quality') for f in self.video_files})}"
            )
        return sorted(candidates, key=lambda f: f.get("width", 0))[-1]

    def _sorted_files(self) -> List[Dict[str, Any]]:
        return sorted(self.video_files, key=lambda f: f.get("width", 0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "slug": self.slug,
            "description": self.description,
            "url": self.url,
            "width": self.width,
            "height": self.height,
            "aspect_ratio": self.aspect_ratio,
            "duration": self.duration,
            "fps": self.fps,
            "author": self.author,
            "author_url": self.author_url,
            "tags": self.tags,
            "thumbnail": self.thumbnail,
            "thumbnail_large": self.thumbnail_large,
            "video_files": self.video_files,
        }


# --------------------------------------------------------------------------- #
# Cliente principal
# --------------------------------------------------------------------------- #

class PexelsClient:
    def __init__(self, session: Optional[ChromeSession] = None, delay: float = 0.4):
        """
        session: permite reaproveitar uma sessão requests já configurada
                 (proxies, cookies etc.)
        delay:   pausa (em segundos) entre requisições ao paginar/baixar,
                 para não martelar o servidor.
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
        per_page: int = 24,
        orientation: Optional[str] = None,
        people_count: Optional[Union[str, int]] = None,
        people_age: Optional[str] = None,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None,
        frame_rate: Optional[Union[str, int]] = None,
        resolution_name: Optional[str] = None,
        date_from: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Faz UMA chamada à API de busca e devolve o JSON cru.

        Todos os filtros são opcionais e replicam exatamente os parâmetros
        da busca avançada do site (veja VALID_* no topo do arquivo para os
        valores aceitos).
        """
        params = self._build_params(
            query=query,
            page=page,
            per_page=per_page,
            orientation=orientation,
            people_count=people_count,
            people_age=people_age,
            min_duration=min_duration,
            max_duration=max_duration,
            frame_rate=frame_rate,
            resolution_name=resolution_name,
            date_from=date_from,
        )

        resp = _request_with_retry(self.session, "GET", BASE_SEARCH_URL, params=params, timeout=20, use_fetch=True)
        if resp.status_code != 200:
            raise PexelsClientError(
                f"Falha na busca (status {resp.status_code}): {resp.text[:300]}"
            )
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise PexelsClientError(f"Resposta não é um JSON válido: {exc}") from exc

    def search_html(
        self,
        query: str,
        page: int = 1,
        **filters: Any,
    ) -> List["PexelsVideo"]:
        """Busca navegando na página normal de resultados (a mesma que você
        vê no navegador: `https://www.pexels.com/search/videos/<termo>/`),
        em vez de bater na API JSON interna.

        Esse é o caminho DEFAULT usado por `search_all()` — é comprovadamente
        mais confiável, porque é exatamente a navegação que um usuário de
        verdade faz (`driver.get()` numa página normal), sem o risco de
        bloqueio que uma navegação direta a um endpoint de API pode
        disparar.

        Tenta, nessa ordem:
          1) Extrair o JSON embutido em __NEXT_DATA__ da própria página de
             busca (dados completos, mesma estrutura da API).
          2) Se não achar, faz parsing direto do HTML dos cards de vídeo
             (menos rico — sem tags/autor/duração — mas sempre disponível,
             como confirmado pelo HTML real da página).

        Os resultados dessa página têm o suficiente pra identificar e listar
        vídeos; o `download_video()` busca os dados completos (qualidade
        máxima) na hora de baixar, via `get_video_by_url()`.
        """
        encoded_query = quote(query.strip())
        url = f"{SEARCH_PAGE_BASE}{encoded_query}/"
        params = {"page": page} if page and page != 1 else {}
        # Filtros da busca avançada (mesmos nomes usados pela API) — se o
        # site não reconhecer algum na página HTML, ele é simplesmente
        # ignorado ali (sem quebrar nada), diferente de bater numa API.
        for key, value in filters.items():
            if value is not None:
                params[key] = value

        resp = _request_with_retry(self.session, "GET", url, params=params, timeout=20)
        if resp.status_code != 200:
            raise PexelsClientError(
                f"Falha ao abrir a página de busca (status {resp.status_code}): {resp.text[:300]}"
            )

        videos = self._parse_next_data_search(resp.text)
        if videos is not None:
            return videos
        return self._parse_search_html(resp.text)

    def _parse_next_data_search(self, html_text: str) -> Optional[List["PexelsVideo"]]:
        """Tenta extrair a lista de vídeos do __NEXT_DATA__ da página de
        busca (dados completos, mesmo formato da API). Devolve None se não
        encontrar essa estrutura (não é erro — só significa que vamos cair
        pro parsing direto do HTML).
        """
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.DOTALL)
        if not match:
            return None
        try:
            next_data = json.loads(match.group(1))
            page_props = next_data["props"]["pageProps"]
            # O nome exato do campo pode variar; tenta os mais prováveis.
            items = (
                page_props.get("mediaData")
                or page_props.get("media")
                or page_props.get("results")
                or {}
            )
            data = items.get("data") if isinstance(items, dict) else items
            if not data:
                return None
            videos = []
            for item in data:
                video = self._parse_search_item(item) if "attributes" in item else None
                if video:
                    videos.append(video)
            return videos or None
        except (KeyError, TypeError, json.JSONDecodeError):
            return None

    def _parse_search_html(self, html_text: str) -> List["PexelsVideo"]:
        """Faz parsing direto do HTML da página de busca, extraindo cada
        card de vídeo: id, url, thumbnail, e um preview de vídeo (baixa
        resolução, mas um link real e funcional).

        Ignora automaticamente blocos que não são cards de vídeo de
        verdade (anúncios do Canva, vídeos patrocinados de terceiros como
        iStock) — eles não têm o padrão `href="/video/slug-ID/"` seguido
        de um `<video src=...>` de vídeo do próprio pexels.com.
        """
        videos: List[PexelsVideo] = []
        seen_ids = set()

        for chunk in re.split(r"(?=<article\b)", html_text)[1:]:
            href_match = re.search(r'href="(/video/([a-z0-9-]+)-(\d+)/)"', chunk)
            if not href_match:
                continue
            path, slug, video_id = href_match.groups()
            if video_id in seen_ids:
                continue

            video_match = re.search(r'<video[^>]*\bsrc="(https://videos\.pexels\.com/[^"]+)"', chunk)
            if not video_match:
                continue  # sem preview de vídeo do próprio pexels.com -> não é um card de vídeo real

            thumb_match = re.search(r'<img[^>]+src="([^"]+)"', chunk)
            preview_url = html.unescape(video_match.group(1))

            seen_ids.add(video_id)
            videos.append(PexelsVideo(
                id=video_id,
                title=slug.replace("-", " ").strip().capitalize(),
                slug=slug,
                description="",
                url=f"https://www.pexels.com{path}",
                width=0, height=0, aspect_ratio=0.0, duration=0, fps=0.0,
                author="", author_url="",
                tags=[],
                thumbnail=html.unescape(thumb_match.group(1)) if thumb_match else "",
                thumbnail_large="",
                video_files=[{"quality": "preview", "link": preview_url, "width": None, "height": None}],
                raw={"source": "html_search"},
            ))

        return videos

    def search_all(
        self,
        query: str,
        max_pages: int = 10,
        per_page: int = 24,
        stop_when_empty: bool = True,
        use_api: bool = False,
        **filters: Any,
    ) -> List[PexelsVideo]:
        """Rola várias páginas de resultado e devolve uma lista única,
        já deduplicada por ID, de objetos PexelsVideo prontos pra usar.

        Por padrão (use_api=False), navega na página normal de resultados
        (`search_html()`) — o caminho mais confiável, porque é exatamente
        como um usuário de verdade busca. Se isso falhar (ex: mudança de
        layout do site), cai automaticamente pra API JSON interna como
        fallback.

        use_api=True: pula direto pra API JSON (dados mais completos —
        tags, autor, duração — mas sujeito a bloqueio anti-bot).

        max_pages:       teto de segurança de páginas a percorrer.
        stop_when_empty: para assim que uma página vier vazia (fim dos resultados).
        filters:         mesmos filtros aceitos por `search()`/`search_html()`.
        """
        all_videos: Dict[str, PexelsVideo] = {}

        for page in range(1, max_pages + 1):
            items: List[PexelsVideo] = []
            html_failed = False

            if not use_api:
                try:
                    items = self.search_html(query=query, page=page, **filters)
                except PexelsClientError:
                    html_failed = True  # cai pro fallback da API abaixo

            if use_api or html_failed:
                raw = self.search(query=query, page=page, per_page=per_page, **filters)
                raw_items = raw.get("data", [])
                items = [v for v in (self._parse_search_item(i) for i in raw_items) if v]
                if not raw_items and stop_when_empty:
                    break
                if len(raw_items) < per_page:
                    for video in items:
                        all_videos[video.id] = video
                    break

            if not items and stop_when_empty:
                break

            for video in items:
                all_videos[video.id] = video

            time.sleep(self.delay)

        return list(all_videos.values())

    # ------------------------------------------------------------------ #
    # Detalhe de um vídeo (a partir da URL da página)
    # ------------------------------------------------------------------ #

    def get_video_by_url(self, video_url: str) -> PexelsVideo:
        """Abre a página HTML de um vídeo específico e extrai o JSON
        embutido em <script id="__NEXT_DATA__">, que contém todos os
        links de download por qualidade.

        Se esse bloco não for encontrado (mudança de layout, ou a página
        não expõe mais isso), cai num fallback: extrai diretamente do HTML
        a descrição (atributo `title` do `<h1>`) e o `<video src=...>` de
        maior resolução disponível na própria página — menos completo
        (sem tags/autor/outras qualidades), mas confirmadamente presente
        na página de qualquer vídeo.
        """
        resp = _request_with_retry(self.session, "GET", video_url, timeout=20)
        if resp.status_code != 200:
            raise PexelsClientError(
                f"Falha ao abrir a página do vídeo (status {resp.status_code}): {video_url}"
            )

        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            resp.text,
            re.DOTALL,
        )
        if match:
            try:
                next_data = json.loads(match.group(1))
                medium = next_data["props"]["pageProps"]["medium"]
                return self._parse_medium(medium)
            except (KeyError, json.JSONDecodeError):
                pass  # cai pro fallback de HTML abaixo

        return self._parse_video_page_html(resp.text, video_url)

    def _parse_video_page_html(self, html_text: str, video_url: str) -> PexelsVideo:
        """Fallback de get_video_by_url: extrai descrição e vídeo direto
        do HTML da página, sem depender de __NEXT_DATA__.
        """
        id_match = re.search(r"-(\d+)/?(?:\?.*)?$", video_url.rstrip("/") + "/")
        video_id = id_match.group(1) if id_match else ""
        slug_match = re.search(r"/video/([a-z0-9-]+)-\d+/?", video_url)
        slug = slug_match.group(1) if slug_match else "video"

        desc_match = re.search(r'<h1[^>]*title="([^"]*)"', html_text)
        description = html.unescape(desc_match.group(1)) if desc_match else ""

        video_match = re.search(r'<video[^>]*\bsrc="(https://videos\.pexels\.com/[^"]+)"', html_text)
        if not video_match:
            raise PexelsClientError(
                f"Não encontrei nem __NEXT_DATA__ nem um <video src=...> na página: {video_url}"
            )
        video_link = html.unescape(video_match.group(1))

        # Tenta extrair largura/altura do nome do arquivo (ex: ..._1080_1920_30fps.mp4)
        dims_match = re.search(r"_(\d+)_(\d+)_\d+fps\.mp4", video_link)
        width = int(dims_match.group(1)) if dims_match else 0
        height = int(dims_match.group(2)) if dims_match else 0

        return PexelsVideo(
            id=video_id,
            title=slug.replace("-", " ").strip().capitalize(),
            slug=slug,
            description=description,
            url=video_url,
            width=width, height=height, aspect_ratio=0.0, duration=0, fps=0.0,
            author="", author_url="",
            tags=[],
            thumbnail="", thumbnail_large="",
            video_files=[{"quality": "hd", "link": video_link, "width": width, "height": height}],
            raw={"source": "html_video_page"},
        )

    def get_video_by_id(self, video_id: Union[str, int], slug: str = "video") -> PexelsVideo:
        """Monta a URL padrão /video/<slug>-<id>/ e delega para get_video_by_url.

        Se você só tem o ID (sem slug), o Pexels aceita qualquer slug na URL
        contanto que o número no final esteja certo, então "video" funciona
        como slug genérico.
        """
        url = f"{VIDEO_PAGE_BASE}{slug}-{video_id}/"
        return self.get_video_by_url(url)

    # ------------------------------------------------------------------ #
    # Download
    # ------------------------------------------------------------------ #

    def download_video(
        self,
        video: Union[PexelsVideo, str, Dict[str, Any]],
        output_dir: str = "videos",
        quality: str = "best",
        filename: Optional[str] = None,
        chunk_size: int = 1024 * 1024,
        overwrite: bool = False,
    ) -> str:
        """Baixa um vídeo para o disco.

        video: pode ser
            - um PexelsVideo (retornado por search_all / get_video_by_url)
            - uma URL da página do vídeo (ex: ".../video/algo-123456/")
            - um dict cru vindo da busca (item de raw["data"])
        quality: 'best' | 'worst' | 'sd' | 'hd' | 'uhd'
        filename: nome do arquivo final; se None, usa "<slug>-<id>-<qualidade>.mp4"

        Retorna o caminho completo do arquivo salvo.
        """
        pv = self._resolve_video(video)

        # Se o vídeo veio do scraping da página de busca (só tem o preview
        # de baixa resolução), busca os dados completos na página do vídeo
        # antes de baixar — isso já usa __NEXT_DATA__ via navegação normal
        # (get_video_by_url), então mantém a mesma robustez.
        if pv.raw.get("source") == "html_search":
            try:
                pv = self.get_video_by_url(pv.url)
            except PexelsClientError:
                pass  # sem os dados completos, segue com o preview mesmo

        if quality == "best":
            file_info = pv.best_file()
        elif quality == "worst":
            file_info = pv.worst_file()
        else:
            file_info = pv.file_by_quality(quality)

        # A API fornece tanto a URL direta quanto a rota oficial de download.
        # Preferimos download_link, pois ela aciona o fluxo oficial do Pexels.
        link = file_info.get("download_link") or file_info.get("link")
        if not link:
            raise PexelsClientError(f"Arquivo de vídeo sem link de download: {file_info}")

        os.makedirs(output_dir, exist_ok=True)

        if not filename:
            q = file_info.get("quality") or f"{file_info.get('width')}p"
            filename = f"{pv.slug}-{pv.id}-{q}.mp4"
        filepath = os.path.join(output_dir, filename)

        if os.path.exists(filepath) and not overwrite:
            return filepath

        self.session.download(link, filepath, timeout=120)

        time.sleep(self.delay)
        return filepath

    def download_many(
        self,
        videos: List[Union[PexelsVideo, str, Dict[str, Any]]],
        output_dir: str = "videos",
        quality: str = "best",
        overwrite: bool = False,
        on_progress=None,
    ) -> List[str]:
        """Baixa uma lista de vídeos em sequência. `on_progress(i, total, path)`
        é chamado (se fornecido) após cada download.
        """
        paths = []
        total = len(videos)
        for i, v in enumerate(videos, start=1):
            path = self.download_video(
                v, output_dir=output_dir, quality=quality, overwrite=overwrite
            )
            paths.append(path)
            if on_progress:
                on_progress(i, total, path)
        return paths

    # ------------------------------------------------------------------ #
    # Helpers internos
    # ------------------------------------------------------------------ #

    def _resolve_video(self, video: Union[PexelsVideo, str, Dict[str, Any]]) -> PexelsVideo:
        if isinstance(video, PexelsVideo):
            return video
        if isinstance(video, str):
            return self.get_video_by_url(video)
        if isinstance(video, dict):
            # Pode ser um item cru de busca (com "attributes") ou já o "medium"
            if "attributes" in video:
                return self._parse_search_item(video)
            return self._parse_medium(video)
        raise PexelsClientError(f"Tipo de vídeo não suportado: {type(video)}")

    @staticmethod
    def _build_params(**kwargs: Any) -> Dict[str, Any]:
        query = kwargs["query"]
        params: Dict[str, Any] = {
            "query": query,
            "page": kwargs.get("page", 1),
            "per_page": kwargs.get("per_page", 24),
            "seo_tags": "true",
        }

        orientation = kwargs.get("orientation")
        if orientation:
            if orientation not in VALID_ORIENTATIONS:
                raise PexelsClientError(
                    f"orientation inválido: {orientation!r} (use {VALID_ORIENTATIONS})"
                )
            params["orientation"] = orientation

        people_count = kwargs.get("people_count")
        if people_count is not None:
            people_count = str(people_count)
            if people_count == "3":
                people_count = "3_plus"
            if people_count not in VALID_PEOPLE_COUNT:
                raise PexelsClientError(
                    f"people_count inválido: {people_count!r} (use {VALID_PEOPLE_COUNT})"
                )
            params["people_count"] = people_count

        people_age = kwargs.get("people_age")
        if people_age:
            if people_age not in VALID_PEOPLE_AGE:
                raise PexelsClientError(
                    f"people_age inválido: {people_age!r} (use {VALID_PEOPLE_AGE})"
                )
            params["people_age"] = people_age

        if kwargs.get("min_duration") is not None:
            params["min_duration"] = int(kwargs["min_duration"])
        if kwargs.get("max_duration") is not None:
            params["max_duration"] = int(kwargs["max_duration"])

        frame_rate = kwargs.get("frame_rate")
        if frame_rate is not None:
            frame_rate = str(frame_rate)
            if frame_rate == "60":
                frame_rate = "60_plus"
            if frame_rate not in VALID_FRAME_RATE:
                raise PexelsClientError(
                    f"frame_rate inválido: {frame_rate!r} (use {VALID_FRAME_RATE})"
                )
            params["frame_rate"] = frame_rate

        resolution_name = kwargs.get("resolution_name")
        if resolution_name:
            if resolution_name not in VALID_RESOLUTION:
                raise PexelsClientError(
                    f"resolution_name inválido: {resolution_name!r} (use {VALID_RESOLUTION})"
                )
            params["resolution_name"] = resolution_name

        date_from = kwargs.get("date_from")
        if date_from:
            if date_from not in VALID_DATE_FROM:
                raise PexelsClientError(
                    f"date_from inválido: {date_from!r} (use {VALID_DATE_FROM})"
                )
            params["date_from"] = date_from

        return params

    @staticmethod
    def _parse_search_item(item: Dict[str, Any]) -> Optional[PexelsVideo]:
        """Converte um item de raw["data"] (resultado de busca) em PexelsVideo.
        Itens que não são vídeos de verdade (ex: cards promocionais da Canva)
        são ignorados (retorna None).
        """
        if item.get("type") != "video":
            return None
        attrs = item.get("attributes", {})
        if not attrs:
            return None

        video_block = attrs.get("video", {}) or {}
        video_files = (video_block.get("video_files", []) if isinstance(video_block, dict) else []) or attrs.get("video_files", []) or []
        thumb = (video_block.get("thumbnail", {}) if isinstance(video_block, dict) else {}) or attrs.get("thumbnail", {}) or {}
        if isinstance(thumb, str):
            thumb = {"medium": thumb, "large": thumb, "small": thumb}
        user = attrs.get("user", {}) or {}
        tags = [t.get("name") for t in attrs.get("tags", []) if t.get("name")]

        vid_id = str(attrs.get("id"))
        slug = attrs.get("slug", "video")

        return PexelsVideo(
            id=vid_id,
            title=attrs.get("title", ""),
            slug=slug,
            description=attrs.get("description", ""),
            url=f"{VIDEO_PAGE_BASE}{slug}-{vid_id}/",
            width=attrs.get("width", 0),
            height=attrs.get("height", 0),
            aspect_ratio=attrs.get("aspect_ratio", 0),
            duration=attrs.get("duration", 0),
            fps=attrs.get("fps", 0),
            author=f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
            author_url=f"https://www.pexels.com/@{user.get('slug', '')}",
            tags=tags,
            thumbnail=thumb.get("medium", thumb.get("small", "")),
            thumbnail_large=thumb.get("large", thumb.get("medium", "")),
            video_files=video_files,
            raw=item,
        )

    @staticmethod
    def _parse_medium(attrs: Dict[str, Any]) -> PexelsVideo:
        """Converte o objeto 'medium' vindo do __NEXT_DATA__ da página de
        um vídeo específico em PexelsVideo. Estrutura ligeiramente diferente
        da usada na busca (às vezes vem "attributes" aninhado, às vezes não).
        """
        # o __NEXT_DATA__["props"]["pageProps"]["medium"] tem shape:
        # {"id": ..., "type": "video", "attributes": {...}}
        if "attributes" in attrs:
            attrs = attrs["attributes"]

        video_block = attrs.get("video", {}) or {}
        video_files = (video_block.get("video_files", []) if isinstance(video_block, dict) else []) or attrs.get("video_files", []) or []
        thumb = (video_block.get("thumbnail", {}) if isinstance(video_block, dict) else {}) or attrs.get("thumbnail", {}) or {}
        if isinstance(thumb, str):
            thumb = {"medium": thumb, "large": thumb, "small": thumb}
        user = attrs.get("user", {}) or {}
        tags = [t.get("name") for t in attrs.get("tags", []) if t.get("name")]

        vid_id = str(attrs.get("id"))
        slug = attrs.get("slug", "video")

        return PexelsVideo(
            id=vid_id,
            title=attrs.get("title", ""),
            slug=slug,
            description=attrs.get("description", ""),
            url=f"{VIDEO_PAGE_BASE}{slug}-{vid_id}/",
            width=attrs.get("width", 0),
            height=attrs.get("height", 0),
            aspect_ratio=attrs.get("aspect_ratio", 0),
            duration=attrs.get("duration", 0),
            fps=attrs.get("fps", 0),
            author=f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
            author_url=f"https://www.pexels.com/@{user.get('slug', '')}",
            tags=tags,
            thumbnail=thumb.get("medium", thumb.get("small", "")),
            thumbnail_large=thumb.get("large", thumb.get("medium", "")),
            video_files=video_files,
            raw=attrs,
        )

    @staticmethod
    def extract_id_from_url(url: str) -> str:
        """Extrai o ID numérico do fim de uma URL de vídeo do Pexels."""
        match = re.search(r"-(\d+)/?$", url.rstrip("/"))
        if not match:
            raise PexelsClientError(f"Não consegui extrair o ID da URL: {url}")
        return match.group(1)


# --------------------------------------------------------------------------- #
# CLI simples (opcional) — útil para testar rapidamente pelo terminal
# --------------------------------------------------------------------------- #

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Buscar e baixar vídeos do Pexels (API interna, sem chave)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- search ---
    p_search = sub.add_parser("search", help="Buscar vídeos e listar resultados (JSON).")
    p_search.add_argument("query", help='Termo de busca, ex: "dog and cats"')
    p_search.add_argument("--pages", type=int, default=1, help="Quantidade de páginas a buscar.")
    p_search.add_argument("--per-page", type=int, default=24)
    p_search.add_argument("--orientation", choices=sorted(VALID_ORIENTATIONS))
    p_search.add_argument("--people-count", choices=sorted(VALID_PEOPLE_COUNT))
    p_search.add_argument("--people-age", choices=sorted(VALID_PEOPLE_AGE))
    p_search.add_argument("--min-duration", type=int)
    p_search.add_argument("--max-duration", type=int)
    p_search.add_argument("--frame-rate", choices=sorted(VALID_FRAME_RATE))
    p_search.add_argument("--resolution-name", choices=sorted(VALID_RESOLUTION))
    p_search.add_argument("--date-from", choices=sorted(VALID_DATE_FROM))
    p_search.add_argument("--out", help="Salvar resultado em um arquivo .json")

    # --- download ---
    p_dl = sub.add_parser("download", help="Baixar um vídeo específico.")
    p_dl.add_argument("target", help="URL da página do vídeo OU apenas o ID numérico.")
    p_dl.add_argument("--quality", default="best", choices=["best", "worst", "sd", "hd", "uhd"])
    p_dl.add_argument("--output-dir", default="videos")

    args = parser.parse_args()
    client = PexelsClient()

    if args.command == "search":
        filters = dict(
            orientation=args.orientation,
            people_count=args.people_count,
            people_age=args.people_age,
            min_duration=args.min_duration,
            max_duration=args.max_duration,
            frame_rate=args.frame_rate,
            resolution_name=args.resolution_name,
            date_from=args.date_from,
        )
        filters = {k: v for k, v in filters.items() if v is not None}

        videos = client.search_all(
            query=args.query,
            max_pages=args.pages,
            per_page=args.per_page,
            **filters,
        )
        result = [v.to_dict() for v in videos]

        print(f"{len(result)} vídeos encontrados.")
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"Salvo em {args.out}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "download":
        target = args.target
        if target.isdigit():
            video = client.get_video_by_id(target)
        else:
            video = target  # deixa o download_video resolver via get_video_by_url

        path = client.download_video(video, output_dir=args.output_dir, quality=args.quality)
        print(f"Baixado em: {path}")


if __name__ == "__main__":
    _cli()
