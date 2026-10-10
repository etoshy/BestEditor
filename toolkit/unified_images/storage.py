"""Pasta por requisição: <raiz>/<id_unico>/{imagens/, imagens.json}."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

IMAGES_DIRNAME = "imagens"
JSON_NAME = "imagens.json"
_ID_RE = re.compile(r"^\d{8}-\d{6}_[0-9a-f]{8}$")


def new_request_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}_{uuid.uuid4().hex[:8]}"


def is_valid_request_id(value: str) -> bool:
    return bool(_ID_RE.match(value or ""))


def create_request_dir(root: Path, request_id: str | None = None) -> tuple[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    rid = request_id or new_request_id()
    if not is_valid_request_id(rid):
        raise ValueError(f"request_id inválido: {rid!r}")
    path = root / rid
    path.mkdir(parents=True, exist_ok=request_id is not None)
    (path / IMAGES_DIRNAME).mkdir(exist_ok=True)
    return rid, path


def write_json_atomic(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_request(root: Path, request_id: str) -> dict[str, Any] | None:
    if not is_valid_request_id(request_id):
        return None
    path = root / request_id / JSON_NAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_requests(root: Path, limit: int = 100) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    items = []
    for child in sorted((p for p in root.iterdir() if p.is_dir() and is_valid_request_id(p.name)), reverse=True):
        data = None
        try:
            data = load_request(root, child.name)
        except (OSError, ValueError):
            pass
        data = data or {}
        totals = data.get("totals") or {}
        items.append(
            {
                "request_id": child.name,
                "status": data.get("status", "desconhecido"),
                "created_at": data.get("created_at"),
                "engines": (data.get("request") or {}).get("engines"),
                "unique_images": totals.get("unique_images"),
                "downloaded": totals.get("downloaded"),
            }
        )
        if len(items) >= limit:
            break
    return items


def resolve_image_path(root: Path, request_id: str, filename: str) -> Path | None:
    """Caminho seguro de uma imagem da requisição (nada fora da pasta imagens/)."""
    if not is_valid_request_id(request_id) or not filename or filename != Path(filename).name:
        return None
    base = (root / request_id / IMAGES_DIRNAME).resolve()
    target = (base / filename).resolve()
    if base not in target.parents or not target.is_file():
        return None
    return target
