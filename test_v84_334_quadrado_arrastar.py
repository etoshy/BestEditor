"""v84_334: ⬛ também a versão 1:1 · ↕ posição livre do @ (arrastada na prévia) · 🎨 sorteio com teoria das cores (na página)."""
import os

import curtos as CT
import curtos_rotas as CR
import marca_canal
from test_v84_320_lote_por_etapa import _app, _espera, _falsos


def test_gera_9x16_e_1x1(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    log, _ = _falsos(base, monkeypatch)
    feitos = []

    def editor(d):
        feitos.append(CT.proporcao_do(d["projeto"]) if "projeto" in d else "?")
        return f"job{len(feitos)}"

    monkeypatch.setattr(CT, "montar_dados_editor", lambda b, pid, prov=None: {"pid": pid, "planos": [], "dur": 1.0, "projeto": CT.carregar(b, pid)})
    CR.CB["para_estudio"] = editor

    def exportar(job, q, prog):
        cam = os.path.join(base, f"{job}.mp4")
        open(cam, "wb").write(b"mp4")
        return cam
    CR.CB["exportar"] = exportar
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/1", "iniciar": True, "voz": "v1", "tambem_quadrado": True}).get_json()
    pid = r["criados"][0]
    _espera([pid])
    p = CT.carregar(base, pid)
    assert not CR.TAREFAS[pid]["erro"], CR.TAREFAS[pid]
    assert feitos == ["9:16", "1:1"] and CT.proporcao_do(p) == "9:16"  # montou de novo em 1:1 e voltou
    assert p["exportado"]["arquivo"].endswith("job1.mp4") and p["exportado_quadrado"]["arquivo"].endswith("job2.mp4")
    v = next(x for x in cl.get("/curtos/link/estado").get_json()["videos"] if x["id"] == pid)
    assert v["pronto"] and v["pronto_1x1"]
    assert cl.get(f"/curtos/{pid}/video_1x1.mp4").data == b"mp4"
    r2 = cl.post("/curtos/link/novo", json={"link": "https://a.com/2", "iniciar": True, "voz": "v1"}).get_json()  # sem a opção: só um
    _espera(r2["criados"])
    assert "exportado_quadrado" not in CT.carregar(base, r2["criados"][0])


def test_posicao_livre_do_arroba(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    a = dict(CT.ACABAMENTO_PADRAO, **CT.limpar_acabamento({"arroba": "@x", "marca_posicao": "livre", "marca_altura": "20"}))
    p = {"modelo": "comentario", "config": {}}
    CT.aplicar_acabamento(p, a)
    m = CT.normalizar_marca(p["config"]["marca"])
    assert m["posicao"] == "livre" and marca_canal.ponto(m, 1080, 1920) == (5, 540, 384)


def test_pagina_tem_alcas_cores_e_quadrado(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    html = cl.get("/curtos/link").get_data(as_text=True)
    for k in ('data-alca="marca"', 'data-alca="legenda"', 'value="livre"', "corEsquema", "corTom", "bSoCores", 'id="tambem_quadrado"',
              'list="lkCores"'):
        assert k in html, k


def test_personalizacao_e_formato_do_canal(tmp_path, monkeypatch):
    """v84_335: a aba 🎨 Personalização (uma aba por canal) e o formato/1:1 salvos por canal."""
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    cid = cl.post("/curtos/canais/novo", json={"nome": "PlaceWow"}).get_json()["id"]
    cl.post("/curtos/acabamento", json={"canal_id": cid, "proporcao": "1:1"})
    outro = cl.post("/curtos/canais/novo", json={"nome": "Fails"}).get_json()["id"]
    cl.post("/curtos/acabamento", json={"canal_id": outro, "tambem_quadrado": True})
    a = cl.post("/curtos/link/novo", json={"link": "https://a.com/1", "canal_id": cid, "proporcao": "9:16"}).get_json()["criados"][0]
    b = cl.post("/curtos/link/novo", json={"link": "https://a.com/2", "canal_id": outro, "proporcao": "9:16"}).get_json()["criados"][0]
    pa, pb = CT.carregar(base, a), CT.carregar(base, b)
    assert CT.proporcao_do(pa) == "1:1" and CT.proporcao_do(pb) == "9:16" and pb["config"].get("tambem_quadrado") is True
    assert CT.acabamento(base)["proporcao"] == "" and not CT.acabamento(base)["tambem_quadrado"]  # o padrão não mudou
    html = cl.get("/curtos/personalizar").get_data(as_text=True)
    assert 'id="pzAbas"' in html and "Personalização dos canais" in html and 'id="a_proporcao"' in html
    assert "Personalização dos canais" not in cl.get("/curtos/link").get_data(as_text=True).split("<h1>")[1].split("</h1>")[0]
