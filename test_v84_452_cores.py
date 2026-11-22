import thumbs_flow as tf


def test_fundo_vivo_no_prompt():
    p = tf.prompt_flow({"modo": "albert", "texto": "GADO", "prompt": "man in a herd", "estilo_arte": "rusty", "cor_fundo": "ciano"})
    assert "sky cyan" in p and "desaturated" not in p and "darker background" not in p and ";," not in p
    livre = tf.prompt_flow({"modo": "albert", "texto": "GADO", "prompt": "x", "estilo_arte": "rusty", "cor_fundo": "livre"})
    assert "desaturated" in livre and "COLORS (" not in livre
    assert "sunny yellow" in tf.prompt_flow({"modo": "albert", "texto": "GADO", "prompt": "x"})  # padrão


def test_cores_em_rodizio(monkeypatch):
    import ia_servico as ia
    monkeypatch.setattr(ia, "motivo_desligado", lambda r=None, c=None: None)
    monkeypatch.setattr(ia, "chamar", lambda *a, **k: {"thumbnails": [
        {"ideia": f"cena {i}", "texto": f"P{i}", "prompt": "s", "modo": "albert"} for i in range(3)]})
    out = tf.pedir_ideias("T", "r", [{"modo": "albert", "cor_fundo": "amarelo", "ideia": "velha", "texto": "VELHA"}], 0, "pt", albert=3)
    assert [t["cor_fundo"] for t in out] == ["ciano", "rosa", "lima"]
    assert tf.normalizar({"ideia": "a", "cor_fundo": "rosa"})["cor_fundo"] == "rosa"
