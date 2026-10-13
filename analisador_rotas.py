"""📊 Analisador de canal + ⛏ Niche Miner (rotas)."""
from __future__ import annotations

import atexit
import os
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Optional

import analisador_canal as ac

# ------------------------------------------------------------------ ⛏ Niche Miner (roda como um app à parte)
NM_PORTA_PADRAO = 8843
_NM: Dict[str, Any] = {"proc": None, "porta": None, "erro": None, "log": None}
_NM_TRAVA = threading.Lock()


def _porta_aberta(porta: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, porta), timeout=0.5):
            return True
    except OSError:
        return False


def nm_porta() -> int:
    try:
        from site_config import load_site_config
        return int(load_site_config().get("niche_miner_porta") or NM_PORTA_PADRAO)
    except Exception:  # noqa: BLE001
        return NM_PORTA_PADRAO


def env_do_niche_miner() -> Dict[str, str]:
    """Ambiente do processo do Niche Miner SEM as variáveis do recarregador do Flask do site (debug=True):
    com WERKZEUG_SERVER_FD herdada, o Niche Miner tentava usar o soquete do site e fechava na hora
    ("OSError: [WinError 10038] ... não é um soquete")."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("WERKZEUG_")}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def nm_iniciar(popen=subprocess.Popen) -> Dict[str, Any]:
    """Sobe o Niche Miner (niche_miner/app.py) na porta dele, se ainda não estiver no ar."""
    porta = nm_porta()
    with _NM_TRAVA:
        if _porta_aberta(porta):
            return {"ok": True, "porta": porta, "ja_rodando": True}
        proc = _NM.get("proc")
        if proc is not None and proc.poll() is None:
            return {"ok": True, "porta": porta, "iniciando": True}
        pasta = ac.NICHE_MINER_DIR
        if not os.path.isfile(os.path.join(pasta, "app.py")):
            return {"ok": False, "erro": "A pasta niche_miner/ não está no site."}
        os.makedirs(os.path.join(pasta, "data"), exist_ok=True)
        log_path = os.path.join(pasta, "data", "niche_miner.log")
        env = env_do_niche_miner()
        try:
            logf = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
            _NM["proc"] = popen([sys.executable, "app.py", "--port", str(porta), "--host", "127.0.0.1"], cwd=pasta,
                                stdout=logf, stderr=subprocess.STDOUT, env=env)
            _NM.update(porta=porta, erro=None, log=log_path)
        except Exception as exc:  # noqa: BLE001
            _NM["erro"] = str(exc)[:300]
            return {"ok": False, "erro": _NM["erro"]}
    return {"ok": True, "porta": porta, "iniciando": True}


def nm_status() -> Dict[str, Any]:
    porta = nm_porta()
    proc = _NM.get("proc")
    morreu = proc is not None and proc.poll() is not None
    out = {"porta": porta, "no_ar": _porta_aberta(porta), "morreu": morreu, "erro": _NM.get("erro")}
    if morreu and _NM.get("log"):
        try:
            with open(_NM["log"], encoding="utf-8", errors="replace") as f:
                out["log"] = f.read()[-1500:]
        except OSError:
            pass
    return out


@atexit.register
def _nm_parar() -> None:
    proc = _NM.get("proc")
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ rotas
_RODANDO: Dict[str, threading.Thread] = {}


def registrar(app, base_dir: str) -> None:
    from flask import abort, jsonify, redirect, render_template, request, url_for

    def _ia_e_salva(a: Dict[str, Any]) -> None:
        """Depois da coleta: se a IA estiver ligada, já analisa."""
        import ia_servico as ia
        if not ia.ativo("canal"):
            return
        a["estado"] = "ia"
        a["etapa"] = "🤖 A IA está lendo números, miniaturas e transcrições…"
        ac.salvar(base_dir, a)
        r = ac.analisar_com_ia(a)
        if r:
            a["ia"] = r
            a["ia_quando"] = time.time()
            a.pop("ia_erro", None)
        else:
            a["ia_erro"] = "A IA não respondeu (" + (ia.motivo_desligado("canal") or "veja as últimas chamadas em 🤖 IA") + ")."
        a["estado"] = "pronto"
        a["etapa"] = "✅ Pronto."
        ac.salvar(base_dir, a)

    def _avisar_analise(aid: str) -> None:
        try:
            import notificacoes
            a = ac.carregar(base_dir, aid)
            nome = str(a.get("canal_nome") or a.get("nome") or a.get("url") or aid)[:60]
            erro = a.get("erro") if a.get("estado") != "pronto" else None
            notificacoes.avisar(("❌ " if erro else "✅ ") + f"Análise do canal {nome}" + (" — deu erro" if erro else " — pronta"),
                                str(erro or a.get("ia_erro") or "")[:400], f"/analisador-canal/{aid}", "erro" if erro else "ok", tipo="analisador")
        except Exception:  # noqa: BLE001
            pass

    def _rodar(aid: str) -> None:
        def _t():
            try:
                ac.executar(base_dir, aid, depois=_ia_e_salva)
            finally:
                _RODANDO.pop(aid, None)
                _avisar_analise(aid)
        t = threading.Thread(target=_t, daemon=True)
        _RODANDO[aid] = t
        t.start()

    @app.route("/analisador-canal")
    def analisador_canal_page():
        import ia_servico as ia
        return render_template("analisador_canal.html", analises=ac.listar(base_dir), erro=request.args.get("erro"),
                               ia_on=ia.ativo("canal"), ia_motivo=ia.motivo_desligado("canal"), n_padrao=ac.N_PADRAO)

    @app.route("/analisador-canal/novo", methods=["POST"])
    def analisador_canal_novo():
        try:
            a = ac.nova(base_dir, request.form.get("url") or "", n=int(request.form.get("n") or ac.N_PADRAO),
                        transcricoes=request.form.get("transcricoes", "on") == "on")
        except (ac.AnaliseError, ValueError) as exc:
            return redirect(url_for("analisador_canal_page", erro=str(exc)))
        _rodar(a["id"])
        return redirect(url_for("analisador_canal_detalhe", aid=a["id"]))

    def _ou_404(aid: str) -> Dict[str, Any]:
        try:
            return ac.carregar(base_dir, aid)
        except ac.AnaliseError:
            abort(404)

    @app.route("/analisador-canal/<aid>")
    def analisador_canal_detalhe(aid: str):
        import ia_servico as ia
        a = _ou_404(aid)
        a["rodando"] = aid in _RODANDO
        import dossies
        return render_template("analisador_canal_detalhe.html", a=a, fmt_num=ac.fmt_num, fmt_dur=ac.fmt_dur,
                               ia_on=ia.ativo("canal"), ia_motivo=ia.motivo_desligado("canal"), modelos=dossies.MODELOS)

    @app.route("/analisador-canal/<aid>/estado")
    def analisador_canal_estado(aid: str):
        a = _ou_404(aid)
        return jsonify({"estado": a.get("estado"), "etapa": a.get("etapa"), "log": (a.get("log") or [])[-12:],
                        "erro": a.get("erro"), "rodando": aid in _RODANDO, "tem_ia": bool(a.get("ia"))})

    @app.route("/analisador-canal/<aid>/ia", methods=["POST"])
    def analisador_canal_ia(aid: str):
        a = _ou_404(aid)
        if aid in _RODANDO:
            return jsonify({"erro": "Ainda está coletando — espere terminar."}), 409
        if a.get("estado") not in ("pronto",):
            return jsonify({"erro": "A coleta não terminou."}), 400
        import ia_servico as ia
        if not ia.ativo("canal"):
            return jsonify({"erro": "IA: " + (ia.motivo_desligado("canal") or "desligada") + " — use o prompt pra colar numa IA de chat."}), 400

        def _t():
            try:
                _ia_e_salva(ac.carregar(base_dir, aid))
            finally:
                _RODANDO.pop(aid, None)
                _avisar_analise(aid)
        t = threading.Thread(target=_t, daemon=True)
        _RODANDO[aid] = t
        t.start()
        return jsonify({"ok": True})

    @app.route("/analisador-canal/<aid>/prompt")
    def analisador_canal_prompt(aid: str):
        return jsonify({"prompt": ac.prompt_manual(_ou_404(aid))})

    @app.route("/analisador-canal/<aid>/colar", methods=["POST"])
    def analisador_canal_colar(aid: str):
        a = _ou_404(aid)
        try:
            a["ia"] = ac.validar_ia((request.get_json(silent=True) or {}).get("texto") or "", set((a.get("videos") or {}).keys()))
        except ac.AnaliseError as exc:
            return jsonify({"erro": str(exc)}), 400
        a["ia_quando"] = time.time()
        a.pop("ia_erro", None)
        ac.salvar(base_dir, a)
        return jsonify({"ok": True})

    @app.route("/analisador-canal/<aid>/refazer", methods=["POST"])
    def analisador_canal_refazer(aid: str):
        a = _ou_404(aid)
        if aid in _RODANDO:
            return redirect(url_for("analisador_canal_detalhe", aid=aid))
        a.update(estado="na_fila", erro=None, log=[], ia=None)
        ac.salvar(base_dir, a)
        _rodar(aid)
        return redirect(url_for("analisador_canal_detalhe", aid=aid))

    @app.route("/analisador-canal/<aid>/apagar", methods=["POST"])
    def analisador_canal_apagar(aid: str):
        _ou_404(aid)
        ac.apagar(base_dir, aid)
        return redirect(url_for("analisador_canal_page"))

    @app.route("/analisador-canal/<aid>/sugestao/<int:k>/projeto", methods=["POST"])
    def analisador_canal_projeto(aid: str, k: int):
        """Leva uma sugestão pra um 🕵️ Modelo de vídeo novo (o tema já vem com o gancho e a ideia de capa)."""
        a = _ou_404(aid)
        sug = ((a.get("ia") or {}).get("sugestoes") or [])
        if not 0 <= k < len(sug):
            abort(404)
        s = sug[k]
        import dossies
        modelo = request.form.get("modelo") or "misterios"
        if modelo not in dossies.MODELOS:
            modelo = "misterios"
        p = dossies.criar(base_dir, s["titulo"], modelo=modelo)
        p["roteiro_base"] = (f"Ideia tirada do 📊 Analisador de canal ({(a.get('canal') or {}).get('nome') or a.get('url')}).\n"
                             f"Título: {s['titulo']}\nTipo: {s.get('tipo', '')}\nPor quê: {s.get('por_que', '')}\n"
                             f"Gancho (1ª frase): {s.get('gancho', '')}\nIdeia de miniatura: {s.get('thumb', '')}\n"
                             "Adicione as fontes (matérias, documentos) antes de gerar o roteiro.")
        dossies.salvar(base_dir, p)
        return redirect(url_for("dossie_detalhe", pid=p["id"]))

    # ---------------------------------------------------------------- ⛏ Niche Miner
    @app.route("/niche-miner")
    def niche_miner_page():
        return render_template("niche_miner.html", porta=nm_porta())

    @app.route("/niche-miner/iniciar", methods=["POST"])
    def niche_miner_iniciar():
        return jsonify(nm_iniciar())

    @app.route("/niche-miner/status")
    def niche_miner_status():
        return jsonify(nm_status())
