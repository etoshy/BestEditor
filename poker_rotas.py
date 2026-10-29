"""
Rotas da aba 🃏 Poker (v84_277): mesa animada (poker_mesa + poker_render), 🏆 ranking (poker_ranking) e
🎬 roteiros de documentário/tutorial/shorts com pesquisa e checagem (poker_doc).

Arquivos em <base>/poker (ou POKER_DIR): maos/<id>.json · avatares/<nome>.jpg · videos/*.mp4 · docs/<id>.json
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import unicodedata
from typing import Any, Callable, Dict, Optional

from flask import abort, jsonify, redirect, render_template, request, send_file, send_from_directory

import poker_3d as P3
import poker_doc as PD
import poker_mesa as PM
import poker_ranking as RK
import poker_render as PR

TAREFAS: Dict[str, Dict[str, Any]] = {}
CB: Dict[str, Any] = {}  # chamar (IA), pesquisar, checar, gravar — os testes trocam aqui
_TRAVA_T = threading.Lock()
_CANCELAR: set = set()
EXT_IMG = (".jpg", ".jpeg", ".png", ".webp")


def slug(nome: str) -> str:
    s = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:60] or "jogador"


def pastas(base: str) -> Dict[str, str]:
    raiz = os.environ.get("POKER_DIR") or os.path.join(base, "poker")
    out = {k: os.path.join(raiz, k) for k in ("maos", "avatares", "videos", "docs", "personagens")}
    for p in out.values():
        os.makedirs(p, exist_ok=True)
    out["raiz"] = raiz
    return out


def avatar_de(base: str, nome: str, pedido: str = "") -> str:
    """O arquivo de foto do jogador: o 'foto=' da mão (se existir na pasta) ou o enviado com o nome dele."""
    pa = pastas(base)["avatares"]
    if pedido and os.path.isfile(os.path.join(pa, os.path.basename(pedido))):
        return os.path.basename(pedido)
    s = slug(nome)
    for ext in EXT_IMG:
        if os.path.isfile(os.path.join(pa, s + ext)):
            return s + ext
    return ""


# ------------------------------------------------------------------ 🎭 personagens do modo 3D (gerados no Flow)
ESTILO_PERSONAGEM = ("dark gritty 1990s low-poly horror video game character, {desc}, seated at a poker table seen from the "
                     "other side, upper body and head facing the camera, hands resting near the table edge, harsh single overhead "
                     "lamp light, grimy worn textures, muted sepia, dark red and olive palette, PS1 era 3D style, unsettling but "
                     "not gory, plain solid pure green background (#00FF00 chroma key), no text, no table in the image")


def personagem_arquivo(pasta: str, nome: str) -> str:
    s = slug(nome)
    for ext in (".png", ".webp", ".jpg", ".jpeg"):
        if os.path.isfile(os.path.join(pasta, s + ext)):
            return s + ext
    return ""


def _pj(base: str) -> str:
    return os.path.join(pastas(base)["personagens"], "personagens.json")


def personagens(base: str) -> Dict[str, Any]:
    try:
        with open(_pj(base), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _salvar_personagens(base: str, d: Dict[str, Any]) -> None:
    with open(_pj(base) + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(_pj(base) + ".tmp", _pj(base))


def tirar_fundo(caminho: str, destino: str) -> str:
    """Fundo verde do Flow → PNG transparente (o personagem fica "sentado" na cena 3D)."""
    from PIL import Image
    try:
        import remover_fundo as RF
        out, _info = RF.remover(Image.open(caminho), "verde", recortar=True, lado_max=900)
    except Exception:  # noqa: BLE001  (sem numpy/cv2: usa a imagem como veio)
        out = Image.open(caminho).convert("RGBA")
    out.save(destino)
    return destino


def pedir_personagem(base: str, nome: str, descricao: str = "", com_foto: bool = True) -> Dict[str, Any]:
    """🎨 pede o personagem do jogador no Flow (com a foto dele de referência, se tiver)."""
    import shorts_ia as SI
    s = slug(nome)
    desc = " ".join(str(descricao or "").split())[:300] or "a mysterious masked card player in a worn jacket"
    pedido = {"tipo": "imagem", "origem": "poker", "prompt": ESTILO_PERSONAGEM.format(desc=desc)}
    foto = avatar_de(base, nome) if com_foto else ""
    if foto:
        pedido["referencia_arquivo"] = os.path.join(pastas(base)["avatares"], foto)
        pedido["prompt"] = ("Stylize the person in the reference photo (keep the face recognizable: hair, face shape, glasses, "
                            "beard) as a " + pedido["prompt"])
    j = SI._lote().adicionar([pedido], proporcao="9:16")[0]
    d = personagens(base)
    d[s] = {"nome": nome, "descricao": desc, "slot": dict(estado="fila", flow_job=j["id"], msg="⏳ na fila do Flow",
                                                         arquivo=personagem_arquivo(pastas(base)["personagens"], nome))}
    _salvar_personagens(base, d)
    return {"personagem": d[s], "aviso": SI._iniciar_lote()}


def sincronizar_personagens(base: str) -> Dict[str, Any]:
    d = personagens(base)
    esperando = [k for k, p in d.items() if (p.get("slot") or {}).get("estado") in ("fila", "gerando", "parado")]
    if not esperando:
        return d
    import shorts_ia as SI
    fila, rodando = SI._foto_da_fila()
    pasta = pastas(base)["personagens"]
    bruto = os.path.join(pasta, "_flow")
    for k in esperando:
        sl = d[k]["slot"]
        if SI._sync_slot(sl, fila, rodando, "imagem", bruto, k) and sl.get("estado") == "pronto":
            for ext in (".png", ".webp", ".jpg", ".jpeg"):
                try:
                    os.remove(os.path.join(pasta, k + ext))
                except OSError:
                    pass
            tirar_fundo(os.path.join(bruto, sl["arquivo"]), os.path.join(pasta, k + ".png"))
            sl.update(arquivo=k + ".png", msg="✅ pronto (sem fundo)")
    _salvar_personagens(base, d)
    return d


def simular(base: str, texto: str, op: Dict[str, Any]) -> Dict[str, Any]:
    op = PR.normalizar(op)
    d = PM.simular(texto, op["velocidade"], "shorts" if op["estilo"] == "shorts" else "", op["pov"], op.get("estrategia", False))
    for j in d["jogadores"]:
        j["avatar"] = avatar_de(base, j["nome"], j.get("avatar") or "")
    return d


def resumo(d: Dict[str, Any]) -> Dict[str, Any]:
    ganhou = next((e for e in reversed(d["eventos"]) if e["tipo"] == "vencedor"), None)
    txt = ""
    if ganhou:
        nomes = [d["jogadores"][i]["nome"] for i in ganhou["dados"]["quem"]]
        jogos = ganhou["depois"].get("jogos") or {}
        j0 = jogos.get(ganhou["dados"]["quem"][0]) or jogos.get(str(ganhou["dados"]["quem"][0])) or ""
        txt = f"{' e '.join(nomes)} leva(m) o pot de {PM._fmt(ganhou['dados']['pot'])}" + (f" — {j0}" if j0 else "")
    return {"duracao": d["duracao"], "jogadores": [{"nome": j["nome"], "avatar": j.get("avatar") or "", "pais": j.get("pais") or ""}
                                                   for j in d["jogadores"]],
            "resumo": txt, "variante": d.get("variante_nome") or "", "cameras": sum(e["tipo"] == "camera" for e in d["eventos"]),
            "emocoes": len(d.get("emocoes") or []), "zooms": len(d.get("zooms") or [])}


# ------------------------------------------------------------------ mãos salvas
def _cam_mao(base: str, mid: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{10}", str(mid or "")):
        raise PM.PokerErro("Mão não encontrada.")
    return os.path.join(pastas(base)["maos"], mid + ".json")


def carregar_mao(base: str, mid: str) -> Dict[str, Any]:
    try:
        with open(_cam_mao(base, mid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        raise PM.PokerErro("Mão não encontrada.") from exc


def salvar_mao(base: str, m: Dict[str, Any]) -> Dict[str, Any]:
    mid = m.get("id") or secrets.token_hex(5)
    velho = {}
    try:
        velho = carregar_mao(base, mid)
    except PM.PokerErro:
        pass
    x = {"id": mid, "titulo": " ".join(str(m.get("titulo") or "").split())[:120] or "Mão sem título",
         "texto": str(m.get("texto") or "")[:40000], "op": PR.normalizar(m.get("op") or {}),
         "criado": velho.get("criado") or time.time(), "atualizado": time.time(), "video": m.get("video") or velho.get("video") or "",
         "origem": m.get("origem") or velho.get("origem") or ""}
    c = _cam_mao(base, mid)
    with open(c + ".tmp", "w", encoding="utf-8") as f:
        json.dump(x, f, ensure_ascii=False, indent=1)
    os.replace(c + ".tmp", c)
    return x


def listar_maos(base: str) -> list:
    out = []
    for f in os.listdir(pastas(base)["maos"]):
        if f.endswith(".json"):
            try:
                out.append(carregar_mao(base, f[:-5]))
            except PM.PokerErro:
                pass
    return sorted(out, key=lambda m: -float(m.get("atualizado") or 0))


def registrar(app, base_dir: str, tts: Optional[Callable[..., Any]] = None, limpar_tts: Optional[Callable[[str, str], str]] = None) -> None:
    CB.update(tts=tts, limpar=limpar_tts)
    def _ok(**kw: Any):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: str, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _corpo() -> Dict[str, Any]:
        return request.get_json(silent=True) or {}

    def _tentar(fn: Callable[[], Any]):
        try:
            r = fn()
            return _ok(**(r if isinstance(r, dict) else {}))
        except PM.PokerErro as exc:
            return _erro(str(exc))

    def _rodar(chave: str, rotulo: str, fn: Callable[[Callable[[str], None], Callable[[], bool]], Any]):
        with _TRAVA_T:
            t = TAREFAS.get(chave)
            if t and not t.get("fim"):
                return jsonify({"ok": False, "ocupado": True, "erro": f"Já está rodando: {t['rotulo']} (⏹ parar, se travou)",
                                "tarefa": dict(t, rodando=True)}), 409
            _CANCELAR.discard(chave)
            TAREFAS[chave] = {"rotulo": rotulo, "inicio": time.time(), "fim": None, "erro": None, "msg": "", "prog": "", "res": None}

        def prog(m: str) -> None:
            TAREFAS[chave]["prog"] = str(m)[:300]

        def parar() -> bool:
            return chave in _CANCELAR

        def corpo():
            try:
                r = fn(prog, parar)
                TAREFAS[chave]["res"] = r if isinstance(r, (dict, str)) else None
            except Exception as exc:  # noqa: BLE001
                TAREFAS[chave]["erro"] = str(exc)[:600]
            finally:
                TAREFAS[chave]["fim"] = time.time()
        threading.Thread(target=corpo, daemon=True, name="poker:" + chave).start()
        return _ok(tarefa=chave)

    def _fontes_url() -> str:
        return "/poker/fontes"

    def _av_url(a: str) -> str:
        return f"/poker/avatar/{os.path.basename(a)}" if a else ""

    def _pers_url(nome: str) -> str:
        pasta = pastas(base_dir)["personagens"]
        arq = personagem_arquivo(pasta, nome)
        return f"/poker/personagem/{arq}?v={int(os.path.getmtime(os.path.join(pasta, arq)))}" if arq else ""

    def _pagina(d: Dict[str, Any], op: Dict[str, Any], modo: str) -> str:
        if op.get("modo") == "3d":
            return P3.pagina(d, op, _fontes_url(), _pers_url, modo)
        return PR.pagina(d, op, _fontes_url(), _av_url, modo)

    def _gravar(d: Dict[str, Any], op: Dict[str, Any], destino: str, prog, parar) -> None:
        if CB.get("gravar"):
            CB["gravar"](d, op, destino, prog, pastas(base_dir)["avatares"], parar)
        elif op.get("modo") == "3d":
            P3.gravar(d, op, destino, prog, pastas(base_dir)["personagens"], parar)
        else:
            PR.gravar(d, op, destino, prog, pastas(base_dir)["avatares"], parar)

    # ------------------------------------------------------------------ 🎞 montagem do vídeo final
    def _voz(slug: str, motor_perfil: str = "xtts") -> Optional[Dict[str, Any]]:
        if CB.get("voz"):
            return CB["voz"](slug)
        try:
            import anime2d as A
            if not slug:
                vs = A.vozes_disponiveis(motor_perfil)
                slug = vs[0]["slug"] if vs else ""
            return A.voz_por_slug(slug, motor_perfil) if slug else None
        except Exception:  # noqa: BLE001
            return None

    @app.route("/poker/vozes")
    def poker_vozes():
        try:
            import anime2d as A
            vs = [{"slug": v["slug"], "nome": v.get("nome") or v["slug"]} for v in A.vozes_disponiveis(request.args.get("motor") or "xtts")]
        except Exception:  # noqa: BLE001
            vs = []
        return _ok(vozes=vs, tts=bool(CB.get("tts")))

    def _musica(d: Dict[str, Any]) -> str:
        import poker_montagem as PMo
        if d.get("musica"):
            c = os.path.join(PMo.pasta_midia(base_dir, d["id"]), d["musica"])
            if os.path.isfile(c):
                return c
        sons = os.path.join(pastas(base_dir)["raiz"], "sons")
        for ext in (".mp3", ".wav", ".m4a", ".ogg"):
            if os.path.isfile(os.path.join(sons, "musica" + ext)):
                return os.path.join(sons, "musica" + ext)
        return ""

    @app.route("/poker/doc/<did>/montar", methods=["POST"])
    def poker_doc_montar(did: str):
        import poker_montagem as PMo
        c = _corpo()
        try:
            d = PD.carregar(base_dir, did)
        except PM.PokerErro:
            abort(404)
        if not CB.get("tts"):
            return _erro("O gerador de voz não está disponível aqui (🎙 Gerar voz).")
        voz = _voz(str(c.get("voz") or d.get("voz") or ""), str(c.get("motor") or "xtts"))
        if not voz:
            return _erro("Nenhuma voz cadastrada — cadastre uma em 🎙 Gerar voz → vozes.")
        op = PR.normalizar(c.get("op") or d.get("op") or {})
        ritmo = str(c.get("ritmo_pecas") or d.get("ritmo_pecas") or "normal")
        with PD.TRAVA:
            dd = PD.carregar(base_dir, did)
            dd["ritmo_pecas"] = ritmo
            dd["voz"] = str(c.get("voz") or dd.get("voz") or "")
            dd["op"] = op
            PD.salvar(base_dir, dd)
        nome = f"doc_{did}_final.mp4"
        destino = os.path.join(pastas(base_dir)["videos"], nome)

        def fn(prog, parar):
            mt = PMo.Montador(base_dir, did, dict(op, ritmo_pecas=ritmo), CB["tts"], voz, CB.get("limpar") or (lambda t, m: t), prog, parar,
                              pastas(base_dir)["avatares"], pastas(base_dir)["personagens"], _musica(d), CB.get("gravar_pagina"))
            r = mt.montar(destino)   # o .srt sai do lado do vídeo
            with PD.TRAVA:
                dd = PD.carregar(base_dir, did)
                dd["montagem"] = dict(r, quando=time.time())
                PD.salvar(base_dir, dd)
            return r
        return _rodar(f"mont:{did}", "🎞 montando o vídeo final (voz + peças + mãos)", fn)

    @app.route("/poker/doc/<did>/bloco/<bid>/midia", methods=["POST"])
    def poker_doc_midia(did: str, bid: str):
        import poker_montagem as PMo
        f = request.files.get("arquivo")
        if not f or not f.filename:
            return _erro("Escolha a imagem ou o vídeo.")
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in EXT_IMG + PMo.EXT_VIDEO:
            return _erro("Use imagem (JPG/PNG/WEBP) ou vídeo (MP4/MOV/WEBM).")
        nome = f"{bid}_{secrets.token_hex(3)}{ext}"
        f.save(os.path.join(PMo.pasta_midia(base_dir, did), nome))

        def fn():
            with PD.TRAVA:
                d = PD.carregar(base_dir, did)
                for b in d.get("blocos") or []:
                    if b["id"] == bid:
                        g = b.setdefault("grafico", {})
                        g["arquivo"] = nome
                        if ext in EXT_IMG and not g.get("tipo"):
                            g["tipo"] = "midia"
                PD.salvar(base_dir, d)
            return {"arquivo": nome, "doc": d}
        return _tentar(fn)

    @app.route("/poker/doc/<did>/midia/<arq>")
    def poker_doc_midia_arq(did: str, arq: str):
        import poker_montagem as PMo
        return send_from_directory(PMo.pasta_midia(base_dir, did), os.path.basename(arq))

    @app.route("/poker/doc/<did>/musica", methods=["POST"])
    def poker_doc_musica(did: str):
        import poker_montagem as PMo
        f = request.files.get("arquivo")
        if not f or not f.filename:
            return _erro("Escolha a música.")
        nome = "musica" + (os.path.splitext(f.filename)[1].lower() or ".mp3")
        f.save(os.path.join(PMo.pasta_midia(base_dir, did), nome))

        def fn():
            with PD.TRAVA:
                d = PD.carregar(base_dir, did)
                d["musica"] = nome
                PD.salvar(base_dir, d)
            return {"musica": nome}
        return _tentar(fn)

    @app.route("/poker/grafico/previa", methods=["POST"])
    def poker_grafico_previa():
        import poker_graficos as PG
        c = _corpo()
        g = PG.normalizar(c.get("grafico") or {})
        op = PR.normalizar(c.get("op") or {})
        foto = _av_url(avatar_de(base_dir, g["titulo"])) if g["tipo"] == "jogador" and g["titulo"] else ""
        midia = f"/poker/doc/{c.get('did')}/midia/{g['arquivo']}" if g.get("arquivo") and c.get("did") else ""
        return _ok(html=PG.pagina(g, op, float(c.get("duracao") or 6), _fontes_url(), foto, midia, str(c.get("frase") or ""), "previa"))

    # ------------------------------------------------------------------ 🎭 personagens 3D
    @app.route("/poker/personagens")
    def poker_personagens():
        nomes = [n for n in (request.args.get("nomes") or "").split("|") if n.strip()]
        try:
            d = sincronizar_personagens(base_dir)
        except Exception as exc:  # noqa: BLE001  (o Flow não está instalado/ligado: mostra o que tem)
            d = personagens(base_dir)
            d["_aviso"] = str(exc)[:200]
        out = []
        for n in nomes:
            p = d.get(slug(n)) or {}
            out.append({"nome": n, "url": _pers_url(n), "descricao": p.get("descricao") or "", "slot": p.get("slot") or {},
                        "foto": avatar_de(base_dir, n)})
        return _ok(personagens=out, aviso=d.get("_aviso") or "")

    @app.route("/poker/personagem/<arq>")
    def poker_personagem_arq(arq: str):
        return send_from_directory(pastas(base_dir)["personagens"], os.path.basename(arq))

    @app.route("/poker/personagem/gerar", methods=["POST"])
    def poker_personagem_gerar():
        c = _corpo()
        if not str(c.get("nome") or "").strip():
            return _erro("Qual jogador?")
        fn = CB.get("pedir_personagem") or pedir_personagem
        try:
            return _ok(**fn(base_dir, c["nome"], c.get("descricao") or "", c.get("com_foto", True) is not False))
        except (PM.PokerErro, ValueError) as exc:
            return _erro(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _erro(f"Não consegui pedir no Flow: {exc}")

    @app.route("/poker/personagem/enviar", methods=["POST"])
    def poker_personagem_enviar():
        nome = request.form.get("nome") or ""
        f = request.files.get("arquivo")
        if not nome.strip() or not f or not f.filename:
            return _erro("Escolha o jogador e a imagem.")
        pasta = pastas(base_dir)["personagens"]
        bruto = os.path.join(pasta, "_enviado_" + slug(nome) + os.path.splitext(f.filename)[1].lower())
        f.save(bruto)
        for ext in (".png", ".webp", ".jpg", ".jpeg"):
            try:
                os.remove(os.path.join(pasta, slug(nome) + ext))
            except OSError:
                pass
        destino = os.path.join(pasta, slug(nome) + ".png")
        if request.form.get("tirar_fundo") == "1":
            tirar_fundo(bruto, destino)
        else:
            from PIL import Image
            Image.open(bruto).convert("RGBA").save(destino)
        os.remove(bruto)
        d = personagens(base_dir)
        d[slug(nome)] = dict(d.get(slug(nome)) or {}, nome=nome, slot={"estado": "pronto", "arquivo": slug(nome) + ".png", "msg": "📤 enviado"})
        _salvar_personagens(base_dir, d)
        return _ok(url=_pers_url(nome))

    @app.route("/poker/personagem/apagar", methods=["POST"])
    def poker_personagem_apagar():
        nome = str(_corpo().get("nome") or "")
        arq = personagem_arquivo(pastas(base_dir)["personagens"], nome)
        if arq:
            os.remove(os.path.join(pastas(base_dir)["personagens"], arq))
        d = personagens(base_dir)
        d.pop(slug(nome), None)
        _salvar_personagens(base_dir, d)
        return _ok()

    # ------------------------------------------------------------------ páginas
    @app.route("/poker")
    def poker_page():
        P = pastas(base_dir)
        avs = sorted(f for f in os.listdir(P["avatares"]) if f.lower().endswith(EXT_IMG))
        vids = sorted((f for f in os.listdir(P["videos"]) if f.endswith(".mp4")),
                      key=lambda f: -os.path.getmtime(os.path.join(P["videos"], f)))[:30]
        return render_template("poker.html", temas=list(PR.TEMAS_CSS), esteticas=PR.ESTETICAS, formatos=list(PR.TAMANHOS),
                               mostrar=PM.MOSTRAR, variantes=PM.VARIANTES, exemplo=PM.EXEMPLO, maos=listar_maos(base_dir),
                               docs=PD.listar(base_dir), tipos_doc=PD.TIPOS, avatares=avs, videos=vids,
                               op=PR.opcoes_padrao(), op_rank=RK.opcoes_padrao(), emocoes=PM.EMOCOES, estilos3d=P3.ESTILOS_3D)

    @app.route("/poker/doc/<did>")
    def poker_doc_page(did: str):
        try:
            d = PD.carregar(base_dir, did)
        except PM.PokerErro:
            abort(404)
        return render_template("poker_doc.html", d=d, status=PD.STATUS_MAO, tipos=PD.TIPOS, temas=list(PR.TEMAS_CSS),
                               esteticas=PR.ESTETICAS, formatos=list(PR.TAMANHOS), mostrar=PM.MOSTRAR, op=PR.opcoes_padrao(), estilos3d=P3.ESTILOS_3D,
                               tipos_graf=__import__("poker_graficos").TIPOS)

    # ------------------------------------------------------------------ arquivos
    @app.route("/poker/fontes/<path:arq>")
    def poker_fontes(arq: str):
        return send_from_directory(os.path.join(PR.AQUI, "assets", "fonts", "dp"), arq)

    @app.route("/poker/avatar/<arq>")
    def poker_avatar(arq: str):
        return send_from_directory(pastas(base_dir)["avatares"], os.path.basename(arq))

    @app.route("/poker/video/<arq>")
    def poker_video(arq: str):
        c = os.path.join(pastas(base_dir)["videos"], os.path.basename(arq))
        if not os.path.isfile(c):
            abort(404)
        return send_file(c, as_attachment=request.args.get("baixar") == "1")

    @app.route("/poker/avatar", methods=["POST"])
    def poker_avatar_enviar():
        nome = request.form.get("nome") or ""
        f = request.files.get("arquivo")
        if not nome.strip() or not f or not f.filename:
            return _erro("Escolha o jogador (nome) e a foto.")
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in EXT_IMG:
            return _erro("A foto tem que ser JPG, PNG ou WEBP.")
        pa = pastas(base_dir)["avatares"]
        for e in EXT_IMG:
            try:
                os.remove(os.path.join(pa, slug(nome) + e))
            except OSError:
                pass
        destino = os.path.join(pa, slug(nome) + ext)
        f.save(destino)
        try:  # recorta quadrado e reduz (fica leve no vídeo)
            from PIL import Image, ImageOps
            im = ImageOps.exif_transpose(Image.open(destino)).convert("RGB")
            lado = min(im.size)
            im = im.crop(((im.width - lado) // 2, (im.height - lado) // 3, (im.width - lado) // 2 + lado, (im.height - lado) // 3 + lado))
            im.resize((320, 320)).save(os.path.splitext(destino)[0] + ".jpg", quality=90)
            if ext != ".jpg":
                os.remove(destino)
        except Exception:  # noqa: BLE001
            pass
        return _ok(arquivo=avatar_de(base_dir, nome))

    @app.route("/poker/avatar/apagar", methods=["POST"])
    def poker_avatar_apagar():
        arq = os.path.basename(str(_corpo().get("arquivo") or ""))
        try:
            os.remove(os.path.join(pastas(base_dir)["avatares"], arq))
        except OSError:
            pass
        return _ok()

    # ------------------------------------------------------------------ mesa
    @app.route("/poker/simular", methods=["POST"])
    def poker_simular():
        c = _corpo()
        return _tentar(lambda: resumo(simular(base_dir, c.get("texto") or "", c.get("op") or {})))

    @app.route("/poker/previa", methods=["POST"])
    def poker_previa():
        c = _corpo()

        def fn():
            op = PR.normalizar(c.get("op") or {})
            d = simular(base_dir, c.get("texto") or "", op)
            return dict(resumo(d), html=_pagina(d, op, "previa"))
        return _tentar(fn)

    @app.route("/poker/mao/salvar", methods=["POST"])
    def poker_mao_salvar():
        c = _corpo()

        def fn():
            simular(base_dir, c.get("texto") or "", c.get("op") or {})  # só salva mão que roda
            return {"mao": salvar_mao(base_dir, c)}
        return _tentar(fn)

    @app.route("/poker/mao/<mid>")
    def poker_mao(mid: str):
        return _tentar(lambda: {"mao": carregar_mao(base_dir, mid)})

    @app.route("/poker/mao/<mid>/apagar", methods=["POST"])
    def poker_mao_apagar(mid: str):
        def fn():
            os.remove(_cam_mao(base_dir, mid))
        return _tentar(fn)

    @app.route("/poker/ia/mao", methods=["POST"])
    def poker_ia_mao():
        c = _corpo()
        return _tentar(lambda: {"texto": PD.mao_de_descricao(c.get("descricao") or "", CB.get("chamar"))})

    def _nome_video(prefixo: str) -> str:
        return f"{prefixo}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"

    @app.route("/poker/exportar", methods=["POST"])
    def poker_exportar():
        c = _corpo()
        try:
            op = PR.normalizar(c.get("op") or {})
            d = simular(base_dir, c.get("texto") or "", op)
        except PM.PokerErro as exc:
            return _erro(str(exc))
        mid = str(c.get("id") or "")
        nome = _nome_video("mao_" + (mid or slug(d.get("titulo") or "poker")[:30]))
        destino = os.path.join(pastas(base_dir)["videos"], nome)

        def fn(prog, parar):
            _gravar(d, op, destino, prog, parar)
            if mid:
                try:
                    m = carregar_mao(base_dir, mid)
                    m["video"] = nome
                    salvar_mao(base_dir, m)
                except PM.PokerErro:
                    pass
            return {"video": nome}
        return _rodar("exp:" + (mid or "avulsa"), f"🎞 exportando a mão ({op['formato']}, {d['duracao']:.0f} s)", fn)

    # ------------------------------------------------------------------ 🏆 ranking
    @app.route("/poker/ranking/previa", methods=["POST"])
    def poker_ranking_previa():
        c = _corpo()

        def fn():
            d = RK.montar(c.get("op") or {})
            return {"html": RK.pagina(d, _fontes_url(), "previa"), "narracao": RK.narracao(d), "duracao": d["duracao"],
                    "cenas": len(d["cenas"])}
        return _tentar(fn)

    @app.route("/poker/ranking/exportar", methods=["POST"])
    def poker_ranking_exportar():
        c = _corpo()
        try:
            d = RK.montar(c.get("op") or {})
        except PM.PokerErro as exc:
            return _erro(str(exc))
        nome = _nome_video(f"ranking_{d['variante']}_{d['op']['formato'].replace(':', 'x')}")
        destino = os.path.join(pastas(base_dir)["videos"], nome)

        def fn(prog, parar):
            dd = (CB.get("gravar_ranking") or RK.gravar)(d["op"], destino, prog, parar)
            with open(destino[:-4] + "_narracao.txt", "w", encoding="utf-8") as f:
                f.write(RK.narracao(dd if isinstance(dd, dict) and dd.get("cenas") else d))
            return {"video": nome}
        return _rodar("ranking", f"🏆 exportando o ranking ({d['variante_nome']}, {d['duracao']:.0f} s)", fn)

    @app.route("/poker/narracao/<arq>")
    def poker_narracao(arq: str):
        c = os.path.join(pastas(base_dir)["videos"], os.path.basename(arq))
        if not (c.endswith("_narracao.txt") or c.endswith(".srt")) or not os.path.isfile(c):
            abort(404)
        return send_file(c, as_attachment=True)

    # ------------------------------------------------------------------ tarefas
    @app.route("/poker/tarefa/<path:chave>")
    def poker_tarefa(chave: str):
        t = TAREFAS.get(chave)
        return _ok(tarefa=dict(t, rodando=not t.get("fim")) if t else None)

    @app.route("/poker/tarefa/parar", methods=["POST"])
    def poker_tarefa_parar():
        chave = str(_corpo().get("chave") or "")
        t = TAREFAS.get(chave)
        if not t or t.get("fim"):
            return _ok(parada=False)
        _CANCELAR.add(chave)
        return _ok(parada=True)

    # ------------------------------------------------------------------ 🎬 roteiros
    @app.route("/poker/doc/novo", methods=["POST"])
    def poker_doc_novo():
        f = request.form
        try:
            d = PD.novo(base_dir, f.get("tema") or "", f.get("infos") or "", f.get("tipo") or "documentario", "pt",
                        float(f.get("minutos") or 8), f.get("moeda") or "R$")
        except (PM.PokerErro, ValueError) as exc:
            return _erro(str(exc))
        return redirect(f"/poker/doc/{d['id']}")

    def _doc(did: str) -> Dict[str, Any]:
        try:
            return PD.carregar(base_dir, did)
        except PM.PokerErro:
            abort(404)

    @app.route("/poker/doc/<did>/estado")
    def poker_doc_estado(did: str):
        d = _doc(did)
        tarefas = {k: dict(t, rodando=not t.get("fim")) for k, t in TAREFAS.items() if k.endswith(":" + did) or (":" + did + ":") in k}
        return _ok(doc=d, tarefas=tarefas)

    @app.route("/poker/doc/<did>/salvar", methods=["POST"])
    def poker_doc_salvar(did: str):
        c = _corpo()

        def fn():
            with PD.TRAVA:
                d = PD.carregar(base_dir, did)
                for k, lim in (("tema", 200), ("infos", 12000), ("notas_pesquisa", 30000), ("titulo", 200), ("moeda", 6)):
                    if k in c:
                        d[k] = str(c[k] or "")[:lim]
                if c.get("tipo") in PD.TIPOS:
                    d["tipo"] = c["tipo"]
                if "minutos" in c:
                    try:
                        d["minutos"] = max(1.0, min(40.0, float(c["minutos"])))
                    except (TypeError, ValueError):
                        pass
                if "op" in c:
                    d["op"] = PR.normalizar(c["op"])
                PD.salvar(base_dir, d)
            if "blocos" in c:
                d = PD.salvar_blocos(base_dir, did, c["blocos"])
            return {"doc": d}
        return _tentar(fn)

    @app.route("/poker/doc/<did>/pesquisar", methods=["POST"])
    def poker_doc_pesquisar(did: str):
        _doc(did)
        return _rodar("pesq:" + did, "🔎 pesquisando na web (IA do Google)",
                      lambda prog, parar: (prog("🔎 pesquisando… (pode levar alguns minutos)"), PD.pesquisar(base_dir, did, CB.get("pesquisar")))[1] and "ok")

    @app.route("/poker/doc/<did>/escrever", methods=["POST"])
    def poker_doc_escrever(did: str):
        _doc(did)
        n = int(_corpo().get("max_maos") or 0)
        return _rodar("escr:" + did, "✍ escrevendo o roteiro",
                      lambda prog, parar: (prog("✍ a IA está escrevendo o roteiro e montando as mãos…"),
                                           PD.escrever(base_dir, did, n, CB.get("chamar")))[1] and "ok")

    @app.route("/poker/doc/<did>/checar_web", methods=["POST"])
    def poker_doc_checar(did: str):
        _doc(did)
        return _rodar("chec:" + did, "✅ checando os fatos na web",
                      lambda prog, parar: (prog("✅ conferindo as afirmações…"), PD.checar_web(base_dir, did, CB.get("checar")))[1] and "ok")

    @app.route("/poker/doc/<did>/checagem")
    def poker_doc_checagem(did: str):
        return _tentar(lambda: {"prompt": PD.prompt_checagem(_doc(did))})

    @app.route("/poker/doc/<did>/checagem_ler", methods=["POST"])
    def poker_doc_checagem_ler(did: str):
        return _tentar(lambda: {"doc": PD.ler_checagem(base_dir, did, _corpo().get("resposta") or "")})

    @app.route("/poker/doc/<did>/aplicar", methods=["POST"])
    def poker_doc_aplicar(did: str):
        idx = _corpo().get("indices")
        return _tentar(lambda: {"doc": PD.aplicar_trocas(base_dir, did, [int(i) for i in idx] if isinstance(idx, list) else None)})

    @app.route("/poker/doc/<did>/texto")
    def poker_doc_texto(did: str):
        d = _doc(did)
        from flask import Response
        return Response(PD.texto_narracao(d), mimetype="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=roteiro_{slug(d.get('titulo') or d['tema'])}.txt"})

    @app.route("/poker/doc/<did>/apagar", methods=["POST"])
    def poker_doc_apagar(did: str):
        def fn():
            os.remove(PD._cam(base_dir, did))
        return _tentar(fn)

    def _bloco(d: Dict[str, Any], bid: str) -> Dict[str, Any]:
        b = next((b for b in d.get("blocos") or [] if b["id"] == bid and b["tipo"] == "mao"), None)
        if not b:
            raise PM.PokerErro("Essa mão não está mais no roteiro.")
        return b

    @app.route("/poker/doc/<did>/mao/<bid>/abrir", methods=["POST"])
    def poker_doc_mao_abrir(did: str, bid: str):
        """Leva a mão do roteiro pra 🃏 mesa (salva como mão, com a origem)."""
        def fn():
            d = PD.carregar(base_dir, did)
            b = _bloco(d, bid)
            m = salvar_mao(base_dir, {"titulo": b["mao"]["titulo"], "texto": b["mao"]["mao"], "op": d.get("op") or {},
                                      "origem": f"{did}:{bid}"})
            return {"mao": m}
        return _tentar(fn)

    @app.route("/poker/doc/<did>/mao/<bid>/exportar", methods=["POST"])
    def poker_doc_mao_exportar(did: str, bid: str):
        try:
            d = PD.carregar(base_dir, did)
            b = _bloco(d, bid)
            op = PR.normalizar(_corpo().get("op") or d.get("op") or {})
            dados = simular(base_dir, b["mao"]["mao"], op)
        except PM.PokerErro as exc:
            return _erro(str(exc))
        nome = _nome_video(f"doc_{did}_{bid}")
        destino = os.path.join(pastas(base_dir)["videos"], nome)

        def fn(prog, parar):
            _gravar(dados, op, destino, prog, parar)
            with PD.TRAVA:
                dd = PD.carregar(base_dir, did)
                for x in dd.get("blocos") or []:
                    if x["id"] == bid:
                        x["video"] = nome
                PD.salvar(base_dir, dd)
            return {"video": nome}
        return _rodar(f"exp:{did}:{bid}", f"🎞 exportando “{b['mao']['titulo'][:40]}”", fn)
