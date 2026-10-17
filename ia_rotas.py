"""🤖 Página /ia — liga a IA (hoje o Claude Haiku 5.5) nas buscas, no editor e nos Modelos de vídeo."""
from __future__ import annotations

from typing import Any

import ia_servico as ia


def registrar(app, base_dir: str) -> None:
    from flask import jsonify, redirect, render_template, request, url_for

    @app.context_processor
    def _ia_no_template():
        def ia_resumo():
            try:
                return ia.resumo_publico()
            except Exception:  # noqa: BLE001
                return {"motivo": "erro ao ler a config", "modelo": ""}
        return {"ia_resumo": ia_resumo}

    def _pagina(**extra: Any):
        return render_template("ia.html", r=ia.resumo_publico(), provedores=ia.PROVEDORES, recursos=ia.RECURSOS,
                               recentes=ia.recentes()[:15], **extra)

    @app.route("/ia", methods=["GET"])
    def ia_page():
        return _pagina()

    @app.route("/ia", methods=["POST"])
    def ia_salvar():
        f = request.form
        novos: dict = {
            "ativo": f.get("ativo") == "on", "provedor": f.get("provedor") or "claude", "modelo": f.get("modelo") or "",
            "recursos": {k: f.get(f"rec_{k}") == "on" for k in ia.RECURSOS},
            "nota_minima": f.get("nota_minima", 7), "candidatos": f.get("candidatos", 10), "limite_usd": f.get("limite_usd", 5),
        }
        aviso = None
        chave = (f.get("chave") or "").strip()
        if chave:  # em branco = mantém a salva
            prefixo = ia.PROVEDORES.get(novos["provedor"], {}).get("prefixo_chave") or ""
            if prefixo and not chave.startswith(prefixo):
                # quase sempre é o navegador preenchendo sozinho com uma senha salva: não troca a chave boa
                aviso = (f"Isso não parece uma chave do {ia.PROVEDORES[novos['provedor']]['nome']} (ela começa com {prefixo}). "
                         "A chave salva foi mantida — se o navegador preencheu o campo sozinho, apague e cole a chave de novo.")
            else:
                novos["chave"] = chave
        if f.get("apagar_chave") == "on":
            novos["chave"] = ""
        ia.salvar_config(novos)
        return _pagina(salvo=not aviso, aviso=aviso)

    def _gerar_roteiro(prompt: str) -> str:
        import re
        # v84_99: prompts que pedem TEXTO PURO (🎙 adaptar pro TTS, ✍️ uma parte do roteiro) não podem receber o system de
        # "só JSON" — a IA embrulhava o texto num JSON com uma chave qualquer e o site não achava o roteiro.
        if re.search(r"sem JSON|TEXTO PURO|no JSON|plain text", prompt[-2500:], re.I):
            system = ("Siga o pedido do usuário e responda SÓ com o texto pedido, em texto puro — sem JSON, sem ``` em volta, "
                      "sem título e sem comentário antes ou depois.")
        else:
            system = "Siga o pedido do usuário e responda SÓ com o JSON pedido, sem texto antes ou depois, sem ``` em volta."
        import idiomas
        m = re.search(r"output language code: ([a-z]{2,3}(?:-[A-Za-z]{2})?)", prompt) or re.search(r"\(([a-z]{2})\) — roteiro", prompt)
        cod = idiomas.normalizar(m.group(1)) if m else None
        if cod and cod != "pt":  # 🌐 o idioma de saída vai também no system (a IA tende a seguir o idioma das instruções)
            nome = idiomas.IDIOMAS.get(cod, (cod, cod))[1]
            system += (f"\n\nOUTPUT LANGUAGE: {nome}. Every text value in the JSON (script/roteiro, titles, chapters, description, "
                       f"tags, CTA, notes) MUST be written in {nome}, even though the instructions and the sources are in Portuguese. "
                       f"Translate the facts faithfully. Keep the JSON keys exactly as in the example.")
        texto = ia.chamar("roteiros", system, prompt, schema=None, max_tokens=64000, effort="medium", timeout=900)
        if not texto:
            raise RuntimeError("A IA não respondeu (" + (ia.motivo_desligado("roteiros") or "veja as últimas chamadas em 🤖 IA") + ").")
        return texto

    @app.route("/ia/gerar", methods=["POST"])
    def ia_gerar():
        """📝 Manda um prompt de roteiro (Modelos de vídeo, Venda, Roteiro do YouTube, Modelados) pra IA e devolve o texto.
        Com "bg": true roda em SEGUNDO PLANO (v84_87): devolve o id da tarefa — pode fechar a aba; ao voltar na página
        a resposta é colada sozinha (e chega um aviso no 🔔)."""
        motivo = ia.motivo_desligado("roteiros")
        if motivo:
            return jsonify({"erro": "IA: " + motivo + " — ligue em 🤖 IA nas buscas e modelos."}), 400
        corpo = request.get_json(silent=True) or {}
        prompt = str(corpo.get("prompt") or "")
        if not prompt.strip():
            return jsonify({"erro": "O prompt veio vazio."}), 400
        if corpo.get("bg"):
            import tarefas_bg
            alvo = {k: str(v)[:80] for k, v in (corpo.get("alvo") or {}).items() if k in ("resp", "ler", "prompt", "botao")} \
                if isinstance(corpo.get("alvo"), dict) else {}
            titulo = "🤖 " + (str(corpo.get("titulo") or "").strip()[:120] or "Roteiro pela IA")
            rot = str(corpo.get("titulo") or "").strip()[:100]

            def _rodar(_t):
                with ia.rotulo(rot):
                    return {"texto": _gerar_roteiro(prompt)}
            tid = tarefas_bg.iniciar("ia_gerar", titulo, _rodar,
                                     pagina=str(corpo.get("pagina") or ""), alvo=alvo)
            return jsonify({"ok": True, "tarefa": tid})
        try:
            with ia.rotulo(str(corpo.get("titulo") or "").strip()[:100]):
                texto = _gerar_roteiro(prompt)
        except RuntimeError as exc:
            return jsonify({"erro": str(exc)}), 200
        return jsonify({"ok": True, "texto": texto})

    @app.route("/ia/testar", methods=["POST"])
    def ia_testar():
        return jsonify(ia.testar())

    @app.route("/ia/tentar-de-novo", methods=["POST"])
    def ia_tentar_de_novo():
        ia.salvar_config({"limpar_sem_credito": True})
        return redirect(url_for("ia_page"))

    @app.route("/ia/zerar-gasto", methods=["POST"])
    def ia_zerar_gasto():
        ia.zerar_gasto()
        return redirect(url_for("ia_page"))

    @app.route("/ia/saldo")
    def ia_saldo():
        """🪙 v84_161: o número ao lado do sininho e a lista do que rodou (custo por ação)."""
        d = ia.saldo()
        try:  # 🔷 v84_162: o Gemini da checagem na internet aparece junto (custo estimado + cota grátis da busca)
            import gemini_servico as gm
            g = gm.resumo()
            d["gemini"] = {k: g[k] for k in ("tem_chave", "modelo", "gasto_usd", "chamadas", "buscas_usadas", "buscas_gratis",
                                             "buscas_periodo", "console")}
        except Exception:  # noqa: BLE001
            d["gemini"] = None
        return jsonify(d)

    @app.route("/ia/credito", methods=["POST"])
    def ia_credito():
        corpo = request.get_json(silent=True) or {}
        c = ia.salvar_config({"credito_usd": corpo.get("credito_usd") or 0})
        return jsonify({"ok": True, "credito_usd": c.get("credito_usd", 0)})

    @app.route("/ia/status")
    def ia_status():
        r = ia.resumo_publico()
        r["pode"] = {k: ia.ativo(k) for k in ia.RECURSOS}
        return jsonify(r)
