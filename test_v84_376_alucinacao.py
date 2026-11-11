"""v84_376: 🛡 o Chatterbox se perdeu (áudio comprido demais pro texto) → gera de novo."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
from tts import voice_generator as vg  # noqa: E402


def _tom(caminho, s):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=300:duration={s}", "-ar", "24000",
                    "-ac", "1", caminho], check=True)


def test_limite():
    assert vg.limite_duracao_fala("x" * 250) == 250 / 9 + 2
    assert vg.limite_duracao_fala("Oi.") == 4.0


def test_repete_quando_sai_comprido_e_fica_com_o_bom(tmp_path):
    duracoes = iter([40.0, 5.0])
    chamadas = []

    def gerar(t, caminho):
        chamadas.append(caminho)
        _tom(caminho, next(duracoes))
    saida = str(tmp_path / "a.wav")
    vg._gerar_com_guarda(gerar, "Texto de umas sessenta letras pra testar a guarda aqui ok.", saida)
    assert len(chamadas) == 2 and abs(vg._duracao_audio_segundos(saida) - 5.0) < 0.1
    assert sorted(os.listdir(tmp_path)) == ["a.wav"]


def test_tudo_comprido_fica_o_mais_curto(tmp_path):
    duracoes = iter([40.0, 20.0, 30.0])
    saida = str(tmp_path / "a.wav")
    vg._gerar_com_guarda(lambda t, c: _tom(c, next(duracoes)), "Frase curta de teste.", saida)
    assert abs(vg._duracao_audio_segundos(saida) - 20.0) < 0.1
    assert sorted(os.listdir(tmp_path)) == ["a.wav"]


def test_normal_gera_uma_vez_so(tmp_path):
    chamadas = []
    vg._gerar_com_guarda(lambda t, c: chamadas.append(c) or _tom(c, 2.0), "Frase normal de teste aqui.", str(tmp_path / "a.wav"))
    assert len(chamadas) == 1
