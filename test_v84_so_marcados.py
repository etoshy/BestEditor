"""v84_72 — 🚫 só os bancos e buscadores MARCADOS no vídeo (a reserva vinha da prioridade das Configurações — todos —
e os 4 buscadores de imagem rodavam sempre, cada um abrindo um navegador)."""
import pytest

import video_assembler as va
from prompt_builder import VideoSegment


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_cfg_do_job_so_com_os_marcados(A, monkeypatch):
    monkeypatch.setattr(A, "load_site_config", lambda: {"provider_priority": ["mixkit", "pexels", "magnific", "vistacreate", "bing", "brave"]})
    cfg = A._job_site_cfg({"providers": ["pexels", "pixabay", "bing"]})
    assert cfg["provider_priority"] == ["pexels", "bing", "pixabay"]  # a ordem das Configurações, só os marcados
    assert cfg["provedores_do_job"] == ["pexels", "pixabay", "bing"]
    assert "provedores_do_job" not in A._job_site_cfg({})  # job antigo sem a lista: como antes


def test_previa_nao_cai_em_banco_desmarcado(A, monkeypatch):
    tentados = []

    def busca(provider, query, **kw):
        tentados.append(provider)
        return []
    monkeypatch.setattr(va, "search_candidates", busca)
    monkeypatch.setattr(A, "load_site_config", lambda: {"provider_priority": ["pexels", "pixabay", "magnific", "mixkit", "vistacreate"]})
    cfg = A._job_site_cfg({"providers": ["pexels", "mixkit"]})
    sg = VideoSegment(start=0.0, end=4.0, provider="pexels", query="cidade")
    va.fetch_segment_preview_lightweight(sg, site_cfg=cfg)
    assert set(tentados) == {"pexels", "mixkit"}


def test_buscadores_de_imagem_so_os_marcados(tmp_path):
    usados = {}

    def lote(itens, pasta, engines=None, **kw):
        usados["engines"] = list(engines)
        return {}
    itens = [(0, VideoSegment(start=0.0, end=4.0, provider="bing", query="torre eiffel", media_type="image"))]
    va.prefetch_browser_images(itens, str(tmp_path), {"provedores_do_job": ["pexels", "bing", "startpage"]}, cache={}, lote_fn=lote)
    assert usados["engines"] == ["bing", "startpage"]
    va.prefetch_browser_images(itens, str(tmp_path), {}, cache={}, lote_fn=lote)  # sem a lista do job: os 4, como antes
    assert usados["engines"] == ["bing", "brave", "yandex", "startpage"]
    va.prefetch_browser_images(itens, str(tmp_path), {"provedores_do_job": ["pexels"]}, cache={}, lote_fn=lote)
    assert usados["engines"] == ["bing"]  # nenhum marcado: só o do próprio trecho


def test_ia_do_youtube_nunca_abre_janela(A, monkeypatch, tmp_path):
    import yt_alternativas as alt
    chamadas = []
    monkeypatch.setattr(alt, "legenda_transcript_api", lambda url, pref: None)
    monkeypatch.setattr(alt, "legenda_painel", lambda url, headless=True: chamadas.append(headless) or None)
    import roteiros_yt
    monkeypatch.setattr(roteiros_yt, "extrair_transcricao", lambda *a, **k: {"blocos": []})
    A._legenda_com_tempos("https://www.youtube.com/watch?v=abcdefghijk", str(tmp_path), pode_visivel=False)
    assert chamadas == [True]
    chamadas.clear()
    A._legenda_com_tempos("https://www.youtube.com/watch?v=abcdefghijk", str(tmp_path))  # o botão 🎯 (um vídeo) pode
    assert chamadas == [True, False]
