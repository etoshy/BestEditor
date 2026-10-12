#!/usr/bin/env python3
"""
Rotas da aba "Analisar canal" (/api/canal/*).

Registradas por ``app.py`` com ``canal_api.registrar(app, JOBS, JOBS_LOCK, novo_job, LogStream)``. Reaproveitam o mesmo
mecanismo de jobs e log ao vivo das outras abas (``/api/logs/<job_id>``) e a mesma trava de UMA coleta por vez.
Nenhuma rota usa API paga: as etapas de IA só montam o prompt e validam o JSON que você cola de volta.
"""

import contextlib
import re
import threading

from flask import jsonify, request
from playwright.sync_api import sync_playwright

import canal
import ideias
import ideias_api
import yt_scraper as core

MIN_VIDEOS, MAX_VIDEOS, PADRAO_VIDEOS = 10, 200, 100


def _nome_do_canal(page):
    """O título da página do canal é "Nome - YouTube"."""
    try:
        titulo = (page.title() or "").strip()
    except Exception:
        return ""
    return re.sub(r"\s*-\s*YouTube\s*$", "", titulo, flags=re.I).strip()


def coletar_canal(page, url, n_videos):
    """Cabeçalho (inscritos, views totais, data de criação) + os últimos ``n_videos`` vídeos, com as funções
    já usadas pelas outras abas."""
    print(f"Lendo o canal: {url}")
    registro = {"canal_url": url}
    sobre = core.scrape_channel_about(page, url)
    registro.update(sobre)
    registro["canal"] = _nome_do_canal(page)
    print(f"  {registro['canal'] or '(nome não encontrado)'} — {sobre.get('inscritos_text') or 'inscritos não encontrados'}")
    registro.update(core.enrich_channel_details(page, url, n_frequencia=n_videos, total_videos=sobre.get("n_videos")))
    return registro


def corpo_analise(url, n_videos, headless, mutar, db_path=None):
    def corpo():
        with sync_playwright() as p:
            browser, _context, page = ideias_api._abrir_navegador(p, headless, mutar)
            try:
                registro = coletar_canal(page, url, n_videos)
            finally:
                browser.close()
        lidos = len(registro.get("amostra_videos") or [])
        if not lidos:
            raise RuntimeError("Não consegui ler os vídeos desse canal. Confira o link e se o canal tem vídeos públicos, e tente de novo.")
        analise_id = canal.salvar_analise(registro, db_path=db_path)
        print(f"Análise salva (#{analise_id}): {lidos} vídeos lidos.")
        return {"analise_id": analise_id, "n_videos_lidos": lidos}
    return corpo


def registrar(app, jobs, jobs_lock, novo_job, LogStream, db_path=None):
    """Adiciona as rotas /api/canal/* ao app Flask."""

    def executar(job_id, corpo):
        log = LogStream(job_id)
        with jobs_lock:
            jobs[job_id]["status"] = "rodando"
        try:
            with contextlib.redirect_stdout(log):
                resumo = corpo()
            with jobs_lock:
                jobs[job_id]["resultado"] = resumo
                jobs[job_id]["status"] = "concluido"
        except Exception as exc:
            with jobs_lock:
                jobs[job_id]["erro"] = str(exc)
                jobs[job_id]["status"] = "erro"
                jobs[job_id]["logs"].append(f"ERRO: {exc}")

    def iniciar(corpo):
        with jobs_lock:
            if ideias_api.ha_job_ativo(jobs):
                return ideias_api._erro("Já existe uma coleta em andamento. Aguarde ela terminar.", 409)
            job_id = novo_job()
            t = threading.Thread(target=executar, args=(job_id, corpo), daemon=True)
            jobs[job_id]["thread"] = t
            t.start()
        return jsonify({"ok": True, "job_id": job_id})

    erro = ideias_api._erro

    @app.route("/api/canal/analises", methods=["GET"])
    def api_canal_listar():
        return jsonify({"ok": True, "analises": canal.listar_analises(db_path)})

    @app.route("/api/canal/analisar", methods=["POST"])
    def api_canal_analisar():
        d = request.get_json(force=True, silent=True) or {}
        try:
            url = canal.normalizar_url_canal(d.get("url"))
        except ValueError as exc:
            return erro(str(exc))
        n = ideias_api._int(d.get("n_videos"), PADRAO_VIDEOS, MIN_VIDEOS, MAX_VIDEOS)
        return iniciar(corpo_analise(url, n, ideias_api._bool(d.get("headless"), False), ideias_api._bool(d.get("mutar_audio"), True), db_path))

    @app.route("/api/canal/analises/<int:aid>", methods=["GET"])
    def api_canal_obter(aid):
        a = canal.obter_analise(aid, db_path)
        return jsonify({"ok": True, "analise": a}) if a else erro("Análise não encontrada.", 404)

    @app.route("/api/canal/analises/<int:aid>", methods=["DELETE"])
    def api_canal_excluir(aid):
        return jsonify({"ok": True}) if canal.excluir_analise(aid, db_path) else erro("Análise não encontrada.", 404)

    @app.route("/api/canal/analises/<int:aid>/prompt/<tipo>", methods=["POST"])
    def api_canal_prompt(aid, tipo):
        if tipo not in canal.TIPOS_IA:
            return erro("Tipo de prompt desconhecido.", 404)
        a = canal.obter_analise(aid, db_path)
        if not a:
            return erro("Análise não encontrada.", 404)
        d = request.get_json(force=True, silent=True) or {}
        try:
            if tipo == "categorias":
                prompt = canal.montar_prompt_categorias(a["dados"])
            elif tipo == "estrategia":
                prompt = canal.montar_prompt_estrategia(a, ideias.codigo_mercado(d.get("mercado")), d.get("objetivo"))
            else:
                prompt = canal.montar_prompt_comentarios(a["dados"], d.get("comentarios"))
        except ValueError as exc:
            return erro(str(exc))
        return jsonify({"ok": True, "prompt": prompt})

    @app.route("/api/canal/analises/<int:aid>/ia/<tipo>", methods=["POST"])
    def api_canal_ia_aplicar(aid, tipo):
        if tipo not in canal.TIPOS_IA:
            return erro("Tipo de análise desconhecido.", 404)
        a = canal.obter_analise(aid, db_path)
        if not a:
            return erro("Análise não encontrada.", 404)
        texto = (request.get_json(force=True, silent=True) or {}).get("texto")
        try:
            if tipo == "categorias":
                conteudo = {"categorias": canal.validar_categorias(texto, len(a["dados"]["videos"]))}
            elif tipo == "estrategia":
                conteudo = canal.validar_estrategia(texto)
            else:
                conteudo = canal.validar_comentarios(texto)
        except ValueError as exc:
            return erro(str(exc))
        return jsonify({"ok": True, "analise": canal.gravar_ia(aid, tipo, conteudo, db_path)})

    @app.route("/api/canal/analises/<int:aid>/ia/<tipo>", methods=["DELETE"])
    def api_canal_ia_limpar(aid, tipo):
        if tipo not in canal.TIPOS_IA:
            return erro("Tipo de análise desconhecido.", 404)
        a = canal.gravar_ia(aid, tipo, None, db_path)
        return jsonify({"ok": True, "analise": a}) if a else erro("Análise não encontrada.", 404)
