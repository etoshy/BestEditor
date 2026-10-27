"""
Rotas do 🎬 Anime quadro a quadro (ver anime_cine.py). `registrar(app, base_dir, criar_job, pasta_job, tts, limpar_tts)`.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

from flask import abort, jsonify, redirect, render_template, request, send_file

import anime_cine as AC

TAREFAS: Dict[str, Dict[str, Any]] = {}
_ULTIMO: Dict[str, float] = {}


def registrar(app, base_dir: str, criar_job: Optional[Callable[[str, Dict[str, Any]], None]] = None,
              pasta_job: Optional[Callable[[str], str]] = None, tts: Optional[Callable[..., Any]] = None,
              limpar_tts: Optional[Callable[[str, str], str]] = None) -> None:

    def _p(pid: str) -> Dict[str, Any]:
        try:
            return AC.carregar(pid, base_dir)
        except AC.CineErro:
            abort(404)

    def _ok(**kw: Any):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: str, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _img():
        from PIL import Image
        f = request.files.get("arquivo")
        if not f or not f.filename:
            raise AC.CineErro("Escolha a imagem.")
        try:
            im = Image.open(f.stream)
            im.load()
            return im
        except Exception:  # noqa: BLE001
            raise AC.CineErro("Isso não é uma imagem.")

    def _mexer(pid: str, fn: Callable[[Dict[str, Any]], Any]):
        try:
            with AC._TRAVA:
                p = _p(pid)
                r = fn(p)
                AC.salvar(p, base_dir)
            return _ok(**(r if isinstance(r, dict) else {}))
        except AC.CineErro as exc:
            return _erro(str(exc))

    def _rodar(pid: str, rotulo: str, fn: Callable[[Callable[[str], None]], Any]):
        t = TAREFAS.get(pid)
        if t and not t.get("fim"):
            return _erro(f"Espere terminar: {t['rotulo']}", 409)
        TAREFAS[pid] = {"rotulo": rotulo, "inicio": time.time(), "fim": None, "erro": None, "msg": "", "prog": ""}

        def prog(m: str) -> None:
            TAREFAS[pid]["prog"] = m

        def corpo():
            try:
                r = fn(prog)
                TAREFAS[pid]["msg"] = r if isinstance(r, str) else ""
            except Exception as exc:  # noqa: BLE001
                TAREFAS[pid]["erro"] = str(exc)[:500]
            finally:
                TAREFAS[pid]["fim"] = time.time()
        threading.Thread(target=corpo, daemon=True).start()
        return _ok(tarefa=True)

    @app.context_processor
    def _ctx_cine():
        return {"anime_cine_lista": lambda: AC.listar(base_dir)}

    @app.route("/anime-cine/novo", methods=["POST"])
    def cine_novo():
        f = request.form
        p = AC.criar(f.get("titulo") or "", base_dir, roteiro=f.get("roteiro") or "", duracao=f.get("duracao") or 15,
                     estilo=f.get("estilo") or "anime", proporcao=f.get("proporcao") or "16:9")
        for arq in request.files.getlist("paginas")[:12]:
            if arq and arq.filename:
                try:
                    from PIL import Image
                    im = Image.open(arq.stream)
                    im.load()
                    AC.guardar_pagina(p, im, base_dir)
                except Exception:  # noqa: BLE001
                    continue
        AC.salvar(p, base_dir)
        return redirect(f"/anime-cine/{p['id']}")

    @app.route("/anime-cine/<pid>", methods=["GET"])
    def cine_pagina(pid: str):
        import criador_personagens as C
        p = _p(pid)
        try:
            import criador_lugares as CL
            lugares = CL.listar(base_dir)
        except Exception:  # noqa: BLE001
            lugares = []
        try:
            import anime2d as A
            vozes = A.vozes_disponiveis(p["entrada"].get("motor_perfil") or "xtts")
        except Exception:  # noqa: BLE001
            vozes = []
        return render_template("anime_cine.html", p=p, estilos=C.ESTILOS, fontes=AC.fontes_personagens(base_dir),
                               lugares=lugares, vozes=vozes, tipos={k: v[0] for k, v in AC.TIPOS_PLANO.items()},
                               cameras=AC.CAMERAS, efeitos=AC.EFEITOS, transicoes=AC.TRANSICOES,
                               sfx={k: v[0] for k, v in AC.SFX.items()}, tem_tts=bool(tts))

    @app.route("/anime-cine/<pid>/estado", methods=["GET"])
    def cine_estado(pid: str):
        _p(pid)
        if time.time() - _ULTIMO.get(pid, 0) > 2.5:
            _ULTIMO[pid] = time.time()
            try:
                AC.acompanhar(pid, base_dir)
            except Exception:  # noqa: BLE001
                pass
        out = AC.para_tela(AC.carregar(pid, base_dir), base_dir)
        out["tarefa"] = TAREFAS.get(pid)
        return jsonify(out)

    @app.route("/anime-cine/<pid>/dados", methods=["POST"])
    def cine_dados(pid: str):
        return _mexer(pid, lambda p: AC.editar_entrada(p, request.get_json(silent=True) or {}))

    @app.route("/anime-cine/<pid>/pagina", methods=["POST"])
    def cine_pagina_up(pid: str):
        try:
            im = _img()
        except AC.CineErro as exc:
            return _erro(str(exc))
        return _mexer(pid, lambda p: {"arquivo": AC.guardar_pagina(p, im, base_dir)})

    @app.route("/anime-cine/<pid>/pagina/<arq>/apagar", methods=["POST"])
    def cine_pagina_del(pid: str, arq: str):
        def fn(p):
            p["entrada"]["paginas"] = [x for x in p["entrada"]["paginas"] if x != arq]
        return _mexer(pid, fn)

    @app.route("/anime-cine/<pid>/cenario-img", methods=["POST"])
    def cine_cenario_img(pid: str):
        if (request.get_json(silent=True) or {}).get("apagar"):
            return _mexer(pid, lambda p: p["entrada"].update(lugar_img=""))
        try:
            im = _img()
        except AC.CineErro as exc:
            return _erro(str(exc))
        return _mexer(pid, lambda p: p["entrada"].update(lugar_img=AC._guardar_img(p, im, "refs", "cenario", base_dir, 2000)))

    @app.route("/anime-cine/<pid>/personagem/importar", methods=["POST"])
    def cine_pers_importar(pid: str):
        fonte = str((request.get_json(silent=True) or {}).get("fonte") or "")
        return _mexer(pid, lambda p: {"personagem": AC.importar_personagem(p, fonte, base_dir)})

    @app.route("/anime-cine/<pid>/personagem/seu", methods=["POST"])
    def cine_pers_seu(pid: str):
        try:
            im = _img()
        except AC.CineErro as exc:
            return _erro(str(exc))
        return _mexer(pid, lambda p: {"personagem": AC.personagem_seu(p, im, request.form.get("nome") or "",
                                                                      request.form.get("aparencia") or "", base_dir)})

    @app.route("/anime-cine/<pid>/personagem/<cid>", methods=["POST"])
    def cine_pers_editar(pid: str, cid: str):
        return _mexer(pid, lambda p: AC.editar_personagem(p, cid, request.get_json(silent=True) or {}, base_dir))

    @app.route("/anime-cine/<pid>/planejar", methods=["POST"])
    def cine_planejar(pid: str):
        _p(pid)
        return _rodar(pid, "🤖 planejando os planos", lambda _prog: AC.planejar(pid, base_dir))

    @app.route("/anime-cine/<pid>/planos", methods=["POST"])
    def cine_planos(pid: str):
        return _mexer(pid, lambda p: AC.salvar_planos(p, (request.get_json(silent=True) or {}).get("planos") or []))

    @app.route("/anime-cine/<pid>/chaves", methods=["POST"])
    def cine_chaves(pid: str):
        _p(pid)
        c = request.get_json(silent=True) or {}
        try:
            return _ok(**AC.gerar_chaves(pid, c.get("plids") or None, str(c.get("correcao") or ""), base_dir))
        except AC.CineErro as exc:
            return _erro(str(exc))

    @app.route("/anime-cine/<pid>/sequencia", methods=["POST"])
    def cine_sequencia(pid: str):
        _p(pid)
        try:
            return _ok(**AC.gerar_sequencia(pid, (request.get_json(silent=True) or {}).get("plids") or None, base_dir))
        except AC.CineErro as exc:
            return _erro(str(exc))

    @app.route("/anime-cine/<pid>/plano/<plid>/chave", methods=["POST"])
    def cine_chave_ok(pid: str, plid: str):
        _p(pid)
        try:
            AC.aprovar_chave(pid, plid, (request.get_json(silent=True) or {}).get("ok", True) is not False, base_dir)
            return _ok()
        except AC.CineErro as exc:
            return _erro(str(exc))

    @app.route("/anime-cine/<pid>/quadro/<plid>/<qid>/<acao>", methods=["POST"])
    def cine_quadro(pid: str, plid: str, qid: str, acao: str):
        _p(pid)
        c = request.get_json(silent=True) or {}
        try:
            if acao == "refazer":
                return _ok(**AC.refazer_quadro(pid, plid, qid, str(c.get("correcao") or ""), base_dir))
            if acao == "enviar":
                AC.enviar_desenho(pid, plid, qid, _img(), base_dir)
                return _ok()
            if acao == "versao":
                AC.escolher_versao(pid, plid, qid, str(c.get("arquivo") or ""), base_dir)
                return _ok()
        except AC.CineErro as exc:
            return _erro(str(exc))
        abort(404)

    @app.route("/anime-cine/<pid>/vozes", methods=["POST"])
    def cine_vozes(pid: str):
        _p(pid)
        if not tts:
            return _erro("O gerador de voz não está disponível aqui.")
        return _rodar(pid, "🎙 gerando as vozes", lambda prog: (
            lambda r: f"{r['feitas']} fala(s)" + (f" · {r['sem_voz']} sem voz escolhida" if r["sem_voz"] else "")
            + (f" · ❌ {r['erros'][0]}" if r["erros"] else ""))(AC.gerar_vozes(pid, base_dir, tts, limpar_tts or (lambda t, m: t), prog)))

    @app.route("/anime-cine/<pid>/previa/<plid>", methods=["POST"])
    def cine_previa(pid: str, plid: str):
        _p(pid)
        return _rodar(pid, "▶ prévia do plano", lambda prog: AC.montar(pid, base_dir, [plid], 0.5, prog))

    @app.route("/anime-cine/<pid>/montar", methods=["POST"])
    def cine_montar(pid: str):
        _p(pid)
        return _rodar(pid, "🎬 montando a cena", lambda prog: AC.montar(pid, base_dir, None, 1.0, prog))

    @app.route("/anime-cine/<pid>/arquivo/<sub>/<nome>", methods=["GET"])
    def cine_arquivo(pid: str, sub: str, nome: str):
        if sub not in ("refs", "quadros", "saida"):
            abort(404)
        cam = os.path.join(AC.pasta(pid, base_dir), sub, os.path.basename(nome))
        if not os.path.isfile(cam):
            abort(404)
        return send_file(cam, conditional=True)

    @app.route("/anime-cine/<pid>/editor", methods=["POST"])
    def cine_editor(pid: str):
        p = _p(pid)
        mp4 = (p.get("saida") or {}).get("mp4")
        cam = os.path.join(AC.pasta(pid, base_dir), "saida", mp4 or "_")
        if not mp4 or not os.path.isfile(cam) or not criar_job or not pasta_job:
            return _erro("Monte a cena primeiro (🎬 Montar).")
        job_id = uuid.uuid4().hex[:12]
        jd = pasta_job(job_id)
        os.makedirs(jd, exist_ok=True)
        audio = os.path.join(jd, "narracao.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", cam, "-vn", "-ac", "2", "-ar", "48000", audio], capture_output=True, timeout=300)
        dur = float((p.get("saida") or {}).get("dur") or AC.duracao_total(p))
        seg = {"start": 0.0, "end": round(dur, 3), "provider": "material", "query": f"🎬 {p['titulo']}"[:150],
               "on_screen_text": None, "media_type": "video", "zoom_direction": "static", "efeito": None,
               "override_source": {"source": "local_file", "value": cam, "kind": "video"}}
        job = {"job_id": job_id, "audio_path": audio, "music_path": None, "music_volume": 0.18, "providers": [],
               "add_word_captions": False, "caption_style": {}, "status": "pronto_para_editar", "created_at": time.time(),
               "cancel_requested": False, "original_filename": f"🎬 {p['titulo']}", "nome_projeto": f"🎬 {p['titulo']}"[:60],
               "segments": [], "pending_segments": [seg],
               "segment_previews": [{"ok": True, "thumbnail_url": f"/job/{job_id}/segment-thumb/0", "provider": "material",
                                     "label": "🎬 a cena animada", "media_type": "video"}],
               "overlays": [], "total_duration": dur, "prompt": "", "whisper_skipped": True,
               "orientation": p["entrada"]["proporcao"], "export_quality": "1080p", "interval_seconds": 7}
        criar_job(job_id, job)
        with AC._TRAVA:
            q = _p(pid)
            q["editor"] = {"job_id": job_id, "quando": time.time()}
            AC.salvar(q, base_dir)
        return _ok(link=f"/job/{job_id}/edit-segments")

    @app.route("/anime-cine/<pid>/excluir", methods=["POST"])
    def cine_excluir(pid: str):
        _p(pid)
        AC.excluir(pid, base_dir)
        return redirect("/modelos-video#animecine")
