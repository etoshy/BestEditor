"""
📣 v84_400 — MyInstants como fonte RESERVA de efeitos (nunca de música).

Muita coisa lá é meme e chega estourada — por isso todo som baixado passa pela checagem do audio_qualidade (estourado =
recusado) e entra no sound design só quando o Pixabay não tem nada que preste pra aquela busca (ou quando o juiz 🎯
acha que o daqui combina MUITO mais).

Baseado no script de busca do MyInstants (Playwright): abre /pt/search/?name=<termo>, rola até carregar, pega o .mp3
de cada card (o onclick="play('/media/sounds/….mp3', …)") e baixa pela MESMA sessão do navegador.
Salva em <pasta>/catalogo.json no mesmo formato do catálogo do Pixabay (busca, tipo, arquivo_cortado, dur, pico…).
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote_plus

BASE = "https://www.myinstants.com"
MP3_RE = re.compile(r"play\('([^']+\.mp3)'")


def url_busca(termo: str, idioma: str = "pt") -> str:
    return f"{BASE}/{idioma}/search/?name={quote_plus(' '.join(str(termo or '').split()))}"


def ler_cards(pagina_html: str) -> List[Dict[str, str]]:
    """Os cards .instant da página → [{"mp3": "/media/sounds/x.mp3", "titulo", "pagina"}] (sem repetir)."""
    s = pagina_html or ""
    partes = re.split(r'<div[^>]+class="[^"]*\binstant\b[^"]*"', s)[1:]
    out, vistos = [], set()
    for p in partes:
        m = MP3_RE.search(_html.unescape(p))
        if not m or m.group(1) in vistos:
            continue
        vistos.add(m.group(1))
        a = re.search(r'<a[^>]+href="([^"]+)"[^>]*class="[^"]*instant-link[^"]*"[^>]*>(.*?)</a>', p, re.S) or \
            re.search(r'<a[^>]+class="[^"]*instant-link[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', p, re.S)
        titulo = _html.unescape(re.sub(r"<[^>]+>", "", a.group(2))).strip() if a else ""
        out.append({"mp3": m.group(1), "titulo": titulo, "pagina": (BASE + a.group(1)) if a else ""})
    return out


def _slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (t or "").lower()).strip("_")[:50] or "som"


def _catalogo(pasta: str) -> List[Dict[str, Any]]:
    try:
        with open(os.path.join(pasta, "catalogo.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _salvar(pasta: str, itens: List[Dict[str, Any]]) -> None:
    por = {x["id"]: x for x in _catalogo(pasta)}
    por.update({x["id"]: x for x in itens})
    tmp = os.path.join(pasta, "catalogo.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(list(por.values()), f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(pasta, "catalogo.json"))


def processar(meta: Dict[str, Any], arquivo: str) -> Dict[str, Any]:
    """Mede, checa se está estourado e corta o silêncio das pontas (igual aos do Pixabay)."""
    import audio_qualidade as AQ
    import pixabay_sons as PS
    meta["qualidade"] = AQ.avaliar(arquivo)
    cortado = os.path.splitext(arquivo)[0] + "_cortado.m4a"
    f = PS.cortar_silencio(arquivo, cortado)
    meta.update({k: f[k] for k in ("dur", "inicio_som", "pico", "fim_som", "nivel_db") if k in f})
    meta["arquivo_cortado"] = cortado
    return meta


def rodar(termos: List[str], pasta: str, limite: int = 4, log: Callable[[str], None] = print,
          oculto: bool = True, preparar_ctx: Optional[Callable[[Any], None]] = None) -> int:
    """Busca e baixa. Devolve quantos ficaram prontos (cortados)."""
    from playwright.sync_api import sync_playwright
    os.makedirs(pasta, exist_ok=True)
    feitos: List[Dict[str, Any]] = []
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=oculto)
        ctx = nav.new_context(locale="pt-BR")
        if preparar_ctx:
            preparar_ctx(ctx)
        page = ctx.new_page()
        try:
            for termo in [t for t in termos if t]:
                url = url_busca(termo)
                log(f"📣 MyInstants: {url}")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_selector(".instant", timeout=15000)
                except Exception:  # noqa: BLE001
                    log(f"   nada pra “{termo}”")
                    continue
                cards = ler_cards(page.content())[:limite]
                for c in cards:
                    sid = "mi_" + _slug(os.path.splitext(os.path.basename(c["mp3"]))[0])
                    destino = os.path.join(pasta, sid + ".mp3")
                    meta = {"id": sid, "titulo": c["titulo"], "pagina": c["pagina"], "busca": termo, "tipo": "efeitos",
                            "fonte": "myinstants", "mp3": BASE + c["mp3"], "autor": "MyInstants"}
                    try:
                        if not os.path.isfile(destino):
                            r = ctx.request.get(BASE + c["mp3"])
                            if not r.ok:
                                log(f"   falhou ({r.status}): {c['mp3']}")
                                continue
                            with open(destino, "wb") as f:
                                f.write(r.body())
                        meta["arquivo_mp3"] = destino
                        processar(meta, destino)
                        q = meta["qualidade"]
                        log(f"   🎵 {c['titulo'] or sid} — {q['lufs']:.0f} LUFS" + (f" · ⚠ {q['motivo']}" if q["motivo"] else ""))
                        feitos.append(meta)
                    except Exception as exc:  # noqa: BLE001
                        log(f"   ❌ {exc}")
                    time.sleep(0.3)  # educado com o servidor
        finally:
            nav.close()
    _salvar(pasta, feitos)
    return sum(1 for x in feitos if x.get("arquivo_cortado"))
