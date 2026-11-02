"""v84_315: ▶ retomar a fila mostra o progresso já na resposta; cada vídeo pendente tem o próprio ▶ retomar este."""
import os
import threading
import time

import curtos as CT
import curtos_comentario as CC
import curtos_rotas as CR
from flask import Flask


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    monkeypatch.setattr(CR, "CB", dict(CR.CB))
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(CT.__file__), "templates"))
    CR.registrar(app, str(tmp_path))
    return app.test_client()


def _pendente(base, n):
    p = CT.criar(base, "", f"🔗 {n}", modelo="comentario")
    p["link_rapido"] = {"link": f"https://a.com/{n}", "etapa": "💬 lendo os comentários", "erro": "", "criado": n + 1}
    CT.salvar(base, p)
    return p["id"]


def _espera_fila(ids):
    for _ in range(400):
        if all((CR.TAREFAS.get(i) or {}).get("fim") for i in ids):
            return
        time.sleep(0.02)


def test_retomar_mostra_progresso_ja_na_resposta(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    ids = [_pendente(base, n) for n in range(3)]
    trava = threading.Event()
    monkeypatch.setattr(CC, "baixar_clipe", lambda *a, **k: trava.wait(5) and (_ for _ in ()).throw(CT.CurtoErro("x")))
    r = cl.post("/curtos/link/retomar").get_json()
    assert r["ok"] and r["retomados"] == 3 and not r["ocupado"]
    por_id = {v["id"]: v for v in r["videos"]}
    assert all(por_id[i]["rodando"] for i in ids)  # nenhum fica parecendo parado
    trava.set()
    _espera_fila(ids)


def test_segundo_clique_com_fila_rodando_avisa_ocupado(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    pid = _pendente(base, 0)
    trava = threading.Event()
    monkeypatch.setattr(CC, "baixar_clipe", lambda *a, **k: trava.wait(5) and (_ for _ in ()).throw(CT.CurtoErro("x")))
    cl.post("/curtos/link/retomar")
    r2 = cl.post("/curtos/link/retomar").get_json()
    assert r2["ok"] and r2["retomados"] == 0 and r2["ocupado"] is True
    trava.set()
    _espera_fila([pid])


def test_retomar_este_botao_individual(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    pid = _pendente(base, 7)
    monkeypatch.setattr(CC, "baixar_clipe", lambda *a, **k: (_ for _ in ()).throw(CT.CurtoErro("parei (teste)")))
    r = cl.post(f"/curtos/link/{pid}/refazer")
    assert r.status_code == 200
    for _ in range(300):
        t = CR.TAREFAS.get(pid) or {}
        if t.get("fim"):
            break
        time.sleep(0.02)
    assert CR.TAREFAS[pid]["fim"] is not None  # rodou e terminou (com erro do teste), sem travar


def test_fila_vazia_nao_faz_nada(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    r = cl.post("/curtos/link/retomar").get_json()
    assert r["ok"] and r["retomados"] == 0 and r["ocupado"] is False
