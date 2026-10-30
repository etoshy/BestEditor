"""explicador_rotas.py — 🎬 a aba Explicador animado (v84_278). A lógica fica no explicador.py."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

from flask import abort, jsonify, redirect, render_template, request, send_file, send_from_directory

import explicador as X

TAREFAS: Dict[str, Dict[str, Any]] = {}
_CANCELAR: set = set()
_TRAVA_T = threading.Lock()
CB: Dict[str, Any] = {}


def registrar(app, base_dir: str, criar_job: Optional[Callable[[str, Dict[str, Any]], None]] = None,
              pasta_job: Optional[Callable[[str], str]] = None, transcrever: Optional[Callable[..., Any]] = None) -> None:
    CB.update(criar_job=criar_job, pasta_job=pasta_job, transcrever=transcrever)

    def _ok(**kw: Any):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: str, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _p(pid: str) -> Dict[str, Any]:
        try:
            return X.carregar(pid, base_dir)
        except X.ExplicadorErro:
            abort(404)

    def _rodar(pid: str, rotulo: str, fn: Callable[[Callable[[str], None], Callable[[], bool]], Any]):
        with _TRAVA_T:
            t = TAREFAS.get(pid)
            if t and not t.get("fim"):
                return jsonify({"ok": False, "erro": f"Já está rodando: {t['rotulo']} (⏹ parar, se travou)"}), 409
            _CANCELAR.discard(pid)
            TAREFAS[pid] = {"rotulo": rotulo, "inicio": time.time(), "fim": None, "erro": None, "prog": "", "res": None}

        def prog(m: str) -> None:
            TAREFAS[pid]["prog"] = str(m)[:300]

        def corpo() -> None:
            try:
                r = fn(prog, lambda: pid in _CANCELAR)
                TAREFAS[pid]["res"] = r if isinstance(r, (dict, str)) else None
            except Exception as exc:  # noqa: BLE001
                TAREFAS[pid]["erro"] = str(exc)[:600]
            finally:
                TAREFAS[pid]["fim"] = time.time()
        threading.Thread(target=corpo, daemon=True, name="explicador:" + pid).start()
        return _ok(tarefa=pid)

    def _estado(p: Dict[str, Any]) -> Dict[str, Any]:
        t = TAREFAS.get(p["id"])
        md = os.path.join(X.pasta(p["id"], base_dir), "midia")
        midia = sorted(f for f in os.listdir(md) if not f.endswith(".info.json")) if os.path.isdir(md) else []
        return {"projeto": {k: p.get(k) for k in ("id", "titulo", "duracao", "op", "plano", "saida", "editor", "musica_arquivo", "log", "trechos")},
                "midia": midia,
                "n_legenda": len(p.get("segs") or []), "resumo": X.resumo(p) if (p.get("plano") or {}).get("cenas") else {"cenas": [], "avisos": []},
                "tarefa": dict(t, rodando=not t.get("fim")) if t else None,
                "transcrever": bool(CB.get("transcrever")), "editor_ok": bool(CB.get("criar_job"))}

    # ------------------------------------------------------------------ páginas
    @app.route("/explicador")
    def explicador_lista():
        return render_template("explicador.html", p=None, projetos=X.listar(base_dir))

    @app.route("/explicador/<pid>")
    def explicador_projeto(pid: str):
        p = _p(pid)
        return render_template("explicador.html", p=p, projetos=[], tipos=X.TIPOS_DOC, fundos=list(X.FUNDOS))

    @app.route("/explicador/novo", methods=["POST"])
    def explicador_novo():
        arq = request.files.get("audio")
        if not arq or not arq.filename:
            return redirect("/explicador?erro=Suba a narração (wav/mp3/m4a).")
        tmp = tempfile.mkdtemp(prefix="expl_")
        cam = os.path.join(tmp, "narracao" + (os.path.splitext(arq.filename)[1].lower() or ".wav"))
        arq.save(cam)
        srt = ""
        s = request.files.get("srt")
        if s and s.filename:
            srt = s.read().decode("utf-8", "replace")
        try:
            p = X.novo(base_dir, request.form.get("titulo") or os.path.splitext(arq.filename)[0], cam, srt)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        with X._TRAVA:
            p = X.carregar(p["id"], base_dir)
            for k in ("marca1", "marca2"):
                if request.form.get(k):
                    p["op"][k] = request.form[k][:30]
            X.salvar(p, base_dir)
        return redirect(f"/explicador/{p['id']}")

    @app.route("/explicador/<pid>/estado")
    def explicador_estado(pid: str):
        return _ok(**_estado(_p(pid)))

    @app.route("/explicador/<pid>/salvar", methods=["POST"])
    def explicador_salvar(pid: str):
        b = request.get_json(silent=True) or {}
        with X._TRAVA:
            p = _p(pid)
            if b.get("titulo"):
                p["titulo"] = str(b["titulo"])[:120]
            if isinstance(b.get("op"), dict):
                op = dict(p["op"])
                for k, v in b["op"].items():
                    if k in X.opcoes_padrao():
                        op[k] = v
                op["resolucao"] = op["resolucao"] if op.get("resolucao") in X.RESOLUCOES else "2160p"
                op["fundo"] = op["fundo"] if op.get("fundo") in X.FUNDOS else "verde"
                try:
                    op["trabalhadores"] = max(1, min(6, int(op.get("trabalhadores") or 2)))
                    op["volume_musica"] = max(0.0, min(1.0, float(op.get("volume_musica") or 0)))
                except (TypeError, ValueError):
                    pass
                p["op"] = op
            if "trechos" in b:
                try:
                    tr = json.loads(b["trechos"]) if isinstance(b["trechos"], str) else b["trechos"]
                except ValueError as exc:
                    return _erro(f"Os trechos não são um JSON válido: {exc}")
                if not isinstance(tr, list):
                    return _erro("Os trechos precisam ser uma lista [...]")
                p["trechos"] = [x for x in tr if isinstance(x, dict) and x.get("arquivo") and x.get("antes_de") not in (None, "")]
            if "plano" in b:
                try:
                    pl = json.loads(b["plano"]) if isinstance(b["plano"], str) else b["plano"]
                except ValueError as exc:
                    return _erro(f"O plano não é um JSON válido: {exc}")
                if isinstance(pl, list):
                    pl = {"cenas": pl}
                if not isinstance(pl, dict) or not isinstance(pl.get("cenas"), list):
                    return _erro('O plano precisa ser {"cenas": [...]}')
                p["plano"] = {"cenas": pl["cenas"]}
            X.salvar(p, base_dir)
        return _ok(**_estado(p))

    @app.route("/explicador/<pid>/srt", methods=["POST"])
    def explicador_srt(pid: str):
        s = request.files.get("srt")
        if not s or not s.filename:
            return _erro("Escolha o .srt")
        segs = X.ler_srt(s.read().decode("utf-8", "replace"))
        if not segs:
            return _erro("Não achei nenhuma legenda nesse arquivo.")
        with X._TRAVA:
            p = _p(pid)
            p["segs"] = segs
            X.log(p, f"📝 legenda: {len(segs)} trechos")
            X.salvar(p, base_dir)
        return _ok(**_estado(p))

    @app.route("/explicador/<pid>/transcrever", methods=["POST"])
    def explicador_transcrever(pid: str):
        p = _p(pid)
        if not CB.get("transcrever"):
            return _erro("O Whisper não está disponível aqui — suba o .srt.")

        def fn(prog, _parar):
            prog("🎙 transcrevendo a narração (Whisper, palavra por palavra)…")
            res = CB["transcrever"](X.caminho_audio(p, base_dir), language=p["op"].get("idioma") or None, word_timestamps=True)
            segs = X.segs_de_whisper(res)
            if not segs:
                raise X.ExplicadorErro("O Whisper não devolveu texto.")
            with X._TRAVA:
                q = X.carregar(pid, base_dir)
                q["segs"] = segs
                X.log(q, f"🎙 Whisper: {len(segs)} palavras")
                X.salvar(q, base_dir)
            return {"n": len(segs)}
        return _rodar(pid, "🎙 transcrever", fn)

    @app.route("/explicador/<pid>/musica", methods=["POST"])
    def explicador_musica(pid: str):
        arq = request.files.get("musica")
        if not arq or not arq.filename:
            return _erro("Escolha o arquivo de música")
        nome = "musica" + (os.path.splitext(arq.filename)[1].lower() or ".mp3")
        arq.save(os.path.join(X.pasta(pid, base_dir), nome))
        with X._TRAVA:
            p = _p(pid)
            p["musica_arquivo"] = nome
            p["op"]["musica"] = "arquivo"
            X.salvar(p, base_dir)
        return _ok(**_estado(p))

    @app.route("/explicador/<pid>/ia", methods=["POST"])
    def explicador_ia(pid: str):
        _p(pid)
        instr = str((request.get_json(silent=True) or {}).get("instrucoes") or "")
        return _rodar(pid, "🤖 plano com a IA", lambda prog, _parar: X.plano_ia(pid, base_dir, instr, prog=prog))

    @app.route("/explicador/<pid>/plano_pronto", methods=["POST"])
    def explicador_plano_pronto(pid: str):
        qual = str((request.get_json(silent=True) or {}).get("qual") or "simples")
        with X._TRAVA:
            p = _p(pid)
            if qual == "exemplo_poker":
                with open(os.path.join(X.AQUI, "assets", "explicador", "exemplo_poker.json"), encoding="utf-8") as f:
                    p["plano"] = json.load(f)
            else:
                if not p.get("segs"):
                    return _erro("Falta a legenda.")
                p["plano"] = X.plano_simples(p)
            X.salvar(p, base_dir)
        return _ok(**_estado(p))

    # ------------------------------------------------------------------ 👁 prévia (a mesma página, com o áudio)
    @app.route("/explicador/fontes/<path:arq>")
    def explicador_fontes(arq: str):
        return send_from_directory(os.path.join(X.AQUI, "assets", "fonts", "dp"), arq)

    @app.route("/explicador/<pid>/audio")
    def explicador_audio(pid: str):
        p = _p(pid)
        try:
            cam = X.audio_final(p, base_dir)
        except Exception:  # noqa: BLE001
            cam = X.caminho_audio(p, base_dir)
        return send_file(cam, conditional=True)

    @app.route("/explicador/<pid>/midia", methods=["POST"])
    def explicador_midia_enviar(pid: str):
        _p(pid)
        md = os.path.join(X.pasta(pid, base_dir), "midia")
        os.makedirs(md, exist_ok=True)
        n = 0
        for arq in request.files.getlist("arquivos"):
            if not arq or not arq.filename:
                continue
            nome = os.path.basename(arq.filename).replace(" ", "_")
            if os.path.splitext(nome)[1].lower() not in (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".mkv", ".webm", ".m4v"):
                continue
            arq.save(os.path.join(md, nome))
            n += 1
        return _ok(enviados=n, **_estado(_p(pid)))

    @app.route("/explicador/<pid>/midia/<path:arq>")
    def explicador_midia(pid: str, arq: str):
        _p(pid)
        return send_from_directory(os.path.join(X.pasta(pid, base_dir), "midia"), arq, conditional=True)

    @app.route("/explicador/<pid>/cache/<h>/<arq>")
    def explicador_cache(pid: str, h: str, arq: str):
        _p(pid)
        return send_from_directory(os.path.join(X.pasta(pid, base_dir), "cache", os.path.basename(h)), arq, max_age=86400)

    @app.route("/explicador/<pid>/preparar", methods=["POST"])
    def explicador_preparar(pid: str):
        p = _p(pid)

        def fn(prog, _parar):
            X.escrever_tela(X.carregar(pid, base_dir), base_dir, previa=True, audio_url=f"/explicador/{pid}/audio", fontes="/explicador/fontes", prog=prog)
            return {}
        return _rodar(p["id"], "🎞 preparar trechos de vídeo e áudio", fn)

    @app.route("/explicador/<pid>/previa/")
    @app.route("/explicador/<pid>/previa/index.html")
    def explicador_previa(pid: str):
        p = _p(pid)
        try:
            d, _C = X.escrever_tela(p, base_dir, previa=True, audio_url=f"/explicador/{pid}/audio", fontes="/explicador/fontes")
        except X.ExplicadorErro as exc:
            return f"<body style='font:16px system-ui;color:#eee;background:#111;padding:20px'>⚠ {exc}</body>"
        return send_file(os.path.join(d, "index.html"), max_age=0)

    @app.route("/explicador/<pid>/previa/maos/<arq>")
    def explicador_previa_mao(pid: str, arq: str):
        _p(pid)
        return send_from_directory(os.path.join(X.pasta(pid, base_dir), "tela_previa", "maos"), arq, max_age=0)

    # ------------------------------------------------------------------ 🎞 renderizar · ⬇ baixar · 🎬 editor
    @app.route("/explicador/<pid>/renderizar", methods=["POST"])
    def explicador_renderizar(pid: str):
        p = _p(pid)
        if not (p.get("plano") or {}).get("cenas"):
            return _erro("Monte o plano primeiro.")
        return _rodar(pid, "🎞 renderizar", lambda prog, parar: X.renderizar(pid, base_dir, prog, parar))

    @app.route("/explicador/<pid>/mp4")
    def explicador_mp4(pid: str):
        p = _p(pid)
        mp4 = (p.get("saida") or {}).get("mp4")
        cam = os.path.join(X.pasta(pid, base_dir), "saida", mp4 or "_")
        if not mp4 or not os.path.isfile(cam):
            abort(404)
        return send_file(cam, as_attachment=bool(request.args.get("baixar")), download_name=mp4, conditional=True)

    @app.route("/explicador/<pid>/editor", methods=["POST"])
    def explicador_editor(pid: str):
        p = _p(pid)
        if not CB.get("criar_job") or not CB.get("pasta_job"):
            return _erro("O editor não está disponível aqui.")
        job_id = uuid.uuid4().hex[:12]
        jd = CB["pasta_job"](job_id)
        os.makedirs(jd, exist_ok=True)
        try:
            m = X.montar_editor(p, base_dir, jd)
        except X.ExplicadorErro as exc:
            import shutil
            shutil.rmtree(jd, ignore_errors=True)
            return _erro(str(exc))
        nome = f"🎬 {p['titulo']}"[:60]
        job = {"job_id": job_id, "audio_path": m["audio"], "music_path": m["musica"], "music_volume": 1.0 if m["musica"] else 0.18,
               "providers": [], "add_word_captions": False, "caption_style": {}, "status": "pronto_para_editar", "created_at": time.time(),
               "cancel_requested": False, "original_filename": nome, "nome_projeto": nome, "segments": [], "pending_segments": m["segmentos"],
               "segment_previews": [{"ok": True, "thumbnail_url": f"/job/{job_id}/segment-thumb/{k}", "provider": "material",
                                     "label": s["query"], "media_type": "video"} for k, s in enumerate(m["segmentos"])],
               "overlays": [], "total_duration": m["duracao"], "prompt": "", "whisper_skipped": True, "orientation": "16:9",
               "export_quality": m["qualidade"], "interval_seconds": 7, "explicador": {"projeto": pid}}
        CB["criar_job"](job_id, job)
        with X._TRAVA:
            q = _p(pid)
            q["editor"] = {"job_id": job_id, "quando": time.time()}
            X.log(q, f"🎬 mandado pro editor ({len(m['segmentos'])} cenas)")
            X.salvar(q, base_dir)
        return _ok(link=f"/job/{job_id}/edit-segments", job_id=job_id)

    @app.route("/explicador/<pid>/excluir", methods=["POST"])
    def explicador_excluir(pid: str):
        _p(pid)
        X.excluir(pid, base_dir)
        return redirect("/explicador")

    @app.route("/explicador/<pid>/tarefa")
    def explicador_tarefa(pid: str):
        t = TAREFAS.get(pid)
        return _ok(tarefa=dict(t, rodando=not t.get("fim")) if t else None)

    @app.route("/explicador/<pid>/parar", methods=["POST"])
    def explicador_parar(pid: str):
        _CANCELAR.add(pid)
        return _ok()
