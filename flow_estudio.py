"""
flow_estudio.py
===============

🎬 ABA "GOOGLE FLOW" (/flow) — usar o Flow pelo site, sem abrir o flow.google.com na mão:

  • ✨ Gerar: imagem ou vídeo (só texto, ou com frames de Início/Fim), com modelo, proporção, quantidade e imagem de
    referência. O navegador fica ABERTO entre um pedido e outro (mesmo projeto do Flow, então "animar a imagem que
    acabou de sair" usa a própria imagem do projeto) e fecha sozinho depois de alguns minutos parado.
  • 🖼 Galeria: tudo o que foi gerado aqui fica em outputs/flow_estudio/ — baixar, usar como Início/Fim/referência
    de outra geração, apagar.
  • 🧪 Testar o Flow: abre o navegador VISÍVEL e faz o caminho inteiro — novo projeto → configurações do agente
    (Nunca + padrões + Salvar) → desliga o agente → gera uma FOTO → um VÍDEO só com texto → um VÍDEO com Início
    (a foto gerada) e Fim. Cada passo aparece com ✅/❌, o tempo e a foto da tela. "Sem gerar" faz tudo até antes
    do "Iniciar geração" (não gasta crédito).

Tudo do Playwright acontece numa thread só (`_Sessao`), dona do navegador. Enquanto ela está com o navegador
aberto, o resto do site espera pra usar o Flow (o perfil do navegador é exclusivo).

Quando um passo falha, a foto e o HTML da tela ficam em flow_dados/diagnostico/ (mande pra ajustar).
"""
from __future__ import annotations

import json
import os
import queue
import re
import secrets
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from flask import jsonify, redirect, render_template, request, send_from_directory, url_for

OCIOSO_S = 300                    # navegador parado esse tempo → fecha (libera o Flow pro resto do site)
ESPERA_LOCK_S = 25
MAX_GALERIA = 1000
PROMPT_IMAGEM = "A red apple on a rustic wooden table, soft window light, photorealistic"
PROMPT_VIDEO = "Slow cinematic push-in on a calm lake at sunrise, gentle mist"
PROMPT_ANIMAR = "The camera slowly pushes in, soft natural motion"
EXT_IMAGEM = (".png", ".jpg", ".jpeg", ".webp")

_ESTADO: Dict[str, Any] = {"rodando": False, "passos": [], "resultados": [], "erro": None, "inicio": None, "fim": None,
                           "modo": None, "parar": False, "opcoes": {}, "diagnostico": None, "detalhe_erro": None}
_SESSAO_INFO: Dict[str, Any] = {"aberto": False, "visivel": None, "conta": None, "projeto": None, "ultimo_uso": None}
_TRAVA = threading.Lock()
_TRAVA_GALERIA = threading.Lock()
_BASE: Dict[str, str] = {"dir": os.path.dirname(os.path.abspath(__file__))}


_RE_DIAG = re.compile(r"\d{8}_\d{6}_\d{6}")


class _Parado(Exception):
    pass


# ------------------------------------------------------------------ pastas e galeria
def pasta_galeria() -> str:
    p = os.path.join(_BASE["dir"], "outputs", "flow_estudio")
    os.makedirs(p, exist_ok=True)
    return p


def pasta_passos(gf) -> str:
    p = os.path.join(str(gf.pasta_dados()), "teste")
    os.makedirs(p, exist_ok=True)
    return p


def _arq_galeria() -> str:
    return os.path.join(pasta_galeria(), "galeria.json")


def galeria() -> List[Dict[str, Any]]:
    try:
        with open(_arq_galeria(), encoding="utf-8") as f:
            d = json.load(f)
        return [e for e in d if isinstance(e, dict)] if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _gravar_galeria(itens: List[Dict[str, Any]]) -> None:
    tmp = _arq_galeria() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(itens[:MAX_GALERIA], f, ensure_ascii=False, indent=0)
    os.replace(tmp, _arq_galeria())


def adicionar_na_galeria(entrada: Dict[str, Any]) -> None:
    with _TRAVA_GALERIA:
        itens = galeria()
        itens.insert(0, entrada)
        for velho in itens[MAX_GALERIA:]:  # passou do limite: o mais antigo sai (e o arquivo dele)
            _apagar_arquivo(velho)
        _gravar_galeria(itens)


def item_da_galeria(gid: str) -> Optional[Dict[str, Any]]:
    return next((e for e in galeria() if e.get("id") == gid), None)


def _apagar_arquivo(e: Dict[str, Any]) -> None:
    nome = e.get("arquivo") or ""
    if re.fullmatch(r"[\w.\-]+", nome):
        try:
            os.remove(os.path.join(pasta_galeria(), nome))
        except OSError:
            pass


def apagar_da_galeria(gid: str) -> bool:
    with _TRAVA_GALERIA:
        itens = galeria()
        e = next((x for x in itens if x.get("id") == gid), None)
        if not e:
            return False
        _gravar_galeria([x for x in itens if x.get("id") != gid])
    _apagar_arquivo(e)
    return True


# ------------------------------------------------------------------ passos (o que a tela mostra)
def _novo_passo_cb(gf, est: Dict[str, Any], atual: Dict[str, Any]) -> Callable[[str, str, str], None]:
    dest = pasta_passos(gf)

    def on_passo(nome: str, estado: str, detalhe: str) -> None:
        if est["parar"]:
            raise _Parado()
        agora = time.monotonic()
        passos = est["passos"]
        if passos and passos[-1]["nome"] == nome and passos[-1]["estado"] == "andando":
            passos[-1].update(estado=estado, detalhe=detalhe or passos[-1]["detalhe"], segundos=round(agora - passos[-1]["_t0"], 1))
            p = passos[-1]
        else:
            p = {"n": len(passos) + 1, "nome": nome, "estado": estado, "detalhe": detalhe, "_t0": agora, "segundos": 0.0, "foto": None}
            passos.append(p)
        if estado in ("ok", "erro", "pulado") and atual.get("page") is not None:
            try:
                foto = f"passo_{p['n']:02d}.jpg"
                atual["page"].screenshot(path=os.path.join(dest, foto), type="jpeg", quality=60)
                p["foto"] = foto
            except Exception:  # noqa: BLE001
                pass
    return on_passo


def _marcar_erro(passo: str, msg: str) -> None:
    passos = _ESTADO["passos"]
    alvo = next((p for p in reversed(passos) if p["nome"] == passo), None)
    if alvo is None or alvo["estado"] != "andando":
        alvo = {"n": len(passos) + 1, "nome": passo, "estado": "erro", "detalhe": msg, "_t0": time.monotonic(), "segundos": 0, "foto": None}
        passos.append(alvo)
    alvo.update(estado="erro", detalhe=msg)


def _imagem_teste(gf) -> str:
    """Uma imagem simples pro Fim do teste de frames (e pro Início quando não gera nada)."""
    caminho = os.path.join(str(gf.pasta_dados()), "teste_frame.png")
    if not os.path.exists(caminho):
        from PIL import Image, ImageDraw
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        im = Image.new("RGB", (1280, 720), (28, 60, 110))
        ImageDraw.Draw(im).ellipse((520, 240, 760, 480), fill=(240, 200, 60))
        im.save(caminho)
    return caminho


# ------------------------------------------------------------------ a thread dona do navegador
_REG = threading.Lock()
_SESSAO: Optional["_Sessao"] = None


class _Sessao(threading.Thread):
    def __init__(self):
        super().__init__(name="flow-estudio", daemon=True)
        self.fila: "queue.Queue" = queue.Queue()
        self.p = None
        self.context = None
        self.fechar_ctx = False
        self.page = None
        self.visivel: Optional[bool] = None
        self.conta: Optional[str] = None
        self.com_lock = False
        self.cfg_projeto: Optional[tuple] = None

    # -- laço
    def run(self) -> None:
        global _SESSAO
        try:
            while True:
                try:
                    cmd = self.fila.get(timeout=OCIOSO_S if self.context is not None else 20)
                except queue.Empty:
                    self._fechar()
                    with _REG:
                        if self.fila.empty():
                            if _SESSAO is self:
                                _SESSAO = None
                            return
                    continue
                tipo, cfg, opcoes = cmd
                if tipo == "fechar":
                    self._fechar()
                    continue
                self._executar(tipo, cfg, opcoes)
        finally:
            self._fechar()
            with _REG:
                if _SESSAO is self:
                    _SESSAO = None

    # -- navegador
    def _fechar_pagina(self) -> None:
        if self.page is not None:
            try:
                self.page.close()
            except Exception:  # noqa: BLE001
                pass
        self.page = None
        _SESSAO_INFO["projeto"] = None

    def _fechar(self) -> None:
        from googleflow import googleflow_client as gf
        self._fechar_pagina()
        if self.context is not None:
            try:
                gf.salvar_sessao(self.context, self.conta)
            except Exception:  # noqa: BLE001
                pass
            if self.fechar_ctx:
                try:
                    self.context.close()
                except Exception:  # noqa: BLE001
                    pass
        self.context = None
        if self.p is not None:
            try:
                self.p.stop()
            except Exception:  # noqa: BLE001
                pass
        self.p = None
        if self.com_lock:
            self.com_lock = False
            gf._FLOW_LOCK.release()
        _SESSAO_INFO.update(aberto=False, visivel=None, conta=None, projeto=None)

    def _garantir_navegador(self, cfg: Dict[str, Any], visivel: bool, conta: str) -> None:
        from googleflow import googleflow_client as gf
        if self.context is not None and (self.visivel != visivel or self.conta != conta):
            self._fechar()  # mudou "mostrar o navegador" ou a conta: reabre
        if self.context is not None:
            return
        if gf._FLOW_LOCK.locked():
            gf.encerrar_sessao(timeout=ESPERA_LOCK_S)  # a sessão de geração do site termina o que tem na fila e fecha
        if not gf._FLOW_LOCK.acquire(timeout=ESPERA_LOCK_S):
            raise RuntimeError("O site está usando o Google Flow agora (gerando um vídeo?). Espere terminar e tente de novo.")
        self.com_lock = True
        try:
            from playwright.sync_api import sync_playwright
            self.p = sync_playwright().start()
            self.context, self.fechar_ctx = gf._abrir(self.p, cfg, headless=not visivel, conta=conta)
            if self.fechar_ctx:
                gf.restaurar_sessao(self.context, conta)
        except BaseException:
            self._fechar()
            raise
        self.visivel, self.conta = visivel, conta
        _SESSAO_INFO.update(aberto=True, visivel=visivel, conta=conta)

    def _garantir_projeto(self, cfg: Dict[str, Any], novo: bool, on_passo, atual: Dict[str, Any]) -> None:
        from googleflow import flow_direto as fd
        from googleflow import googleflow_client as gf
        chave_cfg = gf._config_do_projeto(cfg)
        if self.page is not None:
            try:
                fechada = self.page.is_closed()
            except Exception:  # noqa: BLE001
                fechada = True
            if novo or fechada or self.cfg_projeto != chave_cfg:
                self._fechar_pagina()
        if self.page is not None:
            atual["page"] = self.page
            on_passo("projeto", "ok", "o mesmo projeto do Flow (navegador já aberto)")
            return
        page = fd.abrir_flow(self.context, gf.FLOW_URL, headless=not self.visivel, on_passo=on_passo)
        atual["page"] = page
        page = fd.novo_projeto(page, self.context, on_passo)
        atual["page"] = page
        self.page = page
        _SESSAO_INFO["projeto"] = page.url
        gf.salvar_sessao(self.context, self.conta)
        fd.configurar_agente(page, on_passo=on_passo, **gf.agente_da_cfg(cfg))
        fd.desligar_agente(page, on_passo)
        self.cfg_projeto = chave_cfg

    # -- baixar
    def _baixar(self, midias: List[Dict[str, str]], trab: Dict[str, Any], origem: str, rotulo: str, on_passo) -> None:
        from googleflow import googleflow_client as gf
        for k, m in enumerate(midias):
            passo = f"baixar_{rotulo}" + (f"_{k + 1}" if len(midias) > 1 else "")
            try:
                if m["url"].startswith("blob:"):
                    raise RuntimeError("o Flow deu um link blob: (não dá pra baixar por fora)")
                resp = None
                for u in ([gf._url_original(m["url"]), m["url"]] if m["tipo"] == "imagem" else [m["url"]]):
                    resp = self.context.request.get(u)
                    if resp.ok:
                        break
                if resp is None or not resp.ok:
                    raise RuntimeError(f"HTTP {resp.status if resp is not None else '?'}")
                tipo_ct = resp.headers.get("content-type", "")
                ext = "mp4" if m["tipo"] == "video" else ("jpg" if "jpeg" in tipo_ct else "webp" if "webp" in tipo_ct else "png")
                gid = time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)
                nome = f"{gid}.{ext}"
                with open(os.path.join(pasta_galeria(), nome), "wb") as f:
                    f.write(resp.body())
                e = {"id": gid, "tipo": m["tipo"], "arquivo": nome, "media_id": m.get("id") or "", "prompt": trab.get("prompt") or "",
                     "modelo": trab.get("modelo") or "", "proporcao": trab.get("proporcao") or "", "origem": origem,
                     "frames": bool(trab.get("inicio") or trab.get("fim")), "referencia": bool(trab.get("referencia")),
                     "conta": self.conta, "projeto": _SESSAO_INFO.get("projeto"), "criado": time.time(), "rotulo": rotulo}
                adicionar_na_galeria(e)
                _ESTADO["resultados"].append(e)
                on_passo(passo, "ok", nome)
            except _Parado:
                raise
            except Exception as exc:  # noqa: BLE001
                on_passo(passo, "erro", f"não baixou: {exc}")

    # -- um comando
    def _executar(self, tipo: str, cfg: Dict[str, Any], opcoes: Dict[str, Any]) -> None:
        from googleflow import flow_direto as fd
        from googleflow import googleflow_client as gf
        est = _ESTADO
        atual: Dict[str, Any] = {"page": None}
        on_passo = _novo_passo_cb(gf, est, atual)
        timeout = int(cfg.get("flow_timeout_seconds") or 300)
        simular = bool(opcoes.get("simular"))
        try:
            self._garantir_navegador(cfg, bool(opcoes.get("visivel")), opcoes.get("conta") or gf.CONTA_PADRAO)
            self._garantir_projeto(cfg, tipo == "teste" or bool(opcoes.get("novo_projeto")), on_passo, atual)
            page = self.page
            if tipo == "teste":
                t_img = {"tipo": "imagem", "prompt": PROMPT_IMAGEM, "proporcao": "16:9",
                         "modelo": cfg.get("flow_modelo_imagem") or "", "simular": simular}
                img = fd.gerar_um(page, t_img, on_passo, timeout)
                self._baixar(img[:1], t_img, "teste", "foto", on_passo)
                t_vid = {"tipo": "video", "tipo_video": "Elementos", "prompt": PROMPT_VIDEO, "proporcao": "16:9",
                         "modelo": cfg.get("flow_modelo_video") or "", "simular": simular}
                vid = fd.gerar_um(page, t_vid, on_passo, timeout)
                self._baixar(vid[:1], t_vid, "teste", "video_texto", on_passo)
                inicio = {"media_id": img[0]["id"], "arquivo": opcoes["imagem_teste"]} if img else {"arquivo": opcoes["imagem_teste"]}
                t_fr = {"tipo": "video", "tipo_video": "Frames", "prompt": PROMPT_ANIMAR, "proporcao": "16:9",
                        "modelo": cfg.get("flow_modelo_video") or "", "inicio": inicio,
                        "fim": {"arquivo": opcoes["imagem_teste"]}, "simular": simular}
                fr = fd.gerar_um(page, t_fr, on_passo, timeout)
                self._baixar(fr[:1], t_fr, "teste", "video_frames", on_passo)
                if not simular:
                    ok = {r["rotulo"] for r in est["resultados"]}
                    faltou = [n for n in ("foto", "video_texto", "video_frames") if n not in ok]
                    if faltou:
                        est["erro"] = "Gerou, mas não consegui baixar: " + ", ".join(faltou) + " (veja os passos ❌)."
            else:
                trab: Dict[str, Any] = {"tipo": opcoes["tipo"], "prompt": opcoes["prompt"], "proporcao": opcoes["proporcao"],
                                        "modelo": opcoes["modelo"] or str(cfg.get("flow_modelo_" + opcoes["tipo"]) or ""),
                                        "quantidade": opcoes["quantidade"], "simular": simular}
                for k in ("inicio", "fim", "referencia"):
                    if opcoes.get(k):
                        trab[k] = opcoes[k]
                if trab["tipo"] == "video":
                    trab["tipo_video"] = "Frames" if (trab.get("inicio") or trab.get("fim")) else "Elementos"
                r = fd.gerar_um(page, trab, on_passo, timeout)
                self._baixar(r, trab, "gerar", "resultado", on_passo)
        except _Parado:
            est["erro"] = "Parado por você."
            self._fechar_pagina()  # o projeto pode ter ficado no meio de algo: o próximo pedido abre outro
        except fd.FlowPassoErro as exc:
            pagina_erro = getattr(exc, "page", None) or atual.get("page")  # a aba onde o passo falhou
            diag = gf.salvar_diagnostico(pagina_erro, str(exc)) if pagina_erro is not None else None
            _marcar_erro(exc.passo, exc.mensagem)
            msg = str(exc)
            if isinstance(exc, fd.FlowLimite) and self.conta:
                try:
                    gf.marcar_esgotada(self.conta, gf._horas_para_liberar(cfg))
                except Exception:  # noqa: BLE001
                    pass
                msg += f" — a conta \"{self.conta}\" ficou marcada como esgotada; escolha outra conta e rode de novo."
            est["erro"] = msg + (" — a foto e o HTML da tela foram guardados: use os botões abaixo pra baixar ou copiar e mandar." if diag else "")
            est["diagnostico"] = os.path.basename(diag) if diag else None
            self._fechar_pagina()
        except Exception as exc:  # noqa: BLE001
            est["erro"] = f"{type(exc).__name__}: {exc}"
            est["detalhe_erro"] = traceback.format_exc()[-2500:]
            self._fechar_pagina()
        finally:
            est["rodando"], est["fim"] = False, time.time()
            _SESSAO_INFO["ultimo_uso"] = time.time()


def _enviar(tipo: str, cfg: Dict[str, Any], opcoes: Dict[str, Any]) -> None:
    global _SESSAO
    with _REG:
        if _SESSAO is None or not _SESSAO.is_alive():
            _SESSAO = _Sessao()
            _SESSAO.start()
        _SESSAO.fila.put((tipo, cfg, opcoes))


def fechar_navegador() -> None:
    with _REG:
        s = _SESSAO
    if s is not None and s.is_alive():
        s.fila.put(("fechar", {}, {}))


# ------------------------------------------------------------------ rotas
def _salvar_entrada(gf, campo: str) -> Optional[Dict[str, str]]:
    """Arquivo enviado no formulário OU um item da 🖼 galeria (`<campo>_galeria` = id) → {"arquivo", "media_id"}."""
    gid = (request.form.get(campo + "_galeria") or "").strip()
    if gid:
        e = item_da_galeria(gid)
        if not e or e.get("tipo") != "imagem":
            raise ValueError(f"{campo}: essa imagem não está mais na galeria.")
        caminho = os.path.join(pasta_galeria(), e["arquivo"])
        if not os.path.exists(caminho):
            raise ValueError(f"{campo}: o arquivo dessa imagem sumiu da galeria.")
        mid = e.get("media_id") or ""
        return {"arquivo": caminho, "media_id": mid if e.get("projeto") and e.get("projeto") == _SESSAO_INFO.get("projeto") else ""}
    arq = request.files.get(campo)
    if not arq or not arq.filename:
        return None
    ext = os.path.splitext(arq.filename)[1].lower()
    if ext not in EXT_IMAGEM:
        raise ValueError(f"{campo}: só imagem (.png, .jpg, .webp).")
    entrada = os.path.join(str(gf.pasta_dados()), "teste_entrada")
    os.makedirs(entrada, exist_ok=True)
    caminho = os.path.abspath(os.path.join(entrada, f"{campo}_{secrets.token_hex(3)}{ext}"))
    arq.save(caminho)
    return {"arquivo": caminho}


def registrar(app, base_dir: str) -> None:
    _BASE["dir"] = base_dir

    @app.route("/flow")
    def flow_page():
        from googleflow import flow_direto as fd
        from googleflow import googleflow_client as gf
        from site_config import load_site_config
        cfg = load_site_config()
        return render_template("flow_estudio.html", contas=[c["nome"] for c in gf.listar_contas()], cfg=cfg,
                               modelos_imagem=fd.MODELOS_IMAGEM, modelos_video=fd.MODELOS_VIDEO, proporcoes=fd.PROPORCOES,
                               modo_direto=gf.modo_direto(cfg), ocioso_min=OCIOSO_S // 60)

    @app.route("/flow/teste")
    def flow_teste_page():  # o link antigo (v84_74) cai na aba nova
        return redirect(url_for("flow_page") + "#teste")

    @app.route("/flow/iniciar", methods=["POST"])
    def flow_iniciar():
        from googleflow import flow_direto as fd
        from googleflow import googleflow_client as gf
        from site_config import load_site_config
        f = request.form
        with _TRAVA:
            if _ESTADO["rodando"]:
                return jsonify({"erro": "Já tem algo rodando no Flow — espere ou clique em Parar."}), 409
            modo = "teste" if f.get("modo") == "teste" else "gerar"
            opcoes: Dict[str, Any] = {
                "modo": modo, "visivel": f.get("visivel") == "on", "simular": f.get("simular") == "on",
                "conta": (f.get("conta") or "").strip(), "novo_projeto": f.get("novo_projeto") == "on",
                "tipo": f.get("tipo") if f.get("tipo") in ("imagem", "video") else "imagem",
                "prompt": " ".join((f.get("prompt") or "").split())[:4000],
                "modelo": (f.get("modelo") or "").strip()[:60],
                "proporcao": f.get("proporcao") if f.get("proporcao") in fd.PROPORCOES else "16:9",
                "quantidade": f.get("quantidade") if f.get("quantidade") in ("x1", "x2", "x3", "x4") else "x1",
            }
            if modo == "teste":
                opcoes["visivel"] = f.get("visivel", "on") == "on"  # o teste abre o navegador pra você ver (padrão)
                opcoes["imagem_teste"] = _imagem_teste(gf)
            else:
                if not opcoes["prompt"]:
                    return jsonify({"erro": "Escreva o prompt."}), 400
                opcoes["simular"] = False
                try:
                    for k in ("inicio", "fim", "referencia"):
                        v = _salvar_entrada(gf, k)
                        if v:
                            opcoes[k] = v
                except ValueError as exc:
                    return jsonify({"erro": str(exc)}), 400
                if opcoes.get("inicio") or opcoes.get("fim"):
                    opcoes["tipo"] = "video"
                    opcoes.pop("referencia", None)
                elif opcoes["tipo"] == "video":
                    opcoes.pop("referencia", None)
            dest = pasta_passos(gf)
            for n in os.listdir(dest):  # as fotos dos passos da vez anterior saem
                try:
                    os.remove(os.path.join(dest, n))
                except OSError:
                    pass
            _ESTADO.update(rodando=True, passos=[], resultados=[], erro=None, inicio=time.time(), fim=None, modo=modo,
                           parar=False, diagnostico=None, detalhe_erro=None,
                           opcoes={k: (v if not isinstance(v, dict) else True) for k, v in opcoes.items() if k != "imagem_teste"})
            _enviar("teste" if modo == "teste" else "gerar", load_site_config(), opcoes)
        return jsonify({"ok": True})

    @app.route("/flow/status")
    def flow_status():
        e = {k: v for k, v in _ESTADO.items() if k != "parar"}
        e["passos"] = [{k: v for k, v in p.items() if not k.startswith("_")} for p in _ESTADO["passos"]]
        e["sessao"] = dict(_SESSAO_INFO)
        return jsonify(e)

    @app.route("/flow/parar", methods=["POST"])
    def flow_parar():
        if _ESTADO["rodando"]:
            _ESTADO["parar"] = True
        return jsonify({"ok": True})

    @app.route("/flow/fechar", methods=["POST"])
    def flow_fechar():
        if _ESTADO["rodando"]:
            return jsonify({"erro": "Está rodando — clique em Parar antes."}), 409
        fechar_navegador()
        return jsonify({"ok": True})

    @app.route("/flow/galeria")
    def flow_galeria():
        try:
            pagina = max(0, int(request.args.get("pagina") or 0))
        except ValueError:
            pagina = 0
        q = (request.args.get("q") or "").strip().lower()
        tipo = request.args.get("tipo") or ""
        itens = [e for e in galeria() if (not q or q in (e.get("prompt") or "").lower()) and (not tipo or e.get("tipo") == tipo)]
        return jsonify({"total": len(itens), "itens": itens[pagina * 60:(pagina + 1) * 60]})

    @app.route("/flow/galeria/<gid>/apagar", methods=["POST"])
    def flow_galeria_apagar(gid: str):
        if not apagar_da_galeria(gid):
            return jsonify({"erro": "Não achei esse item na galeria."}), 404
        return jsonify({"ok": True})

    @app.route("/flow/arquivo/<nome>")
    def flow_arquivo(nome: str):
        if not re.fullmatch(r"[\w.\-]+", nome) or nome.endswith(".json"):
            return "nome inválido", 400
        return send_from_directory(pasta_galeria(), nome, as_attachment=request.args.get("baixar") == "1")

    @app.route("/flow/diagnosticos")
    def flow_diagnosticos():
        from googleflow import googleflow_client as gf
        pasta = gf.pasta_dados() / "diagnostico"
        itens = []
        if pasta.is_dir():
            for t in sorted(pasta.glob("*.txt"), reverse=True):
                if t.name.endswith("_html.txt") or not _RE_DIAG.fullmatch(t.stem):
                    continue
                try:
                    motivo = t.read_text(encoding="utf-8").split("\n", 1)[0][:300]
                except OSError:
                    motivo = ""
                itens.append({"id": t.stem, "motivo": motivo, "quando": t.stat().st_mtime,
                              "foto": (pasta / (t.stem + ".png")).exists()})
                if len(itens) >= 20:
                    break
        return jsonify({"itens": itens})

    @app.route("/flow/diagnostico/<diag>/<oque>")
    def flow_diagnostico(diag: str, oque: str):
        """🩺 Diagnóstico de um erro: `zip` (foto + textos + HTML), `html` (texto pra copiar) ou `foto`."""
        import io
        import zipfile
        from flask import send_file
        from googleflow import googleflow_client as gf
        if not _RE_DIAG.fullmatch(diag):
            return "diagnóstico inválido", 400
        arqs = gf.arquivos_do_diagnostico(diag)
        if not arqs:
            return "Esse diagnóstico não existe mais (só os 20 últimos ficam guardados).", 404
        por_fim = {a.name[len(diag):]: a for a in arqs}
        if oque == "foto" and ".png" in por_fim:
            return send_file(str(por_fim[".png"]), mimetype="image/png")
        if oque == "html":
            alvo = por_fim.get("_html.txt") or por_fim.get(".txt")
            txt = alvo.read_text(encoding="utf-8") if alvo else ""
            if len(txt) < 4000 and "_pagina.html" in por_fim:  # a parte importante veio quase vazia: vai a página inteira
                pagina = por_fim["_pagina.html"].read_text(encoding="utf-8")
                txt += "\n\n<!-- ===== PÁGINA INTEIRA (sem scripts/estilos) ===== -->\n" + pagina[:400_000]
            return txt, 200, {"Content-Type": "text/plain; charset=utf-8"}
        if oque == "zip":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for fim, a in por_fim.items():
                    z.write(str(a), arcname="diagnostico_flow_" + diag + fim)
            buf.seek(0)
            return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=f"diagnostico_flow_{diag}.zip")
        return "não achei", 404

    @app.route("/flow/passo/<nome>")
    def flow_passo_foto(nome: str):
        from googleflow import googleflow_client as gf
        if not re.fullmatch(r"passo_\d+\.jpg", nome):
            return "nome inválido", 400
        return send_from_directory(pasta_passos(gf), nome)
