"""
perf_log.py
============

Um log de tempo por job (`timing_log.json`, salvo dentro de
`jobs/<job_id>/`) — registra quanto tempo cada etapa levou: transcrição,
montagem do prompt, parsing do JSON da IA, busca/download/normalização
de CADA segmento (na prévia e na montagem final), concatenação,
mixagem de áudio, geração de legenda.

Uso básico:
    perf = PerfLog(job_dir, job_id="abc123")
    with perf.timed("transcricao"):
        transcribe_audio(...)
    with perf.timed("previa:segmento_3:busca"):
        ...
    perf.save()

O arquivo salvo tem dois blocos:
  - "totals_by_category": soma o tempo de todas as ocorrências do MESMO
    tipo de etapa (ex: todas as "buscas" de todos os segmentos somadas),
    pra já mostrar de cara onde o tempo total foi gasto.
  - "events": a lista crua, um item por chamada, com timestamps de
    início/fim — útil pra investigar um segmento específico que
    demorou muito mais que os outros.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# troca "segmento_7" por "segmento_N" pra agrupar por categoria, não por
# índice individual — assim "previa:segmento_0:busca" e
# "previa:segmento_1:busca" caem juntos em "previa:segmento_N:busca"
_SEGMENT_INDEX_RE = re.compile(r"segmento_\d+")


def _categorize(event_name: str) -> str:
    return _SEGMENT_INDEX_RE.sub("segmento_N", event_name)


class PerfLog:
    def __init__(self, job_dir: str, job_id: Optional[str] = None):
        self.job_dir = job_dir
        self.job_id = job_id
        self.path = os.path.join(job_dir, "timing_log.json")
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []

    @contextmanager
    def timed(self, event: str, **meta: Any):
        """Mede o tempo do bloco `with`. Registra o evento mesmo se o
        bloco levantar uma exceção (útil pra saber quanto tempo levou
        ATÉ falhar, não só os que deram certo) — nesse caso, inclui
        `"error": str(exc)` no evento salvo.
        """
        start = time.time()
        error: Optional[str] = None
        try:
            yield
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            raise
        finally:
            end = time.time()
            record = {
                "event": event,
                "start": round(start, 3),
                "end": round(end, 3),
                "duration_seconds": round(end - start, 3),
                **meta,
            }
            if error is not None:
                record["error"] = error
            with self._lock:
                self._events.append(record)

    def record(self, event: str, duration_seconds: float, **meta: Any) -> None:
        """Pra quando você já tem a duração calculada (em vez de medir
        com `with timed(...)` ao redor do código)."""
        with self._lock:
            self._events.append({"event": event, "duration_seconds": round(duration_seconds, 3), **meta})

    def save(self) -> str:
        """Salva o log em `timing_log.json` dentro do job_dir. Pode ser
        chamado várias vezes (ex: uma vez ao fim da pré-busca de
        prévias, de novo ao fim da montagem) — sempre sobrescreve com o
        estado mais atual, então nunca perde o que já foi registrado
        mesmo se uma etapa seguinte falhar.
        """
        with self._lock:
            events = sorted(self._events, key=lambda e: e.get("start", 0))

        totals: Dict[str, Dict[str, Any]] = {}
        for e in events:
            cat = _categorize(e["event"])
            bucket = totals.setdefault(cat, {"count": 0, "total_seconds": 0.0, "errors": 0})
            bucket["count"] += 1
            bucket["total_seconds"] += e["duration_seconds"]
            if e.get("error"):
                bucket["errors"] += 1
        for cat in totals:
            totals[cat]["total_seconds"] = round(totals[cat]["total_seconds"], 3)
            totals[cat]["avg_seconds"] = round(totals[cat]["total_seconds"] / totals[cat]["count"], 3)

        # ordena as categorias da que mais consumiu tempo pra menos —
        # a primeira linha já mostra o maior gargalo, sem precisar caçar
        totals_sorted = dict(sorted(totals.items(), key=lambda kv: kv[1]["total_seconds"], reverse=True))

        data = {
            "job_id": self.job_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "totals_by_category_ordered_by_time": totals_sorted,
            "events": events,
        }

        os.makedirs(self.job_dir, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return self.path
