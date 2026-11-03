/* 🎚 editor de áudio por forma de onda — usado em narracao_detalhe.html e curto_gravar.html (v84_325).
   A página define: urlGravar(indice), urlGerarRealce(indice, takeId), GRAVACOES, renderizarGravacoes(indice), blocoDaFala(indice). */
// ======================================================================= //
// Editor de áudio por forma de onda -- portado do recurso "Minha Voz" do
// projeto shortmaker (lá era React/preact; aqui é o mesmo comportamento em
// JS puro, pra caber no resto do site). Tudo roda no NAVEGADOR via Web
// Audio API -- decodifica, corta, reconstrói e reexporta o áudio inteiro
// sem precisar do servidor até o passo final de "Salvar". Arraste as
// bordas azuis pra cortar início/fim, ou clique-arraste no meio pra
// selecionar um trecho e removê-lo -- pode ter vários cortes no meio, não
// só nas pontas. Atalhos de teclado iguais a um editor de áudio de
// verdade (Espaço, Delete, setas, +/-, Ctrl+Z/Y). "Salvar" sempre manda o
// resultado como um TAKE NOVO (o original nunca é sobrescrito).
// ======================================================================= //

function audioBufferParaWavBlob(buffer) {
  var numCanais = buffer.numberOfChannels;
  var taxaAmostragem = buffer.sampleRate;
  var numAmostras = buffer.length;
  var blocoAlign = numCanais * 2; // 16-bit = 2 bytes por amostra
  var tamanhoDados = numAmostras * blocoAlign;
  var arrayBuffer = new ArrayBuffer(44 + tamanhoDados);
  var view = new DataView(arrayBuffer);

  function escrever(offset, texto) {
    for (var i = 0; i < texto.length; i++) view.setUint8(offset + i, texto.charCodeAt(i));
  }

  escrever(0, 'RIFF');
  view.setUint32(4, 36 + tamanhoDados, true);
  escrever(8, 'WAVE');
  escrever(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, numCanais, true);
  view.setUint32(24, taxaAmostragem, true);
  view.setUint32(28, taxaAmostragem * blocoAlign, true);
  view.setUint16(32, blocoAlign, true);
  view.setUint16(34, 16, true);
  escrever(36, 'data');
  view.setUint32(40, tamanhoDados, true);

  var canais = [];
  for (var c = 0; c < numCanais; c++) canais.push(buffer.getChannelData(c));
  var offset = 44;
  for (var i2 = 0; i2 < numAmostras; i2++) {
    for (var c2 = 0; c2 < numCanais; c2++) {
      var amostra = Math.max(-1, Math.min(1, canais[c2][i2]));
      amostra = amostra < 0 ? amostra * 0x8000 : amostra * 0x7fff;
      view.setInt16(offset, amostra, true);
      offset += 2;
    }
  }
  return new Blob([arrayBuffer], { type: 'audio/wav' });
}

// Monta um AudioBuffer novo, mantendo só o trecho entre inicioSeg/fimSeg e
// removendo cada região marcada em "cortes" -- concatena o que sobra, em
// ordem, sem deixar buraco nenhum.
function montarBufferEditado(audioContext, bufferOriginal, inicioSeg, fimSeg, cortes) {
  var sr = bufferOriginal.sampleRate;
  var numCanais = bufferOriginal.numberOfChannels;
  var cortesValidos = cortes
    .map(function (c) { return { inicio: Math.max(inicioSeg, c.inicio), fim: Math.min(fimSeg, c.fim) }; })
    .filter(function (c) { return c.fim > c.inicio; });
  var cortesOrdenados = cortesValidos.slice().sort(function (a, b) { return a.inicio - b.inicio; });

  var mantidos = [];
  var cursor = inicioSeg;
  cortesOrdenados.forEach(function (corte) {
    if (corte.inicio > cursor) mantidos.push([cursor, Math.min(corte.inicio, fimSeg)]);
    cursor = Math.max(cursor, corte.fim);
  });
  if (cursor < fimSeg) mantidos.push([cursor, fimSeg]);

  var trechosEmAmostras = mantidos
    .map(function (par) {
      return {
        iniAmostra: Math.max(0, Math.round(par[0] * sr)),
        fimAmostra: Math.min(bufferOriginal.length, Math.round(par[1] * sr)),
      };
    })
    .filter(function (t) { return t.fimAmostra > t.iniAmostra; });

  var totalAmostras = Math.max(1, trechosEmAmostras.reduce(function (soma, t) { return soma + (t.fimAmostra - t.iniAmostra); }, 0));
  var bufferFinal = audioContext.createBuffer(numCanais, totalAmostras, sr);

  for (var c = 0; c < numCanais; c++) {
    var origem = bufferOriginal.getChannelData(c);
    var destino = bufferFinal.getChannelData(c);
    var offset = 0;
    for (var t = 0; t < trechosEmAmostras.length; t++) {
      var iniAmostra = trechosEmAmostras[t].iniAmostra, fimAmostra = trechosEmAmostras[t].fimAmostra;
      var tamanho = Math.min(fimAmostra - iniAmostra, totalAmostras - offset);
      if (tamanho <= 0) break;
      destino.set(origem.subarray(iniAmostra, iniAmostra + tamanho), offset);
      offset += tamanho;
    }
  }
  bufferFinal.__mantidos = mantidos;
  return bufferFinal;
}

// Converte uma posição de tempo DENTRO da prévia editada pra posição
// correspondente no áudio ORIGINAL -- usado pra desenhar o cursor no
// lugar certo durante "Ouvir prévia" (a forma de onda sempre mostra o
// áudio original inteiro, com os trechos cortados marcados).
function tempoPreviaParaTempoOriginal(tempoPrevia, mantidos) {
  if (!mantidos || !mantidos.length) return 0;
  var acumulado = 0;
  for (var i = 0; i < mantidos.length; i++) {
    var a = mantidos[i][0], b = mantidos[i][1];
    var duracaoSegmento = b - a;
    if (tempoPrevia <= acumulado + duracaoSegmento) return a + (tempoPrevia - acumulado);
    acumulado += duracaoSegmento;
  }
  return mantidos[mantidos.length - 1][1];
}

function desenharWaveform(canvas, buffer, inicioSeg, fimSeg, cortes, selecaoTemp, cursorSeg, corCursor) {
  var ctx = canvas.getContext('2d');
  var largura = canvas.width;
  var altura = canvas.height;
  var duracao = buffer.duration || 1;
  ctx.clearRect(0, 0, largura, altura);
  ctx.fillStyle = 'rgba(255,255,255,0.03)';
  ctx.fillRect(0, 0, largura, altura);

  function segParaX(s) { return (s / duracao) * largura; }

  var dados = buffer.getChannelData(0);
  var amostrasPorPixel = Math.max(1, Math.floor(dados.length / largura));
  var meio = altura / 2;
  ctx.fillStyle = '#6c8cff';
  for (var x = 0; x < largura; x++) {
    var ini = x * amostrasPorPixel;
    var min = 0, max = 0;
    for (var i = 0; i < amostrasPorPixel; i++) {
      var v = dados[ini + i] || 0;
      if (v < min) min = v;
      if (v > max) max = v;
    }
    var y1 = meio + min * meio * 0.9;
    var y2 = meio + max * meio * 0.9;
    ctx.fillRect(x, y1, 1, Math.max(1, y2 - y1));
  }

  var xInicio = segParaX(inicioSeg);
  var xFim = segParaX(fimSeg);
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  if (xInicio > 0) ctx.fillRect(0, 0, xInicio, altura);
  if (xFim < largura) ctx.fillRect(xFim, 0, largura - xFim, altura);

  ctx.fillStyle = 'rgba(239,68,68,0.5)';
  cortes.forEach(function (corte) {
    var cx1 = segParaX(corte.inicio), cx2 = segParaX(corte.fim);
    ctx.fillRect(cx1, 0, Math.max(1, cx2 - cx1), altura);
  });

  if (selecaoTemp) {
    ctx.fillStyle = 'rgba(255,207,143,0.5)';
    var sx1 = segParaX(selecaoTemp.inicio), sx2 = segParaX(selecaoTemp.fim);
    ctx.fillRect(sx1, 0, Math.max(1, sx2 - sx1), altura);
  }

  ctx.strokeStyle = '#6c8cff';
  ctx.lineWidth = 3;
  ctx.beginPath(); ctx.moveTo(xInicio, 0); ctx.lineTo(xInicio, altura); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(xFim, 0); ctx.lineTo(xFim, altura); ctx.stroke();

  if (cursorSeg != null) {
    var xCursor = segParaX(cursorSeg);
    var cor = corCursor || '#ffffff';
    ctx.strokeStyle = cor;
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(xCursor, 0); ctx.lineTo(xCursor, altura); ctx.stroke();
    ctx.fillStyle = cor;
    ctx.beginPath();
    ctx.moveTo(xCursor - 5, 0);
    ctx.lineTo(xCursor + 5, 0);
    ctx.lineTo(xCursor, 8);
    ctx.closePath();
    ctx.fill();
  }
}

function formatarTempoEditor(s) {
  var m = Math.floor(s / 60);
  var seg = (s % 60).toFixed(2).padStart(5, '0');
  return m + ':' + seg;
}

function abrirEditorAudio(indice, takeId, srcOriginal, rotulo) {
  var LARGURA_BASE = 700, ALTURA = 120, LIMIAR_ARRASTO_PX = 4;

  var estado = {
    audioContext: null, bufferOriginal: null,
    inicioSeg: 0, fimSeg: 0, cortes: [], selecaoTemp: null,
    cursorSeg: 0, tocandoCursor: false, cursorPreviewSeg: null, tocandoPreview: false, tocandoSelecao: false,
    zoom: 1, historico: [], futuro: [],
    arrastando: null, selecaoInicio: null, mouseDownX: null, houveArrasto: false,
    salvando: false, carregando: true, erro: null,
    fonteCursor: null, fontePreview: null, fonteSelecao: null,
    rafCursor: null, rafPreview: null, mantidosPreview: null, tempoInicioPreview: 0, tempoInicioPlayback: 0, cursorAoIniciar: 0,
  };

  var overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:flex;align-items:center;justify-content:center;padding:16px;';
  var card = document.createElement('div');
  card.style.cssText = 'max-width:820px;width:100%;max-height:90vh;overflow:auto;background:#fff;border-radius:10px;padding:20px;';
  overlay.appendChild(card);

  var titulo = document.createElement('h2');
  titulo.style.marginTop = '0';
  titulo.textContent = '✂️ Editar áudio' + (rotulo ? ' — ' + rotulo : '');
  card.appendChild(titulo);

  var msgCarregando = document.createElement('p');
  msgCarregando.style.color = '#666';
  msgCarregando.textContent = 'Carregando forma de onda...';
  card.appendChild(msgCarregando);

  var msgErro = document.createElement('p');
  msgErro.style.color = '#dc2626';
  msgErro.style.display = 'none';
  card.appendChild(msgErro);

  var corpo = document.createElement('div');
  corpo.style.display = 'none';
  card.appendChild(corpo);

  var ajuda = document.createElement('p');
  ajuda.style.cssText = 'color:#666;font-size:0.82rem;';
  ajuda.textContent = 'Arraste as linhas azuis (bordas) pra cortar início/fim. Clique e arraste no meio pra selecionar um trecho a remover — depois de criada, também dá pra ajustar as bordas da seleção (ou de qualquer corte já feito) arrastando. Um clique simples (sem arrastar) só move o ponteiro branco pra lá, pra navegar/ouvir antes de decidir onde cortar.';
  corpo.appendChild(ajuda);

  var atalhos = document.createElement('details');
  atalhos.style.marginBottom = '8px';
  var atalhosSumario = document.createElement('summary');
  atalhosSumario.style.cssText = 'cursor:pointer;color:#666;font-size:0.82rem;';
  atalhosSumario.textContent = '⌨️ Atalhos de teclado (igual Audacity)';
  var atalhosTexto = document.createElement('p');
  atalhosTexto.style.cssText = 'color:#666;font-size:0.8rem;margin:6px 0 0;';
  atalhosTexto.innerHTML = '<b>Espaço</b> play/pausa — <b>Delete</b> remove a seleção — <b>← →</b> navega 1s (<b>Shift</b> = 5s) — <b>Home/End</b> vai pro início/fim — <b>+ / −</b> zoom, <b>0</b> reseta — <b>Ctrl+Z</b> desfaz, <b>Ctrl+Y</b> refaz — <b>Esc</b> cancela a seleção.';
  atalhos.appendChild(atalhosSumario);
  atalhos.appendChild(atalhosTexto);
  corpo.appendChild(atalhos);

  var containerCanvas = document.createElement('div');
  containerCanvas.style.cssText = 'overflow-x:auto;border-radius:8px;border:1px solid #ddd;';
  var canvas = document.createElement('canvas');
  canvas.height = ALTURA;
  canvas.width = LARGURA_BASE;
  canvas.style.cssText = 'width:' + LARGURA_BASE + 'px;height:' + ALTURA + 'px;cursor:pointer;display:block;';
  containerCanvas.appendChild(canvas);
  corpo.appendChild(containerCanvas);

  function linhaControles() {
    var d = document.createElement('div');
    d.style.cssText = 'display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:10px;';
    return d;
  }
  function botao(texto, cssExtra) {
    var b = document.createElement('button');
    b.type = 'button';
    b.textContent = texto;
    b.style.cssText = 'font-size:12px;padding:6px 10px;margin-top:0;' + (cssExtra || '');
    return b;
  }

  var linhaTransporte = linhaControles();
  var btnVoltar5 = botao('⏪ 5s'); btnVoltar5.style.background = '#666';
  var btnVoltar1 = botao('◀ 1s'); btnVoltar1.style.background = '#666';
  var btnPlay = botao('▶ Play');
  var btnAvancar1 = botao('1s ▶'); btnAvancar1.style.background = '#666';
  var btnAvancar5 = botao('5s ⏩'); btnAvancar5.style.background = '#666';
  var tempoTxt = document.createElement('span');
  tempoTxt.style.cssText = 'color:#666;font-size:0.8rem;margin-left:6px;';
  linhaTransporte.appendChild(btnVoltar5); linhaTransporte.appendChild(btnVoltar1);
  linhaTransporte.appendChild(btnPlay);
  linhaTransporte.appendChild(btnAvancar1); linhaTransporte.appendChild(btnAvancar5);
  linhaTransporte.appendChild(tempoTxt);
  corpo.appendChild(linhaTransporte);

  var linhaZoom = linhaControles();
  var zoomLabel1 = document.createElement('span'); zoomLabel1.style.cssText = 'color:#666;font-size:0.8rem;'; zoomLabel1.textContent = 'Zoom:';
  var btnZoomMenos = botao('−', 'background:#666;');
  var zoomTxt = document.createElement('span'); zoomTxt.style.cssText = 'color:#666;font-size:0.8rem;';
  var btnZoomMais = botao('+', 'background:#666;');
  var btnZoomReset = botao('Resetar zoom', 'background:#666;'); btnZoomReset.style.display = 'none';
  var editarLabel = document.createElement('span'); editarLabel.style.cssText = 'color:#666;font-size:0.8rem;margin-left:14px;'; editarLabel.textContent = 'Editar:';
  var btnDesfazer = botao('↶ Desfazer', 'background:#666;'); btnDesfazer.title = 'Ctrl+Z';
  var btnRefazer = botao('↷ Refazer', 'background:#666;'); btnRefazer.title = 'Ctrl+Y';
  [zoomLabel1, btnZoomMenos, zoomTxt, btnZoomMais, btnZoomReset, editarLabel, btnDesfazer, btnRefazer].forEach(function (el) { linhaZoom.appendChild(el); });
  corpo.appendChild(linhaZoom);

  var linhaPreview = linhaControles();
  var btnPreview = botao('▶ Ouvir prévia (resultado editado)');
  var duracaoTxt = document.createElement('span'); duracaoTxt.style.cssText = 'color:#666;font-size:0.8rem;';
  linhaPreview.appendChild(btnPreview); linhaPreview.appendChild(duracaoTxt);
  corpo.appendChild(linhaPreview);

  var linhaSelecao = linhaControles();
  linhaSelecao.style.display = 'none';
  var selecaoTxt = document.createElement('span'); selecaoTxt.style.cssText = 'color:#666;font-size:0.8rem;';
  var btnOuvirSelecao = botao('🔊 Ouvir seleção', 'background:#666;');
  var btnRemoverSelecao = botao('✂️ Remover esse trecho');
  var btnCancelarSelecao = botao('Cancelar seleção', 'background:#666;');
  [selecaoTxt, btnOuvirSelecao, btnRemoverSelecao, btnCancelarSelecao].forEach(function (el) { linhaSelecao.appendChild(el); });
  corpo.appendChild(linhaSelecao);

  var blocoCortes = document.createElement('div');
  blocoCortes.style.cssText = 'margin-top:10px;display:none;';
  var cortesTitulo = document.createElement('p');
  cortesTitulo.style.cssText = 'color:#666;font-size:0.8rem;margin-bottom:4px;';
  cortesTitulo.textContent = 'Trechos removidos do meio (arraste as bordas deles na forma de onda pra ajustar):';
  blocoCortes.appendChild(cortesTitulo);
  var cortesLista = document.createElement('div');
  blocoCortes.appendChild(cortesLista);
  corpo.appendChild(blocoCortes);

  var labelMelhoria = document.createElement('label');
  labelMelhoria.style.cssText = 'font-weight:normal;font-size:0.85rem;display:flex;align-items:center;gap:6px;margin-top:16px;';
  var checkMelhoria = document.createElement('input');
  checkMelhoria.type = 'checkbox'; checkMelhoria.style.width = 'auto';
  // v84_337: DESLIGADA por padrão — liga se você marcar (e fica lembrado neste navegador)
  try { checkMelhoria.checked = localStorage.getItem('editor_audio_melhoria') === '1'; } catch (e) { checkMelhoria.checked = false; }
  checkMelhoria.addEventListener('change', function () { try { localStorage.setItem('editor_audio_melhoria', checkMelhoria.checked ? '1' : '0'); } catch (e) {} });
  labelMelhoria.appendChild(checkMelhoria);
  labelMelhoria.appendChild(document.createTextNode('✨ Aplicar melhoria de áudio automaticamente (redução de ruído, clareza) ao salvar'));
  corpo.appendChild(labelMelhoria);

  var linhaSalvar = linhaControles();
  var btnSalvar = botao('💾 Salvar como novo take');
  var btnCancelarEditor = botao('Cancelar', 'background:#666;');
  linhaSalvar.appendChild(btnSalvar); linhaSalvar.appendChild(btnCancelarEditor);
  corpo.appendChild(linhaSalvar);

  var dicaTxt = document.createElement('p');
  dicaTxt.style.cssText = 'color:#666;font-size:0.8rem;margin-top:6px;';
  dicaTxt.textContent = 'Arraste as bordas ou remova um trecho do meio pra ter algo pra salvar.';
  corpo.appendChild(dicaTxt);

  document.body.appendChild(overlay);

  function fechar() {
    pararCursor(); pararPreview(); pararSelecao();
    window.removeEventListener('keydown', aoTeclar);
    if (estado.audioContext) { try { estado.audioContext.close(); } catch (e) {} }
    document.body.removeChild(overlay);
  }

  function larguraCanvasAtual() { return Math.round(LARGURA_BASE * estado.zoom); }

  function atualizarTela() {
    canvas.width = larguraCanvasAtual();
    canvas.style.width = larguraCanvasAtual() + 'px';
    if (estado.bufferOriginal) {
      var cursorParaDesenhar = estado.cursorPreviewSeg != null ? estado.cursorPreviewSeg : estado.cursorSeg;
      var corCursor = estado.cursorPreviewSeg != null ? '#ff7a45' : '#ffffff';
      desenharWaveform(canvas, estado.bufferOriginal, estado.inicioSeg, estado.fimSeg, estado.cortes, estado.selecaoTemp, cursorParaDesenhar, corCursor);
    }

    btnPlay.textContent = estado.tocandoCursor ? '⏸ Pausar' : '▶ Play';
    tempoTxt.textContent = formatarTempoEditor(estado.cursorSeg) + ' / ' + (estado.bufferOriginal ? formatarTempoEditor(estado.bufferOriginal.duration) : '0:00');

    zoomTxt.textContent = estado.zoom.toFixed(1) + 'x';
    btnZoomMenos.disabled = estado.zoom <= 1;
    btnZoomMais.disabled = estado.zoom >= 40;
    btnZoomReset.style.display = estado.zoom > 1 ? '' : 'none';
    btnDesfazer.disabled = !estado.historico.length;
    btnRefazer.disabled = !estado.futuro.length;

    btnPreview.textContent = estado.tocandoPreview ? '⏹ Parar' : '▶ Ouvir prévia (resultado editado)';
    var duracaoFinal = estado.bufferOriginal
      ? Math.max(0, (estado.fimSeg - estado.inicioSeg) - estado.cortes.reduce(function (s, c) { return s + (c.fim - c.inicio); }, 0))
      : 0;
    duracaoTxt.textContent = 'Duração final: ' + duracaoFinal.toFixed(2) + 's' + (estado.bufferOriginal ? ' (original: ' + estado.bufferOriginal.duration.toFixed(2) + 's)' : '');

    var temSelecao = estado.selecaoTemp && (estado.selecaoTemp.fim - estado.selecaoTemp.inicio) >= 0.005;
    linhaSelecao.style.display = temSelecao ? '' : 'none';
    if (temSelecao) {
      selecaoTxt.textContent = 'Trecho selecionado: ' + estado.selecaoTemp.inicio.toFixed(2) + 's → ' + estado.selecaoTemp.fim.toFixed(2) + 's (' + (estado.selecaoTemp.fim - estado.selecaoTemp.inicio).toFixed(2) + 's)';
      btnOuvirSelecao.textContent = estado.tocandoSelecao ? '⏹ Parar' : '🔊 Ouvir seleção';
    }

    cortesLista.innerHTML = '';
    blocoCortes.style.display = estado.cortes.length ? '' : 'none';
    estado.cortes.forEach(function (corte, idx) {
      var linha = document.createElement('div');
      linha.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:4px;font-size:0.8rem;';
      var txt = document.createElement('span'); txt.style.color = '#666';
      txt.textContent = corte.inicio.toFixed(2) + 's → ' + corte.fim.toFixed(2) + 's';
      var btnRestaurar = botao('↩ Restaurar', 'background:#666;font-size:11px;padding:3px 8px;');
      btnRestaurar.onclick = function () { restaurarCorte(idx); };
      linha.appendChild(txt); linha.appendChild(btnRestaurar);
      cortesLista.appendChild(linha);
    });

    var houveEdicao = estado.bufferOriginal && (estado.inicioSeg > 0.01 || estado.fimSeg < estado.bufferOriginal.duration - 0.01 || estado.cortes.length > 0);
    btnSalvar.disabled = estado.salvando || !houveEdicao;
    btnSalvar.textContent = estado.salvando ? 'Salvando...' : '💾 Salvar como novo take';
    dicaTxt.style.display = houveEdicao ? 'none' : '';

    msgErro.style.display = estado.erro ? '' : 'none';
    if (estado.erro) msgErro.textContent = estado.erro;
  }

  // --- Carregamento inicial ---
  (async function () {
    try {
      var AC = window.AudioContext || window.webkitAudioContext;
      estado.audioContext = new AC();
      var resp = await fetch(srcOriginal);
      var arrayBuffer = await resp.arrayBuffer();
      var buffer = await estado.audioContext.decodeAudioData(arrayBuffer);
      estado.bufferOriginal = buffer;
      estado.inicioSeg = 0;
      estado.fimSeg = buffer.duration;
      estado.carregando = false;
      msgCarregando.style.display = 'none';
      corpo.style.display = '';
      atualizarTela();
    } catch (e) {
      estado.carregando = false;
      msgCarregando.style.display = 'none';
      msgErro.style.display = '';
      msgErro.textContent = 'Não consegui carregar esse áudio pra editar: ' + e.message;
      var btnFechar = botao('Fechar', 'margin-top:10px;');
      btnFechar.onclick = fechar;
      card.appendChild(btnFechar);
    }
  })();

  // --- Reprodução com ponteiro (navegar/ouvir o original) ---
  function pararCursor() {
    if (estado.fonteCursor) { try { estado.fonteCursor.stop(); } catch (e) {} estado.fonteCursor = null; }
    if (estado.rafCursor) { cancelAnimationFrame(estado.rafCursor); estado.rafCursor = null; }
    estado.tocandoCursor = false;
  }
  function loopAtualizarCursor() {
    if (!estado.audioContext || !estado.bufferOriginal) return;
    var decorrido = estado.audioContext.currentTime - estado.tempoInicioPlayback;
    var novoCursor = estado.cursorAoIniciar + decorrido;
    if (novoCursor >= estado.bufferOriginal.duration) {
      estado.cursorSeg = estado.bufferOriginal.duration;
      pararCursor();
      atualizarTela();
      return;
    }
    estado.cursorSeg = novoCursor;
    atualizarTela();
    estado.rafCursor = requestAnimationFrame(loopAtualizarCursor);
  }
  function tocarDoCursor(posicaoInicial) {
    if (!estado.bufferOriginal) return;
    pararCursor();
    var ac = estado.audioContext;
    var fonte = ac.createBufferSource();
    fonte.buffer = estado.bufferOriginal;
    fonte.connect(ac.destination);
    fonte.onended = function () { if (estado.fonteCursor === fonte) pararCursor(); atualizarTela(); };
    fonte.start(0, posicaoInicial);
    estado.fonteCursor = fonte;
    estado.tempoInicioPlayback = ac.currentTime;
    estado.cursorAoIniciar = posicaoInicial;
    estado.tocandoCursor = true;
    estado.rafCursor = requestAnimationFrame(loopAtualizarCursor);
  }
  function alternarPlayPause() {
    if (estado.tocandoCursor) { pararCursor(); atualizarTela(); return; }
    pararSelecao(); pararPreview();
    var posicao = estado.cursorSeg >= (estado.bufferOriginal ? estado.bufferOriginal.duration - 0.05 : 0) ? 0 : estado.cursorSeg;
    tocarDoCursor(posicao);
    atualizarTela();
  }
  function pular(segundos) {
    if (!estado.bufferOriginal) return;
    var novaPos = Math.max(0, Math.min(estado.bufferOriginal.duration, estado.cursorSeg + segundos));
    estado.cursorSeg = novaPos;
    if (estado.tocandoCursor) tocarDoCursor(novaPos);
    atualizarTela();
  }

  function aplicarZoom(multiplicador) {
    estado.zoom = Math.max(1, Math.min(40, estado.zoom * multiplicador));
    atualizarTela();
    ajustarScrollComZoom();
  }

  function ajustarScrollComZoom() {
    if (!estado.bufferOriginal || estado.zoom <= 1) return;
    var cursorAtivo = estado.cursorPreviewSeg != null ? estado.cursorPreviewSeg : estado.cursorSeg;
    var fracao = cursorAtivo / estado.bufferOriginal.duration;
    var posPx = fracao * larguraCanvasAtual();
    var margem = containerCanvas.clientWidth * 0.15;
    if (posPx < containerCanvas.scrollLeft + margem || posPx > containerCanvas.scrollLeft + containerCanvas.clientWidth - margem) {
      containerCanvas.scrollLeft = Math.max(0, posPx - containerCanvas.clientWidth / 2);
    }
  }

  // --- Desfazer/Refazer ---
  function empilharHistorico() {
    estado.historico.push({ inicioSeg: estado.inicioSeg, fimSeg: estado.fimSeg, cortes: estado.cortes });
    if (estado.historico.length > 50) estado.historico.shift();
    estado.futuro = [];
  }
  function desfazer() {
    if (!estado.historico.length) return;
    var anterior = estado.historico.pop();
    estado.futuro.unshift({ inicioSeg: estado.inicioSeg, fimSeg: estado.fimSeg, cortes: estado.cortes });
    if (estado.futuro.length > 50) estado.futuro.pop();
    estado.inicioSeg = anterior.inicioSeg; estado.fimSeg = anterior.fimSeg; estado.cortes = anterior.cortes;
    estado.selecaoTemp = null;
    atualizarTela();
  }
  function refazer() {
    if (!estado.futuro.length) return;
    var proximo = estado.futuro.shift();
    estado.historico.push({ inicioSeg: estado.inicioSeg, fimSeg: estado.fimSeg, cortes: estado.cortes });
    if (estado.historico.length > 50) estado.historico.shift();
    estado.inicioSeg = proximo.inicioSeg; estado.fimSeg = proximo.fimSeg; estado.cortes = proximo.cortes;
    estado.selecaoTemp = null;
    atualizarTela();
  }

  // --- Arrastar handles ---
  function xParaSegundos(clientX) {
    var rect = canvas.getBoundingClientRect();
    var fracao = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    return fracao * (estado.bufferOriginal ? estado.bufferOriginal.duration : 0);
  }
  function xParaSegundosNaAreaAtiva(clientX) {
    var seg = xParaSegundos(clientX);
    return Math.max(estado.inicioSeg, Math.min(estado.fimSeg, seg));
  }
  function limiarProximidade() {
    return (estado.bufferOriginal ? estado.bufferOriginal.duration / estado.zoom : 0) * 0.015 + 0.03;
  }

  function aoMoverMouse(e) {
    if (!estado.bufferOriginal || !estado.arrastando) return;
    if (estado.mouseDownX != null && Math.abs(e.clientX - estado.mouseDownX) > LIMIAR_ARRASTO_PX) {
      estado.houveArrasto = true;
    }
    var seg = xParaSegundos(e.clientX);
    var segNaArea = xParaSegundosNaAreaAtiva(e.clientX);
    var alvo = estado.arrastando;

    if (alvo === 'pendente-selecao' || alvo === 'pendente-cursor') {
      if (!estado.houveArrasto) return;
      if (alvo === 'pendente-selecao') {
        estado.arrastando = 'selecao';
        var ini0 = estado.selecaoInicio;
        estado.selecaoTemp = { inicio: Math.min(ini0, segNaArea), fim: Math.max(ini0, segNaArea) };
      } else {
        estado.arrastando = null;
      }
      atualizarTela();
      return;
    }

    if (alvo === 'inicio') {
      estado.inicioSeg = Math.min(seg, estado.fimSeg - 0.05);
    } else if (alvo === 'fim') {
      estado.fimSeg = Math.max(seg, estado.inicioSeg + 0.05);
    } else if (alvo === 'selecao') {
      var ini = estado.selecaoInicio;
      estado.selecaoTemp = { inicio: Math.min(ini, segNaArea), fim: Math.max(ini, segNaArea) };
    } else if (alvo === 'sel-ini') {
      if (estado.selecaoTemp) estado.selecaoTemp = { inicio: Math.min(segNaArea, estado.selecaoTemp.fim - 0.02), fim: estado.selecaoTemp.fim };
    } else if (alvo === 'sel-fim') {
      if (estado.selecaoTemp) estado.selecaoTemp = { inicio: estado.selecaoTemp.inicio, fim: Math.max(segNaArea, estado.selecaoTemp.inicio + 0.02) };
    } else if (typeof alvo === 'string' && alvo.indexOf('corte-ini-') === 0) {
      var idxI = parseInt(alvo.slice(10), 10);
      estado.cortes = estado.cortes.map(function (corte, i) { return i === idxI ? { inicio: Math.min(segNaArea, corte.fim - 0.02), fim: corte.fim } : corte; });
    } else if (typeof alvo === 'string' && alvo.indexOf('corte-fim-') === 0) {
      var idxF = parseInt(alvo.slice(10), 10);
      estado.cortes = estado.cortes.map(function (corte, i) { return i === idxF ? { inicio: corte.inicio, fim: Math.max(segNaArea, corte.inicio + 0.02) } : corte; });
    }
    atualizarTela();
  }

  function aoSoltarMouse(e) {
    var alvo = estado.arrastando;
    if ((alvo === 'pendente-selecao' || alvo === 'pendente-cursor') && !estado.houveArrasto) {
      var seg = xParaSegundos(e.clientX);
      estado.cursorSeg = seg;
      if (estado.tocandoCursor) tocarDoCursor(seg);
      atualizarTela();
    }
    estado.arrastando = null;
    estado.mouseDownX = null;
    window.removeEventListener('mousemove', aoMoverMouse);
    window.removeEventListener('mouseup', aoSoltarMouse);
  }

  function aoClicarCanvas(e) {
    if (!estado.bufferOriginal) return;
    var seg = xParaSegundos(e.clientX);
    var limiar = limiarProximidade();
    function pertoDe(alvo) { return Math.abs(seg - alvo) < limiar; }

    estado.mouseDownX = e.clientX;
    estado.houveArrasto = false;

    var alvoEscolhido = null;
    if (pertoDe(estado.inicioSeg)) alvoEscolhido = 'inicio';
    else if (pertoDe(estado.fimSeg)) alvoEscolhido = 'fim';
    else if (estado.selecaoTemp && pertoDe(estado.selecaoTemp.inicio)) alvoEscolhido = 'sel-ini';
    else if (estado.selecaoTemp && pertoDe(estado.selecaoTemp.fim)) alvoEscolhido = 'sel-fim';
    else {
      for (var i = 0; i < estado.cortes.length; i++) {
        if (pertoDe(estado.cortes[i].inicio)) { alvoEscolhido = 'corte-ini-' + i; break; }
        if (pertoDe(estado.cortes[i].fim)) { alvoEscolhido = 'corte-fim-' + i; break; }
      }
    }

    if (alvoEscolhido) {
      if (alvoEscolhido === 'inicio' || alvoEscolhido === 'fim' || alvoEscolhido.indexOf('corte-') === 0) {
        empilharHistorico();
      }
      estado.arrastando = alvoEscolhido;
      estado.selecaoInicio = seg;
      window.addEventListener('mousemove', aoMoverMouse);
      window.addEventListener('mouseup', aoSoltarMouse);
      return;
    }

    var dentroDeCorte = estado.cortes.some(function (c) { return seg > c.inicio && seg < c.fim; });
    var dentroDaAreaEditavel = seg > estado.inicioSeg && seg < estado.fimSeg && !dentroDeCorte;
    estado.arrastando = dentroDaAreaEditavel ? 'pendente-selecao' : 'pendente-cursor';
    estado.selecaoInicio = seg;
    window.addEventListener('mousemove', aoMoverMouse);
    window.addEventListener('mouseup', aoSoltarMouse);
  }
  canvas.addEventListener('mousedown', aoClicarCanvas);

  function removerTrechoSelecionado() {
    if (!estado.selecaoTemp || estado.selecaoTemp.fim - estado.selecaoTemp.inicio < 0.005) { estado.selecaoTemp = null; atualizarTela(); return; }
    empilharHistorico();
    estado.cortes = estado.cortes.concat([estado.selecaoTemp]);
    estado.selecaoTemp = null;
    atualizarTela();
  }
  function restaurarCorte(idx) {
    empilharHistorico();
    estado.cortes = estado.cortes.filter(function (_, i) { return i !== idx; });
    atualizarTela();
  }

  function pararPreview() {
    if (estado.fontePreview) { try { estado.fontePreview.stop(); } catch (e) {} estado.fontePreview = null; }
    if (estado.rafPreview) { cancelAnimationFrame(estado.rafPreview); estado.rafPreview = null; }
    estado.tocandoPreview = false;
    estado.cursorPreviewSeg = null;
  }
  function loopAtualizarCursorPreview() {
    if (!estado.audioContext || !estado.mantidosPreview) return;
    var decorrido = estado.audioContext.currentTime - estado.tempoInicioPreview;
    var duracaoTotal = estado.mantidosPreview.reduce(function (soma, par) { return soma + (par[1] - par[0]); }, 0);
    if (decorrido >= duracaoTotal) return;
    estado.cursorPreviewSeg = tempoPreviaParaTempoOriginal(decorrido, estado.mantidosPreview);
    atualizarTela();
    estado.rafPreview = requestAnimationFrame(loopAtualizarCursorPreview);
  }
  function tocarPreview() {
    pararCursor();
    if (estado.tocandoPreview) { pararPreview(); atualizarTela(); return; }
    var bufferFinal = montarBufferEditado(estado.audioContext, estado.bufferOriginal, estado.inicioSeg, estado.fimSeg, estado.cortes);
    var fonte = estado.audioContext.createBufferSource();
    fonte.buffer = bufferFinal;
    fonte.connect(estado.audioContext.destination);
    fonte.onended = function () { if (estado.fontePreview === fonte) { pararPreview(); atualizarTela(); } };
    fonte.start();
    estado.fontePreview = fonte;
    estado.mantidosPreview = bufferFinal.__mantidos || [];
    estado.tempoInicioPreview = estado.audioContext.currentTime;
    estado.cursorPreviewSeg = estado.mantidosPreview.length ? estado.mantidosPreview[0][0] : 0;
    estado.tocandoPreview = true;
    atualizarTela();
    estado.rafPreview = requestAnimationFrame(loopAtualizarCursorPreview);
  }

  function pararSelecao() {
    if (estado.fonteSelecao) { try { estado.fonteSelecao.stop(); } catch (e) {} estado.fonteSelecao = null; }
    estado.tocandoSelecao = false;
  }
  function tocarSelecao() {
    if (!estado.selecaoTemp || !estado.bufferOriginal) return;
    pararCursor(); pararPreview();
    if (estado.tocandoSelecao) { pararSelecao(); atualizarTela(); return; }
    var ac = estado.audioContext;
    var fonte = ac.createBufferSource();
    fonte.buffer = estado.bufferOriginal;
    fonte.connect(ac.destination);
    fonte.onended = function () { estado.tocandoSelecao = false; atualizarTela(); };
    fonte.start(0, estado.selecaoTemp.inicio, Math.max(0.01, estado.selecaoTemp.fim - estado.selecaoTemp.inicio));
    estado.fonteSelecao = fonte;
    estado.tocandoSelecao = true;
    atualizarTela();
  }

  function montarBufferFinalValidado() {
    if (!estado.bufferOriginal) return null;
    var bufferFinal = montarBufferEditado(estado.audioContext, estado.bufferOriginal, estado.inicioSeg, estado.fimSeg, estado.cortes);
    var duracaoResultante = bufferFinal.length / bufferFinal.sampleRate;
    if (duracaoResultante < 0.1) {
      estado.erro = 'Esse corte deixaria só ' + duracaoResultante.toFixed(2) + 's de áudio (praticamente vazio) — ajuste os cortes antes de continuar. Provavelmente um corte do meio ficou cobrindo todo o trecho que sobrou depois de cortar o início/fim.';
      atualizarTela();
      return null;
    }
    estado.erro = null;
    return bufferFinal;
  }

  async function salvarEdicao() {
    var bufferFinal = montarBufferFinalValidado();
    if (!bufferFinal) return;
    estado.salvando = true;
    atualizarTela();
    pararPreview(); pararCursor(); pararSelecao();
    try {
      var blob = audioBufferParaWavBlob(bufferFinal);
      var formData = new FormData();
      formData.append('audio', blob, 'editado.wav');
      var r = await fetch(urlGravar(indice), { method: 'POST', body: formData });
      var data = await r.json();
      if (!r.ok) {
        estado.erro = data.erro || 'Falha ao salvar a edição.';
        estado.salvando = false;
        atualizarTela();
        return;
      }
      var entrada = GRAVACOES[String(indice)] || { usar: false, takeAtivo: null, takes: [] };
      entrada.takes.push({ id: data.takeId, duracaoSegundos: data.duracaoSegundos, criadoEm: new Date().toISOString() });
      entrada.takeAtivo = data.takeId;
      entrada.usar = data.usar;
      GRAVACOES[String(indice)] = entrada;

      if (checkMelhoria.checked) {
        try {
          await fetch(urlGerarRealce(indice, data.takeId), {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
          });
          var entradaAtual = GRAVACOES[String(indice)];
          var takeAtual = entradaAtual.takes.find(function (t) { return t.id === data.takeId; });
          if (takeAtual) { takeAtual.enhancedGerado = true; takeAtual.usarEnhance = true; }
        } catch (e) { /* melhoria falhando não deve travar o salvamento -- já está salvo */ }
      }

      renderizarGravacoes(indice);
      var bloco = blocoDaFala(indice);
      if (bloco) bloco.querySelector('.gravacao-status').textContent = 'Áudio editado salvo como novo take.';
      fechar();
    } catch (e) {
      estado.erro = 'Falha ao processar o áudio editado: ' + e.message;
      estado.salvando = false;
      atualizarTela();
    }
  }

  // --- Atalhos de teclado ---
  function aoTeclar(e) {
    if (!estado.bufferOriginal) return;
    var tag = (e.target && e.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;

    if (e.code === 'Space') { e.preventDefault(); alternarPlayPause(); }
    else if (e.key === 'Delete' || e.key === 'Backspace') {
      if (estado.selecaoTemp && estado.selecaoTemp.fim - estado.selecaoTemp.inicio >= 0.005) { e.preventDefault(); removerTrechoSelecionado(); }
    } else if (e.key === 'ArrowLeft') { e.preventDefault(); pular(e.shiftKey ? -5 : -1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); pular(e.shiftKey ? 5 : 1); }
    else if (e.key === 'Home') { e.preventDefault(); estado.cursorSeg = 0; if (estado.tocandoCursor) tocarDoCursor(0); atualizarTela(); }
    else if (e.key === 'End') { e.preventDefault(); pararCursor(); estado.cursorSeg = estado.bufferOriginal.duration; atualizarTela(); }
    else if (e.key === '+' || e.key === '=') { e.preventDefault(); aplicarZoom(2); }
    else if (e.key === '-' || e.key === '_') { e.preventDefault(); aplicarZoom(0.5); }
    else if (e.key === '0') { e.preventDefault(); estado.zoom = 1; atualizarTela(); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) { e.preventDefault(); desfazer(); }
    else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) { e.preventDefault(); refazer(); }
    else if (e.key === 'Escape' && estado.selecaoTemp) { e.preventDefault(); estado.selecaoTemp = null; atualizarTela(); }
  }
  window.addEventListener('keydown', aoTeclar);

  btnVoltar5.onclick = function () { pular(-5); };
  btnVoltar1.onclick = function () { pular(-1); };
  btnPlay.onclick = alternarPlayPause;
  btnAvancar1.onclick = function () { pular(1); };
  btnAvancar5.onclick = function () { pular(5); };
  btnZoomMenos.onclick = function () { aplicarZoom(0.5); };
  btnZoomMais.onclick = function () { aplicarZoom(2); };
  btnZoomReset.onclick = function () { estado.zoom = 1; atualizarTela(); };
  btnDesfazer.onclick = desfazer;
  btnRefazer.onclick = refazer;
  btnPreview.onclick = tocarPreview;
  btnOuvirSelecao.onclick = tocarSelecao;
  btnRemoverSelecao.onclick = removerTrechoSelecionado;
  btnCancelarSelecao.onclick = function () { estado.selecaoTemp = null; atualizarTela(); };
  btnSalvar.onclick = salvarEdicao;
  btnCancelarEditor.onclick = fechar;
}
