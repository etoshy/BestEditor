"""v84_92 — 📏 o tempo escolhido vale de verdade: pôs 18 min, a IA devolvia roteiro de ~8.

O prompt ganha uma seção de TAMANHO perto do fim (mínimo de palavras + palavras por parte), a resposta é conferida e,
se ficou curta, o site gera um prompt pra completar (resposta só {"roteiro"} — títulos, descrição, capítulos e cenas
ficam). Vale no 🕵️ Modelo de vídeo e no 📝 Roteiro do YouTube (campo ⏱ min, opcional)."""
import json

import pytest

import dossies as ds
import metodo_roteiro as mr
import roteiros_yt as ry


def _texto(n, palavra="fato"):
    return " ".join(f"{palavra}{k}" for k in range(n))


def _dossie(minutos=18):
    return {"id": "0123456789", "tema": "O caso Y", "fontes": [], "midias": [], "roteiro_base": "minhas anotações",
            "config": {"modelo": "true_crime", "formato": "caso_completo", "minutos": minutos}}


def test_bloco_de_tamanho():
    b = mr.bloco_tamanho(18, 2700, ["GANCHO", "Quem era", "O crime"])
    assert "NO MÍNIMO 2565 palavras" in b and "~18 minutos" in b and "1. GANCHO" in b and "3. O crime" in b
    assert mr.bloco_tamanho(1, 150) == "" and mr.bloco_tamanho(0, 0) == ""  # Shorts / sem alvo: nada
    assert mr.palavras_do_texto("[I3] uma frase [[INSCREVA]] [CENA 2] aqui") == 3
    assert mr.aviso_tamanho(1200, 2700, 18) and not mr.aviso_tamanho(2400, 2700, 18)


def test_prompt_do_modelo_de_video_pede_o_tamanho_perto_do_fim():
    p = _dossie(18)
    p["config"]["modo_partes"] = "nao"  # v84_97: a partir de 8 min o padrão é escrever em partes (test_v84_roteiro_partes)
    texto = ds.prompt_roteiro(p)
    minutos, palavras, ppm = ds.alvo_tamanho(p)
    assert (minutos, palavras) == (18.0, 18 * ppm)
    i = texto.index("📏 TAMANHO DO ROTEIRO")
    assert i > texto.index("Método de roteiro") and i < texto.index("## Resposta — SOMENTE um JSON")
    assert f"NO MÍNIMO {int(palavras * 0.95)} palavras" in texto
    assert "📏 TAMANHO" not in ds.prompt_roteiro(dict(_dossie(), config={"modelo": "true_crime", "formato": "curto", "minutos": 1}))


def test_resposta_curta_avisa_e_o_completar_troca_so_o_roteiro():
    p = _dossie(18)
    curto = "Começo do caso aqui. " + _texto(1200) + " Depois veio o julgamento final. " + _texto(30, "x")
    resp = {"titulos": ["T1"], "descricao": "D", "tags": ["a"], "roteiro": curto,
            "capitulos": [{"titulo": "Intro", "comeca_em": "Começo do caso aqui"},
                          {"titulo": "Julgamento", "comeca_em": "Depois veio o julgamento final"}]}
    p["resultado"] = ds.ler_resposta(json.dumps(resp), p)
    r = p["resultado"]
    assert r["alvo"]["curto"] and r["avisos"][0].startswith("📏 O roteiro ficou CURTO")
    pc = ds.prompt_completar(p)
    assert "NO MÍNIMO" in pc and "Começo do caso aqui" in pc and '{"roteiro"' in pc and curto[:60] in pc
    longo = "Começo do caso aqui. " + _texto(2600) + " Depois veio o julgamento final. " + _texto(100, "x")
    p["resultado"] = ds.ler_resposta(json.dumps({"roteiro": longo}), p)  # só o roteiro: o resto fica
    r = p["resultado"]
    assert r["titulos"] == ["T1"] and r["descricao"] == "D" and r["tags"] == ["a"]
    assert [c["titulo"] for c in r["capitulos"]] == ["Intro", "Julgamento"] and r["capitulos"][1]["posicao"] > 0.9
    assert not r["alvo"]["curto"] and not any(a.startswith("📏") for a in r["avisos"])


def test_rotas_do_modelo_de_video():
    import app as A
    c = A.app.test_client()
    p = ds.criar(A.BASE_DIR, tema="O caso Y")
    try:
        assert c.post(f"/modelos-video/{p['id']}/prompt-completar", json={}).status_code == 400  # ainda sem roteiro
        curto = {"titulos": ["T1"], "descricao": "D", "roteiro": _texto(1000)}
        d = c.post(f"/modelos-video/{p['id']}/resultado", json={"texto": json.dumps(curto)}).get_json()
        assert d["projeto"]["resultado"]["alvo"]["curto"]
        d = c.post(f"/modelos-video/{p['id']}/prompt-completar", json={}).get_json()
        assert "NO MÍNIMO" in d["prompt"]
        alvo = ds.alvo_tamanho(ds.carregar(A.BASE_DIR, p["id"]))[1]
        d = c.post(f"/modelos-video/{p['id']}/resultado", json={"texto": json.dumps({"roteiro": _texto(alvo)})}).get_json()
        r = d["projeto"]["resultado"]
        assert r["titulos"] == ["T1"] and r["descricao"] == "D" and not r["alvo"]["curto"]
        assert 'btnCompletar' in c.get(f"/modelos-video/{p['id']}").get_data(as_text=True)
    finally:
        ds.excluir(A.BASE_DIR, p["id"])


def _roteiro_yt(base, minutos):
    p = ry.criar_projeto(base, texto="[0:00] " + _texto(300))
    p["minutos_alvo"] = ry.minutos_alvo(minutos)
    return p


def test_roteiro_do_youtube_com_duracao(tmp_path):
    base = str(tmp_path)
    p = _roteiro_yt(base, "18")
    p["modo_partes"] = "nao"  # v84_98: ≥ 8 min o padrão é em partes (test_v84_partes_yt_revisao)
    texto = ry.prompt_analise(p, ry.obter_modelo(base, "reescrever_cenas"))
    assert "NO MÍNIMO 2565 palavras" in texto and "expanda" in texto and texto.index("📏") < texto.index(ry._FORMATO_ANALISE[:30])
    assert "📏" not in ry.prompt_analise(p, ry.obter_modelo(base, "so_cenas"))
    p["minutos_alvo"] = ry.minutos_alvo("")
    assert "📏" not in ry.prompt_analise(p, ry.obter_modelo(base, "reescrever_cenas"))  # vazio = tamanho do original
    assert ry.minutos_alvo("abc") == 0 and ry.minutos_alvo("0,5") == 0 and ry.minutos_alvo("12,5") == 12.5


def test_roteiro_do_youtube_curto_e_completar_mantem_as_cenas(tmp_path):
    base = str(tmp_path)
    p = _roteiro_yt(base, 18)
    ry.salvar_projeto(base, p)
    an = ry.conferir_tamanho(p, ry.ler_analise(json.dumps({"roteiro": _texto(900), "cenas": [{"obra": "Filme A", "momento": "a dança"}]})))
    assert an["alvo"]["curto"] and "CURTO" in an["alvo"]["aviso"]
    p["analise"] = an
    pc = ry.prompt_completar_analise(p)
    assert "NO MÍNIMO 2565" in pc and "cenas" in pc
    p["minutos_alvo"] = 0
    with pytest.raises(ry.RoteiroError):
        ry.prompt_completar_analise(p)


def test_fluxo_do_roteiro_do_youtube_pelo_site(tmp_path, monkeypatch):
    import app as A
    c = A.app.test_client()
    base = A.BASE_DIR
    p = ry.criar_projeto(base, texto="[0:00] " + _texto(300))
    try:
        d = c.post(f"/roteiros-yt/{p['id']}/prompt-analise", json={"modelo_id": "reescrever_cenas", "minutos": "18", "modo_partes": "nao"}).get_json()
        assert "NO MÍNIMO 2565" in d["prompt"]
        d = c.post(f"/roteiros-yt/{p['id']}/analise", json={"texto": json.dumps(
            {"roteiro": _texto(900), "cenas": [{"obra": "Filme A", "momento": "a dança"}]})}).get_json()
        assert d["analise"]["alvo"]["curto"]
        d = c.post(f"/roteiros-yt/{p['id']}/prompt-completar", json={}).get_json()
        assert "NO MÍNIMO 2565" in d["prompt"]
        d = c.post(f"/roteiros-yt/{p['id']}/analise", json={"texto": json.dumps({"roteiro": _texto(2700)})}).get_json()
        an = d["analise"]
        assert not an["alvo"]["curto"] and [x["obra"] for x in an["cenas"]] == ["Filme A"]  # as cenas ficaram
        h = c.get(f"/roteiros-yt/{p['id']}").get_data(as_text=True)
        assert 'id="minutosAlvo"' in h and 'value="18.0"' in h
    finally:
        ry.excluir_projeto(base, p["id"])
