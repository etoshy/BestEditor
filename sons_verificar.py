"""🔊 v84_362: verificador dos efeitos sonoros dos curtos — tira o que é ruim ou desconexo do conteúdo.

Trabalha na FAIXA DE SONS de verdade do projeto do editor (os eventos que vão pro vídeo), em duas camadas:

1. Regras (sem IA, sempre):
   • som comprido demais pro tipo (um "whoosh" de 6 s, uma música inteira) → troca por um da base do site;
   • som do Pixabay que veio da busca de OUTRA deixa (um "torcida" que caiu num "whoosh") → troca pelo da base;
   • sons colados (menos de 1,2 s um do outro) → fica o mais importante;
   • sons demais (mais de 1 a cada 5 s) → saem primeiro os automáticos das trocas de bloco;
   • som alto demais → abaixa.
2. IA (se ligada): lê cada som com a FRASE que está sendo dita naquele instante e decide manter / tirar / trocar de tipo —
   som que não tem nada a ver com o que acontece sai.

Os sons que VOCÊ pôs no editor (origem diferente de "ia") nunca são mexidos.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import curtos as CT

DUR_MAX = {"whoosh": 2.5, "swipe": 2.5, "pop": 1.5, "clique": 1.5, "ding": 2.5, "camera": 2.0, "glitch": 2.5,
           "impacto": 3.0, "boom": 4.0, "riser": 6.0, "cinema": 4.0, "vento": 5.0, "respiro": 4.0, "digitacao": 4.0}
GAP_MIN_S = 1.2
POR_SEG_MAX = 1 / 5.0  # no máximo 1 som a cada 5 s
NIVEL_ALTO_DB = -6.0


def _tipo(ev: Dict[str, Any]) -> str:
    c = str(ev.get("curto") or "")
    t = c.split(":", 1)[1] if ":" in c else ""
    if t == "corte":
        return "whoosh"
    return t if t in CT.TIPOS_SFX else ""


def _prio(ev: Dict[str, Any]) -> int:
    """Quem fica quando 2 brigam: o que acontece no clipe > a deixa do roteiro > o automático da troca de bloco."""
    c = str(ev.get("curto") or "")
    return 0 if c.startswith("evento:") else 2 if c.endswith(":corte") else 1


def _pico(ev: Dict[str, Any]) -> float:
    import dp_sons
    s = dp_sons.som(ev.get("som")) or {}
    return float(ev.get("start") or 0) + float(s.get("pico") or 0)


def _dur_som(sid: str) -> float:
    import dp_sons
    s = dp_sons.som(sid) or {}
    a, b = s.get("inicio_som"), s.get("fim_som")
    if a is not None and b is not None and float(b) > float(a):
        return float(b) - float(a)
    return float(s.get("dur") or 0)


def _base_do_tipo(tipo: str, semente: str, evitar: Optional[str] = None) -> Optional[str]:
    """Um som da base do SITE (os curados, não os do Pixabay) pro tipo."""
    import zlib
    cands = [s for s in CT.sons_do_tipo(tipo) if not s["id"].startswith("pixabay/")] or CT.sons_do_tipo(tipo)
    cands = [s for s in cands if _dur_som(s["id"]) <= DUR_MAX.get(tipo, 3.0) + 0.5] or cands
    if not cands:
        return None
    k = zlib.crc32(semente.encode("utf-8")) % len(cands)
    if len(cands) > 1 and cands[k]["id"] == evitar:
        k = (k + 1) % len(cands)
    return cands[k]["id"]


def _pixabay_de_outra_deixa(sid: str, p: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    """O som do Pixabay só vale na deixa pra qual foi buscado (a deixa tem 'som' = ele)."""
    if not str(sid).startswith("pixabay/"):
        return False
    c = str(ev.get("curto") or "")
    bid = c.split(":", 1)[0]
    for b in (p.get("roteiro") or {}).get("blocos") or []:
        if b.get("id") == bid and any(s.get("som") == sid for s in b.get("sfx") or []):
            return False
    return True


def _frase_em(p: Dict[str, Any], t: float) -> str:
    g = p.get("gravacao") or {}
    blocos = (p.get("roteiro") or {}).get("blocos") or []
    al = g.get("alinhamento") or []
    for k, b in enumerate(blocos):
        if k < len(al) and float(al[k].get("start", 0)) - 0.3 <= t <= float(al[k].get("end", 0)) + 0.3:
            return CT.sem_tags(b.get("fala") or "")[:300]
    return ""


def _palavras_em(p: Dict[str, Any], t: float, janela: float = 1.2) -> str:
    ws = (p.get("gravacao") or {}).get("palavras") or []
    return " ".join(str(w.get("word") or w.get("palavra") or "").strip() for w in ws
                    if abs(float(w.get("start", 0)) - t) <= janela)[:160]


def regras(eventos: List[Dict[str, Any]], p: Dict[str, Any], dur: float = 0.0) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Aplica as regras. Devolve (eventos novos, relatório [{t, som, tipo, acao, motivo}])."""
    import dp_sons
    meus = [e for e in eventos if e.get("origem") != "ia"]
    ia = [dict(e) for e in eventos if e.get("origem") == "ia" and e.get("som")]
    rel: List[Dict[str, Any]] = []
    for k, e in enumerate(ia):
        tipo = _tipo(e) or "whoosh"
        t = _pico(e)
        motivo = ""
        if not dp_sons.som(e["som"]):
            motivo = "o som não existe mais na base"
        elif _dur_som(e["som"]) > DUR_MAX.get(tipo, 3.0):
            motivo = f"comprido demais pra um {tipo} ({_dur_som(e['som']):.1f} s)"
        elif _pixabay_de_outra_deixa(e["som"], p, e):
            motivo = "som do Pixabay buscado pra outra coisa"
        if motivo:
            novo = _base_do_tipo(tipo, f"{p.get('id')}|{k}|{t:.2f}", e["som"])
            ev = dp_sons.evento(novo, t, float(e.get("volume") or 0.8)) if novo else None
            rel.append({"t": round(t, 2), "som": e["som"], "tipo": tipo, "acao": "trocar" if ev else "tirar", "motivo": motivo,
                        "novo": novo or ""})
            if ev:
                e.update(som=novo, start=ev["inicio"])
            else:
                e["_tirar"] = True
        s = dp_sons.som(e.get("som")) or {}
        if not e.get("_tirar") and s.get("nivel_db") is not None and float(s["nivel_db"]) > NIVEL_ALTO_DB and float(e.get("volume") or 1) > 0.6:
            e["volume"] = 0.55
            rel.append({"t": round(t, 2), "som": e["som"], "tipo": tipo, "acao": "abaixar", "motivo": f"alto demais ({s['nivel_db']} dB)"})
    ia = [e for e in ia if not e.get("_tirar")]
    # colados / demais: fica o mais importante, depois o que vem antes
    dur = dur or float((p.get("gravacao") or {}).get("dur") or 0) or max([_pico(e) for e in ia] + [10.0])
    limite = max(2, int(dur * POR_SEG_MAX) + 1)
    fica: List[Dict[str, Any]] = []
    for e in sorted(ia, key=lambda e: (_prio(e), _pico(e))):
        t = _pico(e)
        perto = next((f for f in fica if abs(_pico(f) - t) < GAP_MIN_S), None)
        if perto:
            rel.append({"t": round(t, 2), "som": e["som"], "tipo": _tipo(e), "acao": "tirar", "motivo": f"colado em outro som ({abs(_pico(perto) - t):.1f} s)"})
        elif len(fica) >= limite:
            rel.append({"t": round(t, 2), "som": e["som"], "tipo": _tipo(e), "acao": "tirar", "motivo": f"sons demais (máx. {limite} em {dur:.0f} s)"})
        else:
            fica.append(e)
    return sorted(meus + fica, key=lambda e: float(e.get("start") or 0)), rel


SCHEMA_IA = {"type": "object", "properties": {"sons": {"type": "array", "items": {"type": "object", "properties": {
    "i": {"type": "integer"}, "acao": {"type": "string", "enum": ["manter", "tirar", "trocar"]},
    "tipo_novo": {"type": "string", "enum": list(CT.TIPOS_SFX) + [""]}, "motivo": {"type": "string"}},
    "required": ["i", "acao", "tipo_novo", "motivo"]}}}, "required": ["sons"]}


def pedir_ia(eventos: List[Dict[str, Any]], p: Dict[str, Any], chamar: Optional[Callable[..., Any]] = None) -> List[Dict[str, Any]]:
    import dp_sons
    ia = [e for e in eventos if e.get("origem") == "ia"]
    if not ia:
        return []
    linhas = []
    for k, e in enumerate(ia):
        s = dp_sons.som(e["som"]) or {}
        t = _pico(e)
        linhas.append(f"{k}. at {t:.1f}s — {_tipo(e) or 'sound'} — sound file: \"{s.get('nome') or e['som']}\" "
                      f"({', '.join(s.get('tags') or [])[:80]}) — said right then: \"{_palavras_em(p, t)}\" — sentence: \"{_frase_em(p, t)}\"")
    txt = ("You are the sound editor of a short video. For EACH sound effect below decide: keep it, remove it, or change its type.\n"
           "REMOVE when: it has nothing to do with what is said/shown at that moment, it would sound weird, comic or annoying, "
           "it repeats a pattern for no reason, or the moment is calm/emotional and a sound would break it. A short video needs only "
           "a FEW sounds, on real moments (a reveal, an impact, a fast cut, something appearing). When in doubt, remove.\n"
           "CHANGE ('trocar' + tipo_novo) when a sound fits the moment but the type is wrong.\n"
           f"Types: {', '.join(f'{k} = {v['nome']}' for k, v in CT.TIPOS_SFX.items())}.\n"
           "'motivo' in Brazilian Portuguese, short.\n\nSOUNDS:\n" + "\n".join(linhas))
    import ia_servico
    r = (chamar or ia_servico.chamar)("curtos", "You are a careful, minimalist sound editor for short-form video.", txt,
                                      schema=SCHEMA_IA, max_tokens=2500, job=p.get("id"), cache_local=False)
    return list((r or {}).get("sons") or [])


def aplicar_ia(eventos: List[Dict[str, Any]], p: Dict[str, Any], decisoes: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    import dp_sons
    meus = [e for e in eventos if e.get("origem") != "ia"]
    ia = [dict(e) for e in eventos if e.get("origem") == "ia"]
    rel = []
    por_i = {int(d.get("i", -1)): d for d in decisoes}
    fica = []
    for k, e in enumerate(ia):
        d = por_i.get(k) or {}
        t = _pico(e)
        if d.get("acao") == "tirar":
            rel.append({"t": round(t, 2), "som": e["som"], "tipo": _tipo(e), "acao": "tirar", "motivo": "IA: " + str(d.get("motivo") or "")[:160]})
            continue
        if d.get("acao") == "trocar" and d.get("tipo_novo") in CT.TIPOS_SFX and d["tipo_novo"] != _tipo(e):
            novo = _base_do_tipo(d["tipo_novo"], f"{p.get('id')}|ia|{k}", e["som"])
            ev = dp_sons.evento(novo, t, float(e.get("volume") or 0.8)) if novo else None
            if ev:
                rel.append({"t": round(t, 2), "som": e["som"], "tipo": _tipo(e), "acao": "trocar", "novo": novo,
                            "motivo": f"IA: vira {d['tipo_novo']} — " + str(d.get("motivo") or "")[:140]})
                e.update(som=novo, start=ev["inicio"], curto=str(e.get("curto") or "").split(":", 1)[0] + ":" + d["tipo_novo"])
        fica.append(e)
    return sorted(meus + fica, key=lambda e: float(e.get("start") or 0)), rel


def assinatura(eventos: List[Dict[str, Any]]) -> str:
    return hashlib.md5(json.dumps([(e.get("som"), e.get("start"), e.get("volume")) for e in eventos if e.get("origem") == "ia"],
                                  sort_keys=True).encode("utf-8")).hexdigest()[:12]


def verificar(eventos: List[Dict[str, Any]], p: Dict[str, Any], usar_ia: bool = True,
              chamar: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """Regras + IA. Devolve {eventos (corrigidos), relatorio, antes, depois, ia}."""
    novos, rel = regras(eventos, p)
    ia_ok = False
    if usar_ia:
        try:
            dec = pedir_ia(novos, p, chamar)
            if dec:
                novos, rel2 = aplicar_ia(novos, p, dec)
                rel += rel2
                ia_ok = True
        except Exception as exc:  # noqa: BLE001  (sem IA: ficam só as regras)
            rel.append({"t": 0, "som": "", "tipo": "", "acao": "aviso", "motivo": f"a IA não respondeu ({str(exc)[:80]}) — só as regras"})
    rel.sort(key=lambda r: r.get("t") or 0)
    conta = lambda es: len([e for e in es if e.get("origem") == "ia"])  # noqa: E731
    return {"eventos": novos, "relatorio": rel, "antes": conta(eventos), "depois": conta(novos), "ia": ia_ok,
            "assinatura": assinatura(novos)}
