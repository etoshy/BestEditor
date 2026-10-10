"""
Gráficos animados com os dados da narração (pedidos pela IA no prompt de
edição ou criados à mão no Estúdio):

  barras · barras_h · linha · pizza · rosca · comparacao · numero · progresso

Cada gráfico: {"id", "tipo", "titulo", "dados": [{"rotulo", "valor"}],
"unidade" ("%", "R$", "mi", "mil", "km"…), "fonte" (rodapé), "start", "end",
"posicao" (centro | esquerda | direita | baixo | tela_cheia), "destaque"
(índice da barra/fatia em evidência), "cor" (opcional, #RRGGBB)}.

Os quadros são desenhados com o PIL (barras crescendo, linha se desenhando,
fatias girando, números contando), viram um .mov com transparência e entram
por cima do vídeo no tempo certo. A prévia do Estúdio é o último quadro.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

_AQUI = os.path.dirname(os.path.abspath(__file__))
FONTES = os.path.join(_AQUI, "assets", "fonts", "dp")
FPS = 30
TIPOS = {
    "barras": "Barras", "barras_h": "Barras deitadas", "linha": "Linha (evolução)", "pizza": "Pizza",
    "rosca": "Rosca", "comparacao": "Comparação (A × B)", "numero": "Número grande", "progresso": "Porcentagem (anel)",
}
POSICOES = {"centro": "Centro", "esquerda": "Esquerda", "direita": "Direita", "baixo": "Embaixo", "tela_cheia": "Tela cheia"}
ENTRADA_S, SAIDA_S = 1.1, 0.35
ESQUEMAS = {"paleta": "Tons da paleta", "unica": "Uma cor só", "mono": "Monocromático (claro→escuro)", "arcoiris": "Cores vivas variadas", "por_item": "Uma cor por item (escolhida)"}
CARTOES = {"escuro": "Cartão escuro", "claro": "Cartão claro", "transparente": "Sem cartão (só sombra)"}
_ARCOIRIS = [(239, 71, 111), (255, 209, 102), (6, 214, 160), (17, 138, 178), (155, 93, 229), (255, 127, 80), (46, 196, 182), (241, 91, 181), (0, 187, 249), (254, 228, 64), (0, 245, 212), (230, 57, 70)]


# ------------------------------------------------------------------ dados
def _num(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v or "").strip().replace("R$", "").replace("%", "").replace(" ", "")
    m = re.search(r"-?\d[\d.,]*", s)
    if not m:
        return None
    t = m.group(0)
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".") if len(t.split(",")[-1]) != 3 else t.replace(",", "")
    elif t.count(".") > 1 or (t.count(".") == 1 and len(t.split(".")[-1]) == 3 and len(t.split(".")[0]) <= 3 and not t.startswith("0")):
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def normalizar(g: Dict[str, Any], duracao: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Valida um gráfico (da IA ou do editor). None se não der pra desenhar."""
    if not isinstance(g, dict):
        return None
    tipo = g.get("tipo") if g.get("tipo") in TIPOS else "barras"
    dados = []
    for d in g.get("dados") or []:
        cor_it = None
        if isinstance(d, dict):
            v = _num(d.get("valor"))
            rot = str(d.get("rotulo") or d.get("label") or "").strip()[:40]
            cor_it = d.get("cor")
        elif isinstance(d, (list, tuple)) and len(d) >= 2:
            rot, v = str(d[0])[:40], _num(d[1])
            cor_it = d[2] if len(d) > 2 else None
        else:
            continue
        if v is not None:
            item = {"rotulo": rot, "valor": v}
            if re.fullmatch(r"#[0-9a-fA-F]{6}", str(cor_it or "")):
                item["cor"] = str(cor_it).upper()
            dados.append(item)
    dados = dados[:12]
    minimo = 1 if tipo in ("numero", "progresso") else 2
    if len(dados) < minimo:
        return None
    try:
        ini, fim = float(g.get("start", 0)), float(g.get("end", 0))
    except (TypeError, ValueError):
        return None
    if fim - ini < 1.5:
        fim = ini + 4.0
    if duracao:
        fim = min(fim, duracao)
        ini = max(0.0, min(ini, fim - 1.5))
    out = {
        "id": str(g.get("id") or hashlib.md5(json.dumps(g, sort_keys=True, default=str).encode()).hexdigest()[:8])[:16],
        "tipo": tipo, "titulo": str(g.get("titulo") or "").strip()[:80], "dados": dados,
        "unidade": str(g.get("unidade") or "").strip()[:8], "fonte": str(g.get("fonte") or "").strip()[:80],
        "start": round(ini, 2), "end": round(fim, 2),
        "posicao": g.get("posicao") if g.get("posicao") in POSICOES else ("tela_cheia" if tipo in ("pizza", "rosca") and len(dados) > 4 else "centro"),
    }
    try:
        if g.get("destaque") not in (None, ""):
            out["destaque"] = max(0, min(len(dados) - 1, int(g["destaque"])))
    except (TypeError, ValueError):
        pass
    for k in ("cor", "cor_secundaria", "fundo_cor", "texto_cor"):
        cor = str(g.get(k) or "")
        if re.fullmatch(r"#[0-9a-fA-F]{6}", cor):
            out[k] = cor.upper()
    if g.get("esquema") in ESQUEMAS:
        out["esquema"] = g["esquema"]
    if g.get("cartao") in CARTOES:
        out["cartao"] = g["cartao"]
    try:
        if g.get("fundo_opacidade") not in (None, ""):
            out["fundo_opacidade"] = round(max(0.0, min(1.0, float(g["fundo_opacidade"]))), 2)
    except (TypeError, ValueError):
        pass
    if g.get("origem") == "ia":  # reaplicar a resposta da IA troca estes em vez de duplicar
        out["origem"] = "ia"
    return out


def formatar(v: float, unidade: str = "", casas: Optional[int] = None) -> str:
    if casas is None:
        casas = 0 if abs(v) >= 100 or float(v).is_integer() else 1
    s = f"{abs(v):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    s = ("-" if v < 0 else "") + s
    u = unidade.strip()
    if not u:
        return s
    pre = next((m for m in ("R$", "US$", "$", "€", "£") if u.startswith(m)), "")
    suf = u[len(pre):].strip()
    out = f"{pre} {s}" if pre else s
    if suf == "%":
        return out + "%"
    return f"{out} {suf}" if suf else out


# ------------------------------------------------------------------ desenho
def _fonte(nome: str, tam: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(os.path.join(FONTES, nome), max(8, int(tam)))
    except OSError:
        return ImageFont.load_default()


def _rgb(c: str) -> Tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _cores(primaria: str, n: int) -> List[Tuple[int, int, int]]:
    """Série de cores: a primária e tons/vizinhos dela (harmonia com a paleta)."""
    import colorsys
    r, g, b = [x / 255 for x in _rgb(primaria)]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    s = max(s, 0.45)
    out = []
    passos = [0, 0.08, -0.08, 0.5, 0.16, -0.16, 0.58, 0.42, 0.25, -0.25, 0.66, 0.33]
    for k in range(n):
        hh = (h + passos[k % len(passos)]) % 1
        ll = min(0.7, max(0.42, l if k == 0 else 0.5 + (0.08 if k % 2 else -0.04)))
        rr, gg, bb = colorsys.hls_to_rgb(hh, ll, s)
        out.append((int(rr * 255), int(gg * 255), int(bb * 255)))
    return out


def _ease(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3


def caixa(g: Dict[str, Any], W: int, H: int) -> Tuple[int, int, int, int]:
    pos = g.get("posicao", "centro")
    if pos == "tela_cheia":
        return 0, 0, W, H
    if H > W * 1.2:  # vertical (9:16): não cabe coluna lateral — cartão largo, no terço certo
        if pos == "baixo":
            return int(W * 0.05), int(H * 0.56), int(W * 0.90), int(H * 0.30)
        if pos in ("esquerda", "direita"):
            return int(W * 0.05), int(H * 0.14), int(W * 0.90), int(H * 0.34)
        return int(W * 0.05), int(H * 0.27), int(W * 0.90), int(H * 0.40)
    if H > W * 0.8:  # quadrado (1:1)
        if pos == "esquerda":
            return int(W * 0.04), int(H * 0.12), int(W * 0.56), int(H * 0.62)
        if pos == "direita":
            return int(W * 0.40), int(H * 0.12), int(W * 0.56), int(H * 0.62)
        if pos == "baixo":
            return int(W * 0.08), int(H * 0.52), int(W * 0.84), int(H * 0.40)
        return int(W * 0.10), int(H * 0.16), int(W * 0.80), int(H * 0.62)
    if pos == "esquerda":
        return int(W * 0.04), int(H * 0.14), int(W * 0.44), int(H * 0.72)
    if pos == "direita":
        return int(W * 0.52), int(H * 0.14), int(W * 0.44), int(H * 0.72)
    if pos == "baixo":
        return int(W * 0.15), int(H * 0.56), int(W * 0.70), int(H * 0.38)
    return int(W * 0.18), int(H * 0.17), int(W * 0.64), int(H * 0.66)


def desenhar(g: Dict[str, Any], t: float, W: int, H: int, primaria: str = "#FFD60A"):
    """Quadro RGBA (só a caixa do gráfico) no instante t (s desde o início)."""
    from PIL import Image, ImageDraw
    x0, y0, cw, ch = caixa(g, W, H)
    dur = float(g["end"]) - float(g["start"])
    p = _ease(t / ENTRADA_S)
    alfa = min(1.0, t / 0.25, max(0.0, (dur - t) / SAIDA_S))
    im = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = min(W, H) / 1080  # mesmo tamanho de letra em 16:9, 9:16 e 1:1
    cor_p = _rgb(g.get("cor") or primaria)
    dados = g["dados"]
    unidade = g.get("unidade", "")
    cheia = g.get("posicao") == "tela_cheia"
    raio = int(26 * s)
    cartao = g.get("cartao") or "escuro"
    FUNDO = _rgb(g["fundo_cor"]) if g.get("fundo_cor") else ((244, 241, 234) if cartao == "claro" else (12, 13, 17))
    TXT = _rgb(g["texto_cor"]) if g.get("texto_cor") else ((22, 23, 27) if cartao == "claro" or sum(FUNDO) > 450 else (255, 255, 255))
    TXT2 = tuple(int(TXT[i] * 0.78 + FUNDO[i] * 0.22) for i in range(3))
    TXT3 = tuple(int(TXT[i] * 0.6 + FUNDO[i] * 0.4) for i in range(3))
    opac = g.get("fundo_opacidade")
    opac = (0.93 if cheia else 0.86) if opac is None else opac
    if cartao != "transparente":
        d.rounded_rectangle([0, 0, cw - 1, ch - 1], radius=0 if cheia else raio, fill=FUNDO + (int(255 * opac),),
                            outline=None if cheia else TXT + (34,), width=max(1, int(2 * s)))
    else:
        from PIL import ImageFilter
        sombra = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(sombra).rounded_rectangle([int(cw * 0.02), int(ch * 0.04), int(cw * 0.98), int(ch * 0.96)], radius=raio, fill=(0, 0, 0, int(150 * (opac if g.get("fundo_opacidade") is not None else 1))))
        im.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(int(40 * s))))
        d = ImageDraw.Draw(im)
    pad = int((70 if cheia else 40) * s)
    f_tit = _fonte("inter-Bold.ttf", (52 if cheia else 40) * s)
    f_rot = _fonte("inter-Regular.ttf", 24 * s)
    f_val = _fonte("inter-Bold.ttf", 28 * s)
    f_num = _fonte("bebas-neue-Bold.ttf", 150 * s if g["tipo"] in ("numero", "progresso") else 110 * s)
    topo = pad
    if g.get("titulo"):
        d.text((pad, topo), g["titulo"], font=f_tit, fill=TXT + (255,))
        # traço de acento sob o título, crescendo
        ty = topo + int((64 if cheia else 52) * s)
        d.rectangle([pad, ty, pad + int((cw - 2 * pad) * 0.18 * p), ty + max(2, int(5 * s))], fill=cor_p + (255,))
        topo = ty + int(34 * s)
    base = ch - pad - (int(30 * s) if g.get("fonte") else 0)
    if g.get("fonte"):
        d.text((pad, ch - pad - int(22 * s)), "Fonte: " + g["fonte"], font=_fonte("inter-Italic.ttf", 20 * s), fill=TXT3 + (255,))
    area = (pad, topo, cw - pad, base)
    esquema = g.get("esquema") or ("paleta" if g["tipo"] in ("pizza", "rosca") else "unica")
    n_d = len(dados)
    if esquema == "arcoiris":
        cores = [_ARCOIRIS[k % len(_ARCOIRIS)] for k in range(n_d)]
    elif esquema == "mono":
        cores = [tuple(int(c * (1.15 - 0.6 * k / max(1, n_d - 1)) if (1.15 - 0.6 * k / max(1, n_d - 1)) <= 1 else c + (255 - c) * 0.15) for c in cor_p) for k in range(n_d)]
    elif esquema == "unica":
        cores = [cor_p] * n_d
    else:
        cores = _cores(g.get("cor") or primaria, n_d)
    cores = [_rgb(it["cor"]) if it.get("cor") else cores[k] for k, it in enumerate(dados)]  # cor escolhida no item manda
    destaque = g.get("destaque")
    neutra = _rgb(g["cor_secundaria"]) if g.get("cor_secundaria") else (120, 124, 134)

    def cor_k(k):
        if destaque is None:
            return cores[k]
        return (cores[k] if dados[k].get("cor") else cor_p) if k == destaque else neutra

    tipo = g["tipo"]
    if tipo in ("barras", "barras_h", "comparacao"):
        maxv = max(abs(x["valor"]) for x in dados) or 1
        n = len(dados)
        if tipo == "barras" or (tipo == "comparacao" and n > 3):
            ax0, ay0, ax1, ay1 = area
            ay1 -= int(46 * s)
            ay0 += int(44 * s)
            vao = (ax1 - ax0) / n
            bw = vao * 0.62
            d.line([ax0, ay1, ax1, ay1], fill=TXT + (70,), width=max(1, int(2 * s)))
            for k, it in enumerate(dados):
                pk = _ease((t - k * 0.09) / ENTRADA_S)
                hh = (ay1 - ay0) * abs(it["valor"]) / maxv * pk
                bx = ax0 + vao * k + (vao - bw) / 2
                d.rounded_rectangle([bx, ay1 - hh, bx + bw, ay1], radius=int(6 * s), fill=cor_k(k) + (255,))
                val = formatar(it["valor"] * pk, unidade, None if pk >= 1 else 0)
                tw = d.textlength(val, font=f_val)
                d.text((bx + bw / 2 - tw / 2, ay1 - hh - int(40 * s)), val, font=f_val, fill=TXT + (int(255 * min(1, pk * 1.5)),))
                rot = it["rotulo"][:18]
                tw = d.textlength(rot, font=f_rot)
                d.text((bx + bw / 2 - tw / 2, ay1 + int(12 * s)), rot, font=f_rot, fill=TXT2 + (255,))
        elif tipo == "barras_h":
            ax0, ay0, ax1, ay1 = area
            rot_w = max(d.textlength(x["rotulo"][:22], font=f_rot) for x in dados) + int(20 * s)
            vao = (ay1 - ay0) / n
            bh = min(vao * 0.6, 70 * s)
            for k, it in enumerate(dados):
                pk = _ease((t - k * 0.08) / ENTRADA_S)
                yy = ay0 + vao * k + (vao - bh) / 2
                d.text((ax0, yy + bh / 2 - 14 * s), it["rotulo"][:22], font=f_rot, fill=TXT2 + (255,))
                larg = (ax1 - ax0 - rot_w - 150 * s) * abs(it["valor"]) / maxv * pk
                d.rounded_rectangle([ax0 + rot_w, yy, ax0 + rot_w + max(2, larg), yy + bh], radius=int(6 * s), fill=cor_k(k) + (255,))
                d.text((ax0 + rot_w + larg + 14 * s, yy + bh / 2 - 17 * s), formatar(it["valor"] * pk, unidade, None if pk >= 1 else 0), font=f_val, fill=TXT + (255,))
        else:  # comparação de 2–3 itens: números grandes contando + barras
            ax0, ay0, ax1, ay1 = area
            col = (ax1 - ax0) / n
            # números grandes ("139.820 km") num cartão estreito encostavam um no
            # outro: reduz a fonte até o maior valor caber na coluna (com folga).
            maior = max(d.textlength(formatar(x["valor"], unidade, None), font=f_num) for x in dados)
            if maior > col * 0.8:
                f_num = _fonte("bebas-neue-Bold.ttf", max(24, int(110 * s * col * 0.8 / maior)))
            for k, it in enumerate(dados):
                pk = _ease((t - k * 0.15) / ENTRADA_S)
                cx = ax0 + col * k + col / 2
                txt = formatar(it["valor"] * pk, unidade, None if pk >= 1 else 0)
                tw = d.textlength(txt, font=f_num)
                d.text((cx - tw / 2, ay0 + int(10 * s)), txt, font=f_num, fill=cor_k(k) + (255,) if destaque is not None else ((cores[k] if dados[k].get("cor") else (cor_p if k == 0 else TXT2)) + (255,)))
                rot = it["rotulo"][:24]
                tw = d.textlength(rot, font=f_tit)
                d.text((cx - tw / 2, ay0 + int(140 * s)), rot, font=_fonte("inter-Bold.ttf", 32 * s), fill=TXT2 + (255,))
                bh = (ay1 - ay0 - 210 * s) * abs(it["valor"]) / maxv * pk
                bw = col * 0.4
                d.rounded_rectangle([cx - bw / 2, ay1 - bh, cx + bw / 2, ay1], radius=int(6 * s),
                                    fill=(cor_k(k) if destaque is not None or dados[k].get("cor") or esquema != "unica" else (cor_p if k == 0 else neutra)) + (255,))
            if n == 2:
                vs = "×"
                tw = d.textlength(vs, font=f_tit)
                d.text(((ax0 + ax1) / 2 - tw / 2, ay0 + int(50 * s)), vs, font=f_tit, fill=TXT + (int(200 * p),))
    elif tipo == "linha":
        ax0, ay0, ax1, ay1 = area
        ay0 += int(50 * s)
        ay1 -= int(44 * s)
        vals = [x["valor"] for x in dados]
        mn, mx = min(vals), max(vals)
        if mx == mn:
            mx = mn + 1
        mn = min(0, mn) if mn >= 0 and mn < mx * 0.4 else mn - (mx - mn) * 0.15
        pts = [(ax0 + (ax1 - ax0) * k / (len(vals) - 1), ay1 - (ay1 - ay0) * (v - mn) / (mx - mn)) for k, v in enumerate(vals)]
        for k in range(4):
            yy = ay0 + (ay1 - ay0) * k / 3
            d.line([ax0, yy, ax1, yy], fill=TXT + (24,), width=1)
        tot = (len(pts) - 1) * p
        cheio = int(tot)
        visiveis = pts[:cheio + 1]
        if cheio < len(pts) - 1:
            fr = tot - cheio
            a_, b_ = pts[cheio], pts[cheio + 1]
            visiveis = visiveis + [(a_[0] + (b_[0] - a_[0]) * fr, a_[1] + (b_[1] - a_[1]) * fr)]
        if len(visiveis) >= 2:
            sombra = Image.new("RGBA", im.size, (0, 0, 0, 0))
            ImageDraw.Draw(sombra).polygon(visiveis + [(visiveis[-1][0], ay1), (visiveis[0][0], ay1)], fill=cor_p + (46,))
            im.alpha_composite(sombra)
            d = ImageDraw.Draw(im)
            d.line(visiveis, fill=cor_p + (255,), width=max(3, int(7 * s)), joint="curve")
        r_ = max(4, int(9 * s))
        for k, (px_, py_) in enumerate(pts):
            if k <= tot + 0.01:
                cor_pt = cores[k] if dados[k].get("cor") else (cor_p if (destaque is None and k == len(pts) - 1) or k == destaque else TXT2)
                d.ellipse([px_ - r_, py_ - r_, px_ + r_, py_ + r_], fill=cor_pt + (255,))
                if k == len(pts) - 1 or k == destaque or k == 0 or len(pts) <= 6:
                    val = formatar(vals[k], unidade)
                    tw = d.textlength(val, font=f_val)
                    d.text((px_ - tw / 2, py_ - int(48 * s)), val, font=f_val, fill=TXT + (255,))
            rot = dados[k]["rotulo"][:10]
            tw = d.textlength(rot, font=f_rot)
            d.text((px_ - tw / 2, ay1 + int(12 * s)), rot, font=f_rot, fill=TXT2 + (255,))
    elif tipo in ("pizza", "rosca"):
        ax0, ay0, ax1, ay1 = area
        tot = sum(abs(x["valor"]) for x in dados) or 1
        diam = min(ay1 - ay0, (ax1 - ax0) * 0.48)
        cx, cy = ax0 + diam / 2 + 10 * s, (ay0 + ay1) / 2
        caixa_p = [cx - diam / 2, cy - diam / 2, cx + diam / 2, cy + diam / 2]
        ang = -90.0
        limite = -90 + 360 * p
        for k, it in enumerate(dados):
            a = 360 * abs(it["valor"]) / tot
            fim_a = min(ang + a, limite)
            if fim_a > ang:
                deslocar = (destaque == k)
                if deslocar:
                    meio = math.radians((ang + ang + a) / 2)
                    dx, dy = math.cos(meio) * 14 * s, math.sin(meio) * 14 * s
                    d.pieslice([caixa_p[0] + dx, caixa_p[1] + dy, caixa_p[2] + dx, caixa_p[3] + dy], ang, fim_a, fill=cores[k] + (255,))
                else:
                    d.pieslice(caixa_p, ang, fim_a, fill=(cores[k] if destaque is None else (cor_p if k == destaque else cores[k])) + (255,),
                               outline=FUNDO + (255,), width=max(2, int(3 * s)))
            ang += a
        if tipo == "rosca":
            r_in = diam * 0.31
            d.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], fill=FUNDO + (255,))
            k0 = destaque if destaque is not None else max(range(len(dados)), key=lambda i: abs(dados[i]["valor"]))
            pc = formatar(100 * abs(dados[k0]["valor"]) / tot * p, "%")
            f_c = _fonte("bebas-neue-Bold.ttf", diam * 0.2)
            tw = d.textlength(pc, font=f_c)
            d.text((cx - tw / 2, cy - diam * 0.11), pc, font=f_c, fill=TXT + (255,))
        lx = cx + diam / 2 + 50 * s
        lh = min(56 * s, (ay1 - ay0) / max(1, len(dados)))
        ly = cy - lh * len(dados) / 2
        for k, it in enumerate(dados):
            ak = int(255 * _ease((t - 0.3 - k * 0.07) / 0.6))
            d.rounded_rectangle([lx, ly + k * lh + 6 * s, lx + 26 * s, ly + k * lh + 32 * s], radius=int(5 * s), fill=cores[k] + (ak,))
            pc = formatar(100 * abs(it["valor"]) / tot, "%")
            d.text((lx + 40 * s, ly + k * lh + 2 * s), f"{it['rotulo'][:20]}", font=f_rot, fill=TXT2 + (ak,))
            d.text((lx + 40 * s + d.textlength(it['rotulo'][:20] + "  ", font=f_rot), ly + k * lh), pc, font=f_val, fill=TXT + (ak,))
    elif tipo in ("numero", "progresso"):
        ax0, ay0, ax1, ay1 = area
        it = dados[0]
        if tipo == "progresso":
            pct = max(0.0, min(100.0, it["valor"]))
            diam = min(ay1 - ay0, (ax1 - ax0) * 0.8) * 0.82
            cx, cy = (ax0 + ax1) / 2, ay0 + diam / 2 + 10 * s
            bb = [cx - diam / 2, cy - diam / 2, cx + diam / 2, cy + diam / 2]
            esp = max(8, int(diam * 0.09))
            d.arc(bb, 0, 360, fill=TXT + (40,), width=esp)
            d.arc(bb, -90, -90 + 360 * pct / 100 * p, fill=cor_p + (255,), width=esp)
            txt = formatar(pct * p, "%", 0)
            f_c = _fonte("bebas-neue-Bold.ttf", diam * 0.3)
            tw = d.textlength(txt, font=f_c)
            d.text((cx - tw / 2, cy - diam * 0.17), txt, font=f_c, fill=TXT + (255,))
            rot = it["rotulo"]
            if rot:
                tw = d.textlength(rot, font=f_tit)
                d.text((cx - tw / 2, cy + diam / 2 + 18 * s), rot, font=f_tit, fill=TXT2 + (int(255 * p),))
        else:
            txt = formatar(it["valor"] * p, unidade, None if p >= 1 else 0)
            f_c = _fonte("bebas-neue-Bold.ttf", min((ay1 - ay0) * 0.62, (ax1 - ax0) / max(3, len(txt) * 0.5)))
            tw = d.textlength(txt, font=f_c)
            cx = (ax0 + ax1) / 2
            d.text((cx - tw / 2, ay0 + 4 * s), txt, font=f_c, fill=cor_p + (255,))
            yy = ay0 + f_c.size * 1.02
            d.rectangle([cx - tw / 2 * p, yy, cx + tw / 2 * p, yy + max(3, int(6 * s))], fill=TXT + (220,))
            if it["rotulo"]:
                tw2 = d.textlength(it["rotulo"], font=f_tit)
                d.text((cx - tw2 / 2, yy + 24 * s), it["rotulo"], font=f_tit, fill=TXT2 + (int(255 * p),))
    if alfa < 1:
        a_ch = im.getchannel("A").point(lambda v: int(v * max(0.0, alfa)))
        im.putalpha(a_ch)
    return im, (x0, y0)


def previa_png(g: Dict[str, Any], W: int, H: int, destino: str, primaria: str = "#FFD60A") -> str:
    """Último quadro da entrada, numa tela transparente do tamanho do vídeo."""
    from PIL import Image
    g = normalizar(g) or g
    tela = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    q, (x, y) = desenhar(g, ENTRADA_S + 0.3, W, H, primaria)
    tela.alpha_composite(q, (x, y))
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    tela.save(destino)
    return destino


def renderizar_mov(g: Dict[str, Any], W: int, H: int, pasta: str, primaria: str = "#FFD60A") -> Tuple[str, Tuple[int, int]]:
    """.mov com alfa (só a caixa do gráfico) — quadros repetidos viram 1 PNG só."""
    chave = hashlib.md5(json.dumps([g, W, H, primaria], sort_keys=True, default=str).encode()).hexdigest()[:12]
    saida = os.path.join(pasta, f"grafico_{chave}.mov")
    x0, y0, _cw, _ch = caixa(g, W, H)
    if os.path.exists(saida):
        return saida, (x0, y0)
    trab = os.path.join(pasta, f"_g_{chave}")
    os.makedirs(trab, exist_ok=True)
    dur = float(g["end"]) - float(g["start"])
    n = max(1, int(round(dur * FPS)))
    linhas, ultimo, rep = [], None, 0
    k_png = 0

    def fecha(arquivo, vezes):
        linhas.append(f"file '{arquivo}'\nduration {vezes / FPS:.5f}")

    for i in range(n):
        t = i / FPS
        estatico = ENTRADA_S + 0.4 < t < dur - SAIDA_S - 0.05
        if estatico and ultimo is not None and ultimo[1]:
            rep += 1
            continue
        if ultimo is not None:
            fecha(ultimo[0], rep)
        q, _ = desenhar(g, t, W, H, primaria)
        arq = os.path.join(trab, f"q{k_png:05d}.png")
        q.save(arq)
        k_png += 1
        ultimo, rep = (arq, estatico), 1
    fecha(ultimo[0], rep)
    linhas.append(f"file '{ultimo[0]}'")
    lista = os.path.join(trab, "lista.txt")
    with open(lista, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lista,
                        "-vf", f"fps={FPS},format=argb", "-c:v", "qtrle", "-t", f"{dur:.3f}", saida], capture_output=True, text=True, timeout=900)
    shutil.rmtree(trab, ignore_errors=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou ao gerar o gráfico: {r.stderr.strip()[-400:]}")
    return saida, (x0, y0)


def aplicar_graficos(video_in: str, video_out: str, graficos: List[Dict[str, Any]], W: int, H: int, work_dir: str,
                     paleta: Optional[Dict[str, str]] = None) -> str:
    """Um passe do ffmpeg: cada gráfico entra por cima no seu tempo. Áudio copiado."""
    from video_assembler import _probe_duration
    validos = [x for x in (normalizar(g) for g in graficos or []) if x]
    if not validos:
        return video_in
    os.makedirs(work_dir, exist_ok=True)
    primaria = (paleta or {}).get("primaria") or "#FFD60A"
    entradas, grafo, atual = [], ["[0:v]setpts=PTS-STARTPTS,format=yuv420p[b0]"], "b0"
    for k, g in enumerate(validos, start=1):
        mov, (x, y) = renderizar_mov(g, W, H, work_dir, primaria)
        entradas += ["-i", mov]
        a = float(g["start"])
        grafo.append(f"[{k}:v]setpts=PTS-STARTPTS+{a:.3f}/TB[g{k}]")
        grafo.append(f"[{atual}][g{k}]overlay={x}:{y}:eof_action=pass:enable='between(t,{a:.3f},{float(g['end']):.3f})'[b{k}]")
        atual = f"b{k}"
    grafo.append(f"[{atual}]format=yuv420p[vout]")
    dur = _probe_duration(video_in)
    import qualidade_export
    r = qualidade_export.rodar(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video_in] + entradas + [
        "-filter_complex", ";".join(grafo), "-map", "[vout]", "-map", "0:a?", "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "copy", video_out], timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou nos gráficos: {r.stderr.strip()[-600:]}")
    return video_out
