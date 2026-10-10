"""
Teste de integração das rotas de "Cortar do YouTube"
(/cortar-youtube) — injeta um yt-dlp FALSO (copia um vídeo de teste
local) no lugar do download de verdade, mas usa ffmpeg de verdade pro
corte e zip/info.json reais.
"""
import shutil
import subprocess
import time

import pytest


@pytest.fixture(scope="module")
def video_teste():
    import tempfile
    import os
    caminho = os.path.join(tempfile.mkdtemp(prefix="cortar_youtube_app_teste_"), "video_original.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=120:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", caminho],
        capture_output=True, check=True,
    )
    return caminho


class _FakeYoutubeDL:
    origem_video = None

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def extract_info(self, url, download=True):
        video_id = "fakeidapp01"
        destino = self.opts["outtmpl"].replace("%(id)s", video_id).replace("%(ext)s", "mp4")
        shutil.copy(self.origem_video, destino)
        return {"id": video_id, "title": "Vídeo de teste (rota)", "duration": 120.0, "ext": "mp4"}

    def prepare_filename(self, info):
        return self.opts["outtmpl"].replace("%(id)s", info["id"]).replace("%(ext)s", info["ext"])


@pytest.fixture
def app_module(video_teste, monkeypatch):
    import app as _app_module
    import youtube_clipper as yc

    fake_cls = type("FakeYoutubeDL", (_FakeYoutubeDL,), {"origem_video": video_teste})
    fake_mod = type("FakeYtDlpModule", (), {"YoutubeDL": fake_cls})

    processar_original = yc.processar_pedido

    def processar_com_fake(itens, output_dir, qualidade="1080p", on_log=None, ytdlp_module=None):
        return processar_original(itens, output_dir, qualidade=qualidade, on_log=on_log, ytdlp_module=fake_mod)

    monkeypatch.setattr(_app_module, "yt_processar_pedido", processar_com_fake)
    yield _app_module


@pytest.fixture
def client(app_module):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _espera_job(client, job_id, timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = client.get(f"/cortar-youtube/{job_id}/status").get_json()
        if st["status"] != "processando":
            return st
        time.sleep(0.2)
    raise TimeoutError(f"job {job_id} não terminou em {timeout}s")


class TestPaginaInicial:
    def test_pagina_carrega(self, client):
        r = client.get("/cortar-youtube")
        assert r.status_code == 200
        assert "Cortar do YouTube".encode() in r.data

    def test_mostra_as_opcoes_de_qualidade(self, client):
        r = client.get("/cortar-youtube")
        assert b"1080p" in r.data
        assert b"720p" in r.data

    def test_mostra_a_busca_do_youtube(self, client):
        r = client.get("/cortar-youtube")
        assert "Buscar no YouTube".encode() in r.data
        assert b'id="campo-busca"' in r.data
        assert b'onclick="buscarYoutube()"' in r.data

    def test_mostra_botao_de_assistir_e_pegar_tempo(self, client):
        r = client.get("/cortar-youtube")
        assert "Assistir aqui".encode() in r.data
        assert b"btn-pegar-inicio" in r.data
        assert b"btn-pegar-fim" in r.data


class TestBuscarRota:
    def test_busca_com_termo_valido(self, client, monkeypatch):
        import app as app_module

        def fake_buscar(termo, quantidade=15):
            assert termo == "Sweet Home (1989) gameplay"
            return [{
                "id": "n5JqOc-8zBU", "titulo": "Sweet Home (NES) Playthrough",
                "url": "https://www.youtube.com/watch?v=n5JqOc-8zBU",
                "duracao_segundos": 14745, "duracao_formatada": "04:05:45",
                "miniatura_url": "https://i.ytimg.com/vi/n5JqOc-8zBU/hqdefault.jpg",
                "descricao": "", "canal": "NintendoComplete",
            }]
        monkeypatch.setattr(app_module, "buscar_videos_youtube", fake_buscar)

        r = client.get("/cortar-youtube/buscar", query_string={"termo": "Sweet Home (1989) gameplay"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert len(data["resultados"]) == 1
        assert data["resultados"][0]["id"] == "n5JqOc-8zBU"

    def test_busca_sem_termo_400(self, client):
        r = client.get("/cortar-youtube/buscar", query_string={"termo": ""})
        assert r.status_code == 400

    def test_busca_termo_ausente_400(self, client):
        r = client.get("/cortar-youtube/buscar")
        assert r.status_code == 400

    def test_busca_propaga_erro_do_youtube_clipper(self, client, monkeypatch):
        import app as app_module
        from youtube_clipper import YoutubeClipperError

        def fake_buscar_com_erro(termo, quantidade=15):
            raise YoutubeClipperError("yt-dlp não está instalado. Rode: pip install yt-dlp")
        monkeypatch.setattr(app_module, "buscar_videos_youtube", fake_buscar_com_erro)

        r = client.get("/cortar-youtube/buscar", query_string={"termo": "qualquer coisa"})
        assert r.status_code == 400
        assert "yt-dlp" in r.get_json()["erro"]


class TestSubmit:
    def test_submit_sem_itens_400(self, client):
        r = client.post("/cortar-youtube", json={"itens": []})
        assert r.status_code == 400

    def test_submit_valido_inicia_job(self, client):
        r = client.post("/cortar-youtube", json={
            "itens": [{"url": "https://youtube.com/watch?v=x", "trechos": [{"inicio": "00:05", "fim": "00:10"}]}],
        })
        assert r.status_code == 200
        assert "job_id" in r.get_json()

    def test_status_de_job_inexistente_404(self, client):
        r = client.get("/cortar-youtube/nao-existe/status")
        assert r.status_code == 404

    def test_download_antes_de_terminar_404(self, client):
        r = client.post("/cortar-youtube", json={
            "itens": [{"url": "https://x", "trechos": [{"inicio": "00:05", "fim": "00:10"}]}],
        })
        job_id = r.get_json()["job_id"]
        r2 = client.get(f"/cortar-youtube/{job_id}/download")
        assert r2.status_code == 404  # ainda processando (ou pelo menos não confirmado pronto)


class TestFluxoCompleto:
    def test_um_video_um_trecho(self, client):
        r = client.post("/cortar-youtube", json={
            "itens": [{"url": "https://youtube.com/watch?v=teste", "trechos": [
                {"inicio": "00:10", "fim": "00:20", "descricao": "gameplay"},
            ]}],
            "qualidade": "1080p",
        })
        job_id = r.get_json()["job_id"]
        st = _espera_job(client, job_id)
        assert st["status"] == "pronto", st.get("erro")
        assert st["quantidade_clipes"] == 1
        assert st["quantidade_videos"] == 1

    def test_download_do_zip_apos_pronto(self, client):
        r = client.post("/cortar-youtube", json={
            "itens": [{"url": "https://x", "trechos": [{"inicio": "00:05", "fim": "00:15"}]}],
        })
        job_id = r.get_json()["job_id"]
        _espera_job(client, job_id)

        r2 = client.get(f"/cortar-youtube/{job_id}/download")
        assert r2.status_code == 200
        assert len(r2.data) > 500
        assert r2.headers["Content-Type"] in ("application/zip", "application/x-zip-compressed")

    def test_varios_trechos_de_um_video(self, client):
        r = client.post("/cortar-youtube", json={
            "itens": [{"url": "https://x", "trechos": [
                {"inicio": "00:05", "fim": "00:10", "descricao": "um"},
                {"inicio": "00:20", "fim": "00:30", "descricao": "dois"},
                {"inicio": "00:40", "fim": "00:50"},
            ]}],
        })
        job_id = r.get_json()["job_id"]
        st = _espera_job(client, job_id)
        assert st["status"] == "pronto", st.get("erro")
        assert st["quantidade_clipes"] == 3

    def test_varios_videos_de_uma_vez(self, client):
        r = client.post("/cortar-youtube", json={
            "itens": [
                {"url": "https://x/1", "trechos": [{"inicio": "00:05", "fim": "00:10"}]},
                {"url": "https://x/2", "trechos": [{"inicio": "00:20", "fim": "00:30"}]},
            ],
        })
        job_id = r.get_json()["job_id"]
        st = _espera_job(client, job_id)
        assert st["status"] == "pronto", st.get("erro")
        assert st["quantidade_videos"] == 2
        assert st["quantidade_clipes"] == 2

    def test_trecho_invalido_marca_job_como_erro(self, client):
        r = client.post("/cortar-youtube", json={
            "itens": [{"url": "https://x", "trechos": [{"inicio": "00:50", "fim": "00:10"}]}],  # fim antes do inicio
        })
        job_id = r.get_json()["job_id"]
        st = _espera_job(client, job_id)
        assert st["status"] == "erro"
        assert st["erro"]

    def test_log_e_preenchido_durante_o_processamento(self, client):
        r = client.post("/cortar-youtube", json={
            "itens": [{"url": "https://x", "trechos": [{"inicio": "00:05", "fim": "00:10"}]}],
        })
        job_id = r.get_json()["job_id"]
        _espera_job(client, job_id)
        r2 = client.get(f"/cortar-youtube/{job_id}/status")
        assert "Baixando" in r2.get_json()["log"]

    def test_pagina_inicial_linka_do_menu(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Cortar do YouTube".encode() in r.data
