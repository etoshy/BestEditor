"""
Rotas da aba 🛒 Vídeo de venda (ver vendas.py). Registradas pelo app.py com
`registrar(app, base_dir)`.
"""
from __future__ import annotations

import os
import re
import threading
import uuid
from typing import Any, Dict

from flask import abort, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

import vendas as vd


def registrar(app, base_dir: str) -> None:

    def _ia_depois(pid: str, ids=None) -> bool:
        """🤖 ficha das fotos do produto em segundo plano (com a IA ligada)."""
        import ia_servico
        if not ia_servico.ativo("venda_imagens"):
            return False
        threading.Thread(target=lambda: vd.ia_analisar_imagens(base_dir, pid, ids), daemon=True).start()
        return True

    def _proj(pid: str):
        try:
            return vd.carregar(base_dir, pid)
        except vd.VendaError:
            return None

    def _json_proj(p: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(p)
        import midia_transcricao as mt
        out["midias"] = []
        for m in p.get("midias") or []:
            cam = vd.caminho_midia(base_dir, p, m)
            item = dict(m, url_arquivo=(f"/vendas/{p['id']}/arquivo/{m['id']}" if cam else ""))
            if cam and mt.eh_video(cam):
                mt.agendar(cam)  # sem transcrição ainda (ou interrompida): faz em segundo plano
                item["transcricao"] = mt.resumo(cam)
            out["midias"].append(item)
        return out

    @app.context_processor
    def _vendas_no_template():
        return {"vendas_lista": lambda: vd.listar(base_dir)}

    @app.route("/vendas")
    def vendas_page():
        return render_template("vendas.html", projetos=vd.listar(base_dir), erro=request.args.get("erro"))

    @app.route("/vendas/novo", methods=["POST"])
    def vendas_novo():
        link = (request.form.get("link") or "").strip()
        nome = (request.form.get("nome") or "").strip()
        if link and not link.lower().startswith(("http://", "https://")):
            return redirect(url_for("vendas_page", erro="O link precisa começar com http:// ou https://."))
        p = vd.criar(base_dir, link=link, nome=nome)
        if link:
            _ler_link(p)
        vd.salvar(base_dir, p)
        if link:
            _ia_depois(p["id"])
        return redirect(url_for("venda_detalhe", pid=p["id"]))

    def _guardar_produto(p: Dict[str, Any], dados: Dict[str, Any]) -> None:
        p["produto"] = {k: dados.get(k) or ([] if k in ("topicos", "imagens", "videos") else ({} if k == "legendas" else ""))
                        for k in ("titulo", "preco", "topicos", "descricao", "detalhes", "imagens", "videos", "conteudo", "legendas")}
        p["loja"] = dados.get("loja") or p.get("loja") or "outro"
        p["produto_erro"] = None

    def _ler_link(p: Dict[str, Any], com_fotos: bool = True, html: str = None) -> None:
        """Lê a página do produto (Amazon, Gumroad, landing page… — ou o HTML enviado) e
        (opcional) baixa as fotos como mídias do projeto."""
        try:
            if html is None:
                html, final = vd.baixar_html(p["link"])
            else:
                final = p.get("link") or ""
            dados = vd.ler_produto(html, final, p.get("link") or "")
            _guardar_produto(p, dados)
        except vd.VendaError as exc:
            p["produto_erro"] = str(exc)
            return
        if not com_fotos:
            return
        leg = p["produto"].get("legendas") or {}
        ja = {m.get("url") for m in p.get("midias") or []}
        n = sum(1 for m in p.get("midias") or [] if m.get("do_produto"))
        for u in (p["produto"].get("imagens") or [])[:8] + (p["produto"].get("videos") or [])[:2]:
            if u in ja:
                continue
            try:
                cam, tipo = vd.baixar_arquivo(u, vd.pasta_midias(base_dir, p["id"]), f"produto_{uuid.uuid4().hex[:6]}")
            except vd.VendaError:
                continue
            n += 1
            vd.adicionar_midia(p, tipo=tipo, origem="url", url=u, arquivo=os.path.basename(cam), do_produto=True,
                               nome=os.path.basename(cam),
                               descricao=f"{'Foto' if tipo == 'foto' else 'Vídeo'} {n} do produto (página da loja): "
                                         f"{(p['produto'].get('titulo') or '')[:120]}"
                                         + (f" — na página: {leg[u][:300]}" if leg.get(u) else ""), usar="descricao")

    @app.route("/vendas/<pid>")
    def venda_detalhe(pid: str):
        p = _proj(pid)
        if not p:
            return redirect(url_for("vendas_page", erro="Projeto não encontrado."))
        import idiomas
        return render_template("venda_detalhe.html", p=_json_proj(p), tecnicas=vd.TECNICAS, filtros=vd.FILTROS,
                               link_onde=vd.LINK_ONDE, preco_modo=vd.PRECO_MODO, tipos=vd.TIPOS_MIDIA,
                               idiomas=[(k, v[0]) for k, v in idiomas.IDIOMAS.items()])

    @app.route("/vendas/<pid>/dados")
    def venda_dados(pid: str):
        p = _proj(pid)
        return jsonify(_json_proj(p)) if p else (jsonify({"erro": "Projeto não encontrado."}), 404)

    @app.route("/vendas/<pid>/ler-link", methods=["POST"])
    def venda_ler_link(pid: str):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        corpo = request.get_json(silent=True) or {}
        if corpo.get("link"):
            if not str(corpo["link"]).lower().startswith(("http://", "https://")):
                return jsonify({"erro": "O link precisa começar com http:// ou https://."}), 400
            p["link"] = str(corpo["link"]).strip()[:2000]
            p["loja"] = "amazon" if vd._eh_amazon(p["link"]) else "outro"
        if not p.get("link"):
            return jsonify({"erro": "Cole o link do produto."}), 400
        _ler_link(p, com_fotos=corpo.get("fotos", True) is not False)
        vd.salvar(base_dir, p)
        _ia_depois(pid)
        if p.get("produto_erro"):
            return jsonify({"erro": p["produto_erro"], "projeto": _json_proj(p)}), 502
        return jsonify({"ok": True, "projeto": _json_proj(p)})

    @app.route("/vendas/<pid>/ler-html", methods=["POST"])
    def venda_ler_html(pid: str):
        """Página salva no navegador (Ctrl+S → .html) — pra páginas que pedem login ou bloqueiam robôs."""
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        arq = request.files.get("arquivo")
        if not arq or not arq.filename or not arq.filename.lower().endswith((".html", ".htm", ".mhtml", ".txt")):
            return jsonify({"erro": "Envie a página salva (.html)."}), 400
        bruto = arq.read(15 * 1024 * 1024)
        html = bruto.decode("utf-8", errors="replace")
        if arq.filename.lower().endswith(".mhtml"):
            import quopri
            html = quopri.decodestring(bruto).decode("utf-8", errors="replace")
        link = (request.form.get("link") or "").strip()
        if link.lower().startswith(("http://", "https://")):
            p["link"] = link[:2000]
        elif not p.get("link"):
            m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\'](https?://[^"\']+)', html, re.I) or \
                re.search(r'<meta[^>]+property=["\']og:url["\'][^>]*content=["\'](https?://[^"\']+)', html, re.I)
            if m:
                p["link"] = m.group(1)[:2000]
        _ler_link(p, com_fotos=request.form.get("fotos", "1") != "0", html=html)
        vd.salvar(base_dir, p)
        _ia_depois(pid)
        if p.get("produto_erro"):
            return jsonify({"erro": p["produto_erro"], "projeto": _json_proj(p)}), 422
        return jsonify({"ok": True, "projeto": _json_proj(p)})

    @app.route("/vendas/<pid>/produto", methods=["POST"])
    def venda_produto(pid: str):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        c = request.get_json(silent=True) or {}
        pr = p.setdefault("produto", {})
        for k, lim in (("titulo", 300), ("preco", 40), ("descricao", 6000), ("detalhes", 3000), ("conteudo", vd.MAX_CONTEUDO_PAGINA)):
            if k in c:
                pr[k] = str(c.get(k) or "").strip()[:lim]
        if "topicos" in c:
            lista = c["topicos"] if isinstance(c["topicos"], list) else str(c["topicos"] or "").split("\n")
            pr["topicos"] = [str(x).strip().lstrip("-•· ").strip()[:500] for x in lista if str(x).strip()][:20]
        if "nome" in c:
            p["nome"] = str(c.get("nome") or "").strip()[:160]
        if "link" in c:
            link = str(c.get("link") or "").strip()
            if link and not link.lower().startswith(("http://", "https://")):
                return jsonify({"erro": "O link precisa começar com http:// ou https://."}), 400
            p["link"] = link[:2000]
        vd.salvar(base_dir, p)
        return jsonify({"ok": True})

    @app.route("/vendas/<pid>/midia", methods=["POST"])
    def venda_midia_pc(pid: str):
        """Foto/vídeo do PC: a pessoa TEM que dizer o que é."""
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        arq = request.files.get("arquivo")
        desc = (request.form.get("descricao") or "").strip()
        if not arq or not arq.filename:
            return jsonify({"erro": "Escolha o arquivo."}), 400
        import ia_servico
        if not desc and not ia_servico.ativo("venda_imagens"):  # 🤖 com a IA, ela descreve
            return jsonify({"erro": "Diga o que é esse arquivo (ex.: \"produto aberto mostrando os compartimentos\")."}), 400
        tipo = vd.tipo_do_arquivo(arq.filename)
        if not tipo:
            return jsonify({"erro": "Só fotos (jpg, png, webp…) e vídeos (mp4, mov, webm…)."}), 400
        nome = secure_filename(arq.filename) or f"arquivo{os.path.splitext(arq.filename)[1]}"
        os.makedirs(vd.pasta_midias(base_dir, pid), exist_ok=True)
        dest = os.path.join(vd.pasta_midias(base_dir, pid), f"pc_{uuid.uuid4().hex[:6]}_{nome}")
        arq.save(dest)
        m = vd.adicionar_midia(p, tipo=tipo, origem="pc", arquivo=os.path.basename(dest), nome=arq.filename, descricao=desc,
                               usar="descricao" if desc else "ambos")
        vd.salvar(base_dir, p)
        return jsonify({"ok": True, "midia": m, "ia": _ia_depois(pid, [m["id"]])})

    @app.route("/vendas/<pid>/midia-url", methods=["POST"])
    def venda_midia_url(pid: str):
        """Link: arquivo de foto/vídeo é baixado; página vira OG (título, descrição,
        imagem — a imagem é baixada pra poder entrar no vídeo)."""
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        c = request.get_json(silent=True) or {}
        url = str(c.get("url") or "").strip()
        desc = str(c.get("descricao") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return jsonify({"erro": "Cole um link que comece com http:// ou https://."}), 400
        pasta = vd.pasta_midias(base_dir, pid)
        nome_base = f"url_{uuid.uuid4().hex[:6]}"
        if vd.tipo_do_arquivo(url.split("?")[0]):
            try:
                cam, tipo = vd.baixar_arquivo(url, pasta, nome_base)
            except vd.VendaError as exc:
                return jsonify({"erro": str(exc)}), 502
            m = vd.adicionar_midia(p, tipo=tipo, origem="url", url=url, arquivo=os.path.basename(cam), nome=url[-80:],
                                   descricao=desc, usar="descricao")
            if not desc:
                m["descricao"] = ""
        else:
            try:
                html, final = vd.baixar_html(url, navegador=False)
            except vd.VendaError:
                html, final = "", url
            og = vd.ler_og(html, final) if html else {"titulo": "", "descricao": "", "imagem": "", "video": "", "site": "", "url": url}
            conteudo = ""
            if html and c.get("conteudo", True) is not False:
                try:
                    conteudo = vd.ler_pagina(html, final).get("conteudo") or ""
                except Exception:  # noqa: BLE001
                    conteudo = ""
            if not html and not desc:
                return jsonify({"erro": "Não consegui abrir esse link. Descreva o que ele é pra usar mesmo assim."}), 502
            arquivo, tipo = "", "link"
            for u in (og.get("video"), og.get("imagem")):
                if not u:
                    continue
                try:
                    cam, tipo = vd.baixar_arquivo(u, pasta, nome_base)
                    arquivo = os.path.basename(cam)
                    break
                except vd.VendaError:
                    continue
            m = vd.adicionar_midia(p, tipo=tipo if arquivo else "link", origem="url", url=url, arquivo=arquivo,
                                   nome=og.get("titulo") or url[-80:], og=og if (og.get("titulo") or og.get("descricao")) else None,
                                   descricao=desc, usar=c.get("usar"), conteudo=conteudo)
        vd.salvar(base_dir, p)
        return jsonify({"ok": True, "midia": m, "precisa_descricao": not (m.get("descricao") or m.get("og"))})

    @app.route("/vendas/<pid>/texto", methods=["POST"])
    def venda_texto(pid: str):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        c = request.get_json(silent=True) or {}
        conteudo, desc = str(c.get("conteudo") or "").strip(), str(c.get("descricao") or "").strip()
        if not conteudo:
            return jsonify({"erro": "Escreva o texto."}), 400
        if not desc:
            return jsonify({"erro": "Diga o que é esse texto (ex.: \"avaliações de clientes\", \"manual\", \"ficha técnica\")."}), 400
        m = vd.adicionar_midia(p, tipo="texto", origem="pc", conteudo=conteudo, descricao=desc, usar="descricao")
        vd.salvar(base_dir, p)
        return jsonify({"ok": True, "midia": m})

    @app.route("/vendas/<pid>/midia/<mid>", methods=["POST", "DELETE"])
    def venda_midia_editar(pid: str, mid: str):
        p = _proj(pid)
        m = vd.midia(p, mid) if p else None
        if not m:
            return jsonify({"erro": "Mídia não encontrada."}), 404
        if request.method == "DELETE":
            cam = vd.caminho_midia(base_dir, p, m)
            p["midias"] = [x for x in p["midias"] if x is not m]
            if cam:
                try:
                    os.remove(cam)
                except OSError:
                    pass
        else:
            c = request.get_json(silent=True) or {}
            if "descricao" in c:
                m["descricao"] = str(c.get("descricao") or "").strip()[:2000]
            if "conteudo" in c and m["tipo"] == "texto":
                m["conteudo"] = str(c.get("conteudo") or "").strip()[:8000]
            if c.get("usar") in ("og", "descricao", "ambos"):
                m["usar"] = c["usar"]
        vd.salvar(base_dir, p)
        return jsonify({"ok": True})

    @app.route("/vendas/<pid>/arquivo/<mid>")
    def venda_arquivo(pid: str, mid: str):
        p = _proj(pid)
        cam = vd.caminho_midia(base_dir, p, vd.midia(p, mid)) if p else None
        if not cam:
            abort(404)
        return send_file(cam, conditional=True)

    @app.route("/vendas/<pid>/config", methods=["POST"])
    def venda_config(pid: str):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        c = request.get_json(silent=True) or {}
        cfg = p.setdefault("config", dict(vd.CONFIG_PADRAO))
        validas_t = {k for k, _n, _d in vd.TECNICAS}
        validos_f = {k for k, _n, _d in vd.FILTROS}
        if "tecnicas" in c:
            cfg["tecnicas"] = [k for k in c.get("tecnicas") or [] if k in validas_t]
        if "filtros" in c:
            cfg["filtros"] = [k for k in c.get("filtros") or [] if k in validos_f]
        for k, opc in (("link_onde", vd.LINK_ONDE), ("preco_modo", vd.PRECO_MODO), ("tipo_produto", {"pago": 1, "gratuito": 1}),
                       ("formato", {"9:16": 1, "16:9": 1, "1:1": 1}), ("apoio_criador", vd.APOIO_CRIADOR)):
            if c.get(k) in opc:
                cfg[k] = c[k]
        for k, lim in (("tom", 400), ("oferta", 600), ("publico", 400), ("proibidos", 600), ("idioma", 20), ("referencia", 12000)):
            if k in c:
                cfg[k] = str(c.get(k) or "").strip()[:lim]
        if "duracao_s" in c:
            try:
                cfg["duracao_s"] = max(10, min(900, int(float(c["duracao_s"]))))
            except (TypeError, ValueError):
                pass
        vd.salvar(base_dir, p)
        return jsonify({"ok": True, "config": cfg})

    @app.route("/vendas/<pid>/prompt", methods=["POST"])
    def venda_prompt(pid: str):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            texto = vd.prompt_roteiro(p, extra=str((request.get_json(silent=True) or {}).get("extra") or ""), base=base_dir)
        except vd.VendaError as exc:
            return jsonify({"erro": str(exc)}), 400
        sem_desc = [m["id"] for m in p.get("midias") or [] if not (m.get("descricao") or m.get("og"))]
        return jsonify({"ok": True, "prompt": texto, "caracteres": len(texto),
                        "aviso": ("Sem descrição: " + ", ".join(sem_desc) + " — a IA não sabe o que são.") if sem_desc else ""})

    @app.route("/vendas/<pid>/roteiro", methods=["POST"])
    def venda_roteiro(pid: str):
        p = _proj(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            p["roteiro"] = vd.ler_roteiro(str((request.get_json(silent=True) or {}).get("texto") or ""), p)
        except vd.VendaError as exc:
            return jsonify({"erro": str(exc)}), 400
        vd.salvar(base_dir, p)
        return jsonify({"ok": True, "roteiro": p["roteiro"], "voz": vd.roteiro_para_voz(p)})

    @app.route("/vendas/<pid>/excluir", methods=["POST"])
    def venda_excluir(pid: str):
        vd.excluir(base_dir, pid)
        return redirect(url_for("vendas_page"))
