"""v84_437 — fontes que o site aprende + checagem que acha a frase mesmo sem o "de" igual."""
import json

import fontes_confianca as fc
import fontes_web as fw
import revisao_roteiro as rr


class R:
    def __init__(self, status=200, text="", url=""):
        self.status_code, self.text, self.url, self.headers = status, text, url, {"content-type": "text/html"}


def test_trecho_parecido_corrige_mesmo_sem_copia_igual():
    rot = "Primeiro parágrafo. O filósofo Koiakowski mostra que o projeto de conhecimento seguro era impossível em Husserl. Fim."
    d = rr.aplicar(rot, json.dumps({"trocas": [{"de": "Kołakowski mostra que o projeto de conhecimento seguro era impossível em Husserl",
                                                "para": "Kołakowski mostra que esse projeto falhou em Husserl"},
                                               {"de": "uma frase que não existe no roteiro de jeito nenhum aqui", "para": "x"}]}))
    assert d["texto"] == "Primeiro parágrafo. O filósofo Kołakowski mostra que esse projeto falhou em Husserl. Fim."
    assert len(d["nao_achadas"]) == 1 and d["aplicadas"][0]["aproximado"] > 0.8


def test_regras_candidato_e_memoria(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "BASE", str(tmp_path))
    assert fc.decidir("https://pt.wikipedia.org/wiki/X", True) == "confiar"
    assert fc.decidir("https://algum-site.com/a", False) == "candidato"
    fc.regra("fulano.substack.com", "confiar")
    assert fc.decidir("https://fulano.substack.com/p/x", False) == "confiar"
    assert fc.decidir("https://outro.substack.com/p/x", False) == "candidato"
    fc.regra("pt.wikipedia.org/wiki/ruim", "bloquear")
    assert fc.decidir("https://pt.wikipedia.org/wiki/ruim_x", True) == "bloquear"
    ok, motivo, _ = fw.conferir({"referencia": "X — Y", "url": "https://algum-site.com/x", "termos": ["X"]}, lambda u: R(200, "x", u))
    assert not ok and "candidato" in motivo
    fc.lembrar("Platão — Fédon (a preparação para a morte)", "https://plato.stanford.edu/entries/plato/")
    assert fc.lembrada("Platão — Fédon")["url"].endswith("/plato/")
    fc.registrar("https://algum-site.com/x", False, "x não é fonte confiável", "X — Y")
    s = {x["site"]: x for x in fc.todos_os_sites()}
    assert s["algum-site.com"]["falha"] == 1 and s["algum-site.com"]["decisao"] == "candidato"
    assert s["fulano.substack.com"]["decisao"] == "confiar"


def test_ia_avalia_e_libera(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "BASE", str(tmp_path))
    fc.registrar("https://revista-seria.org/artigo", False, "não é fonte confiável")
    fc.registrar("https://frases.com.br/x", False, "não é fonte confiável")
    n = fc.avaliar_com_ia(chamar=lambda *a, **k: {"sites": [
        {"site": "revista-seria.org", "tipo": "acadêmico", "nota": 9, "por_que": "revista com revisão"},
        {"site": "frases.com.br", "tipo": "frases", "nota": 8, "por_que": "x"}]})
    assert n == 2
    assert fc.decidir("https://revista-seria.org/a", False) == "confiar"
    assert fc.decidir("https://frases.com.br/a", False) == "candidato"  # tipo frases nunca entra sozinho
    r = fc.testar_todos(baixar=lambda u: R(500 if "frases" in u else 200), so=["frases.com.br", "revista-seria.org"])
    assert r == {"testados": 2, "no_ar": 1, "fora": 1}


def test_gerar_usa_o_link_lembrado(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "BASE", str(tmp_path))
    fc.lembrar("Platão — Fédon", "https://plato.stanford.edu/entries/plato/")

    def chamar(rec, system, conteudo, **k):
        return {"fontes": [{"referencia": "Platão — Fédon", "url": "https://morto.edu/fedon", "termos": ["Platão"]}]}
    r = fw.gerar("rot", chamar=chamar, baixar=lambda u: R(200, "<title>Plato</title>", u) if "stanford" in u else R(404))
    assert r["itens"][0]["url"].endswith("/plato/") and r["itens"][0].get("lembrada")


def test_pagina(monkeypatch, tmp_path):
    import app as A
    monkeypatch.setattr(fc, "BASE", str(tmp_path))
    c = A.app.test_client()
    h = c.get("/fontes-confiaveis").get_data(as_text=True)
    assert "Fontes confiáveis" in h and "plato.stanford.edu" in h
    assert c.post("/fontes-confiaveis/regra", json={"site": "fulano.substack.com", "decisao": "confiar"}).get_json()["ok"]
    assert c.post("/fontes-confiaveis/regra", json={"site": "nada", "decisao": "confiar"}).status_code == 400
    assert c.post("/fontes-confiaveis/lembrar", json={"referencia": "Platão — Fédon", "url": "https://x.edu/f"}).get_json()["ok"]
