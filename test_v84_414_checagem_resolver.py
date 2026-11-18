"""v84_414 — o que a checagem não confirmou: atualizar / caso equivalente / hipotético / tirar / manter."""
import json

import checagem_resolver as cr


def test_politica_auto_entra_no_prompt_da_internet(monkeypatch):
    import checagem_roteiro as ch
    monkeypatch.setattr(cr, "politica", lambda cfg=None: "auto")
    t = ch.prompt_web("Em 1985 morreram 100 mil pessoas.\n\nOutro parágrafo.",
                      ultima={"verificar": [{"afirmacao": "Em 1985 morreram 100 mil pessoas"}]})
    assert "20 a 30 anos" in t and "\"atualizado\"" in t and "\"trocado\"" in t and "hipotetico" in t
    monkeypatch.setattr(cr, "politica", lambda cfg=None: "suavizar")
    t = ch.prompt_web("Em 1985 morreram 100 mil pessoas.", ultima={"verificar": [{"afirmacao": "Em 1985 morreram 100 mil"}]})
    assert "suavize" in t


def test_prompt_resolver_e_leitura():
    rot = "Primeiro parágrafo.\n\nUma estudante de medicina viu o chefe operar sem anestesia.\n\nTerceiro."
    p = cr.prompt_resolver(rot, [(1, {"afirmacao": "Uma estudante de medicina viu o chefe operar sem anestesia"})], "hipotetico")
    assert "### V2" in p and "Imagine" in p and "Uma estudante de medicina" in p
    out = cr.ler(json.dumps({"correcoes": [{"item": "V2", "de": "Uma estudante", "para": "Imagine uma estudante",
                                            "status": "hipotetico"}, {"item": "V3", "de": "x", "para": None}]}))
    assert len(out) == 1 and out[0]["status"] == "hipotetico"


def test_rota_resolver(monkeypatch):
    import app as A
    import thumbs_tts_rotas  # noqa: F401
    import dossies as ds
    p = ds.criar(A.BASE_DIR, tema="Teste resolver")
    texto = "Começo do vídeo.\n\nUma estudante de medicina viu o chefe operar sem anestesia.\n\nFim do vídeo."
    p["resultado"] = {"roteiro": texto}
    p["checagem"] = {"verificar": [{"afirmacao": "Uma estudante de medicina viu o chefe operar sem anestesia",
                                    "conferido": True, "status_web": "sem_fonte"}]}
    ds.salvar(A.BASE_DIR, p)
    monkeypatch.setattr(cr, "chamar_ia", lambda pr, acao, rot: (json.dumps({"correcoes": [
        {"item": "V1", "de": "Uma estudante de medicina viu o chefe operar sem anestesia.",
         "para": "Imagine uma estudante de medicina vendo o chefe operar sem anestesia.", "status": "hipotetico"}]}), "ia_site"))
    c = A.app.test_client()
    try:
        r = c.post(f"/checagem/dossie/{p['id']}/resolver", json={"itens": [0], "acao": "hipotetico"})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["aplicadas"] == 1
        q = ds.carregar(A.BASE_DIR, p["id"])
        assert "Imagine uma estudante" in q["resultado"]["roteiro"]
        assert q["checagem"]["verificar"][0]["status_web"] == "hipotetico"
        r = c.post(f"/checagem/dossie/{p['id']}/resolver", json={"itens": [0], "acao": "manter"})
        assert ds.carregar(A.BASE_DIR, p["id"])["checagem"]["verificar"][0]["status_web"] == "mantido"
        assert c.get("/checagem/politica").get_json()["politica"] in cr.POLITICAS
    finally:
        ds.excluir(A.BASE_DIR, p["id"])
