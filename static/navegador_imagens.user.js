// ==UserScript==
// @name         Google Imagens - Capturar Links (tamanho original) + BestEditor
// @namespace    https://github.com/rivans/google-img-links
// @version      __VERSAO__
// @description  Marca imagens no Google Imagens e captura o link da imagem em tamanho original. Aberta pelo site (🧲), manda os links direto pra pergunta/pessoa certa e fecha a guia. No 📰 Buscador de casos: marca os resultados da busca normal/notícias e manda pro site.
// @author       rivans
// @match        https://www.google.com/search*
// @match        https://www.google.com.br/search*
// @include      /^https:\/\/www\.google\.[a-z.]+\/search.*$/
// @grant        GM_setClipboard
// @grant        GM_addStyle
// @grant        GM_xmlhttpRequest
// @connect      localhost
// @connect      127.0.0.1
// @connect      *
// @updateURL    __SITE__/navegador-imagens/script.user.js
// @downloadURL  __SITE__/navegador-imagens/script.user.js
// @run-at       document-start
// ==/UserScript==

(function () {
  'use strict';

  // ===================== CONFIGURAÇÃO =====================
  const CFG = {
    autoQtd: 4,              // quantas imagens no modo "Auto: primeiras"
    tempoMaxPainel: 8000,    // ms esperando o link original aparecer no painel
    pausaEntre: 500,         // ms de pausa entre uma imagem e outra
    pausaAposFechar: 400,    // ms após fechar o painel
  };

  // ===================== SELETORES (baseados no HTML enviado) =====================
  const SEL = {
    tile: 'div[jsname="dTDiAc"][data-docid]',           // cada resultado da grade
    tileClick: 'div[jsname="PNoEC"][role="button"]',     // área clicável que abre o painel
    tileImg: 'img',                                      // miniatura dentro do resultado
    dialog: 'div[role="dialog"][jsname="ujKaBc"]',       // painel lateral
    slideAtivo: 'div[jsname="Qzjw6d"][aria-hidden="false"]',
    imgOriginal: 'img[jsname="kn3ccd"], img.sFlh5c',     // imagem grande do painel
    fechar: 'button[aria-label="Fechar"], button[aria-label="Close"]',
  };

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const selecionados = new Set(); // docids marcados
  let rodando = false;
  let parar = false;
  let resultados = []; // {titulo, url, pagina}
  let ultimaUrl = '';

  // ===================== 🧲 DESTINO (a guia foi aberta pelo site: #bes=…) =====================
  // Guarda na sessão da guia: se você mudar a busca nesta guia, os links continuam indo pro mesmo lugar.
  function lerDestino() {
    const m = location.hash.match(/bes=([A-Za-z0-9_-]+)/);
    if (m) {
      try {
        let b = m[1].replace(/-/g, '+').replace(/_/g, '/'); b += '='.repeat((4 - b.length % 4) % 4);
        const bin = atob(b), bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
        const d = JSON.parse(new TextDecoder().decode(bytes));
        sessionStorage.setItem('gcl-bes', JSON.stringify(d));
        return d;
      } catch (e) { console.warn('[GCL] destino inválido', e); }
    }
    try { return JSON.parse(sessionStorage.getItem('gcl-bes') || 'null'); } catch { return null; }
  }
  const DEST = lerDestino();
  // o "#bes=…" sai do endereço JÁ (antes do Google ler): o visualizador de imagens do Google usa o "#" do endereço
  // e, com o nosso lá, o painel da imagem não abria (as marcadas ficavam com borda vermelha)
  if (/bes=/.test(location.hash)) { try { history.replaceState(history.state, '', location.pathname + location.search); } catch {} }
  const enviados = new Set();

  // ===================== ESTILO =====================
  const _css = (`
    .gcl-chk {
      position:absolute; top:6px; left:6px; z-index:50;
      width:26px; height:26px; border-radius:6px;
      background:rgba(255,255,255,.92); border:2px solid #1a73e8;
      display:flex; align-items:center; justify-content:center;
      cursor:pointer; font:bold 16px/1 Arial,sans-serif; color:#fff;
      box-shadow:0 1px 4px rgba(0,0,0,.35); transition:transform .1s;
      user-select:none;
    }
    .gcl-chk:hover { transform:scale(1.12); }
    .gcl-chk.on { background:#1a73e8; }
    .gcl-chk.on::after { content:'✓'; }
    .gcl-tile-on { outline:3px solid #1a73e8 !important; outline-offset:-3px; border-radius:8px; }
    .gcl-tile-ok { outline:3px solid #188038 !important; outline-offset:-3px; border-radius:8px; }
    .gcl-tile-erro { outline:3px solid #d93025 !important; outline-offset:-3px; border-radius:8px; }

    #gcl-painel {
      position:fixed; top:12px; right:12px; z-index:2147483646;
      width:300px; background:#fff; color:#202124;
      border-radius:12px; box-shadow:0 4px 18px rgba(0,0,0,.3);
      font:13px/1.4 Arial,sans-serif; padding:10px;
    }
    #gcl-painel.min #gcl-corpo { display:none; }
    #gcl-topo { display:flex; align-items:center; gap:6px; margin-bottom:8px; }
    #gcl-topo b { flex:1; font-size:14px; }
    #gcl-painel button {
      border:0; border-radius:8px; padding:7px 10px; cursor:pointer;
      font:bold 12px Arial,sans-serif; background:#e8f0fe; color:#1967d2;
    }
    #gcl-painel button:hover { filter:brightness(.95); }
    #gcl-painel button:disabled { opacity:.5; cursor:default; }
    #gcl-painel .principal { background:#1a73e8; color:#fff; width:100%; font-size:14px; padding:10px; }
    #gcl-painel .perigo { background:#fce8e6; color:#c5221f; }
    #gcl-painel .linha { display:flex; gap:6px; margin-top:6px; }
    #gcl-painel .linha button { flex:1; }
    #gcl-status { margin:8px 0 4px; font-size:12px; color:#5f6368; min-height:16px; }
    #gcl-saida {
      width:100%; height:130px; box-sizing:border-box; margin-top:4px;
      font:11px/1.35 monospace; border:1px solid #dadce0; border-radius:8px; padding:6px;
      resize:vertical; color:#202124; background:#f8f9fa;
    }
    #gcl-dest { font-size:12px; background:#e6f4ea; color:#137333; border-radius:8px; padding:6px 8px; margin-bottom:8px; }
    #gcl-painel label { font-size:12px; display:flex; align-items:center; gap:4px; margin-top:6px; }
    @media (prefers-color-scheme: dark) {
      #gcl-painel { background:#303134; color:#e8eaed; }
      #gcl-saida { background:#202124; color:#e8eaed; border-color:#5f6368; }
      #gcl-status { color:#9aa0a6; }
    }
  `);
  const _estilo = () => { try { GM_addStyle(_css); } catch { const st = document.createElement('style'); st.textContent = _css; (document.head || document.documentElement).appendChild(st); } };

  // ===================== CAIXINHAS NAS IMAGENS =====================
  function adicionarCaixinhas() {
    document.querySelectorAll(SEL.tile).forEach((tile) => {
      if (tile.querySelector(':scope > .gcl-chk')) return;
      const id = tile.getAttribute('data-docid');
      if (getComputedStyle(tile).position === 'static') tile.style.position = 'relative';

      const chk = document.createElement('div');
      chk.className = 'gcl-chk' + (selecionados.has(id) ? ' on' : '');
      chk.title = 'Marcar para capturar o link';

      // Impede que o clique na caixinha abra o painel do Google
      ['mousedown', 'mouseup', 'pointerdown', 'pointerup', 'touchstart'].forEach((ev) =>
        chk.addEventListener(ev, (e) => { e.stopPropagation(); }, true)
      );
      chk.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        alternar(tile);
      }, true);

      tile.appendChild(chk);
    });
    atualizarContador();
  }

  function alternar(tile, forcar) {
    const id = tile.getAttribute('data-docid');
    const chk = tile.querySelector(':scope > .gcl-chk');
    const ligar = forcar !== undefined ? forcar : !selecionados.has(id);
    if (ligar) selecionados.add(id); else selecionados.delete(id);
    chk && chk.classList.toggle('on', ligar);
    tile.classList.toggle('gcl-tile-on', ligar);
    atualizarContador();
    avisarEstado();
  }

  const todosTiles = () => [...document.querySelectorAll(SEL.tile)];
  const tilePorId = (id) => document.querySelector(`${SEL.tile}[data-docid="${CSS.escape(id)}"]`);

  // ===================== PAINEL DE CONTROLE =====================
  let elStatus, elSaida, elContador, elBtns = {};

  function criarPainel() {
    if (document.getElementById('gcl-painel')) return;
    const p = document.createElement('div');
    p.id = 'gcl-painel';
    // Sem innerHTML: o Google usa "Trusted Types" e o Chrome/Chromium bloqueia innerHTML
    const el = (tag, attrs = {}, ...filhos) => {
      const e = document.createElement(tag);
      for (const [k, v] of Object.entries(attrs)) {
        if (k === 'class') e.className = v;
        else if (k in e && typeof v !== 'string') e[k] = v;
        else e.setAttribute(k, v);
      }
      filhos.forEach((f) => e.append(f));
      return e;
    };
    p.append(
      el('div', { id: 'gcl-topo' },
        el('b', {}, DEST ? '🧲 Enviar ao site' : '🖼️ Links de imagens'),
        el('button', { id: 'gcl-min', title: 'Minimizar' }, '–')),
      el('div', { id: 'gcl-corpo' },
        DEST ? el('div', { id: 'gcl-dest' }, 'Para: ', el('b', {}, DEST.r || (DEST.e ? DEST.e.n : DEST.q) || 'o modelo')) : '',
        el('button', { class: 'principal', id: 'gcl-capturar' }, DEST ? 'Capturar e enviar ao site (' : 'Capturar links (', el('span', { id: 'gcl-cont' }, '0'), ')'),
        el('div', { class: 'linha' },
          el('button', { id: 'gcl-auto4' }, `Auto: ${CFG.autoQtd} primeiras`),
          el('button', { id: 'gcl-autoTodas' }, 'Auto: todas carregadas')),
        el('div', { class: 'linha' },
          el('button', { id: 'gcl-marcarTodas' }, 'Marcar todas'),
          el('button', { id: 'gcl-limpar' }, 'Desmarcar'),
          el('button', { id: 'gcl-parar', class: 'perigo', disabled: true }, 'Parar')),
        el('label', {}, el('input', { type: 'checkbox', id: 'gcl-comTitulo' }), ' incluir título e página de origem'),
        DEST ? el('label', {}, el('input', { type: 'checkbox', id: 'gcl-fechar', checked: true }), ' fechar a guia quando terminar de enviar') : '',
        DEST ? el('div', { class: 'linha' },
          el('button', { id: 'gcl-proximas', class: 'principal', style: 'background:#188038', title: 'fecha as guias que já terminaram (as que têm imagem marcada e não enviada ficam abertas) e abre as próximas perguntas' }, '➡ Próximas guias'),
          el('select', { id: 'gcl-qtd', title: 'quantas abrir' }, ...[3, 5, 8, 10].map((n) => el('option', n === 5 ? { selected: true } : {}, String(n))))) : '',
        el('div', { id: 'gcl-status' }, 'Marque as imagens na caixinha azul.'),
        el('textarea', { id: 'gcl-saida', placeholder: 'Os links aparecem aqui...' }),
        el('div', { class: 'linha' },
          el('button', { id: 'gcl-copiar' }, 'Copiar'),
          el('button', { id: 'gcl-baixar' }, 'Baixar .txt'),
          el('button', { id: 'gcl-zerar', class: 'perigo' }, 'Limpar lista')))
    );
    document.body.appendChild(p);

    elStatus = p.querySelector('#gcl-status');
    elSaida = p.querySelector('#gcl-saida');
    elContador = p.querySelector('#gcl-cont');
    ['capturar', 'auto4', 'autoTodas', 'marcarTodas', 'limpar', 'parar', 'copiar', 'baixar', 'zerar']
      .forEach((k) => (elBtns[k] = p.querySelector('#gcl-' + k)));

    p.querySelector('#gcl-min').onclick = () => p.classList.toggle('min');
    p.querySelector('#gcl-comTitulo').onchange = renderSaida;

    elBtns.capturar.onclick = () => {
      const ids = todosTiles().map((t) => t.getAttribute('data-docid')).filter((id) => selecionados.has(id));
      if (!ids.length) return status('Nenhuma imagem marcada.');
      processar(ids);
    };
    elBtns.auto4.onclick = () => processar(todosTiles().slice(0, CFG.autoQtd).map((t) => t.getAttribute('data-docid')));
    elBtns.autoTodas.onclick = () => processar(todosTiles().map((t) => t.getAttribute('data-docid')));
    elBtns.marcarTodas.onclick = () => todosTiles().forEach((t) => alternar(t, true));
    elBtns.limpar.onclick = () => todosTiles().forEach((t) => alternar(t, false));
    elBtns.parar.onclick = () => { parar = true; status('Parando...'); };
    elBtns.copiar.onclick = copiar;
    elBtns.baixar.onclick = baixar;
    elBtns.zerar.onclick = () => { resultados = []; renderSaida(); status('Lista limpa.'); };
    const bp = p.querySelector('#gcl-proximas');
    if (bp) bp.onclick = proximasGuias;
  }

  function atualizarContador() { if (elContador) elContador.textContent = selecionados.size; }
  function status(t) { if (elStatus) elStatus.textContent = t; }

  function renderSaida() {
    const comTitulo = document.getElementById('gcl-comTitulo')?.checked;
    elSaida.value = resultados
      .map((r) => (comTitulo ? `${r.titulo}\n${r.url}\n${r.pagina || ''}\n` : r.url))
      .join('\n');
    elSaida.scrollTop = elSaida.scrollHeight;
  }

  function travarBotoes(sim) {
    ['capturar', 'auto4', 'autoTodas', 'marcarTodas', 'limpar'].forEach((k) => (elBtns[k].disabled = sim));
    elBtns.parar.disabled = !sim;
  }

  // ===================== LÓGICA DE CAPTURA =====================
  const ehMiniatura = (src) =>
    !src || src.startsWith('data:') || /encrypted-tbn\d*\.gstatic\.com|gstatic\.com\/images/.test(src);

  function dialogVisivel() {
    const dlgs = [...document.querySelectorAll(SEL.dialog)];
    return dlgs.find((d) => d.getAttribute('aria-hidden') === 'false' && getComputedStyle(d).display !== 'none') ||
      dlgs.find((d) => d.getAttribute('aria-hidden') !== 'true' && getComputedStyle(d).display !== 'none');
  }

  // Procura no painel lateral a imagem em tamanho original (não-miniatura)
  function lerImagemDoPainel(altEsperado, aceitarQualquer, ultimaUrl) {
    const dlg = dialogVisivel();
    if (!dlg) return null;
    const slide = dlg.querySelector(SEL.slideAtivo) || dlg;
    const imgs = [...slide.querySelectorAll(SEL.imgOriginal)];
    const boas = imgs.filter((i) => !ehMiniatura(i.getAttribute('src')));
    if (!boas.length) return null;
    // Prefere a que tem o mesmo "alt" da miniatura clicada (garante que é a imagem certa)
    const certa = altEsperado ? boas.find((i) => (i.alt || '').trim() === altEsperado) : null;
    let img = certa;
    if (!img && (aceitarQualquer || !altEsperado)) img = boas.find((i) => i.getAttribute('src') !== ultimaUrl);
    if (!img) return null;
    const linkPagina = img.closest('a')?.href || '';
    return { url: img.getAttribute('src'), pagina: linkPagina };
  }

  // Plano B: pega o imgurl do link /imgres (o Google preenche depois do clique/hover)
  function lerImgurlDoTile(tile) {
    const a = tile.querySelector('a[href*="imgurl="]');
    if (!a) return null;
    try {
      const u = new URL(a.href, location.origin);
      return { url: u.searchParams.get('imgurl'), pagina: u.searchParams.get('imgrefurl') || '' };
    } catch { return null; }
  }

  // Plano C: o link original está nos dados da própria página (scripts), perto do id do resultado
  function lerDosDadosDaPagina(docid) {
    if (!docid) return null;
    const ehMini = (u) => /gstatic\.com|google\.com\/(images|logos)|^data:/.test(u);
    for (const sc of document.querySelectorAll('script:not([src])')) {
      const t = sc.textContent || '';
      let k = t.indexOf(docid);
      while (k >= 0) {
        const trecho = t.slice(k, k + 4000);
        const re = /\["(https?:\/\/[^"]+)",(\d+),(\d+)\]/g; let m;
        while ((m = re.exec(trecho))) {
          let u = m[1];
          try { u = JSON.parse('"' + u + '"'); } catch {}
          if (!ehMini(u)) return { url: u, pagina: '' };
        }
        k = t.indexOf(docid, k + docid.length);
      }
    }
    return null;
  }

  async function fecharPainel() {
    const dlg = dialogVisivel();
    const btn = (dlg && dlg.querySelector(SEL.fechar)) ||
      [...document.querySelectorAll(SEL.fechar)].find((b) => b.offsetParent !== null);
    if (btn) {
      btn.click();
    } else {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }));
    }
    await sleep(CFG.pausaAposFechar);
  }

  async function capturarUma(tile) {
    const thumb = tile.querySelector(SEL.tileImg);
    const alt = (thumb?.alt || '').trim();
    const alvo = tile.querySelector(SEL.tileClick) || thumb || tile;

    tile.scrollIntoView({ block: 'center', behavior: 'instant' });
    await sleep(150);

    // simula o hover + clique de verdade (o Google escuta esses eventos)
    const r = alvo.getBoundingClientRect();
    // sem "view: window": com GM_xmlhttpRequest a extensão roda o script numa "caixa" e o window dela não é a janela
    // de verdade — o new MouseEvent dava erro e TODAS as imagens ficavam com borda vermelha
    const xy = { bubbles: true, cancelable: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, button: 0 };
    const disparar = (ev) => { try { alvo.dispatchEvent(ev); } catch (e) { console.warn('[GCL] evento', e); } };
    const criar = (Tipo, nome, extra) => { try { return new Tipo(nome, Object.assign({}, xy, extra || {})); } catch { return new MouseEvent(nome.replace('pointer', 'mouse'), xy); } };
    disparar(criar(MouseEvent, 'mouseover'));
    disparar(criar(typeof PointerEvent === 'function' ? PointerEvent : MouseEvent, 'pointerdown', { pointerType: 'mouse', isPrimary: true }));
    disparar(criar(MouseEvent, 'mousedown'));
    disparar(criar(typeof PointerEvent === 'function' ? PointerEvent : MouseEvent, 'pointerup', { pointerType: 'mouse', isPrimary: true }));
    disparar(criar(MouseEvent, 'mouseup'));
    disparar(criar(MouseEvent, 'click'));

    const inicio = Date.now();
    let achou = null;
    while (Date.now() - inicio < CFG.tempoMaxPainel) {
      if (parar) break;
      // nos primeiros 3s exige o mesmo título; depois aceita qualquer imagem nova
      achou = lerImagemDoPainel(alt, Date.now() - inicio > 3000, ultimaUrl);
      if (achou) break;
      await sleep(200);
    }
    if (!achou) achou = lerImgurlDoTile(tile); // plano B
    if (!achou) achou = lerDosDadosDaPagina(tile.getAttribute('data-docid')); // plano C

    await fecharPainel();
    if (achou) ultimaUrl = achou.url;
    return achou ? { titulo: alt, ...achou } : null;
  }

  async function processar(ids) {
    if (rodando || !ids.length) return;
    rodando = true; parar = false;
    travarBotoes(true);
    avisarEstado();
    const jaTem = new Set(resultados.map((r) => r.url));
    let ok = 0, erro = 0;

    for (let i = 0; i < ids.length; i++) {
      if (parar) break;
      const tile = tilePorId(ids[i]);
      if (!tile) { erro++; continue; }
      status(`Capturando ${i + 1} de ${ids.length}...`);
      tile.classList.remove('gcl-tile-ok', 'gcl-tile-erro');

      let r = null;
      try { r = await capturarUma(tile); } catch (e) { console.warn('[GCL]', e); status('⚠ ' + (e && e.message || e)); }
      if (!(r && r.url)) { const c = lerImgurlDoTile(tile) || lerDosDadosDaPagina(ids[i]); if (c) r = { titulo: (tile.querySelector('img')?.alt || '').trim(), ...c }; }
      if (!(r && r.url) && !parar) { await sleep(600); try { r = await capturarUma(tile); } catch (e) { console.warn('[GCL]', e); } } // 2ª tentativa

      if (r && r.url) {
        ok++;
        tile.classList.add('gcl-tile-ok');
        if (!jaTem.has(r.url)) { jaTem.add(r.url); resultados.push(r); renderSaida(); }
        alternar(tile, false);
      } else {
        erro++;
        tile.classList.add('gcl-tile-erro');
      }
      await sleep(CFG.pausaEntre);
    }

    status(`${parar ? 'Interrompido. ' : 'Pronto! '}${ok} capturada(s)${erro ? `, ${erro} com erro (borda vermelha)` : ''}. Total na lista: ${resultados.length}.`);
    if (DEST && !parar) await enviarTudo();
    rodando = false; parar = false;
    travarBotoes(false);
    avisarEstado();
  }

  // ===================== 🧲 MANDAR PRO SITE (ele baixa e liga à pergunta/pessoa) =====================
  // OrangeMonkey/Tampermonkey: GM_xmlhttpRequest (passa por cima do bloqueio do Google). Sem ele: fetch simples (o site libera).
  const _gmx = (typeof GM_xmlhttpRequest === 'function') ? GM_xmlhttpRequest
    : (typeof GM !== 'undefined' && GM && typeof GM.xmlHttpRequest === 'function') ? GM.xmlHttpRequest.bind(GM) : null;
  function postar(caminho, corpo) {
    if (!_gmx) {
      return fetch(DEST.u + caminho, { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify(corpo) })
        .then(async (r) => { let d = {}; try { d = await r.json(); } catch {} return r.ok && !d.erro ? { ok: true, d } : { ok: false, erro: d.erro || ('HTTP ' + r.status) }; })
        .catch(() => ({ ok: false, erro: 'o navegador bloqueou o envio ao site — permita "rede local" para o google.com ou use a extensão com GM_xmlhttpRequest' }));
    }
    return new Promise((fim) => _gmx({
      method: 'POST', url: DEST.u + caminho, headers: { 'Content-Type': 'application/json' }, data: JSON.stringify(corpo), timeout: 120000,
      onload: (x) => { let d = {}; try { d = JSON.parse(x.responseText); } catch {} fim(x.status < 300 && !d.erro ? { ok: true, d } : { ok: false, erro: d.erro || ('HTTP ' + x.status) }); },
      onerror: () => fim({ ok: false, erro: 'o site não respondeu (está aberto?)' }),
      ontimeout: () => fim({ ok: false, erro: 'demorou demais' }),
    }));
  }
  function _paraB64(buf) {
    const bytes = new Uint8Array(buf); let bin = '';
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(bin);
  }
  function baixarNoNavegador(url) {
    return new Promise((fim) => {
      const pelaFetch = () => fetch(url, { credentials: 'include' }).then((r) => r.ok ? r.arrayBuffer() : null).then((b) => fim(b && b.byteLength > 500 ? _paraB64(b) : null)).catch(() => fim(null));
      if (!_gmx) return pelaFetch();
      _gmx({ method: 'GET', url, responseType: 'arraybuffer', timeout: 60000,
        onload: (x) => { const b = x.response; if (x.status < 300 && b && b.byteLength > 500) fim(_paraB64(b)); else pelaFetch(); },
        onerror: pelaFetch, ontimeout: () => fim(null) });
    });
  }
  // 🗂 v84_293: guia aberta pela Busca em lista (#bes com m:"lista") → as fotos vão pra /busca-lista/<id>
  function baseDoDestino() {
    return (DEST && DEST.m === 'lista') ? `/busca-lista/${encodeURIComponent(DEST.p)}` : `/modelos-video/${encodeURIComponent(DEST.p)}/fotos-roteiro`;
  }
  async function enviarTudo() {
    const fila = resultados.filter((r) => !enviados.has(r.url));
    if (!fila.length) return;
    const base = baseDoDestino();
    let ok = 0; const falhas = [];
    for (let i = 0; i < fila.length; i++) {
      const r = fila[i];
      status(`⬆ Mandando pro site ${i + 1} de ${fila.length}…`);
      const corpo = { pergunta: DEST.q || '', descricao: DEST.e ? DEST.e.n : '', origem: 'guia', elenco: DEST.e || null };
      let res = await postar(base + '/link', Object.assign({ url: r.url }, corpo));
      if (!res.ok) { // o site da imagem barrou o servidor (ex.: Facebook): o próprio navegador baixa e manda os bytes
        const b64 = await baixarNoNavegador(r.url);
        if (b64) res = await postar(base + '/link', Object.assign({ url: r.url, dados_b64: b64 }, corpo));
      }
      if (!res.ok && r.pagina) res = await postar(base + '/link', Object.assign({ url: r.pagina }, corpo)); // último caso: a foto principal da página
      if (res.ok) { ok++; enviados.add(r.url); } else falhas.push(res.erro);
    }
    if (DEST.q) await postar(base + '/guia-feita', { pergunta: DEST.q, enviadas: enviados.size });
    teveFalha = falhas.length > 0;
    status(`✔ ${ok} de ${fila.length} no site${falhas.length ? ` · ⚠ ${falhas.length} falharam: ${falhas[0]}` : ''}`);
    if (!falhas.length && document.getElementById('gcl-fechar')?.checked) {
      status(`✔ ${ok} no site — fechando a guia…`);
      setTimeout(async () => {
        const f = await postar('/navegador-imagens/fechar', { p: DEST.p, q: DEST.q || '', e: DEST.e || null });
        if (f.ok && f.d && f.d.fechou) return;
        try { window.close(); } catch {}
        setTimeout(() => status(`✔ ${ok} no site — pode fechar esta guia (Ctrl+W)`), 600);  // se a extensão não deixar fechar sozinha
      }, 1500);
    }
  }

  // ===================== 🧲 ESTADO DA GUIA (pro site saber se pode fechar) + PRÓXIMAS GUIAS =====================
  let teveFalha = false, _avisoT = null;
  function estadoDaGuia() {
    if (rodando) return 'rodando';
    if (selecionados.size) return 'marcada';
    if (teveFalha) return 'erro';
    return enviados.size ? 'enviada' : 'livre';
  }
  function avisarEstado() {
    if (!DEST) return;
    clearTimeout(_avisoT);
    _avisoT = setTimeout(() => postar('/navegador-imagens/aba', { p: DEST.p, q: DEST.q || '', e: DEST.e || null, estado: estadoDaGuia(), marcadas: selecionados.size }), 300);
  }
  async function proximasGuias() {
    const b = document.getElementById('gcl-proximas'); if (b) b.disabled = true;
    await postar('/navegador-imagens/aba', { p: DEST.p, q: DEST.q || '', e: DEST.e || null, estado: estadoDaGuia(), marcadas: selecionados.size });
    status('➡ Fechando as prontas e abrindo as próximas…');
    const qtd = +(document.getElementById('gcl-qtd')?.value || 5);
    const r = await postar(baseDoDestino() + '/guias', { trocar: true, quantas: qtd });
    if (b) b.disabled = false;
    if (!r.ok) return status('⚠ ' + r.erro);
    const d = r.d || {}, m = d.mantidas || [];
    status(`✔ ${d.fechadas || 0} fechada(s) · ${d.abertas || 0} nova(s)` + (m.length ? ` · ${m.length} ficaram abertas (imagem marcada e não enviada${m.some((x) => x.estado === 'erro') ? ' ou com erro' : ''})` : '') + (d.msg ? ' · ' + d.msg : '') + (d.aviso ? ' · ⚠ ' + d.aviso : ''));
  }
  setInterval(() => { if (!(DEST && DEST.m === 'pesquisa')) avisarEstado(); }, 20000);

  // ===================== COPIAR / BAIXAR =====================
  // Tenta 3 jeitos de copiar, porque cada navegador/versão do Tampermonkey se comporta diferente
  async function copiar() {
    const txt = elSaida.value;
    if (!txt) return status('Nada para copiar. Capture os links primeiro.');
    const n = txt.split('\n').filter((l) => /^https?:/.test(l)).length;

    // 1) Tampermonkey
    try {
      if (typeof GM_setClipboard === 'function') { GM_setClipboard(txt, 'text'); return status(`Copiado! (${n} links)`); }
    } catch (e) { console.warn('[GCL] GM_setClipboard falhou', e); }

    // 2) API moderna do navegador
    try {
      await navigator.clipboard.writeText(txt);
      return status(`Copiado! (${n} links)`);
    } catch (e) { console.warn('[GCL] navigator.clipboard falhou', e); }

    // 3) Jeito antigo: textarea temporário + execCommand
    try {
      const t = document.createElement('textarea');
      t.value = txt;
      t.style.cssText = 'position:fixed;top:0;left:0;opacity:0;';
      document.body.appendChild(t);
      t.focus(); t.select();
      const ok = document.execCommand('copy');
      t.remove();
      if (ok) return status(`Copiado! (${n} links)`);
    } catch (e) { console.warn('[GCL] execCommand falhou', e); }

    // Nada funcionou: deixa selecionado para Ctrl+C
    elSaida.focus(); elSaida.select();
    status('Não consegui copiar sozinho. O texto está selecionado: aperte Ctrl+C.');
  }

  function baixar() {
    const txt = elSaida.value;
    if (!txt) return status('Nada para baixar.');
    const q = new URLSearchParams(location.search).get('q') || 'imagens';
    const nome = 'links-' + q.replace(/[^\w\-]+/g, '_').slice(0, 40) + '.txt';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([txt], { type: 'text/plain;charset=utf-8' }));
    a.download = nome;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  // ===================== 📰 MODO PESQUISA (Buscador de casos e notícias, v84_165) =====================
  // A guia foi aberta pelo 📰 Buscador (#bes com m:"pesquisa"): caixinha em cada resultado da busca normal ou da aba
  // Notícias; "Enviar ao site" manda os marcados pra /pesquisas/<id>/resultados. Página 2, 3…: marca e envia de novo.
  const MODO_PESQ = !!(DEST && DEST.m === 'pesquisa');
  const pesqMarcados = new Set(), pesqEnviados = new Set();
  let pesqStatus = null, pesqCont = null;
  const pesqEl = (tag, attrs = {}, ...filhos) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) { if (k === 'class') e.className = v; else if (k in e && typeof v !== 'string') e[k] = v; else e.setAttribute(k, v); }
    filhos.forEach((f) => e.append(f));
    return e;
  };
  function pesqLink(h) {
    try {
      const u = new URL(h, location.href);
      // v84_167: o Google novo esconde o link num código (/goto?url=CAES…) — guarda e descobre o de verdade antes de enviar
      if (/\.google\./.test(u.hostname) && u.pathname === '/goto' && u.searchParams.get('url')) return u.href;
      if (/\.google\./.test(u.hostname) && (u.pathname === '/url' || u.pathname === '/imgres')) return u.searchParams.get('q') || u.searchParams.get('url') || '';
      if (/(^|\.)google\.|gstatic\.com$|googleusercontent\.com$/.test(u.hostname)) return '';
      return /^https?:$/.test(u.protocol) ? u.href : '';
    } catch { return ''; }
  }
  // v84_166: acha pelo TÍTULO (h3 / heading / .LC20lb) em qualquer lugar da página e sobe/desce até o link —
  // o Google muda a estrutura (link dentro do título, título fora do link, #rso ausente na página 2…)
  function pesqLinkDoTitulo(t) {
    let a = t.closest('a[href]');
    if (!a) a = t.querySelector('a[href]');
    for (let n = t.parentElement, k = 0; !a && n && k < 4; n = n.parentElement, k++) a = n.querySelector(':scope > a[href], :scope > * > a[href]');
    return a;
  }
  function pesqItens() {
    const vistos = new Set(), out = [];
    document.querySelectorAll('h3, [role="heading"][aria-level="3"], .LC20lb, a[jsname="UWckNb"] [role="heading"], div.n0jPhd').forEach((tit) => {
      if (tit.closest('#gcl-painel') || tit.querySelector('h3')) return;
      const a = pesqLinkDoTitulo(tit);
      if (!a) return;
      const url = pesqLink(a.getAttribute('href'));
      if (!url || vistos.has(url)) return;
      vistos.add(url);
      const bloco = a.closest('div.MjjYud, div.SoaBEf, div.g, div.Gx5Zad, div[data-hveid], div[data-ved]') || a.parentElement;
      const txt = (sel) => { const x = bloco && bloco.querySelector(sel); return x ? x.textContent.replace(/\s+/g, ' ').trim() : ''; };
      let fonte = txt('.VuuXrf, .MgUUmf, .NUnG9d, cite');
      try { fonte = fonte || (/\/goto\?/.test(url) ? '' : new URL(url).hostname.replace(/^www\./, '')); } catch {}
      out.push({ a, tit, bloco, url, titulo: tit.textContent.replace(/\s+/g, ' ').trim(), fonte, cite: txt('cite'),
        trecho: txt('.VwiC3b, .GI74Re, [data-sncf], .ITZIwc, .UqSP2b, [style*="-webkit-line-clamp"]').slice(0, 400),
        data: txt('.OSrXXb span, .LfVVr, .rbYSKb, .WG9SHc span').slice(0, 40) });
    });
    return out;
  }
  function pesqAtualizar() {
    if (pesqCont) pesqCont.textContent = pesqMarcados.size;
  }
  // 🆘 se as caixinhas não aparecerem (o Google mudou a página): manda a página inteira e o site tira os links do HTML
  async function pesqPaginaInteira() {
    pesqStatus.textContent = '⬆ Mandando a página inteira pro site…';
    const html = document.documentElement.outerHTML;
    const r = await postar(`/pesquisas/${encodeURIComponent(DEST.p)}/colar`, { texto: html, pagina: pesqPagina() });
    if (!r.ok) { pesqStatus.textContent = '⚠ ' + r.erro; return; }
    const d = r.d || {};
    pesqStatus.textContent = `✔ ${d.achados || 0} link(s) achados na página · ${d.novos || 0} novo(s) no site${d.repetidos ? ` · ${d.repetidos} já estavam` : ''}. No site dá pra desmarcar os que não servem.`;
  }
  function pesqCaixinhas() {
    pesqItens().forEach((it) => {
      if (it.tit.querySelector('.gcl-pchk') || (it.bloco && it.bloco.querySelector('.gcl-pchk[data-u="' + CSS.escape(it.url) + '"]'))) return;
      const c = pesqEl('span', { class: 'gcl-pchk' + (pesqMarcados.has(it.url) ? ' on' : '') + (pesqEnviados.has(it.url) ? ' ok' : ''), title: 'marcar pra mandar ao site', 'data-u': it.url });
      c.addEventListener('click', (e) => {
        e.preventDefault(); e.stopPropagation();
        if (pesqMarcados.has(it.url)) pesqMarcados.delete(it.url); else pesqMarcados.add(it.url);
        c.classList.toggle('on', pesqMarcados.has(it.url)); pesqAtualizar();
      }, true);
      it.tit.prepend(c);
    });
  }
  function pesqPagina() { const s = +(new URLSearchParams(location.search).get('start') || 0); return String(Math.floor(s / 10) + 1); }
  // /goto?url=… → o link de verdade (o navegador segue o redirecionamento como num clique; o site tenta de novo os que faltarem)
  function pesqResolver(url) {
    if (!/\/goto\?/.test(url) || !_gmx) return Promise.resolve(url);
    const fora = (u) => { try { const h = new URL(u).hostname; return !/(^|\.)google\./.test(h) ? u : ''; } catch { return ''; } };
    return new Promise((fim) => {
      const tentar = (metodo) => _gmx({ method: metodo, url, timeout: 15000,
        onload: (x) => {
          const f = fora(x.finalUrl || '');
          if (f) return fim(f);
          const html = String(x.responseText || '');
          const m = html.match(/http-equiv=["']?refresh["']?[^>]*?url=['"]?([^"'>\s]+)/i) || html.match(/location\.(?:replace|assign)\(\s*["']([^"']+)/) || html.match(/href="(https?:\/\/(?![a-z.]*google\.)[^"]+)"/);
          if (m) return fim(fora(m[1].replace(/&amp;/g, '&')) || url);
          if (metodo === 'HEAD') return tentar('GET');
          fim(url);
        },
        onerror: () => (metodo === 'HEAD' ? tentar('GET') : fim(url)), ontimeout: () => fim(url) });
      tentar('HEAD');
    });
  }
  async function pesqEnviar(depois) {
    const escolhidos = pesqItens().filter((it) => pesqMarcados.has(it.url) && !pesqEnviados.has(it.url));
    const gotos = escolhidos.filter((it) => /\/goto\?/.test(it.url)).length;
    if (gotos) pesqStatus.textContent = `🔗 descobrindo o link de verdade de ${gotos} resultado(s)…`;
    const reais = await Promise.all(escolhidos.map((it) => pesqResolver(it.url)));
    const itens = escolhidos.map((it, k) => ({ url: reais[k], titulo: it.titulo, fonte: it.fonte, trecho: it.trecho, data: it.data, cite: it.cite }));
    if (!itens.length) { pesqStatus.textContent = pesqMarcados.size ? 'Os marcados já foram enviados.' : 'Marque os resultados na caixinha ☐.'; if (depois) depois(); return; }
    pesqStatus.textContent = `⬆ Mandando ${itens.length}…`;
    const r = await postar(`/pesquisas/${encodeURIComponent(DEST.p)}/resultados`, { itens, pagina: pesqPagina() });
    if (!r.ok) { pesqStatus.textContent = '⚠ ' + r.erro; return; }
    escolhidos.forEach((x) => pesqEnviados.add(x.url));
    document.querySelectorAll('.gcl-pchk.on').forEach((c) => c.classList.add('ok'));
    const d = r.d || {};
    pesqStatus.textContent = `✔ ${d.novos ?? itens.length} novo(s) no site${d.repetidos ? ` · ${d.repetidos} já estavam` : ''} · total: ${d.total ?? '?'}`;
    if (depois) setTimeout(depois, 500);
  }
  function pesqPainel() {
    if (document.getElementById('gcl-painel')) return;
    const p = pesqEl('div', { id: 'gcl-painel' },
      pesqEl('div', { id: 'gcl-topo' }, pesqEl('b', {}, '📰 Enviar ao site'), pesqEl('button', { id: 'gcl-min', title: 'Minimizar' }, '–')),
      pesqEl('div', { id: 'gcl-corpo' },
        pesqEl('div', { id: 'gcl-dest' }, 'Para: ', pesqEl('b', {}, DEST.r || 'a pesquisa')),
        pesqEl('button', { class: 'principal', id: 'gcl-penviar' }, 'Enviar ao site (', (pesqCont = pesqEl('span', {}, '0')), ')'),
        pesqEl('div', { class: 'linha' }, pesqEl('button', { id: 'gcl-ptodos' }, 'Marcar todos'), pesqEl('button', { id: 'gcl-pnenhum' }, 'Desmarcar')),
        pesqEl('div', { class: 'linha' }, pesqEl('button', { id: 'gcl-pprox', class: 'principal', style: 'background:#188038' }, 'Enviar e ir pra próxima página →')),
        pesqEl('div', { class: 'linha' }, pesqEl('button', { id: 'gcl-pinteira', title: 'manda TODOS os resultados desta página (o site lê o HTML) — use se as caixinhas não aparecerem' }, '🆘 Mandar todos desta página')),
        (pesqStatus = pesqEl('div', { id: 'gcl-status' }, 'Marque os resultados na caixinha ☐ (ou Marcar todos) e envie.'))));
    document.body.appendChild(p);
    p.querySelector('#gcl-min').onclick = () => p.classList.toggle('min');
    p.querySelector('#gcl-penviar').onclick = () => pesqEnviar();
    p.querySelector('#gcl-pinteira').onclick = () => pesqPaginaInteira();
    p.querySelector('#gcl-ptodos').onclick = () => { pesqItens().forEach((it) => pesqMarcados.add(it.url)); document.querySelectorAll('.gcl-pchk').forEach((c) => c.classList.add('on')); pesqAtualizar(); };
    p.querySelector('#gcl-pnenhum').onclick = () => { pesqMarcados.clear(); document.querySelectorAll('.gcl-pchk').forEach((c) => c.classList.remove('on')); pesqAtualizar(); };
    p.querySelector('#gcl-pprox').onclick = () => pesqEnviar(() => {
      const prox = document.querySelector('#pnnext, a[aria-label="Next page"], a[aria-label="Próxima página"]');
      if (prox) location.href = prox.href;
      else { const u = new URL(location.href); u.searchParams.set('start', String((+u.searchParams.get('start') || 0) + 10)); location.href = u.href; }
    });
  }
  const _cssPesq = `
    .gcl-pchk { display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; margin-right:8px; vertical-align:middle;
      border:2px solid #1a73e8; border-radius:6px; background:#fff; cursor:pointer; font:bold 14px/1 Arial,sans-serif; color:#fff; flex:none; }
    .gcl-pchk.on { background:#1a73e8; } .gcl-pchk.on::after { content:'✓'; }
    .gcl-pchk.ok { background:#188038; border-color:#188038; }
  `;
  function pesqIniciar() {
    if (!document.body) return false;
    try { GM_addStyle(_cssPesq); } catch { const st = document.createElement('style'); st.textContent = _cssPesq; (document.head || document.documentElement).appendChild(st); }
    pesqPainel();
    pesqCaixinhas();
    setTimeout(() => { const n = pesqItens().length;
      if (pesqStatus && !pesqMarcados.size) pesqStatus.textContent = n ? `${n} resultado(s) nesta página — marque na caixinha ☐ (ou Marcar todos) e envie.`
        : 'Não achei os resultados nesta página (o Google mudou o layout?) — use 🆘 Mandar todos desta página.'; }, 1500);
    return true;
  }

  // ===================== INICIALIZAÇÃO =====================
  function iniciar() {
    if (MODO_PESQ) { if (!document.getElementById('gcl-painel')) pesqIniciar(); else pesqCaixinhas(); return true; }
    if (!document.body || !document.querySelector(SEL.tile)) return false;
    criarPainel();
    adicionarCaixinhas();
    return true;
  }

  function comecar() {
    _estilo();
    let agendado = false;
    const obs = new MutationObserver(() => {
      if (agendado) return;
      agendado = true;
      setTimeout(() => { agendado = false; iniciar(); }, 400); // pega imagens novas do scroll infinito
    });
    obs.observe(document.body, { childList: true, subtree: true });
    iniciar();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', comecar, { once: true }); else comecar();
})();