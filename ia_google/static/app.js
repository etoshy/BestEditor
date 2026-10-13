const $ = (s) => document.querySelector(s);
const elMsgs = $("#mensagens"), elVazio = $("#vazio"), elInput = $("#pergunta");
const elForm = $("#form"), elEnviar = $("#btnEnviar"), elHist = $("#historico");
const elStatus = $("#status"), elTitulo = $("#tituloConversa"), elContinuar = $("#continuar");

let conversaAtual = null;   // id da conversa no servidor
let somenteLeitura = false; // vendo conversa antiga do histórico
let enviando = false;

// ---------- utilidades ----------
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Markdown -> HTML (subconjunto usado pela IA: títulos, listas, negrito, itálico,
// links, citações, código e tabelas). Escapa tudo antes, então é seguro.
function inlineMd(t) {
  return esc(t)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, (m, txt, url) =>
      `<a href="${url}" target="_blank" rel="noopener">${txt}</a>`);
}

function renderMd(md) {
  const linhas = String(md || "").replace(/\r/g, "").split("\n");
  let html = "", lista = null, para = [];
  const fecharPara = () => { if (para.length) { html += `<p>${inlineMd(para.join(" "))}</p>`; para = []; } };
  const fecharLista = () => { if (lista) { html += `</${lista}>`; lista = null; } };
  for (let i = 0; i < linhas.length; i++) {
    const l = linhas[i], t = l.trim();
    let m;
    if (t.startsWith("```")) {           // bloco de código
      fecharPara(); fecharLista();
      const cod = [];
      while (++i < linhas.length && !linhas[i].trim().startsWith("```")) cod.push(linhas[i]);
      html += `<pre>${esc(cod.join("\n"))}</pre>`;
      continue;
    }
    if (!t) { fecharPara(); fecharLista(); continue; }
    if ((m = t.match(/^(#{1,6})\s+(.*)$/))) {
      fecharPara(); fecharLista();
      const n = Math.min(Math.max(m[1].length, 3), 4);
      html += `<h${n}>${inlineMd(m[2])}</h${n}>`; continue;
    }
    if ((m = t.match(/^>\s?(.*)$/))) { fecharPara(); fecharLista(); html += `<blockquote>${inlineMd(m[1])}</blockquote>`; continue; }
    if (t.startsWith("|") && linhas[i + 1] && /^\s*\|?[\s:-]+\|/.test(linhas[i + 1])) {
      fecharPara(); fecharLista();
      const cel = (x) => x.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      html += "<table><thead><tr>" + cel(t).map((c) => `<th>${inlineMd(c)}</th>`).join("") + "</tr></thead><tbody>";
      i += 2;
      while (i < linhas.length && linhas[i].trim().startsWith("|")) {
        html += "<tr>" + cel(linhas[i]).map((c) => `<td>${inlineMd(c)}</td>`).join("") + "</tr>"; i++;
      }
      i--; html += "</tbody></table>"; continue;
    }
    const ul = t.match(/^[-*•]\s+(.*)$/), ol = t.match(/^\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      fecharPara();
      const tipo = ul ? "ul" : "ol";
      if (lista !== tipo) { fecharLista(); html += `<${tipo}>`; lista = tipo; }
      html += `<li>${inlineMd((ul || ol)[1])}</li>`; continue;
    }
    if (lista && /^\s{2,}/.test(l)) { html = html.replace(/<\/li>$/, " " + inlineMd(t) + "</li>"); continue; }
    fecharLista();
    para.push(t);
  }
  fecharPara(); fecharLista();
  return html;
}

function dominio(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
}

function rolarFim() { elMsgs.scrollTop = elMsgs.scrollHeight; }

async function copiar(texto, botao) {
  try { await navigator.clipboard.writeText(texto); } catch { return; }
  const antes = botao.textContent;
  botao.textContent = "Copiado ✓";
  setTimeout(() => (botao.textContent = antes), 1400);
}

function abrirDialogo(titulo, html) {
  $("#dlgTitulo").textContent = titulo;
  $("#dlgCorpo").innerHTML = html;
  $("#dlg").showModal();
}
$("#dlgFechar").onclick = () => $("#dlg").close();
$("#dlg").addEventListener("close", () => { clearInterval(window._pollLogs); });
$("#dlg").addEventListener("click", (e) => { if (e.target.id === "dlg") $("#dlg").close(); });

// ---------- mensagens ----------
function addUsuario(texto) {
  elVazio.style.display = "none";
  const d = document.createElement("div");
  d.className = "msg-usuario";
  d.innerHTML = `<div>${esc(texto)}</div>`;
  elMsgs.appendChild(d);
  rolarFim();
}

function addCarregando(container) {
  const d = document.createElement("div");
  d.className = "carregando";
  const t0 = Date.now();
  d.innerHTML = `<div class="pontos"><i></i><i></i><i></i></div>
    <span><span class="etapa">Pesquisando no Google…</span> <b>0s</b></span>`;
  const timer = setInterval(async () => {
    d.querySelector("b").textContent = Math.round((Date.now() - t0) / 1000) + "s";
    try {
      const st = await (await fetch("/api/status")).json();
      if (st.etapa) d.querySelector(".etapa").textContent = st.etapa;
    } catch {}
  }, 1000);
  d.parar = () => { clearInterval(timer); d.remove(); };
  if (container) container.prepend(d); else { elMsgs.appendChild(d); rolarFim(); }
  return d;
}

const ROTULO_ORIGEM = { citada_pela_ia: "citada pela IA", link_no_texto: "link no texto", video: "vídeo" };

// se a miniatura falhar, tenta a imagem original; se falhar de novo, mostra só o ícone
function falhaImagem(img) {
  const alt = img.dataset.altSrc;
  if (alt && img.src !== alt) { img.src = alt; img.dataset.altSrc = ""; return; }
  img.parentNode.classList.add("sem-img");
  img.remove();
}

function htmlMidias(m) {
  if (!m) return "";
  let h = "";
  const vids = [...(m.videos || []), ...(m.links_destaque || [])];
  if (vids.length) {
    h += `<div class="fontes-titulo"><span class="rotulo">Vídeos e destaques</span><span class="qtd">${vids.length}</span></div>
      <div class="videos">${vids.map((v) => `
        <a class="video" href="${esc(v.url)}" target="_blank" rel="noopener">
          <div class="thumb">${v.miniatura ? `<img src="${esc(v.miniatura)}" alt="" loading="lazy" onerror="this.remove()">` : ""}
            <span class="play">▶</span>${v.duracao ? `<span class="dur">${esc(v.duracao)}</span>` : ""}</div>
          <div class="info"><div class="tit">${esc(v.titulo || v.url)}</div>
            <div class="sub">${esc([v.canal, v.visualizacoes, v.quando].filter(Boolean).join(" · ") || dominio(v.url))}</div></div>
        </a>`).join("")}</div>`;
  }
  if ((m.produtos || []).length) {
    h += `<div class="fontes-titulo"><span class="rotulo">Produtos citados</span><span class="qtd">${m.produtos.length}</span></div>
      <div class="produtos">${m.produtos.map((p) => `<a class="produto" href="${esc(p.url)}" target="_blank" rel="noopener">🛒 ${esc(p.nome)}</a>`).join("")}</div>`;
  }
  if ((m.imagens || []).length) {
    h += `<div class="fontes-titulo"><span class="rotulo">Imagens</span><span class="qtd">${m.imagens.length}</span></div>
      <div class="imagens">${m.imagens.map((im) => `
        <a class="imagem" href="${esc(im.pagina || im.imagem)}" target="_blank" rel="noopener" title="${esc(im.titulo)}">
          <img src="${esc(im.miniatura || im.imagem)}" data-alt-src="${esc(im.imagem || "")}" alt="" loading="lazy" onerror="falhaImagem(this)">
          <span>${esc(im.site || dominio(im.pagina))}</span>
        </a>`).join("")}</div>`;
  }
  return h;
}

function addResposta(r) {
  const d = document.createElement("div");
  d.className = "msg-ia";

  const fontes = (r.fontes || []).map((f) => {
    const dom = dominio(f.url);
    const ico = dom ? `<img src="https://www.google.com/s2/favicons?domain=${esc(dom)}&sz=32" alt="" loading="lazy" onerror="this.remove()">` : "";
    return `<a class="fonte" href="${esc(f.url)}" target="_blank" rel="noopener">
      <div class="site">${ico}<span>${esc(f.site || dom)}</span></div>
      <div class="tit">${esc(f.titulo || f.url)}</div>
      ${f.trecho ? `<div class="trecho">${esc(f.trecho)}</div>` : ""}
      ${ROTULO_ORIGEM[f.origem] ? `<span class="tag">${ROTULO_ORIGEM[f.origem]}</span>` : ""}
    </a>`;
  }).join("");

  const alertas = [];
  if (r.completa === false) alertas.push("A resposta pode estar incompleta (tempo esgotado).");
  if (r.aviso) alertas.push(r.aviso);
  if (r.formato_respeitado === false && !r.aviso) alertas.push("A IA não seguiu o formato pedido. A resposta objetiva foi tirada do 1º parágrafo.");

  d.innerHTML = `
    <div class="objetiva">
      <span class="rotulo">Resposta objetiva</span>
      <p>${esc(r.resposta_objetiva || "—")}</p>
    </div>
    <details class="completa" open>
      <summary><span class="rotulo">Resposta completa</span></summary>
      <div class="md">${renderMd(r.resposta_completa)}</div>
    </details>
    ${htmlMidias(r.midias)}
    ${fontes ? `<div class="fontes-titulo"><span class="rotulo">Fontes</span><span class="qtd">${r.fontes.length}</span></div>
               <div class="fontes">${fontes}</div>` : ""}
    ${alertas.map((a) => `<div class="alerta">⚠️ ${esc(a)}</div>`).join("")}
    <div class="acoes">
      <button data-a="obj">Copiar objetiva</button>
      <button data-a="md">Copiar markdown</button>
      <button data-a="json">Copiar JSON</button>
      <button data-a="ver">Ver JSON</button>
      ${r.debug && r.debug.html ? `<button data-a="html" title="Baixe e me mande para ajustar o extrator">📄 HTML da página</button>` : ""}
      <span class="meta">${r.tempo_segundos ? r.tempo_segundos + "s · " : ""}${esc((r.data || "").replace("T", " "))}</span>
    </div>`;

  const json = JSON.stringify(r, null, 2);
  const md = `# ${r.pergunta}\n\n## Resposta objetiva\n\n${r.resposta_objetiva}\n\n## Resposta completa\n\n${r.resposta_completa}\n\n## Fontes\n\n` +
    (r.fontes || []).map((f, i) => `${i + 1}. [${f.titulo || f.site}](${f.url}) — ${f.site}`).join("\n");
  d.querySelector('[data-a="obj"]').onclick = (e) => copiar(r.resposta_objetiva, e.target);
  d.querySelector('[data-a="md"]').onclick = (e) => copiar(md, e.target);
  d.querySelector('[data-a="json"]').onclick = (e) => copiar(json, e.target);
  const bHtml = d.querySelector('[data-a="html"]');
  if (bHtml) bHtml.onclick = () => window.open(r.debug.html, "_blank");
  d.querySelector('[data-a="ver"]').onclick = () => abrirDialogo("JSON da resposta", `<pre>${esc(json)}</pre>`);

  elMsgs.appendChild(d);
  rolarFim();
}

// Cartão de erro: o que aconteceu, código, dica, print da tela e detalhes técnicos
function addErro(info, perguntaOriginal, opts = {}) {
  if (typeof info === "string") info = { mensagem: info, codigo: "ERRO" };
  const d = document.createElement("div");
  d.className = "cartao-erro";
  d.innerHTML = `
    <div class="cab"><strong>❌ ${esc(info.mensagem || "Erro")}</strong><span class="codigo">${esc(info.codigo || "ERRO")}</span></div>
    ${info.dica ? `<div class="dica"><b>Como resolver:</b> ${esc(info.dica)}</div>` : ""}
    <div class="acoes">
      ${perguntaOriginal ? `<button class="primario" data-a="tentar">↻ Tentar de novo</button>` : ""}
      ${info.print ? `<button data-a="print">🖼 Ver print da tela</button>` : ""}
      ${info.html ? `<button data-a="html">Abrir HTML salvo</button>` : ""}
      <button data-a="cfg">⚙️ Configurações</button>
      <button data-a="logs">📋 Registro</button>
      ${info.traceback || info.detalhe ? `<button data-a="det">Detalhes técnicos</button>` : ""}
      <span class="meta">${esc(info.quando || "")}</span>
    </div>`;
  const on = (a, fn) => { const b = d.querySelector(`[data-a="${a}"]`); if (b) b.onclick = fn; };
  on("tentar", () => { d.remove(); opts.aoTentar ? opts.aoTentar() : enviar(perguntaOriginal, true); });
  on("print", () => abrirDialogo("Print da tela no momento do erro", `<img class="print-erro" src="${esc(info.print)}">`));
  on("html", () => window.open(info.html, "_blank"));
  on("cfg", abrirConfig);
  on("logs", abrirLogs);
  on("det", () => abrirDialogo("Detalhes técnicos",
    `<p><b>${esc(info.codigo)}</b> — ${esc(info.mensagem)}</p>
     ${info.contexto ? `<p>Contexto: ${esc(info.contexto)}</p>` : ""}
     <h3>Erro original</h3><pre>${esc(info.detalhe || "")}</pre>
     <h3>Traceback</h3><pre>${esc(info.traceback || "")}</pre>`));
  if (opts.container) opts.container.prepend(d); else { elMsgs.appendChild(d); rolarFim(); }
  return d;
}

function limparTela() {
  elMsgs.querySelectorAll(".msg-usuario, .msg-ia, .erro, .cartao-erro, .carregando").forEach((e) => e.remove());
  elVazio.style.display = "";
}

// ---------- ações ----------
async function enviar(texto, repetindo = false) {
  texto = texto.trim();
  if (!texto || enviando) return;
  const link = linkYoutube(texto);
  if (link) return enviarVideoNoChat(texto, link, repetindo);
  if (somenteLeitura) { limparTela(); somenteLeitura = false; conversaAtual = null; }
  enviando = true;
  elEnviar.disabled = true;
  elInput.value = "";
  autoAltura();
  if (!repetindo) addUsuario(texto);
  const load = addCarregando();
  const nova = !conversaAtual || !elContinuar.checked;
  try {
    let resp, r;
    try {
      resp = await fetch("/api/pesquisar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pergunta: texto, nova_conversa: nova }),
      });
      r = await resp.json();
    } catch (e) {
      throw { codigo: "SERVIDOR_OFFLINE", mensagem: "Não consegui falar com o servidor local.",
              dica: "Verifique se o app.py ainda está rodando no terminal (a janela preta não pode ser fechada)." };
    }
    load.parar();
    if (!resp.ok || r.erro) throw (r.detalhes_erro || { codigo: "HTTP_" + resp.status, mensagem: r.erro || resp.statusText });
    conversaAtual = r.conversa_id;
    if (nova) elTitulo.textContent = texto.slice(0, 80);
    addResposta(r);
    carregarHistorico();
  } catch (e) {
    load.parar();
    if (e && e.codigo) addErro(e, texto); else addErro({ codigo: "ERRO_NA_TELA", mensagem: String(e) }, texto);
  } finally {
    enviando = false;
    elEnviar.disabled = false;
    elInput.focus();
  }
}

async function novaConversa() {
  await fetch("/api/nova", { method: "POST" }).catch(() => {});
  conversaAtual = null;
  somenteLeitura = false;
  elTitulo.textContent = "Nova conversa";
  limparTela();
  marcarAtivo(null);
  $("#sidebar").classList.remove("aberta");
  elInput.focus();
}

async function abrirConversa(id) {
  const c = await (await fetch("/api/conversas/" + encodeURIComponent(id))).json();
  limparTela();
  elVazio.style.display = "none";
  (c.mensagens || []).forEach((m) => { addUsuario(m.pergunta); addResposta(m); });
  elTitulo.textContent = c.titulo + "  ·  (histórico)";
  somenteLeitura = true;
  conversaAtual = null;
  marcarAtivo(id);
  $("#sidebar").classList.remove("aberta");
}

function marcarAtivo(id) {
  elHist.querySelectorAll("button").forEach((b) => b.classList.toggle("ativo", b.dataset.id === id));
}

async function carregarHistorico() {
  try {
    const lista = await (await fetch("/api/conversas")).json();
    elHist.innerHTML = lista.length ? "" : `<div class="vazio-hist">Nenhuma conversa ainda</div>`;
    lista.forEach((c) => {
      const b = document.createElement("button");
      b.dataset.id = c.id;
      b.title = c.titulo;
      b.textContent = c.titulo;
      b.onclick = () => abrirConversa(c.id);
      elHist.appendChild(b);
    });
  } catch {}
}

let ultimoStatus = {};
async function atualizarStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    ultimoStatus = s;
    const vis = s.navegador_visivel ? "visível" : "invisível";
    elStatus.className = "status " + (s.ocupado ? "ocupado" : s.ultimo_erro ? "erro" : s.navegador_aberto ? "aberto" : "");
    elStatus.lastChild.textContent = s.ocupado ? " pesquisando…"
      : s.ultimo_erro ? " último: erro (" + s.ultimo_erro.codigo + ")"
      : s.navegador_aberto ? ` navegador aberto · ${vis}` : ` navegador fechado · ${vis}`;
    $("#badgeErro").hidden = !s.ultimo_erro;
  } catch {
    elStatus.className = "status erro";
    elStatus.lastChild.textContent = " servidor offline";
  }
}

// ---------- configurações ----------
const CAMPOS_CFG = [
  { k: "timeout_resposta", t: "Tempo limite da resposta (s)", d: "Quanto tempo esperar a IA terminar de responder.", tipo: "num" },
  { k: "espera_captcha", t: "Esperar captcha (s)", d: "Com o navegador visível, o sistema fica monitorando o captcha e continua sozinho quando você resolve. 0 = espera sem limite.", tipo: "num" },
  { k: "max_perguntas_conversa", t: "Perguntas por conversa", d: "Todas as perguntas vão na mesma conversa do Google (evita captcha). Depois desse número abre uma nova. 0 = sem limite.", tipo: "num" },
  { k: "resolver_links", t: "Descobrir o link real das fontes", d: "Segue os links google.com/goto para achar a URL do site. Desligar deixa mais rápido.", tipo: "bool" },
  { k: "usar_instrucao", t: "Enviar instrução de formato", d: "Pede à IA para responder em RESPOSTA OBJETIVA / COMPLETA / FONTES.", tipo: "bool" },
  { k: "salvar_html_respostas", t: "Salvar HTML de cada resposta", d: "Guarda a página de cada resposta em debug/. Use o botão \"HTML da página\" para me mandar e ajustar o extrator.", tipo: "bool" },
  { k: "salvar_print_erro", t: "Salvar print quando der erro", d: "Guarda print e HTML da página em erros/ para você ver o que aconteceu.", tipo: "bool" },
  { k: "fechar_ocioso_min", t: "Fechar navegador sem uso (min)", d: "Fecha o navegador depois de X minutos parado. 0 = nunca.", tipo: "num" },
];

async function abrirConfig() {
  $("#sidebar").classList.remove("aberta");
  let dados;
  try { dados = await (await fetch("/api/config")).json(); }
  catch { return abrirDialogo("Configurações", `<p class="msg-cfg erro">Servidor offline. Rode o app.py.</p>`); }
  const c = dados.config;
  abrirDialogo("Configurações", `
    <div class="cfg-secao">
      <h3>Navegador</h3>
      <div class="cfg-linha">
        <div class="txt"><b>Modo do navegador</b>
          <small>Visível: você vê a janela e pode resolver captchas (recomendado).<br>
          Invisível: roda escondido, mas o Google pede captcha com mais frequência — quando pedir, a janela reabre visível pra você resolver.</small></div>
        <div class="seg" id="segVis">
          <button data-v="1" class="${c.navegador_visivel ? "on" : ""}">👁 Visível</button>
          <button data-v="0" class="${!c.navegador_visivel ? "on" : ""}">🙈 Invisível</button>
        </div>
      </div>
      <div class="nav-estado" id="navEstado"><i></i><span>…</span></div>
      <div class="botoes">
        <button class="btn" id="btTestar">🔎 Testar navegador</button>
        <button class="btn" id="btReiniciar">↻ Reiniciar</button>
        <button class="btn" id="btFechar">✕ Fechar navegador</button>
      </div>
      <ul class="teste" id="resTeste"></ul>
      <div class="msg-cfg" id="msgNav"></div>
    </div>
    <div class="cfg-secao">
      <h3>Pesquisa</h3>
      ${CAMPOS_CFG.map((f) => `
        <div class="cfg-linha">
          <div class="txt"><b>${f.t}</b><small>${f.d}</small></div>
          ${f.tipo === "num"
            ? `<input type="number" min="0" max="3600" data-k="${f.k}" value="${esc(c[f.k])}">`
            : `<label class="toggle"><input type="checkbox" data-k="${f.k}" ${c[f.k] ? "checked" : ""}><span></span></label>`}
        </div>`).join("")}
    </div>
    <div class="msg-cfg" id="msgCfg"></div>
    <div class="rodape-cfg">
      <button class="btn" id="btPadrao">Restaurar padrão</button>
      <button class="btn primario" id="btSalvar">Salvar</button>
    </div>`);

  let visivel = c.navegador_visivel;
  const seg = $("#segVis");
  seg.querySelectorAll("button").forEach((b) => b.onclick = () => {
    visivel = b.dataset.v === "1";
    seg.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
  });

  const msg = (el, texto, tipo) => { const m = $(el); m.className = "msg-cfg " + (tipo || ""); m.textContent = texto || ""; };

  const pintarEstado = async () => {
    await atualizarStatus();
    const s = ultimoStatus, el = $("#navEstado");
    if (!el) return;
    el.className = "nav-estado " + (s.ocupado ? "ocupado" : s.ultimo_erro ? "erro" : s.navegador_aberto ? "aberto" : "");
    el.lastChild.textContent = (s.ocupado ? "Ocupado: " + (s.etapa || "pesquisando…")
      : s.navegador_aberto ? "Navegador aberto" : "Navegador fechado (abre na próxima pesquisa)")
      + " · modo " + (s.navegador_visivel ? "visível" : "invisível")
      + (s.ultimo_erro ? ` · último erro: ${s.ultimo_erro.codigo}` : "");
  };
  pintarEstado();

  const salvar = async (corpo) => {
    const r = await (await fetch("/api/config", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo) })).json();
    if (r.erro) { msg("#msgCfg", "❌ " + r.erro, "erro"); return null; }
    msg("#msgCfg", "✓ Configurações salvas." + (r.aviso ? " " + r.aviso : ""), "ok");
    pintarEstado();
    return r;
  };

  $("#btSalvar").onclick = () => {
    const corpo = { navegador_visivel: visivel };
    $("#dlgCorpo").querySelectorAll("[data-k]").forEach((i) => corpo[i.dataset.k] = i.type === "checkbox" ? i.checked : Number(i.value));
    salvar(corpo);
  };
  $("#btPadrao").onclick = async () => { if (await salvar({ restaurar_padrao: true })) abrirConfig(); };

  const acao = async (botao, url, textoOk) => {
    const bts = $("#dlgCorpo").querySelectorAll(".botoes .btn");
    bts.forEach((b) => b.disabled = true);
    msg("#msgNav", "Aguarde…");
    $("#resTeste").innerHTML = "";
    try {
      const r = await (await fetch(url, { method: "POST" })).json();
      if (r.passos) {
        $("#resTeste").innerHTML = r.passos.map((p) =>
          `<li>${p.ok ? "✅" : p.aviso ? "⚠️" : "❌"} ${esc(p.passo)}${p.dica ? `<small>${esc(p.dica)}</small>` : ""}</li>`).join("");
        msg("#msgNav", r.ok ? `Tudo certo (${r.tempo_segundos}s).` : "Encontrei problemas. Veja acima.", r.ok ? "ok" : "erro");
      } else if (r.erro) {
        msg("#msgNav", `❌ ${r.erro}${r.detalhes_erro?.dica ? " — " + r.detalhes_erro.dica : ""}`, "erro");
      } else msg("#msgNav", textoOk, "ok");
    } catch { msg("#msgNav", "❌ Servidor offline.", "erro"); }
    bts.forEach((b) => b.disabled = false);
    pintarEstado();
  };
  $("#btTestar").onclick = async () => {
    // salva o modo escolhido antes de testar
    if (visivel !== ultimoStatus.navegador_visivel) await salvar({ navegador_visivel: visivel });
    acao(null, "/api/navegador/testar");
  };
  $("#btReiniciar").onclick = async () => {
    if (visivel !== ultimoStatus.navegador_visivel) await salvar({ navegador_visivel: visivel });
    acao(null, "/api/navegador/reiniciar", "Navegador reiniciado.");
  };
  $("#btFechar").onclick = () => acao(null, "/api/navegador/fechar", "Navegador fechado.");
}

// ---------- registro (logs) ----------
async function abrirLogs() {
  $("#sidebar").classList.remove("aberta");
  await atualizarStatus();
  const e = ultimoStatus.ultimo_erro;
  abrirDialogo("Registro", `
    ${e ? `<div class="cartao-erro erro-ultimo">
        <div class="cab"><strong>Último erro: ${esc(e.mensagem)}</strong><span class="codigo">${esc(e.codigo)}</span></div>
        ${e.dica ? `<div class="dica"><b>Como resolver:</b> ${esc(e.dica)}</div>` : ""}
        ${e.print ? `<a href="${esc(e.print)}" target="_blank" title="Abrir print em tamanho real"><img class="print-erro" src="${esc(e.print)}"></a>` : ""}
        <small style="color:var(--texto-2)">${esc(e.quando)} · ${esc(e.contexto || "")}</small>
      </div>` : `<p class="msg-cfg ok">✓ Nenhum erro recente.</p>`}
    <div class="logs" id="listaLogs"></div>
    <div class="botoes"><button class="btn" id="btLimparLogs">Limpar registro</button></div>`);
  let ultimo = 0;
  const caixa = $("#listaLogs");
  const puxar = async () => {
    try {
      const novos = await (await fetch("/api/logs?depois=" + ultimo)).json();
      if (!novos.length && !ultimo) caixa.innerHTML = `<div><span class="h"></span><span>Nada registrado ainda.</span></div>`;
      if (novos.length && !ultimo) caixa.innerHTML = "";
      novos.forEach((l) => {
        const div = document.createElement("div");
        div.className = l.nivel;
        div.innerHTML = `<span class="h">${esc(l.hora)}</span><span>${esc(l.msg)}</span>`;
        caixa.appendChild(div);
        ultimo = l.id;
      });
      if (novos.length) caixa.scrollTop = caixa.scrollHeight;
    } catch {}
  };
  await puxar();
  clearInterval(window._pollLogs);
  window._pollLogs = setInterval(puxar, 1500);
  $("#btLimparLogs").onclick = async () => { await fetch("/api/logs/limpar", { method: "POST" }); abrirLogs(); };
}

function autoAltura() {
  elInput.style.height = "auto";
  elInput.style.height = Math.min(elInput.scrollHeight, 200) + "px";
}

// ---------- eventos ----------
elForm.addEventListener("submit", (e) => { e.preventDefault(); enviar(elInput.value); });
elInput.addEventListener("input", autoAltura);
elInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); enviar(elInput.value); }
});
document.querySelectorAll(".sugestoes button").forEach((b) => (b.onclick = () => enviar(b.textContent)));
$("#btnNova").onclick = novaConversa;
$("#btnConfig").onclick = abrirConfig;
$("#btnLogs").onclick = abrirLogs;
elStatus.onclick = abrirConfig;
$("#btnMenu").onclick = () => $("#sidebar").classList.toggle("aberta");
$("#btnApi").onclick = () => {
  const base = location.origin;
  abrirDialogo("API local", `
    <p>As mesmas rotas que este chat usa. Funcionam a partir de qualquer programa no seu PC.</p>
    <h3>Pesquisar (POST)</h3>
    <pre>curl -X POST ${base}/api/pesquisar \\
  -H "Content-Type: application/json" \\
  -d '{"pergunta": "qual o dólar hoje", "nova_conversa": true}'</pre>
    <h3>Pesquisar (GET, direto no navegador)</h3>
    <pre>${base}/api/pesquisar?q=qual+o+dólar+hoje&nova=1</pre>
    <h3>Python</h3>
    <pre>import requests
r = requests.post("${base}/api/pesquisar",
                  json={"pergunta": "notícias de IA hoje", "nova_conversa": True},
                  timeout=300).json()
print(r["resposta_objetiva"])
print(r["resposta_completa"])
for f in r["fontes"]:
    print(f["site"], f["url"])</pre>
    <h3>Outras rotas</h3>
    <pre>POST ${base}/api/nova              nova conversa
GET  ${base}/api/conversas         histórico
GET  ${base}/api/conversas/&lt;id&gt;    conversa completa
GET  ${base}/api/status            navegador aberto/ocupado</pre>
    <h3>Campos do JSON</h3>
    <pre>conversa_id, pergunta, resposta_objetiva, resposta_completa (markdown),
fontes [{titulo, site, url, trecho, origem}], formato_respeitado,
completa, data, tempo_segundos</pre>`);
};

// =====================================================================
// VÍDEOS DO YOUTUBE
// =====================================================================
const RE_YT = /(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?[^\s]*v=|shorts\/|live\/|embed\/)|youtu\.be\/)([\w-]{11})[^\s]*/;
const linkYoutube = (t) => { const m = (t || "").match(RE_YT); return m ? m[0] : null; };
const idYoutube = (t) => { const m = (t || "").match(RE_YT); return m ? m[1] : null; };
const fmtSeg = (s) => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`; };

let tarefasVideo = {}, videoAtual = null, tarefaSel = null, ocupadoVideo = false;
const elResVideo = $("#videoResultados");

function htmlResultadoVideo(r) {
  const alertas = [];
  if (r.aviso) alertas.push(r.aviso);
  if (r.completa === false) alertas.push("A resposta pode estar incompleta (tempo esgotado).");
  const fontes = (r.fontes || []).filter((f) => f.url).slice(0, 8)
    .map((f) => `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.titulo || f.site || dominio(f.url))}</a>`).join(" · ");
  return `
    ${r.resposta_objetiva ? `<div class="objetiva"><span class="rotulo">Resposta objetiva</span><p>${esc(r.resposta_objetiva)}</p></div>` : ""}
    <div class="completa"><div class="md">${renderMd(r.markdown || "")}</div></div>
    ${fontes ? `<div class="fontes-linha"><span class="rotulo">Fontes</span> ${fontes}</div>` : ""}
    ${alertas.map((a) => `<div class="alerta">⚠️ ${esc(a)}</div>`).join("")}
    <div class="acoes">
      <button data-a="md">Copiar markdown</button>
      <button data-a="json">Copiar JSON</button>
      <button data-a="ver">Ver JSON</button>
      ${r.debug && r.debug.html ? `<button data-a="html">📄 HTML da página</button>` : ""}
      <span class="meta">${r.tempo_segundos ? r.tempo_segundos + "s · " : ""}${r.tentativas > 1 ? r.tentativas + " tentativas · " : ""}${esc((r.data || "").replace("T", " "))}</span>
    </div>`;
}

function ligarAcoesVideo(el, r) {
  const json = JSON.stringify(r, null, 2);
  const on = (a, fn) => { const b = el.querySelector(`[data-a="${a}"]`); if (b) b.onclick = fn; };
  on("md", (e) => copiar(r.markdown || "", e.target));
  on("json", (e) => copiar(json, e.target));
  on("ver", () => abrirDialogo("JSON da análise", `<pre>${esc(json)}</pre>`));
  on("html", () => window.open(r.debug.html, "_blank"));
}

async function chamarVideo(url, tarefa, consulta, nova) {
  let resp, r;
  try {
    resp = await fetch("/api/video", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, tarefa, consulta, nova_conversa: !!nova }) });
    r = await resp.json();
  } catch {
    throw { codigo: "SERVIDOR_OFFLINE", mensagem: "Não consegui falar com o servidor local.",
            dica: "Verifique se o app.py ainda está rodando." };
  }
  if (!resp.ok || r.erro) throw (r.detalhes_erro || { codigo: "HTTP_" + resp.status, mensagem: r.erro || resp.statusText });
  return r;
}

// ---- no chat: link do YouTube = resumo; link + texto = pergunta sobre o vídeo
async function enviarVideoNoChat(texto, link, repetindo) {
  enviando = true; elEnviar.disabled = true; elInput.value = ""; autoAltura();
  if (!repetindo) addUsuario(texto);
  const resto = texto.replace(link, "").trim();
  const tarefa = resto ? "pergunta" : "resumo";
  const load = addCarregando();
  try {
    const r = await chamarVideo(link, tarefa, resto, false);
    load.parar();
    const d = document.createElement("div");
    d.className = "msg-ia";
    d.innerHTML = `<div class="video-cab"><img src="${esc(r.video.miniatura)}" alt="" onerror="this.remove()">
        <div><span class="rotulo">🎬 ${esc(tarefasVideo[tarefa]?.nome || tarefa)} do vídeo</span>
        <b>${esc(r.video.titulo || r.video.url)}</b>
        <button class="link" data-a="abrir">Abrir na aba Vídeo (player + mais análises) →</button></div></div>` + htmlResultadoVideo(r);
    ligarAcoesVideo(d, r);
    d.querySelector('[data-a="abrir"]').onclick = () => { mostrarAba("video"); carregarVideo(link); };
    elMsgs.appendChild(d); rolarFim();
  } catch (e) {
    load.parar();
    addErro(e && e.codigo ? e : { codigo: "ERRO_NA_TELA", mensagem: String(e) }, texto);
  } finally { enviando = false; elEnviar.disabled = false; elInput.focus(); }
}

// ---- aba Vídeo
function mostrarAba(aba) {
  document.querySelectorAll(".aba").forEach((b) => b.classList.toggle("on", b.dataset.aba === aba));
  const video = aba === "video";
  $("#telaVideo").hidden = !video;
  elMsgs.hidden = video;
  document.querySelectorAll(".so-chat").forEach((e) => (e.hidden = video));
  elTitulo.hidden = video;
  if (video) setTimeout(() => (videoAtual ? null : $("#urlVideo").focus()), 50);
}
document.querySelectorAll(".aba").forEach((b) => (b.onclick = () => mostrarAba(b.dataset.aba)));

function pular(seg) {
  if (!videoAtual) return;
  $("#player").src = `https://www.youtube.com/embed/${videoAtual.id}?start=${Math.max(0, seg | 0)}&autoplay=1&rel=0`;
  $("#player").scrollIntoView({ behavior: "smooth", block: "center" });
}

function carregarVideo(url) {
  const id = idYoutube(url);
  if (!id) { $("#urlVideo").classList.add("invalido"); setTimeout(() => $("#urlVideo").classList.remove("invalido"), 1200); return; }
  const novo = !videoAtual || videoAtual.id !== id;
  videoAtual = { id, url: `https://www.youtube.com/watch?v=${id}` };
  $("#urlVideo").value = videoAtual.url;
  $("#videoVazio").hidden = true;
  $("#videoGrid").hidden = false;
  if (novo) {
    $("#player").src = `https://www.youtube.com/embed/${id}?rel=0`;
    $("#videoInfo").innerHTML = `<a href="${videoAtual.url}" target="_blank" rel="noopener">${videoAtual.url}</a>`;
  }
}
$("#formVideo").addEventListener("submit", (e) => { e.preventDefault(); carregarVideo($("#urlVideo").value); });

function desenharTarefas() {
  $("#tarefas").innerHTML = Object.entries(tarefasVideo).map(([k, t]) =>
    `<button class="tarefa" data-k="${k}" title="${esc(t.descricao)}"><span>${t.icone}</span>${esc(t.nome)}</button>`).join("");
  $("#tarefas").querySelectorAll(".tarefa").forEach((b) => (b.onclick = () => escolherTarefa(b.dataset.k)));
}

function escolherTarefa(k) {
  const t = tarefasVideo[k];
  tarefaSel = k;
  $("#tarefas").querySelectorAll(".tarefa").forEach((b) => b.classList.toggle("sel", b.dataset.k === k));
  if (t.consulta) {
    $("#formConsulta").hidden = false;
    $("#rotuloConsulta").textContent = `${t.icone} ${t.nome}: ${t.consulta}`;
    $("#consultaVideo").placeholder = { momentos: "ex.: quando ele explica o paradoxo de Simpson",
      pergunta: "ex.: qual é a conclusão do autor?", cortes: "ex.: até 60 segundos, sobre estatística",
      traduzir: "ex.: inglês", comparar: "link do outro vídeo", livre: "ex.: liste os erros de português falados" }[k] || "";
    $("#consultaVideo").focus();
  } else {
    $("#formConsulta").hidden = true;
    executarVideo(k, "");
  }
}
$("#formConsulta").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = tarefasVideo[tarefaSel], q = $("#consultaVideo").value.trim();
  if (!q && !t.consulta_opcional) { $("#consultaVideo").classList.add("invalido"); setTimeout(() => $("#consultaVideo").classList.remove("invalido"), 1200); return; }
  executarVideo(tarefaSel, q);
});

async function executarVideo(tarefa, consulta) {
  if (!videoAtual) return;
  if (ocupadoVideo) return abrirDialogo("Aguarde", "<p>Já tem uma análise em andamento. Espere ela terminar.</p>");
  ocupadoVideo = true;
  const t = tarefasVideo[tarefa];
  const load = addCarregando(elResVideo);
  load.querySelector(".etapa").textContent = `${t.icone} ${t.nome}${consulta ? ": " + consulta : ""} — analisando o vídeo…`;
  try {
    const r = await chamarVideo(videoAtual.url, tarefa, consulta, $("#videoNova").checked);
    $("#videoNova").checked = false;
    load.parar();
    if (r.video.titulo) $("#videoInfo").innerHTML = `<b>${esc(r.video.titulo)}</b><span>${esc([r.video.canal, r.video.duracao].filter(Boolean).join(" · "))}</span>`;
    const card = document.createElement("div");
    card.className = "msg-ia cartao-video";
    card.innerHTML = `<div class="cab-tarefa">${t.icone} <b>${esc(t.nome)}</b>${consulta ? ` <span>— ${esc(consulta)}</span>` : ""}</div>` + htmlResultadoVideo(r);
    ligarAcoesVideo(card, r);
    elResVideo.prepend(card);
  } catch (e) {
    load.parar();
    addErro(e && e.codigo ? e : { codigo: "ERRO_NA_TELA", mensagem: String(e) }, consulta || tarefa,
            { container: elResVideo, aoTentar: () => executarVideo(tarefa, consulta) });
  } finally { ocupadoVideo = false; }
}

// clicar num tempo (▶ 1:05) pula o player da aba Vídeo; fora dela abre o YouTube
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[href]");
  if (!a) return;
  const m = a.href.match(/youtu\.be\/([\w-]{11})\?t=(\d+)/);
  if (m && videoAtual && m[1] === videoAtual.id && !$("#telaVideo").hidden) { e.preventDefault(); pular(+m[2]); }
});

fetch("/api/video/tarefas").then((r) => r.json()).then((t) => { tarefasVideo = t; desenharTarefas(); }).catch(() => {});

carregarHistorico();
atualizarStatus();
setInterval(atualizarStatus, 3000);
