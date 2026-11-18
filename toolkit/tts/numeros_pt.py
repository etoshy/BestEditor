"""
🔢 v84_410 — números por extenso em PORTUGUÊS antes de narrar (o Chatterbox pt lê "1815" errado/arrastado, "XIV"
letra por letra). Só o texto que vai pro motor muda: a legenda continua com os algarismos.

  1815 → mil oitocentos e quinze · 18 de junho → dezoito de junho · 1º → primeiro · 2ª → segunda
  3,5 → três vírgula cinco · 50% → cinquenta por cento · R$ 10 → dez reais · 1.500 → mil e quinhentos
  séculos XIV e XV → séculos catorze e quinze · Luís XIV → Luís catorze · Dom Pedro II → Dom Pedro segundo
  capítulo IV → capítulo quatro

Tags entre colchetes ([pausa 1.5], [emocao 0.7]…) e *ênfase* ficam como estão.
"""
from __future__ import annotations

import re

_UNI = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze", "treze",
        "catorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
_DEZ = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
_CEM = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos", "oitocentos",
        "novecentos"]
_ORD_U = ["", "primeiro", "segundo", "terceiro", "quarto", "quinto", "sexto", "sétimo", "oitavo", "nono"]
_ORD_D = ["", "décimo", "vigésimo", "trigésimo", "quadragésimo", "quinquagésimo", "sexagésimo", "septuagésimo",
          "octogésimo", "nonagésimo"]
_FEM = {"um": "uma", "dois": "duas", "duzentos": "duzentas", "trezentos": "trezentas", "quatrocentos": "quatrocentas",
        "quinhentos": "quinhentas", "seiscentos": "seiscentas", "setecentos": "setecentas", "oitocentos": "oitocentas",
        "novecentos": "novecentas"}


def _ate_999(n: int) -> str:
    if n < 20:
        return _UNI[n]
    if n < 100:
        d, u = divmod(n, 10)
        return _DEZ[d] + (" e " + _UNI[u] if u else "")
    if n == 100:
        return "cem"
    c, r = divmod(n, 100)
    return _CEM[c] + (" e " + _ate_999(r) if r else "")


def extenso(n: int, feminino: bool = False) -> str:
    """Cardinal por extenso (até 999 trilhões)."""
    if n < 0:
        return "menos " + extenso(-n, feminino)
    if n < 1000:
        s = _ate_999(n)
    else:
        grupos = []
        escalas = [("", ""), ("mil", "mil"), ("milhão", "milhões"), ("bilhão", "bilhões"), ("trilhão", "trilhões")]
        k = 0
        m = n
        while m > 0:
            m, g = divmod(m, 1000)
            if g:
                sing, plur = escalas[k]
                if k == 0:
                    grupos.append((g, _ate_999(g)))
                elif k == 1:
                    grupos.append((g * 1000, "mil" if g == 1 else _ate_999(g) + " mil"))
                else:
                    grupos.append((g * 1000 ** k, _ate_999(g) + " " + (sing if g == 1 else plur)))
            k += 1
        grupos.reverse()
        partes = [grupos[0][1]]
        for valor, txt in grupos[1:]:
            # "e" antes do último grupo quando ele é < 100 ou uma centena redonda (mil e quinze, mil e quinhentos)
            resto = valor % 1000 if valor < 1000 else 0
            if valor < 1000 and (resto < 100 or resto % 100 == 0):
                partes.append("e " + txt)
            else:
                partes.append(txt)
        s = " ".join(partes)
    if feminino:
        s = " ".join(_FEM.get(w, w) for w in s.split())
    return s


def ordinal(n: int, feminino: bool = False) -> str:
    if n <= 0 or n >= 100:
        return extenso(n, feminino)
    d, u = divmod(n, 10)
    s = " ".join(x for x in (_ORD_D[d], _ORD_U[u]) if x)
    return re.sub(r"o\b", "a", s) if feminino else s


# ------------------------------------------------------------------ romanos
_ROM = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_RE_ROMANO = re.compile(r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")


def romano(s: str) -> int:
    if not s or not _RE_ROMANO.match(s):
        return 0
    total, ant = 0, 0
    for ch in reversed(s):
        v = _ROM[ch]
        total = total - v if v < ant else total + v
        ant = max(ant, v)
    return total


_CTX_CARDINAL = r"(?:s[ée]culos?|cap[íi]tulos?|volumes?|tomos?|partes?|atos?|livros?|artigos?|fases?|n[ºo°]\.?)"


def _romanos(t: str) -> str:
    # depois de século/capítulo… (e "XIV e XV", "XIV ou XV" na sequência): cardinal
    def ctx(m):
        lista = re.split(r"(\s+(?:e|a|ou|-|–)\s+|,\s*)", m.group(2))
        out = []
        for p in lista:
            v = romano(p.strip())
            out.append(extenso(v) if v else p)
        return m.group(1) + "".join(out)
    t = re.sub(r"\b(" + _CTX_CARDINAL + r"\s+)([IVXLCDM]{1,7}(?:(?:\s+(?:e|a|ou|-|–)\s+|,\s*)[IVXLCDM]{1,7})*)\b",
               ctx, t, flags=re.I)

    # depois de nome próprio (reis, papas: Luís XIV, Pedro II, João Paulo II): ordinal até 10, depois cardinal
    def nome(m):
        v = romano(m.group(2))
        if not v:
            return m.group(0)
        return m.group(1) + (ordinal(v) if v <= 10 else extenso(v))
    return re.sub(r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõçà]{2,}\s+)([IVXLC]{1,6})\b(?![\w'’])", nome, t)


# ------------------------------------------------------------------ algarismos
_MASC_EM_A = {"dia", "dias", "mapa", "mapas", "problema", "problemas", "sistema", "sistemas", "programa", "programas",
              "planeta", "planetas", "tema", "temas", "idioma", "idiomas", "clima", "climas", "cinema", "cinemas", "poema",
              "poemas", "drama", "dramas", "telefonema", "esquema", "esquemas", "diploma", "diplomas", "atleta", "atletas",
              "cometa", "cometas", "papa", "papas", "guarda", "guardas", "dilema", "dilemas", "lema", "trauma", "traumas"}
_FEM_OUTRAS = {"vez", "vezes", "mulher", "mulheres", "cidade", "cidades", "noite", "noites", "parte", "partes", "tarde",
               "tardes", "mãe", "mães", "nação", "nações", "edição", "edições", "geração", "gerações", "região", "regiões",
               "lição", "lições", "razão", "razões", "versão", "versões", "imagem", "imagens", "viagem", "viagens", "árvore",
               "árvores", "fonte", "fontes", "morte", "mortes", "rede", "redes", "lei", "leis", "libra", "libras", "tonelada",
               "toneladas"}


def _feminino_antes(palavra: str) -> bool:
    w = (palavra or "").lower().strip(".,;:!?)")
    if w in _MASC_EM_A:
        return False
    return w in _FEM_OUTRAS or w.endswith(("a", "as", "ção", "ções", "dade", "dades"))


def _num(s: str) -> int:
    return int(s.replace(".", ""))


def _decimal(inteiro: str, dec: str, fem: bool = False) -> str:
    return extenso(_num(inteiro), fem) + " vírgula " + (" ".join(_UNI[int(c)] for c in dec) if dec.startswith("0") or len(dec) > 2
                                                         else extenso(int(dec)))


def _algarismos(t: str) -> str:
    t = re.sub(r"R\$\s*(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{2}))?",
               lambda m: extenso(_num(m.group(1))) + (" real" if _num(m.group(1)) == 1 else " reais")
               + (" e " + extenso(int(m.group(2))) + (" centavo" if int(m.group(2)) == 1 else " centavos")
                  if m.group(2) and int(m.group(2)) else ""), t)
    t = re.sub(r"(\d+)(?:,(\d+))?\s?%", lambda m: (_decimal(m.group(1), m.group(2)) if m.group(2) else extenso(int(m.group(1))))
               + " por cento", t)
    t = re.sub(r"\b(\d{1,3})\s?[ºo°](?=\s|$|[,.;:!?)])", lambda m: ordinal(int(m.group(1))), t)
    t = re.sub(r"\b(\d{1,3})\s?ª(?=\s|$|[,.;:!?)])", lambda m: ordinal(int(m.group(1)), True), t)
    t = re.sub(r"\b(\d{1,2})h(\d{2})\b", lambda m: extenso(int(m.group(1)), True) + " e " + extenso(int(m.group(2))), t)
    t = re.sub(r"\b(\d{1,2})h\b", lambda m: extenso(int(m.group(1)), True) + (" hora" if int(m.group(1)) == 1 else " horas"), t)
    t = re.sub(r"\b(\d{1,3}(?:\.\d{3})+|\d+),(\d+)\b", lambda m: _decimal(m.group(1), m.group(2)), t)
    def card(m):
        g = m.group(1)
        if len(g.replace(".", "")) > 15:
            return m.group(0)
        prox = m.group(2) or ""
        return extenso(_num(g), _feminino_antes(prox.split()[0] if prox.strip() else "")) + prox
    t = re.sub(r"\b(\d{1,3}(?:\.\d{3})+|\d+)\b(\s+[^\W\d_]+)?", card, t)
    return t


def por_extenso(texto: str) -> str:
    """O texto com números, datas e romanos por extenso — sem mexer nas [tags] nem nos *destaques*."""
    if not texto or not re.search(r"\d|\b[IVXLCDM]{1,7}\b", texto):
        return texto
    partes = re.split(r"(\[[^\[\]]{0,60}\])", texto)
    for k in range(0, len(partes), 2):
        partes[k] = _algarismos(_romanos(partes[k]))
    return "".join(partes)
