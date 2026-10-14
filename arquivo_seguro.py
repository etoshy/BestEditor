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
            os.replace(tmp, destino)
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
