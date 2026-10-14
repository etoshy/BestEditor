"""
notificacoes.py
===============

🔔 NOTIFICAÇÕES — o sininho (tipo o do YouTube) que fica no canto de TODAS as páginas.

Qualquer coisa que roda em segundo plano avisa aqui quando termina, dá erro ou precisa de você
(ex.: captcha no navegador). Aparece a bolinha com o número de não lidas; clicando no sino abre a
lista e clicando num item você vai direto pro lugar (o projeto, o áudio, o zip, a aba…).

  avisar(titulo, msg="", link="", nivel="ok", tipo="", chave="")  → cria (ou atualiza, se a `chave` já existe)
  resolver(chave)                                                → some com um aviso que não vale mais (captcha resolvido)
  listar() · nao_lidas() · marcar_lidas(ids|None) · limpar()

Fica salvo em outputs/notificacoes.json (sobrevive a fechar o site) — e a página 🕘 Histórico mostra tudo,
junto com as tarefas de segundo plano (tarefas_bg.py).

Nunca derruba quem chamou: qualquer erro aqui é engolido.
"""
from __future__ import annotations

import json
import os
import arquivo_seguro  # noqa: E402  (v84_99: os.replace sem WinError 5)
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

ARQUIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", "notificacoes.json")
MAXIMO = 400
NIVEIS = ("ok", "erro", "aviso", "info")
_TRAVA = threading.RLock()


def _ler() -> List[Dict[str, Any]]:
    try:
        with open(ARQUIVO, encoding="utf-8") as f:
            d = json.load(f)
        return [x for x in d if isinstance(x, dict) and x.get("id")] if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _gravar(itens: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(ARQUIVO), exist_ok=True)
    tmp = ARQUIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(itens[:MAXIMO], f, ensure_ascii=False)
    arquivo_seguro.trocar(tmp, ARQUIVO)


def link_seguro(link: Any) -> str:
    """Só links do próprio site ("/…"), nunca "//outro-site" nem "javascript:"."""
    link = str(link or "").strip()
    return link if link.startswith("/") and not link.startswith("//") and "\\" not in link else ""


def avisar(titulo: str, msg: str = "", link: str = "", nivel: str = "ok", tipo: str = "",
           chave: str = "") -> Optional[Dict[str, Any]]:
    """Cria uma notificação. Com `chave`, se já houver uma NÃO lida com a mesma chave ela é atualizada
    (não enche a lista com o mesmo aviso repetido — ex.: "captcha esperando")."""
    try:
        item = {"id": uuid.uuid4().hex[:12], "titulo": str(titulo or "")[:160], "msg": str(msg or "")[:600],
                "link": link_seguro(link), "nivel": nivel if nivel in NIVEIS else "info", "tipo": str(tipo or "")[:40],
                "chave": str(chave or "")[:120], "quando": time.time(), "lida": False}
        with _TRAVA:
            itens = _ler()
            if item["chave"]:
                for velho in itens:
                    if velho.get("chave") == item["chave"] and not velho.get("lida"):
                        itens.remove(velho)
                        item["id"] = velho["id"]
                        break
            itens.insert(0, item)
            _gravar(itens)
        return item
    except Exception:  # noqa: BLE001
        return None


def resolver(chave: str) -> int:
    """Marca como lidas as notificações com essa chave (o problema já foi resolvido)."""
    if not chave:
        return 0
    try:
        with _TRAVA:
            itens, n = _ler(), 0
            for x in itens:
                if x.get("chave") == chave and not x.get("lida"):
                    x["lida"], n = True, n + 1
            if n:
                _gravar(itens)
            return n
    except Exception:  # noqa: BLE001
        return 0


def listar(limite: int = MAXIMO) -> List[Dict[str, Any]]:
    with _TRAVA:
        return _ler()[:limite]


def nao_lidas() -> int:
    return sum(1 for x in listar() if not x.get("lida"))


def marcar_lidas(ids: Optional[List[str]] = None) -> int:
    with _TRAVA:
        itens, n = _ler(), 0
        for x in itens:
            if not x.get("lida") and (ids is None or x["id"] in ids):
                x["lida"], n = True, n + 1
        if n:
            _gravar(itens)
        return n


def pegar(nid: str) -> Optional[Dict[str, Any]]:
    return next((x for x in listar() if x["id"] == nid), None)


def limpar() -> None:
    with _TRAVA:
        _gravar([])


# ------------------------------------------------------------------ rotas
def registrar(app, base_dir: str) -> None:
    from flask import abort, jsonify, redirect, render_template, request

    global ARQUIVO  # noqa: PLW0603
    if os.environ.get("NOTIFICACOES_ARQUIVO"):
        ARQUIVO = os.environ["NOTIFICACOES_ARQUIVO"]
    else:
        ARQUIVO = os.path.join(base_dir, "outputs", "notificacoes.json")

    @app.route("/notificacoes")
    def notificacoes_lista():
        itens = listar(60)
        return jsonify({"itens": itens, "nao_lidas": sum(1 for x in listar() if not x.get("lida")), "agora": time.time()})

    @app.route("/notificacoes/lidas", methods=["POST"])
    def notificacoes_lidas():
        ids = (request.get_json(silent=True) or {}).get("ids")
        n = marcar_lidas([str(i) for i in ids] if isinstance(ids, list) else None)
        return jsonify({"ok": True, "marcadas": n})

    @app.route("/notificacoes/limpar", methods=["POST"])
    def notificacoes_limpar():
        limpar()
        return jsonify({"ok": True})

    @app.route("/notificacoes/ir/<nid>")
    def notificacoes_ir(nid: str):
        item = pegar(nid)
        if not item:
            abort(404)
        marcar_lidas([nid])
        return redirect(item.get("link") or "/historico")

    @app.route("/historico")
    def historico_page():
        import tarefas_bg
        return render_template("historico.html", notificacoes=listar(), tarefas=tarefas_bg.listar(300))
