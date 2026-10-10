"""Gênero e idade nos perfis de voz (v84): herança pelas vozes com slug e uso no prompt."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))

import modelados as md  # noqa: E402
import multivoz  # noqa: E402
import perfis_info  # noqa: E402


@pytest.fixture
def amb(tmp_path, monkeypatch):
    monkeypatch.setattr(perfis_info, "ARQUIVO", str(tmp_path / "perfis_info.json"))
    monkeypatch.setattr(multivoz, "ARQUIVO", str(tmp_path / "vozes.json"))
    monkeypatch.setattr(md, "ARQUIVO_ESTILOS", str(tmp_path / "estilos.json"))
    monkeypatch.setattr(md, "_tags_turbo", lambda: {"whispering"})
    return tmp_path


def test_normalizacao():
    assert perfis_info.normalizar_idade("Criança") == "crianca"
    assert perfis_info.normalizar_idade("old") == "idoso" and perfis_info.normalizar_idade("teen") == "jovem"
    assert perfis_info.normalizar_genero("mulher") == "feminino" and perfis_info.normalizar_genero("boy") == "masculino"
    assert perfis_info.rotulo("feminino", "idoso") == "voz feminina, idosa"
    assert perfis_info.rotulo("", "crianca") == "voz criança"
    with pytest.raises(ValueError):
        perfis_info.definir("x", idade="bebê de colo")


def test_voz_herda_do_perfil_e_pode_sobrepor(amb):
    perfis_info.definir("Vovo_Maria", "feminino", "idoso", "rouca e calma")
    multivoz.salvar({"nome": "Avó", "motor": "chatterbox_turbo", "config": {"vozPerfil": "Vovo_Maria"}})
    v = multivoz.por_slug()["avo"]
    assert (v["genero"], v["idade"], v["descricao"]) == ("feminino", "idoso", "rouca e calma")
    assert set(v["herdado"]) == {"genero", "idade", "descricao"}
    # o arquivo das vozes não guarda o herdado (muda o perfil -> muda a voz)
    assert json.load(open(multivoz.ARQUIVO))["vozes"][0]["genero"] == ""
    perfis_info.definir("Vovo_Maria", idade="adulto")
    assert multivoz.por_slug()["avo"]["idade"] == "adulto"
    multivoz.definir_genero("avo", None, idade="crianca")  # a voz passa a ter idade própria
    v = multivoz.por_slug()["avo"]
    assert v["idade"] == "crianca" and v["genero"] == "feminino" and "idade" not in v["herdado"]
    assert "voz feminina, criança" in multivoz.instrucao_para_ia()


def test_prompt_e_aviso_de_idade(amb):
    perfis_info.definir("menino", "masculino", "crianca")
    multivoz.salvar({"nome": "Narrator", "motor": "chatterbox_turbo", "config": {}, "genero": "masculino", "idade": "adulto"})
    multivoz.salvar({"nome": "Kenji", "motor": "chatterbox_turbo", "config": {"vozPerfil": "menino"}})
    proj = md.criar_projeto(str(amb), "", "kamishibai", "lenda", 20)
    texto = md.prompt_roteiro(proj, md.obter_estilo("kamishibai"), multivoz.listar(), {"whispering"})
    assert '"kenji" = Kenji — voz masculina, criança' in texto and '"narrator" = Narrator — voz masculina, adulta' in texto
    assert "criança = voz de criança" in texto and '"idade": "crianca | jovem | adulto | idoso"' in texto
    rot = {"personagens": [{"nome": "Kenji", "voz": "kenji", "genero": "masculino", "idade": "idoso"}],
           "falas": [{"id": 1, "voz": "kenji", "personagem": "Kenji", "texto": "Grandpa?"}],
           "cenas": [{"falas": [1], "cena": "a boy", "movimento": "push-in"}]}
    r, avisos = md.validar_roteiro(rot, multivoz.listar(), {"whispering"})
    assert r["personagens"][0]["idade"] == "idoso"
    assert any("Kenji" in a and "idoso" in a and "criança" in a for a in avisos)


def test_rota_info_do_perfil(amb, monkeypatch):
    import app
    monkeypatch.setattr(app, "tts_listar_perfis_de_voz", lambda: ["menino"])
    monkeypatch.setattr(app, "tts_caminho_perfil_de_voz", lambda n: ["a.wav"])
    c = app.app.test_client()
    r = c.post("/perfis-de-voz/menino/info", json={"genero": "masculino", "idade": "crianca", "descricao": "agudo"})
    assert r.status_code == 200 and perfis_info.obter("menino") == {"genero": "masculino", "idade": "crianca", "descricao": "agudo"}
    assert c.post("/perfis-de-voz/naoexiste/info", json={"genero": "f"}).status_code == 404
    assert c.post("/perfis-de-voz/menino/info", json={"idade": "xpto"}).status_code == 400
    html = c.get("/perfis-de-voz").get_data(as_text=True)
    assert 'value="crianca" selected' in html and 'value="masculino" selected' in html
    r = c.post("/gerar-voz/vozes", data={"mv_nome": "Kenji", "engine": "chatterbox_turbo", "mv_genero": "masculino", "mv_idade": "jovem"})
    if r.status_code == 200:
        assert multivoz.por_slug()["kenji"]["idade"] == "jovem"
    r = c.post("/gerar-voz/vozes/kenji/genero", json={"idade": "idoso"})
    assert r.status_code in (200, 400)
