// Lógica do lado do navegador da aba "API do YouTube". Módulo puro, sem DOM:
// no navegador vira window.NicheYT; no Node, module.exports (usado nos testes).
//
// É aqui que ficam os filtros que a API do YouTube não faz sozinha (views mínimas, faixa de inscritos e de views do
// canal, duração exata) e a classificação de Short, que a API não informa.
(function (raiz) {
  const num = (v) => (v === null || v === undefined || v === "" || typeof v === "boolean" || !Number.isFinite(Number(v))) ? null : Number(v);
  const semAcento = (s) => String(s === null || s === undefined ? "" : s).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

  // O YouTube só chama de Short o vídeo vertical de até 60 s (até 3 min desde out/2024). A API não diz qual é qual,
  // então é uma classificação por duração, com o limite escolhido pelo usuário.
  const SHORT_PADRAO = 60;
  const ehShort = (v, shortMax) => num(v.duracao_seg) !== null && v.duracao_seg > 0 && v.duracao_seg <= (num(shortMax) || SHORT_PADRAO);
  function formatoOk(v, formato, shortMax) {
    if (!formato || formato === "todos") return true;
    if (num(v.duracao_seg) === null || v.duracao_seg <= 0) return false;      // sem duração (ou ao vivo): não dá para dizer
    return formato === "shorts" ? ehShort(v, shortMax) : !ehShort(v, shortMax);
  }

  // ---------- listas de opções ----------
  const PAISES = [["DZ", "Argélia"], ["AR", "Argentina"], ["AU", "Austrália"], ["AT", "Áustria"], ["AZ", "Azerbaijão"], ["BH", "Bahrein"], ["BD", "Bangladesh"], ["BE", "Bélgica"], ["BO", "Bolívia"],
    ["BA", "Bósnia e Herzegovina"], ["BR", "Brasil"], ["BG", "Bulgária"], ["CA", "Canadá"], ["CL", "Chile"], ["CO", "Colômbia"], ["CR", "Costa Rica"], ["HR", "Croácia"], ["CY", "Chipre"], ["CZ", "Tchéquia"],
    ["DK", "Dinamarca"], ["DO", "República Dominicana"], ["EC", "Equador"], ["EG", "Egito"], ["SV", "El Salvador"], ["EE", "Estônia"], ["FI", "Finlândia"], ["FR", "França"], ["GE", "Geórgia"],
    ["DE", "Alemanha"], ["GH", "Gana"], ["GR", "Grécia"], ["GT", "Guatemala"], ["HN", "Honduras"], ["HK", "Hong Kong"], ["HU", "Hungria"], ["IS", "Islândia"], ["IN", "Índia"], ["ID", "Indonésia"],
    ["IQ", "Iraque"], ["IE", "Irlanda"], ["IL", "Israel"], ["IT", "Itália"], ["JM", "Jamaica"], ["JP", "Japão"], ["JO", "Jordânia"], ["KZ", "Cazaquistão"], ["KE", "Quênia"], ["KW", "Kuwait"],
    ["LV", "Letônia"], ["LB", "Líbano"], ["LY", "Líbia"], ["LT", "Lituânia"], ["LU", "Luxemburgo"], ["MY", "Malásia"], ["MT", "Malta"], ["MX", "México"], ["ME", "Montenegro"], ["MA", "Marrocos"],
    ["NP", "Nepal"], ["NL", "Países Baixos"], ["NZ", "Nova Zelândia"], ["NI", "Nicarágua"], ["NG", "Nigéria"], ["MK", "Macedônia do Norte"], ["NO", "Noruega"], ["OM", "Omã"], ["PK", "Paquistão"],
    ["PA", "Panamá"], ["PY", "Paraguai"], ["PE", "Peru"], ["PH", "Filipinas"], ["PL", "Polônia"], ["PT", "Portugal"], ["PR", "Porto Rico"], ["QA", "Catar"], ["RO", "Romênia"], ["SA", "Arábia Saudita"],
    ["SN", "Senegal"], ["RS", "Sérvia"], ["SG", "Singapura"], ["SK", "Eslováquia"], ["SI", "Eslovênia"], ["ZA", "África do Sul"], ["KR", "Coreia do Sul"], ["ES", "Espanha"], ["LK", "Sri Lanka"],
    ["SE", "Suécia"], ["CH", "Suíça"], ["TW", "Taiwan"], ["TZ", "Tanzânia"], ["TH", "Tailândia"], ["TN", "Tunísia"], ["TR", "Turquia"], ["UG", "Uganda"], ["UA", "Ucrânia"], ["AE", "Emirados Árabes Unidos"],
    ["GB", "Reino Unido"], ["US", "Estados Unidos"], ["UY", "Uruguai"], ["VE", "Venezuela"], ["VN", "Vietnã"], ["YE", "Iêmen"], ["ZW", "Zimbábue"]]
    .sort((a, b) => a[1].localeCompare(b[1], "pt-BR"));
  const ATALHOS_PAIS = [{ rotulo: "PT-BR", codigo: "BR" }, { rotulo: "EN-US", codigo: "US" }, { rotulo: "ES", codigo: "ES" }];
  const IDIOMAS = [["pt", "Português"], ["en", "Inglês"], ["es", "Espanhol"], ["fr", "Francês"], ["de", "Alemão"], ["it", "Italiano"], ["ru", "Russo"], ["ja", "Japonês"], ["ko", "Coreano"],
    ["hi", "Hindi"], ["ar", "Árabe"], ["tr", "Turco"], ["pl", "Polonês"], ["nl", "Holandês"], ["id", "Indonésio"], ["vi", "Vietnamita"], ["th", "Tailandês"]];
  const CATEGORIAS = [["", "Todas"], ["1", "Filmes e animação"], ["2", "Carros e veículos"], ["10", "Música"], ["15", "Animais"], ["17", "Esportes"], ["19", "Viagens e eventos"], ["20", "Jogos"],
    ["22", "Pessoas e blogs"], ["23", "Comédia"], ["24", "Entretenimento"], ["25", "Notícias e política"], ["26", "Estilo e como fazer"], ["27", "Educação"], ["28", "Ciência e tecnologia"],
    ["29", "ONGs e ativismo"]];
  const ATALHOS_DATA = [{ rotulo: "7 dias", dias: 7 }, { rotulo: "15 dias", dias: 15 }, { rotulo: "1 mês", dias: 30 }, { rotulo: "3 meses", dias: 90 }, { rotulo: "6 meses", dias: 180 }, { rotulo: "1 ano", dias: 365 }];

  function diaISO(d) {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }
  function dataAtalho(dias, agora) {
    const d = new Date((agora instanceof Date ? agora : new Date()).getTime());
    d.setDate(d.getDate() - Number(dias));
    return diaISO(d);
  }

  // ---------- custo em unidades de cota (estimativa; o servidor devolve o valor real) ----------
  function custoResolver(texto) {
    const t = String(texto || "").trim();
    if (!t || /^UC[\w-]{22}$/.test(t) || /\/channel\/UC[\w-]{22}/.test(t)) return 0;
    if (/\/c\/[^/]+/.test(t)) return 101;                                     // nome personalizado: só a busca resolve
    return 1;                                                                 // @handle e usuário: channels.list
  }
  const custoPesquisa = (q) => (String(q || "").trim() ? 102 : 2);
  const custoComparar = (a, b) => 5 + custoResolver(a) + custoResolver(b);
  const custoCanal = (c) => 1 + custoResolver(c);
  const custoHistorico = (c) => 3 + custoResolver(c);
  const CUSTO_EM_ALTA = 2, CUSTO_VIDEO = 2;

  // Cota da API zera à meia-noite no horário do Pacífico.
  function diaPacifico(agora) {
    return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles", year: "numeric", month: "2-digit", day: "2-digit" }).format(agora instanceof Date ? agora : new Date());
  }
  function somarCota(estado, dia, unidades) {
    const e = estado && estado.dia === dia ? estado : { dia, usadas: 0 };
    return { dia, usadas: e.usadas + Math.max(0, num(unidades) || 0) };
  }

  // ---------- filtros do lado do cliente ----------
  function filtrar(videos, canais, f, shortMax) {
    const c = f || {};
    const tx = semAcento(c.texto).trim();
    const vmin = num(c.viewsMin), smin = num(c.subsMin), smax = num(c.subsMax), cvmin = num(c.canalViewsMin), cvmax = num(c.canalViewsMax);
    const dmin = num(c.duracaoMinSeg), dmax = num(c.duracaoMaxSeg);
    return (videos || []).filter((v) => {
      const canal = (canais || {})[v.canal_id] || null;
      if (tx && !semAcento(v.titulo).includes(tx)) return false;
      if (!formatoOk(v, c.formato, shortMax)) return false;
      if (vmin !== null && !(num(v.views) !== null && v.views >= vmin)) return false;
      if (smin !== null && !(canal && num(canal.inscritos) !== null && canal.inscritos >= smin)) return false;
      if (smax !== null && !(canal && num(canal.inscritos) !== null && canal.inscritos <= smax)) return false;
      if (cvmin !== null && !(canal && num(canal.views_totais) !== null && canal.views_totais >= cvmin)) return false;
      if (cvmax !== null && !(canal && num(canal.views_totais) !== null && canal.views_totais <= cvmax)) return false;
      if (dmin !== null && !(num(v.duracao_seg) !== null && v.duracao_seg >= dmin)) return false;
      if (dmax !== null && !(num(v.duracao_seg) !== null && v.duracao_seg <= dmax)) return false;
      return true;
    });
  }

  // Em alta: 100 mil views para cima e o filtro de duração escolhido.
  const VIEWS_MIN_EM_ALTA = 100000;
  const DURACOES_EM_ALTA = [["todos", "Qualquer duração"], ["shorts", "Shorts"], ["menos5", "Menos de 5 min"], ["mais8", "Mais de 8 min"], ["mais30", "Mais de 30 min"]];
  function filtrarEmAlta(videos, opcoes, shortMax) {
    const o = opcoes || {};
    const minimo = o.viewsMin === undefined ? VIEWS_MIN_EM_ALTA : num(o.viewsMin);
    return (videos || []).filter((v) => {
      if (minimo !== null && !(num(v.views) !== null && v.views >= minimo)) return false;
      const d = num(v.duracao_seg);
      switch (o.duracao) {
        case "shorts": return ehShort(v, shortMax);
        case "menos5": return d !== null && d > 0 && d < 300;
        case "mais8": return d !== null && d > 480;
        case "mais30": return d !== null && d > 1800;
        default: return true;
      }
    });
  }

  // ---------- ordenação ----------
  const CHAVES = {
    engajamento: (v) => num(v.engajamento), views: (v) => num(v.views), likes: (v) => num(v.likes), comentarios: (v) => num(v.comentarios),
    data: (v) => (v.publicado ? Date.parse(v.publicado) : null), views_dia: (v) => num(v.views_dia), duracao: (v) => num(v.duracao_seg),
  };
  // dir: "desc" (padrão) ou "asc". Sem valor vai sempre para o fim; empate mantém a ordem original.
  function ordenar(videos, chave, dir, canais) {
    const lista = (videos || []).slice();
    const valor = chave === "inscritos" ? (v) => { const c = (canais || {})[v.canal_id]; return c ? num(c.inscritos) : null; } : CHAVES[chave];
    if (!valor) return lista;
    const sinal = dir === "asc" ? 1 : -1;
    return lista.map((v, i) => [v, i, valor(v)]).sort((a, b) => {
      if (a[2] === null && b[2] === null) return a[1] - b[1];
      if (a[2] === null) return 1;
      if (b[2] === null) return -1;
      return (sinal * (a[2] - b[2])) || (a[1] - b[1]);
    }).map((p) => p[0]);
  }

  // ---------- exibição e exportação ----------
  function duracaoTexto(seg) {
    const s = num(seg);
    if (s === null) return "—";
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = Math.round(s % 60);
    const dois = (n) => String(n).padStart(2, "0");
    return h ? `${h}:${dois(m)}:${dois(r)}` : `${m}:${dois(r)}`;
  }
  const COLUNAS_CSV = [
    { chave: "titulo", rotulo: "Título" }, { chave: "url", rotulo: "URL" }, { chave: "canal", rotulo: "Canal" }, { chave: "inscritos", rotulo: "Inscritos do canal" },
    { chave: "views_canal", rotulo: "Views totais do canal" }, { chave: "views", rotulo: "Views" }, { chave: "likes", rotulo: "Likes" }, { chave: "comentarios", rotulo: "Comentários" },
    { chave: "engajamento", rotulo: "Engajamento (%)" }, { chave: "views_dia", rotulo: "Views por dia" }, { chave: "duracao", rotulo: "Duração" }, { chave: "formato", rotulo: "Formato" },
    { chave: "data", rotulo: "Publicado em" }, { chave: "idade_dias", rotulo: "Idade (dias)" },
  ];
  // Título e nome de canal são texto de terceiros: no Excel, um que comece com = + - @ vira fórmula. O apóstrofo neutraliza.
  const seguroCsv = (t) => (/^[=+\-@\t\r]/.test(String(t)) ? "'" + t : String(t));
  function linhasCsv(videos, canais, shortMax) {
    return (videos || []).map((v) => {
      const c = (canais || {})[v.canal_id] || {};
      return {
        titulo: seguroCsv(v.titulo || ""), url: v.url || "", canal: seguroCsv(v.canal || ""), inscritos: num(c.inscritos), views_canal: num(c.views_totais), views: num(v.views), likes: num(v.likes),
        comentarios: num(v.comentarios), engajamento: num(v.engajamento), views_dia: num(v.views_dia), duracao: num(v.duracao_seg) === null ? "" : duracaoTexto(v.duracao_seg),
        formato: num(v.duracao_seg) === null || v.duracao_seg <= 0 ? "" : (ehShort(v, shortMax) ? "Short" : "Longo"), data: v.data || "", idade_dias: num(v.idade_dias),
      };
    });
  }

  const API = { SHORT_PADRAO, ehShort, formatoOk, PAISES, ATALHOS_PAIS, IDIOMAS, CATEGORIAS, ATALHOS_DATA, dataAtalho, custoResolver, custoPesquisa, custoComparar, custoCanal,
    custoHistorico, CUSTO_EM_ALTA, CUSTO_VIDEO, diaPacifico, somarCota, filtrar, VIEWS_MIN_EM_ALTA, DURACOES_EM_ALTA, filtrarEmAlta, ordenar, duracaoTexto, COLUNAS_CSV, linhasCsv, seguroCsv, semAcento };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  else raiz.NicheYT = API;
})(typeof window !== "undefined" ? window : globalThis);
