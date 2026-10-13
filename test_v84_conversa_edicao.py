"""v84_83 — 💬 conversar com a IA no Estúdio sobre a parte selecionada (e 🔄/🗑 sem IA, no JS)."""
import json
import os

import pytest

import conversa_edicao as ce
import dp_visual

EF = next(e["id"] for e in dp_visual.efeitos() if e["id"] != "none" and not dp_visual.efeito_e_movimento(e["id"]))
HL = next(iter(__import__("dp_destaques").catalogo()))
CAM = next(e["id"] for e in dp_visual.efeitos() if dp_visual.efeito_e_movimento(e["id"]))


def _job():
    segs = [{"start": float(a), "end": float(a + 5), "provider": "pexels", "query": f"cena {k}",
             "media_type": "image" if k % 2 else "video", "override_source": None} for k, a in enumerate(range(0, 50, 5))]
    return {"job_id": "x", "total_duration": 50.0, "pending_segments": segs,
            "destaques": [{"id": "d1", "estilo": HL, "start": 1.0, "end": 3.0, "texto": "Primeiro"},
                          {"id": "d2", "estilo": HL, "start": 31.0, "end": 33.0, "texto": "Segundo"}],
            "segments": [{"start": 0, "end": 25, "text": "a história começa aqui"}, {"start": 25, "end": 50, "text": "e termina ali"}]}


def test_prompt_foca_na_selecao_e_vizinhos():
    job = _job()
    p = ce.montar_prompt(job, {}, "deixa mais dramático", {"trechos": [6]}, [{"pedido": "oi", "resposta": "olá"}])
    assert "T7 [" in p and "◀ SELECIONADO" in p and "T5 [" in p and "T9 [" in p  # 2 vizinhos de cada lado
    assert "T1 [" not in p and "T10 [" not in p
    assert f"D2 {HL}" in p and "D1 " not in p  # só os destaques da janela
    assert "Eu: oi" in p and "deixa mais dramático" in p
    todo = ce.montar_prompt(job, {}, "tira todos os zooms", {})
    assert "T1 [" in todo and "T10 [" in todo and "vídeo todo" in todo
    s = ce.sistema()
    assert "## Responda SÓ com este JSON" in s and EF in s and "mudar_destaques" in s


def test_foco_por_emenda_destaque_e_tempo():
    job = _job()
    segs, ds = job["pending_segments"], job["destaques"]
    assert ce.foco_em_trechos({"emendas": [2]}, segs, ds) == [2, 3]
    assert ce.foco_em_trechos({"destaques": [1]}, segs, ds) == [6]
    assert ce.foco_em_trechos({"start": 12, "end": 16}, segs, ds) == [2, 3]
    assert ce.foco_em_trechos({"trechos": [99]}, segs, ds) == []


def test_ler_valida_trechos_e_destaques():
    job = _job()
    estado = {"destaques": job["destaques"]}
    txt = json.dumps({"resposta": "Feito.", "trechos": [{"trecho": 3, "efeito": EF, "transition": "fadeblack"},
                                                       {"trecho": 1, "efeito": CAM},          # câmera em vídeo: ignorado
                                                       {"trecho": 40, "efeito": EF}],         # não existe
                      "mudar_destaques": [{"destaque": 2, "texto": "Novo", "zona": "alto", "estilo": "nao_existe"}, {"destaque": 9, "texto": "x"}],
                      "remover_destaques": ["D1", 7]})
    p = ce.ler(txt, job, estado, [])
    assert p["resposta"] == "Feito." and p["substituir_destaques"] is False
    assert p["trechos"] == [{"indice": 2, "efeito": EF, "transition": "fadeblack"}]
    assert p["mudar_destaques"] == [{"id": "d2", "texto": "Novo", "zona": "alto"}]
    assert p["remover_destaques"] == ["d1"]
    assert any("40" in a for a in p["avisos"]) and any("nao_existe" in a for a in p["avisos"])


@pytest.fixture
def A(monkeypatch, tmp_path):
    import app as _app
    import ia_servico
    _app.app.config["TESTING"] = True
    monkeypatch.setitem(_app._JOBS, "cv1", dict(_job(), job_id="cv1"))
    return _app, ia_servico


def test_rota_com_ia_desligada_e_ligada(A, monkeypatch):
    app, ia = A
    c = app.app.test_client()
    monkeypatch.setattr(ia, "motivo_desligado", lambda r=None, c=None: "a IA está desligada")
    r = c.post("/job/cv1/edicao/conversa", json={"pedido": "tira o zoom"})
    assert r.status_code == 400 and r.get_json()["ia_desligada"]
    monkeypatch.setattr(ia, "motivo_desligado", lambda r=None, c=None: None)
    vistos = {}

    def falso(recurso, system, conteudo, **k):
        vistos.update(recurso=recurso, system=system, conteudo=conteudo)
        return json.dumps({"resposta": "Tirei.", "trechos": [{"trecho": 2, "efeito": None}],
                           "destaques": [{"estilo": HL, "texto": "termina ali", "avulso": True, "start": 40, "end": 43}]})
    monkeypatch.setattr(ia, "chamar", falso)
    assert c.post("/job/cv1/edicao/conversa", json={"pedido": "  "}).status_code == 400
    d = c.post("/job/cv1/edicao/conversa", json={"pedido": "tira o efeito desse", "foco": {"trechos": [1]},
                                                  "estado": {"segmentos": _job()["pending_segments"]}}).get_json()
    assert d["ok"] and d["resposta"] == "Tirei." and d["trechos"] == [{"indice": 1, "efeito": None}]
    assert d["destaques"][0]["id"] and d["destaques"][0]["texto"] == "termina ali"
    assert vistos["recurso"] == "edicao" and "◀ SELECIONADO" in vistos["conteudo"] and "fala:" in vistos["conteudo"]
    monkeypatch.setattr(ia, "chamar", lambda *a, **k: "isso não é json")
    assert c.post("/job/cv1/edicao/conversa", json={"pedido": "x"}).status_code == 502


def test_editor_tem_os_botoes_e_o_chat():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "estudio.html"), encoding="utf-8") as f:
        h = f.read()
    for trecho in ('id="btnChatIA"', 'id="chatIA"', "function barraRapida", "function parecido", "/edicao/conversa", "function voltarEdicao"):
        assert trecho in h
