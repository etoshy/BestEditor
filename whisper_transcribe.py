"""
whisper_transcribe.py
=======================

Transcreve um arquivo de áudio com o Whisper (local, sem precisar de
chave de API) e devolve os segmentos com timestamps, no formato que
`prompt_builder.build_prompt()` espera.

O modelo é carregado uma vez e reaproveitado entre chamadas (carregar o
modelo é a parte mais lenta — a partir da segunda transcrição fica bem
mais rápido).

Uso
----
    from whisper_transcribe import transcribe_audio

    segments = transcribe_audio("narracao.mp3")
    # [{"start": 0.0, "end": 3.2, "text": "..."}, ...]
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

_MODEL_CACHE: Dict[tuple, Any] = {}

# 🧹 v84_262: o modelo do Whisper ficava na memória PARA SEMPRE depois da 1ª transcrição (centenas de MB a alguns GB).
# Agora, parado por WHISPER_OCIOSO_S segundos (padrão 1 min) e sem nenhuma transcrição rodando, ele é descarregado.
import threading as _threading
import time as _time

_USO = {"ultimo": 0.0, "rodando": 0, "vigia": False}
_LOCK = _threading.RLock()


def _ocioso_s() -> float:
    try:
        return float(os.environ.get("WHISPER_OCIOSO_S") or 60)
    except ValueError:
        return 60.0


def descarregar_modelos() -> bool:
    """Tira o(s) modelo(s) do Whisper da memória (RAM e VRAM). Devolve True se havia algum carregado."""
    with _LOCK:
        if not _MODEL_CACHE or _USO["rodando"]:
            return False
        _MODEL_CACHE.clear()
    import gc
    gc.collect()
    try:
        import sys
        if "torch" in sys.modules:  # só limpa a VRAM se o torch já estiver carregado (nunca importa só pra isso)
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return True


def _vigia_ocioso() -> None:
    while True:
        _time.sleep(30)
        with _LOCK:
            vazio = not _MODEL_CACHE
            parado = not _USO["rodando"] and _time.time() - _USO["ultimo"] > _ocioso_s()
        if vazio:
            _USO["vigia"] = False
            return
        if parado:
            descarregar_modelos()


def _marcar_uso() -> None:
    _USO["ultimo"] = _time.time()
    if not _USO["vigia"] and _ocioso_s() > 0:
        _USO["vigia"] = True
        _threading.Thread(target=_vigia_ocioso, daemon=True, name="whisper-ocioso").start()


class TranscriptionError(Exception):
    """Erro genérico de transcrição (arquivo inválido, modelo não carregou, etc.)."""


def detect_best_device() -> str:
    """Detecta automaticamente se há uma GPU (CUDA) disponível na
    máquina — devolve "cuda" se sim, "cpu" caso contrário. Assim a
    pessoa não precisa saber o nome/modelo da placa de vídeo instalada:
    o site descobre sozinho.
    """
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _resolve_device(device: str) -> str:
    """"auto" (padrão) detecta sozinho via `detect_best_device()`;
    "gpu" é aceito como sinônimo de "cuda" (é o termo que aparece na
    interface); "cpu" força processamento pela CPU mesmo se houver GPU.
    """
    if device == "auto":
        return detect_best_device()
    if device == "gpu":
        return "cuda"
    return device


def _get_model(model_size: str = "base", device: str = "auto"):
    """Carrega (ou reaproveita) o modelo Whisper do tamanho e dispositivo
    pedidos — o cache é por (tamanho, dispositivo), já que um modelo
    carregado na GPU e outro na CPU são objetos diferentes.

    Tamanhos disponíveis, do mais rápido/leve ao mais lento/preciso:
    "tiny", "base", "small", "medium", "large". "base" é um bom
    equilíbrio pra narração em português; "small" ou "medium" dão mais
    precisão se a máquina aguentar.

    device: "auto" (padrão, detecta GPU sozinho), "cpu", ou "gpu"/"cuda".
        Se a GPU pedida falhar ao carregar (driver quebrado, sem VRAM
        suficiente, etc.), cai pra CPU automaticamente em vez de travar
        a transcrição inteira — mais lento, mas funciona.
    """
    resolved_device = _resolve_device(device)
    cache_key = (model_size, resolved_device)
    _marcar_uso()

    if cache_key not in _MODEL_CACHE:
        try:
            import whisper  # import tardio: só precisa disso se for transcrever de verdade
        except ImportError as exc:
            raise TranscriptionError(
                "O pacote 'openai-whisper' não está instalado. Rode: "
                "pip install openai-whisper --break-system-packages"
            ) from exc

        try:
            _MODEL_CACHE[cache_key] = whisper.load_model(model_size, device=resolved_device)
        except Exception as exc:  # noqa: BLE001
            if resolved_device == "cpu":
                raise TranscriptionError(f"Falha ao carregar o modelo Whisper (tamanho '{model_size}'): {exc}") from exc
            # GPU pedida mas falhou (driver, VRAM insuficiente, etc.) —
            # cai pra CPU em vez de travar a transcrição inteira.
            cpu_key = (model_size, "cpu")
            if cpu_key not in _MODEL_CACHE:
                _MODEL_CACHE[cpu_key] = whisper.load_model(model_size, device="cpu")
            _MODEL_CACHE[cache_key] = _MODEL_CACHE[cpu_key]

    return _MODEL_CACHE[cache_key]


def transcribe_audio(
    audio_path: str,
    model_size: str = "base",
    language: Optional[str] = None,
    word_timestamps: bool = False,
    device: str = "auto",
    info: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Transcreve o áudio e devolve a lista de segmentos com timestamps.

    audio_path: caminho do arquivo de áudio (mp3, wav, m4a, etc. — o
        Whisper usa ffmpeg por trás, então aceita os formatos que o
        ffmpeg do sistema suportar).
    model_size: ver `_get_model()`.
    language: força um idioma (ex: "pt") em vez de deixar o Whisper
        detectar sozinho — útil se a detecção automática errar.
    device: "auto" (padrão, detecta GPU automaticamente), "cpu", ou
        "gpu" — ver `_get_model()`.
    word_timestamps: se True, cada segmento também vem com uma lista
        `"words"` — timestamp de início/fim de CADA palavra falada, não
        só do trecho inteiro. Usado pra gerar legendas estilo karaokê
        (destaca uma palavra de cada vez, no ritmo da fala). Desligado
        por padrão porque deixa a transcrição um pouco mais lenta e a
        maioria dos usos não precisa desse nível de detalhe.

    Retorna: [{"start": float, "end": float, "text": str}, ...] — com
    `"words": [{"word": str, "start": float, "end": float}, ...]`
    adicional em cada segmento quando `word_timestamps=True`.
    """
    if not os.path.exists(audio_path):
        raise TranscriptionError(f"Arquivo de áudio não encontrado: {audio_path}")

    with _LOCK:
        _USO["rodando"] += 1
    try:
        model = _get_model(model_size, device=device)

        kwargs: Dict[str, Any] = {"verbose": False}
        if language:
            kwargs["language"] = language
        if word_timestamps:
            kwargs["word_timestamps"] = True

        try:
            result = model.transcribe(audio_path, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError(f"Falha ao transcrever '{audio_path}': {exc}") from exc
    finally:
        with _LOCK:
            _USO["rodando"] -= 1
        _marcar_uso()

    if info is not None:  # quem chama quer saber o idioma detectado (\"Automático\")
        info["language"] = result.get("language") or language
    segments = []
    for seg in result.get("segments", []):
        text = seg["text"].strip()
        if not text:
            continue
        entry = {"start": float(seg["start"]), "end": float(seg["end"]), "text": text}
        if word_timestamps:
            entry["words"] = [
                {"word": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])}
                for w in seg.get("words", [])
                if w.get("word", "").strip()
            ]
        segments.append(entry)

    if not segments:
        raise TranscriptionError(
            "A transcrição não encontrou nenhuma fala no áudio. Confira se o arquivo "
            "não está corrompido, mudo, ou em um formato que o ffmpeg não reconhece."
        )

    return segments


def get_audio_duration(audio_path: str) -> float:
    """Duração total do áudio em segundos, via ffprobe (mais rápido que
    transcrever tudo só pra saber a duração).
    """
    import json
    import subprocess

    if not os.path.exists(audio_path):
        raise TranscriptionError(f"Arquivo de áudio não encontrado: {audio_path}")

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", audio_path],
            capture_output=True, text=True, timeout=30, check=True,
        )
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])
    except (subprocess.SubprocessError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise TranscriptionError(f"Não consegui ler a duração de '{audio_path}': {exc}") from exc
