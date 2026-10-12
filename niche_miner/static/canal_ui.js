// Aba "Analisar canal": análise de um canal, painel, explorador de vídeos, IA externa e pontes para as outras abas.
// Depende de canal.js e metodo.js (fórmulas puras) e de app.js (escapeHtml).
(function () {
  const C = window.NicheCanal;
  const M = window.NicheMetodo;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => escapeHtml(s);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const fmt = (n, casas = 2) => (n === null || n === undefined || !Number.isFinite(Number(n))) ? "—" : Number(n).toLocaleString("pt-BR", { maximumFractionDigits: casas });
  const inteiro = (n) => (n === null || n === undefined || !Number.isFinite(Number(n))) ? "—" : new Intl.NumberFormat("pt-BR").format(Math.round(Number(n)));
  const link = (url) => (/^https?:\/\//.test(url || "") ? url : "#");
  const CHAVE_ULTIMA = "niche_miner_canal_ultima";

  let analise = null;       // análise aberta (dados + ia)
  let videosBase = [];      // vídeos da análise com o fator outlier
  let filtrados = [];       // o que a tabela mostra agora
  let rodando = false;
  let iniciado = false;

  async function api(url, opcoes) {
    const resp = await fetch(url, opcoes);
    let j = null;
    try { j = await resp.json(); } catch (_) { /* sem corpo JSON */ }
    if (!resp.ok || !j || j.ok === false) throw new Error((j && j.erro) || `erro ${resp.status}`);
    return j;
  }
  const post = (url, corpo) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo || {}) });

  function dataHora(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(iso || "");
    return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : (iso || "?");
  }
  function dataBr(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
  }
  const slug = (s) => C.semAcento(s).replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "canal";

  function baixar(nome, conteudo, tipo) {
    const url = URL.createObjectURL(new Blob([conteudo], { type: tipo }));
    const a = document.createElement("a");
    a.href = url;
    a.download = nome;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const hoje = () => new Date().toISOString().slice(0, 10);

  // ---------- análise (job) ----------
  function setStatus(txt) { $("cn-status").textContent = txt; }
  function addLog(txt) {
    const div = document.createElement("div");
    div.className = "line";
    div.textContent = txt;
    $("cn-log").appendChild(div);
    $("cn-log").scrollTop = $("cn-log").scrollHeight;
  }

  async function acompanhar(jobId) {
    let cursor = 0;
    const intervalo = window.CN_POLL_MS || 1000;
    for (;;) {
      const j = await api(`/api/logs/${jobId}?cursor=${cursor}`);
      (j.logs || []).forEach(addLog);
      cursor = j.cursor;
      if (j.status === "concluido") {
        const r = await api(`/api/resultado/${jobId}`);
        setStatus("concluído");
        await carregarLista(r.resultado.analise_id);
        return;
      }
      if (j.status === "erro") { setStatus("erro"); return; }      // a mensagem já veio no log ("ERRO: ...")
      await sleep(intervalo);
    }
  }

  async function analisar() {
    if (rodando) return;
    const url = $("cn-url").value.trim();
    if (!url) { setStatus("informe o link do canal"); return; }
    rodando = true;
    $("cn-analisar").disabled = true;
    $("cn-log").innerHTML = "";
    setStatus("rodando");
    try {
      const j = await post("/api/canal/analisar", {
        url, n_videos: parseInt($("cn-n").value, 10) || 100, headless: $("cn-headless").checked, mutar_audio: true,
      });
      await acompanhar(j.job_id);
    } catch (e) {
      addLog(`ERRO: ${e.message}`);
      setStatus("erro");
    } finally {
      rodando = false;
      $("cn-analisar").disabled = false;
    }
  }

  // ---------- lista de análises salvas ----------
  async function carregarLista(selecionar) {
    const j = await api("/api/canal/analises");
    const sel = $("cn-analises");
    sel.innerHTML = j.analises.length
      ? '<option value="">— escolha uma análise —</option>' + j.analises.map((a) =>
        `<option value="${a.id}">#${a.id} · ${esc(a.canal)} · ${esc(dataHora(a.criado_em))} · ${inteiro(a.amostra_n)} vídeos</option>`).join("")
      : '<option value="">nenhuma análise ainda</option>';
    // abre a que foi pedida, senão a última que você viu, senão a mais recente
    let alvo = Number(selecionar || localStorage.getItem(CHAVE_ULTIMA));
    if (!j.analises.some((a) => a.id === alvo)) alvo = j.analises.length ? j.analises[0].id : 0;
    if (alvo) {
      sel.value = String(alvo);
      await abrir(alvo);
    } else {
      fechar();
    }
  }

  function fechar() {
    analise = null;
    videosBase = [];
    $("cn-painel").style.display = "none";
    $("cn-excluir").disabled = true;
  }

  async function abrir(id) {
    try {
      const j = await api(`/api/canal/analises/${id}`);
      analise = j.analise;
      try { localStorage.setItem(CHAVE_ULTIMA, String(analise.id)); } catch (_) { /* sem storage */ }
      renderTudo();
    } catch (e) {
      fechar();
      addLog(`ERRO: ${e.message}`);
    }
  }

  async function excluir() {
    if (!analise || !confirm(`Excluir a análise #${analise.id} de "${analise.canal}"?`)) return;
    try {
      await api(`/api/canal/analises/${analise.id}`, { method: "DELETE" });
      try { localStorage.removeItem(CHAVE_ULTIMA); } catch (_) { /* sem storage */ }
      analise = null;
      await carregarLista();
    } catch (e) { addLog(`ERRO: ${e.message}`); }
  }

  // ---------- painel do canal ----------
  function limitesTracao() {
    const c = parseFloat(($("mp-cuidado") || {}).value), f = parseFloat(($("mp-forte") || {}).value);
    return { cuidado: Number.isFinite(c) ? c : M.LIMITES_TRACAO.cuidado, forte: Number.isFinite(f) ? f : M.LIMITES_TRACAO.forte };
  }
  function badgeSinal(sinal) {
    const cls = sinal.chave === "forte" ? "badge-green" : sinal.chave === "cuidado" ? "badge-red" : "badge-muted";
    return `<span class="badge ${cls}">${esc(sinal.rotulo)}</span>`;
  }

  function renderCab() {
    const d = analise.dados, m = d.metricas, c = d.canal;
    const avisos = [];
    if (m.n_videos && m.amostra_n < m.n_videos && !m.amostra_completa) avisos.push(`Amostra: os ${inteiro(m.amostra_n)} vídeos mais recentes de ${inteiro(m.n_videos)} do canal.`);
    if (m.amostra_com_views < 10) avisos.push("Poucos vídeos com views lidos: a mediana e os padrões de título são frágeis.");
    $("cn-cab").innerHTML = `<div><b><a href="${esc(link(c.url))}" target="_blank" rel="noopener">${esc(c.nome || c.url)}</a></b>`
      + `${c.pais ? ` · ${esc(c.pais)}` : ""}${c.idioma ? ` · ${esc(c.idioma)}` : ""}</div>`
      + `<div class="muted-small">Coletado em ${esc(dataHora(d.coletado_em))} · ${inteiro(m.amostra_n)} vídeos lidos (${inteiro(m.amostra_com_views)} com views)</div>`
      + avisos.map((a) => `<div class="mt-aviso">${esc(a)}</div>`).join("");
  }

  function card(rotulo, valor, sub, nd) {
    return `<div class="cn-card${nd ? " cn-card-nd" : ""}"><div class="cn-card-rot">${esc(rotulo)}</div><div class="cn-card-val">${valor}</div>${sub ? `<div class="cn-card-sub">${sub}</div>` : ""}</div>`;
  }

  function renderCards() {
    const m = analise.dados.metricas;
    const sinal = M.classificarTracao(m.tracao, limitesTracao());
    const cards = [
      card("Inscritos", inteiro(m.inscritos)),
      card("Views totais", inteiro(m.views_totais)),
      card("Vídeos publicados", inteiro(m.n_videos)),
      card("Views por vídeo (total ÷ vídeos)", inteiro(m.views_por_video)),
      card(`Mediana dos últimos ${m.n_mediana_usados || 10} vídeos`, inteiro(m.mediana_ultimos), m.mediana_views_amostra !== null ? `mediana da amostra toda: ${inteiro(m.mediana_views_amostra)}` : ""),
      card("Tração (mediana ÷ inscritos)", fmt(m.tracao, 3), m.tracao === null ? "" : badgeSinal(sinal)),
      card("Idade do canal", m.dias_de_vida === null ? "—" : `${inteiro(m.dias_de_vida)} dias`, m.meses_de_vida === null ? "" : `${fmt(m.meses_de_vida, 1)} meses`),
      card("Vídeos por mês (vida toda)", fmt(m.uploads_por_mes_vida, 1)),
      card("Vídeos nos últimos 30 dias", inteiro(m.videos_ultimos_30d), esc(m.frequencia_label || "")),
      card("Duração média", m.duracao_media_seg === null ? "—" : C.duracaoTexto(m.duracao_media_seg), m.duracao_mediana_seg === null ? "" : `mediana ${C.duracaoTexto(m.duracao_mediana_seg)}`),
      card("Título médio (caracteres)", fmt(m.titulo_medio_chars, 1)),
      card("Views médias por mês", inteiro(m.views_mensais_medias), "total ÷ meses de vida"),
      card("Shorts", "não coletado", "", true),
      card("Monetizado", "não coletado", "", true),
    ];
    $("cn-cards").innerHTML = cards.join("");
    $("cn-cards").querySelectorAll(".cn-card-nd").forEach((n) => { n.title = "O YouTube não mostra isso de forma confiável na página; o NextLEV usa base própria."; });
  }

  function itemVideo(v) {
    const idade = v.idade_dias === null || v.idade_dias === undefined ? "" : ` · há ${v.idade_dias} dia(s)`;
    return `<li><a href="${esc(link(v.url))}" target="_blank" rel="noopener">${esc(v.titulo)}</a><br><span class="muted-small">${inteiro(v.views)} views${idade}</span></li>`;
  }

  function renderPadroes() {
    const p = analise.dados.padroes;
    if (!p.padroes.length) {
      $("cn-padroes").innerHTML = '<div class="empty-state">nenhuma estrutura aparece em 3 ou mais vídeos (e fica de fora em outros 3)</div>';
    } else {
      $("cn-padroes").innerHTML = `<div class="table-wrap"><table class="candidate-table mt-tabela"><thead><tr><th>Estrutura do título</th><th>Vídeos com</th><th>Mediana com</th><th>Mediana sem</th><th>Com ÷ sem</th></tr></thead><tbody>`
        + p.padroes.map((x) => {
          const cls = x.razao === null ? "badge-muted" : x.razao >= 1.5 ? "badge-green" : x.razao <= 1 / 1.5 ? "badge-red" : "badge-muted";
          return `<tr><td class="quebra">${esc(x.rotulo)}</td><td class="num">${x.n_com} de ${x.n_com + x.n_sem}</td><td class="num">${inteiro(x.mediana_com)}</td><td class="num">${inteiro(x.mediana_sem)}</td>`
            + `<td><span class="badge ${cls}">${fmt(x.razao, 2)}×</span>${x.amostra_pequena ? ' <span class="badge badge-muted" title="Menos de 5 vídeos de um dos lados">poucos vídeos</span>' : ""}</td></tr>`;
        }).join("") + "</tbody></table></div>"
        + `<p class="hint">Compara ${p.n_videos_considerados} vídeos${p.idade_min_dias ? ` (só os com ${p.idade_min_dias} dias ou mais, para os recentes não distorcerem)` : ""}. É correlação em amostra pequena, não prova de que a estrutura causa as views. Verde: 1,5× ou mais; vermelho: 1,5× menos ou menos.</p>`;
    }
    $("cn-palavras").innerHTML = p.palavras_chave.length
      ? `<div class="cn-chips">${p.palavras_chave.map((k) => `<div class="cn-chip"><b>${esc(k.palavra)}</b> · ${k.titulos} títulos · mediana com ${inteiro(k.mediana_com)} / sem ${inteiro(k.mediana_sem)}${k.terminam_com ? ` · termina o título em ${k.terminam_com}` : ""}</div>`).join("")}</div>`
      : '<div class="empty-state">nenhuma palavra aparece em 3 ou mais títulos</div>';
  }

  function renderPainel() {
    const m = analise.dados.metricas;
    renderCab();
    renderCards();
    $("cn-melhores").innerHTML = m.melhores.length ? m.melhores.map(itemVideo).join("") : "<li>sem dados</li>";
    $("cn-piores").innerHTML = m.piores.length ? m.piores.map(itemVideo).join("") : "<li>sem vídeos com 14 dias ou mais</li>";
    renderPadroes();
  }

  // ---------- explorador de vídeos ----------
  function catPorIndice() {
    const mapa = {};
    const est = analise && analise.ia && analise.ia.categorias ? analise.ia.categorias.estatisticas || [] : [];
    est.forEach((c) => (c.indices || []).forEach((i) => { mapa[i] = c.nome; }));
    return mapa;
  }

  function preencherCategoriasFiltro() {
    const sel = $("cn-f-cat");
    const anterior = sel.value;
    const est = analise && analise.ia && analise.ia.categorias ? analise.ia.categorias.estatisticas || [] : [];
    sel.innerHTML = '<option value="">todas</option>' + est.map((c, i) => `<option value="${i}">${esc(c.nome)} (${c.n})</option>`).join("");
    if ([...sel.options].some((o) => o.value === anterior)) sel.value = anterior;
  }

  function lerContagem(id) {
    const txt = $(id).value.trim();
    if (!txt) return { valor: null, ruim: false };
    const v = M.parseContagem(txt);
    return { valor: v, ruim: v === null };
  }

  function lerFiltros() {
    const vmin = lerContagem("cn-f-vmin"), vmax = lerContagem("cn-f-vmax");
    const fator = parseFloat($("cn-f-fator").value);
    const est = analise && analise.ia && analise.ia.categorias ? analise.ia.categorias.estatisticas || [] : [];
    const cat = $("cn-f-cat").value;
    return {
      filtros: {
        texto: $("cn-f-texto").value, dias: $("cn-f-dias").value === "" ? null : Number($("cn-f-dias").value), viewsMin: vmin.valor, viewsMax: vmax.valor,
        fatorMin: Number.isFinite(fator) ? fator : null, indices: cat === "" || !est[Number(cat)] ? null : est[Number(cat)].indices,
      },
      ruins: [vmin.ruim ? $("cn-f-vmin").value : null, vmax.ruim ? $("cn-f-vmax").value : null].filter(Boolean),
    };
  }

  function renderVideos() {
    if (!analise) return;
    const { filtros, ruins } = lerFiltros();
    filtrados = C.ordenar(C.filtrar(videosBase, filtros), $("cn-f-ordem").value);
    const cats = catPorIndice();
    $("cn-videos-info").textContent = `${filtrados.length} de ${videosBase.length} vídeos`
      + (ruins.length ? ` · não entendi: ${ruins.join(", ")}` : "");
    $("cn-csv").disabled = $("cn-json").disabled = !filtrados.length;
    if (!filtrados.length) {
      $("cn-videos").innerHTML = '<div class="empty-state">nenhum vídeo com esses filtros</div>';
      return;
    }
    const temCat = Object.keys(cats).length > 0;
    $("cn-videos").innerHTML = `<div class="table-wrap"><table class="candidate-table mt-tabela"><thead><tr><th>#</th><th>Título</th><th>Views</th><th>Views/dia</th><th>Fator</th><th>Publicado</th><th>Duração</th>${temCat ? "<th>Categoria</th>" : ""}</tr></thead><tbody>`
      + filtrados.map((v) => `<tr><td class="num">${v.indice}</td>`
        + `<td class="quebra"><a href="${esc(link(v.url))}" target="_blank" rel="noopener">${esc(v.titulo)}</a><br><button type="button" class="cn-similar" data-url="${esc(v.url)}">canais parecidos</button></td>`
        + `<td class="num">${inteiro(v.views)}</td><td class="num">${fmt(v.views_dia, 1)}</td><td class="num">${v.fator === null ? "—" : `${fmt(v.fator, 1)}×`}</td>`
        + `<td>${esc(dataBr(v.data))}${v.idade_dias === null || v.idade_dias === undefined ? "" : `<br><span class="muted-small">há ${v.idade_dias} dia(s)</span>`}</td>`
        + `<td class="num">${esc(C.duracaoTexto(v.duracao_seg))}</td>${temCat ? `<td>${esc(cats[v.indice] || "")}</td>` : ""}</tr>`).join("")
      + "</tbody></table></div>";
  }

  function prepararExplorador() {
    videosBase = C.prepararVideos(analise.dados.videos, analise.dados.metricas.mediana_ultimos);
    preencherCategoriasFiltro();
    renderVideos();
  }

  function limparFiltros() {
    ["cn-f-texto", "cn-f-vmin", "cn-f-vmax", "cn-f-fator"].forEach((id) => { $(id).value = ""; });
    $("cn-f-dias").value = "";
    $("cn-f-cat").value = "";
    $("cn-f-ordem").value = "views";
    renderVideos();
  }

  function exportar(tipo) {
    if (!filtrados.length) return;
    const linhas = C.linhasExport(filtrados, catPorIndice());
    const base = `videos_${slug(analise.canal)}_${hoje()}`;
    if (tipo === "csv") baixar(`${base}.csv`, M.toCsv(C.COLUNAS_EXPORT, linhas), "text/csv;charset=utf-8");
    else baixar(`${base}.json`, JSON.stringify(linhas, null, 2), "application/json");
  }

  // ---------- IA externa ----------
  const lista = (itens, fn) => (itens && itens.length ? `<ul>${itens.map(fn).join("")}</ul>` : "");
  const bloco = (titulo, corpo) => (corpo ? `<div class="cn-bloco"><h4>${esc(titulo)}</h4>${corpo}</div>` : "");
  const dl = (pares) => {
    const linhas = pares.filter(([, v]) => v && (!Array.isArray(v) || v.length));
    return linhas.length ? `<dl>${linhas.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(Array.isArray(v) ? v.join(", ") : v)}</dd>`).join("")}</dl>` : "";
  };
  const AVISO_IA = '<div class="cn-aviso-ia">Hipóteses da IA a partir dos dados do painel. Confirme no YouTube antes de decidir.</div>';

  const RENDER = {
    categorias(d) {
      const est = d.estatisticas || [];
      return `<div class="table-wrap"><table class="candidate-table mt-tabela"><thead><tr><th>Categoria</th><th>Vídeos</th><th>% do canal</th><th>Mediana de views</th><th>Média de views</th><th>Melhor vídeo</th></tr></thead><tbody>`
        + est.map((c) => `<tr><td class="quebra"><b>${esc(c.nome)}</b>${c.descricao ? `<br><span class="muted-small">${esc(c.descricao)}</span>` : ""}</td><td class="num">${c.n}</td>`
          + `<td class="num">${c.share === null ? "—" : `${fmt(c.share * 100, 0)}%`}</td><td class="num">${inteiro(c.mediana_views)}</td><td class="num">${inteiro(c.media_views)}</td>`
          + `<td class="quebra">${c.melhor ? `<a href="${esc(link(c.melhor.url))}" target="_blank" rel="noopener">${esc(c.melhor.titulo)}</a><br><span class="muted-small">${inteiro(c.melhor.views)} views</span>` : "—"}</td></tr>`).join("")
        + `</tbody></table></div><div class="muted-small">${d.sem_categoria || 0} vídeo(s) ficaram sem categoria. Contagens e views são calculadas pelo app; a IA só decidiu quem entra em qual.</div>`;
    },
    estrategia(d) {
      return AVISO_IA
        + bloco("Padrões de desempenho", lista(d.padroes_de_desempenho, (x) => `<li><b>${esc(x.padrao)}</b>${x.confianca ? ` <span class="badge badge-muted">${esc(x.confianca)}</span>` : ""}${x.evidencia ? `<br><span class="muted-small">${esc(x.evidencia)}</span>` : ""}</li>`))
        + bloco("Fórmula de conteúdo", dl([["Promessa central", d.formula_de_conteudo.promessa_central], ["Estrutura do título", d.formula_de_conteudo.estrutura_do_titulo], ["Estrutura do vídeo", d.formula_de_conteudo.estrutura_do_video], ["Duração e ritmo", d.formula_de_conteudo.duracao_e_ritmo]]))
        + bloco("Público", dl([["Quem é", d.publico.quem_e], ["O que busca", d.publico.o_que_busca], ["Gatilhos emocionais", d.publico.gatilhos_emocionais]]))
        + bloco("Oportunidades", lista(d.oportunidades, (x) => `<li><b>${esc(x.oportunidade)}</b>${x.por_que ? `<br>${esc(x.por_que)}` : ""}${x.como_diferenciar ? `<br><span class="muted-small">Como diferenciar: ${esc(x.como_diferenciar)}</span>` : ""}${x.risco ? `<br><span class="muted-small">Risco: ${esc(x.risco)}</span>` : ""}</li>`))
        + bloco("Tópicos sugeridos", lista(d.topicos_sugeridos, (x) => `<li><b>${esc(x.titulo)}</b>${x.angulo ? `<br>${esc(x.angulo)}` : ""}${x.por_que_deve_funcionar ? `<br><span class="muted-small">${esc(x.por_que_deve_funcionar)}</span>` : ""}</li>`))
        + bloco("Diretrizes de roteiro", dl([["Gancho", d.roteiro.gancho], ["Desenvolvimento", d.roteiro.desenvolvimento], ["Fechamento", d.roteiro.fechamento]]))
        + bloco("Riscos e ressalvas", lista(d.riscos_e_ressalvas, (x) => `<li>${esc(x)}</li>`));
    },
    comentarios(d) {
      const tema = (x) => `<li><b>${esc(x.tema)}</b>${x.quantos_comentarios ? ` <span class="badge badge-muted">≈ ${x.quantos_comentarios} comentários</span>` : ""}${x.exemplo ? `<br><span class="muted-small">“${esc(x.exemplo)}”</span>` : ""}</li>`;
      return AVISO_IA
        + bloco("O que o público elogia", lista(d.gostaram, tema))
        + bloco("O que o público critica", lista(d.nao_gostaram, tema))
        + bloco("O que o público pede", lista(d.pedidos, (x) => `<li><b>${esc(x.pedido)}</b>${x.exemplo ? `<br><span class="muted-small">“${esc(x.exemplo)}”</span>` : ""}</li>`))
        + bloco("Perguntas frequentes", lista(d.perguntas_frequentes, (x) => `<li>${esc(x)}</li>`))
        + bloco("Discussões", lista(d.discussoes, (x) => `<li><b>${esc(x.tema)}</b>${x.posicoes.length ? `<br><span class="muted-small">${x.posicoes.map(esc).join(" × ")}</span>` : ""}</li>`))
        + bloco("Ideias de vídeo que nascem daqui", lista(d.ideias_de_video, (x) => `<li><b>${esc(x.titulo)}</b>${x.dor_que_resolve ? `<br><span class="muted-small">${esc(x.dor_que_resolve)}</span>` : ""}</li>`));
    },
  };

  function renderIA() {
    document.querySelectorAll(".cn-ia").forEach((cardIa) => {
      const dados = analise && analise.ia ? analise.ia[cardIa.dataset.tipo] : null;
      cardIa.querySelector(".cn-out").innerHTML = dados ? RENDER[cardIa.dataset.tipo](dados) : "";
      cardIa.querySelector(".cn-apagar").style.display = dados ? "" : "none";
    });
  }

  function msg(el, texto, ok) {
    el.textContent = texto;
    el.className = `${el.className.split(" ").filter((c) => c !== "cn-erro" && c !== "cn-ok").join(" ")} ${texto ? (ok ? "cn-ok" : "cn-erro") : ""}`.trim();
  }

  async function copiarTexto(texto) {
    try { await navigator.clipboard.writeText(texto); return true; } catch (_) { /* tenta o método antigo */ }
    const ta = document.createElement("textarea");
    ta.value = texto;
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
    ta.remove();
    return ok;
  }

  async function gerarPrompt(cardIa) {
    if (!analise) return;
    const tipo = cardIa.dataset.tipo, m = cardIa.querySelector(".cn-msg-prompt"), saida = cardIa.querySelector(".cn-prompt-out"), btn = cardIa.querySelector(".cn-copiar");
    const corpo = tipo === "estrategia" ? { mercado: $("cn-mercado").value, objetivo: $("cn-objetivo").value }
      : tipo === "comentarios" ? { comentarios: $("cn-comentarios").value } : {};
    try {
      const j = await post(`/api/canal/analises/${analise.id}/prompt/${tipo}`, corpo);
      saida.value = j.prompt;
      saida.style.display = "";
      btn.disabled = false;
      msg(m, `Prompt de ${inteiro(j.prompt.length)} caracteres. Copie e cole na sua IA.`, true);
    } catch (e) {
      saida.style.display = "none";
      btn.disabled = true;
      msg(m, e.message, false);
    }
  }

  async function copiarPrompt(cardIa) {
    const m = cardIa.querySelector(".cn-msg-prompt");
    const ok = await copiarTexto(cardIa.querySelector(".cn-prompt-out").value);
    msg(m, ok ? "Copiado." : "Não consegui copiar sozinho: selecione o texto e copie.", ok);
  }

  async function aplicar(cardIa) {
    if (!analise) return;
    const tipo = cardIa.dataset.tipo, m = cardIa.querySelector(".cn-msg");
    try {
      const j = await post(`/api/canal/analises/${analise.id}/ia/${tipo}`, { texto: cardIa.querySelector(".cn-colar").value });
      analise = j.analise;
      cardIa.querySelector(".cn-colar").value = "";
      msg(m, "Aplicado.", true);
      renderIA();
      prepararExplorador();
    } catch (e) { msg(m, e.message, false); }
  }

  async function apagar(cardIa) {
    if (!analise) return;
    const m = cardIa.querySelector(".cn-msg");
    try {
      const j = await api(`/api/canal/analises/${analise.id}/ia/${cardIa.dataset.tipo}`, { method: "DELETE" });
      analise = j.analise;
      msg(m, "Resultado apagado.", true);
      renderIA();
      prepararExplorador();
    } catch (e) { msg(m, e.message, false); }
  }

  // ---------- pontes para as outras abas ----------
  function irPara(aba) {
    const b = document.querySelector(`.topnav-btn[data-view="${aba}"]`);
    if (b) b.click();
  }

  function enviarParaRecomendacoes(urls) {
    const alvo = $("rec-urls");
    const atuais = alvo.value.split("\n").map((l) => l.trim()).filter(Boolean);
    alvo.value = [...atuais, ...urls.filter((u) => !atuais.includes(u))].join("\n");
    alvo.dispatchEvent(new Event("input"));
    irPara("minerar");
    alvo.scrollIntoView({ block: "center" });
  }

  function pontesPadrao() {
    const p = analise.dados.padroes;
    const palavras = p.palavras_chave.map((k) => k.palavra);
    const nome = analise.canal || "";
    $("cn-ponte-tema").value = palavras[0] ? palavras[0].charAt(0).toUpperCase() + palavras[0].slice(1) : nome;
    $("cn-ponte-termos").value = (palavras.length ? palavras.slice(0, 5) : [nome]).join(", ");
    $("cn-ponte-info").textContent = "";
    $("cn-ponte-nicho-info").textContent = "";
  }

  async function abrirNaIdeias(pid, tema) {
    irPara("ideias");
    for (let i = 0; i < 80; i++) {
      const sel = $("id-sessoes");
      if (sel && sel.options.length) {
        if (![...sel.options].some((o) => o.value === String(pid))) {
          // a aba Ideias só carrega a lista uma vez; a pesquisa nova entra à mão
          sel.insertAdjacentHTML("beforeend", `<option value="${pid}">#${pid} · ${esc(tema)} · 0 ideia(s)</option>`);
        }
        sel.value = String(pid);
        sel.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      }
      await sleep(100);
    }
    return false;
  }

  async function criarPesquisaIdeias() {
    const info = $("cn-ponte-nicho-info");
    const tema = $("cn-ponte-tema").value.trim();
    const termos = $("cn-ponte-termos").value.split(/[,;\n]+/).map((t) => t.trim()).filter(Boolean);
    if (!tema || !termos.length) { msg(info, "Informe o tema e ao menos um termo de busca.", false); return; }
    try {
      const j = await post("/api/ideias/pesquisas", { tema, mercado: $("cn-mercado").value || "BR", termos });
      msg(info, `Pesquisa #${j.pesquisa.id} criada na aba Ideias.`, true);
      await abrirNaIdeias(j.pesquisa.id, tema);
    } catch (e) { msg(info, e.message, false); }
  }

  // ---------- montagem ----------
  function renderTudo() {
    $("cn-painel").style.display = "";
    $("cn-excluir").disabled = false;
    renderPainel();
    prepararExplorador();
    renderIA();
    document.querySelectorAll(".cn-ia").forEach((c) => {
      c.querySelector(".cn-prompt-out").style.display = "none";
      c.querySelector(".cn-copiar").disabled = true;
      msg(c.querySelector(".cn-msg-prompt"), "", true);
      msg(c.querySelector(".cn-msg"), "", true);
    });
    pontesPadrao();
  }

  async function iniciar() {
    if (iniciado) return;
    iniciado = true;
    try {
      const j = await api("/api/ideias/mercados");
      $("cn-mercado").innerHTML = j.mercados.map((m) => `<option value="${esc(m.codigo)}">${esc(m.nome)} — ${esc(m.idioma)}</option>`).join("");
    } catch (_) {
      $("cn-mercado").innerHTML = '<option value="BR">Brasil — português (Brasil)</option>';
    }
    try { await carregarLista(); } catch (e) { iniciado = false; addLog(`ERRO: ${e.message}`); }
  }

  $("cn-analisar").addEventListener("click", analisar);
  $("cn-url").addEventListener("keydown", (e) => { if (e.key === "Enter") analisar(); });
  $("cn-analises").addEventListener("change", (e) => { if (e.target.value) abrir(e.target.value); else fechar(); });
  $("cn-excluir").addEventListener("click", excluir);
  ["cn-f-texto", "cn-f-vmin", "cn-f-vmax", "cn-f-fator"].forEach((id) => $(id).addEventListener("input", renderVideos));
  ["cn-f-dias", "cn-f-cat", "cn-f-ordem"].forEach((id) => $(id).addEventListener("change", renderVideos));
  $("cn-f-limpar").addEventListener("click", limparFiltros);
  $("cn-csv").addEventListener("click", () => exportar("csv"));
  $("cn-json").addEventListener("click", () => exportar("json"));
  $("cn-exp-analise").addEventListener("click", () => {
    if (analise) baixar(`analise_${slug(analise.canal)}_${hoje()}.json`, JSON.stringify({ canal: analise.canal, canal_url: analise.canal_url, coletado_em: analise.dados.coletado_em, dados: analise.dados, ia: analise.ia }, null, 2), "application/json");
  });
  $("cn-videos").addEventListener("click", (e) => {
    const b = e.target.closest(".cn-similar");
    if (b) enviarParaRecomendacoes([b.dataset.url]);
  });
  document.querySelectorAll(".cn-ia").forEach((cardIa) => {
    cardIa.querySelector(".cn-gerar").addEventListener("click", () => gerarPrompt(cardIa));
    cardIa.querySelector(".cn-copiar").addEventListener("click", () => copiarPrompt(cardIa));
    cardIa.querySelector(".cn-aplicar").addEventListener("click", () => aplicar(cardIa));
    cardIa.querySelector(".cn-apagar").addEventListener("click", () => apagar(cardIa));
  });
  $("cn-ponte-similares").addEventListener("click", () => {
    if (!analise) return;
    const urls = analise.dados.metricas.melhores.map((v) => v.url).filter((u) => /^https?:\/\//.test(u || "")).slice(0, 3);
    if (!urls.length) { msg($("cn-ponte-info"), "Não há vídeos com link para enviar.", false); return; }
    msg($("cn-ponte-info"), `Enviei ${urls.length} link(s) para a aba Minerar.`, true);
    enviarParaRecomendacoes(urls);
  });
  $("cn-ponte-nicho").addEventListener("click", criarPesquisaIdeias);
  $("cn-ir-metodo").addEventListener("click", () => { irPara("metodo"); const s = $("ms-n"); if (s) s.focus(); });
  document.querySelectorAll('.topnav-btn[data-view="canal"]').forEach((b) => b.addEventListener("click", iniciar));
})();
