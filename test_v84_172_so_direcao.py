"""v84_172: a IA da edição só aplica o que a DIREÇÃO escolhida tem (o que vier de fora sai, com aviso)."""
import json

import dp_direcao
import dp_visual
import prompt_edicao as pe


def test_fora_da_direcao_sai():
    p = dp_direcao.direcao("sys_true_crime")
    perm = pe.permitidos(p)
    tr_ok = sorted(perm["transicoes"] - {"none"})[0]
    ef_ok = sorted(perm["efeitos"])[0]
    ef_fora = next(e["id"] for e in dp_visual.efeitos() if e["id"] not in perm["efeitos"] and e["id"] != "none")
    fi_fora = next(f["id"] for f in dp_visual.filtros() if f["id"] not in (perm["filtros"] or set()))
    resp = {"trechos": [{"trecho": 1, "transition": tr_ok, "efeito": ef_ok},
                        {"trecho": 2, "transition": "gl_glitch", "efeito": ef_fora}],
            "destaques": [{"estilo": "dallas_tarja", "texto": "x", "start": 0.5}], "filtro_cor": fi_fora}
    r = pe.ler_resposta(json.dumps(resp), 3, 10.0, [], [True, True, True], direcao=p)
    t1, t2 = r["trechos"]
    assert t1["transition"] in (tr_ok, dp_visual.valor_transicao(tr_ok)) and t1["efeito"] == ef_ok
    assert t2["transition"] == "none" and "efeito" not in t2
    assert r["destaques"] == [] and "filtro_cor" not in r
    assert r["fora_da_direcao"] == 4 and "fora da direção" in r["avisos"][0]
    # sem direção: o catálogo todo vale (como antes)
    r = pe.ler_resposta(json.dumps(resp), 3, 10.0, [], [True, True, True])
    assert r["trechos"][1]["transition"] != "none" and r["fora_da_direcao"] == 0
