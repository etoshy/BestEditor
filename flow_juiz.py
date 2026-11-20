"""
🎯 v84_409 — o JUIZ das imagens do Flow: o Flow gera 2 (ou mais) variações e a IA escolhe a mais fiel ao pedido —
a base/pose (enquadramento, pose, expressão), a pessoa certa no lugar certo, o estilo. Também diz se a melhor está BOA o
bastante pra seguir (no 🎬 Refazer cena, um quadro ruim não vai pro Veo: refaz com o motivo no comando).
Sem a IA: fica a primeira, e passa.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

NOTA_MINIMA = 60

SISTEMA = """You judge image-generation results. You get the REQUEST (the prompt, and what each reference image was for), the
REFERENCE images (the base/pose and the new characters) and the CANDIDATES. Score each candidate 0–100 for how faithfully it
does what was asked: same framing/pose/expression as the base or pose image, each new character recognizable and in the
right place (and NOT pasted with the pose/props of its own reference photo), each REPLACED figure wearing the NEW
character's own look and an outfit that fits that character (its reference clothes, or clothes designed in its own colors
and style) — a candidate where only the face/hair changed and the ORIGINAL figure's clothes stayed (unless that figure was
marked "face/head only") is a big failure (score it 40 or less), the requested style, no extra or missing people,
no broken anatomy, no text artifacts. Pick the best. "problemas": short, concrete, in English (they go into a retry prompt as
"Fix: …"), empty if none. "resumo": one short sentence in Brazilian Portuguese."""
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["candidatos", "melhor", "resumo"], "properties": {
    "candidatos": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                              "required": ["n", "nota", "problemas"],
                                              "properties": {"n": {"type": "integer"}, "nota": {"type": "integer"},
                                                             "problemas": {"type": "string"}}}},
    "melhor": {"type": "integer"}, "resumo": {"type": "string"}}}


def julgar(prompt: str, referencias: List[Tuple[str, str]], candidatos: List[str],
           chamar: Optional[Callable[..., Any]] = None,
           bloco_imagem: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    """referencias = [(rótulo, arquivo)] · candidatos = [arquivo] → {melhor (índice), notas [..], problemas [..], ok, resumo,
    com_ia}."""
    sem = {"melhor": 0, "notas": [None] * len(candidatos), "problemas": [""] * len(candidatos), "ok": True,
           "resumo": "", "com_ia": False}
    if not candidatos:
        return dict(sem, ok=False)
    if chamar is None or bloco_imagem is None:
        try:
            import ia_servico
        except Exception:  # noqa: BLE001
            return sem
        chamar = chamar or ia_servico.chamar
        bloco_imagem = bloco_imagem or (lambda f: ia_servico.imagem_bloco(f, 640))
    c: List[Dict[str, Any]] = [{"type": "text", "text": "REQUEST: " + (prompt or "")[:3000]}]
    for rot, arq in referencias:
        b = bloco_imagem(arq)
        if b:
            c += [{"type": "text", "text": "REFERENCE — " + rot}, b]
    vistos = 0
    for k, arq in enumerate(candidatos, 1):
        b = bloco_imagem(arq)
        if b:
            c += [{"type": "text", "text": f"CANDIDATE {k}"}, b]
            vistos += 1
    if not vistos:
        return sem
    try:
        r = chamar("flow_juiz", SISTEMA, c, schema=SCHEMA, max_tokens=900, effort="low", timeout=120)
    except Exception:  # noqa: BLE001
        r = None
    if not isinstance(r, dict):
        return sem
    notas: List[Optional[int]] = [None] * len(candidatos)
    probs = [""] * len(candidatos)
    for x in r.get("candidatos") or []:
        try:
            i = int(x.get("n")) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(candidatos):
            notas[i] = max(0, min(100, int(x.get("nota") or 0)))
            probs[i] = " ".join(str(x.get("problemas") or "").split())[:400]
    try:
        melhor = int(r.get("melhor") or 1) - 1
    except (TypeError, ValueError):
        melhor = 0
    if not (0 <= melhor < len(candidatos)) or notas[melhor] is None:
        validos = [i for i, n in enumerate(notas) if n is not None]
        melhor = max(validos, key=lambda i: notas[i]) if validos else 0
    nota = notas[melhor]
    return {"melhor": melhor, "notas": notas, "problemas": probs, "ok": nota is None or nota >= NOTA_MINIMA,
            "resumo": " ".join(str(r.get("resumo") or "").split())[:300], "com_ia": True}


def refs_do_pacote(pac: Dict[str, Any]) -> List[Tuple[str, str]]:
    """As referências de uma 🧩 montagem com o papel de cada uma (pro juiz)."""
    out = []
    for r in pac.get("refs") or []:
        rot = {"base": "BASE (composition, poses, expressions to keep)", "pose": "POSE (pose/framing only)",
               "personagem": f"NEW CHARACTER “{r.get('nome') or ''}” (" + {"rosto": "face/head only", "inteira": "whole figure"}.get(
                   r.get("troca") or "", "automatic") + ")"}.get(r["papel"], r["papel"].upper())
        out.append((f"image {r['n']} — {rot}", r["arquivo"]))
    return out
