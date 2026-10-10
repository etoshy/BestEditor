"""Adaptadores: um por buscador.

Cada adaptador faz duas coisas e nada além disso:
  1. traduz o pedido unificado (`SearchSpec`) para os parâmetros do
     `search_images_batch()` do motor original;
  2. converte o que o motor devolveu para um formato único.

O download e a visita aos sites de origem NÃO são feitos pelos motores
(`download=False`, `inspect_sources=False`): isso é feito de forma igual para
todos pela camada unificada. A única exceção é o Yandex, que precisa da própria
sessão para descobrir a página de origem de cada resultado — então ele cataloga
as origens sozinho e o catálogo é apenas convertido para o formato comum.
"""

from __future__ import annotations

import importlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Formato comum
# ---------------------------------------------------------------------------


@dataclass
class EngineRun:
    engine: str
    ok: bool = False
    error: str | None = None
    elapsed_s: float = 0.0
    searches: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    sites: list[dict[str, Any]] = field(default_factory=list)  # catálogos de origem já prontos


def _to_int(value: Any) -> int | None:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _http_url(value: Any) -> str:
    """Só devolve URLs http(s); descarta data:, blob:, vazio etc."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value:
        return ""
    return value if urlparse(value).scheme in ("http", "https") else ""


_ENGINE_DATA_KEYS: dict[str, tuple[str, ...]] = {
    "yandex": ("yandex_rank", "result_url", "source_domain", "source_blocked", "source_blocked_reason"),
    "bing": ("media_id", "cid", "md5", "description", "bing_result_url"),
    "brave": ("brave_rank", "source", "detail_url", "proxy_url", "detail_opened", "original_source_url"),
    "startpage": ("detail_url", "source_domain"),
}


def normalize_result(engine: str, query: str, raw: dict[str, Any], rank: int) -> dict[str, Any]:
    original = _http_url(raw.get("original_url"))
    candidates: list[str] = []
    for url in (original, _http_url(raw.get("thumbnail_url")), _http_url(raw.get("proxy_url"))):
        if url and url not in candidates:
            candidates.append(url)

    width, height = _to_int(raw.get("width")), _to_int(raw.get("height"))
    return {
        "engine": engine,
        "query": query,
        "rank": raw.get("rank") or rank,
        "title": (raw.get("title") or raw.get("alt") or raw.get("description") or "").strip(),
        "alt": (raw.get("alt") or "").strip(),
        # original_url = melhor URL conhecida da imagem; as demais viram reserva de download
        "original_url": candidates[0] if candidates else "",
        "fallback_urls": candidates[1:],
        "thumbnail_url": _http_url(raw.get("thumbnail_url")) or _http_url(raw.get("proxy_url")),
        "source_page": _http_url(raw.get("source_page")),
        "width": width,
        "height": height,
        "thumb_width": _to_int(raw.get("thumb_width")),
        "thumb_height": _to_int(raw.get("thumb_height")),
        "aspect_ratio": raw.get("aspect_ratio"),
        "orientation": raw.get("orientation"),
        "orientation_source": raw.get("orientation_source"),
        "engine_data": {
            k: raw[k] for k in _ENGINE_DATA_KEYS.get(engine, ()) if raw.get(k) not in (None, "", False)
        },
    }


def normalize_site(site: dict[str, Any]) -> dict[str, Any]:
    images = []
    for img in site.get("images") or site.get("source_images") or []:
        url = _http_url(img.get("url") or img.get("original_url"))
        if not url:
            continue
        images.append(
            {
                "name": img.get("name") or "",
                "url": url,
                "kind": img.get("kind") or "",
                "alt": img.get("alt") or "",
                "title": img.get("title") or "",
                "width": _to_int(img.get("width")),
                "height": _to_int(img.get("height")),
            }
        )
    return {
        "source_page": site.get("source_page") or "",
        "og": dict(site.get("og") or {}),
        "image_count": len(images),
        "images": images,
        "error": site.get("error"),
        "blocked": False,
        "blocked_reason": "",
        "result_image_url": site.get("result_image_url") or "",
    }


def normalize_search_entry(entry: dict[str, Any]) -> dict[str, Any]:
    stats = entry.get("scan_stats") or {}
    return {
        "index": entry.get("index"),
        "query": entry.get("query"),
        "ok": bool(entry.get("ok")),
        "error": entry.get("error"),
        "results_found": entry.get("results_found", 0),
        "limit_requested": entry.get("limit_requested"),
        "orientation_filter": entry.get("orientation_filter"),
        "search_method": entry.get("search_method"),
        "search_url": entry.get("search_url"),
        "warning": stats.get("warning"),
        "scan_stats": stats,
    }


# ---------------------------------------------------------------------------
# Opções específicas de cada buscador
# ---------------------------------------------------------------------------

_TRUE = {"1", "true", "t", "yes", "y", "sim", "s", "on"}
_FALSE = {"0", "false", "f", "no", "n", "nao", "não", "off", ""}


@dataclass(frozen=True)
class OptionSpec:
    kind: str                      # bool | int | str | choice
    doc: str
    choices: tuple[str, ...] = ()
    min: int | None = None
    max: int | None = None
    default: Any = None

    def coerce(self, name: str, value: Any) -> Any:
        if self.kind == "bool":
            if isinstance(value, bool):
                return value
            key = str(value).strip().lower()
            if key in _TRUE:
                return True
            if key in _FALSE:
                return False
            raise ValueError(f"opção '{name}' deve ser true/false.")
        if self.kind == "int":
            try:
                n = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"opção '{name}' deve ser um número inteiro.") from None
            if self.min is not None and n < self.min or self.max is not None and n > self.max:
                raise ValueError(f"opção '{name}' deve ficar entre {self.min} e {self.max}.")
            return n
        text = str(value).strip()
        if self.kind == "choice":
            text = text.lower()
            if text not in self.choices:
                raise ValueError(f"opção '{name}' deve ser uma de: {', '.join(self.choices)}.")
        return text


_SUBMIT = OptionSpec(
    "choice", "como enviar buscas seguidas na mesma aba",
    choices=("auto", "enter", "click"), default="auto",
)


# ---------------------------------------------------------------------------
# Adaptadores
# ---------------------------------------------------------------------------


class EngineAdapter:
    name: str = ""
    label: str = ""
    module: str = ""
    home: str = ""
    options: dict[str, OptionSpec] = {}
    native_source_catalog: bool = False   # True = o motor cataloga origens na própria sessão
    notes: str = ""

    # -- opções ---------------------------------------------------------
    def validate_options(self, opts: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in opts.items():
            if key not in self.options:
                valid = ", ".join(self.options) or "(nenhuma)"
                raise ValueError(
                    f"opção '{key}' não existe para o buscador '{self.name}'. Opções: {valid}."
                )
            clean[key] = self.options[key].coerce(key, value)
        return clean

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "native_source_catalog": self.native_source_catalog,
            "notes": self.notes,
            "options": {
                k: {
                    "type": o.kind,
                    "doc": o.doc,
                    **({"choices": list(o.choices)} if o.choices else {}),
                    **({"default": o.default} if o.default is not None else {}),
                }
                for k, o in self.options.items()
            },
        }

    # -- execução -------------------------------------------------------
    def load_module(self):
        return importlib.import_module(f"{__package__}.engines.{self.module}")

    def build_kwargs(self, spec, raw_dir: Path) -> dict[str, Any]:  # pragma: no cover - abstrato
        raise NotImplementedError

    def opt(self, spec, name: str) -> Any:
        given = (spec.engine_options or {}).get(self.name, {})
        if name in given:
            return given[name]
        return self.options[name].default

    async def run(self, spec, raw_dir: Path) -> EngineRun:
        started = time.monotonic()
        try:
            module = self.load_module()
            kwargs = self.build_kwargs(spec, raw_dir)
            payload = await module.search_images_batch(**kwargs)
            run = self.normalize(payload)
        except Exception as exc:  # um buscador que falha não derruba os outros
            run = EngineRun(engine=self.name, ok=False, error=f"{type(exc).__name__}: {exc}")
        run.elapsed_s = round(time.monotonic() - started, 2)
        return run

    def normalize(self, payload: dict[str, Any]) -> EngineRun:
        run = EngineRun(engine=self.name, ok=bool(payload.get("ok")))
        seen_sites: set[str] = set()
        for entry in payload.get("searches", []):
            query = entry.get("query") or ""
            run.searches.append(normalize_search_entry(entry))
            hits = [
                normalize_result(self.name, query, raw, n)
                for n, raw in enumerate(entry.get("results") or [], start=1)
            ]
            run.results.extend(hits)

            catalog = entry.get("source_catalog") or {}
            for raw_site in catalog.get("sites", []):
                site = normalize_site(raw_site)
                if not site["source_page"] or site["source_page"] in seen_sites:
                    continue
                seen_sites.add(site["source_page"])
                run.sites.append(site)
                # liga o site ao resultado que o originou (o Yandex só preenche
                # source_page dentro do catálogo)
                for hit in hits:
                    if not hit["source_page"] and hit["original_url"] == site["result_image_url"]:
                        hit["source_page"] = site["source_page"]
        if not run.ok:
            errors = [s["error"] for s in run.searches if s.get("error")]
            run.error = "; ".join(dict.fromkeys(errors))[:500] or "nenhuma busca teve sucesso"
        return run


class YandexAdapter(EngineAdapter):
    name = "yandex"
    label = "Yandex Images"
    module = "yandex_image_api"
    home = "https://yandex.com/"
    native_source_catalog = True
    options: dict[str, OptionSpec] = {}
    notes = (
        "Filtro de proporção medido pela thumbnail. Descobre a página de origem na própria "
        "sessão do Yandex (por isso cataloga as origens sozinho). Pode pedir captcha: "
        "resolva no navegador (use headless=false)."
    )

    def build_kwargs(self, spec, raw_dir: Path) -> dict[str, Any]:
        return dict(
            queries=spec.queries,
            limit=spec.limit,
            orientation=spec.orientation,
            square_tolerance=spec.square_tolerance,
            inspect_sources=spec.inspect_sources,
            download=False,
            download_mode="yandex",
            headless=spec.headless,
            output_dir=str(raw_dir / "yandex"),
            json_path=str(raw_dir / "yandex.json"),
            allow_google_source=spec.allow_google_source,
            allow_search_engine_sources=spec.allow_search_engine_sources,
            max_images_per_site=spec.max_images_per_site,
            pause_between_ms=spec.pause_between_ms,
        )


class BingAdapter(EngineAdapter):
    name = "bing"
    label = "Bing Images"
    module = "bing_image_api"
    home = "https://www.bing.com/"
    options = {
        "aspect": OptionSpec("choice", "filtro do próprio Bing", choices=("wide", "tall", "square")),
        "size": OptionSpec(
            "choice", "tamanho do próprio Bing", choices=("large", "wallpaper", "medium", "small")
        ),
        "animated": OptionSpec("bool", "só GIFs animados", default=False),
        "transparent": OptionSpec("bool", "só PNG com transparência", default=False),
        "extra_qft": OptionSpec("str", "fragmento qft extra do Bing, ex.: filterui:photo-photo"),
        "mkt": OptionSpec("str", "mercado/idioma do Bing", default="pt-BR"),
        "click_details": OptionSpec("bool", "abrir o detalhe de cada resultado (mais lento)", default=True),
        "submit_method": _SUBMIT,
    }
    notes = "Filtros próprios do Bing (aspect/size/animated/transparent) + filtro de proporção medido na imagem."

    def build_kwargs(self, spec, raw_dir: Path) -> dict[str, Any]:
        return dict(
            queries=spec.queries,
            limit=spec.limit,
            aspect=self.opt(spec, "aspect"),
            animated=self.opt(spec, "animated"),
            transparent=self.opt(spec, "transparent"),
            size=self.opt(spec, "size"),
            extra_qft=self.opt(spec, "extra_qft"),
            mkt=self.opt(spec, "mkt"),
            orientation=spec.orientation,
            square_tolerance=spec.square_tolerance,
            click_details=self.opt(spec, "click_details"),
            submit_method=self.opt(spec, "submit_method"),
            headless=spec.headless,
            download=False,
            output_dir=str(raw_dir / "bing"),
            pause_between_ms=spec.pause_between_ms,
        )


class BraveAdapter(EngineAdapter):
    name = "brave"
    label = "Brave Images"
    module = "brave_image_api"
    home = "https://search.brave.com/"
    options = {
        "click_details": OptionSpec(
            "bool",
            "abrir o detalhe de cada resultado para descobrir a página de origem "
            "(sem isso o Brave não informa o source_page)",
            default=True,
        ),
    }
    notes = "Filtro de proporção medido pela thumbnail. Pode exibir verificação anti-bot."

    def build_kwargs(self, spec, raw_dir: Path) -> dict[str, Any]:
        return dict(
            queries=spec.queries,
            limit=spec.limit,
            headless=spec.headless,
            click_details=self.opt(spec, "click_details"),
            download=False,
            download_mode="original",
            output_dir=str(raw_dir / "brave"),
            pause_between_ms=spec.pause_between_ms,
            orientation=spec.orientation,
            square_tolerance=spec.square_tolerance,
            inspect_sources=False,
            allow_google_source=spec.allow_google_source,
            allow_search_engine_sources=spec.allow_search_engine_sources,
            max_images_per_site=spec.max_images_per_site,
        )


class StartpageAdapter(EngineAdapter):
    name = "startpage"
    label = "Startpage Images"
    module = "startpage_image_api"
    home = "https://www.startpage.com/"
    options = {
        "click": OptionSpec("bool", "clicar em cada resultado para ler o detalhe", default=True),
        "submit_method": _SUBMIT,
        "max_pages": OptionSpec("int", "páginas lidas até completar o limit", min=1, max=20, default=5),
        "language": OptionSpec("str", "idioma do Startpage", default="english"),
    }
    notes = "Filtro de proporção medido na imagem original (width/height do payload). Pagina sozinho."

    def build_kwargs(self, spec, raw_dir: Path) -> dict[str, Any]:
        return dict(
            queries=spec.queries,
            limit=spec.limit,
            orientation=spec.orientation,
            square_tolerance=spec.square_tolerance,
            click=self.opt(spec, "click"),
            download=False,
            download_mode="startpage",
            inspect_sources=False,
            source_max_images=spec.max_images_per_site,
            submit_method=self.opt(spec, "submit_method"),
            max_pages=self.opt(spec, "max_pages"),
            language=self.opt(spec, "language"),
            headless=spec.headless,
            output_dir=str(raw_dir / "startpage"),
            pause_between_ms=spec.pause_between_ms,
        )


ADAPTERS: dict[str, EngineAdapter] = {
    a.name: a for a in (YandexAdapter(), BingAdapter(), BraveAdapter(), StartpageAdapter())
}

EngineFactory = Callable[[str], EngineAdapter]
