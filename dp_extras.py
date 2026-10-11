"""
➕ Extras do DarkPlanner — o que VOCÊ cria sem mexer no darkplanner.json nem no código.

Ponha arquivos .json em  assets/darkplanner/extras/  (um só ou vários; os que
começam com "_" são ignorados). Cada arquivo pode ter qualquer uma destas seções:

  "transicoes": [{"id", "rotulo", "familia", "int", "energia", "ritmo",
                  + UM de: "xfade" (nativa do ffmpeg), "expr" (fórmula por pixel,
                  P de 0 = só o trecho A até 1 = só o B), "igual_a" (outra transição)}]
  "efeitos":    [{"id", "rotulo", + UM de: "camera" (in, out, pan_left, pan_right,
                  pan_up, pan_down, rapido, giro, respiro, zoom_pan_left/right/up),
                  "filtro" (filtros do ffmpeg que recebem [base] e terminam em [base]),
                  "igual_a" (outro efeito)}]
  "entradas":   [{"id", "rotulo", "igual_a" (gesto existente: pop, punch_in…), "durAlvoS"}]
                 (as mesmas valem como SAÍDA)
  "filtros":    [{"id", "rotulo", "grupo", "cadeia" (filtros do ffmpeg) ou "igual_a", "css" (prévia)}]
  "destaques":  {"meu_id": {"base": "epico", ...só o que muda...}}
  "cenas":      {"MINHA_CENA": {"base": "MULTITAKE_06", "nome", "slots",
                  "arranjo" (lado_a_lado, triade, mosaico…) ou "janelas": [[x,y,w,h], …] + "texto": [x,y,w,h]}}
  "paletas":    [{"id", "nome", "primaria", "secundaria", "acento"}]
  "sons":       [{"id": "categoria/nome", "categoria", "nome", "arquivo", "dur", "pico", "inicio_som", …}]
                 (gerado pelo  python dp_guia.py som arquivo.mp3)
  "fontes":     {"chave": {"familia": "DP Nome", "arquivos": {"Bold": "x.ttf", "Regular": "y.ttf"}}}
                 (gerado pelo  python dp_guia.py fonte arquivo.ttf --chave nome)

Guia completo: docs/guia/README.md (ou a página 📘 Guia do site).
"""
from __future__ import annotations

import copy
import glob
import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, List

_AQUI = os.path.dirname(os.path.abspath(__file__))
SECOES_LISTA = ("transicoes", "efeitos", "entradas", "filtros", "paletas", "sons")
SECOES_DICT = ("destaques", "cenas", "fontes")
_ID = re.compile(r"^[a-z0-9][a-z0-9_]{1,47}$")
_ID_CENA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_]{1,47}$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
CAMERAS = ("in", "out", "pan_left", "pan_right", "pan_up", "pan_down", "static", "rapido", "giro", "respiro",
           "zoom_pan_left", "zoom_pan_right", "zoom_pan_up")


def pasta() -> str:
    return os.environ.get("DP_EXTRAS_DIR") or os.path.join(_AQUI, "assets", "darkplanner", "extras")


def arquivos() -> List[str]:
    return sorted(c for c in glob.glob(os.path.join(pasta(), "*.json")) if not os.path.basename(c).startswith("_"))


_ERROS_CRUZADOS: List[str] = []  # ids que não batem com o catálogo (preenchido por quem mescla)


def avisar(msg: str) -> None:
    if msg not in _ERROS_CRUZADOS:
        _ERROS_CRUZADOS.append(msg)


def _item_ok(secao: str, it: Any, origem: str, erros: List[str]) -> bool:
    if not isinstance(it, dict):
        erros.append(f"{origem}: item de \"{secao}\" precisa ser um objeto {{...}}.")
        return False
    iid = str(it.get("id") or "")
    if secao == "sons":
        if not re.fullmatch(r"[a-z0-9_]+/[a-z0-9_\-]+", iid) or not it.get("arquivo"):
            erros.append(f"{origem}: som sem \"id\" (categoria/nome) ou sem \"arquivo\" — use  python dp_guia.py som arquivo.mp3")
            return False
        return True
    if not _ID.match(iid):
        erros.append(f"{origem}: \"{secao}\" com id inválido {iid!r} (use letras minúsculas, números e _).")
        return False
    if secao == "transicoes":
        n = sum(1 for k in ("xfade", "expr", "igual_a") if it.get(k))
        if n != 1:
            erros.append(f"{origem}: transição {iid}: diga UM de \"xfade\", \"expr\" ou \"igual_a\".")
            return False
        if it.get("expr") and not re.search(r"\bP\b", str(it["expr"])):
            erros.append(f"{origem}: transição {iid}: a \"expr\" precisa usar P (o progresso, de 0 a 1).")
            return False
    elif secao == "efeitos":
        n = sum(1 for k in ("camera", "filtro", "igual_a") if it.get(k))
        if n != 1:
            erros.append(f"{origem}: efeito {iid}: diga UM de \"camera\", \"filtro\" ou \"igual_a\".")
            return False
        if it.get("camera") and it["camera"] not in CAMERAS:
            erros.append(f"{origem}: efeito {iid}: \"camera\" precisa ser um de {', '.join(CAMERAS)}.")
            return False
        if it.get("filtro") and not (str(it["filtro"]).startswith("[base]") and str(it["filtro"]).endswith("[base]")):
            erros.append(f"{origem}: efeito {iid}: o \"filtro\" começa com [base] e termina com [base] (ex.: \"[base]eq=gamma=1.1[base]\").")
            return False
    elif secao == "entradas":
        if not it.get("igual_a"):
            erros.append(f"{origem}: entrada {iid}: diga \"igual_a\" (o gesto em que ela se baseia — pop, punch_in, slide_up…).")
            return False
    elif secao == "filtros":
        if not (it.get("cadeia") or it.get("igual_a")):
            erros.append(f"{origem}: filtro {iid}: diga \"cadeia\" (filtros do ffmpeg) ou \"igual_a\".")
            return False
    elif secao == "paletas":
        if not all(_HEX.match(str(it.get(k) or "")) for k in ("primaria", "secundaria", "acento")):
            erros.append(f"{origem}: paleta {iid}: \"primaria\", \"secundaria\" e \"acento\" em #RRGGBB.")
            return False
    return True


@lru_cache(maxsize=1)
def carregar() -> Dict[str, Any]:
    """Tudo o que está nos arquivos de extras, já conferido (o que tem erro fica de fora e vai pra "erros")."""
    out: Dict[str, Any] = {s: [] for s in SECOES_LISTA}
    out.update({s: {} for s in SECOES_DICT})
    out["erros"], out["arquivos"] = [], []
    for caminho in arquivos():
        nome = os.path.basename(caminho)
        try:
            with open(caminho, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError) as exc:
            out["erros"].append(f"{nome}: não é um JSON válido ({exc}).")
            continue
        if not isinstance(d, dict):
            out["erros"].append(f"{nome}: o arquivo precisa ser um objeto {{ \"destaques\": …, \"transicoes\": … }}.")
            continue
        out["arquivos"].append(nome)
        desconhecidas = [k for k in d if k not in SECOES_LISTA + SECOES_DICT and not k.startswith("_")]
        if desconhecidas:
            out["erros"].append(f"{nome}: seção desconhecida {', '.join(desconhecidas)} (ignorada).")
        for s in SECOES_LISTA:
            lista = d.get(s) or []
            if not isinstance(lista, list):
                out["erros"].append(f"{nome}: \"{s}\" precisa ser uma lista [...].")
                continue
            for it in lista:
                if _item_ok(s, it, nome, out["erros"]):
                    if any(x["id"] == it["id"] for x in out[s]):
                        out["erros"].append(f"{nome}: {s} {it['id']} repetido (ficou o primeiro).")
                        continue
                    out[s].append(dict(it, _arquivo=nome))
        for s in SECOES_DICT:
            dic = d.get(s) or {}
            if not isinstance(dic, dict):
                out["erros"].append(f"{nome}: \"{s}\" precisa ser um objeto {{\"id\": {{...}}}}.")
                continue
            for k, v in dic.items():
                padrao = _ID_CENA if s == "cenas" else _ID
                if not padrao.match(str(k)) or not isinstance(v, dict):
                    out["erros"].append(f"{nome}: {s} {k!r}: id inválido ou valor que não é objeto.")
                    continue
                if k in out[s]:
                    out["erros"].append(f"{nome}: {s} {k} repetido (ficou o primeiro).")
                    continue
                out[s][k] = dict(v, _arquivo=nome)
    return out


def erros() -> List[str]:
    carregar()
    return list(carregar()["erros"]) + list(_ERROS_CRUZADOS)


def mesclar_profundo(base: Dict[str, Any], mudancas: Dict[str, Any]) -> Dict[str, Any]:
    """Cópia de `base` com `mudancas` por cima (dicionários são mesclados; listas e valores, trocados)."""
    out = copy.deepcopy(base)
    for k, v in mudancas.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = mesclar_profundo(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def limpar(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if k not in ("base", "_arquivo")}


def recarregar() -> None:
    """Relê os arquivos de extras e zera os caches de quem usa (sem reiniciar o site)."""
    carregar.cache_clear()
    _ERROS_CRUZADOS.clear()
    import importlib
    import sys
    for mod, cache in (("dp_visual", "dp"), ("cenas_dp", "_catalogo_bruto"), ("dp_sons", "_manifesto")):
        m = sys.modules.get(mod)
        if m is not None and hasattr(getattr(m, cache, None), "cache_clear"):
            getattr(m, cache).cache_clear()
    for mod in ("dp_visual", "dp_cores", "dp_destaques"):
        m = sys.modules.get(mod)
        if m is not None and hasattr(m, "_aplicar_extras"):
            m._aplicar_extras()
    _ = importlib  # (mantém o import explícito pra quem lê)


def resumo() -> Dict[str, Any]:
    c = carregar()
    return {"pasta": pasta(), "arquivos": c["arquivos"], "erros": erros(),
            "contagem": {s: len(c[s]) for s in SECOES_LISTA + SECOES_DICT}}
