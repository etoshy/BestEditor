"""📐 v84_421 — páginas e rotas dos Formatos de vídeo (ver formatos_video.py)."""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, Optional

import formatos_video as FV


def registrar(app, base_dir: str) -> None:
    from flask import jsonify, render_template, request
    import dossies as ds
    FV.BASE = base_dir
    import dossies_rotas

    def _post(caminho: str, corpo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        r = app.test_client().post(caminho, json=corpo or {})
        d = r.get_json(silent=True) or {}
        if r.status_code >= 400 or d.get("erro"):
            raise RuntimeError(str(d.get("erro") or f"HTTP {r.status_code}"))
        return d

    def _esperar(tid: str, limite_s: float = 3600) -> None:
        import tarefas_bg
        t0 = time.time()
        while time.time() - t0 < limite_s:
            t = tarefas_bg.pegar(tid) or {}
            if t.get("status") and t["status"] != "rodando":
                tarefas_bg.marcar_aplicada(tid)
                if t["status"] != "pronto":
                    raise RuntimeError(t.get("erro") or "a tarefa falhou")
                return
            time.sleep(3)
        raise RuntimeError("demorou demais")

    def _modelos() -> Dict[str, Any]:
        return {k: m for k, m in ds.MODELOS.items() if m.get("formatos")}

    def _valido(modelo: str) -> bool:
        return modelo in ds.MODELOS

    @app.route("/formatos")
    def formatos_pagina():
        mods = _modelos()
        sel = request.args.get("modelo") or ""
        if sel not in mods:  # o primeiro que já tem ficha, senão o 1º da lista
            sel = next((k for k in mods if FV.carregar(base_dir, k).get("ficha")), next(iter(mods), ""))
        return render_template("formatos.html", modelos={k: ds.sem_emoji(m.get("nome") or k) for k, m in mods.items()},
                               sel=sel, r=FV.resumo(base_dir, sel) if sel else None)

    @app.route("/formatos/<modelo>/estado")
    def formatos_estado(modelo: str):
        if not _valido(modelo):
            return jsonify({"erro": "Modelo não encontrado."}), 404
        return jsonify({"ok": True, **FV.resumo(base_dir, modelo)})

    @app.route("/formatos/<modelo>/ativo", methods=["POST"])
    def formatos_ativo(modelo: str):
        """🔁 Liga/desliga o aprender sozinho. Ligar = lê TODOS os roteiros que faltam."""
        if not _valido(modelo):
            return jsonify({"erro": "Modelo não encontrado."}), 404
        ativo = bool((request.get_json(silent=True) or {}).get("ativo"))
        FV.mexer(base_dir, modelo, lambda d: d.update(ativo=ativo))
        tid = ""
        if ativo and FV.pendentes(base_dir, modelo) and not FV._RODANDO.get(FV._ok_chave(modelo)):
            tid = FV.iniciar_atualizacao(base_dir, modelo)
        return jsonify({"ok": True, "tarefa": tid, **FV.resumo(base_dir, modelo)})

    @app.route("/formatos/<modelo>/atualizar", methods=["POST"])
    def formatos_atualizar(modelo: str):
        """🔄 Analisa os roteiros novos (ou ♻ todos de novo) e refaz a ficha."""
        if not _valido(modelo):
            return jsonify({"erro": "Modelo não encontrado."}), 404
        import ia_servico as ia
        motivo = ia.motivo_desligado("roteiros")
        if motivo:
            return jsonify({"erro": "IA: " + motivo + " — ligue em 🤖 IA (📝 Roteiros direto na IA)."}), 400
        if FV._RODANDO.get(FV._ok_chave(modelo)):
            return jsonify({"erro": "Já está atualizando — espere terminar."}), 400
        refazer = bool((request.get_json(silent=True) or {}).get("refazer"))
        if not FV.roteiros(base_dir, modelo):
            return jsonify({"erro": "Esse modelo ainda não tem roteiro pronto (300+ palavras) pra aprender."}), 400
        FV.mexer(base_dir, modelo, lambda d: d.update(estado="analisando", msg="⏳ começando…"))
        return jsonify({"ok": True, "tarefa": FV.iniciar_atualizacao(base_dir, modelo, refazer)})

    @app.route("/formatos/<modelo>/salvar", methods=["POST"])
    def formatos_salvar(modelo: str):
        """✏ O texto da ficha editado à mão ("" = volta pro da IA) e o "usar nos roteiros"."""
        if not _valido(modelo):
            return jsonify({"erro": "Modelo não encontrado."}), 404
        c = request.get_json(silent=True) or {}

        def f(d):
            if "texto" in c:
                t = str(c.get("texto") or "").strip()
                d["texto_manual"] = "" if t == FV.texto_ficha(d.get("ficha")).strip() else t[:12000]
            if "usar" in c:
                d["usar"] = bool(c["usar"])
        FV.mexer(base_dir, modelo, f)
        return jsonify({"ok": True, **FV.resumo(base_dir, modelo)})

    # ------------------------------------------------------------------ 💡 vídeo só com um tema
    def _estado(modelo: str, cid: str, **campos) -> None:
        def f(d):
            for x in d.get("criados") or []:
                if x["id"] == cid:
                    x.update(campos)
        FV.mexer(base_dir, modelo, f)

    def _criar_do_tema(modelo: str, cid: str, tema: str, minutos: float, revisar: bool) -> None:
        try:
            _estado(modelo, cid, estado="pesquisa", msg="🌐 pesquisando o tema na internet…")
            notas = FV.pesquisar(base_dir, modelo, tema, progresso=lambda m: _estado(modelo, cid, msg=m))
            _estado(modelo, cid, estado="projeto", msg="📁 criando o projeto com as notas…")
            with dossies_rotas._TRAVA:
                p = ds.criar(base_dir, tema=tema, modelo=modelo)
                cfg = p["config"]
                if minutos:
                    cfg["minutos"] = float(minutos)
                ds.marcar_mudanca(p, "📐 formato", f"criado só com o tema, pela pesquisa + formato do canal")
                ds.salvar(base_dir, p)
                f = ds.adicionar_fonte_arquivo(base_dir, p, f"notas_pesquisa_{cid}.md", notas.encode("utf-8"))
                ds.salvar(base_dir, p)
            pid = p["id"]
            _estado(modelo, cid, projeto=pid)
            ds.processar_fonte(base_dir, pid, f["id"], dossies_rotas._TRAVA)
            _estado(modelo, cid, estado="roteiro", msg="✍️ a IA está escrevendo o roteiro com o formato do canal…")
            pr = _post(f"/modelos-video/{pid}/prompt")["prompt"]
            resp = _post("/ia/gerar", {"prompt": pr, "titulo": "Roteiro: " + tema[:80]})
            _post(f"/modelos-video/{pid}/resultado", {"texto": resp.get("texto") or ""})
            p = ds.carregar(base_dir, pid)
            res = p.get("resultado") or {}
            if not (res.get("roteiro") or "").strip() and res.get("partes"):
                _estado(modelo, cid, msg=f"✍️ escrevendo as {len(res['partes'])} partes…")
                _esperar(_post(f"/modelos-video/{pid}/partes/ia")["tarefa"])
                p = ds.carregar(base_dir, pid)
            if not ((p.get("resultado") or {}).get("roteiro") or "").strip():
                raise RuntimeError("a IA não devolveu o roteiro")
            if revisar:
                _estado(modelo, cid, estado="revisao", msg="🪄 revisão + 🎙 adaptando pro TTS…")
                try:
                    _esperar(_post(f"/roteiro-auto/dossie/{pid}", {"pagina": f"/modelos-video/{pid}"})["tarefa"])
                    pr = _post(f"/tts-adaptar/dossie/{pid}/prompt")["prompt"]
                    resp = _post("/ia/gerar", {"prompt": pr, "titulo": "TTS: " + tema[:80]})
                    _post(f"/tts-adaptar/dossie/{pid}/ler", {"texto": resp.get("texto") or ""})
                except Exception as exc:  # noqa: BLE001 — sem a revisão o roteiro continua valendo
                    _estado(modelo, cid, msg=f"⚠ revisão: {exc}")
            p = ds.carregar(base_dir, pid)
            palavras = len(ds.roteiro_para_voz(p).split())
            _estado(modelo, cid, estado="pronto", msg=f"✅ roteiro pronto: {palavras} palavras (~{max(1, round(palavras / 150))} min)")
            try:
                import notificacoes
                notificacoes.avisar(f"💡 Roteiro pronto: {tema[:60]}", "", f"/modelos-video/{pid}", "ok", tipo="dossie")
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            _estado(modelo, cid, estado="erro", msg=f"❌ {exc}")

    @app.route("/formatos/<modelo>/criar", methods=["POST"])
    def formatos_criar(modelo: str):
        """💡 Um ou vários temas (um por linha) → pesquisa → projeto → roteiro no formato do canal."""
        if not _valido(modelo):
            return jsonify({"erro": "Modelo não encontrado."}), 404
        import ia_servico as ia
        motivo = ia.motivo_desligado("roteiros")
        if motivo:
            return jsonify({"erro": "IA: " + motivo + " — ligue em 🤖 IA (📝 Roteiros direto na IA)."}), 400
        c = request.get_json(silent=True) or {}
        temas = [" ".join(t.split())[:200] for t in str(c.get("temas") or c.get("tema") or "").splitlines() if t.strip()][:10]
        if not temas:
            return jsonify({"erro": "Escreva pelo menos um tema."}), 400
        try:
            minutos = max(0.0, min(60.0, float(c.get("minutos") or 0)))
        except (TypeError, ValueError):
            minutos = 0.0
        revisar = c.get("revisar", True) is not False
        novos = [{"id": uuid.uuid4().hex[:8], "tema": t, "estado": "fila", "msg": "⏳ na fila", "projeto": "",
                  "criado": time.time()} for t in temas]
        FV.mexer(base_dir, modelo, lambda d: d.setdefault("criados", []).extend(novos))

        def rodar():
            for x in novos:  # um de cada vez (cada um faz pesquisa + roteiro + revisão)
                _criar_do_tema(modelo, x["id"], x["tema"], minutos, revisar)
        threading.Thread(target=rodar, name="formato-criar", daemon=True).start()
        return jsonify({**FV.resumo(base_dir, modelo), "ok": True, "novos": len(novos)})
