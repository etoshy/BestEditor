"""v84_98 — ✍️ roteiro do YouTube longo em partes (plano → capítulo por capítulo → 1 roteiro inteiro) e 🪄 revisão do
roteiro inteiro por TROCAS (não encolhe)."""
import json

import pytest

import dossies as ds
import revisao_roteiro as rv
import roteiros_yt as ry


def _texto(n, s="Satz"):
    return " ".join(f"{s} {i} erzählt etwas Neues." for i in range(n // 5 + 1))


def _yt(minutos=12, **k):
    blocos = [{"inicio": i * 30.0, "fim": i * 30.0 + 30, "texto": f"bloco {i} do vídeo original"} for i in range(int(minutos * 2))]
    return dict({"id": "abcdef0123", "titulo": "Vídeo X", "transcricao": {"blocos": blocos, "com_tempo": True},
                 "minutos_alvo": minutos, "marcar_chamadas": True}, **k)


PLANO = {"titulo": "X", "idioma": "de", "capitulos": [{"titulo": f"K{k}", "objetivo": f"o{k}", "fatos": [{"fato": f"f{k}", "fonte": "[1:00]"}],
                                                        "palavras": 400} for k in range(1, 5)],
         "cenas": [{"obra": "Filme A", "tipo": "filme", "momento": "a cena", "capitulo": 2}]}


def test_prompt_yt_longo_pede_o_plano():
    t = ry.prompt_analise(_yt(), ry.MODELOS_FABRICA[0])
    assert "ESCRITO EM PARTES" in t and 'NÃO inclua "roteiro"' in t and "[3:12]" in t and "Pausas pra vídeo de like" not in t
    assert "ESCRITO EM PARTES" not in ry.prompt_analise(_yt(modo_partes="nao"), ry.MODELOS_FABRICA[0])
    assert "ESCRITO EM PARTES" not in ry.prompt_analise(_yt(5), ry.MODELOS_FABRICA[0])
    # sem ⏱: usa a duração do original
    assert "ESCRITO EM PARTES" in ry.prompt_analise(_yt(10, minutos_alvo=None), ry.MODELOS_FABRICA[0])
    curto = next(m for m in ry.MODELOS_FABRICA if m["id"] == "reescrever_curto")
    assert "ESCRITO EM PARTES" not in ry.prompt_analise(_yt(), curto)


def test_fluxo_partes_yt():
    p = _yt()
    an = ry.ler_analise(json.dumps(PLANO))
    assert an["roteiro"] == "" and an["capitulos_plano"] and an["cenas"][0]["capitulo"] == 2
    import roteiro_partes as rp
    an["partes"] = rp.de_plano(an.pop("capitulos_plano"), ry.alvo_palavras(p)[1])
    p["analise"] = an
    pr = ry.prompt_parte(p, 2)
    assert "PARTE 2 de 4" in pr and "Filme A — a cena" in pr and "transcrição" not in pr.split("## Resposta")[0][-200:]
    assert "bloco 3 do vídeo original" in ry.prompt_parte(p, 2, com_fontes=True)
    for k in range(1, 5):
        ry.salvar_parte(p, k, _texto(450, f"T{k}"))
    a = p["analise"]
    assert a["roteiro"] and a["roteiro"].count("[[INSCREVA]]") == 2 and a["alvo"]["curto"] is False
    assert [c["titulo"] for c in a["capitulos_partes"]] == ["K1", "K2", "K3", "K4"]
    # completar: corta nos capítulos de novo
    a["roteiro"] = "\n\n".join(_texto(100, f"T{k}") for k in range(1, 5))
    an2 = ry.iniciar_completar(p)
    assert len(an2["partes"]) >= 4 and all(x["status"] == "curta" for x in an2["partes"])


# ------------------------------------------------------------------ 🪄 revisão
ROT = "Mas isso não é tudo. Ele chegou em 1924.\n\n[[INSCREVA]]\n\nEle saiu. Ele voltou. Ele ficou."


def test_revisao_prompt_e_aplicar():
    t = rv.prompt(ROT, "alemão", "o caso")
    assert "TROCAS" in t.upper() and "NUNCA mais curta" in t and ROT in t and "[[INSCREVA]]" in t
    r = rv.aplicar(ROT, json.dumps({"trocas": [
        {"de": "Mas isso não é tudo.", "para": "Só que o caso ainda guardava um detalhe: a carta encontrada na gaveta.", "motivo": "clichê"},
        {"de": "Ele saiu.  Ele voltou.", "para": "Ele saiu de manhã e só voltou à noite."},
        {"de": "texto que não existe", "para": "x"},
        {"de": "[[INSCREVA]]", "para": "sumiu"}]}))
    assert len(r["aplicadas"]) == 2 and len(r["nao_achadas"]) == 2
    assert "[[INSCREVA]]" in r["texto"] and r["palavras_depois"] > r["palavras_antes"]
    with pytest.raises(ValueError):
        rv.prompt("  ")
    with pytest.raises(ValueError):
        rv.aplicar(ROT, "não é json")


# ------------------------------------------------------------------ rotas
@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_rotas_yt_partes_e_revisao(A, monkeypatch):
    import ia_servico
    import tarefas_bg
    base = A.BASE_DIR
    p = ry.criar_projeto(base, texto="olá", titulo="YT partes")
    try:
        p.update(_yt(), id=p["id"])
        ry.salvar_projeto(base, p)
        c = A.app.test_client()
        d = c.post(f"/roteiros-yt/{p['id']}/analise", json={"texto": json.dumps(PLANO)}).get_json()
        assert d["ok"] and len(d["analise"]["partes"]) == 4 and d["analise"]["roteiro"] == ""
        assert c.get(f"/roteiros-yt/{p['id']}/partes").get_json()["partes"][0]["titulo"] == "K1"
        assert "PARTE 1 de 4" in c.post(f"/roteiros-yt/{p['id']}/partes/1/prompt", json={}).get_json()["prompt"]
        alvo = d["analise"]["partes"][0]["palavras"]
        r = c.post(f"/roteiros-yt/{p['id']}/partes/1/texto", json={"texto": _texto(alvo, "Eins")}).get_json()
        assert r["ok"] and not r["tem_roteiro"]
        monkeypatch.setattr(ia_servico, "ativo", lambda r=None: True)
        monkeypatch.setattr(ia_servico, "chamar", lambda *a, **k: _texto(alvo + 30, "KI"))
        t = c.post(f"/roteiros-yt/{p['id']}/partes/ia", json={}).get_json()
        assert tarefas_bg.esperar(t["tarefa"], 30)["status"] == "pronto"
        q = ry.carregar_projeto(base, p["id"])
        assert q["analise"]["roteiro"].count("[[INSCREVA]]") >= 1 and all(x["texto"] for x in q["analise"]["partes"])
        # 🪄 revisão
        pr = c.post(f"/revisao/roteiro_yt/{p['id']}/prompt", json={"foco": "o fim"}).get_json()
        assert pr["ok"] and "o fim" in pr["prompt"]
        frase = q["analise"]["roteiro"].split(". ")[0] + "."
        rr = c.post(f"/revisao/roteiro_yt/{p['id']}/ler", json={"texto": json.dumps({"trocas": [{"de": frase, "para": frase + " Neu dazu."}]})}).get_json()
        assert rr["ok"] and len(rr["aplicadas"]) == 1
        q = ry.carregar_projeto(base, p["id"])
        assert "Neu dazu." in q["analise"]["roteiro"] and q["analise"]["antes_da_revisao"]
        assert c.post(f"/revisao/roteiro_yt/{p['id']}/ler", json={"texto": '{"trocas": [{"de": "nada", "para": "x"}]}'}).status_code == 400
        assert c.post(f"/revisao/roteiro_yt/{p['id']}/desfazer", json={}).get_json()["ok"]
        assert "Neu dazu." not in ry.carregar_projeto(base, p["id"])["analise"]["roteiro"]
        h = c.get(f"/roteiros-yt/{p['id']}").get_data(as_text=True)
        assert 'id="ptCard"' in h and 'id="revCard"' in h and 'id="modoPartes"' in h
    finally:
        ry.excluir_projeto(base, p["id"])


def test_revisao_no_dossie(A):
    base = A.BASE_DIR
    p = ds.criar(base, "Caso revisão")
    try:
        p["config"]["modo_partes"] = "nao"
        p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": ROT, "titulos": ["T"]}), p)
        ds.salvar(base, p)
        c = A.app.test_client()
        rr = c.post(f"/revisao/dossie/{p['id']}/ler", json={"texto": json.dumps({"trocas": [{"de": "Mas isso não é tudo.", "para": "O detalhe era outro."}]})}).get_json()
        assert rr["ok"]
        q = ds.carregar(base, p["id"])
        assert q["resultado"]["roteiro"].startswith("O detalhe era outro.") and q["resultado"]["roteiro_antes_revisao"].startswith("Mas isso")
        assert q["resultado"]["titulos"] == ["T"]
        assert c.post(f"/revisao/dossie/{p['id']}/desfazer", json={}).get_json()["ok"]
        q = ds.carregar(base, p["id"])
        assert q["resultado"]["roteiro"].startswith("Mas isso") and not q["resultado"].get("roteiro_antes_revisao")
        assert 'id="revCard"' in c.get(f"/modelos-video/{p['id']}").get_data(as_text=True)
    finally:
        ds.excluir(base, p["id"])
