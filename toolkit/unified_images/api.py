"""API HTTP unificada (FastAPI).

  POST /api/search                      busca (síncrona ou em segundo plano)
  GET  /api/search?q=..&engines=..      mesma busca por querystring
  GET  /api/engines                     buscadores e filtros de cada um
  GET  /api/requests                    requisições já feitas
  GET  /api/requests/{id}               imagens.json da requisição (status/andamento)
  GET  /api/requests/{id}/imagens/{f}   baixa uma imagem salva
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Union

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .adapters import ADAPTERS
from .orchestrator import run_search
from .spec import ENGINE_NAMES, SearchSpec
from .storage import (
    JSON_NAME,
    create_request_dir,
    list_requests,
    load_request,
    resolve_image_path,
    write_json_atomic,
)

OUTPUT_ROOT = Path(os.environ.get("UNIFIED_IMAGES_DIR", "saidas")).resolve()
MAX_CONCURRENT = max(1, int(os.environ.get("UNIFIED_IMAGES_MAX_CONCURRENT", "1")))
ALLOW_PRIVATE_HOSTS = os.environ.get("UNIFIED_IMAGES_ALLOW_PRIVATE_HOSTS", "0").lower() in ("1", "true", "yes")

app = FastAPI(
    title="Busca de Imagens Unificada",
    version="1.0.0",
    description="Yandex + Bing + Brave + Startpage em uma só API. Cada requisição gera uma pasta com ID único.",
)

_slots: asyncio.Semaphore | None = None
_tasks: set[asyncio.Task] = set()


def _get_slots() -> asyncio.Semaphore:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(MAX_CONCURRENT)
    return _slots


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


class QueryItem(BaseModel):
    q: str
    limit: int | None = Field(None, ge=1, le=50)
    orientation: str | None = None


class SearchBody(BaseModel):
    queries: list[Union[str, QueryItem]] = Field(
        ..., min_length=1, description='Ex.: ["gojo", {"q": "geto", "limit": 10, "orientation": "vertical"}]'
    )
    engines: Union[list[str], str] = Field(
        default_factory=lambda: list(ENGINE_NAMES),
        description="yandex, bing, brave, startpage ou 'all'",
    )
    limit: int = Field(5, ge=1, le=50, description="imagens por busca, em cada buscador")
    orientation: str = Field("any", description="any | horizontal | vertical | square")
    square_tolerance: float = Field(0.1, ge=0, le=0.5)
    download: bool = True
    download_mode: str = Field("direct", description="direct | source | both")
    inspect_sources: bool = False
    max_images_per_site: int = Field(50, ge=1, le=500)
    allow_google_source: bool = False
    allow_search_engine_sources: bool = False
    min_source_side: int = Field(0, ge=0)
    headless: bool = False
    pause_between_ms: int = Field(1500, ge=0, le=60000)
    parallel_engines: bool = False
    download_concurrency: int = Field(6, ge=1, le=16)
    keep_raw: bool = False
    engine_options: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description='Filtros próprios, ex.: {"bing": {"aspect": "wide", "size": "large"}}',
    )
    background: bool = Field(False, description="true = responde já com o request_id e roda em segundo plano")


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------


def _make_spec(data: dict[str, Any]) -> SearchSpec:
    try:
        return SearchSpec.from_dict(data)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _execute(spec: SearchSpec, rid: str) -> dict[str, Any]:
    async with _get_slots():
        return await run_search(
            spec,
            output_root=OUTPUT_ROOT,
            request_id=rid,
            allow_private_hosts=ALLOW_PRIVATE_HOSTS,
            log=print,
        )


async def _background(spec: SearchSpec, rid: str) -> None:
    try:
        await _execute(spec, rid)
    except Exception as exc:  # o erro já foi gravado em imagens.json
        print(f"[{rid}] erro: {type(exc).__name__}: {exc}")


async def _start(spec: SearchSpec, background: bool):
    rid, req_dir = create_request_dir(OUTPUT_ROOT)
    write_json_atomic(
        req_dir / JSON_NAME,
        {"request_id": rid, "status": "queued", "request": spec.to_dict(), "imagens": []},
    )
    if background:
        task = asyncio.create_task(_background(spec, rid))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return JSONResponse(
            {"request_id": rid, "status": "queued", "status_url": f"/api/requests/{rid}"}, status_code=202
        )
    try:
        return await _execute(spec, rid)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"request_id": rid, "error": f"{type(exc).__name__}: {exc}", "status_url": f"/api/requests/{rid}"},
        ) from exc


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "output_dir": str(OUTPUT_ROOT), "max_concurrent_requests": MAX_CONCURRENT}


@app.get("/api/engines")
async def engines() -> dict[str, Any]:
    return {
        "engines": {name: a.describe() for name, a in ADAPTERS.items()},
        "common_filters": {
            "limit": "imagens por busca, em cada buscador (1-50)",
            "orientation": "any | horizontal | vertical | square (proporção medida pelo próprio buscador)",
            "square_tolerance": "0-0.5; quão perto de 1:1 conta como quadrada",
            "inspect_sources": "abre as páginas de origem e cataloga as imagens delas (todos os buscadores)",
            "download_mode": "direct (imagem do resultado) | source (imagens do site de origem) | both",
            "max_images_per_site": "1-500",
            "allow_google_source / allow_search_engine_sources": "libera buscadores como 'origem'",
        },
    }


@app.post("/api/search")
async def search_post(body: SearchBody):
    data = body.model_dump(exclude={"background"})
    return await _start(_make_spec(data), body.background)


@app.get("/api/search")
async def search_get(
    request: Request,
    q: list[str] = Query(..., description="repita q= para várias buscas"),
    engines: str = "all",
    limit: int = Query(5, ge=1, le=50),
    orientation: str = "any",
    square_tolerance: float = Query(0.1, ge=0, le=0.5),
    download: bool = True,
    download_mode: str = "direct",
    inspect_sources: bool = False,
    max_images_per_site: int = Query(50, ge=1, le=500),
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
    min_source_side: int = Query(0, ge=0),
    headless: bool = False,
    pause_between_ms: int = Query(1500, ge=0, le=60000),
    parallel_engines: bool = False,
    download_concurrency: int = Query(6, ge=1, le=16),
    keep_raw: bool = False,
    background: bool = False,
):
    """Filtros próprios entram com prefixo do buscador: bing_aspect=wide, startpage_max_pages=3, brave_click_details=false."""
    engine_options: dict[str, dict[str, str]] = {}
    for key, value in request.query_params.items():
        for name in ADAPTERS:
            if key.startswith(name + "_"):
                engine_options.setdefault(name, {})[key[len(name) + 1:]] = value
    spec = _make_spec(
        dict(
            queries=q, engines=engines, limit=limit, orientation=orientation,
            square_tolerance=square_tolerance, download=download, download_mode=download_mode,
            inspect_sources=inspect_sources, max_images_per_site=max_images_per_site,
            allow_google_source=allow_google_source,
            allow_search_engine_sources=allow_search_engine_sources,
            min_source_side=min_source_side, headless=headless, pause_between_ms=pause_between_ms,
            parallel_engines=parallel_engines, download_concurrency=download_concurrency,
            keep_raw=keep_raw, engine_options=engine_options,
        )
    )
    return await _start(spec, background)


@app.get("/api/requests")
async def requests_list(limit: int = Query(100, ge=1, le=1000)):
    return {"output_dir": str(OUTPUT_ROOT), "requests": list_requests(OUTPUT_ROOT, limit)}


@app.get("/api/requests/{request_id}")
async def request_get(request_id: str):
    try:
        data = load_request(OUTPUT_ROOT, request_id)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"imagens.json ilegível: {exc}") from exc
    if data is None:
        raise HTTPException(status_code=404, detail="requisição não encontrada")
    return data


@app.get("/api/requests/{request_id}/imagens/{filename}")
async def request_image(request_id: str, filename: str):
    path = resolve_image_path(OUTPUT_ROOT, request_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="imagem não encontrada")
    return FileResponse(path)


def serve(host: str = "127.0.0.1", port: int = 8010) -> None:
    import uvicorn

    print(f"Busca de Imagens Unificada: http://{host}:{port}/docs")
    print(f"Pasta das requisições: {OUTPUT_ROOT}")
    uvicorn.run(app, host=host, port=port)
