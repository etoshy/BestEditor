"""📦 v84_464 — LOTE do YouTube: várias transcrições (+ os vídeos ou só o áudio) num .zip.

Quem manda é o script "YouTube — Copiar / Baixar Transcrição" (no navegador do site): ele já pegou as transcrições na
página do YouTube e manda pra cá a lista {url, título, transcrição}. O site baixa o VÍDEO (ou só o ÁUDIO na melhor
qualidade) de cada um com o yt-dlp, grava as transcrições ao lado com o MESMO nome e junta tudo num .zip.

Pasta: <transcrições avulsas>/_lotes/<id>/ (arquivos/, lote.json, <nome>.zip)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from typing import Any, Dict, List, Optional

MODOS = {"video": "🎬 vídeo + transcrição", "audio": "🎧 só o áudio (melhor qualidade) + transcrição",
         "transcricao": "📄 só a transcrição",
         # ⬇ v84_465 (aba Baixar do YouTube): o formato do arquivo
         "mp4": "🎬 MP4 (vídeo)", "mp3": "🎵 MP3 (só o som, 320 kbps)"}
QUALIDADES = ("1080p", "720p", "480p", "360p", "melhor")
_FILA = threading.Lock()  # um lote baixando de cada vez (o YouTube não gosta de rajada)
LOTES: Dict[str, Dict[str, Any]] = {}


def nome_seguro(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", str(s or ""))
    return re.sub(r"\s+", " ", s).strip(" .")[:110] or "video"


def pasta_raiz(base: str) -> str:
    return os.path.join(base, "_lotes")


def salvar(base: str, lote: Dict[str, Any]) -> None:
    d = os.path.join(pasta_raiz(base), lote["id"])
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "lote.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in lote.items() if not k.startswith("_")}, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(d, "lote.json"))


def carregar_todos(base: str) -> None:
    raiz = pasta_raiz(base)
    try:
        nomes = os.listdir(raiz)
    except OSError:
        return
    for n in nomes:
        try:
            with open(os.path.join(raiz, n, "lote.json"), encoding="utf-8") as f:
                d = json.load(f)
            if d.get("estado") in ("na_fila", "baixando"):
                d["estado"] = "interrompido"
            LOTES.setdefault(d["id"], d)
        except (OSError, ValueError, KeyError):
            continue


def criar(base: str, videos: List[Dict[str, Any]], modo: str = "video", qualidade: str = "1080p") -> Dict[str, Any]:
    if modo not in MODOS:
        modo = "video"
    if qualidade not in QUALIDADES:
        qualidade = "1080p"
    itens = []
    for v in videos[:200]:
        url = str(v.get("url") or "").strip()
        if not re.match(r"https://(www\.|m\.)?(youtube\.com|youtu\.be)/", url):
            continue
        itens.append({"url": url, "titulo": str(v.get("titulo") or "")[:200], "nome": "", "canal": str(v.get("canal") or "")[:120],
                      "fonte": str(v.get("fonte") or "")[:60], "txt": str(v.get("txt") or "")[:2_000_000],
                      "txt_ts": str(v.get("txt_ts") or "")[:2_500_000], "estado": "na_fila", "erro": "", "arquivos": []})
    if not itens:
        raise ValueError("Nenhum link do YouTube na lista.")
    lote = {"id": uuid.uuid4().hex[:10], "criado": time.time(), "modo": modo, "qualidade": qualidade, "itens": itens,
            "estado": "na_fila", "zip": "", "log": ""}
    LOTES[lote["id"]] = lote
    salvar(base, lote)
    return lote


def _para_mp3(cam: str, log) -> str:
    """O melhor áudio do YouTube (opus/m4a) → MP3 320 kbps (o formato que abre em qualquer lugar)."""
    import subprocess
    saida = os.path.splitext(cam)[0] + ".mp3"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", cam, "-vn", "-codec:a", "libmp3lame", "-b:a", "320k", saida],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0 or not os.path.isfile(saida):
        raise RuntimeError("o ffmpeg não conseguiu fazer o MP3: " + (r.stderr or "")[-300:])
    log("   🎵 MP3 320 kbps pronto")
    return saida


def _baixar(item: Dict[str, Any], modo: str, qualidade: str, pasta_tmp: str, log) -> Optional[str]:
    import youtube_clipper as yc
    if modo in ("audio", "mp3"):
        r = yc.baixar_audio(item["url"], pasta_tmp, on_log=log)
        if not item["titulo"]:
            item["titulo"] = r.get("titulo") or ""
        return _para_mp3(r["caminho"], log) if modo == "mp3" else r["caminho"]
    r = yc.baixar_video(item["url"], pasta_tmp, qualidade=qualidade if qualidade in yc.QUALIDADES else yc.QUALIDADE_PADRAO,
                        on_log=log)
    if not item["titulo"]:
        item["titulo"] = r.get("titulo") or ""
    return r["caminho"]


def _nome(lote: Dict[str, Any], it: Dict[str, Any]) -> str:
    """O nome dos arquivos deste vídeo (o título; fica fixo depois da 1ª vez — vídeo e transcrição com o MESMO nome)."""
    if it.get("nome"):
        return it["nome"]
    base_n = nome_seguro(it.get("titulo") or it["url"].rsplit("=", 1)[-1])
    usados = {i.get("nome") for i in lote["itens"] if i is not it}
    nome, n = base_n, 2
    while nome in usados:
        nome = f"{base_n} ({n})"
        n += 1
    it["nome"] = nome
    return nome


def _gravar_transcricao(base: str, lote: Dict[str, Any], it: Dict[str, Any]) -> None:
    arqs = os.path.join(pasta_raiz(base), lote["id"], "arquivos")
    os.makedirs(arqs, exist_ok=True)
    nome = _nome(lote, it)
    cab = (f"{it['titulo']}\n{(it['canal'] + ' — ') if it.get('canal') else ''}{it['url']}\n"
           + (f"({it['fonte']})\n" if it.get('fonte') else "") + "\n")
    for chave, sufixo in (("txt", ""), ("txt_ts", " (com timestamps)")):
        if it.get(chave):
            a = f"{nome}{sufixo}.txt"
            with open(os.path.join(arqs, a), "w", encoding="utf-8-sig") as f:
                f.write(cab + it[chave])
            if a not in it["arquivos"]:
                it["arquivos"].append(a)


def receber_transcricao(base: str, lote_id: str, idx: int, dados: Dict[str, Any]) -> Dict[str, Any]:
    """📄 A transcrição que o script mandou da guia do vídeo (você clicou em "Salvar transcrição no .zip")."""
    lote = LOTES.get(lote_id)
    if not lote or not (0 <= idx < len(lote["itens"])):
        raise ValueError("Lote ou vídeo não encontrado.")
    it = lote["itens"][idx]
    if not it.get("titulo") and dados.get("titulo"):
        it["titulo"] = str(dados["titulo"])[:200]
    for k, lim in (("canal", 120), ("fonte", 60), ("txt", 2_000_000), ("txt_ts", 2_500_000)):
        if dados.get(k):
            it[k] = str(dados[k])[:lim]
    _gravar_transcricao(base, lote, it)
    it["transcricao_ok"] = True
    it["guia"] = "feita"
    salvar(base, lote)
    return it


def montar_zip(base: str, lote_id: str) -> str:
    """O .zip com o que já existe (refaz se chegou transcrição/arquivo depois). Devolve o caminho."""
    lote = LOTES[lote_id]
    d = os.path.join(pasta_raiz(base), lote_id)
    arqs = os.path.join(d, "arquivos")
    os.makedirs(arqs, exist_ok=True)
    zip_nome = lote.get("zip") or time.strftime("youtube_lote_%Y-%m-%d_%H%M") + ".zip"
    cam = os.path.join(d, zip_nome)
    presentes = [os.path.join(arqs, a) for i in lote["itens"] for a in i["arquivos"] if os.path.isfile(os.path.join(arqs, a))]
    if os.path.isfile(cam) and lote.get("_zip_n") == len(presentes) and \
            all(os.path.getmtime(x) <= os.path.getmtime(cam) for x in presentes):
        return cam
    resumo = [f"{sum(1 for i in lote['itens'] if i['estado'] == 'pronto')} de {len(lote['itens'])} prontos ({MODOS[lote['modo']]})", ""]
    resumo += [f"{'✔' if i['estado'] == 'pronto' else '✖'} {i['titulo'] or i['url']} — {i['url']}"
               + ("  📄 com transcrição" if any(a.endswith(".txt") for a in i["arquivos"]) else "")
               + (f"\n   erro: {i['erro']}" if i["erro"] else "") for i in lote["itens"]]
    tmp = cam + ".tmp"
    with zipfile.ZipFile(tmp, "w") as z:
        for i in lote["itens"]:
            for a in i["arquivos"]:
                c = os.path.join(arqs, a)
                if os.path.isfile(c):
                    z.write(c, a, compress_type=zipfile.ZIP_DEFLATED if a.endswith(".txt") else zipfile.ZIP_STORED)
        z.writestr("_resumo.txt", "\n".join(resumo), compress_type=zipfile.ZIP_DEFLATED)
    os.replace(tmp, cam)
    lote["zip"], lote["_zip_n"] = zip_nome, len(presentes)
    return cam


def rodar(base: str, lote_id: str, baixar=None) -> Dict[str, Any]:
    """Baixa cada item, grava as transcrições com o mesmo nome e faz o .zip."""
    lote = LOTES[lote_id]
    d = os.path.join(pasta_raiz(base), lote_id)
    arqs = os.path.join(d, "arquivos")
    os.makedirs(arqs, exist_ok=True)

    def log(m: str) -> None:
        lote["log"] = (lote.get("log", "") + m + "\n")[-20000:]

    with _FILA:
        lote["estado"] = "baixando"
        for k, it in enumerate(lote["itens"], 1):
            if lote.get("_parar"):
                it["estado"] = "pulado"
                continue
            it["estado"] = "baixando"
            salvar(base, lote)
            log(f"[{k}/{len(lote['itens'])}] {it['titulo'] or it['url']}")
            if it.get("txt") or it.get("txt_ts"):
                _gravar_transcricao(base, lote, it)
            if lote["modo"] != "transcricao":
                tmp = os.path.join(d, "_tmp")
                shutil.rmtree(tmp, ignore_errors=True)
                try:
                    cam = (baixar or _baixar)(it, lote["modo"], lote["qualidade"], tmp, log)
                    final = _nome(lote, it) + os.path.splitext(cam)[1]
                    shutil.move(cam, os.path.join(arqs, final))
                    it["arquivos"].append(final)
                except Exception as exc:  # noqa: BLE001 — um vídeo ruim não para o lote
                    it["erro"] = str(exc)[:400]
                    log(f"   ✖ {it['erro'][:200]}")
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
            it["estado"] = "erro" if it["erro"] and not any(not a.endswith(".txt") for a in it["arquivos"]) else "pronto"
            salvar(base, lote)
        zip_nome = os.path.basename(montar_zip(base, lote_id))
        lote["zip"] = zip_nome
        lote["estado"] = "pronto"
        log(f"📦 {zip_nome}")
        salvar(base, lote)
    return lote


def para_json(lote: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in lote.items() if not k.startswith("_") and k != "itens"}
    out["itens"] = [{k: i.get(k) for k in ("url", "titulo", "estado", "erro", "arquivos", "transcricao_ok", "guia", "nome")}
                    for i in lote["itens"]]
    out["prontos"] = sum(1 for i in lote["itens"] if i["estado"] == "pronto")
    out["total"] = len(lote["itens"])
    return out


def registrar(app, base_transcricoes: str, base_dir: str = "") -> None:
    from flask import Response, jsonify, render_template, request, send_file
    carregar_todos(base_transcricoes)

    def _cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"  # o script manda de dentro do youtube.com
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
        return resp

    @app.route("/transcrever/lote", methods=["POST", "OPTIONS"])
    def transcrever_lote_novo():
        if request.method == "OPTIONS":
            return _cors(Response(""))
        try:
            c = json.loads(request.get_data(as_text=True) or "{}")
            lote = criar(base_transcricoes, c.get("videos") or [], str(c.get("modo") or "video"), str(c.get("qualidade") or "1080p"))
        except (ValueError, TypeError) as exc:
            return _cors(jsonify({"erro": str(exc)})), 400
        threading.Thread(target=lambda: _seguro(lote["id"]), daemon=True).start()
        return _cors(jsonify({"ok": True, "id": lote["id"], "pagina": request.host_url.rstrip("/") + "/transcrever#lote-" + lote["id"]}))

    def _seguro(lid: str) -> None:
        try:
            rodar(base_transcricoes, lid)
        except Exception as exc:  # noqa: BLE001
            LOTES[lid]["estado"] = "erro"
            LOTES[lid]["log"] = LOTES[lid].get("log", "") + f"\n❌ {exc}"
            salvar(base_transcricoes, LOTES[lid])

    @app.route("/transcrever/lote/<lid>")
    def transcrever_lote_estado(lid: str):
        lote = LOTES.get(lid)
        if not lote:
            return _cors(jsonify({"erro": "Lote não encontrado."})), 404
        return _cors(jsonify(para_json(lote)))

    @app.route("/transcrever/lotes")
    def transcrever_lotes():
        return jsonify({"lotes": [para_json(x) for x in sorted(LOTES.values(), key=lambda x: -x["criado"])][:30]})

    @app.route("/transcrever/lote/<lid>/parar", methods=["POST"])
    def transcrever_lote_parar(lid: str):
        if lid in LOTES:
            LOTES[lid]["_parar"] = True
        return jsonify({"ok": True})

    @app.route("/transcrever/lote/<lid>/zip")
    def transcrever_lote_zip(lid: str):
        """O .zip com o que já existe — refeito se chegou transcrição depois (dá pra baixar no meio, também)."""
        lote = LOTES.get(lid)
        if not lote:
            return "Lote não encontrado.", 404
        cam = montar_zip(base_transcricoes, lid)
        salvar(base_transcricoes, lote)
        return send_file(cam, as_attachment=True, download_name=os.path.basename(cam))

    # ------------------------------------------------------------------ ⬇ v84_465: aba "Baixar do YouTube"
    @app.route("/baixar-youtube")
    def baixar_youtube_page():
        return render_template("baixar_youtube.html")

    @app.route("/baixar-youtube/novo", methods=["POST"])
    def baixar_youtube_novo():
        c = request.get_json(silent=True) or {}
        urls = []
        for x in re.split(r"[\s,;]+", str(c.get("links") or "")):
            m = re.search(r"(?:v=|youtu\.be/|shorts/|live/)([\w-]{11})", x)
            if m and m.group(1) not in urls:
                urls.append(m.group(1))
        if not urls:
            return jsonify({"erro": "Cole pelo menos um link do YouTube."}), 400
        formato = "mp3" if c.get("formato") == "mp3" else "mp4"
        try:
            lote = criar(base_transcricoes, [{"url": f"https://www.youtube.com/watch?v={i}"} for i in urls], formato,
                         str(c.get("qualidade") or "1080p"))
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400
        lote["com_transcricao"] = bool(c.get("transcricao"))
        salvar(base_transcricoes, lote)
        threading.Thread(target=lambda: _seguro(lote["id"]), daemon=True).start()
        return jsonify({"ok": True, "lote": para_json(lote)})

    @app.route("/baixar-youtube/<lid>/guias", methods=["POST"])
    def baixar_youtube_guias(lid: str):
        """🧲 Abre as próximas N guias (no navegador do site, onde está o script) dos vídeos ainda sem transcrição.
        Em cada uma você clica em "📄 Salvar transcrição no .zip"; guia em que você não clicar = vídeo sem transcrição."""
        import urllib.parse as _u
        import navegador_imagens as ni
        from site_config import load_site_config
        lote = LOTES.get(lid)
        if not lote:
            return jsonify({"erro": "Lote não encontrado."}), 404
        c = request.get_json(silent=True) or {}
        n = max(1, min(10, int(c.get("quantas") or 5)))
        site = request.host_url.rstrip("/")
        fila = [(k, i) for k, i in enumerate(lote["itens"]) if not i.get("transcricao_ok") and i.get("guia") != "aberta"]
        if c.get("de_novo"):
            fila = [(k, i) for k, i in enumerate(lote["itens"]) if not i.get("transcricao_ok")]
        fila = fila[:n]
        if not fila:
            return jsonify({"erro": "Todos já têm transcrição (ou já estão abertos)."}), 400
        urls = [i["url"] + "#bestyt=" + _u.quote(f"{site}|{lid}|{k}", safe="") for k, i in fila]
        r = ni.abrir(base_dir or base_transcricoes, urls, load_site_config())
        if not r.get("ok"):
            return jsonify({"erro": r.get("erro") or "não abriu o navegador do site"}), 400
        for _k, i in fila:
            i["guia"] = "aberta"
        salvar(base_transcricoes, lote)
        return jsonify({"ok": True, "abertas": len(fila), "lote": para_json(lote)})

    @app.route("/baixar-youtube/<lid>/transcricao", methods=["POST", "OPTIONS"])
    def baixar_youtube_transcricao(lid: str):
        if request.method == "OPTIONS":
            return _cors(Response(""))
        try:
            c = json.loads(request.get_data(as_text=True) or "{}")
            it = receber_transcricao(base_transcricoes, lid, int(c.get("idx")), c)
        except (ValueError, TypeError) as exc:
            return _cors(jsonify({"erro": str(exc)})), 400
        return _cors(jsonify({"ok": True, "nome": it.get("nome")}))
