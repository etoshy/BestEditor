#!/usr/bin/env python3
"""
Rotas da aba "Ideias virais" (/api/ideias/*).

Registradas por ``app.py`` com ``ideias_api.registrar(app, JOBS, JOBS_LOCK, novo_job, LogStream)``,
reaproveitando o mesmo mecanismo de jobs/log ao vivo da aba Minerar
(``/api/logs/<job_id>``). Nenhuma rota usa API paga: as etapas de IA só
montam o prompt e validam o JSON que você cola de volta.
"""

import contextlib
import threading
from datetime import datetime

from flask import Response, jsonify, request
from playwright.sync_api import sync_playwright

import ideias
import ideias_scraper as sc
import yt_scraper as core

LIMITE_VIDEOS_PROMPT = 30
TIPOS_PROMPT = ("decompor", "expandir", "ideias")


def _thread_viva(job):
    """Sem thread registrada = desconhecido (conservador: conta como ativo). Thread ainda não
    iniciada (``ident is None``) também conta; thread já encerrada não bloqueia mais ninguém."""
    t = job.get("thread")
    return t is None or t.ident is None or t.is_alive()


def ha_job_ativo(jobs):
    """Só um job por vez: os prints do scraper são redirecionados para um único log.

    O status sozinho não basta: se uma thread morresse sem atualizá-lo, o app ficaria
    bloqueado até reiniciar. Por isso o job só conta como ativo se a thread estiver viva."""
    return any(j.get("status") in ("pendente", "rodando") and _thread_viva(j) for j in jobs.values())


def _int(valor, padrao, minimo, maximo):
    try:
        return max(minimo, min(maximo, int(valor)))
    except (TypeError, ValueError):
        return padrao


def _bool(valor, padrao=False):
    return padrao if valor is None else bool(valor)


def _erro(msg, status=400):
    return jsonify({"ok": False, "erro": msg}), status


# --------------------------------------------------------------------------
# Jobs (Playwright)
# --------------------------------------------------------------------------

def _abrir_navegador(p, headless, mutar=True):
    browser = p.chromium.launch(headless=headless, args=["--mute-audio"] if mutar else [])
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(core.NAV_TIMEOUT)
    return browser, context, page


def corpo_radar(pid, cfg, db_path=None):
    estado = ideias.obter_pesquisa(pid, db_path)
    if estado is None:
        raise KeyError(pid)
    termos = ideias._limpar_termos(cfg.get("termos")) or estado.get("termos") or []
    if not termos:
        raise ValueError("Informe pelo menos um termo de busca para o radar.")
    filtros = core._normalizar_filtros({
        "duracao_min": cfg.get("duracao_min", 3), "duracao_max": cfg.get("duracao_max", 0),
        "data_periodo": cfg.get("data_periodo", "mes"), "ordenacao": cfg.get("ordenacao", "popularidade"),
    })
    max_videos = _int(cfg.get("max_videos"), 60, 10, 200)
    top_k = _int(cfg.get("top_canais"), 10, 0, 30)
    cod = estado.get("mercado") or ideias.MERCADO_PADRAO
    m = ideias.mercado(cod)
    print(f"Radar | tema: {estado['tema']} | mercado: {m['nome']} | {len(termos)} termo(s) | "
          f"período: {filtros['data_periodo']} | inscritos dos {top_k} maiores canais pequenos")

    todos, falhas, cache = [], [], {}
    with sync_playwright() as p:
        browser, _ctx, page = _abrir_navegador(p, _bool(cfg.get("headless")), _bool(cfg.get("mutar_audio"), True))
        try:
            for i, termo in enumerate(termos, 1):
                print(f"\n--- TERMO {i}/{len(termos)} | {termo} ---")
                try:
                    todos.extend(sc.coletar_videos_termo(page, termo, cod, filtros, max_videos, log=print))
                except Exception as exc:
                    msg = f"Falha isolada no termo '{termo}': {type(exc).__name__}: {exc}"
                    falhas.append(msg)
                    print(f"  ERRO ISOLADO — {msg}")
            if top_k and todos:
                print(f"\nLendo inscritos de até {top_k} canais (uma navegação por canal)...")
                sc.coletar_inscritos(page, todos, top_k, cache, log=print)
        finally:
            browser.close()

    unicos = {}
    for v in todos:
        atual = unicos.get(v["video_id"])
        if atual is None:
            unicos[v["video_id"]] = {**v, "termos": [v["termo_busca"]]}
        elif v["termo_busca"] not in atual["termos"]:
            atual["termos"].append(v["termo_busca"])
    videos = sc.aplicar_razoes(list(unicos.values()), cache)
    videos = ideias.selecionar_para_ia(videos, n=300)
    radar = {"videos": videos, "resumo": ideias.resumo_radar(videos), "falhas": falhas, "filtros": filtros,
             "mercado": cod, "coletado_em": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
    selecao = [v["video_id"] for v in ideias.selecionar_para_ia(videos, 20)]

    def gravar(e):
        e["radar"], e["radar_selecao"], e["termos"] = radar, selecao, termos
        return e

    ideias.mutar_pesquisa(pid, gravar, db_path)
    com_razao = sum(1 for v in videos if v.get("razao_views_inscritos"))
    print(f"\nConcluído. {len(videos)} vídeos únicos, {com_razao} com inscritos do canal conhecidos.")
    if falhas:
        print(f"Termos com falha isolada: {len(falhas)}.")
    return {"videos": len(videos), "falhas": len(falhas)}


def _pares_para_validar(ideias_sel, por_ideia=3):
    pares = []
    for i in ideias_sel:
        for t in (i.get("termos_validacao") or [])[:por_ideia]:
            par = (t, ideias.codigo_mercado(i.get("mercado")))
            if par not in pares:
                pares.append(par)
    return pares


def corpo_validacao(pid, cfg, db_path=None):
    estado = ideias.obter_pesquisa(pid, db_path)
    if estado is None:
        raise KeyError(pid)
    ids = set(cfg.get("ideia_ids") or [])
    sel = [i for i in estado.get("ideias") or [] if i["id"] in ids and i.get("termos_validacao") and not i.get("descartada")]
    pares = _pares_para_validar(sel)
    if not pares:
        raise ValueError("Nenhuma ideia selecionada tem termos de validação.")

    usar_sug, alfabeto = _bool(cfg.get("sugestoes"), True), _bool(cfg.get("alfabeto"))
    usar_serp, usar_trends, usar_yt = _bool(cfg.get("serp"), True), _bool(cfg.get("trends"), True), _bool(cfg.get("yt"), True)
    gprop = "youtube" if cfg.get("trends_fonte") == "youtube" else ""
    periodo_trends = cfg.get("trends_periodo") if cfg.get("trends_periodo") in ("today 3-m", "today 12-m", "today 5-y") else "today 12-m"
    filtros_yt = core._normalizar_filtros({"duracao_min": 3, "duracao_max": 0,
                                           "data_periodo": cfg.get("data_periodo", "mes"), "ordenacao": "popularidade"})
    max_yt = _int(cfg.get("max_videos_yt"), 30, 10, 100)
    print(f"Validação | {len(sel)} ideia(s) | {len(pares)} termo(s) | sugestões={usar_sug} SERP={usar_serp} "
          f"Trends={usar_trends} concorrência YouTube={usar_yt}")

    def novo_reg(termo, cod):
        m = ideias.mercado(cod)
        return {"termo": termo, "mercado": cod, "sugestoes_google": None, "sugestoes_youtube": None,
                "serp_status": "desativado", "paa": [], "relacionadas": [], "trends": None, "yt": None,
                "trends_url": ideias.url_trends([termo], m["gl"], periodo_trends, gprop),
                "coletado_em": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}

    def gravar(chave, reg):
        def f(e):
            e.setdefault("validacao", {})[chave] = reg
            return ideias.recalcular_estado(e)
        ideias.mutar_pesquisa(pid, f, db_path)

    registros, serp_bloqueada = {}, False
    if usar_sug or usar_serp or usar_yt:
        with sync_playwright() as p:
            browser, ctx, page = _abrir_navegador(p, _bool(cfg.get("headless")), _bool(cfg.get("mutar_audio"), True))
            fetch = sc.fetch_por_contexto(ctx)
            try:
                for n, (termo, cod) in enumerate(pares, 1):
                    print(f"\n--- [{n}/{len(pares)}] {termo} ({ideias.mercado(cod)['nome']}) ---")
                    reg = novo_reg(termo, cod)
                    if usar_sug:
                        try:
                            s = sc.coletar_sugestoes(fetch, termo, cod, alfabeto=alfabeto)
                            reg["sugestoes_google"], reg["sugestoes_youtube"] = s["google"], s["youtube"]
                            print(f"  autocomplete: Google {len(s['google'] or [])} | YouTube {len(s['youtube'] or [])}")
                        except Exception as exc:
                            print(f"  autocomplete falhou: {type(exc).__name__}: {exc}")
                    if usar_serp:
                        if serp_bloqueada:
                            reg["serp_status"] = "pulado"
                        else:
                            r = sc.coletar_serp_google(page, termo, cod)
                            reg["serp_status"], reg["paa"], reg["relacionadas"] = r["status"], r["paa"], r["relacionadas"]
                            if r["status"] == "bloqueado":
                                serp_bloqueada = True
                                print("  Google pediu verificação (CAPTCHA/consentimento): pulando a SERP nos demais termos.")
                            else:
                                print(f"  Google: {len(r['paa'])} perguntas, {len(r['relacionadas'])} relacionadas ({r['status']})")
                    if usar_yt:
                        try:
                            vids = sc.coletar_videos_termo(page, termo, cod, filtros_yt, max_yt, log=print)
                            reg["yt"] = ideias.metricas_concorrencia(vids)
                            reg["yt"]["top_videos"] = [{"titulo": v["titulo"], "views": v.get("views_num"), "url": v["url"], "canal": v.get("canal")}
                                                       for v in ideias.selecionar_para_ia(vids, 3)]
                        except Exception as exc:
                            print(f"  concorrência no YouTube falhou: {type(exc).__name__}: {exc}")
                    registros[ideias.chave_validacao(termo, cod)] = reg
                    gravar(ideias.chave_validacao(termo, cod), reg)
            finally:
                browser.close()
    else:
        for termo, cod in pares:
            registros[ideias.chave_validacao(termo, cod)] = novo_reg(termo, cod)

    trends_motivo = ""
    if usar_trends:
        por_mercado = {}
        for termo, cod in pares:
            por_mercado.setdefault(cod, []).append(termo)
        for cod, termos in por_mercado.items():
            m = ideias.mercado(cod)
            print(f"\nGoogle Trends ({m['nome']}, {periodo_trends}, {'YouTube' if gprop else 'Google'}): {len(termos)} termo(s)")
            r = ideias.coletar_trends(termos, geo=m["gl"], periodo=periodo_trends, gprop=gprop, log=print)
            if r["motivo"]:
                trends_motivo = r["motivo"]
                print(f"  Trends: {r['motivo']}")
            for termo in termos:
                dados = r["termos"].get(termo)
                if dados:
                    registros[ideias.chave_validacao(termo, cod)]["trends"] = dados
                    print(f"  {termo}: nível {dados['nivel']} | {dados['tendencia']} | {dados['perfil']}")
        for chave, reg in registros.items():
            gravar(chave, reg)
    print(f"\nConcluído. {len(registros)} termo(s) validados.")
    return {"termos": len(registros), "serp_bloqueada": serp_bloqueada, "trends_motivo": trends_motivo}


# --------------------------------------------------------------------------
# Rotas
# --------------------------------------------------------------------------

def registrar(app, jobs, jobs_lock, novo_job, LogStream, db_path=None):
    """Adiciona as rotas /api/ideias/* ao app Flask."""

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
            if ha_job_ativo(jobs):
                return _erro("Já existe uma coleta em andamento. Aguarde ela terminar.", 409)
            job_id = novo_job()
            t = threading.Thread(target=executar, args=(job_id, corpo), daemon=True)
            jobs[job_id]["thread"] = t
            t.start()
        return jsonify({"ok": True, "job_id": job_id})

    def carregar(pid):
        return ideias.obter_pesquisa(pid, db_path)

    @app.route("/api/ideias/mercados")
    def api_ideias_mercados():
        return jsonify({"ok": True, "mercados": [{"codigo": c, "nome": m["nome"], "idioma": m["idioma"]}
                                                 for c, m in ideias.MERCADOS.items()],
                        "modos": [{"codigo": c, "nome": n} for c, n in ideias.MODOS_IDEIAS.items()],
                        "pesos_padrao": ideias.PESOS_PADRAO, "limiares_padrao": ideias.LIMIARES_PADRAO})

    @app.route("/api/ideias/pesquisas", methods=["GET"])
    def api_ideias_listar():
        return jsonify({"ok": True, "pesquisas": ideias.listar_pesquisas(db_path)})

    @app.route("/api/ideias/pesquisas", methods=["POST"])
    def api_ideias_criar():
        d = request.get_json(force=True) or {}
        try:
            pid = ideias.criar_pesquisa(d.get("tema"), d.get("mercado", ideias.MERCADO_PADRAO), d.get("termos"), db_path)
        except ValueError as exc:
            return _erro(str(exc))
        return jsonify({"ok": True, "pesquisa": carregar(pid)})

    @app.route("/api/ideias/pesquisas/<int:pid>", methods=["GET"])
    def api_ideias_obter(pid):
        e = carregar(pid)
        return jsonify({"ok": True, "pesquisa": e}) if e else _erro("Pesquisa não encontrada.", 404)

    @app.route("/api/ideias/pesquisas/<int:pid>", methods=["PATCH"])
    def api_ideias_config(pid):
        try:
            e = ideias.atualizar_config(pid, request.get_json(force=True) or {}, db_path)
        except KeyError:
            return _erro("Pesquisa não encontrada.", 404)
        return jsonify({"ok": True, "pesquisa": e})

    @app.route("/api/ideias/pesquisas/<int:pid>", methods=["DELETE"])
    def api_ideias_excluir(pid):
        return jsonify({"ok": True}) if ideias.excluir_pesquisa(pid, db_path) else _erro("Pesquisa não encontrada.", 404)

    @app.route("/api/ideias/pesquisas/<int:pid>/ideias/<ideia_id>", methods=["PATCH"])
    def api_ideias_editar(pid, ideia_id):
        try:
            e = ideias.atualizar_ideia(pid, ideia_id, request.get_json(force=True) or {}, db_path)
        except KeyError:
            return _erro("Pesquisa não encontrada.", 404)
        return jsonify({"ok": True, "pesquisa": e}) if e else _erro("Ideia não encontrada.", 404)

    @app.route("/api/ideias/pesquisas/<int:pid>/ideias.csv")
    def api_ideias_csv(pid):
        texto = ideias.exportar_csv(pid, db_path)
        if texto is None:
            return _erro("Pesquisa não encontrada.", 404)
        return Response("\ufeff" + texto, mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="ideias_{pid}.csv"'})

    # ---- IA: gerar prompt / colar JSON ----
    @app.route("/api/ideias/pesquisas/<int:pid>/prompt/<tipo>", methods=["POST"])
    def api_ideias_prompt(pid, tipo):
        if tipo not in TIPOS_PROMPT:
            return _erro("Tipo de prompt inválido.", 404)
        e = carregar(pid)
        if e is None:
            return _erro("Pesquisa não encontrada.", 404)
        d = request.get_json(force=True) or {}
        cod = e.get("mercado") or ideias.MERCADO_PADRAO
        try:
            if tipo == "decompor":
                por_id = {v["video_id"]: v for v in (e.get("radar") or {}).get("videos") or []}
                ids = [i for i in (d.get("video_ids") or e.get("radar_selecao") or []) if i in por_id][:LIMITE_VIDEOS_PROMPT]
                videos = [por_id[i] for i in ids]
                refs = ideias._limpar_termos(d.get("refs_extra", e.get("refs_extra")))
                prompt = ideias.montar_prompt_decomposicao(e["tema"], videos, cod, refs, limite=LIMITE_VIDEOS_PROMPT)
                base = [{"indice": n, "titulo": v["titulo"], "video_id": v["video_id"], "url": v.get("url"),
                         "views": v.get("views_num")} for n, v in enumerate(videos, 1)]
                base += [{"indice": len(base) + n, "titulo": t, "video_id": None, "url": None, "views": None}
                         for n, t in enumerate(refs[:20], 1)]

                def guardar(est):
                    est["decomposicao_base"], est["refs_extra"] = base, refs
                    return est
                ideias.mutar_pesquisa(pid, guardar, db_path)
            elif tipo == "expandir":
                foco = (d.get("foco") or "").strip() or e["tema"]
                prompt = ideias.montar_prompt_expansao(foco, cod, d.get("n", 10))
            else:
                padroes = (e.get("decomposicao") or {}).get("padroes") or []
                prompt = ideias.montar_prompt_ideias(e["tema"], padroes, d.get("n", 10), d.get("modo", "ambos"),
                                                     cod, d.get("mercados_alvo") or [cod])
        except ValueError as exc:
            return _erro(str(exc))
        return jsonify({"ok": True, "prompt": prompt})

    @app.route("/api/ideias/pesquisas/<int:pid>/colar/<tipo>", methods=["POST"])
    def api_ideias_colar(pid, tipo):
        if tipo not in TIPOS_PROMPT:
            return _erro("Tipo inválido.", 404)
        e = carregar(pid)
        if e is None:
            return _erro("Pesquisa não encontrada.", 404)
        texto = (request.get_json(force=True) or {}).get("texto")
        agora = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        try:
            if tipo == "decompor":
                dados = ideias.validar_decomposicao(texto, n_videos=len(e.get("decomposicao_base") or []) or None)
                dados["colado_em"] = agora

                def f(est):
                    est["decomposicao"] = dados
                    return est
                resumo = {"videos": len(dados["videos"]), "padroes": len(dados["padroes"])}
            elif tipo == "expandir":
                dados = ideias.validar_expansao(texto)
                dados["colado_em"] = agora

                def f(est):
                    est["expansao"] = dados
                    return est
                resumo = {"termos": len(dados["termos_para_validar"]), "buscas": len(dados["problemas_e_buscas"])}
            else:
                novas = ideias.validar_ideias(texto, e.get("mercado") or ideias.MERCADO_PADRAO)
                contagem = {}

                def f(est):
                    est["ideias"], contagem["novas"] = ideias.mesclar_ideias(est.get("ideias") or [], novas)
                    return ideias.recalcular_estado(est)
                resumo = contagem
        except ValueError as exc:
            return _erro(str(exc))
        estado = ideias.mutar_pesquisa(pid, f, db_path)
        if tipo == "ideias":
            resumo = {"lidas": len(novas), "novas": contagem.get("novas", 0), "total": len(estado["ideias"])}
        return jsonify({"ok": True, "resumo": resumo, "pesquisa": estado})

    # ---- coletas (jobs) ----
    @app.route("/api/ideias/pesquisas/<int:pid>/radar", methods=["POST"])
    def api_ideias_radar(pid):
        if carregar(pid) is None:
            return _erro("Pesquisa não encontrada.", 404)
        cfg = request.get_json(force=True) or {}
        return iniciar(lambda: corpo_radar(pid, cfg, db_path))

    @app.route("/api/ideias/pesquisas/<int:pid>/validar", methods=["POST"])
    def api_ideias_validar(pid):
        e = carregar(pid)
        if e is None:
            return _erro("Pesquisa não encontrada.", 404)
        cfg = request.get_json(force=True) or {}
        if not cfg.get("ideia_ids"):
            return _erro("Selecione pelo menos uma ideia para validar.")
        return iniciar(lambda: corpo_validacao(pid, cfg, db_path))

    @app.route("/api/ideias/decidir-canal", methods=["POST"])
    def api_ideias_decidir():
        d = request.get_json(force=True) or {}
        return jsonify({"ok": True, "decisao": ideias.decidir_canal(
            d.get("n_videos"), d.get("impressoes"), d.get("ctr"), d.get("retencao"), d.get("limiares"))})
