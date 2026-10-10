"""
Acervos de clipes do Anime Pexels — LOCAL (o app.py rodando no seu PC) e
ONLINE (o mesmo projeto em modo servidor, com chave de API).

Quatro fontes, dois catálogos cada servidor:
  animepexels          anime, servidor local   (animepexels_base_url)
  moviepexels          filmes/séries, local    (mesmo servidor, /movie/)
  animepexels_online   anime, servidor online  (animepexels_online_url + chave)
  moviepexels_online   filmes/séries, online   (mesmo servidor online, /movie/)

As online NÃO substituem as locais: são alternativas. Tudo o que vale pra
uma local (obra, personagem/ator, pesos da busca, prompt dedicado) vale pra
online equivalente — `base()` diz qual é.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

LOCAIS = ("animepexels", "moviepexels")
ONLINE = ("animepexels_online", "moviepexels_online")
TODOS = LOCAIS + ONLINE

URL_ONLINE_PADRAO = "http://84.247.133.185"

ROTULOS = {
    "animepexels": "🎌 Anime Pexels (local)",
    "moviepexels": "🎬 Filmes e Séries Pexels (local)",
    "animepexels_online": "🌐🎌 Anime Pexels online",
    "moviepexels_online": "🌐🎬 Filmes e Séries Pexels online",
}


def eh_acervo(p: Any) -> bool:
    return p in TODOS


def eh_online(p: Any) -> bool:
    return p in ONLINE


def base(p: str) -> str:
    """"moviepexels_online" -> "moviepexels" (o comportamento é o mesmo)."""
    return p[: -len("_online")] if p in ONLINE else p


def eh_filmes(p: Any) -> bool:
    return base(str(p or "")) == "moviepexels"


def so_acervo(providers) -> bool:
    """Só UM acervo marcado (local ou online): o site usa o prompt dedicado."""
    return isinstance(providers, (list, tuple)) and len(providers) == 1 and providers[0] in TODOS


def config_online(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    if cfg is None:
        from site_config import load_site_config
        cfg = load_site_config()
    return {"url": (cfg.get("animepexels_online_url") or URL_ONLINE_PADRAO).rstrip("/"),
            "chave": (cfg.get("animepexels_online_api_key") or "").strip()}


def _modulo():
    tk = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit")
    if tk not in sys.path:
        sys.path.insert(0, tk)
    import importlib
    return importlib.import_module("animepexels.animepexels_client")


def cliente(p: str, cfg: Optional[Dict[str, Any]] = None, timeout: Optional[int] = None):
    """Cliente certo pra fonte `p` (local ou online, anime ou filmes)."""
    m = _modulo()
    if cfg is None:
        from site_config import load_site_config
        cfg = load_site_config()
    kw: Dict[str, Any] = {}
    if timeout:
        kw["timeout"] = timeout
    if eh_online(p):
        on = config_online(cfg)
        classe = m.MoviePexelsOnlineClient if eh_filmes(p) else m.AnimePexelsOnlineClient
        return classe(base_url=on["url"], api_key=on["chave"] or None, **kw)
    classe = m.MoviePexelsClient if eh_filmes(p) else m.AnimePexelsClient
    return classe(base_url=cfg.get("animepexels_base_url") or m.DEFAULT_BASE_URL, **kw)
