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
import subprocess
import shutil
import tempfile
import re
import threading
import time
import unicodedata
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


MARCAS_LINK = {"": "— sem marca", "descartado": "🟥 descartado", "postado": "🟦 postado", "planejado": "🟨 com planos de postar"}


def _log_link(lr: Dict[str, Any], texto: str) -> None:
    """📜 o log do vídeo (o que aconteceu, com a hora) — continua existindo mesmo depois de apagar os arquivos."""
    log = list(lr.get("log") or [])
    log.append({"quando": time.time(), "texto": str(texto)[:200]})
    lr["log"] = log[-60:]


def _chave_grupo(nome: str) -> str:
    """📂 o nome do grupo sem acento e sem maiúscula: 'Locais Incríveis' = 'locais incriveis'."""
    s = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().split())


def _nome_do_grupo(texto: str) -> str:
    """📂 o nome do grupo: tira símbolos e pontuação das pontas (':', '-', '=', '#', '[', aspas…)."""
    return re.sub(r"^[\W_]+|[\W_]+$", "", str(texto or "")).strip()


def _termos_do_grupo(nome: str) -> List[str]:
    """📂 v84_353: 'Comida, Food, Culinária' = 3 termos do mesmo grupo (sem ligar pra maiúscula/acento)."""
    return [t for t in (" ".join(_nome_do_grupo(x).split()) for x in str(nome or "").split(",")) if t]


def _separar_grupos(texto: str, eh_grupo: Optional[Callable[[str], bool]] = None,
                    dicas: Optional[Dict[str, str]] = None) -> List[tuple]:
    """📂 Lê a lista colada: uma palavra vira o grupo dos links que vêm depois, com qualquer símbolo
    depois (ou nenhum): 'Animais', 'Animais:', 'Animais -', '# Animais', '[Animais]'…
    'Animais: https://…' também vale. Devolve [(link, grupo)] na ordem, sem repetir link.
    💡 v84_353: com `eh_grupo`, o texto ANTES do link na MESMA linha só vira grupo se for um grupo/canal que já existe;
    senão é uma DICA pra IA sobre aquele vídeo ('Eclipse com skate: https://…') — vai em `dicas[link]`."""
    atual, out, vistos = "", [], set()
    for linha in str(texto or "").splitlines():
        if "http" in linha:
            pref = _nome_do_grupo(linha[:linha.find("http")])
            dica_linha = ""
            if pref and eh_grupo is not None and not eh_grupo(pref):
                dica_linha, pref = " ".join(linha[:linha.find("http")].split()).rstrip(":-–— ").strip()[:300], ""
            if pref:
                atual = pref
            resto = linha[linha.find("http"):]
            if "," in resto:  # 🧩 v84_349: "link1, link2, link3" na mesma linha = UM vídeo composto com as 3 fontes
                partes = []
                for x in re.split(r",", resto):
                    tok = (x.strip().split() or [""])[0].strip("<>\"'();")
                    if tok.startswith("http") and tok not in partes:
                        partes.append(tok)
                if len(partes) >= 2:
                    chave = ",".join(partes[:5])
                    if chave not in vistos:
                        vistos.add(chave)
                        out.append((chave, atual))
                        if dica_linha and dicas is not None:
                            dicas[chave] = dica_linha
                    continue
            for u in re.split(r"\s+", resto):
                u = u.strip("<>\"'(),;")
                if u.startswith("http") and u not in vistos:
                    vistos.add(u)
                    out.append((u, atual))
                    if dica_linha and dicas is not None:
                        dicas[u] = dica_linha
        else:
            nome = _nome_do_grupo(linha)
            if nome:
                atual = nome
    return out


def _grupos_ler(base: str) -> Dict[str, Dict[str, str]]:
    try:
        with open(os.path.join(CT.raiz(base), "grupos_link.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _grupos_gravar(base: str, dados: Dict[str, Dict[str, str]]) -> None:
    os.makedirs(CT.raiz(base), exist_ok=True)
    caminho = os.path.join(CT.raiz(base), "grupos_link.json")
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def _liberar_memoria_pesada() -> None:
    """🧹 v84_313: ver memoria_ram.liberar_pesados."""
    import memoria_ram
    memoria_ram.liberar_pesados()


def _espera_memoria(prog: Optional[Callable[[str], None]] = None) -> None:
    """⏸ v84_313: ver memoria_ram.espera_ram."""
    import memoria_ram
    memoria_ram.espera_ram(prog)


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
        if "videos" in kw:  # 📄 v84_344: a página da lista do Link vem com a contagem de tudo
            try:
                from flask import g as _g
                if getattr(_g, "vista", None) is not None:
                    kw.setdefault("vista", _g.vista)
            except RuntimeError:
                pass
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: str, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _corpo() -> Dict[str, Any]:
        return request.get_json(silent=True) or {}

    def _reservar(chave: str, rotulo: str, prog: str = "") -> bool:
        """🔒 v84_350 (idempotência): marca a tarefa como rodando SÓ se ela não está rodando — numa operação só, com trava.
        Antes era "olha → marca" em dois passos: 2 cliques/2 abas passavam juntos e o mesmo vídeo rodava 2× (IA cobrando 2×)."""
        with _TRAVA_T:
            t = TAREFAS.get(chave)
            if t and not t.get("fim"):
                return False
            TAREFAS[chave] = {"rotulo": rotulo, "inicio": time.time(), "fim": None, "erro": None, "msg": "", "prog": prog}
            return True

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

    @app.route("/curtos/<pid>/video_1x1.mp4", methods=["GET"])
    def curto_video_quadrado(pid: str):
        """⬛ v84_334: a versão 1:1."""
        p = _proj(pid)
        arq = (p.get("exportado_quadrado") or {}).get("arquivo")
        if not arq or not os.path.isfile(arq):
            abort(404)
        return send_file(arq, as_attachment=bool(request.args.get("baixar", "1") != "0"),
                         download_name=f"{secure_filename(p.get('titulo') or 'video')[:60] or 'video'}_1x1.mp4", conditional=True)

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
            if b.get("estilo_roteiro") in CC.ESTILOS_ROTEIRO:  # ✨ v84_321: vale pro próximo roteiro
                cfg["estilo_roteiro"] = b["estilo_roteiro"]
            if b.get("voz_modo") in ("minha", "tts"):  # 🎤 v84_325
                cfg["voz_modo"] = b["voz_modo"]
            if "camera_exp" in b:  # 🎥 v84_322: vale pro próximo roteiro/montagem
                cfg["camera_exp"] = b["camera_exp"] not in (False, "0", "false", "", None)
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

    def _sons_do_pixabay(pid: str, prog: Callable[[str], None]) -> int:
        """🔊 v84_302: as deixas de som do roteiro ganham um som do Pixabay pela busca que a IA escreveu ("basketball net swish",
        "crowd cheer"…) — busca uma vez (o navegador abre; a Cloudflare pode pedir verificação na 1ª vez), guarda no catálogo e
        reaproveita. Só com "sons do Pixabay" ligado no 🎨 acabamento. Devolve quantas deixas ganharam som."""
        if not CT.acabamento(base_dir).get("sons_pixabay"):
            return 0
        p = CT.carregar(base_dir, pid)
        termos = list(dict.fromkeys(d["busca"] for d in CT.deixas_de_som(p) if not d.get("escolhido") and d.get("busca")))[:4]
        pasta_p = _pasta_pixabay(base_dir)
        escolhidos: Dict[str, str] = {}
        faltam = [t for t in termos if not _resultados_pixabay(pasta_p, t)]
        if faltam:  # 🔊 v84_305: o navegador abre UMA vez e busca todos os termos na mesma aba
            prog("🔊 Pixabay: procurando " + ", ".join(f"“{t}”" for t in faltam) + "…")
            try:
                import pixabay_sons_teste as PT
                args = argparse.Namespace(termo=faltam[0], termos=faltam, paginas=1, limite=2, pasta=pasta_p, oculto=False, chrome=False,
                                          ia=False, sem_baixar=False, html=None)
                (rodar_pixabay or PT.rodar)(args)
            except Exception as exc:  # noqa: BLE001  (sem Pixabay: fica o som da base)
                prog(f"🔊 Pixabay falhou ({str(exc)[:80]}) — ficam os sons da base")
        for termo in termos:
            res = _resultados_pixabay(pasta_p, termo)
            if res:
                try:
                    escolhidos[termo] = importar_pixabay(base_dir, str(res[0]["id"]), pasta_p)
                except CT.CurtoErro:
                    pass
        if not escolhidos:
            return 0
        n = 0
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            for b in (q.get("roteiro") or {}).get("blocos") or []:
                for sx in b.get("sfx") or []:
                    termo = sx.get("busca") or CT.TIPOS_SFX.get(sx.get("tipo"), {}).get("pixabay")
                    if not sx.get("som") and termo in escolhidos:
                        sx["som"] = escolhidos[termo]
                        n += 1
            CT.salvar(base_dir, q)
        prog(f"🔊 {n} efeito(s) sonoro(s) do Pixabay")
        return n

    CB["sons_pixabay"] = _sons_do_pixabay

    def _mandar_pro_editor(pid: str, providers: Optional[List[str]], prog: Callable[[str], None]) -> str:
        if not CB["para_estudio"]:
            raise CT.CurtoErro("O editor não está disponível aqui.")
        try:
            _sons_do_pixabay(pid, prog)
        except Exception as exc:  # noqa: BLE001
            prog(f"🔊 Pixabay: {str(exc)[:120]}")
        if CT.carregar(base_dir, pid).get("rastros_h"):  # 🎥 v84_296: o que faltar enquadrar no vertical (ex.: o roteiro mudou)
            try:
                CC.enquadrar_planos(base_dir, pid, prog)
            except Exception as exc:  # noqa: BLE001
                prog(f"🎥 não deu pra enquadrar no vertical: {str(exc)[:160]}")
        prog("🎬 montando no editor…")
        d = CT.montar_dados_editor(base_dir, pid, providers or None)
        job_id = CB["para_estudio"](d)
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            q["editor"] = {"job_id": job_id, "quando": time.time()}
            CT.salvar(base_dir, q)
        return f"pronto: {len(d['planos'])} planos em {d['dur']:.1f} s — abra no editor"

    # 🧩 v84_320: o caminho do vídeo de comentário dividido em etapas. O vídeo sozinho chama todas em sequência
    # (_fazer_tudo_comentario); o lote "por etapa" chama cada etapa em todos os links antes da próxima. Cada etapa
    # pula o que já está feito e lê a configuração do PRÓPRIO vídeo (voz, idioma, canal, duração…).
    def _cm_preparar(pid: str, prog: Callable[[str], None]) -> List[str]:
        """📰 lê a matéria (explicativo) e devolve os clipes que ainda não têm linha do tempo (se o roteiro ainda não existe)."""
        p = CT.carregar(base_dir, pid)
        expl = CC.explicativo(p)
        if not expl and not CC.clipes(base_dir, p):
            raise CT.CurtoErro("Suba o vídeo cru (o clipe).")
        if expl and any(f.get("estado") != "lida" for f in p["noticia"]["fontes"]):
            prog("📰 lendo a matéria…")
            CT.ler_noticias(base_dir, pid)
            p = CT.carregar(base_dir, pid)
        if (p.get("roteiro") or {}).get("blocos"):
            return []
        return [m["id"] for m in CC.clipes(base_dir, p) if CC.sem_linha_do_tempo(p, m["id"])]

    def _cm_transcrever(pid: str, mids: List[str], prog: Callable[[str], None]) -> None:
        """🎙 a fala dos clipes (Whisper). 📚 no explicativo a fala das fontes não importa (é a narração que manda)."""
        if not mids or not CB["transcrever"] or CC.explicativo(CT.carregar(base_dir, pid)):
            return
        for mid in mids:
            try:
                CC.transcrever_clipe(base_dir, pid, mid, CB["transcrever"], prog)
            except Exception:  # noqa: BLE001
                pass

    def _cm_roteiro(pid: str, mids: List[str], prog: Callable[[str], None]) -> None:
        """👁 o que se VÊ nos clipes (IA) → 📝 o roteiro. Pula se o roteiro já existe."""
        if (CT.carregar(base_dir, pid).get("roteiro") or {}).get("blocos"):
            return
        if _ia_ligada():
            for mid in mids:
                try:
                    CC.descrever_clipe(base_dir, pid, mid, on_log=prog)
                except Exception as exc:  # noqa: BLE001
                    prog(f"👁 não deu pra descrever {mid}: {exc}")
        p = CT.carregar(base_dir, pid)
        prog(f"📝 escrevendo o roteiro ({CT.LINGUAS[CC.lingua_post(p)]} + português, 5 ganchos, 5 finais e 5 títulos)…")
        CC.gerar_roteiro(base_dir, pid)

    def _cm_precisa_voz(p: Dict[str, Any]) -> bool:
        g = p.get("gravacao") or {}
        return not (g.get("arquivo") and g.get("chave_roteiro") == CT.chave_roteiro(p.get("roteiro")))

    def _cm_voz(pid: str, slug: str, prog: Callable[[str], None]) -> None:
        """🎙 os takes da narração (TTS). Pula se já tem voz alinhada em dia ou takes do roteiro atual."""
        p = CT.carregar(base_dir, pid)
        if not _cm_precisa_voz(p):
            return
        if not CB["tts"]:
            raise CT.CurtoErro("O gerador de voz não está disponível aqui.")
        chave = CT.chave_roteiro(p.get("roteiro"))
        if [t for t in p.get("takes") or [] if t.get("chave") == chave]:
            return
        voz = _voz(p, slug)
        if not voz:
            raise CT.CurtoErro("Nenhuma voz de TTS cadastrada (🎙 Gerar voz → vozes).")
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            q["config"]["voz_tts"] = voz.get("slug") or slug
            CT.salvar(base_dir, q)
        CC.gerar_takes(base_dir, pid, CB["tts"], limpar_tts or (lambda t_, m: t_), voz,
                       int((p.get("config") or {}).get("takes") or 3), prog)

    def _cm_alinhar(pid: str, prog: Callable[[str], None]) -> None:
        """🎯 o take escolhido alinhado ao roteiro (Whisper)."""
        if not _cm_precisa_voz(CT.carregar(base_dir, pid)):
            return
        prog("🎯 alinhando o take 1 ao roteiro (Whisper)…")
        CC.usar_take(base_dir, pid, int(CT.carregar(base_dir, pid).get("take_escolhido") or 1), _transcrever(), {}, prog)

    def _fazer_tudo_comentario(pid: str, slug: str, providers: Optional[List[str]], prog: Callable[[str], None]) -> str:
        """🚀 💬 o que acontece (transcreve/descreve se faltar) → roteiro EN/PT → 3 takes → take 1 alinhado → 🎯 destaques → editor."""
        mids = _cm_preparar(pid, prog)
        _cm_transcrever(pid, mids, prog)
        _cm_roteiro(pid, mids, prog)
        _cm_voz(pid, slug, prog)
        _cm_alinhar(pid, prog)
        return _cm_final(pid, providers, prog)

    def _cm_final(pid: str, providers: Optional[List[str]], prog: Callable[[str], None]) -> str:
        """🎥 enquadra no vertical → 🎯 destaques → 🎬 editor."""
        q0 = CT.carregar(base_dir, pid)
        if not CC.explicativo(q0) and CC.so_fontes(q0) and (q0.get("roteiro") or {}).get("blocos"):  # 🎞 v84_330 (roteiros já feitos)
            with CT._TRAVA:
                q = CT.carregar(base_dir, pid)
                n_c = CC.segurar_no_clipe(q, q["roteiro"]["blocos"])
                if n_c:
                    CT.salvar(base_dir, q)
            if n_c:
                prog(f"🎞 {n_c} cena(s) que iam buscar fora do clipe voltaram pro clipe (a ideia ficou como 💡 sugestão)")
        if CT.carregar(base_dir, pid).get("rastros_h"):  # 🎥 v84_296: clipe deitado → vertical focando o que cada fala mostra
            try:
                n_v = CC.enquadrar_planos(base_dir, pid, prog)
                if n_v:
                    prog(f"🎥 {n_v} pedaço(s) enquadrado(s) no vertical")
            except Exception as exc:  # noqa: BLE001
                prog(f"🎥 não deu pra enquadrar no vertical: {str(exc)[:160]}")
        if _ia_ligada():
            r = CC.preparar_destaques(base_dir, pid, providers, on_log=prog)
            if r["pendentes"]:
                prog(f"🎯 {len(r['pendentes'])} destaque(s) pra fazer à mão no 🎯 Rastrear objeto")
        import camera_exp
        if camera_exp.ligada(CT.carregar(base_dir, pid)):  # 🎥 v84_322: zoom no detalhe + congelar com cartão
            try:
                r = camera_exp.preparar(base_dir, pid, providers, chamar=None if _ia_ligada() else (lambda *a, **k: None), on_log=prog)
                if r["feitos"] or r["pulados"]:
                    prog(f"🎥 câmera: {len(r['feitos'])} efeito(s) pronto(s)" + (f", {len(r['pulados'])} pulado(s)" if r["pulados"] else ""))
            except Exception as exc:  # noqa: BLE001  (a câmera nunca impede o vídeo)
                prog(f"🎥 câmera experimental falhou, sigo sem ela: {str(exc)[:160]}")
        return _mandar_pro_editor(pid, providers, prog)

    # ------------------------------------------------------------------ 🔗 link → vídeo pronto (v84_286)
    import curtos_link as CL

    def _link_resumo(p: Dict[str, Any], pend: Optional[set] = None) -> Dict[str, Any]:
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
                "roteiro_pt": _roteiro_pt(r), "roteiro_versoes": len(p.get("roteiro_historico") or []),
                "roteiro_mudou": bool(lr.get("roteiro_mudou")), "roteiro_idioma": r.get("idioma") or "",
                "links": lr.get("links") or [], "dica": lr.get("dica") or "",
                **_musica_local(lr, CC.dados(p)),
                "tem_original": bool(CC.clipes(base_dir, p)) if lr else False,
                "titulos": CN.titulos_do_projeto(p),
                "descricao": CL.com_fonte(CL.limpar_marca(r.get("descricao") or ""), lr.get("link") or "", info) if r.get("descricao") else "",
                "thumbs": [dict(t, k=k) for k, t in enumerate(p.get("thumbs") or [], 1)
                           if os.path.isfile(os.path.join(CT.pasta(base_dir, p["id"]), "thumbs", t["arquivo"]))],
                "hashtags": r.get("hashtags") or [], "n_comentarios": len(info.get("comentarios") or []),
                "comentarios_erro": info.get("erro") or "", "pronto": bool(exp.get("arquivo") and os.path.isfile(exp.get("arquivo") or "")),
                "editor": (p.get("editor") or {}).get("job_id") or "", "etapa": lr.get("etapa") or "",
                "canal": (CT.canal_do(base_dir, p) or {}).get("nome") or "", "canal_id": p.get("canal_id") or "",
                "pendente": p["id"] in (pend if pend is not None else set()),
                "marca": lr.get("marca") or "", "comentario": lr.get("comentario") or "", "log": (lr.get("log") or [])[-60:],
                "apagado": bool(lr.get("apagado")), "escolha": lr.get("escolha") or {}, "aguardando": bool(lr.get("aguardando")),
                "aguardando_voz": bool(lr.get("aguardando_voz")), "minha_voz": (p.get("config") or {}).get("voz_modo") == "minha",
                "pronto_1x1": bool((p.get("exportado_quadrado") or {}).get("arquivo") and os.path.isfile((p.get("exportado_quadrado") or {}).get("arquivo") or ""))}

    def _musica_local(lr: Dict[str, Any], c: Dict[str, Any]) -> Dict[str, str]:
        """🎵📍 v84_351: a música e o local do post (o que você escreveu vale; senão o que a plataforma informou — no composto,
        os de cada fonte, sem repetir). Pra indexar depois (painel de música) e dar contexto ao roteiro."""
        infos = [i.get("info") or {} for i in c.get("info_links") or []] or [c.get("info_link") or {}]
        juntar = lambda k: " | ".join(dict.fromkeys(str(i.get(k) or "").strip() for i in infos if str(i.get(k) or "").strip()))  # noqa: E731
        return {"musica": lr.get("musica") if lr.get("musica") is not None else juntar("musica"),
                "local": lr.get("local") if lr.get("local") is not None else juntar("local"),
                "musica_editada": lr.get("musica") is not None, "local_editado": lr.get("local") is not None}

    def _roteiro_pt(r: Dict[str, Any]) -> str:
        """🇧🇷 v84_343: a tradução do roteiro (quando ele não é narrado em português)."""
        bl = r.get("blocos") or []
        fala = " ".join(CT.sem_tags(b.get("fala") or "") for b in bl)
        pt = " ".join(CT.sem_tags(b.get("fala_pt") or "") for b in bl if b.get("fala_pt"))
        return pt[:1200] if pt and CT.norm(pt) != CT.norm(fala) else ""

    _CACHE_PROJ: Dict[str, tuple] = {}

    def _projetos_link() -> List[Dict[str, Any]]:
        """⚡ v84_344: os projetos do Link, lidos do disco SÓ quando o projeto.json mudou (antes: a lista lia todos os projetos
        2× a cada 2 s — com a gravação/alinhamento dentro, eram MBs por atualização)."""
        d = os.path.join(CT.raiz(base_dir), "projetos")
        out, vistos = [], set()
        for pid in os.listdir(d) if os.path.isdir(d) else []:
            cam = os.path.join(d, pid, "projeto.json")
            try:
                mt = os.stat(cam).st_mtime_ns
            except OSError:
                continue
            vistos.add(pid)
            c = _CACHE_PROJ.get(pid)
            if not c or c[0] != mt:
                try:
                    p = CT.carregar(base_dir, pid)
                except (CT.CurtoErro, OSError, ValueError):
                    continue
                c = _CACHE_PROJ[pid] = (mt, p if p.get("modelo") == "comentario" and p.get("link_rapido") else None)
            if c[1] is not None:
                out.append(c[1])
        for pid in list(_CACHE_PROJ):
            if pid not in vistos:
                _CACHE_PROJ.pop(pid, None)
        return out

    def _leve(p: Dict[str, Any], pend: set) -> Dict[str, Any]:
        """O mínimo de cada vídeo pra filtrar, contar e mostrar as barras (sem montar o cartão inteiro)."""
        lr = p.get("link_rapido") or {}
        t = TAREFAS.get(p["id"]) or {}
        exp = p.get("exportado") or {}
        rod = bool(t) and not t.get("fim")
        return {"id": p["id"], "criado": lr.get("criado") or 0, "canal_id": p.get("canal_id") or "", "rodando": rod,
                "aguardando": bool(lr.get("aguardando")), "aguardando_voz": bool(lr.get("aguardando_voz")), "link": lr.get("link") or "",
                "pendente": p["id"] in pend, "marca": lr.get("marca") or "", "apagado": bool(lr.get("apagado")),
                "escolha": bool((lr.get("escolha") or {}).get("titulo") or (lr.get("escolha") or {}).get("capa")),
                "pronto": bool(exp.get("arquivo") and os.path.isfile(exp.get("arquivo") or "")),
                "erro": bool((t.get("erro") or lr.get("erro")) and not rod)}

    SITUACOES = {"": "todas", "andamento": "⏳ rodando", "prontos": "✅ prontos", "erro": "❌ com erro", "aguardando": "⏸ aguardando",
                 "voz": "🎤 esperando a sua voz", "planejado": "🟡 planejados", "postado": "🔵 postados", "descartado": "🔴 descartados"}

    def _situacao_ok(v: Dict[str, Any], sit: str) -> bool:
        if not sit:
            return True
        return {"andamento": v["rodando"], "prontos": v["pronto"], "erro": v["erro"], "aguardando": (v["aguardando"] or v["pendente"]) and not v["rodando"],
                "voz": v["aguardando_voz"] and not v["rodando"]}.get(sit, v["marca"] == sit)

    def _links(n: Optional[int] = None) -> List[Dict[str, Any]]:
        """Sem `n`: a página pedida (?pagina=&por=&canal=&situacao=) — o cartão completo só dos vídeos dela; a contagem de
        tudo vai em g.vista (o _ok manda junto). Com `n`: os n mais novos, completos (uso interno)."""
        ps = _projetos_link()
        pend = set(_link_pendentes(ps))
        if n is not None:
            return sorted((_link_resumo(p, pend) for p in ps), key=lambda v: -(v["criado"] or 0))[:n]
        try:
            a = request.args
        except RuntimeError:
            a = {}
        try:
            por = max(5, min(100, int(a.get("por") or 10)))
            pag = max(1, int(a.get("pagina") or 1))
        except (TypeError, ValueError):
            por, pag = 10, 1
        canal, sit = str(a.get("canal") or ""), str(a.get("situacao") or "")
        leves = sorted(((_leve(p, pend), p) for p in ps), key=lambda x: -(x[0]["criado"] or 0))
        canais: Dict[str, int] = {}
        for v, _p in leves:
            canais[v["canal_id"]] = canais.get(v["canal_id"], 0) + 1
        filtrados = [(v, p) for v, p in leves if (not canal or v["canal_id"] == ("" if canal == "_sem" else canal)) and _situacao_ok(v, sit)]
        paginas = max(1, -(-len(filtrados) // por))
        pag = min(pag, paginas)
        pagina = [_link_resumo(p, pend) for _v, p in filtrados[(pag - 1) * por: pag * por]]
        todos = [v for v, _p in leves]
        livre = [v for v in todos if not v["rodando"] and not v["apagado"]]
        voz_ = [v for v in livre if v["aguardando_voz"]]
        try:
            from flask import g as _g
            _g.vista = {"pagina": pag, "paginas": paginas, "por": por, "total": len(filtrados), "total_geral": len(todos), "canal": canal,
                        "situacao": sit, "canais": canais, "rodando": sum(1 for v in todos if v["rodando"]),
                        "aguardando_links": [v["link"] for v in livre if v["aguardando"]],
                        "voz": len(voz_), "voz_mais_antigo": voz_[-1]["id"] if voz_ else "",
                        "pendentes": sum(1 for v in todos if v["pendente"] and not v["rodando"]),
                        "apagar": sum(1 for v in livre if v["marca"] in ("descartado", "postado") and not v["pendente"]),
                        "exportar": sum(1 for v in todos if v["escolha"]),
                        "limpaveis": sum(1 for v, _p in filtrados if not v["rodando"])}
        except RuntimeError:
            pass
        return pagina

    def _link_etapa(pid: str, etapa: str, **kw: Any) -> None:
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            q.setdefault("link_rapido", {}).update(etapa=etapa, **kw)
            if etapa.startswith(("✅", "❌")):
                _log_link(q["link_rapido"], f"{etapa} {kw.get('erro') or ''}".strip())
            CT.salvar(base_dir, q)

    _UM_LINK_POR_VEZ = threading.Lock()

    def _link_pendentes(ps: Optional[List[Dict[str, Any]]] = None) -> List[str]:
        """🔁 v84_310: os links que ficaram pelo meio (o site fechou/reiniciou): sem erro guardado, sem terminar, sem tarefa."""
        out = []
        for p in (ps if ps is not None else _projetos_link()):
            x = p
            lr = p.get("link_rapido") or {}
            if not lr or lr.get("erro") or lr.get("parado") or lr.get("apagado") or lr.get("aguardando") or lr.get("aguardando_voz"):
                continue
            if lr.get("etapa") in ("✅ pronto", "✅ no editor"):
                continue
            t = TAREFAS.get(x["id"])
            if t and not t.get("fim"):
                continue
            out.append(x["id"])
        return out

    _FILA_RETOMANDO = threading.Lock()

    def _retomar_fila() -> int:
        """▶ retoma TODOS os que ficaram pelo meio, um depois do outro, numa só fila.
        A lista é fixada no clique e cada vídeo aparece como "na fila" já na resposta (não fica parecendo que nada aconteceu)."""
        if not _FILA_RETOMANDO.acquire(blocking=False):
            return 0  # já tem uma fila de retomada rodando
        ordem = _link_pendentes()
        if not ordem:
            _FILA_RETOMANDO.release()
            return 0
        ordem = [x for k, x in enumerate(ordem) if _reservar(x, "🔗 link → vídeo",
                                                            "🔁 retomando…" if k == 0 else f"⏳ na fila da retomada ({k + 1}/{len(ordem)})")]
        if not ordem:
            _FILA_RETOMANDO.release()
            return 0

        def corpo() -> None:
            try:
                for pid in ordem:
                    p = CT.carregar(base_dir, pid)
                    lr = p.get("link_rapido") or {}
                    if lr.get("erro") or lr.get("apagado") or lr.get("etapa") in ("✅ pronto", "✅ no editor"):
                        TAREFAS[pid]["fim"] = time.time()
                        continue
                    TAREFAS[pid]["prog"] = "🔁 retomando depois da queda do site…"
                    try:
                        with _UM_LINK_POR_VEZ:
                            _espera_memoria(lambda m, pid=pid: TAREFAS[pid].__setitem__("prog", str(m)[:300]))
                            TAREFAS[pid]["msg"] = _link_rodar(pid, (p.get("config") or {}).get("voz_tts") or "",
                                                              lr.get("qualidade") or "1080p", lr.get("exportar", True),
                                                              lambda m, pid=pid: TAREFAS[pid].__setitem__("prog", str(m)[:300]))
                    except Exception as exc:  # noqa: BLE001  (um que falha não para a fila)
                        TAREFAS[pid]["erro"] = str(exc)[:600]
                        _link_etapa(pid, "❌ erro", erro=str(exc)[:600])
                    finally:
                        TAREFAS[pid]["fim"] = time.time()
                        _liberar_memoria_pesada()  # 🧹 v84_313
            finally:
                _FILA_RETOMANDO.release()
        threading.Thread(target=corpo, daemon=True, name="retomar-fila").start()
        return len(ordem)

    def _vigia_links() -> None:
        time.sleep(float(os.environ.get("CURTOS_VIGIA_INICIO_S") or 30))
        while True:
            try:
                if _link_pendentes() and not _UM_LINK_POR_VEZ.locked():
                    _retomar_fila()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(60)

    @app.route("/curtos/link/retomar", methods=["POST"])
    def curtos_link_retomar():
        """▶ retoma a fila que ficou pelo meio (um por vez, sem duplicar)."""
        ocupado = _FILA_RETOMANDO.locked()  # já tinha uma fila rodando: não duplica
        n = _retomar_fila()
        return _ok(retomados=n, ocupado=bool(ocupado and not n), videos=_links())

    import sys as _sys_l
    if "pytest" not in _sys_l.modules and os.environ.get("CURTOS_VIGIA", "1") != "0":
        threading.Thread(target=_vigia_links, daemon=True, name="vigia-links").start()

    def _minha_voz(p: Dict[str, Any]) -> bool:
        """🎤 v84_325: canal de voz própria — o roteiro sai, a voz é você que grava."""
        return (p.get("config") or {}).get("voz_modo") == "minha"

    def _esperar_minha_voz(pid: str, prog: Callable[[str], None]) -> Optional[str]:
        """Com voz própria e sem a sua gravação em dia: faz o roteiro e PARA esperando você gravar (não é erro)."""
        p = CT.carregar(base_dir, pid)
        if not _minha_voz(p) or not _cm_precisa_voz(p):
            return None
        mids = _cm_preparar(pid, prog)
        _cm_transcrever(pid, mids, prog)
        _cm_roteiro(pid, mids, prog)
        _link_etapa(pid, "🎤 grave a sua voz", aguardando_voz=True)
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            _log_link(q.setdefault("link_rapido", {}), "📝 roteiro pronto — esperando a sua voz (🎤 gravar)")
            CT.salvar(base_dir, q)
        return "🎤 roteiro pronto — grave a sua voz"

    def _link_rodar(pid: str, slug: str, qualidade: str, exportar: bool, prog: Callable[[str], None]) -> str:
        _link_coletar(pid, prog)
        espera = _esperar_minha_voz(pid, prog)
        if espera:
            return espera
        _link_etapa(pid, "📝 roteiro → 🎙 narração → 🎬 edição", aguardando_voz=False)
        msg = _fazer_tudo_comentario(pid, slug, None, prog)
        return _link_finalizar(pid, msg, qualidade, exportar, prog)

    def _link_tarja(pid: str, prog: Callable[[str], None]) -> int:
        """▭ v84_333: a tarja do canal (desfoque/cor sólida numa faixa) por cima da legenda que JÁ VEM no vídeo original —
        uma vez por clipe (o original fica guardado como _sem_tarja)."""
        import acabamento_extra as AX
        p = CT.carregar(base_dir, pid)
        t = (p.get("config") or {}).get("tarja")
        if not t:
            return 0
        n = 0
        for m in CC.clipes(base_dir, p):
            mm = next((x for x in p.get("midias") or [] if x["id"] == m["id"]), {})
            if mm.get("tarja"):
                continue
            prog(f"▭ cobrindo a legenda do vídeo original ({m['id']})…")
            if AX.aplicar_tarja(m["caminho"], t):
                n += 1
                with CT._TRAVA:
                    q = CT.carregar(base_dir, pid)
                    for x in q.get("midias") or []:
                        if x["id"] == m["id"]:
                            x["tarja"] = dict(t)
                    CT.salvar(base_dir, q)
        return n

    def _link_coletar(pid: str, prog: Callable[[str], None]) -> None:
        """⬇ o vídeo do link + 💬 a legenda e os comentários do post (rede; pula o que já tem)."""
        p = CT.carregar(base_dir, pid)
        lr = p["link_rapido"]
        url = lr["link"]
        fontes_ = [u for u in lr.get("links") or [] if u] or [url]
        if len(fontes_) > 1:  # 🧩 v84_349: composto — baixa todas (uma que falha não para as outras; precisa de 2+)
            ja = {m.get("origem") for m in CC.clipes(base_dir, p)}
            falhas = []
            for k, u in enumerate(fontes_, 1):
                if u in ja:
                    continue
                _link_etapa(pid, f"⬇ baixando {k}/{len(fontes_)}")
                try:
                    CC.baixar_clipe(base_dir, pid, u, CB.get("baixar"), lambda m, k=k: prog(f"⬇ fonte {k}/{len(fontes_)} — {m}"))
                except Exception as exc:  # noqa: BLE001
                    falhas.append(f"{k}: {str(exc)[:120]}")
            n_ok = len(CC.clipes(base_dir, CT.carregar(base_dir, pid)))
            if falhas:
                with CT._TRAVA:
                    q = CT.carregar(base_dir, pid)
                    _log_link(q["link_rapido"], f"🧩 {len(falhas)} fonte(s) não baixaram: " + " · ".join(falhas))
                    CT.salvar(base_dir, q)
            if n_ok < 2:
                raise CT.CurtoErro(f"O vídeo composto precisa de 2+ fontes e só {n_ok} baixou ({' · '.join(falhas)}).")
        elif not CC.clipes(base_dir, p):
            _link_etapa(pid, "⬇ baixando")
            CC.baixar_clipe(base_dir, pid, url, CB.get("baixar"), prog)
        _link_tarja(pid, prog)
        c = CC.dados(CT.carregar(base_dir, pid))
        if len(fontes_) > 1 and not c.get("info_links"):  # 💬 a legenda e os comentários de CADA fonte
            _link_etapa(pid, "💬 lendo os comentários")
            infos = []
            for k, u in enumerate(fontes_, 1):
                prog(f"💬 fonte {k}/{len(fontes_)}: legenda e comentários…")
                try:
                    infos.append({"url": u, "info": CL.baixar_info(u, 40) if not lr.get("so_colados") else {"comentarios": []}})
                except Exception as exc:  # noqa: BLE001
                    infos.append({"url": u, "info": {"comentarios": [], "erro": str(exc)[:200]}})
            junto = dict(infos[0]["info"])
            junto["comentarios"] = [x for i in infos for x in (i["info"].get("comentarios") or [])][:80]
            colados = CL.comentarios_colados(lr.get("comentarios_colados") or "")
            if colados:
                junto["comentarios"] = colados + junto["comentarios"]
            with CT._TRAVA:
                q = CT.carregar(base_dir, pid)
                CC.dados(q)["info_links"] = infos
                CC.dados(q)["info_link"] = junto
                CC.dados(q)["modo_link"] = lr.get("modo") or "auto"
                CT.salvar(base_dir, q)
            prog(f"💬 {len(junto['comentarios'])} comentários de {len(infos)} fontes")
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

    def _link_finalizar(pid: str, msg: str, qualidade: str, exportar: bool, prog: Callable[[str], None]) -> str:
        """🧾 descrição limpa + fonte → 🖼 prints → 🎬 exporta (se pedido)."""
        url = (CT.carregar(base_dir, pid).get("link_rapido") or {}).get("link") or ""
        with CT._TRAVA:  # o modo que a IA escolheu (no automático) fica marcado; a descrição sai limpa
            q = CT.carregar(base_dir, pid)
            r = q.get("roteiro") or {}
            if r.get("descricao") and not r.get("descricao_bruta"):
                r["descricao_bruta"] = r["descricao"]
                r["descricao"] = CL.limpar_marca(r["descricao"])
            if r.get("descricao"):  # 📌 v84_305: "Source (Instagram): @criador" no fim (🧩 composto: todas as fontes)
                infos_ = CC.dados(q).get("info_links") or []
                if infos_:
                    r["descricao"] = CL.com_fontes(r["descricao"], [(i["url"], i.get("info") or {}) for i in infos_])
                else:
                    r["descricao"] = CL.com_fonte(r["descricao"], url, CC.dados(q).get("info_link") or {})
            CT.salvar(base_dir, q)
        _link_thumbs(pid, prog)
        if not exportar:
            _link_etapa(pid, "✅ no editor")
            return msg
        if not CB.get("exportar"):
            raise CT.CurtoErro("A exportação automática não está disponível aqui — abra no editor e exporte.")
        _link_etapa(pid, "🎬 exportando")
        job_id = (CT.carregar(base_dir, pid).get("editor") or {}).get("job_id")
        if job_id and CB.get("marca"):  # 🏷 v84_347: o @ do projeto do editor = o do canal de agora (antes ficava o de quando criou)
            try:
                CB["marca"](job_id, CT.marca_do(base_dir, CT.carregar(base_dir, pid)))
            except Exception:  # noqa: BLE001
                pass
        arq = CB["exportar"](job_id, qualidade, prog)
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            q["exportado"] = {"arquivo": arq, "quando": time.time(), "qualidade": qualidade, "job_id": job_id}
            q["link_rapido"]["etapa"] = "✅ pronto"
            _log_link(q["link_rapido"], "✅ processado — vídeo pronto")
            CT.salvar(base_dir, q)
        q = CT.carregar(base_dir, pid)
        if (q.get("config") or {}).get("tambem_quadrado") and CT.proporcao_do(q) != "1:1":  # ⬛ v84_334: a versão 1:1 também
            try:
                _exportar_quadrado(pid, qualidade, prog)
                return "✅ vídeo pronto (9:16 + 1:1)"
            except Exception as exc:  # noqa: BLE001  (a 1:1 que falha não estraga a 9:16)
                with CT._TRAVA:
                    q = CT.carregar(base_dir, pid)
                    _log_link(q["link_rapido"], f"⬛ a versão 1:1 não saiu: {str(exc)[:150]}")
                    CT.salvar(base_dir, q)
                prog(f"⬛ a versão 1:1 não saiu: {str(exc)[:150]}")
        return "✅ vídeo pronto"

    def _exportar_quadrado(pid: str, qualidade: str, prog: Callable[[str], None]) -> str:
        """⬛ v84_334: o mesmo curto montado de novo no formato 1:1 (o editor reenquadra; a legenda/@ se ajustam) e exportado."""
        if not (CB.get("para_estudio") and CB.get("exportar")):
            raise CT.CurtoErro("O editor/exportação não está disponível aqui.")
        _link_etapa(pid, "⬛ montando a versão 1:1")
        prog("⬛ montando a versão 1:1 (quadrada)…")
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            antes = (q.get("config") or {}).get("proporcao")
            q["config"]["proporcao"] = "1:1"
            CT.salvar(base_dir, q)
        try:
            d = CT.montar_dados_editor(base_dir, pid)
            job2 = CB["para_estudio"](d)
        finally:
            with CT._TRAVA:
                q = CT.carregar(base_dir, pid)
                if antes:
                    q["config"]["proporcao"] = antes
                else:
                    q["config"].pop("proporcao", None)
                CT.salvar(base_dir, q)
        _link_etapa(pid, "⬛ exportando a versão 1:1")
        arq2 = CB["exportar"](job2, qualidade, prog)
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            q["exportado_quadrado"] = {"arquivo": arq2, "quando": time.time(), "qualidade": qualidade, "job_id": job2}
            q["link_rapido"]["etapa"] = "✅ pronto"
            _log_link(q["link_rapido"], "⬛ versão 1:1 pronta")
            CT.salvar(base_dir, q)
        return arq2

    def _link_thumbs(pid: str, prog: Callable[[str], None]) -> int:
        """🖼 v84_305: 3 prints impactantes do vídeo original (limpo, sem legenda) pra usar de thumb."""
        p = CT.carregar(base_dir, pid)
        cl = CC.clipes(base_dir, p)
        if not cl:
            return 0
        prog("🖼 escolhendo 3 prints pra thumb…")
        try:
            ts = CL.prints_para_thumb(cl[0]["caminho"], os.path.join(CT.pasta(base_dir, pid), "thumbs"),
                                      chamar=None if _ia_ligada() else False)
        except Exception as exc:  # noqa: BLE001  (não atrapalha o vídeo)
            prog(f"🖼 não deu pra tirar os prints: {str(exc)[:120]}")
            return 0
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            q["thumbs"] = [t for t in q.get("thumbs") or [] if t.get("manual")] + ts  # ✋ v84_343: os que VOCÊ salvou ficam
            if (q.get("link_rapido") or {}).get("escolha"):  # os prints mudaram: a capa escolhida antes não vale mais
                q["link_rapido"]["escolha"].pop("capa", None)
            CT.salvar(base_dir, q)
        return len(ts)

    @app.route("/curtos/<pid>/thumbs", methods=["POST"])
    def curto_thumbs(pid: str):
        _proj(pid)
        n = _link_thumbs(pid, lambda m: None)
        if not n:
            return _erro("Não consegui tirar os prints (o vídeo original está no projeto?).")
        return _ok(videos=_links())

    @app.route("/curtos/<pid>/thumb/salvar", methods=["POST"])
    def curto_thumb_salvar(pid: str):
        """✋ v84_343: salva o quadro do vídeo original no segundo que você parou o player (resolução cheia)."""
        p = _proj(pid)
        cl = CC.clipes(base_dir, p)
        if not cl:
            return _erro("O vídeo original não está no projeto.")
        try:
            t = max(0.0, float(_corpo().get("t") or 0))
        except (TypeError, ValueError):
            return _erro("Tempo inválido.")
        pasta = os.path.join(CT.pasta(base_dir, pid), "thumbs")
        os.makedirs(pasta, exist_ok=True)
        nome = f"manual_{int(round(t * 1000))}.jpg"
        cam = os.path.join(pasta, nome)
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", cl[0]["caminho"], "-frames:v", "1", "-q:v", "2", cam],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not os.path.isfile(cam):
            return _erro("Não consegui tirar esse quadro: " + (r.stderr or "")[-200:])
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            ts = [x for x in q.get("thumbs") or [] if x.get("arquivo") != nome]
            ts.append({"arquivo": nome, "t": round(t, 2), "por_que": f"✋ escolhido por você ({t:.1f} s)", "manual": True})
            q["thumbs"] = ts
            CT.salvar(base_dir, q)
        return _ok(videos=_links(), k=len(ts))

    @app.route("/curtos/<pid>/thumb/<int:k>/apagar", methods=["POST"])
    def curto_thumb_apagar(pid: str, k: int):
        """🗑 tira um print da lista (e arruma a capa escolhida)."""
        _proj(pid)
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            ts = q.get("thumbs") or []
            if not 1 <= k <= len(ts):
                return _erro("Print não encontrado.", 404)
            fora = ts.pop(k - 1)
            esc_ = (q.get("link_rapido") or {}).get("escolha") or {}
            if esc_.get("capa") == k:
                esc_.pop("capa", None)
            elif isinstance(esc_.get("capa"), int) and esc_["capa"] > k:
                esc_["capa"] -= 1
            q["thumbs"] = ts
            CT.salvar(base_dir, q)
        try:
            os.remove(os.path.join(CT.pasta(base_dir, pid), "thumbs", fora["arquivo"]))
        except OSError:
            pass
        return _ok(videos=_links())

    @app.route("/curtos/<pid>/roteiro/ajustar", methods=["POST"])
    def curto_roteiro_ajustar(pid: str):
        """✍ v84_343: você diz o que mudar (comentários, sugestões) e a IA reescreve o roteiro. O de antes fica guardado (↶)."""
        _proj(pid)
        t = TAREFAS.get(pid)
        if t and not t.get("fim"):
            return _erro("Espere o vídeo terminar a etapa atual.", 409)
        pedido = str(_corpo().get("pedido") or "").strip()
        if not pedido:
            return _erro("Escreva o que você quer mudar no roteiro.")
        try:
            CC.revisar_roteiro(base_dir, pid, pedido)
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            if q.get("link_rapido"):
                _log_link(q["link_rapido"], "✍ roteiro reescrito: " + pedido[:120])
                q["link_rapido"]["roteiro_mudou"] = True
                CT.salvar(base_dir, q)
        return _ok(videos=_links())

    @app.route("/curtos/<pid>/roteiro/desfazer", methods=["POST"])
    def curto_roteiro_desfazer(pid: str):
        _proj(pid)
        try:
            CC.desfazer_roteiro(base_dir, pid)
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            if q.get("link_rapido"):
                q["link_rapido"]["roteiro_mudou"] = True
                CT.salvar(base_dir, q)
        return _ok(videos=_links())

    @app.route("/curtos/<pid>/roteiro/traduzir", methods=["POST"])
    def curto_roteiro_traduzir(pid: str):
        """🇧🇷 traduz pro português os blocos que ainda não têm a tradução."""
        _proj(pid)
        try:
            CC.traduzir_roteiro(base_dir, pid)
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        return _ok(videos=_links())

    @app.route("/curtos/<pid>/thumb/<int:k>.jpg", methods=["GET"])
    def curto_thumb(pid: str, k: int):
        ts = _proj(pid).get("thumbs") or []
        if not 1 <= k <= len(ts):
            abort(404)
        cam = os.path.join(CT.pasta(base_dir, pid), "thumbs", ts[k - 1]["arquivo"])
        if not os.path.isfile(cam):
            abort(404)
        return send_file(cam, mimetype="image/jpeg", as_attachment=request.args.get("baixar") == "1",
                         download_name=f"thumb_{pid}_{k}.jpg", max_age=0)

    @app.route("/curtos/<pid>/titulos/novos", methods=["POST"])
    def curto_titulos_novos(pid: str):
        """🏷 v84_305: 5 títulos novos — com uma direção pronta (curiosidade, pergunta, polêmico…) e/ou o seu comentário."""
        _proj(pid)
        b = _corpo()
        try:
            _ia_ou_erro()
            novos = CC.mais_opcoes(base_dir, pid, "titulos", direcao=str(b.get("direcao") or ""), comentario=str(b.get("comentario") or ""))
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        return _ok(novos=novos, videos=_links())

    # ------------------------------------------------------------------ 🎤 v84_325: gravar a SUA voz (aos poucos)
    import gravar_voz as GV

    def _dono(pid: str) -> None:
        """O curto ou a sessão avulsa (🎙 texto livre) dona da gravação — 404 se não existe."""
        if GV.avulsa(pid):
            try:
                GV.sessao(base_dir, pid)
            except CT.CurtoErro:
                abort(404)
        else:
            _proj(pid)

    @app.route("/gravar-voz", methods=["GET"])
    def gravar_voz_lista():
        """🎙 v84_325: gravar a sua voz em cima de QUALQUER texto (teste de microfone, narração avulsa)."""
        return render_template("gravar_voz_lista.html", sessoes=GV.listar_avulsas(base_dir), erro=request.args.get("erro") or "")

    @app.route("/gravar-voz/nova", methods=["POST"])
    def gravar_voz_nova():
        f = request.form if request.form else _corpo()
        try:
            s_ = GV.criar_avulsa(base_dir, f.get("titulo") or "", f.get("texto") or "", f.get("separar") or "linha")
        except CT.CurtoErro as exc:
            return redirect("/gravar-voz?erro=" + str(exc))
        return redirect(f"/gravar-voz/{s_['id']}")

    @app.route("/gravar-voz/<sid>", methods=["GET"])
    def gravar_voz_sessao(sid: str):
        if not GV.avulsa(sid):
            abort(404)
        _dono(sid)
        s_ = GV.sessao(base_dir, sid)
        return render_template("curto_gravar.html", p={"titulo": s_.get("titulo") or "", "id": sid}, pid=sid, estado=GV.resumo(base_dir, sid),
                               tem_clipe=False, link=False, lingua="", avulsa=True, sessao=s_)

    @app.route("/gravar-voz/<sid>/texto", methods=["POST"])
    def gravar_voz_texto(sid: str):
        if not GV.avulsa(sid):
            abort(404)
        b = _corpo()
        try:
            GV.trocar_texto(base_dir, sid, b.get("texto") or "", b.get("separar") or "linha")
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        return _ok(estado=GV.resumo(base_dir, sid))

    @app.route("/gravar-voz/<sid>/apagar", methods=["POST"])
    def gravar_voz_apagar(sid: str):
        if not GV.avulsa(sid):
            abort(404)
        try:
            GV.apagar_avulsa(base_dir, sid)
        except CT.CurtoErro:
            abort(404)
        return redirect("/gravar-voz")

    @app.route("/curtos/<pid>/voz/juntar", methods=["POST"])
    def curto_voz_juntar(pid: str):
        """🧩 só junta as partes (com realce, se pedir) e devolve o áudio final pra ouvir/baixar."""
        _dono(pid)
        try:
            GV.juntar(base_dir, pid, bool(_corpo().get("realce_em_tudo")))
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        return _ok(url=f"/curtos/{pid}/voz/final.wav?v={int(time.time())}", estado=GV.resumo(base_dir, pid))

    @app.route("/curtos/<pid>/voz/final.wav", methods=["GET"])
    def curto_voz_final(pid: str):
        _dono(pid)
        cam = os.path.join(GV.pasta(base_dir, pid), "final.wav")
        if not os.path.isfile(cam):
            abort(404)
        return send_file(cam, mimetype="audio/wav", conditional=True, max_age=0, as_attachment=request.args.get("baixar") == "1",
                         download_name="minha_voz.wav")

    @app.route("/curtos/<pid>/gravar", methods=["GET"])
    def curto_gravar_pagina(pid: str):
        p = _proj(pid)
        if not (p.get("roteiro") or {}).get("blocos"):
            return redirect(f"/curtos/{pid}?erro=Faça o roteiro antes de gravar.")
        clipe = next(iter(CC.clipes(base_dir, p)), None)
        return render_template("curto_gravar.html", p=p, pid=pid, estado=GV.resumo(base_dir, pid), tem_clipe=bool(clipe),
                               link=bool(p.get("link_rapido")), lingua=(p.get("roteiro") or {}).get("idioma") or "en")

    @app.route("/curtos/<pid>/voz/estado", methods=["GET"])
    def curto_voz_estado(pid: str):
        _dono(pid)
        return _ok(estado=GV.resumo(base_dir, pid), tarefa=TAREFAS.get(pid))

    @app.route("/curtos/<pid>/voz/texto/<parte>", methods=["POST"])
    def curto_voz_texto(pid: str, parte: str):
        """✏ v84_341: ajusta o texto de uma parte enquanto grava (vazio = volta ao do roteiro)."""
        _dono(pid)
        try:
            return _ok(estado=GV.editar_texto(base_dir, pid, parte, str(_corpo().get("texto") or "")))
        except CT.CurtoErro as exc:
            return _erro(str(exc))

    @app.route("/curtos/<pid>/voz/divisao", methods=["POST"])
    def curto_voz_divisao(pid: str):
        """✂ v84_339: gravar por bloco do roteiro, até o ponto ou em frases curtas (os takes já gravados ficam guardados)."""
        _dono(pid)
        if GV.avulsa(pid):
            return _erro("No texto livre a divisão é escolhida em ✏ trocar o texto.")
        try:
            return _ok(estado=GV.trocar_divisao(base_dir, pid, str(_corpo().get("divisao") or "")))
        except CT.CurtoErro as exc:
            return _erro(str(exc))

    @app.route("/curtos/<pid>/voz/clipe", methods=["GET"])
    def curto_voz_clipe(pid: str):
        """🎞 o vídeo original, pra você ver enquanto lê."""
        c = next(iter(CC.clipes(base_dir, _proj(pid))), None)
        if not c:
            abort(404)
        return send_file(c["caminho"], conditional=True)

    @app.route("/curtos/<pid>/voz/parte/<parte>", methods=["POST"])
    def curto_voz_gravar(pid: str, parte: str):
        _dono(pid)
        arq = request.files.get("audio")
        if not arq:
            return _erro("Mande o áudio.")
        import tempfile
        ext = os.path.splitext(secure_filename(arq.filename or "a.webm"))[1].lower() or ".webm"
        fd, tmp = tempfile.mkstemp(suffix=ext, dir=GV.pasta(base_dir, pid))
        os.close(fd)
        try:
            arq.save(tmp)
            r = GV.adicionar_take(base_dir, pid, parte, tmp)
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if request.form.get("realce") in ("1", "true"):
            try:
                GV.realce(base_dir, pid, parte, r["takeId"], True)
            except CT.CurtoErro:
                pass
        return jsonify(dict(ok=True, estado=GV.resumo(base_dir, pid), **r))

    @app.route("/curtos/<pid>/voz/parte/<parte>/<tid>/<acao>", methods=["POST"])
    def curto_voz_take(pid: str, parte: str, tid: str, acao: str):
        _dono(pid)
        try:
            if acao == "usar":
                GV.usar_take(base_dir, pid, parte, tid)
            elif acao == "apagar":
                GV.apagar_take(base_dir, pid, parte, tid)
            elif acao == "realce":
                GV.realce(base_dir, pid, parte, tid, _corpo().get("usar", True) is not False)
            else:
                abort(404)
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        return _ok(estado=GV.resumo(base_dir, pid))

    @app.route("/curtos/<pid>/voz/parte/<parte>/<tid>.wav", methods=["GET"])
    def curto_voz_audio(pid: str, parte: str, tid: str):
        _dono(pid)
        try:
            cam = GV.caminho_take(base_dir, pid, parte, tid, False if request.args.get("original") == "1" else None)
        except CT.CurtoErro:
            abort(404)
        if not os.path.isfile(cam):
            abort(404)
        return send_file(cam, mimetype="audio/wav", conditional=True, max_age=0)

    @app.route("/curtos/<pid>/voz/enviar", methods=["POST"])
    def curto_voz_enviar(pid: str):
        """✅ junta as partes → a sua voz alinhada ao roteiro → (link) segue a edição: câmera, editor, prints e MP4."""
        p = _proj(pid)
        b = _corpo()
        t = TAREFAS.get(pid)
        if t and not t.get("fim"):
            return _erro("Já está rodando.", 409)
        falta = GV.faltando(base_dir, pid)
        if falta:
            return _erro(f"Falta gravar {len(falta)} parte(s).")
        try:
            _transcrever()
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        realce_tudo = bool(b.get("realce_em_tudo"))
        continuar = b.get("continuar", True) is not False
        op = _opcoes()  # (lido aqui: a thread não tem o pedido)
        lr = p.get("link_rapido") or {}
        if not _reservar(pid, "🎤 sua voz → edição", "⏳ na fila (espera o vídeo que está gerando)"):
            return _erro("Já está rodando.", 409)

        def pr(m: str) -> None:
            TAREFAS[pid]["prog"] = str(m)[:300]

        def corpo() -> None:
            try:
                with _UM_LINK_POR_VEZ:
                    pr("🧩 juntando as partes" + (" (com realce)" if realce_tudo else "") + "…")
                    final = GV.juntar(base_dir, pid, realce_tudo)
                    if GV.aplicar_textos_no_roteiro(base_dir, pid):  # ✏ v84_341: os seus ajustes viram o roteiro
                        pr("✏ seus ajustes de texto entraram no roteiro")
                    pr("🎯 lendo a sua voz (Whisper): tira pausas longas e repetições, alinha ao roteiro (a legenda usa o texto do roteiro)…")
                    CT.processar_gravacao(base_dir, pid, _transcrever(), final, op, pr, fonte="gravacao")
                    if lr:
                        _link_etapa(pid, "🎤 voz recebida", aguardando_voz=False)
                    if continuar and lr:
                        TAREFAS[pid]["msg"] = _link_rodar(pid, "", lr.get("qualidade") or "1080p", lr.get("exportar", True), pr)
                    elif continuar:
                        TAREFAS[pid]["msg"] = _cm_final(pid, None, pr)
                    else:
                        TAREFAS[pid]["msg"] = "🎤 voz alinhada"
            except Exception as exc:  # noqa: BLE001
                TAREFAS[pid]["erro"] = str(exc)[:600]
                if lr:
                    _link_etapa(pid, "❌ erro", erro=str(exc)[:600])
            finally:
                TAREFAS[pid]["fim"] = time.time()
                _liberar_memoria_pesada()
        threading.Thread(target=corpo, daemon=True, name="minha-voz").start()
        return _ok(estado=GV.resumo(base_dir, pid))

    CB["rodar_link"] = _link_rodar  # 🔥 v84_291: os Momentos mais vistos usam o mesmo caminho (roteiro → voz → editor → MP4)

    # ------------------------------------------------------------------ 🧩 v84_320: lote POR ETAPA
    def _lote_paralelo() -> int:
        try:
            return max(1, min(4, int(os.environ.get("CURTOS_LOTE_PARALELO") or 2)))
        except ValueError:
            return 2

    def _chave_compat(pid: str) -> tuple:
        """🔑 o que obriga a trocar de modelo: motor de voz + voz + idioma. Quem bate fica junto (o modelo carrega 1 vez por sub-lote)."""
        try:
            p = CT.carregar(base_dir, pid)
        except CT.CurtoErro:
            return ("", "", "")
        cfg = p.get("config") or {}
        return (cfg.get("motor_perfil") or "", cfg.get("voz_tts") or "", CC.dados(p).get("idioma") or "")

    def _lote_por_etapa(pids: List[str], prog_lote: Callable[[str], None]) -> str:
        """🧩 cada etapa roda em TODOS os links antes da próxima. Cada vídeo mantém a própria configuração.
        1 ⬇ baixar + 💬 comentários (rede) ......... em paralelo (CURTOS_LOTE_PARALELO, padrão 2), RAM checada antes de cada link
        2 🎙 transcrever os clipes (Whisper) ......... um por vez, o Whisper carrega 1 vez
        3 👁 descrever + 📝 roteiro (IA) ............ em paralelo
        4 🎙 narração (TTS) .......................... um por vez, agrupado pela chave de compatibilidade (motor/voz/idioma)
        5 🎯 alinhar (Whisper) ....................... um por vez
        6 🎥 destaques → 🎬 editor → 🖼 prints → MP4 ... um por vez (a parte pesada), com a memória solta entre um e outro
        Um link que falha sai do lote; os outros seguem. Se o site cair, a retomada normal continua cada um de onde parou."""
        from concurrent.futures import ThreadPoolExecutor
        n = len(pids)
        falhou: Dict[str, str] = {}
        mids: Dict[str, List[str]] = {}
        num = {pid: k for k, pid in enumerate(pids, 1)}

        def pr(pid: str) -> Callable[[str], None]:
            def f(m: str) -> None:
                TAREFAS[pid]["prog"] = f"[{num[pid]}/{n}] " + str(m)[:280]
            return f

        def falha(pid: str, exc: Exception) -> None:
            falhou[pid] = str(exc)[:600]
            TAREFAS[pid]["erro"] = falhou[pid]
            TAREFAS[pid]["fim"] = time.time()
            try:
                _link_etapa(pid, "❌ erro", erro=falhou[pid])
            except Exception:  # noqa: BLE001
                pass

        def etapa(k: int, nome: str, fn: Callable[[str], None], paralelo: int = 1, ram_cada: bool = False,
                  ordem: Optional[Callable[[str], Any]] = None) -> None:
            vivos = [p for p in pids if p not in falhou]
            if ordem:
                vivos = sorted(vivos, key=ordem)
            if not vivos:
                return
            prog_lote(f"🧩 etapa {k}/6 · {nome} ({len(vivos)} vídeo(s))")
            for p in vivos:
                _link_etapa(p, f"🧩 {k}/6 · {nome} — na fila desta etapa")
                TAREFAS[p]["prog"] = f"[{num[p]}/{n}] ⏳ etapa {k}/6 · {nome} — esperando a vez"

            def um(p: str) -> None:
                try:
                    if ram_cada:
                        _espera_memoria(pr(p))
                    _link_etapa(p, f"🧩 {k}/6 · {nome}")
                    pr(p)(f"etapa {k}/6 · {nome}…")
                    fn(p)
                    if p not in falhou:  # ✓ v84_329: terminou a etapa — fica claro que está esperando os outros, não travado
                        _link_etapa(p, f"🧩 {k}/6 ✓ {nome} — esperando a próxima etapa")
                        pr(p)(f"✓ etapa {k}/6 pronta — esperando os outros vídeos do lote terminarem esta etapa")
                except Exception as exc:  # noqa: BLE001  (um link ruim não para os outros)
                    falha(p, exc)
            if paralelo > 1 and len(vivos) > 1:
                with ThreadPoolExecutor(max_workers=paralelo, thread_name_prefix="lote-etapa") as ex:
                    list(ex.map(um, vivos))
            else:
                for p in vivos:
                    um(p)

        def coletar(p: str) -> None:
            _link_coletar(p, pr(p))
            mids[p] = _cm_preparar(p, pr(p))

        def roteiro(p: str) -> None:
            _cm_roteiro(p, mids.get(p) or [], pr(p))

        def slug_de(p: str) -> str:
            return (CT.carregar(base_dir, p).get("config") or {}).get("voz_tts") or ""

        par = _lote_paralelo()
        esperando: set = set()  # 🎤 v84_325: voz própria — param depois do roteiro, esperando você gravar
        etapa(1, "⬇ baixando + 💬 comentários", coletar, paralelo=par, ram_cada=True)
        _espera_memoria(prog_lote)
        etapa(2, "🎙 transcrevendo os clipes", lambda p: _cm_transcrever(p, mids.get(p) or [], pr(p)))
        _liberar_memoria_pesada()  # o Whisper sai antes da IA/TTS
        etapa(3, "👁 descrevendo + 📝 roteiro", roteiro, paralelo=par, ram_cada=True)
        for p in [x for x in pids if x not in falhou]:
            try:
                q = CT.carregar(base_dir, p)
                if _minha_voz(q) and _cm_precisa_voz(q):
                    esperando.add(p)
                    _link_etapa(p, "🎤 grave a sua voz", aguardando_voz=True)
                    TAREFAS[p]["msg"] = "🎤 roteiro pronto — grave a sua voz"
                    TAREFAS[p]["fim"] = time.time()
            except Exception as exc:  # noqa: BLE001
                falha(p, exc)
        for p in esperando:
            falhou.setdefault(p, "")  # sai das próximas etapas (sem erro: a tarefa já fechou como "esperando a voz")
        _espera_memoria(prog_lote)
        etapa(4, "🎙 narração", lambda p: _cm_voz(p, slug_de(p), pr(p)), ordem=_chave_compat)
        _espera_memoria(prog_lote)
        etapa(5, "🎯 alinhando a voz", lambda p: _cm_alinhar(p, pr(p)))
        _liberar_memoria_pesada()

        prontos = 0
        fila6 = [x for x in pids if x not in falhou]
        for k6, p in enumerate(fila6, 1):
            _link_etapa(p, f"🧩 6/6 · 🎬 edição → exportar — na fila ({k6}/{len(fila6)})")
            TAREFAS[p]["prog"] = f"[{num[p]}/{n}] ⏳ etapa 6/6 — exporta um por vez ({k6}º da fila)"
        for p in fila6:  # 6: a parte pesada, um por vez
            try:
                _espera_memoria(pr(p))
                lr = CT.carregar(base_dir, p).get("link_rapido") or {}
                _link_etapa(p, "🧩 6/6 · 🎬 edição → exportar")
                msg = _cm_final(p, None, pr(p))
                TAREFAS[p]["msg"] = _link_finalizar(p, msg, lr.get("qualidade") or "1080p", lr.get("exportar", True), pr(p))
                prontos += 1
            except Exception as exc:  # noqa: BLE001
                falha(p, exc)
            finally:
                TAREFAS[p]["fim"] = TAREFAS[p].get("fim") or time.time()
                _liberar_memoria_pesada()
        erros = len([p for p in falhou if p not in esperando])
        return (f"🧩 por etapa: {prontos}/{n} prontos" + (f" · {len(esperando)} esperando a sua voz" if esperando else "")
                + (f" · {erros} com erro" if erros else ""))

    def _iniciar_lote_por_etapa(pids: List[str]) -> Any:
        """Põe o lote na fila geral (espera outro vídeo/lote que estiver rodando) e roda por etapa."""
        pids = [pid for pid in pids if _reservar(pid, "🧩 lote por etapa", "⏳ na fila (lote por etapa)")]  # (rodando: fica de fora)
        if not pids:
            return _erro("Esses vídeos já estão rodando.", 409)
        for pid in pids:  # a tarefa vem ANTES de tirar o "aguardando" (o vigia da retomada não pega no meio)
            _link_etapa(pid, "na fila", aguardando=False, lote_modo="etapa")

        def corpo(prog: Callable[[str], None]) -> str:
            try:
                with _UM_LINK_POR_VEZ:  # nunca junto com outro vídeo/lote
                    return _lote_por_etapa(pids, prog)
            finally:
                for pid in pids:  # nada fica "rodando" pra sempre se algo explodir fora das etapas
                    if pid in TAREFAS and not TAREFAS[pid].get("fim"):
                        TAREFAS[pid]["fim"] = time.time()
        return _rodar("lote-etapa:" + pids[0], f"🧩 lote por etapa ({len(pids)} vídeo(s))", corpo)

    @app.route("/curtos/acabamento", methods=["GET", "POST"])
    def curtos_acabamento():
        """🎨 o acabamento padrão de TODOS os shorts novos: @ do canal, legenda, sons do Pixabay."""
        cid = str(request.args.get("canal") or "")
        if request.method == "POST":
            b = _corpo()
            cid = str(b.pop("canal_id", "") or "")
            try:
                if cid:
                    CT.carregar_canal(base_dir, cid)
                return _ok(acabamento=CT.salvar_acabamento(base_dir, b, cid))
            except CT.CurtoErro as exc:
                return _erro(str(exc))
        return _ok(acabamento=CT.acabamento(base_dir, cid))

    def _voz_link_de(c: Dict[str, Any]) -> Dict[str, str]:
        """🎙 v84_322: idioma de postagem, idioma narrado e voz próprios do canal ('' = o do envio)."""
        v = c.get("voz_link") if isinstance(c.get("voz_link"), dict) else {}
        return {"lingua_post": v.get("lingua_post") if v.get("lingua_post") in CT.LINGUAS else "",
                "idioma": v.get("idioma") if v.get("idioma") in ("en", "pt") else "",
                "voz": str(v.get("voz") or "")[:120],
                "modo": "minha" if v.get("modo") == "minha" else ""}  # 🎤 v84_325: "minha" = você grava a voz

    def _canal_pelo_nome(grupo: str) -> str:
        """📂 v84_325: o termo em cima dos links pode ser o NOME ou o @ do canal ('@AnimalIQ26', 'AnimalIQ26', 'Animal IQ 26')."""
        alvo = re.sub(r"[^a-z0-9]", "", _chave_grupo(grupo))
        if not alvo:
            return ""
        for c in CT.listar_canais(base_dir):
            nomes = [c.get("nome") or "", c["id"]]
            try:
                nomes.append(str(CT.acabamento(base_dir, c["id"]).get("arroba") or ""))
                nomes.append(str(CT.carregar_canal(base_dir, c["id"]).get("nome") or ""))
            except Exception:  # noqa: BLE001
                pass
            if any(re.sub(r"[^a-z0-9]", "", _chave_grupo(x)) == alvo for x in nomes if x):
                return c["id"]
        return ""

    def _gravar_voz_link(c: Dict[str, Any], b: Dict[str, Any]) -> None:
        if isinstance(b.get("voz_link"), dict):
            c["voz_link"] = _voz_link_de({"voz_link": b["voz_link"]})

    @app.route("/curtos/acabamento/sugerir", methods=["POST"])
    def curtos_acabamento_sugerir():
        """🤖 v84_353: 5 estilos (@ + legenda) pelo nicho do canal — pra usar inteiros ou misturar."""
        import acabamento_extra as AX
        b = _corpo()
        cid = str(b.get("canal_id") or "")
        try:
            return _ok(estilos=AX.sugerir_estilos(base_dir, cid, variar=str(b.get("variar") or "")[:40]))
        except CT.CurtoErro as exc:
            return _erro(str(exc))

    @app.route("/curtos/acabamento/previa.jpg", methods=["GET"])
    def curtos_acabamento_previa():
        """🖼 v84_333: a prévia DE VERDADE — um quadro do canal com a tarja, a legenda e o @ queimados pelo mesmo libass do vídeo
        final. Os valores da tela (ainda não salvos) vêm em ?d=<json>."""
        import acabamento_extra as AX
        cid = str(request.args.get("canal") or "")
        try:
            if cid:
                CT.carregar_canal(base_dir, cid)
        except CT.CurtoErro:
            cid = ""
        a = CT.acabamento(base_dir, cid)
        try:
            novos = json.loads(request.args.get("d") or "{}")
            if isinstance(novos, dict):
                a.update(CT.limpar_acabamento(novos))
        except ValueError:
            pass
        import tempfile
        tmp = tempfile.mkdtemp(prefix="previa_acab_", dir=os.path.join(CT.raiz(base_dir)) if os.path.isdir(CT.raiz(base_dir)) else None)
        try:
            cam = AX.previa(base_dir, a, cid, tmp)
            with open(cam, "rb") as f_:
                dados = f_.read()
        except Exception as exc:  # noqa: BLE001
            return _erro(f"Não consegui fazer a prévia: {str(exc)[:200]}", 500)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        import io
        return send_file(io.BytesIO(dados), mimetype="image/jpeg", max_age=0)

    @app.route("/curtos/fontes", methods=["GET", "POST"])
    def curtos_fontes():
        """🔤 v84_333: as fontes do @ e da legenda; POST = enviar uma .ttf/.otf sua (vira "DP <nome>")."""
        import acabamento_extra as AX
        if request.method == "POST":
            arq = request.files.get("fonte")
            if not arq or not arq.filename or os.path.splitext(arq.filename)[1].lower() not in (".ttf", ".otf"):
                return _erro("Mande um arquivo .ttf ou .otf.")
            import tempfile
            fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(arq.filename)[1].lower())
            os.close(fd)
            try:
                arq.save(tmp)
                it = AX.instalar_fonte(tmp, request.form.get("nome") or os.path.splitext(arq.filename)[0])
            except Exception as exc:  # noqa: BLE001
                return _erro(f"Não consegui instalar essa fonte: {str(exc)[:200]}")
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            return _ok(fonte=it, fontes=AX.familias())
        return _ok(fontes=AX.familias())

    @app.route("/curtos/fontes/google", methods=["GET", "POST"])
    def curtos_fontes_google():
        """🔤 v84_338: GET = o catálogo (com o que já está instalado); POST {nome} = baixa e instala uma do Google Fonts."""
        import acabamento_extra as AX
        import fontes_google as FG
        if request.method == "POST":
            nome = str((request.get_json(silent=True) or {}).get("nome") or "")
            try:
                it = FG.baixar(nome)
            except FG.FonteErro as exc:
                return _erro(str(exc))
            except Exception as exc:  # noqa: BLE001  (sem internet, Google fora…)
                return _erro(f"Não consegui baixar: {str(exc)[:200]}")
            return _ok(fonte=it, fontes=AX.familias())
        return _ok(catalogo=FG.catalogo(), fontes=AX.familias())

    def _canais_out() -> list:
        out = []
        for c in CT.listar_canais(base_dir):
            try:
                cc = CT.carregar_canal(base_dir, c["id"])
            except CT.CurtoErro:
                continue
            out.append({"id": cc["id"], "nome": cc.get("nome") or cc["id"], "personalizado": bool(cc.get("acabamento")),
                        "descricao": cc.get("descricao") or "", "voz_link": _voz_link_de(cc), "persona": cc.get("persona") or ""})
        return out

    @app.route("/curtos/canais-link", methods=["GET"])
    def curtos_canais_link():
        """🎚 v84_310: os canais (perfis) pra escolher no link — cada um com a própria legenda/@/destaques."""
        return _ok(canais=_canais_out())

    @app.route("/curtos/canais/exportar", methods=["GET"])
    def curtos_canais_exportar():
        """📦 v84_336: os canais (com estilo e tudo) num ZIP — mídias do canal + as fontes enviadas que ele usa — ou só o JSON."""
        import io
        import canais_pacote as PK
        ids = [x for x in str(request.args.get("ids") or "").split(",") if CT._valido(x)]
        formato = "json" if request.args.get("formato") == "json" else "zip"
        try:
            dados, nome = PK.exportar(base_dir, ids, formato, request.args.get("padrao") == "1")
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        return send_file(io.BytesIO(dados), mimetype="application/json" if formato == "json" else "application/zip",
                         as_attachment=True, download_name=nome)

    @app.route("/curtos/canais/importar", methods=["POST"])
    def curtos_canais_importar():
        """📥 v84_336: o .zip/.json exportado em outro PC. modo: copia (padrão) ou substituir (mesmo id)."""
        import canais_pacote as PK
        arq = request.files.get("pacote")
        if not arq:
            return _erro("Mande o arquivo .zip ou .json do pacote.")
        try:
            r = PK.importar(base_dir, arq.read(), arq.filename or "", request.form.get("modo") or "copia",
                            request.form.get("padrao") in ("1", "true", "on"))
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        return _ok(resultado=r, canais=_canais_out())

    @app.route("/curtos/canais/novo", methods=["POST"])
    def curtos_canal_novo_link():
        """➕ um canal novo: nome + descrição; a legenda/posição você ajusta no 🎨 acabamento dele."""
        b = _corpo()
        try:
            with CT._TRAVA:
                c = CT.criar_canal(base_dir, str(b.get("nome") or ""), "", str(b.get("descricao") or ""))
                if isinstance(b.get("voz_link"), dict):
                    _gravar_voz_link(c, b)
                    CT.salvar_canal(base_dir, c)
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        return _ok(id=c["id"], canais=_canais_out())

    @app.route("/curtos/canais/<cid>/apagar", methods=["POST"])
    def curtos_canal_apagar_link(cid: str):
        """🗑 v84_339: apaga o canal (pela página de Personalização) — os vídeos já feitos ficam."""
        if not CT._valido(cid):
            return _erro("Canal inválido.")
        try:
            CT.carregar_canal(base_dir, cid)
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        CT.excluir_canal(base_dir, cid)
        return _ok(canais=_canais_out())

    @app.route("/curtos/canais/<cid>/editar", methods=["POST"])
    def curtos_canal_editar(cid: str):
        """✎ muda o nome e/ou a descrição do canal."""
        b = _corpo()
        try:
            with CT._TRAVA:
                c = CT.carregar_canal(base_dir, cid)
                if str(b.get("nome") or "").strip():
                    c["nome"] = " ".join(str(b["nome"]).split())[:80]
                if "descricao" in b:
                    c["descricao"] = str(b.get("descricao") or "").strip()[:1500]
                if "persona" in b:  # 🎭 v84_345: a personalidade do narrador (o modo 🎭 do roteiro usa)
                    c["persona"] = str(b.get("persona") or "").strip()[:1500]
                _gravar_voz_link(c, b)
                CT.salvar_canal(base_dir, c)
        except CT.CurtoErro as exc:
            return _erro(str(exc))
        return _ok(canais=_canais_out())

    @app.route("/curtos/personalizar", methods=["GET"])
    def curtos_personalizar():
        """🎨 v84_335: a aba só de personalização — o mesmo editor do acabamento, com uma aba pra cada canal."""
        return curtos_link_pagina(so_personalizar=True)

    @app.route("/curtos/link", methods=["GET"])
    def curtos_link_pagina(so_personalizar: bool = False):
        try:
            import anime2d as A
            vozes_en = A.vozes_disponiveis("chatterbox_turbo")
            vozes = A.vozes_disponiveis("chatterbox")
        except Exception:  # noqa: BLE001
            vozes_en, vozes = [], []
        import qualidade_export
        import dp_legendas
        import acabamento_extra as _AXr
        return render_template("curtos_link.html", situacoes=SITUACOES, fontes_legenda=_AXr.familias(), cores_legenda=CT.CORES_LEGENDA, modos=CL.MODOS, direcoes_titulo={k: v[0] for k, v in CC.DIRECOES_TITULO.items()}, linguas=CT.LINGUAS, proporcoes=CT.PROPORCOES,
                               estilos_legenda=[{"id": e["id"], "nome": e["nome"]} for e in dp_legendas.ESTILOS],
                               vozes_en=vozes_en, vozes=vozes, resolucoes=qualidade_export.RESOLUCOES, ia=_ia_ligada(),
                               tem_tts=bool(CB["tts"]), tem_export=bool(CB.get("exportar")), so_personalizar=so_personalizar)

    @app.route("/curtos/link/estado", methods=["GET"])
    def curtos_link_estado():
        return _ok(videos=_links())

    @app.route("/curtos/link/grupos", methods=["GET"])
    def curtos_link_grupos():
        """📂 os grupos (palavra → canal) que valem pra colar lista de links."""
        out = []
        for chave, g in _grupos_ler(base_dir).items():
            try:
                nome_canal = CT.carregar_canal(base_dir, g.get("canal_id") or "").get("nome") or ""
            except CT.CurtoErro:
                nome_canal = ""
            out.append({"chave": chave, "nome": g.get("nome") or chave, "canal_id": g.get("canal_id") or "", "canal": nome_canal})
        return _ok(grupos=sorted(out, key=lambda x: x["nome"].lower()))

    @app.route("/curtos/link/grupos", methods=["POST"])
    def curtos_link_grupos_salvar():
        """📂 liga um grupo a um canal (ou tira a ligação se canal vier vazio)."""
        b = _corpo()
        nome = " ".join(_nome_do_grupo(b.get("nome")).split())[:60]
        if not nome:
            return _erro("Dê um nome ao grupo (ex.: Animais).")
        chave = _chave_grupo(nome)
        with CT._TRAVA:
            dados = _grupos_ler(base_dir)
            cid = str(b.get("canal_id") or "")
            if cid:
                try:
                    CT.carregar_canal(base_dir, cid)
                except CT.CurtoErro:
                    return _erro("Esse canal não existe mais.")
                dados[chave] = {"nome": nome, "canal_id": cid}
                for termo in _termos_do_grupo(nome):  # 📂 v84_353: "Comida, Food" liga os dois termos (cada um sozinho também vale)
                    dados[_chave_grupo(termo)] = {"nome": termo, "canal_id": cid}
            else:
                dados.pop(chave, None)
                for termo in _termos_do_grupo(nome):
                    dados.pop(_chave_grupo(termo), None)
            _grupos_gravar(base_dir, dados)
        return curtos_link_grupos()

    _ENVIOS_RECENTES: Dict[str, float] = {}

    @app.route("/curtos/link/novo", methods=["POST"])
    def curtos_link_novo():
        b = _corpo()
        mapa_g = _grupos_ler(base_dir)
        dicas_: Dict[str, str] = {}
        pares = _separar_grupos(str(b.get("link") or ""), lambda t: any(_chave_grupo(x) in mapa_g or bool(_canal_pelo_nome(x))
                                                                        for x in [t] + _termos_do_grupo(t)), dicas_)[:50]  # 🔗 v84_306: até 50; 📂 v84_318: cada grupo com o seu canal; 💡 v84_353: dicas
        agora_ = time.time()
        with _TRAVA_T:  # 🔒 v84_350 (idempotência): o mesmo link mandado de novo em 30 s (clique duplo, 2 abas) não vira 2 vídeos
            for k_ in [k_ for k_, t_ in _ENVIOS_RECENTES.items() if agora_ - t_ > 30]:
                _ENVIOS_RECENTES.pop(k_, None)
            repetidos = [u for u, _ in pares if u in _ENVIOS_RECENTES]
            pares = [(u, g) for u, g in pares if u not in _ENVIOS_RECENTES]
            for u, _ in pares:
                _ENVIOS_RECENTES[u] = agora_
        if repetidos and not pares:
            return _erro(f"Esse(s) link(s) acabou(aram) de ser enviado(s) — {len(repetidos)} repetido(s) ignorado(s).", 409)
        links = [u for u, _ in pares]
        if not links:
            return _erro("Cole o link do vídeo (TikTok, Shorts, Reels, Kwai…).")
        modo = b.get("modo") if b.get("modo") in CL.MODOS else "auto"
        lp = b.get("lingua_post") if b.get("lingua_post") in CT.LINGUAS else "en"
        narrar_pt = b.get("idioma") == "pt"
        qualidade = str(b.get("qualidade") or "1080p")
        exportar = b.get("exportar", True) not in (False, "0", "", "false")
        criados = []
        canal_escolhido = str(b.get("canal_id") or "")
        try:
            if canal_escolhido:
                CT.carregar_canal(base_dir, canal_escolhido)
            else:
                canal_escolhido = CT.canal_do_modelo(base_dir, "comentario")
        except CT.CurtoErro:
            canal_escolhido = CT.canal_do_modelo(base_dir, "comentario")
        iniciar = bool(b.get("iniciar"))  # 🕐 v84_319: por padrão os links ficam aguardando; você inicia depois
        por_etapa = bool(b.get("por_etapa")) and len(pares) > 1  # 🧩 v84_320: lote por etapa (só com 2+ links)
        mapa = _grupos_ler(base_dir)
        cache_canal: Dict[str, str] = {}
        voz_canal: Dict[str, Dict[str, str]] = {}
        cache_nome: Dict[str, str] = {}
        acab_canal: Dict[str, Dict[str, Any]] = {}
        for url, grupo in pares:  # 🔗 vários links = vários vídeos, um depois do outro
            canal_do_link = canal_escolhido
            g = mapa.get(_chave_grupo(grupo)) or {}
            for termo in ([] if g.get("canal_id") else _termos_do_grupo(grupo)):  # 📂 v84_353: qualquer termo da lista vale
                g = mapa.get(_chave_grupo(termo)) or {}
                if g.get("canal_id"):
                    break
            if not g.get("canal_id") and grupo:  # 📂 v84_325: o termo é o nome/@ de um canal → vai pra ele
                for termo in [grupo] + _termos_do_grupo(grupo):
                    cid_nome = cache_nome.setdefault(termo, _canal_pelo_nome(termo))
                    if cid_nome:
                        g = {"canal_id": cid_nome}
                        break
            if g.get("canal_id"):
                if g["canal_id"] not in cache_canal:
                    try:
                        CT.carregar_canal(base_dir, g["canal_id"])
                        cache_canal[g["canal_id"]] = g["canal_id"]
                    except CT.CurtoErro:
                        cache_canal[g["canal_id"]] = ""
                canal_do_link = cache_canal[g["canal_id"]] or canal_escolhido
            fontes_ = url.split(",") if "," in url else [url]  # 🧩 v84_349: vídeo composto (várias fontes)
            url = fontes_[0]
            p = CT.criar(base_dir, canal_do_link, ("🧩 " if len(fontes_) > 1 else "🔗 ") + url.split("?")[0][-60:], [], "", modelo="comentario")
            pid = p["id"]
            if canal_do_link not in voz_canal:  # 🎙 v84_322: o canal pode ter idioma e voz próprios
                try:
                    voz_canal[canal_do_link] = _voz_link_de(CT.carregar_canal(base_dir, canal_do_link)) if canal_do_link else {}
                except CT.CurtoErro:
                    voz_canal[canal_do_link] = {}
            vc = voz_canal[canal_do_link]
            lp_ = vc.get("lingua_post") or lp
            pt_ = (vc["idioma"] == "pt") if vc.get("idioma") else narrar_pt
            with CT._TRAVA:
                p = CT.carregar(base_dir, pid)
                c = CC.dados(p)
                c["lingua_post"], c["idioma"] = lp_, ("pt" if pt_ else "en")
                narrada = "pt" if pt_ else lp_
                p["config"]["motor_perfil"] = "chatterbox_turbo" if narrada == "en" else "chatterbox"  # 🇺🇸 inglês: o Turbo (tags de voz)
                if canal_do_link not in acab_canal:  # 📐 v84_335: o canal com formato próprio manda no formato do envio
                    acab_canal[canal_do_link] = CT.acabamento(base_dir, canal_do_link)
                if b.get("proporcao") in CT.PROPORCOES and not acab_canal[canal_do_link].get("proporcao"):
                    p["config"]["proporcao"] = b["proporcao"]
                try:
                    dur = int(float(b.get("duracao") or 0))
                    if dur and not (len(fontes_) > 1 and dur < 60):  # 🧩 o composto tem 60 s ou mais (abaixo disso: a IA decide, 60+)
                        p["config"]["duracao_alvo_s"] = max(10, min(180, dur))
                except (TypeError, ValueError):
                    pass
                if b.get("extra"):
                    p["config"]["extra"] = str(b["extra"])[:2000]
                if vc.get("voz"):
                    p["config"]["voz_tts"] = str(vc["voz"])[:120]
                elif b.get("voz") and (narrada == "en") == (("pt" if narrar_pt else lp) == "en"):
                    p["config"]["voz_tts"] = str(b["voz"])[:120]  # a voz do envio só se for do mesmo motor
                p["config"]["takes"] = 1  # ⚡ automático: 1 take (os outros dá pra gerar depois na página do curto)
                p["config"]["estilo_roteiro"] = ("classico" if b.get("roteiro_classico") is True else
                                                 "personalidade" if b.get("roteiro_personalidade") is True else "autentico")  # ✨ v84_321 · 🎭 v84_345
                p["config"]["camera_exp"] = b.get("camera_exp", True) not in (False, "0", "false")  # 🎥 v84_322 (padrão: ligada)
                p["config"]["retencao"] = b.get("retencao", True) not in (False, "0", "false")  # 🧲 v84_354 (padrão: ligado)
                if b.get("final_loop") is True:  # 🔁 v84_354: só se você pedir
                    p["config"]["final_loop"] = True
                if b.get("tambem_quadrado") is True and CT.proporcao_do(p) != "1:1":  # ⬛ v84_334: também a versão 1:1
                    p["config"]["tambem_quadrado"] = True
                if vc.get("modo") == "minha":  # 🎤 v84_325: o canal é de voz própria
                    p["config"]["voz_modo"] = "minha"
                if len(fontes_) > 1:
                    p["config"]["composto"] = len(fontes_)
                dica_ = dicas_.get(",".join(fontes_) if len(fontes_) > 1 else url) or ""
                p["link_rapido"] = {"link": url, "modo": modo, "criado": time.time(), "qualidade": qualidade, "exportar": exportar,
                                    **({"dica": dica_} if dica_ else {}),
                                    **({"links": fontes_} if len(fontes_) > 1 else {}),
                                    "comentarios_colados": str(b.get("comentarios") or "")[:20000],
                                    "etapa": "na fila" if iniciar else "⏸ aguardando", "aguardando": not iniciar,
                                    "lote_modo": "etapa" if por_etapa else "um"}
                CT.salvar(base_dir, p)
            criados.append(pid)
        slug = str(b.get("voz") or "")

        def fila(prog: Callable[[str], None]) -> str:
            feitos = 0
            for k, pid in enumerate(criados, 1):
                TAREFAS[pid] = {"rotulo": "🔗 link → vídeo", "inicio": time.time(), "fim": None, "erro": None, "msg": "",
                                "prog": "⏳ na fila (espera o vídeo que está gerando)"}

                def pr(m: str, pid=pid, k=k) -> None:
                    TAREFAS[pid]["prog"] = (f"[{k}/{len(criados)}] " if len(criados) > 1 else "") + str(m)[:280]
                    prog(m)
                try:
                    with _UM_LINK_POR_VEZ:  # 🔗 v84_306: outra lista colada depois espera esta (nunca 2 vídeos ao mesmo tempo)
                        _espera_memoria(pr)  # 🧠 v84_313: RAM baixa → espera antes de começar
                        TAREFAS[pid]["prog"] = "começando…"
                        TAREFAS[pid]["msg"] = _link_rodar(pid, (CT.carregar(base_dir, pid).get("config") or {}).get("voz_tts") or slug,
                                                          qualidade, exportar, pr)  # 🎙 v84_322: a voz do canal do link
                    feitos += 1
                except Exception as exc:  # noqa: BLE001  (um link ruim não para os outros)
                    TAREFAS[pid]["erro"] = str(exc)[:600]
                    try:
                        _link_etapa(pid, "❌ erro", erro=str(exc)[:600])
                    except Exception:  # noqa: BLE001
                        pass
                finally:
                    TAREFAS[pid]["fim"] = time.time()
                    _liberar_memoria_pesada()  # 🧹 v84_313: solta a memória antes do próximo da lista
            return f"{feitos}/{len(criados)} prontos"
        if not iniciar:
            return _ok(criados=criados, videos=_links())
        if por_etapa and len(criados) > 1:
            r = _iniciar_lote_por_etapa(criados)
            if isinstance(r, tuple):
                return r
            return _ok(criados=criados, videos=_links(), por_etapa=True)
        for pid in criados:
            TAREFAS[pid] = {"rotulo": "🔗 na fila", "inicio": time.time(), "fim": None, "erro": None, "msg": "", "prog": "⏳ na fila"}
        r = _rodar("link:" + criados[0], "🔗 link → vídeo", fila)
        if isinstance(r, tuple):
            return r
        return _ok(criados=criados, videos=_links())

    def _apagar_arquivos_link(pid: str) -> None:
        """🗑 apaga os arquivos do vídeo (exportado, projeto do editor, clipes, prints). Fica só o link, as marcas, o comentário e o log."""
        p = CT.carregar(base_dir, pid)
        t = TAREFAS.get(pid) or {}
        if t and not t.get("fim"):
            raise CT.CurtoErro("Está sendo feito agora — espere terminar.")
        lr = dict(p.get("link_rapido") or {})
        apagados = []
        arq = (p.get("exportado") or {}).get("arquivo") or ""
        if arq and os.path.isfile(arq):
            os.remove(arq)
            apagados.append("vídeo exportado")
        arq_q = (p.get("exportado_quadrado") or {}).get("arquivo") or ""  # ⬛ v84_334
        if arq_q and os.path.isfile(arq_q):
            os.remove(arq_q)
            apagados.append("versão 1:1")
        job_id = (p.get("editor") or {}).get("job_id") or ""
        if job_id and CB.get("apagar_editor"):
            CB["apagar_editor"](job_id)
            apagados.append("projeto do editor")
        job_q = (p.get("exportado_quadrado") or {}).get("job_id") or ""
        if job_q and CB.get("apagar_editor"):
            CB["apagar_editor"](job_q)
        pasta_p = CT.pasta(base_dir, pid)
        for nome in os.listdir(pasta_p):
            if nome == "projeto.json":
                continue
            caminho = os.path.join(pasta_p, nome)
            if os.path.isdir(caminho):
                shutil.rmtree(caminho, ignore_errors=True)
            else:
                os.remove(caminho)
        apagados.append("clipes, áudios e prints")
        _log_link(lr, "🗑 arquivos apagados: " + ", ".join(apagados) + " — ficou só o link e este log")
        lr.update(apagado=True, apagado_em=time.time(), etapa="🗑 apagado", erro="", parado=False)
        if lr.get("escolha"):
            lr["escolha"].pop("capa", None)  # a capa escolhida foi apagada junto com os prints
        novo = {k: p[k] for k in ("id", "titulo", "modelo", "criado", "canal_id") if k in p}
        novo["link_rapido"] = lr
        with CT._TRAVA:
            CT.salvar(base_dir, novo)

    @app.route("/curtos/link/<pid>/editar", methods=["POST"])
    def curtos_link_editar(pid: str):
        """🏷 marca (vermelho descartado · azul postado · amarelo com planos) e comentário, num vídeo já feito."""
        p = _proj(pid)
        if not p.get("link_rapido"):
            abort(404)
        b = _corpo()
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            lr = q["link_rapido"]
            if "marca" in b:
                m = str(b.get("marca") or "")
                if m not in MARCAS_LINK:
                    return _erro("Marca inválida.")
                if m != (lr.get("marca") or ""):
                    lr["marca"] = m
                    _log_link(lr, "marcado como " + MARCAS_LINK[m])
            for k_ in ("musica", "local"):  # 🎵📍 v84_351: vazio = volta ao que a plataforma informou
                if k_ in b:
                    v_ = " ".join(str(b.get(k_) or "").split())[:160]
                    if v_:
                        lr[k_] = v_
                    else:
                        lr.pop(k_, None)
            if "comentario" in b:
                c = str(b.get("comentario") or "").strip()[:1000]
                if c != (lr.get("comentario") or ""):
                    lr["comentario"] = c
                    _log_link(lr, ("💬 comentário: " + c[:150]) if c else "comentário apagado")
            CT.salvar(base_dir, q)
        return _ok(videos=_links())

    @app.route("/curtos/link/<pid>/escolha", methods=["POST"])
    def curtos_link_escolha(pid: str):
        """⭐ marca o título e a capa (print) que você quer num vídeo pronto — fica salvo e vai pro pacote de exportação."""
        p = _proj(pid)
        if not p.get("link_rapido"):
            abort(404)
        b = _corpo()
        with CT._TRAVA:
            q = CT.carregar(base_dir, pid)
            esc_ = dict((q["link_rapido"].get("escolha") or {}))
            if "titulo" in b:
                esc_["titulo"] = " ".join(str(b.get("titulo") or "").split())[:300]
            if "capa" in b:
                if b.get("capa") in (None, "", 0):
                    esc_.pop("capa", None)
                else:
                    try:
                        k = int(b["capa"])
                    except (TypeError, ValueError):
                        return _erro("Capa inválida.")
                    if not 1 <= k <= len(q.get("thumbs") or []):
                        return _erro("Essa capa não existe mais — tire os prints de novo.")
                    esc_["capa"] = k
            q["link_rapido"]["escolha"] = {x: y for x, y in esc_.items() if y}
            CT.salvar(base_dir, q)
        return _ok(videos=_links())

    # 📤 v84_355: enviar pro YouTube (API oficial) com a capa, na agenda de cada canal
    import youtube_envio as YE

    def _yt_meta(pid: str) -> Optional[Dict[str, Any]]:
        try:
            p = CT.carregar(base_dir, pid)
        except CT.CurtoErro:
            return None
        v = _link_resumo(p)
        r = p.get("roteiro") or {}
        esc_ = v.get("escolha") or {}
        titulo = esc_.get("titulo") or r.get("titulo_video") or next((t["en"] for t in v.get("titulos") or [] if t.get("en")), "") or v["titulo"]
        ts = p.get("thumbs") or []
        k = esc_.get("capa") if esc_.get("capa") and 1 <= esc_["capa"] <= len(ts) else (1 if ts else 0)  # sem capa escolhida: o 1º print
        thumb = os.path.join(CT.pasta(base_dir, pid), "thumbs", ts[k - 1]["arquivo"]) if k else ""
        return {"titulo": titulo, "descricao": v.get("descricao") or "", "hashtags": v.get("hashtags") or [],
                "video": (p.get("exportado") or {}).get("arquivo") or "", "thumb": thumb if thumb and os.path.isfile(thumb) else ""}

    def _yt_item(pid: str) -> Optional[Dict[str, Any]]:
        try:
            p = CT.carregar(base_dir, pid)
        except CT.CurtoErro:
            return None
        v = _link_resumo(p)
        return {"pid": pid, "canal_id": v.get("canal_id") or "", "canal": v.get("canal") or "", "nome": (_yt_meta(pid) or {}).get("titulo") or v["titulo"] or pid,
                "pronto": v.get("pronto")}

    YE.registrar(app, base_dir, meta_de=_yt_meta, item_de=_yt_item, canais=lambda: CT.listar_canais(base_dir))
    CC.CONTEXTO_TITULOS = lambda b, p: YE.contexto_titulos(b, p.get("canal_id") or "")  # 📺 v84_356

    @app.route("/curtos/link/exportar-escolhidos", methods=["GET"])
    def curtos_link_exportar_escolhidos():
        """📦 exporta, de cada vídeo com título ou capa escolhidos: roteiro, títulos, título escolhido e a capa — em ZIP (pacote.json + capas) ou só JSON."""
        import io
        import zipfile
        formato = request.args.get("formato") or "zip"
        marcados = {x for x in str(request.args.get("ids") or "").split(",") if x}  # ☑ v84_331: os que você marcou na lista
        registros, arquivos = [], []
        for v in _links(500):
            esc_ = v.get("escolha") or {}
            if marcados:
                if v["id"] not in marcados:
                    continue
            elif not (esc_.get("titulo") or esc_.get("capa")):
                continue
            p = CT.carregar(base_dir, v["id"])
            r = p.get("roteiro") or {}
            rec = {"id": v["id"], "link": v["link"], "criado": v["criado"], "canal": v["canal"],
                   "modo": v.get("modo_usado") or v["modo"], "marca": v["marca"], "comentario": v["comentario"], "musica": v.get("musica") or "", "local": v.get("local") or "",
                   "apagado": v["apagado"], "titulo_escolhido": esc_.get("titulo") or "",
                   "titulos": CN.titulos_do_projeto(p),
                   "roteiro": " ".join(CT.sem_tags(b.get("fala") or "") for b in r.get("blocos") or []),
                   "roteiro_com_tags": " ".join(b.get("fala") or "" for b in r.get("blocos") or []),
                   "descricao": v["descricao"], "hashtags": r.get("hashtags") or [], "capa": None}
            k = esc_.get("capa")
            ts = p.get("thumbs") or []
            if k and 1 <= k <= len(ts):
                cam = os.path.join(CT.pasta(base_dir, v["id"]), "thumbs", ts[k - 1]["arquivo"])
                if os.path.isfile(cam):
                    nome = f"capas/{v['id']}_{k}.jpg"
                    rec["capa"] = {"arquivo": nome, "por_que": ts[k - 1].get("por_que") or ""}
                    arquivos.append((nome, cam))
            elif marcados:  # ☑ marcado sem capa escolhida: vão os prints que ele tiver (você escolhe depois)
                rec["prints"] = []
                for j, t in enumerate(ts, 1):
                    cam = os.path.join(CT.pasta(base_dir, v["id"]), "thumbs", t.get("arquivo") or "_")
                    if os.path.isfile(cam):
                        nome = f"capas/{v['id']}_print{j}.jpg"
                        rec["prints"].append({"arquivo": nome, "por_que": t.get("por_que") or ""})
                        arquivos.append((nome, cam))
            registros.append(rec)
        pacote = {"gerado_em": time.strftime("%Y-%m-%d %H:%M:%S"), "total": len(registros), "videos": registros}
        texto = json.dumps(pacote, ensure_ascii=False, indent=2)
        if formato == "json":
            return send_file(io.BytesIO(texto.encode("utf-8")), mimetype="application/json", as_attachment=True,
                             download_name="escolhidos.json")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("pacote.json", texto)
            for nome, cam in arquivos:
                z.write(cam, nome)
        buf.seek(0)
        return send_file(buf, mimetype="application/zip", as_attachment=True, download_name="escolhidos.zip")

    @app.route("/curtos/link/iniciar-marcados", methods=["POST"])
    def curtos_link_iniciar_marcados():
        """▶ v84_332: produz os marcados que ainda estão na fila (aguardando, com erro ou parados no meio) — um por vez ou
        🧩 por etapa (em paralelo). Os já prontos, apagados, rodando ou esperando a sua voz ficam de fora."""
        b = _corpo()
        pedidos = [str(x) for x in (b.get("ids") or []) if CT._valido(str(x))][:500]
        ids, pulados = [], 0
        por_data = sorted(pedidos, key=lambda x: ((CT.carregar(base_dir, x).get("link_rapido") or {}).get("criado") or 0)
                          if os.path.isdir(CT.pasta(base_dir, x)) else 0)  # na ordem em que foram colados
        for pid in por_data:
            try:
                p = CT.carregar(base_dir, pid)
            except CT.CurtoErro:
                continue
            lr = p.get("link_rapido") or {}
            t = TAREFAS.get(pid) or {}
            if (not lr or lr.get("apagado") or lr.get("aguardando_voz") or (t and not t.get("fim"))
                    or lr.get("etapa") in ("✅ pronto", "✅ no editor")):
                pulados += 1
                continue
            ids.append(pid)
        por_etapa = bool(b.get("por_etapa")) and len(ids) > 1
        if not ids:
            return _ok(iniciados=0, pulados=pulados, por_etapa=False, videos=_links())
        for pid in ids:
            _link_etapa(pid, "na fila", aguardando=False, erro="", parado=False)
        if por_etapa:
            r = _iniciar_lote_por_etapa(ids)
            if isinstance(r, tuple):
                return r
            return _ok(iniciados=len(ids), pulados=pulados, por_etapa=True, videos=_links())
        reservados = [pid for k, pid in enumerate(ids, 1) if _reservar(pid, "🔗 link → vídeo", f"⏳ na fila dos marcados ({k}/{len(ids)})")]
        pulados += len(ids) - len(reservados)  # 🔒 v84_350: quem começou a rodar entre o olhar e o marcar fica de fora
        ids = reservados

        def corpo() -> None:
            for pid in ids:
                pr = (lambda m, pid=pid: TAREFAS[pid].__setitem__("prog", str(m)[:300]))
                try:
                    with _UM_LINK_POR_VEZ:
                        _espera_memoria(pr)
                        p = CT.carregar(base_dir, pid)
                        lr = p.get("link_rapido") or {}
                        TAREFAS[pid]["msg"] = _link_rodar(pid, (p.get("config") or {}).get("voz_tts") or "", lr.get("qualidade") or "1080p",
                                                          lr.get("exportar", True), pr)
                except Exception as exc:  # noqa: BLE001  (um que falha não para os outros)
                    TAREFAS[pid]["erro"] = str(exc)[:600]
                    _link_etapa(pid, "❌ erro", erro=str(exc)[:600])
                finally:
                    TAREFAS[pid]["fim"] = time.time()
                    _liberar_memoria_pesada()
        threading.Thread(target=corpo, daemon=True, name="marcados").start()
        return _ok(iniciados=len(ids), pulados=pulados, por_etapa=False, videos=_links())

    def _aplicar_acao_links(ids: List[str], acao: str) -> tuple:
        """☑ apagar os arquivos (fica o link e o log) ou tirar da lista de vez. Os que estão rodando ficam de fora."""
        feitos, falhas = [], []
        for pid in ids:
            t = TAREFAS.get(pid) or {}
            try:
                p = CT.carregar(base_dir, pid)
            except CT.CurtoErro:
                continue
            if not p.get("link_rapido"):
                continue
            if t and not t.get("fim"):
                falhas.append(f"{(p.get('titulo') or pid)[:40]}: está rodando agora")
                continue
            try:
                if acao == "apagar":
                    if not (p.get("link_rapido") or {}).get("apagado"):
                        _apagar_arquivos_link(pid)
                else:
                    for exp_ in ("exportado", "exportado_quadrado"):
                        arq = (p.get(exp_) or {}).get("arquivo") or ""
                        if arq and os.path.isfile(arq):
                            os.remove(arq)
                    for jid_ in ((p.get("editor") or {}).get("job_id") or "", (p.get("exportado_quadrado") or {}).get("job_id") or ""):
                        if jid_ and CB.get("apagar_editor"):
                            CB["apagar_editor"](jid_)
                    with CT._TRAVA:
                        CT.excluir(base_dir, pid)
                    TAREFAS.pop(pid, None)
                feitos.append(pid)
            except Exception as exc:  # noqa: BLE001  (um que falha não para os outros)
                falhas.append(f"{(p.get('titulo') or pid)[:40]}: {str(exc)[:120]}")
        return feitos, falhas

    @app.route("/curtos/link/limpar", methods=["POST"])
    def curtos_link_limpar():
        """🧹 v84_344: tira da lista (ou só apaga os arquivos de) TODOS os vídeos do filtro atual (canal/situação) — os que
        estão rodando ficam. Pede confirmar=true com o número que você viu (pra não apagar a mais se a lista mudou)."""
        b = _corpo()
        acao = b.get("acao") if b.get("acao") in ("apagar", "tirar") else ""
        if not acao:
            return _erro("Escolha o que fazer.")
        canal, sit = str(b.get("canal") or ""), str(b.get("situacao") or "")
        ps = _projetos_link()
        pend = set(_link_pendentes(ps))
        ids = [v["id"] for v in (_leve(p, pend) for p in ps)
               if not v["rodando"] and (not canal or v["canal_id"] == ("" if canal == "_sem" else canal)) and _situacao_ok(v, sit)]
        try:
            esperado = int(b.get("quantos"))
        except (TypeError, ValueError):
            esperado = -1
        if esperado != len(ids):
            return _erro(f"A lista mudou (agora são {len(ids)} vídeo(s) nesse filtro) — confira e tente de novo.", 409)
        feitos, falhas = _aplicar_acao_links(ids, acao)
        return _ok(feitos=len(feitos), falhas=falhas, videos=_links())

    @app.route("/curtos/link/selecionados", methods=["POST"])
    def curtos_link_selecionados():
        """☑ v84_331: o que fazer com os vídeos marcados na lista — "apagar" os arquivos (fica o link e o log) ou "tirar"
        da lista de vez (some tudo). Os que estão rodando ficam de fora."""
        b = _corpo()
        ids = [str(x) for x in (b.get("ids") or []) if CT._valido(str(x))][:500]
        acao = b.get("acao")
        if acao not in ("apagar", "tirar") or not ids:
            return _erro("Marque os vídeos e escolha o que fazer.")
        feitos, falhas = _aplicar_acao_links(ids, acao)
        return _ok(feitos=len(feitos), falhas=falhas, videos=_links())

    @app.route("/curtos/link/apagar-marcados", methods=["POST"])
    def curtos_link_apagar_marcados():
        """🗑 apaga os arquivos só dos vídeos marcados como descartado ou postado (não mexe nos planejados nem nos que estão rodando)."""
        feitos, falhas = [], []
        for v in _links(500):
            if v["marca"] not in ("descartado", "postado") or v["apagado"] or v["rodando"] or v["pendente"]:
                continue
            try:
                _apagar_arquivos_link(v["id"])
                feitos.append(v["id"])
            except Exception as exc:  # noqa: BLE001  (um que falha não para os outros)
                falhas.append(f"{v['titulo'][:40] or v['id']}: {exc}")
        return _ok(apagados=len(feitos), falhas=falhas, videos=_links())

    @app.route("/curtos/link/iniciar-aguardando", methods=["POST"])
    def curtos_link_iniciar_aguardando():
        """▶ inicia todos os links que estão aguardando, um depois do outro."""
        b = _corpo()
        ids = [v["id"] for v in _links(500) if v["aguardando"] and not v["rodando"] and not v["apagado"]]
        ids.reverse()  # _links vem do mais novo pro mais velho: o lote roda na ordem em que foram colados
        if "por_etapa" in b:
            por_etapa = bool(b.get("por_etapa"))
        else:
            por_etapa = any((CT.carregar(base_dir, pid).get("link_rapido") or {}).get("lote_modo") == "etapa" for pid in ids)
        if por_etapa and len(ids) > 1:  # 🧩 v84_320
            r = _iniciar_lote_por_etapa(ids)
            if isinstance(r, tuple):
                return r
            return _ok(iniciados=len(ids), por_etapa=True, videos=_links())
        for pid in ids:
            _link_etapa(pid, "na fila", aguardando=False)
        n = _retomar_fila() if ids else 0
        return _ok(iniciados=n, videos=_links())

    @app.route("/curtos/link/<pid>/remover", methods=["POST"])
    def curtos_link_remover(pid: str):
        """🗑 tira um link que ainda está aguardando da fila (não começou; a entrada some)."""
        p = _proj(pid)
        lr = p.get("link_rapido") or {}
        t = TAREFAS.get(pid) or {}
        if not lr.get("aguardando") or (t and not t.get("fim")):
            return _erro("Só dá pra remover um link que ainda está aguardando.", 409)
        with CT._TRAVA:
            CT.excluir(base_dir, pid)
        return _ok(videos=_links())

    @app.route("/curtos/link/<pid>/refazer", methods=["POST"])
    def curtos_link_refazer(pid: str):
        """🔁 tenta de novo do ponto em que parou (o que já está feito e em dia é pulado)."""
        p = _proj(pid)
        lr = p.get("link_rapido") or {}
        if not lr:
            abort(404)
        if lr.get("apagado"):
            return _erro("Este vídeo foi apagado (ficou só o link e o log).", 409)
        if not _reservar(pid, "🔗 link → vídeo", "começando…"):
            return _erro("Já está rodando.", 409)
        slug = (p.get("config") or {}).get("voz_tts") or ""

        def corpo() -> None:
            try:
                TAREFAS[pid]["prog"] = "⏳ na fila (espera o vídeo que está gerando)"
                with _UM_LINK_POR_VEZ:
                    _espera_memoria(lambda m: TAREFAS[pid].__setitem__("prog", str(m)[:300]))
                    TAREFAS[pid]["msg"] = _link_rodar(pid, slug, lr.get("qualidade") or "1080p", lr.get("exportar", True),
                                                      lambda m: TAREFAS[pid].__setitem__("prog", str(m)[:300]))
            except Exception as exc:  # noqa: BLE001
                TAREFAS[pid]["erro"] = str(exc)[:600]
                _link_etapa(pid, "❌ erro", erro=str(exc)[:600])
            finally:
                TAREFAS[pid]["fim"] = time.time()
                _liberar_memoria_pesada()  # 🧹 v84_314
        with CT._TRAVA:  # ✍ v84_343: o roteiro novo vai ser usado agora
            q = CT.carregar(base_dir, pid)
            if (q.get("link_rapido") or {}).pop("roteiro_mudou", None):
                CT.salvar(base_dir, q)
        _link_etapa(pid, "🔁 de novo", erro="", aguardando=False)
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
                q["destaques_rastreio"] = {}
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
            p.setdefault("destaques_rastreio", {})[cur["chave"]] = r["id"]
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
            if "texto" in (b.get("marca") or {}):  # 🏷 v84_347: você mudou o @ DESTE vídeo — ele não segue mais o do canal
                m["texto_manual"] = True
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
    with CT._TRAVA:  # 🔒 v84_350: com trava e atômico (2 sons baixando juntos: um sumia; arquivo pela metade = base de sons quebrada)
        try:
            with open(extras, encoding="utf-8") as f_:
                d = json.load(f_) if os.path.getsize(extras) else {}
        except (OSError, ValueError):
            d = {}
        lista = [s for s in d.get("sons") or [] if s.get("id") != item["id"]]
        lista.append(item)
        d["sons"] = lista
        CT._gravar_json(extras, d)
    dp_extras.recarregar()
    if not dp_sons.som(item["id"]):
        raise CT.CurtoErro("O som não entrou na base (veja os erros dos extras no 📘 Guia).")
    return item["id"]
