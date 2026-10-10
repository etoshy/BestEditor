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


async def collect_yandex_results(
    page: Page,
    limit: int,
) -> list[dict[str, Any]]:
    """
    Usa diretamente a estrutura mostrada no HTML do usuário:
        div.SerpItem
        a.ImagesContentImage-Cover
        img.ImagesContentImage-Image_clickable
    """

    # Aguarda um elemento muito específico dos resultados reais.
    try:
        await page.wait_for_selector(
            "div.SerpItem a.ImagesContentImage-Cover",
            timeout=DEFAULT_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        # fallback, mantendo robustez entre versões do Yandex.
        await page.wait_for_selector(
            "div.SerpList img.ImagesContentImage-Image",
            timeout=10000,
        )

    # Dispara lazy-loading.
    for _ in range(8):
        await page.mouse.wheel(
            0,
            1200,
        )
        await page.wait_for_timeout(
            400,
        )

    cards = page.locator(
        "div.SerpItem"
    )

    count = await cards.count()
    results: list[dict[str, Any]] = []
    seen_images = set()

    for dom_index in range(count):

        if len(results) >= limit:
            break

        card = cards.nth(
            dom_index
        )

        try:
            link = card.locator(
                "a.ImagesContentImage-Cover"
            ).first

            image = card.locator(
                "img.ImagesContentImage-Image"
            ).first

            if await link.count() == 0:
                continue

            href = await link.get_attribute(
                "href"
            )

            if not href:
                continue

            thumb = ""

            if await image.count():
                thumb = await image.get_attribute(
                    "src"
                ) or ""

            alt = ""

            if await image.count():
                alt = await image.get_attribute(
                    "alt"
                ) or ""

            image_url = extract_img_url_from_yandex_result(
                href
            )

            # O resultado fornecido pelo usuário guarda a imagem real em
            # img_url. Não queremos duplicatas.
            if not image_url:
                continue

            image_url = normalize_url(
                YANDEX_BASE,
                image_url,
            )

            if image_url in seen_images:
                continue

            seen_images.add(
                image_url
            )

            # Tamanho do elemento exibido.
            width = None
            height = None

            raw_width = await image.get_attribute(
                "width"
            ) if await image.count() else None

            raw_height = await image.get_attribute(
                "height"
            ) if await image.count() else None

            try:
                if raw_width:
                    width = float(raw_width)
                if raw_height:
                    height = float(raw_height)
            except Exception:
                pass

            source_domain = (
                urlparse(
                    image_url
                ).netloc
            )

            results.append(
                {
                    "rank": len(results) + 1,
                    "yandex_rank": len(results),
                    "title": alt,
                    "alt": alt,
                    "thumbnail_url": normalize_url(
                        YANDEX_BASE,
                        thumb,
                    ),
                    "original_url": image_url,
                    "result_url": normalize_url(
                        YANDEX_BASE,
                        href,
                    ),
                    "source_page": "",
                    "source_domain": source_domain,
                    "width": width,
                    "height": height,
                    "dom_index": dom_index,
                    "clicked": False,
                    "downloaded": False,
                    "download_path": "",
                    "error": "",
                }
            )

        except Exception as exc:
            continue

    return results


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
) -> dict[str, Any]:

    sites = []
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


async def search_images_in_session(
    page: Page,
    context: BrowserContext,
    *,
    query: str,
    limit: int = 5,
    inspect_sources: bool = False,
    download: bool = False,
    download_mode: str = "yandex",
    output_dir: str = "yandex_downloads",
    json_path: str = "yandex_results.json",
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
    max_images_per_site: int = DEFAULT_MAX_IMAGES_PER_SITE,
) -> dict[str, Any]:
    if download_mode not in {"yandex", "source"}:
        raise ValueError("download_mode deve ser 'yandex' ou 'source'.")
    if max_images_per_site < 1:
        raise ValueError("max_images_per_site deve ser >= 1.")
    max_images_per_site = min(max_images_per_site, 500)
    search_url = build_search_url(query)
    await page.goto(search_url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
    await page.wait_for_timeout(1200)
    results = await collect_yandex_results(page, limit)
    if not results:
        raise RuntimeError("Nenhum resultado de imagem foi encontrado no Yandex.")
    source_catalog = None
    if inspect_sources or download_mode == "source":
        source_catalog = await inspect_source_catalog(
            context, results, max_images_per_site=max_images_per_site,
            allow_google_source=allow_google_source, allow_search_engine_sources=allow_search_engine_sources,
        )
    if download:
        if download_mode == "yandex":
            await download_direct_results(context, results, output_dir)
        else:
            if source_catalog is None:
                source_catalog = await inspect_source_catalog(
                    context, results, max_images_per_site=max_images_per_site,
                    allow_google_source=allow_google_source, allow_search_engine_sources=allow_search_engine_sources,
                )
            await download_source_catalog(context, source_catalog, str(Path(output_dir) / "sources"))
    return {
        "ok": True, "engine": "yandex_images", "query": query, "search_url": search_url,
        "limit_requested": limit, "results_found": len(results), "inspect_sources": inspect_sources,
        "download": download, "download_mode": download_mode,
        "results": results,
        **({"source_catalog": source_catalog} if source_catalog is not None else {}),
    }


async def search_images(
    *, query: str, limit: int = 5, inspect_sources: bool = False, download: bool = False,
    download_mode: str = "yandex", headless: bool = False, output_dir: str = "yandex_downloads",
    json_path: str = "yandex_results.json", allow_google_source: bool = False,
    allow_search_engine_sources: bool = False, max_images_per_site: int = DEFAULT_MAX_IMAGES_PER_SITE,
) -> dict[str, Any]:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        context = await browser.new_context(
            locale="pt-BR", viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
        )
        page = await context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        try:
            return await search_images_in_session(
                page, context, query=query, limit=limit, inspect_sources=inspect_sources, download=download,
                download_mode=download_mode, output_dir=output_dir, json_path=json_path,
                allow_google_source=allow_google_source, allow_search_engine_sources=allow_search_engine_sources,
                max_images_per_site=max_images_per_site,
            )
        finally:
            await context.close()
            await browser.close()
