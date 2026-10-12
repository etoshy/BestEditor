"""v84_67 — 📁 as mídias que a pessoa ENVIOU e 🖥 os sites citados entram na edição da IA."""
import os

import pytest

import dp_direcao
import prompt_edicao as pe


def _job_lib(tmp_path):
    foto, video = tmp_path / "a1_foto.jpg", tmp_path / "b2_site.mp4"
    foto.write_bytes(b"x")
    video.write_bytes(b"x")
    return {
        "total_duration": 12.0,
        "pending_segments": [{"start": i * 4.0, "end": i * 4.0 + 4, "provider": "pexels", "query": f"q{i}", "media_type": "video"}
                             for i in range(3)],
        "segments": [{"start": 0, "end": 4, "text": "Tudo começou num fórum."},
                     {"start": 4, "end": 8, "text": "O site exemplo.com.br publicou a lista."},
                     {"start": 8, "end": 12, "text": "E o dono do fórum sumiu."}],
        "media_library": [{"id": "a1", "filename": "a1_foto.jpg", "path": str(foto), "media_type": "image", "descricao": "foto do dono do fórum"},
                          {"id": "b2", "filename": "b2_site.mp4", "path": str(video), "media_type": "video",
                           "rotulo": "exemplo.com.br — rolando a página (12s)"}],
        "links_tela": ["https://exemplo.com.br/lista"],
    }


def test_prompt_lista_as_midias_enviadas_e_os_sites(tmp_path):
    job = _job_lib(tmp_path)
    segs = [dict(s) for s in job["pending_segments"]]
    segs[2]["override_source"] = {"source": "local_file", "value": job["media_library"][0]["path"], "kind": "image"}
    t = pe.montar_prompt(job, {"direcao": "sys_tudo", "segmentos": segs})
    assert "bib:a1 — foto: foto do dono do fórum" in t and "já está em T3" in t
    assert "bib:b2 — vídeo: exemplo.com.br — rolando a página" in t and "AINDA NÃO USADA" in t
    assert "(= bib:a1, já colocada)" in t
    assert "MÍDIAS ENVIADAS" in t and '"midia": "bib:<id>' in t
    assert "https://exemplo.com.br/lista" in t and "citados na fala: exemplo.com.br" in t and "SITE NA TELA" in t


def test_arquivo_da_pessoa_nao_e_trocado(tmp_path):
    job = _job_lib(tmp_path)
    segs = [dict(s) for s in job["pending_segments"]]
    segs[0]["override_source"] = {"source": "local_file", "value": "/outro/upload.mp4"}
    assert "arquivo escolhido pela pessoa — não troque" in pe.montar_prompt(job, {"direcao": "sys_tudo", "segmentos": segs})


def test_quadro_de_pagina_vale_mesmo_em_direcao_sem_quadros(tmp_path, monkeypatch):
    real = dp_direcao.editoriais_da
    monkeypatch.setattr(dp_direcao, "editoriais_da", lambda p: dict(real(p), ativo=False))
    t = pe.montar_prompt(_job_lib(tmp_path), {"direcao": "sys_tudo"})
    assert "NÃO usar nesta direção (exceto os de PROVA abaixo)" in t
    assert "Quadros de PROVA (pagina, post)" in t and "- pagina = " in t and "- ficha = " not in t
    monkeypatch.setattr(dp_direcao, "editoriais_da", lambda p: dict(real(p), ativo=True, tipos=["numero"]))
    t = pe.montar_prompt(_job_lib(tmp_path), {"direcao": "sys_tudo"})
    assert "- numero = " in t and "- pagina = " in t and "- ficha = " not in t


def test_ler_resposta_com_midia():
    r = pe.ler_resposta('{"trechos": [{"trecho": 1, "midia": "bib:a1", "camera": "in"}, {"trecho": 2, "midia": "bib:zz"},'
                        ' {"trecho": 3, "midia": "b2"}]}', 3, 12.0, [], foto=[False, False, False],
                        biblioteca={"a1": "image", "b2": "video"})
    t = {x["indice"]: x for x in r["trechos"]}
    assert t[0]["midia"] == "a1" and t[0]["camera"] == "in"  # virou foto: câmera vale
    assert 1 not in t and any("bib:zz" in a for a in r["avisos"])
    assert t[2]["midia"] == "b2"


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def _job(A, jid, tmp_path):
    os.makedirs(A._job_dir(jid), exist_ok=True)
    lib = os.path.join(A._job_dir(jid), "media_library")
    os.makedirs(lib, exist_ok=True)
    foto = os.path.join(lib, "a1_foto.jpg")
    from PIL import Image
    Image.new("RGB", (64, 36), "red").save(foto)
    up = os.path.join(A._job_dir(jid), "uploads", "seg0_meu.jpg")
    os.makedirs(os.path.dirname(up), exist_ok=True)
    Image.new("RGB", (64, 36), "blue").save(up)
    fora = str(tmp_path / "fora.jpg")
    Image.new("RGB", (64, 36), "green").save(fora)
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 8.0,
                    "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "q0", "media_type": "video",
                                          "override_source": {"source": "local_file", "value": up}},
                                         {"start": 4.0, "end": 8.0, "provider": "pexels", "query": "q1", "media_type": "video", "override_source": None}],
                    "segment_previews": [None, None], "overlays": [], "cutaway_suggestions": [],
                    "media_library": [{"id": "a1", "filename": "a1_foto.jpg", "path": foto, "media_type": "image"}]}
    return A._JOBS[jid], foto, up, fora


def test_salvar_com_midia_da_ia_e_desfazer(A, tmp_path, monkeypatch):
    jid = "midias-ia"
    job, foto, up, fora = _job(A, jid, tmp_path)
    monkeypatch.setattr(A, "_start_assembly", lambda *a: pytest.fail("não deveria montar"))
    c = A.app.test_client()
    h = {"X-Requested-With": "fetch"}
    # a IA pôs a foto da biblioteca nos dois trechos
    d = c.post(f"/job/{jid}/confirm-segments", data={"acao": "salvar", "seg_0_source_mode": "upload", "seg_0_biblioteca": "a1",
                                                      "seg_1_source_mode": "upload", "seg_1_biblioteca": "a1"}, headers=h).get_json()
    assert d["ok"]
    for s in job["pending_segments"]:
        assert s["override_source"]["value"] == foto and s["override_source"]["biblioteca"] == "a1" and s["media_type"] == "image"
    # desfazer: o trecho 1 volta pro upload dele (caminho dentro do projeto); o 2 volta pro automático
    c.post(f"/job/{jid}/confirm-segments", data={"acao": "salvar", "seg_0_source_mode": "upload", "seg_0_local_value": up,
                                                 "seg_1_source_mode": "auto", "seg_1_media_type": "video"}, headers=h)
    assert job["pending_segments"][0]["override_source"]["value"] == up and not job["pending_segments"][1].get("override_source")
    assert job["pending_segments"][1]["media_type"] == "video"
    # caminho de fora do projeto nunca entra
    c.post(f"/job/{jid}/confirm-segments", data={"acao": "salvar", "seg_0_source_mode": "upload", "seg_0_local_value": fora,
                                                 "seg_1_source_mode": "upload", "seg_1_local_value": "/etc/passwd"}, headers=h)
    assert job["pending_segments"][0]["override_source"]["value"] == up and not job["pending_segments"][1].get("override_source")


def test_rotas_descricao_links_e_resposta(A, tmp_path):
    jid = "midias-ia2"
    job, foto, _up, _fora = _job(A, jid, tmp_path)
    c = A.app.test_client()
    assert c.post(f"/job/{jid}/library-item/a1/descricao", json={"descricao": "  foto do   dono "}).get_json()["descricao"] == "foto do dono"
    assert c.post(f"/job/{jid}/library-item/zz/descricao", json={"descricao": "x"}).status_code == 404
    d = c.post(f"/job/{jid}/links-tela", json={"links": "https://site.com/a\nnão é link\nhttp://b.org"}).get_json()
    assert d["links"] == ["https://site.com/a", "http://b.org"] and job["links_tela"] == d["links"]
    p = c.post(f"/job/{jid}/edicao/prompt", json={"direcao": "sys_tudo"}).get_json()["prompt"]
    assert "bib:a1 — foto: foto do dono" in p and "https://site.com/a" in p
    r = c.post(f"/job/{jid}/edicao/resposta", json={"texto": '{"trechos": [{"trecho": 2, "midia": "bib:a1"}]}', "foto": [False, False]}).get_json()
    assert r["trechos"][0]["midia"] == "a1"
    html = c.get(f"/job/{jid}/edit-segments").get_data(as_text=True)
    assert 'id="iaLinks"' in html and '"descricao": "foto do dono"' in html and "https://site.com/a" in html
