"""Download unificado das imagens (stdlib, sem navegador).

- valida que o conteúdo é mesmo uma imagem (assinatura dos bytes), não uma página de erro;
- tenta as URLs reserva (thumbnail/proxy) se a original falhar;
- recusa endereços privados/locais (evita que uma página maliciosa faça o
  programa acessar a sua rede interna) — desligável com allow_private_hosts.
"""

from __future__ import annotations

import asyncio
import ipaddress
import mimetypes
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

MAX_BYTES = 40 * 1024 * 1024
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
ACCEPT = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"


class BlockedHostError(Exception):
    pass


class HttpStatusError(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


# ---------------------------------------------------------------------------
# Segurança de rede
# ---------------------------------------------------------------------------


def check_url_allowed(url: str, allow_private_hosts: bool = False) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedHostError(f"esquema não permitido: {parsed.scheme or '(vazio)'}")
    host = parsed.hostname
    if not host:
        raise BlockedHostError("URL sem host")
    if allow_private_hosts:
        return
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise OSError(f"DNS falhou para {host}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if not ip.is_global:
            raise BlockedHostError(f"endereço não público bloqueado ({ip})")


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_private_hosts: bool):
        self.allow_private_hosts = allow_private_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url_allowed(newurl, self.allow_private_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# ---------------------------------------------------------------------------
# Detecção do tipo de imagem pelos bytes
# ---------------------------------------------------------------------------


def sniff_image(data: bytes) -> tuple[str, str] | None:
    """(extensão, mime) se os bytes forem uma imagem conhecida; senão None."""
    h = data[:32]
    if h.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if h.startswith((b"GIF87a", b"GIF89a")):
        return ".gif", "image/gif"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return ".webp", "image/webp"
    if h[4:8] == b"ftyp" and h[8:12] in (b"avif", b"avis"):
        return ".avif", "image/avif"
    if h[:2] == b"BM" and len(data) > 18 and int.from_bytes(data[14:18], "little") in (12, 40, 52, 56, 64, 108, 124):
        return ".bmp", "image/bmp"
    if h.startswith((b"II*\x00", b"MM\x00*")):
        return ".tif", "image/tiff"
    if h.startswith(b"\x00\x00\x01\x00"):
        return ".ico", "image/x-icon"
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return ".svg", "image/svg+xml"
    return None


def _looks_like_html(data: bytes) -> bool:
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith((b"<!doctype", b"<html", b"<head", b"<body", b"<?xml", b"{", b"["))


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def fetch_url(
    url: str,
    referer: str = "",
    timeout: float = 45,
    allow_private_hosts: bool = False,
    max_bytes: int = MAX_BYTES,
) -> tuple[bytes, str]:
    """Baixa uma URL (bloqueante). Devolve (bytes, content-type)."""
    check_url_allowed(url, allow_private_hosts)
    headers = {"User-Agent": USER_AGENT, "Accept": ACCEPT}
    if referer:
        headers["Referer"] = referer
    opener = urllib.request.build_opener(_GuardedRedirect(allow_private_hosts))
    request = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(request, timeout=timeout) as resp:
            ctype = (resp.headers.get_content_type() or "").lower()
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise ValueError(f"arquivo maior que {max_bytes // (1024 * 1024)} MB")
            data = resp.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        exc.close()  # senão o socket da resposta de erro fica aberto
        raise HttpStatusError(exc.code) from exc
    if len(data) > max_bytes:
        raise ValueError(f"arquivo maior que {max_bytes // (1024 * 1024)} MB")
    return data, ctype


@dataclass
class DownloadJob:
    id: int
    urls: list[str]
    referer: str
    stem: str                       # nome do arquivo sem extensão
    extra: dict[str, Any] = field(default_factory=dict)


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, HttpStatusError):
        return exc.status in (408, 425, 429, 500, 502, 503, 504)
    return isinstance(exc, (TimeoutError, urllib.error.URLError, ConnectionError, socket.timeout)) and not isinstance(
        exc, BlockedHostError
    )


async def _try_url(
    fetch: Callable[..., tuple[bytes, str]],
    url: str,
    referer: str,
    timeout: float,
    allow_private_hosts: bool,
) -> tuple[bytes, str, str, str]:
    """Tenta uma URL (com 1 repetição em falha passageira e 1 tentativa sem Referer)."""
    last: Exception | None = None
    for ref in ([referer, ""] if referer else [""]):
        for attempt in range(2):
            try:
                data, ctype = await asyncio.to_thread(fetch, url, ref, timeout, allow_private_hosts)
                kind = sniff_image(data)
                if kind:
                    return data, ctype, kind[0], kind[1]
                if ctype.startswith("image/") and not _looks_like_html(data) and data:
                    ext = mimetypes.guess_extension(ctype) or ".img"
                    return data, ctype, ext, ctype
                raise ValueError(f"conteúdo não é imagem (content-type: {ctype or 'desconhecido'})")
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt == 0 and _is_transient(exc):
                    await asyncio.sleep(0.8)
                    continue
                break
        # só repete sem Referer quando o servidor recusou
        if not (isinstance(last, HttpStatusError) and last.status in (401, 403)):
            break
    assert last is not None
    raise last


async def download_images(
    jobs: list[DownloadJob],
    images_dir: Path,
    *,
    concurrency: int = 6,
    timeout_s: float = 45,
    allow_private_hosts: bool = False,
    fetch: Callable[..., tuple[bytes, str]] | None = None,
) -> dict[int, dict[str, Any]]:
    """Baixa todos os jobs. Devolve {job.id: resultado}. Nunca levanta por falha de URL."""
    images_dir.mkdir(parents=True, exist_ok=True)
    fetch = fetch or fetch_url
    sem = asyncio.Semaphore(max(1, concurrency))
    out: dict[int, dict[str, Any]] = {}

    async def run(job: DownloadJob) -> None:
        errors: list[str] = []
        async with sem:
            for n, url in enumerate(job.urls):
                try:
                    data, ctype, ext, mime = await _try_url(
                        fetch, url, job.referer, timeout_s, allow_private_hosts
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{url} -> {type(exc).__name__}: {exc}")
                    continue
                target = images_dir / f"{job.stem}{ext}"
                tmp = target.with_suffix(target.suffix + ".part")
                try:
                    await asyncio.to_thread(tmp.write_bytes, data)
                    await asyncio.to_thread(tmp.replace, target)
                except OSError as exc:
                    errors.append(f"gravar {target.name}: {exc}")
                    continue
                out[job.id] = {
                    "ok": True,
                    "file": target.name,
                    "bytes": len(data),
                    "content_type": mime,
                    "url_used": url,
                    "used_fallback": n > 0,
                    "error": None,
                }
                return
        out[job.id] = {
            "ok": False,
            "file": None,
            "bytes": 0,
            "content_type": None,
            "url_used": None,
            "used_fallback": False,
            "error": errors[-1] if errors else "nenhuma URL para baixar",
            "all_errors": errors,
        }

    await asyncio.gather(*(run(j) for j in jobs))
    return out
