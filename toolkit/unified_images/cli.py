"""Linha de comando: serve | search | engines."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .adapters import ADAPTERS
from .orchestrator import run_search
from .spec import ENGINE_NAMES, SearchSpec


def _parse_opts(items: list[str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for item in items:
        if "=" not in item or "." not in item.split("=", 1)[0]:
            raise SystemExit(f"--opt inválido: {item!r}. Use buscador.opção=valor (ex.: bing.aspect=wide)")
        key, value = item.split("=", 1)
        engine, name = key.split(".", 1)
        out.setdefault(engine.strip().lower(), {})[name.strip()] = value
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="unified_images", description="Busca de imagens unificada (Yandex, Bing, Brave, Startpage).")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="sobe a API HTTP")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8010)

    sub.add_parser("engines", help="lista buscadores e filtros")

    r = sub.add_parser("search", help="faz uma requisição direto pelo terminal")
    r.add_argument("-q", "--query", action="append", required=True, help="termo (repita para várias buscas em sequência)")
    r.add_argument("--engines", nargs="+", default=["all"], help=f"{' '.join(ENGINE_NAMES)} ou all")
    r.add_argument("--limit", type=int, default=5)
    r.add_argument("--orientation", default="any", help="any | horizontal | vertical | square")
    r.add_argument("--square-tolerance", type=float, default=0.1)
    r.add_argument("--no-download", action="store_true", help="só lista; não baixa")
    r.add_argument("--download-mode", choices=("direct", "source", "both"), default="direct")
    r.add_argument("--inspect-sources", action="store_true")
    r.add_argument("--max-images-per-site", type=int, default=50)
    r.add_argument("--allow-google-source", action="store_true")
    r.add_argument("--allow-search-engine-sources", action="store_true")
    r.add_argument("--min-source-side", type=int, default=0)
    r.add_argument("--headless", action="store_true")
    r.add_argument("--pause-ms", type=int, default=1500)
    r.add_argument("--parallel-engines", action="store_true")
    r.add_argument("--download-concurrency", type=int, default=6)
    r.add_argument("--keep-raw", action="store_true")
    r.add_argument("--opt", action="append", default=[], metavar="BUSCADOR.OPÇÃO=VALOR",
                   help="filtro próprio, ex.: --opt bing.aspect=wide --opt startpage.max_pages=3")
    r.add_argument("--out", default="saidas", help="pasta onde ficam as pastas de requisição")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "serve":
        from .api import serve

        serve(args.host, args.port)
        return 0

    if args.cmd == "engines":
        print(json.dumps({n: a.describe() for n, a in ADAPTERS.items()}, ensure_ascii=False, indent=2))
        return 0

    try:
        spec = SearchSpec.from_dict(
            dict(
                queries=args.query, engines=args.engines, limit=args.limit, orientation=args.orientation,
                square_tolerance=args.square_tolerance, download=not args.no_download,
                download_mode=args.download_mode, inspect_sources=args.inspect_sources,
                max_images_per_site=args.max_images_per_site,
                allow_google_source=args.allow_google_source,
                allow_search_engine_sources=args.allow_search_engine_sources,
                min_source_side=args.min_source_side, headless=args.headless,
                pause_between_ms=args.pause_ms, parallel_engines=args.parallel_engines,
                download_concurrency=args.download_concurrency, keep_raw=args.keep_raw,
                engine_options=_parse_opts(args.opt),
            )
        )
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    state: dict[str, Any] = asyncio.run(run_search(spec, output_root=Path(args.out), log=print))
    t = state["totals"]
    print(
        f"\n{state['status'].upper()} — {t['downloaded']}/{t['unique_images']} imagem(ns) baixada(s)\n"
        f"pasta: {Path(args.out).resolve() / state['request_id']}"
    )
    for w in state.get("warnings", []):
        print(f"aviso: {w}")
    return 0 if state["status"] != "error" else 1
