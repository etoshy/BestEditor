// Biblioteca: histórico de buscas salvas, organizado por tema, com pesquisa por palavra-chave.
// Depende de app.js (carregado antes): el, fetchJson, escapeHtml, formatViews, formatData, safeScore,
// renderUnverifiedTable.
(function () {
  const $ = (id) => document.getElementById(id);
  let listaCarregada = false;
  let listaPromessa = null;
  let buscaAberta = null;   // id da busca exibida no painel de detalhe

  // ---------- abas Minerar / Biblioteca ----------
  function mostrarView(nome) {
    document.querySelectorAll(".topnav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === nome));
    document.querySelectorAll(".view").forEach((v) => { v.style.display = v.id === `view-${nome}` ? "" : "none"; });
    if (nome === "biblioteca" && !listaCarregada) garantirLista();
  }

  document.querySelectorAll(".topnav-btn").forEach((b) => b.addEventListener("click", () => mostrarView(b.dataset.view)));

  // ---------- helpers ----------
  async function getJson(url, options) {
    const resp = await fetch(url, options);
    let dados = null;
    try { dados = await resp.json(); } catch (_) { /* sem corpo JSON */ }
    if (!resp.ok) throw new Error((dados && dados.error) || `erro ${resp.status}`);
    return dados;
  }

  function dataHora(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(iso || "");
    return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : (iso || "?");
  }

  function num(v) { return Number.isFinite(Number(v)) && v !== null && v !== "" ? Number(v).toLocaleString("pt-BR") : "?"; }

  function erro(alvo, e) {
    alvo.innerHTML = `<div class="empty-state">${escapeHtml(e.message || String(e))}</div>`;
  }

  // ---------- lista de temas e buscas ----------
  function garantirLista() {
    if (!listaPromessa) listaPromessa = carregarLista().finally(() => { listaPromessa = null; });
    return listaPromessa;
  }

  async function carregarLista() {
    const alvo = $("lib-list");
    try {
      const dados = await getJson("/api/biblioteca");
      const temas = Array.isArray(dados) ? dados : (dados.temas || []);
      listaCarregada = true;
      renderLista(temas);
    } catch (e) { erro(alvo, e); }
  }

  function renderLista(temas) {
    const alvo = $("lib-list");
    const totalBuscas = temas.reduce((s, t) => s + (t.n_buscas || 0), 0);
    $("lib-resumo").textContent = temas.length
      ? `${temas.length} tema(s) · ${totalBuscas} busca(s) salva(s)` : "";
    if (!temas.length) {
      alvo.innerHTML = '<div class="empty-state">nenhuma busca salva ainda — cada coleta concluída aparece aqui automaticamente</div>';
      return;
    }
    alvo.innerHTML = temas.map((t, i) => {
      const contemAberta = (t.buscas || []).some((b) => b.id === buscaAberta);
      const buscas = (t.buscas || []).map((b) => {
        const termos = (b.termos || []).join(", ");
        return `<button type="button" class="lib-busca${b.id === buscaAberta ? " active" : ""}" data-busca="${escapeHtml(b.id)}">`
          + `#${escapeHtml(b.id)} · ${escapeHtml(dataHora(b.criado_em))}`
          + `<span class="lib-termos">${escapeHtml(termos || "sem termos")}</span>`
          + `<span class="lib-termos">${num(b.n_canais)} canais · ${num(b.n_videos)} vídeos</span></button>`;
      }).join("");
      return `<details class="lib-tema"${(i === 0 || contemAberta) ? " open" : ""}><summary>${escapeHtml(t.tema || "(sem tema)")}`
        + `<span class="muted-small">${t.n_buscas} busca(s) · ${num(t.n_canais)} canais</span></summary>${buscas}</details>`;
    }).join("");
  }

  $("lib-list").addEventListener("click", (ev) => {
    const b = ev.target.closest ? ev.target.closest(".lib-busca") : null;
    if (b) abrirBusca(Number(b.dataset.busca));
  });

  // ---------- detalhe de uma busca ----------
  function tabelaVideos(videos) {
    if (!videos.length) return '<div class="empty-state">nenhum vídeo salvo nesta busca</div>';
    const LIMITE = 500;
    const linhas = videos.slice(0, LIMITE).map((v) => {
      const views = (v.views_num ?? null) !== null ? formatViews(v.views_num) : (v.views_text || "?");
      const data = v.data_publicacao ? formatData(v.data_publicacao) : "?";
      const canal = v.canal_url
        ? `<a href="${escapeHtml(v.canal_url)}" target="_blank" rel="noopener">${escapeHtml(v.canal || "")}</a>`
        : escapeHtml(v.canal || "");
      return `<tr><td class="canal"><a href="${escapeHtml(v.url || "#")}" target="_blank" rel="noopener">${escapeHtml(v.titulo || "sem título")}</a>`
        + `<div class="channel-term">${escapeHtml(v.termo_busca || "")}</div></td>`
        + `<td>${escapeHtml(data)}</td><td>${escapeHtml(views)}</td><td>${canal}${v.canal_verificado ? ' <span class="badge badge-green">verificado</span>' : ""}</td></tr>`;
    }).join("");
    const aviso = videos.length > LIMITE
      ? `<div class="hint">mostrando os ${LIMITE} vídeos com mais views de ${videos.length} — o CSV traz todos.</div>` : "";
    return `${aviso}<div class="table-wrap"><table class="candidate-table" style="min-width:0"><thead><tr><th>Título</th><th>Data</th><th>Views</th><th>Canal</th></tr></thead><tbody>${linhas}</tbody></table></div>`;
  }

  function renderDetalhe(d) {
    const b = d.busca || {};
    const cfg = b.config || {};
    const janela = cfg.janela_meses ? `canal novo: 1º vídeo há até ${cfg.janela_meses} mês(es)` : "sem limite de idade do canal";
    const canais = Array.isArray(d.canais) ? d.canais : [];
    const videos = Array.isArray(d.videos) ? d.videos : [];
    const verificados = Array.isArray(d.verificados) ? d.verificados : [];
    const id = escapeHtml(b.id);

    const verificadosHtml = verificados.length
      ? `<ul class="video-list" style="list-style:none;padding-left:0">${verificados.map((c) =>
        `<li><a href="${escapeHtml(c.canal_url || "#")}" target="_blank" rel="noopener">${escapeHtml(c.canal || "")}</a> `
        + `<span class="popular-meta">${escapeHtml(c.termo_busca || "")}</span></li>`).join("")}</ul>`
      : '<div class="empty-state">nenhum canal verificado nesta busca</div>';

    $("lib-detail").innerHTML = `
      <div class="lib-head">
        <div>
          <h3>${escapeHtml(b.tema || "")}</h3>
          <div class="muted-small">#${id} · ${escapeHtml(dataHora(b.criado_em))} · ${escapeHtml(janela)}</div>
          <div class="muted-small">Termos: ${escapeHtml((b.termos || []).join(", ") || "—")}</div>
          <div class="muted-small">${num(b.n_canais)} canais · ${num(b.n_videos)} vídeos · ${num(b.n_verificados)} verificados</div>
        </div>
        <div class="lib-actions">
          <a href="/api/biblioteca/busca/${id}/canais.csv">CSV dos canais</a>
          <a href="/api/biblioteca/busca/${id}/videos.csv">CSV dos vídeos</a>
          <a href="#" data-excluir-busca="${id}">Excluir busca</a>
        </div>
      </div>
      <div class="section-kicker" style="margin-top:16px">Canais (ordem do ranking)</div>
      ${canais.length ? renderUnverifiedTable(canais, true, { mostrarFora: true }) : '<div class="empty-state">nenhum canal salvo nesta busca</div>'}
      <div class="section-kicker" style="margin-top:16px">Vídeos encontrados</div>
      ${tabelaVideos(videos)}
      <div class="section-kicker" style="margin-top:16px">Canais verificados</div>
      ${verificadosHtml}`;
  }

  async function abrirBusca(id) {
    const alvo = $("lib-detail");
    if (!Number.isFinite(id)) return;
    alvo.innerHTML = '<div class="empty-state">carregando...</div>';
    try {
      const d = await getJson(`/api/biblioteca/busca/${id}`);
      buscaAberta = id;
      renderDetalhe(d);
      document.querySelectorAll(".lib-busca").forEach((n) => n.classList.toggle("active", Number(n.dataset.busca) === id));
    } catch (e) { erro(alvo, e); }
  }

  async function excluirBusca(id) {
    if (!window.confirm(`Excluir a busca #${id} da biblioteca? Isso não pode ser desfeito.`)) return;
    try {
      await getJson(`/api/biblioteca/busca/${id}`, { method: "DELETE" });
      if (buscaAberta === id) {
        buscaAberta = null;
        $("lib-detail").innerHTML = '<div class="empty-state">busca excluída</div>';
      }
      await carregarLista();
    } catch (e) { window.alert(e.message || String(e)); }
  }

  // ---------- pesquisa por palavra-chave ----------
  function renderPesquisa(r) {
    const alvo = $("lib-detail");
    const { buscas = [], canais = [], videos = [] } = r;
    if (!buscas.length && !canais.length && !videos.length) {
      alvo.innerHTML = `<div class="empty-state">nada encontrado para “${escapeHtml(r.q)}”</div>`;
      return;
    }
    const abrir = (bid, txt) => `<a href="#" data-abrir-busca="${escapeHtml(bid)}">${txt}</a>`;
    const secBuscas = buscas.length ? `<div class="section-kicker">Buscas (${buscas.length})</div>` + buscas.map((b) =>
      `<div class="lib-resultado">${abrir(b.id, `#${escapeHtml(b.id)} · ${escapeHtml(b.tema)}`)}`
      + `<span class="muted-small">${escapeHtml(dataHora(b.criado_em))} · termos: ${escapeHtml((b.termos || []).join(", "))}</span></div>`).join("") : "";

    const secCanais = canais.length ? `<div class="section-kicker" style="margin-top:12px">Canais (${canais.length})</div>` + canais.map((c) =>
      `<div class="lib-resultado"><a href="${escapeHtml(c.canal_url || "#")}" target="_blank" rel="noopener">${escapeHtml(c.canal)}</a>`
      + `<span class="muted-small">${num(c.inscritos_num)} inscritos · ${num(c.n_videos)} vídeos · ${escapeHtml(c.frequencia_label || "frequência?")}`
      + ` · 1º vídeo ${c.data_primeiro_video ? escapeHtml(formatData(c.data_primeiro_video)) : "?"}</span>`
      + `<span class="muted-small">tema ${escapeHtml(c.tema)} — ${abrir(c.busca_id, `busca #${escapeHtml(c.busca_id)}`)}</span></div>`).join("") : "";

    const secVideos = videos.length ? `<div class="section-kicker" style="margin-top:12px">Vídeos (${videos.length})</div>` + videos.map((v) =>
      `<div class="lib-resultado"><a href="${escapeHtml(v.url || "#")}" target="_blank" rel="noopener">${escapeHtml(v.titulo || "sem título")}</a>`
      + `<span class="muted-small">${escapeHtml(v.canal || "")} · ${(v.views_num ?? null) !== null ? escapeHtml(formatViews(v.views_num)) : escapeHtml(v.views_text || "?")} views`
      + ` · ${v.data_publicacao ? escapeHtml(formatData(v.data_publicacao)) : "?"}</span>`
      + `<span class="muted-small">tema ${escapeHtml(v.tema)} — ${abrir(v.busca_id, `busca #${escapeHtml(v.busca_id)}`)}</span></div>`).join("") : "";

    alvo.innerHTML = `<div class="hint" style="margin-bottom:8px">Resultados para “${escapeHtml(r.q)}”</div>${secBuscas}${secCanais}${secVideos}`;
  }

  async function pesquisar() {
    const q = $("lib-q").value.trim();
    if (!q) return;
    const alvo = $("lib-detail");
    alvo.innerHTML = '<div class="empty-state">pesquisando...</div>';
    try { renderPesquisa(await getJson(`/api/biblioteca/pesquisar?q=${encodeURIComponent(q)}`)); }
    catch (e) { erro(alvo, e); }
  }

  $("lib-btn-pesquisar").addEventListener("click", pesquisar);
  $("lib-q").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); pesquisar(); } });
  $("lib-btn-limpar").addEventListener("click", () => {
    $("lib-q").value = "";
    buscaAberta = null;
    $("lib-detail").innerHTML = '<div class="empty-state">escolha uma busca ao lado ou pesquise por palavra-chave</div>';
    document.querySelectorAll(".lib-busca").forEach((n) => n.classList.remove("active"));
  });

  // ---------- links vindos de qualquer lugar (aba Minerar, resultados de pesquisa) ----------
  document.addEventListener("click", (ev) => {
    const abrir = ev.target.closest ? ev.target.closest("[data-abrir-busca]") : null;
    if (abrir) {
      ev.preventDefault();
      const id = Number(abrir.dataset.abrirBusca);
      // a busca pode ter sido salva depois do último carregamento da lista
      mostrarView("biblioteca");
      garantirLista().catch(() => {}).then(() => abrirBusca(id));
      return;
    }
    const excluir = ev.target.closest ? ev.target.closest("[data-excluir-busca]") : null;
    if (excluir) { ev.preventDefault(); excluirBusca(Number(excluir.dataset.excluirBusca)); }
  });

  window.Biblioteca = { abrirBusca: (id) => abrirBusca(Number(id)), recarregar: garantirLista, mostrarView };
})();
