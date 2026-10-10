"""Navegadores Playwright persistentes, um por mecanismo de busca.

Cada mecanismo (Bing/Brave/Yandex/Startpage) recebe um único Chromium por
processo e reutiliza a mesma aba para uma sequência de consultas. As chamadas
são serializadas dentro do worker para impedir duas buscas simultâneas na mesma
aba.
"""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Awaitable, Callable, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright


PageCallable = Callable[[Page, BrowserContext], Awaitable[Any]]


class PersistentBrowserSearchWorker:
    """Mantém um Playwright/Chromium vivo e executa buscas sequencialmente."""

    def __init__(self, *, headless: bool = True, timeout_ms: int = 30000, locale: str = "pt-BR"):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.locale = locale
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._init_error: Optional[BaseException] = None
        self._run_lock = threading.Lock()

        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

        self._start()

    def _start(self) -> None:
        self._thread = threading.Thread(target=self._thread_main, daemon=True, name=f"browser-search-{self.locale}")
        self._thread.start()
        if not self._ready.wait(timeout=60):
            raise RuntimeError("Timeout inicializando navegador persistente de busca.")
        if self._init_error:
            raise RuntimeError(f"Falha inicializando navegador persistente: {self._init_error}") from self._init_error

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        async def boot() -> None:
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                ],
            )
            self._context = await self._browser.new_context(
                locale=self.locale,
                viewport={"width": 1440, "height": 900},
                extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7"},
            )
            self._page = await self._context.new_page()
            self._page.set_default_timeout(self.timeout_ms)

        async def shutdown() -> None:
            try:
                if self._page:
                    await self._page.close()
            except Exception:
                pass
            try:
                if self._context:
                    await self._context.close()
            except Exception:
                pass
            try:
                if self._browser:
                    await self._browser.close()
            except Exception:
                pass
            try:
                if self._pw:
                    await self._pw.stop()
            except Exception:
                pass

        try:
            loop.run_until_complete(boot())
            self._ready.set()
            while not self._stop.is_set():
                loop.run_until_complete(asyncio.sleep(0.05))
        except BaseException as exc:  # noqa: BLE001
            self._init_error = exc
            self._ready.set()
        finally:
            if self._pw or self._browser or self._context or self._page:
                try:
                    loop.run_until_complete(shutdown())
                except Exception:
                    pass
            try:
                loop.close()
            except Exception:
                pass

    def run(self, operation: PageCallable, timeout: Optional[float] = None) -> Any:
        """Executa uma operação assíncrona na mesma aba, uma por vez."""
        if not self._loop or not self._thread or not self._thread.is_alive():
            raise RuntimeError("Navegador persistente de busca não está ativo.")
        with self._run_lock:
            async def invoke() -> Any:
                if self._page is None or self._context is None:
                    raise RuntimeError("Navegador persistente não terminou de inicializar.")
                return await operation(self._page, self._context)

            fut: Future[Any] = asyncio.run_coroutine_threadsafe(invoke(), self._loop)
            return fut.result(timeout=timeout)

    def close(self) -> None:
        thread = self._thread
        if not thread or not thread.is_alive():
            return
        self._stop.set()
        thread.join(timeout=10)
        self._thread = None
        self._loop = None

    quit = close
