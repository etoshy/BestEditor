"""
Cookies do YouTube pro yt-dlp — contra o "Sign in to confirm you're not a bot".

O YouTube às vezes exige login pra ler/baixar um vídeo (principalmente depois de
muitos pedidos do mesmo IP). O yt-dlp resolve isso com os cookies de um navegador
em que você está logado no YouTube. Aqui:

  1. se houver um arquivo `cookies_youtube.txt` (formato Netscape) na pasta do
     site — ou enviado em Configurações → YouTube —, ele é usado sempre;
  2. senão, se um navegador foi escolhido (ou já funcionou antes), usa os cookies
     dele;
  3. se mesmo assim o YouTube pedir login, tenta sozinho os navegadores instalados
     (Firefox, Edge, Chrome, Brave, Opera, Vivaldi) e GUARDA o que funcionou.

Tudo em `youtube_cookies.json` na pasta do site — sem mexer no site_config.
"""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Callable, Dict, List, Optional

_AQUI = os.path.dirname(os.path.abspath(__file__))
ARQ_PREFS = os.path.join(_AQUI, "youtube_cookies.json")
ARQ_COOKIES = os.path.join(_AQUI, "cookies_youtube.txt")
NAVEGADORES = ["firefox", "edge", "chrome", "brave", "opera", "vivaldi", "chromium"]
_trava = threading.Lock()

AJUDA = (
    "O YouTube pediu login (“Sign in to confirm you’re not a bot”). Como resolver: "
    "(1) abra o Firefox, entre na sua conta do YouTube e tente de novo — o site usa os cookies dele sozinho; "
    "ou (2) no Chrome/Edge instale a extensão “Get cookies.txt LOCALLY”, abra youtube.com logado, exporte e envie o arquivo "
    "em Configurações → YouTube (cookies.txt); "
    "(3) atualize o yt-dlp: pip install -U \"yt-dlp[default]\". "
    "Obs.: o Chrome aberto costuma bloquear a leitura dos cookies (feche ele antes) e as versões novas do Chrome criptografam "
    "os cookies de um jeito que o yt-dlp nem sempre consegue ler — o Firefox ou o cookies.txt são os caminhos mais garantidos."
)


class YoutubeBloqueado(Exception):
    """O YouTube pediu login e nenhum cookie resolveu."""


def limpar(msg: Any) -> str:
    """Tira as cores do terminal (\\x1b[0;31m…) e espaços repetidos da mensagem do yt-dlp."""
    return re.sub(r"\s+", " ", re.sub(r"\x1b\[[0-9;]*m|\[0;\d+m|\[0m", "", str(msg))).strip()


def eh_bloqueio(msg: Any) -> bool:
    m = limpar(msg).lower()
    return any(k in m for k in ("confirm you", "not a bot", "sign in to confirm", "use --cookies", "cookies-from-browser",
                                "login required", "this video may be inappropriate", "page needs to be reloaded"))


def prefs() -> Dict[str, Any]:
    try:
        with open(ARQ_PREFS, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def salvar_prefs(**mudancas: Any) -> Dict[str, Any]:
    with _trava:
        d = prefs()
        for k, v in mudancas.items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = v
        with open(ARQ_PREFS, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return d


def arquivo_cookies() -> Optional[str]:
    p = prefs().get("arquivo") or ARQ_COOKIES
    return p if p and os.path.isfile(p) and os.path.getsize(p) > 0 else None


def opcoes() -> Dict[str, Any]:
    """Opções de cookies pro YoutubeDL (vazio = sem cookies)."""
    arq = arquivo_cookies()
    if arq:
        return {"cookiefile": arq}
    p = prefs()
    nav = p.get("navegador") or p.get("navegador_que_funcionou")
    if nav and nav != "nenhum":
        return {"cookiesfrombrowser": (nav,)}
    return {}


def descrever() -> str:
    o = opcoes()
    if "cookiefile" in o:
        return f"arquivo {os.path.basename(o['cookiefile'])}"
    if "cookiesfrombrowser" in o:
        return f"cookies do {o['cookiesfrombrowser'][0]}"
    return "sem cookies"


def salvar_arquivo(conteudo: bytes) -> str:
    texto = conteudo.decode("utf-8", "replace")
    if "youtube.com" not in texto and ".google." not in texto:
        raise ValueError("Esse arquivo não parece ter cookies do YouTube (exporte com youtube.com aberto e logado).")
    with open(ARQ_COOKIES, "wb") as f:
        f.write(conteudo)
    salvar_prefs(arquivo=None)
    return ARQ_COOKIES


def tentar(acao: Callable[[Dict[str, Any]], Any], log: Callable[[str], None] = lambda _m: None) -> Any:
    """Roda `acao(opcoes_de_cookies)`. Se o YouTube pedir login, tenta os cookies
    dos navegadores instalados um por um e guarda o que funcionou."""
    base = opcoes()
    try:
        return acao(dict(base))
    except Exception as exc:  # noqa: BLE001
        if not eh_bloqueio(exc):
            raise
        primeiro = limpar(exc)
    ja = (base.get("cookiesfrombrowser") or (None,))[0]
    erros: List[str] = []
    if base:
        erros.append(f"{descrever()}: {primeiro[:160]}")
    for nav in NAVEGADORES:
        if nav == ja:
            continue
        log(f"🍪 O YouTube pediu login — tentando com os cookies do {nav}…")
        try:
            r = acao({"cookiesfrombrowser": (nav,)})
        except Exception as exc:  # noqa: BLE001
            m = limpar(exc)
            erros.append(f"{nav}: {m[:160]}")
            continue
        salvar_prefs(navegador_que_funcionou=nav)
        log(f"✔ Funcionou com os cookies do {nav} (fica guardado pras próximas vezes)")
        return r
    raise YoutubeBloqueado(AJUDA + " | Tentativas: " + " ; ".join(erros or [primeiro[:200]]))
