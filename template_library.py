"""Biblioteca/contrato dos templates do DarkPlanner Studio.

Carrega o biblioteca-editorial.json incluído no projeto, expõe um catálogo
compacto para o editor e cria/verifica o manifesto de áudios necessários.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
LIBRARY_JSON = BASE_DIR / "assets" / "darkplanner" / "biblioteca-editorial.json"
AUDIO_DIR = BASE_DIR / "assets" / "darkplanner" / "audio_templates"
AUDIO_MANIFEST = AUDIO_DIR / "AUDIO_NECESSARIOS.txt"

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac", ".opus", ".wma", ".aiff", ".aif", ".alac", ".amr", ".caf"}

_CACHE: Optional[Dict[str, Any]] = None


def _strip_resource_prefix(value: str) -> str:
    value = str(value).strip().replace("\\", "/")
    for prefix in ("tpl:", "asset:", "audio:", "sound:"):
        if value.lower().startswith(prefix):
            return value[len(prefix):]
    return value


def load_library(force_reload: bool = False) -> Dict[str, Any]:
    global _CACHE
    if _CACHE is not None and not force_reload:
        return _CACHE
    if not LIBRARY_JSON.exists():
        raise FileNotFoundError(f"Biblioteca editorial não encontrada: {LIBRARY_JSON}")
    with LIBRARY_JSON.open("r", encoding="utf-8-sig") as f:
        _CACHE = json.load(f)
    return _CACHE


def get_template(template_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not template_id or template_id in {"none", "", None}:
        return None
    return (load_library().get("templates") or {}).get(template_id)


def list_templates(include_manual: bool = True) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for template_id, data in (load_library().get("templates") or {}).items():
        if not include_manual and data.get("manualOnly"):
            continue
        fisica = data.get("fisica") or {}
        perfil = data.get("perfil") or {}
        out.append({
            "id": template_id,
            "nome": data.get("nome") or template_id,
            "slots": fisica.get("slots", 1),
            "durS": fisica.get("durS"),
            "motion": fisica.get("motion") or [],
            "fundos": fisica.get("fundos") or [],
            "renderer": fisica.get("renderer"),
            "familia": perfil.get("familia"),
            "papel": perfil.get("papel"),
            "autoEligible": bool(data.get("autoEligible")),
            "manualOnly": bool(data.get("manualOnly")),
            "whenToUse": data.get("whenToUse") or [],
            "whenNotToUse": data.get("whenNotToUse") or [],
            "coversCaption": bool(data.get("coversCaption")),
        })
    return out


def _iter_strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_strings(v)
    elif isinstance(obj, str):
        yield obj


def required_audio_names() -> List[str]:
    found = set()
    data = load_library()
    for raw in _iter_strings(data):
        cleaned = _strip_resource_prefix(raw)
        name = Path(cleaned).name
        if Path(name).suffix.lower() in AUDIO_EXTENSIONS:
            found.add(name)
    for tpl in (data.get("templates") or {}).values():
        for raw in ((tpl.get("fisica") or {}).get("sons") or []):
            cleaned = _strip_resource_prefix(raw)
            name = Path(cleaned).name
            if Path(name).suffix:
                found.add(name)
        audio = (tpl.get("perfil") or {}).get("audio") or {}
        for key in ("principal", "apoio", "contextual"):
            raw = audio.get(key)
            if not raw:
                continue
            cleaned = _strip_resource_prefix(raw)
            name = Path(cleaned).name
            if Path(name).suffix:
                found.add(name)
            else:
                found.add(name + ".mp3")
    return sorted(x for x in found if Path(x).suffix.lower() in AUDIO_EXTENSIONS)


def ensure_audio_manifest() -> Path:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    names = required_audio_names()
    lines = [
        "ÁUDIOS NECESSÁRIOS PARA TEMPLATES/DESTAQUES",
        "=" * 60,
        "",
        *[f"{i}. {name}" for i, name in enumerate(names, 1)],
        "",
        "Coloque os arquivos nesta pasta:",
        str(AUDIO_DIR),
        "",
        "O renderer usa o nome do arquivo exatamente como listado acima.",
    ]
    AUDIO_MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return AUDIO_MANIFEST


def resolve_audio(name: str) -> Optional[str]:
    """Resolve um áudio pelo nome/prefixo. Retorna None se ainda não foi colocado."""
    cleaned = Path(_strip_resource_prefix(name)).name
    candidate = AUDIO_DIR / cleaned
    if candidate.exists():
        return str(candidate)
    # Alguns campos do perfil omitem a extensão.
    if not candidate.suffix:
        mp3 = AUDIO_DIR / f"{cleaned}.mp3"
        if mp3.exists():
            return str(mp3)
        wav = AUDIO_DIR / f"{cleaned}.wav"
        if wav.exists():
            return str(wav)
    return None


def summarize_template(template_id: str) -> Dict[str, Any]:
    tpl = get_template(template_id)
    if not tpl:
        return {}
    f = tpl.get("fisica") or {}
    p = tpl.get("perfil") or {}
    return {
        "id": template_id,
        "nome": tpl.get("nome"),
        "slots": f.get("slots"),
        "durS": f.get("durS"),
        "motion": f.get("motion") or [],
        "fundos": f.get("fundos") or [],
        "sons": f.get("sons") or [],
        "renderer": f.get("renderer"),
        "composition": f.get("composition"),
        "visualMotion": f.get("visualMotion"),
        "perfil": p,
        "textFields": tpl.get("textFields") or [],
        "coversCaption": bool(tpl.get("coversCaption")),
    }
