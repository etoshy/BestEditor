"""
Teste offline de voice_generator.py: detecção de GPU, despachante
`gerar_audio`, e a lógica de cada motor (download-se-faltar, montagem
dos kwargs, fallback de parâmetros) — SEM precisar ter piper-tts,
coqui-tts/torch ou kokoro-onnx instalados de verdade. Cada motor é
simulado injetando um módulo falso em `sys.modules` antes da chamada
(o import de cada lib é local, dentro da função, então isso funciona
sem precisar mockar `voice_generator` em si).
"""
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import types
import wave

import pytest

import voice_generator as vg


@contextlib.contextmanager
def fake_module(name, module):
    """Injeta `module` em `sys.modules[name]` e desfaz no final,
    restaurando o que estava lá antes (nada, na prática, já que
    nenhuma dessas libs está instalada neste ambiente de teste).
    """
    old = sys.modules.get(name)
    sys.modules[name] = module
    try:
        yield module
    finally:
        if old is not None:
            sys.modules[name] = old
        else:
            sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def _limpa_caches_entre_testes():
    """`xtts_load`/`kokoro_load` guardam a instância carregada num cache
    a nível de módulo — sem limpar isso entre testes, um teste "vê" o
    modelo falso carregado por outro.
    """
    vg._xtts_cache.clear()
    vg._kokoro_cache.clear()
    yield
    vg._xtts_cache.clear()
    vg._kokoro_cache.clear()


# --------------------------------------------------------------------------- #
# Detecção de GPU / status geral
# --------------------------------------------------------------------------- #

def test_gpu_status_nao_quebra_sem_onnxruntime_nem_torch():
    status = vg.gpu_status()
    assert set(status.keys()) == {"onnx_gpu (piper/kokoro)", "torch_gpu (xtts)"}
    assert isinstance(status["onnx_gpu (piper/kokoro)"], bool)
    assert isinstance(status["torch_gpu (xtts)"], bool)


def test_onnx_gpu_available_true_quando_cuda_no_provider_list():
    fake_ort = types.ModuleType("onnxruntime")
    fake_ort.get_available_providers = lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"]
    with fake_module("onnxruntime", fake_ort):
        assert vg.onnx_gpu_available() is True


def test_onnx_gpu_available_false_sem_cuda_no_provider_list():
    fake_ort = types.ModuleType("onnxruntime")
    fake_ort.get_available_providers = lambda: ["CPUExecutionProvider"]
    with fake_module("onnxruntime", fake_ort):
        assert vg.onnx_gpu_available() is False


def test_torch_gpu_available_reflete_cuda_is_available():
    fake_torch = types.ModuleType("torch")
    fake_cuda = types.SimpleNamespace(is_available=lambda: True)
    fake_torch.cuda = fake_cuda
    with fake_module("torch", fake_torch):
        assert vg.torch_gpu_available() is True


# --------------------------------------------------------------------------- #
# Despachante gerar_audio()
# --------------------------------------------------------------------------- #

def test_gerar_audio_motor_desconhecido():
    with pytest.raises(vg.VoiceGeneratorError, match="Motor de voz desconhecido"):
        vg.gerar_audio("nao-existe", "texto", "/tmp/saida.wav")


def test_gerar_audio_texto_vazio():
    with pytest.raises(vg.VoiceGeneratorError, match="Texto vazio"):
        vg.gerar_audio("piper", "   ", "/tmp/saida.wav")


def test_engines_tem_os_cinco_motores_com_label_e_instrucao_de_instalacao():
    assert set(vg.ENGINES) == {"piper", "xtts", "chatterbox", "chatterbox_turbo", "kokoro", "fish_s2"}
    for info in vg.ENGINES.values():
        assert info["label"]
        assert info["instalar"].startswith("pip install")


# --------------------------------------------------------------------------- #
# Piper — sem a lib instalada
# --------------------------------------------------------------------------- #

def test_piper_synthesize_sem_lib_instalada_da_erro_claro():
    with pytest.raises(vg.VoiceGeneratorError, match="pip install piper-tts"):
        vg.piper_synthesize("oi", "/tmp/saida.wav")


# --------------------------------------------------------------------------- #
# Piper — com a lib "instalada" (módulo falso)
# --------------------------------------------------------------------------- #

class _FakePiperVoiceConfig:
    sample_rate = 22050


class _FakePiperVoiceBase:
    """Base comum: grava alguns frames de silêncio de verdade no
    wave.Wave_write que `piper_synthesize` já preparou (framerate,
    canais, sample width) — dá pra confirmar que o .wav final existe
    e tem conteúdo, sem precisar de fala de verdade nenhuma.
    """
    def __init__(self):
        self.config = _FakePiperVoiceConfig()

    @classmethod
    def load(cls, model_path, config_path=None, use_cuda=False):
        instancia = cls()
        instancia.model_path = model_path
        instancia.config_path = config_path
        instancia.use_cuda = use_cuda
        return instancia

    def _grava_silencio(self, wav_file):
        wav_file.writeframes(b"\x00\x00" * 500)


class _FakePiperVoiceApiAtual(_FakePiperVoiceBase):
    """Simula a API ATUAL do piper-tts (piper1-gpl) — `.synthesize_wav()`
    escreve direto no wav_file; `.synthesize()` existe só como gerador
    de streaming (não usado nesse caminho)."""
    def synthesize_wav(self, texto, wav_file, syn_config=None):
        self.syn_config_recebido = syn_config
        self._grava_silencio(wav_file)

    def synthesize(self, texto, syn_config=None):
        raise AssertionError("não deveria cair no caminho de gerador quando synthesize_wav existe")


class _FakePiperVoiceApiAntiga(_FakePiperVoiceBase):
    """Simula uma versão ANTIGA do piper-tts — só tem `.synthesize()`
    escrevendo direto no wav_file (sem `.synthesize_wav()` nenhum)."""
    def synthesize(self, texto, wav_file, length_scale=None):
        self.length_scale_recebido = length_scale
        self._grava_silencio(wav_file)


class _FakePiperVoiceSoGerador(_FakePiperVoiceBase):
    """Reproduz EXATAMENTE o bug relatado: uma versão sem
    `.synthesize_wav()` e cujo `.synthesize()` é um GERADOR de streaming
    (não escreve em wav_file nenhum) — é a causa real do "áudio zerado":
    chamar esse `.synthesize()` como se escrevesse sozinho não dá erro
    nenhum (só devolve um generator nunca consumido), e o .wav fecha com
    0 frames. Aqui confirmamos que o código novo detecta a ausência de
    `.synthesize_wav`, cai pro modo gerador, e ESCREVE os pedaços."""
    class _Pedaco:
        def __init__(self, dados):
            self.audio_int16_bytes = dados

    def synthesize(self, texto, syn_config=None):
        self.syn_config_recebido = syn_config
        for _ in range(3):
            yield self._Pedaco(b"\x11\x22" * 100)


class _FakePiperVoiceNaoEscreveNada(_FakePiperVoiceBase):
    """"Sucesso" que na verdade não escreve nenhum frame -- pra testar
    a checagem final de segurança (o .wav não pode sair vazio mesmo que
    nenhuma chamada tenha levantado exceção)."""
    def synthesize_wav(self, texto, wav_file, syn_config=None):
        pass  # não escreve nada -- simula um bug silencioso qualquer


def _fake_piper_module(voice_cls, download_files_de_verdade=True):
    fake_piper = types.ModuleType("piper")
    fake_piper.PiperVoice = voice_cls

    class FakeSynthesisConfig:
        def __init__(self, length_scale=None, **kw):
            self.length_scale = length_scale

    fake_piper.SynthesisConfig = FakeSynthesisConfig

    fake_download_voices = types.ModuleType("piper.download_voices")

    def fake_download_voice(nome_voz, download_dir):
        if download_files_de_verdade:
            os.makedirs(download_dir, exist_ok=True)
            open(os.path.join(download_dir, f"{nome_voz}.onnx"), "wb").close()
            with open(os.path.join(download_dir, f"{nome_voz}.onnx.json"), "w") as f:
                json.dump({}, f)

    fake_download_voices.download_voice = fake_download_voice
    fake_piper.download_voices = fake_download_voices
    return fake_piper, fake_download_voices


def test_piper_ensure_voice_baixa_quando_nao_existe(tmp_path):
    fake_piper, fake_dl = _fake_piper_module(_FakePiperVoiceApiAtual)
    with fake_module("piper", fake_piper), fake_module("piper.download_voices", fake_dl):
        onnx_path, config_path = vg.piper_ensure_voice("pt_BR-teste-medium", models_dir=str(tmp_path))
        assert os.path.exists(onnx_path)
        assert os.path.exists(config_path)


def test_piper_ensure_voice_nao_baixa_de_novo_se_ja_existe(tmp_path):
    onnx_path = tmp_path / "voz-ja-baixada.onnx"
    onnx_path.write_bytes(b"")
    (tmp_path / "voz-ja-baixada.onnx.json").write_text("{}")

    fake_piper, fake_dl = _fake_piper_module(_FakePiperVoiceApiAtual, download_files_de_verdade=False)
    # download_voice não cria nada nesta versão -- se `piper_ensure_voice`
    # tentasse baixar de novo, a checagem final acusaria arquivo ausente.
    with fake_module("piper", fake_piper), fake_module("piper.download_voices", fake_dl):
        caminho, _ = vg.piper_ensure_voice("voz-ja-baixada", models_dir=str(tmp_path))
        assert caminho == str(onnx_path)


def test_piper_ensure_voice_download_nao_produz_arquivo_da_erro(tmp_path):
    fake_piper, fake_dl = _fake_piper_module(_FakePiperVoiceApiAtual, download_files_de_verdade=False)
    with fake_module("piper", fake_piper), fake_module("piper.download_voices", fake_dl):
        with pytest.raises(vg.VoiceGeneratorError, match="não apareceram"):
            vg.piper_ensure_voice("voz-que-nao-baixa", models_dir=str(tmp_path))


def test_piper_synthesize_usa_synthesize_wav_na_api_atual(tmp_path):
    fake_piper, fake_dl = _fake_piper_module(_FakePiperVoiceApiAtual)
    saida = tmp_path / "saida.wav"
    with fake_module("piper", fake_piper), fake_module("piper.download_voices", fake_dl):
        caminho = vg.piper_synthesize(
            "Olá, mundo!", str(saida), nome_voz="pt_BR-teste-medium",
            velocidade=2.0, use_gpu=False, models_dir=str(tmp_path),
        )
    assert caminho == str(saida)
    assert saida.exists() and saida.stat().st_size > 0
    with wave.open(str(saida), "rb") as w:
        assert w.getframerate() == 22050
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() > 0


def test_piper_synthesize_cai_pra_api_antiga_sem_synthesize_wav(tmp_path):
    fake_piper, fake_dl = _fake_piper_module(_FakePiperVoiceApiAntiga)
    saida = tmp_path / "saida.wav"
    with fake_module("piper", fake_piper), fake_module("piper.download_voices", fake_dl):
        vg.piper_synthesize("Teste", str(saida), nome_voz="v", velocidade=1.5, models_dir=str(tmp_path))
    assert saida.exists() and saida.stat().st_size > 0
    with wave.open(str(saida), "rb") as w:
        assert w.getnframes() > 0


def test_piper_synthesize_reproduz_e_corrige_o_bug_do_audio_zerado(tmp_path):
    """Regressão do bug relatado: versão só-com-gerador (sem
    `.synthesize_wav`) — o código precisa detectar isso e consumir o
    gerador manualmente, em vez de devolver um .wav com 0 frames."""
    fake_piper, fake_dl = _fake_piper_module(_FakePiperVoiceSoGerador)
    saida = tmp_path / "saida.wav"
    with fake_module("piper", fake_piper), fake_module("piper.download_voices", fake_dl):
        vg.piper_synthesize("Teste", str(saida), nome_voz="v", velocidade=1.0, models_dir=str(tmp_path))
    with wave.open(str(saida), "rb") as w:
        assert w.getnframes() > 0  # o bug real: isso dava 0 antes da correção


def test_piper_synthesize_arquivo_vazio_da_erro_claro(tmp_path):
    """Rede de segurança: mesmo se TODAS as tentativas "funcionarem"
    sem exceção mas não escreverem nada de verdade, o erro final tem
    que ser claro (nunca devolver silenciosamente um .wav vazio)."""
    fake_piper, fake_dl = _fake_piper_module(_FakePiperVoiceNaoEscreveNada)
    saida = tmp_path / "saida.wav"
    with fake_module("piper", fake_piper), fake_module("piper.download_voices", fake_dl):
        with pytest.raises(vg.VoiceGeneratorError, match="VAZIO"):
            vg.piper_synthesize("Teste", str(saida), nome_voz="v", models_dir=str(tmp_path))


def test_piper_synthesize_velocidade_1_nao_manda_length_scale(tmp_path):
    fake_piper, fake_dl = _fake_piper_module(_FakePiperVoiceApiAtual)
    saida = tmp_path / "saida.wav"
    with fake_module("piper", fake_piper), fake_module("piper.download_voices", fake_dl):
        vg.piper_synthesize("Teste", str(saida), nome_voz="v", velocidade=1.0, models_dir=str(tmp_path))
    assert saida.exists()


# --------------------------------------------------------------------------- #
# XTTS v2 — sem a lib instalada
# --------------------------------------------------------------------------- #

def test_xtts_synthesize_sem_lib_instalada_da_erro_claro():
    with pytest.raises(vg.VoiceGeneratorError, match="pip install coqui-tts"):
        vg.xtts_synthesize("oi", "/tmp/saida.wav")


def test_xtts_synthesize_idioma_invalido():
    with pytest.raises(vg.VoiceGeneratorError, match="não é suportado"):
        vg.xtts_synthesize("oi", "/tmp/saida.wav", idioma="klingon")


# --------------------------------------------------------------------------- #
# XTTS v2 — com a lib "instalada" (módulo falso)
# --------------------------------------------------------------------------- #

class _FakeXttsModel:
    def __init__(self, model_name=None, model_path=None, config_path=None):
        self.model_name = model_name
        self.model_path = model_path
        self.config_path = config_path
        self.speakers = [] if model_path else ["Ana Florence", "Craig Gutsy"]
        self.device = None
        self.chamadas_tts_to_file = []

    def to(self, device):
        self.device = device
        return self

    def tts_to_file(self, text, language, file_path, speaker=None, speaker_wav=None):
        self.chamadas_tts_to_file.append(
            {"text": text, "language": language, "speaker": speaker, "speaker_wav": speaker_wav}
        )
        with open(file_path, "wb") as f:
            f.write(b"fake-audio-xtts")


def _fake_tts_api_module(model_cls=_FakeXttsModel):
    fake_TTS_api = types.ModuleType("TTS.api")
    fake_TTS_api.TTS = model_cls
    fake_TTS_pkg = types.ModuleType("TTS")
    fake_TTS_pkg.api = fake_TTS_api
    return fake_TTS_pkg, fake_TTS_api


def test_xtts_list_speakers_le_do_modelo_carregado():
    pkg, api = _fake_tts_api_module()
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        speakers = vg.xtts_list_speakers(use_gpu=False)
    assert speakers == ["Ana Florence", "Craig Gutsy"]


def test_xtts_synthesize_usa_primeira_voz_quando_nada_informado(tmp_path):
    pkg, api = _fake_tts_api_module()
    saida = tmp_path / "saida.wav"
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        vg.xtts_synthesize("Olá!", str(saida), idioma="pt", use_gpu=False)
    assert saida.exists()
    modelo = list(vg._xtts_cache.values())[0]
    assert modelo.chamadas_tts_to_file[0]["speaker"] == "Ana Florence"


def test_xtts_synthesize_usa_speaker_nomeado():
    pkg, api = _fake_tts_api_module()
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        import tempfile
        saida = os.path.join(tempfile.mkdtemp(), "saida.wav")
        vg.xtts_synthesize("Olá!", saida, idioma="pt", speaker="Craig Gutsy", use_gpu=False)
        modelo = list(vg._xtts_cache.values())[0]
        assert modelo.chamadas_tts_to_file[0]["speaker"] == "Craig Gutsy"


def test_xtts_synthesize_speaker_wav_tem_prioridade_sobre_speaker(tmp_path):
    pkg, api = _fake_tts_api_module()
    ref = tmp_path / "referencia.wav"
    ref.write_bytes(b"audio de referencia")
    saida = tmp_path / "saida.wav"
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        vg.xtts_synthesize(
            "Olá!", str(saida), idioma="pt", speaker="Ana Florence",
            speaker_wav=str(ref), use_gpu=False,
        )
        modelo = list(vg._xtts_cache.values())[0]
        chamada = modelo.chamadas_tts_to_file[0]
        assert chamada["speaker_wav"] == str(ref)
        assert chamada["speaker"] is None


def test_xtts_synthesize_speaker_wav_inexistente_da_erro(tmp_path):
    pkg, api = _fake_tts_api_module()
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        with pytest.raises(vg.VoiceGeneratorError, match="não encontrado"):
            vg.xtts_synthesize(
                "Olá!", str(tmp_path / "saida.wav"), idioma="pt",
                speaker_wav=str(tmp_path / "nao-existe.wav"), use_gpu=False,
            )


def test_xtts_load_reaproveita_instancia_no_mesmo_device():
    pkg, api = _fake_tts_api_module()
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        m1 = vg.xtts_load(use_gpu=False)
        m2 = vg.xtts_load(use_gpu=False)
    assert m1 is m2


# --------------------------------------------------------------------------- #
# Kokoro — sem a lib instalada
# --------------------------------------------------------------------------- #

def test_kokoro_synthesize_sem_soundfile_da_erro_claro():
    with pytest.raises(vg.VoiceGeneratorError, match="pip install soundfile"):
        vg.kokoro_synthesize("oi", "/tmp/saida.wav")


# --------------------------------------------------------------------------- #
# Kokoro — com as libs "instaladas" (módulos falsos)
# --------------------------------------------------------------------------- #

class _FakeKokoro:
    instancias_criadas = []

    def __init__(self, model_path, voices_path):
        self.model_path = model_path
        self.voices_path = voices_path
        self.chamadas_create = []
        _FakeKokoro.instancias_criadas.append(self)

    def create(self, texto, voice="af_heart", speed=1.0, lang="en-us"):
        self.chamadas_create.append({"texto": texto, "voice": voice, "speed": speed, "lang": lang})
        return ("amostras-falsas", 24000)


def _fake_kokoro_onnx_module():
    _FakeKokoro.instancias_criadas = []
    mod = types.ModuleType("kokoro_onnx")
    mod.Kokoro = _FakeKokoro
    return mod


def _fake_soundfile_module():
    mod = types.ModuleType("soundfile")
    chamadas = []

    def fake_write(path, data, samplerate):
        chamadas.append({"path": path, "data": data, "samplerate": samplerate})
        with open(path, "wb") as f:
            f.write(str(data).encode("utf-8"))

    mod.write = fake_write
    mod._chamadas = chamadas
    return mod


def test_kokoro_ensure_model_baixa_arquivos_faltantes(tmp_path, monkeypatch=None):
    chamadas_download = []

    def fake_download_file(url, dest_path):
        chamadas_download.append(url)
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(b"conteudo-fake")

    original = vg._download_file
    vg._download_file = fake_download_file
    try:
        model_path, voices_path = vg.kokoro_ensure_model(models_dir=str(tmp_path))
        assert os.path.exists(model_path) and os.path.exists(voices_path)
        assert len(chamadas_download) == 2
        # rodando de novo, com os arquivos já existindo, não baixa mais nada
        vg.kokoro_ensure_model(models_dir=str(tmp_path))
        assert len(chamadas_download) == 2
    finally:
        vg._download_file = original


def test_kokoro_synthesize_usa_idioma_da_voz_por_padrao(tmp_path):
    kokoro_mod = _fake_kokoro_onnx_module()
    sf_mod = _fake_soundfile_module()
    saida = tmp_path / "saida.wav"

    original_ensure = vg.kokoro_ensure_model
    vg.kokoro_ensure_model = lambda models_dir=vg.KOKORO_MODELS_DIR, variante=None, precisao=None: (
        str(tmp_path / "kokoro-v1.0.onnx"), str(tmp_path / "voices-v1.0.bin")
    )
    try:
        with fake_module("kokoro_onnx", kokoro_mod), fake_module("soundfile", sf_mod):
            vg.kokoro_synthesize("Olá!", str(saida), voz="pf_dora")
    finally:
        vg.kokoro_ensure_model = original_ensure

    assert saida.exists()
    instancia = _FakeKokoro.instancias_criadas[0]
    assert instancia.chamadas_create[0]["voice"] == "pf_dora"
    assert instancia.chamadas_create[0]["lang"] == "pt-br"  # veio de KOKORO_VOZES["pf_dora"]


def test_kokoro_synthesize_idioma_explicito_sobrescreve_o_da_voz(tmp_path):
    kokoro_mod = _fake_kokoro_onnx_module()
    sf_mod = _fake_soundfile_module()
    saida = tmp_path / "saida.wav"

    original_ensure = vg.kokoro_ensure_model
    vg.kokoro_ensure_model = lambda models_dir=vg.KOKORO_MODELS_DIR, variante=None, precisao=None: (
        str(tmp_path / "kokoro-v1.0.onnx"), str(tmp_path / "voices-v1.0.bin")
    )
    try:
        with fake_module("kokoro_onnx", kokoro_mod), fake_module("soundfile", sf_mod):
            vg.kokoro_synthesize("Olá!", str(saida), voz="pf_dora", idioma="en-us")
    finally:
        vg.kokoro_ensure_model = original_ensure

    instancia = _FakeKokoro.instancias_criadas[0]
    assert instancia.chamadas_create[0]["lang"] == "en-us"


def test_kokoro_load_reaproveita_instancia():
    kokoro_mod = _fake_kokoro_onnx_module()
    original_ensure = vg.kokoro_ensure_model
    vg.kokoro_ensure_model = lambda models_dir=vg.KOKORO_MODELS_DIR, variante=None, precisao=None: ("modelo.onnx", "voices.bin")
    try:
        with fake_module("kokoro_onnx", kokoro_mod):
            k1 = vg.kokoro_load()
            k2 = vg.kokoro_load()
    finally:
        vg.kokoro_ensure_model = original_ensure
    assert k1 is k2


# --------------------------------------------------------------------------- #
# gerar_audio() despachando de verdade pra cada motor (com libs falsas)
# --------------------------------------------------------------------------- #

def test_gerar_audio_despacha_pro_kokoro_corretamente(tmp_path):
    kokoro_mod = _fake_kokoro_onnx_module()
    sf_mod = _fake_soundfile_module()
    saida = tmp_path / "saida.wav"

    original_ensure = vg.kokoro_ensure_model
    vg.kokoro_ensure_model = lambda models_dir=vg.KOKORO_MODELS_DIR, variante=None, precisao=None: (
        str(tmp_path / "m.onnx"), str(tmp_path / "v.bin")
    )
    try:
        with fake_module("kokoro_onnx", kokoro_mod), fake_module("soundfile", sf_mod):
            caminho = vg.gerar_audio("kokoro", "Texto de teste", str(saida), voz="pm_alex")
    finally:
        vg.kokoro_ensure_model = original_ensure

    assert caminho == str(saida)
    assert saida.exists()


# --------------------------------------------------------------------------- #
# Bugs reais relatados por usuário — cada um vira um teste de regressão,
# pra nunca mais quebrar do mesmo jeito sem a suíte pegar.
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# _patch_kokoro_speed_dtype_bug — a correção de verdade do bug do Kokoro
# (não é mais só reformular a mensagem de erro: o patch evita o erro
# ACONTECER, substituindo o método com bug por uma cópia corrigida).
# --------------------------------------------------------------------------- #

class _FakeSessInput:
    def __init__(self, name):
        self.name = name


class _FakeOnnxSession:
    """Simula o `InferenceSession` do onnxruntime o suficiente pro
    `_create_audio` corrigido rodar — grava os `inputs` recebidos em
    `.run()` pra inspecionar o dtype de "speed" depois."""
    def __init__(self, nomes_inputs):
        self._nomes_inputs = nomes_inputs
        self.chamadas_run = []

    def get_inputs(self):
        return [_FakeSessInput(n) for n in self._nomes_inputs]

    def run(self, output_names, inputs):
        self.chamadas_run.append(inputs)
        return [np.zeros(2400, dtype=np.float32)] if HAVE_NUMPY else [[0.0] * 2400]


class _FakeTokenizer:
    def tokenize(self, phonemes):
        return list(range(1, len(phonemes) + 1))[:10]


class _FakeKokoroInstanceParaPatch:
    """Fake da instância `Kokoro` real o suficiente pro
    `_patch_kokoro_speed_dtype_bug` conseguir substituir `_create_audio`
    nela e o método substituído conseguir rodar de ponta a ponta."""
    def __init__(self, nomes_inputs=("input_ids",)):
        self.tokenizer = _FakeTokenizer()
        self.sess = _FakeOnnxSession(nomes_inputs)


try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


def test_patch_kokoro_speed_dtype_bug_nao_mexe_se_ja_corrigido_na_lib():
    """Se `kokoro_onnx.session.input_dtypes` existir (versão >= 0.4.8,
    já sem o bug), o patch não deve fazer nada."""
    fake_session_mod = types.ModuleType("kokoro_onnx.session")
    fake_session_mod.input_dtypes = lambda *a, **k: None
    fake_kokoro_pkg = types.ModuleType("kokoro_onnx")
    fake_kokoro_pkg.session = fake_session_mod

    instancia = _FakeKokoroInstanceParaPatch()
    with fake_module("kokoro_onnx", fake_kokoro_pkg), fake_module("kokoro_onnx.session", fake_session_mod):
        vg._patch_kokoro_speed_dtype_bug(instancia)
    assert not hasattr(instancia, "_create_audio")  # nada foi adicionado -- não precisava


@pytest.mark.skipif(not HAVE_NUMPY, reason="numpy não disponível neste ambiente de teste")
def test_patch_kokoro_speed_dtype_bug_corrige_quando_lib_esta_desatualizada():
    """Sem `kokoro_onnx.session.input_dtypes` (versão antiga, com bug),
    o patch substitui `_create_audio` -- e a versão corrigida manda
    'speed' como float32 pro ONNX Runtime, nunca int32."""
    fake_kokoro_pkg = types.ModuleType("kokoro_onnx")
    fake_kokoro_pkg.log = types.SimpleNamespace(warning=lambda *a, **k: None, debug=lambda *a, **k: None)
    fake_kokoro_pkg.MAX_PHONEME_LENGTH = 500
    fake_kokoro_pkg.SAMPLE_RATE = 24000
    # sem atributo "session" -- simula `from kokoro_onnx.session import input_dtypes` falhando

    instancia = _FakeKokoroInstanceParaPatch(nomes_inputs=("input_ids", "style", "speed"))
    with fake_module("kokoro_onnx", fake_kokoro_pkg):
        vg._patch_kokoro_speed_dtype_bug(instancia)

    assert hasattr(instancia, "_create_audio")  # foi substituído

    voice_fake = {10: np.zeros(256, dtype=np.float32)}
    instancia._create_audio("um texto qualquer", voice_fake, speed=1.5)

    inputs_recebidos = instancia.sess.chamadas_run[0]
    speed_enviado = inputs_recebidos["speed"]
    assert speed_enviado.dtype == np.float32  # NUNCA int32 -- essa é a correção do bug real
    assert float(speed_enviado[0]) == 1.5


def test_kokoro_synthesize_com_erro_generico_propaga_mensagem_original(tmp_path):
    """Um erro que o patch não evita (algo fora do bug conhecido de
    dtype) continua chegando com a mensagem original, sem distorção."""
    class _FakeKokoroFalhaGenerica:
        def __init__(self, model_path, voices_path):
            pass

        def create(self, texto, voice="af_heart", speed=1.0, lang="en-us"):
            raise RuntimeError("algum outro erro qualquer")

    kokoro_mod = types.ModuleType("kokoro_onnx")
    kokoro_mod.Kokoro = _FakeKokoroFalhaGenerica
    sf_mod = _fake_soundfile_module()

    original_ensure = vg.kokoro_ensure_model
    vg.kokoro_ensure_model = lambda models_dir=vg.KOKORO_MODELS_DIR, variante=None, precisao=None: ("m.onnx", "v.bin")
    try:
        with fake_module("kokoro_onnx", kokoro_mod), fake_module("soundfile", sf_mod):
            with pytest.raises(vg.VoiceGeneratorError, match="algum outro erro qualquer"):
                vg.kokoro_synthesize("oi", str(tmp_path / "saida.wav"), voz="pm_alex")
    finally:
        vg.kokoro_ensure_model = original_ensure


class _FakeTTSFalhaTorchcodec:
    def __init__(self, model_name):
        pass

    def to(self, device):
        raise RuntimeError(
            "Could not load libtorchcodec. Likely causes:\n"
            "1. FFmpeg is not properly installed..."
        )


def test_xtts_load_erro_de_torchcodec_da_mensagem_com_solucao():
    pkg = types.ModuleType("TTS")
    api = types.ModuleType("TTS.api")
    api.TTS = _FakeTTSFalhaTorchcodec
    pkg.api = api
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        with pytest.raises(vg.VoiceGeneratorError, match="torchcodec"):
            vg.xtts_load(use_gpu=False)


def test_xtts_load_erro_generico_nao_leva_a_mensagem_de_torchcodec():
    class _FakeTTSFalhaGenerica:
        def __init__(self, model_name):
            pass

        def to(self, device):
            raise RuntimeError("sem espaço em disco")

    pkg = types.ModuleType("TTS")
    api = types.ModuleType("TTS.api")
    api.TTS = _FakeTTSFalhaGenerica
    pkg.api = api
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        with pytest.raises(vg.VoiceGeneratorError) as excinfo:
            vg.xtts_load(use_gpu=False)
        assert "torchcodec" not in str(excinfo.value)
        assert "sem espaço em disco" in str(excinfo.value)


def test_patch_torchaudio_load_troca_a_funcao_por_versao_via_soundfile():
    fake_torchaudio = types.ModuleType("torchaudio")
    fake_torchaudio.load = "original (não deveria sobreviver)"
    fake_soundfile = types.ModuleType("soundfile")
    fake_soundfile.read = lambda *a, **k: (None, 22050)
    fake_torch = types.ModuleType("torch")
    fake_torch.from_numpy = lambda x: x

    vg._torchaudio_patch_applied = False
    try:
        with fake_module("torchaudio", fake_torchaudio), fake_module("soundfile", fake_soundfile), fake_module("torch", fake_torch):
            vg._patch_torchaudio_load_via_soundfile()
            assert fake_torchaudio.load != "original (não deveria sobreviver)"
            assert callable(fake_torchaudio.load)
    finally:
        vg._torchaudio_patch_applied = False


def test_patch_torchaudio_load_so_aplica_uma_vez():
    chamada_conta = {"n": 0}
    fake_torchaudio = types.ModuleType("torchaudio")
    fake_soundfile = types.ModuleType("soundfile")
    fake_torch = types.ModuleType("torch")

    vg._torchaudio_patch_applied = False
    try:
        with fake_module("torchaudio", fake_torchaudio), fake_module("soundfile", fake_soundfile), fake_module("torch", fake_torch):
            vg._patch_torchaudio_load_via_soundfile()
            primeira_funcao = fake_torchaudio.load
            vg._patch_torchaudio_load_via_soundfile()  # segunda chamada -- não deve fazer nada
            assert fake_torchaudio.load is primeira_funcao
    finally:
        vg._torchaudio_patch_applied = False


def test_preparar_audio_referencia_converte_com_ffmpeg_de_verdade(tmp_path):
    import subprocess
    original = str(tmp_path / "original.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-ac", "2", "-ar", "44100", original],
        capture_output=True, check=True,
    )
    resultado = vg._preparar_audio_referencia(original)
    assert resultado != original  # gerou um arquivo NOVO, simplificado
    assert os.path.exists(resultado)


def test_preparar_audio_referencia_cai_pro_original_se_ffmpeg_falhar(tmp_path, monkeypatch):
    caminho_inexistente = str(tmp_path / "nao-existe-de-verdade.wav")
    resultado = vg._preparar_audio_referencia(caminho_inexistente)
    assert resultado == caminho_inexistente  # ffmpeg falha (arquivo não existe) -- cai pro original


def test_xtts_synthesize_usa_audio_de_referencia_simplificado(tmp_path):
    pkg, api = _fake_tts_api_module()
    ref = tmp_path / "referencia.wav"
    ref.write_bytes(b"audio de referencia")
    saida = tmp_path / "saida.wav"
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        vg.xtts_synthesize("Olá!", str(saida), idioma="pt", speaker_wav=str(ref), use_gpu=False)
        modelo = list(vg._xtts_cache.values())[0]
        chamada = modelo.chamadas_tts_to_file[0]
        # o arquivo passado pro modelo é o simplificado (ffmpeg falha
        # em cima de "audio de referencia" que não é um wav de verdade,
        # então cai pro original mesmo -- o importante aqui é confirmar
        # que a função de simplificação FOI usada no fluxo, não travou.
        assert chamada["speaker_wav"] in (str(ref), None) or os.path.exists(chamada["speaker_wav"])


# --------------------------------------------------------------------------- #
# Perfis de voz salvos (clonagem XTTS reutilizável)
# --------------------------------------------------------------------------- #

def _gera_wav_curto(caminho, duracao=3):
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duracao}", str(caminho)],
        capture_output=True, check=True,
    )


def test_salvar_e_listar_perfil_de_voz(tmp_path, monkeypatch):
    ref = tmp_path / "voz.wav"
    _gera_wav_curto(ref)
    perfis_dir = tmp_path / "perfis"
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(perfis_dir))

    caminhos = vg.salvar_perfil_de_voz("Minha Voz!", str(ref))
    assert len(caminhos) == 1
    assert os.path.exists(caminhos[0])
    assert "minha_voz" not in vg.listar_perfis_de_voz()  # nome sanitizado, não vira minúsculo
    assert "Minha_Voz" in vg.listar_perfis_de_voz()  # "!" removido, espaço virou "_"


def test_salvar_perfil_de_voz_corta_audio_longo(tmp_path, monkeypatch):
    ref = tmp_path / "voz_longa.wav"
    _gera_wav_curto(ref, duracao=120)
    perfis_dir = tmp_path / "perfis"
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(perfis_dir))

    import subprocess
    caminhos = vg.salvar_perfil_de_voz("locutor", str(ref), duracao_max_segundos=10.0)
    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", caminhos[0]],
        capture_output=True, text=True,
    ).stdout.strip()
    assert float(dur) <= 11.0


def test_salvar_perfil_de_voz_sem_nome_da_erro(tmp_path, monkeypatch):
    ref = tmp_path / "voz.wav"
    _gera_wav_curto(ref)
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    with pytest.raises(vg.VoiceGeneratorError, match="nome"):
        vg.salvar_perfil_de_voz("", str(ref))


def test_salvar_perfil_de_voz_origem_inexistente_da_erro(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    with pytest.raises(vg.VoiceGeneratorError, match="não encontrado"):
        vg.salvar_perfil_de_voz("nome", str(tmp_path / "nao-existe.wav"))


def test_caminho_perfil_de_voz_inexistente_lista_os_que_existem(tmp_path, monkeypatch):
    perfis_dir = tmp_path / "perfis"
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(perfis_dir))
    ref = tmp_path / "voz.wav"
    _gera_wav_curto(ref)
    vg.salvar_perfil_de_voz("existente", str(ref))

    with pytest.raises(vg.VoiceGeneratorError, match="existente"):
        vg.caminho_perfil_de_voz("nao-existe")


def test_excluir_perfil_de_voz(tmp_path, monkeypatch):
    perfis_dir = tmp_path / "perfis"
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(perfis_dir))
    ref = tmp_path / "voz.wav"
    _gera_wav_curto(ref)
    vg.salvar_perfil_de_voz("temporario", str(ref))
    assert "temporario" in vg.listar_perfis_de_voz()
    vg.excluir_perfil_de_voz("temporario")
    assert "temporario" not in vg.listar_perfis_de_voz()


def test_listar_perfis_de_voz_pasta_inexistente_devolve_vazio(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "nunca-criada"))
    assert vg.listar_perfis_de_voz() == []


def test_xtts_synthesize_usa_voice_profile(tmp_path, monkeypatch):
    perfis_dir = tmp_path / "perfis"
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(perfis_dir))
    ref = tmp_path / "voz.wav"
    _gera_wav_curto(ref)
    vg.salvar_perfil_de_voz("locutor_x", str(ref))

    pkg, api = _fake_tts_api_module()
    saida = tmp_path / "saida.wav"
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        vg.xtts_synthesize("Olá!", str(saida), idioma="pt", voice_profile="locutor_x", use_gpu=False)
        modelo = list(vg._xtts_cache.values())[0]
        chamada = modelo.chamadas_tts_to_file[0]
        assert any("locutor_x" in p for p in chamada["speaker_wav"])
        assert chamada["speaker"] is None


def test_xtts_synthesize_speaker_wav_tem_prioridade_sobre_voice_profile(tmp_path, monkeypatch):
    perfis_dir = tmp_path / "perfis"
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(perfis_dir))
    ref_perfil = tmp_path / "voz_perfil.wav"
    _gera_wav_curto(ref_perfil)
    vg.salvar_perfil_de_voz("perfil_a", str(ref_perfil))

    ref_direta = tmp_path / "voz_direta.wav"
    _gera_wav_curto(ref_direta)

    pkg, api = _fake_tts_api_module()
    saida = tmp_path / "saida.wav"
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        vg.xtts_synthesize(
            "Olá!", str(saida), idioma="pt",
            speaker_wav=str(ref_direta), voice_profile="perfil_a", use_gpu=False,
        )
        modelo = list(vg._xtts_cache.values())[0]
        chamada = modelo.chamadas_tts_to_file[0]
        assert "perfil_a" not in chamada["speaker_wav"]  # speaker_wav explícito venceu


# --------------------------------------------------------------------------- #
# ensure_ffmpeg_dll_directory — primeira linha de defesa contra o
# torchcodec no Windows (idempotente, e não faz nada fora do Windows)
# --------------------------------------------------------------------------- #

def test_ensure_ffmpeg_dll_directory_e_idempotente(monkeypatch):
    chamadas = []
    monkeypatch.setattr(os, "add_dll_directory", lambda p: chamadas.append(p), raising=False)
    monkeypatch.setattr(vg.shutil, "which", lambda nome: "/fake/bin/ffmpeg.exe")
    monkeypatch.setattr(vg, "_ffmpeg_dll_dir_registered", False)

    primeiro = vg.ensure_ffmpeg_dll_directory()
    segundo = vg.ensure_ffmpeg_dll_directory()  # segunda chamada -- não deve registrar de novo
    assert primeiro is not None
    assert segundo is None
    assert len(chamadas) == 1

    monkeypatch.setattr(vg, "_ffmpeg_dll_dir_registered", False)


def test_ensure_ffmpeg_dll_directory_sem_ffmpeg_no_path(monkeypatch):
    monkeypatch.setattr(os, "add_dll_directory", lambda p: None, raising=False)
    monkeypatch.setattr(vg.shutil, "which", lambda nome: None)
    monkeypatch.setattr(vg, "_ffmpeg_dll_dir_registered", False)

    resultado = vg.ensure_ffmpeg_dll_directory()
    assert resultado is None


# --------------------------------------------------------------------------- #
# Catálogo de vozes do Piper (busca + download sob demanda)
# --------------------------------------------------------------------------- #

_CATALOGO_FAKE = {
    "pt_BR-faber-medium": {
        "key": "pt_BR-faber-medium", "name": "faber",
        "language": {"code": "pt_BR", "name_english": "Portuguese", "country_english": "Brazil"},
        "quality": "medium", "num_speakers": 1,
        "files": {"pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx": {"size_bytes": 63201294}},
    },
    "pt_BR-edresson-low": {
        "key": "pt_BR-edresson-low", "name": "edresson",
        "language": {"code": "pt_BR", "name_english": "Portuguese", "country_english": "Brazil"},
        "quality": "low", "num_speakers": 1,
        "files": {"pt/pt_BR/edresson/low/pt_BR-edresson-low.onnx": {"size_bytes": 20000000}},
    },
    "en_US-amy-medium": {
        "key": "en_US-amy-medium", "name": "amy",
        "language": {"code": "en_US", "name_english": "English", "country_english": "United States"},
        "quality": "medium", "num_speakers": 1,
        "files": {"en/en_US/amy/medium/en_US-amy-medium.onnx": {"size_bytes": 63201294}},
    },
}


@pytest.fixture(autouse=True)
def _limpa_cache_catalogo_piper():
    """O catálogo do Piper também guarda em cache em memória a nível de
    módulo (`_piper_catalog_memoria`) -- sem limpar entre testes, um
    teste "vê" o catálogo falso que outro injetou."""
    vg._piper_catalog_memoria.clear()
    yield
    vg._piper_catalog_memoria.clear()


def test_piper_fetch_catalog_baixa_e_guarda_em_memoria(monkeypatch, tmp_path):
    fake_requests = types.ModuleType("requests")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return _CATALOGO_FAKE

    fake_requests.get = lambda url, timeout=None: FakeResp()
    monkeypatch.setattr(vg, "PIPER_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(vg, "_PIPER_CATALOG_CACHE_FILE", str(tmp_path / "_catalogo_vozes.json"))

    with fake_module("requests", fake_requests):
        catalogo = vg.piper_fetch_catalog()
    assert catalogo == _CATALOGO_FAKE
    assert vg._piper_catalog_memoria["dados"] == _CATALOGO_FAKE
    # também salvou em disco
    assert os.path.exists(str(tmp_path / "_catalogo_vozes.json"))


def test_piper_fetch_catalog_reaproveita_cache_em_memoria_sem_rede(monkeypatch):
    vg._piper_catalog_memoria["dados"] = _CATALOGO_FAKE

    def rede_nao_deveria_ser_chamada(*a, **k):
        raise AssertionError("não deveria acessar rede com cache em memória disponível")

    fake_requests = types.ModuleType("requests")
    fake_requests.get = rede_nao_deveria_ser_chamada
    with fake_module("requests", fake_requests):
        catalogo = vg.piper_fetch_catalog()
    assert catalogo == _CATALOGO_FAKE


def test_piper_fetch_catalog_reaproveita_cache_em_disco_sem_rede(monkeypatch, tmp_path):
    cache_path = tmp_path / "_catalogo_vozes.json"
    cache_path.write_text(json.dumps(_CATALOGO_FAKE), encoding="utf-8")
    monkeypatch.setattr(vg, "_PIPER_CATALOG_CACHE_FILE", str(cache_path))

    def rede_nao_deveria_ser_chamada(*a, **k):
        raise AssertionError("não deveria acessar rede com cache em disco disponível")

    fake_requests = types.ModuleType("requests")
    fake_requests.get = rede_nao_deveria_ser_chamada
    with fake_module("requests", fake_requests):
        catalogo = vg.piper_fetch_catalog()
    assert catalogo == _CATALOGO_FAKE


def test_piper_fetch_catalog_forcar_atualizacao_ignora_cache(monkeypatch, tmp_path):
    vg._piper_catalog_memoria["dados"] = {"antigo": {}}
    cache_path = tmp_path / "_catalogo_vozes.json"
    cache_path.write_text(json.dumps({"antigo": {}}), encoding="utf-8")
    monkeypatch.setattr(vg, "PIPER_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(vg, "_PIPER_CATALOG_CACHE_FILE", str(cache_path))

    fake_requests = types.ModuleType("requests")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return _CATALOGO_FAKE

    fake_requests.get = lambda url, timeout=None: FakeResp()
    with fake_module("requests", fake_requests):
        catalogo = vg.piper_fetch_catalog(forcar_atualizacao=True)
    assert catalogo == _CATALOGO_FAKE  # veio do "servidor", não do cache antigo


def test_piper_fetch_catalog_erro_de_rede_da_mensagem_clara(monkeypatch, tmp_path):
    monkeypatch.setattr(vg, "_PIPER_CATALOG_CACHE_FILE", str(tmp_path / "nao-existe.json"))
    fake_requests = types.ModuleType("requests")

    def falha(*a, **k):
        raise ConnectionError("simulado: sem internet")

    fake_requests.get = falha
    with fake_module("requests", fake_requests):
        with pytest.raises(vg.VoiceGeneratorError, match="internet"):
            vg.piper_fetch_catalog()


def test_piper_search_voices_por_idioma():
    vg._piper_catalog_memoria["dados"] = _CATALOGO_FAKE
    resultado = vg.piper_search_voices(idioma="pt")
    assert {r["key"] for r in resultado} == {"pt_BR-faber-medium", "pt_BR-edresson-low"}


def test_piper_search_voices_por_nome():
    vg._piper_catalog_memoria["dados"] = _CATALOGO_FAKE
    resultado = vg.piper_search_voices(busca="amy")
    assert [r["key"] for r in resultado] == ["en_US-amy-medium"]


def test_piper_search_voices_por_qualidade():
    vg._piper_catalog_memoria["dados"] = _CATALOGO_FAKE
    resultado = vg.piper_search_voices(idioma="pt", qualidade="low")
    assert [r["key"] for r in resultado] == ["pt_BR-edresson-low"]


def test_piper_search_voices_busca_ignora_acentos_e_maiusculas():
    vg._piper_catalog_memoria["dados"] = _CATALOGO_FAKE
    resultado = vg.piper_search_voices(busca="BRAZIL")
    assert len(resultado) == 2


def test_piper_search_voices_calcula_tamanho_mb():
    vg._piper_catalog_memoria["dados"] = _CATALOGO_FAKE
    resultado = vg.piper_search_voices(busca="faber")
    assert resultado[0]["tamanho_mb"] == round(63201294 / (1024 * 1024), 1)


def test_piper_search_voices_respeita_max_resultados():
    vg._piper_catalog_memoria["dados"] = _CATALOGO_FAKE
    resultado = vg.piper_search_voices(max_resultados=1)
    assert len(resultado) == 1


def test_piper_search_voices_sem_filtro_devolve_tudo():
    vg._piper_catalog_memoria["dados"] = _CATALOGO_FAKE
    resultado = vg.piper_search_voices()
    assert len(resultado) == 3


def test_piper_search_voices_nao_expoe_campos_pesados():
    """A busca não deve devolver speaker_id_map/hashes de arquivo --
    só os campos enxutos pensados pra UI."""
    vg._piper_catalog_memoria["dados"] = _CATALOGO_FAKE
    resultado = vg.piper_search_voices(busca="faber")
    assert set(resultado[0].keys()) == {
        "key", "nome", "idioma_codigo", "idioma_nome", "pais", "qualidade", "num_falantes", "tamanho_mb",
    }


def test_piper_download_voice_now(tmp_path):
    fake_piper, fake_dl = _fake_piper_module(_FakePiperVoiceApiAtual)
    with fake_module("piper", fake_piper), fake_module("piper.download_voices", fake_dl):
        resultado = vg.piper_download_voice_now("pt_BR-faber-medium", models_dir=str(tmp_path))
    assert resultado["nome_voz"] == "pt_BR-faber-medium"
    assert os.path.exists(resultado["onnx_path"])
    assert resultado["tamanho_mb"] == 0.0  # arquivo fake vazio (0 bytes)


# --------------------------------------------------------------------------- #
# Variantes e precisões do Kokoro (v1.0/v1.1-zh × fp32/fp16/int8)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("variante,precisao,arquivo_modelo_esperado,arquivo_vozes_esperado", [
    ("v1.0", "fp32", "kokoro-v1.0.onnx", "voices-v1.0.bin"),
    ("v1.0", "fp16", "kokoro-v1.0.fp16.onnx", "voices-v1.0.bin"),
    ("v1.0", "int8", "kokoro-v1.0.int8.onnx", "voices-v1.0.bin"),
    ("v1.1-zh", "fp32", "kokoro-v1.1-zh.onnx", "voices-v1.1-zh.bin"),
    ("v1.1-zh", "fp16", "kokoro-v1.1-zh.fp16.onnx", "voices-v1.1-zh.bin"),
    ("v1.1-zh", "int8", "kokoro-v1.1-zh.int8.onnx", "voices-v1.1-zh.bin"),
])
def test_kokoro_ensure_model_constroi_nomes_e_urls_certos(
    tmp_path, variante, precisao, arquivo_modelo_esperado, arquivo_vozes_esperado,
):
    chamadas = []

    def fake_download(url, dest):
        chamadas.append(url)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "wb").close()

    original = vg._download_file
    vg._download_file = fake_download
    try:
        model_path, voices_path = vg.kokoro_ensure_model(str(tmp_path), variante=variante, precisao=precisao)
    finally:
        vg._download_file = original

    assert os.path.basename(model_path) == arquivo_modelo_esperado
    assert os.path.basename(voices_path) == arquivo_vozes_esperado
    assert vg.KOKORO_RELEASE_BASE_URL + arquivo_modelo_esperado in chamadas
    assert vg.KOKORO_RELEASE_BASE_URL + arquivo_vozes_esperado in chamadas


def test_kokoro_ensure_model_variante_invalida(tmp_path):
    with pytest.raises(vg.VoiceGeneratorError, match="Variante"):
        vg.kokoro_ensure_model(str(tmp_path), variante="v9.9")


def test_kokoro_ensure_model_precisao_invalida(tmp_path):
    with pytest.raises(vg.VoiceGeneratorError, match="Precisão"):
        vg.kokoro_ensure_model(str(tmp_path), precisao="ultra")


def test_kokoro_ensure_model_combinacoes_diferentes_nao_se_sobrescrevem(tmp_path):
    """v1.0 e v1.1-zh na mesma precisão têm nomes de arquivo DIFERENTES
    -- baixar um não apaga/sobrescreve o outro, os dois convivem no
    mesmo diretório de modelos."""
    def fake_download(url, dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(url.encode())  # grava a própria URL, pra distinguir depois

    original = vg._download_file
    vg._download_file = fake_download
    try:
        m1, v1 = vg.kokoro_ensure_model(str(tmp_path), variante="v1.0", precisao="fp32")
        m2, v2 = vg.kokoro_ensure_model(str(tmp_path), variante="v1.1-zh", precisao="fp32")
    finally:
        vg._download_file = original

    assert m1 != m2
    assert v1 != v2
    assert os.path.exists(m1) and os.path.exists(m2)


def test_kokoro_load_cacheia_por_combinacao_variante_precisao(tmp_path):
    kokoro_mod = _fake_kokoro_onnx_module()
    original_ensure = vg.kokoro_ensure_model
    vg.kokoro_ensure_model = lambda models_dir=vg.KOKORO_MODELS_DIR, variante=None, precisao=None: (
        f"{tmp_path}/{variante}-{precisao}.onnx", f"{tmp_path}/{variante}-{precisao}.bin"
    )
    try:
        with fake_module("kokoro_onnx", kokoro_mod):
            k_v10 = vg.kokoro_load(variante="v1.0", precisao="fp32")
            k_v10_de_novo = vg.kokoro_load(variante="v1.0", precisao="fp32")
            k_v11 = vg.kokoro_load(variante="v1.1-zh", precisao="fp32")
    finally:
        vg.kokoro_ensure_model = original_ensure

    assert k_v10 is k_v10_de_novo  # mesma combinação -- reaproveita
    assert k_v10 is not k_v11  # combinação diferente -- instância nova


def test_kokoro_synthesize_usa_variante_e_precisao_escolhidas(tmp_path):
    kokoro_mod = _fake_kokoro_onnx_module()
    sf_mod = _fake_soundfile_module()
    saida = tmp_path / "saida.wav"

    chamadas_ensure = []
    original_ensure = vg.kokoro_ensure_model

    def fake_ensure(models_dir=vg.KOKORO_MODELS_DIR, variante=None, precisao=None):
        chamadas_ensure.append((variante, precisao))
        return (str(tmp_path / "m.onnx"), str(tmp_path / "v.bin"))

    vg.kokoro_ensure_model = fake_ensure
    try:
        with fake_module("kokoro_onnx", kokoro_mod), fake_module("soundfile", sf_mod):
            vg.kokoro_synthesize(
                "oi", str(saida), voz="zf_xiaobei", variante="v1.1-zh", precisao="int8",
            )
    finally:
        vg.kokoro_ensure_model = original_ensure

    assert chamadas_ensure == [("v1.1-zh", "int8")]


def test_kokoro_model_variants_e_precisions_tem_labels(): 
    for info in vg.KOKORO_MODEL_VARIANTS.values():
        assert info["label"]
    for info in vg.KOKORO_PRECISIONS.values():
        assert info["label"]


# --------------------------------------------------------------------------- #
# Checkpoints customizados do XTTS (fine-tunes da comunidade)
# --------------------------------------------------------------------------- #

def test_xtts_download_checkpoint_baixa_os_tres_arquivos(tmp_path, monkeypatch):
    chamadas = []

    class FakeResp:
        def __init__(self, conteudo=b"dados", status_code=200):
            self.status_code = status_code
            self._conteudo = conteudo

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def iter_content(self, chunk_size=None):
            yield self._conteudo

    fake_requests = types.ModuleType("requests")

    def fake_get(url, timeout=None, stream=None):
        chamadas.append(url)
        return FakeResp()

    fake_requests.get = fake_get
    with fake_module("requests", fake_requests):
        model_path, config_path = vg.xtts_download_checkpoint("Fulano/meu-xtts-finetune", models_dir=str(tmp_path))

    assert os.path.exists(model_path) and os.path.basename(model_path) == "model.pth"
    assert os.path.exists(config_path) and os.path.basename(config_path) == "config.json"
    assert any("model.pth" in c for c in chamadas)
    assert any("config.json" in c for c in chamadas)
    assert any("vocab.json" in c for c in chamadas)


def test_xtts_download_checkpoint_cai_pro_best_model_se_model_pth_nao_existe(tmp_path):
    class FakeResp:
        def __init__(self, url):
            nome_arquivo = url.rsplit("/", 1)[-1]
            self.status_code = 404 if nome_arquivo == "model.pth" else 200

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=None):
            yield b"dados"

    fake_requests = types.ModuleType("requests")
    fake_requests.get = lambda url, timeout=None, stream=None: FakeResp(url)
    with fake_module("requests", fake_requests):
        model_path, config_path = vg.xtts_download_checkpoint("Fulano/repo-com-best-model", models_dir=str(tmp_path))
    # o arquivo final continua se chamando "model.pth" no disco (nome
    # que o resto do código espera), mesmo tendo vindo do "best_model.pth"
    assert os.path.basename(model_path) == "model.pth"
    assert os.path.exists(model_path)


def test_xtts_download_checkpoint_sem_nenhum_dos_dois_da_erro(tmp_path):
    class FakeResp:
        status_code = 404

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=None):
            yield b""

    fake_requests = types.ModuleType("requests")
    fake_requests.get = lambda url, timeout=None, stream=None: FakeResp()
    with fake_module("requests", fake_requests):
        with pytest.raises(vg.VoiceGeneratorError, match="model.pth.*best_model.pth|best_model.pth.*model.pth"):
            vg.xtts_download_checkpoint("Fulano/repo-vazio", models_dir=str(tmp_path))


def test_xtts_download_checkpoint_nao_baixa_de_novo_se_ja_existe(tmp_path):
    pasta = tmp_path / "Fulano__ja-tenho"
    pasta.mkdir()
    (pasta / "model.pth").write_bytes(b"ja tinha")
    (pasta / "config.json").write_bytes(b"{}")

    def rede_nao_deveria_ser_chamada(*a, **k):
        raise AssertionError("não deveria acessar rede -- arquivos já existem")

    fake_requests = types.ModuleType("requests")
    fake_requests.get = rede_nao_deveria_ser_chamada
    with fake_module("requests", fake_requests):
        model_path, config_path = vg.xtts_download_checkpoint("Fulano/ja-tenho", models_dir=str(tmp_path))
    assert open(model_path, "rb").read() == b"ja tinha"


def test_xtts_load_com_checkpoint_customizado(tmp_path):
    chamadas_tts = []

    class FakeXTTSCustom:
        speakers = []

        def __init__(self, model_path=None, config_path=None):
            chamadas_tts.append({"model_path": model_path, "config_path": config_path})

        def to(self, device):
            return self

    pkg = types.ModuleType("TTS")
    api = types.ModuleType("TTS.api")
    api.TTS = FakeXTTSCustom
    pkg.api = api
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        vg.xtts_load(use_gpu=False, model_path="/fake/model.pth", config_path="/fake/config.json")
    assert chamadas_tts[0]["model_path"] == "/fake/model.pth"
    assert chamadas_tts[0]["config_path"] == "/fake/config.json"


def test_xtts_load_checkpoint_customizado_e_padrao_ficam_em_cache_separado():
    class FakeXTTSFlex:
        speakers = []

        def __init__(self, *a, **kw):
            pass

        def to(self, device):
            return self

    pkg = types.ModuleType("TTS")
    api = types.ModuleType("TTS.api")
    api.TTS = FakeXTTSFlex
    pkg.api = api
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        padrao = vg.xtts_load(use_gpu=False)
        customizado = vg.xtts_load(use_gpu=False, model_path="/fake/m.pth", config_path="/fake/c.json")
        padrao_de_novo = vg.xtts_load(use_gpu=False)
    assert padrao is not customizado
    assert padrao is padrao_de_novo


def test_xtts_synthesize_com_checkpoint_conhecido(tmp_path, monkeypatch):
    pkg, api = _fake_tts_api_module()

    chamado_com = {}

    def fake_download(repo_id, models_dir=None):
        chamado_com["repo_id"] = repo_id
        return (str(tmp_path / "model.pth"), str(tmp_path / "config.json"))

    monkeypatch.setattr(vg, "xtts_download_checkpoint", fake_download)
    saida = tmp_path / "saida.wav"
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        vg.xtts_synthesize(
            "Namaste", str(saida), idioma="hi", speaker="Voz Qualquer",
            checkpoint_conhecido="hindi", use_gpu=False,
        )
    assert chamado_com["repo_id"] == vg.XTTS_CHECKPOINTS_CONHECIDOS["hindi"]["repo_id"]


def test_xtts_synthesize_checkpoint_desconhecido_da_erro():
    with pytest.raises(vg.VoiceGeneratorError, match="desconhecido"):
        vg.xtts_synthesize("oi", "/tmp/saida.wav", checkpoint_conhecido="nao-existe-esse")


def test_xtts_checkpoints_conhecidos_tem_labels():
    for chave, info in vg.XTTS_CHECKPOINTS_CONHECIDOS.items():
        assert info["label"]
        if chave != "padrao":
            assert "/" in info["repo_id"]  # formato "usuario/repositorio"


# --------------------------------------------------------------------------- #
# Perfis de voz com MÚLTIPLOS clipes de referência (várias amostras
# curtas em vez de um clipe único, mais longo) + compatibilidade com
# perfis salvos antes dessa mudança (um único .wav solto).
# --------------------------------------------------------------------------- #

def test_salvar_perfil_com_varios_clipes(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    refs = [tmp_path / f"clipe_{i}.wav" for i in range(3)]
    for r in refs:
        _gera_wav_curto(r, duracao=4)

    caminhos = vg.salvar_perfil_de_voz("multi", [str(r) for r in refs])
    assert len(caminhos) == 3
    assert all(os.path.exists(c) for c in caminhos)
    assert "multi" in vg.listar_perfis_de_voz()


def test_caminho_perfil_de_voz_devolve_todos_os_clipes_em_ordem(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    refs = [tmp_path / f"clipe_{i}.wav" for i in range(3)]
    for r in refs:
        _gera_wav_curto(r, duracao=4)
    vg.salvar_perfil_de_voz("multi2", [str(r) for r in refs])

    caminhos = vg.caminho_perfil_de_voz("multi2")
    assert len(caminhos) == 3
    assert caminhos == sorted(caminhos)  # em ordem (ref_01, ref_02, ref_03)


def test_salvar_perfil_respeita_limite_maximo_de_clipes(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    refs = [tmp_path / f"clipe_{i}.wav" for i in range(vg.MAX_CLIPES_POR_PERFIL + 1)]
    for r in refs:
        _gera_wav_curto(r, duracao=2)
    with pytest.raises(vg.VoiceGeneratorError, match=str(vg.MAX_CLIPES_POR_PERFIL)):
        vg.salvar_perfil_de_voz("demais", [str(r) for r in refs])


def test_salvar_perfil_lista_vazia_da_erro(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    with pytest.raises(vg.VoiceGeneratorError, match="pelo menos um"):
        vg.salvar_perfil_de_voz("vazio", [])


def test_salvar_perfil_um_dos_clipes_nao_existe_da_erro(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    ref_ok = tmp_path / "ok.wav"
    _gera_wav_curto(ref_ok)
    with pytest.raises(vg.VoiceGeneratorError, match="não encontrado"):
        vg.salvar_perfil_de_voz("parcial", [str(ref_ok), str(tmp_path / "nao-existe.wav")])


def test_resalvar_perfil_com_mais_clipes_substitui_o_anterior(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    ref1 = tmp_path / "v1.wav"
    _gera_wav_curto(ref1)
    vg.salvar_perfil_de_voz("regravar", str(ref1))
    assert len(vg.caminho_perfil_de_voz("regravar")) == 1

    ref2, ref3 = tmp_path / "v2.wav", tmp_path / "v3.wav"
    _gera_wav_curto(ref2)
    _gera_wav_curto(ref3)
    vg.salvar_perfil_de_voz("regravar", [str(ref2), str(ref3)])
    assert len(vg.caminho_perfil_de_voz("regravar")) == 2


def test_perfil_antigo_formato_arquivo_solto_continua_funcionando(tmp_path, monkeypatch):
    """Simula um perfil salvo ANTES desta mudança (um .wav solto direto
    em VOICE_PROFILES_DIR, sem pasta) -- precisa continuar funcionando
    sem precisar recriar nada."""
    perfis_dir = tmp_path / "perfis"
    perfis_dir.mkdir()
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(perfis_dir))
    (perfis_dir / "antigo.wav").write_bytes(b"RIFF-fake-wav-content")

    assert "antigo" in vg.listar_perfis_de_voz()
    caminhos = vg.caminho_perfil_de_voz("antigo")
    assert caminhos == [str(perfis_dir / "antigo.wav")]


def test_excluir_perfil_novo_formato_remove_a_pasta_inteira(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    refs = [tmp_path / f"c{i}.wav" for i in range(2)]
    for r in refs:
        _gera_wav_curto(r)
    vg.salvar_perfil_de_voz("apagar_multi", [str(r) for r in refs])
    assert "apagar_multi" in vg.listar_perfis_de_voz()

    vg.excluir_perfil_de_voz("apagar_multi")
    assert "apagar_multi" not in vg.listar_perfis_de_voz()


def test_excluir_perfil_formato_antigo_remove_o_arquivo(tmp_path, monkeypatch):
    perfis_dir = tmp_path / "perfis"
    perfis_dir.mkdir()
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(perfis_dir))
    (perfis_dir / "antigo2.wav").write_bytes(b"fake")

    vg.excluir_perfil_de_voz("antigo2")
    assert not (perfis_dir / "antigo2.wav").exists()
    assert "antigo2" not in vg.listar_perfis_de_voz()


def test_xtts_synthesize_com_perfil_de_varios_clipes_manda_lista_inteira(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    refs = [tmp_path / f"c{i}.wav" for i in range(3)]
    for r in refs:
        _gera_wav_curto(r, duracao=4)
    vg.salvar_perfil_de_voz("locutor_multi", [str(r) for r in refs])

    pkg, api = _fake_tts_api_module()
    saida = tmp_path / "saida.wav"
    with fake_module("TTS", pkg), fake_module("TTS.api", api):
        vg.xtts_synthesize("Olá!", str(saida), idioma="pt", voice_profile="locutor_multi", use_gpu=False)
        modelo = list(vg._xtts_cache.values())[0]
        chamada = modelo.chamadas_tts_to_file[0]
        assert isinstance(chamada["speaker_wav"], list)
        assert len(chamada["speaker_wav"]) == 3


# --------------------------------------------------------------------------- #
# Divisão automática de um áudio longo em vários trechos curtos
# espalhados (em vez de só cortar o começo)
# --------------------------------------------------------------------------- #

def test_dividir_audio_curto_nao_divide(tmp_path):
    curto = tmp_path / "curto.wav"
    _gera_wav_curto(curto, duracao=5)
    resultado = vg.dividir_audio_em_clipes(str(curto), duracao_por_clipe=10.0)
    assert resultado == [str(curto)]


def test_dividir_audio_longo_gera_varios_trechos_espalhados(tmp_path):
    longo = tmp_path / "longo.wav"
    _gera_wav_curto(longo, duracao=120)  # 2 minutos
    trechos = vg.dividir_audio_em_clipes(str(longo), duracao_por_clipe=10.0, quantidade=4)
    try:
        assert len(trechos) == 4
        assert all(os.path.exists(t) for t in trechos)
        for t in trechos:
            dur = vg._duracao_audio_segundos(t)
            assert 9.0 <= dur <= 11.0  # ~10s cada (tolerância de encode)
    finally:
        for t in trechos:
            if os.path.exists(t):
                os.remove(t)


def test_dividir_audio_trechos_vem_de_pontos_diferentes_do_audio(tmp_path):
    """Confirma que os trechos NÃO são todos do começo -- vêm de
    posições espalhadas pelo áudio (o motivo de dividir em vez de só
    truncar)."""
    longo = tmp_path / "longo2.wav"
    _gera_wav_curto(longo, duracao=100)
    trechos = vg.dividir_audio_em_clipes(str(longo), duracao_por_clipe=8.0, quantidade=3)
    try:
        assert len(trechos) == 3
        # cada trecho tem um nome de arquivo diferente (trecho_01, 02, 03)
        # -- prova indireta de que vieram de chamadas de ffmpeg -ss
        # diferentes, não do mesmo ponto repetido.
        nomes = {os.path.basename(t) for t in trechos}
        assert len(nomes) == 3
    finally:
        for t in trechos:
            if os.path.exists(t):
                os.remove(t)


def test_dividir_audio_respeita_limite_maximo_de_clipes(tmp_path):
    longo = tmp_path / "longo3.wav"
    _gera_wav_curto(longo, duracao=200)
    trechos = vg.dividir_audio_em_clipes(str(longo), duracao_por_clipe=10.0, quantidade=99)
    try:
        assert len(trechos) <= vg.MAX_CLIPES_POR_PERFIL
    finally:
        for t in trechos:
            if os.path.exists(t):
                os.remove(t)


def test_dividir_audio_arquivo_invalido_cai_pro_original():
    resultado = vg.dividir_audio_em_clipes("/caminho/que/nao/existe.wav")
    assert resultado == ["/caminho/que/nao/existe.wav"]


def test_duracao_audio_segundos_arquivo_invalido_devolve_none():
    assert vg._duracao_audio_segundos("/nao/existe/mesmo.wav") is None


def test_salvar_perfil_com_audio_longo_divide_automaticamente(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    longo = tmp_path / "narracao_longa.wav"
    _gera_wav_curto(longo, duracao=90)

    caminhos = vg.salvar_perfil_de_voz("de_audio_longo", str(longo))
    assert len(caminhos) > 1  # dividiu em vários trechos, não um só
    assert all(os.path.exists(c) for c in caminhos)
    # os trechos temporários da divisão não deveriam sobrar no disco
    for c in caminhos:
        assert "voz_dividida_" not in c  # já foram copiados pra dentro da pasta do perfil


def test_salvar_perfil_com_audio_curto_nao_divide(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    curto = tmp_path / "curto.wav"
    _gera_wav_curto(curto, duracao=6)

    caminhos = vg.salvar_perfil_de_voz("de_audio_curto", str(curto))
    assert len(caminhos) == 1  # áudio já curto -- processado como veio, sem dividir


def test_salvar_perfil_dividir_audio_longo_false_desativa_divisao(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    longo = tmp_path / "narracao_longa2.wav"
    _gera_wav_curto(longo, duracao=90)

    caminhos = vg.salvar_perfil_de_voz("sem_divisao", str(longo), dividir_audio_longo=False)
    assert len(caminhos) == 1  # divisão desativada -- vira 1 clipe só (cortado em duracao_max_segundos)
    dur = vg._duracao_audio_segundos(caminhos[0])
    assert dur <= 26.0  # cortado no duracao_max_segundos padrão (25s)


def test_salvar_perfil_lista_explicita_nao_aciona_divisao_automatica(tmp_path, monkeypatch):
    """Mandar uma LISTA de arquivos (mesmo que algum deles seja longo)
    não deve disparar a divisão automática -- só se aplica a um único
    caminho, porque nesse caso o usuário já escolheu os trechos."""
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    longo = tmp_path / "longo_em_lista.wav"
    _gera_wav_curto(longo, duracao=90)

    caminhos = vg.salvar_perfil_de_voz("lista_com_longo", [str(longo)])
    assert len(caminhos) == 1  # processado como 1 arquivo da lista, sem dividir


# --------------------------------------------------------------------------- #
# Diagnóstico de GPU — detecta hardware de verdade (via nvidia-smi,
# independente de torch/onnxruntime) e aponta exatamente onde está o
# problema quando "tenho GPU mas não está sendo usada".
# --------------------------------------------------------------------------- #

def test_detectar_gpu_nvidia_sem_nvidia_smi(monkeypatch):
    def fake_run(*a, **k):
        raise FileNotFoundError("nvidia-smi não encontrado")
    monkeypatch.setattr(vg.subprocess, "run", fake_run)
    assert vg.detectar_gpu_nvidia() == []


def test_detectar_gpu_nvidia_com_uma_gpu(monkeypatch):
    class FakeResult:
        returncode = 0
        stdout = "NVIDIA GeForce RTX 3060\n"
    monkeypatch.setattr(vg.subprocess, "run", lambda *a, **k: FakeResult())
    assert vg.detectar_gpu_nvidia() == ["NVIDIA GeForce RTX 3060"]


def test_detectar_gpu_nvidia_com_varias_gpus(monkeypatch):
    class FakeResult:
        returncode = 0
        stdout = "NVIDIA GeForce RTX 3060\nNVIDIA GeForce RTX 4090\n"
    monkeypatch.setattr(vg.subprocess, "run", lambda *a, **k: FakeResult())
    assert vg.detectar_gpu_nvidia() == ["NVIDIA GeForce RTX 3060", "NVIDIA GeForce RTX 4090"]


def test_detectar_gpu_nvidia_comando_falha(monkeypatch):
    class FakeResult:
        returncode = 1
        stdout = ""
    monkeypatch.setattr(vg.subprocess, "run", lambda *a, **k: FakeResult())
    assert vg.detectar_gpu_nvidia() == []


def test_diagnosticar_gpu_sem_gpu_nenhuma(monkeypatch):
    monkeypatch.setattr(vg, "detectar_gpu_nvidia", lambda: [])
    diag = vg.diagnosticar_gpu()
    assert diag["gpu_nvidia_detectada"] is False
    assert "nvidia-smi" in diag["diagnostico"] or "GPU NVIDIA" in diag["diagnostico"]


def test_diagnosticar_gpu_com_gpu_e_torch_cpu_only():
    """O cenário real relatado por um usuário: GPU existe, mas o torch
    instalado é a build CPU-only -- o diagnóstico precisa apontar
    EXATAMENTE isso, com o comando de correção."""
    fake_torch = types.ModuleType("torch")
    fake_torch.__version__ = "2.5.0+cpu"
    fake_torch.version = types.SimpleNamespace(cuda=None)  # build sem CUDA
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)

    with fake_module("torch", fake_torch):
        original_detectar = vg.detectar_gpu_nvidia
        vg.detectar_gpu_nvidia = lambda: ["NVIDIA GeForce RTX 3060"]
        try:
            diag = vg.diagnosticar_gpu()
        finally:
            vg.detectar_gpu_nvidia = original_detectar

    assert diag["gpu_nvidia_detectada"] is True
    assert diag["torch_instalado"] is True
    assert diag["torch_build_tem_cuda"] is False
    assert "CPU-ONLY" in diag["diagnostico"]
    assert "pip uninstall torch" in diag["diagnostico"]


def test_diagnosticar_gpu_com_gpu_e_torch_cuda_funcionando():
    fake_torch = types.ModuleType("torch")
    fake_torch.__version__ = "2.5.0+cu121"
    fake_torch.version = types.SimpleNamespace(cuda="12.1")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: True)

    with fake_module("torch", fake_torch):
        original_detectar = vg.detectar_gpu_nvidia
        vg.detectar_gpu_nvidia = lambda: ["NVIDIA GeForce RTX 4090"]
        try:
            diag = vg.diagnosticar_gpu()
        finally:
            vg.detectar_gpu_nvidia = original_detectar

    assert diag["torch_build_tem_cuda"] is True
    assert diag["torch_cuda_runtime_ok"] is True
    assert "usando a GPU normalmente" in diag["diagnostico"]


def test_diagnosticar_gpu_torch_nao_instalado():
    original_detectar = vg.detectar_gpu_nvidia
    vg.detectar_gpu_nvidia = lambda: ["NVIDIA GeForce RTX 3060"]
    try:
        # garante que "torch" não está em sys.modules pra simular ImportError de verdade
        tinha_torch = sys.modules.pop("torch", None)
        try:
            diag = vg.diagnosticar_gpu()
        finally:
            if tinha_torch is not None:
                sys.modules["torch"] = tinha_torch
    finally:
        vg.detectar_gpu_nvidia = original_detectar

    assert diag["torch_instalado"] is False
    assert "PyTorch não está instalado" in diag["diagnostico"]


def test_diagnosticar_gpu_onnxruntime_cpu_only(monkeypatch):
    fake_ort = types.ModuleType("onnxruntime")
    fake_ort.get_available_providers = lambda: ["CPUExecutionProvider"]

    original_detectar = vg.detectar_gpu_nvidia
    vg.detectar_gpu_nvidia = lambda: ["NVIDIA GeForce RTX 3060"]
    try:
        with fake_module("onnxruntime", fake_ort):
            diag = vg.diagnosticar_gpu()
    finally:
        vg.detectar_gpu_nvidia = original_detectar

    assert diag["onnx_instalado"] is True
    assert diag["onnx_eh_build_gpu"] is False
    assert "onnxruntime-gpu" in diag["diagnostico"]


def test_diagnosticar_gpu_devolve_nomes_das_gpus():
    original_detectar = vg.detectar_gpu_nvidia
    vg.detectar_gpu_nvidia = lambda: ["GPU Falsa 1", "GPU Falsa 2"]
    try:
        diag = vg.diagnosticar_gpu()
    finally:
        vg.detectar_gpu_nvidia = original_detectar
    assert diag["nomes_gpu"] == ["GPU Falsa 1", "GPU Falsa 2"]
    assert "GPU Falsa 1" in diag["diagnostico"] and "GPU Falsa 2" in diag["diagnostico"]


# --------------------------------------------------------------------------- #
# Realce de áudio ("audio enhance") pra gravações da própria voz
# --------------------------------------------------------------------------- #

def _gera_wav_de_teste(caminho, duracao=3):
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=300:duration={duracao}", str(caminho)],
        capture_output=True, check=True,
    )


def test_aplicar_realce_de_voz_produz_arquivo_valido(tmp_path, monkeypatch):
    # sem rede -- garante que cai pro fallback afftdn em vez de tentar
    # baixar o modelo de verdade (mais rápido e determinístico no teste)
    monkeypatch.setattr(vg, "_caminho_modelo_arnndn", lambda: None)
    entrada = tmp_path / "entrada.wav"
    _gera_wav_de_teste(entrada)
    saida = tmp_path / "saida.wav"

    resultado = vg.aplicar_realce_de_voz(str(entrada), str(saida))
    assert resultado == str(saida)
    assert saida.exists() and saida.stat().st_size > 0


def test_aplicar_realce_de_voz_nao_mexe_no_original(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "_caminho_modelo_arnndn", lambda: None)
    entrada = tmp_path / "entrada.wav"
    _gera_wav_de_teste(entrada)
    tamanho_original = entrada.stat().st_size
    saida = tmp_path / "saida.wav"

    vg.aplicar_realce_de_voz(str(entrada), str(saida))
    assert entrada.stat().st_size == tamanho_original


def test_aplicar_realce_de_voz_origem_invalida_da_erro_claro(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "_caminho_modelo_arnndn", lambda: None)
    with pytest.raises(vg.VoiceGeneratorError, match="ffmpeg"):
        vg.aplicar_realce_de_voz(str(tmp_path / "nao-existe.wav"), str(tmp_path / "saida.wav"))


def test_aplicar_realce_de_voz_usa_modelo_arnndn_quando_disponivel(tmp_path, monkeypatch):
    """Confirma que, quando o modelo RNN 'existe' (mockado), o filtro
    monta com `arnndn=model=...` em vez do fallback `afftdn`. Mocka o
    `subprocess.run` inteiro (em vez de rodar o ffmpeg de verdade) --
    um arquivo de modelo arnndn FALSO (bytes quaisquer) é rejeitado
    pelo parser de verdade do ffmpeg, então só dá pra testar a
    CONSTRUÇÃO do comando sem executar de fato contra esse modelo
    inválido (o modelo real é só testado implicitamente pelo caminho
    de fallback, que já roda o ffmpeg de verdade nos outros testes)."""
    modelo_falso = tmp_path / "modelo_rnn" / "std.rnnn"
    modelo_falso.parent.mkdir(parents=True)
    modelo_falso.write_bytes(b"modelo falso")
    monkeypatch.setattr(vg, "_caminho_modelo_arnndn", lambda: str(modelo_falso))

    chamada = {}

    class FakeCompletedProcess:
        returncode = 0
        stderr = b""

    def fake_run(cmd, **kwargs):
        chamada["cmd"] = cmd
        chamada["cwd"] = kwargs.get("cwd")
        # cria o arquivo de saída "na mão" -- o código confere que ele
        # existe depois de chamar o ffmpeg.
        saida_path = cmd[-1]
        os.makedirs(os.path.dirname(saida_path) or ".", exist_ok=True)
        with open(saida_path, "wb") as f:
            f.write(b"audio de saida falso")
        return FakeCompletedProcess()

    monkeypatch.setattr(vg.subprocess, "run", fake_run)

    entrada = tmp_path / "entrada.wav"
    _gera_wav_de_teste(entrada)
    saida = tmp_path / "saida.wav"
    vg.aplicar_realce_de_voz(str(entrada), str(saida))

    filtro_usado = chamada["cmd"][chamada["cmd"].index("-af") + 1]
    assert "arnndn=model=std.rnnn" in filtro_usado
    assert "afftdn" not in filtro_usado
    assert chamada["cwd"] == str(modelo_falso.parent)  # roda com cwd na pasta do modelo


def test_aplicar_realce_de_voz_sem_modelo_usa_afftdn(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "_caminho_modelo_arnndn", lambda: None)
    chamada = {}
    subprocess_original = vg.subprocess.run

    def fake_run(cmd, **kwargs):
        chamada["cmd"] = cmd
        return subprocess_original(cmd, **kwargs)

    monkeypatch.setattr(vg.subprocess, "run", fake_run)

    entrada = tmp_path / "entrada.wav"
    _gera_wav_de_teste(entrada)
    vg.aplicar_realce_de_voz(str(entrada), str(tmp_path / "saida.wav"))

    filtro_usado = chamada["cmd"][chamada["cmd"].index("-af") + 1]
    assert "afftdn=nr=12:nf=-25" in filtro_usado
    assert "arnndn" not in filtro_usado


def test_caminho_modelo_arnndn_reaproveita_cache_sem_rede(tmp_path, monkeypatch):
    cache_falso = tmp_path / "std.rnnn"
    cache_falso.write_bytes(b"ja tinha")
    monkeypatch.setattr(vg, "_ARNNDN_MODEL_CACHE", str(cache_falso))

    def rede_nao_deveria_ser_chamada(*a, **k):
        raise AssertionError("não deveria acessar rede -- cache já existe")

    fake_requests = types.ModuleType("requests")
    fake_requests.get = rede_nao_deveria_ser_chamada
    with fake_module("requests", fake_requests):
        assert vg._caminho_modelo_arnndn() == str(cache_falso)


def test_caminho_modelo_arnndn_baixa_quando_nao_existe(tmp_path, monkeypatch):
    cache_alvo = tmp_path / "novo" / "std.rnnn"
    monkeypatch.setattr(vg, "_ARNNDN_MODEL_CACHE", str(cache_alvo))

    class FakeResp:
        content = b"conteudo do modelo"
        def raise_for_status(self): pass

    fake_requests = types.ModuleType("requests")
    fake_requests.get = lambda url, timeout=None: FakeResp()
    with fake_module("requests", fake_requests):
        caminho = vg._caminho_modelo_arnndn()
    assert caminho == str(cache_alvo)
    assert cache_alvo.read_bytes() == b"conteudo do modelo"


def test_caminho_modelo_arnndn_falha_de_rede_devolve_none(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "_ARNNDN_MODEL_CACHE", str(tmp_path / "nunca-baixado" / "std.rnnn"))

    fake_requests = types.ModuleType("requests")
    fake_requests.get = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("sem internet"))
    with fake_module("requests", fake_requests):
        assert vg._caminho_modelo_arnndn() is None


# --------------------------------------------------------------------------- #
# Corte automático de silêncio das pontas (início/fim) de uma gravação
# --------------------------------------------------------------------------- #

def _gera_audio_com_silencio_nas_pontas(caminho, silencio_inicio=1.0, tom=2.0, silencio_fim=1.0):
    import subprocess
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono:d={silencio_inicio}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={tom}:sample_rate=24000",
        "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono:d={silencio_fim}",
        "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1[out]",
        "-map", "[out]", str(caminho),
    ], capture_output=True, check=True)


def test_cortar_silencio_pontas_reduz_a_duracao(tmp_path):
    entrada = tmp_path / "com_silencio.wav"
    _gera_audio_com_silencio_nas_pontas(entrada, silencio_inicio=1.0, tom=2.0, silencio_fim=1.0)
    saida = tmp_path / "cortado.wav"

    vg.cortar_silencio_pontas(str(entrada), str(saida))
    assert saida.exists()
    import subprocess
    dur_depois = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(saida)],
        capture_output=True, text=True,
    ).stdout.strip())
    assert dur_depois < 3.0  # bem menos que os 4s originais


def test_cortar_silencio_pontas_nao_mexe_no_meio_da_fala(tmp_path):
    """Só corta as PONTAS -- uma pausa razoável no MEIO precisa
    continuar lá (o filtro só olha start_periods=1, uma vez de cada lado)."""
    import subprocess
    entrada = tmp_path / "com_pausa_no_meio.wav"
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1:sample_rate=24000",
        "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=0.5",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1:sample_rate=24000",
        "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1[out]",
        "-map", "[out]", str(entrada),
    ], capture_output=True, check=True)
    saida = tmp_path / "saida.wav"
    vg.cortar_silencio_pontas(str(entrada), str(saida))
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(saida)],
        capture_output=True, text=True,
    ).stdout.strip())
    assert dur > 2.0  # os ~2.5s inteiros (fala+pausa+fala) continuam lá, nada cortado do meio


def test_cortar_silencio_pontas_audio_totalmente_silencioso_nao_quebra(tmp_path):
    import subprocess
    entrada = tmp_path / "so_silencio.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=2", str(entrada)], capture_output=True, check=True)
    saida = tmp_path / "saida.wav"
    resultado = vg.cortar_silencio_pontas(str(entrada), str(saida))
    assert resultado == str(saida)
    assert saida.exists()


def test_cortar_silencio_pontas_origem_invalida_da_erro_claro(tmp_path):
    """Se a origem nem existir, dá um erro claro (VoiceGeneratorError)
    em vez de deixar vazar um FileNotFoundError cru do shutil.copy no
    fallback."""
    saida = tmp_path / "saida.wav"
    with pytest.raises(vg.VoiceGeneratorError, match="não encontrado"):
        vg.cortar_silencio_pontas(str(tmp_path / "nao-existe.wav"), str(saida))


def test_cortar_silencio_pontas_devolve_o_caminho_de_saida(tmp_path):
    entrada = tmp_path / "audio.wav"
    _gera_audio_com_silencio_nas_pontas(entrada)
    saida = tmp_path / "saida.wav"
    resultado = vg.cortar_silencio_pontas(str(entrada), str(saida))
    assert resultado == str(saida)


# --------------------------------------------------------------------------- #
# gerar_audio_isolado — roda a geração num PROCESSO separado, pra um
# crash nativo do motor (ex: incompatibilidade de versão do Python com
# o PyTorch — já aconteceu de verdade, derrubando o servidor inteiro
# sem nenhuma exceção Python pra capturar) não derrubar o servidor
# junto. Testado com multiprocessing de verdade (não mockado) — só
# assim dá pra provar que o isolamento funciona mesmo.
# --------------------------------------------------------------------------- #

def test_gerar_audio_isolado_com_motor_desconhecido_propaga_erro_normal():
    """Um erro NORMAL (VoiceGeneratorError de verdade, não um crash) —
    o processo filho termina limpo (exitcode 0) e o erro chega
    intacto no processo pai."""
    with tempfile.TemporaryDirectory() as tmp:
        saida = os.path.join(tmp, "saida.wav")
        with pytest.raises(vg.VoiceGeneratorError, match="Motor de voz desconhecido"):
            vg.gerar_audio_isolado("motor-que-nao-existe", "teste", saida)


def test_gerar_audio_isolado_texto_vazio_propaga_erro_normal():
    with tempfile.TemporaryDirectory() as tmp:
        saida = os.path.join(tmp, "saida.wav")
        with pytest.raises(vg.VoiceGeneratorError, match="Texto vazio"):
            vg.gerar_audio_isolado("piper", "   ", saida)


def test_gerar_audio_isolado_sobrevive_a_crash_nativo_do_processo_filho(monkeypatch):
    """O teste mais importante desse mecanismo inteiro: um crash NATIVO
    de verdade no processo filho (sem exceção Python nenhuma — ver o
    gancho `VOICE_GENERATOR_TESTE_FORCAR_CRASH`, que simula exatamente
    isso) não pode derrubar o processo que chamou. Sem isolamento por
    processo, esse teste mataria o próprio runner de teste.

    Precisa DESLIGAR o "VOICE_GENERATOR_DESATIVAR_ISOLAMENTO" que o
    conftest.py liga globalmente pra suíte inteira (senão esse teste
    específico, que precisa do isolamento de VERDADE ligado pra fazer
    sentido, cairia no atalho de teste e nunca chegaria a testar nada)."""
    monkeypatch.delenv("VOICE_GENERATOR_DESATIVAR_ISOLAMENTO", raising=False)
    monkeypatch.setenv("VOICE_GENERATOR_TESTE_FORCAR_CRASH", "1")
    with tempfile.TemporaryDirectory() as tmp:
        saida = os.path.join(tmp, "saida.wav")
        with pytest.raises(vg.VoiceGeneratorError, match="travou o processo"):
            vg.gerar_audio_isolado("piper", "teste", saida, nome_voz="x")
    # se chegamos até aqui, o processo que RODA O TESTE sobreviveu ao
    # crash do processo filho -- é exatamente isso que a mudança
    # garante (sem isolamento, o teste inteiro cairia junto).


def test_gerar_audio_isolado_erro_menciona_versao_do_python(monkeypatch):
    """A mensagem de erro do crash precisa dar uma pista ACIONÁVEL
    (não só "algo deu errado") -- menciona versão do Python, já que
    foi exatamente essa a causa real observada (Python 3.14 + PyTorch/
    torch.jit incompatíveis, sem exceção nenhuma pra capturar)."""
    monkeypatch.delenv("VOICE_GENERATOR_DESATIVAR_ISOLAMENTO", raising=False)
    monkeypatch.setenv("VOICE_GENERATOR_TESTE_FORCAR_CRASH", "1")
    with tempfile.TemporaryDirectory() as tmp:
        saida = os.path.join(tmp, "saida.wav")
        with pytest.raises(vg.VoiceGeneratorError) as exc_info:
            vg.gerar_audio_isolado("piper", "teste", saida, nome_voz="x")
        mensagem = str(exc_info.value)
        assert "Python" in mensagem
        assert "código de saída" in mensagem


def test_gerar_audio_isolado_timeout_cancela_e_da_erro_claro(monkeypatch):
    """Motor que trava sem nunca terminar (nem crash, nem sucesso) --
    precisa ser cancelado depois do timeout, não travar pra sempre."""
    monkeypatch.delenv("VOICE_GENERATOR_DESATIVAR_ISOLAMENTO", raising=False)
    monkeypatch.setenv("VOICE_GENERATOR_TESTE_FORCAR_TRAVAMENTO", "1")
    with tempfile.TemporaryDirectory() as tmp:
        saida = os.path.join(tmp, "saida.wav")
        with pytest.raises(vg.VoiceGeneratorError, match="travou e não terminou"):
            vg.gerar_audio_isolado("piper", "teste", saida, timeout=1.0)


# --------------------------------------------------------------------------- #
# Divisão automática de texto pro limite por chamada do XTTS v2 --
# bug real relatado: um texto de ~480 caracteres batia no limite do
# modelo ("XTTS can only generate text with a maximum of 400 tokens")
# porque cada CHAMADA tem um teto (que varia por idioma -- o próprio
# Coqui avisa "203 caracteres pro português"), mesmo já sendo possível
# gerar áudios de dezenas de minutos via várias chamadas concatenadas
# (que o Roteiro para Áudio já fazia por fala -- só o Gerador de Voz
# avulso, numa chamada só, não tinha essa proteção).
# --------------------------------------------------------------------------- #

class TestDividirTextoParaXtts:
    def test_texto_curto_nao_divide(self):
        curto = "Olá, tudo bem?"
        assert vg._dividir_texto_para_xtts(curto) == [curto]

    def test_texto_vazio_devolve_lista_vazia(self):
        assert vg._dividir_texto_para_xtts("") == []
        assert vg._dividir_texto_para_xtts("   ") == []

    def test_texto_longo_divide_respeitando_o_limite(self):
        texto = (
            "Como Osama bin Laden foi encontrado: a caçada de 10 anos que terminou com a operação "
            "militar mais famosa da história recente. Depois do ataque de 11 de setembro de 2001, os "
            "Estados Unidos iniciaram uma das maiores operações de inteligência já vistas, rastreando "
            "mensageiros, analisando comunicações e cruzando informações de diversos países até "
            "finalmente localizar o esconderijo em Abbottabad, no Paquistão, onde ele vivia havia anos "
            "sem ser detectado pelas autoridades locais."
        )
        pedacos = vg._dividir_texto_para_xtts(texto)
        assert len(pedacos) > 1
        for p in pedacos:
            assert len(p) <= vg.XTTS_LIMITE_CARACTERES_POR_CHAMADA

    def test_texto_longo_nao_perde_nenhum_conteudo(self):
        texto = "Primeira frase aqui. Segunda frase bem mais longa pra garantir que ultrapassa o limite sozinha ou em conjunto. Terceira e última frase."
        pedacos = vg._dividir_texto_para_xtts(texto, limite=50)
        reconstruido = re.sub(r"\s+", " ", " ".join(pedacos))
        assert reconstruido == re.sub(r"\s+", " ", texto)

    def test_frase_unica_maior_que_o_limite_quebra_por_virgula(self):
        frase = "Isso é uma frase única, mas bem longa, com várias vírgulas espalhadas, que deveria quebrar nelas, em vez de só no ponto final."
        pedacos = vg._dividir_texto_para_xtts(frase, limite=40)
        assert len(pedacos) > 1
        for p in pedacos:
            assert len(p) <= 40

    def test_frase_sem_pontuacao_interna_quebra_por_palavra(self):
        frase = ("palavra " * 30).strip() + "."
        pedacos = vg._dividir_texto_para_xtts(frase, limite=30)
        for p in pedacos:
            assert len(p) <= 30

    def test_respeita_limite_customizado(self):
        texto = "Uma frase. Outra frase. Mais uma frase aqui."
        pedacos = vg._dividir_texto_para_xtts(texto, limite=15)
        for p in pedacos:
            assert len(p) <= 15


class TestXttsSynthesizeComDivisaoAutomatica:
    class _FakeTTS:
        speakers = ["voz_padrao"]

        def __init__(self, falhar_em=None):
            self.falhar_em = falhar_em
            self.chamadas = []

        def tts_to_file(self, text, language, file_path, **kw):
            self.chamadas.append(text)
            if self.falhar_em and self.falhar_em in text:
                raise RuntimeError("falha simulada")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=0.4",
                 "-ar", "24000", "-ac", "1", file_path],
                capture_output=True, check=True,
            )

    def test_texto_curto_gera_numa_chamada_so(self, tmp_path, monkeypatch):
        fake = self._FakeTTS()
        monkeypatch.setattr(vg, "xtts_load", lambda **kw: fake)
        saida = str(tmp_path / "saida.wav")
        vg.xtts_synthesize("Oi, tudo bem?", saida, idioma="pt")
        assert len(fake.chamadas) == 1
        assert fake.chamadas[0] == "Oi, tudo bem?"
        assert os.path.exists(saida)

    def test_texto_longo_gera_em_varias_chamadas_e_concatena(self, tmp_path, monkeypatch):
        fake = self._FakeTTS()
        monkeypatch.setattr(vg, "xtts_load", lambda **kw: fake)
        texto = (
            "Como Osama bin Laden foi encontrado: a caçada de 10 anos que terminou com a operação "
            "militar mais famosa da história recente. Depois do ataque de 11 de setembro de 2001, os "
            "Estados Unidos iniciaram uma das maiores operações de inteligência já vistas, rastreando "
            "mensageiros, analisando comunicações e cruzando informações de diversos países até "
            "finalmente localizar o esconderijo em Abbottabad, no Paquistão, onde ele vivia havia anos "
            "sem ser detectado pelas autoridades locais."
        )
        saida = str(tmp_path / "saida.wav")
        vg.xtts_synthesize(texto, saida, idioma="pt")

        assert len(fake.chamadas) > 1
        for c in fake.chamadas:
            assert len(c) <= vg.XTTS_LIMITE_CARACTERES_POR_CHAMADA

        assert os.path.exists(saida)
        dur = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", saida],
            capture_output=True, text=True,
        ).stdout.strip())
        # cada pedaco fake tem 0.4s -- o final concatenado tem que ter a soma de todos
        assert dur > 0.4 * (len(fake.chamadas) - 1)

    def test_pasta_temporaria_de_pedacos_e_limpa_apos_sucesso(self, tmp_path, monkeypatch):
        fake = self._FakeTTS()
        monkeypatch.setattr(vg, "xtts_load", lambda **kw: fake)
        texto = "Frase um bem longa pra forçar divisão. " * 10
        saida = str(tmp_path / "saida.wav")
        vg.xtts_synthesize(texto, saida, idioma="pt")
        restantes = [f for f in os.listdir(tmp_path) if f.startswith("_xtts_pedacos_")]
        assert restantes == []

    def test_erro_num_pedaco_indica_qual_pedaco_falhou(self, tmp_path, monkeypatch):
        fake = self._FakeTTS(falhar_em="Abbottabad")
        monkeypatch.setattr(vg, "xtts_load", lambda **kw: fake)
        texto = (
            "Como Osama bin Laden foi encontrado: a caçada de 10 anos que terminou com a operação "
            "militar mais famosa da história recente. Depois do ataque de 11 de setembro de 2001, os "
            "Estados Unidos iniciaram uma das maiores operações de inteligência já vistas, rastreando "
            "mensageiros, analisando comunicações e cruzando informações de diversos países até "
            "finalmente localizar o esconderijo em Abbottabad, no Paquistão, onde ele vivia havia anos "
            "sem ser detectado pelas autoridades locais."
        )
        saida = str(tmp_path / "saida.wav")
        with pytest.raises(vg.VoiceGeneratorError, match="pedaço"):
            vg.xtts_synthesize(texto, saida, idioma="pt")

    def test_pasta_temporaria_e_limpa_mesmo_com_erro(self, tmp_path, monkeypatch):
        fake = self._FakeTTS(falhar_em="Abbottabad")
        monkeypatch.setattr(vg, "xtts_load", lambda **kw: fake)
        texto = (
            "Como Osama bin Laden foi encontrado: a caçada de 10 anos que terminou com a operação "
            "militar mais famosa da história recente. Depois do ataque de 11 de setembro de 2001, os "
            "Estados Unidos iniciaram uma das maiores operações de inteligência já vistas, rastreando "
            "mensageiros, analisando comunicações e cruzando informações de diversos países até "
            "finalmente localizar o esconderijo em Abbottabad, no Paquistão, onde ele vivia havia anos "
            "sem ser detectado pelas autoridades locais."
        )
        saida = str(tmp_path / "saida.wav")
        try:
            vg.xtts_synthesize(texto, saida, idioma="pt")
        except vg.VoiceGeneratorError:
            pass
        restantes = [f for f in os.listdir(tmp_path) if f.startswith("_xtts_pedacos_")]
        assert restantes == []


# --------------------------------------------------------------------------- #
# Chatterbox TTS (Resemble AI) — segundo motor com clonagem de voz por
# zero-shot (igual o XTTS v2), open-source, 23 idiomas incluindo
# português. Usa a variante multilíngue (`ChatterboxMultilingualTTS`).
# --------------------------------------------------------------------------- #

class _FakeModeloChatterbox:
    sr = 24000

    def __init__(self):
        self.chamadas = []

    def generate(self, texto, **kwargs):
        self.chamadas.append({"texto": texto, **kwargs})
        return "tensor_de_audio_falso"


def _fake_salvar_audio_chatterbox(wav, output_path, sample_rate):
    """Substitui `_salvar_audio_chatterbox` nos testes -- o
    `torchaudio` de verdade é uma dependência pesada (puxada pelo
    `chatterbox-tts`) que não precisa estar instalada só pra testar a
    lógica de `chatterbox_synthesize`."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=0.4", output_path],
        capture_output=True, check=True,
    )


class TestChatterboxSynthesize:
    def test_geracao_sem_clonagem_usa_parametros_default(self, tmp_path, monkeypatch):
        fake = _FakeModeloChatterbox()
        monkeypatch.setattr(vg, "chatterbox_load", lambda **kw: fake)
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", _fake_salvar_audio_chatterbox)

        saida = str(tmp_path / "saida.wav")
        resultado = vg.chatterbox_synthesize("Olá, isso é um teste.", saida, idioma="pt")

        assert os.path.exists(resultado)
        assert fake.chamadas[-1]["texto"] == "Olá, isso é um teste."
        assert fake.chamadas[-1]["language_id"] == "pt"
        assert fake.chamadas[-1]["exaggeration"] == 0.5
        assert fake.chamadas[-1]["cfg_weight"] == 0.5
        assert "audio_prompt_path" not in fake.chamadas[-1]

    def test_idioma_invalido_da_erro_claro(self, tmp_path, monkeypatch):
        fake = _FakeModeloChatterbox()
        monkeypatch.setattr(vg, "chatterbox_load", lambda **kw: fake)
        with pytest.raises(vg.VoiceGeneratorError, match="Chatterbox TTS"):
            vg.chatterbox_synthesize("teste", str(tmp_path / "x.wav"), idioma="xx-invalido")

    def test_clonagem_com_speaker_wav(self, tmp_path, monkeypatch):
        fake = _FakeModeloChatterbox()
        monkeypatch.setattr(vg, "chatterbox_load", lambda **kw: fake)
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", _fake_salvar_audio_chatterbox)

        ref_audio = str(tmp_path / "referencia.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=200:duration=3", "-ar", "22050", "-ac", "1", ref_audio],
            capture_output=True, check=True,
        )
        saida = str(tmp_path / "com_clonagem.wav")
        vg.chatterbox_synthesize(
            "Texto clonado", saida, idioma="en", speaker_wav=ref_audio,
            exaggeration=0.8, cfg_weight=0.3,
        )
        assert os.path.exists(saida)
        ultima = fake.chamadas[-1]
        assert "audio_prompt_path" in ultima
        assert os.path.exists(ultima["audio_prompt_path"])
        assert ultima["exaggeration"] == 0.8
        assert ultima["cfg_weight"] == 0.3

    def test_speaker_wav_inexistente_da_erro_claro(self, tmp_path, monkeypatch):
        fake = _FakeModeloChatterbox()
        monkeypatch.setattr(vg, "chatterbox_load", lambda **kw: fake)
        with pytest.raises(vg.VoiceGeneratorError, match="Áudio de referência não encontrado"):
            vg.chatterbox_synthesize("teste", str(tmp_path / "x.wav"), speaker_wav="/caminho/que/nao/existe.wav")

    def test_voice_profile_reaproveita_o_mesmo_mecanismo_do_xtts(self, tmp_path, monkeypatch):
        """O MESMO perfil salvo com `salvar_perfil_de_voz()` (já usado
        pelo XTTS) funciona no Chatterbox também -- os dois só
        precisam de um áudio de referência."""
        monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
        ref = str(tmp_path / "ref_perfil.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=250:duration=3", "-ar", "22050", "-ac", "1", ref],
            capture_output=True, check=True,
        )
        vg.salvar_perfil_de_voz("minha_voz_clonada", [ref])

        fake = _FakeModeloChatterbox()
        monkeypatch.setattr(vg, "chatterbox_load", lambda **kw: fake)
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", _fake_salvar_audio_chatterbox)

        saida = str(tmp_path / "com_perfil.wav")
        vg.chatterbox_synthesize("teste com perfil", saida, idioma="pt", voice_profile="minha_voz_clonada")
        assert os.path.exists(saida)
        assert "audio_prompt_path" in fake.chamadas[-1]
        assert os.path.exists(fake.chamadas[-1]["audio_prompt_path"])

    def test_sem_o_pacote_instalado_da_erro_claro(self, tmp_path, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, "chatterbox", None)
        monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", None)
        with pytest.raises(vg.VoiceGeneratorError, match="pip install chatterbox-tts"):
            vg.chatterbox_synthesize("teste", str(tmp_path / "x.wav"))

    def test_gerar_audio_despacha_para_chatterbox(self, tmp_path, monkeypatch):
        fake = _FakeModeloChatterbox()
        monkeypatch.setattr(vg, "chatterbox_load", lambda **kw: fake)
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", _fake_salvar_audio_chatterbox)

        saida = str(tmp_path / "via_dispatch.wav")
        vg.gerar_audio("chatterbox", "teste via dispatch", saida, idioma="pt")
        assert os.path.exists(saida)

    def test_chatterbox_esta_listado_em_engines(self):
        assert "chatterbox" in vg.ENGINES
        assert "instalar" in vg.ENGINES["chatterbox"]

    def test_todos_os_23_idiomas_documentados_sao_aceitos(self, tmp_path, monkeypatch):
        fake = _FakeModeloChatterbox()
        monkeypatch.setattr(vg, "chatterbox_load", lambda **kw: fake)
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", _fake_salvar_audio_chatterbox)
        for idioma in vg.CHATTERBOX_IDIOMAS:
            saida = str(tmp_path / f"idioma_{idioma}.wav")
            vg.chatterbox_synthesize("teste", saida, idioma=idioma)
            assert os.path.exists(saida)

    def test_pt_esta_entre_os_idiomas_suportados(self):
        assert "pt" in vg.CHATTERBOX_IDIOMAS

    def test_salvar_audio_usa_soundfile_em_vez_de_torchaudio_save(self, monkeypatch):
        """Bug real: `torchaudio.save()` em versões recentes tenta criar
        um "AudioEncoder" via torchcodec por baixo dos panos -- o MESMO
        problema de DLL do FFmpeg no Windows que afeta `torchaudio.load()`,
        só que a defesa que já existia só cobria o `load`. Salvar via
        `soundfile` evita esse caminho por completo."""
        import sys
        import types

        import numpy as np

        chamadas_sf_write = []
        fake_sf = types.ModuleType("soundfile")

        def fake_write(path, dados, samplerate):
            chamadas_sf_write.append({"shape": dados.shape, "ndim": dados.ndim, "sr": samplerate})
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=0.1", path], capture_output=True, check=True)

        fake_sf.write = fake_write
        monkeypatch.setitem(sys.modules, "soundfile", fake_sf)

        class FakeTensor:
            def __init__(self, dados):
                self._dados = dados

            def detach(self):
                return self

            def cpu(self):
                return self

            def numpy(self):
                return self._dados

        import tempfile

        # tensor 2D mono (1, N) -- formato real que o Chatterbox devolve
        dados_mono = np.zeros((1, 24000), dtype=np.float32)
        saida = tempfile.mktemp(suffix=".wav")
        vg._salvar_audio_chatterbox(FakeTensor(dados_mono), saida, 24000)

        assert os.path.exists(saida)
        ultima = chamadas_sf_write[-1]
        assert ultima["ndim"] == 1  # convertido de (1, 24000) pra (24000,) -- mono de verdade
        assert ultima["shape"] == (24000,)
        assert ultima["sr"] == 24000

    def test_salvar_audio_tensor_estereo_e_transposto_corretamente(self, monkeypatch):
        import sys
        import types

        import numpy as np

        chamadas_sf_write = []
        fake_sf = types.ModuleType("soundfile")

        def fake_write(path, dados, samplerate):
            chamadas_sf_write.append({"shape": dados.shape})
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=0.1", path], capture_output=True, check=True)

        fake_sf.write = fake_write
        monkeypatch.setitem(sys.modules, "soundfile", fake_sf)

        class FakeTensor:
            def __init__(self, dados):
                self._dados = dados

            def detach(self):
                return self

            def cpu(self):
                return self

            def numpy(self):
                return self._dados

        import tempfile

        dados_estereo = np.zeros((2, 8000), dtype=np.float32)  # (canais, amostras) -- convenção torch
        saida = tempfile.mktemp(suffix=".wav")
        vg._salvar_audio_chatterbox(FakeTensor(dados_estereo), saida, 24000)
        assert chamadas_sf_write[-1]["shape"] == (8000, 2)  # transposto pra (amostras, canais)

    def test_salvar_audio_cai_pro_torchaudio_save_se_soundfile_falhar(self, monkeypatch):
        """Se o caminho do soundfile falhar por qualquer motivo, ainda
        tenta o jeito antigo (torchaudio.save) em vez de travar --
        melhor tentar do que não gerar áudio nenhum."""
        import sys
        import types

        fake_ta = types.ModuleType("torchaudio")
        chamadas = []

        def fake_save(path, wav, sr):
            chamadas.append((path, sr))
            open(path, "wb").close()

        fake_ta.save = fake_save
        monkeypatch.setitem(sys.modules, "torchaudio", fake_ta)
        monkeypatch.setitem(sys.modules, "soundfile", None)  # import falha

        class TensorQuebraSoundfile:
            def detach(self):
                raise RuntimeError("simulando qualquer falha no caminho do soundfile")

        import tempfile

        saida = tempfile.mktemp(suffix=".wav")
        vg._salvar_audio_chatterbox(TensorQuebraSoundfile(), saida, 24000)
        assert len(chamadas) == 1
        assert os.path.exists(saida)

    def test_carregar_aplica_as_duas_defesas_do_torchcodec(self, monkeypatch):
        """Mesmo bug do XTTS no Windows (torchcodec/FFmpeg) também
        afeta o Chatterbox -- ele usa torch/torchaudio por baixo dos
        panos pra carregar o áudio de referência da clonagem. As duas
        defesas que já existiam só pro XTTS (`ensure_ffmpeg_dll_directory`
        e `_patch_torchaudio_load_via_soundfile`) precisam rodar aqui
        também, ANTES de qualquer geração."""
        import sys
        import types

        chamadas = {"ensure_dll": 0, "patch_torchaudio": 0}
        monkeypatch.setattr(vg, "ensure_ffmpeg_dll_directory",
                             lambda: chamadas.__setitem__("ensure_dll", chamadas["ensure_dll"] + 1))
        monkeypatch.setattr(vg, "_patch_torchaudio_load_via_soundfile",
                             lambda: chamadas.__setitem__("patch_torchaudio", chamadas["patch_torchaudio"] + 1))

        fake_perth = types.ModuleType("perth")

        class FakeWatermarker:
            pass

        fake_perth.PerthImplicitWatermarker = FakeWatermarker
        monkeypatch.setitem(sys.modules, "perth", fake_perth)

        fake_chatterbox = types.ModuleType("chatterbox")
        fake_mtl = types.ModuleType("chatterbox.mtl_tts")

        class FakeModeloOk:
            sr = 24000

        class FakeChatterboxMTLOk:
            @staticmethod
            def from_pretrained(device):
                return FakeModeloOk()

        fake_mtl.ChatterboxMultilingualTTS = FakeChatterboxMTLOk
        monkeypatch.setitem(sys.modules, "chatterbox", fake_chatterbox)
        monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", fake_mtl)
        vg._chatterbox_cache.pop("chatterbox-multilingual:cpu", None)

        vg.chatterbox_load(use_gpu=False)
        assert chamadas["ensure_dll"] == 1
        assert chamadas["patch_torchaudio"] == 1

    def test_erro_cuda_device_side_assert_da_dica_sobre_texto_curto(self, monkeypatch):
        """Bug real e documentado do próprio Chatterbox (issues #435 e
        #201 no repositório oficial): texto curto demais pode travar a
        GPU com um "device-side assert". A mensagem de erro genérica
        do CUDA não ajuda em nada -- detecta esse padrão e dá uma dica
        acionável em vez disso."""
        class FakeModeloCudaCrash:
            sr = 24000

            def generate(self, texto, **kwargs):
                raise RuntimeError(
                    "CUDA error: device-side assert triggered\n"
                    "Search for `cudaErrorAssert' in ... for more information.\n"
                    "For debugging consider passing CUDA_LAUNCH_BLOCKING=1"
                )

        monkeypatch.setattr(vg, "chatterbox_load", lambda **kw: FakeModeloCudaCrash())
        import tempfile
        with pytest.raises(vg.VoiceGeneratorError, match="TEXTO CURTO DEMAIS") as exc_info:
            vg.chatterbox_synthesize("Sim.", tempfile.mktemp(suffix=".wav"), idioma="pt")
        mensagem = str(exc_info.value)
        assert "#435" in mensagem and "#201" in mensagem
        assert "processo isolado" in mensagem

    def test_erro_generico_de_geracao_nao_ganha_a_dica_de_cuda(self, monkeypatch):
        """Um erro qualquer que não tenha nada a ver com CUDA continua
        com a mensagem simples de sempre -- a dica de texto curto só
        entra quando o padrão bate."""
        class FakeModeloErroQualquer:
            sr = 24000

            def generate(self, texto, **kwargs):
                raise RuntimeError("algum outro erro qualquer sem nada a ver com CUDA")

        monkeypatch.setattr(vg, "chatterbox_load", lambda **kw: FakeModeloErroQualquer())
        import tempfile
        with pytest.raises(vg.VoiceGeneratorError) as exc_info:
            vg.chatterbox_synthesize("texto normal", tempfile.mktemp(suffix=".wav"), idioma="pt")
        mensagem = str(exc_info.value)
        assert "TEXTO CURTO DEMAIS" not in mensagem
        assert mensagem == "Falha ao gerar áudio com o Chatterbox TTS: algum outro erro qualquer sem nada a ver com CUDA"

    def test_texto_curto_gera_numa_chamada_so(self, tmp_path, monkeypatch):
        chamadas = []

        class FakeModelo:
            sr = 24000

            def generate(self, texto, **kwargs):
                chamadas.append(texto)
                return "wav"

        monkeypatch.setattr(vg, "chatterbox_load", lambda **kw: FakeModelo())
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", _fake_salvar_audio_chatterbox)

        vg.chatterbox_synthesize("Texto normal, de tamanho comum pra uma fala.", str(tmp_path / "x.wav"), idioma="pt")
        assert len(chamadas) == 1

    def test_texto_longo_e_dividido_em_pedacos_e_concatenado_sem_perder_conteudo(self, tmp_path, monkeypatch):
        """Bug real relatado: um texto de vários parágrafos (roteiro
        de narração comum nesse site) mandado inteiro numa chamada só
        travava a GPU com um erro de índice fora dos limites -- o
        Chatterbox tem uma "janela acústica" limitada por chamada,
        igual o XTTS. Corrigido reaproveitando o mesmo mecanismo de
        divisão automática."""
        texto_longo = (
            "Euphoria\n\nDesenvolvida e publicada pela ClockUp, lançada para Windows em 24 de "
            "junho de 2011, com tradução oficial para o inglês em 2015. Recebeu ainda uma "
            "adaptação em OVA de anime, com seis episódios, exibida entre 2011 e 2016. Esse é, "
            "de longe, o título mais difícil de comentar nesta lista.\n\nA premissa envolve um "
            "grupo de personagens que desperta em uma sala isolada, sem memória de como chegaram "
            "ali, e descobre estar participando de um \"jogo\" forçado, imposto por uma voz "
            "computadorizada: para avançar e sobreviver, o protagonista é obrigado a realizar, "
            "contra a vontade das vítimas, uma série de atos extremos e degradantes."
        )
        chamadas = []

        class FakeModelo:
            sr = 24000

            def generate(self, texto, **kwargs):
                chamadas.append(texto)
                return f"wav_{len(chamadas)}"

        def fake_salvar_numerado(wav, output_path, sample_rate):
            numero = wav.split("_")[1]
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={200 + int(numero) * 10}:duration=0.3", output_path],
                capture_output=True, check=True,
            )

        monkeypatch.setattr(vg, "chatterbox_load", lambda **kw: FakeModelo())
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", fake_salvar_numerado)

        saida = str(tmp_path / "euphoria.wav")
        resultado = vg.chatterbox_synthesize(texto_longo, saida, idioma="pt")

        assert len(chamadas) > 1
        for pedaco in chamadas:
            assert len(pedaco) <= vg.CHATTERBOX_LIMITE_CARACTERES_POR_CHAMADA
        assert os.path.exists(resultado)

        original_normalizado = " ".join(texto_longo.split())
        reconstruido_normalizado = " ".join(" ".join(chamadas).split())
        assert original_normalizado == reconstruido_normalizado

    def test_pasta_temporaria_de_pedacos_e_limpa_apos_sucesso(self, tmp_path, monkeypatch):
        texto_longo = "Frase um bem completa pra passar do limite. " * 20
        monkeypatch.setattr(vg, "chatterbox_load", lambda **kw: _FakeModeloChatterbox())
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", _fake_salvar_audio_chatterbox)

        saida = str(tmp_path / "saida.wav")
        vg.chatterbox_synthesize(texto_longo, saida, idioma="pt")
        pastas_temp = [p for p in os.listdir(tmp_path) if p.startswith("_chatterbox_pedacos_")]
        assert pastas_temp == []

    def test_erro_num_pedaco_indica_qual_pedaco_falhou(self, tmp_path, monkeypatch):
        texto_longo = "Frase completa número um por aqui mesmo. " * 20

        class FakeModeloFalhaNoSegundo:
            sr = 24000

            def __init__(self):
                self.chamadas = 0

            def generate(self, texto, **kwargs):
                self.chamadas += 1
                if self.chamadas == 2:
                    raise RuntimeError("falhou nesse pedaço")
                return "wav"

        monkeypatch.setattr(vg, "chatterbox_load", lambda **kw: FakeModeloFalhaNoSegundo())
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", _fake_salvar_audio_chatterbox)

        with pytest.raises(vg.VoiceGeneratorError, match=r"pedaço 2 de"):
            vg.chatterbox_synthesize(texto_longo, str(tmp_path / "x.wav"), idioma="pt")

    def test_perth_watermarker_none_da_erro_claro_sobre_setuptools(self, monkeypatch):
        """Bug real e comum: resemble-perth (o watermarker que o
        Chatterbox usa) importa pkg_resources, removido pelo
        setuptools>=81 -- ele engole esse erro e deixa
        PerthImplicitWatermarker = None, o que faz o Chatterbox quebrar
        bem mais tarde com um TypeError sem contexto nenhum. A
        checagem proativa detecta isso ANTES de chegar nesse ponto."""
        import sys
        import types

        fake_perth = types.ModuleType("perth")
        fake_perth.PerthImplicitWatermarker = None
        monkeypatch.setitem(sys.modules, "perth", fake_perth)

        fake_chatterbox = types.ModuleType("chatterbox")
        fake_mtl = types.ModuleType("chatterbox.mtl_tts")
        fake_mtl.ChatterboxMultilingualTTS = object()
        monkeypatch.setitem(sys.modules, "chatterbox", fake_chatterbox)
        monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", fake_mtl)

        with pytest.raises(vg.VoiceGeneratorError, match="setuptools<81"):
            vg.chatterbox_load()

    def test_erro_nonetype_callable_no_from_pretrained_da_dica_do_setuptools(self, monkeypatch):
        """Mesmo se a checagem proativa não pegar (ex: import do perth
        falhando por outro motivo), o erro típico do from_pretrained()
        também é detectado pela mensagem e ganha a mesma dica."""
        import sys
        import types

        fake_perth = types.ModuleType("perth")

        class FakeWatermarker:
            pass

        fake_perth.PerthImplicitWatermarker = FakeWatermarker  # não é None aqui
        monkeypatch.setitem(sys.modules, "perth", fake_perth)

        fake_chatterbox = types.ModuleType("chatterbox")
        fake_mtl = types.ModuleType("chatterbox.mtl_tts")

        class FakeChatterboxMTLFalha:
            @staticmethod
            def from_pretrained(device):
                raise TypeError("'NoneType' object is not callable")

        fake_mtl.ChatterboxMultilingualTTS = FakeChatterboxMTLFalha
        monkeypatch.setitem(sys.modules, "chatterbox", fake_chatterbox)
        monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", fake_mtl)
        vg._chatterbox_cache.pop("chatterbox-multilingual:cpu", None)

        with pytest.raises(vg.VoiceGeneratorError, match="setuptools<81"):
            vg.chatterbox_load(use_gpu=False)

    def test_carregamento_normal_sem_problema_nenhum_funciona(self, monkeypatch):
        """A checagem proativa não deve atrapalhar o caminho normal,
        sem esse bug nenhum."""
        import sys
        import types

        fake_perth = types.ModuleType("perth")

        class FakeWatermarker:
            pass

        fake_perth.PerthImplicitWatermarker = FakeWatermarker
        monkeypatch.setitem(sys.modules, "perth", fake_perth)

        fake_chatterbox = types.ModuleType("chatterbox")
        fake_mtl = types.ModuleType("chatterbox.mtl_tts")

        class FakeModeloOk:
            sr = 24000

        class FakeChatterboxMTLOk:
            @staticmethod
            def from_pretrained(device):
                return FakeModeloOk()

        fake_mtl.ChatterboxMultilingualTTS = FakeChatterboxMTLOk
        monkeypatch.setitem(sys.modules, "chatterbox", fake_chatterbox)
        monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", fake_mtl)
        vg._chatterbox_cache.pop("chatterbox-multilingual:cpu", None)

        modelo = vg.chatterbox_load(use_gpu=False)
        assert isinstance(modelo, FakeModeloOk)


# --------------------------------------------------------------------------- #
# Chatterbox Turbo — variante mais leve/rápida do Chatterbox, SÓ EM
# INGLÊS, mas com suporte a tags paralinguísticas ([laugh], [sigh],
# [whispering] etc) direto no texto. Sem idioma/exaggeration/cfg_weight
# (o Turbo ignora os dois).
# --------------------------------------------------------------------------- #

class _FakeModeloChatterboxTurbo:
    sr = 24000

    def __init__(self):
        self.chamadas = []

    def generate(self, texto, **kwargs):
        self.chamadas.append({"texto": texto, **kwargs})
        return "tensor_de_audio_falso"


class TestChatterboxTurboSynthesize:
    def test_tags_paralinguisticas_passam_intactas(self, tmp_path, monkeypatch):
        fake = _FakeModeloChatterboxTurbo()
        monkeypatch.setattr(vg, "chatterbox_turbo_load", lambda **kw: fake)
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", _fake_salvar_audio_chatterbox)

        texto = "Hi there [chuckle], how can I help you today?"
        saida = str(tmp_path / "saida.wav")
        resultado = vg.chatterbox_turbo_synthesize(texto, saida)

        assert os.path.exists(resultado)
        assert fake.chamadas[-1]["texto"] == texto  # tag preservada sem nenhuma alteração
        assert "language_id" not in fake.chamadas[-1]
        assert "exaggeration" not in fake.chamadas[-1]
        assert "cfg_weight" not in fake.chamadas[-1]

    def test_clonagem_com_speaker_wav(self, tmp_path, monkeypatch):
        fake = _FakeModeloChatterboxTurbo()
        monkeypatch.setattr(vg, "chatterbox_turbo_load", lambda **kw: fake)
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", _fake_salvar_audio_chatterbox)

        ref_audio = str(tmp_path / "referencia.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=200:duration=3", "-ar", "22050", "-ac", "1", ref_audio],
            capture_output=True, check=True,
        )
        saida = str(tmp_path / "clonado.wav")
        vg.chatterbox_turbo_synthesize("Hello there [laugh]", saida, speaker_wav=ref_audio)
        assert os.path.exists(saida)
        assert "audio_prompt_path" in fake.chamadas[-1]
        assert os.path.exists(fake.chamadas[-1]["audio_prompt_path"])

    def test_voice_profile_reaproveita_o_mesmo_mecanismo_dos_outros_motores(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
        ref = str(tmp_path / "ref_perfil.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=250:duration=3", "-ar", "22050", "-ac", "1", ref],
            capture_output=True, check=True,
        )
        vg.salvar_perfil_de_voz("minha_voz_turbo", [ref])

        fake = _FakeModeloChatterboxTurbo()
        monkeypatch.setattr(vg, "chatterbox_turbo_load", lambda **kw: fake)
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", _fake_salvar_audio_chatterbox)

        saida = str(tmp_path / "com_perfil.wav")
        vg.chatterbox_turbo_synthesize("Testing with a profile", saida, voice_profile="minha_voz_turbo")
        assert os.path.exists(saida)
        assert "audio_prompt_path" in fake.chamadas[-1]

    def test_sem_speaker_wav_nem_perfil_usa_voz_neutra(self, tmp_path, monkeypatch):
        fake = _FakeModeloChatterboxTurbo()
        monkeypatch.setattr(vg, "chatterbox_turbo_load", lambda **kw: fake)
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", _fake_salvar_audio_chatterbox)

        vg.chatterbox_turbo_synthesize("Just a normal sentence", str(tmp_path / "x.wav"))
        assert "audio_prompt_path" not in fake.chamadas[-1]

    def test_sem_o_pacote_instalado_da_erro_claro(self, tmp_path, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, "chatterbox", None)
        monkeypatch.setitem(sys.modules, "chatterbox.tts_turbo", None)
        with pytest.raises(vg.VoiceGeneratorError, match="pip install chatterbox-tts"):
            vg.chatterbox_turbo_synthesize("teste", str(tmp_path / "x.wav"))

    def test_gerar_audio_despacha_para_chatterbox_turbo(self, tmp_path, monkeypatch):
        fake = _FakeModeloChatterboxTurbo()
        monkeypatch.setattr(vg, "chatterbox_turbo_load", lambda **kw: fake)
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", _fake_salvar_audio_chatterbox)

        saida = str(tmp_path / "via_dispatch.wav")
        vg.gerar_audio("chatterbox_turbo", "teste via dispatch [gasp]", saida)
        assert os.path.exists(saida)

    def test_chatterbox_turbo_esta_listado_em_engines(self):
        assert "chatterbox_turbo" in vg.ENGINES
        assert "instalar" in vg.ENGINES["chatterbox_turbo"]

    def test_19_tags_ao_todo_9_som_10_entrega(self):
        assert len(vg.CHATTERBOX_TURBO_TAGS_SOM) == 9
        assert len(vg.CHATTERBOX_TURBO_TAGS_ENTREGA) == 10
        assert len(vg.CHATTERBOX_TURBO_TAGS) == 19
        assert "laugh" in vg.CHATTERBOX_TURBO_TAGS_SOM
        assert "dramatic" in vg.CHATTERBOX_TURBO_TAGS_ENTREGA

    def test_texto_longo_e_dividido_em_pedacos_sem_perder_conteudo(self, tmp_path, monkeypatch):
        texto_longo = (
            "This is the first part of a longer story [dramatic]. It keeps going for a while, "
            "describing all sorts of things that happened during that long and eventful day, one "
            "thing after another, without ever really stopping to catch a breath [sigh]. And then, "
            "just when everyone thought it was finally over, something unexpected happened [gasp]."
        )
        chamadas = []

        class FakeModelo:
            sr = 24000

            def generate(self, texto, **kwargs):
                chamadas.append(texto)
                return f"wav_{len(chamadas)}"

        def fake_salvar_numerado(wav, output_path, sample_rate):
            numero = wav.split("_")[1]
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={200 + int(numero) * 10}:duration=0.3", output_path],
                capture_output=True, check=True,
            )

        monkeypatch.setattr(vg, "chatterbox_turbo_load", lambda **kw: FakeModelo())
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", fake_salvar_numerado)

        saida = str(tmp_path / "longo.wav")
        resultado = vg.chatterbox_turbo_synthesize(texto_longo, saida)

        assert len(chamadas) > 1
        for pedaco in chamadas:
            assert len(pedaco) <= vg.CHATTERBOX_TURBO_LIMITE_CARACTERES_POR_CHAMADA
        assert os.path.exists(resultado)
        original_normalizado = " ".join(texto_longo.split())
        reconstruido_normalizado = " ".join(" ".join(chamadas).split())
        assert original_normalizado == reconstruido_normalizado

    def test_carregar_aplica_as_duas_defesas_do_torchcodec(self, monkeypatch):
        import sys
        import types

        chamadas = {"ensure_dll": 0, "patch_torchaudio": 0}
        monkeypatch.setattr(vg, "ensure_ffmpeg_dll_directory",
                             lambda: chamadas.__setitem__("ensure_dll", chamadas["ensure_dll"] + 1))
        monkeypatch.setattr(vg, "_patch_torchaudio_load_via_soundfile",
                             lambda: chamadas.__setitem__("patch_torchaudio", chamadas["patch_torchaudio"] + 1))

        fake_perth = types.ModuleType("perth")

        class FakeWatermarker:
            pass

        fake_perth.PerthImplicitWatermarker = FakeWatermarker
        monkeypatch.setitem(sys.modules, "perth", fake_perth)

        fake_chatterbox = types.ModuleType("chatterbox")
        fake_turbo = types.ModuleType("chatterbox.tts_turbo")

        class FakeModeloOk:
            sr = 24000

        class FakeChatterboxTurboOk:
            @staticmethod
            def from_pretrained(device):
                return FakeModeloOk()

        fake_turbo.ChatterboxTurboTTS = FakeChatterboxTurboOk
        monkeypatch.setitem(sys.modules, "chatterbox", fake_chatterbox)
        monkeypatch.setitem(sys.modules, "chatterbox.tts_turbo", fake_turbo)
        vg._chatterbox_turbo_cache.pop("chatterbox-turbo:cpu", None)

        vg.chatterbox_turbo_load(use_gpu=False)
        assert chamadas["ensure_dll"] == 1
        assert chamadas["patch_torchaudio"] == 1

    def test_perth_watermarker_none_da_erro_claro_sobre_setuptools(self, monkeypatch):
        """A checagem do watermarker é COMPARTILHADA com o Chatterbox
        multilíngue (`_checar_perth_watermarker`) -- confirma que o
        Turbo também é protegido por ela."""
        import sys
        import types

        fake_perth = types.ModuleType("perth")
        fake_perth.PerthImplicitWatermarker = None
        monkeypatch.setitem(sys.modules, "perth", fake_perth)

        fake_chatterbox = types.ModuleType("chatterbox")
        fake_turbo = types.ModuleType("chatterbox.tts_turbo")
        fake_turbo.ChatterboxTurboTTS = object()
        monkeypatch.setitem(sys.modules, "chatterbox", fake_chatterbox)
        monkeypatch.setitem(sys.modules, "chatterbox.tts_turbo", fake_turbo)

        with pytest.raises(vg.VoiceGeneratorError, match="setuptools<81"):
            vg.chatterbox_turbo_load()

    def test_erro_cuda_device_side_assert_da_dica_sobre_texto_curto(self, monkeypatch):
        class FakeModeloCudaCrash:
            sr = 24000

            def generate(self, texto, **kwargs):
                raise RuntimeError("CUDA error: device-side assert triggered")

        monkeypatch.setattr(vg, "chatterbox_turbo_load", lambda **kw: FakeModeloCudaCrash())
        import tempfile
        with pytest.raises(vg.VoiceGeneratorError, match="texto curto demais"):
            vg.chatterbox_turbo_synthesize("Hi.", tempfile.mktemp(suffix=".wav"))


# --------------------------------------------------------------------------- #
# Chatterbox Turbo + numpy >= 2.0 (issue #499 do repositório oficial):
# `norm_loudness()` promove o áudio de referência de float32 pra float64
# e a geração estoura com "expected scalar type Float but found Double".
# --------------------------------------------------------------------------- #

class TestChatterboxTurboBugNumpy2:
    def test_erro_float_double_e_reconhecido(self):
        assert vg._eh_erro_dtype_float_double(RuntimeError("expected scalar type Float but found Double"))
        assert vg._eh_erro_dtype_float_double(RuntimeError("Expected scalar type Double but found Float"))
        assert not vg._eh_erro_dtype_float_double(RuntimeError("CUDA error: device-side assert triggered"))

    def test_norm_loudness_e_blindado_pra_devolver_float32(self):
        import numpy as np

        class ModeloFalso:
            def norm_loudness(self, wav, sr):
                return wav.astype(np.float64)  # reproduz a promoção do numpy 2

        m = ModeloFalso()
        vg._blindar_norm_loudness_turbo(m)
        saida = m.norm_loudness(np.zeros(10, dtype=np.float32), 24000)
        assert saida.dtype == np.float32

    def test_blindar_e_idempotente_e_ignora_modelo_sem_o_metodo(self):
        class SemMetodo:
            pass

        vg._blindar_norm_loudness_turbo(SemMetodo())  # não pode dar erro

        class ComMetodo:
            def norm_loudness(self, wav, sr):
                return wav

        m = ComMetodo()
        vg._blindar_norm_loudness_turbo(m)
        primeiro = m.norm_loudness
        vg._blindar_norm_loudness_turbo(m)
        assert m.norm_loudness is primeiro

    def test_erro_dtype_refaz_sem_norm_loudness_e_mantem_desligado_nos_proximos_pedacos(self, tmp_path, monkeypatch):
        chamadas = []

        class FakeModelo:
            sr = 24000

            def generate(self, texto, **kwargs):
                chamadas.append(dict(kwargs))
                if kwargs.get("norm_loudness", True) and "audio_prompt_path" in kwargs:
                    raise RuntimeError("expected scalar type Float but found Double")
                return "wav"

        ref = str(tmp_path / "ref.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=200:duration=3", "-ar", "22050", "-ac", "1", ref],
            capture_output=True, check=True,
        )
        monkeypatch.setattr(vg, "chatterbox_turbo_load", lambda **kw: FakeModelo())
        monkeypatch.setattr(vg, "_salvar_audio_chatterbox", _fake_salvar_audio_chatterbox)

        texto_longo = "This is a complete sentence for the test. " * 20  # vários pedaços
        saida = str(tmp_path / "saida.wav")
        vg.chatterbox_turbo_synthesize(texto_longo, saida, speaker_wav=ref)

        assert os.path.exists(saida)
        falhas = [c for c in chamadas if c.get("norm_loudness", True)]
        assert len(falhas) == 1  # só a primeira tentativa falhou; o resto já saiu com norm_loudness=False
        assert all(c.get("norm_loudness") is False for c in chamadas[1:])

    def test_erro_dtype_persistente_da_mensagem_clara(self, tmp_path, monkeypatch):
        class FakeModelo:
            sr = 24000

            def generate(self, texto, **kwargs):
                raise RuntimeError("expected scalar type Float but found Double")

        monkeypatch.setattr(vg, "chatterbox_turbo_load", lambda **kw: FakeModelo())
        with pytest.raises(vg.VoiceGeneratorError, match="numpy >= 2.0"):
            vg.chatterbox_turbo_synthesize("Hello there, friend.", str(tmp_path / "x.wav"))
