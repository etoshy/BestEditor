"""v84_232: ✏️ capa desenhada — contornos numerados (cada um = um item, com texto/foto/personagem) + fundo/textura → prompt
respeitando posição e tamanho; Flow com rascunho + fotos de referência; ou montada sem IA com as fotos nos lugares."""
import io
import json

from PIL import Image

import publicacao as pub
from test_v84_229_publicacao import cena  # noqa: F401


def _png(cor, tam=(200, 120), modo="RGB"):
    b = io.BytesIO()
    Image.new(modo, tam, cor).save(b, "PNG")
    b.seek(0)
    return b


def test_onde():
    assert pub.onde([0, 0, .2, .2]).startswith("small, at the top left")
    assert "huge" in pub.onde([0, 0, 1, 1]) and "center of the frame" in pub.onde([.1, .1, .9, .9])
    assert "bottom right" in pub.onde([.7, .7, 1, 1])


def test_desenho_flow_e_montar(cena):  # noqa: F811
    A, jid, falso, gal, chamadas = cena
    c = A.app.test_client()
    itens = [{"n": 1, "cor": "#ef4444", "o_que": "pirâmide", "bbox": [0.55, 0.2, 0.95, 0.9]},
             {"n": 2, "cor": "#3b82f6", "o_que": "", "personagem": "vanta", "bbox": [0.05, 0.3, 0.35, 1]}]
    # sem dizer o que é → erro
    r = c.post(f"/job/{jid}/publicacao/capas/desenho", data={"desenho": (_png((200, 200, 200)), "d.png"),
               "itens": json.dumps([{"n": 1, "bbox": [0, 0, 1, 1]}])}, content_type="multipart/form-data")
    assert r.status_code == 400 and "item 1" in r.get_json()["erro"]
    d = c.post(f"/job/{jid}/publicacao/capas/desenho",
               data={"desenho": (_png((200, 200, 200), (1280, 720)), "d.png"), "itens": json.dumps(itens),
                     "foto_1": (_png((255, 200, 0)), "pir.png"), "fundo": (_png((0, 0, 120)), "tex.png"),
                     "fundo_desc": "deserto", "texto": "OI", "acao": "flow"}, content_type="multipart/form-data").get_json()
    nova = next(x for x in d["capas"] if x["n"] == d["capa_nova"])
    assert nova["url_desenho"] and [i["n"] for i in nova["itens"]] == [1, 2] and nova["itens"][0]["tem_foto"]
    assert any("RASCUNHO" in str(x) and "pirâmide" in str(x) for x in chamadas)  # a IA viu o rascunho e os itens
    j = falso.fila[-1]
    assert "PANEL 1 = a rough LAYOUT SKETCH" in j["prompt"] and "example of element #1" in j["prompt"]
    assert "example of element #2" in j["prompt"] and "BACKGROUND texture" in j["prompt"] and "NO text" in j["prompt"]
    assert Image.open(j["referencia_arquivo"]).width > 3 * Image.open(j["referencia_arquivo"]).height  # 4 painéis
    # 🧩 sem IA: a foto da pirâmide (amarela) no lugar desenhado, sobre a textura azul
    d = c.post(f"/job/{jid}/publicacao/capas/{nova['n']}/montar", json={}).get_json()
    cap = next(x for x in d["capas"] if x["n"] == nova["n"])
    im = Image.open(io.BytesIO(c.get(cap["url_final"]).data)).convert("RGB")
    r_, g_, b_ = im.getpixel((int(0.75 * 1280), int(0.55 * 720)))
    assert r_ > 200 and g_ > 150 and b_ < 100


def test_desenho_sem_ia(cena, monkeypatch):  # noqa: F811
    import ia_servico
    A, jid, falso, gal, chamadas = cena
    monkeypatch.setattr(ia_servico, "motivo_desligado", lambda r, c=None: "desligada")
    d = A.app.test_client().post(f"/job/{jid}/publicacao/capas/desenho",
                                 data={"desenho": (_png((200, 200, 200)), "d.png"),
                                       "itens": json.dumps([{"n": 1, "o_que": "um gato", "bbox": [0, 0, .2, .2]}])},
                                 content_type="multipart/form-data").get_json()
    nova = next(x for x in d["capas"] if x["n"] == d["capa_nova"])
    assert "Element #1: um gato — small, at the top left" in nova["prompt"]


def test_v84_233_fontes_graficos_presets_livre(cena, tmp_path):  # noqa: F811
    """🔤 fontes com peso, tarja, 🔴➡ círculo/seta desenhados pelo site, 🧩 predefinições e ✋ texto arrastado (livre)."""
    A, jid, falso, gal, chamadas = cena
    c = A.app.test_client()
    d = c.get(f"/job/{jid}/publicacao").get_json()
    assert len(d["presets"]) >= 8 and {"pessoa_objeto", "vs", "reacao_seta", "misterio"} <= {p["id"] for p in d["presets"]}
    assert any(f["nome"] == "poppins" and "Italic" in f["pesos"] for f in d["fontes_info"])
    assert c.get("/publicacao/fonte/anton-Bold.ttf").status_code == 200 and c.get("/publicacao/fonte/..%2Fapp.py").status_code == 404
    est = pub.limpar_estilo({"pos": "livre", "tx": 0.7, "ty": 2, "peso": "Italic", "caixa": True, "cor_caixa": "#00ff00"})
    assert est["pos"] == "livre" and est["tx"] == 0.7 and est["ty"] == 1.0 and est["peso"] == "Italic" and est["caixa"]
    itens = [{"n": 1, "o_que": "pirâmide", "bbox": [0.5, 0.1, 0.95, 0.9]},
             {"n": 2, "tipo": "circulo", "bbox": [0.1, 0.1, 0.3, 0.4]},
             {"n": 3, "tipo": "seta", "bbox": [0.2, 0.5, 0.45, 0.8], "de": [0.2, 0.8], "para": [0.45, 0.5]}]
    d = c.post(f"/job/{jid}/publicacao/capas/desenho",
               data={"desenho": (_png((200, 200, 200)), "d.png"), "itens": json.dumps(itens), "fundo": (_png((0, 0, 0)), "f.png"),
                     "foto_1": (_png((0, 0, 255)), "p.png"), "texto": "OI", "acao": "montar",
                     "estilo": json.dumps({"pos": "livre", "tx": 0.8, "ty": 0.15, "caixa": True, "cor_caixa": "#00ff00", "faixa": False})},
               content_type="multipart/form-data").get_json()
    nova = next(x for x in d["capas"] if x["n"] == d["capa_nova"])
    assert [i["n"] for i in nova["itens"]] == [1] and [g["tipo"] for g in nova["graficos"]] == ["circulo", "seta"]
    assert not any("círculo" in str(x) or "circulo" in str(x) for x in chamadas[-1:])  # a IA não vê os gráficos
    im = Image.open(io.BytesIO(c.get(nova["url_final"]).data)).convert("RGB")
    assert max(im.getpixel((x, 180))[0] for x in range(124, 150)) > 180  # a borda do círculo vermelho
    verde = sum(1 for x in range(900, 1150, 5) for y in range(60, 160, 5) if im.getpixel((x, y))[1] > 200 and im.getpixel((x, y))[0] < 90)
    assert verde > 20  # a tarja verde do texto lá em cima à direita (texto arrastado)


def test_v84_234_copiar_modelo(cena, monkeypatch):  # noqa: F811
    """📤 a thumb enviada vira um modelo editável (itens, seta/círculo, texto com posição/cores) e a original vai de
    referência de estilo pro Flow."""
    import ia_servico
    A, jid, falso, gal, chamadas = cena
    vistos = []

    def chamar(rec, system, conteudo, schema=None, **k):
        vistos.append(conteudo)
        if "graficos" in ((schema or {}).get("properties") or {}):
            preenche = "PREENCHA" in conteudo[-1]["text"]
            return {"itens": [{"papel": "personagem", "forma": "eli", "x0": .6, "y0": .1, "x1": .98, "y1": 1, "original": "homem surpreso",
                               "nosso": "Vanta assustada" if preenche else "x"},
                              {"papel": "coisa", "forma": "ret", "x0": .4, "y0": .3, "x1": .05, "y1": .9, "original": "carro", "nosso": "buraco negro"},
                              {"papel": "coisa", "forma": "ret", "x0": .1, "y0": .1, "x1": .1, "y1": .1, "original": "minúsculo", "nosso": ""}],
                    "graficos": [{"tipo": "seta", "x0": .6, "y0": .4, "x1": .4, "y1": .5, "cor": "#ff0000"},
                                 {"tipo": "circulo", "x0": .3, "y0": .3, "x1": .1, "y1": .1, "cor": "nada"}],
                    "texto": {"original": "INSANE", "nosso": "WAHNSINN", "x": .3, "y": .12, "linhas": 1, "cor": "#ffffff",
                              "cor2": "#ffff00", "caixa": True, "cor_caixa": "#ff0000", "tamanho": 140},
                    "fundo": {"original": "estrada", "nosso": "espaço"}, "estilo": "cores quentes"}
        return {}
    monkeypatch.setattr(ia_servico, "chamar", chamar)
    c = A.app.test_client()
    d = c.post(f"/job/{jid}/publicacao/capas/copiar_modelo", data={"imagem": (_png((50, 50, 50), (1280, 720)), "t.png")},
               content_type="multipart/form-data").get_json()
    m = d["modelo"]
    assert len(m["itens"]) == 2 and m["itens"][1]["bbox"] == [0.05, 0.3, 0.4, 0.9]  # caixa desinvertida, a minúscula fora
    assert m["itens"][0]["dica"] == "homem surpreso" and m["itens"][0]["nosso"] == "" and m["fundo"] == ""  # eu preencho
    assert m["graficos"][0] == {"tipo": "seta", "de": [0.6, 0.4], "para": [0.4, 0.5], "cor": "#ff0000"}
    assert m["graficos"][1]["bbox"] == [0.1, 0.1, 0.3, 0.3] and m["graficos"][1]["cor"] == "#ef2323"
    assert m["estilo"]["pos"] == "livre" and m["estilo"]["tx"] == 0.3 and m["estilo"]["caixa"] and m["estilo"]["tamanho"] == 140
    assert m["texto"] == "WAHNSINN" and m["texto_original"] == "INSANE"
    assert c.get(m["url_guia"]).status_code == 200
    # 🤖 a IA preenche pelo pedido
    d = c.post(f"/job/{jid}/publicacao/capas/copiar_modelo", data={"imagem": (_png((50, 50, 50)), "t.png"), "preencher": "1",
               "pedido": "a Vanta no lugar do homem"}, content_type="multipart/form-data").get_json()
    assert d["modelo"]["itens"][0]["nosso"] == "Vanta assustada" and d["modelo"]["fundo"] == "espaço"
    assert "a Vanta no lugar do homem" in vistos[-1][-1]["text"]
    # a original vai de referência de ESTILO junto com o rascunho
    d = c.post(f"/job/{jid}/publicacao/capas/desenho",
               data={"desenho": (_png((200, 200, 200)), "d.png"), "acao": "flow", "ref_guia": m["ref_guia"],
                     "itens": json.dumps([{"n": 1, "o_que": "buraco negro", "bbox": [0.05, 0.3, 0.4, 0.9]}])},
               content_type="multipart/form-data").get_json()
    j = falso.fila[-1]
    assert "STYLE/mood reference" in j["prompt"] and "LAYOUT SKETCH" in j["prompt"]
    assert c.post(f"/job/{jid}/publicacao/capas/desenho", data={"desenho": (_png((1, 1, 1)), "d.png"), "ref_guia": "../../app.py",
                  "itens": json.dumps([{"n": 1, "o_que": "x", "bbox": [0, 0, 1, 1]}])}, content_type="multipart/form-data").status_code == 200
