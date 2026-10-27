"""🗺 v84_241 — Lugares e mundos (no 🧬 Criador): escalas, hierarquia, ficha (IA), pessoas → personagens, pinos,
sub-lugares, régua, fotos e mapa no Flow; época e idades no personagem."""
import io
import os
import time
import zipfile

import pytest
from PIL import Image

import criador_lugares as CL
import criador_personagens as C
from test_v84_239_criador import Lote, _img, _png_bytes, _terminar, lote  # noqa: F401


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("CRIADOR_PERSONAGENS_DIR", str(tmp_path / "criador"))
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pod"))
    return str(tmp_path)


def test_hierarquia_pinos_regua_e_sub_lugares(base):
    mundo = CL.criar("Aurelia", "mundo", "", base, descricao="um mundo de ilhas flutuantes", estilo="aquarela", epoca="medieval")
    assert len(CL.ESCALAS) >= 12 and "galaxia" in CL.ESCALAS and "comodo" in CL.ESCALAS
    pais = CL.criar("Reino de Vel", "pais", mundo["id"], base)
    assert pais["entrada"]["estilo"] == "aquarela" and pais["entrada"]["epoca"] == "medieval"  # herda do lugar de cima
    assert [x["nome"] for x in CL.caminho(pais, base)] == ["Aurelia", "Reino de Vel"]
    assert [f["id"] for f in CL.filhos(mundo["id"], base)] == [pais["id"]]
    # 📍 pinos: novo, mover, virar sub-lugar
    x = CL.editar_pino(pais, "novo", {"nome": "Porto Âmbar", "x": 0.8, "y": 0.2, "descricao": "a capital no litoral"})
    CL.editar_pino(pais, x["id"], {"x": 1.7, "y": -3})
    assert (x["x"], x["y"]) == (1.0, 0.0) and x["manual"]
    CL.salvar(pais, base)
    sub = CL.sub_lugar_do_pino(pais["id"], x["id"], base)
    cid = CL.carregar(sub, base)
    assert cid["escala"] == "regiao" and cid["pai"] == pais["id"] and "capital" in cid["entrada"]["descricao"]
    assert CL.sub_lugar_do_pino(pais["id"], x["id"], base) == sub  # 2º clique: abre o mesmo
    # 📏 régua: o país padrão tem 1200 km de largura
    assert CL.escala_mapa(pais) == (1200.0, "km")
    assert abs(CL.distancia(pais, (0.0, 0.5), (0.5, 0.5)) - 600) < 0.01
    pais = CL.carregar(pais["id"], base)
    pais["mapa"].update(largura=300, unidade="léguas")
    assert CL.escala_mapa(pais) == (300.0, "léguas")
    # excluir o do meio: os de baixo sobem
    CL.excluir(pais["id"], base)
    assert CL.carregar(sub, base)["pai"] == mundo["id"]
    with pytest.raises(CL.LugarErro):
        CL.editar_entrada(mundo, {"pai": mundo["id"]})


def test_ficha_ia_pessoas_viram_personagens_e_pinos(base, monkeypatch):
    p = CL.criar("", "cidade", "", base, descricao="cidade sobre ossos de baleia", epoca="vitoriana")
    CL.guardar_ref(p, _img(), ["arquitetura", "luz"], "as torres", base)
    CL.editar_pino(p, "novo", {"nome": "Meu Farol", "x": 0.1, "y": 0.1})
    CL.salvar(p, base)
    visto = {}

    class IA:
        @staticmethod
        def imagem_bloco(cam, larg=320):
            return {"type": "image"}

        @staticmethod
        def chamar(rec, sys, conteudo, schema=None, **kw):
            visto.update(txt=conteudo[0]["text"], sys=sys)
            return {"nomes": [{"nome": "Cetária", "porque": "cetáceos"}], "descricao_en": "a foggy port city built on whale bones",
                    "descricao_pt": "porto na neblina", "historia": "fundada por baleeiros", "linha_do_tempo": [{"quando": "ano 1", "evento": "fundação"}],
                    "pessoas": [{"nome": "Lady Marrow", "papel": "governadora", "descricao": "fria e astuta", "aparencia_en": "tall woman, black victorian dress"}],
                    "cultura": "festa do âmbar", "clima": "neblina", "economia": "âmbar", "curiosidades": "x", "segredos": "y",
                    "pontos": [{"nome": "Doca Velha", "tipo": "porto", "descricao": "d", "x": 0.7, "y": 0.6, "escala": "bairro"},
                               {"nome": "meu farol", "tipo": "x", "descricao": "", "x": 0.5, "y": 0.5, "escala": ""}],
                    "mapa_en": "the sea to the east", "originalidade": "ok — original"}
    monkeypatch.setattr(C, "ia_ligada", lambda: True)
    monkeypatch.setattr(C, "_ia", lambda: IA)
    CL.montar_ficha(p["id"], base)
    q = CL.carregar(p["id"], base)
    assert q["nome"] == "Cetária" and "arquitetura" in visto["txt"] and "vitoriana" in visto["txt"] and "WORLDBUILDER" in visto["sys"]
    assert [x["nome"] for x in q["pinos"]] == ["Meu Farol", "Doca Velha"]  # o seu fica; o repetido da IA não entra
    ps = q["ficha"]["pessoas"][0]
    cid = CL.pessoa_vira_personagem(p["id"], ps["id"], base)
    c = C.carregar(cid, base)
    assert c["nome"] == "Lady Marrow" and c["entrada"]["lugar"] == p["id"] and c["entrada"]["epoca"] == "vitoriana"
    assert "black victorian dress" in c["ficha"]["aparencia_en"]
    assert CL.pessoa_vira_personagem(p["id"], ps["id"], base) == cid
    assert [x["id"] for x in CL.personagens_daqui(p["id"], base)] == [cid]
    # o personagem leva a época e o lugar pro design
    pr = C.prompt_design(c)
    assert "Era: Victorian era" in pr and "Cetária" in pr and "whale bones" in pr
    assert "Lady Marrow" in CL.ficha_txt(CL.carregar(p["id"], base), base)


def test_fotos_mapa_no_flow_e_zip(base, lote):
    p = CL.criar("Vila Musgo", "bairro", "", base, descricao="vila de casas de musgo", estilo="ghibli")
    CL.guardar_ref(p, _img(), ["mapa"], "", base)
    CL.editar_pino(p, "novo", {"nome": "Moinho", "x": 0.2, "y": 0.8})
    CL.salvar(p, base)
    r = CL.gerar_fotos(p["id"], ["rua", "alto", "inexistente"], "mais chuva", base)
    assert r["enviadas"] == 2
    it = lote.itens[0]
    assert "main street" in it["prompt"] and "mais chuva" in it["prompt"] and "16:9" in it["prompt"]
    assert "referencia_arquivo" not in it  # a única referência é só pro mapa
    CL.gerar_mapa(p["id"], 2, "", base)
    m = lote.itens[-1]
    assert "NEIGHBORHOOD MAP" in m["prompt"] and "NO TEXT" in m["prompt"] and "Moinho" in m["prompt"] and "south-west" in m["prompt"]
    assert os.path.isfile(m["referencia_arquivo"])
    _terminar(lote)
    assert CL.acompanhar(p["id"], base)
    q = CL.carregar(p["id"], base)
    assert all(x.get("arquivo") for x in q["fotos"]) and CL.mapa_aprovado(q)  # o 1º mapa já vale
    CL.acao_imagem(p["id"], q["fotos"][0]["id"], "aprovar", base)
    assert CL.carregar(p["id"], base)["fotos"][0]["aprovada"]
    png = Image.open(io.BytesIO(CL.mapa_com_pinos(q, base)))
    assert png.size[0] > 100
    nomes = zipfile.ZipFile(io.BytesIO(CL.zip_lugar(p["id"], base))).namelist()
    assert "vila_musgo/mapa.jpg" in nomes and "vila_musgo/mapa_com_pinos.png" in nomes and "vila_musgo/lugar.json" in nomes
    assert sum(n.startswith("vila_musgo/fotos/") for n in nomes) == 2
    mp = CL.enviar_imagem(p["id"], _img((10, 80, 10), (1600, 900)), "mapa", base)
    assert CL.carregar(p["id"], base)["mapa"]["aprovado"] == mp["id"]


def test_epoca_idades_e_paginas(base, lote, monkeypatch):
    import app as A
    monkeypatch.setattr(C, "ia_ligada", lambda: False)
    assert "idades" in C.PACOTES and "pos_apocalipse" in C.EPOCAS
    c = A.app.test_client()
    h = c.get("/criador-personagens").get_data(as_text=True)
    assert "Lugares e mundos" in h and "Galáxia" in h
    r = c.post("/criador-lugares/novo", data={"nome": "Nebulosa Vela", "escala": "galaxia", "descricao": "galáxia em espiral roxa"},
               content_type="multipart/form-data")
    lid = r.headers["Location"].split("/")[-1]
    assert "Régua" in c.get(f"/criador-lugares/{lid}").get_data(as_text=True)
    e = c.get(f"/criador-lugares/{lid}/estado").get_json()
    assert e["escala_mapa"] == {"largura": 100000.0, "unidade": "anos-luz"} and e["vistas"]
    pn = c.post(f"/criador-lugares/{lid}/pinos/novo", json={"nome": "Setor Kappa", "x": 0.3, "y": 0.4, "escala": "sistema"}).get_json()["pino"]
    sid = c.post(f"/criador-lugares/{lid}/pinos/{pn['id']}/sub", json={}).get_json()["id"]
    assert CL.carregar(sid, base)["escala"] == "sistema"
    assert c.post(f"/criador-lugares/{lid}/escala", json={"largura": "120000", "unidade": "anos-luz"}).get_json()["ok"]
    assert c.post(f"/criador-lugares/{lid}/mapa/gerar", json={"n": 1}).get_json()["enviadas"] == 1
    assert c.post(f"/criador-lugares/{lid}/fotos/gerar", json={}).get_json()["enviadas"] == len(CL.ESCALAS["galaxia"][3])
    assert c.post(f"/criador-lugares/{lid}/ficha/ia", json={}).get_json()["ok"]
    for _ in range(50):
        t = c.get(f"/criador-lugares/{lid}/estado").get_json()["tarefa"]
        if t and t.get("fim"):
            break
        time.sleep(0.05)
    assert c.post(f"/criador-lugares/{lid}/ficha", json={"historia": "nasceu de duas galáxias", "pessoas": [{"nome": "Almirante Ko", "papel": "almirante"}]}).get_json()["ok"]
    ps = CL.carregar(lid, base)["ficha"]["pessoas"][0]
    pid = c.post(f"/criador-lugares/{lid}/pessoa/{ps['id']}/personagem", json={}).get_json()["id"]
    # o personagem: época "outra" e o lugar de origem; pacote de idades
    assert c.post(f"/criador-personagens/{pid}/dados", json={"epoca": "outro", "epoca_livre": "ano 3200", "lugar": lid}).get_json()["ok"]
    h = c.get(f"/criador-personagens/{pid}").get_data(as_text=True)
    assert "Época" in h and "Outras idades" in h and "Nebulosa Vela" in h
    pc = C.carregar(pid, base)
    assert "ano 3200" in C.prompt_design(pc)
    assert c.get(f"/criador-lugares/{lid}/zip").status_code == 200
    assert c.post(f"/criador-lugares/{sid}/excluir").headers["Location"].endswith(f"/criador-lugares/{lid}")
