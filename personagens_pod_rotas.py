"""🧍 Rotas da aba Personagens no pod (personagens_pod.py) — v84_183."""
from __future__ import annotations

import io
import json
import os
import re
from typing import Any


def registrar(app, base_dir: str) -> None:
    from flask import abort, jsonify, redirect, render_template, request, send_file, url_for

    import personagens_pod as pp

    def _pod_padrao() -> str:
        try:
            from site_config import load_site_config
            return str(load_site_config().get("personagens_pod_url") or "")
        except Exception:  # noqa: BLE001
            return ""

    def _guardar_pod_padrao(url: str) -> None:
        try:
            from site_config import save_site_config
            if url:
                save_site_config({"personagens_pod_url": url})
        except Exception:  # noqa: BLE001
            pass

    def _corpo() -> Any:
        return request.get_json(silent=True) or {}

    def _ok(fn, *a):
        try:
            r = fn(*a)
        except pp.PersErro as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify(r if isinstance(r, dict) and "imagens" not in r else {"ok": True})

    @app.route("/personagens-pod", methods=["GET"])
    def personagens_pod_page():
        return render_template("personagens_pod.html", projetos=pp.listar(base_dir), pod_url=_pod_padrao(),
                               erro=request.args.get("erro") or "", canais=_canais())

    def _canais():
        try:
            return pp.personagens_dos_canais(base_dir)
        except Exception:  # noqa: BLE001
            return []

    @app.route("/personagens-pod/criar-do-canal", methods=["POST"])
    def personagens_pod_criar_do_canal():
        refs = [(f.filename, f.read()) for f in request.files.getlist("refs") if f and f.filename]
        try:
            p = pp.criar_do_canal(request.form.get("canal") or "", request.form.get("personagem") or "", refs,
                                  request.form.get("motor") or "flow", (request.form.get("pod_url") or "").strip(), "", base_dir)
        except pp.PersErro as exc:
            return redirect(url_for("personagens_pod_page", erro=str(exc)))
        return redirect(url_for("personagens_pod_projeto", pid=p["id"]))

    @app.route("/personagens-pod/<pid>/canal", methods=["POST"])
    def personagens_pod_canal(pid: str):
        c = _corpo()
        return _ok(pp.ligar_canal, pid, str(c.get("canal") or ""), str(c.get("personagem") or ""), bool(c.get("usar_json")), base_dir)

    @app.route("/personagens-pod/<pid>/canal/desligar", methods=["POST"])
    def personagens_pod_canal_desligar(pid: str):
        return _ok(pp.desligar_canal, pid, base_dir)

    @app.route("/personagens-pod/criar", methods=["POST"])
    def personagens_pod_criar():
        texto = request.form.get("json") or ""
        arq_json = request.files.get("json_arquivo")
        if arq_json and arq_json.filename:
            texto = arq_json.read().decode("utf-8-sig", errors="replace")
        refs = [(f.filename, f.read()) for f in request.files.getlist("refs") if f and f.filename]
        url = (request.form.get("pod_url") or "").strip()
        try:
            p = pp.criar(request.form.get("nome") or "", texto, refs, url, base_dir, motor=request.form.get("motor") or "flow")
        except pp.PersErro as exc:
            return redirect(url_for("personagens_pod_page", erro=str(exc)))
        if url:
            _guardar_pod_padrao(url)
        return redirect(url_for("personagens_pod_projeto", pid=p["id"]))

    @app.route("/personagens-pod/<pid>", methods=["GET"])
    def personagens_pod_projeto(pid: str):
        try:
            p = pp.carregar(pid, base_dir)
        except pp.PersErro:
            abort(404)
        try:
            import flow_lote
            visivel = bool(flow_lote.lote().cfg.get("visivel"))
        except Exception:  # noqa: BLE001
            visivel = False
        return render_template("personagens_pod_projeto.html", p=pp.para_tela(p), flow_visivel=visivel, canais=_canais())

    @app.route("/personagens-pod/<pid>/estado", methods=["GET"])
    def personagens_pod_estado(pid: str):
        aviso = None
        try:
            aviso = pp.sincronizar(pid, base_dir).get("aviso")
            p = pp.carregar(pid, base_dir)
        except pp.PersErro as exc:
            return jsonify({"erro": str(exc)}), 404
        return jsonify(dict(pp.para_tela(p), aviso=aviso))

    @app.route("/personagens-pod/<pid>/pod-status", methods=["GET"])
    def personagens_pod_status(pid: str):
        try:
            p = pp.carregar(pid, base_dir)
            return jsonify(pp.status_pod(p.get("pod_url") or ""))
        except pp.PersErro as exc:
            return jsonify({"erro": str(exc)}), 400

    @app.route("/personagens-pod/<pid>/pod-url", methods=["POST"])
    def personagens_pod_url(pid: str):
        url = str(_corpo().get("pod_url") or "")
        try:
            pp.trocar_pod(pid, url, base_dir)
        except pp.PersErro as exc:
            return jsonify({"erro": str(exc)}), 400
        _guardar_pod_padrao(url.strip().rstrip("/"))
        return jsonify({"ok": True})

    @app.route("/personagens-pod/<pid>/gerar", methods=["POST"])
    def personagens_pod_gerar(pid: str):
        c = _corpo()
        try:
            passos = int(c.get("passos") or 0)
        except (TypeError, ValueError):
            passos = 0
        return _ok(lambda: pp.enviar(pid, [str(a) for a in c.get("arquivos") or []], str(c.get("extra") or ""), base_dir,
                                     qualidade=str(c.get("qualidade") or ""), passos=passos,
                                     quantidade=str(c.get("quantidade") or "x1")))

    @app.route("/personagens-pod/<pid>/animar-todas", methods=["POST"])
    def personagens_pod_animar_todas(pid: str):
        """👄 v84_209: a boca aberta de TODA pose (a animação de fala), num clique — como a criação das poses."""
        return _ok(lambda: pp.animar_todas(pid, base_dir, str(_corpo().get("quantidade") or "x1")))

    @app.route("/personagens-pod/<pid>/boca", methods=["POST"])
    def personagens_pod_boca(pid: str):
        c = _corpo()
        return _ok(lambda: pp.animar_pose(pid, str(c.get("arquivo") or ""), base_dir, str(c.get("quantidade") or "x1")))

    @app.route("/personagens-pod/<pid>/motor", methods=["POST"])
    def personagens_pod_motor(pid: str):
        return _ok(pp.trocar_motor, pid, str(_corpo().get("motor") or ""), base_dir)

    @app.route("/personagens-pod/<pid>/json", methods=["GET", "POST"])
    def personagens_pod_json(pid: str):
        if request.method == "GET":
            try:
                p = pp.carregar(pid, base_dir)
            except pp.PersErro as exc:
                return jsonify({"erro": str(exc)}), 404
            return jsonify({"json": json.dumps(p["dados"], ensure_ascii=False, indent=1)})
        return _ok(pp.trocar_json, pid, str(_corpo().get("json") or ""), base_dir)

    @app.route("/personagens-pod/<pid>/aprovar", methods=["POST"])
    def personagens_pod_aprovar(pid: str):
        return _ok(pp.aprovar, pid, str(_corpo().get("arquivo") or ""), base_dir)

    @app.route("/personagens-pod/<pid>/mestre", methods=["POST"])
    def personagens_pod_mestre(pid: str):
        return _ok(pp.usar_como_mestre, pid, str(_corpo().get("arquivo") or ""), base_dir)

    @app.route("/personagens-pod/<pid>/versao", methods=["POST"])
    def personagens_pod_versao(pid: str):
        c = _corpo()
        try:
            idx = int(c.get("idx"))
        except (TypeError, ValueError):
            return jsonify({"erro": "versão inválida"}), 400
        return _ok(pp.escolher_versao, pid, str(c.get("arquivo") or ""), idx, base_dir)

    @app.route("/personagens-pod/<pid>/descartar", methods=["POST"])
    def personagens_pod_descartar(pid: str):
        return _ok(pp.descartar, pid, str(_corpo().get("arquivo") or ""), base_dir)

    @app.route("/personagens-pod/<pid>/img/<nome>")
    def personagens_pod_img(pid: str, nome: str):
        if not re.fullmatch(r"[\w\-. ]+\.png", nome):
            abort(404)
        try:
            d = pp._pasta(pid, base_dir)
        except pp.PersErro:
            abort(404)
        for sub in ("imagens", "refs"):
            cam = os.path.join(d, sub, os.path.basename(nome))
            if os.path.isfile(cam):
                return send_file(cam, max_age=3600)
        abort(404)

    @app.route("/personagens-pod/<pid>/aprovadas.zip")
    def personagens_pod_zip(pid: str):
        try:
            p = pp.carregar(pid, base_dir)
            dados = pp.zip_aprovadas(pid, base_dir)
        except pp.PersErro as exc:
            return redirect(url_for("personagens_pod_projeto", pid=pid, erro=str(exc)))
        nome = re.sub(r"[^\w-]+", "_", p["nome"]).strip("_") or "personagem"
        return send_file(io.BytesIO(dados), mimetype="application/zip", as_attachment=True, download_name=f"poses_{nome}.zip")

    @app.route("/personagens-pod/<pid>/excluir", methods=["POST"])
    def personagens_pod_excluir(pid: str):
        try:
            pp.excluir(pid, base_dir)
        except pp.PersErro as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True})
