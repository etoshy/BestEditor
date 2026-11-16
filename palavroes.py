"""🤬 v84_401 — palavrões (inglês, português, espanhol): achar e tirar do texto narrado (o "reverse rage" nunca xinga).
Lista curta e direta — os casos fortes; "hell"/"damn" ficam (as regras de anúncio aceitam)."""
from __future__ import annotations

import re
from typing import List

_EN = ["fuck", "fucking", "fucked", "fucker", "motherfucker", "shit", "bullshit", "bitch", "bastard", "asshole", "dick",
       "cunt", "pussy", "whore", "slut", "retard", "faggot", "nigger", "nigga", "cock", "wanker", "twat", "prick"]
_PT = ["porra", "caralho", "merda", "puta", "puto", "foda", "fodase", "foda-se", "fodido", "cacete", "buceta", "viado",
       "arrombado", "desgraçado", "filho da puta", "fdp", "corno", "otário", "babaca", "vagabundo", "vagabunda", "piranha"]
_ES = ["mierda", "puta", "pendejo", "cabrón", "cabron", "joder", "coño", "verga", "chingada", "chingar", "maricón", "pinche"]
LISTA = sorted(set(_EN + _PT + _ES), key=len, reverse=True)
_RE = re.compile(r"(?<![\w*])(" + "|".join(re.escape(w) for w in LISTA) + r")\w*", re.IGNORECASE)


def achar(texto: str) -> List[str]:
    return [m.group(0) for m in _RE.finditer(texto or "")]


def limpar(texto: str) -> str:
    """Tira o palavrão (e o espaço que sobra) — pra voz não falar e a legenda não mostrar."""
    t = _RE.sub("", texto or "")
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    t = re.sub(r",\s*([.!?])", r"\1", t)        # "essa, ?" → "essa?"
    t = re.sub(r",\s*,", ",", t)
    return re.sub(r"\s{2,}", " ", t).strip()
