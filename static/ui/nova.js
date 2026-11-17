/* 🧭 v84_405 — a interface nova: procurar ferramenta (Ctrl+K), favoritos e páginas recentes (guardados no navegador). */
(function () {
  'use strict';
  const D = document;
  const LS = {
    get(k, d) { try { const v = JSON.parse(localStorage.getItem(k) || 'null'); return v == null ? d : v; } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) { /* sem storage */ } },
  };
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const sem = (t) => String(t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  let IDX = [];
  try { IDX = JSON.parse((D.getElementById('nvIndice') || {}).textContent || '[]'); } catch (_) {}
  IDX.forEach(x => { x.b = sem(x.n + ' ' + x.d + ' ' + x.p + ' ' + x.g); x.nb = sem(x.n); });

  /* ---------------------------------------------------------------- menu: na primeira vez, só o grupo da página aberto
     (o ui.js guarda quais você abriu/fechou depois; o grupo da página atual sempre abre) */
  try {
    if (!localStorage.getItem('nv-menu-iniciado')) {
      const fech = new Set((localStorage.getItem('ui-menu-fechados') || '').split('|').filter(Boolean));
      D.querySelectorAll('.app-nav .grupo[data-grupo^="nv-"]').forEach(g => fech.add(g.dataset.grupo));
      localStorage.setItem('ui-menu-fechados', [...fech].join('|'));
      localStorage.setItem('nv-menu-iniciado', '1');
    }
  } catch (_) { /* sem storage */ }

  /* ---------------------------------------------------------------- recentes */
  const aqui = IDX.filter(x => location.pathname === x.u || location.pathname.startsWith(x.u.replace(/\/$/, '') + '/'))
    .sort((a, b) => b.u.length - a.u.length)[0];
  if (aqui) {
    const rec = LS.get('nv-recentes', []).filter(r => r.u !== aqui.u);
    rec.unshift({u: aqui.u, n: aqui.n, i: aqui.i});
    LS.set('nv-recentes', rec.slice(0, 12));
  }

  /* ---------------------------------------------------------------- favoritos */
  function desenharFavs() {
    const favs = LS.get('nv-favs', []), box = D.querySelector('[data-nv-favs]');
    if (box) {
      box.innerHTML = favs.map(f => `<li><a class="item${location.pathname === f.u ? ' ativo' : ''}" href="${esc(f.u)}" title="${esc(f.n)}"><i class="ii fa-solid fa-${esc(f.i || 'star')}"></i><span class="itxt">${esc(f.n)}</span></a></li>`).join('');
      box.closest('.grupo').hidden = !favs.length;
    }
    D.querySelectorAll('[data-nv-fav]').forEach(b => {
      const on = favs.some(f => f.u === b.dataset.nvFav);
      b.classList.toggle('on', on);
      b.querySelector('i').className = (on ? 'fa-solid' : 'fa-regular') + ' fa-star';
      b.querySelector('span').textContent = on ? 'Nos favoritos' : 'Favoritar';
    });
  }
  D.querySelectorAll('[data-nv-fav]').forEach(b => b.addEventListener('click', () => {
    let favs = LS.get('nv-favs', []);
    if (favs.some(f => f.u === b.dataset.nvFav)) favs = favs.filter(f => f.u !== b.dataset.nvFav);
    else favs.push({u: b.dataset.nvFav, n: b.dataset.nome, i: b.dataset.icone});
    LS.set('nv-favs', favs); desenharFavs();
  }));
  desenharFavs();

  /* ---------------------------------------------------------------- Ctrl+K */
  const pal = D.getElementById('nvPaleta'), q = D.getElementById('nvPaletaQ'), lista = D.getElementById('nvPaletaLista');
  let res = [], sel = 0;
  function buscar() {
    const termos = sem(q.value).split(/\s+/).filter(Boolean);
    if (!termos.length) {  // sem nada digitado: recentes + favoritos primeiro
      const pri = [...LS.get('nv-favs', []), ...LS.get('nv-recentes', [])].map(r => r.u);
      res = [...new Set(pri)].map(u => IDX.find(x => x.u === u)).filter(Boolean).concat(IDX.filter(x => !pri.includes(x.u))).slice(0, 12);
    } else {
      res = IDX.map(x => {
        if (!termos.every(t => x.b.includes(t))) return null;
        let nota = 0; termos.forEach(t => { if (x.nb.startsWith(t)) nota += 3; else if (x.nb.includes(t)) nota += 2; else nota += 1; });
        return [nota, x];
      }).filter(Boolean).sort((a, b) => b[0] - a[0]).map(a => a[1]).slice(0, 12);
    }
    sel = 0; desenhar();
  }
  function desenhar() {
    lista.innerHTML = res.length ? res.map((x, k) => `<li class="${k === sel ? 'sel' : ''}"><a href="${esc(x.u)}"><i class="fa-solid fa-${esc(x.i)}"></i><span><b>${esc(x.n)}</b><small>${esc(x.g)} · ${esc(x.d)}</small></span></a></li>`).join('')
      : '<li class="nv-vazio">Nada com esse nome — tente outra palavra.</li>';
    const s = lista.querySelector('.sel'); if (s) s.scrollIntoView({block: 'nearest'});
  }
  function abrir() { if (!pal) return; pal.hidden = false; q.value = ''; q.focus(); buscar(); }
  function fechar() { if (pal) pal.hidden = true; }
  D.querySelectorAll('[data-nv-busca]').forEach(b => b.addEventListener('click', abrir));
  if (pal) {
    pal.addEventListener('click', (e) => { if (e.target === pal) fechar(); });
    q.addEventListener('input', buscar);
    q.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { sel = Math.min(res.length - 1, sel + 1); desenhar(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { sel = Math.max(0, sel - 1); desenhar(); e.preventDefault(); }
      else if (e.key === 'Enter' && res[sel]) { location.href = res[sel].u; }
      else if (e.key === 'Escape') fechar();
    });
  }
  D.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); if (pal && pal.hidden) abrir(); else fechar(); }
  });
})();
