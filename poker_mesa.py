"""
poker_mesa.py — 🃏 motor de poker pros vídeos (v84_277)
=======================================================

Descreve uma mão (texto simples, hand history do PokerStars ou JSON) → o motor joga a mão de verdade (blinds, ordem,
call/bet/raise/all-in, side pots, showdown com o nome do jogo, % de vitória por rua) → uma LINHA DO TEMPO de eventos
com o estado da mesa depois de cada um. O poker_render.py desenha essa linha do tempo (mesa 2D quase 3D) e grava o MP4.

Formato de texto (uma coisa por linha; # = comentário):

    mesa: tema=azul formato=9:16 blinds=0.5/1 unidade=bb titulo="Herói com A5 de ouros"
    jogador: NewSted 79 As 5d heroi
    jogador: FlipFlopidy 58.5 Kc Qc
    jogador: PIKASQ 97
    botao: NewSted
    preflop: PIKASQ fold; FlipFlopidy raise 2.5; NewSted call
    flop: 3d Th 2c | FlipFlopidy bet 3; NewSted call
    turn: Kd | FlipFlopidy check; NewSted check
    river: 7c | FlipFlopidy bet 20; NewSted allin; FlipFlopidy call
    camera: FlipFlopidy              # (opcional, a qualquer hora: a mesa gira pra vista dele)
    nota: Aqui o herói tem o nut flush draw    # (opcional: um balão de texto na hora)

Cartas: As Kd Th 9c 2s (T = 10; ♠ s, ♥ h, ♦ d, ♣ c). Valores em BB (ou na unidade da mesa). "raise X" = aumenta PARA X.
"""
from __future__ import annotations

import itertools
import json
import random
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple


class PokerErro(Exception):
    pass


RANKS = "23456789TJQKA"
NAIPES = "shdc"
NOME_RANK = {"T": "10", "J": "J", "Q": "Q", "K": "K", "A": "A"}
TEMAS = {
    "azul": "🔵 Azul (online moderno)",
    "verde": "🟢 Verde clássico",
    "preto_branco": "⚫ Preto e branco",
    "preto_dourado": "🖤 Preto e dourado",
    "dourado_branco": "🤍 Dourado e branco",
    "vinho": "🍷 Vinho e dourado",
}
FORMATOS = ("16:9", "9:16", "1:1")
MOSTRAR = {"todas": "todas as cartas (tutorial)", "heroi": "só as do herói (o resto no showdown)", "showdown": "só no showdown",
           "pov": "👁 POV: só a mão de quem está na vista (a câmera troca de jogador e esconde as outras)"}
POSICOES = {2: ["BTN", "BB"], 3: ["BTN", "SB", "BB"], 4: ["BTN", "SB", "BB", "UTG"], 5: ["BTN", "SB", "BB", "UTG", "CO"],
            6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"], 7: ["BTN", "SB", "BB", "UTG", "MP", "HJ", "CO"],
            8: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "HJ", "CO"], 9: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"]}


# ------------------------------------------------------------------ cartas
DESCONHECIDA = "??"   # carta que ninguém sabe qual foi (aparece com "?" e não entra na conta)


def carta(c: str) -> str:
    c = str(c or "").strip().replace("10", "T")
    if c in ("??", "?"):
        return DESCONHECIDA
    m = re.fullmatch(r"([2-9TJQKAtjqka])([shdcSHDC♠♥♦♣])", c)
    if not m:
        raise PokerErro(f"Carta inválida: “{c}” (use As, Kd, Th, 9c…)")
    n = {"♠": "s", "♥": "h", "♦": "d", "♣": "c"}.get(m.group(2), m.group(2).lower())
    return m.group(1).upper() + n


def cartas(txt: Any) -> List[str]:
    if isinstance(txt, list):
        return [carta(x) for x in txt]
    return [carta(x) for x in re.findall(r"\?\?|(?:10|[2-9TJQKAtjqka])[shdcSHDC♠♥♦♣]", str(txt or ""))]


def conhecidas(cs: List[str]) -> bool:
    return bool(cs) and DESCONHECIDA not in cs


# ------------------------------------------------------------------ avaliador (7 cartas → melhor de 5)
NOMES_JOGO = ["Carta alta", "Par", "Dois pares", "Trinca", "Sequência", "Flush", "Full house", "Quadra", "Straight flush"]


# 🎲 modalidades: quantas cartas na mão, como monta o jogo e a ordem do ranking
VARIANTES = {
    "holdem": {"nome": "Texas Hold'em", "cartas": 2, "omaha": False, "curto": False},
    "omaha": {"nome": "Omaha (PLO)", "cartas": 4, "omaha": True, "curto": False},
    "omaha5": {"nome": "Omaha 5 cartas (PLO5)", "cartas": 5, "omaha": True, "curto": False},
    "omaha6": {"nome": "Omaha 6 cartas (PLO6)", "cartas": 6, "omaha": True, "curto": False},
    "shortdeck": {"nome": "Short Deck (6+)", "cartas": 2, "omaha": False, "curto": True},
    # sem board: Stud (7 cartas, 4 abertas pra todo mundo) e Draw (5 cartas, troca uma vez)
    "stud": {"nome": "7-Card Stud", "cartas": 7, "omaha": False, "curto": False, "tipo": "stud", "abertas": [2, 3, 4, 5]},
    "draw": {"nome": "5-Card Draw", "cartas": 5, "omaha": False, "curto": False, "tipo": "draw"},
}
RUAS_STUD = {"3a": "s3", "3ª": "s3", "terceira": "s3", "3rd": "s3", "third": "s3", "4a": "s4", "4ª": "s4", "quarta": "s4", "4th": "s4",
             "fourth": "s4", "5a": "s5", "5ª": "s5", "quinta": "s5", "5th": "s5", "fifth": "s5", "6a": "s6", "6ª": "s6", "sexta": "s6",
             "6th": "s6", "sixth": "s6", "7a": "s7", "7ª": "s7", "setima": "s7", "sétima": "s7", "7th": "s7", "seventh": "s7"}
APELIDOS_VARIANTE = {"nlh": "holdem", "nlhe": "holdem", "hold'em": "holdem", "holdem": "holdem", "texas": "holdem",
                     "plo": "omaha", "plo4": "omaha", "omaha": "omaha", "plo5": "omaha5", "omaha5": "omaha5",
                     "plo6": "omaha6", "omaha6": "omaha6", "6+": "shortdeck", "shortdeck": "shortdeck", "short": "shortdeck",
                     "short_deck": "shortdeck", "6plus": "shortdeck", "stud": "stud", "7stud": "stud", "7cardstud": "stud",
                     "seven": "stud", "draw": "draw", "5draw": "draw", "5carddraw": "draw", "fivecarddraw": "draw"}
# força de cada categoria (0 carta alta … 8 straight flush); no Short Deck flush > full house e trinca > sequência
ORDEM = {False: {k: k for k in range(9)}, True: {0: 0, 1: 1, 2: 2, 4: 3, 3: 4, 6: 5, 5: 6, 7: 7, 8: 8}}


def variante(nome: Any) -> str:
    k = str(nome or "holdem").strip().lower().replace(" ", "").replace("-", "")
    return APELIDOS_VARIANTE.get(k, k if k in VARIANTES else "holdem")


def baralho(var: str = "holdem") -> List[str]:
    rs = RANKS[4:] if VARIANTES[var]["curto"] else RANKS
    return [r + s for r in rs for s in NAIPES]


def _valor5(cs: List[str], curto: bool = False) -> Tuple:
    rs = sorted((RANKS.index(c[0]) for c in cs), reverse=True)
    ns = [c[1] for c in cs]
    flush = len(set(ns)) == 1
    uniq = sorted(set(rs), reverse=True)
    seq = None
    if len(uniq) == 5 and uniq[0] - uniq[4] == 4:
        seq = uniq[0]
    elif uniq == [12, 3, 2, 1, 0] and not curto:
        seq = 3  # A-2-3-4-5
    elif uniq == [12, 7, 6, 5, 4] and curto:
        seq = 7  # Short Deck: A-6-7-8-9
    cont = sorted(((rs.count(r), r) for r in set(rs)), reverse=True)
    if seq is not None and flush:
        return (8, seq)
    if cont[0][0] == 4:
        return (7, cont[0][1], cont[1][1])
    if cont[0][0] == 3 and cont[1][0] == 2:
        return (6, cont[0][1], cont[1][1])
    if flush:
        return (5, *rs)
    if seq is not None:
        return (4, seq)
    if cont[0][0] == 3:
        return (3, cont[0][1], *[r for _n, r in cont[1:]])
    if cont[0][0] == 2 and cont[1][0] == 2:
        return (2, cont[0][1], cont[1][1], cont[2][1])
    if cont[0][0] == 2:
        return (1, cont[0][1], *[r for _n, r in cont[1:]])
    return (0, *rs)


def avaliar(cs: List[str]) -> Tuple[Tuple, List[str]]:
    """→ (valor comparável, as 5 cartas do melhor jogo) — Hold'em (as 7 cartas juntas)."""
    if len(cs) < 5:
        return ((-1,), [])
    melhor = max(itertools.combinations(cs, 5), key=_valor5)
    return _valor5(list(melhor)), list(melhor)


def forca(v: Tuple, var: str = "holdem") -> Tuple:
    """O valor comparável na modalidade (no Short Deck a ordem das categorias muda)."""
    if not v or v[0] < 0:
        return (-1,)
    return (ORDEM[VARIANTES[var]["curto"]][v[0]],) + tuple(v)


def avaliar_mao(mao: List[str], board: List[str], var: str = "holdem") -> Tuple[Tuple, Tuple, List[str]]:
    """→ (força comparável, valor do jogo pro nome, as 5 cartas). Omaha: exatamente 2 da mão + 3 da mesa."""
    cfg = VARIANTES[var]
    if cfg["omaha"]:
        if len(board) < 3 or len(mao) < 2:
            return ((-1,), (-1,), [])
        melhor = max((list(a) + list(b) for a in itertools.combinations(mao, 2) for b in itertools.combinations(board, 3)),
                     key=lambda c: forca(_valor5(c), var))
    else:
        todas = list(mao) + list(board)
        if len(todas) < 5:
            return ((-1,), (-1,), [])
        melhor = list(max(itertools.combinations(todas, 5), key=lambda c: forca(_valor5(list(c), cfg["curto"]), var)))
    v = _valor5(melhor, cfg["curto"])
    return forca(v, var), v, melhor


def nome_jogo(v: Tuple) -> str:
    if not v or v[0] < 0:
        return ""
    r = lambda i: NOME_RANK.get(RANKS[i], RANKS[i])  # noqa: E731
    k = v[0]
    if k == 8:
        return "Royal flush" if v[1] == 12 else f"Straight flush até {r(v[1])}"
    if k == 7:
        return f"Quadra de {r(v[1])}"
    if k == 6:
        return f"Full house ({r(v[1])} com {r(v[2])})"
    if k == 5:
        return f"Flush, {r(v[1])} alto"
    if k == 4:
        return f"Sequência até {r(v[1])}"
    if k == 3:
        return f"Trinca de {r(v[1])}"
    if k == 2:
        return f"Dois pares ({r(v[1])} e {r(v[2])})"
    if k == 1:
        return f"Par de {r(v[1])}"
    return f"Carta alta {r(v[1])}"


def equidade(maos: Dict[int, List[str]], board: List[str], mortas: List[str] = (), n: int = 1500, semente: int = 7,
             var: str = "holdem") -> Dict[int, float]:
    """% de vitória (empate dividido) de cada jogador com as cartas conhecidas — Monte Carlo (exato no river)."""
    if len(maos) < 2:
        return {k: 100.0 for k in maos}
    usadas = set(board) | set(mortas) | {c for m in maos.values() for c in m}
    resto = [c for c in baralho(var) if c not in usadas]
    falta = 5 - len(board)
    if VARIANTES[var]["omaha"] and falta > 2:
        n = min(n, 500)  # Omaha: 60 combinações por jogador — menos amostras
    rnd = random.Random(semente)
    pontos = {k: 0.0 for k in maos}
    combos = (itertools.combinations(resto, falta) if falta <= 2 else None)
    if combos is not None and VARIANTES[var]["omaha"] and falta == 2 and len(maos) > 2:
        combos = None  # PLO multiway no flop: amostra
    total = 0
    iterador = combos if combos is not None else (rnd.sample(resto, falta) for _ in range(n))
    for extra in iterador:
        b = board + list(extra)
        vals = {k: avaliar_mao(m, b, var)[0] for k, m in maos.items()}
        top = max(vals.values())
        vencedores = [k for k, v in vals.items() if v == top]
        for k in vencedores:
            pontos[k] += 1.0 / len(vencedores)
        total += 1
    return {k: round(100.0 * v / max(1, total), 1) for k, v in pontos.items()}


# ------------------------------------------------------------------ leitura da mão
# ------------------------------------------------------------------ 🧠 ranges (grade 13×13)
RK_DESC = "AKQJT98765432"


def celula(r1: str, r2: str, naipe: str = "") -> str:
    """("A","K","s") → "AKs"; par → "AA"."""
    a, b = sorted([r1, r2], key=lambda r: RK_DESC.index(r))
    return a + b if a == b else a + b + (naipe or "o")


def celula_da_mao(cs: List[str]) -> str:
    if len(cs) != 2 or DESCONHECIDA in cs:
        return ""
    return celula(cs[0][0], cs[1][0], "s" if cs[0][1] == cs[1][1] else "o")


def _chen(c: str) -> float:
    """Fórmula de Chen (força da mão inicial) — pra ordenar as 169 mãos (top X%)."""
    val = {"A": 10, "K": 8, "Q": 7, "J": 6, "T": 5}
    a, b = c[0], c[1]
    pa = val.get(a, int(a) / 2 if a.isdigit() else 0)
    if a == b:
        return max(5, pa * 2)
    sc = pa + (2 if c.endswith("s") else 0)
    gap = abs(RK_DESC.index(a) - RK_DESC.index(b)) - 1
    sc -= [0, 1, 2, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5][gap]
    if gap <= 1 and RK_DESC.index(a) > RK_DESC.index("Q"):
        sc += 1
    return sc


TODAS_CELULAS = [celula(a, b, n) for i, a in enumerate(RK_DESC) for j, b in enumerate(RK_DESC) if i <= j
                 for n in (["s", "o"] if i < j else [""])]
ORDEM_MAOS = sorted(TODAS_CELULAS, key=lambda c: -_chen(c))
COMBOS = lambda c: 6 if len(c) == 2 else (4 if c.endswith("s") else 12)  # noqa: E731


def ler_range(txt: str) -> List[str]:
    """ "AA-TT, AKs, AQs+, KQo, A5s-A2s, 22+, top 15%" → as células da grade."""
    out: List[str] = []
    t = str(txt or "").replace("%", "% ")
    m = re.search(r"top\s*([\d.,]+)\s*%", t, re.I)
    if m or re.search(r"\b(any|todas|100%)\b", t, re.I):
        alvo = (_num(m.group(1)) if m else 100) / 100 * 1326
        soma = 0
        for c in ORDEM_MAOS:
            if soma >= alvo - 1e-9:
                break
            out.append(c)
            soma += COMBOS(c)
        t = re.sub(r"top\s*[\d.,]+\s*%|\bany\b|\btodas\b|100%", " ", t, flags=re.I)
    for tok in re.split(r"[,\s]+", t.strip()):
        tok = tok.strip().upper().replace("10", "T")
        if not tok:
            continue
        mais = tok.endswith("+")
        tok = tok.rstrip("+")
        if "-" in tok:
            a, b = tok.split("-", 1)
        else:
            a = b = tok
        if not re.fullmatch(r"[AKQJT2-9]{2}[SO]?", a) or not re.fullmatch(r"[AKQJT2-9]{2}[SO]?", b):
            raise PokerErro(f"range: não entendi “{tok}” (ex.: AA-TT, AKs, AQo+, 22+, top 15%)")
        suf = (a[2:] or "").lower()
        if a[0] == a[1]:  # pares
            i0, i1 = sorted([RK_DESC.index(a[0]), RK_DESC.index(b[0])])
            if mais:
                i0 = 0
            out += [r + r for r in RK_DESC[i0:i1 + 1]]
        else:
            alto = a[0]
            k0, k1 = sorted([RK_DESC.index(a[1]), RK_DESC.index(b[1])])
            if mais:  # AQs+ = AQs, AKs (sobe o kicker até abaixo da carta alta)
                k0 = RK_DESC.index(alto) + 1
            for k in range(k0, k1 + 1):
                if RK_DESC[k] == alto:
                    continue
                for n in ([suf] if suf else ["s", "o"]):
                    out.append(celula(alto, RK_DESC[k], n))
    vistos, final = set(), []
    for c in out:
        if c not in vistos:
            vistos.add(c)
            final.append(c)
    return final


def pct_range(cels: List[str]) -> float:
    return round(100.0 * sum(COMBOS(c) for c in cels) / 1326, 1)


def _num(x: Any) -> float:
    try:
        return float(str(x).replace(",", ".").replace("bb", "").replace("BB", "").replace("$", ""))
    except ValueError as exc:
        raise PokerErro(f"Valor inválido: “{x}”") from exc


ACOES = {"fold": "fold", "f": "fold", "desiste": "fold", "larga": "fold", "check": "check", "x": "check", "passa": "check",
         "mesa": "check", "call": "call", "c": "call", "paga": "call", "bet": "bet", "b": "bet", "aposta": "bet",
         "raise": "raise", "r": "raise", "aumenta": "raise", "allin": "allin", "all-in": "allin", "shove": "allin",
         "push": "allin", "vai": "allin"}


EMOCOES = {"irritado": "😠", "bravo": "😠", "furioso": "🤬", "raiva": "😡", "ansioso": "😰", "nervoso": "😬", "tenso": "😬",
           "medo": "😨", "assustado": "😨", "chocado": "😱", "surpreso": "😲", "confiante": "😎", "tranquilo": "😌",
           "feliz": "😄", "alegre": "😁", "rindo": "😂", "triste": "😢", "chorando": "😭", "pensativo": "🤔", "duvida": "🤔",
           "dúvida": "🤔", "blefando": "😏", "malicioso": "😏", "aliviado": "😮‍💨", "frio": "🥶", "calculando": "🧐",
           "entediado": "😑", "suando": "😅", "explodindo": "🤯", "incredulo": "🫨", "incrédulo": "🫨", "vitoria": "🤩",
           "vitória": "🤩", "comemorando": "🥳", "desesperado": "😩", "sorte": "🍀", "fogo": "🔥", "gelo": "🧊", "silencio": "🤐",
           "silêncio": "🤐", "rezando": "🙏", "olhos": "👀", "coracao": "💔", "coração": "💔"}
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def extra_de(chave: str, resto: str, apos: int = 0) -> Optional[Dict[str, Any]]:
    """Uma linha de efeito (câmera, nota, zoom, emoção, mostrar) → o extra; None se não for efeito."""
    chave = chave.strip().lower()
    resto = resto.strip()
    if chave in ("camera", "câmera", "vista", "pov"):
        return {"tipo": "camera", "quem": resto, "apos": apos}
    if chave == "nota":
        return {"tipo": "nota", "texto": resto[:200], "apos": apos}
    if chave in ("zoom", "aproxima", "close"):
        toks = resto.split()
        escala = next((_num(t) for t in toks if re.fullmatch(r"[\d.,]+x?", t, re.I)), 0) or (1.0 if (toks[:1] or [""])[0].lower() in ("off", "sai", "fora", "0") else 1.35)
        alvo = " ".join(t for t in toks if not re.fullmatch(r"[\d.,]+x?", t, re.I)) or "board"
        if alvo.lower() in ("off", "sai", "fora", "nada"):
            alvo, escala = "off", 1.0
        return {"tipo": "zoom", "alvo": alvo, "escala": max(1.0, min(2.2, float(escala))), "apos": apos}
    if chave in ("emocao", "emoção", "emoji", "sente", "sentimento", "reacao", "reação"):
        texto = ""
        m = re.search(r"[\"“](.+?)[\"”]", resto)
        if m:
            texto, resto = m.group(1).strip(), (resto[:m.start()] + resto[m.end():]).strip()
        toks = resto.split()
        emoji = next((t for t in toks if _EMOJI_RE.search(t)), "")
        palavra = next((t for t in toks if t.lower() in EMOCOES), "")
        quem = " ".join(t for t in toks if t not in (emoji, palavra))
        return {"tipo": "emocao", "quem": quem, "emoji": emoji or EMOCOES.get(palavra.lower(), "😐"), "texto": texto[:90],
                "palavra": palavra, "apos": apos}
    if chave in ("acordo", "deal", "chop", "divisao", "divisão"):
        toks = resto.replace("%", " ").split()
        modo = "dividir"
        partes: Dict[str, float] = {}
        if toks and toks[0].lower() in ("equidade", "equity", "icm", "chance", "chances"):
            modo = "equidade"
        elif any(re.fullmatch(r"[\d.,]+", t) for t in toks):
            modo, nome = "partes", []
            for t in toks:
                if re.fullmatch(r"[\d.,]+", t) and nome:
                    partes[" ".join(nome)] = _num(t)
                    nome = []
                elif not re.fullmatch(r"[\d.,]+", t):
                    nome.append(t)
        texto = ""
        m = re.search(r"[\"“](.+?)[\"”]", resto)
        if m:
            texto = m.group(1).strip()
        return {"tipo": "acordo", "modo": modo, "partes": partes, "texto": texto[:120], "apos": apos}
    if chave in ("fim", "interrompe", "interrompida", "fim_da_mao", "end"):
        m = re.search(r"[\"“](.+?)[\"”]", resto)
        return {"tipo": "fim", "texto": (m.group(1) if m else resto).strip()[:200], "apos": apos}
    if chave in ("range", "faixa", "ranges"):
        toks = resto.split(None, 1)
        return {"tipo": "range", "quem": toks[0] if toks else "", "spec": toks[1] if len(toks) > 1 else "", "apos": apos}
    if chave in ("correr", "run", "rodar", "runs"):
        n = int(_num((resto.split() or ["2"])[0]) or 2)
        return {"tipo": "correr", "n": max(1, min(3, n)), "apos": apos}
    if chave in ("mostrar", "cartas", "revelar"):
        modo = resto.lower().split()[0] if resto else "heroi"
        modo = {"tudo": "todas", "todos": "todas", "all": "todas", "hero": "heroi", "herói": "heroi"}.get(modo, modo)
        return {"tipo": "mostrar", "modo": modo if modo in MOSTRAR else "heroi", "apos": apos}
    return None


def _acoes(txt: str) -> List[Dict[str, Any]]:
    out = []
    for parte in re.split(r"[;\n]+", txt or ""):
        p = parte.strip()
        if not p:
            continue
        m = re.fullmatch(r"\[(.+)\]", p)
        if m:  # [zoom: Fulano] · [emocao: Fulano ansioso] · [camera: Fulano] · [nota: ...] no meio das ações
            chave, _, resto = m.group(1).partition(":")
            x = extra_de(chave, resto)
            if x is None:
                raise PokerErro(f"Não entendi o efeito “{p}” (ex.: [zoom: Fulano] [emocao: Fulano ansioso])")
            out.append({"extra": x})
            continue
        toks = p.split()
        # "Nome ação [valor]" — o nome pode ter espaços: a ação é a 1ª palavra conhecida
        k = next((i for i, t in enumerate(toks) if t.lower() in ACOES and i > 0), None)
        if k is None:
            if toks and toks[0].lower() in ACOES:  # sem nome: o próximo a agir
                k = 0
            else:
                raise PokerErro(f"Não entendi a ação: “{p}” (ex.: Fulano raise 3)")
        a = {"quem": " ".join(toks[:k]), "acao": ACOES[toks[k].lower()]}
        if a["acao"] in ("bet", "raise") and len(toks) > k + 1:
            a["valor"] = _num(toks[k + 1])
        elif a["acao"] in ("bet", "raise"):
            raise PokerErro(f"Falta o valor em “{p}”")
        out.append(a)
    return out


def _trocas(txt: str) -> List[Dict[str, Any]]:
    """5-Card Draw: "Fulano Kh 3c > 9d 9s; Ciclano fica" — as que ele joga fora > as que recebe."""
    out = []
    for parte in re.split(r"[;\n]+", txt or ""):
        p = parte.strip()
        if not p:
            continue
        antes, _, depois = p.partition(">")
        toks = antes.split()
        fica = any(t.lower() in ("fica", "stand", "pat", "0", "nenhuma") for t in toks)
        nome = " ".join(t for t in toks if not re.fullmatch(r"(?:10|[2-9TJQKAtjqka])[shdcSHDC♠♥♦♣]", t)
                        and not re.fullmatch(r"\d+", t) and t.lower() not in ("fica", "stand", "pat", "troca", "nenhuma"))
        n = next((int(t) for t in toks if re.fullmatch(r"\d+", t)), None)
        fora, novas = cartas(antes), cartas(depois)
        if fica:
            fora, novas, n = [], [], 0
        if n is None:
            n = len(novas) or len(fora)
        if fora and novas and len(fora) != len(novas):
            raise PokerErro(f"troca: {nome} joga fora {len(fora)} e recebe {len(novas)} — tem que ser o mesmo número.")
        out.append({"quem": nome, "fora": fora, "novas": novas, "n": n})
    return out


def ler_texto(txt: str) -> Dict[str, Any]:
    """O formato de texto simples (ver o topo do arquivo) → a mão em dicionário."""
    m: Dict[str, Any] = {"mesa": {}, "jogadores": [], "ruas": [], "extras": []}
    for linha in str(txt or "").splitlines():
        linha = linha.split("#", 1)[0].strip() if not linha.strip().lower().startswith("nota:") else linha.strip()
        if not linha or ":" not in linha:
            continue
        chave, resto = linha.split(":", 1)
        chave, resto = chave.strip().lower(), resto.strip()
        if chave == "mesa":
            for t in shlex.split(resto):
                if "=" in t:
                    a, b = t.split("=", 1)
                    m["mesa"][a.lower()] = b
        elif chave == "jogador":
            toks = resto.split()
            if len(toks) < 2:
                raise PokerErro(f"jogador: precisa de nome e stack — “{linha}”")
            idx = next((i for i, t in enumerate(toks) if re.fullmatch(r"[\d.,]+(bb)?", t, re.I)), None)
            if idx is None or idx == 0:
                raise PokerErro(f"jogador: falta o stack (número) — “{linha}”")
            nome, stack, rest = " ".join(toks[:idx]), _num(toks[idx]), toks[idx + 1:]
            pais = next((t.split("=", 1)[1] for t in rest if t.lower().startswith(("pais=", "país=", "flag="))), "")
            foto = next((t.split("=", 1)[1] for t in rest if t.lower().startswith(("foto=", "avatar="))), "")
            j = {"nome": nome, "stack": stack, "cartas": cartas(" ".join(t for t in rest if "=" not in t)),
                 "heroi": any(t.lower() in ("heroi", "herói", "hero") for t in rest), "pais": pais.upper()[:3], "avatar": foto}
            m["jogadores"].append(j)
        elif chave in ("botao", "botão", "button", "dealer"):
            m["botao"] = resto
        elif chave in RUAS_STUD:
            m["ruas"].append({"rua": RUAS_STUD[chave], "cartas": [], "acoes": _acoes(resto)})
            m["extras"].append({"tipo": "rua", "rua": RUAS_STUD[chave]})
        elif chave in ("troca", "trocas", "draw", "descarte", "descartes"):
            m["ruas"].append({"rua": "troca", "cartas": [], "acoes": [], "trocas": _trocas(resto)})
        elif chave in ("pos", "pós", "depois", "2a", "segunda", "final_apostas"):
            m["ruas"].append({"rua": "pos", "cartas": [], "acoes": _acoes(resto)})
        elif chave in ("preflop", "flop", "turn", "river"):
            board, _, acs = resto.partition("|") if chave != "preflop" else ("", "", resto)
            m["ruas"].append({"rua": chave, "cartas": cartas(board), "acoes": _acoes(acs)})
            m["extras"].append({"tipo": "rua", "rua": chave})
        elif re.fullmatch(r"(board|run|corrida)\s*[23]", chave):
            m.setdefault("boards_extra", {})[int(chave[-1])] = cartas(resto)
        elif chave in ("camera", "câmera", "vista", "pov") and not m["ruas"] and not any(x["tipo"] == "camera" for x in m["extras"]):
            m["camera_inicial"] = resto
        elif extra_de(chave, resto, len(m["ruas"])) is not None:
            m["extras"].append(extra_de(chave, resto, len(m["ruas"])))
    return m


def ler_pokerstars(txt: str) -> Dict[str, Any]:
    """Hand history do PokerStars (e parecidos: GG, 888 no mesmo formato) → a mão. Valores convertidos em BB."""
    t = str(txt or "")
    bb_m = re.search(r"\(\s*[$€£₹]?([\d.,]+)\s*/\s*[$€£₹]?([\d.,]+)", t)
    if not bb_m:
        raise PokerErro("Não achei os blinds (ex.: ($0.01/$0.02)) no hand history.")
    sb, bb = _num(bb_m.group(1)), _num(bb_m.group(2))
    conv = lambda v: round(_num(v) / bb, 2)  # noqa: E731
    btn_seat = re.search(r"Seat #(\d+) is the button", t)
    jogadores, por_assento = [], {}
    for mm in re.finditer(r"^Seat (\d+): (.+?) \([$€£₹]?([\d.,]+) in chips", t, re.M):
        j = {"nome": mm.group(2).strip(), "stack": conv(mm.group(3)), "cartas": [], "assento": int(mm.group(1))}
        jogadores.append(j)
        por_assento[int(mm.group(1))] = j
    if not jogadores:
        raise PokerErro("Não achei os jogadores (linhas “Seat 1: Nome (100 in chips)”).")
    for mm in re.finditer(r"^Dealt to (.+?) \[(.+?)\]", t, re.M):
        for j in jogadores:
            if j["nome"] == mm.group(1).strip():
                j["cartas"], j["heroi"] = cartas(mm.group(2)), True
    for mm in re.finditer(r"^(.+?): shows \[(.+?)\]", t, re.M):
        for j in jogadores:
            if j["nome"] == mm.group(1).strip():
                j["cartas"] = cartas(mm.group(2))
    m: Dict[str, Any] = {"mesa": {"blinds": f"{0.5 if sb / bb == 0.5 else round(sb / bb, 2)}/1", "unidade": "bb"},
                         "jogadores": jogadores, "ruas": [], "extras": []}
    cab = t[:300].lower()
    if "omaha" in cab:
        m["mesa"]["jogo"] = "omaha6" if "6 card" in cab else "omaha5" if "5 card" in cab else "omaha"
    elif "6+" in cab or "short deck" in cab:
        m["mesa"]["jogo"] = "shortdeck"
    if btn_seat and int(btn_seat.group(1)) in por_assento:
        m["botao"] = por_assento[int(btn_seat.group(1))]["nome"]
    blocos = re.split(r"^\*\*\* (HOLE CARDS|FLOP|TURN|RIVER|SHOW DOWN|SUMMARY) \*\*\*(.*)$", t, flags=re.M)
    rua_nome = {"HOLE CARDS": "preflop", "FLOP": "flop", "TURN": "turn", "RIVER": "river"}
    i = 1
    while i + 2 < len(blocos) + 1 and i < len(blocos):
        nome, cab, corpo = blocos[i], blocos[i + 1], blocos[i + 2] if i + 2 < len(blocos) else ""
        i += 3
        if nome not in rua_nome:
            continue
        bd = re.findall(r"\[(.+?)\]", cab)
        novas = cartas(bd[-1]) if bd and nome != "HOLE CARDS" else []
        acs = []
        for mm in re.finditer(r"^(.+?): (folds|checks|calls|bets|raises|is all-in)(?:\s+[$€£₹]?([\d.,]+))?(?:\s+to\s+[$€£₹]?([\d.,]+))?(.*)$", corpo, re.M):
            quem, ac = mm.group(1).strip(), mm.group(2)
            allin = "all-in" in (mm.group(5) or "")
            if ac == "folds":
                acs.append({"quem": quem, "acao": "fold"})
            elif ac == "checks":
                acs.append({"quem": quem, "acao": "check"})
            elif ac == "calls":
                acs.append({"quem": quem, "acao": "call"})
            elif ac == "bets":
                acs.append({"quem": quem, "acao": "allin" if allin else "bet", "valor": conv(mm.group(3))})
            elif ac == "raises":
                acs.append({"quem": quem, "acao": "allin" if allin else "raise", "valor": conv(mm.group(4) or mm.group(3))})
        m["ruas"].append({"rua": rua_nome[nome], "cartas": novas, "acoes": acs})
    return m


def ler(entrada: Any) -> Dict[str, Any]:
    """Texto simples, hand history ou JSON → a mão."""
    if isinstance(entrada, dict):
        return entrada
    t = str(entrada or "").strip()
    if t.startswith("{"):
        try:
            return json.loads(t)
        except ValueError as exc:
            raise PokerErro(f"JSON inválido: {exc}") from exc
    if re.search(r"^\*\*\* HOLE CARDS \*\*\*", t, re.M) or re.search(r"^Seat \d+: .+ in chips", t, re.M):
        return ler_pokerstars(t)
    return ler_texto(t)


# ------------------------------------------------------------------ o motor (joga a mão) → linha do tempo
RITMO_SHORTS = {"intro": 0.5, "carta_jogador": 0.6, "blinds": 0.5, "recolher": 0.7, "equidade": 0.8, "camera": 0.85,
                "showdown": 1.5, "vencedor": 1.2, "final": 0.8, "nota": 0.85}
TEMPOS = {"intro": 1.2, "carta_jogador": 0.13, "blinds": 0.8, "pensa": 0.45, "acao": 0.75, "fold": 0.7, "recolher": 0.7,
          "board": 0.45, "flop_extra": 0.35, "showdown": 1.4, "vencedor": 1.6, "final": 2.2, "camera": 1.3, "nota": 2.6, "pausa": 0.4,
          "equidade": 0.9}


def _fmt(v: float) -> str:
    v = round(float(v), 2)
    return str(int(v)) if v == int(v) else f"{v:g}"


class _Mao:
    def __init__(self, m: Dict[str, Any], velocidade: float = 1.0, ritmo: str = "", pov: str = ""):
        self.m = m
        mesa = {k.lower(): v for k, v in (m.get("mesa") or {}).items()}
        self.mesa = mesa
        js = m.get("jogadores") or []
        if not 2 <= len(js) <= 9:
            raise PokerErro("A mesa precisa de 2 a 9 jogadores.")
        nomes = [str(j.get("nome") or "").strip() for j in js]
        if len(set(n.lower() for n in nomes)) != len(nomes) or not all(nomes):
            raise PokerErro("Cada jogador precisa de um nome diferente.")
        self.var = variante(mesa.get("jogo") or mesa.get("variante") or mesa.get("modalidade") or m.get("variante"))
        self.ncartas = VARIANTES[self.var]["cartas"]
        self.tipo = VARIANTES[self.var].get("tipo", "board")   # board (Hold'em/Omaha) · stud · draw
        self.js = [{"nome": n, "stack": round(_num(j.get("stack") or 0), 2), "cartas": cartas(j.get("cartas") or []),
                    "heroi": bool(j.get("heroi")), "avatar": j.get("avatar") or "", "pais": j.get("pais") or ""} for n, j in zip(nomes, js)]
        usadas = [c for j in self.js for c in j["cartas"] if c != DESCONHECIDA] + [c for r in m.get("ruas") or [] for c in r.get("cartas") or [] if c != DESCONHECIDA]
        if len(usadas) != len(set(usadas)):
            raise PokerErro("Tem carta repetida na mão.")
        if VARIANTES[self.var]["curto"] and any(c[0] in "2345" for c in usadas):
            raise PokerErro("Short Deck não tem cartas de 2 a 5.")
        for j in self.js:
            if j["cartas"] and len(j["cartas"]) != self.ncartas and not (self.tipo == "stud" and len(j["cartas"]) < self.ncartas):
                raise PokerErro(f"{j['nome']}: no {VARIANTES[self.var]['nome']} cada jogador tem {self.ncartas} cartas.")
        bl = str(mesa.get("blinds") or "0.5/1").split("/")
        self.sb, self.bb = _num(bl[0]), _num(bl[1] if len(bl) > 1 else bl[0])
        self.ante = _num(mesa.get("ante") or 0)
        lim = str(mesa.get("limite") or mesa.get("limit") or ("pl" if VARIANTES[self.var]["omaha"] else "nl")).lower().replace("-", "")
        self.limite = "pl" if lim in ("pl", "pot", "potlimit", "plo") else "nl"   # pot-limit: ninguém aposta mais que o pote
        stv = str(mesa.get("straddle") or "").strip().lower()
        self.straddle = (2 * self.bb if stv in ("sim", "1", "true", "s", "yes") else _num(stv)) if stv and stv not in ("0", "nao", "não", "false") else 0.0
        self.st_i = None
        self.estrategia = str(mesa.get("estrategia") or mesa.get("estratégia") or "").lower() in ("1", "sim", "true", "on")
        self.ranges: Dict[int, List[str]] = {}
        self._eq_cache: Dict[Any, Dict[int, float]] = {}
        self.unidade = str(mesa.get("unidade") or "bb")
        self.vel = max(0.4, min(3.0, float(velocidade or 1.0)))
        self.ritmo = "shorts" if str(ritmo or mesa.get("ritmo") or "").lower() in ("shorts", "short", "rapido", "rápido") else "normal"
        self.pov_auto = str(pov or mesa.get("pov") or "").lower() in ("auto", "1", "sim", "true")
        self._cam_t = -99.0
        self.ev: List[Dict[str, Any]] = []
        self.t = 0.0
        n = len(self.js)
        b = m.get("botao")
        self.btn = self.idx(b) if b else n - 1
        heroi = next((i for i, j in enumerate(self.js) if j["heroi"]), None)
        self.vista = self.idx(m["camera_inicial"]) if m.get("camera_inicial") else (heroi if heroi is not None else self.btn)
        ordem = [(self.btn + k) % n for k in range(n)]
        self.pos = {i: POSICOES[n][k] for k, i in enumerate(ordem)}
        self.stack = [j["stack"] for j in self.js]
        self.inicial = list(self.stack)
        self.aposta = [0.0] * n
        self.investido = [0.0] * n
        self.fora = [False] * n
        self.allin = [False] * n
        self.pot = 0.0
        self.board: List[str] = []
        self.ultima = [""] * n
        self.vez: Optional[int] = None
        self.equidade: Dict[int, float] = {}
        self.ganhos: Dict[int, float] = {}
        self.jogos: Dict[int, str] = {}
        self.revelado = [False] * n
        self.mostrar = str(mesa.get("mostrar") or "")
        self.runs, self.corte, self.boards_x = 1, 0, []   # run it twice/três vezes
        self.encerrada = False                           # 🤝 acordo: a mão termina ali
        extra_cs = [c for b in (m.get("boards_extra") or {}).values() for c in b]
        if len(set(extra_cs + usadas)) != len(extra_cs) + len(usadas):
            raise PokerErro("Tem carta repetida nos boards da corrida (run it twice).")
        self.zooms: List[Dict[str, Any]] = []    # não bloqueiam: a câmera aproxima enquanto a mão segue
        self.emocoes: List[Dict[str, Any]] = []
        self.mostrares: List[Dict[str, Any]] = []
        self.rua = "preflop"
        self.maos = [list(j["cartas"]) for j in self.js]   # Draw: as cartas mudam na troca
        novas_troca = [c for r in m.get("ruas") or [] for t in r.get("trocas") or [] for c in t["novas"]]
        if len(set(novas_troca + usadas)) != len(novas_troca) + len(usadas):
            raise PokerErro("Tem carta repetida nas trocas.")

    def idx(self, nome: str) -> int:
        n = str(nome or "").strip().lower()
        for i, j in enumerate(self.js):
            if j["nome"].lower() == n:
                return i
        for i, j in enumerate(self.js):
            if j["nome"].lower().startswith(n) and n:
                return i
        raise PokerErro(f"Não tem jogador “{nome}” na mesa.")

    def fmt(self, v: float) -> str:
        return f"{_fmt(v)} BB" if self.unidade.lower() == "bb" else (f"${_fmt(v)}" if self.unidade == "$" else _fmt(v))

    def estado(self) -> Dict[str, Any]:
        return {"stack": [round(x, 2) for x in self.stack], "aposta": [round(x, 2) for x in self.aposta], "pot": round(self.pot, 2),
                "board": list(self.board), "fora": list(self.fora), "allin": list(self.allin), "ultima": list(self.ultima),
                "vez": self.vez, "vista": self.vista, "equidade": dict(self.equidade), "revelado": list(self.revelado),
                "jogos": dict(self.jogos), "ganhos": {k: round(v, 2) for k, v in self.ganhos.items()}, "rua": self.rua,
                "boards_x": [dict(b, cartas=list(b["cartas"])) for b in self.boards_x], "maos": [list(x) for x in self.maos]}

    def evento(self, tipo: str, dur: float, **dados: Any) -> None:
        if self.ritmo == "shorts":  # ⚡ shorts: o que é rotina voa, o que é emoção ganha câmera lenta
            f = RITMO_SHORTS.get(tipo, 1.0)
            if tipo == "acao":
                f = 1.7 if dados.get("acao") == "allin" or str(dados.get("rotulo", "")).startswith("ALL-IN") else 0.45 if dados.get("acao") == "fold" else 0.85
            elif tipo == "pensa":
                f = 0.35 if self.rua == "preflop" else 0.9
            elif tipo == "board" and dados.get("pos") == 4:
                f = 3.2  # o river vira devagar
            elif tipo == "board" and dados.get("pos") == 3:
                f = 1.6
            dur *= f
        if tipo == "camera":
            self._cam_t = self.t
        d = round(dur / self.vel, 3)
        self.ev.append({"tipo": tipo, "t0": round(self.t, 3), "dur": d, "dados": dados, "depois": self.estado()})
        self.t += d

    # -- regras
    def ativos(self) -> List[int]:
        return [i for i in range(len(self.js)) if not self.fora[i]]

    def podem_agir(self) -> List[int]:
        return [i for i in self.ativos() if not self.allin[i]]

    def por(self, i: int, valor: float) -> float:
        v = max(0.0, min(valor, self.stack[i]))
        self.stack[i] -= v
        self.aposta[i] += v
        self.investido[i] += v
        if self.stack[i] <= 1e-9:
            self.stack[i] = 0.0
            self.allin[i] = True
        return v

    def blinds(self) -> None:
        n = len(self.js)
        if self.tipo == "stud":   # Stud: só ante (o bring-in vem escrito como aposta na 3ª rua)
            self.sb_i = self.bb_i = None
            if self.ante:
                for i in range(n):
                    self.por(i, self.ante)
                    self.ultima[i] = "ANTE"
                self.evento("blinds", TEMPOS["blinds"], quem=list(range(n)))
            return
        if n == 2:
            sb_i, bb_i = self.btn, (self.btn + 1) % n
        else:
            sb_i, bb_i = (self.btn + 1) % n, (self.btn + 2) % n
        self.sb_i, self.bb_i = sb_i, bb_i
        if self.ante:
            for i in range(n):
                self.por(i, self.ante)
            self.recolher()
        self.por(sb_i, self.sb)
        self.por(bb_i, self.bb)
        self.ultima[sb_i], self.ultima[bb_i] = "SB", "BB"
        quem = [sb_i, bb_i]
        if self.straddle and n >= 3:   # straddle: o UTG põe o dobro (ou o valor escrito) e fala por último no pré-flop
            self.st_i = (bb_i + 1) % n
            self.por(self.st_i, self.straddle)
            self.ultima[self.st_i] = "STRADDLE"
            quem.append(self.st_i)
        self.evento("blinds", TEMPOS["blinds"], quem=quem)

    def recolher(self) -> None:
        tinha = [i for i, a in enumerate(self.aposta) if a > 0]
        self.pot += sum(self.aposta)
        self.aposta = [0.0] * len(self.js)
        return tinha

    def calc_equidade(self) -> None:
        if self.tipo != "board":
            self.equidade = {}
            return
        maos = {i: self.js[i]["cartas"] for i in self.ativos() if len(self.js[i]["cartas"]) == self.ncartas and conhecidas(self.js[i]["cartas"])}
        if len(maos) >= 2 and len(maos) == len(self.ativos()):
            mortas = [c for i, j in enumerate(self.js) if self.fora[i] for c in j["cartas"]]
            self.equidade = equidade(maos, list(self.board), mortas, var=self.var)
        else:
            self.equidade = {}

    def decisao(self, quem: int, falta: float, pos_antes: float) -> Dict[str, Any]:
        """🧠 o que o jogador encara: quanto paga, quanto pode ganhar, a % que precisa (pot odds), a que tem, o EV do call e o SPR.
        (calculado com o estado ANTES da ação dele — o motor já aplicou a ação, então desfaz as contas aqui)"""
        aposta_dele = pos_antes
        pagar = min(falta, self.stack[quem] + (self.aposta[quem] - pos_antes))
        pote = self.pot + sum(self.aposta) - (self.aposta[quem] - aposta_dele)
        precisa = 100.0 * pagar / max(1e-9, pote + pagar)
        eq = None
        vivos = [i for i in range(len(self.js)) if not self.fora[i] or i == quem]
        if self.tipo == "board" and all(len(self.js[i]["cartas"]) == self.ncartas and conhecidas(self.js[i]["cartas"]) for i in vivos) \
                and DESCONHECIDA not in self.board and len(vivos) >= 2:
            chave = (len(self.board), tuple(vivos))
            if chave not in self._eq_cache:
                mortas = [c for i, j in enumerate(self.js) if i not in vivos for c in j["cartas"]]
                self._eq_cache[chave] = equidade({i: self.js[i]["cartas"] for i in vivos}, list(self.board), mortas, n=900, var=self.var)
            eq = self._eq_cache[chave].get(quem)
        ev = None if eq is None else round(eq / 100 * (pote + pagar) - pagar, 2)
        resto = self.stack[quem] + (self.aposta[quem] - pos_antes) - pagar
        outros = [self.stack[i] + self.aposta[i] for i in vivos if i != quem]
        spr = round(min([resto] + outros) / max(1e-9, pote + pagar), 1) if outros else None
        return {"pagar": round(pagar, 2), "pote": round(pote, 2), "precisa": round(precisa, 1), "eq": eq, "ev": ev, "spr": spr}

    def dar_stud(self, k_rua: int) -> None:
        """Stud: 3ª rua = 2 fechadas + 1 aberta; 4ª–6ª = 1 aberta; 7ª = 1 fechada (pra quem ainda está na mão)."""
        n = len(self.js)
        ks = [0, 1, 2] if k_rua == 3 else [k_rua - 1]
        for k in ks:
            for d in range(n):
                i = (self.btn + 1 + d) % n
                if not self.fora[i]:
                    self.evento("carta_jogador", TEMPOS["carta_jogador"] * (1.6 if k_rua > 3 else 1), quem=i, k=k)

    def trocar(self, trocas: List[Dict[str, Any]]) -> None:
        """Draw: cada um joga fora as cartas que não quer e recebe as novas."""
        tinha = self.recolher()
        if tinha:
            self.evento("recolher", TEMPOS["recolher"], de=tinha)
        self.ultima = ["" if not self.fora[i] else "FOLD" for i in range(len(self.js))]
        for tr in trocas:
            i = self.idx(tr["quem"])
            if self.fora[i]:
                continue
            mao = self.maos[i]
            if tr["fora"] and mao:
                if any(c not in mao for c in tr["fora"]):
                    raise PokerErro(f"troca: {self.js[i]['nome']} não tem {' '.join(c for c in tr['fora'] if c not in mao)}.")
                pos = [mao.index(c) for c in tr["fora"]]
            else:
                pos = list(range(self.ncartas - tr["n"], self.ncartas)) if tr["n"] else []
            if tr["novas"]:
                if len(tr["novas"]) != len(pos):
                    raise PokerErro(f"troca: {self.js[i]['nome']} troca {len(pos)} e recebe {len(tr['novas'])}.")
                if mao:
                    for p, c in zip(pos, tr["novas"]):
                        mao[p] = c
            self.ultima[i] = f"TROCA {len(pos)}" if pos else "FICA"
            self.vez = i
            self.evento("troca", 1.3 if pos else 0.6, quem=i, pos=pos, n=len(pos))
        self.vez = None

    def jogar_rua(self, rua: Dict[str, Any], extras: List[Dict[str, Any]]) -> None:
        self.rua = rua["rua"]
        if self.rua == "troca":
            self.trocar(rua.get("trocas") or [])
            return
        if self.tipo == "stud":
            k_rua = int(self.rua[1])
            if k_rua > 3:
                tinha = self.recolher()
                if tinha:
                    self.evento("recolher", TEMPOS["recolher"], de=tinha)
                self.ultima = ["" if not self.fora[i] else "FOLD" for i in range(len(self.js))]
            self.dar_stud(k_rua)
        elif self.rua == "pos":
            tinha = self.recolher()
            if tinha:
                self.evento("recolher", TEMPOS["recolher"], de=tinha)
            self.ultima = ["" if not self.fora[i] else "FOLD" for i in range(len(self.js))]
        elif self.rua != "preflop":
            tinha = self.recolher()
            if tinha:
                self.evento("recolher", TEMPOS["recolher"], de=tinha)
            self.ultima = ["" if not self.fora[i] else "FOLD" for i in range(len(self.js))]
            novas = rua.get("cartas") or []
            esperado = {"flop": 3, "turn": 1, "river": 1}[self.rua]
            if len(novas) != esperado:
                raise PokerErro(f"{self.rua}: precisa de {esperado} carta(s) (veio {len(novas)}).")
            for k, c in enumerate(novas):
                self.board.append(c)
                self.vez = None
                self.evento("board", TEMPOS["board"] + (TEMPOS["flop_extra"] if k == 0 and esperado == 3 else 0), carta=c, pos=len(self.board) - 1)
            if self.mesa.get("equidade", "1") not in ("0", "nao", "não", "false"):
                self.calc_equidade()
                if self.equidade:
                    self.evento("equidade", TEMPOS["equidade"])
        self.rodar_extras(extras)
        n = len(self.js)
        acoes = list(rua.get("acoes") or [])
        if self.rua == "preflop" and self.tipo != "stud":
            primeiro = ((self.st_i if self.st_i is not None else self.bb_i) + 1) % n
            maior = max(self.bb, self.straddle if self.st_i is not None else 0)
        else:
            primeiro = (self.btn + 1) % n
            maior = 0.0
        vez = primeiro
        for a in acoes:
            if self.encerrada:
                break
            if a.get("extra"):
                self.rodar_extras([a["extra"]])
                continue
            if len(self.ativos()) <= 1:
                break
            quem = self.idx(a["quem"]) if a.get("quem") else None
            if quem is None:  # sem nome: o próximo que pode agir
                while self.fora[vez] or self.allin[vez]:
                    vez = (vez + 1) % n
                quem = vez
            if self.fora[quem]:
                raise PokerErro(f"{self.js[quem]['nome']} já tinha desistido ({self.rua}).")
            if self.allin[quem]:
                continue
            self.vez = quem
            ac = a["acao"]
            if self.pov_auto and quem != self.vista and self.t - self._cam_t >= 2.5 and (
                    ac == "allin" or (ac in ("bet", "raise") and self.rua != "preflop") or (ac == "call" and any(self.allin))):
                self.vista = quem  # 👁 POV automático: a câmera vai pra quem toma a decisão grande
                self.evento("camera", TEMPOS["camera"], para=quem)
            falta = round(maior - self.aposta[quem], 4)
            if ac == "check" and falta > 1e-6:
                ac = "call"  # “check” com aposta na frente = pagar (texto escrito à mão)
            if ac == "call" and falta <= 1e-6:
                ac = "check"
            rotulo = ""
            pos_antes = self.aposta[quem]
            if ac == "fold":
                self.fora[quem] = True
                rotulo = "FOLD"
            elif ac == "check":
                rotulo = "CHECK"
            elif ac == "call":
                v = self.por(quem, falta)
                rotulo = f"ALL-IN {self.fmt(self.aposta[quem])}" if self.allin[quem] else f"CALL {self.fmt(v)}"
            elif ac in ("bet", "raise", "allin"):
                alvo = self.aposta[quem] + self.stack[quem] if ac == "allin" else float(a.get("valor") or 0)
                if ac == "bet" and maior > 0 and alvo <= maior:
                    alvo = maior + float(a.get("valor") or 0)  # “bet 3” em cima de aposta = raise de mais 3
                if self.limite == "pl":  # pot-limit: o máximo é aumentar o tamanho do pote (contando o call)
                    teto = maior + self.pot + sum(self.aposta) + max(0.0, falta)
                    if ac == "allin":
                        alvo = min(alvo, teto)
                    elif alvo > teto + 1e-6:
                        raise PokerErro(f"{self.js[quem]['nome']}: no pot-limit o máximo é {_fmt(teto)} (pediu {_fmt(alvo)}).")
                if alvo < maior - 1e-6 and ac != "allin":
                    raise PokerErro(f"{self.js[quem]['nome']}: {ac} {a.get('valor')} é menor que a aposta na mesa ({_fmt(maior)}).")
                v = self.por(quem, alvo - self.aposta[quem])
                if self.aposta[quem] > maior:
                    maior = self.aposta[quem]
                if self.allin[quem]:
                    rotulo = f"ALL-IN {self.fmt(self.aposta[quem])}"
                elif ac == "bet" or (maior == self.aposta[quem] and pos_antes == 0 and (self.rua != "preflop" or self.tipo == "stud") and falta <= 1e-6):
                    rotulo = f"BET {self.fmt(self.aposta[quem])}"
                else:
                    rotulo = f"RAISE {self.fmt(self.aposta[quem])}"
            self.ultima[quem] = rotulo
            dec = self.decisao(quem, falta, pos_antes) if falta > 1e-6 else None
            dur_p = TEMPOS["pensa"]
            if dec and self.estrategia and (self.rua != "preflop" or dec["pagar"] >= self.bb * 8 or ac == "allin" or any(self.allin)):
                dur_p = 3.2   # 🧠 tempo pra ler o painel de estratégia
            self.evento("pensa", dur_p, quem=quem, decisao=dec)
            self.evento("acao", TEMPOS["fold"] if ac == "fold" else TEMPOS["acao"], quem=quem, acao=ac, rotulo=rotulo,
                        valor=round(self.aposta[quem] - pos_antes, 2))
            vez = (quem + 1) % n
            self.rodar_extras(extras, apos_acao=True)
        self.vez = None

    def rodar_extras(self, extras: List[Dict[str, Any]], apos_acao: bool = False) -> None:
        while extras and not apos_acao:
            x = extras.pop(0)
            if x["tipo"] == "zoom":
                alvo = x["alvo"]
                if alvo.lower() not in ("board", "mesa", "pot", "off", "centro"):
                    alvo = self.idx(alvo)
                self.zooms.append({"t0": round(self.t, 3), "alvo": alvo, "escala": x["escala"], "dur": round(0.7 / self.vel, 3)})
                self.evento("pausa", 0.35)
            elif x["tipo"] == "emocao":
                d = (3.2 if x.get("texto") else 2.2) / self.vel
                self.emocoes.append({"t0": round(self.t, 3), "dur": round(d, 3), "quem": self.idx(x["quem"]), "emoji": x["emoji"],
                                     "texto": x.get("texto") or ""})
                self.evento("pausa", 0.5)
            elif x["tipo"] == "fim":   # 💀 a mão acaba aqui, sem showdown e sem vencedor (interrompida)
                self.vez = None
                for i in self.ativos():
                    if self.js[i]["cartas"] and (self.mostrar in ("todas", "pov") or self.js[i]["heroi"]):
                        self.revelado[i] = True
                self.evento("fim", 4.2, texto=x.get("texto") or "A mão nunca terminou.")
                self.encerrada = True
            elif x["tipo"] == "range":
                i = self.idx(x["quem"])
                if x.get("spec"):
                    self.ranges[i] = ler_range(x["spec"])
                cels = self.ranges.get(i)
                if not cels:
                    raise PokerErro(f"range: escreva as mãos (ex.: range: {self.js[i]['nome']} AA-TT, AKs)")
                self.evento("range", 3.6, quem=i, celulas=cels, pct=pct_range(cels), mao=celula_da_mao(self.maos[i]) if self.tipo == "board" and self.ncartas == 2 else "")
            elif x["tipo"] == "correr":
                self.runs, self.corte = x["n"], len(self.board)
                if self.runs > 1:
                    self.evento("nota", TEMPOS["nota"] * 0.8, texto=f"🔁 Vão correr {['', '', 'duas', 'três'][self.runs]} vezes: "
                                                                      f"cada board vale 1/{self.runs} do pote")
            elif x["tipo"] == "acordo":
                self.fazer_acordo(x)
            elif x["tipo"] == "mostrar":
                self.mostrares.append({"t0": round(self.t, 3), "modo": x["modo"]})
                self.evento("pausa", 0.4)
            elif x["tipo"] == "camera":
                self.vista = self.idx(x["quem"])
                self.evento("camera", TEMPOS["camera"], para=self.vista)
            elif x["tipo"] == "nota":
                self.evento("nota", TEMPOS["nota"], texto=x["texto"])

    def fazer_acordo(self, x: Dict[str, Any]) -> None:
        """🤝 os jogadores fazem um acordo e dividem o pote (igual, por % ou pela equidade do momento) — a mão acaba aqui."""
        tinha = self.recolher()
        if tinha:
            self.evento("recolher", TEMPOS["recolher"], de=tinha)
        vivos = self.ativos()
        if len(vivos) < 2:
            raise PokerErro("acordo: precisa de pelo menos 2 jogadores na mão.")
        if x["modo"] == "equidade":
            if any(len(self.js[i]["cartas"]) != self.ncartas or not conhecidas(self.js[i]["cartas"]) for i in vivos):
                raise PokerErro("acordo: equidade precisa das cartas de todos que estão na mão.")
            mortas = [c for i, j in enumerate(self.js) if self.fora[i] for c in j["cartas"]]
            eq = equidade({i: self.js[i]["cartas"] for i in vivos}, list(self.board), mortas, var=self.var)
            pesos = {i: eq[i] for i in vivos}
        elif x["modo"] == "partes":
            pesos = {self.idx(n): v for n, v in x["partes"].items()}
            if set(pesos) - set(vivos):
                raise PokerErro("acordo: só quem está na mão entra na divisão.")
        else:
            pesos = {i: 1.0 for i in vivos}
        tot = sum(pesos.values()) or 1.0
        pot = self.pot
        # ninguém leva mais do que poderia ganhar (o side pot de quem tem menos fica com os outros)
        ganhos = {i: pot * p / tot for i, p in pesos.items() if p > 0}
        for i in vivos:
            if self.js[i]["cartas"]:
                self.revelado[i] = True
        txt = x.get("texto") or ("🤝 Acordo: dividem o pote" if x["modo"] == "dividir" else
                                 "🤝 Acordo pela equidade: " + " · ".join(f"{self.js[i]['nome']} {pesos[i] / tot * 100:.0f}%" for i in pesos)
                                 if x["modo"] == "equidade" else
                                 "🤝 Acordo: " + " · ".join(f"{self.js[i]['nome']} {pesos[i] / tot * 100:.0f}%" for i in pesos))
        self.evento("nota", TEMPOS["nota"], texto=txt[:200])
        for i, v in ganhos.items():
            self.stack[i] += v
        self.ganhos = ganhos
        self.pot = 0.0
        self.evento("vencedor", TEMPOS["vencedor"], quem=sorted(ganhos, key=lambda i: -ganhos[i]), pot=round(pot, 2), acordo=True)
        self.encerrada = True

    def correr_extras(self) -> List[List[str]]:
        """Run it twice/três vezes: vira os boards extras (a 2ª/3ª fileira) e devolve os boards completos."""
        boards = [list(self.board)]
        if self.runs <= 1:
            return boards
        extra = self.m.get("boards_extra") or {}
        falta = 5 - self.corte
        for r in range(2, self.runs + 1):
            cs = list(extra.get(r) or extra.get(str(r)) or [])
            if len(cs) != falta:
                raise PokerErro(f"Run it {self.runs}x: a linha board{r}: precisa de {falta} carta(s) (as que faltavam quando correram).")
            b = {"run": r, "corte": self.corte, "cartas": []}
            self.boards_x.append(b)
            for j, c in enumerate(cs):
                b["cartas"].append(c)
                self.evento("board", TEMPOS["board"] * (1.6 if j == len(cs) - 1 else 1), carta=c, pos=self.corte + j, run=r)
            boards.append(self.board[:self.corte] + cs)
        return boards

    def showdown(self) -> None:
        if self.encerrada:
            return
        tinha = self.recolher()
        if tinha:
            self.evento("recolher", TEMPOS["recolher"], de=tinha)
        vivos = self.ativos()
        self.vez = None
        if len(vivos) == 1:
            g = vivos[0]
            self.ganhos = {g: self.pot}
            self.stack[g] += self.pot
            pot = self.pot
            self.pot = 0.0
            self.evento("vencedor", TEMPOS["vencedor"], quem=[g], pot=round(pot, 2), sem_showdown=True)
            return
        # completa o board se todo mundo foi all-in antes do river
        misterio = [self.js[i]["nome"] for i in vivos if DESCONHECIDA in self.maos[i]] + (["o board"] if DESCONHECIDA in self.board else [])
        if misterio:
            raise PokerErro("Showdown com carta desconhecida (??) de " + ", ".join(misterio) + " — a mão não dá pra decidir: "
                            "termine com fim: \"texto\" (ex.: a mão foi interrompida) ou ponha a carta.")
        if self.tipo == "board" and len(self.board) < 5:
            raise PokerErro("Mão com mais de um jogador até o fim precisa do board completo (flop, turn e river).")
        if self.tipo == "stud" and self.rua != "s7":
            raise PokerErro("Stud: com mais de um jogador até o fim, a mão vai até a 7ª rua (escreva 7a: …).")
        sem_carta = [self.js[i]["nome"] for i in vivos if len(self.maos[i]) != self.ncartas]
        if sem_carta:
            raise PokerErro("Showdown: falta as cartas de " + ", ".join(sem_carta) + " (jogador: Nome stack As Kd).")
        boards = self.correr_extras() if self.tipo == "board" else [[]]
        for i in vivos:
            nomes = [nome_jogo(avaliar_mao(self.maos[i], b, self.var)[1]) for b in boards]
            self.jogos[i] = nomes[0] if len(nomes) == 1 else " · ".join(f"{k + 1}ª {n}" for k, n in enumerate(nomes))
            self.revelado[i] = True
        self.evento("showdown", TEMPOS["showdown"])
        # side pots
        niveis = sorted({self.investido[i] for i in vivos})
        anterior = 0.0
        ganhos: Dict[int, float] = {}
        resto_pot = self.pot
        for nivel in niveis:
            contrib = sum(max(0.0, min(self.investido[i], nivel) - anterior) for i in range(len(self.js)))
            elegiveis = [i for i in vivos if self.investido[i] >= nivel - 1e-9]
            for b in boards:  # cada corrida vale 1/n do pote
                vals = {i: avaliar_mao(self.maos[i], b, self.var)[0] for i in elegiveis}
                top = max(vals.values())
                win = [i for i, v in vals.items() if v == top]
                for i in win:
                    ganhos[i] = ganhos.get(i, 0.0) + contrib / len(win) / len(boards)
            resto_pot -= contrib
            anterior = nivel
        if resto_pot > 1e-6 and ganhos:  # sobras (dead money de quem desistiu) vão pro último ganhador
            k = max(ganhos, key=ganhos.get)
            ganhos[k] += resto_pot
        for i, v in ganhos.items():
            self.stack[i] += v
        self.ganhos = ganhos
        pot = self.pot
        self.pot = 0.0
        self.evento("vencedor", TEMPOS["vencedor"], quem=sorted(ganhos, key=lambda i: -ganhos[i]), pot=round(pot, 2))

    def rodar(self) -> Dict[str, Any]:
        self.evento("intro", TEMPOS["intro"])
        n = len(self.js)
        for volta in range(self.ncartas if self.tipo != "stud" else 0):   # Stud: as cartas vêm rua por rua
            for k in range(n):
                i = (self.btn + 1 + k) % n
                self.evento("carta_jogador", TEMPOS["carta_jogador"], quem=i, k=volta)
        self.blinds()
        extras = [x for x in self.m.get("extras") or [] if x["tipo"] != "rua"]
        # extras ficam ancorados na rua: "apos" = quantas ruas já tinham sido escritas
        por_rua: Dict[int, List[Dict[str, Any]]] = {}
        for x in extras:
            por_rua.setdefault(int(x.get("apos") or 0), []).append(x)
        ruas = self.m.get("ruas") or [{"rua": "s3" if self.tipo == "stud" else "preflop", "acoes": []}]
        if self.tipo == "stud":
            if any(r["rua"] in ("preflop", "flop", "turn", "river") for r in ruas):
                raise PokerErro("Stud não tem flop/turn/river: escreva as ruas como 3a: … 4a: … até 7a: …")
            if ruas[0]["rua"] != "s3":
                ruas = [{"rua": "s3", "acoes": []}] + ruas
        elif ruas[0]["rua"] != "preflop":
            ruas = [{"rua": "preflop", "acoes": []}] + ruas
        self.rodar_extras(por_rua.get(0, []))  # escrito antes do preflop (ex.: câmera inicial, nota de abertura)
        for k, rua in enumerate(ruas):
            if len(self.ativos()) <= 1 or self.encerrada:
                break
            if k > 0 and len(self.podem_agir()) <= 1:
                rua = dict(rua, acoes=[])  # todo mundo all-in: só vira as cartas
            self.jogar_rua(rua, [])
            if (len(self.ativos()) > 1 or k + 1 in por_rua) and not self.encerrada:
                self.rodar_extras(por_rua.get(k + 1, []))  # o que foi escrito depois dessa rua (antes da próxima)
        self.showdown()
        self.evento("final", TEMPOS["final"] + (2.6 if self.mesa.get("dinheiro") else 0))
        return {"jogadores": self.js, "posicoes": [self.pos[i] for i in range(n)], "botao": self.btn, "inicial": self.inicial,
                "eventos": self.ev, "duracao": round(self.t, 3), "unidade": self.unidade, "bb": self.bb,
                "titulo": str(self.mesa.get("titulo") or ""), "estado0": self.ev[0]["depois"],
                "variante": self.var, "variante_nome": VARIANTES[self.var]["nome"], "ncartas": self.ncartas,
                "abertas": VARIANTES[self.var].get("abertas") or [], "tipo_jogo": self.tipo, "limite": self.limite,
                "zooms": self.zooms, "emocoes": self.emocoes, "mostrares": self.mostrares, "mostrar": self.mostrar,
                "estrategia": self.estrategia,
                "estetica": str(self.mesa.get("estetica") or self.mesa.get("estética") or ""),
                "dinheiro": str(self.mesa.get("dinheiro") or "")[:200]}


def simular(entrada: Any, velocidade: float = 1.0, ritmo: str = "", pov: str = "", estrategia: bool = False) -> Dict[str, Any]:
    """A mão (texto/hand history/JSON) → a linha do tempo completa pro renderizador.
    ritmo="shorts": rotina rápida + câmera lenta no all-in/river; pov="auto": a câmera vai pra quem decide."""
    m = ler(entrada)
    if estrategia:
        m = dict(m, mesa=dict(m.get("mesa") or {}, estrategia="1"))
    r = _Mao(m, velocidade, ritmo, pov).rodar()
    r["ritmo"] = "shorts" if str(ritmo or (m.get("mesa") or {}).get("ritmo") or "").lower() in ("shorts", "short", "rapido", "rápido") else "normal"
    r["gancho"] = str((m.get("mesa") or {}).get("gancho") or "")[:120]
    return r


EXEMPLO = """# 🃏 exemplo — troque à vontade (valores em BB; "raise X" = aumenta PARA X)
mesa: blinds=0.5/1 unidade=bb titulo="A5 de ouros: o flush que ninguém viu"
jogador: NewSted 79 Ad 5d heroi
jogador: FlipFlopidy 58.5 Kc Qc
jogador: PIKASQ 97
jogador: prabakaran 116.5
jogador: Dusmulacis 187
jogador: VadimN 88
botao: NewSted
preflop: prabakaran fold; Dusmulacis fold; VadimN fold; NewSted raise 2.5; FlipFlopidy call; PIKASQ fold
nota: O herói abre no botão com A5 de ouros — mão boa pra jogar em posição.
flop: 3d Th 2d | FlipFlopidy bet 4; NewSted raise 12; FlipFlopidy call
camera: FlipFlopidy
turn: Kd | FlipFlopidy check; NewSted bet 20; FlipFlopidy call
camera: NewSted
river: 7c | FlipFlopidy check; NewSted allin; FlipFlopidy call
"""
