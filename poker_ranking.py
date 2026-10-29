"""
poker_ranking.py — 🏆 explicador animado do ranking das mãos (motion graphics) (v84_277)
=======================================================================================

Um vídeo curto e bonito que ensina "qual mão ganha de qual":
  • a escada do ranking (da carta alta ao royal flush — ou ao contrário), cada mão com as 5 cartas voando, as que
    formam o jogo subindo e brilhando, a explicação numa frase e a chance de sair (Hold'em, 7 cartas);
  • modalidades: Texas Hold'em, Omaha (PLO 4/5/6 — com a regra "exatamente 2 da mão + 3 da mesa") e Short Deck
    (6+: flush ganha de full house, trinca ganha de sequência, A-6-7-8-9 é a menor sequência);
  • ⚔ duelos: duas mãos + a mesa, o motor (poker_mesa) decide quem ganha e mostra o melhor jogo de cada um
    (kicker, mesa que joga/empate, flush × sequência… ou os seus: "As Kd vs Qh Qs | Ah 7c 2d 9s 3h");
  • a narração de cada cena sai junto (pra mandar pra voz).
Os temas/cores são os mesmos da 🃏 mesa (poker_render.TEMAS_CSS).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Any, Callable, Dict, List, Optional

import poker_mesa as PM
import poker_render as PR

# (categoria do motor, nome, explicação, exemplo, quais cartas formam o jogo, chance em 7 cartas no Hold'em)
CATEGORIAS = [
    ("royal", "Royal Flush", "A, K, Q, J e 10 do mesmo naipe. A mão perfeita — não perde pra ninguém.", "As Ks Qs Js Ts", "11111", 0.0032),
    ("sf", "Straight Flush", "Cinco cartas em sequência, todas do mesmo naipe.", "9h 8h 7h 6h 5h", "11111", 0.0279),
    ("quadra", "Quadra", "Quatro cartas do mesmo valor.", "Qc Qd Qh Qs 4d", "11110", 0.168),
    ("full", "Full House", "Uma trinca + um par.", "Kh Kd Kc 7s 7h", "11111", 2.60),
    ("flush", "Flush", "Cinco cartas do mesmo naipe, em qualquer ordem.", "Ad Jd 8d 4d 2d", "11111", 3.03),
    ("seq", "Sequência", "Cinco cartas em sequência, de naipes misturados.", "9c 8d 7h 6s 5c", "11111", 4.62),
    ("trinca", "Trinca", "Três cartas do mesmo valor.", "7d 7h 7c Ks 2d", "11100", 4.83),
    ("dois", "Dois Pares", "Dois pares diferentes.", "Jh Js 4c 4d 9s", "11110", 23.5),
    ("par", "Um Par", "Duas cartas do mesmo valor.", "Ah Ad Kc 8s 3h", "11000", 43.8),
    ("alta", "Carta Alta", "Nada formado: vale a carta mais alta.", "As Jd 8c 5h 3s", "10000", 17.4),
]
ORDEM_SHORT = ["royal", "sf", "quadra", "flush", "full", "trinca", "seq", "dois", "par", "alta"]
EXTRAS_SHORT = {"flush": "No Short Deck o flush vale MAIS que o full house: com 36 cartas fica mais difícil juntar 5 do mesmo naipe.",
                "trinca": "No Short Deck a trinca ganha da sequência.", "seq": "A menor sequência aqui é A-6-7-8-9 (o Ás vira o \"5\")."}
EXEMPLO_SHORT = {"seq": ("9c 8d 7h 6s Ac", "11111")}

DUELOS_PADRAO = {
    "holdem": [
        ("Kicker: quem desempata", "Ah Kd", "Ac Qs", "As 8d 5c 3h 2s"),
        ("Flush × sequência", "Tc 9c", "Ah 3c", "8h 7d 6h 2h Kh"),
        ("A mesa joga: divide o pote", "2c 3d", "7h 7s", "Ah Kh Qd Jc Ts"),
    ],
    "omaha": [
        ("Só 2 da mão: o 'flush' que não existe", "Ah 9c 8d 7s", "Kc Kd 6c 5d", "Kh Qh 5h 2h Tc"),
    ],
    "shortdeck": [
        ("Flush × full house", "Ah 9h", "Kc Kd", "Kh Th 7h Ts 6c"),
    ],
}
DESCRICAO_VAR = {"holdem": "Texas Hold'em: as suas 2 cartas + as 5 da mesa — vale o melhor jogo de 5.",
                 "omaha": "Omaha: 4 cartas na mão, mas você usa EXATAMENTE 2 delas + 3 da mesa.",
                 "omaha5": "PLO5: 5 cartas na mão, mas você usa EXATAMENTE 2 delas + 3 da mesa.",
                 "omaha6": "PLO6: 6 cartas na mão, mas você usa EXATAMENTE 2 delas + 3 da mesa.",
                 "shortdeck": "Short Deck (6+): o baralho começa no 6 — e o ranking muda."}


def opcoes_padrao() -> Dict[str, Any]:
    return {"tema": "preto_dourado", "formato": "16:9", "variante": "holdem", "ordem": "crescente", "duelos": True,
            "duelos_texto": "", "chances": True, "velocidade": 1.0, "sons": True, "fps": 30, "titulo": "", "logo": ""}


def normalizar(o: Any) -> Dict[str, Any]:
    out = opcoes_padrao()
    o = o if isinstance(o, dict) else {}
    if o.get("tema") in PR.TEMAS_CSS:
        out["tema"] = o["tema"]
    if o.get("formato") in PR.TAMANHOS:
        out["formato"] = o["formato"]
    out["variante"] = PM.variante(o.get("variante") or "holdem")
    out["ordem"] = "decrescente" if o.get("ordem") == "decrescente" else "crescente"
    for k in ("duelos", "chances", "sons"):
        if k in o:
            out[k] = o[k] is True or str(o[k]).lower() in ("1", "true", "on", "sim")
    out["duelos_texto"] = str(o.get("duelos_texto") or "")[:3000]
    try:
        out["velocidade"] = max(0.5, min(2.5, float(o.get("velocidade") or 1.0)))
    except (TypeError, ValueError):
        pass
    if o.get("fps") in (24, 30, 60, "24", "30", "60"):
        out["fps"] = int(o["fps"])
    out["titulo"] = " ".join(str(o.get("titulo") or "").split())[:80]
    out["logo"] = " ".join(str(o.get("logo") or "").split())[:40]
    return out


def ler_duelos(txt: str) -> List[tuple]:
    """Uma linha por duelo: "título: As Kd vs Qh Qs | Ah 7c 2d 9s 3h" (o título é opcional)."""
    out = []
    for linha in str(txt or "").splitlines():
        linha = linha.split("#", 1)[0].strip()
        if not linha or "|" not in linha or " vs " not in linha.lower():
            continue
        tit = ""
        if ":" in linha.split("|")[0]:
            tit, linha = linha.split(":", 1)
        maos, board = linha.split("|", 1)
        a, b = maos.lower().split(" vs ", 1) if " vs " in maos.lower() else (maos, "")
        out.append((tit.strip() or "Duelo", a.strip(), b.strip(), board.strip()))
    return out


def _duelo(tit: str, a: str, b: str, board: str, var: str) -> Dict[str, Any]:
    ca, cb, cbo = PM.cartas(a), PM.cartas(b), PM.cartas(board)
    n = PM.VARIANTES[var]["cartas"]
    if len(ca) != n or len(cb) != n:
        raise PM.PokerErro(f"Duelo “{tit}”: no {PM.VARIANTES[var]['nome']} cada mão tem {n} cartas.")
    if len(cbo) != 5:
        raise PM.PokerErro(f"Duelo “{tit}”: a mesa precisa de 5 cartas.")
    todas = ca + cb + cbo
    if len(set(todas)) != len(todas):
        raise PM.PokerErro(f"Duelo “{tit}”: carta repetida.")
    fa, va, ma = PM.avaliar_mao(ca, cbo, var)
    fb, vb, mb = PM.avaliar_mao(cb, cbo, var)
    venc = "a" if fa > fb else "b" if fb > fa else "split"
    return {"tipo": "duelo", "titulo": tit, "board": cbo,
            "a": {"cartas": ca, "jogo": PM.nome_jogo(va), "melhor": ma}, "b": {"cartas": cb, "jogo": PM.nome_jogo(vb), "melhor": mb},
            "venc": venc}


def montar(op: Any) -> Dict[str, Any]:
    """As cenas + a linha do tempo + a narração de cada cena."""
    op = normalizar(op)
    var = op["variante"]
    curto = PM.VARIANTES[var]["curto"]
    vel = op["velocidade"]
    cats = {c[0]: c for c in CATEGORIAS}
    ordem_forte = ORDEM_SHORT if curto else [c[0] for c in CATEGORIAS]   # da mais forte pra mais fraca
    escada = [cats[k][1] for k in ordem_forte]
    cenas: List[Dict[str, Any]] = []
    nome_var = PM.VARIANTES[var]["nome"]
    titulo = op["titulo"] or f"Ranking das mãos — {nome_var}"
    cenas.append({"tipo": "intro", "dur": 3.0, "titulo": titulo, "sub": DESCRICAO_VAR.get(var, ""),
                  "fala": f"{titulo}. {DESCRICAO_VAR.get(var, '')} Bora ver qual mão ganha de qual."})
    seq = list(range(len(ordem_forte)))
    if op["ordem"] == "crescente":
        seq.reverse()
    for pos in seq:
        k = ordem_forte[pos]
        _, nome, desc, ex, dest, prob = cats[k]
        if curto and k in EXEMPLO_SHORT:
            ex, dest = EXEMPLO_SHORT[k]
        extra = EXTRAS_SHORT.get(k, "") if curto else ""
        cs = PM.cartas(ex)
        chance = prob if (op["chances"] and not curto and not PM.VARIANTES[var]["omaha"]) else None
        um_em = round(100.0 / prob) if chance else 0
        fala = f"Número {pos + 1}: {nome}. {desc}" + (f" {extra}" if extra else "") + (
            f" Sai em mais ou menos {str(prob).replace('.', ',')}% das mãos." if chance else "")
        cenas.append({"tipo": "cat", "dur": 4.6 if not extra else 6.0, "pos": pos, "rank": pos + 1, "nome": nome, "desc": desc,
                      "extra": extra, "cartas": cs, "dest": [x == "1" for x in dest], "chance": chance, "um_em": um_em, "fala": fala})
    if PM.VARIANTES[var]["omaha"]:
        cenas.append({"tipo": "regra", "dur": 6.5, "titulo": "A regra de ouro do Omaha",
                      "texto": "Exatamente 2 cartas da mão + 3 da mesa. Nem mais, nem menos.",
                      "fala": "A regra de ouro do Omaha: você usa exatamente duas cartas da mão e três da mesa. Quatro copas na "
                              "mesa e um Ás de copas na mão? Não é flush!"})
    if op["duelos"]:
        base = "omaha" if PM.VARIANTES[var]["omaha"] else var
        lista = ler_duelos(op["duelos_texto"]) or DUELOS_PADRAO.get(base, [])
        for tit, a, b, board in lista[:8]:
            try:
                d = _duelo(tit, a, b, board, var)
            except PM.PokerErro:
                if op["duelos_texto"]:
                    raise
                continue
            res = ("dividem o pote" if d["venc"] == "split" else
                   f"ganha a mão {'da esquerda' if d['venc'] == 'a' else 'da direita'}, com {d[d['venc']]['jogo']}")
            d.update(dur=7.5, fala=f"{tit}. De um lado, {d['a']['jogo']}; do outro, {d['b']['jogo']}. Resultado: {res}.")
            cenas.append(d)
    cenas.append({"tipo": "final", "dur": 4.0, "titulo": "Do mais forte ao mais fraco",
                  "fala": "Resumindo, do mais forte pro mais fraco: " + ", ".join(escada) + "."})
    t = 0.0
    for c in cenas:
        c["dur"] = round(c["dur"] / vel, 3)
        c["t0"] = round(t, 3)
        t += c["dur"]
    return {"op": op, "cenas": cenas, "escada": escada, "duracao": round(t, 3), "variante": var, "variante_nome": nome_var,
            "ncartas": PM.VARIANTES[var]["cartas"]}


def narracao(dados: Dict[str, Any]) -> str:
    return "\n\n".join(c["fala"] for c in dados["cenas"] if c.get("fala")) + "\n"


def pagina(dados: Dict[str, Any], fontes_prefixo: str, modo: str = "gravar") -> str:
    op = dados["op"]
    W, H = PR.TAMANHOS[op["formato"]]
    payload = dict(dados, W=W, H=H, tema=PR.TEMAS_CSS[op["tema"]], modo=modo)
    return (HTML.replace("/*FONTES*/", PR._fontes_css(fontes_prefixo))
            .replace("__DADOS__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__W__", str(W)).replace("__H__", str(H)))


def trilha(dados: Dict[str, Any], destino: str, pasta: str) -> Optional[str]:
    """Sons: whoosh na troca de cena, carta voando, brilho no destaque, vitória no duelo (sintetizados)."""
    eventos = []
    for c in dados["cenas"]:
        t0, d = c["t0"], c["dur"]
        eventos.append(("whoosh", t0))
        if c["tipo"] == "cat":
            eventos += [("carta", t0 + (0.25 + k * 0.12) * d / 4.6) for k in range(5)] + [("virar", t0 + 0.38 * d)]
        elif c["tipo"] == "duelo":
            eventos += [("carta", t0 + 0.04 * d + k * 0.05 * d) for k in range(5)] + [("virar", t0 + 0.6 * d), ("vitoria", t0 + 0.62 * d)]
        elif c["tipo"] == "regra":
            eventos += [("carta", t0 + 0.1 * d + k * 0.06 * d) for k in range(5)]
    falso = {"eventos": [], "duracao": dados["duracao"]}
    os.makedirs(pasta, exist_ok=True)
    arqs = {k: PR._som(k, os.path.join(pasta, f"_som_{k}.wav")) for k in {e[0] for e in eventos}}
    import subprocess
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", f"{falso['duracao'] + 0.5:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
    fc, mix = [], ["[0:a]"]
    for k, (tipo, t) in enumerate(eventos[:180], 1):
        cmd += ["-i", arqs[tipo]]
        ms = max(0, int(t * 1000))
        fc.append(f"[{k}:a]adelay={ms}|{ms}[s{k}]")
        mix.append(f"[s{k}]")
    fc.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0[a]")
    cmd += ["-filter_complex", ";".join(fc), "-map", "[a]", destino]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        r = subprocess.run([x.replace(":normalize=0", "") for x in cmd], capture_output=True, text=True, timeout=600)
    return destino if r.returncode == 0 and os.path.isfile(destino) else None


def gravar(op: Any, saida: str, on_log: Callable[[str], None] = lambda _m: None, parar: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
    dados = montar(op)
    op = dados["op"]
    W, H = PR.TAMANHOS[op["formato"]]
    tmp = tempfile.mkdtemp(prefix="poker_rank_")
    try:
        fontes = "file://" + os.path.join(PR.AQUI, "assets", "fonts", "dp").replace("\\", "/")
        video = os.path.join(tmp, "video.mp4")
        PR.gravar_pagina(pagina(dados, fontes), W, H, int(op["fps"]), dados["duracao"] + 0.3, video, on_log, parar, tmp, "🏆 desenhando o ranking")
        audio = trilha(dados, os.path.join(tmp, "sons.wav"), tmp) if op["sons"] else None
        on_log("📦 finalizando…")
        PR.juntar_audio(video, audio, saida)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dados


HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>ranking</title>
<style>
/*FONTES*/
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: __W__px; height: __H__px; overflow: hidden; background: #000; }
body.previa { width: auto; height: auto; background: #0b0b0b; overflow: auto; }
#palco { position: relative; width: __W__px; height: __H__px; overflow: hidden; font-family: 'DP Poppins', 'Segoe UI', Arial, sans-serif; }
body.previa #palco { transform-origin: 0 0; }
.abs { position: absolute; }
.carta { position: absolute; border-radius: 10%/7%; transform-style: preserve-3d; }
.carta .face, .carta .verso { position: absolute; inset: 0; border-radius: inherit; backface-visibility: hidden; }
.carta .face { background: linear-gradient(160deg, #ffffff, #eef2f7); box-shadow: 0 8px 18px #0008, inset 0 0 0 1px #0002; }
.carta .verso { transform: rotateY(180deg); box-shadow: 0 8px 18px #0008; }
.carta .r { position: absolute; left: 9%; top: 4%; font-weight: 800; line-height: 1; }
.carta .n1 { position: absolute; left: 10%; font-weight: 700; line-height: 1; }
.carta .n2 { position: absolute; right: 7%; bottom: 4%; line-height: 1; }
.txt { position: absolute; white-space: nowrap; }
.cx { transform: translateX(-50%); text-align: center; }
#controles { position: fixed; left: 0; right: 0; bottom: 0; display: flex; gap: 10px; align-items: center; padding: 8px 12px; background: #000c; color: #fff; font: 14px sans-serif; z-index: 10; }
#controles input[type=range] { flex: 1; }
</style></head><body><div id="palco"></div>
<script>
const D = __DADOS__;
const T = D.tema, W = D.W, H = D.H;
const palco = document.getElementById('palco');
const S = Math.min(W, H) / 1080, VERT = H > W * 1.2, QUAD = !VERT && H > W * 0.8, LARGO = !VERT && !QUAD;
const el = (tag, css, pai) => { const e = document.createElement(tag); if (css) e.style.cssText = css; (pai || palco).appendChild(e); return e; };
const lerp = (a, b, p) => a + (b - a) * p, clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const ease = p => p < 0 ? 0 : p > 1 ? 1 : (p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
const back = p => { p = clamp(p, 0, 1); const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2); };
const fase = (p, a, b) => clamp((p - a) / (b - a), 0, 1);

// ---- fundo (gradiente + brilhos + feltro sugerido)
palco.style.background = `radial-gradient(ellipse at 50% 40%, ${T.fundo2}, ${T.fundo1} 75%)`;
const halo = el('div', `position:absolute;left:50%;top:${VERT ? 42 : 50}%;width:${W * 1.1}px;height:${W * 1.1}px;transform:translate(-50%,-50%);border-radius:50%;background:radial-gradient(${T.feltro1}55, transparent 60%)`);
for (let k = 0; k < 46; k++) { const x = (k * 97) % 100, y = (k * 61) % 100, r = 1 + (k % 3);
  el('div', `position:absolute;left:${x}%;top:${y}%;width:${r * S * 2}px;height:${r * S * 2}px;border-radius:50%;background:${T.acento};opacity:${0.05 + (k % 5) * 0.025}`); }
const linhas = el('div', `position:absolute;inset:0;background:repeating-linear-gradient(115deg, transparent 0 ${60 * S}px, ${T.acento}08 ${60 * S}px ${62 * S}px)`);

// ---- cartas
const COR4 = { s: '#111827', h: '#dc2626', d: '#2563eb', c: '#16a34a' }, COR2 = { s: '#111', h: '#d61f1f', d: '#d61f1f', c: '#111' };
const SIMB = { s: '♠', h: '♥', d: '♦', c: '♣' };
const corNaipe = n => T.naipes === 'quatro' ? COR4[n] : T.naipes === 'mono' ? (n === 'h' || n === 'd' ? '#6b6b6b' : '#111') : T.naipes === 'ouro' ? (n === 'h' || n === 'd' ? '#b8860b' : '#111') : COR2[n];
function novaCarta(w) {
  const c = el('div', `width:${w}px;height:${w * 1.4}px;display:none`); c.className = 'carta';
  const f = el('div', '', c); f.className = 'face';
  const v = el('div', `background:repeating-linear-gradient(45deg, ${T.verso1} 0 ${w * 0.06}px, ${T.verso2} ${w * 0.06}px ${w * 0.12}px);border:${w * 0.05}px solid #fff`, c); v.className = 'verso';
  c._w = w; c._face = f; c._verso = v; c._cod = null; return c;
}
function setCarta(c, cod) {
  if (c._cod === cod) return; c._cod = cod; const w = c._w; c._face.innerHTML = ''; if (!cod) return;
  const r = cod[0] === 'T' ? '10' : cod[0], n = cod[1], cor = corNaipe(n);
  el('div', `font-size:${w * 0.42}px;color:${cor}`, c._face).className = 'r'; c._face.lastChild.textContent = r;
  el('div', `top:${w * 0.48}px;font-size:${w * 0.3}px;color:${cor}`, c._face).className = 'n1'; c._face.lastChild.textContent = SIMB[n];
  el('div', `font-size:${w * 0.62}px;color:${cor}`, c._face).className = 'n2'; c._face.lastChild.textContent = SIMB[n];
}
function poe(c, x, y, aberta, rot, op, esc, brilho, cor) {
  if (op <= 0.001) { c.style.display = 'none'; return; }
  c.style.display = 'block'; c.style.opacity = op;
  c.style.left = (x - c._w / 2) + 'px'; c.style.top = (y - c._w * 0.7) + 'px';
  c.style.transform = `perspective(${1400 * S}px) rotateZ(${rot || 0}deg) rotateY(${(1 - aberta) * 180}deg) scale(${esc || 1})`;
  c._face.style.visibility = aberta > 0.5 ? 'visible' : 'hidden'; c._verso.style.visibility = aberta > 0.5 ? 'hidden' : 'visible';
  c._face.style.boxShadow = brilho ? `0 0 0 ${4 * S}px ${cor || T.valor}, 0 0 ${40 * S * brilho}px ${cor || T.valor}, 0 ${14 * S}px ${26 * S}px #000a` : '';
  c._face.style.filter = brilho < 0 ? `brightness(${1 + brilho * 0.55}) saturate(${1 + brilho * 0.6})` : '';
}
const CWG = (VERT ? 168 : QUAD ? 150 : 170) * S, CWP = (VERT ? 118 : QUAD ? 104 : 118) * S;
const grandes = Array.from({ length: 5 }, () => novaCarta(CWG));
const peq = Array.from({ length: 18 }, () => novaCarta(CWP));

// ---- textos
const tTit = el('div', `font-weight:900;color:${T.texto};text-shadow:0 ${4 * S}px ${18 * S}px #000a`); tTit.className = 'txt cx';
const tRank = el('div', `font-weight:900;color:${T.acento};letter-spacing:.08em`); tRank.className = 'txt cx';
const tDesc = el('div', `font-weight:600;color:${T.texto};white-space:normal;line-height:1.25`); tDesc.className = 'txt cx';
const tExtra = el('div', `font-weight:700;color:#111;background:${T.valor};border-radius:${14 * S}px;padding:${10 * S}px ${18 * S}px;white-space:normal;line-height:1.2`); tExtra.className = 'txt cx';
const tChance = el('div', `font-weight:800;color:${T.placa_txt};background:${T.placa};border:${2 * S}px solid ${T.acento};border-radius:999px;padding:${8 * S}px ${22 * S}px`); tChance.className = 'txt cx';
const barraF = el('div', `position:absolute;height:${10 * S}px;border-radius:99px;background:${T.borda2};overflow:hidden`);
const barraV = el('div', `height:100%;width:0;background:linear-gradient(90deg, ${T.acento}, ${T.valor})`, barraF);
const rotA = el('div', `font-weight:800;color:${T.texto}`); rotA.className = 'txt cx';
const rotB = el('div', `font-weight:800;color:${T.texto}`); rotB.className = 'txt cx';
const jogoA = el('div', `font-weight:800;border-radius:${12 * S}px;padding:${6 * S}px ${16 * S}px`); jogoA.className = 'txt cx';
const jogoB = el('div', `font-weight:800;border-radius:${12 * S}px;padding:${6 * S}px ${16 * S}px`); jogoB.className = 'txt cx';
const selo = el('div', `font-weight:900;color:#111;background:${T.valor};border-radius:${16 * S}px;padding:${8 * S}px ${26 * S}px;letter-spacing:.06em;z-index:5`); selo.className = 'txt cx';
const logo = el('div', `font-weight:800;color:${T.acento};letter-spacing:.25em;opacity:.7;font-size:${24 * S}px;bottom:${30 * S}px;left:50%`); logo.className = 'txt cx'; logo.textContent = (D.op.logo || '').toUpperCase();

// ---- a escada do ranking (lateral no 16:9, embaixo no 9:16)
const ESC = D.escada.length;
const escada = el('div', 'position:absolute'), escRows = [];
const ER = LARGO ? { x: 60 * S, y: 170 * S, w: 470 * S, h: 74 * S } : VERT ? { x: 70 * S, y: H - 640 * S, w: (W - 160 * S) / 2, h: 92 * S } : null;
if (ER) D.escada.forEach((nome, i) => {
  const col = VERT ? (i < 5 ? 0 : 1) : 0, lin = VERT ? i % 5 : i;
  const r = el('div', `position:absolute;left:${ER.x + col * (ER.w + 20 * S)}px;top:${ER.y + lin * ER.h}px;width:${ER.w}px;height:${ER.h - 10 * S}px;border-radius:${12 * S}px;display:flex;align-items:center;gap:${14 * S}px;padding:0 ${18 * S}px;font-size:${(VERT ? 30 : 28) * S}px;font-weight:700;color:${T.texto};background:${T.placa};border:${2 * S}px solid ${T.borda2}`, escada);
  const n = el('span', `font-weight:900;color:${T.acento};min-width:${44 * S}px`, r); n.textContent = (i + 1) + '';
  const tx = el('span', '', r); tx.textContent = nome; escRows.push(r);
});
const escCursor = ER ? el('div', `position:absolute;width:${ER.w}px;height:${ER.h - 10 * S}px;border-radius:${12 * S}px;border:${3 * S}px solid ${T.valor};box-shadow:0 0 ${26 * S}px ${T.valor};pointer-events:none`, escada) : null;

// ---- layout da área principal
const MX = LARGO ? W * 0.62 : W / 2;
const L = VERT ? { tit: H * 0.12, rank: H * 0.085, cartas: H * 0.33, desc: H * 0.43, extra: H * 0.5, chance: H * 0.575 }
  : QUAD ? { tit: H * 0.16, rank: H * 0.09, cartas: H * 0.43, desc: H * 0.64, extra: H * 0.74, chance: H * 0.84 }
    : { tit: H * 0.19, rank: H * 0.11, cartas: H * 0.47, desc: H * 0.68, extra: H * 0.78, chance: H * 0.87 };

const CENAS = D.cenas;
function cenaEm(t) { let k = 0; for (let i = 0; i < CENAS.length; i++) if (CENAS[i].t0 <= t) k = i; return k; }
function revelados(k) { const r = new Set(); for (let i = 0; i <= k; i++) if (CENAS[i].tipo === 'cat') r.add(CENAS[i].pos); return r; }
function posAnterior(k) { for (let i = k - 1; i >= 0; i--) if (CENAS[i].tipo === 'cat') return CENAS[i].pos; return null; }
const esconde = els => els.forEach(e => e.style.opacity = 0);

window.render = function (t) {
  const k = cenaEm(t), c = CENAS[k], p = clamp((t - c.t0) / c.dur, 0, 1);
  const entra = ease(fase(p, 0, 0.12)), sai = 1 - ease(fase(p, 0.9, 1));
  const vis = Math.min(entra, sai);
  [...grandes, ...peq].forEach(x => x.style.display = 'none');
  esconde([tTit, tRank, tDesc, tExtra, tChance, barraF, rotA, rotB, jogoA, jogoB, selo]);
  halo.style.transform = `translate(-50%,-50%) scale(${1 + 0.04 * Math.sin(t * 0.8)})`;
  linhas.style.backgroundPosition = `${t * 18 * S}px 0`;
  // escada
  if (ER) {
    const rev = revelados(k), mostrarEsc = c.tipo === 'cat' || c.tipo === 'final' || (c.tipo === 'intro' && p > 0.5);
    escada.style.opacity = c.tipo === 'duelo' || c.tipo === 'regra' || c.tipo === 'intro' ? 0 : 1;
    escRows.forEach((r, i) => {
      const on = c.tipo === 'final' || rev.has(i) || D.op.ordem === 'decrescente';
      r.style.opacity = on ? 1 : 0.28;
      r.style.transform = `translateX(${c.tipo === 'final' ? 0 : (c.tipo === 'cat' && c.pos === i ? 14 * S : 0)}px)`;
      r.style.background = c.tipo === 'cat' && c.pos === i ? T.acento + '33' : T.placa;
    });
    if (c.tipo === 'cat') {
      const de = posAnterior(k), pp = ease(fase(p, 0, 0.14)), cur = de == null ? c.pos : lerp(de, c.pos, pp);
      const col = VERT ? (cur < 4.5 ? 0 : 1) : 0, lin = VERT ? cur % 5 : cur;
      escCursor.style.display = 'block'; escCursor.style.left = (ER.x + col * (ER.w + 20 * S) + 14 * S) + 'px'; escCursor.style.top = (ER.y + lin * ER.h) + 'px';
    } else escCursor.style.display = 'none';
    if (!mostrarEsc && c.tipo === 'intro') escada.style.opacity = 0;
  }
  if (c.tipo === 'intro') {
    const a = ease(fase(p, 0.05, 0.3));
    tTit.textContent = c.titulo; tTit.style.fontSize = (VERT ? 76 : 84) * S + 'px'; tTit.style.whiteSpace = 'normal'; tTit.style.width = W * 0.86 + 'px';
    tTit.style.left = W / 2 + 'px'; tTit.style.top = (VERT ? H * 0.3 : H * 0.3) + 'px'; tTit.style.opacity = a * sai;
    tTit.style.transform = `translateX(-50%) translateY(${(1 - a) * 40 * S}px) scale(${lerp(1.15, 1, a)})`;
    tDesc.textContent = c.sub; tDesc.style.fontSize = 38 * S + 'px'; tDesc.style.width = W * 0.78 + 'px'; tDesc.style.left = W / 2 + 'px';
    tDesc.style.top = (VERT ? H * 0.48 : H * 0.58) + 'px'; tDesc.style.opacity = ease(fase(p, 0.25, 0.45)) * sai;
    // 5 cartas em leque girando de fundo
    grandes.forEach((g, i) => { setCarta(g, ['As', 'Ks', 'Qs', 'Js', 'Ts'][i]); const q = back(fase(p, 0.1 + i * 0.05, 0.4 + i * 0.05));
      poe(g, W / 2 + (i - 2) * CWG * 0.55, (VERT ? H * 0.68 : H * 0.84) + Math.abs(i - 2) * 12 * S, ease(fase(p, 0.3 + i * 0.04, 0.5 + i * 0.04)), (i - 2) * 9, q * sai, 0.8, 0); });
    tTit.style.transform += ''; return;
  }
  if (c.tipo === 'cat') {
    const sp = CWG * 1.12;
    tRank.textContent = '#' + c.rank; tRank.style.fontSize = 54 * S + 'px'; tRank.style.left = MX + 'px'; tRank.style.top = L.rank + 'px';
    tRank.style.opacity = vis; tRank.style.transform = `translateX(-50%) scale(${lerp(1.6, 1, back(fase(p, 0, 0.12)))})`;
    tTit.textContent = c.nome.toUpperCase(); tTit.style.whiteSpace = 'nowrap'; tTit.style.width = 'auto'; tTit.style.fontSize = (VERT ? 92 : 96) * S + 'px';
    tTit.style.left = MX + 'px'; tTit.style.top = L.tit + 'px'; tTit.style.opacity = vis;
    tTit.style.transform = `translateX(-50%) translateX(${(1 - entra) * 120 * S - (1 - sai) * 120 * S}px)`;
    const destaque = ease(fase(p, 0.36, 0.48));
    c.cartas.forEach((cod, i) => {
      const g = grandes[i]; setCarta(g, cod);
      const q = ease(fase(p, 0.05 + i * 0.026, 0.16 + i * 0.026));
      const x0 = MX + (i - 2) * sp, y0 = L.cartas;
      const x = lerp(x0 + W * 0.35, x0, q) - (1 - sai) * W * 0.3, ab = ease(fase(p, 0.14 + i * 0.026, 0.26 + i * 0.026));
      const on = c.dest[i];
      const y = y0 - (on ? 34 * S * destaque : 0) + (1 - q) * -60 * S;
      poe(g, x, y, ab, (1 - q) * 25, Math.min(q, sai), 1 + (on ? 0.06 * destaque : 0), on ? destaque : -destaque * 0.9);
    });
    tDesc.textContent = c.desc; tDesc.style.fontSize = (VERT ? 40 : 38) * S + 'px'; tDesc.style.width = (LARGO ? W * 0.62 : W * 0.86) + 'px';
    tDesc.style.left = MX + 'px'; tDesc.style.top = L.desc + 'px'; tDesc.style.opacity = ease(fase(p, 0.3, 0.42)) * sai;
    if (c.extra) { tExtra.textContent = c.extra; tExtra.style.fontSize = 30 * S + 'px'; tExtra.style.width = (LARGO ? W * 0.56 : W * 0.84) + 'px';
      tExtra.style.left = MX + 'px'; tExtra.style.top = L.extra + 'px'; tExtra.style.opacity = ease(fase(p, 0.48, 0.58)) * sai; }
    if (c.chance) {
      const q = ease(fase(p, 0.5, 0.62));
      tChance.textContent = String(c.chance).replace('.', ',') + '% das mãos · 1 em ' + c.um_em.toLocaleString('pt-BR');
      tChance.style.fontSize = 30 * S + 'px'; tChance.style.left = MX + 'px'; tChance.style.top = (c.extra ? L.chance + 30 * S : L.chance) + 'px'; tChance.style.opacity = q * sai;
      const bw = (LARGO ? W * 0.4 : W * 0.7); barraF.style.width = bw + 'px'; barraF.style.left = (MX - bw / 2) + 'px';
      barraF.style.top = ((c.extra ? L.chance + 30 * S : L.chance) + 74 * S) + 'px'; barraF.style.opacity = q * sai;
      barraV.style.width = (100 * Math.min(1, Math.pow(c.chance / 50, 0.5)) * ease(fase(p, 0.55, 0.8))) + '%';
    }
    return;
  }
  if (c.tipo === 'duelo' || c.tipo === 'regra') {
    tTit.textContent = c.titulo; tTit.style.whiteSpace = 'normal'; tTit.style.width = W * 0.9 + 'px'; tTit.style.fontSize = (VERT ? 64 : 60) * S + 'px';
    tTit.style.left = W / 2 + 'px'; tTit.style.top = (VERT ? H * 0.07 : H * 0.07) + 'px'; tTit.style.opacity = vis; tTit.style.transform = 'translateX(-50%)';
    const board = c.tipo === 'regra' ? ['Kh', 'Qh', '5h', '2h', 'Tc'] : c.board;
    const maoA = c.tipo === 'regra' ? (D.ncartas === 4 ? ['Ah', '9c', '8d', '7s'] : D.ncartas === 5 ? ['Ah', '9c', '8d', '7s', '3c'] : ['Ah', '9c', '8d', '7s', '3c', '4d']) : c.a.cartas;
    const maoB = c.tipo === 'regra' ? null : c.b.cartas;
    const by = VERT ? H * 0.47 : QUAD ? H * 0.52 : H * 0.5, bsp = CWP * 1.1;
    let n = 0;
    const melhorA = c.tipo === 'regra' ? null : c.a.melhor, melhorB = c.tipo === 'regra' ? null : c.b.melhor;
    const fA = fase(p, 0.36, 0.42), fB = fase(p, 0.48, 0.54), fV = fase(p, 0.6, 0.66);
    const realce = (cod, lado) => {   // quanto a carta brilha agora (e de que cor)
      if (c.tipo === 'regra') return [p > 0.45 ? (cod[1] === 'h' ? (cod === 'Ah' ? ease(fase(p, 0.45, 0.5)) : 0.6) : -0.6) : 0, cod === 'Ah' ? '#ef4444' : T.valor];
      const emA = melhorA.includes(cod), emB = melhorB.includes(cod);
      if (p >= 0.6) { const v = c.venc === 'split' ? (emA || emB) : (c.venc === 'a' ? emA : emB); return [v ? ease(fV) : -ease(fV), T.valor]; }
      if (p >= 0.48) return [emB ? ease(fB) : -0.5 * ease(fB), '#60a5fa'];
      if (p >= 0.36) return [emA ? ease(fA) : -0.5 * ease(fA), '#f472b6'];
      return [0, T.valor];
    };
    board.forEach((cod, i) => { const g = peq[n++]; setCarta(g, cod); const q = ease(fase(p, 0.16 + i * 0.03, 0.24 + i * 0.03));
      const [r, cor] = realce(cod); poe(g, W / 2 + (i - 2) * bsp, by + (r > 0 ? -18 * S * r : 0), ease(fase(p, 0.2 + i * 0.03, 0.28 + i * 0.03)), 0, Math.min(q, sai), 1, r, cor); });
    const lados = c.tipo === 'regra' ? [['a', maoA]] : [['a', maoA], ['b', maoB]];
    lados.forEach(([lado, mao]) => {
      const nn = mao.length, esp = nn <= 2 ? CWP * 1.05 : CWP * 0.62;
      const PILHA = !LARGO;   // 9:16 e 1:1: mão A em cima, mesa no meio, mão B embaixo
      const cx = c.tipo === 'regra' ? W / 2 : PILHA ? W / 2 : (lado === 'a' ? W * 0.14 : W * 0.86);
      const cy = c.tipo === 'regra' ? (VERT ? H * 0.72 : H * 0.8) : VERT ? (lado === 'a' ? H * 0.25 : H * 0.69) : QUAD ? (lado === 'a' ? H * 0.255 : H * 0.765) : by;
      const cxx = c.tipo !== 'regra' && !VERT ? cx : cx;
      mao.forEach((cod, i) => { const g = peq[n++]; setCarta(g, cod); const q = ease(fase(p, 0.03 + i * 0.02 + (lado === 'b' ? 0.05 : 0), 0.1 + i * 0.02 + (lado === 'b' ? 0.05 : 0)));
        const [r, cor] = realce(cod, lado);
        poe(g, cxx + (i - (nn - 1) / 2) * esp, cy + (r > 0 ? -18 * S * r : 0), ease(fase(p, 0.1 + (lado === 'b' ? 0.05 : 0), 0.16 + (lado === 'b' ? 0.05 : 0))), (i - (nn - 1) / 2) * (nn <= 2 ? 6 : 4), Math.min(q, sai), 1.08, r, cor); });
      const rot = lado === 'a' ? rotA : rotB, jg = lado === 'a' ? jogoA : jogoB;
      if (c.tipo === 'regra') return;
      rot.textContent = lado === 'a' ? 'MÃO A' : 'MÃO B'; rot.style.fontSize = 28 * S + 'px'; rot.style.left = cx + 'px'; rot.style.top = (cy - CWP * 1.25) + 'px'; rot.style.opacity = vis * 0.8;
      rot.style.color = lado === 'a' ? '#f472b6' : '#60a5fa';
      const info = c[lado], qq = ease(lado === 'a' ? fA : fB);
      jg.textContent = info.jogo; jg.style.fontSize = 30 * S + 'px'; jg.style.left = cx + 'px'; jg.style.top = (cy + CWP * 0.95) + 'px'; jg.style.opacity = qq * sai;
      const ganhou = c.venc === lado || c.venc === 'split';
      jg.style.background = p >= 0.6 && ganhou ? T.valor : T.placa; jg.style.color = p >= 0.6 && ganhou ? '#111' : T.placa_txt;
      jg.style.filter = p >= 0.6 && !ganhou ? 'brightness(.6)' : 'none';
    });
    if (c.tipo === 'regra') {
      tDesc.textContent = c.texto; tDesc.style.fontSize = 38 * S + 'px'; tDesc.style.width = W * 0.8 + 'px'; tDesc.style.left = W / 2 + 'px';
      tDesc.style.top = (VERT ? H * 0.17 : H * 0.2) + 'px'; tDesc.style.opacity = ease(fase(p, 0.08, 0.16)) * sai;
      selo.textContent = '❌ NÃO É FLUSH — só 1 copas na mão'; selo.style.background = '#ef4444'; selo.style.color = '#fff';
      selo.style.fontSize = 40 * S + 'px'; selo.style.left = W / 2 + 'px'; selo.style.top = (VERT ? H * 0.58 : H * 0.63) + 'px';
      selo.style.opacity = ease(fase(p, 0.55, 0.62)) * sai; selo.style.transform = `translateX(-50%) scale(${lerp(1.4, 1, back(fase(p, 0.55, 0.65)))})`;
      return;
    }
    const sv = ease(fV);
    selo.style.background = T.valor; selo.style.color = '#111';
    selo.textContent = c.venc === 'split' ? '🤝 EMPATE — DIVIDEM O POTE' : (c.venc === 'a' ? '← MÃO A VENCE' : 'MÃO B VENCE →');
    if (!LARGO) selo.textContent = c.venc === 'split' ? '🤝 EMPATE — DIVIDEM O POTE' : (c.venc === 'a' ? '▲ MÃO A VENCE' : '▼ MÃO B VENCE');
    selo.style.fontSize = (QUAD ? 40 : 46) * S + 'px'; selo.style.left = W / 2 + 'px'; selo.style.top = (VERT ? H * 0.83 : QUAD ? H * 0.925 : H * 0.72) + 'px';
    selo.style.opacity = sv * sai; selo.style.transform = `translateX(-50%) scale(${lerp(1.5, 1, back(fV))})`;
    return;
  }
  if (c.tipo === 'final') {
    tTit.textContent = c.titulo.toUpperCase(); tTit.style.whiteSpace = 'nowrap'; tTit.style.width = 'auto'; tTit.style.fontSize = (VERT ? 60 : 64) * S + 'px';
    tTit.style.left = MX + 'px'; tTit.style.top = (VERT ? H * 0.12 : QUAD ? H * 0.38 : H * 0.3) + 'px'; tTit.style.opacity = vis; tTit.style.transform = 'translateX(-50%)';
    if (!ER) { tDesc.textContent = D.escada.map((n, i) => (i + 1) + '. ' + n).join('  ·  '); tDesc.style.fontSize = 32 * S + 'px'; tDesc.style.width = W * 0.86 + 'px';
      tDesc.style.left = W / 2 + 'px'; tDesc.style.top = H * 0.55 + 'px'; tDesc.style.opacity = vis; }
    if (!QUAD) grandes.forEach((g, i) => { setCarta(g, ['As', 'Ks', 'Qs', 'Js', 'Ts'][i]); const q = back(fase(p, 0.08 + i * 0.04, 0.3 + i * 0.04));
      poe(g, MX + (i - 2) * CWG * 0.62, (VERT ? H * 0.38 : H * 0.66) + Math.abs(i - 2) * 14 * S, ease(fase(p, 0.2 + i * 0.04, 0.35 + i * 0.04)), (i - 2) * 8, q * sai, 0.85, ease(fase(p, 0.5, 0.6)) * 0.8); });
    if (ER) escRows.forEach((r, i) => { const q = ease(fase(p, 0.05 + i * 0.04, 0.15 + i * 0.04)); r.style.transform = `translateX(${(1 - q) * -40 * S}px) scale(${1 + 0.05 * Math.sin(Math.PI * q)})`; r.style.boxShadow = q > 0.5 && q < 1 ? `0 0 ${20 * S}px ${T.acento}` : 'none'; });
  }
};
window.render(0);
window.pronto = true;
if (D.modo === 'previa') {
  document.body.className = 'previa';
  const ctl = el('div', '', document.body); ctl.id = 'controles';
  const bt = el('button', '', ctl); bt.textContent = '⏸';
  const rg = el('input', '', ctl); rg.type = 'range'; rg.min = 0; rg.max = D.duracao; rg.step = 0.01; rg.value = 0;
  const lb = el('span', '', ctl);
  let tocando = true, t0 = performance.now(), base = 0;
  const ajustar = () => { const e = Math.min(innerWidth / W, (innerHeight - 44) / H); palco.style.transform = `scale(${e})`; };
  ajustar(); addEventListener('resize', ajustar);
  bt.onclick = () => { tocando = !tocando; bt.textContent = tocando ? '⏸' : '▶'; base = +rg.value; t0 = performance.now(); };
  rg.oninput = () => { base = +rg.value; t0 = performance.now(); window.render(base); };
  const laco = () => { if (tocando) { let t = base + (performance.now() - t0) / 1000; if (t > D.duracao + 0.3) { base = 0; t0 = performance.now(); t = 0; } rg.value = t; window.render(t); lb.textContent = t.toFixed(1) + ' / ' + D.duracao.toFixed(1) + ' s'; } requestAnimationFrame(laco); };
  requestAnimationFrame(laco);
}
</script></body></html>"""
