"""
instagram.py
============

Baixa Reels/posts de vídeo do Instagram usando yt-dlp, que já sabe
resolver os links do Instagram sozinho.

Requisitos externos: ffmpeg instalado e no PATH (necessário pro yt-dlp
juntar vídeo + áudio quando eles vêm em streams separados).
"""
from pathlib import Path
from typing import Any, Optional

from ._ytdlp_base import baixar_com_ytdlp


def baixar_video_instagram(
    url: str, pasta_destino: Path,
    cookies_path: Optional[str] = None, ytdlp_module: Any = None,
) -> str:
    """Baixa um Reel/post de vídeo do Instagram e salva como 'original.mp4'
    dentro de `pasta_destino`.

    `url`: link do Reel/post, ex: "https://www.instagram.com/reel/xxxx/".
    `cookies_path`: opcional — só é necessário se o conteúdo for
        privado/restrito.

    Devolve o caminho (string) do arquivo "original.mp4" salvo.
    """
    return baixar_com_ytdlp(url, pasta_destino, cookies_path=cookies_path, ytdlp_module=ytdlp_module)
