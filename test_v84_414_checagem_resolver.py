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


def test_gemini_sem_cota_cai_pro_claude_com_internet(monkeypatch):
    import gemini_servico as gm
    import ia_servico as ia
    monkeypatch.setattr(gm, "chave", lambda c=None: "k")
    monkeypatch.setattr(gm, "checar", lambda *a, **k: (_ for _ in ()).throw(gm.GeminiErro("passou do limite")))
    monkeypatch.setattr(ia, "motivo_desligado", lambda r, c=None: None)
    pedidos = {}
    monkeypatch.setattr(ia, "chamar", lambda *a, **k: pedidos.update(k) or '{"correcoes": []}')
    t, quem = cr.chamar_ia("p", "auto", "x")
    assert quem == "ia_site" and pedidos.get("web") is True
    monkeypatch.setattr(ia, "chamar", lambda *a, **k: None)
    import pytest
    with pytest.raises(RuntimeError) as e:
        cr.chamar_ia("p", "auto", "x")
    assert "Gemini" in str(e.value) and "📋" in str(e.value)


def test_web_search_vai_no_pedido_da_anthropic(monkeypatch):
    import ia_servico as ia
    visto = {}
    monkeypatch.setattr(ia, "motivo_desligado", lambda r, c=None: None)
    monkeypatch.setattr(ia, "chaves_candidatas", lambda c=None: [("salva", "sk")])
    monkeypatch.setattr(ia, "_transporte", lambda payload, k, t: (visto.update(payload) or 200,
                        {"content": [{"type": "text", "text": "oi"}], "usage": {"server_tool_use": {"web_search_requests": 2}}}))
    assert ia.chamar("roteiros", "s", "c", web=True, cache_local=False) == "oi"
    assert visto["tools"][0]["type"] == "web_search_20250305"


def test_prompt_e_colar_resposta(monkeypatch):
    import app as A
    import dossies as ds
    p = ds.criar(A.BASE_DIR, tema="Teste colar")
    p["resultado"] = {"roteiro": "Começo.\n\nEm 1990, 30% das pessoas usavam isso.\n\nFim."}
    p["checagem"] = {"verificar": [{"afirmacao": "Em 1990, 30% das pessoas usavam isso", "conferido": False},
                                   {"afirmacao": "Algo confirmado", "conferido": True, "status_web": "confirmado"}]}
    ds.salvar(A.BASE_DIR, p)
    c = A.app.test_client()
    try:
        d = c.post(f"/checagem/dossie/{p['id']}/resolver/prompt", json={"pendentes": True, "acao": "auto"}).get_json()
        assert d["itens"] == [0] and "### V1" in d["prompt"] and "Algo confirmado" not in d["prompt"].split("## Roteiro")[0]
        resp = json.dumps({"correcoes": [{"item": "V1", "de": "Em 1990, 30% das pessoas usavam isso.",
                                          "para": "Em 1990, 30% das pessoas usavam isso; em 2023, eram 55%.",
                                          "status": "atualizado", "fonte": "https://exemplo.org"}]})
        r = c.post(f"/checagem/dossie/{p['id']}/resolver/ler", json={"itens": d["itens"], "acao": "auto", "texto": resp}).get_json()
        assert r["aplicadas"] == 1 and r["itens"] == [0]
        q = ds.carregar(A.BASE_DIR, p["id"])
        assert "em 2023, eram 55%" in q["resultado"]["roteiro"] and q["checagem"]["verificar"][0]["status_web"] == "atualizado"
    finally:
        ds.excluir(A.BASE_DIR, p["id"])
