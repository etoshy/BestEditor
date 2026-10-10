"""
Teste de /jobs (histórico): cada status tem que ter uma ação clicável
na tabela -- incluindo os 4 status intermediários dos modos "fontes da
Wikipedia"/"buscadores de imagem" (aguardando_termos_wikipedia,
buscando_termos_wikipedia, aguardando_termos_buscadores,
buscando_termos_buscadores), que ficavam SEM NENHUM link antes desse
fix (a coluna "Ação" simplesmente vinha vazia, sem jeito de voltar pro
fluxo a partir do histórico).
"""
import pytest


@pytest.fixture
def app_module():
    import app as _app_module
    yield _app_module


@pytest.fixture
def client(app_module):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _job_minimo(job_id, status, **extra):
    job = {"job_id": job_id, "status": status, "original_filename": "audio.wav", "created_at": 1000.0}
    job.update(extra)
    return job


@pytest.mark.parametrize("status,texto_esperado_no_link,url_esperada", [
    ("transcrevendo", "Ver progresso", "transcribing_status_page"),
    ("aguardando_termos_wikipedia", "Colar termos da Wikipedia", "show_termos_wikipedia"),
    ("buscando_termos_wikipedia", "Ver progresso", "transcribing_status_page"),
    ("aguardando_termos_buscadores", "Colar termos dos buscadores", "show_termos_buscadores"),
    ("buscando_termos_buscadores", "Ver progresso", "transcribing_status_page"),
    ("aguardando_json", "Ver prompt", "show_prompt"),
    ("buscando_previas", "Ver progresso", "fetching_previews_page"),
    ("pronto_para_editar", "Editar timeline", "edit_segments_page"),
    ("montando", "Ver resultado", "job_status_page"),
    ("concluido", "Ver resultado", "job_status_page"),
    ("erro", "Ver resultado", "job_status_page"),
])
def test_cada_status_tem_link_de_acao(app_module, client, status, texto_esperado_no_link, url_esperada):
    job_id = f"job-{status}"
    app_module._JOBS[job_id] = _job_minimo(job_id, status)
    r = client.get("/jobs")
    assert r.status_code == 200
    html = r.data.decode("utf-8")
    assert texto_esperado_no_link in html
    with app_module.app.test_request_context():
        from flask import url_for
        link_esperado = url_for(url_esperada, job_id=job_id)
    assert link_esperado in html
    del app_module._JOBS[job_id]


def test_erro_transcricao_mostra_mensagem_em_vez_de_link(app_module, client):
    job_id = "job-erro-transcricao"
    app_module._JOBS[job_id] = _job_minimo(job_id, "erro_transcricao", error="Falha ao transcrever: arquivo corrompido")
    r = client.get("/jobs")
    html = r.data.decode("utf-8")
    assert "Falha ao transcrever" in html
    del app_module._JOBS[job_id]


def test_lista_vazia_mostra_mensagem_amigavel(app_module, client):
    app_module._JOBS.clear()
    r = client.get("/jobs")
    assert r.status_code == 200
    assert "Nenhum job ainda".encode() in r.data
