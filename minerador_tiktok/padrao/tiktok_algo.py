"""
tiktok_algo.py (padrão do BestEditor, v84_288) — o que o minerador.py usa pra andar pelo feed "Para você" do TikTok WEB.

O site usa ESTE arquivo quando não acha o seu próprio tiktok_algo.py no computador (o seu, se existir, tem prioridade).

O que faz: abre o feed, fecha os avisos (cookies, login, escolha de interesses), lê os números do vídeo que está na tela,
abre os comentários e lê os principais, passa pro próximo vídeo com a seta ↓ — num ritmo de pessoa assistindo.
Captcha: NÃO tenta burlar — espera VOCÊ resolver na janela do navegador (por isso o navegador fica visível por padrão).

O TikTok muda a página de vez em quando. Se parar de ler algo (curtidas, comentários…), ajuste os seletores em SELETORES
abaixo — cada item é uma lista: o primeiro que existir na página é o usado.
"""
import os
import random
import re
import time

URL_FEED = os.environ.get("TIKTOK_FEED_URL") or "https://www.tiktok.com/foryou"

SELETORES = {
    "item": ['article[data-e2e="recommend-list-item-container"]', 'div[data-e2e="recommend-list-item-container"]',
             'article', 'section[data-e2e="feed-video"]'],
    "curtidas": ['[data-e2e="like-count"]', '[data-e2e="browse-like-count"]'],
    "comentarios": ['[data-e2e="comment-count"]', '[data-e2e="browse-comment-count"]'],
    "salvos": ['[data-e2e="undefined-count"]', '[data-e2e="favorite-count"]', '[data-e2e="collect-count"]'],
    "compartilh": ['[data-e2e="share-count"]'],
    "autor": ['[data-e2e="video-author-uniqueid"]', '[data-e2e="video-author-nickname"]', 'a[href^="/@"] h3', 'a[href^="/@"]'],
    "descricao": ['[data-e2e="video-desc"]', '[data-e2e="browse-video-desc"]'],
    "botao_comentarios": ['[data-e2e="comment-icon"]', 'button[aria-label*="omment"]', 'button[aria-label*="oment"]'],
    "comentario_item": ['[data-e2e="comment-level-1"]'],
    "comentario_like": ['[data-e2e="comment-like-count"]'],
    "comentario_usuario": ['[data-e2e="comment-username-1"]'],
    "comentario_respostas": ['[data-e2e="view-more-1"]'],
    "captcha": ['#captcha-verify-container-main-page', '#captcha_container', '.captcha-verify-container',
                'div[class*="captcha_verify"]', 'iframe[src*="captcha"]'],
    "fechar_modal": ['[data-e2e="modal-close-inner-button"]', '[data-e2e="modal-close-button"]', 'div[role="dialog"] button[aria-label*="lose"]',
                     'div[role="dialog"] button[aria-label*="echar"]'],
}

# ----------------------------------------------------------------------------------------------- JS
# ativo(sel): o elemento `sel` DENTRO do vídeo que está no meio da tela (o feed tem vários carregados ao mesmo tempo)
JS_HELPERS = """
const __S = %s;
const __q = (raiz, lista) => { for (const s of lista) { const e = raiz.querySelector(s); if (e) return e; } return null; };
const __itemAtivo = () => {
  const meio = innerHeight / 2; let melhor = null, dist = 1e9;
  for (const s of __S.item) {
    const els = [...document.querySelectorAll(s)].filter(e => e.querySelector('video'));
    for (const e of els) { const r = e.getBoundingClientRect(); if (r.height < 100) continue;
      const d = Math.abs((r.top + r.bottom) / 2 - meio); if (d < dist) { dist = d; melhor = e; } }
    if (melhor) return melhor;
  }
  const vs = [...document.querySelectorAll('video')]; let mv = null, md = 1e9;
  for (const v of vs) { const r = v.getBoundingClientRect(); const d = Math.abs((r.top + r.bottom) / 2 - meio); if (r.height > 100 && d < md) { md = d; mv = v; } }
  return mv ? (mv.closest('article,section,div[data-e2e]') || mv.parentElement) : null;
};
const ativo = (sel) => { const it = __itemAtivo(); if (!it) return null; if (sel === 'video') return it.querySelector('video');
  return __S[sel] ? __q(it, __S[sel]) : it.querySelector(sel); };
""".replace("%s", "__SELETORES__")

JS_EXPANDIR_DESC = "() => {" + JS_HELPERS + """
  const d = ativo('descricao'); if (!d) return 0;
  const b = [...(d.parentElement || d).querySelectorAll('button,span')].find(x => /^(more|mais|ver mais|\\.\\.\\.more)$/i.test((x.innerText || '').trim()));
  if (b) { b.click(); return 1; } return 0; }"""

JS_EXTRAIR_VIDEO = "() => {" + JS_HELPERS + """
  const it = __itemAtivo(); const v = it ? it.querySelector('video') : null;
  const txt = (k) => { const e = ativo(k); return e ? (e.innerText || e.textContent || '').trim() : ''; };
  let vid = null, autorHref = null;
  if (it) {
    const a = it.querySelector('a[href*="/video/"]'); if (a) { const m = a.getAttribute('href').match(/@([^/?]+)\\/video\\/(\\d+)/); if (m) { vid = m[2]; autorHref = '/@' + m[1]; } }
    if (!vid) { const e = it.querySelector('[id*="xgwrapper"], [id^="one-column-item"], [data-e2e="feed-video"]');
      const m = e && (e.id || '').match(/(\\d{15,})/); if (m) vid = m[1]; }
    if (!vid) { const m = (it.innerHTML.match(/\\/video\\/(\\d{15,})/) || it.innerHTML.match(/"(\\d{18,20})"/)); if (m) vid = m[1]; }
    if (!autorHref) { const a2 = it.querySelector('a[href^="/@"]'); if (a2) autorHref = a2.getAttribute('href').split('?')[0].replace(/\\/video\\/.*/, ''); }
  }
  if (!vid) { const m = location.pathname.match(/\\/video\\/(\\d+)/); if (m) vid = m[1]; }
  const descEl = ativo('descricao');
  const tags = descEl ? [...descEl.querySelectorAll('a[href*="/tag/"]')].map(a => (a.innerText || '').replace('#', '').trim()).filter(Boolean) : [];
  const barra = it ? [...it.querySelectorAll('div,span')].map(e => (e.innerText || '').trim()).find(t => /^\\d{1,2}:\\d{2}\\s*\\/\\s*\\d{1,2}:\\d{2}$/.test(t)) : null;
  return { video_id: vid, autor_nome: txt('autor').split('\\n')[0], autor_href: autorHref,
    curtidas: txt('curtidas'), comentarios: txt('comentarios'), salvos: txt('salvos'), compartilh: txt('compartilh'),
    descricao: descEl ? descEl.innerText.trim() : '', hashtags: tags, tempo_barra: barra || '',
    duracao_tag: v && isFinite(v.duration) ? v.duration : null };
}"""

JS_CAPTCHA = "() => { const S = __SELETORES__; for (const s of S.captcha) { const e = document.querySelector(s); if (e) { const r = e.getBoundingClientRect(); if (r.width > 50 && r.height > 50) return true; } } return false; }"


def _js(s):
    import json
    return s.replace("__SELETORES__", json.dumps(SELETORES))


JS_HELPERS = _js(JS_HELPERS)
JS_EXPANDIR_DESC = _js(JS_EXPANDIR_DESC)
JS_EXTRAIR_VIDEO = _js(JS_EXTRAIR_VIDEO)
JS_CAPTCHA = _js(JS_CAPTCHA)


# ----------------------------------------------------------------------------------------------- ritmo
def pausa(a, b):
    time.sleep(random.uniform(a, b))


# ----------------------------------------------------------------------------------------------- números
def num(s):
    """'12.3K' / '1,2 mi' / '3,4 mil' / '1.2M' / '980' → inteiro (0 se não der)."""
    t = str(s or "").strip().lower().replace(" ", " ")
    if not t:
        return 0
    m = re.search(r"([\d.,]+)\s*(mil|mi|bi|k|m|b)?", t)
    if not m:
        return 0
    n, suf = m.group(1), (m.group(2) or "")
    if suf:
        n = n.replace(",", ".")
        if n.count(".") > 1:
            n = n.replace(".", "", n.count(".") - 1)
    else:
        n = n.replace(",", "").replace(".", "")
    try:
        v = float(n)
    except ValueError:
        return 0
    return int(v * {"k": 1e3, "mil": 1e3, "m": 1e6, "mi": 1e6, "b": 1e9, "bi": 1e9}.get(suf, 1))


def duracao_da_barra(texto):
    """'00:05 / 00:18' → 18 (a duração total)."""
    m = re.search(r"/\s*(\d{1,2}):(\d{2})", str(texto or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


# ----------------------------------------------------------------------------------------------- avisos e captcha
def _clicar_texto(page, textos, escopo="button, div[role=button], a"):
    for t in textos:
        try:
            el = page.locator(escopo).filter(has_text=re.compile(rf"^\s*{t}\s*$", re.I)).first
            if el.count() and el.is_visible():
                el.click(timeout=2000)
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def _fechar_avisos(page):
    _clicar_texto(page, ["Allow all", "Accept all", "Permitir todos", "Aceitar todos", "Decline optional cookies", "Recusar cookies opcionais"])
    for s in SELETORES["fechar_modal"]:
        try:
            el = page.locator(s).first
            if el.count() and el.is_visible():
                el.click(timeout=1500)
        except Exception:  # noqa: BLE001
            pass
    # "Continuar como convidado" no aviso de login
    _clicar_texto(page, ["Continue as guest", "Continuar como convidado"])


def onboarding(page, opcoes=None):
    """Abre o feed 'Para você' e fecha os avisos do começo."""
    page.goto(URL_FEED, wait_until="domcontentloaded", timeout=60000)
    pausa(3, 5)
    checar_captcha(page)
    _fechar_avisos(page)
    try:
        page.mouse.move(683, 425)
        page.mouse.click(683, 425)  # foco no feed (as setas passam o vídeo)
        page.keyboard.press("Escape")
    except Exception:  # noqa: BLE001
        pass
    pausa(1, 2)


def tratar_interesses(page, interesses):
    """O popup 'Escolha seus interesses': marca os do config (precisa de 3) e avança; sem 3, fecha/pula."""
    try:
        pop = page.locator("div[role=dialog]").filter(has_text=re.compile(r"interest|interesse", re.I)).first
        if not (pop.count() and pop.is_visible()):
            return
    except Exception:  # noqa: BLE001
        return
    if len(interesses or []) >= 3:
        for i in interesses:
            try:
                b = pop.locator("button, div[role=button], span").filter(has_text=re.compile(rf"^\s*{re.escape(i)}\s*$", re.I)).first
                if b.count():
                    b.click(timeout=1500)
                    pausa(0.3, 0.7)
            except Exception:  # noqa: BLE001
                pass
        if _clicar_texto(page, ["Next", "Próximo", "Avançar", "Continue", "Continuar", "Done", "Concluído"]):
            pausa(1, 2)
            return
    if not _clicar_texto(page, ["Skip", "Pular", "Ignorar"]):
        try:
            page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
    pausa(0.8, 1.5)


def checar_captcha(page, avisar_a_cada=30):
    """Tem captcha na tela? Espera VOCÊ resolver (não tenta burlar). Com o navegador escondido, avisa pra rodar visível."""
    t0, avisou = time.time(), 0.0
    while True:
        try:
            tem = page.evaluate(JS_CAPTCHA)
        except Exception:  # noqa: BLE001
            tem = False
        if not tem:
            if avisou:
                print("     ✅ captcha resolvido, continuando")
            return
        if time.time() - avisou > avisar_a_cada:
            print("     🧩 apareceu um captcha — resolva na janela do navegador (se o navegador estiver escondido, pare e rode com 👁 mostrar o navegador)")
            avisou = time.time()
        if time.time() - t0 > 20 * 60:
            raise RuntimeError("captcha sem resolver há 20 minutos")
        time.sleep(2)


# ----------------------------------------------------------------------------------------------- feed
def proximo_video(page):
    """Passa pro próximo vídeo (seta ↓, como uma pessoa) e espera ele aparecer."""
    try:
        page.keyboard.press("Escape")  # fecha o painel de comentários se ficou aberto
        page.keyboard.press("ArrowDown")
    except Exception:  # noqa: BLE001
        try:
            page.mouse.wheel(0, 900)
        except Exception:  # noqa: BLE001
            pass
    pausa(1.2, 2.2)


def coletar_comentarios(page, n=40, rolagens=8):
    """Abre os comentários do vídeo da tela e lê os primeiros (o TikTok já mostra os mais relevantes no topo)."""
    out = []
    try:
        abriu = page.evaluate("() => {" + JS_HELPERS + " const b = ativo('botao_comentarios'); if (b) { b.click(); return true; } return false; }")
        if not abriu:
            return out
        pausa(1.5, 2.5)
        checar_captcha(page)
        js_ler = "() => { const S = " + _js("__SELETORES__") + """;
          const q = (r, l) => { for (const s of l) { const e = r.querySelector(s); if (e) return e; } return null; };
          let itens = []; for (const s of S.comentario_item) { itens = [...document.querySelectorAll(s)]; if (itens.length) break; }
          return itens.map(e => { const box = e.closest('div[class*="CommentItem"], div[class*="DivCommentItem"], div[class*="comment-item"]') || e.parentElement.parentElement || e;
            const like = q(box, S.comentario_like), user = q(box, S.comentario_usuario), mais = q(box, S.comentario_respostas);
            const m = mais ? (mais.innerText || '').match(/(\\d[\\d.,]*\\s*[KkMm]?)/) : null;
            return { texto: (e.innerText || '').trim(), curtidas: like ? like.innerText.trim() : '0', usuario: user ? user.innerText.trim() : '',
                     respostas: m ? m[1] : '0' }; }); }"""
        vistos = set()
        for _ in range(rolagens):
            for c in page.evaluate(js_ler) or []:
                k = c["texto"][:120]
                if c["texto"] and k not in vistos:
                    vistos.add(k)
                    c["curtidas"], c["respostas"] = num(c["curtidas"]), num(c["respostas"])
                    out.append(c)
            if len(out) >= n:
                break
            try:  # rola a lista de comentários (não o feed)
                page.evaluate("""() => { const e = document.querySelector('[data-e2e="comment-level-1"]');
                  let p = e; while (p && p !== document.body) { if (p.scrollHeight > p.clientHeight + 20 && getComputedStyle(p).overflowY !== 'visible') { p.scrollBy(0, 700); return; } p = p.parentElement; } }""")
            except Exception:  # noqa: BLE001
                break
            pausa(0.8, 1.4)
    except Exception as e:  # noqa: BLE001
        print(f"     (comentários: {e})")
    finally:
        try:
            page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
    return out[:n]
