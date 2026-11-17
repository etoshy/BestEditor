"""
📥 v84_409 — FILA da aba 🎬 Google Flow: põe vários pedidos (🧩 Montar cena, ✏️ rascunho pelo Flow…) e eles rodam um
atrás do outro, sozinhos, com o mesmo ritmo humano, rodízio e troca de conta do resto da aba — enquanto você faz outra coisa.
A fila fica salva (flow_dados/fila_aba.json): reiniciou o site, o que estava esperando continua; o que estava rodando volta
pra fila.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from typing import Any, Callable, Dict, List, Optional

_TRAVA = threading.Lock()
_TRABALHADOR: Dict[str, Any] = {"thread": None, "parar_item": None}
MAX_ITENS = 200


def _gf():
    from googleflow import googleflow_client as gf
    return gf


def arquivo() -> str:
    return os.path.join(str(_gf().pasta_dados()), "fila_aba.json")


def _ler() -> List[Dict[str, Any]]:
    try:
        with open(arquivo(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _gravar(itens: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(arquivo()), exist_ok=True)
    tmp = arquivo() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(itens[-MAX_ITENS:], f, ensure_ascii=False)
    os.replace(tmp, arquivo())


def listar() -> List[Dict[str, Any]]:
    return _ler()


def adicionar(rotulo: str, pedido: Dict[str, Any], escolher: bool = False, refs_juiz: Optional[List[Any]] = None,
              iniciar: bool = True, rodar: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    it = {"id": time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3), "rotulo": str(rotulo)[:160], "pedido": pedido,
          "escolher": bool(escolher), "refs_juiz": refs_juiz or [], "estado": "esperando", "resultados": [], "melhor": None,
          "notas": [], "erro": "", "criado": time.time(), "fim": None, "msg": ""}
    with _TRAVA:
        itens = _ler()
        itens.append(it)
        _gravar(itens)
    if iniciar:
        garantir_trabalhador(rodar)
    return it


def _mudar(iid: str, **k: Any) -> None:
    with _TRAVA:
        itens = _ler()
        for x in itens:
            if x["id"] == iid:
                x.update(k)
        _gravar(itens)


def tirar(iid: str) -> bool:
    """Tira da fila (se estiver rodando, pede pra parar)."""
    with _TRAVA:
        itens = _ler()
        alvo = next((x for x in itens if x["id"] == iid), None)
        if not alvo:
            return False
        if alvo["estado"] == "rodando":
            _TRABALHADOR["parar_item"] = iid
            alvo["estado"] = "cancelado"
        else:
            itens = [x for x in itens if x["id"] != iid]
        _gravar(itens)
    return True


def limpar_prontos() -> None:
    with _TRAVA:
        _gravar([x for x in _ler() if x["estado"] in ("esperando", "rodando")])


def proximo() -> Optional[Dict[str, Any]]:
    with _TRAVA:
        itens = _ler()
        for x in itens:
            if x["estado"] == "rodando":  # o site reiniciou no meio: volta pra fila
                x["estado"] = "esperando"
        it = next((x for x in itens if x["estado"] == "esperando"), None)
        if it:
            it["estado"], it["inicio"] = "rodando", time.time()
        _gravar(itens)
        return it


def processar_um(it: Dict[str, Any], rodar: Callable[..., List[Dict[str, Any]]],
                 julgar: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
    parar = lambda: _TRABALHADOR.get("parar_item") == it["id"]  # noqa: E731
    try:
        res = rodar(it["pedido"], parar=parar)
        arqs = [r.get("arquivo") for r in res if r.get("arquivo")]
        melhor, notas, resumo = None, [], ""
        imgs = [r for r in res if r.get("tipo") == "imagem"]
        if it.get("escolher") and len(imgs) > 1:
            if julgar is None:
                import flow_estudio as FE
                julgar = lambda prompt, refs, _res: FE.julgar_resultados(prompt, refs, _res)  # noqa: E731
            j = julgar(it["pedido"].get("prompt") or "", [tuple(x) for x in it.get("refs_juiz") or []], imgs)
            melhor, notas, resumo = imgs[j["melhor"]].get("arquivo"), j["notas"], j.get("resumo") or ""
        _mudar(it["id"], estado="cancelado" if parar() else "pronto", resultados=arqs, melhor=melhor, notas=notas,
               msg=resumo, fim=time.time())
    except Exception as exc:  # noqa: BLE001
        _mudar(it["id"], estado="cancelado" if parar() else "erro", erro=str(exc)[:400], fim=time.time())
    finally:
        if _TRABALHADOR.get("parar_item") == it["id"]:
            _TRABALHADOR["parar_item"] = None


def garantir_trabalhador(rodar: Optional[Callable[..., Any]] = None) -> None:
    """Um trabalhador só: pega o próximo da fila até acabar."""
    with _TRAVA:
        t = _TRABALHADOR.get("thread")
        if t is not None and t.is_alive():
            return

        def corpo():
            if rodar is None:
                import flow_estudio as FE
                r_ = lambda pedido, parar=None: FE.rodar_e_esperar(pedido, esperar_livre_s=3600, parar=parar)  # noqa: E731
            else:
                r_ = rodar
            while True:
                it = proximo()
                if not it:
                    return
                processar_um(it, r_)
        t = threading.Thread(target=corpo, name="flow-fila", daemon=True)
        _TRABALHADOR["thread"] = t
        t.start()


def resumo() -> Dict[str, Any]:
    itens = _ler()
    return {"itens": itens[::-1][:60], "esperando": sum(1 for x in itens if x["estado"] == "esperando"),
            "rodando": next((x["rotulo"] for x in itens if x["estado"] == "rodando"), "")}
