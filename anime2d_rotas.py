"""
🎞 anime2d_rotas.py — as rotas do modelo "Animação 2D" (aba 🕵️ Modelos de vídeo, v84_237).

`registrar(app, base_dir, criar_job, pasta_job, tts, limpar_tts)`:
  criar_job(job_id, job) põe o projeto pronto no Estúdio; tts(motor, texto, saida, **kw) gera um áudio; limpar_tts(texto,
  motor) tira o que o motor leria em voz alta.
"""
from __future__ import annotations

import io
import json
import os
import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from flask import abort, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

import anime2d as A
import anime2d_zip as AZ
import anime2d_manga as AM

TAREFAS: Dict[str, Dict[str, Any]] = {}
_ULTIMO: Dict[str, float] = {}


def _avisar(titulo: str, msg: str, link: str, nivel: str = "ok") -> None:
    try:
        import notificacoes
        notificacoes.avisar(titulo, msg, link, nivel, tipo="anime2d")
    except Exception:  # noqa: BLE001
        pass


def registrar(app, base_dir: str, criar_job: Callable[[str, Dict[str, Any]], None], pasta_job: Callable[[str], str],
              tts: Optional[Callable[..., Any]] = None, limpar_tts: Optional[Callable[[str, str], str]] = None) -> None:

    def _p(pid: str) -> Dict[str, Any]:
        try:
            return A.carregar(pid, base_dir)
        except A.AnimeErro:
            abort(404)

    def _ok(**kw: Any):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: str, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _rodar(pid: str, oque: str, rotulo: str, fn: Callable[[], Any]):
        t = TAREFAS.get(pid)
        if t and not t.get("fim"):
            return _erro(f"Espere terminar: {t.get('rotulo')}", 409)
        TAREFAS[pid] = {"oque": oque, "rotulo": rotulo, "inicio": time.time(), "fim": None, "erro": None, "msg": ""}

        def corpo():
            try:
                r = fn()
                TAREFAS[pid].update(msg=r if isinstance(r, str) else "")
                _avisar(f"✅ Animação 2D — {rotulo}", "", f"/anime2d/{pid}")
            except Exception as exc:  # noqa: BLE001
                TAREFAS[pid]["erro"] = str(exc)[:500]
                _avisar(f"❌ Animação 2D — {rotulo}", str(exc)[:400], f"/anime2d/{pid}", "erro")
            finally:
                TAREFAS[pid]["fim"] = time.time()

        threading.Thread(target=corpo, daemon=True).start()
        return None

    def _prog(pid: str) -> Callable[[str], None]:
        return lambda m: TAREFAS[pid].update(progresso=str(m)[:200])

    @app.context_processor
    def _anime2d_no_template():
        return {"anime2d_lista": lambda: A.listar(base_dir), "anime2d_estilos": A.ESTILOS}

    # ------------------------------------------------------------------ criar / página / estado
    @app.route("/anime2d/novo", methods=["POST"])
    def anime2d_novo():
        p = A.criar(request.form.get("titulo") or "", request.form.get("premissa") or "", request.form.get("estilo") or "anime",
                    base_dir, proporcao=request.form.get("proporcao") if request.form.get("proporcao") in A.PROPORCOES else "16:9",
                    duracao_alvo=request.form.get("duracao") or 0)
        au = request.files.get("audio")
        if au and au.filename:
            try:
                A.guardar_audio(p, au.filename, au.read(), base_dir)
            except A.AnimeErro:
                pass
        for f in request.files.getlist("referencias"):
            if f and f.filename:
                try:
                    A.guardar_referencia(p, f.filename, f.read(), request.form.get("tipo_ref") or "personagem",
                                         os.path.splitext(f.filename)[0].replace("_", " ").replace("-", " "), "", base_dir)
                except A.AnimeErro:
                    continue
        A.salvar(p, base_dir)
        zf = request.files.get("zip")
        if zf and zf.filename:  # 📦 um zip com tudo
            try:
                rel = AZ.importar(p["id"], zf.read(), base_dir, novo=not (request.form.get("titulo") or "").strip())
                _avisar("📦 Zip importado", rel["resumo"] + (f" — {len(rel['avisos'])} aviso(s)" if rel["avisos"] else ""),
                        f"/anime2d/{p['id']}", "ok" if not rel["avisos"] else "aviso")
            except A.AnimeErro as exc:
                _avisar("📦 Zip não entrou", str(exc), f"/anime2d/{p['id']}", "erro")
            p = A.carregar(p["id"], base_dir)
        if A.audio_ok(p, base_dir) and not (p.get("audio") or {}).get("transcricao"):
            pid_ = p["id"]
            _rodar(pid_, "transcrever", "🎙 Transcrever o áudio", lambda: f"{A.transcrever_audio(pid_, base_dir)} trecho(s)")
        return redirect(url_for("anime2d_pagina", pid=p["id"]))

    @app.route("/anime2d/<pid>/audio", methods=["POST"])
    def anime2d_audio(pid: str):
        """🎧 o áudio pronto do episódio (ou {"tirar": true}); {"transcricao": "..."} guarda a transcrição corrigida."""
        f = request.files.get("arquivo")
        c = request.get_json(silent=True) or {}
        with A._TRAVA:
            p = _p(pid)
            if f and f.filename:
                try:
                    A.guardar_audio(p, f.filename, f.read(), base_dir)
                except A.AnimeErro as exc:
                    return _erro(str(exc))
                A.salvar(p, base_dir)
                return _rodar(pid, "transcrever", "🎙 Transcrever o áudio", lambda: f"{A.transcrever_audio(pid, base_dir)} trecho(s)") or _ok()
            if c.get("tirar"):
                p["audio"] = {}
                try:
                    os.remove(os.path.join(A.pasta(pid, base_dir), "audio.wav"))
                except OSError:
                    pass
            elif "transcricao" in c:
                n = A.definir_transcricao_audio(p, str(c["transcricao"] or ""))
                A.salvar(p, base_dir)
                return _ok(linhas=n)
            elif c.get("transcrever"):
                A.salvar(p, base_dir)
                return _rodar(pid, "transcrever", "🎙 Transcrever o áudio", lambda: f"{A.transcrever_audio(pid, base_dir)} trecho(s)") or _ok()
            A.salvar(p, base_dir)
        return _ok()

    @app.route("/anime2d/<pid>/audio.wav")
    def anime2d_audio_arq(pid: str):
        p = _p(pid)
        if not A.audio_ok(p, base_dir):
            abort(404)
        return send_file(os.path.join(A.pasta(pid, base_dir), p["audio"]["arquivo"]), max_age=0)

    @app.route("/anime2d/<pid>")
    def anime2d_pagina(pid: str):
        p = _p(pid)
        return render_template("anime2d_detalhe.html", p=A.para_tela(p, base_dir), estilos=A.ESTILOS, poses=A.POSES,
                               posicoes=list(A.POSICOES), cameras=list(A.CAMERAS), tipos_ref=A.TIPOS_REF,
                               tipos_momento=list(A.TIPOS_MOMENTO), exemplo=A.EXEMPLO_INSTRUCOES,
                               guia_zip=AZ.GUIA_ZIP, ex_zip={"projeto.json": AZ.EXEMPLO_PROJETO,
                                                             "personagens/Kenta/personagem.json": AZ.EXEMPLO_PERSONAGEM,
                                                             "locais/Sala/local.json": AZ.EXEMPLO_LOCAL,
                                                             "itens/Vaso quebrado/item.json": AZ.EXEMPLO_ITEM,
                                                             "cenas.json": AZ.EXEMPLO_CENAS,
                                                             "(valores aceitos nas cenas)": AZ.EXEMPLO_CENAS_NOTAS})

    @app.route("/anime2d/<pid>/estado")
    def anime2d_estado(pid: str):
        _p(pid)
        avisos: List[str] = []
        if time.time() - _ULTIMO.get(pid, 0) > 3:
            _ULTIMO[pid] = time.time()
            try:
                avisos = A.acompanhar(pid, base_dir).get("avisos") or []
            except Exception as exc:  # noqa: BLE001
                avisos = [str(exc)[:200]]
        return jsonify(dict(A.para_tela(_p(pid), base_dir), tarefa=TAREFAS.get(pid), avisos=avisos))

    @app.route("/anime2d/<pid>/excluir", methods=["POST"])
    def anime2d_excluir(pid: str):
        _p(pid)
        A.excluir(pid, base_dir)
        return redirect("/modelos-video#anime2d")

    @app.route("/anime2d/<pid>/dados", methods=["POST"])
    def anime2d_dados(pid: str):
        c = request.get_json(silent=True) or {}
        with A._TRAVA:
            p = _p(pid)
            for k, lim in (("titulo", 200), ("premissa", 6000), ("estilo_extra", 300), ("idioma", 60)):
                if k in c:
                    p[k] = str(c[k] or "").strip()[:lim]
            if c.get("estilo") in A.ESTILOS:
                p["estilo"] = c["estilo"]
            if c.get("proporcao") in A.PROPORCOES:
                p["proporcao"] = c["proporcao"]
            if "duracao_alvo" in c:
                v = A.R.segundos(c["duracao_alvo"]) or 0.0
                p["duracao_alvo"] = 0.0 if v <= 0 else max(0.5, min(40.0, v))
            if isinstance(c.get("narrador"), dict):
                p["narrador"] = {"ativo": bool(c["narrador"].get("ativo")), "voz": str(c["narrador"].get("voz") or "")[:40]}
            if "legendas" in c:
                p["legendas"] = bool(c["legendas"])
            if "paralaxe" in c:
                p["paralaxe"] = bool(c["paralaxe"])
            if c.get("motor_perfil") in A.MOTORES_PERFIL:
                p["motor_perfil"] = c["motor_perfil"]
            A.salvar(p, base_dir)
        return _ok()

    # ------------------------------------------------------------------ 📎 referências
    # ------------------------------------------------------------------ 📖 mangá → anime
    @app.route("/anime2d/<pid>/manga/paginas", methods=["POST"])
    def anime2d_manga_paginas(pid: str):
        arqs = []
        for f in request.files.getlist("paginas"):
            if not f or not f.filename:
                continue
            dados = f.read()
            if f.filename.lower().endswith(".zip"):  # as páginas num zip
                import zipfile
                try:
                    z = zipfile.ZipFile(io.BytesIO(dados))
                except zipfile.BadZipFile:
                    return _erro(f"{f.filename} não é um zip válido.")
                arqs += [(i.filename, z.read(i)) for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(AM.EXT_PAG)
                         and "__MACOSX" not in i.filename and i.file_size < 40 * 1024 * 1024][:AM.MAX_PAGINAS]
            else:
                arqs.append((f.filename, dados))
        if not arqs:
            return _erro("Escolha as páginas (imagens ou um .zip com elas).")
        with A._TRAVA:
            p = _p(pid)
            n = AM.guardar_paginas(p, arqs, base_dir, substituir=request.form.get("substituir") == "1")
            A.salvar(p, base_dir)
        return _ok(n=n, total=len(A.paginas_manga(p)))

    @app.route("/anime2d/<pid>/manga/video", methods=["POST"])
    def anime2d_manga_video(pid: str):
        """🎬 Um vídeo de referência: tira os quadros-chave (cortes) e, se pedir, usa o áudio dele (e transcreve)."""
        _p(pid)
        f = request.files.get("video")
        if not f or not f.filename:
            return _erro("Escolha o vídeo.")
        nome, dados = f.filename, f.read()
        if len(dados) > 1024 * 1024 * 1024:
            return _erro("O vídeo passa de 1 GB.")
        usar = request.form.get("usar_audio", "1") == "1"

        def tarefa() -> str:
            with A._TRAVA:
                p = A.carregar(pid, base_dir)
                r = AM.guardar_video(p, nome, dados, base_dir, usar)
                A.salvar(p, base_dir)
            if r["audio"]:
                TAREFAS[pid].update(progresso="🎙 transcrevendo o áudio…")
                A.transcrever_audio(pid, base_dir)
            return f"{r['quadros']} quadro(s)" + (" + o áudio transcrito" if r["audio"] else "")
        return _rodar(pid, "video", "🎬 Lendo o vídeo de referência", tarefa) or _ok()

    @app.route("/anime2d/<pid>/manga/<int:n>.jpg")
    def anime2d_manga_pagina(pid: str, n: int):
        cam = A.arquivo_pagina(_p(pid), n, base_dir)
        return send_file(cam, max_age=0) if cam else ("", 404)

    @app.route("/anime2d/<pid>/manga/recorte", methods=["POST"])
    def anime2d_manga_recorte(pid: str):
        c = request.get_json(silent=True) or {}
        with A._TRAVA:
            p = _p(pid)
            try:
                ref = AM.recortar(p, int(c.get("pagina") or 0), c.get("caixa"), c.get("tipo") if c.get("tipo") in A.TIPOS_REF else "personagem",
                                  str(c.get("nome") or "")[:80], base_dir)
            except (A.AnimeErro, ValueError) as exc:
                return _erro(str(exc))
            if not ref:
                return _erro("Recorte inválido (escolha uma área maior).")
            A.salvar(p, base_dir)
        return _ok(ref=ref)

    @app.route("/anime2d/<pid>/adaptacao.json")
    def anime2d_adaptacao(pid: str):
        p = _p(pid)
        nome = re.sub(r"[^\w\- ]+", "", p["titulo"]).strip().replace(" ", "_")[:60] or pid
        return (json.dumps(AM.json_adaptacao(p), ensure_ascii=False, indent=2), 200,
                {"Content-Type": "application/json; charset=utf-8",
                 "Content-Disposition": f'attachment; filename="adaptacao_{nome}.json"'})

    @app.route("/anime2d/<pid>/design/gerar", methods=["POST"])
    def anime2d_design_gerar(pid: str):
        _p(pid)
        c = request.get_json(silent=True) or {}
        try:
            return _ok(**AM.gerar_designs(pid, c.get("cids") or None, str(c.get("pedido") or "")[:500], base_dir))
        except A.AnimeErro as exc:
            return _erro(str(exc))

    @app.route("/anime2d/<pid>/design/<cid>", methods=["POST"])
    def anime2d_design(pid: str, cid: str):
        """✔ aprovar (arquivo = a versão) / desfazer, ou 📁 o seu design (arquivo enviado)."""
        f = request.files.get("arquivo")
        c = request.get_json(silent=True) or {}
        with A._TRAVA:
            p = _p(pid)
            try:
                if f:
                    AM.design_seu(p, cid, f.read(), base_dir)
                else:
                    AM.aprovar_design(p, cid, str(c.get("arquivo") or ""), c.get("aprovar", True) is not False)
            except A.AnimeErro as exc:
                return _erro(str(exc))
            A.salvar(p, base_dir)
        return _ok()

    # ------------------------------------------------------------------ 📐 montar o cenário (lugares e móveis)
    @app.route("/anime2d/<pid>/local/<lid>/layout", methods=["POST"])
    def anime2d_layout(pid: str, lid: str):
        """Salva onde ficam os LUGARES (x, y = os pés, escala, sentado) e os MÓVEIS (x, y = a base, w = largura) — tudo
        em frações da tela — e a altura de quem está em pé no chão da frente (chao.alt)."""
        c = request.get_json(silent=True) or {}
        with A._TRAVA:
            p = _p(pid)
            lo = next((x for x in p["locais"] if x["id"] == lid), None)
            if not lo:
                return _erro("Local não encontrado.")
            num = lambda v, a, b, d: max(a, min(b, float(v))) if isinstance(v, (int, float)) else d  # noqa: E731
            if isinstance(c.get("lugares"), list):
                novos = []
                for y in c["lugares"][:20]:
                    if not isinstance(y, dict) or not str(y.get("nome") or "").strip():
                        continue
                    novos.append({"nome": " ".join(str(y["nome"]).split())[:40], "x": num(y.get("x"), 0, 1, 0.5),
                                  "y": num(y.get("y"), 0.2, 1.1, 0.97), "escala": num(y.get("escala"), 0.2, 2.5, 1.0),
                                  "sentado": bool(y.get("sentado")), "descricao": str(y.get("descricao") or "")[:200]})
                lo["lugares"] = novos
            for y in c.get("props") or []:
                pr = next((z for z in lo.get("props") or [] if isinstance(y, dict) and z["id"] == y.get("id")), None)
                if pr:
                    pr.update(x=num(y.get("x"), -0.3, 1.3, 0.5), y=num(y.get("y"), 0, 1.4, 1.0), w=num(y.get("w"), 0.02, 2, 0.3))
                    if y.get("camada") in ("atras", "frente"):
                        pr["camada"] = y["camada"]
            if isinstance(c.get("chao"), dict):
                lo["chao"] = {"y": num(c["chao"].get("y"), 0.3, 1.1, 0.97), "alt": num(c["chao"].get("alt"), 0.1, 1.5, 0.62)}
            A.salvar(p, base_dir)
        return _ok()

    @app.route("/anime2d/<pid>/local/<lid>/prop", methods=["POST"])
    def anime2d_prop(pid: str, lid: str):
        """🪑 Cria / edita / apaga um móvel do cenário (uma camada separada, gerada no Flow ou a sua imagem)."""
        c = request.get_json(silent=True) or {}
        with A._TRAVA:
            p = _p(pid)
            lo = next((x for x in p["locais"] if x["id"] == lid), None)
            if not lo:
                return _erro("Local não encontrado.")
            props = lo.setdefault("props", [])
            if c.get("apagar"):
                lo["props"] = [x for x in props if x["id"] != c.get("id")]
            elif c.get("id"):
                pr = next((x for x in props if x["id"] == c["id"]), None)
                if not pr:
                    return _erro("Móvel não encontrado.")
                for k in ("nome", "prompt_en"):
                    if k in c:
                        pr[k] = " ".join(str(c[k] or "").split())[:400]
                if c.get("camada") in ("atras", "frente"):
                    pr["camada"] = c["camada"]
            else:
                nome = " ".join(str(c.get("nome") or "").split())[:60]
                if not nome:
                    return _erro("Escreva o nome do móvel.")
                pr = {"id": A._id("p"), "nome": nome, "prompt_en": " ".join(str(c.get("prompt_en") or nome).split())[:400],
                      "camada": c.get("camada") if c.get("camada") in ("atras", "frente") else "frente", "img": {},
                      "x": 0.5, "y": 1.0 if c.get("camada") != "atras" else 0.8, "w": 0.35 if c.get("camada") != "atras" else 0.16}
                props.append(pr)
            A.salvar(p, base_dir)
        return _ok()

    @app.route("/anime2d/<pid>/local/<lid>/ia", methods=["POST"])
    def anime2d_layout_ia(pid: str, lid: str):
        _p(pid)
        return _rodar(pid, "layout", "📐 A IA posicionando o cenário", lambda: A.ajustar_cenario(pid, lid, base_dir)) or _ok()

    # ------------------------------------------------------------------ 📦 zip com tudo
    @app.route("/anime2d/zip-exemplo.zip")
    def anime2d_zip_exemplo():
        import io
        return send_file(io.BytesIO(AZ.exemplo()), mimetype="application/zip", as_attachment=True,
                         download_name="exemplo_animacao_2d.zip")

    @app.route("/anime2d/zip-guia.txt")
    def anime2d_zip_guia():
        return AZ.GUIA_ZIP, 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.route("/anime2d/<pid>/zip", methods=["GET", "POST"])
    def anime2d_zip(pid: str):
        p = _p(pid)
        if request.method == "GET":  # ⬇ exportar
            import io
            nome = re.sub(r"[^\w\- ]+", "", p["titulo"]).strip().replace(" ", "_")[:60] or pid
            return send_file(io.BytesIO(AZ.exportar(pid, base_dir)), mimetype="application/zip", as_attachment=True,
                             download_name=f"{nome}.zip")
        f = request.files.get("arquivo")
        if not f or not f.filename:
            return _erro("Escolha o .zip.")
        try:
            rel = AZ.importar(pid, f.read(), base_dir)
        except A.AnimeErro as exc:
            return _erro(str(exc))
        q = A.carregar(pid, base_dir)
        if rel.get("audio") and A.audio_ok(q, base_dir):
            _rodar(pid, "transcrever", "🎙 Transcrever o áudio", lambda: f"{A.transcrever_audio(pid, base_dir)} trecho(s)")
        return _ok(**rel)

    @app.route("/anime2d/<pid>/referencia", methods=["POST"])
    def anime2d_ref(pid: str):
        f = request.files.get("arquivo")
        if not f or not f.filename:
            return _erro("Escolha a imagem.")
        with A._TRAVA:
            p = _p(pid)
            try:
                r = A.guardar_referencia(p, f.filename, f.read(), request.form.get("tipo") or "personagem",
                                         request.form.get("nome") or "", request.form.get("nota") or "", base_dir)
            except A.AnimeErro as exc:
                return _erro(str(exc))
            A.salvar(p, base_dir)
        return _ok(ref=r)

    @app.route("/anime2d/<pid>/referencia/<rid>", methods=["POST"])
    def anime2d_ref_editar(pid: str, rid: str):
        c = request.get_json(silent=True) or {}
        with A._TRAVA:
            p = _p(pid)
            r = next((x for x in p["referencias"] if x["id"] == rid), None)
            if not r:
                return _erro("Referência não encontrada.")
            if c.get("apagar"):
                p["referencias"] = [x for x in p["referencias"] if x["id"] != rid]
                for lista in ("personagens", "locais", "itens"):
                    for x in p[lista]:
                        x["refs"] = [a for a in x.get("refs") or [] if a != r["arquivo"]]
            else:
                for k in ("nome", "nota"):
                    if k in c:
                        r[k] = " ".join(str(c[k] or "").split())[:300]
                if c.get("tipo") in A.TIPOS_REF:
                    r["tipo"] = c["tipo"]
                A.vincular_referencias(p)
            A.salvar(p, base_dir)
        return _ok()

    @app.route("/anime2d/<pid>/arquivo/<pasta>/<nome>")
    def anime2d_arquivo(pid: str, pasta: str, nome: str):
        _p(pid)
        if pasta not in ("refs", "imagens", "vozes"):
            abort(404)
        cam = os.path.join(A.pasta(pid, base_dir), pasta, secure_filename(nome))
        return send_file(cam, max_age=0) if os.path.isfile(cam) else ("", 404)

    # ------------------------------------------------------------------ 🤖 plano e cenas (ou colar de outra IA)
    @app.route("/anime2d/<pid>/ia/<oque>", methods=["POST"])
    def anime2d_ia(pid: str, oque: str):
        _p(pid)
        c = request.get_json(silent=True) or {}
        if oque == "plano":
            return _rodar(pid, oque, "🤖 Planejar o episódio", lambda: (
                lambda r: f"{len(A.carregar(pid, base_dir)['cenas'])} cena(s)")(A.planejar(pid, base_dir))) or _ok()
        if oque == "manga":
            return _rodar(pid, oque, "📖 Ler o mangá e planejar a adaptação", lambda: (
                lambda r: f"{r['personagens']} personagem(ns), {r['cenas']} cena(s), {r['recortes']} recorte(s)")(
                    AM.ler_manga(pid, base_dir))) or _ok()
        if oque == "cenas":
            ks = [int(k) for k in c.get("ks") or [] if str(k).isdigit()] or None
            so = bool(c.get("so_vazias"))
            return _rodar(pid, oque, "🤖 Escrever as cenas", lambda: (
                lambda r: f"{r['feitas']} cena(s)" + (f" · ⚠ faltaram {', '.join(r['erros'])}" if r["erros"] else ""))(
                    A.escrever_cenas(pid, base_dir, ks, so, _prog(pid)))) or _ok()
        abort(404)

    @app.route("/anime2d/<pid>/prompt/<tipo>")
    def anime2d_prompt(pid: str, tipo: str):
        p = _p(pid)
        try:
            if tipo == "manga":
                return _ok(prompt=AM.prompt_copiar(p))
            return _ok(prompt=A.prompt_copiar(p, "plano" if tipo == "plano" else "cena", int(request.args.get("k") or 0)))
        except A.AnimeErro as exc:
            return _erro(str(exc))

    @app.route("/anime2d/<pid>/colar/<tipo>", methods=["POST"])
    def anime2d_colar(pid: str, tipo: str):
        c = request.get_json(silent=True) or {}
        txt = str(c.get("texto") or "").strip()
        m = re.search(r"\{.*\}", txt, re.S)
        try:
            r = json.loads(m.group(0) if m else txt)
        except (ValueError, AttributeError):
            return _erro("Não achei um JSON válido na resposta colada.")
        with A._TRAVA:
            p = _p(pid)
            try:
                if tipo == "plano":
                    A.aplicar_plano(p, r)
                elif tipo == "manga":
                    AM.aplicar_adaptacao(p, r, base_dir)
                else:
                    A.aplicar_cena(p, int(c.get("k") or 0), r)
            except (A.AnimeErro, IndexError) as exc:
                return _erro(str(exc))
            A.salvar(p, base_dir)
        return _ok()

    # ------------------------------------------------------------------ ✏ editar personagens / locais / itens / cenas
    CAMPOS = {"personagens": ("nome", "descricao", "personalidade", "jeito_de_falar", "aparencia_en", "voz", "cor", "genero", "idade",
                              "design_en"),
              "locais": ("nome", "descricao", "prompt_en", "frente_en"),
              "itens": ("nome", "prompt_en", "tipo", "texto")}

    @app.route("/anime2d/<pid>/<lista>/<xid>", methods=["POST"])
    def anime2d_editar(pid: str, lista: str, xid: str):
        if lista not in CAMPOS:
            abort(404)
        c = request.get_json(silent=True) or {}
        with A._TRAVA:
            p = _p(pid)
            if xid == "novo":
                nome = " ".join(str(c.get("nome") or "").split())[:60]
                if not nome:
                    return _erro("Escreva o nome.")
                x = {"id": A._id({"personagens": "c", "locais": "l", "itens": "i"}[lista]), "nome": nome, "refs": []}
                if lista == "personagens":
                    x.update(voz="", pod={}, cor=A.CORES[len(p["personagens"]) % len(A.CORES)])
                if lista == "itens":
                    x["tipo"] = c.get("tipo") if c.get("tipo") in ("objeto", "destaque") else "objeto"
                p[lista].append(x)
                A.vincular_referencias(p)
            else:
                x = next((y for y in p[lista] if y["id"] == xid), None)
                if not x:
                    return _erro("Não encontrado.")
                if c.get("apagar"):
                    p[lista] = [y for y in p[lista] if y["id"] != xid]
                else:
                    for k in CAMPOS[lista]:
                        if k in c:
                            x[k] = str(c[k] or "").strip()[:900]
                    if lista == "itens" and x.get("tipo") not in ("objeto", "destaque"):
                        x["tipo"] = "objeto"
                    if lista == "itens" and "personagens_txt" in c:  # 🧍 quem aparece (nomes separados por vírgula)
                        A.aplicar_item_extras(p, x, {"personagens": [n for n in re.split(r"[,;]", str(c["personagens_txt"] or "")) if n.strip()]})
                    if lista == "personagens" and "design_en" in c and str(c["design_en"] or "").strip():
                        x["aparencia_en"] = x["design_en"]
            A.salvar(p, base_dir)
        return _ok(id=x["id"])

    @app.route("/anime2d/<pid>/cenas", methods=["POST"])
    def anime2d_cenas(pid: str):
        c = request.get_json(silent=True) or {}
        with A._TRAVA:
            p = _p(pid)
            acao, k = c.get("acao"), int(c.get("k") or 0)
            if acao == "nova":
                p["cenas"].insert(min(len(p["cenas"]), k), {"id": A._id("s"), "titulo": "Nova cena", "local": (p["locais"][0]["id"] if p["locais"] else ""),
                                                            "resumo": "", "personagens": [], "camera": "fixa", "momentos": []})
            elif acao == "apagar" and 0 <= k < len(p["cenas"]):
                p["cenas"].pop(k)
            elif acao == "mover" and 0 <= k < len(p["cenas"]):
                j = k + (1 if c.get("d") == 1 else -1)
                if 0 <= j < len(p["cenas"]):
                    p["cenas"][k], p["cenas"][j] = p["cenas"][j], p["cenas"][k]
            A.salvar(p, base_dir)
        return _ok()

    @app.route("/anime2d/<pid>/cena/<int:k>", methods=["POST"])
    def anime2d_cena(pid: str, k: int):
        c = request.get_json(silent=True) or {}
        with A._TRAVA:
            p = _p(pid)
            if not 0 <= k < len(p["cenas"]):
                return _erro("Cena inexistente.")
            s = p["cenas"][k]
            for kk in ("titulo", "resumo"):
                if kk in c:
                    s[kk] = str(c[kk] or "").strip()[:1200]
            if "local" in c and any(x["id"] == c["local"] for x in p["locais"]):
                s["local"] = c["local"]
            if isinstance(c.get("momentos"), list):
                antigos = {m["id"]: m for m in s.get("momentos") or []}
                novos = []
                lug = A.lugares_do_local(p, A.local_da_cena(p, s))
                for x in c["momentos"]:
                    m = A.limpar_momento(p, x, lug)
                    if not m:
                        continue
                    velho = antigos.get(m["id"]) or {}
                    for kk in ("audio", "video"):  # a voz/o vídeo que já tinha continua (a voz refaz se o texto mudou)
                        if velho.get(kk):
                            m[kk] = velho[kk]
                    novos.append(m)
                s["momentos"] = novos
            A.salvar(p, base_dir)
        return _ok()

    # ------------------------------------------------------------------ 🧍 personagens no Flow
    @app.route("/anime2d/<pid>/poses/gerar", methods=["POST"])
    def anime2d_poses(pid: str):
        p = _p(pid)
        c = request.get_json(silent=True) or {}
        cids = [x for x in c.get("cids") or [] if any(y["id"] == x for y in p["personagens"])] or [y["id"] for y in p["personagens"]]
        avisos = []
        for cid in cids:
            try:
                r = A.criar_poses(pid, cid, base_dir)
                if r.get("aviso"):
                    avisos.append(r["aviso"])
            except Exception as exc:  # noqa: BLE001
                avisos.append(str(exc)[:200])
        return _ok(avisos=avisos)

    @app.route("/anime2d/<pid>/pose/<cid>/<nome>")
    def anime2d_pose(pid: str, cid: str, nome: str):
        p = _p(pid)
        ch = next((x for x in p["personagens"] if x["id"] == cid), None)
        ppid = ((ch or {}).get("pod") or {}).get("pid")
        if not ppid:
            abort(404)
        import personagens_pod as pp
        cam = os.path.join(pp._pasta(ppid, base_dir), "imagens", secure_filename(nome))
        return send_file(cam) if os.path.isfile(cam) else ("", 404)

    # ------------------------------------------------------------------ 🏞 locais e itens
    @app.route("/anime2d/<pid>/imagens/gerar", methods=["POST"])
    def anime2d_imagens(pid: str):
        _p(pid)
        c = request.get_json(silent=True) or {}
        try:
            return _ok(**A.gerar_imagens(pid, base_dir, c.get("alvos") or None, str(c.get("pedido") or "")))
        except A.AnimeErro as exc:
            return _erro(str(exc))

    @app.route("/anime2d/<pid>/imagens/reaproveitar", methods=["POST"])
    def anime2d_reaproveitar(pid: str):
        _p(pid)
        return _ok(n=A.reaproveitar_imagens(pid, base_dir))

    @app.route("/anime2d/<pid>/imagem/<alvo>", methods=["POST"])
    def anime2d_imagem_sua(pid: str, alvo: str):
        """📁 a sua imagem pro fundo/frente de um local (alvo "l…:fundo"/"l…:frente") ou um item (alvo "i…")."""
        from PIL import Image
        f = request.files.get("arquivo")
        if not f:
            return _erro("Escolha a imagem.")
        with A._TRAVA:
            p = _p(pid)
            xid, _, camada = alvo.partition(":")
            lista = p["locais"] if xid.startswith("l") else p["itens"]
            x = next((y for y in lista if y["id"] == xid), None)
            if not x:
                return _erro("Não encontrado.")
            campo = "frente" if camada == "frente" else "img"
            try:
                img = Image.open(f.stream)
                img.load()
            except Exception:  # noqa: BLE001
                return _erro("Não consegui abrir essa imagem.")
            recortar = camada == "frente" or (xid.startswith("i") and x.get("tipo") != "destaque")
            tela = (xid.startswith("l") and camada != "frente") or (xid.startswith("i") and x.get("tipo") == "destaque")
            if xid.startswith("l") and camada.startswith("p"):  # 🪑 um móvel do cenário
                x = next((y for y in x.get("props") or [] if y["id"] == camada), None)
                if not x:
                    return _erro("Móvel não encontrado.")
                campo, recortar, tela = "img", True, False
            A.guardar_img(p, x.setdefault(campo, {}), img, recortar, base_dir, origem="sua", tela_cheia=tela)
            A.salvar(p, base_dir)
        return _ok()

    # ------------------------------------------------------------------ 🎙 vozes
    @app.route("/anime2d/<pid>/vozes/gerar", methods=["POST"])
    def anime2d_vozes(pid: str):
        _p(pid)
        if not tts:
            return _erro("O gerador de voz não está disponível aqui.")
        c = request.get_json(silent=True) or {}
        tudo = bool(c.get("tudo"))
        return _rodar(pid, "vozes", "🎙 Gerar as vozes", lambda: (
            lambda r: f"{r['feitas']} fala(s)" + (f" · {r['sem_voz']} sem voz" if r["sem_voz"] else "") + (f" · ❌ {len(r['erros'])} erro(s): {r['erros'][0]}" if r["erros"] else ""))(
                A.gerar_vozes(pid, base_dir, tts, limpar_tts or (lambda t, m: t), not tudo, _prog(pid)))) or _ok()

    # ------------------------------------------------------------------ 🎞 um momento animado no Flow (só quando pedir)
    @app.route("/anime2d/<pid>/momento/<mid>/animar", methods=["POST"])
    def anime2d_animar(pid: str, mid: str):
        _p(pid)
        c = request.get_json(silent=True) or {}
        try:
            if c.get("tirar"):
                with A._TRAVA:
                    p = _p(pid)
                    _k, _j, m = A.momento(p, mid)
                    m.pop("video", None)
                    A.salvar(p, base_dir)
                return _ok()
            return _ok(**A.animar_momento(pid, mid, str(c.get("pedido") or ""), base_dir))
        except A.AnimeErro as exc:
            return _erro(str(exc))

    # ------------------------------------------------------------------ 👁 prévia e 🎬 editor
    @app.route("/anime2d/<pid>/previa.jpg")
    def anime2d_previa(pid: str):
        p = _p(pid)
        destino = os.path.join(A.pasta(pid, base_dir), "previa.jpg")
        try:
            A.previa(p, base_dir, destino, A.R.segundos(request.args.get("t")) or 0.0)
        except Exception as exc:  # noqa: BLE001
            return f"não deu pra montar a prévia: {exc}", 500
        return send_file(destino, max_age=0)

    @app.route("/anime2d/<pid>/editor", methods=["POST"])
    def anime2d_editor(pid: str):
        p = _p(pid)
        job_id = uuid.uuid4().hex[:12]
        jd = pasta_job(job_id)
        os.makedirs(jd, exist_ok=True)
        try:
            m = A.montar_editor(p, base_dir, jd)
        except A.AnimeErro as exc:
            import shutil
            shutil.rmtree(jd, ignore_errors=True)
            return _erro(str(exc))
        W, H = A.tamanho(p)
        job = {
            "job_id": job_id, "audio_path": m["audio"], "music_path": None, "music_volume": 0.18, "providers": [],
            "add_word_captions": False, "caption_style": {}, "status": "pronto_para_editar", "created_at": time.time(),
            "cancel_requested": False, "original_filename": f"🎞 {p['titulo']}", "nome_projeto": f"🎞 {p['titulo']}"[:60],
            "segments": [], "pending_segments": m["segmentos"],
            "segment_previews": [{"ok": True, "thumbnail_url": f"/job/{job_id}/segment-thumb/{k}", "provider": "material",
                                  "label": s["query"], "media_type": "image"} for k, s in enumerate(m["segmentos"])],
            "overlays": m["overlays"], "total_duration": m["duracao"], "prompt": "", "whisper_skipped": True,
            "orientation": "16:9" if W > H else "9:16", "export_quality": "1080p",
            "anime2d": {"projeto": pid, "falas": m["falas"], "avisos": m["avisos"]}, "interval_seconds": 7,
        }
        criar_job(job_id, job)
        with A._TRAVA:
            p = _p(pid)
            p["editor"] = {"job_id": job_id, "quando": time.time(), "avisos": m["avisos"]}
            A.log(p, f"🎬 mandado pro editor ({len(m['segmentos'])} cena(s), {len(m['overlays'])} camadas)")
            A.salvar(p, base_dir)
        return _ok(link=f"/job/{job_id}/edit-segments", avisos=m["avisos"], job_id=job_id)
