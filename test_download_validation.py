"""
Teste automatizado de `_validate_downloaded_file()` — resolve um bug
real relatado em produção: um provedor às vezes devolve um arquivo
"baixado com sucesso" (sem erro de rede) que na verdade está vazio,
truncado, ou é uma página de erro HTML salva com extensão .mp4/.jpg.
Sem validar isso logo após o download, o problema só aparecia bem mais
tarde (na montagem final), derrubando o job inteiro por causa de UM
segmento em vez de já tentar o próximo candidato automaticamente.
"""
import os
import shutil
import subprocess

import pytest
from PIL import Image

from prompt_builder import VideoSegment
from video_assembler import (
    VideoAssemblyError,
    _download_first_working_result,
    _search_and_download_photo,
    _validate_downloaded_file,
)


class TestValidateDownloadedFile:
    def test_rejects_empty_file(self, tmp_path):
        path = str(tmp_path / "vazio.mp4")
        open(path, "wb").close()
        with pytest.raises(VideoAssemblyError, match="vazio ou não existe"):
            _validate_downloaded_file(path)

    def test_rejects_missing_file(self, tmp_path):
        with pytest.raises(VideoAssemblyError, match="vazio ou não existe"):
            _validate_downloaded_file(str(tmp_path / "nao_existe.mp4"))

    def test_rejects_html_error_page_saved_as_mp4(self, tmp_path):
        """O cenário real relatado: o provedor devolve uma página de
        erro (404, bloqueio, etc.) que é salva com extensão .mp4 sem
        ninguém perceber que não é um vídeo de verdade."""
        path = str(tmp_path / "parece_video.mp4")
        with open(path, "w") as f:
            f.write("<html><body>404 Not Found</body></html>" * 20)
        with pytest.raises(VideoAssemblyError, match="corrompido/inválido|Não consegui ler a duração"):
            _validate_downloaded_file(path)

    def test_rejects_corrupted_image(self, tmp_path):
        path = str(tmp_path / "foto.jpg")
        with open(path, "wb") as f:
            f.write(b"nao sou uma imagem de verdade" * 10)
        with pytest.raises(VideoAssemblyError, match="corrompido/inválido"):
            _validate_downloaded_file(path)

    def test_accepts_valid_video(self, tmp_path):
        path = str(tmp_path / "valido.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25:duration=2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", path], check=True,
        )
        _validate_downloaded_file(path)  # não deve levantar nada

    def test_accepts_valid_image(self, tmp_path):
        path = str(tmp_path / "valida.jpg")
        Image.new("RGB", (200, 150), (0, 128, 0)).save(path)
        _validate_downloaded_file(path)  # não deve levantar nada


class TestAutomaticRetryOnCorruptedDownload:
    """Confirma que a validação está de fato CONECTADA aos mecanismos
    de retry existentes — um resultado corrompido não derruba o
    segmento, só faz pular pro próximo candidato automaticamente."""

    def test_video_retry_skips_corrupted_result_and_uses_next(self, tmp_path):
        valid_clip = str(tmp_path / "fonte_valida.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=320x240:rate=25:duration=2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", valid_clip], check=True,
        )

        download_attempts = []

        class FakeVideo:
            def __init__(self, video_id):
                self.id = video_id
                self.premium = False

        class FakeClient:
            def download_video(self, video, output_dir, **kw):
                download_attempts.append(video.id)
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{video.id}.mp4")
                if video.id == "corrompido":
                    with open(dest, "w") as f:
                        f.write("<html>erro 404</html>" * 20)
                else:
                    shutil.copy(valid_clip, dest)
                return dest

        videos = [FakeVideo("corrompido"), FakeVideo("bom")]
        segment = VideoSegment(start=0.0, end=2.0, provider="pexels", query="x")
        path = _download_first_working_result(segment, videos, FakeClient(), str(tmp_path / "downloads"))

        assert download_attempts == ["corrompido", "bom"]
        assert "bom.mp4" in path

    def test_all_results_corrupted_raises_clear_error(self, tmp_path):
        class FakeVideo:
            def __init__(self, video_id):
                self.id = video_id
                self.premium = False

        class FakeAlwaysCorruptedClient:
            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{video.id}.mp4")
                with open(dest, "w") as f:
                    f.write("<html>erro</html>")
                return dest

        videos = [FakeVideo("a"), FakeVideo("b")]
        segment = VideoSegment(start=0.0, end=2.0, provider="pexels", query="x")
        with pytest.raises(VideoAssemblyError, match="Nenhum dos"):
            _download_first_working_result(segment, videos, FakeAlwaysCorruptedClient(), str(tmp_path / "downloads"))

    def test_photo_retry_skips_corrupted_result_and_uses_next(self, tmp_path):
        valid_image = str(tmp_path / "foto_valida.jpg")
        Image.new("RGB", (200, 150), (0, 0, 200)).save(valid_image)

        download_attempts = []

        class FakePhoto:
            def __init__(self, photo_id):
                self.id = photo_id

        class FakePhotoClient:
            def search_photos_all(self, query=None, max_pages=1, **kw):
                return [FakePhoto("corrompida"), FakePhoto("boa")]

            def download_photo(self, photo, output_dir, **kw):
                download_attempts.append(photo.id)
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, f"{photo.id}.jpg")
                if photo.id == "corrompida":
                    with open(dest, "wb") as f:
                        f.write(b"lixo, nao e imagem" * 5)
                else:
                    shutil.copy(valid_image, dest)
                return dest

        segment = VideoSegment(start=0.0, end=2.0, provider="pexels", query="x", media_type="image")
        path = _search_and_download_photo(segment, str(tmp_path / "downloads"), FakePhotoClient())

        assert download_attempts == ["corrompida", "boa"]
        assert "boa.jpg" in path
