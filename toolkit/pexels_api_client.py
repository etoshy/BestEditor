"""
pexels_api_client.py
======================

Cliente do Pexels usando a **API oficial** (https://api.pexels.com), em
vez de navegar/fazer scraping do site (que é o que `pexels_client.py`
faz). Existe porque o site do Pexels está atrás de Cloudflare, e a API
oficial é o caminho pretendido pelo próprio Pexels pra automação — sem
risco de bloqueio, sem precisar de Chrome/Selenium (é só HTTP + JSON).

A API oficial é gratuita: peça uma chave em https://www.pexels.com/api/
Ela tem rate limit (varia por conta; o plano gratuito padrão gira em
torno de 200 requisições/hora, 20.000/mês). Este cliente aceita **uma ou
mais chaves** e alterna automaticamente pra próxima assim que uma bate o
limite.

Configuração (.env)
--------------------
Crie um arquivo `.env` na raiz do projeto (veja `.env.example`):

    PEXELS_API_KEYS=sua_chave_aqui
    # ou várias, separadas por vírgula, pra rotacionar quando uma esgotar:
    PEXELS_API_KEYS=chave_um,chave_dois,chave_tres

Uso
----
    from pexels_api_client import PexelsAPIClient

    client = PexelsAPIClient()  # lê PEXELS_API_KEYS do .env/ambiente

    videos = client.search_all(query="dog and cats", max_pages=3)
    client.download_video(videos[0], output_dir="videos")

Limitação importante em relação ao `pexels_client.py` (scraping): a API
oficial não devolve título/descrição curados nem tags — só id, url,
dimensões, duração, autor e os arquivos de vídeo por qualidade. Um
título legível é gerado a partir do slug da URL, como fallback.
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
from urllib.parse import urlencode

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_keys import APIKeyPool, NoAvailableAPIKeyError, load_dotenv

_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_META_DESCRIPTION_RE = re.compile(
    r'<meta\s+name="description"\s+content="([^"]*)"', re.IGNORECASE
)

API_BASE = "https://api.pexels.com/videos"
SEARCH_URL = f"{API_BASE}/search"
POPULAR_URL = f"{API_BASE}/popular"
VIDEO_URL = f"{API_BASE}/videos"

PHOTO_API_BASE = "https://api.pexels.com/v1"  # API de FOTOS — mesma chave, endpoint diferente
PHOTO_SEARCH_URL = f"{PHOTO_API_BASE}/search"
PHOTO_URL = f"{PHOTO_API_BASE}/photos"

QUALITY_RANK = {"sd": 0, "hd": 1, "uhd": 2}
PHOTO_SIZE_RANK = {"tiny": 0, "small": 1, "medium": 2, "large": 3, "large2x": 4, "original": 5}


class PexelsAPIClientError(Exception):
    """Erro genérico do cliente (rede, parsing, chave inválida etc.)."""


@dataclass
class PexelsAPIVideo:
    id: str
    title: str
    slug: str
    description: str
    url: str
    width: int
    height: int
    duration: int
    author: str
    author_url: str
    thumbnail: str
    video_files: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def _sorted_files(self) -> List[Dict[str, Any]]:
        return sorted(self.video_files, key=lambda f: (f.get("width") or 0))

    def best_file(self, max_quality: Optional[str] = None) -> Dict[str, Any]:
        files = self._sorted_files()
        if max_quality:
            files = [
                f for f in files
                if QUALITY_RANK.get(f.get("quality", "sd"), 0) <= QUALITY_RANK.get(max_quality, 2)
            ]
        if not files:
            raise PexelsAPIClientError(f"Nenhum arquivo de vídeo encontrado para {self.id}")
        return files[-1]

    def worst_file(self) -> Dict[str, Any]:
        files = self._sorted_files()
        if not files:
            raise PexelsAPIClientError(f"Nenhum arquivo de vídeo encontrado para {self.id}")
        return files[0]

    def file_by_quality(self, quality: str) -> Dict[str, Any]:
        candidates = [f for f in self.video_files if f.get("quality") == quality]
        if not candidates:
            raise PexelsAPIClientError(
                f"Qualidade '{quality}' não disponível para o vídeo {self.id}. "
                f"Disponíveis: {sorted({f.get('quality') for f in self.video_files})}"
            )
        return sorted(candidates, key=lambda f: f.get("width") or 0)[-1]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "slug": self.slug,
            "description": self.description,
            "url": self.url,
            "width": self.width,
            "height": self.height,
            "duration": self.duration,
            "author": self.author,
            "author_url": self.author_url,
            "thumbnail": self.thumbnail,
            "video_files": self.video_files,
        }


@dataclass
class PexelsAPIPhoto:
    id: str
    description: str  # a API de fotos, ao contrário da de vídeos, FORNECE descrição real (campo "alt")
    url: str
    width: int
    height: int
    author: str
    author_url: str
    avg_color: str
    sizes: Dict[str, str] = field(default_factory=dict)  # nome do tamanho -> URL
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def best_size_url(self) -> str:
        if not self.sizes:
            raise PexelsAPIClientError(f"Nenhum tamanho de imagem disponível para a foto {self.id}")
        best_name = max(self.sizes, key=lambda name: PHOTO_SIZE_RANK.get(name, -1))
        return self.sizes[best_name]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "description": self.description, "url": self.url,
            "width": self.width, "height": self.height, "author": self.author,
            "author_url": self.author_url, "avg_color": self.avg_color, "sizes": self.sizes,
        }


class PexelsAPIClient:
    def __init__(
        self,
        api_keys: Optional[Union[str, List[str]]] = None,
        env_var: str = "PEXELS_API_KEYS",
        dotenv_path: str = ".env",
        delay: float = 0.2,
        max_key_rotations: Optional[int] = None,
    ):
        """
        api_keys: chave única, lista de chaves, ou None (padrão) para ler
            de `env_var` (que por sua vez pode vir de um arquivo `.env`
            carregado automaticamente daqui, se existir).
        max_key_rotations: quantas chaves tentar antes de desistir de uma
            chamada (padrão: o número de chaves no pool, ou seja, tenta
            todas antes de falhar).
        """
        load_dotenv(dotenv_path)

        if api_keys is None:
            self.pool = APIKeyPool.from_env(env_var)
        elif isinstance(api_keys, str):
            self.pool = APIKeyPool([api_keys])
        else:
            self.pool = APIKeyPool(list(api_keys))

        self.delay = delay
        self.max_key_rotations = max_key_rotations or len(self.pool)
        self.session = requests.Session()

    # ------------------------------------------------------------------ #
    # Requisição com rotação automática de chave
    # ------------------------------------------------------------------ #

    def _request(self, url: str, params: Optional[dict] = None) -> Dict[str, Any]:
        last_error: Optional[str] = None

        for _ in range(self.max_key_rotations):
            try:
                key = self.pool.current_key()
            except NoAvailableAPIKeyError as exc:
                raise PexelsAPIClientError(str(exc)) from exc

            resp = self.session.get(
                url, params=params, headers={"Authorization": key}, timeout=20
            )

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                retry_seconds = float(retry_after) if retry_after else None
                last_error = f"chave rate-limited (429) em {url}"
                self.pool.mark_rate_limited(key, retry_after_seconds=retry_seconds)
                continue

            if resp.status_code in (401, 403):
                raise PexelsAPIClientError(
                    f"Chave de API inválida ou sem permissão (status {resp.status_code}). "
                    f"Confira PEXELS_API_KEYS no seu .env. Resposta: {resp.text[:200]}"
                )

            if resp.status_code != 200:
                raise PexelsAPIClientError(
                    f"Falha na API do Pexels (status {resp.status_code}): {resp.text[:300]}"
                )

            try:
                return resp.json()
            except json.JSONDecodeError as exc:
                raise PexelsAPIClientError(f"Resposta não é um JSON válido: {exc}") from exc

        raise PexelsAPIClientError(
            f"Todas as chaves disponíveis bateram rate limit. Último erro: {last_error}"
        )

    # ------------------------------------------------------------------ #
    # Busca
    # ------------------------------------------------------------------ #

    def search(
        self,
        query: str,
        page: int = 1,
        per_page: int = 15,
        orientation: Optional[str] = None,
        size: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Uma chamada de busca à API oficial. `per_page` máximo é 80.

        orientation: 'landscape' | 'portrait' | 'square'
        size:        'large' | 'medium' | 'small' (resolução mínima)
        """
        params: Dict[str, Any] = {"query": query, "page": page, "per_page": per_page}
        if orientation:
            params["orientation"] = orientation
        if size:
            params["size"] = size
        if locale:
            params["locale"] = locale
        return self._request(SEARCH_URL, params=params)

    def search_all(
        self,
        query: str,
        max_pages: int = 10,
        per_page: int = 15,
        fetch_descriptions: bool = True,
        **filters: Any,
    ) -> List[PexelsAPIVideo]:
        """Pagina pelos resultados usando o campo `next_page` que a
        própria API devolve (mais confiável do que contar itens), até
        `max_pages` ou até não haver mais `next_page`.

        fetch_descriptions=True (padrão): a API oficial não devolve
        descrição curada, então, pra cada vídeo, é feita uma requisição
        HTTP simples (sem chave, sem Chrome) à própria página pública do
        vídeo e extraída a meta-tag `description` de lá — é a mesma
        frase que aparece no Google/redes sociais para aquele vídeo.
        Isso é melhor esforço: se a página não responder por qualquer
        motivo, a descrição fica vazia, sem quebrar a busca. Desligue
        com `fetch_descriptions=False` se quiser mais velocidade e não
        precisar da descrição.
        """
        all_videos: Dict[str, PexelsAPIVideo] = {}
        page = 1

        for _ in range(max_pages):
            raw = self.search(query=query, page=page, per_page=per_page, **filters)
            for item in raw.get("videos", []):
                video = self._parse_video(item)
                all_videos[video.id] = video

            if not raw.get("next_page"):
                break
            page += 1
            time.sleep(self.delay)

        videos = list(all_videos.values())
        if fetch_descriptions:
            for video in videos:
                video.description = self._fetch_description(video.url)
                time.sleep(self.delay)

        return videos

    def popular(self, page: int = 1, per_page: int = 15, min_width: Optional[int] = None,
                min_height: Optional[int] = None, min_duration: Optional[int] = None,
                max_duration: Optional[int] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"page": page, "per_page": per_page}
        for name, value in (
            ("min_width", min_width), ("min_height", min_height),
            ("min_duration", min_duration), ("max_duration", max_duration),
        ):
            if value is not None:
                params[name] = value
        return self._request(POPULAR_URL, params=params)

    # ------------------------------------------------------------------ #
    # Fotos (endpoint separado dos vídeos, mesma chave de API)
    # ------------------------------------------------------------------ #

    def search_photos(
        self, query: str, page: int = 1, per_page: int = 15,
        orientation: Optional[str] = None, size: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"query": query, "page": page, "per_page": per_page}
        if orientation:
            params["orientation"] = orientation
        if size:
            params["size"] = size
        return self._request(PHOTO_SEARCH_URL, params=params)

    def search_photos_all(self, query: str, max_pages: int = 5, per_page: int = 15, **filters: Any) -> List[PexelsAPIPhoto]:
        """Pagina pela API de fotos (mesmo padrão de `next_page` da API
        de vídeos) e devolve a lista de `PexelsAPIPhoto` encontradas.
        """
        all_photos: Dict[str, PexelsAPIPhoto] = {}
        page = 1
        for _ in range(max_pages):
            raw = self.search_photos(query=query, page=page, per_page=per_page, **filters)
            for item in raw.get("photos", []):
                photo = self._parse_photo(item)
                all_photos[photo.id] = photo
            if not raw.get("next_page"):
                break
            page += 1
            time.sleep(self.delay)
        return list(all_photos.values())

    def get_photo(self, photo_id: Union[str, int]) -> PexelsAPIPhoto:
        raw = self._request(f"{PHOTO_URL}/{photo_id}")
        return self._parse_photo(raw)

    def download_photo(
        self, photo: Union[PexelsAPIPhoto, Dict[str, Any], str, int],
        output_dir: str = "photos", filename: Optional[str] = None, overwrite: bool = False,
    ) -> str:
        pp = photo if isinstance(photo, PexelsAPIPhoto) else (
            self._parse_photo(photo) if isinstance(photo, dict) else self.get_photo(photo)
        )
        url = pp.best_size_url()
        os.makedirs(output_dir, exist_ok=True)
        if not filename:
            ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
            filename = f"pexels-photo-{pp.id}{ext}"
        filepath = os.path.join(output_dir, filename)
        if os.path.exists(filepath) and not overwrite:
            return filepath
        with self.session.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        return filepath

    @staticmethod
    def _parse_photo(item: Dict[str, Any]) -> PexelsAPIPhoto:
        user = item.get("photographer", "")
        user_url = item.get("photographer_url", "")
        src = item.get("src", {}) or {}
        return PexelsAPIPhoto(
            id=str(item.get("id", "")),
            description=(item.get("alt") or "").strip(),
            url=item.get("url", ""),
            width=item.get("width") or 0,
            height=item.get("height") or 0,
            author=user,
            author_url=user_url,
            avg_color=item.get("avg_color", ""),
            sizes={name: link for name, link in src.items() if link},
            raw=item,
        )

    def get_video(self, video_id: Union[str, int], fetch_description: bool = True) -> PexelsAPIVideo:
        raw = self._request(f"{VIDEO_URL}/{video_id}")
        video = self._parse_video(raw)
        if fetch_description:
            video.description = self._fetch_description(video.url)
        return video

    def get_video_by_url(self, video_url: str, fetch_description: bool = True) -> PexelsAPIVideo:
        """Resolve um vídeo a partir do link da PÁGINA dele (ex:
        "https://www.pexels.com/video/pedestrians-crossing-the-street-27697943/")
        — extrai o ID (o número no final da URL) e busca via API oficial,
        sem precisar abrir a página/usar navegador. Usado pelo site
        principal pra "fixar" um resultado específico escolhido no editor
        de segmentos quando a API (não o scraping) está sendo usada.
        """
        match = re.search(r"-(\d+)/?(?:[?#].*)?$", video_url.rstrip("/"))
        if not match:
            raise PexelsAPIClientError(
                f"Não consegui extrair o ID do vídeo a partir da URL: {video_url!r} "
                "(esperava algo como '.../video/titulo-do-video-1234567/')."
            )
        return self.get_video(match.group(1), fetch_description=fetch_description)

    def _fetch_description(self, video_url: str, timeout: int = 10) -> str:
        """Busca a meta-tag `description` da página pública do vídeo, com
        uma requisição HTTP simples (sem chave de API, sem Chrome). Nunca
        levanta exceção — se algo der errado (timeout, bloqueio, página
        fora do ar), devolve string vazia.
        """
        if not video_url:
            return ""
        try:
            resp = self.session.get(
                video_url,
                headers={"User-Agent": _BROWSER_USER_AGENT, "Accept": "text/html"},
                timeout=timeout,
            )
            if resp.status_code != 200:
                return ""
            match = _META_DESCRIPTION_RE.search(resp.text)
            return html.unescape(match.group(1)).strip() if match else ""
        except Exception:  # noqa: BLE001 - melhor esforço, nunca quebra a busca
            return ""

    # ------------------------------------------------------------------ #
    # Download
    # ------------------------------------------------------------------ #

    def download_video(
        self,
        video: Union[PexelsAPIVideo, Dict[str, Any], str, int],
        output_dir: str = "videos",
        quality: str = "best",
        filename: Optional[str] = None,
        chunk_size: int = 1024 * 1024,
        overwrite: bool = False,
    ) -> str:
        """Baixa um vídeo. `video` pode ser um PexelsAPIVideo, um dict
        cru da API, ou um ID (str/int) — nesse caso busca os dados antes.
        """
        pv = self._resolve_video(video)

        if quality == "best":
            file_info = pv.best_file()
        elif quality == "worst":
            file_info = pv.worst_file()
        else:
            file_info = pv.file_by_quality(quality)

        link = file_info.get("link")
        if not link:
            raise PexelsAPIClientError(f"Arquivo de vídeo sem link: {file_info}")

        os.makedirs(output_dir, exist_ok=True)
        if not filename:
            q = file_info.get("quality") or f"{file_info.get('width')}p"
            filename = f"{pv.slug}-{pv.id}-{q}.mp4"
        filepath = os.path.join(output_dir, filename)

        if os.path.exists(filepath) and not overwrite:
            return filepath

        with self.session.get(link, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)

        time.sleep(self.delay)
        return filepath

    def download_many(
        self,
        videos: List[Union[PexelsAPIVideo, Dict[str, Any], str, int]],
        output_dir: str = "videos",
        quality: str = "best",
        overwrite: bool = False,
        on_progress=None,
    ) -> List[str]:
        paths = []
        total = len(videos)
        for i, v in enumerate(videos, start=1):
            path = self.download_video(v, output_dir=output_dir, quality=quality, overwrite=overwrite)
            paths.append(path)
            if on_progress:
                on_progress(i, total, path)
        return paths

    # ------------------------------------------------------------------ #
    # Helpers internos
    # ------------------------------------------------------------------ #

    def _resolve_video(self, video: Union[PexelsAPIVideo, Dict[str, Any], str, int]) -> PexelsAPIVideo:
        if isinstance(video, PexelsAPIVideo):
            return video
        if isinstance(video, dict):
            return self._parse_video(video)
        return self.get_video(video)  # str ou int -> id

    @staticmethod
    def _parse_video(item: Dict[str, Any]) -> PexelsAPIVideo:
        video_id = str(item.get("id", ""))
        url = item.get("url", "")
        slug_match = re.search(r"/video/([a-z0-9-]+)-\d+/?", url)
        slug = slug_match.group(1) if slug_match else f"video-{video_id}"
        title = slug.replace("-", " ").strip().capitalize() if slug else f"Video {video_id}"

        user = item.get("user") or {}
        video_files = [
            {
                "quality": f.get("quality") or "sd",
                "file_type": f.get("file_type"),
                "width": f.get("width"),
                "height": f.get("height"),
                "fps": f.get("fps"),
                "link": f.get("link"),
            }
            for f in item.get("video_files", [])
            if f.get("link")
        ]

        return PexelsAPIVideo(
            id=video_id,
            title=title,
            slug=slug,
            description="",  # a API oficial não fornece descrição curada
            url=url,
            width=item.get("width") or 0,
            height=item.get("height") or 0,
            duration=item.get("duration") or 0,
            author=user.get("name", ""),
            author_url=user.get("url", ""),
            thumbnail=item.get("image", ""),
            video_files=video_files,
            raw=item,
        )


# --------------------------------------------------------------------------- #
# CLI simples
# --------------------------------------------------------------------------- #

def _cli() -> None:
    parser = argparse.ArgumentParser(description="Cliente da API oficial do Pexels (vídeos).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Busca e salva um JSON com os resultados.")
    p_search.add_argument("query")
    p_search.add_argument("--pages", type=int, default=1)
    p_search.add_argument("--per-page", type=int, default=15)
    p_search.add_argument("--out", default=None)

    p_dl = sub.add_parser("download", help="Baixa um vídeo pelo ID.")
    p_dl.add_argument("video_id")
    p_dl.add_argument("--output-dir", default="videos")
    p_dl.add_argument("--quality", default="best")

    args = parser.parse_args()
    client = PexelsAPIClient()

    if args.command == "search":
        videos = client.search_all(query=args.query, max_pages=args.pages, per_page=args.per_page)
        data = [v.to_dict() for v in videos]
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"{len(data)} vídeos salvos em {args.out}")
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.command == "download":
        path = client.download_video(args.video_id, output_dir=args.output_dir, quality=args.quality)
        print(f"Baixado em: {path}")


if __name__ == "__main__":
    _cli()
