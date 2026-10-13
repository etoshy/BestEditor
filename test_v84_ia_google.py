"""v84_86 — 🔎 IA do Google (app ia_google/ à parte): sobe pelo site, o agente do YouTube usa pra "assistir" o vídeo
e achar o momento, e checa fatos do roteiro."""
import http.server
import json
import os
import socket
import threading
import time

import pytest

import ia_google_rotas as igr
import yt_agente


def _porta_livre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def falso(monkeypatch):
    """Servidor no formato da API do app (POST /api/video e /api/pesquisar)."""
    pedidos = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def do_POST(self):  # noqa: N802
            corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            pedidos.append((self.path, corpo))
            if self.path == "/api/video":
                achou = "sonho" in corpo["consulta"]
                d = {"tarefa": corpo["tarefa"], "dados": {"encontrado": achou, "momentos": [
                    {"inicio": "1:05", "inicio_seg": 65, "fim": "1:12", "fim_seg": 72, "citacao": "I have a dream"}] if achou else []}}
            else:
                d = {"resposta_objetiva": "2 erros", "resposta_completa": "- Data ERRADA: 1964, não 1963",
                     "fontes": [{"titulo": "Wiki", "site": "wikipedia.org", "url": "https://pt.wikipedia.org/x"},
                                {"titulo": "mau", "url": "javascript:alert(1)"}]}
            b = json.dumps(d).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(igr, "porta", lambda: srv.server_address[1])
    yield pedidos
    srv.shutdown()


def test_momento_vira_formato_do_agente(falso):
    m = igr.momento("https://youtu.be/abcdefghijk", "ele fala do sonho dele", 6)
    assert m == {"achou": True, "inicio": 65.0, "fim": 72.0, "frase": "I have a dream", "confianca": 0.7, "fonte": "google"}
    assert falso[0][1]["tarefa"] == "momentos" and "sonho" in falso[0][1]["consulta"]
    assert igr.momento("https://youtu.be/abcdefghijk", "outra coisa") is None


def _agente(legendas, achar_ok, assistir, sempre=False):
    v = [{"url": f"https://youtu.be/v{i}", "titulo": f"vídeo {i}"} for i in range(2)]
    vistos_google = []

    def _assistir(video):
        vistos_google.append(video["url"])
        return assistir(video)
    r = yt_agente.procurar(
        "fala", "termo", 5, buscar=lambda t: v, ordenar=lambda *a: None, legenda=lambda u: {"linhas": legendas.get(u, [])},
        achar=lambda linhas, video: {"achou": True, "inicio": 1.0, "fim": 4.0, "frase": "x", "confianca": 0.9} if achar_ok else None,
        nova_busca=lambda f, m: "", assistir=_assistir if assistir else None, assistir_sempre=sempre, max_buscas=1)
    return r, vistos_google


def test_agente_usa_o_google_sem_legenda_e_quando_a_legenda_nao_acha():
    achou = lambda v: {"achou": True, "inicio": 10.0, "fim": 15.0, "frase": "y", "confianca": 0.7, "fonte": "google"}  # noqa: E731
    r, g = _agente({}, False, achou)  # sem legenda nenhuma
    assert r["achou"] and r["fonte"] == "google" and r["inicio"] == 10.0 and g == ["https://youtu.be/v0"]
    r, g = _agente({"https://youtu.be/v0": [{"t": 0, "texto": "a"}]}, True, achou)  # a legenda achou: o Google nem roda
    assert r["achou"] and r["fonte"] == "legenda" and g == []
    r, g = _agente({"https://youtu.be/v0": [{"t": 0, "texto": "a"}]}, False, achou)  # a legenda não achou: o Google assiste
    assert r["achou"] and r["fonte"] == "google"
    r, g = _agente({"https://youtu.be/v0": [{"t": 0, "texto": "a"}]}, True, achou, sempre=True)  # "sempre": Google primeiro
    assert r["fonte"] == "google" and g == ["https://youtu.be/v0"]
    r, g = _agente({}, False, None)  # sem a IA do Google: como antes
    assert not r["achou"]
    r, g = _agente({}, False, lambda v: (_ for _ in ()).throw(RuntimeError("captcha")))  # erro do Google não derruba
    assert not r["achou"] and len(g) == 2


def test_rota_checar_fatos_filtra_links(falso):
    import app as A
    c = A.app.test_client()
    assert c.post("/ia-google/checar", json={"texto": "curto"}).status_code == 400
    d = c.post("/ia-google/checar", json={"texto": "Martin Luther King discursou em 1963 em Washington para 250 mil pessoas."}).get_json()
    assert d["ok"] and "ERRADA" in d["completa"] and [f["url"] for f in d["fontes"]] == ["https://pt.wikipedia.org/x"]
    assert "Confira" in falso[-1][1]["pergunta"] and falso[-1][0] == "/api/pesquisar"


def test_pagina_e_config():
    import app as A
    import site_config
    c = A.app.test_client()
    h = c.get("/ia-google").get_data(as_text=True)
    assert "igFrame" in h and "porta 8852" in h
    assert site_config.DEFAULT_CONFIG["ia_google_youtube"] == "complemento" and site_config.DEFAULT_CONFIG["ia_google_porta"] == 8852


def test_app_de_verdade_sobe_pelo_site_sem_herdar_o_soquete(monkeypatch):
    """Sobe o ia_google/app.py de verdade (sem abrir navegador nem ir ao Google) e confere a API."""
    pytest.importorskip("playwright")
    p = _porta_livre()
    monkeypatch.setattr(igr, "porta", lambda: p)
    monkeypatch.setenv("WERKZEUG_SERVER_FD", "3")  # o site roda com o recarregador do Flask
    monkeypatch.setitem(igr._PROC, "proc", None)
    try:
        igr.garantir(espera_s=40)
        import requests
        tarefas = requests.get(f"http://127.0.0.1:{p}/api/video/tarefas", timeout=10).json()
        assert "momentos" in json.dumps(tarefas)
        st = requests.get(f"http://127.0.0.1:{p}/api/status", timeout=10).json()
        assert st["navegador_aberto"] is False
    finally:
        proc = igr._PROC.get("proc")
        if proc is not None:
            proc.terminate()
            proc.wait(10)
        for lixo in ("config.json",):
            pass
