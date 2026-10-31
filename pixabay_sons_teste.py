"""🔊 TESTE RÁPIDO — efeitos sonoros do Pixabay (só esta parte, fora do site por enquanto).

O que faz:
  1. abre a busca do Pixabay num Chrome de verdade (perfil próprio em pixabay_sons/_perfil — se aparecer a
     verificação "sou humano" da Cloudflare, resolva na janela uma vez e ela fica lembrada);
  2. lê cada som da página (título, autor, tags, curtidas, a forma de onda → onde está o som);
  3. pega o .mp3 de cada um: primeiro procura no JSON da página; se não tiver, CLICA no ▶ e pega a request do
     .mp3 que o site faz (como no "inspecionar → Rede");
  4. baixa, mede o som de verdade, corta o silêncio das pontas (arquivo _cortado.m4a), faz o espectrograma;
  5. (com --ia) a IA escreve a ficha: nome, descrição, categoria, usos, tags;
  6. salva tudo em pixabay_sons/catalogo.json (e base_sons.json já no formato da base de sons do editor).

Uso (na pasta do site, no PowerShell):
    python pixabay_sons_teste.py "whoosh tall"
    python pixabay_sons_teste.py "whoosh tall" --paginas 2 --limite 5 --ia
    python pixabay_sons_teste.py --html pagina_salva.html        (só lê um HTML salvo, sem navegador)

Opções: --paginas N (1) · --limite N por página (5) · --pasta (pixabay_sons) · --oculto (sem janela — a Cloudflare
costuma barrar) · --chrome (usa o Google Chrome instalado em vez do Chromium do Playwright) · --ia · --sem-baixar
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import pixabay_sons as PS  # noqa: E402

SEL_LINHA = '[class*="audioRow--"]'
SEL_PLAY = 'button[class*="playOverlay--"]'


def log(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------ navegador
def esperar_resultados(page, segundos: int = 90) -> bool:
    """Espera as linhas de som. Se a Cloudflare pedir verificação, dá tempo de resolver na janela."""
    fim = time.time() + segundos
    avisou = False
    while time.time() < fim:
        if page.locator(SEL_LINHA).count():
            return True
        corpo = (page.content() or "").lower()
        if not avisou and ("challenges.cloudflare.com" in corpo and "turnstile" in corpo and not page.locator(SEL_LINHA).count()
                           or "verify you are human" in corpo or "verifique se você é humano" in corpo):
            log("   🛡 a Cloudflare pediu verificação — resolva na janela do navegador (espero até 90 s)…")
            avisou = True
        if "nenhum resultado" in corpo or "no results" in corpo:
            return False
        page.wait_for_timeout(1000)
    return False


def rolar_ate_o_fim(page) -> None:
    """As formas de onda só aparecem quando a linha entra na tela: passa por todas."""
    linhas = page.locator(SEL_LINHA)
    for i in range(linhas.count()):
        try:
            linhas.nth(i).scroll_into_view_if_needed(timeout=3000)
            page.wait_for_timeout(120)
        except Exception:  # noqa: BLE001
            pass
    page.wait_for_timeout(500)


def mp3s_do_bootstrap(page, ids: List[str]) -> Dict[str, str]:
    """O JSON que a página carrega (window.__BOOTSTRAP_URL__) — às vezes já traz o link de todos os sons."""
    try:
        dados = page.evaluate("""async () => {
            const u = window.__BOOTSTRAP_URL__; if (!u) return null;
            const r = await fetch(u, {credentials: 'include'}); if (!r.ok) return null;
            return await r.json();
        }""")
    except Exception as exc:  # noqa: BLE001
        log(f"   (bootstrap não veio: {str(exc)[:120]})")
        return {}
    return PS.mp3_por_id(dados, ids) if dados else {}


def mp3_clicando(page, i: int, ouvidos: List[str], espera: float = 8.0) -> Optional[str]:
    """Clica no ▶ da linha i e devolve o .mp3 novo que o site pediu (depois pausa)."""
    linha = page.locator(SEL_LINHA).nth(i)
    antes = len(ouvidos)
    audios_antes = set(page.eval_on_selector_all("audio", "els => els.map(e => e.src)") or [])
    try:
        linha.scroll_into_view_if_needed(timeout=3000)
        linha.locator(SEL_PLAY).first.click(timeout=5000)
    except Exception as exc:  # noqa: BLE001
        log(f"   ⚠ não consegui clicar no ▶: {str(exc)[:120]}")
        return None
    fim = time.time() + espera
    achado = None
    while time.time() < fim and not achado:
        page.wait_for_timeout(250)
        if len(ouvidos) > antes:
            achado = ouvidos[-1]
            break
        novos = [s for s in (page.eval_on_selector_all("audio", "els => els.map(e => e.src)") or []) if s not in audios_antes]
        novos = [s for s in novos if PS.MP3_RE.search(s or "")]
        if novos:
            achado = novos[-1]
    try:  # pausa (clica de novo no mesmo botão)
        linha.locator(SEL_PLAY).first.click(timeout=2000)
    except Exception:  # noqa: BLE001
        pass
    return achado


def baixar(page, ctx, url: str, destino: str) -> int:
    """Baixa pela própria página (como o player do site faz — mesmos cookies/origem); se não der, direto."""
    corpo = b""
    try:
        b64 = page.evaluate("""async (u) => {
            const r = await fetch(u, {credentials: 'omit'}); if (!r.ok) return null;
            const b = new Uint8Array(await r.arrayBuffer()); let s = '';
            for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
            return btoa(s);
        }""", url)
        if b64:
            import base64
            corpo = base64.b64decode(b64)
    except Exception:  # noqa: BLE001
        corpo = b""
    if len(corpo) < 1000:
        r = ctx.request.get(url, headers={"Referer": "https://pixabay.com/"}, timeout=60000)
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status}")
        corpo = r.body()
    if len(corpo) < 1000:
        raise RuntimeError("arquivo vazio/pequeno demais")
    with open(destino, "wb") as f:
        f.write(corpo)
    return len(corpo)


# ------------------------------------------------------------------ depois de baixar
def processar(meta: Dict[str, Any], pasta: str, usar_ia: bool) -> None:
    mp3 = meta["arquivo_mp3"]
    m = PS.medir(mp3)
    meta.update(dur_original=m["dur"])
    cortado = os.path.splitext(mp3)[0] + "_cortado.m4a"
    f = PS.cortar_silencio(mp3, cortado)
    meta.update({k: f[k] for k in ("dur", "inicio_som", "pico", "fim_som", "nivel_db", "corte_de", "corte_ate")})
    meta["arquivo_cortado"] = cortado
    if meta.get("onde"):  # o que a forma de onda do Pixabay dizia, em segundos (pra comparar com o corte de verdade)
        meta["onda_em_segundos"] = {k: round(v * m["dur"], 2) for k, v in meta["onde"].items() if k != "forca"}
    png = os.path.splitext(mp3)[0] + "_espectro.png"
    try:
        meta["espectrograma"] = PS.espectrograma(cortado, png)
    except Exception as exc:  # noqa: BLE001
        log(f"   ⚠ espectrograma: {exc}")
        png = None
    if usar_ia:
        ficha = PS.ficha_ia(meta, png)
        if ficha:
            meta["ficha"] = ficha
            log(f"   🤖 {ficha['nome']} — {ficha['descricao'][:110]}")
        else:
            log("   🤖 a IA não respondeu (desligada / sem crédito / recurso 'sons_pixabay' desligado nas Configurações)")


def salvar_catalogo(pasta: str, itens: List[Dict[str, Any]]) -> None:
    cam = os.path.join(pasta, "catalogo.json")
    velho = []
    if os.path.isfile(cam):
        try:
            velho = json.load(open(cam, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            velho = []
    por_id = {str(x.get("id")): x for x in velho}
    for x in itens:
        por_id[str(x.get("id"))] = {k: v for k, v in x.items() if k != "onda"}
    tudo = list(por_id.values())
    json.dump(tudo, open(cam, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    base = [PS.item_da_base(x, os.path.relpath(x["arquivo_cortado"], pasta).replace("\\", "/"))
            for x in tudo if x.get("arquivo_cortado") and os.path.isfile(x["arquivo_cortado"])]
    json.dump(base, open(os.path.join(pasta, "base_sons.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log(f"\n📒 {cam} — {len(tudo)} som(ns) no catálogo · base_sons.json com {len(base)}")


# ------------------------------------------------------------------ principal
def rodar(args, preparar_ctx=None) -> int:
    """preparar_ctx(ctx): só pros testes (simular o site sem internet)."""
    pasta = os.path.abspath(args.pasta)
    os.makedirs(pasta, exist_ok=True)

    if args.html:  # 🧪 só lê um HTML salvo
        r = PS.ler_resultados(open(args.html, encoding="utf-8", errors="replace").read())
        for x in r:
            log(f"• {x['id']}  {x['titulo']}  — {x['autor']}  · {', '.join(x['tags'])}  · ❤ {x['curtidas']}"
                + (f"  · som em {x['onde']['inicio']:.0%}–{x['onde']['fim']:.0%} (pico {x['onde']['pico']:.0%})" if x["onde"] else "  · (sem forma de onda)")
                + (f"\n    🎵 {x['mp3']}" if x["mp3"] else ""))
        log(f"\n{len(r)} som(ns) lidos. .mp3 que já estavam na página: {len(PS.mp3s_soltos(open(args.html, encoding='utf-8', errors='replace').read()))}")
        return 0 if r else 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("❌ Playwright não está instalado: pip install playwright  e  python -m playwright install chromium")
        return 2

    todos: List[Dict[str, Any]] = []
    termos = [t for t in (getattr(args, "termos", None) or [args.termo]) if t]
    with sync_playwright() as p:
        opc: Dict[str, Any] = dict(headless=bool(args.oculto), accept_downloads=True, locale="pt-BR",
                                   viewport={"width": 1280, "height": 900},
                                   args=["--mute-audio", "--autoplay-policy=no-user-gesture-required",
                                         "--disable-blink-features=AutomationControlled"])
        if args.chrome:
            opc["channel"] = "chrome"
        ctx = p.chromium.launch_persistent_context(os.path.join(pasta, "_perfil"), **opc)
        if preparar_ctx:
            preparar_ctx(ctx)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ouvidos: List[str] = []
        page.on("request", lambda req: ouvidos.append(req.url) if PS.MP3_RE.search(req.url or "") and req.url not in ouvidos else None)
        try:
            for n_t, termo in enumerate(termos):  # 🔊 v84_305: vários termos na MESMA aba (o navegador abre uma vez só)
                if n_t:
                    page.wait_for_timeout(800)
                for pag in range(1, args.paginas + 1):
                    url = PS.url_busca(termo, pag)
                    log(f"\n🔎 página {pag}: {url}")
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    if not esperar_resultados(page):
                        log("   nenhum som nesta página (ou a verificação não foi resolvida) — parei")
                        break
                    rolar_ate_o_fim(page)
                    linhas = PS.ler_resultados(page.content())
                    log(f"   {len(linhas)} som(ns) na página")
                    if not linhas:
                        break
                    boot = mp3s_do_bootstrap(page, [x["id"] for x in linhas])
                    if boot:
                        log(f"   📦 o JSON da página trouxe {len(boot)} link(s) .mp3")
                    for i, x in enumerate(linhas[: args.limite]):
                        log(f"\n🎵 {x['titulo']}  ({x['autor']}) — {x['pagina']}")
                        x["busca"], x["pagina_busca"] = termo, pag
                        x["mp3"] = x.get("mp3") or boot.get(x["id"] or "") or mp3_clicando(page, i, ouvidos) or ""
                        if not x["mp3"]:
                            log("   ⚠ não achei o .mp3 desse")
                            todos.append(x)
                            continue
                        log(f"   🔗 {x['mp3']}")
                        if args.sem_baixar:
                            todos.append(x)
                            continue
                        destino = os.path.join(pasta, f"{x['id']}_{PS.slug(x['titulo'])}.mp3")
                        try:
                            if not os.path.isfile(destino):
                                n = baixar(page, ctx, x["mp3"], destino)
                                log(f"   ⬇ baixado ({n // 1024} KB)")
                            x["arquivo_mp3"] = destino
                            processar(x, pasta, args.ia)
                            log(f"   ✂ {x['dur_original']:.2f} s → {x['dur']:.2f} s (corte {x['corte_de']:.2f}–{x['corte_ate']:.2f} s, pico em {x['pico']:.2f} s)"
                                + (f" · a onda do Pixabay dizia {x['onda_em_segundos']}" if x.get("onda_em_segundos") else ""))
                        except Exception as exc:  # noqa: BLE001
                            log(f"   ❌ {exc}")
                        todos.append(x)
                        page.wait_for_timeout(600)  # sem pressa: não martelar o site
        finally:
            ctx.close()
    salvar_catalogo(pasta, todos)
    ok = sum(1 for x in todos if x.get("arquivo_cortado"))
    log(f"✅ {ok} de {len(todos)} som(ns) baixados e cortados em {pasta}")
    return 0 if ok or args.sem_baixar else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Teste: buscar e baixar efeitos sonoros do Pixabay")
    ap.add_argument("termo", nargs="?", default="whoosh tall")
    ap.add_argument("--paginas", type=int, default=1)
    ap.add_argument("--limite", type=int, default=5, help="quantos sons baixar por página")
    ap.add_argument("--pasta", default=os.path.join(AQUI, "pixabay_sons"))
    ap.add_argument("--oculto", action="store_true", help="sem janela (a Cloudflare costuma barrar)")
    ap.add_argument("--chrome", action="store_true", help="usar o Google Chrome instalado")
    ap.add_argument("--ia", action="store_true", help="a IA descreve cada som")
    ap.add_argument("--sem-baixar", action="store_true", help="só listar os links")
    ap.add_argument("--html", help="só ler um HTML salvo da busca (sem navegador)")
    return rodar(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
