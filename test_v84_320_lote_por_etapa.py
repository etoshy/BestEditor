"""v84_320: lote POR ETAPA — cada etapa roda em todos os links antes da próxima; cada vídeo mantém a própria configuração."""
import os
import threading
import time

import curtos as CT
import curtos_comentario as CC
import curtos_link as CL
import curtos_rotas as CR
from flask import Flask


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    monkeypatch.setenv("CURTOS_RAM_MIN_GB", "0")
    monkeypatch.setattr(CR, "CB", dict(CR.CB))
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(CT.__file__), "templates"))
    CR.registrar(app, str(tmp_path))
    return app.test_client()


def _falsos(base, monkeypatch, falhar_url=""):
    """O caminho inteiro de mentira: grava (etapa, pid) na ordem e mede quantos rodam juntos na rede."""
    log, baixados = [], set()
    junto = {"agora": 0, "max": 0}
    trava = threading.Lock()

    def baixar(b, pid, url, *a, **k):
        if url == falhar_url:
            raise CT.CurtoErro("link quebrado (teste)")
        with trava:
            junto["agora"] += 1
            junto["max"] = max(junto["max"], junto["agora"])
        time.sleep(0.3)  # tempo pra 2 downloads se sobreporem mesmo com a máquina ocupada
        with trava:
            junto["agora"] -= 1
            log.append(("baixar", pid))
            baixados.add(pid)
        return "M1"

    def clipes(b, p):
        return [{"id": "M1", "caminho": "x.mp4", "tipo": "video"}] if p["id"] in baixados else []

    def roteiro(b, pid, *a, **k):
        log.append(("roteiro", pid))
        with CT._TRAVA:
            q = CT.carregar(b, pid)
            q["roteiro"] = {"blocos": [{"fala": "oi " + pid}]}
            CT.salvar(b, q)

    def takes(b, pid, tts, limpar, voz, n=3, on_log=None):
        log.append(("voz", pid, voz["slug"]))
        chave = CT.chave_roteiro(CT.carregar(b, pid)["roteiro"])
        with CT._TRAVA:
            q = CT.carregar(b, pid)
            q["takes"] = [{"take": 1, "chave": chave, "arquivo": "t1.wav"}]
            CT.salvar(b, q)

    def usar(b, pid, k, transcrever, op=None, on_log=None):
        log.append(("alinhar", pid))
        with CT._TRAVA:
            q = CT.carregar(b, pid)
            q["gravacao"] = {"arquivo": "g.wav", "chave_roteiro": CT.chave_roteiro(q["roteiro"])}
            CT.salvar(b, q)

    def editor(d):
        log.append(("editor", d["pid"]))
        return "job_" + d["pid"]

    monkeypatch.setattr(CC, "baixar_clipe", baixar)
    monkeypatch.setattr(CC, "clipes", clipes)
    monkeypatch.setattr(CL, "baixar_info", lambda url, n=60: {"comentarios": []})
    monkeypatch.setattr(CC, "transcrever_clipe", lambda b, pid, mid, t, prog=None: log.append(("transcrever", pid)))
    monkeypatch.setattr(CC, "gerar_roteiro", roteiro)
    monkeypatch.setattr(CC, "gerar_takes", takes)
    monkeypatch.setattr(CC, "usar_take", usar)
    monkeypatch.setattr(CT, "montar_dados_editor", lambda b, pid, prov=None: {"pid": pid, "planos": [], "dur": 1.0})
    monkeypatch.setattr(CL, "prints_para_thumb", lambda *a, **k: [])
    import anime2d
    monkeypatch.setattr(anime2d, "voz_por_slug", lambda slug, mp: {"slug": slug})
    CR.CB.update(transcrever=lambda *a, **k: [], tts=lambda *a, **k: None, para_estudio=editor)
    return log, junto


def _espera(pids):
    for _ in range(500):
        if all((CR.TAREFAS.get(p) or {}).get("fim") for p in pids):
            return
        time.sleep(0.02)
    raise AssertionError("o lote não terminou")


def test_ordem_por_etapa_erro_isolado_e_paralelo(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    log, junto = _falsos(base, monkeypatch, falhar_url="https://a.com/2")
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/1\nhttps://a.com/2\nhttps://a.com/3\nhttps://a.com/4",
                                           "iniciar": True, "por_etapa": True, "exportar": False, "voz": "v1"}).get_json()
    assert r["ok"] and r.get("por_etapa")
    ids = r["criados"]
    _espera(ids)
    vivos = [ids[0], ids[2], ids[3]]
    etapas = [e[0] for e in log]
    # cada etapa termina em todos antes da próxima começar
    ordem = ["baixar", "transcrever", "roteiro", "voz", "alinhar", "editor"]
    pos = [max(i for i, e in enumerate(etapas) if e == nome) for nome in ordem]
    ini = [min(i for i, e in enumerate(etapas) if e == nome) for nome in ordem]
    for k in range(len(ordem) - 1):
        assert pos[k] < ini[k + 1], (ordem[k], ordem[k + 1], etapas)
    assert junto["max"] == 2  # rede: 2 ao mesmo tempo (padrão), nunca mais
    for e in ("roteiro", "voz", "alinhar", "editor"):
        assert sorted(x[1] for x in log if x[0] == e) == sorted(vivos)
    # o quebrado não parou os outros
    assert CR.TAREFAS[ids[1]]["erro"] and "quebrado" in CT.carregar(base, ids[1])["link_rapido"]["erro"]
    for pid in vivos:
        lr = CT.carregar(base, pid)["link_rapido"]
        assert lr["etapa"] == "✅ no editor" and not CR.TAREFAS[pid]["erro"]
        assert lr["lote_modo"] == "etapa"


def test_voz_agrupada_e_config_de_cada_video(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    log, _ = _falsos(base, monkeypatch)
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/1\nhttps://a.com/2\nhttps://a.com/3", "por_etapa": True,
                                           "exportar": False, "voz": "vA"}).get_json()
    ids = r["criados"]
    for pid, v in zip(ids, ["vA", "vB", "vA"]):  # cada vídeo com a sua voz
        with CT._TRAVA:
            q = CT.carregar(base, pid)
            q["config"]["voz_tts"] = v
            CT.salvar(base, q)
    assert all(CT.carregar(base, p)["link_rapido"]["aguardando"] for p in ids)  # 🕐 v84_319 continua valendo
    res = cl.post("/curtos/link/iniciar-aguardando", json={"por_etapa": True}).get_json()
    assert res["ok"] and res["por_etapa"] and res["iniciados"] == 3
    _espera(ids)
    vozes = [x[2] for x in log if x[0] == "voz"]
    assert vozes == ["vA", "vA", "vB"]  # mesma voz junta (o modelo não fica trocando)
    assert {x[1]: x[2] for x in log if x[0] == "voz"} == {ids[0]: "vA", ids[1]: "vB", ids[2]: "vA"}


def test_um_por_vez_continua_igual(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    log, junto = _falsos(base, monkeypatch)
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/1\nhttps://a.com/2", "iniciar": True, "exportar": False,
                                           "voz": "v1"}).get_json()
    assert not r.get("por_etapa")
    _espera(r["criados"])
    a, b = r["criados"]
    seq = [x[1] for x in log]
    assert seq.index(b) > max(i for i, x in enumerate(seq) if x == a)  # o 1º termina inteiro antes do 2º começar
    assert junto["max"] == 1
