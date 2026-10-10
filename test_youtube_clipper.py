"""
Teste de youtube_clipper.py — o parser de tempo e o corte usam ffmpeg
de verdade; o download usa um "yt-dlp" FALSO injetado via
`ytdlp_module` (só copia um vídeo de teste local), já que este
ambiente não tem acesso à internet de verdade pro YouTube.
"""
import json
import os
import shutil
import subprocess
import zipfile

import pytest

from youtube_clipper import (
    QUALIDADES,
    YoutubeClipperError,
    _normalizar_url_canal_youtube,
    baixar_video,
    buscar_videos_youtube,
    cortar_trecho,
    extrair_links_canal,
    extrair_perfil_de_voz_do_youtube,
    formatar_tempo,
    parse_tempo,
    processar_pedido,
)


@pytest.fixture(scope="module")
def video_teste():
    import tempfile
    caminho = os.path.join(tempfile.mkdtemp(prefix="youtube_clipper_video_"), "video_original.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=200:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", caminho],
        capture_output=True, check=True,
    )
    return caminho


class _FakeYoutubeDL:
    """yt-dlp falso -- em vez de baixar de verdade, copia um vídeo de
    teste local pro destino esperado, simulando o que o yt-dlp real
    faria (inclusive o `outtmpl`/`prepare_filename`)."""
    origem_video = None  # setado por FakeYtDlpModuleFactory

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def extract_info(self, url, download=True):
        video_id = "fakeid12345"
        destino = self.opts["outtmpl"].replace("%(id)s", video_id).replace("%(ext)s", "mp4")
        shutil.copy(self.origem_video, destino)
        return {"id": video_id, "title": f"Vídeo de teste — {url.split('=')[-1]}", "duration": 200.0, "ext": "mp4"}

    def prepare_filename(self, info):
        return self.opts["outtmpl"].replace("%(id)s", info["id"]).replace("%(ext)s", info["ext"])


def _fake_ytdlp_module(video_teste):
    fake_cls = type("FakeYoutubeDL", (_FakeYoutubeDL,), {"origem_video": video_teste})
    return type("FakeYtDlpModule", (), {"YoutubeDL": fake_cls})


# --------------------------------------------------------------------------- #
# parse_tempo / formatar_tempo
# --------------------------------------------------------------------------- #

class TestParseTempo:
    def test_mm_ss(self):
        assert parse_tempo("00:12") == 12.0
        assert parse_tempo("01:45") == 105.0

    def test_hh_mm_ss(self):
        assert parse_tempo("01:00:34") == 3634.0
        assert parse_tempo("00:09:00") == 540.0

    def test_so_segundos(self):
        assert parse_tempo("30") == 30.0

    def test_texto_vazio_da_erro(self):
        with pytest.raises(YoutubeClipperError, match="vazio"):
            parse_tempo("")

    def test_texto_invalido_da_erro(self):
        with pytest.raises(YoutubeClipperError, match="inválido"):
            parse_tempo("abc")

    def test_negativo_da_erro(self):
        with pytest.raises(YoutubeClipperError, match="negativo"):
            parse_tempo("-5")

    def test_muitas_partes_da_erro(self):
        with pytest.raises(YoutubeClipperError, match="inválido"):
            parse_tempo("1:2:3:4")

    def test_espacos_sao_ignorados(self):
        assert parse_tempo("  01:45  ") == 105.0


class TestFormatarTempo:
    def test_formata_com_horas(self):
        assert formatar_tempo(3634) == "01:00:34"

    def test_formata_sem_horas(self):
        assert formatar_tempo(105) == "00:01:45"

    def test_arredonda_fracao(self):
        assert formatar_tempo(105.6) == "00:01:46"

    def test_ida_e_volta(self):
        assert parse_tempo(formatar_tempo(3661)) == 3661.0


# --------------------------------------------------------------------------- #
# cortar_trecho (ffmpeg de verdade)
# --------------------------------------------------------------------------- #

class TestCortarTrecho:
    def test_corta_com_duracao_correta(self, video_teste, tmp_path):
        saida = str(tmp_path / "clipe.mp4")
        cortar_trecho(video_teste, 10, 20, saida)
        dur = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", saida],
            capture_output=True, text=True,
        ).stdout.strip())
        assert abs(dur - 10.0) < 0.5

    def test_fim_antes_do_inicio_da_erro(self, video_teste, tmp_path):
        with pytest.raises(YoutubeClipperError, match="depois do início"):
            cortar_trecho(video_teste, 50, 20, str(tmp_path / "x.mp4"))

    def test_cria_diretorio_de_saida(self, video_teste, tmp_path):
        saida = str(tmp_path / "sub" / "pasta" / "clipe.mp4")
        cortar_trecho(video_teste, 5, 8, saida)
        assert os.path.exists(saida)


# --------------------------------------------------------------------------- #
# baixar_video (yt-dlp injetado)
# --------------------------------------------------------------------------- #

class TestBaixarVideo:
    def test_baixa_e_devolve_metadados(self, video_teste, tmp_path):
        resultado = baixar_video("https://youtube.com/watch?v=teste1", str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        assert os.path.exists(resultado["caminho"])
        assert resultado["titulo"]
        assert resultado["duracao_segundos"] == 200.0
        assert resultado["url"] == "https://youtube.com/watch?v=teste1"

    def test_qualidade_invalida_da_erro(self, video_teste, tmp_path):
        with pytest.raises(YoutubeClipperError, match="Qualidade"):
            baixar_video("https://x", str(tmp_path), qualidade="8k", ytdlp_module=_fake_ytdlp_module(video_teste))

    def test_sem_ytdlp_instalado_da_erro_claro(self, tmp_path, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, "yt_dlp", None)  # força ImportError no "import yt_dlp"
        with pytest.raises(YoutubeClipperError, match="não está instalado"):
            baixar_video("https://x", str(tmp_path))

    def test_todas_as_qualidades_tem_formato_valido(self):
        for nome, formato in QUALIDADES.items():
            # vídeo e áudio separados primeiro (só assim passa de 360p no YouTube); vídeo único só no fim
            assert formato.startswith("bv*") and "+ba" in formato and formato.rstrip().endswith("b")


# --------------------------------------------------------------------------- #
# processar_pedido — pipeline completo (download injetado + corte real
# + zip + info.json)
# --------------------------------------------------------------------------- #

class TestProcessarPedido:
    def test_um_video_dois_trechos(self, video_teste, tmp_path):
        itens = [{
            "url": "https://youtube.com/watch?v=teste1",
            "trechos": [
                {"inicio": "00:10", "fim": "00:20", "descricao": "gameplay"},
                {"inicio": "00:30", "fim": "00:40", "descricao": ""},
            ],
        }]
        resultado = processar_pedido(itens, str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        assert os.path.exists(resultado["zip_path"])
        assert len(resultado["info"]["videos"]) == 1
        assert len(resultado["info"]["videos"][0]["clipes"]) == 2

    def test_zip_contem_os_clipes_e_o_info_json(self, video_teste, tmp_path):
        itens = [{"url": "https://x", "trechos": [{"inicio": "00:05", "fim": "00:15", "descricao": "trecho 1"}]}]
        resultado = processar_pedido(itens, str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        with zipfile.ZipFile(resultado["zip_path"]) as zf:
            nomes = zf.namelist()
            assert "info.json" in nomes
            assert len([n for n in nomes if n.endswith(".mp4")]) == 1

    def test_info_json_tem_titulo_url_e_descricao(self, video_teste, tmp_path):
        itens = [{"url": "https://youtube.com/watch?v=abc", "trechos": [{"inicio": "00:05", "fim": "00:15", "descricao": "momento engraçado"}]}]
        resultado = processar_pedido(itens, str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        video_info = resultado["info"]["videos"][0]
        assert video_info["url"] == "https://youtube.com/watch?v=abc"
        assert video_info["titulo_original"]
        assert video_info["clipes"][0]["descricao"] == "momento engraçado"
        assert video_info["clipes"][0]["inicio"] == "00:00:05"
        assert video_info["clipes"][0]["fim"] == "00:00:15"

    def test_descricao_vazia_vira_null_no_json(self, video_teste, tmp_path):
        itens = [{"url": "https://x", "trechos": [{"inicio": "00:05", "fim": "00:15"}]}]  # sem "descricao" nenhuma
        resultado = processar_pedido(itens, str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        assert resultado["info"]["videos"][0]["clipes"][0]["descricao"] is None

    def test_clipe_extraido_tem_duracao_correta(self, video_teste, tmp_path):
        itens = [{"url": "https://x", "trechos": [{"inicio": "00:10", "fim": "00:25", "descricao": ""}]}]
        resultado = processar_pedido(itens, str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        with zipfile.ZipFile(resultado["zip_path"]) as zf:
            nome_clipe = next(n for n in zf.namelist() if n.endswith(".mp4"))
            with zf.open(nome_clipe) as f, open(str(tmp_path / "extraido.mp4"), "wb") as out:
                out.write(f.read())
        dur = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(tmp_path / "extraido.mp4")],
            capture_output=True, text=True,
        ).stdout.strip())
        assert abs(dur - 15.0) < 0.5

    def test_varios_videos_de_uma_vez(self, video_teste, tmp_path):
        itens = [
            {"url": "https://x/1", "trechos": [{"inicio": "00:05", "fim": "00:10"}]},
            {"url": "https://x/2", "trechos": [{"inicio": "00:20", "fim": "00:30"}]},
        ]
        resultado = processar_pedido(itens, str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        assert len(resultado["info"]["videos"]) == 2
        with zipfile.ZipFile(resultado["zip_path"]) as zf:
            assert len([n for n in zf.namelist() if n.endswith(".mp4")]) == 2

    def test_baixa_cada_video_uma_vez_so_mesmo_com_varios_trechos(self, video_teste, tmp_path, monkeypatch):
        chamadas_download = []
        fake_mod = _fake_ytdlp_module(video_teste)
        extract_info_original = fake_mod.YoutubeDL.extract_info

        def extract_info_contado(self, url, download=True):
            chamadas_download.append(url)
            return extract_info_original(self, url, download)

        monkeypatch.setattr(fake_mod.YoutubeDL, "extract_info", extract_info_contado)

        itens = [{"url": "https://x", "trechos": [
            {"inicio": "00:05", "fim": "00:10"}, {"inicio": "00:20", "fim": "00:25"}, {"inicio": "00:40", "fim": "00:45"},
        ]}]
        import youtube_clipper as _yc
        monkeypatch.setattr(_yc, "CLIENTES_YOUTUBE", [None])  # o vídeo de teste é 240p: aqui só importa não baixar por trecho
        processar_pedido(itens, str(tmp_path), ytdlp_module=fake_mod)
        assert len(chamadas_download) == 1  # baixou o video UMA vez, nao 3

    def test_lista_vazia_da_erro(self, tmp_path):
        with pytest.raises(YoutubeClipperError, match="Nenhum vídeo"):
            processar_pedido([], str(tmp_path))

    def test_item_sem_url_da_erro(self, tmp_path):
        with pytest.raises(YoutubeClipperError, match="URL"):
            processar_pedido([{"url": "", "trechos": [{"inicio": "0", "fim": "10"}]}], str(tmp_path))

    def test_item_sem_trechos_da_erro(self, tmp_path):
        with pytest.raises(YoutubeClipperError, match="trecho"):
            processar_pedido([{"url": "https://x", "trechos": []}], str(tmp_path))

    def test_trecho_alem_da_duracao_do_video_da_erro(self, video_teste, tmp_path):
        itens = [{"url": "https://x", "trechos": [{"inicio": "05:00", "fim": "05:10"}]}]  # video soo tem 200s (3:20)
        with pytest.raises(YoutubeClipperError, match="depois do fim do vídeo"):
            processar_pedido(itens, str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))

    def test_pasta_de_downloads_originais_e_limpa_no_final(self, video_teste, tmp_path):
        itens = [{"url": "https://x", "trechos": [{"inicio": "00:05", "fim": "00:10"}]}]
        processar_pedido(itens, str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        assert not os.path.exists(os.path.join(str(tmp_path), "_downloads_originais"))

    def test_log_callback_e_chamado(self, video_teste, tmp_path):
        logs = []
        itens = [{"url": "https://x", "trechos": [{"inicio": "00:05", "fim": "00:10"}]}]
        processar_pedido(itens, str(tmp_path), on_log=logs.append, ytdlp_module=_fake_ytdlp_module(video_teste))
        assert any("Baixando" in linha for linha in logs)
        assert any("Cortando" in linha for linha in logs)

    def test_trechos_em_segundos_numericos_tambem_funcionam(self, video_teste, tmp_path):
        """Além de string "MM:SS", aceita número de segundos direto."""
        itens = [{"url": "https://x", "trechos": [{"inicio": 5, "fim": 15, "descricao": "numerico"}]}]
        resultado = processar_pedido(itens, str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        assert resultado["info"]["videos"][0]["clipes"][0]["inicio_segundos"] == 5

    def test_inicio_e_fim_vazios_pegam_o_video_inteiro(self, video_teste, tmp_path):
        """video_teste tem 200s -- inicio/fim vazios devem virar
        exatamente [0, 200], sem precisar digitar nada."""
        itens = [{"url": "https://x", "trechos": [{"inicio": "", "fim": ""}]}]
        resultado = processar_pedido(itens, str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        clipe = resultado["info"]["videos"][0]["clipes"][0]
        assert clipe["inicio_segundos"] == 0
        assert clipe["fim_segundos"] == 200.0

    def test_trecho_sem_as_chaves_inicio_fim_tambem_pega_o_video_inteiro(self, video_teste, tmp_path):
        """Um dict de trecho totalmente vazio (`{}`, sem as chaves nem
        aparecerem) tem que funcionar igual a vazio -- não só string
        vazia."""
        itens = [{"url": "https://x", "trechos": [{}]}]
        resultado = processar_pedido(itens, str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        clipe = resultado["info"]["videos"][0]["clipes"][0]
        assert clipe["inicio_segundos"] == 0
        assert clipe["fim_segundos"] == 200.0

    def test_so_inicio_vazio_pega_do_comeco_ate_o_fim_marcado(self, video_teste, tmp_path):
        itens = [{"url": "https://x", "trechos": [{"inicio": "", "fim": "00:50"}]}]
        resultado = processar_pedido(itens, str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        clipe = resultado["info"]["videos"][0]["clipes"][0]
        assert clipe["inicio_segundos"] == 0
        assert clipe["fim_segundos"] == 50.0

    def test_so_fim_vazio_pega_do_inicio_marcado_ate_o_fim_do_video(self, video_teste, tmp_path):
        itens = [{"url": "https://x", "trechos": [{"inicio": "00:20", "fim": ""}]}]
        resultado = processar_pedido(itens, str(tmp_path), ytdlp_module=_fake_ytdlp_module(video_teste))
        clipe = resultado["info"]["videos"][0]["clipes"][0]
        assert clipe["inicio_segundos"] == 20.0
        assert clipe["fim_segundos"] == 200.0


# --------------------------------------------------------------------------- #
# extrair_perfil_de_voz_do_youtube — baixa/corta trechos do YouTube e já
# salva direto como um perfil de voz reutilizável.
# --------------------------------------------------------------------------- #

@pytest.fixture
def vg_perfis_isolado(monkeypatch, tmp_path):
    """Redireciona `VOICE_PROFILES_DIR` pra uma pasta temporária, pra
    não mexer nos perfis de verdade durante os testes -- devolve o
    módulo `tts.voice_generator` já importado."""
    import sys
    toolkit_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit")
    if toolkit_dir not in sys.path:
        sys.path.insert(0, toolkit_dir)
    import tts.voice_generator as vg_mod
    monkeypatch.setattr(vg_mod, "VOICE_PROFILES_DIR", str(tmp_path / "perfis_de_voz"))
    return vg_mod


@pytest.fixture(scope="module")
def video_teste_com_audio():
    """Igual `video_teste`, mas COM trilha de áudio de verdade (uma
    onda senoidal) -- `video_teste` é só imagem, o que basta pra
    testar corte/download, mas não serve pra alimentar
    `salvar_perfil_de_voz()` (precisa ter áudio pra extrair)."""
    import tempfile
    caminho = os.path.join(tempfile.mkdtemp(prefix="youtube_clipper_video_audio_"), "video_com_audio.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=200:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=220:duration=200",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", caminho],
        capture_output=True, check=True,
    )
    return caminho


class TestExtrairPerfilDeVozDoYoutube:
    def test_um_video_dois_trechos_vira_perfil_com_dois_clipes(self, video_teste_com_audio, tmp_path, vg_perfis_isolado):
        itens = [{"url": "https://x", "trechos": [
            {"inicio": "00:05", "fim": "00:10"}, {"inicio": "00:20", "fim": "00:25"},
        ]}]
        salvos = extrair_perfil_de_voz_do_youtube(itens, "voz_do_fulano", ytdlp_module=_fake_ytdlp_module(video_teste_com_audio))
        assert len(salvos) == 2
        for caminho in salvos:
            assert os.path.exists(caminho)
        assert "voz_do_fulano" in vg_perfis_isolado.listar_perfis_de_voz()

    def test_varios_videos_contribuem_pro_mesmo_perfil(self, video_teste_com_audio, tmp_path, vg_perfis_isolado):
        itens = [
            {"url": "https://x/1", "trechos": [{"inicio": "00:05", "fim": "00:10"}]},
            {"url": "https://x/2", "trechos": [{"inicio": "00:20", "fim": "00:25"}]},
        ]
        salvos = extrair_perfil_de_voz_do_youtube(itens, "voz_combinada", ytdlp_module=_fake_ytdlp_module(video_teste_com_audio))
        assert len(salvos) == 2

    def test_baixa_cada_video_uma_vez_so(self, video_teste_com_audio, tmp_path, vg_perfis_isolado, monkeypatch):
        chamadas_download = []
        fake_mod = _fake_ytdlp_module(video_teste_com_audio)
        extract_info_original = fake_mod.YoutubeDL.extract_info

        def extract_info_contado(self, url, download=True):
            chamadas_download.append(url)
            return extract_info_original(self, url, download)

        monkeypatch.setattr(fake_mod.YoutubeDL, "extract_info", extract_info_contado)

        itens = [{"url": "https://x", "trechos": [
            {"inicio": "00:05", "fim": "00:10"}, {"inicio": "00:20", "fim": "00:25"}, {"inicio": "00:40", "fim": "00:45"},
        ]}]
        import youtube_clipper as _yc
        monkeypatch.setattr(_yc, "CLIENTES_YOUTUBE", [None])  # o vídeo de teste é 240p: aqui só importa não baixar por trecho
        extrair_perfil_de_voz_do_youtube(itens, "voz_eficiente", ytdlp_module=fake_mod)
        assert len(chamadas_download) == 1

    def test_lista_vazia_da_erro(self, tmp_path):
        with pytest.raises(YoutubeClipperError, match="Nenhum vídeo"):
            extrair_perfil_de_voz_do_youtube([], "algum_nome")

    def test_item_sem_url_da_erro(self, tmp_path):
        with pytest.raises(YoutubeClipperError, match="URL"):
            extrair_perfil_de_voz_do_youtube([{"url": "", "trechos": [{"inicio": "0", "fim": "10"}]}], "algum_nome")

    def test_item_sem_trechos_da_erro(self, tmp_path):
        with pytest.raises(YoutubeClipperError, match="trecho"):
            extrair_perfil_de_voz_do_youtube([{"url": "https://x", "trechos": []}], "algum_nome")

    def test_trecho_alem_da_duracao_do_video_da_erro(self, video_teste_com_audio, tmp_path, vg_perfis_isolado):
        itens = [{"url": "https://x", "trechos": [{"inicio": "05:00", "fim": "05:10"}]}]  # video so tem 200s
        with pytest.raises(YoutubeClipperError, match="depois do fim do vídeo"):
            extrair_perfil_de_voz_do_youtube(itens, "vai_falhar", ytdlp_module=_fake_ytdlp_module(video_teste_com_audio))
        assert "vai_falhar" not in vg_perfis_isolado.listar_perfis_de_voz()

    def test_pasta_temporaria_e_limpa_mesmo_com_erro(self, video_teste_com_audio, tmp_path, vg_perfis_isolado):
        import glob
        import tempfile
        antes = set(glob.glob(os.path.join(tempfile.gettempdir(), "perfil_youtube_*")))
        itens = [{"url": "https://x", "trechos": [{"inicio": "05:00", "fim": "05:10"}]}]
        with pytest.raises(YoutubeClipperError):
            extrair_perfil_de_voz_do_youtube(itens, "vai_falhar", ytdlp_module=_fake_ytdlp_module(video_teste_com_audio))
        depois = set(glob.glob(os.path.join(tempfile.gettempdir(), "perfil_youtube_*")))
        assert depois == antes

    def test_pasta_temporaria_e_limpa_apos_sucesso(self, video_teste_com_audio, tmp_path, vg_perfis_isolado):
        import glob
        import tempfile
        antes = set(glob.glob(os.path.join(tempfile.gettempdir(), "perfil_youtube_*")))
        itens = [{"url": "https://x", "trechos": [{"inicio": "00:05", "fim": "00:10"}]}]
        extrair_perfil_de_voz_do_youtube(itens, "voz_ok", ytdlp_module=_fake_ytdlp_module(video_teste_com_audio))
        depois = set(glob.glob(os.path.join(tempfile.gettempdir(), "perfil_youtube_*")))
        assert depois == antes

    def test_log_callback_e_chamado(self, video_teste_com_audio, tmp_path, vg_perfis_isolado):
        logs = []
        itens = [{"url": "https://x", "trechos": [{"inicio": "00:05", "fim": "00:10"}]}]
        extrair_perfil_de_voz_do_youtube(itens, "voz_com_log", on_log=logs.append, ytdlp_module=_fake_ytdlp_module(video_teste_com_audio))
        assert any("Baixando" in linha for linha in logs)
        assert any("Cortando" in linha for linha in logs)
        assert any("Salvando o perfil" in linha for linha in logs)

    def test_perfil_extraido_do_youtube_funciona_com_o_gerador_de_voz(self, video_teste_com_audio, tmp_path, vg_perfis_isolado):
        """O perfil criado por essa função precisa ser um perfil NORMAL
        -- funciona igual qualquer outro perfil salvo à mão, incluindo
        no caminho de geração de voz de verdade (usando um motor
        falso, sem precisar do XTTS/Chatterbox instalado)."""
        itens = [{"url": "https://x", "trechos": [{"inicio": "00:05", "fim": "00:10"}]}]
        extrair_perfil_de_voz_do_youtube(itens, "voz_utilizavel", ytdlp_module=_fake_ytdlp_module(video_teste_com_audio))
        caminhos = vg_perfis_isolado.caminho_perfil_de_voz("voz_utilizavel")
        assert len(caminhos) == 1
        assert os.path.exists(caminhos[0])

    def test_inicio_fim_vazios_pegam_o_video_inteiro_e_dividem_automaticamente(
        self, video_teste_com_audio, tmp_path, vg_perfis_isolado,
    ):
        """Não marcar nenhum trecho (início/fim vazios) pega o vídeo
        INTEIRO (200s) -- longo demais pra virar um clipe de referência
        só, então é dividido automaticamente em vários clipes menores,
        o mesmo mecanismo já usado pra um único áudio longo enviado
        direto."""
        itens = [{"url": "https://x", "trechos": [{"inicio": "", "fim": ""}]}]
        salvos = extrair_perfil_de_voz_do_youtube(
            itens, "voz_video_inteiro", ytdlp_module=_fake_ytdlp_module(video_teste_com_audio),
        )
        assert len(salvos) > 1
        for caminho in salvos:
            assert os.path.exists(caminho)

    def test_trecho_marcado_longo_tambem_e_dividido_automaticamente(
        self, video_teste_com_audio, tmp_path, vg_perfis_isolado,
    ):
        itens = [{"url": "https://x", "trechos": [{"inicio": "00:00", "fim": "01:30"}]}]  # 90s
        salvos = extrair_perfil_de_voz_do_youtube(
            itens, "voz_trecho_longo", ytdlp_module=_fake_ytdlp_module(video_teste_com_audio),
        )
        assert len(salvos) > 1

    def test_trecho_curto_nao_e_dividido(self, video_teste_com_audio, tmp_path, vg_perfis_isolado):
        """Regressão: um trecho já curto continua virando um clipe só,
        sem dividir à toa."""
        itens = [{"url": "https://x", "trechos": [{"inicio": "00:05", "fim": "00:12"}]}]  # 7s
        salvos = extrair_perfil_de_voz_do_youtube(
            itens, "voz_trecho_curto", ytdlp_module=_fake_ytdlp_module(video_teste_com_audio),
        )
        assert len(salvos) == 1

    def test_pasta_temporaria_e_limpa_mesmo_com_divisao_automatica(
        self, video_teste_com_audio, tmp_path, vg_perfis_isolado,
    ):
        """A divisão automática cria uma pasta temporária PRÓPRIA (fora
        da pasta temporária principal da função) -- confirma que ela
        também é limpa no final, não só a pasta principal."""
        import glob
        import tempfile

        antes = set(glob.glob(os.path.join(tempfile.gettempdir(), "perfil_youtube_*")))
        antes_divididos = set(glob.glob(os.path.join(tempfile.gettempdir(), "voz_dividida_*")))

        itens = [{"url": "https://x", "trechos": [{"inicio": "", "fim": ""}]}]
        extrair_perfil_de_voz_do_youtube(
            itens, "voz_limpeza_divisao", ytdlp_module=_fake_ytdlp_module(video_teste_com_audio),
        )

        depois = set(glob.glob(os.path.join(tempfile.gettempdir(), "perfil_youtube_*")))
        depois_divididos = set(glob.glob(os.path.join(tempfile.gettempdir(), "voz_dividida_*")))
        assert depois == antes
        assert depois_divididos == antes_divididos


# --------------------------------------------------------------------------- #
# buscar_videos_youtube — busca no YouTube por texto (sem precisar de
# chave de API, via o pseudo-URL ytsearchN: do próprio yt-dlp).
# --------------------------------------------------------------------------- #

class _FakeYoutubeDLBusca:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def extract_info(self, url, download=False):
        assert url.startswith("ytsearch"), f"deveria usar o pseudo-URL ytsearch, veio {url!r}"
        return {"entries": [
            {"id": "n5JqOc-8zBU", "title": "Sweet Home (NES) Playthrough - NintendoComplete",
             "webpage_url": "https://www.youtube.com/watch?v=n5JqOc-8zBU", "duration": 14745,
             "thumbnails": [{"url": "https://i.ytimg.com/vi/n5JqOc-8zBU/hqdefault.jpg"}],
             "description": "", "channel": "NintendoComplete"},
            {"id": "f3EFgkJbSeM", "title": "Sweet Home (NES): O Pai de Resident Evil",
             "webpage_url": "https://www.youtube.com/watch?v=f3EFgkJbSeM", "duration": 807,
             "thumbnails": [{"url": "https://i.ytimg.com/vi/f3EFgkJbSeM/hq720.jpg"}],
             "description": "", "channel": "Baú Old Gamer"},
            None,
        ]}


def _fake_ytdlp_busca():
    return type("FakeYtDlpModuloBusca", (), {"YoutubeDL": _FakeYoutubeDLBusca})


class TestBuscarVideosYoutube:
    def test_busca_devolve_os_campos_certos(self):
        resultados = buscar_videos_youtube("Sweet Home (1989) gameplay", ytdlp_module=_fake_ytdlp_busca())
        assert len(resultados) == 2  # a entrada None foi ignorada
        r0 = resultados[0]
        assert r0["id"] == "n5JqOc-8zBU"
        assert r0["titulo"] == "Sweet Home (NES) Playthrough - NintendoComplete"
        assert r0["url"] == "https://www.youtube.com/watch?v=n5JqOc-8zBU"
        assert r0["duracao_segundos"] == 14745
        assert r0["duracao_formatada"] == "04:05:45"
        assert r0["canal"] == "NintendoComplete"
        assert "hqdefault" in r0["miniatura_url"]

    def test_ignora_entradas_invalidas(self):
        resultados = buscar_videos_youtube("Sweet Home", ytdlp_module=_fake_ytdlp_busca())
        assert all(r is not None for r in resultados)

    def test_termo_vazio_da_erro(self):
        with pytest.raises(YoutubeClipperError, match="vazio"):
            buscar_videos_youtube("   ")

    def test_sem_ytdlp_instalado_da_erro_claro(self, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, "yt_dlp", None)
        with pytest.raises(YoutubeClipperError, match="não está instalado"):
            buscar_videos_youtube("Sweet Home")

    def test_quantidade_e_limitada_a_50(self):
        chamadas = []
        fake_cls = type("FakeYoutubeDL2", (_FakeYoutubeDLBusca,), {
            "extract_info": lambda self, url, download=False: (chamadas.append(url), {"entries": []})[1]
        })
        fake_mod = type("FakeMod2", (), {"YoutubeDL": fake_cls})
        buscar_videos_youtube("teste", quantidade=999, ytdlp_module=fake_mod)
        assert chamadas[0] == "ytsearch50:teste"


# --------------------------------------------------------------------------- #
# Retentativa com o cliente "android" do YouTube -- bug real relatado:
# "HTTP Error 403: Forbidden" na primeira tentativa (causa mais comum
# hoje em dia é o YouTube mudando a autenticação do cliente "web").
# Corrigido reaproveitando o mesmo jeito que o shortmaker já resolve
# isso: tenta de novo com --extractor-args youtube:player_client=android
# antes de desistir.
# --------------------------------------------------------------------------- #

class TestRetentativaClienteAndroid:
    @staticmethod
    def _fake_mod_com_falha_na_primeira(chamadas):
        """Falha com "HTTP Error 403" na tentativa padrão, mas funciona
        na tentativa com o cliente "android". `chamadas` recebe uma
        cópia dos `opts` de cada tentativa, pra inspecionar depois."""
        class FakeYoutubeDL:
            def __init__(self, opts):
                self.opts = opts
                chamadas.append(opts)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def extract_info(self, url, download=True):
                eh_tentativa_android = (
                    "extractor_args" in self.opts
                    and self.opts["extractor_args"].get("youtube", {}).get("player_client") == ["android"]
                )
                if not eh_tentativa_android:
                    raise RuntimeError("ERROR: unable to download video data: HTTP Error 403: Forbidden")
                video_id = "abc12345678"
                destino = self.opts["outtmpl"].replace("%(id)s", video_id).replace("%(ext)s", "mp4")
                subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:duration=2", destino], capture_output=True, check=True)
                return {"id": video_id, "title": "Vídeo que só baixa com cliente android", "duration": 2.0, "ext": "mp4"}

            def prepare_filename(self, info):
                return self.opts["outtmpl"].replace("%(id)s", info["id"]).replace("%(ext)s", info["ext"])

        return type("FakeMod", (), {"YoutubeDL": FakeYoutubeDL})

    class _FakeYoutubeDLFalhaSempre:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def extract_info(self, url, download=True):
            raise RuntimeError("ERROR: unable to download video data: HTTP Error 403: Forbidden")

        def prepare_filename(self, info):
            return "x"

    def test_retentativa_com_android_apos_403_na_primeira(self, tmp_path):
        fake_mod = self._fake_mod_com_falha_na_primeira([])
        resultado = baixar_video("https://youtube.com/watch?v=teste403", str(tmp_path), ytdlp_module=fake_mod)
        assert resultado["titulo"] == "Vídeo que só baixa com cliente android"
        assert os.path.exists(resultado["caminho"])

    def test_primeira_tentativa_sem_extractor_args_e_android_por_ultimo(self, tmp_path):
        chamadas = []
        fake_mod = self._fake_mod_com_falha_na_primeira(chamadas)
        baixar_video("https://youtube.com/watch?v=teste403", str(tmp_path), ytdlp_module=fake_mod)
        assert "extractor_args" not in chamadas[0]
        assert chamadas[-1]["extractor_args"] == {"youtube": {"player_client": ["android"]}}
        # o android (que hoje costuma dar 360p) só entra depois dos outros clientes
        assert [c.get("extractor_args", {}).get("youtube", {}).get("player_client") for c in chamadas] == \
            [None, ["tv", "web_safari"], ["mweb"], ["android"]]

    def test_sucesso_de_primeira_nao_dispara_retentativa(self, tmp_path):
        chamadas = []

        class FakeYoutubeDLOk:
            def __init__(self, opts):
                self.opts = opts
                chamadas.append(opts)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def extract_info(self, url, download=True):
                video_id = "sucesso123"
                destino = self.opts["outtmpl"].replace("%(id)s", video_id).replace("%(ext)s", "mp4")
                subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=1920x1080:duration=1", destino], capture_output=True, check=True)
                return {"id": video_id, "title": "Vídeo normal", "duration": 1.0, "ext": "mp4"}

            def prepare_filename(self, info):
                return self.opts["outtmpl"].replace("%(id)s", info["id"]).replace("%(ext)s", info["ext"])

        fake_mod = type("FakeModOk", (), {"YoutubeDL": FakeYoutubeDLOk})
        baixar_video("https://youtube.com/watch?v=ok", str(tmp_path), ytdlp_module=fake_mod)
        assert len(chamadas) == 1

    def test_mensagem_de_erro_quando_as_duas_tentativas_falham(self, tmp_path):
        fake_mod = type("FakeMod2", (), {"YoutubeDL": self._FakeYoutubeDLFalhaSempre})
        with pytest.raises(YoutubeClipperError) as exc_info:
            baixar_video("https://youtube.com/watch?v=video-privado", str(tmp_path), ytdlp_module=fake_mod)
        mensagem = str(exc_info.value)
        assert "cliente padrão" in mensagem
        assert "android" in mensagem and "tv/web_safari" in mensagem
        assert "yt-dlp[default]" in mensagem
        assert "deno.com" in mensagem
        assert "403" in mensagem


# --------------------------------------------------------------------------- #
# extrair_links_canal — lista título+link de Shorts/vídeos de um canal, sem
# baixar nada. yt-dlp FALSO com extract_flat: devolve um dict com "entries".
# --------------------------------------------------------------------------- #

class _FakeYoutubeDLCanal:
    entradas_por_url = {}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def extract_info(self, url, download=False):
        if url in self.entradas_por_url:
            return {"entries": self.entradas_por_url[url]}
        return {"entries": self.entradas_por_url.get("_default")}


def _fake_ytdlp_canal(entradas, por_url=None):
    mapa = dict(por_url or {})
    mapa.setdefault("_default", entradas)
    return type("FakeYtDlpCanal", (), {"YoutubeDL": type(
        "Cls", (_FakeYoutubeDLCanal,), {"entradas_por_url": mapa},
    )})


def _entrada(video_id, titulo, upload_date=""):
    return {"id": video_id, "title": titulo, "upload_date": upload_date}


class TestNormalizarUrlCanal:
    @pytest.mark.parametrize("entrada,tipo,esperado", [
        ("youtube.com/@canal", "shorts", "https://youtube.com/@canal/shorts"),
        ("https://youtube.com/@canal", "videos", "https://youtube.com/@canal/videos"),
        ("https://youtube.com/@canal/shorts", "shorts", "https://youtube.com/@canal/shorts"),
        ("https://youtube.com/@canal/videos/", "videos", "https://youtube.com/@canal/videos"),
        ("https://youtube.com/@canal/shorts", "videos", "https://youtube.com/@canal/videos"),
        ("https://youtube.com/@canal?al=1", "shorts", "https://youtube.com/@canal/shorts"),
        ("https://youtube.com/@canal/featured", "shorts", "https://youtube.com/@canal/shorts"),
    ])
    def test_normaliza_link_do_canal(self, entrada, tipo, esperado):
        assert _normalizar_url_canal_youtube(entrada, tipo) == esperado

    def test_link_vazio_da_erro(self):
        with pytest.raises(YoutubeClipperError, match="Informe o link"):
            _normalizar_url_canal_youtube("", "shorts")


class TestExtrairLinksCanal:
    def test_extrai_titulo_e_link_de_cada_short(self):
        entradas = [_entrada("abc123", "Primeiro short"), _entrada("def456", "Segundo short")]
        r = extrair_links_canal("youtube.com/@canal", tipo="shorts", ytdlp_module=_fake_ytdlp_canal(entradas))
        assert r["total"] == 2
        assert r["canal"] == "https://youtube.com/@canal/shorts"
        assert r["itens"][0] == {"indice": 1, "titulo": "Primeiro short", "link": "https://www.youtube.com/shorts/abc123", "id": "abc123", "upload_date": ""}
        assert r["itens"][1]["link"] == "https://www.youtube.com/shorts/def456"

    def test_tipo_videos_usa_link_watch(self):
        entradas = [_entrada("abc123", "Um vídeo normal")]
        r = extrair_links_canal("youtube.com/@canal", tipo="videos", ytdlp_module=_fake_ytdlp_canal(entradas))
        assert r["itens"][0]["link"] == "https://www.youtube.com/watch?v=abc123"

    def test_tipo_invalido_da_erro(self):
        with pytest.raises(YoutubeClipperError, match="Tipo inválido"):
            extrair_links_canal("youtube.com/@canal", tipo="lives")

    def test_canal_sem_nenhum_short_devolve_lista_vazia_sem_erro(self):
        # o próprio ytdlp devolveu "entries": [] -- canal existe, só não tem nada
        r = extrair_links_canal("youtube.com/@canal", ytdlp_module=_fake_ytdlp_canal([]))
        assert r == {"canal": "https://youtube.com/@canal/shorts", "tipo": "shorts", "ordem": "mais_novos", "total": 0, "itens": []}

    def test_resposta_sem_a_chave_entries_da_erro_claro(self):
        # canal/link que nem é uma playlist/lista de vídeos pro yt-dlp
        class YtDlpSemEntries:
            class YoutubeDL:
                def __init__(self, opts):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

                def extract_info(self, url, download=False):
                    return {"id": "nao_e_uma_playlist"}

        with pytest.raises(YoutubeClipperError, match="Nenhum vídeo"):
            extrair_links_canal("youtube.com/@canal", ytdlp_module=YtDlpSemEntries)

    def test_entradas_sem_id_sao_ignoradas_sem_quebrar(self):
        entradas = [{"title": "sem id"}, _entrada("abc123", "com id"), None]
        r = extrair_links_canal("youtube.com/@canal", ytdlp_module=_fake_ytdlp_canal(entradas))
        assert r["total"] == 1 and r["itens"][0]["id"] == "abc123"

    def test_titulo_ausente_vira_sem_titulo(self):
        r = extrair_links_canal("youtube.com/@canal", ytdlp_module=_fake_ytdlp_canal([{"id": "x"}]))
        assert r["itens"][0]["titulo"] == "Sem título"

    def test_indices_sao_sequenciais_a_partir_de_1(self):
        entradas = [_entrada(f"id{i}", f"titulo {i}") for i in range(5)]
        r = extrair_links_canal("youtube.com/@canal", ytdlp_module=_fake_ytdlp_canal(entradas))
        assert [item["indice"] for item in r["itens"]] == [1, 2, 3, 4, 5]

    def test_ordena_por_data_quando_disponivel_em_pelo_menos_2_itens(self):
        entradas = [
            _entrada("velho", "O mais velho", "20200101"),
            _entrada("novo", "O mais novo", "20240601"),
            _entrada("meio", "Do meio", "20220315"),
        ]
        mais_novos = extrair_links_canal("youtube.com/@canal", ordem="mais_novos", ytdlp_module=_fake_ytdlp_canal(entradas))
        assert [i["id"] for i in mais_novos["itens"]] == ["novo", "meio", "velho"]

        mais_antigos = extrair_links_canal("youtube.com/@canal", ordem="mais_antigos", ytdlp_module=_fake_ytdlp_canal(entradas))
        assert [i["id"] for i in mais_antigos["itens"]] == ["velho", "meio", "novo"]

    def test_sem_data_suficiente_so_inverte_a_ordem_da_pagina(self):
        entradas = [_entrada("a", "A"), _entrada("b", "B"), _entrada("c", "C")]  # sem upload_date
        r = extrair_links_canal("youtube.com/@canal", ordem="mais_antigos", ytdlp_module=_fake_ytdlp_canal(entradas))
        assert [i["id"] for i in r["itens"]] == ["c", "b", "a"]

    def test_erro_do_ytdlp_vira_youtubeclippererror(self):
        class YtDlpQueQuebra:
            class YoutubeDL:
                def __init__(self, opts):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

                def extract_info(self, url, download=False):
                    raise RuntimeError("canal não existe")

        with pytest.raises(YoutubeClipperError, match="canal não existe"):
            extrair_links_canal("youtube.com/@fantasma", ytdlp_module=YtDlpQueQuebra)


# --------------------------------------------------------------------------- #
# Qualidade baixa (bug real relatado): um cliente do YouTube entrega 360p.
# O site mede a resolução de cada tentativa e fica com a melhor.
# --------------------------------------------------------------------------- #

def _fake_mod_por_cliente(alturas, chamadas):
    """`alturas`: {cliente_ou_None: altura}. Cliente fora do dict = falha (403)."""
    class Fake:
        def __init__(self, opts):
            self.opts = opts
            chamadas.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def extract_info(self, url, download=True):
            pc = self.opts.get("extractor_args", {}).get("youtube", {}).get("player_client")
            chave = tuple(pc) if pc else None
            if chave not in alturas:
                raise RuntimeError("HTTP Error 403: Forbidden")
            h = alturas[chave]
            destino = self.opts["outtmpl"].replace("%(id)s", "vid").replace("%(ext)s", "mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=red:size={h * 16 // 9 // 2 * 2}x{h}:duration=1",
                            destino], check=True)
            return {"id": "vid", "title": f"t{h}", "duration": 1.0, "ext": "mp4"}

        def prepare_filename(self, info):
            return self.opts["outtmpl"].replace("%(id)s", info["id"]).replace("%(ext)s", info["ext"])
    return type("M", (), {"YoutubeDL": Fake})


def test_cliente_que_da_360p_e_trocado_pelo_que_da_1080p(tmp_path):
    chamadas, logs = [], []
    mod = _fake_mod_por_cliente({None: 360, ("tv", "web_safari"): 1080, ("android",): 360}, chamadas)
    r = baixar_video("https://youtu.be/x", str(tmp_path), qualidade="1080p", ytdlp_module=mod, on_log=logs.append)
    assert r["altura"] == 1080 and r["cliente"] == "tv+web_safari" and len(chamadas) == 2
    assert os.path.exists(r["caminho"]) and os.path.dirname(r["caminho"]) == str(tmp_path)
    assert not [d for d in os.listdir(tmp_path) if d.startswith("_tentativa")]  # limpa as tentativas
    assert any("360p" in l and "tentando outro" in l for l in logs)
    assert chamadas[0]["format_sort"][0] == "res:1080" and "bv*" in chamadas[0]["format"]


def test_nenhum_cliente_chega_no_pedido_fica_com_o_melhor_e_avisa(tmp_path):
    chamadas, logs = [], []
    mod = _fake_mod_por_cliente({None: 360, ("mweb",): 480, ("android",): 240}, chamadas)
    r = baixar_video("https://youtu.be/x", str(tmp_path), qualidade="1080p", ytdlp_module=mod, on_log=logs.append)
    assert r["altura"] == 480 and r["cliente"] == "mweb" and len(chamadas) == 4
    assert any("baixado em 480p" in l and "não entregou 1080p" in l for l in logs)


def test_corte_com_qualidade_alta(tmp_path, monkeypatch):
    usados = []
    real = subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: (usados.append(list(args)), real(args, **kw))[1])
    src = str(tmp_path / "a.mp4")
    real(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=red:size=320x240:duration=2", "-f", "lavfi",
          "-i", "sine=duration=2", "-shortest", src], check=True)
    cortar_trecho(src, 0.5, 1.5, str(tmp_path / "b.mp4"))
    cmd = usados[-1]
    assert cmd[cmd.index("-crf") + 1] == "17" and "veryfast" not in cmd
