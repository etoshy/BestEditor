# -*- coding: utf-8 -*-
"""
STARTPAGE IMAGES — Browser API / Tester

Pacote em formato igual ao Brave: um único script + requirements + README.
Usa a implementação funcional de navegação/Anubis e extração do payload
AppSerpImages do Startpage, com catálogo opcional das páginas de origem.

Não tenta contornar a verificação do Startpage.
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
) -> str:
    # Startpage documents /sp/search?query=%s for browser search strings and
    # supports the images category.
    params = {
        "query": query,
        "cat": cat,
        "language": language,
    }
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

async def _proven_search(
    page: Page,
    context: BrowserContext,
    *,
    query: str,
    limit: int = 3,
    click: bool = True,
    download: bool = True,
    output_dir: str = "tests/outputs/startpage_images",
    language: str = "english",
) -> dict[str, Any]:
    url = build_url(query, language=language)

    await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    # The user's supplied HTML showed Startpage's Anubis verification page.
    # Keep the real browser alive until Startpage releases it.
    await wait_for_startpage_ready(page, timeout_ms=180_000)

    # After release, the search result page should render the AppSerpImages
    # payload. Give the React application a moment to settle.
    await page.wait_for_timeout(1200)

    page_html = ""
    for _ in range(8):
        try:
            page_html = await page.content()
            break
        except Exception as exc:
            if "Execution context was destroyed" not in str(exc) and \
               "most likely because of a navigation" not in str(exc):
                raise
            await page.wait_for_timeout(500)

    payload = extract_react_object(page_html)
    raw_results = walk_image_results(payload)

    # DOM fallback: try to extract an image result link if the React object is
    # absent due to a markup change.
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

    results: list[ImageResult] = []

    for item in raw_results:
        if len(results) >= limit:
            break

        alt_click = str(item.get("altClickUrl") or "")
        raw_image = str(item.get("rawImageUrl") or "")
        thumb = str(item.get("thumbnailUrl") or "")

        # Startpage's image data uses:
        #   altClickUrl = image-result link
        #   rawImageUrl = original image URL
        #   thumbnailUrl = proxied thumbnail
        original = raw_image or alt_click
        title = html_lib.unescape(str(item.get("title") or ""))

        if not original:
            continue

        width = height = None
        try:
            if item.get("width"):
                width = int(item["width"])
            if item.get("height"):
                height = int(item["height"])
        except Exception:
            pass

        source_page = str(
            item.get("clickUrl")
            or item.get("pageUrl")
            or ""
        )

        if alt_click.startswith("/"):
            alt_click = urljoin(BASE_URL, alt_click)
        if thumb.startswith("/"):
            thumb = urljoin(BASE_URL, thumb)

        result = ImageResult(
            source=SOURCE_NAME,
            rank=len(results) + 1,
            title=title,
            description="",
            source_page=_normalize_startpage_url(source_page),
            original_url=original,
            thumbnail_url=thumb,
            detail_url=alt_click,
            width=width,
            height=height,
            source_domain=urlparse(source_page or original).netloc,
        )

        if click:
            # Try to open the image result through Startpage's visible result
            # link. When we do not find a clickable card, the extracted
            # altClickUrl remains the deterministic fallback.
            try:
                candidate = page.locator(
                    f'a[href="{alt_click}"]'
                ).first

                if await candidate.count():
                    await candidate.scroll_into_view_if_needed()
                    try:
                        async with page.expect_popup(timeout=5000) as popup_info:
                            await candidate.click(timeout=12000)
                        popup = await popup_info.value
                        try:
                            await popup.wait_for_load_state(
                                "domcontentloaded", timeout=10000
                            )
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
                        if page.url != url:
                            await page.goto(
                                url,
                                wait_until="domcontentloaded",
                                timeout=30000,
                            )
                            await wait_for_startpage_ready(
                                page,
                                timeout_ms=180_000,
                            )
                else:
                    # A separate tab URL is not always rendered as the same
                    # literal href after hydration. Use the known result URL.
                    detail_page = await context.new_page()
                    try:
                        await detail_page.goto(
                            alt_click,
                            wait_until="domcontentloaded",
                            timeout=30000,
                        )
                        result.clicked = True
                        result.detail_url = detail_page.url
                    finally:
                        await detail_page.close()

            except Exception as exc:
                result.error = f"click: {exc}"

        if download:
            ok, path, err = await download_url(
                context,
                original,
                out_dir=Path(output_dir),
                prefix=f"{result.rank:03d}",
                title=result.title,
            )
            result.downloaded = ok
            result.download_path = path
            if err:
                result.error = f"{result.error}; download: {err}".strip("; ")

        results.append(result)

    return {
        "source": SOURCE_NAME,
        "query": query,
        "search_url": url,
        "filters": (
            "Startpage Images: tamanho, cor, tipo e licença são documentados "
            "pela página de suporte; esta primeira integração usa a busca "
            "normal para manter o adaptador independente."
        ),
        "results": [r.to_dict() for r in results],
    }

async def search_in_session(
    page: Page,
    context: BrowserContext,
    *,
    query: str,
    limit: int = 3,
    click: bool = True,
    download: bool = False,
    output_dir: str = "tests/outputs/startpage_images",
    language: str = "english",
) -> dict[str, Any]:
    return await _proven_search(
        page, context, query=query, limit=limit, click=click, download=download,
        output_dir=output_dir, language=language,
    )


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
) -> dict[str, Any]:
    """
    Mantém o mecanismo comprovado de busca do ZIP fornecido pelo usuário.

    Novas opções:
      inspect_sources=False   -> comportamento normal
      inspect_sources=True    -> abre sites de origem e cria catálogo JSON
      download_mode=startpage -> baixa a imagem original exposta pelo Startpage
      download_mode=source    -> baixa as imagens encontradas nas páginas fonte
    """
    if download_mode not in {"startpage", "source"}:
        raise ValueError(
            "download_mode deve ser 'startpage' ou 'source'."
        )

    # Usa o parser + wait_for_startpage_ready comprovados.
    result = await _proven_search(
        page,
        context,
        query=query,
        limit=limit,
        click=click,
        download=(download and download_mode == "startpage"),
        output_dir=output_dir,
        language=language,
    )

    result["inspect_sources"] = inspect_sources
    result["download_mode"] = download_mode

    typed_results = []
    for item in result["results"]:
        typed_results.append(ImageResult(**item))

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
                output_dir=str(
                    Path(output_dir) / "sources"
                ),
            )

            # Propaga um resumo para cada site/imagem.
            result["source_catalog"] = catalog

    return result



# =============================================================================
# PUBLIC API + TEST
# =============================================================================
