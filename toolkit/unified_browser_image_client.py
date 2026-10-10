"""Compatibilidade do editor com a Busca de Imagens Unificada enviada pelo usuário.

O editor antigo espera quatro clientes com a interface:
    search_photos_all(...)
    download_photo(...)

Este módulo reaproveita diretamente os quatro mecanismos da pasta
`toolkit/unified_images/engines/`, mas os executa dentro do
`PersistentBrowserSearchWorker` já existente no editor. Resultado:

* um Chromium por mecanismo;
* mesma aba para várias consultas;
* cada consulta usa somente os primeiros resultados pedidos;
* o chamador pode testar fallback Bing -> Brave -> Yandex -> Startpage;
* o download pode cair para a URL de thumbnail/proxy do MESMO resultado,
  sem buscar a segunda imagem do mesmo mecanismo.
"""
from __future__ import annotations

import importlib
import io
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import requests
from PIL import Image


_ENGINE_IMPORTS = {
    "bing": "unified_images.engines.bing_image_api",
    "brave": "unified_images.engines.brave_image_api",
    "yandex": "unified_images.engines.yandex_image_api",
    "startpage": "unified_images.engines.startpage_image_api",
}

_ENGINE_REFERERS = {
    "bing": "https://www.bing.com/",
    "brave": "https://search.brave.com/",
    "yandex": "https://yandex.com/",
    "startpage": "https://www.startpage.com/",
}

_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".svg"}
_ACCEPT = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"


class UnifiedBrowserImageClientError(RuntimeError):
    pass


@dataclass
class UnifiedPhoto:
    provider: str = ""
    title: str = ""
    description: str = ""
    alt: str = ""
    source_page: str = ""
    source_domain: str = ""
    original_url: str = ""
    thumbnail_url: str = ""
    proxy_url: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    query: str = ""
    raw: Dict[str, Any] | None = None

    @property
    def id(self) -> str:  # noqa: A003
        return self.original_url or self.thumbnail_url or self.proxy_url or self.title

    @property
    def sizes(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        if self.thumbnail_url:
            out["tiny"] = self.thumbnail_url
            out["small"] = self.thumbnail_url
        if self.original_url:
            out["original"] = self.original_url
        if self.proxy_url:
            out.setdefault("proxy", self.proxy_url)
        return out

    @property
    def author(self) -> str:
        return self.source_domain

    @property
    def url(self) -> str:
        return self.source_page

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "title": self.title,
            "description": self.description,
            "alt": self.alt,
            "source_page": self.source_page,
            "source_domain": self.source_domain,
            "original_url": self.original_url,
            "thumbnail_url": self.thumbnail_url,
            "proxy_url": self.proxy_url,
            "width": self.width,
            "height": self.height,
            "query": self.query,
            "raw": self.raw or {},
        }


def safe_filename(name: str, default: str = "imagem") -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:160] or default


def _http_urls(photo: UnifiedPhoto) -> List[str]:
    raw = photo.raw or {}
    candidates = [
        photo.original_url,
        photo.proxy_url,
        photo.thumbnail_url,
        raw.get("original_source_url"),
        raw.get("thumbnail_url"),
        raw.get("proxy_url"),
    ]
    out: List[str] = []
    for u in candidates:
        if not isinstance(u, str) or not u.strip():
            continue
        u = u.strip()
        if urlparse(u).scheme not in {"http", "https"}:
            continue
        if u not in out:
            out.append(u)
    return out


def _guess_extension(url: str, content_type: str) -> str:
    ext = Path(urlparse(url).path).suffix.lower()
    if ext in _EXTENSIONS:
        return ".jpg" if ext == ".jpeg" else ext
    ctype = content_type.split(";", 1)[0].strip().lower()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
        "image/avif": ".avif",
        "image/svg+xml": ".svg",
    }.get(ctype, ".jpg")


def _validate_image_bytes(body: bytes) -> None:
    if not body:
        raise ValueError("arquivo vazio")
    with Image.open(io.BytesIO(body)) as img:
        img.verify()


class UnifiedBrowserImageClient:
    """Base compatível com os quatro clientes antigos do editor."""

    def __init__(
        self,
        provider: str,
        *,
        headless: bool = True,
        browser_worker: Any | None = None,
        **_: Any,
    ) -> None:
        if provider not in _ENGINE_IMPORTS:
            raise ValueError(f"Provedor unificado desconhecido: {provider}")
        self.provider = provider
        self.headless = headless
        self.browser_worker = browser_worker
        self.session = requests.Session()
        self._searched_once = False
        self._engine = importlib.import_module(_ENGINE_IMPORTS[provider])

    # ---------- parâmetros específicos ----------
    def _bing_kwargs(self, max_images: int, filtros: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "limit": max(1, min(20, int(max_images))),
            "aspect": filtros.get("aspect"),
            "animated": bool(filtros.get("animated", False)),
            "transparent": bool(filtros.get("transparent", False)),
            "size": filtros.get("size"),
            "extra_qft": filtros.get("extra_qft"),
            "mkt": filtros.get("mkt", "pt-BR"),
            "orientation": filtros.get("orientation", "any"),
            "square_tolerance": float(filtros.get("square_tolerance", 0.1)),
            # A regra do editor quer somente confirmar/pegar a primeira
            # imagem. Não abrimos N detalhes do Bing.
            "click_details": bool(filtros.get("click_details", False)),
            "submit_method": filtros.get("submit_method", "auto"),
        }

    def _brave_kwargs(self, max_images: int, filtros: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "limit": max(1, min(20, int(max_images))),
            "source": filtros.get("source", "images"),
            "click_details": bool(filtros.get("click_details", False)),
            "orientation": filtros.get("orientation", "any"),
            "square_tolerance": float(filtros.get("square_tolerance", 0.1)),
        }

    def _yandex_kwargs(self, max_images: int, filtros: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "limit": max(1, min(20, int(max_images))),
            "orientation": filtros.get("orientation", "any"),
            "square_tolerance": float(filtros.get("square_tolerance", 0.1)),
        }

    def _startpage_kwargs(self, max_images: int, filtros: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "limit": max(1, min(20, int(max_images))),
            "language": filtros.get("language", "english"),
            "orientation": filtros.get("orientation", "any"),
            "square_tolerance": float(filtros.get("square_tolerance", 0.1)),
            "max_pages": int(filtros.get("max_pages", 1)),
        }

    # ---------- busca dentro de uma única aba persistente ----------
    async def _search_in_page(self, page: Any, context: Any, query: str, max_images: int, filtros: Dict[str, Any]) -> Dict[str, Any]:
        if self.provider == "bing":
            qft = self._engine.build_qft(
                aspect=filtros.get("aspect"),
                animated=bool(filtros.get("animated", False)),
                transparent=bool(filtros.get("transparent", False)),
                size=filtros.get("size"),
                extra_qft=filtros.get("extra_qft"),
            )
            url = self._engine.build_search_url(
                query, mkt=filtros.get("mkt", "pt-BR"), qft=qft,
            )
            if not self._searched_once:
                await page.goto(url, wait_until="domcontentloaded", timeout=self._engine.DEFAULT_TIMEOUT_MS)
                await page.wait_for_timeout(1200)
                method = "url"
            else:
                method = await self._engine.submit_new_search(
                    page, query,
                    submit_method=filtros.get("submit_method", "auto"),
                    fallback_url=url,
                )
                try:
                    await self._engine.ensure_qft_in_url(page, qft)
                except Exception:
                    pass
            results, stats = await self._engine.scrape_current_page(
                context, page, q=query, limit=max(1, min(20, max_images)),
                click_details=bool(filtros.get("click_details", False)),
                orientation=filtros.get("orientation", "any"),
                square_tolerance=float(filtros.get("square_tolerance", 0.1)),
            )
            self._searched_once = True
            return {"results": results, "search_url": page.url, "search_method": method, "scan_stats": stats}

        if self.provider == "brave":
            url = self._engine.build_search_url(query, source=filtros.get("source", "images"), offset=0)
            if not self._searched_once:
                await page.goto(url, wait_until="domcontentloaded", timeout=self._engine.DEFAULT_TIMEOUT_MS)
                await page.wait_for_timeout(1500)
                method = "url"
            else:
                method = await self._engine.submit_new_search(page, query)
            results, stats = await self._engine.scrape_current_page(
                context, page, q=query, limit=max(1, min(20, max_images)),
                click_details=bool(filtros.get("click_details", False)),
                orientation=filtros.get("orientation", "any"),
                square_tolerance=float(filtros.get("square_tolerance", 0.1)),
                policy=None,
            )
            self._searched_once = True
            return {"results": results, "search_url": page.url, "search_method": method, "scan_stats": stats}

        if self.provider == "yandex":
            url = self._engine.build_search_url(query)
            if not self._searched_once:
                await page.goto(url, wait_until="domcontentloaded", timeout=self._engine.DEFAULT_TIMEOUT_MS)
                await page.wait_for_timeout(1000)
                method = "url"
            else:
                method = await self._engine.submit_new_search(page, query)
            results, stats = await self._engine.collect_yandex_results(
                page,
                max(1, min(20, max_images)),
                orientation=filtros.get("orientation", "any"),
                square_tolerance=float(filtros.get("square_tolerance", 0.1)),
            )
            self._searched_once = True
            return {"results": results, "search_url": page.url, "search_method": method, "scan_stats": stats}

        if self.provider == "startpage":
            language = filtros.get("language", "english")
            url = self._engine.build_url(query, language=language)
            if not self._searched_once:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await self._engine.wait_for_startpage_ready(page, timeout_ms=180_000)
                await page.wait_for_timeout(1000)
                method = "url"
            else:
                method = await self._engine.submit_new_search(
                    page, query,
                    submit_method=filtros.get("submit_method", "auto"),
                    fallback_url=url,
                )
            result = await self._engine.search(
                page, context,
                query=query,
                limit=max(1, min(20, max_images)),
                click=False,
                download=False,
                inspect_sources=False,
                language=language,
                orientation=filtros.get("orientation", "any"),
                square_tolerance=float(filtros.get("square_tolerance", 0.1)),
                max_pages=int(filtros.get("max_pages", 1)),
                navigate=False,
            )
            self._searched_once = True
            return {"results": result.get("results", []), "search_url": page.url, "search_method": method, "scan_stats": result.get("scan_stats", {})}

        raise UnifiedBrowserImageClientError(f"Provedor sem implementação: {self.provider}")

    def _run_search(self, query: str, max_images: int, filtros: Dict[str, Any]) -> Dict[str, Any]:
        if self.browser_worker is None:
            # Compatibilidade para quem instancia os clientes diretamente fora
            # do editor. O editor sempre injeta o worker persistente abaixo.
            # Mantemos esse caminho isolado para não alterar o comportamento de
            # consumidores antigos enquanto a nova integração assume o fluxo do site.
            try:
                legacy_modules = {
                    "bing": "bing_image_api",
                    "brave": "brave_image_api",
                    "yandex": "yandex_image_api",
                    "startpage": "startpage_image_api",
                }
                legacy = importlib.import_module(legacy_modules[self.provider])
                if self.provider == "startpage":
                    async def _legacy_startpage():
                        async with legacy.browser_session(headless=self.headless) as manager:
                            page = await manager.new_page()
                            return await legacy.search(page, manager.context, query=query, limit=max_images, click=True, download=False, inspect_sources=False)
                    import asyncio
                    return asyncio.run(_legacy_startpage())
                import asyncio
                fn = getattr(legacy, "search_images_browser", None) or getattr(legacy, "search_images", None)
                if fn is None:
                    raise RuntimeError("cliente legado sem função de busca")
                kwargs = {"q" if self.provider in {"bing", "brave"} else "query": query, "limit": max_images, "headless": self.headless, "download": False}
                if self.provider == "brave":
                    kwargs["click_details"] = False
                if self.provider == "yandex":
                    kwargs["inspect_sources"] = False
                return asyncio.run(fn(**kwargs))
            except Exception as exc:  # noqa: BLE001
                raise UnifiedBrowserImageClientError(
                    f"Falha buscando {query!r} no {self.provider}: {exc}"
                ) from exc
        try:
            return self.browser_worker.run(
                lambda page, context: self._search_in_page(page, context, query, max_images, filtros),
                timeout=240,
            )
        except Exception as exc:  # noqa: BLE001
            raise UnifiedBrowserImageClientError(
                f"Falha buscando {query!r} no {self.provider}: {exc}"
            ) from exc

    def search_images(self, query: str, max_images: int = 5, **filtros: Any) -> List[UnifiedPhoto]:
        if not query or not query.strip():
            raise UnifiedBrowserImageClientError("Termo de busca vazio.")
        payload = self._run_search(query.strip(), max_images, filtros)
        photos: List[UnifiedPhoto] = []
        for raw in payload.get("results", []) or []:
            raw = dict(raw or {})
            photos.append(
                UnifiedPhoto(
                    provider=self.provider,
                    title=str(raw.get("title") or raw.get("description") or raw.get("alt") or ""),
                    description=str(raw.get("description") or raw.get("title") or ""),
                    alt=str(raw.get("alt") or ""),
                    source_page=str(raw.get("source_page") or ""),
                    source_domain=str(raw.get("source_domain") or raw.get("source") or ""),
                    original_url=str(raw.get("original_url") or raw.get("original_source_url") or ""),
                    thumbnail_url=str(raw.get("thumbnail_url") or ""),
                    proxy_url=str(raw.get("proxy_url") or ""),
                    width=int(raw.get("width") or 0) or None,
                    height=int(raw.get("height") or 0) or None,
                    query=query.strip(),
                    raw=raw,
                )
            )
        return photos[: max(1, int(max_images))]

    def search_photos_all(self, query: str, max_pages: int = 1, max_images: Optional[int] = None) -> List[UnifiedPhoto]:
        return self.search_images(query, max_images=max_images or 5, max_pages=max_pages)

    def download_image(
        self,
        photo: UnifiedPhoto,
        output_dir: str = "imagens",
        filename: Optional[str] = None,
        overwrite: bool = False,
        **_: Any,
    ) -> str:
        urls = _http_urls(photo)
        if not urls:
            raise UnifiedBrowserImageClientError(f"Imagem sem URL para download: {photo.title!r}")

        os.makedirs(output_dir, exist_ok=True)
        if not filename:
            base = safe_filename(photo.title or photo.alt or f"{self.provider}_imagem")
            explicit_ext = ""
        else:
            clean_name = safe_filename(Path(filename).name or f"{self.provider}_imagem")
            base = Path(clean_name).stem or f"{self.provider}_imagem"
            explicit_ext = Path(clean_name).suffix.lower() if Path(clean_name).suffix.lower() in _EXTENSIONS else ""

        last_error: Optional[Exception] = None
        for url in urls:
            target_ext_hint = explicit_ext or _guess_extension(url, "")
            target = Path(output_dir) / f"{base}{target_ext_hint}"
            # O comportamento antigo do editor: não baixa duas vezes o mesmo
            # arquivo quando ele já existe e overwrite=False.
            if target.exists() and not overwrite:
                return str(target.resolve())
            try:
                response = self.session.get(
                    url,
                    headers={
                        "Referer": photo.source_page or _ENGINE_REFERERS[self.provider],
                        "Accept": _ACCEPT,
                    },
                    timeout=45,
                    stream=True,
                )
                response.raise_for_status()
                chunks = []
                if hasattr(response, "iter_content"):
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            chunks.append(chunk)
                    body = b"".join(chunks)
                else:
                    body = getattr(response, "content", b"")
                if not body:
                    raise ValueError("resposta vazia")
                content_type = getattr(response, "headers", {}).get("content-type", "") if hasattr(response, "headers") else ""
                ext = explicit_ext or _guess_extension(url, content_type)
                target = Path(output_dir) / f"{base}{ext}"
                if target.exists() and not overwrite:
                    return str(target.resolve())
                target.write_bytes(body)
                return str(target.resolve())
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
        raise UnifiedBrowserImageClientError(
            f"Falha baixando a primeira imagem de {self.provider}; últimas URLs tentadas: {urls}: {last_error}"
        )

    def download_photo(self, photo: UnifiedPhoto, output_dir: str = "imagens", filename: Optional[str] = None, overwrite: bool = False, **kwargs: Any) -> str:
        return self.download_image(photo, output_dir=output_dir, filename=filename, overwrite=overwrite, **kwargs)
