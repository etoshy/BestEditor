// Fórmulas do "Método Dark" (aba Método). Módulo puro, sem DOM:
// no navegador vira window.NicheMetodo; no Node, module.exports (usado nos testes).
//
// Tudo aqui vem do roteiro do vídeo. Os limites são heurísticas DO CRIADOR (ele mesmo diz para não levar
// tão a sério) e por isso ficam ajustáveis na interface.
(function (raiz) {
  const num = (v) => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v))) ? null : Number(v);

  // "5 centés" na transcrição = 0,05 (cinco centésimos). Acima de 3, o algoritmo entrega para muita gente.
  const LIMITES_TRACAO = { cuidado: 0.05, forte: 3 };
  const FAIXAS_SATURACAO = { aberto: 5, saturando: 20, sem_regra: 30 };   // vídeos no mês: <5 | 5-20 | 21-30 | >30

  // Mediana, não média: um único vídeo de 200 mil infla a média e esconde os outros outliers do canal.
  function valoresValidos(valores) {
    return (valores || []).map(num).filter((x) => x !== null);
  }
  function mediana(valores) {
    const v = valoresValidos(valores).sort((a, b) => a - b);
    if (!v.length) return null;
    const m = Math.floor(v.length / 2);
    return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
  }
  function media(valores) {
    const v = valoresValidos(valores);
    return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null;
  }

  // Tração = mediana das views dos últimos 10 vídeos ÷ inscritos.
  function tracao(med, inscritos) {
    return num(med) !== null && num(inscritos) !== null && Number(inscritos) > 0 ? Number(med) / Number(inscritos) : null;
  }
  function classificarTracao(t, limites) {
    const l = { ...LIMITES_TRACAO, ...(limites || {}) };
    if (t === null || t === undefined || !Number.isFinite(t)) return { chave: "sem_dado", rotulo: "sem dado" };
    if (t < l.cuidado) return { chave: "cuidado", rotulo: "cuidado" };
    if (t >= l.forte) return { chave: "forte", rotulo: "algoritmo entregando" };
    return { chave: "intermediario", rotulo: "intermediário" };
  }

  // Fator outlier = views do vídeo ÷ mediana dos últimos 10 vídeos do canal.
  function fatorOutlier(views, med) {
    return num(views) !== null && num(med) !== null && Number(med) > 0 ? Number(views) / Number(med) : null;
  }

  // ---------- datas (AAAA-MM-DD, sem fuso: comparamos dias corridos) ----------
  function dataParaDia(iso) {
    const m = /(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
    return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) / 86400000 : null;
  }
  function hojeEmDias(agora) {
    const d = agora instanceof Date ? agora : new Date();
    return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 86400000;
  }
  function diasDesde(iso, agora) {
    const d = dataParaDia(iso);
    return d === null ? null : Math.max(0, hojeEmDias(agora) - d);
  }
  function idadeMeses(iso, agora) {
    const dias = diasDesde(iso, agora);
    return dias === null ? null : dias / 30.4375;
  }

  // Views por hora MÉDIAS desde a postagem. NÃO é o VPH que ele usa (o do VidIQ é o ritmo ATUAL do vídeo: mede
  // as últimas horas). O app só guarda a data, sem hora e sem histórico, então não consegue medir o ritmo atual.
  // Serve só como contexto; o filtro "últimos 30 dias" é o que se aproxima da recomendação dele.
  function viewsPorHoraMedia(views, iso, agora) {
    const dias = diasDesde(iso, agora);
    return num(views) !== null && dias !== null ? Number(views) / (Math.max(dias, 1) * 24) : null;
  }

  // ---------- saturação: quantos vídeos sobre o mesmo título/ângulo saíram no mês ----------
  function semaforoSaturacao(nNoMes) {
    const n = num(nNoMes);
    if (n === null || n < 0) return null;
    if (n < FAIXAS_SATURACAO.aberto) {
      return { chave: "aberto", rotulo: "campo aberto", n,
        texto: "Menos de 5 vídeos no mês. Só é bom sinal se esses poucos tiverem bastante visualização (oceano azul)." };
    }
    if (n <= FAIXAS_SATURACAO.saturando) {
      return { chave: "saturando", rotulo: "saturando", n,
        texto: "Entre 5 e 20 no mês. Se a mediana das views está caindo, o nicho já foi bom e está saturado: só entra quem se diferencia muito, e ele não recomenda para iniciante." };
    }
    if (n <= FAIXAS_SATURACAO.sem_regra) {
      return { chave: "sem_regra", rotulo: "zona sem regra dele", n,
        texto: "Entre 21 e 30. O roteiro não dá regra para essa faixa; trate como saturado até provar o contrário." };
    }
    return { chave: "abandone", rotulo: "abandone", n,
      texto: "Mais de 30 vídeos no mesmo mês: ele diz que nem vale a pena." };
  }

  // ---------- métricas de um canal a partir do que o app já coletou ----------
  // Ordem cronológica só é confiável quando TODOS os vídeos têm data; senão mantém a ordem da coleta.
  function ultimosN(amostra, n) {
    const lista = (Array.isArray(amostra) ? amostra : []).filter((v) => v && num(v.views_num) !== null);
    const todosComData = lista.length > 0 && lista.every((v) => dataParaDia(v.data) !== null);
    const ordenada = todosComData
      ? lista.map((v, i) => [v, i]).sort((a, b) => (dataParaDia(b[0].data) - dataParaDia(a[0].data)) || (a[1] - b[1])).map((p) => p[0])
      : lista;
    return ordenada.slice(0, Math.max(1, Number(n) || 10));
  }

  function metricasCanal(canal, opcoes) {
    const o = { n: 10, fatorMin: 2, so30d: true, limites: LIMITES_TRACAO, agora: undefined, ...(opcoes || {}) };
    const c = canal || {};
    const amostra = Array.isArray(c.amostra_videos) ? c.amostra_videos : [];
    const ultimos = ultimosN(amostra, o.n);
    const views = ultimos.map((v) => Number(v.views_num));
    const med = mediana(views);
    const mean = media(views);
    const insc = num(c.inscritos_num);
    const t = tracao(med, insc);
    const fatores = ultimos.map((v) => fatorOutlier(v.views_num, med)).filter((f) => f !== null);

    const outliers = amostra
      .filter((v) => v && num(v.views_num) !== null)
      .map((v) => {
        const dias = diasDesde(v.data, o.agora);
        return { titulo: v.titulo || "", url: v.url || "", views: Number(v.views_num), data: v.data || "", dias,
          fator: fatorOutlier(v.views_num, med), vph_medio: viewsPorHoraMedia(v.views_num, v.data, o.agora) };
      })
      .filter((x) => x.fator !== null && x.fator >= o.fatorMin && (!o.so30d || (x.dias !== null && x.dias <= 30)))
      .sort((a, b) => b.fator - a.fator);

    return {
      canal: c.canal || "", canal_url: c.canal_url || "", inscritos: insc, n_videos: num(c.n_videos),
      videos_30d: num(c.videos_ultimos_30d), criado_em: c.data_criacao_canal || "", idade_meses: idadeMeses(c.data_criacao_canal, o.agora),
      n_amostra: amostra.length, n_ultimos: views.length, amostra_pequena: views.length < o.n,
      mediana: med, media: mean, media_sobre_mediana: med !== null && med > 0 && mean !== null ? mean / med : null,
      tracao: t, sinal: classificarTracao(t, o.limites),
      maior_fator: fatores.length ? Math.max(...fatores) : null, outliers,
    };
  }

  // ---------- entrada de números digitados ("12 mil", "1,5 mi", "8.443") ----------
  function parseContagem(texto) {
    const s = String(texto === null || texto === undefined ? "" : texto).trim().toLowerCase().replace(/\u00a0/g, " ");
    const m = /^(\d[\d.,]*)\s*(mil|mi|k|m)?$/.exec(s);
    if (!m) return null;
    let n = m[1];
    const suf = m[2] || "";
    const seps = n.match(/[.,]/g) || [];
    if (seps.length > 1 && new Set(seps).size === 1) {
      n = n.replace(/[.,]/g, "");                                   // 1.234.567
    } else if (n.includes(".") && n.includes(",")) {
      n = n.lastIndexOf(",") > n.lastIndexOf(".") ? n.replace(/\./g, "").replace(",", ".") : n.replace(/,/g, "");
    } else if (n.includes(",")) {
      const [l, r] = n.split(",");
      n = (r.length === 3 && !suf) ? l + r : `${l}.${r}`;
    } else if (n.includes(".")) {
      const [l, r] = n.split(".");
      n = (r.length === 3 && !suf) ? l + r : n;
    }
    const v = parseFloat(n);
    if (!Number.isFinite(v)) return null;
    return Math.round(v * ({ mil: 1e3, k: 1e3, mi: 1e6, m: 1e6 }[suf] || 1));
  }
  // Uma contagem por linha ou separada por ponto e vírgula; o que não entende é devolvido em "invalidos".
  function parseLista(texto) {
    const valores = [], invalidos = [];
    String(texto || "").split(/[\n;]+/).map((p) => p.trim()).filter(Boolean).forEach((p) => {
      const v = parseContagem(p);
      if (v === null) invalidos.push(p); else valores.push(v);
    });
    return { valores, invalidos };
  }

  // ---------- CSV (abre certo no Excel: BOM + aspas) ----------
  function csvCelula(v) {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n\r;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }
  function toCsv(colunas, linhas) {
    const cab = colunas.map((c) => csvCelula(c.rotulo)).join(",");
    const corpo = (linhas || []).map((l) => colunas.map((c) => csvCelula(l[c.chave])).join(","));
    return "\ufeff" + [cab, ...corpo].join("\r\n");
  }

  const API = { LIMITES_TRACAO, FAIXAS_SATURACAO, mediana, media, tracao, classificarTracao, fatorOutlier, diasDesde, idadeMeses,
    viewsPorHoraMedia, semaforoSaturacao, ultimosN, metricasCanal, parseContagem, parseLista, toCsv };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  else raiz.NicheMetodo = API;
})(typeof window !== "undefined" ? window : globalThis);
