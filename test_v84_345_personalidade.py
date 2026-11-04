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


def test_projeto_vazio_nao_derruba_o_roteiro(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    c = CT.criar_canal(base, "FoodYum2", "")
    CT.salvar_canal(base, c)
    _p(base, c["id"], falas=("Old hook.", "Old end."))
    ruim = os.path.join(CT.raiz(base), "projetos", "quebrado1")
    os.makedirs(ruim)
    open(os.path.join(ruim, "projeto.json"), "w").close()  # vazio: "Expecting value: line 1 column 1"
    open(os.path.join(CT.raiz(base), "projetos", "quebrado1", "x"), "w").close()
    novo = _p(base, c["id"], "personalidade")
    assert "Old hook." in CC.conteudo_roteiro(base, novo)


def test_v84_348_moldes_sem_assunto():
    import camera_exp
    for txt in list(CC.TIPOS_GANCHO.values()) + list(CC.TIPOS_FINAL.values()) + [camera_exp.REGRA_CAMERA]:
        assert "sloth" not in txt.lower() and "preguiça" not in txt.lower()
    p = {"id": "abc", "config": {}, "modelo": "comentario"}
    assert "never reuse a shape word for word" in CC.regra_tipos(p)


def test_v84_352_localizar_pro_publico():
    p_en = {"id": "a", "modelo": "comentario", "config": {}, "comentario": {"lingua_post": "en"}}
    p_pt = {"id": "b", "modelo": "comentario", "config": {"estilo_roteiro": "classico"}, "comentario": {"lingua_post": "pt"}}
    s_en, s_pt = CC.sistema(p_en), CC.sistema(p_pt)
    assert "LOCALIZE FOR THE AUDIENCE" in s_en and "English-speaking audience" in s_en and "pamonha" in s_en
    assert "Brazilian audience" in s_pt and "LOCALIZE FOR THE AUDIENCE" in s_pt  # vale em todos os estilos (até o clássico)
    expl = {"id": "c", "modelo": "explicativo", "config": {}, "comentario": {"lingua_post": "es"}}
    assert "Spanish-speaking audience" in CC.sistema(expl)


def test_v84_354_retencao_e_loop_opcional():
    base_p = {"modelo": "comentario", "comentario": {"lingua_post": "en"}}
    # sem loop: o "loop" nunca sai no sorteio dos finais, em nenhum id
    for k in range(60):
        assert CC.tipos_do_video(dict(base_p, id=f"v{k}", config={}))[1] != "loop"
    p = dict(base_p, id="a", config={})
    s = CC.sistema(p)
    assert "MAXIMUM RETENTION" in s and "CURIOSITY GAP" in s and "Do NOT write a loop ending" in s
    pl = dict(base_p, id="a", config={"final_loop": True})
    assert CC.tipos_do_video(pl)[1] == "loop" and "LOOP ENDING (asked by the creator)" in CC.sistema(pl)
    off = dict(base_p, id="a", config={"retencao": False})
    assert "MAXIMUM RETENTION" not in CC.sistema(off)
    assert "LOOP ENDING" in CC.sistema(dict(base_p, id="a", config={"retencao": False, "final_loop": True}))


def test_v84_354_envio_liga_retencao_por_padrao(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    base = str(tmp_path)
    a = cl.post("/curtos/link/novo", json={"link": "https://a.com/1"}).get_json()["criados"][0]
    b = cl.post("/curtos/link/novo", json={"link": "https://a.com/2", "retencao": False, "final_loop": True}).get_json()["criados"][0]
    ca, cb = CT.carregar(base, a)["config"], CT.carregar(base, b)["config"]
    assert ca["retencao"] is True and not ca.get("final_loop")
    assert cb["retencao"] is False and cb["final_loop"] is True
    html = cl.get("/curtos/link").get_data(as_text=True)
    assert 'id="retencao" checked' in html and 'id="final_loop" style' in html
