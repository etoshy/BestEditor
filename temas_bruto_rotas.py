"""📚 Texto bruto → vários vídeos (v84_368): as rotas e o "gerar todos ao mesmo tempo" (veja temas_bruto.py)."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import temas_bruto as TB

PARALELO = 3          # roteiros gerados ao mesmo tempo
_RODANDO: Dict[str, bool] = {}


def registrar(app, base_dir: str) -> None:
    from flask import jsonify, redirect, render_template, request, url_for
    import dossies as ds
    import dossies_rotas

    # ------------------------------------------------------------------ chamar as rotas do próprio site (igual ao 🚀 Piloto)
    def _post(caminho: str, corpo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        r = app.test_client().post(caminho, json=corpo or {})
        d = r.get_json(silent=True) or {}
        if r.status_code >= 400 or d.get("erro"):
            raise RuntimeError(str(d.get("erro") or f"HTTP {r.status_code}"))
        return d

    def _esperar_tarefa(tid: str, limite_s: float = 3600) -> Dict[str, Any]:
        import tarefas_bg
        t0 = time.time()
        while time.time() - t0 < limite_s:
            t = tarefas_bg.pegar(tid) or {}
            if t.get("status") and t["status"] != "rodando":
                tarefas_bg.marcar_aplicada(tid)
                if t["status"] != "pronto":
                    raise RuntimeError(t.get("erro") or "a tarefa falhou")
                return t
            time.sleep(3)
        raise RuntimeError("demorou demais")

    def _estado(aid: str, tid: str, estado: str, msg: str = "", **extra) -> None:
        def f(a):
            for t in a.get("temas") or []:
                if t["id"] == tid:
                    t.update(estado=estado, msg=str(msg)[:300], **extra)
        TB.mexer(base_dir, aid, f)

    # ------------------------------------------------------------------ um tema → projeto + roteiro
    def _um_tema(aid: str, tid: str, gerar: bool, revisar: bool) -> None:
        a = TB.carregar(base_dir, aid)
        t = next((x for x in a.get("temas") or [] if x["id"] == tid), None)
        if not t:
            return
        try:
            pid = t.get("projeto") or ""
            if not pid or not _existe(pid):
                _estado(aid, tid, "criando", "📁 criando o projeto…")
                with dossies_rotas._TRAVA:
                    p = ds.criar(base_dir, tema=t["titulo"], modelo=a["modelo"])
                    cfg = p["config"]
                    cfg["formato"] = t["formato"] if t["formato"] in TB._formatos(a["modelo"]) else cfg.get("formato")
                    cfg["minutos"] = float(t.get("minutos") or cfg.get("minutos") or 10)
                    cfg["titulo"] = t["titulo"]
                    cfg["idioma"] = "pt"
                    ds.marcar_mudanca(p, "📚 texto bruto", f"criado a partir de “{a['nome']}”")
                    ds.salvar(base_dir, p)
                pid = p["id"]
                _estado(aid, tid, "criando", "📁 projeto criado", projeto=pid)
            p = ds.carregar(base_dir, pid)
            if not any(str(f.get("arquivo") or "").startswith(f"F") and ("notas_" in str(f.get("arquivo"))
                                                                         or "bruto_" in str(f.get("arquivo")))
                       for f in p.get("fontes") or []):
                if TB.base_video(a) == "lapidado" and (a.get("fatias") or {}).get("dono"):  # 💎 v84_431
                    _estado(aid, tid, "notas", "💎 lapidando os trechos da aula deste vídeo…")
                    notas = TB.lapidar(base_dir, a, t, progresso=lambda m: _estado(aid, tid, "notas", m))
                    nome_fonte = f"bruto_{tid}.md"
                else:
                    _estado(aid, tid, "notas", "📝 a IA está separando o que o texto diz sobre o tema…")
                    notas = TB.gerar_notas(base_dir, a, t)
                    nome_fonte = f"notas_{tid}.md"
                with dossies_rotas._TRAVA:
                    p = ds.carregar(base_dir, pid)
                    f = ds.adicionar_fonte_arquivo(base_dir, p, nome_fonte, notas.encode("utf-8"))
                    ds.salvar(base_dir, p)
                ds.processar_fonte(base_dir, pid, f["id"], dossies_rotas._TRAVA)
            if not gerar:
                _estado(aid, tid, "criado", "📁 projeto criado com as notas (sem roteiro)")
                return
            p = ds.carregar(base_dir, pid)
            if not ((p.get("resultado") or {}).get("roteiro") or "").strip():
                _estado(aid, tid, "roteiro", "✍️ a IA está escrevendo o roteiro…")
                pr = _post(f"/modelos-video/{pid}/prompt")["prompt"]
                resp = _post("/ia/gerar", {"prompt": pr, "titulo": "Roteiro: " + t["titulo"][:80]})
                _post(f"/modelos-video/{pid}/resultado", {"texto": resp.get("texto") or ""})
                p = ds.carregar(base_dir, pid)
                res = p.get("resultado") or {}
                if not (res.get("roteiro") or "").strip() and res.get("partes"):
                    _estado(aid, tid, "roteiro", f"✍️ escrevendo as {len(res['partes'])} partes…")
                    _esperar_tarefa(_post(f"/modelos-video/{pid}/partes/ia")["tarefa"])
                    p = ds.carregar(base_dir, pid)
            rot = ((p.get("resultado") or {}).get("roteiro") or "").strip()
            if not rot:
                raise RuntimeError("a IA não devolveu o roteiro")
            _completar_tamanho(aid, tid, pid, t)
            if revisar and not t.get("revisado"):
                _estado(aid, tid, "revisao", "🪄 revisão + 🎙 adaptando pro TTS…")
                try:
                    _esperar_tarefa(_post(f"/roteiro-auto/dossie/{pid}", {"pagina": f"/modelos-video/{pid}"})["tarefa"])
                    pr = _post(f"/tts-adaptar/dossie/{pid}/prompt")["prompt"]
                    resp = _post("/ia/gerar", {"prompt": pr, "titulo": "TTS: " + t["titulo"][:80]})
                    _post(f"/tts-adaptar/dossie/{pid}/ler", {"texto": resp.get("texto") or ""})
                    _estado(aid, tid, "revisao", "", revisado=True)
                except Exception as exc:  # noqa: BLE001 — sem a revisão o roteiro continua valendo
                    _estado(aid, tid, "revisao", f"⚠ revisão: {exc}")
            p = ds.carregar(base_dir, pid)
            palavras = len(ds.roteiro_para_voz(p).split())
            _estado(aid, tid, "pronto", f"✅ roteiro pronto: {palavras} palavras (~{max(1, round(palavras / 150))} min)")
        except Exception as exc:  # noqa: BLE001
            _estado(aid, tid, "erro", f"❌ {exc}")

    def _completar_tamanho(aid: str, tid: str, pid: str, t: Dict[str, Any]) -> None:
        """📏 v84_473: roteiro bem abaixo dos minutos pedidos (ex.: 8 de 30 min) = raso. A IA completa sozinha até o
        tamanho (no máx. 2 vezes) — antes só aparecia o aviso e o botão "📏 Prompt pra completar"."""
        import metodo_roteiro
        for vez in (1, 2):
            p = ds.carregar(base_dir, pid)
            minutos, alvo, _ppm = ds.alvo_tamanho(p)
            res = p.get("resultado") or {}
            tem = metodo_roteiro.palavras_do_texto(res.get("roteiro_final") or res.get("roteiro") or "")
            if minutos <= 1 or not alvo or tem >= alvo * metodo_roteiro.TOLERANCIA_TAMANHO:
                return
            _estado(aid, tid, "roteiro", f"📏 o roteiro ficou curto ({tem} de ~{alvo} palavras) — a IA está aprofundando "
                                         f"({vez}/2)…")
            try:
                pr = _post(f"/modelos-video/{pid}/prompt-completar")["prompt"]
                fonte = "\n\n".join(str(f.get("texto") or "") for f in p.get("fontes") or []
                                     if "notas_" in str(f.get("arquivo")) or "bruto_" in str(f.get("arquivo"))).strip()
                if fonte:  # conversa nova: a IA recebe de novo a fonte (as ideias) pra aprofundar com base nela
                    pr += "\n\n## Fonte (as ideias do vídeo)\n" + fonte[:60000]
                resp = _post("/ia/gerar", {"prompt": pr, "titulo": "Completar: " + t["titulo"][:80]})
                novo = str(resp.get("texto") or "")
                if len(novo.split()) <= tem:
                    return
                _post(f"/modelos-video/{pid}/resultado", {"texto": novo})
            except Exception:  # noqa: BLE001 — o roteiro curto continua valendo (dá pra completar à mão)
                return

    def _existe(pid: str) -> bool:
        try:
            ds.carregar(base_dir, pid)
            return True
        except ds.DossieError:
            return False

    def _rodar_todos(aid: str, ids: List[str], gerar: bool, revisar: bool) -> None:
        import notificacoes
        _RODANDO[aid] = True
        try:
            a = TB.carregar(base_dir, aid)
            if TB.base_video(a) == "lapidado":  # 💎 v84_431: divide a aula entre os vídeos ANTES (um trecho → um vídeo)
                fz = a.get("fatias") or {}
                falta = [t["id"] for t in a.get("temas") or [] if t["id"] in ids and not t.get("projeto")]
                if falta and (not fz.get("dono") or sorted(fz.get("ids") or []) != sorted(
                        t["id"] for t in a.get("temas") or [] if t.get("marcado") or t["id"] in ids)):
                    todos = [t["id"] for t in a.get("temas") or [] if t.get("marcado") or t["id"] in ids]
                    for tid in ids:
                        _estado(aid, tid, "fila", "✂ dividindo a aula entre os vídeos…")
                    try:
                        TB.distribuir(base_dir, aid, todos,
                                      progresso=lambda m: [_estado(aid, x, "fila", m) for x in ids])
                    except Exception as exc:  # noqa: BLE001 — sem a divisão, cai nas notas
                        TB.mexer(base_dir, aid, lambda x: x.update(base="notas"))
                        for tid in ids:
                            _estado(aid, tid, "fila", f"⚠ não deu pra dividir a aula ({exc}) — indo pelas notas")
                cont = TB.resumo_fatias(TB.carregar(base_dir, aid))
                ajust = TB.ajustar_minutos(base_dir, aid, ids) if TB.carregar(base_dir, aid).get("ajustar_minutos", True) else {}
                for tid in ids:
                    if tid in ajust:
                        pediu, novo, pal = ajust[tid]
                        _estado(aid, tid, "fila", f"✂ {pal} palavras da aula ficaram com este vídeo — ⏱ dá ~{novo:g} min "
                                f"densos (não {pediu:g}): ajustei pra não esticar", palavras_aula=pal)
                    elif cont.get(tid):
                        _estado(aid, tid, "fila", f"✂ {cont[tid]} palavras da aula ficaram com este vídeo "
                                f"(~{TB.minutos_possiveis(cont[tid]):g} min)", palavras_aula=cont[tid])
            with ThreadPoolExecutor(max_workers=PARALELO) as ex:
                list(ex.map(lambda tid: _um_tema(aid, tid, gerar, revisar), ids))
            a = TB.carregar(base_dir, aid)
            ok = sum(1 for t in a.get("temas") or [] if t["id"] in ids and t.get("estado") in ("pronto", "criado"))
            notificacoes.avisar(f"📚 {a['nome'][:60]}: {ok} de {len(ids)} {'roteiro(s) pronto(s)' if gerar else 'projeto(s) criado(s)'}",
                                "", f"/temas-bruto/{aid}", "ok" if ok == len(ids) else "erro", tipo="dossie")
        finally:
            _RODANDO.pop(aid, None)

    # ------------------------------------------------------------------ páginas
    def _modelos():
        return {k: m for k, m in ds.MODELOS.items() if m.get("formatos")}

    @app.route("/temas-bruto")
    def temas_bruto_lista():
        mods = _modelos()
        padrao = next((k for k in mods if k == "marca_cenariom"), next((k for k, m in mods.items() if m.get("do_pacote")), ""))
        return render_template("temas_bruto.html", a=None, lista=TB.listar(base_dir), modelos=mods, padrao=padrao,
                               divisoes=TB.DIVISOES, divisao=TB.DIVISAO_PADRAO,
                               erro=request.args.get("erro") or "")

    @app.route("/temas-bruto/novo", methods=["POST"])
    def temas_bruto_novo():
        # 🧩 v84_468: VÁRIOS arquivos (e/ou o texto colado) viram um material só
        arquivos = [(f.read(), f.filename) for f in request.files.getlist("arquivo") if f and f.filename]
        colado = (request.form.get("texto") or "").strip()
        if colado:
            arquivos.append((colado.encode("utf-8"), "texto_colado.txt"))
        if not arquivos:
            return redirect(url_for("temas_bruto_lista", erro="Envie o arquivo ou cole o texto."))
        conteudo, nome_arq = arquivos[0]
        try:
            a = TB.criar(base_dir, request.form.get("nome") or "", request.form.get("modelo") or "", conteudo, nome_arq,
                         request.form.get("divisao") or "", extras=arquivos[1:],
                         minutos_alvo_=request.form.get("minutos_alvo") or None)
        except TB.TemasErro as exc:
            return redirect(url_for("temas_bruto_lista", erro=str(exc)))
        import ia_servico as ia
        if not ia.motivo_desligado("roteiros"):
            _iniciar_analise(a["id"])
        return redirect(f"/temas-bruto/{a['id']}")

    def _iniciar_analise(aid: str) -> str:
        import tarefas_bg
        a = TB.carregar(base_dir, aid)
        return tarefas_bg.iniciar("temas_bruto", "📚 Separar os temas: " + a["nome"][:80],
                                  lambda t: {"temas": TB.analisar(base_dir, aid, t.progresso)}, pagina=f"/temas-bruto/{aid}")

    @app.route("/temas-bruto/<aid>")
    def temas_bruto_pagina(aid: str):
        try:
            a = TB.carregar(base_dir, aid)
        except TB.TemasErro:
            return redirect(url_for("temas_bruto_lista", erro="Análise não encontrada."))
        import ia_servico as ia
        mods = _modelos()
        return render_template("temas_bruto.html", a=a, lista=[], modelos=mods, padrao=a["modelo"],
                               formatos=TB._formatos(a["modelo"]), ia_off=ia.motivo_desligado("roteiros") or "",
                               divisoes=TB.DIVISOES, divisao=TB.divisao(a), bases=TB.BASES,
                               base_video=TB.base_video(a), fatias=TB.resumo_fatias(a), parecidos=TB.parecidos(a.get("temas") or []),
                               rodando=bool(_RODANDO.get(aid)), erro=request.args.get("erro") or "")

    @app.route("/temas-bruto/<aid>/estado")
    def temas_bruto_estado(aid: str):
        try:
            a = TB.carregar(base_dir, aid)
        except TB.TemasErro as exc:
            return jsonify({"erro": str(exc)}), 404
        return jsonify({"ok": True, "estado": a.get("estado"), "erro": a.get("erro") or "", "rodando": bool(_RODANDO.get(aid)),
                        "temas": [{k: t.get(k) for k in ("id", "estado", "msg", "projeto")} for t in a.get("temas") or []]})

    @app.route("/temas-bruto/<aid>/analisar", methods=["POST"])
    def temas_bruto_analisar(aid: str):
        import ia_servico as ia
        motivo = ia.motivo_desligado("roteiros")
        if motivo:
            return jsonify({"erro": "IA: " + motivo + " — use 📋 Copiar o pedido."}), 400
        c = request.get_json(silent=True) or {}
        dv = str(c.get("divisao") or "")
        mn = TB.minutos_alvo({"minutos_alvo": c.get("minutos_alvo")}) if str(c.get("minutos_alvo") or "").strip() else 0
        TB.mexer(base_dir, aid, lambda a: a.update(estado="analisando", erro="",
                                                   **({"divisao": dv} if dv in TB.DIVISOES else {}),
                                                   **({"minutos_alvo": mn} if mn else {})))
        return jsonify({"ok": True, "tarefa": _iniciar_analise(aid)})

    @app.route("/temas-bruto/<aid>/juntar", methods=["POST"])
    def temas_bruto_juntar(aid: str):
        """🧩 Junta os temas parecidos da lista atual (sem ler o texto de novo)."""
        import ia_servico as ia
        import tarefas_bg
        motivo = ia.motivo_desligado("roteiros")
        if motivo:
            return jsonify({"erro": "IA: " + motivo}), 400
        try:
            a = TB.carregar(base_dir, aid)
        except TB.TemasErro as exc:
            return jsonify({"erro": str(exc)}), 404
        if sum(1 for t in a.get("temas") or [] if not t.get("projeto")) < 2:
            return jsonify({"erro": "Precisa de pelo menos 2 temas que ainda não viraram projeto."}), 400
        dv = str((request.get_json(silent=True) or {}).get("divisao") or "")
        TB.mexer(base_dir, aid, lambda x: x.update(estado="analisando", erro="",
                                                   **({"divisao": dv} if dv in TB.DIVISOES else {})))

        def rodar(t):
            try:
                return {"temas": TB.juntar_parecidos(base_dir, aid, t.progresso)}
            except Exception as exc:
                TB.mexer(base_dir, aid, lambda x: x.update(estado="erro", erro=str(exc)[:400]))
                raise
        return jsonify({"ok": True, "tarefa": tarefas_bg.iniciar("temas_bruto", "🧩 Juntar temas: " + a["nome"][:80], rodar,
                                                                pagina=f"/temas-bruto/{aid}")})

    @app.route("/temas-bruto/<aid>/prompt")
    def temas_bruto_prompt(aid: str):
        try:
            return jsonify({"ok": True, "prompt": TB.prompt_analise(base_dir, aid)})
        except (TB.TemasErro, OSError) as exc:
            return jsonify({"erro": str(exc)}), 404

    @app.route("/temas-bruto/<aid>/ler", methods=["POST"])
    def temas_bruto_ler(aid: str):
        try:
            n = TB.ler_resposta(base_dir, aid, str((request.get_json(silent=True) or {}).get("texto") or ""))
        except TB.TemasErro as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True, "temas": n})

    @app.route("/temas-bruto/<aid>/tema/<tid>", methods=["POST"])
    def temas_bruto_tema(aid: str, tid: str):
        try:
            TB.editar_tema(base_dir, aid, tid, request.get_json(silent=True) or {})
        except TB.TemasErro as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True})

    @app.route("/temas-bruto/<aid>/gerar", methods=["POST"])
    def temas_bruto_gerar(aid: str):
        """🚀 Cria um Modelo de vídeo por tema marcado e gera os roteiros, {PARALELO} ao mesmo tempo."""
        c = request.get_json(silent=True) or {}
        ids = [str(x) for x in c.get("ids") or []]
        gerar = c.get("gerar", True) is not False
        revisar = c.get("revisar", True) is not False
        base_v = str(c.get("base") or "")
        if not ids:
            return jsonify({"erro": "Marque pelo menos um tema."}), 400
        if _RODANDO.get(aid):
            return jsonify({"erro": "Já está gerando — espere terminar."}), 400
        import ia_servico as ia
        motivo = ia.motivo_desligado("roteiros")
        if motivo:
            return jsonify({"erro": "IA: " + motivo + " — ligue em 🤖 IA (📝 Roteiros direto na IA)."}), 400
        try:
            a = TB.carregar(base_dir, aid)
        except TB.TemasErro as exc:
            return jsonify({"erro": str(exc)}), 404
        validos = [t["id"] for t in a.get("temas") or [] if t["id"] in ids]
        TB.mexer(base_dir, aid, lambda x: ([t.update(estado="fila", msg="⏳ na fila", marcado=True)
                                             for t in x.get("temas") or [] if t["id"] in validos],
                                            x.update(base=base_v) if base_v in TB.BASES else None))
        threading.Thread(target=_rodar_todos, args=(aid, validos, gerar, revisar), daemon=True).start()
        return jsonify({"ok": True, "temas": len(validos)})

    @app.route("/temas-bruto/<aid>/excluir", methods=["POST"])
    def temas_bruto_excluir(aid: str):
        if _RODANDO.get(aid):
            return redirect(f"/temas-bruto/{aid}?erro=Espere+terminar+de+gerar.")
        try:
            TB.excluir(base_dir, aid)
        except TB.TemasErro:
            pass
        return redirect(url_for("temas_bruto_lista"))
