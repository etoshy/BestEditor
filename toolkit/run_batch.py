"""
run_batch.py
=============

Orquestra busca + download em lote nos 5 provedores do toolkit, lendo
tudo de `toolkit_config.json` (gerado por `generate_config.py`):

  - Quais sites estão habilitados, e o que buscar em cada um
    (`providers.<site>.query`/`category`, `max_pages`, `download_count`);
  - Como o Chrome é aberto (`browser.headless`, `browser.download_dir`);
  - Como os downloads são feitos (`downloads.max_workers`,
    `downloads.per_provider_workers`, `downloads.retries`,
    `downloads.retry_backoff_seconds`, `downloads.manifest`,
    `downloads.skip_existing`, `downloads.output_dir`).

Uso
---
    # 1) gera o toolkit_config.json (se ainda não existir) e edite os
    #    valores que quiser (termo de busca, quantos baixar, etc.)
    python generate_config.py

    # 2) roda tudo: busca + baixa, respeitando o config
    python run_batch.py

    # só alguns sites, ignorando o "enabled" do config para esses:
    python run_batch.py --providers pexels mixkit

    # usar outro arquivo de config:
    python run_batch.py --config outro_config.json

Cada site abre sua própria janela do Chrome (uma sessão reaproveitada
entre busca e todos os downloads daquele site) — isso é fechado
automaticamente no final, com sucesso ou erro.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Dict, List

from browser_session import ChromeSession
from download_manager import configure_logging, download_concurrent_grouped
from generate_config import CONFIG_FILENAME, generate_default_config, load_config
from pexels_api_client import PexelsAPIClient
from api_keys import load_dotenv
import os

import pexels.pexels_client as _pexels_mod
import pixabay.pixabay_client as _pixabay_mod
import magnific.magnific_client as _magnific_mod
import mixkit.mixkit_client as _mixkit_mod
import vistacreate.vistacreate_client as _vistacreate_mod

logger = logging.getLogger("run_batch")

_CLIENT_CLASSES = {
    "pexels": _pexels_mod.PexelsClient,
    "pixabay": _pixabay_mod.PixabayClient,
    "magnific": _magnific_mod.MagnificClient,
    "mixkit": _mixkit_mod.MixkitClient,
    "vistacreate": _vistacreate_mod.VistaCreateClient,
}

_DEFAULT_HEADERS = {
    "pexels": _pexels_mod.DEFAULT_HEADERS,
    "pixabay": _pixabay_mod.DEFAULT_HEADERS,
    "magnific": _magnific_mod.DEFAULT_HEADERS,
    "mixkit": _mixkit_mod.DEFAULT_HEADERS,
    "vistacreate": _vistacreate_mod.DEFAULT_HEADERS,
}

# Nome do parâmetro de "o que buscar" em search_all() de cada provedor —
# todos usam query=, exceto o Mixkit, que navega por categoria.
_SEARCH_TERM_PARAM = {
    "pexels": "query",
    "pixabay": "query",
    "magnific": "query",
    "mixkit": "category",
    "vistacreate": "query",
}

# Chaves do bloco providers.<site> em toolkit_config.json que NÃO são
# filtros de busca (são metadados de orquestração, tratados à parte).
_NON_FILTER_KEYS = {"enabled", "max_pages", "download_count", "query", "category"}


def _pexels_api_keys_configured() -> bool:
    """True se houver ao menos uma chave em PEXELS_API_KEYS (carrega o
    .env primeiro, se existir). Quando True, o Pexels usa a API oficial
    (sem Chrome) em vez do scraping por navegador — mais rápido, imune a
    bloqueio por Cloudflare, e economiza um navegador inteiro no lote.
    """
    load_dotenv()
    return bool(os.environ.get("PEXELS_API_KEYS", "").strip())


def _make_client(provider: str, browser_cfg: Dict[str, Any], shared_session=None):
    if provider == "pexels" and _pexels_api_keys_configured():
        return PexelsAPIClient()

    if shared_session is not None:
        return _CLIENT_CLASSES[provider](session=shared_session)

    headless = browser_cfg.get("headless")
    if headless is None:
        headless = not browser_cfg.get("show_browser", True)
    session = ChromeSession(
        headless=headless,
        headers=_DEFAULT_HEADERS[provider],
        download_dir=browser_cfg.get("download_dir"),
        low_resource=browser_cfg.get("low_resource", False),
    )
    return _CLIENT_CLASSES[provider](session=session)


def _build_search_kwargs(provider: str, provider_cfg: Dict[str, Any]) -> Dict[str, Any]:
    term_param = _SEARCH_TERM_PARAM[provider]
    term_value = provider_cfg.get(term_param)
    if term_value is None:
        # Aceita o config usar "query" mesmo pro Mixkit (que internamente
        # chama isso de "category") — só por conveniência de quem edita
        # o JSON sem decorar qual provedor usa qual nome.
        term_value = provider_cfg.get("query") or provider_cfg.get("category")

    filters = {k: v for k, v in provider_cfg.items() if k not in _NON_FILTER_KEYS}
    return {term_param: term_value, **filters}


def run_batch(config_path: str = CONFIG_FILENAME, only_providers: List[str] = None) -> Dict[str, Any]:
    generate_default_config(config_path)  # cria se não existir; nunca sobrescreve
    config = load_config(config_path)
    configure_logging()

    browser_cfg = config["browser"]
    downloads_cfg = config["downloads"]

    providers_to_run = only_providers or [
        p for p, c in config["providers"].items() if c.get("enabled", True)
    ]

    # "shared_session": um único Chrome reaproveitado por todos os sites,
    # em vez de um navegador por site. Economiza muita RAM/CPU, ao custo
    # de perder o paralelismo entre sites (com um navegador só, um site
    # de cada vez, não importa o que "max_workers" diga).
    use_shared_session = browser_cfg.get("shared_session", False)
    shared_session = None
    effective_max_workers = downloads_cfg.get("max_workers", 3)

    if use_shared_session:
        headless = browser_cfg.get("headless")
        if headless is None:
            headless = not browser_cfg.get("show_browser", True)
        try:
            shared_session = ChromeSession(
                headless=headless,
                headers=next(iter(_DEFAULT_HEADERS.values())),
                download_dir=browser_cfg.get("download_dir"),
                low_resource=browser_cfg.get("low_resource", False),
            )
            print("Usando UM único navegador compartilhado entre todos os sites (browser.shared_session=true).")
            effective_max_workers = 1  # um navegador só não processa 2 sites ao mesmo tempo
        except Exception as exc:  # noqa: BLE001
            logger.error("Não consegui abrir o navegador compartilhado, seguindo sem: %s", exc)
            shared_session = None

    clients: Dict[str, Any] = {}
    jobs_by_provider: Dict[str, List[dict]] = {}
    search_summary: Dict[str, int] = {}

    for provider in providers_to_run:
        provider_cfg = config["providers"].get(provider, {})
        if provider == "pexels" and _pexels_api_keys_configured():
            print(f"[{provider}] usando a API oficial do Pexels (sem Chrome) e buscando...")
        else:
            print(f"[{provider}] {'reaproveitando o navegador compartilhado' if shared_session else 'abrindo o Chrome'} e buscando...")

        try:
            client = _make_client(provider, browser_cfg, shared_session=shared_session)
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] não consegui abrir o navegador: %s", provider, exc)
            continue
        clients[provider] = client

        search_kwargs = _build_search_kwargs(provider, provider_cfg)
        max_pages = provider_cfg.get("max_pages", 1)

        try:
            videos = client.search_all(max_pages=max_pages, **search_kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] busca falhou: %s", provider, exc)
            videos = []

        search_summary[provider] = len(videos)
        download_count = provider_cfg.get("download_count", 2)
        chosen = videos[:download_count]
        print(f"[{provider}] {len(videos)} encontrados, selecionando {len(chosen)} para baixar.")

        output_dir = str(Path(downloads_cfg.get("output_dir", "videos")) / provider)
        jobs_by_provider[provider] = [
            {
                "provider": provider,
                "client": client,
                "video": video,
                "output_dir": output_dir,
                "index": i,
                "skip_existing": downloads_cfg.get("skip_existing", True),
            }
            for i, video in enumerate(chosen)
        ]

    results: List[tuple] = []
    if downloads_cfg.get("enabled", True):
        results = download_concurrent_grouped(
            jobs_by_provider,
            max_workers=effective_max_workers,
            per_provider_workers=downloads_cfg.get("per_provider_workers", 1),
            retries=downloads_cfg.get("retries", 3),
            backoff=downloads_cfg.get("retry_backoff_seconds", 2),
            manifest_path=downloads_cfg.get("manifest", "downloads_manifest.json"),
            write_metadata=downloads_cfg.get("write_metadata", True),
            embed_ffmpeg=downloads_cfg.get("embed_ffmpeg_metadata", True),
        )
    else:
        print("downloads.enabled=false no config — só a busca foi feita.")

    if shared_session is not None:
        # Só existe UMA sessão de verdade — fecha uma vez só.
        try:
            shared_session.close()
        except Exception:  # noqa: BLE001
            pass
    else:
        for provider, client in clients.items():
            try:
                client.session.close()
            except Exception:  # noqa: BLE001
                pass

    summary = {
        "search": search_summary,
        "downloads": {
            "ok": sum(1 for _, status, _ in results if status == "ok"),
            "skipped": sum(1 for _, status, _ in results if status == "skipped"),
            "failed": sum(1 for _, status, _ in results if status == "failed"),
        },
        "failed_items": [(key, detail) for key, status, detail in results if status == "failed"],
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Busca + download em lote nos 5 provedores, via toolkit_config.json.")
    parser.add_argument("--config", default=CONFIG_FILENAME, help=f"Caminho do config (padrão: {CONFIG_FILENAME})")
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=sorted(_CLIENT_CLASSES),
        help="Rodar só esses provedores, ignorando 'enabled' do config para eles.",
    )
    args = parser.parse_args()

    summary = run_batch(config_path=args.config, only_providers=args.providers)

    print("\n=== Resumo da busca ===")
    for provider, count in summary["search"].items():
        print(f"  {provider}: {count} vídeos encontrados")

    dl = summary["downloads"]
    print(f"\n=== Resumo dos downloads ===\n  ok={dl['ok']}  pulados(manifesto)={dl['skipped']}  falharam={dl['failed']}")

    if summary["failed_items"]:
        print("\nFalhas:")
        for key, detail in summary["failed_items"]:
            print(f"  {key}: {detail}")


if __name__ == "__main__":
    main()
