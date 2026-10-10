"""Timelines alternativas do Estúdio.

- Timeline 1: a de sempre (a melhor opção de cada cena).
- Timeline 2: a 2ª melhor opção de cada cena (gerada sob demanda).
- Timeline 3 ("Juntar"): trecho a trecho, a pessoa escolhe de qual das duas
  vem a mídia.

Tudo que é EDIÇÃO (efeitos, entradas/saídas, transições, cenas, textos,
destaques, sons, direção da IA, tempos dos trechos…) é um só pras três: só
a MÍDIA de cada trecho muda de uma timeline pra outra. Por isso a timeline
ativa continua morando em `pending_segments`/`segment_previews` (o resto do
site — editor, montagem — não precisa saber de timelines) e as outras ficam
guardadas como "fatias de mídia" com o tempo do trecho. Ao trocar, cada
trecho atual pega a fatia guardada que mais se sobrepõe a ele — dividir ou
juntar trechos numa timeline não bagunça as outras.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

TIMELINES = ("1", "2", "3")
NOMES = {"1": "Timeline 1", "2": "Timeline 2", "3": "Juntar"}
CAMPOS_MIDIA = ("override_source", "media_type", "youtube_link", "provider", "clipes_extra", "curto")  # o banco também: a 2ª opção pode ter vindo de outro


def estado(job: dict) -> dict:
    st = job.get("timelines")
    if not isinstance(st, dict):
        st = job["timelines"] = {}
    st.setdefault("ativa", "1")
    st.setdefault("midias", {})
    st.setdefault("mix", [])
    return st


def tem_2(job: dict) -> bool:
    st = estado(job)
    return "2" in st["midias"] or st["ativa"] == "2"


# ------------------------------------------------------------------ fatias
def fatia(seg: dict, preview: Optional[dict]) -> dict:
    f = {"start": float(seg.get("start", 0)), "end": float(seg.get("end", 0))}
    for k in CAMPOS_MIDIA:
        f[k] = copy.deepcopy(seg.get(k))
    f["preview"] = copy.deepcopy(preview) if isinstance(preview, dict) else None
    return f


def capturar(job: dict) -> List[dict]:
    previews = job.get("segment_previews") or []
    return [fatia(s, previews[i] if i < len(previews) else None) for i, s in enumerate(job.get("pending_segments") or [])]


def melhor(fatias: List[dict], start: float, end: float) -> Optional[dict]:
    """A fatia que mais se sobrepõe a [start, end] (empate: a de centro mais perto)."""
    if not fatias:
        return None
    centro = (start + end) / 2

    def nota(f):
        sob = min(end, f["end"]) - max(start, f["start"])
        return (sob, -abs((f["start"] + f["end"]) / 2 - centro))
    f = max(fatias, key=nota)
    return f


def aplicar_um(job: dict, i: int, f: Optional[dict]) -> None:
    if f is None:
        return
    seg = job["pending_segments"][i]
    for k in CAMPOS_MIDIA:
        v = copy.deepcopy(f.get(k))
        if k == "provider" and not v:
            continue  # fatia antiga (sem o banco): fica o atual
        if v is None and k != "override_source":
            seg.pop(k, None)
            if k == "media_type":
                seg["media_type"] = "video"
        else:
            seg[k] = v
    previews = list(job.get("segment_previews") or [])
    while len(previews) < len(job["pending_segments"]):
        previews.append(None)
    p = f.get("preview")
    previews[i] = dict(p, index=i) if isinstance(p, dict) else None
    job["segment_previews"] = previews


def aplicar(job: dict, fatias: List[dict]) -> None:
    for i, s in enumerate(job.get("pending_segments") or []):
        aplicar_um(job, i, melhor(fatias, float(s["start"]), float(s["end"])))


def assinatura(f: Optional[dict]) -> tuple:
    if not f:
        return ()
    ov = f.get("override_source") or {}
    p = f.get("preview") or {}
    return (ov.get("source"), ov.get("value"), ov.get("provider"), f.get("media_type") or "video",
            None if ov else p.get("result_url"), None if ov else (p.get("thumbnail_path") or p.get("thumbnail_url")))


def urls(fatias: List[dict]) -> set:
    """Endereços de resultado (página do post / link) usados nessas fatias."""
    out = set()
    for f in fatias or []:
        ov = f.get("override_source") or {}
        if ov.get("source") in ("provider_url", "url") and ov.get("value"):
            out.add(ov["value"])
        p = f.get("preview") or {}
        if p.get("result_url"):
            out.add(p["result_url"])
    return out


# ------------------------------------------------------------------ mix (timeline 3)
def _escolhas_alinhadas(job: dict) -> List[dict]:
    st = estado(job)
    mix = st.get("mix") or []
    out = []
    for s in job.get("pending_segments") or []:
        m = melhor(mix, float(s["start"]), float(s["end"])) if mix else None
        e = {"start": float(s["start"]), "end": float(s["end"]), "de": (m or {}).get("de") or "1"}
        if e["de"] == "proprio":
            e["fatia"] = copy.deepcopy((m or {}).get("fatia"))
            if not e["fatia"]:
                e["de"] = "1"
        out.append(e)
    return out


def _fonte_do_mix(job: dict, i: int, de: str, escolha: Optional[dict] = None) -> Optional[dict]:
    s = job["pending_segments"][i]
    if de == "proprio":
        return (escolha or {}).get("fatia")
    return melhor(estado(job)["midias"].get(de) or [], float(s["start"]), float(s["end"]))


def entrar_no_mix(job: dict) -> None:
    escolhas = _escolhas_alinhadas(job)
    for i, e in enumerate(escolhas):
        aplicar_um(job, i, _fonte_do_mix(job, i, e["de"], e))
    estado(job)["mix"] = escolhas


def sair_do_mix(job: dict) -> None:
    """Guarda as escolhas; trecho cuja mídia foi trocada à mão DENTRO do
    "Juntar" vira "próprio" (fica com a mídia escolhida lá)."""
    escolhas = _escolhas_alinhadas(job)
    atuais = capturar(job)
    for i, e in enumerate(escolhas):
        fonte = _fonte_do_mix(job, i, e["de"], e) if e["de"] != "proprio" else None
        if e["de"] != "proprio" and assinatura(fonte) == assinatura(atuais[i]):
            e.pop("fatia", None)
            continue
        if e["de"] == "proprio" or fonte is not None:
            e["de"] = "proprio"
            e["fatia"] = atuais[i]
    estado(job)["mix"] = escolhas


def escolher(job: dict, indices: List[int], de: str) -> None:
    """No "Juntar": o(s) trecho(s) passam a usar a mídia da timeline `de`."""
    if de not in ("1", "2"):
        raise ValueError("Escolha a timeline 1 ou 2.")
    st = estado(job)
    if st["ativa"] != "3":
        raise ValueError("Isso só vale na timeline Juntar.")
    escolhas = _escolhas_alinhadas(job)
    for i in indices:
        if 0 <= i < len(escolhas):
            escolhas[i] = {"start": escolhas[i]["start"], "end": escolhas[i]["end"], "de": de}
            aplicar_um(job, i, _fonte_do_mix(job, i, de))
    st["mix"] = escolhas


def escolhas(job: dict) -> List[str]:
    """De onde vem cada trecho atual no Juntar ("1", "2" ou "proprio")."""
    return [e["de"] for e in _escolhas_alinhadas(job)]


# ------------------------------------------------------------------ trocar
def trocar(job: dict, para: str) -> None:
    if para not in TIMELINES:
        raise ValueError("Timeline desconhecida.")
    st = estado(job)
    atual = st["ativa"]
    if para == atual:
        return
    if para in ("2", "3") and "2" not in st["midias"] and atual != "2":
        raise LookupError("A timeline 2 ainda não foi gerada.")
    if atual == "3":
        sair_do_mix(job)
    else:
        st["midias"][atual] = capturar(job)
    if para == "3":
        st["ativa"] = "3"
        entrar_no_mix(job)
        return
    aplicar(job, st["midias"].get(para) or [])
    st["ativa"] = para


def fatias_da(job: dict, tl: str) -> List[dict]:
    """As fatias de uma timeline (a ativa é lida ao vivo)."""
    st = estado(job)
    if st["ativa"] == tl:
        return capturar(job)
    return st["midias"].get(tl) or []


def guardar_gerada(job: dict, tl: str, fatias: List[dict]) -> None:
    """Resultado da geração da timeline 2: se ela estiver aberta, já aparece."""
    st = estado(job)
    st["midias"][tl] = fatias
    if st["ativa"] == tl:
        aplicar(job, fatias)
