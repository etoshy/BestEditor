#!/usr/bin/env python3
"""
Coleta da aba "Ideias virais" (Playwright, local, sem API key)
==============================================================

Reaproveita o que o yt_scraper.py já faz (busca, filtros, coleta de cards,
cabeçalho de canal) e acrescenta:

  * radar de vídeos em alta com "views por dia" e razão views/inscritos;
  * autocomplete do Google e do YouTube (mesmo endpoint da caixa de busca);
  * "As pessoas também perguntam" e "Pesquisas relacionadas" do Google;
  * métricas de concorrência sobre os resultados do YouTube.

Os seletores do Google/YouTube mudam sem aviso. Toda função aqui falha de forma
isolada (devolve status/vazio) para nunca derrubar a execução inteira.
"""

import re
import time
from datetime import datetime
from urllib.parse import quote

import ideias
import yt_scraper as core


# --------------------------------------------------------------------------
# YouTube: radar de vídeos em alta
# --------------------------------------------------------------------------

def url_busca_youtube(termo, mercado_cod):
    return f"{core.build_search_url(termo)}&gl={ideias.mercado(mercado_cod)['gl']}"


def idade_dias(quando, agora=None):
    """Idade aproximada em dias a partir de 'há 3 semanas' (mínimo 1). None se não der para ler."""
    d = core._data_aproximada_de_texto(quando, agora)
    if d is None:
        return None
    hoje = (agora or datetime.now()).date()
    return max(1, (hoje - d).days)


def enriquecer_video(v, termo, agora=None):
    v = dict(v)
    v["termo_busca"] = termo
    dias = idade_dias(v.get("quando"), agora)
    v["idade_dias"] = dias
    v["views_dia"] = round(v["views_num"] / dias, 1) if dias and v.get("views_num") is not None else None
    return v


def _consentimento_youtube(page):
    """Só clica se o botão existir (count() é instantâneo; um clique com timeout custaria 1,5 s por texto)."""
    for txt in ["Aceitar tudo", "Accept all", "I agree", "Aceito"]:
        try:
            botao = page.get_by_text(txt, exact=True)
            if botao.count():
                botao.first.click(timeout=1500)
                return
        except Exception:
            pass


def coletar_videos_termo(page, termo, mercado_cod, filtros, max_videos, log=print):
    """Busca no YouTube com os filtros e devolve os vídeos enriquecidos (sem abrir cada vídeo)."""
    filtros = core._normalizar_filtros(filtros)
    url = url_busca_youtube(termo, mercado_cod)
    log(f"Abrindo: {url}")
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    _consentimento_youtube(page)
    core.apply_filters(page, filtros)
    videos = core.collect_videos(page, max_videos)
    videos = core._filtrar_por_duracao(videos, filtros)
    agora = datetime.now()
    return [enriquecer_video(v, termo, agora) for v in videos]


def ler_cabecalho_canal(page, canal_url):
    """Inscritos e total de vídeos numa única navegação (bem mais leve que a análise completa)."""
    page.goto(canal_url.rstrip("/"), timeout=core.NAV_TIMEOUT, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    return core._extract_channel_header_metadata(page, page.inner_text("body"))


def coletar_inscritos(page, videos, top_k, cache, log=print):
    """Lê inscritos dos ``top_k`` canais não verificados com mais views (verificados já são grandes)."""
    melhores = {}
    for v in videos:
        url = v.get("canal_url")
        if not url or v.get("canal_verificado"):
            continue
        if url not in melhores or (v.get("views_num") or 0) > (melhores[url].get("views_num") or 0):
            melhores[url] = v
    alvo = sorted(melhores.values(), key=lambda x: x.get("views_num") or 0, reverse=True)[:max(0, top_k)]
    for n, v in enumerate(alvo, 1):
        url = v["canal_url"]
        if url in cache:
            continue
        log(f"  [{n}/{len(alvo)}] lendo inscritos de {v.get('canal') or url}")
        try:
            meta = ler_cabecalho_canal(page, url)
            cache[url] = {"inscritos_num": meta.get("inscritos_num"), "inscritos_text": meta.get("inscritos_text", ""),
                          "n_videos_canal": meta.get("n_videos")}
        except Exception as exc:
            log(f"    não foi possível ler o canal ({type(exc).__name__}: {exc})")
            cache[url] = {"inscritos_num": None, "inscritos_text": "", "n_videos_canal": None}
        time.sleep(0.6)
    return cache


def aplicar_razoes(videos, canais):
    """Junta os inscritos ao vídeo e calcula views/inscritos (o sinal 'canal pequeno, vídeo grande')."""
    for v in videos:
        info = canais.get(v.get("canal_url") or "")
        if info and info.get("inscritos_num"):
            v["inscritos_num"] = info["inscritos_num"]
            v["n_videos_canal"] = info.get("n_videos_canal")
            if v.get("views_num") is not None:
                v["razao_views_inscritos"] = round(v["views_num"] / info["inscritos_num"], 2)
    return videos


# --------------------------------------------------------------------------
# Autocomplete (Google e YouTube)
# --------------------------------------------------------------------------

def url_sugestoes(consulta, mercado_cod, youtube=False):
    m = ideias.mercado(mercado_cod)
    return ("https://suggestqueries.google.com/complete/search?client=firefox"
            f"{'&ds=yt' if youtube else ''}&hl={m['hl']}&gl={m['gl']}&q={quote(consulta)}")


def fetch_por_contexto(context):
    """Função de download usando o contexto do navegador (mesmos cookies/idioma, sem chave)."""
    def _fetch(url):
        resp = context.request.get(url, timeout=15000)
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status}")
        return resp.text()
    return _fetch


def coletar_sugestoes(fetch, termo, mercado_cod, alfabeto=False, pausa=0.3):
    """Sugestões do Google e do YouTube para o termo (e, opcionalmente, 'termo a'…'termo z').

    Cada fonte vem como lista, ou ``None`` quando nenhuma consulta funcionou
    (assim 'não coletado' nunca vira 'zero sugestões').
    """
    consultas = [termo] + ([f"{termo} {c}" for c in "abcdefghijklmnopqrstuvwxyz"] if alfabeto else [])
    saida = {}
    for fonte, yt in (("google", False), ("youtube", True)):
        lista, funcionou = [], False
        for q in consultas:
            try:
                texto = fetch(url_sugestoes(q, mercado_cod, youtube=yt))
                funcionou = True
            except Exception:
                continue
            for s in ideias.parse_sugestoes(texto):
                if s not in lista:
                    lista.append(s)
            if len(consultas) > 1:
                time.sleep(pausa)
        saida[fonte] = lista if funcionou else None
    return saida


# --------------------------------------------------------------------------
# Google: "As pessoas também perguntam" e "Pesquisas relacionadas"
# --------------------------------------------------------------------------

_JS_SERP = r"""() => {
  const ROT_PAA = /as pessoas também perguntam|people also ask|otras preguntas|preguntas relacionadas|les internautes demandent|autres questions|weitere fragen|altre domande|ludzie pytają też/i;
  const ROT_REL = /pesquisas relacionadas|as pessoas também pesquisam|related searches|people also search|búsquedas relacionadas|recherches associées|ähnliche suchanfragen|ricerche correlate|powiązane wyszukiwania/i;
  const limpo = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const acima = (n, k) => { for (let i = 0; i < k && n.parentElement; i++) n = n.parentElement; return n; };
  const paa = new Set(), rel = new Set();
  document.querySelectorAll('[data-q], .related-question-pair').forEach((n) => {
    const t = limpo(n.getAttribute('data-q') || (n.innerText || '').split('\n')[0]);
    if (t.length > 8 && t.length < 220) paa.add(t);
  });
  const cabecalhos = Array.from(document.querySelectorAll('h1,h2,h3,h4,[role=heading]'));
  cabecalhos.forEach((h) => {
    const rotulo = limpo(h.innerText);
    if (ROT_PAA.test(rotulo)) {
      const c = acima(h, 5);
      (c.innerText || '').split('\n').map(limpo).forEach((l) => {
        if (l.endsWith('?') && l.length > 8 && l.length < 220) paa.add(l);
      });
    }
    if (ROT_REL.test(rotulo)) {
      const c = acima(h, 5);
      c.querySelectorAll('a[href*="/search?"]').forEach((a) => {
        const t = limpo(a.innerText);
        if (t.length > 2 && t.length < 120 && t !== rotulo) rel.add(t);
      });
    }
  });
  document.querySelectorAll('#botstuff a[href*="/search?"], #bres a[href*="/search?"]').forEach((a) => {
    const t = limpo(a.innerText);
    if (t.length > 2 && t.length < 120) rel.add(t);
  });
  return { paa: Array.from(paa), relacionadas: Array.from(rel) };
}"""

_SINAIS_BLOQUEIO = ("unusual traffic", "tráfego incomum", "tráfico inusual", "não sou um robô",
                    "i'm not a robot", "trafic inhabituel", "ungewöhnlichen datenverkehr")


def _google_bloqueou(page):
    url = (page.url or "").lower()
    if "/sorry/" in url or "consent.google" in url:
        return True
    try:
        texto = (page.inner_text("body") or "")[:4000].lower()
    except Exception:
        return False
    return any(s in texto for s in _SINAIS_BLOQUEIO)


def _consentimento_google(page):
    """Prefere 'Rejeitar tudo' (não ativa rastreamento); aceita só se não houver outra saída."""
    for padrao in (r"rejeitar tudo|recusar tudo|reject all|alles ablehnen|tout refuser|rechazar todo|rifiuta tutto",
                   r"aceitar tudo|accept all|alles akzeptieren|tout accepter|aceptar todo|accetta tutto"):
        try:
            botao = page.get_by_role("button", name=re.compile(padrao, re.I))
            if botao.count():
                botao.first.click(timeout=1500)
                page.wait_for_timeout(1200)
                return
        except Exception:
            pass


def coletar_serp_google(page, termo, mercado_cod):
    """Lê 'As pessoas também perguntam' e 'Pesquisas relacionadas'. Status: ok | bloqueado | erro."""
    m = ideias.mercado(mercado_cod)
    url = f"https://www.google.com/search?q={quote(termo)}&hl={m['hl']}&gl={m['gl']}"
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        _consentimento_google(page)
        if _google_bloqueou(page):
            return {"status": "bloqueado", "paa": [], "relacionadas": []}
        dados = page.evaluate(_JS_SERP) or {}
        return {"status": "ok", "paa": list(dados.get("paa") or [])[:15],
                "relacionadas": list(dados.get("relacionadas") or [])[:15]}
    except Exception as exc:
        return {"status": "erro", "paa": [], "relacionadas": [], "erro": f"{type(exc).__name__}: {exc}"}
