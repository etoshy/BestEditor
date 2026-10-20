"""🔒 Marcas do roteiro que a IA não pode perder (v84_127).

Quando a IA reescreve o roteiro (🎙 adaptar pro TTS, 🪄 revisão), às vezes ela some com as marcas do site:
[I3] / [M2 0:12-0:25 áudio] (mídia), [[INSCREVA]] / [[VENDA: …]] (chamadas) e [CENA 4].
`restaurar(original, novo)` acha onde cada marca que sumiu estava no texto antigo (pelas palavras em volta) e põe
de volta no mesmo ponto do texto novo. Marca que a IA manteve fica onde ela pôs.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any, Dict, List, Tuple

_MIDIA = r"\[\s*[MIT]\d+(?:\s+[\d:.]+\s*[-–]\s*[\d:.]+)?(?:\s+(?:áudio|audio|som))?\s*\]"
_CENA = r"\[\s*(?:cena|scene|escena)\b[^\]\n]{0,160}\]"
_CHAMADA = r"\[\[[^\]]*\]\]"
MARCA = re.compile(f"{_CHAMADA}|{_MIDIA}|{_CENA}", re.IGNORECASE)
_PALAVRA = re.compile(r"[^\W_]+", re.UNICODE)


def _norm(p: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", p.lower()) if unicodedata.category(c) != "Mn")


def _chave(marca: str) -> str:
    """[I3] e [ i3 ] são a mesma; [[VENDA: compre]] conta como [[VENDA]]; [CENA 4 …] como [CENA 4]."""
    m = marca.strip()
    if m.startswith("[["):
        return "[[" + re.split(r"[:\]]", m[2:], maxsplit=1)[0].strip().upper() + "]]"
    c = re.match(r"\[\s*(?:cena|scene|escena)\s*(\d+)", m, re.I)
    if c:
        return f"[CENA {c.group(1)}]"
    i = re.match(r"\[\s*([MIT]\d+)", m, re.I)
    return f"[{i.group(1).upper()}]" if i else m.upper()


def _palavras(texto: str) -> Tuple[List[str], List[int]]:
    """Palavras (sem as marcas) e a posição (caractere) de cada uma no texto."""
    sem = MARCA.sub(lambda m: " " * len(m.group(0)), texto)
    toks, pos = [], []
    for m in _PALAVRA.finditer(sem):
        toks.append(_norm(m.group(0)))
        pos.append(m.start())
    return toks, pos


def marcas(texto: str) -> List[Dict[str, Any]]:
    """[{marca, chave, k (quantas palavras vêm antes), sozinha (numa linha só dela)}]"""
    out = []
    _toks, pos = _palavras(texto)
    for m in MARCA.finditer(texto or ""):
        k = sum(1 for p in pos if p < m.start())
        ini = texto.rfind("\n", 0, m.start()) + 1
        fim = texto.find("\n", m.end())
        linha = texto[ini:fim if fim >= 0 else len(texto)]
        out.append({"marca": m.group(0), "chave": _chave(m.group(0)), "k": k,
                    "sozinha": linha.strip() == m.group(0).strip()})
    return out


def _mapear(k: int, blocos, n_a: int = 0, n_b: int = 0) -> int:
    """Índice de palavra do texto antigo → índice no novo (pelos blocos iguais do difflib)."""
    if n_a and k >= n_a:
        return n_b  # marca no fim do texto
    for a, b, n in blocos:
        if a <= k < a + n:
            return b + (k - a)
        if a > k:
            return b
    return blocos[-1][1] + blocos[-1][2] if blocos else 0


def restaurar(original: str, novo: str, chamadas: bool = True) -> Tuple[str, List[str]]:
    """→ (texto novo com as marcas que sumiram de volta, [marcas recolocadas]).
    chamadas=False: não mexe nas [[INSCREVA]]/[[VENDA]] (quem chama já cuida delas)."""
    antes = [m for m in marcas(original) if chamadas or not m["chave"].startswith("[[")]
    if not antes or not str(novo or "").strip():
        return novo, []
    depois = marcas(novo)
    falta: Dict[str, int] = {}
    for m in antes:
        falta[m["chave"]] = falta.get(m["chave"], 0) + 1
    for m in depois:
        if m["chave"] in falta:
            falta[m["chave"]] -= 1
    if not any(v > 0 for v in falta.values()):
        return novo, []
    ta, _pa = _palavras(original)
    tb, pb = _palavras(novo)
    blocos = [b for b in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_matching_blocks() if b[2]]
    iguais = sum(n for _a, _b, n in blocos)

    def onde(k: int) -> int:
        if iguais < 0.3 * max(1, min(len(ta), len(tb))):  # texto quase todo outro (ex.: traduzido): pela proporção
            return min(len(tb), round(k * len(tb) / max(1, len(ta))))
        return _mapear(k, blocos, len(ta), len(tb))

    # cada marca que ficou no texto novo "paga" a marca antiga (da mesma chave) mais perto; as que sobram voltam
    inserir: List[Tuple[int, int, Dict[str, Any]]] = []
    for chave, n_falta in falta.items():
        if n_falta <= 0:
            continue
        velhas = [(onde(m["k"]), i, m) for i, m in enumerate(antes) if m["chave"] == chave]
        livres = list(velhas)
        for x in sorted(m["k"] for m in depois if m["chave"] == chave):
            if not livres:
                break
            perto = min(livres, key=lambda v: abs(v[0] - x))
            livres.remove(perto)
        inserir.extend(livres[:n_falta])
    texto = novo
    for kb, _i, m in sorted(inserir, key=lambda x: (-x[0], -x[1])):  # de trás pra frente: as posições não mudam
        pos = pb[kb] if kb < len(pb) else len(texto)
        if m["sozinha"] or m["chave"].startswith("[["):
            # vai pro começo da frase (ou da linha) mais próxima, numa linha só dela
            ini = max(texto.rfind("\n", 0, pos) + 1, *(x.end() for x in re.finditer(r"[.!?…]\s+", texto[:pos])), 0) \
                if pos < len(texto) else pos
            if pos - ini > 80:
                ini = pos
            texto = texto[:ini].rstrip(" \t") + "\n\n" + m["marca"] + "\n\n" + texto[ini:].lstrip(" \t")
        else:
            texto = texto[:pos] + m["marca"] + " " + texto[pos:]
    texto = re.sub(r"[ \t]+\n", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    return texto, [m["marca"] for _k, _i, m in inserir]


# ------------------------------------------------------------------ 🎭 v84_219: tags de quem fala ([narrador|…], [mira|curiosa])
def rx_vozes(slugs) -> "re.Pattern[str]":
    nomes = sorted({str(s).strip().lower() for s in slugs or [] if str(s).strip()}, key=len, reverse=True)
    if not nomes:
        return re.compile(r"(?!x)x")
    return re.compile(r"\[\s*(?:" + "|".join(re.escape(n) for n in nomes) + r")\s*(?:\|[^\[\]\n]*)?\]", re.IGNORECASE)


def restaurar_vozes(original: str, novo: str, slugs) -> Tuple[str, int]:
    """A IA (adaptar pro TTS, revisão…) tirou as tags de quem fala? Recoloca cada uma antes da mesma palavra do texto
    novo (alinhando as palavras com o texto antigo). Se ela manteve quase todas, não mexe. → (texto, quantas recolocou)."""
    rx = rx_vozes(slugs)
    velhas = list(rx.finditer(original or ""))
    if not velhas or not str(novo or "").strip():
        return novo, 0
    if len(rx.findall(novo)) >= 0.9 * len(velhas):
        return novo, 0
    novo = rx.sub("", novo)
    novo = re.sub(r"^[ \t]+", "", novo, flags=re.M)

    def toks(texto: str):
        sem = rx.sub(lambda m: " " * len(m.group(0)), texto)
        sem = MARCA.sub(lambda m: " " * len(m.group(0)), sem)
        out, pos = [], []
        for m in _PALAVRA.finditer(sem):
            out.append(_norm(m.group(0)))
            pos.append(m.start())
        return out, pos

    ta, pa = toks(original)
    tb, pb = toks(novo)
    blocos = [b for b in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_matching_blocks() if b[2]]
    inserir = []
    for m in velhas:
        k = sum(1 for p in pa if p < m.start())
        kb = _mapear(k, blocos, len(ta), len(tb))
        inserir.append((kb, m.group(0)))
    texto = novo
    usados = set()
    for kb, tag in sorted(inserir, key=lambda x: -x[0]):
        if kb in usados:
            continue  # duas tags no mesmo ponto: fica a última (a que vale)
        usados.add(kb)
        pos = pb[kb] if kb < len(pb) else len(texto)
        # se a palavra vem logo depois de uma marca de mídia no começo da linha, a tag vai antes da marca
        ini = texto.rfind("\n", 0, pos) + 1
        if MARCA.fullmatch(texto[ini:pos].strip() or "-") and texto[ini:pos].strip():
            pos = ini
        texto = texto[:pos] + tag + " " + texto[pos:]
    return re.sub(r"[ \t]{2,}", " ", texto).strip(), len(usados)
