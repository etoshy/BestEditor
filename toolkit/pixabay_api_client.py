"""
pixabay_api_client.py
=======================

Cliente do Pixabay usando a **API oficial** (https://pixabay.com/api/),
no mesmo padrão do `pexels_api_client.py`: sem Chrome, com rotação
automática de uma ou mais chaves.

A chave é gratuita: peça em https://pixabay.com/api/docs/ (aparece
direto na própria página de documentação depois de logar, sem precisar
de aprovação). Rate limit padrão: 100 requisições/minuto POR CHAVE — bem
mais folgado que o do Pexels, mas o suporte a múltiplas chaves continua
útil se você processar volume alto.

Configuração (.env)
--------------------
    PIXABAY_API_KEYS=sua_chave_aqui
    # ou várias, separadas por vírgula:
    PIXABAY_API_KEYS=chave_um,chave_dois

Limitação: assim como a API oficial do Pexels, a API do Pixabay não
devolve descrição curada — só "tags" (palavras-chave separadas por
vírgula). Um título é gerado a partir das tags, e a descrição é buscada
via meta-tag da página pública do vídeo (melhor esforço, mesmo padrão
usado no Pexels).
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

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_keys import APIKeyPool, NoAvailableAPIKeyError, load_dotenv

API_BASE = "https://pixabay.com/api"
VIDEO_URL = f"{API_BASE}/videos/"

QUALITY_RANK = {"tiny": 0, "small": 1, "medium": 2, "large": 3}
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_META_DESCRIPTION_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"', re.IGNORECASE)


class PixabayAPIClientError(Exception):
    """Erro genérico do cliente (rede, parsing, chave inválida etc.)."""


@dataclass
class PixabayAPIVideo:
    id: str
    title: str
    tags: List[str]
    description: str
    url: str
    duration: int
    author: str
    thumbnail: str
    video_files: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def _sorted_files(self) -> List[Dict[str, Any]]:
        return sorted(self.video_files, key=lambda f: QUALITY_RANK.get(f.get("quality", "tiny"), 0))

    def best_file(self) -> Dict[str, Any]:
        files = self._sorted_files()
        if not files:
            raise PixabayAPIClientError(f"Nenhum arquivo de vídeo encontrado para {self.id}")
        return files[-1]

    def worst_file(self) -> Dict[str, Any]:
        files = self._sorted_files()
        if not files:
            raise PixabayAPIClientError(f"Nenhum arquivo de vídeo encontrado para {self.id}")
        return files[0]

    def file_by_quality(self, quality: str) -> Dict[str, Any]:
        for f in self.video_files:
            if f.get("quality") == quality:
                return f
        raise PixabayAPIClientError(
            f"Qualidade '{quality}' não disponível para o vídeo {self.id}. "
            f"Disponíveis: {sorted({f.get('quality') for f in self.video_files})}"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "tags": self.tags, "description": self.description,
            "url": self.url, "duration": self.duration, "author": self.author,
            "thumbnail": self.thumbnail, "video_files": self.video_files,
        }


class PixabayAPIClient:
    def __init__(
        self,
        api_keys: Optional[Union[str, List[str]]] = None,
        env_var: str = "PIXABAY_API_KEYS",
        dotenv_path: str = ".env",
        delay: float = 0.2,
        max_key_rotations: Optional[int] = None,
    ):
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

    def _request(self, params: dict) -> Dict[str, Any]:
        last_error: Optional[str] = None

        for _ in range(self.max_key_rotations):
            try:
                key = self.pool.current_key()
            except NoAvailableAPIKeyError as exc:
                raise PixabayAPIClientError(str(exc)) from exc

            resp = self.session.get(VIDEO_URL, params={**params, "key": key}, timeout=20)

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                retry_seconds = float(retry_after) if retry_after else None
                last_error = f"chave rate-limited (429)"
                self.pool.mark_rate_limited(key, retry_after_seconds=retry_seconds)
                continue

            if resp.status_code in (400, 401, 403):
                raise PixabayAPIClientError(
                    f"Chave de API inválida ou requisição rejeitada (status {resp.status_code}). "
                    f"Confira PIXABAY_API_KEYS no seu .env. Resposta: {resp.text[:200]}"
                )

            if resp.status_code != 200:
                raise PixabayAPIClientError(f"Falha na API do Pixabay (status {resp.status_code}): {resp.text[:300]}")

            try:
                return resp.json()
            except json.JSONDecodeError as exc:
                raise PixabayAPIClientError(f"Resposta não é um JSON válido: {exc}") from exc

        raise PixabayAPIClientError(f"Todas as chaves disponíveis bateram rate limit. Último erro: {last_error}")

    # ------------------------------------------------------------------ #
    # Busca
    # ------------------------------------------------------------------ #

    def search(
        self,
        query: str,
        page: int = 1,
        per_page: int = 20,
        video_type: Optional[str] = None,
        category: Optional[str] = None,
        orientation: Optional[str] = None,
        min_width: Optional[int] = None,
        min_height: Optional[int] = None,
        order: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Uma chamada de busca à API oficial. `per_page` entre 3 e 200.

        video_type: "film" | "animation"
        category:   ex: "nature", "business", "people"...
        orientation: usada aqui só por compatibilidade de chamada — a API
            do Pixabay não tem um filtro de orientação nativo pra vídeos
            (diferente da busca por scraping do toolkit), então esse
            parâmetro é ignorado silenciosamente se vier.
        order: "popular" | "latest"
        """
        params: Dict[str, Any] = {"q": query, "page": page, "per_page": max(3, min(per_page, 200))}
        if video_type:
            params["video_type"] = video_type
        if category:
            params["category"] = category
        if min_width:
            params["min_width"] = min_width
        if min_height:
            params["min_height"] = min_height
        if order:
            params["order"] = order
        return self._request(params)

    def search_all(
        self,
        query: str,
        max_pages: int = 10,
        per_page: int = 20,
        fetch_descriptions: bool = True,
        **filters: Any,
    ) -> List[PixabayAPIVideo]:
        """Pagina manualmente (a API do Pixabay não devolve um link de
        'próxima página' como a do Pexels) — para quando uma página vem
        vazia, ou quando já cobrimos o `totalHits` informado.

        fetch_descriptions=True (padrão): mesma lógica do Pexels — como a
        API não devolve descrição curada, busca a meta-tag `description`
        da página pública de cada vídeo (requisição HTTP simples, sem
        chave). Desligue com `fetch_descriptions=False` pra mais
        velocidade.
        """
        # 'orientation' não é um filtro real da API do Pixabay — não deixa
        # passar adiante pra não confundir com um parâmetro válido.
        filters.pop("orientation", None)

        all_videos: Dict[str, PixabayAPIVideo] = {}
        total_hits = None

        for page in range(1, max_pages + 1):
            raw = self.search(query=query, page=page, per_page=per_page, **filters)
            hits = raw.get("hits", [])
            total_hits = raw.get("totalHits", total_hits)

            for item in hits:
                video = self._parse_video(item)
                all_videos[video.id] = video

            if not hits or len(hits) < per_page:
                break
            if total_hits is not None and page * per_page >= total_hits:
                break
            time.sleep(self.delay)

        videos = list(all_videos.values())
        if fetch_descriptions:
            for video in videos:
                video.description = self._fetch_description(video.url)
                time.sleep(self.delay)

        return videos

    def get_video(self, video_id: Union[str, int], fetch_description: bool = True) -> PixabayAPIVideo:
        raw = self._request({"id": str(video_id)})
        hits = raw.get("hits", [])
        if not hits:
            raise PixabayAPIClientError(f"Vídeo com id={video_id} não encontrado.")
        video = self._parse_video(hits[0])
        if fetch_description:
            video.description = self._fetch_description(video.url)
        return video

    def _fetch_description(self, video_url: str, timeout: int = 10) -> str:
        """Busca a meta-tag `description` da página pública do vídeo, com
        uma requisição HTTP simples (sem chave de API). Nunca levanta
        exceção — se algo der errado, devolve string vazia.
        """
        if not video_url:
            return ""
        try:
            resp = self.session.get(
                video_url, headers={"User-Agent": _BROWSER_USER_AGENT, "Accept": "text/html"}, timeout=timeout,
            )
            if resp.status_code != 200:
                return ""
            match = _META_DESCRIPTION_RE.search(resp.text)
            return html.unescape(match.group(1)).strip() if match else ""
        except Exception:  # noqa: BLE001
            return ""

    # ------------------------------------------------------------------ #
    # Download
    # ------------------------------------------------------------------ #

    def download_video(
        self,
        video: Union[PixabayAPIVideo, Dict[str, Any], str, int],
        output_dir: str = "videos",
        quality: str = "best",
        filename: Optional[str] = None,
        chunk_size: int = 1024 * 1024,
        overwrite: bool = False,
    ) -> str:
        pv = self._resolve_video(video)

        if quality == "best":
            file_info = pv.best_file()
        elif quality == "worst":
            file_info = pv.worst_file()
        else:
            file_info = pv.file_by_quality(quality)

        link = file_info.get("url")
        if not link:
            raise PixabayAPIClientError(f"Arquivo de vídeo sem link: {file_info}")

        os.makedirs(output_dir, exist_ok=True)
        if not filename:
            q = file_info.get("quality", "video")
            filename = f"pixabay-{pv.id}-{q}.mp4"
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
        videos: List[Union[PixabayAPIVideo, Dict[str, Any], str, int]],
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

    def _resolve_video(self, video: Union[PixabayAPIVideo, Dict[str, Any], str, int]) -> PixabayAPIVideo:
        if isinstance(video, PixabayAPIVideo):
            return video
        if isinstance(video, dict):
            return self._parse_video(video)
        return self.get_video(video)

    @staticmethod
    def _parse_video(item: Dict[str, Any]) -> PixabayAPIVideo:
        video_id = str(item.get("id", ""))
        tags = [t.strip() for t in item.get("tags", "").split(",") if t.strip()]
        title = ", ".join(tags[:4]).capitalize() if tags else f"Video {video_id}"

        video_files = []
        for quality, info in (item.get("videos") or {}).items():
            if isinstance(info, dict) and info.get("url"):
                video_files.append({
                    "quality": quality, "url": info["url"],
                    "width": info.get("width"), "height": info.get("height"), "size": info.get("size"),
                })

        return PixabayAPIVideo(
            id=video_id,
            title=title,
            tags=tags,
            description="",  # a API oficial não fornece descrição curada
            url=item.get("pageURL", ""),
            duration=item.get("duration", 0),
            author=item.get("user", ""),
            thumbnail=(item.get("videos", {}).get("tiny", {}) or {}).get("url", ""),
            video_files=video_files,
            raw=item,
        )


# --------------------------------------------------------------------------- #
# CLI simples
# --------------------------------------------------------------------------- #

def _cli() -> None:
    parser = argparse.ArgumentParser(description="Cliente da API oficial do Pixabay (vídeos).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Busca e salva um JSON com os resultados.")
    p_search.add_argument("query")
    p_search.add_argument("--pages", type=int, default=1)
    p_search.add_argument("--per-page", type=int, default=20)
    p_search.add_argument("--out", default=None)

    p_dl = sub.add_parser("download", help="Baixa um vídeo pelo ID.")
    p_dl.add_argument("video_id")
    p_dl.add_argument("--output-dir", default="videos")
    p_dl.add_argument("--quality", default="best")

    args = parser.parse_args()
    client = PixabayAPIClient()

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
