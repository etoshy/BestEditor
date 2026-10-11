"""🤖 Página /ia — liga a IA (hoje o Claude Haiku 5.5) nas buscas, no editor e nos Modelos de vídeo."""
from __future__ import annotations

from typing import Any

import ia_servico as ia


def registrar(app, base_dir: str) -> None:
    from flask import jsonify, redirect, render_template, request, url_for

    @app.context_processor
    def _ia_no_template():
        def ia_resumo():
            try:
                return ia.resumo_publico()
            except Exception:  # noqa: BLE001
                return {"motivo": "erro ao ler a config", "modelo": ""}
        return {"ia_resumo": ia_resumo}

    def _pagina(**extra: Any):
        return render_template("ia.html", r=ia.resumo_publico(), provedores=ia.PROVEDORES, recursos=ia.RECURSOS,
                               recentes=ia.recentes()[:15], **extra)

    @app.route("/ia", methods=["GET"])
    def ia_page():
        return _pagina()

    @app.route("/ia", methods=["POST"])
    def ia_salvar():
        f = request.form
        novos: dict = {
            "ativo": f.get("ativo") == "on", "provedor": f.get("provedor") or "claude", "modelo": f.get("modelo") or "",
            "recursos": {k: f.get(f"rec_{k}") == "on" for k in ia.RECURSOS},
            "nota_minima": f.get("nota_minima", 7), "candidatos": f.get("candidatos", 10), "limite_usd": f.get("limite_usd", 5),
        }
        if (f.get("chave") or "").strip():  # em branco = mantém a salva
            novos["chave"] = f["chave"].strip()
        if f.get("apagar_chave") == "on":
            novos["chave"] = ""
        ia.salvar_config(novos)
        return _pagina(salvo=True)

    @app.route("/ia/testar", methods=["POST"])
    def ia_testar():
        return jsonify(ia.testar())

    @app.route("/ia/tentar-de-novo", methods=["POST"])
    def ia_tentar_de_novo():
        ia.salvar_config({"limpar_sem_credito": True})
        return redirect(url_for("ia_page"))

    @app.route("/ia/zerar-gasto", methods=["POST"])
    def ia_zerar_gasto():
        ia.zerar_gasto()
        return redirect(url_for("ia_page"))

    @app.route("/ia/status")
    def ia_status():
        r = ia.resumo_publico()
        r["pode"] = {k: ia.ativo(k) for k in ia.RECURSOS}
        return jsonify(r)
