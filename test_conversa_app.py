"""
Teste de integração das rotas de "Simular Conversa" (/gerar-voz/conversa)
— motor de voz mockado (tom puro via ffmpeg), mesmo padrão de
test_narracoes_app.py.
"""
import io
import subprocess
import time

import pytest


@pytest.fixture
def app_module():
    import app as _app_module
    yield _app_module


@pytest.fixture
def client(app_module):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture
def motor_falso(app_module):
    """Mesmo motivo do fixture equivalente em test_narracoes_app.py:
    precisa mockar tanto `tts.voice_generator.gerar_audio` quanto a
    referência já importada em `conversa.py` (`from tts.voice_generator
    import gerar_audio` dentro da função, então mockar o módulo já
    basta -- `conversa.py` importa de dentro da função, igual
    narracoes.py)."""
    import tts.voice_generator as vg_mod

    chamadas = []

    def fake_gerar_audio(engine, texto, output_path, **kwargs):
        chamadas.append({"engine": engine, "texto": texto, "kwargs": kwargs})
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=0.5",
             "-ar", "22050", "-ac", "1", output_path],
            capture_output=True, check=True,
        )
        return output_path

    original = vg_mod.gerar_audio
    vg_mod.gerar_audio = fake_gerar_audio
    yield chamadas
    vg_mod.gerar_audio = original


def _cria_conversa(client, nome="Teste"):
    r = client.post("/gerar-voz/conversa", data={"nome": nome})
    assert r.status_code == 302
    return r.headers["Location"].rstrip("/").rsplit("/", 1)[-1]


def _espera_fala(client, conversa_id, fala_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = client.get(f"/gerar-voz/conversa/{conversa_id}/fala/{fala_id}/status").get_json()
        if not st["running"]:
            return st
        time.sleep(0.1)
    raise TimeoutError("fala não terminou a tempo")


def _id_primeira_fala(app_module, conversa_id):
    import conversa as cv
    conversa = cv.carregar_conversa(app_module.BASE_DIR, conversa_id)
    return conversa["falas"][0]["id"]


class TestListaECriacao:
    def test_lista_vazia_carrega(self, client):
        r = client.get("/gerar-voz/conversa")
        assert r.status_code == 200

    def test_criar_conversa(self, client):
        r = client.post("/gerar-voz/conversa", data={"nome": "Minha conversa"})
        assert r.status_code == 302

    def test_criar_conversa_aparece_na_lista(self, client):
        _cria_conversa(client, "Conversa Listada")
        r = client.get("/gerar-voz/conversa")
        assert "Conversa Listada".encode() in r.data

    def test_detalhe_de_conversa_inexistente_404(self, client):
        r = client.get("/gerar-voz/conversa/nao-existe")
        assert r.status_code == 404

    def test_renomear_conversa(self, client):
        conversa_id = _cria_conversa(client, "Nome velho")
        r = client.post(f"/gerar-voz/conversa/{conversa_id}/renomear", data={"nome": "Nome novo"})
        assert r.status_code == 302
        r2 = client.get(f"/gerar-voz/conversa/{conversa_id}")
        assert "Nome novo".encode() in r2.data

    def test_excluir_conversa(self, client):
        conversa_id = _cria_conversa(client, "Vai ser excluida")
        client.post(f"/gerar-voz/conversa/{conversa_id}/excluir")
        r = client.get(f"/gerar-voz/conversa/{conversa_id}")
        assert r.status_code == 404

    def test_salvar_pausa(self, client, app_module):
        conversa_id = _cria_conversa(client)
        client.post(f"/gerar-voz/conversa/{conversa_id}/pausa", data={"pausa_segundos": "2.0"})
        import conversa as cv
        conversa = cv.carregar_conversa(app_module.BASE_DIR, conversa_id)
        assert conversa["pausaSegundos"] == 2.0


class TestFalas:
    def test_adicionar_fala(self, client):
        conversa_id = _cria_conversa(client)
        r = client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={
            "texto": "Olá!", "motor": "piper", "voz": "pt_BR-faber-medium",
        })
        assert r.status_code == 302
        r2 = client.get(f"/gerar-voz/conversa/{conversa_id}")
        assert b"Ol\xc3\xa1!" in r2.data

    def test_adicionar_fala_texto_vazio_mostra_erro(self, client):
        conversa_id = _cria_conversa(client)
        r = client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={"texto": "", "motor": "piper"})
        assert r.status_code == 200  # re-renderiza com erro, não redireciona
        assert "texto".encode() in r.data.lower()

    def test_duas_falas_motores_diferentes(self, client, app_module):
        conversa_id = _cria_conversa(client)
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={"texto": "Fala A", "motor": "piper"})
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={"texto": "Fala B", "motor": "kokoro"})
        import conversa as cv
        conversa = cv.carregar_conversa(app_module.BASE_DIR, conversa_id)
        assert [f["motor"] for f in conversa["falas"]] == ["piper", "kokoro"]

    def test_editar_fala(self, client, app_module):
        conversa_id = _cria_conversa(client)
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={"texto": "Original", "motor": "piper"})
        fala_id = _id_primeira_fala(app_module, conversa_id)
        r = client.post(f"/gerar-voz/conversa/{conversa_id}/fala/{fala_id}/editar", data={"texto": "Editado"})
        assert r.status_code == 302
        r2 = client.get(f"/gerar-voz/conversa/{conversa_id}")
        assert b"Editado" in r2.data

    def test_excluir_fala(self, client, app_module):
        conversa_id = _cria_conversa(client)
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={"texto": "Vai sumir", "motor": "piper"})
        fala_id = _id_primeira_fala(app_module, conversa_id)
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala/{fala_id}/excluir")
        r = client.get(f"/gerar-voz/conversa/{conversa_id}")
        assert b"Vai sumir" not in r.data

    def test_mover_fala(self, client, app_module):
        import conversa as cv
        conversa_id = _cria_conversa(client)
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={"texto": "Primeira", "motor": "piper"})
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={"texto": "Segunda", "motor": "piper"})
        conversa = cv.carregar_conversa(app_module.BASE_DIR, conversa_id)
        segunda_id = conversa["falas"][1]["id"]

        client.post(f"/gerar-voz/conversa/{conversa_id}/fala/{segunda_id}/mover", data={"direcao": "cima"})
        conversa2 = cv.carregar_conversa(app_module.BASE_DIR, conversa_id)
        assert conversa2["falas"][0]["id"] == segunda_id


class TestGeracao:
    def test_gerar_fala_individual(self, client, app_module, motor_falso):
        conversa_id = _cria_conversa(client)
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={"texto": "Oi", "motor": "kokoro", "voz": "pf_dora"})
        fala_id = _id_primeira_fala(app_module, conversa_id)

        r = client.post(f"/gerar-voz/conversa/{conversa_id}/fala/{fala_id}/gerar")
        assert r.status_code == 200
        st = _espera_fala(client, conversa_id, fala_id)
        assert st["erro"] is None
        assert motor_falso[0]["engine"] == "kokoro"

    def test_baixar_audio_de_fala_gerada(self, client, app_module, motor_falso):
        conversa_id = _cria_conversa(client)
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={"texto": "Oi", "motor": "piper"})
        fala_id = _id_primeira_fala(app_module, conversa_id)
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala/{fala_id}/gerar")
        _espera_fala(client, conversa_id, fala_id)

        r = client.get(f"/gerar-voz/conversa/{conversa_id}/fala/{fala_id}/audio")
        assert r.status_code == 200
        assert len(r.data) > 500

    def test_audio_de_fala_nao_gerada_404(self, client, app_module):
        conversa_id = _cria_conversa(client)
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={"texto": "Oi", "motor": "piper"})
        fala_id = _id_primeira_fala(app_module, conversa_id)
        r = client.get(f"/gerar-voz/conversa/{conversa_id}/fala/{fala_id}/audio")
        assert r.status_code == 404

    def test_status_de_fala_nunca_gerada(self, client, app_module):
        conversa_id = _cria_conversa(client)
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={"texto": "Oi", "motor": "piper"})
        fala_id = _id_primeira_fala(app_module, conversa_id)
        r = client.get(f"/gerar-voz/conversa/{conversa_id}/fala/{fala_id}/status")
        assert r.status_code == 200
        assert r.get_json()["pronto"] is True  # nunca rodou -- considera "pronto" (nada pendente)

    def test_gerar_tudo_combina_falas_geradas(self, client, app_module, motor_falso):
        conversa_id = _cria_conversa(client)
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={"texto": "Um", "motor": "piper"})
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={"texto": "Dois", "motor": "kokoro"})

        import conversa as cv
        conversa = cv.carregar_conversa(app_module.BASE_DIR, conversa_id)
        for f in conversa["falas"]:
            client.post(f"/gerar-voz/conversa/{conversa_id}/fala/{f['id']}/gerar")
            _espera_fala(client, conversa_id, f["id"])

        r = client.post(f"/gerar-voz/conversa/{conversa_id}/gerar-tudo")
        assert r.status_code == 200
        data = r.get_json()
        assert data["quantidadeFalas"] == 2

    def test_gerar_tudo_sem_fala_nenhuma_400(self, client):
        conversa_id = _cria_conversa(client)
        r = client.post(f"/gerar-voz/conversa/{conversa_id}/gerar-tudo")
        assert r.status_code == 400

    def test_baixar_combinado(self, client, app_module, motor_falso):
        conversa_id = _cria_conversa(client)
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala", data={"texto": "Oi", "motor": "piper"})
        fala_id = _id_primeira_fala(app_module, conversa_id)
        client.post(f"/gerar-voz/conversa/{conversa_id}/fala/{fala_id}/gerar")
        _espera_fala(client, conversa_id, fala_id)
        client.post(f"/gerar-voz/conversa/{conversa_id}/gerar-tudo")

        r = client.get(f"/gerar-voz/conversa/{conversa_id}/completo")
        assert r.status_code == 200
        assert len(r.data) > 500

    def test_baixar_combinado_antes_de_gerar_404(self, client):
        conversa_id = _cria_conversa(client)
        r = client.get(f"/gerar-voz/conversa/{conversa_id}/completo")
        assert r.status_code == 404

    def test_pagina_gerador_de_voz_linka_pra_conversa(self, client):
        r = client.get("/gerar-voz")
        assert r.status_code == 200
        assert "Simular Conversa".encode() in r.data
