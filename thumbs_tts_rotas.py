"""
Rotas de 🖼 thumbnails no Flow (thumbs_flow.py) e 🎙 adaptar o roteiro pro TTS (adaptar_tts.py) — v84_96.
Servem 🕵️ Modelos de vídeo ("dossie"), 📜 Roteiro do YouTube ("roteiro_yt") e (thumbnails) 📊 Analisador de canal ("canal").
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify, request, send_file

import adaptar_tts as at
import thumbs_flow as tf


def registrar(app, base_dir: str) -> None:

    # ------------------------------------------------------------------ as ideias de thumbnail de cada lugar
    def _ideias(origem: str, pid: str) -> Optional[List[Any]]:
        try:
            if origem == "dossie":
                import dossies as ds
                return list(((ds.carregar(base_dir, pid).get("resultado") or {}).get("thumbnails")) or [])
            if origem == "roteiro_yt":
                import roteiros_yt as ry
                return list(((ry.carregar_projeto(base_dir, pid).get("resultado") or {}).get("thumbnails")) or [])
            if origem == "canal":
                import analisador_canal as ac
                sug = ((ac.carregar(base_dir, pid).get("ia") or {}).get("sugestoes")) or []
                return [{"ideia": f"Capa do vídeo “{s.get('titulo')}”: {s.get('thumb')}", "texto": ""} for s in sug if s.get("thumb")]
        except Exception:  # noqa: BLE001 — projeto que não existe
            return None
        return None

    def _url(origem: str, pid: str) -> str:
        return f"/thumbs/{origem}/{pid}"

    @app.route("/thumbs/<origem>/<pid>")
    def thumbs_lista(origem: str, pid: str):
        ideias = _ideias(origem, pid) if origem in tf.ORIGENS else None
        if ideias is None:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        d = tf.sincronizar(base_dir, origem, pid, ideias)
        return jsonify(dict(tf.para_json(d, _url(origem, pid)), ok=True))

    @app.route("/thumbs/<origem>/<pid>/editar", methods=["POST"])
    def thumbs_editar(origem: str, pid: str):
        if _ideias(origem, pid) is None:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        c = request.get_json(silent=True) or {}
        try:
            d = tf.editar(base_dir, origem, pid, int(c.get("n") or 0), **{k: c[k] for k in ("texto", "prompt", "ideia", "novo", "apagar") if k in c})
        except (tf.ThumbErro, ValueError) as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify(dict(tf.para_json(d, _url(origem, pid)), ok=True))

    @app.route("/thumbs/<origem>/<pid>/gerar", methods=["POST"])
    def thumbs_gerar(origem: str, pid: str):
        if _ideias(origem, pid) is None:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        c = request.get_json(silent=True) or {}
        ns = [int(x) for x in c.get("ns") or []] or None
        tarefa = tf.iniciar(base_dir, origem, pid, ns, bool(c.get("forcar")), pagina=str(c.get("pagina") or ""))
        return jsonify({"ok": True, "tarefa": tarefa})

    @app.route("/thumbs/<origem>/<pid>/<int:n>/<qual>")
    def thumbs_arquivo(origem: str, pid: str, n: int, qual: str):
        if origem not in tf.ORIGENS or qual not in ("imagem", "final"):
            return "Não encontrado.", 404
        try:
            d = tf.carregar(base_dir, origem, pid)
        except tf.ThumbErro:
            return "Não encontrado.", 404
        it = next((i for i in d.get("itens") or [] if int(i.get("n") or 0) == n), None)
        cam = (it or {}).get(qual)
        if not cam or not os.path.isfile(cam):
            return "Não encontrado.", 404
        return send_file(cam, as_attachment=request.args.get("baixar") == "1",
                         download_name=f"thumbnail_{n}{os.path.splitext(cam)[1]}")

    # ------------------------------------------------------------------ 🎙 adaptar pro TTS
    def _roteiro(origem: str, pid: str) -> Tuple[Any, str, Dict[str, Any]]:
        """(projeto, texto atual, padrões: idioma, direção, canal, inícios de capítulo)."""
        import canal
        if origem == "dossie":
            import dossies as ds
            p = ds.carregar(base_dir, pid)
            res = p.get("resultado") or {}
            cfg = dict(ds.CONFIG_PADRAO, **(p.get("config") or {}))
            _mins, _alvo, _ppm = ds.alvo_tamanho(p)
            return p, res.get("roteiro") or "", {"minutos": _mins, "alvo": _alvo,
                "idioma": cfg.get("idioma") or "pt", "direcao": at.DIRECAO_DO_MODELO.get(cfg.get("modelo"), "documentario"),
                "canal": canal.nome_do_projeto(cfg.get("nome_canal")),
                "inicios": [c.get("comeca_em") for c in res.get("capitulos") or [] if c.get("comeca_em")],
                "antes": res.get("roteiro_antes_tts") or ""}
        if origem == "roteiro_yt":
            import idiomas
            import roteiros_yt as ry
            p = ry.carregar_projeto(base_dir, pid)
            res, an = p.get("resultado") or {}, p.get("analise") or {}
            alvo = res if res.get("roteiro_final") else an
            texto = alvo.get("roteiro_final") if alvo is res else alvo.get("roteiro")
            try:
                _mins, _alvo = ry.alvo_palavras(p)
            except Exception:  # noqa: BLE001
                _mins, _alvo = 0, 0
            return p, texto or "", {"minutos": _mins, "alvo": _alvo,
                "idioma": idiomas.normalizar(res.get("idioma") or an.get("idioma") or p.get("idioma_roteiro")) or "pt",
                "direcao": p.get("tts_direcao") or "documentario", "canal": canal.nome_do_projeto(p.get("nome_canal")),
                "inicios": [c.get("comeca_em") for c in res.get("capitulos") or [] if c.get("comeca_em")],
                "antes": alvo.get("antes_do_tts") or ""}
        raise ValueError("Origem inválida.")

    def _gravar(origem: str, pid: str, p: Dict[str, Any], novo: str, antes: Optional[str], avisos: List[str],
                chave_antes: str = "", hist: Tuple[str, str] = ("", "")) -> Dict[str, Any]:
        """Grava o roteiro novo. chave_antes "-" = não mexe nos "voltar"; hist = (origem, mensagem) pro 🕘 histórico."""
        if origem == "dossie":
            import dossies as ds
            import dossies_rotas
            with dossies_rotas._TRAVA:
                p = ds.carregar(base_dir, pid)
                velho = p.get("resultado") or {}
                res = ds.roteiro_editado(p, novo)
                for k in ("roteiro_antes_tts", "roteiro_antes_revisao"):  # o "voltar" de cada um sobrevive ao outro
                    if velho.get(k):
                        res[k] = velho[k]
                for k in ("partes", "checagem"):
                    if velho.get(k):
                        res[k] = velho[k]
                if chave_antes != "-":
                    res[chave_antes or "roteiro_antes_tts"] = antes or ""
                res["avisos"] = list(avisos) + list(res.get("avisos") or [])
                p["resultado"] = res
                ds.marcar_mudanca(p, hist[0] or "alteração", hist[1])
                ds.salvar(base_dir, p)
            return {"palavras": res.get("palavras"), "avisos": res["avisos"]}
        import roteiros_yt as ry
        p = ry.carregar_projeto(base_dir, pid)
        res, an = p.get("resultado") or {}, p.get("analise") or {}
        alvo, chave = (res, "roteiro_final") if res.get("roteiro_final") else (an, "roteiro")
        ch = {"roteiro_antes_revisao": "antes_da_revisao"}.get(chave_antes, "antes_do_tts")
        if chave_antes == "-":
            pass
        elif antes is None:
            alvo.pop(ch, None)
        else:
            alvo[ch] = antes
        alvo[chave] = novo
        ry.marcar_mudanca(p, hist[0] or "alteração", hist[1])
        ry.salvar_projeto(base_dir, p)
        return {"palavras": len(novo.split()), "avisos": avisos}

    @app.route("/tts-adaptar/<origem>/<pid>/prompt", methods=["POST"])
    def tts_adaptar_prompt(origem: str, pid: str):
        try:
            p, texto, pad = _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        c = request.get_json(silent=True) or {}
        idioma = (c.get("idioma") or pad["idioma"] or "pt")[:5]
        direcao = c.get("direcao") if c.get("direcao") in at.DIRECOES else pad["direcao"]
        motor = c.get("motor") if c.get("motor") in at.MOTORES else "chatterbox"
        if origem == "roteiro_yt" and c.get("direcao") in at.DIRECOES:  # lembra a direção escolhida
            import roteiros_yt as ry
            p["tts_direcao"] = direcao
            ry.salvar_projeto(base_dir, p)
        try:
            texto_p = at.prompt(texto, idioma, direcao, pad["canal"], motor, pad["inicios"])
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400
        R = at.regras_do_idioma(idioma)
        return jsonify({"ok": True, "prompt": texto_p, "caracteres": len(texto_p), "idioma": idioma, "direcao": direcao,
                        "especifico": R["especifico"], "nome_idioma": R["nome"]})

    @app.route("/tts-adaptar/<origem>/<pid>/ler", methods=["POST"])
    def tts_adaptar_ler(origem: str, pid: str):
        try:
            p, texto, pad = _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            r = at.ler_resposta(str((request.get_json(silent=True) or {}).get("texto") or ""), texto)
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400
        avisos = ["🎙 " + a for a in r["avisos"]]
        if r["colchetes"]:
            avisos.append("🎙 Colchetes no texto (podem ser lidos em voz alta): " + ", ".join(f"[{x}]" for x in r["colchetes"][:8]))
        try:
            g = _gravar(origem, pid, p, r["texto"], pad["antes"] or texto, avisos,
                        hist=("🎙 adaptado pro TTS", f"{r['palavras_antes']} → {r['palavras_depois']} palavras"))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"erro": str(exc)[:300]}), 400
        return jsonify({"ok": True, "palavras_antes": r["palavras_antes"], "palavras_depois": r["palavras_depois"], **g})

    @app.route("/tts-adaptar/<origem>/<pid>/desfazer", methods=["POST"])
    def tts_adaptar_desfazer(origem: str, pid: str):
        try:
            p, _texto, pad = _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        if not pad["antes"]:
            return jsonify({"erro": "Não tem adaptação pra desfazer."}), 400
        g = _gravar(origem, pid, p, pad["antes"], None, [], hist=("↩ desfazer", "voltou ao roteiro de antes do TTS"))
        if origem == "dossie":  # tira a marca de "antes"
            import dossies as ds
            import dossies_rotas
            with dossies_rotas._TRAVA:
                p = ds.carregar(base_dir, pid)
                (p.get("resultado") or {}).pop("roteiro_antes_tts", None)
                ds.salvar(base_dir, p)
        return jsonify({"ok": True, **g})

    # ------------------------------------------------------------------ 🪄 revisão do roteiro inteiro (v84_98)
    @app.route("/revisao/<origem>/<pid>/prompt", methods=["POST"])
    def revisao_prompt(origem: str, pid: str):
        import idiomas
        import revisao_roteiro as rv
        try:
            p, texto, pad = _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            c = request.get_json(silent=True) or {}
            modo = rv.modo_efetivo(str(c.get("modo") or "auto"), rv.palavras(texto), int(pad.get("alvo") or 0))
            t = rv.prompt(texto, idiomas.nome_para_prompt(idiomas.normalizar(pad["idioma"]) or "pt"),
                          str(p.get("tema") or p.get("titulo") or ""), str(c.get("foco") or ""),
                          alvo_palavras=int(pad.get("alvo") or 0), minutos=float(pad.get("minutos") or 0), modo=modo)
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True, "prompt": t, "caracteres": len(t), "modo": modo, "palavras": rv.palavras(texto),
                        "alvo": int(pad.get("alvo") or 0), "minutos": pad.get("minutos") or 0})

    @app.route("/revisao/<origem>/<pid>/info")
    def revisao_info(origem: str, pid: str):
        import revisao_roteiro as rv
        try:
            _p, texto, pad = _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        n, alvo = rv.palavras(texto), int(pad.get("alvo") or 0)
        return jsonify({"ok": True, "palavras": n, "alvo": alvo, "minutos": pad.get("minutos") or 0,
                        "modo_auto": rv.modo_efetivo("auto", n, alvo), "modos": rv.MODOS})

    @app.route("/revisao/<origem>/<pid>/ler", methods=["POST"])
    def revisao_ler(origem: str, pid: str):
        import revisao_roteiro as rv
        try:
            p, texto, pad = _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            r = rv.aplicar(texto, str((request.get_json(silent=True) or {}).get("texto") or ""))
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400
        if not r["aplicadas"]:
            return jsonify({"erro": "Nenhuma troca bateu com o roteiro (" + str(len(r["nao_achadas"])) + " não achadas).", **r}), 400
        antes = (p.get("resultado") or {}).get("roteiro_antes_revisao") if origem == "dossie" else \
            (((p.get("resultado") or {}) if (p.get("resultado") or {}).get("roteiro_final") else (p.get("analise") or {})).get("antes_da_revisao"))
        avisos = [f"🪄 {len(r['nao_achadas'])} troca(s) da revisão não bateram com o texto."] if r["nao_achadas"] else []
        g = _gravar(origem, pid, p, r["texto"], antes or texto, avisos, chave_antes="roteiro_antes_revisao",
                    hist=("🪄 revisão", f"{len(r['aplicadas'])} troca(s) · {r['palavras_antes']} → {r['palavras_depois']} palavras"))
        return jsonify({"ok": True, **{k: r[k] for k in ("aplicadas", "nao_achadas", "palavras_antes", "palavras_depois", "observacoes")}, **g})

    @app.route("/revisao/<origem>/<pid>/desfazer", methods=["POST"])
    def revisao_desfazer(origem: str, pid: str):
        try:
            p, _texto, _pad = _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        if origem == "dossie":
            antes = (p.get("resultado") or {}).get("roteiro_antes_revisao")
        else:
            res, an = p.get("resultado") or {}, p.get("analise") or {}
            antes = (res if res.get("roteiro_final") else an).get("antes_da_revisao")
        if not antes:
            return jsonify({"erro": "Não tem revisão pra desfazer."}), 400
        _gravar(origem, pid, p, antes, None, [], chave_antes="roteiro_antes_revisao",
                hist=("↩ desfazer", "voltou ao roteiro de antes da revisão"))
        if origem == "dossie":
            import dossies as ds
            import dossies_rotas
            with dossies_rotas._TRAVA:
                q = ds.carregar(base_dir, pid)
                (q.get("resultado") or {}).pop("roteiro_antes_revisao", None)
                ds.salvar(base_dir, q)
        return jsonify({"ok": True})

    @app.route("/tts-adaptar/opcoes")
    def tts_adaptar_opcoes():
        return jsonify({"direcoes": {k: v["nome"] for k, v in at.DIRECOES.items()}, "especificos": at.idiomas_especificos(),
                        "motores": {k: v for k, v in at.MOTORES.items() if k}})

    # ------------------------------------------------------------------ 🔎 checagem: cronologia · alegações · repetições (v84_99)
    def _pasta_proj(origem: str, pid: str) -> str:
        if origem == "dossie":
            import dossies as ds
            return ds._pasta(base_dir, pid)
        import roteiros_yt as ry
        return ry._pasta(base_dir, pid)

    def _fontes(origem: str, p: Dict[str, Any]) -> str:
        try:
            if origem == "dossie":
                import dossies as ds
                return ds._fontes_texto(p, 60000)
            blocos = (p.get("transcricao") or {}).get("blocos") or []
            t = " ".join(str(b.get("texto") or "") for b in blocos)
            return ("F1 — transcrição do vídeo original:\n" + t[:60000]) if t.strip() else ""
        except Exception:  # noqa: BLE001
            return ""

    def _guardar(origem: str, pid: str, chave: str, valor: Any) -> None:
        """Guarda um campo de 1º nível do projeto (ex.: a última checagem)."""
        if origem == "dossie":
            import dossies as ds
            import dossies_rotas
            with dossies_rotas._TRAVA:
                q = ds.carregar(base_dir, pid)
                q[chave] = valor
                ds.salvar(base_dir, q)
            return
        import roteiros_yt as ry
        q = ry.carregar_projeto(base_dir, pid)
        q[chave] = valor
        ry.salvar_projeto(base_dir, q)

    @app.route("/checagem/<origem>/<pid>")
    def checagem_ver(origem: str, pid: str):
        import checagem_roteiro as ch
        try:
            p, texto, pad = _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        tema = str(p.get("tema") or p.get("titulo") or "")
        a = ch.analisar(texto, tema) if texto.strip() else {}
        cr = ch.cronologia(texto, tema) if texto.strip() else {}
        cr.pop("ano_de", None)
        return jsonify({"ok": True, "local": a, "cronologia": cr, "ultima": p.get("checagem") or None})

    @app.route("/checagem/<origem>/<pid>/prompt", methods=["POST"])
    def checagem_prompt(origem: str, pid: str):
        import checagem_roteiro as ch
        import idiomas
        try:
            p, texto, pad = _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        c = request.get_json(silent=True) or {}
        try:
            t = ch.prompt(texto, idiomas.nome_para_prompt(idiomas.normalizar(pad["idioma"]) or "pt"),
                          str(p.get("tema") or p.get("titulo") or ""), _fontes(origem, p), str(c.get("foco") or ""))
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True, "prompt": t, "caracteres": len(t)})

    def _aplicar_checagem(origem: str, pid: str, resposta: str) -> Dict[str, Any]:
        import json as _json
        import time as _time

        import checagem_roteiro as ch
        import revisao_roteiro as rv
        p, texto, _pad = _roteiro(origem, pid)
        d = ch.ler(resposta)
        r = rv.aplicar(texto, _json.dumps({"trocas": d["trocas"]}, ensure_ascii=False))
        por_eixo = {e: sum(1 for t in d["trocas"] if t.get("eixo") == e and any(a["de"] == t["de"][:200] for a in r["aplicadas"]))
                    for e in ("cronologia", "alegacao", "repeticao")}
        g = {}
        if r["aplicadas"]:
            avisos = [f"🔎 {len(r['nao_achadas'])} correção(ões) da checagem não bateram com o texto."] if r["nao_achadas"] else []
            g = _gravar(origem, pid, p, r["texto"], None, avisos, chave_antes="-",
                        hist=("🔎 checagem", f"⏳ {por_eixo['cronologia']} · 📚 {por_eixo['alegacao']} · ✂️ {por_eixo['repeticao']} "
                                             f"correções · {r['palavras_antes']} → {r['palavras_depois']} palavras"))
        reg = {"quando": _time.time(), "resumo": d["resumo"], "verificar": d["verificar"], "inconsistencias": d["inconsistencias"],
               "linha_do_tempo": d["linha_do_tempo"], "aplicadas": r["aplicadas"], "nao_achadas": r["nao_achadas"],
               "por_eixo": por_eixo, "palavras_antes": r["palavras_antes"], "palavras_depois": r["palavras_depois"]}
        for t in reg["aplicadas"]:
            orig = next((x for x in d["trocas"] if x["de"][:200] == t["de"]), {})
            t["eixo"], t["fonte"] = orig.get("eixo", ""), orig.get("fonte", "")
        _guardar(origem, pid, "checagem", reg)
        return {**reg, **g}

    @app.route("/checagem/<origem>/<pid>/ler", methods=["POST"])
    def checagem_ler(origem: str, pid: str):
        try:
            _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            r = _aplicar_checagem(origem, pid, str((request.get_json(silent=True) or {}).get("texto") or ""))
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True, **r})

    # ------------------------------------------------------------------ 🌐 checagem por uma 2ª IA com internet (v84_133)
    @app.route("/checagem/<origem>/<pid>/web/prompt", methods=["POST"])
    def checagem_web_prompt(origem: str, pid: str):
        import checagem_roteiro as ch
        import idiomas
        try:
            p, texto, pad = _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        c = request.get_json(silent=True) or {}
        try:
            t = ch.prompt_web(texto, idiomas.nome_para_prompt(idiomas.normalizar(pad["idioma"]) or "pt"),
                              str(p.get("tema") or p.get("titulo") or ""), p.get("checagem") or {},
                              (p.get("resultado") or {}).get("afirmacoes") or [], str(c.get("foco") or ""))
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True, "prompt": t, "caracteres": len(t), "palavras_roteiro": len(texto.split())})

    @app.route("/checagem/<origem>/<pid>/web/ler", methods=["POST"])
    def checagem_web_ler(origem: str, pid: str):
        import json as _json
        import time as _time

        import checagem_roteiro as ch
        import revisao_roteiro as rv
        try:
            p, texto, _pad = _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            d = ch.ler_web(str((request.get_json(silent=True) or {}).get("texto") or ""))
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400
        if not d["trocas"] and not d["conferidos"]:
            return jsonify({"erro": "O JSON não tem \"correcoes\" nem \"conferidos\"."}), 400
        r = rv.aplicar(texto, _json.dumps({"trocas": d["trocas"]}, ensure_ascii=False))
        g = {}
        if r["aplicadas"]:
            avisos = [f"🌐 {len(r['nao_achadas'])} correção(ões) da checagem na internet não bateram com o texto."] if r["nao_achadas"] else []
            g = _gravar(origem, pid, p, r["texto"], None, avisos, chave_antes="-",
                        hist=("🌐 checagem na internet", f"{len(r['aplicadas'])} correção(ões) · {r['palavras_antes']} → {r['palavras_depois']} palavras"))
            p, _t, _pad = _roteiro(origem, pid)
        reg = p.get("checagem") or {}
        for t in r["aplicadas"]:
            orig = next((x for x in d["trocas"] if x["de"][:200] == t["de"]), {})
            t["eixo"], t["fonte"], t["web"] = orig.get("eixo", ""), orig.get("fonte", ""), True
        ver = reg.get("verificar") or []
        marcados = 0
        for c in d["conferidos"]:
            if c["item"].startswith("V") and c["item"][1:].isdigit() and c["ok"]:
                i = int(c["item"][1:]) - 1
                if 0 <= i < len(ver):
                    ver[i].update(conferido=True, fonte_web=c["fonte"], nota_web=c["nota"])
                    marcados += 1
        reg["verificar"] = ver
        reg["aplicadas"] = (reg.get("aplicadas") or []) + r["aplicadas"]
        reg["web"] = {"quando": _time.time(), "resumo": d["resumo"], "aplicadas": len(r["aplicadas"]),
                      "nao_achadas": r["nao_achadas"], "conferidos": d["conferidos"]}
        _guardar(origem, pid, "checagem", reg)
        return jsonify({"ok": True, "aplicadas": r["aplicadas"], "nao_achadas": r["nao_achadas"], "conferidos": d["conferidos"],
                        "verificar_marcados": marcados, "palavras_antes": r["palavras_antes"],
                        "palavras_depois": r["palavras_depois"], "resumo": d["resumo"], **g})

    @app.route("/checagem/<origem>/<pid>/verificar/<int:i>", methods=["POST"])
    def checagem_conferido(origem: str, pid: str, i: int):
        try:
            p, _t, _pad = _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        reg = p.get("checagem") or {}
        lista = reg.get("verificar") or []
        if not 0 <= i < len(lista):
            return jsonify({"erro": "Item não encontrado."}), 404
        lista[i]["conferido"] = bool((request.get_json(silent=True) or {}).get("conferido"))
        _guardar(origem, pid, "checagem", reg)
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ 🤖 tudo automático: revisão → checagem → enxugar
    @app.route("/roteiro-auto/<origem>/<pid>", methods=["POST"])
    def roteiro_auto(origem: str, pid: str):
        """🤖 Melhora (🪄 revisão, enxugando se passou do tempo) → 🔎 checa cronologia/alegações/repetições e corrige →
        se ainda ficou longo, ✂️ enxuga de novo. Cada passo vira uma versão no 🕘 histórico."""
        import ia_servico as ia
        import tarefas_bg
        try:
            _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        if not ia.ativo("roteiros"):
            return jsonify({"erro": "A IA está desligada (" + (ia.motivo_desligado("roteiros") or "ligue em 🤖 IA") + ")."}), 400
        foco = str((request.get_json(silent=True) or {}).get("foco") or "")
        pagina = str((request.get_json(silent=True) or {}).get("pagina") or "")
        system = "Siga o pedido do usuário e responda SÓ com o JSON pedido, sem texto antes ou depois, sem ``` em volta."

        def chamar(prompt: str) -> str:
            texto = ia.chamar("roteiros", system, prompt, schema=None, max_tokens=32000, effort="medium", timeout=900)
            if not texto:
                raise RuntimeError("A IA não respondeu (" + (ia.motivo_desligado("roteiros") or "veja 🤖 IA") + ").")
            return texto

        def revisar(t, modo: str) -> Dict[str, Any]:
            import idiomas
            import revisao_roteiro as rv
            p, texto, pad = _roteiro(origem, pid)
            m = rv.modo_efetivo(modo, rv.palavras(texto), int(pad.get("alvo") or 0))
            t.progresso(("✂️ enxugando" if m == "enxugar" else "🪄 revisando") + " o roteiro com a IA…")
            pr = rv.prompt(texto, idiomas.nome_para_prompt(idiomas.normalizar(pad["idioma"]) or "pt"),
                           str(p.get("tema") or p.get("titulo") or ""), foco, alvo_palavras=int(pad.get("alvo") or 0),
                           minutos=float(pad.get("minutos") or 0), modo=m)
            r = rv.aplicar(texto, chamar(pr))
            if r["aplicadas"]:
                antes = (p.get("resultado") or {}).get("roteiro_antes_revisao") if origem == "dossie" else None
                _gravar(origem, pid, p, r["texto"], antes or texto, [], chave_antes="roteiro_antes_revisao",
                        hist=("🪄 revisão" if m == "melhorar" else "✂️ enxugar",
                              f"🤖 automático · {len(r['aplicadas'])} troca(s) · {r['palavras_antes']} → {r['palavras_depois']} palavras"))
            return {"modo": m, "aplicadas": len(r["aplicadas"]), "palavras": r["palavras_depois"]}

        def rodar(t):
            import checagem_roteiro as ch
            import idiomas
            passos = [revisar(t, "auto")]
            t.progresso("🔎 checando cronologia, alegações históricas e repetições…")
            p, texto, pad = _roteiro(origem, pid)
            pr = ch.prompt(texto, idiomas.nome_para_prompt(idiomas.normalizar(pad["idioma"]) or "pt"),
                           str(p.get("tema") or p.get("titulo") or ""), _fontes(origem, p), foco)
            c = _aplicar_checagem(origem, pid, chamar(pr))
            passos.append({"modo": "checagem", "aplicadas": len(c["aplicadas"]), "palavras": c["palavras_depois"],
                           "verificar": len(c["verificar"])})
            import revisao_roteiro as rv
            _p, texto, pad = _roteiro(origem, pid)
            if pad.get("alvo") and rv.palavras(texto) > int(pad["alvo"]) * 1.1:
                passos.append(revisar(t, "enxugar"))
            return {"passos": passos}

        tid = tarefas_bg.iniciar("roteiro_auto", "🤖 Revisar + checar + corrigir o roteiro", rodar, pagina=pagina)
        return jsonify({"ok": True, "tarefa": tid})

    # ------------------------------------------------------------------ 🕘 histórico de versões (v84_99)
    @app.route("/historico/<origem>/<pid>")
    def historico_lista(origem: str, pid: str):
        import historico_roteiro as hr
        try:
            _p, texto, _pad = _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        pasta = _pasta_proj(origem, pid)
        if texto.strip() and not hr.listar(pasta):  # projeto de antes do histórico: o roteiro atual vira a v1
            hr.registrar(pasta, texto, "📌 início do histórico", "o roteiro como estava quando o histórico começou")
        return jsonify({"ok": True, "versoes": hr.listar(pasta)})

    @app.route("/historico/<origem>/<pid>/<int:n>")
    def historico_versao(origem: str, pid: str, n: int):
        import historico_roteiro as hr
        try:
            _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        pasta = _pasta_proj(origem, pid)
        t = hr.texto(pasta, n)
        if t is None:
            return jsonify({"erro": "Versão não encontrada."}), 404
        versoes = [v["n"] for v in hr.listar(pasta)]
        try:
            contra = int(request.args.get("contra") or 0)
        except ValueError:
            contra = 0
        if not contra:
            contra = max([m for m in versoes if m < n] or [0])
        base_txt = hr.texto(pasta, contra) if contra else ""
        return jsonify({"ok": True, "n": n, "texto": t, "contra": contra, "diff": hr.diff(base_txt or "", t)})

    @app.route("/historico/<origem>/<pid>/<int:n>/restaurar", methods=["POST"])
    def historico_restaurar(origem: str, pid: str, n: int):
        import historico_roteiro as hr
        try:
            p, _texto, _pad = _roteiro(origem, pid)
        except Exception:  # noqa: BLE001
            return jsonify({"erro": "Projeto não encontrado."}), 404
        t = hr.texto(_pasta_proj(origem, pid), n)
        if t is None:
            return jsonify({"erro": "Versão não encontrada."}), 404
        g = _gravar(origem, pid, p, t, None, [], chave_antes="-", hist=("🕘 restaurado", f"voltou pra versão v{n}"))
        return jsonify({"ok": True, **g})
