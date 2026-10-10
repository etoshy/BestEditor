"""
toolkit.redes_sociais
======================

Baixa vídeos "crus" de redes sociais além do YouTube (que já tem seu
próprio módulo em `youtube_clipper.py`), e checa a qualidade máxima
disponível de um link sem baixar o vídeo inteiro.

Cada módulo de plataforma implementa a função
`baixar_video_<fonte>(url, pasta_destino, ...) -> str`, salva o vídeo
baixado como "original.mp4" e devolve esse caminho.

Fontes disponíveis: Kwai, Instagram, Twitter/X, TikTok, Facebook.

Pra adicionar uma fonte nova:
    1. Crie `<fonte>.py` com uma função `baixar_video_<fonte>(url,
       pasta_destino, ...) -> str`, seguindo o contrato acima.
    2. Importe essa função aqui embaixo e registre o(s) domínio(s) dela em
       `FONTES_SUPORTADAS`.
"""
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from ._ytdlp_base import RedesSociaisError, verificar_ytdlp
from ._utils import tem_audio
from .kwai import baixar_video_kwai
from .instagram import baixar_video_instagram
from .twitter import baixar_video_twitter
from .tiktok import baixar_video_tiktok
from .facebook import baixar_video_facebook

FONTES_SUPORTADAS = {
    "kwai.com": baixar_video_kwai,
    "instagram.com": baixar_video_instagram,
    "twitter.com": baixar_video_twitter,
    "x.com": baixar_video_twitter,
    "tiktok.com": baixar_video_tiktok,
    "facebook.com": baixar_video_facebook,
    "fb.watch": baixar_video_facebook,  # domínio de link curto do Facebook
}

# Nome de exibição de cada domínio, pra mensagens/telas (não afeta o dispatcher).
NOMES_AMIGAVEIS = {
    "kwai.com": "Kwai",
    "instagram.com": "Instagram",
    "twitter.com": "Twitter/X",
    "x.com": "Twitter/X",
    "tiktok.com": "TikTok",
    "facebook.com": "Facebook",
    "fb.watch": "Facebook",
}


def obter_dominio(url: str) -> str:
    """Extrai o domínio "limpo" do link, ex: https://www.tiktok.com/... -> tiktok.com."""
    netloc = urlparse(url).netloc.split(":")[0]
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or "dominio_desconhecido"


def baixar_video(url: str, pasta_destino: Path, ytdlp_module: Any = None, requests_module: Any = None) -> str:
    """Escolhe o downloader certo com base no domínio do link e baixa o
    vídeo cru como "original.mp4" dentro de `pasta_destino`.

    `ytdlp_module`/`requests_module`: injeta módulos alternativos (só pra
    teste — em uso normal, não passe nada).

    Devolve o caminho (string) do arquivo salvo.
    """
    dominio = obter_dominio(url)
    baixador = FONTES_SUPORTADAS.get(dominio)
    if baixador is None:
        raise RedesSociaisError(
            f"Fonte '{dominio}' ainda não é suportada por aqui. "
            f"Fontes disponíveis: {', '.join(sorted(set(NOMES_AMIGAVEIS.values())))} "
            "(pro YouTube, use a aba \"Cortar do YouTube\")."
        )
    if dominio == "kwai.com":
        return baixador(url, pasta_destino, requests_module=requests_module)
    return baixador(url, pasta_destino, ytdlp_module=ytdlp_module)


__all__ = [
    "RedesSociaisError",
    "FONTES_SUPORTADAS",
    "NOMES_AMIGAVEIS",
    "obter_dominio",
    "baixar_video",
    "baixar_video_kwai",
    "baixar_video_instagram",
    "baixar_video_twitter",
    "baixar_video_tiktok",
    "baixar_video_facebook",
    "verificar_ytdlp",
    "tem_audio",
]
