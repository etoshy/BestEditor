"""
🛒 Vídeo de venda — projeto de venda de UM produto (por enquanto, link da Amazon).

Fluxo:
  1. link do produto -> título, preço, tópicos, descrição e fotos (Amazon);
     se a Amazon bloquear, a pessoa preenche na mão.
  2. materiais: texto, fotos e vídeos — do PC (a pessoa DIZ o que é cada um)
     ou de links (o site pega a OG: título, descrição, imagem; dá pra
     descrever também). Em cada um: usar a OG, a descrição ou as duas.
  3. como vender: técnicas (urgência, benefício, percepção de valor…), onde
     fica o link, preço (falar / só na tela / não citar), pago ou gratuito,
     filtros (não parecer propaganda paga, palavras proibidas, aviso de
     afiliado…).
  4. prompt -> IA -> JSON com o roteiro narrado (marcas [M1] onde cada mídia
     entra), os momentos, a descrição do vídeo, títulos e hashtags.
  5. Gerar voz com o roteiro; no Novo vídeo escolhe o projeto: o prompt do
     editor recebe as mídias do produto (provider "produto", query = ID) e a
     montagem usa os arquivos do projeto nesses trechos.

Projetos em <base>/vendas/<id>/projeto.json, arquivos em <base>/vendas/<id>/midias/.
"""
from __future__ import annotations

import html as _html
import json
import mimetypes
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

PASTA = "vendas"
MAX_DOWNLOAD = 300 * 1024 * 1024  # 300 MB por arquivo

EXT_FOTO = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp")
EXT_VIDEO = (".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi")

TIPOS_MIDIA = {"foto": "🖼 Foto", "video": "🎥 Vídeo", "texto": "📝 Texto", "link": "🔗 Link/página"}

TECNICAS: List[Tuple[str, str, str]] = [
    ("beneficios", "✅ Benefícios", "o que muda na vida de quem usa (não só as características)"),
    ("dor_solucao", "🩹 Dor → solução", "começa pelo problema que a pessoa sente e mostra o produto resolvendo"),
    ("percepcao_valor", "💎 Percepção de valor", "faz o preço parecer pequeno perto do que entrega (custo por uso, durabilidade, economia)"),
    ("ancoragem", "⚓ Ancoragem de preço", "compara com algo mais caro antes de falar o preço (só com preço real informado)"),
    ("urgencia", "⏰ Urgência", "motivo pra decidir agora — só com fato real (promoção, data, estoque informados)"),
    ("escassez", "📦 Escassez", "pouca unidade / edição limitada — só se isso foi informado"),
    ("prova_social", "⭐ Prova social", "avaliações e quantidade de compradores — só os números informados, nunca inventar"),
    ("autoridade", "🎓 Autoridade", "marca, certificação, especialista — só o que estiver nos dados"),
    ("demonstracao", "🎬 Demonstração", "mostra o produto funcionando, passo a passo, junto com as mídias"),
    ("storytelling", "📖 História", "uma situação do dia a dia em que o produto faz diferença"),
    ("objecoes", "🛡 Quebra de objeções", "responde as dúvidas comuns (é difícil? vale a pena? serve pra mim?)"),
    ("garantia", "🔁 Garantia / risco zero", "devolução, garantia — só se informado"),
    ("comparacao", "⚖️ Comparação", "antes/depois ou com o jeito antigo de fazer (sem citar marca concorrente)"),
    ("bonus", "🎁 Bônus / brinde", "o que vem junto — só se informado"),
    ("fomo", "👀 Curiosidade / FOMO", "gancho que dá vontade de ver até o fim"),
    ("cta_forte", "👉 Chamada pra ação forte", "pede a ação com clareza, mais de uma vez"),
]

LINK_ONDE = {
    "descricao": "o link está na descrição do vídeo (diga isso na narração)",
    "comentario": "o link está no comentário fixado (diga isso na narração)",
    "bio": "o link está na bio do perfil (diga isso na narração)",
    "nao_falar": "NÃO fale de link na narração (ele só fica na descrição)",
}
PRECO_MODO = {
    "falar": "pode FALAR o preço na narração",
    "tela": "NÃO fale o preço; ele aparece só escrito na tela (ponha em \"texto_na_tela\" num momento)",
    "nao": "NÃO cite o preço em lugar nenhum (pode mudar a qualquer hora)",
}
FILTROS = [
    ("nao_publi", "Não parecer propaganda paga", "tom de recomendação/review sincero, sem cara de comercial de TV nem \"publi\""),
    ("sem_promessa", "Não prometer resultado", "nada de \"garantido\", \"cura\", \"emagreça X kg\", resultado financeiro"),
    ("sem_pressao", "Sem pressão agressiva", "nada de \"compre AGORA\", \"última chance\" gritado, contagem regressiva falsa"),
    ("sem_concorrente", "Não citar concorrentes", "nenhuma marca concorrente pelo nome"),
    ("sem_pessoal", "Sem experiências pessoais / citações a outros vídeos",
     "nada de \"quando eu era criança\", \"como falei no vídeo passado\", histórias de quem gravou os vídeos/avaliações usados como material"),
    ("aviso_afiliado", "Aviso de link de afiliado", "a descrição avisa que o link é de afiliado (\"Como associado da Amazon, ganho com compras qualificadas.\")"),
]

CONFIG_PADRAO: Dict[str, Any] = {
    "tecnicas": ["beneficios", "dor_solucao", "percepcao_valor", "demonstracao", "objecoes", "cta_forte"],
    "tom": "",
    "duracao_s": 60,
    "idioma": "pt",
    "formato": "9:16",
    "link_onde": "descricao",
    "preco_modo": "falar",
    "tipo_produto": "pago",
    "oferta": "",
    "publico": "",
    "filtros": ["nao_publi", "sem_promessa", "aviso_afiliado", "sem_pessoal"],
    "proibidos": "",
    "apoio_criador": "nao",
    "referencia": "",  # 📐 transcrição de um vídeo que viralizou: a IA copia a estrutura
}
APOIO_CRIADOR = {
    "sim": "diga, de forma natural e honesta (uma vez, perto do fim), que comprando pelo link a pessoa AJUDA o canal/criador "
           "— ele ganha uma pequena comissão e ela não paga nada a mais por isso",
    "nao": "NÃO fale de comissão nem que a compra ajuda o criador",
}


AVISO_AFILIADO = {
    "pt": "Como associado da Amazon, ganho com compras qualificadas.",
    "en": "As an Amazon Associate I earn from qualifying purchases.",
    "es": "Como afiliado de Amazon, gano con las compras que cumplen los requisitos.",
    "fr": "En tant que Partenaire Amazon, je réalise un bénéfice sur les achats remplissant les conditions requises.",
    "de": "Als Amazon-Partner verdiene ich an qualifizierten Verkäufen.",
    "it": "In qualità di Affiliato Amazon, ricevo un guadagno dagli acquisti idonei.",
}


class VendaError(Exception):
    pass


# ------------------------------------------------------------------ projetos
def _pasta(base: str, pid: str = "") -> str:
    return os.path.join(base, PASTA, pid) if pid else os.path.join(base, PASTA)


def pasta_midias(base: str, pid: str) -> str:
    return os.path.join(_pasta(base, pid), "midias")


def _arquivo(base: str, pid: str) -> str:
    return os.path.join(_pasta(base, pid), "projeto.json")


def valido(pid: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{10}", str(pid or "")))


def criar(base: str, link: str = "", nome: str = "") -> Dict[str, Any]:
    pid = uuid.uuid4().hex[:10]
    p = {"id": pid, "criado": time.time(), "atualizado": time.time(), "nome": (nome or "").strip()[:160],
         "link": (link or "").strip()[:2000], "loja": "amazon" if _eh_amazon(link) else ("outro" if link else ""),
         "produto": {"titulo": "", "preco": "", "topicos": [], "descricao": "", "detalhes": "", "imagens": [], "videos": [],
                     "conteudo": "", "legendas": {}},
         "produto_erro": None, "midias": [], "config": dict(CONFIG_PADRAO), "roteiro": None}
    salvar(base, p)
    return p


def carregar(base: str, pid: str) -> Dict[str, Any]:
    if not valido(pid) or not os.path.exists(_arquivo(base, pid)):
        raise VendaError("Projeto de venda não encontrado.")
    with open(_arquivo(base, pid), encoding="utf-8") as f:
        p = json.load(f)
    p["config"] = dict(CONFIG_PADRAO, **(p.get("config") or {}))
    import idiomas
    p["config"]["idioma"] = idiomas.normalizar(p["config"].get("idioma")) or "pt"  # "pt-BR" antigo -> "pt"
    return p


def salvar(base: str, p: Dict[str, Any]) -> None:
    os.makedirs(_pasta(base, p["id"]), exist_ok=True)
    p["atualizado"] = time.time()
    tmp = _arquivo(base, p["id"]) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _arquivo(base, p["id"]))


def listar(base: str) -> List[Dict[str, Any]]:
    out = []
    if not os.path.isdir(_pasta(base)):
        return out
    for pid in os.listdir(_pasta(base)):
        try:
            p = carregar(base, pid)
        except Exception:  # noqa: BLE001
            continue
        out.append({"id": p["id"], "nome": nome_do_projeto(p), "atualizado": p.get("atualizado") or 0,
                    "midias": len(p.get("midias") or []), "tem_roteiro": bool(p.get("roteiro"))})
    return sorted(out, key=lambda x: -x["atualizado"])


def excluir(base: str, pid: str) -> None:
    import shutil
    if valido(pid) and os.path.isdir(_pasta(base, pid)):
        shutil.rmtree(_pasta(base, pid), ignore_errors=True)


def nome_do_projeto(p: Dict[str, Any]) -> str:
    return (p.get("nome") or (p.get("produto") or {}).get("titulo") or p.get("link") or "Produto sem nome")[:120]


# ------------------------------------------------------------------ baixar páginas e arquivos
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0 Safari/537.36")
_CABECALHOS = {"User-Agent": _UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
               "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"}


def _checar_url(url: str) -> str:
    url = (url or "").strip()
    if not re.match(r"https?://", url, re.IGNORECASE):
        raise VendaError("O link precisa começar com http:// ou https://.")
    return url


def _eh_amazon(url: Any) -> bool:
    host = urlparse(str(url or "")).netloc.lower()
    return bool(re.search(r"(^|\.)amazon\.[a-z.]+$|(^|\.)amzn\.(to|com|eu|asia)$|(^|\.)a\.co$", host))


def _pagina_bloqueada(html: str) -> bool:
    h = html[:20000].lower()
    return ("captcha" in h and "amazon" in h) or "robot check" in h or "api-services-support@amazon.com" in h


def baixar_html(url: str, timeout: int = 20, navegador: bool = True) -> Tuple[str, str]:
    """(html, url_final). Tenta direto; se a loja bloquear (captcha), tenta com o
    Chromium do Playwright (como um navegador de verdade)."""
    import requests
    url = _checar_url(url)
    html, final, erro = "", url, None
    try:
        r = requests.get(url, headers=_CABECALHOS, timeout=timeout, allow_redirects=True)
        html, final = r.text or "", r.url or url
        if r.status_code >= 400:
            erro = f"a página respondeu {r.status_code}"
    except requests.RequestException as exc:
        erro = str(exc)
    if (erro or _pagina_bloqueada(html)) and navegador:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                b = pw.chromium.launch(headless=True)
                try:
                    pg = b.new_page(user_agent=_UA, locale="pt-BR")
                    pg.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                    pg.wait_for_timeout(1500)
                    html, final, erro = pg.content(), pg.url, None
                finally:
                    b.close()
        except Exception as exc:  # noqa: BLE001
            erro = erro or str(exc)
    if erro and not html:
        raise VendaError(f"Não consegui abrir o link ({erro}).")
    if _pagina_bloqueada(html):
        raise VendaError("A Amazon mostrou uma verificação de robô (captcha). Tente de novo mais tarde, ou preencha os "
                         "dados do produto na mão e envie as fotos.")
    return html, final


def _texto(s: Any) -> str:
    s = re.sub(r"<[^>]+>", " ", str(s or ""))
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def ler_og(html: str, url: str = "") -> Dict[str, Any]:
    """Open Graph / Twitter / <title> / meta description de uma página."""
    def meta(*nomes):
        for n in nomes:
            m = (re.search(r'<meta[^>]+(?:property|name)=["\']' + re.escape(n) + r'["\'][^>]*content=["\']([^"\']*)["\']', html, re.IGNORECASE)
                 or re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']' + re.escape(n) + r'["\']', html, re.IGNORECASE))
            if m and m.group(1).strip():
                return _html.unescape(m.group(1).strip())
        return ""
    titulo = meta("og:title", "twitter:title")
    if not titulo:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.S)
        titulo = _texto(m.group(1)) if m else ""
    img = meta("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src")
    vid = meta("og:video:secure_url", "og:video:url", "og:video", "twitter:player:stream")
    return {"titulo": titulo[:300], "descricao": meta("og:description", "twitter:description", "description")[:1500],
            "imagem": urljoin(url, img) if img else "", "video": urljoin(url, vid) if vid else "",
            "site": meta("og:site_name")[:80], "url": url}


def ler_amazon(html: str, url: str = "") -> Dict[str, Any]:
    """Título, preço, tópicos, descrição, detalhes e fotos de uma página de produto da Amazon."""
    og = ler_og(html, url)
    m = re.search(r'id=["\']productTitle["\'][^>]*>(.*?)</span>', html, re.S | re.IGNORECASE)
    titulo = _texto(m.group(1)) if m else og["titulo"]
    titulo = re.sub(r"^\s*Amazon\.com(\.br)?\s*[:|-]\s*", "", titulo)
    preco = ""
    for padrao in (r'id=["\']corePrice[^"\']*["\'].*?class=["\']a-offscreen["\'][^>]*>([^<]+)<',
                   r'class=["\']a-price[^"\']*["\'][^>]*>\s*<span[^>]*class=["\']a-offscreen["\'][^>]*>([^<]+)<',
                   r'id=["\']priceblock_(?:ourprice|dealprice|saleprice)["\'][^>]*>([^<]+)<'):
        m = re.search(padrao, html, re.S | re.IGNORECASE)
        if m and re.search(r"\d", m.group(1)):
            preco = _texto(m.group(1))
            break
    topicos = []
    bloco = re.search(r'id=["\']feature-bullets["\'](.*?)</ul>', html, re.S | re.IGNORECASE)
    if bloco:
        for li in re.findall(r"<li[^>]*>(.*?)</li>", bloco.group(1), re.S | re.IGNORECASE):
            t = _texto(li)
            if t and not t.lower().startswith(("ver mais", "see more", "mostrar mais")):
                topicos.append(t[:500])
    desc = ""
    for ident in ("productDescription", "bookDescription_feature_div"):
        m = re.search(r'id=["\']' + ident + r'["\'][^>]*>(.*?)</div>\s*(?:</div>|<div[^>]+id=)', html, re.S | re.IGNORECASE)
        if m and _texto(m.group(1)):
            desc = _texto(m.group(1))[:4000]
            break
    detalhes = []
    tab = re.search(r'id=["\']productOverview_feature_div["\'](.*?)</table>', html, re.S | re.IGNORECASE)
    if tab:
        for k, v in re.findall(r"<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>", tab.group(1), re.S | re.IGNORECASE):
            if _texto(k) and _texto(v):
                detalhes.append(f"{_texto(k)}: {_texto(v)}")
    nota = re.search(r'id=["\']acrPopover["\'][^>]*title=["\']([^"\']+)["\']', html, re.IGNORECASE)
    n_aval = re.search(r'id=["\']acrCustomerReviewText["\'][^>]*>([^<]+)<', html, re.IGNORECASE)
    if nota:
        detalhes.append(f"Avaliação na Amazon: {_texto(nota.group(1))}" + (f" ({_texto(n_aval.group(1))})" if n_aval else ""))
    imagens: List[str] = []
    for u in re.findall(r'"hiRes"\s*:\s*"(https://[^"]+)"', html) + re.findall(r'"large"\s*:\s*"(https://[^"]+)"', html):
        if u not in imagens:
            imagens.append(u)
    if not imagens:
        m = re.search(r'data-old-hires=["\'](https://[^"\']+)["\']', html) or re.search(r'id=["\']landingImage["\'][^>]*src=["\'](https://[^"\']+)["\']', html)
        if m:
            imagens.append(m.group(1))
        m = re.search(r'data-a-dynamic-image=["\']({[^"\']+})["\']', html)
        if m:
            try:
                for u in json.loads(_html.unescape(m.group(1))):
                    if u not in imagens:
                        imagens.append(u)
            except ValueError:
                pass
    if not imagens and og["imagem"]:
        imagens.append(og["imagem"])
    # mesma foto em tamanhos diferentes (…_AC_SL1500_.jpg / …_AC_SX679_.jpg): fica a maior
    vistas, unicas = set(), []
    for u in imagens:
        chave = re.sub(r"\._[^/]*_\.", ".", u)
        if chave not in vistas:
            vistas.add(chave)
            unicas.append(u)
    videos = []
    for u in re.findall(r'"url"\s*:\s*"(https://[^"]+\.mp4)"', html):
        if u not in videos:
            videos.append(u)
    if not titulo and not topicos and not unicas:
        raise VendaError("Não achei os dados do produto nessa página (a Amazon mudou o layout ou não é a página de um produto). "
                         "Preencha na mão.")
    return {"titulo": titulo[:300], "preco": preco[:40], "topicos": topicos[:15], "descricao": desc,
            "detalhes": "\n".join(detalhes)[:3000], "imagens": unicas[:12], "videos": videos[:4], "url": url}


# ------------------------------------------------------------------ Gumroad / landing page / qualquer página de venda
MAX_CONTEUDO_PAGINA = 15000
_PRECO_RE = re.compile(r"(?:R\$|US\$|\$|€|£|¥|₹)\s?\d{1,3}(?:[.\s]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{2})?\s?(?:€|reais|USD|BRL|EUR)",
                       re.IGNORECASE)


def _eh_gumroad(url: Any, html: str = "") -> bool:
    host = urlparse(str(url or "")).netloc.lower()
    return bool(re.search(r"(^|\.)gumroad\.com$|(^|\.)gum\.co$", host)) or "assets.gumroad.com" in (html or "")[:200000]


def _jsons_da_pagina(html: str) -> List[Any]:
    """JSON-LD + JSONs embutidos (Gumroad/React, Next.js, Nuxt…)."""
    out: List[Any] = []
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, re.S | re.IGNORECASE):
        attrs, corpo = m.group(1), m.group(2).strip()
        if not corpo or not re.search(r"application/(ld\+)?json|js-react-on-rails-component|__NEXT_DATA__|data-component-name", attrs, re.I):
            continue
        try:
            out.append(json.loads(_html.unescape(corpo) if corpo.startswith("{&quot;") else corpo))
        except ValueError:
            continue
    for m in re.finditer(r"data-(?:react-props|page)=[\"']({.*?})[\"']", html, re.S):  # props em atributo (React/Inertia)
        try:
            out.append(json.loads(_html.unescape(m.group(1))))
        except ValueError:
            continue
    return out


def _andar(x: Any, prof: int = 0):
    if prof > 12:
        return
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from _andar(v, prof + 1)
    elif isinstance(x, list):
        for v in x[:200]:
            yield from _andar(v, prof + 1)


def _preco_gumroad(d: Dict[str, Any]) -> str:
    cents = d.get("price_cents")
    if cents is None:
        return ""
    try:
        valor = int(cents) / 100
    except (TypeError, ValueError):
        return ""
    if valor == 0:
        return "grátis (ou pague quanto quiser)" if d.get("customizable_price") or d.get("is_pay_what_you_want") else "grátis"
    moeda = str(d.get("currency_code") or d.get("currency") or "usd").upper()
    simb = {"USD": "US$", "BRL": "R$", "EUR": "€", "GBP": "£"}.get(moeda, moeda + " ")
    txt = f"{simb}{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if moeda == "BRL" else f"{simb}{valor:,.2f}"
    return txt + ("+" if d.get("customizable_price") or d.get("is_pay_what_you_want") else "")


def _preco_ld(valor: Any, moeda: Any) -> str:
    """197.00 + BRL -> "R$ 197,00"; 19 + USD -> "US$ 19.00"; o resto fica como veio."""
    moeda = str(moeda or "").upper()
    try:
        v = float(str(valor).replace(",", "."))
    except ValueError:
        return f"{moeda} {valor}".strip()
    if moeda == "BRL":
        return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    simb = {"USD": "US$ ", "EUR": "€ ", "GBP": "£ "}.get(moeda, (moeda + " ") if moeda else "")
    return f"{simb}{v:,.2f}"


def ler_pagina(html: str, url: str = "") -> Dict[str, Any]:
    """Página de venda que não é Amazon (Gumroad, landing page, Hotmart/Kiwify, loja Shopify…):
    nome, preço, tópicos, descrição, detalhes, o CONTEÚDO inteiro da página (seções) e as
    imagens com legenda. A IA é que separa promessa, benefícios, bônus, garantia, depoimentos…"""
    import dossies  # ler_materia (texto por seções + imagens com legenda) — import aqui (dossies importa vendas)
    og = ler_og(html, url)
    titulo, preco, descricao, imagens, videos, detalhes, topicos = "", "", "", [], [], [], []
    legendas: Dict[str, str] = {}
    # 1) dados estruturados
    for bloco in _jsons_da_pagina(html):
        for d in _andar(bloco):
            tipo = d.get("@type")
            tipo = " ".join(tipo) if isinstance(tipo, list) else str(tipo or "")
            if re.search(r"\bProduct\b|\bCourse\b|\bBook\b|\bSoftwareApplication\b", tipo):  # JSON-LD
                titulo = titulo or _texto(d.get("name"))
                descricao = descricao or _texto(d.get("description"))
                ofs = d.get("offers")
                for of in (ofs if isinstance(ofs, list) else [ofs]):
                    if isinstance(of, dict) and not preco:
                        v = of.get("price") or of.get("lowPrice")
                        if v not in (None, ""):
                            preco = _preco_ld(v, of.get("priceCurrency"))
                img = d.get("image")
                for u in (img if isinstance(img, list) else [img]):
                    u = u.get("url") if isinstance(u, dict) else u
                    if isinstance(u, str) and u.startswith("http"):
                        imagens.append(u)
                ag = d.get("aggregateRating")
                if isinstance(ag, dict) and ag.get("ratingValue"):
                    detalhes.append(f"Avaliação na página: {ag.get('ratingValue')}" + (f" ({ag.get('reviewCount') or ag.get('ratingCount')} avaliações)" if ag.get('reviewCount') or ag.get('ratingCount') else ""))
            elif "price_cents" in d and (d.get("name") or d.get("description_html")):  # Gumroad
                titulo = titulo or _texto(d.get("name"))
                preco = preco or _preco_gumroad(d)
                descricao = descricao or _texto(re.sub(r"</(p|li|h\d)>", "\n", str(d.get("description_html") or d.get("description") or "")))
                if d.get("summary"):
                    topicos.append(_texto(d["summary"])[:500])
                for cov in d.get("covers") or []:
                    if isinstance(cov, dict) and str(cov.get("url") or "").startswith("http"):
                        (videos if str(cov.get("type")) == "video" else imagens).append(cov["url"])
                for at in d.get("attributes") or []:
                    if isinstance(at, dict) and at.get("name") and at.get("value"):
                        detalhes.append(f"{_texto(at['name'])}: {_texto(at['value'])}")
                rt = d.get("ratings")
                if isinstance(rt, dict) and rt.get("count"):
                    detalhes.append(f"Avaliação no Gumroad: {rt.get('average')} de 5 ({rt.get('count')} avaliações)")
                vend = d.get("sales_count")
                if vend:
                    detalhes.append(f"Vendas mostradas na página: {vend}")
                sel = d.get("seller") or d.get("creator")
                if isinstance(sel, dict) and sel.get("name"):
                    detalhes.append(f"Criador: {_texto(sel['name'])}")
    # 2) meta de preço
    if not preco:
        for n in ("product:price:amount", "og:price:amount"):
            m = re.search(r'<meta[^>]+(?:property|name)=["\']' + re.escape(n) + r'["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
            if m:
                moeda = re.search(r'<meta[^>]+(?:property|name)=["\'](?:product|og):price:currency["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
                preco = _preco_ld(m.group(1), moeda.group(1) if moeda else "")
                break
    # 3) conteúdo da página (seções + imagens com legenda)
    try:
        mat = dossies.ler_materia(html, url)
    except Exception:  # noqa: BLE001
        mat = {"titulo": "", "linha_fina": "", "texto": "", "imagens": []}
    conteudo = (mat.get("texto") or "").strip()
    for im in mat.get("imagens") or []:
        if im["url"].lower().split("?")[0].endswith((".mp4", ".webm", ".mov")):
            videos.append(im["url"])
        else:
            imagens.append(im["url"])
            if im.get("legenda"):
                legendas[im["url"]] = im["legenda"]
    if og["imagem"]:
        imagens.insert(0, og["imagem"])
    if og["video"]:
        videos.append(og["video"])
    titulo = (titulo or og["titulo"] or mat.get("titulo") or "").strip()
    descricao = (descricao or og["descricao"] or mat.get("linha_fina") or "").strip()
    if not preco:
        achados = []
        for m in _PRECO_RE.finditer(conteudo):
            v = re.sub(r"\s+", " ", m.group(0)).strip()
            if v not in achados:
                achados.append(v)
        if achados:
            preco = achados[0]
            if len(achados) > 1:
                detalhes.append("Preços que aparecem na página: " + ", ".join(achados[:8]))
    if not topicos:  # listas curtas da página costumam ser os benefícios
        for linha in conteudo.split("\n"):
            linha = linha.strip()
            if 15 <= len(linha) <= 160 and not linha.startswith("##") and len(topicos) < 12:
                topicos.append(linha)
        topicos = topicos if len(topicos) >= 3 else []
    # vídeo de vendas (YouTube/Vimeo/Wistia/Panda…) — não baixa, só avisa
    for src in re.findall(r"<iframe[^>]+src=[\"']([^\"']+)[\"']", html, re.I):
        if re.search(r"youtube|youtu\.be|vimeo|wistia|pandavideo|vturb|loom|vidalytics", src, re.I):
            detalhes.append(f"Vídeo na página: {urljoin(url, src)}")
    vistas, unicas = set(), []
    for u in imagens:
        u = urljoin(url, u)
        if u not in vistas:
            vistas.add(u)
            unicas.append(u)
    if not (titulo or conteudo or descricao):
        raise VendaError("Não achei o conteúdo dessa página. Se ela pede login ou bloqueia robôs, salve a página no navegador "
                         "(Ctrl+S → .html) e envie o arquivo.")
    return {"titulo": titulo[:300], "preco": preco[:40], "topicos": topicos[:15], "descricao": descricao[:4000],
            "detalhes": "\n".join(dict.fromkeys(detalhes))[:3000], "imagens": unicas[:12], "videos": list(dict.fromkeys(videos))[:4],
            "conteudo": conteudo[:MAX_CONTEUDO_PAGINA], "legendas": {u: legendas[u] for u in unicas[:12] if u in legendas},
            "loja": "gumroad" if _eh_gumroad(url, html) else "pagina", "url": url}


def ler_produto(html: str, url: str = "", link_original: str = "") -> Dict[str, Any]:
    """Amazon → ler_amazon; qualquer outra página → ler_pagina."""
    if _eh_amazon(url) or _eh_amazon(link_original):
        d = ler_amazon(html, url)
        d.setdefault("loja", "amazon")
        return d
    return ler_pagina(html, url)


def baixar_arquivo(url: str, pasta: str, nome_base: str, timeout: int = 60) -> Tuple[str, str]:
    """Baixa uma foto/vídeo. (caminho, tipo "foto"|"video")."""
    import requests
    url = _checar_url(url)
    os.makedirs(pasta, exist_ok=True)
    try:
        r = requests.get(url, headers=_CABECALHOS, timeout=timeout, stream=True)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise VendaError(f"Não consegui baixar {url[:120]} ({exc}).") from exc
    ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ctype.startswith("image/"):
        tipo, ext = "foto", (ext if ext in EXT_FOTO else (mimetypes.guess_extension(ctype) or ".jpg"))
    elif ctype.startswith("video/") or ext in EXT_VIDEO:
        tipo, ext = "video", (ext if ext in EXT_VIDEO else ".mp4")
    elif ext in EXT_FOTO:
        tipo = "foto"
    else:
        raise VendaError("Esse link não é um arquivo de foto ou vídeo.")
    caminho = os.path.join(pasta, f"{nome_base}{ext}")
    total = 0
    with open(caminho, "wb") as f:
        for bloco in r.iter_content(256 * 1024):
            total += len(bloco)
            if total > MAX_DOWNLOAD:
                f.close()
                os.remove(caminho)
                raise VendaError("Arquivo grande demais (mais de 300 MB).")
            f.write(bloco)
    if tipo == "foto" and ext in (".avif", ".webp", ".bmp", ".gif"):
        try:  # o montador lida melhor com JPG
            from PIL import Image
            novo = os.path.splitext(caminho)[0] + ".jpg"
            Image.open(caminho).convert("RGB").save(novo, quality=92)
            os.remove(caminho)
            caminho = novo
        except Exception:  # noqa: BLE001
            pass
    return caminho, tipo


def tipo_do_arquivo(nome: str) -> Optional[str]:
    ext = os.path.splitext(nome or "")[1].lower()
    return "foto" if ext in EXT_FOTO else "video" if ext in EXT_VIDEO else None


# ------------------------------------------------------------------ mídias
def _novo_id(p: Dict[str, Any]) -> str:
    """M1, M2… (fotos/vídeos/links) e T1, T2… (textos) — curtos, pra IA citar."""
    usados = {m["id"] for m in p.get("midias") or []}
    k = 1
    while f"M{k}" in usados:
        k += 1
    return f"M{k}"


def _novo_id_texto(p: Dict[str, Any]) -> str:
    usados = {m["id"] for m in p.get("midias") or []}
    k = 1
    while f"T{k}" in usados:
        k += 1
    return f"T{k}"


def adicionar_midia(p: Dict[str, Any], **campos: Any) -> Dict[str, Any]:
    tipo = campos.get("tipo") if campos.get("tipo") in TIPOS_MIDIA else "foto"
    m = {"id": _novo_id_texto(p) if tipo == "texto" else _novo_id(p), "tipo": tipo,
         "origem": campos.get("origem") or "pc", "arquivo": campos.get("arquivo") or "", "url": campos.get("url") or "",
         "nome": (campos.get("nome") or "")[:200], "og": campos.get("og") or None,
         "descricao": (campos.get("descricao") or "").strip()[:2000], "conteudo": (campos.get("conteudo") or "").strip()[:MAX_CONTEUDO_PAGINA if campos.get("tipo") != "texto" else 8000],
         "usar": campos.get("usar") if campos.get("usar") in ("og", "descricao", "ambos") else
                 ("ambos" if campos.get("og") and (campos.get("descricao") or "").strip() else ("og" if campos.get("og") else "descricao")),
         "do_produto": bool(campos.get("do_produto")), "criado": time.time()}
    p.setdefault("midias", []).append(m)
    return m


def midia(p: Dict[str, Any], mid: str) -> Optional[Dict[str, Any]]:
    return next((m for m in p.get("midias") or [] if m["id"].upper() == str(mid or "").strip().upper()), None)


def caminho_midia(base: str, p: Dict[str, Any], m: Dict[str, Any]) -> Optional[str]:
    if not m or not m.get("arquivo"):
        return None
    c = os.path.join(pasta_midias(base, p["id"]), os.path.basename(m["arquivo"]))
    return c if os.path.isfile(c) else None


def ia_analisar_imagens(base: str, pid: str, ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """🤖 Ficha das fotos/vídeos do produto (ângulo, em uso, embalagem, texto/preço na imagem). Sem IA: nada."""
    import ia_dossies
    import ia_servico
    if not ia_servico.ativo("venda_imagens"):
        return {"ok": False, "erro": ia_servico.motivo_desligado("venda_imagens")}
    p = carregar(base, pid)
    titulo = ((p.get("produto") or {}).get("titulo") or "")[:200]
    itens = []
    for m in p.get("midias") or []:
        if m["tipo"] not in ("foto", "video") or m.get("ia") or (ids is not None and m["id"] not in ids):
            continue
        cam = caminho_midia(base, p, m)
        if cam:
            ctx = " | ".join(x for x in (titulo and f"produto: {titulo}", m.get("descricao") and f"o que eu disse: {m['descricao']}",
                                         ((m.get("og") or {}).get("titulo"))) if x)
            itens.append({"id": m["id"], "caminho": cam, "contexto": ctx})
    fichas = ia_dossies.fichar_imagens(itens, venda=True, job=pid)
    if fichas:
        p = carregar(base, pid)
        for m in p.get("midias") or []:
            if m["id"] in fichas:
                m["ia"] = fichas[m["id"]]
        salvar(base, p)
    return {"ok": True, "fichas": len(fichas)}


def o_que_e(m: Dict[str, Any]) -> str:
    """Texto que vai pra IA dizendo o que é a mídia (OG, descrição ou as duas)."""
    if m.get("ia"):  # 🤖 ficha da IA (+ o que você escreveu)
        import ia_dossies
        txt = ia_dossies.texto_da_ficha(m["ia"])
        if txt:
            return txt + (f" | {m['descricao']}" if m.get("descricao") else "")
    og = m.get("og") or {}
    og_txt = " — ".join(x for x in (og.get("titulo"), og.get("descricao")) if x)
    desc = m.get("descricao") or ""
    if m.get("usar") == "og" and og_txt:
        return og_txt
    if m.get("usar") == "descricao" and desc:
        return desc
    return " | ".join(x for x in (desc, (f"da página: {og_txt}" if og_txt else "")) if x) or (m.get("nome") or "(sem descrição)")


# ------------------------------------------------------------------ prompt do roteiro de venda
def _palavras_por_seg(idioma: str) -> float:
    return 2.6 if str(idioma or "").lower().startswith("pt") else 2.5


def prompt_roteiro(p: Dict[str, Any], extra: str = "", base: Optional[str] = None) -> str:
    pr = p.get("produto") or {}
    cfg = dict(CONFIG_PADRAO, **(p.get("config") or {}))
    if not (pr.get("titulo") or pr.get("descricao") or pr.get("topicos") or p.get("midias")):
        raise VendaError("Coloque pelo menos o nome do produto (ou alguma descrição/material) antes de gerar o prompt.")
    gratis = cfg.get("tipo_produto") == "gratuito"
    try:
        dur = max(10, min(900, int(cfg.get("duracao_s") or 60)))
    except (TypeError, ValueError):
        dur = 60
    palavras = int(dur * _palavras_por_seg(cfg.get("idioma")))
    tec = {k: (n, d) for k, n, d in TECNICAS}
    tecnicas = [f"- {tec[k][0].split(' ', 1)[1]}: {tec[k][1]}" for k in cfg.get("tecnicas") or [] if k in tec]
    filt = {k: (n, d) for k, n, d in FILTROS}
    filtros = [f"- {filt[k][0]}: {filt[k][1]}" for k in cfg.get("filtros") or [] if k in filt]
    if (cfg.get("proibidos") or "").strip():
        filtros.append(f"- NUNCA use estas palavras/temas: {cfg['proibidos'].strip()[:600]}")

    L: List[str] = []
    L.append("Você é um copywriter especialista em VÍDEOS DE VENDA curtos pra redes sociais (Reels, Shorts, TikTok) e YouTube. "
             "Escreva o roteiro NARRADO (alguém vai ler em voz alta) de um vídeo que vende o produto abaixo, usando os "
             "materiais que eu tenho.")
    L.append("")
    L.append("## Produto")
    if pr.get("titulo"):
        L.append(f"Nome: {pr['titulo']}")
    if p.get("link"):
        L.append(f"Link: {p['link']}")
    if gratis:
        L.append("É GRATUITO (não tem preço — nunca fale em comprar; fale em baixar/pegar/acessar de graça).")
    elif pr.get("preco"):
        L.append(f"Preço: {pr['preco']}")
    if (cfg.get("oferta") or "").strip():
        L.append(f"Oferta/condição REAL (pode usar pra urgência): {cfg['oferta'].strip()[:600]}")
    if pr.get("topicos"):
        L.append("Tópicos da página:\n" + "\n".join(f"- {t}" for t in pr["topicos"][:15]))
    if pr.get("descricao"):
        L.append("Descrição da página:\n" + pr["descricao"][:3000])
    if pr.get("detalhes"):
        L.append("Detalhes:\n" + pr["detalhes"][:2000])
    if (pr.get("conteudo") or "").strip():
        L.append("")
        L.append("## Conteúdo da página de venda (extraído do link — Gumroad/landing page)")
        L.append("Leia tudo e tire daqui o que vende: a promessa principal, pra quem é, o problema que resolve, os benefícios "
                 "(transforme característica em benefício), o que vem/o que tem dentro, bônus, garantia, prova (números, "
                 "depoimentos e avaliações QUE ESTÃO na página — cite como estão, sem inventar nem aumentar), objeções "
                 "respondidas/FAQ e a oferta. Ignore menu, rodapé, termos e o que não tiver a ver com o produto.\n\n"
                 + pr["conteudo"][:12000])
    if (cfg.get("publico") or "").strip():
        L.append(f"Público-alvo: {cfg['publico'].strip()[:400]}")

    vis = [m for m in p.get("midias") or [] if m["tipo"] in ("foto", "video", "link")]
    txt = [m for m in p.get("midias") or [] if m["tipo"] == "texto"]
    if vis:
        L.append("")
        L.append("## Fotos e vídeos que eu tenho (vão aparecer no vídeo — use os IDs)")
        import midia_transcricao as mt
        for m in vis:
            cam = caminho_midia(base, p, m) if base else None
            L.append(f"- {m['id']} ({TIPOS_MIDIA[m['tipo']].split(' ', 1)[1].lower()}): {o_que_e(m)}"
                     + (mt.para_prompt(cam) if cam and m["tipo"] == "video" else ""))
    pags = [m for m in vis if (m.get("conteudo") or "").strip()]
    if pags:
        L.append("")
        L.append("## Conteúdo das páginas enviadas como material (use as informações; não invente o que não está aqui)")
        for m in pags:
            L.append(f"- {m['id']} ({m.get('url') or m.get('nome') or ''}):\n{m['conteudo'][:6000]}")
    if txt:
        L.append("")
        L.append("## Textos de apoio (informação pra você usar no roteiro)")
        for m in txt:
            L.append(f"- {m['id']}" + (f" — {m['descricao']}" if m.get("descricao") else "") + f":\n{m.get('conteudo') or ''}")

    L.append("")
    L.append("## Como vender")
    import idiomas
    nome_idioma = idiomas.nome_para_prompt(idiomas.normalizar(cfg.get("idioma")) or "pt")
    if (idiomas.normalizar(cfg.get("idioma")) or "pt") == "en":
        import roteiros_yt
        L.insert(1, roteiros_yt.regra_tags_turbo())
    L.insert(1, f"IDIOMA DE SAÍDA: escreva TUDO em {nome_idioma} — roteiro, gancho, CTA, textos na tela, descrição, títulos e "
                "hashtags —, mesmo que a página do produto e os materiais estejam em outro idioma (traduza as informações; "
                "nomes de marca e de produto ficam como são).")
    L.append(f"- Duração: ~{dur} s de narração (~{palavras} palavras). Idioma: {nome_idioma}. "
             f"Formato do vídeo: {cfg.get('formato') or '9:16'}.")
    if (cfg.get("tom") or "").strip():
        L.append(f"- Tom: {cfg['tom'].strip()[:400]}")
    if tecnicas:
        L.append("- Técnicas pra usar (misture com naturalidade, não precisa de todas em toda frase):")
        L.extend("  " + t for t in tecnicas)
    L.append(f"- Link: {LINK_ONDE.get(cfg.get('link_onde'), LINK_ONDE['descricao'])}.")
    if not gratis and p.get("link"):
        L.append(f"- Ganho do criador: {APOIO_CRIADOR.get(cfg.get('apoio_criador'), APOIO_CRIADOR['nao'])}.")
    if not gratis:
        L.append(f"- Preço: {PRECO_MODO.get(cfg.get('preco_modo'), PRECO_MODO['falar'])}.")
    if filtros:
        L.append("- Filtros (obrigatórios):")
        L.extend("  " + f for f in filtros)
    L.append("- HONESTIDADE (obrigatório): use só as informações acima. Não invente especificações, números de vendas, "
             "avaliações, depoimentos, prêmios, garantias ou promoções. Urgência e escassez só com fato real informado"
             + (" (se a página cita prazo, vagas ou bônus por tempo limitado, diga que é \"segundo a página\" — pode ter mudado)."
                if (pr.get("conteudo") or pags) else "."))
    L.append("- Comece com um GANCHO forte nos primeiros 3 segundos. Frases curtas, fáceis de falar.")
    L.append("- No ROTEIRO, ponha a marca do ID (ex.: [M2]) sozinha logo ANTES da frase em que aquela foto/vídeo deve "
             "aparecer. Use todas as mídias que fizerem sentido; uma mídia pode voltar mais de uma vez. As marcas não "
             "são lidas — o editor usa pra pôr a mídia na hora certa.")
    if any(m["tipo"] == "video" for m in vis):
        import midia_transcricao as mt
        L.append("- " + mt.instrucao_roteiro("M3"))
    if (extra or "").strip():
        L.append(f"- Pedido extra (siga com prioridade): {extra.strip()[:1500]}")

    import metodo_roteiro
    L.append("")
    L.append(metodo_roteiro.bloco("venda_curto" if dur <= 60 else "venda"))
    if (cfg.get("referencia") or "").strip():
        L.append("")
        L.append(metodo_roteiro.bloco_referencia(cfg["referencia"]))
    L.append("")
    import metodo_roteiro
    _cod = idiomas.normalizar(cfg.get("idioma")) or "pt"
    L.append(metodo_roteiro.bloco_titulos(5, "" if _cod == "pt" else nome_idioma))
    L.append("")
    L.append("## Resposta — SOMENTE um JSON válido, assim:")
    L.append(json.dumps({
        "plano": metodo_roteiro.PLANO_JSON,
        "titulo_video": "título curto e chamativo",
        "gancho": "a 1ª frase do vídeo",
        "roteiro": "[M1] Primeira frase... [M3] Outra frase...",
        "momentos": [{"midia": "M1", "trecho": "frase exata do roteiro em que a mídia entra",
                      "texto_na_tela": "texto curto opcional (ex.: o preço, um benefício)"}],
        "cta": "a chamada final",
        "descricao": "descrição do vídeo pras redes, com {LINK} onde o link do produto deve entrar",
        "titulos": ["5 opções de título (até ~60 caracteres, cada uma numa fórmula diferente da lista de títulos)"],
        "hashtags": ["#exemplo"],
        "observacoes": "algo pra quem vai editar (opcional)",
    }, ensure_ascii=False, indent=2))
    L.append("")
    L.append(idiomas.lembrete_final(idiomas.normalizar(cfg.get("idioma")) or "pt"))  # 🌐 o idioma de novo, no FIM
    return "\n".join(L)


def ler_roteiro(texto: str, p: Dict[str, Any]) -> Dict[str, Any]:
    import json_ia
    try:
        d = json_ia.carregar(texto)
    except ValueError as exc:
        raise VendaError(str(exc)) from exc
    if isinstance(d, list) and len(d) == 1 and isinstance(d[0], dict):
        d = d[0]
    if not isinstance(d, dict):
        raise VendaError("Esperava um objeto JSON com \"roteiro\".")
    rot = str(d.get("roteiro") or d.get("script") or "").strip()
    if not rot:
        raise VendaError("O JSON não tem o \"roteiro\".")
    import midia_transcricao as mt
    ids = {m["id"].upper() for m in p.get("midias") or []}
    avisos = []
    momentos, sem = mt.momentos_do_roteiro(rot, ids, d.get("momentos"))
    if sem:
        avisos.append("A IA citou mídias que não existem: " + ", ".join(sem) + " (essas marcas são ignoradas).")
    desc = str(d.get("descricao") or "").strip()
    if p.get("link"):
        desc = desc.replace("{LINK}", p["link"])
    if "aviso_afiliado" in ((p.get("config") or {}).get("filtros") or []) and p.get("link") and not any(a.lower()[:20] in desc.lower() for a in AVISO_AFILIADO.values()):
        desc = (desc + "\n\n" + AVISO_AFILIADO.get(str((p.get("config") or {}).get("idioma") or "pt")[:2], AVISO_AFILIADO["en"])).strip()
    return {"titulo_video": str(d.get("titulo_video") or d.get("titulo") or "").strip()[:200],
            "gancho": str(d.get("gancho") or "").strip()[:400], "roteiro": rot, "momentos": momentos,
            "cta": str(d.get("cta") or "").strip()[:400], "descricao": desc[:5000],
            "titulos": [str(x)[:150] for x in (d.get("titulos") or []) if str(x).strip()][:10],
            "hashtags": [str(x)[:60] for x in (d.get("hashtags") or []) if str(x).strip()][:20],
            "observacoes": str(d.get("observacoes") or "").strip()[:1500], "avisos": avisos, "gerado_em": time.time(),
            "plano": __import__("metodo_roteiro").ler_plano(d.get("plano"))}


def roteiro_para_voz(p: Dict[str, Any]) -> str:
    """Texto pra narrar: sem as marcas [M1] / [M3 0:12-0:25 áudio] (e sem marcas de cena)."""
    import midia_transcricao as mt
    return mt.tirar_marcas((p.get("roteiro") or {}).get("roteiro") or "")


# ------------------------------------------------------------------ editor (Novo vídeo com o projeto)
def midias_para_editor(base: str, p: Dict[str, Any], momentos: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Fotos/vídeos do projeto que têm arquivo (os que dá pra pôr no vídeo), com os
    momentos planejados no roteiro e, nos vídeos, a transcrição com os tempos."""
    import midia_transcricao as mt
    momentos = momentos if momentos is not None else ((p.get("roteiro") or {}).get("momentos") or [])
    out = []
    for m in p.get("midias") or []:
        cam = caminho_midia(base, p, m)
        tipo = tipo_do_arquivo(cam or "")
        if not cam or not tipo:
            continue
        usos = [mo for mo in momentos if mo.get("midia") == m["id"]]
        out.append({"id": m["id"], "tipo": tipo, "caminho": cam, "o_que_e": o_que_e(m), "usos": usos,
                    "trecho": (usos[0] if usos else {}).get("trecho") or "",
                    "texto_na_tela": (usos[0] if usos else {}).get("texto_na_tela") or "",
                    "transcricao": mt.para_prompt(cam) if tipo == "video" else ""})
    return out


def linhas_editor(ms: List[Dict[str, Any]]) -> List[str]:
    """Uma linha por mídia (com transcrição dos vídeos) + um item por momento planejado."""
    import midia_transcricao as mt
    L = []
    for m in ms:
        L.append(f"- {m['id']} ({'vídeo' if m['tipo'] == 'video' else 'foto'}): {m['o_que_e'][:300]}{m.get('transcricao') or ''}")
        for mo in m.get("usos") or []:
            L.append(f"    • trecho sugerido: \"{mo.get('trecho') or ''}\"" + mt.uso_sugerido(mo)
                     + (f" — texto na tela sugerido: \"{mo['texto_na_tela']}\"" if mo.get("texto_na_tela") else ""))
    if any(m["tipo"] == "video" for m in ms):
        L.append(mt.INSTRUCAO_EDITOR)
    return L


def bloco_prompt_editor(base: str, p: Dict[str, Any]) -> str:
    """Bloco que vai no FIM do prompt do editor: as mídias do produto e como usar."""
    ms = midias_para_editor(base, p)
    if not ms:
        return ""
    pr = p.get("produto") or {}
    L = ["", "## 🛒 Mídias do PRODUTO deste vídeo de venda (use primeiro!)",
         f"Este vídeo vende: {pr.get('titulo') or nome_do_projeto(p)}. Tenho estas fotos/vídeos do próprio produto. "
         "Nos trechos em que a narração fala do que uma delas mostra, use-a com `\"provider\": \"produto\"` e "
         "`\"query\": \"<ID>\"` (ex.: `{\"start\": 3.2, \"end\": 6.0, \"provider\": \"produto\", \"query\": \"M2\"}`) — "
         "sem \"alternativas\". O \"trecho\" sugerido é onde o roteiro de venda planejou cada uma: ache esse momento "
         "na transcrição. Use as mídias do produto nos momentos principais (apresentação, benefícios, demonstração, "
         "preço, chamada final); a mesma pode voltar, mas varie. Nos outros trechos, complete com os bancos normais "
         "(cenas de contexto, pessoas no dia a dia, o problema que o produto resolve) — nunca com outro produto/marca."]
    L.extend(linhas_editor(ms))
    return "\n".join(L)
