"""
Testes de integração das rotas das ferramentas pequenas adicionadas:
"Baixar de outras redes" (/redes-sociais), "Extrair links de canal"
(/extrair-links-canal) e "Transcrever" (/transcrever). O download/checagem/
transcrição de verdade são sempre FALSOS (monkeypatch nas funções que o
app.py chama) — só o zip/arquivos em disco são reais.
"""
import io
import json
import os
import subprocess
import time

import pytest


@pytest.fixture(scope="module")
def video_teste():
    import tempfile
    caminho = os.path.join(tempfile.mkdtemp(prefix="ferramentas_app_teste_"), "video.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=2:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", caminho],
        capture_output=True, check=True,
    )
    return caminho


@pytest.fixture
def app_module():
    import app as _app_module
    return _app_module


@pytest.fixture
def client(app_module):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _espera(fn_status, timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = fn_status()
        if st["status"] != "processando":
            return st
        time.sleep(0.15)
    raise TimeoutError("job não terminou a tempo")


# =========================================================================
# Baixar de outras redes (/redes-sociais)
# =========================================================================

class TestRedesSociaisPagina:
    def test_pagina_carrega(self, client):
        r = client.get("/redes-sociais")
        assert r.status_code == 200
        assert "Baixar de outras redes".encode() in r.data

    def test_mostra_o_botao_de_checar_qualidade(self, client):
        r = client.get("/redes-sociais")
        assert b"Checar qualidade" in r.data


class TestChecarQualidadeRota:
    def test_sem_url_da_400(self, client):
        r = client.post("/redes-sociais/checar-qualidade", json={})
        assert r.status_code == 400

    def test_com_url_valida_devolve_resultado(self, client, app_module, monkeypatch):
        monkeypatch.setattr(app_module, "checar_qualidade", lambda url: {
            "titulo": "Um vídeo", "largura": 1920, "altura": 1080, "fps": 30,
            "codec_video": "h264", "extensao": "mp4", "tamanho_aproximado_mb": 5.2,
            "duracao_segundos": 12.0, "dominio": "tiktok.com",
        })
        r = client.post("/redes-sociais/checar-qualidade", json={"url": "https://www.tiktok.com/@x/video/1"})
        assert r.status_code == 200
        assert r.get_json()["resultado"]["largura"] == 1920

    def test_erro_conhecido_vira_400(self, client, app_module, monkeypatch):
        def _fake(url):
            raise app_module.RedesSociaisError("fonte não suportada")

        monkeypatch.setattr(app_module, "checar_qualidade", _fake)
        r = client.post("/redes-sociais/checar-qualidade", json={"url": "https://www.pinterest.com/pin/1"})
        assert r.status_code == 400 and "não suportada" in r.get_json()["erro"]

    def test_erro_inesperado_vira_500(self, client, app_module, monkeypatch):
        def _fake(url):
            raise RuntimeError("algo quebrou")

        monkeypatch.setattr(app_module, "checar_qualidade", _fake)
        r = client.post("/redes-sociais/checar-qualidade", json={"url": "https://x"})
        assert r.status_code == 500


class TestRedesSociaisSubmit:
    def test_sem_urls_da_400(self, client):
        r = client.post("/redes-sociais", json={"urls": []})
        assert r.status_code == 400

    def test_baixa_e_zipa_cada_url(self, client, app_module, video_teste, monkeypatch):
        chamadas = []

        def _fake_baixar(url, pasta_destino, ytdlp_module=None, requests_module=None):
            chamadas.append(url)
            import shutil
            os.makedirs(pasta_destino, exist_ok=True)
            destino = os.path.join(pasta_destino, "original.mp4")
            shutil.copy(video_teste, destino)
            return destino

        monkeypatch.setattr(app_module.redes_sociais, "baixar_video", _fake_baixar)
        r = client.post("/redes-sociais", json={"urls": [
            "https://www.tiktok.com/@a/video/1", "https://www.instagram.com/reel/b/",
        ]})
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]

        st = _espera(lambda: client.get(f"/redes-sociais/{job_id}/status").get_json())
        assert st["status"] == "pronto" and st["quantidade_baixados"] == 2
        assert len(chamadas) == 2

        r2 = client.get(f"/redes-sociais/{job_id}/download")
        assert r2.status_code == 200 and r2.headers["Content-Type"] == "application/zip"

    def test_erro_em_uma_url_marca_job_como_erro(self, client, app_module, monkeypatch):
        def _fake_baixar(url, pasta_destino, ytdlp_module=None, requests_module=None):
            raise app_module.RedesSociaisError("fonte não suportada")

        monkeypatch.setattr(app_module.redes_sociais, "baixar_video", _fake_baixar)
        r = client.post("/redes-sociais", json={"urls": ["https://www.pinterest.com/pin/1"]})
        job_id = r.get_json()["job_id"]
        st = _espera(lambda: client.get(f"/redes-sociais/{job_id}/status").get_json())
        assert st["status"] == "erro" and "não suportada" in st["erro"]

    def test_status_de_job_inexistente_da_404(self, client):
        assert client.get("/redes-sociais/fantasma/status").status_code == 404

    def test_download_antes_de_pronto_da_404(self, client, app_module, monkeypatch):
        monkeypatch.setattr(app_module.redes_sociais, "baixar_video", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nunca termina")))
        r = client.post("/redes-sociais", json={"urls": ["https://tiktok.com/@a/video/1"]})
        job_id = r.get_json()["job_id"]
        assert client.get(f"/redes-sociais/{job_id}/download").status_code == 404


# =========================================================================
# Extrair links de canal (/extrair-links-canal)
# =========================================================================

class TestExtrairLinksCanalPagina:
    def test_pagina_carrega(self, client):
        r = client.get("/extrair-links-canal")
        assert r.status_code == 200
        assert "Extrair links de canal".encode() in r.data


class TestExtrairLinksCanalBuscar:
    def test_url_vazia_da_erro(self, client):
        r = client.post("/extrair-links-canal/buscar", json={"url": ""})
        assert r.status_code == 400

    def test_com_canal_valido_devolve_itens(self, client, app_module, monkeypatch):
        monkeypatch.setattr(app_module, "extrair_links_canal", lambda url, tipo="shorts", ordem="mais_novos": {
            "canal": "https://youtube.com/@canal/shorts", "tipo": tipo, "ordem": ordem,
            "total": 2, "itens": [
                {"indice": 1, "titulo": "Um", "link": "https://www.youtube.com/shorts/a", "id": "a", "upload_date": ""},
                {"indice": 2, "titulo": "Dois", "link": "https://www.youtube.com/shorts/b", "id": "b", "upload_date": ""},
            ],
        })
        r = client.post("/extrair-links-canal/buscar", json={"url": "youtube.com/@canal"})
        assert r.status_code == 200
        body = r.get_json()
        assert body["total"] == 2 and body["itens"][0]["titulo"] == "Um"

    def test_erro_do_youtube_clipper_vira_400(self, client, app_module, monkeypatch):
        def _fake(url, tipo="shorts", ordem="mais_novos"):
            raise app_module.YoutubeClipperError("Nenhum vídeo foi encontrado nesse canal.")

        monkeypatch.setattr(app_module, "extrair_links_canal", _fake)
        r = client.post("/extrair-links-canal/buscar", json={"url": "youtube.com/@fantasma"})
        assert r.status_code == 400 and "Nenhum vídeo" in r.get_json()["erro"]


# =========================================================================
# Transcrever (/transcrever)
# =========================================================================

class TestTranscreverPagina:
    def test_pagina_carrega(self, client):
        r = client.get("/transcrever")
        assert r.status_code == 200
        assert "Transcrever".encode() in r.data


class TestTranscreverSubmit:
    def test_sem_url_e_sem_arquivo_da_400(self, client):
        r = client.post("/transcrever", data={})
        assert r.status_code == 400

    def test_com_url_e_arquivo_juntos_da_400(self, client, video_teste):
        with open(video_teste, "rb") as f:
            r = client.post("/transcrever", data={
                "url": "https://x", "arquivo": (f, "video.mp4"),
            }, content_type="multipart/form-data")
        assert r.status_code == 400

    def test_com_url_chama_processar_e_devolve_resultado(self, client, app_module, monkeypatch):
        chamadas = []

        def _fake_processar(saida_dir, url=None, arquivo_path=None, modo="transcrever", **kwargs):
            chamadas.append((url, arquivo_path, modo))
            return {"modo": modo, "video": "video.mp4", "largura": 1920, "altura": 1080,
                    "aviso_resolucao_baixa": False, "idioma": None, "total_segmentos": 2,
                    "segmentos": [{"start": 0.0, "end": 1.0, "text": "Oi."}],
                    "arquivo_texto": "transcricao.txt", "arquivo_srt": "transcricao.srt",
                    "arquivo_segmentos": "transcricao.json"}

        monkeypatch.setattr(app_module.ta_avulso, "processar", _fake_processar)
        r = client.post("/transcrever", data={"url": "https://youtu.be/x", "modo": "transcrever"})
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        st = _espera(lambda: client.get(f"/transcrever/{job_id}/status").get_json())
        assert st["status"] == "pronto"
        assert st["resultado"]["total_segmentos"] == 2
        assert chamadas[0][0] == "https://youtu.be/x" and chamadas[0][1] is None

    def test_com_arquivo_enviado_salva_e_passa_o_caminho(self, client, app_module, video_teste, monkeypatch):
        chamadas = []

        def _fake_processar(saida_dir, url=None, arquivo_path=None, modo="baixar", **kwargs):
            chamadas.append(arquivo_path)
            assert arquivo_path and os.path.exists(arquivo_path)
            return {"modo": modo, "video": "video.mp4", "largura": 320, "altura": 240, "aviso_resolucao_baixa": True}

        monkeypatch.setattr(app_module.ta_avulso, "processar", _fake_processar)
        with open(video_teste, "rb") as f:
            r = client.post("/transcrever", data={
                "arquivo": (f, "meu_video.mp4"), "modo": "baixar",
            }, content_type="multipart/form-data")
        job_id = r.get_json()["job_id"]
        st = _espera(lambda: client.get(f"/transcrever/{job_id}/status").get_json())
        assert st["status"] == "pronto"
        assert chamadas[0] is not None

    def test_erro_conhecido_marca_job_como_erro(self, client, app_module, monkeypatch):
        def _fake_processar(*a, **k):
            raise app_module.ta_avulso.TranscreverAvulsoError("yt-dlp não está instalado.")

        monkeypatch.setattr(app_module.ta_avulso, "processar", _fake_processar)
        r = client.post("/transcrever", data={"url": "https://youtu.be/x"})
        job_id = r.get_json()["job_id"]
        st = _espera(lambda: client.get(f"/transcrever/{job_id}/status").get_json())
        assert st["status"] == "erro" and "yt-dlp" in st["erro"]

    def test_status_de_job_inexistente_da_404(self, client):
        assert client.get("/transcrever/fantasma/status").status_code == 404

    def test_modo_padrao_e_transcrever(self, client, app_module, monkeypatch):
        modos = []

        def _fake_processar(saida_dir, url=None, arquivo_path=None, modo="transcrever", **kwargs):
            modos.append(modo)
            return {"modo": modo, "video": "video.mp4", "largura": None, "altura": None, "aviso_resolucao_baixa": False}

        monkeypatch.setattr(app_module.ta_avulso, "processar", _fake_processar)
        r = client.post("/transcrever", data={"url": "https://youtu.be/x"})
        _espera(lambda: client.get(f"/transcrever/{r.get_json()['job_id']}/status").get_json())
        assert modos == ["transcrever"]


class TestTranscreverArquivoDownload:
    def _job_pronto(self, client, app_module, monkeypatch, tmp_arquivos):
        def _fake_processar(saida_dir, url=None, arquivo_path=None, modo="transcrever", **kwargs):
            for nome, conteudo in tmp_arquivos.items():
                with open(os.path.join(saida_dir, nome), "w", encoding="utf-8") as f:
                    f.write(conteudo)
            return {"modo": modo, "video": "video.mp4", "largura": None, "altura": None,
                    "aviso_resolucao_baixa": False, "arquivo_texto": "transcricao.txt"}

        monkeypatch.setattr(app_module.ta_avulso, "processar", _fake_processar)
        r = client.post("/transcrever", data={"url": "https://youtu.be/x"})
        job_id = r.get_json()["job_id"]
        _espera(lambda: client.get(f"/transcrever/{job_id}/status").get_json())
        return job_id

    def test_baixa_um_arquivo_permitido(self, client, app_module, monkeypatch):
        job_id = self._job_pronto(client, app_module, monkeypatch, {"transcricao.txt": "Olá mundo."})
        r = client.get(f"/transcrever/{job_id}/arquivo/transcricao.txt")
        assert r.status_code == 200 and r.data == b"Ol\xc3\xa1 mundo."

    def test_arquivo_fora_da_lista_permitida_da_404(self, client, app_module, monkeypatch):
        job_id = self._job_pronto(client, app_module, monkeypatch, {"transcricao.txt": "x", "segredo.env": "SENHA=123"})
        # o arquivo EXISTE em disco -- se a whitelist não bloqueasse, isso baixaria normalmente
        r = client.get(f"/transcrever/{job_id}/arquivo/segredo.env")
        assert r.status_code == 404

    def test_tentativa_de_path_traversal_da_404(self, client, app_module, monkeypatch):
        job_id = self._job_pronto(client, app_module, monkeypatch, {"transcricao.txt": "x"})
        r = client.get(f"/transcrever/{job_id}/arquivo/..%2F..%2Fapp.py")
        assert r.status_code in (404, 400)

    def test_job_nao_encontrado_da_404(self, client):
        assert client.get("/transcrever/fantasma/arquivo/transcricao.txt").status_code == 404
