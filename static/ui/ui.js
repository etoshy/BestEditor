/* ==========================================================================
   BestEditor — interface (v84_161)
   1. modo claro/escuro (botão no topo) — no escuro recolore os estilos antigos
      das páginas (inline e <style>) mantendo o matiz de cada cor
   2. emojis → ícones do Font Awesome (static/ui/icones.js)
   3. menu lateral (grupos que recolhem, modo só ícones, gaveta no celular)
   4. seções numeradas que recolhem (triângulo) + "concluída" + índice lateral
   5. saldo do Claude ao lado do sininho
   6. lembrar a última escolha (voz, idioma…) pros próximos usos
   ========================================================================== */
(function () {
  'use strict';
  const D = document, H = D.documentElement;
  const LS = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (_) { return d; } },
    set(k, v) { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (_) { /* sem storage */ } },
  };
  const MODO = (D.currentScript && D.currentScript.dataset.modo) || 'completo';  // "minimo" = Estúdio (só ícones)
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* ======================================================================
     1. cores — recolorir pro modo escuro
     ====================================================================== */
  const NOMES = { white: [255, 255, 255], black: [0, 0, 0], red: [255, 0, 0], green: [0, 128, 0], blue: [0, 0, 255], gray: [128, 128, 128],
    grey: [128, 128, 128], silver: [192, 192, 192], yellow: [255, 255, 0], orange: [255, 165, 0], purple: [128, 0, 128], navy: [0, 0, 128],
    whitesmoke: [245, 245, 245], gainsboro: [220, 220, 220], lightgray: [211, 211, 211], lightgrey: [211, 211, 211], darkgray: [169, 169, 169],
    ivory: [255, 255, 240], beige: [245, 245, 220], linen: [250, 240, 230], snow: [255, 250, 250], aliceblue: [240, 248, 255],
    lightyellow: [255, 255, 224], lightblue: [173, 216, 230], lavender: [230, 230, 250], honeydew: [240, 255, 240], mintcream: [245, 255, 250],
    seashell: [255, 245, 238], darkred: [139, 0, 0], darkgreen: [0, 100, 0], maroon: [128, 0, 0], teal: [0, 128, 128], olive: [128, 128, 0] };
  const RX_COR = /rgba?\([^)]*\)|#[0-9a-f]{3,8}\b|\b(?:white|black|red|green|blue|gr[ae]y|silver|yellow|orange|purple|navy|whitesmoke|gainsboro|light(?:gr[ae]y|yellow|blue)|darkgray|ivory|beige|linen|snow|aliceblue|lavender|honeydew|mintcream|seashell|darkred|darkgreen|maroon|teal|olive)\b/gi;

  function lerCor(t) {
    t = String(t).trim().toLowerCase();
    let m;
    if ((m = t.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)$/))) {
      const a = m[4] == null ? 1 : (m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]));
      return [+m[1], +m[2], +m[3], a];
    }
    if (t[0] === '#') {
      let h = t.slice(1);
      if (h.length === 3 || h.length === 4) h = h.split('').map(c => c + c).join('');
      if (h.length !== 6 && h.length !== 8) return null;
      return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1];
    }
    if (NOMES[t]) return NOMES[t].concat(1);
    return null;
  }
  function hsl(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
    if (mx === mn) return [0, 0, l];
    const d = mx - mn, s = l > .5 ? d / (2 - mx - mn) : d / (mx + mn);
    const h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [h * 60, s, l];
  }
  function rgbDe(h, s, l) {
    h = ((h % 360) + 360) % 360 / 360;
    if (!s) { const v = Math.round(l * 255); return [v, v, v]; }
    const q = l < .5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
    const f = (t) => { t = (t + 1) % 1; return t < 1 / 6 ? p + (q - p) * 6 * t : t < .5 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p; };
    return [Math.round(f(h + 1 / 3) * 255), Math.round(f(h) * 255), Math.round(f(h - 1 / 3) * 255)];
  }
  const txtCor = (rgb, a) => a < 1 ? `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${+a.toFixed(3)})` : `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
  const HUE_TEMA = 228;

  // fundo claro → superfície escura do mesmo matiz; fundos escuros/coloridos médios ficam
  function corFundo(c) {
    const [h, s, l] = hsl(c[0], c[1], c[2]);
    if (l < .55 || c[3] === 0) return null;
    let nl = .175 + (1 - l) * .4, nh = h, ns;
    if (s < .1) { nh = HUE_TEMA; ns = .14; } else { ns = Math.min(s, .7) * .5; nl += .015; }
    return txtCor(rgbDe(nh, ns, nl), c[3]);
  }
  // texto escuro → claro (cinzas mantêm a hierarquia: o mais escuro vira o mais claro)
  function corTexto(c) {
    const [h, s, l] = hsl(c[0], c[1], c[2]);
    if (s < .15) { if (l > .8) return null; return txtCor(rgbDe(HUE_TEMA, Math.min(s, .08) + .04, .92 - l * .42), c[3]); }
    if (l > .6) return null;
    return txtCor(rgbDe(h, Math.min(s, .85), .93 - l * .4), c[3]);
  }
  function corBorda(c) {
    const [h, s, l] = hsl(c[0], c[1], c[2]);
    if (l < .5 || c[3] === 0) return null;
    let nh = h, ns;
    const nl = .24 + (1 - l) * .3;
    if (s < .1) { nh = HUE_TEMA; ns = .12; } else { ns = Math.min(s, .6) * .5; }
    return txtCor(rgbDe(nh, ns, nl), c[3]);
  }
  const CACHE = { f: new Map(), t: new Map(), b: new Map() };
  function trocarCores(valor, tipo) {
    const fn = tipo === 'f' ? corFundo : tipo === 't' ? corTexto : corBorda, cache = CACHE[tipo];
    let mudou = false;
    const novo = String(valor).replace(RX_COR, (m) => {
      if (cache.has(m)) { const r = cache.get(m); if (r) mudou = true; return r || m; }
      const c = lerCor(m), r = c ? fn(c) : null;
      cache.set(m, r); if (r) mudou = true; return r || m;
    });
    return mudou ? novo : null;
  }
  const P_FUNDO = ['background-color', 'background-image'];
  const P_BORDA = ['border-top-color', 'border-right-color', 'border-bottom-color', 'border-left-color', 'outline-color', 'text-decoration-color', 'column-rule-color'];

  // recolore uma declaração (estilo inline ou regra de <style>); devolve a lista do que trocou
  function recolorirDecl(st, pular) {
    const feitas = [];
    const por = (prop, tipo) => {
      if (pular && pular.has(prop)) return false;  // já é cor que o tema pôs (não recolore de novo)
      const v = st.getPropertyValue(prop);
      if (!v || v === 'initial' || v === 'inherit' || v.includes('var(')) return false;
      if (prop === 'background-image' && !/gradient/i.test(v)) return false;
      const n = trocarCores(v, tipo);
      if (n && n !== v) { feitas.push([prop, v, n, st.getPropertyPriority(prop)]); return true; }
      return false;
    };
    let fundoProprio = false, fundoTrocado = false;
    for (const p of P_FUNDO) {
      const v = st.getPropertyValue(p);
      if (v && v !== 'transparent' && v !== 'none' && v !== 'initial' && !v.includes('var(')) fundoProprio = true;
      if (por(p, 'f')) fundoTrocado = true;
    }
    // fundo colorido mantido (botão roxo, faixa amarela…): o texto dele fica como está
    if (!(fundoProprio && !fundoTrocado)) por('color', 't');
    for (const p of P_BORDA) por(p, 'b');
    for (const [prop, , n, pri] of feitas) { try { st.setProperty(prop, n, pri); } catch (_) { /* ignora */ } }
    return feitas;
  }

  const REG_EL = new WeakMap();   // elemento → [[prop, original, novo, pri]]
  const ELS = new Set();          // pra desfazer (WeakMap não itera)
  let REG_FOLHAS = [];            // [[CSSStyleDeclaration, prop, original, novo, pri]]
  let FOLHAS_FEITAS = new WeakSet();
  const escuro = () => H.dataset.tema === 'escuro';

  function recolorirEl(el) {
    if (!el.getAttribute || !el.getAttribute('style') || el.closest('[data-ui-base],svg')) return;
    const ant = REG_EL.get(el);
    if (ant) {  // já recolorido: só mexe nas cores que o JS da página pôs depois
      const mantidas = ant.filter(([p, , n]) => el.style.getPropertyValue(p) === n);
      const extra = recolorirDecl(el.style, new Set(mantidas.map(x => x[0])));
      if (extra.length || mantidas.length !== ant.length) REG_EL.set(el, mantidas.concat(extra));
      return;
    }
    const feitas = recolorirDecl(el.style);
    if (feitas.length) { REG_EL.set(el, feitas); ELS.add(el); }
  }
  function regras(lista, fn) {
    for (const r of Array.from(lista || [])) {
      if (r.style && r.selectorText) fn(r);
      if (r.cssRules) regras(r.cssRules, fn);
    }
  }
  function recolorirFolha(sh) {
    if (FOLHAS_FEITAS.has(sh)) return;
    const dono = sh.ownerNode;
    if (dono && (dono.hasAttribute('data-ui-base') || (dono.closest && dono.closest('svg')))) return;
    let lista; try { lista = sh.cssRules; } catch (_) { return; }  // outra origem
    FOLHAS_FEITAS.add(sh);
    regras(lista, (r) => {
      if (/^\s*(html|:root)\b/.test(r.selectorText)) return;
      for (const [p, o, n, pri] of recolorirDecl(r.style)) REG_FOLHAS.push([r.style, p, o, n, pri]);
    });
  }
  function recolorirTudo() {
    for (const sh of Array.from(D.styleSheets)) recolorirFolha(sh);
    D.querySelectorAll('[style]').forEach(recolorirEl);
  }
  function desfazerCores() {
    for (const [st, p, o, n, pri] of REG_FOLHAS) { try { if (st.getPropertyValue(p) === n) st.setProperty(p, o, pri); } catch (_) { /* */ } }
    REG_FOLHAS = [];
    FOLHAS_FEITAS = new WeakSet();
    for (const el of ELS) {
      const reg = REG_EL.get(el); if (!reg) continue;
      for (const [p, o, n, pri] of reg) if (el.style.getPropertyValue(p) === n) el.style.setProperty(p, o, pri);
      REG_EL.delete(el);
    }
    ELS.clear();
  }

  function aplicarTema(t, salvar) {
    const antes = H.dataset.tema;
    H.dataset.tema = t;
    if (salvar) LS.set('ui-tema', t);
    if (MODO !== 'minimo') {
      if (t === 'escuro') recolorirTudo(); else if (antes === 'escuro') desfazerCores();
    }
    D.querySelectorAll('[data-ui-tema-ico]').forEach(i => { i.className = 'fa-solid ' + (t === 'escuro' ? 'fa-sun' : 'fa-moon'); });
    D.querySelectorAll('[data-ui-tema-btn]').forEach(b => { b.title = t === 'escuro' ? 'Mudar para o modo claro' : 'Mudar para o modo escuro'; });
  }

  /* ======================================================================
     2. emojis → ícones
     ====================================================================== */
  const MAPA = window.UI_ICONES || {};
  // setas e formas que são tipografia (ficam como texto)
  const MANTER = new Set('←→↑↓↔↕↖↗↘↙↳↪▾▸▴◂▭◻◼▦▤▥▯◌○◐◤◥◣◢⌈⌉▪▫♂♀☰©®™‼⁉'.split(''));
  const RX_EMO = /(?:\p{Extended_Pictographic}|[←-⇿⌀-⏿■-◿☀-➿⬀-⯿〰〽])(?:️|︎|⃣|[\u{1F3FB}-\u{1F3FF}]|‍(?:\p{Extended_Pictographic}|[♀♂])️?)*|[\u{1F1E6}-\u{1F1FF}]{2}/gu;
  const RX_TEM = /[←-⯿〰〽\u{1F000}-\u{1FAFF}]/u;
  const PULAR = 'script,style,textarea,select,option,svg,noscript,canvas,[contenteditable=""],[contenteditable="true"],.emo-txt,.no-ico,[data-no-ico]';

  function classeIcone(emo) {
    const base = Array.from(emo.replace(/[️︎‍⃣]|[\u{1F3FB}-\u{1F3FF}]/gu, ''))[0] || '';
    let v = MAPA[base];
    if (!v) {
      if (MANTER.has(base)) return 'manter';
      const cp = base.codePointAt(0) || 0;
      if (cp < 0x2600 && !/\p{Extended_Pictographic}/u.test(base)) return 'manter';  // seta/forma tipográfica
      return '';  // some (fica escondido)
    }
    let estilo = 'fa-solid';
    if (v.startsWith('r:')) { estilo = 'fa-regular'; v = v.slice(2); } else if (v.startsWith('b:')) { estilo = 'fa-brands'; v = v.slice(2); }
    return estilo + ' fa-' + v;
  }
  const semEmoji = (s) => String(s).replace(RX_EMO, (m) => classeIcone(m) === 'manter' ? m : '').replace(/^\s+/, '').replace(/\s{2,}/g, ' ');

  function iconizarTexto(no) {
    const t = no.data;
    if (!t || !RX_TEM.test(t)) return;
    const pai = no.parentNode;
    if (!pai || (pai.closest && pai.closest(PULAR))) return;
    RX_EMO.lastIndex = 0;
    let m, ult = 0, frag = null;
    while ((m = RX_EMO.exec(t))) {
      const cls = classeIcone(m[0]);
      if (cls === 'manter') continue;
      frag = frag || D.createDocumentFragment();
      if (m.index > ult) frag.appendChild(D.createTextNode(t.slice(ult, m.index)));
      if (cls) { const i = D.createElement('i'); i.className = cls + ' ico'; i.setAttribute('aria-hidden', 'true'); frag.appendChild(i); }
      const s = D.createElement('span'); s.className = 'emo-txt'; s.textContent = m[0]; frag.appendChild(s);
      ult = m.index + m[0].length;
    }
    if (!frag) return;
    if (ult < t.length) frag.appendChild(D.createTextNode(t.slice(ult)));
    pai.replaceChild(frag, no);
  }
  function iconizarAtributos(el) {
    for (const a of ['title', 'placeholder', 'aria-label', 'alt']) {
      const v = el.getAttribute && el.getAttribute(a);
      if (v && RX_TEM.test(v)) { const n = semEmoji(v); if (n !== v) el.setAttribute(a, n); }
    }
    if (el.tagName === 'OPTION' || el.tagName === 'OPTGROUP') {
      if (el.tagName === 'OPTION' && RX_TEM.test(el.text)) { const n = semEmoji(el.text); if (n !== el.text) el.text = n; }
      const lb = el.getAttribute('label'); if (lb && RX_TEM.test(lb)) el.setAttribute('label', semEmoji(lb));
    }
    if (el.tagName === 'INPUT' && /^(button|submit|reset)$/i.test(el.type) && RX_TEM.test(el.value)) el.value = semEmoji(el.value);
  }
  function iconizar(raiz) {
    if (!raiz) return;
    if (raiz.nodeType === 3) { iconizarTexto(raiz); return; }
    if (raiz.nodeType !== 1 && raiz.nodeType !== 9 && raiz.nodeType !== 11) return;
    if (raiz.nodeType === 1) { if (raiz.closest(PULAR) && !/^(SELECT|OPTION|OPTGROUP)$/.test(raiz.tagName)) return; iconizarAtributos(raiz); }
    const w = D.createTreeWalker(raiz, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (RX_TEM.test(n.data) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT) });
    const lista = []; let n; while ((n = w.nextNode())) lista.push(n);
    lista.forEach(iconizarTexto);
    if (raiz.querySelectorAll) raiz.querySelectorAll('[title],[placeholder],[aria-label],option,optgroup,input[type=button],input[type=submit]').forEach(iconizarAtributos);
  }
  function tituloSemEmoji() {  // só troca se mudou: um símbolo que fica (→) fazia o observador do <title> girar pra sempre
    if (!RX_TEM.test(D.title)) return; const n = semEmoji(D.title); if (n !== D.title) D.title = n; }

  /* ======================================================================
     3. menu lateral
     ====================================================================== */
  function montarMenu() {
    const nav = D.querySelector('.app-nav');
    if (!nav) return;
    const fechados = new Set((LS.get('ui-menu-fechados', '') || '').split('|').filter(Boolean));
    nav.querySelectorAll('.grupo').forEach(g => {
      const id = g.dataset.grupo;
      const temAtivo = !!g.querySelector('.item.ativo');
      if (fechados.has(id) && !temAtivo) g.classList.add('fechado');
      const bt = g.querySelector('.grupo-tit');
      bt.addEventListener('click', () => {
        if (H.classList.contains('menu-mini') && innerWidth > 1100) { H.classList.remove('menu-mini'); LS.set('ui-menu-mini', null); g.classList.remove('fechado'); setTimeout(ajustarIndice, 230); return; }
        g.classList.toggle('fechado');
        if (g.classList.contains('fechado')) fechados.add(id); else fechados.delete(id);
        LS.set('ui-menu-fechados', Array.from(fechados).join('|'));
      });
    });
    const ativo = nav.querySelector('.item.ativo');
    if (ativo) setTimeout(() => ativo.scrollIntoView({ block: 'nearest' }), 0);
    const abrir = () => H.classList.add('menu-aberto'), fechar = () => H.classList.remove('menu-aberto');
    D.querySelectorAll('[data-ui-abrir-menu]').forEach(b => b.addEventListener('click', abrir));
    D.querySelectorAll('[data-ui-fechar-menu], .app-veu').forEach(b => b.addEventListener('click', fechar));
    D.querySelectorAll('[data-ui-mini-menu]').forEach(b => b.addEventListener('click', () => {
      H.classList.toggle('menu-mini'); LS.set('ui-menu-mini', H.classList.contains('menu-mini') ? '1' : null);
      setTimeout(ajustarIndice, 230);
    }));
    D.addEventListener('keydown', (e) => { if (e.key === 'Escape') { fechar(); D.body.classList.remove('indice-aberto'); } });
    nav.addEventListener('click', (e) => { if (e.target.closest('a.item') && innerWidth <= 1100) fechar(); });
  }

  /* ======================================================================
     4. seções numeradas + índice lateral
     ====================================================================== */
  const SECOES = [];
  let indiceEl = null, fabEl = null, obsSec = null;
  const caminho = location.pathname;
  const slug = (s) => String(s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40);

  function rotuloDe(h2) {
    const c = h2.cloneNode(true);
    c.querySelectorAll('.sec-desc,.emo-txt,.sec-num,.sec-tri,.sec-check,button,small,[class$="-num"]').forEach(x => x.remove());
    let t = c.textContent.replace(/\s+/g, ' ').trim();
    t = t.replace(/\s*\(.*$/, '').replace(/\s*[—–-]\s.*$/, '').trim() || c.textContent.trim();
    return t.length > 46 ? t.slice(0, 44).trim() + '…' : t;
  }

  function prepararSecao(h2, raiz) {
    let sec = h2.parentElement;
    const filhos = Array.from(sec.children).filter(c => !/^(SCRIPT|STYLE|TEMPLATE)$/.test(c.tagName));
    const ehCartao = sec !== raiz && filhos[0] === h2 && sec.querySelectorAll('h2').length === 1 && !/^(DETAILS|SUMMARY|FORM|LI|TD)$/.test(sec.tagName);
    if (!ehCartao) {
      sec = D.createElement('div');
      sec.className = 'secao-auto';
      h2.parentNode.insertBefore(sec, h2);
      let n = h2;
      while (n) {
        const prox = n.nextSibling;
        sec.appendChild(n);
        if (!prox || (prox.nodeType === 1 && (/^(H1|H2)$/.test(prox.tagName) || (prox.querySelector && prox.querySelector('h1,h2'))))) break;
        n = prox;
      }
    }
    sec.classList.add('sec');
    h2.classList.add('sec-cab');
    h2.dataset.sec = '1';
    // número antigo da página (ry-num, ds-num…) sai: o número passa a ser o da ordem na página
    Array.from(h2.children).forEach(ch => { if (/-num\b/.test(ch.className) || (ch.tagName === 'SPAN' && /^\s*\d+\s*$/.test(ch.textContent))) ch.remove(); });
    Array.from(h2.querySelectorAll('span')).forEach(sp => { if (/font-weight:\s*400/.test(sp.getAttribute('style') || '')) sp.classList.add('sec-desc'); });
    // o título (texto + ícone) vai num bloco só: no celular o botão "concluir" fica na mesma linha
    const tit = D.createElement('span'); tit.className = 'sec-tit';
    Array.from(h2.childNodes).forEach(n => { if (!(n.nodeType === 1 && (n.classList.contains('sec-desc') || n.tagName === 'BUTTON' || n.tagName === 'SMALL'))) tit.appendChild(n); });
    h2.insertBefore(tit, h2.firstChild);
    const rot = rotuloDe(h2);
    const tri = D.createElement('button'); tri.type = 'button'; tri.className = 'sec-tri'; tri.title = 'Recolher / abrir'; tri.innerHTML = '<i class="fa-solid fa-chevron-down"></i>';
    const num = D.createElement('span'); num.className = 'sec-num';
    h2.insertBefore(num, h2.firstChild); h2.insertBefore(tri, num);
    const chk = D.createElement('button'); chk.type = 'button'; chk.className = 'sec-check';
    h2.appendChild(chk);
    if (!sec.id) sec.id = 'sec-' + slug(rot || 'secao');
    const s = { sec, h2, num, chk, rot, chave: sec.id || ('s-' + slug(rot)) };
    tri.addEventListener('click', (e) => { e.stopPropagation(); alternar(s); });
    chk.addEventListener('click', (e) => { e.stopPropagation(); marcarFeita(s, !s.feita); });
    h2.addEventListener('click', (e) => {
      if (e.target.closest('a,button,input,select,textarea,label,summary')) return;
      if (String(window.getSelection && window.getSelection()) !== '') return;
      alternar(s);
    });
    return s;
  }

  const kFeita = (s) => 'ui-feita:' + caminho + ':' + s.chave;
  const kRec = (s) => 'ui-rec:' + caminho + ':' + s.chave;
  function feitaNoServidor(s) {
    const el = s.sec.closest('[data-feito]');  // no próprio cartão ou num invólucro em volta (includes)
    return !!el && (el.dataset.feito === '1' || el.dataset.feito === 'true');
  }
  function estadoFeita(s) {
    const m = LS.get(kFeita(s), null);
    if (m === '1') return true; if (m === '0') return false;
    return feitaNoServidor(s);
  }
  function desenharSecao(s) {
    s.sec.classList.toggle('sec-feita', !!s.feita);
    s.sec.classList.toggle('sec-recolhida', !!s.recolhida);
    s.chk.innerHTML = s.feita ? '<i class="fa-solid fa-circle-check"></i><span class="sc-t">Concluída</span>' : '<i class="fa-regular fa-circle"></i><span class="sc-t">Concluir</span>';
    s.chk.title = s.feita ? 'Marcar como não concluída (abre de novo)' : 'Marcar esta etapa como concluída (ela recolhe)';
    s.num.innerHTML = s.feita ? '<i class="fa-solid fa-check"></i>' : String(s.n || '');
    if (s.link) {
      s.link.classList.toggle('feita', !!s.feita); s.link.classList.toggle('recolhida', !!s.recolhida);
      s.link.querySelector('.in').innerHTML = s.feita ? '<i class="fa-solid fa-check"></i>' : String(s.n || '');
    }
  }
  function alternar(s, forcar) {
    s.recolhida = forcar == null ? !s.recolhida : forcar;
    LS.set(kRec(s), s.recolhida ? '1' : '0');
    desenharSecao(s);
  }
  function marcarFeita(s, v) {
    s.feita = v;
    LS.set(kFeita(s), v === feitaNoServidor(s) ? null : (v ? '1' : '0'));
    LS.set(kRec(s), null);  // volta a seguir o padrão: concluída = recolhida
    s.recolhida = v;
    desenharSecao(s);
    if (v) {  // abre a próxima etapa que falta
      const prox = SECOES.slice(SECOES.indexOf(s) + 1).find(x => !x.feita && x.visivel);
      if (prox && prox.recolhida) alternar(prox, false);
    }
  }

  function montarSecoes() {
    const raiz = D.querySelector('.app-content');
    if (!raiz || raiz.hasAttribute('data-sem-secoes')) return;
    const h2s = Array.from(raiz.querySelectorAll('h2')).filter(h =>
      !h.dataset.sec && !h.closest('.sec,.indice,.topo-painel,template,[data-sem-secao],dialog,[role=dialog]'));
    if (SECOES.length + h2s.length < 2) return;
    h2s.forEach(h => SECOES.push(prepararSecao(h, raiz)));
    SECOES.sort((a, b) => (a.sec.compareDocumentPosition(b.sec) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1);
    SECOES.forEach((s) => {
      if (s.feita == null) {
        s.feita = estadoFeita(s);
        const r = LS.get(kRec(s), null);
        s.recolhida = r === '1' ? true : r === '0' ? false : s.feita;
      }
    });
    // quem chegou pelo link #âncora vê a seção aberta
    if (location.hash) {
      const id = location.hash.slice(1);
      const alvo = SECOES.find(s => s.sec.id === id || (id && s.sec.querySelector('#' + CSS.escape(id))));
      if (alvo) alvo.recolhida = false;
    }
    montarIndice();
    renumerar();
  }

  // só as seções que aparecem contam na numeração (algumas só surgem depois, ex.: ✍️ Roteiro em partes)
  let assinatura = '';
  const aparece = (s) => s.sec.isConnected && s.sec.getClientRects().length > 0;
  function renumerar() {
    let n = 0;
    SECOES.forEach(s => {
      s.visivel = aparece(s);
      if (s.visivel) s.n = ++n;
      if (s.link) s.link.style.display = s.visivel ? '' : 'none';
      desenharSecao(s);
    });
    assinatura = SECOES.map(s => s.visivel ? 1 : 0).join('');
    if (indiceEl) {
      const algum = n >= 2;
      indiceEl.style.display = algum ? '' : 'none'; fabEl.style.display = algum ? '' : 'none';
      D.body.classList.toggle('tem-indice', algum);
    }
  }
  setInterval(() => {
    if (!SECOES.length || D.hidden) return;
    const a = SECOES.map(s => aparece(s) ? 1 : 0).join('');
    if (a !== assinatura) renumerar();
  }, 1200);

  function montarIndice() {
    if (!indiceEl) {
      indiceEl = D.createElement('nav'); indiceEl.className = 'indice'; indiceEl.setAttribute('aria-label', 'Etapas desta página');
      indiceEl.innerHTML = '<div class="ind-caixa"><div class="ind-tit"><i class="fa-solid fa-list-ol"></i><span>Etapas</span>' +
        '<button type="button" data-ind-tudo="1" title="Recolher todas / abrir todas"><i class="fa-solid fa-down-left-and-up-right-to-center"></i></button></div><div class="ind-lista"></div></div>';
      D.body.appendChild(indiceEl);
      fabEl = D.createElement('button'); fabEl.type = 'button'; fabEl.className = 'ind-fab'; fabEl.innerHTML = '<i class="fa-solid fa-list-ol"></i> Etapas';
      fabEl.addEventListener('click', () => D.body.classList.toggle('indice-aberto'));
      D.body.appendChild(fabEl);
      indiceEl.querySelector('[data-ind-tudo]').addEventListener('click', () => {
        const fechar = SECOES.some(s => s.visivel && !s.recolhida);
        SECOES.forEach(s => alternar(s, fechar));
      });
      addEventListener('resize', ajustarIndice);
    }
    const lista = indiceEl.querySelector('.ind-lista');
    lista.innerHTML = '';
    SECOES.forEach(s => {
      const a = D.createElement('a'); a.href = '#' + s.sec.id; a.title = s.rot;
      a.innerHTML = `<span class="in"></span><span class="it">${esc(s.rot)}</span>`;
      a.addEventListener('click', (e) => {
        e.preventDefault();
        if (s.recolhida) alternar(s, false);
        D.body.classList.remove('indice-aberto');
        s.h2.scrollIntoView({ behavior: 'smooth', block: 'start' });
        history.replaceState(null, '', '#' + s.sec.id);
      });
      s.link = a; lista.appendChild(a);
    });
    D.body.classList.add('tem-indice');
    ajustarIndice();
    if (obsSec) obsSec.disconnect();
    const vis = new Map();
    obsSec = new IntersectionObserver((ents) => {
      ents.forEach(e => vis.set(e.target, e.isIntersecting));
      const atual = SECOES.find(s => vis.get(s.sec)) || null;
      SECOES.forEach(s => s.link && s.link.classList.toggle('atual', s === atual));
    }, { rootMargin: '-70px 0px -55% 0px' });
    SECOES.forEach(s => obsSec.observe(s.sec));
  }
  function ajustarIndice() {
    if (!indiceEl) return;
    const w = innerWidth, mini = H.classList.contains('menu-mini');
    const larga = w >= (mini ? 1380 : 1560);
    D.body.classList.toggle('indice-estreito', !larga && w > 760);
    D.body.style.setProperty('--indice-w', w <= 760 ? '0px' : (larga ? '220px' : '52px'));
  }

  /* ======================================================================
     5. saldo do Claude
     ====================================================================== */
  const brl = (v) => 'US$ ' + (Number(v) || 0).toLocaleString('pt-BR', { minimumFractionDigits: v && Math.abs(v) < 0.1 ? 4 : 2, maximumFractionDigits: v && Math.abs(v) < 0.1 ? 4 : 2 });
  function quando(t) {
    const s = Math.max(0, Date.now() / 1000 - t);
    if (s < 60) return 'agora'; if (s < 3600) return Math.floor(s / 60) + ' min'; if (s < 86400) return Math.floor(s / 3600) + ' h';
    return new Date(t * 1000).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) + ' ' + new Date(t * 1000).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  }
  function montarSaldo() {
    const box = D.getElementById('saldoBox'); if (!box) return;
    const btn = box.querySelector('#saldoBtn'), pn = box.querySelector('#saldoPainel');
    let dados = null;
    function chip(d) {
      const longo = btn.querySelector('.rot-longo'), curto = btn.querySelector('.rot-curto');
      if (!d || d.erro) { longo.textContent = 'Claude'; curto.textContent = '—'; return; }
      const temCred = d.credito_usd > 0;
      const v = temCred ? d.saldo_usd : d.gasto_usd;
      longo.innerHTML = `<span class="saldo-num">${brl(v)}</span> <span style="font-weight:400;color:var(--mudo)">${temCred ? 'restante' : 'gasto'}</span>`;
      curto.textContent = brl(v).replace('US$ ', '$');
      btn.title = temCred ? `Saldo do Claude: ${brl(d.saldo_usd)} de ${brl(d.credito_usd)} (gasto ${brl(d.gasto_usd)})` : `Gasto com o Claude: ${brl(d.gasto_usd)} em ${d.chamadas} chamadas`;
      btn.style.color = temCred && d.saldo_usd < Math.max(0.5, d.credito_usd * 0.1) ? 'var(--erro)' : '';
    }
    function painel(d) {
      if (!d || d.erro) { pn.innerHTML = `<div class="saldo-vazio">${esc((d && d.erro) || 'Carregando…')}</div>`; return; }
      const temCred = d.credito_usd > 0;
      let h = `<div class="pTopo"><b><i class="fa-solid fa-robot"></i> Uso do Claude</b><span style="font-size:.78rem;color:var(--mudo)">${esc(d.modelo || '')}</span></div>`;
      h += temCred
        ? `<div class="saldo-resumo">
        <div><small>Saldo restante</small><b style="color:${d.saldo_usd < Math.max(0.5, d.credito_usd * 0.1) ? 'var(--erro)' : 'var(--ok)'}">${brl(d.saldo_usd)}</b></div>
        <div><small>Gasto no Claude</small><b>${brl(d.gasto_usd)}</b></div>
        <div><small>Hoje</small><b>${brl(d.hoje_usd)}</b></div></div>
        <div class="saldo-cred" style="padding-bottom:2px">de ${brl(d.credito_usd)} de crédito · ${d.chamadas} chamada${d.chamadas === 1 ? '' : 's'}</div>`
        : `<div class="saldo-resumo">
        <div><small>Gasto no Claude</small><b>${brl(d.gasto_usd)}</b></div>
        <div><small>Hoje</small><b>${brl(d.hoje_usd)}</b></div>
        <div><small>Chamadas</small><b>${d.chamadas}</b></div></div>`;
      h += `<div class="saldo-cred"><span>Crédito colocado na conta (US$):</span><input type="number" step="0.01" min="0" id="saldoCred" value="${temCred ? d.credito_usd : ''}" placeholder="ex.: 10">
        <button type="button" id="saldoCredOk">Salvar</button>
        <span style="width:100%">${temCred ? `Saldo = crédito − gasto desde ${d.desde ? new Date(d.desde * 1000).toLocaleDateString('pt-BR') : 'o início'}. ` : 'Informe o crédito para ver quanto resta. '}A Anthropic não mostra o saldo da conta pela API: confira no <a href="${esc(d.console || 'https://platform.claude.com/settings/billing')}" target="_blank" rel="noopener">painel de cobrança</a>.</span></div>`;
      const G = d.gemini;
      if (G && (G.tem_chave || G.chamadas)) {
        h += `<div class="saldo-sec">Gemini (checagem na internet)</div><div class="saldo-item"><span class="si-nome">${esc(G.modelo)}<small>busca do Google: ${G.buscas_usadas} de ${Number(G.buscas_gratis).toLocaleString('pt-BR')} grátis por ${esc(G.buscas_periodo)} · ${G.chamadas} checagem(ns) · <a href="${esc(G.console)}" target="_blank" rel="noopener">uso no AI Studio</a></small></span><span class="si-usd">${brl(G.gasto_usd)}<small style="display:block;font-weight:400;color:var(--mudo);font-size:.7rem;text-align:right">estimado</small></span></div>`;
      }
      if ((d.por_recurso || []).length) {
        h += `<div class="saldo-sec">Custo por ação (Claude)</div>`;
        h += d.por_recurso.map(r => `<div class="saldo-item"><span class="si-nome">${esc(r.nome)}<small>${r.chamadas} chamada${r.chamadas === 1 ? '' : 's'} · média ${brl(r.chamadas ? r.usd / r.chamadas : 0)}</small></span><span class="si-usd">${brl(r.usd)}</span></div>`).join('');
      }
      h += `<div class="saldo-sec">O que rodou por último</div>`;
      h += (d.log || []).length ? d.log.map(x => `<div class="saldo-item ${x.ok ? '' : 'erro'} ${x.cache ? 'cache' : ''}"><span class="si-nome">${esc(x.nome)}${x.rotulo ? ' · ' + esc(x.rotulo) : ''}
          <small>${quando(x.quando)}${x.cache ? ' · resposta guardada (grátis)' : ` · ${(x.entrada || 0).toLocaleString('pt-BR')} tokens de entrada, ${(x.saida || 0).toLocaleString('pt-BR')} de saída`}${x.ok ? '' : ' · erro: ' + esc(x.erro || '')}</small></span>
          <span class="si-usd">${x.cache ? 'grátis' : brl(x.usd)}</span></div>`).join('')
        : `<div class="saldo-vazio">Nenhuma chamada ainda.${d.ativo ? '' : ' A IA está desligada.'}</div>`;
      h += `<div class="saldo-item" style="justify-content:space-between"><a href="/ia"><i class="fa-solid fa-gear"></i> Configurar a IA</a><span style="color:var(--mudo);font-size:.76rem">${d.limite_usd ? 'limite de gasto: ' + brl(d.limite_usd) : ''}</span></div>`;
      pn.innerHTML = h;
      pn.querySelector('#saldoCredOk').addEventListener('click', async () => {
        const v = pn.querySelector('#saldoCred').value;
        try { await fetch('/ia/credito', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ credito_usd: v }) }); } catch (_) { /* */ }
        buscar(true);
      });
    }
    async function buscar(redesenhar) {
      try { const r = await fetch('/ia/saldo', { cache: 'no-store' }); dados = r.ok ? await r.json() : { erro: 'erro ' + r.status }; }
      catch (_) { dados = { erro: 'O site não respondeu.' }; }
      chip(dados);
      if (redesenhar || pn.classList.contains('aberta')) painel(dados);
    }
    btn.addEventListener('click', (e) => { e.stopPropagation(); pn.classList.toggle('aberta'); if (pn.classList.contains('aberta')) { painel(dados); buscar(true); } });
    pn.addEventListener('click', (e) => e.stopPropagation());
    D.addEventListener('click', () => pn.classList.remove('aberta'));
    buscar();
    setInterval(() => { if (!D.hidden) buscar(); }, 20000);
    D.addEventListener('visibilitychange', () => { if (!D.hidden) buscar(); });
    window.saldoAtualizar = () => buscar();
  }

  /* ======================================================================
     6. lembrar a última escolha (voz, idioma…) pros próximos usos
        <form data-lembrar="grupo"> → selects, números, faixas, caixas e opções do formulário
        (campo com data-nao-restaurar: só guarda; data-nao-lembrar: ignora)
        <campo data-lembrar="chave" data-lembrar-aplicar> → um campo solto
     ====================================================================== */
  const kLem = (c) => 'ui-lembrar:' + c;
  function valorDe(el) {
    if (el.type === 'checkbox') return el.checked ? '1' : '0';
    if (el.type === 'radio') return el.checked ? el.value : null;
    return el.value;
  }
  function aplicarValor(el, v, tentativa) {
    if (el.type === 'checkbox') { const c = v === '1'; if (el.checked === c) return; el.checked = c; }
    else if (el.type === 'radio') { if (el.value !== v || el.checked) return; el.checked = true; }
    else {
      if (el.value === v) return;
      if (el.tagName === 'SELECT' && !Array.from(el.options).some(o => o.value === v)) {
        // as opções podem chegar depois (lista que vem do servidor): tenta de novo por uns segundos
        if ((tentativa || 0) < 16) setTimeout(() => aplicarValor(el, v, (tentativa || 0) + 1), 400);
        return;
      }
      el.value = v;
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  function ligarLembrar(el, chave, restaurar) {
    if (el.dataset.lemLigado) return; el.dataset.lemLigado = '1';
    const salvar = () => { const v = valorDe(el); if (v !== null) LS.set(kLem(chave), v); };
    el.addEventListener('change', salvar);
    if (el.type === 'text' || el.type === 'number') el.addEventListener('input', salvar);
    if (restaurar) { const v = LS.get(kLem(chave), null); if (v !== null) aplicarValor(el, v); }
  }
  function montarLembrar(raiz) {
    (raiz || D).querySelectorAll('form[data-lembrar]').forEach(f => {
      const g = f.dataset.lembrar;
      // o motor primeiro: ele mostra as opções de cada motor
      const campos = Array.from(f.querySelectorAll('select[name],input[name]')).sort((a, b) => (b.name === 'engine') - (a.name === 'engine'));
      campos.forEach(el => {
        const t = (el.type || '').toLowerCase();
        if (['file', 'hidden', 'password', 'submit', 'button', 'email', 'url', 'search'].includes(t)) return;
        if (t === 'text' && !el.hasAttribute('data-lembrar-campo')) return;
        if (/salvar|nome_novo|novo_perfil/i.test(el.name) || el.hasAttribute('data-nao-lembrar')) return;
        ligarLembrar(el, g + ':' + el.name, !el.hasAttribute('data-nao-restaurar'));
      });
    });
    (raiz || D).querySelectorAll('[data-lembrar]:not(form)').forEach(el => ligarLembrar(el, el.dataset.lembrar, el.hasAttribute('data-lembrar-aplicar')));
  }

  /* ======================================================================
     início
     ====================================================================== */
  function observar() {
    let fila = new Set();
    const processar = () => {
      const itens = Array.from(fila); fila = new Set();
      for (const n of itens) {
        if (!n.isConnected) continue;
        iconizar(n);
        if (escuro() && MODO !== 'minimo' && n.nodeType === 1) { recolorirEl(n); if (n.querySelectorAll) n.querySelectorAll('[style]').forEach(recolorirEl); }
      }
    };
    const obs = new MutationObserver((muts) => {
      let h2novo = false, folhaNova = false;
      for (const m of muts) {
        if (m.type === 'childList') {
          m.addedNodes.forEach(n => {
            if (n.nodeType === 1 && n.classList && (n.classList.contains('emo-txt') || n.classList.contains('ico'))) return;
            fila.add(n);
            if (n.nodeType === 1) {
              if (n.tagName === 'STYLE' || n.tagName === 'LINK') folhaNova = true;
              if (n.tagName === 'H2' || (n.querySelector && n.querySelector('h2'))) h2novo = true;
            }
          });
        } else if (m.type === 'characterData') fila.add(m.target);
        else if (m.type === 'attributes') {
          if (m.attributeName === 'style') { if (escuro() && MODO !== 'minimo') recolorirEl(m.target); }
          else fila.add(m.target);
        }
      }
      if (fila.size) processar();
      if (folhaNova && escuro() && MODO !== 'minimo') setTimeout(() => { for (const sh of Array.from(D.styleSheets)) recolorirFolha(sh); }, 0);
      if (h2novo && MODO !== 'minimo') { clearTimeout(observar._t); observar._t = setTimeout(montarSecoes, 300); }
    });
    obs.observe(D.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['style', 'title', 'placeholder', 'label'] });
    // document.title muda pelo sininho ("(2) …")
    const t = D.querySelector('title');
    if (t) new MutationObserver(tituloSemEmoji).observe(t, { childList: true, characterData: true, subtree: true });
  }

  function iniciar() {
    try {
      tituloSemEmoji();
      iconizar(D.body);
      if (MODO !== 'minimo') {
        montarMenu();
        montarSecoes();  // antes do tema: mover um <style> pra dentro da seção recria a folha (perderia as cores)
        aplicarTema(H.dataset.tema || 'escuro', false);
        D.querySelectorAll('[data-ui-tema-btn]').forEach(b => b.addEventListener('click', () => aplicarTema(escuro() ? 'claro' : 'escuro', true)));
        montarSaldo();
        montarLembrar();
      }
      observar();
    } catch (e) { console.error('ui.js', e); }
    finally { H.classList.add('tema-pronto'); }
  }
  // outras abas: trocou o tema lá → troca aqui
  addEventListener('storage', (e) => { if (e.key === 'ui-tema' && e.newValue && MODO !== 'minimo') aplicarTema(e.newValue, false); });
  window.UI = { aplicarTema, iconizar, montarSecoes, montarLembrar, semEmoji };
  if (D.readyState === 'loading') D.addEventListener('DOMContentLoaded', iniciar); else iniciar();
})();
