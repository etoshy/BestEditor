#!/usr/bin/env python3
"""
Niche Miner — interface web local para a automação de mineração de nicho
no YouTube (yt_scraper.py).

Fluxo:
  1. Você digita um nicho amplo -> o app monta um PROMPT pra você colar em
     qualquer IA de chat (ChatGPT, Gemini, Claude web, etc).
  2. Você cola de volta o JSON que a IA te devolveu -> o app valida e extrai
     os termos de busca.
  3. Você ajusta as opções e clica em "Iniciar" -> o app roda o Playwright
     localmente (abre o Chromium de verdade, na sua máquina) e mostra o
     progresso ao vivo, terminando num ranking de canais candidatos.

Uso:
    pip install flask playwright --break-system-packages
    python3 -m playwright install chromium
    python3 app.py                # abre em http://127.0.0.1:8843
    python3 app.py --port 9100    # pra usar outra porta
"""

import argparse
import io
import json
import os
import threading
import time
import uuid

from flask import Flask, Response, jsonify, render_template, request

import biblioteca
import canal_api
import ideias_api
import recomendados
import yt_rotas
import yt_scraper as core
from playwright.sync_api import sync_playwright

app = Flask(__name__)

# --------------------------------------------------------------------------
# Estado dos jobs (em memória — é uma ferramenta local, uso único por vez)
# --------------------------------------------------------------------------

JOBS = {}
JOBS_LOCK = threading.Lock()


class LogStream(io.TextIOBase):
    """Redireciona os prints do yt_scraper.py pro log do job, linha a linha.

    Com mais de um navegador rodando em paralelo (threads), ``sys.stdout`` é trocado uma vez só
    (no processo inteiro) pelo ``contextlib.redirect_stdout`` — então os prints de TODAS as
    threads caem aqui. ``marcar_thread`` guarda, por thread (``threading.local``), o prefixo que
    identifica o navegador; cada thread ganha seu próprio buffer de linha incompleta (chave =
    prefixo) para um print cortado de uma thread nunca se misturar com o de outra."""

    def __init__(self, job_id):
        self.job_id = job_id
        self._local = threading.local()
        self._buffers = {}

    def marcar_thread(self, prefixo=""):
        """Chamado no INÍCIO de cada thread de trabalho — o prefixo vale só para quem chamou."""
        self._local.prefixo = prefixo

    def write(self, s):
        prefixo = getattr(self._local, "prefixo", "")
        with JOBS_LOCK:
            buf = self._buffers.get(prefixo, "") + s
            while "\n" in buf:
                linha, buf = buf.split("\n", 1)
                JOBS[self.job_id]["logs"].append(f"{prefixo}{linha}" if prefixo and linha else linha)
            self._buffers[prefixo] = buf
        return len(s)

    def flush(self):
        pass


def novo_job():
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {"status": "pendente", "logs": [], "resultado": None, "erro": None}
    return job_id


def _ordenar_por_janela(canais, janela_meses):
    """Ordena os canais pelo critério "melhor canal = começo recente".

    Com janela definida: primeiro os canais cujo 1º vídeo está DENTRO da janela,
    depois os de idade desconhecida (nunca tratados como novos) e por último os
    que ficaram FORA da janela; em cada faixa vale o score. Sem janela
    (``0`` = sem limite) a ordem é só pelo score, como antes.
    """
    def score(c):
        return c.get("score") or 0

    def chave(c):
        if c.get("fora_da_janela"):
            faixa = 0
        elif c.get("idade_desconhecida"):
            faixa = 1
        else:
            faixa = 2
        return (faixa, score(c))

    return sorted(canais or [], key=chave if janela_meses else score, reverse=True)


def _resumo_janela(canais):
    return {
        "dentro": sum(1 for c in canais if not c.get("fora_da_janela") and not c.get("idade_desconhecida")),
        "desconhecida": sum(1 for c in canais if c.get("idade_desconhecida") and not c.get("fora_da_janela")),
        "fora": sum(1 for c in canais if c.get("fora_da_janela")),
    }


def _dividir(lista, n):
    """Distribui os itens em até ``n`` grupos (round-robin, preserva a ordem dentro do grupo).

    Grupos vazios não entram no resultado — com menos itens do que navegadores pedidos, roda
    menos navegadores (não faz sentido abrir um Chromium para não fazer nada)."""
    grupos = [[] for _ in range(max(1, n))]
    for i, item in enumerate(lista):
        grupos[i % len(grupos)].append(item)
    return [g for g in grupos if g]


def rodar_pipeline(job_id, termos, max_videos, min_subs, headless, usar_trends,
                   nicho="", subnichos=None, filtros=None, mutar_audio=True, analise=None,
                   recomendados_cfg=None, recomendados_auto=None, n_navegadores=1):
    """Roda a coleta e consolida o resultado.

    Fonte padrão: busca por ``termos``. Com ``recomendados_cfg`` a fonte passa a ser a lateral
    de recomendados dos vídeos em ``termos`` (URLs); a análise de canais e o resultado são os mesmos.

    ``recomendados_auto`` (só com busca por termo) liga, além disso, a coleta automática da
    lateral de cada vídeo achado durante a mineração — sem precisar colar links à parte.

    ``n_navegadores`` (1 a 5) abre esse tanto de Chromium em paralelo, cada um com sua fatia dos
    termos (ou dos vídeos de origem, no modo recomendados). Com 1 (padrão) roda exatamente como
    antes, num navegador só."""
    import contextlib

    log = LogStream(job_id)
    JOBS[job_id]["status"] = "rodando"
    try:
        subnichos = subnichos or []
        termo_para_subnicho = {}
        for s in subnichos:
            nome = (s.get("nome") or "").strip()
            for t in (s.get("termos") or []):
                if t and nome:
                    termo_para_subnicho[core._norm_key(t)] = nome

        with contextlib.redirect_stdout(log):
            if usar_trends and not recomendados_cfg:
                print("Checando Google Trends para os termos informados...")
                trends = core.checar_google_trends(termos)
                for t, v in trends.items():
                    print(f"  tendência '{t}': interesse médio (0-100) = {v}")

            all_videos, all_ranked = [], []
            falhas_termos = []
            relatorio_recomendados = None
            filtros = core._normalizar_filtros(filtros)
            analise = core._normalizar_analise(analise)
            cache_canais = {}  # o mesmo canal achado em vários termos é analisado uma vez só (só no modo 1 navegador)
            n_navegadores = max(1, min(5, int(n_navegadores or 1)))
            print(
                "Canal novo = 1º vídeo há no máximo %s mês(es) | fora da janela: %s | frequência: últimos %s vídeos"
                % (
                    analise["janela_meses"] or "sem limite",
                    "análise detalhada pulada" if analise["descartar_fora_janela"] else "analisados normalmente",
                    analise["n_frequencia"],
                )
            )
            print(
                "Configuração: duração %s-%s min | data=%s | ordenação=%s | áudio=%s"
                % (
                    filtros["duracao_min"], filtros["duracao_max"],
                    filtros["data_periodo"], filtros["ordenacao"],
                    "mutado" if mutar_audio else "ativo",
                )
            )
            if recomendados_auto:
                print(f"Recomendados da lateral: ligado (até {recomendados.normalizar_cfg(recomendados_auto)['max_itens']} por vídeo, "
                      "aprovados entram como candidatos a mais no mesmo termo).")

            usar_varios = n_navegadores > 1 and len(termos) > 1

            if not usar_varios:
                print("Rodando com 1 navegador." if n_navegadores == 1 else
                      "Só há 1 item para processar — ignorando os navegadores extras pedidos.")
                with sync_playwright() as p:
                    launch_args = ["--mute-audio"] if mutar_audio else []
                    browser = p.chromium.launch(headless=headless, args=launch_args)
                    context = browser.new_context()
                    page = context.new_page()
                    page.set_default_timeout(core.NAV_TIMEOUT)

                    try:
                        if recomendados_cfg:
                            videos_r, ranked_r, falhas_r, relatorio_recomendados = recomendados.processar_recomendados(
                                page, termos, recomendados_cfg, min_subs, max_videos, analise, cache_canais, nicho or "Sem nicho")
                            all_videos.extend(videos_r)
                            all_ranked.extend(ranked_r)
                            falhas_termos.extend(falhas_r)
                        for i, termo in enumerate([] if recomendados_cfg else termos, 1):
                            subnicho = termo_para_subnicho.get(core._norm_key(termo), "")
                            if not subnicho:
                                subnicho = "Sem subnicho"
                            print(f"\n--- TERMO {i}/{len(termos)} | {termo} | subnicho: {subnicho} ---")
                            try:
                                videos, ranked = core.processar_termo(
                                    page, termo, max_videos, min_subs,
                                    subnicho, nicho or "Sem nicho", filtros=filtros,
                                    analise=analise, cache_canais=cache_canais,
                                    recomendados_auto=recomendados_auto,
                                )
                                all_videos.extend(videos)
                                all_ranked.extend(ranked)
                            except Exception as exc:
                                msg = f"Falha isolada no termo '{termo}': {type(exc).__name__}: {exc}"
                                falhas_termos.append(msg)
                                print(f"  ERRO ISOLADO — {msg}")
                                # Não aborta os demais nichos/subnichos.
                                continue
                    finally:
                        browser.close()
            else:
                grupos = _dividir(termos, n_navegadores)
                print(f"Rodando com {len(grupos)} navegadores em paralelo "
                      f"({', '.join(str(len(g)) for g in grupos)} {'URLs' if recomendados_cfg else 'termos'} por navegador).")
                resultados_lock = threading.Lock()

                def worker(indice, fatia):
                    nonlocal relatorio_recomendados
                    prefixo = f"[navegador {indice}] "
                    log.marcar_thread(prefixo)
                    cache_local = {}  # cada navegador com o seu — evita condição de corrida; duplicatas se resolvem no ranking final
                    print(f"Iniciando — {len(fatia)} {'vídeo(s) de origem' if recomendados_cfg else 'termo(s)'}.")
                    with sync_playwright() as p:
                        launch_args = ["--mute-audio"] if mutar_audio else []
                        browser = p.chromium.launch(headless=headless, args=launch_args)
                        context = browser.new_context()
                        page = context.new_page()
                        page.set_default_timeout(core.NAV_TIMEOUT)
                        try:
                            if recomendados_cfg:
                                try:
                                    videos_r, ranked_r, falhas_r, rel_r = recomendados.processar_recomendados(
                                        page, fatia, recomendados_cfg, min_subs, max_videos, analise, cache_local, nicho or "Sem nicho", log=print)
                                except Exception as exc:
                                    videos_r, ranked_r, falhas_r, rel_r = [], [], [f"Falha isolada no navegador {indice}: {type(exc).__name__}: {exc}"], None
                                    print(f"  ERRO ISOLADO NO NAVEGADOR — {falhas_r[0]}")
                                with resultados_lock:
                                    all_videos.extend(videos_r)
                                    all_ranked.extend(ranked_r)
                                    falhas_termos.extend(falhas_r)
                                    if rel_r:  # junta o relatório de cada navegador (grupos, origens e itens somados)
                                        if relatorio_recomendados is None:
                                            relatorio_recomendados = rel_r
                                        else:
                                            relatorio_recomendados["grupos"].extend(rel_r["grupos"])
                                            relatorio_recomendados["origens"].extend(rel_r.get("origens") or [])
                                            relatorio_recomendados["itens"].extend(rel_r.get("itens") or [])
                                            relatorio_recomendados["totais"]["coletados"] += rel_r["totais"]["coletados"]
                                            relatorio_recomendados["totais"]["aprovados"] += rel_r["totais"]["aprovados"]
                                            relatorio_recomendados["canais_analisados"] = (relatorio_recomendados.get("canais_analisados") or 0) + (rel_r.get("canais_analisados") or 0)
                            else:
                                for termo in fatia:
                                    subnicho = termo_para_subnicho.get(core._norm_key(termo), "") or "Sem subnicho"
                                    print(f"\n--- TERMO | {termo} | subnicho: {subnicho} ---")
                                    try:
                                        videos, ranked = core.processar_termo(
                                            page, termo, max_videos, min_subs,
                                            subnicho, nicho or "Sem nicho", filtros=filtros,
                                            analise=analise, cache_canais=cache_local,
                                            recomendados_auto=recomendados_auto,
                                        )
                                    except Exception as exc:
                                        msg = f"Falha isolada no termo '{termo}': {type(exc).__name__}: {exc}"
                                        with resultados_lock:
                                            falhas_termos.append(msg)
                                        print(f"  ERRO ISOLADO — {msg}")
                                        continue
                                    with resultados_lock:
                                        all_videos.extend(videos)
                                        all_ranked.extend(ranked)
                        finally:
                            browser.close()
                    print("Terminou este navegador.")

                threads = [threading.Thread(target=worker, args=(i, fatia), daemon=True) for i, fatia in enumerate(grupos, 1)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                log.marcar_thread("")  # a thread principal volta a logar sem prefixo

            # Consolida cada canal uma única vez no ranking geral, preservando
            # todas as associações de nicho/subnicho/termos para rankings segmentados.
            ranking_geral = core.merge_channel_records(all_ranked)
            ranking_geral = _ordenar_por_janela(ranking_geral, analise["janela_meses"])
            for idx, c in enumerate(ranking_geral, 1):
                c["rank_geral"] = idx

            rankings_nichos = core.build_group_rankings(ranking_geral, "nicho", "Sem nicho")
            rankings_subnichos = core.build_group_rankings(ranking_geral, "subnicho", "Sem subnicho")
            rankings_paises = core.build_group_rankings(ranking_geral, "pais_canal", "País desconhecido")
            rankings_idiomas = core.build_group_rankings(ranking_geral, "idioma_canal", "Idioma desconhecido")

            resumo_nichos = core.build_group_summaries(rankings_nichos, "nicho")
            resumo_subnichos = core.build_group_summaries(rankings_subnichos, "subnicho")
            resumo_paises = core.build_group_summaries(rankings_paises, "pais")
            resumo_idiomas = core.build_group_summaries(rankings_idiomas, "idioma")

            # A interface passa a exibir os grupos na mesma ordem do índice
            # de oportunidade, em vez da ordem arbitrária dos termos coletados.
            rankings_nichos = core.reorder_group_rankings(rankings_nichos, resumo_nichos, "nicho")
            rankings_subnichos = core.reorder_group_rankings(rankings_subnichos, resumo_subnichos, "subnicho")
            rankings_paises = core.reorder_group_rankings(rankings_paises, resumo_paises, "pais")
            rankings_idiomas = core.reorder_group_rankings(rankings_idiomas, resumo_idiomas, "idioma")

            # Canais verificados ficam separados; a lógica dos não verificados
            # permanece independente.
            verificados_map = {}
            for v in all_videos:
                if v.get("canal_url") and v.get("canal_verificado"):
                    key = v["canal_url"]
                    atual = verificados_map.get(key)
                    candidato = {
                        "canal": v.get("canal", ""),
                        "canal_url": key,
                        "termo_busca": v.get("termo_busca", ""),
                        "subnicho": v.get("subnicho", "Sem subnicho"),
                        "nicho": v.get("nicho", nicho or "Sem nicho"),
                        "pais_canal": v.get("pais_canal", ""),
                        "idioma_canal": v.get("idioma_canal", ""),
                        "video_exemplo": v.get("url", ""),
                        "views_text_video_exemplo": v.get("views_text", ""),
                        "views_video_exemplo": v.get("views_num"),
                        "canal_verificado": True,
                    }
                    if atual is None or (candidato.get("views_video_exemplo") or 0) > (atual.get("views_video_exemplo") or 0):
                        verificados_map[key] = candidato
            verificados_final = sorted(
                verificados_map.values(),
                key=lambda c: (c.get("views_video_exemplo") or 0),
                reverse=True,
            )

            print(f"\nConcluído. {len(all_videos)} vídeos válidos, {len(ranking_geral)} canais não verificados no ranking e {len(verificados_final)} canais verificados separados.")
            incompletos = sum(1 for c in ranking_geral if c.get("dados_incompletos"))
            if incompletos:
                print(f"Dados incompletos em {incompletos} canais — eles permaneceram no ranking com penalização conservadora.")
            if falhas_termos:
                print(f"Termos com falha isolada: {len(falhas_termos)} (os demais foram processados normalmente).")

            busca_id = None
            try:
                busca_id = biblioteca.salvar_busca(
                    nicho, termos, subnichos, filtros,
                    {**analise, "max_videos": max_videos, "min_subs": min_subs,
                     "headless": bool(headless), "mutar_audio": bool(mutar_audio), "n_navegadores": n_navegadores,
                     **({"fonte": "recomendados", "recomendados": recomendados_cfg} if recomendados_cfg else {}),
                     **({"recomendados_auto": recomendados_auto} if recomendados_auto else {})},
                    ranking_geral, all_videos,
                )
                print(f"Busca salva na biblioteca (#{busca_id}, tema '{nicho or 'Sem tema'}').")
            except Exception as exc:
                print(f"AVISO: não foi possível salvar na biblioteca: {type(exc).__name__}: {exc}")

        with JOBS_LOCK:
            JOBS[job_id]["resultado"] = {
                "nicho": nicho,
                "ranking_nao_verificados": ranking_geral,
                "ranking_geral": ranking_geral,
                "rankings_nichos": rankings_nichos,
                "rankings_subnichos": rankings_subnichos,
                "rankings_paises": rankings_paises,
                "rankings_idiomas": rankings_idiomas,
                "resumo_nichos": resumo_nichos,
                "resumo_subnichos": resumo_subnichos,
                "resumo_paises": resumo_paises,
                "resumo_idiomas": resumo_idiomas,
                "verificados": verificados_final,
                "videos": all_videos,
                "falhas_termos": falhas_termos,
                "filtros": filtros,
                "mutar_audio": bool(mutar_audio),
                "analise": analise,
                "resumo_janela": _resumo_janela(ranking_geral),
                "busca_id": busca_id,
                "fonte": "recomendados" if recomendados_cfg else "busca",
                "recomendados": relatorio_recomendados,
            }
            JOBS[job_id]["status"] = "concluido"

    except Exception as e:
        with JOBS_LOCK:
            JOBS[job_id]["erro"] = str(e)
            JOBS[job_id]["status"] = "erro"
            JOBS[job_id]["logs"].append(f"ERRO: {e}")


# --------------------------------------------------------------------------
# Rotas
# --------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/gerar-prompt", methods=["POST"])
def api_gerar_prompt():
    data = request.get_json(force=True)
    nicho = (data.get("nicho") or "").strip()
    if not nicho:
        return jsonify({"ok": False, "erro": "Informe um nicho."}), 400
    n_subnichos = int(data.get("n_subnichos", 5))
    n_termos = int(data.get("n_termos", 5))
    prompt = core.montar_prompt_subnichos(nicho, n_subnichos, n_termos)
    return jsonify({"ok": True, "prompt": prompt})


@app.route("/api/validar-json", methods=["POST"])
def api_validar_json():
    data = request.get_json(force=True)
    texto = (data.get("texto") or "").strip()
    texto = texto.strip("`")
    if texto.lower().startswith("json"):
        texto = texto[4:].strip()
    try:
        parsed = json.loads(texto)
    except Exception as e:
        return jsonify({"ok": False, "erro": f"JSON inválido: {e}"}), 400

    subnichos = parsed.get("subnichos")
    if not isinstance(subnichos, list) or not subnichos:
        return jsonify({"ok": False, "erro": "JSON não tem uma lista 'subnichos' válida."}), 400

    termos = []
    subnichos_limpos = []
    for s in subnichos:
        if not isinstance(s, dict):
            continue
        nome = (s.get("nome") or "").strip()
        termos_s = []
        for t in (s.get("termos") or []):
            t = str(t).strip()
            if t and t not in termos_s:
                termos_s.append(t)
            if t and t not in termos:
                termos.append(t)
        if nome and termos_s:
            subnichos_limpos.append({"nome": nome, "termos": termos_s})

    if not termos:
        return jsonify({"ok": False, "erro": "Nenhum termo de busca encontrado no JSON."}), 400

    return jsonify({"ok": True, "subnichos": subnichos_limpos, "termos": termos})


@app.route("/api/iniciar", methods=["POST"])
def api_iniciar():
    data = request.get_json(force=True)
    termos = data.get("termos") or []
    termos = [t.strip() for t in termos if t and t.strip()]
    if not termos:
        return jsonify({"ok": False, "erro": "Nenhum termo de busca informado."}), 400

    max_videos = int(data.get("max_videos", 100))
    min_subs = int(data.get("min_subs", 0))
    headless = bool(data.get("headless", False))
    usar_trends = bool(data.get("trends", False))
    mutar_audio = bool(data.get("mutar_audio", True))
    try:
        n_navegadores = max(1, min(5, int(data.get("n_navegadores", 1))))
    except (TypeError, ValueError):
        n_navegadores = 1
    filtros = {
        "duracao_min": data.get("duracao_min", 3),
        "duracao_max": data.get("duracao_max", 20),
        "data_periodo": data.get("data_periodo", "mes"),
        "ordenacao": data.get("ordenacao", "popularidade"),
    }
    analise = {
        "janela_meses": data.get("janela_meses", 3),
        "descartar_fora_janela": bool(data.get("descartar_fora_janela", True)),
        "n_frequencia": data.get("n_frequencia", 50),
    }
    nicho = (data.get("nicho") or "").strip()
    subnichos = data.get("subnichos") or []
    subnichos = [s for s in subnichos if isinstance(s, dict)]
    nicho = nicho or "Sem nicho"

    rec_auto_in = data.get("recomendados_auto") or {}
    recomendados_auto = recomendados.normalizar_cfg(rec_auto_in) if rec_auto_in.get("ativo") else None

    return _iniciar_job((termos, max_videos, min_subs, headless, usar_trends, nicho,
                         subnichos, filtros, mutar_audio, analise),
                        {"recomendados_auto": recomendados_auto, "n_navegadores": n_navegadores})


def _iniciar_job(args, kwargs=None):
    """Cria o job e dispara ``rodar_pipeline``. Verificação e criação são atômicas: só uma coleta
    por vez (Minerar, Recomendações ou Ideias), porque os prints do scraper vão para um único log."""
    with JOBS_LOCK:
        if ideias_api.ha_job_ativo(JOBS):
            return jsonify({"ok": False, "erro": "Já existe uma coleta em andamento. Aguarde ela terminar."}), 409
        job_id = novo_job()
        thread = threading.Thread(target=rodar_pipeline, args=(job_id, *args), kwargs=kwargs or {}, daemon=True)
        JOBS[job_id]["thread"] = thread
        thread.start()
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/iniciar-recomendados", methods=["POST"])
def api_iniciar_recomendados():
    """Mineração pela lateral de recomendados de vídeos que o usuário achou bons."""
    data = request.get_json(force=True)
    urls, invalidas, cortadas = recomendados.separar_urls(data.get("urls") or data.get("texto") or "")
    if invalidas:
        return jsonify({"ok": False, "erro": "Estas linhas não são links de vídeo do YouTube (watch?v= ou youtu.be): "
                        + " | ".join(i[:60] for i in invalidas[:3]) + (" ..." if len(invalidas) > 3 else "")}), 400
    if not urls:
        return jsonify({"ok": False, "erro": "Informe ao menos um link de vídeo do YouTube."}), 400
    if cortadas:
        return jsonify({"ok": False, "erro": f"No máximo {recomendados.MAX_ORIGENS} vídeos de origem por rodada; você enviou {len(urls) + cortadas}."}), 400
    try:
        max_videos, min_subs = int(data.get("max_videos", 100)), int(data.get("min_subs", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "erro": "Máx. de vídeos e inscritos mínimos precisam ser números."}), 400

    cfg = recomendados.normalizar_cfg({
        "max_itens": data.get("max_itens"), "meses_max": data.get("meses_max"), "referencia": data.get("referencia"),
        "fator": data.get("fator"), "escopo": data.get("escopo"),
        "duracao_min": data.get("duracao_min"), "duracao_max": data.get("duracao_max"),
    })
    filtros = {"duracao_min": cfg["duracao_min"], "duracao_max": cfg["duracao_max"], "data_periodo": "todos", "ordenacao": "relevancia"}
    analise = {
        "janela_meses": data.get("janela_meses", 3),
        "descartar_fora_janela": bool(data.get("descartar_fora_janela", True)),
        "n_frequencia": data.get("n_frequencia", 50),
    }
    try:
        n_navegadores = max(1, min(5, int(data.get("n_navegadores", 1))))
    except (TypeError, ValueError):
        n_navegadores = 1
    nicho = (data.get("nicho") or "").strip() or "Sem nicho"
    resposta = _iniciar_job(
        (urls, max_videos, min_subs, bool(data.get("headless", False)), False,
         nicho, [], filtros, bool(data.get("mutar_audio", True)), analise),
        {"recomendados_cfg": cfg, "n_navegadores": n_navegadores})
    return resposta


@app.route("/api/gerar-prompt-canais", methods=["POST"])
def api_gerar_prompt_canais():
    """Prompt (para qualquer IA de chat) que transforma os canais achados em subnichos + termos de busca.
    A resposta da IA tem o mesmo JSON do passo 1 e entra no passo 2."""
    data = request.get_json(force=True)
    try:
        busca_id = int(data.get("busca_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "erro": "Informe o busca_id da pesquisa salva na biblioteca."}), 400
    busca = biblioteca.obter_busca(busca_id)
    if busca is None:
        return jsonify({"ok": False, "erro": "Busca não encontrada na biblioteca."}), 404
    canais = [c for c in busca["canais"] if not c.get("fora_da_janela")] or busca["canais"]
    try:
        max_canais = max(1, min(30, int(data.get("max_canais", 15))))
        prompt = recomendados.montar_prompt_subnichos_de_canais(canais, busca["videos"], max_canais=max_canais)
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    return jsonify({"ok": True, "prompt": prompt, "n_canais": min(len(canais), max_canais)})


@app.route("/api/logs/<job_id>")
def api_logs(job_id):
    cursor = int(request.args.get("cursor", 0))
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"ok": False, "erro": "job não encontrado"}), 404
    with JOBS_LOCK:
        novas = job["logs"][cursor:]
        cursor_novo = len(job["logs"])
        status = job["status"]
    return jsonify({"ok": True, "logs": novas, "cursor": cursor_novo, "status": status})


@app.route("/api/resultado/<job_id>")
def api_resultado(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"ok": False, "erro": "job não encontrado"}), 404
    if job["status"] != "concluido":
        return jsonify({"ok": False, "erro": "job ainda não concluído", "status": job["status"]}), 409
    return jsonify({"ok": True, "resultado": job["resultado"]})


# --------------------------------------------------------------------------
# Biblioteca (buscas salvas por tema)
# --------------------------------------------------------------------------

@app.route("/api/biblioteca")
def api_biblioteca():
    return jsonify({"ok": True, "temas": biblioteca.listar_biblioteca()})


@app.route("/api/biblioteca/pesquisar")
def api_biblioteca_pesquisar():
    q = (request.args.get("q") or "").strip()
    return jsonify({"ok": True, **biblioteca.pesquisar(q)})


@app.route("/api/biblioteca/busca/<int:busca_id>")
def api_biblioteca_busca(busca_id):
    dados = biblioteca.obter_busca(busca_id)
    if dados is None:
        return jsonify({"ok": False, "erro": "Busca não encontrada."}), 404
    return jsonify({"ok": True, **dados})


@app.route("/api/biblioteca/busca/<int:busca_id>", methods=["DELETE"])
def api_biblioteca_excluir(busca_id):
    if not biblioteca.excluir_busca(busca_id):
        return jsonify({"ok": False, "erro": "Busca não encontrada."}), 404
    return jsonify({"ok": True})


@app.route("/api/biblioteca/busca/<int:busca_id>/<tipo>.csv")
def api_biblioteca_csv(busca_id, tipo):
    if tipo not in ("canais", "videos"):
        return jsonify({"ok": False, "erro": "Tipo inválido (use canais ou videos)."}), 404
    texto = biblioteca.exportar_csv(busca_id, tipo)
    if texto is None:
        return jsonify({"ok": False, "erro": "Busca não encontrada."}), 404
    return Response(
        "\ufeff" + texto, mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="busca_{busca_id}_{tipo}.csv"'},
    )


# Aba "Ideias virais" (rotas /api/ideias/*) — mesmo mecanismo de jobs/logs da mineração.
ideias_api.registrar(app, JOBS, JOBS_LOCK, novo_job, LogStream)
canal_api.registrar(app, JOBS, JOBS_LOCK, novo_job, LogStream)
yt_rotas.registrar(app)


def main():
    ap = argparse.ArgumentParser(description="Niche Miner — servidor local")
    ap.add_argument("--port", type=int, default=8843,
                     help="Porta pra rodar o servidor (padrão: 8843)")
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    # aberto pelo site (que roda com o recarregador do Flask): não herda o soquete dele (WinError 10038)
    for k in ("WERKZEUG_SERVER_FD", "WERKZEUG_RUN_MAIN"):
        os.environ.pop(k, None)
    print(f"Niche Miner rodando em http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
