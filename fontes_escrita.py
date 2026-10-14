"""
fontes_escrita.py — 🔤 as fontes de MÁQUINA DE ESCREVER e de LETRA À MÃO (v84_94)
==================================================================================

O site procura as fontes nestas pastas (é só soltar um .ttf/.otf e reiniciar):

  assets/fonts/maquina/              livres (vão pro GitHub): Special Elite, Courier Prime, 1942 report, Mom's Typewriter
  assets/fonts/manuscrita/           livres: Kalam, Permanent Marker, Shareit
  assets/fonts/pessoais/maquina/     ⚠ uso pessoal (ficam só no seu PC — .gitignore): Elegant Typewriter, JMH…
  assets/fonts/pessoais/manuscrita/  ⚠ uso pessoal: Brittany Signature, Astoria, Stay With Me…

Muitas fontes decorativas não têm acento (ã, ç, é) ou números. Em vez de sair um buraco/quadradinho:
  • letra acentuada que falta → a letra base da PRÓPRIA fonte + o acento desenhado por cima (do til/agudo da fonte,
    ou de uma fonte reserva do mesmo estilo);
  • número/pontuação que falta → a fonte reserva (Courier Prime na máquina, Kalam na letra à mão).

API:
  catalogo()              {id: {id, nome, tipo, licenca, arquivo}}
  escolhas(tipo)          ["auto", ids…] (pra lista de escolha do quadro)
  resolver(id, tipo)      id válido (ou o padrão do tipo)
  Letra(id, px)           .avanco(ch) · .glifo(ch, cor) → (RGBA, dx, dy) · .largura(txt) · .quebrar(txt, largura)
"""
from __future__ import annotations

import os
import re
import unicodedata
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

_AQUI = os.path.dirname(os.path.abspath(__file__))
_F = os.path.join(_AQUI, "assets", "fonts")
PASTAS = [
    (os.path.join(_F, "maquina"), "maquina", "livre"),
    (os.path.join(_F, "manuscrita"), "manuscrita", "livre"),
    (os.path.join(_F, "pessoais", "maquina"), "maquina", "pessoal"),
    (os.path.join(_F, "pessoais", "manuscrita"), "manuscrita", "pessoal"),
]
PADRAO = {"maquina": "special-elite", "manuscrita": "kalam"}
RESERVA = {"maquina": "courier-prime", "manuscrita": "kalam"}
# nomes bonitos / ids estáveis pros arquivos conhecidos (o resto usa o nome do arquivo)
NOMES = {
    "SpecialElite-Regular": ("special-elite", "Special Elite (máquina clássica)"),
    "CourierPrime-Regular": ("courier-prime", "Courier Prime (datilografia limpa)"),
    "CourierPrime-Bold": ("courier-prime-negrito", "Courier Prime negrito"),
    "1942-report": ("1942-report", "1942 report (fita gasta)"),
    "MomsTypewriter": ("moms-typewriter", "Mom's Typewriter (máquina velha)"),
    "Kalam-Regular": ("kalam", "Kalam (caneta)"),
    "Kalam-Bold": ("kalam-negrito", "Kalam negrito"),
    "PermanentMarker-Regular": ("marcador", "Permanent Marker (pincel atômico)"),
    "Shareit": ("shareit", "Shareit (pincel fino)"),
    "ELEGANT TYPEWRITER Regular": ("elegant-typewriter", "Elegant Typewriter"),
    "ELEGANT TYPEWRITER Bold": ("elegant-typewriter-negrito", "Elegant Typewriter negrito"),
    "ELEGANT TYPEWRITER Italic": ("elegant-typewriter-italico", "Elegant Typewriter itálico"),
    "ELEGANT TYPEWRITER Light": ("elegant-typewriter-fino", "Elegant Typewriter fino"),
    "JMH Typewriter": ("jmh-typewriter", "JMH Typewriter"),
    "JMH Typewriter-Bold": ("jmh-typewriter-negrito", "JMH Typewriter negrito"),
    "JMH Typewriter-Black": ("jmh-typewriter-preto", "JMH Typewriter black"),
    "JMH Typewriter-Thin": ("jmh-typewriter-fino", "JMH Typewriter fino"),
    "OldNewspaperTypes": ("old-newspaper", "Old Newspaper Types (jornal antigo)"),
    "Punk Typewriter": ("punk-typewriter", "Punk Typewriter (borrada)"),
    "Why do we blink so frequently.": ("why-blink", "Why do we blink (carimbada)"),
    "Why do we blink so frequently, Dark": ("why-blink-escura", "Why do we blink (escura)"),
    "Why do we blink so frequently, Jungle": ("why-blink-jungle", "Why do we blink (jungle)"),
    "BrittanySignature": ("brittany", "Brittany Signature (assinatura)"),
    "Astoria": ("astoria", "Astoria (assinatura)"),
    "Always in the Star": ("always-star", "Always in the Star (caligrafia)"),
    "Stay With Me": ("stay-with-me", "Stay With Me (caneta)"),
    "Smart Water": ("smart-water", "Smart Water (caneta)"),
    "Smile Moon": ("smile-moon", "Smile Moon (marcador)"),
    "Please write me a song": ("please-write", "Please write me a song (lápis)"),
    "Chillin on Sunday": ("chillin-sunday", "Chillin on Sunday (marcador)"),
    "Dudu_Calligraphy": ("dudu", "Dudu Calligraphy (letra redonda)"),
    "212 Baby Girl": ("212-baby-girl", "212 Baby Girl (letra de forma)"),
    "B-de-bonita": ("b-de-bonita", "B de bonita (cursiva)"),
    "b-de-bonita-shadow": ("b-de-bonita-sombra", "B de bonita com sombra"),
    "Biro_Script_reduced": ("biro", "Biro Script (esferográfica)"),
    "Catlove": ("catlove", "Catlove (cursiva)"),
    "CuteFont-Regular": ("cute", "Cute Font"),
    "Wintery Christmas": ("wintery", "Wintery Christmas"),
}
_ACENTO_ESPACO = {"́": "´", "̀": "`", "̃": "~", "̂": "^", "̈": "¨", "̧": "¸", "̊": "°"}


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


@lru_cache(maxsize=1)
def _catalogo_cache(_chave: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for pasta, tipo, lic in PASTAS:
        if not os.path.isdir(pasta):
            continue
        arquivos = sorted(os.listdir(pasta))
        stems_ttf = {os.path.splitext(a)[0] for a in arquivos if a.lower().endswith(".ttf")}
        for a in arquivos:
            stem, ext = os.path.splitext(a)
            if ext.lower() not in (".ttf", ".otf") or (ext.lower() == ".otf" and stem in stems_ttf):
                continue
            fid, nome = NOMES.get(stem, (_slug(stem), stem.replace("_", " ")))
            if fid in out:
                continue
            out[fid] = {"id": fid, "nome": nome + (" ⚠ uso pessoal" if lic == "pessoal" else ""), "tipo": tipo, "licenca": lic,
                        "arquivo": os.path.join(pasta, a)}
    return out


def _assinatura_pastas() -> str:
    partes = []
    for pasta, _t, _l in PASTAS:
        try:
            partes.append(f"{pasta}:{len(os.listdir(pasta))}:{int(os.path.getmtime(pasta))}")
        except OSError:
            partes.append(f"{pasta}:-")
    return "|".join(partes)


def catalogo() -> Dict[str, Dict[str, Any]]:
    """Todas as fontes achadas (relê as pastas se mudaram)."""
    return _catalogo_cache(_assinatura_pastas())


def escolhas(tipo: Optional[str] = None) -> List[str]:
    """Ids pra lista de escolha (o 1º é "auto"). As livres vêm antes das pessoais."""
    c = catalogo()
    ids = sorted((f for f in c.values() if tipo in (None, f["tipo"])), key=lambda f: (f["tipo"], f["licenca"] != "livre", f["nome"].lower()))
    return ["auto"] + [f["id"] for f in ids]


def resolver(fid: Optional[str], tipo: str) -> str:
    c = catalogo()
    if fid and fid in c:
        return fid
    for cand in (PADRAO.get(tipo), RESERVA.get(tipo), "kalam", "courier-prime"):
        if cand in c:
            return cand
    return next(iter(c), "")


def arquivo(fid: str) -> Optional[str]:
    f = catalogo().get(fid)
    return f["arquivo"] if f else None


# ------------------------------------------------------------------ glifos
@lru_cache(maxsize=64)
def _fonte(caminho: str, px: int):
    from PIL import ImageFont
    return ImageFont.truetype(caminho, max(6, int(px)))


@lru_cache(maxsize=8192)
def _render_teste(caminho: str, ch: str) -> Optional[bytes]:
    """O desenho do caractere em 48 px (None = sem tinta = a fonte não tem)."""
    from PIL import Image, ImageDraw
    f = _fonte(caminho, 48)
    im = Image.new("L", (120, 120), 0)
    ImageDraw.Draw(im).text((30, 90), ch, font=f, fill=255, anchor="ls")
    if im.getbbox() is None:
        return None
    return im.tobytes()


@lru_cache(maxsize=256)
def _cmap(caminho: str) -> frozenset:
    try:
        from fontTools.ttLib import TTFont
        return frozenset((TTFont(caminho, fontNumber=0, lazy=True).getBestCmap() or {}).keys())
    except Exception:  # noqa: BLE001 — sem fontTools: confia no desenho
        return frozenset()


@lru_cache(maxsize=8192)
def tem(caminho: str, ch: str) -> bool:
    """A fonte desenha este caractere de verdade? Não tem quando: não está no mapa da fonte, sai em branco, sai o
    "quadradinho" (.notdef), ou é acentuada e a fonte não tem o acento (aí as acentuadas costumam sair com caixinha)."""
    if ch.isspace():
        return True
    cm = _cmap(caminho)
    if cm and ord(ch) not in cm:
        return False
    r = _render_teste(caminho, ch)
    if r is None or r == _render_teste(caminho, "\uE000"):
        return False
    nfd = unicodedata.normalize("NFD", ch)
    if len(nfd) > 1:
        rb = _render_teste(caminho, nfd[0])
        if rb is not None and rb == r:
            return False
        sinal = _ACENTO_ESPACO.get(nfd[1])
        if sinal and not tem(caminho, sinal):
            return False
    return True


def _tinta(fonte, txt: str):
    """O desenho de verdade (recortado na tinta) de `txt` como máscara L — getbbox mente em fonte mal feita."""
    from PIL import Image, ImageDraw
    px = int(getattr(fonte, "size", 40))
    im = Image.new("L", (px * 4, px * 4), 0)
    ImageDraw.Draw(im).text((px, px * 3), txt, font=fonte, fill=255, anchor="ls")
    bb = im.getbbox()
    return im.crop(bb) if bb else None


class Letra:
    """Uma fonte num tamanho, com a reserva pros caracteres que ela não tem."""

    def __init__(self, fid: str, px: int, tipo: str = "manuscrita", caminho: Optional[str] = None):
        """`caminho` = usar um arquivo de fonte qualquer (ex.: a fonte "de computador" do quadro)."""
        self.id = resolver(fid, tipo) if not caminho else (fid or os.path.basename(caminho))
        self.tipo = catalogo().get(self.id, {}).get("tipo", tipo)
        self.px = int(px)
        self.caminho = caminho or arquivo(self.id) or ""
        self.reserva = arquivo(resolver(RESERVA.get(self.tipo, "kalam"), self.tipo)) or self.caminho
        self._av: Dict[str, float] = {}
        self.f = _fonte(self.caminho, self.px)
        self.fr = _fonte(self.reserva, self.px)
        asc, desc = self.f.getmetrics()
        self.asc, self.desc = asc, desc

    def _plano(self, ch: str) -> Tuple[str, Any, Optional[Tuple[str, Any]]]:
        """(texto, fonte, acento) — como desenhar `ch`."""
        if not self.caminho or tem(self.caminho, ch):
            return ch, self.f, None
        nfd = unicodedata.normalize("NFD", ch)
        if len(nfd) > 1 and tem(self.caminho, nfd[0]):
            sinal = _ACENTO_ESPACO.get(nfd[1])
            if sinal:
                return nfd[0], self.f, (sinal, self.f if tem(self.caminho, sinal) else self.fr)
        return ch, self.fr, None

    def avanco(self, ch: str) -> float:
        v = self._av.get(ch)
        if v is None:
            txt, f, _a = self._plano(ch)
            v = self._av[ch] = f.getlength(txt)
        return v

    def largura(self, txt: str) -> float:
        return sum(self.avanco(c) for c in txt)

    def getlength(self, txt: str) -> float:  # mesma cara de ImageFont (quem já usava ImageFont aceita uma Letra)
        return self.largura(txt)

    def getmetrics(self) -> Tuple[int, int]:
        return self.asc, self.desc

    def quebrar(self, txt: str, largura: float) -> List[str]:
        """Quebra em linhas que cabem em `largura` (respeita as quebras do texto)."""
        linhas: List[str] = []
        for par in str(txt or "").replace("\r", "").split("\n"):
            atual = ""
            for palavra in par.split(" "):
                tent = palavra if not atual else atual + " " + palavra
                if self.largura(tent) <= largura or not atual:
                    atual = tent
                else:
                    linhas.append(atual)
                    atual = palavra
            linhas.append(atual)
        return linhas

    def glifo(self, ch: str, cor) -> Tuple[Any, float, float]:
        """(imagem RGBA do caractere, dx, dy) — a imagem vai em (x + dx, linha_de_base + dy)."""
        return _glifo(self.caminho, self.reserva, self.px, ch, tuple(cor))


@lru_cache(maxsize=128)
def letra(fid: str, px: int, tipo: str = "manuscrita", caminho: Optional[str] = None) -> "Letra":
    """Letra guardada (o mesmo tamanho é pedido em todo quadro do vídeo)."""
    return Letra(fid, int(px), tipo, caminho)


@lru_cache(maxsize=6000)
def _glifo(caminho: str, reserva: str, px: int, ch: str, cor: tuple):
    from PIL import Image, ImageDraw
    let = Letra.__new__(Letra)
    let.caminho, let.reserva, let.px, let._av = caminho, reserva, px, {}
    let.f, let.fr = _fonte(caminho, px), _fonte(reserva, px)
    txt, f, acento = let._plano(ch)
    m = int(px * 0.6) + 4
    w = int(f.getlength(txt) + 2 * m) + 2
    h = int(px * 2.2 + 2 * m)
    base_y = int(m + px * 1.3)
    im = Image.new("RGBA", (max(4, w), h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((m, base_y), txt, font=f, fill=cor, anchor="ls")
    if acento:
        sinal, fs = acento
        bb = im.getbbox() or (m, base_y - px // 2, m + px // 2, base_y)  # a tinta da letra base
        cx = (bb[0] + bb[2]) / 2
        marca = _tinta(_fonte(fs.path, int(px * 0.9)) if getattr(fs, "path", None) else fs, sinal)
        if marca is None or marca.height > px * 0.6:  # acento da fonte esquisito: o da reserva
            marca = _tinta(_fonte(reserva, int(px * 0.9)), sinal)
        if marca is not None:
            tinta = Image.new("RGBA", marca.size, cor[:3] + (0,))
            tinta.putalpha(marca.point(lambda v: v * (cor[3] if len(cor) > 3 else 255) // 255))
            if sinal == "¸":  # cedilha embaixo da letra
                im.alpha_composite(tinta, (int(cx - marca.width / 2), int(min(h - marca.height, bb[3] - px * 0.02))))
            else:
                im.alpha_composite(tinta, (int(cx - marca.width / 2), int(max(0, bb[1] - px * 0.08 - marca.height))))
    return im, -m, -base_y
