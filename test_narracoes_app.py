"""
Teste de integração Flask das duas abas novas:

- Gerador de voz (`/gerar-voz`): formulário -> gera um áudio com o
  motor escolhido -> player + link de download.
- Roteiro para Áudio (`/narracoes`): projetos avulsos de narração --
  criar, colar/editar/remover falas, configurar motor/voz, disparar a
  geração em background e acompanhar o status, baixar/remover os
  áudios gerados.

Os três motores de voz (Piper/XTTS v2/Kokoro) são mockados via
`tts.voice_generator.gerar_audio` — o comportamento de cada motor em
si já tem sua própria suíte em `toolkit/tts/test_voice_generator.py`;
aqui o que importa é que as ROTAS chamam a coisa certa e devolvem a
resposta certa pra cada caminho (sucesso, erro, 404, 409).
"""
import io
import shutil
import subprocess
import time

import pytest


@pytest.fixture
def app_module():
    """Importa o app.py uma vez. Não reseta `_NARRACAO_STATUS`/limpa a
    pasta `narracoes/` entre testes -- cada projeto usa um id baseado em
    timestamp+uuid, então não colide entre testes; a limpeza de disco
    fica por conta de cada teste que criou algo (ver `_apaga_projeto`).
    """
    import app as _app_module
    _app_module.app.config["TESTING"] = True
    yield _app_module


@pytest.fixture
def client(app_module):
    return app_module.app.test_client()


@pytest.fixture
def motor_falso(app_module):
    """Substitui `tts.voice_generator.gerar_audio` por uma versão que
    gera um tom puro via ffmpeg (rápido, sem rede, sem precisar de
    nenhuma das libs pesadas de TTS instaladas) — e devolve a lista de
    chamadas feitas, pra inspecionar quais parâmetros a rota passou.

    Precisa mockar em DOIS lugares: `narracoes.py` importa `gerar_audio`
    localmente (dentro da função, a cada chamada), então mockar só o
    módulo `tts.voice_generator` já basta pra ele. Mas `app.py` importa
    `gerar_audio` uma vez no topo do arquivo, como `tts_gerar_audio`
    ("from ... import gerar_audio as tts_gerar_audio") — essa referência
    já ficou "presa" ao objeto função ORIGINAL no momento do import, e
    trocar o atributo em `tts.voice_generator` depois não muda o que
    `app.tts_gerar_audio` aponta. A rota /gerar-voz (que chama
    `tts_gerar_audio` direto) só vê o mock se a gente trocar essa
    referência em `app_module` também.
    """
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

    original_vg = vg_mod.gerar_audio
    original_app = app_module.tts_gerar_audio
    vg_mod.gerar_audio = fake_gerar_audio
    app_module.tts_gerar_audio = fake_gerar_audio
    yield chamadas
    vg_mod.gerar_audio = original_vg
    app_module.tts_gerar_audio = original_app


def _espera_geracao_terminar(client, projeto_id, timeout=15):
    status_url = f"/narracoes/{projeto_id}/gerar/status"
    deadline = time.time() + timeout
    data = None
    while time.time() < deadline:
        data = client.get(status_url).get_json()
        if not data["running"]:
            return data
        time.sleep(0.1)
    raise TimeoutError(f"geração do projeto {projeto_id} não terminou em {timeout}s")


# --------------------------------------------------------------------------- #
# Gerador de voz (/gerar-voz)
# --------------------------------------------------------------------------- #

def _espera_gerar_voz_terminar(client, job_id, timeout=15):
    deadline = time.time() + timeout
    data = None
    while time.time() < deadline:
        data = client.get(f"/gerar-voz/status/{job_id}").get_json()
        if not data["running"]:
            return data
        time.sleep(0.1)
    raise TimeoutError(f"geração {job_id} não terminou em {timeout}s")


class TestGerarVoz:
    def test_pagina_carrega_com_os_cinco_motores(self, client):
        r = client.get("/gerar-voz")
        assert r.status_code == 200
        for label in (b"Piper TTS", b"XTTS", b"Chatterbox TTS", b"Chatterbox Turbo", b"Kokoro"):
            assert label in r.data

    def test_gerar_com_motor_nao_instalado_mostra_erro_amigavel(self, client):
        r = client.post("/gerar-voz/gerar", data={"texto": "Olá", "engine": "piper"})
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        status = _espera_gerar_voz_terminar(client, job_id)
        assert status["erro"] and ("piper-tts" in status["erro"] or "não está instalado" in status["erro"])

    def test_gerar_texto_vazio(self, client):
        r = client.post("/gerar-voz/gerar", data={"texto": "", "engine": "piper"})
        assert r.status_code == 400
        assert "Escreva algum texto" in r.get_json()["erro"]

    def test_gerar_motor_desconhecido(self, client):
        r = client.post("/gerar-voz/gerar", data={"texto": "oi", "engine": "nao-existe"})
        assert r.status_code == 400

    def test_gerar_limpa_pontuacao_antes_de_mandar_pro_motor(self, client, motor_falso):
        """Bug real relatado: o Gerador de Voz avulso mandava o texto
        cru pro motor (diferente do Roteiro para Áudio, que já limpava)
        -- o motor às vezes "lia" a pontuação em voz alta (falava
        "aspas", "reticências"). Confirma que agora limpa também."""
        r = client.post("/gerar-voz/gerar", data={
            "texto": 'Ele disse: "isso é incrível..." (de verdade).', "engine": "kokoro",
        })
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        _espera_gerar_voz_terminar(client, job_id)
        texto_mandado_pro_motor = motor_falso[0]["texto"]
        assert '"' not in texto_mandado_pro_motor
        assert "(" not in texto_mandado_pro_motor and ")" not in texto_mandado_pro_motor
        assert "..." not in texto_mandado_pro_motor

    def test_gerar_com_motor_falso_devolve_player_de_audio(self, client, motor_falso):
        r = client.post("/gerar-voz/gerar", data={
            "texto": "Texto de teste", "engine": "kokoro", "kokoro_voz": "pf_dora", "velocidade": "1.0",
        })
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        status = _espera_gerar_voz_terminar(client, job_id)
        assert status["erro"] is None
        assert status["resultado"]["audio_url"]
        assert len(motor_falso) == 1
        assert motor_falso[0]["engine"] == "kokoro"
        assert motor_falso[0]["kwargs"]["voz"] == "pf_dora"
        # variante/precisão padrão, mesmo sem escolher nada explicitamente
        assert motor_falso[0]["kwargs"]["variante"] == "v1.0"
        assert motor_falso[0]["kwargs"]["precisao"] == "fp32"

    def test_gerar_kokoro_com_variante_e_precisao_escolhidas(self, client, motor_falso):
        r = client.post("/gerar-voz/gerar", data={
            "texto": "Ni hao", "engine": "kokoro", "kokoro_voz": "zf_xiaobei",
            "kokoro_variante": "v1.1-zh", "kokoro_precisao": "int8",
        })
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        _espera_gerar_voz_terminar(client, job_id)
        assert motor_falso[0]["kwargs"]["variante"] == "v1.1-zh"
        assert motor_falso[0]["kwargs"]["precisao"] == "int8"

    def test_status_de_job_inexistente_nao_quebra(self, client):
        r = client.get("/gerar-voz/status/nao-existe-mesmo")
        assert r.status_code == 200
        data = r.get_json()
        assert data["pronto"] is True and data["erro"]

    def test_baixar_audio_gerado(self, client, motor_falso):
        r = client.post("/gerar-voz/gerar", data={"texto": "Oi de novo", "engine": "piper", "piper_voz": "pt_BR-faber-medium"})
        job_id = r.get_json()["job_id"]
        status = _espera_gerar_voz_terminar(client, job_id)
        audio_url = status["resultado"]["audio_url"]
        r3 = client.get(audio_url)
        assert r3.status_code == 200
        assert len(r3.data) > 100

    def test_baixar_audio_inexistente_404(self, client):
        r = client.get("/gerar-voz/audio/nao-existe.wav")
        assert r.status_code == 404

    def test_upload_referencia_xtts_sem_salvar_perfil(self, client, app_module):
        import io
        r = client.post("/gerar-voz/gerar", data={
            "texto": "Clonagem", "engine": "xtts", "xtts_idioma": "pt",
            "xtts_speaker_wav": (io.BytesIO(b"audio falso"), "ref.wav"),
        }, content_type="multipart/form-data")
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        _espera_gerar_voz_terminar(client, job_id)
        # sem XTTS instalado, o job termina com erro -- mas o arquivo de
        # referência já tinha sido salvo ANTES dessa checagem
        import os
        assert any(f.startswith("ref_") for f in os.listdir(app_module.VOZES_DIR))

    def test_gerar_xtts_checkpoint_padrao_nao_manda_o_kwarg(self, client, motor_falso):
        r = client.post("/gerar-voz/gerar", data={
            "texto": "Oi", "engine": "xtts", "xtts_idioma": "pt", "xtts_checkpoint": "padrao",
        })
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        _espera_gerar_voz_terminar(client, job_id)
        assert "checkpoint_conhecido" not in motor_falso[0]["kwargs"]

    def test_gerar_xtts_com_checkpoint_conhecido(self, client, motor_falso):
        r = client.post("/gerar-voz/gerar", data={
            "texto": "Namaste", "engine": "xtts", "xtts_idioma": "hi", "xtts_checkpoint": "hindi",
        })
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        _espera_gerar_voz_terminar(client, job_id)
        assert motor_falso[0]["kwargs"]["checkpoint_conhecido"] == "hindi"

    def test_salvar_perfil_de_voz_pela_pagina_nao_quebra(self, client, app_module):
        """O ffmpez pode aceitar ou rejeitar esse ffmpeg conteúdo falso de
        áudio dependendo do ambiente -- o que importa aqui é que a rota
        nunca quebra com 500 em nenhum dos dois casos."""
        import io
        r = client.post("/gerar-voz/gerar", data={
            "texto": "Teste de perfil", "engine": "xtts", "xtts_idioma": "pt",
            "xtts_speaker_wav": (io.BytesIO(b"RIFF0000WAVEfmt "), "ref.wav"),
            "xtts_salvar_perfil": "on", "xtts_nome_novo_perfil": "perfil_de_teste_app",
        }, content_type="multipart/form-data")
        assert r.status_code in (200, 400)
        if r.status_code == 200:
            job_id = r.get_json()["job_id"]
            _espera_gerar_voz_terminar(client, job_id)
        app_module.tts_excluir_perfil_de_voz("perfil_de_teste_app")

    def test_salvar_perfil_sem_nome_da_erro_400(self, client):
        import io
        r = client.post("/gerar-voz/gerar", data={
            "texto": "Teste", "engine": "xtts", "xtts_idioma": "pt",
            "xtts_speaker_wav": (io.BytesIO(b"audio falso"), "ref.wav"),
            "xtts_salvar_perfil": "on", "xtts_nome_novo_perfil": "",
        }, content_type="multipart/form-data")
        assert r.status_code == 400
        assert "nome" in r.get_json()["erro"].lower()

    def test_gerar_chatterbox_com_parametros_default(self, client, motor_falso):
        r = client.post("/gerar-voz/gerar", data={"texto": "Olá", "engine": "chatterbox"})
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        _espera_gerar_voz_terminar(client, job_id)
        assert motor_falso[0]["engine"] == "chatterbox"
        assert motor_falso[0]["kwargs"]["idioma"] == "pt"
        assert motor_falso[0]["kwargs"]["exaggeration"] == 0.5
        assert motor_falso[0]["kwargs"]["cfg_weight"] == 0.5

    def test_gerar_chatterbox_com_idioma_e_intensidade_customizados(self, client, motor_falso):
        r = client.post("/gerar-voz/gerar", data={
            "texto": "Bonjour", "engine": "chatterbox", "chatterbox_idioma": "fr",
            "chatterbox_exaggeration": "0.8", "chatterbox_cfg_weight": "0.3",
        })
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        _espera_gerar_voz_terminar(client, job_id)
        assert motor_falso[0]["kwargs"]["idioma"] == "fr"
        assert motor_falso[0]["kwargs"]["exaggeration"] == 0.8
        assert motor_falso[0]["kwargs"]["cfg_weight"] == 0.3

    def test_upload_referencia_chatterbox_sem_salvar_perfil(self, client, app_module):
        import io
        r = client.post("/gerar-voz/gerar", data={
            "texto": "Clonagem", "engine": "chatterbox", "chatterbox_idioma": "pt",
            "chatterbox_speaker_wav": (io.BytesIO(b"audio falso"), "ref.wav"),
        }, content_type="multipart/form-data")
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        _espera_gerar_voz_terminar(client, job_id)
        # sem Chatterbox instalado, o job termina com erro -- mas o
        # arquivo de referência já tinha sido salvo ANTES dessa checagem
        import os
        assert any(f.startswith("ref_") for f in os.listdir(app_module.VOZES_DIR))

    def test_chatterbox_reaproveita_perfil_de_voz_ja_salvo(self, client, motor_falso, app_module):
        """O mesmo perfil salvo (pelo XTTS ou por qualquer motor) tem
        que funcionar pro Chatterbox também -- os dois só precisam de
        um áudio de referência."""
        import os
        import subprocess
        import tempfile

        ref = os.path.join(tempfile.mkdtemp(), "ref.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=2", "-ar", "22050", "-ac", "1", ref],
            capture_output=True, check=True,
        )
        app_module.tts_salvar_perfil_de_voz("perfil_compartilhado_teste", ref)
        try:
            r = client.post("/gerar-voz/gerar", data={
                "texto": "usando o perfil", "engine": "chatterbox", "chatterbox_idioma": "pt",
                "chatterbox_perfil": "perfil_compartilhado_teste",
            })
            assert r.status_code == 200
            job_id = r.get_json()["job_id"]
            _espera_gerar_voz_terminar(client, job_id)
            assert motor_falso[0]["kwargs"]["voice_profile"] == "perfil_compartilhado_teste"
        finally:
            app_module.tts_excluir_perfil_de_voz("perfil_compartilhado_teste")

    def test_excluir_perfil_de_voz(self, client):
        r = client.post("/gerar-voz/perfis/nao-existe/excluir")
        assert r.status_code == 302  # não quebra mesmo se o perfil não existir

    def test_busca_de_vozes_piper(self, client, monkeypatch):
        import app as app_module

        def fake_search(busca="", idioma="", qualidade="", max_resultados=50):
            return [{
                "key": "pt_BR-faber-medium", "nome": "faber", "idioma_codigo": "pt_BR",
                "idioma_nome": "Portuguese", "pais": "Brazil", "qualidade": "medium",
                "num_falantes": 1, "tamanho_mb": 60.3,
            }]

        monkeypatch.setattr(app_module, "tts_piper_search_voices", fake_search)
        r = client.get("/gerar-voz/piper-vozes?q=faber")
        assert r.status_code == 200
        data = r.get_json()
        assert data["erro"] is None
        assert data["resultados"][0]["key"] == "pt_BR-faber-medium"

    def test_busca_de_vozes_piper_erro_de_rede(self, client, monkeypatch):
        import app as app_module
        from tts.voice_generator import VoiceGeneratorError

        def fake_search_com_erro(**kwargs):
            raise VoiceGeneratorError("sem internet (simulado)")

        monkeypatch.setattr(app_module, "tts_piper_search_voices", fake_search_com_erro)
        r = client.get("/gerar-voz/piper-vozes?q=qualquer")
        assert r.status_code == 502
        assert "sem internet" in r.get_json()["erro"]

    def test_baixar_voz_piper_agora(self, client, monkeypatch):
        import app as app_module

        def fake_download(nome_voz, models_dir=None):
            return {"nome_voz": nome_voz, "onnx_path": "/fake/path.onnx", "config_path": "/fake/path.onnx.json", "tamanho_mb": 60.3}

        monkeypatch.setattr(app_module, "tts_piper_download_voice_now", fake_download)
        r = client.post("/gerar-voz/piper-vozes/baixar", data={"nome_voz": "pt_BR-faber-medium"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["erro"] is None
        assert data["resultado"]["tamanho_mb"] == 60.3

    def test_baixar_voz_piper_sem_nome_400(self, client):
        r = client.post("/gerar-voz/piper-vozes/baixar", data={})
        assert r.status_code == 400

    def test_baixar_voz_piper_nome_invalido_502(self, client, monkeypatch):
        import app as app_module
        from tts.voice_generator import VoiceGeneratorError

        def fake_download_com_erro(nome_voz, models_dir=None):
            raise VoiceGeneratorError(f"voz {nome_voz!r} não encontrada")

        monkeypatch.setattr(app_module, "tts_piper_download_voice_now", fake_download_com_erro)
        r = client.post("/gerar-voz/piper-vozes/baixar", data={"nome_voz": "nao-existe-123"})
        assert r.status_code == 502

    def test_gerar_chatterbox_turbo_sem_parametros_de_idioma(self, client, motor_falso):
        """O Turbo não aceita idioma/exaggeration/cfg_weight -- confirma
        que a rota não manda nenhum desses três pro motor."""
        r = client.post("/gerar-voz/gerar", data={"texto": "Hi there [chuckle]!", "engine": "chatterbox_turbo"})
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        _espera_gerar_voz_terminar(client, job_id)
        assert motor_falso[0]["engine"] == "chatterbox_turbo"
        assert "idioma" not in motor_falso[0]["kwargs"]
        assert "exaggeration" not in motor_falso[0]["kwargs"]
        assert "cfg_weight" not in motor_falso[0]["kwargs"]

    def test_gerar_chatterbox_turbo_preserva_tags_no_texto(self, client, motor_falso):
        r = client.post("/gerar-voz/gerar", data={
            "texto": "Hi there [chuckle], welcome back!", "engine": "chatterbox_turbo",
        })
        job_id = r.get_json()["job_id"]
        _espera_gerar_voz_terminar(client, job_id)
        assert "[chuckle]" in motor_falso[0]["texto"]

    def test_upload_referencia_chatterbox_turbo_sem_salvar_perfil(self, client, app_module):
        import io
        r = client.post("/gerar-voz/gerar", data={
            "texto": "Hello", "engine": "chatterbox_turbo",
            "chatterbox_turbo_speaker_wav": (io.BytesIO(b"audio falso"), "ref.wav"),
        }, content_type="multipart/form-data")
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        _espera_gerar_voz_terminar(client, job_id)
        import os
        assert any(f.startswith("ref_") for f in os.listdir(app_module.VOZES_DIR))

    def test_chatterbox_turbo_reaproveita_perfil_de_voz_ja_salvo(self, client, motor_falso, app_module):
        import os
        import subprocess
        import tempfile

        ref = os.path.join(tempfile.mkdtemp(), "ref.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=2", "-ar", "22050", "-ac", "1", ref],
            capture_output=True, check=True,
        )
        app_module.tts_salvar_perfil_de_voz("perfil_compartilhado_turbo", ref)
        try:
            r = client.post("/gerar-voz/gerar", data={
                "texto": "usando o perfil", "engine": "chatterbox_turbo",
                "chatterbox_turbo_perfil": "perfil_compartilhado_turbo",
            })
            assert r.status_code == 200
            job_id = r.get_json()["job_id"]
            _espera_gerar_voz_terminar(client, job_id)
            assert motor_falso[0]["kwargs"]["voice_profile"] == "perfil_compartilhado_turbo"
        finally:
            app_module.tts_excluir_perfil_de_voz("perfil_compartilhado_turbo")


@pytest.fixture
def whisper_falso(app_module):
    """Substitui `app.transcribe_audio` (a referência que `_gerar_voz_em_background`
    de fato chama -- é importada direto no topo de app.py, então mockar
    `whisper_transcribe.transcribe_audio` não bastaria, igual o `motor_falso`
    acima já explica pro tts_gerar_audio) por uma versão que devolve
    palavras com timestamp fixas, sem precisar do Whisper de verdade
    instalado. Devolve a lista de chamadas feitas."""
    chamadas = []

    def fake_transcribe_audio(audio_path, model_size="base", language=None, word_timestamps=False, device="auto"):
        chamadas.append({"audio_path": audio_path, "word_timestamps": word_timestamps})
        return [{
            "start": 0.0, "end": 1.5, "text": "Olá mundo bonito",
            "words": [
                {"word": "Olá", "start": 0.0, "end": 0.4},
                {"word": "mundo", "start": 0.5, "end": 0.9},
                {"word": "bonito", "start": 1.0, "end": 1.5},
            ],
        }]

    original = app_module.transcribe_audio
    app_module.transcribe_audio = fake_transcribe_audio
    yield chamadas
    app_module.transcribe_audio = original


class TestGerarVozComLegenda:
    def test_gera_legenda_junto_com_o_audio_por_padrao(self, client, motor_falso, whisper_falso):
        r = client.post("/gerar-voz/gerar", data={"texto": "Olá mundo bonito", "engine": "piper"})
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        status = _espera_gerar_voz_terminar(client, job_id)
        assert status["erro"] is None
        assert status["resultado"]["srt_url"]
        assert status["resultado"]["zip_url"]
        assert whisper_falso[0]["word_timestamps"] is True  # tem que pedir timestamp por palavra

    def test_baixar_a_legenda_devolve_srt_valido(self, client, motor_falso, whisper_falso):
        r = client.post("/gerar-voz/gerar", data={"texto": "Olá mundo bonito", "engine": "piper"})
        job_id = r.get_json()["job_id"]
        status = _espera_gerar_voz_terminar(client, job_id)
        srt_url = status["resultado"]["srt_url"]
        resp = client.get(srt_url)
        assert resp.status_code == 200
        texto = resp.data.decode("utf-8")
        assert "-->" in texto
        assert "Olá" in texto

    def test_baixar_o_zip_contem_audio_e_legenda(self, client, motor_falso, whisper_falso):
        import io
        import zipfile
        r = client.post("/gerar-voz/gerar", data={"texto": "Olá mundo bonito", "engine": "piper"})
        job_id = r.get_json()["job_id"]
        status = _espera_gerar_voz_terminar(client, job_id)
        resp = client.get(status["resultado"]["zip_url"])
        assert resp.status_code == 200
        with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
            nomes = zf.namelist()
            assert "narracao.wav" in nomes
            assert "legenda.srt" in nomes

    def test_modo_por_palavra_respeita_o_tamanho_do_grupo(self, client, motor_falso, whisper_falso):
        r = client.post("/gerar-voz/gerar", data={
            "texto": "Olá mundo bonito", "engine": "piper",
            "legenda_modo": "palavra", "legenda_palavras_por_linha": "1",
        })
        job_id = r.get_json()["job_id"]
        status = _espera_gerar_voz_terminar(client, job_id)
        srt = client.get(status["resultado"]["srt_url"]).data.decode("utf-8")
        # 3 palavras, 1 por linha -> 3 blocos numerados
        assert srt.count("-->") == 3

    def test_modo_desconhecido_cai_no_padrao_em_vez_de_dar_erro(self, client, motor_falso, whisper_falso):
        r = client.post("/gerar-voz/gerar", data={
            "texto": "Olá mundo bonito", "engine": "piper", "legenda_modo": "isso-nao-existe",
        })
        job_id = r.get_json()["job_id"]
        status = _espera_gerar_voz_terminar(client, job_id)
        assert status["erro"] is None
        assert status["resultado"]["srt_url"]

    def test_falha_na_transcricao_nao_derruba_o_audio_ja_gerado(self, client, motor_falso, app_module):
        def transcricao_com_erro(*a, **k):
            raise app_module.TranscriptionError("falha simulada")
        original = app_module.transcribe_audio
        app_module.transcribe_audio = transcricao_com_erro
        try:
            r = client.post("/gerar-voz/gerar", data={"texto": "Olá mundo bonito", "engine": "piper"})
            job_id = r.get_json()["job_id"]
            status = _espera_gerar_voz_terminar(client, job_id)
            assert status["erro"] is None  # o áudio continua sendo sucesso
            assert status["resultado"]["audio_url"]
            # v84_94: sem o Whisper a legenda sai com o texto do roteiro e tempos estimados
            assert status["resultado"].get("srt_url")
            assert "falha simulada" in status["log"] and "ESTIMADOS" in status["log"]
        finally:
            app_module.transcribe_audio = original



    def _cria_projeto(self, client, nome="Projeto de teste"):
        r = client.post("/narracoes", data={"nome": nome})
        assert r.status_code == 302
        return r.headers["Location"].rsplit("/", 1)[-1]

    def _apaga_projeto(self, client, projeto_id):
        client.post(f"/narracoes/{projeto_id}/excluir")

    def test_lista_vazia(self, client):
        r = client.get("/narracoes")
        assert r.status_code == 200

    def test_criar_projeto_redireciona_pro_detalhe(self, client):
        pid = self._cria_projeto(client, "Meu projeto")
        try:
            r = client.get(f"/narracoes/{pid}")
            assert r.status_code == 200
            assert "Meu projeto".encode() in r.data
        finally:
            self._apaga_projeto(client, pid)

    def test_detalhe_projeto_inexistente_404(self, client):
        r = client.get("/narracoes/nao-existe-mesmo")
        assert r.status_code == 404

    def test_importar_roteiro_e_listar_falas(self, client):
        pid = self._cria_projeto(client)
        try:
            r = client.post(f"/narracoes/{pid}/roteiro", data={"texto": "Um.\nDois.\nTrês.", "modo_separacao": "linha"})
            assert r.status_code == 302
            r = client.get(f"/narracoes/{pid}")
            assert b"Um." in r.data and b"Dois." in r.data and b"Tr\xc3\xaas." in r.data
        finally:
            self._apaga_projeto(client, pid)

    def test_importar_roteiro_texto_vazio_mostra_erro_sem_redirecionar(self, client):
        pid = self._cria_projeto(client)
        try:
            r = client.post(f"/narracoes/{pid}/roteiro", data={"texto": "   ", "modo_separacao": "linha"})
            assert r.status_code == 200  # não redireciona -- mostra o erro na própria página
            assert "Cole o texto".encode() in r.data
        finally:
            self._apaga_projeto(client, pid)

    def test_adicionar_editar_remover_fala(self, client):
        pid = self._cria_projeto(client)
        try:
            client.post(f"/narracoes/{pid}/roteiro", data={"texto": "A.\nB."})
            client.post(f"/narracoes/{pid}/fala/adicionar", data={"texto": "C adicionada"})
            r = client.get(f"/narracoes/{pid}")
            assert b"C adicionada" in r.data

            client.post(f"/narracoes/{pid}/fala/0/editar", data={"texto": "A editada"})
            r = client.get(f"/narracoes/{pid}")
            assert b"A editada" in r.data

            client.post(f"/narracoes/{pid}/fala/1/remover")
            r = client.get(f"/narracoes/{pid}")
            assert b"B." not in r.data
        finally:
            self._apaga_projeto(client, pid)

    def test_salvar_config(self, client):
        pid = self._cria_projeto(client)
        try:
            r = client.post(f"/narracoes/{pid}/config", data={
                "motor": "xtts", "voz": "Ana Florence", "idioma": "pt",
                "velocidade": "1.1", "pausa_segundos": "0.8", "usar_gpu": "on",
            })
            assert r.status_code == 302
            r = client.get(f"/narracoes/{pid}")
            assert r.status_code == 200
        finally:
            self._apaga_projeto(client, pid)

    def test_pagina_de_detalhe_mostra_campos_de_voz_novos(self, client):
        pid = self._cria_projeto(client)
        try:
            r = client.get(f"/narracoes/{pid}")
            assert b"xtts_checkpoint" in r.data
            assert b"kokoro_variante" in r.data
            assert b"kokoro_precisao" in r.data
            # sem perfil nenhum salvo, o SELETOR de perfil (XTTS e
            # Chatterbox) não aparece -- o campo oculto "voz_perfil"
            # em si sempre existe (guarda o valor escolhido, mesmo
            # vazio), então o teste checa os seletores visíveis.
            assert b"xtts_perfil_visivel" not in r.data
            assert b"chatterbox_perfil_visivel" not in r.data
        finally:
            self._apaga_projeto(client, pid)

    def test_salvar_config_checkpoint_xtts(self, client, app_module):
        pid = self._cria_projeto(client)
        try:
            r = client.post(f"/narracoes/{pid}/config", data={
                "motor": "xtts", "xtts_checkpoint": "hindi", "idioma": "hi",
            })
            assert r.status_code == 302
            import narracoes as na
            projeto = na.carregar_projeto(app_module.BASE_DIR, pid)
            assert projeto["xttsCheckpoint"] == "hindi"
        finally:
            self._apaga_projeto(client, pid)

    def test_salvar_config_variante_precisao_kokoro(self, client, app_module):
        pid = self._cria_projeto(client)
        try:
            r = client.post(f"/narracoes/{pid}/config", data={
                "motor": "kokoro", "kokoro_variante": "v1.1-zh", "kokoro_precisao": "int8",
            })
            assert r.status_code == 302
            import narracoes as na
            projeto = na.carregar_projeto(app_module.BASE_DIR, pid)
            assert projeto["kokoroVariante"] == "v1.1-zh"
            assert projeto["kokoroPrecisao"] == "int8"
        finally:
            self._apaga_projeto(client, pid)

    def test_salvar_config_cortar_silencio_gravacoes(self, client, app_module):
        pid = self._cria_projeto(client)
        try:
            import narracoes as na
            # padrão: vem ligado (checa via GET, não via config POST vazio)
            projeto_inicial = na.carregar_projeto(app_module.BASE_DIR, pid)
            assert projeto_inicial["cortarSilencioGravacoes"] is True

            r = client.post(f"/narracoes/{pid}/config", data={})  # checkbox NÃO marcada
            assert r.status_code == 302
            projeto = na.carregar_projeto(app_module.BASE_DIR, pid)
            assert projeto["cortarSilencioGravacoes"] is False

            r2 = client.post(f"/narracoes/{pid}/config", data={"cortar_silencio_gravacoes": "on"})
            assert r2.status_code == 302
            projeto2 = na.carregar_projeto(app_module.BASE_DIR, pid)
            assert projeto2["cortarSilencioGravacoes"] is True
        finally:
            self._apaga_projeto(client, pid)

    def test_pagina_mostra_checkbox_cortar_silencio_marcada_por_padrao(self, client):
        pid = self._cria_projeto(client)
        try:
            r = client.get(f"/narracoes/{pid}")
            assert b"cortar_silencio_gravacoes" in r.data
        finally:
            self._apaga_projeto(client, pid)

    def test_pagina_de_detalhe_mostra_perfil_quando_existe(self, client, app_module, tmp_path):
        import subprocess
        ref = tmp_path / "ref.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", str(ref)],
            capture_output=True, check=True,
        )
        app_module.tts_salvar_perfil_de_voz("perfil_narracoes_teste", str(ref))
        pid = self._cria_projeto(client)
        try:
            r = client.get(f"/narracoes/{pid}")
            assert b"voz_perfil" in r.data
            assert b"perfil_narracoes_teste" in r.data
        finally:
            self._apaga_projeto(client, pid)
            app_module.tts_excluir_perfil_de_voz("perfil_narracoes_teste")

    def test_gerar_com_perfil_de_voz_usa_o_kwarg_certo(self, client, app_module, tmp_path, motor_falso):
        import subprocess
        ref = tmp_path / "ref2.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", str(ref)],
            capture_output=True, check=True,
        )
        app_module.tts_salvar_perfil_de_voz("perfil_geracao_teste", str(ref))
        pid = self._cria_projeto(client)
        try:
            client.post(f"/narracoes/{pid}/roteiro", data={"texto": "Fala de teste."})
            client.post(f"/narracoes/{pid}/config", data={"motor": "xtts", "voz_perfil": "perfil_geracao_teste"})
            client.post(f"/narracoes/{pid}/gerar")
            _espera_geracao_terminar(client, pid)
            assert motor_falso[0]["kwargs"]["voice_profile"] == "perfil_geracao_teste"
        finally:
            self._apaga_projeto(client, pid)
            app_module.tts_excluir_perfil_de_voz("perfil_geracao_teste")

    def test_excluir_projeto(self, client):
        pid = self._cria_projeto(client)
        r = client.post(f"/narracoes/{pid}/excluir")
        assert r.status_code == 302
        r = client.get(f"/narracoes/{pid}")
        assert r.status_code == 404


class TestNarracoesGeracao:
    def _cria_projeto_pronto(self, client, motor="piper", pausa="0.2"):
        r = client.post("/narracoes", data={"nome": "Projeto pronto"})
        pid = r.headers["Location"].rsplit("/", 1)[-1]
        client.post(f"/narracoes/{pid}/roteiro", data={"texto": "Primeira fala.\nSegunda fala."})
        client.post(f"/narracoes/{pid}/config", data={"motor": motor, "pausa_segundos": pausa, "usar_gpu": "on"})
        return pid

    def test_gerar_status_inicial_sem_nada_rodando(self, client):
        pid = self._cria_projeto_pronto(client)
        try:
            r = client.get(f"/narracoes/{pid}/gerar/status")
            data = r.get_json()
            assert data == {"running": False, "log": "", "erro": None, "pronto": False}
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_gerar_projeto_inexistente_404(self, client):
        r = client.post("/narracoes/nao-existe/gerar")
        assert r.status_code == 404

    def test_pipeline_completo_gerar_baixar_remover(self, client, motor_falso, app_module):
        pid = self._cria_projeto_pronto(client)
        try:
            r = client.post(f"/narracoes/{pid}/gerar")
            assert r.status_code == 200 and r.get_json()["ok"] is True

            # tentar de novo enquanto roda -> 409 (pode já ter terminado
            # se a máquina for rápida, então aceita os dois)
            r2 = client.post(f"/narracoes/{pid}/gerar")
            assert r2.status_code in (200, 409)

            status = _espera_geracao_terminar(client, pid)
            assert status["pronto"] is True
            assert status["erro"] is None
            assert len(motor_falso) == 2  # uma chamada por fala

            import narracoes as na
            geracoes = na.carregar_geracoes(app_module.BASE_DIR, pid)
            assert len(geracoes) == 1
            geracao_id = geracoes[0]["id"]

            r3 = client.get(f"/narracoes/{pid}/geracoes/{geracao_id}/audio")
            assert r3.status_code == 200 and len(r3.data) > 100

            r4 = client.post(f"/narracoes/{pid}/geracoes/{geracao_id}/remover")
            assert r4.status_code == 302
            assert na.carregar_geracoes(app_module.BASE_DIR, pid) == []
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_gerar_com_erro_no_motor_aparece_no_status(self, client, app_module):
        import tts.voice_generator as vg_mod

        def fake_com_erro(engine, texto, output_path, **kwargs):
            raise vg_mod.VoiceGeneratorError("falha proposital de teste")

        original = vg_mod.gerar_audio
        vg_mod.gerar_audio = fake_com_erro
        pid = self._cria_projeto_pronto(client)
        try:
            client.post(f"/narracoes/{pid}/gerar")
            status = _espera_geracao_terminar(client, pid)
            assert status["pronto"] is True
            assert "falha proposital" in status["erro"]
        finally:
            vg_mod.gerar_audio = original
            client.post(f"/narracoes/{pid}/excluir")

    def test_baixar_geracao_inexistente_404(self, client):
        pid = self._cria_projeto_pronto(client)
        try:
            r = client.get(f"/narracoes/{pid}/geracoes/nao-existe/audio")
            assert r.status_code == 404
        finally:
            client.post(f"/narracoes/{pid}/excluir")


# --------------------------------------------------------------------------- #
# Navegação: os links novos aparecem em toda página (base.html)
# --------------------------------------------------------------------------- #

def test_links_de_navegacao_aparecem_na_home(client):
    r = client.get("/")
    assert "Gerador de voz".encode() in r.data
    assert "Roteiro para \u00c1udio".encode() in r.data
    assert "Perfis de voz".encode() in r.data


# --------------------------------------------------------------------------- #
# Aba dedicada de Perfis de voz (/perfis-de-voz)
# --------------------------------------------------------------------------- #

def _gera_audio_real(caminho, duracao=4):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duracao}", caminho],
        capture_output=True, check=True,
    )


def _gera_video_com_audio_real(caminho, duracao=8):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size=320x240:duration={duracao}:rate=10",
         "-f", "lavfi", "-i", f"sine=frequency=300:duration={duracao}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", caminho],
        capture_output=True, check=True,
    )


class _FakeYoutubeDLPerfil:
    """yt-dlp falso pra extração de perfil via YouTube -- devolve um
    vídeo de teste COM áudio (diferente do `video_teste` de
    `test_youtube_clipper.py`, que é só imagem)."""
    origem_video = None
    duracao_reportada = 60.0  # precisa bater com a duração REAL do `origem_video` em cada teste

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def extract_info(self, url, download=True):
        video_id = "fakeidperfil1"
        destino = self.opts["outtmpl"].replace("%(id)s", video_id).replace("%(ext)s", "mp4")
        shutil.copy(self.origem_video, destino)
        return {"id": video_id, "title": f"Vídeo de teste — {url}", "duration": self.duracao_reportada, "ext": "mp4"}

    def prepare_filename(self, info):
        return self.opts["outtmpl"].replace("%(id)s", info["id"]).replace("%(ext)s", info["ext"])


class TestPerfisDeVozPage:
    def test_pagina_carrega_vazia(self, client):
        r = client.get("/perfis-de-voz")
        assert r.status_code == 200
        assert "Nenhum perfil ainda".encode() in r.data

    def test_criar_perfil_com_varios_arquivos(self, client, tmp_path):
        c1, c2 = tmp_path / "c1.wav", tmp_path / "c2.wav"
        _gera_audio_real(c1)
        _gera_audio_real(c2)
        try:
            with open(c1, "rb") as f1, open(c2, "rb") as f2:
                r = client.post("/perfis-de-voz/criar", data={
                    "nome": "perfil_teste_app", "audios": [(f1, "c1.wav"), (f2, "c2.wav")],
                }, content_type="multipart/form-data")
            assert r.status_code == 302

            r2 = client.get("/perfis-de-voz")
            assert b"perfil_teste_app" in r2.data
            assert b"2 clipe" in r2.data
        finally:
            client.post("/perfis-de-voz/perfil_teste_app/excluir")

    def test_criar_perfil_audio_longo_unico_divide_automaticamente(self, client, tmp_path):
        longo = tmp_path / "longo.wav"
        _gera_audio_real(longo, duracao=90)
        try:
            with open(longo, "rb") as f:
                r = client.post("/perfis-de-voz/criar", data={
                    "nome": "perfil_longo_app", "audios": [(f, "longo.wav")],
                    "dividir_automaticamente": "on",  # estado padrão da checkbox no template (marcada)
                }, content_type="multipart/form-data")
            assert r.status_code == 302

            r2 = client.get("/perfis-de-voz")
            import re
            m = re.search(rb"perfil_longo_app.*?(\d+) clipe", r2.data, re.S)
            assert m and int(m.group(1)) > 1
        finally:
            client.post("/perfis-de-voz/perfil_longo_app/excluir")

    def test_criar_perfil_audio_longo_sem_dividir(self, client, tmp_path):
        longo = tmp_path / "longo2.wav"
        _gera_audio_real(longo, duracao=90)
        try:
            with open(longo, "rb") as f:
                r = client.post("/perfis-de-voz/criar", data={
                    "nome": "perfil_longo_sem_div", "audios": [(f, "longo2.wav")],
                    # sem "dividir_automaticamente" no form -- checkbox desmarcada
                }, content_type="multipart/form-data")
            assert r.status_code == 302
            r2 = client.get("/perfis-de-voz")
            import re
            m = re.search(rb"perfil_longo_sem_div.*?(\d+) clipe", r2.data, re.S)
            assert m and int(m.group(1)) == 1
        finally:
            client.post("/perfis-de-voz/perfil_longo_sem_div/excluir")

    def test_criar_sem_nome_mostra_erro(self, client, tmp_path):
        c1 = tmp_path / "c1.wav"
        _gera_audio_real(c1)
        with open(c1, "rb") as f:
            r = client.post("/perfis-de-voz/criar", data={
                "nome": "", "audios": [(f, "c1.wav")],
            }, content_type="multipart/form-data")
        assert r.status_code == 200
        assert "Dê um nome".encode() in r.data

    def test_criar_sem_arquivo_mostra_erro(self, client):
        r = client.post("/perfis-de-voz/criar", data={"nome": "sem_arquivo"})
        assert r.status_code == 200
        assert "Envie pelo menos um".encode() in r.data

    def test_streaming_de_clipe_individual(self, client, tmp_path):
        c1 = tmp_path / "c1.wav"
        _gera_audio_real(c1)
        try:
            with open(c1, "rb") as f:
                client.post("/perfis-de-voz/criar", data={
                    "nome": "perfil_streaming", "audios": [(f, "c1.wav")],
                }, content_type="multipart/form-data")
            r = client.get("/perfis-de-voz/perfil_streaming/clipe/0")
            assert r.status_code == 200
            assert len(r.data) > 100
            r2 = client.get("/perfis-de-voz/perfil_streaming/clipe/5")
            assert r2.status_code == 404
        finally:
            client.post("/perfis-de-voz/perfil_streaming/excluir")

    def test_clipe_de_perfil_inexistente_404(self, client):
        r = client.get("/perfis-de-voz/nao-existe-mesmo/clipe/0")
        assert r.status_code == 404

    def test_excluir_perfil_inexistente_nao_quebra(self, client):
        r = client.post("/perfis-de-voz/nao-existe-mesmo/excluir")
        assert r.status_code == 302

    def test_upload_de_video_extrai_audio_automaticamente(self, client, tmp_path):
        """Diferente de áudio puro, um arquivo de VÍDEO (com trilha de
        áudio) enviado pelo mesmo formulário de sempre também cria o
        perfil normalmente -- o ffmpeg já extrai só o áudio sozinho,
        sem precisar de nenhum tratamento especial no backend."""
        video = tmp_path / "video.mp4"
        _gera_video_com_audio_real(video)
        try:
            with open(video, "rb") as f:
                r = client.post("/perfis-de-voz/criar", data={
                    "nome": "perfil_de_video_app", "audios": [(f, "video.mp4")],
                }, content_type="multipart/form-data")
            assert r.status_code == 302
            r2 = client.get("/perfis-de-voz")
            assert b"perfil_de_video_app" in r2.data
            assert b"1 clipe" in r2.data
        finally:
            client.post("/perfis-de-voz/perfil_de_video_app/excluir")

    def test_youtube_buscar_sem_termo_da_erro_400(self, client):
        r = client.get("/perfis-de-voz/youtube/buscar")
        assert r.status_code == 400
        assert "termo" in r.get_json()["erro"].lower() or "busca" in r.get_json()["erro"].lower()

    def test_youtube_extrair_sem_nome_da_erro_400(self, client):
        r = client.post("/perfis-de-voz/youtube/extrair", json={
            "itens": [{"url": "https://x", "trechos": [{"inicio": "0", "fim": "5"}]}],
        })
        assert r.status_code == 400
        assert "nome" in r.get_json()["erro"].lower()

    def test_youtube_extrair_sem_itens_da_erro_400(self, client):
        r = client.post("/perfis-de-voz/youtube/extrair", json={"nome": "algum_nome"})
        assert r.status_code == 400

    def test_youtube_status_job_inexistente_404(self, client):
        r = client.get("/perfis-de-voz/youtube/nao-existe/status")
        assert r.status_code == 404

    def test_youtube_extrair_fluxo_completo(self, client, app_module, tmp_path, monkeypatch):
        """Ponta a ponta pela ROTA: baixa (com yt-dlp falso), corta os
        trechos, e salva como perfil de voz de verdade -- confere que
        o job termina 'pronto', com o número certo de clipes, e que o
        perfil aparece na página depois."""
        import youtube_clipper as yc_mod

        video_com_audio = tmp_path / "video_origem.mp4"
        _gera_video_com_audio_real(video_com_audio, duracao=40)
        fake_cls = type("FakeYtDlpPerfil", (_FakeYoutubeDLPerfil,), {"origem_video": str(video_com_audio)})
        fake_mod = type("FakeYtDlpModulo", (), {"YoutubeDL": fake_cls})

        original = yc_mod.extrair_perfil_de_voz_do_youtube

        def com_modulo_falso(itens, nome_perfil, qualidade="1080p", on_log=None, ytdlp_module=None):
            return original(itens, nome_perfil, qualidade=qualidade, on_log=on_log, ytdlp_module=fake_mod)

        monkeypatch.setattr(app_module, "yt_extrair_perfil_de_voz_do_youtube", com_modulo_falso)

        r = client.post("/perfis-de-voz/youtube/extrair", json={
            "nome": "voz_extraida_app",
            "itens": [{"url": "https://youtube.com/watch?v=teste", "trechos": [
                {"inicio": "00:05", "fim": "00:10"}, {"inicio": "00:20", "fim": "00:25"},
            ]}],
        })
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]

        deadline = time.time() + 30
        status = None
        while time.time() < deadline:
            status = client.get(f"/perfis-de-voz/youtube/{job_id}/status").get_json()
            if status["status"] != "processando":
                break
            time.sleep(0.2)
        try:
            assert status["status"] == "pronto", status.get("erro")
            assert status["quantidade_clipes"] == 2
            assert status["nome_perfil"] == "voz_extraida_app"

            r2 = client.get("/perfis-de-voz")
            assert b"voz_extraida_app" in r2.data
            assert b"2 clipe" in r2.data
        finally:
            client.post("/perfis-de-voz/voz_extraida_app/excluir")

    def test_youtube_extrair_trecho_alem_da_duracao_da_erro_no_job(self, client, app_module, tmp_path, monkeypatch):
        import youtube_clipper as yc_mod

        video_curto = tmp_path / "video_curto.mp4"
        _gera_video_com_audio_real(video_curto, duracao=5)
        fake_cls = type("FakeYtDlpPerfilCurto", (_FakeYoutubeDLPerfil,),
                         {"origem_video": str(video_curto), "duracao_reportada": 5.0})
        fake_mod = type("FakeYtDlpModuloCurto", (), {"YoutubeDL": fake_cls})

        original = yc_mod.extrair_perfil_de_voz_do_youtube

        def com_modulo_falso(itens, nome_perfil, qualidade="1080p", on_log=None, ytdlp_module=None):
            return original(itens, nome_perfil, qualidade=qualidade, on_log=on_log, ytdlp_module=fake_mod)

        monkeypatch.setattr(app_module, "yt_extrair_perfil_de_voz_do_youtube", com_modulo_falso)

        r = client.post("/perfis-de-voz/youtube/extrair", json={
            "nome": "vai_falhar_app",
            "itens": [{"url": "https://x", "trechos": [{"inicio": "00:30", "fim": "00:40"}]}],  # video so tem 5s
        })
        job_id = r.get_json()["job_id"]

        deadline = time.time() + 30
        status = None
        while time.time() < deadline:
            status = client.get(f"/perfis-de-voz/youtube/{job_id}/status").get_json()
            if status["status"] != "processando":
                break
            time.sleep(0.2)
        assert status["status"] == "erro"
        assert "depois do fim do vídeo" in status["erro"]
        assert "vai_falhar_app" not in app_module.tts_listar_perfis_de_voz()


# --------------------------------------------------------------------------- #
# Gravação da própria voz por fala (rotas Flask) — MediaRecorder no
# navegador manda o blob aqui; testado com áudio real (sine wave via
# ffmpeg), sem precisar de navegador nenhum.
# --------------------------------------------------------------------------- #

def _audio_gravado_bytes(duracao=3):
    p = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=300:duration={duracao}", "-f", "wav", "pipe:1"],
        capture_output=True, check=True,
    )
    return p.stdout


class TestNarracoesGravacao:
    def _cria_projeto_com_fala(self, client):
        r = client.post("/narracoes", data={"nome": "Projeto com gravação"})
        pid = r.headers["Location"].rsplit("/", 1)[-1]
        client.post(f"/narracoes/{pid}/roteiro", data={"texto": "Primeira fala.\nSegunda fala."})
        return pid

    def test_pagina_sem_gravacoes_mostra_botao_e_estado_vazio(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            r = client.get(f"/narracoes/{pid}")
            assert b"Gravar minha voz" in r.data
            assert b"var GRAVACOES = {}" in r.data
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_listar_gravacoes_projeto_inexistente_404(self, client):
        r = client.get("/narracoes/nao-existe/gravacoes")
        assert r.status_code == 404

    def test_gravar_sem_arquivo_400(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={})
            assert r.status_code == 400
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_gravar_fala_inexistente_da_erro(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes())
            r = client.post(f"/narracoes/{pid}/fala/99/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            assert r.status_code == 400
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_gravar_e_listar_fluxo_completo(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes())
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            assert r.status_code == 200
            data = r.get_json()
            assert data["usar"] is True
            assert data["duracaoSegundos"] > 2.5
            take_id = data["takeId"]

            r2 = client.get(f"/narracoes/{pid}")
            assert take_id.encode() in r2.data

            r3 = client.get(f"/narracoes/{pid}/gravacoes")
            gravacoes = r3.get_json()
            assert gravacoes["0"]["takeAtivo"] == take_id
            assert len(gravacoes["0"]["takes"]) == 1
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_streaming_de_audio_de_um_take(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes())
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            take_id = r.get_json()["takeId"]

            r2 = client.get(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/audio")
            assert r2.status_code == 200
            assert len(r2.data) > 100
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_audio_de_take_inexistente_404(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            r = client.get(f"/narracoes/{pid}/fala/0/gravacao/nao-existe/audio")
            assert r.status_code == 404
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_alternar_uso_da_gravacao(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes())
            client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")

            r = client.post(f"/narracoes/{pid}/fala/0/usar-gravacao", json={"usar": False})
            assert r.status_code == 200
            assert r.get_json()["usar"] is False

            r2 = client.post(f"/narracoes/{pid}/fala/0/usar-gravacao", json={"usar": True})
            assert r2.get_json()["usar"] is True
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_selecionar_take_valido_e_invalido(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio1 = io.BytesIO(_audio_gravado_bytes())
            r1 = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio1, "g1.webm")}, content_type="multipart/form-data")
            take1 = r1.get_json()["takeId"]
            audio2 = io.BytesIO(_audio_gravado_bytes())
            r2 = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio2, "g2.webm")}, content_type="multipart/form-data")

            r3 = client.post(f"/narracoes/{pid}/fala/0/selecionar-take", json={"takeId": take1})
            assert r3.status_code == 200
            assert r3.get_json()["takeAtivo"] == take1

            r4 = client.post(f"/narracoes/{pid}/fala/0/selecionar-take", json={"takeId": "nao-existe"})
            assert r4.status_code == 400
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_excluir_take_pela_rota(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes())
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            take_id = r.get_json()["takeId"]

            r2 = client.post(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/excluir")
            assert r2.status_code == 200

            r3 = client.get(f"/narracoes/{pid}/gravacoes")
            assert r3.get_json()["0"]["takes"] == []
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_excluir_take_de_fala_sem_gravacao_nao_quebra(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            r = client.post(f"/narracoes/{pid}/fala/0/gravacao/qualquer/excluir")
            assert r.status_code == 200
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_pipeline_de_geracao_usa_gravacao_da_rota(self, client, motor_falso):
        """Ponta a ponta pela API HTTP: grava uma fala pelo microfone
        (simulado), gera o áudio final, e confirma que essa fala NÃO
        chamou o motor de TTS (usou a gravação em vez disso)."""
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes(duracao=2))
            client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            client.post(f"/narracoes/{pid}/config", data={"pausa_segundos": "0.2"})

            client.post(f"/narracoes/{pid}/gerar")
            status = _espera_geracao_terminar(client, pid)
            assert status["pronto"] is True and status["erro"] is None
            assert len(motor_falso) == 1  # só a segunda fala (sem gravação) chamou o TTS
            assert "gravação própria" in status["log"]
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_gerar_realce_pela_rota(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes())
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            take_id = r.get_json()["takeId"]

            r2 = client.post(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/realce")
            assert r2.status_code == 200
            data = r2.get_json()
            assert data["enhancedGerado"] is True
            assert data["usarEnhance"] is True

            r3 = client.get(f"/narracoes/{pid}")
            assert take_id.encode() in r3.data
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_gerar_realce_take_inexistente_400(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            r = client.post(f"/narracoes/{pid}/fala/0/gravacao/nao-existe/realce")
            assert r.status_code == 400
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_streaming_do_audio_com_realce(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes())
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            take_id = r.get_json()["takeId"]
            client.post(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/realce")

            r2 = client.get(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/audio-realce")
            assert r2.status_code == 200
            assert len(r2.data) > 100
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_audio_com_realce_nao_gerado_404(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes())
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            take_id = r.get_json()["takeId"]
            r2 = client.get(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/audio-realce")
            assert r2.status_code == 404
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_alternar_uso_do_realce_pela_rota(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes())
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            take_id = r.get_json()["takeId"]
            client.post(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/realce")

            r2 = client.post(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/usar-realce", json={"usarEnhance": False})
            assert r2.status_code == 200
            assert r2.get_json()["usarEnhance"] is False
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_usar_realce_sem_gerar_antes_400(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes())
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            take_id = r.get_json()["takeId"]
            r2 = client.post(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/usar-realce", json={"usarEnhance": True})
            assert r2.status_code == 400
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_excluir_take_remove_o_realce_tambem_pela_rota(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes())
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            take_id = r.get_json()["takeId"]
            client.post(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/realce")

            client.post(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/excluir")
            r2 = client.get(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/audio-realce")
            assert r2.status_code == 404
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_recortar_take_pela_rota(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes(duracao=10))
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            take_id = r.get_json()["takeId"]

            r2 = client.post(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/recortar", json={"inicio": 2.0, "fim": 6.0})
            assert r2.status_code == 200
            data = r2.get_json()
            assert abs(data["duracaoSegundos"] - 4.0) < 0.3
            assert data["recortado"] is True
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_recortar_take_fim_menor_que_inicio_400(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes(duracao=5))
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            take_id = r.get_json()["takeId"]
            r2 = client.post(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/recortar", json={"inicio": 4.0, "fim": 1.0})
            assert r2.status_code == 400
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_recortar_take_valores_invalidos_400(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes(duracao=5))
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            take_id = r.get_json()["takeId"]
            r2 = client.post(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/recortar", json={"inicio": "abc", "fim": 2.0})
            assert r2.status_code == 400
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_desfazer_corte_pela_rota(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes(duracao=10))
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            take_id = r.get_json()["takeId"]
            client.post(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/recortar", json={"inicio": 2.0, "fim": 6.0})

            r2 = client.post(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/desfazer-corte")
            assert r2.status_code == 200
            data = r2.get_json()
            assert abs(data["duracaoSegundos"] - 10.0) < 0.3
            assert data["recortado"] is False
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_desfazer_corte_sem_corte_400(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes())
            r = client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            take_id = r.get_json()["takeId"]
            r2 = client.post(f"/narracoes/{pid}/fala/0/gravacao/{take_id}/desfazer-corte")
            assert r2.status_code == 400
        finally:
            client.post(f"/narracoes/{pid}/excluir")

    def test_pagina_mostra_editor_de_audio(self, client):
        pid = self._cria_projeto_com_fala(client)
        try:
            audio = io.BytesIO(_audio_gravado_bytes())
            client.post(f"/narracoes/{pid}/fala/0/gravar", data={"audio": (audio, "g.webm")}, content_type="multipart/form-data")
            r = client.get(f"/narracoes/{pid}")
            assert b"abrirEditorAudio" in r.data
            assert b"Editar \xc3\xa1udio" in r.data or "Editar áudio".encode() in r.data
            assert b"editor_audio.js" in r.data  # v84_325: o editor de forma de onda completo mora em static/editor_audio.js
            js = client.get("/static/editor_audio.js").data
            assert b"montarBufferEditado" in js and b"function abrirEditorAudio" in js
        finally:
            client.post(f"/narracoes/{pid}/excluir")


class TestGerarVozDoRoteiro:
    def test_audio_do_roteiro_ajusta_os_capitulos(self, client, app_module, motor_falso, whisper_falso, monkeypatch, tmp_path):
        """Gerar voz aberto pelo Roteiro do YouTube: no fim, os capítulos da descrição
        ganham o tempo real do áudio (palavras do Whisper)."""
        import json as _json
        import roteiros_yt as ry
        monkeypatch.setattr(app_module, "BASE_DIR", str(tmp_path))
        p = ry.criar_projeto(str(tmp_path), texto="[0:00] x")
        roteiro = "Olá mundo bonito"
        p["analise"] = {"roteiro": roteiro, "cenas": []}
        p["resultado"] = ry.ler_resultado(_json.dumps({"roteiro_final": roteiro, "descricao": "D",
                                                       "capitulos": [{"titulo": "Início", "comeca_em": "Olá mundo"},
                                                                     {"titulo": "Final", "comeca_em": "bonito"}]}), p)
        ry.salvar_projeto(str(tmp_path), p)
        assert f'name="roteiro_id" value="{p["id"]}"' in client.get(f"/gerar-voz?roteiro={p['id']}").get_data(as_text=True)
        r = client.post("/gerar-voz/gerar", data={"texto": roteiro, "engine": "piper", "roteiro_id": p["id"]})
        st = _espera_gerar_voz_terminar(client, r.get_json()["job_id"])
        assert st["erro"] is None and "0:00 Início" in st["resultado"]["roteiro_descricao"]
        caps = ry.carregar_projeto(str(tmp_path), p["id"])["resultado"]["capitulos"]
        assert caps[1]["segundos_audio"] >= 1.0  # "bonito" foi dito em 1,0 s (e o YouTube pede 10 s entre capítulos)
