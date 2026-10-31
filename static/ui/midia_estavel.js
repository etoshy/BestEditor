/* midia_estavel.js — 🎞 v84_298: os vídeos não recarregam quando a página se atualiza sozinha.
 *
 * Quase toda aba redesenha um pedaço da tela a cada 1-3 s (progresso, lista de vídeos…) com `el.innerHTML = …`. Isso
 * recriava os <video>, <audio> e <iframe> (YouTube) que estavam ali: o vídeo piscava, parava e voltava pro começo.
 *
 * Aqui o `innerHTML` de qualquer elemento continua funcionando igual, com uma diferença: o player que JÁ estava na tela e
 * continua no HTML novo (mesmo tipo + mesmo src + mesmo data-k) é REAPROVEITADO no lugar do novo — a reprodução, o ponto
 * em que estava, o volume e a tela cheia continuam. Os atributos novos (classe, estilo, controles) são copiados pra ele.
 *
 * Mover um player sem reiniciar usa `moveBefore()` (Chrome/Edge 133+). Em navegador mais antigo: o vídeo volta a tocar
 * do ponto em que estava (o iframe do YouTube, nesse caso, ainda recarrega).
 * Pra desligar num elemento: <div data-midia-livre>…</div>.
 */
(function () {
  'use strict';
  var desc = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
  if (!desc || !desc.set || window.__midiaEstavel) return;
  window.__midiaEstavel = true;
  var SEL = 'video, audio, iframe';
  var temMove = typeof Element.prototype.moveBefore === 'function';
  var guarda = null;

  function srcDe(el) {
    var s = el.getAttribute('src');
    if (!s) {
      var f = el.querySelector && el.querySelector('source[src]');
      s = f ? f.getAttribute('src') : '';
    }
    if (!s) return '';
    try { return new URL(s, location.href).href; } catch (e) { return s; }
  }
  function chave(el) {
    var s = srcDe(el);
    return s ? el.tagName + '|' + (el.getAttribute('data-k') || '') + '|' + s : '';
  }
  function mover(pai, no, antes) {
    if (temMove && no.isConnected && pai.isConnected) {
      try { pai.moveBefore(no, antes || null); return; } catch (e) { /* cai no insertBefore */ }
    }
    pai.insertBefore(no, antes || null);
  }
  function caixa() {
    if (guarda && guarda.isConnected) return guarda;
    guarda = document.createElement('div');
    guarda.setAttribute('aria-hidden', 'true');
    guarda.style.cssText = 'position:fixed;left:-10000px;top:0;width:1px;height:1px;overflow:hidden;opacity:0;pointer-events:none';
    (document.body || document.documentElement).appendChild(guarda);
    return guarda;
  }

  Object.defineProperty(Element.prototype, 'innerHTML', {
    configurable: true,
    enumerable: desc.enumerable,
    get: function () { return desc.get.call(this); },
    set: function (html) {
      if (!this.isConnected || (this.hasAttribute && this.hasAttribute('data-midia-livre')) || this.tagName === 'TEMPLATE') {
        return desc.set.call(this, html);
      }
      var velhos = this.querySelectorAll ? this.querySelectorAll(SEL) : [];
      if (!velhos.length) return desc.set.call(this, html);
      var mapa = new Map(), estado = new Map(), g = null;
      for (var i = 0; i < velhos.length; i++) {
        var v = velhos[i], k = chave(v);
        if (!k || mapa.has(k) || v.closest('[data-midia-livre]')) continue;
        mapa.set(k, v);
        if (v.tagName !== 'IFRAME') estado.set(v, { tocando: !v.paused && !v.ended, t: v.currentTime });
        g = g || caixa();
        mover(g, v, null);  // tira da frente antes do innerHTML (sem desmontar)
      }
      desc.set.call(this, html);
      var novos = this.querySelectorAll(SEL);
      for (var j = 0; j < novos.length; j++) {
        var n = novos[j], kk = chave(n), velho = mapa.get(kk);
        if (!velho) continue;
        mapa.delete(kk);
        var a, idx;
        for (idx = 0; idx < n.attributes.length; idx++) {
          a = n.attributes[idx];
          if (a.name !== 'src' && velho.getAttribute(a.name) !== a.value) velho.setAttribute(a.name, a.value);
        }
        for (idx = velho.attributes.length - 1; idx >= 0; idx--) {
          a = velho.attributes[idx];
          if (a.name !== 'src' && !n.hasAttribute(a.name)) velho.removeAttribute(a.name);
        }
        mover(n.parentNode, velho, n);
        n.remove();
        var st = estado.get(velho);
        if (st && !temMove) {  // sem moveBefore o navegador pausou ao tirar da página: volta de onde estava
          try { if (Math.abs(velho.currentTime - st.t) > 0.3) velho.currentTime = st.t; } catch (e) {}
          if (st.tocando) { var pr = velho.play(); if (pr && pr.catch) pr.catch(function () {}); }
        }
      }
      mapa.forEach(function (v) { v.remove(); });  // os que saíram do HTML novo somem de verdade
    }
  });
})();
