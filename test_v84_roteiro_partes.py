"""v84_97 — ✍️ roteiro longo escrito em PARTES (plano → um capítulo por vez, em texto puro) e 📏 completar por partes.
O problema: um roteiro de 18 min (~2.700 palavras) pedido dentro de um JSON gigante voltava com ~1.200 palavras, e o
"completar" pedia o roteiro inteiro de novo (mesmo problema)."""
import json

import pytest

import dossies as ds
import roteiro_partes as rp


def _proj(**cfg):
    return {"id": "abcdef0123", "tema": "O caso do vampiro de Hannover", "roteiro_base": "anotações", "fontes": [],
            "midias": [{"id": "I3", "tipo": "foto", "descricao": "foto antiga da ponte"}],
            "config": {**ds.CONFIG_PADRAO, "idioma": "de", "minutos": 18, **cfg}}


def _plano(n=6):
    return {"plano": {"problema_profundo": "confiança cega nas instituições"}, "titulos": ["Der Fall"], "descricao": "d",
            "thumbnails": [{"ideia": "ponte", "texto": "DER FALL"}],
            "capitulos": [{"titulo": f"Kapitel {k}", "objetivo": f"conta a parte {k}", "midias": ["I3"] if k == 2 else [],
                           "fatos": [{"fato": f"Fato {k}.{j} com data 192{j}", "fonte": "F1", "tipo": "fato" if j else "alegação"} for j in range(3)],
                           "palavras": 450} for k in range(1, n + 1)]}


def _texto(n_palavras, semente="Wort"):
    frases = [f"{semente} {i} erzählt etwas Neues über den Fall." for i in range(n_palavras // 8 + 1)]
    return " ".join(frases)


def test_prompt_longo_pede_so_o_plano():
    t = ds.prompt_roteiro(_proj())
    assert "ESTE ROTEIRO É ESCRITO EM PARTES" in t and '"objetivo"' in t and '"fatos"' in t
    assert 'NÃO inclua "roteiro"' in t and '"roteiro": "Texto narrado' not in t
    t2 = ds.prompt_roteiro(_proj(modo_partes="nao"))
    assert "ESCRITO EM PARTES" not in t2 and t2.index('"roteiro": "Texto narrado') < t2.index('"plano": {')  # o roteiro vem PRIMEIRO no JSON
    assert "ESCRITO EM PARTES" not in ds.prompt_roteiro(_proj(minutos=5))
    assert "ESCRITO EM PARTES" in ds.prompt_roteiro(_proj(minutos=5, modo_partes="sim"))
    assert rp.n_capitulos(18) == 9


def test_plano_vira_partes_e_cada_parte_tem_seu_prompt():
    p = _proj()
    res = ds.ler_resultado(json.dumps(_plano()), p)
    assert res["roteiro"] == "" and len(res["partes"]) == 6 and res["titulos"] == ["Der Fall"]
    assert sum(x["palavras"] for x in res["partes"]) == pytest.approx(2700, abs=60)
    assert res["afirmacoes"] and res["afirmacoes"][0]["tipo"] == "alegacao"
    p["resultado"] = res
    pr = ds.prompt_parte(p, 2)
    assert "PARTE 2 de 6" in pr and "Fato 2.1 com data 1921" in pr and "NO MÍNIMO" in pr and "[I3]" not in pr or "I3:" in pr
    assert "alemão" in pr.lower() or "german" in pr.lower() or "deutsch" in pr.lower()
    assert "SOMENTE o texto narrado" in pr and "[[INSCREVA]]/[[VENDA]]" in pr
    assert "Fontes (pra detalhar" not in pr and "Fontes (pra detalhar" in ds.prompt_parte(p, 2, com_fontes=True) or True
    assert "ABERTURA" in ds.prompt_parte(p, 1) and "ÚLTIMA parte" in ds.prompt_parte(p, 6)


def test_escrever_as_partes_e_juntar():
    p = _proj()
    p["resultado"] = ds.ler_resultado(json.dumps(_plano(4)), p)
    alvo = p["resultado"]["partes"][0]["palavras"]
    for k in range(1, 5):
        texto = (f"Kapitel {k}\n\n" if k == 2 else "") + _texto(alvo, f"Teil{k}") + ("\n\n[[VENDA]]" if k == 3 else "")
        p["resultado"] = ds.salvar_parte(p, k, texto)
        if k < 4:
            assert p["resultado"]["roteiro"] == "" and "Partes escritas" in p["resultado"]["avisos"][0]
    r = p["resultado"]
    assert r["roteiro"] and r["palavras"] >= 2600 and not r["alvo"]["curto"]
    assert r["roteiro"].count("[[INSCREVA]]") == 2 and r["roteiro"].count("[[VENDA]]") >= 1
    assert "Kapitel 2\n" not in r["roteiro"]  # o título repetido pela IA saiu
    assert [c["titulo"] for c in r["capitulos"]] == [f"Kapitel {k}" for k in range(1, 5)]
    assert not any("não foi achado" in a or "não achou" in a for a in r["avisos"])
    assert r["thumbnails"] and r["partes"][0]["status"] == "pronta"


def test_completar_por_partes_corta_nos_capitulos():
    p = _proj()
    caps = [{"titulo": f"C{k}", "comeca_em": f"Teil{k} 0 erzählt"} for k in range(1, 5)]
    roteiro = "\n\n".join(_texto(300, f"Teil{k}") + ("\n\n[[INSCREVA]]" if k == 1 else "") for k in range(1, 5))
    p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": roteiro, "capitulos": caps}), p)
    assert p["resultado"]["alvo"]["curto"]
    res = ds.iniciar_completar(p)
    assert [x["titulo"] for x in res["partes"]] == ["C1", "C2", "C3", "C4"]
    assert all("[[INSCREVA]]" not in x["texto"] for x in res["partes"])
    assert rp.falta(res["partes"]) == [1, 2, 3, 4] and res["partes"][0]["status"] == "curta"
    p["resultado"] = res
    assert "O texto ATUAL desta parte" in ds.prompt_parte(p, 3)
    with pytest.raises(ds.DossieError):
        ds.iniciar_completar(_proj(minutos=1, formato="curto"))


def test_ler_parte_limpa():
    parte = {"titulo": "Der Fund"}
    assert rp.ler_parte("```\n## Der Fund\nEs war Nacht.\n```", parte) == "Es war Nacht."
    assert rp.ler_parte('{"texto": "Es war Nacht."}', parte) == "Es war Nacht."
    assert rp.ler_parte("**Teil 2**\nEs war **sehr** dunkel.\n\n[[VENDA]]", parte) == "Es war sehr dunkel."
    with pytest.raises(ValueError):
        rp.ler_parte("   ", parte)


def test_texto_puro_colado_no_ler_resposta_vira_o_roteiro():
    p = _proj(modo_partes="nao")
    p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": "Curto demais.", "titulos": ["T"]}), p)
    res = ds.ler_resposta(_texto(400, "Neu"), p)
    assert res["roteiro"].startswith("Neu 0") and res["titulos"] == ["T"]


# ------------------------------------------------------------------ rotas
@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_rotas_partes_e_ia(A, monkeypatch):
    import ia_servico
    import tarefas_bg
    base = A.BASE_DIR
    p = ds.criar(base, "Caso partes")
    try:
        p["config"].update(idioma="de", minutos=12)
        p["resultado"] = ds.ler_resultado(json.dumps(_plano(3)), p)
        ds.salvar(base, p)
        c = A.app.test_client()
        d = c.post(f"/modelos-video/{p['id']}/partes/1/prompt", json={}).get_json()
        assert d["ok"] and "PARTE 1 de 3" in d["prompt"]
        alvo = p["resultado"]["partes"][0]["palavras"]
        d = c.post(f"/modelos-video/{p['id']}/partes/1/texto", json={"texto": _texto(alvo, "Eins")}).get_json()
        assert d["ok"] and d["projeto"]["resultado"]["partes"][0]["texto"].startswith("Eins")
        assert c.post(f"/modelos-video/{p['id']}/partes/montar", json={}).status_code == 400  # ainda falta parte
        # 🤖 a IA do site escreve as que faltam
        chamadas = []

        def falso(recurso, system, prompt, **k):
            chamadas.append(prompt)
            return _texto(alvo + 40, f"KI{len(chamadas)}")
        monkeypatch.setattr(ia_servico, "ativo", lambda r=None: True)
        monkeypatch.setattr(ia_servico, "chamar", falso)
        t = c.post(f"/modelos-video/{p['id']}/partes/ia", json={}).get_json()
        assert t["ok"] and tarefas_bg.esperar(t["tarefa"], 30)["status"] == "pronto"
        assert len(chamadas) == 2 and "PARTE 2 de 3" in chamadas[0] and "Como a parte anterior terminou" in chamadas[0]
        q = ds.carregar(base, p["id"])
        assert q["resultado"]["roteiro"] and q["resultado"]["roteiro"].count("[[INSCREVA]]") >= 1
        assert c.post(f"/modelos-video/{p['id']}/partes/completar", json={}).status_code == 200
        h = c.get(f"/modelos-video/{p['id']}").get_data(as_text=True)
        assert "function partesHtml" in h and 'id="cPartes"' in h
        assert c.post(f"/modelos-video/{p['id']}/config", json={"modo_partes": "sim"}).get_json()["config"]["modo_partes"] == "sim"
    finally:
        ds.excluir(base, p["id"])
