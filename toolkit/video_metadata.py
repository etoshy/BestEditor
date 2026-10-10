"""
video_metadata.py
===================

Liga o título/descrição (e o resto dos metadados) de um vídeo ao arquivo
que foi baixado, de duas formas — feitas pra funcionar juntas ou
separadas:

1) **Sidecar** (sempre disponível, sem dependência nenhuma): grava um
   `<nome-do-video>.json` e um `<nome-do-video>.txt` do lado do
   `.mp4`, com o título, descrição, autor, url original, provedor etc.
   Funciona sempre, em qualquer sistema.

2) **Embutido no próprio arquivo** (precisa de `ffmpeg` instalado): usa
   `ffmpeg -c copy -metadata title=... -metadata description=...` pra
   escrever o título/descrição dentro do container do `.mp4` em si — sem
   recodificar o vídeo (é uma cópia direta dos streams, então é rápido e
   não perde qualidade). Isso faz o título/descrição aparecerem nas
   propriedades do arquivo em players e no explorador de arquivos. Se o
   `ffmpeg` não estiver instalado, essa parte é pulada silenciosamente —
   o sidecar continua funcionando normalmente.

Uso
---
    from video_metadata import attach_metadata

    path = client.download_video(video, output_dir="videos")
    attach_metadata(video, path, provider="pexels")
    # -> cria videos/algum-video.json e videos/algum-video.txt
    #    e, se tiver ffmpeg, embute title/description no próprio .mp4

Funciona com qualquer um dos 5 clientes do toolkit (todos os objetos de
vídeo têm `.to_dict()`), e também com um dict cru (ex: vindo de um
`fontes_combinadas.json` salvo antes).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Union

logger = logging.getLogger("video_metadata")


def metadata_from_video(video: Any, provider: Optional[str] = None) -> Dict[str, Any]:
    """Normaliza os dados de um vídeo (de qualquer um dos 5 clientes, ou
    um dict cru) num dicionário com pelo menos "title" e "description"
    preenchidos (mesmo que vazios), prontos pra gravar como metadado.
    """
    if hasattr(video, "to_dict"):
        data = dict(video.to_dict())
    elif isinstance(video, dict):
        data = dict(video)
    else:
        data = {"raw": str(video)}

    # Cada provedor chama o "nome" do vídeo de um jeito (title, name...);
    # normaliza pra "title" sempre existir.
    title = data.get("title") or data.get("name") or ""
    description = data.get("description") or ""

    data["title"] = title
    data["description"] = description
    if provider and "provider" not in data:
        data["provider"] = provider

    return data


def write_sidecar(
    video_path: Union[str, Path],
    metadata: Dict[str, Any],
    write_json: bool = True,
    write_txt: bool = True,
) -> list:
    """Grava os arquivos de metadado ao lado do vídeo, com o mesmo nome
    (trocando só a extensão): `video.mp4` -> `video.json` / `video.txt`.

    Retorna a lista de caminhos gravados.
    """
    base = Path(video_path)
    written = []

    if write_json:
        json_path = base.with_suffix(".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        written.append(str(json_path))

    if write_txt:
        txt_path = base.with_suffix(".txt")
        lines = [
            f"Título: {metadata.get('title', '')}",
            f"Descrição: {metadata.get('description', '')}",
        ]
        if metadata.get("url"):
            lines.append(f"URL: {metadata['url']}")
        if metadata.get("author"):
            lines.append(f"Autor: {metadata['author']}")
        if metadata.get("provider"):
            lines.append(f"Provedor: {metadata['provider']}")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        written.append(str(txt_path))

    return written


def embed_ffmpeg_metadata(
    video_path: Union[str, Path],
    title: str = "",
    description: str = "",
    timeout: int = 120,
) -> bool:
    """Tenta embutir título/descrição dentro do próprio arquivo de vídeo,
    usando `ffmpeg -c copy` (não recodifica, só reescreve o container —
    rápido e sem perda). Se o `ffmpeg` não estiver instalado, ou o
    comando falhar por qualquer motivo, devolve False sem levantar
    exceção — o vídeo baixado continua intacto, só sem o metadado
    embutido (o sidecar cobre isso de qualquer forma).
    """
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        logger.debug("ffmpeg não encontrado no PATH — pulando embed de metadados.")
        return False

    video_path = Path(video_path)
    if not video_path.exists():
        return False

    tmp_path = video_path.with_name(f"{video_path.stem}__meta_tmp{video_path.suffix}")

    cmd = [
        ffmpeg_bin, "-y",
        "-i", str(video_path),
        "-c", "copy",
        "-metadata", f"title={title}",
        "-metadata", f"description={description}",
        "-metadata", f"comment={description}",
        str(tmp_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("Falha ao rodar ffmpeg em %s: %s", video_path, exc)
        tmp_path.unlink(missing_ok=True)
        return False

    if result.returncode != 0 or not tmp_path.exists() or tmp_path.stat().st_size == 0:
        logger.warning("ffmpeg não conseguiu embutir metadados em %s: %s", video_path, result.stderr[-300:])
        tmp_path.unlink(missing_ok=True)
        return False

    tmp_path.replace(video_path)
    return True


def attach_metadata(
    video: Any,
    video_path: Union[str, Path],
    provider: Optional[str] = None,
    sidecar: bool = True,
    embed: bool = True,
    write_json: bool = True,
    write_txt: bool = True,
) -> Dict[str, Any]:
    """Função principal: junta as duas formas de anexar metadado.

    sidecar=True (padrão): grava .json/.txt do lado do vídeo (sempre funciona).
    embed=True (padrão):   tenta embutir no próprio .mp4 via ffmpeg (se disponível).

    Retorna um dicionário com o que foi feito de verdade:
        {"sidecar_files": [...], "embedded": True/False, "metadata": {...}}
    """
    metadata = metadata_from_video(video, provider=provider)

    sidecar_files = []
    if sidecar:
        try:
            sidecar_files = write_sidecar(video_path, metadata, write_json=write_json, write_txt=write_txt)
        except OSError as exc:
            logger.warning("Falha ao gravar sidecar de metadados para %s: %s", video_path, exc)

    embedded = False
    if embed:
        embedded = embed_ffmpeg_metadata(
            video_path,
            title=metadata.get("title", ""),
            description=metadata.get("description", ""),
        )

    return {"sidecar_files": sidecar_files, "embedded": embedded, "metadata": metadata}
