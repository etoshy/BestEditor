"""
Teste de narracoes.py ("Roteiro para Áudio"): criação/listagem/exclusão
de projetos, importar/editar/adicionar/remover falas, validação de
config, limpeza de texto antes do TTS, e o pipeline completo de geração
de áudio (com o motor de voz mockado — só interessa aqui que
`narracoes.py` chama certo e monta o áudio final certo; o motor em si
já é testado em `toolkit/tts/test_voice_generator.py`). Usa ffmpeg de
verdade pra concatenação/normalização/export, sem tocar rede nenhuma.
"""
import os
import subprocess

import pytest

import narracoes as na


# --------------------------------------------------------------------------- #
# Projetos
# --------------------------------------------------------------------------- #

def test_criar_projeto_usa_config_padrao(tmp_path):
    p = na.criar_projeto(str(tmp_path), "Meu roteiro")
    assert p["nome"] == "Meu roteiro"
    assert p["motor"] == "piper"
    assert p["voz"] == "pt_BR-faber-medium"
    assert p["pausaSegundos"] == 0.6
    assert "projetoId" in p


def test_criar_projeto_sem_nome_usa_nome_com_data():
    import tempfile
    base = tempfile.mkdtemp()
    p = na.criar_projeto(base, "")
    assert p["nome"].startswith("Narração ")


def test_carregar_projeto_inexistente_da_erro(tmp_path):
    with pytest.raises(na.NarracaoError, match="não encontrado"):
        na.carregar_projeto(str(tmp_path), "id-que-nao-existe")


def test_projeto_existe(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    assert na.projeto_existe(str(tmp_path), p["projetoId"]) is True
    assert na.projeto_existe(str(tmp_path), "outro-id") is False


def test_salvar_config_valida_motor(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    with pytest.raises(na.NarracaoError, match="inválido"):
        na.salvar_config(str(tmp_path), p["projetoId"], motor="motor-que-nao-existe")


def test_salvar_config_atualiza_campos_e_limita_faixas(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    atualizado = na.salvar_config(
        str(tmp_path), pid, nome="Novo nome", motor="kokoro", voz="pf_dora",
        idioma="pt-br", velocidade=5.0,  # acima do teto (2.0) -- deve ser limitado
        pausa_segundos=-1.0,  # abaixo do piso (0.0) -- deve ser limitado
        usar_gpu=False,
    )
    assert atualizado["nome"] == "Novo nome"
    assert atualizado["motor"] == "kokoro"
    assert atualizado["voz"] == "pf_dora"
    assert atualizado["velocidade"] == 2.0
    assert atualizado["pausaSegundos"] == 0.0
    assert atualizado["usarGpu"] is False

    # persistiu de verdade -- recarregar do disco confirma
    recarregado = na.carregar_projeto(str(tmp_path), pid)
    assert recarregado["motor"] == "kokoro"


def test_carregar_projeto_projetos_antigos_sem_campo_novo_usam_padrao(tmp_path):
    """Simula um projeto salvo ANTES de um campo (ex: usarGpu) existir --
    carregar não deve quebrar, e o campo ausente usa o valor padrão."""
    p = na.criar_projeto(str(tmp_path), "Antigo")
    pid = p["projetoId"]
    caminho = na.narracoes_dir(str(tmp_path)) / pid / "projeto.json"
    import json
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    del dados["usarGpu"]
    caminho.write_text(json.dumps(dados), encoding="utf-8")

    recarregado = na.carregar_projeto(str(tmp_path), pid)
    assert recarregado["usarGpu"] == na.CONFIG_PADRAO["usarGpu"]


def test_carregar_projeto_bem_antigo_sem_nenhum_dos_campos_novos_de_voz(tmp_path):
    """Projeto salvo antes de vozPerfil/xttsCheckpoint/kokoroVariante/
    kokoroPrecisao existirem -- todos precisam vir com o padrão, sem
    quebrar o carregamento."""
    p = na.criar_projeto(str(tmp_path), "Bem antigo")
    pid = p["projetoId"]
    caminho = na.narracoes_dir(str(tmp_path)) / pid / "projeto.json"
    import json
    dados_minimos = {"nome": "Bem antigo", "motor": "piper", "voz": "pt_BR-faber-medium"}
    caminho.write_text(json.dumps(dados_minimos), encoding="utf-8")

    recarregado = na.carregar_projeto(str(tmp_path), pid)
    assert recarregado["vozPerfil"] == ""
    assert recarregado["xttsCheckpoint"] == ""
    assert recarregado["kokoroVariante"] == "v1.0"
    assert recarregado["kokoroPrecisao"] == "fp32"


def test_salvar_config_campos_novos_de_voz(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    atualizado = na.salvar_config(
        str(tmp_path), pid, motor="xtts",
        voz_perfil="minha_voz", xtts_checkpoint="hindi",
        kokoro_variante="v1.1-zh", kokoro_precisao="int8",
    )
    assert atualizado["vozPerfil"] == "minha_voz"
    assert atualizado["xttsCheckpoint"] == "hindi"
    assert atualizado["kokoroVariante"] == "v1.1-zh"
    assert atualizado["kokoroPrecisao"] == "int8"

    # persistiu de verdade
    recarregado = na.carregar_projeto(str(tmp_path), pid)
    assert recarregado["vozPerfil"] == "minha_voz"
    assert recarregado["xttsCheckpoint"] == "hindi"


def test_salvar_config_kokoro_variante_precisao_vazias_caem_pro_padrao(tmp_path):
    """Mandar string vazia pra variante/precisão (ex: um <select> sem
    opção nenhuma escolhida) não deve salvar um valor inválido -- cai
    pro padrão em vez disso."""
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    atualizado = na.salvar_config(str(tmp_path), pid, kokoro_variante="", kokoro_precisao="")
    assert atualizado["kokoroVariante"] == "v1.0"
    assert atualizado["kokoroPrecisao"] == "fp32"


def test_salvar_config_nao_mexe_em_campos_nao_informados(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.salvar_config(str(tmp_path), pid, voz_perfil="minha_voz")
    # salva de novo, só mudando outro campo -- vozPerfil não deveria sumir
    atualizado = na.salvar_config(str(tmp_path), pid, motor="kokoro")
    assert atualizado["vozPerfil"] == "minha_voz"


def test_listar_projetos_ordena_do_mais_recente(tmp_path):
    p1 = na.criar_projeto(str(tmp_path), "Primeiro")
    import time
    time.sleep(0.01)
    p2 = na.criar_projeto(str(tmp_path), "Segundo")
    projetos = na.listar_projetos(str(tmp_path))
    assert [p["nome"] for p in projetos] == ["Segundo", "Primeiro"]


def test_listar_projetos_inclui_contagem_de_falas_e_geracoes(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    na.importar_roteiro(str(tmp_path), p["projetoId"], "Fala 1.\nFala 2.")
    projetos = na.listar_projetos(str(tmp_path))
    assert projetos[0]["quantidadeFalas"] == 2
    assert projetos[0]["quantidadeGeracoes"] == 0


def test_excluir_projeto_remove_a_pasta_inteira(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.excluir_projeto(str(tmp_path), pid)
    assert na.projeto_existe(str(tmp_path), pid) is False
    assert na.listar_projetos(str(tmp_path)) == []


def test_excluir_projeto_inexistente_nao_quebra(tmp_path):
    na.excluir_projeto(str(tmp_path), "nunca-existiu")  # não deve levantar nada


# --------------------------------------------------------------------------- #
# Separação de texto bruto em falas
# --------------------------------------------------------------------------- #

def test_separar_texto_bruto_por_linha_ignora_linhas_vazias():
    falas = na.separar_texto_bruto("Fala um.\n\n  Fala dois.  \n\nFala três.", "linha")
    assert falas == ["Fala um.", "Fala dois.", "Fala três."]


def test_separar_texto_bruto_por_frase():
    falas = na.separar_texto_bruto("Fala um. Fala dois! Fala três?", "frase")
    assert falas == ["Fala um.", "Fala dois!", "Fala três?"]


def test_separar_texto_bruto_vazio_devolve_lista_vazia():
    assert na.separar_texto_bruto("   \n  \n  ", "linha") == []
    assert na.separar_texto_bruto("", "linha") == []


# --------------------------------------------------------------------------- #
# Roteiro (falas)
# --------------------------------------------------------------------------- #

def test_importar_roteiro_substitui_falas_existentes(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "A.\nB.")
    roteiro = na.importar_roteiro(str(tmp_path), pid, "C.\nD.\nE.")
    assert [f["texto"] for f in roteiro["falas"]] == ["C.", "D.", "E."]


def test_importar_roteiro_texto_vazio_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    with pytest.raises(na.NarracaoError, match="Cole o texto"):
        na.importar_roteiro(str(tmp_path), p["projetoId"], "   ")


def test_importar_roteiro_projeto_inexistente_da_erro(tmp_path):
    with pytest.raises(na.NarracaoError, match="não encontrado"):
        na.importar_roteiro(str(tmp_path), "nao-existe", "Fala.")


def test_carregar_roteiro_sem_arquivo_devolve_vazio(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    assert na.carregar_roteiro(str(tmp_path), p["projetoId"]) == {"falas": []}


def test_adicionar_fala(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "A.")
    roteiro = na.adicionar_fala(str(tmp_path), pid, "  Nova fala  ")
    assert roteiro["falas"][-1]["texto"] == "Nova fala"
    assert len(roteiro["falas"]) == 2


def test_adicionar_fala_texto_vazio_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    with pytest.raises(na.NarracaoError, match="Digite o texto"):
        na.adicionar_fala(str(tmp_path), p["projetoId"], "   ")


def test_editar_fala(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "A.\nB.\nC.")
    roteiro = na.editar_fala(str(tmp_path), pid, 1, "B editada")
    assert roteiro["falas"][1]["texto"] == "B editada"
    assert roteiro["falas"][0]["texto"] == "A."  # as outras não mudam


def test_editar_fala_indice_invalido_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "A.")
    with pytest.raises(na.NarracaoError, match="não existe"):
        na.editar_fala(str(tmp_path), pid, 5, "texto")


def test_editar_fala_texto_vazio_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "A.")
    with pytest.raises(na.NarracaoError, match="não pode ficar vazio"):
        na.editar_fala(str(tmp_path), pid, 0, "")


def test_remover_fala(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "A.\nB.\nC.")
    roteiro = na.remover_fala(str(tmp_path), pid, 1)
    assert [f["texto"] for f in roteiro["falas"]] == ["A.", "C."]


def test_remover_fala_indice_invalido_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "A.")
    with pytest.raises(na.NarracaoError, match="não existe"):
        na.remover_fala(str(tmp_path), pid, 99)


# --------------------------------------------------------------------------- #
# Limpeza de texto antes do TTS
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("entrada,esperado", [
    ('Ele disse: "incrível!"', "Ele disse: incrível!"),
    ("Isso é... muito bom", "Isso é, muito bom"),
    ("Fim.", "Fim"),  # ponto final vira vírgula, mas vírgula sobrando no FIM da frase é removida
    ("O valor é 3.14 hoje", "O valor é 3.14 hoje"),  # ponto decimal PRESERVADO
    ("Uma frase (com parênteses) aqui", "Uma frase com parênteses aqui"),
    ("Muito!!! Really??", "Muito! Really?"),
    ("  espaços   demais   aqui  ", "espaços demais aqui"),
    (", começa com vírgula", "começa com vírgula"),
])
def test_limpar_texto_para_tts_casos(entrada, esperado):
    assert na.limpar_texto_para_tts(entrada) == esperado


def test_limpar_texto_para_tts_vazio():
    assert na.limpar_texto_para_tts("") == ""
    assert na.limpar_texto_para_tts(None) is None


def test_limpar_texto_preserva_tags_chatterbox_turbo_quando_pedido():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
    texto = 'Ele disse: "olá [chuckle], tudo bem?" (rindo) [dramatic] Isso é sério...'
    limpo = na.limpar_texto_para_tts(texto, preservar_tags_chatterbox_turbo=True)
    assert "[chuckle]" in limpo
    assert "[dramatic]" in limpo
    assert '"' not in limpo  # o resto da limpeza continua normal
    assert "(rindo)" not in limpo  # parênteses não são tag -- continuam removidos


def test_limpar_texto_sem_a_flag_remove_colchetes_normalmente():
    """Comportamento de sempre (Piper/XTTS/Chatterbox/Kokoro) não muda
    -- só quando `preservar_tags_chatterbox_turbo=True` é que os
    colchetes de tags reconhecidas sobrevivem."""
    texto = "Ele disse [chuckle] alguma coisa."
    limpo = na.limpar_texto_para_tts(texto)
    assert "[chuckle]" not in limpo
    assert "chuckle" in limpo  # só os colchetes somem, o texto interno fica (como qualquer parêntese)


def test_limpar_texto_tag_desconhecida_nao_sobrevive_mesmo_com_a_flag():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
    texto = "Isso [naoexiste] deveria sumir igual sempre."
    limpo = na.limpar_texto_para_tts(texto, preservar_tags_chatterbox_turbo=True)
    assert "[naoexiste]" not in limpo
    assert "naoexiste" in limpo


def test_limpar_texto_varias_tags_diferentes_todas_preservadas():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
    texto = "[dramatic] First [gasp] then [whispering] and finally [laugh]"
    limpo = na.limpar_texto_para_tts(texto, preservar_tags_chatterbox_turbo=True)
    for tag in ("[dramatic]", "[gasp]", "[whispering]", "[laugh]"):
        assert tag in limpo


# --------------------------------------------------------------------------- #
# Normalização de volume (usa ffmpeg de verdade)
# --------------------------------------------------------------------------- #

def test_normalizar_volume_wav_produz_arquivo_valido(tmp_path):
    entrada = tmp_path / "entrada.wav"
    saida = tmp_path / "saida.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=1", str(entrada)],
        capture_output=True, check=True,
    )
    na.normalizar_volume_wav(entrada, saida, alvo_lufs=-18.0)
    assert saida.exists() and saida.stat().st_size > 0


# --------------------------------------------------------------------------- #
# Gerações (histórico + exclusão)
# --------------------------------------------------------------------------- #

def test_carregar_geracoes_sem_arquivo_devolve_lista_vazia(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    assert na.carregar_geracoes(str(tmp_path), p["projetoId"]) == []


def test_excluir_geracao_remove_arquivo_e_entrada(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    pasta_geracoes = na.narracoes_dir(str(tmp_path)) / pid / "geracoes"
    pasta_geracoes.mkdir(parents=True)
    (pasta_geracoes / "abc123.mp3").write_bytes(b"fake mp3")
    na._salvar_geracoes(str(tmp_path), pid, [{"id": "abc123", "arquivo": "abc123.mp3"}])

    na.excluir_geracao(str(tmp_path), pid, "abc123")
    assert not (pasta_geracoes / "abc123.mp3").exists()
    assert na.carregar_geracoes(str(tmp_path), pid) == []


def test_excluir_geracao_sanitiza_id_contra_path_traversal(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    # não deve levantar nem tocar em nada fora da pasta de gerações
    na.excluir_geracao(str(tmp_path), pid, "../../../etc/passwd")


# --------------------------------------------------------------------------- #
# _kwargs_motor — tradução da config do projeto pros kwargs de cada motor
# --------------------------------------------------------------------------- #

def test_kwargs_motor_piper():
    projeto = {**na.CONFIG_PADRAO, "motor": "piper", "voz": "pt_BR-faber-medium", "velocidade": 1.2, "usarGpu": True}
    kwargs = na._kwargs_motor(projeto)
    assert kwargs == {"nome_voz": "pt_BR-faber-medium", "velocidade": 1.2, "use_gpu": None}


def test_kwargs_motor_piper_forca_cpu():
    projeto = {**na.CONFIG_PADRAO, "motor": "piper", "usarGpu": False}
    kwargs = na._kwargs_motor(projeto)
    assert kwargs["use_gpu"] is False


def test_kwargs_motor_xtts_com_voz():
    projeto = {**na.CONFIG_PADRAO, "motor": "xtts", "voz": "Ana Florence", "idioma": "pt"}
    kwargs = na._kwargs_motor(projeto)
    assert kwargs == {"idioma": "pt", "use_gpu": None, "speaker": "Ana Florence"}


def test_kwargs_motor_xtts_sem_voz_nao_manda_speaker():
    projeto = {**na.CONFIG_PADRAO, "motor": "xtts", "voz": "", "idioma": "en"}
    kwargs = na._kwargs_motor(projeto)
    assert "speaker" not in kwargs
    assert kwargs["idioma"] == "en"


def test_kwargs_motor_xtts_com_perfil_de_voz():
    projeto = {**na.CONFIG_PADRAO, "motor": "xtts", "vozPerfil": "minha_voz", "idioma": "pt"}
    kwargs = na._kwargs_motor(projeto)
    assert kwargs["voice_profile"] == "minha_voz"
    assert "speaker" not in kwargs


def test_kwargs_motor_xtts_perfil_tem_prioridade_sobre_voz():
    """Se o projeto tem um perfil salvo E uma voz pronta configurados
    (ex: usuário trocou de perfil sem limpar o campo de voz), o perfil
    (clonagem) ganha -- mesmo critério de prioridade que
    xtts_synthesize já usa entre speaker_wav/voice_profile e speaker."""
    projeto = {**na.CONFIG_PADRAO, "motor": "xtts", "vozPerfil": "minha_voz", "voz": "Ana Florence"}
    kwargs = na._kwargs_motor(projeto)
    assert kwargs["voice_profile"] == "minha_voz"
    assert "speaker" not in kwargs


def test_kwargs_motor_xtts_com_checkpoint_conhecido():
    projeto = {**na.CONFIG_PADRAO, "motor": "xtts", "xttsCheckpoint": "hindi", "idioma": "hi"}
    kwargs = na._kwargs_motor(projeto)
    assert kwargs["checkpoint_conhecido"] == "hindi"


def test_kwargs_motor_xtts_checkpoint_padrao_nao_manda_o_kwarg():
    projeto = {**na.CONFIG_PADRAO, "motor": "xtts", "xttsCheckpoint": "padrao"}
    kwargs = na._kwargs_motor(projeto)
    assert "checkpoint_conhecido" not in kwargs


def test_kwargs_motor_xtts_checkpoint_vazio_nao_manda_o_kwarg():
    projeto = {**na.CONFIG_PADRAO, "motor": "xtts", "xttsCheckpoint": ""}
    kwargs = na._kwargs_motor(projeto)
    assert "checkpoint_conhecido" not in kwargs


def test_kwargs_motor_chatterbox_turbo_sem_perfil():
    projeto = {**na.CONFIG_PADRAO, "motor": "chatterbox_turbo", "usarGpu": True}
    kwargs = na._kwargs_motor(projeto)
    assert kwargs == {"use_gpu": None}  # sem idioma/exaggeration/cfg_weight -- o Turbo não aceita nenhum


def test_kwargs_motor_chatterbox_turbo_com_perfil():
    projeto = {**na.CONFIG_PADRAO, "motor": "chatterbox_turbo", "vozPerfil": "minha_voz"}
    kwargs = na._kwargs_motor(projeto)
    assert kwargs["voice_profile"] == "minha_voz"
    assert "idioma" not in kwargs
    assert "exaggeration" not in kwargs
    assert "cfg_weight" not in kwargs


def test_kwargs_motor_chatterbox_turbo_forca_cpu():
    projeto = {**na.CONFIG_PADRAO, "motor": "chatterbox_turbo", "usarGpu": False}
    kwargs = na._kwargs_motor(projeto)
    assert kwargs["use_gpu"] is False


def test_kwargs_motor_kokoro_variante_e_precisao_customizadas():
    projeto = {
        **na.CONFIG_PADRAO, "motor": "kokoro", "voz": "zf_xiaobei",
        "kokoroVariante": "v1.1-zh", "kokoroPrecisao": "int8",
    }
    kwargs = na._kwargs_motor(projeto)
    assert kwargs["variante"] == "v1.1-zh"
    assert kwargs["precisao"] == "int8"


def test_kwargs_motor_kokoro_sem_variante_precisao_usa_padrao():
    """Projeto salvo ANTES desses campos existirem (carregar_projeto já
    faz merge com CONFIG_PADRAO, mas testa aqui o _kwargs_motor
    isoladamente com um dict que não tem as chaves)."""
    projeto = {"motor": "kokoro", "voz": "pf_dora", "velocidade": 1.0, "usarGpu": True}
    kwargs = na._kwargs_motor(projeto)
    assert kwargs["variante"] == "v1.0"
    assert kwargs["precisao"] == "fp32"


def test_kwargs_motor_kokoro():
    projeto = {**na.CONFIG_PADRAO, "motor": "kokoro", "voz": "pf_dora", "velocidade": 0.9, "idioma": ""}
    kwargs = na._kwargs_motor(projeto)
    assert kwargs == {
        "voz": "pf_dora", "velocidade": 0.9, "idioma": None,
        "variante": "v1.0", "precisao": "fp32",
    }


# --------------------------------------------------------------------------- #
# gerar_audio_projeto — pipeline completo (motor mockado, ffmpeg de verdade)
# --------------------------------------------------------------------------- #

def _instala_motor_falso(monkeypatch_dur_por_char=0.03):
    """Substitui `tts.voice_generator.gerar_audio` por uma versão que
    gera um tom puro (via ffmpeg) do tamanho proporcional ao texto, em
    vez de chamar Piper/XTTS/Kokoro de verdade. Devolve uma função de
    'desfazer' pra restaurar o original depois.
    """
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
    import tts.voice_generator as vg_mod

    chamadas = []

    def fake_gerar_audio(engine, texto, output_path, **kwargs):
        chamadas.append({"engine": engine, "texto": texto, "kwargs": kwargs})
        dur = 0.4 + monkeypatch_dur_por_char * len(texto)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=300:duration={dur:.2f}",
             "-ar", "22050", "-ac", "1", output_path],
            capture_output=True, check=True,
        )
        return output_path

    original = vg_mod.gerar_audio
    vg_mod.gerar_audio = fake_gerar_audio

    def desfazer():
        vg_mod.gerar_audio = original

    return chamadas, desfazer


def test_gerar_audio_projeto_pipeline_completo(tmp_path):
    chamadas, desfazer = _instala_motor_falso()
    try:
        p = na.criar_projeto(str(tmp_path), "Projeto completo")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, "Primeira fala.\nSegunda fala.\nTerceira fala.")
        na.salvar_config(str(tmp_path), pid, motor="piper", pausa_segundos=0.2)

        logs = []
        resultado = na.gerar_audio_projeto(str(tmp_path), pid, on_log=logs.append)

        assert len(chamadas) == 3  # uma chamada de TTS por fala
        assert resultado["quantidadeFalas"] == 3
        assert resultado["motor"] == "piper"
        assert resultado["duracaoSegundos"] and resultado["duracaoSegundos"] > 1.0

        arquivo = na.narracoes_dir(str(tmp_path)) / pid / "geracoes" / f"{resultado['id']}.mp3"
        assert arquivo.exists() and arquivo.stat().st_size > 0

        geracoes = na.carregar_geracoes(str(tmp_path), pid)
        assert len(geracoes) == 1 and geracoes[0]["id"] == resultado["id"]

        assert any("Pronto!" in linha for linha in logs)

        # a pasta temporária de trabalho não deve sobrar depois
        assert not (na.narracoes_dir(str(tmp_path)) / pid / "_tmp_gerar_audio").exists()
    finally:
        desfazer()


def test_gerar_audio_projeto_chatterbox_turbo_preserva_tags_no_texto_mandado_ao_motor(tmp_path):
    """Ponta a ponta: um projeto com motor chatterbox_turbo e uma fala
    com tag paralinguística precisa chegar no motor de voz com a tag
    INTACTA (colchetes incluídos) -- outros motores perderiam os
    colchetes na limpeza normal do texto."""
    chamadas, desfazer = _instala_motor_falso()
    try:
        p = na.criar_projeto(str(tmp_path), "Projeto com tags")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, 'Hi there [chuckle], welcome back!\nThis is serious [dramatic] stuff.')
        na.salvar_config(str(tmp_path), pid, motor="chatterbox_turbo")

        na.gerar_audio_projeto(str(tmp_path), pid)

        assert len(chamadas) == 2
        assert "[chuckle]" in chamadas[0]["texto"]
        assert "[dramatic]" in chamadas[1]["texto"]
        assert all(c["engine"] == "chatterbox_turbo" for c in chamadas)
    finally:
        desfazer()


def test_gerar_audio_projeto_sem_roteiro_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "Sem roteiro")
    with pytest.raises(na.NarracaoError, match="nenhuma fala"):
        na.gerar_audio_projeto(str(tmp_path), p["projetoId"])


def test_gerar_audio_projeto_falas_so_com_texto_vazio_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.adicionar_fala(str(tmp_path), pid, "temporaria")
    # zera o texto direto no arquivo (adicionar_fala não permite texto vazio)
    roteiro = na.carregar_roteiro(str(tmp_path), pid)
    roteiro["falas"][0]["texto"] = "   "
    na._salvar_roteiro(str(tmp_path), pid, roteiro)
    with pytest.raises(na.NarracaoError, match="Nenhuma fala"):
        na.gerar_audio_projeto(str(tmp_path), pid)


def test_gerar_audio_projeto_propaga_erro_do_motor(tmp_path):
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
    import tts.voice_generator as vg_mod

    def fake_gerar_audio_com_erro(engine, texto, output_path, **kwargs):
        raise vg_mod.VoiceGeneratorError("motor de teste falhou de propósito")

    original = vg_mod.gerar_audio
    vg_mod.gerar_audio = fake_gerar_audio_com_erro
    try:
        p = na.criar_projeto(str(tmp_path), "X")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, "Fala que vai falhar.")
        with pytest.raises(na.NarracaoError, match="motor de teste falhou"):
            na.gerar_audio_projeto(str(tmp_path), pid)
        # a pasta temporária é limpa mesmo quando dá erro
        assert not (na.narracoes_dir(str(tmp_path)) / pid / "_tmp_gerar_audio").exists()
    finally:
        vg_mod.gerar_audio = original


def test_gerar_audio_projeto_pula_falas_sem_texto(tmp_path):
    chamadas, desfazer = _instala_motor_falso()
    try:
        p = na.criar_projeto(str(tmp_path), "X")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, "Fala válida.")
        # injeta uma fala com texto vazio direto no roteiro (não dá pra
        # fazer isso via adicionar_fala, que valida) -- confirma que o
        # pipeline pula ela sem quebrar, em vez de mandar pro TTS.
        roteiro = na.carregar_roteiro(str(tmp_path), pid)
        roteiro["falas"].append({"texto": ""})
        roteiro["falas"].append({"texto": "Outra fala válida."})
        na._salvar_roteiro(str(tmp_path), pid, roteiro)

        resultado = na.gerar_audio_projeto(str(tmp_path), pid)
        assert resultado["quantidadeFalas"] == 2  # só as 2 com texto de verdade
        assert len(chamadas) == 2
    finally:
        desfazer()


def test_gerar_audio_projeto_sem_pausa_entre_falas(tmp_path):
    chamadas, desfazer = _instala_motor_falso()
    try:
        p = na.criar_projeto(str(tmp_path), "X")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, "A.\nB.")
        na.salvar_config(str(tmp_path), pid, pausa_segundos=0.0)
        resultado = na.gerar_audio_projeto(str(tmp_path), pid)
        assert resultado["quantidadeFalas"] == 2
    finally:
        desfazer()


# --------------------------------------------------------------------------- #
# Gravações da própria voz por fala (múltiplos takes, seleção, uso
# opcional, integração com o pipeline de geração)
# --------------------------------------------------------------------------- #

def _gera_gravacao_bruta(caminho, duracao=3):
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=300:duration={duracao}", str(caminho)],
        capture_output=True, check=True,
    )


def test_salvar_gravacao_cria_take_e_marca_uso(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala um.\nFala dois.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)

    resultado = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    assert resultado["usar"] is True
    assert resultado["duracaoSegundos"] > 2.5
    assert resultado["takeId"]


def test_salvar_gravacao_fala_inexistente_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Só uma fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    with pytest.raises(na.NarracaoError, match="não existe"):
        na.salvar_gravacao(str(tmp_path), pid, 99, str(bruta))


def test_salvar_gravacao_projeto_inexistente_da_erro(tmp_path):
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    with pytest.raises(na.NarracaoError, match="não encontrado"):
        na.salvar_gravacao(str(tmp_path), "nao-existe", 0, str(bruta))


def test_salvar_gravacao_arquivo_de_origem_inexistente_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    with pytest.raises(na.NarracaoError, match="não encontrado"):
        na.salvar_gravacao(str(tmp_path), pid, 0, str(tmp_path / "nao-existe.webm"))


def test_listar_gravacoes_projeto_sem_gravacao_nenhuma(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    assert na.listar_gravacoes(str(tmp_path), pid) == {}


def test_gravar_varios_takes_o_mais_recente_fica_ativo(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)

    r1 = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    r2 = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))

    gravacoes = na.listar_gravacoes(str(tmp_path), pid)
    assert len(gravacoes["0"]["takes"]) == 2
    assert gravacoes["0"]["takeAtivo"] == r2["takeId"]
    assert r1["takeId"] != r2["takeId"]


def test_selecionar_take_troca_o_ativo(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    r1 = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    r2 = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))

    na.selecionar_take(str(tmp_path), pid, 0, r1["takeId"])
    assert na.listar_gravacoes(str(tmp_path), pid)["0"]["takeAtivo"] == r1["takeId"]


def test_selecionar_take_inexistente_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    with pytest.raises(na.NarracaoError, match="não existe"):
        na.selecionar_take(str(tmp_path), pid, 0, "id-invalido")


def test_selecionar_take_fala_sem_gravacao_nenhuma_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    with pytest.raises(na.NarracaoError, match="não tem gravações"):
        na.selecionar_take(str(tmp_path), pid, 0, "qualquer")


def test_marcar_uso_gravacao_liga_e_desliga(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))

    na.marcar_uso_gravacao(str(tmp_path), pid, 0, False)
    assert na.listar_gravacoes(str(tmp_path), pid)["0"]["usar"] is False
    na.marcar_uso_gravacao(str(tmp_path), pid, 0, True)
    assert na.listar_gravacoes(str(tmp_path), pid)["0"]["usar"] is True


def test_marcar_uso_gravacao_fala_sem_entrada_ainda_nao_quebra(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    entrada = na.marcar_uso_gravacao(str(tmp_path), pid, 0, True)
    assert entrada["usar"] is True
    assert entrada["takes"] == []


def test_excluir_take_remove_o_arquivo_e_a_entrada(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    caminho = na.caminho_take(str(tmp_path), pid, 0, r["takeId"])
    assert caminho.exists()

    na.excluir_take(str(tmp_path), pid, 0, r["takeId"])
    assert not caminho.exists()
    assert na.listar_gravacoes(str(tmp_path), pid)["0"]["takes"] == []


def test_excluir_take_ativo_promove_outro_take_restante(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    r1 = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    r2 = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))  # r2 fica ativo

    na.excluir_take(str(tmp_path), pid, 0, r2["takeId"])
    gravacoes = na.listar_gravacoes(str(tmp_path), pid)
    assert gravacoes["0"]["takeAtivo"] == r1["takeId"]
    assert gravacoes["0"]["usar"] is True  # ainda sobrou um take -- continua ligado


def test_excluir_ultimo_take_desliga_uso_automaticamente(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))

    na.excluir_take(str(tmp_path), pid, 0, r["takeId"])
    gravacoes = na.listar_gravacoes(str(tmp_path), pid)
    assert gravacoes["0"]["takeAtivo"] is None
    assert gravacoes["0"]["usar"] is False


def test_excluir_take_de_fala_sem_gravacao_nao_quebra(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.excluir_take(str(tmp_path), pid, 0, "qualquer-id")  # não deve levantar nada


def test_caminho_take_inexistente_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    with pytest.raises(na.NarracaoError, match="não foi encontrado"):
        na.caminho_take(str(tmp_path), pid, 0, "nao-existe")


def test_caminho_take_sanitiza_id_contra_path_traversal(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    with pytest.raises(na.NarracaoError, match="não foi encontrado"):
        na.caminho_take(str(tmp_path), pid, 0, "../../../etc/passwd")


def test_caminho_take_ativo_sem_gravacao_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    with pytest.raises(na.NarracaoError, match="não tem uma gravação ativa"):
        na.caminho_take_ativo(str(tmp_path), pid, 0)


def test_caminho_take_ativo_funciona(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    caminho = na.caminho_take_ativo(str(tmp_path), pid, 0)
    assert caminho == na.caminho_take(str(tmp_path), pid, 0, r["takeId"])


# --------------------------------------------------------------------------- #
# Integração da gravação própria com o pipeline de geração (mistura
# falas geradas por TTS com falas usando a gravação do usuário)
# --------------------------------------------------------------------------- #

def test_gerar_audio_projeto_usa_gravacao_propria_quando_marcada(tmp_path):
    chamadas, desfazer = _instala_motor_falso()
    try:
        p = na.criar_projeto(str(tmp_path), "Pipeline misto")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, "Fala por IA.\nFala com minha voz.\nOutra fala por IA.")

        bruta = tmp_path / "bruta.wav"
        _gera_gravacao_bruta(bruta, duracao=2.5)
        na.salvar_gravacao(str(tmp_path), pid, 1, str(bruta))  # fala do meio usa gravação própria

        logs = []
        resultado = na.gerar_audio_projeto(str(tmp_path), pid, on_log=logs.append)

        assert len(chamadas) == 2  # só as 2 falas SEM gravação chamaram o TTS
        assert not any("minha voz" in c["texto"].lower() for c in chamadas)
        assert resultado["quantidadeFalas"] == 3
        assert any("gravação própria" in linha for linha in logs)

        arquivo = na.narracoes_dir(str(tmp_path)) / pid / "geracoes" / f"{resultado['id']}.mp3"
        assert arquivo.exists() and arquivo.stat().st_size > 0
    finally:
        desfazer()


def test_gerar_audio_projeto_todas_as_falas_com_gravacao_propria(tmp_path):
    chamadas, desfazer = _instala_motor_falso()
    try:
        p = na.criar_projeto(str(tmp_path), "Só gravação")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, "Fala um.\nFala dois.")

        bruta = tmp_path / "bruta.wav"
        _gera_gravacao_bruta(bruta, duracao=2)
        na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
        na.salvar_gravacao(str(tmp_path), pid, 1, str(bruta))

        resultado = na.gerar_audio_projeto(str(tmp_path), pid)
        assert len(chamadas) == 0  # TTS nunca foi chamado
        assert resultado["quantidadeFalas"] == 2
    finally:
        desfazer()


def test_gerar_audio_projeto_gravacao_desligada_usa_tts_mesmo_assim(tmp_path):
    chamadas, desfazer = _instala_motor_falso()
    try:
        p = na.criar_projeto(str(tmp_path), "X")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, "Fala com gravação desligada.")

        bruta = tmp_path / "bruta.wav"
        _gera_gravacao_bruta(bruta, duracao=2)
        na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
        na.marcar_uso_gravacao(str(tmp_path), pid, 0, False)  # grava mas desliga o uso

        na.gerar_audio_projeto(str(tmp_path), pid)
        assert len(chamadas) == 1  # caiu pro TTS mesmo tendo uma gravação salva
    finally:
        desfazer()


def test_gerar_audio_projeto_take_ativo_apagado_da_erro_claro(tmp_path):
    """Se o take marcado como ativo foi apagado do disco por fora (ou o
    config ficou inconsistente), o erro tem que ser claro, apontando a
    fala, em vez de uma exceção genérica de arquivo não encontrado."""
    chamadas, desfazer = _instala_motor_falso()
    try:
        p = na.criar_projeto(str(tmp_path), "X")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, "Fala.")
        bruta = tmp_path / "bruta.wav"
        _gera_gravacao_bruta(bruta, duracao=2)
        r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
        na.caminho_take(str(tmp_path), pid, 0, r["takeId"]).unlink()  # apaga o arquivo por fora

        with pytest.raises(na.NarracaoError, match="Falha na fala 1"):
            na.gerar_audio_projeto(str(tmp_path), pid)
    finally:
        desfazer()


# --------------------------------------------------------------------------- #
# Realce de áudio ("audio enhance") de um take gravado — portado do
# recurso "Minha Voz" do shortmaker (gerar_realce_de_take/
# usar_realce_de_take/caminho_take_realce), com ffmpeg de verdade.
# --------------------------------------------------------------------------- #

def test_gerar_realce_de_take_cria_arquivo_e_marca_uso(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))

    resultado = na.gerar_realce_de_take(str(tmp_path), pid, 0, r["takeId"])
    assert resultado["enhancedGerado"] is True
    assert resultado["usarEnhance"] is True

    caminho_realce = na.caminho_take_realce(str(tmp_path), pid, 0, r["takeId"])
    assert caminho_realce.exists() and caminho_realce.stat().st_size > 0
    # o original continua intacto e separado
    assert caminho_realce != na.caminho_take(str(tmp_path), pid, 0, r["takeId"])


def test_gerar_realce_sem_marcar_uso(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))

    resultado = na.gerar_realce_de_take(str(tmp_path), pid, 0, r["takeId"], marcar_como_usar=False)
    assert resultado["enhancedGerado"] is True
    assert resultado["usarEnhance"] is False
    # gerado mas não em uso -- caminho_take_ativo continua no original
    assert na.caminho_take_ativo(str(tmp_path), pid, 0) == na.caminho_take(str(tmp_path), pid, 0, r["takeId"])


def test_gerar_realce_take_inexistente_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    with pytest.raises(na.NarracaoError, match="não foi encontrado"):
        na.gerar_realce_de_take(str(tmp_path), pid, 0, "nao-existe")


def test_caminho_take_realce_antes_de_gerar_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    with pytest.raises(na.NarracaoError, match="ainda não foi gerado"):
        na.caminho_take_realce(str(tmp_path), pid, 0, r["takeId"])


def test_usar_realce_de_take_liga_e_desliga(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    na.gerar_realce_de_take(str(tmp_path), pid, 0, r["takeId"])

    na.usar_realce_de_take(str(tmp_path), pid, 0, r["takeId"], False)
    assert na.caminho_take_ativo(str(tmp_path), pid, 0) == na.caminho_take(str(tmp_path), pid, 0, r["takeId"])

    na.usar_realce_de_take(str(tmp_path), pid, 0, r["takeId"], True)
    assert na.caminho_take_ativo(str(tmp_path), pid, 0) == na.caminho_take_realce(str(tmp_path), pid, 0, r["takeId"])


def test_usar_realce_sem_ter_gerado_antes_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    with pytest.raises(na.NarracaoError, match="Gere o realce"):
        na.usar_realce_de_take(str(tmp_path), pid, 0, r["takeId"], True)


def test_usar_realce_take_inexistente_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    with pytest.raises(na.NarracaoError, match="não existe"):
        na.usar_realce_de_take(str(tmp_path), pid, 0, "nao-existe", True)


def test_usar_realce_fala_sem_gravacao_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    with pytest.raises(na.NarracaoError, match="não tem gravações"):
        na.usar_realce_de_take(str(tmp_path), pid, 0, "qualquer", True)


def test_excluir_take_remove_tambem_o_arquivo_de_realce(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    na.gerar_realce_de_take(str(tmp_path), pid, 0, r["takeId"])
    caminho_realce = na.caminho_take_realce(str(tmp_path), pid, 0, r["takeId"])
    assert caminho_realce.exists()

    na.excluir_take(str(tmp_path), pid, 0, r["takeId"])
    assert not caminho_realce.exists()


def test_caminho_take_ativo_com_realce_apagado_por_fora_cai_pro_original(tmp_path):
    """Se o config ainda diz 'usarEnhance: true' mas o arquivo de realce
    sumiu do disco por algum motivo externo, não deve quebrar -- cai
    pro original em vez de levantar exceção."""
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    na.gerar_realce_de_take(str(tmp_path), pid, 0, r["takeId"])
    na.caminho_take_realce(str(tmp_path), pid, 0, r["takeId"]).unlink()  # apaga por fora

    caminho = na.caminho_take_ativo(str(tmp_path), pid, 0)
    assert caminho == na.caminho_take(str(tmp_path), pid, 0, r["takeId"])


def test_gerar_audio_projeto_usa_versao_com_realce_quando_ativa(tmp_path):
    """Ponta a ponta: o pipeline de geração usa a versão COM REALCE do
    take ativo (não a gravação crua) quando ela está marcada em uso."""
    chamadas, desfazer = _instala_motor_falso()
    try:
        p = na.criar_projeto(str(tmp_path), "X")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, "Fala com realce.")
        bruta = tmp_path / "bruta.wav"
        _gera_gravacao_bruta(bruta, duracao=2)
        r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
        na.gerar_realce_de_take(str(tmp_path), pid, 0, r["takeId"])

        resultado = na.gerar_audio_projeto(str(tmp_path), pid)
        assert len(chamadas) == 0  # não chamou TTS -- usou a gravação (com realce)
        assert resultado["quantidadeFalas"] == 1
    finally:
        desfazer()


# --------------------------------------------------------------------------- #
# Corte (trim) de um take gravado — tira silêncio/ruído do começo ou do
# fim da gravação. Sempre corta a partir do áudio ORIGINAL intacto
# (nunca de um corte anterior), então cortar de novo com limites
# diferentes não perde qualidade nem acumula erro.
# --------------------------------------------------------------------------- #

def test_recortar_take_corta_pro_intervalo_certo(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta, duracao=10)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))

    resultado = na.recortar_take(str(tmp_path), pid, 0, r["takeId"], 2.0, 6.0)
    assert abs(resultado["duracaoSegundos"] - 4.0) < 0.2
    assert resultado["duracaoOriginalSegundos"] == 10.0
    assert resultado["recortado"] is True

    caminho = na.caminho_take(str(tmp_path), pid, 0, r["takeId"])
    dur_real = na._duracao_audio(caminho)
    assert abs(dur_real - 4.0) < 0.2


def test_recortar_take_de_novo_parte_do_original_nao_do_corte_anterior(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta, duracao=10)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))

    na.recortar_take(str(tmp_path), pid, 0, r["takeId"], 2.0, 4.0)  # 2s
    resultado2 = na.recortar_take(str(tmp_path), pid, 0, r["takeId"], 0.0, 8.0)  # pede 8s do ORIGINAL
    assert abs(resultado2["duracaoSegundos"] - 8.0) < 0.2  # se partisse do corte anterior (2s), não conseguiria 8s


def test_recortar_take_fim_antes_do_inicio_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta, duracao=5)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    with pytest.raises(na.NarracaoError, match="depois do início"):
        na.recortar_take(str(tmp_path), pid, 0, r["takeId"], 4.0, 2.0)


def test_recortar_take_inicio_negativo_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta, duracao=5)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    with pytest.raises(na.NarracaoError, match="negativo"):
        na.recortar_take(str(tmp_path), pid, 0, r["takeId"], -1.0, 2.0)


def test_recortar_take_inicio_alem_da_duracao_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta, duracao=5)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    with pytest.raises(na.NarracaoError, match="precisa ser menor"):
        na.recortar_take(str(tmp_path), pid, 0, r["takeId"], 50.0, 60.0)


def test_recortar_take_inexistente_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    with pytest.raises(na.NarracaoError, match="não foi encontrado"):
        na.recortar_take(str(tmp_path), pid, 0, "nao-existe", 0.0, 2.0)


def test_desfazer_recorte_restaura_duracao_original(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta, duracao=10)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    na.recortar_take(str(tmp_path), pid, 0, r["takeId"], 2.0, 5.0)

    resultado = na.desfazer_recorte_take(str(tmp_path), pid, 0, r["takeId"])
    assert abs(resultado["duracaoSegundos"] - 10.0) < 0.2
    assert resultado["recortado"] is False


def test_desfazer_recorte_sem_corte_nenhum_da_erro(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    with pytest.raises(na.NarracaoError, match="nenhum corte"):
        na.desfazer_recorte_take(str(tmp_path), pid, 0, r["takeId"])


def test_recortar_take_invalida_realce_existente(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta, duracao=10)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    na.gerar_realce_de_take(str(tmp_path), pid, 0, r["takeId"])
    assert na.caminho_take_realce(str(tmp_path), pid, 0, r["takeId"]).exists()

    na.recortar_take(str(tmp_path), pid, 0, r["takeId"], 1.0, 5.0)

    with pytest.raises(na.NarracaoError, match="ainda não foi gerado"):
        na.caminho_take_realce(str(tmp_path), pid, 0, r["takeId"])
    gravacoes = na.listar_gravacoes(str(tmp_path), pid)
    take = gravacoes["0"]["takes"][0]
    assert take["enhancedGerado"] is False
    assert take["usarEnhance"] is False


def test_desfazer_recorte_tambem_invalida_realce(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta, duracao=10)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    na.recortar_take(str(tmp_path), pid, 0, r["takeId"], 1.0, 5.0)
    na.gerar_realce_de_take(str(tmp_path), pid, 0, r["takeId"])

    na.desfazer_recorte_take(str(tmp_path), pid, 0, r["takeId"])
    with pytest.raises(na.NarracaoError, match="ainda não foi gerado"):
        na.caminho_take_realce(str(tmp_path), pid, 0, r["takeId"])


def test_excluir_take_remove_tambem_o_backup_raw(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    na.importar_roteiro(str(tmp_path), pid, "Fala.")
    bruta = tmp_path / "bruta.wav"
    _gera_gravacao_bruta(bruta, duracao=10)
    r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
    na.recortar_take(str(tmp_path), pid, 0, r["takeId"], 1.0, 5.0)
    take_id_seguro = r["takeId"]
    caminho_raw = na._caminho_take_raw(str(tmp_path), pid, 0, take_id_seguro)
    assert caminho_raw.exists()

    na.excluir_take(str(tmp_path), pid, 0, r["takeId"])
    assert not caminho_raw.exists()


def test_gerar_audio_projeto_usa_take_recortado(tmp_path):
    """Ponta a ponta: o pipeline usa a duração CORTADA do take, não a
    original."""
    chamadas, desfazer = _instala_motor_falso()
    try:
        p = na.criar_projeto(str(tmp_path), "X")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, "Fala cortada.")
        bruta = tmp_path / "bruta.wav"
        _gera_gravacao_bruta(bruta, duracao=10)
        r = na.salvar_gravacao(str(tmp_path), pid, 0, str(bruta))
        na.recortar_take(str(tmp_path), pid, 0, r["takeId"], 2.0, 5.0)  # 3s

        resultado = na.gerar_audio_projeto(str(tmp_path), pid)
        assert len(chamadas) == 0
        # 3s da fala cortada -- bem menos que os 10s originais que teria
        # sem o corte (o teste confirma indiretamente que usou o
        # ARQUIVO CORTADO, não o original de 10s)
        assert resultado["duracaoSegundos"] < 8.0
    finally:
        desfazer()


# --------------------------------------------------------------------------- #
# Corte automático de silêncio das pontas das gravações, aplicado no
# pipeline de geração (não modifica o take salvo — só o áudio final)
# --------------------------------------------------------------------------- #

def _gera_gravacao_com_silencio_nas_pontas(caminho, silencio_inicio=1.0, tom=2.0, silencio_fim=1.0):
    import subprocess
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono:d={silencio_inicio}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={tom}:sample_rate=24000",
        "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono:d={silencio_fim}",
        "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1[out]",
        "-map", "[out]", str(caminho),
    ], capture_output=True, check=True)


def test_cortar_silencio_gravacoes_ligado_por_padrao():
    assert na.CONFIG_PADRAO["cortarSilencioGravacoes"] is True


def test_salvar_config_cortar_silencio_gravacoes(tmp_path):
    p = na.criar_projeto(str(tmp_path), "X")
    pid = p["projetoId"]
    atualizado = na.salvar_config(str(tmp_path), pid, cortar_silencio_gravacoes=False)
    assert atualizado["cortarSilencioGravacoes"] is False

    recarregado = na.carregar_projeto(str(tmp_path), pid)
    assert recarregado["cortarSilencioGravacoes"] is False


def test_gerar_audio_projeto_corta_silencio_das_pontas_por_padrao(tmp_path):
    """Ponta a ponta: com a config padrão (ligada), o áudio final fica
    bem mais curto que a gravação bruta com silêncio nas pontas."""
    chamadas, desfazer = _instala_motor_falso()
    try:
        p = na.criar_projeto(str(tmp_path), "X")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, "Fala gravada.")
        gravacao = tmp_path / "gravacao.wav"
        _gera_gravacao_com_silencio_nas_pontas(gravacao, silencio_inicio=1.0, tom=2.0, silencio_fim=1.0)
        na.salvar_gravacao(str(tmp_path), pid, 0, str(gravacao))

        resultado = na.gerar_audio_projeto(str(tmp_path), pid)
        assert resultado["duracaoSegundos"] < 3.0  # bem menos que os 4s da gravação bruta
    finally:
        desfazer()


def test_gerar_audio_projeto_sem_cortar_silencio_quando_desligado(tmp_path):
    chamadas, desfazer = _instala_motor_falso()
    try:
        p = na.criar_projeto(str(tmp_path), "X")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, "Fala gravada.")
        gravacao = tmp_path / "gravacao.wav"
        _gera_gravacao_com_silencio_nas_pontas(gravacao, silencio_inicio=1.0, tom=2.0, silencio_fim=1.0)
        na.salvar_gravacao(str(tmp_path), pid, 0, str(gravacao))
        na.salvar_config(str(tmp_path), pid, cortar_silencio_gravacoes=False)

        resultado = na.gerar_audio_projeto(str(tmp_path), pid)
        assert resultado["duracaoSegundos"] > 3.5  # os ~4s originais continuam (nada cortado)
    finally:
        desfazer()


def test_gerar_audio_projeto_corte_de_silencio_nao_mexe_no_take_salvo(tmp_path):
    """O corte automático é aplicado só no áudio FINAL -- o take
    salvo (que aparece nos players da interface) continua com a
    duração original, sem cortar nada."""
    chamadas, desfazer = _instala_motor_falso()
    try:
        p = na.criar_projeto(str(tmp_path), "X")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, "Fala gravada.")
        gravacao = tmp_path / "gravacao.wav"
        _gera_gravacao_com_silencio_nas_pontas(gravacao, silencio_inicio=1.0, tom=2.0, silencio_fim=1.0)
        r = na.salvar_gravacao(str(tmp_path), pid, 0, str(gravacao))

        na.gerar_audio_projeto(str(tmp_path), pid)

        caminho_take = na.caminho_take(str(tmp_path), pid, 0, r["takeId"])
        dur_take = na._duracao_audio(caminho_take)
        assert dur_take > 3.5  # o take em si continua intacto (4s), só o áudio final foi cortado
    finally:
        desfazer()
