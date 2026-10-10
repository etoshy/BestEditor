# -*- coding: utf-8 -*-
"""
Brave Images Browser API/tester.

Baseado no HTML real do Brave Images fornecido no projeto:
    https://search.brave.com/images?q=gojo&source=web
    https://search.brave.com/images?q=gojo+eye&source=images

O Brave usa cards:
    button.image-result
        img[data-rank]
        img[src="https://imgs.search.brave.com/..."]

O src das imagens exibidas pelo Brave é um proxy/cache.
Quando possível, este script:
1. abre o Brave Images em Chromium real via Playwright;
2. coleta os cards e metadados (rank, alt, site, título);
3. decodifica o URL original embutido no proxy imgs.search.brave.com;
4. abre/clica o resultado para tentar descobrir a página de origem e a
   imagem original;
5. opcionalmente baixa as imagens;
6. expõe uma API FastAPI semelhante à API de teste do Bing.

Instalação:
    py -m pip install -r requirements.txt
    py -m playwright install chromium

Teste:
    py brave_image_api.py --test

API:
    py brave_image_api.py

Exemplos:
    http://127.0.0.1:8001/api/images/search?q=gojo
    http://127.0.0.1:8001/api/images/search?q=gojo%20eye&limit=5
    http://127.0.0.1:8001/api/images/search?q=gojo%20eye&download=true&download_mode=original&limit=5
    http://127.0.0.1:8001/api/images/search?q=gojo%20eye&download=true&download_mode=brave&limit=5

Observação:
O Brave pode apresentar verificação/anti-bot. Nesse caso o script mantém
o navegador visível por padrão para permitir que a verificação seja feita.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, unquote, urljoin, urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn
from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


BRAVE_IMAGES = "https://search.brave.com/images"
DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_LIMIT = 3


DEFAULT_MAX_IMAGES_PER_SITE = 50

# ----------------------------------------------------------------------------
# Filtro por proporção (orientação) da THUMBNAIL
# ----------------------------------------------------------------------------
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


# ----------------------------------------------------------------------------
# Acesso aos sites de origem (opcional, como no Yandex)
# ----------------------------------------------------------------------------
SEARCH_ENGINE_HOSTS = {
    "google.com", "google.com.br", "www.google.com", "www.google.com.br",
    "bing.com", "www.bing.com", "search.yahoo.com", "duckduckgo.com",
    "www.duckduckgo.com", "startpage.com", "www.startpage.com",
    "yandex.com", "yandex.ru", "brave.com", "search.brave.com",
}


@dataclass
class SourcePolicy:
    """Controla se/como as páginas de origem dos resultados são acessadas."""
    inspect_sources: bool = False        # cataloga TODAS as imagens da página de origem
    visit_original: bool = False         # abre a origem só p/ achar a imagem original (download_mode=original)
    allow_google_source: bool = False
    allow_search_engine_sources: bool = False
    max_images_per_site: int = DEFAULT_MAX_IMAGES_PER_SITE

    @property
    def visit(self) -> bool:
        return self.inspect_sources or self.visit_original


def make_source_policy(
    *,
    inspect_sources: bool = False,
    download: bool = False,
    download_mode: str = "original",
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
    max_images_per_site: int = DEFAULT_MAX_IMAGES_PER_SITE,
) -> SourcePolicy:
    return SourcePolicy(
        inspect_sources=bool(inspect_sources),
        visit_original=bool(download and download_mode == "original"),
        allow_google_source=bool(allow_google_source),
        allow_search_engine_sources=bool(allow_search_engine_sources),
        max_images_per_site=max(1, min(int(max_images_per_site), 500)),
    )


def is_google_host(host: str) -> bool:
    host = (host or "").lower().split(":", 1)[0].strip(".")
    return (
        host == "google.com" or host.endswith(".google.com")
        or host == "google.com.br" or host.endswith(".google.com.br")
    )


def is_search_engine_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().split(":", 1)[0].strip(".")
    except Exception:
        return False
    return (
        is_google_host(host)
        or host in SEARCH_ENGINE_HOSTS
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
    q: str,
    *,
    source: str = "images",
    offset: int = 0,
) -> str:
    """
    O HTML fornecido usa:
        /images?q=gojo&source=web
        /images?q=gojo+eye&source=images

    Mantemos source configurável para facilitar testes.
    """
    return (
        f"{BRAVE_IMAGES}"
        f"?q={quote_plus(q)}"
        f"&source={quote_plus(source)}"
        f"&offset={max(0, int(offset))}"
    )


def safe_filename(name: str, default: str = "imagem") -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:180] or default


def decode_brave_proxy_url(proxy_url: str | None) -> str | None:
    """
    Converte URLs do tipo:

    https://imgs.search.brave.com/<hash>/rs:fit:500:0:1:0/g:ce/<BASE64>

    para o URL original, quando o payload estiver disponível em Base64.

    O HTML fornecido pelo usuário contém exatamente esse padrão.
    """
    if not proxy_url:
        return None

    try:
        parsed = urlparse(proxy_url)
        host = parsed.netloc.lower()

        if host != "imgs.search.brave.com":
            return proxy_url

        marker = "/g:ce/"
        if marker not in parsed.path:
            return None

        encoded = parsed.path.split(marker, 1)[1].strip("/")
        if not encoded:
            return None

        # O Brave normalmente usa base64 sem padding.
        encoded += "=" * (-len(encoded) % 4)

        raw = base64.urlsafe_b64decode(encoded)
        decoded = raw.decode("utf-8", errors="strict")

        if decoded.startswith(("http://", "https://")):
            return decoded

    except Exception:
        pass

    return None


async def wait_for_brave_results(page: Page) -> None:
    """
    Espera pelos cards do Brave.

    Se houver uma página de verificação, não tentamos contorná-la.
    O navegador fica visível por padrão para o usuário poder resolver
    a verificação normalmente.
    """
    try:
        await page.wait_for_selector(
            "button.image-result img[data-rank]",
            timeout=DEFAULT_TIMEOUT_MS,
        )
        return
    except PlaywrightTimeoutError:
        # Alguns carregamentos podem usar apenas .image-result.
        try:
            await page.wait_for_selector(
                "button.image-result",
                timeout=10_000,
            )
            return
        except PlaywrightTimeoutError:
            raise RuntimeError(
                "Brave não exibiu os resultados de imagens dentro do tempo esperado. "
                "Se apareceu uma verificação no navegador, conclua a verificação "
                "e execute novamente."
            )


async def read_thumbnail_size(img) -> dict[str, Any]:
    """
    Lê o tamanho da THUMBNAIL já carregada no card (naturalWidth/Height).
    O proxy do Brave (rs:fit:500:0) mantém a proporção da imagem, então a
    razão largura/altura da thumbnail é a da imagem original.
    Se ainda for lazy-load, rola até o card e espera carregar.
    """
    probe = """
    el => ({
        nw: el.naturalWidth || 0,
        nh: el.naturalHeight || 0,
        placeholder: (el.currentSrc || el.src || '').startsWith('data:'),
        rw: el.getBoundingClientRect().width || 0,
        rh: el.getBoundingClientRect().height || 0,
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
        data = await img.evaluate(probe)
        if not data["nw"] or data["placeholder"]:
            try:
                await img.scroll_into_view_if_needed(timeout=3_000)
            except Exception:
                pass
            await img.evaluate(wait_loaded)
            data = await img.evaluate(probe)
    except Exception:
        return {"width": None, "height": None, "source": None}

    if data["nw"] and data["nh"] and not data["placeholder"]:
        return {"width": data["nw"], "height": data["nh"], "source": "natural"}
    if data["rw"] and data["rh"]:
        return {"width": round(data["rw"]), "height": round(data["rh"]), "source": "displayed"}
    return {"width": None, "height": None, "source": None}


async def collect_result_cards(
    page: Page,
    wanted: int,
    *,
    orientation: str = "any",
    square_tolerance: float = 0.1,
    max_scroll_rounds: int = 25,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Extrai os cards (button.image-result) e aplica o filtro de proporção.

    `wanted` = quantas imagens QUE PASSAM NO FILTRO queremos. Se os primeiros
    cards não bastam, rola a página para o Brave carregar mais e continua.

    Retorna (resultados, estatísticas).
    """
    orientation = normalize_orientation(orientation)
    await wait_for_brave_results(page)

    # As imagens são lazy-load. Rola um pouco para disparar o carregamento.
    for _ in range(3):
        await page.mouse.wheel(0, 1000)
        await page.wait_for_timeout(500)

    stats: dict[str, Any] = {
        "cards_scanned": 0,
        "filtered_out": 0,
        "unknown_orientation": 0,
        "scroll_rounds": 0,
    }
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    idle_rounds = 0

    while True:
        cards = page.locator("button.image-result")
        count = await cards.count()
        new_cards = 0

        for dom_index in range(count):
            if len(results) >= wanted:
                break

            card = cards.nth(dom_index)
            try:
                # Não incluir o bloco "Pesquisar em outro lugar".
                if await card.locator(".image-search-elsewhere").count():
                    continue

                img = card.locator("img[data-rank]").first
                if await img.count() == 0:
                    img = card.locator("img").first
                if await img.count() == 0:
                    continue

                rank_raw = await img.get_attribute("data-rank")
                key = rank_raw if rank_raw is not None else f"dom{dom_index}"
                if key in seen:
                    continue
                seen.add(key)
                new_cards += 1
                stats["cards_scanned"] += 1

                # ---- proporção pela thumbnail ----
                size = await read_thumbnail_size(img)
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

                src = await img.get_attribute("src")
                alt = await img.get_attribute("alt") or ""

                source_el = card.locator(".image-metadata-source").first
                title_el = card.locator(".image-metadata-title").first
                source = (
                    (await source_el.inner_text()).strip()
                    if await source_el.count() else ""
                )
                title = (
                    (await title_el.inner_text()).strip()
                    if await title_el.count() else ""
                )

                try:
                    brave_rank = int(rank_raw) if rank_raw is not None else len(results)
                except ValueError:
                    brave_rank = len(results)

                results.append(
                    {
                        "rank": len(results) + 1,
                        "brave_rank": brave_rank,
                        "dom_index": dom_index,
                        "title": title,
                        "alt": alt,
                        "source": source,
                        "proxy_url": src or "",
                        "original_url": decode_brave_proxy_url(src),
                        "thumb_width": size["width"],
                        "thumb_height": size["height"],
                        "aspect_ratio": ratio,
                        "orientation": kind,
                        "orientation_source": size["source"],
                        "source_page": None,
                        "detail_url": None,
                        "detail_opened": False,
                        "query": None,
                    }
                )
            except Exception:
                continue

        if len(results) >= wanted:
            break
        if stats["scroll_rounds"] >= max_scroll_rounds:
            break

        idle_rounds = idle_rounds + 1 if new_cards == 0 else 0
        if idle_rounds >= 3:  # a página parou de carregar novos cards
            break

        await page.mouse.wheel(0, 1500)
        await page.wait_for_timeout(700)
        stats["scroll_rounds"] += 1

    return results, stats


def image_name_from_url(url: str, alt: str = "", index: int = 0) -> str:
    """Gera um nome útil para a imagem a partir do arquivo/alt."""
    path_name = Path(urlparse(url).path).name
    if path_name:
        name = unquote(path_name)
        if name and name not in {"/", "."}:
            return safe_filename(name)
    if alt.strip():
        return safe_filename(alt.strip())
    return f"imagem_{index:03d}"


async def collect_all_source_images(
    context: BrowserContext,
    source_page_url: str,
    page_timeout: int = DEFAULT_TIMEOUT_MS,
    max_images: int = DEFAULT_MAX_IMAGES_PER_SITE,
) -> dict[str, Any]:
    """
    Varre a página de origem e retorna TODAS as imagens relevantes encontradas.

    Inclui imagens de <img>, og:image/twitter:image, JSON-LD e links diretos.
    Pequenos ícones, logos e pixels de tracking são descartados por dimensões
    quando essas dimensões estão disponíveis.
    """
    data: dict[str, Any] = {
        "source_page": source_page_url,
        "source_page_opened": False,
        "source_images": [],
        "source_images_count": 0,
        "source_page_error": None,
    }
    if not source_page_url:
        data["source_page_error"] = "source_page ausente"
        return data

    page = await context.new_page()
    page.set_default_timeout(page_timeout)
    try:
        await page.goto(source_page_url, wait_until="domcontentloaded", timeout=page_timeout)
        await page.wait_for_timeout(1200)
        data["source_page_opened"] = True

        # Lazy loading: percorre a página até o final, sem ficar preso em loops.
        last_height = 0
        stable = 0
        for _ in range(30):
            height = await page.evaluate("document.body ? document.body.scrollHeight : 0")
            await page.mouse.wheel(0, 1200)
            await page.wait_for_timeout(350)
            if height == last_height:
                stable += 1
                if stable >= 3:
                    break
            else:
                stable = 0
            last_height = height

        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(300)

        rows = await page.locator("img").evaluate_all(
            """
            els => els.map((img, i) => ({
                url: img.currentSrc || img.src || '',
                src: img.src || '',
                srcset: img.srcset || '',
                alt: img.alt || '',
                title: img.title || '',
                width: img.naturalWidth || 0,
                height: img.naturalHeight || 0,
                displayedWidth: img.getBoundingClientRect().width || 0,
                displayedHeight: img.getBoundingClientRect().height || 0,
                index: i
            }))
            .filter(x => x.url || x.src || x.srcset)
            """
        )

        meta_urls = await page.locator(
            'meta[property="og:image"], meta[property="og:image:url"], '
            'meta[name="twitter:image"], meta[name="twitter:image:src"]'
        ).evaluate_all("els => els.map(x => x.content || '').filter(Boolean)")

        jsonld_urls = await page.locator('script[type="application/ld+json"]').evaluate_all(
            """
            els => {
                const out = [];
                const walk = (v) => {
                    if (!v) return;
                    if (typeof v === 'string' && /^https?:\\/\\//i.test(v)) {
                        if (/\\.(?:jpe?g|png|webp|gif|avif|bmp|svg)(?:[?#]|$)/i.test(v)) out.push(v);
                        return;
                    }
                    if (Array.isArray(v)) { v.forEach(walk); return; }
                    if (typeof v === 'object') {
                        for (const [k,val] of Object.entries(v)) {
                            if (/^(image|contentUrl|thumbnailUrl|url)$/i.test(k)) walk(val);
                            else if (typeof val === 'object') walk(val);
                        }
                    }
                };
                for (const el of els) {
                    try { walk(JSON.parse(el.textContent || '{}')); } catch (_) {}
                }
                return [...new Set(out)];
            }
            """
        )

        link_urls = await page.locator("a[href]").evaluate_all(
            """
            els => els.map(a => a.href || '').filter(u =>
                /^https?:\\/\\//i.test(u) &&
                /\\.(?:jpe?g|png|webp|gif|avif|bmp|svg)(?:[?#]|$)/i.test(u)
            )
            """
        )

        found: dict[str, dict[str, Any]] = {}
        def add(url, alt="", title="", width=0, height=0, kind="img"):
            if not url or not url.startswith(("http://", "https://")):
                return
            host = urlparse(url).netloc.lower()
            if host in {"search.brave.com", "imgs.search.brave.com"}:
                return
            width = int(width or 0); height = int(height or 0)
            # Remove trackers/icons; preserve images where dimensions are unknown.
            if width and height and (width < 120 or height < 120):
                return
            key = url.split('#', 1)[0]
            item = found.get(key)
            candidate = {
                "original_url": url,
                "name": image_name_from_url(url, alt or title, len(found)+1),
                "alt": alt or "",
                "title": title or "",
                "width": width or None,
                "height": height or None,
                "kind": kind,
            }
            if item is None or (width * height) > ((item.get("width") or 0) * (item.get("height") or 0)):
                found[key] = candidate

        for row in rows:
            add(row.get("url"), row.get("alt"), row.get("title"), row.get("width"), row.get("height"), "img")
            # Prefer candidates from srcset that have actual URL variants.
            for part in (row.get("srcset") or "").split(","):
                bits = part.strip().split()
                if bits:
                    add(bits[0], row.get("alt"), row.get("title"), row.get("width"), row.get("height"), "srcset")
        for u in meta_urls:
            add(u, kind="meta")
        for u in jsonld_urls:
            add(u, kind="jsonld")
        for u in link_urls:
            add(u, kind="link")

        images = list(found.values())
        data["source_images_total_found"] = len(images)
        if len(images) > max_images:
            # Limite por site: mantém as maiores (as sem dimensão ficam por último).
            images.sort(key=lambda x: (x.get("width") or 0) * (x.get("height") or 0), reverse=True)
            images = images[:max_images]
            data["source_images_truncated"] = True
        for i, item in enumerate(images, 1):
            item["index"] = i
            item["source_page"] = source_page_url
            item["name"] = safe_filename(item.get("name") or f"imagem_{i:03d}")

        data["source_images"] = images
        data["source_images_count"] = len(images)
    except Exception as exc:
        data["source_page_error"] = str(exc)
    finally:
        try: await page.close()
        except Exception: pass
    return data


async def find_original_on_source_page(
    context: BrowserContext,
    source_page_url: str,
    brave_original_url: str | None = None,
) -> dict[str, Any]:
    """
    Abre a página original indicada pelo resultado do Brave e procura a imagem
    em elementos reais da página: og:image, twitter:image, JSON-LD, img/src,
    srcset e links de imagem.

    O objetivo é não baixar o thumbnail/proxy do Brave quando o usuário escolhe
    download_mode="original".
    """
    data: dict[str, Any] = {
        "source_page": source_page_url,
        "source_page_opened": False,
        "original_found_on_source": False,
        "original_source_url": None,
        "source_image_width": None,
        "source_image_height": None,
        "source_page_error": None,
    }

    if not source_page_url:
        data["source_page_error"] = "source_page ausente"
        return data

    page = await context.new_page()
    page.set_default_timeout(DEFAULT_TIMEOUT_MS)

    try:
        await page.goto(
            source_page_url,
            wait_until="domcontentloaded",
            timeout=DEFAULT_TIMEOUT_MS,
        )
        await page.wait_for_timeout(1200)
        data["source_page_opened"] = True

        # Ativa lazy-loading sem precisar rolar a página inteira.
        for _ in range(5):
            await page.mouse.wheel(0, 1000)
            await page.wait_for_timeout(300)

        candidates = await page.locator("img").evaluate_all(
            """
            els => els.map((img, i) => ({
                src: img.currentSrc || img.src || "",
                srcset: img.srcset || "",
                alt: img.alt || "",
                width: img.naturalWidth || 0,
                height: img.naturalHeight || 0,
                displayedWidth: img.getBoundingClientRect().width || 0,
                displayedHeight: img.getBoundingClientRect().height || 0,
                index: i
            })).filter(x => x.src || x.srcset)
            """
        )

        # Metadados que frequentemente apontam para a imagem original.
        meta_urls = await page.locator(
            'meta[property="og:image"], '
            'meta[property="og:image:url"], '
            'meta[name="twitter:image"], '
            'meta[name="twitter:image:src"]'
        ).evaluate_all(
            "els => els.map(x => x.content || '').filter(Boolean)"
        )

        # JSON-LD também pode conter image/image.url.
        jsonld_urls = await page.locator('script[type="application/ld+json"]').evaluate_all(
            """
            els => {
                const out = [];
                for (const el of els) {
                    try {
                        const x = JSON.parse(el.textContent || '{}');
                        const walk = (v) => {
                            if (!v) return;
                            if (typeof v === 'string' && /^https?:\\/\\//i.test(v)) {
                                if (/\\.(?:jpe?g|png|webp|gif|avif|bmp|svg)(?:[?#]|$)/i.test(v)) out.push(v);
                                return;
                            }
                            if (Array.isArray(v)) v.forEach(walk);
                            else if (typeof v === 'object') {
                                for (const [k, val] of Object.entries(v)) {
                                    if (/^(image|contentUrl|thumbnailUrl|url)$/i.test(k)) walk(val);
                                    else if (typeof val === 'object') walk(val);
                                }
                            }
                        };
                        walk(x);
                    } catch (_) {}
                }
                return [...new Set(out)];
            }
            """
        )

        # Links diretos para arquivos de imagem.
        link_urls = await page.locator('a[href]').evaluate_all(
            """
            els => els.map(a => a.href || '').filter(u =>
                /^https?:\\/\\//i.test(u) &&
                /\\.(?:jpe?g|png|webp|gif|avif|bmp|svg)(?:[?#]|$)/i.test(u)
            )
            """
        )

        all_candidates: list[dict[str, Any]] = []

        def add_candidate(url: str, width=0, height=0, kind="unknown"):
            if not url or not url.startswith(("http://", "https://")):
                return
            if "imgs.search.brave.com" in url:
                return
            all_candidates.append({
                "url": url,
                "width": int(width or 0),
                "height": int(height or 0),
                "area": int(width or 0) * int(height or 0),
                "kind": kind,
            })

        for c in candidates:
            add_candidate(c.get("src", ""), c.get("width"), c.get("height"), "img")
            # Escolhe também a maior entrada do srcset.
            for part in (c.get("srcset") or "").split(","):
                part = part.strip()
                if not part:
                    continue
                bits = part.split()
                add_candidate(bits[0], c.get("width"), c.get("height"), "srcset")

        for u in meta_urls:
            add_candidate(u, kind="meta")
        for u in jsonld_urls:
            add_candidate(u, kind="jsonld")
        for u in link_urls:
            add_candidate(u, kind="link")

        # Remove duplicados preservando os melhores dados.
        unique: dict[str, dict[str, Any]] = {}
        for c in all_candidates:
            old = unique.get(c["url"])
            if old is None or c["area"] > old["area"]:
                unique[c["url"]] = c

        candidates_final = list(unique.values())

        # Se temos a imagem que o Brave encontrou, usamos similaridade de URL
        # para dar preferência ao mesmo arquivo no site de origem.
        brave_host = urlparse(brave_original_url or "").netloc.lower()
        brave_path = urlparse(brave_original_url or "").path.lower()

        def score(c: dict[str, Any]) -> tuple:
            u = c["url"]
            p = urlparse(u)
            same_name = int(bool(brave_path and Path(p.path).name.lower() == Path(brave_path).name.lower()))
            same_host = int(bool(brave_host and p.netloc.lower() == brave_host))
            kind_bonus = {"meta": 4, "jsonld": 3, "link": 2, "img": 1, "srcset": 1}.get(c["kind"], 0)
            return (same_name, kind_bonus, c["area"])

        candidates_final.sort(key=score, reverse=True)

        if candidates_final:
            best = candidates_final[0]
            data["original_found_on_source"] = True
            data["original_source_url"] = best["url"]
            data["source_image_width"] = best["width"] or None
            data["source_image_height"] = best["height"] or None
            data["source_image_kind"] = best["kind"]

    except Exception as exc:
        data["source_page_error"] = str(exc)
    finally:
        try:
            await page.close()
        except Exception:
            pass

    return data


async def extract_detail_data(
    context: BrowserContext,
    page: Page,
    result: dict[str, Any],
    policy: SourcePolicy | None = None,
) -> dict[str, Any]:
    """Abre o detalhe do Brave e descobre a página de origem."""
    policy = policy or SourcePolicy()
    result = dict(result)
    dom_index = result["dom_index"]
    cards = page.locator("button.image-result")

    if dom_index >= await cards.count():
        result["detail_error"] = "card não existe mais no DOM"
        return result

    card = cards.nth(dom_index)
    before_url = page.url

    try:
        await card.scroll_into_view_if_needed()
        await page.wait_for_timeout(250)
        await card.click(timeout=12_000)
        await page.wait_for_timeout(1000)

        # O detalhe pode conter links para a página de origem.
        links = await page.locator("a[href]").evaluate_all(
            """
            els => els.map(a => ({
                href: a.href || '',
                text: (a.innerText || '').trim(),
                rel: a.rel || ''
            })).filter(x => x.href)
            """
        )

        source_page = None
        for link in links:
            href = link["href"]
            host = urlparse(href).netloc.lower()
            if (
                href.startswith(("http://", "https://"))
                and "brave.com" not in host
                and "search.brave.com" not in host
                and "imgs.search.brave.com" not in host
                and not href.startswith("javascript:")
            ):
                # Preferir link que pareça ser página/article/source.
                text = (link.get("text") or "").lower()
                if source_page is None:
                    source_page = href
                if any(x in text for x in ["visitar", "source", "fonte", "site", "original", "abrir"]):
                    source_page = href
                    break

        result["detail_url"] = page.url
        result["detail_opened"] = True
        result["source_page"] = source_page

        # Tenta descobrir a imagem direta que o detalhe do Brave mostra.
        detail_imgs = await page.locator("img").evaluate_all(
            """
            els => els.map(img => ({
                src: img.currentSrc || img.src || '',
                alt: img.alt || '',
                width: img.naturalWidth || 0,
                height: img.naturalHeight || 0
            })).filter(x => x.src && !x.src.startsWith('data:'))
              .sort((a,b) => (b.width*b.height) - (a.width*a.height))
            """
        )

        for candidate in detail_imgs:
            src = candidate["src"]
            if src and "imgs.search.brave.com" not in src:
                result["detail_display_url"] = src
                break

        # Acessar a página de origem é OPCIONAL (policy):
        #   inspect_sources  -> abre a origem e cataloga as imagens dela
        #   visit_original   -> abre a origem só para achar a imagem original
        if source_page and policy.visit:
            skip, reason = should_skip_source_url(
                source_page,
                allow_google_source=policy.allow_google_source,
                allow_search_engine_sources=policy.allow_search_engine_sources,
            )
            if skip:
                result["source_blocked"] = True
                result["source_blocked_reason"] = reason
            else:
                source_data = await find_original_on_source_page(
                    context,
                    source_page,
                    brave_original_url=result.get("original_url"),
                )
                result.update(source_data)

                if policy.inspect_sources:
                    all_source = await collect_all_source_images(
                        context, source_page, max_images=policy.max_images_per_site,
                    )
                    result["source_images"] = all_source.get("source_images", [])
                    result["source_images_count"] = all_source.get("source_images_count", 0)
                    result["source_images_total_found"] = all_source.get("source_images_total_found", 0)
                    result["source_images_truncated"] = bool(all_source.get("source_images_truncated"))
                    if all_source.get("source_page_error") and not result.get("source_page_error"):
                        result["source_page_error"] = all_source.get("source_page_error")

    except Exception as exc:
        result["detail_error"] = str(exc)
        result["detail_opened"] = False

    # Volta para a busca para processar o próximo resultado.
    if page.url != before_url:
        try:
            await page.go_back(wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
            await page.wait_for_timeout(700)
        except Exception:
            try:
                await page.goto(before_url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
                await page.wait_for_timeout(800)
            except Exception:
                pass

    return result


async def download_image(
    context: BrowserContext,
    result: dict[str, Any],
    out_dir: Path,
    index: int,
    download_mode: str = "original",
) -> dict[str, Any]:
    """
    download_mode:
      brave    = baixa exatamente o proxy/reduzida entregue pelo Brave.
      original = usa a página de origem e a imagem encontrada nela.
    """
    if download_mode == "brave":
        url = result.get("proxy_url")
    elif download_mode == "original":
        url = result.get("original_source_url") or result.get("original_url")
    else:
        result["downloaded"] = False
        result["download_error"] = f"download_mode inválido: {download_mode}"
        return result

    if not url:
        result["downloaded"] = False
        result["download_error"] = f"URL ausente para download_mode={download_mode}"
        return result

    out_dir.mkdir(parents=True, exist_ok=True)
    title = safe_filename(result.get("title") or result.get("alt") or f"brave_{index:03d}", f"brave_{index:03d}")
    ext = Path(urlparse(url).path).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".svg"}:
        ext = ""
    target = out_dir / f"{index:03d}_{title}{ext}"

    try:
        response = await context.request.get(
            url,
            timeout=45_000,
            headers={
                "Referer": result.get("source_page") or "https://search.brave.com/",
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
        result["download_mode"] = download_mode
        result["download_url"] = url
        result["download_path"] = str(target.resolve())
        result["download_content_type"] = content_type
        result["download_bytes"] = len(body)
    except Exception as exc:
        result["downloaded"] = False
        result["download_mode"] = download_mode
        result["download_error"] = str(exc)

    return result


async def download_source_images_manifest(
    context: BrowserContext,
    detailed: list[dict[str, Any]],
    out_dir: Path,
    download_files: bool = True,
) -> dict[str, Any]:
    """Baixa todas as imagens encontradas nas páginas de origem e cria um JSON."""
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "imagens"
    images_dir.mkdir(parents=True, exist_ok=True)

    unique: dict[str, dict[str, Any]] = {}
    for result in detailed:
        for image in result.get("source_images", []) or []:
            url = image.get("original_url")
            if not url:
                continue
            if url not in unique:
                item = dict(image)
                item["query"] = result.get("query")
                item["brave_result_rank"] = result.get("rank")
                item["brave_source"] = result.get("source")
                unique[url] = item

    manifest = []
    for i, item in enumerate(unique.values(), 1):
        item = dict(item)
        item["global_index"] = i
        url = item["original_url"]
        name = safe_filename(item.get("name") or f"imagem_{i:04d}")
        ext = Path(urlparse(url).path).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".svg"}:
            ext = ""
        target = images_dir / f"{i:04d}_{name}{ext}"
        if not download_files:
            item["downloaded"] = False
            item["download_skipped"] = True
            manifest.append(item)
            continue
        try:
            response = await context.request.get(
                url,
                timeout=45_000,
                headers={
                    "Referer": item.get("source_page") or "https://search.brave.com/",
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                },
            )
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status}")
            body = await response.body()
            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            if not ext:
                ext = mimetypes.guess_extension(content_type) or ".bin"
                target = images_dir / f"{i:04d}_{name}{ext}"
            target.write_bytes(body)
            item["downloaded"] = True
            item["download_path"] = str(target.resolve())
            item["download_bytes"] = len(body)
            item["content_type"] = content_type
        except Exception as exc:
            item["downloaded"] = False
            item["download_error"] = str(exc)
        manifest.append(item)

    manifest_payload = {
        "ok": True,
        "total_images": len(manifest),
        "images": manifest,
    }
    manifest_path = out_dir / "imagens_originais.json"
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"manifest": manifest_payload, "manifest_path": str(manifest_path.resolve())}


async def scrape_current_page(
    context: BrowserContext,
    page: Page,
    *,
    q: str,
    limit: int,
    click_details: bool,
    orientation: str = "any",
    square_tolerance: float = 0.1,
    policy: SourcePolicy | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Coleta os cards da página de resultados ATUAL (e abre os detalhes)."""
    orientation = normalize_orientation(orientation)
    results, stats = await collect_result_cards(
        page,
        wanted=limit,
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
        raise RuntimeError(
            "Nenhum resultado de imagem foi encontrado no Brave. "
            "Se apareceu uma verificação, conclua-a no navegador "
            "e tente novamente."
        )
    stats["orientation_filter"] = orientation
    if len(results) < limit:
        stats["warning"] = (
            f"Só {len(results)} de {limit} imagens atenderam ao filtro "
            f"'{orientation}' (cards analisados: {stats['cards_scanned']})."
        )

    if click_details:
        detailed = []

        # Depois que um detalhe é aberto a grade pode mudar.
        # Reencontramos o card pelo data-rank a cada iteração.
        for result in results:
            try:
                current_rank = result.get("brave_rank")

                locator = page.locator(
                    f'button.image-result img[data-rank="{current_rank}"]'
                )

                if await locator.count() > 0:
                    card = locator.first.locator("xpath=ancestor::button[1]")
                    result = dict(result)
                    result["dom_index"] = await page.locator(
                        "button.image-result"
                    ).evaluate_all(
                        """
                        (els, rank) => els.findIndex(
                            b => {
                                const img = b.querySelector('img[data-rank]');
                                return img && img.getAttribute('data-rank') === String(rank);
                            }
                        )
                        """,
                        current_rank,
                    )
                    result = await extract_detail_data(context, page, result, policy)

            except Exception as exc:
                result["detail_error"] = str(exc)

            detailed.append(result)

    else:
        detailed = results


    for item in detailed:
        item["query"] = q
    return detailed, stats


async def search_images_browser(
    *,
    q: str,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    source: str = "images",
    headless: bool = False,
    click_details: bool = True,
    download: bool = False,
    download_mode: str = "original",
    output_dir: str = "brave_downloads",
    orientation: str = "any",
    square_tolerance: float = 0.1,
    inspect_sources: bool = False,
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
    max_images_per_site: int = DEFAULT_MAX_IMAGES_PER_SITE,
) -> dict[str, Any]:

    if not q.strip():
        raise ValueError("q não pode ficar vazio.")

    if limit < 1 or limit > 50:
        raise ValueError("limit deve ficar entre 1 e 50.")

    orientation = normalize_orientation(orientation)
    if not 0 <= square_tolerance <= 0.5:
        raise ValueError("square_tolerance deve ficar entre 0 e 0.5.")

    if inspect_sources:
        click_details = True  # precisa abrir o detalhe para descobrir a origem

    policy = make_source_policy(
        inspect_sources=inspect_sources,
        download=download,
        download_mode=download_mode,
        allow_google_source=allow_google_source,
        allow_search_engine_sources=allow_search_engine_sources,
        max_images_per_site=max_images_per_site,
    )

    search_url = build_search_url(
        q,
        source=source,
        offset=offset,
    )

    async with async_playwright() as pw:

        # Chromium real. Não tentamos burlar verificação do Brave.
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
            extra_http_headers={
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7"
            },
        )

        page = await context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        try:
            await page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT_MS,
            )

            # Tempo inicial para Svelte montar os cards.
            await page.wait_for_timeout(1500)

            detailed, scan_stats = await scrape_current_page(
                context,
                page,
                q=q,
                limit=limit,
                click_details=click_details,
                orientation=orientation,
                square_tolerance=square_tolerance,
                policy=policy,
            )

            source_manifest = None
            if policy.inspect_sources:
                # Catálogo com as imagens das páginas de origem.
                # O download físico só ocorre quando download=true.
                source_manifest = await download_source_images_manifest(
                    context,
                    detailed,
                    Path(output_dir),
                    download_files=download,
                )

            if download:
                out = Path(output_dir)
                for i, result in enumerate(detailed, start=1):
                    await download_image(
                        context, result, out, i, download_mode=download_mode,
                    )

            return {
                "ok": True,
                "engine": "brave_images",
                "query": q,
                "offset": offset,
                "limit_requested": limit,
                "results_found": len(detailed),
                "orientation_filter": orientation,
                "square_tolerance": square_tolerance,
                "inspect_sources": policy.inspect_sources,
                "scan_stats": scan_stats,
                "source": source,
                "search_url": search_url,
                "results": detailed,
                "source_images_manifest": source_manifest.get("manifest") if source_manifest else None,
                "source_images_manifest_path": source_manifest.get("manifest_path") if source_manifest else None,
            }

        finally:
            await context.close()
            await browser.close()


SEARCHBOX_SELECTOR = "input#searchbox"
SUBMIT_SELECTOR = "button#submit-button"

FIRST_CARD_SRC_JS = """
() => {
    const i = document.querySelector('button.image-result img[data-rank]');
    return i ? (i.currentSrc || i.src || '') : '';
}
"""


async def submit_new_search(
    page: Page,
    term: str,
    *,
    typing_delay_ms: int = 35,
    settle_ms: int = 1500,
) -> str:
    """
    Faz uma nova busca NA MESMA ABA, como uma pessoa faria:

      1. localiza o <input id="searchbox">;
      2. clica, apaga o texto antigo e digita o novo termo;
      3. clica no <button id="submit-button"> (lupa);
      4. aguarda a grade de resultados ser substituída.

    Retorna "searchbox" quando funcionou pelo input, ou "url_fallback" se o
    campo não pôde ser usado e foi preciso navegar direto pela URL.
    """
    try:
        # Fecha painel de detalhes/overlay que possa estar cobrindo o topo.
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(300)

        old_url = page.url
        old_first = await page.evaluate(FIRST_CARD_SRC_JS)

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

        # --- clicar na lupa ---
        submit = page.locator(SUBMIT_SELECTOR).first
        await submit.wait_for(state="visible", timeout=10_000)
        await submit.click(timeout=10_000)

        # --- aguardar ---
        # (a) a URL passa a refletir o novo termo (se o termo mudou)
        try:
            await page.wait_for_function(
                """(oldUrl) => location.href !== oldUrl""",
                arg=old_url,
                timeout=15_000,
            )
        except PlaywrightTimeoutError:
            pass  # termo igual ao anterior ou SPA que não mudou a URL

        if "/images" not in urlparse(page.url).path:
            raise RuntimeError(f"Busca saiu da aba de imagens: {page.url}")

        # (b) os cards antigos somem / o primeiro card muda
        try:
            await page.wait_for_function(
                """(oldFirst) => {
                    const i = document.querySelector('button.image-result img[data-rank]');
                    const cur = i ? (i.currentSrc || i.src || '') : '';
                    return cur && cur !== oldFirst;
                }""",
                arg=old_first,
                timeout=15_000,
            )
        except PlaywrightTimeoutError:
            pass  # pode ser que o 1º resultado seja igual; segue para o wait normal

        await wait_for_brave_results(page)
        await page.wait_for_timeout(settle_ms)  # deixa a grade estabilizar
        return "searchbox"

    except Exception:
        # Fallback: navega direto pela URL para não derrubar o lote inteiro.
        await page.goto(
            build_search_url(term),
            wait_until="domcontentloaded",
            timeout=DEFAULT_TIMEOUT_MS,
        )
        await page.wait_for_timeout(1500)
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
    limit: int = DEFAULT_LIMIT,
    source: str = "images",
    headless: bool = False,
    click_details: bool = True,
    download: bool = False,
    download_mode: str = "original",
    output_dir: str = "brave_downloads",
    pause_between_ms: int = 1500,
    orientation: str = "any",
    square_tolerance: float = 0.1,
    inspect_sources: bool = False,
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
    max_images_per_site: int = DEFAULT_MAX_IMAGES_PER_SITE,
) -> dict[str, Any]:
    """
    Várias buscas em sequência, TODAS na mesma aba/navegador.

    A 1ª busca abre a URL do Brave. As seguintes reutilizam a página:
    apagam o #searchbox, digitam o novo termo e clicam em #submit-button.
    """
    plan = normalize_batch_queries(queries, limit, orientation)
    if not 0 <= square_tolerance <= 0.5:
        raise ValueError("square_tolerance deve ficar entre 0 e 0.5.")
    if inspect_sources:
        click_details = True
    policy = make_source_policy(
        inspect_sources=inspect_sources,
        download=download,
        download_mode=download_mode,
        allow_google_source=allow_google_source,
        allow_search_engine_sources=allow_search_engine_sources,
        max_images_per_site=max_images_per_site,
    )
    out = Path(output_dir)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        context = await browser.new_context(
            locale="pt-BR",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7"},
        )
        page = await context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        searches: list[dict[str, Any]] = []
        all_detailed: list[dict[str, Any]] = []

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
                        entry["search_url"] = build_search_url(q, source=source)
                        await page.goto(
                            entry["search_url"],
                            wait_until="domcontentloaded",
                            timeout=DEFAULT_TIMEOUT_MS,
                        )
                        await page.wait_for_timeout(1500)
                        entry["search_method"] = "url"
                    else:
                        await page.wait_for_timeout(pause_between_ms)
                        entry["search_method"] = await submit_new_search(page, q)
                        entry["search_url"] = page.url

                    detailed, scan_stats = await scrape_current_page(
                        context, page, q=q, limit=lim, click_details=click_details,
                        orientation=ori, square_tolerance=square_tolerance, policy=policy,
                    )

                    if download:
                        qdir = out / f"{n:02d}_{safe_filename(q, f'busca_{n}')}"
                        for i, result in enumerate(detailed, start=1):
                            await download_image(
                                context, result, qdir, i, download_mode=download_mode,
                            )

                    entry.update(
                        ok=True,
                        results_found=len(detailed),
                        scan_stats=scan_stats,
                        results=detailed,
                    )
                    all_detailed.extend(detailed)

                except Exception as exc:
                    # Uma busca que falha não derruba as próximas.
                    entry["error"] = str(exc)
                    entry["results_found"] = 0
                    entry["results"] = []

                searches.append(entry)

            source_manifest = None
            if policy.inspect_sources and all_detailed:
                source_manifest = await download_source_images_manifest(
                    context, all_detailed, out, download_files=download,
                )

            return {
                "ok": any(s["ok"] for s in searches),
                "engine": "brave_images",
                "mode": "batch",
                "inspect_sources": policy.inspect_sources,
                "searches_requested": len(plan),
                "searches_ok": sum(1 for s in searches if s["ok"]),
                "total_results": sum(s["results_found"] for s in searches),
                "searches": searches,
                "source_images_manifest": source_manifest.get("manifest") if source_manifest else None,
                "source_images_manifest_path": source_manifest.get("manifest_path") if source_manifest else None,
            }

        finally:
            await context.close()
            await browser.close()


app = FastAPI(
    title="Brave Images Browser API",
    version="1.0.0",
    description="Pesquisa imagens no Brave Images usando Playwright + Chromium.",
)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "brave-image-browser-api",
    }


@app.get("/api/images/search")
async def api_search(
    q: str = Query(..., min_length=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(3, ge=1, le=50),
    source: str = Query("images"),
    orientation: str = Query(
        "any",
        description="any (qualquer) | horizontal | vertical | square (quadrada)",
    ),
    square_tolerance: float = Query(0.1, ge=0, le=0.5),
    click_details: bool = True,
    inspect_sources: bool = Query(
        False, description="Acessa os sites de origem e cataloga as imagens deles."
    ),
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
    max_images_per_site: int = Query(DEFAULT_MAX_IMAGES_PER_SITE, ge=1, le=500),
    download: bool = False,
    download_mode: str = "original",
    output_dir: str = "brave_downloads",
    headless: bool = False,
) -> JSONResponse:

    try:
        payload = await search_images_browser(
            q=q,
            offset=offset,
            limit=limit,
            source=source,
            headless=headless,
            click_details=click_details,
            download=download,
            download_mode=download_mode,
            output_dir=output_dir,
            orientation=orientation,
            square_tolerance=square_tolerance,
            inspect_sources=inspect_sources,
            allow_google_source=allow_google_source,
            allow_search_engine_sources=allow_search_engine_sources,
            max_images_per_site=max_images_per_site,
        )

        return JSONResponse(payload)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


class BatchRequest(BaseModel):
    # ["gojo", "geto"]  ou  [{"q": "gojo", "limit": 10, "orientation": "vertical"}, ...]
    queries: list[Any]
    limit: int = Field(3, ge=1, le=50)
    source: str = "images"
    orientation: str = "any"
    square_tolerance: float = Field(0.1, ge=0, le=0.5)
    click_details: bool = True
    inspect_sources: bool = False
    allow_google_source: bool = False
    allow_search_engine_sources: bool = False
    max_images_per_site: int = Field(DEFAULT_MAX_IMAGES_PER_SITE, ge=1, le=500)
    download: bool = False
    download_mode: str = "original"
    output_dir: str = "brave_downloads"
    headless: bool = False
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
    limit: int = Query(3, ge=1, le=50),
    source: str = Query("images"),
    orientation: str = Query(
        "any",
        description="any (qualquer) | horizontal | vertical | square (quadrada)",
    ),
    square_tolerance: float = Query(0.1, ge=0, le=0.5),
    click_details: bool = True,
    inspect_sources: bool = False,
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
    max_images_per_site: int = Query(DEFAULT_MAX_IMAGES_PER_SITE, ge=1, le=500),
    download: bool = False,
    download_mode: str = "original",
    output_dir: str = "brave_downloads",
    headless: bool = False,
    pause_between_ms: int = Query(1500, ge=0, le=60_000),
) -> JSONResponse:
    return await _run_batch(
        queries=q, limit=limit, source=source, headless=headless,
        click_details=click_details, download=download,
        download_mode=download_mode, output_dir=output_dir,
        pause_between_ms=pause_between_ms, orientation=orientation,
        square_tolerance=square_tolerance, inspect_sources=inspect_sources,
        allow_google_source=allow_google_source,
        allow_search_engine_sources=allow_search_engine_sources,
        max_images_per_site=max_images_per_site,
    )


@app.post("/api/images/batch")
async def api_batch_post(body: BatchRequest) -> JSONResponse:
    return await _run_batch(**body.model_dump())


async def run_test(
    headless: bool = False,
    orientation: str = "any",
    inspect_sources: bool = True,
) -> None:

    print("=" * 72)
    print("BRAVE IMAGES — TESTE")
    print("=" * 72)

    print("Busca: osama bin laden")
    print("Navegador: Chromium/Playwright")
    print("Filtro de proporção:", orientation)
    print()

    payload = await search_images_browser(
        q="osama bin laden",
        offset=0,
        limit=5,
        source="images",
        headless=headless,
        click_details=True,
        download=True,
        download_mode="original",
        output_dir="brave_test_downloads",
        orientation=orientation,
        inspect_sources=inspect_sources,
    )

    print("\nURL usada:")
    print(payload["search_url"])

    print("\nResultados:")

    for item in payload["results"]:

        print(
            f"\n#{item['rank']} "
            f"(Brave rank {item.get('brave_rank')}) "
            f"{item.get('title', '')}"
        )

        print(
            "  proporção:", item.get("orientation"),
            f"({item.get('thumb_width')}x{item.get('thumb_height')},",
            f"razão {item.get('aspect_ratio')})",
        )
        print("  alt:", item.get("alt"))
        print("  site:", item.get("source"))
        print("  proxy:", item.get("proxy_url"))
        print("  original:", item.get("original_url"))
        print("  fonte:", item.get("source_page"))
        print("  detalhe:", item.get("detail_url"))
        print("  detalhe aberto:", item.get("detail_opened"))

        if item.get("downloaded"):
            print("  baixada:", item.get("download_path"))
            print("  bytes:", item.get("download_bytes"))
        elif item.get("download_error"):
            print("  erro download:", item.get("download_error"))

        print("  imagens encontradas no site:", item.get("source_images_count", 0))
        if item.get("detail_error"):
            print("  erro detalhe:", item.get("detail_error"))

    out = Path("brave_test_results.json")

    out.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\nJSON salvo em:")
    print(out.resolve())


def main() -> None:

    parser = argparse.ArgumentParser(
        description="Brave Images Browser API"
    )

    parser.add_argument(
        "--test",
        action="store_true",
        help="Executa o teste com 'osama bin laden'.",
    )

    parser.add_argument(
        "--batch",
        nargs="+",
        metavar="TERMO",
        help='Várias buscas na mesma aba. Ex.: --batch "gojo" "geto" --limit 5',
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Imagens por busca (usado com --batch).",
    )

    parser.add_argument(
        "--download",
        action="store_true",
        help="Baixa as imagens (usado com --batch).",
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
        "--inspect-sources",
        action="store_true",
        help="Acessa os sites de origem e cataloga as imagens deles (opcional).",
    )

    parser.add_argument("--allow-google-source", action="store_true",
                        help="Permite Google como site de origem.")
    parser.add_argument("--allow-search-engine-sources", action="store_true",
                        help="Permite buscadores como site de origem.")
    parser.add_argument("--max-images-per-site", type=int,
                        default=DEFAULT_MAX_IMAGES_PER_SITE,
                        help="Máximo de imagens catalogadas por site de origem (1-500).")

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Executa sem abrir janela.",
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8001,
    )

    args = parser.parse_args()

    if args.batch:
        payload = asyncio.run(
            search_images_batch(
                queries=args.batch,
                limit=args.limit,
                headless=args.headless,
                download=args.download,
                output_dir="brave_batch_downloads",
                orientation=args.orientation,
                square_tolerance=args.square_tolerance,
                inspect_sources=args.inspect_sources,
                allow_google_source=args.allow_google_source,
                allow_search_engine_sources=args.allow_search_engine_sources,
                max_images_per_site=args.max_images_per_site,
            )
        )
        for sr in payload["searches"]:
            status = "OK" if sr["ok"] else f"ERRO: {sr.get('error')}"
            print(f"[{sr['index']}] {sr['query']!r} [{sr.get('orientation_filter')}]: "
                  f"{sr['results_found']} imagens ({sr.get('search_method', '-')}) {status}")
            warn = (sr.get("scan_stats") or {}).get("warning")
            if warn:
                print("     aviso:", warn)
        out = Path("brave_batch_results.json")
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\nJSON salvo em:", out.resolve())
        return

    if args.test:
        asyncio.run(
            run_test(
                headless=args.headless,
                orientation=args.orientation,
                inspect_sources=True,
            )
        )
        return

    print(
        f"Brave Images Browser API: "
        f"http://{args.host}:{args.port}"
    )

    print(
        "Endpoint: "
        "/api/images/search?q=gojo%20eye&limit=5"
    )

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
