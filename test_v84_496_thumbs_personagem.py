"""v84_496 — 🧑 thumbs estilo personagem: foto de referência (rosto + roupa) salva como padrão do canal."""
import io
import os

import pytest

import thumbs_flow as tf
import thumbs_personagem as tp

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 2000


def test_referencia_preset_e_troca(tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setattr(tp, "chave_canal", lambda b, o, p: "raciocinio_maldito")
    assert tp.referencia(base, "avulso", "aaaaaaaaaa")["arquivo"] == ""
    r = tp.salvar_referencia(base, "avulso", "aaaaaaaaaa", PNG, "eu.png", como_padrao=True)
    assert r["de"] == "projeto" and os.path.isfile(r["arquivo"])
    outro = tp.referencia(base, "avulso", "bbbbbbbbbb")  # outro projeto do mesmo canal já usa a padrão
    assert outro["de"] == "canal" and outro["arquivo"] == r["arquivo"]
    r2 = tp.salvar_referencia(base, "avulso", "bbbbbbbbbb", PNG + b"1", "outra.jpg", como_padrao=False)
    assert r2["de"] == "projeto" and r2["arquivo"] != r["arquivo"]
    assert tp.referencia(base, "avulso", "aaaaaaaaaa")["arquivo"] == r["arquivo"]  # a padrão não mudou
    assert tp.usar_padrao(base, "avulso", "bbbbbbbbbb")["de"] == "canal"
    with pytest.raises(tf.ThumbErro):
        tp.salvar_referencia(base, "avulso", "aaaaaaaaaa", PNG, "x.gif")


def test_normalizar_e_prompt():
    it = tf.normalizar({"ideia": "ele segura um celular gigante", "texto": "viral script", "prompt": "holding a giant phone",
                        "modo": "personagem"})
    assert it["modo"] == "personagem" and it["texto"] == "VIRAL SCRIPT"
    pf = tf.prompt_flow(it)
    assert "COMPLETE outfit" in pf and '"VIRAL SCRIPT"' in pf and "PERSPECTIVE" in pf
    assert "COMPLETE outfit" not in tf.prompt_flow(dict(it, _tem_ref=False))


def test_gerar_usa_a_referencia(tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setattr(tp, "chave_canal", lambda b, o, p: "padrao")
    pid = "cccccccccc"
    tf.salvar(base, "avulso", pid, {"titulo": "t", "itens": [dict(tf.normalizar({"ideia": "x", "prompt": "y", "texto": "OI",
                                                                                   "modo": "personagem"}), n=1, imagem="")]})
    ref = tp.salvar_referencia(base, "avulso", pid, PNG, "eu.png")["arquivo"]
    from PIL import Image
    img = tmp_path / "out.png"
    Image.new("RGB", (64, 36), "red").save(img)
    chamadas = []

    class Foto:
        local_path = str(img)

    class Cli:
        def gerar_imagem_com_referencia(self, pf, r, forcar=False):
            chamadas.append(r)
            return [Foto()]

        def gerar_imagem_prompt(self, pf, forcar=False):
            raise AssertionError("devia ir com referência")
    tf.gerar(base, "avulso", pid, None, cliente=Cli())
    assert chamadas == [ref]
    assert tf.carregar(base, "avulso", pid)["itens"][0]["status"] == "pronto"


def test_flow_trabalho_com_referencia():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "toolkit"))
    from googleflow.googleflow_client import trabalho_direto
    t = trabalho_direto("imagem", "p", {"orientation": "16:9"}, {}, "/x/ref.png")
    assert t["referencia"]["arquivo"] == "/x/ref.png"
    assert "referencia" not in trabalho_direto("imagem", "p", {"orientation": "16:9"})
