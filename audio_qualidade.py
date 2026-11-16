"""
🔊 v84_400 — a checagem técnica de qualquer áudio que entra no sound design (Pixabay, MyInstants…):

  • loudness integrada (LUFS) e pico;
  • ESTOURADO? (clipping: amostras grudadas no teto, em sequência — o "som de meme" saturado);
  • normalizar: deixa cada arquivo num volume de referência antes da mixagem (assim os níveis do sound design valem
    pra qualquer fonte, alto ou baixo).

Sem IA, só ffmpeg + numpy.
"""
from __future__ import annotations

import re
import subprocess
from typing import Any, Dict

LUFS_REFERENCIA = -20.0   # cada arquivo escolhido fica aqui (a mixagem aplica os ganhos por camada em cima)
TETO_PICO = -2.0          # dBTP depois de normalizar


def _pcm(caminho: str, taxa: int = 22050, max_s: float = 120.0):
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", caminho, "-t", f"{max_s:.0f}", "-ac", "1", "-ar", str(taxa),
                        "-f", "s16le", "-"], capture_output=True, timeout=300)
    return np.frombuffer(r.stdout, dtype=np.int16)


def clipping(caminho: str) -> Dict[str, float]:
    """% de amostras no teto e quantas "chapadas" (3+ amostras seguidas no teto = a onda cortada)."""
    import numpy as np
    x = _pcm(caminho)
    if not len(x):
        return {"clip_pct": 0.0, "chapadas_por_s": 0.0, "pico": 0.0}
    a = np.abs(x.astype(np.int32))
    pico = int(a.max())
    teto = max(32000, int(pico * 0.995)) if pico >= 32000 else 10 ** 9   # só conta quando chegou no teto digital
    no_teto = a >= teto
    pct = float(no_teto.mean() * 100)
    # sequências de 3+ amostras no teto
    d = np.diff(np.concatenate([[0], no_teto.astype(np.int8), [0]]))
    ini, fim = np.where(d == 1)[0], np.where(d == -1)[0]
    chapadas = int(((fim - ini) >= 3).sum())
    return {"clip_pct": round(pct, 4), "chapadas_por_s": round(chapadas / (len(x) / 22050.0), 3), "pico": round(pico / 32768.0, 4)}


def loudness(caminho: str) -> Dict[str, float]:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", caminho, "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    txt = r.stderr[-3000:]
    i = re.findall(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", txt)
    p = re.findall(r"Peak:\s+(-?[\d.]+|-inf)\s+dBFS", txt)
    num = lambda v, d: float(v) if v not in (None, "-inf") else d  # noqa: E731
    return {"lufs": num(i[-1] if i else None, -70.0), "pico_db": num(p[-1] if p else None, -70.0)}


def avaliar(caminho: str) -> Dict[str, Any]:
    """{"lufs", "pico_db", "clip_pct", "chapadas_por_s", "estourado", "baixo", "ok", "motivo"}."""
    q: Dict[str, Any] = {}
    try:
        q.update(loudness(caminho))
    except Exception:  # noqa: BLE001
        q.update(lufs=-70.0, pico_db=-70.0)
    try:
        q.update(clipping(caminho))
    except Exception:  # noqa: BLE001
        q.update(clip_pct=0.0, chapadas_por_s=0.0, pico=0.0)
    q["estourado"] = q["clip_pct"] > 0.3 or q["chapadas_por_s"] > 2.0
    q["baixo"] = q["lufs"] < -50
    q["ok"] = not q["estourado"] and not q["baixo"]
    q["motivo"] = ("estourado (distorcido no teto)" if q["estourado"] else "quase mudo" if q["baixo"] else "")
    return q


def normalizar(entrada: str, saida: str, alvo_lufs: float = LUFS_REFERENCIA, teto: float = TETO_PICO) -> str:
    """Volume de referência (loudnorm) + um limitador de segurança. Sai .m4a (ou o formato da extensão)."""
    filtro = f"loudnorm=I={alvo_lufs:.1f}:TP={teto:.1f}:LRA=11,alimiter=limit=0.89,aresample=48000"
    args = ["ffmpeg", "-y", "-v", "error", "-i", entrada, "-af", filtro, "-ac", "2"]
    args += ["-c:a", "aac", "-b:a", "192k"] if saida.lower().endswith((".m4a", ".aac")) else []
    subprocess.run(args + [saida], check=True, timeout=600)
    return saida
