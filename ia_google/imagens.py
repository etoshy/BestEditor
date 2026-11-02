"""
Busca de imagens em tamanho real pelo Modo IA do Google.

O Google já manda, junto com cada miniatura, o link da imagem ORIGINAL (atributo data-im):
endereço da imagem em tamanho real, largura, altura, página de origem e título.
Quando isso falta, o plano B é clicar na miniatura e ler a imagem grande do painel lateral.

    from ia_google import GoogleIA
    from imagens import BuscadorImagens, baixar_imagens

    with GoogleIA() as ia:
        r = BuscadorImagens(ia).buscar("Satoru Gojo domain expansion", quantidade=20, verificar=True)
        for im in r["imagens"]:
            print(im["largura"], im["altura"], im["imagem"])
        baixar_imagens(r["imagens"], "imagens_baixadas/gojo")
"""
import concurrent.futures as cf
import io
import re
import time
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")

PEDIDO_1 = "Mostre {qtd} imagens de {termo}"
PEDIDO_MAIS = "Mostre mais {qtd} imagens diferentes de {termo}, que ainda não apareceram"

# Plano B: clica na miniatura e lê a imagem grande do painel lateral
JS_PAINEL = r"""
() => {
  const grande = [...document.querySelectorAll('img[jsname="kn3ccd"], img.sFlh5c.FyHeAf')]
    .find(i => /^https?:/.test(i.src) && !/gstatic\.com|^data:/.test(i.src) && i.offsetParent !== null);
  if (!grande) return null;
  const pagina = (document.querySelector('[data-lpage]') || {}).getAttribute
    ? document.querySelector('[data-lpage]').getAttribute('data-lpage') : '';
  return {imagem: grande.src, titulo: grande.alt || '', pagina: pagina || '',
          largura: grande.naturalWidth || null, altura: grande.naturalHeight || null};
}
"""


# Estado do painel lateral: imagem grande (original) + lista de imagens relacionadas (embaixo)
JS_ESTADO_PAINEL = r"""
() => {
  const visivel = (e) => e && e.offsetParent !== null && e.getBoundingClientRect().width > 0;
  const paineis = [...document.querySelectorAll('[role="dialog"]')].filter(visivel);
  const raiz = paineis.length ? paineis[paineis.length - 1] : document;
  const grandes = [...raiz.querySelectorAll('img[jsname="kn3ccd"], img.sFlh5c')]
    .filter(i => visivel(i) && i.getBoundingClientRect().width > 120);
  const orig = grandes.find(i => /^https?:/.test(i.src) && !/gstatic\.com/.test(i.src));
  const temp = grandes.find(i => /gstatic\.com|^data:/.test(i.src));
  // "1.400 × 700" escrito no painel
  let largura = null, altura = null;
  const m = (raiz.innerText || '').match(/(\d{1,2}\.?\d{3}|\d{2,4})\s*[×x]\s*(\d{1,2}\.?\d{3}|\d{2,4})/);
  if (m) { largura = +m[1].replace('.', ''); altura = +m[2].replace('.', ''); }
  if (orig && orig.complete && orig.naturalWidth > 50) { largura = orig.naturalWidth; altura = orig.naturalHeight; }
  const vistos = new Set();
  const relacionadas = [...raiz.querySelectorAll('[data-docid][data-lpage]')].filter(e => {
    const d = e.getAttribute('data-docid'); if (vistos.has(d)) return false; vistos.add(d); return true;
  }).map(e => {
    const img = e.querySelector('img');
    return {docid: e.getAttribute('data-docid'), pagina: e.getAttribute('data-lpage') || '',
            titulo: img ? (img.alt || '') : '', miniatura: img && /^https?:/.test(img.src) ? img.src : ''};
  });
  const linkPagina = [...raiz.querySelectorAll('a[href^="http"]')].find(a => visivel(a) && !/google\./.test(a.host));
  return {imagem: orig ? orig.src : null, carregando: !orig && !!temp, titulo: orig ? orig.alt : '',
          largura, altura, pagina: linkPagina ? linkPagina.href : '', relacionadas, aberto: paineis.length > 0};
}
"""


def _req(url, referer=None, metodo="GET", faixa=None):
    h = {"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    if referer:
        h["Referer"] = referer
    if faixa:
        h["Range"] = faixa
    return urllib.request.Request(url, headers=h, method=metodo)


def verificar_imagem(im, timeout=10):
    """Confere se o link abre e é mesmo uma imagem. Preenche verificada, tipo, bytes."""
    url = im.get("imagem")
    if not url:
        return {**im, "verificada": False, "erro_verificacao": "sem link"}
    try:
        with urllib.request.urlopen(_req(url, im.get("pagina"), faixa="bytes=0-2047"), timeout=timeout) as resp:
            tipo = resp.headers.get("Content-Type", "").split(";")[0]
            total = resp.headers.get("Content-Range", "").split("/")[-1] or resp.headers.get("Content-Length")
            ok = tipo.startswith("image/")
            return {**im, "verificada": ok, "tipo": tipo, "bytes": int(total) if str(total).isdigit() else None,
                    **({} if ok else {"erro_verificacao": f"não é imagem ({tipo or 'tipo desconhecido'})"})}
    except Exception as e:
        return {**im, "verificada": False, "erro_verificacao": str(e)[:120]}


def baixar_bytes(im, timeout=25):
    with urllib.request.urlopen(_req(im["imagem"], im.get("pagina")), timeout=timeout) as resp:
        tipo = resp.headers.get("Content-Type", "").split(";")[0]
        return resp.read(), tipo


def nome_arquivo(im, i, tipo=""):
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
           "image/avif": ".avif", "image/svg+xml": ".svg"}.get(tipo) or (Path(urlparse(im["imagem"]).path).suffix[:5] or ".jpg")
    base = re.sub(r"[^\w\-]+", "_", (im.get("titulo") or im.get("site") or "imagem").lower())[:50].strip("_")
    return f"{i:02d}_{base or 'imagem'}{ext}"


def baixar_imagens(imagens, pasta, paralelo=6):
    """Baixa as imagens originais para uma pasta. Devolve [(arquivo, erro)]."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)

    def um(par):
        i, im = par
        try:
            dados, tipo = baixar_bytes(im)
            arq = pasta / nome_arquivo(im, i, tipo)
            arq.write_bytes(dados)
            return str(arq), None
        except Exception as e:
            return im.get("imagem"), str(e)[:120]
    with cf.ThreadPoolExecutor(paralelo) as ex:
        return list(ex.map(um, enumerate(imagens, 1)))


def zip_imagens(imagens, paralelo=6):
    """Baixa as imagens e devolve um .zip em memória (bytes) + lista de falhas."""
    buf, falhas = io.BytesIO(), []

    def um(par):
        i, im = par
        try:
            dados, tipo = baixar_bytes(im)
            return nome_arquivo(im, i, tipo), dados, None
        except Exception as e:
            return None, None, f"{im.get('imagem')}: {str(e)[:100]}"
    with cf.ThreadPoolExecutor(paralelo) as ex, zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        linhas = []
        for nome, dados, erro in ex.map(um, enumerate(imagens, 1)):
            if erro:
                falhas.append(erro)
            else:
                z.writestr(nome, dados)
        for i, im in enumerate(imagens, 1):
            linhas.append(f"{i:02d}\t{im.get('largura')}x{im.get('altura')}\t{im.get('imagem')}\t{im.get('pagina', '')}")
        z.writestr("_links.txt", "nº\ttamanho\timagem original\tpágina de origem\n" + "\n".join(linhas)
                   + ("\n\nFALHARAM:\n" + "\n".join(falhas) if falhas else ""))
    return buf.getvalue(), falhas


class BuscadorImagens:
    def __init__(self, ia):
        self.ia = ia

    def _plano_b_clicar(self, limite=12):
        """Para miniaturas sem link original: clica e lê a imagem grande do painel lateral."""
        achadas = []
        p = self.ia.page
        try:
            tiles = p.locator('[data-subtree="aimc"]').last.locator("[data-im]")
            n = min(tiles.count(), limite)
        except Exception:
            return achadas
        for i in range(n):
            try:
                tiles.nth(i).click(timeout=4000)
                inicio = time.time()
                info = None
                while time.time() - inicio < 6 and not info:
                    time.sleep(0.4)
                    info = p.evaluate(JS_PAINEL)
                if info:
                    info["site"] = urlparse(info.get("pagina") or info["imagem"]).netloc
                    info["miniatura"] = ""
                    achadas.append(info)
                p.keyboard.press("Escape")
                time.sleep(0.3)
            except Exception:
                continue
        return achadas

    # ------------------------------------------------------------ exploração pelo painel lateral
    def _estado(self):
        try:
            return self.ia.page.evaluate(JS_ESTADO_PAINEL)
        except Exception:
            return {}

    def _esperar_original(self, anterior, timeout=9):
        """Espera a imagem grande do painel trocar para um original novo (≠ anterior)."""
        fim = time.time() + timeout
        est = {}
        while time.time() < fim:
            est = self._estado()
            if est.get("imagem") and est["imagem"] != anterior:
                time.sleep(0.4)  # deixa carregar para ler naturalWidth
                return self._estado() or est
            time.sleep(0.35)
        return None

    def _clicar(self, seletor):
        loc = self.ia.page.locator(seletor).filter(visible=True).first
        loc.scroll_into_view_if_needed(timeout=3000)
        loc.click(timeout=4000)

    def explorar_relacionadas(self, quantidade=20, ja_vistas=(), min_lado=0, max_cliques=None, aoachar=None,
                              profundidade=5):
        """Abre o painel de uma imagem da galeria e vai clicando nas RELACIONADAS (embaixo do painel),
        pegando o link original de cada uma. Cada clique mostra novas relacionadas (exploração em cadeia).
        A cada `profundidade` cliques volta para outra imagem da galeria, para não fugir do assunto."""
        page = self.ia.page
        vistas = set(ja_vistas)
        achadas, tentados, cliques = [], set(), 0
        max_cliques = max_cliques or quantidade * 3

        def registrar(est, extra=None):
            url = est.get("imagem")
            if not url or url in vistas:
                return False
            vistas.add(url)
            im = {"titulo": (extra or {}).get("titulo") or est.get("titulo", ""),
                  "pagina": (extra or {}).get("pagina") or est.get("pagina", ""),
                  "imagem": url, "miniatura": (extra or {}).get("miniatura", ""),
                  "largura": est.get("largura"), "altura": est.get("altura"), "origem": "relacionada"}
            im["site"] = urlparse(im["pagina"] or url).netloc
            if min_lado and max(im["largura"] or 0, im["altura"] or 0) < min_lado:
                return False
            achadas.append(im)
            if aoachar:
                aoachar(im)
            return True

        sementes = page.locator('[data-subtree="aimc"] [data-im]')
        n_sementes = min(sementes.count(), 12)
        semente = 0
        while len(achadas) < quantidade and cliques < max_cliques and semente < n_sementes:
            # 1) abre o painel numa imagem da galeria (semente)
            try:
                page.keyboard.press("Escape")
                sementes.nth(semente).scroll_into_view_if_needed(timeout=3000)
                sementes.nth(semente).click(timeout=4000)
            except Exception:
                semente += 1
                continue
            semente += 1
            est = self._esperar_original(None)
            if not est:
                continue
            registrar(est)
            anterior = est["imagem"]
            # 2) segue pelas relacionadas visíveis no painel atual
            for _ in range(profundidade):
                if len(achadas) >= quantidade or cliques >= max_cliques:
                    break
                candidatas = [r for r in est.get("relacionadas", []) if r["docid"] not in tentados]
                if not candidatas:
                    break
                rel = candidatas[0]
                tentados.add(rel["docid"])
                alvo = page.locator(f'[data-docid="{rel["docid"]}"] [role="button"], [data-docid="{rel["docid"]}"] img').filter(visible=True)
                if not alvo.count():
                    continue
                cliques += 1
                try:
                    alvo.first.scroll_into_view_if_needed(timeout=2000)
                    alvo.first.click(timeout=3000)
                except Exception:
                    continue
                novo = self._esperar_original(anterior)
                if not novo:
                    continue
                est, anterior = novo, novo["imagem"]
                if registrar(est, rel):
                    self.ia.log(f"Relacionada {len(achadas)}/{quantidade}: {est['imagem'][:80]}")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        if not achadas:
            self.ia.log("Não consegui abrir o painel lateral / relacionadas de nenhuma imagem.", "aviso")
        return achadas

    def buscar(self, termo, quantidade=20, verificar=False, min_lado=0, max_rodadas=4, relacionadas=False):
        termo = (termo or "").strip()
        if not termo:
            raise ValueError("Diga do que você quer imagens.")
        self.ia.nova_conversa()
        vistas, imagens, rodadas, avisos, pequenas = set(), [], 0, [], 0
        if relacionadas:
            max_rodadas = min(max_rodadas, 2)
        while len(imagens) < quantidade and rodadas < max_rodadas:
            rodadas += 1
            falta = max(4, quantidade - len(imagens))
            pedido = (PEDIDO_1 if rodadas == 1 else PEDIDO_MAIS).format(qtd=falta, termo=termo)
            self.ia.log(f"Imagens: rodada {rodadas} — {pedido}")
            r = self.ia.perguntar(pedido, usar_instrucao=False)
            novas = list((r.get("midias") or {}).get("imagens") or [])
            if any(not im.get("imagem") for im in novas):
                self.ia.log("Algumas miniaturas sem link original; abrindo o painel lateral de cada uma…", "aviso")
                novas = [im for im in novas if im.get("imagem")] + self._plano_b_clicar()
            novas_urls = 0
            for im in novas:
                url = im.get("imagem")
                if not url or url in vistas:
                    continue
                vistas.add(url)
                novas_urls += 1
                if min_lado and max(im.get("largura") or 0, im.get("altura") or 0) < min_lado:
                    pequenas += 1   # menor que o tamanho mínimo: descarta e busca mais
                    continue
                imagens.append({
                    "titulo": im.get("titulo", ""), "site": im.get("site") or urlparse(im.get("pagina") or url).netloc,
                    "pagina": im.get("pagina", ""), "imagem": url, "miniatura": im.get("miniatura", ""),
                    "largura": im.get("largura"), "altura": im.get("altura"),
                })
            if not novas_urls:
                if rodadas == 1:
                    avisos.append("O Google não mostrou uma galeria de imagens para este pedido. Tente descrever de outro jeito "
                                  "(ex.: 'fotos de…', 'wallpaper de…').")
                break  # não vieram imagens novas: não adianta insistir
            time.sleep(1.5)

        if relacionadas and len(imagens) < quantidade:
            falta = quantidade - len(imagens)
            self.ia.log(f"Explorando imagens relacionadas no painel lateral (faltam {falta})…")
            try:
                extras = self.explorar_relacionadas(falta, ja_vistas=vistas, min_lado=min_lado)
                imagens += extras
                avisos.append(f"{len(extras)} imagem(ns) vieram das relacionadas do painel lateral.")
            except Exception as e:
                avisos.append(f"Não consegui explorar as relacionadas: {str(e)[:100]}")
        if pequenas:
            avisos.append(f"{pequenas} imagem(ns) menores que {min_lado}px foram descartadas.")
        if len(imagens) < quantidade and rodadas >= max_rodadas:
            avisos.append(f"Depois de {rodadas} rodadas o Google trouxe {len(imagens)} imagem(ns) que atendem ao pedido.")
        imagens = imagens[:quantidade]

        if verificar and imagens:
            self.ia.log(f"Verificando {len(imagens)} links de imagem…")
            with cf.ThreadPoolExecutor(3) as ex:
                imagens = list(ex.map(verificar_imagem, imagens))
            quebradas = sum(1 for im in imagens if not im["verificada"])
            if quebradas:
                avisos.append(f"{quebradas} link(s) não abriram como imagem (sites que bloqueiam acesso direto ou link expirado).")

        return {"termo": termo, "total": len(imagens), "imagens": imagens, "rodadas": rodadas,
                "aviso": " ".join(avisos) or None, "data": time.strftime("%Y-%m-%dT%H:%M:%S")}
