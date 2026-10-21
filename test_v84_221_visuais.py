"""v84_221: 👗 visuais da personagem (roupa/penteado consistente), 🆕 poses novas pedidas pela IA e 👄 boca automática."""
import io
import json

from PIL import Image

import personagens_pod as pp
from test_v84_183_personagens_pod import JSON_POSES, _png
from test_v84_184_personagens_flow import LoteFalso, _ok, flow  # noqa: F401  (fixture)


def _criar(c):
    r = c.post("/personagens-pod/criar", data={"nome": "Vanta", "motor": "flow", "json": json.dumps(JSON_POSES),
                                                "refs": [(io.BytesIO(_png()), "ficha.png")]}, content_type="multipart/form-data")
    return r.headers["Location"].rstrip("/").split("/")[-1]


def _pronta(c, falso, gal, pid, arquivo):
    c.post(f"/personagens-pod/{pid}/gerar", json={"arquivos": [arquivo]})
    _ok(falso, gal, falso.fila[-1]["id"])
    c.get(f"/personagens-pod/{pid}/estado")


def test_boca_automatica(flow, monkeypatch):
    c, falso, gal = flow
    monkeypatch.setattr(pp, "boca_auto", lambda p: p["dados"].get("boca_auto", True) is not False)
    pid = _criar(c)
    c.post(f"/personagens-pod/{pid}/gerar", json={"arquivos": ["vanta_relogio_esq.png"]})
    _ok(falso, gal, falso.fila[-1]["id"])
    e = c.get(f"/personagens-pod/{pid}/estado").get_json()
    # a pose ficou pronta → a boca dela entrou no JSON e já foi pro Flow
    assert falso.fila[-1]["prompt"].startswith("The reference image is the finished character image to edit")
    por = {x["arquivo"]: x for x in e["itens"]}
    assert por["vanta_relogio_esq_boca.png"]["estado"] in ("fila", "gerando")
    _ok(falso, gal, falso.fila[-1]["id"])
    n = len(falso.fila)
    c.get(f"/personagens-pod/{pid}/estado")
    assert len(falso.fila) == n  # a boca pronta não pede mais nada
    # desligada no projeto: não pede
    q = pp.carregar(pid)
    q["dados"]["boca_auto"] = False
    pp.salvar(q)
    _pronta(c, falso, gal, pid, "vanta_neutra_esq.png")
    assert not falso.fila[-1]["prompt"].startswith("The reference image is the finished")


def test_visual_novo_e_consistente(flow):
    c, falso, gal = flow
    pid = _criar(c)
    _pronta(c, falso, gal, pid, "vanta_neutra_esq.png")
    c.post(f"/personagens-pod/{pid}/mestre", json={"arquivo": "vanta_neutra_esq.png"})
    _pronta(c, falso, gal, pid, "vanta_cetica_esq.png")
    d = c.post(f"/personagens-pod/{pid}/visual", json={"nome": "Praia", "descricao_en": "summer beach outfit, straw hat",
                                                       "poses": "todas", "gerar": True}).get_json()
    assert d["ok"] and d["visual"] == "praia"
    mestra = "vanta_neutra_esq__praia.png"
    assert mestra in d["novas"] and "vanta_cetica_esq__praia.png" in d["novas"]
    jm = falso.fila[-1]
    # a mestra do visual: edição da pose pronta, só a roupa muda; a outra pose ⏳ espera a mestra
    assert "Change ONLY the outfit" in jm["prompt"] and "straw hat" in jm["prompt"] and "VANTA LOCK" not in jm["prompt"]
    e = c.get(f"/personagens-pod/{pid}/estado").get_json()
    por = {x["arquivo"]: x for x in e["itens"]}
    assert por["vanta_cetica_esq__praia.png"]["aguarda"] and "esperando" in por["vanta_cetica_esq__praia.png"]["msg"]
    assert e["visuais"][0]["nome"] == "Praia"
    _ok(falso, gal, jm["id"])
    c.get(f"/personagens-pod/{pid}/estado")
    jp = falso.fila[-1]
    # a outra pose foi sozinha: colagem pose de origem + mestra do visual, "copie a roupa da direita"
    assert "wearing EXACTLY the outfit" in jp["prompt"]
    im = Image.open(jp["referencia_arquivo"])
    assert im.width > im.height
    # pose nova pedida pela IA, dentro do visual → a mestra do visual é a referência
    arq = pp.adicionar_pose(pid, "pointing at a thermometer, sweating", "apontando pro termômetro", "praia")
    assert arq.startswith("ia_") and "__praia" in arq
    c.post(f"/personagens-pod/{pid}/gerar", json={"arquivos": [arq]})
    jn = falso.fila[-1]
    assert "pointing at a thermometer" in jn["prompt"] and "Praia" in jn["prompt"] and "NOT its pose" in jn["prompt"]


def test_visual_exige_pose_pronta(flow):
    c, falso, gal = flow
    pid = _criar(c)
    r = c.post(f"/personagens-pod/{pid}/visual", json={"nome": "Inverno", "descricao_en": "winter coat"}).get_json()
    assert "erro" in r
