"""
Teste automatizado de whisper_transcribe.py.

A transcrição de fala em si (modelo Whisper) não é testada aqui com
áudio real de voz — baixar o modelo e rodar inferência é pesado demais
pra um teste automatizado de unidade, e depende de rede na primeira
execução. O que É testado automaticamente:

  - get_audio_duration(): via ffprobe, 100% real, sem mock.
  - Tratamento de erros: arquivo inexistente, tanto pra
    transcribe_audio() quanto get_audio_duration().
  - _get_model(): mockado, confirma que o cache de modelo funciona
    (carrega uma vez só) e que o erro de pacote não instalado é claro.
"""
import pytest

from whisper_transcribe import TranscriptionError, get_audio_duration, transcribe_audio


class TestGetAudioDuration:
    def test_returns_correct_duration_for_real_file(self, synthetic_audio):
        duration = get_audio_duration(synthetic_audio)
        assert abs(duration - 9.469) < 0.05

    def test_raises_clear_error_for_missing_file(self):
        with pytest.raises(TranscriptionError, match="não encontrado"):
            get_audio_duration("/tmp/isso_nao_existe_de_verdade.wav")


class TestTranscribeAudio:
    def test_raises_clear_error_for_missing_file(self):
        with pytest.raises(TranscriptionError, match="não encontrado"):
            transcribe_audio("/tmp/isso_nao_existe_de_verdade.mp3")

    def test_raises_clear_error_when_whisper_not_installed(self, synthetic_audio, monkeypatch):
        import whisper_transcribe

        # Simula o pacote 'whisper' não instalado, sem precisar
        # desinstalar de verdade (o que quebraria outros testes).
        monkeypatch.setitem(whisper_transcribe._MODEL_CACHE, "base", None)
        whisper_transcribe._MODEL_CACHE.clear()

        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "whisper":
                raise ImportError("simulado: whisper não instalado")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(TranscriptionError, match="openai-whisper"):
            transcribe_audio(synthetic_audio)

    def test_model_is_loaded_only_once_and_cached(self, monkeypatch):
        import whisper_transcribe

        whisper_transcribe._MODEL_CACHE.clear()
        load_calls = []

        class FakeModel:
            def transcribe(self, path, **kwargs):
                return {"segments": [{"start": 0.0, "end": 1.0, "text": "oi"}]}

        class FakeWhisperModule:
            @staticmethod
            def load_model(size, device=None):
                load_calls.append(size)
                return FakeModel()

        import sys
        monkeypatch.setitem(sys.modules, "whisper", FakeWhisperModule())

        model1 = whisper_transcribe._get_model("base")
        model2 = whisper_transcribe._get_model("base")
        assert model1 is model2
        assert load_calls == ["base"], "deveria ter carregado o modelo só uma vez (cache)"

    def test_transcribe_returns_segments_with_expected_shape(self, synthetic_audio, monkeypatch):
        import whisper_transcribe
        whisper_transcribe._MODEL_CACHE.clear()

        class FakeModel:
            def transcribe(self, path, **kwargs):
                return {
                    "segments": [
                        {"start": 0.0, "end": 3.2, "text": "  Bem-vindos ao vídeo.  "},
                        {"start": 3.2, "end": 6.0, "text": "Fim."},
                        {"start": 6.0, "end": 6.5, "text": "   "},  # vazio -> deve ser filtrado
                    ]
                }

        import sys

        class FakeWhisperModule:
            @staticmethod
            def load_model(size, device=None):
                return FakeModel()

        monkeypatch.setitem(sys.modules, "whisper", FakeWhisperModule())

        segments = transcribe_audio(synthetic_audio, model_size="base")
        assert len(segments) == 2, "o segmento com texto vazio/só espaço deveria ter sido filtrado"
        assert segments[0] == {"start": 0.0, "end": 3.2, "text": "Bem-vindos ao vídeo."}
        assert segments[1]["text"] == "Fim."

    def test_word_timestamps_included_when_requested(self, synthetic_audio, monkeypatch):
        import whisper_transcribe
        whisper_transcribe._MODEL_CACHE.clear()

        class FakeModel:
            def transcribe(self, path, **kwargs):
                assert kwargs.get("word_timestamps") is True
                return {
                    "segments": [{
                        "start": 0.0, "end": 2.0, "text": "Olá mundo",
                        "words": [
                            {"word": "Olá", "start": 0.0, "end": 0.8},
                            {"word": "mundo", "start": 0.9, "end": 1.8},
                        ],
                    }]
                }

        import sys

        class FakeWhisperModule:
            @staticmethod
            def load_model(size, device=None):
                return FakeModel()

        monkeypatch.setitem(sys.modules, "whisper", FakeWhisperModule())

        segments = transcribe_audio(synthetic_audio, word_timestamps=True)
        assert segments[0]["words"] == [
            {"word": "Olá", "start": 0.0, "end": 0.8},
            {"word": "mundo", "start": 0.9, "end": 1.8},
        ]

    def test_no_words_key_when_word_timestamps_not_requested(self, synthetic_audio, monkeypatch):
        import whisper_transcribe
        whisper_transcribe._MODEL_CACHE.clear()

        class FakeModel:
            def transcribe(self, path, **kwargs):
                assert "word_timestamps" not in kwargs
                return {"segments": [{"start": 0.0, "end": 2.0, "text": "Olá mundo"}]}

        import sys

        class FakeWhisperModule:
            @staticmethod
            def load_model(size, device=None):
                return FakeModel()

        monkeypatch.setitem(sys.modules, "whisper", FakeWhisperModule())

        segments = transcribe_audio(synthetic_audio, word_timestamps=False)
        assert "words" not in segments[0]
        assert segments[0] == {"start": 0.0, "end": 2.0, "text": "Olá mundo"}

    def test_raises_clear_error_when_no_speech_found(self, synthetic_audio, monkeypatch):
        import whisper_transcribe
        whisper_transcribe._MODEL_CACHE.clear()

        class FakeModel:
            def transcribe(self, path, **kwargs):
                return {"segments": [{"start": 0.0, "end": 1.0, "text": "   "}]}  # só espaço

        import sys

        class FakeWhisperModule:
            @staticmethod
            def load_model(size, device=None):
                return FakeModel()

        monkeypatch.setitem(sys.modules, "whisper", FakeWhisperModule())

        with pytest.raises(TranscriptionError, match="nenhuma fala"):
            transcribe_audio(synthetic_audio)


class TestDeviceSelection:
    """Cobre a seleção de GPU/CPU pro Whisper: detecção automática,
    cache separado por dispositivo, e fallback pra CPU quando a GPU
    pedida falha ao carregar (driver quebrado, sem VRAM suficiente,
    etc.) em vez de travar a transcrição inteira."""

    def test_detect_best_device_returns_cpu_or_cuda(self):
        import whisper_transcribe
        device = whisper_transcribe.detect_best_device()
        assert device in ("cpu", "cuda")

    def test_resolve_device_maps_auto_gpu_cpu(self):
        import whisper_transcribe as wt
        assert wt._resolve_device("cpu") == "cpu"
        assert wt._resolve_device("gpu") == "cuda"
        assert wt._resolve_device("auto") == wt.detect_best_device()

    def test_model_cache_is_separate_per_device(self, monkeypatch):
        import sys
        import whisper_transcribe as wt
        wt._MODEL_CACHE.clear()

        load_calls = []

        class FakeModel:
            def __init__(self, name):
                self.name = name

        class FakeWhisperModule:
            @staticmethod
            def load_model(size, device=None):
                load_calls.append((size, device))
                return FakeModel(f"{size}-{device}")

        monkeypatch.setitem(sys.modules, "whisper", FakeWhisperModule())

        m1 = wt._get_model("base", device="cpu")
        m2 = wt._get_model("base", device="gpu")
        assert m1.name == "base-cpu"
        assert m2.name == "base-cuda"
        assert m1 is not m2
        assert load_calls == [("base", "cpu"), ("base", "cuda")]

        m3 = wt._get_model("base", device="cpu")
        assert m3 is m1
        assert len(load_calls) == 2, "não deveria ter recarregado o modelo já em cache"
        wt._MODEL_CACHE.clear()

    def test_falls_back_to_cpu_when_gpu_fails_to_load(self, monkeypatch):
        import sys
        import whisper_transcribe as wt
        wt._MODEL_CACHE.clear()

        class FakeModel:
            def __init__(self, name):
                self.name = name

        class FakeWhisperModuleGpuFails:
            @staticmethod
            def load_model(size, device=None):
                if device == "cuda":
                    raise RuntimeError("CUDA out of memory (simulado)")
                return FakeModel(f"{size}-{device}")

        monkeypatch.setitem(sys.modules, "whisper", FakeWhisperModuleGpuFails())

        model = wt._get_model("base", device="gpu")
        assert model.name == "base-cpu"
        wt._MODEL_CACHE.clear()

    def test_transcribe_audio_passes_device_through(self, synthetic_audio, monkeypatch):
        import sys
        import whisper_transcribe as wt
        wt._MODEL_CACHE.clear()

        received = {}

        class FakeModel:
            def transcribe(self, path, **kwargs):
                return {"segments": [{"start": 0.0, "end": 1.0, "text": "ok"}]}

        class FakeWhisperModule:
            @staticmethod
            def load_model(size, device=None):
                received["device"] = device
                return FakeModel()

        monkeypatch.setitem(sys.modules, "whisper", FakeWhisperModule())

        transcribe_audio(synthetic_audio, device="cpu")
        assert received["device"] == "cpu"
        wt._MODEL_CACHE.clear()
