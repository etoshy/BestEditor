"""Orquestra uma requisição: buscadores -> origens -> download -> pasta com JSON."""

from __future__ import annotations

import asyncio
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from .adapters import ADAPTERS, EngineRun
from .downloader import DownloadJob, download_images
from .sources import Inspector, inspect_missing_sources
from .spec import SearchSpec
from .storage import IMAGES_DIRNAME, JSON_NAME, create_request_dir, write_json_atomic

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".svg", ".tif", ".tiff", ".ico"}


# ---------------------------------------------------------------------------
# Nomes
# ---------------------------------------------------------------------------


def slugify(text: str, max_len: int = 80) -> str:
    text = re.sub(r"[^\w.\-]+", "_", text.strip(), flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("._- ")
    return text[:max_len].strip("._- ")


def image_name(url: str, title: str, fallback: str) -> str:
    """Nome legível: arquivo da URL se parecer imagem; senão o título; senão genérico."""
    base = unquote(urlparse(url).path).rsplit("/", 1)[-1].strip()
    if base and Path(base).suffix.lower() in IMAGE_EXTS:
        return base[:150]
    if title.strip():
        return title.strip()[:150]
    return base[:150] if base else fallback


def _url_key(url: str) -> str:
    return url.split("#", 1)[0]


# ---------------------------------------------------------------------------
# Candidatos a download
# ---------------------------------------------------------------------------


def build_images(
    spec: SearchSpec,
    engine_runs: list[EngineRun],
    sites: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Une resultados diretos + imagens catalogadas dos sites, sem repetir URL."""
    by_url: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def add(url: str, **data: Any) -> dict[str, Any]:
        key = _url_key(url)
        entry = by_url.get(key)
        if entry is None:
            entry = {
                "original_url": key, "name": "", "title": "", "alt": "", "kind": "",
                "source_page": "", "og": {}, "origin": [], "found_by": [],
                "width": None, "height": None, "orientation": None, "aspect_ratio": None,
                "thumbnail_url": "", "fallback_urls": [],
            }
            by_url[key] = entry
            order.append(key)
        for k, v in data.items():
            if k == "origin":
                if v not in entry["origin"]:
                    entry["origin"].append(v)
            elif k == "found_by":
                for fb in v:
                    if fb not in entry["found_by"]:
                        entry["found_by"].append(fb)
            elif k == "fallback_urls":
                for u in v:
                    if u not in entry["fallback_urls"] and u != key:
                        entry["fallback_urls"].append(u)
            elif k == "og":
                if v and not entry["og"]:
                    entry["og"] = v
            elif v not in (None, "", [], {}) and entry.get(k) in (None, "", [], {}):
                entry[k] = v
        return entry

    all_hits = [h for run in engine_runs for h in run.results]
    hits_by_site: dict[str, list[dict[str, Any]]] = {}
    for hit in all_hits:
        if hit["source_page"]:
            hits_by_site.setdefault(hit["source_page"], []).append(hit)

    def found(hit: dict[str, Any]) -> dict[str, Any]:
        return {"engine": hit["engine"], "query": hit["query"], "rank": hit["rank"]}

    # 1) resultado direto de cada buscador
    if spec.download_mode in ("direct", "both"):
        for hit in all_hits:
            if not hit["original_url"]:
                continue
            site = sites.get(hit["source_page"]) if hit["source_page"] else None
            add(
                hit["original_url"],
                origin="direct",
                kind="result",
                title=hit["title"],
                alt=hit["alt"],
                source_page=hit["source_page"],
                og=(site or {}).get("og") or {},
                width=hit["width"],
                height=hit["height"],
                orientation=hit["orientation"],
                aspect_ratio=hit["aspect_ratio"],
                thumbnail_url=hit["thumbnail_url"],
                fallback_urls=hit["fallback_urls"],
                found_by=[found(hit)],
            )

    # 2) imagens catalogadas nos sites de origem (só quando o pedido é baixá-las)
    if spec.download_mode in ("source", "both"):
        for page, site in sites.items():
            if site.get("blocked"):
                continue
            for img in site.get("images", []):
                w, h = img.get("width"), img.get("height")
                if spec.min_source_side and w and h and min(w, h) < spec.min_source_side:
                    continue
                add(
                    img["url"],
                    origin="source",
                    kind=img.get("kind", ""),
                    name=img.get("name", ""),
                    title=img.get("title", ""),
                    alt=img.get("alt", ""),
                    source_page=page,
                    og=site.get("og") or {},
                    width=w,
                    height=h,
                    found_by=[found(hit) for hit in hits_by_site.get(page, [])],
                )

    images: list[dict[str, Any]] = []
    for n, key in enumerate(order, start=1):
        e = by_url[key]
        e["id"] = n
        e["name"] = image_name(key, e["name"] or e["title"] or e["alt"], f"imagem_{n:04d}")
        e["engines"] = list(dict.fromkeys(f["engine"] for f in e["found_by"]))
        e["queries"] = list(dict.fromkeys(f["query"] for f in e["found_by"]))
        images.append(e)
    return images


def make_jobs(images: list[dict[str, Any]]) -> list[DownloadJob]:
    jobs = []
    for e in images:
        engine = (e["engines"] or ["site"])[0]
        stem = f"{e['id']:04d}_{engine}_{slugify(Path(e['name']).stem) or 'imagem'}"
        referer = e["source_page"] or (ADAPTERS[engine].home if engine in ADAPTERS else "")
        jobs.append(DownloadJob(id=e["id"], urls=[e["original_url"], *e["fallback_urls"]], referer=referer, stem=stem))
    return jobs


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------


def _engine_summary(run: EngineRun) -> dict[str, Any]:
    return {
        "ok": run.ok,
        "error": run.error,
        "elapsed_s": run.elapsed_s,
        "results_found": len(run.results),
        "searches": run.searches,
    }


async def run_search(
    spec: SearchSpec,
    *,
    output_root: Path | str,
    request_id: str | None = None,
    adapters: dict[str, Any] | None = None,
    inspector: Inspector | None = None,
    fetch: Callable[..., tuple[bytes, str]] | None = None,
    allow_private_hosts: bool = False,
    log: Callable[[str], None] = lambda _m: None,
) -> dict[str, Any]:
    adapters = adapters or ADAPTERS
    root = Path(output_root)
    rid, req_dir = create_request_dir(root, request_id)
    images_dir = req_dir / IMAGES_DIRNAME
    raw_dir = req_dir / "_bruto"
    json_path = req_dir / JSON_NAME
    started_at = datetime.now().astimezone()
    t0 = time.monotonic()

    state: dict[str, Any] = {
        "request_id": rid,
        "status": "running",
        "stage": "buscando",
        "created_at": started_at.isoformat(timespec="seconds"),
        "finished_at": None,
        "request": spec.to_dict(),
        "totals": {},
        "imagens": [],
        "engines": {},
        "warnings": [],
        "sites": [],
        "results": [],
    }
    write_json_atomic(json_path, state)
    log(f"[{rid}] pasta: {req_dir}")

    try:
        # ---- 1) buscadores ------------------------------------------------
        raw_dir.mkdir(exist_ok=True)
        runs: list[EngineRun] = []

        async def run_engine(name: str) -> EngineRun:
            log(f"[{rid}] {name}: buscando…")
            run = await adapters[name].run(spec, raw_dir)
            state["engines"][name] = _engine_summary(run)
            write_json_atomic(json_path, state)
            if run.ok:
                log(f"[{rid}] {name}: {len(run.results)} resultado(s) em {run.elapsed_s}s")
            else:
                log(f"[{rid}] {name}: FALHOU — {run.error}")
            return run

        if spec.parallel_engines and len(spec.engines) > 1:
            runs = list(await asyncio.gather(*(run_engine(n) for n in spec.engines)))
        else:
            for name in spec.engines:
                runs.append(await run_engine(name))

        # ---- 2) sites de origem ------------------------------------------
        sites: dict[str, dict[str, Any]] = {}
        for run in runs:
            for site in run.sites:
                sites.setdefault(site["source_page"], site)
        if spec.inspect_sources:
            state["stage"] = "sites_de_origem"
            write_json_atomic(json_path, state)
            all_hits = [h for r in runs for h in r.results]
            await inspect_missing_sources(all_hits, sites, spec, inspector=inspector, log=lambda m: log(f"[{rid}] {m}"))

        # ---- 3) lista de imagens + download ------------------------------
        images = build_images(spec, runs, sites)
        if spec.download and images:
            state["stage"] = "baixando"
            write_json_atomic(json_path, state)
            log(f"[{rid}] baixando {len(images)} imagem(ns)…")
            results = await download_images(
                make_jobs(images),
                images_dir,
                concurrency=spec.download_concurrency,
                allow_private_hosts=allow_private_hosts,
                fetch=fetch,
            )
        else:
            results = {}

        for e in images:
            r = results.get(e["id"])
            e["downloaded"] = bool(r and r["ok"])
            e["file"] = f"{IMAGES_DIRNAME}/{r['file']}" if r and r["ok"] else None
            e["bytes"] = r["bytes"] if r else None
            e["content_type"] = r["content_type"] if r else None
            e["download_url_used"] = r["url_used"] if r else None
            e["error"] = r["error"] if r and not r["ok"] else None
            e.pop("fallback_urls", None)
        ordered = [
            {k: e.get(k) for k in (
                "id", "name", "file", "downloaded", "original_url", "og", "source_page", "origin",
                "engines", "queries", "kind", "title", "alt", "width", "height", "orientation",
                "aspect_ratio", "thumbnail_url", "bytes", "content_type", "download_url_used",
                "error", "found_by",
            )}
            for e in images
        ]

        # ---- 4) fechamento -----------------------------------------------
        warnings: list[str] = []
        all_hits = [h for r in runs for h in r.results]
        if spec.inspect_sources:
            no_page = sum(1 for h in all_hits if not h["source_page"])
            blocked = sum(1 for h in all_hits if h.get("source_blocked"))
            if no_page:
                warnings.append(
                    f"{no_page} resultado(s) sem página de origem não puderam ser catalogados "
                    "(alguns buscadores só informam a origem ao abrir o detalhe; no Brave use click_details=true)."
                )
            if blocked:
                warnings.append(
                    f"{blocked} resultado(s) apontam para um buscador como origem e foram ignorados "
                    "(libere com allow_search_engine_sources)."
                )
        if spec.download_mode == "source" and not ordered and all_hits:
            warnings.append("modo 'source': nenhum site de origem pôde ser catalogado, então nada foi baixado.")
        for r in runs:
            for s_ in r.searches:
                if s_.get("warning"):
                    warnings.append(f"{r.engine} / '{s_['query']}': {s_['warning']}")

        downloaded = sum(1 for e in ordered if e["downloaded"])
        failed = sum(1 for e in ordered if spec.download and not e["downloaded"])
        search_failures = sum(1 for r in runs for s in r.searches if not s["ok"])
        engine_failures = sum(1 for r in runs if not r.ok)
        total_hits = sum(len(r.results) for r in runs)
        if not ordered and total_hits == 0:
            status = "error"
        elif engine_failures or search_failures or failed or (spec.download_mode == "source" and not ordered):
            status = "partial"
        else:
            status = "ok"

        state.update(
            status=status,
            stage="concluido",
            warnings=warnings,
            finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            totals={
                "results_found": total_hits,
                "unique_images": len(ordered),
                "downloaded": downloaded,
                "failed": failed,
                "sites_inspected": sum(1 for s in sites.values() if not s.get("blocked") and not s.get("error")),
                "sites_blocked": sum(1 for s in sites.values() if s.get("blocked")),
                "elapsed_s": round(time.monotonic() - t0, 2),
            },
            imagens=ordered,
            sites=[
                {k: s.get(k) for k in ("source_page", "og", "image_count", "error", "blocked", "blocked_reason", "images")}
                for s in sites.values()
            ],
            results=[
                {k: v for k, v in h.items() if k != "fallback_urls"} for r in runs for h in r.results
            ],
        )
        write_json_atomic(json_path, state)
        log(f"[{rid}] {status}: {downloaded}/{len(ordered)} imagem(ns) em {req_dir}")
        return state
    except Exception as exc:
        state.update(
            status="error",
            stage="erro",
            error=f"{type(exc).__name__}: {exc}",
            finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        write_json_atomic(json_path, state)
        raise
    finally:
        if not spec.keep_raw:
            shutil.rmtree(raw_dir, ignore_errors=True)
