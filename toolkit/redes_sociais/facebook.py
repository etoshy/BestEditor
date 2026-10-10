"""
facebook.py
===========

Baixa vídeos/reels públicos do Facebook usando yt-dlp.

O Facebook costuma ser mais exigente que outras fontes — por isso usa um
User-Agent mais atual (Chrome recente) e mais tentativas em caso de falha
de rede/fragmento, em vez dos padrões genéricos usados por
instagram.py/twitter.py/tiktok.py.

Requisitos externos: ffmpeg instalado e no PATH.
"""
from pathlib import Path
from typing import Any, Optional

from ._ytdlp_base import baixar_com_ytdlp

# User-Agent mais recente que o HEADERS_PADRAO genérico — o Facebook tende
# a ser mais sensível a User-Agents desatualizados que outras plataformas.
_HEADERS_FACEBOOK = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}

# Vídeos do Facebook às vezes vêm em fragmentos que falham/piscam mais que
# o normal — mais tentativas aqui evita ter que reiniciar o download
# inteiro por causa de uma falha passageira de rede.
_OPCOES_EXTRAS_FACEBOOK = {
    "retries": 10,
    "fragment_retries": 10,
}


def baixar_video_facebook(
    url: str, pasta_destino: Path,
    cookies_path: Optional[str] = None, ytdlp_module: Any = None,
) -> str:
    """Baixa um vídeo/reel do Facebook e salva como 'original.mp4' dentro
    de `pasta_destino`.

    `url`: link do vídeo, ex: "https://www.facebook.com/watch/?v=xxxx" ou
        um link curto "https://fb.watch/xxxx/".
    `cookies_path`: opcional — MUITOS vídeos do Facebook exigem estar
        logado pra baixar (mesmo os "públicos"), então isso costuma ser
        necessário mais frequentemente aqui do que nas outras fontes.

    Devolve o caminho (string) do arquivo "original.mp4" salvo.
    """
    return baixar_com_ytdlp(
        url, pasta_destino, cookies_path=cookies_path,
        headers=_HEADERS_FACEBOOK, extra_opcoes=_OPCOES_EXTRAS_FACEBOOK,
        ytdlp_module=ytdlp_module,
    )
