"""
tiktok.py
=========

Baixa vídeos do TikTok usando yt-dlp, que já sabe resolver os links do
TikTok sozinho (inclusive sem marca d'água, na maioria dos casos).

Requisitos externos: ffmpeg instalado e no PATH. Costuma precisar do
pacote `curl_cffi` (o TikTok exige "impersonation" de navegador) — sem
ele, o erro do yt-dlp já vem com a dica de instalação.
"""
from pathlib import Path
from typing import Any, Optional

from ._ytdlp_base import baixar_com_ytdlp


def baixar_video_tiktok(
    url: str, pasta_destino: Path,
    cookies_path: Optional[str] = None, ytdlp_module: Any = None,
) -> str:
    """Baixa um vídeo do TikTok e salva como 'original.mp4' dentro de
    `pasta_destino`.

    `url`: link do vídeo, ex: "https://www.tiktok.com/@user/video/xxxx".
    `cookies_path`: opcional — só é necessário se o conteúdo for
        privado/restrito.

    Devolve o caminho (string) do arquivo "original.mp4" salvo.
    """
    return baixar_com_ytdlp(url, pasta_destino, cookies_path=cookies_path, ytdlp_module=ytdlp_module)
