"""
Rotas da aba 🕵️ Modelos de vídeo (ver dossies.py). Registradas pelo app.py com
`registrar(app, base_dir)`.
"""
from __future__ import annotations

import os
import threading
import uuid
from typing import Any, Dict

from flask import abort, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

import dossies as ds
import vendas as vd

_TRAVA = threading.RLock()
_IA_ESTADO: Dict[str, Dict[str, Any]] = {}  # 🤖 ficha das imagens rodando por projeto  # o projeto é mexido por rotas e pelas fontes baixando em segundo plano


def registrar(app, base_dir: str) -> None:

    def _proj(pid: str):
        try:
            return ds.carregar(base_dir, pid)
        except ds.DossieError:
            return None

    def _json_proj(p: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(p)
        import midia_transcricao as mt
        out["midias"] = []
        for m in p.get("midias") or []:
            cam = ds.caminho_midia(base_dir, p, m)
            item = dict(m, url_arquivo=(ds.url_midia(p, m) if cam else ""))
            if cam and mt.eh_video(cam):
                mt.agendar(cam)  # sem transcrição ainda (ou interrompida): faz em segundo plano
                item["transcricao"] = mt.resumo(cam)
            out["midias"].append(item)
        if p.get("resultado"):
            out["descricao_pronta"] = ds.descricao_completa(p)
        return out

    @app.context_processor
    def _dossies_no_template():
        return {"dossies_lista": lambda: ds.listar(base_dir)}

    @app.route("/modelos-video")
    def dossies_page():
        return render_template("dossies.html", projetos=ds.listar(base_dir), modelos=ds.MODELOS, erro=request.args.get("erro"))

    @app.route("/modelos-video/novo", methods=["POST"])
    def dossies_novo():
        tema = (request.form.get("tema") or "").strip()
        if not tema:
            return redirect(url_for("dossies_page", erro="Escreva o tema do vídeo."))
        with _TRAVA:
            p = ds.criar(base_dir, tema=tema, modelo=request.form.get("modelo") or "true_crime")
            urls = [u.strip() for u in (request.form.get("fontes") or "").split("\n") if u.strip()]
            novas = []
            for u in urls[:30]:
                try:
                    novas.append(ds.adicionar_fonte(p, u)["id"])
                except (ds.DossieError, vd.VendaError):
                    continue
            ds.salvar(base_dir, p)
        for fid in novas:
            _processar(p["id"], fid)
        return redirect(url_for("dossie_detalhe", pid=p["id"]))

    _fila = threading.Semaphore(2)  # até 2 matérias baixando ao mesmo tempo

    def _processar(pid: str, fid: str) -> None:
        def rodar():
            with _fila:
                try:
                    ds.processar_fonte(base_dir, pid, fid, _TRAVA)
                    import notificacoes
                    f_ok = next((x for x in (_proj(pid) or {}).get("fontes") or [] if x["id"] == fid), {})
                    if f_ok.get("estado") == "erro":
                        notificacoes.avisar("❌ Modelo de vídeo — uma fonte deu erro", str(f_ok.get("erro") or "")[:400],
                                            f"/modelos-video/{pid}", "erro", tipo="dossie")
                    else:
                        notificacoes.avisar("✅ Modelo de vídeo — fontes processadas", "", f"/modelos-video/{pid}", "ok",
                                            tipo="dossie", chave=f"dossie:{pid}")
                except Exception as exc:  # noqa: BLE001
                    import notificacoes
                    notificacoes.avisar("❌ Modelo de vídeo — uma fonte deu erro", str(exc)[:400], f"/modelos-video/{pid}", "erro", tipo="dossie")
                    with _TRAVA:
                        p = _proj(pid)
                        f = next((x for x in (p or {}).get("fontes") or [] if x["id"] == fid), None)
                        if f is not None:
                            f.update(estado="erro", erro=f"Erro inesperado: {exc}")
                            ds.salvar(base_dir, p)
        threading.Thread(target=rodar, daemon=True).start()

    @app.route("/modelos-video/<pid>")
    def dossie_detalhe(pid: str):
        p = _proj(pid)
        if not p:
            return redirect(url_for("dossies_page", erro="Projeto não encontrado."))
        import idiomas
        return render_template("dossie_detalhe.html", p=_json_proj(p), modelos=ds.MODELOS, tipos=ds.TIPOS_MIDIA,
                               ordem={k: list(m["formatos"]) for k, m in ds.MODELOS.items()},
                               idiomas=[(k, v[0]) for k, v in idiomas.IDIOMAS.items()],
                               nome_canal_global=__import__("canal").nome_global())

    @app.route("/modelos-video/<pid>/dados")
    def dossie_dados(pid: str):
        p = _proj(pid)
        return jsonify(_json_proj(p)) if p else (jsonify({"erro": "Projeto não encontrado."}), 404)

    @app.route("/modelos-video/<pid>/config", methods=["POST"])
    def dossie_config(pid: str):
        c = request.get_json(silent=True) or {}
        with _TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            cfg = p["config"]
            if c.get("modelo") in ds.MODELOS:
                if c["modelo"] != cfg.get("modelo") and ds.canal_do_modelo(c["modelo"]) and not str(c.get("nome_canal") or "").strip():
                    cfg["nome_canal"] = ds.canal_do_modelo(c["modelo"])  # 🎨 modelo da marca: o nome do canal dela
                cfg["modelo"] = c["modelo"]
            fmts = (ds.MODELOS.get(cfg["modelo"]) or ds.MODELOS["true_crime"])["formatos"]
            if c.get("formato") in fmts:
                cfg["formato"] = c["formato"]
            elif cfg.get("formato") not in fmts:
                cfg["formato"] = next(iter(fmts))
            if c.get("formato_video") in ("16:9", "9:16", "1:1"):
                cfg["formato_video"] = c["formato_video"]
            for k, lim in (("tom", 400), ("extra", 1500), ("idioma", 20), ("referencia", 60000), ("nome_canal", 80), ("titulo", 200)):
                if k in c:
                    cfg[k] = str(c.get(k) or "").strip()[:lim]
            if "minutos" in c:
                try:
                    cfg["minutos"] = max(0.5, min(120.0, float(c["minutos"])))
                except (TypeError, ValueError):
                    pass
            for k in ("sem_experiencias", "marcar_chamadas", "sugerir_produto"):
                if k in c:
                    cfg[k] = bool(c[k])
            if c.get("referencia_modo") in ("inspirar", "modelar"):
                cfg["referencia_modo"] = c["referencia_modo"]
            if c.get("modo_partes") in ("auto", "sim", "nao"):
                cfg["modo_partes"] = c["modo_partes"]
            if "tema" in c:
                p["tema"] = str(c.get("tema") or "").strip()[:300]
            if "roteiro_base" in c:
                p["roteiro_base"] = str(c.get("roteiro_base") or "")[:250000]  # v84_161: cabe a transcrição de vídeos longos
            ds.salvar(base_dir, p)
            __import__("ultimas_escolhas").lembrar(base_dir, idioma=cfg.get("idioma") if "idioma" in c else None,
                                                   nome_canal=cfg.get("nome_canal") if "nome_canal" in c else None)
        return jsonify({"ok": True, "config": cfg})

    def _transcrever_videos(pid: str, links: list) -> str:
        """🎬 v84_161: links de VÍDEO colados nas fontes → a transcrição (sem os tempos) de cada um vai pro campo
        "Roteiro / anotações seus" (passo 1), um bloco por vídeo. Roda em segundo plano (chega aviso no 🔔)."""
        import tarefas_bg
        import roteiros_yt as ry

        def _rodar(t):
            feitos, falhas = [], []
            for k, url in enumerate(links, 1):
                t.progresso(f"vídeo {k} de {len(links)}: lendo a transcrição…")
                try:
                    pasta = os.path.join(ds._pasta(base_dir, pid), "transcricoes_links")
                    tr = ry.extrair_transcricao(url, pasta, on_log=lambda m: t.progresso(f"vídeo {k} de {len(links)}: {str(m)[:120]}"))
                    texto = ry.texto_da_transcricao(tr, com_tempo=False).strip()
                    if not texto:
                        raise ValueError("o vídeo não tem fala/legenda")
                except Exception as exc:  # noqa: BLE001
                    falhas.append(f"{url[:80]}: {str(exc).splitlines()[0][:200] if str(exc) else exc.__class__.__name__}")
                    continue
                titulo = (tr.get("titulo") or "").strip() or url
                with _TRAVA:
                    p = _proj(pid)
                    if not p:
                        raise ValueError("Projeto não encontrado.")
                    base = (p.get("roteiro_base") or "").rstrip()
                    bloco = f"── Transcrição: {titulo} ──\n({url})\n{texto}"
                    p["roteiro_base"] = ((base + "\n\n") if base else "") + bloco
                    ds.salvar(base_dir, p)
                feitos.append({"url": url, "titulo": titulo, "caracteres": len(texto)})
            if not feitos and falhas:
                raise ValueError("Nenhuma transcrição: " + " · ".join(falhas))
            return {"feitos": feitos, "falhas": falhas}

        return tarefas_bg.iniciar("dossie_transcricao", f"🎬 Transcrição de {len(links)} vídeo(s) pras anotações", _rodar,
                                  pagina=f"/modelos-video/{pid}")

    @app.route("/modelos-video/<pid>/referencia/link", methods=["POST"])
    def dossie_referencia_link(pid: str):
        """📐 v84_169: link de um vídeo (YouTube, TikTok…) → a transcrição dele vira o roteiro exemplo."""
        import tarefas_bg
        import roteiros_yt as ry
        url = str((request.get_json(silent=True) or {}).get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return jsonify({"erro": "Cole o link do vídeo."}), 400
        if not _proj(pid):
            return jsonify({"erro": "Projeto não encontrado."}), 404

        def _rodar(t):
            t.progresso("lendo a transcrição do vídeo exemplo…")
            pasta = os.path.join(ds._pasta(base_dir, pid), "transcricoes_links")
            tr = ry.extrair_transcricao(url, pasta, on_log=lambda m: t.progresso(str(m)[:150]))
            texto = ry.texto_da_transcricao(tr, com_tempo=False).strip()
            if not texto:
                raise ValueError("o vídeo não tem fala/legenda")
            with _TRAVA:
                p = _proj(pid)
                p["config"]["referencia"] = texto[:60000]
                ds.salvar(base_dir, p)
            return {"caracteres": len(texto), "titulo": tr.get("titulo") or ""}
        tid = tarefas_bg.iniciar("dossie_referencia", "📐 Roteiro exemplo (transcrição)", _rodar, pagina=f"/modelos-video/{pid}")
        return jsonify({"ok": True, "tarefa": tid})

    @app.route("/modelos-video/<pid>/fontes", methods=["POST"])
    def dossie_fontes(pid: str):
        """Um ou vários links (um por linha) de matérias — cada um é lido e tem as imagens baixadas em segundo plano.
        Link de vídeo (YouTube, TikTok, Instagram, Vimeo…) não vira matéria: a transcrição dele vai pras anotações (v84_161)."""
        c = request.get_json(silent=True) or {}
        urls = [u.strip() for u in str(c.get("urls") or "").split("\n") if u.strip()]
        if not urls:
            return jsonify({"erro": "Cole pelo menos um link."}), 400
        videos = [u for u in urls if ds.eh_link_de_video(u)] if c.get("videos_transcrever", True) is not False else []
        urls = [u for u in urls if u not in videos]
        tarefa = _transcrever_videos(pid, videos[:20]) if videos and _proj(pid) else None
        if not urls:
            return jsonify({"ok": bool(tarefa), "novas": [], "erros": [], "videos": len(videos[:20]), "tarefa_videos": tarefa})
        novas, erros = [], []
        with _TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            for u in urls[:30]:
                try:
                    novas.append(ds.adicionar_fonte(p, u)["id"])
                except (ds.DossieError, vd.VendaError) as exc:
                    erros.append(f"{u[:60]}: {exc}")
            ds.salvar(base_dir, p)
        for fid in novas:
            _processar(pid, fid)
        return jsonify({"ok": bool(novas) or bool(tarefa), "novas": novas, "erros": erros, "videos": len(videos[:20]), "tarefa_videos": tarefa})

    @app.route("/modelos-video/<pid>/fonte-arquivo", methods=["POST"])
    def dossie_fonte_arquivo(pid: str):
        """📄 Fontes por arquivo: TXT, PDF (com páginas), EPUB, DOCX, SRT… (pode mandar vários)."""
        arqs = [a for a in request.files.getlist("arquivo") if a and a.filename]
        if not arqs:
            return jsonify({"erro": "Escolha o arquivo."}), 400
        paginas = (request.form.get("paginas") or "").strip()
        novas, erros = [], []
        with _TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            for a in arqs[:20]:
                try:
                    novas.append(ds.adicionar_fonte_arquivo(base_dir, p, a.filename, a.read(), paginas)["id"])
                except ds.DossieError as exc:
                    erros.append(f"{a.filename}: {exc}")
            ds.salvar(base_dir, p)
        for fid in novas:
            _processar(pid, fid)
        return jsonify({"ok": bool(novas), "novas": novas, "erros": erros}), (200 if novas else 400)

    @app.route("/modelos-video/<pid>/fonte/<fid>", methods=["POST", "DELETE"])
    def dossie_fonte(pid: str, fid: str):
        with _TRAVA:
            p = _proj(pid)
            f = next((x for x in (p or {}).get("fontes") or [] if x["id"] == fid), None)
            if not f:
                return jsonify({"erro": "Fonte não encontrada."}), 404
            if request.method == "DELETE":
                apagar_imgs = (request.args.get("imagens") == "1")
                p["fontes"] = [x for x in p["fontes"] if x is not f]
                if f.get("arquivo"):
                    try:
                        os.remove(os.path.join(ds._pasta(base_dir, pid), "fontes", os.path.basename(f["arquivo"])))
                    except OSError:
                        pass
                if apagar_imgs:
                    for m in [m for m in p["midias"] if m.get("fonte") == fid]:
                        cam = ds.caminho_midia(base_dir, p, m)
                        if cam:
                            try:
                                os.remove(cam)
                            except OSError:
                                pass
                    p["midias"] = [m for m in p["midias"] if m.get("fonte") != fid]
                ds.salvar(base_dir, p)
                return jsonify({"ok": True})
            c = request.get_json(silent=True) or {}
            if "paginas" in c:
                f["paginas"] = str(c.get("paginas") or "").strip()[:60]
            f.update(estado="na fila", erro=None)
            ds.salvar(base_dir, p)
        _processar(pid, fid)  # ler de novo
        return jsonify({"ok": True})

    @app.route("/modelos-video/<pid>/midia", methods=["POST"])
    def dossie_midia_pc(pid: str):
        arq = request.files.get("arquivo")
        desc = (request.form.get("descricao") or "").strip()
        if not arq or not arq.filename:
            return jsonify({"erro": "Escolha o arquivo."}), 400
        import ia_servico
        com_ia = ia_servico.ativo("dossie_imagens")
        if not desc and not com_ia:  # 🤖 com a IA ligada, ela descreve sozinha (passo D)
            return jsonify({"erro": "Diga o que é esse arquivo (ex.: \"foto da casa onde o crime aconteceu\")."}), 400
        tipo = vd.tipo_do_arquivo(arq.filename)
        if not tipo:
            return jsonify({"erro": "Só fotos (jpg, png, webp…) e vídeos (mp4, mov, webm…)."}), 400
        os.makedirs(ds.pasta_midias(base_dir, pid), exist_ok=True)
        dest = os.path.join(ds.pasta_midias(base_dir, pid), f"pc_{uuid.uuid4().hex[:6]}_{secure_filename(arq.filename) or 'arquivo'}")
        with _TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            arq.save(dest)
            m = ds.adicionar_midia(p, tipo=tipo, origem="pc", arquivo=os.path.basename(dest), nome=arq.filename, descricao=desc,
                                   usar="descricao" if desc else "ambos")
            _q = (request.form.get("pergunta") or "").strip()[:10]  # 📸 resposta a uma pergunta das fotos pro roteiro
            if _q:
                _alvo = next((x.get("alvo") for x in (p.get("fotos_roteiro") or {}).get("perguntas") or [] if x["id"] == _q), "")
                m["pergunta"], m["pergunta_alvo"] = _q, (_alvo or "")[:120]
            ds.salvar(base_dir, p)
        if com_ia:
            threading.Thread(target=lambda: ds.ia_analisar_imagens(base_dir, pid, trava=_TRAVA, ids=[m["id"]]), daemon=True).start()
        return jsonify({"ok": True, "midia": m, "ia": com_ia})

    @app.route("/modelos-video/<pid>/ia/imagens", methods=["POST"])
    def dossie_ia_imagens(pid: str):
        """🤖 Ficha de todas as imagens que ainda não têm (ou de todas, com refazer) — em segundo plano."""
        import ia_servico
        motivo = ia_servico.motivo_desligado("dossie_imagens")
        if motivo:
            return jsonify({"erro": "IA: " + motivo}), 400
        if not _proj(pid):
            return jsonify({"erro": "Projeto não encontrado."}), 404
        refazer = bool((request.get_json(silent=True) or {}).get("refazer"))

        def rodar():
            try:
                r = ds.ia_analisar_imagens(base_dir, pid, trava=_TRAVA, refazer=refazer)
            except Exception as exc:  # noqa: BLE001
                r = {"erro": str(exc)[:300]}
            _IA_ESTADO[pid] = {"rodando": False, **r}
            import notificacoes
            notificacoes.avisar(("❌ " if r.get("erro") else "✅ ") + "Modelo de vídeo — fichas das imagens pela IA",
                                str(r.get("erro") or ""), f"/modelos-video/{pid}", "erro" if r.get("erro") else "ok", tipo="dossie")
        _IA_ESTADO[pid] = {"rodando": True}
        threading.Thread(target=rodar, daemon=True).start()
        return jsonify({"ok": True})

    @app.route("/modelos-video/<pid>/ia/estado")
    def dossie_ia_estado(pid: str):
        return jsonify(_IA_ESTADO.get(pid) or {"rodando": False})

    @app.route("/modelos-video/<pid>/ia/marcas", methods=["POST"])
    def dossie_ia_marcas(pid: str):
        """🤖 Passo E: as marcas [I3] do roteiro que não combinam com a imagem."""
        import ia_servico
        motivo = ia_servico.motivo_desligado("dossie_marcas")
        if motivo:
            return jsonify({"erro": "IA: " + motivo}), 400
        p = _proj(pid)
        if not p or not p.get("resultado"):
            return jsonify({"erro": "Leia a resposta da IA (o roteiro) primeiro."}), 400
        r = ds.ia_conferir_marcas(p)
        if r is None:
            return jsonify({"erro": "A IA não respondeu agora — tente de novo."}), 200
        with _TRAVA:
            p = _proj(pid)
            p["ia_marcas"] = r
            ds.salvar(base_dir, p)
        return jsonify({"ok": True, "problemas": r})

    @app.route("/modelos-video/<pid>/midia-url", methods=["POST"])
    def dossie_midia_url(pid: str):
        """Link de foto/vídeo (baixa) ou de página (OG + imagem da página)."""
        c = request.get_json(silent=True) or {}
        url, desc = str(c.get("url") or "").strip(), str(c.get("descricao") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return jsonify({"erro": "Cole um link que comece com http:// ou https://."}), 400
        pasta, nome_base = ds.pasta_midias(base_dir, pid), f"url_{uuid.uuid4().hex[:6]}"
        og, arquivo, tipo = None, "", "link"
        if vd.tipo_do_arquivo(url.split("?")[0]):
            try:
                cam, tipo = vd.baixar_arquivo(url, pasta, nome_base)
                arquivo = os.path.basename(cam)
            except vd.VendaError as exc:
                return jsonify({"erro": str(exc)}), 502
        else:
            try:
                html, final = vd.baixar_html(url, navegador=False)
                og = vd.ler_og(html, final)
            except vd.VendaError:
                if not desc:
                    return jsonify({"erro": "Não consegui abrir esse link. Descreva o que ele é pra usar mesmo assim."}), 502
            for u in ((og or {}).get("video"), (og or {}).get("imagem")):
                if not u:
                    continue
                try:
                    cam, tipo = vd.baixar_arquivo(u, pasta, nome_base)
                    arquivo = os.path.basename(cam)
                    break
                except vd.VendaError:
                    continue
        with _TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            m = ds.adicionar_midia(p, tipo=tipo if arquivo else "link", origem="url", url=url, arquivo=arquivo,
                                   nome=(og or {}).get("titulo") or url[-80:],
                                   og={"titulo": og.get("titulo"), "descricao": og.get("descricao")} if og and (og.get("titulo") or og.get("descricao")) else None,
                                   descricao=desc, usar=c.get("usar"))
            ds.salvar(base_dir, p)
        return jsonify({"ok": True, "midia": m, "precisa_descricao": not (m.get("descricao") or m.get("og"))})

    @app.route("/modelos-video/<pid>/texto", methods=["POST"])
    def dossie_texto(pid: str):
        c = request.get_json(silent=True) or {}
        conteudo, desc = str(c.get("conteudo") or "").strip(), str(c.get("descricao") or "").strip()
        if not conteudo:
            return jsonify({"erro": "Escreva o texto."}), 400
        if not desc:
            return jsonify({"erro": "Diga o que é esse texto (ex.: \"trecho do processo\", \"depoimento\", \"linha do tempo\")."}), 400
        with _TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            m = ds.adicionar_midia(p, tipo="texto", origem="pc", conteudo=conteudo, descricao=desc, usar="descricao")
            ds.salvar(base_dir, p)
        return jsonify({"ok": True, "midia": m})

    @app.route("/modelos-video/<pid>/midia/<mid>", methods=["POST", "DELETE"])
    def dossie_midia_editar(pid: str, mid: str):
        with _TRAVA:
            p = _proj(pid)
            m = ds.midia(p, mid) if p else None
            if not m:
                return jsonify({"erro": "Mídia não encontrada."}), 404
            if request.method == "DELETE":
                cam = ds.caminho_midia(base_dir, p, m)
                p["midias"] = [x for x in p["midias"] if x is not m]
                if cam:
                    try:
                        os.remove(cam)
                    except OSError:
                        pass
            else:
                c = request.get_json(silent=True) or {}
                if "descricao" in c:
                    m["descricao"] = str(c.get("descricao") or "").strip()[:2000]
                if "conteudo" in c and m["tipo"] == "texto":
                    m["conteudo"] = str(c.get("conteudo") or "").strip()[:12000]
                if c.get("usar") in ("og", "descricao", "ambos"):
                    m["usar"] = c["usar"]
                if "descartada" in c:  # 🤖 recuperar (ou descartar) uma imagem que a IA marcou como lixo/anúncio
                    m["descartada"] = bool(c["descartada"])
                    if not m["descartada"]:
                        m.pop("duplicada_de", None)
            ds.salvar(base_dir, p)
        return jsonify({"ok": True})

    @app.route("/modelos-video/<pid>/apagar-midias", methods=["POST"])
    def dossie_apagar_varias(pid: str):
        ids = {str(x).upper() for x in (request.get_json(silent=True) or {}).get("ids") or []}
        with _TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            for m in [m for m in p["midias"] if m["id"].upper() in ids]:
                cam = ds.caminho_midia(base_dir, p, m)
                if cam:
                    try:
                        os.remove(cam)
                    except OSError:
                        pass
            p["midias"] = [m for m in p["midias"] if m["id"].upper() not in ids]
            ds.salvar(base_dir, p)
        return jsonify({"ok": True})

    @app.route("/modelos-video/<pid>/arquivo/<mid>")
    def dossie_arquivo(pid: str, mid: str):
        p = _proj(pid)
        cam = ds.caminho_midia(base_dir, p, ds.midia(p, mid)) if p else None
        if not cam:
            abort(404)
        r = send_file(cam, conditional=True)
        r.headers["Cache-Control"] = "no-cache"  # mesmo ID pode virar outra foto: o navegador sempre confere
        return r

    @app.route("/modelos-video/<pid>/prompt", methods=["POST"])
    def dossie_prompt(pid: str):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            texto = ds.prompt_roteiro(p, base=base_dir)
        except ds.DossieError as exc:
            return jsonify({"erro": str(exc)}), 400
        pend = [f["id"] for f in p.get("fontes") or [] if f.get("estado") not in ("pronta", "erro")]
        sem = [m["id"] for m in p.get("midias") or [] if not (m.get("descricao") or m.get("og") or m.get("legenda"))]
        avisos = []
        if pend:
            avisos.append("Ainda baixando: " + ", ".join(pend) + " (gere de novo quando terminar).")
        if sem:
            avisos.append("Sem descrição: " + ", ".join(sem[:20]) + ".")
        if len(texto) > 180000:
            avisos.append(f"Prompt grande ({len(texto) // 1000} mil caracteres) — algumas IAs cortam; tire fontes repetidas se precisar.")
        return jsonify({"ok": True, "prompt": texto, "caracteres": len(texto), "aviso": " ".join(avisos)})

    @app.route("/modelos-video/<pid>/resultado", methods=["POST"])
    def dossie_resultado(pid: str):
        with _TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            try:
                p["resultado"] = ds.ler_resposta(str((request.get_json(silent=True) or {}).get("texto") or ""), p)
            except ds.DossieError as exc:
                return jsonify({"erro": str(exc)}), 400
            ds.marcar_mudanca(p, "🤖 resposta da IA", "roteiro lido da resposta da IA")
            ds.salvar(base_dir, p)
        return jsonify({"ok": True, "projeto": _json_proj(p)})

    # ------------------------------------------------------------------ ✍️ roteiro em partes (v84_97)
    @app.route("/modelos-video/<pid>/partes/completar", methods=["POST"])
    def dossie_partes_completar(pid: str):
        """📏 Roteiro curto: corta nos capítulos pra reescrever só as partes curtas, uma por vez."""
        with _TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            try:
                p["resultado"] = ds.iniciar_completar(p)
            except ds.DossieError as exc:
                return jsonify({"erro": str(exc)}), 400
            ds.salvar(base_dir, p)
        return jsonify({"ok": True, "projeto": _json_proj(p)})

    @app.route("/modelos-video/<pid>/partes/<int:k>/prompt", methods=["POST"])
    def dossie_parte_prompt(pid: str, k: int):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            texto = ds.prompt_parte(p, k, com_fontes=bool((request.get_json(silent=True) or {}).get("com_fontes")))
        except ds.DossieError as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True, "prompt": texto, "caracteres": len(texto)})

    @app.route("/modelos-video/<pid>/partes/<int:k>/texto", methods=["POST"])
    def dossie_parte_texto(pid: str, k: int):
        with _TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            try:
                p["resultado"] = ds.salvar_parte(p, k, str((request.get_json(silent=True) or {}).get("texto") or ""))
            except ds.DossieError as exc:
                return jsonify({"erro": str(exc)}), 400
            ds.marcar_mudanca(p, "✍️ partes montadas", f"parte {k} colada")
            ds.salvar(base_dir, p)
        return jsonify({"ok": True, "projeto": _json_proj(p)})

    @app.route("/modelos-video/<pid>/partes/montar", methods=["POST"])
    def dossie_partes_montar(pid: str):
        """Junta as partes que já têm texto (mesmo com alguma curta)."""
        with _TRAVA:
            p = _proj(pid)
            if not p or not (p.get("resultado") or {}).get("partes"):
                return jsonify({"erro": "Não tem partes."}), 404
            if any(not x.get("texto") for x in p["resultado"]["partes"]):
                return jsonify({"erro": "Ainda tem parte sem texto."}), 400
            p["resultado"] = ds.montar_partes(p)
            ds.marcar_mudanca(p, "✍️ partes montadas", "as partes juntadas num roteiro só")
            ds.salvar(base_dir, p)
        return jsonify({"ok": True, "projeto": _json_proj(p)})

    @app.route("/modelos-video/<pid>/partes/ia", methods=["POST"])
    def dossie_partes_ia(pid: str):
        """🤖 A IA do site escreve as partes que faltam (ou as curtas), uma de cada vez, em segundo plano."""
        import ia_servico as ia
        import roteiro_partes as rp
        import tarefas_bg
        p = _proj(pid)
        if not p or not (p.get("resultado") or {}).get("partes"):
            return jsonify({"erro": "Não tem partes."}), 404
        if not ia.ativo("roteiros"):
            return jsonify({"erro": "A IA está desligada (" + (ia.motivo_desligado("roteiros") or "ligue em 🤖 IA") + ")."}), 400

        def rodar(t):
            feitas = 0
            while True:
                with _TRAVA:
                    q = _proj(pid)
                    pend = rp.falta((q.get("resultado") or {}).get("partes") or [])
                if not pend:
                    break
                k = pend[0]
                total = len(q["resultado"]["partes"])
                t.progresso(f"✍️ escrevendo a parte {k} de {total}…")
                prompt = ds.prompt_parte(q, k, com_fontes=True)
                system = ("Você é roteirista de documentários. Responda SÓ com o texto narrado pedido, sem JSON, sem markdown, "
                          "sem título e sem comentários.")
                texto = ia.chamar("roteiros", system, prompt, schema=None, max_tokens=16000, effort="medium", timeout=900)
                if not texto:
                    raise RuntimeError("A IA não respondeu (" + (ia.motivo_desligado("roteiros") or "veja 🤖 IA") + ").")
                with _TRAVA:
                    q = _proj(pid)
                    antes = next((x for x in q["resultado"]["partes"] if x["k"] == k), {})
                    ja_tentou = antes.get("tentativas", 0)
                    q["resultado"] = ds.salvar_parte(q, k, texto)
                    parte = next((x for x in (q["resultado"].get("partes") or []) if x["k"] == k), None)
                    if parte is not None:
                        parte["tentativas"] = ja_tentou + 1
                        if parte["status"] in ("curta", "longa") and parte["tentativas"] >= 2:
                            parte["status"] = "pronta"  # tentou 2x: aceita e segue (avisa na lista)
                            parte["aceita_curta"] = True
                    ds.salvar(base_dir, q)
                feitas += 1
                if feitas > 40:
                    break
            with _TRAVA:
                q = _proj(pid)
                if q and (q.get("resultado") or {}).get("partes") and all(x.get("texto") for x in q["resultado"]["partes"]):
                    q["resultado"] = ds.montar_partes(q)
                    ds.marcar_mudanca(q, "✍️ partes montadas", "🤖 a IA escreveu as partes")
                    ds.salvar(base_dir, q)
            return {"partes": feitas}

        tid = tarefas_bg.iniciar("roteiro_partes", "✍️ Roteiro em partes (🤖 IA)", rodar, pagina=f"/modelos-video/{pid}")
        return jsonify({"ok": True, "tarefa": tid})

    @app.route("/modelos-video/<pid>/prompt-completar", methods=["POST"])
    def dossie_prompt_completar(pid: str):
        """📏 O roteiro ficou curto: prompt pra IA esticar até o tamanho escolhido."""
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            texto = ds.prompt_completar(p)
        except ds.DossieError as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True, "prompt": texto, "caracteres": len(texto)})

    @app.route("/modelos-video/<pid>/roteiro-editado", methods=["POST"])
    def dossie_roteiro_editado(pid: str):
        """✏️ Roteiro mexido à mão (ex.: mudar o [[VENDA]] / [[INSCREVA]] de lugar)."""
        with _TRAVA:
            p = _proj(pid)
            if not p or not p.get("resultado"):
                return jsonify({"erro": "Ainda não tem roteiro."}), 404
            try:
                p["resultado"] = ds.roteiro_editado(p, str((request.get_json(silent=True) or {}).get("roteiro") or ""))
            except ds.DossieError as exc:
                return jsonify({"erro": str(exc)}), 400
            ds.marcar_mudanca(p, "✏️ edição manual")
            ds.salvar(base_dir, p)
        return jsonify({"ok": True, "projeto": _json_proj(p)})

    @app.route("/modelos-video/<pid>/produto-para-venda", methods=["POST"])
    def dossie_produto_para_venda(pid: str):
        """🛒 O produto que a IA sugeriu vira um projeto de Vídeo de venda (pra fazer o vídeo da [[VENDA]])."""
        p = _proj(pid)
        prod = ((p or {}).get("resultado") or {}).get("produto_sugerido")
        if not prod:
            return jsonify({"erro": "A IA não sugeriu produto neste roteiro."}), 404
        from urllib.parse import quote_plus
        v = vd.criar(base_dir, nome=f"{prod['nome']} — {p.get('tema') or ''}"[:160])
        v["produto"]["titulo"] = prod["nome"]
        v["produto"]["descricao"] = prod.get("por_que") or ""
        v["config"]["idioma"] = p["config"].get("idioma") or "pt"
        v["config"]["publico"] = f"quem assiste vídeos de {(ds.MODELOS.get(p['config']['modelo']) or {}).get('nome', '')} sobre {p.get('tema') or ''}"[:400]
        if prod.get("chamada"):
            vd.adicionar_midia(v, tipo="texto", origem="pc", conteudo=prod["chamada"], descricao="ideia de chamada de venda sugerida pela IA")
        vd.salvar(base_dir, v)
        return jsonify({"ok": True, "url": f"/vendas/{v['id']}",
                        "amazon": "https://www.amazon.com.br/s?k=" + quote_plus(prod.get("busca") or prod["nome"])})

    @app.route("/modelos-video/<pid>/excluir", methods=["POST"])
    def dossie_excluir(pid: str):
        with _TRAVA:
            ds.excluir(base_dir, pid)
        return redirect(url_for("dossies_page"))
