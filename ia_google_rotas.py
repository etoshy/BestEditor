"""
ia_google_rotas.py
==================

🔎 IA DO GOOGLE (Modo IA do Google, por um navegador automatizado) — o app da pasta `ia_google/` roda À PARTE
(porta própria, padrão 8852; o perfil do navegador dele é só dele) e o site:

  • mostra o app numa aba (🔎 IA do Google) — chat, vídeos do YouTube, histórico;
  • usa a API dele pra:
      - 🎬 achar o MOMENTO num vídeo do YouTube "assistindo" o vídeo (o agente do YouTube usa quando o vídeo não
        tem legenda ou a leitura da legenda não achou — ou sempre, se você escolher);
      - ✅ checar fatos de um roteiro (com fontes).

  cliente: no_ar() · garantir() · pesquisar(pergunta) · video(url, tarefa, consulta) · momento(url, fala)
"""
from __future__ import annotations

import atexit
import os
import re
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

PORTA_PADRAO = 8852
PASTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ia_google")
_PROC: Dict[str, Any] = {"proc": None, "erro": None, "log": None}
_TRAVA = threading.Lock()
MODOS_YOUTUBE = ("complemento", "sempre", "desligado")


class IAGoogleErro(Exception):
    pass


def _cfg() -> Dict[str, Any]:
    try:
        from site_config import load_site_config
        return load_site_config()
    except Exception:  # noqa: BLE001
        return {}


def porta() -> int:
    try:
        return int(_cfg().get("ia_google_porta") or PORTA_PADRAO)
    except (TypeError, ValueError):
        return PORTA_PADRAO


def url_base() -> str:
    return f"http://127.0.0.1:{porta()}"


def instalado() -> bool:
    return os.path.isfile(os.path.join(PASTA, "app.py"))


def modo_youtube() -> str:
    m = str(_cfg().get("ia_google_youtube") or "complemento")
    return m if m in MODOS_YOUTUBE else "complemento"


def no_ar() -> bool:
    from analisador_rotas import _porta_aberta
    return _porta_aberta(porta())


def iniciar(popen=subprocess.Popen) -> Dict[str, Any]:
    """Sobe o app da IA do Google (se ainda não estiver no ar)."""
    p = porta()
    with _TRAVA:
        if no_ar():
            return {"ok": True, "porta": p, "ja_rodando": True}
        proc = _PROC.get("proc")
        if proc is not None and proc.poll() is None:
            return {"ok": True, "porta": p, "iniciando": True}
        if not instalado():
            return {"ok": False, "erro": "A pasta ia_google/ não está no site."}
        from analisador_rotas import env_do_niche_miner
        env = env_do_niche_miner()  # sem as variáveis do recarregador do Flask (senão ele fecha na hora)
        env["PORTA"] = str(p)
        log_path = os.path.join(PASTA, "ia_google.log")
        try:
            logf = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
            _PROC["proc"] = popen([sys.executable, "app.py"], cwd=PASTA, stdout=logf, stderr=subprocess.STDOUT, env=env)
            _PROC.update(erro=None, log=log_path)
        except Exception as exc:  # noqa: BLE001
            _PROC["erro"] = str(exc)[:300]
            return {"ok": False, "erro": _PROC["erro"]}
    return {"ok": True, "porta": p, "iniciando": True}


def status() -> Dict[str, Any]:
    proc = _PROC.get("proc")
    morreu = proc is not None and proc.poll() is not None
    out = {"porta": porta(), "no_ar": no_ar(), "morreu": morreu, "erro": _PROC.get("erro"), "instalado": instalado(),
           "modo_youtube": modo_youtube()}
    out["captcha"] = captcha_esperando() if out["no_ar"] else False
    if morreu and _PROC.get("log"):
        try:
            with open(_PROC["log"], encoding="utf-8", errors="replace") as f:
                out["log"] = f.read()[-1500:]
        except OSError:
            pass
    return out


def garantir(espera_s: float = 45.0) -> None:
    """Liga (se precisar) e espera ficar no ar."""
    if no_ar():
        return
    r = iniciar()
    if not r.get("ok"):
        raise IAGoogleErro(r.get("erro") or "não deu pra ligar a IA do Google")
    fim = time.monotonic() + espera_s
    while time.monotonic() < fim:
        if no_ar():
            return
        proc = _PROC.get("proc")
        if proc is not None and proc.poll() is not None:
            raise IAGoogleErro("o app da IA do Google fechou sozinho — veja ia_google/ia_google.log "
                               "(ele precisa do Flask e do Playwright: pip install -r ia_google/requirements.txt)")
        time.sleep(0.5)
    raise IAGoogleErro(f"a IA do Google não subiu em {int(espera_s)}s (porta {porta()})")


CHAVE_CAPTCHA = "ia_google:captcha"


def captcha_esperando() -> bool:
    """O app está esperando você resolver um captcha? (pergunta rápida pro /api/status dele)"""
    import requests
    try:
        return bool(requests.get(url_base() + "/api/status", timeout=2).json().get("captcha"))
    except Exception:  # noqa: BLE001
        return False


def _vigiar_captcha(parar: threading.Event, intervalo: float = 3.0) -> None:
    """Enquanto uma pergunta do site roda: se o Google pedir captcha, avisa no 🔔 (o app já reabriu o navegador
    VISÍVEL) e, quando resolver, tira o aviso."""
    import notificacoes
    avisou = False
    while not parar.wait(intervalo):
        if captcha_esperando():
            if not avisou:
                notificacoes.avisar("🔒 A IA do Google pediu captcha — resolva na janela do navegador",
                                    "A janela do navegador dela abriu visível (se estava oculta). Resolva o “não sou um robô” "
                                    "lá — a pesquisa continua sozinha.", "/ia-google", "aviso", tipo="captcha", chave=CHAVE_CAPTCHA)
                avisou = True
        elif avisou:
            notificacoes.resolver(CHAVE_CAPTCHA)
            avisou = False
    if avisou:
        notificacoes.resolver(CHAVE_CAPTCHA)


def _post(rota: str, corpo: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    import requests
    garantir()
    parar = threading.Event()
    threading.Thread(target=_vigiar_captcha, args=(parar,), name="ia-google-captcha", daemon=True).start()
    try:
        return _post_direto(requests, rota, corpo, timeout)
    finally:
        parar.set()


def _post_direto(requests, rota: str, corpo: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    try:
        r = requests.post(url_base() + rota, json=corpo, timeout=timeout)
    except requests.exceptions.Timeout:
        raise IAGoogleErro(f"a IA do Google demorou mais de {int(timeout)}s (captcha esperando? abra a aba 🔎 IA do Google)")
    except requests.exceptions.ConnectionError:
        raise IAGoogleErro("não consegui falar com a IA do Google")
    try:
        d = r.json()
    except ValueError:
        raise IAGoogleErro(f"a IA do Google respondeu HTTP {r.status_code} sem JSON")
    if r.status_code >= 400 or d.get("erro"):
        det = d.get("detalhes_erro") or {}
        raise IAGoogleErro(str(d.get("erro") or f"HTTP {r.status_code}") + (f" — {det['dica']}" if det.get("dica") else ""))
    return d


def pesquisar(pergunta: str, nova_conversa: bool = True, timeout: float = 360) -> Dict[str, Any]:
    """→ {resposta_objetiva, resposta_completa (markdown), fontes: [{titulo, site, url, trecho}], …}"""
    return _post("/api/pesquisar", {"pergunta": pergunta, "nova_conversa": nova_conversa}, timeout)


def video(url: str, tarefa: str, consulta: str = "", timeout: float = 480,
          errados: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Tarefas: resumo, pergunta, momentos, capitulos, cortes, frases, checar, … (ver ia_google/youtube.py).
    `errados` (🔁 olhar de novo): momentos que ela indicou e não eram — vai na MESMA conversa dizendo isso."""
    corpo: Dict[str, Any] = {"url": url, "tarefa": tarefa, "consulta": consulta}
    if errados:
        corpo["errados"] = [{"inicio": float(e["inicio"]), "fim": float(e.get("fim") or float(e["inicio"]) + 5)}
                            for e in errados if e.get("inicio") is not None][:20]
    return _post("/api/video", corpo, timeout)


def _recusado(ini: float, evitar: Optional[List[Dict[str, Any]]], folga: float = 3.0) -> bool:
    for e in evitar or []:
        try:
            a = float(e["inicio"])
            b = float(e.get("fim") or a + 5)
        except (KeyError, TypeError, ValueError):
            continue
        if a - folga <= ini <= max(b, a + folga):
            return True
    return False


def momento(url: str, fala: str, duracao_alvo: Optional[float] = None, timeout: float = 480,
            evitar: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """🎬 O Google "assiste" o vídeo e diz onde está o que a narração pede → formato do yt_agente
    ({"achou", "inicio", "fim", "frase", "confianca"}) ou None (não achou).
    `evitar` = [{"inicio", "fim"}] (🔁 olhar de novo): os momentos que estavam errados."""
    fala = " ".join(str(fala or "").split())[:600]
    consulta = (f"o momento que mostra ou em que é dito o que esta narração descreve: \"{fala}\""
                + (f" (trecho de uns {int(duracao_alvo)} segundos)" if duracao_alvo else ""))
    d = video(url, "momentos", consulta, timeout, errados=evitar)
    dados = d.get("dados") or {}
    if dados.get("encontrado") is False:
        return None
    for m in dados.get("momentos") or []:
        try:
            ini = float(m.get("inicio_seg"))
            fim = float(m.get("fim_seg") if m.get("fim_seg") is not None else ini + (duracao_alvo or 5))
        except (TypeError, ValueError):
            continue
        if fim > ini >= 0 and not _recusado(ini, evitar):
            return {"achou": True, "inicio": ini, "fim": fim, "frase": str(m.get("citacao") or m.get("descricao") or "")[:300],
                    "confianca": 0.7, "fonte": "google"}
    return None


def checar_fatos(texto: str, timeout: float = 420) -> Dict[str, Any]:
    """✅ Confere as afirmações de um roteiro na web (com fontes)."""
    texto = str(texto or "").strip()[:9000]
    pergunta = ("Confira, pesquisando na web, se as afirmações FACTUAIS deste roteiro estão corretas (nomes, datas, números, "
                "lugares, quem disse o quê). Para cada afirmação importante diga se está CORRETA, ERRADA ou DUVIDOSA, "
                "a correção quando estiver errada e a fonte. Ignore opiniões e frases de efeito. Roteiro:\n\n" + texto)
    return pesquisar(pergunta, nova_conversa=True, timeout=timeout)


@atexit.register
def _parar() -> None:
    proc = _PROC.get("proc")
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ rotas
def registrar(app, base_dir: str) -> None:
    from flask import jsonify, render_template, request

    @app.route("/ia-google")
    def ia_google_page():
        return render_template("ia_google.html", porta=porta(), instalado=instalado(), modo=modo_youtube())

    @app.route("/ia-google/iniciar", methods=["POST"])
    def ia_google_iniciar():
        return jsonify(iniciar())

    @app.route("/ia-google/status")
    def ia_google_status():
        return jsonify(status())

    def _checagem(texto: str) -> Dict[str, Any]:
        d = checar_fatos(texto)
        fontes = [{k: str(f.get(k) or "")[:300] for k in ("titulo", "site", "url", "trecho")}
                  for f in d.get("fontes") or [] if re.match(r"https?://", str(f.get("url") or ""))]
        return {"ok": True, "objetiva": d.get("resposta_objetiva") or "", "completa": d.get("resposta_completa") or "",
                "fontes": fontes[:20]}

    @app.route("/ia-google/checar", methods=["POST"])
    def ia_google_checar():
        """✅ Checa fatos. Com "bg": true roda em segundo plano (v84_87): pode fechar a aba — o resultado fica guardado
        (volta sozinho na página) e chega um aviso no 🔔."""
        corpo = request.get_json(silent=True) or {}
        texto = str(corpo.get("texto") or "").strip()
        if len(texto) < 20:
            return jsonify({"erro": "Mande o texto do roteiro."}), 400
        if corpo.get("bg"):
            import tarefas_bg
            tid = tarefas_bg.iniciar("checar_fatos", "✅ Checar fatos do roteiro", lambda t: _checagem(texto),
                                     pagina=str(corpo.get("pagina") or ""))
            return jsonify({"ok": True, "tarefa": tid})
        try:
            return jsonify(_checagem(texto))
        except IAGoogleErro as exc:
            return jsonify({"erro": str(exc)}), 502
