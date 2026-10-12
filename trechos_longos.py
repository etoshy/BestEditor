"""
trechos_longos.py
=================

✂️ TRECHO LONGO DEMAIS (v84_73). Com transcrição longa a IA às vezes "cansa" no fim e devolve um trecho de
1–2 minutos (ex.: o último cobrindo 12:20 → 14:20) — um clipe curto repetido/esticado por minutos.

Aqui um trecho maior que o limite (2,5× o intervalo escolhido, no mínimo 15 s) vira vários pedaços do tamanho do
intervalo, cortados nas pausas da fala (início de frase da transcrição) quando dá. O 1º pedaço fica com a busca e o
texto; os outros usam as buscas de reserva (alternativas) da IA, um diferente por pedaço — e, com a 🤖 IA ligada,
a etapa "buscas melhores" ainda reescreve a busca de cada pedaço pela fala dele.

Ficam como estão: trechos do YouTube/projeto (o clipe longo pode ser de propósito) e cenas (template). Trecho com
mídia escolhida: o 1º pedaço fica com ela, os outros ganham busca própria.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Any, Dict, List, Optional

NAO_DIVIDIR = {"youtube", "material", "produto"}
MINIMO = 15.0


def limite(intervalo: Optional[float]) -> float:
    return max(MINIMO, 2.5 * float(intervalo or 7.0))


def _g(s: Any, k: str, d: Any = None) -> Any:
    return s.get(k, d) if isinstance(s, dict) else getattr(s, k, d)


def pode_dividir(s: Any, intervalo: Optional[float]) -> bool:
    dur = float(_g(s, "end", 0)) - float(_g(s, "start", 0))
    return dur > limite(intervalo) and _g(s, "provider") not in NAO_DIVIDIR and not _g(s, "template")


def cortes(ini: float, fim: float, intervalo: Optional[float], pausas: List[float]) -> List[float]:
    """Os pontos de corte dentro de [ini, fim]: ~1 a cada `intervalo`, puxados pra pausa da fala mais perto."""
    alvo = max(3.0, float(intervalo or 7.0))
    n = max(2, int(math.ceil((fim - ini) / alvo)))
    passo = (fim - ini) / n
    out: List[float] = []
    for k in range(1, n):
        t = ini + k * passo
        perto = [p for p in pausas if abs(p - t) <= passo * 0.4]
        if perto:
            t = min(perto, key=lambda p: abs(p - t))
        anterior = out[-1] if out else ini
        if t - anterior >= 1.5 and fim - t >= 1.5:
            out.append(round(t, 3))
    return out


def pedacos(s: Dict[str, Any], intervalo: Optional[float], pausas: List[float]) -> List[Dict[str, Any]]:
    """Um trecho (dict) → os pedaços (dicts)."""
    ini, fim = float(s["start"]), float(s["end"])
    pts = [ini] + cortes(ini, fim, intervalo, pausas) + [fim]
    buscas = [b for b in [s.get("query")] + list(s.get("alternativas") or []) if b]
    out = []
    for k in range(len(pts) - 1):
        p = dict(s, start=pts[k], end=pts[k + 1])
        if k:
            p["override_source"] = None  # a mídia escolhida fica só no 1º pedaço
            p["query"] = buscas[k % len(buscas)] if buscas else s.get("query")
            p["on_screen_text"] = None
            p["texto_da_ia"] = None
            p["alternativas"] = [b for b in buscas if b != p["query"]][:5] or None
        if k < len(pts) - 2:  # a transição do trecho original é na emenda do FIM dele
            p.pop("transition", None)
            p.pop("transition_duration", None)
        p["pedaco_de_longo"] = True
        out.append(p)
    return out


def dividir_segmentos(segments: List[Any], intervalo: Optional[float], pausas: List[float]) -> List[Any]:
    """Lista de VideoSegment (ou dicts) com os trechos longos divididos. Devolve uma lista nova."""
    novos: List[Any] = []
    for s in segments:
        if not pode_dividir(s, intervalo):
            novos.append(s)
            continue
        if isinstance(s, dict):
            novos.extend(pedacos(s, intervalo, pausas))
            continue
        campos = {f.name for f in dataclasses.fields(s)}
        base = {f: getattr(s, f) for f in campos}
        for p in pedacos(base, intervalo, pausas):
            novos.append(dataclasses.replace(s, **{k: v for k, v in p.items() if k in campos}))
    return novos


def pausas_da_fala(blocos: List[Dict[str, Any]]) -> List[float]:
    """Onde começa cada frase/bloco da transcrição (um bom lugar pra trocar de imagem)."""
    return sorted({round(float(b["start"]), 3) for b in blocos or [] if b.get("start") is not None})
