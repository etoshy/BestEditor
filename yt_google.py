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
          quantidade: int = 20, max_buscas: int = yt_agente.MAX_BUSCAS) -> Dict[str, Any]:
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

    log("🤖 Claude busca e escolhe os vídeos · 🔎 a IA do Google assiste e acha o momento")
    r = yt_agente.procurar(
        descricao, termo, duracao_alvo, so_google=True,
        assistir=lambda v: igr.momento(v["url"], descricao, duracao_alvo),
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
    return r


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
