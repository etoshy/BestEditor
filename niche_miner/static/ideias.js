// Aba "Ideias virais": radar -> IA (decompor) -> IA (ideias) -> validação -> ranking/decisão.
// Depende de app.js (carregado antes): fetchJson, escapeHtml, formatViews.
(function () {
  const $ = (id) => document.getElementById(id);
  const h = (s) => escapeHtml(s);
  const CRITERIOS = ["amplitude", "demanda", "concorrencia", "repetibilidade", "producao"];
  const ROTULOS = { amplitude: "Amplitude", demanda: "Demanda", concorrencia: "Pouca concorr.", repetibilidade: "Repetibilidade", producao: "Produção" };
  const EDITAVEIS = ["amplitude", "repetibilidade", "producao"];
  const SETA = { subindo: "↑", caindo: "↓", estavel: "→" };

  let META = null;        // mercados, modos, pesos e limiares padrão
  let P = null;           // pesquisa aberta (estado vindo do servidor)
  let valSel = null;      // ids de ideias marcadas para validar (null = todas)
  let timerSalvar = null;
  let timerSel = null;
  let iniciado = false;

  // ---------- utilidades ----------
  async function api(url, method = "GET", corpo) {
    const opts = { method, headers: {} };
    if (corpo !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(corpo); }
    const j = await fetchJson(url, opts);
    if (!j.ok) throw new Error(j.erro || "Erro inesperado.");
    return j;
  }
  const n1 = (v) => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v))) ? "—" : Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 1 });
  const linhas = (txt) => String(txt || "").split("\n").map((s) => s.trim()).filter(Boolean);
  const nomeMercado = (cod) => ((META && META.mercados.find((m) => m.codigo === cod)) || {}).nome || cod || "?";

  function addLog(alvo, texto) {
    const div = document.createElement("div");
    div.className = "line";
    div.textContent = texto;
    alvo.appendChild(div);
    alvo.scrollTop = alvo.scrollHeight;
  }

  // ---------- navegação entre abas (o rail lateral é só da aba Minerar) ----------
  document.querySelectorAll(".topnav-btn").forEach((b) => b.addEventListener("click", () => {
    document.body.dataset.view = b.dataset.view;
    if (b.dataset.view === "ideias") iniciar();
  }));

  async function iniciar() {
    if (iniciado) return;
    iniciado = true;
    try {
      META = await api("/api/ideias/mercados");
      preencherSelects();
      montarIAs();
      await listar();
    } catch (e) { iniciado = false; alert(`Não foi possível iniciar a aba: ${e.message}`); }
  }

  function preencherSelects() {
    $("id-mercado").innerHTML = META.mercados.map((m) => `<option value="${h(m.codigo)}">${h(m.nome)} — ${h(m.idioma)}</option>`).join("");
    $("id-modo").innerHTML = META.modos.map((m, i) => `<option value="${h(m.codigo)}"${m.codigo === "ambos" ? " selected" : ""}>${h(m.nome)}</option>`).join("");
    $("id-d-limiares").innerHTML = [
      ["corte_alerta", "Alerta a partir de (vídeos)"], ["corte_final", "Corte aos (vídeos)"],
      ["impressoes_baixas", "Impressões baixas (<)"], ["ctr_baixo", "CTR baixo (<, %)"], ["retencao_baixa", "Retenção baixa (<, %)"],
    ].map(([k, r]) => `<div><label>${r}</label><input type="number" data-limiar="${k}" min="0" step="any" value="${h(META.limiares_padrao[k])}"></div>`).join("");
  }

  // ---------- lista de pesquisas ----------
  async function listar(selecionar) {
    const j = await api("/api/ideias/pesquisas");
    const sel = $("id-sessoes");
    sel.innerHTML = '<option value="">— escolha uma pesquisa —</option>' + j.pesquisas.map((p) =>
      `<option value="${p.id}">#${p.id} · ${h(p.tema)} · ${p.n_ideias} ideia(s)</option>`).join("");
    if (selecionar) sel.value = String(selecionar);
    if (!P) mostrarSetup();
  }

  function mostrarSetup() {
    P = null;
    $("id-setup").style.display = "";
    $("id-fluxo").style.display = "none";
    $("id-excluir").disabled = true;
    $("id-sessoes").value = "";
    $("id-mercado").value = "BR";
  }

  async function abrir(id) {
    const j = await api(`/api/ideias/pesquisas/${id}`);
    P = j.pesquisa;
    valSel = null;
    $("id-setup").style.display = "none";
    $("id-fluxo").style.display = "";
    $("id-excluir").disabled = false;
    $("id-sessoes").value = String(P.id);
    $("id-termos").value = (P.termos || []).join("\n");
    $("id-refs").value = (P.refs_extra || []).join("\n");
    ["id-console-radar", "id-console-val"].forEach((c) => { $(c).innerHTML = ""; });
    document.querySelectorAll("#id-mercados-alvo input").forEach((i) => { i.checked = i.value === P.mercado; });
    ["id-exp", "id-dec", "id-ide"].forEach((p) => { $(`${p}-texto`).value = ""; $(`${p}-fb`).innerHTML = ""; $(`${p}-prompt-wrap`).style.display = "none"; });
    renderTudo();
  }

  async function recarregar() {
    if (!P) return;
    const j = await api(`/api/ideias/pesquisas/${P.id}`);
    P = j.pesquisa;
    renderTudo();
  }

  $("id-sessoes").addEventListener("change", (e) => { if (e.target.value) abrir(e.target.value); else mostrarSetup(); });
  $("id-nova").addEventListener("click", () => { mostrarSetup(); $("id-tema").focus(); });
  $("id-criar").addEventListener("click", async () => {
    const tema = $("id-tema").value.trim();
    if (!tema) { $("id-tema").focus(); return; }
    try {
      const j = await api("/api/ideias/pesquisas", "POST", { tema, mercado: $("id-mercado").value, termos: linhas($("id-termos-ini").value) });
      $("id-tema").value = ""; $("id-termos-ini").value = "";
      await listar(j.pesquisa.id);
      await abrir(j.pesquisa.id);
    } catch (e) { alert(e.message); }
  });
  $("id-excluir").addEventListener("click", async () => {
    if (!P || !confirm(`Excluir a pesquisa "${P.tema}" e todas as suas ideias?`)) return;
    try { await api(`/api/ideias/pesquisas/${P.id}`, "DELETE"); P = null; await listar(); } catch (e) { alert(e.message); }
  });

  // ---------- salvar configuração editável ----------
  function agendarSalvar() { clearTimeout(timerSalvar); timerSalvar = setTimeout(salvarConfig, 500); }
  async function salvarConfig() {
    clearTimeout(timerSalvar);
    if (!P) return;
    try { P = (await api(`/api/ideias/pesquisas/${P.id}`, "PATCH", { termos: linhas($("id-termos").value), refs_extra: linhas($("id-refs").value) })).pesquisa; } catch (_) { /* tenta de novo na próxima ação */ }
  }
  $("id-termos").addEventListener("input", agendarSalvar);
  $("id-refs").addEventListener("input", agendarSalvar);

  $("id-usar-minerar").addEventListener("click", () => {
    const lista = (typeof termosValidados !== "undefined" && Array.isArray(termosValidados)) ? termosValidados : [];
    if (!lista.length) { $("id-termos-info").textContent = "A aba Minerar ainda não tem termos validados (passo 2 da barra lateral)."; return; }
    $("id-termos").value = lista.join("\n");
    $("id-termos-info").textContent = `${lista.length} termo(s) copiados da aba Minerar.`;
    agendarSalvar();
  });

  // ---------- blocos de IA (prompt -> copiar -> colar JSON -> validar) ----------
  function htmlIA(p, rotulo) {
    return `<div class="id-ia">
      <div><button type="button" id="${p}-gerar">${rotulo}</button></div>
      <div id="${p}-prompt-wrap" style="display:none">
        <label>Prompt (copie e cole numa IA de chat: ChatGPT, Gemini, Claude...)</label>
        <div class="prompt-box" id="${p}-prompt"></div>
        <button type="button" id="${p}-copiar">Copiar prompt</button>
      </div>
      <div><label for="${p}-texto">Cole aqui o JSON que a IA devolveu, exatamente como veio</label>
        <textarea id="${p}-texto" class="mono" rows="6" placeholder="{...}"></textarea></div>
      <div><button type="button" id="${p}-validar">Validar e importar</button></div>
      <div id="${p}-fb"></div>
    </div>`;
  }

  function ligarIA(p, cfg) {
    $(`${p}-gerar`).addEventListener("click", async () => {
      if (!P) return;
      await salvarConfig();
      try {
        const j = await api(`/api/ideias/pesquisas/${P.id}/prompt/${cfg.tipo}`, "POST", cfg.corpo());
        $(`${p}-prompt`).textContent = j.prompt;
        $(`${p}-prompt-wrap`).style.display = "block";
        $(`${p}-fb`).innerHTML = "";
      } catch (e) { $(`${p}-fb`).innerHTML = `<div class="error-msg">${h(e.message)}</div>`; }
    });
    $(`${p}-copiar`).addEventListener("click", async () => {
      try { await navigator.clipboard.writeText($(`${p}-prompt`).textContent); } catch (_) { /* clipboard indisponível */ }
      const b = $(`${p}-copiar`), o = b.textContent;
      b.textContent = "Copiado!"; setTimeout(() => { b.textContent = o; }, 1200);
    });
    $(`${p}-validar`).addEventListener("click", async () => {
      if (!P) return;
      const texto = $(`${p}-texto`).value.trim();
      if (!texto) { $(`${p}-fb`).innerHTML = '<div class="error-msg">Cole o JSON devolvido pela IA.</div>'; return; }
      try {
        const j = await api(`/api/ideias/pesquisas/${P.id}/colar/${cfg.tipo}`, "POST", { texto });
        P = j.pesquisa;
        $(`${p}-fb`).innerHTML = `<div class="ok-msg">${h(cfg.resumo(j.resumo))}</div>`;
        renderTudo();
      } catch (e) { $(`${p}-fb`).innerHTML = `<div class="error-msg">${h(e.message)}</div>`; }
    });
  }

  function montarIAs() {
    $("id-exp-ia").innerHTML = htmlIA("id-exp", "Gerar prompt de expansão");
    $("id-dec-ia").innerHTML = htmlIA("id-dec", "Gerar prompt de decomposição");
    $("id-ide-ia").innerHTML = htmlIA("id-ide", "Gerar prompt de ideias");
    $("id-mercados-alvo").innerHTML = META.mercados.map((m) =>
      `<label class="id-chip-check"><input type="checkbox" value="${h(m.codigo)}"> ${h(m.nome)}</label>`).join("");
    ligarIA("id-exp", { tipo: "expandir", corpo: () => ({ foco: $("id-foco").value.trim(), n: Number($("id-exp-n").value) || 10 }),
      resumo: (r) => `${r.termos} termo(s) para validar importados.` });
    ligarIA("id-dec", { tipo: "decompor", corpo: () => ({ video_ids: P.radar_selecao || [], refs_extra: linhas($("id-refs").value) }),
      resumo: (r) => `${r.videos} vídeo(s) e ${r.padroes} padrão(ões) importados.` });
    ligarIA("id-ide", { tipo: "ideias",
      corpo: () => ({ n: Number($("id-n-ideias").value) || 10, modo: $("id-modo").value,
        mercados_alvo: [...document.querySelectorAll("#id-mercados-alvo input:checked")].map((i) => i.value) }),
      resumo: (r) => `${r.lidas} ideia(s) lida(s), ${r.novas} nova(s); ${r.total} no total (veja o ranking na etapa 5).` });
  }

  // ---------- jobs (radar / validação) ----------
  function acompanhar(jobId, consoleEl) {
    return new Promise((resolve) => {
      let cursor = 0;
      const t = setInterval(async () => {
        try {
          const j = await fetchJson(`/api/logs/${jobId}?cursor=${cursor}`);
          if (!j.ok) return;
          cursor = j.cursor;
          (j.logs || []).forEach((l) => addLog(consoleEl, l));
          if (j.status === "concluido" || j.status === "erro") { clearInterval(t); resolve(j.status); }
        } catch (e) { addLog(consoleEl, `[poll erro] ${e.message}`); }
      }, 1000);
    });
  }

  async function rodarJob(rota, corpo, consoleEl, botao) {
    consoleEl.innerHTML = "";
    botao.disabled = true;
    try {
      const j = await api(rota, "POST", corpo);
      await acompanhar(j.job_id, consoleEl);
      await recarregar();
    } catch (e) { addLog(consoleEl, `ERRO: ${e.message}`); }
    botao.disabled = false;
  }

  $("id-rodar-radar").addEventListener("click", async () => {
    if (!P) return;
    const termos = linhas($("id-termos").value);
    if (!termos.length) { alert("Informe pelo menos um termo de busca."); return; }
    await salvarConfig();
    await rodarJob(`/api/ideias/pesquisas/${P.id}/radar`, {
      termos, data_periodo: $("id-periodo").value, max_videos: Number($("id-max-videos").value),
      duracao_min: Number($("id-dur-min").value), duracao_max: Number($("id-dur-max").value),
      top_canais: Number($("id-top-canais").value), headless: $("id-headless").checked,
    }, $("id-console-radar"), $("id-rodar-radar"));
  });

  $("id-validar").addEventListener("click", async () => {
    if (!P) return;
    const ids = [...document.querySelectorAll(".id-val-ck:checked")].map((c) => c.value);
    if (!ids.length) { alert("Marque pelo menos uma ideia."); return; }
    await rodarJob(`/api/ideias/pesquisas/${P.id}/validar`, {
      ideia_ids: ids, sugestoes: $("id-v-sug").checked, alfabeto: $("id-v-alfa").checked, serp: $("id-v-serp").checked,
      trends: $("id-v-trends").checked, yt: $("id-v-yt").checked, headless: $("id-v-headless").checked,
      trends_fonte: $("id-v-trends-fonte").value, trends_periodo: $("id-v-trends-periodo").value, data_periodo: $("id-v-periodo").value,
    }, $("id-console-val"), $("id-validar"));
  });

  // ---------- renderização ----------
  function renderTudo() {
    if (!P) return;
    const radar = P.radar;
    const op = $("id-sessoes").selectedOptions[0];   // mantém a contagem do seletor em dia sem recarregar a lista
    if (op && op.value === String(P.id)) op.textContent = `#${P.id} · ${P.tema} · ${(P.ideias || []).length} ideia(s)`;
    $("id-resumo").innerHTML = `<strong>${h(P.tema)}</strong> · mercado ${h(nomeMercado(P.mercado))} · `
      + `${radar ? (radar.videos || []).length : 0} vídeos no radar · ${(P.ideias || []).filter((i) => !i.descartada).length} ideia(s)`;
    renderRadar(); renderSelInfo(); renderExpansao(); renderDecomp(); renderIdeias(); renderValLista(); renderPesos(); renderRanking();
  }

  function renderRadar() {
    const r = P.radar, alvo = $("id-radar-res");
    if (!r || !(r.videos || []).length) { alvo.innerHTML = '<div class="empty-state">o resultado do radar aparece aqui</div>'; return; }
    const sel = new Set(P.radar_selecao || []);
    const limite = 150;
    const trs = r.videos.slice(0, limite).map((v) => {
      const razao = v.razao_views_inscritos;
      const canal = v.canal_url ? `<a href="${h(v.canal_url)}" target="_blank" rel="noopener">${h(v.canal || "")}</a>` : h(v.canal || "");
      const subs = v.inscritos_num ? `<div class="channel-term">${h(formatViews(v.inscritos_num))} inscritos</div>` : (v.canal_verificado ? '<div class="channel-term">verificado</div>' : "");
      return `<tr><td><input type="checkbox" class="id-sel" data-vid="${h(v.video_id)}"${sel.has(v.video_id) ? " checked" : ""}></td>`
        + `<td class="canal"><a href="${h(v.url)}" target="_blank" rel="noopener">${h(v.titulo)}</a><div class="channel-term">${h((v.termos || [v.termo_busca]).join(", "))}</div></td>`
        + `<td>${canal}${subs}</td><td>${h(formatViews(v.views_num))}</td><td>${h(v.quando || "?")}</td>`
        + `<td>${v.views_dia != null ? h(formatViews(Math.round(v.views_dia))) : "?"}</td>`
        + `<td>${razao != null ? `${h(n1(razao))}x${razao >= 1 ? ' <span class="badge badge-green">outlier</span>' : ""}` : "?"}</td></tr>`;
    }).join("");
    const resumo = (r.resumo || []).map((x) => `<span class="tag">${h(x.termo)}: ${x.n_videos} vídeos · mediana ${h(formatViews(x.mediana_views))} · ${x.outliers} outlier(s)</span>`).join("");
    const falhas = (r.falhas || []).length ? `<div class="warning-box"><strong>${r.falhas.length} termo(s) com falha isolada.</strong> ${h(r.falhas.slice(0, 2).join(" | "))}</div>` : "";
    const aviso = r.videos.length > limite ? `<div class="hint">mostrando os ${limite} primeiros de ${r.videos.length}, ordenados por razão views/inscritos e views por dia.</div>` : "";
    alvo.innerHTML = `${falhas}<div class="tags">${resumo}</div>${aviso}
      <div class="table-wrap"><table class="candidate-table" style="min-width:0"><thead><tr><th></th><th>Vídeo</th><th>Canal</th><th>Views</th><th>Idade</th><th>Views/dia</th><th>× inscritos</th></tr></thead><tbody>${trs}</tbody></table></div>
      <div class="hint">Marque os vídeos que devem ir para a IA (etapa 2). "Outlier" = o vídeo tem mais views do que o canal tem de inscritos; só existe para canais cujos inscritos foram lidos.</div>`;
  }

  $("id-radar-res").addEventListener("change", (ev) => {
    if (!ev.target.classList || !ev.target.classList.contains("id-sel") || !P) return;
    P.radar_selecao = [...document.querySelectorAll(".id-sel:checked")].map((c) => c.dataset.vid);
    renderSelInfo();
    clearTimeout(timerSel);
    timerSel = setTimeout(() => api(`/api/ideias/pesquisas/${P.id}`, "PATCH", { radar_selecao: P.radar_selecao }).catch(() => {}), 500);
  });

  function renderSelInfo() {
    const n = (P.radar_selecao || []).length;
    $("id-sel-info").textContent = P.radar
      ? `${n} vídeo(s) marcado(s) no radar${n > 30 ? " (só os 30 primeiros entram no prompt)" : ""}.`
      : "Sem radar ainda: use os títulos de referência abaixo ou rode o radar na etapa 1.";
  }

  function renderExpansao() {
    const e = P.expansao, alvo = $("id-exp-res");
    if (!e) { alvo.innerHTML = ""; return; }
    const chips = (e.termos_para_validar || []).map((t) => `<button type="button" class="tag id-add-termo" data-termo="${h(t)}" title="adicionar aos termos do radar">+ ${h(t)}</button>`).join("");
    const publicos = (e.publicos_adjacentes || []).map((p) => `<li><strong>${h(p.publico)}</strong>${p.por_que ? ` — ${h(p.por_que)}` : ""}</li>`).join("");
    const buscas = (e.problemas_e_buscas || []).map((b) => `<li><strong>${h(b.busca)}</strong>${b.motivo ? ` — ${h(b.motivo)}` : ""}</li>`).join("");
    alvo.innerHTML = `<div class="hint">Clique num termo para adicioná-lo à lista do radar (etapa 1).</div><div class="tags">${chips}</div>`
      + (publicos ? `<details class="id-sub"><summary>Públicos adjacentes (${(e.publicos_adjacentes || []).length})</summary><ul class="video-list">${publicos}</ul></details>` : "")
      + (buscas ? `<details class="id-sub"><summary>Problemas e buscas (${(e.problemas_e_buscas || []).length})</summary><ul class="video-list">${buscas}</ul></details>` : "");
  }

  $("id-exp-res").addEventListener("click", (ev) => {
    const b = ev.target.closest ? ev.target.closest(".id-add-termo") : null;
    if (!b) return;
    const atuais = linhas($("id-termos").value);
    if (!atuais.includes(b.dataset.termo)) { atuais.push(b.dataset.termo); $("id-termos").value = atuais.join("\n"); agendarSalvar(); }
    b.disabled = true;
  });

  function renderDecomp() {
    const d = P.decomposicao, alvo = $("id-dec-res");
    if (!d) { alvo.innerHTML = ""; return; }
    const base = Object.fromEntries((P.decomposicao_base || []).map((b) => [b.indice, b]));
    const lista = (a) => (a || []).map((x) => h(x)).join(", ") || "—";
    const padroes = (d.padroes || []).map((p) => `<div class="id-padrao"><strong>${h(p.nome)}</strong>
      <div class="muted-small">emoção: ${h(p.emocao || "—")} · estrutura: ${h(p.estrutura || "—")}</div>
      <div class="muted-small">fixo: ${lista(p.elementos_fixos)}</div><div class="muted-small">variável: ${lista(p.elementos_variaveis)}</div></div>`).join("");
    const trs = (d.videos || []).map((v) => {
      const b = base[v.indice] || {};
      const titulo = b.url ? `<a href="${h(b.url)}" target="_blank" rel="noopener">${h(b.titulo)}</a>` : h(b.titulo || `#${v.indice}`);
      return `<tr><td>${v.indice}</td><td class="canal">${titulo}</td><td>${h(v.emocao)}</td><td>${h(v.estrutura_titulo)}</td>`
        + `<td>${h([v.personagem, v.cenario].filter(Boolean).join(" · "))}</td><td>${lista(v.publicos_adjacentes)}</td><td>${h(n1(v.amplitude))}</td></tr>`;
    }).join("");
    alvo.innerHTML = (padroes ? `<div class="id-padroes">${padroes}</div>` : "")
      + (trs ? `<div class="table-wrap"><table class="candidate-table" style="min-width:0"><thead><tr><th>#</th><th>Vídeo</th><th>Emoção</th><th>Estrutura do título</th><th>Personagem · cenário</th><th>Públicos adjacentes</th><th>Amplitude</th></tr></thead><tbody>${trs}</tbody></table></div>` : "");
  }

  function renderIdeias() {
    const n = (P.ideias || []).length;
    $("id-ide-res").innerHTML = n ? `<div class="muted-small">${n} ideia(s) nesta pesquisa. Veja e ajuste o ranking na etapa 5.</div>` : "";
  }

  function renderValLista() {
    const ativas = (P.ideias || []).filter((i) => !i.descartada);
    const alvo = $("id-val-lista");
    $("id-validar").disabled = !ativas.length;
    if (!ativas.length) { alvo.innerHTML = '<div class="empty-state">importe ideias na etapa 3 para validar</div>'; return; }
    const marcadas = valSel || new Set(ativas.map((i) => i.id));
    alvo.innerHTML = `<div class="id-linha"><button type="button" id="id-val-todas">Marcar todas</button><button type="button" id="id-val-nenhuma">Desmarcar</button></div>`
      + ativas.map((i) => `<label class="id-val-item"><input type="checkbox" class="id-val-ck" value="${h(i.id)}"${marcadas.has(i.id) ? " checked" : ""}>
        <span><strong>${h(i.titulo_amplo)}</strong> <span class="badge badge-muted">${h(i.mercado)}</span>
        <span class="channel-term">${(i.termos_validacao || []).length ? h(i.termos_validacao.join(" · ")) : "sem termos de validação (edite no ranking)"}</span></span></label>`).join("");
  }

  $("id-val-lista").addEventListener("click", (ev) => {
    if (ev.target.id === "id-val-todas" || ev.target.id === "id-val-nenhuma") {
      document.querySelectorAll(".id-val-ck").forEach((c) => { c.checked = ev.target.id === "id-val-todas"; });
      valSel = new Set([...document.querySelectorAll(".id-val-ck:checked")].map((c) => c.value));
    }
  });
  $("id-val-lista").addEventListener("change", (ev) => {
    if (ev.target.classList && ev.target.classList.contains("id-val-ck")) valSel = new Set([...document.querySelectorAll(".id-val-ck:checked")].map((c) => c.value));
  });

  function renderPesos() {
    const pesos = P.pesos || META.pesos_padrao;
    $("id-pesos").innerHTML = `<span class="muted-small">Pesos:</span>` + CRITERIOS.map((c) =>
      `<label class="id-peso">${ROTULOS[c]} <input type="number" data-peso="${c}" min="0" max="100" step="1" value="${h(pesos[c])}"></label>`).join("")
      + `<button type="button" id="id-pesos-reset">Restaurar padrão</button>`;
  }

  $("id-pesos").addEventListener("change", async (ev) => {
    if (!ev.target.dataset || !ev.target.dataset.peso || !P) return;
    const pesos = {};
    document.querySelectorAll("#id-pesos input[data-peso]").forEach((i) => { pesos[i.dataset.peso] = Number(i.value); });
    try { P = (await api(`/api/ideias/pesquisas/${P.id}`, "PATCH", { pesos })).pesquisa; renderRanking(); renderPesos(); } catch (e) { alert(e.message); }
  });
  $("id-pesos").addEventListener("click", async (ev) => {
    if (ev.target.id !== "id-pesos-reset" || !P) return;
    try { P = (await api(`/api/ideias/pesquisas/${P.id}`, "PATCH", { pesos: META.pesos_padrao })).pesquisa; renderPesos(); renderRanking(); } catch (e) { alert(e.message); }
  });

  function chipsSinais(s) {
    if (!s || !Object.keys(s).length) return '<span class="muted-small">ainda não validada</span>';
    const c = [];
    if (s.sugestoes_google != null) c.push(`<span class="badge badge-muted" title="Sugestões do autocomplete do Google (média por termo)">Google ${n1(s.sugestoes_google)}</span>`);
    if (s.sugestoes_youtube != null) c.push(`<span class="badge badge-muted" title="Sugestões do autocomplete do YouTube (média por termo)">YouTube ${n1(s.sugestoes_youtube)}</span>`);
    if (s.trends_nivel != null) {
      const t = `Trends ${n1(s.trends_nivel)} ${SETA[s.trends_tendencia] || ""} ${h(s.trends_perfil || "")}`;
      c.push(s.trends_url ? `<a class="badge badge-muted" href="${h(s.trends_url)}" target="_blank" rel="noopener" title="Abrir no Google Trends">${t}</a>` : `<span class="badge badge-muted">${t}</span>`);
    } else if (s.trends_url) {
      c.push(`<a class="badge badge-muted" href="${h(s.trends_url)}" target="_blank" rel="noopener" title="Sem dados do Trends: abrir e conferir manualmente">Trends ↗</a>`);
    }
    if (s.yt_mediana_views_dia != null) c.push(`<span class="badge badge-muted" title="Mediana de views por dia dos vídeos do período">${n1(s.yt_mediana_views_dia)} views/dia</span>`);
    if (s.yt_concentracao_top3 != null) c.push(`<span class="badge badge-muted" title="Parcela dos resultados que pertence aos 3 canais que mais aparecem">top 3 canais: ${n1(s.yt_concentracao_top3 * 100)}%</span>`);
    if (s.serp_perguntas != null) c.push(`<span class="badge badge-muted" title="Perguntas em 'As pessoas também perguntam'">${s.serp_perguntas} perguntas</span>`);
    if (s.trends_perfil === "sazonal") c.push('<span class="badge badge-red" title="Pico concentrado em poucas semanas">sazonal</span>');
    const det = [["Perguntas do Google (ganchos)", s.perguntas_exemplo], ["Buscas relacionadas", s.relacionadas_exemplo], ["Autocomplete", s.sugestoes_exemplo]]
      .filter(([, l]) => l && l.length).map(([r, l]) => `<div class="muted-small"><strong>${r}:</strong> ${l.map(h).join(" · ")}</div>`).join("");
    return c.join(" ") + (det ? `<details class="id-sub"><summary>ver exemplos</summary>${det}</details>` : "");
  }

  function celulaCriterio(i, c) {
    const v = (i.criterios || {})[c];
    if (EDITAVEIS.includes(c)) {
      return `<input type="number" class="id-nota" data-id="${h(i.id)}" data-campo="${c}" min="0" max="5" step="0.5" value="${v == null ? "" : h(v)}" placeholder="?">`;
    }
    return `<span title="Calculado a partir da validação (relativo às demais ideias do mesmo mercado)">${v == null ? "?" : n1(v)}</span>`;
  }

  function linhaIdeia(i) {
    const badges = `<span class="badge badge-muted">${h(i.mercado)}</span> `
      + `<span class="badge ${i.tipo_brecha === "dupla" ? "badge-green" : "badge-muted"}">brecha ${h(i.tipo_brecha)}</span>`;
    const outros = [i.titulo_sub ? `sub: ${h(i.titulo_sub)}` : "", i.titulo_micro ? `micro: ${h(i.titulo_micro)}` : ""].filter(Boolean).map((t) => `<div class="muted-small">${t}</div>`).join("");
    const meta = [i.emocao && `emoção: ${h(i.emocao)}`, i.estrutura && `estrutura: ${h(i.estrutura)}`, i.personagem && `personagem: ${h(i.personagem)}`, i.cenario && `cenário: ${h(i.cenario)}`]
      .filter(Boolean).join(" · ");
    return `<tr>
      <td class="opp-rank">${i.rank || "—"}</td>
      <td class="canal"><strong>${h(i.titulo_amplo)}</strong> ${badges}${outros}
        ${meta ? `<div class="muted-small">${meta}</div>` : ""}${i.observacao ? `<div class="muted-small">${h(i.observacao)}</div>` : ""}
        <label class="id-termos-lbl">termos de validação (separe por vírgula)
          <input type="text" class="id-ideia-termos" data-id="${h(i.id)}" value="${h((i.termos_validacao || []).join(", "))}"></label></td>
      <td><div class="id-score">${i.score == null ? "—" : n1(i.score)}</div><div class="muted-small">confiança ${Math.round((i.confianca || 0) * 100)}%</div></td>
      ${CRITERIOS.map((c) => `<td>${celulaCriterio(i, c)}</td>`).join("")}
      <td class="id-sinais">${chipsSinais(i.sinais)}</td>
      <td class="id-acoes"><button type="button" class="id-fav" data-id="${h(i.id)}" title="Favoritar">${i.favorita ? "★" : "☆"}</button>
        <button type="button" class="id-desc danger" data-id="${h(i.id)}" title="Descartar">✕</button></td></tr>`;
  }

  function renderRanking() {
    const alvo = $("id-ranking"), csv = $("id-csv");
    const todas = P.ideias || [];
    csv.style.display = todas.length ? "" : "none";
    csv.href = `/api/ideias/pesquisas/${P.id}/ideias.csv`;
    if (!todas.length) { alvo.innerHTML = '<div class="empty-state">o ranking aparece aqui depois de importar ideias (etapa 3)</div>'; return; }
    const ativas = todas.filter((i) => !i.descartada).sort((a, b) => (a.rank || 999) - (b.rank || 999));
    const descartadas = todas.filter((i) => i.descartada);
    const cab = `<thead><tr><th>#</th><th>Ideia</th><th>Score</th>${CRITERIOS.map((c) => `<th>${ROTULOS[c]}</th>`).join("")}<th>Sinais</th><th></th></tr></thead>`;
    alvo.innerHTML = `<div class="table-wrap"><table class="candidate-table id-rank" style="min-width:0">${cab}<tbody>${ativas.map(linhaIdeia).join("")}</tbody></table></div>`
      + (descartadas.length ? `<details class="id-sub"><summary>${descartadas.length} descartada(s)</summary><ul class="video-list">${descartadas.map((i) =>
        `<li>${h(i.titulo_amplo)} <button type="button" class="id-restaurar" data-id="${h(i.id)}">restaurar</button></li>`).join("")}</ul></details>` : "");
  }

  async function editarIdeia(id, dados) {
    try { P = (await api(`/api/ideias/pesquisas/${P.id}/ideias/${id}`, "PATCH", dados)).pesquisa; renderTudo(); } catch (e) { alert(e.message); }
  }

  $("id-ranking").addEventListener("change", (ev) => {
    const t = ev.target;
    if (!t.classList || !P) return;
    if (t.classList.contains("id-nota")) editarIdeia(t.dataset.id, { [t.dataset.campo]: t.value === "" ? null : Number(t.value) });
    if (t.classList.contains("id-ideia-termos")) editarIdeia(t.dataset.id, { termos_validacao: t.value.split(",").map((s) => s.trim()).filter(Boolean) });
  });
  $("id-ranking").addEventListener("click", (ev) => {
    const b = ev.target.closest ? ev.target.closest("button") : null;
    if (!b || !P || !b.dataset.id) return;
    const i = (P.ideias || []).find((x) => x.id === b.dataset.id);
    if (!i) return;
    if (b.classList.contains("id-fav")) editarIdeia(i.id, { favorita: !i.favorita });
    if (b.classList.contains("id-desc")) editarIdeia(i.id, { descartada: true });
    if (b.classList.contains("id-restaurar")) editarIdeia(i.id, { descartada: false });
  });

  // ---------- decisão de canal ----------
  $("id-decidir").addEventListener("click", async () => {
    const limiares = {};
    document.querySelectorAll("#id-d-limiares input[data-limiar]").forEach((i) => { limiares[i.dataset.limiar] = i.value; });
    try {
      const j = await api("/api/ideias/decidir-canal", "POST", {
        n_videos: $("id-d-n").value, impressoes: $("id-d-imp").value, ctr: $("id-d-ctr").value, retencao: $("id-d-ret").value, limiares,
      });
      const d = j.decisao;
      const cor = { escalar: "badge-green", descartar: "badge-red", alerta: "badge-red", continuar: "badge-muted" }[d.veredito] || "badge-muted";
      $("id-decisao").innerHTML = `<div class="id-veredito"><span class="badge ${cor}">${h(d.veredito)}</span> <strong>${h(d.titulo)}</strong>
        <p>${h(d.explicacao)}</p>${(d.diagnosticos || []).map((x) => `<div class="muted-small"><strong>${h(x.causa)}:</strong> ${h(x.acao)}</div>`).join("")}</div>`;
    } catch (e) { $("id-decisao").innerHTML = `<div class="error-msg">${h(e.message)}</div>`; }
  });
})();
