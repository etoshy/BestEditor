"""
🎧 v84_399 — rotas do sound design, pra TODAS as ferramentas que lidam com áudio:

  • no Estúdio (vídeo longo): /job/<jid>/sound-design… — o plano fica no projeto e entra na montagem (antes do mux,
    com ducking da música);
  • em qualquer outro vídeo ou áudio do site (curtos, react, poker, anime, explicador, Gerador de voz, dublagem…) e
    em arquivos enviados: a página 🎧 Sound design (/sound-design) — escolhe o arquivo (os recentes do site aparecem
    sozinhos), transcreve (Whisper), a IA lê as emoções, busca os áudios no Pixabay e gera uma cópia com o som novo.

As duas usam o MESMO painel (templates/_sound_design.html) e a mesma API: <base>/estado · /salvar · /analisar ·
/buscar · /ouvir — o <base> muda (/job/<jid>/sound-design ou /sound-design/<pid>).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import sound_design as SD

PASTA_PROJETOS = "sound_design_projetos"
EXT_VIDEO = (".mp4", ".mov", ".mkv", ".webm")
EXT_AUDIO = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
_FORA_DA_LISTA = {"assets", "pixabay_sons", "myinstants_sons", PASTA_PROJETOS, "node_modules", ".git", "toolkit", "flow_dados", "_perfil",
                  "venv", ".venv", "__pycache__", "static", "templates", "modelos_tts", "models", "cache", "_cache"}


def pasta_pixabay(base_dir: str) -> str:
    return os.environ.get("CURTOS_PIXABAY_DIR") or os.path.join(base_dir, "pixabay_sons")


def pasta_memes(base_dir: str) -> str:
    return os.environ.get("BESTEDITOR_MYINSTANTS_DIR") or os.path.join(base_dir, "myinstants_sons")


def recentes(base_dir: str, limite: int = 60, dias: int = 45) -> List[Dict[str, Any]]:
    """Os vídeos/áudios que as ferramentas do site geraram por último (pra escolher sem procurar a pasta)."""
    agora, out = time.time(), []
    raiz = os.path.abspath(base_dir)
    for d, dirs, fs in os.walk(raiz):
        rel = os.path.relpath(d, raiz)
        nivel = 0 if rel == "." else rel.count(os.sep) + 1
        dirs[:] = [x for x in dirs if x not in _FORA_DA_LISTA and not x.startswith(".")] if nivel < 4 else []
        for f in fs:
            ext = os.path.splitext(f)[1].lower()
            if ext not in EXT_VIDEO + EXT_AUDIO or f.startswith(("_", ".")) or "sound_design" in f:
                continue
            cam = os.path.join(d, f)
            try:
                st = os.stat(cam)
            except OSError:
                continue
            if agora - st.st_mtime > dias * 86400 or st.st_size < 50 * 1024:
                continue
            out.append({"caminho": cam, "rel": os.path.relpath(cam, raiz).replace("\\", "/"), "mtime": st.st_mtime,
                        "mb": round(st.st_size / 1048576, 1), "video": ext in EXT_VIDEO})
    out.sort(key=lambda x: -x["mtime"])
    return out[:limite]


def _dur(caminho: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", caminho],
                           capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


# ------------------------------------------------------------------ projetos avulsos (qualquer arquivo)
def pasta_projeto(base_dir: str, pid: str = "") -> str:
    if pid and not re.fullmatch(r"[0-9a-f]{10}", pid):
        raise ValueError("Projeto inválido.")
    return os.path.join(base_dir, PASTA_PROJETOS, pid) if pid else os.path.join(base_dir, PASTA_PROJETOS)


def carregar_projeto(base_dir: str, pid: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(pasta_projeto(base_dir, pid), "projeto.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        raise ValueError("Projeto não encontrado.")


def salvar_projeto(base_dir: str, p: Dict[str, Any]) -> None:
    pasta = pasta_projeto(base_dir, p["id"])
    os.makedirs(pasta, exist_ok=True)
    tmp = os.path.join(pasta, "projeto.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(pasta, "projeto.json"))


def criar_projeto(base_dir: str, caminho: str, nome: str = "", copiar: bool = False) -> Dict[str, Any]:
    ext = os.path.splitext(caminho)[1].lower()
    if ext not in EXT_VIDEO + EXT_AUDIO or not os.path.isfile(caminho):
        raise ValueError("Escolha um vídeo (mp4, mov, mkv, webm) ou áudio (mp3, wav, m4a…).")
    pid = uuid.uuid4().hex[:10]
    pasta = pasta_projeto(base_dir, pid)
    os.makedirs(pasta, exist_ok=True)
    fonte = caminho
    if copiar:
        fonte = os.path.join(pasta, "original" + ext)
        shutil.move(caminho, fonte)
    p = {"id": pid, "nome": (nome or os.path.basename(caminho))[:120], "fonte": os.path.abspath(fonte),
         "video": ext in EXT_VIDEO, "criado": time.time(), "segments": [], "total_duration": _dur(fonte),
         "sound_design": SD.vazio(), "saida": ""}
    salvar_projeto(base_dir, p)
    return p


def listar_projetos(base_dir: str) -> List[Dict[str, Any]]:
    raiz = pasta_projeto(base_dir)
    out = []
    if os.path.isdir(raiz):
        for pid in os.listdir(raiz):
            try:
                p = carregar_projeto(base_dir, pid)
            except ValueError:
                continue
            out.append({"id": pid, "nome": p.get("nome"), "criado": p.get("criado") or 0, "video": p.get("video"),
                        "pronto": bool(p.get("saida") and os.path.isfile(p["saida"])),
                        "blocos": len((p.get("sound_design") or {}).get("blocos") or [])})
    out.sort(key=lambda x: -x["criado"])
    return out


def transcrever(p: Dict[str, Any], pasta: str, prog: Callable[[str], None] = lambda s: None,
                transcrever_fn: Optional[Callable[..., List[Dict[str, Any]]]] = None) -> List[Dict[str, Any]]:
    """Whisper na narração do arquivo → blocos com tempos (o que a IA lê pra achar as emoções)."""
    wav = os.path.join(pasta, "_audio_para_whisper.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", p["fonte"], "-vn", "-ac", "1", "-ar", "16000", wav],
                   check=True, timeout=3600)
    prog("📝 transcrevendo (Whisper)…")
    if transcrever_fn is None:
        from whisper_transcribe import transcribe_audio as transcrever_fn  # type: ignore
    segs = transcrever_fn(wav, model_size="base", language=None, device="auto")
    try:
        os.remove(wav)
    except OSError:
        pass
    return [{"start": float(s.get("start") or 0), "end": float(s.get("end") or 0), "text": str(s.get("text") or "").strip()}
            for s in segs or [] if str(s.get("text") or "").strip()]


def gerar_saida(base_dir: str, p: Dict[str, Any], prog: Callable[[str], None] = lambda s: None) -> str:
    """Aplica o plano no arquivo: o áudio do arquivo vira a "narração"; entram acentos + ambiente + música; o vídeo
    é copiado sem recodificar. Sai uma CÓPIA (o original fica)."""
    import dp_sons
    pasta = pasta_projeto(base_dir, p["id"])
    plano = SD.para_montar(p)
    if not plano:
        raise ValueError("Nada pra aplicar: leia as emoções e busque os áudios primeiro (ou ligue alguma camada).")
    trab = os.path.join(pasta, "_trabalho")
    os.makedirs(trab, exist_ok=True)
    base_wav = os.path.join(trab, "audio.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", p["fonte"], "-vn", "-ar", "48000", "-ac", "2", base_wav],
                   check=True, timeout=3600)
    prog("💥 acentos…")
    ev = SD.eventos_acentos(plano)
    audio = dp_sons.mixar(base_wav, ev, os.path.join(trab, "com_acentos.wav"), volume_sfx=1.0, reverb=bool(plano.get("mix"))) \
        if ev else base_wav
    prog("🌫🎵 ambiente e música…")
    audio = SD.aplicar(audio, plano, os.path.join(trab, "com_camadas.wav"))
    nome = re.sub(r"[^\w.-]+", "_", os.path.splitext(os.path.basename(p["fonte"]))[0])[:60]
    if p.get("video"):
        saida = os.path.join(pasta, f"{nome}_sound_design.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", p["fonte"], "-i", audio, "-map", "0:v:0", "-map", "1:a:0",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", saida], check=True, timeout=3600)
    else:
        saida = os.path.join(pasta, f"{nome}_sound_design.m4a")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", audio, "-c:a", "aac", "-b:a", "192k", saida], check=True, timeout=3600)
    shutil.rmtree(trab, ignore_errors=True)
    return saida


def _url_local(url: str) -> str:
    """Só caminhos do próprio site (/job/…/final.mp4) — nunca um link de fora."""
    from urllib.parse import urlsplit
    u = urlsplit(str(url or "").strip())
    if u.netloc and u.netloc.split(":")[0] not in ("127.0.0.1", "localhost"):
        return ""
    caminho = u.path + (("?" + u.query) if u.query else "")
    return caminho if caminho.startswith("/") and not caminho.startswith("//") else ""


def criar_de_url(app, base_dir: str, url: str) -> Dict[str, Any]:
    """Pega o vídeo/áudio pela própria rota do site que o mostra (serve pra QUALQUER ferramenta, sem saber a pasta)."""
    from urllib.parse import unquote
    caminho = _url_local(url)
    if not caminho:
        raise ValueError("Esse arquivo não é do site.")
    with app.test_client() as c:
        r = c.get(caminho, follow_redirects=True)
        tipo = (r.headers.get("Content-Type") or "").split(";")[0]
        if r.status_code != 200 or not tipo.startswith(("video/", "audio/")):
            raise ValueError(f"Não consegui pegar o arquivo ({r.status_code} {tipo or 'sem tipo'}).")
        nome = os.path.basename(unquote(caminho.split("?")[0])) or "arquivo"
        ext = os.path.splitext(nome)[1].lower()
        if ext not in EXT_VIDEO + EXT_AUDIO:
            ext = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov", "audio/mpeg": ".mp3", "audio/wav": ".wav",
                   "audio/x-wav": ".wav", "audio/mp4": ".m4a", "audio/aac": ".aac", "audio/ogg": ".ogg"}.get(tipo, ".mp4")
            nome = os.path.splitext(nome)[0] + ext
        pasta_tmp = pasta_projeto(base_dir)
        os.makedirs(pasta_tmp, exist_ok=True)
        tmp = os.path.join(pasta_tmp, "_url_" + uuid.uuid4().hex[:6] + ext)
        with open(tmp, "wb") as f:
            for parte in r.response:
                f.write(parte)
        r.close()
    return criar_projeto(base_dir, tmp, nome, copiar=True)


# ------------------------------------------------------------------ rotas
def registrar(app, base_dir: str, jobs: Dict[str, Any], salvar_job: Callable[[str], None], pasta_do_job: Callable[[str], str]) -> None:
    from flask import abort, jsonify, redirect, render_template, request, send_file, url_for
    import tarefas_bg

    # o "alvo" é um projeto do Estúdio (job) ou um projeto avulso — mesma API
    def _alvo(tipo: str, ident: str) -> Tuple[Dict[str, Any], Callable[[], None], str, str]:
        if tipo == "job":
            job = jobs.get(ident)
            if not job:
                raise ValueError("Projeto não encontrado.")
            return job, (lambda: salvar_job(ident)), pasta_do_job(ident), f"/job/{ident}/sound-design"
        p = carregar_projeto(base_dir, ident)
        return p, (lambda: salvar_projeto(base_dir, p)), pasta_projeto(base_dir, ident), f"/sound-design/{ident}"

    def _estado_json(tipo: str, ident: str):
        alvo, _s, _pasta, base = _alvo(tipo, ident)
        r = SD.resumo(alvo)
        t = tarefas_bg.pegar(str((alvo.get("sound_design") or {}).get("tarefa") or "")) or {}
        r["tarefa"] = {k: t.get(k) for k in ("status", "progresso", "erro", "titulo")} if t else None
        r["base"] = base
        r["tem_texto"] = bool(SD.texto_com_tempos(alvo).strip())
        if tipo == "proj":
            r["saida"] = f"{base}/saida" if alvo.get("saida") and os.path.isfile(alvo["saida"]) else ""
            r["video"] = bool(alvo.get("video"))
        return jsonify(r)

    def _tarefa(tipo: str, ident: str, titulo: str, fn: Callable[[Dict[str, Any], Callable[[str], None], str], Any]):
        alvo, salvar, pasta, base = _alvo(tipo, ident)
        sd = SD.estado(alvo)
        t_ant = tarefas_bg.pegar(str(sd.get("tarefa") or "")) or {}
        if t_ant.get("status") == "rodando":
            raise ValueError("Já tem uma etapa rodando — espere terminar.")

        def rodar(t):
            alvo2, salvar2, pasta2, _b = _alvo(tipo, ident)  # relê (o painel pode ter salvo no meio)

            def prog(msg: str) -> None:
                t.progresso(msg)
                sd2 = SD.estado(alvo2)
                sd2["log"] = (sd2.get("log") or [])[-30:] + [f"{time.strftime('%H:%M:%S')} {msg}"]
            out = fn(alvo2, prog, pasta2)
            salvar2()
            return out
        tid = tarefas_bg.iniciar("sound_design", titulo, rodar, pagina=request.headers.get("X-Pagina") or "")
        sd["tarefa"] = tid
        salvar()
        return tid

    def _api(tipo: str):
        sufixo = "job" if tipo == "job" else "proj"
        pref = "/job/<ident>/sound-design" if tipo == "job" else "/sound-design/<ident>"

        def estado_rota(ident: str):
            try:
                return _estado_json(sufixo, ident)
            except ValueError as exc:
                return jsonify({"erro": str(exc)}), 404

        def salvar_rota(ident: str):
            try:
                alvo, salvar, _p, _b = _alvo(sufixo, ident)
                SD.salvar_plano(alvo, request.get_json(silent=True) or {})
                salvar()
                return _estado_json(sufixo, ident)
            except ValueError as exc:
                return jsonify({"erro": str(exc)}), 400

        def analisar_rota(ident: str):
            def fn(alvo, prog, pasta):
                prog("🤖 a IA está lendo as emoções da narração…")
                plano = SD.analisar(alvo, job_id=ident if sufixo == "job" else "")
                sd = SD.estado(alvo)
                sd["blocos"], sd["momentos"] = plano["blocos"], plano["momentos"]
                prog(f"✅ {len(plano['blocos'])} bloco(s) de emoção e {len(plano['momentos'])} momento(s)-chave")
                return len(plano["blocos"])
            try:
                return jsonify({"ok": True, "tarefa": _tarefa(sufixo, ident, "🎧 Sound design: emoções", fn)})
            except ValueError as exc:
                return jsonify({"erro": str(exc)}), 400

        def buscar_rota(ident: str):
            def fn(alvo, prog, pasta):
                r = SD.buscar_audios(SD.estado(alvo), pasta_pixabay(base_dir), pasta, prog, pasta_memes=pasta_memes(base_dir))
                prog(f"✅ {r['novos']} áudio(s) novos" + (f" · sem resultado: {', '.join(r['faltando'])}" if r["faltando"] else ""))
                return r
            try:
                alvo, *_ = _alvo(sufixo, ident)
                if not SD.estado(alvo)["blocos"]:
                    raise ValueError("Leia as emoções primeiro (🤖).")
                return jsonify({"ok": True, "tarefa": _tarefa(sufixo, ident, "🎧 Sound design: áudios do Pixabay", fn)})
            except ValueError as exc:
                return jsonify({"erro": str(exc)}), 400

        def trocar_rota(ident: str):  # 🔁 não gostei desse áudio: o próximo 🔊 escolhe outro
            try:
                alvo, salvar, _p, _b = _alvo(sufixo, ident)
                SD.trocar(SD.estado(alvo), str((request.get_json(silent=True) or {}).get("chave") or ""))
                salvar()
                return _estado_json(sufixo, ident)
            except ValueError as exc:
                return jsonify({"erro": str(exc)}), 400

        def ouvir_rota(ident: str):
            try:
                alvo, *_ = _alvo(sufixo, ident)
            except ValueError:
                abort(404)
            a = (SD.estado(alvo).get("audios") or {}).get(request.args.get("chave") or "") or {}
            if not a.get("arquivo") or not os.path.isfile(a["arquivo"]):
                abort(404)
            return send_file(a["arquivo"], conditional=True)

        for nome, fn_, met in (("estado", estado_rota, ["GET"]), ("salvar", salvar_rota, ["POST"]),
                               ("analisar", analisar_rota, ["POST"]), ("buscar", buscar_rota, ["POST"]),
                               ("ouvir", ouvir_rota, ["GET"]), ("trocar", trocar_rota, ["POST"])):
            app.add_url_rule(f"{pref}/{nome}", f"sd_{sufixo}_{nome}", fn_, methods=met)

    _api("job")
    _api("proj")

    # ---------------------------------------------------------------- 🎧 página universal
    @app.route("/sound-design")
    def sd_pagina():
        return render_template("sound_design.html", projetos=listar_projetos(base_dir), recentes=recentes(base_dir),
                               p=None, preencher=request.args.get("arquivo") or "", url=_url_local(request.args.get("url") or ""))

    @app.route("/sound-design/novo", methods=["POST"])
    def sd_novo():
        try:
            f = request.files.get("arquivo")
            if f and f.filename:
                from werkzeug.utils import secure_filename
                pasta_tmp = pasta_projeto(base_dir)
                os.makedirs(pasta_tmp, exist_ok=True)
                tmp = os.path.join(pasta_tmp, "_envio_" + uuid.uuid4().hex[:6] + "_" + secure_filename(f.filename))
                f.save(tmp)
                p = criar_projeto(base_dir, tmp, f.filename, copiar=True)
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            elif request.form.get("url"):  # 🎧 o botão que aparece em qualquer vídeo/áudio do site: busca o arquivo na própria rota
                p = criar_de_url(app, base_dir, str(request.form["url"]))
            else:
                cam = os.path.abspath(str(request.form.get("caminho") or ""))
                if not cam.startswith(os.path.abspath(base_dir) + os.sep):
                    raise ValueError("Escolha um arquivo da lista (ou envie um).")
                p = criar_projeto(base_dir, cam)
        except ValueError as exc:
            return render_template("sound_design.html", projetos=listar_projetos(base_dir), recentes=recentes(base_dir),
                                   p=None, erro=str(exc), preencher="")
        return redirect(url_for("sd_projeto", pid=p["id"]))

    @app.route("/sound-design/<pid>")
    def sd_projeto(pid: str):
        try:
            p = carregar_projeto(base_dir, pid)
        except ValueError:
            abort(404)
        return render_template("sound_design.html", p=p, projetos=[], recentes=[], preencher="")

    @app.route("/sound-design/<pid>/transcrever", methods=["POST"])
    def sd_transcrever(pid: str):
        def fn(alvo, prog, pasta):
            alvo["segments"] = transcrever(alvo, pasta, prog)
            prog(f"✅ {len(alvo['segments'])} frase(s) transcritas")
            return len(alvo["segments"])
        try:
            return jsonify({"ok": True, "tarefa": _tarefa("proj", pid, "🎧 Sound design: transcrição", fn)})
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400

    @app.route("/sound-design/<pid>/aplicar", methods=["POST"])
    def sd_aplicar(pid: str):
        def fn(alvo, prog, pasta):
            alvo["saida"] = gerar_saida(base_dir, alvo, prog)
            prog("✅ pronto — baixe a cópia com o som novo")
            return alvo["saida"]
        try:
            return jsonify({"ok": True, "tarefa": _tarefa("proj", pid, "🎧 Sound design: gerando a cópia", fn)})
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400

    @app.route("/sound-design/<pid>/saida")
    def sd_saida(pid: str):
        try:
            p = carregar_projeto(base_dir, pid)
        except ValueError:
            abort(404)
        if not p.get("saida") or not os.path.isfile(p["saida"]):
            abort(404)
        return send_file(p["saida"], conditional=True, as_attachment=bool(request.args.get("baixar")),
                         download_name=os.path.basename(p["saida"]))

    @app.route("/sound-design/<pid>/excluir", methods=["POST"])
    def sd_excluir(pid: str):
        try:
            shutil.rmtree(pasta_projeto(base_dir, pid), ignore_errors=True)
        except ValueError:
            pass
        return redirect(url_for("sd_pagina"))
