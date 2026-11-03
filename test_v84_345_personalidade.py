"""v84_345: 🎭 roteiro com mais personalidade (desligado por padrão) — persona do canal, opinião, sem repetir os recentes."""
import curtos as CT
import curtos_comentario as CC
from test_v84_320_lote_por_etapa import _app, _espera, _falsos


def _p(base, cid, estilo=None, falas=("Hook line here.", "Ending line here.")):
    p = CT.criar(base, cid, "t", modelo="comentario")
    if estilo:
        p["config"]["estilo_roteiro"] = estilo
    p["roteiro"] = {"idioma": "en", "blocos": [{"id": f"B{k}", "fala": f, "fala_en": f} for k, f in enumerate(falas, 1)]}
    CT.salvar(base, p)
    return CT.carregar(base, p["id"])


def test_padrao_continua_autentico_e_o_modo_novo(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    c = CT.criar_canal(base, "FoodYum2", "")
    c["descricao"] = "Comida de rua do mundo"
    c["persona"] = "cético, humor seco, compara tudo com feira de domingo"
    CT.salvar_canal(base, c)
    velho = _p(base, c["id"], falas=("Nobody can eat this in one bite.", "Would you try it?"))
    normal = _p(base, c["id"])
    assert CC.estilo_roteiro(normal) == "autentico" and "PERSONALITY MODE" not in CC.sistema(normal)
    novo = _p(base, c["id"], "personalidade")
    sis = CC.sistema(novo)
    assert "AUTHENTIC MODE" in sis and "PERSONALITY MODE" in sis and "NEVER invent biography" in sis
    cont = CC.conteudo_roteiro(base, novo)
    assert "## CHANNEL PERSONA" in cont and "feira de domingo" in cont
    assert "Nobody can eat this in one bite." in cont and "RECENT SCRIPTS" in cont  # o que não repetir
    assert "HOOK TYPE" in cont  # os tipos de gancho/final continuam
    assert CC.estilo_roteiro(_p(base, c["id"], "classico")) == "classico"
    # sem persona escrita: deduz da descrição
    c["persona"] = ""
    CT.salvar_canal(base, c)
    assert "Comida de rua do mundo" in CC.conteudo_roteiro(base, novo)


def test_link_e_canal(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    base = str(tmp_path)
    _falsos(base, monkeypatch)
    cid = cl.post("/curtos/canais/novo", json={"nome": "A"}).get_json()["id"]
    j = cl.post(f"/curtos/canais/{cid}/editar", json={"persona": "fala como amigo no zap"}).get_json()
    assert next(x for x in j["canais"] if x["id"] == cid)["persona"] == "fala como amigo no zap"
    r1 = cl.post("/curtos/link/novo", json={"link": "https://a.com/1", "exportar": False}).get_json()
    r2 = cl.post("/curtos/link/novo", json={"link": "https://a.com/2", "exportar": False, "roteiro_personalidade": True}).get_json()
    assert CT.carregar(base, r1["criados"][0])["config"]["estilo_roteiro"] == "autentico"  # desligado por padrão
    assert CT.carregar(base, r2["criados"][0])["config"]["estilo_roteiro"] == "personalidade"
    html = cl.get("/curtos/link").get_data(as_text=True)
    assert 'id="roteiro_personalidade"' in html and 'id="c_persona"' in html
    assert 'id="roteiro_personalidade" style="width:auto;margin:0"> ' in html  # sem "checked"
