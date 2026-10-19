"""🎨 Rotas da Identidade visual (marca_visual.py) — v84_168."""
from __future__ import annotations

import io
import os
import re
import time
import uuid
from typing import Any, Dict

import marca_visual as mv


def registrar(app, base_dir: str) -> None:
    from flask import abort, jsonify, redirect, render_template, request, send_file, url_for

    import tarefas_bg

    def _corpo() -> Dict[str, Any]:
        return request.get_json(silent=True) or {}

    def _marca(slug: str):
        try:
            return mv.carregar(base_dir, slug)
        except mv.MarcaErro:
            abort(404)

    def _cfg_pod() -> Dict[str, Any]:
        try:
            import pod_studio
            return pod_studio._cfg(None)
        except Exception:  # noqa: BLE001
            return {}

    def _erro(exc: Exception, cod: int = 400):
        return jsonify({"erro": str(exc)}), cod

    def _motor(v: Any) -> str:
        return v if v in mv.MOTORES else "pod"

    try:  # 🕵️ cada pacote de canal com modelo_roteiro.json vira um modelo nos Modelos de vídeo
        mv.registrar_modelos(base_dir)
    except Exception:  # noqa: BLE001
        pass

    @app.context_processor
    def _marcas_no_template():
        return {"marcas_visuais": lambda: mv.listar(base_dir)}

    # ---------------------------------------------------------------- marcas
    @app.route("/marca")
    def marca_lista():
        marcas = mv.listar(base_dir)
        if len(marcas) == 1 and not request.args.get("todas"):
            return redirect(url_for("marca_detalhe", slug=marcas[0]["slug"]))
        return render_template("marca_lista.html", marcas=marcas, erro=request.args.get("erro"))

    def _js(v):
        import json
        return json.dumps(v, ensure_ascii=False, indent=1)

    @app.route("/marca/como-montar")
    def marca_como_montar():
        return render_template("marca_como.html", estrutura=mv.ESTRUTURA_PACOTE, chaves=mv.CHAVES_GUIA,
                               prompt_com=mv.prompt_montar_pacote(True), prompt_sem=mv.prompt_montar_pacote(False),
                               ex_pacote=_js(mv.EXEMPLO_PACOTE), ex_poses_personagem=_js(mv.EXEMPLO_POSES_PERSONAGEM), ex_reforcos=_js(mv.EXEMPLO_REFORCOS), ex_poses=_js(mv.EXEMPLO_POSES),
                               ex_modelo=_js(mv.EXEMPLO_MODELO), formato=mv.FORMATO_PACOTE, marcas=mv.listar(base_dir),
                               ex_direcao=_js(mv.EXEMPLO_DIRECAO), ex_personagens=_js(mv.EXEMPLO_PERSONAGENS),
                               ex_continuidade=_js(mv.EXEMPLO_CONTINUIDADE), ids_editor=mv._ids_catalogo(), direcoes=mv.direcoes_do_editor())

    @app.route("/marca/modelo-vazio.zip")
    def marca_modelo_vazio():
        return send_file(io.BytesIO(mv.zip_modelo_vazio()), mimetype="application/zip", as_attachment=True,
                         download_name="pacote_canal_modelo_vazio.zip")

    @app.route("/marca/<slug>/pacote.zip")
    def marca_pacote(slug: str):
        m = _marca(slug)
        pers = request.args.get("personagens") or "aprovadas"  # 🧍 v84_188: aprovadas | tudo | nao
        return send_file(io.BytesIO(mv.exportar_pacote(m, pers if pers in ("aprovadas", "tudo", "nao") else "aprovadas")),
                         mimetype="application/zip", as_attachment=True, download_name=f"pacote_{slug}.zip")

    @app.route("/marca/<slug>/excluir", methods=["POST"])
    def marca_excluir(slug: str):
        import shutil
        m = _marca(slug)
        shutil.rmtree(m["dir"], ignore_errors=True)
        import dossies as ds
        for k in [k for k, v in ds.MODELOS.items() if v.get("do_pacote") and v.get("identidade_visual") == slug]:
            ds.MODELOS.pop(k, None)
        return redirect(url_for("marca_lista", todas=1))

    @app.route("/marca/importar", methods=["POST"])
    def marca_importar():
        arq = request.files.get("zip")
        if not arq or not arq.filename:
            return redirect(url_for("marca_lista", todas=1, erro="Escolha o .zip do pacote do canal."))
        try:
            slug = mv.importar_zip(base_dir, arq.read())
        except mv.MarcaErro as exc:
            return redirect(url_for("marca_lista", todas=1, erro=str(exc)))
        return redirect(url_for("marca_detalhe", slug=slug, importado=1))

    @app.route("/marca/<slug>")
    def marca_detalhe(slug: str):
        m = _marca(slug)
        import dossies as ds
        return render_template("marca_detalhe.html", m=m, g=m["guia"], paleta=mv.paleta(m), celulas=mv.celulas_folha(m),
                               folha=mv.estado_folha(m), poses=mv.todas_poses(m), projetos=mv.listar_projetos(m),
                               motores=mv.MOTORES, dossies=ds.listar(base_dir)[:40], erro=request.args.get("erro"),
                               sugeridas=mv.poses_sugeridas(m), conferir=mv.conferir_pacote(m), importado=request.args.get("importado"),
                               modelo=mv.modelo_roteiro(m), direcao=mv._json(os.path.join(m["dir"], "direcao.json")),
                               perfil=__import__("canal_perfil").carregar(base_dir, slug),
                               tem_mascote=bool((m["guia"].get("mascot") or {}).get("prompt_lock_en")),
                               tem_proporcoes=os.path.isfile(os.path.join(m["dir"], "referencias", "mascote_proporcoes.png")))

    # ---------------------------------------------------------------- 🎭 perfil do canal: lore e histórico
    @app.route("/marca/<slug>/lore", methods=["POST"])
    def marca_lore(slug: str):
        import canal_perfil
        _marca(slug)
        c = _corpo()
        canal_perfil.salvar_lore(base_dir, slug, str(c.get("texto") or "")[:200000], str(c.get("motivo") or ""))
        return jsonify({"ok": True})

    @app.route("/marca/<slug>/historico/<acao>", methods=["POST"])
    def marca_historico(slug: str, acao: str):
        import canal_perfil
        _marca(slug)
        c = _corpo()
        try:
            if acao == "nota":
                canal_perfil.adicionar_nota(base_dir, slug, str(c.get("texto") or ""), str(c.get("tipo") or "nota"))
            elif acao == "apagar":
                canal_perfil.apagar_entrada(base_dir, slug, float(c.get("quando") or 0))
            else:
                abort(404)
        except ValueError as exc:
            return _erro(exc)
        return jsonify({"ok": True})

    @app.route("/marca/<slug>/arquivo/<path:rel>")
    def marca_arquivo(slug: str, rel: str):
        m = _marca(slug)
        try:
            cam = mv.arquivo(m, rel)
        except mv.MarcaErro:
            abort(404)
        if not os.path.isfile(cam):
            abort(404)
        if request.args.get("mini"):
            from PIL import Image
            im = Image.open(cam)
            im.thumbnail((int(request.args.get("mini") or 480),) * 2)
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=85)
            buf.seek(0)
            return send_file(buf, mimetype="image/jpeg", max_age=60)
        return send_file(cam, max_age=0)

    @app.route("/marca/<slug>/estado")
    def marca_estado(slug: str):
        m = _marca(slug)
        return jsonify({"folha": mv.estado_folha(m), "folha_aprovada": m["estado"].get("folha_aprovada"),
                        "celulas": mv.celulas_folha(m), "poses": mv.todas_poses(m)})

    # ---------------------------------------------------------------- folha mestra
    @app.route("/marca/<slug>/folha/gerar", methods=["POST"])
    def marca_folha_gerar(slug: str):
        m = _marca(slug)
        c = _corpo()
        ids = [str(x) for x in c.get("ids") or []]
        motor, var = _motor(c.get("motor")), int(c.get("variacoes") or 2)
        if not ids:
            return _erro(mv.MarcaErro("Escolha ao menos uma célula."))

        def _rodar(t):
            mm = mv.carregar(base_dir, slug)
            return mv.gerar_celulas(mm, ids, motor, _cfg_pod(), var, on_passo=t.progresso)
        tid = tarefas_bg.iniciar("marca_folha", f"🎨 Folha mestra: {len(ids)} células", _rodar, pagina=f"/marca/{slug}")
        return jsonify({"ok": True, "tarefa": tid})

    @app.route("/marca/<slug>/folha/<acao>", methods=["POST"])
    def marca_folha_acao(slug: str, acao: str):
        m = _marca(slug)
        c = _corpo()
        try:
            if acao == "aprovar":
                mv.aprovar_celula(m, str(c.get("celula")), str(c.get("arquivo")))
            elif acao == "reprovar":
                mv.reprovar_celula(m, str(c.get("celula")), str(c.get("arquivo")), str(c.get("motivo") or ""))
            elif acao == "compor":
                return jsonify({"ok": True, "folha": mv.compor_folha_aprovada(m, base_dir)})
            else:
                abort(404)
        except mv.MarcaErro as exc:
            return _erro(exc)
        return jsonify({"ok": True})

    # ---------------------------------------------------------------- 🆕 poses/emoções novas
    @app.route("/marca/<slug>/pose/nova", methods=["POST"])
    def marca_pose_nova(slug: str):
        m = _marca(slug)
        c = _corpo()
        try:
            pid = mv.nova_pose(m, str(c.get("descricao") or ""), en=str(c.get("en") or ""))
        except mv.MarcaErro as exc:
            return _erro(exc)
        out = {"ok": True, "pose": pid, "info": mv.pose_info(m, pid)}
        if c.get("gerar", True):
            motor, var = _motor(c.get("motor")), int(c.get("variacoes") or 3)

            def _rodar(t):
                return mv.gerar_celulas(mv.carregar(base_dir, slug), [pid], motor, _cfg_pod(), var, on_passo=t.progresso)
            out["tarefa"] = tarefas_bg.iniciar("marca_folha", f"🧍 Pose nova: {out['info']['nome']}", _rodar, pagina=f"/marca/{slug}")
        return jsonify(out)

    @app.route("/marca/<slug>/pose/<pid>/excluir", methods=["POST"])
    def marca_pose_excluir(slug: str, pid: str):
        try:
            mv.excluir_pose(_marca(slug), pid)
        except mv.MarcaErro as exc:
            return _erro(exc)
        return jsonify({"ok": True})

    # ---------------------------------------------------------------- projetos
    @app.route("/marca/<slug>/projeto/novo", methods=["POST"])
    def marca_projeto_novo(slug: str):
        m = _marca(slug)
        f = request.form
        narr, origem, fotos = (f.get("narracao") or "").strip(), {}, []
        titulo = f.get("titulo") or ""
        did = (f.get("dossie") or "").strip()
        if did:  # 🕵️ do Modelo de vídeo: o roteiro + as fotos (as marcas [I3] viram a foto da batida)
            import dossies as ds
            try:
                d = ds.carregar(base_dir, did)
            except Exception as exc:  # noqa: BLE001
                return redirect(url_for("marca_detalhe", slug=slug, erro=str(exc)))
            narr = narr or ((d.get("resultado") or {}).get("roteiro") or d.get("roteiro_base") or "").strip()
            titulo = titulo or d.get("tema") or ""
            origem = {"tipo": "dossie", "id": did}
            for md in d.get("midias") or []:
                if md.get("tipo") == "foto" and not md.get("descartada") and md.get("arquivo"):
                    cam = os.path.join(ds.pasta_midias(base_dir, did), md["arquivo"])
                    if os.path.isfile(cam):
                        fotos.append((md["id"], cam, md.get("legenda") or md.get("nome") or md["id"], md.get("descricao") or ""))
        if not narr:
            return redirect(url_for("marca_detalhe", slug=slug, erro="Cole a narração (ou escolha um Modelo de vídeo com roteiro)."))
        p = mv.criar_projeto(m, titulo, narr, origem, _motor(f.get("motor")), f.get("proporcao") or "16:9")
        if fotos:
            import shutil
            pasta = os.path.join(mv._pasta_proj(m, p["id"]), "fotos")
            os.makedirs(pasta, exist_ok=True)
            for mid, cam, nome, desc in fotos[:60]:
                arq = f"{mid}{os.path.splitext(cam)[1].lower() or '.jpg'}"
                shutil.copy(cam, os.path.join(pasta, arq))  # a ficha da foto do Modelo de vídeo vira as características
                p["fotos"].append({"id": mid.upper(), "arquivo": arq, "nome": nome[:120], "descricao_en": desc[:400], "estilo": "foto"})
            mv.salvar_projeto(m, p)
        return redirect(url_for("marca_projeto", slug=slug, pid=p["id"]))

    def _proj(m, pid):
        try:
            return mv.carregar_projeto(m, pid)
        except mv.MarcaErro:
            abort(404)

    @app.route("/marca/<slug>/p/<pid>")
    def marca_projeto(slug: str, pid: str):
        m = _marca(slug)
        p = _proj(m, pid)
        return render_template("marca_projeto.html", m=m, p=p, poses=mv.todas_poses(m), tipos=mv.TIPOS_IMAGEM, motores=mv.MOTORES)

    @app.route("/marca/<slug>/p/<pid>/dados")
    def marca_projeto_dados(slug: str, pid: str):
        m = _marca(slug)
        p = _proj(m, pid)
        for b in p["batidas"]:
            try:
                b["_previa"] = mv.previa_prompt(m, p, b)
            except Exception as exc:  # noqa: BLE001
                b["_previa"] = {"prompt": f"(erro: {exc})", "referencias": []}
        return jsonify(p)

    @app.route("/marca/<slug>/p/<pid>/elenco")
    def marca_elenco(slug: str, pid: str):
        """🎭 O elenco do Modelo de vídeo de origem (pessoas com idade, locais), com a miniatura da melhor foto."""
        m = _marca(slug)
        p = _proj(m, pid)
        d, el = mv.elenco_de(m, p)
        if not d:
            return jsonify({"origem": False})
        pessoas = []
        for x in el.get("pessoas") or []:
            f = (x.get("fotos") or [{}])[0]
            pessoas.append({"nome": x["nome"], "papel": x.get("papel") or "", "nascimento": x.get("nascimento") or 0,
                            "idades": [f2.get("idade") for f2 in x.get("fotos") or [] if f2.get("idade")],
                            "foto": f"/modelos-video/{d['id']}/arquivo/{f.get('midia')}" if f.get("midia") else "", "usar": x.get("usar", True)})
        locais = [{"nome": x["nome"], "tipo": x.get("tipo") or "", "foto": bool(x.get("fotos"))} for x in el.get("locais") or []]
        return jsonify({"origem": True, "dossie": d["id"], "tema": d.get("tema") or "", "pessoas": pessoas, "locais": locais,
                        "cronologia": el.get("cronologia") or []})

    @app.route("/marca/<slug>/p/<pid>/elenco/montar", methods=["POST"])
    def marca_elenco_montar(slug: str, pid: str):
        m = _marca(slug)
        p = _proj(m, pid)
        d, _el = mv.elenco_de(m, p)
        if not d:
            return _erro(mv.MarcaErro("Esse vídeo não veio de um Modelo de vídeo."))

        def _rodar(t):
            import dossies as ds
            import elenco
            t.progresso("a IA está vendo quem é quem nas fotos (e com que idade)…")
            dd = ds.carregar(base_dir, d["id"])
            dd.pop("elenco", None)
            el = elenco.do_projeto(base_dir, dd, criar=True, job=d["id"])
            return {"pessoas": len(el.get("pessoas") or []), "locais": len(el.get("locais") or [])}
        return jsonify({"ok": True, "tarefa": tarefas_bg.iniciar("marca_elenco", "🎭 Elenco das fotos", _rodar, pagina=f"/marca/{slug}/p/{pid}")})

    @app.route("/marca/<slug>/p/<pid>/prompt-batidas")
    def marca_prompt_batidas(slug: str, pid: str):
        m = _marca(slug)
        p = _proj(m, pid)
        return jsonify({"prompt": mv.prompt_batidas(m, p["narracao"], int(request.args.get("alvo") or 0), elenco=mv.elenco_de(m, p)[1])})

    def _anexar_fotos_marcadas(p):
        ids = {f["id"] for f in p.get("fotos") or []}
        for b in p["batidas"]:
            achadas = [x.upper() for x in re.findall(r"\[(I\d+)\]", b.get("narracao") or "", re.I)]
            if achadas and not b.get("fotos"):
                b["fotos"] = [x for x in dict.fromkeys(achadas) if x in ids][:3]

    @app.route("/marca/<slug>/p/<pid>/batidas", methods=["POST"])
    def marca_batidas(slug: str, pid: str):
        m = _marca(slug)
        c = _corpo()
        if c.get("ia"):
            def _rodar(t):
                import ia_servico
                mm = mv.carregar(base_dir, slug)
                pp = mv.carregar_projeto(mm, pid)
                t.progresso("a IA está dividindo a narração em batidas…")
                with ia_servico.rotulo(f"Identidade visual: batidas de {pp['titulo'][:40]}"):
                    r = ia_servico.chamar("marca", "Você é diretor de arte. Responda só com o JSON pedido.",
                                          mv.prompt_batidas(mm, pp["narracao"], elenco=mv.elenco_de(mm, pp)[1]), max_tokens=32000, timeout=600)
                if not r:
                    raise mv.MarcaErro("A IA não respondeu (ligada? com crédito? o recurso 🎨 está ligado em /ia?). "
                                       "Use o prompt pra copiar e colar.")
                with mv._TRAVA:
                    pp = mv.carregar_projeto(mm, pid)
                    pp["batidas"] = mv.ler_batidas(r, mm)
                    _anexar_fotos_marcadas(pp)
                    mv.salvar_projeto(mm, pp)
                return {"batidas": len(pp["batidas"])}
            return jsonify({"ok": True, "tarefa": tarefas_bg.iniciar("marca_batidas", "🎨 Batidas da narração", _rodar,
                                                                     pagina=f"/marca/{slug}/p/{pid}")})
        with mv._TRAVA:
            p = _proj(m, pid)
            try:
                if c.get("simples"):
                    p["batidas"] = mv.batidas_sem_ia(p["narracao"], int(c.get("a_cada") or 3), m)
                else:
                    p["batidas"] = mv.ler_batidas(str(c.get("resposta") or ""), m)
            except (mv.MarcaErro, ValueError) as exc:
                return _erro(exc)
            _anexar_fotos_marcadas(p)
            mv.salvar_projeto(m, p)
        return jsonify({"ok": True, "batidas": len(p["batidas"])})

    CAMPOS = {"narracao": 2000, "intencao_visual": 600, "assunto_en": 800, "pergunta_visual_en": 300, "composicao_en": 400,
              "acao_mascote_en": 300, "prompt_manual": 4000, "qa_notas": 600}

    @app.route("/marca/<slug>/p/<pid>/batida/<bid>", methods=["POST"])
    def marca_batida_editar(slug: str, pid: str, bid: str):
        m = _marca(slug)
        c = _corpo()
        with mv._TRAVA:
            p = _proj(m, pid)
            b = next((x for x in p["batidas"] if x["id"] == bid), None)
            if not b:
                return _erro(mv.MarcaErro("Batida não encontrada."), 404)
            for k, lim in CAMPOS.items():
                if k in c:
                    b[k] = str(c[k] or "")[:lim]
            if "mascote" in c:
                b["mascote"] = c["mascote"] if c["mascote"] in mv.todas_poses(m) else ""
            if "tipo_imagem" in c and c["tipo_imagem"] in mv.TIPOS_IMAGEM:
                b["tipo_imagem"] = c["tipo_imagem"]
            if "texto_de" in c:
                v = c["texto_de"]
                b["texto_de"] = [str(x)[:80] for x in (v if isinstance(v, list) else str(v).split("\n")) if str(x).strip()][:6]
            if "personagens" in c:  # 🎭 "mira: looking up; vanta" ou lista
                v = c["personagens"]
                if isinstance(v, str):
                    v = [{"slug": x.split(":", 1)[0].strip(), "acao_en": (x.split(":", 1)[1].strip() if ":" in x else "")}
                         for x in re.split(r"[;\n]", v) if x.strip()]
                b["personagens"] = mv._slugs_personagens(v)
            if "pessoas" in c:
                b["pessoas"] = mv._pessoas(c["pessoas"])
            if "lugar" in c:
                b["lugar"] = str(c["lugar"] or "")[:120]
            if "ano" in c:
                b["ano"] = mv._int0(c["ano"])
            if "anotacao" in c:
                b["anotacao"] = c["anotacao"] if c["anotacao"] in ("circulo", "seta") else None
            if "fotos" in c:
                ids = {f["id"] for f in p.get("fotos") or []}
                b["fotos"] = [str(x).upper() for x in c["fotos"] or [] if str(x).upper() in ids][:3]
            if "usar_corrigida" in c:
                b["usar_corrigida"] = bool(c["usar_corrigida"])
            if "seed_fixa" in c:
                try:
                    b["seed_fixa"] = int(c["seed_fixa"]) if str(c["seed_fixa"]).strip() != "" else None
                except ValueError:
                    b["seed_fixa"] = None
            if "qa_status" in c and c["qa_status"] in ("approved", "revise", "reject", ""):
                b["qa_status"] = c["qa_status"]
                b["qa_por"] = "manual"
            if c.get("voltar_geracao") is not None:  # usar uma geração anterior
                g = (b.get("geracoes") or [])[int(c["voltar_geracao"])]
                if g.get("arquivo"):
                    b["arquivo_master"] = g["arquivo"]
                    b["paleta"] = mv.validar_paleta(mv.arquivo(m, g["arquivo"]), m)
                    b["arquivo_corrigido"] = b["arquivo_texto"] = None
            mv.salvar_projeto(m, p)
        return jsonify({"ok": True})

    @app.route("/marca/<slug>/p/<pid>/batida/<bid>/excluir", methods=["POST"])
    def marca_batida_excluir(slug: str, pid: str, bid: str):
        m = _marca(slug)
        with mv._TRAVA:
            p = _proj(m, pid)
            p["batidas"] = [b for b in p["batidas"] if b["id"] != bid]
            mv.salvar_projeto(m, p)
        return jsonify({"ok": True})

    @app.route("/marca/<slug>/p/<pid>/config", methods=["POST"])
    def marca_projeto_config(slug: str, pid: str):
        m = _marca(slug)
        c = _corpo()
        with mv._TRAVA:
            p = _proj(m, pid)
            if "motor" in c:
                p["motor"] = _motor(c["motor"])
            if c.get("proporcao") in mv.DIMS:
                p["proporcao"] = c["proporcao"]
            for k in ("corrigir_sempre", "ref_estilo_sempre"):
                if k in c:
                    p[k] = bool(c[k])
            if "titulo" in c:
                p["titulo"] = " ".join(str(c["titulo"]).split())[:160] or p["titulo"]
            mv.salvar_projeto(m, p)
        return jsonify({"ok": True})

    @app.route("/marca/<slug>/p/<pid>/fotos", methods=["POST"])
    def marca_fotos(slug: str, pid: str):
        """📷 Fotos suas (pessoa, objeto, lugar real): viram referência do klein nas batidas que você marcar."""
        m = _marca(slug)
        with mv._TRAVA:
            p = _proj(m, pid)
            pasta = os.path.join(mv._pasta_proj(m, pid), "fotos")
            os.makedirs(pasta, exist_ok=True)
            novas = []
            for arq in request.files.getlist("fotos"):
                ext = os.path.splitext(arq.filename or "")[1].lower()
                if ext not in (".png", ".jpg", ".jpeg", ".webp"):
                    continue
                fid = "F" + uuid.uuid4().hex[:5].upper()
                nome = f"{fid}{ext}"
                arq.save(os.path.join(pasta, nome))
                p.setdefault("fotos", []).append({"id": fid, "arquivo": nome, "nome": (request.form.get("nome") or arq.filename or fid)[:120]})
                novas.append(fid)
            mv.salvar_projeto(m, p)
        tid = _descrever_fotos(slug, pid, novas) if novas else None
        return jsonify({"ok": True, "novas": novas, "tarefa": tid})

    def _descrever_fotos(slug: str, pid: str, ids):
        try:
            import ia_servico
            if ia_servico.motivo_desligado("marca", ia_servico.config()) is not None:
                return None
        except Exception:  # noqa: BLE001
            return None

        def _rodar(t):
            mm = mv.carregar(base_dir, slug)
            feitas = 0
            for k, fid in enumerate(ids):
                t.progresso(f"olhando a foto {k + 1}/{len(ids)}")
                pp = mv.carregar_projeto(mm, pid)
                f = next((x for x in pp.get("fotos") or [] if x["id"] == fid), None)
                cam = mv._foto_proj(mm, pp, fid)
                if not f or not cam:
                    continue
                d = mv.descrever_foto(cam, f.get("nome") or "")
                if d:
                    with mv._TRAVA:
                        pp = mv.carregar_projeto(mm, pid)
                        for x in pp.get("fotos") or []:
                            if x["id"] == fid:
                                x["descricao_en"] = d
                        mv.salvar_projeto(mm, pp)
                        feitas += 1
            return {"descritas": feitas}
        return tarefas_bg.iniciar("marca_fotos", "📷 Características das fotos", _rodar, pagina=f"/marca/{slug}/p/{pid}", avisar=False)

    @app.route("/marca/<slug>/p/<pid>/foto/<fid>/editar", methods=["POST"])
    def marca_foto_editar(slug: str, pid: str, fid: str):
        m = _marca(slug)
        c = _corpo()
        with mv._TRAVA:
            p = _proj(m, pid)
            f = next((x for x in p.get("fotos") or [] if x["id"] == fid.upper()), None)
            if not f:
                return _erro(mv.MarcaErro("Foto não encontrada."), 404)
            if "descricao_en" in c:
                f["descricao_en"] = " ".join(str(c["descricao_en"] or "").split())[:400]
            if c.get("estilo") in ("foto", "ilustracao"):
                f["estilo"] = c["estilo"]
            if "nome" in c:
                f["nome"] = str(c["nome"] or "")[:120]
            if c.get("excluir"):
                p["fotos"] = [x for x in p["fotos"] if x["id"] != f["id"]]
                for b in p["batidas"]:
                    b["fotos"] = [x for x in b.get("fotos") or [] if x != f["id"]]
            mv.salvar_projeto(m, p)
        if c.get("descrever"):
            return jsonify({"ok": True, "tarefa": _descrever_fotos(slug, pid, [fid.upper()])})
        return jsonify({"ok": True})

    @app.route("/marca/<slug>/p/<pid>/foto/<fid>")
    def marca_foto(slug: str, pid: str, fid: str):
        m = _marca(slug)
        p = _proj(m, pid)
        cam = mv._foto_proj(m, p, fid.upper())
        if not cam:
            abort(404)
        return send_file(cam, max_age=60)

    @app.route("/marca/<slug>/p/<pid>/gerar", methods=["POST"])
    def marca_gerar(slug: str, pid: str):
        m = _marca(slug)
        p = _proj(m, pid)
        c = _corpo()
        ids = [str(x) for x in c.get("ids") or [b["id"] for b in p["batidas"] if not b.get("arquivo_master")]]
        if not ids:
            return _erro(mv.MarcaErro("Nada pra gerar (todas as batidas já têm imagem — escolha quais refazer)."))
        motor = _motor(c.get("motor") or p.get("motor"))

        def _rodar(t):
            mm = mv.carregar(base_dir, slug)
            r = mv.gerar_batidas(mm, pid, ids, motor, _cfg_pod(), on_passo=t.progresso)
            if c.get("texto", True):
                pp = mv.carregar_projeto(mm, pid)
                for b in pp["batidas"]:
                    if b["id"] in ids and b.get("arquivo_master") and (b.get("texto_de") or b.get("anotacao")):
                        try:
                            mv.aplicar_texto_batida(base_dir, mm, pid, b["id"])
                        except mv.MarcaErro:
                            pass
            return r
        tid = tarefas_bg.iniciar("marca_gerar", f"🎨 Gerando {len(ids)} imagens ({mv.MOTORES[motor].split(' (')[0]})", _rodar,
                                 pagina=f"/marca/{slug}/p/{pid}")
        return jsonify({"ok": True, "tarefa": tid})

    @app.route("/marca/<slug>/p/<pid>/batida/<bid>/texto", methods=["POST"])
    def marca_texto(slug: str, pid: str, bid: str):
        m = _marca(slug)
        c = _corpo()
        try:
            mv.aplicar_texto_batida(base_dir, m, pid, bid, c.get("elementos") if "elementos" in c else None)
        except mv.MarcaErro as exc:
            return _erro(exc)
        return jsonify({"ok": True})

    @app.route("/marca/<slug>/p/<pid>/batida/<bid>/corrigir", methods=["POST"])
    def marca_corrigir(slug: str, pid: str, bid: str):
        m = _marca(slug)
        with mv._TRAVA:
            p = _proj(m, pid)
            b = next((x for x in p["batidas"] if x["id"] == bid), None)
            if not b or not b.get("arquivo_master"):
                return _erro(mv.MarcaErro("Gere a imagem primeiro."))
            corr = os.path.join(mv._pasta_proj(m, pid), "corrigidas", os.path.basename(b["arquivo_master"]))
            os.makedirs(os.path.dirname(corr), exist_ok=True)
            mv.gradear(mv.arquivo(m, b["arquivo_master"]), corr, m)
            b.update(arquivo_corrigido=os.path.relpath(corr, m["dir"]), paleta_corrigida=mv.validar_paleta(corr, m),
                     usar_corrigida=True, arquivo_texto=None)
            mv.salvar_projeto(m, p)
        if b.get("elementos") or b.get("texto_de"):
            mv.aplicar_texto_batida(base_dir, m, pid, bid)
        return jsonify({"ok": True})

    @app.route("/marca/<slug>/p/<pid>/revisar-ia", methods=["POST"])
    def marca_revisar_ia(slug: str, pid: str):
        m = _marca(slug)
        p = _proj(m, pid)
        ids = [str(x) for x in _corpo().get("ids") or [b["id"] for b in p["batidas"] if b.get("arquivo_master") and not b.get("qa_por")]]

        def _rodar(t):
            mm = mv.carregar(base_dir, slug)
            feitas = 0
            for k, bid in enumerate(ids):
                t.progresso(f"revisando {k + 1}/{len(ids)}")
                pp = mv.carregar_projeto(mm, pid)
                b = next((x for x in pp["batidas"] if x["id"] == bid), None)
                img = mv.imagem_final_da_batida(mm, b, com_texto=False) if b else None
                if not img:
                    continue
                r = mv.revisar_ia(mm, img, b)
                if not r:
                    raise mv.MarcaErro("A IA não respondeu (ligada, com crédito, recurso 🎨 ligado em /ia?).")
                with mv._TRAVA:
                    pp = mv.carregar_projeto(mm, pid)
                    b = next((x for x in pp["batidas"] if x["id"] == bid), None)
                    if b:
                        b.update(qa_status=r["status"], qa_notas=r.get("notas") or "", qa_por="ia",
                                 qa_ia={k2: r.get(k2) for k2 in ("mascote_igual", "tem_texto", "paleta_ok")})
                        mv.salvar_projeto(mm, pp)
                        feitas += 1
            return {"revisadas": feitas}
        return jsonify({"ok": True, "tarefa": tarefas_bg.iniciar("marca_qa", f"👁 Revisão da IA: {len(ids)} imagens", _rodar,
                                                                 pagina=f"/marca/{slug}/p/{pid}")})

    @app.route("/marca/<slug>/p/<pid>/exportar")
    def marca_exportar(slug: str, pid: str):
        m = _marca(slug)
        p = _proj(m, pid)
        dados = mv.exportar(m, pid)
        nome = re.sub(r"[^A-Za-z0-9_-]+", "_", p["titulo"])[:50] or "imagens"
        return send_file(io.BytesIO(dados), mimetype="application/zip", as_attachment=True,
                         download_name=f"{m['slug']}_{nome}_{time.strftime('%Y%m%d')}.zip")

    @app.route("/marca/<slug>/p/<pid>/excluir", methods=["POST"])
    def marca_projeto_excluir(slug: str, pid: str):
        import shutil
        m = _marca(slug)
        _proj(m, pid)
        shutil.rmtree(mv._pasta_proj(m, pid), ignore_errors=True)
        return redirect(url_for("marca_detalhe", slug=slug))
