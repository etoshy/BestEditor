"""v84_223: 100% no pod = TODA cena (mesmo com foto marcada no roteiro); as pendentes de um roteiro já planejado viram
imagem do pod num clique; o projeto já criado passa a usar essas cenas."""
import json
import os

import cenas_lote


def test_completar_pendentes(monkeypatch, tmp_path):
    import pod_studio
    import producao_pod as pp
    monkeypatch.setattr(pp, "PASTA", str(tmp_path))
    lid, iid = "lotey", "itemy"
    lote = {"id": lid, "nome": "L", "config": {"orientacao": "16:9"}, "pod_url": "http://x", "status": "concluido",
            "itens": [{"id": iid, "titulo": "Pyramiden", "estado": "pronto", "pod_img": "img-1", "log": [], "job_id": "j1"}]}
    salvos = []
    monkeypatch.setattr(pp, "carregar", lambda l: lote)
    monkeypatch.setattr(pp, "salvar", lambda l: salvos.append(1))
    monkeypatch.setattr(pp, "_cfg_pod", lambda l: {})
    monkeypatch.setattr(pp, "garantir_runner", lambda: None)
    env = {}
    monkeypatch.setattr(pod_studio, "enviar_imagens_com_refs",
                        lambda pedidos, **kw: (env.setdefault("p", pedidos) and "img-2", []))
    pasta = pp.pasta_item(lid, iid)
    with open(os.path.join(pasta, "cenas.json"), "w", encoding="utf-8") as f:
        json.dump({"segments": [
            {"start": 0, "end": 5, "provider": "runpod", "query": "pyramids at dawn", "visual": "pirâmides"},
            {"start": 5, "end": 10, "provider": cenas_lote.PROVIDER_ADIADO, "query": "moon footprint", "visual": "a footprint on the Moon"},
            {"start": 10, "end": 15, "provider": "material", "query": "I3", "visual": "the Apollo 11 bootprint photo"}]}, f)
    r = pp.completar_no_pod(lid, iid)
    assert r["convertidas"] == 2 and r["enviadas"] == 2
    assert [p["nome"] for p in env["p"]] == ["cena-0002", "cena-0003"]
    assert "footprint on the Moon" in env["p"][0]["prompt"]
    it = lote["itens"][0]
    assert it["estado"] == "imagens" and it["pod_img"] == "img-2" and it["pod_imgs"] == ["img-1"]
    assert it["cenas"]["pendentes"] == 0 and it["cenas"]["pct"] == 100
    segs = json.load(open(os.path.join(pasta, "cenas.json"), encoding="utf-8"))["segments"]
    assert all(s["provider"] == "runpod" for s in segs) and segs[2]["material_alternativo"] == "I3"


def test_anotar_alternativas():
    import producao_pod as pp
    resp = {"segments": [{"provider": "runpod"}, {"provider": "runpod"}]}
    pp._anotar_alternativas(resp, {1: {"id": "I3"}})
    assert resp["segments"][1]["material_alternativo"] == "I3" and "material_alternativo" not in resp["segments"][0]


def test_projeto_existente_usa_as_cenas_novas(monkeypatch):
    import app as A
    job = {"pending_segments": [{"start": 0, "end": 5, "provider": "runpod", "query": "a"},
                                {"start": 5, "end": 10, "provider": "adiado", "query": "b"},
                                {"start": 10, "end": 15, "provider": "adiado", "query": "c", "override_source": {"x": 1}}],
           "segment_previews": [{"ok": True}, {"ok": True, "url": "stock"}, {"ok": True}]}
    monkeypatch.setitem(A._JOBS, "jx", job)
    monkeypatch.setattr(A, "_save_state", lambda j: None)
    resp = {"segments": [{"start": 0, "provider": "runpod", "query": "a"}, {"start": 5.1, "provider": "runpod", "query": "new"},
                         {"start": 10, "provider": "runpod", "query": "new2"}]}
    assert A._atualizar_projeto_producao("jx", resp) == 1  # a cena que você trocou no editor fica
    assert job["pending_segments"][1]["provider"] == "runpod" and job["pending_segments"][1]["query"] == "new"
    assert A._cenas_pod_para_refazer(job) == [1]


def test_parar_cancela_no_pod(monkeypatch, tmp_path):
    import pod_studio
    import producao_pod as pp
    lote = {"id": "l", "config": {"orientacao": "16:9"}, "status": "rodando",
            "itens": [{"id": "i", "titulo": "T", "estado": "imagens", "pod_img": "img-2", "pod_imgs": ["img-1"], "log": []}]}
    monkeypatch.setattr(pp, "carregar", lambda l: lote)
    monkeypatch.setattr(pp, "salvar", lambda l: None)
    monkeypatch.setattr(pp, "_cfg_pod", lambda l: {})
    st = {"img-1": "concluido", "img-2": "processando"}
    monkeypatch.setattr(pod_studio, "job", lambda j, cfg=None: {"status": st[j]})
    canc = []
    monkeypatch.setattr(pod_studio, "cancelar", lambda j, cfg=None: canc.append(j))
    r = pp.parar("l", "i")
    it = lote["itens"][0]
    assert r["cancelados_no_pod"] == 1 and canc == ["img-2"]
    assert it["estado"] == "cancelado" and it["pod_img"] is None and it["pod_img_antigo"] == "img-2"
    assert lote["status"] == "concluido"
