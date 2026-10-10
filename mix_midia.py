"""
Proporção FOTOS × VÍDEOS escolhida na hora de escolher os bancos (opcional).

  - por provedor (só os que trazem os dois tipos: hoje "pexels" e "flow" —
    no Flow, vídeo = gerado com IA, bem mais lento que imagem);
  - no vídeo inteiro ("global"), valendo pros demais bancos: um banco só de
    vídeo (pixabay, mixkit...) pode virar FOTO do pexels (mesmo termo de
    busca) quando o pexels estiver marcado.

O valor guardado é sempre a % de FOTOS (0–100); o resto é vídeo. A regra entra
no prompt da IA e, depois que a resposta chega, `aplicar()` ajusta os
`media_type` que fugirem da proporção (a IA costuma ignorar números).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# bancos que trazem foto E vídeo (o resto é só um dos dois)
PROVEDORES_MISTOS = ("pexels", "flow")
SO_FOTO = ("wikipedia", "bing", "brave", "yandex", "startpage")
SO_VIDEO = ("pixabay", "magnific", "mixkit", "vistacreate", "animepexels", "moviepexels", "animepexels_online", "moviepexels_online", "youtube")
# bancos de estoque só-vídeo cujos termos (inglês, genéricos) servem igual pra
# buscar FOTO no pexels — os outros (youtube, animepexels) têm termos próprios.
_ESTOQUE_TROCAVEL = ("pixabay", "magnific", "mixkit", "vistacreate")
PRESETS = (100, 90, 75, 50, 25, 10, 0)


def _pct(v: Any) -> Optional[int]:
    if v is None or str(v).strip() == "":
        return None
    try:
        return max(0, min(100, int(round(float(str(v).replace("%", "").replace(",", "."))))))
    except (TypeError, ValueError):
        return None


def do_form(form, sufixo: str = "") -> Dict[str, Any]:
    """Lê os campos `mix_global{sufixo}` e `mix_<provedor>{sufixo}` (% de fotos;
    vazio = a IA decide). Devolve {} quando nada foi escolhido."""
    out: Dict[str, Any] = {}
    if form.get("mix_ativo" + sufixo) != "on":  # caixa "definir proporção" desmarcada = a IA decide
        return out
    g = _pct(form.get("mix_global" + sufixo))
    if g is not None:
        out["global"] = g
    prov = {p: _pct(form.get(f"mix_{p}{sufixo}")) for p in PROVEDORES_MISTOS}
    prov = {p: v for p, v in prov.items() if v is not None}
    if prov:
        out["provedores"] = prov
    return out


def normalizar(mix: Any) -> Dict[str, Any]:
    if not isinstance(mix, dict):
        return {}
    out: Dict[str, Any] = {}
    g = _pct(mix.get("global"))
    if g is not None:
        out["global"] = g
    prov = {p: _pct(v) for p, v in (mix.get("provedores") or {}).items() if p in PROVEDORES_MISTOS}
    prov = {p: v for p, v in prov.items() if v is not None}
    if prov:
        out["provedores"] = prov
    return out


def resumo(mix: Dict[str, Any]) -> str:
    mix = normalizar(mix)
    partes = []
    if "global" in mix:
        partes.append(f"vídeo todo: {mix['global']}% fotos / {100 - mix['global']}% vídeos")
    for p, v in (mix.get("provedores") or {}).items():
        partes.append(f"{p}: {v}% fotos / {100 - v}% vídeos")
    return "; ".join(partes)


def regra_prompt(mix: Dict[str, Any], providers: List[str]) -> str:
    """Texto da regra pro prompt da IA ('' se não houver escolha)."""
    mix = normalizar(mix)
    if not mix:
        return ""
    linhas = []
    if "global" in mix:
        g = mix["global"]
        foto_ok = [p for p in providers if p in PROVEDORES_MISTOS + SO_FOTO]
        linhas.append(
            f"no VÍDEO INTEIRO, cerca de {g}% dos segmentos devem ser FOTO (`\"media_type\": \"image\"`) e {100 - g}% VÍDEO"
            + (f" — foto só nos bancos que têm foto ({', '.join(foto_ok)})" if foto_ok and g > 0 else "")
        )
    for p, v in (mix.get("provedores") or {}).items():
        if p not in providers:
            continue
        extra = " (no flow, vídeo é GERADO por IA — curto, ~8 s, e bem mais demorado que imagem)" if p == "flow" else ""
        linhas.append(f"entre os segmentos com `\"provider\": \"{p}\"`, cerca de {v}% FOTO e {100 - v}% VÍDEO{extra}")
    if not linhas:
        return ""
    return ("PROPORÇÃO FOTOS × VÍDEOS (escolha da pessoa — siga): " + "; ".join(linhas)
            + ". Escolha como VÍDEO os trechos em que o movimento faz mais diferença (ação, natureza em movimento, "
              "gente fazendo algo) e como FOTO os de conceito, retrato, objeto ou lugar. O site confere a proporção "
              "depois e ajusta o que passar muito longe.")


def _espalhados(cands: List[int], k: int) -> List[int]:
    """k índices de `cands` bem distribuídos ao longo da lista (não todos no começo)."""
    if k <= 0 or not cands:
        return []
    if k >= len(cands):
        return list(cands)
    passo = len(cands) / k
    return [cands[min(len(cands) - 1, int(passo * j + passo / 2))] for j in range(k)]


def _fixo(s: Dict[str, Any]) -> bool:
    """Trecho que a pessoa já fixou (arquivo/link/YouTube escolhido) não muda."""
    return bool(s.get("override_source") or (s.get("youtube_link") or {}).get("url"))


def aplicar(segs: List[Dict[str, Any]], mix: Dict[str, Any], providers: List[str]) -> Tuple[int, List[str]]:
    """Ajusta `media_type` (e, no global, troca banco só-vídeo de estoque por
    foto do pexels) pra chegar perto da proporção. Mexe nos dicts no lugar.
    Devolve (quantos trechos mudaram, avisos)."""
    mix = normalizar(mix)
    if not mix or not segs:
        return 0, []
    mudou, avisos = 0, []
    por_prov = mix.get("provedores") or {}

    def tipo(s):
        return "image" if s.get("media_type") == "image" else "video"

    for p, pct in por_prov.items():
        idx = [i for i, s in enumerate(segs) if s.get("provider") == p and not _fixo(s)]
        if not idx:
            continue
        alvo = round(pct * len(idx) / 100)
        fotos = [i for i in idx if tipo(segs[i]) == "image"]
        videos = [i for i in idx if tipo(segs[i]) == "video"]
        if len(fotos) < alvo:
            for i in _espalhados(videos, alvo - len(fotos)):
                segs[i]["media_type"] = "image"
                mudou += 1
        elif len(fotos) > alvo:
            for i in _espalhados(fotos, len(fotos) - alvo):
                segs[i]["media_type"] = "video"
                mudou += 1

    if "global" in mix:
        pct = mix["global"]
        alvo = round(pct * len(segs) / 100)
        fotos = sum(1 for s in segs if tipo(s) == "image")
        livres = [i for i, s in enumerate(segs) if not _fixo(s) and s.get("provider") not in por_prov]
        if fotos < alvo:
            viraveis = [i for i in livres if tipo(segs[i]) == "video" and segs[i].get("provider") in PROVEDORES_MISTOS]
            if "pexels" in providers:
                viraveis += [i for i in livres if segs[i].get("provider") in _ESTOQUE_TROCAVEL]
            viraveis.sort()
            for i in _espalhados(viraveis, alvo - fotos):
                if segs[i].get("provider") not in PROVEDORES_MISTOS:
                    segs[i]["provider"] = "pexels"
                segs[i]["media_type"] = "image"
                mudou += 1
                fotos += 1
            if fotos < alvo:
                avisos.append(f"Pedido de {pct}% de fotos: só deu {round(100 * fotos / len(segs))}% — os outros trechos estão em bancos "
                              "que só têm vídeo (marque o pexels ou o flow pra ter foto).")
        elif fotos > alvo:
            viraveis = [i for i in livres if tipo(segs[i]) == "image" and segs[i].get("provider") in PROVEDORES_MISTOS]
            for i in _espalhados(viraveis, fotos - alvo):
                segs[i]["media_type"] = "video"
                mudou += 1
                fotos -= 1
            if fotos > alvo:
                avisos.append(f"Pedido de {100 - pct}% de vídeos: só deu {round(100 * (len(segs) - fotos) / len(segs))}% — os outros "
                              "trechos são de bancos só de foto (Wikipedia/buscadores).")
    if mudou:
        avisos.insert(0, f"Proporção fotos × vídeos ({resumo(mix)}): ajustei {mudou} trecho(s).")
    return mudou, avisos
