"""v84_394: 🎨 estilo de arte por cima do pacote do canal (🖌 Rusty Art) — cenas, thumbnails e Flow/Runpod do editor."""
import json
import os

import marca_visual as mv
import thumbs_flow
from test_v84_168_marca import marca  # noqa: F401 — fixture


def test_rusty_nas_cenas_e_thumbs(marca):  # noqa: F811
    base, m = marca
    original = json.load(open(os.path.join(m["dir"], "brand_guide.json"), encoding="utf-8"))
    mv.salvar_estilo_arte(m, "rusty", cenas=True, thumbs=True)
    m2 = mv.carregar(base, m["slug"])
    p = mv.montar_prompt(m2, {"tipo": "cena", "assunto_en": "Socrates talking in the agora"})
    assert "rusty art" in p and "Vintage noir" not in p and "photorealistic" in p.split("Avoid:")[1]
    t = mv.montar_prompt(m2, {"tipo": "thumbnail", "assunto_en": "Socrates"})
    assert "rusty art" in t
    assert "rusty art" in thumbs_flow.estilo_da_marca(base, m["slug"])
    # o arquivo do pacote não muda, e exportar leva o original
    assert json.load(open(os.path.join(m["dir"], "brand_guide.json"), encoding="utf-8")) == original


def test_so_thumbs(marca):  # noqa: F811
    base, m = marca
    mv.salvar_estilo_arte(m, "rusty", cenas=False, thumbs=True)
    m2 = mv.carregar(base, m["slug"])
    assert "Vintage noir" in mv.montar_prompt(m2, {"tipo": "cena", "assunto_en": "x"})
    assert "rusty art" in thumbs_flow.estilo_da_marca(base, m["slug"])
    mv.salvar_estilo_arte(m, "")
    assert "rusty art" not in thumbs_flow.estilo_da_marca(base, m["slug"])


def test_tira_do_avoid_o_que_briga():
    g = {"generation_system": {"style_lock_en": "documentary photograph", "negative_prompt_global_en": "cartoon, illustration, text"}}
    r = mv.aplicar_estilo_arte(g, {"preset": "rusty"})
    neg = r["generation_system"]["negative_prompt_global_en"]
    assert neg.startswith("text,") and "cartoon" not in neg.split("photorealistic")[0]
    assert g["generation_system"]["style_lock_en"] == "documentary photograph"


def test_flow_e_runpod_recebem_o_estilo():
    import app  # noqa: F401 — põe o toolkit no caminho
    from googleflow import googleflow_client as gf
    import runpod_gerador as rg
    cfg = {"_estilo_arte_en": "rough hand-drawn rusty sketch"}
    q = gf.com_estilo("um filósofo grego", cfg)
    assert q.endswith("rough hand-drawn rusty sketch") and gf.com_estilo(q, cfg) == q
    assert gf.com_estilo("x", {}) == "x"
    assert "rusty sketch" in rg._regra("black-forest-labs-flux-1-schnell", "a greek philosopher", cfg)["prompt"]


def test_rota_da_marca(marca, monkeypatch):  # noqa: F811
    base, m = marca
    import app as A
    import marca_rotas  # noqa: F401
    monkeypatch.setattr(mv, "_pasta", lambda b, slug="": os.path.join(base, mv.PASTA, slug) if slug else os.path.join(base, mv.PASTA))
    c = A.app.test_client()
    d = c.post(f"/marca/{m['slug']}/estilo-arte", json={"preset": "rusty", "cenas": True, "thumbs": False}).get_json()
    assert d["ok"] and d["estilo"] == {"preset": "rusty", "cenas": True, "thumbs": False}
    assert c.post(f"/marca/{m['slug']}/estilo-arte", json={"preset": "xx"}).status_code == 400
    html = c.get(f"/marca/{m['slug']}").get_data(as_text=True)
    assert 'id="eaPreset"' in html and "Rusty Art" in html


def test_thumb_com_estilo_proprio_e_ideias_por_estilo(tmp_path, monkeypatch):
    """v84_397: cada thumbnail pode ter o seu estilo; o +5 ideias distribui entre os estilos marcados."""
    import estilos_arte
    assert len(estilos_arte.ESTILOS) >= 8 and "rusty" in estilos_arte.ESTILOS
    base = str(tmp_path)
    d = thumbs_flow.sincronizar(base, "avulso", "abcdef0123", [{"ideia": "Sócrates", "prompt": "Socrates portrait"}])
    it = d["itens"][0]
    d = thumbs_flow.editar(base, "avulso", "abcdef0123", 1, estilo_arte="nanquim")
    p = thumbs_flow.prompt_flow(d["itens"][0], estilo="CANAL STYLE")
    assert "ink wash" in p and "CANAL STYLE" not in p and p.startswith("Socrates portrait")
    d = thumbs_flow.editar(base, "avulso", "abcdef0123", 1, estilo_arte="")
    assert "CANAL STYLE" in thumbs_flow.prompt_flow(d["itens"][0], estilo="CANAL STYLE")
    j = thumbs_flow.para_json(d, "/thumbs/avulso/abcdef0123")
    assert ("rusty", estilos_arte.ESTILOS["rusty"]["nome"]) in j["estilos"]

    import ia_servico as ia
    vistos = {}
    monkeypatch.setattr(ia, "motivo_desligado", lambda r=None: None)

    def chamar(rec, system, conteudo, **kw):
        vistos["system"] = system
        return {"thumbnails": [{"ideia": f"ideia {k}", "texto": "X", "prompt": f"scene {k}"} for k in range(3)]}
    monkeypatch.setattr(ia, "chamar", chamar)
    novas = thumbs_flow.pedir_ideias("Título", "roteiro", [], 3, "pt", "", ["rusty", "oleo_classico", "xx"])
    assert [n["estilo_arte"] for n in novas] == ["rusty", "oleo_classico", "rusty"]
    assert "Rusty Art" in vistos["system"] and "óleo" in vistos["system"]
