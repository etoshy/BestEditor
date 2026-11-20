"""🛡 v84_437 — página Fontes confiáveis: testar todos os sites, a IA avaliar os candidatos, confiar/bloquear, referências."""
from __future__ import annotations

from typing import Any, Dict


def registrar(app, base_dir: str) -> None:
    from flask import jsonify, render_template, request
    import fontes_confianca as fc
    import os
    if not os.environ.get("FONTES_CONFIANCA_DIR"):
        fc.BASE = base_dir

    def _dados() -> Dict[str, Any]:
        d = fc.carregar()
        refs = sorted(({"chave": k, **v} for k, v in (d.get("referencias") or {}).items()),
                      key=lambda x: -(x.get("em") or 0))
        return {"sites": fc.todos_os_sites(), "referencias": refs}

    @app.route("/fontes-confiaveis")
    def fontes_confiaveis():
        return render_template("fontes_confiaveis.html", dados=_dados(), nota_min=fc.NOTA_MIN_IA)

    @app.route("/fontes-confiaveis/dados")
    def fontes_confiaveis_dados():
        return jsonify(_dados())

    @app.route("/fontes-confiaveis/regra", methods=["POST"])
    def fontes_confiaveis_regra():
        c = request.get_json(silent=True) or {}
        try:
            fc.regra(str(c.get("site") or ""), str(c.get("decisao") or ""))
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify(dict(_dados(), ok=True))

    def _tarefa(tipo: str, titulo: str, fn):
        import tarefas_bg
        return tarefas_bg.iniciar(tipo, titulo, fn, pagina="/fontes-confiaveis")

    @app.route("/fontes-confiaveis/testar", methods=["POST"])
    def fontes_confiaveis_testar():
        so = [str(x) for x in (request.get_json(silent=True) or {}).get("so") or []]
        return jsonify({"ok": True, "tarefa": _tarefa("fontes_testar", "🔌 Testar os sites das fontes",
                                                      lambda t: fc.testar_todos(progresso=t.progresso, so=so or None))})

    @app.route("/fontes-confiaveis/avaliar", methods=["POST"])
    def fontes_confiaveis_avaliar():
        import ia_servico as ia
        motivo = ia.motivo_desligado("fontes_descricao")
        if motivo:
            return jsonify({"erro": "IA: " + motivo}), 400
        so = [str(x) for x in (request.get_json(silent=True) or {}).get("so") or []]
        return jsonify({"ok": True, "tarefa": _tarefa("fontes_avaliar", "🤖 Avaliar os sites das fontes",
                                                      lambda t: {"avaliados": fc.avaliar_com_ia(so=so or None)})})

    @app.route("/fontes-confiaveis/lembrar", methods=["POST"])
    def fontes_confiaveis_lembrar():
        c = request.get_json(silent=True) or {}
        ref, url = str(c.get("referencia") or "").strip(), str(c.get("url") or "").strip()
        if not ref or not url.startswith(("http://", "https://")):
            return jsonify({"erro": "Escreva a referência (ex.: Platão — Fédon) e o link (https://…)."}), 400
        fc.lembrar(ref, url, manual=True)
        return jsonify(dict(_dados(), ok=True))

    @app.route("/fontes-confiaveis/esquecer", methods=["POST"])
    def fontes_confiaveis_esquecer():
        fc.esquecer(str((request.get_json(silent=True) or {}).get("chave") or ""))
        return jsonify(dict(_dados(), ok=True))
