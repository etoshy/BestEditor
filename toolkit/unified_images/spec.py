"""Pedido de busca unificado (validação sem depender de FastAPI/pydantic)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

ENGINE_NAMES: tuple[str, ...] = ("yandex", "bing", "brave", "startpage")
DOWNLOAD_MODES = ("direct", "source", "both")
MAX_LIMIT = 50

ORIENTATION_ALIASES = {
    "": "any", "any": "any", "qualquer": "any", "todas": "any", "todos": "any",
    "horizontal": "horizontal", "landscape": "horizontal", "wide": "horizontal",
    "paisagem": "horizontal", "deitada": "horizontal",
    "vertical": "vertical", "portrait": "vertical", "tall": "vertical",
    "retrato": "vertical", "em_pe": "vertical", "empe": "vertical",
    "square": "square", "quadrada": "square", "quadrado": "square", "quadro": "square",
}


def normalize_orientation(value: str | None) -> str:
    key = (value or "any").strip().lower().replace(" ", "_").replace("-", "_")
    if key not in ORIENTATION_ALIASES:
        raise ValueError(
            "orientation deve ser: any (qualquer), horizontal, vertical ou square (quadrada)."
        )
    return ORIENTATION_ALIASES[key]


def normalize_engines(value: Any) -> list[str]:
    """Aceita lista, 'yandex,bing' ou 'all'/'todos'. Remove repetidos mantendo a ordem."""
    if value is None:
        return list(ENGINE_NAMES)
    if isinstance(value, str):
        value = [p for p in value.replace(";", ",").split(",")]
    out: list[str] = []
    for raw in value:
        name = str(raw).strip().lower()
        if not name:
            continue
        if name in {"all", "todos", "todas", "*"}:
            for n in ENGINE_NAMES:
                if n not in out:
                    out.append(n)
            continue
        if name not in ENGINE_NAMES:
            raise ValueError(
                f"Buscador desconhecido: '{name}'. Use: {', '.join(ENGINE_NAMES)} ou 'all'."
            )
        if name not in out:
            out.append(name)
    if not out:
        raise ValueError("Informe ao menos um buscador em 'engines'.")
    return out


def normalize_queries(queries: Any, default_limit: int, default_orientation: str) -> list[dict[str, Any]]:
    """['termo', {'q': 'termo', 'limit': 10, 'orientation': 'vertical'}] -> lista padronizada."""
    if isinstance(queries, str):
        queries = [queries]
    if not isinstance(queries, (list, tuple)):
        raise ValueError("'queries' deve ser uma lista de termos.")
    out: list[dict[str, Any]] = []
    for item in queries:
        if isinstance(item, str):
            q, lim, ori = item.strip(), default_limit, default_orientation
        elif isinstance(item, dict):
            q = str(item.get("q", "")).strip()
            lim = int(item.get("limit") or default_limit)
            ori = normalize_orientation(item.get("orientation") or default_orientation)
        else:
            continue
        if not q:
            continue
        if lim < 1 or lim > MAX_LIMIT:
            raise ValueError(f"limit de '{q}' deve ficar entre 1 e {MAX_LIMIT}.")
        out.append({"q": q, "limit": lim, "orientation": ori})
    if not out:
        raise ValueError("Informe ao menos um termo de busca em 'queries'.")
    return out


@dataclass
class SearchSpec:
    queries: list[Any]
    engines: list[str] = field(default_factory=lambda: list(ENGINE_NAMES))

    # --- filtros comuns (valem para todos os buscadores) ---
    limit: int = 5
    orientation: str = "any"
    square_tolerance: float = 0.1

    # --- download / sites de origem ---
    download: bool = True
    download_mode: str = "direct"          # direct | source | both
    inspect_sources: bool = False
    max_images_per_site: int = 50
    allow_google_source: bool = False
    allow_search_engine_sources: bool = False
    min_source_side: int = 0               # ignora imagens de origem menores que isso (px)

    # --- execução ---
    headless: bool = False
    pause_between_ms: int = 1500
    parallel_engines: bool = False
    download_concurrency: int = 6
    keep_raw: bool = False

    # --- filtros/opções específicos de cada buscador ---
    engine_options: dict[str, dict[str, Any]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SearchSpec":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"Parâmetros desconhecidos: {', '.join(unknown)}")
        spec = cls(**data)
        spec.validate()
        return spec

    def validate(self) -> None:
        from .adapters import ADAPTERS  # evita import circular

        self.engines = normalize_engines(self.engines)
        self.orientation = normalize_orientation(self.orientation)
        self.limit = int(self.limit)
        if not 1 <= self.limit <= MAX_LIMIT:
            raise ValueError(f"limit deve ficar entre 1 e {MAX_LIMIT}.")
        self.square_tolerance = float(self.square_tolerance)
        if not 0 <= self.square_tolerance <= 0.5:
            raise ValueError("square_tolerance deve ficar entre 0 e 0.5.")
        self.queries = normalize_queries(self.queries, self.limit, self.orientation)

        if self.download_mode not in DOWNLOAD_MODES:
            raise ValueError("download_mode deve ser: direct, source ou both.")
        self.max_images_per_site = int(self.max_images_per_site)
        if not 1 <= self.max_images_per_site <= 500:
            raise ValueError("max_images_per_site deve ficar entre 1 e 500.")
        self.min_source_side = int(self.min_source_side)
        if self.min_source_side < 0:
            raise ValueError("min_source_side deve ser >= 0.")
        self.pause_between_ms = int(self.pause_between_ms)
        if not 0 <= self.pause_between_ms <= 60_000:
            raise ValueError("pause_between_ms deve ficar entre 0 e 60000.")
        self.download_concurrency = int(self.download_concurrency)
        if not 1 <= self.download_concurrency <= 16:
            raise ValueError("download_concurrency deve ficar entre 1 e 16.")

        # Baixar do site de origem exige catalogar o site de origem.
        if self.download_mode in ("source", "both"):
            self.inspect_sources = True

        # engine_options: só buscadores existentes e só opções que o motor entende.
        clean: dict[str, dict[str, Any]] = {}
        for engine, opts in (self.engine_options or {}).items():
            engine = str(engine).strip().lower()
            if engine not in ADAPTERS:
                raise ValueError(f"engine_options: buscador desconhecido '{engine}'.")
            clean[engine] = ADAPTERS[engine].validate_options(opts or {})
        self.engine_options = clean

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
