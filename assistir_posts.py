"""👀 v84_351: Assistir posts — cole links (Instagram, TikTok, Shorts…), um por linha, e assista aqui mesmo, com uma área de
notas pra cada vídeo (e pra cada vídeo de um carrossel). O botão ⏱ põe o tempo do player nas notas.

É TEMPORÁRIO de propósito: cada aba aberta é uma sessão; os vídeos baixados ficam numa pasta da sessão e somem quando você
fecha a aba (a página avisa o servidor ao sair) — e, se o aviso não chegar (PC desligou, navegador fechou à força), a
faxina apaga as sessões com mais de 6 h. As notas ficam só na página (não vão pro disco)."""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

VALIDADE_S = 6 * 3600
MAX_POR_SESSAO = 40
_ID = re.compile(r"[a-f0-9]{12}")
_TRAVA = threading.RLock()
_SESSOES: Dict[str, Dict[str, Any]] = {}
_FILA = threading.Semaphore(2)  # no máximo 2 downloads ao mesmo tempo (a rede e o PC agradecem)


def raiz(base: str) -> str:
    return os.path.join(base, "assistir_tmp")


def _pasta(base: str, sid: str) -> str:
    if not _ID.fullmatch(str(sid or "")):
        raise ValueError("sessão inválida")
    return os.path.join(raiz(base), sid)


def faxina(base: str, agora: Optional[float] = None) -> int:
    """Apaga as sessões esquecidas (mais de 6 h sem uso)."""
    agora = agora or time.time()
    n = 0
    try:
        nomes = os.listdir(raiz(base))
    except OSError:
        return 0
    for nome in nomes:
        cam = os.path.join(raiz(base), nome)
        try:
            velho = agora - os.path.getmtime(cam) > VALIDADE_S
        except OSError:
            continue
        if velho and nome not in _SESSOES:
            shutil.rmtree(cam, ignore_errors=True)
            n += 1
    return n


def nova_sessao(base: str) -> str:
    faxina(base)
    sid = uuid.uuid4().hex[:12]
    os.makedirs(_pasta(base, sid), exist_ok=True)
    with _TRAVA:
        _SESSOES[sid] = {"itens": [], "criada": time.time()}
    return sid


def apagar_sessao(base: str, sid: str) -> None:
    with _TRAVA:
        _SESSOES.pop(sid, None)
    try:
        shutil.rmtree(_pasta(base, sid), ignore_errors=True)
    except ValueError:
        pass


def _baixar_padrao(url: str, pasta: str) -> List[str]:
    import sys
    raiz_ = os.path.dirname(os.path.abspath(__file__))
    if os.path.join(raiz_, "toolkit") not in sys.path:
        sys.path.insert(0, os.path.join(raiz_, "toolkit"))
    from redes_sociais._ytdlp_base import baixar_com_ytdlp
    baixar_com_ytdlp(url, Path(pasta), varios=True, extra_opcoes={"format": "best[ext=mp4]/bestvideo+bestaudio/best"})
    return sorted((str(p) for p in Path(pasta).glob("item_*.mp4")), key=lambda c: int(re.sub(r"\D", "", os.path.basename(c)) or 0))


def _info_padrao(url: str) -> Dict[str, Any]:
    import curtos_link as CL
    i = CL.baixar_info(url, 0, timeout=45)
    return {k: i.get(k) for k in ("titulo", "descricao", "autor", "autor_handle", "musica", "local") if i.get(k)}


def adicionar(base: str, sid: str, urls: List[str], baixar: Optional[Callable[[str, str], List[str]]] = None,
              info: Optional[Callable[[str], Dict[str, Any]]] = None, esperar: bool = False) -> List[Dict[str, Any]]:
    """Cada link vira um item da sessão e começa a baixar (em segundo plano, 2 por vez)."""
    pasta = _pasta(base, sid)
    with _TRAVA:
        s = _SESSOES.get(sid)
        if s is None:
            if not os.path.isdir(pasta):
                raise ValueError("sessão expirada — recarregue a página")
            s = _SESSOES[sid] = {"itens": [], "criada": time.time()}
        ja = {i["url"] for i in s["itens"]}
        novos = []
        for u in urls:
            u = str(u or "").strip().strip("<>\"'(),;")
            if not re.match(r"https?://", u) or u in ja or len(s["itens"]) >= MAX_POR_SESSAO:
                continue
            ja.add(u)
            it = {"k": len(s["itens"]) + 1, "url": u, "estado": "na fila", "videos": [], "erro": "", "info": {}}
            s["itens"].append(it)
            novos.append(it)
    ths = []
    for it in novos:
        t = threading.Thread(target=_rodar, args=(base, sid, it, baixar or _baixar_padrao, info or _info_padrao), daemon=True)
        t.start()
        ths.append(t)
    if esperar:
        for t in ths:
            t.join(120)
    return novos


def _rodar(base: str, sid: str, it: Dict[str, Any], baixar: Callable, info: Callable) -> None:
    pasta = os.path.join(_pasta(base, sid), str(it["k"]))
    try:
        with _FILA:
            if sid not in _SESSOES:
                return  # a aba fechou enquanto esperava
            it["estado"] = "baixando"
            try:
                it["info"] = info(it["url"]) or {}
            except Exception:  # noqa: BLE001  (sem a legenda/música, o vídeo ainda vale)
                it["info"] = {}
            os.makedirs(pasta, exist_ok=True)
            arqs = baixar(it["url"], pasta)
        if sid not in _SESSOES:
            shutil.rmtree(pasta, ignore_errors=True)
            return
        it["videos"] = [os.path.basename(a) for a in arqs if os.path.isfile(a)]
        it["estado"] = "pronto" if it["videos"] else "erro"
        if not it["videos"]:
            it["erro"] = "não veio nenhum vídeo desse post"
    except Exception as exc:  # noqa: BLE001
        it["estado"], it["erro"] = "erro", re.sub(r"\x1b?\[[0-9;]{1,6}m", "", str(exc)).strip()[:400]


def estado(sid: str) -> List[Dict[str, Any]]:
    with _TRAVA:
        s = _SESSOES.get(sid) or {"itens": []}
        return [dict(i) for i in s["itens"]]


def arquivo(base: str, sid: str, k: int, nome: str) -> Optional[str]:
    if not re.fullmatch(r"item_\d{1,3}\.mp4", str(nome or "")):
        return None
    cam = os.path.join(_pasta(base, sid), str(int(k)), nome)
    return cam if os.path.isfile(cam) else None


def registrar(app: Any, base_dir: str) -> None:
    from flask import abort, jsonify, render_template, request, send_file

    @app.route("/assistir", methods=["GET"])
    def assistir_pagina():
        return render_template("assistir_posts.html", sid=nova_sessao(base_dir))

    @app.route("/assistir/<sid>/adicionar", methods=["POST"])
    def assistir_adicionar(sid: str):
        b = request.get_json(silent=True) or {}
        urls = [u for u in re.split(r"\s+", str(b.get("links") or "")) if u.startswith("http")]
        try:
            novos = adicionar(base_dir, sid, urls)
        except ValueError as exc:
            return jsonify({"ok": False, "erro": str(exc)}), 400
        return jsonify({"ok": True, "novos": len(novos), "itens": estado(sid)})

    @app.route("/assistir/<sid>/estado", methods=["GET"])
    def assistir_estado(sid: str):
        if not _ID.fullmatch(sid):
            abort(404)
        return jsonify({"ok": True, "itens": estado(sid), "viva": sid in _SESSOES})

    @app.route("/assistir/<sid>/<int:k>/<nome>", methods=["GET"])
    def assistir_video(sid: str, k: int, nome: str):
        try:
            cam = arquivo(base_dir, sid, k, nome)
        except ValueError:
            cam = None
        if not cam:
            abort(404)
        return send_file(cam, mimetype="video/mp4", conditional=True, max_age=0)

    @app.route("/assistir/<sid>/apagar", methods=["POST"])
    def assistir_apagar(sid: str):
        """Chamado quando a aba fecha (sendBeacon) — apaga os vídeos dessa sessão."""
        if _ID.fullmatch(sid):
            apagar_sessao(base_dir, sid)
        return jsonify({"ok": True})
