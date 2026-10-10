"""
legendas.py
============

Gera arquivos de legenda (.srt) a partir de palavras com timestamp
(a saída de `whisper_transcribe.transcribe_audio(..., word_timestamps=True)`,
achatada numa lista única de palavras).

Três formatos, pensados pros três jeitos mais comuns de usar a legenda
depois:

  - "tempo": divide em blocos de duração alvo (ex.: 3-8s) — pensado pra
    sincronizar com vídeo gerado em blocos (Veo/Shorts), onde cada bloco
    de legenda corresponde a um clipe.
  - "legenda" (padrão): quebra no RITMO da fala -- quando há uma pausa
    natural entre palavras, ou quando o bloco atingiria mais que o
    máximo de palavras configurado. Leitura confortável, é o formato
    recomendado pra a maioria dos casos.
  - "palavra": toda linha com a MESMA quantidade de palavras, não importa
    o ritmo da fala. Visual uniforme, mas pode cortar no meio de uma
    pausa natural.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

MODOS_VALIDOS = {"tempo", "legenda", "palavra"}

# pausa mínima entre o fim de uma palavra e o início da próxima pra
# considerar que é uma "pausa natural" de fala (usado só no modo "legenda")
LIMIAR_PAUSA_S = 0.35


class LegendaError(Exception):
    """Erro genérico ao montar a legenda (sem palavras, modo desconhecido etc.)."""


def _tempo_srt(segundos: float) -> str:
    segundos = max(0.0, segundos)
    total_ms = round(segundos * 1000)
    h, resto = divmod(total_ms, 3_600_000)
    m, resto = divmod(resto, 60_000)
    s, ms = divmod(resto, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fechar_bloco(palavras: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "start": palavras[0]["start"],
        "end": palavras[-1]["end"],
        "text": " ".join(p["word"] for p in palavras),
    }


def _achatar_palavras(segmentos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Os segmentos do whisper vêm agrupados por frase, cada um com sua
    própria lista `words`; aqui a gente achata tudo numa lista só de
    palavras em ordem, que é o formato que as três funções de quebra
    abaixo esperam."""
    palavras: List[Dict[str, Any]] = []
    for seg in segmentos:
        for w in seg.get("words", []):
            texto = w.get("word", "").strip()
            if texto:
                palavras.append({"word": texto, "start": float(w["start"]), "end": float(w["end"])})
    return palavras


def _modo_palavra(palavras: List[Dict[str, Any]], palavras_por_linha: int) -> List[Dict[str, Any]]:
    palavras_por_linha = max(1, int(palavras_por_linha))
    return [
        _fechar_bloco(palavras[i:i + palavras_por_linha])
        for i in range(0, len(palavras), palavras_por_linha)
    ]


def _modo_legenda(palavras: List[Dict[str, Any]], max_palavras: int, limiar_pausa: float = LIMIAR_PAUSA_S) -> List[Dict[str, Any]]:
    max_palavras = max(1, int(max_palavras))
    blocos: List[Dict[str, Any]] = []
    atual: List[Dict[str, Any]] = []
    for w in palavras:
        if atual:
            pausa = w["start"] - atual[-1]["end"]
            if pausa >= limiar_pausa or len(atual) >= max_palavras:
                blocos.append(_fechar_bloco(atual))
                atual = []
        atual.append(w)
    if atual:
        blocos.append(_fechar_bloco(atual))
    return blocos


def _modo_tempo(palavras: List[Dict[str, Any]], duracao_alvo: float) -> List[Dict[str, Any]]:
    duracao_alvo = max(0.5, float(duracao_alvo))
    blocos: List[Dict[str, Any]] = []
    atual: List[Dict[str, Any]] = []
    inicio_bloco = None
    for w in palavras:
        if inicio_bloco is None:
            inicio_bloco = w["start"]
        atual.append(w)
        if w["end"] - inicio_bloco >= duracao_alvo:
            blocos.append(_fechar_bloco(atual))
            atual = []
            inicio_bloco = None
    if atual:
        blocos.append(_fechar_bloco(atual))
    return blocos


def blocos_para_srt(blocos: List[Dict[str, Any]]) -> str:
    linhas = []
    for i, b in enumerate(blocos, start=1):
        linhas.append(str(i))
        linhas.append(f"{_tempo_srt(b['start'])} --> {_tempo_srt(b['end'])}")
        linhas.append(b["text"])
        linhas.append("")
    return "\n".join(linhas)


def gerar_srt(
    segmentos_com_palavras: List[Dict[str, Any]],
    modo: str = "legenda",
    duracao_alvo_s: float = 5.0,
    max_palavras: int = 5,
    palavras_por_linha: int = 5,
) -> str:
    """Monta o conteúdo de um .srt a partir dos segmentos que o whisper
    devolveu com `word_timestamps=True` (cada segmento com uma lista
    `words`). `modo` escolhe a estratégia de quebra -- ver o docstring
    do módulo. Devolve o conteúdo pronto pra escrever num arquivo .srt
    (já com as quebras de linha certas, sem precisar de mais nada)."""
    if modo not in MODOS_VALIDOS:
        raise LegendaError(f"Modo de legenda desconhecido: {modo!r} (válidos: {sorted(MODOS_VALIDOS)})")

    palavras = _achatar_palavras(segmentos_com_palavras)
    if not palavras:
        raise LegendaError(
            "Não achei palavras com timestamp na transcrição -- confira se "
            "word_timestamps=True foi passado pro whisper."
        )

    if modo == "tempo":
        blocos = _modo_tempo(palavras, duracao_alvo_s)
    elif modo == "palavra":
        blocos = _modo_palavra(palavras, palavras_por_linha)
    else:
        blocos = _modo_legenda(palavras, max_palavras)

    return blocos_para_srt(blocos)


# --------------------------------------------------------------------- #
# Caminho inverso: ler um .srt já pronto e devolver segmentos no mesmo
# formato que whisper_transcribe.transcribe_audio() devolve -- usado
# quando a pessoa já tem a legenda (ex: baixou o .zip do Gerador de Voz,
# que tem áudio + .srt) e quer pular a transcrição inteira.
# --------------------------------------------------------------------- #

_TEMPO_SRT_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _tempo_srt_para_segundos(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000  # "5" = 500ms, "05" = 50ms


def parse_srt(texto: str) -> List[Dict[str, Any]]:
    """Lê o conteúdo de um .srt (o que `gerar_srt()` escreve, ou
    qualquer .srt no formato padrão) e devolve segmentos no MESMO
    formato que `whisper_transcribe.transcribe_audio()` devolve --
    `[{"start": float, "end": float, "text": str}, ...]`, prontos pra
    usar direto em `build_prompt()` e no resto do pipeline, sem
    precisar transcrever de novo.

    Tolerante a variações comuns: número do bloco ausente, linhas em
    branco extras, BOM no início do arquivo, quebra de linha \\r\\n.
    Descarta blocos sem texto (linha de tempo sozinha). Os segmentos
    saem ordenados por `start`, mesmo que o arquivo não estivesse.
    """
    if texto is None:
        raise LegendaError("Conteúdo de .srt vazio.")
    texto = texto.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not texto:
        raise LegendaError("Arquivo .srt vazio -- nada pra usar como transcrição.")

    blocos = re.split(r"\n\s*\n", texto)
    segmentos: List[Dict[str, Any]] = []
    for bloco in blocos:
        linhas = [l for l in bloco.split("\n") if l.strip() != ""]
        if not linhas:
            continue
        # a primeira linha costuma ser o número do bloco ("1", "2"...) --
        # mas é opcional aqui: se a primeira linha já for a marcação de
        # tempo, não exige o número antes dela.
        indice_tempo = 1 if re.fullmatch(r"\d+", linhas[0].strip()) else 0
        if indice_tempo >= len(linhas):
            continue
        m = _TEMPO_SRT_RE.match(linhas[indice_tempo].strip())
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = m.groups()
        start = _tempo_srt_para_segundos(h1, m1, s1, ms1)
        end = _tempo_srt_para_segundos(h2, m2, s2, ms2)
        texto_bloco = " ".join(linhas[indice_tempo + 1:]).strip()
        if not texto_bloco:
            continue  # bloco só com tempo, sem texto -- não vira segmento
        segmentos.append({"start": start, "end": end, "text": texto_bloco})

    if not segmentos:
        raise LegendaError(
            "Não encontrei nenhum bloco válido de legenda nesse .srt (esperava blocos "
            "\"00:00:01,000 --> 00:00:03,000\" com texto embaixo)."
        )
    segmentos.sort(key=lambda s: s["start"])
    return segmentos
