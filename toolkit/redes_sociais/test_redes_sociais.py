"""
Testes do pacote toolkit.redes_sociais. NÃO baixa nada de verdade nem
acessa a internet — um "yt-dlp" e um "requests"/"bs4" FALSOS são
injetados nos pontos onde o código real chamaria essas bibliotecas
(mesmo padrão usado em test_youtube_clipper.py).
"""
import json
import os
import subprocess
import sys

import pytest

_TOOLKIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _TOOLKIT not in sys.path:
    sys.path.insert(0, os.path.abspath(_TOOLKIT))

from redes_sociais import (  # noqa: E402
    FONTES_SUPORTADAS, NOMES_AMIGAVEIS, RedesSociaisError,
    baixar_video, baixar_video_facebook, baixar_video_instagram,
    baixar_video_kwai, baixar_video_tiktok, baixar_video_twitter,
    obter_dominio, tem_audio, verificar_ytdlp,
)
from redes_sociais.qualidade import checar_qualidade


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def video_teste():
    import tempfile
    caminho = os.path.join(tempfile.mkdtemp(prefix="redes_sociais_video_"), "video.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=5:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=5",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", caminho],
        capture_output=True, check=True,
    )
    return caminho


@pytest.fixture(scope="module")
def video_sem_audio():
    import tempfile
    caminho = os.path.join(tempfile.mkdtemp(prefix="redes_sociais_semaudio_"), "video.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=3:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", caminho],
        capture_output=True, check=True,
    )
    return caminho


class _FakeYoutubeDL:
    """yt-dlp falso -- `.download()` copia um vídeo de teste local pro
    destino esperado (o outtmpl real termina em "original.mp4")."""
    origem_video = None
    erro = None
    opcoes_usadas = None

    def __init__(self, opts):
        self.opts = opts
        _FakeYoutubeDL.opcoes_usadas = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def download(self, urls):
        if self.erro:
            raise self.erro
        destino = self.opts["outtmpl"].replace("%(ext)s", "mp4")
        import shutil
        shutil.copy(self.origem_video, destino)


def _fake_ytdlp_module(video_teste, erro=None):
    fake_cls = type("FakeYoutubeDL", (_FakeYoutubeDL,), {"origem_video": video_teste, "erro": erro})
    return type("FakeYtDlpModule", (), {"YoutubeDL": fake_cls})


class _FakeRespKwaiPagina:
    def __init__(self, texto, status=200):
        self.text = texto
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeRespKwaiVideo:
    def __init__(self, conteudo, status=200):
        self._conteudo = conteudo
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        yield self._conteudo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _html_kwai(content_url, nome="Um vídeo legal) #fy #kwai"):
    dados = {"name": nome, "contentUrl": content_url}
    return f'<html><script id="VideoObject">{json.dumps(dados)}</script></html>'


class _FakeRequestsKwai:
    """`requests` falso: GET na página do Kwai devolve o HTML com o
    <script id="VideoObject">; GET na contentUrl devolve bytes de vídeo
    de teste reais (lidos do disco), pra o ffprobe/tem_audio funcionarem."""

    def __init__(self, video_bytes, pagina_html=None, pagina_status=200, video_status=200, sem_script=False):
        self.video_bytes = video_bytes
        self.pagina_html = pagina_html if pagina_html is not None else _html_kwai("https://cdn.kwai.com/v.mp4")
        if sem_script:
            self.pagina_html = "<html>nada aqui</html>"
        self.pagina_status = pagina_status
        self.video_status = video_status
        self.chamadas = []

    def get(self, url, headers=None, stream=False, timeout=None):
        self.chamadas.append(url)
        if stream:
            return _FakeRespKwaiVideo(self.video_bytes, status=self.video_status)
        return _FakeRespKwaiPagina(self.pagina_html, status=self.pagina_status)


# --------------------------------------------------------------------------- #
# obter_dominio / FONTES_SUPORTADAS
# --------------------------------------------------------------------------- #
class TestObterDominio:
    @pytest.mark.parametrize("url,esperado", [
        ("https://www.tiktok.com/@user/video/123", "tiktok.com"),
        ("https://tiktok.com/@user/video/123", "tiktok.com"),
        ("https://x.com/user/status/123", "x.com"),
        ("https://www.instagram.com/reel/abc/", "instagram.com"),
        ("https://fb.watch/xyz/", "fb.watch"),
        ("https://www.kwai.com/@user/video/123", "kwai.com"),
    ])
    def test_extrai_dominio_limpo(self, url, esperado):
        assert obter_dominio(url) == esperado

    def test_dominio_vazio_quando_url_invalida(self):
        assert obter_dominio("nem-e-uma-url") == "dominio_desconhecido"

    def test_todas_as_fontes_tem_nome_amigavel(self):
        assert set(FONTES_SUPORTADAS) == set(NOMES_AMIGAVEIS)


# --------------------------------------------------------------------------- #
# baixar_video — dispatcher
# --------------------------------------------------------------------------- #
class TestBaixarVideoDispatcher:
    def test_tiktok_usa_o_downloader_certo(self, tmp_path, video_teste):
        caminho = baixar_video("https://www.tiktok.com/@x/video/1", str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        assert os.path.basename(caminho) == "original.mp4"
        assert os.path.exists(caminho)

    def test_instagram_usa_o_downloader_certo(self, tmp_path, video_teste):
        caminho = baixar_video("https://www.instagram.com/reel/x/", str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        assert os.path.exists(caminho)

    def test_twitter_e_x_usam_o_mesmo_downloader(self, tmp_path, video_teste):
        for dominio in ("https://twitter.com/u/status/1", "https://x.com/u/status/1"):
            caminho = baixar_video(dominio, str(tmp_path / dominio[-1]), ytdlp_module=_fake_ytdlp_module(video_teste))
            assert os.path.exists(caminho)

    def test_facebook_e_fb_watch_usam_o_mesmo_downloader(self, tmp_path, video_teste):
        for i, url in enumerate(("https://www.facebook.com/watch/?v=1", "https://fb.watch/abc/")):
            caminho = baixar_video(url, str(tmp_path / str(i)), ytdlp_module=_fake_ytdlp_module(video_teste))
            assert os.path.exists(caminho)

    def test_kwai_usa_requests_nao_ytdlp(self, tmp_path, video_teste):
        with open(video_teste, "rb") as f:
            video_bytes = f.read()
        fake_requests = _FakeRequestsKwai(video_bytes)
        caminho = baixar_video("https://www.kwai.com/@x/video/1", str(tmp_path), requests_module=fake_requests)
        assert os.path.exists(caminho)
        assert len(fake_requests.chamadas) == 2  # página + vídeo

    def test_fonte_nao_suportada_lista_as_disponiveis(self, tmp_path):
        with pytest.raises(RedesSociaisError, match="ainda não é suportada") as exc:  # (YouTube tem a aba própria)
            baixar_video("https://www.youtube.com/watch?v=x", str(tmp_path))
        assert "YouTube" in str(exc.value)  # dica de usar a aba do YouTube

    def test_outros_sites_vao_direto_no_ytdlp(self, tmp_path):
        """🌐 v84_311: Reddit, Pinterest, Vimeo… — o yt-dlp genérico tenta."""
        pedidos = []

        class YDL:
            def __init__(self, o):
                self.o = o

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def download(self, urls):
                pedidos.append(urls[0])
                open(self.o["outtmpl"].replace("%(ext)s", "mp4"), "wb").write(b"x")
        fake = type("M", (), {"YoutubeDL": YDL})
        cam = baixar_video("https://www.reddit.com/r/x/comments/1/a/", str(tmp_path), ytdlp_module=fake)
        assert cam.endswith("original.mp4") and pedidos == ["https://www.reddit.com/r/x/comments/1/a/"]


# --------------------------------------------------------------------------- #
# cada downloader de plataforma, isoladamente
# --------------------------------------------------------------------------- #
class TestDownloadersYtdlp:
    def test_instagram(self, tmp_path, video_teste):
        assert os.path.exists(baixar_video_instagram("https://instagram.com/reel/x", str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste)))

    def test_twitter(self, tmp_path, video_teste):
        assert os.path.exists(baixar_video_twitter("https://x.com/u/status/1", str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste)))

    def test_tiktok(self, tmp_path, video_teste):
        assert os.path.exists(baixar_video_tiktok("https://tiktok.com/@u/video/1", str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste)))

    def test_facebook_usa_headers_e_retries_proprios(self, tmp_path, video_teste):
        caminho = baixar_video_facebook("https://fb.watch/x/", str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        assert os.path.exists(caminho)
        opcoes = _FakeYoutubeDL.opcoes_usadas
        assert opcoes["retries"] == 10 and opcoes["fragment_retries"] == 10
        assert "Chrome/131" in opcoes["http_headers"]["User-Agent"]

    def test_cookies_path_e_repassado(self, tmp_path, video_teste):
        baixar_video_instagram("https://instagram.com/reel/x", str(tmp_path), cookies_path="/tmp/cookies.txt", ytdlp_module=_fake_ytdlp_module(video_teste))
        assert _FakeYoutubeDL.opcoes_usadas["cookiefile"] == "/tmp/cookies.txt"

    def test_erro_do_ytdlp_vira_redessociaiserror_com_dicas(self, tmp_path, video_teste):
        erro = _fake_ytdlp_module(video_teste, erro=RuntimeError("HTTP Error 403: Forbidden"))
        with pytest.raises(RedesSociaisError, match="Erro ao baixar com yt-dlp"):
            baixar_video_tiktok("https://tiktok.com/@u/video/1", str(tmp_path), ytdlp_module=erro)

    def test_erro_de_impersonation_da_dica_do_curl_cffi(self, tmp_path, video_teste):
        erro = _fake_ytdlp_module(video_teste, erro=RuntimeError("no impersonate target is available"))
        with pytest.raises(RedesSociaisError, match="curl_cffi"):
            baixar_video_tiktok("https://tiktok.com/@u/video/1", str(tmp_path), ytdlp_module=erro)

    def test_arquivo_final_ausente_da_erro_claro(self, tmp_path):
        class YtDlpQueNaoBaixaNada:
            class YoutubeDL:
                def __init__(self, opts):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

                def download(self, urls):
                    pass  # não cria nenhum arquivo

        with pytest.raises(RedesSociaisError, match="não encontrei"):
            baixar_video_instagram("https://instagram.com/reel/x", str(tmp_path), ytdlp_module=YtDlpQueNaoBaixaNada)


class TestKwai:
    def test_baixa_e_le_o_titulo_do_json(self, tmp_path, video_teste):
        with open(video_teste, "rb") as f:
            video_bytes = f.read()
        fake_requests = _FakeRequestsKwai(video_bytes)
        caminho = baixar_video_kwai("https://www.kwai.com/@x/video/1", str(tmp_path), requests_module=fake_requests)
        assert os.path.basename(caminho) == "original.mp4"
        with open(caminho, "rb") as f:
            assert f.read() == video_bytes

    def test_pagina_sem_o_script_do_video_da_erro_claro(self, tmp_path):
        fake_requests = _FakeRequestsKwai(b"", sem_script=True)
        with pytest.raises(RedesSociaisError, match="VideoObject"):
            baixar_video_kwai("https://www.kwai.com/@x/video/1", str(tmp_path), requests_module=fake_requests)

    def test_json_sem_content_url_da_erro_claro(self, tmp_path):
        fake_requests = _FakeRequestsKwai(b"", pagina_html=_html_kwai(None))
        # contentUrl None -> get() devolve None -> erro esperado
        with pytest.raises(RedesSociaisError, match="contentUrl"):
            baixar_video_kwai("https://www.kwai.com/@x/video/1", str(tmp_path), requests_module=fake_requests)

    def test_pagina_indisponivel_da_erro_claro(self, tmp_path):
        fake_requests = _FakeRequestsKwai(b"", pagina_status=404)
        with pytest.raises(RedesSociaisError, match="acessar o link"):
            baixar_video_kwai("https://www.kwai.com/@x/video/1", str(tmp_path), requests_module=fake_requests)

    def test_video_e_verificavel_com_tem_audio(self, tmp_path, video_teste, video_sem_audio):
        with open(video_teste, "rb") as f:
            caminho_com = baixar_video_kwai("https://kwai.com/@x/video/1", str(tmp_path / "1"), requests_module=_FakeRequestsKwai(f.read()))
        with open(video_sem_audio, "rb") as f:
            caminho_sem = baixar_video_kwai("https://kwai.com/@x/video/2", str(tmp_path / "2"), requests_module=_FakeRequestsKwai(f.read()))
        assert tem_audio(caminho_com) is True
        assert tem_audio(caminho_sem) is False


class TestVerificarYtdlp:
    def test_com_modulo_injetado_sempre_true(self):
        assert verificar_ytdlp(ytdlp_module=object()) is True

    def test_sem_modulo_reflete_se_o_pacote_existe_de_verdade(self):
        import importlib.util
        assert verificar_ytdlp() == (importlib.util.find_spec("yt_dlp") is not None)


# --------------------------------------------------------------------------- #
# checar_qualidade
# --------------------------------------------------------------------------- #
class _FakeYoutubeDLQualidade:
    formatos_por_url = {}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def extract_info(self, url, download=False):
        return self.formatos_por_url.get(url, self.formatos_por_url.get("_default"))


def _fake_ytdlp_qualidade(info_por_url):
    return type("FakeYtDlpQualidade", (), {"YoutubeDL": type(
        "Cls", (_FakeYoutubeDLQualidade,), {"formatos_por_url": info_por_url},
    )})


_INFO_PADRAO = {
    "title": "Vídeo de teste",
    "duration": 42.5,
    "formats": [
        {"vcodec": "none", "acodec": "aac"},  # só áudio -- deve ser ignorado
        {"vcodec": "h264", "width": 640, "height": 360, "fps": 30, "ext": "mp4", "filesize": 1_000_000},
        {"vcodec": "h264", "width": 1920, "height": 1080, "fps": 60, "ext": "mp4", "filesize": 5_000_000},  # a melhor
    ],
}


class TestChecarQualidadeYtdlp:
    def test_escolhe_o_formato_de_maior_resolucao(self):
        r = checar_qualidade("https://www.tiktok.com/@x/video/1", ytdlp_module=_fake_ytdlp_qualidade({"_default": _INFO_PADRAO}))
        assert (r["largura"], r["altura"], r["fps"]) == (1920, 1080, 60)
        assert r["tamanho_aproximado_mb"] == 4.8
        assert r["dominio"] == "tiktok.com"
        assert r["titulo"] == "Vídeo de teste"
        assert r["duracao_segundos"] == 42.5

    def test_youtube_tambem_suportado(self):
        r = checar_qualidade("https://www.youtube.com/watch?v=abc", ytdlp_module=_fake_ytdlp_qualidade({"_default": _INFO_PADRAO}))
        assert r["dominio"] == "youtube.com"

    def test_sem_formato_de_video_cai_pro_info_geral(self):
        info = {"title": "x", "width": 100, "height": 200, "formats": [{"vcodec": "none"}]}
        r = checar_qualidade("https://x.com/u/status/1", ytdlp_module=_fake_ytdlp_qualidade({"_default": info}))
        assert (r["largura"], r["altura"]) == (100, 200)

    def test_fonte_nao_suportada_da_erro_claro(self):
        with pytest.raises(RedesSociaisError, match="não suportada"):
            checar_qualidade("https://www.pinterest.com/pin/1")


class TestChecarQualidadeKwai:
    def _ffprobe_fake(self, saida):
        def _run(cmd, capture_output=True, text=True, timeout=None):
            return type("R", (), {"stdout": json.dumps(saida), "stderr": ""})()
        return _run

    def test_le_via_ffprobe_no_link_direto(self):
        saida = {
            "streams": [{"width": 1080, "height": 1920, "r_frame_rate": "30/1", "codec_name": "h264"}],
            "format": {"duration": "12.3", "size": "2000000"},
        }
        fake_requests = _FakeRequestsKwai(b"", pagina_html=_html_kwai("https://cdn.kwai.com/v.mp4", "Legal) #a"))
        r = checar_qualidade(
            "https://www.kwai.com/@x/video/1",
            requests_module=fake_requests, ffprobe_runner=self._ffprobe_fake(saida),
        )
        assert (r["largura"], r["altura"], r["fps"]) == (1080, 1920, 30.0)
        assert r["titulo"] == "Legal)"
        assert r["duracao_segundos"] == 12.3
        assert r["dominio"] == "kwai.com"

    def test_sem_stream_de_video_da_erro_claro(self):
        fake_requests = _FakeRequestsKwai(b"", pagina_html=_html_kwai("https://cdn.kwai.com/v.mp4"))
        with pytest.raises(RedesSociaisError, match="ffprobe"):
            checar_qualidade("https://kwai.com/@x/video/1", requests_module=fake_requests, ffprobe_runner=self._ffprobe_fake({"streams": []}))
