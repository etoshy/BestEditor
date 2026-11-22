import json

import checagem_resolver as cr
import checagem_roteiro as ch
import ia_servico as ia
import thumbs_flow as tf


def test_completa_as_que_faltam(monkeypatch):
    monkeypatch.setattr(ia, "motivo_desligado", lambda r=None, c=None: None)
    chamadas = []

    def chamar(rec, system, conteudo, **kw):
        chamadas.append(kw.get("modelo"))
        k = len(chamadas)
        return {"thumbnails": [{"ideia": f"cena {k}", "texto": f"PALAVRA{k}", "prompt": "scene", "modo": "albert"}]}
    monkeypatch.setattr(ia, "chamar", chamar)
    out = tf.pedir_ideias("T", "roteiro", [], 0, "pt", albert=3, modelo="claude-opus-5-5")
    assert len(out) == 3 and len(chamadas) == 3
    assert chamadas == ["claude-opus-5-5"] * 3


def test_estimar_custos():
    d = tf.estimar_custos("x" * 12000)
    ids = [m["id"] for m in d["modelos"]]
    assert ids == ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
    h, s, o = (m["usd"]["ideias"] for m in d["modelos"])
    assert h < s < o and o < 1


def test_albert_padrao_3():
    assert tf.ativo_albert({}) == 3
    assert tf.ativo_albert({"thumbs_albert": 2}) == 3  # o padrão antigo
    assert tf.ativo_albert({"thumbs_albert": 2, "thumbs_albert_v448": True}) == 2
    assert tf.ativo_albert({"thumbs_albert": 0}) == 0


def test_ler_resolver_chaves():
    assert cr.ler('{"trocas":[{"de":"a b","para":"c"}]}')[0]["para"] == "c"
    assert cr.ler('[{"de":"a b","para":"c"}]')[0]["de"] == "a b"
    assert cr.ler('{"correcoes":[{"item":"V1","de":"a b","para":null,"status":"tirado"}]}')[0]["para"] == ""
    assert cr.ler('{"correcoes":[{"item":"V1","de":"a b","para":null,"status":"corrigido"}]}') == []
    assert ch.ler('[{"de":"a b c","para":"d"}]')["trocas"][0]["para"] == "d"


def test_prompt_reacertar():
    rot = "Primeiro parágrafo sobre gatos.\n\nEinstein publicou quatro artigos em 1905, aos 26 anos.\n\nFim."
    assert "Einstein publicou quatro" in cr.paragrafo_parecido(rot, "Einstein lançou 4 artigos em 1905")
    pr = cr.prompt_reacertar(rot, [{"item": "V1", "de": "Einstein lançou 4 artigos em 1905", "para": "x"}])
    assert "LETRA POR LETRA" in pr and "C1" in pr


def test_titulo_da_galeria(monkeypatch):
    import app as A
    import dossies
    monkeypatch.setattr(dossies, "carregar", lambda base, pid: {"nome": "Clássicos", "resultado": {"titulos": ["Você Finge Que Leu?"]}})
    assert A._titulo_do_projeto_ligado({"dossie_id": "abcdef0123"}) == "Você Finge Que Leu?"
    monkeypatch.setattr(dossies, "carregar", lambda base, pid: {"nome": "Clássicos", "resultado": {}})
    assert A._titulo_do_projeto_ligado({"dossie_id": "abcdef0123"}, {}) == "Clássicos"
    assert A._titulo_do_projeto_ligado({}) == ""


def test_historico_por_id(tmp_path, monkeypatch):
    import historico_voz as hv
    monkeypatch.setattr(hv, "_ler", lambda pasta: [{"id": "3ead6ef6abcd", "criado": 2}, {"id": "ffff0000aaaa", "criado": 1}])
    assert [x["id"] for x in hv.listar(str(tmp_path), id_="3ead6ef6")["itens"]] == ["3ead6ef6abcd"]
    assert hv.listar(str(tmp_path))["total"] == 2


def test_claude_code_so_nesta_chamada(monkeypatch):
    import ia_assinatura
    vistos = {}
    monkeypatch.setattr(ia_assinatura, "executavel", lambda modo: "/bin/claude")

    def fake(modo, system, conteudo, schema=None, web=False, modelo_claude="sonnet", timeout=600):
        vistos.update(modo=modo, modelo=modelo_claude)
        return {"ok": True}
    monkeypatch.setattr(ia_assinatura, "chamar", fake)
    monkeypatch.setattr(ia, "_transporte", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não pode ir na API")))
    assert ia.chamar("roteiros", "s", "c", schema={"type": "object"}, modelo="cc:opus") == {"ok": True}
    assert vistos == {"modo": "claude", "modelo": "opus"}
    monkeypatch.setattr(ia_assinatura, "executavel", lambda modo: None)
    assert ia.chamar("roteiros", "s", "c", modelo="cc:opus") is None
    d = tf.estimar_custos("x")
    assert [x["id"] for x in d["claude_code"]] == ["cc:opus", "cc:sonnet"]
