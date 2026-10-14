// Google Flow SIMULADO — o HTML é o REAL (capturado da página do Flow); este script só imita o comportamento:
// agente liga/desliga, painel do agente, pop-up de configurações, menus de modelo, Início/Fim, menu de mídia,
// "Iniciar geração" → cartão com % → imagem/vídeo. Parâmetros da URL: ?limite=1 (limite de uso), ?falha=1 (recusa), ?sem_credito=1 (sem créditos pra vídeo).
(function () {
  const Q = new URLSearchParams(location.search);
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const T = id => { const t = document.getElementById('t-' + id); const d = document.createElement('div'); d.innerHTML = t.innerHTML.trim(); return d.firstElementChild; };
  const st = { agente: true, modo: 'Imagem', tipoVideo: 'Elementos', prop: '16:9', qtd: 'x1',
               modeloImg: '🍌 Nano Banana 2.1', modeloVid: 'Veo 3.1 - Lite', midias: [], n: 0, origem: null, sel: null };
  window.__flowSim = st;
  const caixa = () => $('flow-prompt-box');
  const overlay = () => $('.cdk-overlay-container');
  const gatilho = () => $('flow-prompt-box button.settings-trigger-button');

  function marcar(btn) {  // botão de um mat-button-toggle-group
    const g = btn.closest('mat-button-toggle-group');
    $$('button.mat-button-toggle-button', g).forEach(b => { b.setAttribute('aria-checked', 'false'); b.closest('mat-button-toggle').classList.remove('mat-button-toggle-checked'); });
    btn.setAttribute('aria-checked', 'true'); btn.closest('mat-button-toggle').classList.add('mat-button-toggle-checked');
  }
  function marcarTexto(raiz, grupo, texto) {
    const b = $$(`flow-toggles[aria-label="${grupo}"] button.mat-button-toggle-button`, raiz).find(x => ($('.toggle-text', x) || {}).textContent.trim() === texto);
    if (b) marcar(b);
  }
  function resumo() {
    const g = gatilho(); if (!g) return;
    const txt = st.modo === 'Vídeo' ? ` Vídeo · 720p · 8s ${st.prop} ${st.qtd} ` : ` ${st.modeloImg} ${st.prop} ${st.qtd} `;
    $('.mdc-button__label', g).innerHTML = `<span settingstriggercontent="" class="settings-summary">${txt}</span>`;
  }
  function agente(ligado) {
    st.agente = ligado;
    const chip = $('flow-agent-mode-toggle-chip button.agent-mode-chip', caixa());
    chip.setAttribute('aria-pressed', String(ligado)); chip.classList.toggle('agent-mode-chip-checked', ligado);
    const pes = $('.agent-footer-actions', caixa()); if (pes) pes.hidden = !ligado;
    const g = gatilho(); if (ligado) g.setAttribute('hidden', ''); else { g.removeAttribute('hidden'); resumo(); }
  }
  function framesBar() {
    const linha = $('.prompt-top-row', caixa()); const barra = $('flow-ingredient-bar', caixa());
    const quer = st.modo === 'Vídeo' && st.tipoVideo === 'Frames';
    if (quer && !barra) { linha.classList.add('has-ingredient-bar'); linha.insertBefore(T('barra_frames'), linha.firstChild); }
    if (!quer && barra) { barra.remove(); linha.classList.remove('has-ingredient-bar'); }
  }
  function fecharMenusModelo() { $$('.cdk-overlay-pane.menu-modelos').forEach(e => e.remove()); }
  function fecharPopup() { fecharMenusModelo(); $$('.cdk-overlay-pane.popup-config').forEach(e => e.remove()); resumo(); }
  function abrirPopup() {
    fecharPopup();
    const pane = T(st.modo === 'Vídeo' ? 'popup_video' : 'popup_imagem'); pane.classList.add('popup-config');
    overlay().appendChild(pane);
    marcarTexto(pane, 'Modo', st.modo); marcarTexto(pane, 'Tipo de vídeo', st.tipoVideo);
    marcarTexto(pane, 'Proporção', st.prop); marcarTexto(pane, 'Quantidade de resultados', st.qtd);
    const m = $('.model-select-trigger-content', pane);
    if (m) m.firstChild.textContent = ' ' + (st.modo === 'Vídeo' ? st.modeloVid : st.modeloImg) + ' ';
    const cr = $('.credit-cost-link', pane); if (cr) cr.textContent = st.modo === 'Vídeo' ? '10 créditos' : '0 créditos';
  }
  function abrirMenuModelos(video, aoEscolher) {
    fecharMenusModelo();
    const pane = document.createElement('div'); pane.className = 'cdk-overlay-pane menu-modelos';
    pane.appendChild(T(video ? 'menu_modelos_video' : 'menu_modelos_imagem')); overlay().appendChild(pane);
    $$('flow-menu-item button', pane).forEach(b => b.addEventListener('click', ev => {
      ev.stopPropagation(); aoEscolher($('.label', b).textContent.trim()); fecharMenusModelo(); }));
  }
  // ---------------- menu de mídia (Início / Fim / +)
  function itemMidia(m) {
    return `<div class="asset-item-container"><button type="button" role="option" class="asset-item" aria-selected="false" data-id="${m.id}">` +
      `<flow-add-menu-asset-item><div class="asset-thumbnail"><img alt="" class="asset-thumbnail-image" src="${m.url}"></div>` +
      `<div class="asset-text"><span class="asset-title">${m.titulo}</span><span class="type-subtitle">Imagem</span></div></flow-add-menu-asset-item></button></div>`;
  }
  function fecharMidia() { $$('.cdk-overlay-pane.menu-midia').forEach(e => e.remove()); st.sel = null; }
  function abrirMidia(origem) {
    fecharMidia(); st.origem = origem;
    const pane = document.createElement('div'); pane.className = 'cdk-overlay-pane menu-midia';
    pane.appendChild(T('menu_midia')); overlay().appendChild(pane);
    const det = $('flow-add-menu-detail-pane', pane); det.dataset.vazio = '1'; det.innerHTML = '';
    desenharLista(pane);
    $('button.sidebar-upload-btn', pane).addEventListener('click', () => {
      const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/*';
      inp.addEventListener('change', () => { const f = inp.files[0]; if (!f) return;
        const m = { id: 'up' + (++st.n), url: URL.createObjectURL(f), titulo: f.name, tipo: 'imagem' };
        const subir = () => setTimeout(() => { st.midias.unshift(m); desenharLista(pane); escolher(pane, m.id); }, 300);
        if (!Q.get('direitos')) return subir();
        // ?direitos=1 (HTML REAL, v84_107): "Direitos de uso desta imagem" — só sobe depois do "Concordo"
        document.body.insertAdjacentHTML('beforeend', '<div class="sim-direitos" style="position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.4)">'
          + '<mat-dialog-container role="dialog" style="display:block;background:#fff;margin:80px auto;width:420px;padding:20px"><flow-upload-consent-dialog>'
          + '<h2>Direitos de uso desta imagem</h2><mat-dialog-actions><button class="mdc-button">Cancelar</button>'
          + '<div class="agree-actions-group"><button class="mdc-button"><span class="mdc-button__label">Concordo</span></button></div>'
          + '</mat-dialog-actions></flow-upload-consent-dialog></mat-dialog-container></div>');
        document.querySelector('.sim-direitos .agree-actions-group button').addEventListener('click', () => { document.querySelector('.sim-direitos').remove(); subir(); });
      });
      inp.click();
    });
  }
  function desenharLista(pane) {
    $('.cdk-virtual-scroll-content-wrapper', pane).innerHTML = st.midias.filter(m => m.tipo === 'imagem').map(itemMidia).join('');
    $$('button.asset-item', pane).forEach(b => b.addEventListener('click', () => escolher(pane, b.dataset.id)));
  }
  function escolher(pane, id) {
    const m = st.midias.find(x => x.id === id); if (!m) return; st.sel = m;
    $$('button.asset-item', pane).forEach(b => b.classList.toggle('asset-item-active', b.dataset.id === id));
    const det = $('flow-add-menu-detail-pane', pane); delete det.dataset.vazio;
    det.innerHTML = `<div class="detail-preview-box"><img class="detail-preview-image" src="${m.url}" alt="Prévia de ${m.titulo}"></div>` +
      `<div class="bottom-actions"><button type="button" class="mdc-button detail-add-to-prompt-btn"><span class="mdc-button__label"> Incluir no comando </span></button></div>`;
    $('button.detail-add-to-prompt-btn', det).addEventListener('click', () => {
      if (st.origem === 'inicio' || st.origem === 'fim') {
        const chip = $$('flow-ingredient-bar .frame-trigger', caixa())[st.origem === 'inicio' ? 0 : 1];
        chip.innerHTML = `<button class="filled-chip"><img class="frame-image" src="${m.url}"></button>`;
      } else {
        $('.prompt-top-row', caixa()).insertAdjacentHTML('afterbegin', `<img class="ref-image" src="${m.url}" width="40">`);
      }
      fecharMidia();
    });
  }
  // ---------------- gerar
  function gerar() {
    const ed = $('flow-prompt-box .ProseMirror'); const prompt = ed.innerText.trim(); if (!prompt) return;
    if (Q.get('limite')) { document.body.insertAdjacentHTML('beforeend', '<div class="error-text">Você chegou ao limite de uso.</div>'); return; }
    const video = st.modo === 'Vídeo'; const qtd = parseInt(st.qtd.slice(1), 10) || 1;
    for (let k = 0; k < qtd; k++) {
      const n = ++st.n; const tile = document.createElement('div'); tile.className = 'tile';
      const mid = '7d415d65-' + String(n).padStart(4, '0') + '-4ab9-flow';  // como o Flow: /image/<id>?Expires=…
      tile.appendChild(T('card_gerando')); $('.subtitle', tile).textContent = prompt; $('.loading-percentage', tile).textContent = '0%';
      $('.tiles').prepend(tile);
      let pct = 0;
      const tick = setInterval(() => {
        pct += 33;
        if (Q.get('falha') && pct > 40) { clearInterval(tick); $('.loading-percentage', tile).textContent = 'Não foi possível gerar. Tente outro comando.'; return; }
        if (pct < 99) { $('.loading-percentage', tile).textContent = pct + '%'; return; }
        clearInterval(tick);
        if (video && Q.get('hover')) {
          // ?hover=1 (como o Flow de verdade, v84_107): só a capa com o play — o <video> entra quando o mouse passa por cima
          tile.innerHTML = `<flow-video-tile style="display:block;width:400px;height:225px"><img src="/media/image/${mid}?Expires=1" width="400" height="225"><mat-icon class="google-symbols">play_circle</mat-icon><span class="footer-title">${prompt}</span></flow-video-tile>`;
          tile.addEventListener('mouseenter', () => { const t = $('flow-video-tile', tile); if (t.querySelector('video')) return;
            t.insertAdjacentHTML('afterbegin', `<video src="/media/video/${mid}?Expires=1" data-media-id="${mid}" muted></video>`); });
          st.midias.unshift({ id: mid, url: `/media/video/${mid}?Expires=1`, titulo: prompt, tipo: 'video' });
        } else if (video) {
          tile.innerHTML = `<flow-video-tile><video src="/media/video/${mid}?Expires=1" data-media-id="${mid}" muted></video><span class="footer-title">${prompt}</span></flow-video-tile>`;
          st.midias.unshift({ id: mid, url: `/media/video/${mid}?Expires=1`, titulo: prompt, tipo: 'video' });
        } else {
          tile.appendChild(T('tile_imagem')); tile.firstElementChild.remove();
          const img = $('img.image', tile); img.src = `/media/image/${mid}?Expires=1`; img.dataset.mediaId = mid;
          $('.footer-title', tile).textContent = prompt;
          st.midias.unshift({ id: mid, url: `/media/image/${mid}?Expires=1`, titulo: prompt, tipo: 'imagem' });
        }
      }, 400);
    }
    ed.innerHTML = '<p><br class="ProseMirror-trailingBreak"></p>'; editorMudou();
  }
  // ?sem_credito=1 (HTML REAL, v84_104): conta sem créditos pra vídeo — o "Iniciar geração" some e no lugar aparece o
  // "Alerta de créditos insuficientes"
  function semCredito() {
    const b = $('flow-prompt-box button[aria-label="Iniciar geração"]'); if (!b) return;
    const sem = Q.get('sem_credito') && st.modo === 'Vídeo';
    b.style.display = sem ? 'none' : '';
    const w = $('flow-prompt-box flow-credit-warning-button');
    if (sem && !w) b.insertAdjacentHTML('afterend', '<flow-credit-warning-button><flow-prompt-warning-button arialabel="Alerta de créditos insuficientes"><button type="button" class="prompt-warning-button" aria-label="Alerta de créditos insuficientes"><mat-icon class="mat-icon google-symbols">info</mat-icon></button></flow-prompt-warning-button></flow-credit-warning-button>');
    if (!sem && w) w.remove();
  }
  function editorMudou() {
    const ed = $('flow-prompt-box .ProseMirror'); const tem = ed.innerText.trim().length > 0;
    const b = $('flow-prompt-box button[aria-label="Iniciar geração"]');
    if (tem) { b.removeAttribute('disabled'); b.classList.remove('mat-mdc-button-disabled'); }
    else { b.setAttribute('disabled', 'true'); b.classList.add('mat-mdc-button-disabled'); }
    const ph = $('flow-prompt-box .prosemirror-placeholder'); if (ph) ph.hidden = tem;
  }
  // ---------------- cliques
  document.addEventListener('mousedown', ev => {  // clicar FORA fecha o pop-up de configurações
    if ($('.popup-config') && !ev.target.closest('.cdk-overlay-container') && !ev.target.closest('button.settings-trigger-button')) fecharPopup();
  }, true);
  document.addEventListener('keydown', ev => {
    if (ev.key !== 'Escape') return;
    if ($('.menu-modelos')) fecharMenusModelo(); else if ($('.menu-midia')) fecharMidia(); else fecharPopup();
  });
  document.addEventListener('input', ev => { if (ev.target.closest('flow-prompt-box .ProseMirror')) editorMudou(); });
  document.addEventListener('click', ev => {
    const t = ev.target;
    const btn = t.closest('button');
    if (!btn) return;
    if (btn.matches('flow-prompt-box button.agent-mode-chip')) return agente(!st.agente);
    if (btn.matches('flow-prompt-box .agent-footer-actions button[aria-label="Configurações"], flow-creative-agent-prompt-box .agent-footer-actions button[aria-label="Configurações"]')) {
      if (!$('flow-settings-view')) document.body.appendChild(T('painel_agente')); return; }
    if (btn.matches('flow-prompt-box button.settings-trigger-button')) return $('.popup-config') ? fecharPopup() : abrirPopup();
    if (btn.matches('flow-prompt-box button[aria-label="Iniciar geração"]')) return gerar();
    if (btn.matches('flow-prompt-box button.add-menu-trigger')) return abrirMidia('ref');
    if (btn.closest('flow-prompt-box flow-ingredient-bar .frame-trigger')) {
      const chips = $$('flow-ingredient-bar .frame-trigger', caixa()); return abrirMidia(chips.indexOf(btn.closest('.frame-trigger')) === 0 ? 'inicio' : 'fim'); }
    // painel do agente
    if (btn.closest('flow-settings-view')) {
      if (btn.matches('button.settings-save-button')) return $('.agent-panel-wrapper:not(.sessao-agente)').remove();
      if (btn.matches('button.mat-button-toggle-button')) return marcar(btn);
      if (btn.matches('button.image-model-picker-button, button.video-model-picker-button')) {
        const video = btn.matches('.video-model-picker-button');
        return abrirMenuModelos(video, nome => { $('.model-select-trigger-label', btn).textContent = ' ' + nome + ' '; });
      }
    }
    if (btn.closest('.agent-panel-header') && btn.matches('[aria-label="Voltar"]')) return $('.agent-panel-wrapper:not(.sessao-agente)').remove();
    if (btn.closest('.sessao-agente') && btn.matches('button.header-action[aria-label="Fechar"]')) {  // X do painel = agente desligado
      $('.sessao-agente').remove(); caixa().style.display = ''; return agente(false); }
    // pop-up de configurações da caixa
    const pop = btn.closest('.popup-config');
    if (pop) {
      if (btn.matches('button.mat-button-toggle-button')) {
        marcar(btn);
        const grupo = btn.closest('flow-toggles').getAttribute('aria-label'); const v = $('.toggle-text', btn).textContent.trim();
        if (grupo === 'Modo') { st.modo = v; framesBar(); semCredito(); abrirPopup(); }
        else if (grupo === 'Tipo de vídeo') { st.tipoVideo = v; framesBar(); }
        else if (grupo === 'Proporção') st.prop = v; else if (grupo === 'Quantidade de resultados') st.qtd = v;
        return;
      }
      if (btn.matches('button[aria-label="Selecionar família de modelos"]')) {
        const video = st.modo === 'Vídeo';
        return abrirMenuModelos(video, nome => { if (video) st.modeloVid = nome; else st.modeloImg = nome;
          const m = $('.model-select-trigger-content', pop); if (m) m.firstChild.textContent = ' ' + nome + ' '; });
      }
    }
  });
  document.addEventListener('click', ev => {  // radio "Nunca"/"Sempre" do painel
    const r = ev.target.closest('flow-settings-view mat-radio-button'); if (!r) return;
    $$('mat-radio-button', r.closest('mat-radio-group')).forEach(x => { x.classList.remove('mat-mdc-radio-checked'); $('input', x).checked = false; });
    r.classList.add('mat-mdc-radio-checked'); $('input', r).checked = true;
  });
  // começo: igual ao projeto novo (agente ligado, sem nada gerado)
  agente(true);
  if (Q.get('painel') === '1') {  // janela larga: o agente é um PAINEL à direita (sem o chip) e a caixa principal some
    caixa().style.display = 'none'; document.body.appendChild(T('painel_sessao'));
  }
  ($$('flow-prompt-box flow-ingredient-bar') || []).forEach(e => e.remove());
  // ?novidades=1 (HTML REAL, v84_107): o aviso de novidades do Flow cobre a tela até clicar em "Começar"
  if (Q.get('novidades')) setTimeout(() => {
    document.body.insertAdjacentHTML('beforeend', '<div class="sim-novidades" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999">'
      + '<mat-dialog-container role="dialog" class="mat-mdc-dialog-container" style="display:block;background:#fff;margin:80px auto;width:420px;padding:20px">'
      + '<flow-change-log-modal><h2>Novidades</h2><p>registros de alterações</p><mat-dialog-actions>'
      + '<button class="mdc-button flow-button-transparent">Ver todos os registros de alterações</button>'
      + '<button class="mdc-button flow-button-primary"><span class="mdc-button__label">Começar</span></button>'
      + '</mat-dialog-actions></flow-change-log-modal></mat-dialog-container></div>');
    document.querySelector('.sim-novidades .flow-button-primary').addEventListener('click', () => document.querySelector('.sim-novidades').remove());
  }, 300);
})();
