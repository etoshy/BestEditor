"""📰 Rotas do Buscador de casos e notícias (pesquisa_casos.py) — v84_165."""
from __future__ import annotations

from typing import Any, Dict

import pesquisa_casos as pc


def registrar(app, base_dir: str) -> None:
    from flask import jsonify, redirect, render_template, request, url_for

    def _corpo() -> Dict[str, Any]:
        return request.get_json(silent=True, force=True) or {}  # force: o userscript do Google manda como text/plain

    def _site() -> str:
        return request.host_url.rstrip("/")

    def _proj(pid: str):
        try:
            return pc.carregar(base_dir, pid)
        except pc.PesquisaErro:
            return None

    def _dados(p: Dict[str, Any]) -> Dict[str, Any]:
        rs = p.get("resultados") or []
        cont = {}
        for r in rs:
            cont[r["tipo"]] = cont.get(r["tipo"], 0) + 1
        return dict(p, contagem=cont, marcados=sum(1 for r in rs if r.get("marcado", True)))

    @app.context_processor
    def _pesquisas_no_template():
        return {"pesquisas_lista": lambda: pc.listar(base_dir)}

    @app.route("/pesquisas")
    def pesquisas_page():
        import dossies as ds
        return render_template("pesquisas.html", pesquisas=pc.listar(base_dir), categorias=pc.CATEGORIAS,
                               idiomas=pc.IDIOMAS_BUSCA, erro=request.args.get("erro"), dossies=ds.listar(base_dir)[:30])

    @app.route("/pesquisas/nova", methods=["POST"])
    def pesquisa_nova():
        f = request.form
        try:
            p = pc.criar(base_dir, f.get("tema", ""), f.get("idioma") or "en", f.get("categoria") or "noticias")
        except pc.PesquisaErro as exc:
            return redirect(url_for("pesquisas_page", erro=str(exc)))
        t = pc.traduzir_termo(p["tema"], p["idioma"])
        if t:
            p["termo"] = t
            pc.salvar(base_dir, p)
        return redirect(url_for("pesquisa_detalhe", pid=p["id"]))

    @app.route("/pesquisas/<pid>")
    def pesquisa_detalhe(pid: str):
        p = _proj(pid)
        if not p:
            return redirect(url_for("pesquisas_page", erro="Pesquisa não encontrada."))
        import dossies as ds
        import ia_servico as ia
        return render_template("pesquisa_detalhe.html", p=_dados(p), categorias=pc.CATEGORIAS, idiomas=pc.IDIOMAS_BUSCA,
                               dossies=ds.listar(base_dir)[:40], ia_ligada=ia.ativo("buscas"))

    @app.route("/pesquisas/<pid>/dados")
    def pesquisa_dados(pid: str):
        p = _proj(pid)
        return jsonify(_dados(p)) if p else (jsonify({"erro": "Pesquisa não encontrada."}), 404)

    @app.route("/pesquisas/<pid>/config", methods=["POST"])
    def pesquisa_config(pid: str):
        c = _corpo()
        with pc._TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"erro": "Pesquisa não encontrada."}), 404
            for k, lim in (("tema", 200), ("termo", 200)):
                if isinstance(c.get(k), str) and c[k].strip():
                    p[k] = " ".join(c[k].split())[:lim]
            if c.get("idioma") in pc.IDIOMAS_BUSCA:
                p["idioma"] = c["idioma"]
            if c.get("categoria") in pc.CATEGORIAS:
                p["categoria"] = c["categoria"]
            pc.salvar(base_dir, p)
        return jsonify({"ok": True})

    @app.route("/pesquisas/<pid>/traduzir", methods=["POST"])
    def pesquisa_traduzir(pid: str):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Pesquisa não encontrada."}), 404
        t = pc.traduzir_termo(p["tema"], str(_corpo().get("idioma") or p["idioma"]))
        if not t:
            return jsonify({"erro": "A IA está desligada (🤖 IA nas buscas e modelos) — escreva o termo à mão."}), 400
        return jsonify({"ok": True, "termo": t})

    @app.route("/pesquisas/<pid>/youtube", methods=["POST"])
    def pesquisa_youtube(pid: str):
        """▶ Os mais vistos do YouTube (em segundo plano: o yt-dlp leva uns segundos)."""
        import tarefas_bg
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Pesquisa não encontrada."}), 404
        c = _corpo()
        termo = " ".join(str(c.get("termo") or p.get("termo") or p["tema"]).split())[:200]
        idioma = c.get("idioma") if c.get("idioma") in pc.IDIOMAS_BUSCA else p["idioma"]
        qtd = int(c.get("quantidade") or 20)

        def _rodar(t):
            t.progresso("buscando os mais vistos no YouTube…")
            r = pc.buscar_youtube(termo, idioma, qtd)
            with pc._TRAVA:
                q = pc.carregar(base_dir, pid)
                q["youtube"] = r
                pc.salvar(base_dir, q)
            return {"videos": len(r["videos"]), "sugestao_min": r.get("sugestao_min")}
        tid = tarefas_bg.iniciar("pesquisa_youtube", "▶ Mais vistos no YouTube: " + termo[:60], _rodar,
                                 pagina=f"/pesquisas/{pid}", avisar=False)
        return jsonify({"ok": True, "tarefa": tid})

    @app.route("/pesquisas/<pid>/youtube/estatisticas", methods=["POST"])
    def pesquisa_youtube_stats(pid: str):
        """Recalcula a média (com ou sem Shorts, top N)."""
        c = _corpo()
        with pc._TRAVA:
            p = _proj(pid)
            if not p or not p.get("youtube"):
                return jsonify({"erro": "Busque no YouTube primeiro."}), 400
            yt = p["youtube"]
            yt.update(pc.estatisticas(yt.get("videos") or [], c.get("sem_shorts", True) is not False, int(c.get("top") or 5)))
            pc.salvar(base_dir, p)
        return jsonify({"ok": True, "youtube": yt})

    @app.route("/pesquisas/<pid>/google", methods=["POST"])
    def pesquisa_google(pid: str):
        """🌐 Abre a busca no Google no navegador do site (o Brave das imagens, com o userscript)."""
        import navegador_imagens as ni
        from site_config import load_site_config
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Pesquisa não encontrada."}), 404
        c = _corpo()
        cat = c.get("categoria") if c.get("categoria") in pc.CATEGORIAS else p["categoria"]
        termo = " ".join(str(c.get("termo") or p.get("termo") or p["tema"]).split())[:200]
        pagina = max(1, min(10, int(c.get("pagina") or 1)))
        url = pc.url_google(termo, cat, p["idioma"], pc.destino(_site(), pid, "📰 " + p["tema"]), pagina)
        r = ni.abrir(base_dir, [url], load_site_config(), chaves=["pesquisa"], pid="pesq_" + pid)
        if not r.get("ok"):
            return jsonify({"ok": False, "erro": r.get("erro"), "url": url}), 400
        return jsonify({"ok": True, "navegador": r.get("navegador"), "url": url, "aviso": r.get("aviso") or ""})

    @app.route("/pesquisas/<pid>/resultados", methods=["POST"])
    def pesquisa_resultados(pid: str):
        """Recebe do userscript (Google no Brave do site) os resultados marcados. Página 2, 3… se juntam."""
        c = _corpo()
        itens = pc.resolver_itens([x for x in (c.get("itens") or []) if isinstance(x, dict)][:200])  # /goto → link de verdade
        with pc._TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"ok": False, "erro": "Pesquisa não encontrada."}), 404
            r = pc.adicionar_resultados(p, itens, origem="google", pagina=str(c.get("pagina") or ""))
            pc.salvar(base_dir, p)
        try:
            import notificacoes
            if r["novos"]:
                notificacoes.avisar(f"📰 {r['novos']} resultado(s) novos em “{p['tema'][:60]}”", f"total: {r['total']}",
                                    f"/pesquisas/{pid}", "ok", tipo="pesquisa")
        except Exception:  # noqa: BLE001
            pass
        return jsonify({"ok": True, **r})

    @app.route("/pesquisas/<pid>/colar", methods=["POST"])
    def pesquisa_colar(pid: str):
        """Links (um por linha) ou o HTML inteiro da página do Google."""
        texto = str(_corpo().get("texto") or "")
        if not texto.strip():
            return jsonify({"erro": "Cole os links ou o HTML."}), 400
        itens = pc.resolver_itens(pc.extrair_de_texto(texto))  # v84_167: o Google novo esconde o link em /goto?url=…
        if not itens:
            return jsonify({"erro": "Não achei nenhum link (fora os do Google) no que foi colado."}), 400
        with pc._TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"erro": "Pesquisa não encontrada."}), 404
            r = pc.adicionar_resultados(p, itens, origem="html" if "<" in texto[:3000] else "colado")
            pc.salvar(base_dir, p)
        return jsonify({"ok": True, "achados": len(itens), **r})

    @app.route("/pesquisas/<pid>/item/<rid>", methods=["POST", "DELETE"])
    def pesquisa_item(pid: str, rid: str):
        with pc._TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"erro": "Pesquisa não encontrada."}), 404
            if request.method == "DELETE":
                p["resultados"] = [r for r in p["resultados"] if r["id"] != rid]
            else:
                c = _corpo()
                for r in p["resultados"]:
                    if r["id"] == rid:
                        if "marcado" in c:
                            r["marcado"] = bool(c["marcado"])
                        if c.get("tipo") in ("materia", "video", "social", "documento"):
                            r["tipo"] = c["tipo"]
            pc.salvar(base_dir, p)
        return jsonify({"ok": True})

    @app.route("/pesquisas/<pid>/marcar", methods=["POST"])
    def pesquisa_marcar(pid: str):
        """Marca/desmarca todos (ou só de um tipo); "apagar_desmarcados" limpa a lista."""
        c = _corpo()
        with pc._TRAVA:
            p = _proj(pid)
            if not p:
                return jsonify({"erro": "Pesquisa não encontrada."}), 404
            if c.get("apagar_desmarcados"):
                p["resultados"] = [r for r in p["resultados"] if r.get("marcado", True)]
            else:
                for r in p["resultados"]:
                    if not c.get("tipo") or r["tipo"] == c["tipo"]:
                        r["marcado"] = bool(c.get("marcado", True))
            pc.salvar(base_dir, p)
        return jsonify({"ok": True})

    @app.route("/pesquisas/<pid>/para-modelo", methods=["POST"])
    def pesquisa_para_modelo(pid: str):
        """🕵️ Leva os marcados pra um Modelo de vídeo (novo ou existente). Devolve os links: a página manda pro
        /modelos-video/<id>/fontes, que lê as matérias e transcreve os vídeos (pras anotações)."""
        import dossies as ds
        import dossies_rotas
        c = _corpo()
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Pesquisa não encontrada."}), 404
        urls = [r["url"] for r in pc.marcados(p)]
        yt = p.get("youtube") or {}
        top_yt = max(0, min(10, int(c.get("youtube_top") or 0)))
        if top_yt:
            vids = [v for v in yt.get("videos") or [] if not v.get("short")][:top_yt]
            urls += [v["url"] for v in vids if v["url"] not in urls]
        if not urls:
            return jsonify({"erro": "Nenhum resultado marcado (nem vídeo do YouTube escolhido)."}), 400
        destino = str(c.get("modelo") or "novo")
        with dossies_rotas._TRAVA:
            if destino == "novo":
                d = ds.criar(base_dir, tema=p["tema"])
                try:
                    minutos = float(c.get("minutos") or yt.get("sugestao_min") or 0)
                except (TypeError, ValueError):
                    minutos = 0
                if minutos:
                    d["config"]["minutos"] = max(0.5, min(120.0, minutos))
                if yt.get("videos"):
                    linhas = [f"Pesquisa no YouTube (mais vistos sobre “{yt.get('termo')}”): média dos {yt.get('usados') or 5} mais vistos "
                              f"= {yt.get('media_fmt') or '?'} — tempo sugerido ≈ {yt.get('sugestao_min') or '?'} min."]
                    d["roteiro_base"] = "\n".join(linhas)
                ds.salvar(base_dir, d)
            else:
                try:
                    d = ds.carregar(base_dir, destino)
                except ds.DossieError:
                    return jsonify({"erro": "Modelo de vídeo não encontrado."}), 404
        with pc._TRAVA:
            q = pc.carregar(base_dir, pid)
            q.setdefault("modelos", []).append({"id": d["id"], "quando": __import__("time").time(), "links": len(urls)})
            pc.salvar(base_dir, q)
        return jsonify({"ok": True, "modelo": d["id"], "urls": urls, "link": f"/modelos-video/{d['id']}"})

    @app.route("/pesquisas/<pid>/excluir", methods=["POST"])
    def pesquisa_excluir(pid: str):
        pc.excluir(base_dir, pid)
        return redirect(url_for("pesquisas_page"))
