"""
Testes de dublagem.py. ffmpeg/ffprobe de verdade (arquivos curtos
gerados na hora), mas Demucs e Argos Translate são sempre FALSOS/
injetados (pesados demais, e não instalados neste sandbox) — o motor de
TTS também é sempre uma função falsa (gera um tom simples com a duração
pedida), pra não depender de nenhum modelo de voz de verdade.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dublagem as d  # noqa: E402


# --------------------------------------------------------------------------- #
# fixtures de áudio (ffmpeg de verdade)
# --------------------------------------------------------------------------- #
def _tom(caminho, freq=300, duracao=1.0):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duracao}", str(caminho)],
        capture_output=True, check=True,
    )
    return str(caminho)


@pytest.fixture
def audio_1s(tmp_path):
    return _tom(tmp_path / "audio_1s.wav", 300, 1.0)


def _picos_por_trecho(caminho, janelas):
    """[(peak_db_ou_None_se_-inf, ...)] pra cada (inicio, fim) em `janelas`."""
    saida = []
    for inicio, fim in janelas:
        r = subprocess.run(
            ["ffmpeg", "-i", str(caminho), "-af", f"atrim={inicio}:{fim},astats", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        linhas = [l for l in r.stderr.splitlines() if "Peak level dB" in l]
        if not linhas:
            saida.append(None)
            continue
        valor = linhas[0].split(":")[-1].strip()
        saida.append(None if valor == "-inf" else float(valor))
    return saida


# --------------------------------------------------------------------------- #
# ajuste de velocidade (atempo)
# --------------------------------------------------------------------------- #
class TestAjusteDeVelocidade:
    @pytest.mark.parametrize("fator,esperado_partes", [
        (1.0, 1), (1.5, 1), (2.0, 1), (3.0, 2), (0.3, 2), (0.1, 4),
    ])
    def test_cadeia_de_filtros_fica_dentro_de_0_5_a_2_0_por_instancia(self, fator, esperado_partes):
        filtro = d._cadeia_filtros_atempo(fator)
        assert filtro.count("atempo=") == esperado_partes
        for parte in filtro.split(","):
            valor = float(parte.split("=")[1])
            assert 0.5 <= round(valor, 3) <= 2.0

    def test_produto_das_partes_reproduz_o_fator_pedido(self):
        import math
        for fator in (0.15, 0.6, 1.0, 1.8, 3.5, 5.0):
            filtro = d._cadeia_filtros_atempo(fator)
            produto = math.prod(float(p.split("=")[1]) for p in filtro.split(","))
            assert abs(produto - max(0.05, fator)) < 0.01

    def test_fator_proximo_de_1_so_copia_o_arquivo(self, audio_1s, tmp_path):
        saida = str(tmp_path / "saida.wav")
        d.ajustar_velocidade(audio_1s, saida, 1.005)
        assert abs(d._duracao_audio_segundos(saida) - 1.0) < 0.05

    def test_acelerar_encurta_e_desacelerar_alonga(self, audio_1s, tmp_path):
        rapido = str(tmp_path / "rapido.wav")
        devagar = str(tmp_path / "devagar.wav")
        d.ajustar_velocidade(audio_1s, rapido, 2.0)
        d.ajustar_velocidade(audio_1s, devagar, 0.5)
        assert abs(d._duracao_audio_segundos(rapido) - 0.5) < 0.05
        assert abs(d._duracao_audio_segundos(devagar) - 2.0) < 0.05

    def test_fator_extremo_fora_de_0_5_a_2_0_tambem_funciona(self, audio_1s, tmp_path):
        saida = str(tmp_path / "saida.wav")
        d.ajustar_velocidade(audio_1s, saida, 4.0)
        assert abs(d._duracao_audio_segundos(saida) - 0.25) < 0.05


class TestDuracaoAudio:
    def test_mede_duracao_real(self, audio_1s):
        assert abs(d._duracao_audio_segundos(audio_1s) - 1.0) < 0.05

    def test_arquivo_invalido_da_erro_claro(self, tmp_path):
        ruim = tmp_path / "nao_e_audio.wav"
        ruim.write_bytes(b"lixo")
        with pytest.raises(d.DublagemError, match="duração"):
            d._duracao_audio_segundos(str(ruim))


# --------------------------------------------------------------------------- #
# posicionamento na linha do tempo (adelay + amix, sem pydub)
# --------------------------------------------------------------------------- #
class TestMontarTrilhaComPosicoes:
    def test_dura_o_tempo_total_pedido(self, tmp_path, audio_1s):
        saida = str(tmp_path / "trilha.wav")
        d._montar_trilha_com_posicoes([(audio_1s, 0)], 5000, saida)
        assert abs(d._duracao_audio_segundos(saida) - 5.0) < 0.1

    def test_cada_trecho_soa_na_posicao_certa_e_silencio_no_resto(self, tmp_path):
        seg1 = _tom(tmp_path / "seg1.wav", 300, 1.0)
        seg2 = _tom(tmp_path / "seg2.wav", 600, 1.0)
        saida = str(tmp_path / "trilha.wav")
        d._montar_trilha_com_posicoes([(seg1, 0), (seg2, 5000)], 8000, saida)

        picos = _picos_por_trecho(saida, [(0, 1), (2, 4), (5, 6), (6.5, 8)])
        assert picos[0] is not None   # som no início
        assert picos[1] is None       # silêncio no meio
        assert picos[2] is not None   # som aos 5s
        assert picos[3] is None       # silêncio no fim

    def test_um_trecho_so_sem_deslocamento(self, tmp_path, audio_1s):
        saida = str(tmp_path / "trilha.wav")
        d._montar_trilha_com_posicoes([(audio_1s, 0)], 2000, saida)
        picos = _picos_por_trecho(saida, [(0, 1), (1.2, 2)])
        assert picos[0] is not None
        assert picos[1] is None


# --------------------------------------------------------------------------- #
# separar_voz_musica (Demucs FALSO)
# --------------------------------------------------------------------------- #
class TestSepararVozMusica:
    def _demucs_falso(self, tmp_path, modelo="htdemucs"):
        def _runner(cmd, capture_output=True, text=True):
            # cmd: [python, -m, demucs, --two-stems, vocals, -n, modelo, -d, device, -o, out_dir, audio]
            out_dir = cmd[cmd.index("-o") + 1]
            audio_path = cmd[-1]
            stem = os.path.splitext(os.path.basename(audio_path))[0]
            pasta = os.path.join(out_dir, modelo, stem)
            os.makedirs(pasta, exist_ok=True)
            _tom(os.path.join(pasta, "vocals.wav"), 300, 0.5)
            _tom(os.path.join(pasta, "no_vocals.wav"), 100, 0.5)
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return _runner

    def test_devolve_os_dois_caminhos(self, tmp_path, audio_1s):
        vocals, no_vocals = d.separar_voz_musica(audio_1s, str(tmp_path / "out"), demucs_runner=self._demucs_falso(tmp_path))
        assert os.path.exists(vocals) and os.path.exists(no_vocals)
        assert vocals.endswith("vocals.wav") and no_vocals.endswith("no_vocals.wav")

    def test_demucs_com_erro_vira_dublagemerror(self, tmp_path, audio_1s):
        def _runner(cmd, capture_output=True, text=True):
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": "demucs explodiu"})()

        with pytest.raises(d.DublagemError, match="demucs explodiu"):
            d.separar_voz_musica(audio_1s, str(tmp_path / "out"), demucs_runner=_runner)

    def test_arquivos_esperados_ausentes_da_erro_claro(self, tmp_path, audio_1s):
        def _runner(cmd, capture_output=True, text=True):
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()  # não cria nada

        with pytest.raises(d.DublagemError, match="não encontrei"):
            d.separar_voz_musica(audio_1s, str(tmp_path / "out"), demucs_runner=_runner)

    def test_log_recebe_mensagem_de_progresso(self, tmp_path, audio_1s):
        logs = []
        d.separar_voz_musica(audio_1s, str(tmp_path / "out"), demucs_runner=self._demucs_falso(tmp_path), on_log=logs.append)
        assert any("Demucs" in l for l in logs)


# --------------------------------------------------------------------------- #
# tradução (Argos Translate FALSO)
# --------------------------------------------------------------------------- #
class _FakeArgosPackage:
    def __init__(self, pares_instalados=(), pares_disponiveis=()):
        self.instalados = set(pares_instalados)
        self.disponiveis = [
            type("Pkg", (), {
                "from_code": de, "to_code": para,
                "download": lambda self, de=de, para=para: f"pkg_{de}_{para}.argosmodel",
            })()
            for de, para in pares_disponiveis
        ]

    def update_package_index(self):
        pass

    def get_available_packages(self):
        return self.disponiveis

    def get_installed_packages(self):
        return [type("Pkg", (), {"from_code": de, "to_code": para})() for de, para in self.instalados]

    def install_from_path(self, caminho):
        # o "caminho" falso embute o par (ver download() acima) -- é
        # assim que o fake sabe QUAL par acabou de ser instalado.
        nome = os.path.basename(caminho).removesuffix(".argosmodel")
        de, para = nome.split("_", 1)[1].rsplit("_", 1)
        self.instalados.add((de, para))


class _FakeArgosTranslateNamespace:
    """Simula o submódulo `argostranslate.translate` (que tem uma FUNÇÃO
    `translate(texto, de, para)` dentro, não uma classe)."""
    def __init__(self, traducoes, chamadas):
        self._traducoes = traducoes
        self._chamadas = chamadas

    def translate(self, texto, de, para):
        self._chamadas.append((texto, de, para))
        return self._traducoes.get(texto, f"[{para}] {texto}")


class _FakeArgosTranslate:
    def __init__(self, package, traducoes=None):
        self.package = package
        self.chamadas = []
        self.translate = _FakeArgosTranslateNamespace(traducoes or {}, self.chamadas)


def _fake_argos(pares_instalados=(), pares_disponiveis=(), traducoes=None):
    pkg = _FakeArgosPackage(pares_instalados, pares_disponiveis)
    mod = _FakeArgosTranslate(pkg, traducoes)
    return mod


class TestGarantirPacoteTraducao:
    def test_mesmo_idioma_nao_faz_nada(self):
        d.garantir_pacote_traducao("pt", "pt", argostranslate_module=_fake_argos())

    def test_pacote_ja_instalado_nao_baixa_de_novo(self):
        mod = _fake_argos(pares_instalados={("en", "pt")})
        d.garantir_pacote_traducao("en", "pt", argostranslate_module=mod)  # não levanta

    def test_instala_pacote_direto_disponivel(self):
        mod = _fake_argos(pares_disponiveis={("en", "pt")})
        d.garantir_pacote_traducao("en", "pt", argostranslate_module=mod)
        assert ("en", "pt") in mod.package.instalados

    def test_sem_pacote_direto_tenta_caminho_via_ingles(self):
        mod = _fake_argos(pares_disponiveis={("ja", "en"), ("en", "pt")})
        d.garantir_pacote_traducao("ja", "pt", argostranslate_module=mod)
        assert ("ja", "en") in mod.package.instalados and ("en", "pt") in mod.package.instalados

    def test_sem_nenhum_caminho_da_erro_claro(self):
        mod = _fake_argos()
        with pytest.raises(d.DublagemError, match="Não há pacote"):
            d.garantir_pacote_traducao("ja", "pt", argostranslate_module=mod)

    def test_sem_pacote_instalado_da_erro_de_dependencia(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def fake_import(nome, *a, **kw):
            if nome.startswith("argostranslate"):
                raise ImportError("no module")
            return real_import(nome, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(d.DublagemError, match="argostranslate"):
            d.garantir_pacote_traducao("en", "pt")


class TestTraduzirSegmentos:
    def _segmentos(self):
        return [
            {"start": 0.0, "end": 1.0, "text": "Hello"},
            {"start": 1.0, "end": 2.0, "text": "World"},
        ]

    def test_traduz_cada_segmento_preservando_tempos(self):
        mod = _fake_argos(pares_instalados={("en", "pt")}, traducoes={"Hello": "Olá", "World": "Mundo"})
        r = d.traduzir_segmentos(self._segmentos(), "en", "pt", argostranslate_module=mod)
        assert r[0]["text_traduzido"] == "Olá" and r[0]["start"] == 0.0 and r[0]["end"] == 1.0
        assert r[1]["text_traduzido"] == "Mundo"
        assert r[0]["text"] == "Hello"  # o texto original continua lá

    def test_mesmo_idioma_nao_chama_traducao(self):
        mod = _fake_argos()
        r = d.traduzir_segmentos(self._segmentos(), "pt", "pt", argostranslate_module=mod)
        assert r[0]["text_traduzido"] == "Hello"
        assert mod.chamadas == []

    def test_segmento_com_texto_vazio_nao_e_traduzido(self):
        mod = _fake_argos(pares_instalados={("en", "pt")})
        segs = [{"start": 0.0, "end": 1.0, "text": "   "}]
        r = d.traduzir_segmentos(segs, "en", "pt", argostranslate_module=mod)
        assert r[0]["text_traduzido"] == "   "
        assert mod.chamadas == []

    def test_log_recebe_progresso(self):
        mod = _fake_argos(pares_instalados={("en", "pt")})
        logs = []
        d.traduzir_segmentos(self._segmentos(), "en", "pt", on_log=logs.append, argostranslate_module=mod)
        assert any("Traduzindo" in l for l in logs)


# --------------------------------------------------------------------------- #
# gerar_narracao_sincronizada (motor de TTS FALSO)
# --------------------------------------------------------------------------- #
def _tts_falso(duracoes_por_texto=None, log=None):
    """Devolve uma gerar_audio_fn falsa: gera um tom cuja duração pode
    ser controlada por texto (pra testar o ajuste de velocidade de
    verdade) -- por padrão, gera sempre 1s."""
    duracoes_por_texto = duracoes_por_texto or {}

    def _fn(engine, texto, output_path, **kwargs):
        if log is not None:
            log.append((engine, texto, dict(kwargs)))
        duracao = duracoes_por_texto.get(texto, 1.0)
        _tom(output_path, 300, duracao)

    return _fn


class TestGerarNarracaoSincronizada:
    def _segmentos_pt(self):
        return [
            {"start": 0.0, "end": 2.0, "text": "Hello", "text_traduzido": "Olá mundo"},
            {"start": 5.0, "end": 7.0, "text": "World", "text_traduzido": "Como vai você"},
        ]

    def test_gera_um_trecho_por_segmento_na_posicao_certa(self, tmp_path):
        saida = str(tmp_path / "narracao.wav")
        chamadas = []
        d.gerar_narracao_sincronizada(
            self._segmentos_pt(), saida, duracao_total_segundos=8.0,
            gerar_audio_fn=_tts_falso(log=chamadas),
        )
        assert os.path.exists(saida)
        assert len(chamadas) == 2
        assert chamadas[0][1] == "Olá mundo" and chamadas[1][1] == "Como vai você"
        picos = _picos_por_trecho(saida, [(0, 1.8), (3, 4.5), (5, 6.8)])
        assert picos[0] is not None and picos[1] is None and picos[2] is not None

    def test_texto_limpo_antes_de_ir_pro_tts(self, tmp_path):
        segs = [{"start": 0.0, "end": 1.0, "text": "x", "text_traduzido": '"Olá..." (teste)'}]
        chamadas = []
        d.gerar_narracao_sincronizada(segs, str(tmp_path / "n.wav"), 2.0, gerar_audio_fn=_tts_falso(log=chamadas))
        assert '"' not in chamadas[0][1] and "(" not in chamadas[0][1]

    def test_segmento_so_com_pontuacao_e_pulado(self, tmp_path):
        segs = [
            {"start": 0.0, "end": 1.0, "text": "x", "text_traduzido": "..."},
            {"start": 2.0, "end": 3.0, "text": "y", "text_traduzido": "Oi"},
        ]
        chamadas = []
        d.gerar_narracao_sincronizada(segs, str(tmp_path / "n.wav"), 4.0, gerar_audio_fn=_tts_falso(log=chamadas))
        assert len(chamadas) == 1 and chamadas[0][1] == "Oi"

    def test_nenhum_segmento_com_texto_da_erro_claro(self, tmp_path):
        segs = [{"start": 0.0, "end": 1.0, "text": "x", "text_traduzido": "..."}]
        with pytest.raises(d.DublagemError, match="silêncio total"):
            d.gerar_narracao_sincronizada(segs, str(tmp_path / "n.wav"), 2.0, gerar_audio_fn=_tts_falso())

    def test_engine_de_clonagem_recebe_speaker_wav(self, tmp_path):
        segs = [{"start": 0.0, "end": 1.0, "text": "x", "text_traduzido": "Oi"}]
        chamadas = []
        ref = str(tmp_path / "ref.wav")
        _tom(ref, 300, 1.0)
        d.gerar_narracao_sincronizada(
            segs, str(tmp_path / "n.wav"), 2.0, engine="xtts", voz_referencia=ref,
            gerar_audio_fn=_tts_falso(log=chamadas),
        )
        assert chamadas[0][2]["speaker_wav"] == ref
        assert chamadas[0][2]["idioma"] == "pt"

    def test_engine_sem_clonagem_ignora_voz_referencia(self, tmp_path):
        segs = [{"start": 0.0, "end": 1.0, "text": "x", "text_traduzido": "Oi"}]
        chamadas = []
        ref = str(tmp_path / "ref.wav")
        _tom(ref, 300, 1.0)
        d.gerar_narracao_sincronizada(
            segs, str(tmp_path / "n.wav"), 2.0, engine="piper", voz_referencia=ref,
            gerar_audio_fn=_tts_falso(log=chamadas),
        )
        assert "speaker_wav" not in chamadas[0][2]

    def test_velocidade_e_limitada_pelos_extremos_configurados(self, tmp_path):
        # texto gerado MUITO mais longo que a janela -- teria que acelerar
        # mais que o permitido; o resultado fica mais longo que a janela
        # (não corta a fala), mas nunca mais rápido que velocidade_max.
        segs = [{"start": 0.0, "end": 1.0, "text": "x", "text_traduzido": "fala longa"}]
        r = d.gerar_narracao_sincronizada(
            segs, str(tmp_path / "n.wav"), 10.0,
            gerar_audio_fn=_tts_falso({"fala longa": 5.0}), velocidade_max=1.5,
        )
        # duração original 5s / velocidade_max 1.5 = ~3.33s (não os 1s da janela,
        # nem os 5s originais sem limite nenhum -- tem que ficar ENTRE os dois)
        picos = _picos_por_trecho(r, [(1.2, 3.2), (3.6, 5.0)])
        assert picos[0] is not None  # ainda tocando bem além da janela de 1s (não foi limitado a 1s)
        assert picos[1] is None      # mas já parou antes dos 5s originais (respeitou o limite de velocidade)

    def test_tts_kwargs_extra_sao_repassados(self, tmp_path):
        segs = [{"start": 0.0, "end": 1.0, "text": "x", "text_traduzido": "Oi"}]
        chamadas = []
        d.gerar_narracao_sincronizada(
            segs, str(tmp_path / "n.wav"), 2.0, engine="kokoro",
            tts_kwargs={"nome_voz": "af_bella"}, gerar_audio_fn=_tts_falso(log=chamadas),
        )
        assert chamadas[0][2]["nome_voz"] == "af_bella"


# --------------------------------------------------------------------------- #
# misturar_audios / remontar_video_com_audio
# --------------------------------------------------------------------------- #
class TestMisturarAudios:
    def test_mistura_com_normalizacao(self, tmp_path):
        fundo = _tom(tmp_path / "fundo.wav", 100, 2.0)
        voz = _tom(tmp_path / "voz.wav", 400, 2.0)
        saida = str(tmp_path / "mix.wav")
        d.misturar_audios(fundo, voz, saida)
        assert os.path.exists(saida)
        assert abs(d._duracao_audio_segundos(saida) - 2.0) < 0.1

    def test_mistura_sem_normalizacao(self, tmp_path):
        fundo = _tom(tmp_path / "fundo.wav", 100, 1.0)
        voz = _tom(tmp_path / "voz.wav", 400, 1.0)
        saida = str(tmp_path / "mix.wav")
        d.misturar_audios(fundo, voz, saida, normalizar=False)
        assert os.path.exists(saida)


class TestRemontarVideoComAudio:
    def test_junta_video_e_audio(self, tmp_path):
        video = str(tmp_path / "video.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=2:rate=10",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", video],
            capture_output=True, check=True,
        )
        audio = _tom(tmp_path / "audio.wav", 300, 2.0)
        saida = str(tmp_path / "final.mp4")
        d.remontar_video_com_audio(video, audio, saida)
        assert os.path.exists(saida)
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", saida],
            capture_output=True, text=True,
        )
        assert "video" in r.stdout and "audio" in r.stdout

    def test_video_inexistente_da_erro_claro(self, tmp_path):
        audio = _tom(tmp_path / "audio.wav", 300, 1.0)
        with pytest.raises(d.DublagemError, match="remontar"):
            d.remontar_video_com_audio(str(tmp_path / "fantasma.mp4"), audio, str(tmp_path / "saida.mp4"))
