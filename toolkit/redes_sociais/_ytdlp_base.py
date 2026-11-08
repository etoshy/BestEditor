"""
_ytdlp_base.py
==============

Instagram, Twitter/X, TikTok e Facebook baixam do mesmo jeito (yt-dlp
resolve tudo), só muda o link/cabeçalhos. Em vez de repetir o código em
cada módulo, cada um chama `baixar_com_ytdlp()` daqui.

Isso NÃO é uma fonte por si só (não tem entrada em `FONTES_SUPORTADAS`) —
é só a "engine" usada por instagram.py, twitter.py, tiktok.py e facebook.py.
"""
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ._utils import HEADERS_PADRAO


class RedesSociaisError(Exception):
    """Falha ao baixar ou consultar um vídeo de alguma rede social."""


def verificar_ytdlp(ytdlp_module: Any = None) -> bool:
    """Confere se o pacote 'yt-dlp' está instalado (ou se um módulo já foi injetado)."""
    if ytdlp_module is not None:
        return True
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False


NAVEGADORES = ["firefox", "edge", "chrome", "brave", "opera", "vivaldi", "chromium"]
AJUDA_LOGIN = (
    "A rede pediu login pra liberar esse vídeo (o Instagram faz isso muito). Como resolver: (1) abra o FIREFOX (ou o Edge), "
    "entre na sua conta do Instagram/TikTok e tente de novo — o site usa os cookies dele sozinho (feche o Chrome antes, se "
    "for usar o Chrome: aberto ele bloqueia a leitura); ou (2) exporte o cookies.txt com a extensão “Get cookies.txt "
    "LOCALLY” com o site aberto e logado e envie em Configurações → YouTube (cookies.txt — vale pra todas as redes); "
    "(3) atualize o yt-dlp: pip install -U \"yt-dlp[default]\"."
)


def pediu_login(exc: Any) -> bool:
    m = str(exc).lower()
    return any(k in m for k in ("empty media response", "login", "log in", "cookies", "rate-limit", "rate limit",
                                "requested content is not available", "private", "not available", "sign in", "authentication"))


# 🌐 v84_363: a conexão caiu no meio (o Instagram corta quando recebe pedidos demais: "10054 ... cancelamento de uma conexão
# existente pelo host remoto", "Connection broken", "Too Many Requests") → espera e tenta de novo; se continuar, tenta com os
# cookies do navegador logado (o Instagram corta bem menos quem está logado).
ESPERAS_REDE_S = (6, 20, 45)


def erro_de_rede(exc: Any) -> bool:
    m = str(exc).lower()
    return any(k in m for k in ("10054", "10053", "10060", "connection reset", "connection broken", "connection aborted",
                                "forcibly closed", "remote end closed", "remotedisconnected", "incompleteread", "timed out",
                                "timeout", "too many requests", "http error 429", "429", "temporarily unavailable",
                                "cancelamento de uma conex", "getaddrinfo failed", "name resolution", "ssl: ", "eof occurred"))


def _prefs():
    try:
        import yt_cookies  # a pasta do site (o mesmo lugar dos cookies do YouTube)
        return yt_cookies
    except ImportError:
        return None


def _tentar_com_cookies(yt_dlp: Any, opcoes: Dict[str, Any], url: str, primeiro: Exception) -> None:
    yc = _prefs()
    tentativas = []
    arq = yc.arquivo_cookies() if yc else None
    if arq:
        tentativas.append(("cookies.txt", {"cookiefile": arq}))
    guardado = (yc.prefs().get("redes_navegador") if yc else None) or ""
    for nav in ([guardado] if guardado in NAVEGADORES else []) + [n for n in NAVEGADORES if n != guardado]:
        tentativas.append((nav, {"cookiesfrombrowser": (nav,)}))
    erros = [f"sem cookies: {str(primeiro).strip()[:140]}"]
    for nome, extra in tentativas:
        try:
            with yt_dlp.YoutubeDL(dict(opcoes, **extra)) as ydl:
                ydl.download([url])
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{nome}: {str(exc).strip()[:120]}")
            continue
        if yc and nome in NAVEGADORES:
            try:
                yc.salvar_prefs(redes_navegador=nome)
            except Exception:  # noqa: BLE001
                pass
        return
    import re as _re
    erros = [_re.sub(r"\x1b?\[[0-9;]{1,6}m", "", e_) for e_ in erros]  # 🧹 sem códigos de cor
    raise RedesSociaisError(AJUDA_LOGIN + "\nTentativas: " + " ; ".join(erros))


def baixar_com_ytdlp(
    url: str,
    pasta_destino: Path,
    cookies_path: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    extra_opcoes: Optional[Dict[str, Any]] = None,
    ytdlp_module: Any = None,
    varios: bool = False,
) -> str:
    """Baixa qualquer vídeo suportado pelo yt-dlp e salva como 'original.mp4'
    dentro de `pasta_destino`, sempre na MELHOR qualidade disponível (sem
    nenhum teto de resolução aqui — se o vídeo original for 4K, baixa em 4K).

    `cookies_path`: caminho opcional pra um arquivo de cookies exportado do
        navegador (necessário pra conteúdo privado/restrito de login).
    `headers`: cabeçalhos HTTP extras; usa `HEADERS_PADRAO` se não informado.
    `extra_opcoes`: opções extras do yt-dlp (dict) pra sobrepor/completar as
        opções padrão — ex: `{"retries": 10}` pra uma fonte que costuma
        precisar de mais tentativas.
    `ytdlp_module`: injeta um módulo yt-dlp alternativo (só pra teste — em
        uso normal, não passe nada, usa o `yt_dlp` de verdade).

    Devolve o caminho (string) do arquivo "original.mp4" salvo.
    """
    if ytdlp_module is not None:
        yt_dlp = ytdlp_module
    else:
        try:
            import yt_dlp  # type: ignore
        except ImportError as exc:
            raise RedesSociaisError(
                "O pacote 'yt-dlp' não está instalado. Rode: pip install yt-dlp"
            ) from exc

    pasta_destino = Path(pasta_destino)
    pasta_destino.mkdir(parents=True, exist_ok=True)

    # outtmpl com "%(ext)s": o yt-dlp escolhe a extensão intermediária de
    # cada stream baixado, mas o merge_output_format="mp4" abaixo garante
    # que o arquivo final sempre vira "original.mp4".
    saida_template = str(pasta_destino / "original.%(ext)s")
    if varios:  # 🎠 v84_351: post com VÁRIOS vídeos (carrossel do Instagram…): item_1.mp4, item_2.mp4… (devolve a pasta)
        saida_template = str(pasta_destino / "item_%(playlist_index|1)s.%(ext)s")

    opcoes: Dict[str, Any] = {
        "outtmpl": saida_template,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "http_headers": headers or HEADERS_PADRAO,
        "noplaylist": not varios,
        "quiet": True,
        "no_warnings": True,
        "no_color": True,  # 🧹 v84_329: sem os códigos de cor ([0;31m) no erro que aparece na página
        "color": {"stdout": "no_color", "stderr": "no_color"},
    }
    if cookies_path:
        opcoes["cookiefile"] = cookies_path
    if extra_opcoes:
        opcoes.update(extra_opcoes)

    opcoes.setdefault("retries", 10)  # 🌐 v84_363: o próprio yt-dlp repete os pedidos que caem
    opcoes.setdefault("fragment_retries", 10)
    opcoes.setdefault("extractor_retries", 3)
    opcoes.setdefault("socket_timeout", 30)
    esperas = (0,) * len(ESPERAS_REDE_S) if ytdlp_module is not None else ESPERAS_REDE_S
    try:
        try:
            exc_rede = None
            for k in range(len(esperas) + 1):
                try:
                    with yt_dlp.YoutubeDL(opcoes) as ydl:
                        ydl.download([url])
                    exc_rede = None
                    break
                except Exception as exc_k:  # noqa: BLE001
                    if not erro_de_rede(exc_k) or k == len(esperas):
                        raise
                    exc_rede = exc_k
                    time.sleep(esperas[k])
        except Exception as exc0:  # noqa: BLE001
            # 🍪 v84_311: o Instagram/TikTok/Facebook pediu login ("empty media response") → tenta com os cookies dos
            # navegadores em que você está logado (o que funcionar fica guardado). Não mexe se já veio cookie de fora.
            # 🌐 v84_363: a conexão continuou caindo depois das novas tentativas → os cookies também (logado corta menos).
            if ytdlp_module is not None or cookies_path or not (pediu_login(exc0) or erro_de_rede(exc0)):
                raise
            try:
                _tentar_com_cookies(yt_dlp, opcoes, url, exc0)
            except RedesSociaisError:
                if erro_de_rede(exc0):
                    raise exc0
                raise
    except RedesSociaisError:
        raise
    except Exception as exc:  # noqa: BLE001
        mensagem_original = str(exc)
        if erro_de_rede(exc):  # 🌐 v84_363: explica em português o que é
            raise RedesSociaisError(
                "🌐 A conexão com o site caiu no meio do download (tentei de novo 3 vezes e com os cookies do navegador). "
                "Isso é o Instagram/TikTok cortando por excesso de pedidos seguidos (bloqueio temporário) ou a internet/antivírus/VPN "
                "derrubando a conexão. O que fazer: espere 15-30 min e clique em 🔁 tentar de novo (ou marque todos e ▶ produzir "
                "marcados); entre na sua conta do Instagram no navegador (logado ele corta bem menos); se usar VPN, desligue; "
                "e atualize o yt-dlp (pip install -U yt-dlp).\n"
                f"(detalhe: {mensagem_original.strip()[:300]})"
            ) from exc
        dica_impersonation = ""
        if "impersonat" in mensagem_original.lower() or "unexpected response from webpage" in mensagem_original.lower():
            dica_impersonation = (
                "  - PROVÁVEL CAUSA: falta o pacote 'curl_cffi' — o TikTok (e às vezes o "
                "Instagram) exige que o yt-dlp imite a \"impressão digital\" de um navegador "
                "de verdade. Rode: pip install curl_cffi --upgrade\n"
            )
        raise RedesSociaisError(
            f"Erro ao baixar com yt-dlp: {mensagem_original}\n"
            "Dicas:\n"
            f"{dica_impersonation}"
            "  - Confira se o link é público.\n"
            "  - Tente atualizar o yt-dlp: pip install -U yt-dlp\n"
            "  - Se o conteúdo for privado/restrito, exporte os cookies do seu navegador e "
            "passe o caminho pelo parâmetro cookies_path."
        ) from exc

    if varios:
        if not any(pasta_destino.glob("item_*.mp4")):
            raise RedesSociaisError("Não veio nenhum vídeo desse post (pode ser só foto, ou pedir login — veja os cookies).")
        return str(pasta_destino)
    caminho_final = pasta_destino / "original.mp4"
    if not caminho_final.exists():
        raise RedesSociaisError(
            f"yt-dlp terminou sem erro, mas não encontrei '{caminho_final}'. "
            "Confira o conteúdo da pasta — pode ter salvo com outra extensão."
        )
    return str(caminho_final)
