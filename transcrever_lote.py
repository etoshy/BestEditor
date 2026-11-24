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
         "transcricao": "📄 só a transcrição"}
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
        itens.append({"url": url, "titulo": str(v.get("titulo") or "")[:200], "canal": str(v.get("canal") or "")[:120],
                      "fonte": str(v.get("fonte") or "")[:60], "txt": str(v.get("txt") or "")[:2_000_000],
                      "txt_ts": str(v.get("txt_ts") or "")[:2_500_000], "estado": "na_fila", "erro": "", "arquivos": []})
    if not itens:
        raise ValueError("Nenhum link do YouTube na lista.")
    lote = {"id": uuid.uuid4().hex[:10], "criado": time.time(), "modo": modo, "qualidade": qualidade, "itens": itens,
            "estado": "na_fila", "zip": "", "log": ""}
    LOTES[lote["id"]] = lote
    salvar(base, lote)
    return lote


def _baixar(item: Dict[str, Any], modo: str, qualidade: str, pasta_tmp: str, log) -> Optional[str]:
    import youtube_clipper as yc
    if modo == "audio":
        return yc.baixar_audio(item["url"], pasta_tmp, on_log=log)["caminho"]
    r = yc.baixar_video(item["url"], pasta_tmp, qualidade=qualidade if qualidade in yc.QUALIDADES else yc.QUALIDADE_PADRAO,
                        on_log=log)
    if not item["titulo"]:
        item["titulo"] = r.get("titulo") or ""
    return r["caminho"]


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
        usados: set = set()
        for k, it in enumerate(lote["itens"], 1):
            if lote.get("_parar"):
                it["estado"] = "pulado"
                continue
            it["estado"] = "baixando"
            salvar(base, lote)
            nome = nome_seguro(it["titulo"] or it["url"].rsplit("=", 1)[-1])
            n = 2
            while nome in usados:
                nome = nome_seguro(it["titulo"]) + f" ({n})"
                n += 1
            usados.add(nome)
            log(f"[{k}/{len(lote['itens'])}] {nome}")
            cab = f"{it['titulo']}\n{(it['canal'] + ' — ') if it['canal'] else ''}{it['url']}\n" + (f"({it['fonte']})\n" if it['fonte'] else "") + "\n"
            if it["txt"]:
                with open(os.path.join(arqs, nome + ".txt"), "w", encoding="utf-8-sig") as f:
                    f.write(cab + it["txt"])
                it["arquivos"].append(nome + ".txt")
            if it["txt_ts"]:
                with open(os.path.join(arqs, nome + " (com timestamps).txt"), "w", encoding="utf-8-sig") as f:
                    f.write(cab + it["txt_ts"])
                it["arquivos"].append(nome + " (com timestamps).txt")
            if lote["modo"] != "transcricao":
                tmp = os.path.join(d, "_tmp")
                shutil.rmtree(tmp, ignore_errors=True)
                try:
                    cam = (baixar or _baixar)(it, lote["modo"], lote["qualidade"], tmp, log)
                    final = nome + os.path.splitext(cam)[1]
                    shutil.move(cam, os.path.join(arqs, final))
                    it["arquivos"].append(final)
                except Exception as exc:  # noqa: BLE001 — um vídeo ruim não para o lote
                    it["erro"] = str(exc)[:400]
                    log(f"   ✖ {it['erro'][:200]}")
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
            it["estado"] = "erro" if it["erro"] and len(it["arquivos"]) == (1 if it["txt"] else 0) + (1 if it["txt_ts"] else 0) else "pronto"
            salvar(base, lote)
        # o .zip (vídeo/áudio já são comprimidos: guarda sem recomprimir; texto comprime)
        resumo = [f"{sum(1 for i in lote['itens'] if i['estado'] == 'pronto')} de {len(lote['itens'])} prontos "
                  f"({MODOS[lote['modo']]})", ""]
        resumo += [f"{'✔' if i['estado'] == 'pronto' else '✖'} {i['titulo'] or i['url']} — {i['url']}"
                   + (f"\n   erro: {i['erro']}" if i["erro"] else "") for i in lote["itens"]]
        zip_nome = time.strftime("youtube_lote_%Y-%m-%d_%H%M") + ".zip"
        with zipfile.ZipFile(os.path.join(d, zip_nome), "w") as z:
            for i in lote["itens"]:
                for a in i["arquivos"]:
                    cam = os.path.join(arqs, a)
                    if os.path.isfile(cam):
                        z.write(cam, a, compress_type=zipfile.ZIP_DEFLATED if a.endswith(".txt") else zipfile.ZIP_STORED)
            z.writestr("_resumo.txt", "\n".join(resumo), compress_type=zipfile.ZIP_DEFLATED)
        lote["zip"] = zip_nome
        lote["estado"] = "pronto"
        log(f"📦 {zip_nome}")
        salvar(base, lote)
    return lote


def para_json(lote: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in lote.items() if not k.startswith("_") and k != "itens"}
    out["itens"] = [{k: i.get(k) for k in ("url", "titulo", "estado", "erro", "arquivos")} for i in lote["itens"]]
    out["prontos"] = sum(1 for i in lote["itens"] if i["estado"] == "pronto")
    out["total"] = len(lote["itens"])
    return out


def registrar(app, base_transcricoes: str) -> None:
    from flask import Response, jsonify, request, send_file
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
        lote = LOTES.get(lid)
        if not lote or not lote.get("zip"):
            return "Ainda não tem .zip.", 404
        cam = os.path.join(pasta_raiz(base_transcricoes), lid, lote["zip"])
        if not os.path.isfile(cam):
            return "Arquivo não encontrado.", 404
        return send_file(cam, as_attachment=True, download_name=lote["zip"])
