// Ordenação das tabelas de canais (Minerar e Biblioteca).
// Módulo puro (sem DOM): no navegador vira window.NicheOrdenacao; no Node, module.exports (usado nos testes).
(function (raiz) {
  const num = (v) => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v))) ? null : Number(v);
  // Razão só existe quando há vídeos publicados (evita divisão por zero e "infinito").
  const razao = (a, b) => (num(a) !== null && num(b) !== null && num(b) > 0) ? num(a) / num(b) : null;

  // padrao = direção em que o "melhor" vem primeiro. "asc" para vídeos: menos vídeos é melhor na regra do app.
  const METRICAS = {
    padrao: { rotulo: "Regra do app (padrão)", padrao: "desc", valor: null,
      ajuda: "Ordem original da coleta: canais dentro da janela primeiro e, dentro de cada faixa, maior score." },
    inscritos: { rotulo: "Inscritos", padrao: "desc", valor: (c) => num(c.inscritos_num),
      ajuda: "Número de inscritos do canal." },
    videos: { rotulo: "Vídeos publicados", padrao: "asc", valor: (c) => num(c.n_videos),
      ajuda: "Total de vídeos do canal. Por padrão, quem tem menos vídeos vem primeiro." },
    views: { rotulo: "Views totais", padrao: "desc", valor: (c) => num(c.views_totais),
      ajuda: "Total de visualizações do canal (aba Sobre)." },
    views_por_video: { rotulo: "Views por vídeo", padrao: "desc", valor: (c) => razao(c.views_totais, c.n_videos),
      ajuda: "Views totais ÷ vídeos publicados: quanto cada vídeo rendeu em média." },
    inscritos_por_video: { rotulo: "Inscritos por vídeo", padrao: "desc", valor: (c) => razao(c.inscritos_num, c.n_videos),
      ajuda: "Inscritos ÷ vídeos publicados: quanta audiência cada vídeo trouxe." },
    combinada: { rotulo: "Combinada: menos vídeos + mais views + mais inscritos", padrao: "asc", valor: null,
      ajuda: "Média da posição do canal em três listas: mais inscritos, mais views totais e menos vídeos (1 = melhor). Dado ausente conta como a pior posição. Vale só para os canais que estão na tabela." },
    score: { rotulo: "Score (regra do app)", padrao: "desc", valor: (c) => num(c.score),
      ajuda: "Score da regra principal: mais inscritos, menos vídeos e primeiro vídeo mais recente." },
  };
  const ORDEM = ["padrao", "inscritos", "videos", "views", "views_por_video", "inscritos_por_video", "combinada", "score"];

  function normalizar(campo, dir) {
    const c = METRICAS[campo] ? campo : "padrao";
    const d = (dir === "asc" || dir === "desc") ? dir : METRICAS[c].padrao;
    return { campo: c, dir: d };
  }

  // Posição média (1 = melhor) de cada canal em: inscritos (mais), views totais (mais) e vídeos (menos).
  // Empates dividem a melhor posição; dado ausente recebe a pior posição (n) — nunca é tratado como bom.
  function posicaoCombinada(canais) {
    const lista = Array.isArray(canais) ? canais : [];
    const n = lista.length;
    const criterios = [
      { valor: (c) => num(c.inscritos_num), melhor: (a, b) => a > b },
      { valor: (c) => num(c.views_totais), melhor: (a, b) => a > b },
      { valor: (c) => num(c.n_videos), melhor: (a, b) => a < b },
    ];
    const soma = new Map(lista.map((c) => [c, 0]));
    criterios.forEach((cr) => {
      const valores = lista.map(cr.valor);
      lista.forEach((c, i) => {
        const v = valores[i];
        let pos = n;
        if (v !== null) {
          let melhores = 0;
          for (const o of valores) if (o !== null && cr.melhor(o, v)) melhores += 1;
          pos = melhores + 1;
        }
        soma.set(c, soma.get(c) + pos);
      });
    });
    const saida = new Map();
    soma.forEach((s, c) => saida.set(c, s / criterios.length));
    return saida;
  }

  // Devolve uma NOVA lista. Valores ausentes ficam sempre no fim (em qualquer direção); empates mantêm a ordem original.
  function ordenar(canais, campo, dir) {
    const lista = Array.isArray(canais) ? canais.slice() : [];
    const { campo: c, dir: d } = normalizar(campo, dir);
    if (c === "padrao") return lista;
    let valor = METRICAS[c].valor;
    if (c === "combinada") {
      const pos = posicaoCombinada(lista);
      valor = (canal) => pos.get(canal);
    }
    const itens = lista.map((canal, i) => ({ canal, i, v: valor(canal) }));
    itens.sort((a, b) => {
      const an = a.v === null || a.v === undefined;
      const bn = b.v === null || b.v === undefined;
      if (an || bn) return an && bn ? a.i - b.i : (an ? 1 : -1);
      if (a.v !== b.v) return d === "asc" ? a.v - b.v : b.v - a.v;
      return a.i - b.i;
    });
    return itens.map((x) => x.canal);
  }

  const api = { METRICAS, ORDEM, normalizar, ordenar, posicaoCombinada, razao };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else raiz.NicheOrdenacao = api;
})(typeof window !== "undefined" ? window : globalThis);
