"""🧲 Navegador das imagens (v84_150) — um Brave (ou Chrome/Edge) SÓ do site, com perfil próprio, onde fica
instalado o Tampermonkey + o userscript "Capturar links" (o da pessoa, adaptado).

Fluxo:
  1. ⚙ Preparar (uma vez): abre esse navegador na página do Tampermonkey e no script (/navegador-imagens/script.user.js).
  2. 🧲 Abrir as próximas 5: o site abre 5 guias do Google Imagens (uma por pergunta das 📸 Fotos do roteiro, ou por
     pessoa/lugar do 🎭 Elenco). Cada guia leva no endereço (#bes=…) pra onde mandar: o site, o modelo e a pergunta.
  3. Em cada guia a pessoa marca as imagens certas e clica em "Capturar e enviar ao site": o script pega o link da
     imagem em tamanho original e manda pro site (POST /fotos-roteiro/link), que BAIXA e liga à pergunta. A guia fecha.
  4. Guia que ela não rodou = não achou imagem boa: a pergunta continua pendente (dá pra mudar o termo e abrir de novo).
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
from typing import Any, Dict, List, Optional

PERFIL = "navegador_imagens_perfil"
TAMPERMONKEY = "https://chromewebstore.google.com/detail/tampermonkey/dhdgffkkebhmkfjojejmpbldmpobfkfo"
ORANGEMONKEY = "https://chromewebstore.google.com/detail/orangemonkey/ekmeppjgajofkpiofbebgcbohbmfldaf"
GERENCIADORES = {"orangemonkey": ORANGEMONKEY, "tampermonkey": TAMPERMONKEY}
# guia em segundo plano não pode "dormir": o script clica e espera o painel do Google abrir em todas ao mesmo tempo
FLAGS = ["--no-first-run", "--no-default-browser-check", "--disable-background-timer-throttling",
         "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows"]


def _candidatos() -> List[str]:
    if sys.platform.startswith("win"):
        raizes = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        rel = [r"BraveSoftware\Brave-Browser\Application\brave.exe", r"Google\Chrome\Application\chrome.exe",
               r"Microsoft\Edge\Application\msedge.exe"]
        return [os.path.join(r, x) for x in rel for r in raizes if r]
    if sys.platform == "darwin":
        return ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    return [shutil.which(n) or "" for n in ("brave-browser", "brave", "google-chrome", "chromium", "chromium-browser")]


def achar(cfg: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """O executável: o de ⚙ (navegador_imagens_exe) ou o Brave; sem Brave, Chrome/Edge."""
    meu = str((cfg or {}).get("navegador_imagens_exe") or "").strip().strip('"')
    if meu and os.path.isfile(meu):
        return meu
    return next((c for c in _candidatos() if c and os.path.isfile(c)), None)


def nome_do(exe: Optional[str]) -> str:
    n = os.path.basename(exe or "").lower()
    return "Brave" if "brave" in n else "Edge" if "edge" in n else "Chrome" if ("chrome" in n or "chromium" in n) else (n or "—")


PORTA = 9333  # porta de controle do Brave do site (só no 127.0.0.1): o site abre e FECHA as guias por ela
ABAS: Dict[str, List[Dict[str, Any]]] = {}      # pid → guias que o site abriu [{id, chave}]
ESTADOS: Dict[str, Dict[str, Any]] = {}         # "pid|chave" → {estado, marcadas, t} (o script avisa)
OCUPADA = ("marcada", "rodando", "erro")         # guia que NÃO fecha sozinha


def _porta(cfg: Optional[Dict[str, Any]]) -> int:
    try:
        return int((cfg or {}).get("navegador_imagens_porta") or PORTA)
    except (TypeError, ValueError):
        return PORTA


def _cdp(porta: int, caminho: str, metodo: str = "GET", timeout: float = 3.0) -> Any:
    import urllib.request
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{porta}{caminho}", method=metodo)
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (só localhost)
            corpo = r.read().decode("utf-8", "replace")
        try:
            return json.loads(corpo)
        except ValueError:
            return corpo or True
    except Exception:  # noqa: BLE001
        return None


def _nova_guia(porta: int, url: str) -> Optional[str]:
    q = urllib.parse.quote(url, safe="")
    d = _cdp(porta, "/json/new?" + q, "PUT") or _cdp(porta, "/json/new?" + q)  # Chrome novo pede PUT
    return d.get("id") if isinstance(d, dict) else None


def abrir(base: str, urls: List[str], cfg: Optional[Dict[str, Any]] = None, chaves: Optional[List[str]] = None,
          pid: str = "") -> Dict[str, Any]:
    """Abre as guias no navegador do site (perfil próprio, separado do seu navegador de sempre). Com a porta de
    controle no ar, guarda o id de cada guia — é assim que o site consegue FECHAR as que já terminaram."""
    import time
    exe = achar(cfg)
    if not exe:
        return {"ok": False, "erro": "Não achei o Brave (nem Chrome/Edge). Instale o Brave ou ponha o caminho do .exe em ⚙."}
    porta = _porta(cfg)
    if not _cdp(porta, "/json/version"):
        perfil = os.path.join(base, PERFIL)
        os.makedirs(perfil, exist_ok=True)
        kw: Dict[str, Any] = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform.startswith("win"):
            kw["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kw["start_new_session"] = True
        subprocess.Popen([exe, f"--user-data-dir={perfil}", f"--remote-debugging-port={porta}"] + FLAGS, **kw)  # noqa: S603
        for _ in range(40):
            time.sleep(0.25)
            if _cdp(porta, "/json/version"):
                break
        else:  # o Brave do site já estava aberto sem a porta (versão antiga): abre do jeito simples
            subprocess.Popen([exe, f"--user-data-dir={perfil}"] + FLAGS + list(urls), **kw)  # noqa: S603
            return {"ok": True, "navegador": nome_do(exe), "guias": len(urls), "controle": False,
                    "aviso": "feche o Brave do site e abra de novo pelo site pra ele poder fechar as guias sozinho"}
        branca = [t.get("id") for t in (_cdp(porta, "/json/list") or []) if isinstance(t, dict) and t.get("type") == "page"]
    else:
        branca = []
    ids = []
    for k, u in enumerate(urls):
        gid = _nova_guia(porta, u)
        ids.append(gid)
        if gid and pid and chaves and k < len(chaves):
            ABAS.setdefault(pid, []).append({"id": gid, "chave": chaves[k]})
    for gid in branca:  # a guia em branco de quando o Brave abriu
        _cdp(porta, f"/json/close/{gid}")
    return {"ok": True, "navegador": nome_do(exe), "guias": len(urls), "controle": any(ids)}


def fechar_terminadas(pid: str, cfg: Optional[Dict[str, Any]] = None, espera_s: float = 0) -> Dict[str, Any]:
    """Fecha as guias desse modelo que o site abriu e NÃO estão ocupadas (imagem marcada e não enviada, ou enviando).
    As ocupadas ficam pra próxima rodada."""
    import time
    porta = _porta(cfg)
    vivas = {t.get("id") for t in (_cdp(porta, "/json/list") or []) if isinstance(t, dict)}
    fechadas, mantidas = [], []
    for a in list(ABAS.get(pid) or []):
        if a["id"] not in vivas:  # você já fechou
            ABAS[pid].remove(a)
            fechadas.append(a["chave"])
            continue
        est = ESTADOS.get(f"{pid}|{a['chave']}") or {}
        if est.get("estado") in OCUPADA and time.time() - float(est.get("t") or 0) < 15 * 60:
            mantidas.append({"chave": a["chave"], "estado": est.get("estado"), "marcadas": est.get("marcadas", 0)})
            continue
        _cdp(porta, f"/json/close/{a['id']}")
        ABAS[pid].remove(a)
        fechadas.append(a["chave"])
    return {"fechadas": fechadas, "mantidas": mantidas}


def destino(site: str, pid: str, pergunta: str = "", elenco: Optional[Dict[str, str]] = None, rotulo: str = "") -> str:
    d: Dict[str, Any] = {"u": site.rstrip("/"), "p": pid}
    if pergunta:
        d["q"] = pergunta
    if elenco:
        d["e"] = elenco
    if rotulo:
        d["r"] = rotulo[:120]
    return base64.urlsafe_b64encode(json.dumps(d, ensure_ascii=False).encode()).decode().rstrip("=")


def url_google(termo: str, dest: str) -> str:
    return "https://www.google.com/search?udm=2&q=" + urllib.parse.quote(termo) + "#bes=" + dest


def termo_da(q: Dict[str, Any]) -> str:
    return str(q.get("busca") or q.get("alvo") or q.get("pergunta") or "").strip()


def proximas(perguntas: List[Dict[str, Any]], enviadas: Dict[str, List[str]], quantas: int = 5,
             so: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """As próximas perguntas pra abrir: sem foto ainda, não puladas e não abertas (ou as pedidas)."""
    if so:
        return [q for q in perguntas if q["id"] in so][:20]
    fila = [q for q in perguntas if not q.get("pulada") and not enviadas.get(q["id"]) and q.get("guia") != "aberta" and termo_da(q)]
    return fila[:max(1, min(10, int(quantas or 5)))]


def script(site: str = "http://localhost:5050", versao: str = "2.4.0") -> str:
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "navegador_imagens.user.js")
    with open(caminho, encoding="utf-8") as fh:
        return fh.read().replace("__VERSAO__", versao).replace("__SITE__", site.rstrip("/"))


# ------------------------------------------------------------------ rotas
def registrar(app, base_dir: str) -> None:
    from flask import Response, jsonify, request
    import dossies as ds
    import dossies_rotas
    from site_config import load_site_config

    def _site() -> str:
        return request.host_url.rstrip("/")

    @app.route("/navegador-imagens/script.user.js")
    def navegador_imagens_script():
        return Response(script(_site()), mimetype="text/javascript; charset=utf-8", headers={"Cache-Control": "no-cache"})

    @app.route("/navegador-imagens/instalar")
    def navegador_imagens_instalar():
        """Página de instalação: link do .user.js (Tampermonkey/OrangeMonkey abrem sozinhos) + o código pra colar."""
        import html as _h
        cod = script(_site())
        pag = f"""<!doctype html><meta charset="utf-8"><title>Instalar o script</title>
<body style="font-family:Arial,sans-serif;max-width:900px;margin:20px auto;padding:0 16px;line-height:1.5">
<h2>🧲 Script "Capturar links" do BestEditor</h2>
<ol><li>Instale a extensão (<b>OrangeMonkey</b> ou Tampermonkey) na outra guia.</li>
<li>Clique em <a href="/navegador-imagens/script.user.js"><b>instalar o script</b></a> — a extensão abre a tela de instalação.<br>
Se não abrir: no ícone da extensão → <b>Criar/Adicionar novo script</b>, apague o que vier e cole o código abaixo (<button onclick="navigator.clipboard.writeText(document.getElementById('c').value);this.textContent='✔ copiado'">📋 copiar</button>), salve.</li>
<li>Se a extensão pedir, ative <b>"Permitir scripts de usuário"</b> (chrome://extensions → Detalhes da extensão).</li>
<li>Se o script já existia (versão antiga sem o envio ao site), substitua pelo novo.</li></ol>
<textarea id="c" style="width:100%;height:340px;font:12px monospace">{_h.escape(cod)}</textarea></body>"""
        return Response(pag, mimetype="text/html; charset=utf-8")

    @app.route("/navegador-imagens/estado")
    def navegador_imagens_estado():
        exe = achar(load_site_config())
        return jsonify({"ok": True, "navegador": nome_do(exe) if exe else "", "exe": exe or "",
                        "preparado": os.path.isdir(os.path.join(base_dir, PERFIL))})

    @app.route("/navegador-imagens/preparar", methods=["POST"])
    def navegador_imagens_preparar():
        c = request.get_json(silent=True) or {}
        loja = GERENCIADORES.get(str(c.get("gerenciador") or "orangemonkey"), ORANGEMONKEY)
        r = abrir(base_dir, [loja, _site() + "/navegador-imagens/instalar"], load_site_config())
        return jsonify(r), (200 if r.get("ok") else 400)

    @app.route("/modelos-video/<pid>/fotos-roteiro/guias", methods=["POST"])
    def fotos_roteiro_guias(pid: str):
        """🧲 Abre as próximas N perguntas (ou as pedidas) no navegador do site, uma guia cada.
        "trocar": antes fecha as guias que já terminaram (as com imagem marcada e não enviada ficam abertas)."""
        c = request.get_json(silent=True, force=True) or {}
        cfg = load_site_config()
        troca = fechar_terminadas(pid, cfg) if c.get("trocar") else {"fechadas": [], "mantidas": []}
        termos = {str(k): str(v).strip()[:200] for k, v in (c.get("termos") or {}).items() if str(v or "").strip()}
        with dossies_rotas._TRAVA:
            try:
                p = ds.carregar(base_dir, pid)
            except ds.DossieError:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            qs = (p.get("fotos_roteiro") or {}).get("perguntas") or []
            for q in qs:
                if q["id"] in termos:
                    q["busca"] = termos[q["id"]]
            enviadas: Dict[str, List[str]] = {}
            for m in p.get("midias") or []:
                if m.get("pergunta"):
                    enviadas.setdefault(m["pergunta"], []).append(m["id"])
            fech = set(troca["fechadas"])
            for q in qs:  # guia fechada sem nenhuma foto = não achou (fica pendente, com o aviso)
                if q["id"] in fech and not enviadas.get(q["id"]):
                    q["guia"] = "vazia"
                elif q["id"] in fech and q.get("guia") == "aberta":
                    q["guia"] = "feita"
            if c.get("reabrir_abertas"):
                for q in qs:
                    if q.get("guia") in ("aberta", "vazia") and not enviadas.get(q["id"]):
                        q.pop("guia", None)
            escolhidas = proximas([q for q in qs if q.get("guia") != "vazia" or c.get("perguntas")], enviadas,
                                  int(c.get("quantas") or 5), [str(x) for x in c.get("perguntas") or []] or None)
            if not escolhidas:
                ds.salvar(base_dir, p)
                return jsonify({"ok": True, "abertas": 0, "fechadas": len(troca["fechadas"]), "mantidas": troca["mantidas"],
                                "msg": "Nenhuma pergunta pendente (todas com foto, puladas, sem imagem boa ou já abertas)."})
            urls = [url_google(termo_da(q), destino(_site(), pid, q["id"], rotulo=q.get("pergunta") or "")) for q in escolhidas]
            r = abrir(base_dir, urls, cfg, chaves=[q["id"] for q in escolhidas], pid=pid)
            if r.get("ok") or c.get("sem_navegador"):
                for q in escolhidas:
                    q["guia"] = "aberta"
            ds.salvar(base_dir, p)
        if not r.get("ok"):
            return jsonify({"ok": False, "erro": r.get("erro"), "urls": urls}), 400
        faltam = sum(1 for q in qs if not q.get("pulada") and not enviadas.get(q["id"]) and q.get("guia") != "aberta")
        return jsonify({"ok": True, "abertas": len(escolhidas), "navegador": r.get("navegador"), "faltam": faltam,
                        "ids": [q["id"] for q in escolhidas], "fechadas": len(troca["fechadas"]), "mantidas": troca["mantidas"],
                        "controle": r.get("controle"), "aviso": r.get("aviso") or ""})

    @app.route("/navegador-imagens/fechar", methods=["POST"])
    def navegador_imagens_fechar():
        """A guia terminou de enviar: o site fecha ela pela porta de controle (window.close nem sempre pode)."""
        c = request.get_json(silent=True, force=True) or {}
        pid = str(c.get("p") or "")[:40]
        chave = str(c.get("q") or "") or ("el:" + str((c.get("e") or {}).get("n") or "") if c.get("e") else "")
        porta = _porta(load_site_config())
        for a in list(ABAS.get(pid) or []):
            if a["chave"] == chave:
                _cdp(porta, f"/json/close/{a['id']}")
                ABAS[pid].remove(a)
                return jsonify({"ok": True, "fechou": True})
        return jsonify({"ok": True, "fechou": False})

    @app.route("/navegador-imagens/aba", methods=["POST"])
    def navegador_imagens_aba():
        """O script de cada guia avisa como ela está: livre / marcada (tem imagem marcada e não enviada) / rodando /
        enviada / erro — é o que decide se ela pode ser fechada na troca."""
        import time
        c = request.get_json(silent=True, force=True) or {}
        pid = str(c.get("p") or "")[:40]
        chave = str(c.get("q") or "") or ("el:" + str((c.get("e") or {}).get("n") or "") if c.get("e") else "")
        if pid and chave:
            ESTADOS[f"{pid}|{chave[:130]}"] = {"estado": str(c.get("estado") or "livre")[:12], "marcadas": int(c.get("marcadas") or 0), "t": time.time()}
        return jsonify({"ok": True})

    @app.route("/modelos-video/<pid>/fotos-roteiro/guia-feita", methods=["POST"])
    def fotos_roteiro_guia_feita(pid: str):
        """O script terminou uma guia (mandou N links)."""
        c = request.get_json(silent=True, force=True) or {}
        qid = str(c.get("pergunta") or "")[:10]
        with dossies_rotas._TRAVA:
            try:
                p = ds.carregar(base_dir, pid)
            except ds.DossieError:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            for q in (p.get("fotos_roteiro") or {}).get("perguntas") or []:
                if q["id"] == qid:
                    q["guia"] = "feita" if int(c.get("enviadas") or 0) else "vazia"
            ds.salvar(base_dir, p)
        return jsonify({"ok": True})

    @app.route("/modelos-video/<pid>/elenco/guias", methods=["POST"])
    def elenco_guias(pid: str):
        """🧲 Abre o Google Imagens de pessoas/lugares do elenco (as fotos que chegarem já entram nela/nele)."""
        c = request.get_json(silent=True) or {}
        try:
            p = ds.carregar(base_dir, pid)
        except ds.DossieError:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        urls = []
        for x in (c.get("itens") or [])[:10]:
            tipo = "local" if x.get("tipo") == "local" else "pessoa"
            nome, termo = str(x.get("nome") or "").strip()[:120], str(x.get("termo") or x.get("nome") or "").strip()[:200]
            if nome and termo:
                urls.append(url_google(termo, destino(_site(), pid, elenco={"t": tipo, "n": nome}, rotulo=("👤 " if tipo == "pessoa" else "📍 ") + nome)))
        if not urls:
            return jsonify({"erro": "Nada pra abrir."}), 400
        cfg = load_site_config()
        if c.get("trocar"):
            fechar_terminadas(pid, cfg)
        chaves = ["el:" + str(x.get("nome") or "").strip()[:120] for x in (c.get("itens") or [])[:10] if str(x.get("nome") or "").strip()]
        r = abrir(base_dir, urls, cfg, chaves=chaves, pid=pid)
        return jsonify(dict(r, urls=urls)), (200 if r.get("ok") else 400)
