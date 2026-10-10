"""
kwai.py
=======

Baixa o vídeo "cru" a partir de um link do Kwai, lendo o JSON embutido na
tag <script id="VideoObject"> da própria página (não usa yt-dlp aqui,
porque o Kwai expõe o link direto do vídeo nesse JSON).

Bibliotecas usadas: requests, beautifulsoup4.
"""
import json
import re
from pathlib import Path
from typing import Any

from ._utils import HEADERS_PADRAO
from ._ytdlp_base import RedesSociaisError


def baixar_video_kwai(url: str, pasta_destino: Path, requests_module: Any = None) -> str:
    """Baixa o vídeo do Kwai e salva como 'original.mp4' dentro de
    `pasta_destino`.

    `url`: link do vídeo no Kwai, ex: "https://www.kwai.com/@user/video/xxxx".
    `requests_module`: injeta um módulo `requests` alternativo (só pra
        teste — em uso normal, não passe nada).

    Devolve o caminho (string) do arquivo "original.mp4" salvo.
    """
    if requests_module is not None:
        requests = requests_module
    else:
        try:
            import requests  # type: ignore
        except ImportError as exc:
            raise RedesSociaisError(
                "O pacote 'requests' não está instalado. Rode: pip install requests"
            ) from exc
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RedesSociaisError(
            "O pacote 'beautifulsoup4' não está instalado. Rode: pip install beautifulsoup4"
        ) from exc

    pasta_destino = Path(pasta_destino)
    pasta_destino.mkdir(parents=True, exist_ok=True)

    try:
        response = requests.get(url, headers=HEADERS_PADRAO)
        response.raise_for_status()
    except RedesSociaisError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RedesSociaisError(f"Não consegui acessar o link do Kwai: {exc}") from exc

    soup = BeautifulSoup(response.text, "html.parser")
    script_tag = soup.find("script", id="VideoObject")
    if not script_tag:
        raise RedesSociaisError("Não achei a tag <script id='VideoObject'> no HTML — o link é mesmo de um vídeo do Kwai?")

    try:
        video_data = json.loads(script_tag.string)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RedesSociaisError(f"Não consegui ler os dados do vídeo (JSON inválido): {exc}") from exc

    content_url = video_data.get("contentUrl")
    if not content_url:
        raise RedesSociaisError("contentUrl não encontrado no JSON do vídeo.")

    caminho_video = str(pasta_destino / "original.mp4")

    try:
        with requests.get(content_url, headers=HEADERS_PADRAO, stream=True) as r:
            r.raise_for_status()
            with open(caminho_video, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
    except RedesSociaisError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RedesSociaisError(f"Falha ao baixar o vídeo do Kwai: {exc}") from exc

    return caminho_video


def _titulo_do_kwai(video_data: dict) -> str:
    """Extrai um título "limpo" do campo `name` do JSON do Kwai (que
    normalmente vem como "Título) #hashtags #mais_hashtags")."""
    name_completo = video_data.get("name", "video")
    match = re.match(r"^.*?\)", name_completo)
    name = match.group(0) if match else name_completo
    nome_seguro = re.sub(r'[\\/*?:"<>|]', "", name)
    nome_seguro = re.sub(r"[^\x00-\x7F]+", "", nome_seguro)
    return re.sub(r"\s+", " ", nome_seguro).strip() or "video_kwai"
