"""📸 v84_127: marcas que a IA não pode perder + fotos pro roteiro (perguntas e posicionar)."""
import io
import json

import pytest

import adaptar_tts
import dossies as ds
import fotos_roteiro as fr
import marcas_seguras as ms
import revisao_roteiro as rv

ORIG = ("Em 1971 tudo mudou. [I3] John List matou a família em Westfield.\n\n[[INSCREVA]]\n\n"
        "[I5] A casa ficou vazia por semanas. Os vizinhos não notaram nada. [I3] Ele fugiu sem deixar rastros.\n\n"
        "[[VENDA: compre o livro]]")


def test_restaura_marcas_que_a_ia_tirou():
    novo = ("Em 1971, tudo mudou. John List matou a família, em Westfield. A casa ficou vazia por semanas. "
            "Os vizinhos não perceberam nada. [I3] Ele fugiu sem deixar nenhum rastro.")
    t, volta = ms.restaurar(ORIG, novo)
    assert t.count("[I3]") == 2 and "[I5] A casa" in t
    assert "\n[[INSCREVA]]\n" in t and t.strip().endswith("[[VENDA: compre o livro]]")
    assert t.index("[[INSCREVA]]") < t.index("[I5]")
    assert sorted(volta) == sorted(["[I3]", "[[INSCREVA]]", "[I5]", "[[VENDA: compre o livro]]"])
    assert ms.restaurar(ORIG, ORIG) == (ORIG, [])


def test_adaptar_tts_e_revisao_nao_perdem_marcas():
    r = adaptar_tts.ler_resposta(ms.MARCA.sub("", ORIG), ORIG)
    assert r["texto"].count("[I3]") == 2 and "[[VENDA" in r["texto"] and any("🔒" in a for a in r["avisos"])
    d = rv.aplicar(ORIG, json.dumps({"trocas": [{"de": "[I5] A casa ficou vazia", "para": "A casa ficou abandonada"}]}))
    assert "[I5] A casa ficou abandonada" in d["texto"]


def test_frases_e_posicionar():
    f = fr.frases(ORIG)
    assert [x["texto"] for x in f][:2] == ["Em 1971 tudo mudou.", "John List matou a família em Westfield."]
    assert f[1]["midias"] == ["I3"] and not any("compre" in x["texto"] for x in f)
    novo, info = fr.aplicar_posicoes(ORIG, json.dumps({"usos": [{"midia": "I9", "frases": [1, 2, 4]}, {"midia": "X1", "frases": [4]}]}),
                                     {"I3", "I5", "I9"})
    assert novo.startswith("[I9] Em 1971") and "[I9] Os vizinhos" in novo and info["postas"] == 2 and info["ignoradas"] == 2


@pytest.fixture()
def cliente(tmp_path):
    from flask import Flask
    import dossies_rotas
    app = Flask(__name__, template_folder="templates")
    app.config["TESTING"] = True
    dossies_rotas.registrar(app, str(tmp_path))
    fr.registrar(app, str(tmp_path))
    p = ds.criar(str(tmp_path), "John List")
    for k in (3, 5):
        while len(p.get("midias") or []) < k:
            ds.adicionar_midia(p, tipo="foto", descricao=f"foto {len(p.get('midias') or []) + 1}")
    p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": ORIG, "titulos": ["t"]}), p)
    ds.salvar(str(tmp_path), p)
    return app.test_client(), p["id"], str(tmp_path)


def test_fluxo_perguntas_envio_e_posicionar(cliente):
    c, pid, base = cliente
    r = c.post(f"/modelos-video/{pid}/fotos-roteiro/perguntas/prompt", json={})
    assert r.status_code == 200 and "Helen" in r.get_json()["prompt"] or "Roteiro" in r.get_json()["prompt"]
    resp = {"perguntas": [{"tipo": "pessoa", "alvo": "Helen List", "pergunta": "Você tem foto de Helen List?", "vezes": 3},
                          {"tipo": "lugar", "alvo": "Casa de Westfield", "pergunta": "Tem foto da casa?", "ja_tem": ["I5"]}]}
    d = c.post(f"/modelos-video/{pid}/fotos-roteiro/perguntas/ler", json={"texto": json.dumps(resp)}).get_json()
    assert [q["id"] for q in d["perguntas"]] == ["P1", "P2"] and d["perguntas"][1]["ja_tem"] == ["I5"]
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (20, 20)).save(buf, "PNG")
    buf.seek(0)
    r = c.post(f"/modelos-video/{pid}/midia", data={"arquivo": (buf, "helen.png"), "descricao": "Helen List", "pergunta": "P1"},
               content_type="multipart/form-data")
    novo_id = r.get_json()["midia"]["id"]
    est = c.get(f"/modelos-video/{pid}/fotos-roteiro").get_json()
    assert est["enviadas"] == {"P1": [novo_id]}
    pr = c.post(f"/modelos-video/{pid}/fotos-roteiro/posicionar/prompt", json={"modo": "novas"}).get_json()["prompt"]
    assert f"{novo_id}: [pra: Helen List]" in pr and "S1:" in pr
    d = c.post(f"/modelos-video/{pid}/fotos-roteiro/posicionar/ler",
               json={"texto": json.dumps({"usos": [{"midia": novo_id, "frases": [1, 4]}]})}).get_json()
    assert d["postas"] == 2 and d["uso"][novo_id] == 2 and d["pode_desfazer"]
    p = ds.carregar(base, pid)
    assert p["resultado"]["roteiro"].startswith(f"[{novo_id}] Em 1971")
    assert f"[{novo_id}]" not in p["resultado"]["roteiro_final"]  # a voz não lê a marca
    assert sum(1 for m in p["resultado"]["momentos"] if m["midia"] == novo_id) == 2
    assert c.post(f"/modelos-video/{pid}/fotos-roteiro/desfazer", json={}).status_code == 200
    assert ds.carregar(base, pid)["resultado"]["roteiro"] == ORIG


def test_cenas_do_pod_usam_as_fotos_do_modelo():
    import cenas_lote
    cenas = [{"start": 0, "end": 5, "fala": "Em 1971 tudo mudou."}, {"start": 5, "end": 10, "fala": "John List matou a família em"},
             {"start": 10, "end": 15, "fala": "Westfield. A casa ficou vazia por semanas."},
             {"start": 15, "end": 20, "fala": "Os vizinhos não notaram nada. Ele fugiu sem deixar rastros."}]
    momentos = [{"midia": "I3", "trecho": "John List matou a família em Westfield."},
                {"midia": "I5", "trecho": "A casa ficou vazia por semanas."},
                {"midia": "I3", "trecho": "Ele fugiu sem deixar rastros."}]
    assert cenas_lote.cenas_dos_momentos(cenas, momentos) == {1: "I3", 2: "I5", 3: "I3"}
    j = cenas_lote.montar_json(cenas, {}, {0}, "", {1: {"id": "I3", "tipo": "foto"}})
    assert j["segments"][1]["provider"] == "material" and j["segments"][1]["query"] == "I3"
    assert j["segments"][0]["provider"] == "runpod"


def test_buscar_fotos_bing_google(cliente, monkeypatch):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "toolkit"))
    import buscador_imagens_unificado as bu
    from PIL import Image
    c, pid, base = cliente
    p = ds.carregar(base, pid)
    p["fotos_roteiro"] = {"perguntas": [{"id": "P1", "alvo": "Linda Patrik", "pergunta": "Tem foto de Linda Patrik?", "busca": "Linda Patrik Unabomber"},
                                        {"id": "P2", "alvo": "Gary Wright", "pergunta": "?", "busca": "", "pulada": True}]}
    ds.salvar(base, p)
    pedidos = []

    def lote(motor, termos, limit=1, orientation="any", **kw):
        pedidos.append((motor, list(termos)))
        return {"por_termo": {bu._norm(t): [bu.ImagemBuscador(title=f"{motor} {i}", description="", source_page="https://x/p",
                                                               original_url=f"https://x/{motor}{i}.jpg", thumbnail_url="",
                                                               width=800, height=600, query=t, engine=motor)
                                            for i in range(3)] for t in termos}, "erros": {}, "erro_geral": None}
    cores = iter(range(10, 250, 20))

    def baixar(im, pasta, stem=None, timeout_s=0):
        cam = os.path.join(pasta, stem + ".jpg")
        img = Image.new("RGB", (64, 64), (next(cores), 0, 0))
        for x in range(0, 64, 8):  # padrões diferentes (a assinatura visual não acha "parecidas")
            img.paste((255, 255, 255), (x, (x * 7) % 64, x + 4, (x * 7) % 64 + 4))
        img.save(cam)
        return cam
    monkeypatch.setattr(bu, "buscar_lote", lote)
    monkeypatch.setattr(bu, "baixar_imagem", baixar)
    monkeypatch.setattr(bu, "assinatura_visual", lambda cam: None)
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: False)
    r = fr.buscar_fotos(base, pid, [{"id": "P1"}, {"id": "P2"}], ["bing", "google"], quantidade=2)
    assert pedidos == [("bing", ["Linda Patrik Unabomber"]), ("google", ["Linda Patrik Unabomber"])]
    assert len(r["novas"]) == 4
    p = ds.carregar(base, pid)
    novas = [m for m in p["midias"] if m["id"] in r["novas"]]
    assert all(m["pergunta"] == "P1" and m["a_conferir"] and m["pergunta_alvo"] == "Linda Patrik" for m in novas)
    est = c.get(f"/modelos-video/{pid}/fotos-roteiro").get_json()
    assert sorted(est["enviadas"]["P1"]) == sorted(r["novas"]) and est["midias"][r["novas"][0]]["a_conferir"]
    est = c.post(f"/modelos-video/{pid}/fotos-roteiro/conferidas", json={"ids": r["novas"]}).get_json()
    assert not any(est["midias"][i]["a_conferir"] for i in r["novas"])
    assert fr.termo_da_pergunta(p, {"alvo": "Gary Wright", "busca": ""}).startswith("Gary Wright")


def test_termos_sempre_em_ingles(monkeypatch):
    import ia_servico
    p = {"id": "x", "tema": "Unabomber", "midias": []}
    assert fr.termo_da_pergunta(p, {"alvo": "David Kaczynski, o irmão"}) == "David Kaczynski"
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: True)
    visto = {}

    def chamar(rec, system, conteudo, schema=None, **kw):
        visto["s"] = system
        return {"termos": [{"id": "P2", "busca": "David Kaczynski Unabomber brother"}, {"id": "P9", "busca": "x"}]}
    monkeypatch.setattr(ia_servico, "chamar", chamar)
    import dossies as ds
    monkeypatch.setattr(ds, "nome_do_projeto", lambda p: "Unabomber")
    assert fr.termos_em_ingles(p, [{"id": "P2", "alvo": "David Kaczynski, o irmão", "pergunta": "?"}]) == {"P2": "David Kaczynski Unabomber brother"}
    assert "EM INGLÊS" in visto["s"]
    assert "SEMPRE EM INGLÊS" in fr.prompt_perguntas({"resultado": {"roteiro_final": "Texto do roteiro."}, "midias": []})


def test_apagar_fotos_das_buscas(cliente):
    c, pid, base = cliente
    import os
    p = ds.carregar(base, pid)
    os.makedirs(ds.pasta_midias(base, pid), exist_ok=True)
    novos = []
    for k, conferir in enumerate((True, False, True)):
        nome = f"busca_{k}.jpg"
        open(os.path.join(ds.pasta_midias(base, pid), nome), "wb").write(b"x")
        m = ds.adicionar_midia(p, tipo="foto", origem="busca", arquivo=nome, descricao="x")
        m.update(pergunta="P1", a_conferir=conferir)
        novos.append(m["id"])
    manual = ds.adicionar_midia(p, tipo="foto", origem="pc", descricao="minha")
    p["elenco"] = {"pessoas": [{"nome": "X", "fotos": [{"midia": novos[0]}]}, {"nome": "Y", "fotos": [{"midia": manual["id"]}]}], "locais": []}
    p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": f"[{novos[0]}] Em 1971 tudo mudou. [{novos[1]}] John List matou a família.", "titulos": ["t"]}), p)
    ds.salvar(base, p)
    d = c.get(f"/modelos-video/{pid}/fotos-roteiro").get_json()
    assert d["de_busca"] == 3 and d["de_busca_conferir"] == 2
    d = c.post(f"/modelos-video/{pid}/fotos-roteiro/apagar-buscas", json={"so_a_conferir": True}).get_json()
    assert d["apagadas"] == 2 and d["marcas_tiradas"] == 1 and d["de_busca"] == 1
    p = ds.carregar(base, pid)
    assert p["resultado"]["roteiro"].startswith("Em 1971") and f"[{novos[1]}]" in p["resultado"]["roteiro"]
    assert [x["nome"] for x in p["elenco"]["pessoas"]] == ["Y"]
    assert not os.path.exists(os.path.join(ds.pasta_midias(base, pid), "busca_0.jpg"))
    d = c.post(f"/modelos-video/{pid}/fotos-roteiro/apagar-buscas", json={}).get_json()
    assert d["apagadas"] == 1 and d["de_busca"] == 0
    assert any(m["id"] == manual["id"] for m in ds.carregar(base, pid)["midias"])
    assert c.post(f"/modelos-video/{pid}/fotos-roteiro/apagar-buscas", json={}).status_code == 400


def test_link_colado_vira_foto_conferida(cliente, monkeypatch):
    c, pid, base = cliente
    import os
    import vendas as vd
    p = ds.carregar(base, pid)
    p["fotos_roteiro"] = {"perguntas": [{"id": "P1", "alvo": "Linda Patrik", "pergunta": "?"}]}
    ds.salvar(base, p)

    def baixar(url, pasta, nome, timeout=60):
        if "pagina" in url:
            raise vd.VendaError("Esse link não é um arquivo de foto ou vídeo.")
        os.makedirs(pasta, exist_ok=True)
        open(os.path.join(pasta, nome + ".jpg"), "wb").write(b"x")
        return os.path.join(pasta, nome + ".jpg"), "foto"
    monkeypatch.setattr(vd, "baixar_arquivo", baixar)
    monkeypatch.setattr(vd, "baixar_html", lambda url, navegador=False: ("<html>", url))
    monkeypatch.setattr(vd, "ler_og", lambda html, final: {"titulo": "Matéria", "imagem": "https://x/foto.jpg"})
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: False)
    d = c.post(f"/modelos-video/{pid}/fotos-roteiro/link", json={"url": "https://x/a.jpg", "pergunta": "P1"}).get_json()
    assert d["ok"] and not d["da_pagina"]
    d2 = c.post(f"/modelos-video/{pid}/fotos-roteiro/link", json={"url": "https://site/pagina", "pergunta": "P1"}).get_json()
    assert d2["ok"] and d2["da_pagina"]
    p = ds.carregar(base, pid)
    novas = [m for m in p["midias"] if m["id"] in (d["midia"]["id"], d2["midia"]["id"])]
    assert all(m["pergunta"] == "P1" and not m.get("a_conferir") and m["descricao"] == "Linda Patrik" for m in novas)
    assert c.post(f"/modelos-video/{pid}/fotos-roteiro/link", json={"url": "ftp://x"}).status_code == 400
