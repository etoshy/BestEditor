"""v84_486 — 🧪 verificação de qualidade do roteiro pronto: prompt → JSON de correções → aplica (sem encolher)."""
import json

import pytest

import dossies as ds
import qualidade_roteiro as qr

ROT = ("A resposta indireta é quando você muda de assunto ou faz uma piada.\n\n"
       "Também não diz que a reunião vai acontecer sem você.\n\n"
       "Essa conversa começa onde a anterior parou. " + "Uma frase qualquer sobre perguntas. " * 60)


def test_prompt_e_ler():
    pr = qr.prompt(ROT, "Pergunta armadilha", "F1 — notas: resposta indireta = informação parcial", "1) réplica | 2) disjunção",
                   alvo_palavras=500)
    assert "conceito_errado" in pr and "MAPA" in pr and "FONTE" in pr and "TAMANHO" in pr and ROT[:40] in pr
    d = qr.ler(json.dumps({"problemas": [{"tipo": "conceito errado", "trecho": "A resposta indireta é", "correcao": "x"},
                                         {"tipo": "zzz", "de": "a", "para": "a"}], "resumo": "ok"}))
    assert len(d["trocas"]) == 1 and d["trocas"][0]["tipo"] == "conceito_errado" and d["resumo"] == "ok"
    with pytest.raises(ValueError):
        qr.prompt("", "x")


@pytest.fixture
def proj():
    import app as _app
    p = ds.criar(_app.BASE_DIR, "Pergunta armadilha", modelo="raciocinio_maldito")
    p["config"].update(modo_partes="nao", minutos=2, extra="1) réplica | 2) disjunção")
    p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": ROT, "titulos": ["T"]}), p)
    ds.salvar(_app.BASE_DIR, p)
    yield _app, p
    ds.excluir(_app.BASE_DIR, p["id"])


def test_rotas(proj):
    A, p = proj
    c = A.app.test_client()
    pr = c.post(f"/qualidade/dossie/{p['id']}/prompt", json={}).get_json()
    assert pr["ok"] and "disjunção" in pr["prompt"]
    resp = json.dumps({"correcoes": [
        {"tipo": "conceito_errado", "de": "A resposta indireta é quando você muda de assunto ou faz uma piada.",
         "para": "A resposta indireta dá só parte da informação pedida.", "porque": "a fonte define assim"}],
        "resumo": "1 conceito corrigido"})
    r = c.post(f"/qualidade/dossie/{p['id']}/ler", json={"texto": resp}).get_json()
    assert r["ok"] and len(r["aplicadas"]) == 1 and r["aplicadas"][0]["tipo"] == "conceito_errado"
    q = ds.carregar(A.BASE_DIR, p["id"])
    assert "parte da informação pedida" in q["resultado"]["roteiro"]
    vazio = c.post(f"/qualidade/dossie/{p['id']}/ler", json={"texto": json.dumps({"correcoes": [], "resumo": "nada"})}).get_json()
    assert vazio["ok"] and vazio["aplicadas"] == []
    # encolher demais = não aplica
    corta = json.dumps({"correcoes": [{"tipo": "repeticao", "de": "Uma frase qualquer sobre perguntas. " * 50, "para": ""}]})
    assert c.post(f"/qualidade/dossie/{p['id']}/ler", json={"texto": corta}).status_code == 400


def test_v488_link_amazon_encurtado():
    import vendas as v
    assert v._eh_amazon("https://link.amazon/B0jjxqS7M") and v._eh_amazon("https://www.amazon.com.br/dp/1")
    assert not v._eh_amazon("https://amazon.evil.com/x")
