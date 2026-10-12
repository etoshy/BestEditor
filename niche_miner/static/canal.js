// Explorador de vídeos da aba "Analisar canal". Módulo puro, sem DOM:
// no navegador vira window.NicheCanal; no Node, module.exports (usado nos testes).
//
// Equivalente ao filtro de vídeos do NextLEV (data de upload, pontuação, total de views, exportar CSV/JSON).
// A "pontuação" aqui é o fator outlier: views do vídeo ÷ mediana dos últimos vídeos do canal.
(function (raiz) {
  const num = (v) => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v))) ? null : Number(v);
  const semAcento = (s) => String(s === null || s === undefined ? "" : s).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

  function fatorOutlier(views, mediana) {
    return num(views) !== null && num(mediana) !== null && Number(mediana) > 0 ? Number(views) / Number(mediana) : null;
  }

  // Acrescenta o fator de cada vídeo (a mediana vem do painel do canal).
  function prepararVideos(videos, mediana) {
    return (Array.isArray(videos) ? videos : []).map((v) => ({ ...v, fator: fatorOutlier(v.views, mediana) }));
  }

  // f: { texto, dias, viewsMin, viewsMax, fatorMin, indices }. Campo vazio/null = sem filtro.
  // "dias" é a idade máxima; vídeo sem data não passa quando o filtro de dias está ligado (não dá para saber).
  function filtrar(videos, f) {
    const c = f || {};
    const texto = semAcento(c.texto).trim();
    const dias = num(c.dias), vmin = num(c.viewsMin), vmax = num(c.viewsMax), fmin = num(c.fatorMin);
    const indices = Array.isArray(c.indices) ? new Set(c.indices) : null;
    return (videos || []).filter((v) => {
      if (texto && !semAcento(v.titulo).includes(texto)) return false;
      if (dias !== null && !(num(v.idade_dias) !== null && v.idade_dias <= dias)) return false;
      if (vmin !== null && !(num(v.views) !== null && v.views >= vmin)) return false;
      if (vmax !== null && !(num(v.views) !== null && v.views <= vmax)) return false;
      if (fmin !== null && !(num(v.fator) !== null && v.fator >= fmin)) return false;
      if (indices && !indices.has(v.indice)) return false;
      return true;
    });
  }

  // Ordena do maior para o menor (data: mais recente primeiro). Sem valor vai para o fim; empate mantém a ordem original.
  const CHAVES = {
    views: (v) => num(v.views),
    views_dia: (v) => num(v.views_dia),
    fator: (v) => num(v.fator),
    data: (v) => (v.data ? Date.parse(v.data) : null),
    duracao: (v) => num(v.duracao_seg),
    original: null,
  };
  function ordenar(videos, chave, crescente) {
    const lista = (videos || []).slice();
    const valor = CHAVES[chave];
    if (!valor) return lista;
    const sinal = crescente ? 1 : -1;
    return lista.map((v, i) => [v, i, valor(v)]).sort((a, b) => {
      const x = a[2], y = b[2];
      if (x === null && y === null) return a[1] - b[1];
      if (x === null) return 1;
      if (y === null) return -1;
      return (sinal * (x - y)) || (a[1] - b[1]);
    }).map((p) => p[0]);
  }

  function duracaoTexto(seg) {
    const s = num(seg);
    if (s === null) return "—";
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = Math.round(s % 60);
    const dois = (n) => String(n).padStart(2, "0");
    return h ? `${h}:${dois(m)}:${dois(r)}` : `${m}:${dois(r)}`;
  }

  // Linhas para CSV/JSON (nomes de coluna em português). categorias: { indice: "nome" } opcional.
  const COLUNAS_EXPORT = [
    { chave: "titulo", rotulo: "Título" }, { chave: "url", rotulo: "URL" }, { chave: "views", rotulo: "Views" },
    { chave: "views_dia", rotulo: "Views por dia" }, { chave: "fator", rotulo: "Fator outlier (x a mediana)" },
    { chave: "data", rotulo: "Publicado em" }, { chave: "idade_dias", rotulo: "Idade (dias)" },
    { chave: "duracao", rotulo: "Duração" }, { chave: "categoria", rotulo: "Categoria" },
  ];
  const arred = (n, casas) => (num(n) === null ? null : Math.round(Number(n) * 10 ** casas) / 10 ** casas);
  function linhasExport(videos, categorias) {
    const cats = categorias || {};
    return (videos || []).map((v) => ({
      titulo: v.titulo || "", url: v.url || "", views: num(v.views), views_dia: arred(v.views_dia, 1), fator: arred(v.fator, 2),
      data: v.data || "", idade_dias: num(v.idade_dias), duracao: v.duracao || duracaoTexto(v.duracao_seg).replace("—", ""),
      categoria: cats[v.indice] || "",
    }));
  }

  const API = { fatorOutlier, prepararVideos, filtrar, ordenar, duracaoTexto, linhasExport, COLUNAS_EXPORT, semAcento };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  else raiz.NicheCanal = API;
})(typeof window !== "undefined" ? window : globalThis);
