/* 🧭 v84_405 — ⚙ Configurações em ABAS na interface nova.
   A página é a mesma (os mesmos campos e o mesmo "Salvar"); aqui cada seção vira um cartão, vai pra uma aba pelo
   título, ganha os atalhos "usado em → ferramenta" e cada aba mostra também as páginas de ajuste que ficam fora daqui
   (IA, contas Google, vozes…). /settings#flow abre direto na aba e na seção certa. */
(function () {
  'use strict';
  const D = document, raiz = D.querySelector('.app-content');
  let cfg = {abas: [], secoes: [], extras: []};
  try { cfg = JSON.parse(D.getElementById('nvAjustes').textContent); } catch (_) { return; }
  if (!raiz) return;
  raiz.setAttribute('data-sem-secoes', '');  // o ui.js não numera nem recolhe: aqui são abas
  D.querySelectorAll('.nv-so-classica').forEach(e => e.hidden = true);
  const sem = (t) => String(t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

  // 1. as seções: cada h2 (e o h3 das vinhetas) até o próximo título do mesmo nível
  const inicios = [...raiz.querySelectorAll('h2, h3#vinhetas')];
  const ehInicio = (n) => n.nodeType === 1 && (inicios.includes(n));
  const cartoes = [];
  inicios.forEach(h => {
    const mapa = cfg.secoes.find(s => sem(h.textContent).includes(sem(s.t)));
    const box = D.createElement('div');
    box.className = 'nv-ajuste';
    box.dataset.aba = mapa ? mapa.aba : 'geral';
    box.dataset.chave = mapa ? mapa.id : '';
    h.parentNode.insertBefore(box, h);
    let n = h;
    while (n) {
      const prox = n.nextSibling;
      box.appendChild(n);
      if (!prox || ehInicio(prox) || (prox.nodeType === 1 && (prox.matches('button[type=submit]') || inicios.some(x => prox.contains(x))))) break;
      n = prox;
    }
    if (mapa && !h.id && !D.getElementById(mapa.id)) h.id = mapa.id;
    if (mapa && mapa.links.length) {
      const u = D.createElement('div'); u.className = 'nv-usado-em';
      u.innerHTML = '<span>usado em:</span>' + mapa.links.map(l => `<a class="nv-chip" href="${esc(l.u)}"><i class="fa-solid fa-arrow-up-right-from-square"></i> ${esc(l.n)}</a>`).join('');
      h.insertAdjacentElement('afterend', u);
    }
    cartoes.push(box);
  });
  // o "Salvar configurações" fica sempre à mão
  const salvar = raiz.querySelector('form button[type=submit]');
  if (salvar && salvar.parentNode.tagName === 'FORM') {
    const f = D.createElement('div'); f.className = 'nv-salvar-fixo'; salvar.parentNode.insertBefore(f, salvar); f.appendChild(salvar);
  }
  // 2. o que não é seção mas tem aba (ex.: o resumo da IA)
  const soltos = [...raiz.querySelectorAll('[data-nv-aba]')];
  // 3. a barra de abas + os atalhos pras páginas de ajuste que ficam fora daqui
  const usadas = new Set(cartoes.map(c => c.dataset.aba).concat(soltos.map(s => s.dataset.nvAba)).concat(cfg.extras.map(e => e.aba)));
  const abas = cfg.abas.filter(a => usadas.has(a.id));
  const barra = D.createElement('div'); barra.className = 'nv-abas'; barra.setAttribute('role', 'tablist');
  barra.innerHTML = abas.map(a => `<button type="button" class="nv-aba" role="tab" data-aba="${a.id}"><i class="fa-solid fa-${a.icone}"></i> ${esc(a.nome)}</button>`).join('');
  const h1 = raiz.querySelector('h1');
  (h1 || raiz.firstChild).insertAdjacentElement(h1 ? 'afterend' : 'beforebegin', barra);
  const extras = {};
  abas.forEach(a => {
    const lista = cfg.extras.filter(e => e.aba === a.id);
    if (!lista.length) return;
    const box = D.createElement('div'); box.className = 'nv-extras'; box.dataset.abaExtra = a.id;
    box.innerHTML = lista.map(e => `<a class="nv-item" href="${esc(e.u)}" style="--g-cor: var(--acento)"><i class="fa-solid fa-arrow-up-right-from-square"></i><span><b>${esc(e.n)}</b><small>${esc(e.d)}</small></span></a>`).join('');
    barra.insertAdjacentElement('afterend', box);
    extras[a.id] = box;
  });
  const btnSalvar = raiz.querySelector('.nv-salvar-fixo');
  function mostrar(aba, rolarPara) {
    barra.querySelectorAll('.nv-aba').forEach(b => b.classList.toggle('on', b.dataset.aba === aba));
    cartoes.forEach(c => c.hidden = c.dataset.aba !== aba);
    soltos.forEach(s => s.hidden = s.dataset.nvAba !== aba);
    Object.entries(extras).forEach(([k, b]) => b.hidden = k !== aba);
    if (btnSalvar) btnSalvar.hidden = !cartoes.some(c => !c.hidden && c.closest('form'));
    try { sessionStorage.setItem('nv-aba-ajustes', aba); } catch (_) {}
    if (rolarPara) setTimeout(() => rolarPara.scrollIntoView({block: 'start'}), 30);
  }
  barra.addEventListener('click', (e) => { const b = e.target.closest('.nv-aba'); if (b) { mostrar(b.dataset.aba); history.replaceState(null, '', '#aba-' + b.dataset.aba); } });
  function pelaAncora() {
    const h = decodeURIComponent(location.hash.slice(1));
    if (h.startsWith('aba-') && abas.some(a => a.id === h.slice(4))) { mostrar(h.slice(4)); return true; }
    if (!h) return false;
    const alvo = D.getElementById(h);
    const c = alvo && cartoes.find(x => x.contains(alvo) || x === alvo) || cartoes.find(x => x.dataset.chave === h);
    if (c) { mostrar(c.dataset.aba, c); return true; }
    return false;
  }
  window.addEventListener('hashchange', pelaAncora);
  if (!pelaAncora()) {
    let ult = null; try { ult = sessionStorage.getItem('nv-aba-ajustes'); } catch (_) {}
    mostrar(abas.some(a => a.id === ult) ? ult : (abas[0] || {}).id);
  }
})();
