"""
Gênero, idade e descrição dos PERFIS DE VOZ (os áudios de referência usados pra
clonar voz no XTTS / Chatterbox / Chatterbox Turbo).

Os perfis em si ficam em `toolkit/tts/models/perfis_de_voz/` (pasta ou .wav
solto); esses dados ficam à parte, em `perfis_info.json` na pasta do site, pra
não mexer no formato dos perfis. As vozes com slug (multivoz.py) que usam um
perfil HERDAM gênero/idade/descrição dele quando não têm os próprios.
"""
from __future__ import annotations

import json
import os
import threading
import unicodedata
from typing import Any, Dict, Optional

_AQUI = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.path.join(_AQUI, "perfis_info.json")
_TRAVA = threading.Lock()

GENEROS = {"masculino": "masculina", "feminino": "feminina", "neutro": "neutra/indefinida"}
IDADES = {"crianca": "criança", "jovem": "jovem", "adulto": "adulta", "idoso": "idosa"}
IDADES_ROTULO = {"crianca": "👧 criança", "jovem": "🧑 jovem", "adulto": "🧔 adulto", "idoso": "👴 idoso"}


def _sem_acento(t: Any) -> str:
    s = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower().strip()
    return "".join(c if c.isalnum() else "_" for c in s).strip("_")


def normalizar_genero(g: Any) -> str:
    t = _sem_acento(g)
    if not t:
        return ""
    if t in GENEROS:
        return t
    if t in ("m", "masc", "male", "man", "homem", "masculina", "menino", "boy"):
        return "masculino"
    if t in ("f", "fem", "female", "woman", "mulher", "feminina", "menina", "girl"):
        return "feminino"
    if t in ("n", "neutra", "neutral", "nb", "nao_binario", "indefinido", "outro"):
        return "neutro"
    return ""


def normalizar_idade(i: Any) -> str:
    """\"criança\"/\"child\"/\"kid\" -> crianca; \"teen\"/\"adolescente\" -> jovem;
    \"adult\" -> adulto; \"velho\"/\"elderly\"/\"old\" -> idoso."""
    t = _sem_acento(i)
    if not t:
        return ""
    if t in IDADES:
        return t
    if t in ("child", "kid", "crianca", "infantil", "menino", "menina", "boy", "girl", "c"):
        return "crianca"
    if t in ("teen", "teenager", "adolescente", "young", "jovem", "youth", "j"):
        return "jovem"
    if t in ("adult", "adulta", "adulto", "a", "meia_idade", "middle_aged"):
        return "adulto"
    if t in ("old", "elderly", "senior", "velho", "velha", "idosa", "anciao", "anciã", "i"):
        return "idoso"
    return ""


def _ler() -> Dict[str, Dict[str, Any]]:
    try:
        with open(ARQUIVO, encoding="utf-8") as f:
            d = json.load(f)
        return {k: v for k, v in (d.get("perfis") if isinstance(d, dict) else {}).items() if isinstance(v, dict)}
    except (OSError, ValueError):
        return {}


def _gravar(d: Dict[str, Dict[str, Any]]) -> None:
    tmp = ARQUIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"perfis": d}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ARQUIVO)


def todos() -> Dict[str, Dict[str, Any]]:
    return _ler()


def obter(nome: Optional[str]) -> Dict[str, Any]:
    if not nome:
        return {}
    return dict(_ler().get(str(nome)) or {})


def definir(nome: str, genero: Any = None, idade: Any = None, descricao: Optional[str] = None) -> Dict[str, Any]:
    """Grava gênero/idade/descrição do perfil (None = não mexe; \"\" = limpa)."""
    nome = str(nome or "").strip()
    if not nome:
        raise ValueError("Perfil sem nome.")
    if genero not in (None, "") and not normalizar_genero(genero):
        raise ValueError("Gênero inválido — use masculino, feminino ou neutro.")
    if idade not in (None, "") and not normalizar_idade(idade):
        raise ValueError("Idade inválida — use criança, jovem, adulto ou idoso.")
    with _TRAVA:
        d = _ler()
        info = d.get(nome) or {}
        if genero is not None:
            info["genero"] = normalizar_genero(genero)
        if idade is not None:
            info["idade"] = normalizar_idade(idade)
        if descricao is not None:
            info["descricao"] = str(descricao).strip()[:120]
        d[nome] = info
        _gravar(d)
    return info


def atualizar(nome: str, **campos: Any) -> Dict[str, Any]:
    """Grava outros campos do perfil (ex.: 🎧 "audio" e "limpeza" — ver perfis_limpeza.py). None = apaga o campo."""
    nome = str(nome or "").strip()
    if not nome:
        raise ValueError("Perfil sem nome.")
    with _TRAVA:
        d = _ler()
        info = d.get(nome) or {}
        for k, v in campos.items():
            if v is None:
                info.pop(k, None)
            else:
                info[k] = v
        d[nome] = info
        _gravar(d)
    return dict(info)


def remover(nome: str) -> None:
    with _TRAVA:
        d = _ler()
        if d.pop(str(nome), None) is not None:
            _gravar(d)


def rotulo(genero: str, idade: str) -> str:
    """\"voz feminina, idosa\" / \"voz masculina\" / \"gênero não definido\"."""
    partes = []
    if genero in GENEROS:
        partes.append("voz " + GENEROS[genero])
    if idade in IDADES:
        partes.append(IDADES[idade] if partes else "voz " + IDADES[idade])
    return ", ".join(partes) or "gênero não definido"
