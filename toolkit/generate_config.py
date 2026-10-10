"""
generate_config.py
====================

Gera (ou mostra) o `toolkit_config.json` — um arquivo de configuração com
uma seção por site (Pexels, Pixabay, Magnific, Mixkit, VistaCreate), mais
as seções `browser` (como o Chrome é aberto) e `downloads` (concorrência,
retries, manifesto).

Uso
---
    python generate_config.py                 # cria toolkit_config.json (se não existir)
    python generate_config.py --force          # sobrescreve o existente
    python generate_config.py --show           # só imprime a config atual (sem gravar)
    python generate_config.py --path outro.json

O arquivo gerado tem esta forma:

    {
      "browser": {
        "headless": false,       # true = roda o Chrome sem mostrar janela
        "show_browser": true,    # oposto de headless, por legibilidade
        "download_dir": "downloads",
        "shared_session": false,  # true = 1 único Chrome pra todos os sites (economiza muita RAM)
        "low_resource": false     # true = bloqueia imagens e desliga recursos que não usamos
      },
      "downloads": {
        "enabled": true,
        "max_workers": 3,             # quantos SITES em paralelo
        "per_provider_workers": 1,    # quantos downloads em paralelo POR site
        "skip_existing": true,        # usa o manifesto pra não rebaixar
        "retries": 3,
        "retry_backoff_seconds": 2,
        "manifest": "downloads_manifest.json",
        "output_dir": "videos",
        "write_metadata": true,         # grava .json/.txt com título/descrição do lado do vídeo
        "embed_ffmpeg_metadata": true   # tenta também embutir no próprio .mp4 (precisa de ffmpeg)
      },
      "providers": {
        "pexels":     {"enabled": true, "query": "dog", "max_pages": 1, "download_count": 2},
        "pixabay":    {"enabled": true, "query": "dog", "max_pages": 1, "download_count": 2},
        "magnific":   {"enabled": true, "query": "dog", "only_free": true, "max_pages": 1, "download_count": 2},
        "mixkit":     {"enabled": true, "category": "animal-nature", "max_pages": 1, "download_count": 2},
        "vistacreate":{"enabled": true, "query": "dog", "max_pages": 1, "download_count": 2}
      }
    }

Edite os valores que quiser: termo/categoria de busca de cada site,
quantas páginas buscar, quantos vídeos baixar, se aquele site está
habilitado, quantos downloads simultâneos, etc. `run_batch.py` lê esse
arquivo automaticamente.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict

CONFIG_FILENAME = "toolkit_config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "browser": {
        "headless": False,
        "show_browser": True,
        "download_dir": "downloads",
        "shared_session": False,
        "low_resource": False,
    },
    "downloads": {
        "enabled": True,
        "max_workers": 3,
        "per_provider_workers": 1,
        "skip_existing": True,
        "retries": 3,
        "retry_backoff_seconds": 2,
        "manifest": "downloads_manifest.json",
        "output_dir": "videos",
        "write_metadata": True,
        "embed_ffmpeg_metadata": True,
    },
    "providers": {
        "pexels": {"enabled": True, "query": "dog", "max_pages": 1, "download_count": 2},
        "pixabay": {"enabled": True, "query": "dog", "max_pages": 1, "download_count": 2},
        "magnific": {"enabled": True, "query": "dog", "only_free": True, "max_pages": 1, "download_count": 2},
        "mixkit": {"enabled": True, "category": "animal-nature", "max_pages": 1, "download_count": 2},
        "vistacreate": {"enabled": True, "query": "dog", "max_pages": 1, "download_count": 2},
    },
}


def generate_default_config(path: str = CONFIG_FILENAME, overwrite: bool = False) -> str:
    """Cria o arquivo de configuração padrão em `path`. Não sobrescreve um
    arquivo já existente a menos que `overwrite=True` — rodar de novo por
    engano não apaga ajustes que você já tenha feito.

    Retorna o caminho do arquivo (criado agora, ou já existente antes).
    """
    if os.path.exists(path) and not overwrite:
        return path
    with open(path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    return path


def load_config(path: str = CONFIG_FILENAME) -> Dict[str, Any]:
    """Carrega o config do disco, mesclado com os padrões (qualquer campo
    que faltar no arquivo do usuário usa o valor padrão). Nunca falha por
    o arquivo não existir — nesse caso devolve os padrões em memória, sem
    criar nada.
    """
    merged = json.loads(json.dumps(DEFAULT_CONFIG))  # cópia profunda simples

    if not os.path.exists(path):
        return merged

    try:
        with open(path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
    except (json.JSONDecodeError, OSError):
        return merged

    for section in ("browser", "downloads"):
        merged[section].update(user_config.get(section, {}))

    for provider, values in user_config.get("providers", {}).items():
        merged["providers"].setdefault(provider, {})
        merged["providers"][provider].update(values)

    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera/mostra o toolkit_config.json (um bloco de config por site).")
    parser.add_argument("--path", default=CONFIG_FILENAME, help=f"Caminho do arquivo (padrão: {CONFIG_FILENAME})")
    parser.add_argument("--force", action="store_true", help="Sobrescreve o arquivo se já existir.")
    parser.add_argument("--show", action="store_true", help="Só imprime a configuração atual, sem gravar nada.")
    args = parser.parse_args()

    if args.show:
        print(json.dumps(load_config(args.path), ensure_ascii=False, indent=2))
        return

    existed = os.path.exists(args.path)
    path = generate_default_config(args.path, overwrite=args.force)

    if existed and not args.force:
        print(f"'{path}' já existe — nada foi sobrescrito (use --force para substituir).")
    else:
        print(f"Configuração padrão gerada em '{path}':")
        print(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
