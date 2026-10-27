"""🧬 v84_239 — Criador de personagens: entrada (clonar/misturar/descrever), ficha (IA), design no Flow, poses."""
import io
import json
import os
import threading
import time

import pytest
from PIL import Image, ImageDraw

import criador_personagens as C


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("CRIADOR_PERSONAGENS_DIR", str(tmp_path / "criador"))
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pod"))
    return str(tmp_path)


def _img(cor=(200, 60, 60), tam=(400, 600)):
    return Image.new("RGB", tam, cor)


def _png_bytes(cor=(200, 60, 60), tam=(400, 600)):
    b = io.BytesIO()
    _img(cor, tam).save(b, "PNG")
    return b.getvalue()


def _verde(cor=(220, 80, 80)):
    """Uma 'imagem do Flow': figura no fundo verde."""
    im = Image.new("RGB", (900, 1200), (0, 255, 0))
    ImageDraw.Draw(im).rectangle([300, 150, 600, 1100], fill=cor)
    return im


class Lote:
    def __init__(self):
        self.trava = threading.Lock()
        self.fila, self.rodando, self.itens, self.n = [], True, [], 0

    def adicionar(self, itens, modelo="", proporcao="16:9", quantidade="x1", **kw):
        out = []
        for it in itens:
            self.n += 1
            j = {"id": f"j{self.n}", "estado": "fila", "resultados": [], "item": it}
            self.fila.append(j)
            self.itens.append(it)
            out.append({"id": j["id"]})
        return out

    def iniciar(self):
        pass


@pytest.fixture
def lote(monkeypatch, tmp_path):
    import flow_lote
    import flow_estudio as FE
    L = Lote()
    monkeypatch.setattr(flow_lote, "lote", lambda: L)
    gal = tmp_path / "galeria"
    gal.mkdir()
    monkeypatch.setattr(FE, "pasta_galeria", lambda: str(gal))
    L.galeria = gal
    return L


def _terminar(L, cor=(220, 80, 80)):
    for j in L.fila:
        if j["estado"] == "fila":
            nome = f"{j['id']}.png"
            _verde(cor).save(L.galeria / nome)
            j.update(estado="ok", resultados=[{"tipo": "imagem", "arquivo": nome}])


def test_entrada_estilos_e_colagem_numerada(base):
    p = C.criar("", base)
    assert p["id"].startswith("cp") and p["entrada"]["original"] is True
    assert len(C.ESTILOS) >= 40 and "expressionismo" in C.ESTILOS and "manga" in C.ESTILOS and "realista" in C.ESTILOS
    C.editar_entrada(p, {"estilo": "outro", "estilo_livre": "vitral gótico com chumbo grosso", "descricao": "uma bruxa"})
    assert "vitral gótico" in C.estilo_en(p) and C.estilo_nome(p).startswith("✍")
    C.editar_entrada(p, {"estilo": "nao_existe"})
    assert p["entrada"]["estilo"] == "anime"
    for k, cor in enumerate([(200, 0, 0), (0, 0, 200), (0, 150, 0)]):
        C.guardar_ref(p, _img(cor), [["rosto"], ["cabelo", "cores"], ["roupa"]][k], "só a franja" if k == 1 else "", base)
    m = C.mapa_refs(p)
    assert m[0].startswith("panel 1: take ONLY the FACE") and "HAIRSTYLE" in m[1] and "franja" in m[1] and "OUTFIT" in m[2]
    cam = C.colagem_numerada(p, base)
    assert os.path.isfile(cam) and Image.open(cam).getpixel((40, 30))[:2] == (255, 255)  # o número amarelo no canto
    assert C.colagem_numerada(p, base) == cam  # mesma colagem = mesmo arquivo (o Flow reusa a mídia)
    a1 = p["entrada"]["refs"][1]["arquivo"]
    C.editar_ref(p, a1, {"mover": -1}, base)
    assert p["entrada"]["refs"][0]["arquivo"] == a1
    C.editar_ref(p, a1, {"apagar": True}, base)
    assert len(p["entrada"]["refs"]) == 2
    for _ in range(4):
        C.guardar_ref(p, _img(), None, "", base)
    with pytest.raises(C.CriadorErro):
        C.guardar_ref(p, _img(), None, "", base)


def test_ficha_pela_ia_e_sem_ia(base, monkeypatch):
    p = C.criar("", base)
    C.editar_entrada(p, {"descricao": "caçadora de demônios", "inspiracoes": "a frieza do Levi", "travas": "cicatriz no olho"})
    C.guardar_ref(p, _img(), ["rosto"], "", base)
    C.salvar(p, base)
    # sem IA: a aparência sai dos campos
    monkeypatch.setattr(C, "ia_ligada", lambda: False)
    C.montar_ficha(p["id"], base)
    assert "caçadora" in C.carregar(p["id"], base)["ficha"]["aparencia_en"]
    # com IA: olha as imagens numeradas e devolve a ficha
    visto = {}

    class IA:
        @staticmethod
        def imagem_bloco(cam, larg=320):
            return {"type": "image", "cam": cam}

        @staticmethod
        def chamar(rec, sys, conteudo, schema=None, **kw):
            visto.update(rec=rec, sys=sys, conteudo=conteudo, schema=schema)
            return {"nomes": [{"nome": "Akemi", "porque": "brilho vermelho"}, {"nome": "Yuki", "porque": "neve"}],
                    "aparencia_en": "a tall young woman, white short hair with a red streak, black long coat, scar over the left eye",
                    "aparencia_pt": "alta, cabelo branco", "personalidade": "fria mas gentil", "jeito_de_falar": "seca",
                    "bordoes": "Tsc.", "historia": "órfã", "gostos": "doce", "medos": "escuro", "voz": "grave e calma",
                    "paleta": "#111111 preto", "mistura": "rosto: imagem 1; frieza: Levi", "originalidade": "ok — original"}
    monkeypatch.setattr(C, "ia_ligada", lambda: True)
    monkeypatch.setattr(C, "_ia", lambda: IA)
    C.montar_ficha(p["id"], base)
    q = C.carregar(p["id"], base)
    assert q["nome"] == "Akemi" and q["ficha"]["nomes"][1]["nome"] == "Yuki" and "scar" in q["ficha"]["aparencia_en"]
    txt = visto["conteudo"][0]["text"]
    assert visto["rec"] == "criador" and "IMAGEM 1: pegar 🙂 rosto" in txt and "Levi" in txt and "cicatriz" in txt
    assert any(c.get("type") == "image" for c in visto["conteudo"]) and "ORIGINAL" in visto["sys"]
    C.editar_ficha(q, {"nome": "Akemi Kurogane", "voz": "rouca"})
    assert q["nome"] == "Akemi Kurogane" and q["ficha"]["voz"] == "rouca"
    assert "Akemi Kurogane" in C.ficha_txt(q) and "rouca" in C.ficha_txt(q)


def test_design_variacoes_aprovar_e_poses(base, lote):
    p = C.criar("Akemi", base)
    C.editar_entrada(p, {"descricao": "caçadora", "estilo": "aquarela", "travas": "cicatriz no olho esquerdo", "evitar": "asas"})
    C.guardar_ref(p, _img((200, 0, 0)), ["rosto"], "", base)
    C.guardar_ref(p, _img((0, 0, 200)), ["cabelo"], "", base)
    C.aplicar_ficha(p, {"aparencia_en": "white short hair, black coat", "paleta": "#000 black"})
    C.salvar(p, base)
    r = C.gerar_design(p["id"], base, 3, "olhos mais finos")
    assert r["enviadas"] == 3 and len(lote.itens) == 3
    it = lote.itens[0]
    assert os.path.isfile(it["referencia_arquivo"]) and "2 NUMBERED panels" in it["prompt"] and "panel 1: take ONLY the FACE" in it["prompt"]
    assert "watercolor" in it["prompt"] and "cicatriz" in it["prompt"] and "Avoid: asas" in it["prompt"] and "Variation 1 of 3" in it["prompt"]
    assert "olhos mais finos" in it["prompt"] and "chroma-key green" in it["prompt"] and "FULL BODY" in it["prompt"]
    # o Flow termina → PNG transparente
    _terminar(lote)
    assert C.acompanhar(p["id"], base)
    q = C.carregar(p["id"], base)
    vs = q["design"]["variacoes"]
    assert all(v["estado"] == "pronta" and v["arquivo"] for v in vs)
    png = Image.open(os.path.join(C.pasta(p["id"], base), "design", vs[0]["arquivo"]))
    assert png.mode == "RGBA" and png.getpixel((5, 5))[3] == 0
    # 🎯 variar a partir de uma: a referência é a própria variação
    C.gerar_design(p["id"], base, 4, "sem o casaco", vs[0]["id"])
    assert len(lote.itens) == 5 and lote.itens[-1]["referencia_arquivo"].endswith(vs[0]["bruto"]) and "previous design" in lote.itens[-1]["prompt"]
    # sem aprovar não tem poses
    with pytest.raises(C.CriadorErro):
        C.criar_poses(p["id"], ["giro"], [], base)
    C.aprovar(p["id"], vs[1]["id"], base)
    r = C.criar_poses(p["id"], ["giro", "expressoes"], ["segurando uma espada nas costas"], base)
    import personagens_pod as pp
    proj = pp.carregar(r["pod"], base)
    nomes = [x["arquivo"] for x in proj["dados"]["poses"]]
    assert nomes[0] == "akemi_design.png" and "akemi_costas.png" in nomes and "akemi_bravo.png" in nomes and "akemi_extra1.png" in nomes
    assert proj["mestre"]["arquivo"] == "akemi_design.png" and pp.arquivo_atual(proj, "akemi_design.png", base)
    assert r["enviadas"] == len(nomes) - 1  # todas menos a mestre (já pronta)
    ult = lote.itens[-1]
    assert "APPROVED MASTER" in ult["prompt"] and "white short hair" in ult["prompt"] and "watercolor" in ult["prompt"]
    # rodar de novo com outro pacote: as que já existem ficam, as novas entram
    r2 = C.criar_poses(p["id"], ["react"], [], base)
    assert r2["pod"] == r["pod"]
    proj = pp.carregar(r["pod"], base)
    assert "akemi_react_chocado.png" in [x["arquivo"] for x in proj["dados"]["poses"]] and "akemi_frente.png" in [x["arquivo"] for x in proj["dados"]["poses"]]
    assert C.estado_poses(C.carregar(p["id"], base), base)["tem"]
    z = zipfile_nomes(C.zip_personagem(p["id"], base))
    assert "akemi/ficha.txt" in z and "akemi/akemi_design.png" in z and "akemi/ficha.json" in z


def zipfile_nomes(b):
    import zipfile
    return zipfile.ZipFile(io.BytesIO(b)).namelist()


def test_rotas_da_pagina(base, lote, monkeypatch):
    import app as A
    monkeypatch.setattr(C, "ia_ligada", lambda: False)
    c = A.app.test_client()
    assert "Criador de personagens" in c.get("/modelos-video").get_data(as_text=True)
    r = c.post("/criador-personagens/novo", data={"nome": "", "descricao": "um robô jardineiro", "estilo": "pixel",
                                                  "refs": [(io.BytesIO(_png_bytes()), "a.png"), (io.BytesIO(_png_bytes((0, 0, 255))), "b.png")]},
               content_type="multipart/form-data")
    pid = r.headers["Location"].split("/")[-1]
    h = c.get(f"/criador-personagens/{pid}").get_data(as_text=True)
    assert "🧬" in h and "Expressionismo" in h and "Giro" in h
    e = c.get(f"/criador-personagens/{pid}/estado").get_json()
    assert len(e["entrada"]["refs"]) == 2 and e["entrada"]["estilo"] == "pixel"
    a0 = e["entrada"]["refs"][0]["arquivo"]
    assert c.post(f"/criador-personagens/{pid}/refs/{a0}", json={"pegar": ["rosto", "olhos"]}).get_json()["ok"]
    assert c.get(f"/criador-personagens/{pid}/arquivo/refs/{a0}").status_code == 200
    assert c.post(f"/criador-personagens/{pid}/dados", json={"estilo": "outro", "estilo_livre": "expressionismo", "original": False}).get_json()["ok"]
    assert c.post(f"/criador-personagens/{pid}/ficha/ia", json={}).get_json()["ok"]
    for _ in range(50):
        t = c.get(f"/criador-personagens/{pid}/estado").get_json()["tarefa"]
        if t and t.get("fim"):
            break
        time.sleep(0.05)
    assert c.post(f"/criador-personagens/{pid}/ficha", json={"nome": "Brotinho", "personalidade": "calmo"}).get_json()["nome"] == "Brotinho"
    assert c.post(f"/criador-personagens/{pid}/design/gerar", json={"n": 2}).get_json()["enviadas"] == 2
    assert "expressionismo" in lote.itens[-1]["prompt"]
    v = c.post(f"/criador-personagens/{pid}/design/enviar", data={"arquivo": (io.BytesIO(_png_bytes()), "d.png")},
               content_type="multipart/form-data").get_json()["id"]
    assert c.post(f"/criador-personagens/{pid}/design/{v}/aprovar", json={}).get_json()["ok"]
    r = c.post(f"/criador-personagens/{pid}/poses", json={"pacotes": ["acao"], "extras": "dormindo\n"}).get_json()
    assert r["ok"] and r["enviadas"] == 9
    assert c.get(f"/criador-personagens/{pid}/zip").status_code == 200
    assert "Brotinho" in c.get("/criador-personagens").get_data(as_text=True)
    assert c.post(f"/criador-personagens/{pid}/excluir").status_code == 302
    assert c.get(f"/criador-personagens/{pid}").status_code == 404
