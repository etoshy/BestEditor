"""
flow_teste.py
=============

🧪 ÁREA DE TESTE DO GOOGLE FLOW (/flow/teste) — roda a automação do Flow (modo direto, `flow_direto.py`) passo a
passo, com o navegador VISÍVEL ou oculto, e mostra cada passo (✅/❌, quanto levou, a foto da tela depois dele).

  • 🧪 Teste completo: abrir → novo projeto → configurações do agente (Nunca + padrões + Salvar) → desligar o agente →
    imagem → vídeo só com texto (Elementos) → vídeo com Início (a imagem gerada) e Fim (um arquivo) — com a opção
    "sem gerar" (faz tudo até antes do "Iniciar geração": testa a automação sem gastar crédito).
  • ▶ Gerar um: imagem / vídeo / vídeo com frames, com prompt, modelo, proporção e as imagens que você escolher.

Quando um passo falha, o HTML da tela e a foto ficam em flow_dados/diagnostico/ (mande pra ajustar).
"""
from __future__ import annotations

import os
import re
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

from flask import jsonify, render_template, request, send_from_directory

_ESTADO: Dict[str, Any] = {"rodando": False, "passos": [], "resultados": [], "erro": None, "inicio": None, "fim": None,
                           "modo": None, "parar": False}
_TRAVA = threading.Lock()
PROMPT_IMAGEM = "A red apple on a rustic wooden table, soft window light, photorealistic"
PROMPT_VIDEO = "Slow cinematic push-in on a calm lake at sunrise, gentle mist"
PROMPT_ANIMAR = "The camera slowly pushes in, soft natural motion"


def pasta(gf) -> str:
    p = os.path.join(str(gf.pasta_dados()), "teste")
    os.makedirs(p, exist_ok=True)
    return p


class _Parado(Exception):
    pass


def _rodar(cfg: Dict[str, Any], opcoes: Dict[str, Any]) -> None:
    from googleflow import flow_direto as fd
    from googleflow import googleflow_client as gf
    from playwright.sync_api import sync_playwright
    dest = pasta(gf)
    for n in os.listdir(dest):  # o teste anterior sai (fotos e arquivos)
        try:
            os.remove(os.path.join(dest, n))
        except OSError:
            pass
    est = _ESTADO
    atual: Dict[str, Any] = {"page": None, "t": time.monotonic()}

    def on_passo(nome: str, estado: str, detalhe: str) -> None:
        if est["parar"]:
            raise _Parado()
        agora = time.monotonic()
        passos = est["passos"]
        if passos and passos[-1]["nome"] == nome and passos[-1]["estado"] == "andando":
            passos[-1].update(estado=estado, detalhe=detalhe or passos[-1]["detalhe"],
                              segundos=round(agora - passos[-1]["_t0"], 1))
            p = passos[-1]
        else:
            p = {"n": len(passos) + 1, "nome": nome, "estado": estado, "detalhe": detalhe, "_t0": agora, "segundos": 0.0, "foto": None}
            passos.append(p)
        if estado in ("ok", "erro", "pulado") and atual["page"] is not None:
            try:
                foto = f"passo_{p['n']:02d}.jpg"
                atual["page"].screenshot(path=os.path.join(dest, foto), type="jpeg", quality=60)
                p["foto"] = foto
            except Exception:  # noqa: BLE001
                pass

    def baixar(context, midias: List[Dict[str, str]], rotulo: str) -> None:
        for k, m in enumerate(midias[:1]):
            try:
                if m["url"].startswith("blob:"):
                    continue
                r = context.request.get(m["url"])
                if not r.ok:
                    raise RuntimeError(f"HTTP {r.status}")
                ext = "mp4" if m["tipo"] == "video" else ("jpg" if "jpeg" in r.headers.get("content-type", "") else "png")
                nome = f"{rotulo}_{k + 1}.{ext}"
                with open(os.path.join(dest, nome), "wb") as f:
                    f.write(r.body())
                est["resultados"].append({"rotulo": rotulo, "arquivo": nome, "tipo": m["tipo"], "media_id": m["id"]})
                on_passo("baixar_" + rotulo, "ok", nome)
            except Exception as exc:  # noqa: BLE001
                on_passo("baixar_" + rotulo, "erro", f"não baixou: {exc}")

    visivel = bool(opcoes.get("visivel"))
    conta = opcoes.get("conta") or gf.CONTA_PADRAO
    simular = bool(opcoes.get("simular"))
    timeout = int(cfg.get("flow_timeout_seconds") or 300)
    try:
        gf.encerrar_sessao()  # o perfil do navegador é exclusivo: fecha a sessão de geração antes
        with gf._FLOW_LOCK:
            with sync_playwright() as p:
                context, fechar = gf._abrir(p, cfg, headless=not visivel, conta=conta)
                try:
                    if fechar:
                        gf.restaurar_sessao(context, conta)
                    page = fd.abrir_flow(context, gf.FLOW_URL, headless=not visivel, on_passo=on_passo)
                    atual["page"] = page
                    page = fd.novo_projeto(page, context, on_passo)
                    atual["page"] = page
                    gf.salvar_sessao(context, conta)
                    if opcoes.get("modo") == "completo" or opcoes.get("configurar_agente"):
                        fd.configurar_agente(page, on_passo=on_passo, **gf.agente_da_cfg(cfg))
                    fd.desligar_agente(page, on_passo)
                    if opcoes.get("modo") == "completo":
                        img = fd.gerar_um(page, {"tipo": "imagem", "prompt": PROMPT_IMAGEM, "proporcao": "16:9",
                                                 "modelo": cfg.get("flow_modelo_imagem") or "", "simular": simular}, on_passo, timeout)
                        baixar(context, img, "imagem")
                        vid = fd.gerar_um(page, {"tipo": "video", "tipo_video": "Elementos", "prompt": PROMPT_VIDEO, "proporcao": "16:9",
                                                 "modelo": cfg.get("flow_modelo_video") or "", "simular": simular}, on_passo, timeout)
                        baixar(context, vid, "video_texto")
                        inicio = {"media_id": img[0]["id"]} if img else {"arquivo": opcoes["imagem_teste"]}
                        ani = fd.gerar_um(page, {"tipo": "video", "tipo_video": "Frames", "prompt": PROMPT_ANIMAR, "proporcao": "16:9",
                                                 "modelo": cfg.get("flow_modelo_video") or "", "inicio": inicio,
                                                 "fim": {"arquivo": opcoes["imagem_teste"]}, "simular": simular}, on_passo, timeout)
                        baixar(context, ani, "video_frames")
                    else:
                        trab = {"tipo": opcoes.get("tipo") or "imagem", "prompt": opcoes.get("prompt") or PROMPT_IMAGEM,
                                "proporcao": opcoes.get("proporcao") or "16:9", "modelo": opcoes.get("modelo") or "",
                                "quantidade": opcoes.get("quantidade") or "x1", "simular": simular,
                                "tipo_video": "Frames" if (opcoes.get("inicio") or opcoes.get("fim")) else "Elementos"}
                        for k in ("inicio", "fim", "referencia"):
                            if opcoes.get(k):
                                trab[k] = {"arquivo": opcoes[k]}
                        r = fd.gerar_um(page, trab, on_passo, timeout)
                        baixar(context, r, "resultado")
                finally:
                    try:
                        gf.salvar_sessao(context, conta)
                    except Exception:  # noqa: BLE001
                        pass
                    if fechar:
                        context.close()
    except _Parado:
        est["erro"] = "Parado por você."
    except fd.FlowPassoErro as exc:
        diag = gf.salvar_diagnostico(atual["page"], str(exc)) if atual["page"] is not None else None
        _marcar_erro(exc.passo, exc.mensagem)
        est["erro"] = str(exc) + (f" — a tela e o HTML ficaram em {diag}.png / _html.txt (mande pra ajustar)" if diag else "")
        est["diagnostico"] = os.path.basename(diag) if diag else None
    except Exception as exc:  # noqa: BLE001
        est["erro"] = f"{type(exc).__name__}: {exc}"
        est["detalhe_erro"] = traceback.format_exc()[-2500:]
    finally:
        est["rodando"], est["fim"] = False, time.time()


def _marcar_erro(passo: str, msg: str) -> None:
    passos = _ESTADO["passos"]
    alvo = next((p for p in reversed(passos) if p["nome"] == passo), None)
    if alvo is None or alvo["estado"] != "andando":
        alvo = {"n": len(passos) + 1, "nome": passo, "estado": "erro", "detalhe": msg, "_t0": time.monotonic(), "segundos": 0, "foto": None}
        passos.append(alvo)
    alvo.update(estado="erro", detalhe=msg)


def _imagem_teste(gf) -> str:
    """Uma imagem simples pro teste de frames (sem gerar nada antes)."""
    caminho = os.path.join(str(gf.pasta_dados()), "teste_frame.png")
    if not os.path.exists(caminho):
        from PIL import Image, ImageDraw
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        im = Image.new("RGB", (1280, 720), (28, 60, 110))
        ImageDraw.Draw(im).ellipse((520, 240, 760, 480), fill=(240, 200, 60))
        im.save(caminho)
    return caminho


def registrar(app, base_dir: str) -> None:

    @app.route("/flow/teste")
    def flow_teste_page():
        from googleflow import flow_direto as fd
        from googleflow import googleflow_client as gf
        from site_config import load_site_config
        cfg = load_site_config()
        return render_template("flow_teste.html", contas=[c["nome"] for c in gf.listar_contas()], cfg=cfg,
                               modelos_imagem=fd.MODELOS_IMAGEM, modelos_video=fd.MODELOS_VIDEO, proporcoes=fd.PROPORCOES,
                               modo_direto=gf.modo_direto(cfg))

    @app.route("/flow/teste/iniciar", methods=["POST"])
    def flow_teste_iniciar():
        from googleflow import googleflow_client as gf
        from site_config import load_site_config
        with _TRAVA:
            if _ESTADO["rodando"]:
                return jsonify({"erro": "Já tem um teste rodando — espere ou clique em Parar."}), 409
            f = request.form
            modo = "completo" if f.get("modo") == "completo" else "um"
            opcoes: Dict[str, Any] = {"modo": modo, "visivel": f.get("visivel") == "on", "simular": f.get("simular") == "on",
                                      "conta": f.get("conta") or "", "configurar_agente": f.get("configurar_agente") == "on",
                                      "tipo": f.get("tipo") if f.get("tipo") in ("imagem", "video") else "imagem",
                                      "prompt": " ".join((f.get("prompt") or "").split())[:2000],
                                      "modelo": (f.get("modelo") or "").strip()[:60], "proporcao": f.get("proporcao") or "16:9",
                                      "quantidade": f.get("quantidade") if f.get("quantidade") in ("x1", "x2", "x3", "x4") else "x1",
                                      "imagem_teste": _imagem_teste(gf)}
            if modo == "um" and not opcoes["prompt"]:
                return jsonify({"erro": "Escreva o prompt."}), 400
            entrada = os.path.join(pasta(gf), "..", "teste_entrada")
            os.makedirs(entrada, exist_ok=True)
            for k in ("inicio", "fim", "referencia"):
                arq = request.files.get(k)
                if arq and arq.filename:
                    ext = os.path.splitext(arq.filename)[1].lower()
                    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
                        return jsonify({"erro": f"{k}: só imagem (.png, .jpg, .webp)."}), 400
                    caminho = os.path.abspath(os.path.join(entrada, f"{k}{ext}"))
                    arq.save(caminho)
                    opcoes[k] = caminho
            if opcoes.get("inicio") or opcoes.get("fim"):
                opcoes["tipo"] = "video"
            _ESTADO.update(rodando=True, passos=[], resultados=[], erro=None, inicio=time.time(), fim=None, modo=modo,
                           parar=False, diagnostico=None, detalhe_erro=None,
                           opcoes={k: v for k, v in opcoes.items() if k not in ("imagem_teste",)})
            cfg = load_site_config()
            threading.Thread(target=_rodar, args=(cfg, opcoes), name="flow-teste", daemon=True).start()
        return jsonify({"ok": True})

    @app.route("/flow/teste/status")
    def flow_teste_status():
        e = {k: v for k, v in _ESTADO.items() if k != "parar"}
        e["passos"] = [{k: v for k, v in p.items() if not k.startswith("_")} for p in _ESTADO["passos"]]
        return jsonify(e)

    @app.route("/flow/teste/parar", methods=["POST"])
    def flow_teste_parar():
        _ESTADO["parar"] = True
        return jsonify({"ok": True})

    @app.route("/flow/teste/arquivo/<path:nome>")
    def flow_teste_arquivo(nome: str):
        from googleflow import googleflow_client as gf
        if not re.fullmatch(r"[\w.\-]+", nome):
            return "nome inválido", 400
        return send_from_directory(pasta(gf), nome)
