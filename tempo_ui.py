"""🕒 v84_413 — data e hora em tudo que é listado (criado / editado), num formato só.

No Jinja: {{ tempo(item) }} (procura criado/created_at/… e atualizado/updated_at/…) ou {{ tempo(criado=ts, editado=ts) }}.
No JavaScript das páginas: beTempo(item) devolve o mesmo HTML. O static/ui/tempo.js troca o texto pelo horário LOCAL do
navegador e atualiza o "há 5 min" sozinho.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

from markupsafe import Markup, escape

CHAVES_CRIADO = ("criado", "criado_em", "criadoEm", "created_at", "created", "criada", "data_criacao", "inicio", "quando",
                 "ts")
CHAVES_EDITADO = ("atualizado", "atualizado_em", "atualizadoEm", "updated_at", "updated", "modificado", "editado", "mudou",
                  "mtime", "fim", "terminado")


def _ts(v: Any) -> float:
    if v in (None, "", 0):
        return 0.0
    if isinstance(v, (int, float)):
        x = float(v)
        return x / 1000 if x > 1e11 else x  # milissegundos (JS) → segundos
    s = str(v).strip()
    try:
        return _ts(float(s))
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def data_hora(ts: Any, ano: Optional[bool] = None) -> str:
    """18/11 10:37 (com o ano quando não é o ano corrente)."""
    t = _ts(ts)
    if not t:
        return ""
    d = datetime.fromtimestamp(t)
    if ano is None:
        ano = d.year != datetime.now().year
    return d.strftime("%d/%m/%Y %H:%M" if ano else "%d/%m %H:%M")


def ha_quanto(ts: Any, agora: Optional[float] = None) -> str:
    t = _ts(ts)
    if not t:
        return ""
    s = max(0, int((agora or time.time()) - t))
    if s < 60:
        return "agora"
    for lim, div, sing, plur in ((3600, 60, "min", "min"), (86400, 3600, "h", "h"), (86400 * 30, 86400, "dia", "dias"),
                                 (86400 * 365, 86400 * 30, "mês", "meses")):
        if s < lim:
            n = s // div
            return f"há {n} {sing if n == 1 else plur}"
    n = s // (86400 * 365)
    return f"há {n} {'ano' if n == 1 else 'anos'}"


def _pegar(item: Any, chaves) -> float:
    if not isinstance(item, dict):
        item = {k: getattr(item, k, None) for k in chaves}
    for k in chaves:
        t = _ts(item.get(k))
        if t:
            return t
    return 0.0


def tempo(item: Any = None, criado: Any = None, editado: Any = None, so_data: bool = False) -> Markup:
    c = _ts(criado) or (_pegar(item, CHAVES_CRIADO) if item is not None else 0.0)
    e = _ts(editado) or (_pegar(item, CHAVES_EDITADO) if item is not None else 0.0)
    if not c and not e:
        return Markup("")
    partes = []
    if c:
        partes.append(f'<span data-ts="{c:.0f}" data-rot="criado">criado {escape(data_hora(c))}</span>')
    mostra_e = bool(e and (not c or e - c > 90))
    if mostra_e:
        partes.append(f'<span data-ts="{e:.0f}" data-rot="editado" data-rel="1">editado {escape(ha_quanto(e))}</span>')
    titulo = " · ".join(x for x in (f"criado em {data_hora(c, True)}" if c else "",
                                    f"editado em {data_hora(e, True)}" if mostra_e else "") if x)
    return Markup(f'<span class="be-tempo" title="{escape(titulo)}">🕒 ' + " · ".join(partes) + "</span>")


def registrar(app) -> None:
    app.jinja_env.globals["tempo"] = tempo
    app.jinja_env.filters["data_hora"] = data_hora
    app.jinja_env.filters["ha_quanto"] = ha_quanto
