"""
Rotas do 🧬 Criador de personagens (ver criador_personagens.py). Registradas pelo app.py com `registrar(app, base_dir)`.
"""
from __future__ import annotations

import io
import os
import threading
import time
from typing import Any, Callable, Dict, Optional

from flask import abort, jsonify, redirect, render_template, request, send_file

import criador_lugares as CL
import criador_personagens as C

TAREFAS: Dict[str, Dict[str, Any]] = {}
_ULTIMO: Dict[str, float] = {}


def registrar(app, base_dir: str) -> None:
    registrar_lugares(app, base_dir)

    def _p(pid: str) -> Dict[str, Any]:
        try:
            return C.carregar(pid, base_dir)
        except C.CriadorErro:
            abort(404)

    def _ok(**kw: Any):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: str, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _img():
        from PIL import Image
        arq = request.files.get("arquivo")
        if not arq or not arq.filename:
            raise C.CriadorErro("Escolha a imagem.")
        try:
            im = Image.open(arq.stream)
            im.load()
            return im
        except Exception:  # noqa: BLE001
            raise C.CriadorErro("Isso não é uma imagem.")

    def _rodar(pid: str, rotulo: str, fn: Callable[[], Any]):
        t = TAREFAS.get(pid)
        if t and not t.get("fim"):
            return _erro(f"Espere terminar: {t['rotulo']}", 409)
        TAREFAS[pid] = {"rotulo": rotulo, "inicio": time.time(), "fim": None, "erro": None, "msg": ""}

        def corpo():
            try:
                r = fn()
                TAREFAS[pid].update(msg=r if isinstance(r, str) else "")
            except Exception as exc:  # noqa: BLE001
                TAREFAS[pid].update(erro=str(exc)[:400])
            finally:
                TAREFAS[pid]["fim"] = time.time()
        threading.Thread(target=corpo, daemon=True).start()
        return _ok(tarefa=True)

    @app.context_processor
    def _ctx_criador():
        return {"criador_lista": lambda: C.listar(base_dir)}

    @app.route("/criador-personagens", methods=["GET"])
    def criador_lista():
        return render_template("criador_lista.html", lista=C.listar(base_dir), estilos=C.ESTILOS, epocas=C.EPOCAS,
                               lugares=CL.listar(base_dir), escalas={k: v[0] for k, v in CL.ESCALAS.items()})

    @app.route("/criador-personagens/novo", methods=["POST"])
    def criador_novo():
        p = C.criar(request.form.get("nome") or "", base_dir)
        dados = {k: request.form.get(k) for k in ("descricao", "inspiracoes", "estilo", "estilo_livre") if request.form.get(k)}
        if dados:
            C.editar_entrada(p, dados)
        for k, f in enumerate(request.files.getlist("refs")[:C.MAX_REFS]):
            if not f or not f.filename:
                continue
            try:
                from PIL import Image
                im = Image.open(f.stream)
                im.load()
                C.guardar_ref(p, im, ["tudo"], "", base_dir)
            except Exception:  # noqa: BLE001
                continue
        C.salvar(p, base_dir)
        return redirect(f"/criador-personagens/{p['id']}")

    @app.route("/criador-personagens/<pid>", methods=["GET"])
    def criador_detalhe(pid: str):
        p = _p(pid)
        return render_template("criador_detalhe.html", p=p, estilos=C.ESTILOS, aspectos={k: v[0] for k, v in C.ASPECTOS.items()},
                               epocas=C.EPOCAS, lugares=CL.listar(base_dir),
                               pacotes={k: v[0] for k, v in C.PACOTES.items()}, max_refs=C.MAX_REFS,
                               max_var=C.MAX_VARIACOES)

    @app.route("/criador-personagens/<pid>/estado", methods=["GET"])
    def criador_estado(pid: str):
        _p(pid)
        if time.time() - _ULTIMO.get(pid, 0) > 2.5:
            _ULTIMO[pid] = time.time()
            try:
                C.acompanhar(pid, base_dir)
            except Exception:  # noqa: BLE001
                pass
        out = C.para_tela(C.carregar(pid, base_dir), base_dir)
        out["tarefa"] = TAREFAS.get(pid)
        return jsonify(out)

    @app.route("/criador-personagens/<pid>/dados", methods=["POST"])
    def criador_dados(pid: str):
        with C._TRAVA:
            p = _p(pid)
            C.editar_entrada(p, request.get_json(silent=True) or {})
            C.salvar(p, base_dir)
        return _ok()

    @app.route("/criador-personagens/<pid>/refs", methods=["POST"])
    def criador_refs(pid: str):
        try:
            im = _img()
            with C._TRAVA:
                p = _p(pid)
                pegar = [x for x in (request.form.get("pegar") or "tudo").split(",") if x]
                r = C.guardar_ref(p, im, pegar, request.form.get("nota") or "", base_dir)
                C.salvar(p, base_dir)
            return _ok(ref=r)
        except C.CriadorErro as exc:
            return _erro(str(exc))

    @app.route("/criador-personagens/<pid>/refs/<arquivo>", methods=["POST"])
    def criador_ref_editar(pid: str, arquivo: str):
        try:
            with C._TRAVA:
                p = _p(pid)
                C.editar_ref(p, arquivo, request.get_json(silent=True) or {}, base_dir)
                C.salvar(p, base_dir)
            return _ok()
        except C.CriadorErro as exc:
            return _erro(str(exc))

    @app.route("/criador-personagens/<pid>/ficha/ia", methods=["POST"])
    def criador_ficha_ia(pid: str):
        _p(pid)
        return _rodar(pid, "🤖 montando a ficha", lambda: C.montar_ficha(pid, base_dir))

    @app.route("/criador-personagens/<pid>/ficha", methods=["POST"])
    def criador_ficha(pid: str):
        with C._TRAVA:
            p = _p(pid)
            C.editar_ficha(p, request.get_json(silent=True) or {})
            C.salvar(p, base_dir)
        return _ok(nome=p["nome"])

    @app.route("/criador-personagens/<pid>/design/gerar", methods=["POST"])
    def criador_design_gerar(pid: str):
        _p(pid)
        c = request.get_json(silent=True) or {}
        try:
            return _ok(**C.gerar_design(pid, base_dir, int(c.get("n") or 4), str(c.get("correcao") or ""),
                                        str(c.get("a_partir") or "")))
        except (C.CriadorErro, ValueError) as exc:
            return _erro(str(exc))

    @app.route("/criador-personagens/<pid>/design/enviar", methods=["POST"])
    def criador_design_enviar(pid: str):
        _p(pid)
        try:
            v = C.enviar_imagem_design(pid, _img(), base_dir)
            return _ok(id=v["id"])
        except C.CriadorErro as exc:
            return _erro(str(exc))

    @app.route("/criador-personagens/<pid>/design/<vid>/<acao>", methods=["POST"])
    def criador_design_acao(pid: str, vid: str, acao: str):
        _p(pid)
        try:
            if acao == "aprovar":
                C.aprovar(pid, vid, base_dir)
            elif acao == "apagar":
                C.apagar_variacao(pid, vid, base_dir)
            else:
                abort(404)
            return _ok()
        except C.CriadorErro as exc:
            return _erro(str(exc))

    @app.route("/criador-personagens/<pid>/poses", methods=["POST"])
    def criador_poses(pid: str):
        _p(pid)
        c = request.get_json(silent=True) or {}
        extras = [x for x in str(c.get("extras") or "").splitlines() if x.strip()]
        try:
            return _ok(**C.criar_poses(pid, list(c.get("pacotes") or []), extras, base_dir))
        except Exception as exc:  # noqa: BLE001
            return _erro(str(exc))

    @app.route("/criador-personagens/<pid>/arquivo/<pasta>/<nome>", methods=["GET"])
    def criador_arquivo(pid: str, pasta: str, nome: str):
        if pasta not in ("refs", "design"):
            abort(404)
        nome = os.path.basename(nome)
        cam = os.path.join(C.pasta(pid, base_dir), pasta, nome)
        if not os.path.isfile(cam):
            abort(404)
        return send_file(cam)

    @app.route("/criador-personagens/<pid>/pose/<nome>", methods=["GET"])
    def criador_pose_img(pid: str, nome: str):
        import personagens_pod as pp
        p = _p(pid)
        ppid = p["poses"].get("pod")
        if not ppid:
            abort(404)
        cam = os.path.join(pp._pasta(ppid, base_dir), "imagens", os.path.basename(nome))
        if not os.path.isfile(cam):
            abort(404)
        return send_file(cam)

    @app.route("/criador-personagens/<pid>/zip", methods=["GET"])
    def criador_zip(pid: str):
        p = _p(pid)
        return send_file(io.BytesIO(C.zip_personagem(pid, base_dir)), mimetype="application/zip", as_attachment=True,
                         download_name=f"{C._slug(p['nome'])}.zip")

    @app.route("/criador-personagens/<pid>/excluir", methods=["POST"])
    def criador_excluir(pid: str):
        _p(pid)
        C.excluir(pid, base_dir)
        return redirect("/criador-personagens")


def registrar_lugares(app, base_dir: str) -> None:
    """🗺 Lugares e mundos (v84_241)."""

    def _l(lid: str) -> Dict[str, Any]:
        try:
            return CL.carregar(lid, base_dir)
        except CL.LugarErro:
            abort(404)

    def _ok(**kw: Any):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: str, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _img():
        from PIL import Image
        arq = request.files.get("arquivo")
        if not arq or not arq.filename:
            raise CL.LugarErro("Escolha a imagem.")
        try:
            im = Image.open(arq.stream)
            im.load()
            return im
        except Exception:  # noqa: BLE001
            raise CL.LugarErro("Isso não é uma imagem.")

    def _mexer(lid: str, fn: Callable[[Dict[str, Any]], Any]):
        try:
            with CL._TRAVA:
                p = _l(lid)
                r = fn(p)
                CL.salvar(p, base_dir)
            return _ok(**(r if isinstance(r, dict) else {}))
        except (CL.LugarErro, ValueError) as exc:
            return _erro(str(exc))

    @app.route("/criador-lugares/novo", methods=["POST"])
    def lugar_novo():
        f = request.form
        try:
            p = CL.criar(f.get("nome") or "", f.get("escala") or "cidade", f.get("pai") or "", base_dir,
                         descricao=f.get("descricao") or "", estilo=f.get("estilo") or None, epoca=f.get("epoca") or None,
                         estilo_livre=f.get("estilo_livre") or None, epoca_livre=f.get("epoca_livre") or None)
        except CL.LugarErro as exc:
            return _erro(str(exc))
        for arq in request.files.getlist("refs")[:C.MAX_REFS]:
            if arq and arq.filename:
                try:
                    from PIL import Image
                    im = Image.open(arq.stream)
                    im.load()
                    CL.guardar_ref(p, im, ["tudo"], "", base_dir)
                except Exception:  # noqa: BLE001
                    continue
        CL.salvar(p, base_dir)
        return redirect(f"/criador-lugares/{p['id']}")

    @app.route("/criador-lugares/<lid>", methods=["GET"])
    def lugar_detalhe(lid: str):
        p = _l(lid)
        return render_template("criador_lugar.html", p=p, estilos=C.ESTILOS, epocas=C.EPOCAS,
                               escalas={k: v[0] for k, v in CL.ESCALAS.items()},
                               aspectos={k: v[0] for k, v in CL.ASPECTOS_LUGAR.items()},
                               lugares=[x for x in CL.listar(base_dir) if x["id"] != lid], max_refs=C.MAX_REFS)

    @app.route("/criador-lugares/<lid>/estado", methods=["GET"])
    def lugar_estado(lid: str):
        _l(lid)
        if time.time() - _ULTIMO.get(lid, 0) > 2.5:
            _ULTIMO[lid] = time.time()
            try:
                CL.acompanhar(lid, base_dir)
            except Exception:  # noqa: BLE001
                pass
        out = CL.para_tela(CL.carregar(lid, base_dir), base_dir)
        out["tarefa"] = TAREFAS.get(lid)
        return jsonify(out)

    @app.route("/criador-lugares/<lid>/dados", methods=["POST"])
    def lugar_dados(lid: str):
        return _mexer(lid, lambda p: CL.editar_entrada(p, request.get_json(silent=True) or {}))

    @app.route("/criador-lugares/<lid>/refs", methods=["POST"])
    def lugar_refs(lid: str):
        try:
            im = _img()
        except CL.LugarErro as exc:
            return _erro(str(exc))
        pegar = [x for x in (request.form.get("pegar") or "tudo").split(",") if x]
        return _mexer(lid, lambda p: {"ref": CL.guardar_ref(p, im, pegar, request.form.get("nota") or "", base_dir)})

    @app.route("/criador-lugares/<lid>/refs/<arquivo>", methods=["POST"])
    def lugar_ref_editar(lid: str, arquivo: str):
        return _mexer(lid, lambda p: CL.editar_ref(p, arquivo, request.get_json(silent=True) or {}, base_dir))

    @app.route("/criador-lugares/<lid>/ficha/ia", methods=["POST"])
    def lugar_ficha_ia(lid: str):
        _l(lid)
        t = TAREFAS.get(lid)
        if t and not t.get("fim"):
            return _erro(f"Espere terminar: {t['rotulo']}", 409)
        TAREFAS[lid] = {"rotulo": "🤖 montando a ficha do lugar", "inicio": time.time(), "fim": None, "erro": None, "msg": ""}

        def corpo():
            try:
                TAREFAS[lid]["msg"] = CL.montar_ficha(lid, base_dir)
            except Exception as exc:  # noqa: BLE001
                TAREFAS[lid]["erro"] = str(exc)[:400]
            finally:
                TAREFAS[lid]["fim"] = time.time()
        threading.Thread(target=corpo, daemon=True).start()
        return _ok(tarefa=True)

    @app.route("/criador-lugares/<lid>/ficha", methods=["POST"])
    def lugar_ficha(lid: str):
        return _mexer(lid, lambda p: CL.editar_ficha(p, request.get_json(silent=True) or {}))

    @app.route("/criador-lugares/<lid>/pessoa/<psid>/personagem", methods=["POST"])
    def lugar_pessoa(lid: str, psid: str):
        _l(lid)
        try:
            return _ok(id=CL.pessoa_vira_personagem(lid, psid, base_dir))
        except (CL.LugarErro, C.CriadorErro) as exc:
            return _erro(str(exc))

    @app.route("/criador-lugares/<lid>/pinos/<pnid>", methods=["POST"])
    def lugar_pino(lid: str, pnid: str):
        return _mexer(lid, lambda p: {"pino": CL.editar_pino(p, pnid, request.get_json(silent=True) or {})})

    @app.route("/criador-lugares/<lid>/pinos/<pnid>/sub", methods=["POST"])
    def lugar_pino_sub(lid: str, pnid: str):
        _l(lid)
        try:
            return _ok(id=CL.sub_lugar_do_pino(lid, pnid, base_dir))
        except CL.LugarErro as exc:
            return _erro(str(exc))

    @app.route("/criador-lugares/<lid>/escala", methods=["POST"])
    def lugar_escala(lid: str):
        c = request.get_json(silent=True) or {}

        def fn(p):
            try:
                larg = float(str(c.get("largura") or "0").replace(",", "."))
            except ValueError:
                raise CL.LugarErro("Largura inválida.")
            p["mapa"]["largura"] = larg if larg > 0 else None
            p["mapa"]["unidade"] = C._txt(c.get("unidade"), 30) or None
        return _mexer(lid, fn)

    @app.route("/criador-lugares/<lid>/fotos/gerar", methods=["POST"])
    def lugar_fotos(lid: str):
        _l(lid)
        c = request.get_json(silent=True) or {}
        try:
            return _ok(**CL.gerar_fotos(lid, list(c.get("vistas") or []), str(c.get("correcao") or ""), base_dir))
        except CL.LugarErro as exc:
            return _erro(str(exc))

    @app.route("/criador-lugares/<lid>/mapa/gerar", methods=["POST"])
    def lugar_mapa(lid: str):
        _l(lid)
        c = request.get_json(silent=True) or {}
        try:
            return _ok(**CL.gerar_mapa(lid, int(c.get("n") or 2), str(c.get("correcao") or ""), base_dir))
        except (CL.LugarErro, ValueError) as exc:
            return _erro(str(exc))

    @app.route("/criador-lugares/<lid>/imagem/enviar", methods=["POST"])
    def lugar_imagem_enviar(lid: str):
        _l(lid)
        try:
            it = CL.enviar_imagem(lid, _img(), request.form.get("tipo") or "foto", base_dir, request.form.get("vista") or "")
            return _ok(id=it["id"])
        except CL.LugarErro as exc:
            return _erro(str(exc))

    @app.route("/criador-lugares/<lid>/imagem/<iid>/<acao>", methods=["POST"])
    def lugar_imagem_acao(lid: str, iid: str, acao: str):
        _l(lid)
        try:
            CL.acao_imagem(lid, iid, acao, base_dir)
            return _ok()
        except CL.LugarErro as exc:
            return _erro(str(exc))

    @app.route("/criador-lugares/<lid>/arquivo/<pasta>/<nome>", methods=["GET"])
    def lugar_arquivo(lid: str, pasta: str, nome: str):
        if pasta not in ("refs", "fotos", "mapa"):
            abort(404)
        cam = os.path.join(CL.pasta(lid, base_dir), pasta, os.path.basename(nome))
        if not os.path.isfile(cam):
            abort(404)
        return send_file(cam)

    @app.route("/criador-lugares/<lid>/mapa-com-pinos.png", methods=["GET"])
    def lugar_mapa_pinos(lid: str):
        p = _l(lid)
        try:
            return send_file(io.BytesIO(CL.mapa_com_pinos(p, base_dir)), mimetype="image/png", as_attachment=True,
                             download_name=f"{C._slug(p['nome'])}_mapa.png")
        except CL.LugarErro:
            abort(404)

    @app.route("/criador-lugares/<lid>/zip", methods=["GET"])
    def lugar_zip(lid: str):
        p = _l(lid)
        return send_file(io.BytesIO(CL.zip_lugar(lid, base_dir)), mimetype="application/zip", as_attachment=True,
                         download_name=f"{C._slug(p['nome'])}.zip")

    @app.route("/criador-lugares/<lid>/excluir", methods=["POST"])
    def lugar_excluir(lid: str):
        p = _l(lid)
        CL.excluir(lid, base_dir)
        return redirect(f"/criador-lugares/{p['pai']}" if p.get("pai") else "/criador-personagens#lugares")
