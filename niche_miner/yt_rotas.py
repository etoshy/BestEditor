#!/usr/bin/env python3
"""
Rotas da aba "API do YouTube" (/api/yt/*). Registradas por ``app.py`` com ``yt_rotas.registrar(app)``.

A chave da API vem no corpo da requisição (o navegador a guarda) ou da variável ``YOUTUBE_API_KEY``. Ela nunca é
gravada em disco nem devolvida em resposta. Sem estado no servidor: cada chamada lê o que precisa do YouTube e devolve
as ``unidades`` de cota gastas.
"""

import logging
import os
from datetime import datetime, timezone

from flask import Response, jsonify, request

import yt_api
import yt_ia

log = logging.getLogger(__name__)
LIMITE_N_HISTORICO = 50


def _agora():
    """Trocado nos testes para fixar a data."""
    return datetime.now(timezone.utc)


def _corpo():
    d = request.get_json(force=True, silent=True)
    return d if isinstance(d, dict) else {}


def _erro(msg, status=400, razao=""):
    return jsonify({"ok": False, "erro": msg, "razao": razao}), status


def registrar(app):
    def cliente(d):
        return yt_api.Cliente(d.get("chave") or os.environ.get("YOUTUBE_API_KEY"))

    def executar(fn, d=None):
        """Roda a ferramenta e traduz os erros conhecidos. Toda mensagem (resposta e log) passa por máscara da chave, e o
        erro inesperado vira 500 sem traceback (a mensagem original pode carregar a URL com a chave)."""
        chave = (d or {}).get("chave") or os.environ.get("YOUTUBE_API_KEY") or ""
        try:
            return jsonify({"ok": True, **fn()})
        except yt_api.YTErro as e:
            return _erro(yt_api._mascarar(e.mensagem, chave), e.status, e.razao)
        except ValueError as e:
            return _erro(yt_api._mascarar(str(e), chave))
        except Exception as e:                                                 # noqa: BLE001
            log.error("erro inesperado em /api/yt: %s: %s", type(e).__name__, yt_api._mascarar(str(e), chave))
            return _erro("Erro interno ao falar com o YouTube. Veja o terminal onde o app roda.", 500, "interno")

    @app.route("/api/yt/config")
    def api_yt_config():
        return jsonify({"ok": True, "chave_no_ambiente": bool(os.environ.get("YOUTUBE_API_KEY")), "custos": yt_api.CUSTO})

    @app.route("/api/yt/pesquisar", methods=["POST"])
    def api_yt_pesquisar():
        d = _corpo()
        return executar(lambda: yt_api.pesquisa_avancada(cliente(d), d, _agora()), d)

    @app.route("/api/yt/em-alta", methods=["POST"])
    def api_yt_em_alta():
        d = _corpo()
        return executar(lambda: yt_api.em_alta(cliente(d), d.get("pais"), d.get("categoria"), _agora()), d)

    @app.route("/api/yt/comparar", methods=["POST"])
    def api_yt_comparar():
        d = _corpo()
        return executar(lambda: yt_api.comparar(cliente(d), d.get("a"), d.get("b"), _agora()), d)

    @app.route("/api/yt/canal", methods=["POST"])
    def api_yt_canal():
        d = _corpo()
        return executar(lambda: yt_api.analisar_canal(cliente(d), d.get("canal"), _agora()), d)

    @app.route("/api/yt/video", methods=["POST"])
    def api_yt_video():
        d = _corpo()
        return executar(lambda: yt_api.analisar_video(cliente(d), d.get("video"), _agora()), d)

    @app.route("/api/yt/historico", methods=["POST"])
    def api_yt_historico():
        d = _corpo()
        try:
            n = max(1, min(LIMITE_N_HISTORICO, int(d.get("n") or 30)))
        except (TypeError, ValueError):
            n = 30
        return executar(lambda: yt_api.historico(cliente(d), d.get("canal"), n, _agora()), d)

    @app.route("/api/yt/prompt/<tipo>", methods=["POST"])
    def api_yt_prompt(tipo):
        if tipo not in yt_ia.TIPOS:
            return _erro("Tipo de análise desconhecido.", 404)
        d = _corpo()
        try:
            prompt = yt_ia.montar_prompt(tipo, d.get("dados"), d.get("contexto"), d.get("transcricao"))
        except ValueError as e:
            return _erro(str(e))
        except (TypeError, KeyError, AttributeError):
            return _erro("Os dados enviados não têm o formato esperado. Refaça a consulta e tente de novo.")
        return jsonify({"ok": True, "prompt": prompt})

    @app.route("/api/yt/ia/<tipo>", methods=["POST"])
    def api_yt_ia(tipo):
        if tipo not in yt_ia.TIPOS:
            return _erro("Tipo de análise desconhecido.", 404)
        d = _corpo()
        try:
            n = max(1, min(yt_ia.MAX_VIDEOS_PROMPT if tipo == "oportunidades" else LIMITE_N_HISTORICO, int(d.get("n_videos") or 0) or 999))
        except (TypeError, ValueError):
            n = 999
        try:
            validar = yt_ia.VALIDADORES[tipo]
            resultado = validar(d.get("texto"), n) if tipo in ("oportunidades", "auditoria") else validar(d.get("texto"))
        except ValueError as e:
            return _erro(str(e))
        return jsonify({"ok": True, "resultado": resultado})

    @app.route("/api/yt/miniatura")
    def api_yt_miniatura():
        video = request.args.get("video", "")
        try:
            corpo, tipo, nome = yt_api.baixar_miniatura(video)
        except ValueError as e:
            return _erro(str(e))
        except yt_api.YTErro as e:
            return _erro(e.mensagem, e.status, e.razao)
        return Response(corpo, mimetype=tipo, headers={"Content-Disposition": f'attachment; filename="{video}_{nome}.jpg"', "X-Resolucao": nome})
