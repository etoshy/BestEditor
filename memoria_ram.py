"""🧠 v84_313: controle de memória compartilhado — o lote de links, a retomada e a geração de voz usam este.

- liberar_pesados(): solta o Whisper e o Moondream (só se já estiverem carregados) e roda o coletor de lixo.
- espera_ram(): se a RAM livre estiver abaixo de CURTOS_RAM_MIN_GB (padrão 3 GB), espera (soltando modelos)
  até no máximo 15 min. Sem psutil, não faz nada.
"""
from __future__ import annotations

import gc
import os
import sys
import time
from typing import Callable, Optional


def liberar_pesados() -> None:
    """Solta modelos pesados que já estão carregados e a memória do Python. Nunca importa módulo nenhum só pra isso."""
    if "whisper_transcribe" in sys.modules:
        try:
            sys.modules["whisper_transcribe"].descarregar_modelos()
        except Exception:  # noqa: BLE001
            pass
    if "momentos_yt" in sys.modules:
        try:
            sys.modules["momentos_yt"].liberar_moondream()
        except Exception:  # noqa: BLE001
            pass
    gc.collect()


def espera_ram(prog: Optional[Callable[[str], None]] = None, limite_s: float = 900) -> None:
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return
    minimo = float(os.environ.get("CURTOS_RAM_MIN_GB") or 3.0) * 1024 ** 3
    t0 = time.time()
    while True:
        livre = psutil.virtual_memory().available
        if livre >= minimo or time.time() - t0 >= limite_s:
            break
        if prog:
            prog(f"⏸ pouca memória livre ({livre / 1024 ** 3:.1f} GB) — espero liberar antes de continuar")
        liberar_pesados()
        time.sleep(10)
    liberar_pesados()
