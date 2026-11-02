"""v84_318: a lista colada tem termos (Animais, radical…) e cada termo é ligado a um canal; sem termo, vale o canal do lote."""
import os

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


def test_parser_dois_pontos_opcional_e_sem_repetir():
    txt = 'Animais\nhttps://a.com/1\nhttps://a.com/2\n\nradical:\nhttps://a.com/3\nesporte: https://a.com/4\nhttps://a.com/2\n"'
    assert CR._separar_grupos(txt) == [("https://a.com/1", "Animais"), ("https://a.com/2", "Animais"),
                                       ("https://a.com/3", "radical"), ("https://a.com/4", "esporte")]


def test_termos_acentuados_casam():
    assert CR._chave_grupo("Locais Incríveis") == CR._chave_grupo("locais  incriveis") == "locais incriveis"


def test_link_novo_usa_o_canal_de_cada_termo(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    monkeypatch.setattr(CC, "baixar_clipe", lambda *a, **k: (_ for _ in ()).throw(CT.CurtoErro("parei (teste)")))
    animais = CT.criar_canal(base, "Canal Animais")
    radical = CT.criar_canal(base, "Canal Radical")
    lote = CT.criar_canal(base, "Canal do lote")
    cl.post("/curtos/link/grupos", json={"nome": "Animais", "canal_id": animais["id"]})
    cl.post("/curtos/link/grupos", json={"nome": "radical", "canal_id": radical["id"]})
    cl.post("/curtos/link/grupos", json={"nome": "animais", "canal_id": animais["id"]})  # um canal pode ter mais de um termo
    r = cl.post("/curtos/link/novo", json={"canal_id": lote["id"], "link": "Animais\nhttps://a.com/1\nradical:\nhttps://a.com/2\n"
                                                                             "Fails\nhttps://a.com/3"}).get_json()
    assert r["ok"] and len(r["criados"]) == 3
    canais = [CT.carregar(base, pid)["canal_id"] for pid in r["criados"]]
    assert canais == [animais["id"], radical["id"], lote["id"]]  # Fails não tem canal ligado: vai pro canal do lote


def test_grupos_listar_e_desligar(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    c = CT.criar_canal(base, "Canal X")
    cl.post("/curtos/link/grupos", json={"nome": "esporte:", "canal_id": c["id"]})
    grupos = cl.get("/curtos/link/grupos").get_json()["grupos"]
    assert grupos[0]["nome"] == "esporte" and grupos[0]["canal"] == "Canal X"
    cl.post("/curtos/link/grupos", json={"nome": "esporte", "canal_id": ""})
    assert cl.get("/curtos/link/grupos").get_json()["grupos"] == []
    assert cl.post("/curtos/link/grupos", json={"nome": "x", "canal_id": "naoexiste"}).status_code == 400


def test_qualquer_simbolo_separa_o_nome_do_grupo():
    txt = "Animais -\nhttps://a.com/1\n# radical\nhttps://a.com/2\n[esporte]\nhttps://a.com/3\nLocais = https://a.com/4\n"
    assert CR._separar_grupos(txt) == [("https://a.com/1", "Animais"), ("https://a.com/2", "radical"),
                                       ("https://a.com/3", "esporte"), ("https://a.com/4", "Locais")]
    assert CR._nome_do_grupo("  ~~Fails!!  ") == "Fails"
