"""
Chat local + API para pesquisar pelo Modo IA do Google.

    pip install -r requirements.txt
    playwright install chromium
    python app.py            -> abre http://127.0.0.1:5000

API:
    POST /api/pesquisar      {"pergunta": "...", "nova_conversa": false}
    GET  /api/pesquisar?q=...&nova=1
    POST /api/nova           começa conversa nova
    GET  /api/conversas      histórico salvo
    GET  /api/conversas/<id> uma conversa completa
    GET  /api/status         navegador aberto/ocupado + etapa atual + último erro
    GET  /api/config         configurações
    POST /api/config         altera configurações  {"navegador_visivel": false, ...}
    POST /api/navegador/testar    abre o Google e diz se está tudo ok
    POST /api/navegador/reiniciar fecha e reabre o navegador
    POST /api/navegador/fechar    fecha o navegador
    GET  /api/logs           últimos eventos (para achar erros)
"""
import json
import re
import os
import queue
import threading
import time
import traceback
import uuid
from collections import deque
from concurrent.futures import Future
from pathlib import Path

from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory

from ia_google import ErroIA, GoogleIA, classificar_erro
from youtube import AnalisadorYouTube, TAREFAS as TAREFAS_VIDEO, id_do_video
from imagens import BuscadorImagens, baixar_bytes, nome_arquivo, zip_imagens

BASE = Path(__file__).resolve().parent
CONVERSAS_DIR = BASE / "conversas"
ERROS_DIR = BASE / "erros"
DEBUG_DIR = BASE / "debug"
VIDEOS_DIR = BASE / "videos"
CONFIG_PATH = BASE / "config.json"
CONVERSAS_DIR.mkdir(exist_ok=True)
ERROS_DIR.mkdir(exist_ok=True)
DEBUG_DIR.mkdir(exist_ok=True)
VIDEOS_DIR.mkdir(exist_ok=True)

# ---------------- configurações ----------------
CONFIG_PADRAO = {
    "navegador_visivel": True,     # False = headless (invisível)
    "timeout_resposta": 120,       # segundos esperando a IA responder
    "espera_captcha": 0,           # segundos esperando você resolver um captcha (0 = sem limite, fica monitorando)
    "max_perguntas_conversa": 25,  # perguntas na mesma conversa do Google antes de abrir outra (0 = sem limite)
    "resolver_links": True,        # segue os links /goto do Google para achar a URL real
    "usar_instrucao": True,        # envia a instrução de formato junto com a pergunta
    "salvar_print_erro": True,     # salva print + HTML da página quando dá erro
    "salvar_html_respostas": True, # salva o HTML de cada resposta em debug/ (para ajustar o extrator)
    "fechar_ocioso_min": 0,        # fecha o navegador após X min sem uso (0 = nunca)
}


def carregar_config():
    cfg = dict(CONFIG_PADRAO)
    if os.environ.get("IA_HEADLESS") == "1":
        cfg["navegador_visivel"] = False
    try:
        cfg.update({k: v for k, v in json.loads(CONFIG_PATH.read_text(encoding="utf-8")).items()
                    if k in CONFIG_PADRAO})
    except Exception:
        pass
    return cfg


def validar_config(novo):
    erros, limpo = [], {}
    for k, v in novo.items():
        if k not in CONFIG_PADRAO:
            erros.append(f"opção desconhecida: {k}")
            continue
        padrao = CONFIG_PADRAO[k]
        if isinstance(padrao, bool):
            if not isinstance(v, bool):
                erros.append(f"{k} deve ser true/false")
                continue
        elif isinstance(padrao, int):
            try:
                v = int(v)
            except (TypeError, ValueError):
                erros.append(f"{k} deve ser um número")
                continue
            minimo = {"timeout_resposta": 20}.get(k, 0)
            if v < minimo or v > 3600:
                erros.append(f"{k} deve estar entre {minimo} e 3600")
                continue
        limpo[k] = v
    return limpo, erros


config = carregar_config()

# ---------------- logs ----------------
LOGS = deque(maxlen=300)
_log_id = 0
_log_lock = threading.Lock()
estado = {"etapa": "", "ultimo_erro": None}


def log(msg, nivel="info"):
    global _log_id
    with _log_lock:
        _log_id += 1
        LOGS.append({"id": _log_id, "hora": time.strftime("%H:%M:%S"), "nivel": nivel, "msg": msg})
    if nivel != "debug":
        estado["etapa"] = msg
    print(f"[{time.strftime('%H:%M:%S')}] [{nivel}] {msg}", flush=True)


# ---------------- navegador (uma thread dona do Playwright) ----------------
class Navegador:
    """O Playwright (sync) só pode ser usado pela thread que o criou.
    Uma thread fica dona do navegador e processa uma fila de tarefas."""

    def __init__(self):
        self.fila = queue.Queue()
        self.ocupado = False
        self.ia = None
        self.ultimo_uso = time.time()
        self._thread = None
        self._lock = threading.Lock()

    @property
    def aberto(self):
        return self.ia is not None and self.ia.esta_aberto()

    def _garantir_thread(self):
        with self._lock:
            if not self._thread or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, daemon=True)
                self._thread.start()

    def _criar_ia(self):
        ia = GoogleIA(headless=not config["navegador_visivel"],
                      resolver_links=config["resolver_links"],
                      timeout_resposta=config["timeout_resposta"],
                      espera_captcha=config["espera_captcha"],
                      max_perguntas_conversa=config["max_perguntas_conversa"],
                      interativo=False, log=log)
        ia.abrir()
        return ia

    def garantir_aberto(self):
        """(roda na thread do navegador) abre/reabre se preciso e aplica a config."""
        if self.ia is not None and (not self.ia.esta_aberto()
                                    or self.ia.headless == config["navegador_visivel"]):
            log("Reabrindo o navegador…")
            self.fechar_ia()
        if self.ia is None:
            self.ia = self._criar_ia()
        self.ia.resolver_links = config["resolver_links"]
        self.ia.timeout_resposta = config["timeout_resposta"]
        self.ia.espera_captcha = config["espera_captcha"]
        self.ia.max_perguntas_conversa = config["max_perguntas_conversa"]
        return self.ia

    def fechar_ia(self):
        if self.ia is not None:
            try:
                self.ia.fechar()
            finally:
                self.ia = None
                log("Navegador fechado.")

    def _loop(self):
        while True:
            try:
                fn, args, fut = self.fila.get(timeout=30)
            except queue.Empty:
                minutos = config.get("fechar_ocioso_min", 0)
                if minutos and self.ia and time.time() - self.ultimo_uso > minutos * 60:
                    log(f"Fechando navegador após {minutos} min sem uso.")
                    self.fechar_ia()
                continue
            if fn is None:
                break
            self.ocupado = True
            try:
                fut.set_result(fn(self, *args))
            except Exception as e:
                fut.set_exception(e)
            finally:
                self.ocupado = False
                self.ultimo_uso = time.time()
        self.fechar_ia()

    def executar(self, fn, *args, timeout=None):
        self._garantir_thread()
        fut = Future()
        self.fila.put((fn, args, fut))
        espera = timeout or (config["timeout_resposta"] + config["espera_captcha"] + 120)
        return fut.result(timeout=espera)

    def parar(self):
        if self._thread and self._thread.is_alive():
            self.fila.put((None, None, None))


nav = Navegador()


def registrar_erro(e, nav_obj=None, contexto=""):
    """Converte o erro em algo legível, salva print/HTML e guarda como último erro."""
    erro = classificar_erro(e)
    info = erro.to_dict()
    info["quando"] = time.strftime("%Y-%m-%d %H:%M:%S")
    info["contexto"] = contexto
    info["traceback"] = "".join(traceback.format_exception(type(e), e, e.__traceback__))[-4000:]
    if config["salvar_print_erro"] and nav_obj and nav_obj.ia and nav_obj.ia.esta_aberto():
        nome = time.strftime("%Y%m%d-%H%M%S") + "_" + erro.codigo.lower()
        arquivos = nav_obj.ia.salvar_print(ERROS_DIR / nome)
        info["print"] = f"/erros/{Path(arquivos['print']).name}" if "print" in arquivos else None
        info["html"] = f"/erros/{Path(arquivos['html']).name}" if "html" in arquivos else None
    log(f"ERRO [{erro.codigo}] {erro.mensagem}", "erro")
    if erro.dica:
        log(f"Dica: {erro.dica}", "aviso")
    estado["ultimo_erro"] = info
    return info


# ---------------- tarefas (rodam na thread do navegador) ----------------
def tarefa_perguntar(n, pergunta, nova, usar_instrucao):
    try:
        ia = n.garantir_aberto()
        if nova or getattr(n, "modo", "chat") != "chat":
            ia.nova_conversa()   # depois de analisar vídeo, o chat volta para uma conversa própria
        n.modo = "chat"
        log(f"Pergunta: {pergunta[:120]}")
        r = ia.perguntar(pergunta, usar_instrucao=usar_instrucao)
        if config.get("salvar_html_respostas"):
            nome = time.strftime("%Y%m%d-%H%M%S")
            arqs = ia.salvar_print(DEBUG_DIR / nome)
            r["debug"] = {k: f"/debug/{Path(v).name}" for k, v in arqs.items()}
        log(f"Pronto: {len(r['fontes'])} fontes, formato {'ok' if r['formato_respeitado'] else 'NÃO respeitado'}.", "ok")
        estado["ultimo_erro"] = None
        return r
    except Exception as e:
        info = registrar_erro(e, n, contexto=f"pergunta: {pergunta[:200]}")
        if n.ia:
            n.ia.nova_conversa()  # próxima pergunta começa limpa
        raise ErroComInfo(info)


def tarefa_video(n, url, tarefa, consulta, nova, errados=None):
    try:
        ia = n.garantir_aberto()
        if getattr(n, "yt", None) is None or n.yt.ia is not ia:
            n.yt = AnalisadorYouTube(ia)
        if getattr(n, "modo", "chat") != "video":
            n.yt.video_atual = None  # vinha do chat: começa conversa nova para o vídeo
        n.modo = "video"
        r = n.yt.executar(url, tarefa, consulta, nova_conversa=True if nova else None, errados=errados)
        if config.get("salvar_html_respostas"):
            nome = time.strftime("%Y%m%d-%H%M%S") + f"_video_{tarefa}"
            arqs = ia.salvar_print(DEBUG_DIR / nome)
            r["debug"] = {k: f"/debug/{Path(v).name}" for k, v in arqs.items()}
        (VIDEOS_DIR / f"{r['video']['id']}_{time.strftime('%Y%m%d-%H%M%S')}_{tarefa}.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"Vídeo pronto: {TAREFAS_VIDEO[tarefa]['nome']}" + ("" if r["formato_respeitado"] else " (sem JSON)"), "ok")
        estado["ultimo_erro"] = None
        return r
    except ValueError:
        raise
    except Exception as e:
        info = registrar_erro(e, n, contexto=f"vídeo {url} / {tarefa}: {consulta[:150]}")
        if n.ia:
            n.ia.nova_conversa()
        if getattr(n, "yt", None):
            n.yt.video_atual = None
        raise ErroComInfo(info)


def tarefa_imagens(n, termo, quantidade, verificar, min_lado, relacionadas=False):
    try:
        ia = n.garantir_aberto()
        n.modo = "imagens"
        r = BuscadorImagens(ia).buscar(termo, quantidade=quantidade, verificar=verificar, min_lado=min_lado,
                                       relacionadas=relacionadas)
        if config.get("salvar_html_respostas"):
            arqs = ia.salvar_print(DEBUG_DIR / (time.strftime("%Y%m%d-%H%M%S") + "_imagens"))
            r["debug"] = {k: f"/debug/{Path(v).name}" for k, v in arqs.items()}
        log(f"Imagens: {r['total']} encontradas para '{termo}'.", "ok")
        estado["ultimo_erro"] = None
        return r
    except ValueError:
        raise
    except Exception as e:
        info = registrar_erro(e, n, contexto=f"imagens: {termo}")
        if n.ia:
            n.ia.nova_conversa()
        raise ErroComInfo(info)


def tarefa_imagens_mais(n, quantidade, ja_vistas, min_lado, verificar):
    """Continua explorando as relacionadas do painel lateral na página da última busca."""
    from imagens import verificar_imagem
    import concurrent.futures as cf
    try:
        if getattr(n, "modo", "") != "imagens" or not n.ia or not n.ia.esta_aberto():
            raise ErroIA("SEM_BUSCA", "Não há uma busca de imagens aberta no navegador.",
                         "Faça uma busca de imagens primeiro e depois clique em “Mais imagens”.")
        novas = BuscadorImagens(n.ia).explorar_relacionadas(quantidade, ja_vistas=set(ja_vistas), min_lado=min_lado)
        if verificar and novas:
            with cf.ThreadPoolExecutor(8) as ex:
                novas = list(ex.map(verificar_imagem, novas))
        log(f"Mais imagens: {len(novas)} novas das relacionadas.", "ok")
        return {"imagens": novas, "total": len(novas),
                "aviso": None if novas else "Não encontrei mais imagens novas nas relacionadas."}
    except Exception as e:
        raise ErroComInfo(registrar_erro(e, n, contexto="mais imagens"))


def tarefa_testar(n):
    passos = []
    inicio = time.time()
    try:
        ia = n.garantir_aberto()
        passos.append({"ok": True, "passo": f"Navegador aberto ({'visível' if not ia.headless else 'invisível'})"})
        ia.page.goto("https://www.google.com/?hl=pt-BR", wait_until="domcontentloaded", timeout=30000)
        passos.append({"ok": True, "passo": "google.com carregou"})
        if ia._tem_captcha():
            passos.append({"ok": False, "passo": "O Google está pedindo captcha",
                           "dica": "Deixe o navegador visível e resolva o captcha na janela."})
        else:
            passos.append({"ok": True, "passo": "Sem captcha"})
        tem_botao = ia.page.locator("button.plR5qb").filter(has_text="Modo IA").count() > 0
        passos.append({"ok": tem_botao, "passo": "Botão \"Modo IA\" encontrado" if tem_botao
                       else "Botão \"Modo IA\" não encontrado (o script usa a URL direta como alternativa)",
                       "aviso": not tem_botao})
        ia.em_conversa = False
        ok = all(p["ok"] or p.get("aviso") for p in passos)
        log("Teste do navegador: " + ("tudo certo" if ok else "com problemas"), "ok" if ok else "aviso")
        return {"ok": ok, "passos": passos, "tempo_segundos": round(time.time() - inicio, 1)}
    except Exception as e:
        info = registrar_erro(e, n, contexto="teste do navegador")
        passos.append({"ok": False, "passo": info["mensagem"], "dica": info["dica"]})
        return {"ok": False, "passos": passos, "erro": info, "tempo_segundos": round(time.time() - inicio, 1)}


def tarefa_reiniciar(n):
    n.fechar_ia()
    n.garantir_aberto()
    return True


def tarefa_fechar(n):
    n.fechar_ia()
    return True


class ErroComInfo(Exception):
    def __init__(self, info):
        super().__init__(info["mensagem"])
        self.info = info


# ---------------- conversas ----------------
class Conversas:
    def __init__(self):
        self.atual = None
        self._lock = threading.Lock()

    def nova(self):
        with self._lock:
            self.atual = {"id": time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4],
                          "criada": time.strftime("%Y-%m-%dT%H:%M:%S"), "titulo": "", "mensagens": []}
            return self.atual

    def adicionar(self, resultado):
        with self._lock:
            if self.atual is None:
                self.nova()
            if not self.atual["titulo"]:
                self.atual["titulo"] = resultado["pergunta"][:80]
            self.atual["mensagens"].append(resultado)
            (CONVERSAS_DIR / f"{self.atual['id']}.json").write_text(
                json.dumps(self.atual, ensure_ascii=False, indent=2), encoding="utf-8")
            return self.atual["id"]

    @staticmethod
    def listar():
        itens = []
        for p in sorted(CONVERSAS_DIR.glob("*.json"), reverse=True):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                itens.append({"id": d["id"], "titulo": d.get("titulo") or "(sem título)",
                              "criada": d.get("criada"), "mensagens": len(d.get("mensagens", []))})
            except Exception:
                continue
        return itens

    @staticmethod
    def carregar(cid):
        p = CONVERSAS_DIR / f"{Path(cid).name}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


conversas = Conversas()

app = Flask(__name__)
app.json.ensure_ascii = False
app.json.sort_keys = False


def resposta_erro(info, status=500):
    return jsonify({"erro": info["mensagem"], "detalhes_erro": info}), status


# ---------------- rotas ----------------
@app.get("/")
def index():
    return render_template("index.html")


@app.route("/api/pesquisar", methods=["GET", "POST"])
def api_pesquisar():
    dados = request.get_json(silent=True) or {}
    pergunta = (dados.get("pergunta") or request.args.get("q") or "").strip()
    if not pergunta:
        return jsonify({"erro": "envie {'pergunta': '...'} ou ?q=..."}), 400

    nova = dados.get("nova_conversa")
    if nova is None:
        nova = request.args.get("nova", "0") in ("1", "true", "sim")
    nova = bool(nova) or conversas.atual is None or not conversas.atual["mensagens"]
    usar_instrucao = dados.get("usar_instrucao", config["usar_instrucao"])

    if nova:
        conversas.nova()
    inicio = time.time()
    try:
        r = nav.executar(tarefa_perguntar, pergunta, nova, usar_instrucao)
    except ErroComInfo as e:
        return resposta_erro(e.info)
    except Exception as e:  # ex.: timeout da fila
        return resposta_erro(registrar_erro(e, None, contexto="servidor"))

    r["tempo_segundos"] = round(time.time() - inicio, 1)
    cid = conversas.adicionar(r)
    saida = {"conversa_id": cid, **r}
    if not dados.get("incluir_bruto") and request.args.get("bruto") != "1":
        saida.pop("resposta_bruta_md", None)
    return jsonify(saida)


@app.get("/api/video/tarefas")
def api_video_tarefas():
    return jsonify(AnalisadorYouTube.tarefas())


@app.route("/api/video", methods=["GET", "POST"])
def api_video():
    """POST {"url": "...", "tarefa": "resumo|pergunta|momentos|...", "consulta": "...", "nova_conversa": false,
             "errados": [{"inicio": "1:05", "fim": "1:20"}]}   ← 🔁 olhar de novo (na mesma conversa)"""
    d = request.get_json(silent=True) or {}
    url = (d.get("url") or request.args.get("url") or "").strip()
    tarefa = (d.get("tarefa") or request.args.get("tarefa") or "resumo").strip()
    consulta = (d.get("consulta") or request.args.get("q") or "").strip()
    if not id_do_video(url):
        return jsonify({"erro": "Envie um link válido do YouTube em 'url'."}), 400
    if tarefa not in TAREFAS_VIDEO:
        return jsonify({"erro": f"Tarefa inválida. Opções: {', '.join(TAREFAS_VIDEO)}"}), 400
    inicio = time.time()
    try:
        errados = d.get("errados") if isinstance(d.get("errados"), list) else None
        r = nav.executar(tarefa_video, url, tarefa, consulta, bool(d.get("nova_conversa")) and not errados, errados)
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400
    except ErroComInfo as e:
        return resposta_erro(e.info)
    except Exception as e:
        return resposta_erro(registrar_erro(e, None, contexto="vídeo"))
    r["tempo_segundos"] = round(time.time() - inicio, 1)
    if not d.get("incluir_bruto"):
        r.pop("resposta_bruta_md", None)
    return jsonify(r)


@app.post("/api/imagens")
def api_imagens():
    """POST {"termo": "...", "quantidade": 20, "verificar": false, "min_lado": 0}"""
    d = request.get_json(silent=True) or {}
    termo = (d.get("termo") or request.args.get("q") or "").strip()
    if not termo:
        return jsonify({"erro": "Diga do que você quer imagens em 'termo'."}), 400
    try:
        qtd = max(1, min(int(d.get("quantidade", 20)), 80))
        min_lado = max(0, int(d.get("min_lado", 0)))
    except (TypeError, ValueError):
        return jsonify({"erro": "quantidade e min_lado devem ser números."}), 400
    inicio = time.time()
    try:
        r = nav.executar(tarefa_imagens, termo, qtd, bool(d.get("verificar")), min_lado, bool(d.get("relacionadas")))
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400
    except ErroComInfo as e:
        return resposta_erro(e.info)
    except Exception as e:
        return resposta_erro(registrar_erro(e, None, contexto="imagens"))
    r["tempo_segundos"] = round(time.time() - inicio, 1)
    return jsonify(r)


@app.post("/api/imagens/mais")
def api_imagens_mais():
    """POST {"quantidade": 10, "ja_vistas": ["url", ...], "min_lado": 0, "verificar": false}
    Continua explorando as imagens relacionadas (painel lateral) da última busca."""
    d = request.get_json(silent=True) or {}
    try:
        qtd = max(1, min(int(d.get("quantidade", 10)), 60))
        r = nav.executar(tarefa_imagens_mais, qtd, d.get("ja_vistas", []), int(d.get("min_lado", 0)), bool(d.get("verificar")))
    except ErroComInfo as e:
        return resposta_erro(e.info)
    except Exception as e:
        return resposta_erro(registrar_erro(e, None, contexto="mais imagens"))
    return jsonify(r)


@app.get("/api/imagens/baixar")
def api_imagem_baixar():
    """Baixa UMA imagem original pelo servidor (evita bloqueio de hotlink). ?url=...&pagina=...&titulo=..."""
    url = request.args.get("url", "")
    if not url.startswith(("http://", "https://")):
        return jsonify({"erro": "url inválida"}), 400
    im = {"imagem": url, "pagina": request.args.get("pagina", ""), "titulo": request.args.get("titulo", "")}
    try:
        dados, tipo = baixar_bytes(im)
    except Exception as e:
        return jsonify({"erro": f"Não consegui baixar: {e}"}), 502
    return Response(dados, mimetype=tipo or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{nome_arquivo(im, 1, tipo)}"'})


@app.post("/api/imagens/zip")
def api_imagens_zip():
    """POST {"imagens": [{"imagem": "...", "pagina": "...", "titulo": "..."}], "nome": "gojo"} -> arquivo .zip"""
    d = request.get_json(silent=True) or {}
    imagens = [im for im in d.get("imagens", []) if str(im.get("imagem", "")).startswith("http")][:100]
    if not imagens:
        return jsonify({"erro": "nenhuma imagem enviada"}), 400
    dados, falhas = zip_imagens(imagens)
    nome = re.sub(r"[^\w\-]+", "_", d.get("nome") or "imagens")[:40] or "imagens"
    log(f"Zip de imagens: {len(imagens) - len(falhas)} baixadas, {len(falhas)} falharam.", "ok" if not falhas else "aviso")
    return Response(dados, mimetype="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{nome}.zip"', "X-Falhas": str(len(falhas))})


@app.post("/api/nova")
def api_nova():
    c = conversas.nova()
    return jsonify({"ok": True, "conversa_id": c["id"]})


@app.get("/api/conversas")
def api_conversas():
    return jsonify(conversas.listar())


@app.get("/api/conversas/<cid>")
def api_conversa(cid):
    c = conversas.carregar(cid)
    return (jsonify(c), 200) if c else (jsonify({"erro": "não encontrada"}), 404)


@app.get("/api/status")
def api_status():
    return jsonify({
        "navegador_aberto": nav.aberto,
        "navegador_visivel": config["navegador_visivel"],
        "ocupado": nav.ocupado,
        "fila": nav.fila.qsize(),
        "etapa": estado["etapa"],
        "ultimo_erro": estado["ultimo_erro"],
        "conversa_atual": conversas.atual["id"] if conversas.atual else None,
        # 🔒 esperando você resolver um captcha na janela (com o navegador oculto ele reabre VISÍVEL)
        "captcha": bool(getattr(nav.ia, "esperando_captcha", False)) if getattr(nav, "ia", None) is not None else False,
    })


@app.get("/api/config")
def api_config_get():
    return jsonify({"config": config, "padrao": CONFIG_PADRAO})


@app.post("/api/config")
def api_config_set():
    novo = request.get_json(silent=True) or {}
    if novo.get("restaurar_padrao"):
        novo = dict(CONFIG_PADRAO)
    limpo, erros = validar_config(novo)
    if erros:
        return jsonify({"erro": "; ".join(erros)}), 400
    mudou_visibilidade = "navegador_visivel" in limpo and limpo["navegador_visivel"] != config["navegador_visivel"]
    config.update(limpo)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    log("Configurações salvas: " + ", ".join(f"{k}={v}" for k, v in limpo.items()), "ok")
    aviso = None
    if mudou_visibilidade and nav.aberto:
        aviso = "O navegador será reaberto " + ("visível" if config["navegador_visivel"] else "invisível") \
                + " na próxima pesquisa."
        log(aviso)
    return jsonify({"ok": True, "config": config, "aviso": aviso})


@app.post("/api/navegador/testar")
def api_testar():
    try:
        return jsonify(nav.executar(tarefa_testar, timeout=120))
    except Exception as e:
        return resposta_erro(registrar_erro(e, None, contexto="teste do navegador"))


@app.post("/api/navegador/reiniciar")
def api_reiniciar():
    try:
        nav.executar(tarefa_reiniciar, timeout=90)
        return jsonify({"ok": True})
    except Exception as e:
        return resposta_erro(registrar_erro(e, None, contexto="reiniciar navegador"))


@app.post("/api/navegador/fechar")
def api_fechar():
    nav.executar(tarefa_fechar, timeout=60)
    return jsonify({"ok": True})


@app.get("/api/logs")
def api_logs():
    depois = request.args.get("depois", type=int, default=0)
    return jsonify([l for l in list(LOGS) if l["id"] > depois])


@app.post("/api/logs/limpar")
def api_logs_limpar():
    LOGS.clear()
    estado["ultimo_erro"] = None
    return jsonify({"ok": True})


@app.get("/debug/<path:nome>")
def arquivos_debug(nome):
    if not (DEBUG_DIR / Path(nome).name).exists():
        abort(404)
    return send_from_directory(DEBUG_DIR, Path(nome).name, as_attachment=nome.endswith(".html"))


@app.get("/erros/<path:nome>")
def arquivos_erro(nome):
    if not (ERROS_DIR / Path(nome).name).exists():
        abort(404)
    return send_from_directory(ERROS_DIR, Path(nome).name)


if __name__ == "__main__":
    # aberto pelo site (BestEditor, que roda com o recarregador do Flask): não herda o soquete dele (WinError 10038)
    for _k in ("WERKZEUG_SERVER_FD", "WERKZEUG_RUN_MAIN"):
        os.environ.pop(_k, None)
    porta = int(os.environ.get("PORTA", "5000"))
    print(f"\n  Chat:  http://127.0.0.1:{porta}\n  API:   http://127.0.0.1:{porta}/api/pesquisar\n"
          f"  Navegador: {'visível' if config['navegador_visivel'] else 'invisível'} "
          f"(mude em Configurações)\n")
    try:
        app.run(host="127.0.0.1", port=porta, threaded=True, use_reloader=False)
    finally:
        nav.parar()
