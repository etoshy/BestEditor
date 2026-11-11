"""
conftest.py
============

Fixtures compartilhadas por todos os testes: geram áudio e clipes de
vídeo sintéticos com ffmpeg na hora (nada de rede, nada de arquivos
versionados no repo), e limpam tudo depois.
"""
import os
import shutil
import subprocess

import pytest

# Desativa o isolamento por processo do gerar_audio_isolado() SÓ dentro
# da suíte de testes -- um `monkeypatch`/mock de gerar_audio() feito
# aqui não seria visto por um processo FILHO de verdade (o isolamento
# via multiprocessing cria um interpretador novo do zero). Setado logo
# no import deste arquivo, antes de qualquer teste rodar -- nunca
# definida em produção (só quando o pytest carrega este conftest.py).
os.environ["VOICE_GENERATOR_DESATIVAR_ISOLAMENTO"] = "1"
# 🛡 a guarda contra alucinação não chama o Whisper de verdade nos testes (os testes dela usam um falso)
os.environ.setdefault("VOICE_GENERATOR_SEM_WHISPER_GUARDA", "1")
# a suíte não deve carregar projetos de verdade de jobs/ ao importar o app
os.environ["NARRATION_SITE_NAO_CARREGAR_PROJETOS"] = "1"
# os testes usam o catálogo DE FÁBRICA: os seus extras (assets/darkplanner/extras) ficam de fora
# (os testes que precisam de extras apontam DP_EXTRAS_DIR pra uma pasta própria)
_EXTRAS_VAZIO = "/tmp/_narration_site_tests_extras_vazio"
os.makedirs(_EXTRAS_VAZIO, exist_ok=True)
os.environ.setdefault("DP_EXTRAS_DIR", _EXTRAS_VAZIO)
# 🤖 a IA dos testes começa DESLIGADA e sem a sua chave (os testes da IA usam um transporte falso)
_IA_DADOS = "/tmp/_narration_site_tests_ia"
shutil.rmtree(_IA_DADOS, ignore_errors=True)
os.makedirs(_IA_DADOS, exist_ok=True)
os.environ["IA_DADOS_DIR"] = _IA_DADOS
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)  # 🔷 o Gemini dos testes também começa sem chave
os.environ.pop("GOOGLE_API_KEY", None)
# ⬇ sem pré-download em segundo plano nos testes (não baixa nada da internet)
os.environ["NARRATION_SEM_PREBAIXAR"] = "1"
# 🔁 projetos novos com os padrões de fábrica (sem herdar idioma/canal/voz do teste anterior)
os.environ["ULTIMAS_ESCOLHAS_DESLIGADO"] = "1"

TEST_TMP_ROOT = "/tmp/_narration_site_tests"


@pytest.fixture(scope="session", autouse=True)
def _clean_test_tmp_root():
    """Limpa a pasta de trabalho dos testes uma vez no início da sessão,
    e deixa limpa no final também.
    """
    if os.path.exists(TEST_TMP_ROOT):
        shutil.rmtree(TEST_TMP_ROOT)
    os.makedirs(TEST_TMP_ROOT)
    yield
    shutil.rmtree(TEST_TMP_ROOT, ignore_errors=True)


@pytest.fixture
def tmp_work_dir(tmp_path):
    """Diretório de trabalho isolado por teste (pytest já garante que
    `tmp_path` é único por teste e limpo automaticamente pelo pytest).
    """
    return str(tmp_path)


@pytest.fixture
def synthetic_audio(tmp_work_dir):
    """Gera um áudio sintético (tom puro) de ~9.47s — não é fala de
    verdade, então não serve pra testar o CONTEÚDO da transcrição, mas
    serve perfeitamente pra testar duração, sincronismo e o pipeline de
    montagem de vídeo, que é o que a maioria dos testes precisa.
    """
    path = os.path.join(tmp_work_dir, "audio.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=9.469", "-loglevel", "error", path],
        check=True,
    )
    return path


@pytest.fixture
def synthetic_clips(tmp_work_dir):
    """Três clipes de vídeo sintéticos com durações diferentes — um mais
    curto que um segmento típico (precisa de loop), um mais longo
    (precisa de corte), e um quase exato. Cores sólidas diferentes pra
    dar pra confirmar visualmente (via pixel de um frame) que cada um
    apareceu no tempo certo depois de concatenado.
    """
    clips_dir = os.path.join(tmp_work_dir, "src_clips")
    os.makedirs(clips_dir, exist_ok=True)

    def _make(name, color, duration):
        path = os.path.join(clips_dir, name)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color={color}:size=640x360:rate=25:duration={duration}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", path],
            check=True,
        )
        return path

    return {
        "short_red": _make("short_red.mp4", "red", 2),
        "long_blue": _make("long_blue.mp4", "blue", 6),
        "exact_green": _make("exact_green.mp4", "green", 3),
    }


@pytest.fixture
def sample_pt_segments():
    """Segmentos de transcrição de exemplo (como o Whisper devolveria),
    reutilizados por vários testes de prompt_builder/app.
    """
    return [
        {"start": 0.0, "end": 3.2, "text": "Bem-vindos ao vídeo de hoje sobre a natureza."},
        {"start": 3.2, "end": 6.5, "text": "Vamos explorar as montanhas ao amanhecer."},
        {"start": 6.5, "end": 9.469, "text": "E depois visitar uma cidade movimentada."},
    ]
