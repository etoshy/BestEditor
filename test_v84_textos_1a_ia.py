"""
v84 — a 1ª IA (a das buscas, página /prompt) também põe textos: texto na tela
por trecho, destaques e overlays de texto. Quando a IA de edição do Estúdio
manda os destaques dela (melhores), os da 1ª IA saem — menos os que a pessoa
editou à mão. Aqui: as marcas que tornam isso possível e a rota dos overlays.
"""
import json
import os

import pytest


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


@pytest.fixture
def client(A):
    return A.app.test_client()


def _job(A, jid):
    os.makedirs(A._job_dir(jid), exist_ok=True)
    A._JOBS[jid] = {"job_id": jid, "status": "aguardando_json", "created_at": 1.0, "language": "pt",
                    "providers": ["pexels"], "total_duration": 8.0, "pending_segments": [],
                    "segments": [{"start": 0, "end": 8, "text": "Em 1992 saiu Cães de Aluguel"}]}
    return A._JOBS[jid]


_RESP = {
    "segments": [
        {"start": 0, "end": 4, "provider": "pexels", "query": "old cinema", "on_screen_text": "1992"},
        {"start": 4, "end": 8, "provider": "pexels", "query": "film reel"},
    ],
    "overlays": [{"media_type": "text", "text": "CÃES DE ALUGUEL", "start": 1, "end": 3},
                 {"media_type": "image", "provider": "pexels", "query": "film camera", "start": 5, "end": 7}],
    "highlights": [{"start": 0.5, "end": 2.0, "estilo": "carimbo", "texto": "1992"}],
}


def test_submit_json_marca_os_textos_da_1a_ia(A, client, monkeypatch):
    job = _job(A, "t1a-marca")
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    client.post("/job/t1a-marca/submit-json", data={"ai_response": json.dumps(_RESP)})
    s0, s1 = job["pending_segments"]
    assert s0["texto_da_ia"] == "1992" and "texto_da_ia" not in s1
    assert all(o["origem"] == "ia_busca" for o in job["overlays"])
    assert job["destaques"] and all(d.get("origem") == "ia_busca" for d in job["destaques"])


def test_salvar_no_estudio_mantem_as_marcas(A, client, monkeypatch):
    job = _job(A, "t1a-salvar")
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    client.post("/job/t1a-salvar/submit-json", data={"ai_response": json.dumps(_RESP)})
    hl = [dict(d) for d in job["destaques"]]
    client.post("/job/t1a-salvar/confirm-segments", data={
        "acao": "salvar", "seg_0_on_screen_text": "1992", "seg_1_on_screen_text": "",
        "destaques_json": json.dumps(hl)})
    assert job["pending_segments"][0]["texto_da_ia"] == "1992"
    assert all(d.get("origem") == "ia_busca" for d in job["destaques"])


def test_rota_tira_e_devolve_so_os_overlays_de_texto_da_1a_ia(A, client, monkeypatch):
    job = _job(A, "t1a-ov")
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    client.post("/job/t1a-ov/submit-json", data={"ai_response": json.dumps(_RESP)})
    job["overlays"].append({"id": "meu", "media_type": "text", "text": "meu texto", "start": 6, "end": 7})
    d = client.post("/job/t1a-ov/overlays/textos-1a-ia", json={"acao": "remover"}).get_json()
    assert [o["text"] for o in d["overlays"]] == ["CÃES DE ALUGUEL"]
    assert sorted(o.get("text") or o["source"]["query"] for o in job["overlays"]) == ["film camera", "meu texto"]
    d = client.post("/job/t1a-ov/overlays/textos-1a-ia", json={"acao": "restaurar"}).get_json()
    assert [o["text"] for o in d["overlays"]] == ["CÃES DE ALUGUEL"] and len(job["overlays"]) == 3
    assert client.post("/job/t1a-ov/overlays/textos-1a-ia", json={"acao": "x"}).status_code == 400


def test_estudio_tem_a_opcao_de_limpar(A, client, monkeypatch):
    _job(A, "t1a-ui")
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    client.post("/job/t1a-ui/submit-json", data={"ai_response": json.dumps(_RESP)})
    A._JOBS["t1a-ui"]["status"] = "pronto_para_editar"
    html = client.get("/job/t1a-ui/edit-segments?modo=estudio").get_data(as_text=True)
    assert "limpar_1a" in html and "textos-1a-ia" in html
