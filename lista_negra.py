"""
⛔ lista_negra.py — SITES BLOQUEADOS (imagens e vídeos que nunca entram no vídeo) — v84_106
=========================================================================================

Bancos pagos servem a prévia com MARCA D'ÁGUA por cima (Shutterstock, Alamy, Getty, Adobe Stock…), e o Magnific
(o antigo Freepik) também — e os buscadores (Bing, Brave, Yandex, Startpage, Google) acham muito disso. Tudo que vier
de um site desta lista é ignorado:
  • nos buscadores de imagem (a imagem, a página de origem e os endereços reserva);
  • como BANCO de vídeo/foto: um banco cujo site está na lista (ex.: "magnific") sai da ordem de busca — nem como
    reserva ele é tentado.

A lista é EDITÁVEL em ⚙️ Configurações → Fontes de vídeo (um por linha). Como cada linha casa com o endereço:
  • sem ponto ("alamy", "magnific") = esse nome como parte do endereço: alamy.com, c8.alamy.com, alamy.co.uk…
  • com ponto ("stock.adobe.", "ftcdn.net") = esse pedaço em qualquer lugar do endereço.
Além do endereço, o 🤖 juiz olha a MINIATURA: imagem com marca d'água leva nota 0 e nunca entra (busca outra; sem
nada bom, vira cartão de texto).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

PADRAO: List[str] = [
    # Magnific / Freepik (prévias com marca d'água) e parecidos
    "magnific", "freepik", "vecteezy", "pngtree", "lovepik", "pikbest",
    # bancos pagos (prévia com marca d'água)
    "alamy", "shutterstock", "gettyimages", "istockphoto", "dreamstime", "123rf", "depositphotos", "stock.adobe.",
    "adobestock", "ftcdn.net", "fotolia", "bigstockphoto", "canstockphoto", "vectorstock", "pond5", "agefotostock",
    "superstock", "masterfile", "fotosearch", "colourbox", "storyblocks", "featurepics", "panthermedia", "mostphotos",
    "zoonar", "stockfresh", "pixtastock", "imago-images", "dissolve.com", "offset.com", "bridgemanimages", "granger.com",
    "mediastorehouse", "lookandlearn", "sciencephoto", "pictorialpress", "photodune", "elements.envato.",
    "wavebreakmedia", "stocksy", "megapixl", "crushpixel", "yayimages", "lightstock",
]

# banco do site → endereços dele (se um estiver na lista, o banco inteiro sai da busca)
PROVEDORES: Dict[str, List[str]] = {"magnific": ["magnific", "freepik"], "vistacreate": ["vistacreate"],
                                    "pexels": ["pexels"], "pixabay": ["pixabay"], "mixkit": ["mixkit"]}

_TITULO = re.compile(r"\b(?:stock\s+(?:photo|image|picture|footage|illustration|vector)s?|alamy|shutterstock|getty\s*images|"
                     r"istock|dreamstime|123rf|depositphotos|adobe\s+stock|freepik|magnific|vecteezy)\b", re.I)


def normalizar(linhas: Any) -> List[str]:
    """Texto (um por linha, ou separado por vírgula) ou lista → entradas limpas, sem repetir."""
    if isinstance(linhas, str):
        itens = re.split(r"[\n,;]+", linhas)
    else:
        itens = list(linhas or [])
    out: List[str] = []
    for x in itens:
        s = str(x or "").strip().lower()
        if not s or s.startswith("#"):
            continue
        s = re.sub(r"^[a-z]+://", "", s)
        s = re.sub(r"^www\.", "", s).split("/", 1)[0].strip()
        if s and len(s) <= 80 and s not in out:
            out.append(s)
    return out[:500]


def sites(cfg: Optional[Dict[str, Any]] = None) -> List[str]:
    if cfg is None:
        try:
            from site_config import load_site_config
            cfg = load_site_config()
        except Exception:  # noqa: BLE001
            cfg = {}
    v = cfg.get("sites_bloqueados")
    return normalizar(v) if isinstance(v, (list, str)) else list(PADRAO)


def _host(url: str) -> str:
    u = str(url or "").strip().lower()
    if not u:
        return ""
    if "://" not in u:
        u = "http://" + u
    try:
        return urlparse(u).netloc.split("@")[-1].split(":", 1)[0].strip(".")
    except Exception:  # noqa: BLE001
        return u


def casa(host: str, entrada: str) -> bool:
    if not host or not entrada:
        return False
    if "." in entrada:
        return entrada.strip(".") in host if entrada.endswith(".") or entrada.startswith(".") else (
            host == entrada or host.endswith("." + entrada) or entrada in host)
    return re.search(r"(^|[.-])" + re.escape(entrada) + r"([.-]|$)", host) is not None


def bloqueado(url: str, lista: Optional[Iterable[str]] = None) -> Optional[str]:
    """A entrada da lista negra que bloqueia esse endereço (ou None)."""
    host = _host(url)
    for e in (sites() if lista is None else lista):
        if casa(host, e):
            return e
    return None


def titulo_de_banco(texto: str) -> bool:
    """"... Stock Photo - Alamy", "Free Vector | Freepik"…"""
    return bool(_TITULO.search(texto or ""))


def provedor_bloqueado(provider: str, lista: Optional[Iterable[str]] = None) -> bool:
    lst = list(sites() if lista is None else lista)
    nomes = PROVEDORES.get(str(provider or "").lower(), [])
    return any(casa(n + ".com", e) or e == n for n in nomes for e in lst)


def sem_bloqueados(provedores: Iterable[str], lista: Optional[Iterable[str]] = None) -> List[str]:
    lst = list(sites() if lista is None else lista)
    return [p for p in provedores if not provedor_bloqueado(p, lst)]
