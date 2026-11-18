/* 🕒 v84_413 — data/hora local + "há X min" que se atualiza. beTempo(obj) monta o mesmo selo nas listas feitas em JS. */
(function () {
  const C = ['criado', 'criado_em', 'criadoEm', 'created_at', 'created', 'criada', 'data_criacao', 'inicio', 'quando', 'ts'];
  const E = ['atualizado', 'atualizado_em', 'atualizadoEm', 'mudou', 'updated_at', 'updated', 'modificado', 'editado', 'mtime', 'fim', 'terminado'];
  const num = v => {
    if (v === null || v === undefined || v === '' || v === 0) return 0;
    if (typeof v === 'number') return v > 1e11 ? v / 1000 : v;
    const n = Number(v); if (!isNaN(n)) return num(n);
    const d = Date.parse(v); return isNaN(d) ? 0 : d / 1000;
  };
  const p2 = n => String(n).padStart(2, '0');
  function dataHora(ts, ano) {
    const t = num(ts); if (!t) return '';
    const d = new Date(t * 1000);
    if (ano === undefined) ano = d.getFullYear() !== new Date().getFullYear();
    return `${p2(d.getDate())}/${p2(d.getMonth() + 1)}${ano ? '/' + d.getFullYear() : ''} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
  }
  function haQuanto(ts) {
    const t = num(ts); if (!t) return '';
    const s = Math.max(0, Math.floor(Date.now() / 1000 - t));
    if (s < 60) return 'agora';
    const tab = [[3600, 60, 'min', 'min'], [86400, 3600, 'h', 'h'], [86400 * 30, 86400, 'dia', 'dias'], [86400 * 365, 86400 * 30, 'mês', 'meses']];
    for (const [lim, div, a, b] of tab) if (s < lim) { const n = Math.floor(s / div); return `há ${n} ${n === 1 ? a : b}`; }
    const n = Math.floor(s / (86400 * 365)); return `há ${n} ${n === 1 ? 'ano' : 'anos'}`;
  }
  const pega = (o, ks) => { for (const k of ks) { const t = num(o && o[k]); if (t) return t; } return 0; };
  function beTempo(o, editado) {
    let c, e;
    if (o && typeof o === 'object') { c = pega(o, C); e = pega(o, E); } else { c = num(o); e = num(editado); }
    if (!c && !e) return '';
    const partes = [];
    if (c) partes.push(`<span data-ts="${Math.round(c)}" data-rot="criado">criado ${dataHora(c)}</span>`);
    const mostraE = !!(e && (!c || e - c > 90));
    if (mostraE) partes.push(`<span data-ts="${Math.round(e)}" data-rot="editado" data-rel="1">editado ${haQuanto(e)}</span>`);
    const tit = [c ? 'criado em ' + dataHora(c, true) : '', mostraE ? 'editado em ' + dataHora(e, true) : ''].filter(Boolean).join(' · ');
    return `<span class="be-tempo" title="${tit}">🕒 ${partes.join(' · ')}</span>`;
  }
  function atualizar(raiz) {
    (raiz || document).querySelectorAll('.be-tempo [data-ts]').forEach(el => {
      const t = num(el.dataset.ts); if (!t) return;
      const txt = (el.dataset.rot ? el.dataset.rot + ' ' : '') + (el.dataset.rel ? haQuanto(t) : dataHora(t));
      if (el.textContent !== txt) el.textContent = txt;
    });
  }
  window.beTempo = beTempo; window.beDataHora = dataHora; window.beHaQuanto = haQuanto; window.beTempoAtualizar = atualizar;
  document.addEventListener('DOMContentLoaded', () => atualizar());
  setInterval(() => atualizar(), 60000);
  try { new MutationObserver(() => { clearTimeout(window.__beT); window.__beT = setTimeout(() => atualizar(), 300); })
    .observe(document.documentElement, { childList: true, subtree: true }); } catch (e) {}
})();
