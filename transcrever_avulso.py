"""
transcrever_avulso.py
======================

Ferramenta AVULSA (fora do pipeline de "Roteiro para Áudio"): baixa um
vídeo de qualquer fonte suportada — YouTube, TikTok, Twitter/X,
Instagram, Facebook ou Kwai — sempre na maior qualidade disponível, ou
usa um arquivo já enviado pelo navegador, e opcionalmente transcreve a
fala com Whisper (o mesmo motor que o resto do site já usa via
`whisper_transcribe.py`), detectando o idioma original e dividindo em
trechos com início/fim.

Uso:
    from transcrever_avulso import processar

    resultado = processar(saida_dir="pasta/", url="https://...", modo="transcrever")
    resultado = processar(saida_dir="pasta/", arquivo_path="video.mp4", modo="baixar")
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional

MODOS_VALIDOS = ("baixar", "transcrever")
ALTURA_MINIMA_RECOMENDADA = 720


class TranscreverAvulsoError(Exception):
    """Falha ao baixar e/ou transcrever um vídeo avulso."""


def _log(on_log: Optional[Callable[[str], None]], linha: str) -> None:
    if on_log:
        on_log(linha)


def _dimensoes_do_video(caminho: str) -> Optional[tuple]:
    """(largura, altura) do vídeo via ffprobe, ou None se não der pra ler."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height", "-of", "csv=p=0:s=x", str(caminho)],
            capture_output=True, text=True, timeout=60,
        )
        largura, altura = (int(x) for x in r.stdout.strip().split("x", 1))
        return largura, altura
    except Exception:  # noqa: BLE001
        return None


def _extrair_audio(video_path: str, audio_path: str) -> None:
    resultado = subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path],
        capture_output=True, text=True,
    )
    if resultado.returncode != 0 or not os.path.exists(audio_path):
        raise TranscreverAvulsoError(
            f"Falha ao extrair o áudio do vídeo (ffmpeg): {(resultado.stderr or '')[-500:]}"
        )


def _escrever_srt(segmentos: List[Dict[str, Any]], caminho: str) -> None:
    def _tempo_srt(segundos: float) -> str:
        segundos = max(0.0, segundos)
        h, resto = divmod(segundos, 3600)
        m, s = divmod(resto, 60)
        ms = round((s - int(s)) * 1000)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"

    linhas = []
    for i, seg in enumerate(segmentos, start=1):
        linhas.append(str(i))
        linhas.append(f"{_tempo_srt(seg['start'])} --> {_tempo_srt(seg['end'])}")
        linhas.append(seg["text"].strip())
        linhas.append("")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))


def baixar_de_qualquer_fonte(
    url: str, saida_dir: str, destino_nome: str = "video.mp4",
    max_height: Optional[int] = None, on_log: Optional[Callable[[str], None]] = None,
    ytdlp_module: Any = None, requests_module: Any = None,
) -> str:
    """Baixa `url` (qualquer fonte suportada, YouTube incluso) pra dentro
    de `saida_dir`, sempre salvando como `destino_nome`. Devolve o
    caminho final. `max_height` só se aplica a downloads do YouTube (as
    outras fontes já baixam sempre na maior qualidade disponível, sem
    teto configurável)."""
    from youtube_clipper import YoutubeClipperError

    destino_final = os.path.join(saida_dir, destino_nome)
    os.makedirs(saida_dir, exist_ok=True)

    import redes_sociais
    dominio = redes_sociais.obter_dominio(url)
    eh_youtube = dominio in ("youtube.com", "youtu.be", "m.youtube.com")

    if eh_youtube:
        _log(on_log, "Baixando do YouTube, na maior qualidade disponível...")
        import youtube_clipper
        qualidade = youtube_clipper.QUALIDADE_PADRAO
        if max_height:
            # a qualidade mais próxima, sem passar do teto pedido
            candidatas = [q for q in youtube_clipper.QUALIDADES if q not in ("melhor",)]
            alturas = sorted((int(q.rstrip("p")), q) for q in candidatas if q.rstrip("p").isdigit())
            aceitas = [q for altura, q in alturas if altura <= max_height]
            if aceitas:
                qualidade = aceitas[-1]
        try:
            info = youtube_clipper.baixar_video(url, saida_dir, qualidade=qualidade, ytdlp_module=ytdlp_module)
        except YoutubeClipperError as exc:
            raise TranscreverAvulsoError(str(exc)) from exc
        caminho_baixado = info["caminho"]
    else:
        nome_amigavel = redes_sociais.NOMES_AMIGAVEIS.get(dominio, dominio)
        _log(on_log, f"Baixando de {nome_amigavel}, na maior qualidade disponível...")
        try:
            caminho_baixado = redes_sociais.baixar_video(
                url, saida_dir, ytdlp_module=ytdlp_module, requests_module=requests_module,
            )
        except redes_sociais.RedesSociaisError as exc:
            raise TranscreverAvulsoError(str(exc)) from exc

    if os.path.abspath(caminho_baixado) != os.path.abspath(destino_final):
        shutil.move(caminho_baixado, destino_final)
    return destino_final


def processar(
    saida_dir: str,
    url: Optional[str] = None,
    arquivo_path: Optional[str] = None,
    modo: str = "transcrever",
    whisper_model: str = "base",
    idioma: Optional[str] = None,
    device: str = "auto",
    max_height: Optional[int] = None,
    on_log: Optional[Callable[[str], None]] = None,
    ytdlp_module: Any = None,
    requests_module: Any = None,
    apagar_video: bool = False,
) -> Dict[str, Any]:
    """Baixa (de `url`) ou usa (`arquivo_path`) um vídeo e, se
    `modo="transcrever"` (padrão), também transcreve a fala com Whisper.
    `modo="baixar"` só baixa/copia o vídeo, sem transcrever.

    Exatamente um entre `url`/`arquivo_path` deve ser informado.

    Devolve `{"modo", "video", "largura", "altura", "aviso_resolucao_baixa",
    "idioma", "total_segmentos", "segmentos", "arquivo_texto",
    "arquivo_srt", "arquivo_segmentos"}` — as últimas 6 chaves só
    aparecem quando `modo="transcrever"`. `idioma` é o idioma FORÇADO
    (parâmetro `idioma`), quando informado — a detecção automática do
    Whisper não é exposta por `whisper_transcribe.transcribe_audio`,
    então fica `None` quando ninguém força um idioma.
    """
    if modo not in MODOS_VALIDOS:
        raise TranscreverAvulsoError(f"Modo {modo!r} inválido — use 'baixar' ou 'transcrever'.")
    if bool(url) == bool(arquivo_path):
        raise TranscreverAvulsoError("Informe exatamente um: 'url' (link do vídeo) ou 'arquivo_path' (arquivo enviado).")

    os.makedirs(saida_dir, exist_ok=True)
    video_final = os.path.join(saida_dir, "video.mp4")

    if arquivo_path:
        _log(on_log, f"Usando o arquivo enviado: {arquivo_path}")
        if not os.path.exists(arquivo_path):
            raise TranscreverAvulsoError(f"Arquivo não encontrado: {arquivo_path}")
        if os.path.abspath(arquivo_path) != os.path.abspath(video_final):
            # v84_384: o envio já está na pasta do trabalho — MOVE em vez de copiar (antes ficava 2× o tamanho no disco)
            if os.path.dirname(os.path.abspath(arquivo_path)) == os.path.abspath(saida_dir):
                os.replace(arquivo_path, video_final)
            else:
                shutil.copy(arquivo_path, video_final)
    else:
        video_final = baixar_de_qualquer_fonte(
            url, saida_dir, max_height=max_height, on_log=on_log,
            ytdlp_module=ytdlp_module, requests_module=requests_module,
        )

    if not os.path.exists(video_final):
        raise TranscreverAvulsoError("O download terminou, mas o arquivo de vídeo não foi encontrado.")
    _log(on_log, f"Vídeo pronto em {video_final}")

    dimensoes = _dimensoes_do_video(video_final)
    aviso_resolucao_baixa = bool(dimensoes and dimensoes[1] < ALTURA_MINIMA_RECOMENDADA)
    if aviso_resolucao_baixa:
        _log(on_log, f"[AVISO] O vídeo está em baixa resolução ({dimensoes[0]}x{dimensoes[1]}).")

    resultado: Dict[str, Any] = {
        "modo": modo, "video": "video.mp4",
        "largura": dimensoes[0] if dimensoes else None,
        "altura": dimensoes[1] if dimensoes else None,
        "aviso_resolucao_baixa": aviso_resolucao_baixa,
    }

    if modo == "transcrever":
        from whisper_transcribe import transcribe_audio

        audio_path = os.path.join(saida_dir, "audio.wav")
        _log(on_log, "Extraindo áudio...")
        _extrair_audio(video_final, audio_path)

        _log(on_log, "Transcrevendo (Whisper)...")
        segmentos = transcribe_audio(audio_path, model_size=whisper_model, language=idioma, device=device)

        txt_out = os.path.join(saida_dir, "transcricao.txt")
        srt_out = os.path.join(saida_dir, "transcricao.srt")
        segmentos_out = os.path.join(saida_dir, "transcricao.json")
        with open(txt_out, "w", encoding="utf-8") as f:
            f.write("\n".join(s["text"].strip() for s in segmentos))
        _escrever_srt(segmentos, srt_out)
        with open(segmentos_out, "w", encoding="utf-8") as f:
            json.dump(segmentos, f, ensure_ascii=False, indent=2)

        idioma_detectado = idioma  # a função de transcrição não expõe o idioma
        # detectado automaticamente quando `idioma` não é forçado — só o texto.
        resultado.update({
            "idioma": idioma_detectado,
            "total_segmentos": len(segmentos),
            "segmentos": segmentos,
            "arquivo_texto": "transcricao.txt",
            "arquivo_srt": "transcricao.srt",
            "arquivo_segmentos": "transcricao.json",
        })
        os.remove(audio_path)  # só precisava pra transcrever, não pra guardar
        if apagar_video:  # 🗑 v84_384: fica só a transcrição (txt, srt, json)
            try:
                tam = os.path.getsize(video_final)
                os.remove(video_final)
                resultado.update(video=None, video_apagado=True)
                _log(on_log, f"🗑 Vídeo apagado ({tam / 1e6:.0f} MB liberados) — ficou só a transcrição.")
            except OSError as exc:
                _log(on_log, f"(não consegui apagar o vídeo: {exc})")
        _log(on_log, "Concluído.")
    else:
        _log(on_log, "Concluído (só download).")

    return resultado
