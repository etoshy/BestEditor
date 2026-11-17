"""v84_406: 🧩 Flow → montar cena: pose + fotos de personagens (cada uma com observação) + observação geral → a IA escreve
o comando e o Flow gera com todas as imagens, na ordem."""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
import flow_montar as FM  # noqa: E402


def _png(caminho, cor="red"):
    from PIL import Image
    Image.new("RGB", (64, 64), cor).save(caminho)
    return str(caminho)


def _pacote(tmp_path):
    return FM.novo_pacote(str(tmp_path), [
        {"papel": "personagem", "nome": "Ana", "obs": "sorrindo, mantém a jaqueta", "arquivo": _png(tmp_path / "a.png")},
        {"papel": "pose", "nome": "", "obs": "só a posição", "arquivo": _png(tmp_path / "p.png", "blue")},
        {"papel": "personagem", "nome": "Beto", "obs": "", "arquivo": _png(tmp_path / "b.png", "green")},
    ], "os dois brindando num bar à noite")


def test_pacote_pose_primeiro_e_comando_basico(tmp_path):
    pac = _pacote(tmp_path)
    assert [(r["n"], r["papel"], r["nome"]) for r in pac["refs"]] == [(1, "pose", ""), (2, "personagem", "Ana"), (3, "personagem", "Beto")]
    assert all(os.path.isfile(r["arquivo"]) for r in pac["refs"])
    assert FM.carregar_pacote(str(tmp_path), pac["id"])["obs_geral"] == "os dois brindando num bar à noite"
    p = FM.prompt_basico(pac)
    assert "pose" in p and "reference image 1" in p and "Ana replaces the WHOLE figure" in p and "person in reference image 2" in p
    assert "sorrindo, mantém a jaqueta" in p and "brindando" in p
    assert [r["arquivo"] for r in FM.referencias_flow(pac)] == [r["arquivo"] for r in pac["refs"]]
    with pytest.raises(FM.MontarErro):
        FM.novo_pacote(str(tmp_path), [], "")
    with pytest.raises(FM.MontarErro):
        FM.novo_pacote(str(tmp_path), [{"papel": "personagem", "arquivo": _png(tmp_path / f"x{k}.png")} for k in range(FM.MAX_REFS + 1)])
    with pytest.raises(FM.MontarErro):
        FM.carregar_pacote(str(tmp_path), "../etc")


def test_ia_ve_as_fotos_com_as_observacoes(tmp_path):
    pac = _pacote(tmp_path)
    visto = {}

    def chamar(recurso, sistema, conteudo, **k):
        visto.update(recurso=recurso, conteudo=conteudo)
        return {"prompt": "Two friends toasting  in a bar, pose from image 1.", "explicacao": "Usei a pose da 1.", "avisos": []}
    r = FM.montar_prompt(pac, chamar, lambda f: {"type": "image", "f": os.path.basename(f)})
    assert r["com_ia"] and r["prompt"] == "Two friends toasting in a bar, pose from image 1."
    textos = [c["text"] for c in visto["conteudo"] if c["type"] == "text"]
    assert visto["recurso"] == "flow_montar" and "Reference image 1 — POSE — note: só a posição" in textos[0]
    assert "name: Ana" in textos[1] and "GENERAL NOTE: os dois brindando" in textos[-2]
    assert sum(1 for c in visto["conteudo"] if c["type"] == "image") == 3
    # IA desligada / sem resposta → o comando básico
    r2 = FM.montar_prompt(pac, lambda *a, **k: None, lambda f: None)
    assert not r2["com_ia"] and "reference image 2" in r2["prompt"]


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    import app as A
    import flow_estudio as FE
    from googleflow import googleflow_client as gf
    A.app.config["TESTING"] = True
    monkeypatch.setitem(FE._BASE, "dir", str(tmp_path))
    monkeypatch.setattr(gf, "pasta_dados", lambda: tmp_path / "flow_dados")
    return A.app.test_client(), FE


def test_rotas(ctx, monkeypatch, tmp_path):
    c, FE = ctx
    monkeypatch.setattr(FM, "montar_prompt", lambda pac: {"prompt": "P " + str(len(pac["refs"])), "explicacao": "x", "avisos": [], "com_ia": True})
    dados = {"n": "2", "obs_geral": "na praia",
             "r0_papel": "pose", "r0_obs": "só a pose", "r0": (io.BytesIO(open(_png(tmp_path / "p.png"), "rb").read()), "pose.png"),
             "r1_papel": "personagem", "r1_nome": "Ana", "r1": (io.BytesIO(open(_png(tmp_path / "a.png"), "rb").read()), "ana.png")}
    j = c.post("/flow/montar/prompt", data=dados, content_type="multipart/form-data").get_json()
    assert j["ok"] and j["prompt"] == "P 2" and [x["quem"] for x in j["refs"]] == ["pose / composição", "personagem “Ana”"]
    assert c.get(f"/flow/montar/{j['pacote']}/{j['refs'][0]['arquivo']}").status_code == 200
    assert c.post("/flow/montar/prompt", data={"n": "0"}, content_type="multipart/form-data").status_code == 400
    # gerar: entra na mesma fila do ✨ Gerar, com as imagens na ordem
    enviados = []
    monkeypatch.setattr(FE, "_enviar", lambda tipo, cfg, op: enviados.append(op))
    monkeypatch.setitem(FE._ESTADO, "rodando", False)
    assert c.post("/flow/montar/gerar", json={"pacote": j["pacote"], "prompt": ""}).status_code == 400
    assert c.post("/flow/montar/gerar", json={"pacote": "lixo", "prompt": "x"}).status_code == 400
    r = c.post("/flow/montar/gerar", json={"pacote": j["pacote"], "prompt": "the pose of image 1", "proporcao": "9:16"})
    assert r.status_code == 200 and enviados[0]["tipo"] == "imagem" and enviados[0]["proporcao"] == "9:16"
    assert [os.path.basename(x["arquivo"]) for x in enviados[0]["referencias"]] == ["01_pose.png", "02_personagem.png"]
    FE._ESTADO["rodando"] = False
    h = c.get("/flow").get_data(as_text=True)
    assert 'id="montar"' in h and "fl-montar-usar" in h
