"""JSON colado da IA, estragado pelo copiar/colar, ainda é lido (json_ia.py)."""
import json

import pytest

import json_ia

CERTO = {"roteiro": "Linha 1\n\n[[VENDA]]\n\nLinha 2", "cenas": [{"obra": "Naruto", "ano": "2002", "ok": True}], "n": 3}


@pytest.mark.parametrize("texto", [
    json.dumps(CERTO),
    json.dumps(CERTO, indent=2, ensure_ascii=False),
    "```json\n" + json.dumps(CERTO, indent=2) + "\n```",
    "Aqui está o JSON:\n```json\n" + json.dumps(CERTO) + "\n```\nEspero ter ajudado!",
    "json\nCopiar código\n" + json.dumps(CERTO, indent=2),
    "json" + json.dumps(CERTO),
    # quebra de linha de verdade dentro do texto (inválido em JSON)
    '{"roteiro": "Linha 1\n\n[[VENDA]]\n\nLinha 2", "cenas": [{"obra": "Naruto", "ano": "2002", "ok": true}], "n": 3}',
    # barras do markdown que o botão copiar põe
    '{"roteiro": "Linha 1\\n\\n\\[\\[VENDA\\]\\]\\n\\nLinha 2", "cenas": \\[{"obra": "Naruto", "ano": "2002", "ok": true}\\], "n": 3}',
    # aspas curvas, vírgulas sobrando, NBSP, comentário
    '{“roteiro”: “Linha 1\\n\\n[[VENDA]]\\n\\nLinha 2”,\u00a0"cenas": [{"obra": "Naruto", "ano": "2002", "ok": true,},], // fim\n "n": 3,}',
    # chave sem aspas, aspas simples, True do Python
    "{roteiro: 'Linha 1\\n\\n[[VENDA]]\\n\\nLinha 2', cenas: [{obra: 'Naruto', ano: '2002', ok: True}], n: 3}",
    # vírgula faltando entre itens / entre chaves
    '{"roteiro": "Linha 1\\n\\n[[VENDA]]\\n\\nLinha 2"\n"cenas": [{"obra": "Naruto", "ano": "2002", "ok": true}] "n": 3}',
])
def test_le_mesmo_estragado(texto):
    assert json_ia.carregar(texto) == CERTO


def test_aspas_sem_escape_dentro_do_texto():
    d = json_ia.carregar('{"fala": "Ele disse "não volto mais" e saiu.", "x": 1}')
    assert d == {"fala": 'Ele disse "não volto mais" e saiu.', "x": 1}


def test_resposta_cortada_no_fim_avisa_em_vez_de_aceitar_pela_metade():
    cortado = '{"roteiro": "abc", "cenas": [{"obra": "A"}, {"obra": "B", "momento": "lut'
    with pytest.raises(ValueError, match="cortou"):
        json_ia.carregar(cortado)
    d = json_ia.carregar(cortado, aceitar_cortado=True)
    assert d["cenas"][1] == {"obra": "B", "momento": "lut"}


def test_link_que_virou_markdown():
    assert json_ia.carregar('{"link": "[https://youtu.be/x](https://youtu.be/x)"}') == {"link": "https://youtu.be/x"}


def test_escapes_validos_continuam():
    d = {"a": 'x "y" \\ z / \u00e9 \t', "b": "C:\\pasta"}
    assert json_ia.carregar(json.dumps(d)) == d
    assert json_ia.carregar(json.dumps(d, ensure_ascii=False).replace("\\t", "\t")) == d


def test_sem_json_explica():
    with pytest.raises(ValueError, match="Não achei"):
        json_ia.carregar("oi, tudo bem?")
    with pytest.raises(ValueError, match="Cole"):
        json_ia.carregar("   ")


def test_os_leitores_do_site_usam_o_conserto():
    import modelados
    import prompt_edicao
    import roteiros_yt
    ruim = 'Claro! ```json\n{"roteiro": "Linha 1\nLinha 2", "cenas": [],}\n```'
    assert modelados.extrair_json(ruim)["roteiro"] == "Linha 1\nLinha 2"
    assert prompt_edicao.extrair_json(ruim)["roteiro"] == "Linha 1\nLinha 2"
    assert roteiros_yt.ler_analise(ruim)["roteiro"] == "Linha 1\nLinha 2"


def test_prompt_principal_aceita_json_estragado_do_chatgpt():
    from prompt_builder import parse_ai_response
    # botão copiar do ChatGPT: tudo numa linha, barras de markdown, aspas curvas e vírgula sobrando
    resp = ('Aqui está: [{“start”: 0.0, "end": 6.8, "provider": "pexels", "query": "sunrise \\[mountains\\]",}, '
            '{"start": 6.8, "end": 12.0, "provider": "pixabay", "query": "busy city\nstreet"},]')
    segs = parse_ai_response(resp, valid_providers=["pexels", "pixabay"], total_duration=12.0).segments
    assert [s.query for s in segs] == ["sunrise [mountains]", "busy city\nstreet"] or segs[1].query.startswith("busy city")
