"""v84_319: links colados ficam AGUARDANDO (não começam sozinhos); iniciar, remover da fila ou copiar."""
import os
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


def _falha(monkeypatch):
    monkeypatch.setattr(CC, "baixar_clipe", lambda *a, **k: (_ for _ in ()).throw(CT.CurtoErro("parei (teste)")))


def _espera(pids):
    for _ in range(300):
        if all((CR.TAREFAS.get(p) or {}).get("fim") for p in pids):
            return
        time.sleep(0.02)


def test_colar_nao_inicia_sozinho(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    _falha(monkeypatch)
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/1\nhttps://a.com/2"}).get_json()
    assert r["ok"] and len(r["criados"]) == 2
    for pid in r["criados"]:
        lr = CT.carregar(base, pid)["link_rapido"]
        assert lr["aguardando"] is True and "aguardando" in lr["etapa"]
        assert pid not in CR.TAREFAS  # nenhum começou
    time.sleep(0.2)
    estado = {v["id"]: v for v in cl.get("/curtos/link/estado").get_json()["videos"]}
    assert all(estado[p]["aguardando"] and not estado[p]["rodando"] and not estado[p]["pendente"] for p in r["criados"])


def test_iniciar_com_iniciar_marcado(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    _falha(monkeypatch)
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/9", "iniciar": True}).get_json()
    pid = r["criados"][0]
    assert CT.carregar(base, pid)["link_rapido"].get("aguardando") is False
    _espera([pid])
    assert CR.TAREFAS[pid]["fim"] is not None


def test_remover_so_aguardando(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    _falha(monkeypatch)
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/5"}).get_json()
    pid = r["criados"][0]
    assert cl.post(f"/curtos/link/{pid}/remover").status_code == 200
    assert not os.path.exists(CT.pasta(base, pid))
    assert cl.get("/curtos/link/estado").get_json()["videos"] == []
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/6", "iniciar": True}).get_json()
    _espera(r["criados"])
    assert cl.post(f"/curtos/link/{r['criados'][0]}/remover").status_code == 409


def test_iniciar_todos_os_aguardando(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    _falha(monkeypatch)
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/7\nhttps://a.com/8"}).get_json()
    res = cl.post("/curtos/link/iniciar-aguardando").get_json()
    assert res["ok"] and res["iniciados"] == 2
    _espera(r["criados"])
    for pid in r["criados"]:
        assert CT.carregar(base, pid)["link_rapido"].get("aguardando") is False


def test_iniciar_este_tira_o_aguardando(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    _falha(monkeypatch)
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/10"}).get_json()
    pid = r["criados"][0]
    assert cl.post(f"/curtos/link/{pid}/refazer").status_code == 200
    _espera([pid])
    time.sleep(0.05)
    assert CT.carregar(base, pid)["link_rapido"].get("aguardando") is False
