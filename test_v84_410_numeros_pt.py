"""v84_410: 🔢 números, datas e romanos por extenso antes do Chatterbox pt (o "1815" saía estranho, "XIV" letra por letra)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
from tts import numeros_pt as N  # noqa: E402
from tts import voice_generator as vg  # noqa: E402


def test_extenso():
    casos = {0: "zero", 15: "quinze", 21: "vinte e um", 100: "cem", 101: "cento e um", 1000: "mil", 1001: "mil e um",
             1100: "mil e cem", 1215: "mil duzentos e quinze", 1500: "mil e quinhentos", 1815: "mil oitocentos e quinze",
             1985: "mil novecentos e oitenta e cinco", 2024: "dois mil e vinte e quatro", 2000000: "dois milhões",
             1000000: "um milhão", 3200500: "três milhões duzentos mil e quinhentos"}
    for n, esperado in casos.items():
        assert N.extenso(n) == esperado, (n, N.extenso(n))
    assert N.ordinal(1) == "primeiro" and N.ordinal(2, True) == "segunda" and N.ordinal(14) == "décimo quarto"


def test_por_extenso_no_texto():
    t = N.por_extenso("Imagine a cena: 18 de junho de 1815, perto de Waterloo. Dos séculos XIV e XV, publicado em 1919.")
    assert "dezoito de junho de mil oitocentos e quinze" in t and "séculos catorze e quinze" in t and "mil novecentos e dezenove" in t
    assert N.por_extenso("Luís XIV e Dom Pedro II, capítulo IV") == "Luís catorze e Dom Pedro segundo, capítulo quatro"
    assert N.por_extenso("1º de maio, a 2ª vez, 50% e R$ 10,50") == \
        "primeiro de maio, a segunda vez, cinquenta por cento e dez reais e cinquenta centavos"
    assert N.por_extenso("1.500 pessoas e 2 dias, 3,5 milhões") == "mil e quinhentas pessoas e dois dias, três vírgula cinco milhões"
    assert N.por_extenso("[pausa 1.5] em 1985 [emocao 0.7]") == "[pausa 1.5] em mil novecentos e oitenta e cinco [emocao 0.7]"
    assert N.por_extenso("o V de vingança, sem números") == "o V de vingança, sem números"


def test_gerar_audio_manda_por_extenso(monkeypatch, tmp_path):
    vistos = []
    monkeypatch.setattr(vg, "_gerar_audio_motor", lambda engine, texto, out, **k: vistos.append((engine, texto, k)) or out)
    vg.gerar_audio("chatterbox", "Em 1815, no século XIX.", str(tmp_path / "a.wav"), idioma="pt")
    assert vistos[-1][1] == "Em mil oitocentos e quinze, no século dezenove." and "numeros_por_extenso" not in vistos[-1][2]
    vg.gerar_audio("chatterbox_turbo", "In 1815.", str(tmp_path / "b.wav"))
    assert vistos[-1][1] == "In 1815."  # inglês: o Turbo lê sozinho
    vg.gerar_audio("chatterbox", "Em 1815.", str(tmp_path / "c.wav"), idioma="pt", numeros_por_extenso=False)
    assert vistos[-1][1] == "Em 1815."
