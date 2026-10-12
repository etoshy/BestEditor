"""
capitulos_video.py
==================

📑 CAPÍTULOS DO YOUTUBE NO TEMPO DO VÍDEO FINAL (v84_68).

O roteiro do 🕵️ modelo de vídeo traz os capítulos ("comeca_em" = as primeiras palavras de cada um).
Depois de gerar a voz o site já punha o tempo de cada um NO ÁUDIO — mas o vídeo final não é o áudio:
as chamadas (inscreva-se/venda) e os cortes com vídeo pausam a narração e empurram tudo o que vem
depois. Aqui o tempo de cada capítulo é achado na narração DO PRÓPRIO VÍDEO (as palavras com tempo
da transcrição) e deslocado pelos clipes inseridos, do mesmo jeito que a legenda — a descrição sai
pronta pra colar.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

MIN_ENTRE = 10.0  # o YouTube exige pelo menos 10 s entre capítulos


def tempo_no_video(t: float, cortes: List[Dict[str, Any]]) -> float:
    """Segundo da narração → segundo no vídeo final, com os clipes inseridos
    (cada corte: insertion_point, remove_ate opcional, duration)."""
    shift = 0.0
    for c in sorted(cortes or [], key=lambda c: float(c["insertion_point"])):
        ponto = float(c["insertion_point"])
        fim = float(c.get("remove_ate") or ponto)
        dur = float(c.get("duration") or 0.0)
        if fim > ponto:  # o clipe entra NO LUGAR desse trecho da fala
            if ponto <= t < fim:
                return ponto + shift  # o capítulo começa junto com o clipe
            if t >= fim:
                shift += dur - (fim - ponto)
        elif ponto <= t:
            shift += dur
    return t + shift


def calcular(res: Dict[str, Any], palavras: List[Dict[str, Any]], duracao_narracao: Optional[float],
             cortes: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Capítulos do resultado do roteiro → [{titulo, segundos}] no vídeo final."""
    import roteiros_yt
    if not (res or {}).get("capitulos"):
        return []
    caps = roteiros_yt.capitulos_pelo_audio({"resultado": res}, palavras, duracao_narracao)
    out = []
    for k, c in enumerate(caps):
        s = c.get("segundos_audio")
        if s is None:
            s = (c.get("posicao") or 0.0) * float(duracao_narracao or 0)
        out.append({"titulo": c["titulo"], "segundos": 0.0 if k == 0 else round(tempo_no_video(float(s), cortes or []), 1)})
    for k in range(1, len(out)):
        if out[k]["segundos"] < out[k - 1]["segundos"] + MIN_ENTRE:
            out[k]["segundos"] = round(out[k - 1]["segundos"] + MIN_ENTRE, 1)
    return out


def fmt(s: float, longo: bool) -> str:
    s = int(round(s))
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}" if longo else f"{s // 60}:{s % 60:02d}"


def linhas(caps: List[Dict[str, Any]], duracao_video: Optional[float] = None) -> str:
    longo = max([duracao_video or 0.0] + [c["segundos"] for c in caps]) >= 3600
    return "\n".join(f"{fmt(c['segundos'], longo)} {c['titulo']}" for c in caps)


def para_job(job: Dict[str, Any], base: str, palavras: List[Dict[str, Any]], cortes: List[Dict[str, Any]],
             duracao_video: Optional[float]) -> Optional[Tuple[List[Dict[str, Any]], str]]:
    """Vídeo ligado a um 🕵️ modelo de vídeo ou a um 📝 Roteiro do YouTube → (capítulos, descrição pronta).
    Grava no projeto também (a descrição de lá passa a usar os tempos do vídeo final)."""
    if job.get("dossie_id"):
        import dossies
        carregar, salvar, descricao = (lambda: dossies.carregar(base, job["dossie_id"]), lambda p: dossies.salvar(base, p),
                                       dossies.descricao_completa)
    elif job.get("roteiro_id"):
        import roteiros_yt
        carregar, salvar = (lambda: roteiros_yt.carregar_projeto(base, job["roteiro_id"]), lambda p: roteiros_yt.salvar_projeto(base, p))
        descricao = lambda p: roteiros_yt.descricao_com_capitulos(p.get("resultado") or {})  # noqa: E731
    else:
        return None
    p = carregar()
    res = p.get("resultado") or {}
    if not res.get("capitulos"):
        return None
    dur_narr = float(job.get("total_duration") or 0) or None
    caps = calcular(res, palavras, dur_narr, cortes)
    if not caps:
        return None
    res["capitulos_video"] = {"capitulos": caps, "job_id": job.get("job_id"), "duracao": duracao_video,
                              "gerado_em": __import__("time").time()}
    p["resultado"] = res
    salvar(p)
    return caps, descricao(p)
