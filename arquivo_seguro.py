"""
💾 arquivo_seguro.py — troca o arquivo salvo SEM dar "[WinError 5] Acesso negado" (v84_99)
=========================================================================================

No Windows, `os.replace(tmp, destino)` falha com PermissionError (WinError 5 / 32) quando, NAQUELE instante, outro
processo ou outra thread está com o destino aberto: o antivírus/Windows Defender escaneando o .json recém-gravado, o
indexador de busca, o OneDrive/Google Drive sincronizando a pasta, ou a própria página lendo o projeto enquanto a 🤖 IA
salva uma parte. É sempre passageiro — então tenta de novo por alguns segundos e, se ainda assim não der, grava direto
no destino (sem o arquivo temporário) em vez de perder o trabalho.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

TENTATIVAS = 25      # ~5 s no total
ESPERA = 0.05        # cresce até 0.4 s


def trocar(tmp: str, destino: str) -> None:
    """os.replace com novas tentativas (Windows: arquivo aberto por outro programa) e plano B: copiar o conteúdo."""
    espera = ESPERA
    erro: Exception = OSError("?")
    for _ in range(TENTATIVAS):
        try:
            (_REPLACE_ORIGINAL if os.replace is _replace_com_retentativa else os.replace)(tmp, destino)  # (sem somar tentativas)
            return
        except PermissionError as exc:  # WinError 5 (acesso negado) / 32 (em uso)
            erro = exc
        except OSError as exc:
            if getattr(exc, "winerror", None) not in (5, 32, 33):
                raise
            erro = exc
        time.sleep(espera)
        espera = min(0.4, espera * 1.5)
    # plano B: escreve por cima (o destino pode estar aberto pra leitura, mas não travado pra escrita)
    try:
        with open(tmp, "rb") as f:
            dados = f.read()
        with open(destino, "wb") as f:
            f.write(dados)
    except OSError:
        raise erro
    try:
        os.remove(tmp)
    except OSError:
        pass


def gravar_json(caminho: str, dados: Any, indent: int = 2) -> None:
    """Grava o JSON num temporário com nome único e troca pelo destino (atômico; à prova de antivírus no Windows)."""
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    tmp = f"{caminho}.{uuid.uuid4().hex[:6]}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=indent)
        trocar(tmp, caminho)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


_REPLACE_ORIGINAL = os.replace


def _replace_com_retentativa(src, dst, *a, **k):
    """🔒 v84_350: o os.replace de TODO o projeto, no Windows, tenta de novo (~5 s) quando o destino está aberto por outro
    programa (antivírus, OneDrive, indexador, a página lendo) — antes, só quem chamava `trocar()` tinha isso."""
    espera, ultima = ESPERA, None
    for _ in range(TENTATIVAS):
        try:
            return _REPLACE_ORIGINAL(src, dst, *a, **k)
        except PermissionError as exc:
            ultima = exc
        except OSError as exc:
            if getattr(exc, "winerror", None) not in (5, 32, 33):
                raise
            ultima = exc
        time.sleep(espera)
        espera = min(0.4, espera * 1.5)
    raise ultima  # type: ignore[misc]


def instalar_no_windows() -> bool:
    """Chamado uma vez no começo do app (só no Windows — no Linux/Mac o os.replace já não sofre disso)."""
    import sys
    if not sys.platform.startswith("win") or os.replace is _replace_com_retentativa:
        return False
    os.replace = _replace_com_retentativa  # type: ignore[assignment]
    return True
