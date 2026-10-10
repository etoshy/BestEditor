# -*- coding: utf-8 -*-
"""
YANDEX IMAGES — Browser API / Tester

Formato propositalmente parecido com o projeto Brave:
    yandex_image_api.py
    requirements_yandex.txt
    README_yandex_image_api.md

Fluxo básico:
    Yandex Images
        |
        +--> thumbnail do Yandex
        |
        +--> img_url (URL direta da imagem exposta no href)
        |
        +--> opcionalmente abre a página de detalhe do Yandex
                 |
                 +--> tenta descobrir a página/fonte original
                 |
                 +--> opcionalmente abre a fonte
                         |
                         +--> OG / Twitter / JSON-LD
                         +--> <img>
                         +--> srcset
                         +--> lazy images
                         +--> links diretos
                         +--> catálogo JSON
                         +--> download

A estrutura do HTML fornecido pelo usuário contém:
    .SerpItem
    .ImagesContentImage-Cover
    href="/images/search?pos=...&img_url=..."
    img.ImagesContentImage-Image_clickable
    src="//avatars.mds.yandex.net/i?id=..."
    alt="..."

O script usa o href do resultado para recuperar img_url.
Assim, o download normal NÃO salva o thumbnail avatars.mds.yandex.net;
ele usa a URL direta codificada em img_url.

A coleta das páginas de origem é OPCIONAL.
"""

from __future__ import annotations

import argparse
import asyncio
import html as html_lib
import json
import mimetypes
import re
from pathlib import Path
from typing import Any
from urllib.parse import (
    parse_qs,
    quote_plus,
    unquote,
    urljoin,
    urlparse,
)

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn

from playwright.async_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


YANDEX_BASE = "https://yandex.com"
YANDEX_IMAGES = "https://yandex.com/images/search"
DEFAULT_TIMEOUT_MS = 30_000
SOURCE_TIMEOUT_MS = 35_000

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".bmp", ".avif", ".svg", ".jfif", ".tif", ".tiff"
}

# Domínios que são motores/agregadores de busca.
# Por padrão NÃO são tratados como "site de origem", para impedir que
# uma página de resultados (especialmente Google) vire um catálogo enorme.
SEARCH_ENGINE_HOSTS = {
    "google.com",
    "google.com.br",
    "www.google.com",
    "www.google.com.br",
    "bing.com",
    "www.bing.com",
    "search.yahoo.com",
    "duckduckgo.com",
    "www.duckduckgo.com",
    "startpage.com",
    "www.startpage.com",
    "yandex.com",
    "yandex.ru",
    "brave.com",
    "search.brave.com",
}

DEFAULT_MAX_IMAGES_PER_SITE = 50


# ----------------------------------------------------------------------------
# Filtro por proporção (orientação) da THUMBNAIL
# ----------------------------------------------------------------------------
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


def is_google_host(host: str) -> bool:
    host = (host or "").lower().split(":", 1)[0].strip(".")
    return (
        host == "google.com"
        or host.endswith(".google.com")
        or host == "google.com.br"
        or host.endswith(".google.com.br")
    )


def is_search_engine_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().split(":", 1)[0].strip(".")
    except Exception:
        return False

    if is_google_host(host):
        return True

    return (
        host in SEARCH_ENGINE_HOSTS
        or any(host.endswith("." + base) for base in SEARCH_ENGINE_HOSTS)
    )


def should_skip_source_url(
    url: str,
    *,
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
) -> tuple[bool, str]:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return True, "URL inválida"

    if not host:
        return True, "host ausente"

    if is_google_host(host):
        if allow_google_source or allow_search_engine_sources:
            return False, ""
        return True, "Google bloqueado como site de origem"

    if is_search_engine_url(url):
        if allow_search_engine_sources:
            return False, ""
        return True, "motor de busca bloqueado como site de origem"

    return False, ""


def build_search_url(
    query: str,
    *,
    lang: str = "en",
) -> str:
    return (
        f"{YANDEX_IMAGES}"
        f"?text={quote_plus(query)}"
        f"&lang={quote_plus(lang)}"
    )


def normalize_url(
    base: str,
    value: str | None,
) -> str:
    if not value:
        return ""

    value = html_lib.unescape(
        str(value)
    ).strip()

    if not value:
        return ""

    if value.startswith("//"):
        return "https:" + value

    return urljoin(
        base,
        value,
    )


def safe_filename(
    value: str,
    fallback: str = "imagem",
) -> str:
    value = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "_",
        value or "",
    )
    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip(" .")

    return value[:180] or fallback


def is_image_url(
    url: str,
) -> bool:
    try:
        path = urlparse(url).path.lower()
        return path.endswith(
            tuple(IMAGE_EXTENSIONS)
        )
    except Exception:
        return False


def extract_img_url_from_yandex_result(
    href: str,
) -> str:
    """
    Exemplo do HTML fornecido:

    /images/search?pos=0&img_url=https%3A%2F%2F...jpg&text=gojo&rpt=simage
    """
    href = normalize_url(
        YANDEX_BASE,
        href,
    )

    try:
        parsed = urlparse(href)
        params = parse_qs(
            parsed.query,
            keep_blank_values=True,
        )

        value = (
            params.get(
                "img_url",
                [""],
            )[0]
        )

        return unquote(value)

    except Exception:
        return ""


SERP_LINK_SELECTOR = "div.SerpItem a.ImagesContentImage-Cover"
FIRST_RESULT_HREF_JS = """
() => {
    const a = document.querySelector('div.SerpItem a.ImagesContentImage-Cover');
    return a ? (a.getAttribute('href') || '') : '';
}
"""


async def detect_captcha(page: Page) -> bool:
    """Detecta a página de verificação do Yandex (não tentamos contorná-la)."""
    try:
        url = page.url.lower()
        if "showcaptcha" in url or "captcha" in urlparse(url).path:
            return True
        return (
            await page.locator(
                ".CheckboxCaptcha, .AdvancedCaptcha, form[action*='captcha']"
            ).count()
        ) > 0
    except Exception:
        return False


async def wait_for_yandex_results(page: Page) -> None:
    """Aguarda os cards reais. Se houver captcha, avisa em vez de falhar mudo."""
    try:
        await page.wait_for_selector(SERP_LINK_SELECTOR, timeout=DEFAULT_TIMEOUT_MS)
        return
    except PlaywrightTimeoutError:
        pass
    try:
        # fallback, mantendo robustez entre versões do Yandex.
        await page.wait_for_selector("div.SerpList img.ImagesContentImage-Image", timeout=10_000)
        return
    except PlaywrightTimeoutError:
        if await detect_captcha(page):
            raise RuntimeError(
                "O Yandex exibiu uma verificação (captcha). Conclua a verificação "
                "no navegador e execute novamente."
            )
        raise RuntimeError(
            "O Yandex não exibiu resultados de imagens dentro do tempo esperado."
        )


async def read_thumbnail_size(image) -> dict[str, Any]:
    """
    Lê o tamanho da THUMBNAIL já carregada no card (naturalWidth/Height).
    Se ainda for lazy-load, rola até o card e espera carregar.
    Ordem: tamanho natural -> tamanho exibido -> atributos width/height.
    """
    probe = """
    el => ({
        nw: el.naturalWidth || 0,
        nh: el.naturalHeight || 0,
        placeholder: (el.currentSrc || el.src || '').startsWith('data:'),
        rw: el.getBoundingClientRect().width || 0,
        rh: el.getBoundingClientRect().height || 0,
        aw: parseFloat(el.getAttribute('width')) || 0,
        ah: parseFloat(el.getAttribute('height')) || 0,
    })
    """
    wait_loaded = """
    el => new Promise(res => {
        const ok = () => el.naturalWidth > 0 && !(el.currentSrc || el.src || '').startsWith('data:');
        if (ok()) return res(true);
        const t = setInterval(() => { if (ok()) { clearInterval(t); res(true); } }, 100);
        setTimeout(() => { clearInterval(t); res(false); }, 2500);
    })
    """
    try:
        data = await image.evaluate(probe)
        if not data["nw"] or data["placeholder"]:
            try:
                await image.scroll_into_view_if_needed(timeout=3_000)
            except Exception:
                pass
            await image.evaluate(wait_loaded)
            data = await image.evaluate(probe)
    except Exception:
        return {"width": None, "height": None, "source": None}

    if data["nw"] and data["nh"] and not data["placeholder"]:
        return {"width": data["nw"], "height": data["nh"], "source": "natural"}
    if data["rw"] and data["rh"]:
        return {"width": round(data["rw"]), "height": round(data["rh"]), "source": "displayed"}
    if data["aw"] and data["ah"]:
        return {"width": data["aw"], "height": data["ah"], "source": "attributes"}
    return {"width": None, "height": None, "source": None}


async def click_show_more_if_present(page: Page) -> bool:
    """Se o Yandex mostrar um botão 'Mostrar mais', clica nele (melhor esforço)."""
    try:
        btn = page.locator("button.FetchListButton-Button, .FetchListButton button").first
        if await btn.count() and await btn.is_visible():
            await btn.click(timeout=3_000)
            await page.wait_for_timeout(800)
            return True
    except Exception:
        pass
    return False


async def collect_yandex_results(
    page: Page,
    limit: int,
    *,
    orientation: str = "any",
    square_tolerance: float = 0.1,
    max_scroll_rounds: int = 25,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Usa diretamente a estrutura mostrada no HTML do usuário:
        div.SerpItem
        a.ImagesContentImage-Cover
        img.ImagesContentImage-Image_clickable

    Aplica o filtro de proporção pela thumbnail. `limit` conta só as imagens
    que passam no filtro; se não bastam, rola a página para carregar mais.
    Retorna (resultados, estatísticas).
    """
    orientation = normalize_orientation(orientation)

    await wait_for_yandex_results(page)

    # Dispara lazy-loading.
    for _ in range(8):
        await page.mouse.wheel(0, 1200)
        await page.wait_for_timeout(400)

    stats: dict[str, Any] = {
        "cards_scanned": 0,
        "filtered_out": 0,
        "unknown_orientation": 0,
        "scroll_rounds": 0,
    }
    results: list[dict[str, Any]] = []
    seen_images: set[str] = set()
    idle_rounds = 0

    while True:
        cards = page.locator("div.SerpItem")
        count = await cards.count()
        new_cards = 0

        for dom_index in range(count):

            if len(results) >= limit:
                break

            card = cards.nth(dom_index)

            try:
                link = card.locator("a.ImagesContentImage-Cover").first
                image = card.locator("img.ImagesContentImage-Image").first

                if await link.count() == 0:
                    continue

                href = await link.get_attribute("href")
                if not href:
                    continue

                image_url = extract_img_url_from_yandex_result(href)

                # O resultado guarda a imagem real em img_url. Sem duplicatas.
                if not image_url:
                    continue

                image_url = normalize_url(YANDEX_BASE, image_url)

                if image_url in seen_images:
                    continue
                seen_images.add(image_url)
                new_cards += 1
                stats["cards_scanned"] += 1

                has_image = await image.count() > 0

                # ---- proporção pela thumbnail ----
                size = (
                    await read_thumbnail_size(image)
                    if has_image
                    else {"width": None, "height": None, "source": None}
                )
                kind, ratio = classify_orientation(
                    size["width"], size["height"], square_tolerance,
                )
                if orientation != "any":
                    if kind is None:
                        stats["unknown_orientation"] += 1
                        stats["filtered_out"] += 1
                        continue  # não dá para confirmar -> não entra
                    if kind != orientation:
                        stats["filtered_out"] += 1
                        continue

                thumb = (await image.get_attribute("src") or "") if has_image else ""
                alt = (await image.get_attribute("alt") or "") if has_image else ""

                # Atributos width/height do elemento exibido.
                width = None
                height = None
                raw_width = await image.get_attribute("width") if has_image else None
                raw_height = await image.get_attribute("height") if has_image else None
                try:
                    if raw_width:
                        width = float(raw_width)
                    if raw_height:
                        height = float(raw_height)
                except Exception:
                    pass

                results.append(
                    {
                        "rank": len(results) + 1,
                        "yandex_rank": len(results),
                        "title": alt,
                        "alt": alt,
                        "thumbnail_url": normalize_url(YANDEX_BASE, thumb),
                        "original_url": image_url,
                        "result_url": normalize_url(YANDEX_BASE, href),
                        "source_page": "",
                        "source_domain": urlparse(image_url).netloc,
                        "width": width,
                        "height": height,
                        "thumb_width": size["width"],
                        "thumb_height": size["height"],
                        "aspect_ratio": ratio,
                        "orientation": kind,
                        "orientation_source": size["source"],
                        "dom_index": dom_index,
                        "clicked": False,
                        "downloaded": False,
                        "download_path": "",
                        "error": "",
                    }
                )

            except Exception:
                continue

        if len(results) >= limit:
            break
        if stats["scroll_rounds"] >= max_scroll_rounds:
            break

        idle_rounds = idle_rounds + 1 if new_cards == 0 else 0
        if idle_rounds >= 3:
            # Última tentativa: botão "Mostrar mais", se existir.
            if await click_show_more_if_present(page):
                idle_rounds = 0
                stats["scroll_rounds"] += 1
                continue
            break

        await page.mouse.wheel(0, 1500)
        await page.wait_for_timeout(700)
        stats["scroll_rounds"] += 1

    return results, stats


async def discover_source_page(
    context: BrowserContext,
    result: dict[str, Any],
    *,
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
) -> dict[str, Any]:

    result = dict(result)

    detail_url = (
        result.get("result_url")
        or ""
    )

    if not detail_url:
        result["source_discovery_error"] = (
            "result_url ausente"
        )
        return result

    page = await context.new_page()
    page.set_default_timeout(
        DEFAULT_TIMEOUT_MS
    )

    try:
        await page.goto(
            detail_url,
            wait_until="domcontentloaded",
            timeout=SOURCE_TIMEOUT_MS,
        )

        await page.wait_for_timeout(
            900
        )

        # Primeiro tenta links claramente externos.
        links = await page.locator(
            "a[href]"
        ).evaluate_all(
            """
            els => els.map(a => ({
                href: a.href || '',
                text: (a.innerText || '').trim(),
                title: a.getAttribute('title') || ''
            })).filter(x => x.href)
            """
        )

        source_page = ""

        for link in links:
            href = link["href"]

            if not href.startswith(
                (
                    "http://",
                    "https://",
                )
            ):
                continue

            host = urlparse(
                href
            ).netloc.lower()

            if not host:
                continue

            if (
                host == "yandex.com"
                or host.endswith(".yandex.com")
                or host == "yandex.ru"
                or host.endswith(".yandex.ru")
                or "yandex.net" in host
            ):
                continue

            skip, _reason = should_skip_source_url(
                href,
                allow_google_source=allow_google_source,
                allow_search_engine_sources=allow_search_engine_sources,
            )
            if skip:
                continue

            source_page = href
            break

        # Alguns detalhes podem entregar a URL da imagem direta mas não a
        # página; neste caso mantemos vazio em vez de inventar uma origem.
        result["source_page"] = source_page
        result["detail_url"] = page.url
        result["clicked"] = True

        # Procura uma imagem maior na página de detalhe.
        candidates = await page.locator(
            "img"
        ).evaluate_all(
            """
            els => els.map(img => ({
                src: img.currentSrc || img.src || '',
                alt: img.alt || '',
                width: img.naturalWidth || 0,
                height: img.naturalHeight || 0
            }))
            .filter(x => x.src && !x.src.startsWith('data:'))
            .sort((a,b) =>
                (b.width*b.height) - (a.width*a.height)
            )
            """
        )

        for candidate in candidates:

            src = normalize_url(
                page.url,
                candidate.get(
                    "src"
                ),
            )

            if not src:
                continue

            if (
                "yandex.net" in
                urlparse(src).netloc.lower()
            ):
                continue

            result["detail_image_url"] = src
            break

    except Exception as exc:
        result["source_discovery_error"] = str(
            exc
        )

    finally:
        await page.close()

    return result


def choose_largest_srcset(
    srcset: str | None,
) -> str:
    if not srcset:
        return ""

    values = []

    for item in srcset.split(","):
        parts = item.strip().split()

        if not parts:
            continue

        score = 0.0

        if len(parts) > 1:
            m = re.match(
                r"(\d+(?:\.\d+)?)w",
                parts[1],
            )

            if m:
                score = float(
                    m.group(1)
                )

            else:
                m = re.match(
                    r"(\d+(?:\.\d+)?)x",
                    parts[1],
                )

                if m:
                    score = (
                        float(
                            m.group(1)
                        )
                        * 1000
                    )

        values.append(
            (
                score,
                parts[0],
            )
        )

    if not values:
        return ""

    values.sort(
        reverse=True
    )

    return values[0][1]


async def inspect_source_page(
    context: BrowserContext,
    source_url: str,
    *,
    max_images: int = 500,
) -> dict[str, Any]:

    page = await context.new_page()
    page.set_default_timeout(
        DEFAULT_TIMEOUT_MS
    )

    catalog = {
        "source_page": source_url,
        "og": {},
        "image_count": 0,
        "images": [],
        "error": None,
    }

    try:
        await page.goto(
            source_url,
            wait_until="domcontentloaded",
            timeout=SOURCE_TIMEOUT_MS,
        )

        await page.wait_for_timeout(
            900
        )

        # Lazy loading.
        for _ in range(12):
            await page.mouse.wheel(
                0,
                1200,
            )
            await page.wait_for_timeout(
                350
            )

        # Meta / OG.
        metas = await page.locator(
            "meta"
        ).evaluate_all(
            """
            els => els.map(m => ({
              property: m.getAttribute('property') || '',
              name: m.getAttribute('name') || '',
              content: m.getAttribute('content') || ''
            })).filter(x => x.content)
            """
        )

        for meta in metas:

            key = (
                meta.get("property")
                or meta.get("name")
                or ""
            ).strip().lower()

            if key in {
                "og:image",
                "og:image:url",
                "og:image:secure_url",
                "twitter:image",
                "twitter:image:src",
            }:

                value = normalize_url(
                    page.url,
                    meta["content"],
                )

                if value:
                    catalog["og"][
                        key
                    ] = value

        images = []
        seen = set()

        def add_image(
            url: str | None,
            kind: str,
            *,
            alt: str = "",
            title: str = "",
            width: int = 0,
            height: int = 0,
        ):

            if not url:
                return

            url = normalize_url(
                page.url,
                url,
            )

            if not url:
                return

            if url.startswith(
                (
                    "data:",
                    "blob:",
                    "javascript:",
                )
            ):
                return

            key = url.split(
                "#",
                1
            )[0]

            if key in seen:
                return

            seen.add(
                key
            )

            images.append(
                {
                    "index": len(images) + 1,
                    "name": (
                        Path(
                            urlparse(
                                key
                            ).path
                        ).name
                        or ""
                    ),
                    "url": key,
                    "kind": kind,
                    "alt": alt or "",
                    "title": title or "",
                    "width": width or 0,
                    "height": height or 0,
                }
            )

        # OG primeiro.
        for key, value in catalog["og"].items():
            add_image(
                value,
                key,
            )

        # JSON-LD.
        jsonld = await page.locator(
            'script[type="application/ld+json"]'
        ).evaluate_all(
            """
            els => els.map(x => x.textContent || '')
            """
        )

        def walk_json(
            value: Any,
        ):
            if isinstance(
                value,
                dict,
            ):

                for key, val in value.items():

                    low = str(
                        key
                    ).lower()

                    if low in {
                        "image",
                        "thumbnailurl",
                        "contenturl",
                    }:

                        if isinstance(
                            val,
                            str,
                        ):
                            yield val

                        elif isinstance(
                            val,
                            list,
                        ):
                            for item in val:
                                if isinstance(
                                    item,
                                    str,
                                ):
                                    yield item

                                elif isinstance(
                                    item,
                                    dict,
                                ):
                                    for k in (
                                        "url",
                                        "contentUrl",
                                        "contenturl",
                                    ):
                                        if isinstance(
                                            item.get(k),
                                            str,
                                        ):
                                            yield item[k]

                        elif isinstance(
                            val,
                            dict,
                        ):
                            for k in (
                                "url",
                                "contentUrl",
                                "contenturl",
                            ):
                                if isinstance(
                                    val.get(k),
                                    str,
                                ):
                                    yield val[k]

                    yield from walk_json(
                        val
                    )

            elif isinstance(
                value,
                list,
            ):
                for item in value:
                    yield from walk_json(
                        item
                    )

        for raw in jsonld:

            try:
                parsed = json.loads(
                    raw
                )
            except Exception:
                continue

            for value in walk_json(
                parsed
            ):
                add_image(
                    value,
                    "json-ld",
                )

                if len(images) >= max_images:
                    break

            if len(images) >= max_images:
                break

        # <img>
        img_data = await page.locator(
            "img"
        ).evaluate_all(
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

            meta = {
                "alt": img.get(
                    "alt",
                    "",
                ),
                "title": img.get(
                    "title",
                    "",
                ),
                "width": img.get(
                    "width",
                    0,
                ),
                "height": img.get(
                    "height",
                    0,
                ),
            }

            add_image(
                choose_largest_srcset(
                    img.get(
                        "srcset"
                    )
                ),
                "srcset",
                **meta,
            )

            add_image(
                img.get(
                    "dataOriginal"
                ),
                "data-original",
                **meta,
            )

            add_image(
                img.get(
                    "dataSrc"
                ),
                "data-src",
                **meta,
            )

            add_image(
                img.get(
                    "dataLazy"
                ),
                "data-lazy-src",
                **meta,
            )

            add_image(
                img.get(
                    "src"
                ),
                "img",
                **meta,
            )

            if len(images) >= max_images:
                break

        # Links diretos.
        if len(images) < max_images:

            links = await page.locator(
                "a[href]"
            ).evaluate_all(
                """
                els => els.map(a => a.href || '').filter(Boolean)
                """
            )

            for href in links:

                if is_image_url(
                    href
                ):
                    add_image(
                        href,
                        "image-link",
                    )

                if len(images) >= max_images:
                    break

        catalog["images"] = images
        catalog["image_count"] = len(
            images
        )

    except Exception as exc:
        catalog["error"] = str(
            exc
        )

    finally:
        await page.close()

    return catalog


async def inspect_source_catalog(
    context: BrowserContext,
    results: list[dict[str, Any]],
    *,
    max_images_per_site: int = DEFAULT_MAX_IMAGES_PER_SITE,
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
    visited: set[str] | None = None,
) -> dict[str, Any]:
    """
    `visited` pode ser compartilhado entre buscas de um lote: um site já aberto
    numa busca anterior não é reaberto/recatalogado nas seguintes.
    """

    sites = []
    if visited is None:
        visited = set()

    for result in results:

        source_page = (
            result.get(
                "source_page"
            )
            or ""
        ).strip()

        # Se ainda não descobrimos a origem, tenta descobrir no detalhe do Yandex.
        enriched = result

        if not source_page:
            enriched = await discover_source_page(
                context,
                result,
                allow_google_source=allow_google_source,
                allow_search_engine_sources=allow_search_engine_sources,
            )
            source_page = (
                enriched.get(
                    "source_page"
                )
                or ""
            ).strip()

        if not source_page:
            continue

        source_page = normalize_url(
            YANDEX_BASE,
            source_page,
        )

        host = urlparse(
            source_page
        ).netloc.lower()

        if (
            not host
            or host == "yandex.com"
            or host.endswith(".yandex.com")
            or host == "yandex.ru"
            or host.endswith(".yandex.ru")
            or source_page in visited
        ):
            continue

        skip, reason = should_skip_source_url(
            source_page,
            allow_google_source=allow_google_source,
            allow_search_engine_sources=allow_search_engine_sources,
        )
        if skip:
            enriched["source_blocked"] = True
            enriched["source_blocked_reason"] = reason
            result.update(enriched)
            continue

        visited.add(
            source_page
        )

        site = await inspect_source_page(
            context,
            source_page,
            max_images=max_images_per_site,
        )

        site["result_rank"] = enriched.get(
            "rank"
        )
        site["result_title"] = enriched.get(
            "title",
            ""
        )
        site["result_image_url"] = enriched.get(
            "original_url",
            ""
        )

        sites.append(
            site
        )

    return {
        "site_count": len(
            sites
        ),
        "sites": sites,
    }


async def download_url(
    context: BrowserContext,
    url: str,
    *,
    out_dir: Path,
    prefix: str,
    title: str,
    referer: str | None = None,
) -> tuple[bool, str, str]:

    if not url:
        return (
            False,
            "",
            "URL vazia",
        )

    out_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    parsed = urlparse(
        url
    )

    ext = Path(
        parsed.path
    ).suffix.lower()

    if ext not in IMAGE_EXTENSIONS:
        ext = ""

    filename = safe_filename(
        title,
        f"imagem_{prefix}",
    )

    target = (
        out_dir
        / f"{prefix}_{filename}{ext}"
    )

    headers = {
        "Accept": (
            "image/avif,image/webp,image/apng,"
            "image/svg+xml,image/*,*/*;q=0.8"
        ),
        "Referer": (
            referer
            or "https://yandex.com/"
        ),
    }

    try:

        response = await context.request.get(
            url,
            timeout=45_000,
            headers=headers,
        )

        if not response.ok:
            raise RuntimeError(
                f"HTTP {response.status}"
            )

        body = await response.body()

        content_type = (
            response.headers.get(
                "content-type",
                "",
            )
            .split(
                ";",
                1,
            )[0]
            .strip()
        )

        if not ext:
            ext = (
                mimetypes.guess_extension(
                    content_type
                )
                or ".bin"
            )

            target = (
                out_dir
                / f"{prefix}_{filename}{ext}"
            )

        target.write_bytes(
            body
        )

        return (
            True,
            str(
                target.resolve()
            ),
            "",
        )

    except Exception as exc:
        return (
            False,
            "",
            str(exc),
        )


async def download_direct_results(
    context: BrowserContext,
    results: list[dict[str, Any]],
    output_dir: str,
):

    out = Path(
        output_dir
    )
    out.mkdir(
        parents=True,
        exist_ok=True,
    )

    for i, result in enumerate(
        results,
        start=1,
    ):

        url = result.get(
            "original_url"
        )

        title = (
            result.get(
                "title"
            )
            or f"yandex_{i:04d}"
        )

        ok, path, err = await download_url(
            context,
            url,
            out_dir=out,
            prefix=f"{i:04d}",
            title=title,
            referer=YANDEX_IMAGES,
        )

        result["downloaded"] = ok
        result["download_path"] = path
        result["download_error"] = err


async def download_source_catalog(
    context: BrowserContext,
    catalog: dict[str, Any],
    output_dir: str,
):

    base = Path(
        output_dir
    )
    base.mkdir(
        parents=True,
        exist_ok=True,
    )

    global_index = 0

    for site_index, site in enumerate(
        catalog.get(
            "sites",
            [],
        ),
        start=1,
    ):

        site_dir = (
            base
            / f"site_{site_index:03d}"
        )

        site_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        source_page = site.get(
            "source_page",
            "",
        )

        for image in site.get(
            "images",
            [],
        ):

            global_index += 1

            url = image.get(
                "url"
            )

            if not url:
                continue

            title = (
                image.get(
                    "title"
                )
                or image.get(
                    "alt"
                )
                or image.get(
                    "name"
                )
                or f"imagem_{global_index:05d}"
            )

            ok, path, err = await download_url(
                context,
                url,
                out_dir=site_dir,
                prefix=f"{global_index:05d}",
                title=title,
                referer=source_page,
            )

            image["downloaded"] = ok
            image["download_path"] = path
            image["download_error"] = err


async def process_current_page(
    context: BrowserContext,
    page: Page,
    *,
    query: str,
    limit: int,
    orientation: str,
    square_tolerance: float,
    inspect_sources: bool,
    download: bool,
    download_mode: str,
    output_dir: str,
    allow_google_source: bool,
    allow_search_engine_sources: bool,
    max_images_per_site: int,
    visited_sites: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any]]:
    """Coleta (com filtro de proporção), cataloga origens e baixa — na página ATUAL."""

    results, stats = await collect_yandex_results(
        page,
        limit,
        orientation=orientation,
        square_tolerance=square_tolerance,
    )

    if not results:
        if orientation != "any" and stats["cards_scanned"] > 0:
            raise RuntimeError(
                f"Nenhuma imagem '{orientation}' entre {stats['cards_scanned']} "
                f"resultados analisados ({stats['unknown_orientation']} sem tamanho "
                "conhecido). Tente outra proporção ou outro termo."
            )
        raise RuntimeError("Nenhum resultado de imagem foi encontrado no Yandex.")

    stats["orientation_filter"] = orientation
    if len(results) < limit:
        stats["warning"] = (
            f"Só {len(results)} de {limit} imagens atenderam ao filtro "
            f"'{orientation}' (cards analisados: {stats['cards_scanned']})."
        )

    for item in results:
        item["query"] = query

    source_catalog = None

    # Acessar fonte é explicitamente opcional.
    if inspect_sources or download_mode == "source":
        source_catalog = await inspect_source_catalog(
            context,
            results,
            max_images_per_site=max_images_per_site,
            allow_google_source=allow_google_source,
            allow_search_engine_sources=allow_search_engine_sources,
            visited=visited_sites,
        )

    if download:
        if download_mode == "yandex":
            await download_direct_results(context, results, output_dir)
        else:
            if source_catalog is None:
                source_catalog = await inspect_source_catalog(
                    context,
                    results,
                    max_images_per_site=max_images_per_site,
                    allow_google_source=allow_google_source,
                    allow_search_engine_sources=allow_search_engine_sources,
                    visited=visited_sites,
                )
            await download_source_catalog(
                context, source_catalog, str(Path(output_dir) / "sources"),
            )

    return results, source_catalog, stats


async def search_images(
    *,
    query: str,
    limit: int = 5,
    inspect_sources: bool = False,
    download: bool = False,
    download_mode: str = "yandex",
    headless: bool = False,
    output_dir: str = "yandex_downloads",
    json_path: str = "yandex_results.json",
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
    max_images_per_site: int = DEFAULT_MAX_IMAGES_PER_SITE,
    orientation: str = "any",
    square_tolerance: float = 0.1,
) -> dict[str, Any]:

    if download_mode not in {"yandex", "source"}:
        raise ValueError("download_mode deve ser 'yandex' ou 'source'.")

    if max_images_per_site < 1:
        raise ValueError("max_images_per_site deve ser >= 1.")

    max_images_per_site = min(max_images_per_site, 500)

    orientation = normalize_orientation(orientation)
    if not 0 <= square_tolerance <= 0.5:
        raise ValueError("square_tolerance deve ficar entre 0 e 0.5.")

    async with async_playwright() as pw:

        browser = await pw.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )

        context = await browser.new_context(
            locale="pt-BR",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
        )

        page = await context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        search_url = build_search_url(query)

        try:

            await page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT_MS,
            )

            await page.wait_for_timeout(1200)

            results, source_catalog, scan_stats = await process_current_page(
                context,
                page,
                query=query,
                limit=limit,
                orientation=orientation,
                square_tolerance=square_tolerance,
                inspect_sources=inspect_sources,
                download=download,
                download_mode=download_mode,
                output_dir=output_dir,
                allow_google_source=allow_google_source,
                allow_search_engine_sources=allow_search_engine_sources,
                max_images_per_site=max_images_per_site,
            )

            payload = {
                "ok": True,
                "engine": "yandex_images",
                "query": query,
                "search_url": search_url,
                "limit_requested": limit,
                "results_found": len(results),
                "orientation_filter": orientation,
                "square_tolerance": square_tolerance,
                "scan_stats": scan_stats,
                "inspect_sources": inspect_sources,
                "download": download,
                "download_mode": download_mode,
                "source_policy": {
                    "allow_google_source": allow_google_source,
                    "allow_search_engine_sources": allow_search_engine_sources,
                    "max_images_per_site": max_images_per_site,
                    "default_behavior": (
                        "bloqueia Google e outros buscadores como origem; "
                        "limita o catálogo por site"
                    ),
                },
                "download_options": {
                    "yandex": (
                        "baixa original_url/img_url "
                        "extraído do resultado Yandex"
                    ),
                    "source": (
                        "tenta abrir o detalhe, descobrir a página "
                        "de origem e baixar as imagens encontradas nela"
                    ),
                },
                "results": results,
            }

            if source_catalog is not None:
                payload["source_catalog"] = source_catalog

            Path(json_path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            payload["json_path"] = str(Path(json_path).resolve())

            return payload

        finally:

            await context.close()
            await browser.close()


# ----------------------------------------------------------------------------
# Várias buscas em sequência, na MESMA aba
# ----------------------------------------------------------------------------
# Campo de busca real do cabeçalho do Yandex Images. O <input name="text"> com
# aria-hidden="true" é só o espelho do valor; quem recebe a digitação é o <textarea>.
SEARCH_INPUT_SELECTORS = [
    "form.HeaderForm textarea.mini-suggest__input",
    "form.HeaderForm textarea.HeaderForm-Input",
    "form[role='search'] textarea",
    "textarea.mini-suggest__input",
]
SUBMIT_SELECTOR = "form.HeaderForm button.HeaderForm-Submit"
CLEAR_SELECTOR = "form.HeaderForm button.HeaderForm-Clear"


def _norm_term(value: str | None) -> str:
    return " ".join((value or "").split()).lower()


def _text_param(url: str) -> str:
    try:
        return parse_qs(urlparse(url).query).get("text", [""])[0]
    except Exception:
        return ""


async def find_search_input(page: Page):
    for selector in SEARCH_INPUT_SELECTORS:
        loc = page.locator(selector).first
        try:
            if await loc.count() and await loc.is_visible():
                return loc
        except Exception:
            continue
    return None


async def _wait_text_param(page: Page, term: str, timeout_ms: int = 12_000) -> bool:
    """Espera a URL refletir o novo termo (navegação completa ou pushState)."""
    wanted = _norm_term(term)
    try:
        await page.wait_for_url(
            lambda url: _norm_term(_text_param(url)) == wanted,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        return True
    except PlaywrightTimeoutError:
        return False


async def submit_new_search(
    page: Page,
    term: str,
    *,
    typing_delay_ms: int = 35,
    settle_ms: int = 1500,
) -> str:
    """
    Nova busca NA MESMA ABA, como uma pessoa faria:

      1. localiza o campo de busca (textarea do cabeçalho);
      2. clica, apaga o termo antigo e digita o novo;
      3. aperta ENTER;
      4. se o Enter não disparar a busca, clica no botão "Search";
      5. aguarda a grade de resultados ser substituída.

    Retorna "enter", "submit_button" ou "url_fallback" (navegou direto pela URL
    se o campo não pôde ser usado — o lote continua).
    """
    try:
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(300)

        old_first = await page.evaluate(FIRST_RESULT_HREF_JS)
        same_term = _norm_term(_text_param(page.url)) == _norm_term(term)

        box = await find_search_input(page)
        if box is None:
            raise RuntimeError("campo de busca não encontrado")

        # --- apagar o termo antigo ---
        await box.click()
        await box.fill("")
        if (await box.input_value()) != "":
            await box.press("ControlOrMeta+A")
            await box.press("Backspace")
        if (await box.input_value()) != "":
            clear = page.locator(CLEAR_SELECTOR).first
            if await clear.count() and await clear.is_visible():
                await clear.click()
                await box.click()

        # --- digitar o novo termo ---
        await box.press_sequentially(term, delay=typing_delay_ms)
        if _norm_term(await box.input_value()) != _norm_term(term):
            await box.fill(term)  # garante o texto exato

        # --- ENTER ---
        method = "enter"
        await box.press("Enter")
        navigated = same_term or await _wait_text_param(page, term, 12_000)

        # --- se o Enter não disparou, clica em "Search" ---
        if not navigated:
            submit = page.locator(SUBMIT_SELECTOR).first
            await submit.click(timeout=8_000)
            method = "submit_button"
            if not await _wait_text_param(page, term, 12_000):
                raise RuntimeError("a busca não foi enviada")

        # --- aguardar os resultados novos ---
        await wait_for_yandex_results(page)
        try:
            await page.wait_for_function(
                """(oldFirst) => {
                    const a = document.querySelector('div.SerpItem a.ImagesContentImage-Cover');
                    const cur = a ? (a.getAttribute('href') || '') : '';
                    return cur && cur !== oldFirst;
                }""",
                arg=old_first,
                timeout=12_000,
            )
        except Exception:
            pass  # 1º resultado igual (ou página recarregou); segue
        await page.wait_for_timeout(settle_ms)
        return method

    except Exception as exc:
        if "verificação" in str(exc) or "captcha" in str(exc).lower():
            raise
        # Fallback: navega direto pela URL para não derrubar o lote inteiro.
        await page.goto(
            build_search_url(term),
            wait_until="domcontentloaded",
            timeout=DEFAULT_TIMEOUT_MS,
        )
        await page.wait_for_timeout(1200)
        return "url_fallback"


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
        if lim < 1 or lim > 50:
            raise ValueError(f"limit de '{q}' deve ficar entre 1 e 50.")
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
    inspect_sources: bool = False,
    download: bool = False,
    download_mode: str = "yandex",
    headless: bool = False,
    output_dir: str = "yandex_downloads",
    json_path: str = "yandex_batch_results.json",
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
    max_images_per_site: int = DEFAULT_MAX_IMAGES_PER_SITE,
    pause_between_ms: int = 1500,
) -> dict[str, Any]:
    """
    Várias buscas em sequência, TODAS na mesma aba/navegador.

    A 1ª busca abre a URL do Yandex. As seguintes reutilizam a página: apagam
    o campo de busca, digitam o novo termo e apertam Enter.
    """
    if download_mode not in {"yandex", "source"}:
        raise ValueError("download_mode deve ser 'yandex' ou 'source'.")
    if max_images_per_site < 1:
        raise ValueError("max_images_per_site deve ser >= 1.")
    max_images_per_site = min(max_images_per_site, 500)
    if not 0 <= square_tolerance <= 0.5:
        raise ValueError("square_tolerance deve ficar entre 0 e 0.5.")

    plan = normalize_batch_queries(queries, limit, orientation)
    out = Path(output_dir)

    async with async_playwright() as pw:

        browser = await pw.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )
        context = await browser.new_context(
            locale="pt-BR",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
        )
        page = await context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        searches: list[dict[str, Any]] = []
        visited_sites: set[str] = set()  # sites de origem já abertos no lote

        try:
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
                        await page.goto(
                            build_search_url(q),
                            wait_until="domcontentloaded",
                            timeout=DEFAULT_TIMEOUT_MS,
                        )
                        await page.wait_for_timeout(1200)
                    else:
                        await page.wait_for_timeout(pause_between_ms)
                        entry["search_method"] = await submit_new_search(page, q)
                    entry["search_url"] = page.url

                    qdir = out / f"{n:02d}_{safe_filename(q, f'busca_{n}')}"
                    results, catalog, stats = await process_current_page(
                        context,
                        page,
                        query=q,
                        limit=lim,
                        orientation=ori,
                        square_tolerance=square_tolerance,
                        inspect_sources=inspect_sources,
                        download=download,
                        download_mode=download_mode,
                        output_dir=str(qdir),
                        allow_google_source=allow_google_source,
                        allow_search_engine_sources=allow_search_engine_sources,
                        max_images_per_site=max_images_per_site,
                        visited_sites=visited_sites,
                    )
                    entry.update(
                        ok=True,
                        results_found=len(results),
                        scan_stats=stats,
                        results=results,
                    )
                    if catalog is not None:
                        entry["source_catalog"] = catalog

                except Exception as exc:
                    # Uma busca que falha não derruba as próximas.
                    entry["error"] = str(exc)
                    entry["results_found"] = 0
                    entry["results"] = []

                searches.append(entry)

            payload = {
                "ok": any(s["ok"] for s in searches),
                "engine": "yandex_images",
                "mode": "batch",
                "searches_requested": len(plan),
                "searches_ok": sum(1 for s in searches if s["ok"]),
                "total_results": sum(s["results_found"] for s in searches),
                "inspect_sources": inspect_sources,
                "download": download,
                "download_mode": download_mode,
                "source_policy": {
                    "allow_google_source": allow_google_source,
                    "allow_search_engine_sources": allow_search_engine_sources,
                    "max_images_per_site": max_images_per_site,
                },
                "searches": searches,
            }

            Path(json_path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            payload["json_path"] = str(Path(json_path).resolve())
            return payload

        finally:
            await context.close()
            await browser.close()


app = FastAPI(
    title="Yandex Images Browser API",
    version="1.0.0",
)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "yandex_images",
    }


@app.get("/api/images/search")
async def api_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=50),
    orientation: str = Query(
        "any",
        description="any (qualquer) | horizontal | vertical | square (quadrada)",
    ),
    square_tolerance: float = Query(0.1, ge=0, le=0.5),
    inspect_sources: bool = False,
    download: bool = False,
    download_mode: str = Query("yandex"),
    headless: bool = False,
    output_dir: str = "yandex_downloads",
    json_path: str = "yandex_results.json",
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
    max_images_per_site: int = Query(DEFAULT_MAX_IMAGES_PER_SITE, ge=1, le=500),
):

    try:

        payload = await search_images(
            query=q,
            limit=limit,
            inspect_sources=inspect_sources,
            download=download,
            download_mode=download_mode,
            headless=headless,
            output_dir=output_dir,
            json_path=json_path,
            allow_google_source=allow_google_source,
            allow_search_engine_sources=allow_search_engine_sources,
            max_images_per_site=max_images_per_site,
            orientation=orientation,
            square_tolerance=square_tolerance,
        )

        return JSONResponse(payload)

    except ValueError as exc:

        raise HTTPException(status_code=400, detail=str(exc))

    except Exception as exc:

        raise HTTPException(status_code=500, detail=str(exc))


class BatchRequest(BaseModel):
    # ["gojo", "geto"]  ou  [{"q": "gojo", "limit": 10, "orientation": "vertical"}, ...]
    queries: list[Any]
    limit: int = Field(5, ge=1, le=50)
    orientation: str = "any"
    square_tolerance: float = Field(0.1, ge=0, le=0.5)
    inspect_sources: bool = False
    download: bool = False
    download_mode: str = "yandex"
    headless: bool = False
    output_dir: str = "yandex_downloads"
    json_path: str = "yandex_batch_results.json"
    allow_google_source: bool = False
    allow_search_engine_sources: bool = False
    max_images_per_site: int = Field(DEFAULT_MAX_IMAGES_PER_SITE, ge=1, le=500)
    pause_between_ms: int = Field(1500, ge=0, le=60_000)


async def _run_batch(**kwargs: Any) -> JSONResponse:
    try:
        return JSONResponse(await search_images_batch(**kwargs))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/images/batch")
async def api_batch_get(
    q: list[str] = Query(..., description="Repita q= para cada termo"),
    limit: int = Query(5, ge=1, le=50),
    orientation: str = Query(
        "any",
        description="any (qualquer) | horizontal | vertical | square (quadrada)",
    ),
    square_tolerance: float = Query(0.1, ge=0, le=0.5),
    inspect_sources: bool = False,
    download: bool = False,
    download_mode: str = Query("yandex"),
    headless: bool = False,
    output_dir: str = "yandex_downloads",
    json_path: str = "yandex_batch_results.json",
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
    max_images_per_site: int = Query(DEFAULT_MAX_IMAGES_PER_SITE, ge=1, le=500),
    pause_between_ms: int = Query(1500, ge=0, le=60_000),
):
    return await _run_batch(
        queries=q, limit=limit, orientation=orientation,
        square_tolerance=square_tolerance, inspect_sources=inspect_sources,
        download=download, download_mode=download_mode, headless=headless,
        output_dir=output_dir, json_path=json_path,
        allow_google_source=allow_google_source,
        allow_search_engine_sources=allow_search_engine_sources,
        max_images_per_site=max_images_per_site,
        pause_between_ms=pause_between_ms,
    )


@app.post("/api/images/batch")
async def api_batch_post(body: BatchRequest):
    return await _run_batch(**body.model_dump())


async def run_test(
    query: str = "osama bin laden",
    limit: int = 5,
    mode: str = "both",
    headless: bool = False,
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
    max_images_per_site: int = DEFAULT_MAX_IMAGES_PER_SITE,
    orientation: str = "any",
    square_tolerance: float = 0.1,
):

    if mode not in {
        "yandex",
        "source",
        "both",
    }:
        raise ValueError(
            "mode deve ser yandex, source ou both."
        )

    print("=" * 78)
    print("YANDEX IMAGES — TESTE")
    print("=" * 78)
    print("Busca:", query)
    print("Limite:", limit)
    print("Filtro de proporção:", orientation)
    print("Modo:", mode)
    print("Permitir Google como origem:", allow_google_source)
    print("Permitir outros buscadores como origem:", allow_search_engine_sources)
    print("Máximo de imagens por site:", max_images_per_site)
    print()

    inspect = mode in {
        "source",
        "both",
    }

    download_mode = (
        "source"
        if mode in {
            "source",
            "both",
        }
        else "yandex"
    )

    payload = await search_images(
        query=query,
        limit=limit,
        inspect_sources=inspect,
        download=True,
        download_mode=download_mode,
        headless=headless,
        output_dir="yandex_test_downloads",
        json_path="yandex_test_results.json",
        allow_google_source=allow_google_source,
        allow_search_engine_sources=allow_search_engine_sources,
        max_images_per_site=max_images_per_site,
        orientation=orientation,
        square_tolerance=square_tolerance,
    )

    print(
        "Resultados encontrados:",
        payload["results_found"],
    )

    for item in payload["results"]:

        print()
        print(
            f"#{item['rank']} "
            f"{item.get('title', '')[:100]}"
        )
        print(
            "  thumbnail:",
            item.get(
                "thumbnail_url"
            ),
        )
        print(
            "  original:",
            item.get(
                "original_url"
            ),
        )
        print(
            "  resultado:",
            item.get(
                "result_url"
            ),
        )
        print(
            "  origem:",
            item.get(
                "source_page"
            )
            or "(não descoberta)",
        )
        print(
            "  dimensões:",
            item.get(
                "width"
            ),
            "x",
            item.get(
                "height"
            ),
        )
        print(
            "  proporção:",
            item.get("orientation"),
            f"({item.get('thumb_width')}x{item.get('thumb_height')},",
            f"razão {item.get('aspect_ratio')})",
        )
        print(
            "  baixada:",
            item.get(
                "downloaded"
            ),
        )
        print(
            "  arquivo:",
            item.get(
                "download_path"
            ),
        )

        if item.get(
            "download_error"
        ):
            print(
                "  erro:",
                item[
                    "download_error"
                ],
            )

        if item.get(
            "source_discovery_error"
        ):
            print(
                "  descoberta:",
                item[
                    "source_discovery_error"
                ],
            )

        if item.get("source_blocked"):
            print(
                "  origem bloqueada:",
                item.get("source_blocked_reason", "")
            )

    if "source_catalog" in payload:

        catalog = payload[
            "source_catalog"
        ]

        print()
        print(
            "Sites de origem:",
            catalog.get(
                "site_count",
                0,
            ),
        )

        for site in catalog.get(
            "sites",
            [],
        ):

            print()
            print(
                "SITE:",
                site.get(
                    "source_page"
                ),
            )

            print(
                "  imagens:",
                site.get(
                    "image_count",
                    0,
                ),
            )

            for image in site.get(
                "images",
                [],
            )[:20]:

                print(
                    f"    [{image.get('index')}] "
                    f"{image.get('name') or image.get('url')}"
                )

    print()
    print(
        "JSON:",
        Path(
            "yandex_test_results.json"
        ).resolve(),
    )

    print(
        "Downloads:",
        Path(
            "yandex_test_downloads"
        ).resolve(),
    )

    return payload


def main():
    parser = argparse.ArgumentParser(
        description="Yandex Images Browser API/tester"
    )

    parser.add_argument(
        "--test",
        action="store_true",
        help="Executa o teste.",
    )

    parser.add_argument(
        "--query",
        default="osama bin laden",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
    )

    parser.add_argument(
        "--mode",
        choices=[
            "yandex",
            "source",
            "both",
        ],
        default="both",
        help=(
            "yandex = imagem direta do resultado; "
            "source = acessar fonte; "
            "both = fluxo completo."
        ),
    )

    parser.add_argument(
        "--headless",
        action="store_true",
    )

    parser.add_argument(
        "--allow-google-source",
        action="store_true",
        help=(
            "Permite Google como página de origem. "
            "Por padrão Google é bloqueado. Use junto com modo source/both."
        ),
    )

    parser.add_argument(
        "--allow-search-engine-sources",
        action="store_true",
        help=(
            "Permite Google e outros buscadores como origem. "
            "Mais amplo que --allow-google-source."
        ),
    )

    parser.add_argument(
        "--max-images-per-site",
        type=int,
        default=DEFAULT_MAX_IMAGES_PER_SITE,
        help="Limite de imagens coletadas por página de origem (1-500).",
    )

    parser.add_argument(
        "--orientation",
        default="any",
        help="Proporção da thumbnail: any (qualquer), horizontal, vertical ou square (quadrada).",
    )

    parser.add_argument(
        "--square-tolerance",
        type=float,
        default=0.1,
        help="Quão perto de 1:1 conta como quadrada (0.1 = razão entre 0.9 e 1.1).",
    )

    parser.add_argument(
        "--batch",
        nargs="+",
        metavar="TERMO",
        help='Várias buscas na mesma aba. Ex.: --batch "gojo" "geto" --limit 5',
    )

    parser.add_argument(
        "--inspect-sources",
        action="store_true",
        help="(com --batch) acessa os sites de origem e cataloga as imagens deles.",
    )

    parser.add_argument(
        "--download",
        action="store_true",
        help="(com --batch) baixa as imagens.",
    )

    parser.add_argument(
        "--download-mode",
        choices=["yandex", "source"],
        default="yandex",
        help="(com --batch) yandex = imagem direta; source = imagens da página de origem.",
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8003,
    )

    args = parser.parse_args()

    if args.batch:
        payload = asyncio.run(
            search_images_batch(
                queries=args.batch,
                limit=max(1, min(args.limit, 50)),
                orientation=args.orientation,
                square_tolerance=args.square_tolerance,
                inspect_sources=args.inspect_sources,
                download=args.download,
                download_mode=args.download_mode,
                headless=args.headless,
                output_dir="yandex_batch_downloads",
                json_path="yandex_batch_results.json",
                allow_google_source=args.allow_google_source,
                allow_search_engine_sources=args.allow_search_engine_sources,
                max_images_per_site=max(1, min(args.max_images_per_site, 500)),
            )
        )
        for sr in payload["searches"]:
            status = "OK" if sr["ok"] else f"ERRO: {sr.get('error')}"
            print(
                f"[{sr['index']}] {sr['query']!r} [{sr.get('orientation_filter')}]: "
                f"{sr['results_found']} imagens ({sr.get('search_method', '-')}) {status}"
            )
            warn = (sr.get("scan_stats") or {}).get("warning")
            if warn:
                print("     aviso:", warn)
        print("\nJSON salvo em:", payload["json_path"])
        return

    if args.test:

        asyncio.run(
            run_test(
                query=args.query,
                limit=max(
                    1,
                    min(
                        args.limit,
                        50,
                    ),
                ),
                mode=args.mode,
                headless=args.headless,
                allow_google_source=args.allow_google_source,
                allow_search_engine_sources=args.allow_search_engine_sources,
                max_images_per_site=max(
                    1,
                    min(args.max_images_per_site, 500),
                ),
                orientation=args.orientation,
                square_tolerance=args.square_tolerance,
            )
        )

        return

    print(
        f"Yandex Images API: "
        f"http://{args.host}:{args.port}"
    )

    print(
        "Exemplo:"
        " /api/images/search?q=gojo&limit=5"
    )

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
