"""📝 v84_477 — as transcrições do site (aba 📝 Transcrever e os lotes do YouTube) como matéria-prima do 📚 Texto bruto.

Cada transcrição tem uma CHAVE estável:
  - "a:<id>"            → Transcrever (outputs/transcricoes_avulsas/<id>/transcricao.txt)
  - "l:<lote>:<arquivo>" → lote do YouTube (outputs/transcricoes_avulsas/_lotes/<lote>/arquivos/<arquivo>.txt)
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

_RE_ID = re.compile(r"^[\w-]{1,64}$")


def _ler_json(c: str) -> Dict[str, Any]:
    try:
        with open(c, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _palavras(c: str) -> int:
    try:
        with open(c, encoding="utf-8-sig", errors="replace") as f:
            return len(f.read().split())
    except OSError:
        return 0


def listar(raiz: str, jobs: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """As transcrições prontas, da mais nova pra mais velha: {chave, titulo, origem, quando, palavras, feito}."""
    out: List[Dict[str, Any]] = []
    try:
        nomes = os.listdir(raiz)
    except OSError:
        nomes = []
    for n in nomes:
        if n.startswith("_") or not _RE_ID.match(n):
            continue
        txt = os.path.join(raiz, n, "transcricao.txt")
        if not os.path.isfile(txt):
            continue
        j = (jobs or {}).get(n) or _ler_json(os.path.join(raiz, n, "_job.json"))
        titulo = (str((j.get("resultado") or {}).get("titulo") or "") or os.path.splitext(str(j.get("nome") or ""))[0]
                  or str(j.get("url") or "") or n)
        out.append({"chave": f"a:{n}", "titulo": titulo[:160], "origem": "📝 Transcrever",
                    "quando": float(j.get("criado_em") or os.path.getmtime(txt)), "palavras": _palavras(txt),
                    "feito": bool(j.get("feito"))})
    lotes = os.path.join(raiz, "_lotes")
    for lid in (os.listdir(lotes) if os.path.isdir(lotes) else []):
        arqs = os.path.join(lotes, lid, "arquivos")
        if not _RE_ID.match(lid) or not os.path.isdir(arqs):
            continue
        for a in os.listdir(arqs):
            if not a.endswith(".txt") or a.endswith("(com timestamps).txt") or a.startswith("_"):
                continue
            c = os.path.join(arqs, a)
            out.append({"chave": f"l:{lid}:{a[:-4]}", "titulo": a[:-4][:160], "origem": "▶ YouTube (lote)",
                        "quando": os.path.getmtime(c), "palavras": _palavras(c), "feito": False})
    out.sort(key=lambda x: -x["quando"])
    return out


def caminho(raiz: str, chave: str) -> Optional[str]:
    """O arquivo .txt da chave (sempre dentro da pasta das transcrições)."""
    partes = str(chave or "").split(":", 2)
    if partes[0] == "a" and len(partes) == 2 and _RE_ID.match(partes[1]):
        c = os.path.join(raiz, partes[1], "transcricao.txt")
    elif partes[0] == "l" and len(partes) == 3 and _RE_ID.match(partes[1]) and partes[2] and "/" not in partes[2] \
            and "\\" not in partes[2] and ".." not in partes[2]:
        c = os.path.join(raiz, "_lotes", partes[1], "arquivos", partes[2] + ".txt")
    else:
        return None
    c = os.path.realpath(c)
    if not c.startswith(os.path.realpath(raiz) + os.sep) or not os.path.isfile(c):
        return None
    return c


def ler(raiz: str, chaves: List[str], jobs: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Tuple[bytes, str]]:
    """[(conteúdo, "Título.txt")] das chaves escolhidas, na ordem (as que não existem ficam de fora)."""
    titulos = {x["chave"]: x["titulo"] for x in listar(raiz, jobs)}
    out = []
    for k in chaves:
        c = caminho(raiz, k)
        if not c:
            continue
        with open(c, "rb") as f:
            cont = f.read()
        nome = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", titulos.get(k) or os.path.basename(c)).strip()[:100] or "transcricao"
        out.append((cont, nome + ".txt"))
    return out


def marcar_feitas(chaves: List[str], marcar: Optional[Callable[[str], None]]) -> None:
    for k in chaves:
        if marcar and str(k).startswith("a:"):
            try:
                marcar(k[2:])
            except Exception:  # noqa: BLE001
                pass
