"""🧭 Método de roteiro em todo prompt que escreve ou reescreve roteiro + o "plano" que a IA devolve."""
import json

import dossies as ds
import metodo_roteiro as mr
import roteiros_yt as ry
import vendas as vd

CHAVES = ("🧭 Método de roteiro", "PROBLEMA DE SUPERFÍCIE + PROBLEMA PROFUNDO", "\"MAS / PORTANTO\"", "RITMO", "SEM MANIPULAÇÃO", "AUTOCRÍTICA")


def _tem(texto):
    return all(c in texto for c in CHAVES)


def test_blocos():
    assert "jornada do herói" in mr.bloco("longo") and "MINI-JORNADA DE VENDA" in mr.bloco("venda")
    assert "FORMATO CURTO" in mr.bloco("curto") and "LACUNA" not in mr.bloco("curto")
    assert "Ao REESCREVER" in mr.bloco("reescrita")
    assert mr.ler_plano({"problema_profundo": " medo ", "jornada": ["a", "", "b"], "lixo": 1}) == {"problema_profundo": "medo", "jornada": ["a", "b"]}


def test_venda_e_modelo_usam_o_metodo_e_devolvem_o_plano():
    p = {"id": "x", "produto": {"titulo": "Garrafa"}, "config": {}, "midias": [], "link": ""}
    pr = vd.prompt_roteiro(p)
    assert _tem(pr) and "MINI-JORNADA DE VENDA" in pr and '"plano": {' in pr and pr.index("🧭") < pr.index("## Resposta")
    r = vd.ler_roteiro(json.dumps({"roteiro": "Oi.", "plano": {"problema_profundo": "perder tempo"}}), p)
    assert r["plano"] == {"problema_profundo": "perder tempo"}
    d = {"tema": "Caso", "config": {"modelo": "true_crime", "formato": "caso_completo"}, "fontes": [], "midias": [], "roteiro_base": "notas"}
    pr = ds.prompt_roteiro(d)
    assert _tem(pr) and "jornada do herói" in pr and '"plano": {' in pr
    d["config"]["formato"] = "curto"
    assert "FORMATO CURTO" in ds.prompt_roteiro(d)
    res = ds.ler_resultado(json.dumps({"roteiro": "Era uma vez.", "plano": {"comeco_e_fim": "dúvida → verdade"}}), d)
    assert res["plano"] == {"comeco_e_fim": "dúvida → verdade"}


def test_roteiro_do_youtube():
    p = {"transcricao": {"blocos": [{"inicio": 0, "texto": "oi"}]}, "titulo": "T"}
    m = {x["id"]: x for x in ry.MODELOS_FABRICA}
    assert _tem(ry.prompt_analise(p, m["reescrever_cenas"])) and "Ao REESCREVER" in ry.prompt_analise(p, m["reescrever_cenas"])
    assert "FORMATO CURTO" in ry.prompt_analise(p, m["reescrever_curto"])
    assert "🧭" not in ry.prompt_analise(p, m["so_cenas"])  # só lista as cenas, não reescreve
    p["analise"] = {"roteiro": "Texto.", "cenas": []}
    assert "MÉTODO DE ROTEIRO" in ry.prompt_acoes(p, ["traduzir"]) and "MÉTODO DE ROTEIRO" not in ry.prompt_acoes(p, ["tags"])
    assert ry.ler_analise(json.dumps({"roteiro": "x", "cenas": [], "plano": {"publico": "fãs"}}))["plano"] == {"publico": "fãs"}


def test_estrategia_de_shorts_e_estrutura_de_referencia():
    c = mr.bloco("curto")
    assert "GANCHO COM O ESPECTADOR DENTRO" in c and "FINAL COM RECOMPENSA" in c and "taxa de visualização > 80%" in c
    assert "legendas de 1-3 palavras" in c and "TRANSFORMADOR" in c and "jornada do herói" not in c
    assert "GANCHO COM O ESPECTADOR DENTRO" not in mr.bloco("longo")
    p = {"id": "x", "produto": {"titulo": "Garrafa"}, "config": {"duracao_s": 45}, "midias": [], "link": ""}
    pr = vd.prompt_roteiro(p)
    assert "MINI-JORNADA DE VENDA" in pr and "GANCHO COM O ESPECTADOR DENTRO" in pr
    p["config"] = {"duracao_s": 300, "referencia": "You're a coffee company and you have a problem..."}
    pr = vd.prompt_roteiro(p)
    assert "GANCHO COM O ESPECTADOR DENTRO" not in pr
    assert "📐 Estrutura de referência" in pr and "You're a coffee company" in pr and "Não copie frases" in pr
    d = {"tema": "Caso", "config": {"modelo": "negocios", "formato": "curto", "referencia": "Você é a Nescafé…"}, "fontes": [], "midias": [], "roteiro_base": "n"}
    pr = ds.prompt_roteiro(d)
    assert "GANCHO COM O ESPECTADOR DENTRO" in pr and "Você é a Nescafé…" in pr
    assert "GANCHO COM O ESPECTADOR DENTRO" in ry.prompt_analise({"transcricao": {"blocos": [{"inicio": 0, "texto": "oi"}]}},
                                                                {x["id"]: x for x in ry.MODELOS_FABRICA}["reescrever_curto"])


def test_short_e_ate_60_segundos():
    import metodo_roteiro, vendas
    assert "no MÁXIMO 60 segundos" in metodo_roteiro.bloco("curto")
    assert "no MÁXIMO 60 segundos" in metodo_roteiro.bloco("venda_curto")
    assert "no MÁXIMO 60 segundos" not in metodo_roteiro.bloco("longo")
    base = {"id": "x", "produto": {"titulo": "Garrafa"}, "midias": [], "link": ""}
    assert "GANCHO COM O ESPECTADOR DENTRO" in vendas.prompt_roteiro({**base, "config": {"duracao_s": 60}})
    assert "GANCHO COM O ESPECTADOR DENTRO" not in vendas.prompt_roteiro({**base, "config": {"duracao_s": 90}})
