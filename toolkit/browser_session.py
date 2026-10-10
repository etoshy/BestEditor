"""Sessão baseada em um navegador Chrome real (Selenium)."""
from __future__ import annotations
import json, os, shutil, time, html
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

@dataclass
class BrowserResponse:
    status_code: int
    text: str
    url: str
    def json(self):
        """Converte respostas JSON exibidas pelo Chrome em objeto Python.

        Chrome normalmente renderiza um endpoint JSON dentro de <pre>, então
        page_source não é JSON puro mesmo quando o conteúdo visual é JSON.
        """
        text = (self.text or "").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        import re
        match = re.search(r"<pre[^>]*>(.*?)</pre>", text, re.I | re.S)
        if match:
            candidate = html.unescape(match.group(1)).strip()
            return json.loads(candidate)
        # Último fallback: remove tags e usa o texto visível da página.
        # Fallback final: use texto renderizado do documento, que é mais
        # confiável quando o Chrome embrulha JSON em uma página própria.
        plain = re.sub(r"<[^>]+>", "", text)
        plain = html.unescape(plain).strip()
        return json.loads(plain)

class ChromeSession:
    """Substitui requests.Session por uma sessão que navega usando Chrome."""
    def __init__(
        self,
        headless: bool = False,
        headers: Optional[dict] = None,
        download_dir: Optional[str] = None,
        low_resource: bool = False,
    ):
        """
        low_resource: desliga carregamento de imagens e vários recursos do
            Chrome que este toolkit nunca usa (sync, extensões, tradução,
            áudio, GPU) — reduz bastante o consumo de RAM/CPU por
            navegador, sem afetar em nada a busca/parsing (que só precisa
            do HTML/JSON da página, não da renderização visual). Desligado
            por padrão para não mudar o comportamento de quem já usa a
            classe sem esse parâmetro.
        """
        self.headers = headers or {}
        self.download_dir = Path(download_dir or os.environ.get("VIDEO_TOOLKIT_DOWNLOAD_DIR", Path.cwd() / ".chrome_downloads"))
        self.download_dir.mkdir(parents=True, exist_ok=True)
        options = Options()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        if self.headers.get("User-Agent"):
            options.add_argument(f"--user-agent={self.headers['User-Agent']}")
        prefs = {
            "download.default_directory": str(self.download_dir.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        }
        if low_resource:
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-background-networking")
            options.add_argument("--disable-sync")
            options.add_argument("--disable-translate")
            options.add_argument("--mute-audio")
            options.add_argument("--disable-software-rasterizer")
            options.add_argument("--blink-settings=imagesEnabled=false")
            # Pref equivalente (mais confiável em versões recentes do Chrome
            # do que só a flag do blink acima): 2 = bloquear imagens.
            prefs["profile.managed_default_content_settings.images"] = 2
        options.add_experimental_option("prefs", prefs)
        self.driver = webdriver.Chrome(options=options)
        try:
            self.driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                "behavior": "allow", "downloadPath": str(self.download_dir.resolve())
            })
        except Exception:
            pass

    def request(self, method: str, url: str, params: Optional[dict] = None, timeout: int = 30,
                wait_for_selector: Optional[str] = None, wait_for_attr: Optional[str] = None,
                wait_timeout: int = 10, **kwargs: Any) -> BrowserResponse:
        """
        wait_for_selector: se fornecido, espera até um elemento que bate
            com esse seletor CSS aparecer no DOM antes de capturar o HTML
            — necessário em páginas que populam conteúdo via JavaScript
            DEPOIS do carregamento inicial (ex: um player de vídeo tipo
            Stimulus.js que só define o `src` do `<video>` depois de
            conectar). Sem isso, `driver.get()` + `page_source` captura o
            HTML ANTES do JS terminar, perdendo esse conteúdo dinâmico.
        wait_for_attr: junto com `wait_for_selector`, espera não só o
            elemento existir, mas um ATRIBUTO específico dele (ex: "src")
            estar preenchido (não vazio) — mais preciso que só esperar o
            elemento existir, já que muitos players criam o `<video>`
            vazio primeiro e só preenchem o `src` um instante depois.
        wait_timeout: quantos segundos esperar no máximo pela condição
            acima antes de desistir e capturar o HTML do jeito que
            estiver (não trava a página pra sempre se o layout mudou de
            verdade e o elemento nunca aparece).
        """
        if method.upper() != "GET":
            raise ValueError("ChromeSession atualmente suporta apenas GET")
        if params:
            sep = "&" if "?" in url else "?"
            url = url + sep + urlencode(params, doseq=True)
        self.driver.set_page_load_timeout(timeout)
        try:
            self.driver.get(url)
            if wait_for_selector:
                self._wait_for_element(wait_for_selector, wait_for_attr, wait_timeout)
            text = self.driver.page_source
            if not text:
                text = self.driver.execute_script("return document.documentElement.innerText || document.body.innerText || '';" )
            return BrowserResponse(200, text, self.driver.current_url)
        except Exception as exc:
            return BrowserResponse(599, str(exc), url)

    def _wait_for_element(self, selector: str, attr: Optional[str], wait_timeout: int) -> None:
        """Espera até `wait_timeout` segundos por um elemento (e,
        opcionalmente, um atributo dele preenchido) — nunca levanta
        exceção mesmo se o tempo esgotar, já que é melhor capturar o
        HTML do jeito que estiver do que travar a requisição inteira por
        causa de uma página com layout diferente do esperado.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait

        def _condition(driver):
            try:
                el = driver.find_element(By.CSS_SELECTOR, selector)
            except Exception:  # noqa: BLE001
                return False
            if attr:
                return bool(el.get_attribute(attr))
            return True

        try:
            WebDriverWait(self.driver, wait_timeout).until(_condition)
        except Exception:  # noqa: BLE001
            pass  # esgotou o tempo — segue com o HTML do jeito que está

    def fetch_api(
        self,
        url: str,
        params: Optional[dict] = None,
        timeout: int = 30,
        referer_url: Optional[str] = None,
    ) -> BrowserResponse:
        """Busca um endpoint JSON como o próprio site faria: com uma página
        do mesmo domínio já carregada, chamando `fetch()` de DENTRO dela em
        vez de navegar a aba inteira para a URL da API.

        Isso importa porque `driver.get(url_da_api)` faz uma navegação de
        nível superior (o Chrome pede a URL como se fosse abrir uma página
        nova) — o que é bem diferente de como um usuário de verdade chega
        nesses dados (o JavaScript da página faz um `fetch()` em segundo
        plano, com referer, cookies e cabeçalhos de "mesma origem"). Vários
        sites reconhecem essa diferença e bloqueiam/alteram a resposta só
        para navegações diretas à API — este método evita isso.

        referer_url: página a carregar antes de chamar `fetch()`, caso a
        aba ainda não esteja em uma página do mesmo domínio da API. Se não
        for passado, usa a raiz do domínio da própria `url`.
        """
        if params:
            sep = "&" if "?" in url else "?"
            full_url = url + sep + urlencode(params, doseq=True)
        else:
            full_url = url

        try:
            from urllib.parse import urlparse
            target_origin = urlparse(full_url)
            api_origin = f"{target_origin.scheme}://{target_origin.netloc}"

            current_origin = None
            try:
                current_origin = self.driver.execute_script("return window.location.origin;")
            except Exception:
                current_origin = None

            if current_origin != api_origin:
                self.driver.set_page_load_timeout(timeout)
                self.driver.get(referer_url or f"{api_origin}/")

            result = self.driver.execute_async_script(
                """
                const url = arguments[0], timeoutMs = arguments[1], done = arguments[arguments.length - 1];
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort(), timeoutMs);
                fetch(url, {credentials: 'include', signal: controller.signal})
                    .then(r => r.text().then(t => { clearTimeout(timer); done({status: r.status, text: t}); }))
                    .catch(e => { clearTimeout(timer); done({status: 599, text: String(e)}); });
                """,
                full_url, timeout * 1000,
            )
            return BrowserResponse(result.get("status", 599), result.get("text", ""), full_url)
        except Exception as exc:
            return BrowserResponse(599, str(exc), full_url)

    def download(self, url: str, destination: str, timeout: int = 120) -> str:
        """Baixa usando o próprio Chrome.

        Para MP4s, um simples ``driver.get(url)`` abre o player interno e não
        inicia download. Primeiro tentamos buscar o recurso dentro do contexto
        do navegador e transformar a resposta em Blob, acionando então um link
        ``blob:`` com ``download``. Isso evita o player e equivale ao "Salvar
        vídeo como" sem automatizar menus nativos do Windows.
        """
        dest = Path(destination).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        before = {p.name for p in self.download_dir.iterdir()}
        filename = dest.name or 'video.mp4'

        # A página precisa ter um documento ativo para executar fetch/blob.
        blob_result = None
        try:
            self.driver.execute_script("if (!document.body) location.href='about:blank';")
            blob_result = self.driver.execute_async_script("""
                const url = arguments[0], filename = arguments[1], done = arguments[arguments.length - 1];
                (async () => {
                  try {
                    const r = await fetch(url, {credentials: 'omit', redirect: 'follow'});
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    const blob = await r.blob();
                    if (!blob || blob.size === 0) throw new Error('arquivo vazio');
                    const a = document.createElement('a');
                    const objectUrl = URL.createObjectURL(blob);
                    a.href = objectUrl; a.download = filename; a.style.display = 'none';
                    document.body.appendChild(a); a.click();
                    setTimeout(() => { URL.revokeObjectURL(objectUrl); a.remove(); }, 5000);
                    done({ok:true, size:blob.size});
                  } catch (e) { done({ok:false, error:String(e)}); }
                })();
            """, url, filename)
        except Exception:
            blob_result = None

        # O fetch()+Blob acima pode "funcionar" do ponto de vista do
        # Selenium (a chamada assíncrona termina normalmente, sem
        # exceção) mas ainda assim FALHAR de verdade por dentro — o caso
        # mais comum é CORS: muitos CDNs de vídeo (como o da Pixabay) não
        # enviam os headers `Access-Control-Allow-Origin` que permitiriam
        # ler a resposta via JavaScript de outra origem. Nesse caso,
        # `blob_result` vem como `{"ok": False, "error": "..."}` — sem
        # checar isso, o código ficava esperando o arquivo aparecer no
        # disco pelo timeout INTEIRO, mesmo que o download nunca tivesse
        # começado de verdade, e só then estourava um erro genérico de
        # timeout, sem indicar a causa real.
        if not blob_result or not blob_result.get("ok"):
            try:
                self.driver.execute_script("""
                    const a=document.createElement('a'); a.href=arguments[0];
                    a.download=arguments[1]; a.style.display='none'; document.body.appendChild(a);
                    a.click(); setTimeout(()=>a.remove(), 3000);
                """, url, filename)
            except Exception:
                pass

        deadline = time.time() + timeout
        stable = None; last_size = -1; last_change = time.time()
        while time.time() < deadline:
            entries = list(self.download_dir.iterdir())
            files = [p for p in entries if p.name not in before and not p.name.endswith(('.crdownload', '.tmp'))]
            partial = any(p.name not in before and p.name.endswith('.crdownload') for p in entries)
            if files:
                candidate = max(files, key=lambda p: p.stat().st_mtime)
                size = candidate.stat().st_size
                if size != last_size:
                    last_size = size; last_change = time.time()
                if not partial and size > 0 and time.time() - last_change >= 1.5:
                    stable = candidate; break
            time.sleep(0.25)
        if not stable or not stable.exists():
            reason = ""
            if blob_result and not blob_result.get("ok"):
                reason = f" (a tentativa via fetch()+Blob falhou: {blob_result.get('error')} — provavelmente CORS bloqueando leitura entre origens; o fallback de clique direto também não gerou um download detectável)"
            raise TimeoutError(f"Chrome não concluiu o download: {url}{reason}")
        if dest.exists(): dest.unlink()
        shutil.move(str(stable), str(dest))
        return str(dest)

    def close(self):
        try: self.driver.quit()
        except Exception: pass
    quit = close
