"""
🗓 dp_calendario.py — quadros editoriais de CALENDÁRIO e LISTA À MÃO (v84_93)
==============================================================================

Cinco quadros novos do 🗞 Editorial (mesmo motor de dp_editorial.py: desenhados com o PIL quadro a quadro, viram .mov
e entram por cima do vídeo; aparecem na aba 🗞 Editorial do Estúdio e no prompt de edição da IA):

  calendario_mes  📅 a folha do mês cai na mesa e a caneta CIRCULA o dia, faz um X, passa MARCA-TEXTO na semana ou
                     RISCA os dias um a um até o dia marcado — com anotação escrita à mão e uma seta
  calendario_ano  🗓 os 12 meses do ano; circula os meses marcados ou RISCA os meses passando até o mês final
  folhinha        📆 folhinha de mesa ARRANCANDO páginas (dias, meses ou anos passando, acelerando) até a data final,
                     que fica circulada
  placar_datas    🛫 placar de aeroporto (split-flap) virando MÊS e ANO até a data final
  lista_riscar    ✅ lista ESCRITA À MÃO (caderno, post-it ou quadro-negro), item por item, depois RISCADA / MARCADA ✓ /
                     CIRCULADA

Traço "à mão": círculos com 1,1 volta e raio tremido, riscos levemente ondulados, X em dois traços, ✓, seta curva —
tudo desenhado aos poucos (a caneta andando). Letra à mão: Kalam (OFL) e Permanent Marker (Apache 2.0), em
assets/fonts/manuscrita/.
"""
from __future__ import annotations

import calendar
import datetime as _dt
import math
import os
import random
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import dp_editorial as E

_AQUI = os.path.dirname(os.path.abspath(__file__))
_MANUSCRITA = os.path.join(_AQUI, "assets", "fonts", "manuscrita")
_PLACA = os.path.join(_AQUI, "assets", "fonts", "dp", "bebas-neue-Bold.ttf")
AMARELO_MARCA = (255, 224, 70)

MESES = {
    "pt": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"],
    "en": ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"],
    "de": ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember"],
}
SEMANA = {"pt": "DSTQQSS", "en": "SMTWTFS", "es": "DLMMJVS", "fr": "DLMMJVS", "it": "DLMMGVS", "de": "SMDMDFS"}  # começa no domingo
DIAS_SEMANA = {  # segunda … domingo (a folhinha de dias)
    "pt": ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"],
    "en": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
    "it": ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"],
    "de": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
}
_C_IDIOMA = ("idioma", "Idioma do calendário", "escolha:auto|pt|en|es|fr|it|de", "auto",
             "auto = o idioma do vídeo (o da narração/roteiro); ou fixe um")


def idioma_de(it: Dict[str, Any], padrao: str = "pt") -> str:
    """O idioma dos nomes de mês/dia: o escolhido no quadro, ou (auto) o do vídeo — o site põe em it["_idioma_video"]."""
    v = str(it.get("idioma") or "").lower()
    if v in MESES:
        return v
    v = str(it.get("_idioma_video") or "").lower()[:2]
    return v if v in MESES else padrao

def _c_letra():
    import fontes_escrita as FE
    return ("letra", "Letra à mão", "escolha:" + "|".join(FE.escolhas("manuscrita")), "auto", "auto = Kalam · ⚠ = fonte só de uso pessoal")

TIPOS: Dict[str, Dict[str, Any]] = {
    "calendario_mes": {
        "nome": "📅 Calendário do mês (circular/riscar)", "camada": "tela", "dur": 6.0, "fundo": "papel",
        "quando": "uma data importante (o dia em que algo aconteceu), uma semana, ou os dias passando até um dia — "
                  "a caneta circula/risca o calendário de verdade daquele mês",
        "campos": [("mes", "Mês (1–12 ou nome)", "texto", "3", "ex.: março"), ("ano", "Ano", "num", 2026, ""),
                   ("dias", "Dia(s) marcados", "texto", "18", "ex.: 18 · 4, 18 · 10-16 (a semana)"),
                   ("marca", "Como marcar", "escolha:circulo|x|marca_texto|riscar_ate", "circulo",
                    "riscar_ate = risca os dias um a um até o último marcado (que fica circulado)"),
                   ("anotacao", "Anotação à mão (com seta)", "texto", "", "ex.: o dia do assalto"),
                   ("rotulo", "Rótulo em cima (versalete)", "texto", "", ""), _C_IDIOMA, _c_letra(), E._C_CREDITO],
    },
    "calendario_ano": {
        "nome": "🗓 O ano inteiro (meses marcados/passando)", "camada": "tela", "dur": 6.0, "fundo": "papel",
        "quando": "um período de meses dentro de um ano (de março a julho), ou os meses passando até um mês",
        "campos": [("ano", "Ano", "num", 2026, ""), ("meses", "Mês(es) marcados", "texto", "3-7", "ex.: 9 · 3, 9 · 3-7 · mar, jun"),
                   ("marca", "Como marcar", "escolha:circulo|marca_texto|riscar_ate", "circulo",
                    "riscar_ate = risca os meses passando até o último marcado"),
                   ("anotacao", "Anotação à mão", "texto", "", ""), ("rotulo", "Rótulo em cima", "texto", "", ""), _C_IDIOMA, _c_letra(), E._C_CREDITO],
    },
    "folhinha": {
        "nome": "📆 Folhinha arrancando (dias/meses/anos passando)", "camada": "tela", "dur": 5.0, "fundo": "mesa",
        "quando": "o tempo passando entre duas datas (dias, meses ou anos) — as páginas voam e a última fica circulada",
        "campos": [("de", "De", "texto", "01/2019", "dd/mm/aaaa = dias · mm/aaaa = meses · aaaa = anos"),
                   ("ate", "Até", "texto", "03/2020", "mesmo formato do De"),
                   ("rotulo", "Frase no fim (escrita à mão)", "texto", "", "ex.: 14 meses depois"),
                   ("circular", "Circular a última", "escolha:sim|nao", "sim", ""), _C_IDIOMA, _c_letra(), E._C_CREDITO],
    },
    "placar_datas": {
        "nome": "🛫 Placar de virar (mês/ano)", "camada": "tela", "dur": 5.0, "fundo": "escuro",
        "quando": "saltos no tempo (\"dez anos depois\"), datas mudando rápido — estilo painel de aeroporto",
        "campos": [("de", "De", "texto", "01/2015", "mm/aaaa ou aaaa"), ("ate", "Até", "texto", "06/2026", "mesmo formato"),
                   ("rotulo", "Rótulo em cima", "texto", "", "ex.: ONZE ANOS DEPOIS"), _C_IDIOMA, E._C_CREDITO],
    },
    "lista_riscar": {
        "nome": "✅ Lista escrita à mão (riscar/marcar)", "camada": "tela", "dur": 7.0, "fundo": "papel",
        "quando": "uma lista de passos, planos, suspeitos, metas — escrita à mão e depois riscada/marcada",
        "campos": [("titulo", "Título (sublinhado)", "texto", "Plano", ""),
                   ("itens", "Itens (\"x \" no começo = riscar · \"v \" = marcar ✓ · \"! \" = circular)", "linhas",
                    "x primeiro item\nx segundo item\nv terceiro item\n! o que importa", ""),
                   ("estilo", "Papel", "escolha:caderno|postit|quadro", "caderno", "quadro = quadro-negro com giz"),
                   ("rotulo", "Rótulo embaixo (versalete)", "texto", "", ""), _c_letra(), E._C_CREDITO],
    },
}
EXEMPLOS: Dict[str, Dict[str, Any]] = {
    "calendario_mes": {"mes": "3", "ano": 2026, "dias": "18", "marca": "riscar_ate", "anotacao": "o dia do assalto",
                       "rotulo": "Março de 2026", "_t": 5.4},
    "calendario_ano": {"ano": 2026, "meses": "3-7", "marca": "marca_texto", "anotacao": "cinco meses de obra", "_t": 4.8},
    "folhinha": {"de": "01/2019", "ate": "03/2020", "rotulo": "14 meses depois", "_t": 4.6},
    "placar_datas": {"de": "01/2015", "ate": "06/2026", "rotulo": "Onze anos depois", "_t": 4.6},
    "lista_riscar": {"titulo": "Plano", "itens": "x alugar o galpão\nx comprar as ferramentas\nv cavar o túnel\n! entrar no cofre",
                     "estilo": "caderno", "_t": 6.6},
}


# ------------------------------------------------------------------ fontes
@lru_cache(maxsize=64)
def _fm(px: int, negrito: bool = False, letra: Optional[str] = None):
    """A letra à mão: Kalam (padrão) ou a escolhida no quadro (campo "letra" — inclusive as suas fontes)."""
    from PIL import ImageFont
    if letra and letra != "auto":
        import fontes_escrita as FE
        if letra in FE.catalogo():
            return FE.letra(letra, max(6, int(px)), "manuscrita")
    nome = "Kalam-Bold.ttf" if negrito else "Kalam-Regular.ttf"
    return ImageFont.truetype(os.path.join(_MANUSCRITA, nome), max(6, int(px)))



@lru_cache(maxsize=32)
def _fmk(px: int):
    from PIL import ImageFont
    return ImageFont.truetype(os.path.join(_MANUSCRITA, "PermanentMarker-Regular.ttf"), max(6, int(px)))


@lru_cache(maxsize=32)
def _fplaca(px: int):
    from PIL import ImageFont
    return ImageFont.truetype(_PLACA, max(6, int(px)))


# ------------------------------------------------------------------ traço à mão
def _parcial(pts: List[Tuple[float, float]], p: float) -> List[Tuple[float, float]]:
    """O começo do caminho (fração p do comprimento) — a caneta andando."""
    if p <= 0 or len(pts) < 2:
        return []
    if p >= 1:
        return list(pts)
    segs = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
    alvo = sum(segs) * p
    out = [pts[0]]
    for (a, b), s in zip(zip(pts, pts[1:]), segs):
        if alvo <= s:
            f = alvo / s if s else 0
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            return out
        out.append(b)
        alvo -= s
    return out


def _traco(d, pts: List[Tuple[float, float]], p: float, cor, larg: float) -> Optional[Tuple[float, float]]:
    """Desenha o caminho até a fração p (pontas redondas). Devolve onde a caneta está."""
    q = _parcial(pts, p)
    if len(q) < 2:
        return None
    w = max(1, int(round(larg)))
    d.line(q, fill=cor, width=w, joint="curve")
    r = larg / 2
    for x, y in (q[0], q[-1]):
        d.ellipse([x - r, y - r, x + r, y + r], fill=cor)
    return q[-1]


def _pts_circulo(cx, cy, rx, ry, semente: int, voltas: float = 1.13, n: int = 96) -> List[Tuple[float, float]]:
    rng = random.Random(semente)
    a0 = rng.uniform(-2.5, -1.7)
    inc = rng.uniform(-0.12, 0.12)
    fase = rng.uniform(0, 6.28)
    out = []
    for i in range(n + 1):
        f = i / n
        a = a0 + f * 2 * math.pi * voltas
        m = 1 + 0.045 * math.sin(3 * a + fase) + 0.07 * f
        x, y = rx * m * math.cos(a), ry * m * math.sin(a)
        out.append((cx + x * math.cos(inc) - y * math.sin(inc), cy + x * math.sin(inc) + y * math.cos(inc)))
    return out


def _pts_risco(x0, x1, y, semente: int, u: float, n: int = 24) -> List[Tuple[float, float]]:
    rng = random.Random(semente)
    inc = rng.uniform(-0.035, 0.035)
    amp = rng.uniform(1.0, 2.6) * u
    fase = rng.uniform(0, 6.28)
    x0 -= rng.uniform(4, 10) * u
    x1 += rng.uniform(4, 12) * u
    return [(x0 + (x1 - x0) * i / n, y + (x1 - x0) * i / n * inc + amp * math.sin(i / n * 6.3 + fase)) for i in range(n + 1)]


def _pts_x(cx, cy, r, semente: int) -> Tuple[List, List]:
    rng = random.Random(semente)
    j = lambda: rng.uniform(-0.12, 0.12) * r  # noqa: E731
    a = [(cx - r + j(), cy - r + j()), (cx + r + j(), cy + r + j())]
    b = [(cx + r + j(), cy - r + j()), (cx - r + j(), cy + r + j())]
    return a, b


def _pts_barra(cx, cy, r, semente: int) -> List:
    rng = random.Random(semente)
    return [(cx - r * 0.75 + rng.uniform(-2, 2), cy + r * 0.8), (cx + r * 0.75 + rng.uniform(-2, 2), cy - r * 0.8)]


def _pts_check(x, y, s) -> List[Tuple[float, float]]:
    return [(x, y), (x + s * 0.35, y + s * 0.42), (x + s * 1.05, y - s * 0.55)]


def _pts_seta(a: Tuple[float, float], b: Tuple[float, float], curva: float = 0.25, n: int = 30) -> List[Tuple[float, float]]:
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    dx, dy = b[0] - a[0], b[1] - a[1]
    cx, cy = mx - dy * curva, my + dx * curva
    return [((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * cx + t * t * b[0], (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * cy + t * t * b[1])
            for t in (i / n for i in range(n + 1))]


def _ponta_seta(d, pts, p, cor, larg, tam):
    if p < 0.98 or len(pts) < 3:
        return
    (x1, y1), (x2, y2) = pts[-3], pts[-1]
    ang = math.atan2(y2 - y1, x2 - x1)
    for s in (2.6, -2.6):
        d.line([(x2, y2), (x2 + tam * math.cos(ang + s), y2 + tam * math.sin(ang + s))], fill=cor, width=max(1, int(larg)))


class _Pincel:
    """ImageDraw que MISTURA a cor translúcida (o ImageDraw puro, numa imagem RGBA, troca o pixel — um traço com alfa
    200 furava a folha e um marca-texto com alfa 95 tampava os números). Traço opaco vai direto (rápido)."""

    def __init__(self, im):
        from PIL import ImageDraw
        self.im = im
        self.d = ImageDraw.Draw(im, "RGBA")

    def __getattr__(self, nome):
        return getattr(self.d, nome)

    def _translucido(self, fill) -> bool:
        # numa imagem RGB o próprio ImageDraw("RGBA") já mistura
        return self.im.mode == "RGBA" and isinstance(fill, tuple) and len(fill) == 4 and fill[3] < 255

    def _camada(self, x0, y0, x1, y1, desenhar):
        from PIL import Image, ImageDraw
        x0, y0 = max(0, int(math.floor(x0)) - 2), max(0, int(math.floor(y0)) - 2)
        x1, y1 = min(self.im.width, int(math.ceil(x1)) + 2), min(self.im.height, int(math.ceil(y1)) + 2)
        if x1 <= x0 or y1 <= y0:
            return
        lay = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
        desenhar(ImageDraw.Draw(lay, "RGBA"), x0, y0)
        self.im.alpha_composite(lay, dest=(x0, y0))

    def line(self, xy, fill=None, width=1, joint=None):
        if not self._translucido(fill):
            return self.d.line(xy, fill=fill, width=width, joint=joint)
        xy = list(xy)
        pts = [tuple(p) for p in xy] if xy and isinstance(xy[0], (tuple, list)) else list(zip(xy[0::2], xy[1::2]))
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        r = width
        self._camada(min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r,
                     lambda dd, ox, oy: dd.line([(x - ox, y - oy) for x, y in pts], fill=fill, width=width, joint=joint))

    def _caixa(self, metodo, box, **kw):
        fill = kw.get("fill")
        if not self._translucido(fill) and not self._translucido(kw.get("outline")):
            return getattr(self.d, metodo)(box, **kw)
        x0, y0, x1, y1 = box
        self._camada(x0 - 4, y0 - 4, x1 + 4, y1 + 4,
                     lambda dd, ox, oy: getattr(dd, metodo)([x0 - ox, y0 - oy, x1 - ox, y1 - oy], **kw))

    def ellipse(self, box, **kw):
        return self._caixa("ellipse", box, **kw)

    def rectangle(self, box, **kw):
        return self._caixa("rectangle", box, **kw)

    def rounded_rectangle(self, box, **kw):
        return self._caixa("rounded_rectangle", box, **kw)

    def text(self, xy, txt, fill=None, font=None, anchor=None, **kw):
        if not self._translucido(fill) or not txt:
            return self.d.text(xy, txt, fill=fill, font=font, anchor=anchor, **kw)
        x0, y0, x1, y1 = self.d.textbbox(xy, txt, font=font, anchor=anchor)
        self._camada(x0 - 2, y0 - 2, x1 + 2, y1 + 2,
                     lambda dd, ox, oy: dd.text((xy[0] - ox, xy[1] - oy), txt, fill=fill, font=font, anchor=anchor, **kw))

    def realce(self, box, raio: float, cor=(255, 224, 70), forca: float = 1.0) -> None:
        """🖍 marca-texto de verdade: MULTIPLICA a cor (os números ficam pretos por cima do amarelo)."""
        from PIL import Image, ImageChops, ImageDraw
        x0, y0, x1, y1 = [int(round(v)) for v in box]
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(self.im.width, x1), min(self.im.height, y1)
        if x1 - x0 < 2 or y1 - y0 < 2:
            return
        reg = self.im.crop((x0, y0, x1, y1))
        mult = ImageChops.multiply(reg.convert("RGB"), Image.new("RGB", reg.size, cor)).convert("RGBA")
        if reg.mode == "RGBA":
            mult.putalpha(reg.getchannel("A"))
        else:
            mult = mult.convert(reg.mode)
        masc = Image.new("L", reg.size, 0)
        ImageDraw.Draw(masc).rounded_rectangle([0, 0, reg.width - 1, reg.height - 1], radius=int(raio), fill=int(255 * E._cl(forca)))
        self.im.paste(Image.composite(mult, reg, masc), (x0, y0))


def _pincel(im) -> _Pincel:
    return _Pincel(im)


def _escrever(im, x: float, y: float, txt: str, fonte, cor, p: float, ancora: str = "ls") -> float:
    """Texto aparecendo da esquerda pra direita, como se fosse escrito (a ponta da caneta junto). Devolve a largura."""
    from PIL import Image, ImageDraw
    if not txt:
        return 0.0
    w = fonte.getlength(txt)
    if p <= 0:
        return w
    asc, desc = fonte.getmetrics()
    m = int(asc * 0.4) + 6
    lay = Image.new("RGBA", (int(w) + 2 * m, asc + desc + 2 * m), (0, 0, 0, 0))
    if hasattr(fonte, "glifo"):  # uma Letra (fontes_escrita): letra por letra, com a reserva/acento composto
        xx = m
        for ch in txt:
            if not ch.isspace():
                g, gx, gy = fonte.glifo(ch, tuple(cor))
                E._cola(lay, g, xx + gx, m + asc + gy)
            xx += fonte.avanco(ch)
    else:
        ImageDraw.Draw(lay).text((m, m + asc), txt, font=fonte, fill=cor, anchor="ls")
    if p < 1:
        lay = lay.crop((0, 0, max(1, int(m + w * p)), lay.height))
    if ancora == "ms":
        x -= w / 2
    elif ancora == "rs":
        x -= w
    E._cola(im, lay, x - m, y - asc - m)
    return w


# ------------------------------------------------------------------ datas
def _mes(v: Any) -> int:
    s = str(v or "").strip().lower()
    if s.isdigit():
        return min(12, max(1, int(s)))
    for nomes in MESES.values():
        for i, n in enumerate(nomes):
            if s and (n.startswith(s[:3]) or s.startswith(n[:3])):
                return i + 1
    return 1


def _lista_num(txt: Any, maximo: int, conv=None) -> List[int]:
    """"18" · "4, 18" · "10-16" · "mar, jun" → [números] (dentro de 1..maximo)."""
    conv = conv or (lambda s: int(s) if s.strip().isdigit() else None)
    out: List[int] = []
    for parte in re.split(r"[,;/ e]+(?![^-]*-)", str(txt or "")):
        parte = parte.strip()
        if not parte:
            continue
        if "-" in parte or "–" in parte or " a " in parte:
            a, _s, b = re.split(r"\s*(?:-|–| a )\s*", parte, maxsplit=1)[0], None, re.split(r"\s*(?:-|–| a )\s*", parte, maxsplit=1)[-1]
            va, vb = conv(a), conv(b)
            if va and vb:
                out += list(range(min(va, vb), max(va, vb) + 1))
        else:
            v = conv(parte)
            if v:
                out.append(v)
    return sorted({v for v in out if 1 <= v <= maximo})


def _data(txt: Any) -> Tuple[str, _dt.date]:
    """"12/03/2019" → ("dia", data) · "03/2019" ou "mar/2019" → ("mes", 1º do mês) · "2019" → ("ano", 1º/jan)."""
    s = str(txt or "").strip().lower()
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", s)
    if m:
        try:
            return "dia", _dt.date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            pass
    m = re.fullmatch(r"([a-zç]+|\d{1,2})[/.\s-]+(\d{4})", s)
    if m:
        return "mes", _dt.date(int(m[2]), _mes(m[1]), 1)
    m = re.fullmatch(r"(\d{4})", s)
    if m:
        return "ano", _dt.date(int(m[1]), 1, 1)
    return "ano", _dt.date(2000, 1, 1)


def _passos(de: Any, ate: Any, maximo: int) -> Tuple[str, List[_dt.date]]:
    """As datas entre De e Até, na unidade do formato (no máximo `maximo`, sempre com a 1ª e a última)."""
    u1, d1 = _data(de)
    u2, d2 = _data(ate)
    un = u1 if u1 == u2 else ("mes" if "mes" in (u1, u2) else u1)
    if un == "dia":
        n = abs((d2 - d1).days)
        todos = [d1 + _dt.timedelta(days=k if d2 >= d1 else -k) for k in range(n + 1)]
    elif un == "mes":
        a, b = d1.year * 12 + d1.month - 1, d2.year * 12 + d2.month - 1
        passo = 1 if b >= a else -1
        todos = [_dt.date(k // 12, k % 12 + 1, 1) for k in range(a, b + passo, passo)]
    else:
        passo = 1 if d2.year >= d1.year else -1
        todos = [_dt.date(y, 1, 1) for y in range(d1.year, d2.year + passo, passo)]
    if len(todos) > maximo:
        idx = sorted({round(i * (len(todos) - 1) / (maximo - 1)) for i in range(maximo)})
        todos = [todos[i] for i in idx]
    return un, todos


def _indice_no_tempo(t: float, t0: float, t1: float, n: int) -> Tuple[int, float]:
    """Qual passo está na tela em t (acelera e desacelera) e quanto já andou até o próximo (0–1)."""
    if n <= 1 or t <= t0:
        return 0, 0.0
    if t >= t1:
        return n - 1, 0.0
    g = (t - t0) / (t1 - t0)
    g = g * g * (3 - 2 * g)  # suave nas pontas, rápido no meio
    pos = g * (n - 1)
    return int(pos), pos - int(pos)


def _rot(x, y, cx, cy, graus, ncx, ncy) -> Tuple[float, float]:
    """Ponto (x, y) de uma camada girada com PIL rotate(graus, expand=True) — pra seta achar o círculo."""
    a = math.radians(graus)
    dx, dy = x - cx, y - cy
    return ncx + dx * math.cos(a) + dy * math.sin(a), ncy - dx * math.sin(a) + dy * math.cos(a)


def _marcador(it) -> Tuple[int, int, int, int]:
    return E._rgb(E._acento(it)) + (235,)


# ------------------------------------------------------------------ 📅 calendário do mês
def _pagina_mes(it, pw: int, ph: int, u: float, ctx) -> Tuple[Any, Dict[int, Tuple[float, float, float, float]]]:
    """A folha do mês (sem as marcas) + onde fica cada dia {dia: (x0, y0, x1, y1)} na folha."""
    from PIL import ImageDraw

    def fazer():
        mes, ano = _mes(it.get("mes")), int(E._num(it.get("ano"), 2026))
        lang = idioma_de(it)
        folha, m = E._papel_retangulo(pw, ph, (251, 249, 244), 1.0, u, int(6 * u))
        d = _pincel(folha)
        acento = E._rgb(E._acento(it))
        topo = ph * 0.2
        d.rectangle([m, m - 3 * u, m + pw, m - 3 * u + topo], fill=acento)
        for k in range(2):  # argolas
            cx = m + pw * (0.3 + 0.4 * k)
            d.ellipse([cx - 9 * u, m - 3 * u - 14 * u, cx + 9 * u, m - 3 * u + 4 * u], fill=(60, 58, 56), outline=(30, 30, 30))
        nome = MESES[lang][mes - 1].upper()
        f_t = E._f("serif_b", ph * 0.085)
        d.text((m + pw / 2, m - 3 * u + topo * 0.62), nome, font=f_t, fill=(255, 255, 255), anchor="ms")
        E._espacado(d, m + pw / 2 - E._largura(str(ano), E._f("sans", ph * 0.032), 6 * u) / 2, m - 3 * u + topo * 0.9,
                    str(ano), E._f("sans", ph * 0.032), (255, 235, 230), 6 * u)
        x0, x1 = m + pw * 0.05, m + pw * 0.95
        cw = (x1 - x0) / 7
        y_sem = m + topo + ph * 0.09
        f_s = E._f("sans_b", ph * 0.034)
        for i, ch in enumerate(SEMANA[lang]):
            d.text((x0 + cw * (i + 0.5), y_sem), ch, font=f_s, fill=acento if i == 0 else (110, 104, 96), anchor="ms")
        semanas = calendar.Calendar(firstweekday=6).monthdayscalendar(ano, mes)
        gy0 = y_sem + ph * 0.035
        ch_ = (m + ph * 0.97 - gy0) / max(5, len(semanas))
        f_n = E._f("serif", min(ch_ * 0.5, cw * 0.48))
        caixas = {}
        for r, sem in enumerate(semanas):
            y = gy0 + r * ch_
            d.line([x0, y, x1, y], fill=(200, 194, 184), width=max(1, int(u)))
            for c, dia in enumerate(sem):
                if not dia:
                    continue
                cx = x0 + cw * (c + 0.5)
                d.text((cx, y + ch_ * 0.66), str(dia), font=f_n, fill=acento if c == 0 else (40, 38, 36), anchor="ms")
                caixas[dia] = (x0 + cw * c, y, x0 + cw * (c + 1), y + ch_)
        return folha, caixas, m
    return E._cache(ctx, f"calmes:{it.get('mes')}:{it.get('ano')}:{idioma_de(it)}:{it.get('cor')}:{pw}x{ph}", fazer)


def _blocos_semana(dias: List[int], caixas) -> List[Tuple[float, float, float, float]]:
    """Dias seguidos na mesma linha viram um bloco só (a semana inteira = uma cápsula)."""
    blocos: List[List[int]] = []
    for dd in dias:
        if blocos and dd == blocos[-1][-1] + 1 and abs(caixas[dd][1] - caixas[blocos[-1][-1]][1]) < 1:
            blocos[-1].append(dd)
        else:
            blocos.append([dd])
    return [(caixas[b[0]][0], caixas[b[0]][1], caixas[b[-1]][2], caixas[b[-1]][3]) for b in blocos]


def _d_calendario_mes(it, t, W, H, ctx):
    from PIL import ImageDraw
    u, dur = E._u(W, H), it["end"] - it["start"]
    fundo = it.get("fundo") or "papel"
    im = E._fundo(fundo, W, H).copy()
    d0 = _pincel(im)
    claro = fundo != "escuro"
    vert = E._vert(W, H)
    ph = int(H * (0.72 if not vert else 0.42))
    pw = int(ph * 1.02)
    folha, caixas, m = _pagina_mes(it, pw, ph, u, ctx)
    folha = folha.copy()
    d = _pincel(folha)
    marca = it.get("marca") or "circulo"
    cor = _marcador(it)
    dias = [x for x in _lista_num(it.get("dias"), 31) if x in caixas] or [min(caixas)]
    lw = 5.5 * u
    t_m = 0.85  # as marcas começam depois da folha assentar
    fim_marcas = dur * 0.66
    alvo_pt = None
    if marca == "riscar_ate":
        ultimo = dias[-1]
        anteriores = [x for x in sorted(caixas) if x < ultimo and x >= (dias[0] if len(dias) > 1 else 1)]
        janela = max(0.6, fim_marcas - t_m - 0.8)
        passo = janela / max(1, len(anteriores))
        for k, dd in enumerate(anteriores):
            x0, y0, x1, y1 = caixas[dd]
            r = min(x1 - x0, y1 - y0) * 0.36
            E_p = E._cl((t - t_m - k * passo) / max(0.06, passo * 0.9))
            _traco(d, [(p[0], p[1]) for p in _pts_barra((x0 + x1) / 2, (y0 + y1) / 2, r, dd)], E_p, cor[:3] + (200,), lw * 0.8)
        x0, y0, x1, y1 = caixas[ultimo]
        tc = t_m + janela + 0.1
        pts = _pts_circulo((x0 + x1) / 2, (y0 + y1) / 2 + (y1 - y0) * 0.05, (x1 - x0) * 0.58, (y1 - y0) * 0.5, ultimo)
        _traco(d, pts, E._cl((t - tc) / 0.6), cor, lw)
        alvo_pt = ((x0 + x1) / 2, y0 - (y1 - y0) * 0.05)
    elif marca == "marca_texto":
        blocos = _blocos_semana(dias, caixas)
        janela = max(0.5, fim_marcas - t_m)
        for k, (x0, y0, x1, y1) in enumerate(blocos):
            p = E._ease((t - t_m - k * janela / len(blocos)) / max(0.3, janela / len(blocos) * 0.9))
            if p > 0:
                h = (y1 - y0) * 0.62
                yc = (y0 + y1) / 2 + (y1 - y0) * 0.08
                d.realce([x0 + 4 * u, yc - h / 2, x0 + 4 * u + (x1 - x0 - 8 * u) * p, yc + h / 2], 6 * u, AMARELO_MARCA, 0.85)
        x0, y0, x1, y1 = blocos[-1]
        alvo_pt = ((x0 + x1) / 2, y0)
    else:  # circulo / x — um por um (a semana numa cápsula)
        blocos = _blocos_semana(dias, caixas) if marca == "circulo" else [caixas[x] for x in dias]
        janela = max(0.6, fim_marcas - t_m)
        passo = janela / len(blocos)
        for k, (x0, y0, x1, y1) in enumerate(blocos):
            p = E._cl((t - t_m - k * passo) / max(0.35, passo * 0.85))
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 + (y1 - y0) * 0.05
            if marca == "x":
                r = min(x1 - x0, y1 - y0) * 0.38
                a, b = _pts_x(cx, cy, r, k + 7)
                _traco(d, a, E._cl(p * 2), cor, lw)
                _traco(d, b, E._cl(p * 2 - 1), cor, lw)
            else:
                _traco(d, _pts_circulo(cx, cy, (x1 - x0) * 0.58, (y1 - y0) * 0.5, k + 11), p, cor, lw)
        x0, y0, x1, y1 = blocos[-1]
        alvo_pt = ((x0 + x1) / 2, y0 - (y1 - y0) * 0.05)
    # a folha caindo na mesa e assentando
    q = E._ease(t / 0.75)
    graus = -6 * (1 - q) + -1.3 * q
    gir = E._rotacionar(folha, graus)
    cxl, cyl = folha.width / 2, folha.height / 2
    ox = (W * (0.42 if not vert else 0.5)) - gir.width / 2
    oy = (H * (0.53 if not vert else 0.43)) - gir.height / 2 - (1 - q) * H * 0.2
    E._cola(im, gir, ox, oy, E._cl(t / 0.35))
    d0 = _pincel(im)
    if it.get("rotulo"):
        E._espacado(d0, W * 0.06 if not vert else W * 0.08, H * 0.09, it["rotulo"].upper(), E._f("sans", 19 * u),
                    (90, 84, 76) if claro else (170, 175, 182), 5 * u)
    if it.get("anotacao") and alvo_pt:
        ta = fim_marcas
        p_txt = E._cl((t - ta) / max(0.5, min(1.1, 0.045 * len(it["anotacao"]))))
        ax, ay = _rot(alvo_pt[0], alvo_pt[1], cxl, cyl, graus, gir.width / 2, gir.height / 2)
        ax, ay = ox + ax, oy + ay
        f_a = _fm(int((52 if not vert else 44) * u), True, it.get("letra"))
        if not vert:
            tx, ty = ox + gir.width + 30 * u, H * 0.3
        else:
            tx, ty = W * 0.1, oy + gir.height + 90 * u
        largura = _escrever(im, tx, ty, it["anotacao"], f_a, cor[:3] + (255,), p_txt)
        d1 = _pincel(im)
        inicio = (tx + min(largura, 260 * u) * 0.3, ty + 18 * u) if not vert else (tx + 40 * u, ty - 60 * u)
        pts = _pts_seta(inicio, (ax + (14 * u if not vert else 0), ay - 6 * u), 0.28 if not vert else -0.2)
        p_seta = E._cl((t - ta - 0.25) / 0.55)
        _traco(d1, pts, p_seta, cor, 4 * u)
        _ponta_seta(d1, pts, p_seta, cor, 4 * u, 22 * u)
    E._credito(_pincel(im), it, W, H, u, fundo)
    return E._com_alfa(im, E._k_tela(t, dur))


# ------------------------------------------------------------------ 🗓 o ano inteiro
def _pagina_ano(it, pw: int, ph: int, u: float, ctx):
    from PIL import ImageDraw

    def fazer():
        ano = int(E._num(it.get("ano"), 2026))
        lang = idioma_de(it)
        folha, m = E._papel_retangulo(pw, ph, (251, 249, 244), 1.0, u, int(6 * u))
        d = _pincel(folha)
        acento = E._rgb(E._acento(it))
        d.text((m + pw / 2, m + ph * 0.11), str(ano), font=E._f("serif_b", ph * 0.09), fill=(30, 28, 26), anchor="ms")
        cols, rows = (4, 3) if pw >= ph else (3, 4)
        gx0, gy0 = m + pw * 0.04, m + ph * 0.16
        cw, chh = pw * 0.92 / cols, ph * 0.8 / rows
        f_m = E._f("sans_b", min(cw, chh) * 0.11)
        f_d = E._f("sans", min(cw / 7 * 0.5, chh / 8 * 0.62))
        caixas = {}
        for k in range(12):
            c, r = k % cols, k // cols
            x0, y0 = gx0 + c * cw, gy0 + r * chh
            caixas[k + 1] = (x0 + cw * 0.04, y0 + chh * 0.02, x0 + cw * 0.96, y0 + chh * 0.98)
            d.text((x0 + cw * 0.08, y0 + chh * 0.16), MESES[lang][k].upper()[:3], font=f_m, fill=acento, anchor="ls")
            sems = calendar.Calendar(firstweekday=6).monthdayscalendar(ano, k + 1)
            for rr, sem in enumerate(sems):
                for cc, dia in enumerate(sem):
                    if dia:
                        d.text((x0 + cw * (0.09 + cc * 0.125), y0 + chh * (0.3 + rr * 0.11)), str(dia), font=f_d,
                               fill=acento if cc == 0 else (90, 86, 80), anchor="ls")
        return folha, caixas, m
    return E._cache(ctx, f"calano:{it.get('ano')}:{idioma_de(it)}:{it.get('cor')}:{pw}x{ph}", fazer)


def _d_calendario_ano(it, t, W, H, ctx):
    from PIL import ImageDraw
    u, dur = E._u(W, H), it["end"] - it["start"]
    fundo = it.get("fundo") or "papel"
    im = E._fundo(fundo, W, H).copy()
    claro = fundo != "escuro"
    vert = E._vert(W, H)
    pw, ph = (int(W * 0.6), int(H * 0.76)) if not vert else (int(W * 0.86), int(H * 0.6))
    folha, caixas, m = _pagina_ano(it, pw, ph, u, ctx)
    folha = folha.copy()
    d = _pincel(folha)
    meses = _lista_num(it.get("meses"), 12, _mes_ou_none) or [1]
    marca = it.get("marca") or "circulo"
    cor = _marcador(it)
    lw = 6 * u
    t_m, fim = 0.8, dur * 0.66
    if marca == "riscar_ate":
        ultimo = meses[-1]
        antes = [k for k in range(meses[0] if len(meses) > 1 else 1, ultimo)]
        passo = max(0.15, (fim - t_m - 0.8) / max(1, len(antes)))
        for k, mm in enumerate(antes):
            x0, y0, x1, y1 = caixas[mm]
            p = E._cl((t - t_m - k * passo) / max(0.12, passo * 0.9))
            a, b = _pts_x((x0 + x1) / 2, (y0 + y1) / 2, min(x1 - x0, y1 - y0) * 0.36, mm)
            _traco(d, a, E._cl(p * 2), cor[:3] + (200,), lw)
            _traco(d, b, E._cl(p * 2 - 1), cor[:3] + (200,), lw)
        x0, y0, x1, y1 = caixas[ultimo]
        _traco(d, _pts_circulo((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * 0.56, (y1 - y0) * 0.55, ultimo),
               E._cl((t - t_m - len(antes) * passo - 0.1) / 0.6), cor, lw)
    elif marca == "marca_texto":
        janela = max(0.5, fim - t_m)
        for k, mm in enumerate(meses):
            x0, y0, x1, y1 = caixas[mm]
            p = E._ease((t - t_m - k * janela / len(meses)) / max(0.25, janela / len(meses)))
            if p > 0:
                d.realce([x0, y0, x0 + (x1 - x0) * p, y1], 8 * u, AMARELO_MARCA, 0.8)
    else:
        janela = max(0.6, fim - t_m)
        for k, mm in enumerate(meses):
            x0, y0, x1, y1 = caixas[mm]
            p = E._cl((t - t_m - k * janela / len(meses)) / max(0.35, janela / len(meses) * 0.85))
            _traco(d, _pts_circulo((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * 0.56, (y1 - y0) * 0.55, mm + 3), p, cor, lw)
    q = E._ease(t / 0.75)
    gir = E._rotacionar(folha, -4 * (1 - q) - 0.8 * q)
    ox, oy = W * 0.5 - gir.width / 2, H * (0.48 if not vert else 0.46) - gir.height / 2 + (1 - q) * H * 0.15
    E._cola(im, gir, ox, oy, E._cl(t / 0.35))
    d0 = _pincel(im)
    if it.get("rotulo"):
        E._espacado(d0, W * 0.06, H * 0.07, it["rotulo"].upper(), E._f("sans", 19 * u), (90, 84, 76) if claro else (170, 175, 182), 5 * u)
    if it.get("anotacao"):
        f_a = _fm(int(46 * u), True, it.get("letra"))
        p_txt = E._cl((t - fim) / max(0.5, min(1.1, 0.045 * len(it["anotacao"]))))
        y = oy + gir.height + 70 * u if vert else H * 0.955 + 10 * u
        _escrever(im, W * 0.5, min(y, H * 0.97), it["anotacao"], f_a, cor[:3] + (255,), p_txt, ancora="ms")
    E._credito(_pincel(im), it, W, H, u, fundo)
    return E._com_alfa(im, E._k_tela(t, dur))


def _mes_ou_none(s: str) -> Optional[int]:
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s) if 1 <= int(s) <= 12 else None
    v = _mes(s)
    return v if any(n.startswith(s.lower()[:3]) for ns in MESES.values() for n in ns) else None


# ------------------------------------------------------------------ 📆 folhinha
def _txt_passo(un: str, d: _dt.date, lang: str) -> Tuple[str, str, str]:
    """(em cima, número grande, embaixo) de uma página da folhinha."""
    nomes = MESES[lang]
    if un == "dia":
        sem = DIAS_SEMANA.get(lang, DIAS_SEMANA["pt"])
        return nomes[d.month - 1].upper(), str(d.day), f"{sem[d.weekday()]} · {d.year}"
    if un == "mes":
        return str(d.year), nomes[d.month - 1][:3].upper(), nomes[d.month - 1]
    return "", str(d.year), ""


def _pagina_folhinha(it, w: int, h: int, u: float, txt: Tuple[str, str, str], ctx):
    from PIL import Image, ImageDraw

    def fazer():
        pg = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = _pincel(pg)
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(5 * u), fill=(252, 250, 246), outline=(214, 208, 198), width=max(1, int(u)))
        acento = E._rgb(E._acento(it))
        cima, meio, baixo = txt
        if cima:
            d.rectangle([0, 0, w, h * 0.17], fill=acento)
            d.text((w / 2, h * 0.125), cima, font=E._f("sans_b", h * 0.085), fill=(255, 255, 255), anchor="ms")
        tam = h * (0.5 if len(meio) <= 2 else (0.36 if len(meio) <= 3 else 0.3))
        d.text((w / 2, h * 0.7), meio, font=E._f("serif_b", tam), fill=(28, 26, 24), anchor="ms")
        if baixo:
            d.text((w / 2, h * 0.88), baixo, font=E._f("serif_i", h * 0.065), fill=(110, 104, 96), anchor="ms")
        return pg
    return E._cache(ctx, f"folha:{txt}:{w}x{h}:{it.get('cor')}", fazer)


def _d_folhinha(it, t, W, H, ctx):
    from PIL import ImageDraw
    u, dur = E._u(W, H), it["end"] - it["start"]
    fundo = it.get("fundo") or "mesa"
    im = E._fundo(fundo, W, H).copy()
    vert = E._vert(W, H)
    lang = idioma_de(it)
    un, passos = _passos(it.get("de"), it.get("ate"), max(2, int(dur * 7)))
    ph = int(H * (0.58 if not vert else 0.36))
    pw = int(ph * 0.86)
    cx, cy = W * 0.5, H * (0.47 if not vert else 0.44)
    x0, y0 = cx - pw / 2, cy - ph / 2
    t0, t1 = 0.45, max(0.9, dur * 0.66)
    i, frac = _indice_no_tempo(t, t0, t1, len(passos))
    # bloco (as folhas de baixo) + sombra
    sh, msh = E._sombra(pw, ph, int(14 * u), 170, int(6 * u))
    E._cola(im, sh, x0 - msh, y0 - msh + 10 * u)
    d = _pincel(im)
    for k in range(4, 0, -1):
        d.rounded_rectangle([x0 + k * 1.5 * u, y0 + k * 3 * u, x0 + pw + k * 1.5 * u, y0 + ph + k * 3 * u], radius=int(5 * u),
                            fill=(236 - k * 6, 232 - k * 6, 224 - k * 6), outline=(190, 184, 174))
    prox = passos[min(i + 1, len(passos) - 1)] if frac > 0 else passos[i]
    atual = passos[i]
    E._cola(im, _pagina_folhinha(it, pw, ph, u, _txt_passo(un, prox if frac > 0 else atual, lang), ctx), x0, y0)
    if frac > 0:  # a página de cima sendo arrancada: sobe, gira e some
        pg = _pagina_folhinha(it, pw, ph, u, _txt_passo(un, atual, lang), ctx)
        g = E._ease(frac)
        gir = E._rotacionar(pg, 25 * g)
        E._cola(im, gir, x0 + pw / 2 - gir.width / 2 + g * W * 0.28, y0 + ph / 2 - gir.height / 2 - g * H * 0.38, 1 - g * g)
    d = _pincel(im)
    # a presilha de cima
    d.rounded_rectangle([x0 - 8 * u, y0 - 26 * u, x0 + pw + 8 * u, y0 + 8 * u], radius=int(6 * u), fill=(44, 42, 40))
    for k in range(2):
        rx = x0 + pw * (0.28 + 0.44 * k)
        d.ellipse([rx - 8 * u, y0 - 34 * u, rx + 8 * u, y0 - 18 * u], fill=(120, 116, 110))
    cor = _marcador(it)
    if t >= t1 and it.get("circular", "sim") != "nao":
        pts = _pts_circulo(cx, y0 + ph * 0.6, pw * 0.42, ph * 0.26, 5)
        _traco(d, pts, E._cl((t - t1 - 0.1) / 0.6), cor, 7 * u)
    if it.get("rotulo"):
        f_a = _fm(int(64 * u), True, it.get("letra"))
        _escrever(im, cx, y0 + ph + (95 if not vert else 120) * u, it["rotulo"], f_a, (250, 246, 238, 255) if fundo != "papel" else cor[:3] + (255,),
                  E._cl((t - t1 - 0.3) / max(0.5, min(1.1, 0.045 * len(it["rotulo"])))), ancora="ms")
    E._credito(_pincel(im), it, W, H, u, fundo)
    return E._com_alfa(im, E._k_tela(t, dur))


# ------------------------------------------------------------------ 🛫 placar de virar
def _celula(ch: str, w: int, h: int, u: float, ctx):
    from PIL import Image, ImageDraw

    def fazer():
        c = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = _pincel(c)
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(7 * u), fill=(26, 27, 30), outline=(8, 8, 9), width=max(1, int(2 * u)))
        d.rectangle([0, 0, w, h * 0.5], fill=(34, 35, 39))
        d.text((w / 2, h * 0.5), ch, font=_fplaca(int(h * 0.86)), fill=(244, 238, 222), anchor="mm")
        d.line([0, h / 2, w, h / 2], fill=(5, 5, 6), width=max(2, int(3 * u)))
        return c
    return E._cache(ctx, f"cel:{ch}:{w}x{h}", fazer)


def _virar(im, x, y, velho: str, novo: str, frac: float, w: int, h: int, u: float, ctx):
    """Uma célula do placar no meio da virada (a aba de cima cai mostrando o caractere novo)."""
    from PIL import Image
    a, b = _celula(velho, w, h, u, ctx), _celula(novo, w, h, u, ctx)
    meio = h // 2
    if frac <= 0 or velho == novo:
        E._cola(im, b if frac > 0 else a, x, y)
        return
    E._cola(im, b.crop((0, 0, w, meio)), x, y)           # em cima: o novo (atrás da aba)
    E._cola(im, a.crop((0, meio, w, h)), x, y + meio)     # embaixo: o velho (até a aba chegar)
    if frac < 0.5:   # a aba de cima (velha) dobrando pra baixo
        k = max(1, int(meio * math.cos(frac * math.pi)))
        aba = a.crop((0, 0, w, meio)).resize((w, k), Image.BILINEAR)
        E._cola(im, aba, x, y + meio - k)
    else:            # a aba (nova) abrindo embaixo
        k = max(1, int(meio * -math.cos(frac * math.pi)))
        aba = b.crop((0, meio, w, h)).resize((w, k), Image.BILINEAR)
        E._cola(im, aba, x, y + meio)


def _d_placar_datas(it, t, W, H, ctx):
    from PIL import ImageDraw
    u, dur = E._u(W, H), it["end"] - it["start"]
    fundo = it.get("fundo") or "escuro"
    im = E._fundo(fundo, W, H).copy()
    vert = E._vert(W, H)
    lang = idioma_de(it)
    un, passos = _passos(it.get("de"), it.get("ate"), max(2, int(dur * 9)))
    com_mes = un in ("mes", "dia")
    txt = [((MESES[lang][p.month - 1][:3].upper() if com_mes else ""), str(p.year)) for p in passos]
    t0, t1 = 0.4, max(0.9, dur * 0.7)
    i, frac = _indice_no_tempo(t, t0, t1, len(txt))
    ch = int(H * (0.24 if not vert else 0.13))
    empilhar = vert and com_mes  # no vertical: MÊS em cima, ANO embaixo (maior que numa linha só)
    larg = lambda n, cw_, gap_: n * cw_ + (n - 1) * gap_  # noqa: E731
    while True:
        cw = int(ch * 0.66)
        gap = int(cw * 0.1)
        if empilhar:
            total = larg(4, cw, gap)
        else:
            total = sum(larg(n, cw, gap) for n in (([3] if com_mes else []) + [4])) + (cw if com_mes else 0)
        if total <= W * 0.84 or ch < 40:
            break
        ch = int(ch * 0.92)
    altura = ch * 2 + int(ch * 0.25) if empilhar else ch
    y = H * 0.5 - altura / 2
    atual = txt[i]
    prox = txt[min(i + 1, len(txt) - 1)]
    d = _pincel(im)
    d.rounded_rectangle([W / 2 - total / 2 - 26 * u, y - 26 * u, W / 2 + total / 2 + 26 * u, y + altura + 26 * u],
                        radius=int(14 * u), fill=(12, 12, 14, 230))
    pares = list(zip((atual[0], atual[1]) if com_mes else (atual[1],), (prox[0], prox[1]) if com_mes else (prox[1],)))
    x = W / 2 - total / 2
    yl = y
    for gi, (velho, novo) in enumerate(pares):
        n = len(novo)
        velho = velho.rjust(n)[:n]
        if empilhar:
            x, yl = W / 2 - larg(n, cw, gap) / 2, y + gi * (ch + int(ch * 0.25))
        for k in range(n):
            # as células não viram juntas: um pequeno atraso da esquerda pra direita
            f = E._cl(frac * 1.25 - (k + gi * 3) * 0.06) if frac > 0 else 0.0
            _virar(im, x, yl, velho[k], novo[k], f, cw, ch, u, ctx)
            x += cw + gap
        x += cw - gap if gi == 0 and com_mes else 0
    ch = altura
    d = _pincel(im)
    if it.get("rotulo"):
        f = E._f("sans", 24 * u)
        r = it["rotulo"].upper()
        n = int(len(r) * E._cl((t - 0.2) / 0.8))
        E._espacado(d, W / 2 - E._largura(r, f, 7 * u) / 2, y - 70 * u, r[:n], f, (226, 220, 206), 7 * u)
    if t >= t1:  # chegou: a data acende no acento
        q = E._janela(t, t1, 0.4)
        d.rounded_rectangle([W / 2 - total / 2 - 26 * u, y + ch + 40 * u, W / 2 + total / 2 + 26 * u, y + ch + 46 * u],
                            radius=int(3 * u), fill=E._rgb(E._acento(it)) + (int(255 * q),))
    E._credito(d, it, W, H, u, fundo)
    return E._com_alfa(im, E._k_tela(t, dur))


# ------------------------------------------------------------------ ✅ lista à mão
def _itens_lista(it) -> List[Tuple[str, str]]:
    out = []
    for l in str(it.get("itens") or "").split("\n"):
        s = l.strip()
        if not s:
            continue
        m = re.match(r"^([xXvV✓✔!])\s+(.*)$", s)
        if m:
            k = m.group(1).lower()
            out.append(({"x": "riscar", "v": "check", "✓": "check", "✔": "check", "!": "circular"}[k], m.group(2).strip()))
        else:
            out.append(("", s))
    return out[:9]


def _d_lista_riscar(it, t, W, H, ctx):
    from PIL import ImageDraw
    u, dur = E._u(W, H), it["end"] - it["start"]
    estilo = it.get("estilo") or "caderno"
    vert = E._vert(W, H)
    fundo = it.get("fundo") or ("escuro" if estilo == "quadro" else "papel")
    im = E._fundo(fundo, W, H).copy()
    itens = _itens_lista(it)
    n = max(1, len(itens))
    tem_caixa = any(k == "check" for k, _s in itens)
    # a folha
    if estilo == "postit":
        pw = ph = int(H * (0.78 if not vert else 0.46))
        cor_papel, cor_tinta, cor_linha = (255, 236, 120), (30, 34, 70), None
    elif estilo == "quadro":
        pw, ph = (int(W * 0.7), int(H * 0.8)) if not vert else (int(W * 0.9), int(H * 0.6))
        cor_papel, cor_tinta, cor_linha = (34, 52, 44), (238, 238, 230), None
    else:
        pw, ph = (int(W * 0.56), int(H * 0.84)) if not vert else (int(W * 0.88), int(H * 0.62))
        cor_papel, cor_tinta, cor_linha = (252, 252, 248), (28, 44, 110), (170, 196, 230)

    def base():
        folha, m = E._papel_retangulo(pw, ph, cor_papel, 1.0, u, int((4 if estilo != "quadro" else 10) * u))
        dd = _pincel(folha)
        if estilo == "quadro":
            dd.rectangle([m, m - 3 * u, m + pw, m - 3 * u + ph], outline=(120, 86, 52), width=int(14 * u))
            rng = random.Random(3)
            for _ in range(140):  # pó de giz
                x, y = m + rng.random() * pw, m + rng.random() * ph
                dd.ellipse([x, y, x + 2 * u, y + 2 * u], fill=(255, 255, 255, rng.randint(8, 30)))
        if cor_linha:
            for k in range(1, 30):
                yy = m + ph * 0.2 + k * ph * 0.075
                if yy > m + ph * 0.97:
                    break
                dd.line([m, yy, m + pw, yy], fill=cor_linha + (160,), width=max(1, int(1.2 * u)))
            dd.line([m + pw * 0.12, m, m + pw * 0.12, m + ph], fill=(230, 120, 120, 170), width=max(1, int(1.5 * u)))
        if estilo == "postit":
            dd.rectangle([m, m - 3 * u, m + pw, m - 3 * u + ph * 0.09], fill=(250, 222, 96))
        return folha, m
    folha, m = E._cache(ctx, f"lista:{estilo}:{pw}x{ph}", base)
    folha = folha.copy()
    lh = ph * (0.075 if estilo == "caderno" else 0.62 / (n + 1.6))
    if estilo == "caderno":
        lh = ph * 0.075 * max(1, round(min(2, (0.7 / max(n + 1.6, 1)) / 0.075)))
    f_t = _fm(int(lh * 0.95), True, it.get("letra"))
    f_i = _fm(int(lh * 0.66), False, it.get("letra"))
    xi = m + pw * (0.17 if estilo == "caderno" else 0.1) + (lh * 0.6 if tem_caixa else 0)
    yt = m + ph * 0.2 - lh * 0.18 if estilo == "caderno" else m + ph * 0.1 + lh
    # cabe na folha: o item mais comprido diminui a letra (em vez de sair do papel)
    livre = m + pw * 0.95 - xi
    mais_largo = max([f_i.getlength(x) for _k, x in itens] or [1.0])
    if mais_largo > livre:
        f_i = _fm(max(8, int(lh * 0.66 * livre / mais_largo)), False, it.get("letra"))
    if it.get("titulo") and f_t.getlength(it["titulo"]) > livre:
        f_t = _fm(max(10, int(lh * 0.95 * livre / f_t.getlength(it["titulo"]))), True, it.get("letra"))
    tinta = cor_tinta + (255,)
    cor = (_marcador(it)[:3] + (235,)) if estilo != "quadro" else (255, 120, 110, 235)
    # orçamento: escrever tudo em ~55% do tempo, marcar no resto
    t_escr0, t_escr1 = 0.45, max(1.2, dur * 0.58)
    textos = [it.get("titulo") or ""] + [s for _k, s in itens]
    total_ch = sum(len(s) + 4 for s in textos) or 1
    tc = t_escr0
    tempos = []
    for s in textos:
        dt = (t_escr1 - t_escr0) * (len(s) + 4) / total_ch
        tempos.append((tc, dt))
        tc += dt
    # título (sublinhado)
    t0, dt = tempos[0]
    if it.get("titulo"):
        w = _escrever(folha, xi - (lh * 0.6 if tem_caixa else 0), yt, it["titulo"], f_t, tinta, E._cl((t - t0) / (dt * 0.8)))
        d = _pincel(folha)
        _traco(d, _pts_risco(xi - (lh * 0.6 if tem_caixa else 0), xi - (lh * 0.6 if tem_caixa else 0) + w, yt + lh * 0.16, 2, u),
               E._cl((t - t0 - dt * 0.8) / max(0.15, dt * 0.2)), tinta, 3.5 * u)
    posicoes = []
    for k, (tipo, s) in enumerate(itens):
        t0, dt = tempos[k + 1]
        y = yt + (k + 1.25) * lh
        if tem_caixa:
            d = _pincel(folha)
            q = E._cl((t - t0) / 0.2)
            if q > 0:
                bx = xi - lh * 0.62
                caixa = [(bx, y - lh * 0.42), (bx + lh * 0.4, y - lh * 0.44), (bx + lh * 0.42, y - lh * 0.04), (bx + 1, y - lh * 0.02), (bx, y - lh * 0.42)]
                _traco(d, caixa, q, tinta[:3] + (200,), 2.6 * u)
        w = _escrever(folha, xi, y, s, f_i, tinta, E._cl((t - t0) / (dt * 0.92)))
        posicoes.append((tipo, xi, y, w))
    # as marcas, uma de cada vez
    marcas = [p for p in posicoes if p[0]]
    janela = max(0.6, dur * 0.88 - t_escr1 - 0.2)
    passo = janela / max(1, len(marcas))
    d = _pincel(folha)
    for k, (tipo, x, y, w) in enumerate(marcas):
        p = E._cl((t - t_escr1 - 0.2 - k * passo) / max(0.3, passo * 0.8))
        if tipo == "riscar":
            _traco(d, _pts_risco(x, x + w, y - lh * 0.2, k + 21, u), p, cor, 5.5 * u)
        elif tipo == "check":
            s = lh * 0.42
            _traco(d, _pts_check(xi - lh * 0.6, y - lh * 0.26, s), p, cor, 5.5 * u)
        else:
            rx = min(w / 2 + lh * 0.35, m + pw * 0.985 - (x + w / 2))  # não sai do papel
            _traco(d, _pts_circulo(x + w / 2, y - lh * 0.22, rx, lh * 0.5, k + 31), p, cor, 5 * u)
    if it.get("rotulo"):
        q = E._janela(t, dur * 0.85, 0.4)
        f = E._f("sans", 16 * u)
        E._espacado(d, xi, m + ph * 0.95, it["rotulo"].upper(), f, (cor_tinta if estilo != "quadro" else (230, 230, 224)) + (int(230 * q),), 4 * u)
    q = E._ease(t / 0.6)
    gir = E._rotacionar(folha, (2.4 if estilo == "postit" else -1.1) * (0.4 + 0.6 * q))
    E._cola(im, gir, W / 2 - gir.width / 2, H * 0.5 - gir.height / 2 + (1 - q) * H * 0.08, E._cl(t / 0.35))
    E._credito(_pincel(im), it, W, H, u, fundo)
    return E._com_alfa(im, E._k_tela(t, dur))


DESENHOS = {"calendario_mes": _d_calendario_mes, "calendario_ano": _d_calendario_ano, "folhinha": _d_folhinha,
            "placar_datas": _d_placar_datas, "lista_riscar": _d_lista_riscar}


# ------------------------------------------------------------------ sons
def batidas(it: Dict[str, Any], dur: float, S: Dict[str, str]) -> List[Tuple[float, str, float, str]]:
    tipo = it.get("tipo")
    b: List[Tuple[float, str, float, str]] = []
    if tipo in ("calendario_mes", "calendario_ano"):
        b.append((0.1, S["papel"], 0.55, "pico"))
        n = len(_lista_num(it.get("dias") if tipo == "calendario_mes" else it.get("meses"), 31 if tipo == "calendario_mes" else 12,
                           None if tipo == "calendario_mes" else _mes_ou_none)) or 1
        if it.get("marca") == "riscar_ate":
            b.append((0.85, S["risco"], 0.45, "inicio"))
            b.append((dur * 0.66 - 0.4, S["risco"], 0.6, "pico"))
        else:
            b += [(0.85 + k * max(0.6, dur * 0.66 - 0.85) / n, S["risco"], 0.55, "pico") for k in range(min(n, 6))]
        if it.get("anotacao"):
            b.append((dur * 0.66, S["risco"], 0.35, "inicio"))
    elif tipo == "folhinha":
        b.append((0.45, S["passo"], 0.45, "inicio"))
        b.append((max(0.9, dur * 0.66), S["numero_fim"], 0.6, "pico"))
        if it.get("circular", "sim") != "nao":
            b.append((max(0.9, dur * 0.66) + 0.15, S["risco"], 0.5, "pico"))
    elif tipo == "placar_datas":
        b.append((0.4, S["passo"], 0.5, "inicio"))
        b.append((max(0.9, dur * 0.7), S["nome"], 0.6, "pico"))
    elif tipo == "lista_riscar":
        b.append((0.45, S["risco"], 0.4, "inicio"))
        n = sum(1 for k, _s in _itens_lista(it) if k)
        t1 = max(1.2, dur * 0.58) + 0.2
        passo = max(0.6, dur * 0.88 - t1) / max(1, n)
        b += [(t1 + k * passo, S["risco"], 0.6, "pico") for k in range(min(n, 8))]
    return b


def registrar() -> None:
    """Põe os 5 quadros no catálogo do 🗞 Editorial (chamado no fim de dp_editorial.py)."""
    E.TIPOS.update(TIPOS)
    E.EXEMPLOS.update(EXEMPLOS)
    E._DESENHOS.update(DESENHOS)


registrar()  # (idempotente) cobre o caso de alguém importar dp_calendario antes de dp_editorial
