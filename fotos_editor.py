"""
📸 v84_387 — "Coisas do roteiro" no Estúdio (como as 📸 Fotos do roteiro dos Modelos de vídeo, só que dentro da edição).

  1. 🤖 A IA lê a narração (com os tempos) e lista o que vale mostrar com imagem REAL: pessoas, lugares, obras,
     eventos históricos, documentos, objetos específicos — cada um com o termo de busca e o momento em que é falado.
  2. 🧲 O site abre o Brave do site (o mesmo navegador das imagens, com o userscript) — uma guia do Google Imagens
     por item. Você marca as imagens certas e clica em "Capturar e enviar ao site": elas entram na 🖼️ Biblioteca
     do vídeo, já ligadas ao item.
  3. ➕ Pra cada imagem: 🔁 SUBSTITUIR a cena daquele momento ou ➕ CAMADA por cima (no canto ou no centro).
     Tudo dá pra desfazer.
"""
from __future__ import annotations

import base64
import os
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

TIPOS = ("pessoa", "lugar", "obra", "evento", "documento", "objeto", "outro")
MAX_ITENS = 30

SCHEMA = {
    "type": "object",
    "properties": {"itens": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "nome": {"type": "string"}, "tipo": {"type": "string", "enum": list(TIPOS)},
            "busca": {"type": "string"}, "start": {"type": "number"}, "end": {"type": "number"},
            "frase": {"type": "string"}, "por_que": {"type": "string"}},
        "required": ["nome", "tipo", "busca", "start", "end", "frase", "por_que"], "additionalProperties": False}}},
    "required": ["itens"], "additionalProperties": False}

SISTEMA = """Você é pesquisador de imagens de um canal de vídeos (documentário, história, filosofia, notícias).
Recebe a narração com os tempos de cada trecho e lista o que vale mostrar com uma IMAGEM REAL encontrada no Google
Imagens — não banco de imagens genérico.

O QUE ENTRA
- Pessoas citadas pelo nome (históricas, famosas, autores) → retrato/foto/pintura dela.
- Lugares específicos (cidades antigas, monumentos, prédios, regiões) → foto ou ilustração do lugar.
- Obras (livros, pinturas, esculturas, filmes) → a capa/a obra.
- Eventos históricos (batalhas, revoluções, julgamentos) → pintura/gravura/foto do evento.
- Documentos, mapas, objetos específicos e únicos (a cicuta de Sócrates, a Magna Carta…).
O QUE NÃO ENTRA: ideias abstratas, emoções, coisas genéricas ("uma pessoa sentada", "um celular") — isso o banco de
vídeos já resolve. Se nada no texto pede imagem real, devolva a lista vazia.

PARA CADA ITEM
- nome: como aparece no texto. tipo: pessoa|lugar|obra|evento|documento|objeto|outro.
- busca: o melhor termo pro Google Imagens achar EXATAMENTE isso, no idioma em que há mais imagens (geralmente o nome
  original ou em inglês) + o tipo de imagem: "Immanuel Kant portrait", "Ágora de Atenas reconstrução", "The Death of
  Socrates David painting", "Critique of Pure Reason first edition".
- start/end: os segundos (dos trechos dados) em que o item é falado — onde a imagem deve aparecer. Se ele volta
  várias vezes, use a PRIMEIRA vez em que é mais importante.
- frase: o trecho exato da narração. por_que: em poucas palavras, por que a imagem ajuda.
No máximo {max} itens, os mais importantes, em ordem de tempo. Não repita o mesmo item."""


def _blocos(job: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"start": float(b["start"]), "end": float(b["end"]), "text": str(b.get("text") or "").strip()}
            for b in job.get("segments") or [] if str(b.get("text") or "").strip()]


def texto_com_tempos(job: Dict[str, Any], limite_chars: int = 60000) -> str:
    linhas = [f"[{b['start']:.1f}–{b['end']:.1f}] {b['text']}" for b in _blocos(job)]
    t = "\n".join(linhas)
    return t[:limite_chars]


def ler_itens(resposta: Any, duracao: float) -> List[Dict[str, Any]]:
    itens = (resposta or {}).get("itens") if isinstance(resposta, dict) else None
    out, vistos = [], set()
    for x in itens or []:
        nome = str(x.get("nome") or "").strip()[:120]
        busca = str(x.get("busca") or "").strip()[:200]
        if not nome or not busca or nome.lower() in vistos:
            continue
        vistos.add(nome.lower())
        try:
            a, b = float(x.get("start") or 0), float(x.get("end") or 0)
        except (TypeError, ValueError):
            continue
        a = max(0.0, min(a, duracao or a))
        b = max(a + 3.0, min(b, (duracao or b + 99))) if b > a else a + 4.0
        out.append({"id": uuid.uuid4().hex[:8], "nome": nome, "tipo": x.get("tipo") if x.get("tipo") in TIPOS else "outro",
                    "busca": busca, "start": round(a, 2), "end": round(min(b, a + 12.0), 2),
                    "frase": str(x.get("frase") or "").strip()[:300], "por_que": str(x.get("por_que") or "").strip()[:200]})
    out.sort(key=lambda i: i["start"])
    return out[:MAX_ITENS]


def analisar(job: Dict[str, Any], chamar: Optional[Callable[..., Any]] = None, job_id: str = "") -> List[Dict[str, Any]]:
    if chamar is None:
        import ia_servico
        chamar = ia_servico.chamar
    texto = texto_com_tempos(job)
    if not texto.strip():
        raise ValueError("Esse vídeo não tem a narração com os tempos (transcrição).")
    r = chamar("buscas", SISTEMA.replace("{max}", str(MAX_ITENS)), "NARRAÇÃO (com os tempos em segundos):\n\n" + texto,
               schema=SCHEMA, max_tokens=8000, effort="medium", timeout=300, job=job_id or None)
    if r is None:
        import ia_servico
        raise RuntimeError("A IA não respondeu: " + (ia_servico.motivo_desligado("buscas") or ia_servico.ultimo_erro("buscas")
                                                      or "veja as últimas chamadas em 🤖 IA"))
    return ler_itens(r, float(job.get("total_duration") or 0))


# ------------------------------------------------------------------ imagens recebidas
def baixar_para(pasta: str, url: str = "", dados_b64: str = "") -> str:
    """Guarda a imagem que a guia mandou (link ou os bytes que o próprio navegador baixou) → caminho."""
    import io
    from PIL import Image
    os.makedirs(pasta, exist_ok=True)
    nome = f"foto_{uuid.uuid4().hex[:8]}"
    if dados_b64:
        dados = base64.b64decode(str(dados_b64).split(",")[-1])
        if not dados or len(dados) > 40 * 1024 * 1024:
            raise ValueError("imagem vazia ou grande demais")
        try:
            im = Image.open(io.BytesIO(dados))
            fmt = (im.format or "").lower()
        except Exception:  # noqa: BLE001
            raise ValueError("o que veio não é uma imagem")
        ext = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif", "bmp": ".bmp"}.get(fmt)
        caminho = os.path.join(pasta, nome + (ext or ".jpg"))
        if ext:
            with open(caminho, "wb") as fh:
                fh.write(dados)
        else:
            im.convert("RGB").save(caminho, quality=92)
        return caminho
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("link inválido")
    try:
        import vendas as vd
        cam, tipo = vd.baixar_arquivo(url, pasta, nome)
        if tipo != "foto":
            raise ValueError("o link não é uma imagem")
        return cam
    except Exception:  # noqa: BLE001 — o site barrou: o baixador dos buscadores (cabeçalhos de navegador)
        import buscador_imagens_unificado as bu
        im = bu.ImagemBuscador(title="", description="", source_page="", original_url=url, thumbnail_url="",
                               width=None, height=None, query="", engine="")
        return bu.baixar_imagem(im, pasta, stem=nome, timeout_s=40)


# ------------------------------------------------------------------ aplicar no vídeo
def trechos_no_intervalo(pend: List[Dict[str, Any]], a: float, b: float) -> List[Tuple[int, float]]:
    """[(índice, sobreposição em s)] dos trechos que caem em [a, b], do que mais cobre pro que menos cobre."""
    out = []
    for i, s in enumerate(pend):
        sa, sb = float(s.get("start") or 0), float(s.get("end") or 0)
        sobra = min(b, sb) - max(a, sa)
        if sobra > 0.05:
            out.append((i, sobra))
    if not out:  # o item cai num buraco: o trecho mais perto
        if pend:
            meio = (a + b) / 2
            i = min(range(len(pend)), key=lambda k: abs((float(pend[k]["start"]) + float(pend[k]["end"])) / 2 - meio))
            out = [(i, 0.0)]
    return sorted(out, key=lambda x: (-x[1], x[0]))


def substituir(job: Dict[str, Any], item: Dict[str, Any], caminhos: List[str]) -> List[Dict[str, Any]]:
    """🔁 As fotos do item entram no lugar das cenas do momento em que ele é falado (uma foto por trecho, na ordem).
    Devolve o que foi feito (com o que estava antes, pra desfazer)."""
    pend = job.get("pending_segments") or []
    alvos = sorted(i for i, _ in trechos_no_intervalo(pend, float(item["start"]), float(item["end"]))[:max(1, len(caminhos))])
    feitos = []
    for k, i in enumerate(alvos):
        cam = caminhos[min(k, len(caminhos) - 1)]
        antes = {"override_source": pend[i].get("override_source"), "media_type": pend[i].get("media_type")}
        pend[i]["override_source"] = {"source": "local_file", "value": cam, "kind": "image", "zoom_direction": "in",
                                      "fotos_editor": item["id"]}
        pend[i]["media_type"] = "image"
        pend[i].pop("assembly_error", None)
        feitos.append({"id": uuid.uuid4().hex[:8], "modo": "substituir", "item": item["id"], "trecho": i, "foto": cam,
                       "antes": antes, "quando": time.time()})
    return feitos


POSICOES = {"canto": {"position": "top-right", "size_percent": 32.0, "x_percent": 80.0, "y_percent": 22.0},
            "centro": {"position": "center", "size_percent": 62.0, "x_percent": 50.0, "y_percent": 50.0}}


def camada(job: Dict[str, Any], item: Dict[str, Any], caminhos: List[str], onde: str = "canto") -> List[Dict[str, Any]]:
    """➕ As fotos entram POR CIMA do vídeo (overlay) no momento do item — várias fotos dividem o tempo."""
    a, b = float(item["start"]), float(item["end"])
    b = max(b, a + 3.0)
    passo = (b - a) / max(1, len(caminhos))
    feitos = []
    for k, cam in enumerate(caminhos):
        ov = {"id": uuid.uuid4().hex[:8], "media_type": "image",
              "source": {"source": "local_file", "value": cam, "kind": "image"},
              "start": round(a + k * passo, 2), "end": round(a + (k + 1) * passo, 2), "fotos_editor": item["id"]}
        ov.update(POSICOES.get(onde) or POSICOES["canto"])
        job.setdefault("overlays", []).append(ov)
        feitos.append({"id": uuid.uuid4().hex[:8], "modo": "camada", "item": item["id"], "overlay": ov["id"], "foto": cam,
                       "quando": time.time()})
    return feitos


def desfazer(job: Dict[str, Any], feito: Dict[str, Any]) -> None:
    if feito.get("modo") == "substituir":
        pend = job.get("pending_segments") or []
        i = int(feito.get("trecho", -1))
        if 0 <= i < len(pend):
            atual = pend[i].get("override_source") or {}
            if atual.get("value") == feito.get("foto"):  # só volta se ninguém trocou de novo depois
                antes = feito.get("antes") or {}
                if antes.get("override_source"):
                    pend[i]["override_source"] = antes["override_source"]
                else:
                    pend[i].pop("override_source", None)
                if antes.get("media_type"):
                    pend[i]["media_type"] = antes["media_type"]
    elif feito.get("modo") == "camada":
        job["overlays"] = [o for o in job.get("overlays") or [] if o.get("id") != feito.get("overlay")]


# ------------------------------------------------------------------ rotas
def registrar(app, base_dir: str, jobs: Dict[str, Dict[str, Any]], salvar_job: Callable[[str], None],
              pasta_do_job: Callable[[str], str], load_site_config: Callable[[], Dict[str, Any]]) -> None:
    from flask import jsonify, render_template, request, send_file
    import threading
    import navegador_imagens as nav

    trava = threading.Lock()

    def _job(jid: str) -> Optional[Dict[str, Any]]:
        j = jobs.get(jid)
        return j if j and "pending_segments" in j else None

    def _estado(jid: str, job: Dict[str, Any]) -> Dict[str, Any]:
        fe = job.get("fotos_editor") or {}
        fotos: Dict[str, List[Dict[str, Any]]] = {}
        for m in job.get("media_library") or []:
            if m.get("fotos_editor"):
                fotos.setdefault(m["fotos_editor"], []).append(
                    {"bib": m["id"], "url": f"/job/{jid}/fotos-editor/foto/{m['id']}", "nome": m.get("filename")})
        usadas = {}
        for f in fe.get("feitos") or []:
            usadas.setdefault(f["item"], []).append({k: f.get(k) for k in ("id", "modo", "trecho", "overlay", "foto")})
        return {"itens": fe.get("itens") or [], "fotos": fotos, "feitos": usadas, "analisando": bool(fe.get("analisando")),
                "erro": fe.get("erro"), "duracao": job.get("total_duration")}

    @app.route("/job/<jid>/fotos-editor")
    def fotos_editor_pagina(jid: str):
        job = _job(jid)
        if not job:
            return "Vídeo não encontrado.", 404
        return render_template("fotos_editor.html", job=job, jid=jid)

    @app.route("/job/<jid>/fotos-editor/estado")
    def fotos_editor_estado(jid: str):
        job = _job(jid)
        if not job:
            return jsonify({"erro": "Vídeo não encontrado."}), 404
        return jsonify(_estado(jid, job))

    @app.route("/job/<jid>/fotos-editor/analisar", methods=["POST"])
    def fotos_editor_analisar(jid: str):
        job = _job(jid)
        if not job:
            return jsonify({"erro": "Vídeo não encontrado."}), 404
        fe = job.setdefault("fotos_editor", {})
        if fe.get("analisando"):
            return jsonify({"ok": True, "ja": True})
        fe.update(analisando=True, erro=None)

        def _rodar():
            try:
                itens = analisar(job, job_id=jid)
                with trava:
                    antigos = {i["nome"].lower(): i for i in fe.get("itens") or []}
                    for it in itens:  # mantém o id (e as fotos) dos itens que já existiam
                        if it["nome"].lower() in antigos:
                            it["id"] = antigos[it["nome"].lower()]["id"]
                    fe["itens"] = itens
            except Exception as exc:  # noqa: BLE001
                fe["erro"] = str(exc)[:500]
            finally:
                fe["analisando"] = False
                salvar_job(jid)
        threading.Thread(target=_rodar, daemon=True).start()
        return jsonify({"ok": True})

    @app.route("/job/<jid>/fotos-editor/item", methods=["POST"])
    def fotos_editor_item(jid: str):
        """Cria/edita um item à mão (nome, busca, start, end) ou apaga (apagar: true)."""
        job = _job(jid)
        if not job:
            return jsonify({"erro": "Vídeo não encontrado."}), 404
        c = request.get_json(silent=True) or {}
        with trava:
            fe = job.setdefault("fotos_editor", {})
            itens = fe.setdefault("itens", [])
            it = next((x for x in itens if x["id"] == c.get("id")), None)
            if c.get("apagar"):
                fe["itens"] = [x for x in itens if x["id"] != c.get("id")]
            else:
                if not it:
                    it = {"id": uuid.uuid4().hex[:8], "tipo": "outro", "frase": "", "por_que": "à mão"}
                    itens.append(it)
                for k in ("nome", "busca"):
                    if c.get(k) is not None:
                        it[k] = str(c[k]).strip()[:200]
                for k in ("start", "end"):
                    if c.get(k) is not None:
                        try:
                            it[k] = round(max(0.0, float(c[k])), 2)
                        except (TypeError, ValueError):
                            pass
                it.setdefault("nome", it.get("busca") or "item")
                it.setdefault("busca", it.get("nome") or "")
                it.setdefault("start", 0.0)
                if float(it.get("end") or 0) <= float(it["start"]):
                    it["end"] = round(float(it["start"]) + 4.0, 2)
                itens.sort(key=lambda x: float(x.get("start") or 0))
        salvar_job(jid)
        return jsonify({"ok": True, **_estado(jid, job)})

    @app.route("/job/<jid>/fotos-editor/guias", methods=["POST"])
    def fotos_editor_guias(jid: str):
        """🧲 Abre o Brave do site com uma guia do Google Imagens por item (os pedidos, ou os que ainda não têm foto)."""
        job = _job(jid)
        if not job:
            return jsonify({"erro": "Vídeo não encontrado."}), 404
        c = request.get_json(silent=True) or {}
        st = _estado(jid, job)
        pedidos = [str(x) for x in c.get("ids") or []]
        itens = [i for i in st["itens"] if (i["id"] in pedidos if pedidos else not st["fotos"].get(i["id"]))]
        itens = itens[:max(1, min(10, int(c.get("quantas") or 6)))]
        if not itens:
            return jsonify({"ok": True, "abertas": 0, "msg": "Todos os itens já têm foto (marque os que quer abrir de novo)."})
        site = request.host_url.rstrip("/")
        urls = [nav.url_google(i["busca"], nav.destino(site, jid, i["id"], rotulo=i["nome"], modo="estudio")) for i in itens]
        r = nav.abrir(base_dir, urls, load_site_config(), chaves=[i["id"] for i in itens], pid=jid)
        if not r.get("ok"):
            return jsonify({"ok": False, "erro": r.get("erro"), "urls": urls}), 400
        return jsonify({"ok": True, "abertas": r.get("guias"), "navegador": r.get("navegador"), "aviso": r.get("aviso")})

    @app.route("/job/<jid>/fotos-editor/link", methods=["POST"])
    def fotos_editor_link(jid: str):
        """O userscript da guia manda cada imagem marcada (link ou bytes) → 🖼️ Biblioteca do vídeo, ligada ao item."""
        job = _job(jid)
        if not job:
            return jsonify({"ok": False, "erro": "Vídeo não encontrado (o site reiniciou?)."}), 404
        c = request.get_json(silent=True, force=True) or {}
        item_id = str(c.get("pergunta") or "")[:12]
        pasta = os.path.join(pasta_do_job(jid), "media_library")
        try:
            cam = baixar_para(pasta, str(c.get("url") or ""), str(c.get("dados_b64") or ""))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "erro": f"não consegui baixar ({str(exc)[:140]})"}), 400
        with trava:
            m = {"id": uuid.uuid4().hex[:8], "filename": os.path.basename(cam), "path": cam, "media_type": "image",
                 "fotos_editor": item_id, "origem_url": str(c.get("url") or "")[:500]}
            job.setdefault("media_library", []).append(m)
        salvar_job(jid)
        return jsonify({"ok": True, "midia": {"id": m["id"]}})

    @app.route("/job/<jid>/fotos-editor/guia-feita", methods=["POST"])
    def fotos_editor_guia_feita(jid: str):
        return jsonify({"ok": True})

    @app.route("/job/<jid>/fotos-editor/foto/<bib>")
    def fotos_editor_foto(jid: str, bib: str):
        job = _job(jid)
        m = next((x for x in (job or {}).get("media_library") or [] if x.get("id") == bib), None)
        if not m or not os.path.isfile(m.get("path") or ""):
            return "Foto não encontrada.", 404
        return send_file(m["path"])

    @app.route("/job/<jid>/fotos-editor/aplicar", methods=["POST"])
    def fotos_editor_aplicar(jid: str):
        """{item, fotos:[bib…], modo: substituir|camada, onde: canto|centro}"""
        job = _job(jid)
        if not job:
            return jsonify({"erro": "Vídeo não encontrado."}), 404
        c = request.get_json(silent=True) or {}
        with trava:
            fe = job.setdefault("fotos_editor", {})
            item = next((x for x in fe.get("itens") or [] if x["id"] == c.get("item")), None)
            if not item:
                return jsonify({"erro": "Item não encontrado."}), 404
            bibs = {m["id"]: m for m in job.get("media_library") or []}
            caminhos = [bibs[b]["path"] for b in c.get("fotos") or [] if b in bibs and os.path.isfile(bibs[b]["path"])]
            if not caminhos:
                return jsonify({"erro": "Marque pelo menos uma foto desse item."}), 400
            if c.get("modo") == "camada":
                feitos = camada(job, item, caminhos, str(c.get("onde") or "canto"))
            else:
                feitos = substituir(job, item, caminhos)
            fe.setdefault("feitos", []).extend(feitos)
        salvar_job(jid)
        return jsonify({"ok": True, "feitos": feitos, **_estado(jid, job)})

    @app.route("/job/<jid>/fotos-editor/desfazer", methods=["POST"])
    def fotos_editor_desfazer(jid: str):
        job = _job(jid)
        if not job:
            return jsonify({"erro": "Vídeo não encontrado."}), 404
        fid = str((request.get_json(silent=True) or {}).get("id") or "")
        with trava:
            fe = job.setdefault("fotos_editor", {})
            f = next((x for x in fe.get("feitos") or [] if x["id"] == fid), None)
            if not f:
                return jsonify({"erro": "Não achei o que desfazer."}), 404
            desfazer(job, f)
            fe["feitos"] = [x for x in fe["feitos"] if x["id"] != fid]
        salvar_job(jid)
        return jsonify({"ok": True, **_estado(jid, job)})
