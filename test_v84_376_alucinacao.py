"""v84_376: 🛡 o Chatterbox se perdeu (áudio comprido demais pro texto) → gera de novo."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
from tts import voice_generator as vg  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _tom_de_teste_nao_e_zumbido(monkeypatch, request):
    """Os testes de DURAÇÃO usam um tom puro (que é 'som contínuo'): aqui o detector de zumbido fica de fora."""
    if "zumbido" not in request.node.name:
        monkeypatch.setattr(vg, "trechos_sem_fala", lambda caminho, min_s=2.0: [])
    if "whisper" in request.node.name:
        monkeypatch.delenv("VOICE_GENERATOR_SEM_WHISPER_GUARDA", raising=False)


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


def test_desligada_gera_uma_vez_como_antes(tmp_path, monkeypatch):
    monkeypatch.setitem(vg._PROTECAO, "ativa", False)
    chamadas = []
    vg._gerar_com_guarda(lambda t, c: chamadas.append(c) or _tom(c, 40.0), "Frase curta.", str(tmp_path / "a.wav"))
    assert len(chamadas) == 1


def test_gerar_audio_liga_e_desliga(tmp_path, monkeypatch):
    vistos = []
    monkeypatch.setattr(vg, "chatterbox_synthesize", lambda t, s, **k: vistos.append((dict(k), vg._PROTECAO["ativa"])) or s)
    vg.gerar_audio("chatterbox", "Olá.", str(tmp_path / "a.wav"), protecao_alucinacao=False)
    vg.gerar_audio("chatterbox", "Olá.", str(tmp_path / "a.wav"))
    assert vistos == [({}, False), ({}, True)]  # a chave nunca chega no motor; padrão = ligada


def test_velocidade_lenta_aumenta_o_limite(tmp_path):
    chamadas = []
    vg._gerar_com_guarda(lambda t, c: chamadas.append(c) or _tom(c, 7.0), "Frase curta de teste.", str(tmp_path / "a.wav"),
                         velocidade=0.5)  # limite 4 s / 0,5 = 8 s
    assert len(chamadas) == 1


def test_rota_manda_a_opcao(monkeypatch):
    import time
    import app as A
    recebido = []
    monkeypatch.setattr(A, "tts_gerar_audio_isolado", lambda e, t, s, **kw: recebido.append(kw) or open(s, "wb").write(b"RIFF") or s)
    c = A.app.test_client()
    c.post("/gerar-voz/gerar", data={"engine": "chatterbox", "texto": "Um texto qualquer de teste.", "chatterbox_idioma": "pt",
                                     "protecao_alucinacao_enviado": "1"})  # caixa desmarcada
    c.post("/gerar-voz/gerar", data={"engine": "chatterbox", "texto": "Outro texto qualquer de teste.", "chatterbox_idioma": "pt",
                                     "protecao_alucinacao_enviado": "1", "protecao_alucinacao": "on"})
    for _ in range(100):
        if len(recebido) == 2:
            break
        time.sleep(0.05)
    assert sorted(k["protecao_alucinacao"] for k in recebido) == [False, True]
    assert "🛡 Proteção contra alucinação" in c.get("/gerar-voz").get_data(as_text=True)


def _fala_com_zumbido(caminho, zumbido_s):
    """'Fala' (tom que liga e desliga 5x por segundo, como sílabas) + zumbido contínuo no meio."""
    f = ("sine=frequency=220:duration=2,volume='if(lt(mod(t,0.2),0.1),1,0.02)':eval=frame")
    partes = ["-f", "lavfi", "-i", f, "-f", "lavfi", "-i", f"anoisesrc=d={zumbido_s}:a=0.08:r=24000", "-f", "lavfi", "-i", f]
    subprocess.run(["ffmpeg", "-y", "-v", "error", *partes, "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", "-ar", "24000",
                    "-ac", "1", caminho], check=True)


def test_zumbido_no_meio_e_detectado_e_gera_de_novo(tmp_path):
    ruim = str(tmp_path / "ruim.wav")
    _fala_com_zumbido(ruim, 3.0)
    achou = vg.trechos_sem_fala(ruim)
    assert len(achou) == 1 and 1.5 <= achou[0][0] <= 2.5 and achou[0][1] >= 2.0
    bom = str(tmp_path / "bom.wav")
    _fala_com_zumbido(bom, 0.3)
    assert vg.trechos_sem_fala(bom) == []
    seq = iter([3.0, 0.3])
    chamadas = []
    vg._gerar_com_guarda(lambda t, c: chamadas.append(c) or _fala_com_zumbido(c, next(seq)), "x" * 200, str(tmp_path / "a.wav"))
    assert len(chamadas) == 2 and vg.trechos_sem_fala(str(tmp_path / "a.wav")) == []


def _fala_buraco_fala(caminho, buraco_s, buraco="anoisesrc=d={d}:a=0.05:r=24000"):
    f = "sine=frequency=220:duration=2,volume='if(lt(mod(t,0.2),0.1),1,0.02)':eval=frame"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f, "-f", "lavfi", "-i", buraco.format(d=buraco_s),
                    "-f", "lavfi", "-i", f, "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", "-ar", "24000", "-ac", "1",
                    caminho], check=True)


def _whisper_falso(monkeypatch, palavras):
    import types
    wt = types.SimpleNamespace(transcribe_audio=lambda *a, **k: [{"start": 0, "end": 9, "text": "x", "words": palavras}])
    monkeypatch.setitem(sys.modules, "whisper_transcribe", wt)


def test_whisper_acusa_som_sem_palavras_e_aceita_pausa_silenciosa(tmp_path, monkeypatch):
    pal = [{"word": w, "start": i * 0.3, "end": i * 0.3 + 0.25} for i, w in enumerate("um dois tres quatro cinco seis".split())]
    pal += [{"word": w, "start": 4.6 + i * 0.3, "end": 4.6 + i * 0.3 + 0.25} for i, w in enumerate("sete oito nove".split())]
    _whisper_falso(monkeypatch, pal)
    ruim = str(tmp_path / "r.wav")
    _fala_buraco_fala(ruim, 2.5)  # lixo de 2,0 a 4,5 s
    buracos, cob = vg.trechos_sem_palavras(ruim, "um dois tres quatro cinco seis sete oito nove", "pt")
    assert len(buracos) == 1 and 1.6 <= buracos[0][0] <= 2.0 and buracos[0][1] >= 2.0 and cob == 1.0
    calmo = str(tmp_path / "c.wav")
    _fala_buraco_fala(calmo, 2.5, "anullsrc=r=24000:cl=mono:d={d}")  # pausa SILENCIOSA longa: não é lixo
    assert vg.trechos_sem_palavras(calmo, "um dois tres quatro cinco seis sete oito nove", "pt")[0] == []


def test_whisper_cobertura_baixa(tmp_path, monkeypatch):
    _whisper_falso(monkeypatch, [{"word": "um", "start": 0.1, "end": 0.3}])
    c = str(tmp_path / "a.wav")
    _tom(c, 1.0)
    assert vg.trechos_sem_palavras(c, "um dois tres quatro cinco seis", "pt")[1] < 0.6


def test_whisper_tudo_com_lixo_corta_no_fim(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "trechos_sem_palavras", lambda c, t, i=None, min_s=1.5: ([(2.0, 2.5)], 1.0))
    chamadas = []
    saida = str(tmp_path / "a.wav")
    vg._gerar_com_guarda(lambda t, c: chamadas.append(c) or _fala_buraco_fala(c, 2.5), "x" * 100, saida)
    assert len(chamadas) == 3
    assert abs(vg._duracao_audio_segundos(saida) - (6.5 - 2.5 + 0.24)) < 0.1  # o lixo saiu, ficou a folga
    assert sorted(os.listdir(tmp_path)) == ["a.wav"]
