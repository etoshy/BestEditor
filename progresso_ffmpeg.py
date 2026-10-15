"""
progresso_ffmpeg.py — quanto falta de cada passe do ffmpeg (v84_114)
====================================================================

As etapas finais da montagem (juntar, filtro, destaques, gráficos, legendas, qualidade…) são passes LONGOS do ffmpeg
sobre o vídeo inteiro — num vídeo de 1 hora, cada um leva vários minutos e a tela ficava parada em "destaques
(208/208)". Aqui o ffmpeg roda com `-progress pipe:1`, que diz até onde ele já chegou no vídeo (`out_time`), e isso
vira a fração da etapa.

Uso (na montagem):
    with progresso_ffmpeg.acompanhar(lambda frac, detalhe: ..., duracao_do_video):
        ...  # qualquer ffmpeg rodado por `rodar()` (qualidade_export.executar usa) avisa o andamento
        with progresso_ffmpeg.parte(2, 5, "lote 2/5 dos fundos"):  # divide a etapa em pedaços
            ...

Fora de um `acompanhar`, `rodar()` é igual ao `subprocess.run(..., capture_output=True, text=True)` de sempre.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional

_local = threading.local()
_RE_T = re.compile(r"^(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)$")


def _pilha() -> List[Dict[str, Any]]:
    p = getattr(_local, "pilha", None)
    if p is None:
        p = []
        _local.pilha = p
    return p


def ativo() -> bool:
    return bool(_pilha())


@contextmanager
def acompanhar(cb: Callable[[float, str], None], duracao: Optional[float]):
    """cb(fração 0–1 da etapa, detalhe) — chamado no máximo ~2× por segundo."""
    anterior = list(_pilha())
    _local.pilha = [{"cb": cb, "dur": float(duracao or 0), "ini": 0.0, "fim": 1.0, "rot": "", "ult": 0.0}]
    try:
        yield
    finally:
        _local.pilha = anterior


@contextmanager
def parte(k: int, n: int, rotulo: str = "", duracao: Optional[float] = None):
    """O pedaço k (1..n) da etapa atual (ex.: o lote 2 de 5)."""
    p = _pilha()
    if not p:
        yield
        return
    topo = p[-1]
    larg = (topo["fim"] - topo["ini"]) / max(1, n)
    p.append(dict(topo, ini=topo["ini"] + larg * (k - 1), fim=topo["ini"] + larg * k,
                  rot=" · ".join(x for x in (topo["rot"], rotulo) if x), dur=float(duracao or topo["dur"]), ult=0.0))
    try:
        avisar(0.0, forcar=True)
        yield
    finally:
        p.pop()


def avisar(frac: float, forcar: bool = False) -> None:
    p = _pilha()
    if not p:
        return
    topo = p[-1]
    agora = time.monotonic()
    if not forcar and agora - topo.get("ult", 0.0) < 0.5:
        return
    topo["ult"] = agora
    total = topo["ini"] + max(0.0, min(1.0, frac)) * (topo["fim"] - topo["ini"])
    try:
        p[0]["cb"](total, topo["rot"])
    except Exception:  # noqa: BLE001 — quem mostra o progresso nunca derruba a montagem
        pass


def _segundos(txt: str) -> Optional[float]:
    m = _RE_T.match(str(txt or "").strip())
    if not m:
        return None
    partes = [x for x in m.groups() if x is not None]
    seg = 0.0
    for x in partes:
        seg = seg * 60 + float(x)
    return seg


def _duracao_do_cmd(cmd: List[str]) -> Optional[float]:
    """O `-t` de saída (o último antes do arquivo) — senão a duração da etapa."""
    for k in range(len(cmd) - 2, 0, -1):
        if cmd[k] == "-t":
            return _segundos(cmd[k + 1])
    return None


def rodar(cmd: List[str], timeout: Optional[float] = None, **kw) -> "subprocess.CompletedProcess":
    """subprocess.run(cmd, capture_output=True, text=True); dentro de `acompanhar`, com o andamento do ffmpeg."""
    eh_ffmpeg = bool(cmd) and os.path.basename(str(cmd[0])).lower() in ("ffmpeg", "ffmpeg.exe")
    if not ativo() or not eh_ffmpeg or "-progress" in cmd:
        kw.setdefault("encoding", "utf-8")
        kw.setdefault("errors", "replace")
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    dur = _duracao_do_cmd(cmd) or _pilha()[-1]["dur"]
    cmd2 = [cmd[0], "-progress", "pipe:1", "-nostats"] + list(cmd[1:])
    proc = subprocess.Popen(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", **{k: v for k, v in kw.items() if k not in ("encoding", "errors", "check")})
    erros: List[str] = []
    t_err = threading.Thread(target=lambda: erros.append(proc.stderr.read()), daemon=True)
    t_err.start()
    estourou = threading.Event()
    timer = None
    if timeout:
        def _matar():
            estourou.set()
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        timer = threading.Timer(float(timeout), _matar)
        timer.daemon = True
        timer.start()
    try:
        for linha in proc.stdout:
            chave, _, valor = linha.strip().partition("=")
            if chave in ("out_time_us", "out_time_ms") and dur:
                try:
                    avisar(max(0, int(valor)) / 1_000_000 / dur)
                except ValueError:
                    pass
            elif chave == "progress" and valor == "end":
                avisar(1.0, forcar=True)
        rc = proc.wait()
    finally:
        if timer is not None:
            timer.cancel()
    t_err.join(5)
    if estourou.is_set():
        raise subprocess.TimeoutExpired(cmd, timeout, stderr="".join(erros))
    return subprocess.CompletedProcess(cmd, rc, "", "".join(erros))


def ramo() -> Callable[[float, str], None]:
    """Pra trabalho em OUTRAS threads (pedaços em paralelo): uma função (fração 0–1, detalhe) que avisa a barra da
    etapa atual DESTA thread (no pedaço dela, se estiver dentro de um `parte`). Sem `acompanhar`, não faz nada."""
    p = _pilha()
    if not p:
        return lambda f, d="": None
    topo, cb = dict(p[-1]), p[0]["cb"]
    trava = threading.Lock()
    ult = [0.0]

    def _avisa(frac: float, detalhe: str = "") -> None:
        agora = time.monotonic()
        with trava:
            if frac < 1.0 and agora - ult[0] < 0.5:
                return
            ult[0] = agora
        total = topo["ini"] + max(0.0, min(1.0, frac)) * (topo["fim"] - topo["ini"])
        try:
            cb(total, " · ".join(x for x in (topo["rot"], detalhe) if x))
        except Exception:  # noqa: BLE001
            pass
    return _avisa
