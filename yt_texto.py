"""
Links do YouTube com o tempo, colados como TEXTO (uma linha por trecho):

    3: https://youtu.be/abc123?t=95 1:35-1:42
    https://www.youtube.com/watch?v=xyz 0:10 até 0:18
    trecho 5 - https://youtube.com/shorts/qwe 12s
    1:02:03 - 1:02:09 https://www.youtube.com/watch?v=abc

* prefixo opcional com o número do trecho ("3:", "#3", "trecho 3", "T3");
  sem número, a linha vai pro próximo trecho da lista de alvos (os
  selecionados na timeline, ou do trecho atual em diante);
* tempos em MM:SS, HH:MM:SS, segundos ("95", "95s") ou "1m35s"; o 1º é o
  início e o 2º o fim. Sem fim = início + duração do trecho. Sem tempo
  nenhum vale o ?t= do link (ou 0).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

_RE_URL = re.compile(r"(https?://)?(www\.|m\.|music\.)?(youtube\.com/(watch\?\S+|shorts/[\w-]+\S*|live/[\w-]+\S*|embed/[\w-]+\S*)|youtu\.be/[\w-]+\S*)", re.I)
_RE_TEMPO = re.compile(r"(?<![\w:.])(\d{1,2}:\d{1,2}:\d{1,2}(?:\.\d+)?|\d{1,3}:\d{1,2}(?:\.\d+)?|\d+h(?:\d+m)?(?:\d+(?:\.\d+)?s)?|\d+m(?:\d+(?:\.\d+)?s)?|\d+(?:\.\d+)?s|\d+(?:\.\d+)?)(?![\w:])", re.I)


def tempo(txt: str) -> Optional[float]:
    t = (txt or "").strip().lower()
    if not t:
        return None
    if ":" in t:
        seg = 0.0
        for p in t.split(":"):
            seg = seg * 60 + float(p)
        return seg
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s?)?", t)
    if not m or not any(m.groups()):
        return None
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)


def video_id(url: str) -> Optional[str]:
    u = url if url.lower().startswith("http") else "https://" + url
    p = urlparse(u)
    host = p.netloc.lower()
    if host.endswith("youtu.be"):
        return p.path.strip("/").split("/")[0] or None
    q = parse_qs(p.query)
    if q.get("v"):
        return q["v"][0]
    partes = [x for x in p.path.split("/") if x]
    if len(partes) >= 2 and partes[0] in ("shorts", "live", "embed"):
        return partes[1]
    return None


def _tempo_do_link(url: str) -> Dict[str, Optional[float]]:
    u = url if url.lower().startswith("http") else "https://" + url
    q = parse_qs(urlparse(u).query)
    out: Dict[str, Optional[float]] = {"inicio": None, "fim": None}
    for chave, nomes in (("inicio", ("t", "start")), ("fim", ("end",))):
        for n in nomes:
            if q.get(n):
                out[chave] = tempo(q[n][0])
                break
    return out


def parse_linha(linha: str) -> Optional[Dict[str, Any]]:
    """None pra linha vazia/comentário; senão {trecho, url, id, inicio, fim, erro}."""
    s = (linha or "").strip()
    if not s or s.startswith("//"):
        return None
    m = _RE_URL.search(s)
    if not m:
        return {"linha": s, "erro": "Não achei um link do YouTube nessa linha."}
    url = m.group(0).rstrip(".,;)")
    vid = video_id(url)
    if not vid:
        return {"linha": s, "erro": "Link do YouTube sem o id do vídeo."}
    antes, depois = s[:m.start()], s[m.end():]
    trecho = None
    p = re.match(r"^\s*(?:trecho|cena|seg(?:mento)?|t|#)\s*(\d{1,4})\s*[:.)\-–—=]?\s*", antes, re.I)
    if not p:
        p = re.match(r"^\s*(\d{1,4})\s*[:.)\-–—=]\s*$", antes)  # "3: <link>" (nada mais antes do link)
    if p:
        trecho, antes = int(p.group(1)), antes[p.end():]
    tempos = [tempo(x) for x in _RE_TEMPO.findall(antes + " " + depois)]
    tempos = [t for t in tempos if t is not None]
    do_link = _tempo_do_link(url)
    inicio = tempos[0] if tempos else do_link["inicio"]
    fim = tempos[1] if len(tempos) > 1 else do_link["fim"]
    out = {"linha": s, "trecho": trecho, "url": f"https://www.youtube.com/watch?v={vid}", "id": vid,
           "inicio": inicio, "fim": fim, "miniatura_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", "erro": None}
    if inicio is not None and fim is not None and fim <= inicio:
        out["erro"] = f"O fim ({fim:g}s) precisa vir depois do início ({inicio:g}s)."
    return out


def distribuir(texto: str, duracoes: List[float], alvos: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """Lê todas as linhas e decide o trecho (índice 0-based) e o fim de cada uma.
    `duracoes[i]` = duração do trecho i; `alvos` = ordem dos trechos pras
    linhas sem número (padrão: todos, do 1º em diante)."""
    fila = [i for i in (alvos if alvos is not None else range(len(duracoes))) if 0 <= i < len(duracoes)]
    usados: set = set()
    out = []
    for linha in (texto or "").splitlines():
        r = parse_linha(linha)
        if r is None:
            continue
        if not r.get("erro"):
            if r.get("trecho") is not None:
                idx = r["trecho"] - 1
                if not 0 <= idx < len(duracoes):
                    r["erro"] = f"Não existe o trecho {r['trecho']} (o projeto tem {len(duracoes)})."
            else:
                idx = next((i for i in fila if i not in usados), None)
                if idx is None:
                    r["erro"] = "Sobrou link sem trecho — selecione mais trechos ou ponha o número (ex.: \"5: link\")."
            if not r.get("erro"):
                usados.add(idx)
                r["indice"] = idx
                dur = float(duracoes[idx])
                r["inicio"] = float(r["inicio"] or 0.0)
                if r["fim"] is None:
                    r["fim"] = round(r["inicio"] + dur, 2)
                r["duracao_trecho"] = round(dur, 2)
                if r["fim"] - r["inicio"] < dur - 0.05:
                    r["aviso"] = f"o clipe ({r['fim'] - r['inicio']:.1f}s) é mais curto que o trecho ({dur:.1f}s)"
        out.append(r)
    return out
