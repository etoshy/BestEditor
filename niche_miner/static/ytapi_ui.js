// Aba "API do YouTube": seis ferramentas sobre a YouTube Data API v3, com IA externa no padrão do app.
// Depende de ytapi.js (filtros e ordenação puros), metodo.js (toCsv) e app.js (escapeHtml).
(function () {
  const Y = window.NicheYT;
  const M = window.NicheMetodo;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => escapeHtml(s);
  const fmt = (n, casas = 2) => (n === null || n === undefined || !Number.isFinite(Number(n))) ? "—" : Number(n).toLocaleString("pt-BR", { maximumFractionDigits: casas });
  const inteiro = (n) => (n === null || n === undefined || !Number.isFinite(Number(n))) ? "—" : new Intl.NumberFormat("pt-BR").format(Math.round(Number(n)));
  const link = (url) => (/^https:\/\//.test(url || "") ? url : "#");
  const dataBr = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ""); return m ? `${m[3]}/${m[2]}/${m[1]}` : "—"; };
  const hoje = () => new Date().toISOString().slice(0, 10);
  const LS = { chave: "niche_miner_yt_chave", short: "niche_miner_yt_short", cota: "niche_miner_yt_cota" };
  const LIMITE_LISTA_IA = 40;

  const guardar = (k, v) => { try { localStorage.setItem(k, v); } catch (_) { /* navegador sem storage */ } };
  const ler = (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } };
  const apagarChave = (k) => { try { localStorage.removeItem(k); } catch (_) { /* idem */ } };

  let chaveNoAmbiente = false;
  const estado = { pesquisa: null, alta: null, comparar: null, canal: null, video: null, historico: null };

  // ---------- rede ----------
  async function api(url, opcoes) {
    const resp = await fetch(url, opcoes);
    let j = null;
    try { j = await resp.json(); } catch (_) { /* sem corpo JSON */ }
    if (!resp.ok || !j || j.ok === false) throw new Error((j && j.erro) || `erro ${resp.status}`);
    return j;
  }
  const chave = () => $("yt-chave").value.trim();
  const shortMax = () => Number($("yt-short").value) || Y.SHORT_PADRAO;
  const postJson = (url, corpo) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo || {}) });
  const postYT = (url, corpo) => postJson(url, { ...corpo, chave: chave() });        // só as rotas que falam com o YouTube levam a chave

  function msg(el, texto, ok) {
    el.textContent = texto || "";
    el.className = `${el.className.split(" ").filter((c) => c !== "cn-erro" && c !== "cn-ok").join(" ")} ${texto ? (ok ? "cn-ok" : "cn-erro") : ""}`.trim();
  }

  function baixar(nome, conteudo, tipo) {
    const url = URL.createObjectURL(new Blob([conteudo], { type: tipo }));
    const a = document.createElement("a");
    a.href = url; a.download = nome;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function copiarTexto(texto) {
    try { await navigator.clipboard.writeText(texto); return true; } catch (_) { /* tenta o método antigo */ }
    const ta = document.createElement("textarea");
    ta.value = texto; document.body.appendChild(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
    ta.remove();
    return ok;
  }

  // ---------- chave, short e cota ----------
  function cotaLer() { try { return JSON.parse(ler(LS.cota)); } catch (_) { return null; } }
  function cotaMostrar() {
    const e = cotaLer();
    $("yt-cota-usada").textContent = inteiro(e && e.dia === Y.diaPacifico(new Date()) ? e.usadas : 0);
  }
  function cotaSomar(unidades) {
    guardar(LS.cota, JSON.stringify(Y.somarCota(cotaLer(), Y.diaPacifico(new Date()), unidades)));
    cotaMostrar();
  }

  // Roda uma chamada ao YouTube: bloqueia o botão, soma a cota e mostra o resultado (ou o erro) na mensagem do painel.
  async function executar(btn, msgEl, ocupado, fn) {
    if (btn.disabled) return null;
    if (!chave() && !chaveNoAmbiente) {
      msg(msgEl, "Cole a chave da API na seção 0 (Chave da API e cota).", false);
      return null;
    }
    const original = btn.textContent;
    btn.disabled = true; btn.textContent = ocupado; msg(msgEl, "", true);
    try {
      const j = await fn();
      cotaSomar(j.unidades);
      msg(msgEl, `Gastou ${inteiro(j.unidades)} unidades de cota.${(j.avisos || []).length ? " " + j.avisos.join(" ") : ""}`, true);
      return j;
    } catch (e) {
      msg(msgEl, e.message, false);
      return null;
    } finally {
      btn.disabled = false; btn.textContent = original;
    }
  }

  // ---------- tabela de vídeos ----------
  const canalUrl = (v, canais) => {
    const c = (canais || {})[v.canal_id];
    if (c && c.url) return link(c.url);
    return /^UC[\w-]{22}$/.test(v.canal_id || "") ? `https://www.youtube.com/channel/${v.canal_id}` : "#";
  };

  function tabelaHtml(lista, canais, opcoes) {
    const o = { thumbs: true, ...(opcoes || {}) };
    const cab = ["#", "Vídeo", "Canal", "Inscritos", "Views", "Likes", "Coment.", "Engaj.", "Views/dia", "Duração", "Publicado"];
    const linhas = lista.map((v, i) => {
      const c = (canais || {})[v.canal_id];
      const ins = c ? (c.inscritos_ocultos ? "ocultos" : inteiro(c.inscritos)) : "—";
      const selo = v.ao_vivo ? ' <span class="badge badge-muted">ao vivo</span>' : (Y.ehShort(v, shortMax()) ? ' <span class="badge badge-muted">Short</span>' : "");
      const thumb = o.thumbs && v.thumb ? `<img src="${esc(link(v.thumb))}" alt="" width="96" loading="lazy"> ` : "";
      return `<tr><td class="num">${i + 1}</td><td class="quebra yt-video">${thumb}<a href="${esc(link(v.url))}" target="_blank" rel="noopener">${esc(v.titulo)}</a></td>`
        + `<td class="quebra"><a href="${esc(canalUrl(v, canais))}" target="_blank" rel="noopener">${esc(v.canal)}</a></td><td class="num">${ins}</td>`
        + `<td class="num">${inteiro(v.views)}</td><td class="num">${inteiro(v.likes)}</td><td class="num">${inteiro(v.comentarios)}</td>`
        + `<td class="num">${v.engajamento === null || v.engajamento === undefined ? "—" : fmt(v.engajamento) + "%"}</td><td class="num">${inteiro(v.views_dia)}</td>`
        + `<td class="num">${Y.duracaoTexto(v.duracao_seg)}${selo}</td><td class="num">${dataBr(v.data)}</td></tr>`;
    });
    return `<thead><tr>${cab.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${linhas.join("") || `<tr><td colspan="${cab.length}" class="muted-small">Nenhum vídeo passa nos filtros.</td></tr>`}</tbody>`;
  }

  function cartao(rot, val, sub) {
    const nd = val === null || val === undefined || val === "—";
    return `<div class="cn-card${nd ? " cn-card-nd" : ""}"><div class="cn-card-rot">${esc(rot)}</div><div class="cn-card-val">${nd ? "não disponível" : esc(val)}</div>${sub ? `<div class="cn-card-sub">${esc(sub)}</div>` : ""}</div>`;
  }

  function preencherSelect(el, pares, padrao) {
    el.innerHTML = pares.map(([v, r]) => `<option value="${esc(v)}">${esc(r)}</option>`).join("");
    if (padrao !== undefined) el.value = padrao;
  }

  // ---------- IA (o mesmo padrão nas cinco): gerar prompt, colar a resposta, aplicar ----------
  const ev = (indices, lista) => {
    const itens = (indices || []).filter((i) => lista && lista[i - 1]);
    return itens.length ? ` <span class="yt-ev">evidência: ${itens.map((i) => `<a href="${esc(link(lista[i - 1].url))}" target="_blank" rel="noopener" title="${esc(lista[i - 1].titulo)}">${i}</a>`).join(" ")}</span>` : "";
  };
  const li = (itens) => (itens && itens.length ? `<ul>${itens.map((x) => `<li>${x}</li>`).join("")}</ul>` : "");
  const lista = (itens) => li((itens || []).map(esc));

  // [rótulo, campo, tipo, formatador do item]
  const SECOES = {
    oportunidades: [
      ["Leitura geral", "leitura_geral", "texto"],
      ["Nichos em alta", "nichos_em_alta", "itens", (x, l) => `<b>${esc(x.nicho)}</b>${x.dificuldade ? ` <span class="badge badge-muted">${esc(x.dificuldade)}</span>` : ""}<br>${esc(x.por_que_esta_em_alta)}${x.risco ? `<br><i>Risco: ${esc(x.risco)}</i>` : ""}${ev(x.evidencia, l)}`],
      ["Oportunidades para canal dark", "oportunidades_dark", "itens", (x, l) => `<b>${esc(x.ideia)}</b>${x.formato ? ` — ${esc(x.formato)}` : ""}${x.como_produzir_sem_aparecer ? `<br>Como produzir: ${esc(x.como_produzir_sem_aparecer)}` : ""}${x.exemplo_de_titulo ? `<br>Título de exemplo: “${esc(x.exemplo_de_titulo)}”` : ""}${ev(x.evidencia, l)}`],
      ["Canais pequenos em destaque", "canais_pequenos_em_destaque", "itens", (x, l, extra) => {
        const v = l && l[x.indice - 1];
        const c = v && extra && extra.canais ? extra.canais[v.canal_id] : null;
        const rotulo = v ? esc(v.canal) : `vídeo ${x.indice}`;
        return `${v ? `<a href="${esc(canalUrl(v, (extra && extra.canais) || {}))}" target="_blank" rel="noopener">${rotulo}</a>` : rotulo}${v ? ` (<a href="${esc(link(v.url))}" target="_blank" rel="noopener">ver vídeo</a>)` : ""}: ${esc(x.por_que_chama_atencao)}`;
      }],
      ["Ressalvas", "ressalvas", "lista"],
    ],
    comparativo: [
      ["Resumo", "resumo", "texto"], ["Onde o canal A vai melhor", "forcas_a", "lista"], ["Onde o canal B vai melhor", "forcas_b", "lista"],
      ["Diferenças de estratégia", "diferencas_de_estrategia", "itens", (x) => `<b>${esc(x.tema)}</b><br>A: ${esc(x.a)}<br>B: ${esc(x.b)}`],
      ["Oportunidades para competir", "oportunidades_para_competir", "itens", (x) => `<b>${esc(x.oportunidade)}</b>${x.como ? `<br>${esc(x.como)}` : ""}`],
      ["Veredito", "veredito", "texto"], ["Ressalvas", "ressalvas", "lista"],
    ],
    dossie: [
      ["Resumo", "resumo", "texto"], ["Posicionamento", "posicionamento", "texto"], ["Proposta de valor", "proposta_de_valor", "texto"], ["Público", "publico", "texto"],
      ["Pontos fortes", "pontos_fortes", "lista"], ["Pontos fracos", "pontos_fracos", "lista"],
      ["Oportunidades", "oportunidades", "itens", (x) => `<b>${esc(x.oportunidade)}</b>${x.como_aproveitar ? `<br>${esc(x.como_aproveitar)}` : ""}`],
      ["Riscos", "riscos", "lista"], ["Próximos passos", "proximos_passos", "lista"], ["Ressalvas", "ressalvas", "lista"],
    ],
    engenharia: [
      ["Resumo", "resumo", "texto"], ["Gancho", "gancho", "objeto", (x) => `<b>${esc(x.tecnica)}</b>${x.como_funciona ? `<br>${esc(x.como_funciona)}` : ""}`], ["Promessa", "promessa", "texto"],
      ["Estrutura do roteiro", "estrutura", "itens", (x) => `<b>${esc(x.trecho)}</b>${x.funcao ? ` — ${esc(x.funcao)}` : ""}${x.tecnica ? `<br><i>${esc(x.tecnica)}</i>` : ""}`],
      ["Retenção", "retencao", "lista"], ["Tom e ritmo", "tom_e_ritmo", "texto"], ["Chamada para ação", "cta", "texto"],
      ["O que replicar", "o_que_replicar", "lista"], ["O que evitar", "o_que_evitar", "lista"], ["Ressalvas", "ressalvas", "lista"],
    ],
    auditoria: [
      ["Resumo", "resumo", "texto"],
      ["Fases do canal", "fases", "itens", (x, l) => `<b>${esc(x.periodo)}</b>: ${esc(x.o_que_aconteceu)}${ev(x.evidencia, l)}`],
      ["Padrões", "padroes", "itens", (x, l) => `${esc(x.padrao)}${ev(x.evidencia, l)}`],
      ["Pontos de virada", "pontos_de_virada", "itens", (x, l) => `<b>${esc(x.quando)}</b>: ${esc(x.o_que_mudou)}${ev(x.evidencia, l)}`],
      ["O que funciona", "o_que_funciona", "lista"], ["O que não funciona", "o_que_nao_funciona", "lista"],
      ["Recomendações", "recomendacoes", "itens", (x) => `<b>${esc(x.acao)}</b>${x.por_que ? `<br>${esc(x.por_que)}` : ""}`], ["Ressalvas", "ressalvas", "lista"],
    ],
  };

  function renderIA(tipo, res, ref, extra) {
    const blocos = [];
    for (const [rotulo, campo, kind, fmtItem] of SECOES[tipo]) {
      const v = res[campo];
      let corpo = "";
      if (kind === "texto") corpo = v ? `<p>${esc(v)}</p>` : "";
      else if (kind === "lista") corpo = lista(v);
      else if (kind === "itens") corpo = li((v || []).map((x) => fmtItem(x, ref, extra)));
      else if (kind === "objeto") corpo = v && (v.tecnica || v.como_funciona) ? `<p>${fmtItem(v)}</p>` : "";
      if (corpo) blocos.push(`<div class="cn-bloco"><h4>${esc(rotulo)}</h4>${corpo}</div>`);
    }
    return `${blocos.join("")}<div class="cn-aviso-ia">Resposta de uma IA que só viu os dados do prompt: trate como hipótese e confirme no YouTube.</div>`;
  }

  const IAS = {};        // tipo -> { alvo, titulo, ajuda, dados: () => {dados, transcricao, ref}|null }

  function montarIA(tipo, cfg) {
    IAS[tipo] = cfg;
    const alvo = $(cfg.alvo);
    alvo.innerHTML = `<div class="id-card mt-card yt-ia" data-tipo="${tipo}">
      <div class="mt-titulo">${esc(cfg.titulo)}</div>
      <p class="hint">${esc(cfg.ajuda)}</p>
      <label>Contexto extra (opcional)</label>
      <textarea class="yt-ctx" rows="2" placeholder="${esc(cfg.placeholder || "Ex.: o que você quer decidir com essa análise")}"></textarea>
      <div class="id-linha"><button type="button" class="yt-gerar">1. Gerar prompt</button><button type="button" class="yt-copiar" disabled>Copiar prompt</button><span class="muted-small yt-msg-prompt"></span></div>
      <textarea class="yt-prompt-out" rows="5" readonly style="display:none"></textarea>
      <label>2. Cole a resposta da IA (JSON)</label>
      <textarea class="yt-colar" rows="4"></textarea>
      <div class="id-linha"><button type="button" class="primary yt-aplicar">Aplicar resposta</button><button type="button" class="danger yt-apagar" style="display:none">Apagar resultado</button><span class="muted-small yt-msg"></span></div>
      <div class="yt-out cn-out"></div>
    </div>`;
    const card = alvo.firstElementChild;
    const q = (s) => card.querySelector(s);
    let ref = null, extra = null;
    cfg.limparRef = () => { ref = null; extra = null; };          // dados novos: a lista de evidências antiga não vale mais

    q(".yt-gerar").addEventListener("click", async () => {
      const m = q(".yt-msg-prompt");
      const d = cfg.dados();
      if (!d) { msg(m, "Carregue os dados primeiro.", false); return; }
      try {
        const j = await postJson(`/api/yt/prompt/${tipo}`, { dados: d.dados, contexto: q(".yt-ctx").value, transcricao: d.transcricao || "" });
        ref = d.ref || null;
        extra = d.extra || null;
        q(".yt-prompt-out").value = j.prompt;
        q(".yt-prompt-out").style.display = "";
        q(".yt-copiar").disabled = false;
        msg(m, `Prompt de ${inteiro(j.prompt.length)} caracteres. Copie e cole na sua IA.`, true);
      } catch (e) {
        q(".yt-prompt-out").style.display = "none";
        q(".yt-copiar").disabled = true;
        msg(m, e.message, false);
      }
    });
    q(".yt-copiar").addEventListener("click", async () => {
      msg(q(".yt-msg-prompt"), (await copiarTexto(q(".yt-prompt-out").value)) ? "Copiado." : "Não consegui copiar sozinho: selecione o texto e copie.", true);
    });
    q(".yt-aplicar").addEventListener("click", async () => {
      const m = q(".yt-msg");
      try {
        const j = await postJson(`/api/yt/ia/${tipo}`, { texto: q(".yt-colar").value, n_videos: ref ? ref.length : 0 });
        q(".yt-out").innerHTML = renderIA(tipo, j.resultado, ref, extra);
        q(".yt-colar").value = "";
        q(".yt-apagar").style.display = "";
        msg(m, "Aplicado.", true);
      } catch (e) { msg(m, e.message, false); }
    });
    q(".yt-apagar").addEventListener("click", () => {
      q(".yt-out").innerHTML = "";
      q(".yt-apagar").style.display = "none";
      msg(q(".yt-msg"), "Resultado apagado.", true);
    });
  }

  // Dados novos deixam prompt e resultado antigos velhos: limpa (o contexto digitado fica).
  function reiniciarIA(tipo) {
    const cfg = IAS[tipo];
    if (!cfg) return;
    cfg.limparRef();
    const card = $(cfg.alvo).firstElementChild;
    card.querySelector(".yt-out").innerHTML = "";
    card.querySelector(".yt-prompt-out").value = "";
    card.querySelector(".yt-prompt-out").style.display = "none";
    card.querySelector(".yt-copiar").disabled = true;
    card.querySelector(".yt-apagar").style.display = "none";
    msg(card.querySelector(".yt-msg"), "", true);
    msg(card.querySelector(".yt-msg-prompt"), "", true);
  }

  // ---------- 1. Pesquisa avançada ----------
  const ORDENS_TABELA = [["engajamento", "Engajamento"], ["views", "Views"], ["likes", "Likes"], ["comentarios", "Comentários"], ["data", "Data de publicação"], ["views_dia", "Views por dia"], ["inscritos", "Inscritos do canal"], ["duracao", "Duração"]];
  const minutos = (id) => { const v = $(id).value; return v === "" ? null : Math.round(Number(v) * 60); };

  function filtrosPesquisa() {
    return {
      viewsMin: $("yp-f-views").value, subsMin: $("yp-f-smin").value, subsMax: $("yp-f-smax").value, canalViewsMin: $("yp-f-cvmin").value, canalViewsMax: $("yp-f-cvmax").value,
      duracaoMinSeg: minutos("yp-f-dmin"), duracaoMaxSeg: minutos("yp-f-dmax"), formato: $("yp-f-formato").value,
    };
  }
  function listaPesquisa() {
    const p = estado.pesquisa;
    if (!p) return [];
    return Y.ordenar(Y.filtrar(p.videos, p.canais, filtrosPesquisa(), shortMax()), $("yp-ordem").value, $("yp-dir").value, p.canais);
  }
  function renderPesquisa() {
    const p = estado.pesquisa;
    if (!p) return;
    const vis = listaPesquisa();
    $("yp-tabela").innerHTML = tabelaHtml(vis, p.canais);
    $("yp-contagem").textContent = `${vis.length} de ${p.videos.length} vídeos`;
  }

  function atualizarCustoPesquisa() {
    const q = $("yp-q").value;
    $("yp-custo").textContent = `Custa cerca de ${Y.custoPesquisa(q)} unidades (${q.trim() ? "busca por palavra-chave: 100 da busca + 2 dos detalhes" : "vídeos em alta filtrados: 2"}).`;
  }

  async function buscar() {
    const dados = { q: $("yp-q").value, formato: $("yp-formato").value, idioma: $("yp-idioma").value, pais: $("yp-pais").value, duracao: $("yp-duracao").value,
      ordem: $("yp-api-ordem").value, quantidade: $("yp-qtd").value, de: $("yp-de").value, ate: $("yp-ate").value };
    const j = await executar($("yp-buscar"), $("yp-msg"), "Buscando…", () => postYT("/api/yt/pesquisar", dados));
    if (!j) return;
    estado.pesquisa = j;
    if (j.params.assumiu_7_dias) $("yp-de").value = j.params.de;
    $("yp-f-formato").value = $("yp-formato").value;
    $("yp-ordem").value = "engajamento";
    $("yp-dir").value = "desc";
    $("yp-resultado").style.display = "";
    renderPesquisa();
    if (j.params.assumiu_7_dias) msg($("yp-msg"), `Gastou ${inteiro(j.unidades)} unidades de cota. Sem datas: usei os últimos 7 dias (a partir de ${dataBr(j.params.de)}). ${(j.avisos || []).join(" ")}`, true);
  }

  function csvPesquisa() {
    const p = estado.pesquisa;
    if (!p) return;
    baixar(`pesquisa_youtube_${hoje()}.csv`, M.toCsv(Y.COLUNAS_CSV, Y.linhasCsv(listaPesquisa(), p.canais, shortMax())), "text/csv;charset=utf-8");
  }

  // PDF: monta uma cópia só para impressão e abre a janela do navegador (o usuário escolhe "Salvar como PDF").
  function pdfPesquisa() {
    const p = estado.pesquisa;
    if (!p) return;
    const vis = listaPesquisa();
    const d = p.params;
    const cab = `<h1>Pesquisa no YouTube${d.q ? `: ${esc(d.q)}` : " (em alta filtrado)"}</h1><p>${esc(dataBr(hoje()))} · ${vis.length} de ${p.videos.length} vídeos · país ${esc(d.pais_usado || d.pais || "qualquer")} · período a partir de ${esc(dataBr(d.de))}${d.ate ? ` até ${esc(dataBr(d.ate))}` : ""}</p>`;
    const area = document.createElement("div");
    area.id = "yt-print";
    area.innerHTML = `${cab}<table class="yt-print-tabela">${tabelaHtml(vis, p.canais, { thumbs: false })}</table>`;
    document.body.appendChild(area);
    document.body.classList.add("yt-imprimindo");
    const limpar = () => { document.body.classList.remove("yt-imprimindo"); area.remove(); window.removeEventListener("afterprint", limpar); };
    window.addEventListener("afterprint", limpar);
    window.print();
    setTimeout(limpar, 60000);        // se o navegador não disparar afterprint
  }

  // ---------- 2. Em alta ----------
  function listaAlta() {
    const a = estado.alta;
    if (!a) return { visiveis: [], total: 0 };
    const filtrados = Y.filtrarEmAlta(a.videos, { duracao: $("ya-dur").value }, shortMax());
    return { visiveis: Y.ordenar(filtrados, $("ya-ordem").value, $("ya-dir").value, a.canais), total: a.videos.length };
  }
  function renderAlta() {
    const a = estado.alta;
    if (!a) return;
    const { visiveis, total } = listaAlta();
    $("ya-tabela").innerHTML = tabelaHtml(visiveis, a.canais);
    $("ya-contagem").textContent = `${visiveis.length} de ${total} vídeos em alta (só com 100 mil views ou mais)`;
  }
  async function carregarAlta() {
    const j = await executar($("ya-carregar"), $("ya-msg"), "Carregando…", () => postYT("/api/yt/em-alta", { pais: $("ya-pais").value, categoria: $("ya-cat").value }));
    if (!j) return;
    estado.alta = j;
    $("ya-resultado").style.display = "";
    reiniciarIA("oportunidades");
    renderAlta();
  }

  // ---------- 3. Comparar ----------
  const CASAS = { inscritos_por_video: 1, videos_por_semana_vida: 2, videos_por_semana: 2, tracao: 2, engajamento_medio: 2 };
  function cabecaCanal(rot, p) {
    const c = p.canal;
    return `<div class="cn-cab"><div><b>${rot}</b> · <a href="${esc(link(c.url))}" target="_blank" rel="noopener">${esc(c.titulo)}</a>${c.handle ? ` ${esc(c.handle)}` : ""}</div>`
      + `<div class="muted-small">${c.inscritos_ocultos ? "inscritos ocultos" : `${inteiro(c.inscritos)} inscritos`} · no ar desde ${dataBr(c.criado_em)}</div></div>`;
  }
  function renderComparar(j) {
    $("yc-cabecas").innerHTML = cabecaCanal("A", j.a) + cabecaCanal("B", j.b);
    const celula = (linha, lado) => {
      const v = linha[lado];
      const txt = v === null || v === undefined ? "—" : (CASAS[linha.chave] ? fmt(v, CASAS[linha.chave]) : inteiro(v));
      return `<td class="num${linha.maior === lado ? " yt-maior" : ""}">${txt}${linha.maior === lado ? ' <span class="badge badge-muted">maior</span>' : ""}</td>`;
    };
    $("yc-tabela").innerHTML = `<thead><tr><th>Métrica</th><th>Canal A</th><th>Canal B</th></tr></thead><tbody>${j.comparacao.map((l) => `<tr><td class="quebra">${esc(l.rotulo)}</td>${celula(l, "a")}${celula(l, "b")}</tr>`).join("")}</tbody>`;
    const top = (rot, p) => `<div class="cn-bloco"><h4>${rot}: mais vistos entre os últimos ${p.videos.length}</h4>${li([...p.videos].sort((x, y) => (y.views || 0) - (x.views || 0)).slice(0, 5).map((v) => `<a href="${esc(link(v.url))}" target="_blank" rel="noopener">${esc(v.titulo)}</a> — ${inteiro(v.views)} views`))}</div>`;
    $("yc-videos").innerHTML = top("Canal A", j.a) + top("Canal B", j.b);
  }
  async function comparar() {
    const j = await executar($("yc-comparar"), $("yc-msg"), "Comparando…", () => postYT("/api/yt/comparar", { a: $("yc-a").value, b: $("yc-b").value }));
    if (!j) return;
    estado.comparar = j;
    $("yc-resultado").style.display = "";
    reiniciarIA("comparativo");
    renderComparar(j);
  }

  // ---------- 4. Analisar canal ----------
  function idadeTexto(dias) {
    if (dias === null || dias === undefined) return null;
    return dias >= 365 ? `${fmt(dias / 365, 1)} anos` : `${inteiro(dias)} dias`;
  }
  function renderCanal(j) {
    const c = j.canal, m = j.metricas;
    $("yk-cab").innerHTML = `${c.thumb ? `<img src="${esc(link(c.thumb))}" alt="" width="64" height="64" style="border-radius:50%">` : ""}<div><b><a href="${esc(link(c.url))}" target="_blank" rel="noopener">${esc(c.titulo)}</a></b> ${c.handle ? esc(c.handle) : ""}<div class="muted-small">${c.pais ? `${esc(c.pais)} · ` : ""}criado em ${dataBr(c.criado_em)}</div></div>`;
    $("yk-cards").innerHTML = [
      cartao("Inscritos", c.inscritos_ocultos ? null : inteiro(c.inscritos), c.inscritos_ocultos ? "o canal esconde" : ""), cartao("Views totais", inteiro(c.views_totais)), cartao("Vídeos publicados", inteiro(c.n_videos)),
      cartao("Views por vídeo", m.views_por_video === null ? null : inteiro(m.views_por_video), "views totais ÷ vídeos"),
      cartao("Vídeos por semana", m.videos_por_semana === null ? null : fmt(m.videos_por_semana), "desde a criação do canal"),
      cartao("Inscritos ÷ views", m.inscritos_por_view_pct === null ? null : `${fmt(m.inscritos_por_view_pct, 3)}%`, "quanto da audiência virou inscrito"),
      cartao("Inscritos por vídeo", m.inscritos_por_video === null ? null : fmt(m.inscritos_por_video, 1)), cartao("Tempo de canal", idadeTexto(m.idade_dias)),
    ].join("");
    $("yk-palavras").innerHTML = c.palavras_chave.map((k) => `<span class="cn-chip">${esc(k)}</span>`).join("");
    $("yk-descricao").textContent = c.descricao || "(sem descrição)";
  }
  async function analisarCanal() {
    const j = await executar($("yk-analisar"), $("yk-msg"), "Analisando…", () => postYT("/api/yt/canal", { canal: $("yk-canal").value }));
    if (!j) return;
    estado.canal = j;
    $("yk-resultado").style.display = "";
    reiniciarIA("dossie");
    renderCanal(j);
  }

  // ---------- 5. Analisar vídeo ----------
  function renderVideo(j, anterior) {
    const v = j.video;
    $("yv-thumb").src = link(v.thumb);
    $("yv-baixar").href = `/api/yt/miniatura?video=${encodeURIComponent(v.id)}`;
    $("yv-baixar-info").className = "muted-small";
    $("yv-baixar-info").textContent = "tenta maxresdefault e desce até default";
    $("yv-cab").innerHTML = `<b><a href="${esc(link(v.url))}" target="_blank" rel="noopener">${esc(v.titulo)}</a></b><div class="muted-small">${esc(v.canal)} · publicado em ${dataBr(v.data)}${v.topicos.length ? ` · tópicos: ${esc(v.topicos.join(", "))}` : ""}</div>`;
    const formato = v.ao_vivo ? "Ao vivo" : (v.duracao_seg > 0 ? (Y.ehShort(v, shortMax()) ? "Short" : "Longo") : null);
    $("yv-cards").innerHTML = [
      cartao("Views", inteiro(v.views)), cartao("Likes", v.likes === null ? null : inteiro(v.likes)), cartao("Comentários", inteiro(v.comentarios)),
      cartao("Engajamento", v.engajamento === null ? null : `${fmt(v.engajamento)}%`, "(likes + comentários) ÷ views"), cartao("Duração", Y.duracaoTexto(v.duracao_seg), v.duracao_seg === null ? "" : `${inteiro(v.duracao_seg)} segundos`),
      cartao("Formato", formato, formato === "Short" ? `até ${shortMax()} s` : ""), cartao("Views ÷ inscritos", v.views_sobre_inscritos === null ? null : fmt(v.views_sobre_inscritos), v.inscritos_do_canal === null ? "canal esconde inscritos" : `${inteiro(v.inscritos_do_canal)} inscritos`),
      cartao("Idade", v.idade_dias === null ? null : `${inteiro(v.idade_dias)} dias`, `${fmt(v.views_dia, 0)} views por dia`),
    ].join("");
    $("yv-tags").innerHTML = v.tags.map((t) => `<span class="cn-chip">${esc(t)}</span>`).join("") || '<span class="muted-small">Sem tags públicas.</span>';
    $("yv-descricao").textContent = v.descricao || "(sem descrição)";
    if (!anterior || anterior.video.id !== v.id) $("yv-transcricao").value = "";
  }
  // Baixa por fetch (e não pelo link direto) para mostrar o erro quando o YouTube não tem miniatura, em vez de falhar calado.
  async function baixarMiniatura(ev) {
    ev.preventDefault();
    const v = estado.video && estado.video.video;
    const info = $("yv-baixar-info");
    if (!v) return;
    try {
      const resp = await fetch(`/api/yt/miniatura?video=${encodeURIComponent(v.id)}`);
      if (!resp.ok) {
        let j = null;
        try { j = await resp.json(); } catch (_) { /* sem corpo JSON */ }
        throw new Error((j && j.erro) || `erro ${resp.status}`);
      }
      const resolucao = resp.headers.get("X-Resolucao") || "miniatura";
      baixar(`${v.id}_${resolucao}.jpg`, await resp.blob(), "image/jpeg");
      msg(info, `Baixada em ${resolucao}.`, true);
    } catch (e) { msg(info, e.message, false); }
  }
  async function analisarVideo() {
    const anterior = estado.video;
    const j = await executar($("yv-analisar"), $("yv-msg"), "Analisando…", () => postYT("/api/yt/video", { video: $("yv-video").value }));
    if (!j) return;
    estado.video = j;
    $("yv-resultado").style.display = "";
    reiniciarIA("engenharia");
    renderVideo(j, anterior);
  }

  // ---------- 6. Histórico ----------
  function listaHistorico() {
    const h = estado.historico;
    if (!h) return [];
    return Y.ordenar(Y.filtrar(h.videos, {}, { formato: $("yh-formato").value }, shortMax()), $("yh-ordem").value, "desc", {});
  }
  function renderHistorico() {
    const h = estado.historico;
    if (!h) return;
    const vis = listaHistorico();
    $("yh-tabela").innerHTML = tabelaHtml(vis, { [h.canal.id]: h.canal });
    $("yh-contagem").textContent = `${vis.length} de ${h.videos.length} vídeos`;
  }
  async function carregarHistorico() {
    const j = await executar($("yh-carregar"), $("yh-msg"), "Carregando…", () => postYT("/api/yt/historico", { canal: $("yh-canal").value, n: 30 }));
    if (!j) return;
    estado.historico = j;
    const c = j.canal, r = j.recentes;
    $("yh-cab").innerHTML = `<div><b><a href="${esc(link(c.url))}" target="_blank" rel="noopener">${esc(c.titulo)}</a></b> ${c.handle ? esc(c.handle) : ""}</div><div class="muted-small">${c.inscritos_ocultos ? "inscritos ocultos" : `${inteiro(c.inscritos)} inscritos`}</div>`;
    $("yh-cards").innerHTML = [cartao("Vídeos lidos", inteiro(r.n)), cartao("Mediana de views", r.mediana_views === null ? null : inteiro(r.mediana_views)), cartao("Média de views", r.media_views === null ? null : inteiro(r.media_views)),
      cartao("Engajamento médio", r.engajamento_medio === null ? null : `${fmt(r.engajamento_medio)}%`), cartao("Vídeos por semana", r.videos_por_semana === null ? null : fmt(r.videos_por_semana), "nos vídeos lidos"),
      cartao("Tração", r.tracao === null ? null : fmt(r.tracao), "mediana ÷ inscritos"), cartao("Dias desde o último", r.dias_desde_o_ultimo === null ? null : inteiro(r.dias_desde_o_ultimo))].join("");
    $("yh-resultado").style.display = "";
    reiniciarIA("auditoria");
    renderHistorico();
  }

  // ---------- montagem ----------
  function mostrarSub(nome) {
    document.querySelectorAll(".yt-sub-btn").forEach((b) => { const ativo = b.dataset.sub === nome; b.classList.toggle("active", ativo); b.setAttribute("aria-selected", String(ativo)); });
    document.querySelectorAll(".yt-painel").forEach((p) => { p.hidden = p.id !== `yt-painel-${nome}`; });
  }

  function iniciar() {
    // chave, short e cota
    const salva = ler(LS.chave);
    if (salva) $("yt-chave").value = salva;
    $("yt-short").value = ler(LS.short) === "180" ? "180" : "60";
    cotaMostrar();
    $("yt-chave").addEventListener("input", () => {
      if (chave()) { guardar(LS.chave, chave()); msg($("yt-chave-msg"), "Chave guardada só neste navegador.", true); } else { apagarChave(LS.chave); msg($("yt-chave-msg"), "", true); }
    });
    $("yt-chave-ver").addEventListener("click", () => { const oculto = $("yt-chave").type === "password"; $("yt-chave").type = oculto ? "text" : "password"; $("yt-chave-ver").textContent = oculto ? "Ocultar" : "Mostrar"; });
    $("yt-chave-esquecer").addEventListener("click", () => { $("yt-chave").value = ""; apagarChave(LS.chave); msg($("yt-chave-msg"), "Chave esquecida.", true); });
    $("yt-cota-zerar").addEventListener("click", () => { apagarChave(LS.cota); cotaMostrar(); });
    $("yt-short").addEventListener("change", () => { guardar(LS.short, $("yt-short").value); renderPesquisa(); renderAlta(); renderHistorico(); if (estado.video) renderVideo(estado.video, estado.video); });
    api("/api/yt/config").then((c) => {
      chaveNoAmbiente = !!c.chave_no_ambiente;
      $("yt-ambiente").textContent = chaveNoAmbiente ? "sim" : "não";
      if (chaveNoAmbiente && !chave()) msg($("yt-chave-msg"), "Sem chave aqui: vou usar a da variável de ambiente YOUTUBE_API_KEY.", true);
    }).catch(() => { $("yt-ambiente").textContent = "—"; });

    document.querySelectorAll(".yt-sub-btn").forEach((b) => b.addEventListener("click", () => mostrarSub(b.dataset.sub)));

    // 1
    preencherSelect($("yp-idioma"), [["", "Qualquer"], ...Y.IDIOMAS]);
    preencherSelect($("yp-pais"), [["", "Qualquer"], ...Y.PAISES]);
    preencherSelect($("yp-ordem"), ORDENS_TABELA);
    $("yp-atalhos").insertAdjacentHTML("beforeend", Y.ATALHOS_DATA.map((a) => `<button type="button" class="yt-atalho-data" data-dias="${a.dias}">${esc(a.rotulo)}</button>`).join(""));
    document.querySelectorAll(".yt-atalho-data").forEach((b) => b.addEventListener("click", () => { $("yp-de").value = Y.dataAtalho(b.dataset.dias, new Date()); $("yp-ate").value = ""; }));
    $("yp-q").addEventListener("input", atualizarCustoPesquisa);
    atualizarCustoPesquisa();
    $("yp-buscar").addEventListener("click", buscar);
    ["yp-f-views", "yp-f-smin", "yp-f-smax", "yp-f-cvmin", "yp-f-cvmax", "yp-f-dmin", "yp-f-dmax", "yp-f-formato", "yp-ordem", "yp-dir"].forEach((id) => $(id).addEventListener("input", renderPesquisa));
    $("yp-csv").addEventListener("click", csvPesquisa);
    $("yp-pdf").addEventListener("click", pdfPesquisa);

    // 2
    preencherSelect($("ya-pais"), Y.PAISES, "BR");
    preencherSelect($("ya-cat"), Y.CATEGORIAS);
    preencherSelect($("ya-dur"), Y.DURACOES_EM_ALTA);
    $("ya-atalhos").insertAdjacentHTML("beforeend", Y.ATALHOS_PAIS.map((a) => `<button type="button" class="yt-atalho-pais" data-codigo="${a.codigo}">${esc(a.rotulo)}</button>`).join(""));
    document.querySelectorAll(".yt-atalho-pais").forEach((b) => b.addEventListener("click", () => { $("ya-pais").value = b.dataset.codigo; }));
    $("ya-carregar").addEventListener("click", carregarAlta);
    ["ya-dur", "ya-ordem", "ya-dir"].forEach((id) => $(id).addEventListener("input", renderAlta));
    montarIA("oportunidades", {
      alvo: "yt-ia-alta", titulo: "Mapear oportunidades dark com IA", placeholder: "Ex.: quero um canal sem rosto, produzindo 3 vídeos por semana",
      ajuda: "Envia a lista que está na tela (já filtrada e ordenada, até 40 vídeos) para a IA apontar nichos em alta e ideias de canal dark. Cada nicho vem com os vídeos da lista que o sustentam.",
      dados: () => { const a = estado.alta; if (!a) return null; const { visiveis } = listaAlta(); const ref = visiveis.slice(0, LIMITE_LISTA_IA); if (!ref.length) return null; return { dados: { videos: ref, canais: a.canais, pais: a.pais, categoria: a.categoria }, ref, extra: { canais: a.canais } }; },
    });

    // 3
    $("yc-comparar").addEventListener("click", comparar);
    const custoC = () => { $("yc-custo").textContent = `Custa cerca de ${Y.custoComparar($("yc-a").value, $("yc-b").value)} unidades.`; };
    ["yc-a", "yc-b"].forEach((id) => $(id).addEventListener("input", custoC));
    custoC();
    montarIA("comparativo", {
      alvo: "yt-ia-comparar", titulo: "Relatório comparativo com IA", placeholder: "Ex.: vou entrar no mesmo nicho e quero saber onde o concorrente é fraco",
      ajuda: "Envia os dois canais, os números lado a lado e os vídeos mais vistos de cada um. A IA compara e aponta oportunidades, sem inventar número.",
      dados: () => (estado.comparar ? { dados: estado.comparar } : null),
    });

    // 4
    $("yk-analisar").addEventListener("click", analisarCanal);
    const custoK = () => { $("yk-custo").textContent = `Custa ${Y.custoCanal($("yk-canal").value)} unidades.`; };
    $("yk-canal").addEventListener("input", custoK);
    custoK();
    montarIA("dossie", {
      alvo: "yt-ia-canal", titulo: "Dossiê do canal com IA", placeholder: "Ex.: penso em copiar o formato deste canal",
      ajuda: "Envia os números do canal, a descrição e as palavras-chave. A IA não viu os vídeos e o prompt a obriga a dizer o que é dedução.",
      dados: () => (estado.canal ? { dados: estado.canal } : null),
    });

    // 5
    $("yv-analisar").addEventListener("click", analisarVideo);
    $("yv-baixar").addEventListener("click", baixarMiniatura);
    montarIA("engenharia", {
      alvo: "yt-ia-video", titulo: "Engenharia reversa do vídeo com IA", placeholder: "Ex.: quero fazer um vídeo parecido sobre outro tema",
      ajuda: "Envia o vídeo, as métricas e a transcrição que você colou acima. Sem transcrição, a IA só vê título, descrição e tags e marca o resto como hipótese.",
      dados: () => (estado.video ? { dados: estado.video, transcricao: $("yv-transcricao").value } : null),
    });

    // 6
    $("yh-carregar").addEventListener("click", carregarHistorico);
    const custoH = () => { $("yh-custo").textContent = `Custa ${Y.custoHistorico($("yh-canal").value)} unidades.`; };
    $("yh-canal").addEventListener("input", custoH);
    custoH();
    ["yh-formato", "yh-ordem"].forEach((id) => $(id).addEventListener("input", renderHistorico));
    montarIA("auditoria", {
      alvo: "yt-ia-historico", titulo: "Auditoria de crescimento com IA", placeholder: "Ex.: o canal parou de crescer em julho e quero entender por quê",
      ajuda: "Envia o histórico completo lido (não só o que o filtro mostra), do mais antigo ao mais novo, para a IA achar padrões de evolução. Vídeos recentes ainda estão juntando views e o prompt avisa isso.",
      dados: () => { const h = estado.historico; if (!h) return null; const ref = [...h.videos].sort((a, b) => String(a.publicado || "").localeCompare(String(b.publicado || ""))); return { dados: { canal: h.canal, videos: h.videos, recentes: h.recentes }, ref }; },
    });
  }

  iniciar();
  window.NicheYTUI = { mostrarSub, estado };
})();
