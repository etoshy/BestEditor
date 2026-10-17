"""🎭 v84_128: elenco (rostos e idades) → cenas do pod com o rosto certo na idade certa."""
import json

import pytest

import cenas_lote
import dossies as ds
import elenco


@pytest.fixture()
def proj(tmp_path):
    from PIL import Image
    base = str(tmp_path)
    p = ds.criar(base, "John List")
    import os
    os.makedirs(ds.pasta_midias(base, p["id"]), exist_ok=True)
    for nome, desc in (("pai.jpg", "John List em 1971"), ("filho.jpg", "John Frederick List criança"), ("familia.jpg", "a família")):
        Image.new("RGB", (64, 64)).save(os.path.join(ds.pasta_midias(base, p["id"]), nome))
        ds.adicionar_midia(p, tipo="foto", arquivo=nome, descricao=desc)
    ds.salvar(base, p)
    return base, p


def test_ler_e_rosto_com_idade(proj):
    base, p = proj
    el = elenco.ler({"pessoas": [
        {"nome": "John List", "papel": "o pai", "nascimento": 1925, "aparencia": "thin white man, glasses",
         "fotos": [{"midia": "I1", "idade": 46, "ano": 1971, "quem_na_foto": "", "so_ele": True, "rosto_visivel": True},
                   {"midia": "I3", "idade": 45, "quem_na_foto": "the man with glasses on the left", "so_ele": False}]},
        {"nome": "John Frederick", "papel": "filho", "fotos": [{"midia": "I2", "idade": 10, "so_ele": True}, {"midia": "X9"}]},
        {"nome": "Sem foto", "fotos": []}]}, elenco.ids_de_fotos(base, p))
    assert [x["nome"] for x in el["pessoas"]] == ["John List", "John Frederick"]
    assert len(el["pessoas"][1]["fotos"]) == 1
    prompt, refs = elenco.rostos_da_cena(el, [{"nome": "john list", "idade": 64}, {"nome": "John Frederick", "idade": 30}],
                                         "A courtroom in 1990.", base, p)
    assert [n for n, _c in refs] == ["I1.jpg", "I2.jpg"]
    assert "image 1, about 64 years old, 18 years older" in prompt and "image 2, about 30 years old, 20 years older" in prompt
    assert "grown adult face" in prompt and "thin white man" in prompt
    assert elenco.rostos_da_cena(el, [{"nome": "Ninguém", "idade": 3}], "x", base, p) == ("x", [])
    assert "nasceu em 1925" in elenco.bloco_para_cenas(el)


def test_descrever_devolve_pessoas_do_elenco(monkeypatch):
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: True)
    visto = {}

    def chamar(recurso, system, conteudo, schema=None, **kw):
        visto["system"], visto["schema"] = system, schema
        return {"cenas": [{"n": 1, "visual": "v", "busca": "b", "dificil": 7, "prompt_imagem": "p", "ano": 1990,
                           "pessoas": [{"nome": "John List", "idade": 64}, {"nome": "Desconhecido", "idade": 3}]}]}
    monkeypatch.setattr(ia_servico, "chamar", chamar)
    el = {"pessoas": [{"nome": "John List", "papel": "pai", "nascimento": 1925, "usar": True, "fotos": [{"midia": "I1", "idade": 46}]}]}
    info = cenas_lote.descrever([{"start": 0, "end": 5, "fala": "Em 1990 ele foi julgado."}], elenco=el)
    assert info[1]["pessoas"] == [{"nome": "John List", "idade": 64}] and info[1]["ano"] == 1990
    assert "ELENCO" in visto["system"] and "pessoas" in json.dumps(visto["schema"])
    info = cenas_lote.descrever([{"start": 0, "end": 5, "fala": "x y z"}])
    assert "pessoas" not in info[1]


def test_cataloga_em_lotes_com_cartaz_e_locais(proj, monkeypatch):
    base, p = proj
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: True)
    monkeypatch.setattr(ia_servico, "imagem_bloco", lambda c, largura=0: {"type": "image", "x": c})
    monkeypatch.setattr(elenco, "LOTE_IA", 2)
    chamadas = []

    def chamar(recurso, system, conteudo, schema=None, **kw):
        chamadas.append(conteudo)
        ids = [c["text"].split("]")[0][1:] for c in conteudo if c.get("type") == "text" and c["text"].startswith("[")]
        r = {"pessoas": [], "locais": []}
        if "I1" in ids:
            r["pessoas"].append({"nome": "John List", "papel": "pai", "nascimento": 0, "aparencia": "",
                                 "fotos": [{"midia": "I1", "idade": 46, "como_sei": "legenda"}]})
        if "I3" in ids:
            r["pessoas"].append({"nome": "john list", "papel": "", "nascimento": 1925, "aparencia": "glasses",
                                 "fotos": [{"midia": "I3", "idade": 45, "como_sei": "cartaz de procurado"}]})
        if "I2" in ids:
            r["locais"].append({"nome": "Casa de Westfield", "tipo": "casa", "descricao": "large victorian house", "ano": 1971,
                                "fotos": ["I2"]})
        return r
    monkeypatch.setattr(ia_servico, "chamar", chamar)
    el = elenco.montar_com_ia(base, p)
    assert len(chamadas) == 2 and "JÁ CATALOGADOS" in chamadas[1][-1]["text"]
    assert [x["nome"] for x in el["pessoas"]] == ["John List"]
    jl = el["pessoas"][0]
    assert sorted(f["midia"] for f in jl["fotos"]) == ["I1", "I3"] and jl["nascimento"] == 1925 and jl["fotos"][1]["como_sei"] == "cartaz de procurado"
    assert el["locais"][0]["nome"] == "Casa de Westfield"
    prompt, refs = elenco.rostos_da_cena(el, [], "A house at night in 1971.", base, p, lugar="casa de westfield")
    assert [n for n, _c in refs] == ["I2.jpg"] and "place shown in image 1" in prompt and "Use the face" not in prompt


def test_epoca_cronologia_e_local_sem_foto(proj):
    base, p = proj
    el = elenco.ler({"pessoas": [{"nome": "John List", "nascimento": 1925, "fotos": [{"midia": "I1", "idade": 46}]}],
                     "locais": [{"nome": "Breeze Knoll", "tipo": "casa", "fotos": [],
                                 "descricao": "a large 19-room Victorian mansion with a ballroom, dark wood panelling, "
                                              "stained glass skylight, overgrown garden, Westfield New Jersey"},
                                {"nome": "Lugar vago", "descricao": "uma casa", "fotos": []}],
                     "cronologia": [{"ano": 1971, "evento": "o crime"}, {"ano": 1925, "evento": "nasce John"}, {"ano": 0, "evento": "x"}]},
                    elenco.ids_de_fotos(base, p))
    assert [x["nome"] for x in el["locais"]] == ["Breeze Knoll"]
    assert [c["ano"] for c in el["cronologia"]] == [1925, 1971] and "CRONOLOGIA" in elenco.bloco_para_cenas(el)
    prompt, refs = elenco.rostos_da_cena(el, [{"nome": "John List", "idade": 0}], "He leaves the house.", base, p,
                                         lugar="Breeze Knoll", ano=1989)
    assert "about 64 years old, 18 years older" in prompt and "Location (Breeze Knoll): a large 19-room" in prompt
    prompt, refs = elenco.rostos_da_cena(el, [], "Night.", base, p, lugar="Breeze Knoll")
    assert refs == [] and "Location (Breeze Knoll)" in prompt
    assert "1970s 35mm color film" in cenas_lote.look_da_epoca(1971) and "of 1971" in cenas_lote.look_da_epoca(1971)
    assert cenas_lote.look_da_epoca(0) == ""
    j = cenas_lote.montar_json([{"start": 0, "end": 5, "fala": "f"}], {1: {"prompt_imagem": "A house", "ano": 1971}}, {0}, epoca=True)
    assert "1970s 35mm" in j["segments"][0]["query"]


def test_cataloga_so_texto_sem_fotos(tmp_path, monkeypatch):
    import ia_servico
    base = str(tmp_path)
    p = ds.criar(base, "Caso sem fotos")
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: True)
    visto = []
    monkeypatch.setattr(ia_servico, "chamar", lambda r, s, c, sc=None, **kw: visto.append(c) or {
        "pessoas": [], "locais": [{"nome": "A fazenda", "tipo": "casa", "ano": 1950, "fotos": [],
                                   "descricao": "an isolated wooden farmhouse with a red barn and a dirt road, flat fields of corn around"}],
        "cronologia": [{"ano": 1950, "evento": "o desaparecimento"}]})
    el = elenco.montar_com_ia(base, p)
    assert el["locais"][0]["nome"] == "A fazenda" and el["cronologia"][0]["ano"] == 1950
    assert "Ainda não tenho fotos" in visto[0][-1]["text"]


def test_descrever_em_blocos_de_20_e_refaz_as_que_faltaram(monkeypatch):
    import re
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: True)
    chamadas = []

    def chamar(rec, system, conteudo, schema=None, **kw):
        ns = [int(x) for x in re.findall(r"^\[(\d+)\]", conteudo, re.M)]
        chamadas.append(ns)
        if len(chamadas) == 1:  # o 1º bloco falha inteiro
            return None
        return {"cenas": [{"n": n, "visual": "v", "busca": "b", "dificil": 5, "prompt_imagem": f"p{n}", "ano": 0}
                          for n in ns if n % 7 or len(chamadas) > 3]}
    monkeypatch.setattr(ia_servico, "chamar", chamar)
    cenas = [{"start": i * 5, "end": i * 5 + 5, "fala": f"fala {i}"} for i in range(45)]
    info = cenas_lote.descrever(cenas)
    assert len(info) == 45 and info[45]["prompt_imagem"] == "p45"
    assert max(len(c) for c in chamadas) <= 20 and len(chamadas) > 3
