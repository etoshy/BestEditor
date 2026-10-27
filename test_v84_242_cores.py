"""🌈 v84_242 — a foto COLORIDA opcional do personagem (quando a referência é mangá P&B): Animação 2D, React e Criador."""
import io
import json
import os

import pytest
from PIL import Image

import anime2d as A
import anime2d_manga as AM
import criador_personagens as C
import personagens_pod as pp
import react_personagens as R


@pytest.fixture
def base(tmp_path, monkeypatch):
    for k, v in (("ANIME2D_DIR", "anime2d"), ("PERSONAGENS_POD_DIR", "pod"), ("REACT_PERSONAGENS_DIR", "react"),
                 ("CRIADOR_PERSONAGENS_DIR", "criador")):
        monkeypatch.setenv(k, str(tmp_path / v))
    return str(tmp_path)


def _b(cor, modo="RGB"):
    b = io.BytesIO()
    Image.new(modo, (300, 400), cor).save(b, "PNG")
    return b.getvalue()


class Lote:
    def __init__(self):
        self.itens = []

    def adicionar(self, itens, **kw):
        self.itens += itens
        return [{"id": f"j{len(self.itens)}{k}"} for k in range(len(itens))]

    def iniciar(self):
        pass


@pytest.fixture
def lote(monkeypatch):
    import flow_lote
    L = Lote()
    monkeypatch.setattr(flow_lote, "lote", lambda: L)
    return L


def test_anime2d_design_e_poses_com_a_colorida(base, lote):
    p = A.criar("Yomi", "x", "anime", base)
    c = {"id": A._id("c"), "nome": "Yomi", "refs": [], "design": {}, "design_en": "girl, black bob hair, blue eyes"}
    p["personagens"].append(c)
    A.guardar_referencia(p, "manga.png", _b((128, 128, 128)), "personagem", "Yomi", "", base)
    # pela lista de referências (tipo 🌈 cores + nome) ou pelo botão do personagem
    r = A.guardar_referencia(p, "cor.png", _b((200, 30, 30)), "cores", "Yomi", "", base)
    assert c["cor_ref"] == r["arquivo"] and r["arquivo"] not in c["refs"]
    A.guardar_cor_ref(p, c, "cor2.png", _b((30, 30, 200)), base)
    assert c["cor_ref"] != r["arquivo"] and not any(x["arquivo"] == r["arquivo"] for x in p["referencias"])
    A.salvar(p, base)
    ref, paineis = AM.ref_design(p, c, base)
    assert os.path.isfile(ref) and len(paineis) == 2 and "COLORED" in paineis[1]
    pr = AM.prompt_design(p, c, paineis)
    assert "2 panels" in pr and "REAL colors" in pr and "win over" in pr
    AM.gerar_designs(p["id"], [c["id"]], "", base)
    assert "REAL colors" in lote.itens[-1]["prompt"] and lote.itens[-1]["referencia_arquivo"] == lote.itens[-1]["referencia_arquivo"]
    # poses: a colorida vai logo depois do design aprovado, com a descrição de "só as cores"
    p = A.carregar(p["id"], base)
    c = p["personagens"][0]
    Image.new("RGBA", (300, 400), (0, 0, 0, 255)).save(os.path.join(A.pasta(p["id"], base), "imagens", "d.png"))
    c["design"] = {"aprovado": "d.png", "arquivo": "d.png", "estado": "aprovado"}
    A.salvar(p, base)
    dados = A.poses_json(p, c)
    assert dados["descricoes_referencias"][c["cor_ref"]] == pp.COR_REF_EN and "COLORED reference" in dados["texto_fixo"]["trava"]
    A.criar_poses(p["id"], c["id"], base)
    proj = pp.carregar(A.carregar(p["id"], base)["personagens"][0]["pod"]["pid"], base)
    assert proj["refs"][:2] == ["design_anime_aprovado.png", c["cor_ref"]]
    # tirar
    q = A.carregar(p["id"], base)
    A.tirar_cor_ref(q, q["personagens"][0], base)
    assert not q["personagens"][0].get("cor_ref") and not any(x["tipo"] == "cores" for x in q["referencias"])


def test_react_e_criador(base, lote):
    import app as AP
    cl = AP.app.test_client()
    p = R.criar("Teste", base)
    ch = R.novo_personagem(p, "Itachi", obra="Naruto")
    R.guardar_ref(p, ch, _b((120, 120, 120)), base)
    R.salvar(p, base)
    assert cl.post(f"/react-personagens/{p['id']}/personagem/{ch['id']}/cor", data={"arquivo": (io.BytesIO(_b((180, 20, 20))), "c.png")},
                   content_type="multipart/form-data").get_json()["ok"]
    q = R.carregar(p["id"], base)
    c = R.personagem(q, ch["id"])
    assert c["cor_ref"].startswith(ch["id"] + "_cor_") and os.path.isfile(os.path.join(R.pasta(p["id"], base), "refs", c["cor_ref"]))
    dados = R.poses_json(q, c, ["dir"])
    assert dados["descricoes_referencias"][c["cor_ref"]] == pp.COR_REF_EN
    R.criar_poses(p["id"], ch["id"], base)
    proj = pp.carregar(R.personagem(R.carregar(p["id"], base), ch["id"])["pod"]["pid"], base)
    assert c["cor_ref"] in proj["refs"] and proj["refs"][0] == c["refs"][0]
    assert cl.post(f"/react-personagens/{p['id']}/personagem/{ch['id']}/cor", json={"apagar": True}).get_json()["ok"]
    assert not R.personagem(R.carregar(p["id"], base), ch["id"]).get("cor_ref")
    assert "Foto colorida" in cl.get(f"/react-personagens/{p['id']}").get_data(as_text=True)
    # 🧬 criador: a referência colorida com "🌈 cores reais"
    k = C.criar("Yomi", base)
    C.guardar_ref(k, Image.new("RGB", (200, 300), (128, 128, 128)), ["tudo"], "", base)
    C.guardar_ref(k, Image.new("RGB", (200, 300), (200, 30, 30)), ["cores_reais"], "", base)
    m = C.mapa_refs(k)
    assert "REAL COLORS" in m[1] and "win over" in m[1]
    assert "colorida" in cl.get(f"/criador-personagens/{k['id']}").get_data(as_text=True)
