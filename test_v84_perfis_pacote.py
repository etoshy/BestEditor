"""📦 Perfis de voz: exportar num .zip (clipes, _original/, gênero/idade/descrição, 🎧, vozes com slug) e importar
em outro PC — tanto o .zip exportado quanto um .zip "comum" só com áudios."""
import io
import json
import math
import os
import struct
import wave
import zipfile

import pytest

import multivoz
import perfis_info
import perfis_pacote as pp


def _wav(caminho, freq=220.0, dur=1.0, sr=22050):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with wave.open(caminho, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * k / sr))) for k in range(int(sr * dur))))
    return caminho


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """Um "PC": pasta de perfis + perfis_info.json + vozes_multi.json próprios."""
    def novo(rotulo):
        base = tmp_path / rotulo
        (base / "perfis").mkdir(parents=True)
        return base

    def usar(base):
        vg = pp._vg()
        monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(base / "perfis"))
        monkeypatch.setattr(perfis_info, "ARQUIVO", str(base / "perfis_info.json"))
        monkeypatch.setattr(multivoz, "ARQUIVO", str(base / "vozes_multi.json"))
        return str(base / "perfis")

    return novo, usar


def test_exportar_e_importar_em_outro_pc(pc, tmp_path):
    novo, usar = pc
    pasta = usar(novo("pc1"))
    a = _wav(os.path.join(pasta, "locutor", "ref_01.wav"))
    _wav(os.path.join(pasta, "locutor", "ref_02.wav"), freq=330)
    _wav(os.path.join(pasta, "locutor", "_original", "ref_01.wav"), freq=500)
    _wav(os.path.join(pasta, "outro", "ref_01.wav"))
    perfis_info.definir("locutor", "masculino", "idoso", "grave e rouca")
    perfis_info.atualizar("locutor", audio="musica", limpeza={"estado": "pronto", "clipes": ["ref_01.wav"]})
    multivoz.salvar({"nome": "Vovô", "motor": "xtts", "config": {"vozPerfil": "locutor", "idioma": "pt"}})

    dados = pp.exportar(["locutor"])
    z = zipfile.ZipFile(io.BytesIO(dados))
    nomes = set(z.namelist())
    assert {"manifesto.json", "perfis/locutor/ref_01.wav", "perfis/locutor/ref_02.wav", "perfis/locutor/_original/ref_01.wav"} <= nomes
    assert not any("outro" in n for n in nomes)
    man = json.loads(z.read("manifesto.json"))
    assert man["perfis"][0]["info"]["idade"] == "idoso" and man["perfis"][0]["vozes_slug"][0]["slug"] == "vovo"

    arq = tmp_path / "pacote.zip"
    arq.write_bytes(dados)
    pasta2 = usar(novo("pc2"))
    res = pp.importar(str(arq))
    assert [r["nome"] for r in res] == ["locutor"] and res[0]["vozes_slug"] == ["vovo"]
    assert open(os.path.join(pasta2, "locutor", "ref_01.wav"), "rb").read() == open(a, "rb").read()
    assert os.path.isfile(os.path.join(pasta2, "locutor", "_original", "ref_01.wav"))
    assert pp._vg().caminho_perfil_de_voz("locutor") == [os.path.join(pasta2, "locutor", f"ref_0{i}.wav") for i in (1, 2)]
    i = perfis_info.obter("locutor")
    assert (i["genero"], i["idade"], i["descricao"], i["audio"]) == ("masculino", "idoso", "grave e rouca", "musica")
    assert multivoz.por_slug()["vovo"]["config"]["vozPerfil"] == "locutor"

    # de novo: não sobrescreve, vira locutor_2 (e a voz com slug já existe — não duplica)
    res2 = pp.importar(str(arq))
    assert res2[0]["nome"] == "locutor_2" and res2[0]["renomeado"] and res2[0]["vozes_slug"] == []
    # substituir
    res3 = pp.importar(str(arq), substituir=True)
    assert res3[0]["nome"] == "locutor"


def test_importar_zip_comum_so_com_audios(pc, tmp_path):
    novo, usar = pc
    usar(novo("pc"))
    origem = tmp_path / "src"
    arq = tmp_path / "vozes.zip"
    with zipfile.ZipFile(arq, "w") as z:
        z.write(_wav(str(origem / "j1.wav")), "pessoas/joao/a.wav")
        z.write(_wav(str(origem / "j2.wav"), freq=300), "pessoas/joao/b.wav")
        z.write(_wav(str(origem / "m1.wav")), "pessoas/maria/x.wav")
        z.writestr("pessoas/leia.txt", "oi")
        z.writestr("__MACOSX/pessoas/._a.wav", "lixo")
    res = pp.importar(str(arq), dividir=False)
    assert sorted((r["nome"], r["clipes"]) for r in res) == [("joao", 2), ("maria", 1)]

    arq2 = tmp_path / "Narrador Top.zip"
    with zipfile.ZipFile(arq2, "w") as z:
        z.write(_wav(str(origem / "n.wav")), "n.wav")
    res = pp.importar(str(arq2), dividir=False)
    assert res[0]["nome"] == "Narrador_Top"
    res = pp.importar(str(arq2), nome="meu nome", dividir=False)
    assert res[0]["nome"] == "meu_nome"


def test_zip_perigoso_ou_vazio(pc, tmp_path):
    novo, usar = pc
    pasta = usar(novo("pc"))
    arq = tmp_path / "mal.zip"
    with zipfile.ZipFile(arq, "w") as z:
        z.writestr("../../fora.wav", "x")
        z.writestr("/abs.wav", "x")
    with pytest.raises(pp.PacoteErro):
        pp.importar(str(arq))
    assert not os.path.exists(tmp_path / "fora.wav")
    (tmp_path / "nao_zip.zip").write_text("oi")
    with pytest.raises(pp.PacoteErro):
        pp.importar(str(tmp_path / "nao_zip.zip"))
    with pytest.raises(pp.PacoteErro):
        pp.exportar()  # nada pra exportar
    assert os.listdir(pasta) == []


def test_rotas(pc, tmp_path, monkeypatch):
    import app as _app
    _app.app.config["TESTING"] = True
    monkeypatch.setattr(_app, "VOZES_DIR", str(tmp_path / "vozes"))
    novo, usar = pc
    pasta = usar(novo("pc1"))
    _wav(os.path.join(pasta, "ana", "ref_01.wav"))
    c = _app.app.test_client()
    pg = c.get("/perfis-de-voz").get_data(as_text=True)
    assert "📦 Importar perfis" in pg and "📦 Exportar todos" in pg
    r = c.get("/perfis-de-voz/exportar?nomes=ana")
    assert r.status_code == 200 and r.mimetype == "application/zip"
    dados = r.data
    assert c.get("/perfis-de-voz/exportar?nomes=nao_existe").status_code == 404

    usar(novo("pc2"))
    r = c.post("/perfis-de-voz/importar", data={"zip": (io.BytesIO(dados), "p.zip")}, content_type="multipart/form-data")
    assert r.status_code == 302 and "importados=ana" in r.headers["Location"]
    assert "✅ Importado" in c.get(r.headers["Location"]).get_data(as_text=True)
    r = c.post("/perfis-de-voz/importar?json=1", data={"zip": (io.BytesIO(dados), "p.zip")}, content_type="multipart/form-data")
    assert r.get_json()["importados"][0]["nome"] == "ana_2"
    r = c.post("/perfis-de-voz/importar?json=1", data={"zip": (io.BytesIO(b"x"), "p.txt")}, content_type="multipart/form-data")
    assert r.status_code == 400
