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
            return p, res.get("roteiro") or "", {
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
            return p, texto or "", {
                "idioma": idiomas.normalizar(res.get("idioma") or an.get("idioma") or p.get("idioma_roteiro")) or "pt",
                "direcao": p.get("tts_direcao") or "documentario", "canal": canal.nome_do_projeto(p.get("nome_canal")),
                "inicios": [c.get("comeca_em") for c in res.get("capitulos") or [] if c.get("comeca_em")],
                "antes": alvo.get("antes_do_tts") or ""}
        raise ValueError("Origem inválida.")

    def _gravar(origem: str, pid: str, p: Dict[str, Any], novo: str, antes: Optional[str], avisos: List[str]) -> Dict[str, Any]:
        if origem == "dossie":
            import dossies as ds
            import dossies_rotas
            with dossies_rotas._TRAVA:
                p = ds.carregar(base_dir, pid)
                res = ds.roteiro_editado(p, novo)
                res["roteiro_antes_tts"] = antes or ""
                res["avisos"] = list(avisos) + list(res.get("avisos") or [])
                p["resultado"] = res
                ds.salvar(base_dir, p)
            return {"palavras": res.get("palavras"), "avisos": res["avisos"]}
        import roteiros_yt as ry
        p = ry.carregar_projeto(base_dir, pid)
        res, an = p.get("resultado") or {}, p.get("analise") or {}
        alvo, chave = (res, "roteiro_final") if res.get("roteiro_final") else (an, "roteiro")
        if antes is None:
            alvo.pop("antes_do_tts", None)
        else:
            alvo["antes_do_tts"] = antes
        alvo[chave] = novo
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
            g = _gravar(origem, pid, p, r["texto"], pad["antes"] or texto, avisos)
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
        g = _gravar(origem, pid, p, pad["antes"], None, [])
        if origem == "dossie":  # tira a marca de "antes"
            import dossies as ds
            import dossies_rotas
            with dossies_rotas._TRAVA:
                p = ds.carregar(base_dir, pid)
                (p.get("resultado") or {}).pop("roteiro_antes_tts", None)
                ds.salvar(base_dir, p)
        return jsonify({"ok": True, **g})

    @app.route("/tts-adaptar/opcoes")
    def tts_adaptar_opcoes():
        return jsonify({"direcoes": {k: v["nome"] for k, v in at.DIRECOES.items()}, "especificos": at.idiomas_especificos(),
                        "motores": {k: v for k, v in at.MOTORES.items() if k}})
