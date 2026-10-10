"""
Testes de transcrever_avulso.py — ffmpeg/ffprobe de verdade (vídeos
curtos gerados na hora), mas o download (youtube_clipper.baixar_video /
redes_sociais.baixar_video) e a transcrição (whisper_transcribe.transcribe_audio)
são sempre FALSOS/injetados, pra não depender de internet nem do Whisper
de verdade (pesado e lento demais pra teste).
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_TOOLKIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit")
if _TOOLKIT not in sys.path:
    sys.path.insert(0, _TOOLKIT)

import transcrever_avulso as ta  # noqa: E402
import youtube_clipper  # noqa: E402
import redes_sociais  # noqa: E402
import whisper_transcribe  # noqa: E402


@pytest.fixture(scope="module")
def video_720p():
    import tempfile
    caminho = os.path.join(tempfile.mkdtemp(prefix="ta_video_"), "original.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:duration=2:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", caminho],
        capture_output=True, check=True,
    )
    return caminho


@pytest.fixture(scope="module")
def video_360p():
    import tempfile
    caminho = os.path.join(tempfile.mkdtemp(prefix="ta_video_baixa_"), "original.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=480x360:duration=2:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", caminho],
        capture_output=True, check=True,
    )
    return caminho


_SEGMENTOS_FALSOS = [
    {"start": 0.0, "end": 1.0, "text": "Olá mundo."},
    {"start": 1.0, "end": 2.0, "text": "Segunda fala."},
]


def _transcribe_audio_falso(audio_path, model_size="base", language=None, word_timestamps=False, device="auto"):
    assert os.path.exists(audio_path)
    return list(_SEGMENTOS_FALSOS)


# --------------------------------------------------------------------------- #
# helpers internos (ffmpeg/ffprobe de verdade)
# --------------------------------------------------------------------------- #
class TestHelpersInternos:
    def test_dimensoes_do_video(self, video_720p):
        assert ta._dimensoes_do_video(video_720p) == (1280, 720)

    def test_dimensoes_de_arquivo_invalido_devolve_none(self, tmp_path):
        caminho = tmp_path / "nao_e_video.mp4"
        caminho.write_bytes(b"lixo")
        assert ta._dimensoes_do_video(str(caminho)) is None

    def test_extrair_audio_gera_wav(self, video_720p, tmp_path):
        audio_out = str(tmp_path / "audio.wav")
        ta._extrair_audio(video_720p, audio_out)
        assert os.path.exists(audio_out) and os.path.getsize(audio_out) > 0

    def test_extrair_audio_de_video_invalido_da_erro_claro(self, tmp_path):
        video_ruim = tmp_path / "nao_e_video.mp4"
        video_ruim.write_bytes(b"lixo")
        with pytest.raises(ta.TranscreverAvulsoError, match="ffmpeg"):
            ta._extrair_audio(str(video_ruim), str(tmp_path / "audio.wav"))

    def test_escrever_srt_formata_tempo_e_numera(self, tmp_path):
        caminho = tmp_path / "out.srt"
        ta._escrever_srt([
            {"start": 0.0, "end": 1.5, "text": "Primeira."},
            {"start": 61.25, "end": 63.0, "text": "Depois de um minuto."},
        ], str(caminho))
        conteudo = caminho.read_text(encoding="utf-8")
        assert "1\n00:00:00,000 --> 00:00:01,500\nPrimeira." in conteudo
        assert "2\n00:01:01,250 --> 00:01:03,000\nDepois de um minuto." in conteudo


# --------------------------------------------------------------------------- #
# processar() — modo "baixar" (arquivo enviado)
# --------------------------------------------------------------------------- #
class TestProcessarComArquivoEnviado:
    def test_modo_baixar_so_copia_sem_transcrever(self, video_720p, tmp_path, monkeypatch):
        chamou_transcricao = []
        monkeypatch.setattr(ta, "TranscreverAvulsoError", ta.TranscreverAvulsoError)
        import whisper_transcribe
        monkeypatch.setattr(whisper_transcribe, "transcribe_audio", lambda *a, **k: chamou_transcricao.append(1) or [])
        saida = str(tmp_path / "saida")
        r = ta.processar(saida, arquivo_path=video_720p, modo="baixar")
        assert r["modo"] == "baixar" and r["video"] == "video.mp4"
        assert os.path.exists(os.path.join(saida, "video.mp4"))
        assert not chamou_transcricao
        assert "segmentos" not in r

    def test_modo_transcrever_com_arquivo_enviado(self, video_720p, tmp_path, monkeypatch):
        import whisper_transcribe
        monkeypatch.setattr(whisper_transcribe, "transcribe_audio", _transcribe_audio_falso)
        saida = str(tmp_path / "saida")
        r = ta.processar(saida, arquivo_path=video_720p, modo="transcrever")
        assert r["total_segmentos"] == 2
        assert r["segmentos"] == _SEGMENTOS_FALSOS
        assert (r["largura"], r["altura"]) == (1280, 720)
        assert r["aviso_resolucao_baixa"] is False
        assert os.path.exists(os.path.join(saida, "transcricao.txt"))
        assert os.path.exists(os.path.join(saida, "transcricao.srt"))
        assert os.path.exists(os.path.join(saida, "transcricao.json"))
        assert not os.path.exists(os.path.join(saida, "audio.wav"))  # apagado no final
        with open(os.path.join(saida, "transcricao.json"), encoding="utf-8") as f:
            assert json.load(f) == _SEGMENTOS_FALSOS

    def test_texto_txt_junta_os_segmentos(self, video_720p, tmp_path, monkeypatch):
        import whisper_transcribe
        monkeypatch.setattr(whisper_transcribe, "transcribe_audio", _transcribe_audio_falso)
        saida = str(tmp_path / "saida")
        ta.processar(saida, arquivo_path=video_720p, modo="transcrever")
        texto = open(os.path.join(saida, "transcricao.txt"), encoding="utf-8").read()
        assert texto == "Olá mundo.\nSegunda fala."

    def test_avisa_resolucao_baixa(self, video_360p, tmp_path, monkeypatch):
        import whisper_transcribe
        monkeypatch.setattr(whisper_transcribe, "transcribe_audio", _transcribe_audio_falso)
        logs = []
        r = ta.processar(str(tmp_path / "saida"), arquivo_path=video_360p, modo="transcrever", on_log=logs.append)
        assert r["aviso_resolucao_baixa"] is True
        assert any("baixa resolução" in linha for linha in logs)

    def test_idioma_forcado_aparece_no_resultado(self, video_720p, tmp_path, monkeypatch):
        import whisper_transcribe
        monkeypatch.setattr(whisper_transcribe, "transcribe_audio", _transcribe_audio_falso)
        r = ta.processar(str(tmp_path / "saida"), arquivo_path=video_720p, modo="transcrever", idioma="en")
        assert r["idioma"] == "en"

    def test_idioma_nao_forcado_fica_none(self, video_720p, tmp_path, monkeypatch):
        import whisper_transcribe
        monkeypatch.setattr(whisper_transcribe, "transcribe_audio", _transcribe_audio_falso)
        r = ta.processar(str(tmp_path / "saida"), arquivo_path=video_720p, modo="transcrever")
        assert r["idioma"] is None

    def test_arquivo_inexistente_da_erro_claro(self, tmp_path):
        with pytest.raises(ta.TranscreverAvulsoError, match="não encontrado"):
            ta.processar(str(tmp_path / "saida"), arquivo_path=str(tmp_path / "fantasma.mp4"))


# --------------------------------------------------------------------------- #
# validações de parâmetros
# --------------------------------------------------------------------------- #
class TestValidacoes:
    def test_sem_url_e_sem_arquivo_da_erro(self, tmp_path):
        with pytest.raises(ta.TranscreverAvulsoError, match="Informe exatamente um"):
            ta.processar(str(tmp_path))

    def test_url_e_arquivo_juntos_da_erro(self, tmp_path, video_720p):
        with pytest.raises(ta.TranscreverAvulsoError, match="Informe exatamente um"):
            ta.processar(str(tmp_path), url="https://x", arquivo_path=video_720p)

    def test_modo_invalido_da_erro(self, tmp_path, video_720p):
        with pytest.raises(ta.TranscreverAvulsoError, match="inválido"):
            ta.processar(str(tmp_path), arquivo_path=video_720p, modo="resumir")


# --------------------------------------------------------------------------- #
# processar() — baixar de uma URL (YouTube vs. outras redes)
# --------------------------------------------------------------------------- #
class TestProcessarComUrl:
    def test_youtube_usa_youtube_clipper(self, video_720p, tmp_path, monkeypatch):
        chamadas = []

        def _fake_baixar(url, output_dir, qualidade="1080p", ytdlp_module=None):
            chamadas.append((url, qualidade))
            import shutil
            destino = os.path.join(output_dir, "abc123.mp4")
            shutil.copy(video_720p, destino)
            return {"caminho": destino, "titulo": "Vídeo", "duracao_segundos": 2.0, "url": url, "id": "abc123"}

        monkeypatch.setattr(youtube_clipper, "baixar_video", _fake_baixar)
        import whisper_transcribe
        monkeypatch.setattr(whisper_transcribe, "transcribe_audio", _transcribe_audio_falso)
        r = ta.processar(str(tmp_path / "saida"), url="https://www.youtube.com/watch?v=abc123", modo="transcrever")
        assert chamadas == [("https://www.youtube.com/watch?v=abc123", "1080p")]
        assert r["total_segmentos"] == 2
        assert os.path.exists(os.path.join(tmp_path / "saida", "video.mp4"))

    def test_youtube_com_teto_de_altura_escolhe_qualidade_mais_proxima(self, video_720p, tmp_path, monkeypatch):
        chamadas = []

        def _fake_baixar(url, output_dir, qualidade="1080p", ytdlp_module=None):
            chamadas.append(qualidade)
            import shutil
            destino = os.path.join(output_dir, "x.mp4")
            shutil.copy(video_720p, destino)
            return {"caminho": destino, "titulo": "x", "duracao_segundos": 1.0, "url": url, "id": "x"}

        monkeypatch.setattr(youtube_clipper, "baixar_video", _fake_baixar)
        ta.processar(str(tmp_path / "saida"), url="https://youtu.be/x", modo="baixar", max_height=720)
        assert chamadas == ["720p"]

    def test_tiktok_usa_redes_sociais(self, video_720p, tmp_path, monkeypatch):
        chamadas = []

        def _fake_baixar(url, pasta_destino, ytdlp_module=None, requests_module=None):
            chamadas.append(url)
            import shutil
            destino = os.path.join(pasta_destino, "original.mp4")
            shutil.copy(video_720p, destino)
            return destino

        monkeypatch.setattr(redes_sociais, "baixar_video", _fake_baixar)
        import whisper_transcribe
        monkeypatch.setattr(whisper_transcribe, "transcribe_audio", _transcribe_audio_falso)
        r = ta.processar(str(tmp_path / "saida"), url="https://www.tiktok.com/@u/video/1", modo="transcrever")
        assert chamadas == ["https://www.tiktok.com/@u/video/1"]
        assert r["total_segmentos"] == 2

    def test_erro_do_youtube_clipper_vira_transcreveravulsoerror(self, tmp_path, monkeypatch):
        def _fake_baixar(*a, **k):
            raise youtube_clipper.YoutubeClipperError("HTTP Error 403: Forbidden")

        monkeypatch.setattr(youtube_clipper, "baixar_video", _fake_baixar)
        with pytest.raises(ta.TranscreverAvulsoError, match="403"):
            ta.processar(str(tmp_path / "saida"), url="https://youtu.be/x", modo="baixar")

    def test_erro_de_redes_sociais_vira_transcreveravulsoerror(self, tmp_path, monkeypatch):
        def _fake_baixar(*a, **k):
            raise redes_sociais.RedesSociaisError("fonte não suportada")

        monkeypatch.setattr(redes_sociais, "baixar_video", _fake_baixar)
        with pytest.raises(ta.TranscreverAvulsoError, match="fonte não suportada"):
            ta.processar(str(tmp_path / "saida"), url="https://www.instagram.com/reel/x", modo="baixar")

    def test_log_recebe_as_mensagens_de_progresso(self, video_720p, tmp_path, monkeypatch):
        def _fake_baixar(url, output_dir, qualidade="1080p", ytdlp_module=None):
            import shutil
            destino = os.path.join(output_dir, "x.mp4")
            shutil.copy(video_720p, destino)
            return {"caminho": destino, "titulo": "x", "duracao_segundos": 1.0, "url": url, "id": "x"}

        monkeypatch.setattr(youtube_clipper, "baixar_video", _fake_baixar)
        logs = []
        ta.processar(str(tmp_path / "saida"), url="https://youtu.be/x", modo="baixar", on_log=logs.append)
        assert any("YouTube" in linha for linha in logs)
        assert any("Concluído" in linha for linha in logs)
