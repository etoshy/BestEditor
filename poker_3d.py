"""
poker_3d.py — 🎲 modo 3D da mesa (estilo "Buckshot Roulette") (v84_277)
=========================================================================

A mesma mão (poker_mesa.simular) vista em primeira pessoa: a câmera fica sentada no lugar do jogador observado,
olhando a mesa de cima pra baixo, e quando a vista troca ela levanta e dá a volta até a cadeira do outro.
Tudo é 3D de verdade (projeção em perspectiva feita aqui, num <canvas>, sem biblioteca):
  • mesa oval com borda, feltro iluminado pela luminária pendurada, logo no feltro (gira junto);
  • cartas deitadas na mesa (distribuídas voando do dealer, viram com giro de verdade, quem desiste joga no muck);
    as do jogador da vista ficam "na mão", levantadas na frente da câmera;
  • fichas em pilhas 3D que deslizam pra aposta, pro pote e pro vencedor; botão do dealer;
  • os outros jogadores sentados do outro lado — a imagem do personagem (gerada no 🎨 Flow) ou um genérico no
    mesmo estilo (figura mascarada, sombria), virado pra câmera;
  • a sala em volta (tábuas, luminária) que se move com a câmera (dá a noção de espaço);
  • acabamento "buckshot": baixa resolução + pixel, paleta escura, dither, grão e vinheta — ou "limpo".
Os textos (nomes, stacks, ações, pote) ficam na tela, por cima, no mesmo estilo pixel.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict

import poker_render as PR

ESTILOS_3D = {"buckshot": "🩸 Buckshot (pixel escuro, grão, dither)", "limpo": "✨ limpo (resolução cheia)"}


def pagina(dados: Dict[str, Any], op: Dict[str, Any], fontes_prefixo: str, personagem_url: Callable[[str], str],
           modo: str = "gravar") -> str:
    W, H = PR.TAMANHOS[op["formato"]]
    est = PR.ESTETICAS.get(op.get("estetica") or dados.get("estetica") or "") or {}
    tema = PR.TEMAS_CSS[est["tema"] if est.get("tema") and not op.get("tema_fixo") else op["tema"]]
    js = [{"nome": j["nome"], "cartas": j["cartas"], "heroi": j["heroi"], "pais": j.get("pais") or "",
           "personagem": personagem_url(j["nome"]) or ""} for j in dados["jogadores"]]
    payload = {"W": W, "H": H, "tema": tema, "op": op, "jogadores": js, "posicoes": dados["posicoes"], "botao": dados["botao"],
               "eventos": dados["eventos"], "duracao": dados["duracao"], "unidade": dados["unidade"], "titulo": dados.get("titulo") or "",
               "inicial": dados["inicial"], "modo": modo, "ncartas": dados.get("ncartas") or 2, "abertas": dados.get("abertas") or [], "estrategia": bool(dados.get("estrategia")), "zooms": dados.get("zooms") or [],
               "emocoes": dados.get("emocoes") or [], "mostrares": dados.get("mostrares") or [], "mostrar": dados.get("mostrar") or "",
               "gancho": dados.get("gancho") or "", "ritmo": dados.get("ritmo") or "normal", "dinheiro": dados.get("dinheiro") or "",
               "variante_nome": dados.get("variante_nome") or "", "variante": dados.get("variante") or "holdem"}
    return (HTML.replace("/*FONTES*/", PR._fontes_css(fontes_prefixo))
            .replace("__DADOS__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__W__", str(W)).replace("__H__", str(H)))


def gravar(dados: Dict[str, Any], op: Dict[str, Any], saida: str, on_log: Callable[[str], None] = lambda _m: None,
           pasta_personagens: str = "", parar: Callable[[], bool] = lambda: False) -> str:
    import shutil
    import tempfile
    op = PR.normalizar(op)
    W, H = PR.TAMANHOS[op["formato"]]
    tmp = tempfile.mkdtemp(prefix="poker3d_")
    fontes = "file://" + os.path.join(PR.AQUI, "assets", "fonts", "dp").replace("\\", "/")

    def url(nome: str) -> str:
        if not pasta_personagens:
            return ""
        import poker_rotas as R
        arq = R.personagem_arquivo(pasta_personagens, nome)
        return ("file://" + os.path.join(pasta_personagens, arq).replace("\\", "/")) if arq else ""
    try:
        video = os.path.join(tmp, "video.mp4")
        PR.gravar_pagina(pagina(dados, op, fontes, url, "gravar"), W, H, int(op["fps"]), dados["duracao"] + 0.4, video,
                         on_log, parar, tmp, "🎲 desenhando a mesa 3D", 23)
        audio = PR.trilha_sons(dados, os.path.join(tmp, "sons.wav"), tmp, op.get("estilo") == "shorts") if op.get("sons") else None
        on_log("🔊 juntando os sons…" if audio else "📦 finalizando…")
        return PR.juntar_audio(video, audio, saida)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>mesa 3d</title>
<style>
/*FONTES*/
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: __W__px; height: __H__px; overflow: hidden; background: #000; }
body.previa { width: auto; height: auto; background: #0b0b0b; overflow: auto; }
#palco { position: relative; width: __W__px; height: __H__px; overflow: hidden; background: #000; }
body.previa #palco { transform-origin: 0 0; }
#c { position: absolute; left: 0; top: 0; width: __W__px; height: __H__px; image-rendering: pixelated; image-rendering: crisp-edges; }
#controles { position: fixed; left: 0; right: 0; bottom: 0; display: flex; gap: 10px; align-items: center; padding: 8px 12px; background: #000c; color: #fff; font: 14px sans-serif; z-index: 10; }
#controles input[type=range] { flex: 1; }
</style></head><body><div id="palco"><canvas id="c"></canvas></div>
<script>
const D = __DADOS__;
const OP = D.op, T = D.tema, W = D.W, H = D.H, N = D.jogadores.length, NC = D.ncartas || 2, EV = D.eventos;
const LIMPO = OP.estilo3d === 'limpo';
const PX = LIMPO ? 1 : 3;                                   // buckshot: desenha em 1/3 da resolução e amplia em pixel
const cw = Math.round(W / PX), ch = Math.round(H / PX);
const cv = document.getElementById('c'); cv.width = cw; cv.height = ch;
const ctx = cv.getContext('2d');
const VERT = H > W * 1.2;
const UI = ch / (VERT ? 640 : 360);                          // escala dos textos (na resolução interna)
const SH = D.ritmo === 'shorts' || OP.estilo === 'shorts';
const PI = Math.PI, lerp = (a, b, p) => a + (b - a) * p, clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const ease = p => p < 0 ? 0 : p > 1 ? 1 : (p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
const UNI = String(D.unidade || 'bb'), UNI_L = UNI.toLowerCase();
const num = v => { const s = (Math.abs(v - Math.round(v)) < 1e-9 ? String(Math.round(v)) : String(Math.round(v * 100) / 100)); return s.replace('.', ','); };
const curto = v => { const a = Math.abs(v); if (a >= 1e6) return num(Math.round(v / 1e4) / 100) + 'M'; if (a >= 1e4) return num(Math.round(v / 100) / 10) + 'K'; return num(v); };
const fmt = v => { v = Math.round(v * 100) / 100; if (UNI_L === 'bb') return num(v) + ' BB';
  if (['$', 'us$', 'r$', '€', '£', 'eur', 'usd', 'brl'].includes(UNI_L)) { const pre = { usd: 'US$', brl: 'R$', eur: '€' }[UNI_L] || UNI; return pre + (pre.length > 1 ? ' ' : '') + curto(v); }
  return curto(v); };
const FONTE = "'DP Poppins','Segoe UI',Arial,sans-serif";

// ------------------------------------------------------------------ vetores e câmera
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]], add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k], dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
const lerp3 = (a, b, p) => [lerp(a[0], b[0], p), lerp(a[1], b[1], p), lerp(a[2], b[2], p)];
let E = [0, 1, -2], CF = [0, 0, 1], CR = [1, 0, 0], CU = [0, 1, 0], FOC = 300;
function setCam(eye, alvo, fov) { E = eye; CF = norm(sub(alvo, eye)); CR = norm(cross([0, 1, 0], CF)); CU = cross(CF, CR); FOC = (ch / 2) / Math.tan(fov * PI / 360); }
function P(p) { const d = sub(p, E), z = Math.max(0.02, dot(d, CF)); return { x: cw / 2 + dot(d, CR) / z * FOC, y: ch / 2 - dot(d, CU) / z * FOC, z, s: FOC / z }; }

// ------------------------------------------------------------------ o mundo: mesa no chão (y = 0), x direita, z pra frente
const TA = 1.6, TB = 1.0, SA = TA * 1.4, SB = TB * 1.55, ANG = 360 / N;
const VISTA0 = EV[0].depois.vista;
const angW = i => (90 + (i - VISTA0) * ANG) * PI / 180;                 // ângulo do lugar i no mundo (fixo)
const lugar = (i, f, y) => { const a = angW(i); return [Math.cos(a) * SA * f, y || 0, -Math.sin(a) * SB * f]; };
const tang = i => { const a = angW(i); return norm([-Math.sin(a) * SA, 0, -Math.cos(a) * SB]); };   // de lado (pra espalhar as cartas)
const praCentro = i => norm(mul(lugar(i, 1), -1));
function vistaEm(t) {
  let v = VISTA0;
  for (const e of EV) { if (e.tipo !== 'camera') continue; if (t < e.t0) break;
    let dif = ((e.dados.para - v) % N + N) % N; if (dif > N / 2) dif -= N; v = v + dif * ease((t - e.t0) / e.dur); }
  return v;
}
function trocaEm(t) { for (const e of EV) if (e.tipo === 'camera' && t >= e.t0 && t <= e.t0 + e.dur) return Math.sin(PI * (t - e.t0) / e.dur); return 0; }
const angDiff = (i, v) => { let d = ((i - v) % N + N) % N; if (d > N / 2) d -= N; return d; };

// ------------------------------------------------------------------ texturas (geradas uma vez)
function tela(w, h) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }
const COR4 = { s: '#111827', h: '#dc2626', d: '#2563eb', c: '#16a34a' }, COR2 = { s: '#111', h: '#d61f1f', d: '#d61f1f', c: '#111' };
const SIMB = { s: '♠', h: '♥', d: '♦', c: '♣' };
const corNaipe = n => T.naipes === 'quatro' ? COR4[n] : T.naipes === 'mono' ? (n === 'h' || n === 'd' ? '#6b6b6b' : '#111') : T.naipes === 'ouro' ? (n === 'h' || n === 'd' ? '#b8860b' : '#111') : COR2[n];
const TX = {};
function texCarta(cod) {
  if (TX[cod]) return TX[cod];
  const c = tela(100, 140), g = c.getContext('2d');
  g.fillStyle = '#f4efe4'; g.beginPath(); g.roundRect(1, 1, 98, 138, 9); g.fill();
  g.strokeStyle = '#0003'; g.lineWidth = 2; g.stroke();
  if (cod === 'verso') {
    g.fillStyle = T.verso1; g.beginPath(); g.roundRect(7, 7, 86, 126, 6); g.fill();
    g.strokeStyle = T.verso2; g.lineWidth = 5; for (let k = -140; k < 140; k += 13) { g.beginPath(); g.moveTo(k, 0); g.lineTo(k + 140, 140); g.stroke(); }
    g.strokeStyle = '#fff8'; g.lineWidth = 3; g.strokeRect(12, 12, 76, 116);
  } else {
    const r = cod[0] === 'T' ? '10' : cod[0], n = cod[1], cor = corNaipe(n);
    g.fillStyle = cor; g.font = `800 46px ${FONTE}`; g.textBaseline = 'top'; g.fillText(r, 9, 6);
    g.font = `700 34px ${FONTE}`; g.fillText(SIMB[n], 10, 54);
    g.font = `700 62px ${FONTE}`; g.textAlign = 'right'; g.textBaseline = 'bottom'; g.fillText(SIMB[n], 94, 136);
  }
  TX[cod] = c; return c;
}
// o personagem: a imagem do Flow (se tiver) ou um genérico mascarado no mesmo clima (cada nome sai diferente)
const IMG = [];
function generico(i) {
  const c = tela(220, 330), g = c.getContext('2d');
  let s = 0; for (const ch2 of D.jogadores[i].nome) s = (s * 31 + ch2.charCodeAt(0)) % 9973;
  const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const pele = ['#c9b79c', '#a98f75', '#d8cdb8', '#8d7a66'][s % 4], roupa = ['#2b2420', '#3a2a24', '#22282b', '#352f22'][(s >> 3) % 4];
  const mascara = ['#d9d2c0', '#b8a88a', '#9c8f7a', '#e6e0cf'][(s >> 5) % 4];
  // ombros e tronco
  g.fillStyle = roupa; g.beginPath(); g.moveTo(10, 330); g.quadraticCurveTo(20, 205, 110, 196); g.quadraticCurveTo(200, 205, 210, 330); g.fill();
  g.fillStyle = '#0006'; g.fillRect(100, 205, 20, 125);
  // pescoço + cabeça
  g.fillStyle = pele; g.fillRect(92, 165, 36, 40);
  g.fillStyle = mascara; g.beginPath(); g.ellipse(110, 112, 52 + rnd() * 8, 66 + rnd() * 8, 0, 0, 2 * PI); g.fill();
  // olhos (buracos da máscara) e boca
  g.fillStyle = '#050403';
  const tipo = (s >> 7) % 3;
  if (tipo === 0) { g.beginPath(); g.ellipse(88, 102, 13, 17, 0.2, 0, 2 * PI); g.ellipse(132, 102, 13, 17, -0.2, 0, 2 * PI); g.fill(); }
  else if (tipo === 1) { g.fillRect(74, 96, 72, 14); g.fillStyle = '#7fff7f55'; g.fillRect(80, 100, 60, 5); g.fillStyle = '#050403'; }
  else { g.beginPath(); g.arc(90, 104, 11, 0, 2 * PI); g.arc(130, 104, 11, 0, 2 * PI); g.fill(); }
  g.fillRect(96, 145, 28, 5 + rnd() * 5);
  // sujeira / costuras
  g.strokeStyle = '#3a2a1f88'; g.lineWidth = 2; for (let k = 0; k < 7; k++) { g.beginPath(); const x = 70 + rnd() * 80, y = 60 + rnd() * 100; g.moveTo(x, y); g.lineTo(x + rnd() * 20 - 10, y + rnd() * 20 - 10); g.stroke(); }
  for (let k = 0; k < 500; k++) { g.fillStyle = `rgba(30,20,10,${rnd() * 0.25})`; g.fillRect(rnd() * 220, rnd() * 330, 2, 2); }
  // capuz/chapéu às vezes
  if ((s >> 9) % 2) { g.fillStyle = roupa; g.beginPath(); g.ellipse(110, 80, 64, 50, 0, PI, 2 * PI); g.fill(); }
  return c;
}
const LOGO = (() => { if (!OP.logo) return null; const c = tela(600, 120), g = c.getContext('2d'); g.fillStyle = T.linha.slice(0, 7);
  g.globalAlpha = 0.85; g.font = `800 82px ${FONTE}`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(OP.logo.toUpperCase(), 300, 64); return c; })();

// ------------------------------------------------------------------ desenho com textura (triângulos afins)
function tri(img, s0, s1, s2, d0, d1, d2) {
  const cx = (d0.x + d1.x + d2.x) / 3, cy = (d0.y + d1.y + d2.y) / 3, inf = q => ({ x: q.x + Math.sign(q.x - cx) * 0.6, y: q.y + Math.sign(q.y - cy) * 0.6 });
  const a0 = inf(d0), a1 = inf(d1), a2 = inf(d2);
  ctx.save(); ctx.beginPath(); ctx.moveTo(a0.x, a0.y); ctx.lineTo(a1.x, a1.y); ctx.lineTo(a2.x, a2.y); ctx.closePath(); ctx.clip();
  const s1x = s1[0] - s0[0], s1y = s1[1] - s0[1], s2x = s2[0] - s0[0], s2y = s2[1] - s0[1], det = s1x * s2y - s2x * s1y;
  const q1x = d1.x - d0.x, q1y = d1.y - d0.y, q2x = d2.x - d0.x, q2y = d2.y - d0.y;
  const a = (q1x * s2y - q2x * s1y) / det, c = (-q1x * s2x + q2x * s1x) / det, b = (q1y * s2y - q2y * s1y) / det, d = (-q1y * s2x + q2y * s1x) / det;
  ctx.setTransform(a, b, c, d, d0.x - a * s0[0] - c * s0[1], d0.y - b * s0[0] - d * s0[1]);
  ctx.drawImage(img, 0, 0); ctx.restore();
}
function quad(img, q) { const w = img.width, h = img.height; tri(img, [0, 0], [w, 0], [w, h], q[0], q[1], q[2]); tri(img, [0, 0], [w, h], [0, h], q[0], q[2], q[3]); }
function elipse(cx, cy, rx, ry, y, passos) { const pts = []; for (let k = 0; k < (passos || 56); k++) { const a = k / (passos || 56) * 2 * PI; pts.push(P([cx + Math.cos(a) * rx, y, cy + Math.sin(a) * ry])); } return pts; }
function poligono(pts) { ctx.beginPath(); pts.forEach((q, k) => k ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y)); ctx.closePath(); }

// ------------------------------------------------------------------ cartas 3D: centro, eixo da largura (R), eixo do comprimento (V)
const CWd = 0.2, CHd = 0.28;
// carta: {c, R, V, vira (0 = virada pra baixo, 1 = face pra cima), cod, alpha, escuro}
function desenhaCarta(k) {
  if (!k || k.alpha <= 0.01) return;
  const th = PI * (1 - k.vira), N0 = norm(cross(k.V, k.R));
  const R2 = add(mul(k.R, Math.cos(th)), mul(N0, Math.sin(th))), n = add(mul(N0, Math.cos(th)), mul(k.R, -Math.sin(th)));
  const c = add(k.c, mul(N0, Math.abs(Math.sin(th)) * CWd * 0.5 + 0.004));
  const hw = mul(R2, CWd / 2), hh = mul(k.V, CHd / 2);
  let q = [P(add(sub(c, hw), hh)), P(add(add(c, hw), hh)), P(sub(add(c, hw), hh)), P(sub(sub(c, hw), hh))];
  const face = dot(n, sub(E, c)) > 0 && k.cod;
  if (face && q[0].y > q[3].y) q = [q[2], q[3], q[0], q[1]];   // de ponta-cabeça pra câmera: gira a imagem (fica legível)
  ctx.globalAlpha = k.alpha;
  // sombra
  ctx.fillStyle = '#0007'; poligono(q.map(p => ({ x: p.x + 1.5 * UI, y: p.y + 2 * UI }))); ctx.fill();
  quad(texCarta(face ? k.cod : 'verso'), q);
  if (k.escuro) { ctx.fillStyle = `rgba(0,0,0,${k.escuro})`; poligono(q); ctx.fill(); }
  if (k.brilho) { ctx.strokeStyle = T.valor; ctx.lineWidth = 2 * UI; poligono(q); ctx.stroke(); }
  ctx.globalAlpha = 1;
}
const plano = (c, V) => ({ c, V: norm(V), R: norm(cross([0, 1, 0], norm(V))) });

// ------------------------------------------------------------------ fichas 3D
const CORES_FICHA = ['#b91c1c', '#1d4ed8', '#15803d', '#111827', '#ca8a04', '#6d28d9'];
const nFichas = v => v <= 0 ? 0 : Math.max(1, Math.min(14, Math.round(2 + Math.log2(1 + v) * 1.6)));
function pilha(p, n, seed) {   // n fichas empilhadas num ponto do mundo (de baixo pra cima)
  if (n <= 0) return;
  const R0 = 0.05, alt = 0.012;
  for (let k = 0; k < n; k++) {
    const base = P(add(p, [0, k * alt, 0])), topo = P(add(p, [0, (k + 1) * alt, 0]));
    const r = R0 * base.s, ry = Math.max(1, Math.abs(P(add(p, [0, k * alt, R0])).y - base.y) * 0.9 + r * 0.2);
    const cor = CORES_FICHA[(k + (seed || 0)) % CORES_FICHA.length];
    ctx.fillStyle = '#0009'; ctx.beginPath(); ctx.ellipse(base.x, base.y, r, ry, 0, 0, 2 * PI); ctx.fill();
    ctx.fillStyle = cor; ctx.beginPath(); ctx.ellipse(topo.x, topo.y, r, ry, 0, 0, 2 * PI); ctx.fill();
    ctx.strokeStyle = '#ffffffaa'; ctx.lineWidth = Math.max(1, r * 0.18); ctx.setLineDash([r * 0.35, r * 0.35]);
    ctx.beginPath(); ctx.ellipse(topo.x, topo.y, r * 0.86, ry * 0.86, 0, 0, 2 * PI); ctx.stroke(); ctx.setLineDash([]);
  }
}

// ------------------------------------------------------------------ textos (no estilo pixel, na resolução interna)
function texto(s, x, y, tam, cor, al, fundo, peso) {
  ctx.font = `${peso || 800} ${Math.round(tam * UI)}px ${FONTE}`; ctx.textAlign = al || 'center'; ctx.textBaseline = 'middle';
  if (fundo) { const w = ctx.measureText(s).width, h = tam * UI * 1.3; const x0 = al === 'left' ? x - 4 * UI : al === 'right' ? x - w - 4 * UI : x - w / 2 - 4 * UI;
    ctx.fillStyle = fundo; ctx.beginPath(); ctx.roundRect(x0, y - h / 2, w + 8 * UI, h, 3 * UI); ctx.fill(); }
  ctx.fillStyle = '#000a'; ctx.fillText(s, x + UI, y + UI); ctx.fillStyle = cor; ctx.fillText(s, x, y);
}
const COR_ACAO = r => /FOLD/.test(r) ? '#6b7280' : /ALL-IN/.test(r) ? '#dc2626' : /RAISE|BET/.test(r) ? '#d97706' : /CALL/.test(r) ? '#16a34a' : /^\+/.test(r) ? T.valor : '#475569';

// ------------------------------------------------------------------ estado num instante (igual ao 2D)
function indice(t) { let lo = 0, hi = EV.length - 1, k = 0; while (lo <= hi) { const m = (lo + hi) >> 1; if (EV[m].t0 <= t) { k = m; lo = m + 1; } else hi = m - 1; } return k; }
const VAZIO = { stack: D.inicial, aposta: D.inicial.map(() => 0), pot: 0, board: [], fora: D.inicial.map(() => false), allin: D.inicial.map(() => false),
  ultima: D.inicial.map(() => ''), vez: null, equidade: {}, revelado: D.inicial.map(() => false), jogos: {}, ganhos: {}, rua: 'preflop', boards_x: [] };
function cartasDadas(t) { const q = D.jogadores.map(() => Array(NC).fill(null)); for (const e of EV) if (e.tipo === 'carta_jogador') q[e.dados.quem][e.dados.k] = e; return q; }
const DADAS = cartasDadas(0);
const MOSTRA0 = D.mostrar || OP.mostrar;
function modoEm(t) { let m = MOSTRA0; for (const x of D.mostrares || []) { if (x.t0 > t) break; m = x.modo; } return m; }
const heroiIdx = D.jogadores.findIndex(j => j.heroi);
const DEALER = [0, 0.32, 0.62];

// ------------------------------------------------------------------ o quadro
function render(t) {
  const k = indice(t), e = EV[k], antes = k > 0 ? EV[k - 1].depois : VAZIO, depois = e.depois;
  const p = clamp((t - e.t0) / Math.max(0.001, e.dur), 0, 1), pe = ease(p), fim = p >= 0.999, st = fim ? depois : antes;
  const intro = e.tipo === 'intro' ? pe : 1;
  // ---- câmera: sentada atrás do jogador da vista; na troca levanta e dá a volta
  const v = vistaEm(t), aV = (90 + (v - VISTA0) * ANG) * PI / 180, tro = trocaEm(t);
  // sentado na cadeira, olhando por cima da mesa pros outros (o lado de lá aparece inteiro, com os rostos)
  let eye = [Math.cos(aV) * SA * 1.1, 1.38 + 0.5 * tro, -Math.sin(aV) * SB * 1.1];
  let alvo = [-Math.cos(aV) * SA * 0.22, 0.05, Math.sin(aV) * SB * 0.22];
  let fov = (VERT ? 74 : 54) + 8 * tro + (1 - intro) * 10;
  { let ant = { z: 1, alvo: 'board' }, cur = ant, t0 = -9, dur = 0.7;
    for (const z of D.zooms || []) { if (z.t0 > t) break; ant = cur; cur = { z: z.escala, alvo: z.alvo }; t0 = z.t0; dur = z.dur; }
    const foco = a => typeof a === 'number' ? lugar(a, 1, 0.55) : a === 'pot' ? [0, 0, 0.36] : [0, 0, 0];
    const q = ease(clamp((t - t0) / dur, 0, 1)), zz = lerp(ant.z, cur.z, q);
    if (zz > 1.001 && OP.zoom !== false) { const f = foco(cur.alvo === 'off' ? ant.alvo : cur.alvo), w = clamp((zz - 1) / 0.6, 0, 0.75);
      eye = lerp3(eye, lerp3(f, eye, 0.45), w); alvo = lerp3(alvo, f, w * 0.9); } }
  // shorts: tremida no all-in
  let tremida = 0, flash = 0;
  if (SH && e.tipo === 'acao' && /ALL-IN/.test(e.dados.rotulo || '') && p > 0.25 && p < 0.55) tremida = 1;
  if (SH && e.tipo === 'vencedor' && p > 0.35 && p < 0.5) tremida = 0.6;
  if (tremida) alvo = add(alvo, [Math.sin(t * 97) * 0.02 * tremida, Math.cos(t * 83) * 0.015 * tremida, 0]);
  if (SH && e.tipo === 'acao' && /ALL-IN/.test(e.dados.rotulo || '')) { fov -= 8 * Math.sin(PI * p); flash = Math.max(0, 1 - Math.abs(p - 0.3) * 6) * 0.35; }
  if (SH && e.tipo === 'board' && e.dados.pos === 4) fov -= 6 * Math.sin(PI * p);
  setCam(eye, alvo, fov);

  // ---- sala
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  const g0 = ctx.createLinearGradient(0, 0, 0, ch); g0.addColorStop(0, '#0d0907'); g0.addColorStop(1, '#030202');
  ctx.fillStyle = g0; ctx.fillRect(0, 0, cw, ch);
  for (let a = 0; a < 360; a += 9) {   // tábuas da parede (num cilindro em volta): se mexem com a câmera
    const r = a * PI / 180, x = Math.cos(r) * 4.6, z = Math.sin(r) * 4.2, pa = P([x, -1, z]), pb = P([x, 3.2, z]);
    if (pa.z < 0.3 || pb.z < 0.3) continue;
    ctx.strokeStyle = a % 27 === 0 ? '#1d1410' : '#140e0b'; ctx.lineWidth = Math.max(1, 0.06 * pa.s); ctx.beginPath(); ctx.moveTo(pa.x, pa.y); ctx.lineTo(pb.x, pb.y); ctx.stroke();
  }
  // luminária pendurada
  { const L = P([0, 2.3, 0]), Lc = P([0, 3.6, 0]); ctx.strokeStyle = '#2a2220'; ctx.lineWidth = Math.max(1, UI); ctx.beginPath(); ctx.moveTo(Lc.x, Lc.y); ctx.lineTo(L.x, L.y); ctx.stroke();
    const rg = ctx.createRadialGradient(L.x, L.y, 0, L.x, L.y, 0.9 * L.s); rg.addColorStop(0, '#ffe6b04d'); rg.addColorStop(1, '#ffe6b000'); ctx.fillStyle = rg; ctx.fillRect(0, 0, cw, ch);
    ctx.fillStyle = '#3a302a'; ctx.beginPath(); const a1 = P([-0.28, 2.15, 0]), a2 = P([0.28, 2.15, 0]), b1 = P([-0.08, 2.32, 0]), b2 = P([0.08, 2.32, 0]);
    ctx.moveTo(b1.x, b1.y); ctx.lineTo(b2.x, b2.y); ctx.lineTo(a2.x, a2.y); ctx.lineTo(a1.x, a1.y); ctx.fill();
    ctx.fillStyle = '#fff3c4'; ctx.beginPath(); ctx.ellipse((a1.x + a2.x) / 2, (a1.y + a2.y) / 2, Math.abs(a2.x - a1.x) / 2.4, Math.max(1, 2 * UI), 0, 0, 2 * PI); ctx.fill(); }

  // ---- personagens (atrás da mesa: a borda tapa a cintura)
  const MODO = modoEm(t);
  const ordem = [...Array(N).keys()].sort((a, b) => P(lugar(b, 1)).z - P(lugar(a, 1)).z);
  const pessoa = {};
  ordem.forEach(i => {
    const base = lugar(i, 1.08, -0.5), cab = lugar(i, 1.08, 0.95), pb = P(base), pc = P(cab);
    pessoa[i] = { pb, pc };
    if (pb.z < 0.7) return;   // é a câmera (ou está passando por ela)
    const img = IMG[i], h = pb.y - pc.y, w = h * img.width / img.height;
    const foraAgora = st.fora[i];
    ctx.globalAlpha = clamp((pb.z - 0.7) / 0.6, 0, 1) * intro;
    ctx.filter = foraAgora ? 'brightness(.7) grayscale(.6)' : 'brightness(1.5)';   // a luz da mesa bate neles
    ctx.drawImage(img, pb.x - w / 2, pc.y, w, h);
    ctx.filter = 'none'; ctx.globalAlpha = 1;
  });

  // ---- mesa: base (espessura), borda, feltro com a luz em cima, linha, logo
  ctx.globalAlpha = intro;
  ctx.fillStyle = T.lateral; poligono(elipse(0, 0, TA + 0.16, TB + 0.16, -0.14)); ctx.fill();
  const borda = elipse(0, 0, TA + 0.16, TB + 0.16, 0);
  { const c0 = P([0, 0, 0]); const gb = ctx.createRadialGradient(c0.x, c0.y, 0, c0.x, c0.y, TA * 1.2 * c0.s);
    gb.addColorStop(0, T.borda); gb.addColorStop(1, T.borda2); ctx.fillStyle = gb; poligono(borda); ctx.fill(); }
  { const c0 = P([0, 0, 0]); const gf = ctx.createRadialGradient(c0.x, c0.y - 0.2 * c0.s, 0, c0.x, c0.y, TA * 1.05 * c0.s);
    gf.addColorStop(0, T.feltro1); gf.addColorStop(1, T.feltro2); ctx.fillStyle = gf; poligono(elipse(0, 0, TA, TB, 0.002)); ctx.fill(); }
  ctx.strokeStyle = T.linha; ctx.lineWidth = Math.max(1, UI); poligono(elipse(0, 0, TA * 0.84, TB * 0.8, 0.003)); ctx.stroke();
  if (LOGO) { const w = 1.1, h = w * LOGO.height / LOGO.width, z0 = -0.5;
    quad(LOGO, [P([-w / 2, 0.003, z0 + h / 2]), P([w / 2, 0.003, z0 + h / 2]), P([w / 2, 0.003, z0 - h / 2]), P([-w / 2, 0.003, z0 - h / 2])]); }
  ctx.globalAlpha = 1;

  // ---- botão do dealer
  { const b = add(lugar(D.botao, 0.56), mul(tang(D.botao), -0.22)), pb = P(b), r = 0.06 * pb.s;
    ctx.fillStyle = '#0008'; ctx.beginPath(); ctx.ellipse(pb.x + UI, pb.y + UI, r, r * 0.45, 0, 0, 2 * PI); ctx.fill();
    ctx.fillStyle = '#f5f5f5'; ctx.beginPath(); ctx.ellipse(pb.x, pb.y, r, r * 0.45, 0, 0, 2 * PI); ctx.fill();
    ctx.fillStyle = '#b91c1c'; ctx.font = `900 ${Math.max(6, r * 0.8)}px ${FONTE}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('D', pb.x, pb.y); }

  // ---- board (o dealer desliza e vira)
  const bx = j => (j - 2) * 0.25;
  for (let j = 0; j < 5; j++) {
    const cod = depois.board[j] || antes.board[j]; if (!cod) continue;
    const agora = e.tipo === 'board' && !e.dados.run && e.dados.pos === j;
    if (!st.board[j] && !agora) continue;
    let c = [bx(j), 0, 0.04], vira = 1;
    if (agora) { const q = ease(clamp(p / 0.45, 0, 1)); c = lerp3(DEALER, c, q); c[1] += Math.sin(PI * q) * 0.12; vira = ease(clamp((p - 0.5) / 0.4, 0, 1)); }
    desenhaCarta(Object.assign(plano(c, [0, 0, 1]), { vira, cod, alpha: 1 }));
  }
  (depois.boards_x || []).forEach((b, r) => { const bAntes = (st.boards_x || [])[r];
    b.cartas.forEach((cod, kk) => { const j = b.corte + kk, agora = e.tipo === 'board' && e.dados.run === b.run && e.dados.pos === j;
      if (!(bAntes && bAntes.cartas[kk]) && !agora) return;
      let c = [bx(j), 0, 0.04 - (r + 1) * 0.33], vira = 1;
      if (agora) { const q = ease(clamp(p / 0.45, 0, 1)); c = lerp3(DEALER, c, q); vira = ease(clamp((p - 0.5) / 0.4, 0, 1)); }
      desenhaCarta(Object.assign(plano(c, [0, 0, 1]), { vira, cod, alpha: 1 })); }); });

  // ---- pote, apostas, fichas voando
  const POT = [0, 0, 0.42];
  let pot = st.pot; if (e.tipo === 'recolher' && !fim) pot = p > 0.85 ? depois.pot : antes.pot; if (e.tipo === 'vencedor' && !fim) pot = p > 0.8 ? 0 : antes.pot;
  pilha(POT, nFichas(pot), 2);
  const soma = st.aposta.reduce((a, b) => a + b, 0);
  for (let i = 0; i < N; i++) {
    let ap = st.aposta[i];
    if (e.tipo === 'acao' && e.dados.quem === i && !fim) ap = p > 0.8 ? depois.aposta[i] : antes.aposta[i];
    if (e.tipo === 'blinds' && !fim) ap = p > 0.75 ? depois.aposta[i] : antes.aposta[i];
    if (e.tipo === 'recolher' && !fim) ap = 0;
    pilha(lugar(i, 0.47), nFichas(ap), i);
    if (ap > 0) { const q = P(add(lugar(i, 0.47), [0, 0.2, 0])); texto(fmt(ap), q.x, q.y, 8, '#fff', 'center', '#000b'); }
    // o stack do jogador (torre de fichas do lado das cartas)
    pilha(add(lugar(i, 0.66), mul(tang(i), 0.3)), Math.min(10, nFichas(st.stack[i])), i + 3);
  }
  const voar = (de, para, q, n) => { const c = lerp3(de, para, q); c[1] += Math.sin(PI * q) * 0.25; pilha(c, n, 1); };
  if (e.tipo === 'acao' && e.dados.valor > 0 && p < 0.85) voar(add(lugar(e.dados.quem, 0.66), mul(tang(e.dados.quem), 0.3)), lugar(e.dados.quem, 0.47), ease(clamp((p - 0.2) / 0.6, 0, 1)), nFichas(e.dados.valor));
  if (e.tipo === 'blinds' && p < 0.8) e.dados.quem.forEach(q => voar(add(lugar(q, 0.66), mul(tang(q), 0.3)), lugar(q, 0.47), ease(clamp(p / 0.75, 0, 1)), 2));
  if (e.tipo === 'recolher' && p < 0.9) e.dados.de.forEach(q => voar(lugar(q, 0.47), POT, ease(p / 0.9), nFichas(antes.aposta[q])));
  if (e.tipo === 'vencedor' && p > 0.35 && p < 0.95) e.dados.quem.forEach(q => voar(POT, lugar(q, 0.6), ease((p - 0.35) / 0.6), nFichas(depois.ganhos[q] || 1)));
  if (pot + soma > 0 && e.tipo !== 'final') { const q = P([POT[0], 0.35, POT[2]]); texto('POT ' + fmt(pot + (e.tipo === 'recolher' ? 0 : soma)), q.x, q.y, 10, T.valor, 'center', '#000c'); }

  // ---- cartas dos jogadores (as que estão na mão da câmera vão por último, por cima de tudo)
  const naMao = [];
  for (let i = 0; i < N; i++) {
    const povPeso = clamp(1 - Math.abs(angDiff(i, v)) * 2, 0, 1);
    const souEu = povPeso > 0.5;                       // o jogador da vista segura as cartas na frente da câmera
    const ver = MODO === 'todas' ? 1 : MODO === 'heroi' ? (i === heroiIdx ? 1 : 0) : MODO === 'pov' ? povPeso : 0;
    const foldAgora = e.tipo === 'acao' && e.dados.quem === i && e.dados.acao === 'fold';
    for (let kk = 0; kk < NC; kk++) {
      const ev = DADAS[i][kk]; if (!ev || t < ev.t0) continue;
      const trocaAgora = e.tipo === 'troca' && e.dados.quem === i && (e.dados.pos || []).includes(kk);
      const cods = (trocaAgora && p < 0.5 ? antes : st).maos;
      const cod = (cods && cods[i] ? cods[i][kk] : D.jogadores[i].cartas[kk]) || null;
      const abertaSempre = (D.abertas || []).includes(kk);
      const meio = kk - (NC - 1) / 2, esp = NC <= 2 ? 0.13 : 0.09;
      const centro = add(lugar(i, 0.66), mul(tang(i), -meio * esp - 0.08));
      let pose = plano(centro, praCentro(i)), vira = (ver || st.revelado[i] || abertaSempre) && cod ? 1 : 0;
      if (e.tipo === 'showdown' && depois.revelado[i] && !antes.revelado[i] && !ver) vira = pe;
      // 🂠 nas mãos: o da vista levanta as cartas na frente da câmera (como quem espia)
      const segura = souEu && !st.fora[i] && !foldAgora && e.tipo !== 'intro';
      if (segura) {
        // na frente da câmera, um pouco abaixo do centro, viradas pra ela (como na mão de quem está sentado)
        const perto = add(add(add(E, mul(CF, VERT ? 1.15 : 1.05)), mul(CU, VERT ? -0.62 : -0.5)), mul(CR, meio * 0.17 + (VERT ? 0.12 : 0.42)));
        const V2 = norm(add(add(mul(CU, 0.85), mul(CF, 0.45)), mul(CR, -meio * 0.18))), R2 = norm(add(CR, mul(CF, meio * 0.2)));
        const q = clamp((povPeso - 0.5) * 2, 0, 1);
        pose = { c: lerp3(pose.c, perto, q), V: norm(lerp3(pose.V, V2, q)), R: norm(lerp3(pose.R, R2, q)) };
        vira = cod && (ver || MODO !== 'showdown' || st.revelado[i]) ? 1 : vira;
      }
      // distribuindo: voa do dealer
      const chegou = t >= ev.t0 + ev.dur;
      if (!chegou) { const q = ease((t - ev.t0) / ev.dur); pose = Object.assign({}, pose, { c: add(lerp3(DEALER, pose.c, q), [0, Math.sin(PI * q) * 0.1, 0]) }); vira = 0; }
      // desistiu: vai virada pro muck (e fica lá)
      const muck = add(add(lugar(i, 0.5), mul(tang(i), 0.25)), [0, 0, 0]);
      const mV = norm(add(praCentro(i), mul(tang(i), 0.4 + 0.2 * kk)));
      let escuro = 0;
      if (st.fora[i] && !foldAgora) { pose = plano(add(muck, mul(tang(i), kk * 0.06)), mV); vira = 0; escuro = 0.25; }
      if (foldAgora) { const q = ease(clamp((p - 0.1) / 0.75, 0, 1)); const alvoM = plano(add(muck, mul(tang(i), kk * 0.06)), mV);
        pose = { c: add(lerp3(pose.c, alvoM.c, q), [0, Math.sin(PI * q) * 0.08, 0]), V: norm(lerp3(pose.V, alvoM.V, q)), R: pose.R }; vira = vira * (1 - clamp(q * 3, 0, 1)); }
      if (trocaAgora) { const q2 = p < 0.5 ? ease(p / 0.45) : 1 - ease((p - 0.55) / 0.45); pose = Object.assign({}, pose, { c: add(lerp3(pose.c, DEALER, clamp(q2, 0, 1)), [0, Math.sin(PI * clamp(q2, 0, 1)) * 0.1, 0]) }); if (q2 > 0.2) vira = 0; }
      if (e.tipo === 'intro') continue;
      (segura ? (x => naMao.push(x)) : desenhaCarta)(Object.assign({}, pose, { R: pose.R || norm(cross([0, 1, 0], pose.V)), vira, cod, alpha: 1, escuro,
        brilho: (e.tipo === 'vencedor' || e.tipo === 'final') && (depois.ganhos[i] || 0) > 0 && !st.fora[i] }));
    }
  }

  // ---- a luz da luminária: só a mesa fica clara, o resto afunda no escuro
  { const c0 = P([0, 0, 0]), r = TA * 1.25 * c0.s; const gl = ctx.createRadialGradient(c0.x, c0.y, r * 0.15, c0.x, c0.y, r);
    gl.addColorStop(0, '#ffffff'); gl.addColorStop(0.6, LIMPO ? '#d8d0c8' : '#b8aa98'); gl.addColorStop(1, LIMPO ? '#605850' : '#3a302a');
    ctx.globalCompositeOperation = 'multiply'; ctx.fillStyle = gl; ctx.fillRect(0, 0, cw, ch); ctx.globalCompositeOperation = 'source-over'; }
  naMao.forEach(desenhaCarta);   // na mão, perto da câmera (fora do escuro da sala)
  posProcesso(t);   // o acabamento (paleta/dither/grão) só na cena: os textos por cima ficam legíveis
  // ---- HUD de cada jogador (nome, stack, ação, equidade, jogo)
  for (let i = 0; i < N; i++) {
    const pp = pessoa[i], povPeso = clamp(1 - Math.abs(angDiff(i, v)) * 2, 0, 1);
    let x, y;
    if (povPeso > 0.5 || pp.pb.z < 0.7) { x = 60 * UI; y = ch - 30 * UI; }            // eu: no canto de baixo
    else { x = pp.pb.x; y = clamp(pp.pc.y + (pp.pb.y - pp.pc.y) * 0.6, 40 * UI, ch - 40 * UI); }   // no peito (o rosto fica livre)
    let sv = st.stack[i];
    if (!fim && ['acao', 'blinds', 'vencedor'].includes(e.tipo)) sv = lerp(antes.stack[i], depois.stack[i], clamp((p - 0.15) / 0.6, 0, 1));
    const vez = (e.tipo === 'pensa' && e.dados.quem === i) || (e.tipo === 'acao' && e.dados.quem === i && p < 0.4);
    const venceu = (e.tipo === 'vencedor' || e.tipo === 'final') && (depois.ganhos[i] || 0) > 0 && (e.tipo === 'final' || p > 0.55);
    ctx.globalAlpha = intro * (st.fora[i] ? 0.6 : 1);
    texto(D.jogadores[i].nome + (D.jogadores[i].pais ? ' · ' + D.jogadores[i].pais : ''), x, y, 9, vez ? T.acento : T.placa_txt, 'center', venceu ? T.valor + 'cc' : '#000c', 700);
    texto(st.allin[i] && sv <= 0.001 ? 'ALL-IN' : fmt(sv), x, y + 13 * UI, 10, T.valor, 'center', '#000c');
    let rot = st.ultima[i]; if (e.tipo === 'acao' && e.dados.quem === i) rot = p > 0.25 ? e.dados.rotulo : antes.ultima[i];
    if (venceu) rot = '+' + fmt(depois.ganhos[i]);
    if (rot && UNI_L !== 'bb' && !venceu) rot = rot.replace(/(-?[\d.]+)$/, m0 => fmt(parseFloat(m0)));
    if (rot) texto(rot, x, y - 13 * UI, 8, /^\+/.test(rot) ? '#111' : '#fff', 'center', COR_ACAO(rot));
    const eq = st.equidade[i];
    if (OP.equidade && eq != null && !st.fora[i] && !['vencedor', 'final', 'showdown'].includes(e.tipo) && (MODO !== 'pov' || povPeso > 0.5 || st.revelado[i]))
      texto(String(eq).replace('.', ',') + '%', x, y + 25 * UI, 8, '#fff', 'center', '#000c');
    const jogo = ['showdown', 'vencedor', 'final'].includes(e.tipo) && depois.jogos[i];
    if (jogo) texto(jogo, x, y + 25 * UI, 8, '#111', 'center', T.valor);
    if (vez) { ctx.fillStyle = T.acento; ctx.fillRect(x - 24 * UI, y + 20 * UI, 48 * UI * (e.tipo === 'pensa' ? 1 - p : 0), 2 * UI); }
    ctx.globalAlpha = 1;
    // 😰 emoção
    if (OP.emocoes) for (const em of D.emocoes || []) { if (em.quem !== i || t < em.t0 || t > em.t0 + em.dur) continue;
      const q = (t - em.t0) / em.dur, ent = clamp(q / 0.14, 0, 1), sai = clamp((1 - q) / 0.16, 0, 1);
      const ex = povPeso > 0.5 ? 40 * UI : x, ey = povPeso > 0.5 ? ch - 72 * UI : pp.pc.y + 10 * UI;
      ctx.globalAlpha = Math.min(ent * 2, sai); ctx.font = `${Math.round(30 * UI * (0.6 + 0.4 * ent))}px 'Noto Color Emoji','Segoe UI Emoji',sans-serif`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(em.emoji, ex, ey - (1 - sai) * 10 * UI);
      if (em.texto) texto(em.texto, ex, ey - 26 * UI, 8, '#111', 'center', '#fff');
      ctx.globalAlpha = 1; }
  }

  // ---- letreiros: rua, título, nota, gancho, all-in, vencedor
  const nomesRua = { preflop: 'PRÉ-FLOP', flop: 'FLOP', turn: 'TURN', river: 'RIVER', s3: '3ª RUA', s4: '4ª RUA', s5: '5ª RUA', s6: '6ª RUA', s7: '7ª RUA', troca: 'TROCA', pos: 'APOSTAS FINAIS' };
  const rua = e.tipo === 'intro' ? '' : ['vencedor', 'final', 'showdown'].includes(e.tipo) ? (e.dados && e.dados.sem_showdown ? '' : 'SHOWDOWN') : nomesRua[st.rua] || '';
  if (rua) texto(rua, cw / 2, 14 * UI, 9, T.acento, 'center', '#0008');
  if (OP.titulo && D.titulo) texto(D.titulo, 8 * UI, 14 * UI + (VERT ? 18 * UI : 0), 9, T.texto, 'left', null, 700);
  if (e.tipo === 'nota') { ctx.globalAlpha = Math.min(1, p * 6, (1 - p) * 6); texto(e.dados.texto, cw / 2, ch * (VERT ? 0.72 : 0.78), 10, T.placa_txt, 'center', T.placa); ctx.globalAlpha = 1; }
  if (D.dinheiro && OP.dinheiro && e.tipo === 'final') { ctx.globalAlpha = Math.min(1, p * 6, (1 - p) * 6); texto('💰 ' + D.dinheiro, cw / 2, ch * 0.2, 10, T.placa_txt, 'center', T.placa); ctx.globalAlpha = 1; }
  const GANCHO = (OP.gancho || D.gancho || '').trim(), gq = (t - EV[0].dur * 0.3) / 3.2;
  if (GANCHO && gq > 0 && gq < 1) { ctx.globalAlpha = Math.min(1, gq * 8, (1 - gq) * 6); texto(GANCHO, cw / 2, ch * 0.16, VERT ? 15 : 13, '#111', 'center', T.valor, 900); ctx.globalAlpha = 1; }
  if (SH && e.tipo === 'acao' && /ALL-IN/.test(e.dados.rotulo || '')) { const q = clamp((p - 0.2) / 0.8, 0, 1); ctx.globalAlpha = Math.min(1, q * 8, (1 - q) * 3);
    texto('ALL-IN', cw / 2, ch * 0.36, 34 * (1 + 0.5 * Math.pow(1 - q, 3)), '#fff', 'center', null, 900); texto(D.jogadores[e.dados.quem].nome, cw / 2, ch * 0.36 - 30 * UI, 12, T.valor); ctx.globalAlpha = 1; }
  if (SH && e.tipo === 'vencedor') { const q = clamp((p - 0.3) / 0.7, 0, 1), w0 = e.dados.quem[0]; ctx.globalAlpha = Math.min(1, q * 8, (1 - q) * 3);
    texto(D.jogadores[w0].nome, cw / 2, ch * 0.34, 26, '#fff', 'center', null, 900); texto('+' + fmt(e.dados.pot) + (depois.jogos[w0] ? ' · ' + depois.jogos[w0] : ''), cw / 2, ch * 0.34 + 22 * UI, 11, T.valor); ctx.globalAlpha = 1; }
  // ---- 🧠 estratégia (painel na decisão, grade de range)
  if (e.tipo === 'range') {
    const q = clamp(p / 0.35, 0, 1), vis = Math.min(clamp(p * 8, 0, 1), clamp((1 - p) / 0.12, 0, 1)), c = (VERT ? 15 : 17) * UI, x0 = cw / 2 - c * 6.5, y0 = ch / 2 - c * 6.5 + 6 * UI;
    ctx.globalAlpha = vis; ctx.fillStyle = '#000d'; ctx.fillRect(x0 - 6 * UI, y0 - 22 * UI, c * 13 + 12 * UI, c * 13 + 28 * UI);
    texto(`RANGE DE ${D.jogadores[e.dados.quem].nome.toUpperCase()} · ${String(e.dados.pct).replace('.', ',')}%` + (e.dados.mao ? ` · TEM ${e.dados.mao}` : ''), cw / 2, y0 - 11 * UI, 9, T.acento);
    const set = new Set(e.dados.celulas), R0 = 'AKQJT98765432';
    for (let i = 0; i < 13; i++) for (let j = 0; j < 13; j++) {
      const nome = i === j ? R0[i] + R0[j] : i < j ? R0[i] + R0[j] + 's' : R0[j] + R0[i] + 'o', on = set.has(nome) && q > (i + j) / 24;
      ctx.fillStyle = on ? (i === j ? '#b91c1c' : i < j ? T.acento : '#15803d') : '#1f2937'; ctx.fillRect(x0 + j * c + 0.5, y0 + i * c + 0.5, c - 1, c - 1);
      if (nome === e.dados.mao) { ctx.strokeStyle = '#fff'; ctx.lineWidth = Math.max(1, UI * (1 + (Math.sin(t * 8) + 1))); ctx.strokeRect(x0 + j * c + 1, y0 + i * c + 1, c - 2, c - 2); }
      ctx.fillStyle = on ? '#111' : '#6b7280'; ctx.font = `700 ${Math.max(5, c * 0.34)}px ${FONTE}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(nome, x0 + j * c + c / 2, y0 + i * c + c / 2);
    }
    ctx.globalAlpha = 1;
  }
  { const dc = e.tipo === 'pensa' && e.dados.decisao;
    if ((OP.estrategia || D.estrategia) && dc && e.dur >= 1) {
      const vis = Math.min(clamp(p * 8, 0, 1), clamp((1 - p) * 8, 0, 1)), f = x => String(x).replace('.', ',');
      const ok = dc.eq != null ? dc.eq >= dc.precisa : null, x = VERT ? cw / 2 : cw - 92 * UI, y = VERT ? ch * 0.62 : ch - 70 * UI;
      ctx.globalAlpha = vis; ctx.fillStyle = '#000d'; ctx.fillRect(x - 86 * UI, y - 20 * UI, 172 * UI, 66 * UI);
      ctx.strokeStyle = T.acento; ctx.lineWidth = UI; ctx.strokeRect(x - 86 * UI, y - 20 * UI, 172 * UI, 66 * UI);
      texto('DECISÃO DE ' + D.jogadores[e.dados.quem].nome.toUpperCase(), x, y - 12 * UI, 7, T.acento);
      texto(`PAGA ${fmt(dc.pagar)} PRA GANHAR ${fmt(dc.pote)}`, x, y, 8, '#fff');
      texto(`PRECISA ${f(dc.precisa)}%` + (dc.eq != null ? ` · TEM ${f(dc.eq)}%` : ''), x, y + 12 * UI, 8, ok == null ? '#fff' : ok ? '#4ade80' : '#f87171');
      if (dc.ev != null) texto(`EV DO CALL ${dc.ev >= 0 ? '+' : ''}${fmt(dc.ev)} ${ok ? '· PAGAR' : '· LARGAR'}`, x, y + 24 * UI, 8, dc.ev >= 0 ? '#4ade80' : '#f87171');
      if (dc.spr != null) texto(`SPR ${f(dc.spr)}`, x, y + 36 * UI, 7, '#cbd5e1');
      ctx.globalAlpha = 1;
    } }
  if (SH) { ctx.fillStyle = T.acento; ctx.fillRect(0, ch - 2 * UI, cw * clamp(t / D.duracao, 0, 1), 2 * UI); }
  if (flash) { ctx.fillStyle = `rgba(255,240,220,${flash})`; ctx.fillRect(0, 0, cw, ch); }
}

// ------------------------------------------------------------------ acabamento: paleta escura, dither, grão, vinheta
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map(v => (v / 16 - 0.5));
function posProcesso(t) {
  const img = ctx.getImageData(0, 0, cw, ch), d = img.data, fr = Math.floor(t * 8);   // o grão muda 8x por segundo (vídeo leve)
  const niveis = LIMPO ? 0 : 7, grao = LIMPO ? 4 : 12, vin = LIMPO ? 0.35 : 0.6;
  let sd = (fr * 9301 + 49297) % 233280;
  for (let y = 0; y < ch; y++) {
    const dy = (y / ch - 0.5) * 2;
    for (let x = 0; x < cw; x++) {
      const o = (y * cw + x) * 4, dx = (x / cw - 0.5) * 2;
      let r = d[o], g = d[o + 1], b = d[o + 2];
      if (!LIMPO) { const l = 0.3 * r + 0.59 * g + 0.11 * b; r = lerp(r, l * 1.1 + 8, 0.5) * 0.92; g = lerp(g, l * 0.96, 0.5) * 0.9; b = lerp(b, l * 0.8, 0.5) * 0.86; }   // sépia sujo, escuro
      sd = (sd * 9301 + 49297) % 233280; const n = (sd / 233280 - 0.5) * grao;
      const vg = 1 - vin * (dx * dx * 0.6 + dy * dy * 0.8);
      r = (r + n) * vg; g = (g + n) * vg; b = (b + n) * vg;
      if (niveis) { const th = BAYER[(y & 3) * 4 + (x & 3)] * (255 / niveis); const q = 255 / niveis;
        r = Math.round((r + th) / q) * q; g = Math.round((g + th) / q) * q; b = Math.round((b + th) / q) * q; }
      d[o] = r; d[o + 1] = g; d[o + 2] = b;
    }
  }
  ctx.putImageData(img, 0, 0);
}

// ------------------------------------------------------------------ carregar as imagens e começar
let faltam = N;
const pronto = () => { window.render = render; render(0); window.pronto = true; previa(); };
D.jogadores.forEach((j, i) => {
  IMG[i] = generico(i);
  if (!j.personagem) { if (--faltam === 0) pronto(); return; }
  const im = new Image(); im.crossOrigin = 'anonymous';
  im.onload = () => { IMG[i] = im; if (--faltam === 0) pronto(); };
  im.onerror = () => { if (--faltam === 0) pronto(); };
  im.src = j.personagem;
});
if (N === 0) pronto();
function previa() {
  if (D.modo !== 'previa') return;
  document.body.className = 'previa';
  const palco = document.getElementById('palco');
  const ctl = document.createElement('div'); ctl.id = 'controles'; document.body.appendChild(ctl);
  const bt = document.createElement('button'); bt.textContent = '⏸'; ctl.appendChild(bt);
  const rg = document.createElement('input'); rg.type = 'range'; rg.min = 0; rg.max = D.duracao; rg.step = 0.01; rg.value = 0; ctl.appendChild(rg);
  const lb = document.createElement('span'); ctl.appendChild(lb);
  let tocando = true, t0 = performance.now(), base = 0;
  const ajustar = () => { const e = Math.min(innerWidth / W, (innerHeight - 44) / H); palco.style.transform = `scale(${e})`; };
  ajustar(); addEventListener('resize', ajustar);
  bt.onclick = () => { tocando = !tocando; bt.textContent = tocando ? '⏸' : '▶'; base = +rg.value; t0 = performance.now(); };
  rg.oninput = () => { base = +rg.value; t0 = performance.now(); render(base); };
  const laco = () => { if (tocando) { let t = base + (performance.now() - t0) / 1000; if (t > D.duracao + 0.5) { base = 0; t0 = performance.now(); t = 0; } rg.value = t; render(t); lb.textContent = t.toFixed(1) + ' / ' + D.duracao.toFixed(1) + ' s'; } requestAnimationFrame(laco); };
  requestAnimationFrame(laco);
}
</script></body></html>"""
