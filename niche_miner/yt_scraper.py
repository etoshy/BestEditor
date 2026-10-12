#!/usr/bin/env python3
"""
yt_scraper.py
=============

Automatiza (localmente, no seu navegador) o fluxo de "mineração de nicho"
no YouTube:

  1. (Opcional) Gera subnichos e termos de busca em inglês a partir de um
     nicho amplo, usando a API da Anthropic (ANTHROPIC_API_KEY).
  2. (Opcional) Checa o Google Trends pra cada termo, pra ver se tem
     tendência de crescimento.
  3. Para cada termo: abre uma aba com contexto novo (equivalente a
     "anônimo"), pesquisa no YouTube, aplica filtros (3-20 min, este mês,
     ordenar por popularidade) e coleta ~100 resultados.
  4. Separa canais verificados dos não verificados.
  5. Para cada canal não verificado, visita o canal e coleta: nº de
     inscritos, nº de vídeos publicados e a data do PRIMEIRO vídeo postado
     (indicando há quanto tempo o canal realmente começou a postar).
  6. Gera um ranking consolidado (todos os termos) de canais "suspeitos":
     muitos inscritos, poucos vídeos, começaram a postar há pouco tempo —
     ou seja, um formato/nicho que decolou rápido e vale investigar.

Requisitos:
    pip install playwright --break-system-packages
    python3 -m playwright install chromium
    # opcionais:
    pip install anthropic --break-system-packages   # geração automática de subnichos
    pip install pytrends --break-system-packages    # checagem de Google Trends

Uso:
    # modo manual, um ou mais termos direto
    python3 yt_scraper.py --termos "serial killer documentary,unsolved murder case"

    # termos vindos de um arquivo (um por linha)
    python3 yt_scraper.py --termos-file termos.txt

    # deixa a IA sugerir subnichos e termos a partir de um nicho amplo
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 yt_scraper.py --nicho "crime" --trends

O resultado é salvo em:
    resultados_busca.csv       -> todos os vídeos coletados (todos os termos)
    canais_nao_verificados.csv -> ranking final consolidado dos canais
"""

import argparse
import csv
import re
import sys
import time
from datetime import datetime, timedelta
from urllib.parse import quote

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

NAV_TIMEOUT = 30_000
SCROLL_PAUSE = 1.2


def build_search_url(term: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote(term)}"


def open_filter_menu(page):
    """Abre o painel nativo de filtros do YouTube com vários fallbacks.

    O YouTube muda o seletor/aria-label do botão com frequência. Em versões
    recentes o botão pode estar dentro de componentes que não respondem bem a
    um seletor único. Por isso primeiro tentamos seletores diretos e depois
    um clique via DOM procurando qualquer botão visível cujo texto/aria-label
    contenha "filtro/filter".
    """
    dialog = page.locator('ytd-search-filter-options-dialog-renderer').first
    try:
        if dialog.count() and dialog.is_visible():
            return True
    except Exception:
        pass

    selectors = [
        'button[aria-label*="Filtro" i]',
        'button[aria-label*="Filter" i]',
        '[data-tooltip-text*="Filtro" i]',
        '[data-tooltip-text*="Filter" i]',
        '#filter-button',
        'ytd-search-sub-menu-renderer button',
        'ytd-search-sub-menu-renderer tp-yt-paper-button',
        'yt-chip-cloud-renderer button[aria-label*="Filtro" i]',
    ]

    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2500)
                page.wait_for_timeout(700)
                if page.locator('ytd-search-filter-options-dialog-renderer').count():
                    try:
                        if page.locator('ytd-search-filter-options-dialog-renderer').first.is_visible():
                            return True
                    except Exception:
                        return True
        except Exception:
            continue

    # Último fallback: clique real no elemento encontrado no DOM.
    try:
        clicked = page.evaluate("""() => {
            const nodes = Array.from(document.querySelectorAll(
                'button, [role=\"button\"], tp-yt-paper-button, yt-button-shape'
            ));
            const candidate = nodes.find(el => {
                const label = [
                    el.getAttribute('aria-label'),
                    el.getAttribute('title'),
                    el.getAttribute('data-tooltip-text'),
                    el.textContent
                ].filter(Boolean).join(' ');
                const visible = !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                return visible && /filtro|filter/i.test(label);
            });
            if (!candidate) return false;
            candidate.click();
            return true;
        }""")
        if clicked:
            page.wait_for_timeout(900)
            if page.locator('ytd-search-filter-options-dialog-renderer').count():
                return True
    except Exception:
        pass

    return False


def find_filter_href(page, group_pattern: str, option_patterns: list):
    """
    Estrutura real do diálogo de filtros do YouTube:

        ytd-search-filter-group-renderer
          h4#filter-group-name > yt-formatted-string   (nome do grupo, ex: "Duração")
          ytd-search-filter-renderer                     (uma opção)
            a#endpoint[href=".../results?...&sp=XXXX"]
              div#label[title="Pesquisar por ..."]
                yt-formatted-string                      (texto da opção)

    Em vez de clicar (sujeito a overlay/animação), pegamos o href pronto
    -- o próprio YouTube já calcula o parâmetro sp= combinando os filtros
    já aplicados anteriormente -- e navegamos direto pra lá.
    """
    grp_rx = re.compile(group_pattern, re.IGNORECASE)
    for grp in page.query_selector_all("ytd-search-filter-group-renderer"):
        h4 = grp.query_selector("h4#filter-group-name, h4")
        if not h4:
            continue
        try:
            group_text = h4.inner_text().strip()
        except Exception:
            continue
        if not grp_rx.search(group_text):
            continue

        # achamos o grupo certo (ex: "Duração"); procura a opção dentro dele
        for opt_pattern in option_patterns:
            opt_rx = re.compile(opt_pattern, re.IGNORECASE)
            for opt in grp.query_selector_all("ytd-search-filter-renderer"):
                label = opt.query_selector("#label")
                if not label:
                    continue
                title_attr = label.get_attribute("title") or ""
                try:
                    label_text = label.inner_text()
                except Exception:
                    label_text = ""
                combined = f"{title_attr} {label_text}"
                if opt_rx.search(combined):
                    a = opt.query_selector("a#endpoint")
                    href = a.get_attribute("href") if a else None
                    if href:
                        return href
        return None  # grupo encontrado mas nenhuma opção bateu
    return None


def apply_single_filter(page, group_pattern: str, option_patterns: list, label_for_log: str) -> bool:
    if not open_filter_menu(page):
        print(f"  AVISO: não consegui abrir o menu de filtros para '{label_for_log}'.")
        return False
    page.wait_for_timeout(500)

    href = find_filter_href(page, group_pattern, option_patterns)
    if not href:
        print(f"  AVISO: não encontrei a opção '{label_for_log}' no menu de filtros.")
        return False

    full_url = "https://www.youtube.com" + href if href.startswith("/") else href
    page.goto(full_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    return True


def _normalizar_filtros(filtros=None):
    """Normaliza a configuração recebida da interface web/CLI."""
    filtros = dict(filtros or {})
    try:
        min_d = max(0, int(filtros.get("duracao_min", 3)))
    except (TypeError, ValueError):
        min_d = 3
    try:
        max_d = max(0, int(filtros.get("duracao_max", 20)))
    except (TypeError, ValueError):
        max_d = 20
    if max_d and min_d > max_d:
        min_d, max_d = max_d, min_d

    data_periodo = str(filtros.get("data_periodo", "mes")).strip().lower()
    if data_periodo not in {"hoje", "semana", "mes", "ano", "todos"}:
        data_periodo = "mes"

    ordenacao = str(filtros.get("ordenacao", "popularidade")).strip().lower()
    if ordenacao not in {"popularidade", "relevancia"}:
        ordenacao = "popularidade"

    return {
        "duracao_min": min_d,
        "duracao_max": max_d,
        "data_periodo": data_periodo,
        "ordenacao": ordenacao,
    }


def _normalizar_analise(analise=None):
    """Normaliza a configuração da análise de canal (janela de idade e amostra de frequência)."""
    analise = dict(analise or {})
    try:
        janela = max(0.0, float(analise.get("janela_meses", 3)))  # 0 = sem limite
    except (TypeError, ValueError):
        janela = 3.0
    try:
        n_freq = int(analise.get("n_frequencia", 50))
    except (TypeError, ValueError):
        n_freq = 50
    return {
        "janela_meses": int(janela) if janela.is_integer() else janela,
        "descartar_fora_janela": bool(analise.get("descartar_fora_janela", True)),
        "n_frequencia": min(100, max(10, n_freq)),
    }


def _label_filtro_duracao(min_d, max_d):
    if min_d == 0 and max_d == 0:
        return "duração (todas)"
    if min_d == 0 and max_d == 3:
        return "duração (menos de 3 minutos)"
    if min_d == 3 and max_d == 20:
        return "duração (3 a 20 minutos)"
    if min_d >= 20 and (not max_d or max_d >= 120):
        return "duração (mais de 20 minutos)"
    if max_d == 0:
        return f"duração ({min_d}+ minutos)"
    return f"duração ({min_d}-{max_d} minutos) — validação exata"


def _filtro_nativo_duracao(min_d, max_d):
    """Retorna padrões do menu nativo quando o intervalo coincide com o YouTube."""
    if min_d == 0 and max_d == 3:
        return [r"menos\s*de\s*3\s*min"]
    if min_d == 3 and max_d == 20:
        return [r"de\s*3\s*a\s*20\s*min", r"3\s*[-–]\s*20\s*min"]
    if min_d >= 20 and (not max_d or max_d >= 120):
        return [r"mais\s*de\s*20\s*min"]
    return None


def apply_filters(page, filtros=None):
    """Aplica os filtros escolhidos na interface.

    O menu nativo é usado quando existe uma opção equivalente. Para um
    intervalo de duração personalizado, a validação exata é feita depois da
    coleta dos cards.
    """
    cfg = _normalizar_filtros(filtros)
    min_d = cfg["duracao_min"]
    max_d = cfg["duracao_max"]
    periodo = cfg["data_periodo"]
    ordenacao = cfg["ordenacao"]

    native_duration = _filtro_nativo_duracao(min_d, max_d)
    if native_duration:
        label = _label_filtro_duracao(min_d, max_d)
        print(f"Aplicando filtro: {label}...")
        apply_single_filter(page, r"dura[cç][aã]o", native_duration, label)
    else:
        print(f"Aplicando filtro: {_label_filtro_duracao(min_d, max_d)}...")
        print("  Duração personalizada: será aplicada com validação exata nos vídeos coletados.")

    periodo_patterns = {
        "hoje": [r"hoje"],
        "semana": [r"esta\s*semana"],
        "mes": [r"este\s*m[eê]s"],
        "ano": [r"este\s*ano"],
        "todos": None,
    }
    if periodo_patterns[periodo]:
        labels = {"hoje": "Hoje", "semana": "Esta semana", "mes": "Este mês", "ano": "Este ano"}
        label = f"data de upload ({labels[periodo]})"
        print(f"Aplicando filtro: {label}...")
        apply_single_filter(page, r"data do upload", periodo_patterns[periodo], label)
    else:
        print("Aplicando filtro: data de upload (todas as datas)...")
        print("  Sem filtro nativo de data; a validação final não excluirá por idade.")

    if ordenacao == "popularidade":
        print("Aplicando filtro: prioridade (popularidade)...")
        apply_single_filter(page, r"prioridade", [r"popularidade"], "prioridade (popularidade)")
    else:
        print("Aplicando ordenação: relevância (padrão do YouTube)...")

    print("Filtros aplicados. URL atual:", page.url)
    return cfg


def parse_count(text: str):
    """Converte contagens do YouTube respeitando separadores PT/EN.

    Exemplos: ``841 mil inscritos`` -> 841000, ``8.443 visualizações`` ->
    8443, ``1,2 mi`` -> 1200000, ``8.4K`` -> 8400.
    """
    if not text:
        return None
    raw = str(text).lower().replace("\xa0", " ").strip()
    m = re.search(r"(\d[\d.,]*)\s*(mil|mi|k|m|b)?", raw)
    if not m:
        return None
    num_str, suffix = m.groups()
    suffix = suffix or ""

    # Interpreta pontuação conforme o contexto numérico/local.
    seps = re.findall(r"[.,]", num_str)
    if len(seps) > 1 and len(set(seps)) == 1:
        # Vários separadores iguais só podem ser agrupamento de milhares
        # ("1.234.567" ou "1,234,567"), como no total de views da aba Sobre.
        normalized = num_str.replace(seps[0], "")
    elif "." in num_str and "," in num_str:
        # O último separador é o decimal; os anteriores são milhares.
        if num_str.rfind(",") > num_str.rfind("."):
            normalized = num_str.replace(".", "").replace(",", ".")
        else:
            normalized = num_str.replace(",", "").replace(".", ".")
    elif "," in num_str:
        left, right = num_str.rsplit(",", 1)
        normalized = num_str.replace(",", ".") if len(right) != 3 else left + right
    elif "." in num_str:
        left, right = num_str.rsplit(".", 1)
        # Sem sufixo, 8.443 normalmente é milhares no locale PT.
        # Com sufixo, 1.2M/1.2mi é decimal.
        if len(right) == 3:
            normalized = left + right
        else:
            normalized = num_str
    else:
        normalized = num_str

    try:
        num = float(normalized)
    except ValueError:
        return None
    mult = {
        "": 1, "k": 1_000, "mil": 1_000,
        "mi": 1_000_000, "m": 1_000_000,
        "b": 1_000_000_000,
    }.get(suffix, 1)
    return int(num * mult)


def parse_duration_seconds(text: str):
    """Converte HH:MM:SS / MM:SS para segundos."""
    if not text:
        return None
    raw = str(text).strip()
    if not re.fullmatch(r"\d{1,2}(:\d{2}){1,2}", raw):
        return None
    parts = [int(p) for p in raw.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    hours, minutes, seconds = parts
    return hours * 3600 + minutes * 60 + seconds



def texto_indica_patrocinado(texto: str) -> bool:
    """Detecta indicações comuns de conteúdo patrocinado/promoção paga."""
    if not texto:
        return False
    t = re.sub(r"\s+", " ", texto.lower()).strip()
    patterns = [
        r"\bpatrocinad[oa]s?\b",
        r"\bsponsored\b",
        r"\bpaid promotion\b",
        r"\bpaid partnership\b",
        r"\bincludes paid promotion\b",
        r"\bincludes a paid promotion\b",
        r"\binclui promoção paga\b",
        r"\bpromoção paga\b",
        r"\bparceria paga\b",
    ]
    return any(re.search(p, t, re.IGNORECASE) for p in patterns)


def extrair_data_publicacao(page):
    """Extrai a data real de publicação da página do vídeo (ISO, quando disponível)."""
    selectors = [
        'meta[itemprop="datePublished"]',
        'meta[property="article:published_time"]',
        'meta[name="date"]',
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if not el:
                continue
            value = el.get_attribute("content") or ""
            if not value:
                continue
            # Aceita ISO completo ou apenas YYYY-MM-DD.
            m = re.search(r"(\d{4}-\d{2}-\d{2})", value)
            if m:
                return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except Exception:
            continue
    return None


def _periodo_data_bounds(data_periodo: str, agora=None):
    """Retorna (inicio, fim) inclusivos para a janela escolhida."""
    agora = agora or datetime.now()
    hoje = agora.date()
    if data_periodo == "hoje":
        return hoje, hoje
    if data_periodo == "semana":
        return hoje.fromordinal(hoje.toordinal() - 6), hoje
    if data_periodo == "mes":
        return hoje.replace(day=1), hoje
    if data_periodo == "ano":
        return hoje.replace(month=1, day=1), hoje
    return None, None


def validar_video_no_periodo(page, video: dict, data_periodo="mes", agora=None):
    """Confirma data real e ausência de indicação de patrocínio."""
    try:
        page.goto(video["url"], timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        page.wait_for_timeout(700)

        # Primeiro verifica o conteúdo da página por disclosures de promoção paga.
        snippets = []
        for sel in [
            '[itemprop="paidPromotion"]',
            'ytd-paid-content-overlay-renderer',
            '#paid-content-overlay',
            'ytm-paid-content-overlay-renderer',
        ]:
            try:
                for el in page.query_selector_all(sel):
                    snippets.append(el.inner_text() or "")
            except Exception:
                pass
        try:
            body_text = page.locator("body").inner_text(timeout=2500)
        except Exception:
            body_text = ""
        snippets.append(body_text[:20000])

        if any(texto_indica_patrocinado(x) for x in snippets):
            return False, "patrocinado"

        published = extrair_data_publicacao(page)
        inicio, fim = _periodo_data_bounds(data_periodo, agora=agora)
        if published:
            pub_date = published.date() if hasattr(published, "date") else published
            if inicio and (pub_date < inicio or pub_date > fim):
                return False, f"fora_do_periodo:{published.isoformat()}"
        elif inicio:
            return False, "data_real_nao_verificada"

        if published:
            video["data_publicacao"] = published.isoformat()
        video["data_verificada"] = bool(published)
        video["patrocinado"] = False
        return True, "ok"
    except Exception as e:
        return False, f"erro_validacao:{type(e).__name__}"


def validar_video_no_mes(page, video: dict, ano: int, mes: int):
    """Compatibilidade com a API de testes/versões anteriores."""
    return validar_video_no_periodo(page, video, "mes", agora=datetime(ano, mes, 15))


_YT_MONTHS_PT = {
    "jan": 1, "janeiro": 1,
    "fev": 2, "fevereiro": 2,
    "mar": 3, "março": 3, "marco": 3,
    "abr": 4, "abril": 4,
    "mai": 5, "maio": 5,
    "jun": 6, "junho": 6,
    "jul": 7, "julho": 7,
    "ago": 8, "agosto": 8,
    "set": 9, "setembro": 9,
    "out": 10, "outubro": 10,
    "nov": 11, "novembro": 11,
    "dez": 12, "dezembro": 12,
}
_YT_MONTHS_EN = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _parse_date_text(text: str):
    """Converte datas visíveis do YouTube em date, priorizando DD/MM/YYYY e
    formatos textuais PT/EN como '26 de ago. de 2026' e 'Aug 26, 2026'."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", str(text).replace("\xa0", " ")).strip()

    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", t)
    if m:
        d, mo, y = map(int, m.groups())
        try:
            return datetime(y, mo, d).date()
        except ValueError:
            return None

    m = re.search(
        r"\b(\d{1,2})\s*(?:de\s*)?([A-Za-zÀ-ÿ.]+)\s*(?:de|,)\s*(\d{4})\b",
        t, re.IGNORECASE,
    )
    if m:
        d = int(m.group(1))
        month_token = m.group(2).lower().rstrip(".")
        mo = _YT_MONTHS_PT.get(month_token) or _YT_MONTHS_EN.get(month_token)
        if mo:
            try:
                return datetime(int(m.group(3)), mo, d).date()
            except ValueError:
                return None

    m = re.search(
        r"\b([A-Za-zÀ-ÿ.]+)\s+(\d{1,2})(?:,)?\s+(\d{4})\b",
        t, re.IGNORECASE,
    )
    if m:
        month_token = m.group(1).lower().rstrip(".")
        mo = _YT_MONTHS_PT.get(month_token) or _YT_MONTHS_EN.get(month_token)
        if mo:
            try:
                return datetime(int(m.group(3)), mo, int(m.group(2))).date()
            except ValueError:
                return None
    return None


def _extrair_views_data_do_texto_info(texto: str):
    """Extrai views e data do bloco #info/#tooltip do watch page."""
    texto = re.sub(r"\s+", " ", str(texto or "").replace("\xa0", " ")).strip()
    if not texto:
        return None, None, "", ""

    views_text = ""
    views_num = None
    published = _parse_date_text(texto)

    parts = [p.strip() for p in texto.split("•") if p.strip()]
    if parts:
        candidate = parts[0]
        # O primeiro pedaço do #info é normalmente só a contagem de views.
        if re.search(r"(?:visualiza|views?)", candidate, re.IGNORECASE):
            views_text = candidate
            views_num = parse_count(candidate)
    if views_num is None:
        m = re.search(r"(?:([\d.,]+)\s*(?:mil|mi|k|m|b)?)(?:\s+(?:visualizações|visualizacoes|views?))", texto, re.IGNORECASE)
        if m:
            views_text = m.group(0).strip()
            views_num = parse_count(views_text)

    date_text = ""
    if published:
        # Preserva um trecho amigável contendo apenas a data quando possível.
        for part in parts[1:]:
            if _parse_date_text(part):
                date_text = part
                break
        if not date_text:
            date_text = published.strftime("%Y-%m-%d")
    return views_num, published, views_text, date_text


def _expand_watch_description(page):
    """Expande a descrição/área de informações antes de ler o bloco #info."""
    selectors = [
        '#description tp-yt-paper-button#expand',
        'tp-yt-paper-button#expand',
        '#description-inline-expander tp-yt-paper-button#expand',
        'button[aria-label*="mais" i]',
        'button[aria-label*="more" i]',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2500)
                page.wait_for_timeout(400)
                return True
        except Exception:
            continue
    try:
        return bool(page.evaluate("""() => {
            const nodes = Array.from(document.querySelectorAll('tp-yt-paper-button,button,[role="button"]'));
            const el = nodes.find(x => {
                const txt = [x.getAttribute('aria-label'), x.textContent].filter(Boolean).join(' ');
                return /\b(\\.\\.\\.mais|mais|more)\b/i.test(txt) && (x.offsetWidth || x.offsetHeight || x.getClientRects().length);
            });
            if (!el) return false;
            el.click();
            return true;
        }"""))
    except Exception:
        return False
    return False


def extrair_watch_info(page, fallback_views_text="", fallback_when=""):
    """Lê views e data exatas do bloco atual do watch page.

    No layout atual do YouTube, #info pode mostrar uma data relativa, enquanto
    #tooltip contém o texto exato, por exemplo:
      '8.443 visualizações • 26 de ago. de 2026'
    """
    try:
        _expand_watch_description(page)
    except Exception:
        pass
    textos = []
    for sel in [
        '#info-container #tooltip',
        'ytd-watch-info-text #tooltip',
        '#info-container #info',
        'ytd-watch-info-text #info',
    ]:
        try:
            for el in page.query_selector_all(sel):
                txt = el.inner_text() or ""
                if txt.strip():
                    textos.append(txt.strip())
        except Exception:
            continue

    best = ""
    best_data = None
    best_views = None
    best_views_text = ""
    for txt in textos:
        views_num, published, views_text, date_text = _extrair_views_data_do_texto_info(txt)
        if published and not best_data:
            best_data = published
            best = date_text
        if views_num is not None and best_views is None:
            best_views = views_num
            best_views_text = views_text
        if published and views_num is not None:
            best = date_text or best
            best_data = published
            best_views = views_num
            best_views_text = views_text or best_views_text

    # O meta datePublished continua sendo um fallback excelente para a data.
    if best_data is None:
        try:
            best_data = extrair_data_publicacao(page)
        except Exception:
            best_data = None

    if best_views is None and fallback_views_text:
        best_views = parse_count(fallback_views_text)
        best_views_text = fallback_views_text

    if best_data is None and fallback_when:
        # Não inventa data; mantém o texto relativo apenas como fallback visual.
        best = fallback_when

    return {
        "data_publicacao": best_data.isoformat() if best_data else "",
        "data_texto": best or (best_data.strftime("%Y-%m-%d") if best_data else fallback_when or ""),
        "views_text": best_views_text or fallback_views_text or "",
        "views_num": best_views,
    }


def _enriquecer_video_com_watch_info(page, data: dict):
    """Abre um vídeo e substitui data/views aproximadas pelos valores exatos do watch page."""
    try:
        page.goto(data["url"], timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        page.wait_for_timeout(850)
        info = extrair_watch_info(page, data.get("views_text", ""), data.get("quando", ""))
        if info.get("views_num") is not None:
            data["views_num"] = info["views_num"]
            data["views_text"] = info["views_text"] or data.get("views_text", "")
        if info.get("data_publicacao"):
            data["data_publicacao"] = info["data_publicacao"]
            data["quando"] = info.get("data_texto") or info["data_publicacao"]
        else:
            data["data_publicacao"] = data.get("data_publicacao", "")
        return data
    except Exception as e:
        print(f"    [aviso ao ler data/views do vídeo {data.get('url','')}]: {type(e).__name__}: {e}")
        return data


def _filtrar_por_duracao(videos: list, filtros: dict):
    min_d = int(filtros.get("duracao_min", 3))
    max_d = int(filtros.get("duracao_max", 20))
    kept = []
    descartados = 0
    for video in videos:
        sec = video.get("duracao_segundos")
        if sec is None:
            # Sem duração verificável não é possível garantir um filtro exato.
            print(f"  IGNORADO — duração não identificada: {video.get('titulo', '')[:80]}")
            descartados += 1
            continue
        if sec < min_d * 60:
            descartados += 1
            continue
        if max_d and sec > max_d * 60:
            descartados += 1
            continue
        kept.append(video)
    if descartados:
        print(f"Filtro de duração: {descartados} vídeos descartados; {len(kept)} mantidos.")
    return kept


def collect_videos(page, max_videos: int):
    """Rola a página coletando cards de vídeo até atingir max_videos ou não carregar mais."""
    print(f"Coletando até {max_videos} vídeos...")
    seen_ids = set()
    videos = []

    stagnant_rounds = 0
    while len(videos) < max_videos and stagnant_rounds < 6:
        cards = page.query_selector_all("ytd-video-renderer")
        before = len(videos)

        for card in cards:
            link_el = card.query_selector("a#video-title")
            if not link_el:
                continue
            href = link_el.get_attribute("href") or ""
            if "watch?v=" not in href:
                continue
            vid = href.split("watch?v=")[-1].split("&")[0]
            if vid in seen_ids:
                continue
            seen_ids.add(vid)

            title = (link_el.get_attribute("title") or link_el.inner_text() or "").strip()
            try:
                card_text = card.inner_text() or ""
            except Exception:
                card_text = title
            if texto_indica_patrocinado(card_text):
                print(f"  Pulando vídeo patrocinado: {title[:80]}")
                continue

            channel_el = card.query_selector("ytd-channel-name a")
            channel_name = channel_el.inner_text().strip() if channel_el else ""
            channel_href = channel_el.get_attribute("href") if channel_el else ""
            channel_url = f"https://www.youtube.com{channel_href}" if channel_href else ""

            # selo de verificado — cobre o renderer antigo e aria-labels novos.
            verified = False
            badge_candidates = card.query_selector_all(
                "ytd-channel-name ytd-badge-supported-renderer, "
                "[aria-label*='verified' i], [aria-label*='verificado' i], "
                "[title*='verified' i], [title*='verificado' i]"
            )
            for badge in badge_candidates:
                badge_text = " ".join(
                    x for x in [
                        badge.get_attribute("aria-label") or "",
                        badge.get_attribute("title") or "",
                        badge.inner_text() or "",
                    ] if x
                ).lower()
                if "verific" in badge_text or "verified" in badge_text:
                    verified = True
                    break
                try:
                    icon_html = badge.inner_html().lower()
                    if "check" in icon_html and ("badge" in icon_html or "verif" in icon_html):
                        verified = True
                        break
                except Exception:
                    pass

            meta_spans = card.query_selector_all("#metadata-line span")
            views_text = meta_spans[0].inner_text() if len(meta_spans) > 0 else ""
            when_text = meta_spans[1].inner_text() if len(meta_spans) > 1 else ""

            duration_text = ""
            for dur_sel in [
                "ytd-thumbnail-overlay-time-status-renderer span",
                "badge-shape-wiz__text",
                "yt-thumbnail-overlay-time-status-renderer span",
            ]:
                try:
                    dur_el = card.query_selector(dur_sel)
                    if dur_el and (dur_el.inner_text() or "").strip():
                        duration_text = dur_el.inner_text().strip()
                        break
                except Exception:
                    pass

            videos.append({
                "video_id": vid,
                "titulo": title,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "canal": channel_name,
                "canal_url": channel_url,
                "canal_verificado": verified,
                "views_text": views_text,
                "views_num": parse_count(views_text),
                "quando": when_text,
                "duracao": duration_text,
                "duracao_segundos": parse_duration_seconds(duration_text),
                "data_publicacao": "",
                "data_verificada": False,
                "patrocinado": False,
            })

            if len(videos) >= max_videos:
                break

        if len(videos) == before:
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0

        page.mouse.wheel(0, 4000)
        time.sleep(SCROLL_PAUSE)

    print(f"Coletados {len(videos)} vídeos.")
    return videos


LANGUAGE_NAMES = {
    "pt": "Português",
    "en": "Inglês",
    "es": "Espanhol",
    "fr": "Francês",
    "de": "Alemão",
    "it": "Italiano",
}


def _infer_language(text: str):
    """Heurística de idioma baseada em texto do próprio canal, não na UI do YouTube."""
    if not text:
        return ""
    t = re.sub(r"[^a-záéíóúàâêôãõçüñ\s]", " ", text.lower())
    words = t.split()
    wordset = set(words)
    vocab = {
        "pt": {"que","não","uma","um","para","com","dos","das","você","sobre","vídeo","vídeos","canal","brasil","história","como","mais","por","são"},
        "en": {"the","and","with","for","this","that","you","about","video","videos","channel","documentary","history","how","more","from","are"},
        "es": {"que","una","con","para","este","esta","sobre","vídeo","canal","historia","los","las","cómo","más","desde","son"},
        "fr": {"les","des","une","avec","pour","dans","sur","vidéo","chaîne","histoire","plus","comment","sont","avec"},
        "de": {"die","der","das","und","mit","für","von","über","video","kanal","geschichte","mehr","wie","sind","aus"},
        "it": {"che","una","con","per","questo","video","canale","storia","degli","delle","come","più","sono","con"},
    }
    scores = {lang: len(wordset & terms) for lang, terms in vocab.items()}
    # Pesos para sinais fortes de idioma.
    for lang, strong in {
        "pt": {"não", "você", "brasil", "vídeos", "são"},
        "es": {"cómo", "historia", "vídeo"},
        "fr": {"vidéo", "chaîne", "histoire"},
        "de": {"geschichte", "kanal"},
        "it": {"canale", "storia"},
    }.items():
        scores[lang] += sum(1 for w in strong if w in wordset)
    best = max(scores, key=scores.get)
    if scores[best] < 3:
        return ""
    return LANGUAGE_NAMES.get(best, best)


def _extrair_pais_about(page, page_text: str):
    """Tenta obter o país explicitamente exibido na aba Sobre, sem usar o idioma da interface."""
    selectors = [
        '#country', '[id*="country" i]', '[class*="country" i]',
        'a[href*="country" i]', 'yt-formatted-string[aria-label*="country" i]',
        'yt-formatted-string[aria-label*="país" i]',
    ]
    for sel in selectors:
        try:
            for el in page.query_selector_all(sel)[:10]:
                txt = (el.inner_text() or el.get_attribute("aria-label") or "").strip()
                if txt and len(txt) < 80:
                    txt = re.sub(r"^(country|pa[ií]s)\s*[:\-]?\s*", "", txt, flags=re.I).strip()
                    if txt and txt.lower() not in {"country", "país"}:
                        return txt
        except Exception:
            pass

    # Fallback por linhas do texto, procurando a linha imediatamente após o rótulo.
    lines = [re.sub(r"\s+", " ", x).strip() for x in page_text.splitlines() if x.strip()]
    for i, line in enumerate(lines):
        if re.fullmatch(r"(?:country|pa[ií]s)", line, re.I) and i + 1 < len(lines):
            nxt = lines[i + 1]
            if len(nxt) <= 80:
                return nxt
    return ""


def _extract_channel_header_metadata(page, page_text: str = ""):
    """Extrai inscritos e total de vídeos da página principal do canal.

    O YouTube mudou o DOM e, em layouts atuais, esses dados aparecem em
    ``yt-content-metadata-view-model`` com ``aria-label`` no elemento que
    contém o texto. Ex.: ``841 mil inscritos`` e ``346 vídeos``.
    """
    result = {"inscritos_text": "", "inscritos_num": None, "n_videos": None}

    # 1) Estrutura atual observada no HTML enviado pelo usuário.
    sub_selectors = [
        'yt-content-metadata-view-model [aria-label*="inscrit" i]',
        'yt-content-metadata-view-model [aria-label*="subscriber" i]',
        'yt-content-metadata-view-model span[role="text"][aria-label*="inscrit" i]',
        'yt-content-metadata-view-model span[role="text"][aria-label*="subscriber" i]',
        '[aria-label*="inscritos" i]',
        '[aria-label*="subscribers" i]',
    ]
    for sel in sub_selectors:
        try:
            for el in page.query_selector_all(sel)[:20]:
                txt = (el.get_attribute("aria-label") or el.inner_text() or "").strip()
                if re.search(r"(?:inscrit|subscriber)", txt, re.I):
                    num = parse_count(txt)
                    if num is not None:
                        result["inscritos_text"] = txt
                        result["inscritos_num"] = num
                        break
        except Exception:
            pass
        if result["inscritos_num"] is not None:
            break

    # 2) Total de vídeos no mesmo bloco de metadados.
    video_selectors = [
        'yt-content-metadata-view-model [role="text"]',
        'yt-content-metadata-view-model span',
        '[aria-label*="vídeos" i]',
        '[aria-label*="videos" i]',
    ]
    for sel in video_selectors:
        try:
            for el in page.query_selector_all(sel)[:40]:
                txt = (el.get_attribute("aria-label") or el.inner_text() or "").strip()
                if re.search(r"\bvídeos?\b|\bvideos?\b", txt, re.I):
                    m = re.search(r"([\d\.,]+)\s*(?:mil|mi|k|m)?\s*(?:vídeos|videos)", txt, re.I)
                    if m:
                        result["n_videos"] = parse_count(m.group(0))
                        break
        except Exception:
            pass
        if result["n_videos"] is not None:
            break

    # 3) Fallback no texto visível da página. Útil quando o componente é
    # renderizado, mas seus atributos não estão acessíveis ao Playwright.
    text = page_text or ""
    if result["inscritos_num"] is None:
        m = re.search(r"([\d\.,]+(?:\s*(?:mil|mi|k|m|b))?)\s*(?:de\s*)?(?:inscritos|subscribers)", text, re.I)
        if m:
            result["inscritos_text"] = m.group(0).strip()
            result["inscritos_num"] = parse_count(m.group(1))
    if result["n_videos"] is None:
        m = re.search(r"([\d\.,]+(?:\s*(?:mil|mi|k|m|b))?)\s*(?:vídeos|videos)", text, re.I)
        if m:
            result["n_videos"] = parse_count(m.group(1))

    return result


def _extrair_stats_about(texto: str):
    """Lê do texto da aba Sobre o total de views e a data de criação do canal.

    O Sobre mostra o número completo ("12.345.678 visualizações") e
    "Inscreveu-se em 15 de mar. de 2024". O texto da descrição do canal vem
    antes das estatísticas, então usamos a ÚLTIMA ocorrência de "visualizações".
    """
    out = {"views_totais": None, "views_totais_text": "", "data_criacao_canal": ""}
    t = (texto or "").replace("\xa0", " ")
    achados = list(re.finditer(r"(\d[\d.,]*)\s*(?:visualiza[çc][õo]es|visualiza[çc][ãa]o|views?)\b", t, re.I))
    if achados:
        m = achados[-1]
        out["views_totais_text"] = m.group(0).strip()
        out["views_totais"] = parse_count(m.group(1))
    m = re.search(r"(?:Inscreveu-se em|Entrou em|Joined)\s+([^\n\r]+)", t, re.I)
    if m:
        d = _parse_date_text(m.group(1))
        if d:
            out["data_criacao_canal"] = d.isoformat()
    return out


def scrape_channel_about(page, channel_url: str):
    """Extrai inscritos/vídeos da página do canal e usa /about para país/idioma."""
    about_url = channel_url.rstrip("/") + "/about"
    result = {
        "inscritos_text": "", "inscritos_num": None, "n_videos": None,
        "pais_canal": "", "idioma_canal": "", "idioma_canal_rotulo": "Idioma provável",
        "views_totais": None, "views_totais_text": "", "data_criacao_canal": "",
    }
    try:
        # Os inscritos e o total de vídeos ficam na página principal do canal,
        # não dependem de #subscriber-count (seletor antigo).
        page.goto(channel_url.rstrip("/"), timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        header_text = page.inner_text("body")
        result.update(_extract_channel_header_metadata(page, header_text))

        # Agora usa /about para país e textos de contexto, sem perder os dados
        # capturados do cabeçalho.
        page.goto(about_url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        page_text = page.inner_text("body")

        # Algumas variantes ainda exibem inscritos/vídeos também no /about;
        # aproveitamos como fallback se a página principal não forneceu algum.
        fallback_meta = _extract_channel_header_metadata(page, page_text)
        for key in ("inscritos_text", "inscritos_num", "n_videos"):
            if result.get(key) in (None, "") and fallback_meta.get(key) not in (None, ""):
                result[key] = fallback_meta[key]

        result["pais_canal"] = _extrair_pais_about(page, page_text) or "País desconhecido"
        result.update(_extrair_stats_about(page_text))

        # Inferimos apenas a partir de conteúdo atribuído ao canal, não do
        # restante da interface do YouTube (que pode estar em pt-BR por causa
        # do navegador).
        language_chunks = []
        for sel in [
            '#description-container',
            'yt-description-text',
            'yt-attributed-string',
            'yt-content-metadata-view-model',
            'meta[property="og:title"]',
            'meta[property="og:description"]',
            'meta[name="description"]',
        ]:
            try:
                for el in page.query_selector_all(sel)[:20]:
                    txt = el.inner_text() or el.get_attribute("content") or ""
                    if txt.strip():
                        language_chunks.append(txt.strip())
            except Exception:
                pass
        # Inclui títulos de vídeos recentes para aumentar a cobertura quando a
        # descrição do canal é curta ou vazia.
        try:
            page.goto(channel_url.rstrip("/") + "/videos", timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            for card in page.query_selector_all("ytd-rich-item-renderer, ytd-grid-video-renderer, ytd-video-renderer")[:20]:
                title_el = card.query_selector("#video-title, a#video-title")
                if title_el:
                    txt = (title_el.get_attribute("title") or title_el.inner_text() or "").strip()
                    if txt:
                        language_chunks.append(txt)
        except Exception:
            pass
        result["idioma_canal"] = _infer_language(" ".join(language_chunks)[:50000]) or "Idioma desconhecido"

    except Exception as e:
        print(f"  [erro ao ler dados do canal {channel_url}]: {e}")

    return result


_RE_VIDEO_ID = re.compile(r"[?&]v=([\w-]{11})")
_RE_DURACAO = re.compile(r"^\d{1,2}(?::\d{2}){1,2}$")
_RE_META_VIEWS = re.compile(r"visualiza|\bviews?\b", re.I)
_RE_META_QUANDO = re.compile(r"\bh[áa]\s+\S+|\bago\b|estreia|premiere", re.I)

# Seletores dos cards na aba /videos do canal (layout novo + legados).
CARDS_CANAL_SEL = "ytd-rich-item-renderer, ytd-grid-video-renderer, ytd-rich-grid-media"
# Máximo de cards carregados ao procurar o 1º vídeo quando não há ordenação 'Mais antigos'.
LIMITE_LISTA_COMPLETA = 500


def _card_video_data(card):
    """Extrai os dados visíveis de um card de vídeo da página de um canal.

    Suporta o layout atual (``yt-lockup-view-model``: título em
    ``a.ytLockupMetadataViewModelTitle``, views/data em
    ``.ytContentMetadataViewModelMetadataText``, duração em
    ``.ytBadgeShapeText``) e o layout legado (``#video-title``,
    ``#metadata-line``). Views e data são identificadas pelo TEXTO
    ("… visualizações", "há 2 dias"), não pela posição, porque lives/estreias
    mudam a ordem e a quantidade dos campos.
    """
    link_el = card.query_selector(
        "a.ytLockupMetadataViewModelTitle, h3 a[href*='watch?v='], "
        "a#video-title-link, a#video-title, a.ytLockupViewModelContentImage, a#thumbnail"
    )
    href = (link_el.get_attribute("href") if link_el else "") or ""
    m = _RE_VIDEO_ID.search(href)
    if not m:
        return None
    vid = m.group(1)

    title = ""
    for sel in ("h3[title]", "#video-title", "a.ytLockupMetadataViewModelTitle", "h3"):
        el = card.query_selector(sel)
        if not el:
            continue
        txt = (el.get_attribute("title") or el.inner_text() or "").strip()
        if txt:
            title = txt
            break
    if not title and link_el:
        title = (link_el.get_attribute("title") or link_el.get_attribute("aria-label") or "").strip()

    meta_texts = []
    for sel in (".ytContentMetadataViewModelMetadataText", "#metadata-line span", "span.inline-metadata-item"):
        nodes = card.query_selector_all(sel)
        meta_texts = [(n.inner_text() or "").replace("\xa0", " ").strip() for n in nodes]
        meta_texts = [t for t in meta_texts if t]
        if meta_texts:
            break
    views_text = next((t for t in meta_texts if _RE_META_VIEWS.search(t)), "")
    when_text = next((t for t in meta_texts if _RE_META_QUANDO.search(t)), "")

    duration = ""
    for sel in (
        ".ytBadgeShapeText",
        "ytd-thumbnail-overlay-time-status-renderer span",
        "yt-thumbnail-overlay-time-status-renderer span",
        "badge-shape-wiz__text",
    ):
        try:
            for el in card.query_selector_all(sel):
                txt = (el.inner_text() or "").strip()
                if _RE_DURACAO.match(txt):
                    duration = txt
                    break
        except Exception:
            pass
        if duration:
            break

    data_aprox = _data_aproximada_de_texto(when_text)
    return {
        "video_id": vid,
        "titulo": title,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "views_text": views_text,
        "views_num": parse_count(views_text) if views_text else None,
        "quando": when_text,
        "data_aprox": data_aprox.isoformat() if data_aprox else "",
        "duracao": duration,
    }


# --------------------------------------------------------------------------
# Análise de frequência de postagem
# --------------------------------------------------------------------------

def classificar_frequencia(intervalo_medio_dias):
    """Traduz o intervalo médio entre vídeos em um rótulo legível."""
    if intervalo_medio_dias is None:
        return "dados insuficientes"
    d = intervalo_medio_dias
    if d <= 0.6:
        return "vários por dia"
    if d <= 1.2:
        return "todo dia"
    if d <= 2.0:
        return "quase todo dia"
    if d <= 3.5:
        return "2–3 por semana"
    if d <= 9:
        return "1 por semana"
    if d <= 17:
        return "a cada 2 semanas"
    if d <= 45:
        return "1 por mês"
    return "menos de 1 por mês"


def _data_do_video(v):
    """(date, exata). Prefere a data exata do watch page; senão a aproximada do card."""
    for chave, exata in (("data_publicacao", True), ("data_aprox", False), ("data", None)):
        iso = (v or {}).get(chave) or ""
        if not iso:
            continue
        try:
            d = datetime.strptime(str(iso)[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if exata is None:  # campo 'data' de vídeos já "públicos"
            exata = bool((v or {}).get("data_exata"))
        return d, exata
    return None, False


def _video_publico(v):
    """Formato enxuto e estável dos vídeos que vão para a interface e para a biblioteca."""
    d, exata = _data_do_video(v)
    return {
        "video_id": v.get("video_id", ""),
        "titulo": v.get("titulo", ""),
        "url": v.get("url", ""),
        "views_num": v.get("views_num"),
        "views_text": v.get("views_text", ""),
        "quando": v.get("quando", ""),
        "duracao": v.get("duracao", ""),
        "data": d.isoformat() if d else "",
        "data_exata": bool(d and exata),
    }


def analisar_frequencia(videos, agora=None, ultimo_data_iso="", primeiro_data_iso="", amostra_completa=False):
    """Estima a frequência de postagem a partir de uma amostra de vídeos recentes.

    Intervalo médio = (data do mais novo - data do mais antigo da amostra) / (n - 1).
    O mais novo usa a data exata (``ultimo_data_iso``) quando disponível; se a
    amostra cobre o canal inteiro, o mais antigo usa a data exata do primeiro
    vídeo. As demais datas vêm do texto relativo do card e são aproximadas.
    """
    hoje = (agora or datetime.now()).date()
    datas = sorted((d for d, _ in (_data_do_video(v) for v in (videos or [])) if d), reverse=True)
    out = {
        "frequencia_label": "dados insuficientes",
        "frequencia_intervalo_medio_dias": None,
        "frequencia_videos_por_semana": None,
        "frequencia_n_amostra": len(datas),
        "frequencia_periodo_dias": None,
        "frequencia_amostra_pequena": len(datas) < 8,
        "videos_ultimos_30d": sum(1 for d in datas if (hoje - d).days < 30),
        "dias_desde_ultimo_video": None,
        "frequencia_atividade": "",
    }
    if not datas:
        return out

    def _iso(v):
        try:
            return datetime.strptime(str(v)[:10], "%Y-%m-%d").date() if v else None
        except ValueError:
            return None

    novo = _iso(ultimo_data_iso) or datas[0]
    antigo = (_iso(primeiro_data_iso) if amostra_completa else None) or datas[-1]
    out["dias_desde_ultimo_video"] = max(0, (hoje - novo).days)

    if len(datas) >= 2:
        periodo = max(0, (novo - antigo).days)
        intervalo = periodo / (len(datas) - 1)
        out["frequencia_periodo_dias"] = periodo
        out["frequencia_intervalo_medio_dias"] = round(intervalo, 2)
        out["frequencia_videos_por_semana"] = round(7 / intervalo, 1) if intervalo > 0 else None
        out["frequencia_label"] = classificar_frequencia(intervalo)
        limite_parado = max(30, 3 * intervalo)
    else:
        limite_parado = 30
    out["frequencia_atividade"] = "parado" if out["dias_desde_ultimo_video"] > limite_parado else "ativo"
    return out


# --------------------------------------------------------------------------
# Aba "Vídeos" do canal: ordenação, coleta de cards
# --------------------------------------------------------------------------

_CHIP_PADROES = {
    "recentes": r"mais\s+recentes|latest|newest|m[aá]s\s+recientes",
    "antigos": r"mais\s+antigos|oldest|m[aá]s\s+antiguos",
    "populares": r"populares?|popular",
}
_ORDENACAO_URL = {"antigos": "sort=da", "populares": "sort=p"}

_JS_CLICAR_CHIP = """(pattern) => {
  const re = new RegExp(pattern, 'i');
  const visivel = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const candidatos = Array.from(document.querySelectorAll(
    'button, [role="tab"], [role="radio"], yt-chip-cloud-chip-renderer, chip-shape'));
  const alvo = candidatos.find((el) => {
    if (!visivel(el)) return false;
    if (el.closest('ytd-rich-item-renderer, yt-lockup-view-model, ytd-video-renderer')) return false;
    const txt = ((el.getAttribute('aria-label') || '') + ' ' + (el.textContent || '')).trim();
    return txt.length > 0 && txt.length < 40 && re.test(txt);
  });
  if (!alvo) return false;
  alvo.click();
  return true;
}"""


def _clicar_chip_ordenacao(page, ordem: str) -> bool:
    try:
        return bool(page.evaluate(_JS_CLICAR_CHIP, _CHIP_PADROES[ordem]))
    except Exception:
        return False


def _primeiro_id_card(page):
    try:
        for card in page.query_selector_all(CARDS_CANAL_SEL)[:1]:
            d = _card_video_data(card)
            return d["video_id"] if d else None
    except Exception:
        pass
    return None


def _abrir_videos_canal(page, channel_url: str, ordem: str = "recentes") -> bool:
    """Abre a aba Vídeos do canal na ordem pedida ('recentes', 'antigos', 'populares').

    Tenta o chip de ordenação da página; se não existir, tenta o parâmetro de
    URL. Retorna True se a ordem pedida foi aplicada (verificado pela troca do
    primeiro card) ou se é a ordem padrão. Retorna False caso contrário — quem
    chama decide o fallback.
    """
    base = channel_url.rstrip("/") + "/videos"
    page.goto(base, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
    page.wait_for_timeout(1800)
    try:
        page.locator(CARDS_CANAL_SEL).first.wait_for(state="attached", timeout=6000)
    except Exception:
        pass
    if ordem == "recentes":
        return True

    antes = _primeiro_id_card(page)

    def _esperar_troca():
        for _ in range(12):
            page.wait_for_timeout(500)
            if _primeiro_id_card(page) != antes:
                return True
        return False

    if _clicar_chip_ordenacao(page, ordem) and _esperar_troca():
        return True
    if ordem in _ORDENACAO_URL:
        try:
            page.goto(f"{base}?view=0&{_ORDENACAO_URL[ordem]}&flow=grid", timeout=NAV_TIMEOUT,
                      wait_until="domcontentloaded")
            page.wait_for_timeout(1800)
            if _esperar_troca():
                return True
        except Exception:
            pass
    return False


def _coletar_cards_canal(page, limite: int, max_rodadas: int = 40):
    """Rola a aba Vídeos coletando cards, na ordem em que aparecem, sem repetir.

    Retorna ``(videos, chegou_ao_fim)``. ``chegou_ao_fim`` é True quando a lista
    parou de crescer antes de atingir ``limite`` — ou seja, o canal não tem mais
    vídeos do que o coletado.
    """
    vistos, videos = set(), []
    parado = 0
    for _ in range(max_rodadas):
        antes = len(videos)
        for card in page.query_selector_all(CARDS_CANAL_SEL):
            d = _card_video_data(card)
            if not d or d["video_id"] in vistos:
                continue
            vistos.add(d["video_id"])
            videos.append(d)
            if len(videos) >= limite:
                return videos, False
        parado = parado + 1 if len(videos) == antes else 0
        if parado >= 3:
            return videos, True
        page.mouse.wheel(0, 5000)
        page.wait_for_timeout(900)
    return videos, False


# --------------------------------------------------------------------------
# Leitura do canal: primeiros 5, mais recentes + frequência, populares
# --------------------------------------------------------------------------

def scrape_first_video(page, channel_url: str, n_primeiros: int = 5):
    """Lê os ``n_primeiros`` vídeos MAIS ANTIGOS do canal (o primeiro deles com data exata).

    Mantém os campos ``primeiro_video_*`` (o vídeo mais antigo) e acrescenta
    ``primeiros_5_videos``. ``primeiro_video_confiavel`` é False quando não foi
    possível garantir que o vídeo lido é mesmo o primeiro (ordenação por "Mais
    antigos" indisponível e lista não carregada até o fim): nesse caso a idade
    do canal é tratada como desconhecida, nunca como recente.
    """
    result = {
        "primeiro_video_titulo": "",
        "primeiro_video_quando": "",
        "primeiro_video_data_publicacao": "",
        "primeiro_video_url": "",
        "primeiro_video_views_text": "",
        "primeiro_video_views_num": None,
        "primeiro_video_duracao": "",
        "primeiro_video_confiavel": False,
        "primeiros_5_videos": [],
    }
    try:
        print(f"    Abrindo vídeos mais antigos: {channel_url.rstrip('/')}/videos")
        if _abrir_videos_canal(page, channel_url, "antigos"):
            print("    Ordenação 'Mais antigos' aplicada.")
            cards, _ = _coletar_cards_canal(page, n_primeiros)
            primeiros, confiavel = cards[:n_primeiros], bool(cards)
        else:
            print("    Ordenação 'Mais antigos' indisponível — carregando a lista inteira...")
            cards, fim = _coletar_cards_canal(page, LIMITE_LISTA_COMPLETA)
            primeiros, confiavel = list(reversed(cards))[:n_primeiros], bool(cards) and fim
            if not confiavel:
                print("    AVISO: lista não carregada até o fim — idade do canal marcada como incerta.")
        if not primeiros:
            return result

        first = _enriquecer_video_com_watch_info(page, dict(primeiros[0]))
        primeiros[0] = first
        result.update({
            "primeiro_video_titulo": first["titulo"],
            "primeiro_video_quando": first.get("quando", ""),
            "primeiro_video_data_publicacao": first.get("data_publicacao", ""),
            "primeiro_video_url": first["url"],
            "primeiro_video_views_text": first["views_text"],
            "primeiro_video_views_num": first["views_num"],
            "primeiro_video_duracao": first["duracao"],
            "primeiro_video_confiavel": confiavel,
            "primeiros_5_videos": [_video_publico(v) for v in primeiros],
        })
    except Exception as e:
        print(f"  [erro ao ler vídeos do canal {channel_url}]: {e}")
    return result


def scrape_recent_videos(page, channel_url: str, n: int = 50, primeiro_data_iso: str = "", total_videos=None):
    """Lê os ``n`` vídeos mais recentes: separa os 3 últimos, guarda a amostra e
    calcula a frequência de postagem. A data do último vídeo é a exata."""
    result = {
        "ultimos_3_videos": [],
        "amostra_videos": [],
        "amostra_completa": False,
        "ultimo_video_titulo": "",
        "ultimo_video_url": "",
        "ultimo_video_data_publicacao": "",
        "ultimo_video_quando": "",
        "ultimo_video_views_text": "",
    }
    result.update(analisar_frequencia([]))
    try:
        print(f"    Lendo os últimos {n} vídeos: {channel_url.rstrip('/')}/videos")
        _abrir_videos_canal(page, channel_url, "recentes")
        cards, fim = _coletar_cards_canal(page, n)
        if not cards:
            return result
        completa = fim or (total_videos is not None and len(cards) >= total_videos)

        ultimo = _enriquecer_video_com_watch_info(page, dict(cards[0]))
        cards[0] = ultimo
        result.update({
            "amostra_completa": bool(completa),
            "ultimo_video_titulo": ultimo["titulo"],
            "ultimo_video_url": ultimo["url"],
            "ultimo_video_data_publicacao": ultimo.get("data_publicacao", ""),
            "ultimo_video_quando": ultimo.get("quando", ""),
            "ultimo_video_views_text": ultimo["views_text"],
            "ultimos_3_videos": [_video_publico(v) for v in cards[:3]],
            "amostra_videos": [_video_publico(v) for v in cards],
        })
        freq = analisar_frequencia(
            cards, ultimo_data_iso=ultimo.get("data_publicacao", ""),
            primeiro_data_iso=primeiro_data_iso, amostra_completa=bool(completa),
        )
        result.update(freq)
        print(f"    Frequência: {freq['frequencia_label']} "
              f"({freq['frequencia_n_amostra']} vídeos, {freq['videos_ultimos_30d']} nos últimos 30 dias)")
    except Exception as e:
        print(f"    [erro ao ler vídeos recentes de {channel_url}]: {e}")
    return result


def _top_por_views(videos, top_n):
    validos = [v for v in videos if v.get("video_id")]
    validos.sort(key=lambda v: (v.get("views_num") is not None, v.get("views_num") or -1), reverse=True)
    return validos[:top_n]


def scrape_top_popular_videos(page, channel_url: str, top_n: int = 3, amostra=None):
    """Vídeos mais populares do canal (chip "Populares"). Se a ordenação não puder
    ser aplicada, escolhe entre os vídeos já carregados (``amostra``) pelo número de views.
    Views e datas vêm do card (arredondadas), sem abrir cada vídeo."""
    try:
        print(f"    Buscando TOP {top_n} populares...")
        aplicou = _abrir_videos_canal(page, channel_url, "populares")
        cards, _ = _coletar_cards_canal(page, max(12, top_n * 4), max_rodadas=6)
        candidatos = [_video_publico(c) for c in cards]
        if not aplicou:
            print("    AVISO: ordenação 'Populares' indisponível — usando só os vídeos já carregados.")
            candidatos += list(amostra or [])
        vistos, unicos = set(), []
        for v in candidatos:
            if v["video_id"] not in vistos:
                vistos.add(v["video_id"])
                unicos.append(v)
        return _top_por_views(unicos, top_n)
    except Exception as e:
        print(f"    [erro ao ler populares de {channel_url}]: {e}")
        return _top_por_views(list(amostra or []), top_n)


def _meses_primeiro_video(ch: dict, agora=None):
    """Meses desde o primeiro vídeo; None se desconhecido OU não confiável."""
    if ch.get("primeiro_video_confiavel") is False:
        return None
    meses = _meses_desde_data(ch.get("primeiro_video_data_publicacao", ""), agora)
    if meses is None:
        meses = _meses_desde_texto(ch.get("primeiro_video_quando", ""))
    return meses


def enrich_channel_details(page, channel_url: str, janela_meses=None, descartar_fora_janela=False,
                           n_frequencia: int = 50, total_videos=None):
    """Une: 5 vídeos mais antigos + últimos vídeos/frequência + 3 mais populares.

    Se ``janela_meses`` e ``descartar_fora_janela`` estiverem definidos e o
    primeiro vídeo for mais antigo que a janela, a análise detalhada é pulada
    (economiza ~4 navegações por canal). Idade desconhecida nunca descarta.
    """
    result = {}
    result.update(scrape_first_video(page, channel_url))
    meses = _meses_primeiro_video(result)
    result["ultimos_3_videos"] = []
    result["top_3_populares"] = []

    if janela_meses and meses is not None and meses > janela_meses and descartar_fora_janela:
        print(f"    Primeiro vídeo há {meses:.1f} meses (janela: {janela_meses:g}) — fora da janela, análise detalhada pulada.")
        return result

    rec = scrape_recent_videos(
        page, channel_url, n=n_frequencia,
        primeiro_data_iso=result.get("primeiro_video_data_publicacao", ""),
        total_videos=total_videos,
    )
    result.update(rec)
    amostra = rec.get("amostra_videos") or []
    if rec.get("amostra_completa") and amostra:
        # A amostra já é o canal inteiro: o TOP 3 é exato sem outra navegação.
        result["top_3_populares"] = _top_por_views(amostra, 3)
    else:
        result["top_3_populares"] = scrape_top_popular_videos(page, channel_url, top_n=3, amostra=amostra)
    return result


# (padrão da unidade, dias por unidade, deslocamento até o ponto médio da faixa).
# O YouTube arredonda para baixo: "há 2 meses" significa de 60 a 89 dias. Usar o
# ponto médio evita que a frequência de postagem saia sistematicamente viesada.
_UNIDADES_REL = [
    (r"segundos?|seconds?", 0.0, 0.0),
    (r"minutos?|minutes?", 0.0, 0.0),
    (r"horas?|hours?", 0.0, 0.0),
    (r"dias?|days?", 1.0, 0.0),
    (r"semanas?|weeks?", 7.0, 3.0),
    (r"m[eê]s(?:es)?|months?", 30.4375, 15.0),
    (r"anos?|years?", 365.25, 182.0),
]


def _data_aproximada_de_texto(texto: str, agora=None):
    """Converte 'há 3 semanas' / '2 months ago' / 'Transmitido há 1 dia' em uma
    data aproximada (date), no ponto médio da faixa. O YouTube só informa a
    unidade mais grossa, então o erro é de até meia unidade (ex.: ±15 dias para
    'há 1 mês'). Por isso a interface mostra o texto relativo, não essa data.
    Retorna None se o texto não for uma data relativa reconhecível."""
    if not texto:
        return None
    t = str(texto).lower().replace("\xa0", " ")
    if not re.search(r"\bh[áa]\b|\bago\b", t):
        return None
    m = re.search(r"(\d+|um|uma|an?)\s+([a-zê]+)", t.split("há", 1)[-1] if "há" in t else t)
    if not m:
        return None
    qtd_txt, unidade = m.groups()
    qtd = int(qtd_txt) if qtd_txt.isdigit() else 1
    dias = None
    for padrao, fator, meio in _UNIDADES_REL:
        if re.fullmatch(padrao, unidade):
            dias = round(qtd * fator + meio)
            break
    if dias is None:
        return None
    hoje = (agora or datetime.now()).date()
    return hoje - timedelta(days=dias)


def _meses_desde_data(data_iso: str, agora=None):
    """Calcula meses aproximados desde uma data ISO confirmada."""
    if not data_iso:
        return None
    try:
        d = datetime.strptime(str(data_iso)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    hoje = (agora or datetime.now()).date()
    dias = max(0, (hoje - d).days)
    return dias / 30.4375


def _meses_desde_texto(texto: str):
    """
    Converte um texto relativo do YouTube tipo 'há 3 meses', 'há 1 ano',
    '2 years ago' em número aproximado de meses. Retorna None se não
    conseguir interpretar (aí tratamos como 'desconhecido', não como recente).
    """
    if not texto:
        return None
    t = texto.lower()
    m = re.search(r"(\d+)\s*(dia|day)", t)
    if m:
        return int(m.group(1)) / 30
    m = re.search(r"(\d+)\s*(semana|week)", t)
    if m:
        return int(m.group(1)) / 4.345
    m = re.search(r"(\d+)\s*(m[eê]s|mes|month)", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)\s*(ano|year)", t)
    if m:
        return float(m.group(1)) * 12
    if re.search(r"\bum\b|\ban?\b", t):
        return 12  # "há um ano" / "a year ago" sem número
    return None


def _norm_key(value: str) -> str:
    """Normaliza chaves de agrupamento/termos sem alterar o texto exibido."""
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _ensure_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value).strip()
    return [text] if text else []


def merge_channel_records(records: list) -> list:
    """Mescla o mesmo canal encontrado em vários termos/subnichos.

    O ranking geral usa uma única entrada por canal, mas preserva todas as
    associações de nicho/subnicho/termos para que os rankings segmentados não
    percam canais encontrados em mais de uma busca.
    """
    merged = {}
    for src in records or []:
        curl = (src.get("canal_url") or "").strip()
        if not curl:
            continue
        if curl not in merged:
            item = dict(src)
            item["nichos"] = _ensure_list(src.get("nichos")) or _ensure_list(src.get("nicho"))
            item["subnichos"] = _ensure_list(src.get("subnichos")) or _ensure_list(src.get("subnicho"))
            item["termos_busca"] = _ensure_list(src.get("termos_busca")) or _ensure_list(src.get("termo_busca"))
            merged[curl] = item
            continue

        item = merged[curl]
        for field, singular in (("nichos", "nicho"), ("subnichos", "subnicho"), ("termos_busca", "termo_busca")):
            current = list(item.get(field) or [])
            for val in _ensure_list(src.get(field)) + _ensure_list(src.get(singular)):
                if _norm_key(val) not in {_norm_key(x) for x in current}:
                    current.append(val)
            item[field] = current

        # Mantém no objeto geral a versão com maior score.
        if (src.get("score") or 0) > (item.get("score") or 0):
            keep_lists = {k: item.get(k, []) for k in ("nichos", "subnichos", "termos_busca")}
            item.update(src)
            for k, vals in keep_lists.items():
                item[k] = vals

    for item in merged.values():
        item["nicho"] = (item.get("nichos") or [item.get("nicho") or "Sem nicho"])[0]
        item["subnicho"] = (item.get("subnichos") or [item.get("subnicho") or "Sem subnicho"])[0]
        item["termo_busca"] = (item.get("termos_busca") or [item.get("termo_busca") or ""])[0]
    return list(merged.values())


def build_group_rankings(records: list, field: str, empty_label: str) -> dict:
    """Cria ranking por nicho/subnicho/país/idioma sem perder associações múltiplas."""
    groups = {}
    for item in records or []:
        if field == "nicho":
            values = item.get("nichos") or _ensure_list(item.get("nicho"))
        elif field == "subnicho":
            values = item.get("subnichos") or _ensure_list(item.get("subnicho"))
        else:
            values = _ensure_list(item.get(field))
        if not values:
            values = [empty_label]

        seen = set()
        for value in values:
            label = str(value).strip() or empty_label
            key = _norm_key(label) or _norm_key(empty_label)
            if key in seen:
                continue
            seen.add(key)
            groups.setdefault(label, []).append(item)

    result = {}
    for label, members in groups.items():
        # O mesmo canal deve aparecer uma vez dentro de cada grupo.
        unique = merge_channel_records(members)
        unique.sort(key=lambda c: (c.get("score") or 0), reverse=True)
        for idx, c in enumerate(unique, 1):
            c = dict(c)
            c["rank_grupo"] = idx
            c["grupo"] = label
            result.setdefault(label, []).append(c)
    return dict(sorted(result.items(), key=lambda kv: ((kv[1][0].get("score") if kv[1] else 0), kv[0]), reverse=True))


def build_group_summaries(groups: dict, label_key: str) -> list:
    """Resume grupos e ordena pelo potencial dos canais encontrados.

    A ideia de "nicho mais promissor" usa a mesma regra do ranking dos canais:
    mais inscritos, menos vídeos e maior recência do primeiro vídeo.
    Para não deixar um único outlier dominar totalmente o grupo, o índice do
    grupo combina o melhor canal e os três melhores scores do grupo.

    Canais marcados ``fora_da_janela`` (primeiro vídeo mais antigo que a idade
    máxima escolhida) NÃO entram no índice: um canal antigo e grande não pode
    fazer um nicho parecer promissor para quem procura canais que começaram
    há pouco. Um grupo só com canais fora da janela fica sem índice (continua
    listado, no fim).
    """
    summaries = []
    for label, members in (groups or {}).items():
        elegiveis = [m for m in (members or []) if not m.get("fora_da_janela")]
        if not elegiveis:
            continue
        members = elegiveis
        members_sorted = sorted(members, key=lambda m: (m.get("score") or 0), reverse=True)
        scores = [float(m.get("score") or 0) for m in members_sorted]
        top3 = scores[:3]
        if not top3:
            continue
        melhor = top3[0]
        media_top3 = sum(top3) / len(top3)
        media_todos = sum(scores) / len(scores)
        # Peso maior no melhor canal, mas exige recorrência de bons candidatos.
        score_oportunidade = (0.50 * melhor) + (0.35 * media_top3) + (0.15 * media_todos)
        top_canais = []
        for m in members_sorted[:3]:
            top_canais.append({
                "canal": m.get("canal", ""),
                "canal_url": m.get("canal_url", ""),
                "score": round(float(m.get("score") or 0), 2),
                "inscritos_num": m.get("inscritos_num"),
                "n_videos": m.get("n_videos"),
                "dados_incompletos": bool(m.get("dados_incompletos")),
            })
        summaries.append({
            label_key: label,
            "candidatos": len(members_sorted),
            "melhor_score": round(melhor, 2),
            "media_top3_score": round(media_top3, 2),
            "media_score": round(media_todos, 2),
            "score_oportunidade": round(score_oportunidade, 2),
            "melhor_canal": members_sorted[0].get("canal", ""),
            "melhor_canal_url": members_sorted[0].get("canal_url", ""),
            "top_canais": top_canais,
        })
    summaries.sort(
        key=lambda x: (x["score_oportunidade"], x["melhor_score"], x["candidatos"]),
        reverse=True,
    )
    for idx, row in enumerate(summaries, 1):
        row["rank"] = idx
    return summaries


def reorder_group_rankings(groups: dict, summaries: list, label_key: str) -> dict:
    """Reordena o dicionário de grupos conforme o ranking de oportunidade."""
    if not groups:
        return {}
    ordered = {}
    seen = set()
    for row in summaries or []:
        label = str(row.get(label_key) or "").strip()
        if label in groups:
            ordered[label] = groups[label]
            seen.add(label)
    for label, members in groups.items():
        if label not in seen:
            ordered[label] = members
    return ordered


def rank_channels(unverified_channels: list, min_subs=0, max_videos=100, max_meses_primeiro_video=24,
                  apply_filters=True, janela_meses=None):
    """Calcula o ranking sem transformar preferências em cortes indevidos.

    Regra do projeto: maximizar inscritos, minimizar quantidade de vídeos e
    favorecer canais cujo primeiro vídeo é recente.

    ``max_videos`` representa quantos resultados são coletados por termo no
    YouTube; ele NÃO é um limite de quantidade total de vídeos do canal.
    Portanto, a quantidade de vídeos do canal entra no score, mas não elimina
    o candidato. A idade do canal também é preferência, não exclusão.

    O único corte rígido mantido aqui é ``min_subs`` quando o número de
    inscritos foi confirmado e o usuário definiu um valor > 0.
    Dados desconhecidos permanecem no ranking com penalização conservadora.

    ``janela_meses`` é a idade máxima desejada do canal (meses desde o primeiro
    vídeo). Ela define a escala do bônus de recência e marca cada canal com
    ``fora_da_janela`` (True/False). Quem exclui ou mostra à parte os canais
    fora da janela é o chamador. Idade desconhecida NUNCA marca fora da janela.
    """
    janela = float(janela_meses) if janela_meses else None
    escala_recencia = janela or max_meses_primeiro_video
    ranked = []
    for original in unverified_channels:
        ch = dict(original)
        subs_raw = ch.get("inscritos_num")
        nvid_raw = ch.get("n_videos")
        subs = subs_raw if isinstance(subs_raw, (int, float)) else None
        nvid = nvid_raw if isinstance(nvid_raw, (int, float)) and nvid_raw >= 0 else None
        meses = _meses_primeiro_video(ch)

        if apply_filters and min_subs > 0 and subs is not None and subs < min_subs:
            ch["status_ranking"] = "abaixo_min_subs"
            continue

        dados_incompletos = []
        if subs is None:
            dados_incompletos.append("inscritos")
        if nvid is None:
            dados_incompletos.append("numero_de_videos")
        if meses is None:
            dados_incompletos.append("idade_do_canal")

        # Mais inscritos = melhor.
        subs_score = float(subs or 0)

        # Menos vídeos = melhor. Se não houver a contagem, usamos uma referência
        # conservadora para evitar premiar dados ausentes.
        divisor = float((nvid + 1) if nvid is not None else (max(25, min(max_videos, 100)) + 1))
        score = subs_score / divisor

        # Mais recente = maior fator. Não há corte de idade: um canal antigo
        # continua visível, apenas perde o bônus de recência.
        if meses is not None and escala_recencia:
            recencia_fator = min(2.0, max(0.5, 2.0 - (meses / escala_recencia)))
            score *= recencia_fator
            ch["fator_recencia"] = round(recencia_fator, 3)
        else:
            ch["fator_recencia"] = None

        # Dados incompletos continuam visíveis, mas não podem ganhar de um
        # candidato equivalente que tenha os três indicadores confirmados.
        if dados_incompletos:
            score *= 0.35

        ch["meses_desde_primeiro_video"] = round(meses, 1) if meses is not None else None
        ch["idade_desconhecida"] = meses is None
        ch["fora_da_janela"] = bool(janela and meses is not None and meses > janela)
        ch["inscritos_por_mes"] = (
            round(subs / max(meses, 0.25)) if (subs is not None and meses is not None) else None
        )
        ch["score"] = round(score, 2)
        ch["top_3_populares_count"] = len(ch.get("top_3_populares") or [])
        ch["inscritos_por_video"] = round(subs / nvid, 2) if (subs is not None and nvid is not None and nvid > 0) else None
        ch["regra_resumo"] = "máximo de inscritos + mínimo de vídeos + maior recência"
        ch["dados_incompletos"] = dados_incompletos
        ch["dados_incompletos_texto"] = ", ".join(dados_incompletos) if dados_incompletos else ""
        ch["status_ranking"] = "ranqueado"
        ranked.append(ch)

    ranked.sort(key=lambda c: (c.get("score") or 0, c.get("inscritos_num") or 0), reverse=True)
    return ranked

def montar_prompt_subnichos(nicho: str, n_subnichos=5, n_termos=5) -> str:
    """
    Monta o texto do prompt pra colar em QUALQUER chat de IA (ChatGPT, Gemini,
    Claude web, etc.) — não depende de API key. A IA deve devolver um JSON
    que o app consegue colar de volta na interface.
    """
    return (
        f"Liste {n_subnichos} subnichos específicos e pouco saturados dentro do "
        f"nicho \"{nicho}\" para canais do YouTube. Para cada subnicho, dê "
        f"{n_termos} termos de busca em inglês para pesquisar no YouTube. "
        f"Responda ESTRITAMENTE em JSON válido, sem markdown, sem texto antes "
        f"ou depois, exatamente neste formato:\n\n"
        f'{{"subnichos": [{{"nome": "nome do subnicho", "termos": '
        f'["termo 1", "termo 2"]}}]}}'
    )


def gerar_subnichos_e_termos(nicho: str, n_subnichos=5, n_termos=5):
    """
    Usa a API da Anthropic (se ANTHROPIC_API_KEY estiver definida no ambiente)
    para replicar a etapa de "mineração com IA" do vídeo: a partir de um
    nicho amplo, gera subnichos e, pra cada subnicho, termos de busca em
    inglês pra usar no YouTube.

    Se não houver chave de API configurada ou o pacote `anthropic` não
    estiver instalado, retorna None e o script segue no modo manual
    (você passa os termos direto via --termos / --termos-file).
    """
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("(ANTHROPIC_API_KEY não definida — pulando geração automática de "
              "subnichos. Use --termos ou --termos-file pra passar os termos manualmente.)")
        return None
    try:
        import anthropic
    except ImportError:
        print("(pacote 'anthropic' não instalado — rode "
              "`pip install anthropic --break-system-packages` pra usar a geração automática.)")
        return None

    client = anthropic.Anthropic(api_key=api_key)
    prompt = (
        f"Liste {n_subnichos} subnichos específicos e pouco saturados dentro do "
        f"nicho '{nicho}' para canais do YouTube. Para cada subnicho, dê "
        f"{n_termos} termos de busca em inglês para pesquisar no YouTube. "
        f"Responda ESTRITAMENTE em JSON, sem markdown, no formato: "
        f'{{"subnichos": [{{"nome": "...", "termos": ["...", "..."]}}]}}'
    )
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        text = text.strip().strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
        import json
        data = json.loads(text)
        return data.get("subnichos", [])
    except Exception as e:
        print(f"(falha ao gerar subnichos via IA: {e}. Seguindo no modo manual.)")
        return None


def checar_google_trends(termos: list):
    """
    Consulta o interesse relativo de cada termo no Google Trends (filtrado
    pra busca do YouTube), replicando a etapa final do vídeo. Requer
    `pip install pytrends --break-system-packages`. Se não estiver
    instalado, apenas avisa e segue sem essa etapa (não é crítica pro
    ranking final).
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("(pacote 'pytrends' não instalado — pulando checagem de Google Trends. "
              "Rode `pip install pytrends --break-system-packages` pra habilitar.)")
        return {}

    resultado = {}
    try:
        pytrends = TrendReq(hl="pt-BR")
        # gprop='youtube' filtra pra pesquisa dentro do YouTube, como no vídeo
        for i in range(0, len(termos), 5):  # a API aceita até 5 termos por consulta
            lote = termos[i:i + 5]
            pytrends.build_payload(lote, timeframe="today 3-m", gprop="youtube")
            df = pytrends.interest_over_time()
            if df is not None and not df.empty:
                for termo in lote:
                    if termo in df.columns:
                        resultado[termo] = round(df[termo].mean(), 1)
            time.sleep(1)
    except Exception as e:
        print(f"(erro ao consultar Google Trends: {e})")

    return resultado


def analisar_canais_nao_verificados(page, videos: list, termo: str, subnicho: str, nicho: str,
                                    min_subs: int, max_videos: int, analise=None, cache_canais=None):
    """Etapa "vídeos -> canais não verificados -> análise -> ranking", independente da fonte dos vídeos.

    Usada pela busca por termo (``processar_termo``) e pela mineração de recomendações.
    Cada vídeo pode trazer seu próprio ``termo_busca``/``subnicho``/``nicho``; o que faltar
    cai nos argumentos. ``cache_canais`` evita reler um canal já analisado no mesmo job."""
    analise = _normalizar_analise(analise)
    cache_canais = cache_canais if cache_canais is not None else {}
    unverified_map = {}
    for v in videos:
        if v["canal_url"] and not v["canal_verificado"]:
            unverified_map.setdefault(v["canal_url"], {
                "canal": v["canal"],
                "canal_url": v["canal_url"],
                "termo_busca": v.get("termo_busca") or termo,
                "subnicho": v.get("subnicho") or subnicho,
                "nicho": v.get("nicho") or nicho,
                "video_exemplo": v["url"],
                "views_video_exemplo": v["views_num"],
                "pais_canal": "",
                "idioma_canal": "",
            })

    print(f"{len(unverified_map)} canais não verificados únicos neste termo. Visitando...")

    enriched = []
    for i, (curl, data) in enumerate(unverified_map.items(), 1):
        print(f"  [{i}/{len(unverified_map)}] {data['canal']}")
        if curl in cache_canais:
            print("    (já analisado em outro termo — reaproveitando)")
            data.update(cache_canais[curl])
            enriched.append(data)
            continue
        data.update(scrape_channel_about(page, curl))
        # Não descarte dados só porque o canal ficou abaixo do corte de inscritos.
        # O corte é aplicado somente no ranking; assim o site continua mostrando
        # candidatos e os dados disponíveis para diagnóstico.
        data.update(enrich_channel_details(
            page, curl,
            janela_meses=analise["janela_meses"],
            descartar_fora_janela=analise["descartar_fora_janela"],
            n_frequencia=analise["n_frequencia"],
            total_videos=data.get("n_videos"),
        ))
        cache_canais[curl] = {k: v for k, v in data.items()
                              if k not in ("termo_busca", "subnicho", "nicho", "canal", "canal_url",
                                           "video_exemplo", "views_video_exemplo")}
        enriched.append(data)
        time.sleep(0.7)

    ranked = rank_channels(enriched, min_subs=min_subs, max_videos=max_videos,
                           janela_meses=analise["janela_meses"])
    return ranked


def processar_termo(page, termo: str, max_videos: int, min_subs: int,
                    subnicho: str = "", nicho: str = "", filtros=None,
                    analise=None, cache_canais=None, recomendados_auto=None):
    """Roda o fluxo completo (busca -> filtros -> coleta -> canais -> ranking) pra um termo.

    ``cache_canais`` (dict) evita reler, no mesmo job, um canal já analisado em
    outro termo — cada canal custa várias navegações.

    ``recomendados_auto``, se preenchido, liga a coleta automática da lateral de recomendados:
    para cada vídeo validado (a página já está aberta nele por causa da checagem de data/
    patrocínio, então a lateral é lida sem navegação extra), os recomendados são lidos e, ao
    final, passam pela mesma triagem por média/mediana da mineração manual (``recomendados.py``).
    Os aprovados viram candidatos a mais, entrando na mesma análise de canais deste termo."""
    filtros = _normalizar_filtros(filtros)
    analise = _normalizar_analise(analise)
    cache_canais = cache_canais if cache_canais is not None else {}
    rec_cfg = None
    itens_lateral = []
    if recomendados_auto:
        import recomendados  # import tardio: recomendados.py importa este módulo (evitaria ciclo no topo)
        rec_cfg = recomendados.normalizar_cfg(recomendados_auto)
    url = build_search_url(termo)
    print(f"\n{'='*70}\nTERMO: {termo}\n{'='*70}")
    print(f"Abrindo: {url}")
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    for txt in ["Aceitar tudo", "Accept all", "I agree", "Aceito"]:
        try:
            page.get_by_text(txt, exact=True).first.click(timeout=1500)
            break
        except Exception:
            pass

    apply_filters(page, filtros)
    videos = collect_videos(page, max_videos)

    # Mesmo quando existe opção nativa equivalente, esta checagem garante
    # que intervalos personalizados definidos na interface sejam respeitados.
    videos = _filtrar_por_duracao(videos, filtros)

    # O filtro do YouTube pode falhar e misturar vídeos fora do período.
    # Validação final: data real selecionada na interface + conteúdo patrocinado.
    agora = datetime.now()
    videos_validados = []
    print(f"Validando data real e patrocínio de {len(videos)} vídeos...")
    for idx, v in enumerate(videos, 1):
        ok, motivo = validar_video_no_periodo(page, v, filtros["data_periodo"], agora=agora)
        if not ok:
            if motivo == "patrocinado":
                print(f"  [{idx}/{len(videos)}] IGNORADO — patrocinado: {v['titulo'][:80]}")
            elif motivo.startswith("fora_do_periodo"):
                print(f"  [{idx}/{len(videos)}] IGNORADO — data incorreta ({motivo.split(':',1)[1]}): {v['titulo'][:80]}")
            else:
                print(f"  [{idx}/{len(videos)}] IGNORADO — não foi possível validar ({motivo}): {v['titulo'][:80]}")
            continue
        v["termo_busca"] = termo
        v["subnicho"] = subnicho
        v["nicho"] = nicho
        videos_validados.append(v)
        print(f"  [{idx}/{len(videos)}] OK — {v['data_publicacao']} — {v['titulo'][:80]}")
        if rec_cfg:
            try:
                _, brutos = recomendados._ler_lateral_atual(page, rec_cfg["max_itens"], log=print)
                itens_lateral.extend(recomendados.normalizar_item(b, v["video_id"], v["url"], v["titulo"]) for b in brutos)
                print(f"    + lateral: {len(brutos)} recomendados lidos.")
            except Exception as exc:
                print(f"    lateral não lida: {type(exc).__name__}: {exc}")

    videos = videos_validados
    print(f"Após validação: {len(videos)} vídeos válidos no período.")

    if rec_cfg and itens_lateral:
        videos_lateral, _ = recomendados.processar_lateral_inline(page, itens_lateral, rec_cfg, nicho, termo, log=print)
        if videos_lateral:
            print(f"{len(videos_lateral)} vídeos a mais vindos da lateral (aprovados na triagem).")
            videos = videos + videos_lateral

    ranked = analisar_canais_nao_verificados(
        page, videos, termo, subnicho, nicho, min_subs, max_videos, analise, cache_canais)
    return videos, ranked


def save_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"Salvo: {path} ({len(rows)} linhas)")


def main():
    ap = argparse.ArgumentParser(description="Automação de mineração de nicho no YouTube")
    ap.add_argument("--nicho", help='Nicho amplo pra gerar subnichos+termos via IA, '
                                     'ex: "crime". Requer ANTHROPIC_API_KEY no ambiente.')
    ap.add_argument("--termos", help='Termos de busca separados por vírgula, '
                                      'ex: "serial killer documentary,unsolved murder case"')
    ap.add_argument("--termos-file", help="Arquivo .txt com um termo de busca por linha")
    ap.add_argument("--max-videos", type=int, default=100)
    ap.add_argument("--min-subs", type=int, default=0, help="Inscritos mínimos; 0 = sem corte")
    ap.add_argument("--duracao-min", type=int, default=3, help="Duração mínima em minutos")
    ap.add_argument("--duracao-max", type=int, default=20, help="Duração máxima em minutos; 0 = sem limite")
    ap.add_argument("--data-periodo", choices=["hoje", "semana", "mes", "ano", "todos"], default="mes")
    ap.add_argument("--ordenacao", choices=["popularidade", "relevancia"], default="popularidade")
    ap.add_argument("--janela-meses", type=float, default=3,
                     help="Idade máxima do canal (meses desde o 1º vídeo); 0 = sem limite (padrão: 3)")
    ap.add_argument("--manter-fora-da-janela", action="store_true",
                     help="Não descartar canais mais antigos que a janela (analisa todos)")
    ap.add_argument("--n-frequencia", type=int, default=50,
                     help="Quantos vídeos recentes analisar para a frequência de postagem (padrão: 50)")
    ap.add_argument("--mute-audio", action="store_true", help="Mutar o áudio do Chromium")
    ap.add_argument("--trends", action="store_true",
                     help="Checar Google Trends pra cada termo (requer pytrends)")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    termos = []
    termo_para_subnicho = {}
    if args.nicho:
        subnichos = gerar_subnichos_e_termos(args.nicho)
        if subnichos:
            print("\nSubnichos sugeridos pela IA:")
            for s in subnichos:
                print(f"  - {s['nome']}: {s['termos']}")
                for t in s["termos"]:
                    termo_para_subnicho[t] = s["nome"]
                termos.extend(s["termos"])
    if args.termos:
        termos.extend([t.strip() for t in args.termos.split(",") if t.strip()])
    if args.termos_file:
        with open(args.termos_file, encoding="utf-8") as f:
            termos.extend([l.strip() for l in f if l.strip()])

    if not termos:
        print("Nenhum termo de busca definido. Use --nicho, --termos ou --termos-file.")
        sys.exit(1)

    # dedup mantendo ordem
    termos = list(dict.fromkeys(termos))
    print(f"\nTermos a processar ({len(termos)}): {termos}")

    if args.trends:
        print("\nChecando Google Trends...")
        trends = checar_google_trends(termos)
        for t, v in trends.items():
            print(f"  {t}: interesse médio (0-100) = {v}")

    all_videos = []
    all_ranked = []
    nicho_atual = args.nicho or ""
    filtros = _normalizar_filtros({
        "duracao_min": args.duracao_min,
        "duracao_max": args.duracao_max,
        "data_periodo": args.data_periodo,
        "ordenacao": args.ordenacao,
    })

    analise = _normalizar_analise({
        "janela_meses": args.janela_meses,
        "descartar_fora_janela": not args.manter_fora_da_janela,
        "n_frequencia": args.n_frequencia,
    })
    cache_canais = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, args=["--mute-audio"] if args.mute_audio else [])
        context = browser.new_context()  # contexto novo = equivalente a "anônimo"
        page = context.new_page()
        page.set_default_timeout(NAV_TIMEOUT)

        falhas_termos = []
        for termo in termos:
            try:
                videos, ranked = processar_termo(
                    page, termo, args.max_videos, args.min_subs,
                    termo_para_subnicho.get(termo, ""), nicho_atual, filtros=filtros,
                    analise=analise, cache_canais=cache_canais,
                )
                all_videos.extend(videos)
                all_ranked.extend(ranked)
            except Exception as exc:
                msg = f"Falha isolada no termo '{termo}': {type(exc).__name__}: {exc}"
                falhas_termos.append(msg)
                print(f"ERRO ISOLADO — {msg}")
                continue

        browser.close()

    save_csv("resultados_busca.csv", all_videos,
              fieldnames=["video_id", "titulo", "url", "canal", "canal_url",
                          "canal_verificado", "views_text", "views_num", "quando",
                          "data_publicacao", "data_verificada", "patrocinado", "termo_busca", "subnicho", "nicho", "pais_canal", "idioma_canal"])

    # remove duplicados no ranking geral, preservando todas as associações
    ranked_final = merge_channel_records(all_ranked)
    ranked_final.sort(key=lambda c: c.get("score") or 0, reverse=True)
    for idx, c in enumerate(ranked_final, 1):
        c["rank_geral"] = idx

    fieldnames = ["canal", "canal_url", "termo_busca", "inscritos_text", "inscritos_num",
                  "n_videos", "primeiro_video_titulo", "primeiro_video_quando", "primeiro_video_data_publicacao",
                  "primeiro_video_url", "primeiro_video_views_text", "primeiro_video_duracao",
                  "meses_desde_primeiro_video", "score", "inscritos_por_video",
                  "views_totais", "data_criacao_canal", "ultimo_video_data_publicacao",
                  "frequencia_label", "frequencia_intervalo_medio_dias", "videos_ultimos_30d",
                  "fora_da_janela",
                  "dados_incompletos_texto", "status_ranking",
                  "subnicho", "nicho", "pais_canal", "idioma_canal",
                  "top_3_populares_json", "video_exemplo", "views_video_exemplo"]
    import json as _json
    for _c in ranked_final:
        _c["top_3_populares_json"] = _json.dumps(_c.get("top_3_populares") or [], ensure_ascii=False)
    save_csv("canais_nao_verificados.csv", ranked_final, fieldnames=fieldnames)

    # Rankings segmentados, usando exatamente a mesma regra de score.
    for grupo_nome, grupos in [
        ("nichos", build_group_rankings(ranked_final, "nicho", "Sem nicho")),
        ("subnichos", build_group_rankings(ranked_final, "subnicho", "Sem subnicho")),
        ("paises", build_group_rankings(ranked_final, "pais_canal", "País desconhecido")),
        ("idiomas", build_group_rankings(ranked_final, "idioma_canal", "Idioma desconhecido")),
    ]:
        rows = []
        for grupo, members in grupos.items():
            for pos, c in enumerate(members, 1):
                rows.append({
                    "ranking_grupo": pos,
                    "grupo": grupo,
                    "canal": c.get("canal", ""),
                    "canal_url": c.get("canal_url", ""),
                    "score": c.get("score", 0),
                    "inscritos_num": c.get("inscritos_num", 0),
                    "n_videos": c.get("n_videos", 0),
                    "primeiro_video_quando": c.get("primeiro_video_quando", ""),
                    "pais_canal": c.get("pais_canal", ""),
                    "idioma_canal": c.get("idioma_canal", ""),
                    "subnichos": ", ".join(c.get("subnichos") or []),
                    "nichos": ", ".join(c.get("nichos") or []),
                })
        save_csv(f"ranking_{grupo_nome}.csv", rows, fieldnames=[
            "ranking_grupo", "grupo", "canal", "canal_url", "score", "inscritos_num",
            "n_videos", "primeiro_video_quando", "pais_canal", "idioma_canal", "subnichos", "nichos"
        ])

    # Canais verificados: separados da lógica de ranking dos não verificados.
    verificados_map = {}
    for v in all_videos:
        if v.get("canal_url") and v.get("canal_verificado"):
            verificados_map.setdefault(v["canal_url"], {
                "canal": v.get("canal", ""),
                "canal_url": v.get("canal_url", ""),
                "termo_busca": v.get("termo_busca", ""),
                "video_exemplo": v.get("url", ""),
                "views_text_video_exemplo": v.get("views_text", ""),
                "views_video_exemplo": v.get("views_num"),
                "canal_verificado": True,
            })
    verificados_final = sorted(
        verificados_map.values(),
        key=lambda c: (c.get("views_video_exemplo") or 0),
        reverse=True,
    )
    save_csv("canais_verificados.csv", verificados_final, fieldnames=[
        "canal", "canal_url", "termo_busca", "video_exemplo",
        "views_text_video_exemplo", "views_video_exemplo", "canal_verificado"
    ])

    print("\n=== TOP 15 CANAIS/NICHOS SUSPEITOS (não verificados; todos os termos) ===")
    for c in ranked_final[:15]:
        print(f"{c['canal']:<30} | termo='{c['termo_busca']:<28}' | inscritos={c.get('inscritos_text','?'):<10} "
              f"| vídeos={c.get('n_videos','?'):<4} | 1º vídeo={c.get('primeiro_video_quando','?'):<12} "
              f"| score={c['score']}")

    if falhas_termos:
        print(f"\n=== TERMOS COM FALHA ISOLADA: {len(falhas_termos)} ===")
        for falha in falhas_termos:
            print(f"- {falha}")

    print(f"\n=== CANAIS VERIFICADOS SEPARADOS: {len(verificados_final)} ===")
    for c in verificados_final[:15]:
        print(f"{c['canal']:<30} | termo='{c['termo_busca']:<28}' | visualizações do vídeo exemplo={c.get('views_text_video_exemplo','?'):<12}")


if __name__ == "__main__":
    main()
