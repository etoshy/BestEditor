"""
Rotas do 🎭 React de personagens (ver react_personagens.py). Registradas pelo app.py com
`registrar(app, base_dir, criar_job)` — `criar_job(job_id, job)` põe o projeto pronto no Estúdio.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from flask import abort, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

import react_personagens as R

TAREFAS: Dict[str, Dict[str, Any]] = {}  # pid → a tarefa em segundo plano (uma por vez por projeto)
_ULTIMO_ACOMP: Dict[str, float] = {}
_RE_GUIA = re.compile(r"^/modelos-video/(rp[0-9a-f]{10})/fotos-roteiro/(link|guia-feita|guias)$")


def _avisar(titulo: str, msg: str, link: str, nivel: str = "ok") -> None:
    try:
        import notificacoes
        notificacoes.avisar(titulo, msg, link, nivel, tipo="react")
    except Exception:  # noqa: BLE001
        pass


def registrar(app, base_dir: str, criar_job: Callable[[str, Dict[str, Any]], None],
              pasta_job: Callable[[str], str]) -> None:

    def _p(pid: str) -> Dict[str, Any]:
        try:
            return R.carregar(pid, base_dir)
        except R.ReactErro:
            abort(404)

    def _ok(**kw: Any):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: str, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _rodar(pid: str, oque: str, rotulo: str, fn: Callable[[], Any]) -> Optional[Any]:
        """Roda `fn` numa thread (a página acompanha pelo /estado). → resposta de erro se já tem uma rodando."""
        t = TAREFAS.get(pid)
        if t and not t.get("fim"):
            return _erro(f"Espere terminar: {t.get('rotulo')}", 409)
        TAREFAS[pid] = {"oque": oque, "rotulo": rotulo, "inicio": time.time(), "fim": None, "erro": None, "msg": ""}

        def corpo():
            try:
                r = fn()
                TAREFAS[pid].update(msg=r if isinstance(r, str) else "")
                _avisar(f"✅ React — {rotulo}", "", f"/react-personagens/{pid}")
            except Exception as exc:  # noqa: BLE001
                TAREFAS[pid]["erro"] = str(exc)[:500]
                _avisar(f"❌ React — {rotulo}", str(exc)[:400], f"/react-personagens/{pid}", "erro")
            finally:
                TAREFAS[pid]["fim"] = time.time()

        threading.Thread(target=corpo, daemon=True).start()
        return None

    @app.context_processor
    def _react_no_template():
        return {"react_lista": lambda: R.listar(base_dir)}

    # ------------------------------------------------------------------ criar / página
    @app.route("/react-personagens")
    def react_lista_pagina():
        return redirect("/modelos-video#react")

    @app.route("/react-personagens/novo", methods=["POST"])
    def react_novo():
        titulo = (request.form.get("titulo") or "").strip()
        p = R.criar(titulo, base_dir)
        p["obra"] = (request.form.get("obra") or "").strip()[:200]
        url = (request.form.get("url") or "").strip()
        trans = request.form.get("transcricao") or ""
        arq_t = request.files.get("transcricao_arquivo")
        if arq_t and arq_t.filename:
            trans = arq_t.read().decode("utf-8-sig", errors="replace")
        if trans.strip():
            R.definir_transcricao(p, trans)
        if url:
            p["video"] = {"url": url, "estado": "baixando"}
        arq_v = request.files.get("video_arquivo")
        if arq_v and arq_v.filename:
            tmp = os.path.join(R.pasta(p["id"], base_dir), "_up_" + secure_filename(arq_v.filename))
            arq_v.save(tmp)
            R.guardar_video(p, tmp, base_dir, nome=arq_v.filename)
            if not titulo:
                p["titulo"] = os.path.splitext(arq_v.filename)[0][:200]
        R.salvar(p, base_dir)
        if url and not (arq_v and arq_v.filename):
            pid_ = p["id"]
            if R.eh_youtube(url) and not trans.strip():
                _rodar(pid_, "baixar", "⬇ Baixar o vídeo e 📺 puxar a transcrição do YouTube",
                       lambda: _baixar(pid_) + " · " + _transcrever_yt(pid_))
            else:
                _rodar(pid_, "baixar", "⬇ Baixar o vídeo", lambda: _baixar(pid_))
        return redirect(url_for("react_pagina", pid=p["id"]))

    def _baixar(pid: str) -> str:
        try:
            v = R.baixar_video(pid, base_dir)
        except Exception as exc:
            with R._TRAVA:
                p = R.carregar(pid, base_dir)
                p["video"].update(estado="erro", erro=str(exc)[:300])
                R.salvar(p, base_dir)
            raise
        return f"vídeo de {R.mmss(v.get('duracao'))}"

    def _transcrever_yt(pid: str) -> str:
        try:
            return f"transcrição do YouTube: {R.transcrever_youtube(pid, base_dir)} linha(s)"
        except R.ReactErro as exc:  # o vídeo baixou: a transcrição falhar não derruba a tarefa
            return f"⚠ transcrição do YouTube: {exc} (cole a transcrição ou use o Whisper)"

    @app.route("/react-personagens/<pid>/transcricao/youtube", methods=["POST"])
    def react_transcricao_youtube(pid: str):
        p = _p(pid)
        url = str((request.get_json(silent=True) or {}).get("url") or "").strip()
        if url:
            with R._TRAVA:
                p = _p(pid)
                p["video"]["url"] = url[:500]
                R.salvar(p, base_dir)
        if not R.eh_youtube(p["video"].get("url") or url):
            return _erro("A transcrição automática é pra link do YouTube — cole o link no campo do vídeo.")
        return _rodar(pid, "transcricao", "📺 Puxar a transcrição do YouTube",
                      lambda: f"{R.transcrever_youtube(pid, base_dir)} linha(s)") or _ok()

    @app.route("/react-personagens/<pid>/destaque", methods=["POST"])
    def react_destaque(pid: str):
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            n = R.marcar_destaque(p, str(c.get("texto") or ""), R.segundos(c.get("ini")), bool(c.get("marcar", True)))
            R.salvar(p, base_dir)
        return _ok(destaques=n)

    @app.route("/react-personagens/<pid>/cortes", methods=["POST"])
    def react_cortes(pid: str):
        p = _p(pid)
        if not R.video_original(p, base_dir):
            return _erro("Baixe ou envie o vídeo antes.")
        c = request.get_json(silent=True) or {}
        cortes = {"inicio": c.get("inicio"), "fim": c.get("fim"), "meio": c.get("meio") or []}
        for x in cortes["meio"]:
            if not (isinstance(x, (list, tuple)) and len(x) == 2 and R.segundos(x[0]) is not None and R.segundos(x[1]) is not None
                    and R.segundos(x[1]) > R.segundos(x[0])):
                return _erro(f"Corte do meio inválido: {x} (o “até” tem que vir depois do “de”).")
        def fazer():
            r = R.aplicar_cortes(pid, base_dir, cortes)
            return (f"vídeo com {R.mmss(r['duracao'])}" + (f" · {r['falas_sairam']} fala(s) saíram" if r["falas_sairam"] else ""))
        return _rodar(pid, "cortes", "✂ Cortar o vídeo", fazer) or _ok()

    @app.route("/react-personagens/<pid>")
    def react_pagina(pid: str):
        p = _p(pid)
        try:
            R.sincronizar_publicacao(p, base_dir)  # 🖼 o react também é uma publicação (capas, títulos, descrição)
        except Exception:  # noqa: BLE001
            pass
        return render_template("react_detalhe.html", p=R.para_tela(p, base_dir), biblia=p.get("biblia") or {}, pub_api=f"/publicacoes/{p['id']}/api", layouts=R.LAYOUTS, estilos=R.ESTILOS,
                               expressoes=R.EXPRESSOES, densidades=list(R.DENSIDADES),
                               intrigas=R.INTRIGAS, tipos_evento=R.TIPOS_EVENTO, estilos_arte=R.ESTILOS_ARTE, camadas=R.CAMADAS, tipos_nota=R.TIPOS_NOTA, modos_ref=R.MODOS_REF, gestos={k: v[0] for k, v in R.GESTOS.items()}, passante=R.PASSANTE,
                               rotulo_camada=R.ROTULO_CAMADA)

    @app.route("/react-personagens/<pid>/estado")
    def react_estado(pid: str):
        _p(pid)
        avisos: List[str] = []
        if time.time() - _ULTIMO_ACOMP.get(pid, 0) > 3:  # o Flow é olhado no máximo a cada 3 s
            _ULTIMO_ACOMP[pid] = time.time()
            try:
                avisos = R.acompanhar(pid, base_dir).get("avisos") or []
            except Exception as exc:  # noqa: BLE001
                avisos = [str(exc)[:200]]
        p = R.carregar(pid, base_dir)
        return jsonify(dict(R.para_tela(p, base_dir), tarefa=TAREFAS.get(pid), avisos=avisos))

    @app.route("/react-personagens/<pid>/excluir", methods=["POST"])
    def react_excluir(pid: str):
        _p(pid)
        R.excluir(pid, base_dir)
        return redirect("/modelos-video#react")

    @app.route("/react-personagens/<pid>/dados", methods=["POST"])
    def react_dados(pid: str):
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            for k in ("titulo", "obra", "contexto", "idioma"):
                if k in c:
                    p[k] = str(c[k] or "").strip()[:2000 if k == "contexto" else 200]
            if c.get("estilo") in R.ESTILOS:
                p["estilo"] = c["estilo"]
            if c.get("layout") in R.LAYOUTS:
                p["layout"] = c["layout"]
            if c.get("densidade") in R.DENSIDADES:
                p["densidade"] = c["densidade"]
            if c.get("intriga") in R.INTRIGAS:
                p["intriga"] = c["intriga"]
            if "imagens_destaque" in c:
                p["imagens_destaque"] = bool(c["imagens_destaque"])
            if "escutar" in c:  # 👂 v84_245
                p["escutar"] = bool(c["escutar"])
            for k in ("abertura", "encerramento", "movimentos"):
                if k in c:
                    p[k] = bool(c[k])
            if "biblia" in c:
                R.definir_biblia(p, str(c["biblia"] or ""))
            if isinstance(c.get("expressoes"), list):
                ex = [e for e in c["expressoes"] if e in R.EXPRESSOES]
                p["expressoes"] = (["neutro"] if "neutro" not in ex else []) + ex
            if "pedido_cenario" in c:
                p["cenario"]["pedido"] = str(c["pedido_cenario"] or "").strip()[:500]
            if "url" in c:
                p["video"]["url"] = str(c["url"] or "").strip()[:500]
            if "transcricao_bruta" in c:
                R.definir_transcricao(p, str(c["transcricao_bruta"] or ""))
            R.salvar(p, base_dir)
        return _ok(linhas=len(p["transcricao"]), creditos=sum(1 for e in p["transcricao"] if e["tipo"] == "credito"))

    # ------------------------------------------------------------------ vídeo
    @app.route("/react-personagens/<pid>/video", methods=["GET", "POST"])
    def react_video(pid: str):
        p = _p(pid)
        if request.method == "GET":
            cam = R.video_original(p, base_dir) if request.args.get("original") else R.video_local(p, base_dir)
            return send_file(cam, conditional=True) if cam else ("sem vídeo", 404)
        arq = request.files.get("video")
        if not arq or not arq.filename:
            return _erro("Escolha o arquivo do vídeo.")
        tmp = os.path.join(R.pasta(pid, base_dir), "_up_" + secure_filename(arq.filename))
        arq.save(tmp)
        with R._TRAVA:
            p = _p(pid)
            v = R.guardar_video(p, tmp, base_dir, nome=arq.filename)
            R.log(p, f"📁 vídeo enviado ({R.mmss(v.get('duracao'))})")
            R.salvar(p, base_dir)
        return _ok(video=v)

    @app.route("/react-personagens/<pid>/video/baixar", methods=["POST"])
    def react_video_baixar(pid: str):
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            if c.get("url"):
                p["video"]["url"] = str(c["url"]).strip()[:500]
            if not re.match(r"^https?://", str(p["video"].get("url") or "")):
                return _erro("Cole o link do vídeo (https://…).")
            p["video"].update(estado="baixando", erro=None)
            R.salvar(p, base_dir)
        return _rodar(pid, "baixar", "⬇ Baixar o vídeo", lambda: _baixar(pid)) or _ok()

    @app.route("/react-personagens/<pid>/whisper", methods=["POST"])
    def react_whisper(pid: str):
        _p(pid)
        return _rodar(pid, "whisper", "🎙 Transcrever com o Whisper",
                      lambda: f"{R.transcrever_whisper(pid, base_dir)} linha(s)") or _ok()

    # ------------------------------------------------------------------ 🤖 IA (ou colar de outra IA)
    @app.route("/react-personagens/<pid>/ia/<oque>", methods=["POST"])
    def react_ia(pid: str, oque: str):
        _p(pid)
        if oque == "sugerir":
            return _rodar(pid, oque, "🤖 Sugerir personagens",
                          lambda: f"{len(R.sugerir(pid, base_dir)['personagens'])} sugestão(ões)") or _ok()
        if oque == "fichas":
            return _rodar(pid, oque, "🤖 Completar as fichas", lambda: f"{R.completar_fichas(pid, base_dir)} ficha(s)") or _ok()
        if oque == "roteiro":
            c = request.get_json(silent=True) or {}
            parte = c.get("parte")
            parte = int(parte) if isinstance(parte, (int, float, str)) and str(parte).isdigit() else None
            so_vazias = bool(c.get("so_vazias"))
            rot = ("🤖 Escrever a parte " + str(parte + 1) if parte is not None
                   else "🤖 Completar as partes que faltam" if so_vazias else "🤖 Escrever o roteiro (em partes)")
            return _rodar(pid, oque, rot, lambda: R.gerar_roteiro(
                pid, base_dir, parte=parte, so_vazias=so_vazias,
                on_log=lambda m: TAREFAS[pid].update(progresso=str(m)[:200]))["msg"]) or _ok()
        if oque == "biblia":
            def bib():
                r = R.resumir_biblia(pid, base_dir)
                return f"{r['episodios']} episódio(s), {r['personagens']} personagem(ns)" + (f" · {r['fichas']} ficha(s) completadas" if r["fichas"] else "")
            return _rodar(pid, oque, "📖 Organizar a bíblia da obra", bib) or _ok()
        if oque == "ler":
            c = request.get_json(silent=True) or {}
            refazer = bool(c.get("refazer"))

            def ler():
                r = R.ler_video(pid, base_dir, refazer=refazer, on_log=lambda m: TAREFAS[pid].update(progresso=str(m)[:200]))
                return f"{r['trechos']} de {r['total']} trecho(s) lidos" + (f" · {r['erros']} com erro" if r["erros"] else "")
            return _rodar(pid, oque, "👁 A IA assistindo ao vídeo", ler) or _ok()
        abort(404)

    @app.route("/react-personagens/<pid>/prompt/<tipo>")
    def react_prompt(pid: str, tipo: str):
        p = _p(pid)
        if tipo not in ("sugestoes", "fichas", "roteiro"):
            abort(404)
        parte = request.args.get("parte")
        try:
            return jsonify({"ok": True, "prompt": R.prompt_copiar(p, tipo, int(parte) if parte and parte.isdigit() else None)})
        except R.ReactErro as exc:
            return _erro(str(exc))

    @app.route("/react-personagens/<pid>/colar/<tipo>", methods=["POST"])
    def react_colar(pid: str, tipo: str):
        import json_ia
        texto = str((request.get_json(silent=True) or {}).get("texto") or "")
        try:
            r = json_ia.carregar(texto, aceitar_cortado=True)
        except ValueError as exc:
            return _erro(f"Não consegui ler o JSON: {exc}")
        with R._TRAVA:
            p = _p(pid)
            try:
                if tipo == "sugestoes":
                    n = len(R.aplicar_sugestoes(p, r)["personagens"])
                elif tipo == "fichas":
                    n = R.aplicar_fichas(p, r, [c["id"] for c in p["personagens"]])
                elif tipo == "roteiro":
                    parte = (request.get_json(silent=True) or {}).get("parte")
                    ps = R.partes_roteiro(p)
                    if isinstance(parte, int) and 0 <= parte < len(ps):
                        antes = len((p.get("roteiro") or {}).get("falas") or [])
                        n = len(R.aplicar_roteiro(p, r, janela=ps[parte])["falas"]) - antes
                        if all(not x["vazia"] for x in R.estado_partes(p)):
                            R.garantir_cta(p)
                    else:
                        n = len(R.aplicar_roteiro(p, r)["falas"])
                else:
                    abort(404)
            except R.ReactErro as exc:
                return _erro(str(exc))
            R.salvar(p, base_dir)
        return _ok(n=n)

    # ------------------------------------------------------------------ 🧑‍🤝‍🧑 elenco
    @app.route("/react-personagens/<pid>/sugestoes/usar", methods=["POST"])
    def react_usar_sugestoes(pid: str):
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            try:
                novos = R.usar_sugestoes(p, [str(x) for x in c.get("nomes") or []], c.get("editados") or {})
            except R.ReactErro as exc:
                return _erro(str(exc))
            for x in novos:
                R.reaproveitar(p, x, base_dir)  # ♻ já foi gerado num react anterior
            R.salvar(p, base_dir)
        return _ok(novos=[x["id"] for x in novos])

    @app.route("/react-personagens/<pid>/personagem", methods=["POST"])
    def react_add_personagem(pid: str):
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            try:
                novo = R.novo_personagem(p, str(c.get("nome") or ""), obra=c.get("obra") or "")
            except R.ReactErro as exc:
                return _erro(str(exc))
            R.log(p, f"➕ {novo['nome']} no elenco")
            R.reaproveitar(p, novo, base_dir)  # ♻ já foi gerado num react anterior
            R.salvar(p, base_dir)
        return _ok(id=novo["id"], reaproveitado=novo.get("reaproveitado") or "")

    @app.route("/react-personagens/<pid>/personagem/<cid>", methods=["POST", "DELETE"])
    def react_personagem(pid: str, cid: str):
        with R._TRAVA:
            p = _p(pid)
            try:
                ch = R.personagem(p, cid)
            except R.ReactErro as exc:
                return _erro(str(exc), 404)
            if request.method == "DELETE":
                p["personagens"] = [x for x in p["personagens"] if x["id"] != cid]
                rot = p.get("roteiro") or {}
                if rot.get("falas"):
                    rot["falas"] = [f for f in rot["falas"] if f["cid"] != cid]
                    for f in rot["falas"]:
                        f["reacoes"] = [x for x in f.get("reacoes") or [] if x["cid"] != cid]
                R.log(p, f"🗑 {ch['nome']} saiu do elenco")
                R.salvar(p, base_dir)
                return _ok()
            c = request.get_json(silent=True) or {}
            if "nome" in c and str(c["nome"]).strip():
                novo = " ".join(str(c["nome"]).split())[:80]
                if any(R._norm(x["nome"]) == R._norm(novo) and x["id"] != cid for x in p["personagens"]):
                    return _erro(f"{novo} já está no elenco.")
                ch["nome"] = novo
            for k in R.CAMPOS_FICHA_TXT:
                if k in c:
                    ch[k] = str(c[k] or "").strip()[:600]
            if "biblia" in c:  # 📖 a bíblia do personagem (como ele é, como responderia)
                ch["biblia"] = str(c["biblia"] or "").strip()[:4000]
            if c.get("estilo") in ("anime", "realista", ""):
                ch["estilo"] = c["estilo"]
            if re.fullmatch(r"#[0-9a-fA-F]{6}", str(c.get("cor") or "")):
                ch["cor"] = c["cor"]
            R.salvar(p, base_dir)
        return _ok()

    @app.route("/react-personagens/<pid>/personagens/ordem", methods=["POST"])
    def react_ordem(pid: str):
        ids = [str(x) for x in (request.get_json(silent=True) or {}).get("ids") or []]
        with R._TRAVA:
            p = _p(pid)
            por = {c["id"]: c for c in p["personagens"]}
            p["personagens"] = [por[i] for i in ids if i in por] + [c for c in p["personagens"] if c["id"] not in ids]
            R.salvar(p, base_dir)
        return _ok()

    @app.route("/react-personagens/<pid>/personagem/<cid>/ref", methods=["POST"])
    def react_ref(pid: str, cid: str):
        arq = request.files.get("arquivo")
        url = (request.form.get("url") or (request.get_json(silent=True) or {}).get("url") or "").strip()
        with R._TRAVA:
            p = _p(pid)
            try:
                ch = R.personagem(p, cid)
                if arq and arq.filename:
                    nome = R.guardar_ref(p, ch, arq.read(), base_dir)
                elif url:
                    nome = R.baixar_ref(p, ch, url, base_dir)
                else:
                    return _erro("Mande um arquivo ou um link.")
            except R.ReactErro as exc:
                return _erro(str(exc))
            R.salvar(p, base_dir)
        return _ok(ref=nome)

    @app.route("/react-personagens/<pid>/personagem/<cid>/cor", methods=["POST"])
    def react_cor_ref(pid: str, cid: str):
        """🌈 A foto COLORIDA do personagem (só pras cores reais) — enviar/trocar ou tirar ({"apagar": true})."""
        arq = request.files.get("arquivo")
        with R._TRAVA:
            p = _p(pid)
            try:
                ch = R.personagem(p, cid)
                if (request.get_json(silent=True) or {}).get("apagar"):
                    R.tirar_cor_ref(p, ch, base_dir)
                elif arq and arq.filename:
                    R.guardar_cor_ref(p, ch, arq.read(), base_dir)
                else:
                    return _erro("Escolha a imagem colorida.")
            except R.ReactErro as exc:
                return _erro(str(exc))
            R.salvar(p, base_dir)
        return _ok()

    @app.route("/react-personagens/<pid>/personagem/<cid>/ref/<nome>", methods=["DELETE"])
    def react_ref_apagar(pid: str, cid: str, nome: str):
        with R._TRAVA:
            p = _p(pid)
            ch = R.personagem(p, cid)
            ch["refs"] = [r for r in ch.get("refs") or [] if r != nome]
            try:
                os.remove(os.path.join(R.pasta(pid, base_dir), "refs", secure_filename(nome)))
            except OSError:
                pass
            R.salvar(p, base_dir)
        return _ok()

    @app.route("/react-personagens/<pid>/arquivo/<pasta>/<nome>")
    def react_arquivo(pid: str, pasta: str, nome: str):
        _p(pid)
        if pasta not in ("refs", "cenario", "cenas"):
            abort(404)
        cam = os.path.join(R.pasta(pid, base_dir), pasta, secure_filename(nome))
        return send_file(cam) if os.path.isfile(cam) else ("não achei", 404)

    @app.route("/react-personagens/<pid>/pose/<cid>/<nome>")
    def react_pose_img(pid: str, cid: str, nome: str):
        p = _p(pid)
        ch = R.personagem(p, cid)
        ppid = (ch.get("pod") or {}).get("pid")
        if not ppid:
            abort(404)
        import personagens_pod as pp
        cam = os.path.join(pp._pasta(ppid, base_dir), "imagens", secure_filename(nome))
        return send_file(cam) if os.path.isfile(cam) else ("não achei", 404)

    # 🧲 navegador das imagens (o Brave do site + o script "Capturar links"): uma guia do Google Imagens por personagem
    @app.route("/react-personagens/<pid>/brave", methods=["POST"])
    def react_brave(pid: str):
        import navegador_imagens as nav
        from site_config import load_site_config
        p = _p(pid)
        c = request.get_json(silent=True) or {}
        alvo = [x for x in p["personagens"] if x["id"] in (c.get("cids") or [])] or [x for x in p["personagens"] if not x.get("refs")]
        alvo = alvo[:20]
        if not alvo:
            return _erro("Todos já têm imagem de referência (escolha quem buscar de novo).")
        site = request.host_url.rstrip("/")
        termos = {str(k): str(v) for k, v in (c.get("termos") or {}).items()}
        urls, chaves = [], []
        for x in alvo:
            termo = (termos.get(x["id"]) or x.get("busca_imagem") or f"{x['nome']} {x.get('obra') or ''}").strip()
            urls.append(nav.url_google(termo, nav.destino(site, pid, elenco={"t": "react", "n": x["id"]}, rotulo="🎭 " + x["nome"])))
            chaves.append("el:" + x["id"])
        cfg = load_site_config()
        if c.get("trocar"):
            nav.fechar_terminadas(pid, cfg)
        r = nav.abrir(base_dir, urls, cfg, chaves=chaves, pid=pid)
        return jsonify(dict(r, urls=urls)), (200 if r.get("ok") else 400)

    @app.before_request
    def _react_guias_do_script():
        """O script das guias manda pra /modelos-video/<id>/fotos-roteiro/… — quando o <id> é de um react, a foto vai
        pra referência do personagem (o script instalado não precisa mudar)."""
        m = _RE_GUIA.match(request.path)
        if not m or request.method != "POST":
            return None
        pid, acao = m.group(1), m.group(2)
        try:
            corpo = json.loads(request.get_data(as_text=True) or "{}")
        except ValueError:
            corpo = {}
        if acao == "guias":  # "➡ próximas guias" do script: fecha as prontas (as próximas abrem pela página)
            import navegador_imagens as nav
            from site_config import load_site_config
            r = nav.fechar_terminadas(pid, load_site_config())
            return jsonify({"ok": True, "abertas": 0, "fechadas": len(r["fechadas"]), "mantidas": r["mantidas"],
                            "msg": "No react, abra as próximas pela página do projeto (🧲 Buscar)."})
        if acao == "guia-feita":
            return jsonify({"ok": True})
        dest = corpo.get("elenco") if isinstance(corpo.get("elenco"), dict) else {}
        cid = str(dest.get("n") or "")
        with R._TRAVA:
            try:
                p = R.carregar(pid, base_dir)
                ch = R.personagem(p, cid)
                nome = R.baixar_ref(p, ch, str(corpo.get("url") or ""), base_dir, str(corpo.get("dados_b64") or ""))
            except R.ReactErro as exc:
                return jsonify({"erro": str(exc)}), 400
            except Exception as exc:  # noqa: BLE001
                return jsonify({"erro": f"não consegui baixar ({str(exc)[:120]})"}), 400
            R.log(p, f"🧲 imagem de referência de {ch['nome']}")
            R.salvar(p, base_dir)
        return jsonify({"ok": True, "midia": {"id": nome, "tipo": "foto"}})

    # ------------------------------------------------------------------ 📝 roteiro
    @app.route("/react-personagens/<pid>/roteiro", methods=["POST"])
    def react_roteiro_salvar(pid: str):
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            ids = {x["id"] for x in p["personagens"]}
            antes = {x["id"]: x for x in (p.get("roteiro") or {}).get("falas") or []}
            falas = []
            for f in c.get("falas") or []:
                t = R.segundos(f.get("t"))
                nome_c = next((x["nome"] for x in p["personagens"] if x["id"] == f.get("cid")), "")
                texto = R.limpar_texto_fala(f.get("texto"), nome_c)[:300]
                if t is None or not texto or f.get("cid") not in ids:
                    continue
                ex = f.get("expressao") if f.get("expressao") in R.EXPRESSOES else "neutro"
                dur = R.segundos(f.get("dur")) or R.duracao_fala(texto)
                reacoes = [{"cid": x["cid"], "expressao": x["expressao"]} for x in f.get("reacoes") or []
                           if isinstance(x, dict) and x.get("cid") in ids and x.get("cid") != f["cid"] and x.get("expressao") in R.EXPRESSOES][:2]
                falas.append({"id": str(f.get("id") or ("f" + uuid.uuid4().hex[:6]))[:12], "t": round(t, 2), "cid": f["cid"],
                              "texto": texto, "expressao": ex, "dur": round(max(0.8, min(15.0, dur)), 2),
                              "expressao_depois": f.get("expressao_depois") if f.get("expressao_depois") in R.EXPRESSOES and f.get("expressao_depois") != ex else "",
                              "cta": bool(f.get("cta")), "reacoes": reacoes, "duvida": str(f.get("duvida") or "")[:300],
                              "destaque": f.get("destaque") if f.get("destaque") in ("letra", "edicao") else ""})
                # 👂 o tempo que você mexeu fica; o que veio igual guarda o "já ouviu" (ou ainda vai ser ajustado)
                velha = antes.get(falas[-1]["id"])
                if velha and abs(float(velha["t"]) - falas[-1]["t"]) < 0.01:
                    falas[-1].update({k: velha[k] for k in ("ouviu", "t_ia") if k in velha})
                else:
                    falas[-1]["ouviu"] = True
            falas.sort(key=lambda x: x["t"])
            p["roteiro"] = dict(p.get("roteiro") or {}, falas=falas, editado=time.time())
            R.salvar(p, base_dir)
        return _ok(falas=len(falas))

    # ------------------------------------------------------------------ ⚡ intrigas (brigas, cenas, quem sai e volta)
    @app.route("/react-personagens/<pid>/eventos", methods=["POST"])
    def react_eventos(pid: str):
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            evs = R.salvar_eventos(p, c.get("eventos") or [])
            R.log(p, f"⚡ {len(evs)} evento(s) de intriga salvos")
            R.salvar(p, base_dir)
        return _ok(eventos=len(evs))

    @app.route("/react-personagens/<pid>/eventos/gerar", methods=["POST"])
    def react_eventos_gerar(pid: str):
        c = request.get_json(silent=True) or {}
        _p(pid)
        try:
            return _ok(**{k: v for k, v in R.gerar_cenas(pid, base_dir, c.get("ids") or None, str(c.get("pedido") or "")).items() if k != "ok"})
        except R.ReactErro as exc:
            return _erro(str(exc))

    @app.route("/react-personagens/<pid>/eventos/<eid>/arquivo", methods=["POST"])
    def react_evento_arquivo(pid: str, eid: str):
        from PIL import Image
        f = request.files.get("arquivo")
        if not f:
            return _erro("Escolha uma imagem.")
        with R._TRAVA:
            p = _p(pid)
            try:
                e = R.evento(p, eid)
                R.guardar_cena(p, e, Image.open(f.stream), base_dir, origem="enviada")
            except (R.ReactErro, OSError) as exc:
                return _erro(str(exc))
            R.salvar(p, base_dir)
        return _ok()

    @app.route("/react-personagens/<pid>/eventos/<eid>/versao", methods=["POST"])
    def react_evento_versao(pid: str, eid: str):
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            try:
                e = R.evento(p, eid)
            except R.ReactErro as exc:
                return _erro(str(exc))
            arq = str(c.get("arquivo") or "")
            if arq not in ((e.get("cena") or {}).get("versoes") or []):
                return _erro("Versão não encontrada.")
            e["cena"]["arquivo"] = arq
            R.salvar(p, base_dir)
        return _ok()

    # ------------------------------------------------------------------ 🔎 verificador de fatos
    @app.route("/react-personagens/<pid>/checagem/prompt")
    def react_checagem_prompt(pid: str):
        p = _p(pid)
        try:
            return _ok(prompt=R.prompt_checagem(p, request.args.get("alvo") or "tudo", request.args.get("foco") or ""))
        except R.ReactErro as exc:
            return _erro(str(exc))

    @app.route("/react-personagens/<pid>/checagem/rodar", methods=["POST"])
    def react_checagem_rodar(pid: str):
        p = _p(pid)
        c = request.get_json(silent=True) or {}
        alvo, foco = str(c.get("alvo") or "tudo"), str(c.get("foco") or "")
        motor = "gemini" if c.get("motor") == "gemini" else "claude"
        try:
            R.prompt_checagem(p, alvo, foco)  # erro de cara (sem elenco / sem roteiro)
        except R.ReactErro as exc:
            return _erro(str(exc))
        if motor == "gemini":
            import gemini_servico as gm
            if not gm.chave():
                return _erro("Falta a chave do Gemini — cole em qualquer 🔎 Checagem de um Modelo de vídeo (caixa “🔷 Gemini”).")
        rot = "🔎 Verificador de fatos" + (" (Gemini + Google)" if motor == "gemini" else " (IA do site)")
        return _rodar(pid, "checagem", rot, lambda: f"{R.checar(pid, base_dir, alvo, foco, motor)} correção(ões)") or _ok()

    @app.route("/react-personagens/<pid>/checagem/colar", methods=["POST"])
    def react_checagem_colar(pid: str):
        import json_ia
        c = request.get_json(silent=True) or {}
        try:
            r = json_ia.carregar(str(c.get("texto") or ""), aceitar_cortado=True)
        except ValueError as exc:
            return _erro(f"Não consegui ler o JSON: {exc}")
        with R._TRAVA:
            p = _p(pid)
            try:
                ch = R.aplicar_checagem(p, r, "📋 outra IA", str(c.get("alvo") or "tudo"))
            except R.ReactErro as exc:
                return _erro(str(exc))
            R.salvar(p, base_dir)
        return _ok(n=len(ch["itens"]))

    @app.route("/react-personagens/<pid>/checagem/<iid>/<acao>", methods=["POST"])
    def react_checagem_item(pid: str, iid: str, acao: str):
        if acao not in ("aplicar", "ignorar"):
            abort(404)
        with R._TRAVA:
            p = _p(pid)
            n = R.resolver_checagem(p, "*" if iid == "todas" else iid, acao)
            R.salvar(p, base_dir)
        return _ok(n=n)

    # ------------------------------------------------------------------ 🏠 cenário
    @app.route("/react-personagens/<pid>/cenario/gerar", methods=["POST"])
    def react_cenario_gerar(pid: str):
        _p(pid)
        quais = (request.get_json(silent=True) or {}).get("quais") or list(R.camadas_do_layout(R.carregar(pid, base_dir)))
        try:
            return _ok(**R.gerar_camadas(pid, base_dir, quais))
        except R.ReactErro as exc:
            return _erro(str(exc))

    @app.route("/react-personagens/<pid>/cenario/<camada>/arquivo", methods=["POST"])
    def react_cenario_upload(pid: str, camada: str):
        from PIL import Image
        if camada not in R.CAMADAS:
            abort(404)
        arq = request.files.get("arquivo")
        if not arq or not arq.filename:
            return _erro("Escolha a imagem.")
        try:
            im = Image.open(arq.stream)
            im.load()
        except Exception:  # noqa: BLE001
            return _erro("Isso não é uma imagem.")
        with R._TRAVA:
            p = _p(pid)
            try:
                R.guardar_camada(p, camada, im, base_dir, recortar=(None if request.form.get("verde") != "1" else True), origem="upload")
            except R.ReactErro as exc:
                return _erro(str(exc))
            R.log(p, f"📁 {R.ROTULO_CAMADA[camada]} enviado")
            R.salvar(p, base_dir)
        return _ok()

    @app.route("/react-personagens/<pid>/cenario/<camada>/referencia", methods=["POST"])
    def react_cenario_referencia(pid: str, camada: str):
        """🖼 A sua imagem como REFERÊNCIA (o Flow recria o lugar: 🏠 ambiente ou 🎨 anime). Com 'gerar', já manda."""
        from PIL import Image
        if camada not in R.CAMADAS:
            abort(404)
        c = request.get_json(silent=True) or {}
        arq = request.files.get("arquivo")
        modo = request.form.get("modo") or c.get("modo") or "ambiente"
        with R._TRAVA:
            p = _p(pid)
            cam = p["cenario"]["camadas"].setdefault(camada, {})
            if c.get("apagar"):
                cam.pop("ref", None)
                R.log(p, f"🖼 referência de {R.ROTULO_CAMADA[camada]} tirada")
            elif arq and arq.filename:
                try:
                    im = Image.open(arq.stream)
                    im.load()
                except Exception:  # noqa: BLE001
                    return _erro("Isso não é uma imagem.")
                try:
                    R.guardar_referencia(p, camada, im, modo, base_dir)
                except R.ReactErro as exc:
                    return _erro(str(exc))
                R.log(p, f"🖼 referência de {R.ROTULO_CAMADA[camada]} ({R.MODOS_REF[modo]})")
            elif cam.get("ref"):
                if modo not in R.MODOS_REF:
                    return _erro("Modo desconhecido.")
                cam["ref"]["modo"] = modo
            else:
                return _erro("Escolha a imagem.")
            R.salvar(p, base_dir)
        gerar = (request.form.get("gerar") or c.get("gerar")) in ("1", 1, True, "true")
        if gerar and not c.get("apagar"):
            try:
                return _ok(**R.gerar_camadas(pid, base_dir, [camada]))
            except R.ReactErro as exc:
                return _erro(str(exc))
        return _ok()

    # 🛋 quem senta onde
    @app.route("/react-personagens/<pid>/assentos", methods=["POST"])
    def react_assentos(pid: str):
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            try:
                sofas = R.guardar_assentos(p, c.get("sofas"))
            except R.ReactErro as exc:
                return _erro(str(exc))
            R.salvar(p, base_dir)
        return _ok(sofas=sofas)

    # 📌 marcações num segundo do vídeo
    @app.route("/react-personagens/<pid>/notas", methods=["POST"])
    def react_notas(pid: str):
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            try:
                if c.get("acao") == "apagar":
                    p["notas"] = [n for n in p.get("notas") or [] if n["id"] != c.get("id")]
                else:
                    R.nova_nota(p, c.get("t"), str(c.get("tipo") or "video"), str(c.get("texto") or ""),
                                [str(x) for x in c.get("cids") or []], bool(c.get("exata")), c.get("original", True) is not False)
            except R.ReactErro as exc:
                return _erro(str(exc))
            R.salvar(p, base_dir)
        return _ok()

    # 🍿 itens da mesa
    @app.route("/react-personagens/<pid>/objetos", methods=["POST"])
    def react_objetos(pid: str):
        import react_objetos as RO
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            try:
                if c.get("acao") == "novo":
                    RO.novo(p, c.get("nome"), c.get("en"), c.get("mesa") or "mesa")
                elif c.get("acao") == "editar":
                    RO.editar(p, str(c.get("id") or ""), c)
                if "mesa_por_sofa" in c:
                    p["mesa_por_sofa"] = bool(c["mesa_por_sofa"])
            except R.ReactErro as exc:
                return _erro(str(exc))
            R.salvar(p, base_dir)
        return _ok()

    @app.route("/react-personagens/<pid>/objetos/gerar", methods=["POST"])
    def react_objetos_gerar(pid: str):
        import react_objetos as RO
        _p(pid)
        try:
            return _ok(**RO.gerar(pid, base_dir, (request.get_json(silent=True) or {}).get("ids") or None))
        except R.ReactErro as exc:
            return _erro(str(exc))

    @app.route("/react-personagens/<pid>/objetos/<oid>/arquivo", methods=["POST"])
    def react_objeto_upload(pid: str, oid: str):
        import react_objetos as RO
        from PIL import Image
        arq = request.files.get("arquivo")
        if not arq or not arq.filename:
            return _erro("Escolha a imagem.")
        try:
            im = Image.open(arq.stream)
            im.load()
        except Exception:  # noqa: BLE001
            return _erro("Isso não é uma imagem.")
        with R._TRAVA:
            p = _p(pid)
            o = next((x for x in RO.objetos(p) if x["id"] == oid), None)
            if not o:
                return _erro("Item não encontrado.")
            try:
                RO.guardar(p, o, im, base_dir, origem="upload")
            except R.ReactErro as exc:
                return _erro(str(exc))
            R.salvar(p, base_dir)
        return _ok()

    @app.route("/react-personagens/<pid>/cenario/<camada>/outros")
    def react_cenario_outros(pid: str, camada: str):
        p = _p(pid)
        return _ok(itens=R.camadas_de_outros(p, camada, base_dir))

    @app.route("/react-personagens/<pid>/outro/<projeto>/<nome>")
    def react_cenario_outro_img(pid: str, projeto: str, nome: str):
        _p(pid)
        if not R.RE_ID.match(projeto):
            abort(404)
        cam = os.path.join(R.pasta(projeto, base_dir), "cenario", secure_filename(nome))
        return send_file(cam) if os.path.isfile(cam) else ("não achei", 404)

    @app.route("/react-personagens/<pid>/cenario/<camada>/reusar", methods=["POST"])
    def react_cenario_reusar(pid: str, camada: str):
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            try:
                R.usar_camada_de_outro(p, camada, str(c.get("projeto") or ""), str(c.get("arquivo") or ""), base_dir)
            except R.ReactErro as exc:
                return _erro(str(exc))
            R.salvar(p, base_dir)
        return _ok()

    @app.route("/react-personagens/<pid>/cenario/<camada>/versao", methods=["POST"])
    def react_cenario_versao(pid: str, camada: str):
        nome = str((request.get_json(silent=True) or {}).get("arquivo") or "")
        with R._TRAVA:
            p = _p(pid)
            cam = p["cenario"]["camadas"].get(camada) or {}
            if nome not in (cam.get("versoes") or []):
                return _erro("Versão não encontrada.")
            cam["arquivo"] = nome
            R.salvar(p, base_dir)
        return _ok()

    # ------------------------------------------------------------------ 🧍 personagens no Flow
    # ------------------------------------------------------------------ 🖼 thumbnail do react
    def _pecas_capa(p: Dict[str, Any]) -> Dict[str, Any]:
        cfg = R.capa_cfg(p)
        pc = R.capa_pecas(p, base_dir, cfg)
        import hashlib

        def url(cam: str) -> str:  # v84_244: a versão é o CONTEÚDO — a imagem só recarrega (e pisca) quando muda de verdade
            try:
                with open(cam, "rb") as fh:
                    v = hashlib.md5(fh.read()).hexdigest()[:10]
            except OSError:
                v = str(int(time.time()))
            return f"/react-personagens/{p['id']}/capa/arq/{os.path.basename(cam)}?v={v}"
        return {"fundo": url(pc["fundo"]), "W": R.CAPA_W, "H": R.CAPA_H, "tem_video": pc["tem_video"],
                "pecas": [dict({k: x[k] for k in ("chave", "nome", "x", "y", "w", "h", "oculta", "rot", "esp")}, img=url(x["arq"]),
                               ajustada=bool(x.get("ajustada"))) for x in pc["pecas"]],
                "cfg": {k: cfg[k] for k in ("cids", "exprs", "t", "lado", "seta", "quadro_off", "ocultas")} | {"imagem": bool(cfg.get("imagem"))}}

    @app.route("/react-personagens/<pid>/capa/estado", methods=["GET", "POST"])
    def react_capa_estado(pid: str):
        """A capa (o que entra, as caras, o quadro, o lado) e as peças pra arrastar. POST guarda o que mudou;
        {"pos": {chave: null}} volta uma peça pro automático; {"pos_limpar": true} volta todas."""
        c = request.get_json(silent=True) or {} if request.method == "POST" else {}
        with R._TRAVA:
            p = _p(pid)
            if c:
                cfg = R.capa_cfg(p)
                if c.get("pos_limpar"):
                    cfg["pos"], cfg["ordem"] = {}, []
                if isinstance(c.get("pos"), dict):
                    for k, v in c["pos"].items():
                        if v is None:
                            cfg["pos"].pop(k, None)
                        elif isinstance(v, dict):
                            novo = {kk: round(float(v[kk]), 1) for kk in ("x", "y", "w", "rot") if isinstance(v.get(kk), (int, float))}
                            if "esp" in v:
                                novo["esp"] = bool(v["esp"])
                            cfg["pos"][k] = dict(cfg["pos"].get(k) or {}, **novo)
                p["capa"] = R.capa_cfg(p, dict({k: v for k, v in c.items() if k not in ("pos", "pos_limpar")}, pos=cfg["pos"],
                                               ordem=c.get("ordem", cfg["ordem"])))
                R.salvar(p, base_dir)
        if c.get("leve"):  # só lugar/tamanho/giro/ordem/ocultar: a página já mostra — não remonta as peças (era o que travava)
            return _ok()
        try:
            return _ok(**_pecas_capa(_p(pid)))
        except Exception as exc:  # noqa: BLE001
            return _erro(f"não deu pra montar a capa: {exc}")

    @app.route("/react-personagens/<pid>/capa/arq/<nome>")
    def react_capa_arq(pid: str, nome: str):
        p = _p(pid)
        cam = os.path.join(R.pasta(p["id"], base_dir), "_capa", secure_filename(nome))
        return send_file(cam, max_age=0) if os.path.isfile(cam) else ("", 404)

    @app.route("/react-personagens/<pid>/capa/imagem", methods=["POST"])
    def react_capa_imagem(pid: str):
        """📤 uma imagem sua na capa (ou {"apagar": true})."""
        f = request.files.get("arquivo")
        with R._TRAVA:
            p = _p(pid)
            cfg = R.capa_cfg(p)
            if f and f.filename:
                try:
                    cfg["imagem"] = R.guardar_imagem_capa(p, f.filename, f.read(), base_dir)
                except R.ReactErro as exc:
                    return _erro(str(exc))
                cfg["pos"].pop("imagem", None)
            elif (request.get_json(silent=True) or {}).get("apagar") or request.form.get("apagar"):
                cfg["imagem"] = None
                cfg["quadro_off"] = False
            else:
                return _erro("Escolha a imagem.")
            p["capa"] = cfg
            R.salvar(p, base_dir)
        return _ok(**_pecas_capa(_p(pid)))

    @app.route("/react-personagens/<pid>/capa/previa.jpg")
    def react_capa_previa(pid: str):
        p = _p(pid)
        destino = os.path.join(R.pasta(pid, base_dir), "_capa_previa.jpg")
        try:
            R.compor_capa_react(p, base_dir, R.capa_cfg(p), destino)
        except Exception as exc:  # noqa: BLE001
            return f"não deu pra montar: {exc}", 500
        return send_file(destino, max_age=0)

    @app.route("/react-personagens/<pid>/capa", methods=["POST"])
    def react_capa(pid: str):
        _p(pid)
        c = request.get_json(silent=True) or {}
        dados = {k: c.get(k) for k in ("cids", "exprs", "t", "lado", "seta") if k in c}
        dados.update(texto=c.get("texto"), modo=c.get("modo"), pedido=c.get("pedido"),
                     estilo=c.get("estilo") if isinstance(c.get("estilo"), dict) else None)
        try:
            r = R.capa_react(pid, base_dir, dados)
        except R.ReactErro as exc:
            return _erro(str(exc))
        return _ok(**r)

    @app.route("/react-personagens/<pid>/pose/<cid>/virar", methods=["POST"])
    def react_pose_virar(pid: str, cid: str):
        """↔ esta pose veio virada pro outro lado."""
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            try:
                novo = R.marcar_virada(p, cid, os.path.basename(str(c.get("arquivo") or "")), base_dir)
            except R.ReactErro as exc:
                return _erro(str(exc))
            R.salvar(p, base_dir)
        return _ok(virada=novo)

    @app.route("/react-personagens/<pid>/pose/<cid>/conferir", methods=["POST"])
    def react_pose_conferir(pid: str, cid: str):
        """🧭 a IA confere pra que lado cada pose está virada."""
        _p(pid)
        try:
            return _ok(**R.conferir_lados(pid, cid, base_dir, todas=True))
        except R.ReactErro as exc:
            return _erro(str(exc))

    @app.route("/react-personagens/<pid>/biblia/arquivo", methods=["POST"])
    def react_biblia_arquivo(pid: str):
        """📖 a bíblia num .txt (ou .md) — junta no fim do que já tem."""
        f = request.files.get("arquivo")
        if not f:
            return _erro("Escolha o arquivo.")
        dados = f.read()
        txt = ""
        for cod in ("utf-8", "utf-16", "latin-1"):
            try:
                txt = dados.decode(cod)
                break
            except UnicodeDecodeError:
                continue
        with R._TRAVA:
            p = _p(pid)
            atual = str((p.get("biblia") or {}).get("texto") or "")
            R.definir_biblia(p, (atual + "\n\n" + txt).strip() if atual else txt)
            R.salvar(p, base_dir)
        return _ok(chars=len((p.get("biblia") or {}).get("texto") or ""), texto=(p.get("biblia") or {}).get("texto") or "")

    @app.route("/react-personagens/<pid>/pose/<cid>/refazer", methods=["POST"])
    def react_pose_refazer(pid: str, cid: str):
        c = request.get_json(silent=True) or {}
        _p(pid)
        try:
            R.refazer_pose(pid, cid, str(c.get("arquivo") or ""), str(c.get("pedido") or ""), base_dir)
        except (R.ReactErro, KeyError) as exc:
            return _erro(str(exc))
        return _ok()

    @app.route("/react-personagens/<pid>/poses/gerar", methods=["POST"])
    def react_poses(pid: str):
        p = _p(pid)
        c = request.get_json(silent=True) or {}
        cids = [x for x in c.get("cids") or [] if any(y["id"] == x for y in p["personagens"])] or [y["id"] for y in p["personagens"]]
        sem_ficha = [y["nome"] for y in p["personagens"] if y["id"] in cids and not y.get("aparencia_en") and not y.get("refs")]
        if sem_ficha and not c.get("mesmo_assim"):
            return _erro("Sem imagem de referência e sem aparência: " + ", ".join(sem_ficha)
                         + " — busque a imagem (🧲) ou complete a ficha (🤖) antes.")
        avisos = []
        for cid in cids:
            try:
                r = R.criar_poses(pid, cid, base_dir, refazer=bool(c.get("refazer")))
                if r.get("aviso"):
                    avisos.append(r["aviso"])
            except Exception as exc:  # noqa: BLE001
                avisos.append(f"{R.personagem(p, cid)['nome']}: {str(exc)[:200]}")
        return _ok(avisos=avisos)

    # ------------------------------------------------------------------ 👁 prévia e 🎬 editor
    @app.route("/react-personagens/<pid>/previa.jpg")
    def react_previa(pid: str):
        p = _p(pid)
        t = R.segundos(request.args.get("t"))
        destino = os.path.join(R.pasta(pid, base_dir), "previa.jpg")
        try:
            with R._TRAVA:
                R.previa(p, base_dir, destino, t)
        except Exception as exc:  # noqa: BLE001
            return f"não deu pra montar a prévia: {exc}", 500
        return send_file(destino, max_age=0)

    @app.route("/react-personagens/<pid>/pecas")
    def react_pecas(pid: str):
        p = _p(pid)
        return _ok(**R.pecas_para_editar(p, base_dir, R.segundos(request.args.get("t"))))

    @app.route("/react-personagens/<pid>/duplicar", methods=["POST"])
    def react_duplicar(pid: str):
        """⧉ duplica uma camada (mesa, sofá, TV, personagem) — ou {"apagar": chave} tira uma cópia."""
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            try:
                if c.get("apagar"):
                    R.apagar_copia(p, str(c["apagar"]))
                    nova = None
                else:
                    nova = R.duplicar(p, str(c.get("chave") or ""), base_dir)
            except R.ReactErro as exc:
                return _erro(str(exc))
            R.salvar(p, base_dir)
        return _ok(chave=nova)

    @app.route("/react-personagens/<pid>/pilha", methods=["POST"])
    def react_pilha(pid: str):
        """🗂 ordem das camadas / 👁 ocultas / 🔒 travadas."""
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            pil = R.guardar_pilha(p, c, base_dir)
            R.salvar(p, base_dir)
        return _ok(pilha=pil)

    @app.route("/react-personagens/<pid>/posicao", methods=["POST"])
    def react_posicao(pid: str):
        c = request.get_json(silent=True) or {}
        with R._TRAVA:
            p = _p(pid)
            try:
                if c.get("limpar_tudo"):
                    R.guardar_posicao(p, "*", None, base_dir)
                else:
                    R.guardar_posicao(p, str(c.get("chave") or ""), None if c.get("limpar") else c, base_dir)
            except R.ReactErro as exc:
                return _erro(str(exc))
            R.salvar(p, base_dir)
        return _ok()

    @app.route("/react-personagens/<pid>/quadro.jpg")
    def react_quadro(pid: str):
        """Um quadro do vídeo (pra TV do palco de ajuste)."""
        import subprocess
        p = _p(pid)
        video = R.video_local(p, base_dir)
        if not video:
            abort(404)
        t = R.segundos(request.args.get("t")) or 0.0
        destino = os.path.join(R.pasta(pid, base_dir), "_quadro.jpg")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", video, "-frames:v", "1",
                        "-vf", "scale=640:-2", destino], capture_output=True, timeout=60)
        return send_file(destino, max_age=0) if os.path.isfile(destino) else ("sem quadro", 404)

    @app.route("/react-personagens/<pid>/editor", methods=["POST"])
    def react_editor(pid: str):
        p = _p(pid)
        job_id = uuid.uuid4().hex[:12]
        jd = pasta_job(job_id)
        os.makedirs(jd, exist_ok=True)
        try:
            m = R.montar_editor(p, base_dir, jd)
        except R.ReactErro as exc:
            import shutil
            shutil.rmtree(jd, ignore_errors=True)
            return _erro(str(exc))
        job = {
            "job_id": job_id, "audio_path": m["audio"], "music_path": None, "music_volume": 0.18, "providers": [],
            "add_word_captions": False, "caption_style": {}, "status": "pronto_para_editar", "created_at": time.time(),
            "cancel_requested": False, "original_filename": f"🎭 {p.get('titulo') or 'React'}",
            "nome_projeto": f"🎭 {p.get('titulo') or 'React'}"[:60],
            "segments": [], "pending_segments": [m["segmento"]],
            "segment_previews": [{"ok": True, "thumbnail_url": f"/job/{job_id}/segment-thumb/0", "provider": "material",
                                  "label": "🎭 cenário do react", "media_type": "image"}],
            "overlays": m["overlays"], "total_duration": m["duracao"], "prompt": "", "whisper_skipped": True,
            "orientation": "16:9", "export_quality": "1080p",
            "react": {"projeto": pid, "falas": m["falas"], "avisos": m["avisos"]},
            "interval_seconds": 7,
        }
        criar_job(job_id, job)
        with R._TRAVA:
            p = _p(pid)
            p["editor"] = {"job_id": job_id, "quando": time.time(), "avisos": m["avisos"]}
            R.log(p, f"🎬 mandado pro editor ({len(m['overlays'])} camadas)" + (f" · ⚠ {len(m['avisos'])} aviso(s)" if m["avisos"] else ""))
            R.salvar(p, base_dir)
        return _ok(link=f"/job/{job_id}/edit-segments", avisos=m["avisos"], job_id=job_id)
