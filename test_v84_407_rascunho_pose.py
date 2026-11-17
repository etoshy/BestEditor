"""v84_407: ✏️ rascunho da pose — foto → esboço a lápis (Flow ou filtro no PC) → numerar as pessoas → pose da Montar cena."""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
import flow_montar as FM  # noqa: E402
import flow_rascunho as FR  # noqa: E402


def _foto(caminho):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (400, 300), (180, 200, 220))
    d = ImageDraw.Draw(im)
    d.ellipse([60, 40, 140, 120], fill=(230, 190, 160))   # cabeça 1
    d.rectangle([70, 120, 130, 280], fill=(40, 60, 120))  # corpo 1
    d.ellipse([240, 50, 320, 130], fill=(210, 170, 140))
    d.rectangle([250, 130, 310, 290], fill=(120, 30, 30))
    im.save(caminho)
    return str(caminho)


def test_rascunho_local_vira_lapis(tmp_path):
    import numpy as np
    from PIL import Image
    out = FR.rascunho_local(_foto(tmp_path / "f.png"), str(tmp_path / "r.png"))
    a = np.asarray(Image.open(out).convert("L"))
    assert a.shape == (300, 400)
    assert (a > 230).mean() > 0.6 and (a < 120).mean() > 0.005  # papel branco com traços escuros
    with pytest.raises(ValueError):
        (tmp_path / "x.png").write_bytes(b"nada")
        FR.rascunho_local(str(tmp_path / "x.png"), str(tmp_path / "y.png"))


def test_marcas_texto_e_copia_numerada(tmp_path):
    m = FR.limpar_marcas(json.dumps([{"x": 0.2, "y": 0.2, "nome": "Ana"}, {"x": 0.8, "y": 0.5, "nome": "", "obs": "de costas"},
                                     {"x": 3, "y": 0.5}, {"x": "a"}]))
    assert [(x["n"], x["nome"]) for x in m] == [(1, "Ana"), (2, "")]
    assert FR.texto_marcas(m) == "figura 1 (pessoa, à esquerda, no alto) = Ana; figura 2 (pessoa, à direita) = personagem 2 — de costas"
    foto = _foto(tmp_path / "f.png")
    out = FR.desenhar_marcas(foto, str(tmp_path / "n.png"), m)
    from PIL import Image
    assert Image.open(out).getpixel((80, 60))[0] > 200  # o círculo vermelho em cima da figura 1


def test_pose_numerada_no_pacote(tmp_path):
    marcas = [{"x": 0.25, "y": 0.25, "nome": "Ana"}, {"x": 0.7, "y": 0.3, "nome": "Beto"}]
    pac = FM.novo_pacote(str(tmp_path), [{"papel": "pose", "arquivo": _foto(tmp_path / "p.png"), "obs": "", "marcas": json.dumps(marcas)},
                                         {"papel": "personagem", "nome": "Ana", "arquivo": _foto(tmp_path / "a.png")}])
    pose = pac["refs"][0]
    assert pose["papel"] == "pose" and len(pose["marcas"]) == 2 and os.path.isfile(pose["arquivo_ia"])
    assert "figura 1 (pessoa, à esquerda, no alto) = Ana" in pose["obs"] and "figura 2" in pose["obs"]
    vistos = []
    FM.conteudo_ia(pac, lambda f: vistos.append(os.path.basename(f)) or {"type": "image"})
    assert vistos[0] == "01_pose_numerada.png"  # a IA vê os números…
    assert FM.referencias_flow(pac)[0]["arquivo"].endswith("01_pose.png")  # …o Flow recebe o rascunho limpo


def test_entender_a_cena_inteira(tmp_path):
    foto = _foto(tmp_path / "f.png")
    resp = {"camera": "de cima, grande angular", "cenario": "estacionamento de cascalho", "estilo": "foto",
            "elementos": [{"tipo": "objeto", "x": 0.2, "y": 0.15, "descricao": "carro conversível laranja"},
                          {"tipo": "pessoa", "x": 0.25, "y": 0.4, "descricao": "camisa preta, mão no bolso"},
                          {"tipo": "pessoa", "x": 0.75, "y": 0.25, "descricao": "terno cinza"}]}
    r = FR.entender_cena(foto, lambda *a, **k: resp, lambda f: {"type": "image"})
    assert [(m["n"], m["tipo"]) for m in r["marcas"]] == [(1, "pessoa"), (2, "pessoa"), (3, "objeto")]  # pessoas primeiro
    assert r["cena"]["camera"].startswith("de cima") and r["estilo"] == "foto"
    m = r["marcas"]
    m[0]["nome"], m[2]["nome"] = "Ana", "moto vermelha"
    t = FR.texto_marcas(m)
    assert "figura 1 (pessoa, à esquerda) = Ana" in t and "elemento 3 (objeto: carro conversível laranja, à esquerda, no alto) → trocar por: moto vermelha" in t
    assert FR.texto_cena(dict(r["cena"], cenario_novo="rua de Tóquio")) == \
        "câmera: de cima, grande angular; cenário original: estacionamento de cascalho → trocar por: rua de Tóquio"
    assert FR.entender_cena(foto, lambda *a, **k: None, lambda f: {"type": "image"})["marcas"] == []


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
    foto = open(_foto(tmp_path / "f.png"), "rb").read()
    j = c.post("/flow/rascunho/local", data={"foto": (io.BytesIO(foto), "f.png")}, content_type="multipart/form-data").get_json()
    it = j["item"]
    assert j["ok"] and it["origem"] == "rascunho" and os.path.isfile(os.path.join(FE.pasta_galeria(), it["arquivo"]))
    assert c.post("/flow/rascunho/local", data={}, content_type="multipart/form-data").status_code == 400
    monkeypatch.setattr(FR, "entender_cena", lambda arq: {"marcas": [{"n": 1, "x": 0.2, "y": 0.2, "tipo": "pessoa", "nome": "", "obs": "em pé"}],
                                                          "cena": {"camera": "de cima", "cenario": "rua", "cenario_novo": ""}, "estilo": "foto"})
    j_ = c.post("/flow/rascunho/figuras", json={"galeria": it["id"]}).get_json()
    assert j_["marcas"][0]["obs"] == "em pé" and j_["cena"]["camera"] == "de cima" and j_["estilo"] == "foto"
    j_ = c.post("/flow/rascunho/figuras", data={"foto": (io.BytesIO(foto), "f.png")}, content_type="multipart/form-data").get_json()
    assert j_["ok"]
    assert c.post("/flow/rascunho/figuras", json={"galeria": "nada"}).status_code == 404
    # o rascunho (da galeria) com as figuras numeradas → pose da montagem
    monkeypatch.setattr(FM, "montar_prompt", lambda pac: {"prompt": pac["refs"][0]["obs"], "explicacao": "", "avisos": [], "com_ia": False})
    d = {"n": "1", "r0_papel": "pose", "r0_galeria": it["id"], "r0_marcas": json.dumps([{"x": 0.2, "y": 0.2, "nome": "Ana"}])}
    j2 = c.post("/flow/montar/prompt", data=d, content_type="multipart/form-data").get_json()
    assert "figura 1 (pessoa, à esquerda, no alto) = Ana" in j2["prompt"]
    # 🎨 pelo Flow: a foto vai como referência, com o pedido de rascunho
    enviados = []
    monkeypatch.setattr(FE, "_enviar", lambda tipo, cfg, op: enviados.append(op))
    monkeypatch.setitem(FE._ESTADO, "rodando", False)
    r = c.post("/flow/rascunho/flow", data={"foto": (io.BytesIO(foto), "f.png"), "extra": "estilo mangá"}, content_type="multipart/form-data")
    assert r.status_code == 200 and enviados[0]["referencia"]["arquivo"] and "pencil storyboard sketch" in enviados[0]["prompt"]
    assert enviados[0]["prompt"].endswith("estilo mangá")
    FE._ESTADO["rodando"] = False
    h = c.get("/flow").get_data(as_text=True)
    assert 'id="rascunho"' in h and "fl-montar-pose" in h and "data-rascunho" in h


def test_estilo_final_e_cena_no_pacote(tmp_path):
    assert any(e["id"] == "anime" for e in FM.estilos()) and any(e["id"].startswith("arte:") for e in FM.estilos())
    pac = FM.novo_pacote(str(tmp_path), [{"papel": "pose", "arquivo": _foto(tmp_path / "p.png"),
                                          "cena": json.dumps({"camera": "de cima", "cenario": "rua", "cenario_novo": "praia"})}],
                         "", "anime")
    assert "câmera: de cima" in pac["refs"][0]["obs"] and "trocar por: praia" in pac["refs"][0]["obs"]
    assert "anime illustration" in FM.prompt_basico(pac)
    textos = [c.get("text", "") for c in FM.conteudo_ia(pac, lambda f: None)]
    assert any(t.startswith("FINAL ART STYLE: modern anime") for t in textos)
    assert FM.novo_pacote(str(tmp_path), [{"papel": "pose", "arquivo": _foto(tmp_path / "q.png")}], "", "inventado")["estilo"] == ""


def test_foto_base_sem_converter_e_pessoa_inteira(tmp_path):
    """v84_407c: a própria foto como base (composição + cores), cores da original opcionais e a troca da pessoa INTEIRA."""
    pac = FM.novo_pacote(str(tmp_path), [
        {"papel": "personagem", "nome": "Ana", "arquivo": _foto(tmp_path / "a.png")},
        {"papel": "base", "arquivo": _foto(tmp_path / "b.png"), "marcas": json.dumps([{"x": 0.2, "y": 0.3, "nome": "Ana"}])},
        {"papel": "cores", "nome": "foto original", "arquivo": _foto(tmp_path / "c.png")}])
    assert [r["papel"] for r in pac["refs"]] == ["base", "personagem", "cores"]  # a base é a imagem 1
    assert pac["refs"][0].get("arquivo_ia") and "figura 1" in pac["refs"][0]["obs"]
    p = FM.prompt_basico(pac)
    assert "BASE of the composition" in p and "replaced ENTIRELY" in p
    assert "Ana replaces the WHOLE figure" in p and "clothes and their colors" in p
    assert "ONLY the color palette and lighting from reference image 3" in p
    assert "BASE image" in FM.SISTEMA and "never just the" in FM.SISTEMA


def test_rota_foto_original(ctx, tmp_path):
    c, FE = ctx
    foto = open(_foto(tmp_path / "f.png"), "rb").read()
    j = c.post("/flow/rascunho/original", data={"foto": (io.BytesIO(foto), "f.png")}, content_type="multipart/form-data").get_json()
    assert j["ok"] and j["item"]["rotulo"] == "base"
    assert open(os.path.join(FE.pasta_galeria(), j["item"]["arquivo"]), "rb").read() == foto  # sem converter
    h = c.get("/flow").get_data(as_text=True)
    assert 'id="rcOriginal"' in h and 'id="rcCores"' in h
