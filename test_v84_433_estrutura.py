"""v84_433 — a estrutura (abertura, arco, fecho, chamada) muda de vídeo pra vídeo."""
import random

import estrutura_video as ev


def test_sortear_nao_repete_os_ultimos():
    rnd = random.Random(1)
    hist = []
    for _ in range(30):
        e = ev.sortear(hist, rnd)
        assert e["abertura"] not in [h["abertura"] for h in hist[-3:]]
        assert e["arco"] not in [h["arco"] for h in hist[-2:]] and e["fecho"] not in [h["fecho"] for h in hist[-2:]]
        hist.append(e)
    assert len({h["abertura"] for h in hist}) >= 5


def test_garantir_grava_e_varia_entre_projetos(tmp_path):
    ps = [{"id": f"p{i}", "config": {"modelo": "filo"}} for i in range(4)]
    es = [ev.garantir(str(tmp_path), p) for p in ps]
    assert all(p["config"]["estrutura"] for p in ps)
    assert len({e["abertura"] for e in es[:4]}) == 4
    assert ev.garantir(str(tmp_path), ps[0]) is ps[0]["config"]["estrutura"]  # não sorteia de novo


def test_bloco_e_mudar():
    p = {"config": {}}
    e = ev.mudar(p, {"abertura": "pergunta", "arco": "dois_lados", "fecho": "volta", "chamada": "1", "lixo": "x"})
    b = ev.bloco(e)
    assert "Pergunta direta" in b and "Dois pensadores" in b and "Volta à abertura" in b and "IDENTIDADE fica" in b
    assert "ARCO" not in ev.bloco(e, curto=True)
    assert ev.bloco({}) == ""


def test_prompt_e_rota(monkeypatch):
    import app as A
    import dossies as ds
    p = ds.criar(A.BASE_DIR, tema="Teste estrutura", modelo=next(k for k, m in ds.MODELOS.items() if m.get("formatos")))
    p["roteiro_base"] = "Um texto base sobre a morte e o sentido da vida. " * 20
    ds.salvar(A.BASE_DIR, p)
    try:
        c = A.app.test_client()
        r = c.post(f"/modelos-video/{p['id']}/prompt", json={}).get_json()
        assert "ESTRUTURA DESTE VÍDEO" in r["prompt"]
        q = ds.carregar(A.BASE_DIR, p["id"])
        assert q["config"]["estrutura"]["abertura"] in ev.ABERTURAS
        d = c.post(f"/modelos-video/{p['id']}/estrutura", json={"abertura": "frase"}).get_json()
        assert d["estrutura"]["abertura"] == "frase"
        assert "estBox" in c.get(f"/modelos-video/{p['id']}").get_data(as_text=True)
        assert "ABERTURA —" in str(ds._contexto_partes(ds.carregar(A.BASE_DIR, p["id"]), A.BASE_DIR))
    finally:
        ds.excluir(A.BASE_DIR, p["id"])


def test_ajustar_thumb(tmp_path, monkeypatch):
    import thumbs_flow as tf
    d = {"itens": [{"n": 1, "ideia": "mulher velha deitada", "texto": "MEDO", "prompt": "an old woman lying in bed", "modo": "albert"}]}
    monkeypatch.setattr(tf, "carregar", lambda b, o, p: d)
    monkeypatch.setattr(tf, "salvar", lambda b, o, p, x: None)
    vistos = []

    def chamar(rec, system, conteudo, **k):
        vistos.append(conteudo)
        return {"prompt": "a young girl standing by the bed", "ideia": "garota em pé", "texto": ""}
    out = tf.ajustar("", "dossie", "x", 1, "uma garota em pé", chamar=chamar)
    it = out["itens"][0]
    assert it["prompt"] == "a young girl standing by the bed" and it["texto"] == "MEDO" and it["modo"] == "albert"
    assert it["ajustes"] == ["uma garota em pé"] and it["prompt_antes"] == "an old woman lying in bed"
    tf.ajustar("", "dossie", "x", 1, "olhando pra câmera", chamar=chamar)
    assert "uma garota em pé" in vistos[-1]  # o pedido anterior continua valendo
    import pytest
    with pytest.raises(tf.ThumbErro):
        tf.ajustar("", "dossie", "x", 1, "  ", chamar=chamar)
