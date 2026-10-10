"""
Teste de conversa.py — "Simular Conversa": várias falas em sequência,
cada uma podendo usar um motor/voz DIFERENTE (ao contrário do Roteiro
para Áudio, onde o motor/voz é uma config única do projeto inteiro).
Motor de voz mockado (gera um tom puro via ffmpeg) — sem depender de
nenhuma das libs pesadas de TTS instaladas.
"""
import subprocess
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))

import conversa as cv
import tts.voice_generator as vg_mod


@pytest.fixture(autouse=True)
def motor_falso(monkeypatch):
    chamadas = []

    def fake_gerar_audio(engine, texto, output_path, **kwargs):
        chamadas.append({"engine": engine, "texto": texto, "kwargs": kwargs})
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=1",
             "-ar", "22050", "-ac", "1", output_path],
            capture_output=True, check=True,
        )
        return output_path

    monkeypatch.setattr(vg_mod, "gerar_audio", fake_gerar_audio)
    return chamadas


# --------------------------------------------------------------------------- #
# Criar/carregar/listar/excluir conversas
# --------------------------------------------------------------------------- #

def test_criar_conversa_com_nome(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "Minha conversa")
    assert c["nome"] == "Minha conversa"
    assert c["falas"] == []
    assert "conversaId" in c


def test_criar_conversa_sem_nome_usa_padrao(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "")
    assert c["nome"]  # tem algum nome padrão, não vazio


def test_carregar_conversa_inexistente_da_erro(tmp_path):
    with pytest.raises(cv.ConversaError, match="não encontrada"):
        cv.carregar_conversa(str(tmp_path), "nao-existe")


def test_conversa_existe(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    assert cv.conversa_existe(str(tmp_path), c["conversaId"]) is True
    assert cv.conversa_existe(str(tmp_path), "nao-existe") is False


def test_listar_conversas_ordenadas_mais_recente_primeiro(tmp_path):
    import time
    c1 = cv.criar_conversa(str(tmp_path), "Primeira")
    time.sleep(0.01)
    c2 = cv.criar_conversa(str(tmp_path), "Segunda")
    lista = cv.listar_conversas(str(tmp_path))
    assert lista[0]["conversaId"] == c2["conversaId"]
    assert lista[1]["conversaId"] == c1["conversaId"]


def test_listar_conversas_pasta_vazia(tmp_path):
    assert cv.listar_conversas(str(tmp_path)) == []


def test_excluir_conversa(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    cv.excluir_conversa(str(tmp_path), c["conversaId"])
    assert cv.conversa_existe(str(tmp_path), c["conversaId"]) is False


def test_excluir_conversa_inexistente_nao_quebra(tmp_path):
    cv.excluir_conversa(str(tmp_path), "nao-existe")  # não deve levantar nada


def test_renomear_conversa(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "Nome velho")
    atualizado = cv.renomear_conversa(str(tmp_path), c["conversaId"], "Nome novo")
    assert atualizado["nome"] == "Nome novo"
    recarregado = cv.carregar_conversa(str(tmp_path), c["conversaId"])
    assert recarregado["nome"] == "Nome novo"


def test_salvar_pausa(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    atualizado = cv.salvar_pausa(str(tmp_path), c["conversaId"], 1.5)
    assert atualizado["pausaSegundos"] == 1.5


def test_salvar_pausa_limita_faixa(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    atualizado = cv.salvar_pausa(str(tmp_path), c["conversaId"], 999)
    assert atualizado["pausaSegundos"] == 10.0
    atualizado2 = cv.salvar_pausa(str(tmp_path), c["conversaId"], -5)
    assert atualizado2["pausaSegundos"] == 0.0


# --------------------------------------------------------------------------- #
# Falas — adicionar/editar/remover/mover
# --------------------------------------------------------------------------- #

def test_adicionar_fala(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Olá!", motor="piper", voz="pt_BR-faber-medium")
    assert fala["texto"] == "Olá!"
    assert fala["motor"] == "piper"
    assert fala["status"] == "pendente"
    conversa = cv.carregar_conversa(str(tmp_path), c["conversaId"])
    assert len(conversa["falas"]) == 1


def test_adicionar_fala_texto_vazio_da_erro(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    with pytest.raises(cv.ConversaError, match="texto"):
        cv.adicionar_fala(str(tmp_path), c["conversaId"], "   ", motor="piper")


def test_adicionar_fala_motor_invalido_da_erro(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    with pytest.raises(cv.ConversaError, match="Motor"):
        cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="motor-invalido")


def test_adicionar_varias_falas_com_motores_diferentes(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    cv.adicionar_fala(str(tmp_path), c["conversaId"], "Fala 1", motor="piper")
    cv.adicionar_fala(str(tmp_path), c["conversaId"], "Fala 2", motor="kokoro")
    cv.adicionar_fala(str(tmp_path), c["conversaId"], "Fala 3", motor="xtts")
    conversa = cv.carregar_conversa(str(tmp_path), c["conversaId"])
    assert [f["motor"] for f in conversa["falas"]] == ["piper", "kokoro", "xtts"]


def test_editar_fala_texto(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Original", motor="piper")
    atualizada = cv.editar_fala(str(tmp_path), c["conversaId"], fala["id"], texto="Editado")
    assert atualizada["texto"] == "Editado"


def test_editar_fala_motor_e_voz(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="piper", voz="voz-a")
    atualizada = cv.editar_fala(str(tmp_path), c["conversaId"], fala["id"], motor="kokoro", voz="voz-b")
    assert atualizada["motor"] == "kokoro"
    assert atualizada["voz"] == "voz-b"


def test_editar_fala_motor_invalido_da_erro(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="piper")
    with pytest.raises(cv.ConversaError, match="Motor"):
        cv.editar_fala(str(tmp_path), c["conversaId"], fala["id"], motor="invalido")


def test_editar_fala_inexistente_da_erro(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    with pytest.raises(cv.ConversaError, match="não encontrada"):
        cv.editar_fala(str(tmp_path), c["conversaId"], "nao-existe", texto="X")


def test_editar_fala_invalida_audio_ja_gerado(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="piper")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    caminho = cv.caminho_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    assert caminho.exists()

    cv.editar_fala(str(tmp_path), c["conversaId"], fala["id"], texto="Texto novo")
    assert not caminho.exists()
    with pytest.raises(cv.ConversaError):
        cv.caminho_audio_fala(str(tmp_path), c["conversaId"], fala["id"])


def test_remover_fala(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    f1 = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Um", motor="piper")
    f2 = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Dois", motor="piper")
    cv.remover_fala(str(tmp_path), c["conversaId"], f1["id"])
    conversa = cv.carregar_conversa(str(tmp_path), c["conversaId"])
    assert len(conversa["falas"]) == 1
    assert conversa["falas"][0]["id"] == f2["id"]


def test_remover_fala_remove_audio_tambem(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="piper")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    caminho = cv.caminho_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    assert caminho.exists()
    cv.remover_fala(str(tmp_path), c["conversaId"], fala["id"])
    assert not caminho.exists()


def test_mover_fala_cima(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    f1 = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Um", motor="piper")
    f2 = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Dois", motor="piper")
    cv.mover_fala(str(tmp_path), c["conversaId"], f2["id"], "cima")
    conversa = cv.carregar_conversa(str(tmp_path), c["conversaId"])
    assert [f["id"] for f in conversa["falas"]] == [f2["id"], f1["id"]]


def test_mover_fala_ja_no_topo_nao_quebra(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    f1 = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Um", motor="piper")
    cv.adicionar_fala(str(tmp_path), c["conversaId"], "Dois", motor="piper")
    cv.mover_fala(str(tmp_path), c["conversaId"], f1["id"], "cima")  # já está no topo
    conversa = cv.carregar_conversa(str(tmp_path), c["conversaId"])
    assert conversa["falas"][0]["id"] == f1["id"]


def test_mover_fala_direcao_invalida_da_erro(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Um", motor="piper")
    with pytest.raises(cv.ConversaError, match="cima.*baixo|baixo.*cima"):
        cv.mover_fala(str(tmp_path), c["conversaId"], fala["id"], "lado")


# --------------------------------------------------------------------------- #
# Geração individual — motor certo, kwargs certos, texto limpo
# --------------------------------------------------------------------------- #

def test_gerar_audio_fala_usa_o_motor_certo(tmp_path, motor_falso):
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="kokoro", voz="pf_dora")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    assert motor_falso[0]["engine"] == "kokoro"
    assert motor_falso[0]["kwargs"]["voz"] == "pf_dora"


def test_gerar_audio_fala_piper_usa_nome_voz(tmp_path, motor_falso):
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="piper", voz="pt_BR-edresson-low")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    assert motor_falso[0]["kwargs"]["nome_voz"] == "pt_BR-edresson-low"


def test_gerar_audio_fala_xtts_sem_voz_perfil_usa_speaker(tmp_path, motor_falso):
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="xtts", voz="Ana Florence")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    assert motor_falso[0]["kwargs"]["speaker"] == "Ana Florence"
    assert "voice_profile" not in motor_falso[0]["kwargs"]


def test_gerar_audio_fala_xtts_com_perfil_salvo_usa_voice_profile(tmp_path, monkeypatch, motor_falso):
    monkeypatch.setattr(vg_mod, "listar_perfis_de_voz", lambda: ["meu_perfil"])
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="xtts", voz="meu_perfil")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    assert motor_falso[0]["kwargs"]["voice_profile"] == "meu_perfil"
    assert "speaker" not in motor_falso[0]["kwargs"]


def test_gerar_audio_fala_chatterbox_sem_perfil_usa_voz_neutra(tmp_path, monkeypatch, motor_falso):
    """Diferente do XTTS, o Chatterbox não tem "voz pronta com nome" --
    um nome que não bate com nenhum perfil salvo é ignorado (cai pra
    voz neutra padrão do modelo), em vez de virar um kwarg "speaker"."""
    monkeypatch.setattr(vg_mod, "listar_perfis_de_voz", lambda: [])
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="chatterbox", voz="nome qualquer")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    assert motor_falso[0]["engine"] == "chatterbox"
    assert "voice_profile" not in motor_falso[0]["kwargs"]
    assert "speaker" not in motor_falso[0]["kwargs"]
    assert motor_falso[0]["kwargs"]["idioma"] == "pt"


def test_gerar_audio_fala_chatterbox_com_perfil_salvo_usa_voice_profile(tmp_path, monkeypatch, motor_falso):
    monkeypatch.setattr(vg_mod, "listar_perfis_de_voz", lambda: ["meu_perfil"])
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="chatterbox", voz="meu_perfil", idioma="en")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    assert motor_falso[0]["kwargs"]["voice_profile"] == "meu_perfil"
    assert motor_falso[0]["kwargs"]["idioma"] == "en"
    assert motor_falso[0]["kwargs"]["exaggeration"] == 0.5
    assert motor_falso[0]["kwargs"]["cfg_weight"] == 0.5


def test_gerar_audio_fala_chatterbox_turbo_sem_perfil_usa_voz_neutra(tmp_path, monkeypatch, motor_falso):
    monkeypatch.setattr(vg_mod, "listar_perfis_de_voz", lambda: [])
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Hi", motor="chatterbox_turbo", voz="nome qualquer")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    assert motor_falso[0]["engine"] == "chatterbox_turbo"
    assert "voice_profile" not in motor_falso[0]["kwargs"]
    assert "idioma" not in motor_falso[0]["kwargs"]
    assert "exaggeration" not in motor_falso[0]["kwargs"]
    assert "cfg_weight" not in motor_falso[0]["kwargs"]


def test_gerar_audio_fala_chatterbox_turbo_com_perfil_salvo_usa_voice_profile(tmp_path, monkeypatch, motor_falso):
    monkeypatch.setattr(vg_mod, "listar_perfis_de_voz", lambda: ["meu_perfil"])
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Hi", motor="chatterbox_turbo", voz="meu_perfil")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    assert motor_falso[0]["kwargs"]["voice_profile"] == "meu_perfil"
    assert "idioma" not in motor_falso[0]["kwargs"]


def test_gerar_audio_fala_chatterbox_turbo_preserva_tags_no_texto(tmp_path, motor_falso):
    """Bug real que corrigi: a limpeza de texto removia TODOS os
    colchetes antes de mandar pro motor -- destruiria tags como
    "[chuckle]" (viraria só "chuckle", sem efeito nenhum). Só quando o
    motor é chatterbox_turbo é que as tags reconhecidas sobrevivem."""
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Hi there [chuckle], welcome!", motor="chatterbox_turbo")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    assert "[chuckle]" in motor_falso[0]["texto"]


def test_gerar_audio_fala_chatterbox_normal_nao_preserva_tags(tmp_path, motor_falso):
    """Confirma que o motor chatterbox (multilíngue, não-turbo) NÃO
    ganha essa preservação -- ele não entende essas tags, então os
    colchetes continuam sendo removidos como sempre."""
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi [chuckle], tudo bem?", motor="chatterbox")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    assert "[chuckle]" not in motor_falso[0]["texto"]


def test_gerar_audio_fala_limpa_pontuacao(tmp_path, motor_falso):
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], 'Ele disse: "uau..." (sério).', motor="piper")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    texto_mandado = motor_falso[0]["texto"]
    assert '"' not in texto_mandado
    assert "(" not in texto_mandado
    assert "..." not in texto_mandado


def test_gerar_audio_fala_marca_status_pronto_com_duracao(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="piper")
    resultado = cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    assert resultado["status"] == "pronto"
    assert resultado["duracaoSegundos"] > 0

    conversa = cv.carregar_conversa(str(tmp_path), c["conversaId"])
    fala_salva = conversa["falas"][0]
    assert fala_salva["status"] == "pronto"
    assert fala_salva["duracaoSegundos"] > 0


def test_gerar_audio_fala_erro_do_motor_marca_status_erro(tmp_path, monkeypatch):
    from tts.voice_generator import VoiceGeneratorError

    def fake_falha(engine, texto, output_path, **kwargs):
        raise VoiceGeneratorError("motor não instalado (simulado)")

    monkeypatch.setattr(vg_mod, "gerar_audio", fake_falha)
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="piper")
    with pytest.raises(cv.ConversaError, match="não instalado"):
        cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])

    conversa = cv.carregar_conversa(str(tmp_path), c["conversaId"])
    assert conversa["falas"][0]["status"] == "erro"
    assert "não instalado" in conversa["falas"][0]["erro"]


def test_gerar_audio_fala_inexistente_da_erro(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    with pytest.raises(cv.ConversaError, match="não encontrada"):
        cv.gerar_audio_fala(str(tmp_path), c["conversaId"], "nao-existe")


def test_caminho_audio_fala_antes_de_gerar_da_erro(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="piper")
    with pytest.raises(cv.ConversaError, match="ainda não tem áudio"):
        cv.caminho_audio_fala(str(tmp_path), c["conversaId"], fala["id"])


# --------------------------------------------------------------------------- #
# Combinar todas as falas num único áudio
# --------------------------------------------------------------------------- #

def test_gerar_audio_completo_combina_falas_prontas(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    f1 = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Um", motor="piper")
    f2 = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Dois", motor="kokoro")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], f1["id"])
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], f2["id"])

    resultado = cv.gerar_audio_completo(str(tmp_path), c["conversaId"])
    assert resultado["quantidadeFalas"] == 2
    assert resultado["duracaoSegundos"] > 0
    assert os.path.exists(resultado["arquivo"])


def test_gerar_audio_completo_pula_falas_sem_audio(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    f1 = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Um", motor="piper")
    cv.adicionar_fala(str(tmp_path), c["conversaId"], "Dois (nunca gerada)", motor="piper")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], f1["id"])

    resultado = cv.gerar_audio_completo(str(tmp_path), c["conversaId"])
    assert resultado["quantidadeFalas"] == 1  # só a que tinha áudio


def test_gerar_audio_completo_sem_nenhuma_fala_pronta_da_erro(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    cv.adicionar_fala(str(tmp_path), c["conversaId"], "Nunca gerada", motor="piper")
    with pytest.raises(cv.ConversaError, match="Nenhuma fala"):
        cv.gerar_audio_completo(str(tmp_path), c["conversaId"])


def test_gerar_audio_completo_conversa_vazia_da_erro(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    with pytest.raises(cv.ConversaError, match="Nenhuma fala"):
        cv.gerar_audio_completo(str(tmp_path), c["conversaId"])


def test_gerar_audio_completo_respeita_pausa_configurada(tmp_path):
    from video_assembler import _probe_duration
    c = cv.criar_conversa(str(tmp_path), "X")
    cv.salvar_pausa(str(tmp_path), c["conversaId"], 2.0)
    f1 = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Um", motor="piper")
    f2 = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Dois", motor="piper")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], f1["id"])
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], f2["id"])

    resultado = cv.gerar_audio_completo(str(tmp_path), c["conversaId"])
    # 2 falas de ~1s cada (mock) + 2s de pausa entre elas = pelo menos ~3s
    assert resultado["duracaoSegundos"] >= 2.8


def test_caminho_audio_completo_antes_de_gerar_da_erro(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    with pytest.raises(cv.ConversaError, match="Ainda não foi gerado"):
        cv.caminho_audio_completo(str(tmp_path), c["conversaId"])


def test_caminho_audio_completo_apos_gerar(tmp_path):
    c = cv.criar_conversa(str(tmp_path), "X")
    fala = cv.adicionar_fala(str(tmp_path), c["conversaId"], "Oi", motor="piper")
    cv.gerar_audio_fala(str(tmp_path), c["conversaId"], fala["id"])
    cv.gerar_audio_completo(str(tmp_path), c["conversaId"])
    caminho = cv.caminho_audio_completo(str(tmp_path), c["conversaId"])
    assert caminho.exists()
