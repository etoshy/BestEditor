"""v84_174 — ✂ perfis de voz clipe a clipe: 🗑 apagar um clipe ruim, ⭐ escolher o principal (o único que o Chatterbox
usa) e ➕ juntar mais áudio/vídeo num perfil que já existe (sem apagar o que ele tem)."""
import io
import math
import os
import struct
import wave
import zipfile

import pytest

import perfis_info
import perfis_limpeza as pl


def _wav(caminho, freq=220.0, dur=1.0, sr=22050):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with wave.open(caminho, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * k / sr))) for k in range(int(sr * dur))))
    return caminho


@pytest.fixture
def vg(tmp_path, monkeypatch):
    v = pl._vg()
    pasta = tmp_path / "perfis_de_voz"
    pasta.mkdir()
    monkeypatch.setattr(v, "VOICE_PROFILES_DIR", str(pasta))
    monkeypatch.setattr(perfis_info, "ARQUIVO", str(tmp_path / "perfis_info.json"))
    return v


def test_adicionar_principal_e_apagar(vg, tmp_path):
    vg.salvar_perfil_de_voz("mira", [_wav(str(tmp_path / "a.wav")), _wav(str(tmp_path / "b.wav"), dur=2.0)])
    novos = vg.adicionar_clipes_ao_perfil("mira", [_wav(str(tmp_path / "c.wav"), dur=3.0)])
    nomes = [os.path.basename(c) for c in vg.caminho_perfil_de_voz("mira")]
    assert [os.path.basename(n) for n in novos] == ["ref_03.wav"] and nomes == ["ref_01.wav", "ref_02.wav", "ref_03.wav"]
    assert vg.duracao_wav(novos[0]) == 3.0
    # ⭐ o principal vai primeiro (é o [0] que o Chatterbox usa)
    vg.definir_clipe_principal("mira", 2)
    assert os.path.basename(vg.caminho_perfil_de_voz("mira")[0]) == "ref_03.wav"
    # 🗑 apagar o principal: volta pro primeiro da ordem normal
    assert vg.excluir_clipe_do_perfil("mira", 0) == "ref_03.wav"
    assert [os.path.basename(c) for c in vg.caminho_perfil_de_voz("mira")] == ["ref_01.wav", "ref_02.wav"]
    vg.excluir_clipe_do_perfil("mira", 0)
    with pytest.raises(vg.VoiceGeneratorError, match="único clipe"):
        vg.excluir_clipe_do_perfil("mira", 0)
    # o próximo número não reaproveita um que ainda existe
    assert os.path.basename(vg.adicionar_clipes_ao_perfil("mira", _wav(str(tmp_path / "d.wav")))[0]) == "ref_03.wav"


def test_limite_total_e_perfil_antigo(vg, tmp_path):
    with pytest.raises(vg.VoiceGeneratorError):
        vg.adicionar_clipes_ao_perfil("nao_existe", _wav(str(tmp_path / "a.wav")))
    _wav(os.path.join(vg.VOICE_PROFILES_DIR, "velho.wav"))  # perfil de antes (um .wav solto)
    vg.adicionar_clipes_ao_perfil("velho", _wav(str(tmp_path / "b.wav")))
    assert len(vg.caminho_perfil_de_voz("velho")) == 2
    arqs = [_wav(str(tmp_path / f"x{i}.wav")) for i in range(vg.MAX_CLIPES_TOTAL - 1)]
    with pytest.raises(vg.VoiceGeneratorError, match="Apague os clipes ruins"):
        vg.adicionar_clipes_ao_perfil("velho", arqs)
    assert len(vg.caminho_perfil_de_voz("velho")) == 2  # nada pela metade


def test_rotas_e_pagina(vg, tmp_path):
    import app as a
    c = a.app.test_client()
    vg.salvar_perfil_de_voz("vanta", [_wav(str(tmp_path / "a.wav")), _wav(str(tmp_path / "b.wav"))])
    pasta = os.path.join(vg.VOICE_PROFILES_DIR, "vanta")
    _wav(os.path.join(pasta, "_original", "ref_02.wav"))
    perfis_info.atualizar("vanta", audio="musica", limpeza={"clipes": ["ref_01.wav", "ref_02.wav"], "estado": "pronto"})
    h = c.get("/perfis-de-voz").get_data(as_text=True)
    assert 'class="pf-apagar"' in h and "⭐ principal" in h and "➕ adicionar ao perfil “vanta”" in h
    d = c.post("/perfis-de-voz/vanta/clipe/1/principal").get_json()
    assert d["ok"] and d["clipes"][0]["arquivo"] == "ref_02.wav" and d["clipes"][0]["principal"]
    d = c.post("/perfis-de-voz/vanta/clipe/0/excluir").get_json()
    assert d["ok"] and d["apagado"] == "ref_02.wav" and [x["arquivo"] for x in d["clipes"]] == ["ref_01.wav"]
    assert not os.path.exists(os.path.join(pasta, "_original", "ref_02.wav"))
    assert perfis_info.obter("vanta")["limpeza"]["clipes"] == ["ref_01.wav"]  # o novo ref_02 terá de ser limpo
    assert c.post("/perfis-de-voz/vanta/clipe/0/excluir").status_code == 400
    iniciadas = []
    orig = pl.iniciar
    pl.iniciar = lambda nome, **k: iniciadas.append(nome) or "t1"
    try:
        dados = open(_wav(str(tmp_path / "novo.wav")), "rb").read()
        d = c.post("/perfis-de-voz/vanta/adicionar", data={"audios": (io.BytesIO(dados), "novo.wav")},
                   content_type="multipart/form-data").get_json()
    finally:
        pl.iniciar = orig
    assert d["ok"] and d["adicionados"] == 1 and len(d["clipes"]) == 2 and iniciadas == ["vanta"]  # 🎵: limpa só o novo
    assert c.post("/perfis-de-voz/nada/adicionar").status_code == 404


def test_exportar_leva_o_principal(vg, tmp_path):
    import perfis_pacote
    vg.salvar_perfil_de_voz("mira", [_wav(str(tmp_path / "a.wav")), _wav(str(tmp_path / "b.wav"))])
    vg.definir_clipe_principal("mira", 1)
    dados = perfis_pacote.exportar(["mira"])
    assert "perfis/mira/_principal.txt" in zipfile.ZipFile(io.BytesIO(dados)).namelist()
    vg.excluir_perfil_de_voz("mira")
    zp = str(tmp_path / "p.zip")
    open(zp, "wb").write(dados)
    perfis_pacote.importar(zp)
    assert os.path.basename(vg.caminho_perfil_de_voz("mira")[0]) == "ref_02.wav"


def test_youtube_adiciona_ao_perfil_existente(vg, tmp_path, monkeypatch):
    import time
    import app as a
    vg.salvar_perfil_de_voz("mira", [_wav(str(tmp_path / "a.wav"))])
    recebeu = {}

    def extrair(itens, nome, qualidade=None, on_log=None, adicionar=False):
        recebeu["adicionar"] = adicionar
        return vg.adicionar_clipes_ao_perfil(nome, [_wav(str(tmp_path / "y1.wav")), _wav(str(tmp_path / "y2.wav"))])
    monkeypatch.setattr(a, "yt_extrair_perfil_de_voz_do_youtube", extrair)
    c = a.app.test_client()
    assert c.post("/perfis-de-voz/youtube/extrair", json={"nome": "outro", "adicionar": True,
                                                           "itens": [{"url": "x"}]}).status_code == 400
    d = c.post("/perfis-de-voz/youtube/extrair", json={"nome": "mira", "adicionar": True, "itens": [{"url": "x"}]}).get_json()
    for _ in range(100):
        st = c.get(f"/perfis-de-voz/youtube/{d['job_id']}/status").get_json()
        if st["status"] in ("pronto", "erro"):
            break
        time.sleep(0.1)
    assert st["status"] == "pronto" and st["adicionados"] == 2 and st["quantidade_clipes"] == 3 and recebeu["adicionar"]
