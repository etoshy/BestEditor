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
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from flask import abort, jsonify, redirect, render_template, request, send_file
from werkzeug.utils import secure_filename

import curtos as CT

TAREFAS: Dict[str, Dict[str, Any]] = {}
CB: Dict[str, Any] = {}  # os ganchos do app (transcrever, tts, para_estudio, trocar) — os testes trocam aqui
_TRAVA_T = threading.Lock()


def _pasta_pixabay(base_dir: str) -> str:
    return os.environ.get("CURTOS_PIXABAY_DIR") or os.path.join(base_dir, "pixabay_sons")


def registrar(app, base_dir: str, transcrever: Optional[Callable[..., Any]] = None, tts: Optional[Callable[..., Any]] = None,
              limpar_tts: Optional[Callable[[str, str], str]] = None,
              para_estudio: Optional[Callable[[Dict[str, Any]], str]] = None,
              rodar_pixabay: Optional[Callable[[Any], int]] = None,
              trocar_no_estudio: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None) -> None:
    CB.update(transcrever=transcrever, tts=tts, para_estudio=para_estudio, trocar=trocar_no_estudio)

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
    @app.route("/curtos", methods=["GET"])
    def curtos_hub():
        CT.garantir_canais_prontos(base_dir)
        try:
            import anime2d as A
            vozes = A.vozes_disponiveis("xtts")
        except Exception:  # noqa: BLE001
            vozes = []
        return render_template("curtos.html", canais=CT.listar_canais(base_dir), projetos=CT.listar(base_dir),
                               prontos=CT.perfis_prontos(), vozes=vozes, erro=request.args.get("erro"))

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
        try:
            p = CT.criar(base_dir, f.get("canal_id") or "", f.get("titulo") or "", (f.get("links") or "").split(),
                         f.get("texto") or "")
        except CT.CurtoErro as exc:
            return redirect(f"/curtos?erro={exc}")
        try:
            dur = int(float(f.get("duracao") or 0))
            if dur:
                p["config"]["duracao_alvo_s"] = max(10, min(180, dur))
                CT.salvar(base_dir, p)
        except ValueError:
            pass
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
                               destaques=sorted(dp_destaques.catalogo().keys()), ia=_ia_ligada())

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
        try:
            import anime2d as A
            vozes = A.vozes_disponiveis((p.get("config") or {}).get("motor_perfil") or "xtts")
        except Exception:  # noqa: BLE001
            vozes = []
        import prompt_builder
        return render_template("curto_detalhe.html", p=p, canais=CT.listar_canais(base_dir), layouts=CT.LAYOUTS,
                               tipos_sfx={k: v["nome"] for k, v in CT.TIPOS_SFX.items()}, funcoes=CT.FUNCOES_BLOCO,
                               efeitos=CT.EFEITOS_CURTOS, entradas=CT.ENTRADAS_CURTOS, vozes=vozes, ia=_ia_ligada(),
                               todos_providers=prompt_builder.DEFAULT_PROVIDERS, providers_padrao=CT.PROVIDERS_PADRAO,
                               tem_tts=bool(CB["tts"]), tem_whisper=bool(CB["transcrever"]))

    @app.route("/curtos/<pid>/estado", methods=["GET"])
    def curto_estado(pid: str):
        p = _proj(pid)
        out = CT.resumo_tela(base_dir, p)
        out["tarefa"] = TAREFAS.get(pid)
        out["perfil"] = CT.perfil_do(base_dir, p)
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
            for k, n in (("extra", 3000), ("voz_tts", 120), ("motor_perfil", 20)):
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
            r = CT.gerar_roteiro(base_dir, pid)
            CT.realinhar(base_dir, pid)
            return f"{len(r['blocos'])} bloco(s)"
        return _rodar(pid, "📝 escrevendo o roteiro", fn)

    @app.route("/curtos/<pid>/roteiro/prompt", methods=["GET"])
    def curto_roteiro_prompt(pid: str):
        return _ok(prompt=CT.prompt_roteiro(base_dir, _proj(pid)))

    @app.route("/curtos/<pid>/roteiro", methods=["POST"])
    def curto_roteiro_salvar(pid: str):
        b = _corpo()
        try:
            with CT._TRAVA:
                p = _proj(pid)
                dados = b.get("resposta") if b.get("resposta") else b.get("roteiro")
                if not dados:
                    return _erro("Nada pra salvar.")
                novo = CT.ler_roteiro(dados, p)
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
