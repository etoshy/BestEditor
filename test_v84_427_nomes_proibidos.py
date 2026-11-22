"""v84_427 — nomes que nunca entram no roteiro (ex.: o autor da aula), inclusive pela checagem."""
import metodo_roteiro as mr


def test_tira_as_atribuicoes_dos_roteiros_reais():
    n = ["Olavo de Carvalho"]
    casos = {
        "Aqui no CenarioM, partimos de uma tese defendida por Olavo de Carvalho: a filosofia não se aprende só em livros.":
            "Aqui no CenarioM, partimos de uma tese: a filosofia não se aprende só em livros.",
        "Ainda assim, segundo a leitura de Olavo de Carvalho, quando comparamos o alcance dele, a diferença aparece.":
            "Ainda assim, quando comparamos o alcance dele, a diferença aparece.",
        "Segundo a distinção filosófica retomada por Olavo de Carvalho, a partir de Santo Anselmo, a verdade está no real.":
            "Segundo a distinção filosófica, a partir de Santo Anselmo, a verdade está no real.",
        "Mas porque, segundo Olavo de Carvalho, faltaram-lhe mestres.": "Mas porque, faltaram-lhe mestres.",
    }
    for antes, depois in casos.items():
        t, restos = mr.tirar_nomes(antes, n)
        assert t == depois and not restos
    t, restos = mr.tirar_nomes("Olavo de Carvalho dizia que a filosofia é viva.", n)
    assert t == "Há quem diga que a filosofia é viva." and not restos  # v84_444: tira também quando é o sujeito


def test_regra_vai_em_todo_pedido_de_texto(monkeypatch):
    import ia_servico as ia
    visto = {}
    monkeypatch.setattr(mr, "nomes_proibidos", lambda cfg=None: ["Olavo de Carvalho"])
    monkeypatch.setattr(ia, "_transporte", lambda payload, k, t: (visto.update(payload) or 200,
                        {"content": [{"type": "text", "text": "ok"}], "usage": {}}))
    monkeypatch.setattr(ia, "_registrar", lambda *a, **k: None)
    cfg = dict(ia.config(), ativo=True, chave="sk-ant-x", texto_via="api")
    monkeypatch.setattr(ia, "config", lambda: cfg)
    ia.chamar("roteiros", "Você é o checador.", "texto", cache_local=False)
    assert "NOMES PROIBIDOS" in visto["system"][0]["text"] and "Olavo de Carvalho" in visto["system"][0]["text"]
    ia.chamar("juiz", "Você é o juiz.", "texto", cache_local=False)
    assert "NOMES PROIBIDOS" not in visto["system"][0]["text"]


def test_lista_do_site_e_do_projeto(monkeypatch):
    import site_config
    monkeypatch.setattr(site_config, "load_site_config", lambda: {"nomes_proibidos": "Fulano de Tal, Ciclano"})
    assert mr.nomes_proibidos({"nao_citar": ["Beltrano"]}) == ["Fulano de Tal", "Ciclano", "Beltrano"]


def test_parte_e_resultado_limpam(monkeypatch):
    import roteiro_partes as rp
    monkeypatch.setattr(mr, "nomes_proibidos", lambda cfg=None: ["Olavo de Carvalho"])
    assert "Olavo" not in rp.ler_parte("Segundo Olavo de Carvalho, a filosofia é viva.", {"titulo": "x"})


def test_v84_444_todas_as_formas_do_nome():
    n = ["Olavo de Carvalho"]
    casos = ["Na interpretação de Olavo de Carvalho, a ciência recorta.",
             "Conforme essa interpretação atribuída a Olavo de Carvalho na aula de 13 de junho de 2009, um grupo ocupou.",
             "Olavo recorre a Antonio Gramsci, e isso é interpretação de Olavo.",
             "Para Olavo, a palavra remeteria. A tese de Olavo de Carvalho parte da ideia."]
    for c in casos:
        t, restos = mr.tirar_nomes(c, n)
        assert "Olavo" not in t and not restos, t
    assert "Olavo Bilac" in mr.tirar_nomes("O poeta Olavo Bilac escreveu.", n)[0]


def test_v84_444_checagem_aplicada_tambem_tira():
    import json
    import revisao_roteiro as rr
    d = rr.aplicar("Uma ideia forte sobre a ciência aqui.", json.dumps({"trocas": [
        {"de": "Uma ideia forte sobre a ciência aqui.", "para": "Segundo Olavo de Carvalho, uma ideia forte sobre a ciência aqui."}]}))
    assert "Olavo" not in d["texto"]
