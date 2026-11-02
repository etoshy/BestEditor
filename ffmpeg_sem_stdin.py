"""🧯 v84_329: ffmpeg/ffprobe NUNCA herdam o teclado do console.

No Windows, o ffmpeg rodado pelo site (sem `stdin=` no subprocess) herda o stdin da janela do PowerShell e fica
olhando o teclado ("aperte q pra sair"). Com várias tarefas ao mesmo tempo (lote por etapa, exportação, voz) ele pode
travar esperando o console — aí até um silêncio de 0,12 s estoura o tempo ("timed out after 60 seconds").
Importar este módulo faz todo `subprocess.Popen/run` de ffmpeg/ffprobe sem `stdin` (nem `input=`) usar DEVNULL.
Quem passa `stdin=PIPE` (ex.: a câmera mandando quadros) continua igual.
"""
from __future__ import annotations

import os
import subprocess

_NOMES = ("ffmpeg", "ffprobe", "ffplay")


def _eh_ffmpeg(args) -> bool:
    try:
        prog = args[0] if isinstance(args, (list, tuple)) else str(args).strip().split()[0]
    except (IndexError, TypeError):
        return False
    nome = os.path.basename(str(prog)).lower()
    return any(nome == n or nome == n + ".exe" for n in _NOMES)


if not getattr(subprocess.Popen, "_sem_stdin_ffmpeg", False):
    _init_original = subprocess.Popen.__init__

    def _init(self, args, *a, **kw):  # noqa: ANN001
        if "stdin" not in kw and len(a) < 3 and _eh_ffmpeg(args):  # (stdin é o 4º posicional do Popen)
            kw["stdin"] = subprocess.DEVNULL
        _init_original(self, args, *a, **kw)

    subprocess.Popen.__init__ = _init
    subprocess.Popen._sem_stdin_ffmpeg = True
