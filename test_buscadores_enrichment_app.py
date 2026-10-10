"""
Teste de integração do modo "🔎 Este vídeo usa buscadores de imagem" no
pipeline principal — mesma ideia de duas rodadas de
`test_wikipedia_enrichment_app.py`, mas pros 4 buscadores de imagem por
navegador (bing/brave/yandex/startpage):

  1. Transcrição -> gera um prompt pedindo pra IA sugerir termos de
     busca (baseado no roteiro inteiro, com contexto) -> job fica em
     "aguardando_termos_buscadores".
  2. Usuário cola a resposta (JSON de termos) -> o site PESQUISA DE
     VERDADE esses termos nos buscadores marcados (mockada aqui — a
     busca em si já tem sua própria suíte em
     test_buscadores_enrichment.py) -> monta o prompt PRINCIPAL de
     edição, já enriquecido -> job fica em "aguardando_json" (fluxo
     normal a partir daqui).
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


def _inicia_transcricao_com_buscadores(client, synthetic_audio, marcado=True, providers=("pexels", "bing")):
    dados = {"interval_seconds": "7", "providers": list(providers)}
    if marcado:
        dados["usar_buscadores_inteligente"] = "on"
    with open(synthetic_audio, "rb") as f:
        dados["audio"] = (f, "audio.wav")
        r = client.post("/transcribe", data=dados, content_type="multipart/form-data")
    assert r.status_code == 302
    return r.headers["Location"].rstrip("/").rsplit("/", 2)[-2]


class TestEtapa1PromptDeBuscaDeTermos:
    def test_checkbox_marcada_gera_prompt_de_busca_e_para_ai(self, app_module, client, synthetic_audio, monkeypatch):
        segments = [{"start": 0.0, "end": 5.0, "text": "O iPhone 15 Pro foi lançado esse ano.", "words": []}]
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: segments)

        job_id = _inicia_transcricao_com_buscadores(client, synthetic_audio, marcado=True)
        _wait_status(app_module, job_id, {"aguardando_termos_buscadores", "erro_transcricao"})
        job = app_module._JOBS[job_id]

        assert job["status"] == "aguardando_termos_buscadores", job.get("error")
        assert "iPhone 15 Pro" in job["prompt_termos_buscadores"]
        assert '"termos"' in job["prompt_termos_buscadores"]
        assert "prompt" not in job  # o prompt PRINCIPAL ainda não foi montado nessa etapa

    def test_checkbox_marcada_sem_nenhum_buscador_ativa_bing_automaticamente(self, app_module, client, synthetic_audio, monkeypatch):
        segments = [{"start": 0.0, "end": 5.0, "text": "Fala qualquer.", "words": []}]
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: segments)
        job_id = _inicia_transcricao_com_buscadores(client, synthetic_audio, marcado=True, providers=("pexels",))
        _wait_status(app_module, job_id, {"aguardando_termos_buscadores", "erro_transcricao"})
        assert "bing" in app_module._JOBS[job_id]["providers"]

    def test_checkbox_desmarcada_pula_direto_pro_prompt_principal(self, app_module, client, synthetic_audio, monkeypatch):
        segments = [{"start": 0.0, "end": 5.0, "text": "O iPhone 15 Pro foi lançado esse ano.", "words": []}]
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: segments)

        job_id = _inicia_transcricao_com_buscadores(client, synthetic_audio, marcado=False)
        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        job = app_module._JOBS[job_id]

        assert job["status"] == "aguardando_json", job.get("error")
        assert "prompt_termos_buscadores" not in job
        assert "CONFIRMADOS como tendo resultado de imagem disponível" not in job["prompt"]

    def test_pagina_de_termos_buscadores_carrega(self, app_module, client, synthetic_audio, monkeypatch):
        segments = [{"start": 0.0, "end": 5.0, "text": "Fala qualquer.", "words": []}]
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: segments)
        job_id = _inicia_transcricao_com_buscadores(client, synthetic_audio, marcado=True)
        _wait_status(app_module, job_id, {"aguardando_termos_buscadores", "erro_transcricao"})

        r = client.get(f"/job/{job_id}/termos-buscadores")
        assert r.status_code == 200
        assert "termos".encode() in r.data.lower()

    def test_pagina_de_termos_buscadores_job_inexistente_404(self, client):
        r = client.get("/job/nao-existe/termos-buscadores")
        assert r.status_code == 404

    def test_wikipedia_tem_prioridade_quando_os_dois_marcados(self, app_module, client, synthetic_audio, monkeypatch):
        segments = [{"start": 0.0, "end": 5.0, "text": "Albert Einstein e o iPhone.", "words": []}]
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: segments)
        dados = {
            "interval_seconds": "7", "providers": ["pexels", "wikipedia", "bing"],
            "usar_wikipedia_inteligente": "on", "usar_buscadores_inteligente": "on",
        }
        with open(synthetic_audio, "rb") as f:
            dados["audio"] = (f, "audio.wav")
            r = client.post("/transcribe", data=dados, content_type="multipart/form-data")
        job_id = r.headers["Location"].rstrip("/").rsplit("/", 2)[-2]
        _wait_status(app_module, job_id, {"aguardando_termos_wikipedia", "aguardando_termos_buscadores", "erro_transcricao"})
        job = app_module._JOBS[job_id]
        assert job["status"] == "aguardando_termos_wikipedia", job.get("error")  # wikipedia venceu


class TestEtapa2ColarRespostaEBuscarDeVerdade:
    def _job_pronto_pra_colar_termos(self, app_module, client, synthetic_audio, monkeypatch, texto="O iPhone 15 Pro foi lançado esse ano.", providers=("pexels", "bing")):
        segments = [{"start": 0.0, "end": 5.0, "text": texto, "words": []}]
        monkeypatch.setattr(app_module, "transcribe_audio", lambda *a, **k: segments)
        job_id = _inicia_transcricao_com_buscadores(client, synthetic_audio, marcado=True, providers=providers)
        _wait_status(app_module, job_id, {"aguardando_termos_buscadores", "erro_transcricao"})
        assert app_module._JOBS[job_id]["status"] == "aguardando_termos_buscadores"
        return job_id

    def test_colar_termos_busca_de_verdade_e_enriquece_o_prompt_principal(self, app_module, client, synthetic_audio, monkeypatch):
        job_id = self._job_pronto_pra_colar_termos(app_module, client, synthetic_audio, monkeypatch)

        chamadas = []

        def fake_buscar(termos, providers, **kwargs):
            chamadas.append((termos, providers))
            return [{"termo": "iPhone 15 Pro", "provider": "bing", "descricao": "smartphone da Apple"}]

        monkeypatch.setattr(app_module.buscadores_enrichment, "buscar_confirmados_nos_buscadores", fake_buscar)

        r = client.post(f"/job/{job_id}/termos-buscadores", data={"resposta_termos": '{"termos": ["iPhone 15 Pro"]}'})
        assert r.status_code == 302

        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        job = app_module._JOBS[job_id]
        assert job["status"] == "aguardando_json", job.get("error")

        assert chamadas == [(["iPhone 15 Pro"], ["bing"])]
        assert job["buscadores_confirmados"] == [
            {"termo": "iPhone 15 Pro", "provider": "bing", "descricao": "smartphone da Apple"}
        ]
        assert "CONFIRMADOS como tendo resultado de imagem disponível" in job["prompt"]
        assert '"iPhone 15 Pro"' in job["prompt"]
        assert job["fase"] == "Pronto!"

    def test_termos_nao_confirmados_ainda_gera_prompt_normal(self, app_module, client, synthetic_audio, monkeypatch):
        job_id = self._job_pronto_pra_colar_termos(app_module, client, synthetic_audio, monkeypatch)
        monkeypatch.setattr(app_module.buscadores_enrichment, "buscar_confirmados_nos_buscadores", lambda termos, providers, **k: [])

        r = client.post(f"/job/{job_id}/termos-buscadores", data={"resposta_termos": '{"termos": ["Termo Que Nao Existe"]}'})
        assert r.status_code == 302
        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        job = app_module._JOBS[job_id]
        assert job["status"] == "aguardando_json", job.get("error")
        assert job["buscadores_confirmados"] == []
        assert "CONFIRMADOS como tendo resultado de imagem disponível" not in job["prompt"]

    def test_lista_de_termos_vazia_nao_chama_a_busca_e_segue_normal(self, app_module, client, synthetic_audio, monkeypatch):
        job_id = self._job_pronto_pra_colar_termos(app_module, client, synthetic_audio, monkeypatch, texto="nada de especial aqui.")

        def fake_buscar_nao_deveria_ser_chamada(termos, providers, **k):
            raise AssertionError("não deveria chamar a busca com lista de termos vazia")

        monkeypatch.setattr(app_module.buscadores_enrichment, "buscar_confirmados_nos_buscadores", fake_buscar_nao_deveria_ser_chamada)

        r = client.post(f"/job/{job_id}/termos-buscadores", data={"resposta_termos": '{"termos": []}'})
        assert r.status_code == 302
        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        job = app_module._JOBS[job_id]
        assert job["status"] == "aguardando_json", job.get("error")
        assert job["buscadores_confirmados"] == []

    def test_resposta_invalida_mostra_erro_sem_avancar(self, app_module, client, synthetic_audio, monkeypatch):
        job_id = self._job_pronto_pra_colar_termos(app_module, client, synthetic_audio, monkeypatch)

        r = client.post(f"/job/{job_id}/termos-buscadores", data={"resposta_termos": "isso não é json nenhum"})
        assert r.status_code == 200  # re-renderiza a mesma página com erro, não redireciona
        assert "JSON".encode() in r.data
        assert app_module._JOBS[job_id]["status"] == "aguardando_termos_buscadores"

    def test_job_inexistente_na_etapa_2_404(self, client):
        r = client.post("/job/nao-existe/termos-buscadores", data={"resposta_termos": "{}"})
        assert r.status_code == 404

    def test_pagina_de_prompt_principal_mostra_termos_apos_as_duas_etapas(self, app_module, client, synthetic_audio, monkeypatch):
        job_id = self._job_pronto_pra_colar_termos(app_module, client, synthetic_audio, monkeypatch)
        monkeypatch.setattr(
            app_module.buscadores_enrichment, "buscar_confirmados_nos_buscadores",
            lambda termos, providers, **k: [{"termo": "iPhone 15 Pro", "provider": "bing", "descricao": "smartphone"}],
        )
        client.post(f"/job/{job_id}/termos-buscadores", data={"resposta_termos": '{"termos": ["iPhone 15 Pro"]}'})
        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})

        r = client.get(f"/job/{job_id}/prompt")
        assert r.status_code == 200
        assert "iPhone 15 Pro".encode() in r.data
        assert "Termos confirmados".encode() in r.data

    def test_providers_passados_pra_busca_sao_so_os_buscadores_de_navegador(self, app_module, client, synthetic_audio, monkeypatch):
        """job["providers"] pode ter pexels/wikipedia junto -- só os 4
        buscadores de navegador devem ser passados pra função de busca."""
        job_id = self._job_pronto_pra_colar_termos(
            app_module, client, synthetic_audio, monkeypatch, providers=("pexels", "wikipedia", "bing", "brave"),
        )
        capturado = {}

        def fake_buscar(termos, providers, **k):
            capturado["providers"] = providers
            return []

        monkeypatch.setattr(app_module.buscadores_enrichment, "buscar_confirmados_nos_buscadores", fake_buscar)
        client.post(f"/job/{job_id}/termos-buscadores", data={"resposta_termos": '{"termos": ["x"]}'})
        _wait_status(app_module, job_id, {"aguardando_json", "erro_transcricao"})
        assert sorted(capturado["providers"]) == ["bing", "brave"]
