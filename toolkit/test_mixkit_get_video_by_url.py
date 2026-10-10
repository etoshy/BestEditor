"""
Teste automatizado de `MixkitClient.get_video_by_url()` — regressão de
um bug real relatado em produção: a regex antiga só reconhecia
`<video src="...">` quando `src` era o PRIMEIRO atributo da tag (como
na listagem/busca), mas a página de DETALHE tem vários atributos antes
de `src` (class, data-controller, poster, etc), então nunca encontrava
nada e a resolução de "fixar candidato" sempre falhava com
"Não encontrei nenhum vídeo reconhecível".

O HTML de teste abaixo é uma amostra real, colada pelo usuário, da
página de detalhe de um vídeo do Mixkit.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

import mixkit.mixkit_client as mixkit_mod
from mixkit.mixkit_client import MixkitClient, MixkitClientError, MixkitVideo

# HTML real da página de detalhe, fornecido pelo usuário — a tag <video>
# tem vários atributos ANTES de "src" (diferente da listagem).
_REAL_DETAIL_PAGE_HTML = """
<div class="video-player " data-controller="video-player--video-player" data-video-player--video-player-is-paused-value="false">
  <video class="video-player__viewer" data-video-player--video-player-target="video"
    data-action="click-&gt;video-player--video-player#togglePlay"
    poster="https://assets.mixkit.co/videos/1473/1473-thumb-720-0.jpg"
    src="https://assets.mixkit.co/videos/1473/1473-720.mp4"
    controlslist="nodownload" disablepictureinpicture="" autoplay="" playsinline="" loop="" muted="">
  </video>
</div>
<title>Lizard Over A Trunk At Nature Closeup Free Stock Video - Mixkit</title>
"""


class FakeResp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


def _client_with_response(monkeypatch, resp):
    client = MixkitClient.__new__(MixkitClient)
    client.session = object()
    client.delay = 0
    monkeypatch.setattr(mixkit_mod, "_request_with_retry", lambda *a, **kw: resp)
    return client


class TestGetVideoByUrlDetailPage:
    def test_parses_real_detail_page_html(self, monkeypatch):
        client = _client_with_response(monkeypatch, FakeResp(200, _REAL_DETAIL_PAGE_HTML))
        video = client.get_video_by_url("https://mixkit.co/free-stock-video/lizard-over-a-trunk-at-nature-closeup-1473/")

        assert video.id == "1473"
        assert video.preview_url == "https://assets.mixkit.co/videos/1473/1473-720.mp4"
        assert video.thumbnail == "https://assets.mixkit.co/videos/1473/1473-thumb-720-0.jpg"
        assert "Lizard" in video.title

    def test_resolved_video_can_build_quality_candidates_for_download(self, monkeypatch):
        """Confirma que o preview_url extraído da página de detalhe
        funciona de verdade com o mecanismo de retry de qualidade do
        download — não só que os campos foram parseados."""
        client = _client_with_response(monkeypatch, FakeResp(200, _REAL_DETAIL_PAGE_HTML))
        video = client.get_video_by_url("https://mixkit.co/free-stock-video/lizard-over-a-trunk-at-nature-closeup-1473/")

        candidates = client._build_quality_candidates(video.preview_url, "best")
        urls = [c[0] for c in candidates]
        assert any("1473-2160.mp4" in u for u in urls)
        assert any("1473-1080.mp4" in u for u in urls)
        assert any("1473-720.mp4" in u for u in urls)
        assert any("1473-360.mp4" in u for u in urls)

    def test_raises_clear_error_when_no_video_tag_found(self, monkeypatch):
        client = _client_with_response(monkeypatch, FakeResp(200, "<html><body>página sem vídeo nenhum</body></html>"))
        with pytest.raises(MixkitClientError, match="Não encontrei nenhuma tag <video>"):
            client.get_video_by_url("https://mixkit.co/free-stock-video/algo-999/")

    def test_raises_clear_error_on_http_failure(self, monkeypatch):
        client = _client_with_response(monkeypatch, FakeResp(404, ""))
        with pytest.raises(MixkitClientError, match="404"):
            client.get_video_by_url("https://mixkit.co/free-stock-video/nao-existe-999/")

    def test_falls_back_to_asset_url_id_when_page_url_has_no_trailing_number(self, monkeypatch):
        """Se por algum motivo a URL da página não terminar em número,
        ainda dá pra extrair o ID de dentro da própria URL do arquivo de
        vídeo (.../videos/1473/1473-720.mp4)."""
        client = _client_with_response(monkeypatch, FakeResp(200, _REAL_DETAIL_PAGE_HTML))
        video = client.get_video_by_url("https://mixkit.co/free-stock-video/sem-numero-no-final/")
        assert video.id == "1473"
