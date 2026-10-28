"""Rotas do 🎯 Rastrear objeto (ver rastreio.py).

`registrar(app, base_dir, clipe_do_trecho, aplicar_no_trecho)`:
  clipe_do_trecho(job_id, i) → caminho do vídeo do trecho i do Estúdio (baixa se precisar);
  aplicar_no_trecho(job_id, i, caminho) → o trecho passa a usar esse vídeo.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from typing import Any, Callable, Dict, Optional

from flask import abort, jsonify, redirect, render_template, request, send_file
from werkzeug.utils import secure_filename

import rastreio as RT

TAREFAS: Dict[str, Dict[str, Any]] = {}


def registrar(app, base_dir: str, clipe_do_trecho: Optional[Callable[[str, int], str]] = None,
              aplicar_no_trecho: Optional[Callable[[str, int, str], None]] = None) -> None:

    def _ok(**kw: Any):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: str, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _r(rid: str) -> Dict[str, Any]:
        try:
            return RT.carregar(base_dir, rid)
        except RT.RastreioErro:
            abort(404)

    def _rodar(chave: str, rotulo: str, fn: Callable[[Callable[[str], None]], Any]):
        t = TAREFAS.get(chave)
        if t and not t.get("fim"):
            return _erro(f"Espere terminar: {t['rotulo']}", 409)
        TAREFAS[chave] = {"rotulo": rotulo, "inicio": time.time(), "fim": None, "erro": None, "msg": "", "prog": ""}

        def prog(m: str) -> None:
            TAREFAS[chave]["prog"] = str(m)[:200]

        def corpo():
            try:
                r = fn(prog)
                TAREFAS[chave]["msg"] = r if isinstance(r, str) else ""
            except Exception as exc:  # noqa: BLE001
                TAREFAS[chave]["erro"] = str(exc)[:500]
            finally:
                TAREFAS[chave]["fim"] = time.time()
        threading.Thread(target=corpo, daemon=True).start()
        return _ok(tarefa=True)

    @app.route("/rastrear", methods=["GET"])
    def rastrear_hub():
        return render_template("rastrear_lista.html", lista=RT.listar(base_dir), erro=request.args.get("erro"))

    @app.route("/rastrear/novo", methods=["POST"])
    def rastrear_novo():
        arq = request.files.get("video")
        if not arq or not arq.filename:
            return redirect("/rastrear?erro=Escolha o vídeo.")
        tmp = os.path.join(tempfile.mkdtemp(prefix="rastreio_"), secure_filename(arq.filename) or "video.mp4")
        arq.save(tmp)
        try:
            r = RT.criar(base_dir, tmp, os.path.splitext(arq.filename)[0], mover=True)
        except RT.RastreioErro as exc:
            return redirect(f"/rastrear?erro={exc}")
        return redirect(f"/rastrear/{r['id']}")

    @app.route("/rastrear/do-editor", methods=["GET", "POST"])
    def rastrear_do_editor():
        """🎞 Do Estúdio: o vídeo do trecho vira um rastreio ligado a ele (o resultado volta pro trecho)."""
        job_id = str(request.values.get("job") or "")
        try:
            i = int(request.values.get("trecho"))
        except (TypeError, ValueError):
            return redirect("/rastrear?erro=Trecho inválido.")
        if not clipe_do_trecho:
            return redirect("/rastrear?erro=O editor não está disponível aqui.")
        for x in RT.listar(base_dir):  # já tem um rastreio desse trecho: abre ele
            if x.get("job") == job_id and x.get("trecho") == i:
                return redirect(f"/rastrear/{x['id']}")
        try:
            cam = clipe_do_trecho(job_id, i)
            r = RT.criar(base_dir, cam, f"Trecho {i + 1}", job=job_id, trecho=i)
        except Exception as exc:  # noqa: BLE001
            return redirect(f"/rastrear?erro={exc}")
        return redirect(f"/rastrear/{r['id']}")

    @app.route("/rastrear/<rid>", methods=["GET"])
    def rastrear_pagina(rid: str):
        return render_template("rastrear.html", r=_r(rid), tipos=RT.TIPOS, direcoes=RT.DIRECOES_SETA,
                               no_editor=bool(aplicar_no_trecho))

    @app.route("/rastrear/<rid>/estado", methods=["GET"])
    def rastrear_estado(rid: str):
        r = _r(rid)
        r["tarefa"] = TAREFAS.get(rid)
        r["estilo"] = RT.normalizar_estilo(r.get("estilo"))
        return jsonify(r)

    @app.route("/rastrear/<rid>/video", methods=["GET"])
    def rastrear_video(rid: str):
        return send_file(RT.caminho_video(base_dir, _r(rid)), conditional=True)

    @app.route("/rastrear/<rid>/saida.mp4", methods=["GET"])
    def rastrear_saida(rid: str):
        r = _r(rid)
        if not r.get("saida"):
            abort(404)
        return send_file(os.path.join(RT.pasta(base_dir, rid), r["saida"]), conditional=True,
                         as_attachment=bool(request.args.get("baixar")), download_name=f"rastreio_{rid}.mp4")

    @app.route("/rastrear/<rid>/salvar", methods=["POST"])
    def rastrear_salvar(rid: str):
        b = request.get_json(silent=True) or {}
        with RT._TRAVA:
            r = _r(rid)
            if isinstance(b.get("chaves"), list):
                ch = []
                for c in b["chaves"][:50]:
                    try:
                        cx = [max(0.0, float(v)) for v in c["caixa"]][:4]
                        if len(cx) == 4 and cx[2] >= 4 and cx[3] >= 4:
                            ch.append({"t": round(float(c["t"]), 3), "caixa": [round(v, 1) for v in cx]})
                    except (KeyError, TypeError, ValueError):
                        continue
                r["chaves"] = sorted(ch, key=lambda c: c["t"])
            if isinstance(b.get("faixa"), list) and len(b["faixa"]) == 2:
                try:
                    a, z = sorted(max(0.0, min(r["info"]["dur"], float(v))) for v in b["faixa"])
                    r["faixa"] = [round(a, 3), round(z, 3)]
                except (TypeError, ValueError):
                    pass
            if isinstance(b.get("estilo"), dict):
                r["estilo"] = RT.normalizar_estilo(b["estilo"])
            RT.salvar(base_dir, r)
        return _ok(r=r)

    @app.route("/rastrear/<rid>/rastrear", methods=["POST"])
    def rastrear_rodar(rid: str):
        r = _r(rid)
        if not r.get("chaves"):
            return _erro("Pause no quadro e desenhe uma caixa em volta do objeto.")
        preferir = str((request.get_json(silent=True) or {}).get("rastreador") or "auto")

        def fn(prog):
            q = RT.carregar(base_dir, rid)
            res = RT.rastrear(RT.caminho_video(base_dir, q), q["chaves"], q["faixa"][0], q["faixa"][1], q["info"]["fps"], prog,
                              preferir=preferir)
            with RT._TRAVA:
                q = RT.carregar(base_dir, rid)
                q["caixas"] = res
                RT.salvar(base_dir, q)
            perdido = res["total"] - res["achados"]
            cortes = res.get("cortes") or []
            return (f"objeto seguido em {res['achados']} de {res['total']} quadros ({res['rastreador']})"
                    + (f" — o vídeo troca de cena em {', '.join(f'{c:.2f} s' for c in cortes[:4])}: o rastreio para no corte; "
                       "pra continuar depois dele, desenhe uma caixa no plano novo" if cortes and perdido > res["total"] * 0.05 else
                       f" — perdeu {perdido}: pause onde escorregou e desenhe de novo" if perdido > res["total"] * 0.05 else ""))
        return _rodar(rid, "🎯 rastreando", fn)

    @app.route("/rastrear/<rid>/gerar", methods=["POST"])
    def rastrear_gerar(rid: str):
        _r(rid)
        return _rodar(rid, "🎬 gerando o vídeo", lambda prog: (RT.gerar(base_dir, rid, prog), "vídeo pronto")[1])

    @app.route("/rastrear/<rid>/aplicar", methods=["POST"])
    def rastrear_aplicar(rid: str):
        r = _r(rid)
        if not (r.get("job") and r.get("trecho") is not None):
            return _erro("Esse rastreio não veio de um trecho do editor.")
        if not r.get("saida") or not aplicar_no_trecho:
            return _erro("Gere o vídeo antes (🎬).")
        try:
            aplicar_no_trecho(r["job"], int(r["trecho"]), os.path.join(RT.pasta(base_dir, rid), r["saida"]))
        except Exception as exc:  # noqa: BLE001
            return _erro(str(exc))
        return _ok(link=f"/job/{r['job']}/edit-segments")

    @app.route("/rastrear/<rid>/excluir", methods=["POST"])
    def rastrear_excluir(rid: str):
        _r(rid)
        RT.excluir(base_dir, rid)
        return redirect("/rastrear")
