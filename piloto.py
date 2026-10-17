"""🚀 Piloto automático do Modelo de vídeo (v84_157).

Você cola os LINKS (matérias) e o TEXTO (o roteiro pronto ou as suas anotações) e clica em 🚀. O site faz sozinho:

  FASE 1 (automática)
    1. 📰 lê as matérias (fontes)
    2. ✍️ roteiro — usa o seu (se você colou o roteiro pronto) ou a IA escreve a partir das fontes + anotações
    3. 🪄 revisão + 🔎 checagem (cronologia, alegações, repetições) com correção
    4. 📸 perguntas de fotos (quem/onde/o quê precisa de foto) + 🔎 termos de busca em inglês
    5. 🌐 prompt da checagem na internet (pra você mandar pra outra IA)
  ⏸ VOCÊ: cola a resposta da outra IA (🌐) e pega as fotos no 🧲 navegador das imagens → ▶ Continuar
  FASE 2 (automática)
    6. 📍 posiciona as fotos no roteiro
    7. 🎭 elenco (pessoas, idades, lugares)
    8. 🎙 adapta pro TTS (sempre o último passo de texto)

Cada passo usa as MESMAS rotas dos botões da página (o site chama a si mesmo), então o resultado é igual ao manual.
Passo que falha fica ⚠ com o motivo e o piloto segue (menos o roteiro: sem roteiro, para).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

PASSOS = [
    ("fontes", "📰 Ler as matérias", 1), ("roteiro", "✍️ Roteiro", 1), ("revisao", "🪄 Revisão + 🔎 checagem", 1),
    ("perguntas", "📸 Perguntas de fotos", 1), ("termos", "🔎 Termos de busca (inglês)", 1),
    ("web", "🌐 Prompt da checagem na internet", 1),
    ("voce", "⏸ Você: resposta da outra IA + fotos no 🧲", 0),
    ("posicionar", "📍 Posicionar as fotos no roteiro", 2), ("elenco", "🎭 Elenco", 2), ("tts", "🎙 Adaptar pro TTS", 2),
]
_RODANDO: Dict[str, bool] = {}


def novo_estado(modo_texto: str) -> Dict[str, Any]:
    return {"ativo": False, "fase": 0, "modo_texto": modo_texto, "inicio": time.time(), "erro": "",
            "passos": [{"id": k, "nome": n, "fase": f, "estado": "esperando", "msg": ""} for k, n, f in PASSOS],
            "web_prompt": ""}


def registrar(app, base_dir: str) -> None:
    from flask import jsonify, redirect, render_template, request, url_for
    import dossies as ds
    import dossies_rotas

    def _p(pid: str) -> Optional[Dict[str, Any]]:
        try:
            return ds.carregar(base_dir, pid)
        except ds.DossieError:
            return None

    def _mexer(pid: str, fn: Callable[[Dict[str, Any]], None]) -> None:
        with dossies_rotas._TRAVA:
            p = _p(pid)
            if p is not None:
                fn(p)
                ds.salvar(base_dir, p)

    def _passo(pid: str, pid_passo: str, estado: str, msg: str = "") -> None:
        def f(p):
            for x in (p.get("piloto") or {}).get("passos") or []:
                if x["id"] == pid_passo:
                    x.update(estado=estado, msg=str(msg)[:400])
        _mexer(pid, f)

    def _cli():
        return app.test_client()

    def _post(caminho: str, corpo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        r = _cli().post(caminho, json=corpo or {})
        d = r.get_json(silent=True) or {}
        if r.status_code >= 400 or d.get("erro"):
            raise RuntimeError(str(d.get("erro") or f"HTTP {r.status_code}"))
        return d

    def _get(caminho: str) -> Dict[str, Any]:
        return _cli().get(caminho).get_json(silent=True) or {}

    def _ia(prompt: str) -> str:
        d = _post("/ia/gerar", {"prompt": prompt})
        if not str(d.get("texto") or "").strip():
            raise RuntimeError("a IA não respondeu")
        return d["texto"]

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

    # ------------------------------------------------------------------ os passos
    def p_fontes(pid):
        t0 = time.time()
        while time.time() - t0 < 10 * 60:
            p = _p(pid) or {}
            fs = p.get("fontes") or []
            pend = [f for f in fs if f.get("estado") not in ("pronta", "erro")]
            if not pend:
                ok = sum(1 for f in fs if f.get("estado") == "pronta")
                return f"{ok} de {len(fs)} lida(s)" if fs else "sem links"
            time.sleep(4)
        return "algumas ainda baixando — segui assim mesmo"

    def p_roteiro(pid):
        p = _p(pid) or {}
        est = p.get("piloto") or {}
        if ((p.get("resultado") or {}).get("roteiro") or "").strip() and not est.get("refazer_roteiro"):
            return "já tinha roteiro"
        forcar = bool(est.get("refazer_roteiro"))
        if forcar:  # 🔁 roteiro do zero: o atual vai pro 🕘 histórico antes
            atual = ((p.get("resultado") or {}).get("roteiro") or "").strip()
            if atual:
                try:
                    import historico_roteiro as hr
                    hr.registrar(ds._pasta(base_dir, pid), atual, "🚀 antes do piloto refazer", "o roteiro antes de escrever de novo")
                except Exception:  # noqa: BLE001
                    pass
            _mexer(pid, lambda q: q.setdefault("piloto", {}).update(refazer_roteiro=False))
        tem = bool(((p.get("resultado") or {}).get("roteiro") or "").strip())
        if est.get("modo_texto") == "roteiro" and (p.get("roteiro_base") or "").strip() and (forcar or not tem):
            import json as _json
            texto = p["roteiro_base"].strip()
            with dossies_rotas._TRAVA:
                q = _p(pid)
                q["resultado"] = ds.ler_resultado(_json.dumps({"roteiro": texto, "titulos": [q.get("tema") or ""]}, ensure_ascii=False), q)
                ds.marcar_mudanca(q, "🚀 piloto", "o seu roteiro colado")
                ds.salvar(base_dir, q)
            return f"o seu roteiro ({len(texto.split())} palavras)"
        pr = _post(f"/modelos-video/{pid}/prompt")["prompt"]
        _post(f"/modelos-video/{pid}/resultado", {"texto": _ia(pr)})
        p = _p(pid) or {}
        res = p.get("resultado") or {}
        if not (res.get("roteiro") or "").strip() and res.get("partes"):  # ✍️ veio o plano: a IA escreve as partes
            _esperar_tarefa(_post(f"/modelos-video/{pid}/partes/ia")["tarefa"])
            p = _p(pid) or {}
        rot = ((p.get("resultado") or {}).get("roteiro") or "").strip()
        if not rot:
            raise RuntimeError("a IA não devolveu o roteiro")
        return f"{len(rot.split())} palavras"

    def p_revisao(pid):
        t = _esperar_tarefa(_post(f"/roteiro-auto/dossie/{pid}", {"pagina": f"/modelos-video/{pid}"})["tarefa"])
        ps = (t.get("resultado") or {}).get("passos") or []
        return " → ".join(f"{x.get('modo')}: {x.get('aplicadas', 0)}" for x in ps) or "ok"

    def p_perguntas(pid):
        pr = _post(f"/modelos-video/{pid}/fotos-roteiro/perguntas/prompt")["prompt"]
        d = _post(f"/modelos-video/{pid}/fotos-roteiro/perguntas/ler", {"texto": _ia(pr)})
        return f"{len(d.get('perguntas') or [])} pergunta(s)"

    def p_termos(pid):
        import fotos_roteiro as fr
        p = _p(pid) or {}
        qs = [q for q in (p.get("fotos_roteiro") or {}).get("perguntas") or [] if not q.get("pulada") and not (q.get("busca") or "").strip()]
        if not qs:
            return "nada a fazer"
        termos = fr.termos_em_ingles(p, qs, job=pid) or {}

        def f(q_p):
            for q in (q_p.get("fotos_roteiro") or {}).get("perguntas") or []:
                if not (q.get("busca") or "").strip():
                    q["busca"] = termos.get(q["id"]) or fr.termo_da_pergunta(q_p, q)
        _mexer(pid, f)
        return f"{len(termos)} pela IA" + ("" if len(termos) == len(qs) else f", {len(qs) - len(termos)} pelo nome")

    def p_web(pid):
        pr = _post(f"/checagem/dossie/{pid}/web/prompt")["prompt"]
        _mexer(pid, lambda p: p.setdefault("piloto", {}).update(web_prompt=pr))
        return f"{len(pr) // 1000} mil caracteres — copie e mande pra outra IA"

    def p_posicionar(pid):
        p = _p(pid) or {}
        if not any(m.get("tipo") in ("foto", "video") for m in p.get("midias") or []):
            return "sem fotos — pulei"
        pr = _post(f"/modelos-video/{pid}/fotos-roteiro/posicionar/prompt", {"modo": "todas"})["prompt"]
        _post(f"/modelos-video/{pid}/fotos-roteiro/posicionar/ler", {"texto": _ia(pr)})
        return "marcas postas"

    def p_elenco(pid):
        d = _post(f"/modelos-video/{pid}/elenco/ia")
        t0 = time.time()
        while (d.get("rodando") or {}).get("ativo") and time.time() - t0 < 40 * 60:
            time.sleep(4)
            d = _get(f"/modelos-video/{pid}/elenco")
        r = d.get("rodando") or {}
        if r.get("erro"):
            raise RuntimeError(r["erro"])
        el = d.get("elenco") or {}
        return f"{len(el.get('pessoas') or [])} pessoa(s), {len(el.get('locais') or [])} local(is)"

    def p_tts(pid):
        pr = _post(f"/tts-adaptar/dossie/{pid}/prompt")["prompt"]
        d = _post(f"/tts-adaptar/dossie/{pid}/ler", {"texto": _ia(pr)})
        return f"{d.get('palavras_antes')} → {d.get('palavras_depois')} palavras"

    FUNCOES = {"fontes": p_fontes, "roteiro": p_roteiro, "revisao": p_revisao, "perguntas": p_perguntas, "termos": p_termos,
               "web": p_web, "posicionar": p_posicionar, "elenco": p_elenco, "tts": p_tts}

    def rodar(pid: str, fase: int) -> None:
        import notificacoes
        _RODANDO[pid] = True
        _mexer(pid, lambda p: p.setdefault("piloto", {}).update(ativo=True, fase=fase, erro=""))
        try:
            for k, _n, f in PASSOS:
                if f != fase:
                    continue
                est = next((x for x in ((_p(pid) or {}).get("piloto") or {}).get("passos") or [] if x["id"] == k), {})
                if est.get("estado") in ("ok", "pulado"):
                    continue
                _passo(pid, k, "rodando")
                try:
                    _passo(pid, k, "ok", FUNCOES[k](pid))
                except Exception as exc:  # noqa: BLE001
                    _passo(pid, k, "erro", str(exc))
                    if k == "roteiro":
                        raise RuntimeError("sem roteiro não dá pra seguir: " + str(exc)) from exc
            if fase == 1:
                _passo(pid, "voce", "voce", "cole a resposta da outra IA (🌐) e pegue as fotos no 🧲 — depois ▶ Continuar")
                notificacoes.avisar("🚀 Piloto: sua vez", "Mande o prompt 🌐 pra outra IA e pegue as fotos no 🧲; depois ▶ Continuar.",
                                    f"/modelos-video/{pid}", "ok", tipo="dossie")
            else:
                notificacoes.avisar("✅ Piloto: roteiro pronto pro TTS", "", f"/modelos-video/{pid}", "ok", tipo="dossie")
        except Exception as exc:  # noqa: BLE001
            _mexer(pid, lambda p: p.setdefault("piloto", {}).update(erro=str(exc)[:400]))
            notificacoes.avisar("❌ Piloto parou", str(exc)[:300], f"/modelos-video/{pid}", "erro", tipo="dossie")
        finally:
            _RODANDO.pop(pid, None)
            _mexer(pid, lambda p: p.setdefault("piloto", {}).update(ativo=False))

    def comecar(pid: str, fase: int) -> bool:
        if _RODANDO.get(pid):
            return False
        threading.Thread(target=rodar, args=(pid, fase), daemon=True).start()
        return True

    # ------------------------------------------------------------------ rotas
    @app.route("/piloto")
    def piloto_pagina():
        import idiomas
        return render_template("piloto.html", modelos=ds.MODELOS, idiomas=[(k, v[0]) for k, v in idiomas.IDIOMAS.items()],
                               erro=request.args.get("erro") or "")

    @app.route("/piloto/iniciar", methods=["POST"])
    def piloto_iniciar():
        f = request.form
        tema = (f.get("tema") or "").strip()
        texto = (f.get("texto") or "").strip()
        links = (f.get("links") or "").strip()
        if not tema:
            return redirect(url_for("piloto_pagina", erro="Escreva o tema (ex.: o nome do caso)."))
        if not texto and not links:
            return redirect(url_for("piloto_pagina", erro="Cole os links e/ou o texto."))
        modo = "roteiro" if f.get("modo_texto") == "roteiro" else "anotacoes"
        with dossies_rotas._TRAVA:
            p = ds.criar(base_dir, tema=tema[:300], modelo=f.get("modelo") if f.get("modelo") in ds.MODELOS else "true_crime")
            cfg = p["config"]
            if f.get("idioma"):
                cfg["idioma"] = f["idioma"][:20]
            try:
                cfg["minutos"] = max(0.5, min(120.0, float(f.get("minutos") or cfg.get("minutos") or 20)))
            except (TypeError, ValueError):
                pass
            if f.get("formato_video") in ("16:9", "9:16", "1:1"):
                cfg["formato_video"] = f["formato_video"]
            p["roteiro_base"] = texto[:60000]
            p["piloto"] = novo_estado(modo)
            ds.marcar_mudanca(p, "🚀 piloto", "criado pelo piloto automático")
            ds.salvar(base_dir, p)
        if links:
            try:
                _post(f"/modelos-video/{p['id']}/fontes", {"urls": links})
            except RuntimeError:
                pass
        comecar(p["id"], 1)
        return redirect(f"/modelos-video/{p['id']}#piloto")

    @app.route("/modelos-video/<pid>/piloto")
    def piloto_estado(pid: str):
        p = _p(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        est = p.get("piloto")
        return jsonify({"ok": True, "piloto": est, "rodando": bool(_RODANDO.get(pid))})

    @app.route("/modelos-video/<pid>/piloto/iniciar", methods=["POST"])
    def piloto_iniciar_existente(pid: str):
        """🚀 Num modelo que já existe: roda o que falta (o que já está feito é pulado)."""
        c = request.get_json(silent=True) or {}
        if _RODANDO.get(pid):
            return jsonify({"erro": "O piloto já está rodando."}), 400
        refazer = [str(x) for x in c.get("refazer") or []]
        fase = int(c.get("fase") or 1)

        def f(p):
            velho = p.get("piloto") or {}
            modo = c.get("modo_texto") if c.get("modo_texto") in ("roteiro", "anotacoes") else velho.get("modo_texto") or "anotacoes"
            if not velho or c.get("do_zero") or refazer:
                novo = novo_estado(modo)
                if refazer:  # 🔁 rodar de novo SÓ os passos marcados; os outros ficam como estão
                    for x in novo["passos"]:
                        if x["id"] != "voce" and x["id"] not in refazer:
                            x.update(estado="pulado", msg="mantido (não marcado pra refazer)")
                    novo["refazer_roteiro"] = "roteiro" in refazer
                    novo["web_prompt"] = velho.get("web_prompt") or ""
                p["piloto"] = novo
        _mexer(pid, f)
        if refazer and not any(k in refazer for k, _n, fs in PASSOS if fs == 1):
            _passo(pid, "voce", "ok", "pulado (só passos da fase 2)")
            fase = 2
        comecar(pid, fase)
        return jsonify({"ok": True, "fase": fase})

    @app.route("/modelos-video/<pid>/piloto/continuar", methods=["POST"])
    def piloto_continuar(pid: str):
        _passo(pid, "voce", "ok", "continuado")
        if not comecar(pid, 2):
            return jsonify({"erro": "O piloto já está rodando."}), 400
        return jsonify({"ok": True})

    @app.route("/modelos-video/<pid>/piloto/passo/<k>", methods=["POST"])
    def piloto_passo(pid: str, k: str):
        """↻ refazer / ⏭ pular um passo."""
        acao = (request.get_json(silent=True) or {}).get("acao")
        _passo(pid, k, "pulado" if acao == "pular" else "esperando", "pulado por você" if acao == "pular" else "")
        return jsonify({"ok": True})
