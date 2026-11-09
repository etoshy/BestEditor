"""v84_368: 📚 texto bruto → vários vídeos e 🖼 thumbnails (5 ideias, estilo do canal, avulsas)."""
import json

import temas_bruto as TB
import thumbs_flow as tf


def test_limpar_tira_tempos_e_texto_duplicado():
    bruto = "\n".join(f"0:{i:02d} frase número {i}." for i in range(40))
    limpo = TB.limpar(bruto + "\n" + bruto)
    assert "0:0" not in limpo
    assert limpo.count("frase número 7.") == 1
    assert TB.limpar("1\n00:00:01,000 --> 00:00:02,000\nOlá\n") == "Olá"


def test_ler_temas_valida_formato_e_minutos(monkeypatch):
    import dossies as ds
    monkeypatch.setitem(ds.MODELOS, "teste_fil", {"nome": "Teste", "formatos": {"ensaio": {"nome": "E", "minutos": 14},
                                                                               "curto": {"nome": "C", "minutos": 1}}})
    temas = TB.ler_temas({"temas": [{"titulo": "A", "formato": "xx", "minutos": 99, "forca": 4},
                                    {"titulo": "B", "formato": "curto", "minutos": 1, "forca": 9}, {"titulo": ""}]}, "teste_fil")
    assert [t["titulo"] for t in temas] == ["B", "A"]  # do mais forte pro mais fraco, sem o vazio
    assert temas[1]["formato"] == "ensaio" and temas[1]["minutos"] == 60


def test_system_das_notas_proibe_o_curso():
    s = TB.system_notas({"id": "x"}, "texto")
    assert "NADA do evento" in s and "curso" in s and "=== TEXTO BRUTO ===" in s


def test_thumbs_bloco_pede_5_diferentes():
    assert "5 thumbnails BEM diferentes" in tf.BLOCO_PROMPT


def test_prompt_flow_com_estilo_do_canal():
    it = {"prompt": "a philosopher in the agora"}
    assert "documentary thumbnail" in tf.prompt_flow(it)
    est = "YouTube thumbnail, space on the {lado} third. Photorealistic."
    assert tf.prompt_flow(it, "left", est).endswith("space on the left third. Photorealistic.")


def test_avulsa_criar_listar(tmp_path):
    pid = tf.criar_avulsa(str(tmp_path), "Título X", "sobre", "", "pt")
    assert tf.listar_avulsas(str(tmp_path))[0]["id"] == pid
    d = tf.adicionar_ideias(str(tmp_path), "avulso", pid, [{"ideia": "a", "texto": "T", "prompt": "p"},
                                                           {"ideia": "a", "texto": "T", "prompt": "p"}])
    assert len(d["itens"]) == 1 and d["titulo"] == "Título X"
    assert tf.para_json(d, "/x")["itens"][0]["prompt_flow"].startswith("p. ")
