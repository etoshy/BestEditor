let termosValidados = [];
let subnichosValidados = [];
let jobAtual = null;
let pollTimer = null;

const el = (id) => document.getElementById(id);

function carregarPreferencias() {
  const ids = ["max_videos", "min_subs", "duracao_min", "duracao_max", "data_periodo", "ordenacao", "headless", "mutar_audio", "trends", "janela_meses", "descartar_fora_janela", "rec-itens", "rec-meses", "rec-ref", "rec-fator", "rec-escopo", "n_navegadores", "ra-ativo", "ra-itens", "ra-meses", "ra-ref", "ra-fator"];
  ids.forEach((id) => {
    const node = el(id);
    if (!node) return;
    try {
      const raw = localStorage.getItem(`niche_miner_${id}`);
      if (raw === null) return;
      if (node.type === "checkbox") node.checked = raw === "true";
      else node.value = raw;
    } catch (_) {}
  });
}

function salvarPreferencias() {
  const ids = ["max_videos", "min_subs", "duracao_min", "duracao_max", "data_periodo", "ordenacao", "headless", "mutar_audio", "trends", "janela_meses", "descartar_fora_janela", "rec-itens", "rec-meses", "rec-ref", "rec-fator", "rec-escopo", "n_navegadores", "ra-ativo", "ra-itens", "ra-meses", "ra-ref", "ra-fator"];
  ids.forEach((id) => {
    const node = el(id);
    if (!node) return;
    try { localStorage.setItem(`niche_miner_${id}`, node.type === "checkbox" ? String(node.checked) : node.value); } catch (_) {}
  });
}

carregarPreferencias();
document.querySelectorAll("#max_videos, #min_subs, #duracao_min, #duracao_max, #data_periodo, #ordenacao, #headless, #mutar_audio, #trends, #janela_meses, #descartar_fora_janela, #rec-itens, #rec-meses, #rec-ref, #rec-fator, #rec-escopo, #n_navegadores, #ra-ativo, #ra-itens, #ra-meses, #ra-ref, #ra-fator")
  .forEach((node) => node.addEventListener("change", salvarPreferencias));

async function fetchJson(url, options = {}) {
  const resp = await fetch(url, options);
  let data;
  try { data = await resp.json(); } catch (_) { data = { ok: false, erro: `HTTP ${resp.status}` }; }
  if (!resp.ok && data.ok !== false) data.ok = false;
  return data;
}

// ---------- passo 1: gerar prompt ----------
el("btn-gerar-prompt").addEventListener("click", async () => {
  const nicho = el("nicho").value.trim();
  if (!nicho) { el("nicho").focus(); return; }
  try {
    const data = await fetchJson("/api/gerar-prompt", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nicho, n_subnichos: el("n_subnichos").value, n_termos: el("n_termos").value })
    });
    if (!data.ok) return alert(data.erro || "Não foi possível gerar o prompt.");
    el("prompt-text").textContent = data.prompt;
    el("prompt-wrap").style.display = "block";
  } catch (e) { alert(`Erro de comunicação: ${e.message}`); }
});

el("btn-copiar-prompt").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(el("prompt-text").textContent); } catch (_) {}
  const btn = el("btn-copiar-prompt"); const original = btn.textContent;
  btn.textContent = "Copiado!"; setTimeout(() => (btn.textContent = original), 1200);
});

// ---------- passo 2: validar JSON ----------
el("btn-validar").addEventListener("click", async () => {
  const texto = el("json-input").value.trim();
  const feedback = el("json-feedback");
  feedback.innerHTML = "";
  if (!texto) return;
  try {
    const data = await fetchJson("/api/validar-json", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ texto })
    });
    if (!data.ok) {
      feedback.innerHTML = `<div class="error-msg">${escapeHtml(data.erro || "JSON inválido")}</div>`;
      el("btn-iniciar").disabled = true; return;
    }
    termosValidados = Array.isArray(data.termos) ? data.termos : [];
    subnichosValidados = Array.isArray(data.subnichos) ? data.subnichos : [];
    feedback.innerHTML = `<div class="ok-msg">${subnichosValidados.length} subnichos, ${termosValidados.length} termos encontrados.</div>`;
    const tagsWrap = el("termos-tags"); tagsWrap.innerHTML = "";
    subnichosValidados.forEach((s) => {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = `${s.nome}: ${(s.termos || []).join(", ")}`;
      tagsWrap.appendChild(tag);
    });
    el("btn-iniciar").disabled = !termosValidados.length;
  } catch (e) {
    feedback.innerHTML = `<div class="error-msg">Erro de comunicação: ${escapeHtml(e.message)}</div>`;
    el("btn-iniciar").disabled = true;
  }
});

// ---------- passo 3: iniciar ----------
// Parâmetros do passo 3 (duração, canal novo, inscritos...), usados pela busca por termo e pelas recomendações.
function configPasso3() {
  const duracaoMin = parseInt(el("duracao_min").value, 10);
  const duracaoMax = parseInt(el("duracao_max").value, 10);
  if (!Number.isFinite(duracaoMin) || !Number.isFinite(duracaoMax) || duracaoMin < 0 || duracaoMax < 0 || (duracaoMax > 0 && duracaoMin > duracaoMax)) {
    alert("A duração mínima/máxima é inválida. Use mínimo <= máximo; máximo 0 significa sem limite.");
    return null;
  }
  return {
    max_videos: parseInt(el("max_videos").value, 10),
    min_subs: parseInt(el("min_subs").value, 10),
    duracao_min: duracaoMin,
    duracao_max: duracaoMax,
    headless: el("headless").checked,
    mutar_audio: el("mutar_audio").checked,
    janela_meses: parseInt(el("janela_meses").value, 10),
    descartar_fora_janela: el("descartar_fora_janela").checked,
    n_navegadores: parseInt(el("n_navegadores").value, 10) || 1,
  };
}

function configRecomendadosAuto() {
  return {
    ativo: el("ra-ativo").checked,
    max_itens: parseInt(el("ra-itens").value, 10),
    meses_max: parseInt(el("ra-meses").value, 10),
    referencia: el("ra-ref").value,
    fator: parseFloat(el("ra-fator").value),
  };
}

function travarBotoes() { el("btn-iniciar").disabled = true; el("btn-rec-iniciar").disabled = true; }
function liberarBotoes() {
  el("btn-iniciar").disabled = !termosValidados.length;
  el("btn-rec-iniciar").disabled = !urlsRecomendados().length;
}

async function iniciarMineracao(url, corpo, mensagemInicial) {
  salvarPreferencias();
  travarBotoes();
  el("console").innerHTML = "";
  el("results-area").innerHTML = `<div class="empty-state">${mensagemInicial}</div>`;
  setStatus("rodando");
  try {
    const data = await fetchJson(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) });
    if (!data.ok) { alert(data.erro || "Não foi possível iniciar."); setStatus("erro"); liberarBotoes(); return; }
    acompanharMineracao(data.job_id);
  } catch (e) {
    alert(`Erro de comunicação: ${e.message}`); setStatus("erro"); liberarBotoes();
  }
}

function acompanharMineracao(jobId) {
  jobAtual = jobId;
  let cursor = 0;
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const j = await fetchJson(`/api/logs/${jobAtual}?cursor=${cursor}`);
      if (!j.ok) return;
      cursor = j.cursor; appendLogs(j.logs || []); setStatus(j.status);
      if (j.status === "concluido") {
        clearInterval(pollTimer);
        await carregarResultado(jobAtual);
        liberarBotoes();
      } else if (j.status === "erro") {
        clearInterval(pollTimer); liberarBotoes();
      }
    } catch (e) { appendLogs([`[poll erro] ${e.message}`]); }
  }, 1000);
}

el("btn-iniciar").addEventListener("click", async () => {
  if (!termosValidados.length) return;
  const cfg = configPasso3();
  if (!cfg) return;
  await iniciarMineracao("/api/iniciar", {
    nicho: el("nicho").value.trim(),
    subnichos: subnichosValidados,
    termos: termosValidados,
    ...cfg,
    data_periodo: el("data_periodo").value,
    ordenacao: el("ordenacao").value,
    trends: el("trends").checked,
    recomendados_auto: configRecomendadosAuto(),
  }, "coletando todos os termos; falhas isoladas não interrompem os demais...");
});

el("ra-ativo").addEventListener("change", () => {
  el("ra-opcoes").style.display = el("ra-ativo").checked ? "" : "none";
});
el("ra-opcoes").style.display = el("ra-ativo").checked ? "" : "none";

function setStatus(status) {
  const pill = el("status-pill");
  pill.className = "status-pill " + status;
  pill.textContent = status;
}
function appendLogs(linhas) {
  const console_ = el("console");
  (linhas || []).forEach((l) => { const div = document.createElement("div"); div.className = "line"; div.textContent = l; console_.appendChild(div); });
  console_.scrollTop = console_.scrollHeight;
}
async function carregarResultado(jobId) {
  const j = await fetchJson(`/api/resultado/${jobId}`); if (j.ok) renderResultado(j.resultado);
}

function formatViews(v) {
  if (v === null || v === undefined || v === "") return "?";
  const n = Number(v); return Number.isFinite(n) ? new Intl.NumberFormat("pt-BR").format(n) : String(v);
}
function safeScore(v) { return Number.isFinite(Number(v)) ? Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 2 }) : "?"; }
function escapeHtml(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function renderResultado(resultado) {
  const area = el("results-area");
  const ranking = Array.isArray(resultado) ? resultado : (resultado?.ranking_geral || resultado?.ranking_nao_verificados || []);
  const verificados = Array.isArray(resultado) ? [] : (resultado?.verificados || []);
  if (!ranking.length && !verificados.length) {
    area.innerHTML = renderRelatorioRecomendados(resultado?.recomendados) + '<div class="empty-state">nenhum canal passou dos filtros mínimos</div>';
    return;
  }

  const falhas = Array.isArray(resultado?.falhas_termos) ? resultado.falhas_termos : [];
  const filtros = resultado?.filtros || {};
  const counts = {
    geral: ranking.length,
    nichos: Object.keys(resultado?.rankings_nichos || {}).length,
    subnichos: Object.keys(resultado?.rankings_subnichos || {}).length,
    paises: Object.keys(resultado?.rankings_paises || {}).length,
    idiomas: Object.keys(resultado?.rankings_idiomas || {}).length,
    verificados: verificados.length,
  };

  area.innerHTML = `
    <div class="results-hero"><div class="results-number">${counts.geral}</div><div class="results-caption">canais candidatos — regra: mais inscritos + menos vídeos + maior recência do primeiro vídeo</div></div>
    <div class="filter-summary"><strong>Filtros usados:</strong> ${escapeHtml(filtros.duracao_min ?? "?")}–${escapeHtml(filtros.duracao_max ?? "?")} min · ${escapeHtml(filtros.data_periodo || "?")} · ${escapeHtml(filtros.ordenacao || "?")} · áudio ${resultado?.mutar_audio ? "mutado" : "ativo"}</div>
    ${falhas.length ? `<div class="warning-box"><strong>${falhas.length} termo(s) com falha isolada.</strong> Os demais continuam válidos. ${escapeHtml(falhas.slice(0, 2).join(" | "))}${falhas.length > 2 ? " …" : ""}</div>` : ""}
    ${renderJanelaBar(resultado)}
    ${renderRelatorioRecomendados(resultado?.recomendados)}
    ${renderBarraPromptCanais(resultado)}
    ${renderOpportunityOverview(resultado?.resumo_nichos || [], resultado?.resumo_subnichos || [])}
    <div class="result-tabs">
      <button class="result-tab active" data-result-tab="geral">Geral (${counts.geral})</button>
      <button class="result-tab" data-result-tab="nichos">Por nicho (${counts.nichos})</button>
      <button class="result-tab" data-result-tab="subnichos">Por subnicho (${counts.subnichos})</button>
      <button class="result-tab" data-result-tab="paises">Por país (${counts.paises})</button>
      <button class="result-tab" data-result-tab="idiomas">Por idioma (${counts.idiomas})</button>
      <button class="result-tab" data-result-tab="verificados">Verificados (${counts.verificados})</button>
    </div>
    <section class="result-panel active" id="panel-geral">${renderUnverifiedTable(ranking, true)}</section>
    <section class="result-panel" id="panel-nichos" style="display:none">${renderGroupedPanel(resultado?.rankings_nichos || {}, "nicho")}</section>
    <section class="result-panel" id="panel-subnichos" style="display:none">${renderGroupedPanel(resultado?.rankings_subnichos || {}, "subnicho")}</section>
    <section class="result-panel" id="panel-paises" style="display:none">${renderGroupedPanel(resultado?.rankings_paises || {}, "pais")}</section>
    <section class="result-panel" id="panel-idiomas" style="display:none">${renderGroupedPanel(resultado?.rankings_idiomas || {}, "idioma")}</section>
    <section class="result-panel" id="panel-verificados" style="display:none">${renderVerifiedTable(verificados)}</section>
  `;

  area.querySelectorAll('.result-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      area.querySelectorAll('.result-tab').forEach((b) => b.classList.remove('active'));
      area.querySelectorAll('.result-panel').forEach((p) => p.style.display = 'none');
      btn.classList.add('active'); const panel = el(`panel-${btn.dataset.resultTab}`); if (panel) panel.style.display = 'block';
    });
  });
}

function renderOpportunityOverview(nichos, subnichos) {
  const topNicho = Array.isArray(nichos) && nichos.length ? nichos[0] : null;
  const topSub = Array.isArray(subnichos) && subnichos.length ? subnichos[0] : null;
  if (!topNicho && !topSub) return "";

  const renderTopChannels = (row) => {
    const tops = Array.isArray(row?.top_canais) ? row.top_canais.slice(0, 3) : [];
    if (!tops.length) return '<span class="muted-small">sem canais suficientes</span>';
    return tops.map((c, i) => `<div class="opp-channel"><span>#${i + 1}</span><a href="${escapeHtml(c.canal_url || '#')}" target="_blank" rel="noopener">${escapeHtml(c.canal || 'canal')}</a><strong>${safeScore(c.score)}</strong></div>`).join('');
  };

  const renderRows = (rows, labelKey) => {
    if (!Array.isArray(rows) || !rows.length) return '<div class="empty-state">sem dados</div>';
    return `<div class="opportunity-table-wrap"><table class="opportunity-table"><thead><tr><th>#</th><th>${labelKey === 'nicho' ? 'Nicho' : 'Subnicho'}</th><th>Canais</th><th>Score oportunidade</th><th>Melhor score</th><th>Top canais</th></tr></thead><tbody>${rows.slice(0, 12).map((r) => `<tr><td class="opp-rank">${escapeHtml(r.rank)}</td><td><strong>${escapeHtml(r[labelKey] || '?')}</strong></td><td>${escapeHtml(r.candidatos ?? 0)}</td><td class="opp-score">${safeScore(r.score_oportunidade)}</td><td>${safeScore(r.melhor_score)}</td><td>${renderTopChannels(r)}</td></tr>`).join('')}</tbody></table></div>`;
  };

  return `
    <section class="opportunity-overview">
      <div class="opportunity-head">
        <div>
          <div class="section-kicker">PRIORIDADE DE DESCOBERTA</div>
          <h3>Nichos organizados pelos canais mais promissores</h3>
          <p>O índice combina o melhor canal do grupo com os três melhores scores e a média do grupo. A regra do canal continua sendo inscritos ↑, poucos vídeos ↑ e primeiro vídeo recente ↑.</p>
        </div>
        <div class="opportunity-winners">
          ${topNicho ? `<div class="winner-card"><span>nicho #1</span><strong>${escapeHtml(topNicho.nicho || '?')}</strong><em>${safeScore(topNicho.score_oportunidade)}</em></div>` : ''}
          ${topSub ? `<div class="winner-card"><span>subnicho #1</span><strong>${escapeHtml(topSub.subnicho || '?')}</strong><em>${safeScore(topSub.score_oportunidade)}</em></div>` : ''}
        </div>
      </div>
      <div class="opportunity-block"><div class="section-kicker">RANKING DE NICHOS</div>${renderRows(nichos, 'nicho')}</div>
      <div class="opportunity-block"><div class="section-kicker">RANKING DE SUBNICHOS</div>${renderRows(subnichos, 'subnicho')}</div>
    </section>
  `;
}

function renderGroupedPanel(groups, kind) {
  const labels = Object.keys(groups || {});
  if (!labels.length) return '<div class="empty-state">nenhum agrupamento disponível</div>';
  const selectId = `group-select-${kind}`;
  const groupId = `group-table-${kind}`;
  const options = labels.map((label, i) => `<option value="${i}">${escapeHtml(label)} (${groups[label].length})</option>`).join('');
  const first = groups[labels[0]] || [];
  const firstHtml = renderUnverifiedTable(first, false);
  const encoded = encodeURIComponent(JSON.stringify(groups));
  return `<div class="group-toolbar"><div><label for="${selectId}">Escolha o ${escapeHtml(kind)}</label><select id="${selectId}">${options}</select></div><div class="group-caption">${labels.length} grupos disponíveis</div></div><div id="${groupId}">${firstHtml}</div><script type="application/json" id="data-${groupId}">${encoded}</script>`;
}

function wireGroupedPanels() {
  ["nicho", "subnicho", "pais", "idioma"].forEach(kind => {
    const select = el(`group-select-${kind}`); if (!select) return;
    const groupData = el(`data-group-table-${kind}`); if (!groupData) return;
    let groups; try { groups = JSON.parse(decodeURIComponent(groupData.textContent)); } catch (_) { groups = {}; }
    const labels = Object.keys(groups);
    select.addEventListener("change", () => {
      const label = labels[Number(select.value)];
      const host = el(`group-table-${kind}`); if (host) host.innerHTML = renderUnverifiedTable(groups[label] || [], false);
    });
  });
}

// Reaproveita a renderização acima e conecta os selects depois que o DOM recebe o resultado.
const _renderResultadoOriginal = renderResultado;
renderResultado = function(resultado) { _renderResultadoOriginal(resultado); wireGroupedPanels(); };

// ---------- canais: 5 primeiros, 3 populares, 3 recentes, frequência e janela ----------
let mostrarForaJanela = false;   // canais fora da janela começam ocultos
let ultimoResultado = null;      // usado para redesenhar ao alternar "mostrar fora da janela"
let detalheSeq = 0;

function formatData(iso, exata) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  if (!m) return "?";
  return `${exata === false ? "~" : ""}${m[3]}/${m[2]}/${m[1]}`;   // "~" = data aproximada ("há 3 semanas")
}

function renderListaVideos(titulo, lista, vazio) {
  const itens = Array.isArray(lista) ? lista : [];
  const corpo = itens.length
    ? itens.map((v) => `<li><a href="${escapeHtml(v.url || '#')}" target="_blank" rel="noopener">${escapeHtml(v.titulo || 'sem título')}</a><div class="popular-meta">${escapeHtml(v.views_text || formatViews(v.views_num))} · ${formatData(v.data, v.data_exata)}${v.duracao ? ` · ${escapeHtml(v.duracao)}` : ''}</div></li>`).join('')
    : `<li class="muted-small">${escapeHtml(vazio || 'não disponível')}</li>`;
  return `<div class="detail-col"><div class="section-kicker">${escapeHtml(titulo)}</div><ol class="video-list">${corpo}</ol></div>`;
}

function dataPrimeiroVideo(c) {
  if (c.primeiro_video_confiavel === false) return '<span class="muted-small">não confirmado</span>';
  const p = Array.isArray(c.primeiros_5_videos) ? c.primeiros_5_videos[0] : null;
  const iso = c.primeiro_video_data_publicacao || (p && p.data) || "";
  if (!iso) return '<span class="muted-small">?</span>';
  return escapeHtml(formatData(iso, c.primeiro_video_data_publicacao ? true : (p ? p.data_exata : false)));
}

function dataUltimoVideo(c) {
  const u = Array.isArray(c.ultimos_3_videos) ? c.ultimos_3_videos[0] : null;
  const iso = c.ultimo_video_data_publicacao || (u && u.data) || "";
  if (!iso) return '<span class="muted-small">?</span>';
  const dias = (c.dias_desde_ultimo_video ?? null) !== null ? `<div class="popular-meta">há ${escapeHtml(c.dias_desde_ultimo_video)} dia(s)</div>` : "";
  return escapeHtml(formatData(iso, c.ultimo_video_data_publicacao ? true : (u ? u.data_exata : false))) + dias;
}

function renderFrequencia(c) {
  const bits = [];
  if ((c.frequencia_videos_por_semana ?? null) !== null) bits.push(`~${safeScore(c.frequencia_videos_por_semana)}/sem`);
  if (c.frequencia_n_amostra) bits.push(`${c.frequencia_n_amostra} vídeos`);
  if (c.frequencia_amostra_pequena) bits.push("amostra pequena");
  const parado = c.frequencia_atividade === "parado" ? ' <span class="badge badge-red">parado</span>' : "";
  return `<strong>${escapeHtml(c.frequencia_label || "dados insuficientes")}</strong>${parado}<div class="popular-meta">${escapeHtml(bits.join(" · "))}</div>`;
}

function renderJanela(c) {
  const m = c.meses_desde_primeiro_video;
  const meses = (m === null || m === undefined) ? "" : `<div class="popular-meta">1º vídeo há ${safeScore(m)} m</div>`;
  if (!c.janela_meses) return meses || '<span class="muted-small">—</span>';   // sem janela definida: só informa a idade
  if (c.fora_da_janela) return `<span class="badge badge-red">fora</span>${meses}`;
  if (c.idade_desconhecida) return `<span class="badge badge-muted">idade?</span>${meses}`;
  return `<span class="badge badge-green">novo</span>${meses}`;
}

function renderDetalhesCanal(c) {
  const nichos = Array.isArray(c.nichos) ? c.nichos.join(", ") : (c.nicho || "?");
  const subs = Array.isArray(c.subnichos) ? c.subnichos.join(", ") : (c.subnicho || "?");
  const amostra = Array.isArray(c.amostra_videos) ? c.amostra_videos : [];
  const amostraHtml = amostra.length
    ? `<details class="amostra"><summary>ver os ${amostra.length} vídeos usados na frequência</summary><ol class="video-list">${amostra.map((v) => `<li><a href="${escapeHtml(v.url || '#')}" target="_blank" rel="noopener">${escapeHtml(v.titulo || 'sem título')}</a> <span class="popular-meta">${escapeHtml(v.views_text || formatViews(v.views_num))} · ${formatData(v.data, v.data_exata)}</span></li>`).join('')}</ol></details>`
    : "";
  return `<div class="detail-grid">
      ${renderListaVideos("5 primeiros vídeos (mais antigos)", c.primeiros_5_videos, c.primeiro_video_confiavel === false ? "não foi possível confirmar quais são os primeiros" : "não disponível")}
      ${renderListaVideos("3 mais populares", c.top_3_populares)}
      ${renderListaVideos("3 mais recentes", c.ultimos_3_videos)}
    </div>
    <div class="detail-meta">
      <span>País: ${escapeHtml(c.pais_canal || "desconhecido")}</span>
      <span>Idioma: ${escapeHtml(c.idioma_canal || "desconhecido")}</span>
      <span>Nicho: ${escapeHtml(nichos)}</span>
      <span>Subnicho: ${escapeHtml(subs)}</span>
      <span>Canal criado em: ${c.data_criacao_canal ? escapeHtml(formatData(c.data_criacao_canal)) : "?"}</span>
      <span>Dados: ${c.dados_incompletos_texto ? `incompleto (${escapeHtml(c.dados_incompletos_texto)})` : "completos"}</span>
    </div>
    ${amostraHtml}`;
}

// ---------- ordenação das tabelas de canais (lógica pura em ordenacao.js) ----------
const ORD_KEY = "niche_miner_ordenacao";
let ordenacaoEstado = (() => {
  try {
    const salvo = JSON.parse(localStorage.getItem(ORD_KEY) || "null");
    if (salvo) return NicheOrdenacao.normalizar(salvo.campo, salvo.dir);
  } catch (_) { /* preferência ilegível: volta ao padrão */ }
  return NicheOrdenacao.normalizar("padrao");
})();
const tabelasCanais = new Map();   // id do host -> argumentos; permite redesenhar TODAS as tabelas quando a ordem muda
let tabelasSeq = 0;

function definirOrdenacao(campo, dir) {
  ordenacaoEstado = NicheOrdenacao.normalizar(campo, dir);
  try { localStorage.setItem(ORD_KEY, JSON.stringify(ordenacaoEstado)); } catch (_) {}
  rerenderTabelasCanais();
}

function rerenderTabelasCanais() {
  document.querySelectorAll("[data-sort-host]").forEach((host) => {
    const id = Number(host.dataset.sortHost);
    const reg = tabelasCanais.get(id);
    tabelasCanais.delete(id);
    if (!reg) return;
    const tmp = document.createElement("div");
    tmp.innerHTML = renderUnverifiedTable(reg.canais, reg.showGroup, reg.opts);
    host.replaceWith(...tmp.childNodes);
  });
  // descarta registros de tabelas que saíram da tela (ex.: troca de grupo)
  [...tabelasCanais.keys()].forEach((id) => { if (!document.querySelector(`[data-sort-host="${id}"]`)) tabelasCanais.delete(id); });
}

function htmlBarraOrdenacao() {
  const { campo, dir } = ordenacaoEstado;
  const opcoes = NicheOrdenacao.ORDEM.map((k) => `<option value="${k}"${k === campo ? " selected" : ""}>${escapeHtml(NicheOrdenacao.METRICAS[k].rotulo)}</option>`).join("");
  return `<div class="sort-bar"><label>Ordenar canais por</label><select class="sort-select">${opcoes}</select>`
    + `<button type="button" class="sort-dir"${campo === "padrao" ? " disabled" : ""} title="Inverter a ordem">${dir === "asc" ? "▲ crescente" : "▼ decrescente"}</button>`
    + `<span class="hint">${escapeHtml(NicheOrdenacao.METRICAS[campo].ajuda)}</span></div>`;
}

document.addEventListener("click", (ev) => {
  const alvo = ev.target && ev.target.closest ? ev.target : null;
  if (!alvo) return;
  const th = alvo.closest("th.sortable");
  if (th) {
    const campo = th.dataset.sort;
    const mesmo = ordenacaoEstado.campo === campo;
    definirOrdenacao(campo, mesmo ? (ordenacaoEstado.dir === "asc" ? "desc" : "asc") : NicheOrdenacao.METRICAS[campo].padrao);
    return;
  }
  if (alvo.closest(".sort-dir") && ordenacaoEstado.campo !== "padrao") {
    definirOrdenacao(ordenacaoEstado.campo, ordenacaoEstado.dir === "asc" ? "desc" : "asc");
  }
});

document.addEventListener("change", (ev) => {
  if (!ev.target || !ev.target.classList || !ev.target.classList.contains("sort-select")) return;
  definirOrdenacao(ev.target.value, NicheOrdenacao.METRICAS[ev.target.value].padrao);
});

function renderUnverifiedTable(canais, showGroup, opts = {}) {
  const mostrarFora = opts.mostrarFora ?? mostrarForaJanela;
  const todos = Array.isArray(canais) ? canais : [];
  if (!todos.length) return '<div class="empty-state">nenhum canal não verificado neste grupo</div>';
  const filtrados = mostrarFora ? todos : todos.filter((c) => !c.fora_da_janela);
  const ocultos = todos.length - filtrados.length;
  const aviso = ocultos ? `<div class="hint" style="margin:0 0 8px">${ocultos} canal(is) fora da janela ocultos — marque "mostrar canais fora da janela" para vê-los.</div>` : "";
  if (!filtrados.length) return aviso + '<div class="empty-state">nenhum canal dentro da janela neste grupo</div>';

  const { campo, dir } = ordenacaoEstado;
  const lista = NicheOrdenacao.ordenar(filtrados, campo, dir);
  const combinadas = NicheOrdenacao.posicaoCombinada(lista);
  const hostId = ++tabelasSeq;
  tabelasCanais.set(hostId, { canais, showGroup, opts });
  const th = (chave, rotulo, dica) => `<th class="sortable${campo === chave ? " active" : ""}" data-sort="${chave}" title="${escapeHtml(dica || `Ordenar por ${rotulo}`)}">${rotulo}${campo === chave ? (dir === "asc" ? " ▲" : " ▼") : ""}</th>`;
  const razao = (a, b) => { const r = NicheOrdenacao.razao(a, b); return r === null ? "?" : escapeHtml(formatViews(Math.round(r))); };

  let html = `<div class="sort-host" data-sort-host="${hostId}">${htmlBarraOrdenacao()}${aviso}<div class="table-wrap"><table class="candidate-table"><thead><tr><th>#</th><th>Canal</th>`
    + `${th("inscritos", "Inscritos")}${th("videos", "Vídeos")}${th("views", "Views totais")}`
    + `${th("views_por_video", "Views/vídeo", "Views totais ÷ vídeos publicados")}${th("inscritos_por_video", "Inscr./vídeo", "Inscritos ÷ vídeos publicados")}`
    + `<th>1º vídeo</th><th>Último vídeo</th><th>Frequência</th><th>Janela</th>`
    + `${th("combinada", "Combinada", "Posição média (1 = melhor) em inscritos, views e menos vídeos")}${th("score", "Score")}<th></th></tr></thead><tbody>`;
  lista.forEach((c, i) => {
    const id = `detalhe-${++detalheSeq}`;
    const termos = Array.isArray(c.termos_busca) ? c.termos_busca.join(", ") : (c.termo_busca || "");
    const posicao = campo === "padrao" ? (showGroup ? (c.rank_geral || i + 1) : (c.rank_grupo || i + 1)) : i + 1;
    html += `<tr><td>${posicao}</td>`
      + `<td class="canal"><a href="${escapeHtml(c.canal_url || '#')}" target="_blank" rel="noopener">${escapeHtml(c.canal || '')}</a><div class="channel-term">${escapeHtml(termos)}</div></td>`
      + `<td>${escapeHtml(c.inscritos_text || (c.inscritos_num ? formatViews(c.inscritos_num) : '?'))}</td>`
      + `<td>${c.n_videos ?? '?'}</td>`
      + `<td>${(c.views_totais ?? null) !== null ? escapeHtml(formatViews(c.views_totais)) : '?'}</td>`
      + `<td>${razao(c.views_totais, c.n_videos)}</td><td>${razao(c.inscritos_num, c.n_videos)}</td>`
      + `<td>${dataPrimeiroVideo(c)}</td><td>${dataUltimoVideo(c)}</td>`
      + `<td>${renderFrequencia(c)}</td><td>${renderJanela(c)}</td>`
      + `<td>${combinadas.get(c).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}</td>`
      + `<td class="score">${safeScore(c.score)}</td>`
      + `<td><button type="button" class="btn-detalhes" data-detalhes="${id}" aria-expanded="false">detalhes ▾</button></td></tr>`
      + `<tr class="detail-row" id="${id}" hidden><td colspan="14">${renderDetalhesCanal(c)}</td></tr>`;
  });
  return html + '</tbody></table></div></div>';
}

function renderJanelaBar(resultado) {
  ultimoResultado = resultado;
  const a = resultado?.analise || {};
  const r = resultado?.resumo_janela || {};
  const id = resultado?.busca_id;
  const resumo = a.janela_meses
    ? `<strong>Canal novo:</strong> 1º vídeo há no máximo ${escapeHtml(a.janela_meses)} mês(es) · <span class="badge badge-green">${r.dentro ?? 0} dentro</span> <span class="badge badge-muted">${r.desconhecida ?? 0} idade desconhecida</span> <span class="badge badge-red">${r.fora ?? 0} fora</span>`
    : "<strong>Canal novo:</strong> sem limite de idade";
  const controle = a.janela_meses
    ? `<label class="checkline" style="margin:0"><input type="checkbox" id="toggle-fora-janela" ${mostrarForaJanela ? "checked" : ""}> mostrar canais fora da janela</label>` : "";
  const salvo = id ? `<a href="#" data-abrir-busca="${escapeHtml(id)}">salva na biblioteca (#${escapeHtml(id)}) →</a>` : '<span class="muted-small">não foi salva na biblioteca</span>';
  return `<div class="janela-bar"><div>${resumo}</div>${controle}${salvo}</div>`;
}

document.addEventListener("click", (ev) => {
  const btn = ev.target.closest ? ev.target.closest(".btn-detalhes") : null;
  if (!btn) return;
  const linha = document.getElementById(btn.dataset.detalhes);
  if (!linha) return;
  const abrir = linha.hidden;
  linha.hidden = !abrir;
  btn.setAttribute("aria-expanded", String(abrir));
  btn.textContent = abrir ? "ocultar ▴" : "detalhes ▾";
});

document.addEventListener("change", (ev) => {
  if (!ev.target || ev.target.id !== "toggle-fora-janela") return;
  mostrarForaJanela = ev.target.checked;
  if (!ultimoResultado) return;
  const aba = document.querySelector("#results-area .result-tab.active")?.dataset.resultTab;
  renderResultado(ultimoResultado);
  if (aba) document.querySelector(`#results-area .result-tab[data-result-tab="${aba}"]`)?.click();
});

function renderVerifiedTable(canais) {
  if (!canais.length) return '<div class="empty-state">nenhum canal verificado encontrado nos vídeos coletados</div>';
  let html = '<div class="table-wrap"><table><thead><tr><th>#</th><th>Canal</th><th>Nicho</th><th>Subnicho</th><th>Termo</th><th>Vídeo exemplo</th><th>Visualizações</th></tr></thead><tbody>';
  canais.forEach((c, i) => { html += `<tr><td>${i + 1}</td><td class="canal"><a href="${escapeHtml(c.canal_url || '#')}" target="_blank" rel="noopener">${escapeHtml(c.canal || '')}</a></td><td>${escapeHtml(c.nicho || '?')}</td><td>${escapeHtml(c.subnicho || '?')}</td><td>${escapeHtml(c.termo_busca || '')}</td><td>${c.video_exemplo ? `<a href="${escapeHtml(c.video_exemplo)}" target="_blank" rel="noopener">abrir vídeo</a>` : '?'}</td><td>${escapeHtml(c.views_text_video_exemplo || '?')}</td></tr>`; });
  return html + '</tbody></table></div>';
}


// ---------- recomendações de um vídeo ----------
function urlsRecomendados() {
  return el("rec-urls").value.split("\n").map((l) => l.trim()).filter(Boolean);
}

el("rec-urls").addEventListener("input", () => {
  if (el("status-pill").textContent === "rodando") return;      // não reabilita no meio de uma coleta
  el("btn-rec-iniciar").disabled = !urlsRecomendados().length;
});

el("btn-rec-exemplos").addEventListener("click", () => {
  const canais = (ultimoResultado && (ultimoResultado.ranking_geral || ultimoResultado.ranking_nao_verificados)) || [];
  const urls = canais.filter((c) => c.video_exemplo && !c.fora_da_janela).slice(0, 5).map((c) => c.video_exemplo);
  if (!urls.length) return alert("Rode uma mineração antes: os vídeos de exemplo vêm dos canais do último resultado.");
  const atuais = urlsRecomendados();
  el("rec-urls").value = [...atuais, ...urls.filter((u) => !atuais.includes(u))].join("\n");
  el("rec-urls").dispatchEvent(new Event("input"));
});

el("btn-rec-iniciar").addEventListener("click", async () => {
  const urls = urlsRecomendados();
  if (!urls.length) return;
  const cfg = configPasso3();
  if (!cfg) return;
  await iniciarMineracao("/api/iniciar-recomendados", {
    urls, ...cfg,
    nicho: el("nicho").value.trim(),
    max_itens: parseInt(el("rec-itens").value, 10),
    meses_max: parseInt(el("rec-meses").value, 10),
    referencia: el("rec-ref").value,
    fator: parseFloat(el("rec-fator").value),
    escopo: el("rec-escopo").value,
  }, "lendo os recomendados de cada vídeo e conferindo os canais que passam na triagem...");
});

const MOTIVOS_REC = {
  ok: "aprovado", abaixo_da_media: "abaixo do corte de views", verificado: "canal verificado", antigo: "vídeo antigo demais",
  idade_desconhecida: "idade não identificada", sem_views: "views não identificadas", nao_video: "short, playlist ou live",
  duracao: "duração fora do filtro", patrocinado: "patrocinado", duplicado: "já visto em outra lateral",
};
function motivoRec(item) {
  const m = String(item.motivo || "");
  if (m.startsWith("validacao:")) return `descartado ao abrir o vídeo (${m.slice(10).replace(/^fora_do_periodo.*/, "fora do período")})`;
  if (item.analisado) return "canal analisado ✓";
  return MOTIVOS_REC[m] || m;
}

function renderRelatorioRecomendados(rel) {
  if (!rel || !Array.isArray(rel.grupos)) return "";
  const cfg = rel.cfg || {};
  const ref = cfg.referencia === "mediana" ? "mediana" : "média";
  const grupos = rel.grupos.map((g) => {
    const nome = `<strong>${escapeHtml(g.origem_titulo || "(sem título)")}</strong>`;
    if (g.valor === null || g.valor === undefined) return `<div class="rec-grupo">${nome} · <span class="muted-small">nenhum recomendado elegível (não verificado + recente)</span></div>`;
    return `<div class="rec-grupo">${nome} · ${g.elegiveis} elegíveis de ${g.coletados} · ${ref} ${escapeHtml(formatViews(g.valor))} views · corte ${escapeHtml(formatViews(g.limiar))} · `
      + `<span class="badge badge-green">${g.aprovados} ${g.aprovados === 1 ? "aprovado" : "aprovados"}</span>${g.pouco_confiavel ? ' <span class="badge badge-muted">poucos elegíveis: referência frágil</span>' : ""}</div>`;
  }).join("");
  const itens = [...(rel.itens || [])].sort((a, b) => (Number(b.analisado) - Number(a.analisado)) || ((b.razao_media ?? -1) - (a.razao_media ?? -1)));
  const linhas = itens.map((i) => {
    const titulo = String(i.titulo || "").length > 70 ? `${String(i.titulo).slice(0, 70)}…` : String(i.titulo || "");
    return `<tr class="${i.analisado ? "rec-ok" : "rec-fora"}"><td><a href="${escapeHtml(i.url || "#")}" target="_blank" rel="noopener">${escapeHtml(titulo)}</a></td>`
      + `<td>${escapeHtml(i.canal || "?")}${i.canal_verificado ? ' <span class="badge badge-muted">verificado</span>' : ""}</td>`
      + `<td>${i.views_num !== null && i.views_num !== undefined ? escapeHtml(formatViews(i.views_num)) : "?"}</td><td>${escapeHtml(i.quando || "?")}</td>`
      + `<td>${i.razao_media === null || i.razao_media === undefined ? "—" : (Number(i.razao_media) < 0.01 ? "<0,01×" : `${Number(i.razao_media).toLocaleString("pt-BR")}×`)}</td><td>${escapeHtml(motivoRec(i))}</td></tr>`;
  }).join("");
  const escopo = cfg.escopo === "global" ? "todos os vídeos de origem juntos" : "cada vídeo de origem separado";
  return `<div class="rec-report"><h3>Triagem das recomendações</h3>`
    + `<div class="hint" style="margin-bottom:6px">Vídeo postado há até ${escapeHtml(cfg.meses_max ?? "?")} mês(es) · canal não verificado · views ≥ ${escapeHtml(cfg.fator ?? 1)} × ${ref} (${escopo}) · ${rel.canais_analisados ?? 0} canal(is) analisado(s)</div>`
    + grupos
    + (linhas ? `<details><summary>Decisão vídeo a vídeo (${itens.length})</summary><div class="table-wrap"><table class="rec-tabela"><thead><tr><th>Vídeo</th><th>Canal</th><th>Views</th><th>Postado</th><th>× ${ref}</th><th>Situação</th></tr></thead><tbody>${linhas}</tbody></table></div></details>` : "")
    + `</div>`;
}

// prompt "canais achados -> subnichos e termos" (a resposta da IA entra no passo 2)
let promptCanais = { buscaId: null, texto: "" };

function renderBarraPromptCanais(resultado) {
  const id = resultado?.busca_id;
  if (!id) return "";
  const aberto = promptCanais.buscaId === id && promptCanais.texto;
  return `<div class="prompt-canais"><div><button type="button" id="btn-prompt-canais" data-busca="${escapeHtml(id)}">Gerar prompt a partir destes canais</button>`
    + `<span class="hint">A IA descobre o nicho deles e devolve termos para achar mais canais parecidos. Cole a resposta no passo 2 (barra lateral).</span></div>`
    + `<div id="prompt-canais-wrap" style="display:${aberto ? "block" : "none"}"><div class="prompt-box" id="prompt-canais-text">${escapeHtml(aberto ? promptCanais.texto : "")}</div>`
    + `<button type="button" id="btn-copiar-prompt-canais">Copiar prompt</button></div></div>`;
}

document.addEventListener("click", async (ev) => {
  const alvo = ev.target && ev.target.closest ? ev.target : null;
  if (!alvo) return;
  const gerar = alvo.closest("#btn-prompt-canais");
  if (gerar) {
    const buscaId = Number(gerar.dataset.busca);
    try {
      const data = await fetchJson("/api/gerar-prompt-canais", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ busca_id: buscaId }),
      });
      if (!data.ok) return alert(data.erro || "Não foi possível gerar o prompt.");
      promptCanais = { buscaId, texto: data.prompt };
      el("prompt-canais-text").textContent = data.prompt;
      el("prompt-canais-wrap").style.display = "block";
    } catch (e) { alert(`Erro de comunicação: ${e.message}`); }
    return;
  }
  const copiar = alvo.closest("#btn-copiar-prompt-canais");
  if (copiar) {
    try { await navigator.clipboard.writeText(el("prompt-canais-text").textContent); } catch (_) {}
    const original = copiar.textContent;
    copiar.textContent = "Copiado!"; setTimeout(() => (copiar.textContent = original), 1200);
  }
});
