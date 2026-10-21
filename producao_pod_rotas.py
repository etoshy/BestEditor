"""🏭 Rotas da aba Produção no pod (producao_pod.py)."""
from __future__ import annotations

from typing import Any


def registrar(app, base_dir: str) -> None:
    import os

    from flask import abort, jsonify, render_template, request, send_file

    import producao_pod as pp

    def _perfis():
        try:
            from tts.voice_generator import listar_perfis_de_voz
            return listar_perfis_de_voz()
        except Exception:  # noqa: BLE001
            return []

    def _idiomas():
        import idiomas
        return [(k, v[0]) for k, v in idiomas.IDIOMAS.items()]

    def _canais():
        try:
            import marca_visual
            return marca_visual.listar(base_dir)
        except Exception:  # noqa: BLE001
            return []

    @app.route("/producao-pod", methods=["GET"])
    def producao_pod_page():
        import pod_studio
        pp.garantir_runner()
        lotes = [dict(l, resumo=pp.resumo_lote(l)) for l in pp.listar()]
        return render_template("producao_pod.html", lotes=lotes, roteiros=pp.roteiros_disponiveis(base_dir),
                               perfis=_perfis(), idiomas=_idiomas(), pod_url=pod_studio.url() or "",
                               chatterbox_onde=(pod_studio._cfg(None).get("chatterbox_onde") or "local"),
                               padrao=dict(pp.PADRAO_ITEM, **pp.PADRAO_LOTE), canais=_canais())

    @app.route("/producao-pod/roteiro", methods=["GET"])
    def producao_pod_roteiro():
        try:
            texto = pp.texto_do_roteiro(request.args.get("origem", ""), request.args.get("id", ""), base_dir)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"erro": str(exc)}), 404
        return jsonify({"texto": texto, "palavras": len(texto.split())})

    @app.route("/producao-pod/criar", methods=["POST"])
    def producao_pod_criar():
        d: Any = request.get_json(silent=True) or {}
        try:
            lote = pp.criar(d.get("itens") or [], d.get("config") or {}, pod_url=str(d.get("pod_url") or ""),
                            nome=str(d.get("nome") or ""))
        except pp.ProducaoErro as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True, "id": lote["id"], "link": f"/producao-pod/{lote['id']}"})

    @app.route("/producao-pod/<lid>", methods=["GET"])
    def producao_pod_lote(lid: str):
        try:
            lote = pp.carregar(lid)
        except pp.ProducaoErro:
            abort(404)
        pp.garantir_runner()
        return render_template("producao_pod_lote.html", lote=lote, resumo=pp.resumo_lote(lote), rotulos=pp.ROTULOS)

    @app.route("/producao-pod/<lid>/estado", methods=["GET"])
    def producao_pod_estado(lid: str):
        try:
            lote = pp.carregar(lid)
        except pp.ProducaoErro:
            return jsonify({"erro": "lote não encontrado"}), 404
        itens = [{k: it.get(k) for k in ("id", "titulo", "estado", "mensagem", "job_id", "erro", "cenas", "idioma",
                                          "motor", "perfil", "avisos", "inicio", "fim", "gv_id", "pod_img", "faltam_img", "baixadas", "recentes", "canal")}
                 | {"rotulo": pp.ROTULOS.get(it["estado"], it["estado"]), "log": (it.get("log") or [])[-8:]}
                 for it in lote["itens"]]
        return jsonify({"status": lote["status"], "resumo": pp.resumo_lote(lote), "itens": itens, "pod_url": lote.get("pod_url") or ""})

    @app.route("/producao-pod/<lid>/cancelar", methods=["POST"])
    def producao_pod_cancelar(lid: str):
        try:
            pp.cancelar(lid)
        except pp.ProducaoErro as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True})

    def _pod_url_do_pedido() -> str:
        d: Any = request.get_json(silent=True) or {}
        return str(d.get("pod_url") or request.form.get("pod_url") or "").strip()

    @app.route("/producao-pod/<lid>/pod-url", methods=["POST"])
    def producao_pod_trocar_pod(lid: str):
        """🔗 v84_181: o lote passa a usar outro pod (VPS nova)."""
        try:
            return jsonify(pp.trocar_pod(lid, _pod_url_do_pedido()))
        except pp.ProducaoErro as exc:
            return jsonify({"erro": str(exc)}), 400

    @app.route("/producao-pod/<lid>/<iid>/tentar", methods=["POST"])
    def producao_pod_tentar(lid: str, iid: str):
        try:
            pp.tentar_de_novo(lid, iid, pod_url=_pod_url_do_pedido())
        except pp.ProducaoErro as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True})

    @app.route("/producao-pod/<lid>/<iid>/imagens-de-novo", methods=["POST"])
    def producao_pod_imagens_de_novo(lid: str, iid: str):
        try:
            pp.baixar_imagens_de_novo(lid, iid)
        except pp.ProducaoErro as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True})

    @app.route("/producao-pod/<lid>/<iid>/imagem/<nome>")
    def producao_pod_imagem(lid: str, iid: str, nome: str):
        import re as _re
        if not _re.fullmatch(r"cena-\d{4}\.png", nome) or not _re.fullmatch(r"[\w-]+", lid + iid):
            return "", 404
        cam = os.path.join(pp.pasta_item(lid, iid), "imagens", nome)
        if not os.path.exists(cam):
            return "", 404
        return send_file(cam, max_age=3600)

    @app.route("/producao-pod/<lid>/<iid>/galeria")
    def producao_pod_galeria(lid: str, iid: str):
        try:
            lote = pp.carregar(lid)
            it = next(x for x in lote["itens"] if x["id"] == iid)
        except Exception:  # noqa: BLE001
            return "Roteiro não encontrado.", 404
        return render_template("producao_pod_galeria.html", lote=lote, it=it, imgs=pp.galeria(lid, iid))

    @app.route("/producao-pod/<lid>/<iid>/completar-pod", methods=["POST"])
    def producao_pod_completar(lid: str, iid: str):
        """🖼 v84_223: as cenas ⏳ pendentes deste roteiro viram imagem do pod (100%)."""
        try:
            return jsonify(pp.completar_no_pod(lid, iid))
        except pp.ProducaoErro as exc:
            return jsonify({"erro": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001 — pod fora do ar etc.
            return jsonify({"erro": str(exc)[:300]}), 400

    @app.route("/producao-pod/<lid>/<iid>/refazer-imagens", methods=["POST"])
    def producao_pod_refazer_imagens(lid: str, iid: str):
        try:
            return jsonify(pp.refazer_imagens(lid, iid, pod_url=_pod_url_do_pedido()))
        except pp.ProducaoErro as exc:
            return jsonify({"erro": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001 — pod fora do ar etc.
            return jsonify({"erro": str(exc)[:300]}), 400

    @app.route("/producao-pod/<lid>/excluir", methods=["POST"])
    def producao_pod_excluir(lid: str):
        try:
            pp.excluir(lid)
        except pp.ProducaoErro as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True})
