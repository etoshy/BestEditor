"""v84_366: 🗂 o script do Google ANTIGO manda as fotos da Busca em lista pra /modelos-video/<id>/fotos-roteiro/link
("Projeto não encontrado") — agora o site reconhece o id da lista e guarda a foto lá."""
import base64
import json
import os

from flask import Flask

import busca_lista as BL
import fotos_roteiro as FR
import navegador_imagens as NI
from test_v84_293_busca_lista import _png


def test_script_antigo_cai_na_lista(tmp_path, monkeypatch):
    monkeypatch.setenv("BUSCA_LISTA_DIR", str(tmp_path / "bl"))
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))
    BL.registrar(app, str(tmp_path))
    FR.registrar(app, str(tmp_path))
    NI.registrar(app, str(tmp_path))
    c = app.test_client()
    pid = c.post("/busca-lista/novo", data={"titulo": "Poker", "termos": "Andy Beal\nPhil Ivey"}).headers["Location"].rsplit("/", 1)[-1]
    q = BL.termo_id("Andy Beal")
    corpo = {"url": "https://imageio.forbes.com/x.jpg", "pergunta": q, "origem": "guia",
             "dados_b64": base64.b64encode(_png((200, 30, 30))).decode()}
    r = c.post(f"/modelos-video/{pid}/fotos-roteiro/link", data=json.dumps(corpo), content_type="text/plain")
    assert r.status_code == 200 and r.get_json()["ok"], r.get_json()
    assert c.post(f"/modelos-video/{pid}/fotos-roteiro/link", json=corpo).get_json().get("repetida")
    assert c.post(f"/modelos-video/{pid}/fotos-roteiro/guia-feita", json={"pergunta": q, "enviadas": 1}).get_json()["ok"]
    e = c.get(f"/busca-lista/{pid}/estado").get_json()
    assert [i["arq"] for i in e["projeto"]["itens"]] == ["andy_beal_01.png"] and e["termos"][0]["fotos"] == 1
    assert c.post("/modelos-video/naoexiste99/fotos-roteiro/link", json=corpo).status_code == 404
    assert "@version      2.6.1" in NI.script()
