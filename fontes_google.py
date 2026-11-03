"""🔤 v84_338: baixar fontes do Google Fonts (livres, OFL) direto pro site — no SEU PC, com internet.

Um catálogo pronto de fontes boas pra shorts (impacto, arredondadas, manuscritas, tech, terror, elegantes…) e a busca por
qualquer nome do Google Fonts. Cada uma vira "DP <Nome>" (o mesmo instalador da fonte enviada), aparece nas listas de
fonte do @ e da legenda como "(Google)" e é queimada pelo libass igual às de fábrica.

Como baixa: a API css do Google Fonts devolve o .ttf quando quem pede não é um navegador moderno — pega o peso mais forte
que a fonte tiver (700 → 400).
"""
from __future__ import annotations

import os
import re
import tempfile
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

# (nome no Google Fonts, grupo)
CATALOGO: List[tuple] = [
    # 💥 impacto / títulos
    ("Bangers", "💥 impacto"), ("Luckiest Guy", "💥 impacto"), ("Lilita One", "💥 impacto"), ("Titan One", "💥 impacto"),
    ("Archivo Black", "💥 impacto"), ("Bowlby One", "💥 impacto"), ("Passion One", "💥 impacto"), ("Russo One", "💥 impacto"),
    ("Black Ops One", "💥 impacto"), ("Bungee", "💥 impacto"), ("Changa One", "💥 impacto"), ("Paytone One", "💥 impacto"),
    ("Dela Gothic One", "💥 impacto"), ("Rubik Mono One", "💥 impacto"), ("Ultra", "💥 impacto"), ("Squada One", "💥 impacto"),
    ("Big Shoulders Display", "💥 impacto"), ("League Spartan", "💥 impacto"), ("Kanit", "💥 impacto"), ("Saira Condensed", "💥 impacto"),
    # 🫧 arredondadas / amigáveis
    ("Fredoka", "🫧 arredondada"), ("Baloo 2", "🫧 arredondada"), ("Nunito", "🫧 arredondada"), ("Rubik", "🫧 arredondada"),
    ("Varela Round", "🫧 arredondada"), ("Quicksand", "🫧 arredondada"), ("Chewy", "🫧 arredondada"), ("Sniglet", "🫧 arredondada"),
    ("Concert One", "🫧 arredondada"), ("Mochiy Pop One", "🫧 arredondada"),
    # ✍ manuscritas / pincel
    ("Permanent Marker", "✍ manuscrita"), ("Pacifico", "✍ manuscrita"), ("Lobster", "✍ manuscrita"), ("Caveat Brush", "✍ manuscrita"),
    ("Kaushan Script", "✍ manuscrita"), ("Satisfy", "✍ manuscrita"), ("Dancing Script", "✍ manuscrita"), ("Rock Salt", "✍ manuscrita"),
    ("Gochi Hand", "✍ manuscrita"), ("Marck Script", "✍ manuscrita"), ("Yellowtail", "✍ manuscrita"), ("Shadows Into Light", "✍ manuscrita"),
    # 🤖 tech / games
    ("Orbitron", "🤖 tech"), ("Audiowide", "🤖 tech"), ("Exo 2", "🤖 tech"), ("Press Start 2P", "🤖 tech"), ("Silkscreen", "🤖 tech"),
    ("Michroma", "🤖 tech"), ("Chakra Petch", "🤖 tech"), ("Share Tech Mono", "🤖 tech"), ("VT323", "🤖 tech"), ("Monoton", "🤖 tech"),
    # 🎃 terror / mistério
    ("Creepster", "🎃 terror"), ("Nosifer", "🎃 terror"), ("Butcherman", "🎃 terror"), ("Metal Mania", "🎃 terror"), ("Eater", "🎃 terror"),
    ("Pirata One", "🎃 terror"), ("UnifrakturMaguntia", "🎃 terror"),
    # 💎 elegantes / revista
    ("DM Serif Display", "💎 elegante"), ("Bodoni Moda", "💎 elegante"), ("Prata", "💎 elegante"), ("Cormorant Garamond", "💎 elegante"),
    ("Libre Baskerville", "💎 elegante"), ("Yeseva One", "💎 elegante"), ("Marcellus", "💎 elegante"), ("Italiana", "💎 elegante"),
    # 🧱 modernas limpas
    ("Sora", "🧱 moderna"), ("Outfit", "🧱 moderna"), ("Urbanist", "🧱 moderna"), ("Lexend", "🧱 moderna"), ("Manrope", "🧱 moderna"),
    ("Space Grotesk", "🧱 moderna"), ("Plus Jakarta Sans", "🧱 moderna"), ("Raleway", "🧱 moderna"), ("Josefin Sans", "🧱 moderna"),
    # 🎪 divertidas
    ("Bungee Shade", "🎪 divertida"), ("Rampart One", "🎪 divertida"), ("Rubik Wet Paint", "🎪 divertida"), ("Rubik Glitch", "🎪 divertida"),
    ("Bungee Inline", "🎪 divertida"), ("Fascinate", "🎪 divertida"), ("Shrikhand", "🎪 divertida"), ("Righteous", "🎪 divertida"),
]
_UA = "Mozilla/4.0 (compatible; BestEditor fontes)"  # um "navegador antigo": o Google devolve .ttf
_NOME_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ]{0,48}")


class FonteErro(Exception):
    pass


def familia_de(nome: str) -> str:
    return "DP " + " ".join(str(nome or "").split())


def instaladas() -> set:
    try:
        import dp_destaques
        return {str(v.get("familia") or "") for v in dp_destaques.fontes_json().values()}
    except Exception:  # noqa: BLE001
        return set()


def catalogo() -> List[Dict[str, Any]]:
    tem = instaladas()
    return [{"nome": n, "grupo": g, "familia": familia_de(n), "instalada": familia_de(n) in tem} for n, g in CATALOGO]


def _pegar(url: str, abrir: Optional[Callable] = None, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with (abrir or urllib.request.urlopen)(req, timeout=timeout) as r:
        return r.read()


def url_do_ttf(nome: str, abrir: Optional[Callable] = None) -> str:
    """O endereço do .ttf mais forte (700, senão 400, senão o 1º que vier)."""
    fam = urllib.parse.quote_plus(nome)
    for pesos in ("700", "400", ""):
        url = f"https://fonts.googleapis.com/css?family={fam}" + (f":{pesos}" if pesos else "")
        try:
            css = _pegar(url, abrir).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001  (400 = esse peso não existe nessa fonte)
            continue
        achados = re.findall(r"src:\s*url\((https://[^)]+?)\)\s*format\('(truetype|opentype)'\)", css)
        if achados:
            return achados[0][0]
        m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+?\.(?:ttf|otf))\)", css)
        if m:
            return m.group(1)
    raise FonteErro(f"não achei a fonte “{nome}” no Google Fonts (confira o nome em fonts.google.com)")


def baixar(nome: str, abrir: Optional[Callable] = None) -> Dict[str, Any]:
    """Baixa e instala. Devolve {"familia", "nome", "ja_tinha"}."""
    nome = " ".join(str(nome or "").split())
    if not _NOME_OK.fullmatch(nome):
        raise FonteErro("nome de fonte inválido (só letras, números e espaços)")
    fam = familia_de(nome)
    if fam in instaladas():
        return {"familia": fam, "nome": nome, "ja_tinha": True}
    url = url_do_ttf(nome, abrir)
    try:
        dados = _pegar(url, abrir, timeout=60)
    except Exception as exc:  # noqa: BLE001
        raise FonteErro(f"não consegui baixar “{nome}”: {exc}") from exc
    if len(dados) < 1000:
        raise FonteErro(f"o arquivo de “{nome}” veio vazio")
    import acabamento_extra
    fd, tmp = tempfile.mkstemp(suffix=".ttf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dados)
        try:
            it = acabamento_extra.instalar_fonte(tmp, nome, prefixo="gf_")
        except ValueError as exc:
            raise FonteErro(str(exc)) from exc
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return {"familia": it["familia"], "nome": nome, "ja_tinha": False}
