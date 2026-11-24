// ==UserScript==
// @name         YouTube - Copiar / Baixar Transcrição
// @namespace    https://github.com/local/yt-transcricao
// @version      1.4.0
// @description  Botão ao lado do Like que abre a transcrição e permite copiar ou baixar (.txt), com ou sem timestamps. 📦 Lote: várias transcrições num .zip.
// @match        https://www.youtube.com/*
// @run-at       document-idle
// @grant        none
// @updateURL    __SITE__/navegador-imagens/youtube-transcricao.user.js
// @downloadURL  __SITE__/navegador-imagens/youtube-transcricao.user.js
// ==/UserScript==

(function () {
  'use strict';

  const BTN_ID = 'yt-transcript-tools-btn';
  const MENU_ID = 'yt-transcript-tools-menu';

  /* ---------- utilidades ---------- */
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function waitFor(fn, timeout = 8000, step = 150) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      const v = fn();
      if (v) return v;
      await sleep(step);
    }
    return null;
  }

  function toast(msg) {
    let el = document.getElementById('yt-tt-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'yt-tt-toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove('show'), 2500);
  }

  /* ---------- estilos ---------- */
  const style = document.createElement('style');
  style.textContent = `
    #${BTN_ID} {
      display: inline-flex !important; align-items: center; gap: 6px; flex-shrink: 0 !important;
      width: auto !important; min-width: max-content !important; overflow: visible !important;
      height: 36px; padding: 0 14px; margin-right: 8px; font-size: 14px !important;
      border: none; border-radius: 18px; cursor: pointer;
      font: 500 14px/36px Roboto, Arial, sans-serif;
      pointer-events: auto; position: relative; z-index: 10;
      color: var(--yt-spec-text-primary, #fff);
      background: var(--yt-spec-badge-chip-background, rgba(255,255,255,.1));
      white-space: nowrap;
    }
    #${BTN_ID}:hover { background: var(--yt-spec-button-chip-background-hover, rgba(255,255,255,.2)); }
    #${BTN_ID}[disabled] { opacity: .6; cursor: progress; }
    #${MENU_ID} {
      position: fixed; z-index: 99999; display: none; min-width: 230px;
      padding: 8px 0; border-radius: 12px;
      background: var(--yt-spec-menu-background, #282828);
      color: var(--yt-spec-text-primary, #fff);
      box-shadow: 0 4px 32px rgba(0,0,0,.5);
      font: 400 14px Roboto, Arial, sans-serif;
    }
    #${MENU_ID} .yt-tt-item { padding: 10px 16px; cursor: pointer; }
    #${MENU_ID} .yt-tt-item:hover { background: var(--yt-spec-10-percent-layer, rgba(255,255,255,.1)); }
    #${MENU_ID} .yt-tt-sep { height: 1px; margin: 6px 0; background: var(--yt-spec-10-percent-layer, rgba(255,255,255,.15)); }
    #yt-tt-toast {
      position: fixed; left: 50%; bottom: 40px; transform: translateX(-50%);
      padding: 10px 18px; border-radius: 8px; z-index: 100000;
      background: #323232; color: #fff; font: 14px Roboto, Arial, sans-serif;
      opacity: 0; pointer-events: none; transition: opacity .2s;
    }
    #yt-tt-toast.show { opacity: 1; }
    #yt-tt-overlay {
      position: fixed; inset: 0; z-index: 100001; display: flex;
      align-items: center; justify-content: center; background: rgba(0,0,0,.6);
    }
    #yt-tt-overlay .yt-tt-box {
      width: min(440px, 92vw); padding: 20px; border-radius: 14px;
      background: var(--yt-spec-menu-background, #282828);
      color: var(--yt-spec-text-primary, #fff);
      font: 400 14px Roboto, Arial, sans-serif; box-shadow: 0 8px 40px rgba(0,0,0,.6);
    }
    #yt-tt-overlay h3 { margin: 0 0 14px; font: 500 18px Roboto, Arial, sans-serif; }
    #yt-tt-overlay label.yt-tt-lbl { display: block; margin: 12px 0 4px; opacity: .8; }
    #yt-tt-overlay select {
      width: 100%; padding: 8px; border-radius: 8px; border: 1px solid rgba(255,255,255,.25);
      background: var(--yt-spec-base-background, #0f0f0f); color: inherit; font: inherit;
    }
    #yt-tt-overlay select:disabled { opacity: .5; }
    #yt-tt-overlay .yt-tt-check { display: flex; align-items: center; gap: 8px; margin-top: 14px; cursor: pointer; }
    #yt-tt-overlay .yt-tt-status { min-height: 20px; margin-top: 12px; opacity: .85; }
    #yt-tt-overlay .yt-tt-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; flex-wrap: wrap; }
    #yt-tt-overlay .yt-tt-actions button {
      padding: 8px 14px; border: none; border-radius: 18px; cursor: pointer;
      font: 500 14px Roboto, Arial, sans-serif; color: inherit;
      background: var(--yt-spec-badge-chip-background, rgba(255,255,255,.12));
    }
    #yt-tt-overlay .yt-tt-actions button.primary { background: #3ea6ff; color: #0f0f0f; }
    #yt-tt-overlay .yt-tt-actions button[disabled] { opacity: .5; cursor: progress; }
  `;
  document.head.appendChild(style);

  /* ---------- extração da transcrição ---------- */
  function readSegments() {
    const out = [];

    // Layout novo (view-model)
    document.querySelectorAll('transcript-segment-view-model').forEach((seg) => {
      const time = seg.querySelector('.ytwTranscriptSegmentViewModelTimestamp');
      const text = seg.querySelector('span[role="text"]');
      if (text && text.textContent.trim()) {
        out.push({
          time: time ? time.textContent.trim() : '',
          text: text.textContent.replace(/\s+/g, ' ').trim(),
        });
      }
    });
    if (out.length) return out;

    // Layout antigo
    document.querySelectorAll('ytd-transcript-segment-renderer').forEach((seg) => {
      const time = seg.querySelector('.segment-timestamp');
      const text = seg.querySelector('.segment-text');
      if (text && text.textContent.trim()) {
        out.push({
          time: time ? time.textContent.trim() : '',
          text: text.textContent.replace(/\s+/g, ' ').trim(),
        });
      }
    });
    return out;
  }

  async function ensureTranscriptOpen() {
    // Já aberta?
    let segs = readSegments();
    if (segs.length) return segs;

    // 1) Expande a descrição, se necessário
    const getShowBtn = () =>
      document.querySelector(
        'ytd-video-description-transcript-section-renderer #primary-button button'
      );

    if (!getShowBtn()) {
      const expand =
        document.querySelector('ytd-watch-metadata #description-inline-expander #expand') ||
        document.querySelector('#description-inline-expander #expand') ||
        document.querySelector('ytd-text-inline-expander #expand') ||
        document.querySelector('#description #expand');
      if (expand) expand.click();
    }

    // 2) Clica em "Mostrar transcrição"
    const showBtn = await waitFor(getShowBtn, 4000);
    if (!showBtn) return null;
    showBtn.click();

    // 3) Espera os segmentos aparecerem
    segs = await waitFor(() => {
      const s = readSegments();
      return s.length ? s : null;
    }, 10000);
    if (!segs) return null;

    // Aguarda estabilizar (carregamento incremental)
    let last = segs.length;
    for (let i = 0; i < 5; i++) {
      await sleep(250);
      const n = readSegments().length;
      if (n === last) break;
      last = n;
    }
    return readSegments();
  }

  function buildText(segments, withTime) {
    return segments
      .map((s) => (withTime && s.time ? `[${s.time}] ${s.text}` : s.text))
      .join(withTime ? '\n' : ' ');
  }

  function videoTitle() {
    const el =
      document.querySelector('ytd-watch-metadata h1 yt-formatted-string') ||
      document.querySelector('h1.ytd-watch-metadata');
    const t = (el && el.textContent.trim()) || document.title.replace(/ - YouTube$/, '');
    return t.replace(/[\\/:*?"<>|]+/g, '').slice(0, 120) || 'transcricao';
  }

  /* ---------- ações ---------- */
  async function copyToClipboard(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
  }

  function download(text, filename) {
    const blob = new Blob(['\ufeff' + text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  /* ---------- legendas (quando não há transcrição) ---------- */
  function h(tag, props = {}, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === 'class') e.className = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (k in e) e[k] = v;
      else e.setAttribute(k, v);
    }
    kids.flat().forEach((c) => e.append(c));
    return e;
  }

  function getPlayerResponse() {
    const p = document.getElementById('movie_player');
    let pr = null;
    try { pr = p && p.getPlayerResponse && p.getPlayerResponse(); } catch (e) { /* ignora */ }
    if (pr && pr.captions) return pr;
    return window.ytInitialPlayerResponse || null;
  }

  function getCaptionData() {
    const pr = getPlayerResponse();
    const r = pr && pr.captions && pr.captions.playerCaptionsTracklistRenderer;
    if (!r || !r.captionTracks || !r.captionTracks.length) return null;
    return { tracks: r.captionTracks, langs: r.translationLanguages || [] };
  }

  function textOf(n) {
    if (!n) return '';
    return n.simpleText || (n.runs || []).map((x) => x.text).join('');
  }

  function trackLabel(t) {
    let l = textOf(t.name) || t.languageCode;
    if (t.kind === 'asr' && !/auto/i.test(l)) l += ' (automática)';
    return l;
  }

  function fmtTime(ms) {
    const s = Math.floor(ms / 1000);
    const hh = Math.floor(s / 3600);
    const mm = Math.floor((s % 3600) / 60);
    const ss = String(s % 60).padStart(2, '0');
    return hh ? `${hh}:${String(mm).padStart(2, '0')}:${ss}` : `${mm}:${ss}`;
  }

  async function tryFetchCaptions(url) {
    try {
      const res = await fetch(url, { credentials: 'include' });
      const txt = await res.text();
      if (!txt) return null;
      const data = JSON.parse(txt);
      const out = [];
      for (const ev of data.events || []) {
        if (!ev.segs) continue;
        const text = ev.segs.map((s) => s.utf8 || '').join('').replace(/\s+/g, ' ').trim();
        if (text) out.push({ time: fmtTime(ev.tStartMs || 0), text });
      }
      return out.length ? out : null;
    } catch (e) {
      return null;
    }
  }

  // Plano B: o YouTube às vezes exige um token (pot) na URL da legenda.
  // Fazemos o próprio player pedir a legenda e reaproveitamos a URL dele.
  async function captureUrlViaPlayer(track, tlang) {
    const player = document.getElementById('movie_player');
    if (!player || !player.setOption) return null;

    const matches = (name) => {
      if (!name.includes('/api/timedtext')) return false;
      const u = new URL(name);
      if (u.searchParams.get('lang') !== track.languageCode) return false;
      const t = u.searchParams.get('tlang');
      return tlang ? t === tlang : !t;
    };
    const find = () => {
      const list = performance.getEntriesByType('resource').filter((e) => matches(e.name));
      return list.length ? list[list.length - 1].name : null;
    };

    let prev = null;
    try { prev = player.getOption('captions', 'track'); } catch (e) { /* ignora */ }
    const wasOn = prev && prev.languageCode;

    try {
      player.loadModule('captions');
      const opt = { languageCode: track.languageCode };
      if (track.kind) opt.kind = track.kind;
      if (tlang) opt.translationLanguage = { languageCode: tlang };
      player.setOption('captions', 'track', opt);
    } catch (e) { /* ignora */ }

    const url = await waitFor(find, 7000, 250);

    try {
      if (wasOn) player.setOption('captions', 'track', prev);
      else player.unloadModule('captions');
    } catch (e) { /* ignora */ }

    return url;
  }

  async function fetchCaptions(track, tlang) {
    const build = (base) => {
      const u = new URL(base, location.origin);
      u.searchParams.set('fmt', 'json3');
      if (tlang) u.searchParams.set('tlang', tlang);
      else u.searchParams.delete('tlang');
      return u.toString();
    };
    let segs = await tryFetchCaptions(build(track.baseUrl));
    if (!segs) {
      const captured = await captureUrlViaPlayer(track, tlang);
      if (captured) segs = await tryFetchCaptions(build(captured));
    }
    return segs;
  }

  function closeCaptionsDialog() {
    const o = document.getElementById('yt-tt-overlay');
    if (o) o.remove();
    document.removeEventListener('keydown', onDialogKey, true);
  }
  function onDialogKey(e) {
    if (e.key === 'Escape') closeCaptionsDialog();
  }

  function openCaptionsDialog(defaultWithTime = true, note = '') {
    closeCaptionsDialog();
    const data = getCaptionData();
    const box = h('div', { class: 'yt-tt-box' });
    const overlay = h('div', { id: 'yt-tt-overlay' }, box);
    overlay.addEventListener('mousedown', (e) => {
      if (e.target === overlay) closeCaptionsDialog();
    });

    box.append(h('h3', {}, 'Legendas do vídeo'));
    if (note) box.append(h('div', { class: 'yt-tt-status' }, note));

    if (!data) {
      box.append(h('div', { class: 'yt-tt-status' }, 'Este vídeo não tem transcrição nem legendas disponíveis.'));
      box.append(h('div', { class: 'yt-tt-actions' }, h('button', { onclick: closeCaptionsDialog }, 'Fechar')));
      document.body.appendChild(overlay);
      document.addEventListener('keydown', onDialogKey, true);
      return;
    }

    const trackSel = h('select', {}, data.tracks.map((t, i) => h('option', { value: String(i) }, trackLabel(t))));
    const langSel = h(
      'select',
      {},
      h('option', { value: '' }, 'Sem tradução (idioma da legenda)'),
      data.langs.map((l) => h('option', { value: l.languageCode }, textOf(l.languageName) || l.languageCode))
    );
    const tsBox = h('input', { type: 'checkbox', checked: !!defaultWithTime });
    const status = h('div', { class: 'yt-tt-status' });

    const syncLang = () => {
      const t = data.tracks[+trackSel.value];
      const can = t.isTranslatable !== false && data.langs.length > 0;
      langSel.disabled = !can;
      if (!can) langSel.value = '';
    };
    trackSel.addEventListener('change', syncLang);
    syncLang();

    const btnCopy = h('button', { class: 'primary' }, 'Copiar');
    const btnDl = h('button', {}, 'Baixar .txt');
    const btnClose = h('button', { onclick: closeCaptionsDialog }, 'Fechar');

    const go = async (action) => {
      const track = data.tracks[+trackSel.value];
      const tlang = langSel.value || '';
      btnCopy.disabled = btnDl.disabled = true;
      status.textContent = 'Baixando legenda…';
      const segs = await fetchCaptions(track, tlang);
      btnCopy.disabled = btnDl.disabled = false;
      if (!segs) {
        status.textContent = 'Não consegui baixar essa legenda. Tente outra faixa ou idioma.';
        return;
      }
      const text = buildText(segs, tsBox.checked);
      if (action === 'copy') {
        await copyToClipboard(text);
        status.textContent = 'Legenda copiada!';
      } else {
        const tag = track.languageCode + (tlang ? '-' + tlang : '');
        download(text, `${videoTitle()} [${tag}]${tsBox.checked ? ' (com timestamps)' : ''}.txt`);
        status.textContent = 'Download iniciado!';
      }
    };
    btnCopy.addEventListener('click', () => go('copy'));
    btnDl.addEventListener('click', () => go('download'));

    box.append(
      h('label', { class: 'yt-tt-lbl' }, 'Faixa de legenda'),
      trackSel,
      h('label', { class: 'yt-tt-lbl' }, 'Traduzir para'),
      langSel,
      h('label', { class: 'yt-tt-check' }, tsBox, 'Incluir timestamps'),
      status,
      h('div', { class: 'yt-tt-actions' }, btnClose, btnDl, btnCopy)
    );

    document.body.appendChild(overlay);
    document.addEventListener('keydown', onDialogKey, true);
  }

  /* ---------- fechar painel ---------- */
  const PREF_KEY = 'yt-tt-close-after';
  const getCloseAfter = () => {
    try { return localStorage.getItem(PREF_KEY) !== '0'; } catch (e) { return true; }
  };
  const setCloseAfter = (v) => {
    try { localStorage.setItem(PREF_KEY, v ? '1' : '0'); } catch (e) { /* ignora */ }
  };

  function closeTranscriptPanel() {
    const panel =
      document.querySelector('ytd-engagement-panel-section-list-renderer[target-id="PAmodern_transcript_view"]') ||
      document.querySelector('ytd-engagement-panel-section-list-renderer[target-id*="transcript"]');
    if (!panel) return;
    const closeBtn =
      panel.querySelector('#visibility-button button') ||
      panel.querySelector('button[aria-label="Fechar"], button[aria-label="Close"]');
    if (closeBtn) closeBtn.click();
  }

  async function run(action, withTime) {
    const btn = document.getElementById(BTN_ID);
    if (btn) btn.setAttribute('disabled', '');
    try {
      toast('Carregando transcrição…');
      const segments = await ensureTranscriptOpen();
      if (!segments || !segments.length) {
        toast('Sem transcrição neste vídeo. Tentando as legendas…');
        openCaptionsDialog(withTime, 'Este vídeo não tem transcrição. Escolha uma legenda:');
        return;
      }
      const text = buildText(segments, withTime);
      if (action === 'copy') {
        await copyToClipboard(text);
        toast('Transcrição copiada!');
      } else {
        download(text, `${videoTitle()}${withTime ? ' (com timestamps)' : ''}.txt`);
        toast('Download iniciado!');
      }
      if (getCloseAfter()) {
        await sleep(300);
        closeTranscriptPanel();
      }
    } catch (err) {
      console.error('[YT Transcrição]', err);
      toast('Erro ao processar a transcrição.');
    } finally {
      if (btn) btn.removeAttribute('disabled');
    }
  }

  /* ---------- 📦 LOTE: várias transcrições de uma vez → um .zip (v1.3) ---------- */
  // Não abre vídeo nenhum: pra cada link, lê a página do vídeo em segundo plano e pede a transcrição
  // pro próprio YouTube (o mesmo pedido do botão "Mostrar transcrição"). Se o vídeo não tiver
  // transcrição, tenta a legenda (preferindo o idioma escolhido).

  // zip sem compressão (texto já é pequeno) — sem biblioteca externa
  const CRC_T = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();
  function crc32(bytes) {
    let c = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) c = CRC_T[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }
  function makeZip(files) { // files: [{name, text}]
    const enc = new TextEncoder();
    const parts = [], central = [];
    let offset = 0;
    const d = new Date();
    const dosTime = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
    const dosDate = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
    for (const f of files) {
      const name = enc.encode(f.name);
      const data = enc.encode('\ufeff' + f.text);
      const crc = crc32(data);
      const lh = new DataView(new ArrayBuffer(30));
      lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true); lh.setUint16(6, 0x0800, true); // UTF-8 nos nomes
      lh.setUint16(8, 0, true); lh.setUint16(10, dosTime, true); lh.setUint16(12, dosDate, true);
      lh.setUint32(14, crc, true); lh.setUint32(18, data.length, true); lh.setUint32(22, data.length, true);
      lh.setUint16(26, name.length, true); lh.setUint16(28, 0, true);
      parts.push(new Uint8Array(lh.buffer), name, data);
      const ch = new DataView(new ArrayBuffer(46));
      ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true); ch.setUint16(6, 20, true); ch.setUint16(8, 0x0800, true);
      ch.setUint16(10, 0, true); ch.setUint16(12, dosTime, true); ch.setUint16(14, dosDate, true);
      ch.setUint32(16, crc, true); ch.setUint32(20, data.length, true); ch.setUint32(24, data.length, true);
      ch.setUint16(28, name.length, true); ch.setUint32(42, offset, true);
      central.push(new Uint8Array(ch.buffer), name);
      offset += 30 + name.length + data.length;
    }
    const cdSize = central.reduce((a, b) => a + b.length, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
    end.setUint32(12, cdSize, true); end.setUint32(16, offset, true);
    return new Blob([...parts, ...central, new Uint8Array(end.buffer)], { type: 'application/zip' });
  }
  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }

  function videoIdOf(s) {
    s = String(s || '').trim();
    if (/^[\w-]{11}$/.test(s)) return s;
    try {
      const u = new URL(s, location.origin);
      if (u.searchParams.get('v')) return u.searchParams.get('v');
      const m = u.pathname.match(/\/(?:shorts|live|embed)\/([\w-]{11})/) || (u.hostname === 'youtu.be' && u.pathname.match(/\/([\w-]{11})/));
      if (m) return m[1];
    } catch (e) { /* ignora */ }
    const m = s.match(/(?:v=|youtu\.be\/|shorts\/)([\w-]{11})/);
    return m ? m[1] : null;
  }
  function idsFromText(text) {
    const out = [];
    String(text || '').split(/[\s,;]+/).forEach((p) => { const id = videoIdOf(p); if (id && !out.includes(id)) out.push(id); });
    return out;
  }
  function idsFromPage() { // os vídeos que estão na página (playlist, canal, busca, inscrições…)
    const out = [];
    document.querySelectorAll('a[href*="/watch?v="], a[href*="/shorts/"]').forEach((a) => {
      if (a.closest('#' + MENU_ID) || a.closest('#yt-tt-overlay')) return;
      const id = videoIdOf(a.href);
      if (id && !out.includes(id)) out.push(id);
    });
    return out;
  }

  function cfg(k) {
    try { return window.ytcfg && window.ytcfg.get ? window.ytcfg.get(k) : (window.ytcfg && window.ytcfg.data_ && window.ytcfg.data_[k]); }
    catch (e) { return undefined; }
  }
  function jsonAfter(html, marker) { // o JSON que vem logo depois de "var ytInitialData = " etc.
    const i = html.indexOf(marker);
    if (i < 0) return null;
    let j = html.indexOf('{', i), depth = 0, inStr = false, esc = false;
    if (j < 0) return null;
    for (let k = j; k < html.length; k++) {
      const c = html[k];
      if (inStr) { if (esc) esc = false; else if (c === '\\') esc = true; else if (c === '"') inStr = false; continue; }
      if (c === '"') inStr = true;
      else if (c === '{') depth++;
      else if (c === '}') { depth--; if (!depth) { try { return JSON.parse(html.slice(j, k + 1)); } catch (e) { return null; } } }
    }
    return null;
  }
  function findKey(obj, key, out = [], depth = 0) {
    if (!obj || typeof obj !== 'object' || depth > 60) return out;
    if (Array.isArray(obj)) { obj.forEach((x) => findKey(x, key, out, depth + 1)); return out; }
    for (const k of Object.keys(obj)) {
      if (k === key) out.push(obj[k]);
      findKey(obj[k], key, out, depth + 1);
    }
    return out;
  }
  function segsFromTranscriptResponse(data) {
    const out = [];
    for (const r of findKey(data, 'transcriptSegmentRenderer')) {
      const text = textOf(r.snippet).replace(/\s+/g, ' ').trim();
      if (!text) continue;
      const time = (r.startTimeText && textOf(r.startTimeText)) || fmtTime(+r.startMs || 0);
      out.push({ time, text });
    }
    return out;
  }

  async function transcriptOf(id, langPref) {
    const res = await fetch(`/watch?v=${id}&hl=${encodeURIComponent(cfg('HL') || 'pt')}`, { credentials: 'include' });
    if (!res.ok) throw new Error('a página do vídeo não abriu (' + res.status + ')');
    const html = await res.text();
    const player = jsonAfter(html, 'ytInitialPlayerResponse = ') || {};
    const initial = jsonAfter(html, 'ytInitialData = ') || {};
    const title = (player.videoDetails && player.videoDetails.title) || id;
    const channel = (player.videoDetails && player.videoDetails.author) || '';
    // 1) transcrição (o mesmo pedido do botão "Mostrar transcrição")
    const params = findKey(initial, 'getTranscriptEndpoint').map((e) => e && e.params).find(Boolean);
    if (params) {
      try {
        const r = await fetch(`/youtubei/v1/get_transcript?prettyPrint=false`, {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'application/json', 'X-Youtube-Client-Name': String(cfg('INNERTUBE_CONTEXT_CLIENT_NAME') || 1),
                     'X-Youtube-Client-Version': String(cfg('INNERTUBE_CLIENT_VERSION') || '') },
          body: JSON.stringify({ context: cfg('INNERTUBE_CONTEXT') || { client: { clientName: 'WEB', clientVersion: cfg('INNERTUBE_CLIENT_VERSION') || '2.20250101.00.00', hl: 'pt' } }, params }),
        });
        if (r.ok) {
          const segs = segsFromTranscriptResponse(await r.json());
          if (segs.length) return { title, channel, segs, fonte: 'transcrição' };
        }
      } catch (e) { /* tenta a legenda */ }
    }
    // 2) legenda (preferindo o idioma escolhido; a manual antes da automática)
    const tracks = (((player.captions || {}).playerCaptionsTracklistRenderer || {}).captionTracks) || [];
    if (tracks.length) {
      const lp = (langPref || '').toLowerCase();
      const ord = [...tracks].sort((a, b) => {
        const sa = (a.languageCode.toLowerCase().startsWith(lp) ? 0 : 2) + (a.kind === 'asr' ? 1 : 0);
        const sb = (b.languageCode.toLowerCase().startsWith(lp) ? 0 : 2) + (b.kind === 'asr' ? 1 : 0);
        return sa - sb;
      });
      for (const t of ord.slice(0, 3)) {
        const u = new URL(t.baseUrl, location.origin);
        u.searchParams.set('fmt', 'json3');
        const segs = await tryFetchCaptions(u.toString());
        if (segs) return { title, channel, segs, fonte: 'legenda ' + t.languageCode + (t.kind === 'asr' ? ' (automática)' : '') };
      }
    }
    throw new Error(params || tracks.length ? 'o YouTube não entregou a transcrição/legenda' : 'sem transcrição nem legenda');
  }

  function safeName(s) {
    return String(s || '').replace(/[\\/:*?"<>|\u0000-\u001f]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 110) || 'video';
  }

  let LOTE_PARAR = false;
  const SITE = ('__SITE__'.startsWith('http') ? '__SITE__' : 'http://localhost:5050').replace(/\/$/, '');
  function openBatchDialog() {
    closeCaptionsDialog();
    const box = h('div', { class: 'yt-tt-box', style: 'width:min(560px,94vw)' });
    const overlay = h('div', { id: 'yt-tt-overlay' }, box);
    const ta = h('textarea', { rows: 7, placeholder: 'Cole os links (um por linha, ou separados por espaço) — vídeos, shorts ou youtu.be',
      style: 'width:100%;box-sizing:border-box;padding:8px;border-radius:8px;border:1px solid rgba(255,255,255,.25);background:var(--yt-spec-base-background,#0f0f0f);color:inherit;font:13px Roboto,Arial,sans-serif' });
    const count = h('div', { class: 'yt-tt-status' });
    const upd = () => { const n = idsFromText(ta.value).length; count.textContent = n ? `${n} vídeo(s) na lista` : ''; };
    ta.addEventListener('input', upd);
    const btnPage = h('button', { onclick: () => {
      const ids = idsFromPage();
      if (!ids.length) { count.textContent = 'Não achei vídeos nesta página (role a página pra carregar mais).'; return; }
      const atual = idsFromText(ta.value);
      ta.value = [...atual, ...ids.filter((i) => !atual.includes(i))].map((i) => 'https://www.youtube.com/watch?v=' + i).join('\n');
      upd();
    } }, '➕ Pegar os vídeos desta página');
    const modoSel = h('select', {},
      h('option', { value: 'zip' }, '📄 Só as transcrições (o .zip sai aqui mesmo)'),
      h('option', { value: 'video' }, '🎬 Vídeos + transcrições (o site BestEditor baixa e faz o .zip)'),
      h('option', { value: 'audio' }, '🎧 Só o áudio, na melhor qualidade + transcrições (pelo site)'));
    const qualSel = h('select', {}, ['1080p', '720p', '480p', '360p', 'melhor'].map((q) => h('option', { value: q }, 'Qualidade do vídeo: ' + q)));
    const qualBox = h('div', { style: 'display:none' }, h('label', { class: 'yt-tt-lbl' }, 'Qualidade'), qualSel);
    try { modoSel.value = localStorage.getItem('yt-tt-lote-modo') || 'zip'; } catch (e) { /* ignora */ }
    const syncModo = () => { qualBox.style.display = modoSel.value === 'video' ? '' : 'none';
      btnGo.textContent = modoSel.value === 'zip' ? '📦 Baixar tudo em .zip' : '📤 Mandar pro site baixar';
      try { localStorage.setItem('yt-tt-lote-modo', modoSel.value); } catch (e) { /* ignora */ } };
    modoSel.addEventListener('change', () => syncModo());
    const fmtSel = h('select', {},
      h('option', { value: 'ambos' }, '2 arquivos por vídeo: com e sem timestamps'),
      h('option', { value: 'com' }, 'Só com timestamps'),
      h('option', { value: 'sem' }, 'Só sem timestamps (texto corrido)'));
    const langSel = h('select', {},
      ['pt', 'en', 'es', 'de', 'fr', 'it', 'ja'].map((l) => h('option', { value: l }, 'Legenda preferida (se não tiver transcrição): ' + l)));
    try { langSel.value = (cfg('HL') || 'pt').slice(0, 2); } catch (e) { /* ignora */ }
    const status = h('div', { class: 'yt-tt-status', style: 'max-height:200px;overflow:auto;font-size:12px;white-space:pre-wrap' });
    const btnGo = h('button', { class: 'primary' }, '📦 Baixar tudo em .zip');
    const btnStop = h('button', { style: 'display:none' }, '⏹ Parar (baixa o que já foi)');
    const btnClose = h('button', { onclick: () => { LOTE_PARAR = true; closeCaptionsDialog(); } }, 'Fechar');
    btnStop.addEventListener('click', () => { LOTE_PARAR = true; btnStop.disabled = true; btnStop.textContent = 'parando…'; });

    btnGo.addEventListener('click', async () => {
      const ids = idsFromText(ta.value);
      if (!ids.length) { count.textContent = 'Cole pelo menos um link.'; return; }
      LOTE_PARAR = false;
      btnGo.disabled = true; btnStop.style.display = ''; btnStop.disabled = false; btnStop.textContent = '⏹ Parar (baixa o que já foi)';
      const files = [], falhas = [], nomes = new Set(), coletados = [];
      const log = (t) => { status.textContent += t + '\n'; status.scrollTop = status.scrollHeight; };
      status.textContent = '';
      for (let k = 0; k < ids.length && !LOTE_PARAR; k++) {
        const id = ids[k];
        count.textContent = `⏳ ${k + 1} de ${ids.length}…`;
        try {
          const r = await transcriptOf(id, langSel.value);
          let base = safeName(r.title), n = 2;
          while (nomes.has(base)) base = safeName(r.title) + ' (' + n++ + ')';
          nomes.add(base);
          const cab = `${r.title}\n${r.channel ? r.channel + ' — ' : ''}https://www.youtube.com/watch?v=${id}\n(${r.fonte})\n\n`;
          if (fmtSel.value !== 'sem') files.push({ name: `${base} (com timestamps).txt`, text: cab + buildText(r.segs, true) });
          if (fmtSel.value !== 'com') files.push({ name: `${base}.txt`, text: cab + buildText(r.segs, false) });
          coletados.push({ url: 'https://www.youtube.com/watch?v=' + id, titulo: r.title, canal: r.channel, fonte: r.fonte,
                           txt: fmtSel.value !== 'com' ? buildText(r.segs, false) : '', txt_ts: fmtSel.value !== 'sem' ? buildText(r.segs, true) : '' });
          log(`✔ ${r.title} — ${r.segs.length} trechos (${r.fonte})`);
        } catch (e) {
          falhas.push(`${id}: ${e.message || e}`);
          coletados.push({ url: 'https://www.youtube.com/watch?v=' + id, titulo: '', txt: '', txt_ts: '' });  // o site baixa o vídeo/áudio mesmo assim
          log(`✖ ${id}: ${e.message || e}` + (modoSel.value !== 'zip' ? ' (o vídeo/áudio vai mesmo assim)' : ''));
        }
        if (k < ids.length - 1 && !LOTE_PARAR) await sleep(1200 + Math.random() * 800); // devagar: o YouTube não gosta de rajada
      }
      btnStop.style.display = 'none'; btnGo.disabled = false;
      if (modoSel.value !== 'zip') { await mandarProSite(coletados, modoSel.value, qualSel.value, count, log); return; }
      const ok = files.length ? new Set(files.map((f) => f.name.replace(/ \(com timestamps\)\.txt$|\.txt$/, ''))).size : 0;
      if (!files.length) { count.textContent = '❌ Nenhuma transcrição saiu.'; return; }
      files.push({ name: '_resumo.txt', text: `${ok} de ${ids.length} vídeo(s) com transcrição.\n` +
        (falhas.length ? `\nSem transcrição:\n${falhas.join('\n')}\n` : '') });
      const d = new Date();
      const stamp = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}_${String(d.getHours()).padStart(2, '0')}${String(d.getMinutes()).padStart(2, '0')}`;
      downloadBlob(makeZip(files), `transcricoes_${stamp}.zip`);
      count.textContent = `✅ ${ok} de ${ids.length} no .zip` + (falhas.length ? ` · ${falhas.length} sem transcrição (lista no _resumo.txt)` : '') + (LOTE_PARAR ? ' · parado antes do fim' : '');
    });

    box.append(
      h('h3', {}, '📦 Transcrições em lote (.zip)'),
      ta, h('div', { class: 'yt-tt-actions', style: 'justify-content:flex-start;margin-top:8px' }, btnPage), count,
      h('label', { class: 'yt-tt-lbl' }, 'O que baixar'), modoSel, qualBox,
      h('label', { class: 'yt-tt-lbl' }, 'Transcrição'), fmtSel,
      h('label', { class: 'yt-tt-lbl' }, 'Sem transcrição'), langSel,
      status,
      h('div', { class: 'yt-tt-actions' }, btnClose, btnStop, btnGo)
    );
    if (location.pathname.startsWith('/watch')) { const id = videoIdOf(location.href); if (id) { ta.value = 'https://www.youtube.com/watch?v=' + id; upd(); } }
    syncModo();
    document.body.appendChild(overlay);
    document.addEventListener('keydown', onDialogKey, true);
  }

  // 🎬🎧 vídeo/áudio: quem baixa é o site BestEditor (yt-dlp) — o navegador não consegue baixar o vídeo do YouTube
  async function mandarProSite(videos, modo, qualidade, count, log) {
    if (!videos.length) { count.textContent = 'Nada pra mandar.'; return; }
    count.textContent = '📤 mandando pro site…';
    let d;
    try {
      const r = await fetch(SITE + '/transcrever/lote', { method: 'POST', headers: { 'Content-Type': 'text/plain' },
        body: JSON.stringify({ videos, modo, qualidade }) });
      d = await r.json();
      if (!r.ok || d.erro) throw new Error(d.erro || ('HTTP ' + r.status));
    } catch (e) {
      count.textContent = '❌ Não consegui falar com o site (' + SITE + '). Ele está aberto? Se o Brave perguntar, permita o acesso à rede local pro youtube.com. (' + (e.message || e) + ')';
      return;
    }
    log(`📤 ${videos.length} vídeo(s) mandados pro site — ele baixa um de cada vez e faz o .zip.`);
    const link = h('a', { href: d.pagina, target: '_blank', style: 'color:#3ea6ff' }, 'acompanhar no site');
    count.textContent = ''; count.append('⏳ o site está baixando… ', link);
    for (let k = 0; k < 2400; k++) {  // até ~2 h olhando
      await sleep(3000);
      let e;
      try { e = await (await fetch(SITE + '/transcrever/lote/' + d.id)).json(); } catch (err) { continue; }
      if (!e || e.erro) continue;
      const atual = (e.itens || []).find((i) => i.estado === 'baixando');
      count.textContent = `⏳ ${e.prontos} de ${e.total} prontos` + (atual ? ` — baixando: ${atual.titulo || atual.url}` : '') + ' · ';
      count.append(link);
      if (e.estado === 'pronto') {
        count.textContent = `✅ ${e.prontos} de ${e.total} prontos — `;
        const zip = h('a', { href: SITE + '/transcrever/lote/' + d.id + '/zip', style: 'color:#3ea6ff;font-weight:500' }, '⬇ baixar o .zip');
        count.append(zip);
        zip.click();
        return;
      }
      if (e.estado === 'erro') { count.textContent = '❌ o lote deu erro — veja no site. '; count.append(link); return; }
    }
  }

  // botão flutuante fora da página de vídeo (playlist, canal, busca…)
  function injectFloating() {
    let f = document.getElementById('yt-tt-float');
    const show = !location.pathname.startsWith('/watch');
    if (!f) {
      f = h('button', { id: 'yt-tt-float', title: 'Baixar as transcrições de vários vídeos num .zip', onclick: openBatchDialog }, '📦 Transcrições');
      f.style.cssText = 'position:fixed;right:18px;bottom:18px;z-index:9999;padding:9px 14px;border:none;border-radius:20px;cursor:pointer;' +
        'font:500 14px Roboto,Arial,sans-serif;background:#3ea6ff;color:#0f0f0f;box-shadow:0 4px 16px rgba(0,0,0,.4)';
      document.body.appendChild(f);
    }
    f.style.display = show ? '' : 'none';
  }

  /* ---------- menu ---------- */
  function getMenu() {
    let menu = document.getElementById(MENU_ID);
    if (menu) return menu;

    menu = document.createElement('div');
    menu.id = MENU_ID;

    const items = [
      ['Copiar com timestamps', 'copy', true],
      ['Copiar sem timestamps', 'copy', false],
      null,
      ['Baixar .txt com timestamps', 'download', true],
      ['Baixar .txt sem timestamps', 'download', false],
    ];

    items.forEach((it) => {
      if (!it) {
        const sep = document.createElement('div');
        sep.className = 'yt-tt-sep';
        menu.appendChild(sep);
        return;
      }
      const div = document.createElement('div');
      div.className = 'yt-tt-item';
      div.textContent = it[0];
      div.addEventListener('click', () => {
        menu.style.display = 'none';
        run(it[1], it[2]);
      });
      menu.appendChild(div);
    });

    // 📦 várias de uma vez
    const loteItem = document.createElement('div');
    loteItem.className = 'yt-tt-item';
    loteItem.textContent = '📦 Várias transcrições num .zip…';
    loteItem.addEventListener('click', () => { menu.style.display = 'none'; openBatchDialog(); });
    menu.appendChild(loteItem);

    // Legendas (faixa original, automática ou traduzida)
    const capItem = document.createElement('div');
    capItem.className = 'yt-tt-item';
    capItem.textContent = '🌐 Legendas (original / automática / traduzida)…';
    capItem.addEventListener('click', () => {
      menu.style.display = 'none';
      openCaptionsDialog(true);
    });
    menu.appendChild(capItem);

    // Opção: fechar o painel depois de copiar/baixar
    const sep2 = document.createElement('div');
    sep2.className = 'yt-tt-sep';
    menu.appendChild(sep2);

    const closeItem = document.createElement('div');
    closeItem.className = 'yt-tt-item';
    const render = () => {
      closeItem.textContent = (getCloseAfter() ? '☑' : '☐') + ' Fechar painel após copiar/baixar';
    };
    render();
    closeItem.addEventListener('click', (e) => {
      e.stopPropagation();
      setCloseAfter(!getCloseAfter());
      render();
    });
    menu.appendChild(closeItem);

    const closeNow = document.createElement('div');
    closeNow.className = 'yt-tt-item';
    closeNow.textContent = '✕ Fechar painel da transcrição agora';
    closeNow.addEventListener('click', () => {
      menu.style.display = 'none';
      closeTranscriptPanel();
    });
    menu.appendChild(closeNow);

    document.body.appendChild(menu);
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#' + MENU_ID) && !e.target.closest('#' + BTN_ID)) {
        menu.style.display = 'none';
      }
    });
    return menu;
  }

  function toggleMenu(btn) {
    const menu = getMenu();
    if (menu.style.display === 'block') {
      menu.style.display = 'none';
      return;
    }
    const r = btn.getBoundingClientRect();
    menu.style.top = r.bottom + 6 + 'px';
    menu.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 240)) + 'px';
    menu.style.display = 'block';
  }

  /* ---------- injeção do botão ---------- */
  function inject() {
    if (!location.pathname.startsWith('/watch')) return;
    if (document.getElementById(BTN_ID)) return;

    const container =
      document.querySelector('ytd-watch-metadata #top-level-buttons-computed') ||
      document.querySelector('#actions #top-level-buttons-computed');
    if (!container) return;

    const btn = document.createElement('button');
    btn.id = BTN_ID;
    btn.type = 'button';
    btn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" style="flex:none"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm4 18H6V4h7v5h5v11zM8 12h8v1.6H8V12zm0 3.4h8V17H8v-1.6zm0-6.8h4v1.6H8V8.6z"/></svg><span style="font-size:14px;line-height:36px">Transcrição</span><span style="font-size:11px;opacity:.8">▼</span>';
    btn.title = 'Copiar ou baixar a transcrição';
    // Captura os eventos antes que o YouTube os engula
    ['mousedown', 'mouseup', 'pointerdown', 'pointerup'].forEach((ev) =>
      btn.addEventListener(ev, (e) => e.stopPropagation())
    );
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleMenu(btn);
    });

    // Antes do botão de like
    container.insertBefore(btn, container.firstChild);
  }

  const obs = new MutationObserver(() => { inject(); injectFloating(); });
  obs.observe(document.body, { childList: true, subtree: true });
  document.addEventListener('yt-navigate-finish', () => setTimeout(() => { inject(); injectFloating(); }, 300));
  inject();
  injectFloating();
})();