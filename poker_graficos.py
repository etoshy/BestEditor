"""
poker_graficos.py — 🎬 peças de documentário em motion graphics (v84_277)
=========================================================================

As telas que aparecem entre as mãos enquanto o narrador conta a história, no tema/cores da mesa:
  • titulo        — abertura de capítulo ("CAPÍTULO 2 · O garoto do Lower East Side")
  • jogador       — cartão do jogador: foto (a do 📷 avatar, se tiver), nome, apelido, país e os números dele
  • linha_do_tempo— a carreira em datas (desenha a linha e cada marco entra na hora)
  • grafico       — fichas ao longo do torneio / ganhos por ano (linha que se desenha; ou barras)
  • citacao       — uma frase dele (ou sobre ele), escrita na tela
  • fato          — um número grande que conta até o valor ("US$ 2,5 milhões") + o contexto
  • midia         — a SUA foto/imagem do bloco, com zoom lento (Ken Burns) e a legenda embaixo
Cada peça dura o que a narração do bloco durar (a montagem passa a duração).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List

import poker_render as PR

TIPOS = {"titulo": "🎬 título de capítulo", "jogador": "🪪 cartão do jogador", "linha_do_tempo": "📅 linha do tempo",
         "grafico": "📈 gráfico (linha)", "barras": "📊 gráfico (barras)", "citacao": "💬 citação", "fato": "🔢 número/fato",
         "midia": "🖼 a sua imagem (Ken Burns)", "gancho": "💥 frase impactante (gancho / final)",
         "": "— nenhuma (foto do jogador citado, se tiver; senão a frase sobre o fundo)"}


def normalizar(g: Any) -> Dict[str, Any]:
    g = g if isinstance(g, dict) else {}
    tipo = str(g.get("tipo") or "").strip().lower().replace(" ", "_")
    tipo = {"timeline": "linha_do_tempo", "linha": "linha_do_tempo", "chart": "grafico", "quote": "citacao", "numero": "fato",
            "card": "jogador", "title": "titulo", "imagem": "midia", "foto": "midia"}.get(tipo, tipo)
    itens = []
    for it in g.get("itens") or []:
        if isinstance(it, dict):
            itens.append({k: str(it.get(k) or "")[:160] for k in ("rotulo", "valor", "ano", "texto")})
    return {"tipo": tipo if tipo in TIPOS else "", "titulo": str(g.get("titulo") or "")[:120], "subtitulo": str(g.get("subtitulo") or "")[:160],
            "texto": str(g.get("texto") or "")[:400], "autor": str(g.get("autor") or "")[:80], "numero": str(g.get("numero") or "")[:40],
            "unidade": str(g.get("unidade") or "")[:20], "pais": str(g.get("pais") or "")[:3].upper(), "itens": itens[:14],
            "arquivo": os.path.basename(str(g.get("arquivo") or ""))[:120]}


# ⏱ tempo mínimo recomendado de cada peça (pra dar tempo de ler/entender, mesmo se a fala for curta)
RITMOS = {"rapido": 0.75, "normal": 1.0, "calmo": 1.35}


def tempo_minimo(g: Any, frase: str = "", ritmo: str = "normal") -> float:
    g = normalizar(g)
    n = len(g["itens"])
    leitura = lambda txt: len(str(txt or "")) / 14.0  # noqa: E731  (~14 letras por segundo)
    t = {"titulo": 4.5 + leitura(g["subtitulo"]) * 0.5,
         "jogador": 4.0 + 1.3 * n,
         "linha_do_tempo": 3.0 + 1.8 * n,
         "grafico": 5.0 + 0.6 * n, "barras": 5.0 + 0.6 * n,
         "citacao": 2.5 + leitura(g["texto"] or frase),
         "fato": 4.5 + leitura(g["texto"]) * 0.6,
         "midia": 4.0 + leitura(g["texto"]) * 0.5,
         "gancho": 2.6 + leitura(g["titulo"] or frase) * 0.8 + leitura(g["subtitulo"]) * 0.6,
         "": 3.0 + leitura(g["titulo"] or g["texto"] or frase) * 0.6}[g["tipo"]]
    return round(max(2.5, t) * RITMOS.get(ritmo, 1.0), 2)


def numero(v: str) -> float:
    """ "US$ 2,5 mi" → 2.5 · "1.200.000" → 1200000 · "34%" → 34."""
    m = re.search(r"-?\d[\d.,]*", str(v or ""))
    if not m:
        return 0.0
    s = m.group(0)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def pagina(g: Dict[str, Any], op: Dict[str, Any], duracao: float, fontes_prefixo: str, foto_url: str = "", midia_url: str = "",
           frase: str = "", modo: str = "gravar") -> str:
    W, H = PR.TAMANHOS[op["formato"]]
    est = PR.ESTETICAS.get(op.get("estetica") or "") or {}
    tema = PR.TEMAS_CSS[est["tema"] if est.get("tema") and not op.get("tema_fixo") else op["tema"]]
    g = normalizar(g)
    for it in g["itens"]:
        it["num"] = numero(it.get("valor"))
    payload = {"W": W, "H": H, "tema": tema, "g": g, "dur": max(1.0, float(duracao)), "foto": foto_url, "midia": midia_url,
               "frase": (frase or "")[:220], "modo": modo, "logo": op.get("logo") or "", "num": numero(g.get("numero")),
               "bandeira": g.get("pais") or ""}
    return (HTML.replace("/*FONTES*/", PR._fontes_css(fontes_prefixo))
            .replace("__DADOS__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__W__", str(W)).replace("__H__", str(H)))


def gravar(g: Dict[str, Any], op: Dict[str, Any], duracao: float, saida: str, foto: str = "", midia: str = "", frase: str = "",
           on_log: Callable[[str], None] = lambda _m: None, parar: Callable[[], bool] = lambda: False) -> str:
    """Grava a peça em MP4 (sem som) com a duração pedida."""
    import shutil
    import tempfile
    op = PR.normalizar(op)
    W, H = PR.TAMANHOS[op["formato"]]
    tmp = tempfile.mkdtemp(prefix="poker_gr_")
    fontes = "file://" + os.path.join(PR.AQUI, "assets", "fonts", "dp").replace("\\", "/")
    url = lambda c: ("file://" + c.replace("\\", "/")) if c and os.path.isfile(c) else ""  # noqa: E731
    try:
        video = os.path.join(tmp, "v.mp4")
        PR.gravar_pagina(pagina(g, op, duracao, fontes, url(foto), url(midia), frase), W, H, int(op["fps"]), duracao, video,
                         on_log, parar, tmp, "🎬 desenhando a peça", 20)
        shutil.copyfile(video, saida)
        return saida
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>peça</title>
<style>
/*FONTES*/
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: __W__px; height: __H__px; overflow: hidden; background: #000; }
body.previa { width: auto; height: auto; background: #0b0b0b; overflow: auto; }
#palco { position: relative; width: __W__px; height: __H__px; overflow: hidden; font-family: 'DP Poppins', 'Segoe UI', Arial, sans-serif; }
body.previa #palco { transform-origin: 0 0; }
.a { position: absolute; }
#controles { position: fixed; left: 0; right: 0; bottom: 0; display: flex; gap: 10px; align-items: center; padding: 8px 12px; background: #000c; color: #fff; font: 14px sans-serif; z-index: 10; }
#controles input[type=range] { flex: 1; }
</style></head><body><div id="palco"></div>
<script>
const D = __DADOS__;
const T = D.tema, W = D.W, H = D.H, G = D.g, DUR = D.dur;
const VERT = H > W * 1.2, S = Math.min(W, H) / 1080;
const palco = document.getElementById('palco');
const el = (tag, css, pai) => { const e = document.createElement(tag); if (css) e.style.cssText = css; (pai || palco).appendChild(e); return e; };
const clamp = (x, a, b) => Math.max(a, Math.min(b, x)), lerp = (a, b, p) => a + (b - a) * p;
const ease = p => p < 0 ? 0 : p > 1 ? 1 : 1 - Math.pow(1 - p, 3);
const fase = (t, a, d) => ease(clamp((t - a) / d, 0, 1));
const saida = t => 1 - fase(t, DUR - 0.45, 0.45);
const numFmt = (v, ref) => { const casas = /[.,]\d/.test(ref || '') ? 1 : 0; return v.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas }); };
const conta = (texto, n, q) => { const m = String(texto || '').match(/-?\d[\d.,]*/); if (!m || /^(1[89]|20)\d\d$/.test(m[0])) return texto; /* ano não conta */ return String(texto).replace(m[0], numFmt(n * q, m[0])); };

// ---- fundo: o gradiente do tema, faixas de luz andando, grão
palco.style.background = `radial-gradient(ellipse at 30% 20%, ${T.fundo2}, ${T.fundo1} 75%)`;
const faixas = [0, 1, 2].map(k => el('div', `left:-30%;top:${-20 + k * 35}%;width:160%;height:${18 + k * 6}%;background:linear-gradient(90deg, transparent, ${T.acento}14, transparent);transform:rotate(-12deg)`));
faixas.forEach(f => f.className = 'a');
const cartasFundo = [];
for (let k = 0; k < 7; k++) {   // naipes flutuando bem de leve atrás
  const c = el('div', `font-size:${(80 + k * 30) * S}px;color:${T.acento};opacity:.06;font-weight:900`); c.className = 'a'; c.textContent = '♠♥♦♣'[k % 4]; cartasFundo.push(c);
}
const grao = (() => { const cv = document.createElement('canvas'); cv.width = cv.height = 160; const g = cv.getContext('2d'), im = g.createImageData(160, 160);
  let s = 3; for (let i = 0; i < im.data.length; i += 4) { s = (s * 16807) % 2147483647; const v = s % 255; im.data[i] = im.data[i + 1] = im.data[i + 2] = v; im.data[i + 3] = 255; }
  g.putImageData(im, 0, 0); const d = el('div', `inset:0;opacity:.06;mix-blend-mode:overlay;background-image:url(${cv.toDataURL()})`); d.className = 'a'; return d; })();
const area = el('div', `inset:0`); area.className = 'a';
const logo = el('div', `right:${40 * S}px;bottom:${30 * S}px;color:${T.acento};opacity:.6;font-weight:800;letter-spacing:.25em;font-size:${22 * S}px`); logo.className = 'a'; logo.textContent = (D.logo || '').toUpperCase();

const TXT = T.texto, AC = T.acento, VAL = T.valor;
let monta = () => {}, anima = () => {};
const F = (px, peso) => `font-size:${px * S}px;font-weight:${peso || 800};color:${TXT};`;

if (G.tipo === 'titulo') {
  const num = el('div', F(VERT ? 34 : 30, 800) + `color:${AC};letter-spacing:.3em;left:${VERT ? 60 : 140}px;top:${H * (VERT ? 0.36 : 0.34)}px`, area); num.className = 'a';
  num.textContent = G.subtitulo && /cap/i.test(G.subtitulo) ? G.subtitulo.toUpperCase() : (G.numero ? 'CAPÍTULO ' + G.numero : '');
  const tit = el('div', F(VERT ? 92 : 104, 900) + `left:${VERT ? 60 : 140}px;top:${H * (VERT ? 0.4 : 0.4)}px;max-width:${W * 0.82}px;line-height:1.05`, area); tit.className = 'a'; tit.textContent = G.titulo || D.frase;
  const bar = el('div', `left:${VERT ? 60 : 140}px;height:${8 * S}px;background:${VAL};border-radius:4px`, area); bar.className = 'a';
  const sub = el('div', F(VERT ? 36 : 34, 600) + `opacity:.85;left:${VERT ? 60 : 140}px;max-width:${W * 0.8}px`, area); sub.className = 'a';
  sub.textContent = /cap/i.test(G.subtitulo || '') ? '' : G.subtitulo;
  anima = t => { const o = saida(t);
    num.style.opacity = fase(t, 0.1, 0.5) * o; num.style.transform = `translateX(${(1 - fase(t, 0.1, 0.6)) * -40 * S}px)`;
    tit.style.clipPath = `inset(0 ${100 - 100 * fase(t, 0.25, 0.9)}% 0 0)`; tit.style.opacity = o;
    const hb = tit.getBoundingClientRect(); bar.style.top = (tit.offsetTop + tit.offsetHeight + 20 * S) + 'px'; bar.style.width = (fase(t, 0.7, 0.6) * Math.min(W * 0.5, tit.offsetWidth)) + 'px'; bar.style.opacity = o;
    sub.style.top = (tit.offsetTop + tit.offsetHeight + 50 * S) + 'px'; sub.style.opacity = fase(t, 1.0, 0.6) * o; };
} else if (G.tipo === 'jogador') {
  const R0 = (VERT ? 230 : 230) * S;
  const foto = el('div', `width:${R0 * 2}px;height:${R0 * 2}px;border-radius:50%;overflow:hidden;border:${8 * S}px solid ${VAL};box-shadow:0 0 ${60 * S}px ${AC}55;background:radial-gradient(circle at 35% 30%, ${AC}, ${T.borda2});display:flex;align-items:center;justify-content:center;${F(R0 * 0.9 / S, 900)}`, area); foto.className = 'a';
  if (D.foto) { const im = el('img', 'width:100%;height:100%;object-fit:cover', foto); im.src = D.foto; } else foto.textContent = (G.titulo || '?')[0].toUpperCase();
  const bx = VERT ? W / 2 : W * 0.25, by = VERT ? H * 0.27 : H * 0.5;
  foto.style.left = (bx - R0) + 'px'; foto.style.top = (by - R0) + 'px';
  const col = el('div', `left:${VERT ? 60 * S : W * 0.45}px;top:${VERT ? H * 0.47 : H * 0.2}px;width:${VERT ? W - 120 * S : W * 0.5}px`, area); col.className = 'a';
  const nome = el('div', F(VERT ? 84 : 92, 900) + 'line-height:1', col);
  nome.textContent = G.titulo + (D.bandeira ? '  ' : '');
  const ap = el('div', F(VERT ? 38 : 36, 600) + `color:${AC};font-style:italic;margin-top:${10 * S}px`, col); ap.textContent = G.subtitulo ? '“' + G.subtitulo + '”' : '';
  const linhas = G.itens.map(it => { const l = el('div', `display:flex;justify-content:space-between;gap:${20 * S}px;padding:${12 * S}px 0;border-bottom:${2 * S}px solid ${T.linha};${F(VERT ? 34 : 32, 600)}`, col);
    const a = el('span', 'opacity:.8', l); a.textContent = it.rotulo || it.ano; const b = el('b', `color:${VAL}`, l); b.textContent = it.valor || it.texto; return { l, b, it }; });
  if (D.bandeira) { const f = el('span', `display:inline-block;margin-left:${16 * S}px;padding:${2 * S}px ${12 * S}px;border-radius:${6 * S}px;background:${AC};color:#111;font-size:.4em;vertical-align:middle`, nome); f.textContent = D.bandeira; }
  anima = t => { const o = saida(t);
    foto.style.transform = `scale(${0.6 + 0.4 * fase(t, 0.05, 0.6)}) rotate(${(1 - fase(t, 0.05, 0.6)) * -12}deg)`; foto.style.opacity = fase(t, 0.05, 0.4) * o;
    nome.style.opacity = fase(t, 0.35, 0.5) * o; nome.style.transform = `translateY(${(1 - fase(t, 0.35, 0.5)) * 30 * S}px)`;
    ap.style.opacity = fase(t, 0.6, 0.5) * o;
    linhas.forEach((x, k) => { const q = fase(t, 0.9 + k * 0.35, 0.5); x.l.style.opacity = q * o; x.l.style.transform = `translateX(${(1 - q) * 40 * S}px)`;
      if (x.it.num) x.b.textContent = conta(x.it.valor, x.it.num, fase(t, 0.9 + k * 0.35, 0.9)); }); };
} else if (G.tipo === 'linha_do_tempo') {
  const n = Math.max(1, G.itens.length);
  const tit = el('div', F(VERT ? 60 : 56, 900) + `left:${60 * S}px;top:${70 * S}px;max-width:${W * 0.85}px`, area); tit.className = 'a'; tit.textContent = G.titulo || 'Linha do tempo';
  const linha = el('div', `background:${AC};border-radius:4px`, area); linha.className = 'a';
  const pts = G.itens.map((it, k) => {
    const p = el('div', `width:${26 * S}px;height:${26 * S}px;border-radius:50%;background:${VAL};box-shadow:0 0 ${20 * S}px ${VAL};transform:translate(-50%,-50%)`, area); p.className = 'a';
    const ano = el('div', F(VERT ? 44 : 40, 900) + `color:${VAL};white-space:nowrap`, area); ano.className = 'a'; ano.textContent = it.ano || it.rotulo;
    const tx = el('div', F(VERT ? 30 : 26, 600) + `max-width:${VERT ? W * 0.62 : Math.min(360 * S, W / Math.min(n, 5) - 30 * S)}px;line-height:1.25`, area); tx.className = 'a'; tx.textContent = it.texto || it.valor;
    return { p, ano, tx };
  });
  const passo = DUR / (n + 1.2);
  anima = t => { const o = saida(t), cam = Math.max(0, Math.min(n - 5, (t / DUR) * (n + 0.4) - 4.6));
    if (VERT) { const x = W * 0.18, y0 = H * 0.24, dy = H * 0.135; linha.style.left = (x - 3 * S) + 'px'; linha.style.width = 6 * S + 'px'; linha.style.top = y0 + 'px';
      linha.style.height = (fase(t, 0.2, DUR * 0.8) * dy * (n - 1 + 0.3)) + 'px'; linha.style.transform = `translateY(${-cam * dy}px)`;
      pts.forEach((q, k) => { const y = y0 + k * dy - cam * dy, a = fase(t, 0.3 + k * passo, 0.5) * o;
        q.p.style.left = x + 'px'; q.p.style.top = y + 'px'; q.p.style.opacity = a; q.p.style.transform = `translate(-50%,-50%) scale(${0.3 + 0.7 * a})`;
        q.ano.style.left = (x + 40 * S) + 'px'; q.ano.style.top = (y - 34 * S) + 'px'; q.ano.style.opacity = a;
        q.tx.style.left = (x + 40 * S) + 'px'; q.tx.style.top = (y + 16 * S) + 'px'; q.tx.style.opacity = a; }); }
    else { const y = H * 0.5, x0 = W * 0.1, dx = W * 0.8 / Math.min(Math.max(n - 1, 1), 4);
      linha.style.top = (y - 3 * S) + 'px'; linha.style.height = 6 * S + 'px'; linha.style.left = x0 + 'px';
      linha.style.width = (fase(t, 0.2, DUR * 0.8) * dx * (n - 1 + 0.3)) + 'px'; linha.style.transform = `translateX(${-cam * dx}px)`;
      pts.forEach((q, k) => { const x = x0 + k * dx - cam * dx, a = fase(t, 0.3 + k * passo, 0.5) * o, cima = k % 2 === 0;
        q.p.style.left = x + 'px'; q.p.style.top = y + 'px'; q.p.style.opacity = a; q.p.style.transform = `translate(-50%,-50%) scale(${0.3 + 0.7 * a})`;
        q.ano.style.left = (x - 20 * S) + 'px'; q.ano.style.top = (cima ? y - 150 * S : y + 30 * S) + 'px'; q.ano.style.opacity = a;
        q.tx.style.left = (x - 20 * S) + 'px'; q.tx.style.top = (cima ? y - 100 * S : y + 82 * S) + 'px'; q.tx.style.opacity = a; }); }
    tit.style.opacity = fase(t, 0, 0.4) * o; };
} else if (G.tipo === 'grafico' || G.tipo === 'barras') {
  const tit = el('div', F(VERT ? 56 : 52, 900) + `left:${60 * S}px;top:${60 * S}px;max-width:${W * 0.85}px`, area); tit.className = 'a'; tit.textContent = G.titulo;
  const sub = el('div', F(28, 600) + `opacity:.8;left:${60 * S}px;top:${(VERT ? 130 : 125) * S}px`, area); sub.className = 'a'; sub.textContent = G.subtitulo;
  const cv = el('canvas', '', area); cv.className = 'a';
  const X0 = 90 * S, Y0 = (VERT ? 260 : 200) * S, CWg = W - 160 * S, CHg = H - Y0 - (VERT ? 260 : 120) * S;
  cv.width = W; cv.height = H; cv.style.left = 0; cv.style.top = 0;
  const g = cv.getContext('2d'), vals = G.itens.map(i => i.num), mx = Math.max(1, ...vals), mn = Math.min(0, ...vals);
  anima = t => { const o = saida(t), q = fase(t, 0.3, Math.max(1, DUR * 0.6)); g.clearRect(0, 0, W, H); g.globalAlpha = o;
    tit.style.opacity = fase(t, 0, 0.4) * o; sub.style.opacity = fase(t, 0.2, 0.4) * o;
    g.strokeStyle = T.linha; g.lineWidth = 2 * S; for (let k = 0; k <= 4; k++) { const y = Y0 + CHg * k / 4; g.beginPath(); g.moveTo(X0, y); g.lineTo(X0 + CWg, y); g.stroke(); }
    const n = vals.length; if (!n) return;
    const px = k => X0 + (n === 1 ? CWg / 2 : CWg * k / (n - 1)), py = v => Y0 + CHg - CHg * (v - mn) / (mx - mn || 1);
    g.font = `600 ${24 * S}px DP Poppins, sans-serif`; g.textAlign = 'center';
    if (G.tipo === 'barras') {
      const bw = CWg / n * 0.6;
      G.itens.forEach((it, k) => { const qq = clamp(q * n - k, 0, 1), x = X0 + CWg * (k + 0.5) / n, h = (CHg * (it.num - mn) / (mx - mn || 1)) * ease(qq);
        g.fillStyle = k === n - 1 ? VAL : AC; g.fillRect(x - bw / 2, Y0 + CHg - h, bw, h);
        g.fillStyle = TXT; g.fillText(it.rotulo || it.ano, x, Y0 + CHg + 36 * S);
        if (qq > 0.5) { g.fillStyle = VAL; g.font = `800 ${26 * S}px DP Poppins, sans-serif`; g.fillText(conta(it.valor, it.num, ease(qq)), x, Y0 + CHg - h - 14 * S); g.font = `600 ${24 * S}px DP Poppins, sans-serif`; } });
    } else {
      const ate = q * (n - 1);
      g.strokeStyle = AC; g.lineWidth = 7 * S; g.lineJoin = 'round'; g.shadowColor = AC; g.shadowBlur = 18 * S; g.beginPath();
      for (let k = 0; k <= Math.floor(ate); k++) { const x = px(k), y = py(vals[k]); k ? g.lineTo(x, y) : g.moveTo(x, y); }
      if (ate % 1 > 0 && Math.floor(ate) + 1 < n) { const k = Math.floor(ate), f = ate % 1; g.lineTo(lerp(px(k), px(k + 1), f), lerp(py(vals[k]), py(vals[k + 1]), f)); }
      g.stroke(); g.shadowBlur = 0;
      G.itens.forEach((it, k) => { if (k > ate + 0.01) return; const x = px(k), y = py(it.num), ult = k === n - 1 || k === Math.floor(ate);
        g.fillStyle = ult ? VAL : AC; g.beginPath(); g.arc(x, y, (ult ? 12 : 8) * S, 0, 2 * Math.PI); g.fill();
        g.fillStyle = TXT; g.fillText(it.rotulo || it.ano, x, Y0 + CHg + 36 * S);
        if (ult || n <= 6) { g.fillStyle = VAL; g.font = `800 ${(ult ? 30 : 22) * S}px DP Poppins, sans-serif`; g.fillText(it.valor, x, y - 22 * S); g.font = `600 ${24 * S}px DP Poppins, sans-serif`; } });
    }
    g.globalAlpha = 1; };
} else if (G.tipo === 'citacao') {
  const aspas = el('div', F(VERT ? 300 : 320, 900) + `color:${AC};opacity:.35;left:${70 * S}px;top:${H * 0.12}px;line-height:1`, area); aspas.className = 'a'; aspas.textContent = '“';
  const tx = el('div', F(VERT ? 58 : 60, 700) + `left:${120 * S}px;top:${H * (VERT ? 0.3 : 0.3)}px;max-width:${W - 240 * S}px;line-height:1.25`, area); tx.className = 'a';
  const au = el('div', F(VERT ? 36 : 34, 600) + `color:${VAL};left:${120 * S}px`, area); au.className = 'a'; au.textContent = G.autor ? '— ' + G.autor : '';
  const texto = G.texto || D.frase;
  anima = t => { const o = saida(t), q = fase(t, 0.3, Math.min(DUR * 0.6, texto.length * 0.045));
    aspas.style.opacity = 0.35 * fase(t, 0, 0.5) * o; tx.textContent = texto.slice(0, Math.round(texto.length * clamp((t - 0.3) / Math.min(DUR * 0.6, texto.length * 0.045), 0, 1)));
    tx.style.opacity = o; au.style.top = (tx.offsetTop + tx.offsetHeight + 30 * S) + 'px'; au.style.opacity = fase(t, 0.4 + Math.min(DUR * 0.6, texto.length * 0.045), 0.5) * o; };
} else if (G.tipo === 'fato') {
  const nm = el('div', F(VERT ? 150 : 190, 900) + `color:${VAL};left:50%;top:${H * 0.34}px;transform:translateX(-50%);white-space:nowrap;text-shadow:0 0 ${40 * S}px ${VAL}66`, area); nm.className = 'a';
  const tx = el('div', F(VERT ? 46 : 46, 700) + `left:50%;top:${H * (VERT ? 0.5 : 0.6)}px;transform:translateX(-50%);text-align:center;width:${W * 0.8}px;line-height:1.25`, area); tx.className = 'a'; tx.textContent = G.texto || G.titulo || D.frase;
  anima = t => { const o = saida(t); nm.textContent = D.num ? conta(G.numero, D.num, fase(t, 0.2, Math.min(1.8, DUR * 0.5))) : G.numero;
    nm.style.opacity = fase(t, 0.1, 0.4) * o; nm.style.transform = `translateX(-50%) scale(${0.8 + 0.2 * fase(t, 0.1, 0.6)})`;
    tx.style.opacity = fase(t, 0.9, 0.6) * o; };
} else if (G.tipo === 'gancho') {
  // 💥 a frase que prende (ou fecha): as palavras entram uma a uma com soco, a última no destaque, tremida + flash
  const frase = (G.titulo || D.frase || '').trim(), pal = frase.split(/\s+/);
  const caixa = el('div', `left:50%;top:${H * (VERT ? 0.42 : 0.42)}px;transform:translate(-50%,-50%);width:${W * 0.88}px;text-align:center;line-height:1.05`, area); caixa.className = 'a';
  const spans = pal.map((w, k) => { const sp = el('span', F(VERT ? 104 : 112, 900) + `display:inline-block;margin:0 ${12 * S}px;text-transform:uppercase;text-shadow:0 ${8 * S}px ${30 * S}px #000;color:${k === pal.length - 1 ? VAL : TXT}`, caixa); sp.textContent = w; return sp; });
  const sub = el('div', F(VERT ? 40 : 38, 700) + `left:50%;transform:translateX(-50%);width:${W * 0.8}px;text-align:center;opacity:0`, area); sub.className = 'a'; sub.textContent = G.subtitulo;
  const au = el('div', F(VERT ? 30 : 28, 600) + `color:${AC};left:50%;transform:translateX(-50%);text-align:center;width:${W * 0.8}px`, area); au.className = 'a'; au.textContent = G.autor ? '— ' + G.autor : '';
  const flash = el('div', 'inset:0;background:#fff;opacity:0;mix-blend-mode:overlay', area); flash.className = 'a';
  const passo = Math.min(0.32, Math.max(0.12, (DUR * 0.45) / Math.max(1, pal.length)));
  anima = t => { const o = saida(t);
    spans.forEach((sp, k) => { const q = clamp((t - 0.15 - k * passo) / 0.22, 0, 1), soco = 1 + 0.6 * Math.pow(1 - q, 3);
      sp.style.opacity = (q > 0 ? 1 : 0) * o; sp.style.transform = `scale(${soco}) rotate(${(1 - q) * (k % 2 ? 4 : -4)}deg)`; });
    const fimP = 0.15 + pal.length * passo, tre = t > fimP && t < fimP + 0.25 ? 1 : 0;
    caixa.style.transform = `translate(-50%,-50%) translate(${tre * Math.sin(t * 97) * 8 * S}px, ${tre * Math.cos(t * 83) * 6 * S}px) scale(${1 + 0.03 * clamp((t - fimP) / DUR, 0, 1)})`;
    flash.style.opacity = Math.max(0, 0.5 - Math.abs(t - fimP) * 3) * o;
    sub.style.top = (caixa.offsetTop + caixa.offsetHeight / 2 + 40 * S) + 'px'; sub.style.opacity = fase(t, fimP + 0.2, 0.4) * o;
    au.style.top = (caixa.offsetTop + caixa.offsetHeight / 2 + 110 * S) + 'px'; au.style.opacity = fase(t, fimP + 0.4, 0.4) * o; };
} else if (G.tipo === 'midia' && D.midia) {
  const im = el('img', `left:0;top:0;width:${W}px;height:${H}px;object-fit:cover`, area); im.className = 'a'; im.src = D.midia;
  const sombra = el('div', `left:0;right:0;bottom:0;height:${H * 0.35}px;background:linear-gradient(transparent, #000c)`, area); sombra.className = 'a';
  const leg = el('div', F(VERT ? 44 : 40, 700) + `left:${60 * S}px;bottom:${(VERT ? 220 : 70) * S}px;max-width:${W - 120 * S}px;line-height:1.25`, area); leg.className = 'a'; leg.textContent = G.texto || G.titulo || '';
  const dirx = (G.titulo.length % 2 ? 1 : -1);
  anima = t => { const q = t / DUR, o = saida(t); im.style.transform = `scale(${1.05 + 0.12 * q}) translate(${dirx * q * 2}%, ${-q * 1.5}%)`; im.style.opacity = fase(t, 0, 0.5) * o;
    leg.style.opacity = fase(t, 0.6, 0.6) * o; leg.style.transform = `translateY(${(1 - fase(t, 0.6, 0.6)) * 20 * S}px)`; };
} else {   // sem peça: a frase-chave do bloco sobre o fundo animado
  const tx = el('div', F(VERT ? 64 : 62, 800) + `left:50%;top:50%;transform:translate(-50%,-50%);text-align:center;width:${W * 0.78}px;line-height:1.25`, area); tx.className = 'a';
  tx.textContent = G.titulo || G.texto || D.frase;
  anima = t => { const o = saida(t); tx.style.opacity = fase(t, 0.2, 0.6) * o; tx.style.transform = `translate(-50%,-50%) scale(${0.96 + 0.04 * fase(t, 0.2, 1.2) + 0.02 * t / DUR})`; };
}

window.render = function (t) {
  faixas.forEach((f, k) => f.style.transform = `rotate(-12deg) translateX(${((t * (20 + k * 8)) % 100) - 50}%)`);
  cartasFundo.forEach((c, k) => { c.style.left = ((k * 17 + 5) % 100) + '%'; c.style.top = (((k * 29 + 10) % 90) + Math.sin(t * 0.4 + k) * 3) + '%'; c.style.transform = `rotate(${Math.sin(t * 0.3 + k) * 12}deg)`; });
  grao.style.backgroundPosition = `${(Math.floor(t * 12) * 37) % 160}px ${(Math.floor(t * 12) * 71) % 160}px`;
  anima(t);
};
const comeca = () => { window.render(0); window.pronto = true; previa(); };
const imgs = [...document.images]; let falta = imgs.length;
if (!falta) comeca(); else imgs.forEach(im => { if (im.complete) { if (--falta === 0) comeca(); } else { im.onload = im.onerror = () => { if (--falta === 0) comeca(); }; } });
function previa() {
  if (D.modo !== 'previa') return;
  document.body.className = 'previa';
  const ctl = el('div', '', document.body); ctl.id = 'controles';
  const bt = el('button', '', ctl); bt.textContent = '⏸';
  const rg = el('input', '', ctl); rg.type = 'range'; rg.min = 0; rg.max = DUR; rg.step = 0.01; rg.value = 0;
  let tocando = true, t0 = performance.now(), base = 0;
  const ajustar = () => { const e = Math.min(innerWidth / W, (innerHeight - 44) / H); palco.style.transform = `scale(${e})`; };
  ajustar(); addEventListener('resize', ajustar);
  bt.onclick = () => { tocando = !tocando; bt.textContent = tocando ? '⏸' : '▶'; base = +rg.value; t0 = performance.now(); };
  rg.oninput = () => { base = +rg.value; t0 = performance.now(); window.render(base); };
  const laco = () => { if (tocando) { let t = base + (performance.now() - t0) / 1000; if (t > DUR + 0.3) { base = 0; t0 = performance.now(); t = 0; } rg.value = t; window.render(t); } requestAnimationFrame(laco); };
  requestAnimationFrame(laco);
}
</script></body></html>"""
