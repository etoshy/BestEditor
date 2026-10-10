"""
_ytdlp_base.py
==============

Instagram, Twitter/X, TikTok e Facebook baixam do mesmo jeito (yt-dlp
resolve tudo), só muda o link/cabeçalhos. Em vez de repetir o código em
cada módulo, cada um chama `baixar_com_ytdlp()` daqui.

Isso NÃO é uma fonte por si só (não tem entrada em `FONTES_SUPORTADAS`) —
é só a "engine" usada por instagram.py, twitter.py, tiktok.py e facebook.py.
"""
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


def baixar_com_ytdlp(
    url: str,
    pasta_destino: Path,
    cookies_path: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    extra_opcoes: Optional[Dict[str, Any]] = None,
    ytdlp_module: Any = None,
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

    opcoes: Dict[str, Any] = {
        "outtmpl": saida_template,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "http_headers": headers or HEADERS_PADRAO,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    if cookies_path:
        opcoes["cookiefile"] = cookies_path
    if extra_opcoes:
        opcoes.update(extra_opcoes)

    try:
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            ydl.download([url])
    except RedesSociaisError:
        raise
    except Exception as exc:  # noqa: BLE001
        mensagem_original = str(exc)
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

    caminho_final = pasta_destino / "original.mp4"
    if not caminho_final.exists():
        raise RedesSociaisError(
            f"yt-dlp terminou sem erro, mas não encontrei '{caminho_final}'. "
            "Confira o conteúdo da pasta — pode ter salvo com outra extensão."
        )
    return str(caminho_final)
