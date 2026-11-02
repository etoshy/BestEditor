"""v84_317: ⭐ escolher título e capa por vídeo, e exportar roteiro + título + capa (ZIP com JSON ou só JSON)."""
import io
import json
import os
import zipfile

import curtos as CT
import curtos_rotas as CR
from flask import Flask


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    monkeypatch.setattr(CR, "CB", dict(CR.CB))
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(CT.__file__), "templates"))
    CR.registrar(app, str(tmp_path))
    return app.test_client()


def _video(base, nome, com_capa=True):
    p = CT.criar(base, "", nome, modelo="comentario")
    pasta = CT.pasta(base, p["id"])
    os.makedirs(os.path.join(pasta, "thumbs"), exist_ok=True)
    p["link_rapido"] = {"link": f"https://a.com/{nome}", "etapa": "✅ no editor", "erro": "", "criado": 1, "modo": "auto"}
    p["roteiro"] = {"blocos": [{"fala": "[suspense] Ele achou algo estranho."}, {"fala": "Ninguém esperava."}],
                    "hashtags": ["#arte"], "descricao": "Uma descrição."}
    p["thumbs"] = [{"arquivo": "t1.jpg", "por_que": "rosto em destaque"}, {"arquivo": "t2.jpg", "por_que": "cor forte"}]
    for t in p["thumbs"]:
        with open(os.path.join(pasta, "thumbs", t["arquivo"]), "wb") as f:
            f.write(b"\xff\xd8img")
    CT.salvar(base, p)
    return p["id"]


def test_escolha_titulo_e_capa_fica_salva(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    pid = _video(base, "um")
    r = cl.post(f"/curtos/link/{pid}/escolha", json={"titulo": "  Título   escolhido ", "capa": 2}).get_json()
    v = [x for x in r["videos"] if x["id"] == pid][0]
    assert v["escolha"] == {"titulo": "Título escolhido", "capa": 2}
    assert cl.post(f"/curtos/link/{pid}/escolha", json={"capa": 9}).status_code == 400  # capa que não existe
    r = cl.post(f"/curtos/link/{pid}/escolha", json={"capa": None}).get_json()
    assert "capa" not in [x for x in r["videos"] if x["id"] == pid][0]["escolha"]


def test_exporta_zip_com_json_e_capa(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    pid = _video(base, "um")
    _video(base, "sem escolha")
    cl.post(f"/curtos/link/{pid}/escolha", json={"titulo": "Meu título", "capa": 1})
    resp = cl.get("/curtos/link/exportar-escolhidos?formato=zip")
    assert resp.status_code == 200 and resp.mimetype == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(resp.data))
    nomes = set(z.namelist())
    assert "pacote.json" in nomes and f"capas/{pid}_1.jpg" in nomes
    pacote = json.loads(z.read("pacote.json").decode("utf-8"))
    assert pacote["total"] == 1
    v = pacote["videos"][0]
    assert v["id"] == pid and v["titulo_escolhido"] == "Meu título"
    assert v["roteiro"] == "Ele achou algo estranho. Ninguém esperava."  # sem as tags de atuação
    assert "[suspense]" in v["roteiro_com_tags"]
    assert v["capa"]["arquivo"] == f"capas/{pid}_1.jpg" and v["capa"]["por_que"] == "rosto em destaque"
    assert v["link"] == "https://a.com/um" and v["hashtags"] == ["#arte"]


def test_exporta_so_json_sem_imagens(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    pid = _video(base, "um")
    cl.post(f"/curtos/link/{pid}/escolha", json={"capa": 2})
    resp = cl.get("/curtos/link/exportar-escolhidos?formato=json")
    assert resp.mimetype == "application/json"
    dados = json.loads(resp.data.decode("utf-8"))
    assert dados["total"] == 1 and dados["videos"][0]["capa"]["arquivo"] == f"capas/{pid}_2.jpg"


def test_sem_escolha_nao_exporta_nada(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    _video(base, "um")
    dados = json.loads(cl.get("/curtos/link/exportar-escolhidos?formato=json").data.decode("utf-8"))
    assert dados["total"] == 0
