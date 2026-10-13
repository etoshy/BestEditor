"""
yt_google.py
============

🔎🤖 ACHAR COM CLAUDE + GOOGLE (v84_88) — o botão ALTERNATIVO de todas as partes de YouTube do site
(🎬 cenas do Roteiro do YouTube, painel do YouTube no editor, ✂️ Cortar do YouTube):

  1. a IA (Claude) faz as buscas/perguntas pra achar a cena (e refaz se não achar);
  2. busca no YouTube e a IA escolhe os vídeos mais prováveis (capa, título, canal, duração);
  3. o LINK de cada vídeo vai pra 🔎 IA do Google (pela API dela), que "assiste" o vídeo e devolve o momento certo
     (início/fim) — sem depender de legenda.

  achar(descricao, termo, duracao_alvo) → {"achou", "url", "titulo", "inicio", "fim", "frase", "buscas", ...}
  momento_no_link(url, descricao)        → só o passo 3, quando você já tem o link.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import yt_agente


class IndisponivelErro(Exception):
    pass


def disponivel() -> Optional[str]:
    """None se dá pra usar; senão, o motivo."""
    try:
        import ia_google_rotas as igr
    except Exception:  # noqa: BLE001
        return "a IA do Google não está no site"
    if not igr.instalado():
        return "a pasta ia_google/ não está no site"
    return None


def achar(descricao: str, termo: str = "", duracao_alvo: Optional[float] = None, *, ficha: Optional[Dict[str, Any]] = None,
          job: Optional[str] = None, log: Callable[[str], None] = lambda _m: None, parar: Callable[[], bool] = lambda: False,
          quantidade: int = 20, max_buscas: int = yt_agente.MAX_BUSCAS,
          ao_responder: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """`ao_responder(resposta)` é chamada a CADA resposta da IA do Google (achou ou não), pra página ir mostrando.
    O retorno traz `respostas` (todas), pra acompanhar clipe por clipe."""
    motivo = disponivel()
    if motivo:
        raise IndisponivelErro(motivo)
    import ia_google_rotas as igr
    import ia_midia
    from youtube_clipper import buscar_videos_youtube
    descricao = " ".join(str(descricao or "").split())[:900]

    def ordenar(resultados, t, vistos):
        try:
            return ia_midia.ordenar_youtube(resultados, descricao, t, ficha, job=job, com_capas=12, ja_vistos=vistos)
        except Exception:  # noqa: BLE001
            return None

    def nova_busca(feitas, motivos):
        try:
            return ia_midia.nova_busca_youtube(descricao, feitas, motivos, ficha, job=job)
        except Exception:  # noqa: BLE001
            return ""

    respostas: List[Dict[str, Any]] = []

    def assistir(v):
        try:
            m = igr.momento(v["url"], descricao, duracao_alvo)
        except Exception as exc:  # noqa: BLE001
            respostas.append(resposta(v, None, erro=str(exc)[:160]))
            if ao_responder:
                ao_responder(respostas[-1])
            raise
        respostas.append(resposta(v, m))
        if ao_responder:
            ao_responder(respostas[-1])
        return m

    log("🤖 Claude busca e escolhe os vídeos · 🔎 a IA do Google assiste e acha o momento")
    r = yt_agente.procurar(
        descricao, termo, duracao_alvo, so_google=True,
        assistir=assistir,
        buscar=lambda t: buscar_videos_youtube(t, quantidade=quantidade), ordenar=ordenar,
        legenda=lambda _u: {}, achar=lambda _l, _v: None, nova_busca=nova_busca, log=log, parar=parar, max_buscas=max_buscas)
    if r.get("achou"):
        v = r["video"]
        ini, fim = float(r["inicio"]), float(r["fim"])
        if duracao_alvo and fim - ini < duracao_alvo:
            fim = ini + float(duracao_alvo)
            if v.get("duracao_segundos"):
                fim = min(fim, float(v["duracao_segundos"]))
        r.update(url=v["url"], titulo=str(v.get("titulo") or "")[:200], miniatura_url=str(v.get("miniatura_url") or ""),
                 inicio=round(ini, 2), fim=round(fim, 2))
    r["respostas"] = respostas
    return r


def resposta(video: Dict[str, Any], m: Optional[Dict[str, Any]], tipo: str = "google", erro: str = "") -> Dict[str, Any]:
    """Uma resposta da IA sobre um vídeo, no formato do 🧾 histórico de cada clipe."""
    import time
    import uuid
    achou = bool(m and m.get("achou"))
    return {"id": uuid.uuid4().hex[:8], "quando": time.time(), "tipo": tipo, "url": str(video.get("url") or ""),
            "titulo": str(video.get("titulo") or "")[:160], "miniatura_url": str(video.get("miniatura_url") or ""),
            "achou": achou, "inicio": round(float(m["inicio"]), 2) if achou else None,
            "fim": round(float(m["fim"]), 2) if achou else None, "frase": str((m or {}).get("frase") or "")[:240],
            "erro": erro}


def guardar_resposta(lista: Optional[List[Dict[str, Any]]], nova: Dict[str, Any], limite: int = 40) -> List[Dict[str, Any]]:
    return ([x for x in (lista or []) if isinstance(x, dict)] + [nova])[-limite:]


def momento_no_link(url: str, descricao: str, duracao_alvo: Optional[float] = None,
                    evitar: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """`evitar` (🔁 olhar de novo): os momentos que a IA do Google deu antes e estavam errados — ela é avisada na mesma
    conversa ("esses momentos não têm o que procuramos") e o que buscamos é reafirmado."""
    motivo = disponivel()
    if motivo:
        raise IndisponivelErro(motivo)
    import ia_google_rotas as igr
    if evitar:
        return igr.momento(url, descricao, duracao_alvo, evitar=evitar)
    return igr.momento(url, descricao, duracao_alvo)


def tempo_seg(t: Any) -> Optional[float]:
    """'1:05' / '1:02:05' / 65 → segundos (None se vazio/inválido)."""
    if t is None or t == "":
        return None
    if isinstance(t, (int, float)):
        return float(t)
    partes = str(t).strip().split(":")
    try:
        n = [float(x) for x in partes]
    except ValueError:
        return None
    s = 0.0
    for x in n:
        s = s * 60 + x
    return s


def mmss(s: float) -> str:
    s = max(0, int(round(float(s or 0))))
    h, m, x = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{x:02d}" if h else f"{m}:{x:02d}"


# ------------------------------------------------------------------ 🔎 perguntar pra IA do Google ONDE achar (v84_91)
import re as _re

_RE_LINK_YT = _re.compile(r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?[^\s)\]>\"']*?v=|shorts/|live/|embed/)|youtu\.be/)([\w-]{11})[^\s)\]>\"']*")
_RE_TEMPO = _re.compile(r"(?<![\d:])(\d{1,2}:\d{2}(?::\d{2})?)(?![\d:])")


def links_youtube(texto: str, fontes: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Os vídeos do YouTube citados na resposta (texto + fontes), cada um com o tempo que a IA deu (se deu):
    → [{"id", "url", "titulo", "inicio", "fim"}] na ordem em que aparecem, sem repetir."""
    out: Dict[str, Dict[str, Any]] = {}
    titulos = {}
    for f in fontes or []:
        m = _RE_LINK_YT.search(str(f.get("url") or ""))
        if m:
            titulos[m.group(1)] = str(f.get("titulo") or "")[:160]
    linhas = str(texto or "").splitlines()
    for k, linha in enumerate(linhas):
        for m in _RE_LINK_YT.finditer(linha):
            vid = m.group(1)
            if vid in out:
                continue
            ini = fim = None
            t = _re.search(r"[?&#]t=(\d+)", m.group(0))
            if t:
                ini = float(t.group(1))
            # tempos escritos na mesma linha (ou na de baixo, quando a IA quebra a linha)
            vizinho = linha.replace(m.group(0), " ") + " " + (linhas[k + 1] if k + 1 < len(linhas) and not _RE_LINK_YT.search(linhas[k + 1]) else "")
            tempos = [tempo_seg(x) for x in _RE_TEMPO.findall(vizinho)]
            tempos = [x for x in tempos if x is not None]
            if tempos and ini is None:
                ini = tempos[0]
            if len(tempos) > 1 and tempos[1] > (ini or 0):
                fim = tempos[1]
            resto = _RE_TEMPO.sub(" ", _re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", linha.replace(m.group(0), "")))
            resto = _re.sub(r"\s*(?:[-—–|·]\s*){2,}", " — ", resto)
            titulo = titulos.get(vid) or " ".join(resto.split()).strip(" -—–*:·|()[]")[:160]
            out[vid] = {"id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "titulo": titulo, "inicio": ini, "fim": fim}
    for vid, tit in titulos.items():  # link só nas fontes
        out.setdefault(vid, {"id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "titulo": tit, "inicio": None, "fim": None})
    return list(out.values())


def pergunta_onde(descricao: str) -> str:
    return (f"Quero achar no YouTube um vídeo que mostre exatamente esta cena/momento: \"{descricao}\". "
            "Pesquise com foco no YouTube e indique os melhores vídeos (de preferência o clipe oficial ou a cena isolada) "
            "com o LINK completo do YouTube (youtube.com/watch?v=... ou youtu.be/...) e o tempo EXATO em que a cena "
            "aparece em cada um (início e fim, no formato mm:ss). Responda com uma lista, um vídeo por linha: "
            "link — início–fim — o que aparece nesse trecho.")


def perguntar_onde(descricao: str, duracao_alvo: Optional[float] = None, *, log: Callable[[str], None] = lambda _m: None,
                   ao_responder: Optional[Callable[[Dict[str, Any]], None]] = None, conferir: int = 3,
                   parar: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
    """🔎 Pergunta pra IA do Google (pesquisa, com foco no YouTube) ONDE achar a cena: ela indica os links e os tempos.
    Depois, até `conferir` desses vídeos vão pra ela "assistir" e confirmar/achar o momento certo.
    → {"achou", "url", "titulo", "inicio", "fim", "frase", "respostas", "texto", "links"}"""
    motivo = disponivel()
    if motivo:
        raise IndisponivelErro(motivo)
    import ia_google_rotas as igr
    descricao = " ".join(str(descricao or "").split())[:700]
    respostas: List[Dict[str, Any]] = []

    def anotar(r):
        respostas.append(r)
        if ao_responder:
            ao_responder(r)
    log("🔎 perguntando pra IA do Google onde achar essa cena no YouTube…")
    d = igr.pesquisar(pergunta_onde(descricao), nova_conversa=True)
    texto = "\n".join(str(d.get(k) or "") for k in ("resposta_objetiva", "resposta_completa"))
    links = links_youtube(texto, d.get("fontes") or [])
    log(f"   ela indicou {len(links)} vídeo(s) do YouTube" if links else "   ela não indicou nenhum link do YouTube")
    melhor = None
    for k, l in enumerate(links[:8]):
        sugerido = {"achou": l["inicio"] is not None, "inicio": l["inicio"] or 0,
                    "fim": l["fim"] or ((l["inicio"] or 0) + (duracao_alvo or 8)), "frase": ""}
        anotar(resposta(l, sugerido if sugerido["achou"] else None, tipo="google indicou"))
        if parar():
            break
        confirmado = None
        if k < conferir:
            log(f"   🔎 a IA do Google está assistindo “{(l['titulo'] or l['url'])[:60]}” pra confirmar o momento…")
            try:
                confirmado = igr.momento(l["url"], descricao, duracao_alvo)
                anotar(resposta(l, confirmado, tipo="google"))
            except Exception as exc:  # noqa: BLE001
                anotar(resposta(l, None, tipo="google", erro=str(exc)[:160]))
        if confirmado and confirmado.get("achou"):
            melhor = dict(l, inicio=float(confirmado["inicio"]), fim=float(confirmado["fim"]), frase=confirmado.get("frase") or "")
            break
        if melhor is None and sugerido["achou"]:
            melhor = dict(l, inicio=float(sugerido["inicio"]), fim=float(sugerido["fim"]), frase="(tempo indicado na pesquisa)")
    out: Dict[str, Any] = {"achou": melhor is not None, "respostas": respostas, "texto": texto[:4000], "links": links}
    if melhor:
        ini, fim = round(melhor["inicio"], 2), round(melhor["fim"], 2)
        if duracao_alvo and fim - ini < duracao_alvo:
            fim = ini + float(duracao_alvo)
        out.update(url=melhor["url"], titulo=melhor["titulo"], inicio=ini, fim=fim, frase=melhor.get("frase") or "",
                   miniatura_url=f"https://i.ytimg.com/vi/{melhor['id']}/mqdefault.jpg")
        log(f"🎯 {out['titulo'][:60]} {mmss(ini)} → {mmss(fim)}")
    else:
        out["motivo"] = "a IA do Google não indicou um vídeo com esse momento" if not links else "nenhum dos vídeos indicados tinha o momento"
        log("❌ " + out["motivo"])
    return out
