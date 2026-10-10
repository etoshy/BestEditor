"""
Teste de integração do modo "🧠 Este vídeo tem fontes de imagens da
Wikipedia" no pipeline principal — fluxo de DUAS rodadas de IA:

  1. Transcrição -> gera um prompt pedindo pra IA sugerir termos de
     busca pra Wikipedia (baseado no roteiro inteiro, com contexto) ->
     job fica em "aguardando_termos_wikipedia".
  2. Usuário cola a resposta (JSON de termos) -> o site PESQUISA DE
     VERDADE esses termos na Wikipedia (mockada aqui — a busca em si já
     tem sua própria suíte em test_wikipedia_enrichment.py) -> monta o
     prompt PRINCIPAL de edição, já enriquecido -> job fica em
     "aguardando_json" (fluxo normal a partir daqui).
"""
import time

import pytest


@pytest.fixture
def app_module(monkeypatch):
    import app as _app_module

    def _sem_previa(segment, **kwargs):
        return {"ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mockado"}

    monkeypatch.setattr(_app_module, "fetch_segment_preview_lightweight", _sem_previa)
    yield _app_module


@pytest.fixture
def client(app_module):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _wait_status(app_module, job_id, alvo, timeout=20):
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        status = app_module._JOBS[job_id]["status"]
        if status in alvo:
            return status
        time.sleep(0.1)
    raise TimeoutError(f"job {job_id} não chegou a {alvo} em {timeout}s (ficou em {status!r})")


def _inicia_transcricao_com_wikipedia(client, synthetic_audio, marcado=True):
    dados = {"interval_seconds": "7", "providers": ["pexels"]}
    if marcado:
        dados["usar_wikipedia_inteligente"] = "on"
    with open(synthetic_audio, "rb") as f:
        dados["audio"] = (f, "audio.wav")
        r = client.post("/transcribe", data=dados, content_type="multipart/form-data")
    assert r.status_code == 302
    return r.headers["Location"].rstrip("/").rsplit("/", 2)[-2]


class TestEtapa1PromptDeBuscaDeTermos:
    def test_checkbox_marcada_gera_prompt_de_busca_e_para_ai(self, app_module, client, synthetic_audio, monkeypatch):
        segments = [{"start": 0.0, "end": 5.0, "text": "Albert Einstein nasceu na Alemanha.", "words": []}]
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: segments)

        job_id = _inicia_transcricao_com_wikipedia(client, synthetic_audio, marcado=True)
        _wait_status(app_module, job_id, {"aguardando_termos_wikipedia", "erro_transcricao"})
        job = app_module._JOBS[job_id]

        assert job["status"] == "aguardando_termos_wikipedia", job.get("error")
        assert "Albert Einstein" in job["prompt_termos_wikipedia"]
        assert '"termos"' in job["prompt_termos_wikipedia"]
        assert "prompt" not in job  # o prompt PRINCIPAL ainda não foi montado nessa etapa
        assert "wikipedia" in job["providers"]  # já ativado, mesmo antes da busca acontecer

    def test_checkbox_desmarcada_pula_direto_pro_prompt_principal(self, app_module, client, synthetic_audio, monkeypatch):
        segments = [{"start": 0.0, "end": 5.0, "text": "Albert Einstein nasceu na Alemanha.", "words": []}]
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: segments)

        job_id = _inicia_transcricao_com_wikipedia(client, synthetic_audio, marcado=False)
        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        job = app_module._JOBS[job_id]

        assert job["status"] == "aguardando_json", job.get("error")
        assert "prompt_termos_wikipedia" not in job
        assert "JÁ FOI PESQUISADO" not in job["prompt"]

    def test_pagina_de_termos_wikipedia_carrega(self, app_module, client, synthetic_audio, monkeypatch):
        segments = [{"start": 0.0, "end": 5.0, "text": "Fala qualquer.", "words": []}]
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: segments)
        job_id = _inicia_transcricao_com_wikipedia(client, synthetic_audio, marcado=True)
        _wait_status(app_module, job_id, {"aguardando_termos_wikipedia", "erro_transcricao"})

        r = client.get(f"/job/{job_id}/termos-wikipedia")
        assert r.status_code == 200
        assert "termos".encode() in r.data.lower()

    def test_pagina_de_termos_wikipedia_job_inexistente_404(self, client):
        r = client.get("/job/nao-existe/termos-wikipedia")
        assert r.status_code == 404


class TestEtapa2ColarRespostaEBuscarDeVerdade:
    def _job_pronto_pra_colar_termos(self, app_module, client, synthetic_audio, monkeypatch, texto="Albert Einstein nasceu na Alemanha."):
        segments = [{"start": 0.0, "end": 5.0, "text": texto, "words": []}]
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: segments)
        job_id = _inicia_transcricao_com_wikipedia(client, synthetic_audio, marcado=True)
        _wait_status(app_module, job_id, {"aguardando_termos_wikipedia", "erro_transcricao"})
        assert app_module._JOBS[job_id]["status"] == "aguardando_termos_wikipedia"
        return job_id

    def test_colar_termos_busca_de_verdade_e_enriquece_o_prompt_principal(self, app_module, client, synthetic_audio, monkeypatch):
        job_id = self._job_pronto_pra_colar_termos(app_module, client, synthetic_audio, monkeypatch)

        chamadas = []

        def fake_buscar(termos, **kwargs):
            chamadas.append(termos)
            return [{"termo": "Albert Einstein", "titulo_pagina": "Albert Einstein", "descricao": "físico alemão"}]

        monkeypatch.setattr(app_module.wikipedia_enrichment, "buscar_entidades_confirmadas_na_wikipedia", fake_buscar)

        r = client.post(f"/job/{job_id}/termos-wikipedia", data={"resposta_termos": '{"termos": ["Albert Einstein"]}'})
        assert r.status_code == 302

        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        job = app_module._JOBS[job_id]
        assert job["status"] == "aguardando_json", job.get("error")

        assert chamadas == [["Albert Einstein"]]
        assert job["wikipedia_entidades"] == [
            {"termo": "Albert Einstein", "titulo_pagina": "Albert Einstein", "descricao": "físico alemão"}
        ]
        assert "JÁ FOI PESQUISADO" in job["prompt"]
        assert '"Albert Einstein"' in job["prompt"]
        assert job["fase"] == "Pronto!"

    def test_termos_nao_confirmados_ainda_gera_prompt_normal(self, app_module, client, synthetic_audio, monkeypatch):
        job_id = self._job_pronto_pra_colar_termos(app_module, client, synthetic_audio, monkeypatch)
        monkeypatch.setattr(app_module.wikipedia_enrichment, "buscar_entidades_confirmadas_na_wikipedia", lambda termos, **k: [])

        r = client.post(f"/job/{job_id}/termos-wikipedia", data={"resposta_termos": '{"termos": ["Termo Que Nao Existe"]}'})
        assert r.status_code == 302
        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        job = app_module._JOBS[job_id]
        assert job["status"] == "aguardando_json", job.get("error")
        assert job["wikipedia_entidades"] == []
        assert "JÁ FOI PESQUISADO" not in job["prompt"]

    def test_lista_de_termos_vazia_nao_chama_a_busca_e_segue_normal(self, app_module, client, synthetic_audio, monkeypatch):
        """Se a IA (etapa 1) devolveu uma lista vazia (roteiro sem
        entidade real nenhuma), não faz sentido nem chamar a busca --
        vai direto pro prompt principal sem entidades."""
        job_id = self._job_pronto_pra_colar_termos(app_module, client, synthetic_audio, monkeypatch, texto="nada de especial aqui.")

        def fake_buscar_nao_deveria_ser_chamada(termos, **k):
            raise AssertionError("não deveria chamar a busca com lista de termos vazia")

        monkeypatch.setattr(app_module.wikipedia_enrichment, "buscar_entidades_confirmadas_na_wikipedia", fake_buscar_nao_deveria_ser_chamada)

        r = client.post(f"/job/{job_id}/termos-wikipedia", data={"resposta_termos": '{"termos": []}'})
        assert r.status_code == 302
        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        job = app_module._JOBS[job_id]
        assert job["status"] == "aguardando_json", job.get("error")
        assert job["wikipedia_entidades"] == []

    def test_resposta_invalida_mostra_erro_sem_avancar(self, app_module, client, synthetic_audio, monkeypatch):
        job_id = self._job_pronto_pra_colar_termos(app_module, client, synthetic_audio, monkeypatch)

        r = client.post(f"/job/{job_id}/termos-wikipedia", data={"resposta_termos": "isso não é json nenhum"})
        assert r.status_code == 200  # re-renderiza a mesma página com erro, não redireciona
        assert "JSON".encode() in r.data
        # o job continua esperando a resposta certa -- não avançou
        assert app_module._JOBS[job_id]["status"] == "aguardando_termos_wikipedia"

    def test_job_inexistente_na_etapa_2_404(self, client):
        r = client.post("/job/nao-existe/termos-wikipedia", data={"resposta_termos": "{}"})
        assert r.status_code == 404

    def test_pagina_de_prompt_principal_mostra_entidades_apos_as_duas_etapas(self, app_module, client, synthetic_audio, monkeypatch):
        job_id = self._job_pronto_pra_colar_termos(app_module, client, synthetic_audio, monkeypatch)
        monkeypatch.setattr(
            app_module.wikipedia_enrichment, "buscar_entidades_confirmadas_na_wikipedia",
            lambda termos, **k: [{"termo": "Albert Einstein", "titulo_pagina": "Albert Einstein", "descricao": "físico"}],
        )
        client.post(f"/job/{job_id}/termos-wikipedia", data={"resposta_termos": '{"termos": ["Albert Einstein"]}'})
        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})

        r = client.get(f"/job/{job_id}/prompt")
        assert r.status_code == 200
        assert "Albert Einstein".encode() in r.data
        assert "Entidades confirmadas".encode() in r.data
