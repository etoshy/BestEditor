"""
_utils.py
=========

Pedacinhos compartilhados pelos módulos de download (kwai.py, instagram.py,
twitter.py, tiktok.py, facebook.py) — nada aqui baixa vídeo sozinho.
"""
import subprocess

# User-Agent "de navegador normal" usado nas requisições HTTP diretas
# (kwai.py) e como header extra passado pro yt-dlp (instagram/twitter/
# tiktok), porque vários sites bloqueiam requisições sem esse cabeçalho.
HEADERS_PADRAO = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def tem_audio(video_path: str) -> bool:
    """Verifica (via ffprobe) se o vídeo baixado realmente tem faixa de áudio."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index", "-of", "csv=p=0",
        video_path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    return bool(out)
