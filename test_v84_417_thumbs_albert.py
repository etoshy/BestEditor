"""v84_417 — além das 5 thumbs/títulos, 2 no estilo palavra gigante + ironia (o estilo de arte do canal não muda)."""
import thumbs_flow as tf


def test_prompt_da_palavra_gigante_mantem_o_estilo_do_canal():
    est = ("@@Rusty art@@YouTube thumbnail, 16:9, one strong focal subject, strong emotion, dramatic light and clear contrast, "
           "large empty negative space on the {lado} third for a big title added later. painterly rusty style. "
           "No text, no letters, no words, no watermark, no logo.")
    it = tf.normalizar({"ideia": "sorrindo com uma corda", "texto": "Morte!", "prompt": "the channel host smiling, holding a noose",
                        "modo": "albert"})
    assert it["modo"] == "albert" and it["texto"] == "MORTE"
    p = tf.prompt_flow(it, estilo=est)
    assert p.startswith("Rusty art:") and '"MORTE"' in p and "painterly rusty style" in p
    assert "no letters" not in p.lower() and "negative space" not in p
    normal = tf.prompt_flow({"prompt": "x", "texto": "A B"}, estilo=est)
    assert "No text" in normal and "MORTE" not in normal


def test_pedir_ideias_vem_5_mais_2(monkeypatch):
    import ia_servico as ia
    monkeypatch.setattr(ia, "motivo_desligado", lambda r, c=None: None)
    visto = {}

    def falso(rec, system, conteudo, **k):
        visto["s"] = system
        return {"thumbnails": [{"ideia": f"n{i}", "texto": "X", "prompt": "p"} for i in range(5)]
                + [{"ideia": f"a{i}", "texto": "MEDO", "prompt": "p", "modo": "albert"} for i in range(2)]}
    monkeypatch.setattr(ia, "chamar", falso)
    out = tf.pedir_ideias("Medo", "roteiro", [], 5, albert=2)
    assert len(out) == 7 and [t.get("modo") for t in out].count("albert") == 2
    assert "PALAVRA" in visto["s"] and "IRONIA" in visto["s"]


def test_compor_sem_texto_por_cima_no_modo_albert(tmp_path):
    from PIL import Image
    img = tmp_path / "a.png"
    Image.new("RGB", (1600, 900), (200, 30, 30)).save(img)
    final = tf.compor(str(img), "", str(tmp_path / "f.jpg"))
    assert Image.open(final).size == (1280, 720)


def test_titulos_e_bloco(monkeypatch):
    import metodo_roteiro as mr
    monkeypatch.setattr(tf, "ativo_albert", lambda cfg=None: 2)
    t = mr.bloco_titulos(5)
    assert "mais 2 no ESTILO TEMA-PONTO-PERGUNTA" in t and "O que há na cabeça deles?" in t
    assert "\"modo\": \"albert\"" in tf.bloco_prompt()
    monkeypatch.setattr(tf, "ativo_albert", lambda cfg=None: 0)
    assert "TEMA-PONTO" not in mr.bloco_titulos(5) and tf.bloco_prompt().startswith(tf.BLOCO_PROMPT) and "albert" not in tf.bloco_prompt()


def test_so_palavra_gigante(monkeypatch):
    import ia_servico as ia
    monkeypatch.setattr(ia, "motivo_desligado", lambda r, c=None: None)
    visto = {}
    monkeypatch.setattr(ia, "chamar", lambda rec, system, conteudo, **k: visto.update(s=system) or {"thumbnails": [
        {"ideia": "boca costurada sorrindo", "texto": "MENTIROSO", "prompt": "p"},
        {"ideia": "marionete", "texto": "Marionete", "prompt": "p"}, {"ideia": "x", "texto": "X", "prompt": "p"}]})
    out = tf.pedir_ideias("Linguagem", "roteiro", [], 0, albert=2)
    assert len(out) == 2 and all(t["modo"] == "albert" for t in out) and out[1]["texto"] == "MARIONETE"
    assert "NERVO" in visto["s"] and "RUIM" in visto["s"] and "NÃO repita" in visto["s"] and "MENTIROSO" not in visto["s"]


def test_rota_so_albert(monkeypatch):
    import app as A
    import dossies as ds
    monkeypatch.setattr(tf, "pedir_ideias", lambda *a, **k: [{"ideia": "i", "texto": "MEDO", "prompt": "p", "modo": "albert"}]
                        if a[3] == 0 and k.get("albert") == 3 else [])
    p = ds.criar(A.BASE_DIR, tema="Medo")
    p["resultado"] = {"roteiro": "um roteiro sobre o medo " * 20, "titulos": ["Medo"]}
    ds.salvar(A.BASE_DIR, p)
    try:
        r = A.app.test_client().post(f"/thumbs/dossie/{p['id']}/ia", json={"n": 0, "albert": 3})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["novas"] == 1 and r.get_json()["itens"][-1]["modo"] == "albert"
    finally:
        ds.excluir(A.BASE_DIR, p["id"])


def test_tira_segundo_as_notas():
    import metodo_roteiro as mr
    import roteiro_partes as rp
    t = ("Segundo a leitura das notas, essas fontes repetem ideias. Parece pouco, mas, como propõem as notas, treinar-se é "
         "o primeiro passo. Segundo a crítica apresentada nas notas, perder a música é perder a sinceridade.")
    out = mr.tirar_meta_fonte(t)
    assert "notas" not in out and out.startswith("Essas fontes") and "mas treinar-se" in out and "Perder a música" in out
    assert "notas" not in rp.ler_parte("Segundo as notas, o medo é antigo.", {"titulo": "x"})
    assert mr.tirar_meta_fonte("Ele tirou boas notas na escola.") == "Ele tirou boas notas na escola."


def test_titulos_casados_com_a_thumb(monkeypatch):
    import ia_servico as ia
    monkeypatch.setattr(ia, "motivo_desligado", lambda r, c=None: None)
    visto = {}
    monkeypatch.setattr(ia, "chamar", lambda rec, system, conteudo, **k: visto.update(s=system, c=conteudo) or {"thumbs": [
        {"n": 7, "titulos": ["Contradição. Por que você foge do que quer?", "Contradição. Quem desiste de si mesmo?"]},
        {"n": 99, "titulos": ["não pedido"]}]})
    itens = [{"n": 7, "texto": "CONTRADIÇÃO", "modo": "albert", "ideia": "sorrindo segurando a própria lápide"}]
    out = tf.pedir_titulos("O Maior Erro de Quem Desiste", "roteiro", itens,
                           originais=["Por que a História Universal Não Existe?"])
    assert out == {7: ["Contradição. Por que você foge do que quer?", "Contradição. Quem desiste de si mesmo?"]}
    assert "Assunto. Pergunta" in visto["s"] and "CONTRADIÇÃO" in visto["c"] and "Não mude a palavra" in visto["s"]
    assert "Títulos ORIGINAIS" in visto["c"] and "História Universal Não Existe" in visto["c"]
    assert "NUNCA explique a metáfora" in visto["s"]
    assert tf.normalizar({"ideia": "x", "texto": "MEDO", "prompt": "p", "titulos": ["Medo. Como desligar isso?", "b"]})["titulos"][0] == "Medo. Como desligar isso?"
    assert "titulos" in tf.bloco_prompt(2) and "titulos" in tf.bloco_prompt(0)


def test_rota_titulos(monkeypatch):
    import app as A
    import dossies as ds
    p = ds.criar(A.BASE_DIR, tema="Contradição")
    p["resultado"] = {"roteiro": "um roteiro " * 50, "titulos": ["O Maior Erro"],
                      "thumbnails": [{"ideia": "i", "texto": "CONTRADIÇÃO", "prompt": "p", "modo": "albert"}]}
    ds.salvar(A.BASE_DIR, p)
    monkeypatch.setattr(tf, "pedir_titulos", lambda titulo, sobre, alvo, idioma="pt", originais=None: {int(alvo[0]["n"]): ["Contradição. Por quê?", "Outro"]})
    try:
        r = A.app.test_client().post(f"/thumbs/dossie/{p['id']}/titulos", json={})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["itens"][0]["titulos"] == ["Contradição. Por quê?", "Outro"]
    finally:
        ds.excluir(A.BASE_DIR, p["id"])
