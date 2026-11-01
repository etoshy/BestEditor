"""v84_310: acabamento por canal (legenda/@ próprios), lote com canal, retomar a fila que caiu."""
import os

import curtos as CT
import curtos_rotas as CR
from flask import Flask


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    monkeypatch.setattr(CR, "CB", dict(CR.CB))  # o registrar() zera os ganchos do app: não vazar pros outros testes
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(CT.__file__), "templates"))
    CR.registrar(app, str(tmp_path))
    return app.test_client()


def test_acabamento_do_canal_sobrepoe_o_padrao(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    cl.post("/curtos/acabamento", json={"legenda_posicao": "meio", "arroba": "@padrao"})
    c = CT.criar_canal(base, "Canal Arte")
    r = cl.post("/curtos/acabamento", json={"canal_id": c["id"], "arroba": "@arte", "legenda_posicao": "topo",
                                            "legenda_fonte": "DP Anton"}).get_json()
    assert r["ok"] and r["acabamento"]["arroba"] == "@arte"
    assert CT.acabamento(base)["arroba"] == "@padrao" and CT.acabamento(base)["legenda_posicao"] == "meio"  # padrão intacto
    assert CT.acabamento(base, c["id"])["legenda_posicao"] == "topo"
    p = CT.criar(base, c["id"], "t", modelo="comentario")
    assert p["config"]["marca"]["texto"] == "@arte" and p["config"]["legenda"]["fonte"] == "DP Anton"
    q = CT.criar(base, "", "t2", modelo="comentario")
    assert q["config"]["marca"]["texto"] == "@padrao"


def test_canais_para_o_link(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    c = CT.criar_canal(base, "Canal Dois")
    cl.post("/curtos/acabamento", json={"canal_id": c["id"], "arroba": "@dois"})
    lista = cl.get("/curtos/canais-link").get_json()["canais"]
    assert any(x["id"] == c["id"] and x["personalizado"] for x in lista)
    assert cl.post("/curtos/acabamento", json={"canal_id": "naoexiste", "arroba": "x"}).status_code == 400


def test_link_novo_usa_o_canal_escolhido(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    import curtos_comentario as CC
    monkeypatch.setattr(CC, "baixar_clipe", lambda *a, **k: (_ for _ in ()).throw(CT.CurtoErro("parei (teste)")))
    c = CT.criar_canal(base, "Lote B")
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/1", "canal_id": c["id"]}).get_json()
    assert r["ok"] and CT.carregar(base, r["criados"][0])["canal_id"] == c["id"]


def test_fila_que_caiu_e_retomada(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    p = CT.criar(base, "", "🔗 x", modelo="comentario")
    p["link_rapido"] = {"link": "https://a.com/9", "etapa": "💬 lendo os comentários", "erro": "", "criado": 1}
    CT.salvar(base, p)
    ok = CT.criar(base, "", "🔗 pronto", modelo="comentario")
    ok["link_rapido"] = {"link": "https://a.com/8", "etapa": "✅ no editor", "erro": ""}
    CT.salvar(base, ok)
    lista = cl.get("/curtos/link/estado").get_json()["videos"]
    marcados = {v["id"]: v["pendente"] for v in lista}
    assert marcados[p["id"]] is True and marcados[ok["id"]] is False


def test_marca_ligada_a_legenda():
    import marca_canal as MC
    # legenda no terço (0.76): o @ 10% acima dela → 0.66 da altura; em px (26 px de 260) → 0.66 também
    cfg = {"posicao": "legenda", "lado": "acima", "distancia": 0.10}
    an, x, y = MC.ponto(cfg, 1000, 1000, "terco", MC.centro_legenda({"posicao": "terco"}))
    assert an == 5 and y == 660
    an, x, y = MC.ponto({"posicao": "legenda", "lado": "abaixo", "distancia_px": 50}, 1000, 1000, "", 0.5)
    assert y == 550
    assert MC.centro_legenda({"posicao": "terco", "altura": 0.3}) == 0.3
    assert MC.centro_legenda(None) is None
    # desligado (padrão): continua no meio, como era
    assert MC.ponto({"posicao": "meio"}, 1000, 1000)[2] == 500


def test_acabamento_marca_posicao(tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    a = CT.salvar_acabamento(base, {"marca_posicao": "legenda", "marca_lado": "acima", "marca_distancia": 12})
    assert a["marca_posicao"] == "legenda" and a["marca_distancia"] == 12
    p = CT.criar(base, "", "t", modelo="comentario")
    m = p["config"]["marca"]
    assert m["posicao"] == "legenda" and m["lado"] == "acima" and abs(m["distancia"] - 0.12) < 1e-6
    CT.salvar_acabamento(base, {"marca_posicao": "", "marca_px": 30})  # de volta ao padrão
    assert CT.normalizar_marca({"posicao": "legenda", "distancia_px": 30})["distancia_px"] == 30
