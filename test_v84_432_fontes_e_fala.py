"""v84_432 — correção do roteiro (bastidor, retorno da imagem, checagem que substitui) + fontes confiáveis na descrição."""
import fontes_web as fw
import metodo_roteiro as mr


class R:
    def __init__(self, status=200, text="", url="", ct="text/html"):
        self.status_code, self.text, self.url, self.headers = status, text, url, {"content-type": ct}


def test_tira_o_bastidor_da_fala():
    t = mr.tirar_meta_fonte("Lembra daquela voz que, no fim da parte anterior, perguntava? A partir daí, o roteiro propõe "
                            "uma interpretação: quando você cai. Esse é o ponto que a parte seguinte vai desdobrar.")
    assert "parte" not in t and "roteiro" not in t
    assert "que, agora há pouco, perguntava" in t and "uma leitura possível:" in t and "o ponto que vamos desdobrar" in t
    assert mr.tirar_bastidor("Texto normal. sem mudança") == "Texto normal. sem mudança"


def test_regras_no_prompt_e_na_checagem():
    import checagem_resolver as cr
    import dossies as ds
    assert "IMAGEM QUE VOLTA" in ds.REGRA_FALA and "Lembra de" in ds.REGRA_FALA and "página" in ds.REGRA_FALA
    for pol in ("auto", "suavizar", "tirar"):
        assert "SUBSTITUI" in cr.regra_sem_fonte(pol, True)


def test_so_sites_confiaveis():
    assert fw.confiavel("pt.wikipedia.org") and fw.confiavel("plato.stanford.edu") and fw.confiavel("www.usp.br")
    assert not fw.confiavel("www.pensador.com") and not fw.confiavel("algum.blogspot.com")
    ok, motivo, _ = fw.conferir({"referencia": "X", "url": "https://frases.blogspot.com/lavelle", "termos": ["Lavelle"]},
                                lambda u: R(200, "<title>Lavelle</title>Lavelle"))
    assert not ok and "confiável" in motivo


def test_conferir_link():
    f = {"referencia": "Louis Lavelle — De l'intimité spirituelle", "url": "https://fr.wikipedia.org/wiki/Louis_Lavelle",
         "termos": ["Lavelle", "intimité"]}
    assert fw.conferir(f, lambda u: R(200, "<title>Louis Lavelle</title> philosophe français …", u))[0]
    assert not fw.conferir(f, lambda u: R(404))[0]
    assert not fw.conferir(f, lambda u: R(200, "<title>Page not found</title>", u))[0]
    assert not fw.conferir(f, lambda u: R(200, "<title>Home</title> Lavelle", "https://fr.wikipedia.org/"))[0]
    assert not fw.conferir(dict(f, termos=["Machado", "Castilla", "Retrato"]),
                           lambda u: R(200, "<title>Louis Lavelle</title> Machado", u))[0]  # não fala do assunto
    assert not fw.conferir(dict(f, url="https://www.youtube.com/watch?v=x"), lambda u: R(200))[0]


def test_gerar_procura_de_novo_o_que_falhou_e_bloco():
    chamadas = []

    def chamar(rec, system, conteudo, **k):
        chamadas.append(conteudo)
        assert k.get("web") and "CONFIÁVEL" in system and "Olavo" in system
        if "NÃO SERVEM" in conteudo:
            return {"fontes": [{"referencia": "Platão — Fédon", "url": "https://plato.stanford.edu/entries/plato/",
                                "termos": ["Plato", "Phaedo"]}]}
        return {"fontes": [{"referencia": "Platão — Fédon", "url": "https://site-morto.edu/fedon", "termos": ["Fédon"]},
                           {"referencia": "Antonio Machado — «Retrato», Campos de Castilla",
                            "url": "https://es.wikipedia.org/wiki/Campos_de_Castilla", "termos": ["Machado", "Castilla"]}]}

    def baixar(u):
        if "morto" in u:
            return R(404)
        return R(200, "<title>Campos de Castilla</title> Antonio Machado" if "Castilla" in u else
                 "<title>Plato</title> Phaedo dialogue", u)
    r = fw.gerar("roteiro", "T", ["Olavo de Carvalho"], chamar=chamar, baixar=baixar)
    assert len(chamadas) == 2 and [i["referencia"] for i in r["itens"]] == [
        "Antonio Machado — «Retrato», Campos de Castilla", "Platão — Fédon"]
    assert not r["sem_link"]
    b = fw.bloco(r)
    assert b.startswith("📚 Fontes e referências:") and "plato.stanford.edu" in b


def test_descricao_tem_as_fontes_e_nao_os_arquivos():
    import dossies as ds
    p = {"resultado": {"descricao": "Desc", "fontes_web": {"itens": [{"referencia": "Platão — Fédon", "url": "https://x.edu/f"}]}},
         "fontes": [{"id": "F1", "titulo": "notas_t1.md", "arquivo": "F1_notas_t1.md"},
                    {"id": "F2", "titulo": "Matéria", "url": "https://bbc.com/a", "site": "BBC"}]}
    d = ds.descricao_completa(p)
    assert "notas_t1" not in d and "https://bbc.com/a" in d and "📚 Fontes e referências:\n- Platão — Fédon: https://x.edu/f" in d


def test_recurso_registrado():
    import ia_servico as ia
    assert ia.RECURSOS["fontes_descricao"][2] is True


def test_v84_436_nome_em_outra_lingua_e_termos_traduzidos():
    f = {"referencia": "Espinosa — Ética (imaginação e conhecimento racional)", "url": "https://plato.stanford.edu/entries/spinoza/",
         "termos": ["Espinosa", "imaginação", "conhecimento racional"]}
    assert fw.conferir(f, lambda u: R(200, "<title>Baruch Spinoza (Stanford Encyclopedia)</title> Spinoza's Ethics", u))[0]
    g = {"referencia": "George Berkeley — Tratado sobre os princípios do conhecimento humano", "termos": ["Berkeley", "ideias"],
         "url": "https://en.wikipedia.org/wiki/A_Treatise_Concerning_the_Principles_of_Human_Knowledge"}
    assert fw.conferir(g, lambda u: R(200, "<title>A Treatise Concerning the Principles of Human Knowledge</title> "
                                          "a work by George Berkeley. Berkeley argues… Berkeley", u))[0]


def test_v84_436_sem_link_vai_pra_wikipedia():
    import json

    class J(R):
        def json(self):
            return json.loads(self.text)

    def chamar(rec, system, conteudo, **k):
        return {"fontes": [{"referencia": "René Descartes — Meditações Metafísicas (dúvida metódica)",
                            "url": "https://morto.edu/x", "termos": ["Descartes"]}]}

    def baixar(u):
        if "opensearch" in u and "pt.wikipedia" in u:
            return J(200, json.dumps(["Meditações Metafísicas", ["Meditações sobre Filosofia Primeira"], [""],
                                      ["https://pt.wikipedia.org/wiki/Medita%C3%A7%C3%B5es_sobre_Filosofia_Primeira"]]))
        if "Filosofia_Primeira" in u:
            return R(200, "<title>Meditações sobre Filosofia Primeira – Wikipédia</title> Meditações Metafísicas de Descartes", u)
        return R(404)
    r = fw.gerar("rot", "T", chamar=chamar, baixar=baixar)
    assert r["itens"] and "Filosofia_Primeira" in r["itens"][0]["url"] and not r["sem_link"]


def test_v84_440_um_comentario_e_mais_bastidor():
    t = "A.\n\nComenta aí, nos comentários: x\n\nB.\n\nComplete esta frase nos comentários: z\n\nE você? Conta nos comentários."
    novo, tirados = mr.uma_chamada_comentario(t)
    assert novo == "A.\n\nB.\n\nE você? Conta nos comentários." and len(tirados) == 2
    s = mr.tirar_meta_fonte("O que isso acrescenta à pergunta do título é o seguinte: a cultura perde. Voltando ao título: será?")
    assert "título" not in s and s.startswith("A cultura perde")
    import dossies as ds
    assert "náufrago" not in ds.REGRA_FALA and "UM GANCHO SÓ" in ds.REGRA_FALA
