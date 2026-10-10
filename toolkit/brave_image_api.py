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
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, unquote, urljoin, urlparse

from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


BRAVE_IMAGES = "https://search.brave.com/images"
DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_LIMIT = 3


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


async def collect_result_cards(
    page: Page,
    wanted: int,
) -> list[dict[str, Any]]:
    """
    Extrai os cards conforme o HTML fornecido:

      <button class="image-result ...">
        <img ... alt="..." data-rank="0">
        ...
        <span class="image-metadata-source">criticalhits.com.br</span>
        <span class="image-metadata-title">...</span>
      </button>
    """
    await wait_for_brave_results(page)

    # As imagens são lazy-load. Rola um pouco para disparar o carregamento.
    for _ in range(3):
        await page.mouse.wheel(0, 1000)
        await page.wait_for_timeout(500)

    cards = page.locator("button.image-result")
    count = await cards.count()

    results: list[dict[str, Any]] = []

    for dom_index in range(count):
        if len(results) >= wanted:
            break

        card = cards.nth(dom_index)

        try:
            img = card.locator("img[data-rank]").first

            if await img.count() == 0:
                # Fallback para qualquer img dentro do card.
                img = card.locator("img").first

            if await img.count() == 0:
                continue

            src = await img.get_attribute("src")
            alt = await img.get_attribute("alt") or ""
            rank_raw = await img.get_attribute("data-rank")

            # Não incluir o bloco "Pesquisar em outro lugar".
            if await card.locator(".image-search-elsewhere").count():
                continue

            source_el = card.locator(".image-metadata-source").first
            title_el = card.locator(".image-metadata-title").first

            source = (
                (await source_el.inner_text()).strip()
                if await source_el.count()
                else ""
            )

            title = (
                (await title_el.inner_text()).strip()
                if await title_el.count()
                else ""
            )

            try:
                brave_rank = int(rank_raw) if rank_raw is not None else len(results)
            except ValueError:
                brave_rank = len(results)

            original = decode_brave_proxy_url(src)

            results.append(
                {
                    "rank": len(results) + 1,
                    "brave_rank": brave_rank,
                    "dom_index": dom_index,
                    "title": title,
                    "alt": alt,
                    "source": source,
                    "proxy_url": src or "",
                    "original_url": original,
                    "source_page": None,
                    "detail_url": None,
                    "detail_opened": False,
                    "query": None,
                }
            )

        except Exception:
            continue

    return results


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
) -> dict[str, Any]:
    """Abre o detalhe do Brave e descobre a página de origem."""
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

        # Se o detalhe trouxe a fonte, acessamos a página real e procuramos
        # novamente a imagem em tamanho original.
        if source_page:
            source_data = await find_original_on_source_page(
                context,
                source_page,
                brave_original_url=result.get("original_url"),
            )
            result.update(source_data)
            # Além da imagem encontrada pelo Brave, guarda TODAS as imagens da página.
            all_source = await collect_all_source_images(context, source_page)
            result["source_images"] = all_source.get("source_images", [])
            result["source_images_count"] = all_source.get("source_images_count", 0)
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


async def search_images_browser_in_session(
    page: Page,
    context: BrowserContext,
    *,
    q: str,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    source: str = "images",
    click_details: bool = True,
    download: bool = False,
    download_mode: str = "original",
    output_dir: str = "brave_downloads",
) -> dict[str, Any]:
    if not q.strip():
        raise ValueError("q não pode ficar vazio.")
    if limit < 1 or limit > 50:
        raise ValueError("limit deve ficar entre 1 e 50.")
    search_url = build_search_url(q, source=source, offset=offset)
    await page.goto(search_url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
    await page.wait_for_timeout(1500)
    results = await collect_result_cards(page, wanted=limit)
    if not results:
        raise RuntimeError(
            "Nenhum resultado de imagem foi encontrado no Brave. "
            "Se apareceu uma verificação, conclua-a no navegador e tente novamente."
        )
    if click_details:
        detailed = []
        for result in results:
            try:
                current_rank = result.get("brave_rank")
                locator = page.locator(f'button.image-result img[data-rank="{current_rank}"]')
                if await locator.count() > 0:
                    result = dict(result)
                    result["dom_index"] = await page.locator("button.image-result").evaluate_all(
                        """(els, rank) => els.findIndex(b => { const img = b.querySelector('img[data-rank]'); return img && img.getAttribute('data-rank') === String(rank); })""", current_rank,
                    )
                    result = await extract_detail_data(context, page, result)
            except Exception as exc:
                result["detail_error"] = str(exc)
            detailed.append(result)
    else:
        detailed = results
    for item in detailed:
        item["query"] = q
    source_manifest = None
    if click_details:
        out = Path(output_dir)
        source_manifest = await download_source_images_manifest(context, detailed, out, download_files=download)
    if download:
        out = Path(output_dir)
        for i, result in enumerate(detailed, start=1):
            await download_image(context, result, out, i, download_mode=download_mode)
    return {
        "ok": True, "engine": "brave_images", "query": q, "offset": offset,
        "limit_requested": limit, "results_found": len(detailed), "source": source,
        "search_url": search_url, "results": detailed,
        "source_images_manifest": source_manifest.get("manifest") if source_manifest else None,
        "source_images_manifest_path": source_manifest.get("manifest_path") if source_manifest else None,
    }


async def search_images_browser(
    *,
    q: str, offset: int = 0, limit: int = DEFAULT_LIMIT, source: str = "images",
    headless: bool = False, click_details: bool = True, download: bool = False,
    download_mode: str = "original", output_dir: str = "brave_downloads",
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
                page, context, q=q, offset=offset, limit=limit, source=source,
                click_details=click_details, download=download, download_mode=download_mode, output_dir=output_dir,
            )
        finally:
            await context.close()
            await browser.close()
