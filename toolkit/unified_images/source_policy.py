"""Política de sites de origem (mesma regra do Yandex/Brave, sem depender dos motores).

Páginas de resultados de buscadores NÃO são "site de origem": catalogá-las traria
centenas de imagens que não pertencem ao resultado.
"""

from __future__ import annotations

from urllib.parse import urlparse

SEARCH_ENGINE_HOSTS = {
    "google.com", "google.com.br", "www.google.com", "www.google.com.br",
    "bing.com", "www.bing.com", "search.yahoo.com",
    "duckduckgo.com", "www.duckduckgo.com",
    "startpage.com", "www.startpage.com",
    "yandex.com", "yandex.ru",
    "brave.com", "search.brave.com",
}


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().split(":", 1)[0].strip(".")
    except Exception:
        return ""


def is_google_host(host: str) -> bool:
    host = (host or "").lower().split(":", 1)[0].strip(".")
    return (
        host == "google.com" or host.endswith(".google.com")
        or host == "google.com.br" or host.endswith(".google.com.br")
    )


def should_skip_source_url(
    url: str,
    *,
    allow_google_source: bool = False,
    allow_search_engine_sources: bool = False,
) -> tuple[bool, str]:
    """Devolve (pular?, motivo)."""
    host = _host(url)
    if not host:
        return True, "host ausente"
    if is_google_host(host):
        if allow_google_source or allow_search_engine_sources:
            return False, ""
        return True, "Google bloqueado como site de origem"
    if host in SEARCH_ENGINE_HOSTS or any(host.endswith("." + h) for h in SEARCH_ENGINE_HOSTS):
        if allow_search_engine_sources:
            return False, ""
        return True, "motor de busca bloqueado como site de origem"
    return False, ""
