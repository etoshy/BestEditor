"""Visita aos sites de origem — igual para todos os buscadores.

Reaproveita `inspect_source_page()` do motor Yandex (a coleta mais completa:
og:image / twitter:image / JSON-LD / <img> / srcset / data-src / links diretos,
com rolagem para lazy-load) e a mesma política de bloqueio de buscadores.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from .adapters import normalize_site
from .source_policy import should_skip_source_url

# inspector(urls, max_images=..., headless=...) -> {url: site_dict_bruto}
Inspector = Callable[..., Awaitable[dict[str, dict[str, Any]]]]


async def default_inspector(urls: list[str], *, max_images: int, headless: bool) -> dict[str, dict[str, Any]]:
    from playwright.async_api import async_playwright

    from .engines import yandex_image_api as yandex

    sites: dict[str, dict[str, Any]] = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless, args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            locale="pt-BR",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
        )
        try:
            for url in urls:
                sites[url] = await yandex.inspect_source_page(context, url, max_images=max_images)
        finally:
            await context.close()
            await browser.close()
    return sites


def _blocked_stub(url: str, reason: str) -> dict[str, Any]:
    return {
        "source_page": url, "og": {}, "image_count": 0, "images": [],
        "error": None, "blocked": True, "blocked_reason": reason, "result_image_url": "",
    }


async def inspect_missing_sources(
    results: list[dict[str, Any]],
    known_sites: dict[str, dict[str, Any]],
    spec,
    *,
    inspector: Inspector | None = None,
    log: Callable[[str], None] = lambda _m: None,
) -> int:
    """Cataloga as páginas de origem que ainda não têm catálogo.

    `known_sites` é atualizado no lugar. Devolve quantas páginas foram abertas.
    Resultados cujo site é bloqueado pela política recebem source_blocked=True.
    """
    pending: list[str] = []
    for hit in results:
        url = hit.get("source_page") or ""
        if not url or url in known_sites or url in pending:
            continue
        skip, reason = should_skip_source_url(
            url,
            allow_google_source=spec.allow_google_source,
            allow_search_engine_sources=spec.allow_search_engine_sources,
        )
        if skip:
            known_sites[url] = _blocked_stub(url, reason)
            continue
        pending.append(url)

    for hit in results:
        site = known_sites.get(hit.get("source_page") or "")
        if site and site.get("blocked"):
            hit["source_blocked"] = True
            hit["source_blocked_reason"] = site["blocked_reason"]

    if not pending:
        return 0

    inspector = inspector or default_inspector
    log(f"abrindo {len(pending)} site(s) de origem…")
    raw_sites = await inspector(pending, max_images=spec.max_images_per_site, headless=spec.headless)
    for url in pending:
        raw = raw_sites.get(url) or {"source_page": url, "error": "site não inspecionado"}
        raw.setdefault("source_page", url)
        known_sites[url] = normalize_site(raw)
    return len(pending)
