"""v84_235: 📊 modelar títulos e capas no estilo de um canal do Analisador — o canal escolhido entra em TODOS os pedidos
à IA da Publicação, e as thumbs dele viram modelo pro ✏️ desenho."""
import io

import pytest
from PIL import Image

import publicacao as pub
from test_v84_229_publicacao import cena  # noqa: F401

ANALISE = {"id": "can1", "url": "https://youtube.com/@x", "canal": {"nome": "Kanal X"}, "criado": 1, "estado": "pronto",
           "videos": {"a1": {"titulo": "Das passiert WIRKLICH im Schwarzen Loch", "views": 900000, "thumb": "https://i.ytimg.com/vi/a1/hqdefault.jpg"},
                      "b2": {"titulo": "Kleiner Titel", "views": 1000, "thumb": "https://i.ytimg.com/vi/b2/hqdefault.jpg"}},
           "ia": {"titulos": {"formulas": [{"formula": "Das passiert WIRKLICH [X]", "desempenho": "3x mediana"}], "funcionam": ["CAPS numa palavra"]},
                  "thumbs": {"estilo": "rosto + objeto", "receita": "fundo escuro, 2 palavras amarelas", "funcionam": ["seta vermelha"]}}}


@pytest.fixture
def canal(monkeypatch):
    import analisador_canal as ac
    monkeypatch.setattr(ac, "carregar", lambda base, aid: ANALISE if aid == "can1" else (_ for _ in ()).throw(ac.AnaliseError("x")))
    monkeypatch.setattr(ac, "listar", lambda base: [{"id": "can1", "nome": "Kanal X", "n_videos": 2, "tem_ia": True},
                                                    {"id": "vazio", "nome": "V", "n_videos": 0}])


def test_estilo_canal_em_tudo(cena, canal):  # noqa: F811
    A, jid, falso, gal, chamadas = cena
    c = A.app.test_client()
    assert [x["id"] for x in c.get(f"/job/{jid}/publicacao/canais").get_json()["canais"]] == ["can1"]
    assert c.post(f"/job/{jid}/publicacao/canal_estilo", json={"aid": "nao"}).status_code == 400
    d = c.post(f"/job/{jid}/publicacao/canal_estilo", json={"aid": "can1"}).get_json()
    e = d["canal_estilo"]
    assert e["nome"] == "Kanal X" and e["thumbs"][0]["id"] == "a1" and e["formulas"] == ["Das passiert WIRKLICH [X]"]
    c.post(f"/job/{jid}/publicacao/textos", json={"tipos": ["titulos"]})
    assert "MODELE NO ESTILO DO CANAL “Kanal X”" in chamadas[-1] and "Das passiert WIRKLICH im Schwarzen Loch" in chamadas[-1]
    assert "2 palavras amarelas" in chamadas[-1] and chamadas[-1].index("MODELE") < chamadas[-1].index("NARRAÇÃO")
    c.post(f"/job/{jid}/publicacao/capas/ideias", json={})
    assert "Das passiert WIRKLICH [X]" in chamadas[-1]
    # tira o canal → some dos pedidos
    d = c.post(f"/job/{jid}/publicacao/canal_estilo", json={"aid": ""}).get_json()
    assert d["canal_estilo"] is None
    c.post(f"/job/{jid}/publicacao/textos", json={"tipos": ["titulos"]})
    assert "MODELE" not in chamadas[-1]


def test_thumb_do_canal_vira_modelo(cena, canal, monkeypatch, tmp_path):  # noqa: F811
    import ia_servico
    A, jid, falso, gal, chamadas = cena
    b = io.BytesIO()
    Image.new("RGB", (1280, 720), (90, 10, 10)).save(b, "JPEG")
    urls = []

    def baixar(url):
        urls.append(url)
        if "maxres" in url:
            raise OSError("404")
        return b.getvalue()
    orig = pub.baixar_thumb_canal
    monkeypatch.setattr(pub, "baixar_thumb_canal", lambda *a, **k: orig(*a, baixar=baixar))
    monkeypatch.setattr(ia_servico, "chamar", lambda *a, **k: {"itens": [{"papel": "coisa", "forma": "ret", "x0": .1, "y0": .1, "x1": .5, "y1": .9,
                                                                          "original": "buraco", "nosso": ""}], "graficos": [],
                                                               "texto": {"original": ""}, "fundo": {"original": "", "nosso": ""}, "estilo": "escuro"})
    c = A.app.test_client()
    c.post(f"/job/{jid}/publicacao/canal_estilo", json={"aid": "can1"})
    d = c.post(f"/job/{jid}/publicacao/capas/copiar_modelo", data={"video_id": "a1"}, content_type="multipart/form-data").get_json()
    assert d["modelo"]["itens"][0]["dica"] == "buraco" and urls[:2] == ["https://i.ytimg.com/vi/a1/maxresdefault.jpg",
                                                                        "https://i.ytimg.com/vi/a1/sddefault.jpg"]
    assert c.get(d["modelo"]["url_guia"]).status_code == 200
    r = c.post(f"/job/{jid}/publicacao/capas/copiar_modelo", data={"video_id": "zz"}, content_type="multipart/form-data")
    assert r.status_code == 400
