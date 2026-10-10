# -*- coding: utf-8 -*-
"""
STARTPAGE IMAGES — Browser API / Tester

Pacote em formato igual ao Brave: um único script + requirements + README.
Usa a implementação funcional de navegação/Anubis e extração do payload
AppSerpImages do Startpage, com catálogo opcional das páginas de origem.

Não tenta contornar a verificação do Startpage.

NOVO (trazido do Brave):
- VÁRIAS BUSCAS NA MESMA ABA (--batch / /api/images/batch): a 1ª busca abre a
  URL; as seguintes localizam input#q, apagam o termo antigo, digitam o novo e
  enviam com ENTER ou clicando na lupa (button.search-btn).
- FILTRO DE PROPORÇÃO (orientation): any | horizontal | vertical | square,
  medido pelo width/height que o próprio Startpage entrega. O `limit` conta só
  as imagens que passam no filtro; se faltar, lê as próximas páginas.
"""

from __future__ import annotations



import argparse
import asyncio
import json
import mimetypes
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn


# --- models ---
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class ImageResult:
    source: str
    rank: int
    title: str = ""
    description: str = ""
    source_page: str = ""
    original_url: str = ""
    thumbnail_url: str = ""
    detail_url: str = ""
    width: int | None = None
    height: int | None = None
    media_id: str | None = None
    source_domain: str = ""
    clicked: bool = False
    downloaded: bool = False
    download_path: str = ""
    error: str = ""
    thumb_width: int | None = None
    thumb_height: int | None = None
    aspect_ratio: float | None = None
    orientation: str | None = None
    orientation_source: str | None = None
    query: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

# --- browser ---

from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)


class BrowserManager:
    def __init__(self, *, headless: bool = False, timeout_ms: int = 30000):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._pw: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None

    async def start(self) -> BrowserContext:
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )
        self.context = await self.browser.new_context(
            locale="pt-BR",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7"},
        )
        return self.context

    async def stop(self) -> None:
        if self.context:
            await self.context.close()
            self.context = None
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self._pw:
            await self._pw.stop()
            self._pw = None

    async def new_page(self) -> Page:
        if not self.context:
            raise RuntimeError("BrowserManager não iniciado.")
        page = await self.context.new_page()
        page.set_default_timeout(self.timeout_ms)
        return page


@asynccontextmanager
async def browser_session(
    *, headless: bool = False, timeout_ms: int = 30000
) -> AsyncIterator[BrowserManager]:
    manager = BrowserManager(headless=headless, timeout_ms=timeout_ms)
    await manager.start()
    try:
        yield manager
    finally:
        await manager.stop()


async def wait_for_startpage_ready(
    page: Page,
    *,
    timeout_ms: int = 180_000,
    poll_ms: int = 500,
) -> dict:
    """Wait for Startpage's client-side verification to finish.

    Startpage/Anubis can navigate the same tab while the verification page is
    running. During that transition Playwright may destroy the JavaScript
    execution context between an evaluate call and its completion. This
    helper treats that race as normal: it waits for the navigation to settle
    and simply retries the readiness check. It does not bypass the challenge.
    """
    import time
    from playwright.async_api import Error as PlaywrightError

    start = time.monotonic()
    last_state: dict = {"ready": False, "challenge": True, "status": ""}

    while True:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        remaining_ms = timeout_ms - elapsed_ms
        if remaining_ms <= 0:
            raise TimeoutError(
                "Startpage não liberou a página dentro do tempo limite. "
                f"Último status: {last_state.get('status', '')!r}"
            )

        try:
            # Give Playwright a chance to finish an in-flight navigation.
            try:
                await page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=min(1500, max(250, remaining_ms)),
                )
            except Exception:
                pass

            state = await page.evaluate(
                """
                () => {
                    const challenge =
                        document.querySelector('#anubis-main') ||
                        document.querySelector('#anubis_challenge') ||
                        document.querySelector('#progress[role=\"progressbar\"]');

                    const status =
                        document.querySelector('#status')?.innerText ||
                        document.querySelector('.sp-message')?.innerText ||
                        '';

                    const ready =
                        !!document.querySelector('.search-home-inner') ||
                        !!document.querySelector('input[name=\"query\"]') ||
                        !!document.querySelector('#search') ||
                        !!document.querySelector('[data-testid*=\"image\"]') ||
                        !!document.querySelector('.images');

                    return {
                        challenge: !!challenge && !ready,
                        ready,
                        status,
                        url: location.href
                    };
                }
                """
            )
            last_state = state if isinstance(state, dict) else last_state

            if state.get("ready"):
                return state

        except PlaywrightError as exc:
            # Navigation can destroy the execution context between the
            # navigation and evaluate(). This is expected during Anubis.
            if "Execution context was destroyed" not in str(exc) and \
               "most likely because of a navigation" not in str(exc):
                raise

        except Exception:
            # A transient navigation/context replacement should not abort the
            # whole search. The next iteration checks the new document.
            pass

        await page.wait_for_timeout(min(poll_ms, max(50, remaining_ms)))


# --- downloader ---

import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import BrowserContext


def safe_filename(name: str, default: str = "imagem") -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:160] or default


async def download_url(
    context: BrowserContext,
    url: str,
    *,
    out_dir: Path,
    prefix: str,
    title: str,
) -> tuple[bool, str, str]:
    if not url:
        return False, "", "URL original vazia"

    out_dir.mkdir(parents=True, exist_ok=True)
    clean_title = safe_filename(title or "imagem")
    path = urlparse(url).path
    ext = Path(path).suffix.lower()

    allowed = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".svg"}
    if ext not in allowed:
        ext = ""

    target = out_dir / f"{prefix}_{clean_title}{ext}"

    try:
        response = await context.request.get(
            url,
            timeout=45_000,
            headers={
                "Referer": "https://www.startpage.com/",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
        )
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status}")

        body = await response.body()
        content_type = response.headers.get("content-type", "").split(";")[0].strip()

        if not ext:
            ext = mimetypes.guess_extension(content_type) or ".bin"
            target = out_dir / f"{prefix}_{clean_title}{ext}"

        target.write_bytes(body)
        return True, str(target.resolve()), ""

    except Exception as exc:
        return False, "", str(exc)

# --- startpage implementation ---

import html as html_lib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlparse

from playwright.async_api import BrowserContext, Page



SOURCE_NAME = "startpage_images"
BASE_URL = "https://www.startpage.com"
SEARCH_URL = BASE_URL + "/sp/search"



def _normalize_startpage_url(value: str | None) -> str:
    if not value:
        return ""
    value = str(value).strip()
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("/"):
        return "https://www.startpage.com" + value
    return value


def build_url(
    query: str,
    *,
    language: str = "english",
    cat: str = "images",
    page_no: int = 1,
) -> str:
    # Startpage documents /sp/search?query=%s for browser search strings and
    # supports the images category.
    params = {
        "query": query,
        "cat": cat,
        "language": language,
    }
    if page_no and page_no > 1:
        params["page"] = str(int(page_no))
    return f"{SEARCH_URL}?{urlencode(params)}"


def extract_react_object(source_html: str) -> dict[str, Any]:
    """
    Current Startpage result pages render their result payload through:
      React.createElement(UIStartpage.AppSerpImages, {...})
    We extract the balanced JS object and parse it as JSON.

    This follows the result structure documented/used by SearXNG:
      render.presenter.regions.mainline
    """
    marker = "React.createElement(UIStartpage.AppSerpImages,"
    start = source_html.find(marker)
    if start < 0:
        return {}

    brace = source_html.find("{", start)
    if brace < 0:
        return {}

    depth = 0
    in_string = False
    escape = False
    quote_char = ""

    for i in range(brace, len(source_html)):
        ch = source_html[i]

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote_char:
                in_string = False
            continue

        if ch in ('"', "'"):
            in_string = True
            quote_char = ch
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = source_html[brace : i + 1]
                try:
                    value = json.loads(html_lib.unescape(raw))
                    return value if isinstance(value, dict) else {}
                except Exception:
                    return {}

    return {}


def walk_image_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    regions = (
        payload.get("render", {})
        .get("presenter", {})
        .get("regions", {})
    )

    found: list[dict[str, Any]] = []

    for group in regions.get("mainline", []) or []:
        display_type = str(group.get("display_type", ""))
        if "images" not in display_type.lower():
            continue

        for item in group.get("results", []) or []:
            if not isinstance(item, dict):
                continue
            if not item.get("altClickUrl") and not item.get("rawImageUrl"):
                continue
            found.append(item)

    return found




# ---------------------------------------------------------------------------
# OPTIONAL SOURCE-SITE / OG / ALL-IMAGES LAYER
# ---------------------------------------------------------------------------

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".bmp", ".avif", ".svg", ".jfif", ".tif", ".tiff"
}


def _abs_url(base: str, value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if value.startswith("//"):
        return "https:" + value
    return urljoin(base, value)


def _largest_srcset(srcset: str | None) -> str | None:
    if not srcset:
        return None

    candidates = []
    for item in srcset.split(","):
        parts = item.strip().split()
        if not parts:
            continue

        score = 0.0
        if len(parts) > 1:
            m = re.match(r"(\d+(?:\.\d+)?)w", parts[1])
            if m:
                score = float(m.group(1))
            else:
                m = re.match(r"(\d+(?:\.\d+)?)x", parts[1])
                if m:
                    score = float(m.group(1)) * 1000.0

        candidates.append((score, parts[0]))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return candidates[0][1]


async def inspect_source_page(
    context: BrowserContext,
    source_url: str,
    *,
    max_images: int = 500,
) -> dict[str, Any]:
    """
    Abre a página original e monta um catálogo.

    Coleta:
      - og:image
      - og:image:url
      - og:image:secure_url
      - twitter:image
      - twitter:image:src
      - JSON-LD image/thumbnailUrl/contentUrl
      - srcset
      - data-original / data-src / data-lazy-src
      - <img>
      - links diretos para imagens

    Não tenta contornar desafios do site de origem.
    """
    page = await context.new_page()
    page.set_default_timeout(25000)

    result = {
        "source_page": source_url,
        "og": {},
        "images": [],
        "image_count": 0,
        "error": None,
    }

    try:
        await page.goto(
            source_url,
            wait_until="domcontentloaded",
            timeout=35000,
        )
        await page.wait_for_timeout(1000)

        # Dispara lazy loading.
        for _ in range(10):
            try:
                await page.mouse.wheel(0, 1200)
            except Exception:
                pass
            await page.wait_for_timeout(350)

        # OG / Twitter.
        meta = await page.locator("meta").evaluate_all(
            """
            els => els.map(m => ({
                property: m.getAttribute('property') || '',
                name: m.getAttribute('name') || '',
                content: m.getAttribute('content') || ''
            })).filter(x => x.content)
            """
        )

        for m in meta:
            key = (
                m["property"] or m["name"] or ""
            ).strip().lower()

            if key in {
                "og:image",
                "og:image:url",
                "og:image:secure_url",
                "twitter:image",
                "twitter:image:src",
            }:
                val = _abs_url(page.url, m["content"])
                if val:
                    result["og"][key] = val

        images = []
        seen = set()

        def add_image(
            value: str | None,
            kind: str,
            *,
            alt: str = "",
            title: str = "",
            width: int = 0,
            height: int = 0,
        ):
            if not value:
                return

            absolute = _abs_url(page.url, value)

            if not absolute or absolute.startswith(
                ("data:", "blob:", "javascript:")
            ):
                return

            key = absolute.split("#", 1)[0]

            if key in seen:
                return

            seen.add(key)

            path_name = Path(urlparse(key).path).name

            images.append(
                {
                    "index": len(images) + 1,
                    "name": path_name,
                    "url": key,
                    "kind": kind,
                    "alt": alt or "",
                    "title": title or "",
                    "width": width or 0,
                    "height": height or 0,
                }
            )

        # OG items ficam primeiro no catálogo.
        for key, value in result["og"].items():
            add_image(value, key)

        # JSON-LD.
        jsonld = await page.locator(
            'script[type="application/ld+json"]'
        ).evaluate_all(
            "els => els.map(x => x.textContent || '')"
        )

        def walk(value):
            if isinstance(value, dict):
                for key, val in value.items():
                    low = str(key).lower()

                    if low in {
                        "image",
                        "thumbnailurl",
                        "contenturl",
                    }:
                        if isinstance(val, str):
                            yield val
                        elif isinstance(val, list):
                            for item in val:
                                if isinstance(item, str):
                                    yield item
                                elif isinstance(item, dict):
                                    for k in (
                                        "url",
                                        "contentUrl",
                                        "contenturl",
                                    ):
                                        if isinstance(item.get(k), str):
                                            yield item[k]
                        elif isinstance(val, dict):
                            for k in (
                                "url",
                                "contentUrl",
                                "contenturl",
                            ):
                                if isinstance(val.get(k), str):
                                    yield val[k]

                    yield from walk(val)

            elif isinstance(value, list):
                for item in value:
                    yield from walk(item)

        for raw in jsonld:
            try:
                obj = json.loads(raw)
            except Exception:
                continue

            for value in walk(obj):
                add_image(value, "json-ld")

            if len(images) >= max_images:
                break

        # Todas as imagens DOM.
        img_data = await page.locator("img").evaluate_all(
            """
            els => els.map((img, i) => ({
              index: i,
              src: img.currentSrc || img.src || '',
              dataSrc: img.getAttribute('data-src') || '',
              dataOriginal: img.getAttribute('data-original') || '',
              dataLazy: img.getAttribute('data-lazy-src') || '',
              srcset: img.getAttribute('srcset') || '',
              alt: img.alt || '',
              title: img.title || '',
              width: img.naturalWidth || 0,
              height: img.naturalHeight || 0
            }))
            """
        )

        for img in img_data:
            add_image(
                _largest_srcset(img.get("srcset")),
                "srcset",
                alt=img.get("alt", ""),
                title=img.get("title", ""),
                width=img.get("width", 0),
                height=img.get("height", 0),
            )
            add_image(
                img.get("dataOriginal"),
                "data-original",
                alt=img.get("alt", ""),
                title=img.get("title", ""),
                width=img.get("width", 0),
                height=img.get("height", 0),
            )
            add_image(
                img.get("dataSrc"),
                "data-src",
                alt=img.get("alt", ""),
                title=img.get("title", ""),
                width=img.get("width", 0),
                height=img.get("height", 0),
            )
            add_image(
                img.get("dataLazy"),
                "data-lazy-src",
                alt=img.get("alt", ""),
                title=img.get("title", ""),
                width=img.get("width", 0),
                height=img.get("height", 0),
            )
            add_image(
                img.get("src"),
                "img",
                alt=img.get("alt", ""),
                title=img.get("title", ""),
                width=img.get("width", 0),
                height=img.get("height", 0),
            )

            if len(images) >= max_images:
                break

        # Links diretos para imagens.
        if len(images) < max_images:
            links = await page.locator(
                "a[href]"
            ).evaluate_all(
                "els => els.map(a => a.href || '').filter(Boolean)"
            )

            for href in links:
                if urlparse(href).path.lower().endswith(
                    tuple(IMAGE_EXTS)
                ):
                    add_image(
                        href,
                        "image-link",
                    )

                if len(images) >= max_images:
                    break

        result["images"] = images
        result["image_count"] = len(images)

    except Exception as exc:
        result["error"] = str(exc)

    finally:
        await page.close()

    return result


async def inspect_source_catalog(
    context: BrowserContext,
    results: list[ImageResult],
    *,
    max_images_per_site: int = 500,
) -> dict[str, Any]:
    """
    Visita cada site uma única vez e gera o catálogo de origem.
    """
    sites = []
    visited = set()

    for item in results:
        source_page = _normalize_startpage_url(
            (item.source_page or "").strip()
        )

        if not source_page:
            continue

        host = urlparse(source_page).netloc.lower()

        if (
            not host
            or host == "startpage.com"
            or host.endswith(".startpage.com")
            or source_page in visited
        ):
            continue

        visited.add(source_page)

        site = await inspect_source_page(
            context,
            source_page,
            max_images=max_images_per_site,
        )

        site["startpage_rank"] = item.rank
        site["startpage_title"] = item.title
        site["startpage_original_url"] = item.original_url

        sites.append(site)

    return {
        "site_count": len(sites),
        "sites": sites,
    }


async def download_source_catalog(
    context: BrowserContext,
    catalog: dict[str, Any],
    *,
    output_dir: str,
) -> None:
    """
    Baixa todas as imagens catalogadas nas páginas originais.
    """
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)

    global_index = 0

    for site_no, site in enumerate(
        catalog.get("sites", []),
        start=1,
    ):
        site_dir = base / f"site_{site_no:03d}"
        site_dir.mkdir(parents=True, exist_ok=True)

        for image in site.get("images", []):
            url = image.get("url")
            if not url:
                continue

            global_index += 1

            title = (
                image.get("title")
                or image.get("alt")
                or image.get("name")
                or f"imagem_{global_index:05d}"
            )

            clean = re.sub(
                r'[<>:"/\\|?*\x00-\x1f]',
                "_",
                str(title),
            )
            clean = re.sub(r"\s+", " ", clean).strip(" .")
            clean = clean[:160] or f"imagem_{global_index:05d}"

            suffix = Path(urlparse(url).path).suffix.lower()

            if suffix not in IMAGE_EXTS:
                suffix = ""

            ok, path, err = await download_url(
                context,
                url,
                out_dir=site_dir,
                prefix=f"{global_index:05d}",
                title=clean,
            )

            image["downloaded"] = ok
            image["download_path"] = path
            image["download_error"] = err or ""


# =============================================================================
# FILTRO DE PROPORÇÃO (igual ao do Brave / Bing)
# =============================================================================
MAX_LIMIT = 50
DEFAULT_MAX_PAGES = 5

ORIENTATIONS = ("any", "horizontal", "vertical", "square")
ORIENTATION_ALIASES = {
    "": "any", "any": "any", "qualquer": "any", "todas": "any", "todos": "any",
    "horizontal": "horizontal", "landscape": "horizontal", "wide": "horizontal",
    "paisagem": "horizontal", "deitada": "horizontal",
    "vertical": "vertical", "portrait": "vertical", "tall": "vertical",
    "retrato": "vertical", "em_pe": "vertical", "empe": "vertical",
    "square": "square", "quadrada": "square", "quadrado": "square", "quadro": "square",
}


def normalize_orientation(value: str | None) -> str:
    key = (value or "any").strip().lower().replace(" ", "_").replace("-", "_")
    if key not in ORIENTATION_ALIASES:
        raise ValueError(
            "orientation deve ser: any (qualquer), horizontal, vertical ou square (quadrada)."
        )
    return ORIENTATION_ALIASES[key]


def classify_orientation(
    width: int | float | None,
    height: int | float | None,
    square_tolerance: float = 0.1,
) -> tuple[str | None, float | None]:
    """
    Proporção = largura / altura.
      |proporção - 1| <= tolerância  -> square
      proporção > 1                  -> horizontal
      proporção < 1                  -> vertical
    """
    if not width or not height:
        return None, None
    ratio = float(width) / float(height)
    if abs(ratio - 1.0) <= square_tolerance:
        kind = "square"
    elif ratio > 1.0:
        kind = "horizontal"
    else:
        kind = "vertical"
    return kind, round(ratio, 3)


def _to_int(value: Any) -> int | None:
    try:
        n = int(float(value))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


async def read_dom_thumb_sizes(page: Page) -> dict[str, tuple[int, int]]:
    """
    Plano B para a proporção: tamanho natural das thumbnails já carregadas na
    página (URL absoluta -> (largura, altura)). Só é usado quando o payload do
    Startpage não traz width/height.
    """
    try:
        data = await page.locator("img").evaluate_all(
            """
            els => els.map(i => [i.currentSrc || i.src || '',
                                 i.naturalWidth || 0, i.naturalHeight || 0])
                      .filter(x => x[0] && x[1] > 1 && x[2] > 1)
            """
        )
    except Exception:
        return {}
    return {u: (int(w), int(h)) for u, w, h in data}


# =============================================================================
# LEITURA DA PÁGINA DE RESULTADOS ATUAL
# =============================================================================
def _is_transient_nav_error(exc: Exception) -> bool:
    msg = str(exc)
    return (
        "Execution context was destroyed" in msg
        or "most likely because of a navigation" in msg
    )


async def read_page_raw(page: Page) -> list[dict[str, Any]]:
    """Lê o payload AppSerpImages da página atual (com o fallback de DOM original)."""
    page_html = ""
    for _ in range(8):
        try:
            page_html = await page.content()
            break
        except Exception as exc:
            if not _is_transient_nav_error(exc):
                raise
            await page.wait_for_timeout(500)

    payload = extract_react_object(page_html)
    raw_results = walk_image_results(payload)

    # DOM fallback: tenta extrair links de imagem se o objeto React sumir
    # por mudança de markup.
    if not raw_results:
        raw_results = await page.locator("a").evaluate_all(
            """
            els => els.map(a => ({
                href: a.href || "",
                text: (a.innerText || "").trim(),
                img: a.querySelector("img")?.src || "",
                alt: a.querySelector("img")?.alt || ""
            })).filter(x =>
                x.href.includes("altClickUrl") ||
                x.href.startsWith("https://") && x.img
            ).slice(0, 30)
            """
        )
    return raw_results


def item_to_result(
    item: dict[str, Any],
    *,
    rank: int,
    thumb_sizes: dict[str, tuple[int, int]],
    square_tolerance: float,
) -> ImageResult | None:
    alt_click = str(item.get("altClickUrl") or "")
    raw_image = str(item.get("rawImageUrl") or "")
    thumb = str(item.get("thumbnailUrl") or "")

    # altClickUrl = link do resultado; rawImageUrl = imagem original;
    # thumbnailUrl = thumbnail via proxy.
    original = raw_image or alt_click
    if not original:
        return None

    title = html_lib.unescape(str(item.get("title") or ""))

    source_page = str(item.get("clickUrl") or item.get("pageUrl") or "")

    if alt_click.startswith("/"):
        alt_click = urljoin(BASE_URL, alt_click)
    if thumb.startswith("/"):
        thumb = urljoin(BASE_URL, thumb)

    # ---- proporção: 1) width/height do payload; 2) thumbnail na tela ----
    w, h = _to_int(item.get("width")), _to_int(item.get("height"))
    if w and h:
        size_src, tw, th = "startpage_meta", None, None
    else:
        w = h = None
        tw = th = None
        t = thumb_sizes.get(thumb)
        if t:
            size_src, tw, th = "thumbnail", t[0], t[1]
        else:
            size_src = None
    kind, ratio = classify_orientation(w or tw, h or th, square_tolerance)

    return ImageResult(
        source=SOURCE_NAME,
        rank=rank,
        title=title,
        description="",
        source_page=_normalize_startpage_url(source_page),
        original_url=original,
        thumbnail_url=thumb,
        detail_url=alt_click,
        width=w,
        height=h,
        source_domain=urlparse(source_page or original).netloc,
        thumb_width=tw,
        thumb_height=th,
        aspect_ratio=ratio,
        orientation=kind,
        orientation_source=size_src,
    )


async def _open_search_url(page: Page, query: str, language: str) -> str:
    url = build_url(query, language=language)
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    # Mantém o navegador vivo até o Startpage liberar a verificação (Anubis).
    await wait_for_startpage_ready(page, timeout_ms=180_000)
    await page.wait_for_timeout(1200)  # deixa o React assentar
    return url


async def collect_filtered_results(
    page: Page,
    *,
    query: str,
    language: str,
    limit: int,
    orientation: str = "any",
    square_tolerance: float = 0.1,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> tuple[list[ImageResult], dict[str, Any]]:
    """
    Lê a página de resultados ATUAL e aplica o filtro de proporção.

    `limit` = quantas imagens QUE PASSAM NO FILTRO queremos. Se a 1ª página não
    basta, carrega as próximas (`page=2`, `page=3`... até `max_pages`) e continua.
    Para quando completar o limit, quando uma página não trouxer nada novo
    ou quando acabar `max_pages`.
    """
    orientation = normalize_orientation(orientation)
    stats: dict[str, Any] = {
        "cards_scanned": 0,
        "filtered_out": 0,
        "unknown_orientation": 0,
        "pages_scanned": 0,
        "orientation_filter": orientation,
    }
    results: list[ImageResult] = []
    seen: set[str] = set()

    for page_no in range(1, max_pages + 1):
        if page_no > 1:
            await page.goto(
                build_url(query, language=language, page_no=page_no),
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await wait_for_startpage_ready(page, timeout_ms=180_000)
            await page.wait_for_timeout(1200)

        raw_items = await read_page_raw(page)
        stats["pages_scanned"] = page_no
        thumb_sizes = await read_dom_thumb_sizes(page) if orientation != "any" else {}

        new_items = 0
        for item in raw_items:
            if len(results) >= limit:
                break

            key = str(item.get("rawImageUrl") or item.get("altClickUrl") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            new_items += 1

            res = item_to_result(
                item,
                rank=len(results) + 1,
                thumb_sizes=thumb_sizes,
                square_tolerance=square_tolerance,
            )
            if res is None:
                continue
            stats["cards_scanned"] += 1

            if orientation != "any":
                if res.orientation is None:
                    stats["unknown_orientation"] += 1
                    stats["filtered_out"] += 1
                    continue  # não dá para confirmar -> não entra
                if res.orientation != orientation:
                    stats["filtered_out"] += 1
                    continue

            results.append(res)

        if len(results) >= limit:
            break
        if new_items == 0:  # a página não trouxe nada novo: acabou
            break

    if len(results) < limit:
        stats["warning"] = (
            f"Só {len(results)} de {limit} imagens"
            + (f" atenderam ao filtro '{orientation}'" if orientation != "any" else " encontradas")
            + f" (cards analisados: {stats['cards_scanned']}, "
            f"páginas: {stats['pages_scanned']})."
        )
    return results, stats


async def _click_result(
    page: Page,
    context: BrowserContext,
    result: ImageResult,
    grid_url: str,
) -> None:
    """Abre o resultado (clique real; se não achar o card, abre o altClickUrl)."""
    alt_click = result.detail_url
    if not alt_click:
        return
    try:
        candidate = page.locator(f'a[href="{alt_click}"]').first

        if await candidate.count():
            await candidate.scroll_into_view_if_needed()
            before = page.url
            try:
                async with page.expect_popup(timeout=5000) as popup_info:
                    await candidate.click(timeout=12000)
                popup = await popup_info.value
                try:
                    await popup.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                result.clicked = True
                result.detail_url = popup.url
                await popup.close()
            except Exception:
                await candidate.click(timeout=12000)
                await page.wait_for_timeout(500)
                result.clicked = True
                result.detail_url = page.url
                if page.url != before:
                    await page.goto(grid_url, wait_until="domcontentloaded", timeout=30000)
                    await wait_for_startpage_ready(page, timeout_ms=180_000)
        else:
            # O card pode não estar na página atual (ex.: veio de outra página
            # de resultados). Usa o altClickUrl conhecido numa aba separada.
            detail_page = await context.new_page()
            try:
                await detail_page.goto(alt_click, wait_until="domcontentloaded", timeout=30000)
                result.clicked = True
                result.detail_url = detail_page.url
            finally:
                await detail_page.close()
    except Exception as exc:
        result.error = f"click: {exc}"


async def search(
    page: Page,
    context: BrowserContext,
    *,
    query: str,
    limit: int = 3,
    click: bool = True,
    download: bool = False,
    output_dir: str = "tests/outputs/startpage_images",
    language: str = "english",
    inspect_sources: bool = False,
    download_mode: str = "startpage",
    source_max_images: int = 500,
    orientation: str = "any",
    square_tolerance: float = 0.1,
    max_pages: int = DEFAULT_MAX_PAGES,
    navigate: bool = True,
) -> dict[str, Any]:
    """
    Mantém o mecanismo comprovado de busca do ZIP fornecido pelo usuário.

      navigate=True   -> abre a URL de busca (comportamento original)
      navigate=False  -> a página JÁ está nos resultados (busca digitada no lote)
      inspect_sources -> abre sites de origem e cria catálogo JSON
      download_mode=startpage -> baixa a imagem original exposta pelo Startpage
      download_mode=source    -> baixa as imagens encontradas nas páginas fonte
      orientation / square_tolerance / max_pages -> filtro de proporção
    """
    if download_mode not in {"startpage", "source"}:
        raise ValueError("download_mode deve ser 'startpage' ou 'source'.")
    if not query.strip():
        raise ValueError("query não pode ficar vazia.")
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit deve ficar entre 1 e {MAX_LIMIT}.")
    if not 0 <= square_tolerance <= 0.5:
        raise ValueError("square_tolerance deve ficar entre 0 e 0.5.")
    if max_pages < 1:
        raise ValueError("max_pages deve ser >= 1.")
    orientation = normalize_orientation(orientation)

    grid_url = build_url(query, language=language)
    if navigate:
        await _open_search_url(page, query, language)

    typed_results, scan_stats = await collect_filtered_results(
        page,
        query=query,
        language=language,
        limit=limit,
        orientation=orientation,
        square_tolerance=square_tolerance,
        max_pages=max_pages,
    )

    if not typed_results:
        if orientation != "any" and scan_stats["cards_scanned"] > 0:
            raise RuntimeError(
                f"Nenhuma imagem '{orientation}' entre {scan_stats['cards_scanned']} "
                f"resultados analisados ({scan_stats['unknown_orientation']} sem tamanho "
                "conhecido). Tente outra proporção ou outro termo."
            )
        raise RuntimeError(
            "Nenhum resultado de imagem foi encontrado no Startpage. "
            "Se apareceu uma verificação, conclua-a no navegador e tente novamente."
        )

    for res in typed_results:
        res.query = query
        if click:
            await _click_result(page, context, res, grid_url)
        if download and download_mode == "startpage":
            ok, path, err = await download_url(
                context,
                res.original_url,
                out_dir=Path(output_dir),
                prefix=f"{res.rank:03d}",
                title=res.title,
            )
            res.downloaded = ok
            res.download_path = path
            if err:
                res.error = f"{res.error}; download: {err}".strip("; ")

    result: dict[str, Any] = {
        "source": SOURCE_NAME,
        "query": query,
        "search_url": page.url if not navigate else grid_url,
        "limit_requested": limit,
        "results_found": len(typed_results),
        "orientation_filter": orientation,
        "square_tolerance": square_tolerance,
        "scan_stats": scan_stats,
        "filters": (
            "Startpage Images: tamanho, cor, tipo e licença são documentados "
            "pela página de suporte; esta integração usa a busca normal e "
            "aplica a proporção (orientation) sobre os resultados."
        ),
        "results": [r.to_dict() for r in typed_results],
        "inspect_sources": inspect_sources,
        "download_mode": download_mode,
    }

    if inspect_sources or download_mode == "source":
        catalog = await inspect_source_catalog(
            context,
            typed_results,
            max_images_per_site=source_max_images,
        )
        result["source_catalog"] = catalog

        if download and download_mode == "source":
            await download_source_catalog(
                context,
                catalog,
                output_dir=str(Path(output_dir) / "sources"),
            )
            result["source_catalog"] = catalog

    return result


# =============================================================================
# NOVA BUSCA NA MESMA ABA (apaga, digita, ENTER ou clica na lupa)
# =============================================================================
# HTML do formulário do Startpage:
#   <form id="search" action="/sp/search" method="post">
#       <input id="q" name="query" ...>
#       <button class="search-btn" type="submit" aria-label="search button">
SEARCHBOX_SELECTOR = "form#search input[name='query']"
SUBMIT_SELECTOR = "form#search button.search-btn[type='submit']"
SUBMIT_METHODS = ("auto", "enter", "click")

_MARK_JS = "() => { window.__sp_batch_marker = true; return true; }"
_MARK_STILL_JS = "() => window.__sp_batch_marker === true"


async def _page_swapped(page: Page, timeout_ms: int) -> bool:
    """
    O formulário é POST para /sp/search, então a URL pode ficar igual. Em vez de
    comparar URL, deixamos uma marca em `window` antes de enviar: se ela sumiu
    (ou o contexto JS foi destruído), um documento novo foi carregado.
    """
    import time

    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        try:
            still = await page.evaluate(_MARK_STILL_JS)
            if not still:
                return True
        except Exception:
            return True  # contexto destruído = navegação em andamento
        await page.wait_for_timeout(200)
    return False


async def submit_new_search(
    page: Page,
    term: str,
    *,
    submit_method: str = "auto",
    fallback_url: str | None = None,
    typing_delay_ms: int = 35,
    settle_ms: int = 1200,
) -> str:
    """
    Faz uma nova busca na MESMA aba, como uma pessoa faria:

      1. localiza o campo  input#q (name="query");
      2. clica, apaga o texto antigo e digita o novo termo;
      3. envia:  submit_method="enter"  -> tecla ENTER
                 submit_method="click"  -> clica na lupa (button.search-btn)
                 submit_method="auto"   -> ENTER; se a página não mudar, clica na lupa;
      4. espera o Startpage liberar (verificação Anubis, se aparecer) e a nova grade.

    Retorna "searchbox:enter" / "searchbox:click" quando funcionou pelo campo,
    ou "url_fallback" se foi preciso navegar direto pela URL.
    """
    if submit_method not in SUBMIT_METHODS:
        raise ValueError("submit_method deve ser: auto, enter ou click.")

    try:
        await wait_for_startpage_ready(page, timeout_ms=180_000)

        # Fecha overlay que possa estar cobrindo o topo.
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(300)

        box = page.locator(SEARCHBOX_SELECTOR).first
        await box.wait_for(state="visible", timeout=15_000)

        # --- apagar o termo antigo ---
        await box.click()
        await box.fill("")
        if (await box.input_value()) != "":
            await box.press("ControlOrMeta+A")
            await box.press("Backspace")

        # --- digitar o novo termo ---
        await box.press_sequentially(term, delay=typing_delay_ms)
        if (await box.input_value()) != term:
            await box.fill(term)  # garante o texto exato

        # --- enviar: ENTER e/ou clique na lupa ---
        await page.evaluate(_MARK_JS)
        used = "enter"
        swapped = False
        if submit_method in ("auto", "enter"):
            await box.press("Enter")
            swapped = await _page_swapped(
                page, 8_000 if submit_method == "auto" else 20_000
            )
        if not swapped and submit_method in ("auto", "click"):
            submit = page.locator(SUBMIT_SELECTOR).first
            await submit.wait_for(state="visible", timeout=10_000)
            await submit.click(timeout=10_000)
            used = "click"
            swapped = await _page_swapped(page, 20_000)

        if not swapped:
            raise RuntimeError("A busca digitada não mudou a página.")

        # Pode aparecer a verificação do Startpage (não é contornada).
        await wait_for_startpage_ready(page, timeout_ms=180_000)
        await page.wait_for_timeout(settle_ms)  # deixa a grade estabilizar
        return f"searchbox:{used}"

    except Exception:
        # Fallback: navega direto pela URL para não derrubar o lote inteiro.
        await page.goto(
            fallback_url or build_url(term),
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await wait_for_startpage_ready(page, timeout_ms=180_000)
        await page.wait_for_timeout(1500)
        return "url_fallback"


# =============================================================================
# VÁRIAS BUSCAS EM SEQUÊNCIA (mesma aba)
# =============================================================================
def normalize_batch_queries(
    queries: list[Any],
    default_limit: int,
    default_orientation: str = "any",
) -> list[dict[str, Any]]:
    """
    Aceita ["termo", ...] ou
           [{"q": "termo", "limit": 10, "orientation": "vertical"}, ...]
    """
    default_orientation = normalize_orientation(default_orientation)
    out: list[dict[str, Any]] = []
    for item in queries:
        if isinstance(item, str):
            q, lim, ori = item.strip(), default_limit, default_orientation
        elif isinstance(item, dict):
            q = str(item.get("q", "")).strip()
            lim = int(item.get("limit") or default_limit)
            ori = normalize_orientation(item.get("orientation") or default_orientation)
        else:
            continue
        if not q:
            continue
        if lim < 1 or lim > MAX_LIMIT:
            raise ValueError(f"limit de '{q}' deve ficar entre 1 e {MAX_LIMIT}.")
        out.append({"q": q, "limit": lim, "orientation": ori})
    if not out:
        raise ValueError("Informe ao menos um termo de busca.")
    return out


async def search_images_batch(
    *,
    queries: list[Any],
    limit: int = 5,
    orientation: str = "any",
    square_tolerance: float = 0.1,
    click: bool = True,
    download: bool = False,
    download_mode: str = "startpage",
    inspect_sources: bool = False,
    source_max_images: int = 500,
    submit_method: str = "auto",
    max_pages: int = DEFAULT_MAX_PAGES,
    language: str = "english",
    headless: bool = False,
    output_dir: str = "startpage_batch_downloads",
    pause_between_ms: int = 1500,
) -> dict[str, Any]:
    """
    Várias buscas em sequência, TODAS na mesma aba/navegador.

    A 1ª busca abre a URL do Startpage. As seguintes reutilizam a página:
    apagam o input#q, digitam o novo termo e enviam com ENTER ou clicando na
    lupa (veja `submit_method`).
    """
    if submit_method not in SUBMIT_METHODS:
        raise ValueError("submit_method deve ser: auto, enter ou click.")
    if not 0 <= square_tolerance <= 0.5:
        raise ValueError("square_tolerance deve ficar entre 0 e 0.5.")
    plan = normalize_batch_queries(queries, limit, orientation)
    out = Path(output_dir)

    manager = BrowserManager(headless=headless, timeout_ms=30000)
    await manager.start()
    searches: list[dict[str, Any]] = []
    try:
        page = await manager.new_page()
        for n, item in enumerate(plan, start=1):
            q, lim, ori = item["q"], item["limit"], item["orientation"]
            entry: dict[str, Any] = {
                "index": n,
                "query": q,
                "limit_requested": lim,
                "orientation_filter": ori,
                "ok": False,
            }
            try:
                if n == 1:
                    entry["search_method"] = "url"
                else:
                    await page.wait_for_timeout(pause_between_ms)
                    entry["search_method"] = await submit_new_search(
                        page,
                        q,
                        submit_method=submit_method,
                        fallback_url=build_url(q, language=language),
                    )
                    try:  # confere o que ficou escrito no campo depois da busca
                        entry["query_on_page"] = await page.locator(
                            SEARCHBOX_SELECTOR
                        ).first.input_value()
                    except Exception:
                        pass

                result = await search(
                    page,
                    manager.context,
                    query=q,
                    limit=lim,
                    click=click,
                    download=download,
                    output_dir=str(out / f"{n:02d}_{safe_filename(q, f'busca_{n}')}"),
                    language=language,
                    inspect_sources=inspect_sources,
                    download_mode=download_mode,
                    source_max_images=source_max_images,
                    orientation=ori,
                    square_tolerance=square_tolerance,
                    max_pages=max_pages,
                    navigate=(n == 1),
                )
                entry.update(
                    ok=True,
                    search_url=result["search_url"],
                    results_found=result["results_found"],
                    scan_stats=result["scan_stats"],
                    results=result["results"],
                )
                if "source_catalog" in result:
                    entry["source_catalog"] = result["source_catalog"]
            except Exception as exc:
                # Uma busca que falha não derruba as próximas.
                entry["error"] = str(exc)
                entry["results_found"] = 0
                entry["results"] = []

            searches.append(entry)

        return {
            "ok": any(s["ok"] for s in searches),
            "engine": SOURCE_NAME,
            "mode": "batch",
            "submit_method": submit_method,
            "searches_requested": len(plan),
            "searches_ok": sum(1 for s in searches if s["ok"]),
            "total_results": sum(s["results_found"] for s in searches),
            "searches": searches,
        }
    finally:
        await manager.stop()


# =============================================================================
# PUBLIC API + TEST
# =============================================================================

app = FastAPI(
    title="Startpage Images Browser API",
    version="2.2.0",
)

ORIENTATION_DOC = "any (qualquer) | horizontal | vertical | square (quadrada)"


@app.get("/health")
async def health():
    return {"ok": True, "service": "startpage_images", "version": "2.2.0"}


@app.get("/api/images/search")
async def api_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=MAX_LIMIT),
    orientation: str = Query("any", description=ORIENTATION_DOC),
    square_tolerance: float = Query(0.1, ge=0, le=0.5),
    max_pages: int = Query(DEFAULT_MAX_PAGES, ge=1, le=20),
    click: bool = True,
    download: bool = False,
    inspect_sources: bool = False,
    download_mode: str = Query("startpage"),
    source_max_images: int = Query(500, ge=1, le=2000),
    headless: bool = False,
    output_dir: str = "startpage_downloads",
    json_path: str = "startpage_results.json",
):
    manager = BrowserManager(headless=headless, timeout_ms=30000)
    await manager.start()
    try:
        page = await manager.new_page()
        result = await search(
            page,
            manager.context,
            query=q,
            limit=limit,
            click=click,
            download=download,
            output_dir=output_dir,
            language="english",
            inspect_sources=inspect_sources,
            download_mode=download_mode,
            source_max_images=source_max_images,
            orientation=orientation,
            square_tolerance=square_tolerance,
            max_pages=max_pages,
        )
        Path(json_path).write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result["json_path"] = str(Path(json_path).resolve())
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        await manager.stop()


class BatchRequest(BaseModel):
    # ["gojo", "geto"]  ou  [{"q": "gojo", "limit": 10, "orientation": "vertical"}, ...]
    queries: list[Any]
    limit: int = Field(5, ge=1, le=MAX_LIMIT)
    orientation: str = "any"
    square_tolerance: float = Field(0.1, ge=0, le=0.5)
    max_pages: int = Field(DEFAULT_MAX_PAGES, ge=1, le=20)
    submit_method: str = Field("auto", pattern="^(auto|enter|click)$")
    click: bool = True
    download: bool = False
    download_mode: str = "startpage"
    inspect_sources: bool = False
    source_max_images: int = Field(500, ge=1, le=2000)
    headless: bool = False
    output_dir: str = "startpage_batch_downloads"
    pause_between_ms: int = Field(1500, ge=0, le=60_000)
    json_path: str = "startpage_batch_results.json"


async def _run_batch(json_path: str = "startpage_batch_results.json", **kwargs: Any):
    try:
        result = await search_images_batch(**kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    Path(json_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result["json_path"] = str(Path(json_path).resolve())
    return result


@app.get("/api/images/batch")
async def api_batch_get(
    q: list[str] = Query(..., description="Repita q= para cada termo"),
    limit: int = Query(5, ge=1, le=MAX_LIMIT),
    orientation: str = Query("any", description=ORIENTATION_DOC),
    square_tolerance: float = Query(0.1, ge=0, le=0.5),
    max_pages: int = Query(DEFAULT_MAX_PAGES, ge=1, le=20),
    submit_method: str = Query("auto", pattern="^(auto|enter|click)$"),
    click: bool = True,
    download: bool = False,
    download_mode: str = Query("startpage"),
    inspect_sources: bool = False,
    source_max_images: int = Query(500, ge=1, le=2000),
    headless: bool = False,
    output_dir: str = "startpage_batch_downloads",
    pause_between_ms: int = Query(1500, ge=0, le=60_000),
    json_path: str = "startpage_batch_results.json",
):
    return await _run_batch(
        json_path=json_path, queries=q, limit=limit, orientation=orientation,
        square_tolerance=square_tolerance, max_pages=max_pages,
        submit_method=submit_method, click=click, download=download,
        download_mode=download_mode, inspect_sources=inspect_sources,
        source_max_images=source_max_images, headless=headless,
        output_dir=output_dir, pause_between_ms=pause_between_ms,
    )


@app.post("/api/images/batch")
async def api_batch_post(body: BatchRequest):
    return await _run_batch(**body.model_dump())


def _print_item(item: dict[str, Any]) -> None:
    print()
    print(f"#{item['rank']} {item.get('title', '')[:100]}")
    print(
        "  proporção:", item.get("orientation"),
        f"(razão {item.get('aspect_ratio')}, fonte {item.get('orientation_source')})",
    )
    print("  original:", item.get("original_url"))
    print("  origem:", item.get("source_page"))
    print("  tamanho:", f"{item.get('width')}x{item.get('height')}")
    print("  baixada:", item.get("downloaded"))
    print("  arquivo:", item.get("download_path"))


async def run_test(
    query: str = "osama bin laden",
    limit: int = 5,
    mode: str = "both",
    headless: bool = False,
    orientation: str = "any",
):
    if mode not in {"startpage", "source", "both"}:
        raise ValueError("mode deve ser startpage, source ou both.")

    manager = BrowserManager(headless=headless, timeout_ms=30000)
    await manager.start()
    try:
        page = await manager.new_page()
        print("=" * 78)
        print("STARTPAGE IMAGES — TESTE")
        print("=" * 78)
        print("Busca:", query)
        print("Limite:", limit)
        print("Modo:", mode)
        print("Proporção:", orientation)
        print("Aguardando o Startpage liberar a verificação, se aparecer...")
        print()

        inspect = mode in {"source", "both"}
        download_mode = "source" if mode in {"source", "both"} else "startpage"

        result = await search(
            page,
            manager.context,
            query=query,
            limit=limit,
            click=True,
            download=True,
            output_dir="startpage_test_downloads",
            language="english",
            inspect_sources=inspect,
            download_mode=download_mode,
            source_max_images=500,
            orientation=orientation,
        )

        Path("startpage_test_results.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print("Resultados encontrados:", len(result["results"]))
        warn = result["scan_stats"].get("warning")
        if warn:
            print("AVISO:", warn)
        for item in result["results"]:
            _print_item(item)

        if "source_catalog" in result:
            catalog = result["source_catalog"]
            print()
            print("Sites de origem:", catalog.get("site_count", 0))
            for site in catalog.get("sites", []):
                print()
                print("SITE:", site.get("source_page"))
                print("IMAGENS:", site.get("image_count", 0))
                for image in site.get("images", [])[:20]:
                    print(f"  [{image.get('index')}] {image.get('name') or image.get('url')}")

        print()
        print("JSON:", Path("startpage_test_results.json").resolve())
        print("Downloads:", Path("startpage_test_downloads").resolve())
        return result
    finally:
        await manager.stop()


async def run_batch_cli(args: argparse.Namespace):
    result = await search_images_batch(
        queries=args.batch,
        limit=max(1, min(args.limit, MAX_LIMIT)),
        orientation=args.orientation,
        square_tolerance=args.square_tolerance,
        click=not args.no_click,
        download=args.download,
        download_mode=args.download_mode,
        inspect_sources=args.inspect_sources,
        submit_method=args.submit_method,
        max_pages=args.max_pages,
        headless=args.headless,
        pause_between_ms=args.pause_ms,
    )
    for s in result["searches"]:
        print("\n" + "=" * 78)
        print(f"BUSCA {s['index']}: {s['query']}  [{s.get('search_method')}]")
        print("=" * 78)
        if s.get("error"):
            print("  ERRO:", s["error"])
        for item in s["results"]:
            _print_item(item)
        warn = (s.get("scan_stats") or {}).get("warning")
        if warn:
            print("\n  AVISO:", warn)

    out = Path("startpage_batch_results.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON salvo em: {out.resolve()}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Startpage Images Browser API/tester")
    parser.add_argument("--test", action="store_true", help="Executa o teste padrão.")
    parser.add_argument("--query", default="osama bin laden", help="Busca usada no teste.")
    parser.add_argument("--limit", type=int, default=5, help="Quantidade de resultados (teste e --batch).")
    parser.add_argument(
        "--mode",
        choices=["startpage", "source", "both"],
        default="both",
        help="startpage=imagem direta; source=site + imagens; both=fluxo completo.",
    )
    parser.add_argument(
        "--batch", nargs="+", metavar="TERMO",
        help='Várias buscas na mesma aba. Ex.: --batch "gojo" "geto" --limit 5',
    )
    parser.add_argument("--orientation", default="any",
                        help="Proporção: any (qualquer), horizontal, vertical ou square (quadrada).")
    parser.add_argument("--square-tolerance", type=float, default=0.1,
                        help="Quão perto de 1:1 conta como quadrada (0.1 = razão entre 0.9 e 1.1).")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES,
                        help="Máximo de páginas de resultados lidas para completar o limit.")
    parser.add_argument("--submit-method", choices=list(SUBMIT_METHODS), default="auto",
                        help="Como enviar a busca digitada: enter, click (lupa) ou auto (enter e, se falhar, clique).")
    parser.add_argument("--download", action="store_true", help="Baixa as imagens (com --batch).")
    parser.add_argument("--download-mode", choices=["startpage", "source"], default="startpage",
                        help="Modo de download no --batch.")
    parser.add_argument("--inspect-sources", action="store_true",
                        help="Acessa os sites de origem e cataloga as imagens (com --batch).")
    parser.add_argument("--no-click", action="store_true", help="Não abre o detalhe de cada resultado (com --batch).")
    parser.add_argument("--pause-ms", type=int, default=1500, help="Pausa entre buscas do lote.")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()

    if args.batch:
        asyncio.run(run_batch_cli(args))
        return

    if args.test:
        asyncio.run(
            run_test(
                query=args.query,
                limit=max(1, min(args.limit, MAX_LIMIT)),
                mode=args.mode,
                headless=args.headless,
                orientation=args.orientation,
            )
        )
        return

    print(f"Startpage Images API: http://{args.host}:{args.port}")
    print("Exemplo: /api/images/search?q=osama%20bin%20laden&limit=5&orientation=vertical")
    print("Lote:    /api/images/batch?q=gojo&q=geto&limit=5")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
