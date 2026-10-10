"""Dependências opcionais dos motores.

Os 4 motores (`engines/*.py`) também rodam sozinhos como API, então importam
FastAPI, pydantic e uvicorn NO TOPO do arquivo — mesmo quando só a função de
busca é usada (caso do site). Se algum desses pacotes não estiver instalado,
o import do motor quebrava e TODAS as buscas de imagem falhavam na hora
("sem prévia" em todo trecho), sem nenhum navegador abrir.

`garantir_imports_dos_motores()` instala substitutos mínimos em `sys.modules`
só pros pacotes que faltarem: o suficiente pra definição das rotas/modelos no
topo dos motores não quebrar. A busca em si (Playwright) não usa nada disso.
Com os pacotes de verdade instalados, nada é substituído.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from typing import Any


def _faltando(nome: str) -> bool:
    if nome in sys.modules:
        return False
    try:
        return importlib.util.find_spec(nome) is None
    except (ImportError, ValueError):
        return True


class _Qualquer:
    """Aceita qualquer construção/atributo/decorador sem fazer nada."""

    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    def __call__(self, *a: Any, **k: Any) -> Any:
        if len(a) == 1 and callable(a[0]) and not k:
            return a[0]  # usado como @decorador
        return lambda f: f  # usado como @decorador(...)

    def __getattr__(self, _nome: str) -> "_Qualquer":
        return _Qualquer()


def _valor_padrao(default: Any = None, *a: Any, **k: Any) -> Any:
    return None if default is Ellipsis else default


def garantir_imports_dos_motores() -> list:
    """Devolve a lista de pacotes substituídos (vazia = todos instalados)."""
    trocados = []

    if _faltando("fastapi"):
        fastapi = types.ModuleType("fastapi")

        class HTTPException(Exception):
            def __init__(self, status_code: int = 500, detail: Any = None, **_k: Any) -> None:
                super().__init__(detail)
                self.status_code, self.detail = status_code, detail

        fastapi.FastAPI = _Qualquer
        fastapi.HTTPException = HTTPException
        fastapi.Query = _valor_padrao
        fastapi.Body = _valor_padrao
        fastapi.Request = object
        responses = types.ModuleType("fastapi.responses")

        class JSONResponse(dict):
            def __init__(self, content: Any = None, status_code: int = 200, **_k: Any) -> None:
                super().__init__(content=content, status_code=status_code)

        responses.JSONResponse = JSONResponse
        responses.FileResponse = JSONResponse
        fastapi.responses = responses
        sys.modules["fastapi"] = fastapi
        sys.modules["fastapi.responses"] = responses
        trocados.append("fastapi")

    if _faltando("pydantic"):
        pydantic = types.ModuleType("pydantic")

        class BaseModel:
            def __init__(self, **dados: Any) -> None:
                for k, v in dados.items():
                    setattr(self, k, v)

            def model_dump(self, **_k: Any) -> dict:
                return dict(self.__dict__)

        pydantic.BaseModel = BaseModel
        pydantic.Field = _valor_padrao
        sys.modules["pydantic"] = pydantic
        trocados.append("pydantic")

    if _faltando("uvicorn"):
        uvicorn = types.ModuleType("uvicorn")
        uvicorn.run = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("uvicorn não instalado (pip install uvicorn) — só é preciso pra rodar o motor como API.")
        )
        sys.modules["uvicorn"] = uvicorn
        trocados.append("uvicorn")

    return trocados
