"""v84_316: marcar vídeos (descartado/postado/planejado), comentar, log, e apagar só os marcados (fica o link e o log)."""
import os

import curtos as CT
import curtos_rotas as CR
from flask import Flask


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    monkeypatch.setattr(CR, "CB", dict(CR.CB))
    apagados_editor = []
    monkeypatch.setitem(CR.CB, "apagar_editor", lambda job: apagados_editor.append(job))
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(CT.__file__), "templates"))
    CR.registrar(app, str(tmp_path))
    CR.CB["apagar_editor"] = lambda job: apagados_editor.append(job)
    return app.test_client(), apagados_editor


def _feito(base, nome, etapa="✅ pronto", com_arquivo=True):
    p = CT.criar(base, "", nome, modelo="comentario")
    pasta = CT.pasta(base, p["id"])
    os.makedirs(os.path.join(pasta, "clipes"), exist_ok=True)
    with open(os.path.join(pasta, "clipes", "a.mp4"), "wb") as f:
        f.write(b"x" * 100)
    arq = os.path.join(base, f"export_{p['id']}.mp4")
    if com_arquivo:
        with open(arq, "wb") as f:
            f.write(b"video")
    p["link_rapido"] = {"link": f"https://a.com/{nome}", "etapa": etapa, "erro": "", "criado": 1, "modo": "auto"}
    p["exportado"] = {"arquivo": arq if com_arquivo else ""}
    p["editor"] = {"job_id": "job" + p["id"][:6]}
    CT.salvar(base, p)
    return p["id"], arq


def test_marca_e_comentario_com_log(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl, _ = _app(tmp_path, monkeypatch)
    pid, _ = _feito(base, "um")
    r = cl.post(f"/curtos/link/{pid}/editar", json={"marca": "descartado"}).get_json()
    v = [x for x in r["videos"] if x["id"] == pid][0]
    assert v["marca"] == "descartado" and any("descartado" in e["texto"] for e in v["log"])
    r = cl.post(f"/curtos/link/{pid}/editar", json={"comentario": "ficou bom, mas sem legenda"}).get_json()
    v = [x for x in r["videos"] if x["id"] == pid][0]
    assert v["comentario"] == "ficou bom, mas sem legenda" and any("comentário" in e["texto"] for e in v["log"])
    assert cl.post(f"/curtos/link/{pid}/editar", json={"marca": "xxx"}).status_code == 400


def test_apagar_marcados_deixa_so_link_e_log(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl, apagados_editor = _app(tmp_path, monkeypatch)
    desc, arq_desc = _feito(base, "descartar")
    post, arq_post = _feito(base, "postar")
    plan, arq_plan = _feito(base, "planejar")
    cl.post(f"/curtos/link/{desc}/editar", json={"marca": "descartado"})
    cl.post(f"/curtos/link/{post}/editar", json={"marca": "postado"})
    cl.post(f"/curtos/link/{plan}/editar", json={"marca": "planejado"})
    r = cl.post("/curtos/link/apagar-marcados").get_json()
    assert r["ok"] and r["apagados"] == 2 and r["falhas"] == []
    assert not os.path.exists(arq_desc) and not os.path.exists(arq_post)
    assert os.path.exists(arq_plan)  # planejado fica
    assert os.path.isfile(os.path.join(CT.pasta(base, plan), "clipes", "a.mp4"))  # planejado mantém as mídias
    assert not os.path.exists(os.path.join(CT.pasta(base, desc), "clipes"))  # descartado: só o projeto.json
    assert os.listdir(CT.pasta(base, desc)) == ["projeto.json"]
    assert len(apagados_editor) == 2
    v = [x for x in r["videos"] if x["id"] == desc][0]
    assert v["apagado"] is True and v["link"] == "https://a.com/descartar" and v["pronto"] is False
    assert any("apagados" in e["texto"] for e in v["log"]) and v["marca"] == "descartado"


def test_apagado_nao_volta_pra_fila_nem_refaz(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl, _ = _app(tmp_path, monkeypatch)
    pid, _ = _feito(base, "x")
    cl.post(f"/curtos/link/{pid}/editar", json={"marca": "postado"})
    cl.post("/curtos/link/apagar-marcados")
    assert cl.post(f"/curtos/link/{pid}/refazer").status_code == 409
    estado = {x["id"]: x for x in cl.get("/curtos/link/estado").get_json()["videos"]}
    assert estado[pid]["pendente"] is False


def test_sem_marca_nada_e_apagado(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl, _ = _app(tmp_path, monkeypatch)
    pid, arq = _feito(base, "intacto")
    r = cl.post("/curtos/link/apagar-marcados").get_json()
    assert r["apagados"] == 0 and os.path.exists(arq)
