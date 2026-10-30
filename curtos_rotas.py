"""
Rotas da aba ⚡ Vídeos curtos (ver curtos.py).

`registrar(app, base_dir, transcrever, tts, limpar_tts, para_estudio)`:
  transcrever(audio, language=, word_timestamps=, info=) → segmentos do Whisper;
  tts(motor, texto, saida, **kw) → gera a fala;  limpar_tts(texto, motor) → texto limpo pro motor;
  para_estudio(dados) → job_id (cria o projeto do Estúdio e dispara as buscas das prévias).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from flask import abort, jsonify, redirect, render_template, request, send_file
from werkzeug.utils import secure_filename

import curtos as CT
import curtos_comentario as CC
import curtos_nichos as CN

TAREFAS: Dict[str, Dict[str, Any]] = {}
CB: Dict[str, Any] = {}  # os ganchos do app (transcrever, tts, para_estudio, trocar) — os testes trocam aqui
_TRAVA_T = threading.Lock()


def _pasta_pixabay(base_dir: str) -> str:
    return os.environ.get("CURTOS_PIXABAY_DIR") or os.path.join(base_dir, "pixabay_sons")


def registrar(app, base_dir: str, transcrever: Optional[Callable[..., Any]] = None, tts: Optional[Callable[..., Any]] = None,
              limpar_tts: Optional[Callable[[str, str], str]] = None,
              para_estudio: Optional[Callable[[Dict[str, Any]], str]] = None,
              rodar_pixabay: Optional[Callable[[Any], int]] = None,
              trocar_no_estudio: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
              marca_no_estudio: Optional[Callable[[str, Dict[str, Any]], None]] = None,
              exportar: Optional[Callable[..., str]] = None) -> None:
    CB.update(transcrever=transcrever, tts=tts, para_estudio=para_estudio, trocar=trocar_no_estudio, marca=marca_no_estudio,
              exportar=exportar, limpar=limpar_tts)

    def _ok(**kw: Any):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: str, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _corpo() -> Dict[str, Any]:
        return request.get_json(silent=True) or {}

    def _rodar(chave: str, rotulo: str, fn: Callable[[Callable[[str], None]], Any]):
        with _TRAVA_T:
            t = TAREFAS.get(chave)
            if t and not t.get("fim"):
                return _erro(f"Espere terminar: {t['rotulo']}", 409)
            TAREFAS[chave] = {"rotulo": rotulo, "inicio": time.time(), "fim": None, "erro": None, "msg": "", "prog": ""}

        def prog(m: str) -> None:
            TAREFAS[chave]["prog"] = str(m)[:300]

        def corpo():
            try:
                r = fn(prog)
                TAREFAS[chave]["msg"] = r if isinstance(r, str) else ""
            except Exception as exc:  # noqa: BLE001
                TAREFAS[chave]["erro"] = str(exc)[:600]
            finally:
                TAREFAS[chave]["fim"] = time.time()
        threading.Thread(target=corpo, daemon=True).start()
        return _ok(tarefa=True)

    def _canal(cid: str) -> Dict[str, Any]:
        try:
            return CT.carregar_canal(base_dir, cid)
        except CT.CurtoErro:
            abort(404)

    def _proj(pid: str) -> Dict[str, Any]:
        try:
            return CT.carregar(base_dir, pid)
        except CT.CurtoErro:
            abort(404)

    def _transcrever():
        if not CB["transcrever"]:
            raise CT.CurtoErro("O Whisper não está disponível aqui.")
        return CB["transcrever"]

    def _ia_ligada() -> bool:
        try:
            import ia_servico
            return ia_servico.motivo_desligado("curtos") is None
        except Exception:  # noqa: BLE001
            return False

    def _voz(p: Dict[str, Any], slug: str = "") -> Optional[Dict[str, Any]]:
        """A voz do TTS: a pedida, a do projeto ou a 1ª que o site tem."""
        try:
            import anime2d as A
            mp = (p.get("config") or {}).get("motor_perfil") or "xtts"
            slug = slug or (p.get("config") or {}).get("voz_tts") or ""
            if not slug:
                vs = A.vozes_disponiveis(mp)
                slug = vs[0]["slug"] if vs else ""
            return A.voz_por_slug(slug, mp) if slug else None
        except Exception:  # noqa: BLE001
            return None

    def _fazer_tudo(pid: str, slug: str, providers: Optional[List[str]], prog: Callable[[str], None]) -> str:
        """🚀 notícia → roteiro (IA) → voz guia (TTS) → alinhada → projeto no editor. Pula o que já está feito e em dia."""
        p = CT.carregar(base_dir, pid)
        if p.get("modelo") in CT.MODELOS_CLIPE:
            return _fazer_tudo_comentario(pid, slug, providers, prog)
        if any(f.get("estado") != "lida" for f in p["noticia"]["fontes"]):
            prog("📰 lendo a notícia…")
            CT.ler_noticias(base_dir, pid)
            p = CT.carregar(base_dir, pid)
        if not (p.get("roteiro") or {}).get("blocos"):
            prog("📝 escrevendo o roteiro no estilo do canal…")
            CT.gerar_roteiro(base_dir, pid)
            p = CT.carregar(base_dir, pid)
        chave = CT.chave_roteiro(p.get("roteiro"))
        g = p.get("gravacao") or {}
        if not (g.get("arquivo") and g.get("chave_roteiro") == chave):  # sem voz em dia: narra com o TTS
            if not CB["tts"]:
                raise CT.CurtoErro("O gerador de voz não está disponível aqui.")
            t = p.get("tts") or {}
            if not (t.get("arquivo") and t.get("chave") == chave and (not slug or t.get("voz") == slug)):
                voz = _voz(p, slug)
                if not voz:
                    raise CT.CurtoErro("Nenhuma voz de TTS cadastrada (🎙 Gerar voz → vozes) — ou escolha uma na seção 3.")
                with CT._TRAVA:
                    q = CT.carregar(base_dir, pid)
                    q["config"]["voz_tts"] = voz.get("slug") or slug
                    CT.salvar(base_dir, q)
                CT.gerar_voz_guia(base_dir, pid, CB["tts"], limpar_tts or (lambda t_, m: t_), voz, on_log=lambda m: prog("🎙 narrando — " + m))
                p = CT.carregar(base_dir, pid)
            prog("🎯 alinhando a narração ao roteiro (Whisper)…")
            CT.processar_gravacao(base_dir, pid, _transcrever(), os.path.join(CT.pasta(base_dir, pid), p["tts"]["arquivo"]), {},
                                  prog, fonte="guia")
        if not CB["para_estudio"]:
            raise CT.CurtoErro("O editor não está disponível aqui.")
        prog("🎬 montando no editor…")
        if providers:
            with CT._TRAVA:
                q = CT.carregar(base_dir, pid)
                q["config"]["providers"] = providers
                CT.salvar(base_dir, q)
        d = CT.montar_dados_editor(base_dir, pid, providers or None)
        job_id = CB["para_estudio"](d)
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            q["editor"] = {"job_id": job_id, "quando": time.time()}
            CT.salvar(base_dir, q)
        return f"pronto: {len(d['planos'])} planos em {d['dur']:.1f} s — abra no editor"

    def _trocar(pid: str, arquivo: str, op: Dict[str, Any], prog: Callable[[str], None]) -> str:
        p = CT.carregar(base_dir, pid)
        job_id = (p.get("editor") or {}).get("job_id")
        if not job_id:
            raise CT.CurtoErro("Esse vídeo ainda não foi pro editor (🎬 Montar no editor).")
        if not CB["trocar"]:
            raise CT.CurtoErro("O editor não está disponível aqui.")
        if arquivo:
            CT.processar_gravacao(base_dir, pid, _transcrever(), arquivo, op, prog, fonte="gravacao")
        elif not (p.get("gravacao") or {}).get("arquivo"):
            raise CT.CurtoErro("Grave ou suba o seu áudio antes.")
        prog("🔁 levando a voz nova pro editor (as mídias ficam)…")
        d = CT.montar_dados_editor(base_dir, pid)
        r = CB["trocar"](job_id, d)
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            q["editor"] = dict(q.get("editor") or {}, job_id=job_id, voz_trocada=time.time())
            CT.salvar(base_dir, q)
        return (f"voz trocada no editor: {r['mantidos']} trecho(s) com a mesma mídia"
                + (f", {r['novos']} novo(s) buscando mídia" if r["novos"] else "") + f" · {r['dur']:.1f} s")

    @app.context_processor
    def _ctx_curtos():
        return {"curtos_canais": lambda: CT.listar_canais(base_dir), "curtos_lista": lambda: CT.listar(base_dir)}

    # ------------------------------------------------------------------ hub
    def _roteiro_pronto(rid: str) -> Optional[Dict[str, Any]]:
        """✍ v84_283: veio do Roteiro de comentário (sem vídeo) → o roteiro entra como referência do curto."""
        if not rid:
            return None
        try:
            import roteiro_comentario as RC
            r = RC.carregar(base_dir, rid)
        except Exception:  # noqa: BLE001
            return None
        if not r.get("res"):
            return None
        return {"id": rid, "titulo": r.get("titulo") or "", "texto": RC.texto(r["res"], "en"), "segundos": int(round(RC.segundos(r["res"]))),
                "lingua_post": r.get("lingua_post") or "en", "historia": r.get("historia") or "",
                "link": (r.get("minerador") or {}).get("link") or "", "modelo": (r.get("minerador") or {}).get("modelo") or "",
                "explicativo": (((r.get("minerador") or {}).get("assunto_explicativo") or "") + "\n\n" + RC.texto(r["res"], "en")).strip()}

    def _hub(foco: str = ""):
        CT.garantir_canais_prontos(base_dir)
        try:
            import anime2d as A
            vozes = A.vozes_disponiveis("xtts")
            vozes_en = A.vozes_disponiveis("chatterbox_turbo")
        except Exception:  # noqa: BLE001
            vozes, vozes_en = [], []
        return render_template("curtos.html", canais=CT.listar_canais(base_dir), projetos=CT.listar(base_dir), modos_anime=CT.MODOS_ANIME,
                               prontos=CT.perfis_prontos(), vozes=vozes, vozes_ingles=vozes_en, foco=foco, modelos=CT.MODELOS,
                               linguas=CT.LINGUAS, proporcoes=CT.PROPORCOES, modos_midia=CC.MODOS_MIDIA, estilos_ia=CT.ESTILOS_IA,
                               nichos=CN.nichos(), canais_nicho=CN.canais_de_nicho(base_dir), canal_sel=request.args.get("canal") or "",
                               tema_sel=request.args.get("tema") or "",
                               roteiro_pronto=_roteiro_pronto(request.args.get("roteiro") or ""),
                               erro=request.args.get("erro"))

    @app.route("/curtos", methods=["GET"])
    def curtos_hub():
        return _hub()

    # ------------------------------------------------------------------ ⚡ geração rápida (v84_258)
    def _rodar_lote(lid: str, prog: Callable[[str], None]) -> str:
        """As ideias, uma por uma: vídeo 📚 no Flow → roteiro → 1 take → editor → as mídias (Flow) → EXPORTA. Sem clicar em nada."""
        lote = CN.carregar_lote(base_dir, lid)
        op, cid = lote["opcoes"], lote["canal"]
        n = len(lote["itens"])
        lote["parado"], lote["fim"] = False, None
        CN.salvar_lote(base_dir, lote)
        for rodada in range(CN.TENTATIVAS_POR_IDEIA):  # 🔁 no fim, as que deram erro tentam de novo (até 3 vezes cada)
            fila = [(k, it) for k, it in enumerate(lote["itens"], 1) if it["estado"] in ("na fila", "fazendo")
                    or (it["estado"] == "erro" and int(it.get("tentativas") or 0) < CN.TENTATIVAS_POR_IDEIA)]
            if not fila or _lote_parado(lid):
                break
            for k, it in fila:
                if _lote_parado(lid):
                    break
                _fazer_item(lote, k, n, it, op, cid, prog, lid)
        lote["fim"] = time.time() if not _lote_parado(lid) else None
        lote["parado"] = _lote_parado(lid)
        CN.salvar_lote(base_dir, lote)
        ok = sum(1 for x in lote["itens"] if x["estado"] == "pronto")
        return (f"⏹ parado: {ok} de {n} pronto(s)" if lote["parado"] else f"{ok} de {n} vídeo(s) exportado(s)")

    _PARAR: Dict[str, bool] = {}

    def _lote_parado(lid: str) -> bool:
        return bool(_PARAR.get(lid))

    def _fazer_item(lote: Dict[str, Any], k: int, n: int, it: Dict[str, Any], op: Dict[str, Any], cid: str,
                    prog: Callable[[str], None], lid: str) -> None:
        rot = f"{k}/{n} · {it['titulo_en'][:50]}"
        if rot:

            def log(m: str, it=it, rot=rot) -> None:
                if _lote_parado(lid):
                    raise CT.CurtoErro("⏹ parado por você")
                it["msg"] = str(m)[:200]
                prog(f"{rot} — {m}")
            try:
                it.update(estado="fazendo", erro=None, tentativas=int(it.get("tentativas") or 0) + 1)
                CN.salvar_lote(base_dir, lote)
                p = CN.video_da_ideia(base_dir, cid, it["ideia"], op["proporcao"], op.get("voz") or "")
                it["pid"] = p["id"]
                with CT._TRAVA:
                    q = CT.carregar(base_dir, p["id"])
                    q["config"].update(flow_video=bool(op.get("video")), takes=1, qualidade=op["qualidade"], midia="flow",
                                       providers=["flow"])  # 🖼 só Flow: nenhuma foto da internet
                    CT.salvar(base_dir, q)
                CN.salvar_lote(base_dir, lote)
                _fazer_tudo(p["id"], op.get("voz") or "", None, log)
                if not CB.get("exportar"):
                    raise CT.CurtoErro("A exportação automática não está disponível aqui.")
                job_id = (CT.carregar(base_dir, p["id"]).get("editor") or {}).get("job_id")
                arq = CB["exportar"](job_id, op["qualidade"], log)
                with CT._TRAVA:
                    q = CT.carregar(base_dir, p["id"])
                    q["exportado"] = {"arquivo": arq, "quando": time.time(), "qualidade": op["qualidade"], "job_id": job_id}
                    CT.salvar(base_dir, q)
                it.update(estado="pronto", arquivo=arq, msg="✅ exportado", titulos=CN.titulos_do_projeto(CT.carregar(base_dir, p["id"])))
            except Exception as exc:  # noqa: BLE001  (uma ideia que falhou não para as outras)
                if _lote_parado(lid):
                    it.update(estado="na fila", msg="⏹ parado", tentativas=max(0, int(it.get("tentativas") or 1) - 1))
                else:
                    it.update(estado="erro", erro=str(exc)[:400])
            CN.salvar_lote(base_dir, lote)
            import gc
            gc.collect()  # 🧹 solta a memória do vídeo anterior (Whisper, áudio, quadros) antes do próximo

    @app.route("/curtos/canal/<cid>/rapido", methods=["POST"])
    def curtos_rapido(cid: str):
        _canal(cid)
        b = _corpo()
        ids = b.get("ideias")
        if ids == "todas" or not ids:
            ids = [i["id"] for i in CN.ideias(base_dir, cid) if not i.get("pid")]
        try:
            lote = CN.criar_lote(base_dir, cid, [str(x) for x in ids][:50], bool(b.get("video")), str(b.get("qualidade") or "1080p"),
                                 str(b.get("proporcao") or "9:16"), str(b.get("voz") or ""))
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        r = _rodar("lote:" + lote["id"], f"⚡ geração rápida ({len(lote['itens'])} vídeo(s))", lambda prog: _rodar_lote(lote["id"], prog))
        if isinstance(r, tuple):
            return r
        return _ok(lote=lote["id"])

    @app.route("/curtos/canal/<cid>/lotes", methods=["GET"])
    def curtos_lotes(cid: str):
        _canal(cid)
        return _ok(lotes=[dict(lt, tarefa=TAREFAS.get("lote:" + lt["id"])) for lt in CN.lotes_do_canal(base_dir, cid)[:10]])

    @app.route("/curtos/lote/<lid>", methods=["GET"])
    def curtos_lote(lid: str):
        try:
            lt = CN.carregar_lote(base_dir, lid)
        except CT.CurtoErro:
            abort(404)
        return _ok(lote=lt, tarefa=TAREFAS.get("lote:" + lid))

    @app.route("/curtos/lote/<lid>/parar", methods=["POST"])
    def curtos_lote_parar(lid: str):
        """⏹ para o lote (o vídeo que está sendo feito para no próximo passo; volta pra fila). O vigia não retoma mais."""
        try:
            lt = CN.carregar_lote(base_dir, lid)
        except CT.CurtoErro:
            abort(404)
        _PARAR[lid] = True
        lt["parado"] = True
        CN.salvar_lote(base_dir, lt)
        return _ok()

    def _retomar(lid: str, zerar_erros: bool = True):
        lt = CN.carregar_lote(base_dir, lid)
        for it in lt["itens"]:
            if it["estado"] == "fazendo" or (zerar_erros and it["estado"] == "erro"):
                it["estado"] = "na fila"
                if zerar_erros:
                    it["tentativas"] = 0
        lt["parado"] = False
        CN.salvar_lote(base_dir, lt)
        _PARAR.pop(lid, None)
        return _rodar("lote:" + lid, "⚡ geração rápida (retomando)", lambda prog: _rodar_lote(lid, prog))

    def _vigia_lotes() -> None:
        """🔁 o lote parou porque o site reiniciou/caiu? Retoma sozinho (a não ser que você tenha parado)."""
        time.sleep(float(os.environ.get("CURTOS_VIGIA_INICIO_S") or 25))
        while True:
            try:
                for lt in CN.lotes_pendentes(base_dir):
                    t = TAREFAS.get("lote:" + lt["id"])
                    if (t and not t.get("fim")) or _lote_parado(lt["id"]):
                        continue
                    if any(x for k, x in TAREFAS.items() if k.startswith("lote:") and not x.get("fim")):
                        break  # um lote por vez: o próximo espera este terminar
                    _retomar(lt["id"], zerar_erros=False)
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(60)

    import sys as _sys
    if "pytest" not in _sys.modules and os.environ.get("CURTOS_VIGIA", "1") != "0":
        threading.Thread(target=_vigia_lotes, daemon=True, name="vigia-lotes").start()

    @app.route("/curtos/lote/<lid>/retomar", methods=["POST"])
    def curtos_lote_retomar(lid: str):
        try:
            CN.carregar_lote(base_dir, lid)
        except CT.CurtoErro:
            abort(404)
        r = _retomar(lid)
        return r if isinstance(r, tuple) else _ok()

    @app.route("/curtos/lote/<lid>/titulos.txt", methods=["GET"])
    def curtos_lote_titulos(lid: str):
        try:
            lt = CN.carregar_lote(base_dir, lid)
        except CT.CurtoErro:
            abort(404)
        from flask import Response
        return Response(CN.texto_dos_titulos(base_dir, lt), mimetype="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=titulos_{lid}.txt"} if request.args.get("baixar") else {})

    @app.route("/curtos/lote/<lid>/todos.zip", methods=["GET"])
    def curtos_lote_zip(lid: str):
        """⬇ todos os vídeos prontos do lote + os títulos (o zip é só "guardado", sem recomprimir: vídeo já é comprimido)."""
        import zipfile
        try:
            lt = CN.carregar_lote(base_dir, lid)
        except CT.CurtoErro:
            abort(404)
        prontos = [it for it in lt["itens"] if it["estado"] == "pronto" and it.get("arquivo") and os.path.isfile(it["arquivo"])]
        if not prontos:
            abort(404)
        cam = os.path.join(tempfile.mkdtemp(prefix="lote_"), f"videos_{lid}.zip")
        with zipfile.ZipFile(cam, "w", zipfile.ZIP_STORED) as z:
            for k, it in enumerate(prontos, 1):
                z.write(it["arquivo"], f"{k:02d}_{secure_filename(it['titulo_en'])[:60] or 'video'}.mp4")
            z.writestr("titulos.txt", CN.texto_dos_titulos(base_dir, lt))
        return send_file(cam, as_attachment=True, download_name=f"videos_{lt.get('canal_nome') or lid}.zip")

    @app.route("/curtos/<pid>/video.mp4", methods=["GET"])
    def curto_video_exportado(pid: str):
        p = _proj(pid)
        arq = (p.get("exportado") or {}).get("arquivo")
        if not arq or not os.path.isfile(arq):
            jid = (p.get("editor") or {}).get("job_id")
            return redirect(f"/job/{jid}/edit-segments") if jid else abort(404)
        return send_file(arq, as_attachment=bool(request.args.get("baixar", "1") != "0"),
                         download_name=f"{secure_filename(p.get('titulo') or 'video')[:60] or 'video'}.mp4", conditional=True)

    # ------------------------------------------------------------------ 💡 nichos e ideias (v84_256)
    @app.route("/curtos/nicho/<chave>/criar", methods=["POST"])
    def curtos_nicho_criar(chave: str):
        try:
            c = CN.criar_canal_do_nicho(base_dir, chave)
        except CT.CurtoErro as exc:
            return redirect(f"/curtos/modelo/explicativo?erro={exc}")
        return redirect(f"/curtos/modelo/explicativo?canal={c['id']}#nichos")

    @app.route("/curtos/canal/<cid>/marca", methods=["POST"])
    def curtos_canal_marca(cid: str):
        """🏷 o @ do canal (a marca por cima do vídeo) — vale pros vídeos do canal que ainda não foram exportados."""
        b = _corpo()
        with CT._TRAVA:
            c = _canal(cid)
            texto = " ".join(str(b.get("texto") or "").split())[:60]
            if texto and not texto.startswith("@"):
                texto = "@" + texto.lstrip("@")
            m = dict(CT.normalizar_marca(c["perfil"].get("marca"), c["nome"]), texto=texto or "@seucanal")
            if "ativa" in b:
                m["ativa"] = bool(b["ativa"])
            c["perfil"]["marca"] = CT.normalizar_marca(m)
            CT.salvar_canal(base_dir, c)
        return _ok(marca=c["perfil"]["marca"])

    @app.route("/curtos/canal/<cid>/ideias", methods=["GET", "POST"])
    def curtos_ideias(cid: str):
        _canal(cid)
        if request.method == "GET":
            return _ok(ideias=CN.ideias(base_dir, cid), tarefa=TAREFAS.get("ideias:" + cid))
        b = _corpo()
        if not _ia_ligada():
            return _erro("A IA está desligada (ou o recurso “⚡ Vídeos curtos” desligado em /ia).")
        try:
            n = int(b.get("n") or 10)
        except (TypeError, ValueError):
            n = 10
        pedido = str(b.get("pedido") or "")[:400]
        return _rodar("ideias:" + cid, "💡 pensando em ideias", lambda prog: f"{len(CN.gerar_ideias(base_dir, cid, n, pedido=pedido))} ideia(s) nova(s)")

    @app.route("/curtos/canal/<cid>/ideia/<iid>/video", methods=["POST"])
    def curtos_ideia_video(cid: str, iid: str):
        _canal(cid)
        b = _corpo()
        try:
            p = CN.video_da_ideia(base_dir, cid, iid, str(b.get("proporcao") or "9:16"), str(b.get("voz") or ""))
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        if b.get("tudo"):
            _rodar(p["id"], "🚀 fazendo tudo", lambda prog: _fazer_tudo(p["id"], str(b.get("voz") or ""), None, prog))
        return _ok(pid=p["id"], link=f"/curtos/{p['id']}")

    @app.route("/curtos/modelo/<modelo>", methods=["GET"])
    def curtos_hub_modelo(modelo: str):
        if modelo not in CT.MODELOS:
            abort(404)
        return _hub(modelo)

    @app.route("/curtos/canal/novo", methods=["POST"])
    def curtos_canal_novo():
        try:
            c = CT.criar_canal(base_dir, request.form.get("nome") or "", request.form.get("idioma") or "")
        except CT.CurtoErro as exc:
            return redirect(f"/curtos?erro={exc}")
        pronto = CT.perfis_prontos().get(request.form.get("pronto") or "")
        if pronto:
            c["perfil"] = CT.aplicar_perfil(c["perfil"], pronto.get("perfil") or {})
            c["perfil_ia"] = True
            c["idioma"] = c.get("idioma") or pronto.get("idioma") or ""
            c["perfil_origem"] = pronto.get("nome") or ""
            CT.salvar_canal(base_dir, c)
        arq = request.files.get("perfil")
        if arq and arq.filename:
            try:
                c["perfil"] = CT.aplicar_perfil(c["perfil"], json.loads(arq.read().decode("utf-8", "replace")).get("perfil") or {})
                CT.salvar_canal(base_dir, c)
            except Exception:  # noqa: BLE001
                pass
        return redirect(f"/curtos/canal/{c['id']}")

    @app.route("/curtos/novo", methods=["POST"])
    def curtos_novo():
        f = request.form
        if f.get("modelo") in CT.MODELOS_CLIPE:
            return _novo_comentario()
        try:
            p = CT.criar(base_dir, f.get("canal_id") or "", f.get("titulo") or "", (f.get("links") or "").split(),
                         f.get("texto") or "")
        except CT.CurtoErro as exc:
            return redirect(f"/curtos?erro={exc}")
        try:
            dur = int(float(f.get("duracao") or 0))
            if dur:
                p["config"]["duracao_alvo_s"] = max(10, min(180, dur))
        except ValueError:
            pass
        if f.get("modo_anime") in CT.MODOS_ANIME:
            p["config"]["modo_anime"] = f["modo_anime"]
            if f.get("modo_anime") != "nao":
                p["config"]["providers"] = list(dict.fromkeys(CT.PROVIDERS_PADRAO + ["animepexels"]))
        p["config"]["anime_obras"] = " ".join(str(f.get("anime_obras") or "").split())[:300]
        if f.get("proporcao") in CT.PROPORCOES:
            p["config"]["proporcao"] = f["proporcao"]
        CT.salvar(base_dir, p)
        if f.get("tudo"):
            slug = f.get("voz") or ""
            _rodar(p["id"], "🚀 fazendo tudo", lambda prog: _fazer_tudo(p["id"], slug, None, prog))
        elif p["noticia"]["fontes"]:
            _rodar(p["id"], "📰 lendo a notícia", lambda prog: f"{CT.ler_noticias(base_dir, p['id'])} matéria(s) lida(s)")
        return redirect(f"/curtos/{p['id']}")

    # ------------------------------------------------------------------ 🧬 canal
    @app.route("/curtos/canal/<cid>", methods=["GET"])
    def curtos_canal(cid: str):
        c = _canal(cid)
        import dp_destaques
        import dp_legendas
        return render_template("curto_canal.html", c=c, layouts=CT.LAYOUTS, tipos_sfx={k: v["nome"] for k, v in CT.TIPOS_SFX.items()},
                               funcoes=CT.FUNCOES_BLOCO, estilos_legenda=dp_legendas.ESTILOS,
                               destaques=sorted(dp_destaques.catalogo().keys()), ia=_ia_ligada(), modos_anime=CT.MODOS_ANIME)

    def _canal_tela(c: Dict[str, Any]) -> Dict[str, Any]:
        out = json.loads(json.dumps(c))
        for r in out.get("referencias") or []:
            (r.get("transcricao") or {}).pop("palavras", None)
        out["metricas"] = CT.metricas_canal(c)
        out["tarefa"] = TAREFAS.get(c["id"])
        out["perfil_texto"] = CT.texto_do_perfil(c["perfil"])
        return out

    @app.route("/curtos/canal/<cid>/estado", methods=["GET"])
    def curtos_canal_estado(cid: str):
        return jsonify(_canal_tela(_canal(cid)))

    @app.route("/curtos/canal/<cid>/renomear", methods=["POST"])
    def curtos_canal_renomear(cid: str):
        with CT._TRAVA:
            c = _canal(cid)
            nome = " ".join(str(_corpo().get("nome") or "").split())[:80]
            if nome:
                c["nome"] = nome
            if "idioma" in _corpo():
                c["idioma"] = str(_corpo().get("idioma") or "")[:8]
            CT.salvar_canal(base_dir, c)
        return _ok()

    @app.route("/curtos/canal/<cid>/refs", methods=["POST"])
    def curtos_canal_refs(cid: str):
        novos: List[str] = []
        try:
            with CT._TRAVA:
                c = _canal(cid)
                tmpd = tempfile.mkdtemp(prefix="curto_ref_")
                for arq in request.files.getlist("videos"):
                    if not arq or not arq.filename:
                        continue
                    nome = secure_filename(arq.filename) or "video.mp4"
                    if os.path.splitext(nome)[1].lower() not in CT.EXT_VIDEO:
                        continue
                    cam = os.path.join(tmpd, nome)
                    arq.save(cam)
                    novos.append(CT.adicionar_referencia(base_dir, c, arquivo=cam, titulo=os.path.splitext(arq.filename)[0])["id"])
                for u in (request.form.get("links") or "").split():
                    if u.startswith("http"):
                        novos.append(CT.adicionar_referencia(base_dir, c, link=u)["id"])
                CT.salvar_canal(base_dir, c)
                shutil.rmtree(tmpd, ignore_errors=True)
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        if not novos:
            return _erro("Mande vídeos (.mp4, .mov, .webm…) ou links.")
        return _ok(novos=novos)

    @app.route("/curtos/canal/<cid>/midia", methods=["POST"])
    def curtos_canal_midia(cid: str):
        feitos = []
        with CT._TRAVA:
            c = _canal(cid)
            tmpd = tempfile.mkdtemp(prefix="curto_k_")
            for arq in request.files.getlist("arquivos"):
                nome = secure_filename(arq.filename or "") if arq else ""
                tipo = CT.tipo_arquivo(nome)
                if not tipo:
                    continue
                cam = os.path.join(tmpd, nome)
                arq.save(cam)
                feitos.append(CT.adicionar_midia_canal(base_dir, c, cam, tipo, request.form.get("descricao") or os.path.splitext(arq.filename)[0])["id"])
            CT.salvar_canal(base_dir, c)
            shutil.rmtree(tmpd, ignore_errors=True)
        return _ok(novos=feitos) if feitos else _erro("Mande fotos ou vídeos.")

    @app.route("/curtos/canal/<cid>/midia/<mid>", methods=["POST"])
    def curtos_canal_midia_editar(cid: str, mid: str):
        b = _corpo()
        with CT._TRAVA:
            c = _canal(cid)
            m = next((x for x in c.get("midias") or [] if x["id"] == mid), None)
            if not m:
                return _erro("Mídia não encontrada.", 404)
            if b.get("apagar"):
                cam = os.path.join(CT.pasta_canal(base_dir, cid), m.get("arquivo") or "_")
                if os.path.isfile(cam):
                    os.remove(cam)
                c["midias"].remove(m)
            elif "descricao" in b:
                m["descricao"] = " ".join(str(b["descricao"] or "").split())[:400]
            CT.salvar_canal(base_dir, c)
        return _ok()

    @app.route("/curtos/canal/<cid>/ref/<rid>/apagar", methods=["POST"])
    def curtos_canal_ref_apagar(cid: str, rid: str):
        with CT._TRAVA:
            c = _canal(cid)
            c["referencias"] = [r for r in c["referencias"] if r["id"] != rid]
            shutil.rmtree(os.path.join(CT.pasta_canal(base_dir, cid), "refs", os.path.basename(rid)), ignore_errors=True)
            CT.salvar_canal(base_dir, c)
        return _ok()

    @app.route("/curtos/canal/<cid>/analisar", methods=["POST"])
    def curtos_canal_analisar(cid: str):
        c = _canal(cid)
        b = _corpo()
        rids = [r["id"] for r in c["referencias"] if (b.get("rids") and r["id"] in b["rids"]) or
                (not b.get("rids") and r.get("estado") in ("na fila", "erro", "medida"))]
        if not rids:
            return _erro("Nada pra analisar (todas já estão prontas — use 🔁 em uma pra refazer).")
        usar_ia = bool(b.get("ia", True)) and _ia_ligada()

        def fn(prog):
            erros = []
            for k, rid in enumerate(rids):
                prog(f"{k + 1}/{len(rids)} · {rid}")
                try:
                    CT.analisar_referencia(base_dir, cid, rid, _transcrever(), None, usar_ia,
                                           on_log=lambda m, k=k: prog(f"{k + 1}/{len(rids)} · {m}"))
                except Exception as exc:  # noqa: BLE001
                    erros.append(f"{rid}: {str(exc)[:120]}")
            if usar_ia and len(rids) - len(erros) > 0:
                prog("🧬 juntando o perfil do canal…")
                try:
                    CT.gerar_perfil(base_dir, cid)
                except CT.CurtoErro as exc:
                    erros.append(str(exc)[:200])
            else:
                with CT._TRAVA:
                    cc = CT.carregar_canal(base_dir, cid)
                    cc["perfil"] = CT.perfil_das_medidas(cc)
                    cc["metricas"] = CT.metricas_canal(cc)
                    CT.salvar_canal(base_dir, cc)
            return f"{len(rids) - len(erros)} de {len(rids)} vídeo(s) analisados" + (" · ❌ " + " · ".join(erros) if erros else "") + \
                ("" if usar_ia else " · (sem IA: só as medidas — ligue a IA em /ia ou use o 📋 prompt)")
        return _rodar(cid, "🔍 analisando os vídeos", fn)

    @app.route("/curtos/canal/<cid>/arquivo/<path:caminho>", methods=["GET"])
    def curtos_canal_arquivo(cid: str, caminho: str):
        _canal(cid)
        raiz = os.path.realpath(CT.pasta_canal(base_dir, cid))
        cam = os.path.realpath(os.path.join(raiz, caminho))
        if not cam.startswith(raiz + os.sep) or not os.path.isfile(cam):
            abort(404)
        return send_file(cam, conditional=True)

    @app.route("/curtos/canal/<cid>/perfil/gerar", methods=["POST"])
    def curtos_perfil_gerar(cid: str):
        _canal(cid)
        return _rodar(cid, "🧬 escrevendo o perfil do canal", lambda prog: (CT.gerar_perfil(base_dir, cid), "perfil pronto")[1])

    @app.route("/curtos/canal/<cid>/perfil/medidas", methods=["POST"])
    def curtos_perfil_medidas(cid: str):
        with CT._TRAVA:
            c = _canal(cid)
            c["perfil"] = CT.perfil_das_medidas(c)
            CT.salvar_canal(base_dir, c)
        return _ok(perfil=c["perfil"])

    @app.route("/curtos/canal/<cid>/perfil/prompt", methods=["GET"])
    def curtos_perfil_prompt(cid: str):
        return _ok(prompt=CT.prompt_perfil(_canal(cid)))

    @app.route("/curtos/canal/<cid>/perfil", methods=["POST"])
    def curtos_perfil_salvar(cid: str):
        b = _corpo()
        try:
            with CT._TRAVA:
                c = _canal(cid)
                if b.get("resposta"):
                    c["perfil"] = CT.aplicar_perfil(c["perfil"], b["resposta"])
                    c["perfil_ia"] = True
                elif isinstance(b.get("perfil"), dict):
                    c["perfil"] = CT.normalizar_perfil(b["perfil"])
                else:
                    return _erro("Nada pra salvar.")
                CT.salvar_canal(base_dir, c)
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        return _ok(perfil=c["perfil"])

    @app.route("/curtos/canal/<cid>/perfil.json", methods=["GET"])
    def curtos_perfil_exportar(cid: str):
        c = _canal(cid)
        dados = {"formato": "besteditor-curtos-perfil", "versao": 1, "nome": c["nome"], "idioma": c.get("idioma") or "",
                 "perfil": c["perfil"], "metricas": CT.metricas_canal(c)}
        tmp = os.path.join(tempfile.gettempdir(), f"perfil_{cid}.json")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=1)
        return send_file(tmp, as_attachment=True, download_name=f"perfil_{CT.norm(c['nome']) or 'canal'}.json")

    @app.route("/curtos/canal/<cid>/perfil/importar", methods=["POST"])
    def curtos_perfil_importar(cid: str):
        arq = request.files.get("arquivo")
        if not arq or not arq.filename:
            return _erro("Escolha o arquivo .json do perfil.")
        try:
            d = json.loads(arq.read().decode("utf-8", "replace"))
            with CT._TRAVA:
                c = _canal(cid)
                c["perfil"] = CT.aplicar_perfil(c["perfil"], d.get("perfil") if isinstance(d.get("perfil"), dict) else d)
                if d.get("idioma") and not c.get("idioma"):
                    c["idioma"] = str(d["idioma"])[:8]
                CT.salvar_canal(base_dir, c)
        except (ValueError, CT.CurtoErro) as exc:
            return _erro(f"Arquivo inválido: {exc}")
        return _ok()

    @app.route("/curtos/canal/<cid>/excluir", methods=["POST"])
    def curtos_canal_excluir(cid: str):
        _canal(cid)
        CT.excluir_canal(base_dir, cid)
        return redirect("/curtos")

    # ------------------------------------------------------------------ ⚡ projeto
    @app.route("/curtos/<pid>", methods=["GET"])
    def curto_pagina(pid: str):
        p = _proj(pid)
        if p.get("modelo") in CT.MODELOS_CLIPE:
            return _pagina_comentario(p)
        try:
            import anime2d as A
            vozes = A.vozes_disponiveis((p.get("config") or {}).get("motor_perfil") or "xtts")
        except Exception:  # noqa: BLE001
            vozes = []
        import prompt_builder
        return render_template("curto_detalhe.html", p=p, canais=CT.listar_canais(base_dir), layouts=CT.LAYOUTS,
                               tipos_sfx={k: v["nome"] for k, v in CT.TIPOS_SFX.items()}, funcoes=CT.FUNCOES_BLOCO,
                               efeitos=CT.EFEITOS_CURTOS, entradas=CT.ENTRADAS_CURTOS, vozes=vozes, ia=_ia_ligada(),
                               modos_anime=CT.MODOS_ANIME, emocoes=CT.EMOCOES_ANIME, anime=CT.anime_do(base_dir, p),
                               todos_providers=prompt_builder.DEFAULT_PROVIDERS, providers_padrao=CT.PROVIDERS_PADRAO,
                               tem_tts=bool(CB["tts"]), tem_whisper=bool(CB["transcrever"]),
                               proporcoes=CT.PROPORCOES, fontes_dp=_fontes_dp(), posicoes_marca=CT.MARCA_POSICOES)

    @app.route("/curtos/<pid>/estado", methods=["GET"])
    def curto_estado(pid: str):
        p = _proj(pid)
        out = CT.resumo_tela(base_dir, p)
        out["tarefa"] = TAREFAS.get(pid)
        out["perfil"] = CT.perfil_do(base_dir, p)
        if p.get("modelo") in CT.MODELOS_CLIPE:
            out["sugestoes"] = CC.sugestoes(p)
            out["so_fontes"] = CC.so_fontes(p)
            out["midia_modo"] = CC.modo_midia(p)
            out["estilo_ia"] = CT.estilo_ia_do(p, out["perfil"])
        return jsonify(out)

    @app.route("/curtos/<pid>/config", methods=["POST"])
    def curto_config(pid: str):
        b = _corpo()
        with CT._TRAVA:
            p = _proj(pid)
            if "titulo" in b:
                p["titulo"] = " ".join(str(b["titulo"] or "").split())[:120] or p["titulo"]
            if "canal_id" in b:
                cid = str(b["canal_id"] or "")
                if cid and not CT._valido(cid):
                    return _erro("Canal inválido.")
                p["canal_id"] = cid
            cfg = p.setdefault("config", {})
            if "duracao_alvo_s" in b:
                try:
                    cfg["duracao_alvo_s"] = max(0, min(180, int(float(b["duracao_alvo_s"] or 0))))
                except (TypeError, ValueError):
                    pass
            if "modo_anime" in b and (b["modo_anime"] in CT.MODOS_ANIME or b["modo_anime"] == ""):
                cfg["modo_anime"] = b["modo_anime"]
            for k, n in (("extra", 3000), ("voz_tts", 120), ("motor_perfil", 20), ("anime_obras", 300)):
                if k in b:
                    cfg[k] = str(b[k] or "")[:n]
            if isinstance(b.get("providers"), list):
                cfg["providers"] = [str(x) for x in b["providers"] if str(x)][:20]
            if "texto_noticia" in b:
                p["noticia"]["texto"] = str(b["texto_noticia"] or "")[:60000]
            novos = 0
            for u in str(b.get("links") or "").split():
                if u.startswith("http") and u not in [f["url"] for f in p["noticia"]["fontes"]] and len(p["noticia"]["fontes"]) < 8:
                    p["noticia"]["fontes"].append({"url": u[:800], "estado": "na fila", "titulo": "", "texto": "", "erro": None})
                    novos += 1
            CT.salvar(base_dir, p)
        if novos:
            _rodar(pid, "📰 lendo a notícia", lambda prog: f"{CT.ler_noticias(base_dir, pid)} matéria(s) lida(s)")
        return _ok(novos=novos)

    @app.route("/curtos/<pid>/noticias/ler", methods=["POST"])
    def curto_ler(pid: str):
        with CT._TRAVA:
            p = _proj(pid)
            for f in p["noticia"]["fontes"]:
                if f.get("estado") == "erro":
                    f["estado"] = "na fila"
            CT.salvar(base_dir, p)
        return _rodar(pid, "📰 lendo a notícia", lambda prog: f"{CT.ler_noticias(base_dir, pid)} matéria(s) lida(s)")

    @app.route("/curtos/<pid>/fonte/<int:i>/apagar", methods=["POST"])
    def curto_fonte_apagar(pid: str, i: int):
        with CT._TRAVA:
            p = _proj(pid)
            if 0 <= i < len(p["noticia"]["fontes"]):
                p["noticia"]["fontes"].pop(i)
            CT.salvar(base_dir, p)
        return _ok()

    @app.route("/curtos/<pid>/midia", methods=["POST"])
    def curto_midia(pid: str):
        feitos = []
        with CT._TRAVA:
            p = _proj(pid)
            tmpd = tempfile.mkdtemp(prefix="curto_m_")
            for arq in request.files.getlist("arquivos"):
                if not arq or not arq.filename:
                    continue
                nome = secure_filename(arq.filename) or "arquivo"
                tipo = CT.tipo_arquivo(nome)
                if not tipo:
                    continue
                cam = os.path.join(tmpd, nome)
                arq.save(cam)
                feitos.append(CT.adicionar_midia(base_dir, p, cam, tipo, request.form.get("descricao") or os.path.splitext(arq.filename)[0])["id"])
            CT.salvar(base_dir, p)
            shutil.rmtree(tmpd, ignore_errors=True)
        return _ok(novos=feitos) if feitos else _erro("Mande fotos ou vídeos.")

    @app.route("/curtos/<pid>/midia/<mid>", methods=["POST"])
    def curto_midia_editar(pid: str, mid: str):
        b = _corpo()
        with CT._TRAVA:
            p = _proj(pid)
            m = next((x for x in p["midias"] if x["id"] == mid), None)
            if not m:
                return _erro("Mídia não encontrada.", 404)
            if b.get("apagar"):
                cam = CT.caminho_midia(base_dir, p, m)
                if cam:
                    os.remove(cam)
                p["midias"].remove(m)
            elif "descricao" in b:
                m["descricao"] = " ".join(str(b["descricao"] or "").split())[:400]
            CT.salvar(base_dir, p)
        return _ok()

    @app.route("/curtos/<pid>/arquivo/<path:caminho>", methods=["GET"])
    def curto_arquivo(pid: str, caminho: str):
        _proj(pid)
        raiz = os.path.realpath(CT.pasta(base_dir, pid))
        cam = os.path.realpath(os.path.join(raiz, caminho))
        if not cam.startswith(raiz + os.sep) or not os.path.isfile(cam):
            abort(404)
        return send_file(cam, conditional=True)

    # roteiro
    @app.route("/curtos/<pid>/roteiro/gerar", methods=["POST"])
    def curto_roteiro_gerar(pid: str):
        _proj(pid)

        def fn(prog):
            r = (CC.gerar_roteiro if _proj(pid).get("modelo") in CT.MODELOS_CLIPE else CT.gerar_roteiro)(base_dir, pid)
            CT.realinhar(base_dir, pid)
            return f"{len(r['blocos'])} bloco(s)"
        return _rodar(pid, "📝 escrevendo o roteiro", fn)

    @app.route("/curtos/<pid>/roteiro/prompt", methods=["GET"])
    def curto_roteiro_prompt(pid: str):
        p = _proj(pid)
        return _ok(prompt=(CC.prompt_roteiro if p.get("modelo") in CT.MODELOS_CLIPE else CT.prompt_roteiro)(base_dir, p))

    @app.route("/curtos/<pid>/roteiro", methods=["POST"])
    def curto_roteiro_salvar(pid: str):
        b = _corpo()
        try:
            with CT._TRAVA:
                p = _proj(pid)
                dados = b.get("resposta") if b.get("resposta") else b.get("roteiro")
                if not dados:
                    return _erro("Nada pra salvar.")
                if p.get("modelo") in CT.MODELOS_CLIPE and b.get("resposta"):  # a resposta de outra IA (fala_en/fala_pt, ganchos…)
                    novo = CC.ler_roteiro(dados, p, CC.dados(p).get("idioma") or "en")
                else:
                    novo = CT.ler_roteiro(dados, p)
                    for k in ("ganchos", "finais", "titulos", "roteiro_en", "roteiro_pt", "idioma", "titulo_pt", "ganchos_escolhido", "finais_escolhido",
                              "titulos_escolhido"):
                        if k not in novo and (p.get("roteiro") or {}).get(k) is not None:
                            novo[k] = p["roteiro"][k]
                if isinstance(dados, dict) and not b.get("resposta"):  # editado na tela: mantém títulos/descrição de antes se não vieram
                    for k in ("titulo_video", "titulos_alt", "descricao", "hashtags"):
                        if k not in dados and p.get("roteiro"):
                            novo[k] = p["roteiro"].get(k)
                p["roteiro"] = novo
                CT.salvar(base_dir, p)
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        CT.realinhar(base_dir, pid)
        return _ok(roteiro=novo)

    # voz guia
    @app.route("/curtos/<pid>/tts", methods=["POST"])
    def curto_tts(pid: str):
        p = _proj(pid)
        if not CB["tts"]:
            return _erro("O gerador de voz não está disponível aqui.")
        slug = str(_corpo().get("voz") or (p.get("config") or {}).get("voz_tts") or "")
        try:
            import anime2d as A
            voz = A.voz_por_slug(slug, (p.get("config") or {}).get("motor_perfil") or "xtts")
        except Exception:  # noqa: BLE001
            voz = None
        if not voz:
            return _erro("Escolha a voz.")
        with CT._TRAVA:
            q = _proj(pid)
            q["config"]["voz_tts"] = slug
            CT.salvar(base_dir, q)

        def fn(prog):
            info = CT.gerar_voz_guia(base_dir, pid, CB["tts"], limpar_tts or (lambda t, m: t), voz, on_log=prog)
            return f"voz guia: {info['dur']:.1f} s"
        return _rodar(pid, "🎙 gerando a voz guia", fn)

    # gravação
    def _opcoes() -> Dict[str, Any]:
        f = request.form if request.form else _corpo()
        op: Dict[str, Any] = {}
        for k in ("cortar_pausas", "cortar_repeticoes"):
            if k in f:
                op[k] = str(f.get(k)).lower() in ("1", "true", "on", "sim")
        if f.get("pausa_max") not in (None, ""):
            try:
                op["pausa_max"] = max(0.1, min(1.5, float(f.get("pausa_max"))))
            except (TypeError, ValueError):
                pass
        return op

    @app.route("/curtos/<pid>/gravacao", methods=["POST"])
    def curto_gravacao(pid: str):
        _proj(pid)
        arq = request.files.get("audio")
        if not arq or not arq.filename:
            return _erro("Mande o áudio (ou grave na página).")
        try:
            _transcrever()
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        d = os.path.join(CT.pasta(base_dir, pid), "voz")
        os.makedirs(d, exist_ok=True)
        ext = os.path.splitext(secure_filename(arq.filename) or "a.webm")[1].lower() or ".webm"
        bruto = os.path.join(d, "enviado" + ext)
        arq.save(bruto)
        op = _opcoes()

        def fn(prog):
            g = CT.processar_gravacao(base_dir, pid, _transcrever(), bruto, op, prog, fonte="gravacao")
            return f"{g['dur_original']:.1f} s → {g['dur']:.1f} s ({len(g['cortes'])} corte(s))"
        return _rodar(pid, "🎤 lendo a sua voz", fn)

    @app.route("/curtos/<pid>/gravacao/usar-guia", methods=["POST"])
    def curto_usar_guia(pid: str):
        p = _proj(pid)
        t = p.get("tts") or {}
        cam = os.path.join(CT.pasta(base_dir, pid), t.get("arquivo") or "_")
        if not os.path.isfile(cam):
            return _erro("Gere a voz guia antes.")
        op = _opcoes()

        def fn(prog):
            g = CT.processar_gravacao(base_dir, pid, _transcrever(), cam, op, prog, fonte="guia")
            return f"voz guia alinhada ({g['dur']:.1f} s)"
        return _rodar(pid, "🎙 usando a voz guia", fn)

    @app.route("/curtos/<pid>/gravacao/refazer", methods=["POST"])
    def curto_gravacao_refazer(pid: str):
        p = _proj(pid)
        if not (p.get("gravacao") or {}).get("original"):
            return _erro("Ainda não tem gravação.")
        op = _opcoes()

        def fn(prog):
            g = CT.processar_gravacao(base_dir, pid, _transcrever() if CB["transcrever"] else (lambda *a, **k: []), "", op, prog)
            return f"{g['dur_original']:.1f} s → {g['dur']:.1f} s ({len(g['cortes'])} corte(s))"
        return _rodar(pid, "✂ refazendo os cortes", fn)

    @app.route("/curtos/<pid>/gravacao/usar-falado", methods=["POST"])
    def curto_usar_falado(pid: str):
        _proj(pid)
        n = CT.usar_o_que_falei(base_dir, pid, _corpo().get("blocos") or None)
        return _ok(mudou=n)

    # sons
    @app.route("/curtos/<pid>/som", methods=["POST"])
    def curto_som(pid: str):
        b = _corpo()
        with CT._TRAVA:
            p = _proj(pid)
            bl = next((x for x in (p.get("roteiro") or {}).get("blocos") or [] if x["id"] == b.get("bloco")), None)
            try:
                s = bl["sfx"][int(b.get("indice"))] if bl else None
            except (IndexError, TypeError, ValueError):
                s = None
            if not s:
                return _erro("Deixa não encontrada.", 404)
            if b.get("som"):
                s["som"] = str(b["som"])[:80]
            elif "som" in b:
                s.pop("som", None)
            if b.get("volume") not in (None, ""):
                try:
                    s["volume"] = round(max(0.0, min(3.0, float(b["volume"]))), 2)
                except (TypeError, ValueError):
                    pass
            CT.salvar(base_dir, p)
        return _ok()

    @app.route("/curtos/sons/<tipo>", methods=["GET"])
    def curtos_sons_tipo(tipo: str):
        import dp_sons
        if tipo == "todos":
            return _ok(sons=[{"id": s["id"], "nome": s.get("nome") or s["id"], "categoria": s.get("categoria"), "arquivo": s.get("arquivo")} for s in dp_sons.sons()])
        if tipo not in CT.TIPOS_SFX:
            abort(404)
        return _ok(sons=[{"id": s["id"], "nome": s.get("nome") or s["id"], "categoria": s.get("categoria"), "arquivo": s.get("arquivo")}
                         for s in CT.sons_do_tipo(tipo)])

    # 🔎 Pixabay
    @app.route("/curtos/pixabay/buscar", methods=["POST"])
    def curtos_pixabay_buscar():
        b = _corpo()
        termo = " ".join(str(b.get("termo") or "").split())[:80]
        if not termo:
            return _erro("Escreva o que procurar (em inglês funciona melhor: whoosh, cinematic hit…).")
        try:
            limite = max(1, min(12, int(b.get("limite") or 6)))
        except (TypeError, ValueError):
            limite = 6
        pasta_p = _pasta_pixabay(base_dir)

        def fn(prog):
            import pixabay_sons_teste as PT
            args = argparse.Namespace(termo=termo, paginas=1, limite=limite, pasta=pasta_p, oculto=bool(b.get("oculto")),
                                      chrome=bool(b.get("chrome")), ia=_ia_ligada(), sem_baixar=False, html=None)
            velho_log = PT.log
            PT.log = lambda m: (prog(str(m).strip()[:200]), velho_log(m))
            try:
                rc = (rodar_pixabay or PT.rodar)(args)
            finally:
                PT.log = velho_log
            n = len(_resultados_pixabay(pasta_p, termo))
            if not n:
                raise CT.CurtoErro("Nenhum som baixado (a verificação da Cloudflare foi resolvida na janela do navegador?)" + (f" — código {rc}" if rc else ""))
            return f"{n} som(ns) do Pixabay pra “{termo}”"
        return _rodar("pixabay", f"🔎 Pixabay: {termo}", fn)

    @app.route("/curtos/pixabay/estado", methods=["GET"])
    def curtos_pixabay_estado():
        termo = " ".join(str(request.args.get("termo") or "").split())
        return jsonify({"tarefa": TAREFAS.get("pixabay"), "sons": _resultados_pixabay(_pasta_pixabay(base_dir), termo) if termo else []})

    @app.route("/curtos/pixabay/arquivo/<path:nome>", methods=["GET"])
    def curtos_pixabay_arquivo(nome: str):
        raiz = os.path.realpath(_pasta_pixabay(base_dir))
        cam = os.path.realpath(os.path.join(raiz, nome))
        if not cam.startswith(raiz + os.sep) or not os.path.isfile(cam):
            abort(404)
        return send_file(cam, conditional=True)

    @app.route("/curtos/pixabay/usar", methods=["POST"])
    def curtos_pixabay_usar():
        b = _corpo()
        try:
            sid = importar_pixabay(base_dir, str(b.get("id") or ""))
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        pid = str(b.get("pid") or "")
        if CT._valido(pid) and b.get("bloco"):
            with CT._TRAVA:
                p = CT.carregar(base_dir, pid)
                bl = next((x for x in (p.get("roteiro") or {}).get("blocos") or [] if x["id"] == b["bloco"]), None)
                try:
                    bl["sfx"][int(b.get("indice"))]["som"] = sid
                    CT.salvar(base_dir, p)
                except (TypeError, IndexError, ValueError, KeyError):
                    pass
        return _ok(som=sid)

    # prévia e editor
    @app.route("/curtos/<pid>/previa", methods=["POST"])
    def curto_previa(pid: str):
        _proj(pid)
        prov = _corpo().get("providers")
        try:
            d = CT.montar_dados_editor(base_dir, pid, prov if isinstance(prov, list) else None)
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        return _ok(planos=d["planos"], destaques=d["resposta"]["highlights"], sfx=d["sfx"], dur=d["dur"], legendas=d["legendas"])

    @app.route("/curtos/<pid>/editor", methods=["POST"])
    def curto_editor(pid: str):
        _proj(pid)
        if not CB["para_estudio"]:
            return _erro("O editor não está disponível aqui.")
        prov = _corpo().get("providers")
        if isinstance(prov, list) and prov:
            with CT._TRAVA:
                p = _proj(pid)
                p["config"]["providers"] = [str(x) for x in prov][:20]
                CT.salvar(base_dir, p)
        try:
            d = CT.montar_dados_editor(base_dir, pid, prov if isinstance(prov, list) and prov else None)
            job_id = CB["para_estudio"](d)
        except Exception as exc:  # noqa: BLE001
            return _erro(str(exc))
        with CT._TRAVA:
            p = _proj(pid)
            p["editor"] = {"job_id": job_id, "quando": time.time()}
            CT.salvar(base_dir, p)
        return _ok(job_id=job_id, link=f"/job/{job_id}/fetching-previews")

    @app.route("/curtos/<pid>/fazer-tudo", methods=["POST"])
    def curto_fazer_tudo(pid: str):
        _proj(pid)
        b = _corpo()
        prov = [str(x) for x in b.get("providers") or [] if str(x)][:20] or None
        if b.get("refazer_roteiro"):
            with CT._TRAVA:
                q = _proj(pid)
                q["roteiro"] = None
                CT.salvar(base_dir, q)
        return _rodar(pid, "🚀 fazendo tudo", lambda prog: _fazer_tudo(pid, str(b.get("voz") or ""), prov, prog))

    @app.route("/curtos/<pid>/trocar-voz", methods=["POST"])
    def curto_trocar_voz(pid: str):
        _proj(pid)
        arq = request.files.get("audio")
        cam = ""
        if arq and arq.filename:
            d = os.path.join(CT.pasta(base_dir, pid), "voz")
            os.makedirs(d, exist_ok=True)
            cam = os.path.join(d, "enviado" + (os.path.splitext(secure_filename(arq.filename) or "a.webm")[1].lower() or ".webm"))
            arq.save(cam)
        op = _opcoes()
        return _rodar(pid, "🔁 trocando a voz no editor", lambda prog: _trocar(pid, cam, op, prog))

    # ------------------------------------------------------------------ 💬 comentário
    def _ia_ou_erro() -> None:
        if not _ia_ligada():
            raise CT.CurtoErro("A IA está desligada (ou o recurso “⚡ Vídeos curtos” desligado em /ia).")

    def _mandar_pro_editor(pid: str, providers: Optional[List[str]], prog: Callable[[str], None]) -> str:
        if not CB["para_estudio"]:
            raise CT.CurtoErro("O editor não está disponível aqui.")
        prog("🎬 montando no editor…")
        d = CT.montar_dados_editor(base_dir, pid, providers or None)
        job_id = CB["para_estudio"](d)
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            q["editor"] = {"job_id": job_id, "quando": time.time()}
            CT.salvar(base_dir, q)
        return f"pronto: {len(d['planos'])} planos em {d['dur']:.1f} s — abra no editor"

    def _fazer_tudo_comentario(pid: str, slug: str, providers: Optional[List[str]], prog: Callable[[str], None]) -> str:
        """🚀 💬 o que acontece (transcreve/descreve se faltar) → roteiro EN/PT → 3 takes → take 1 alinhado → 🎯 destaques → editor."""
        p = CT.carregar(base_dir, pid)
        c = CC.dados(p)
        expl = CC.explicativo(p)
        if not expl and not CC.clipes(base_dir, p):
            raise CT.CurtoErro("Suba o vídeo cru (o clipe).")
        if expl and any(f.get("estado") != "lida" for f in p["noticia"]["fontes"]):
            prog("📰 lendo a matéria…")
            CT.ler_noticias(base_dir, pid)
            p = CT.carregar(base_dir, pid)
        if not (p.get("roteiro") or {}).get("blocos"):
            for m in CC.clipes(base_dir, p):
                if not CC.sem_linha_do_tempo(CT.carregar(base_dir, pid), m["id"]):
                    continue
                if CB["transcrever"] and not expl:  # 📚 a fala das fontes não importa (é a narração que manda): só o que se VÊ
                    try:
                        CC.transcrever_clipe(base_dir, pid, m["id"], CB["transcrever"], prog)
                    except Exception:  # noqa: BLE001
                        pass
                if _ia_ligada():  # o que se VÊ também (clipe sem fala, ou pra completar)
                    try:
                        CC.descrever_clipe(base_dir, pid, m["id"], on_log=prog)
                    except Exception as exc:  # noqa: BLE001
                        prog(f"👁 não deu pra descrever {m['id']}: {exc}")
            prog(f"📝 escrevendo o roteiro ({CT.LINGUAS[CC.lingua_post(p)]} + português, 5 ganchos, 5 finais e 5 títulos)…")
            CC.gerar_roteiro(base_dir, pid)
            p = CT.carregar(base_dir, pid)
        chave = CT.chave_roteiro(p.get("roteiro"))
        g = p.get("gravacao") or {}
        if not (g.get("arquivo") and g.get("chave_roteiro") == chave):
            if not CB["tts"]:
                raise CT.CurtoErro("O gerador de voz não está disponível aqui.")
            takes = [t for t in p.get("takes") or [] if t.get("chave") == chave]
            if not takes:
                voz = _voz(p, slug)
                if not voz:
                    raise CT.CurtoErro("Nenhuma voz de TTS cadastrada (🎙 Gerar voz → vozes).")
                with CT._TRAVA:
                    q = CT.carregar(base_dir, pid)
                    q["config"]["voz_tts"] = voz.get("slug") or slug
                    CT.salvar(base_dir, q)
                CC.gerar_takes(base_dir, pid, CB["tts"], limpar_tts or (lambda t_, m: t_), voz,
                               int((p.get("config") or {}).get("takes") or 3), prog)
            prog("🎯 alinhando o take 1 ao roteiro (Whisper)…")
            CC.usar_take(base_dir, pid, int(CT.carregar(base_dir, pid).get("take_escolhido") or 1), _transcrever(), {}, prog)
        if _ia_ligada():
            r = CC.preparar_destaques(base_dir, pid, providers, on_log=prog)
            if r["pendentes"]:
                prog(f"🎯 {len(r['pendentes'])} destaque(s) pra fazer à mão no 🎯 Rastrear objeto")
        return _mandar_pro_editor(pid, providers, prog)

    # ------------------------------------------------------------------ 🔗 link → vídeo pronto (v84_286)
    import curtos_link as CL

    def _link_resumo(p: Dict[str, Any]) -> Dict[str, Any]:
        lr = p.get("link_rapido") or {}
        r = p.get("roteiro") or {}
        t = TAREFAS.get(p["id"]) or {}
        exp = p.get("exportado") or {}
        info = CC.dados(p).get("info_link") or {}
        return {"id": p["id"], "titulo": p.get("titulo") or "", "link": lr.get("link") or "", "modo": lr.get("modo") or "auto",
                "modo_usado": CL.modo_escolhido(r.get("descricao_bruta") or r.get("descricao") or "", lr.get("modo") or "auto"),
                "criado": lr.get("criado") or 0, "rodando": bool(t) and not t.get("fim"), "prog": t.get("prog") or "",
                "erro": t.get("erro") or lr.get("erro") or "", "fim": t.get("fim"),
                "roteiro": " ".join(CT.sem_tags(b.get("fala") or "") for b in r.get("blocos") or [])[:900],
                "roteiro_tags": " ".join(b.get("fala") or "" for b in r.get("blocos") or [])[:900],
                "titulos": CN.titulos_do_projeto(p), "descricao": CL.limpar_marca(r.get("descricao") or ""),
                "hashtags": r.get("hashtags") or [], "n_comentarios": len(info.get("comentarios") or []),
                "comentarios_erro": info.get("erro") or "", "pronto": bool(exp.get("arquivo") and os.path.isfile(exp.get("arquivo") or "")),
                "editor": (p.get("editor") or {}).get("job_id") or "", "etapa": lr.get("etapa") or ""}

    def _links(n: int = 30) -> List[Dict[str, Any]]:
        out = []
        for x in CT.listar(base_dir):
            if x.get("modelo") != "comentario":
                continue
            try:
                p = CT.carregar(base_dir, x["id"])
            except CT.CurtoErro:
                continue
            if p.get("link_rapido"):
                out.append(_link_resumo(p))
        return sorted(out, key=lambda v: -(v["criado"] or 0))[:n]

    def _link_etapa(pid: str, etapa: str, **kw: Any) -> None:
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            q.setdefault("link_rapido", {}).update(etapa=etapa, **kw)
            CT.salvar(base_dir, q)

    def _link_rodar(pid: str, slug: str, qualidade: str, exportar: bool, prog: Callable[[str], None]) -> str:
        p = CT.carregar(base_dir, pid)
        lr = p["link_rapido"]
        url = lr["link"]
        if not CC.clipes(base_dir, p):
            _link_etapa(pid, "⬇ baixando")
            CC.baixar_clipe(base_dir, pid, url, CB.get("baixar"), prog)
        c = CC.dados(CT.carregar(base_dir, pid))
        if not c.get("info_link"):
            _link_etapa(pid, "💬 lendo os comentários")
            prog("💬 lendo a legenda e os comentários do post…")
            info = CL.baixar_info(url, 60) if not lr.get("so_colados") else {"comentarios": []}
            colados = CL.comentarios_colados(lr.get("comentarios_colados") or "")
            if colados:
                info["comentarios"] = colados + [x for x in info.get("comentarios") or [] if x["texto"] not in {y["texto"] for y in colados}]
            with CT._TRAVA:
                q = CT.carregar(base_dir, pid)
                CC.dados(q)["info_link"] = info
                CC.dados(q)["modo_link"] = lr.get("modo") or "auto"
                if info.get("titulo") and (q.get("titulo") or "").startswith("🔗"):
                    q["titulo"] = info["titulo"][:120]
                CT.salvar(base_dir, q)
            prog(f"💬 {len(info.get('comentarios') or [])} comentários" + (f" ({info['erro']})" if info.get("erro") else ""))
        _link_etapa(pid, "📝 roteiro → 🎙 narração → 🎬 edição")
        msg = _fazer_tudo_comentario(pid, slug, None, prog)
        with CT._TRAVA:  # o modo que a IA escolheu (no automático) fica marcado; a descrição sai limpa
            q = CT.carregar(base_dir, pid)
            r = q.get("roteiro") or {}
            if r.get("descricao") and not r.get("descricao_bruta"):
                r["descricao_bruta"] = r["descricao"]
                r["descricao"] = CL.limpar_marca(r["descricao"])
            CT.salvar(base_dir, q)
        if not exportar:
            _link_etapa(pid, "✅ no editor")
            return msg
        if not CB.get("exportar"):
            raise CT.CurtoErro("A exportação automática não está disponível aqui — abra no editor e exporte.")
        _link_etapa(pid, "🎬 exportando")
        job_id = (CT.carregar(base_dir, pid).get("editor") or {}).get("job_id")
        arq = CB["exportar"](job_id, qualidade, prog)
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            q["exportado"] = {"arquivo": arq, "quando": time.time(), "qualidade": qualidade, "job_id": job_id}
            q["link_rapido"]["etapa"] = "✅ pronto"
            CT.salvar(base_dir, q)
        return "✅ vídeo pronto"

    @app.route("/curtos/link", methods=["GET"])
    def curtos_link_pagina():
        try:
            import anime2d as A
            vozes_en = A.vozes_disponiveis("chatterbox_turbo")
            vozes = A.vozes_disponiveis("chatterbox")
        except Exception:  # noqa: BLE001
            vozes_en, vozes = [], []
        import qualidade_export
        return render_template("curtos_link.html", modos=CL.MODOS, linguas=CT.LINGUAS, proporcoes=CT.PROPORCOES,
                               vozes_en=vozes_en, vozes=vozes, resolucoes=qualidade_export.RESOLUCOES, ia=_ia_ligada(),
                               tem_tts=bool(CB["tts"]), tem_export=bool(CB.get("exportar")))

    @app.route("/curtos/link/estado", methods=["GET"])
    def curtos_link_estado():
        return _ok(videos=_links())

    @app.route("/curtos/link/novo", methods=["POST"])
    def curtos_link_novo():
        b = _corpo()
        links = [u for u in re.split(r"\s+", str(b.get("link") or "")) if u.startswith("http")][:10]
        if not links:
            return _erro("Cole o link do vídeo (TikTok, Shorts, Reels, Kwai…).")
        modo = b.get("modo") if b.get("modo") in CL.MODOS else "auto"
        lp = b.get("lingua_post") if b.get("lingua_post") in CT.LINGUAS else "en"
        narrar_pt = b.get("idioma") == "pt"
        qualidade = str(b.get("qualidade") or "1080p")
        exportar = b.get("exportar", True) not in (False, "0", "", "false")
        criados = []
        for url in links:  # 🔗 vários links = vários vídeos, um depois do outro
            p = CT.criar(base_dir, CT.canal_do_modelo(base_dir, "comentario"), "🔗 " + url.split("?")[0][-60:], [], "", modelo="comentario")
            pid = p["id"]
            with CT._TRAVA:
                p = CT.carregar(base_dir, pid)
                c = CC.dados(p)
                c["lingua_post"], c["idioma"] = lp, ("pt" if narrar_pt else "en")
                narrada = "pt" if narrar_pt else lp
                p["config"]["motor_perfil"] = "chatterbox_turbo" if narrada == "en" else "chatterbox"
                if b.get("proporcao") in CT.PROPORCOES:
                    p["config"]["proporcao"] = b["proporcao"]
                try:
                    dur = int(float(b.get("duracao") or 0))
                    if dur:
                        p["config"]["duracao_alvo_s"] = max(10, min(180, dur))
                except (TypeError, ValueError):
                    pass
                if b.get("extra"):
                    p["config"]["extra"] = str(b["extra"])[:2000]
                if b.get("voz"):
                    p["config"]["voz_tts"] = str(b["voz"])[:120]
                p["config"]["takes"] = 1  # ⚡ automático: 1 take (os outros dá pra gerar depois na página do curto)
                p["link_rapido"] = {"link": url, "modo": modo, "criado": time.time(), "qualidade": qualidade, "exportar": exportar,
                                    "comentarios_colados": str(b.get("comentarios") or "")[:20000], "etapa": "na fila"}
                CT.salvar(base_dir, p)
            criados.append(pid)
        slug = str(b.get("voz") or "")

        def fila(prog: Callable[[str], None]) -> str:
            feitos = 0
            for k, pid in enumerate(criados, 1):
                TAREFAS[pid] = {"rotulo": "🔗 link → vídeo", "inicio": time.time(), "fim": None, "erro": None, "msg": "", "prog": "começando…"}

                def pr(m: str, pid=pid, k=k) -> None:
                    TAREFAS[pid]["prog"] = (f"[{k}/{len(criados)}] " if len(criados) > 1 else "") + str(m)[:280]
                    prog(m)
                try:
                    TAREFAS[pid]["msg"] = _link_rodar(pid, slug, qualidade, exportar, pr)
                    feitos += 1
                except Exception as exc:  # noqa: BLE001  (um link ruim não para os outros)
                    TAREFAS[pid]["erro"] = str(exc)[:600]
                    try:
                        _link_etapa(pid, "❌ erro", erro=str(exc)[:600])
                    except Exception:  # noqa: BLE001
                        pass
                finally:
                    TAREFAS[pid]["fim"] = time.time()
            return f"{feitos}/{len(criados)} prontos"
        for pid in criados[1:]:
            TAREFAS[pid] = {"rotulo": "🔗 na fila", "inicio": time.time(), "fim": None, "erro": None, "msg": "", "prog": "⏳ na fila"}
        r = _rodar("link:" + criados[0], "🔗 link → vídeo", fila)
        if isinstance(r, tuple):
            return r
        return _ok(criados=criados, videos=_links())

    @app.route("/curtos/link/<pid>/refazer", methods=["POST"])
    def curtos_link_refazer(pid: str):
        """🔁 tenta de novo do ponto em que parou (o que já está feito e em dia é pulado)."""
        p = _proj(pid)
        lr = p.get("link_rapido") or {}
        if not lr:
            abort(404)
        t = TAREFAS.get(pid)
        if t and not t.get("fim"):
            return _erro("Já está rodando.", 409)
        TAREFAS[pid] = {"rotulo": "🔗 link → vídeo", "inicio": time.time(), "fim": None, "erro": None, "msg": "", "prog": "começando…"}
        slug = (p.get("config") or {}).get("voz_tts") or ""

        def corpo() -> None:
            try:
                TAREFAS[pid]["msg"] = _link_rodar(pid, slug, lr.get("qualidade") or "1080p", lr.get("exportar", True),
                                                  lambda m: TAREFAS[pid].__setitem__("prog", str(m)[:300]))
            except Exception as exc:  # noqa: BLE001
                TAREFAS[pid]["erro"] = str(exc)[:600]
                _link_etapa(pid, "❌ erro", erro=str(exc)[:600])
            finally:
                TAREFAS[pid]["fim"] = time.time()
        _link_etapa(pid, "🔁 de novo", erro="")
        threading.Thread(target=corpo, daemon=True).start()
        return _ok(videos=_links())

    def _novo_comentario():
        f = request.form
        modelo = f.get("modelo") if f.get("modelo") in CT.MODELOS_CLIPE else "comentario"
        expl = modelo == "explicativo"
        clipes_ = [a for a in request.files.getlist("clipe") if a and a.filename]
        links = [u for u in str(f.get("link") or "").split() if u.startswith("http")][:20 if expl else 6]
        artigos = [u for u in str(f.get("artigos") or "").split() if u.startswith("http")][:8]
        if not expl and not clipes_ and not links:
            return redirect("/curtos/modelo/comentario?erro=Suba o vídeo cru (o clipe) ou cole o link dele.")
        if expl and not (f.get("texto") or "").strip() and not (f.get("titulo") or "").strip() and not artigos and not clipes_ and not links:
            return redirect("/curtos/modelo/explicativo?erro=Diga o assunto e mande os vídeos (ou o link de uma matéria).")
        cid = f.get("canal_id") if CT._valido(f.get("canal_id")) else CT.canal_do_modelo(base_dir, modelo)
        p = CT.criar(base_dir, cid, f.get("titulo") or (os.path.splitext(clipes_[0].filename)[0] if clipes_ else
                     " ".join(str(f.get("texto") or "").split()[:8]) or ("Explicativo" if expl else "Comentário")), artigos,
                     str(f.get("texto") or "") if expl else "", modelo=modelo)
        pid = p["id"]
        tmpd = tempfile.mkdtemp(prefix="curto_c_")
        with CT._TRAVA:
            p = CT.carregar(base_dir, pid)
            for arq in clipes_[:20 if expl else 6]:
                cam = os.path.join(tmpd, secure_filename(arq.filename) or "clipe.mp4")
                arq.save(cam)
                if CT.tipo_arquivo(cam) == "video":
                    CT.adicionar_midia(base_dir, p, cam, "video", os.path.splitext(arq.filename)[0][:120])
            try:
                dur = int(float(f.get("duracao") or 0))
                if dur:
                    p["config"]["duracao_alvo_s"] = max(10, min(180, dur))
            except ValueError:
                pass
            c = CC.dados(p)
            c["idioma"] = "pt" if f.get("idioma") == "pt" else "en"
            c["lingua_post"] = f.get("lingua_post") if f.get("lingua_post") in CT.LINGUAS else "en"
            narrada = "pt" if c["idioma"] == "pt" else c["lingua_post"]
            p["config"]["motor_perfil"] = "chatterbox_turbo" if narrada == "en" else "chatterbox"
            if f.get("proporcao") in CT.PROPORCOES:
                p["config"]["proporcao"] = f["proporcao"]
            if expl:
                p["config"]["so_fontes"] = ("so_fontes" in f) if "tem_so_fontes" in f else True
                if f.get("midia") in CC.MODOS_MIDIA:
                    p["config"]["midia"] = f["midia"]
                    p["config"]["so_fontes"] = f["midia"] == "minhas"
                p["config"]["estilo_ia"] = f.get("estilo_ia") if f.get("estilo_ia") in CT.ESTILOS_IA else "realista"
            c["referencia"] = str(f.get("referencia") or "")[:20000]
            if f.get("roteiro_pronto") and not expl:  # ✍ v84_283: o roteiro feito sem vídeo, já aprovado — narra como está
                rp = _roteiro_pronto(str(f["roteiro_pronto"]))
                if rp:
                    p.setdefault("noticia", {})["texto"] = (
                        "APPROVED SCRIPT — the creator already wrote and approved this narration. Use it WORD FOR WORD as the "
                        "script (fala_en; keep any voice tags), only split it into blocks and match each line to the moment of "
                        "the clip that shows it; translate it for fala_pt. Keep the hook and the final question exactly:\n"
                        + rp["texto"])[:4000]
                    c["roteiro_pronto"] = rp["id"]
            if f.get("voz"):
                p["config"]["voz_tts"] = str(f["voz"])[:120]
            CT.salvar(base_dir, p)
        shutil.rmtree(tmpd, ignore_errors=True)
        if not expl and clipes_ and not links and not CC.clipes(base_dir, CT.carregar(base_dir, pid)):
            CT.excluir(base_dir, pid)
            return redirect("/curtos/modelo/comentario?erro=Isso não parece um vídeo.")
        if (f.get("linhas") or "").strip():
            CC.salvar_o_que_acontece(base_dir, pid, f["linhas"], "M1")
        ref = request.files.get("referencia_video")
        cam_ref = ""
        if ref and ref.filename:
            d = os.path.join(CT.pasta(base_dir, pid), "referencia")
            os.makedirs(d, exist_ok=True)
            cam_ref = os.path.join(d, secure_filename(ref.filename) or "ref.mp4")
            ref.save(cam_ref)
        slug = f.get("voz") or ""
        tudo = bool(f.get("tudo"))

        ref_link = str(f.get("referencia_link") or "").strip()

        def fn(prog):
            feito = []
            for k, u in enumerate(links):
                try:
                    CC.baixar_clipe(base_dir, pid, u, CB.get("baixar"), lambda m, k=k: prog(f"⬇ vídeo {k + 1}/{len(links)} — {m}"))
                    feito.append("vídeo baixado")
                except Exception as exc:  # noqa: BLE001  (📚 um link ruim não derruba os outros)
                    if not expl:
                        raise
                    feito.append(f"❌ {u[:50]}: {str(exc)[:80]}")
            if expl and CT.carregar(base_dir, pid)["noticia"]["fontes"]:
                prog("📰 lendo a matéria…")
                CT.ler_noticias(base_dir, pid)
            if ref_link and not cam_ref:
                prog("⬇ baixando o vídeo de referência…")
                cam = CC.baixar_link(ref_link, os.path.join(CT.pasta(base_dir, pid), "referencia"), CB.get("baixar"))
            else:
                cam = cam_ref
            if cam:
                prog("📺 transcrevendo o vídeo de referência…")
                CC.transcrever_referencia(base_dir, pid, cam, _transcrever())
                feito.append("referência transcrita")
            if tudo:
                return _fazer_tudo_comentario(pid, slug, None, prog)
            q = CT.carregar(base_dir, pid)
            if _ia_ligada():  # sem linha do tempo (sem texto, ou só a transcrição corrida): a IA olha o vídeo
                for m in CC.clipes(base_dir, q):
                    if CC.sem_linha_do_tempo(q, m["id"]):
                        CC.descrever_clipe(base_dir, pid, m["id"], on_log=prog)
                        feito.append(f"👁 {m['id']} descrito")
            return " · ".join(feito)
        if cam_ref or tudo or links or ref_link or artigos or _ia_ligada():
            _rodar(pid, "🚀 fazendo tudo" if tudo else ("⬇ preparando as fontes" if expl else "⬇ preparando o clipe"), fn)
        return redirect(f"/curtos/{pid}")

    def _pagina_comentario(p: Dict[str, Any]):
        try:
            import anime2d as A
            vozes = A.vozes_disponiveis((p.get("config") or {}).get("motor_perfil") or "chatterbox_turbo")
        except Exception:  # noqa: BLE001
            vozes = []
        return render_template("curto_comentario.html", p=p, vozes=vozes, ia=_ia_ligada(), tags=CC.TAGS_VOZ, linguas=CT.LINGUAS,
                               modos_midia=CC.MODOS_MIDIA, estilos_ia=CT.ESTILOS_IA,
                               proporcoes=CT.PROPORCOES, fontes_dp=_fontes_dp(), posicoes_marca=CT.MARCA_POSICOES,
                               tipos_sfx={k: v["nome"] for k, v in CT.TIPOS_SFX.items()},
                               tem_tts=bool(CB["tts"]), tem_whisper=bool(CB["transcrever"]))

    def _fontes_dp() -> List[str]:
        try:
            import dp_legendas
            return sorted(dp_legendas._mapa_fontes())
        except Exception:  # noqa: BLE001
            return ["DP Poppins"]

    @app.route("/curtos/<pid>/comentario/lingua", methods=["POST"])
    def curto_c_lingua(pid: str):
        _modelo_comentario(pid)
        try:
            CC.definir_lingua_post(base_dir, pid, str(_corpo().get("lingua") or ""))
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        return _ok()

    @app.route("/curtos/<pid>/comentario/sugestao", methods=["POST"])
    def curto_c_sugestao(pid: str):
        _modelo_comentario(pid)
        b = _corpo()
        try:
            CC.usar_sugestao(base_dir, pid, int(b.get("bloco")), int(b.get("cena")), bool(b.get("usar", True)))
        except (CT.CurtoErro, TypeError, ValueError) as exc:
            return _erro(str(exc) or "Cena inválida.")
        return _ok()

    def _modelo_comentario(pid: str) -> Dict[str, Any]:
        p = _proj(pid)
        if p.get("modelo") not in CT.MODELOS_CLIPE:
            abort(404)
        return p

    @app.route("/curtos/<pid>/comentario/linhas", methods=["POST"])
    def curto_c_linhas(pid: str):
        _modelo_comentario(pid)
        b = _corpo()
        mid = str(b.get("mid") or "M1").upper()[:6]
        tipo = b.get("tipo") if b.get("tipo") in ("texto", "fala", "visual") else "texto"
        texto = str(b.get("texto") or "")[:30000]
        if tipo == "texto" and texto.strip() and not CC.tem_tempos(texto):
            return _ok(**CC.salvar_o_que_acontece(base_dir, pid, texto, mid))
        return _ok(linhas=CC.salvar_texto_do_clipe(base_dir, pid, texto, mid, tipo), referencia=False)

    @app.route("/curtos/<pid>/comentario/baixar", methods=["POST"])
    def curto_c_baixar(pid: str):
        _modelo_comentario(pid)
        b = _corpo()
        urls = [str(u).strip() for u in (b.get("urls") or [b.get("url")]) if str(u or "").strip().startswith("http")][:20]
        url, ref = (urls[0] if urls else ""), bool(b.get("referencia"))
        if not url:
            return _erro("Cole o link do vídeo.")

        def fn(prog):
            if len(urls) > 1 and not ref:  # 📚 vários links de uma vez
                feitos, erros = [], []
                for k, u in enumerate(urls):
                    try:
                        mid = CC.baixar_clipe(base_dir, pid, u, CB.get("baixar"), lambda m, k=k: prog(f"⬇ {k + 1}/{len(urls)} — {m}"))
                        feitos.append(mid)
                        if _ia_ligada() and CC.sem_linha_do_tempo(CT.carregar(base_dir, pid), mid):
                            CC.descrever_clipe(base_dir, pid, mid, on_log=prog)
                    except Exception as exc:  # noqa: BLE001
                        erros.append(f"{u[:40]}: {str(exc)[:60]}")
                return f"{len(feitos)} vídeo(s) baixado(s)" + (f" · ❌ {'; '.join(erros)}" if erros else "")
            if ref:
                cam = CC.baixar_link(url, os.path.join(CT.pasta(base_dir, pid), "referencia"), CB.get("baixar"))
                prog("📺 transcrevendo a referência…")
                return f"referência: {len(CC.transcrever_referencia(base_dir, pid, cam, _transcrever()).split())} palavras"
            mid = CC.baixar_clipe(base_dir, pid, url, CB.get("baixar"), prog)
            if _ia_ligada() and CC.sem_linha_do_tempo(CT.carregar(base_dir, pid), mid):
                CC.descrever_clipe(base_dir, pid, mid, on_log=prog)
                return f"{mid} baixado e descrito pela IA"
            return f"{mid} baixado"
        return _rodar(pid, "⬇ baixando o vídeo", fn)

    @app.route("/curtos/<pid>/comentario/transcrever", methods=["POST"])
    def curto_c_transcrever(pid: str):
        _modelo_comentario(pid)
        mid = str(_corpo().get("mid") or "M1").upper()[:6]
        if not CB["transcrever"]:
            return _erro("O Whisper não está disponível aqui.")
        return _rodar(pid, f"🎙 transcrevendo {mid}",
                      lambda prog: f"{CC.transcrever_clipe(base_dir, pid, mid, CB['transcrever'], prog)} linha(s)")

    @app.route("/curtos/<pid>/comentario/descrever", methods=["POST"])
    def curto_c_descrever(pid: str):
        _modelo_comentario(pid)
        mid = str(_corpo().get("mid") or "M1").upper()[:6]
        try:
            _ia_ou_erro()
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        return _rodar(pid, f"👁 a IA está olhando o {mid}", lambda prog: f"{CC.descrever_clipe(base_dir, pid, mid, on_log=prog)} linha(s)")

    @app.route("/curtos/<pid>/comentario/referencia", methods=["POST"])
    def curto_c_referencia(pid: str):
        _modelo_comentario(pid)
        arq = request.files.get("video")
        if arq and arq.filename:
            d = os.path.join(CT.pasta(base_dir, pid), "referencia")
            os.makedirs(d, exist_ok=True)
            cam = os.path.join(d, secure_filename(arq.filename) or "ref.mp4")
            arq.save(cam)
            if not CB["transcrever"]:
                return _erro("O Whisper não está disponível aqui.")
            return _rodar(pid, "📺 transcrevendo a referência",
                          lambda prog: f"referência: {len(CC.transcrever_referencia(base_dir, pid, cam, CB['transcrever']).split())} palavras")
        texto = str((request.form.get("texto") if request.form else None) or _corpo().get("texto") or "")[:20000]
        with CT._TRAVA:
            p = _proj(pid)
            CC.dados(p)["referencia"] = texto
            CT.salvar(base_dir, p)
        return _ok(dur=CC.duracao_da_referencia(texto))

    @app.route("/curtos/<pid>/comentario/idioma", methods=["POST"])
    def curto_c_idioma(pid: str):
        _modelo_comentario(pid)
        try:
            CC.trocar_idioma(base_dir, pid, str(_corpo().get("idioma") or ""))
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        CT.realinhar(base_dir, pid)
        return _ok()

    @app.route("/curtos/<pid>/comentario/mais", methods=["POST"])
    def curto_c_mais(pid: str):
        _modelo_comentario(pid)
        qual = str(_corpo().get("qual") or "")
        if qual not in ("ganchos", "finais", "titulos"):
            return _erro("Pedido inválido.")
        try:
            _ia_ou_erro()
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        return _rodar(pid, f"➕ mais 5 {qual}", lambda prog: f"{len(CC.mais_opcoes(base_dir, pid, qual))} {qual} novos")

    @app.route("/curtos/<pid>/comentario/escolher", methods=["POST"])
    def curto_c_escolher(pid: str):
        _modelo_comentario(pid)
        b = _corpo()
        try:
            CC.escolher(base_dir, pid, str(b.get("qual") or ""), int(b.get("i")))
        except (CT.CurtoErro, TypeError, ValueError) as exc:
            return _erro(str(exc) or "Opção inválida.")
        return _ok()

    @app.route("/curtos/<pid>/comentario/takes", methods=["POST"])
    def curto_c_takes(pid: str):
        p = _modelo_comentario(pid)
        if not CB["tts"]:
            return _erro("O gerador de voz não está disponível aqui.")
        b = _corpo()
        voz = _voz(p, str(b.get("voz") or ""))
        if not voz:
            return _erro("Escolha a voz.")
        with CT._TRAVA:
            q = _proj(pid)
            q["config"]["voz_tts"] = voz.get("slug") or ""
            CT.salvar(base_dir, q)
        try:
            n = max(1, min(5, int(b.get("n") or 3)))
        except (TypeError, ValueError):
            n = 3
        return _rodar(pid, f"🎙 gerando {n} takes",
                      lambda prog: f"{len(CC.gerar_takes(base_dir, pid, CB['tts'], limpar_tts or (lambda t, m: t), voz, n, prog))} take(s) — ouça e escolha")

    @app.route("/curtos/<pid>/comentario/take", methods=["POST"])
    def curto_c_take(pid: str):
        _modelo_comentario(pid)
        try:
            k = int(_corpo().get("k"))
        except (TypeError, ValueError):
            return _erro("Take inválido.")
        if not CB["transcrever"]:
            return _erro("O Whisper não está disponível aqui.")
        op = _opcoes()
        return _rodar(pid, f"🎯 usando o take {k}",
                      lambda prog: f"take {k} alinhado ({CC.usar_take(base_dir, pid, k, CB['transcrever'], op, prog)['dur']:.1f} s)")

    @app.route("/curtos/<pid>/comentario/destaques", methods=["POST"])
    def curto_c_destaques(pid: str):
        _modelo_comentario(pid)
        b = _corpo()
        if b.get("refazer"):
            with CT._TRAVA:
                q = _proj(pid)
                q["destaques_prontos"] = {}
                CT.salvar(base_dir, q)

        def fn(prog):
            r = CC.preparar_destaques(base_dir, pid, on_log=prog)
            return f"🎯 {len(r['feitos'])} destaque(s) prontos" + (f", {len(r['pendentes'])} pendente(s)" if r["pendentes"] else "")
        return _rodar(pid, "🎯 preparando os destaques", fn)

    @app.route("/curtos/<pid>/comentario/destaque-manual", methods=["POST"])
    def curto_c_destaque_manual(pid: str):
        """🎯 destaque pendente → um rastreio com o pedaço do clipe; quando você gerar lá, “usar no curto” volta pra cá."""
        p = _modelo_comentario(pid)
        b = _corpo()
        pend = next((x for x in p.get("destaques_pendentes") or [] if x.get("chave") == b.get("chave")), None)
        if not pend or not pend.get("mid"):
            return _erro("Destaque não encontrado.")
        import rastreio as RT
        m = next((mm for mm in CC.clipes(base_dir, p) if mm["id"] == pend["mid"]), None)
        if not m:
            return _erro("Clipe não encontrado.")
        tmp = os.path.join(CT.pasta(base_dir, pid), "_destaque")
        os.makedirs(tmp, exist_ok=True)
        pedaco = os.path.join(tmp, "manual.mp4")
        import subprocess
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{float(pend['ini']):.3f}", "-i", m["caminho"], "-t",
                        f"{float(pend['fim']) - float(pend['ini']):.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                        "-pix_fmt", "yuv420p", pedaco], capture_output=True, timeout=600)
        try:
            r = RT.criar(base_dir, pedaco, f"{p.get('titulo') or 'curto'} · {pend['alvo']}")
        except Exception as exc:  # noqa: BLE001
            return _erro(str(exc))
        with RT._TRAVA:
            r = RT.carregar(base_dir, r["id"])
            r["curto"] = {"pid": pid, "chave": pend["chave"], "alvo": pend["alvo"]}
            RT.salvar(base_dir, r)
        return _ok(link=f"/rastrear/{r['id']}")

    @app.route("/curtos/<pid>/comentario/usar-rastreio", methods=["POST"])
    def curto_c_usar_rastreio(pid: str):
        """O vídeo gerado no 🎯 Rastrear objeto vira o destaque daquele plano (mídia R…)."""
        _modelo_comentario(pid)
        import rastreio as RT
        try:
            r = RT.carregar(base_dir, str(_corpo().get("rid") or ""))
        except RT.RastreioErro:
            return _erro("Rastreio não encontrado.", 404)
        cur = r.get("curto") or {}
        if cur.get("pid") != pid or not r.get("saida"):
            return _erro("Gere o vídeo no rastreio antes (🎬).")
        with CT._TRAVA:
            p = _proj(pid)
            copia = os.path.join(tempfile.mkdtemp(prefix="curto_r_"), "r.mp4")
            shutil.copy(os.path.join(RT.pasta(base_dir, r["id"]), r["saida"]), copia)
            mm = CT.adicionar_midia(base_dir, p, copia, "video", f"🎯 {cur.get('alvo')}", "R")
            p.setdefault("destaques_prontos", {})[cur["chave"]] = mm["id"]
            p["destaques_pendentes"] = [x for x in p.get("destaques_pendentes") or [] if x.get("chave") != cur["chave"]]
            CT.salvar(base_dir, p)
        return _ok(link=f"/curtos/{pid}")

    @app.route("/curtos/<pid>/marca", methods=["POST"])
    def curto_marca(pid: str):
        """🏷 a marca @canal deste vídeo (e, se pedir, o padrão do canal); vai junto pro projeto do editor."""
        b = _corpo()
        with CT._TRAVA:
            p = _proj(pid)
            c = CT.canal_do(base_dir, p)
            m = CT.normalizar_marca(dict(CT.marca_do(base_dir, p), **(b.get("marca") or {})))
            p["config"]["marca"] = m
            CT.salvar(base_dir, p)
            if b.get("padrao_canal") and c:
                c["perfil"]["marca"] = m
                CT.salvar_canal(base_dir, c)
        jid = (p.get("editor") or {}).get("job_id")
        if jid and CB.get("marca"):
            CB["marca"](jid, m)
        return _ok(marca=m, no_editor=bool(jid))

    @app.route("/curtos/<pid>/proporcao", methods=["POST"])
    def curto_proporcao(pid: str):
        b = _corpo()
        if b.get("proporcao") not in CT.PROPORCOES:
            return _erro("Proporção inválida.")
        with CT._TRAVA:
            p = _proj(pid)
            p["config"]["proporcao"] = b["proporcao"]
            if "so_fontes" in b:
                p["config"]["so_fontes"] = bool(b["so_fontes"])
            if b.get("midia") in CC.MODOS_MIDIA:
                p["config"]["midia"] = b["midia"]
                p["config"]["so_fontes"] = b["midia"] == "minhas"
            if b.get("estilo_ia") in CT.ESTILOS_IA:
                p["config"]["estilo_ia"] = b["estilo_ia"]
            CT.salvar(base_dir, p)
        return _ok()

    @app.route("/curtos/<pid>/excluir", methods=["POST"])
    def curto_excluir(pid: str):
        _proj(pid)
        CT.excluir(base_dir, pid)
        return redirect("/curtos")


# ------------------------------------------------------------------ Pixabay → base de sons
def _resultados_pixabay(pasta_p: str, termo: str) -> List[Dict[str, Any]]:
    cam = os.path.join(pasta_p, "catalogo.json")
    if not os.path.isfile(cam):
        return []
    try:
        itens = json.load(open(cam, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    t = " ".join(termo.lower().split())
    out = []
    for x in itens:
        if t and " ".join(str(x.get("busca") or "").lower().split()) != t:
            continue
        cort = x.get("arquivo_cortado")
        if not cort or not os.path.isfile(cort):
            continue
        f = x.get("ficha") or {}
        out.append({"id": str(x.get("id")), "titulo": x.get("titulo") or "", "autor": x.get("autor") or "",
                    "tags": x.get("tags") or [], "dur": x.get("dur"), "pico": x.get("pico"),
                    "nome": f.get("nome") or "", "descricao": f.get("descricao") or "",
                    "arquivo": os.path.relpath(cort, pasta_p).replace("\\", "/"), "pagina": x.get("pagina") or "",
                    "na_base": _ja_na_base(str(x.get("id")))})
    return out


def _ja_na_base(pid_som: str) -> bool:
    try:
        import dp_sons
        return dp_sons.som(f"pixabay/{pid_som}") is not None
    except Exception:  # noqa: BLE001
        return False


def importar_pixabay(base_dir: str, som_id: str, pasta_p: Optional[str] = None) -> str:
    """Um som baixado do Pixabay entra na BASE de sons do editor (assets/sons/pixabay + um arquivo de extras) — passa a
    aparecer na faixa Sons do Estúdio e nas deixas dos curtos. Devolve o id ("pixabay/123456")."""
    import dp_extras
    import dp_sons
    import pixabay_sons as PS
    if not som_id.isdigit():
        raise CT.CurtoErro("Som inválido.")
    pasta_p = pasta_p or _pasta_pixabay(base_dir)
    try:
        itens = json.load(open(os.path.join(pasta_p, "catalogo.json"), encoding="utf-8"))
    except (OSError, ValueError):
        raise CT.CurtoErro("Faça a busca no Pixabay antes.")
    meta = next((x for x in itens if str(x.get("id")) == som_id), None)
    if not meta or not meta.get("arquivo_cortado") or not os.path.isfile(meta["arquivo_cortado"]):
        raise CT.CurtoErro("Esse som não foi baixado.")
    rel = f"pixabay/{som_id}{os.path.splitext(meta['arquivo_cortado'])[1] or '.m4a'}"
    destino = os.path.join(dp_sons.SONS_DIR, rel)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.copy(meta["arquivo_cortado"], destino)
    item = PS.item_da_base(meta, rel)
    os.makedirs(dp_extras.pasta(), exist_ok=True)
    extras = os.path.join(dp_extras.pasta(), "pixabay_sons.json")
    try:
        d = json.load(open(extras, encoding="utf-8")) if os.path.isfile(extras) else {}
    except (OSError, ValueError):
        d = {}
    lista = [s for s in d.get("sons") or [] if s.get("id") != item["id"]]
    lista.append(item)
    d["sons"] = lista
    with open(extras, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    dp_extras.recarregar()
    if not dp_sons.som(item["id"]):
        raise CT.CurtoErro("O som não entrou na base (veja os erros dos extras no 📘 Guia).")
    return item["id"]
