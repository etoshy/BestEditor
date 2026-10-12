#!/usr/bin/env python3
"""
Mineração pelas recomendações de um vídeo
=========================================

Ao abrir um vídeo, o YouTube mostra ~15+ recomendados na lateral. Quando o
vídeo de origem é bom, ali costumam aparecer canais pequenos e ainda não
monetizados que estão indo bem. Este módulo automatiza a triagem:

  1. lê a lateral de cada vídeo de origem (título, canal, selo, views, idade, duração);
  2. mantém só canais NÃO verificados, com vídeo RECENTE (ex.: até 3 meses);
  3. calcula a média (ou mediana) de views dos elegíveis e guarda quem está na
     média ou acima dela (com fator ajustável);
  4. abre só os aprovados para descobrir o canal (a lateral não traz o link do
     canal) e confirmar a data real e a ausência de patrocínio;
  5. entrega os vídeos para a MESMA análise de canais da busca por nicho
     (``yt_scraper.analisar_canais_nao_verificados``): inscritos, nº de vídeos,
     idade, frequência, score e ranking.

Toda a lógica de decisão é pura (sem navegador) para ser testável.
"""

import re
import statistics
import time
from datetime import datetime
from urllib.parse import quote, unquote, urlparse

import yt_scraper as core

# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------

CFG_PADRAO = {
    "max_itens": 15,          # quantos recomendados olhar por vídeo de origem
    "meses_max": 3,           # vídeo postado há no máximo N meses
    "referencia": "media",    # "media" | "mediana"
    "fator": 1.0,             # aceita views >= referência x fator (1.0 = na média ou acima)
    "escopo": "por_video",    # "por_video" (cada lateral separada) | "global" (todas juntas)
    "duracao_min": 0,         # minutos; 0 = sem mínimo
    "duracao_max": 0,         # minutos; 0 = sem máximo
}
MAX_ORIGENS = 20

MOTIVOS = {
    "ok": "aprovado",
    "abaixo_da_media": "abaixo da referência de views",
    "verificado": "canal verificado",
    "antigo": "vídeo antigo demais",
    "idade_desconhecida": "idade do vídeo não identificada",
    "sem_views": "views não identificadas",
    "nao_video": "não é vídeo comum (short, playlist ou live)",
    "duracao": "duração fora do filtro",
    "patrocinado": "conteúdo patrocinado",
    "duplicado": "já apareceu em outra lateral",
}


def normalizar_cfg(cfg=None):
    """Valida e limita a configuração vinda da interface."""
    c = dict(CFG_PADRAO)
    for k, v in (cfg or {}).items():
        if k in c and v is not None:
            c[k] = v

    def num(valor, padrao, minimo, maximo, inteiro=False):
        try:
            x = float(str(valor).replace(",", "."))
        except (TypeError, ValueError):
            return padrao
        x = max(minimo, min(maximo, x))
        return int(x) if inteiro else x

    c["max_itens"] = num(c["max_itens"], 15, 5, 40, inteiro=True)
    c["meses_max"] = num(c["meses_max"], 3, 1, 36)
    c["meses_max"] = int(c["meses_max"]) if float(c["meses_max"]).is_integer() else c["meses_max"]
    c["fator"] = num(c["fator"], 1.0, 0.1, 3.0)
    c["duracao_min"] = num(c["duracao_min"], 0, 0, 240, inteiro=True)
    c["duracao_max"] = num(c["duracao_max"], 0, 0, 240, inteiro=True)
    c["referencia"] = c["referencia"] if c["referencia"] in ("media", "mediana") else "media"
    c["escopo"] = c["escopo"] if c["escopo"] in ("por_video", "global") else "por_video"
    return c


# --------------------------------------------------------------------------
# Entradas: URLs de vídeo, idade e itens da lateral
# --------------------------------------------------------------------------

_RE_VIDEO = re.compile(r"(?:youtube\.com/(?:watch\?(?:[^#\s]*&)?v=|live/)|youtu\.be/)([A-Za-z0-9_-]{11})")


def normalizar_url_video(texto):
    """Devolve ``(url_padrao, video_id)`` para links de vídeo do YouTube, ou ``None``.

    Aceita watch?v=, youtu.be/ e /live/. Shorts não têm lateral de recomendados."""
    m = _RE_VIDEO.search(str(texto or ""))
    if not m:
        return None
    return f"https://www.youtube.com/watch?v={m.group(1)}", m.group(1)


def separar_urls(texto_ou_lista, limite=MAX_ORIGENS):
    """Lê um por linha (ou lista), remove repetidos e separa os inválidos."""
    if isinstance(texto_ou_lista, str):
        linhas = texto_ou_lista.splitlines()
    else:
        linhas = list(texto_ou_lista or [])
    validas, invalidas, vistos = [], [], set()
    for bruto in linhas:
        linha = str(bruto or "").strip()
        if not linha:
            continue
        r = normalizar_url_video(linha)
        if r is None:
            invalidas.append(linha)
        elif r[1] not in vistos:
            vistos.add(r[1])
            validas.append(r[0])
    return validas[:limite], invalidas, max(0, len(validas) - limite)


def normalizar_url_canal(href):
    """URL canônica do canal (mesmo formato dos cards de busca), ou '' se não for de canal."""
    if not href:
        return ""
    caminho = unquote(urlparse(str(href)).path or "").rstrip("/")
    if not re.match(r"^/(@|channel/|c/|user/)", caminho):
        return ""
    return "https://www.youtube.com" + quote(caminho, safe="/@")


def idade_meses(texto):
    """Idade aproximada, em meses, de 'há 14 horas', 'há 14 h', 'há 5 dias', '2 years ago'...

    Devolve ``None`` quando não entende o texto (idade desconhecida NUNCA vira 'recente')."""
    if not texto:
        return None
    t = str(texto).lower().replace("\xa0", " ").strip()
    if re.search(r"\b(agora|just now|now)\b", t):
        return 0.0
    # "um mês" / "an hour": sem número, vira 1
    t = re.sub(r"\b(um|uma|an?)\s+(?=(dia|semana|m[eê]s|ano|day|week|month|year|hora|hour|minuto|minute|segundo|second))", "1 ", t)
    m = re.search(r"(\d+)\s*(horas?|hours?|h)\b", t)
    if m:
        return int(m.group(1)) / 24 / 30.4375
    if re.search(r"(\d+)\s*(segundos?|seconds?|minutos?|minutes?|seg|min|s)\b", t):
        return 0.0
    return core._meses_desde_texto(t)


def _tem_digito(txt):
    return bool(re.search(r"\d", txt or ""))


def normalizar_item(bruto, origem_id="", origem_url="", origem_titulo=""):
    """Transforma o item bruto lido da página no formato usado pelo resto do app."""
    vid = str(bruto.get("id") or "").strip()
    href = str(bruto.get("href") or "")
    ao_vivo = bool(bruto.get("ao_vivo"))
    if "/shorts/" in href:
        tipo = "short"
    elif "/playlist" in href or ("list=" in href and "v=" not in href):
        tipo = "playlist"
    elif ao_vivo:
        tipo = "live"
    elif not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
        tipo = "desconhecido"
    else:
        tipo = "video"

    views_text = str(bruto.get("views_txt") or "").strip()
    quando = str(bruto.get("quando_txt") or bruto.get("quando_curto") or "").strip()
    duracao = str(bruto.get("dur_txt") or "").strip()
    return {
        "video_id": vid,
        "url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
        "titulo": str(bruto.get("titulo") or "").strip(),
        "canal": str(bruto.get("canal") or "").strip(),
        "canal_verificado": bool(bruto.get("verificado")),
        "views_text": views_text,
        "views_num": core.parse_count(views_text) if _tem_digito(views_text) and not ao_vivo else None,
        "quando": quando,
        "idade_meses": idade_meses(quando),
        "duracao": duracao,
        "duracao_segundos": core.parse_duration_seconds(duracao),
        "tipo": tipo,
        "novo": bool(bruto.get("novo")),
        "patrocinado": core.texto_indica_patrocinado(str(bruto.get("texto") or "")),
        "origem_id": origem_id,
        "origem_url": origem_url,
        "origem_titulo": origem_titulo,
    }


# --------------------------------------------------------------------------
# Seleção pela média (lógica pura)
# --------------------------------------------------------------------------

def _valor_referencia(views, referencia):
    return float(statistics.median(views)) if referencia == "mediana" else float(statistics.fmean(views))


def selecionar_candidatos(itens, cfg=None):
    """Aplica os filtros e a regra da média. Devolve ``(itens_anotados, relatorio)``.

    Cada item ganha ``aprovado``, ``motivo`` (chave de ``MOTIVOS``), ``razao_media`` e
    ``referencia_views``. A referência é calculada só sobre os elegíveis (não
    verificados, recentes, vídeo comum, duração ok): verificados e virais antigos
    distorceriam a média. Com ``escopo="por_video"`` cada lateral tem a sua média.
    """
    c = normalizar_cfg(cfg)
    dmin, dmax = c["duracao_min"] * 60, c["duracao_max"] * 60
    vistos, anotados = set(), []
    for original in itens or []:
        it = dict(original)
        it.update({"aprovado": False, "motivo": "", "razao_media": None, "referencia_views": None, "limiar_views": None})
        dur = it.get("duracao_segundos")
        if it.get("video_id") in vistos:
            it["motivo"] = "duplicado"
        elif it.get("tipo") != "video":
            it["motivo"] = "nao_video"
        elif it.get("patrocinado"):
            it["motivo"] = "patrocinado"
        elif it.get("canal_verificado"):
            it["motivo"] = "verificado"
        elif it.get("views_num") is None:
            it["motivo"] = "sem_views"
        elif it.get("idade_meses") is None:
            it["motivo"] = "idade_desconhecida"
        elif it["idade_meses"] > c["meses_max"]:
            it["motivo"] = "antigo"
        elif dur is not None and ((dmin and dur < dmin) or (dmax and dur > dmax)):
            it["motivo"] = "duracao"
        else:
            it["motivo"] = "elegivel"
        if it.get("video_id"):
            vistos.add(it["video_id"])
        anotados.append(it)

    def chave_grupo(it):
        return it.get("origem_id") or "?" if c["escopo"] == "por_video" else "global"

    grupos = {}
    for it in anotados:
        g = grupos.setdefault(chave_grupo(it), {"itens": [], "pool": []})
        g["itens"].append(it)
        if it["motivo"] == "elegivel":
            g["pool"].append(it)

    relatorio_grupos = []
    for chave, g in grupos.items():
        views = [x["views_num"] for x in g["pool"]]
        valor = _valor_referencia(views, c["referencia"]) if views else None
        limiar = valor * c["fator"] if valor is not None else None
        aprovados = 0
        for it in g["pool"]:
            it["referencia_views"] = round(valor)
            it["limiar_views"] = round(limiar)
            it["razao_media"] = round(it["views_num"] / valor, 2) if valor else None
            if it["views_num"] >= limiar:
                it["aprovado"], it["motivo"] = True, "ok"
                aprovados += 1
            else:
                it["motivo"] = "abaixo_da_media"
        excluidos = {}
        for it in g["itens"]:
            if it["motivo"] not in ("ok", "abaixo_da_media"):
                excluidos[it["motivo"]] = excluidos.get(it["motivo"], 0) + 1
        origens = []
        for it in g["itens"]:
            if it.get("origem_id") and it["origem_id"] not in [o["origem_id"] for o in origens]:
                origens.append({"origem_id": it["origem_id"], "origem_titulo": it.get("origem_titulo", ""), "origem_url": it.get("origem_url", "")})
        primeiro = g["itens"][0] if g["itens"] else {}
        relatorio_grupos.append({
            "origem_id": primeiro.get("origem_id", "") if c["escopo"] == "por_video" else "",
            "origem_titulo": primeiro.get("origem_titulo", "") if c["escopo"] == "por_video" else "todos os vídeos de origem",
            "origem_url": primeiro.get("origem_url", "") if c["escopo"] == "por_video" else "",
            "origens": origens,
            "coletados": len(g["itens"]), "elegiveis": len(g["pool"]),
            "referencia": c["referencia"], "valor": round(valor) if valor is not None else None,
            "limiar": round(limiar) if limiar is not None else None,
            "aprovados": aprovados, "pouco_confiavel": 0 < len(g["pool"]) < 3, "excluidos": excluidos,
        })
    relatorio = {"cfg": c, "grupos": relatorio_grupos,
                 "totais": {"coletados": len(anotados), "aprovados": sum(1 for i in anotados if i["aprovado"])}}
    return anotados, relatorio


# --------------------------------------------------------------------------
# Leitura da página (Playwright)
# --------------------------------------------------------------------------

SEL_ITENS = "ytd-watch-next-secondary-results-renderer yt-lockup-view-model, ytd-watch-next-secondary-results-renderer ytd-compact-video-renderer"

# Roda no navegador. Layout atual: <yt-lockup-view-model> (classes yt*ViewModel). O layout
# antigo (<ytd-compact-video-renderer>) fica como reserva. A lateral NÃO traz o link do canal.
_JS_RECOMENDADOS = r"""(max) => {
  const limpo = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const idDe = (href) => { const m = /[?&]v=([\w-]{11})/.exec(href || '') || /\/(?:shorts|live)\/([\w-]{11})/.exec(href || ''); return m ? m[1] : ''; };
  const REGEX_VIEWS = /visualiza|views|assistindo|watching/i;
  const REGEX_QUANDO = /^(h[aá]\s|streamed|premiered)|\bago\b/i;
  const saida = [], vistos = new Set();
  const empilhar = (o) => { const k = o.id || o.href; if (saida.length >= max || (k && vistos.has(k))) return; if (k) vistos.add(k); saida.push(o); };

  document.querySelectorAll('ytd-watch-next-secondary-results-renderer yt-lockup-view-model').forEach((el) => {
    const a = el.querySelector('a.ytLockupMetadataViewModelTitle') || el.querySelector('a.ytLockupViewModelContentImage') || el.querySelector('a[href]');
    const href = a ? (a.getAttribute('href') || '') : '';
    const host = el.querySelector('.ytLockupViewModelHost');
    let id = idDe(href);
    if (!id && host) { const m = /content-id-([\w-]{11})/.exec(host.className || ''); if (m) id = m[1]; }
    const h3 = el.querySelector('h3[title]');
    const titulo = limpo((h3 && h3.getAttribute('title')) || (a && a.textContent) || '');
    const linhas = Array.from(el.querySelectorAll('.ytContentMetadataViewModelMetadataRow'));
    const primeira = linhas.length ? linhas[0] : null;
    let canal = '', verificado = false;
    if (primeira) {
      const span = primeira.querySelector('.ytContentMetadataViewModelMetadataText');
      const rotulo = span ? (span.getAttribute('aria-label') || '') : '';
      if (span && !REGEX_VIEWS.test(rotulo)) {
        canal = limpo(span.textContent);
        verificado = !!primeira.querySelector('.ytAttributedStringImageElement, svg');
      }
    }
    let viewsTxt = '', quando = '', quandoCurto = '';
    el.querySelectorAll('.ytContentMetadataViewModelMetadataText').forEach((sp) => {
      const rot = sp.getAttribute('aria-label') || '', txt = limpo(sp.textContent);
      if (!viewsTxt && REGEX_VIEWS.test(rot || txt)) viewsTxt = txt;
      else if (!quando && REGEX_QUANDO.test(rot || txt)) { quando = rot; quandoCurto = txt; }
    });
    const dur = el.querySelector('.ytThumbnailBottomOverlayViewModelBadgeContainer .ytBadgeShapeText, badge-shape .ytBadgeShapeText');
    const durTxt = dur ? limpo(dur.textContent) : '';
    const selo = Array.from(el.querySelectorAll('.ytBadgeShapeText')).map((n) => limpo(n.textContent)).join(' | ');
    empilhar({ id, href, titulo, canal, verificado, views_txt: viewsTxt, quando_txt: quando || quandoCurto, quando_curto: quandoCurto,
      dur_txt: /^\d{1,2}(:\d{2}){1,2}$/.test(durTxt) ? durTxt : '', ao_vivo: /ao vivo|\blive\b|estreia|premiere/i.test(selo) || /assistindo|watching/i.test(viewsTxt),
      novo: /\b(novo|new)\b/i.test(selo), texto: limpo(el.innerText).slice(0, 500) });
  });

  document.querySelectorAll('ytd-watch-next-secondary-results-renderer ytd-compact-video-renderer').forEach((el) => {
    const a = el.querySelector('a#thumbnail, a.yt-simple-endpoint');
    const href = a ? (a.getAttribute('href') || '') : '';
    const t = el.querySelector('#video-title');
    const c = el.querySelector('ytd-channel-name #text, #channel-name #text, ytd-channel-name yt-formatted-string');
    const spans = Array.from(el.querySelectorAll('#metadata-line span')).map((s) => limpo(s.textContent));
    const dur = el.querySelector('ytd-thumbnail-overlay-time-status-renderer span, .badge-shape-wiz__text');
    const durTxt = dur ? limpo(dur.textContent) : '';
    empilhar({ id: idDe(href), href, titulo: limpo((t && (t.getAttribute('title') || t.textContent)) || ''), canal: limpo(c ? c.textContent : ''),
      verificado: !!el.querySelector('ytd-badge-supported-renderer .badge-style-type-verified, ytd-badge-supported-renderer [aria-label*="erific" i]'),
      views_txt: spans[0] || '', quando_txt: spans[1] || '', quando_curto: spans[1] || '',
      dur_txt: /^\d{1,2}(:\d{2}){1,2}$/.test(durTxt) ? durTxt : '', ao_vivo: /assistindo|watching/i.test(spans[0] || ''), novo: false, texto: limpo(el.innerText).slice(0, 500) });
  });
  return saida;
}"""

_JS_CANAL = r"""() => {
  const meta = document.querySelector('span[itemprop="author"] link[itemprop="url"]');
  const nomeMeta = document.querySelector('span[itemprop="author"] link[itemprop="name"]');
  const a = document.querySelector('ytd-video-owner-renderer a[href^="/@"], ytd-video-owner-renderer a[href^="/channel/"], #owner a[href^="/@"], #owner a[href^="/channel/"]');
  const nomeEl = document.querySelector('ytd-video-owner-renderer ytd-channel-name a, #owner ytd-channel-name a');
  return {
    url: a ? a.href : (meta ? meta.getAttribute('href') : ''),
    nome: (nomeEl && (nomeEl.textContent || '').trim()) || (nomeMeta ? nomeMeta.getAttribute('content') : ''),
  };
}"""


def _consentimento(page):
    for txt in ["Aceitar tudo", "Accept all", "I agree", "Aceito"]:
        try:
            botao = page.get_by_text(txt, exact=True)
            if botao.count():
                botao.first.click(timeout=1500)
                return
        except Exception:
            pass


def _resetar_pagina(page):
    """Depois de uma navegação que falhou, o Chromium carrega uma página de erro de forma assíncrona
    e a PRÓXIMA navegação pode ser interrompida por ela. Esperar um pouco e ir a about:blank limpa isso."""
    try:
        page.wait_for_timeout(600)
        page.goto("about:blank")
    except Exception:
        pass


def _titulo_da_pagina(page, fallback=""):
    try:
        t = re.sub(r"^\(\d+\)\s*", "", page.title() or "")
        t = re.sub(r"\s*-\s*YouTube\s*$", "", t).strip()
        return t or fallback
    except Exception:
        return fallback


def _ler_lateral_atual(page, max_itens=15, log=print, espera_ms=15000):
    """Lê a lateral de recomendados da página JÁ ABERTA (sem navegar).

    Usado tanto por ``coletar_recomendados`` (que navega antes) quanto pela mineração por
    termo, que já está na página do vídeo por causa da validação de data/patrocínio — assim
    a lateral é lida sem gastar uma navegação a mais.
    """
    try:  # não precisa reproduzir o vídeo
        page.evaluate("() => { const v = document.querySelector('video'); if (v) v.pause(); }")
    except Exception:
        pass
    try:
        page.wait_for_selector(SEL_ITENS, timeout=espera_ms)
    except Exception:
        log("  a lateral de recomendados não apareceu (vídeo indisponível ou layout novo).")
    page.wait_for_timeout(800)
    brutos, parados = [], 0
    for _ in range(6):
        atuais = page.evaluate(_JS_RECOMENDADOS, max_itens) or []
        parados = parados + 1 if len(atuais) <= len(brutos) else 0
        brutos = atuais
        if len(brutos) >= max_itens or parados >= 2:
            break
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(1000)
    return _titulo_da_pagina(page), brutos


def coletar_recomendados(page, url, max_itens=15, log=print, espera_ms=15000):
    """Abre o vídeo e lê os primeiros ``max_itens`` recomendados da lateral.

    Devolve ``(titulo_do_video_de_origem, itens_brutos)``. Rola a página quando a
    lateral ainda mostra menos itens do que o pedido."""
    page.goto(url, wait_until="domcontentloaded", timeout=core.NAV_TIMEOUT)
    page.wait_for_timeout(1500)
    _consentimento(page)
    return _ler_lateral_atual(page, max_itens, log, espera_ms)


def extrair_canal_da_pagina(page):
    """Link e nome do canal na página do vídeo aberta. ``('', '')`` se não achar."""
    try:
        r = page.evaluate(_JS_CANAL) or {}
    except Exception:
        return "", ""
    return normalizar_url_canal(r.get("url")), str(r.get("nome") or "").strip()


def validar_e_resolver(page, item, meses_max, agora=None):
    """Abre o vídeo aprovado: confirma data real e patrocínio e descobre o canal.

    Devolve ``(video_no_formato_do_app, 'ok')`` ou ``(None, motivo)``."""
    agora = agora or datetime.now()
    video = {
        "video_id": item["video_id"], "titulo": item["titulo"], "url": item["url"],
        "canal": item["canal"], "canal_url": "", "canal_verificado": False,
        "views_text": item["views_text"], "views_num": item["views_num"], "quando": item["quando"],
        "duracao": item["duracao"], "duracao_segundos": item["duracao_segundos"],
        "data_publicacao": "", "data_verificada": False, "patrocinado": False,
        "origem_video": item.get("origem_url", ""), "razao_media": item.get("razao_media"),
    }
    ok, motivo = core.validar_video_no_periodo(page, video, "todos", agora=agora)   # data real + patrocínio
    if not ok:
        return None, motivo
    meses = core._meses_desde_data(video["data_publicacao"], agora) if video["data_verificada"] else None
    if meses is not None and meses > meses_max:
        return None, f"fora_do_periodo:{video['data_publicacao']}"
    url_canal, nome = extrair_canal_da_pagina(page)
    if not url_canal:
        return None, "canal_nao_identificado"
    video["canal_url"] = url_canal
    if nome:
        video["canal"] = nome
    return video, "ok"


# --------------------------------------------------------------------------
# Fluxo completo
# --------------------------------------------------------------------------

def _resumo_item(it, analisado):
    chaves = ("video_id", "url", "titulo", "canal", "canal_verificado", "views_num", "views_text", "quando",
              "idade_meses", "duracao", "aprovado", "motivo", "razao_media", "origem_id", "tipo")
    return {**{k: it.get(k) for k in chaves}, "analisado": analisado}


def _logar_grupos(relatorio, log=print, prefixo=""):
    """Uma linha de resumo por grupo (mesmo texto usado pela triagem manual e pela automática)."""
    for g in relatorio["grupos"]:
        rotulo = g["origem_titulo"][:50] or "?"
        if g["valor"] is None:
            log(f"  [{prefixo}{rotulo}] nenhum recomendado elegível (não verificado + recente).")
            continue
        aviso = " (poucos elegíveis: referência pouco confiável)" if g["pouco_confiavel"] else ""
        log(f"  [{prefixo}{rotulo}] {g['elegiveis']} elegíveis | {'média' if relatorio['cfg']['referencia'] == 'media' else 'mediana'} = "
            f"{_fmt_num(g['valor'])} views | corte = {_fmt_num(g['limiar'])} | {g['aprovados']} aprovados{aviso}")


def _validar_aprovados(page, aprovados, meses_max, nicho, rotulo_termo, log=print):
    """Abre cada aprovado (confirma data/patrocínio e acha o canal) e monta os vídeos no formato do app.

    Devolve ``(videos, ids_validados)``. Usado pela triagem manual (vídeos colados) e pela
    automática (lateral lida durante a mineração por termo) — o resultado entra na MESMA análise
    de canais não verificados do resto do app."""
    videos, validados = [], set()
    for i, it in enumerate(aprovados, 1):
        try:
            video, motivo = validar_e_resolver(page, it, meses_max)
        except Exception as exc:
            video, motivo = None, f"erro:{type(exc).__name__}"
        if video is None:
            it["aprovado"], it["motivo"] = False, "validacao:" + motivo
            log(f"  [{i}/{len(aprovados)}] IGNORADO ({motivo}): {it['titulo'][:80]}")
            if motivo.startswith("erro"):
                _resetar_pagina(page)
            continue
        video["termo_busca"] = rotulo_termo or f"Recomendados de: {it.get('origem_titulo') or it.get('origem_id')}"
        video["subnicho"], video["nicho"] = "Sem subnicho", nicho or "Sem nicho"
        videos.append(video)
        validados.add(it["video_id"])
        log(f"  [{i}/{len(aprovados)}] OK — {video['data_publicacao'] or 'data não lida'} — {it['canal']} — {it['titulo'][:70]}")
        time.sleep(0.5)
    return videos, validados


def processar_recomendados(page, urls, cfg, min_subs, max_videos, analise, cache_canais, nicho="Sem nicho", log=print):
    """Lateral de cada vídeo -> seleção pela média -> canal + data real -> análise de canais.

    Devolve ``(videos, ranked, falhas, relatorio)`` no mesmo formato de ``processar_termo``
    (mais o relatório da triagem para a interface). Falha em um vídeo de origem não
    derruba os demais."""
    c = normalizar_cfg(cfg)
    itens, falhas, origens = [], [], []
    for i, url in enumerate(urls, 1):
        log(f"\n--- VÍDEO DE ORIGEM {i}/{len(urls)} | {url} ---")
        try:
            titulo, brutos = coletar_recomendados(page, url, c["max_itens"], log=log)
        except Exception as exc:
            msg = f"Falha isolada no vídeo de origem '{url}': {type(exc).__name__}: {exc}"
            falhas.append(msg)
            log(f"  ERRO ISOLADO — {msg}")
            _resetar_pagina(page)
            continue
        origem_id = normalizar_url_video(url)[1]
        titulo = titulo or origem_id
        lote = [normalizar_item(b, origem_id, url, titulo) for b in brutos]
        origens.append({"origem_id": origem_id, "origem_titulo": titulo, "origem_url": url, "lidos": len(lote)})
        log(f"  '{titulo[:70]}': {len(lote)} recomendados lidos.")
        itens.extend(lote)
        time.sleep(0.6)

    anotados, relatorio = selecionar_candidatos(itens, c)
    relatorio["origens"] = origens
    _logar_grupos(relatorio, log)

    aprovados = [it for it in anotados if it["aprovado"]]
    log(f"\n{len(aprovados)} vídeos aprovados de {len(anotados)} lidos. Abrindo cada um para confirmar data e descobrir o canal...")
    videos, validados = _validar_aprovados(page, aprovados, c["meses_max"], nicho, None, log=log)

    ranked = core.analisar_canais_nao_verificados(page, videos, "recomendações", "Sem subnicho", nicho or "Sem nicho",
                                                  min_subs, max_videos, analise, cache_canais)
    relatorio["itens"] = [_resumo_item(it, it["video_id"] in validados) for it in anotados]
    relatorio["canais_analisados"] = len(ranked)
    return videos, ranked, falhas, relatorio


def processar_lateral_inline(page, itens, cfg, nicho, termo, log=print):
    """Mesma seleção pela média + validação da triagem manual, mas para itens já lidos DURANTE a
    mineração por termo (chamado de ``yt_scraper.processar_termo``, que lê cada lateral sem
    navegação extra, pois já está na página do vídeo por causa da validação de data/patrocínio).

    Devolve ``(videos, relatorio)``. ``videos`` entra na mesma lista da busca por termo antes
    da análise de canais — vira só mais uma fonte de candidatos, sem rota nem ranking próprios."""
    c = normalizar_cfg(cfg)
    anotados, relatorio = selecionar_candidatos(itens, c)
    _logar_grupos(relatorio, log, prefixo="lateral: ")
    aprovados = [it for it in anotados if it["aprovado"]]
    if not aprovados:
        relatorio["itens"] = [_resumo_item(it, False) for it in anotados]
        return [], relatorio
    log(f"\n{len(aprovados)} recomendados da lateral aprovados de {len(anotados)} lidos. Abrindo cada um...")
    videos, validados = _validar_aprovados(page, aprovados, c["meses_max"], nicho, f"Recomendados (lateral) de: {termo}", log=log)
    relatorio["itens"] = [_resumo_item(it, it["video_id"] in validados) for it in anotados]
    return videos, relatorio


# --------------------------------------------------------------------------
# Prompt: canais encontrados -> subnichos e termos (mesmo JSON do passo 1/2)
# --------------------------------------------------------------------------

def _fmt_num(n):
    return f"{int(n):,}".replace(",", ".") if isinstance(n, (int, float)) else "?"


def montar_prompt_subnichos_de_canais(canais, videos=None, n_subnichos=5, n_termos=5, max_canais=15):
    """Prompt para colar numa IA de chat, sem API. A resposta tem o MESMO formato do passo 1
    (``{"subnichos": [{"nome", "termos"}]}``), então entra no passo 2 e alimenta uma busca por nicho."""
    lista = list(canais or [])[:max(1, int(max_canais))]
    if not lista:
        raise ValueError("Não há canais para montar o prompt.")
    titulos = {}
    for v in videos or []:
        if v.get("canal_url") and v.get("titulo"):
            titulos.setdefault(v["canal_url"], []).append((v.get("views_num") or 0, v["titulo"]))
    linhas = []
    for i, ch in enumerate(lista, 1):
        partes = []
        if ch.get("inscritos_num") is not None:
            partes.append(f"{_fmt_num(ch['inscritos_num'])} inscritos")
        if ch.get("n_videos") is not None:
            partes.append(f"{ch['n_videos']} vídeos")
        if ch.get("views_totais") is not None:
            partes.append(f"{_fmt_num(ch['views_totais'])} views totais")
        if ch.get("pais_canal"):
            partes.append(f"país {ch['pais_canal']}")
        if ch.get("idioma_canal"):
            partes.append(f"idioma {ch['idioma_canal']}")
        exemplos = [t for _, t in sorted(titulos.get(ch.get("canal_url"), []), reverse=True)[:2]]
        if not exemplos:
            exemplos = [str(p.get("titulo")) for p in (ch.get("top_3_populares") or [])[:2] if isinstance(p, dict) and p.get("titulo")]
        if exemplos:
            partes.append("vídeos: " + "; ".join(f'"{t}"' for t in exemplos))
        linhas.append(f'{i}. "{ch.get("canal", "?")}" — ' + ("; ".join(partes) or "sem dados"))
    return (
        "Estes canais do YouTube, ainda não verificados e com vídeos recentes e boas views, apareceram nas "
        "recomendações de vídeos que estão funcionando:\n\n" + "\n".join(linhas) + "\n\n"
        "Identifique o que eles têm em comum (nicho, formato, ângulo, público). Depois liste "
        f"{n_subnichos} subnichos específicos e pouco saturados nesse território para canais do YouTube. "
        f"Para cada subnicho, dê {n_termos} termos de busca em inglês para pesquisar no YouTube e achar canais "
        "parecidos com esses (sem usar o nome dos canais acima). "
        "Responda ESTRITAMENTE em JSON válido, sem markdown, sem texto antes ou depois, exatamente neste formato:\n\n"
        '{"subnichos": [{"nome": "nome do subnicho", "termos": ["termo 1", "termo 2"]}]}'
    )
