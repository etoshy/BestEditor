"""
estilo_imagem.py — 🎞️ "este vídeo é de imagens REAIS" (v84_92)
================================================================

Os bancos de estoque (Pexels principalmente) devolvem no meio das fotos reais: boneco 3D em fundo branco, ilustração
vetorial chapada, objeto recortado em fundo preto, clipart. Num documentário de imagens reais isso quebra o vídeo.

Este módulo olha a MINIATURA (sem IA, de graça, ~50 ms) e diz se ela parece ilustração/recorte:
  • recorte_fundo_branco — a borda é quase toda branca e a imagem tem grandes áreas lisas (3D/clipart/produto isolado);
  • recorte_fundo_preto  — a borda é toda preta e lisa (objeto renderizado em fundo preto);
  • ilustracao_chapada   — áreas lisas demais e pouquíssimas cores (vetor/flat design).
Calibrado com os casos reais do projeto (boneco 3D, seta de gráfico, dinheiro 3D, hospital vetorial, médico 3D) e com
fotos reais difíceis (céu, espaço, retina com borda preta, foto P&B): nenhuma foto real marcada.

Não é um bloqueio: as marcadas só vão pro FIM da lista de candidatos (se só tiver isso, ainda usa — melhor que nada).
Com a IA ligada, o juiz também tira ponto delas (ver ia_midia: problema "ilustracao_ou_3d").

🖼️ (v84_92) Também confere o FORMATO pela miniatura: mídia em pé num vídeo deitado (16:9) — ou deitada num vídeo em pé
(9:16) — vai pro fim da fila (o filtro de orientação da busca já pede o formato certo nos bancos que têm esse filtro;
a miniatura cobre os outros e a escolha antiga).

Config `estilo_imagens`: "auto" (padrão — imagens reais, a não ser que a ficha do vídeo diga que é ilustração/misto),
"real" (sempre filtra) ou "qualquer" (não filtra).
"""
from __future__ import annotations

import io
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional

MODOS = ("auto", "real", "qualquer")
ROTULOS = {"recorte_fundo_branco": "recorte/3D em fundo branco", "recorte_fundo_preto": "recorte em fundo preto",
           "ilustracao_chapada": "ilustração/vetor"}

_CACHE: Dict[str, str] = {}
_TRAVA = threading.Lock()
_MAX_CACHE = 5000


def medir(im) -> Dict[str, float]:
    """Métricas da imagem (PIL): borda branca/preta, área branca, fração lisa e nº de cores que cobrem 90%."""
    import numpy as np
    from PIL import Image, ImageFilter
    im = im.convert("RGB")
    w, h = im.size
    s = 160 / max(w, h, 1)
    im = im.resize((max(8, int(w * s)), max(8, int(h * s))))
    a = np.asarray(im).astype(int)
    hh, ww, _ = a.shape
    b = max(2, int(min(hh, ww) * 0.06))
    borda = np.concatenate([a[:b].reshape(-1, 3), a[-b:].reshape(-1, 3), a[:, :b].reshape(-1, 3), a[:, -b:].reshape(-1, 3)])
    branco_b = float((borda.min(-1) >= 232).mean())
    preto_b = float((borda.max(-1) <= 20).mean())
    branco = float((a.reshape(-1, 3).min(-1) >= 232).mean())
    cinza = im.convert("L")
    mx = np.asarray(cinza.filter(ImageFilter.MaxFilter(3))).astype(int)
    mn = np.asarray(cinza.filter(ImageFilter.MinFilter(3))).astype(int)
    lisa = float(((mx - mn) <= 3).mean())
    q = (a >> 5).reshape(-1, 3)
    cod = q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]
    _, cont = np.unique(cod, return_counts=True)
    cont = np.sort(cont)[::-1]
    acc = np.cumsum(cont) / cont.sum()
    n90 = int(np.searchsorted(acc, 0.90) + 1)
    return {"borda_branca": branco_b, "borda_preta": preto_b, "branco": branco, "lisa": lisa, "cores90": n90}


def classificar(im) -> str:
    """"" = parece foto/filmagem real; senão o motivo (chave de ROTULOS)."""
    try:
        m = medir(im)
    except Exception:  # noqa: BLE001
        return ""
    if m["borda_branca"] >= 0.6 and m["branco"] >= 0.35 and m["lisa"] >= 0.5:
        return "recorte_fundo_branco"
    if m["borda_preta"] >= 0.8 and m["lisa"] >= 0.6:
        return "recorte_fundo_preto"
    if m["lisa"] >= 0.65 and m["cores90"] <= 15:
        return "ilustracao_chapada"
    return ""


def formato(im) -> str:
    """"horizontal" | "vertical" | "quadrada" pela proporção da imagem."""
    w, h = im.size
    if not w or not h:
        return ""
    r = w / h
    return "horizontal" if r >= 1.15 else ("vertical" if r <= 0.87 else "quadrada")


def analisar(im) -> Dict[str, str]:
    return {"estilo": classificar(im), "formato": formato(im)}


def classificar_bytes(dados: bytes) -> str:
    return _analisar_bytes(dados)["estilo"]


def _analisar_bytes(dados: bytes) -> Dict[str, str]:
    from PIL import Image
    try:
        with Image.open(io.BytesIO(dados)) as im:
            im.seek(0)
            return analisar(im)
    except Exception:  # noqa: BLE001
        return {"estilo": "", "formato": ""}


def classificar_arquivo(caminho: str) -> str:
    return analisar_arquivo(caminho)["estilo"]


def analisar_arquivo(caminho: str) -> Dict[str, str]:
    from PIL import Image
    try:
        with Image.open(caminho) as im:
            im.seek(0)
            return analisar(im)
    except Exception:  # noqa: BLE001
        return {"estilo": "", "formato": ""}


def _baixar(url: str, timeout: float) -> Optional[bytes]:
    import requests
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0"})
    if r.status_code != 200 or len(r.content) > 6_000_000:
        return None
    return r.content


_VAZIO = {"estilo": "", "formato": ""}


def analisar_url(url: str, timeout: float = 6.0, baixar: Optional[Callable[[str, float], Optional[bytes]]] = None) -> Dict[str, str]:
    """Miniatura por URL ou caminho (com cache): {"estilo", "formato"}. Erro de rede = vazio (não pune quem não deu
    pra olhar)."""
    if not url or str(url).startswith("data:"):
        return dict(_VAZIO)
    if not str(url).startswith(("http://", "https://")):
        import os
        return analisar_arquivo(url) if os.path.isfile(url) else dict(_VAZIO)
    with _TRAVA:
        if url in _CACHE:
            return dict(_CACHE[url])
    try:
        dados = (baixar or _baixar)(url, timeout)
        res = _analisar_bytes(dados) if dados else dict(_VAZIO)
    except Exception:  # noqa: BLE001
        return dict(_VAZIO)
    with _TRAVA:
        if len(_CACHE) > _MAX_CACHE:
            _CACHE.clear()
        _CACHE[url] = dict(res)
    return res


def classificar_url(url: str, timeout: float = 6.0, baixar: Optional[Callable[[str, float], Optional[bytes]]] = None) -> str:
    """Estilo da miniatura ("" = parece foto real)."""
    return analisar_url(url, timeout, baixar)["estilo"]


def formato_url(url: str, timeout: float = 6.0, baixar: Optional[Callable[[str, float], Optional[bytes]]] = None) -> str:
    """Formato da miniatura ("horizontal" | "vertical" | "quadrada" | "" sem dar pra ver)."""
    return analisar_url(url, timeout, baixar)["formato"]


FORMATO_DO_VIDEO = {"16:9": "horizontal", "9:16": "vertical"}


def formato_errado(formato_midia: str, orientacao_video: Optional[str]) -> bool:
    """Mídia em pé num vídeo deitado (ou o contrário). Quadrada / sem saber = não é erro."""
    alvo = FORMATO_DO_VIDEO.get(str(orientacao_video or ""))
    return bool(alvo and formato_midia and formato_midia != "quadrada" and formato_midia != alvo)


def modo_real(cfg: Optional[Dict[str, Any]]) -> bool:
    """O vídeo quer só imagens reais? (config + a ficha do vídeo, quando a IA leu o roteiro)."""
    cfg = cfg or {}
    modo = str(cfg.get("estilo_imagens") or "auto")
    if modo == "qualquer":
        return False
    if modo == "real":
        return True
    return str(cfg.get("_estilo_ficha") or "real") not in ("ilustracao", "misto")


def ordenar(itens: List[Any], miniatura: Callable[[Any], str], limite: int = 6, timeout: float = 6.0,
            marcar: Optional[Callable[[Any, str], None]] = None,
            classificar_fn: Optional[Callable[[str], str]] = None,
            orientacao: Optional[str] = None, checar_estilo: bool = True,
            formato_fn: Optional[Callable[[str], str]] = None,
            marcar_formato: Optional[Callable[[Any], None]] = None) -> List[Any]:
    """Os `limite` primeiros itens são olhados (em paralelo). Ficam na frente os que parecem foto real E estão no
    formato do vídeo; os que não foram olhados vêm depois; no fim, os em pé num vídeo deitado (ou o contrário) e, por
    último, desenho/3D/recorte. A ordem dentro de cada grupo se mantém."""
    if not itens:
        return itens
    alvo = FORMATO_DO_VIDEO.get(str(orientacao or ""))
    if not checar_estilo and not alvo:
        return list(itens)
    olhar = list(itens[:max(1, limite)])
    f_est = classificar_fn or (lambda u: classificar_url(u, timeout))
    f_fmt = formato_fn or (lambda u: formato_url(u, timeout))

    def _um(it):
        u = miniatura(it) or ""
        return (f_est(u) if checar_estilo else ""), (f_fmt(u) if alvo else "")
    with ThreadPoolExecutor(max_workers=min(6, len(olhar))) as ex:
        res = list(ex.map(_um, olhar))
    bons, meio, ruins = [], [], []
    for it, (mot, fmt) in zip(olhar, res):
        errado = formato_errado(fmt, orientacao)
        if errado and marcar_formato:
            try:
                marcar_formato(it)
            except Exception:  # noqa: BLE001
                pass
        if mot:
            if marcar:
                try:
                    marcar(it, mot)
                except Exception:  # noqa: BLE001
                    pass
            ruins.append(it)
        elif errado:
            meio.append(it)
        else:
            bons.append(it)
    return bons + list(itens[len(olhar):]) + meio + ruins


def filtro_ativo(cfg: Optional[Dict[str, Any]]) -> bool:
    """Tem o que conferir? (estilo "imagens reais" e/ou o formato do vídeo 16:9 / 9:16)."""
    cfg = cfg or {}
    return modo_real(cfg) or str(cfg.get("orientation") or "") in FORMATO_DO_VIDEO


def ordenar_candidatos(candidatos: List[Dict[str, Any]], cfg: Optional[Dict[str, Any]], limite: int = 6,
                       chave: str = "thumbnail", classificar_fn: Optional[Callable[[str], str]] = None,
                       formato_fn: Optional[Callable[[str], str]] = None) -> List[Dict[str, Any]]:
    """Candidatos da prévia (dicts com "thumbnail"): desenho/3D/recorte e mídia no formato errado vão pro fim,
    marcados com "estilo_problema" / "formato_errado"."""
    cfg = cfg or {}
    if not candidatos or not filtro_ativo(cfg):
        return candidatos
    copia = [dict(c) for c in candidatos]
    return ordenar(copia, lambda c: c.get(chave) or c.get("image_url") or "", limite,
                   marcar=lambda c, m: c.__setitem__("estilo_problema", m), classificar_fn=classificar_fn,
                   orientacao=cfg.get("orientation"), checar_estilo=modo_real(cfg), formato_fn=formato_fn,
                   marcar_formato=lambda c: c.__setitem__("formato_errado", True))


def miniatura_de_resultado(r: Any) -> str:
    """Miniatura de um resultado de cliente do toolkit (vídeo: to_dict()["thumbnail"]; foto: sizes)."""
    try:
        sizes = getattr(r, "sizes", None)
        if isinstance(sizes, dict) and sizes:
            return sizes.get("tiny") or sizes.get("small") or sizes.get("medium") or ""
        data = r.to_dict() if hasattr(r, "to_dict") else (r if isinstance(r, dict) else {})
        return str(data.get("thumbnail") or data.get("image") or "")
    except Exception:  # noqa: BLE001
        return ""


def ordenar_resultados(resultados: Iterable[Any], cfg: Optional[Dict[str, Any]], limite: int = 6,
                       classificar_fn: Optional[Callable[[str], str]] = None, orientacao: Optional[str] = None,
                       formato_fn: Optional[Callable[[str], str]] = None) -> List[Any]:
    """Mesma coisa pros objetos do toolkit, na montagem (quando ela busca de novo). `orientacao` = a do vídeo."""
    lista = list(resultados or [])
    real = modo_real(cfg)
    if not lista or (not real and orientacao not in FORMATO_DO_VIDEO):
        return lista
    return ordenar(lista, miniatura_de_resultado, limite, classificar_fn=classificar_fn, orientacao=orientacao,
                   checar_estilo=real, formato_fn=formato_fn)
