"""
twitter.py
==========

Baixa vídeos de tweets/posts do Twitter (twitter.com) e do X (x.com)
usando yt-dlp, que já sabe resolver esses links sozinho.

Requisitos externos: ffmpeg instalado e no PATH.
"""
from pathlib import Path
from typing import Any, Optional

from ._ytdlp_base import baixar_com_ytdlp


def baixar_video_twitter(
    url: str, pasta_destino: Path,
    cookies_path: Optional[str] = None, ytdlp_module: Any = None,
) -> str:
    """Baixa o vídeo de um tweet/post do Twitter (X) e salva como
    'original.mp4' dentro de `pasta_destino`.

    `url`: link do tweet, ex: "https://x.com/usuario/status/1234567890".
    `cookies_path`: opcional — só é necessário se o conteúdo for
        privado/restrito.

    Devolve o caminho (string) do arquivo "original.mp4" salvo.
    """
    return baixar_com_ytdlp(url, pasta_destino, cookies_path=cookies_path, ytdlp_module=ytdlp_module)
