# -*- coding: utf-8 -*-
"""
Bing Images browser API/tester  (+ busca em lote na mesma aba + filtro de proporção)

O que faz:
- Abre o Bing Images num Chromium real (Playwright).
- Monta os filtros qft do Bing a partir de parâmetros amigáveis.
- Lê os cards `.iusc` e o JSON do atributo `m` (murl, purl, turl...).
- Para os N primeiros resultados abre/clica o detalhe e extrai a URL original.
- Opcionalmente baixa as imagens originais.

NOVO (trazido do Brave):
- VÁRIAS BUSCAS NA MESMA ABA: a 1ª busca abre a URL; as seguintes localizam
  `#sb_form_q`, apagam o termo antigo, digitam o novo e enviam com ENTER ou
  clicando em `#sb_form_go` (ícone da lupa).
- FILTRO DE PROPORÇÃO (`orientation`): any | horizontal | vertical | square,
  medido na própria imagem (não só pelo filtro do Bing). O `limit` conta só
  as imagens que passam no filtro; se faltar, o script rola a página.

Instalação:
    py -m pip install -r requirements.txt
    py -m playwright install chromium

Teste:
    py bing_image_api.py --test

API:
    py bing_image_api.py

Exemplos:
    http://127.0.0.1:8000/api/images/search?q=gojo%20eyes&limit=3
    http://127.0.0.1:8000/api/images/search?q=gojo%20eyes&limit=5&orientation=vertical
    http://127.0.0.1:8000/api/images/batch?q=gojo&q=geto&q=sukuna&limit=5&orientation=horizontal

Linha de comando (lote):
    py bing_image_api.py --batch "gojo" "geto" "sukuna" --limit 5 --orientation vertical
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import mimetypes
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse

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


BING_IMAGES = "https://www.bing.com/images/search"
DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_LIMIT = 3
MAX_LIMIT = 50

# Campo de pesquisa e ícone da lupa do Bing (HTML do formulário #sb_form)
SEARCHBOX_SELECTOR = "#sb_form_q"
SUBMIT_SELECTOR = "#sb_form_go"
SUBMIT_METHODS = ("auto", "enter", "click")


# ----------------------------------------------------------------------------
# Filtro por proporção (orientação) — igual ao do Brave
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


_DIMS_RE = re.compile(r"(\d{2,5})\s*[x×X]\s*(\d{2,5})")


def parse_dims_text(text: str | None) -> tuple[int, int] | None:
    """Lê textos como '1920 x 1080 · jpeg' (info que o Bing mostra no card)."""
    m = _DIMS_RE.search(text or "")
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    return (w, h) if w and h else None


# ----------------------------------------------------------------------------
# URL / filtros do Bing
# ----------------------------------------------------------------------------
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


# ----------------------------------------------------------------------------
# Medição da proporção de cada card
# ----------------------------------------------------------------------------
_CARD_INFO_JS = """
el => {
    const box = el.closest('.imgpt') || el.parentElement;
    const t = box ? box.querySelector('.img_info .nowrap, .nowrap') : null;
    return t ? (t.textContent || '') : '';
}
"""

_THUMB_PROBE_JS = """
el => {
    const r = el.getBoundingClientRect();
    return {
        nw: el.naturalWidth || 0,
        nh: el.naturalHeight || 0,
        ok: el.naturalWidth > 1 && el.naturalHeight > 1,
        rw: r.width || 0,
        rh: r.height || 0,
    };
}
"""

_THUMB_WAIT_JS = """
el => new Promise(res => {
    const ok = () => el.naturalWidth > 1 && el.naturalHeight > 1;
    if (ok()) return res(true);
    const t = setInterval(() => { if (ok()) { clearInterval(t); res(true); } }, 100);
    setTimeout(() => { clearInterval(t); res(false); }, 2500);
})
"""


async def read_card_size(card, meta: dict[str, Any], *, wait_thumb: bool = False) -> dict[str, Any]:
    """
    Descobre largura/altura (para a proporção), na ordem:
      1. `expw`/`exph` do atributo `m`                  -> source "bing_meta"
      2. texto "1920 x 1080 · jpeg" do card             -> source "bing_info"
      3. naturalWidth/Height da thumbnail já carregada  -> source "natural"
      4. tamanho exibido na grade                       -> source "displayed"
    (As thumbnails do Bing são data:URI; por isso o teste de "carregada" usa
     naturalWidth > 1, e não o prefixo data:.)
    """
    try:
        w = int(meta.get("expw") or 0)
        h = int(meta.get("exph") or 0)
    except (TypeError, ValueError):
        w = h = 0
    if w and h:
        return {"width": w, "height": h, "source": "bing_meta"}

    try:
        dims = parse_dims_text(await card.evaluate(_CARD_INFO_JS))
        if dims:
            return {"width": dims[0], "height": dims[1], "source": "bing_info"}
    except Exception:
        pass

    try:
        img = card.locator("img").first
        if await img.count() == 0:
            return {"width": None, "height": None, "source": None}
        data = await img.evaluate(_THUMB_PROBE_JS)
        if wait_thumb and not data["ok"]:
            try:
                await img.scroll_into_view_if_needed(timeout=3_000)
            except Exception:
                pass
            await img.evaluate(_THUMB_WAIT_JS)
            data = await img.evaluate(_THUMB_PROBE_JS)
    except Exception:
        return {"width": None, "height": None, "source": None}

    if data["ok"]:
        return {"width": data["nw"], "height": data["nh"], "source": "natural"}
    if data["rw"] and data["rh"]:
        return {"width": round(data["rw"]), "height": round(data["rh"]), "source": "displayed"}
    return {"width": None, "height": None, "source": None}


# Aviso de cookies do Bing ("A Microsoft e nossos fornecedores terceirizados
# usam cookies..." com Aceitar / Rejeitar / Mais opções). Pode aparecer a
# qualquer momento e fica por cima da grade: os cliques nos cards caem nele.
# em ordem: o link "Aceitar" primeiro (um seletor com vírgula pegaria a div de
# fora, que vem antes no documento, e o clique no meio dela pode errar o link)
SEL_COOKIES_ACEITAR = ("#bnp_btn_accept a", "#bnp_btn_accept", "#bnp_container .bnp_btn_accept")
SEL_COOKIES_AVISO = "#bnp_container"


async def aceitar_cookies(page: Page) -> bool:
    """Clica em 'Aceitar' no aviso de cookies do Bing, se ele estiver na tela."""
    for sel in SEL_COOKIES_ACEITAR:
        try:
            botao = page.locator(sel).first
            if not (await botao.count() and await botao.is_visible()):
                continue
            await botao.click(timeout=3_000)
            await page.wait_for_timeout(300)
            if not await page.locator(SEL_COOKIES_AVISO).first.is_visible():
                return True
        except Exception:
            continue
    try:  # último recurso: clique via JS (o <a> é javascript:void(0))
        return bool(await page.evaluate(
            "() => { const a = document.querySelector('#bnp_btn_accept a') || document.querySelector('#bnp_btn_accept');"
            " if (!a) return false; a.click(); return true; }"))
    except Exception:
        return False


async def vigiar_cookies(page: Page) -> None:
    """Registra o clique automático: toda vez que o aviso aparecer antes de uma
    ação (clique, digitação...), o Playwright clica em 'Aceitar' primeiro."""
    async def _aceitar(_loc=None):
        await aceitar_cookies(page)
    try:
        await page.add_locator_handler(page.locator(SEL_COOKIES_AVISO), _aceitar, no_wait_after=True)
    except TypeError:
        await page.add_locator_handler(page.locator(SEL_COOKIES_AVISO), _aceitar)
    except Exception:
        pass  # Playwright antigo: fica só o aceitar_cookies explícito


async def load_more_cards(page: Page) -> None:
    """Rola a página e clica em 'Ver mais' (se existir) para o Bing carregar mais cards."""
    await aceitar_cookies(page)
    await page.mouse.wheel(0, 1800)
    await page.wait_for_timeout(700)
    try:
        btn = page.locator("a.btn_seemore, .btn_seemore").first
        if await btn.count() and await btn.is_visible():
            await btn.click(timeout=3_000)
            await page.wait_for_timeout(900)
    except Exception:
        pass


async def collect_result_cards(
    page: Page,
    wanted: int,
    *,
    orientation: str = "any",
    square_tolerance: float = 0.1,
    max_scroll_rounds: int = 25,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Lê os cards `<a class="iusc" m="...">` e aplica o filtro de proporção.

    `wanted` = quantas imagens QUE PASSAM NO FILTRO queremos. Se os primeiros
    cards não bastam, rola a página para o Bing carregar mais e continua.
    Retorna (resultados, estatísticas).
    """
    orientation = normalize_orientation(orientation)
    await aceitar_cookies(page)
    await page.wait_for_selector("a.iusc", timeout=DEFAULT_TIMEOUT_MS)
    await page.wait_for_timeout(1200)  # lazy-load inicial
    await aceitar_cookies(page)

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
        cards = page.locator("a.iusc")
        count = await cards.count()
        new_cards = 0

        for dom_index in range(count):
            if len(results) >= wanted:
                break

            card = cards.nth(dom_index)
            try:
                m_raw = await card.get_attribute("m")
                meta = decode_m_attribute(m_raw)
                href = await card.get_attribute("href")

                murl = meta.get("murl") or extract_mediaurl_from_href(href)
                if not murl:
                    continue

                key = str(meta.get("mid") or murl)
                if key in seen:
                    continue
                seen.add(key)
                new_cards += 1
                stats["cards_scanned"] += 1

                # ---- proporção ----
                size = await read_card_size(
                    card, meta, wait_thumb=(orientation != "any")
                )
                kind, ratio = classify_orientation(
                    size["width"], size["height"], square_tolerance
                )
                if orientation != "any":
                    if kind is None:
                        stats["unknown_orientation"] += 1
                        stats["filtered_out"] += 1
                        continue  # não dá para confirmar -> não entra
                    if kind != orientation:
                        stats["filtered_out"] += 1
                        continue

                from_bing = size["source"] in ("bing_meta", "bing_info")
                width = size["width"] if from_bing else None
                height = size["height"] if from_bing else None

                results.append(
                    {
                        "rank": len(results) + 1,
                        "dom_index": dom_index,
                        "title": meta.get("t") or meta.get("desc") or "",
                        "description": meta.get("desc", ""),
                        "source_page": meta.get("purl") or "",
                        "original_url": murl,
                        "thumbnail_url": meta.get("turl") or "",
                        "media_id": meta.get("mid"),
                        "cid": meta.get("cid"),
                        "md5": meta.get("md5"),
                        "width": width,
                        "height": height,
                        "thumb_width": None if from_bing else size["width"],
                        "thumb_height": None if from_bing else size["height"],
                        "aspect_ratio": ratio,
                        "orientation": kind,
                        "orientation_source": size["source"],
                        "bing_result_url": urljoin("https://www.bing.com", href or ""),
                        "m_raw": m_raw,
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

        await load_more_cards(page)
        stats["scroll_rounds"] += 1

    return results, stats


# ----------------------------------------------------------------------------
# Detalhe do resultado
# ----------------------------------------------------------------------------
async def find_card_index(page: Page, murl: str) -> int:
    """Acha o card pelo murl (o dom_index muda quando a grade é recarregada)."""
    return await page.locator("a.iusc").evaluate_all(
        """(els, murl) => els.findIndex(a => {
            try { return JSON.parse(a.getAttribute('m') || '{}').murl === murl; }
            catch (e) { return false; }
        })""",
        murl,
    )


async def restore_grid_for(page: Page, grid_url: str, murl: str, max_rounds: int = 15) -> int:
    """Se a grade foi recarregada e o card sumiu, reabre a busca e rola até achá-lo."""
    await page.goto(grid_url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
    await page.wait_for_selector("a.iusc", timeout=DEFAULT_TIMEOUT_MS)
    await page.wait_for_timeout(900)
    for _ in range(max_rounds):
        idx = await find_card_index(page, murl)
        if idx >= 0:
            return idx
        await load_more_cards(page)
    return -1


async def open_detail_for_result(
    context: BrowserContext,
    search_page: Page,
    result: dict[str, Any],
) -> dict[str, Any]:
    """
    Abre o detalhe do resultado. Tenta um click real primeiro; se não abrir,
    usa o href do resultado como fallback determinístico.
    """
    result = dict(result)
    before = search_page.url

    try:
        await aceitar_cookies(search_page)
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

    # Bing coloca as dimensões completas na URL do detalhe como expw/exph.
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

    # Tenta achar a imagem grande/principal na página de detalhe.
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

    # Volta para a grade para o próximo item poder ser clicado.
    if search_page.url != before:
        try:
            await search_page.go_back(
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT_MS,
            )
            await search_page.wait_for_timeout(600)
        except Exception:
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


# ----------------------------------------------------------------------------
# Coleta da página de resultados ATUAL
# ----------------------------------------------------------------------------
async def scrape_current_page(
    context: BrowserContext,
    page: Page,
    *,
    q: str,
    limit: int,
    click_details: bool = True,
    orientation: str = "any",
    square_tolerance: float = 0.1,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Coleta os cards da página de resultados atual (e abre os detalhes)."""
    orientation = normalize_orientation(orientation)
    grid_url = page.url

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
            "Nenhum resultado .iusc com murl foi encontrado. "
            "O Bing pode ter alterado o HTML ou exibido um bloqueio/desafio."
        )

    stats["orientation_filter"] = orientation
    if len(results) < limit:
        stats["warning"] = (
            f"Só {len(results)} de {limit} imagens atenderam ao filtro "
            f"'{orientation}' (cards analisados: {stats['cards_scanned']})."
        )

    if click_details:
        detailed: list[dict[str, Any]] = []
        for result in results:
            try:
                # Depois de abrir um detalhe a grade pode mudar: reencontra o card pelo murl.
                idx = await find_card_index(page, result["original_url"])
                if idx < 0:
                    idx = await restore_grid_for(page, grid_url, result["original_url"])
                if idx >= 0:
                    result = dict(result)
                    result["dom_index"] = idx
                    result = await open_detail_for_result(context, page, result)
                else:
                    result = dict(result)
                    result["detail_opened"] = False
                    result["detail_error"] = "card não encontrado na grade após recarregar"

                # Garante que a grade continua na tela para o próximo item / próxima busca.
                if await page.locator("a.iusc").count() == 0:
                    await page.goto(grid_url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
                    await page.wait_for_timeout(900)
            except Exception as exc:
                result = dict(result)
                result["detail_error"] = str(exc)
                result["detail_opened"] = False
            detailed.append(result)
    else:
        detailed = results

    for item in detailed:
        item["query"] = q
    return detailed, stats


async def _new_browser_page(pw, headless: bool):
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
        extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7"},
    )
    page = await context.new_page()
    page.set_default_timeout(DEFAULT_TIMEOUT_MS)
    await vigiar_cookies(page)
    return browser, context, page


def _validate_common(limit: int, square_tolerance: float) -> None:
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit deve ficar entre 1 e {MAX_LIMIT}.")
    if not 0 <= square_tolerance <= 0.5:
        raise ValueError("square_tolerance deve ficar entre 0 e 0.5.")


# ----------------------------------------------------------------------------
# Busca única (comportamento original + proporção)
# ----------------------------------------------------------------------------
async def search_images_browser(
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
    orientation: str = "any",
    square_tolerance: float = 0.1,
    click_details: bool = True,
    headless: bool = False,
    download: bool = False,
    output_dir: str = "bing_downloads",
) -> dict[str, Any]:
    if not q.strip():
        raise ValueError("q não pode ficar vazio.")
    _validate_common(limit, square_tolerance)
    orientation = normalize_orientation(orientation)

    qft = build_qft(
        aspect=aspect,
        animated=animated,
        transparent=transparent,
        size=size,
        extra_qft=extra_qft,
    )
    search_url = build_search_url(q, first=first, mkt=mkt, qft=qft)

    async with async_playwright() as pw:
        browser, context, page = await _new_browser_page(pw, headless)
        try:
            await page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT_MS,
            )

            detailed, scan_stats = await scrape_current_page(
                context,
                page,
                q=q,
                limit=limit,
                click_details=click_details,
                orientation=orientation,
                square_tolerance=square_tolerance,
            )

            if download:
                out = Path(output_dir)
                for i, result in enumerate(detailed, start=1):
                    await download_original(context, result, out, i)

            return {
                "ok": True,
                "engine": "bing_images",
                "query": q,
                "first": first,
                "limit_requested": limit,
                "results_found": len(detailed),
                "filters": {
                    "aspect": aspect,
                    "animated": animated,
                    "transparent": transparent,
                    "size": size,
                    "extra_qft": extra_qft,
                    "qft_final": qft,
                    "orientation": orientation,
                    "square_tolerance": square_tolerance,
                },
                "scan_stats": scan_stats,
                "search_url": search_url,
                "results": detailed,
            }
        finally:
            await context.close()
            await browser.close()


# ----------------------------------------------------------------------------
# Nova busca NA MESMA ABA (apaga, digita, ENTER ou clica na lupa)
# ----------------------------------------------------------------------------
_FIRST_CARD_KEY_JS = """
() => {
    const a = document.querySelector('a.iusc');
    return a ? (a.getAttribute('href') || a.getAttribute('m') || '') : '';
}
"""


async def _url_changed(page: Page, old_url: str, timeout_ms: int) -> bool:
    try:
        await page.wait_for_url(
            lambda u: u != old_url,
            timeout=timeout_ms,
            wait_until="domcontentloaded",
        )
        return True
    except PlaywrightTimeoutError:
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

      1. localiza o campo  #sb_form_q;
      2. clica, apaga o texto antigo e digita o novo termo;
      3. envia:  submit_method="enter"  -> tecla ENTER
                 submit_method="click"  -> clica no ícone #sb_form_go
                 submit_method="auto"   -> ENTER; se a página não mudar, clica no ícone;
      4. aguarda a nova página de resultados.

    Retorna "searchbox:enter" / "searchbox:click" quando funcionou pelo campo,
    ou "url_fallback" se foi preciso navegar direto pela URL.
    """
    if submit_method not in SUBMIT_METHODS:
        raise ValueError("submit_method deve ser: auto, enter ou click.")

    try:
        await aceitar_cookies(page)
        # Fecha overlay/painel de detalhe que possa estar cobrindo o topo.
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(300)

        old_url = page.url
        old_first = await page.evaluate(_FIRST_CARD_KEY_JS)

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

        # --- enviar: ENTER e/ou clique no ícone ---
        used = "enter"
        changed = False
        if submit_method in ("auto", "enter"):
            await box.press("Enter")
            changed = await _url_changed(
                page, old_url, 6_000 if submit_method == "auto" else 15_000
            )
        if not changed and submit_method in ("auto", "click"):
            submit = page.locator(SUBMIT_SELECTOR).first
            await submit.wait_for(state="visible", timeout=10_000)
            await submit.click(timeout=10_000)
            used = "click"
            changed = await _url_changed(page, old_url, 15_000)

        if not changed:
            # Pode ser uma atualização sem trocar a URL: confere se o 1º card mudou.
            try:
                await page.wait_for_function(
                    """(oldFirst) => {
                        const a = document.querySelector('a.iusc');
                        const cur = a ? (a.getAttribute('href') || a.getAttribute('m') || '') : '';
                        return cur && cur !== oldFirst;
                    }""",
                    arg=old_first,
                    timeout=8_000,
                )
            except PlaywrightTimeoutError:
                raise RuntimeError("A busca digitada não mudou a página.")

        if "/images" not in urlparse(page.url).path:
            raise RuntimeError(f"Busca saiu da aba de imagens: {page.url}")

        await page.wait_for_selector("a.iusc", timeout=DEFAULT_TIMEOUT_MS)
        await page.wait_for_timeout(settle_ms)  # deixa a grade estabilizar
        return f"searchbox:{used}"

    except Exception:
        # Fallback: navega direto pela URL para não derrubar o lote inteiro.
        await page.goto(
            fallback_url or build_search_url(term),
            wait_until="domcontentloaded",
            timeout=DEFAULT_TIMEOUT_MS,
        )
        await page.wait_for_timeout(1500)
        return "url_fallback"


async def ensure_qft_in_url(page: Page, qft: str | None) -> bool:
    """
    O formulário #sb_form do Bing só envia q/qs/form: os filtros (qft) se perdem
    ao digitar uma nova busca. Se os filtros do Bing foram pedidos e não estão
    na URL, recarrega a MESMA busca com o qft. Retorna True se recarregou.
    """
    if not qft:
        return False
    cur = urlparse(page.url)
    qs = {k: v[0] for k, v in parse_qs(cur.query).items()}
    if (qs.get("qft") or "").strip() == qft.strip():
        return False
    qs["qft"] = qft
    await page.goto(
        cur._replace(query=urlencode(qs)).geturl(),
        wait_until="domcontentloaded",
        timeout=DEFAULT_TIMEOUT_MS,
    )
    await page.wait_for_timeout(900)
    return True


# ----------------------------------------------------------------------------
# Várias buscas em sequência (mesma aba)
# ----------------------------------------------------------------------------
def normalize_batch_queries(
    queries: list[Any],
    default_limit: int,
    default_orientation: str = "any",
    default_aspect: str | None = None,
) -> list[dict[str, Any]]:
    """
    Aceita ["termo", ...] ou
           [{"q": "termo", "limit": 10, "orientation": "vertical", "aspect": "tall"}, ...]
    """
    default_orientation = normalize_orientation(default_orientation)
    out: list[dict[str, Any]] = []
    for item in queries:
        if isinstance(item, str):
            q, lim, ori, asp = item.strip(), default_limit, default_orientation, default_aspect
        elif isinstance(item, dict):
            q = str(item.get("q", "")).strip()
            lim = int(item.get("limit") or default_limit)
            ori = normalize_orientation(item.get("orientation") or default_orientation)
            asp = item.get("aspect") or default_aspect
        else:
            continue
        if not q:
            continue
        if lim < 1 or lim > MAX_LIMIT:
            raise ValueError(f"limit de '{q}' deve ficar entre 1 e {MAX_LIMIT}.")
        if asp:
            build_qft(aspect=asp)  # valida (levanta ValueError se inválido)
        out.append({"q": q, "limit": lim, "orientation": ori, "aspect": asp})
    if not out:
        raise ValueError("Informe ao menos um termo de busca.")
    return out


async def search_images_batch(
    *,
    queries: list[Any],
    limit: int = DEFAULT_LIMIT,
    aspect: str | None = None,
    animated: bool = False,
    transparent: bool = False,
    size: str | None = None,
    extra_qft: str | None = None,
    mkt: str = "pt-BR",
    orientation: str = "any",
    square_tolerance: float = 0.1,
    click_details: bool = True,
    submit_method: str = "auto",
    headless: bool = False,
    download: bool = False,
    output_dir: str = "bing_downloads",
    pause_between_ms: int = 1500,
) -> dict[str, Any]:
    """
    Várias buscas em sequência, TODAS na mesma aba/navegador.

    A 1ª busca abre a URL do Bing. As seguintes reutilizam a página:
    apagam o #sb_form_q, digitam o novo termo e enviam com ENTER ou clicando
    na lupa #sb_form_go (veja `submit_method`).
    """
    _validate_common(limit, square_tolerance)
    if submit_method not in SUBMIT_METHODS:
        raise ValueError("submit_method deve ser: auto, enter ou click.")
    plan = normalize_batch_queries(queries, limit, orientation, aspect)
    out = Path(output_dir)

    async with async_playwright() as pw:
        browser, context, page = await _new_browser_page(pw, headless)

        searches: list[dict[str, Any]] = []
        try:
            for n, item in enumerate(plan, start=1):
                q, lim, ori, asp = item["q"], item["limit"], item["orientation"], item["aspect"]
                qft = build_qft(
                    aspect=asp,
                    animated=animated,
                    transparent=transparent,
                    size=size,
                    extra_qft=extra_qft,
                )
                entry: dict[str, Any] = {
                    "index": n,
                    "query": q,
                    "limit_requested": lim,
                    "orientation_filter": ori,
                    "qft_final": qft,
                    "ok": False,
                }
                try:
                    url = build_search_url(q, mkt=mkt, qft=qft)
                    if n == 1:
                        entry["search_url"] = url
                        await page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
                        await page.wait_for_timeout(1500)
                        entry["search_method"] = "url"
                    else:
                        await page.wait_for_timeout(pause_between_ms)
                        entry["search_method"] = await submit_new_search(
                            page, q, submit_method=submit_method, fallback_url=url,
                        )
                        entry["qft_reapplied"] = await ensure_qft_in_url(page, qft)
                        entry["search_url"] = page.url

                    detailed, scan_stats = await scrape_current_page(
                        context,
                        page,
                        q=q,
                        limit=lim,
                        click_details=click_details,
                        orientation=ori,
                        square_tolerance=square_tolerance,
                    )

                    if download:
                        qdir = out / f"{n:02d}_{safe_filename(q, f'busca_{n}')}"
                        for i, result in enumerate(detailed, start=1):
                            await download_original(context, result, qdir, i)

                    entry.update(
                        ok=True,
                        results_found=len(detailed),
                        scan_stats=scan_stats,
                        results=detailed,
                    )
                except Exception as exc:
                    # Uma busca que falha não derruba as próximas.
                    entry["error"] = str(exc)
                    entry["results_found"] = 0
                    entry["results"] = []

                searches.append(entry)

            return {
                "ok": any(s["ok"] for s in searches),
                "engine": "bing_images",
                "mode": "batch",
                "submit_method": submit_method,
                "searches_requested": len(plan),
                "searches_ok": sum(1 for s in searches if s["ok"]),
                "total_results": sum(s["results_found"] for s in searches),
                "searches": searches,
            }
        finally:
            await context.close()
            await browser.close()


# ----------------------------------------------------------------------------
# API
# ----------------------------------------------------------------------------
app = FastAPI(
    title="Bing Images Browser API",
    version="1.1.0",
    description="Pesquisa imagens no Bing através de um navegador Playwright.",
)

ORIENTATION_DOC = "any (qualquer) | horizontal | vertical | square (quadrada)"


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "bing-image-browser-api"}


@app.get("/api/images/search")
async def api_search(
    q: str = Query(..., min_length=1),
    first: int = Query(1, ge=1),
    limit: int = Query(3, ge=1, le=MAX_LIMIT),
    aspect: str | None = Query(None, pattern="^(wide|tall|square)$"),
    animated: bool = False,
    transparent: bool = False,
    size: str | None = Query(None, pattern="^(large|wallpaper|medium|small)$"),
    extra_qft: str | None = None,
    mkt: str = "pt-BR",
    orientation: str = Query("any", description=ORIENTATION_DOC),
    square_tolerance: float = Query(0.1, ge=0, le=0.5),
    click_details: bool = True,
    download: bool = False,
    output_dir: str = "bing_downloads",
    headless: bool = False,
) -> JSONResponse:
    try:
        payload = await search_images_browser(
            q=q,
            first=first,
            limit=limit,
            aspect=aspect,
            animated=animated,
            transparent=transparent,
            size=size,
            extra_qft=extra_qft,
            mkt=mkt,
            orientation=orientation,
            square_tolerance=square_tolerance,
            click_details=click_details,
            headless=headless,
            download=download,
            output_dir=output_dir,
        )
        return JSONResponse(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class BatchRequest(BaseModel):
    # ["gojo", "geto"]  ou  [{"q": "gojo", "limit": 10, "orientation": "vertical"}, ...]
    queries: list[Any]
    limit: int = Field(3, ge=1, le=MAX_LIMIT)
    aspect: str | None = Field(None, pattern="^(wide|tall|square)$")
    animated: bool = False
    transparent: bool = False
    size: str | None = Field(None, pattern="^(large|wallpaper|medium|small)$")
    extra_qft: str | None = None
    mkt: str = "pt-BR"
    orientation: str = "any"
    square_tolerance: float = Field(0.1, ge=0, le=0.5)
    click_details: bool = True
    submit_method: str = Field("auto", pattern="^(auto|enter|click)$")
    download: bool = False
    output_dir: str = "bing_downloads"
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
    limit: int = Query(3, ge=1, le=MAX_LIMIT),
    aspect: str | None = Query(None, pattern="^(wide|tall|square)$"),
    animated: bool = False,
    transparent: bool = False,
    size: str | None = Query(None, pattern="^(large|wallpaper|medium|small)$"),
    extra_qft: str | None = None,
    mkt: str = "pt-BR",
    orientation: str = Query("any", description=ORIENTATION_DOC),
    square_tolerance: float = Query(0.1, ge=0, le=0.5),
    click_details: bool = True,
    submit_method: str = Query("auto", pattern="^(auto|enter|click)$"),
    download: bool = False,
    output_dir: str = "bing_downloads",
    headless: bool = False,
    pause_between_ms: int = Query(1500, ge=0, le=60_000),
) -> JSONResponse:
    return await _run_batch(
        queries=q, limit=limit, aspect=aspect, animated=animated,
        transparent=transparent, size=size, extra_qft=extra_qft, mkt=mkt,
        orientation=orientation, square_tolerance=square_tolerance,
        click_details=click_details, submit_method=submit_method,
        download=download, output_dir=output_dir, headless=headless,
        pause_between_ms=pause_between_ms,
    )


@app.post("/api/images/batch")
async def api_batch_post(body: BatchRequest) -> JSONResponse:
    return await _run_batch(**body.model_dump())


# ----------------------------------------------------------------------------
# Teste e linha de comando
# ----------------------------------------------------------------------------
def _print_item(item: dict[str, Any]) -> None:
    print(f"\n#{item['rank']} {item.get('title', '')}")
    print(
        "  proporção:", item.get("orientation"),
        f"(razão {item.get('aspect_ratio')}, fonte {item.get('orientation_source')})",
    )
    print("  detalhe:", item.get("detail_url"))
    print("  original:", item.get("original_url"))
    print("  fonte:", item.get("source_page"))
    print("  dimensões:", item.get("width"), "x", item.get("height"))
    print("  click detalhe:", item.get("detail_opened"))
    print("  baixada:", item.get("downloaded"))
    if item.get("download_path"):
        print("  arquivo:", item.get("download_path"))
    elif item.get("download_error"):
        print("  erro download:", item.get("download_error"))


async def run_test(headless: bool = False, orientation: str = "any") -> None:
    print("=" * 72)
    print("TESTE: Bing Images / primeiras 3 imagens")
    print("=" * 72)

    payload = await search_images_browser(
        q="gojo eyes",
        first=1,
        limit=3,
        aspect="wide",
        orientation=orientation,
        headless=headless,
        download=True,
        output_dir="bing_test_downloads",
    )

    print("\nURL usada:")
    print(payload["search_url"])
    for item in payload["results"]:
        _print_item(item)

    out = Path("bing_test_results.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON salvo em: {out.resolve()}")


async def run_batch_cli(args: argparse.Namespace) -> None:
    payload = await search_images_batch(
        queries=args.batch,
        limit=args.limit,
        aspect=args.aspect,
        orientation=args.orientation,
        square_tolerance=args.square_tolerance,
        click_details=not args.no_details,
        submit_method=args.submit_method,
        headless=args.headless,
        download=args.download,
        output_dir="bing_batch_downloads",
        pause_between_ms=args.pause_ms,
    )

    for s in payload["searches"]:
        print("\n" + "=" * 72)
        print(f"BUSCA {s['index']}: {s['query']}  [{s.get('search_method')}]")
        print("=" * 72)
        if s.get("error"):
            print("  ERRO:", s["error"])
        for item in s["results"]:
            _print_item(item)
        warn = (s.get("scan_stats") or {}).get("warning")
        if warn:
            print("\n  AVISO:", warn)

    out = Path("bing_batch_results.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON salvo em: {out.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bing Images Browser API")
    parser.add_argument("--test", action="store_true", help="Executa o teste Gojo Eyes com 3 resultados.")
    parser.add_argument(
        "--batch", nargs="+", metavar="TERMO",
        help='Várias buscas na mesma aba. Ex.: --batch "gojo" "geto" --limit 5',
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Imagens por busca (com --batch).")
    parser.add_argument("--download", action="store_true", help="Baixa as imagens (com --batch).")
    parser.add_argument("--aspect", choices=["wide", "tall", "square"], default=None,
                        help="Filtro de aspecto do próprio Bing (com --batch).")
    parser.add_argument("--orientation", default="any",
                        help="Proporção medida: any (qualquer), horizontal, vertical ou square (quadrada).")
    parser.add_argument("--square-tolerance", type=float, default=0.1,
                        help="Quão perto de 1:1 conta como quadrada (0.1 = razão entre 0.9 e 1.1).")
    parser.add_argument("--submit-method", choices=list(SUBMIT_METHODS), default="auto",
                        help="Como enviar a busca digitada: enter, click (lupa) ou auto (enter e, se falhar, clique).")
    parser.add_argument("--no-details", action="store_true", help="Não abre o detalhe de cada resultado.")
    parser.add_argument("--pause-ms", type=int, default=1500, help="Pausa entre buscas do lote.")
    parser.add_argument("--headless", action="store_true", help="Não abre a janela do Chromium.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.batch:
        asyncio.run(run_batch_cli(args))
        return

    if args.test:
        asyncio.run(run_test(headless=args.headless, orientation=args.orientation))
        return

    print(f"Bing Images Browser API: http://{args.host}:{args.port}")
    print("Endpoint: /api/images/search?q=gojo%20eyes&limit=3&orientation=horizontal")
    print("Lote:     /api/images/batch?q=gojo&q=geto&limit=5")
    uvicorn.run(app, host=args.host, port=args.port)


# ---------------------------------------------------------------------------
# OPTIONAL SOURCE-SITE INSPECTION
# ---------------------------------------------------------------------------
# Default behavior remains the original Bing behavior.
# When inspect_source=true, each selected Bing result's source page is opened
# and a JSON catalog of OG/meta/HTML image URLs is generated.

import json as _json
from urllib.parse import urljoin as _urljoin, urlparse as _urlparse

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".svg")

def _absolute_url(base, value):
    if not value:
        return None
    value = value.strip()
    if value.startswith("//"):
        return "https:" + value
    return _urljoin(base, value)

def _pick_srcset(value):
    if not value:
        return None
    parts = [x.strip() for x in value.split(",") if x.strip()]
    if not parts:
        return None
    # Prefer the candidate with the largest numeric descriptor.
    def score(x):
        m = re.search(r"(\d+)(w|x)?\s*$", x)
        return int(m.group(1)) if m else 0
    return parts[-1].split()[0] if score(parts[-1]) >= 0 else parts[0].split()[0]

async def _inspect_source_page(context, source_url):
    page = await context.new_page()
    page.set_default_timeout(20000)
    data = {
        "source_page": source_url,
        "og": {},
        "images": [],
    }

    try:
        await page.goto(source_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1200)

        # Trigger lazy-loaded images without changing normal Bing behavior.
        for _ in range(5):
            await page.mouse.wheel(0, 1200)
            await page.wait_for_timeout(350)

        metas = await page.locator("meta").evaluate_all("""
        els => els.map(m => ({
            property: m.getAttribute('property') || '',
            name: m.getAttribute('name') || '',
            content: m.getAttribute('content') || ''
        })).filter(x => x.content)
        """)

        for m in metas:
            key = (m["property"] or m["name"]).lower()
            if key in ("og:image", "og:image:url", "og:image:secure_url",
                       "twitter:image", "twitter:image:src"):
                data["og"][key] = _absolute_url(page.url, m["content"])

        imgs = await page.locator("img").evaluate_all("""
        els => els.map((img, i) => ({
            index: i,
            src: img.currentSrc || img.getAttribute('src') || '',
            dataSrc: img.getAttribute('data-src') || '',
            dataOriginal: img.getAttribute('data-original') || '',
            srcset: img.getAttribute('srcset') || '',
            alt: img.getAttribute('alt') || '',
            title: img.getAttribute('title') || '',
            width: img.naturalWidth || 0,
            height: img.naturalHeight || 0
        }))
        """)

        seen = set()

        def add_image(url, kind, meta=None):
            if not url:
                return
            absolute = _absolute_url(page.url, url)
            if not absolute:
                return
            key = absolute.split("#", 1)[0]
            if key in seen:
                return
            seen.add(key)
            item = {
                "name": Path(_urlparse(absolute).path).name or "",
                "url": absolute,
                "kind": kind,
            }
            if meta:
                item.update({
                    "alt": meta.get("alt", ""),
                    "title": meta.get("title", ""),
                    "width": meta.get("width", 0),
                    "height": meta.get("height", 0),
                })
            data["images"].append(item)

        # OG images are explicitly marked and kept at the beginning.
        for key, url in data["og"].items():
            add_image(url, key)

        for img in imgs:
            candidates = [
                ("img", img.get("src")),
                ("data-src", img.get("dataSrc")),
                ("data-original", img.get("dataOriginal")),
                ("srcset", _pick_srcset(img.get("srcset"))),
            ]
            for kind, url in candidates:
                add_image(url, kind, img)

        # Also collect direct image links.
        links = await page.locator("a[href]").evaluate_all("""
        els => els.map(a => a.href || '').filter(Boolean)
        """)
        for href in links:
            path = _urlparse(href).path.lower()
            if path.endswith(_IMAGE_EXTS):
                add_image(href, "image-link")

        return data

    except Exception as exc:
        data["error"] = str(exc)
        return data
    finally:
        await page.close()

async def inspect_bing_sources(results, context, json_path):
    catalog = {
        "engine": "bing_images",
        "results": [],
    }

    for result in results:
        source_url = (
            result.get("source_page")
            or result.get("page_url")
            or result.get("context_url")
            or result.get("source_url")
        )

        if not source_url:
            catalog["results"].append({
                "bing_result": result,
                "source_page": None,
                "og": {},
                "images": [],
                "error": "Bing result has no source page URL"
            })
            continue

        inspected = await _inspect_source_page(context, source_url)
        catalog["results"].append({
            "bing_result": result,
            **inspected
        })

    Path(json_path).write_text(
        _json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return catalog


# ---------------------------------------------------------------------------
# MODO PÓS-PROCESSADOR (opcional, não altera a busca)
# ---------------------------------------------------------------------------
#   python bing_image_api.py --inspect-json bing_batch_results.json
# Aceita o JSON de uma busca única ("results") ou de um lote ("searches").
# Gera *_sources.json com OG + todas as imagens achadas nas páginas de origem.

async def _run_inspect_json(input_json, output_json=None, headless=False):
    raw = _json.loads(Path(input_json).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        if "searches" in raw:  # formato do lote
            results = [r for s in raw["searches"] for r in s.get("results", [])]
        else:
            results = raw.get("results", raw.get("images", []))
    else:
        results = raw

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context(
            locale="pt-BR",
            viewport={"width": 1440, "height": 900},
        )
        try:
            output_json = output_json or str(
                Path(input_json).with_name(Path(input_json).stem + "_sources.json")
            )
            return await inspect_bing_sources(results, context, output_json)
        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    import sys as _sys
    if "--inspect-json" in _sys.argv:
        import argparse as _argparse
        ap = _argparse.ArgumentParser()
        ap.add_argument("--inspect-json", required=True)
        ap.add_argument("--output")
        ap.add_argument("--headless", action="store_true")
        a = ap.parse_args()
        asyncio.run(_run_inspect_json(a.inspect_json, a.output, a.headless))
    else:
        main()  # (o original chamava main() duas vezes; corrigido)
