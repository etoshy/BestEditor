"""
magnific_client.py
===================

Cliente não-oficial para o Magnific (magnific.com, do grupo Freepik), feito
para:
  1) Buscar vídeos usando o endpoint público de busca
     (https://www.magnific.com/api/videos), com os filtros da busca
     avançada (licença free/premium, IA gerada ou não, resolução, duração,
     fps, orientação);
  2) Rolar as páginas de resultado e devolver uma lista limpa e
     deduplicada de vídeos — diferente do Pexels/Pixabay, aqui a própria
     resposta da busca já traz os links de preview/download, sem precisar
     visitar uma página de detalhe separada;
  3) Baixar um vídeo específico, pegando o preview de maior resolução
     disponível no item.

Importante sobre qualidade e marca d'água
------------------------------------------
- Vídeos **grátis** (`premium: false`): o link de preview retornado
  (`previews[].url`) é um MP4 **sem marca d'água** ("clear"), com um
  token de acesso temporário — é a peça completa disponível publicamente.
- Vídeos **premium** (`premium: true`): o link de preview é sempre
  **com marca d'água** ("watermarked"/"magnific_watermarked"). O arquivo
  em resolução final sem marca d'água só é liberado dentro do site,
  mediante login e consumo de créditos — isso está fora do escopo deste
  cliente (não faz nenhum tipo de bypass de paywall). Por padrão, o
  cliente **recusa** baixar vídeos premium; para baixar mesmo assim o
  preview com marca d'água, passe `allow_watermarked=True`.

Uso rápido
----------
    from magnific_client import MagnificClient

    client = MagnificClient()

    # 1) Buscar (com filtros) e pegar várias páginas
    videos = client.search_all(
        query="dog",
        only_free=True,
        resolutions=["1080", "4k"],
        orientations=["horizontal"],
        max_pages=3,
    )

    # 2) Baixar o primeiro resultado (só funciona liso para vídeos free)
    client.download_video(videos[0], output_dir="videos")

Também dá pra usar via linha de comando (veja `python magnific_client.py --help`).
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

import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from browser_session import ChromeSession, BrowserResponse
from urllib.parse import urlencode
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains


# --------------------------------------------------------------------------- #
# Configuração básica
# --------------------------------------------------------------------------- #

SEARCH_URL = "https://www.magnific.com/api/videos"
SITE_BASE = "https://www.magnific.com"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://www.magnific.com/",
}

VALID_FPS = {"24", "25", "30", "60", "gt60"}
VALID_ORIENTATIONS = {"horizontal", "vertical", "square"}
VALID_RESOLUTIONS = {"720", "1080", "2k", "4k", "8k"}
VALID_AI_GENERATED = {"excluded", "only"}


class MagnificClientError(Exception):
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
    para erros transitórios. Erros "definitivos" (404, 403 etc.) são
    devolvidos imediatamente, sem retry.

    use_fetch=True: usa `session.fetch_api()` em vez de `session.request()`
    — importante para endpoints de API JSON (ver mesma explicação em
    pexels_client.py).
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


class WatermarkedDownloadError(MagnificClientError):
    """Levantado ao tentar baixar um vídeo premium sem `allow_watermarked=True`."""


# --------------------------------------------------------------------------- #
# Estrutura de dados de um vídeo
# --------------------------------------------------------------------------- #

@dataclass
class MagnificVideo:
    id: str
    name: str
    url: str  # link da página do vídeo no magnific.com
    quality: Optional[str] = None  # rótulo tipo "4K", "1080p"
    premium: bool = False
    duration: Optional[int] = None  # em segundos
    is_ai_generated: bool = False
    orientation: Optional[str] = None
    aspect_ratio: Optional[str] = None
    author: Optional[str] = None
    author_slug: Optional[str] = None
    thumbnail: Optional[str] = None
    thumbnail_large: Optional[str] = None
    credit_cost: Optional[int] = None
    download_url: Optional[str] = None  # melhor preview disponível
    watermarked: bool = False  # se o download_url tem marca d'água
    description: str = ""  # frase da meta-tag da página do vídeo (ver nota abaixo)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "quality": self.quality,
            "premium": self.premium,
            "duration": self.duration,
            "is_ai_generated": self.is_ai_generated,
            "orientation": self.orientation,
            "aspect_ratio": self.aspect_ratio,
            "author": self.author,
            "author_slug": self.author_slug,
            "thumbnail": self.thumbnail,
            "thumbnail_large": self.thumbnail_large,
            "credit_cost": self.credit_cost,
            "download_url": self.download_url,
            "watermarked": self.watermarked,
            "description": self.description,
        }


# --------------------------------------------------------------------------- #
# Cliente principal
# --------------------------------------------------------------------------- #

class MagnificClient:
    def __init__(self, session: Optional[ChromeSession] = None, delay: float = 0.5):
        """
        session: permite reaproveitar uma sessão Chrome já configurada.
        delay:   pausa (em segundos) entre requisições.
        """
        self.session = session or ChromeSession(headers=DEFAULT_HEADERS)
        self.delay = delay

    # ------------------------------------------------------------------ #
    # Navegação real no Magnific (integrado da fonte enviada)
    # ------------------------------------------------------------------ #
    def build_search_url(self, term: str) -> str:
        params = {"format": "search", "last_filter": "type", "last_value": "video", "query": term, "type": "video"}
        return f"{SITE_BASE}/search?" + urlencode(params)

    def open_search(self, term: str, wait_seconds: float = 3.0) -> str:
        """Abre a busca no Chrome visível antes de consultar a lista estruturada."""
        url = self.build_search_url(term)
        self.session.driver.get(url)
        time.sleep(wait_seconds)
        return self.session.driver.current_url

    def real_scroll(self, max_scrolls: int = 10, pause: float = 1.5) -> None:
        """Scroll real para carregar resultados lazy-load/infinite-scroll."""
        driver = self.session.driver
        try:
            body = driver.find_element(By.TAG_NAME, "body")
        except Exception:
            return
        previous_height = driver.execute_script("return document.body.scrollHeight")
        unchanged = 0
        for _ in range(max_scrolls):
            try:
                ActionChains(driver).scroll_by_amount(0, 700).perform()
            except Exception:
                body.send_keys(Keys.PAGE_DOWN)
            time.sleep(pause)
            current_height = driver.execute_script("return document.body.scrollHeight")
            unchanged = unchanged + 1 if current_height == previous_height else 0
            previous_height = current_height
            if unchanged >= 3:
                break

    # ------------------------------------------------------------------ #
    # Busca
    # ------------------------------------------------------------------ #

    def search(
        self,
        query: str,
        page: int = 1,
        locale: str = "en",
        only_free: bool = False,
        only_premium: bool = False,
        ai_generated: Optional[str] = None,  # "excluded" | "only"
        resolutions: Optional[List[str]] = None,  # ["720","1080","2k","4k","8k"]
        duration_from: Optional[int] = None,
        duration_to: Optional[int] = None,
        fps: Optional[List[str]] = None,  # ["24","25","30","60","gt60"]
        orientations: Optional[List[str]] = None,  # ["horizontal","vertical","square"]
    ) -> List[MagnificVideo]:
        """Busca UMA página de resultados e devolve a lista de MagnificVideo
        já parseada. Todos os filtros são opcionais.
        """
        params = self._build_params(
            query=query,
            page=page,
            locale=locale,
            only_free=only_free,
            only_premium=only_premium,
            ai_generated=ai_generated,
            resolutions=resolutions,
            duration_from=duration_from,
            duration_to=duration_to,
            fps=fps,
            orientations=orientations,
        )

        resp = _request_with_retry(self.session, "GET", SEARCH_URL, params=params, timeout=20, use_fetch=True)
        if resp.status_code != 200:
            raise MagnificClientError(
                f"Falha na busca (status {resp.status_code}): {resp.text[:300]}"
            )
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise MagnificClientError(f"Resposta não é um JSON válido: {exc}") from exc

        items = data.get("items", [])
        return [self._parse_item(item, locale=locale) for item in items]

    def search_all(
        self,
        query: str,
        max_pages: int = 10,
        stop_when_empty: bool = True,
        **filters: Any,
    ) -> List[MagnificVideo]:
        """Rola várias páginas de resultado e devolve uma lista única,
        deduplicada por ID.

        max_pages:       teto de segurança de páginas a percorrer.
        stop_when_empty: para assim que uma página vier vazia.
        filters:         mesmos filtros aceitos por `search()`.
        """
        all_videos: Dict[str, MagnificVideo] = {}

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
        video: Union[MagnificVideo, Dict[str, Any]],
        output_dir: str = "videos",
        filename: Optional[str] = None,
        chunk_size: int = 1024 * 1024,
        overwrite: bool = False,
        allow_watermarked: bool = False,
    ) -> str:
        """Baixa um vídeo para o disco.

        video: um MagnificVideo (de search_all) ou um dict (ex: to_dict()).

        Por padrão, recusa baixar vídeos marcados como `premium` (que só
        têm preview com marca d'água disponível publicamente). Passe
        `allow_watermarked=True` para baixar mesmo assim o preview
        com marca d'água.

        Retorna o caminho completo do arquivo salvo.
        """
        mv = self._resolve_video(video)

        if not mv.download_url:
            raise MagnificClientError(f"Vídeo {mv.id} não tem nenhum link de preview/download.")

        if mv.watermarked and not allow_watermarked:
            raise WatermarkedDownloadError(
                f"O vídeo {mv.id} ('{mv.name}') é premium e só tem preview COM marca "
                "d'água disponível publicamente. Passe allow_watermarked=True para "
                "baixar esse preview mesmo assim, ou escolha um vídeo grátis "
                "(premium=False) para obter o arquivo sem marca d'água."
            )

        if not mv.description and mv.url:
            mv.description = self._fetch_description(mv.url)

        os.makedirs(output_dir, exist_ok=True)

        if not filename:
            suffix = "_watermarked" if mv.watermarked else ""
            filename = f"{mv.id}{suffix}.mp4"
        filepath = os.path.join(output_dir, filename)

        if os.path.exists(filepath) and not overwrite:
            return filepath

        self.session.download(mv.download_url, filepath, timeout=120)

        time.sleep(self.delay)
        return filepath

    def download_many(
        self,
        videos: List[Union[MagnificVideo, Dict[str, Any]]],
        output_dir: str = "videos",
        overwrite: bool = False,
        allow_watermarked: bool = False,
        skip_errors: bool = True,
        on_progress=None,
    ) -> List[str]:
        """Baixa uma lista de vídeos em sequência. Por padrão, pula (com
        aviso) vídeos premium sem `allow_watermarked=True` em vez de
        interromper o lote inteiro; `on_progress(i, total, path_ou_None)`
        é chamado após cada tentativa.
        """
        paths = []
        total = len(videos)
        for i, v in enumerate(videos, start=1):
            try:
                path = self.download_video(
                    v,
                    output_dir=output_dir,
                    overwrite=overwrite,
                    allow_watermarked=allow_watermarked,
                )
                paths.append(path)
                if on_progress:
                    on_progress(i, total, path)
            except WatermarkedDownloadError as exc:
                if not skip_errors:
                    raise
                if on_progress:
                    on_progress(i, total, None)
                print(f"[aviso] pulado: {exc}")
        return paths

    # ------------------------------------------------------------------ #
    # Helpers internos
    # ------------------------------------------------------------------ #

    _META_DESCRIPTION_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"', re.IGNORECASE)

    def _fetch_description(self, video_url: str, timeout: int = 20) -> str:
        """Busca a meta-tag `description` da página pública do vídeo.

        No Magnific essa frase é gerada automaticamente pelo site (algo
        como "Download this free video of <nome> and explore millions of
        professional stock videos on Magnific.") — não é uma descrição
        autoral distinta do nome, mas é a única informação textual extra
        que o site expõe além do próprio nome. Melhor esforço: qualquer
        falha (rede, bloqueio, timeout) devolve string vazia, sem
        levantar exceção.
        """
        if not video_url:
            return ""
        try:
            resp = _request_with_retry(self.session, "GET", video_url, timeout=timeout, max_retries=1)
            if resp.status_code != 200:
                return ""
            match = self._META_DESCRIPTION_RE.search(resp.text)
            return html.unescape(match.group(1)).strip() if match else ""
        except Exception:  # noqa: BLE001 - melhor esforço, nunca quebra o download
            return ""

    def _resolve_video(self, video: Union[MagnificVideo, Dict[str, Any]]) -> MagnificVideo:
        if isinstance(video, MagnificVideo):
            return video
        if isinstance(video, dict):
            return MagnificVideo(
                id=str(video["id"]),
                name=video.get("name", ""),
                url=video.get("url", ""),
                quality=video.get("quality"),
                premium=bool(video.get("premium", False)),
                duration=video.get("duration"),
                is_ai_generated=bool(video.get("is_ai_generated", False)),
                orientation=video.get("orientation"),
                aspect_ratio=video.get("aspect_ratio"),
                author=video.get("author"),
                author_slug=video.get("author_slug"),
                thumbnail=video.get("thumbnail"),
                thumbnail_large=video.get("thumbnail_large"),
                credit_cost=video.get("credit_cost"),
                download_url=video.get("download_url"),
                watermarked=bool(video.get("watermarked", False)),
                description=video.get("description", ""),
            )
        raise MagnificClientError(f"Tipo de vídeo não suportado: {type(video)}")

    @staticmethod
    def _build_params(**kwargs: Any) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "format[search]": "1",
            "type[video]": "1",
            "locale": kwargs.get("locale", "en"),
            "term": kwargs["query"],
        }

        page = kwargs.get("page", 1)
        if page:
            params["page"] = page

        if kwargs.get("only_free"):
            params["license[free]"] = 1
        if kwargs.get("only_premium"):
            params["premium"] = 1

        ai_generated = kwargs.get("ai_generated")
        if ai_generated:
            if ai_generated not in VALID_AI_GENERATED:
                raise MagnificClientError(
                    f"ai_generated inválido: {ai_generated!r} (use {VALID_AI_GENERATED})"
                )
            params[f"filters[ai-generated][{ai_generated}]"] = 1

        resolutions = kwargs.get("resolutions")
        if resolutions:
            for res in resolutions:
                if res not in VALID_RESOLUTIONS:
                    raise MagnificClientError(
                        f"resolution inválida: {res!r} (use {VALID_RESOLUTIONS})"
                    )
                params[f"resolution[{res}]"] = 1

        duration_from = kwargs.get("duration_from")
        if duration_from is not None:
            params["duration[from]"] = int(duration_from)
        duration_to = kwargs.get("duration_to")
        if duration_to is not None:
            params["duration[to]"] = int(duration_to)

        fps = kwargs.get("fps")
        if fps:
            for f in fps:
                if f not in VALID_FPS:
                    raise MagnificClientError(f"fps inválido: {f!r} (use {VALID_FPS})")
            params["filters[fps][]"] = list(fps)

        orientations = kwargs.get("orientations")
        if orientations:
            for o in orientations:
                if o not in VALID_ORIENTATIONS:
                    raise MagnificClientError(
                        f"orientation inválida: {o!r} (use {VALID_ORIENTATIONS})"
                    )
            params["filters[orientations][]"] = list(orientations)

        return params

    @staticmethod
    def _best_preview(previews: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Escolhe o preview de maior largura entre os disponíveis com URL válida."""
        candidates = [p for p in (previews or []) if p.get("url")]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.get("width", 0))

    @classmethod
    def _parse_item(cls, item: Dict[str, Any], locale: str = "pt") -> MagnificVideo:
        thumbs = item.get("thumbnails", []) or []
        thumb_small = thumbs[0]["url"] if thumbs else item.get("poster")
        thumb_large = thumbs[-1]["url"] if thumbs else item.get("posterLarge")

        # A resposta do endpoint pode trazer videoSrc diretamente; caso
        # contrário, usamos o melhor preview disponível.
        best = cls._best_preview(item.get("previews", []))
        download_url = (best.get("url") if best else None) or item.get("videoSrc")
        watermarked = bool(download_url) and "watermarked" in download_url.lower()

        author = item.get("author", {}) or {}
        rel_url = item.get("url", "")
        full_url = f"{SITE_BASE}{rel_url}" if rel_url.startswith("/") else rel_url

        return MagnificVideo(
            id=str(item.get("id")),
            name=item.get("name", ""),
            url=full_url,
            quality=item.get("quality"),
            premium=bool(item.get("premium", False)),
            duration=item.get("duration"),
            is_ai_generated=bool(item.get("isAIGenerated", False)),
            orientation=item.get("nativeOrientation"),
            aspect_ratio=item.get("nativeAspectRatio"),
            author=author.get("name"),
            author_slug=author.get("slug"),
            thumbnail=thumb_small,
            thumbnail_large=thumb_large,
            credit_cost=item.get("creditCost"),
            download_url=download_url,
            watermarked=watermarked,
            raw=item,
        )


# --------------------------------------------------------------------------- #
# CLI simples (opcional) — útil para testar rapidamente pelo terminal
# --------------------------------------------------------------------------- #

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Buscar e baixar vídeos do Magnific (sem chave de API)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- search ---
    p_search = sub.add_parser("search", help="Buscar vídeos e listar resultados (JSON).")
    p_search.add_argument("query", help='Termo de busca, ex: "dog"')
    p_search.add_argument("--pages", type=int, default=1, help="Quantidade de páginas a buscar.")
    p_search.add_argument("--locale", default="pt")
    p_search.add_argument("--only-free", action="store_true")
    p_search.add_argument("--only-premium", action="store_true")
    p_search.add_argument("--ai-generated", choices=sorted(VALID_AI_GENERATED))
    p_search.add_argument("--resolution", action="append", dest="resolutions",
                           choices=sorted(VALID_RESOLUTIONS))
    p_search.add_argument("--duration-from", type=int)
    p_search.add_argument("--duration-to", type=int)
    p_search.add_argument("--fps", action="append", choices=sorted(VALID_FPS))
    p_search.add_argument("--orientation", action="append", dest="orientations",
                           choices=sorted(VALID_ORIENTATIONS))
    p_search.add_argument("--out", help="Salvar resultado em um arquivo .json")

    # --- download ---
    p_dl = sub.add_parser("download", help="Baixar um vídeo específico (pelo id, via nova busca).")
    p_dl.add_argument("query", help="Termo de busca para localizar o vídeo (necessário nesta API).")
    p_dl.add_argument("video_id", help="ID numérico do vídeo (visto no campo 'id' da busca).")
    p_dl.add_argument("--output-dir", default="videos")
    p_dl.add_argument("--allow-watermarked", action="store_true")

    args = parser.parse_args()
    client = MagnificClient()

    if args.command == "search":
        filters = dict(
            locale=args.locale,
            only_free=args.only_free,
            only_premium=args.only_premium,
            ai_generated=args.ai_generated,
            resolutions=args.resolutions,
            duration_from=args.duration_from,
            duration_to=args.duration_to,
            fps=args.fps,
            orientations=args.orientations,
        )
        filters = {k: v for k, v in filters.items() if v not in (None, False, [])}

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
        # A API do Magnific não expõe um endpoint de "detalhe por ID", então
        # localizamos o vídeo buscando pelo termo e filtrando pelo ID.
        videos = client.search_all(query=args.query, max_pages=5)
        match = next((v for v in videos if v.id == str(args.video_id)), None)
        if not match:
            raise MagnificClientError(
                f"Não achei o vídeo id={args.video_id} buscando por {args.query!r}. "
                "Tente aumentar o número de páginas ou refinar o termo de busca."
            )
        path = client.download_video(
            match, output_dir=args.output_dir, allow_watermarked=args.allow_watermarked
        )
        print(f"Baixado em: {path}")


if __name__ == "__main__":
    _cli()
