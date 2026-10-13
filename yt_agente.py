"""
yt_agente.py
============

🤖 A IA ACHA O VÍDEO DO YOUTUBE (v84_69) — o que antes era a parte mais braçal do editor.

Para cada trecho/corte que pede um vídeo do YouTube:

  1. busca no YouTube (20 resultados: capa, título, canal, duração);
  2. a IA dá nota olhando as CAPAS, títulos e durações e escolhe os mais prováveis;
  3. o site pega a legenda/transcrição de cada um desses (na ordem da nota);
  4. a IA lê a transcrição e tenta achar o MOMENTO exato que a narração pede;
  5. não achou em nenhum → a IA sugere outra busca e repete (no máximo 3 buscas);
  6. ainda nada → avisa que não conseguiu, deixa os resultados da última busca pra você escolher à mão
     e vai pro próximo.

As funções de busca/legenda/IA entram como parâmetros (os testes trocam por falsas).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

MAX_BUSCAS = 3
VIDEOS_POR_BUSCA = 3
NOTA_MINIMA = 5
CONFIANCA_MINIMA = 0.45


def procurar(fala: str, termo: str, duracao_alvo: Optional[float], *,
             buscar: Callable[[str], List[Dict[str, Any]]],
             ordenar: Callable[[List[Dict[str, Any]], str, List[str]], Optional[Dict[str, Any]]],
             legenda: Callable[[str], Dict[str, Any]],
             achar: Callable[[List[Dict[str, Any]], Dict[str, Any]], Optional[Dict[str, Any]]],
             nova_busca: Callable[[List[str], List[str]], str],
             assistir: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None,
             assistir_sempre: bool = False,
             log: Callable[[str], None] = lambda _m: None,
             parar: Callable[[], bool] = lambda: False,
             max_buscas: int = MAX_BUSCAS, videos_por_busca: int = VIDEOS_POR_BUSCA) -> Dict[str, Any]:
    """`assistir(video)` (opcional, 🔎 IA do Google): "assiste" o vídeo e devolve o momento (mesmo formato do `achar`).
    Usada quando o vídeo não tem legenda ou a leitura da legenda não achou — ou ANTES da legenda, com `assistir_sempre`.
    → {"achou": True, "video", "inicio", "fim", "frase", "confianca", "busca", "buscas", "conferidos"}
       ou {"achou": False, "motivo", "buscas", "conferidos", "resultados" (os da última busca)}."""
    feitas: List[str] = []
    motivos: List[str] = []
    vistos: Dict[str, str] = {}   # url → título (já conferidos)
    ultimos: List[Dict[str, Any]] = []
    termo_ultimos = ""
    termo = (termo or "").strip()
    while termo and len(feitas) < max_buscas and not parar():
        feitas.append(termo)
        log(f"🔍 Busca {len(feitas)}/{max_buscas}: “{termo}”")
        try:
            resultados = buscar(termo) or []
        except Exception as exc:  # noqa: BLE001
            resultados = []
            motivos.append(f"a busca “{termo}” falhou ({str(exc)[:80]})")
        if resultados:
            o = None
            try:
                o = ordenar(resultados, termo, list(vistos.values()))
            except Exception:  # noqa: BLE001
                o = None
            ranqueados = (o or {}).get("resultados") or resultados
            ultimos, termo_ultimos = ranqueados, termo
            cands = [v for v in ranqueados if v.get("url") and v["url"] not in vistos
                     and (v.get("ia_nota") is None or v["ia_nota"] >= NOTA_MINIMA)][:videos_por_busca]
            if not cands:
                motivos.append(f"“{termo}”: nenhum vídeo promissor")
                log("   nenhum vídeo promissor nessa busca")
            for v in cands:
                if parar():
                    break
                vistos[v["url"]] = str(v.get("titulo") or v["url"])[:80]
                nota = f" (nota {v['ia_nota']})" if v.get("ia_nota") is not None else ""

                def _google() -> Optional[Dict[str, Any]]:
                    if assistir is None:
                        return None
                    log(f"   🔎 a IA do Google está assistindo “{str(v.get('titulo') or '')[:60]}”…")
                    try:
                        return assistir(v)
                    except Exception as exc:  # noqa: BLE001
                        log(f"      IA do Google: {str(exc)[:120]}")
                        return None
                m = _google() if assistir_sempre else None
                if not (m and m.get("achou")):
                    log(f"   📄 lendo a transcrição de “{str(v.get('titulo') or '')[:70]}”{nota}")
                    try:
                        leg = legenda(v["url"]) or {}
                    except Exception as exc:  # noqa: BLE001
                        leg = {"linhas": [], "erro": str(exc)[:80]}
                    m = None
                    if leg.get("linhas"):
                        try:
                            m = achar(leg["linhas"], v)
                        except Exception:  # noqa: BLE001
                            m = None
                    if not (m and m.get("achou")) and assistir is not None and not assistir_sempre:
                        if not leg.get("linhas"):
                            log("      sem legenda")
                        m = _google()  # sem legenda, ou a legenda não achou: o Google assiste o vídeo
                    elif not leg.get("linhas"):
                        motivos.append(f"“{str(v.get('titulo') or '')[:50]}”: sem legenda")
                        log("      sem legenda — próximo")
                        continue
                if m and m.get("achou") and float(m.get("confianca") or 0) >= CONFIANCA_MINIMA and m["fim"] > m["inicio"]:
                    log(f"   🎯 achei{' (IA do Google)' if m.get('fonte') == 'google' else ''}: {m['inicio']:.1f}s → {m['fim']:.1f}s “{str(m.get('frase') or '')[:80]}”")
                    return {"achou": True, "video": v, "inicio": m["inicio"], "fim": m["fim"], "frase": m.get("frase") or "",
                            "traducao": m.get("traducao") or "", "confianca": float(m.get("confianca") or 0),
                            "busca": termo, "buscas": feitas, "conferidos": list(vistos.values()), "fonte": m.get("fonte") or "legenda"}
                motivos.append(f"“{str(v.get('titulo') or '')[:50]}”: não fala disso")
                log("      não fala disso — próximo")
            sugerida = str((o or {}).get("busca_melhor") or "").strip()
        else:
            sugerida = ""
            if not motivos or not motivos[-1].startswith("a busca"):
                motivos.append(f"“{termo}”: nenhum resultado")
        if len(feitas) >= max_buscas or parar():
            break
        prox = sugerida if sugerida and sugerida.lower() not in {f.lower() for f in feitas} else ""
        if not prox:
            try:
                prox = (nova_busca(feitas, motivos) or "").strip()
            except Exception:  # noqa: BLE001
                prox = ""
        termo = prox if prox.lower() not in {f.lower() for f in feitas} else ""
    motivo = ("parado por você" if parar() else
              f"não achei o momento em {len(feitas)} busca(s) e {len(vistos)} vídeo(s) — escolha à mão")
    log("❌ " + motivo)
    return {"achou": False, "motivo": motivo, "buscas": feitas, "conferidos": list(vistos.values()),
            "motivos": motivos[-10:], "resultados": ultimos, "termo_resultados": termo_ultimos}
