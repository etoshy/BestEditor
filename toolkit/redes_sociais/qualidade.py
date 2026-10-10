"""
qualidade.py
============

Consulta a qualidade MÁXIMA disponível de um vídeo (largura, altura, fps,
codec, tamanho aproximado, duração) sem baixar o vídeo inteiro — só os
metadados. Suporta as mesmas fontes do resto do pacote (via yt-dlp) mais
YouTube, já que essa checagem não precisa "escolher qual downloader
baixa": só olha os metadados que o yt-dlp já traz pra qualquer link que
ele reconheça, e trata o Kwai à parte (não é suportado por ele).
"""
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from ._ytdlp_base import RedesSociaisError
from ._utils import HEADERS_PADRAO

# Domínios que o yt-dlp resolve sozinho (inclui o YouTube, mesmo esse
# módulo não tendo um downloader próprio pra ele — youtube_clipper.py
# já cuida do download; aqui só checamos a qualidade).
DOMINIOS_YTDLP = {
    "youtube.com", "youtu.be", "m.youtube.com",
    "tiktok.com", "twitter.com", "x.com", "instagram.com",
    "facebook.com", "fb.watch",
}


def _obter_dominio(url: str) -> str:
    netloc = urlparse(url).netloc.split(":")[0]
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or ""


def _checar_via_ytdlp(url: str, ytdlp_module: Any = None) -> Dict[str, Any]:
    if ytdlp_module is not None:
        yt_dlp = ytdlp_module
    else:
        try:
            import yt_dlp  # type: ignore
        except ImportError as exc:
            raise RedesSociaisError("O pacote 'yt-dlp' não está instalado. Rode: pip install yt-dlp") from exc

    opcoes = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(url, download=False)

    # Escolhe o formato de VÍDEO com a maior resolução entre os disponíveis
    # (ignora formatos só-de-áudio) — é a mesma info que "bestvideo" usaria
    # na hora de baixar de verdade.
    formatos = info.get("formats") or []
    melhor = None
    for f in formatos:
        if f.get("vcodec") in (None, "none"):
            continue
        area = (f.get("height") or 0) * (f.get("width") or 0)
        area_melhor = (melhor.get("height") or 0) * (melhor.get("width") or 0) if melhor else -1
        if melhor is None or area > area_melhor:
            melhor = f
    if melhor is None:
        melhor = info

    tamanho = melhor.get("filesize") or melhor.get("filesize_approx")
    return {
        "titulo": info.get("title"),
        "largura": melhor.get("width") or info.get("width"),
        "altura": melhor.get("height") or info.get("height"),
        "fps": melhor.get("fps") or info.get("fps"),
        "codec_video": melhor.get("vcodec"),
        "extensao": melhor.get("ext") or info.get("ext"),
        "tamanho_aproximado_mb": round(tamanho / 1024 / 1024, 1) if tamanho else None,
        "duracao_segundos": info.get("duration"),
    }


def _titulo_do_kwai(name_completo: str) -> str:
    match = re.match(r"^.*?\)", name_completo)
    return match.group(0) if match else name_completo


def _checar_via_kwai(url: str, requests_module: Any = None, ffprobe_runner: Any = None) -> Dict[str, Any]:
    if requests_module is not None:
        requests = requests_module
    else:
        try:
            import requests  # type: ignore
        except ImportError as exc:
            raise RedesSociaisError("O pacote 'requests' não está instalado. Rode: pip install requests") from exc
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RedesSociaisError("O pacote 'beautifulsoup4' não está instalado. Rode: pip install beautifulsoup4") from exc

    r = requests.get(url, headers=HEADERS_PADRAO, timeout=15)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    script_tag = soup.find("script", id="VideoObject")
    if not script_tag:
        raise RedesSociaisError("Não achei os dados do vídeo nessa página do Kwai.")

    dados = json.loads(script_tag.string)
    content_url = dados.get("contentUrl")
    if not content_url:
        raise RedesSociaisError("contentUrl não encontrado no JSON do vídeo.")

    # Lê as informações do stream DIRETO da URL remota (ffprobe consegue ler
    # só o cabeçalho na maioria dos casos) — sem baixar o vídeo inteiro só
    # pra descobrir a resolução.
    executar = ffprobe_runner or subprocess.run
    resultado = executar(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,codec_name",
         "-show_entries", "format=duration,size",
         "-of", "json", content_url],
        capture_output=True, text=True, timeout=30,
    )
    info_ffprobe = json.loads(resultado.stdout or "{}")
    streams = info_ffprobe.get("streams") or []
    if not streams:
        raise RedesSociaisError(
            "Não consegui ler as informações do vídeo (ffprobe) — " + (resultado.stderr or "")[-300:]
        )
    s = streams[0]
    fmt = info_ffprobe.get("format", {})

    fps = None
    if s.get("r_frame_rate") and "/" in s["r_frame_rate"]:
        num, den = s["r_frame_rate"].split("/")
        try:
            if float(den) > 0:
                fps = round(float(num) / float(den), 2)
        except (ValueError, ZeroDivisionError):
            pass

    tamanho = fmt.get("size")
    return {
        "titulo": _titulo_do_kwai(dados.get("name", "video")),
        "largura": s.get("width"),
        "altura": s.get("height"),
        "fps": fps,
        "codec_video": s.get("codec_name"),
        "extensao": None,
        "tamanho_aproximado_mb": round(float(tamanho) / 1024 / 1024, 1) if tamanho else None,
        "duracao_segundos": round(float(fmt["duration"]), 1) if fmt.get("duration") else None,
    }


def checar_qualidade(
    url: str, ytdlp_module: Any = None, requests_module: Any = None, ffprobe_runner: Any = None,
) -> Dict[str, Any]:
    """Devolve a qualidade máxima disponível de `url` sem baixar o vídeo
    inteiro: `{titulo, largura, altura, fps, codec_video, extensao,
    tamanho_aproximado_mb, duracao_segundos, dominio}`.

    Suporta YouTube, TikTok, Twitter/X, Instagram, Facebook (via yt-dlp) e
    Kwai (via requests + beautifulsoup4 + ffprobe no link direto).
    """
    dominio = _obter_dominio(url)
    if dominio in DOMINIOS_YTDLP:
        resultado = _checar_via_ytdlp(url, ytdlp_module=ytdlp_module)
    elif dominio == "kwai.com":
        resultado = _checar_via_kwai(url, requests_module=requests_module, ffprobe_runner=ffprobe_runner)
    else:
        raise RedesSociaisError(
            f"Fonte '{dominio}' não suportada. Fontes disponíveis: YouTube, TikTok, "
            "Twitter/X, Instagram, Facebook, Kwai."
        )
    resultado["dominio"] = dominio
    return resultado
