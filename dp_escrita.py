"""
✍️ dp_escrita.py — quadro editorial ESCRITA NO PAPEL (v84_94)
=============================================================

Um texto sendo escrito, de três jeitos, em vários papéis:

  modo "mao"         a caneta (ou o giz) escreve letra por letra — a ponta anda junto, a câmera acompanha de leve
  modo "maquina"     MÁQUINA DE ESCREVER: cada tecla bate a letra (tinta irregular, letra um pouco torta), o carro
                     anda pra esquerda, no fim da linha toca o sininho e o carro volta; o papel sobe pelo rolo
  modo "computador"  digitando num programa: documento (tipo Word), bloco de notas, editor de código (escuro, com
                     números de linha) ou MENSAGEM (cada linha é digitada na caixa e ENVIADA como balão) — com ritmo
                     humano, cursor piscando e (opcional) um erro de digitação apagado com backspace

Papéis: branco · antigo (amarelado, manchas, dobras, borda gasta) · caderno (pautado, margem, furos) · quadriculado ·
carta (creme, pauta fina) · kraft · post-it · guardanapo · quadro-negro (escreve com giz).

Depois de escrever: assinatura à mão (opcional) e as palavras de "destaque" circuladas/sublinhadas a caneta vermelha
(no computador: selecionadas com marca-texto).

Fontes: as de fontes_escrita.py (máquina e manuscrita — inclusive as suas, em assets/fonts/pessoais/).
"""
from __future__ import annotations

import hashlib
import math
import random
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import dp_calendario as C
import dp_editorial as E
import fontes_escrita as FE

TINTAS = {"azul": (26, 50, 128), "preta": (24, 24, 28), "vermelha": (168, 28, 30), "grafite": (72, 72, 78), "branca": (238, 238, 230)}
PAPEIS = ["branco", "antigo", "caderno", "quadriculado", "carta", "kraft", "postit", "guardanapo", "quadro"]
PROGRAMAS = ["documento", "bloco_notas", "codigo", "mensagem"]


def _campos_fonte():
    return ("fonte", "Fonte", "escolha:" + "|".join(FE.escolhas()), "auto",
            "auto = Kalam (mão) · Special Elite (máquina) · a do programa (computador). ⚠ = fonte só de uso pessoal")


TIPOS: Dict[str, Dict[str, Any]] = {
    "escrita": {
        "nome": "✍️ Escrita no papel (mão · máquina · computador)", "camada": "tela", "dur": 7.0, "fundo": "mesa",
        "quando": "uma carta, um diário, um bilhete, um relatório datilografado, uma mensagem sendo digitada e enviada — "
                  "o texto aparecendo letra por letra",
        "campos": [("texto", "Texto", "linhas", "Querido diário,\nhoje tudo mudou.", "quebre as linhas como quiser"),
                   ("modo", "Como escreve", "escolha:mao|maquina|computador", "mao",
                    "mao = caneta/giz · maquina = máquina de escrever · computador = digitando num programa"),
                   ("papel", "Papel (mão e máquina)", "escolha:" + "|".join(PAPEIS), "branco",
                    "antigo = amarelado com manchas · quadro = quadro-negro com giz"),
                   ("programa", "Programa (computador)", "escolha:" + "|".join(PROGRAMAS), "documento",
                    "mensagem = cada linha é digitada e ENVIADA como balão"),
                   _campos_fonte(),
                   ("tinta", "Tinta", "escolha:auto|azul|preta|vermelha|grafite|branca", "auto", "auto = azul na caneta, preta na máquina"),
                   ("titulo", "Título / nome do arquivo / contato", "texto", "", "ex.: Querido diário · relatorio.docx · Marina"),
                   ("data", "Data no canto", "texto", "", "ex.: 12 de março de 1942"),
                   ("assinatura", "Assinatura no fim (à mão)", "texto", "", ""),
                   ("destaque", "Palavras pra destacar no fim", "texto", "", "separe por vírgula — a caneta circula/sublinha"),
                   ("erros", "Erro de digitação (computador)", "escolha:nao|sim", "nao", "sim = erra uma palavra e apaga"),
                   E._C_CREDITO],
    },
}
EXEMPLOS: Dict[str, Dict[str, Any]] = {
    "escrita": {"texto": "Querido diário,\nhoje eu descobri a verdade.\nNinguém pode saber.", "modo": "mao", "papel": "antigo",
                "data": "12 de março de 1942", "destaque": "verdade", "_t": 6.4},
}


SONS = {"maquina_rajada": "foley/maquina_datilografando", "maquina_tecla": "foley/maquina_tecla",
        "maquina_ding": "foley/maquina_ding", "maquina_retorno": "foley/maquina_retorno", "mensagem": "pop/pop_1"}


def registrar() -> None:
    TIPOS["escrita"]["campos"][4] = _campos_fonte()  # as fontes da pasta podem ter mudado
    TIPOS["escrita"]["rotulos"] = {"fonte": dict({"auto": "automática"}, **{k: f["nome"] for k, f in FE.catalogo().items()})}
    E.SONS.update(SONS)
    E.TIPOS.update(TIPOS)
    E.EXEMPLOS.update(EXEMPLOS)
    E._DESENHOS.update({"escrita": _d_escrita})


# ------------------------------------------------------------------ ajudas
def _semente(it) -> int:
    return int(hashlib.md5((str(it.get("texto")) + str(it.get("modo")) + str(it.get("id"))).encode()).hexdigest()[:8], 16)


def _modo(it) -> str:
    return it.get("modo") if it.get("modo") in ("mao", "maquina", "computador") else "mao"


def _tinta(it) -> Tuple[int, int, int]:
    t = it.get("tinta")
    if t in TINTAS:
        return TINTAS[t]
    if it.get("papel") == "quadro" and _modo(it) == "mao":
        return TINTAS["branca"]
    return TINTAS["preta"] if _modo(it) == "maquina" else TINTAS["azul"]


def _texto(it) -> str:
    return "\n".join(l.rstrip() for l in str(it.get("texto") or "").replace("\r", "").split("\n")).strip("\n") or " "


def _destaques(it) -> List[str]:
    return [p.strip() for p in str(it.get("destaque") or "").split(",") if p.strip()][:4]


# ------------------------------------------------------------------ ritmo (o mesmo pro desenho e pros sons)
def _peso(ch: str, modo: str, rng: random.Random) -> float:
    if ch == "\n":
        return 9.0 if modo == "maquina" else 5.0
    p = 1.0
    if ch == " ":
        p = 1.25
    elif ch in ",;:":
        p = 3.0
    elif ch in ".!?…":
        p = 5.0
    if modo == "maquina":
        p *= rng.uniform(0.6, 1.5)
    elif modo == "computador":
        p *= rng.uniform(0.35, 1.7) if rng.random() > 0.07 else rng.uniform(2.5, 4.0)  # rajadas e hesitações
    else:
        p *= rng.uniform(0.85, 1.15)
    return p


CPS = {"mao": 13.0, "maquina": 11.0, "computador": 17.0}  # velocidade natural (letras por segundo)


def cronograma(it: Dict[str, Any], dur: float) -> Dict[str, Any]:
    """Teclas no tempo: [(t, "c", letra) | (t, "bs", "") | (t, "nl", "") | (t, "env", "")] e o fim da escrita."""
    return _cronograma(_texto(it), _modo(it), it.get("programa") or "documento", it.get("erros") == "sim", round(dur, 3),
                       bool(it.get("assinatura")), bool(_destaques(it)), _semente(it))


@lru_cache(maxsize=64)
def _cronograma(texto: str, modo: str, programa: str, erros: bool, dur: float, assin: bool, dest: bool, semente: int):
    rng = random.Random(semente)
    teclas: List[Tuple[str, str]] = []
    errou = False
    palavras_longas = [m.start() for m in re.finditer(r"\b\w{5,}\b", texto)]
    alvo_erro = rng.choice(palavras_longas) + 2 if (erros and modo == "computador" and palavras_longas) else -1
    for i, ch in enumerate(texto):
        if i == alvo_erro and not errou:
            vizinho = "qwertyuiopasdfghjklzxcvbnm"[rng.randrange(26)]
            teclas += [("c", vizinho), ("c", texto[i] if i < len(texto) else ""), ("pausa", ""), ("bs", ""), ("bs", "")]
            errou = True
        if ch == "\n":
            teclas.append(("env" if (modo == "computador" and programa == "mensagem") else "nl", ""))
        else:
            teclas.append(("c", ch))
    if modo == "computador" and programa == "mensagem":
        teclas.append(("env", ""))
    pesos = []
    for k, (tipo, ch) in enumerate(teclas):
        if tipo == "c":
            pesos.append(_peso(ch, modo, rng))
        elif tipo == "bs":
            pesos.append(1.6)
        elif tipo == "pausa":
            pesos.append(7.0)
        elif tipo == "env":
            pesos.append(9.0)
        else:
            pesos.append(_peso("\n", modo, rng))
    t0 = 0.75 if modo != "computador" else 0.55
    fim_max = dur * (0.62 if (assin or dest) else 0.8)
    total = sum(pesos) or 1.0
    natural = total / CPS[modo]  # quanto levaria no ritmo natural
    janela = max(0.4, fim_max - t0)
    escala = min(1.0, janela / natural) if natural > 0 else 1.0
    t = t0
    eventos = []
    for (tipo, ch), p in zip(teclas, pesos):
        t += p / CPS[modo] * escala
        eventos.append((round(t, 4), tipo, ch))
    return {"eventos": eventos, "fim": round(t, 4), "inicio": t0}


def _visivel(eventos, t: float) -> Tuple[str, int, float]:
    """(texto já escrito em t, quantas mensagens já enviadas, fração da letra atual)."""
    s: List[str] = []
    enviadas = 0
    ult = None
    prox = None
    for k, (te, tipo, ch) in enumerate(eventos):
        if te > t:
            prox = te
            break
        ult = te
        if tipo == "c":
            s.append(ch)
        elif tipo == "bs":
            if s:
                s.pop()
        elif tipo == "nl":
            s.append("\n")
        elif tipo == "env":
            s.append("\x00")  # marca de mensagem enviada
            enviadas += 1
    frac = 1.0
    if prox is not None and ult is not None and prox > ult:
        frac = E._cl((t - ult) / (prox - ult))
    return "".join(s), enviadas, frac


# ------------------------------------------------------------------ papéis
def _papel(tipo: str, pw: int, ph: int, u: float, semente: int, pauta: float):
    """O papel (RGBA, com sombra fora) — `pauta` = espaço entre linhas (pras pautas baterem com o texto)."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    rng = np.random.default_rng(semente)
    cores = {"branco": (248, 247, 243), "antigo": (226, 205, 160), "caderno": (250, 250, 247), "quadriculado": (250, 250, 248),
             "carta": (246, 239, 222), "kraft": (186, 150, 108), "postit": (255, 236, 120), "guardanapo": (250, 250, 250),
             "quadro": (36, 52, 44)}
    base = np.array(cores.get(tipo, cores["branco"]), np.float32)
    arr = np.ones((ph, pw, 3), np.float32) * base
    grao = {"kraft": 9.0, "antigo": 7.0, "quadro": 5.0}.get(tipo, 3.0)
    arr += rng.normal(0, grao, (ph, pw, 1))
    yy, xx = np.mgrid[0:ph, 0:pw].astype(np.float32)
    if tipo == "antigo":  # bordas queimadas, manchas de café/umidade, dobras
        r = np.sqrt(((xx - pw / 2) / (pw * 0.55)) ** 2 + ((yy - ph / 2) / (ph * 0.55)) ** 2)
        arr *= np.clip(1.12 - 0.35 * r ** 3, 0.55, 1.0)[..., None]
        for _ in range(7):
            cx, cy, rr = rng.uniform(0, pw), rng.uniform(0, ph), rng.uniform(0.04, 0.16) * min(pw, ph)
            d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / rr
            mancha = np.clip(1 - d, 0, 1) ** 1.5 * rng.uniform(0.05, 0.16) + (np.abs(d - 1) < 0.03) * 0.035 * (rng.random() < 0.4)
            arr *= (1 - mancha)[..., None]
        for fx in (0.5,):
            dobra = np.exp(-((xx - pw * fx) / (pw * 0.004)) ** 2) * 0.10
            arr *= (1 - dobra)[..., None]
        dobra_h = np.exp(-((yy - ph * 0.5) / (ph * 0.004)) ** 2) * 0.08
        arr *= (1 - dobra_h)[..., None]
    if tipo == "kraft":  # fibras
        for _ in range(int(pw * ph / 900)):
            x, y = int(rng.uniform(0, pw - 8)), int(rng.uniform(0, ph - 2))
            arr[y, x:x + int(rng.uniform(3, 12))] *= rng.uniform(0.8, 1.15)
    if tipo == "quadro":
        r = np.sqrt(((xx - pw / 2) / pw) ** 2 + ((yy - ph / 2) / ph) ** 2)
        arr *= np.clip(1.1 - 0.5 * r, 0.6, 1.0)[..., None]
        arr += np.clip(rng.normal(0, 1, (ph, pw, 1)) * 6 * (rng.random((ph, pw, 1)) > 0.92), 0, 30)  # pó de giz
    papel = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    d = ImageDraw.Draw(papel, "RGBA")
    topo = pauta * 2.2
    if tipo in ("caderno", "carta"):
        cor = (150, 182, 225, 170) if tipo == "caderno" else (190, 170, 140, 130)
        y = topo
        while y < ph - pauta * 0.4:
            d.line([0, y, pw, y], fill=cor, width=max(1, int(1.3 * u)))
            y += pauta
        if tipo == "caderno":
            d.line([pw * 0.1, 0, pw * 0.1, ph], fill=(228, 110, 110, 190), width=max(1, int(1.8 * u)))
            for k in range(3):  # furos de fichário
                cy = ph * (0.18 + 0.32 * k)
                d.ellipse([pw * 0.035 - 9 * u, cy - 9 * u, pw * 0.035 + 9 * u, cy + 9 * u], fill=(0, 0, 0, 0))
        else:
            d.line([pw * 0.06, topo - pauta * 1.2, pw * 0.94, topo - pauta * 1.2], fill=(160, 120, 80, 150), width=max(1, int(2 * u)))
    if tipo == "quadriculado":
        passo = pauta / 2
        x = 0.0
        while x < pw:
            d.line([x, 0, x, ph], fill=(160, 190, 225, 110), width=1)
            x += passo
        y = topo - pauta
        while y < ph:
            d.line([0, y, pw, y], fill=(160, 190, 225, 110), width=1)
            y += passo
    if tipo == "postit":
        d.rectangle([0, 0, pw, ph * 0.08], fill=(248, 222, 92, 255))
    if tipo == "guardanapo":  # borda em relevo
        for k in range(3):
            m = (10 + 7 * k) * u
            d.rectangle([m, m, pw - m, ph - m], outline=(225, 225, 228, 255), width=max(1, int(1.5 * u)))
        papel = papel.filter(ImageFilter.GaussianBlur(0.4))
    if tipo == "quadro":
        d.rectangle([0, 0, pw - 1, ph - 1], outline=(118, 84, 52, 255), width=int(16 * u))
    # borda irregular (papel antigo e kraft) — recorta o alfa com ruído
    if tipo in ("antigo", "kraft", "guardanapo"):
        a = np.ones((ph, pw), np.float32)
        aspero = 3.0 * u if tipo != "guardanapo" else 1.5 * u
        borda = np.minimum(np.minimum(xx, pw - 1 - xx), np.minimum(yy, ph - 1 - yy))
        ruido = np.abs(np.sin(xx * 0.21 + rng.uniform(0, 6)) + np.sin(yy * 0.17 + rng.uniform(0, 6))) * aspero + rng.normal(0, aspero * 0.4, (ph, pw))
        a = np.clip((borda - ruido) / max(1.0, u), 0, 1)
        if tipo == "antigo":
            arr2 = np.array(papel).astype(np.float32)
            queim = np.clip(1 - (borda - ruido) / (14 * u), 0, 1)[..., None]
            arr2[..., :3] = arr2[..., :3] * (1 - 0.6 * queim) + np.array([90, 55, 25], np.float32) * 0.6 * queim
            arr2[..., 3] = a * 255
            papel = Image.fromarray(np.clip(arr2, 0, 255).astype(np.uint8), "RGBA")
        else:
            papel.putalpha(Image.fromarray((a * 255).astype(np.uint8), "L"))
    # furos do caderno transparentes
    if tipo == "caderno":
        al = papel.getchannel("A")
        da = ImageDraw.Draw(al)
        for k in range(3):
            cy = ph * (0.18 + 0.32 * k)
            da.ellipse([pw * 0.035 - 9 * u, cy - 9 * u, pw * 0.035 + 9 * u, cy + 9 * u], fill=0)
        papel.putalpha(al)
    # sombra
    sh, m = E._sombra(pw, ph, max(2, int(12 * u)), 140, 0)
    sh.alpha_composite(papel, dest=(m, int(m - 3 * u)))
    return sh, m


# ------------------------------------------------------------------ layout (onde cada letra fica)
def _layout(texto: str, L, largura: float, lh: float) -> List[Tuple[str, float, int]]:
    """[(letra, x, linha)] na ordem do texto (as quebras viram ("\\n", x, linha))."""
    out: List[Tuple[str, float, int]] = []
    linha = 0
    paragrafos = texto.split("\n")
    for pi, par in enumerate(paragrafos):
        for li, l in enumerate(L.quebrar(par, largura)):
            x = 0.0
            if li > 0:  # quebra automática: o espaço que ficou no fim vira a quebra
                linha += 1
            for ch in l:
                out.append((ch, x, linha))
                x += L.avanco(ch)
            if li == 0 and l != par and not par[len(l):len(l) + 1].strip():
                out.append((" ", x, linha))  # o espaço engolido pela quebra
        if pi < len(paragrafos) - 1:
            out.append(("\n", 0.0, linha))
            linha += 1
    return out


def _caber(texto: str, fid: str, tipo_fonte: str, larg: float, alt: float, px0: float, entrelinha: float, caminho=None):
    """Maior tamanho (até px0) em que o texto cabe na área."""
    px = px0
    while px > 10:
        L = FE.letra(fid, int(px), tipo_fonte, caminho)
        lay = _layout(texto, L, larg, px * entrelinha)
        n = (lay[-1][2] + 1) if lay else 1
        if n * px * entrelinha <= alt:
            return L, px
        px *= 0.92
    return FE.letra(fid, int(px), tipo_fonte, caminho), px


def _jitter(semente: int, k: int) -> Tuple[float, float, float, float]:
    r = random.Random(semente * 1000003 + k)
    return r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(0.72, 1.0), r.random()


# ------------------------------------------------------------------ desenho
def _d_escrita(it, t, W, H, ctx):
    modo = _modo(it)
    if modo == "computador":
        return _d_computador(it, t, W, H, ctx)
    if modo == "maquina":
        return _d_maquina(it, t, W, H, ctx)
    return _d_mao(it, t, W, H, ctx)


def _caneta(im, x: float, y: float, u: float, cor, giz: bool = False, levantada: float = 0.0) -> None:
    """A caneta (ou o giz) com a ponta em (x, y)."""
    from PIL import Image, ImageDraw
    comp = 230 * u
    ang = math.radians(-58)
    dx, dy = math.cos(ang), math.sin(ang)  # pra cima e pra direita
    y -= levantada * 18 * u
    px_, py_ = -dy, dx
    lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay, "RGBA")
    # sombra
    sx, sy = 16 * u, 22 * u
    if giz:  # um toco de giz
        w = 16 * u
        cg = comp * 0.38
        corpo = [(x + px_ * w / 2, y + py_ * w / 2), (x - px_ * w / 2, y - py_ * w / 2),
                 (x - px_ * w / 2 + dx * cg, y - py_ * w / 2 - abs(dy) * cg), (x + px_ * w / 2 + dx * cg, y + py_ * w / 2 - abs(dy) * cg)]
        d.polygon([(a + sx, b + sy) for a, b in corpo], fill=(0, 0, 0, 70))
        d.polygon(corpo, fill=(240, 238, 228, 255))
    else:
        w = 20 * u
        ponta = 26 * u
        p1 = (x + dx * ponta, y - abs(dy) * ponta)
        corpo = [(p1[0] + px_ * w / 2, p1[1] + py_ * w / 2), (p1[0] - px_ * w / 2, p1[1] - py_ * w / 2),
                 (p1[0] - px_ * w / 2 + dx * comp, p1[1] - py_ * w / 2 - abs(dy) * comp),
                 (p1[0] + px_ * w / 2 + dx * comp, p1[1] + py_ * w / 2 - abs(dy) * comp)]
        cone = [(x, y), corpo[0], corpo[1]]
        d.polygon([(a + sx, b + sy) for a, b in corpo + [(x, y)]], fill=(0, 0, 0, 60))
        d.polygon(cone, fill=(196, 198, 204, 255))
        d.polygon(corpo, fill=tuple(int(c * 0.55) for c in cor[:3]) + (255,))
        d.line([corpo[0], corpo[3]], fill=(255, 255, 255, 70), width=max(1, int(3 * u)))
        clip = [(corpo[3][0] - px_ * w * 0.1 - dx * comp * 0.42, corpo[3][1] - py_ * w * 0.1 + abs(dy) * comp * 0.42),
                (corpo[3][0] - px_ * w * 0.1 - dx * comp * 0.05, corpo[3][1] - py_ * w * 0.1 + abs(dy) * comp * 0.05)]
        d.line(clip, fill=(210, 212, 218, 255), width=max(1, int(4 * u)))
        d.ellipse([x - 2 * u, y - 2 * u, x + 2 * u, y + 2 * u], fill=tuple(cor[:3]) + (255,))
    im.alpha_composite(lay)


def _escrever_letras(folha, lay, n_vis: float, x0: float, y0: float, lh: float, L, cor, semente: int, modo: str,
                     tinta_var: bool = True) -> Optional[Tuple[float, float]]:
    """Desenha as letras [0, n_vis) do layout na folha (a última pela metade, no modo mão). Devolve a ponta."""
    inteiras = int(n_vis)
    frac = n_vis - inteiras
    ponta = None
    for k, (ch, x, ln) in enumerate(lay[:inteiras + 1]):
        if k > inteiras or ch in ("\n",) or (k == inteiras and frac <= 0):
            if k == inteiras and ch == "\n":
                ponta = (x0 + x, y0 + ln * lh)
            continue
        jx, jy, alfa, sorte = _jitter(semente, k)
        if modo == "maquina":
            dx, dy = jx * 0.6, jy * L.px * 0.025
            a = int(255 * (alfa if tinta_var else 1.0))
        else:
            dx, dy = jx * 0.3, jy * L.px * 0.018 + math.sin(k * 0.37) * L.px * 0.012
            a = 245
        if ch == " ":
            ponta = (x0 + x + L.avanco(ch), y0 + ln * lh)
            continue
        g, gx, gy = L.glifo(ch, tuple(cor[:3]) + (a,))
        if k == inteiras:  # a letra sendo escrita: aparece da esquerda pra direita
            larg = max(1, int(-gx + L.avanco(ch) * frac + 2))
            g = g.crop((0, 0, min(g.width, larg), g.height))
        px_, py_ = x0 + x + dx + gx, y0 + ln * lh + dy + gy
        folha.alpha_composite(g, (int(px_), int(py_))) if px_ >= 0 and py_ >= 0 else E._cola(folha, g, px_, py_)
        if modo == "maquina" and sorte > 0.9:  # batida dupla: um fantasma de leve
            g2, _a, _b = L.glifo(ch, tuple(cor[:3]) + (70,))
            E._cola(folha, g2, px_ + 1.2, py_ - 0.8)
        ponta = (x0 + x + L.avanco(ch) * (frac if k == inteiras else 1.0), y0 + ln * lh)
    return ponta


def _posicoes_palavras(lay, palavras: List[str]) -> List[Tuple[float, float, int]]:
    """(x0, x1, linha) das palavras de destaque no layout."""
    texto = "".join(c for c, _x, _l in lay)
    out = []
    for p in palavras:
        m = re.search(re.escape(p), texto, re.IGNORECASE)
        if not m:
            continue
        a, b = m.start(), m.end() - 1
        if lay[a][2] != lay[b][2]:
            b = max(k for k in range(a, b + 1) if lay[k][2] == lay[a][2])
        out.append((lay[a][1], lay[b][1] + 0.0, lay[a][2], b))
    return out


def _d_mao(it, t, W, H, ctx):
    from PIL import Image
    u, dur = E._u(W, H), it["end"] - it["start"]
    vert = E._vert(W, H)
    papel = it.get("papel") if it.get("papel") in PAPEIS else "branco"
    quadro = papel == "quadro"
    im = (E._fundo("escuro", W, H) if quadro else E._fundo("mesa", W, H)).convert("RGBA")
    if papel == "postit":
        pw = ph = int(min(W * 0.86, H * (0.8 if not vert else 0.5)))
    elif quadro:
        pw, ph = (int(W * 0.84), int(H * 0.8)) if not vert else (int(W * 0.92), int(H * 0.62))
    else:
        pw, ph = (int(H * 0.86 * 0.8), int(H * 0.86)) if not vert else (int(W * 0.86), int(H * 0.66))
        if not vert and len(_texto(it)) > 140:
            pw = int(W * 0.66)
    texto = _texto(it)
    cor = _tinta(it)
    semente = _semente(it)
    fid = it.get("fonte") if it.get("fonte") not in ("", "auto", None) else ("marcador" if quadro else "kalam")
    mx = pw * (0.16 if papel == "caderno" else 0.1)
    tem_tit = bool(it.get("titulo"))
    larg = pw - mx - pw * 0.08
    # linhas: a 1ª pauta fica em 2,2 entrelinhas do topo; o título ocupa uma linha; a assinatura, o rodapé
    alt = ph * (1 - 0.06 - (0.17 if it.get("assinatura") else 0.04)) - (ph * 0.05 if it.get("data") else 0)
    px = min(pw, ph) * 0.11
    while True:
        L, px = _caber(texto, fid, "manuscrita", larg, alt - px * 1.45 * (2.2 + (1.0 if tem_tit else 0.0) - 1), px, 1.45)
        lh = px * 1.45
        if px < 14 or lh * (2.2 + (1.0 if tem_tit else 0.0)) < ph * 0.42:
            break
        px *= 0.9
    lay = _layout(texto, L, larg, lh)
    base_papel, m = E._cache(ctx, f"esc_papel:{papel}:{pw}x{ph}:{int(lh)}:{semente}",
                             lambda: _papel(papel, pw, ph, u, semente, lh))
    folha = base_papel.copy()
    topo_papel = m - 3 * u  # onde o papel começa dentro da folha (a folha tem a margem da sombra)
    y_tit = topo_papel + lh * 2.2 - 4 * u  # a linha de base em cima da 1ª pauta
    x0, y0 = m + mx, y_tit + (lh if tem_tit else 0)
    cr = cronograma(it, dur)
    ev = cr["eventos"]
    s, _env, frac = _visivel(ev, t)
    n_vis = len(s) + (frac if len(s) < len(lay) and t < cr["fim"] else 0)
    # título e data (escritos antes, já estão lá)
    if it.get("titulo"):
        Lt = FE.letra(fid, int(px * 1.25), "manuscrita")
        _escrever_letras(folha, [(c, Lt.largura(it["titulo"][:k]), 0) for k, c in enumerate(it["titulo"])], 1e9,
                         m + mx, y_tit, lh, Lt, cor, semente + 1, "mao")
    if it.get("data"):
        Ld = FE.letra(fid, int(px * 0.8), "manuscrita")
        wd = Ld.largura(it["data"])
        _escrever_letras(folha, [(c, Ld.largura(it["data"][:k]), 0) for k, c in enumerate(it["data"])], 1e9,
                         m + pw - pw * 0.07 - wd, topo_papel + lh * 1.2 - 4 * u, lh, Ld, cor, semente + 2, "mao")
    ponta = _escrever_letras(folha, lay, min(n_vis, len(lay)), x0, y0, lh, L, cor, semente, "mao")
    escrevendo = cr["inicio"] - 0.1 < t < cr["fim"] + 0.05
    t_fim = cr["fim"]
    # assinatura
    pd = C._pincel(folha)
    if it.get("assinatura"):
        La = FE.letra(it.get("fonte") if it.get("fonte") not in ("", "auto", None) else ("brittany" if "brittany" in FE.catalogo() else "kalam"),
                      int(px * 1.3), "manuscrita")
        txt = it["assinatura"]
        p_as = E._cl((t - t_fim - 0.2) / max(0.6, 0.07 * len(txt)))
        lay_a = [(c, La.largura(txt[:k]), 0) for k, c in enumerate(txt)]
        ya = m + ph - ph * 0.09
        xa = m + pw - pw * 0.08 - La.largura(txt)
        pa = _escrever_letras(folha, lay_a, len(txt) * p_as, xa, ya, lh, La, cor, semente + 3, "mao")
        if 0 < p_as < 1 and pa:
            ponta, escrevendo = pa, True
        t_fim += 0.2 + max(0.6, 0.07 * len(txt))
    # destaques: a caneta vermelha circula/sublinha
    dest = _posicoes_palavras(lay, _destaques(it))
    vermelho = (190, 30, 34, 235) if not quadro else (255, 120, 110, 235)
    for k, (a, b, ln, kb) in enumerate(dest):
        ch_b = lay[kb][0]
        x1 = b + L.avanco(ch_b)
        p = E._cl((t - t_fim - 0.25 - k * 0.6) / 0.5)
        yb = y0 + ln * lh
        if k % 2 == 0:
            C._traco(pd, C._pts_circulo(x0 + (a + x1) / 2, yb - px * 0.3, (x1 - a) / 2 + px * 0.35, px * 0.62, semente + k), p, vermelho, 4.5 * u)
        else:
            C._traco(pd, C._pts_risco(x0 + a, x0 + x1, yb + px * 0.18, semente + k, u), p, vermelho, 4.5 * u)
    # a folha na mesa (entra deslizando), câmera acompanhando de leve a ponta
    q = E._ease(t / 0.7)
    gir = E._rotacionar(folha, -1.6 * (0.3 + 0.7 * q) if not quadro else 0)
    ox = W / 2 - gir.width / 2
    oy = H / 2 - gir.height / 2 + (1 - q) * H * 0.12
    E._cola(im, gir, ox, oy, E._cl(t / 0.3))
    if ponta and escrevendo and t >= cr["inicio"] - 0.1:
        ang = math.radians(-1.6 * (0.3 + 0.7 * q) if not quadro else 0)
        cxl, cyl = folha.width / 2, folha.height / 2
        rx, ry = ponta[0] - cxl, ponta[1] - cyl
        tx = ox + gir.width / 2 + rx * math.cos(ang) + ry * math.sin(ang)
        ty = oy + gir.height / 2 - rx * math.sin(ang) + ry * math.cos(ang)
        sobe = 0.5 + 0.5 * math.sin(t * 23) if frac >= 0.999 else 0.0
        _caneta(im, tx, ty - px * 0.05, u, cor, giz=quadro, levantada=0.25 * sobe)
    # câmera: aproxima devagar
    z = 1.0 + 0.05 * E._ease(t / max(1.0, dur))
    if z > 1.001:
        cw, ch_ = int(W / z), int(H / z)
        im = im.crop(((W - cw) // 2, (H - ch_) // 2, (W - cw) // 2 + cw, (H - ch_) // 2 + ch_)).resize((W, H), Image.BILINEAR)
    E._credito(C._pincel(im), it, W, H, u, "escuro")
    return E._com_alfa(im, E._k_tela(t, dur))


# ------------------------------------------------------------------ ⌨ máquina de escrever
def _d_maquina(it, t, W, H, ctx):
    from PIL import Image, ImageDraw
    u, dur = E._u(W, H), it["end"] - it["start"]
    vert = E._vert(W, H)
    papel = it.get("papel") if it.get("papel") in PAPEIS and it.get("papel") != "quadro" else "branco"
    texto = _texto(it)
    cor = _tinta(it)
    semente = _semente(it)
    fid = it.get("fonte") if it.get("fonte") not in ("", "auto", None) else "special-elite"
    px = int(H * (0.066 if not vert else 0.04))
    L = FE.letra(fid, px, "maquina")
    lh = px * 1.5
    larg = W * (0.9 if not vert else 0.86)  # o carro anda com a letra; no fim a câmera recua e mostra tudo
    if L.largura(max(texto.split("\n"), key=len)) < larg * 0.6:
        larg = max(W * 0.55, L.largura(max(texto.split("\n"), key=len)) * 1.05)
    lay = _layout(texto, L, larg, lh)
    n_linhas = (lay[-1][2] + 1) if lay else 1
    pw = int(larg + W * 0.5)
    mx = W * 0.25
    ph = int(max(lh * (n_linhas + 9), pw * 1.25))  # uma folha inteira (o resto fica pra baixo do rolo)
    base, m = E._cache(ctx, f"esc_maq:{papel}:{pw}x{ph}:{semente}", lambda: _papel(papel, pw, ph, u, semente, lh))
    folha = base.copy()
    y_l0 = m + lh * 4.5
    if it.get("titulo"):
        Lt = FE.letra(fid, int(px * 1.0), "maquina")
        tt = it["titulo"].upper()
        _escrever_letras(folha, [(c, Lt.largura(tt[:k]), 0) for k, c in enumerate(tt)], 1e9, m + mx, m + lh * 3.0, lh, Lt, cor, semente + 5, "maquina")
    cr = cronograma(it, dur)
    s, _e, _f = _visivel(cr["eventos"], t)
    n = min(len(s), len(lay))
    _escrever_letras(folha, lay, n, m + mx, y_l0, lh, L, cor, semente, "maquina")
    # onde está o "tipo" (o ponto que bate): a próxima letra
    if n < len(lay):
        ch, x_at, ln_at = lay[n]
    elif lay:
        ch, x_at, ln_at = lay[-1][0], lay[-1][1] + L.avanco(lay[-1][0]), lay[-1][2]
    else:
        x_at, ln_at = 0.0, 0
    # o carro: anda com a letra; na volta (nova linha) desliza com easing
    t_nl = [te for te, tp, _c in cr["eventos"] if tp == "nl" and te <= t]
    if t_nl and t - t_nl[-1] < 0.35 and n > 0:
        k_ret = E._ease((t - t_nl[-1]) / 0.35)
        x_ant = max([lx + L.avanco(c) for c, lx, ll in lay[:n] if ll == ln_at - 1] or [0.0])
        x_cam = x_ant + (x_at - x_ant) * k_ret
        y_cam = (ln_at - 1) + k_ret
    else:
        x_cam, y_cam = x_at, ln_at
    centro_x, linha_y = W * 0.5, H * (0.66 if not vert else 0.6)
    k_fim = E._ease((t - cr["fim"] - 0.35) / 0.9)  # terminou: o carro vai pro meio e dá pra ler a folha inteira
    if k_fim > 0 and lay:
        meio = max(lx + L.avanco(c) for c, lx, _l in lay) / 2
        x_cam = x_cam + (meio - x_cam) * k_fim
    ox = centro_x - (m + mx + x_cam)
    oy = linha_y - (y_l0 + y_cam * lh)
    # entrada: o papel sobe pelo rolo
    q = E._ease(t / 0.6)
    oy += (1 - q) * H * 0.3
    im = E._fundo("escuro", W, H).convert("RGBA")
    E._cola(im, folha, ox, oy)
    d = ImageDraw.Draw(im, "RGBA")
    # o rolo (por cima do papel, logo abaixo da linha) e o corpo da máquina
    ry0 = linha_y + lh * 0.55
    ry1 = ry0 + lh * 1.25
    for k in range(int(ry1 - ry0)):
        f = k / max(1, ry1 - ry0)
        luz = 20 + int(60 * math.sin(math.pi * f) ** 2)
        d.line([0, ry0 + k, W, ry0 + k], fill=(luz, luz, luz + 4, 255))
    d.rectangle([0, ry1, W, H], fill=(16, 16, 18, 255))
    for k in range(int(H - ry1)):  # brilho metálico no corpo
        if k % 3 == 0:
            g = int(26 + 14 * math.exp(-k / (H * 0.08)))
            d.line([0, ry1 + k, W, ry1 + k], fill=(g, g, g + 3, 255))
    # rodinhas de borracha da barra do papel, nas bordas da folha, em cima do rolo
    for rx in (ox + m + mx * 0.5, ox + m + pw - mx * 0.5):
        d.rounded_rectangle([rx - 16 * u, ry0 - 6 * u, rx + 16 * u, ry0 + 12 * u], radius=int(8 * u), fill=(26, 26, 28, 255))
    # guia do tipo (onde a letra bate)
    gx = centro_x + L.avanco(ch if n < len(lay) else " ") / 2
    d.polygon([(gx - 26 * u, ry0 + 2 * u), (gx + 26 * u, ry0 + 2 * u), (gx + 10 * u, linha_y + lh * 0.12), (gx - 10 * u, linha_y + lh * 0.12)],
              fill=(196, 200, 208, 230))
    d.line([gx, linha_y + lh * 0.12, gx, linha_y + lh * 0.3], fill=(60, 60, 64, 255), width=max(1, int(2 * u)))
    # marcador de margem (régua) no rolo
    for k in range(-30, 31):
        xx = centro_x + k * L.avanco("m") - (x_cam % L.avanco("m"))
        h = 8 * u if (k + int(x_cam / max(1, L.avanco("m")))) % 5 == 0 else 4 * u
        d.line([xx, ry0 + lh * 0.3, xx, ry0 + lh * 0.3 + h], fill=(200, 200, 205, 110), width=1)
    if it.get("assinatura") or _destaques(it):
        _depois_maquina(im, it, t, cr["fim"], lay, L, ox + m + mx, oy + y_l0, lh, u, semente)
    E._credito(C._pincel(im), it, W, H, u, "escuro")
    return E._com_alfa(im, E._k_tela(t, dur))


def _depois_maquina(im, it, t, t_fim, lay, L, x0, y0, lh, u, semente):
    """Depois de datilografar: a caneta vermelha marca as palavras e a assinatura entra à mão."""
    pd = C._pincel(im)
    for k, (a, b, ln, kb) in enumerate(_posicoes_palavras(lay, _destaques(it))):
        x1 = b + L.avanco(lay[kb][0])
        p = E._cl((t - t_fim - 0.3 - k * 0.6) / 0.5)
        yb = y0 + ln * lh
        C._traco(pd, C._pts_risco(x0 + a - 4 * u, x0 + x1 + 4 * u, yb + L.px * 0.2, semente + k, u), p, (190, 30, 34, 235), 5 * u)


# ------------------------------------------------------------------ 💻 computador
def _fonte_pc(it, programa: str, px: int):
    fid = it.get("fonte")
    if fid and fid != "auto" and fid in FE.catalogo():
        return FE.letra(fid, px, FE.catalogo()[fid]["tipo"])
    fam = {"codigo": ("DP Jetbrains Mono", False), "bloco_notas": ("DP Jetbrains Mono", False),
           "documento": ("DP Eb Garamond", False), "mensagem": ("DP Inter", False)}[programa]
    return FE.letra("pc-" + programa, px, "maquina", E._fonte_arq(fam[0], fam[1], False))


def _janela_pc(im, x, y, w, h, u, titulo: str, escuro: bool):
    """Moldura de janela (barra com os 3 botões)."""
    from PIL import ImageDraw
    sh, m = E._sombra(int(w), int(h), max(2, int(18 * u)), 160, int(12 * u))
    E._cola(im, sh, x - m, y - m)
    d = ImageDraw.Draw(im, "RGBA")
    fundo = (30, 32, 38, 255) if escuro else (250, 250, 252, 255)
    barra = (44, 46, 54, 255) if escuro else (232, 233, 238, 255)
    d.rounded_rectangle([x, y, x + w, y + h], radius=int(12 * u), fill=fundo)
    d.rounded_rectangle([x, y, x + w, y + 46 * u], radius=int(12 * u), fill=barra)
    d.rectangle([x, y + 30 * u, x + w, y + 46 * u], fill=barra)
    for k, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([x + (20 + 24 * k) * u, y + 15 * u, x + (34 + 24 * k) * u, y + 29 * u], fill=c + (255,))
    f = E._f("sans", 17 * u)
    d.text((x + w / 2, y + 29 * u), titulo, font=f, fill=(200, 202, 210) if escuro else (80, 82, 90), anchor="ms")
    return y + 46 * u


def _d_computador(it, t, W, H, ctx):
    from PIL import ImageDraw
    u, dur = E._u(W, H), it["end"] - it["start"]
    vert = E._vert(W, H)
    programa = it.get("programa") if it.get("programa") in PROGRAMAS else "documento"
    escuro = programa == "codigo"
    im = E._fundo("escuro", W, H).convert("RGBA")
    cr = cronograma(it, dur)
    s, enviadas, _f = _visivel(cr["eventos"], t)
    cursor_on = (int(t * 2.2) % 2 == 0) or (cr["inicio"] < t < cr["fim"])
    q = E._ease(t / 0.5)
    ww, wh = (W * 0.7, H * 0.82) if not vert else (W * 0.92, H * 0.62)
    wx, wy = W / 2 - ww / 2, H / 2 - wh / 2 + (1 - q) * H * 0.06
    if programa == "mensagem":
        return _d_mensagem(im, it, t, W, H, u, s, enviadas, cr, wx, wy, ww, wh, cursor_on, dur)
    titulo = it.get("titulo") or {"documento": "Documento sem título", "bloco_notas": "anotações.txt", "codigo": "main.py"}[programa]
    yt = _janela_pc(im, wx, wy, ww, wh, u, titulo, escuro)
    d = ImageDraw.Draw(im, "RGBA")
    px = int(H * ((0.052 if programa == "documento" else 0.046) if not vert else 0.03))
    L = _fonte_pc(it, programa, px)
    lh = px * (1.55 if programa != "codigo" else 1.45)
    if programa == "documento":  # barra de ferramentas + página
        d.rectangle([wx, yt, wx + ww, yt + 40 * u], fill=(244, 245, 248, 255))
        fx = E._f("sans_b", 15 * u)
        for k, b in enumerate(["B", "I", "U", "≡", "A"]):
            d.text((wx + (30 + 38 * k) * u, yt + 27 * u), b, font=fx if b != "≡" else E._f_simbolos(int(15 * u)), fill=(90, 92, 100), anchor="ms")
        d.rectangle([wx, yt + 40 * u, wx + ww, wy + wh - 12 * u], fill=(228, 230, 234, 255))
        pgx0, pgx1 = wx + ww * 0.1, wx + ww * 0.9
        d.rectangle([pgx0, yt + 58 * u, pgx1, wy + wh], fill=(255, 255, 255, 255))
        x0, y0, larg = pgx0 + ww * 0.08, yt + 58 * u + ww * 0.06 + px, (pgx1 - pgx0) - ww * 0.16
        cor = (30, 30, 34)
    elif programa == "codigo":
        x0, y0, larg = wx + 78 * u, yt + 34 * u + px, ww - 110 * u
        cor = (214, 218, 226)
    else:
        x0, y0, larg = wx + 30 * u, yt + 30 * u + px, ww - 60 * u
        cor = (34, 34, 38)
    lay = _layout(s.replace("\x00", ""), L, larg, lh)
    visiveis = int((wy + wh - 30 * u - y0) / lh)
    ult = lay[-1][2] if lay else 0
    rolar = max(0, ult - visiveis + 1)
    if programa == "codigo":
        fn = E._f("mono", int(px * 0.8))
        for ln in range(rolar, rolar + visiveis):
            if ln <= ult or ln == 0:
                d.text((wx + 56 * u, y0 + (ln - rolar) * lh), str(ln + 1), font=fn, fill=(110, 116, 130), anchor="rs")
    texto_vis = "".join(c for c, _x, _l in lay)
    cores = _cores_codigo(texto_vis) if programa == "codigo" else None
    for k, (ch, x, ln) in enumerate(lay):
        if ch in ("\n", " ") or ln < rolar or ln >= rolar + visiveis:
            continue
        c = cores[k] if cores else cor
        g, gx, gy = L.glifo(ch, tuple(c) + (255,))
        E._cola(im, g, x0 + x + gx, y0 + (ln - rolar) * lh + gy)
    # destaques (marca-texto / seleção)
    if t > cr["fim"]:
        for k, (a, b, ln, kb) in enumerate(_posicoes_palavras(lay, _destaques(it))):
            p = E._ease((t - cr["fim"] - 0.2 - 0.4 * k) / 0.35)
            if p > 0 and rolar <= ln < rolar + visiveis:
                x1 = b + L.avanco(lay[kb][0])
                yb = y0 + (ln - rolar) * lh
                C._pincel(im).realce([x0 + a - 2 * u, yb - px * 0.95, x0 + a + (x1 - a) * p + 2 * u, yb + px * 0.28], 3 * u,
                                     (255, 224, 70) if not escuro else (90, 140, 255), 0.85)
    # cursor
    if cursor_on:
        if lay:
            ch, x, ln = lay[-1]
            cx = x0 + x + (L.avanco(ch) if ch != "\n" else 0)
            ln = ln + (1 if ch == "\n" else 0)
            if ch == "\n":
                cx = x0
        else:
            cx, ln = x0, 0
        yb = y0 + (ln - rolar) * lh
        d.rectangle([cx + 1, yb - px * 0.95, cx + max(2, 2.5 * u), yb + px * 0.25], fill=(cor if not escuro else (230, 230, 240)) + (255,))
    E._credito(C._pincel(im), it, W, H, u, "escuro")
    return E._com_alfa(im, E._k_tela(t, dur))


_PALAVRAS_PY = set("def return if else elif for while import from as class in not and or None True False with try except print".split())


def _cores_codigo(txt: str) -> List[Tuple[int, int, int]]:
    """Cor de cada letra (palavra-chave, texto entre aspas, número, comentário)."""
    cores = [(214, 218, 226)] * len(txt)
    for m in re.finditer(r"#.*$|//.*$", txt, re.M):
        for k in range(m.start(), m.end()):
            cores[k] = (120, 132, 150)
    for m in re.finditer(r"\"[^\"\n]*\"?|'[^'\n]*'?", txt):
        for k in range(m.start(), m.end()):
            cores[k] = (152, 195, 121)
    for m in re.finditer(r"\b\d+(\.\d+)?\b", txt):
        for k in range(m.start(), m.end()):
            cores[k] = (209, 154, 102)
    for m in re.finditer(r"\b[A-Za-z_]+\b", txt):
        if m.group(0) in _PALAVRAS_PY:
            for k in range(m.start(), m.end()):
                cores[k] = (198, 120, 221)
    return cores


def _d_mensagem(im, it, t, W, H, u, s, enviadas, cr, wx, wy, ww, wh, cursor_on, dur):
    """Conversa: cada linha é digitada na caixa e enviada como balão (sobe com ✓✓)."""
    from PIL import ImageDraw
    contato = it.get("titulo") or "Conversa"
    yt = _janela_pc(im, wx, wy, ww, wh, u, contato, False)
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle([wx, yt, wx + ww, wy + wh - 12 * u], fill=(236, 229, 221, 255))
    d.rounded_rectangle([wx, wy + wh - 24 * u, wx + ww, wy + wh], radius=int(12 * u), fill=(236, 229, 221, 255))
    px = int(min(W, H) * 0.046)
    L = _fonte_pc(it, "mensagem", px)
    partes = s.split("\x00")
    enviadas_txt, digitando = partes[:-1], partes[-1]
    # a caixa de digitar
    cy0 = wy + wh - 90 * u
    d.rounded_rectangle([wx + 20 * u, cy0, wx + ww - 96 * u, cy0 + 62 * u], radius=int(31 * u), fill=(255, 255, 255, 255))
    d.ellipse([wx + ww - 82 * u, cy0, wx + ww - 20 * u, cy0 + 62 * u], fill=(0, 168, 132, 255))
    d.polygon([(wx + ww - 62 * u, cy0 + 18 * u), (wx + ww - 36 * u, cy0 + 31 * u), (wx + ww - 62 * u, cy0 + 44 * u)], fill=(255, 255, 255, 255))
    larg_cx = ww - 160 * u
    vis = digitando.replace("\n", " ")
    while vis and L.largura(vis) > larg_cx:
        vis = vis[1:]
    x = wx + 46 * u
    for ch in vis:
        if ch != " ":
            g, gx, gy = L.glifo(ch, (30, 30, 34, 255))
            E._cola(im, g, x + gx, cy0 + 31 * u + px * 0.35 + gy)
        x += L.avanco(ch)
    if not vis:
        d.text((wx + 46 * u, cy0 + 31 * u + px * 0.35), "Mensagem", font=E._f("sans", px), fill=(150, 150, 156), anchor="ls")
    if cursor_on:
        d.rectangle([x + 1, cy0 + 14 * u, x + 3 * u, cy0 + 48 * u], fill=(0, 140, 110, 255))
    # os balões enviados (de baixo pra cima)
    tempos_env = [te for te, tp, _c in cr["eventos"] if tp == "env"]
    y = cy0 - 18 * u
    larg_b = ww * 0.62
    for k in range(len(enviadas_txt) - 1, -1, -1):
        txt = enviadas_txt[k].replace("\n", " ").strip()
        linhas = L.quebrar(txt, larg_b - 40 * u) if txt else [""]
        bw = max(L.largura(l) for l in linhas) + 40 * u + 60 * u
        bh = len(linhas) * px * 1.35 + 28 * u
        idade = t - tempos_env[k] if k < len(tempos_env) else 9.0
        p = E._ease(idade / 0.3)
        bx1 = wx + ww - 24 * u
        bx0 = bx1 - bw
        yb1 = y + (1 - p) * 40 * u
        yb0 = yb1 - bh
        if yb1 < yt + 10 * u:
            break
        d.rounded_rectangle([bx0, yb0, bx1, yb1], radius=int(16 * u), fill=(217, 253, 211, int(255 * p)))
        for li, l in enumerate(linhas):
            xx = bx0 + 20 * u
            for ch in l:
                if ch != " ":
                    g, gx, gy = L.glifo(ch, (24, 24, 28, int(255 * p)))
                    E._cola(im, g, xx + gx, yb0 + 14 * u + px * (1.0 + 1.35 * li) + gy)
                xx += L.avanco(ch)
        d.text((bx1 - 14 * u, yb1 - 10 * u), "✓✓", font=E._f_simbolos(int(14 * u)),
               fill=(52, 183, 241, int(255 * p)) if idade > 0.9 else (140, 150, 156, int(255 * p)), anchor="rs")
        y = yb0 - 14 * u
    E._credito(C._pincel(im), it, W, H, u, "escuro")
    return E._com_alfa(im, E._k_tela(t, dur))


# ------------------------------------------------------------------ sons
def batidas(it: Dict[str, Any], dur: float, S: Dict[str, str]) -> List[Tuple[float, str, float, str]]:
    modo = _modo(it)
    cr = cronograma(it, dur)
    ev = cr["eventos"]
    b: List[Tuple[float, str, float, str]] = []
    if modo == "maquina":
        # rajadas de datilografia por linha + sininho e retorno do carro em cada quebra
        ini = cr["inicio"]
        for te, tp, _c in ev:
            if tp == "nl":
                if te - ini > 0.25:
                    b += [(ini + k * 2.3, S["maquina_rajada"], 0.55, "inicio") for k in range(int((te - ini) // 2.3) + 1)]
                b += [(te - 0.18, S["maquina_ding"], 0.45, "pico"), (te, S["maquina_retorno"], 0.6, "pico")]
                ini = te + 0.35
        if cr["fim"] - ini > 0.1:
            b += [(ini + k * 2.3, S["maquina_rajada"], 0.55, "inicio") for k in range(int((cr["fim"] - ini) // 2.3) + 1)]
        b.append((cr["fim"] + 0.05, S["maquina_tecla"], 0.7, "pico"))
    elif modo == "computador":
        if (it.get("programa") or "documento") == "mensagem":
            ini = cr["inicio"]
            for te, tp, _c in ev:
                if tp == "env":
                    b.append((ini, S["digitar_frase"], 0.4, "inicio"))
                    b.append((te, S["mensagem"], 0.55, "pico"))
                    ini = te + 0.2
        else:
            b += [(cr["inicio"] + k * 2.2, S["digitar_frase"], 0.45, "inicio") for k in range(max(1, int((cr["fim"] - cr["inicio"]) // 2.2) + 1))]
    else:
        b.append((0.15, S["papel"], 0.45, "pico"))
        b += [(cr["inicio"] + k * 1.6, S["risco"], 0.35, "inicio") for k in range(max(1, int((cr["fim"] - cr["inicio"]) // 1.6) + 1))]
        if it.get("assinatura"):
            b.append((cr["fim"] + 0.2, S["risco"], 0.5, "inicio"))
    for k, _p in enumerate(_destaques(it)):
        b.append((cr["fim"] + (0.9 if it.get("assinatura") else 0) + 0.3 + 0.6 * k, S["risco"], 0.5, "pico"))
    return [x for x in b if 0 <= x[0] <= dur][:60]


registrar()
