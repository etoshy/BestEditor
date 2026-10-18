"""v84_171: 🎬 direção "True crime investigativo" no editor + direcao.json (opcional) no pacote do canal."""
import io
import json
import zipfile

import numpy  # noqa: F401

import direcoes_canais as dc
import dossies as ds
import dp_direcao
from test_v84_168_marca import pacote_zip

DIRECAO = {"nome": "🎨 Canal Teste — noir", "ritmo": "calmo",
           "cores": {"ativa": True, "modo": "predef", "primaria": "#E8DDC5", "secundaria": "#080807", "acento": "#C51F27"},
           "efeitos": {"pct": 70, "itens": [{"id": "zoom_respiro", "peso": 4}, {"id": "nao_existe", "peso": 9}]},
           "transicoes": {"pct": 30, "itens": [{"id": "book_flip", "peso": 2}]},
           "destaques": {"ativo": True, "densidade": "equilibrado", "estilos": ["recorte", "inventado"]}}


def test_true_crime_no_editor():
    d = dp_direcao.direcao("sys_true_crime")
    assert d and d["nome"].startswith("True crime investigativo")
    for eixo in ("filtros", "efeitos", "transicoes", "entradas", "templates"):  # sobra algo mesmo sem o pacote de extras
        assert d[eixo]["itens"], eixo
    assert ds.MODELOS["true_crime"]["direcao_sugerida"] == "sys_true_crime"


def test_direcao_do_pacote():
    x = dc._so_o_que_existe(dc.direcao_de_pacote(DIRECAO, "canal_teste", "Canal Teste"))
    assert x["id"] == "marca_canal_teste" and x["ritmo"] == "calmo" and x["sistema"]
    assert [i["id"] for i in x["efeitos"]["itens"]] == ["zoom_respiro"] and x["destaques"]["estilos"] == ["recorte"]
    assert x["templates"] == {"pct": 0, "itens": []}  # o que faltou é completado


def test_importar_pacote_com_direcao():
    import app as a
    S = "canal_teste_direcao"
    z = zipfile.ZipFile(io.BytesIO(pacote_zip(S)))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for n in z.namelist():
            out.writestr(n, z.read(n))
        out.writestr(f"{S}/direcao.json", json.dumps(DIRECAO, ensure_ascii=False))
    c = a.app.test_client()
    r = c.post("/marca/importar", data={"zip": (io.BytesIO(buf.getvalue()), "p.zip")}, content_type="multipart/form-data")
    assert r.status_code == 302
    try:
        assert dp_direcao.direcao("marca_" + S)["nome"] == "🎨 Canal Teste — noir"
        assert ds.MODELOS["marca_canal_teste"]["direcao_sugerida"] == "marca_" + S
        assert "Direção no editor" in c.get(f"/marca/{S}").get_data(as_text=True)
        h = c.get("/marca/como-montar").get_data(as_text=True)
        assert "direcao.json" in h and "sys_true_crime" in h
    finally:
        c.post(f"/marca/{S}/excluir")
    assert dp_direcao.direcao("marca_" + S) is None
