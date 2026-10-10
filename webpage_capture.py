"""
webpage_capture.py
====================

Captura GENÉRICA de qualquer página web pra virar base de vídeo — não
depende da estrutura HTML de nenhum site específico (ao contrário de um
scraper feito pra um site só). Devolve três coisas:

  1. Um PRINT da página (ou da área de conteúdo principal, se
     detectada) — um PNG, possivelmente bem alto (a página inteira).
  2. Um MAPA de blocos de texto (títulos, parágrafos, listas, legendas
     de imagem) com a posição/tamanho de cada um DENTRO do print — é
     esse mapa que permite depois "focar a câmera" num trecho
     específico (ver `webpage_animator.py`).
  3. Uma GALERIA das imagens da página, baixadas separadamente com uma
     legenda (de um `<figcaption>` próximo, ou do `alt` se não tiver) — prontas pra
     usar como qualquer outra imagem do site (banco de mídia,
     segmento de imagem, etc), não só dentro do vídeo da própria
     página capturada.

Funciona em cima do MESMO princípio da extração de matéria de notícia
de outros projetos (achar automaticamente `h1,h2,h3,h4,p,blockquote,li,
figcaption` e medir a posição deles na tela) — só que sem nenhuma regra
específica de site: tenta achar uma área de conteúdo principal razoável
(`<article>`, depois `<main>`, senão a página inteira) e funciona a
partir daí.

NÃO cobre (por enquanto): posts do X/Twitter e Instagram — esses
plataformas bloqueiam/exigem login pra abrir o DOM de verdade via
navegador, então precisam de uma abordagem diferente (ler os dados via
API pública e desenhar um cartão do zero, em vez de tirar print da
página) — ver a observação no README do projeto.
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse


class WebpageCaptureError(Exception):
    """Erro genérico de captura — página inacessível, Playwright não
    instalado, timeout, etc."""


def _slugify(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-zA-Z0-9]+", "_", texto).strip("_").lower()
    return texto[:80] or "pagina"


# Seletores removidos ANTES de medir/tirar o print — coisa que
# tipicamente não faz sentido levar pro vídeo (anúncio, cookie banner,
# comentários, newsletter, compartilhamento) e que iria "sujar" tanto o
# print quanto o mapa de blocos de texto com ruído. Como não sabemos o
# HTML de cada site de antemão, isso é feito por PADRÃO de classe/id
# (não por seletor exato de um site), então funciona de forma
# razoável em qualquer lugar sem depender da estrutura exata.
_SELETORES_PARA_REMOVER = [
    "script", "noscript", "style", "iframe:not([src*='youtube'])",
    "nav", "footer", "aside",
    "[class*='cookie' i]", "[id*='cookie' i]", "[class*='consent' i]", "[id*='consent' i]",
    "[class*='advert' i]", "[id*='advert' i]", "[class*='adsbygoogle' i]",
    "[class*='sponsor' i]", "[id*='sponsor' i]", "[class*='patrocin' i]", "[id*='patrocin' i]",
    "[class*='newsletter' i]", "[class*='comment' i]", "[id*='comment' i]",
    "[class*='share' i]:not([class*='shape' i])", "[class*='popup' i]", "[class*='modal' i]",
]


def capturar_pagina(
    url: str,
    output_dir: str,
    largura_viewport: int = 1400,
    timeout_ms: int = 60000,
    headless: bool = True,
) -> Dict[str, Any]:
    """Abre `url` num navegador headless, encontra a área de conteúdo
    principal (tenta `<article>`, depois `<main>`, senão a página
    inteira), tira um print PNG dela, mede a posição de cada bloco de
    texto relevante, e baixa as imagens numa galeria separada com
    legenda.

    Devolve um dict:
      `{"screenshot_path": ..., "map_path": ..., "gallery_dir": ...,
        "blocos": [...], "galeria": [...], "titulo": ..., "url": ...}`

    `blocos`: lista de `{"id", "tipo", "texto", "x", "y", "largura",
        "altura"}` — posição relativa ao TOPO ESQUERDO do print.
    `galeria`: lista de `{"arquivo", "legenda", "url_original", "x",
        "y", "largura", "altura"}`.

    Levanta `WebpageCaptureError` com uma mensagem clara se o
    Playwright não estiver instalado, a página não carregar, ou nada
    de conteúdo relevante for encontrado.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise WebpageCaptureError(
            "Playwright não está instalado. Rode: pip install playwright && playwright install chromium"
        ) from exc

    os.makedirs(output_dir, exist_ok=True)
    galeria_dir = os.path.join(output_dir, "galeria")
    os.makedirs(galeria_dir, exist_ok=True)
    screenshot_path = os.path.join(output_dir, "captura_completa.png")
    map_path = os.path.join(output_dir, "mapa_texto_imagem.json")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                context = browser.new_context(
                    viewport={"width": largura_viewport, "height": 1000},
                    device_scale_factor=2,
                    java_script_enabled=True,
                )
                page = context.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception as exc:  # noqa: BLE001
                    raise WebpageCaptureError(f"Não consegui abrir a página: {exc}") from exc
                page.wait_for_timeout(800)

                titulo = page.title() or url

                # Acha a área de conteúdo principal -- sem depender de
                # nenhum site específico: tenta as tags semânticas
                # padrão do HTML5 nessa ordem, cai pro <body> inteiro
                # se nenhuma existir.
                seletor_conteudo = None
                for candidato in ("article", "main"):
                    if page.locator(candidato).first.count() > 0:
                        seletor_conteudo = candidato
                        break
                if seletor_conteudo is None:
                    seletor_conteudo = "body"

                # Remove ruído (anúncio, cookie banner, etc) só DENTRO
                # da área de conteúdo -- por padrão de classe/id, não
                # por regra de site específico.
                page.evaluate(
                    """([seletorConteudo, seletoresRemover]) => {
                        const raiz = document.querySelector(seletorConteudo);
                        if (!raiz) return;
                        raiz.querySelectorAll(seletoresRemover.join(',')).forEach(el => el.remove());
                    }""",
                    [seletor_conteudo, _SELETORES_PARA_REMOVER],
                )

                # Rola a página inteira pra disparar carregamento
                # preguiçoso (lazy-load) de imagens antes de medir/
                # printar -- sem isso, imagens fora da tela inicial
                # nunca chegam a carregar.
                page.evaluate(
                    """async () => {
                        const passo = Math.max(400, Math.floor(window.innerHeight * 0.8));
                        const alturaTotal = document.documentElement.scrollHeight;
                        for (let y = 0; y < alturaTotal; y += passo) {
                            window.scrollTo(0, y);
                            await new Promise(r => setTimeout(r, 220));
                        }
                        window.scrollTo(0, 0);
                        await new Promise(r => setTimeout(r, 300));
                    }"""
                )
                page.wait_for_timeout(500)

                # Mede blocos de texto e imagens ANTES do screenshot
                # (não depois) -- qualquer reflow entre medir e
                # printar deixaria as coordenadas do mapa
                # correspondendo a um layout diferente do print final.
                dados = page.evaluate(
                    """(seletorConteudo) => {
                        const raiz = document.querySelector(seletorConteudo);
                        if (!raiz) return null;
                        const rr = raiz.getBoundingClientRect();

                        const blocos = [];
                        let idxBloco = 0;
                        for (const el of raiz.querySelectorAll('h1,h2,h3,h4,p,blockquote,li,figcaption')) {
                            const texto = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                            if (!texto || texto.length < 2) continue;
                            const r = el.getBoundingClientRect();
                            if (r.width < 2 || r.height < 2) continue;
                            const tag = el.tagName.toLowerCase();
                            blocos.push({
                                id: 'bloco_' + String(++idxBloco).padStart(4, '0'),
                                tipo: tag === 'figcaption' ? 'legenda_imagem' : tag,
                                texto: texto,
                                x: Math.round(r.left - rr.left),
                                y: Math.round(r.top - rr.top),
                                largura: Math.round(r.width),
                                altura: Math.round(r.height),
                            });
                        }

                        const imagens = [];
                        let idxImg = 0;
                        for (const img of raiz.querySelectorAll('img')) {
                            const r = img.getBoundingClientRect();
                            if (r.width < 40 || r.height < 40) continue;  // ícone pequeno, não é conteúdo
                            const src = img.currentSrc || img.src || '';
                            if (!src || src.startsWith('data:')) continue;
                            let legenda = '';
                            const fig = img.closest('figure');
                            const cap = fig ? fig.querySelector('figcaption') : null;
                            if (cap) legenda = (cap.innerText || '').trim();
                            if (!legenda) legenda = img.getAttribute('alt') || '';
                            imagens.push({
                                id: 'imagem_' + String(++idxImg).padStart(4, '0'),
                                url: src,
                                legenda: legenda.replace(/\\s+/g, ' ').trim(),
                                x: Math.round(r.left - rr.left),
                                y: Math.round(r.top - rr.top),
                                largura: Math.round(r.width),
                                altura: Math.round(r.height),
                            });
                        }

                        return { blocos, imagens, larguraConteudo: Math.round(rr.width), alturaConteudo: Math.round(rr.height) };
                    }""",
                    seletor_conteudo,
                )
                if not dados:
                    raise WebpageCaptureError(
                        f"Não encontrei a área de conteúdo ({seletor_conteudo!r}) depois de carregar a página."
                    )
                if not dados["blocos"] and not dados["imagens"]:
                    raise WebpageCaptureError(
                        "Não encontrei nenhum texto ou imagem relevante nessa página — confira se a URL "
                        "está certa e se a página carrega conteúdo sem precisar de login."
                    )

                elemento_conteudo = page.locator(seletor_conteudo).first
                elemento_conteudo.screenshot(path=screenshot_path)

                galeria = _baixar_galeria(page, dados["imagens"], galeria_dir, url)
            finally:
                browser.close()
    except WebpageCaptureError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise WebpageCaptureError(f"Falha inesperada ao capturar a página: {exc}") from exc

    mapa = {
        "url": url,
        "titulo": titulo,
        "capturado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "largura": dados["larguraConteudo"],
        "altura": dados["alturaConteudo"],
        "blocos": dados["blocos"],
        "galeria": galeria,
    }
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(mapa, f, ensure_ascii=False, indent=2)

    return {
        "screenshot_path": screenshot_path,
        "map_path": map_path,
        "gallery_dir": galeria_dir,
        "blocos": dados["blocos"],
        "galeria": galeria,
        "titulo": titulo,
        "url": url,
    }


def _baixar_galeria(page, imagens: List[Dict[str, Any]], galeria_dir: str, url_base: str) -> List[Dict[str, Any]]:
    """Baixa cada imagem encontrada (via `page.request`, reaproveitando
    os cookies/sessão do navegador — necessário pra sites que exigem
    referer/sessão pra servir a própria imagem) pra dentro de
    `galeria_dir`, com um nome de arquivo previsível."""
    resultado = []
    for img in imagens:
        url_absoluta = urljoin(url_base, img["url"])
        try:
            resp = page.request.get(url_absoluta, timeout=20000)
            if not resp.ok:
                continue
            corpo = resp.body()
        except Exception:  # noqa: BLE001
            continue
        if not corpo or len(corpo) < 200:  # provavelmente um pixel de rastreamento, não uma foto de verdade
            continue

        extensao = os.path.splitext(urlparse(url_absoluta).path)[1].lower()
        if extensao not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"):
            extensao = ".jpg"
        nome_arquivo = f"{img['id']}{extensao}"
        caminho = os.path.join(galeria_dir, nome_arquivo)
        with open(caminho, "wb") as f:
            f.write(corpo)

        resultado.append({
            "arquivo": nome_arquivo,
            "legenda": img["legenda"],
            "url_original": url_absoluta,
            "x": img["x"], "y": img["y"], "largura": img["largura"], "altura": img["altura"],
        })
    return resultado
