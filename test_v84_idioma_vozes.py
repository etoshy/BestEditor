"""v84: idioma da narração vai no .zip e o vídeo segue ele; perfis de voz viram vozes nos Vídeos modelados."""
import io
import json
import os
import sys
import time
import wave
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))

import idiomas  # noqa: E402
import modelados as md  # noqa: E402
import multivoz  # noqa: E402
import perfis_info  # noqa: E402


def test_idiomas():
    assert idiomas.normalizar("pt-BR") == "pt" and idiomas.normalizar("English") == "en" and idiomas.normalizar("auto") is None
    assert idiomas.detectar_do_texto("Era uma noite fria e ninguém sabia o que estava acontecendo com a cidade.") == "pt"
    assert idiomas.detectar_do_texto("It was a cold night and nobody knew what was happening in the city.") == "en"
    assert idiomas.idioma_do_motor("chatterbox_turbo") == "en"
    assert idiomas.idioma_do_motor("piper", {"nome_voz": "es_ES-davefx-medium"}) == "es"
    assert idiomas.idioma_do_motor("kokoro", {"voz": "pf_dora"}) == "pt"
    d = idiomas.descobrir("piper", {"nome_voz": "pt_BR-faber-medium"}, "texto", "en")
    assert d["codigo"] == "en" and d["origem"] == "escolhido"
    assert idiomas.ler_info(idiomas.info_json("es")) == "es"
    r = idiomas.regra_para_prompt("inglês — English (en)")
    assert "IDIOMA DO VÍDEO: inglês — English (en)" in r and "on_screen_text" in r


def _zip(info=None, srt_texto="Era uma noite fria e ninguém sabia o que estava acontecendo."):
    w = io.BytesIO()
    ww = wave.open(w, "wb"); ww.setnchannels(1); ww.setsampwidth(2); ww.setframerate(16000); ww.writeframes(b"\0\0" * 32000); ww.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("narracao.wav", w.getvalue())
        z.writestr("legenda.srt", f"1\n00:00:00,000 --> 00:00:01,500\n{srt_texto}\n")
        if info:
            z.writestr("info.json", json.dumps(info))
    buf.seek(0)
    return buf


@pytest.mark.parametrize("info,form,esperado,origem", [
    ({"idioma": "en"}, "auto", "en", "zip"),
    (None, "auto", "pt", "legenda"),
    ({"idioma": "en"}, "es", "es", "escolhido"),
])
def test_zip_define_idioma_do_video(monkeypatch, info, form, esperado, origem):
    monkeypatch.setenv("NARRATION_SITE_NAO_CARREGAR_PROJETOS", "1")
    import app
    c = app.app.test_client()
    antes = set(app._JOBS)
    c.post("/transcribe", data={"audio": (_zip(info), "n.zip"), "language": form, "providers": "pexels"},
           content_type="multipart/form-data")
    jid = (set(app._JOBS) - antes).pop()
    for _ in range(40):
        if app._JOBS[jid].get("prompt"):
            break
        time.sleep(0.1)
    j = app._JOBS[jid]
    assert (j["language"], j["language_origem"]) == (esperado, origem)
    assert "IDIOMA DO VÍDEO: " + idiomas.nome_para_prompt(esperado) in j["prompt"]
    html = c.get(f"/job/{jid}/prompt").get_data(as_text=True)
    assert "Idioma do vídeo" in html


def test_zip_do_gerador_leva_info_json(monkeypatch, tmp_path):
    monkeypatch.setenv("NARRATION_SITE_NAO_CARREGAR_PROJETOS", "1")
    import app
    monkeypatch.setattr(app, "VOZES_DIR", str(tmp_path))
    (tmp_path / "a.wav").write_bytes(b"RIFF" + b"\0" * 100)
    (tmp_path / "a.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\noi\n", encoding="utf-8")
    app._GERAR_VOZ_STATUS["jz"] = {"resultado_filename": "a.wav", "resultado_srt_filename": "a.srt", "idioma": "en",
                                   "idioma_origem": "voz", "engine": "chatterbox_turbo"}
    r = app.app.test_client().get("/gerar-voz/baixar-zip/jz")
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert json.loads(z.read("info.json"))["idioma"] == "en" and "narracao.wav" in z.namelist()


def test_perfis_viram_vozes_sem_aviso_falso(tmp_path, monkeypatch):
    monkeypatch.setattr(multivoz, "ARQUIVO", str(tmp_path / "vozes.json"))
    monkeypatch.setattr(perfis_info, "ARQUIVO", str(tmp_path / "pi.json"))
    monkeypatch.setattr(md, "ARQUIVO_ESTILOS", str(tmp_path / "e.json"))
    monkeypatch.setattr(md, "_perfis_salvos", lambda: ["Kuchisake", "Menino"])
    monkeypatch.setattr(md, "_tags_turbo", lambda: {"whispering"})
    perfis_info.definir("Kuchisake", "feminino", "adulto", "fria e sussurrada")
    perfis_info.definir("Menino", "masculino", "crianca")
    vozes = md.vozes_efetivas()
    assert [v["slug"] for v in vozes] == ["kuchisake", "menino", "narrator"]
    k = vozes[0]
    assert k["motor"] == "chatterbox_turbo" and k["config"] == {"vozPerfil": "Kuchisake"} and k["genero"] == "feminino"
    proj = md.criar_projeto(str(tmp_path), "", "kamishibai", "Kuchisake-onna", 20)
    texto = md.prompt_roteiro(proj, md.obter_estilo("kamishibai"), multivoz.listar(), {"whispering"})
    assert '"kuchisake" = Kuchisake — voz feminina, adulta — fria e sussurrada' in texto
    assert '"menino" = Menino — voz masculina, criança' in texto and "Só existe UMA voz" not in texto
    rot = {"personagens": [{"nome": "Kuchisake-onna", "voz": "kuchisake", "genero": "feminino"},
                           {"nome": "Boy", "voz": "menino", "genero": "masculino"},
                           {"nome": "Narrador", "voz": "narrator", "genero": "masculino"}],
           "falas": [{"id": 1, "voz": "narrator", "texto": "A cold night."}, {"id": 2, "voz": "kuchisake", "texto": "Am I pretty?"},
                     {"id": 3, "voz": "menino", "texto": "Y-yes."}],
           "cenas": [{"falas": [1, 2, 3], "cena": "street", "movimento": "push-in"}]}
    _r, avisos = md.validar_roteiro(rot, multivoz.listar(), {"whispering"})
    assert not [a for a in avisos if "cadastrada como" in a]
    # cadastrar a voz com slug pro perfil: o perfil não aparece duplicado
    multivoz.salvar({"nome": "Onna", "motor": "chatterbox_turbo", "config": {"vozPerfil": "Kuchisake"}})
    assert [v["slug"] for v in md.vozes_efetivas()] == ["onna", "menino", "narrator"]
    assert md.vozes_efetivas()[0]["genero"] == "feminino"  # herda do perfil


def test_voz_do_personagem_muda_todas_as_falas(tmp_path, monkeypatch):
    monkeypatch.setattr(multivoz, "ARQUIVO", str(tmp_path / "vozes.json"))
    monkeypatch.setattr(perfis_info, "ARQUIVO", str(tmp_path / "pi.json"))
    monkeypatch.setattr(md, "ARQUIVO_ESTILOS", str(tmp_path / "e.json"))
    monkeypatch.setattr(md, "_perfis_salvos", lambda: ["Kuchisake", "Menino"])
    monkeypatch.setattr(md, "_tags_turbo", lambda: set())
    perfis_info.definir("Menino", "masculino", "crianca")
    base = str(tmp_path)
    proj = md.criar_projeto(base, "", "kamishibai", "lenda", 20)
    rot = {"personagens": [{"nome": "Boy", "voz": "narrator", "genero": "masculino", "idade": "crianca"}],
           "falas": [{"id": 1, "tipo": "narracao", "voz": "narrator", "texto": "Night."},
                     {"id": 2, "tipo": "dialogo", "personagem": "Boy", "voz": "narrator", "texto": "Hello?"},
                     {"id": 3, "tipo": "dialogo", "personagem": "boy", "voz": "kuchisake", "texto": "Mom?"}],
           "cenas": [{"falas": [1, 2, 3], "cena": "x", "movimento": "y"}]}
    md.aplicar_roteiro(base, proj["id"], json.dumps(rot), md.vozes_efetivas(), set())
    papeis = md.personagens_do_roteiro(md.carregar_projeto(base, proj["id"])["roteiro"])
    assert [(p["nome"], p["falas"], p["misturado"]) for p in papeis] == [("Narrador", 1, False), ("Boy", 2, True)]
    assert papeis[1]["idade"] == "crianca"
    r = md.definir_voz_do_personagem(base, proj["id"], "Boy", "menino", {v["slug"] for v in md.vozes_efetivas()})
    falas = md.carregar_projeto(base, proj["id"])["roteiro"]["falas"]
    assert r["alteradas"] == 2 and [f["voz"] for f in falas] == ["narrator", "menino", "menino"]
    with pytest.raises(md.ModeladoError):
        md.definir_voz_do_personagem(base, proj["id"], "Boy", "naoexiste", {"menino"})
