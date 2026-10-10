"""
Teste de webpage_capture.py — usa um Chromium de verdade (via
Playwright) contra uma página HTML de teste servida por um
`http.server` local, rodando numa THREAD dentro do próprio processo de
teste (não um processo externo — assim não depende de nenhum estado
entre execuções, e funciona igual em qualquer máquina que tenha o
Chromium do Playwright instalado).

Pulado automaticamente se o Playwright (ou o Chromium dele) não
estiver disponível, em vez de falhar a suíte inteira por causa disso.
"""
import http.server
import os
import shutil
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as _p:
        _b = _p.chromium.launch(headless=True)
        _b.close()
    _PLAYWRIGHT_OK = True
except Exception:  # noqa: BLE001
    _PLAYWRIGHT_OK = False

pytestmark = pytest.mark.skipif(not _PLAYWRIGHT_OK, reason="Playwright/Chromium não disponível neste ambiente")

from webpage_capture import WebpageCaptureError, capturar_pagina  # noqa: E402


_PAGINA_TESTE = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Notícia de Teste</title></head>
<body>
  <nav>Menu que deveria ser ignorado</nav>
  <div class="advertisement">Anúncio que deveria ser removido</div>
  <article>
    <h1>Título Principal da Matéria</h1>
    <p>Este é o primeiro parágrafo com informações importantes sobre o assunto tratado.</p>
    <figure>
      <img src="foto1.png" alt="Uma foto de teste">
      <figcaption>Legenda da primeira foto</figcaption>
    </figure>
    <p>Segundo parágrafo com mais detalhes e um nome próprio como Albert Einstein.</p>
    <blockquote>Uma citação importante de alguém.</blockquote>
    <ul>
      <li>Primeiro item da lista</li>
      <li>Segundo item da lista</li>
    </ul>
    <img src="foto2.png" alt="Segunda foto sem legenda separada">
  </article>
  <div class="comments-container">Comentários que deveriam ser removidos</div>
</body>
</html>"""

_PAGINA_SEM_ARTICLE = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Página sem article</title></head>
<body>
  <h1>Site genérico qualquer</h1>
  <p>Um parágrafo qualquer, fora de qualquer tag article ou main.</p>
</body>
</html>"""

_PAGINA_VAZIA = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Vazia</title></head><body></body></html>"""


@pytest.fixture(scope="module")
def servidor_local():
    """Sobe um `http.server` numa thread, servindo um diretório com as
    páginas de teste + duas imagens geradas na hora -- devolve a URL
    base (ex: "http://localhost:PORTA")."""
    import tempfile
    pasta = Path(tempfile.mkdtemp(prefix="webpage_capture_teste_"))
    (pasta / "index.html").write_text(_PAGINA_TESTE, encoding="utf-8")
    (pasta / "sem_article.html").write_text(_PAGINA_SEM_ARTICLE, encoding="utf-8")
    (pasta / "vazia.html").write_text(_PAGINA_VAZIA, encoding="utf-8")

    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=400x300", "-frames:v", "1", str(pasta / "foto1.png")],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=400x300", "-frames:v", "1", str(pasta / "foto2.png")],
        capture_output=True, check=True,
    )

    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(*args, directory=str(pasta), **kwargs)
    servidor = http.server.ThreadingHTTPServer(("localhost", 0), handler)
    porta = servidor.server_port
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{porta}"
    servidor.shutdown()


class TestCapturaBasica:
    def test_captura_pagina_completa(self, servidor_local, tmp_path):
        resultado = capturar_pagina(f"{servidor_local}/index.html", str(tmp_path))
        assert resultado["titulo"] == "Notícia de Teste"
        assert os.path.exists(resultado["screenshot_path"])
        assert os.path.getsize(resultado["screenshot_path"]) > 1000
        assert os.path.exists(resultado["map_path"])

    def test_blocos_de_texto_relevantes_sao_encontrados(self, servidor_local, tmp_path):
        resultado = capturar_pagina(f"{servidor_local}/index.html", str(tmp_path))
        textos = [b["texto"] for b in resultado["blocos"]]
        assert any("Título Principal da Matéria" == t for t in textos)
        assert any("Albert Einstein" in t for t in textos)
        assert any("Uma citação importante" in t for t in textos)
        assert any("Primeiro item da lista" == t for t in textos)

    def test_tipos_de_bloco_corretos(self, servidor_local, tmp_path):
        resultado = capturar_pagina(f"{servidor_local}/index.html", str(tmp_path))
        tipos_por_texto = {b["texto"]: b["tipo"] for b in resultado["blocos"]}
        assert tipos_por_texto["Título Principal da Matéria"] == "h1"
        assert tipos_por_texto["Legenda da primeira foto"] == "legenda_imagem"
        assert tipos_por_texto["Uma citação importante de alguém."] == "blockquote"
        assert tipos_por_texto["Primeiro item da lista"] == "li"

    def test_blocos_tem_coordenadas_validas(self, servidor_local, tmp_path):
        resultado = capturar_pagina(f"{servidor_local}/index.html", str(tmp_path))
        for b in resultado["blocos"]:
            assert b["largura"] > 0 and b["altura"] > 0
            assert b["x"] >= 0 and b["y"] >= 0

    def test_blocos_em_ordem_vertical_crescente(self, servidor_local, tmp_path):
        """O título vem antes do primeiro parágrafo na página -- o
        bloco dele deveria ter um "y" menor (mais pro topo)."""
        resultado = capturar_pagina(f"{servidor_local}/index.html", str(tmp_path))
        por_texto = {b["texto"]: b for b in resultado["blocos"]}
        titulo = por_texto["Título Principal da Matéria"]
        paragrafo = por_texto["Este é o primeiro parágrafo com informações importantes sobre o assunto tratado."]
        assert titulo["y"] < paragrafo["y"]

    def test_ruido_e_filtrado(self, servidor_local, tmp_path):
        resultado = capturar_pagina(f"{servidor_local}/index.html", str(tmp_path))
        textos = " ".join(b["texto"] for b in resultado["blocos"])
        assert "Menu que deveria ser ignorado" not in textos
        assert "Anúncio que deveria ser removido" not in textos
        assert "Comentários que deveriam ser removidos" not in textos

    def test_ids_dos_blocos_sao_unicos(self, servidor_local, tmp_path):
        resultado = capturar_pagina(f"{servidor_local}/index.html", str(tmp_path))
        ids = [b["id"] for b in resultado["blocos"]]
        assert len(ids) == len(set(ids))


class TestGaleria:
    def test_galeria_baixa_as_duas_imagens(self, servidor_local, tmp_path):
        resultado = capturar_pagina(f"{servidor_local}/index.html", str(tmp_path))
        assert len(resultado["galeria"]) == 2

    def test_galeria_arquivos_existem_de_verdade(self, servidor_local, tmp_path):
        resultado = capturar_pagina(f"{servidor_local}/index.html", str(tmp_path))
        for g in resultado["galeria"]:
            caminho = os.path.join(resultado["gallery_dir"], g["arquivo"])
            assert os.path.exists(caminho)
            assert os.path.getsize(caminho) > 100

    def test_galeria_usa_legenda_do_figcaption_quando_existe(self, servidor_local, tmp_path):
        resultado = capturar_pagina(f"{servidor_local}/index.html", str(tmp_path))
        legendas = {g["legenda"] for g in resultado["galeria"]}
        assert "Legenda da primeira foto" in legendas

    def test_galeria_usa_alt_quando_nao_tem_figcaption(self, servidor_local, tmp_path):
        resultado = capturar_pagina(f"{servidor_local}/index.html", str(tmp_path))
        legendas = {g["legenda"] for g in resultado["galeria"]}
        assert "Segunda foto sem legenda separada" in legendas

    def test_galeria_guarda_a_url_original(self, servidor_local, tmp_path):
        resultado = capturar_pagina(f"{servidor_local}/index.html", str(tmp_path))
        for g in resultado["galeria"]:
            assert g["url_original"].startswith(servidor_local)


class TestMapaSalvo:
    def test_mapa_json_consistente_com_o_resultado(self, servidor_local, tmp_path):
        import json
        resultado = capturar_pagina(f"{servidor_local}/index.html", str(tmp_path))
        with open(resultado["map_path"], encoding="utf-8") as f:
            mapa = json.load(f)
        assert mapa["blocos"] == resultado["blocos"]
        assert mapa["galeria"] == resultado["galeria"]
        assert mapa["titulo"] == resultado["titulo"]
        assert mapa["url"] == f"{servidor_local}/index.html"

    def test_mapa_tem_dimensoes_da_area_de_conteudo(self, servidor_local, tmp_path):
        import json
        resultado = capturar_pagina(f"{servidor_local}/index.html", str(tmp_path))
        with open(resultado["map_path"], encoding="utf-8") as f:
            mapa = json.load(f)
        assert mapa["largura"] > 0
        assert mapa["altura"] > 0


class TestSemArticleTag:
    def test_cai_pro_body_inteiro_quando_nao_tem_article_nem_main(self, servidor_local, tmp_path):
        """Página SEM <article>/<main> -- não é um site de notícia
        clássico, mas ainda deve funcionar (cai pro <body> inteiro)."""
        resultado = capturar_pagina(f"{servidor_local}/sem_article.html", str(tmp_path))
        textos = [b["texto"] for b in resultado["blocos"]]
        assert any("Site genérico qualquer" == t for t in textos)
        assert any("fora de qualquer tag article ou main" in t for t in textos)


class TestErros:
    def test_pagina_vazia_da_erro_claro(self, servidor_local, tmp_path):
        with pytest.raises(WebpageCaptureError, match="Não encontrei"):
            capturar_pagina(f"{servidor_local}/vazia.html", str(tmp_path))

    def test_url_inacessivel_da_erro_claro(self, tmp_path):
        with pytest.raises(WebpageCaptureError, match="Não consegui abrir"):
            capturar_pagina("http://localhost:1/pagina-que-nao-existe", str(tmp_path))

    def test_cria_diretorio_de_saida_se_nao_existir(self, servidor_local, tmp_path):
        alvo = tmp_path / "pasta" / "que" / "nao" / "existe"
        capturar_pagina(f"{servidor_local}/index.html", str(alvo))
        assert alvo.exists()
