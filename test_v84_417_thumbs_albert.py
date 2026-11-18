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
    assert "TEMA-PONTO" not in mr.bloco_titulos(5) and tf.bloco_prompt() == tf.BLOCO_PROMPT
