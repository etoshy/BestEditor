"""
📰 Buscador de casos e notícias (v84_165)

Você escreve o caso (ex.: "o Unabomber") e o site:
  1. traduz o termo pro idioma da busca (padrão: inglês) — com a IA, se estiver ligada; dá pra editar;
  2. busca no YouTube os vídeos MAIS VISTOS sobre o caso (yt-dlp, sem chave), lista e calcula o tempo médio
     dos 5 mais vistos → um tempo sugerido pra falar do caso;
  3. abre o Google no navegador do site (o Brave das imagens, com o userscript) já na busca certa
     (padrão: aba Notícias, em inglês). Lá você marca os resultados e clica em "Enviar ao site";
     na página 2, manda de novo — tudo se junta, sem repetir;
  4. também aceita colar links (um por linha) ou o HTML inteiro da página do Google;
  5. o que foi marcado vira fontes de um 🕵️ Modelo de vídeo (matérias → fontes; vídeos → transcrição).

Os projetos ficam em pesquisas/<id>.json.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import uuid
from typing import Any, Dict, Iterable, List, Optional

PASTA = "pesquisas"
_TRAVA = threading.Lock()

# o que buscar no Google (categoria → parâmetros da busca); o padrão é notícias
CATEGORIAS: Dict[str, Dict[str, str]] = {
    "noticias": {"nome": "Notícias", "params": "tbm=nws", "extra": ""},
    "geral": {"nome": "Tudo (busca normal)", "params": "", "extra": ""},
    "enciclopedias": {"nome": "Enciclopédias e biografias", "params": "",
                      "extra": " (site:wikipedia.org OR site:britannica.com OR site:biography.com OR site:history.com)"},
    "documentos": {"nome": "Documentos e arquivos (PDF)", "params": "", "extra": " filetype:pdf"},
    "forums": {"nome": "Fóruns e discussões (Reddit…)", "params": "", "extra": " (site:reddit.com OR site:quora.com)"},
    "videos": {"nome": "Vídeos", "params": "tbm=vid", "extra": ""},
    "imagens_de_arquivo": {"nome": "Arquivos de jornal antigos", "params": "",
                           "extra": " (site:newspapers.com OR site:nytimes.com OR site:latimes.com OR site:washingtonpost.com)"},
}
# idioma da busca → (hl, gl, lr, nome)
IDIOMAS_BUSCA: Dict[str, tuple] = {
    "en": ("en", "us", "lang_en", "inglês"),
    "pt": ("pt-BR", "br", "lang_pt", "português"),
    "es": ("es", "es", "lang_es", "espanhol"),
    "fr": ("fr", "fr", "lang_fr", "francês"),
    "de": ("de", "de", "lang_de", "alemão"),
    "it": ("it", "it", "lang_it", "italiano"),
    "ja": ("ja", "jp", "lang_ja", "japonês"),
}
DOMINIOS_VIDEO = ("youtube.com", "youtu.be", "vimeo.com", "tiktok.com", "dailymotion.com", "dai.ly", "twitch.tv", "rumble.com")
DOMINIOS_SOCIAL = ("facebook.com", "fb.watch", "instagram.com", "x.com", "twitter.com", "threads.net", "reddit.com", "quora.com",
                   "pinterest.", "linkedin.com")


class PesquisaErro(Exception):
    pass


# ------------------------------------------------------------------ projetos
def _pasta(base: str) -> str:
    return os.path.join(base, PASTA)


def _valido(pid: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{10}", str(pid or "")))


def _arquivo(base: str, pid: str) -> str:
    if not _valido(pid):
        raise PesquisaErro("Pesquisa não encontrada.")
    return os.path.join(_pasta(base), pid + ".json")


def criar(base: str, tema: str, idioma: str = "en", categoria: str = "noticias", termo: str = "") -> Dict[str, Any]:
    tema = " ".join(str(tema or "").split())[:200]
    if not tema:
        raise PesquisaErro("Escreva o caso ou o tema da pesquisa.")
    p = {"id": uuid.uuid4().hex[:10], "criado": time.time(), "atualizado": time.time(), "tema": tema,
         "termo": " ".join(str(termo or "").split())[:200] or tema,
         "idioma": idioma if idioma in IDIOMAS_BUSCA else "en",
         "categoria": categoria if categoria in CATEGORIAS else "noticias",
         "youtube": None, "resultados": [], "modelos": []}
    salvar(base, p)
    return p


def carregar(base: str, pid: str) -> Dict[str, Any]:
    try:
        with open(_arquivo(base, pid), encoding="utf-8") as f:
            p = json.load(f)
    except (OSError, ValueError) as exc:
        raise PesquisaErro("Pesquisa não encontrada.") from exc
    p.setdefault("resultados", [])
    p.setdefault("modelos", [])
    return p


def salvar(base: str, p: Dict[str, Any]) -> None:
    os.makedirs(_pasta(base), exist_ok=True)
    p["atualizado"] = time.time()
    caminho = _arquivo(base, p["id"])
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def listar(base: str) -> List[Dict[str, Any]]:
    out = []
    if not os.path.isdir(_pasta(base)):
        return out
    for nome in os.listdir(_pasta(base)):
        if not nome.endswith(".json"):
            continue
        try:
            p = carregar(base, nome[:-5])
        except PesquisaErro:
            continue
        rs = p.get("resultados") or []
        out.append({"id": p["id"], "tema": p["tema"], "termo": p.get("termo"), "atualizado": p.get("atualizado") or 0,
                    "resultados": len(rs), "marcados": sum(1 for r in rs if r.get("marcado", True)),
                    "videos_yt": len(((p.get("youtube") or {}).get("videos")) or []),
                    "sugestao_min": (p.get("youtube") or {}).get("sugestao_min")})
    return sorted(out, key=lambda x: -x["atualizado"])


def excluir(base: str, pid: str) -> None:
    try:
        os.remove(_arquivo(base, pid))
    except OSError:
        pass


# ------------------------------------------------------------------ termo no idioma da busca
def traduzir_termo(tema: str, idioma: str) -> Optional[str]:
    """O termo de busca no idioma escolhido, com a IA (Claude) se ela estiver ligada. None = sem IA (fica o tema)."""
    if idioma == "pt":
        return None
    try:
        import ia_servico as ia
        if not ia.ativo("buscas"):
            return None
        nome = IDIOMAS_BUSCA.get(idioma, IDIOMAS_BUSCA["en"])[3]
        r = ia.chamar("buscas", "Você escreve termos de busca curtos para o Google e o YouTube. Responda só com o termo.",
                      f"Escreva em {nome} o melhor termo de busca (2 a 6 palavras, como um jornalista pesquisaria) sobre: {tema}\n"
                      "Use o nome pelo qual o caso é conhecido nesse idioma. Só o termo, sem aspas.", max_tokens=60)
        t = " ".join(str(r or "").replace('"', "").split())[:120]
        return t or None
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------ YouTube: os mais vistos
def _fmt(seg: Optional[float]) -> str:
    if not seg:
        return ""
    s = int(round(seg))
    h, m, x = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{x:02d}" if h else f"{m}:{x:02d}"


def url_youtube_mais_vistos(termo: str, idioma: str = "en") -> str:
    hl, gl = IDIOMAS_BUSCA.get(idioma, IDIOMAS_BUSCA["en"])[:2]
    # sp=CAMSAhAB = ordenar por visualizações + só vídeos
    return ("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(termo) + "&sp=CAMSAhAB"
            + f"&hl={urllib.parse.quote(hl)}&gl={gl.upper()}")


def estatisticas(videos: List[Dict[str, Any]], sem_shorts: bool = True, top: int = 5) -> Dict[str, Any]:
    """Tempo médio dos `top` mais vistos (sem Shorts, por padrão) e o tempo sugerido pra falar do caso."""
    base = [v for v in videos if v.get("duracao_s") and (not sem_shorts or v["duracao_s"] > 75)]
    base = sorted(base, key=lambda v: -(v.get("views") or 0))[:top]
    if not base:
        return {"media_s": None, "sugestao_min": None, "usados": 0}
    ds_ = sorted(v["duracao_s"] for v in base)
    media = sum(ds_) / len(ds_)
    mediana = ds_[len(ds_) // 2] if len(ds_) % 2 else (ds_[len(ds_) // 2 - 1] + ds_[len(ds_) // 2]) / 2
    sug = max(3, min(90, round((media + mediana) / 2 / 60)))
    return {"media_s": round(media), "media_fmt": _fmt(media), "mediana_s": round(mediana), "mediana_fmt": _fmt(mediana),
            "min_fmt": _fmt(ds_[0]), "max_fmt": _fmt(ds_[-1]), "sugestao_min": sug, "usados": len(base),
            "views_media": round(sum(v.get("views") or 0 for v in base) / len(base))}


def buscar_youtube(termo: str, idioma: str = "en", quantidade: int = 20, ytdlp_module: Any = None,
                   sem_shorts: bool = True) -> Dict[str, Any]:
    """Os vídeos mais vistos do YouTube sobre o termo (sem chave de API)."""
    termo = (termo or "").strip()
    if not termo:
        raise PesquisaErro("Termo de busca vazio.")
    if ytdlp_module is None:
        try:
            import yt_dlp as ytdlp_module  # type: ignore
        except ImportError as exc:
            raise PesquisaErro('O yt-dlp não está instalado (pip install -U "yt-dlp[default]").') from exc
    try:
        cookies = __import__("yt_cookies").opcoes()
    except Exception:  # noqa: BLE001
        cookies = {}
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "skip_download": True,
            "playlistend": max(5, min(int(quantidade or 20), 50)), **cookies}
    url = url_youtube_mais_vistos(termo, idioma)
    try:
        with ytdlp_module.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001
        raise PesquisaErro(f"Não consegui buscar no YouTube: {str(exc).splitlines()[0][:200]}") from exc
    videos = []
    for e in (info or {}).get("entries") or []:
        if not e or not e.get("id") or (e.get("ie_key") not in (None, "Youtube") and "watch" not in str(e.get("url") or "")):
            continue
        dur = e.get("duration")
        vid = {"id": e["id"], "titulo": e.get("title") or "(sem título)", "canal": e.get("channel") or e.get("uploader") or "",
               "views": int(e.get("view_count") or 0), "duracao_s": float(dur) if dur else None, "duracao_fmt": _fmt(dur),
               "url": f"https://www.youtube.com/watch?v={e['id']}", "data": e.get("upload_date") or "",
               "miniatura": f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg"}
        vid["short"] = bool(vid["duracao_s"] and vid["duracao_s"] <= 75)
        videos.append(vid)
    videos.sort(key=lambda v: -v["views"])
    if not videos:
        raise PesquisaErro("O YouTube não devolveu vídeos pra esse termo (tente o termo em outro idioma).")
    return {"termo": termo, "idioma": idioma, "url": url, "quando": time.time(), "videos": videos,
            **estatisticas(videos, sem_shorts)}


# ------------------------------------------------------------------ Google: busca no navegador do site
def url_google(termo: str, categoria: str = "noticias", idioma: str = "en", dest: str = "", pagina: int = 1) -> str:
    cat = CATEGORIAS.get(categoria) or CATEGORIAS["noticias"]
    hl, gl, lr, _n = IDIOMAS_BUSCA.get(idioma, IDIOMAS_BUSCA["en"])
    q = (termo or "").strip() + cat["extra"]
    partes = ["q=" + urllib.parse.quote_plus(q), f"hl={hl}", f"gl={gl}", f"lr={lr}"]
    if cat["params"]:
        partes.append(cat["params"])
    if pagina > 1:
        partes.append(f"start={(pagina - 1) * 10}")
    return "https://www.google.com/search?" + "&".join(partes) + (("#bes=" + dest) if dest else "")


def destino(site: str, pid: str, rotulo: str = "") -> str:
    """O "#bes=…" que o userscript lê: modo pesquisa → manda os resultados marcados pra /pesquisas/<pid>/resultados."""
    import base64
    d = {"u": site.rstrip("/"), "m": "pesquisa", "p": pid, "r": (rotulo or "")[:120]}
    return base64.urlsafe_b64encode(json.dumps(d, ensure_ascii=False).encode()).decode().rstrip("=")


# ------------------------------------------------------------------ resultados (links)
def _host(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def tipo_de(url: str) -> str:
    h = _host(url)
    if any(h == d or h.endswith("." + d) or h.startswith(d) for d in DOMINIOS_VIDEO):
        return "video"
    if any(h == d or h.endswith("." + d) or (d.endswith(".") and h.startswith(d)) for d in DOMINIOS_SOCIAL):
        return "social"
    if re.search(r"\.pdf($|\?)", url, re.I):
        return "documento"
    return "materia"


def normalizar_url(url: str) -> str:
    """Pra não repetir: tira #âncora, parâmetros de rastreio e o / do fim; google.com/url?q=… vira o link de verdade."""
    u = str(url or "").strip()
    if not re.match(r"https?://", u, re.I):
        return ""
    sp = urllib.parse.urlsplit(u)
    host = (sp.hostname or "").lower()
    if "google." in host and sp.path == "/goto" and "url=" in sp.query:
        return u  # v84_167: o Google novo esconde o link num código (/goto?url=CAES…) — resolve_itens descobre o de verdade
    if "google." in host and sp.path in ("/url", "/imgres"):
        q = urllib.parse.parse_qs(sp.query)
        alvo = (q.get("q") or q.get("url") or q.get("imgrefurl") or [""])[0]
        return normalizar_url(alvo) if alvo else ""
    if "google." in host or host.endswith("gstatic.com") or host.endswith("googleusercontent.com"):
        return ""
    query = [(k, v) for k, v in urllib.parse.parse_qsl(sp.query, keep_blank_values=True)
             if not re.match(r"^(utm_|fbclid|gclid|ved|ei|sa|usg|si$|feature$|ref$|ref_src)", k, re.I)]
    caminho = sp.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((sp.scheme.lower(), sp.netloc.lower(), caminho, urllib.parse.urlencode(query), ""))


def eh_goto(url: str) -> bool:
    return bool(re.match(r"https?://(www\.)?google\.[a-z.]+/goto\?", str(url or ""), re.I))


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


def resolver_goto(url: str, transporte: Optional[Any] = None, timeout: float = 8.0) -> Optional[str]:
    """O link de verdade por trás do /goto?url=… do Google (o mesmo que um clique faria). None se não der."""
    def _get(u):
        import requests
        r = requests.get(u, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}, allow_redirects=False, timeout=timeout)
        return r.status_code, r.headers.get("Location") or "", r.text[:300000] if r.status_code < 300 else ""
    transporte = transporte or _get
    alvo = url
    for _ in range(3):
        try:
            status, loc, html = transporte(alvo)
        except Exception:  # noqa: BLE001
            return None
        if loc:
            alvo = urllib.parse.urljoin(alvo, loc)
        else:
            m = (re.search(r"http-equiv=[\"']?refresh[\"']?[^>]*?url=['\"]?([^\"'>\s]+)", html, re.I)
                 or re.search(r"location\.(?:replace|assign)\(\s*[\"']([^\"']+)", html)
                 or re.search(r"location\.href\s*=\s*[\"']([^\"']+)", html)
                 or re.search(r"href=\"(https?://(?![a-z.]*google\.)[^\"]+)\"", html))
            if not m:
                return None
            alvo = urllib.parse.urljoin(alvo, m.group(1).replace("&amp;", "&").replace("\\x3d", "=").replace("\\x26", "&"))
        n = normalizar_url(alvo)
        if n and not eh_goto(n):
            return n
        if not n:
            return None
    return None


def url_pela_cite(cite: str, titulo: str = "") -> Optional[str]:
    """Plano B: monta o link pelo endereço que o Google mostra embaixo do título ("https://site.com › a › b").
    Pedaço cortado ("…") sai; na Wikipédia o título completa o nome do artigo."""
    c = " ".join(str(cite or "").split())
    m = re.match(r"(https?://[^\s›]+)\s*(.*)$", c)
    if not m:
        return None
    base, resto = m.group(1).rstrip("/"), m.group(2)
    partes = [x.strip() for x in resto.split("›") if x.strip()]
    if "wikipedia.org" in base and (titulo or "").strip() and partes[:1] == ["wiki"]:
        nome = re.sub(r"\s[-–]\s*Wikip[eé]dia\s*$", "", titulo).strip()
        return base + "/wiki/" + urllib.parse.quote(nome.replace(" ", "_"))
    bons = []
    for x in partes:
        if "…" in x or "..." in x:
            break
        bons.append(urllib.parse.quote(x, safe="-_.~%"))
    return normalizar_url(base + ("/" + "/".join(bons) if bons else ""))


def resolver_itens(itens: List[Dict[str, Any]], transporte: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Troca os /goto do Google pelo link de verdade (em paralelo); sem jeito → pelo endereço mostrado (aproximado)."""
    pend = [it for it in itens if eh_goto(it.get("url") or "")]
    if pend:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as ex:
            res = list(ex.map(lambda it: resolver_goto(it["url"], transporte), pend))
        for it, real in zip(pend, res):
            if real:
                it["url"] = real
            else:
                aprox = url_pela_cite(it.get("cite") or "", it.get("titulo") or "")
                it["url"] = aprox or ""
                it["aproximado"] = bool(aprox)
    return [it for it in itens if it.get("url") and not eh_goto(it["url"])]


def _chave(url: str) -> str:
    n = normalizar_url(url)
    m = re.search(r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([\w-]{11})", n)
    if m:
        return "yt:" + m.group(1)
    return re.sub(r"^https?://(www\.)?", "", n).lower()


def extrair_de_html(html: str) -> List[Dict[str, Any]]:
    """Os resultados de uma página do Google salva/colada (busca normal ou Notícias): link, título, fonte e trecho."""
    from bs4 import BeautifulSoup
    sp = BeautifulSoup(html or "", "html.parser")
    out, vistos = [], set()

    def bloco_de(a):
        return a.find_parent(lambda x: x.name == "div" and any(c in (x.get("class") or []) for c in ("MjjYud", "g", "SoaBEf", "Gx5Zad")))
    def link_do_titulo(t):
        a = t.find_parent("a", href=True) or t.find("a", href=True)
        n, k = t.parent, 0
        while not a and n is not None and k < 4:
            a = n.find("a", href=True, recursive=False) or next((c.find("a", href=True, recursive=False) for c in n.find_all(recursive=False)
                                                                 if getattr(c, "find", None) and c.find("a", href=True, recursive=False)), None)
            n, k = n.parent, k + 1
        return a

    # v84_166: pelo TÍTULO (h3 / heading / .LC20lb) e daí até o link — o Google muda a estrutura
    titulos = sp.select("h3, [role=heading][aria-level='3'], .LC20lb, div.n0jPhd")
    for tit in titulos:
        if tit.find("h3"):
            continue
        a = link_do_titulo(tit)
        if not a:
            continue
        url = normalizar_url(urllib.parse.urljoin("https://www.google.com/", a.get("href") or ""))  # "/url?q=…" relativo
        if not url:
            continue
        k = _chave(url)
        if k in vistos:
            continue
        vistos.add(k)
        bloco = bloco_de(a) or a.find_parent(lambda x: x.name == "div" and (x.get("data-hveid") or x.get("data-ved"))) or a.parent
        fonte_el = (bloco or a).select_one(".VuuXrf, .MgUUmf, .NUnG9d, cite") if bloco else None
        trecho = ""
        data = ""
        if bloco:
            sn = bloco.select_one(".VwiC3b, .GI74Re, [data-sncf], .ITZIwc, .UqSP2b")
            trecho = sn.get_text(" ", strip=True)[:400] if sn else ""
            dt = bloco.select_one(".OSrXXb span, .LfVVr, .rbYSKb, .WG9SHc span")
            data = dt.get_text(" ", strip=True)[:40] if dt else ""
        cite_el = (bloco or a).select_one("cite")
        out.append({"url": url, "titulo": tit.get_text(" ", strip=True)[:300],
                    "fonte": (fonte_el.get_text(" ", strip=True) if fonte_el else _host(url))[:120],
                    "trecho": trecho, "data": data, "cite": cite_el.get_text(" ", strip=True)[:300] if cite_el else ""})
    if not out:  # HTML que não é do Google (ou mudou): pega os links de fora mesmo
        for a in sp.select("a[href]"):
            url = normalizar_url(a.get("href") or "")
            if url and _chave(url) not in vistos:
                vistos.add(_chave(url))
                out.append({"url": url, "titulo": a.get_text(" ", strip=True)[:300] or url, "fonte": _host(url), "trecho": "", "data": ""})
    return out


def extrair_de_texto(texto: str) -> List[Dict[str, Any]]:
    """Colado: o HTML da página do Google OU links soltos (um por linha, ou no meio do texto)."""
    t = str(texto or "")
    if re.search(r"<(html|div|a)\b", t[:5000], re.I) and "href" in t:
        return extrair_de_html(t)
    out, vistos = [], set()
    for u in re.findall(r"https?://[^\s<>\"'()\[\]]+", t):
        url = normalizar_url(u.rstrip(".,;)"))
        if url and _chave(url) not in vistos:
            vistos.add(_chave(url))
            out.append({"url": url, "titulo": "", "fonte": _host(url), "trecho": "", "data": ""})
    return out


def adicionar_resultados(p: Dict[str, Any], itens: Iterable[Dict[str, Any]], origem: str = "", pagina: str = "") -> Dict[str, int]:
    """Junta sem repetir (página 2, 3… e links colados se somam). Item repetido ganha o título/trecho que faltava."""
    lista = p.setdefault("resultados", [])
    por = {_chave(r["url"]): r for r in lista}
    novos = repetidos = 0
    for it in itens or []:
        url = normalizar_url(str((it or {}).get("url") or ""))
        if not url:
            continue
        k = _chave(url)
        if eh_goto(url):
            continue  # não deu pra descobrir o link de verdade
        campos = {c: " ".join(str(it.get(c) or "").split())[:lim] for c, lim in (("titulo", 300), ("fonte", 120), ("trecho", 400), ("data", 40))}
        if k in por:
            r = por[k]
            for c, v in campos.items():
                if v and not r.get(c):
                    r[c] = v
            repetidos += 1
            continue
        r = {"id": uuid.uuid4().hex[:8], "url": url, "tipo": tipo_de(url), "marcado": True, "origem": origem[:40],
             "pagina": pagina[:20], "adicionado": time.time(), **campos}
        if it.get("aproximado"):
            r["aproximado"] = True  # montado pelo endereço que o Google mostra (pode faltar um pedaço)
        if not r["fonte"]:
            r["fonte"] = _host(url)
        lista.append(r)
        por[k] = r
        novos += 1
    return {"novos": novos, "repetidos": repetidos, "total": len(lista)}


def marcados(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [r for r in p.get("resultados") or [] if r.get("marcado", True)]
