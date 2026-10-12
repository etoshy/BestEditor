// Aba Método: checklist, planilha automática dos canais, calculadora e semáforo de saturação.
// Depende de metodo.js (fórmulas) e de app.js (escapeHtml, formatData, salvarPreferencias, ultimoResultado).
(function () {
  const M = window.NicheMetodo;
  const $ = (id) => document.getElementById(id);
  const fmt = (n, casas = 2) => (n === null || n === undefined || !Number.isFinite(n)) ? "—" : Number(n).toLocaleString("pt-BR", { maximumFractionDigits: casas });
  const inteiro = (n) => (n === null || n === undefined || !Number.isFinite(n)) ? "—" : new Intl.NumberFormat("pt-BR").format(Math.round(n));
  const cortar = (s, n) => (String(s || "").length > n ? `${String(s).slice(0, n)}…` : String(s || ""));

  // ---------- checklist (salvo neste navegador) ----------
  const CHAVE_CHECKS = "niche_miner_metodo_checks";
  function lerChecks() { try { return JSON.parse(localStorage.getItem(CHAVE_CHECKS) || "{}") || {}; } catch (_) { return {}; } }
  function gravarChecks(o) { try { localStorage.setItem(CHAVE_CHECKS, JSON.stringify(o)); } catch (_) { /* sem storage: só não persiste */ } }
  function atualizarProgresso() {
    $("mt-progresso").textContent = `${document.querySelectorAll(".mt-check:checked").length} de ${document.querySelectorAll(".mt-check").length}`;
  }
  function iniciarChecklist() {
    const salvos = lerChecks();
    document.querySelectorAll(".mt-check").forEach((c) => {
      c.checked = !!salvos[c.dataset.chave];
      c.addEventListener("change", () => {
        const o = lerChecks();
        if (c.checked) o[c.dataset.chave] = true; else delete o[c.dataset.chave];
        gravarChecks(o);
        atualizarProgresso();
      });
    });
    $("mt-limpar").addEventListener("click", () => {
      if (!confirm("Limpar todas as marcações do checklist?")) return;
      gravarChecks({});
      document.querySelectorAll(".mt-check").forEach((c) => { c.checked = false; });
      atualizarProgresso();
    });
    atualizarProgresso();
  }

  // ---------- limites (compartilhados pela planilha e pela calculadora) ----------
  function limites() {
    const c = parseFloat($("mp-cuidado").value);
    const f = parseFloat($("mp-forte").value);
    return {
      cuidado: Number.isFinite(c) && c >= 0 ? c : M.LIMITES_TRACAO.cuidado,
      forte: Number.isFinite(f) && f > 0 ? f : M.LIMITES_TRACAO.forte,
    };
  }
  function fatorMinimo() {
    const f = parseFloat($("mp-fator").value);
    return Number.isFinite(f) && f >= 1 ? f : 2;
  }
  function badgeSinal(sinal) {
    const cls = sinal.chave === "forte" ? "badge-green" : sinal.chave === "cuidado" ? "badge-red" : "badge-muted";
    return `<span class="badge ${cls}">${escapeHtml(sinal.rotulo)}</span>`;
  }

  // ---------- planilha automática ----------
  let canaisFonte = [];
  let linhasAtuais = [];
  let cargaAtual = 0;

  function opcoesPlanilha() {
    const n = Math.max(3, Math.min(50, parseInt($("mp-n").value, 10) || 10));
    return { n, fatorMin: fatorMinimo(), so30d: $("mp-30d").checked, limites: limites(), agora: new Date() };
  }

  function ordenar(linhas, chave) {
    const valor = { tracao: (m) => m.tracao, mediana: (m) => m.mediana, inscritos: (m) => m.inscritos }[chave];
    if (!valor) return linhas;      // "original": ordem do app
    return linhas.map((m, i) => [m, i]).sort((a, b) => {
      const x = valor(a[0]), y = valor(b[0]);
      if (x === null && y === null) return a[1] - b[1];
      if (x === null) return 1;
      if (y === null) return -1;
      return (y - x) || (a[1] - b[1]);
    }).map((p) => p[0]);
  }

  function linhaHtml(m, o) {
    const canal = /^https?:\/\//.test(m.canal_url)
      ? `<a href="${escapeHtml(m.canal_url)}" target="_blank" rel="noopener">${escapeHtml(m.canal || m.canal_url)}</a>` : escapeHtml(m.canal || "?");
    const criado = m.criado_em
      ? `${escapeHtml(typeof formatData === "function" ? formatData(m.criado_em) : m.criado_em)}<br><span class="muted-small">${fmt(m.idade_meses, 1)} meses</span>` : "?";
    const nota = m.n_ultimos > 0 && m.amostra_pequena
      ? ` <span class="badge badge-muted" title="Só ${m.n_ultimos} vídeos na amostra (pedido: ${o.n})">n=${m.n_ultimos}</span>` : "";
    const outliers = m.outliers.length
      ? `<details><summary>${m.outliers.length}</summary><ol>${m.outliers.slice(0, 8).map((x) =>
        `<li><a href="${escapeHtml(x.url || "#")}" target="_blank" rel="noopener">${escapeHtml(cortar(x.titulo, 60))}</a><br>`
        + `${inteiro(x.views)} views · ${fmt(x.fator, 1)}× a mediana · há ${x.dias === null ? "?" : x.dias} dia(s) · ≈ ${fmt(x.vph_medio, 1)} views/h de média desde a postagem</li>`).join("")}</ol></details>`
      : "—";
    return `<tr><td>${canal}</td><td class="num">${inteiro(m.inscritos)}</td><td>${criado}</td><td class="num">${inteiro(m.n_videos)}</td>`
      + `<td class="num">${inteiro(m.videos_30d)}</td><td class="num">${inteiro(m.mediana)}${nota}</td><td class="num">${inteiro(m.media)}</td>`
      + `<td class="num">${fmt(m.tracao, 3)}</td><td>${badgeSinal(m.sinal)}</td><td class="num">${m.maior_fator === null ? "—" : `${fmt(m.maior_fator, 1)}×`}</td><td>${outliers}</td></tr>`;
  }

  function renderPlanilha() {
    const alvo = $("mp-tabela");
    if (!canaisFonte.length) {
      linhasAtuais = [];
      $("mp-csv").disabled = true;
      $("mp-info").textContent = "";
      alvo.innerHTML = '<div class="empty-state">rode uma mineração (aba Minerar) ou escolha uma busca da Biblioteca: os canais aparecem aqui</div>';
      return;
    }
    const o = opcoesPlanilha();
    const linhas = ordenar(canaisFonte.map((c) => M.metricasCanal(c, o)), $("mp-ordem").value);
    linhasAtuais = linhas;
    const comAmostra = linhas.filter((m) => m.n_ultimos > 0).length;
    $("mp-csv").disabled = false;
    $("mp-info").textContent = `${linhas.length} canais · ${comAmostra} com vídeos recentes para a mediana`
      + (comAmostra < linhas.length ? " (os outros vêm de uma busca sem essa lista: rode de novo para preencher)" : "");
    alvo.innerHTML = `<div class="table-wrap"><table class="candidate-table mt-tabela"><thead><tr><th>Canal</th><th>Inscritos</th><th>Criado</th><th>Vídeos</th><th>30 dias</th>`
      + `<th>Mediana (${o.n})</th><th>Média</th><th>Tração</th><th>Sinal</th><th>Maior fator</th><th>Outliers</th></tr></thead><tbody>${linhas.map((m) => linhaHtml(m, o)).join("")}</tbody></table></div>`;
  }

  async function carregarCanais() {
    const token = ++cargaAtual;
    const v = $("mp-fonte").value;
    let canais = [];
    if (v === "sessao") {
      const res = typeof ultimoResultado !== "undefined" ? ultimoResultado : null;
      canais = (res && (res.ranking_geral || res.ranking_nao_verificados)) || [];
    } else if (v.startsWith("busca:")) {
      try {
        const resp = await fetch(`/api/biblioteca/busca/${encodeURIComponent(v.slice(6))}`);
        const j = await resp.json();
        if (!resp.ok || !j.ok) throw new Error(j.erro || `erro ${resp.status}`);
        canais = j.canais || [];
      } catch (e) {
        if (token !== cargaAtual) return;
        canaisFonte = [];
        linhasAtuais = [];
        $("mp-csv").disabled = true;
        $("mp-tabela").innerHTML = `<div class="empty-state">${escapeHtml(e.message)}</div>`;
        return;
      }
    }
    if (token !== cargaAtual) return;       // o usuário já escolheu outra fonte
    canaisFonte = Array.isArray(canais) ? canais.slice() : [];
    renderPlanilha();
  }

  async function carregarFontes() {
    const sel = $("mp-fonte");
    const anterior = sel.value;
    const opcoes = [];
    const res = typeof ultimoResultado !== "undefined" ? ultimoResultado : null;
    const sessao = res && (res.ranking_geral || res.ranking_nao_verificados);
    if (Array.isArray(sessao) && sessao.length) opcoes.push({ v: "sessao", t: `Último resultado desta sessão (${sessao.length} canais)` });
    try {
      const resp = await fetch("/api/biblioteca");
      const j = await resp.json();
      (j.temas || []).forEach((t) => (t.buscas || []).forEach((b) => opcoes.push({ v: `busca:${b.id}`, t: `Biblioteca · ${t.tema} · #${b.id} (${b.n_canais} canais)` })));
    } catch (_) { /* sem biblioteca: só a sessão */ }
    sel.innerHTML = opcoes.length
      ? opcoes.map((o) => `<option value="${escapeHtml(o.v)}">${escapeHtml(o.t)}</option>`).join("")
      : '<option value="">nenhuma fonte ainda</option>';
    if (opcoes.some((o) => o.v === anterior)) sel.value = anterior;
    await carregarCanais();
  }

  const COLUNAS_CSV = [
    { chave: "canal", rotulo: "Canal" }, { chave: "canal_url", rotulo: "URL" }, { chave: "inscritos", rotulo: "Inscritos" },
    { chave: "criado_em", rotulo: "Criado em" }, { chave: "idade_meses", rotulo: "Idade (meses)" }, { chave: "n_videos", rotulo: "Vídeos" },
    { chave: "videos_30d", rotulo: "Vídeos nos últimos 30 dias" }, { chave: "n_ultimos", rotulo: "Vídeos usados na mediana" },
    { chave: "mediana", rotulo: "Mediana de views" }, { chave: "media", rotulo: "Média de views" }, { chave: "tracao", rotulo: "Tração" },
    { chave: "sinal", rotulo: "Sinal" }, { chave: "maior_fator", rotulo: "Maior fator outlier" }, { chave: "n_outliers", rotulo: "Outliers" },
    { chave: "outliers_txt", rotulo: "Vídeos outlier" },
  ];
  const arred = (n, casas) => (n === null || n === undefined || !Number.isFinite(n)) ? null : Math.round(n * 10 ** casas) / 10 ** casas;

  function baixarCsv() {
    if (!linhasAtuais.length) return;
    const linhas = linhasAtuais.map((m) => ({
      ...m, idade_meses: arred(m.idade_meses, 1), media: arred(m.media, 0), tracao: arred(m.tracao, 3), sinal: m.sinal.rotulo,
      maior_fator: arred(m.maior_fator, 2), n_outliers: m.outliers.length,
      outliers_txt: m.outliers.map((x) => `${x.titulo} (${x.views} views, ${arred(x.fator, 1)}x)`).join(" | "),
    }));
    const blob = new Blob([M.toCsv(COLUNAS_CSV, linhas)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `metodo_canais_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ---------- calculadora rápida ----------
  function calcular() {
    const saida = $("mc-saida");
    const { valores, invalidos } = M.parseLista($("mc-views").value);
    const txtInsc = $("mc-inscritos").value.trim();
    const txtVideo = $("mc-video").value.trim();
    const insc = txtInsc ? M.parseContagem(txtInsc) : null;
    const video = txtVideo ? M.parseContagem(txtVideo) : null;
    const partes = [];
    const avisos = [...invalidos];
    if (txtInsc && insc === null) avisos.push(txtInsc);
    if (txtVideo && video === null) avisos.push(txtVideo);
    if (avisos.length) partes.push(`<div class="mt-aviso">Não entendi: ${avisos.map(escapeHtml).join(", ")}</div>`);

    const med = M.mediana(valores);
    const mean = M.media(valores);
    if (med !== null) {
      let linha = `<div><b>Mediana</b> de ${valores.length} vídeo(s): ${inteiro(med)} views · média: ${inteiro(mean)}</div>`;
      if (valores.length < 10) linha += `<div class="mt-aviso">Ele usa os últimos 10 vídeos; com ${valores.length} a mediana é frágil.</div>`;
      if (med > 0 && mean / med >= 1.5) linha += `<div class="mt-aviso">A média é ${fmt(mean / med, 1)}× a mediana: um ou dois vídeos puxam a média para cima. Use a mediana.</div>`;
      partes.push(linha);
      const t = M.tracao(med, insc);
      if (t !== null) partes.push(`<div><b>Tração</b> (mediana ÷ inscritos): ${fmt(t, 3)} ${badgeSinal(M.classificarTracao(t, limites()))}</div>`);
      else if (insc !== null) partes.push('<div class="mt-aviso">Informe inscritos maiores que zero para calcular a tração.</div>');
      const f = M.fatorOutlier(video, med);
      if (f !== null) partes.push(`<div><b>Fator outlier</b> do vídeo: ${fmt(f, 1)}× a mediana ${f >= fatorMinimo() ? `<span class="badge badge-green">acima do seu mínimo (${fmt(fatorMinimo(), 1)}×)</span>` : '<span class="badge badge-muted">abaixo do seu mínimo</span>'}</div>`);
    } else if (video !== null || insc !== null) {
      partes.push('<div class="mt-aviso">Cole as views dos últimos vídeos para calcular mediana, tração e fator outlier.</div>');
    }
    const idade = M.idadeMeses($("mc-criado").value);
    if (idade !== null) partes.push(`<div><b>Canal criado há</b> ${fmt(idade, 1)} meses</div>`);
    saida.innerHTML = partes.join("");
  }

  // ---------- semáforo de saturação ----------
  function atualizarSaturacao() {
    const bruto = $("ms-n").value;
    const s = bruto === "" ? null : M.semaforoSaturacao(bruto);
    const cls = !s ? "" : s.chave === "aberto" ? "badge-green" : s.chave === "abandone" ? "badge-red" : "badge-muted";
    $("ms-saida").innerHTML = s ? `<div><span class="badge ${cls}">${escapeHtml(s.rotulo)}</span></div><div>${escapeHtml(s.texto)}</div>` : "";
  }

  // ---------- ligação com o resto do app ----------
  function usarMedianaNasRecomendacoes() {
    const sel = $("rec-ref");
    if (!sel) return;
    sel.value = "mediana";
    if (typeof salvarPreferencias === "function") salvarPreferencias();
    $("mm-info").textContent = "Pronto: a triagem de recomendações agora usa a mediana.";
  }

  function iniciar() {
    iniciarChecklist();
    ["mp-n", "mp-cuidado", "mp-forte", "mp-fator", "mp-ordem", "mp-30d"].forEach((id) => {
      $(id).addEventListener("input", () => { renderPlanilha(); calcular(); });
      $(id).addEventListener("change", () => { renderPlanilha(); calcular(); });
    });
    $("mp-fonte").addEventListener("change", carregarCanais);
    $("mp-atualizar").addEventListener("click", carregarFontes);
    $("mp-csv").addEventListener("click", baixarCsv);
    ["mc-views", "mc-inscritos", "mc-video", "mc-criado"].forEach((id) => $(id).addEventListener("input", calcular));
    $("ms-n").addEventListener("input", atualizarSaturacao);
    $("mm-usar-mediana").addEventListener("click", usarMedianaNasRecomendacoes);
    document.querySelectorAll('.topnav-btn[data-view="metodo"]').forEach((b) => b.addEventListener("click", carregarFontes));
    calcular();
    atualizarSaturacao();
    renderPlanilha();
  }

  iniciar();
})();
