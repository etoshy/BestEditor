"""
🕘 historico_roteiro.py — HISTÓRICO DE VERSÕES do roteiro (tipo o git, v84_99)
==============================================================================

Toda vez que o roteiro de um projeto (🕵️ Modelos de vídeo ou 📜 Roteiro do YouTube) MUDA — gerado pela IA, partes
montadas, 🪄 revisão, 🔎 checagem, 🎙 adaptação pro TTS, edição sua, desfazer —, o texto novo vira uma VERSÃO, com
data, de onde veio a mudança e quantas palavras entraram/saíram. Dá pra ver o que mudou de uma versão pra outra
(as palavras riscadas em vermelho / novas em verde, como um diff do GitHub) e voltar pra qualquer uma — voltar
também vira uma versão nova, então nada se perde.

Fica na pasta do projeto: historico/indice.json (só os dados de cada versão) + historico/v0001.txt, v0002.txt…
(o texto de cada uma). Guarda as últimas MAX_VERSOES.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import arquivo_seguro

MAX_VERSOES = 80
PASTA = "historico"


def _hash(texto: str) -> str:
    return hashlib.sha1(str(texto or "").strip().encode("utf-8")).hexdigest()[:16]


def palavras(texto: str) -> int:
    return len(re.sub(r"\[\[[^\]]*\]\]|\[[^\]]*\]", " ", str(texto or "")).split())


def _dir(pasta_projeto: str) -> str:
    return os.path.join(pasta_projeto, PASTA)


def _indice(pasta_projeto: str) -> List[Dict[str, Any]]:
    try:
        with open(os.path.join(_dir(pasta_projeto), "indice.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def listar(pasta_projeto: str) -> List[Dict[str, Any]]:
    """As versões, da mais nova pra mais velha (sem o texto)."""
    return list(reversed(_indice(pasta_projeto)))


def texto(pasta_projeto: str, n: int) -> Optional[str]:
    try:
        with open(os.path.join(_dir(pasta_projeto), f"v{int(n):04d}.txt"), encoding="utf-8") as f:
            return f.read()
    except (OSError, ValueError):
        return None


def registrar(pasta_projeto: str, novo: str, origem: str = "", mensagem: str = "") -> Optional[Dict[str, Any]]:
    """Guarda `novo` como versão nova — se for diferente da última. Devolve a versão criada (ou None)."""
    novo = str(novo or "")
    if not novo.strip():
        return None
    idx = _indice(pasta_projeto)
    h = _hash(novo)
    if idx and idx[-1].get("hash") == h:
        return None
    os.makedirs(_dir(pasta_projeto), exist_ok=True)
    n = (idx[-1]["n"] + 1) if idx else 1
    antes = texto(pasta_projeto, idx[-1]["n"]) if idx else None
    ent, sai = _contar(antes or "", novo) if antes is not None else (palavras(novo), 0)
    v = {"n": n, "quando": time.time(), "origem": str(origem or "alteração")[:40], "mensagem": str(mensagem or "")[:300],
         "palavras": palavras(novo), "entraram": ent, "sairam": sai, "hash": h}
    tmp = os.path.join(_dir(pasta_projeto), f"v{n:04d}.txt.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(novo)
    arquivo_seguro.trocar(tmp, os.path.join(_dir(pasta_projeto), f"v{n:04d}.txt"))
    idx.append(v)
    while len(idx) > MAX_VERSOES:
        velho = idx.pop(0)
        try:
            os.remove(os.path.join(_dir(pasta_projeto), f"v{velho['n']:04d}.txt"))
        except OSError:
            pass
    arquivo_seguro.gravar_json(os.path.join(_dir(pasta_projeto), "indice.json"), idx, indent=1)
    return v


# ------------------------------------------------------------------ o que mudou (diff por palavras)
_TOKEN = re.compile(r"\s+|[^\s]+")


def _tokens(t: str) -> List[str]:
    return _TOKEN.findall(t or "")


def _ops(antes: str, depois: str) -> List[Dict[str, str]]:
    """Diff em 2 níveis (rápido até pra roteiro de 6 mil palavras): primeiro por parágrafo/linha; dentro dos parágrafos
    trocados, por palavra."""
    la, lb = antes.splitlines(keepends=True), depois.splitlines(keepends=True)
    out: List[Dict[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, la, lb, autojunk=False).get_opcodes():
        if op == "equal":
            out.append({"op": "=", "t": "".join(la[i1:i2])})
        elif op == "delete":
            out.append({"op": "-", "t": "".join(la[i1:i2])})
        elif op == "insert":
            out.append({"op": "+", "t": "".join(lb[j1:j2])})
        else:
            a, b = _tokens("".join(la[i1:i2])), _tokens("".join(lb[j1:j2]))
            for o2, x1, x2, y1, y2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
                if o2 == "equal":
                    out.append({"op": "=", "t": "".join(a[x1:x2])})
                    continue
                if o2 in ("replace", "delete"):
                    out.append({"op": "-", "t": "".join(a[x1:x2])})
                if o2 in ("replace", "insert"):
                    out.append({"op": "+", "t": "".join(b[y1:y2])})
    juntos: List[Dict[str, str]] = []
    for x in out:  # junta pedaços vizinhos do mesmo tipo
        if x["t"] and juntos and juntos[-1]["op"] == x["op"]:
            juntos[-1] = {"op": x["op"], "t": juntos[-1]["t"] + x["t"]}
        elif x["t"]:
            juntos.append(dict(x))
    return juntos


def _contar(a: str, b: str):
    ent = sai = 0
    for x in _ops(a, b):
        if x["op"] == "+":
            ent += len(x["t"].split())
        elif x["op"] == "-":
            sai += len(x["t"].split())
    return ent, sai


def diff(antes: str, depois: str, contexto: int = 14) -> Dict[str, Any]:
    """Diff por palavras: [{"op": "=", "t": "…"}, {"op": "-", "t": "…"}, {"op": "+", "t": "…"}] — trechos iguais longos
    viram só as pontas (… N palavras iguais …)."""
    out: List[Dict[str, str]] = []
    ent = sai = 0
    ops = _ops(antes or "", depois or "")
    for k, x in enumerate(ops):
        if x["op"] != "=":
            out.append(x)
            if x["op"] == "+":
                ent += len(x["t"].split())
            else:
                sai += len(x["t"].split())
            continue
        pedaco = _tokens(x["t"])
        pal = [w for w in pedaco if w.strip()]
        primeiro, ultimo = k == 0, k == len(ops) - 1
        if len(pal) <= contexto * 2 + 6:
            out.append(x)
            continue
        ini, fim, n = [], [], 0
        if not primeiro:
            for w in pedaco:
                ini.append(w)
                n += bool(w.strip())
                if n >= contexto:
                    break
        n = 0
        if not ultimo:
            for w in reversed(pedaco):
                fim.insert(0, w)
                n += bool(w.strip())
                if n >= contexto:
                    break
        escondidas = len(pal) - (contexto if not primeiro else 0) - (contexto if not ultimo else 0)
        if ini:
            out.append({"op": "=", "t": "".join(ini)})
        out.append({"op": "…", "t": f"{escondidas} palavras iguais"})
        if fim:
            out.append({"op": "=", "t": "".join(fim)})
    return {"partes": out, "entraram": ent, "sairam": sai}
