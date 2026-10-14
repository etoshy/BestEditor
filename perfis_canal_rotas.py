"""Rotas da página 📺 Perfis do canal (perfis_canal.py) — v84_101."""
from __future__ import annotations

import os
import uuid

from flask import jsonify, redirect, render_template, request, send_file
from werkzeug.utils import secure_filename

import perfis_canal as pc


def registrar(app, base_dir: str) -> None:

    def _json():
        d = pc.carregar()
        return {"ok": True, "ativo": d["ativo"], "tipos": pc.TIPOS, "curto": pc.CURTO, "ordem": list(pc.TIPOS),
                "perfis": [{"id": p["id"], "nome": p["nome"], "nome_canal": p["nome_canal"], "ativo": p["id"] == d["ativo"],
                            "videos": {t: [dict(v, padrao=v["id"] == p["padrao"].get(t), url=f"/perfis-canal/{p['id']}/video/{v['id']}",
                                               arquivo=os.path.basename(v["arquivo"])) for v in p["videos"][t]] for t in pc.TIPOS}}
                           for p in d["perfis"]]}

    def _erro(exc):
        return jsonify({"erro": str(exc)}), 400

    @app.route("/perfis-canal")
    def perfis_canal_page():
        return render_template("perfis_canal.html")

    @app.route("/perfis-canal/dados")
    def perfis_canal_dados():
        return jsonify(_json())

    @app.route("/perfis-canal/novo", methods=["POST"])
    def perfis_canal_novo():
        c = request.get_json(silent=True) or {}
        p = pc.criar(str(c.get("nome") or "Novo canal"), str(c.get("nome_canal") or ""), bool(c.get("ativar")))
        return jsonify(dict(_json(), novo=p["id"]))

    @app.route("/perfis-canal/<pid>", methods=["POST"])
    def perfis_canal_editar(pid: str):
        c = request.get_json(silent=True) or {}
        try:
            pc.editar(pid, c.get("nome"), c.get("nome_canal"))
            if c.get("ativar"):
                pc.definir_ativo(pid)
        except pc.PerfilErro as exc:
            return _erro(exc)
        if pc.ativo_id() == pid and c.get("nome_canal") is not None:  # o nome do canal das ⚙️ Configurações acompanha
            try:
                from site_config import save_site_config
                save_site_config({"nome_canal": str(c.get("nome_canal") or "")})
            except Exception:  # noqa: BLE001
                pass
        return jsonify(_json())

    @app.route("/perfis-canal/<pid>/apagar", methods=["POST"])
    def perfis_canal_apagar(pid: str):
        try:
            pc.apagar(pid)
        except pc.PerfilErro as exc:
            return _erro(exc)
        return jsonify(_json())

    @app.route("/perfis-canal/<pid>/<tipo>/enviar", methods=["POST"])
    def perfis_canal_enviar(pid: str, tipo: str):
        """Um ou vários vídeos de um tipo (campo "arquivos", múltiplo)."""
        if tipo not in pc.TIPOS:
            return jsonify({"erro": "Tipo desconhecido."}), 404
        arqs = [f for f in request.files.getlist("arquivos") + request.files.getlist("arquivo") if f and f.filename]
        if not arqs:
            return jsonify({"erro": "Nenhum arquivo enviado."}), 400
        tmpdir = os.path.join(pc.pasta(), "_envio")
        os.makedirs(tmpdir, exist_ok=True)
        novos = []
        try:
            for f in arqs:
                tmp = os.path.join(tmpdir, f"{uuid.uuid4().hex[:8]}_{secure_filename(f.filename) or 'video.mp4'}")
                f.save(tmp)
                try:
                    novos.append(pc.adicionar_video(pid, tipo, tmp, f.filename))
                finally:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        except pc.PerfilErro as exc:
            return _erro(exc)
        if request.args.get("voltar"):
            return redirect("/perfis-canal")
        return jsonify(dict(_json(), enviados=len(novos)))

    @app.route("/perfis-canal/<pid>/video/<vid>")
    def perfis_canal_video(pid: str, vid: str):
        cam = pc.caminho(pid, vid)
        if not cam:
            return "Vídeo não encontrado.", 404
        return send_file(cam, conditional=True)

    @app.route("/perfis-canal/<pid>/video/<vid>", methods=["POST"])
    def perfis_canal_video_editar(pid: str, vid: str):
        c = request.get_json(silent=True) or {}
        try:
            pc.editar_video(pid, vid, c.get("nome"), c.get("padrao") if "padrao" in c else None)
        except pc.PerfilErro as exc:
            return _erro(exc)
        return jsonify(_json())

    @app.route("/perfis-canal/<pid>/video/<vid>/apagar", methods=["POST"])
    def perfis_canal_video_apagar(pid: str, vid: str):
        try:
            pc.apagar_video(pid, vid)
        except pc.PerfilErro as exc:
            return _erro(exc)
        return jsonify(_json())
