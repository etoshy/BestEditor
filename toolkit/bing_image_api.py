# -*- coding: utf-8 -*-
"""
Bing Images browser API/tester.

What it does:
- Opens Bing Images in a real Playwright Chromium browser.
- Builds the Bing qft filters from friendly API parameters.
- Reads Bing's `.iusc` result cards and parses the `m` JSON attribute.
- For the first N results, actually opens/clicks the image detail.
- Extracts the image's original `mediaurl`/murl and source page.
- Optionally downloads the original files.

Install:
    py -m pip install -r requirements.txt
    py -m playwright install chromium

Run test:
    py bing_image_api.py --test

Run API:
    py bing_image_api.py

API examples:
    http://127.0.0.1:8000/api/images/search?q=gojo%20eyes
    http://127.0.0.1:8000/api/images/search?q=gojo%20eyes&aspect=wide&limit=3
    http://127.0.0.1:8000/api/images/search?q=gojo%20eyes&aspect=wide&animated=true&limit=3
    http://127.0.0.1:8000/api/images/search?q=gojo%20eyes&aspect=wide&transparent=true&size=large&limit=3
    http://127.0.0.1:8000/api/images/search?q=gojo%20eyes&download=true&limit=3

Optional:
    --headless     Run Chromium without opening a visible window.
    --port 8000    API port.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import mimetypes
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urljoin, urlparse

from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, async_playwright


BING_IMAGES = "https://www.bing.com/images/search"
DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_LIMIT = 3


def build_qft(
    *,
    aspect: str | None = None,
    animated: bool = False,
    transparent: bool = False,
    size: str | None = None,
    extra_qft: str | None = None,
) -> str | None:
    """
    Bing qft fragments observed in the supplied Bing HTML:
      aspect-wide / aspect-tall / aspect-square
      photo-animatedgif
      photo-transparent
      imagesize-large / wallpaper / medium / small

    Returns the qft value including the leading space used by Bing.
    """
    parts: list[str] = []

    aspect_map = {
        "wide": "filterui:aspect-wide",
        "tall": "filterui:aspect-tall",
        "square": "filterui:aspect-square",
    }
    size_map = {
        "large": "filterui:imagesize-large",
        "wallpaper": "filterui:imagesize-wallpaper",
        "medium": "filterui:imagesize-medium",
        "small": "filterui:imagesize-small",
    }

    if aspect:
        aspect = aspect.lower().strip()
        if aspect not in aspect_map:
            raise ValueError(f"aspect inválido: {aspect}. Use wide, tall ou square.")
        parts.append(aspect_map[aspect])

    if animated:
        parts.append("filterui:photo-animatedgif")

    if transparent:
        parts.append("filterui:photo-transparent")

    if size:
        size = size.lower().strip()
        if size not in size_map:
            raise ValueError(
                f"size inválido: {size}. Use large, wallpaper, medium ou small."
            )
        parts.append(size_map[size])

    if extra_qft:
        # Permite passar filtros qft adicionais do próprio Bing.
        raw = extra_qft.strip()
        if raw:
            # Remove eventuais espaços extras no começo/fim, mas preserva os tokens.
            parts.append(raw.lstrip("+ "))

    if not parts:
        return None

    return " " + " ".join(parts)


def build_search_url(
    q: str,
    *,
    first: int = 1,
    mkt: str = "pt-BR",
    qft: str | None = None,
) -> str:
    params = {
        "q": q,
        "first": str(max(1, int(first))),
        "form": "HDRSC2",
        "mkt": mkt,
    }
    if qft:
        params["qft"] = qft
    return f"{BING_IMAGES}?{urlencode(params)}"


def safe_filename(name: str, default: str = "imagem") -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:180] or default


def decode_m_attribute(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        # Playwright normalmente já retorna &quot; decodificado, mas este fallback
        # deixa o parser robusto para HTML copiado/raw.
        decoded = html.unescape(raw)
        data = json.loads(decoded)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def extract_mediaurl_from_href(href: str | None) -> str | None:
    if not href:
        return None

    try:
        parsed = urlparse(urljoin("https://www.bing.com", href))
        qs = parse_qs(parsed.query)
        values = qs.get("mediaurl")
        if values:
            return unquote(values[0])
    except Exception:
        pass

    return None


async def collect_result_cards(page: Page, wanted: int) -> list[dict[str, Any]]:
    """
    Reads normal Bing Image result cards.
    The core selector is the one shown in the supplied HTML:
        <a class="iusc" ... m="...">
    """
    await page.wait_for_selector("a.iusc", timeout=DEFAULT_TIMEOUT_MS)

    # Give lazy-loaded cards a moment to finish.
    await page.wait_for_timeout(1200)

    cards = await page.locator("a.iusc").all()
    results: list[dict[str, Any]] = []

    for idx, card in enumerate(cards):
        if len(results) >= wanted:
            break

        try:
            m_raw = await card.get_attribute("m")
            meta = decode_m_attribute(m_raw)
            href = await card.get_attribute("href")

            # Ignore cards where Bing did not give media metadata.
            murl = meta.get("murl") or extract_mediaurl_from_href(href)
            if not murl:
                continue

            t = meta.get("t") or meta.get("desc") or ""
            purl = meta.get("purl") or ""
            turl = meta.get("turl") or ""

            try:
                width = int(meta.get("expw")) if meta.get("expw") else None
                height = int(meta.get("exph")) if meta.get("exph") else None
            except Exception:
                width = height = None

            results.append(
                {
                    "rank": len(results) + 1,
                    "dom_index": idx,
                    "title": t,
                    "description": meta.get("desc", ""),
                    "source_page": purl,
                    "original_url": murl,
                    "thumbnail_url": turl,
                    "media_id": meta.get("mid"),
                    "cid": meta.get("cid"),
                    "md5": meta.get("md5"),
                    "width": width,
                    "height": height,
                    "bing_result_url": urljoin("https://www.bing.com", href or ""),
                    "m_raw": m_raw,
                }
            )
        except Exception:
            continue

    return results


async def open_detail_for_result(
    context: BrowserContext,
    search_page: Page,
    result: dict[str, Any],
) -> dict[str, Any]:
    """
    Opens the result detail. We try a real click first, then use the Bing
    result href as a deterministic fallback.
    """
    result = dict(result)
    before = search_page.url

    try:
        locator = search_page.locator("a.iusc").nth(result["dom_index"])
        await locator.scroll_into_view_if_needed()
        await locator.click(timeout=12_000)
        await search_page.wait_for_timeout(900)

        current = search_page.url
        if "view=detailV2" not in current:
            raise RuntimeError("Bing não abriu o detalhe via click.")
        detail_url = current
    except Exception as click_error:
        detail_url = result["bing_result_url"]
        try:
            await search_page.goto(
                detail_url,
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT_MS,
            )
            await search_page.wait_for_timeout(700)
        except Exception as goto_error:
            result["detail_error"] = f"click={click_error}; goto={goto_error}"
            result["detail_opened"] = False
            return result

    result["detail_url"] = detail_url
    result["detail_opened"] = True

    # Bing puts the full result dimensions in the detail URL as expw/exph.
    try:
        detail_qs = parse_qs(urlparse(detail_url).query)
        if detail_qs.get("expw") and not result.get("width"):
            result["width"] = int(detail_qs["expw"][0])
        if detail_qs.get("exph") and not result.get("height"):
            result["height"] = int(detail_qs["exph"][0])
    except Exception:
        pass

    media_from_detail = extract_mediaurl_from_href(detail_url)
    if media_from_detail:
        result["original_url"] = media_from_detail

    # Try to locate the large/main image on the detail page.
    try:
        detail_candidates = await search_page.locator("img").evaluate_all(
            """
            els => els.map(img => ({
                src: img.currentSrc || img.src || "",
                alt: img.alt || "",
                width: img.naturalWidth || 0,
                height: img.naturalHeight || 0
            }))
            .filter(x => x.src && !x.src.startsWith("data:"))
            .sort((a,b) => (b.width*b.height) - (a.width*a.height))
            .slice(0, 12)
            """
        )

        for candidate in detail_candidates:
            src = candidate.get("src", "")
            if not src:
                continue
            if "th.bing.com" not in src and "mm.bing.net" not in src:
                result["detail_display_url"] = src
                break
        if not result.get("detail_display_url") and detail_candidates:
            result["detail_display_url"] = detail_candidates[0]["src"]
    except Exception:
        pass

    # Return to result grid so the next item can be clicked.
    if search_page.url != before:
        try:
            await search_page.go_back(
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT_MS,
            )
            await search_page.wait_for_timeout(600)
        except Exception:
            # Re-open the search page if the overlay navigation cannot be reversed.
            await search_page.goto(
                before,
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT_MS,
            )
            await search_page.wait_for_timeout(900)

    return result


async def download_original(
    context: BrowserContext,
    result: dict[str, Any],
    out_dir: Path,
    index: int,
) -> dict[str, Any]:
    url = result.get("original_url")
    if not url:
        result["download_error"] = "original_url ausente"
        return result

    out_dir.mkdir(parents=True, exist_ok=True)

    title = safe_filename(result.get("title") or f"bing_{index:03d}", f"bing_{index:03d}")
    ext = Path(urlparse(url).path).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".svg"}:
        ext = ""

    target = out_dir / f"{index:03d}_{title}{ext}"

    try:
        response = await context.request.get(
            url,
            timeout=45_000,
            headers={
                "Referer": "https://www.bing.com/",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
        )

        if not response.ok:
            raise RuntimeError(f"HTTP {response.status}")

        body = await response.body()
        content_type = response.headers.get("content-type", "").split(";")[0].strip()

        if not ext:
            ext = mimetypes.guess_extension(content_type) or ".bin"
            target = out_dir / f"{index:03d}_{title}{ext}"

        target.write_bytes(body)

        result["downloaded"] = True
        result["download_path"] = str(target.resolve())
        result["download_content_type"] = content_type
        result["download_bytes"] = len(body)
    except Exception as exc:
        result["downloaded"] = False
        result["download_error"] = str(exc)

    return result


async def search_images_browser_in_session(
    page: Page,
    context: BrowserContext,
    *,
    q: str,
    first: int = 1,
    limit: int = DEFAULT_LIMIT,
    aspect: str | None = None,
    animated: bool = False,
    transparent: bool = False,
    size: str | None = None,
    extra_qft: str | None = None,
    mkt: str = "pt-BR",
    download: bool = False,
    output_dir: str = "bing_downloads",
) -> dict[str, Any]:
    if not q.strip():
        raise ValueError("q não pode ficar vazio.")
    if limit < 1 or limit > 20:
        raise ValueError("limit deve ficar entre 1 e 20.")
    qft = build_qft(
        aspect=aspect, animated=animated, transparent=transparent, size=size, extra_qft=extra_qft,
    )
    search_url = build_search_url(q, first=first, mkt=mkt, qft=qft)
    await page.goto(search_url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
    results = await collect_result_cards(page, wanted=limit)
    if not results:
        raise RuntimeError(
            "Nenhum resultado .iusc com murl foi encontrado. "
            "O Bing pode ter alterado o HTML ou exibido um bloqueio/desafio."
        )
    detailed: list[dict[str, Any]] = []
    for result in results:
        detailed.append(await open_detail_for_result(context, page, result))
    if download:
        out = Path(output_dir)
        for i, result in enumerate(detailed, start=1):
            await download_original(context, result, out, i)
    return {
        "ok": True, "query": q, "first": first, "limit_requested": limit,
        "results_found": len(detailed),
        "filters": {"aspect": aspect, "animated": animated, "transparent": transparent, "size": size, "extra_qft": extra_qft, "qft_final": qft},
        "search_url": search_url, "results": detailed,
    }


async def search_images_browser(
    *,
    q: str, first: int = 1, limit: int = DEFAULT_LIMIT, aspect: str | None = None,
    animated: bool = False, transparent: bool = False, size: str | None = None,
    extra_qft: str | None = None, mkt: str = "pt-BR", headless: bool = False,
    download: bool = False, output_dir: str = "bing_downloads",
) -> dict[str, Any]:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        context = await browser.new_context(
            locale="pt-BR", viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7"},
        )
        page = await context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        try:
            return await search_images_browser_in_session(
                page, context, q=q, first=first, limit=limit, aspect=aspect, animated=animated,
                transparent=transparent, size=size, extra_qft=extra_qft, mkt=mkt, download=download, output_dir=output_dir,
            )
        finally:
            await context.close()
            await browser.close()
