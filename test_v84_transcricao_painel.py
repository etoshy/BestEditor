"""
v84_52 — transcrição do YouTube pelo painel "Mostrar transcrição", do jeito do
projeto transcript-youtube-video (abre o vídeo, "…mais" → "Mostrar transcrição",
lê <transcript-segment-view-model>). Sem rede: a página do YouTube é simulada.
"""
import pytest

import roteiros_yt as ry
import yt_alternativas as alt

# o painel NOVO do YouTube (o que o transcript-youtube-video lê) e o antigo
_NOVO = """
<div id="description-inline-expander"><tp-yt-paper-button id="expand" onclick="document.getElementById('sec').style.display='block'">…mais</tp-yt-paper-button></div>
<ytd-video-description-transcript-section-renderer id="sec" style="display:none">
  <div id="primary-button"><ytd-button-renderer><yt-button-shape><button onclick="abrir()">Mostrar transcrição</button></yt-button-shape></ytd-button-renderer></div>
</ytd-video-description-transcript-section-renderer>
<div id="content"></div>
<script>
function abrir() {
  setTimeout(() => {
    const c = document.getElementById('content');
    c.innerHTML = '<yt-section-list-renderer><div id="contents">' +
      '<div><macro-markers-panel-item-view-model><h3>Introdução</h3></macro-markers-panel-item-view-model></div>' +
      [['0:00', 'Nessa aula de JavaScript que começa agora,'], ['0:07', 'vamos falar sobre o processo de aprendizagem'], ['1:05', 'e dar os primeiros passos.']]
        .map(([t, x]) => '<div><macro-markers-panel-item-view-model><timeline-item-view-model><div><transcript-segment-view-model><div>' + t + '</div><span>' + x + '</span></transcript-segment-view-model></div></timeline-item-view-model></macro-markers-panel-item-view-model></div>').join('') +
      '</div></yt-section-list-renderer>';
  }, 300);
}
</script>"""

_ANTIGO = """
<button aria-label="Mostrar transcrição" onclick="document.body.insertAdjacentHTML('beforeend',
 '<ytd-transcript-segment-renderer><div class=segment-timestamp>0:03</div><yt-formatted-string class=segment-text>olá  mundo</yt-formatted-string></ytd-transcript-segment-renderer>')">t</button>"""


@pytest.fixture(scope="module")
def navegador():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def test_painel_novo_do_youtube(navegador):
    pg = navegador.new_page()
    pg.set_content(_NOVO)
    linhas = alt._painel_transcricao(pg, timeout_ms=5000)
    assert [l["texto"] for l in linhas] == ["Nessa aula de JavaScript que começa agora,", "vamos falar sobre o processo de aprendizagem",
                                           "e dar os primeiros passos."]
    assert [l["inicio"] for l in linhas] == [0.0, 7.0, 65.0] and linhas[0]["fim"] == 7.0
    pg.close()


def test_painel_antigo_continua_funcionando(navegador):
    pg = navegador.new_page()
    pg.set_content(_ANTIGO)
    assert alt._painel_transcricao(pg, timeout_ms=5000) == [{"inicio": 3.0, "fim": 6.0, "texto": "olá mundo"}]
    pg.close()


def test_painel_vazio_devolve_lista_vazia(navegador):
    pg = navegador.new_page()
    pg.set_content("<p>sem transcrição</p>")
    assert alt._painel_transcricao(pg, timeout_ms=800) == []
    pg.close()


def test_tempos_do_painel():
    assert alt.linhas_do_painel([["1:02:03", "a"], ["", "sem tempo"], ["0:10", "b"], ["0:20", " "]]) == [
        {"inicio": 10.0, "fim": 3723.0, "texto": "b"}, {"inicio": 3723.0, "fim": 3726.0, "texto": "a"}]


class _Alt:
    CLIENTES = []

    def __init__(self, linhas, tem=True):
        self.linhas, self.tem, self.chamadas = linhas, tem, []

    def legenda_painel(self, url, log, headless=True):
        self.chamadas.append(headless)
        return {"titulo": "Vídeo", "canal": "Canal", "duracao": 70, "linhas": self.linhas, "lang": "pt", "auto": True, "tem_legenda": self.tem}


class _YtdlpQueNaoPodeSerUsado:
    class YoutubeDL:  # noqa: N801
        def __init__(self, *_a, **_k):
            raise AssertionError("o painel já resolveu — não devia chegar no yt-dlp")


def test_painel_vem_primeiro(tmp_path):
    a = _Alt([{"inicio": 0.0, "fim": 5.0, "texto": "Oi pessoal, tudo bem?"}, {"inicio": 5.0, "fim": 9.0, "texto": "Hoje vamos falar de história."}])
    logs = []
    tr = ry.extrair_transcricao("https://youtu.be/abcdefghijk", str(tmp_path), ytdlp_module=_YtdlpQueNaoPodeSerUsado,
                                alternativas=a, painel_primeiro=True, on_log=logs.append)
    assert tr["titulo"] == "Vídeo" and tr["fonte"].startswith("transcrição do YouTube") and tr["idioma"] == "pt"
    assert "Hoje vamos falar de história." in ry.texto_da_transcricao(tr) and a.chamadas == [True]


def test_painel_sem_nada_segue_a_fila(tmp_path, monkeypatch):
    a = _Alt([], tem=None)
    monkeypatch.setattr("site_config.load_site_config", lambda: {"browser_visible": False})
    seguiu = []

    class _Y:
        class YoutubeDL:  # noqa: N801
            def __init__(self, *_a, **_k):
                seguiu.append(1)
                raise RuntimeError("parou aqui")

    with pytest.raises(Exception):
        ry.extrair_transcricao("https://youtu.be/abcdefghijk", str(tmp_path), ytdlp_module=_Y, alternativas=a, painel_primeiro=True,
                               usar_whisper=False)
    assert a.chamadas == [True, False] and seguiu  # escondido, visível, e depois o yt-dlp


def test_nos_testes_com_ytdlp_falso_o_painel_nao_e_usado(tmp_path):
    a = _Alt([{"inicio": 0.0, "fim": 1.0, "texto": "x"}])

    class _Y:
        class YoutubeDL:  # noqa: N801
            def __init__(self, *_a, **_k):
                raise RuntimeError("yt-dlp")

    with pytest.raises(Exception):
        ry.extrair_transcricao("https://youtu.be/abcdefghijk", str(tmp_path), ytdlp_module=_Y, alternativas=a, usar_whisper=False)
    assert a.chamadas == []
