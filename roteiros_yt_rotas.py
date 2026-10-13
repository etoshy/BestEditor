"""
Rotas da aba 📜 Roteiro do YouTube (ver roteiros_yt.py). Registradas pelo
app.py com `registrar(app, base_dir)`.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from typing import Any, Dict, List

from flask import Response, jsonify, redirect, render_template, request, url_for

import roteiros_yt as ry

_TAREFAS: Dict[str, Dict[str, Any]] = {}


_TRAVA_CENAS = threading.Lock()


def _descr_cena(c: Dict[str, Any]) -> str:
    """O que procurar no vídeo (vai pra IA do Google)."""
    return (f"{c.get('obra') or ''} ({c.get('tipo') or ''}{' ' + str(c.get('ano')) if c.get('ano') else ''}): "
            f"{c.get('momento') or ''}" + (f" — {c['episodio_ou_tempo']}" if c.get("episodio_ou_tempo") else ""))


def _atualizar_cena(base_dir: str, pid: str, cid: int, dados: Dict[str, Any]) -> None:
    with _TRAVA_CENAS:
        pp = ry.carregar_projeto(base_dir, pid)
        for lista in ((pp.get("analise") or {}).get("cenas") or [], (pp.get("resultado") or {}).get("cenas") or []):
            for x in lista:
                if x.get("id") == cid:
                    x.update(dados)
        ry.salvar_projeto(base_dir, pp)


def _cenas_do(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    """As cenas que a página mostra (as do resultado; senão as da análise)."""
    return list((p.get("resultado") or {}).get("cenas") or (p.get("analise") or {}).get("cenas") or [])


def registrar(app, base_dir: str) -> None:

    @app.context_processor
    def _roteiros_no_template():
        def _lista():  # 📝 projetos com roteiro pronto (o "Novo vídeo" liga um ao vídeo)
            out = []
            for it in ry.listar_projetos(base_dir):
                if it.get("etapa") != "pronto":
                    continue
                try:
                    n = len(ry.cenas_atuais(ry.carregar_projeto(base_dir, it["id"])))
                except Exception:  # noqa: BLE001
                    n = 0
                out.append(dict(it, cenas=n))
            return out
        return {"roteiros_yt_lista": _lista}

    def _proj(pid: str):
        try:
            return ry.carregar_projeto(base_dir, pid)
        except ry.RoteiroError:
            return None

    @app.route("/roteiros-yt")
    def roteiros_yt_page():
        return render_template("roteiros_yt.html", projetos=ry.listar_projetos(base_dir), erro=request.args.get("erro"))

    @app.route("/roteiros-yt/novo", methods=["POST"])
    def roteiros_yt_novo():
        url = (request.form.get("url") or "").strip()
        texto = request.form.get("texto") or ""
        if not url and not texto.strip():
            return redirect(url_for("roteiros_yt_page", erro="Cole o link do vídeo ou a transcrição."))
        p = ry.criar_projeto(base_dir, url=url, texto=texto, titulo=request.form.get("titulo") or "")
        if url and not texto.strip():
            _transcrever(p["id"], url, usar_whisper=request.form.get("whisper", "on") == "on")
        return redirect(url_for("roteiro_yt_detalhe", pid=p["id"]))

    def _transcrever(pid: str, url: str, usar_whisper: bool = True) -> None:
        t = {"rodando": True, "log": [], "erro": None, "inicio": time.time()}
        _TAREFAS[pid] = t

        def log(m: str) -> None:
            t["log"] = (t["log"] + [time.strftime("%H:%M:%S ") + m])[-80:]

        def _th():
            try:
                tr = ry.extrair_transcricao(url, ry._pasta(base_dir, pid), on_log=log, usar_whisper=usar_whisper)
                p = ry.carregar_projeto(base_dir, pid)
                p["transcricao"] = tr
                p["titulo"] = p.get("titulo") or tr.get("titulo") or ""
                ry.salvar_projeto(base_dir, p)
            except Exception as exc:  # noqa: BLE001
                t["erro"] = str(exc) if isinstance(exc, ry.RoteiroError) else f"{exc}\n{traceback.format_exc()[-800:]}"
                log("✖ " + str(exc).splitlines()[0][:300])
            finally:
                t["rodando"] = False
                import notificacoes
                notificacoes.avisar(("❌ Roteiro do YouTube — transcrição deu erro" if t.get("erro") else "✅ Roteiro do YouTube — transcrição pronta"),
                                    str(t.get("erro") or "")[:400], f"/roteiros-yt/{pid}", "erro" if t.get("erro") else "ok", tipo="roteiro_yt")
        threading.Thread(target=_th, daemon=True).start()

    @app.route("/roteiros-yt/<pid>")
    def roteiro_yt_detalhe(pid: str):
        p = _proj(pid)
        if not p:
            return redirect(url_for("roteiros_yt_page", erro="Projeto não encontrado."))
        import idiomas
        return render_template(
            "roteiro_yt_detalhe.html", p=p, modelos=ry.modelos(base_dir), acoes=ry.ACOES,
            transcricao_txt=ry.texto_da_transcricao(p.get("transcricao") or {}),
            tarefa=_TAREFAS.get(pid) or {}, tags_som=ry.TAGS_SOM, tags_estilo=ry.TAGS_ESTILO,
            idiomas=[(k, v[0]) for k, v in idiomas.IDIOMAS.items()], usadas=ry.opcoes_usadas(base_dir),
        )

    @app.route("/roteiros-yt/<pid>/status")
    def roteiro_yt_status(pid: str):
        p = _proj(pid)
        t = _TAREFAS.get(pid) or {}
        return jsonify({"rodando": bool(t.get("rodando")), "log": t.get("log") or [], "erro": t.get("erro"),
                        "transcrito": bool(p and p.get("transcricao"))})

    @app.route("/roteiros-yt/<pid>/transcrever", methods=["POST"])
    def roteiro_yt_transcrever(pid: str):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        corpo = request.get_json(silent=True) or {}
        if corpo.get("texto"):
            p["transcricao"] = ry.transcricao_de_texto(corpo["texto"])
            ry.salvar_projeto(base_dir, p)
            return jsonify({"ok": True})
        url = (corpo.get("url") or p.get("url") or "").strip()
        if not url:
            return jsonify({"erro": "Sem link do vídeo."}), 400
        if (_TAREFAS.get(pid) or {}).get("rodando"):
            return jsonify({"erro": "Já está transcrevendo."}), 409
        p["url"] = url
        ry.salvar_projeto(base_dir, p)
        _transcrever(pid, url, usar_whisper=corpo.get("whisper", True) is not False)
        return jsonify({"ok": True})

    @app.route("/roteiros-yt/<pid>/prompt-analise", methods=["POST"])
    def roteiro_yt_prompt_analise(pid: str):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        corpo = request.get_json(silent=True) or {}
        modelo = ry.obter_modelo(base_dir, str(corpo.get("modelo_id") or p.get("modelo_id") or ""))
        import idiomas
        cod = idiomas.normalizar(corpo.get("idioma") or "")
        idioma = idiomas.nome_para_prompt(cod) if cod else "o mesmo idioma da transcrição"
        try:
            sem_exp = corpo.get("sem_experiencias", True) is not False
            texto = ry.prompt_analise(p, modelo, idioma, marcar_chamadas=corpo.get("marcar_chamadas", True) is not False,
                                      sem_experiencias=sem_exp)
            p["marcar_chamadas"] = corpo.get("marcar_chamadas", True) is not False
            p["sem_experiencias"] = sem_exp
            p["idioma_roteiro"] = cod or ""
            ry.lembrar_passo1(base_dir, {"modelo_id": modelo["id"], "idioma": cod or "",
                                         "marcar_chamadas": p["marcar_chamadas"], "sem_experiencias": sem_exp})
        except ry.RoteiroError as exc:
            return jsonify({"erro": str(exc)}), 400
        p["modelo_id"] = modelo["id"]
        ry.salvar_projeto(base_dir, p)
        return jsonify({"ok": True, "prompt": texto, "caracteres": len(texto)})

    @app.route("/roteiros-yt/<pid>/analise", methods=["POST"])
    def roteiro_yt_analise(pid: str):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            an = ry.ler_analise((request.get_json(silent=True) or {}).get("texto") or "")
        except ry.RoteiroError as exc:
            return jsonify({"erro": str(exc)}), 400
        p["analise"] = an
        p["resultado"] = None
        p["titulo"] = p.get("titulo") or an.get("titulo") or ""
        ry.salvar_projeto(base_dir, p)
        return jsonify({"ok": True, "analise": an})

    @app.route("/roteiros-yt/opcoes-usadas", methods=["GET", "DELETE"])
    def roteiro_yt_opcoes_usadas():
        if request.method == "DELETE":
            ry.esquecer_historico(base_dir)
        return jsonify({"ok": True, **ry.opcoes_usadas(base_dir)})

    @app.route("/roteiros-yt/<pid>/prompt-acoes", methods=["POST"])
    def roteiro_yt_prompt_acoes(pid: str):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        corpo = request.get_json(silent=True) or {}
        try:
            texto = ry.prompt_acoes(p, list(corpo.get("acoes") or []), idioma=str(corpo.get("idioma") or "en"),
                                    extra=str(corpo.get("extra") or ""), cta_no_texto=corpo.get("cta_no_texto", True) is not False)
        except ry.RoteiroError as exc:
            return jsonify({"erro": str(exc)}), 400
        p["acoes"] = {k: corpo.get(k) for k in ("acoes", "idioma", "extra", "cta_no_texto")}
        ry.salvar_projeto(base_dir, p)
        try:
            ry.lembrar_acoes(base_dir, p["acoes"])
        except OSError:
            pass
        return jsonify({"ok": True, "prompt": texto, "caracteres": len(texto)})

    @app.route("/roteiros-yt/<pid>/resultado", methods=["POST"])
    def roteiro_yt_resultado(pid: str):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            res = ry.ler_resultado((request.get_json(silent=True) or {}).get("texto") or "", p)
        except ry.RoteiroError as exc:
            return jsonify({"erro": str(exc)}), 400
        # links já escolhidos nas cenas da análise continuam valendo
        base = {c["id"]: c for c in (p.get("analise") or {}).get("cenas") or []}
        for c in res["cenas"]:
            for k in ("link", "link_inicio", "link_fim"):
                if base.get(c.get("id"), {}).get(k) and not c.get(k):
                    c[k] = base[c["id"]][k]
        p["resultado"] = res
        limpeza = None
        if "limpar_tts" in ((p.get("acoes") or {}).get("acoes") or []) and res.get("roteiro_final"):
            limpeza = ry.aplicar_limpeza(p)  # o que a IA deixou passar, o site tira
        ry.salvar_projeto(base_dir, p)
        return jsonify({"ok": True, "resultado": p["resultado"], "limpeza": limpeza})

    @app.route("/roteiros-yt/<pid>/limpar-tts", methods=["POST"])
    def roteiro_yt_limpar_tts(pid: str):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            if (request.get_json(silent=True) or {}).get("desfazer"):
                if not ry.desfazer_limpeza(p):
                    return jsonify({"erro": "Nada pra desfazer."}), 400
                ry.salvar_projeto(base_dir, p)
                return jsonify({"ok": True, "analise": p.get("analise"), "resultado": p.get("resultado")})
            feito = ry.aplicar_limpeza(p)
        except ry.RoteiroError as exc:
            return jsonify({"erro": str(exc)}), 400
        ry.salvar_projeto(base_dir, p)
        return jsonify({"ok": True, **feito, "analise": p.get("analise"), "resultado": p.get("resultado")})

    @app.route("/roteiros-yt/<pid>/cena/<int:cid>", methods=["POST"])
    def roteiro_yt_cena(pid: str, cid: int):
        """Guarda o link do YouTube e o trecho escolhidos pra uma cena."""
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        corpo = request.get_json(silent=True) or {}
        achou = False
        for lista in ((p.get("analise") or {}).get("cenas") or [], (p.get("resultado") or {}).get("cenas") or []):
            for c in lista:
                if c.get("id") == cid:
                    if "link" in corpo and str(corpo["link"] or "").strip() != (c.get("link") or ""):
                        c["google_errados"] = []  # outro vídeo: os momentos recusados não valem mais
                    for k in ("link", "link_inicio", "link_fim"):
                        if k in corpo:
                            c[k] = str(corpo[k] or "").strip()[:300]
                    achou = True
        if not achou:
            return jsonify({"erro": "Cena não encontrada."}), 404
        ry.salvar_projeto(base_dir, p)
        return jsonify({"ok": True})

    @app.route("/roteiros-yt/<pid>/achar-google", methods=["POST"])
    def roteiro_yt_achar_google(pid: str):
        """🔎🤖 Alternativa (v84_88): Claude busca no YouTube e escolhe os vídeos, a IA do Google assiste e acha o
        momento de cada cena → preenche link + início/fim. Em segundo plano (pode fechar a aba)."""
        import tarefas_bg
        import yt_google
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        motivo = yt_google.disponivel()
        if motivo:
            return jsonify({"erro": "🔎 IA do Google: " + motivo}), 400
        corpo = request.get_json(silent=True) or {}
        todas = _cenas_do(p)
        pedidas = corpo.get("cenas")
        if isinstance(pedidas, list) and pedidas:
            alvo = [c for c in todas if c.get("id") in {int(x) for x in pedidas if str(x).isdigit()}]
        else:
            alvo = [c for c in todas if not c.get("link")]
        if not alvo:
            return jsonify({"erro": "Nenhuma cena sem link (escolha uma cena)."}), 400
        rodando = [t for t in tarefas_bg.listar(5, tipo="achar_google", pagina=f"/roteiros-yt/{pid}") if t["status"] == "rodando"]
        if rodando:
            return jsonify({"ok": True, "tarefa": rodando[0]["id"], "ja_rodando": True})
        ids = [c["id"] for c in alvo]

        def _tarefa(t):
            estado: Dict[str, Any] = {str(i): {"estado": "na_fila"} for i in ids}
            achadas = 0
            for k, cid in enumerate(ids, 1):
                c = next((x for x in _cenas_do(ry.carregar_projeto(base_dir, pid)) if x.get("id") == cid), None)
                if c is None:
                    continue
                st = estado[str(cid)] = {"estado": "procurando", "log": []}
                t.progresso(f"cena {k}/{len(ids)}: {c.get('obra') or ''}")
                t.parcial(estado)

                def log(m, st=st):
                    st["log"] = (st["log"] + [m])[-12:]
                    t.parcial(estado)
                descr = _descr_cena(c)
                try:
                    r = yt_google.achar(descr, c.get("busca_youtube") or "", log=log, job=pid)
                except Exception as exc:  # noqa: BLE001
                    r = {"achou": False, "motivo": str(exc)[:200]}
                if r.get("achou"):
                    achadas += 1
                    dados = {"link": r["url"], "link_inicio": yt_google.mmss(r["inicio"]), "link_fim": yt_google.mmss(r["fim"])}
                    _atualizar_cena(base_dir, pid, cid, dict(dados, google_errados=[]))
                    st.update(estado="pronto", msg=f"✅ “{r['titulo'][:60]}” {dados['link_inicio']} → {dados['link_fim']}", **dados)
                else:
                    st.update(estado="nao_achou", msg="❌ " + str(r.get("motivo") or "não achei"))
                t.parcial(estado)
            return {"cenas": estado, "achadas": achadas, "total": len(ids)}
        tid = tarefas_bg.iniciar("achar_google", f"🔎🤖 Achar {len(ids)} cena(s) com Claude + Google", _tarefa,
                                 pagina=f"/roteiros-yt/{pid}")
        return jsonify({"ok": True, "tarefa": tid, "total": len(ids)})

    @app.route("/roteiros-yt/<pid>/cena/<int:cid>/olhar-de-novo", methods=["POST"])
    def roteiro_yt_olhar_de_novo(pid: str, cid: int):
        """🔁 A IA do Google errou o momento: pede, na mesma conversa, pra olhar o vídeo de novo — dizendo que o(s)
        momento(s) anterior(es) não tinham o que buscamos e reafirmando o que é. Em segundo plano."""
        import tarefas_bg
        import yt_google
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        c = next((x for x in _cenas_do(p) if x.get("id") == cid), None)
        if c is None:
            return jsonify({"erro": "Cena não encontrada."}), 404
        if not c.get("link"):
            return jsonify({"erro": "Essa cena ainda não tem link."}), 400
        motivo = yt_google.disponivel()
        if motivo:
            return jsonify({"erro": "🔎 IA do Google: " + motivo}), 400
        corpo = request.get_json(silent=True) or {}
        ini = yt_google.tempo_seg(corpo.get("inicio", c.get("link_inicio")))
        fim = yt_google.tempo_seg(corpo.get("fim", c.get("link_fim")))
        errados = [e for e in (c.get("google_errados") or []) if isinstance(e, dict)]
        if ini is not None:
            errados.append({"inicio": ini, "fim": fim if fim and fim > ini else ini + 5})
        if not errados:
            return jsonify({"erro": "Diga qual momento estava errado (início/fim)."}), 400
        link = c["link"]

        def _tarefa(t):
            st: Dict[str, Any] = {"estado": "procurando", "log": [f"🔁 pedindo pra IA do Google olhar de novo (sem {len(errados)} momento(s) errado(s))…"]}
            estado = {str(cid): st}
            t.parcial(estado)
            try:
                m = yt_google.momento_no_link(link, _descr_cena(c), evitar=errados)
            except Exception as exc:  # noqa: BLE001
                m, st["log"] = None, st["log"] + [str(exc)[:200]]
            if m and m.get("achou"):
                dados = {"link": link, "link_inicio": yt_google.mmss(m["inicio"]), "link_fim": yt_google.mmss(m["fim"])}
                _atualizar_cena(base_dir, pid, cid, dict(dados, google_errados=errados))
                st.update(estado="pronto", msg=f"✅ olhou de novo: {dados['link_inicio']} → {dados['link_fim']}"
                          + (f" — “{str(m.get('frase') or '')[:80]}”" if m.get("frase") else ""), **dados)
                return {"cenas": estado, "achadas": 1, "total": 1}
            _atualizar_cena(base_dir, pid, cid, {"google_errados": errados})
            st.update(estado="nao_achou", msg="❌ olhou de novo e não achou outro momento nesse vídeo — tente outro vídeo (🤖🔎 Achar) ou escolha à mão")
            return {"cenas": estado, "achadas": 0, "total": 1}
        tid = tarefas_bg.iniciar("achar_google", f"🔁 Olhar de novo: {c.get('obra') or 'cena'}", _tarefa, pagina=f"/roteiros-yt/{pid}")
        return jsonify({"ok": True, "tarefa": tid})

    @app.route("/roteiros-yt/<pid>/buscar-cena")
    def roteiro_yt_buscar_cena(pid: str):
        from youtube_clipper import YoutubeClipperError, buscar_videos_youtube
        termo = (request.args.get("termo") or "").strip()
        if not termo:
            return jsonify({"erro": "Termo vazio."}), 400
        try:
            return jsonify({"ok": True, "resultados": buscar_videos_youtube(termo, quantidade=8)})
        except YoutubeClipperError as exc:
            return jsonify({"erro": str(exc)}), 400

    @app.route("/roteiros-yt/<pid>/baixar/<tipo>")
    def roteiro_yt_baixar(pid: str, tipo: str):
        p = _proj(pid)
        if not p:
            return "Projeto não encontrado.", 404
        nome = (p.get("titulo") or "roteiro")[:40].strip().replace("/", "-") or "roteiro"
        if tipo == "json":
            corpo, mime, ext = json.dumps({k: p.get(k) for k in ("titulo", "url", "analise", "resultado")}, ensure_ascii=False, indent=2), "application/json", "json"
        elif tipo == "txt":
            corpo, mime, ext = ry.roteiro_para_voz(p, sem_marcadores=False), "text/plain; charset=utf-8", "txt"
        elif tipo == "descricao":
            res = p.get("resultado") or {}
            titulos = ([res["titulo_original"]] if res.get("titulo_original") else []) + list(res.get("titulos") or [])
            corpo = ("TÍTULOS\n" + "\n".join(titulos) + "\n\n" if titulos else "") + "DESCRIÇÃO\n" + ry.descricao_com_capitulos(res)
            mime, ext = "text/plain; charset=utf-8", "txt"
            nome += " - descricao"
        elif tipo == "transcricao":
            corpo, mime, ext = ry.texto_da_transcricao(p.get("transcricao") or {}), "text/plain; charset=utf-8", "txt"
        else:
            return "Tipo desconhecido.", 404
        return Response(corpo, mimetype=mime, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{__import__('urllib.parse').parse.quote(nome)}.{ext}"})

    @app.route("/roteiros-yt/<pid>/excluir", methods=["POST"])
    def roteiro_yt_excluir(pid: str):
        ry.excluir_projeto(base_dir, pid)
        return redirect(url_for("roteiros_yt_page"))

    @app.route("/roteiros-yt/modelos", methods=["POST"])
    def roteiros_yt_modelos():
        corpo = request.get_json(silent=True) or {}
        try:
            if corpo.get("excluir"):
                ry.excluir_modelo(base_dir, str(corpo["excluir"]))
                return jsonify({"ok": True, "modelos": ry.modelos(base_dir)})
            m = ry.salvar_modelo(base_dir, corpo.get("nome", ""), corpo.get("texto", ""), corpo.get("id", ""))
        except ry.RoteiroError as exc:
            return jsonify({"erro": str(exc)}), 400
        return jsonify({"ok": True, "modelo": m, "modelos": ry.modelos(base_dir)})
