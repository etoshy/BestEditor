"""
Rotas da aba 🎞️ Vídeos modelados (ver modelados.py). Registradas pelo app.py
com `registrar(app, ...)` — recebe as peças do app (jobs, salvar estado, pasta
do job) em vez de importar o app.py (evita import circular).
"""
from __future__ import annotations

import os
import threading
import time
import traceback
import uuid
from typing import Any, Callable, Dict, List, Optional

from flask import jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

import modelados as md

_TAREFAS: Dict[str, Dict[str, Any]] = {}
_TRAVA = threading.Lock()


def _tarefa(pid: str) -> Dict[str, Any]:
    return _TAREFAS.get(pid) or {"rodando": False, "fase": "", "log": [], "erro": None}


def _rodar(pid: str, fase: str, alvo: Callable[[Callable[[str], None], Callable[[], bool]], Any],
           extra: Optional[Dict[str, Any]] = None) -> bool:
    """Roda `alvo(log, cancelar)` numa thread (uma tarefa por projeto)."""
    def log(msg: str) -> None:
        t["log"] = (t["log"] + [time.strftime("%H:%M:%S ") + msg])[-300:]

    with _TRAVA:
        atual = _TAREFAS.get(pid)
        if atual and atual.get("rodando"):
            return False
        t = {"rodando": True, "fase": fase, "log": [], "erro": None, "cancelar": False, "inicio": time.time(), "log_fn": log}
        t.update(extra or {})
        _TAREFAS[pid] = t

    def cancelar() -> bool:
        return bool(t.get("cancelar"))

    def _thread():
        try:
            alvo(log, cancelar)
        except Exception as exc:  # noqa: BLE001
            t["erro"] = str(exc) if isinstance(exc, md.ModeladoError) or type(exc).__name__.startswith("GoogleFlow") \
                else f"{exc}\n{traceback.format_exc()[-1500:]}"
            log("✖ " + str(exc).splitlines()[0][:300])
        finally:
            t["rodando"] = False
    threading.Thread(target=_thread, daemon=True).start()
    return True


def registrar(app, base_dir: str, jobs: Dict[str, Dict[str, Any]], save_state: Callable[[str], None],
              job_dir: Callable[[str], str], load_site_config: Callable[[], Dict[str, Any]],
              waveform: Optional[Callable[[str, str], Any]] = None) -> None:

    def _vozes() -> List[Dict[str, Any]]:
        return md.vozes_efetivas()

    def _vozes_view() -> List[Dict[str, Any]]:
        import multivoz
        return [dict(v, resumo=multivoz.resumo(v), genero=v.get("genero") or "", idade=v.get("idade") or "",
                     herdado=v.get("herdado") or [], genero_rotulo=multivoz.rotulo_genero(v)) for v in md.vozes_efetivas()]

    def _perfis() -> List[str]:
        try:
            from tts.voice_generator import listar_perfis_de_voz
            return listar_perfis_de_voz()
        except Exception:  # noqa: BLE001
            return []

    @app.route("/modelados/vozes-padrao", methods=["POST"])
    def modelados_vozes_padrao():
        """Cadastra vozes Chatterbox Turbo com slug (embutida + uma por perfil de voz)."""
        try:
            criadas = md.criar_vozes_padrao(_perfis())
        except Exception as exc:  # noqa: BLE001
            return _erro(exc)
        return jsonify({"ok": True, "criadas": [v["slug"] for v in criadas]})

    def _cliente_flow(proj: Dict[str, Any], visivel: bool = True, compacta: bool = True):
        from googleflow.googleflow_client import GoogleFlowClient
        estilo = md.obter_estilo(proj["estilo_id"])
        return GoogleFlowClient(md.cfg_flow(load_site_config(), estilo, proj["formato"], visivel=visivel, compacta=compacta))

    def _erro(exc: Exception, cod: int = 400):
        return jsonify({"erro": str(exc)}), cod

    def _dados(pid: str) -> Dict[str, Any]:
        proj = md.carregar_projeto(base_dir, pid)
        estilo = md.obter_estilo(proj["estilo_id"])
        t = _tarefa(pid)
        cenas = []
        for c in proj.get("cenas") or []:
            cc = dict(c)
            cc["url_imagem"] = f"/modelados/{pid}/cena/{c['id']}/imagem?v={int(os.path.getmtime(c['imagem']))}" \
                if c.get("imagem") and os.path.isfile(c["imagem"]) else None
            cc["url_video"] = f"/modelados/{pid}/cena/{c['id']}/video?v={int(os.path.getmtime(c['video']))}" \
                if c.get("video") and os.path.isfile(c["video"]) else None
            cc["prompt_imagem_final"] = md.prompt_imagem_final(estilo, c, proj["formato"])
            cc["prompt_animacao_final"] = md.prompt_animacao_final(estilo, c)
            cc["duracao_clipe"] = md.duracao_clipe_para(estilo, float(c.get("duracao") or 4))
            cenas.append(cc)
        audio = proj.get("audio")
        return {"projeto": {k: v for k, v in proj.items() if k not in ("roteiro_bruto",)} | {"cenas": cenas},
                "personagens": md.personagens_do_roteiro(proj.get("roteiro") or {}) if proj.get("roteiro") else [],
                "estilo": estilo, "audio_url": f"/modelados/{pid}/audio.mp3?v={int(audio.get('gerado_em', 0))}" if audio else None,
                "tarefa": {k: t.get(k) for k in ("rodando", "fase", "log", "erro", "inicio", "flow", "abas", "cooldown_ate", "opcoes")}
                          | {"na_fila": len(t["fila"]) if t.get("fila") is not None else 0},
                "agora": time.time(),
                "editor_url": (url_for("edit_segments_page", job_id=proj["job_id"]) if proj.get("job_id") and proj["job_id"] in jobs else None),
                "vozes": _vozes_view()}

    # --------------------------------------------------------------- páginas
    @app.route("/modelados", methods=["GET"])
    def modelados_page():
        return render_template("modelados.html", projetos=md.listar_projetos(base_dir), estilos=md.listar_estilos(),
                               vozes=_vozes_view(), perfis=_perfis(), formatos=md.FORMATOS, duracoes=md.DURACOES_VIDEO + ("auto",),
                               resolucoes=md.RESOLUCOES_VIDEO, legendas=__import__("dp_legendas").ESTILOS)

    @app.route("/modelados/novo", methods=["POST"])
    def modelados_novo():
        f = request.form
        try:
            proj = md.criar_projeto(base_dir, f.get("nome", ""), f.get("estilo_id", "kamishibai"), f.get("tema", ""),
                                    f.get("duracao_alvo"), f.get("formato"), f.get("idioma"), f.get("instrucoes_extra", ""))
        except md.ModeladoError as exc:
            return render_template("modelados.html", projetos=md.listar_projetos(base_dir), estilos=md.listar_estilos(),
                                   vozes=_vozes_view(), formatos=md.FORMATOS, duracoes=md.DURACOES_VIDEO + ("auto",),
                                   resolucoes=md.RESOLUCOES_VIDEO, legendas=__import__("dp_legendas").ESTILOS,
                                   erro=str(exc), form=f), 400
        return redirect(url_for("modelado_detalhe", pid=proj["id"]))

    @app.route("/modelados/<pid>", methods=["GET"])
    def modelado_detalhe(pid: str):
        try:
            d = _dados(pid)
        except md.ModeladoError:
            return "Projeto não encontrado.", 404
        return render_template("modelado_detalhe.html", d=d, pid=pid)

    @app.route("/modelados/<pid>/dados", methods=["GET"])
    def modelado_dados(pid: str):
        try:
            return jsonify(_dados(pid))
        except md.ModeladoError as exc:
            return _erro(exc, 404)

    @app.route("/modelados/<pid>/excluir", methods=["POST"])
    def modelado_excluir(pid: str):
        md.excluir_projeto(base_dir, pid)
        return redirect(url_for("modelados_page"))

    @app.route("/modelados/<pid>/config", methods=["POST"])
    def modelado_config(pid: str):
        """Muda tema/duração/formato/idioma/estilo do projeto (antes do roteiro)."""
        corpo = request.get_json(silent=True) or {}
        try:
            proj = md.carregar_projeto(base_dir, pid)
            if corpo.get("estilo_id"):
                proj["estilo_id"] = md.obter_estilo(corpo["estilo_id"])["id"]
            for k in ("tema", "idioma", "instrucoes_extra", "nome"):
                if isinstance(corpo.get(k), str):
                    proj[k] = corpo[k].strip()[:4000]
            if corpo.get("formato") in md.FORMATOS:
                proj["formato"] = corpo["formato"]
            if corpo.get("duracao_alvo") not in (None, ""):
                proj["duracao_alvo"] = max(10, min(600, int(float(corpo["duracao_alvo"]))))
            md.salvar_projeto(base_dir, proj)
        except (md.ModeladoError, ValueError) as exc:
            return _erro(exc)
        return jsonify({"ok": True, **_dados(pid)})

    # --------------------------------------------------------------- 1) roteiro
    @app.route("/modelados/<pid>/prompt-roteiro", methods=["GET"])
    def modelado_prompt_roteiro(pid: str):
        try:
            proj = md.carregar_projeto(base_dir, pid)
            texto = md.prompt_roteiro(proj, md.obter_estilo(proj["estilo_id"]), _vozes())
        except md.ModeladoError as exc:
            return _erro(exc)
        return jsonify({"ok": True, "prompt": texto})

    @app.route("/modelados/<pid>/roteiro", methods=["POST"])
    def modelado_roteiro(pid: str):
        corpo = request.get_json(silent=True) or request.form
        try:
            md.aplicar_roteiro(base_dir, pid, corpo.get("json", ""), _vozes())
        except md.ModeladoError as exc:
            return _erro(exc)
        return jsonify({"ok": True, **_dados(pid)})

    @app.route("/modelados/<pid>/personagem", methods=["POST"])
    def modelado_personagem(pid: str):
        """Troca a voz de um personagem em TODAS as falas dele de uma vez."""
        corpo = request.get_json(silent=True) or {}
        try:
            r = md.definir_voz_do_personagem(base_dir, pid, str(corpo.get("nome") or ""), str(corpo.get("voz") or ""),
                                             {v["slug"] for v in md.vozes_efetivas()})
        except md.ModeladoError as exc:
            return _erro(exc)
        return jsonify({"ok": True, **r, **_dados(pid)})

    @app.route("/modelados/<pid>/fala/<int:fid>", methods=["POST"])
    def modelado_editar_fala(pid: str, fid: int):
        """Corrige uma fala (texto, voz, tags, emoção, pausa) antes/depois de gerar."""
        import multivoz
        corpo = request.get_json(silent=True) or {}
        try:
            proj = md.carregar_projeto(base_dir, pid)
            vozes = {v["slug"]: v for v in md.vozes_efetivas()}
            for f in (proj.get("roteiro") or {}).get("falas") or []:
                if f["id"] == fid:
                    if isinstance(corpo.get("texto"), str) and corpo["texto"].strip():
                        f["texto"] = corpo["texto"].strip()[:1200]
                    if corpo.get("voz"):
                        if corpo["voz"] not in vozes:
                            raise md.ModeladoError(f"Voz [{corpo['voz']}] não cadastrada.")
                        f["voz"] = corpo["voz"]
                    if isinstance(corpo.get("tags"), list):
                        permitidas = md._tags_turbo()
                        f["tags"] = [t for t in (str(x).strip().lower() for x in corpo["tags"]) if t in permitidas]
                    if corpo.get("emocao") not in (None, ""):
                        f["emocao"] = md._float(corpo["emocao"], 0.5, 0.0, 1.0)
                    if corpo.get("pausa_depois") not in (None, ""):
                        f["pausa_depois"] = md._float(corpo["pausa_depois"], 0.35, 0.0, 3.0)
                    if proj.get("audio"):
                        proj["audio_desatualizado"] = True  # o áudio pronto ainda tem a fala antiga
                    md.salvar_projeto(base_dir, proj)
                    return jsonify({"ok": True, **_dados(pid)})
            raise md.ModeladoError("Fala não encontrada.")
        except md.ModeladoError as exc:
            return _erro(exc)

    # --------------------------------------------------------------- 2) áudio
    @app.route("/modelados/<pid>/audio", methods=["POST"])
    def modelado_gerar_audio(pid: str):
        try:
            md.carregar_projeto(base_dir, pid)
        except md.ModeladoError as exc:
            return _erro(exc, 404)

        def alvo(log, _cancelar):
            md.gerar_audio(base_dir, pid, on_log=log)
        if not _rodar(pid, "Gerando o áudio", alvo):
            return _erro(md.ModeladoError("Já tem uma etapa rodando neste projeto."), 409)
        return jsonify({"ok": True})

    @app.route("/modelados/<pid>/audio.mp3", methods=["GET"])
    def modelado_audio(pid: str):
        caminho = md.pasta_projeto(base_dir, pid) / "audio_final.mp3"
        return send_file(str(caminho)) if caminho.exists() else ("Sem áudio.", 404)

    @app.route("/modelados/<pid>/<any('legenda.srt', 'legenda_personagens.srt'):nome>", methods=["GET"])
    def modelado_srt(pid: str, nome: str):
        caminho = md.pasta_projeto(base_dir, pid) / nome
        if not caminho.exists():
            return "Sem legenda.", 404
        return send_file(str(caminho), as_attachment=True, download_name=f"{pid}_{nome}", mimetype="application/x-subrip")

    # --------------------------------------------------------------- 3) ajuste
    @app.route("/modelados/<pid>/prompt-ajuste", methods=["GET"])
    def modelado_prompt_ajuste(pid: str):
        try:
            proj = md.carregar_projeto(base_dir, pid)
            return jsonify({"ok": True, "prompt": md.prompt_ajuste(proj, md.obter_estilo(proj["estilo_id"]))})
        except md.ModeladoError as exc:
            return _erro(exc)

    @app.route("/modelados/<pid>/ajuste", methods=["POST"])
    def modelado_ajuste(pid: str):
        corpo = request.get_json(silent=True) or request.form
        try:
            md.aplicar_ajuste(base_dir, pid, corpo.get("json", ""))
        except md.ModeladoError as exc:
            return _erro(exc)
        return jsonify({"ok": True, **_dados(pid)})

    @app.route("/modelados/<pid>/ajuste-auto", methods=["POST"])
    def modelado_ajuste_auto(pid: str):
        try:
            proj = md.carregar_projeto(base_dir, pid)
            cenas, avisos = md.distribuir_automatico(proj, md.obter_estilo(proj["estilo_id"]))
            md.aplicar_cenas(base_dir, pid, cenas, avisos)
        except md.ModeladoError as exc:
            return _erro(exc)
        return jsonify({"ok": True, **_dados(pid)})

    # --------------------------------------------------------------- 4/5) Flow
    def _indices(corpo) -> Optional[List[int]]:
        v = corpo.get("indices")
        if isinstance(v, list) and v:
            return [int(x) for x in v if str(x).lstrip("-").isdigit()]
        return None

    @app.route("/modelados/<pid>/<any('frames', 'animar', 'tudo'):etapa>", methods=["POST"])
    def modelado_flow(pid: str, etapa: str):
        """Gera no Flow. Se já tem uma geração do Flow rodando neste projeto, o
        pedido ENTRA NA FILA dela (não precisa esperar terminar)."""
        import collections
        corpo = request.get_json(silent=True) or {}
        try:
            proj = md.carregar_projeto(base_dir, pid)
        except md.ModeladoError as exc:
            return _erro(exc, 404)
        if not proj.get("cenas"):
            return _erro(md.ModeladoError("Defina as cenas antes (etapa 3: ajuste de tempos)."))
        indices, forcar = _indices(corpo), bool(corpo.get("forcar"))
        try:
            abas = max(1, min(3, int(corpo.get("abas") or md.ABAS_PADRAO)))
            cd_min = max(0.0, min(60.0, float(corpo.get("cooldown_min", md.COOLDOWN_PADRAO[0]))))
            cd_max = max(cd_min, min(120.0, float(corpo.get("cooldown_max", md.COOLDOWN_PADRAO[1]))))
        except (TypeError, ValueError):
            abas, (cd_min, cd_max) = md.ABAS_PADRAO, md.COOLDOWN_PADRAO
        visivel = corpo.get("visivel", True) not in (False, "false", "0", 0)
        compacta = corpo.get("compacta", True) not in (False, "false", "0", 0)

        t = _TAREFAS.get(pid)
        if t and t.get("rodando"):
            if not t.get("flow"):
                return _erro(md.ModeladoError("O áudio está sendo gerado agora — espere terminar pra mandar pro Flow."), 409)
            n = md.enfileirar(base_dir, pid, t["cliente"], t["fila"], etapa, indices, forcar, t["encadear"], t["log_fn"])
            t["log_fn"](f"➕ {n} pedido(s) entraram na fila do Flow (já rodando)." if n else "➕ Essa cena já estava na fila do Flow.")
            return jsonify({"ok": True, "na_fila": True, "adicionados": n, **_dados(pid)})

        fila: Any = collections.deque()
        encadear: set = set()
        cliente = _cliente_flow(proj, visivel, compacta)

        extra = {"flow": True, "fila": fila, "encadear": encadear, "cliente": cliente, "abas": {},
                 "opcoes": {"abas": abas, "cooldown": [cd_min, cd_max], "visivel": visivel, "compacta": compacta}}

        def alvo(log, cancelar):
            tt = _TAREFAS[pid]

            def on_estado(d: Dict[str, Any]) -> None:
                if d.get("aba"):
                    tt["abas"][str(d["aba"])] = {"estado": d.get("estado"), "desde": time.time()}
                if d.get("cooldown_ate"):
                    tt["cooldown_ate"] = d["cooldown_ate"]
            md.gerar_flow(base_dir, pid, cliente, etapa, indices, forcar, abas=abas, cooldown=(cd_min, cd_max),
                          on_log=log, cancelar=cancelar, on_estado=on_estado, fila=fila, encadear=encadear)
            log("✔ Fila do Flow concluída.")
        nomes = {"frames": "Gerando os frames no Google Flow", "animar": "Animando as cenas no Google Flow",
                 "tudo": "Frames + animação no Google Flow"}
        if not _rodar(pid, nomes[etapa], alvo, extra):
            return _erro(md.ModeladoError("Já tem uma etapa rodando neste projeto."), 409)
        return jsonify({"ok": True})

    @app.route("/modelados/flow-ao-vivo/<int:n>.jpg", methods=["GET"])
    def modelado_flow_ao_vivo(n: int):
        """Captura de tela (a cada ~3 s) da aba N do Flow enquanto ela trabalha."""
        try:
            from googleflow.googleflow_client import pasta_ao_vivo
            caminho = pasta_ao_vivo() / f"aba_{int(n)}.jpg"
        except Exception:  # noqa: BLE001
            return "", 404
        if not caminho.exists():
            return "", 404
        resp = send_file(str(caminho), mimetype="image/jpeg", max_age=0)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/modelados/<pid>/parar", methods=["POST"])
    def modelado_parar(pid: str):
        t = _TAREFAS.get(pid)
        if t and t.get("rodando"):
            t["cancelar"] = True
        return jsonify({"ok": True})

    @app.route("/modelados/<pid>/cena/<int:cid>", methods=["POST"])
    def modelado_editar_cena(pid: str, cid: int):
        corpo = request.get_json(silent=True) or {}
        try:
            md.editar_cena(base_dir, pid, cid, corpo.get("cena"), corpo.get("movimento"))
        except md.ModeladoError as exc:
            return _erro(exc)
        return jsonify({"ok": True, **_dados(pid)})

    @app.route("/modelados/<pid>/cena/<int:cid>/arquivo", methods=["POST"])
    def modelado_arquivo_cena(pid: str, cid: int):
        arq = request.files.get("arquivo")
        if not arq or not arq.filename:
            return _erro(md.ModeladoError("Escolha um arquivo."))
        ext = os.path.splitext(secure_filename(arq.filename))[1].lower()
        tipo = "imagem" if ext in (".png", ".jpg", ".jpeg", ".webp") else "video" if ext in (".mp4", ".mov", ".webm", ".mkv") else ""
        if not tipo:
            return _erro(md.ModeladoError("Use uma imagem (png/jpg/webp) ou um vídeo (mp4/mov/webm)."))
        tmp = os.path.join(str(md.pasta_projeto(base_dir, pid)), f"_upload_{uuid.uuid4().hex[:6]}{ext}")
        arq.save(tmp)
        try:
            md.usar_arquivo_na_cena(base_dir, pid, cid, tmp, tipo)
        except md.ModeladoError as exc:
            return _erro(exc)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return jsonify({"ok": True, **_dados(pid)})

    @app.route("/modelados/<pid>/cena/<int:cid>/<any('imagem', 'video'):tipo>", methods=["GET"])
    def modelado_midia_cena(pid: str, cid: int, tipo: str):
        try:
            proj = md.carregar_projeto(base_dir, pid)
        except md.ModeladoError:
            return "Projeto não encontrado.", 404
        for c in proj.get("cenas") or []:
            if c["id"] == cid and c.get(tipo) and os.path.isfile(c[tipo]):
                return send_file(c[tipo])
        return "Sem arquivo.", 404

    # --------------------------------------------------------------- 6) editor
    @app.route("/modelados/<pid>/editor", methods=["POST"])
    def modelado_para_editor(pid: str):
        job_id = uuid.uuid4().hex[:12]
        pasta = job_dir(job_id)
        try:
            pac = md.pacote_para_editor(base_dir, pid, pasta)
        except md.ModeladoError as exc:
            return _erro(exc)
        n = len(pac["pending_segments"])
        job = {
            "job_id": job_id, "audio_path": pac["audio_path"], "music_path": None, "music_volume": 0.18,
            "providers": ["flow"], "add_word_captions": False, "caption_style": {}, "status": "pronto_para_editar",
            "fase": "Pronto!", "created_at": time.time(), "cancel_requested": False,
            "original_filename": f"🎞️ {pac['nome']}", "interval_seconds": 4.0, "language": pac.get("idioma") or "pt", "language_origem": "falas",
            "extra_instructions": "", "usar_wikipedia_inteligente": False, "usar_buscadores_inteligente": False,
            "mix_midia": None, "orientation": pac["orientation"], "segments": pac["segments"],
            "total_duration": pac["total_duration"], "word_timestamps": [], "prompt": "",
            "pending_segments": pac["pending_segments"], "overlays": [], "cutaway_suggestions": [], "youtube_itens": [],
            "soundtrack_suggestion": None, "legendas": pac["legendas"], "cfg_overrides": {},
            "editor_defaults": {"transition_type": "none", "transition_duration": 0.3},
            "segment_previews": [{"index": i, "ok": True, "thumbnail_url": None, "result_url": None,
                                  "label": f"🎞️ cena {s.get('modelado_cena')}", "error": None, "video_preview_url": None,
                                  "provider": "flow", "original_provider": "flow"} for i, s in enumerate(pac["pending_segments"])],
            "preview_progress": {"current": n, "total": n}, "modelado_id": pid,
        }
        if waveform:
            try:
                wf = os.path.join(pasta, "waveform.png")
                waveform(pac["audio_path"], wf)
                job["waveform_path"] = wf
            except Exception:  # noqa: BLE001
                job["waveform_path"] = None
        jobs[job_id] = job
        save_state(job_id)
        proj = md.carregar_projeto(base_dir, pid)
        proj["job_id"] = job_id
        md.salvar_projeto(base_dir, proj)
        return jsonify({"ok": True, "job_id": job_id, "url": url_for("edit_segments_page", job_id=job_id),
                        "sem_video": pac["sem_video"]})

    # --------------------------------------------------------------- estilos
    @app.route("/modelados/estilos", methods=["POST"])
    def modelados_salvar_estilo():
        corpo = request.get_json(silent=True) or {}
        try:
            e = md.salvar_estilo(corpo, id_antigo=corpo.get("id_antigo") or None)
        except md.ModeladoError as exc:
            return _erro(exc)
        return jsonify({"ok": True, "estilo": e, "estilos": md.listar_estilos()})

    @app.route("/modelados/estilos/<eid>/excluir", methods=["POST"])
    def modelados_excluir_estilo(eid: str):
        md.apagar_estilo(eid)
        return jsonify({"ok": True, "estilos": md.listar_estilos()})
