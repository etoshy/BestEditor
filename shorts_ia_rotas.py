"""
Rotas da aba 🎌 Shorts de IA (ver shorts_ia.py).

`registrar(app, base_dir, transcrever)` — transcrever(audio, language=, word_timestamps=, info=) → segmentos do Whisper.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from typing import Any, Callable, Dict, Optional

from flask import abort, jsonify, redirect, render_template, request, send_file
from werkzeug.utils import secure_filename

import shorts_ia as SI

TAREFAS: Dict[str, Dict[str, Any]] = {}
CB: Dict[str, Any] = {}  # transcrever, chamar (IA), baixador — os testes trocam aqui
_TRAVA_T = threading.Lock()
_CANCELAR: set = set()  # ⏹ chaves de tarefa que você mandou parar (param no próximo passo)


def registrar(app, base_dir: str, transcrever: Optional[Callable[..., Any]] = None) -> None:
    CB.update(transcrever=transcrever)

    def _ok(**kw: Any):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: str, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _corpo() -> Dict[str, Any]:
        return request.get_json(silent=True) or {}

    def _rodar(chave: str, rotulo: str, fn: Callable[[Callable[[str], None]], Any]):
        with _TRAVA_T:
            t = TAREFAS.get(chave)
            if t and not t.get("fim"):
                # 409 com o que está rodando: a página mostra o progresso em vez de dar erro (e dá pra ⏹ parar)
                return jsonify({"ok": False, "ocupado": True, "erro": f"Já está rodando: {t['rotulo']}"
                                + (f" — {t['prog']}" if t.get("prog") else "") + " (⏹ parar, se travou)",
                                "tarefa": dict(t, rodando=True)}), 409
            _CANCELAR.discard(chave)
            TAREFAS[chave] = {"rotulo": rotulo, "inicio": time.time(), "fim": None, "erro": None, "msg": "", "prog": ""}

        def prog(m: str) -> None:
            if chave in _CANCELAR:
                raise SI.ShortsIAErro("⏹ parado por você")
            TAREFAS[chave]["prog"] = str(m)[:300]
            TAREFAS[chave]["prog_em"] = time.time()

        def corpo():
            try:
                r = fn(prog)
                TAREFAS[chave]["msg"] = r if isinstance(r, str) else ""
            except Exception as exc:  # noqa: BLE001
                TAREFAS[chave]["erro"] = str(exc)[:600]
            finally:
                TAREFAS[chave]["fim"] = time.time()
                try:
                    import gc
                    gc.collect()
                except Exception:  # noqa: BLE001
                    pass
        threading.Thread(target=corpo, daemon=True, name="shorts-ia:" + chave).start()
        return _ok(tarefa=chave)

    @app.route("/shorts-ia/tarefa/parar", methods=["POST"])
    def shorts_ia_tarefa_parar():
        """⏹ para a tarefa (exportar/modelar/analisar): ela para no próximo passo e a chave fica livre na hora."""
        chave = str(_corpo().get("chave") or "")
        t = TAREFAS.get(chave)
        if not t or t.get("fim"):
            return _ok(parada=False)
        _CANCELAR.add(chave)
        t.update(fim=time.time(), erro="⏹ parado por você")
        return _ok(parada=True)

    def _tarefa(chave: str) -> Optional[Dict[str, Any]]:
        t = TAREFAS.get(chave)
        return dict(t, rodando=not t.get("fim")) if t else None

    def _serie(sid: str) -> Dict[str, Any]:
        try:
            return SI.carregar_serie(base_dir, sid)
        except SI.ShortsIAErro:
            abort(404)

    def _ep(sid: str, eid: str) -> Dict[str, Any]:
        try:
            return SI.carregar_ep(base_dir, sid, eid)
        except SI.ShortsIAErro:
            abort(404)

    def _upload(campo: str = "arquivo") -> str:
        f = request.files.get(campo)
        if not f or not f.filename:
            raise SI.ShortsIAErro("Escolha um arquivo.")
        d = tempfile.mkdtemp(prefix="shorts_ia_up_")
        c = os.path.join(d, secure_filename(f.filename) or "arquivo")
        f.save(c)
        return c

    def _uploads(campo: str = "arquivo") -> list:
        out = []
        d = tempfile.mkdtemp(prefix="shorts_ia_up_")
        for k, f in enumerate(request.files.getlist(campo)[:SI.MAX_INSPIRACOES]):
            if f and f.filename:
                c = os.path.join(d, f"{k:02d}_{secure_filename(f.filename) or 'img.png'}")
                f.save(c)
                out.append(c)
        return out

    def _tentar(fn: Callable[[], Any]):
        try:
            r = fn()
            return _ok(**(r if isinstance(r, dict) else {}))
        except SI.ShortsIAErro as exc:
            return _erro(str(exc))
        except ValueError as exc:  # fila do Flow cheia
            return _erro(str(exc))

    # ------------------------------------------------------------------ páginas
    @app.route("/shorts-ia")
    def shorts_ia_hub():
        return render_template("shorts_ia.html", series=SI.series(base_dir), estilos=SI.ESTILOS, linguas=SI.LINGUAS,
                               proporcoes=SI.PROPORCOES)

    @app.route("/shorts-ia/nova", methods=["POST"])
    def shorts_ia_nova():
        f = request.form
        s = SI.nova_serie(base_dir, f.get("nome") or "", f.get("premissa") or "", f.get("estilo") or SI.ESTILO_PADRAO,
                          f.get("idioma") or "en", f.get("proporcao") or "9:16")
        if f.get("dur_plano") or f.get("modelo_video"):
            SI.atualizar_serie(base_dir, s["id"], {"padroes": {"dur_plano": f.get("dur_plano"), "modelo_video": f.get("modelo_video")}})
        imagens = []
        d = os.path.join(SI.pasta_serie(base_dir, s["id"]), "_entrada")
        for k, arq in enumerate(request.files.getlist("refs")[:8]):  # 🖼 suas imagens de referência → personagens
            if arq and arq.filename:
                os.makedirs(d, exist_ok=True)
                c = os.path.join(d, f"{k:02d}_{secure_filename(arq.filename) or 'img.png'}")
                arq.save(c)
                imagens.append(c)
        if f.get("gerar") == "1" or imagens:
            def fazer(prog):
                prog("🤖 a IA está criando o elenco" + (f" (olhando {len(imagens)} imagem(ns) suas)" if imagens else "") + "…")
                s2 = SI.gerar_universo(base_dir, s["id"], f.get("premissa") or "", CB.get("chamar"), imagens=imagens)
                if f.get("preparar") == "1":
                    prog("🧍📋🎙 pedindo referências, fichas e vozes…")
                    SI.preparar_personagens(base_dir, s["id"], [p["id"] for p in s2["elenco"]])
                return "universo pronto"
            _rodar("serie:" + s["id"], "🌌 criando o universo", fazer)
        return redirect(f"/shorts-ia/s/{s['id']}")

    @app.route("/shorts-ia/s/<sid>")
    def shorts_ia_serie(sid: str):
        s = _serie(sid)
        SI.sincronizar_serie(base_dir, sid)
        s = _serie(sid)
        return render_template("shorts_ia_serie.html", s=s, eps=[SI.resumo_ep(e) for e in SI.eps_da_serie(base_dir, s)],
                               estilos=SI.ESTILOS, linguas=SI.LINGUAS, proporcoes=SI.PROPORCOES, formatos=SI.FORMATOS_VIRAIS,
                               modelos_video=SI.MODELOS_VIDEO, modelos_imagem=SI.MODELOS_IMAGEM, modos_video=SI.MODOS_VIDEO,
                               formatos_serie=SI.FORMATOS_SERIE)

    @app.route("/shorts-ia/s/<sid>/personagem-da-imagem", methods=["POST"])
    def shorts_ia_personagem_img(sid: str):
        """➕ personagem a partir de uma imagem sua (a IA escreve o perfil; a imagem fica travada como referência)."""
        _serie(sid)
        imagens = _uploads()
        if not imagens:
            return _erro("Escolha a(s) imagem(ns).")
        nota = str(request.form.get("nota") or "")[:600]
        preparar = request.form.get("preparar") == "1"
        modo = "inspiracao" if request.form.get("modo") == "inspiracao" else "minha"

        def fazer(prog):
            prog(f"🤖 a IA está olhando {len(imagens)} imagem(ns)…")
            p = SI.personagem_da_imagem(base_dir, sid, imagens, nota, CB.get("chamar"), modo)
            if preparar:
                SI.preparar_personagens(base_dir, sid, [p["id"]])
            return f"➕ {p['nome']}"
        return _rodar("serie:" + sid, "➕ personagem da imagem", fazer)

    @app.route("/shorts-ia/s/<sid>/item/<iid>/inspiracoes", methods=["POST"])
    def shorts_ia_inspiracoes(sid: str, iid: str):
        """🖼 imagens de inspiração do personagem (várias de uma vez)."""
        _serie(sid)
        return _tentar(lambda: {"inspiracoes": SI.guardar_inspiracoes(base_dir, sid, iid, _uploads())})

    @app.route("/shorts-ia/s/<sid>/item/<iid>/inspiracao/<nome>/apagar", methods=["POST"])
    def shorts_ia_inspiracao_tirar(sid: str, iid: str, nome: str):
        _serie(sid)
        SI.tirar_inspiracao(base_dir, sid, iid, nome)
        return _ok()

    @app.route("/shorts-ia/s/<sid>/item/<iid>/refazer", methods=["POST"])
    def shorts_ia_refazer(sid: str, iid: str):
        """🔁 refaz tudo: perfil (IA olhando as imagens) → 🧍 referência (só no modo inspiração) → 📋 ficha → 🎙 voz."""
        _serie(sid)
        d = _corpo()
        modo = "inspiracao" if d.get("modo") == "inspiracao" else "referencia"
        com_foto = d.get("com_foto", True) is not False
        nota = str(d.get("nota") or "")[:600]

        def fazer(prog):
            prog("🤖 a IA está olhando as imagens e refazendo o perfil…")
            p = SI.refazer_personagem(base_dir, sid, iid, modo, nota, CB.get("chamar"), com_foto)
            return f"🔁 {p['nome']}: perfil novo — " + ("🧍 referência nova, 📋 ficha e 🎙 voz no Flow (sozinho)" if modo == "inspiracao"
                                                         else "📋 ficha e 🎙 voz refeitas a partir da referência")
        return _rodar("serie:" + sid, "🔁 refazendo o personagem", fazer)

    @app.route("/shorts-ia/s/<sid>/capitulo/premissa", methods=["POST"])
    def shorts_ia_cap_premissa(sid: str):
        """📖 a IA escreve a premissa do próximo capítulo (fica como rascunho na série pra você editar)."""
        _serie(sid)
        d = _corpo()
        ideia, quem, novos = str(d.get("ideia") or ""), [str(x) for x in d.get("quem") or []], d.get("novos", True) is not False

        def fazer(prog):
            prog("📖 escrevendo a premissa do capítulo…")
            pr = SI.gerar_premissa_capitulo(base_dir, sid, ideia, quem, novos, CB.get("chamar"))
            with SI.TRAVA:
                s2 = SI.carregar_serie(base_dir, sid)
                s2["rascunho_capitulo"] = pr
                SI.salvar_serie(base_dir, s2)
            return "📖 premissa pronta — confira e 🎬 crie o capítulo"
        return _rodar("serie:" + sid, "📖 premissa do capítulo", fazer)

    @app.route("/shorts-ia/s/<sid>/capitulo/criar", methods=["POST"])
    def shorts_ia_cap_criar(sid: str):
        _serie(sid)
        pr = _corpo().get("premissa") or {}
        try:
            e = SI.criar_capitulo(base_dir, sid, pr)
        except SI.ShortsIAErro as exc:
            return _erro(str(exc))
        with SI.TRAVA:
            s2 = SI.carregar_serie(base_dir, sid)
            s2.pop("rascunho_capitulo", None)
            SI.salvar_serie(base_dir, s2)
        _modelar(sid, e["id"], None)
        return _ok(ep=e["id"], url=f"/shorts-ia/s/{sid}/ep/{e['id']}")

    @app.route("/shorts-ia/s/<sid>/preparar", methods=["POST"])
    def shorts_ia_preparar(sid: str):
        """🧍📋🎙 referência → ficha → voz, em sequência e sozinho."""
        _serie(sid)
        ids = [str(x) for x in _corpo().get("ids") or [] if str(x).startswith("P")]
        return _tentar(lambda: SI.preparar_personagens(base_dir, sid, ids))

    @app.route("/shorts-ia/s/<sid>/estado")
    def shorts_ia_serie_estado(sid: str):
        _serie(sid)
        try:
            SI.sincronizar_serie(base_dir, sid)
        except Exception:  # noqa: BLE001 — Flow indisponível: mostra o que tem
            pass
        s = _serie(sid)
        return jsonify({"serie": s, "tarefa": _tarefa("serie:" + sid)})

    @app.route("/shorts-ia/s/<sid>/salvar", methods=["POST"])
    def shorts_ia_serie_salvar(sid: str):
        _serie(sid)
        return _tentar(lambda: {"serie": SI.atualizar_serie(base_dir, sid, _corpo())})

    @app.route("/shorts-ia/s/<sid>/apagar", methods=["POST"])
    def shorts_ia_serie_apagar(sid: str):
        import shutil
        _serie(sid)
        shutil.rmtree(SI.pasta_serie(base_dir, sid), ignore_errors=True)
        return redirect("/shorts-ia")

    @app.route("/shorts-ia/s/<sid>/universo", methods=["POST"])
    def shorts_ia_universo(sid: str):
        _serie(sid)
        premissa = str(_corpo().get("premissa") or "")
        return _rodar("serie:" + sid, "🌌 criando o universo",
                      lambda prog: (prog("🤖 a IA está criando o elenco…"),
                                    SI.gerar_universo(base_dir, sid, premissa, CB.get("chamar")), "universo pronto")[-1])

    @app.route("/shorts-ia/s/<sid>/ideias", methods=["POST"])
    def shorts_ia_ideias(sid: str):
        _serie(sid)
        n = int(_corpo().get("n") or 8)
        return _rodar("serie:" + sid, "💡 ideias de episódio",
                      lambda prog: (prog("🤖 pensando em episódios…"),
                                    f"{len(SI.gerar_ideias(base_dir, sid, n, CB.get('chamar')))} ideia(s) nova(s)")[-1])

    @app.route("/shorts-ia/s/<sid>/personagem", methods=["POST"])
    def shorts_ia_personagem(sid: str):
        _serie(sid)
        return _tentar(lambda: {"item": SI.salvar_personagem(base_dir, sid, _corpo())})

    @app.route("/shorts-ia/s/<sid>/cenario", methods=["POST"])
    def shorts_ia_cenario(sid: str):
        _serie(sid)
        return _tentar(lambda: {"item": SI.salvar_cenario(base_dir, sid, _corpo())})

    @app.route("/shorts-ia/s/<sid>/item/<iid>/apagar", methods=["POST"])
    def shorts_ia_item_apagar(sid: str, iid: str):
        _serie(sid)
        SI.apagar_item(base_dir, sid, "personagem" if iid.startswith("P") else "cenario", iid)
        return _ok()

    @app.route("/shorts-ia/s/<sid>/refs", methods=["POST"])
    def shorts_ia_refs(sid: str):
        """🧍 gera no Flow a referência isolada (personagem de corpo inteiro / cenário vazio)."""
        _serie(sid)
        d = _corpo()
        ids = [str(x) for x in d.get("ids") or []]
        return _tentar(lambda: SI.pedir_refs(base_dir, sid, ids, com_foto=bool(d.get("com_foto")), preparar=bool(d.get("preparar"))))

    @app.route("/shorts-ia/s/<sid>/estilo", methods=["POST"])
    def shorts_ia_estilo(sid: str):
        """🎨 a imagem que dita o traço (cenários seguem ela): arquivo seu, a referência de um personagem, ou padrão."""
        _serie(sid)
        try:
            if request.files.get("arquivo"):
                nome = SI.guardar_estilo_ref(base_dir, sid, _upload())
            else:
                nome = SI.guardar_estilo_ref(base_dir, sid, None, str(_corpo().get("de") or ""))
        except SI.ShortsIAErro as exc:
            return _erro(str(exc))
        return _ok(estilo_ref=nome)

    @app.route("/shorts-ia/s/<sid>/fichas", methods=["POST"])
    def shorts_ia_fichas(sid: str):
        """📋 a folha de personagem (várias vistas + expressões + nome/gênero/idade) no Flow, a partir da referência."""
        _serie(sid)
        ids = [str(x) for x in _corpo().get("ids") or []]
        return _tentar(lambda: SI.pedir_fichas(base_dir, sid, ids))

    @app.route("/shorts-ia/s/<sid>/vozes", methods=["POST"])
    def shorts_ia_vozes(sid: str):
        """🎙 o perfil de voz (IA) + a imagem da folha de voz de cada personagem."""
        _serie(sid)
        ids = [str(x) for x in _corpo().get("ids") or [] if str(x).startswith("P")]
        if not ids:
            return _erro("Escolha as personagens.")

        def fazer(prog):
            for k, pid in enumerate(ids, 1):
                prog(f"🎙 ficha de voz {k}/{len(ids)}…")
                SI.fazer_ficha_de_voz(base_dir, sid, pid, CB.get("chamar"))
            return f"🎙 {len(ids)} ficha(s) de voz"
        return _rodar("serie:" + sid, "🎙 fichas de voz", fazer)

    @app.route("/shorts-ia/s/<sid>/item/<iid>/ref", methods=["POST"])
    def shorts_ia_ref_enviar(sid: str, iid: str):
        _serie(sid)
        return _tentar(lambda: {"arquivo": SI.guardar_ref(base_dir, sid, iid, _upload())})

    @app.route("/shorts-ia/s/<sid>/arquivo/<path:arq>")
    def shorts_ia_arquivo(sid: str, arq: str):
        """Imagens/vídeos da série e dos episódios (refs/…, eps/<ep>/midia/…, quadros, export)."""
        _serie(sid)
        raiz = os.path.realpath(SI.pasta_serie(base_dir, sid))
        c = os.path.realpath(os.path.join(raiz, arq))
        if not c.startswith(raiz + os.sep) or not os.path.isfile(c) or c.endswith(".json"):
            abort(404)
        return send_file(c, conditional=True)

    # ------------------------------------------------------------------ episódios
    @app.route("/shorts-ia/s/<sid>/ep/novo", methods=["POST"])
    def shorts_ia_ep_novo(sid: str):
        _serie(sid)
        d = request.form if request.form else _corpo()
        e = SI.novo_ep(base_dir, sid, d.get("titulo") or "", d.get("url") or "", d.get("ideia") or "")
        if e["origem"]["url"]:
            _analisar(sid, e["id"])
        elif e["origem"]["tipo"] == "ideia" and d.get("modelar", "1") == "1":
            _modelar(sid, e["id"], None)
        if request.form:
            return redirect(f"/shorts-ia/s/{sid}/ep/{e['id']}")
        return _ok(ep=e["id"], url=f"/shorts-ia/s/{sid}/ep/{e['id']}")

    def _analisar(sid: str, eid: str, arquivo: str = ""):
        return _rodar("ep:" + eid, "📺 analisando o viral",
                      lambda prog: (SI.analisar_viral(base_dir, sid, eid, CB.get("transcrever"), CB.get("chamar"), CB.get("baixador"),
                                                      prog, arquivo), "storyboard pronto")[-1])

    def _modelar(sid: str, eid: str, notas: Optional[str]):
        return _rodar("ep:" + eid, "✍ modelando o episódio",
                      lambda prog: (prog("🤖 a IA está escrevendo as cenas…"),
                                    f"{len(SI.modelar(base_dir, sid, eid, notas, CB.get('chamar'))['cenas'])} cena(s)")[-1])

    @app.route("/shorts-ia/s/<sid>/ep/<eid>")
    def shorts_ia_ep(sid: str, eid: str):
        s = _serie(sid)
        _ep(sid, eid)
        try:
            SI.sincronizar_ep(base_dir, sid, eid)
        except Exception:  # noqa: BLE001
            pass
        e = _ep(sid, eid)
        return render_template("shorts_ia_ep.html", s=s, e=e, estilos=SI.ESTILOS, linguas=SI.LINGUAS, modos_video=SI.MODOS_VIDEO,
                               modelos_video=SI.MODELOS_VIDEO,
                               filtros=list(SI.FILTROS), qualidades=list(SI.QUALIDADES))

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/estado")
    def shorts_ia_ep_estado(sid: str, eid: str):
        _ep(sid, eid)
        try:
            SI.sincronizar_ep(base_dir, sid, eid)
        except Exception:  # noqa: BLE001
            pass
        e = _ep(sid, eid)
        return jsonify({"ep": e, "serie": _serie(sid), "tarefa": _tarefa("ep:" + eid)})

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/analisar", methods=["POST"])
    def shorts_ia_ep_analisar(sid: str, eid: str):
        e = _ep(sid, eid)
        arquivo = ""
        if request.files.get("arquivo"):
            try:
                arquivo = _upload()
            except SI.ShortsIAErro as exc:
                return _erro(str(exc))
        else:
            url = str(_corpo().get("url") or "").strip()
            if url and url != e["origem"].get("url"):
                with SI.TRAVA:
                    e = _ep(sid, eid)
                    e["origem"]["url"] = url[:600]
                    e["origem"]["tipo"] = "viral"
                    SI.salvar_ep(base_dir, e)
                v = os.path.join(SI.pasta_ep(base_dir, sid, eid), "origem.mp4")
                if os.path.isfile(v):
                    os.remove(v)  # link novo: baixa de novo
        return _analisar(sid, eid, arquivo)

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/papeis", methods=["POST"])
    def shorts_ia_ep_papeis(sid: str, eid: str):
        _ep(sid, eid)
        with SI.TRAVA:
            e = _ep(sid, eid)
            e["papeis"] = {str(k)[:20]: str(v)[:8] for k, v in (_corpo().get("papeis") or {}).items()}
            SI.salvar_ep(base_dir, e)
        return _ok()

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/modelar", methods=["POST"])
    def shorts_ia_ep_modelar(sid: str, eid: str):
        _ep(sid, eid)
        d = _corpo()
        if d.get("dur_plano") not in (None, ""):
            with SI.TRAVA:
                e = _ep(sid, eid)
                try:
                    e["dur_plano"] = round(max(2.0, min(SI.DUR_VIDEO_FLOW, float(d["dur_plano"]))), 1)
                except (TypeError, ValueError):
                    pass
                SI.salvar_ep(base_dir, e)
        return _modelar(sid, eid, d.get("notas") if "notas" in d else None)

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/cenas", methods=["POST"])
    def shorts_ia_ep_cenas(sid: str, eid: str):
        _ep(sid, eid)
        d = _corpo()
        if "titulo" in d:
            with SI.TRAVA:
                e = _ep(sid, eid)
                e["titulo"] = " ".join(str(d["titulo"] or "").split())[:140] or e["titulo"]
                SI.salvar_ep(base_dir, e)
        return _tentar(lambda: {"ep": SI.salvar_cenas(base_dir, sid, eid, d.get("cenas") or [])})

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/voltar", methods=["POST"])
    def shorts_ia_ep_voltar(sid: str, eid: str):
        _ep(sid, eid)
        return _tentar(lambda: {"ep": SI.voltar_cenas(base_dir, sid, eid)})

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/gerar", methods=["POST"])
    def shorts_ia_ep_gerar(sid: str, eid: str):
        _ep(sid, eid)
        d = _corpo()
        idx = [int(x) for x in d["cenas"]] if isinstance(d.get("cenas"), list) else None
        refazer = bool(d.get("refazer"))
        if d.get("o_que") == "videos":
            return _tentar(lambda: SI.pedir_videos(base_dir, sid, eid, idx, refazer))
        return _tentar(lambda: SI.pedir_imagens(base_dir, sid, eid, idx, refazer))

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/cena/<int:k>/<qual>", methods=["POST"])
    def shorts_ia_ep_enviar(sid: str, eid: str, k: int, qual: str):
        """Sua própria imagem (quadro A/B) ou vídeo pra cena."""
        _ep(sid, eid)
        try:
            c = _upload()
            if qual == "video":
                SI.usar_video_enviado(base_dir, sid, eid, k, c)
            else:
                SI.usar_imagem_enviada(base_dir, sid, eid, k, qual, c)
        except SI.ShortsIAErro as exc:
            return _erro(str(exc))
        return _ok()

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/edicao", methods=["POST"])
    def shorts_ia_ep_edicao(sid: str, eid: str):
        _ep(sid, eid)
        return _ok(edicao=SI.salvar_opcoes(base_dir, sid, eid, _corpo()))

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/musica", methods=["POST"])
    def shorts_ia_ep_musica(sid: str, eid: str):
        _ep(sid, eid)
        if request.form.get("tirar") == "1":
            return _ok(edicao=SI.salvar_opcoes(base_dir, sid, eid, {"musica": None}))
        try:
            f = request.files.get("arquivo")
            c = _upload()
            SI.guardar_musica(base_dir, sid, eid, c, f.filename if f else "musica.mp3")
        except SI.ShortsIAErro as exc:
            return _erro(str(exc))
        return _ok()

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/exportar", methods=["POST"])
    def shorts_ia_ep_exportar(sid: str, eid: str):
        _ep(sid, eid)
        d = _corpo()
        if d:
            SI.salvar_opcoes(base_dir, sid, eid, d)
        return _rodar("ep:" + eid, "📤 exportando",
                      lambda prog: (SI.exportar(base_dir, sid, eid, CB.get("transcrever"), prog), "✅ exportado")[-1])

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/video.mp4")
    def shorts_ia_ep_video(sid: str, eid: str):
        e = _ep(sid, eid)
        if not e.get("export"):
            abort(404)
        c = os.path.join(SI.pasta_ep(base_dir, sid, eid), "export", os.path.basename(e["export"]["arquivo"]))
        if not os.path.isfile(c):
            abort(404)
        nome = secure_filename(e["titulo"])[:60] or eid
        return send_file(c, as_attachment=request.args.get("baixar") == "1", download_name=f"{nome}.mp4", conditional=True)

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/cenas.zip")
    def shorts_ia_ep_zip(sid: str, eid: str):
        """⬇ todas as cenas (quadros e vídeos) em ordem: cena_01_A.png, cena_01_video.mp4…"""
        import io
        import zipfile
        e = _ep(sid, eid)
        md = os.path.join(SI.pasta_ep(base_dir, sid, eid), "midia")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            for k, cn in enumerate(e["cenas"], 1):
                for slot, rot in (("img_inicio", "A"), ("video", "video")):
                    arq = (cn.get(slot) or {}).get("arquivo")
                    c = os.path.join(md, os.path.basename(arq)) if arq else ""
                    if c and os.path.isfile(c):
                        z.write(c, f"cena_{k:02d}_{rot}{os.path.splitext(c)[1]}")
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f"{secure_filename(e['titulo'])[:50] or eid}_cenas.zip",
                         mimetype="application/zip")

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/titulos.txt")
    def shorts_ia_ep_titulos(sid: str, eid: str):
        e = _ep(sid, eid)
        return SI.texto_titulos(e), 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.route("/shorts-ia/s/<sid>/ep/<eid>/apagar", methods=["POST"])
    def shorts_ia_ep_apagar(sid: str, eid: str):
        _ep(sid, eid)
        SI.apagar_ep(base_dir, sid, eid)
        return redirect(f"/shorts-ia/s/{sid}")

    @app.route("/shorts-ia/flow/continuar", methods=["POST"])
    def shorts_ia_flow_continuar():
        aviso = SI._iniciar_lote()
        return _erro(aviso) if aviso else _ok()
