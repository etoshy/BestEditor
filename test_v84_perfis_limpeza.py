"""v84_92 — 🎧 perfis de voz marcados "limpo" × "tem música de fundo": com música, os clipes passam UMA VEZ pelo Demucs
(o mesmo da dublagem) e fica só a voz pra clonagem; o original fica em _original/ (ouvir / voltar)."""
import math
import os
import struct
import subprocess
import wave

import pytest

import perfis_info
import perfis_limpeza as pl


def _wav(caminho, freq=220.0, dur=1.0, sr=22050, canais=1):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with wave.open(caminho, "wb") as w:
        w.setnchannels(canais)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * k / sr))) * canais for k in range(int(sr * dur)))
        w.writeframes(frames)
    return caminho


def _fmt(caminho):
    with wave.open(caminho) as w:
        return w.getframerate(), w.getnchannels()


@pytest.fixture
def perfis(tmp_path, monkeypatch):
    vg = pl._vg()
    pasta = tmp_path / "perfis_de_voz"
    pasta.mkdir()
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(pasta))
    monkeypatch.setattr(perfis_info, "ARQUIVO", str(tmp_path / "perfis_info.json"))
    chamadas = []

    def separar(audio, pasta_tmp, log):
        """Demucs falso: a 'voz' é um tom diferente, em 44,1 kHz estéreo (como o Demucs devolve)."""
        chamadas.append(audio)
        return _wav(os.path.join(pasta_tmp, "htdemucs", "vocals.wav"), freq=880.0, sr=44100, canais=2)
    monkeypatch.setattr(pl, "_separar_padrao", separar)
    return str(pasta), chamadas


def test_marcar_e_limpar_uma_vez(perfis):
    pasta, chamadas = perfis
    a = _wav(os.path.join(pasta, "locutor", "a.wav"))
    b = _wav(os.path.join(pasta, "locutor", "b.wav"))
    original_a = open(a, "rb").read()
    pl.marcar("locutor", "musica")
    assert pl.info("locutor")["audio"] == "musica" and pl.precisa_limpar("locutor")
    r = pl.limpar("locutor")
    assert r == {"limpos": 2, "total": 2, "ja_estavam": 0} and len(chamadas) == 2
    assert open(a, "rb").read() != original_a and _fmt(a) == (22050, 1)  # voz limpa, no formato do clipe original
    assert open(os.path.join(pasta, "locutor", "_original", "a.wav"), "rb").read() == original_a
    assert pl._vg().caminho_perfil_de_voz("locutor") == [a, b]  # a clonagem não enxerga _original/
    li = pl.info("locutor")["limpeza"]
    assert li["estado"] == "pronto" and li["clipes"] == ["a.wav", "b.wav"] and not pl.precisa_limpar("locutor")
    # de novo: nada a fazer (uma vez só)
    assert pl.limpar("locutor")["limpos"] == 0 and len(chamadas) == 2
    # clipe novo: só ele
    _wav(os.path.join(pasta, "locutor", "c.wav"))
    assert pl.precisa_limpar("locutor") and pl.limpar("locutor")["limpos"] == 1 and len(chamadas) == 3
    # forçar refaz todos a partir dos ORIGINAIS (não limpa a voz já limpa de novo)
    pl.limpar("locutor", forcar=True)
    assert len(chamadas) == 6 and all(os.path.basename(os.path.dirname(c)) for c in chamadas)
    assert pl.originais("locutor") and len(pl.originais("locutor")) == 3


def test_voltar_aos_originais(perfis):
    pasta, _ch = perfis
    a = _wav(os.path.join(pasta, "p", "a.wav"))
    antes = open(a, "rb").read()
    pl.marcar("p", "musica")
    pl.limpar("p")
    assert pl.restaurar("p") == 1 and open(a, "rb").read() == antes
    assert pl.info("p")["limpeza"] == {} and pl.precisa_limpar("p")


def test_perfil_antigo_de_um_wav_vira_pasta(perfis):
    pasta, _ch = perfis
    _wav(os.path.join(pasta, "velho.wav"))
    pl.marcar("velho", "musica")
    pl.limpar("velho")
    assert not os.path.exists(os.path.join(pasta, "velho.wav"))
    assert pl._vg().caminho_perfil_de_voz("velho") == [os.path.join(pasta, "velho", "velho.wav")]
    assert pl._vg().listar_perfis_de_voz() == ["velho"]


def test_erro_fica_registrado_e_demucs_faltando(perfis, monkeypatch):
    pasta, _ch = perfis
    _wav(os.path.join(pasta, "x", "a.wav"))
    import dublagem
    monkeypatch.setattr(dublagem, "separar_voz_musica",
                        lambda *a, **k: (_ for _ in ()).throw(dublagem.DublagemError("Falha: No module named demucs")))
    with pytest.raises(pl.LimpezaErro, match="pip install demucs"):
        pl.limpar("x", separar=_demucs_real)
    li = pl.info("x")["limpeza"]
    assert li["estado"] == "erro" and "demucs" in li["erro"]
    assert open(os.path.join(pasta, "x", "a.wav"), "rb").read() == open(os.path.join(pasta, "x", "_original", "a.wav"), "rb").read()


def _demucs_real(audio, pasta_tmp, log):
    """O caminho de verdade (sem o falso da fixture), com o separar_voz_musica do monkeypatch."""
    import dublagem
    try:
        voz, _ = dublagem.separar_voz_musica(audio, pasta_tmp, device="cpu", on_log=log)
    except dublagem.DublagemError as exc:
        if "No module named" in str(exc) and "demucs" in str(exc):
            raise pl.LimpezaErro("O Demucs não está instalado — rode: pip install demucs (depois tente de novo).") from exc
        raise
    return voz


# ------------------------------------------------------------------ rotas
@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_rotas(A, perfis):
    import tarefas_bg
    pasta, chamadas = perfis
    _wav(os.path.join(pasta, "voz_yt", "a.wav"))
    c = A.app.test_client()
    h = c.get("/perfis-de-voz").get_data(as_text=True)
    assert 'class="pf-audio-tipo"' in h and 'name="audio" value="musica"' in h and 'id="yt-musica"' in h
    d = c.post("/perfis-de-voz/voz_yt/audio", json={"audio": "musica"}).get_json()
    assert d["ok"] and d["tarefa"] and d["audio"] == "musica"
    t = tarefas_bg.esperar(d["tarefa"], 20)
    assert t["status"] == "pronto", t.get("erro")
    d = c.get("/perfis-de-voz/voz_yt/estado").get_json()
    assert d["limpeza"]["estado"] == "pronto" and d["n_originais"] == 1
    assert c.get("/perfis-de-voz/voz_yt/original/0").status_code == 200
    h = c.get("/perfis-de-voz").get_data(as_text=True)
    assert "voz limpa (1 clipe(s))" in h and "ouvir os originais" in h
    d = c.post("/perfis-de-voz/voz_yt/audio", json={"audio": "limpo"}).get_json()
    assert d["tarefa"] is None  # marcar "limpo" não processa nada
    assert c.post("/perfis-de-voz/voz_yt/restaurar", json={}).get_json()["voltaram"] == 1
    assert c.get("/perfis-de-voz/voz_yt/original/0").status_code == 404
    assert c.post("/perfis-de-voz/nao_existe/audio", json={"audio": "musica"}).status_code == 404
    assert c.post("/perfis-de-voz/voz_yt/audio", json={"audio": "xyz"}).status_code == 400


def test_criar_pelo_youtube_com_musica_limpa_na_hora(A, perfis, monkeypatch):
    pasta, chamadas = perfis
    import time

    def extrair(itens, nome, qualidade=None, on_log=None):
        return [_wav(os.path.join(pasta, nome, "yt1.wav")), _wav(os.path.join(pasta, nome, "yt2.wav"))]
    monkeypatch.setattr(A, "yt_extrair_perfil_de_voz_do_youtube", extrair)
    c = A.app.test_client()
    d = c.post("/perfis-de-voz/youtube/extrair", json={"nome": "entrevista", "itens": [{"url": "https://youtu.be/abcdefghijk"}],
                                                       "audio": "musica"}).get_json()
    for _ in range(100):
        st = c.get(f"/perfis-de-voz/youtube/{d['job_id']}/status").get_json()
        if st["status"] in ("pronto", "erro"):
            break
        time.sleep(0.1)
    assert st["status"] == "pronto" and st["quantidade_clipes"] == 2
    assert len(chamadas) == 2 and pl.info("entrevista")["limpeza"]["clipes"] == ["yt1.wav", "yt2.wav"]
