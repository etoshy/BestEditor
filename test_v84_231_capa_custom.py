"""v84_231: 🎛 capa personalizada (descrição, personagem do canal ou de fora, foto de fundo, texto e estilo) e
✏️ modificar uma capa gerada — a mesma conta volta ao projeto do Flow; sem crédito, outra conta sobe a imagem."""
import io
import time

from PIL import Image

import publicacao as pub
from test_v84_229_publicacao import cena  # noqa: F401 — a fixture


def _arq(cor, tam=(200, 120), modo="RGB"):
    b = io.BytesIO()
    Image.new(modo, tam, cor).save(b, "PNG")
    b.seek(0)
    return b


def test_capa_personalizada_montar_e_flow(cena):  # noqa: F811
    A, jid, falso, gal, chamadas = cena
    c = A.app.test_client()
    d = c.get(f"/job/{jid}/publicacao").get_json()
    assert "bebas-neue" in d["fontes"] and d["estilo_padrao"]["pos"] == "auto"
    est = '{"pos":"topo","cor":"#00ff00","cor2":"#ff0000","fonte":"anton","tamanho":120,"faixa":false,"pers_lado":"esquerda","pers_tam":80}'
    d = c.post(f"/job/{jid}/publicacao/capas/personalizada",
               data={"descricao": "ela rindo na frente de uma pirâmide", "texto": "DIE SPHINX\nLÜGT?", "acao": "montar",
                     "estilo": est, "fundo": (_arq((0, 0, 255)), "fundo.png"),
                     "personagem_img": (_arq((255, 0, 0, 255), (60, 90), "RGBA"), "p.png")},
               content_type="multipart/form-data").get_json()
    nova = next(x for x in d["capas"] if x["n"] == d["capa_nova"])
    assert nova["personalizada"] and nova["pers_fora"] and nova["url_fundo"] and nova["status"] == "pronta"
    assert nova["estilo"]["fonte"] == "anton" and nova["estilo"]["pos"] == "topo" and nova["estilo"]["faixa"] is False
    im = Image.open(io.BytesIO(c.get(nova["url_final"]).data)).convert("RGB")
    assert im.size == (1280, 720)
    assert im.getpixel((1200, 600))[2] > 200  # o fundo azul
    assert im.getpixel((40 + 30, 715))[0] > 200  # a personagem de fora (vermelha) colada à esquerda, embaixo
    # estilo novo → refaz a final; o texto continua no topo
    d = c.post(f"/job/{jid}/publicacao/capas/{nova['n']}", json={"estilo": {"pos": "base", "cor": "#ffffff"}}).get_json()
    assert next(x for x in d["capas"] if x["n"] == nova["n"])["estilo"]["pos"] == "base"
    # 🎨 no Flow: colagem personagem + fundo, a descrição virou prompt
    d = c.post(f"/job/{jid}/publicacao/capas/personalizada",
               data={"descricao": "Vanta zombando da esfinge", "texto": "X", "acao": "flow", "personagem": "vanta",
                     "fundo": (_arq((0, 200, 0)), "f.png")}, content_type="multipart/form-data").get_json()
    j = falso.fila[-1]
    assert "LEFT = the CHARACTER" in j["prompt"] and "RIGHT = the BACKGROUND" in j["prompt"] and "NO text" in j["prompt"]
    assert Image.open(j["referencia_arquivo"]).width > Image.open(j["referencia_arquivo"]).height


def test_modificar_no_mesmo_projeto(cena):  # noqa: F811
    A, jid, falso, gal, chamadas = cena
    itens = []
    orig = falso.adicionar

    def adicionar(its, **kw):
        itens.extend(its)
        return orig(its, **kw)
    falso.adicionar = adicionar
    c = A.app.test_client()
    d = c.post(f"/job/{jid}/publicacao/capas/ideias", json={}).get_json()
    n = d["capas"][0]["n"]
    c.post(f"/job/{jid}/publicacao/capas/{n}/gerar", json={})
    Image.new("RGB", (1280, 720), (30, 30, 90)).save(gal / "r.png")
    falso.fila[-1].update(estado="ok", resultados=[{"tipo": "imagem", "arquivo": "r.png", "conta": "ana",
                                                    "projeto": "https://labs.google/fx/tools/flow/project/abc", "media_id": "m1"}])
    d = c.get(f"/job/{jid}/publicacao").get_json()
    capa = next(x for x in d["capas"] if x["n"] == n)
    assert capa["origem_flow"]
    assert c.post(f"/job/{jid}/publicacao/capas/{n}/modificar", json={"pedido": ""}).status_code == 400
    d = c.post(f"/job/{jid}/publicacao/capas/{n}/modificar", json={"pedido": "céu à noite"}).get_json()
    assert d["mesmo_projeto"] is True
    it = itens[-1]
    assert it["conta_pref"] == "ana" and it["projeto_url"].endswith("/abc") and it["ref_media_id"] == "m1"
    assert "change ONLY this: céu à noite" in it["prompt"] and it["referencia_arquivo"].endswith(".png")
    capa = next(x for x in d["capas"] if x["n"] == n)
    assert capa["status"] == "fila" and capa["modificacoes"] == ["céu à noite"]


def test_flow_lote_conta_preferida():
    import flow_lote
    L = flow_lote.LoteFlow.__new__(flow_lote.LoteFlow) if hasattr(flow_lote, "LoteFlow") else None
    cls = type(flow_lote.lote())
    L = cls.__new__(cls)
    sem_credito = set()
    L._serve = lambda conta, tipo: conta not in sem_credito
    L.contas_do_lote = lambda: ["ana", "bia"]
    j = {"tipo": "imagem", "conta_pref": "ana", "criado": time.time()}
    assert L._pode_pegar("ana", j) and not L._pode_pegar("bia", j)
    sem_credito.add("ana")
    assert L._pode_pegar("bia", j)  # sem crédito na dona do projeto: outra pega (e sobe a imagem)
    sem_credito.clear()
    j["criado"] = time.time() - 999
    assert L._pode_pegar("bia", j)  # esperou demais
    assert L._pode_pegar("bia", {"tipo": "imagem", "conta_pref": "zé", "criado": time.time()})  # fora do lote
    assert L._pode_pegar("bia", {"tipo": "imagem"})


def test_compor_custom_posicoes(tmp_path):
    Image.new("RGB", (1280, 720), (90, 90, 90)).save(tmp_path / "b.png")
    for pos in pub.POSICOES:
        out = pub.compor_custom(str(tmp_path / "b.png"), "UM DOIS\nTRÊS", {"pos": pos, "fonte": "nao-existe"}, str(tmp_path / f"{pos}.jpg"))
        assert Image.open(out).size == (1280, 720)
    topo = Image.open(tmp_path / "topo.jpg").convert("L")
    assert max(topo.crop((0, 0, 1280, 300)).getdata()) > 200 and max(topo.crop((0, 500, 1280, 720)).getdata()) < 120
