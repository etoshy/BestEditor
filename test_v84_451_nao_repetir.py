import json
import os

import ia_servico as ia
import thumbs_flow as tf

PAP = ("O personagem vestido de papagaio, com bico, penas verdes e pés no poleiro dentro de uma gaiola, sorri orgulhoso e faz "
       "joinha, como se repetir frase pronta fosse inteligência.")


def test_repete_outro_video():
    outros = [{"modo": "albert", "texto": "PAPAGAIO", "ideia": PAP}]
    assert tf.repete_outro_video({"modo": "albert", "texto": "PAPAGAIOS", "ideia": "x"}, outros)
    assert tf.repete_outro_video({"modo": "albert", "texto": "ECO", "ideia": "O personagem fantasiado de papagaio com penas "
                                  "verdes no poleiro da gaiola repetindo frase pronta com joinha"}, outros)
    assert not tf.repete_outro_video({"modo": "albert", "texto": "GADO", "ideia": "O personagem de quatro no meio de um "
                                      "rebanho de vacas, com sino no pescoço, mastigando capim"}, outros)


def test_outras_thumbs_e_prompt(tmp_path, monkeypatch):
    for pid, palavra in (("aaa111", "PAPAGAIO"), ("bbb222", "GADO")):
        os.makedirs(tmp_path / "thumbs" / f"dossie_{pid}")
        (tmp_path / "thumbs" / f"dossie_{pid}" / "thumbs.json").write_text(json.dumps(
            {"itens": [{"n": 1, "modo": "albert", "texto": palavra, "ideia": f"cena com {palavra.lower()}"}]}))
    outros = tf.outras_thumbs(str(tmp_path), "dossie", "bbb222")
    assert [o["texto"] for o in outros] == ["PAPAGAIO"]  # o próprio vídeo não conta
    monkeypatch.setattr(ia, "motivo_desligado", lambda r=None, c=None: None)
    vistos = []

    def chamar(rec, system, conteudo, **kw):
        vistos.append(system)
        k = len(vistos)
        palavra = "PAPAGAIO" if k == 1 else f"NOVA{k}"
        return {"thumbnails": [{"ideia": f"ideia diferente numero {k}", "texto": palavra, "prompt": "s", "modo": "albert"}]}
    monkeypatch.setattr(ia, "chamar", chamar)
    out = tf.pedir_ideias("T", "roteiro", [], 0, "pt", albert=1, outros=outros)
    assert [t["texto"] for t in out] == ["NOVA2"]  # o PAPAGAIO repetido caiu e ela pediu outra
    assert "PAPAGAIO" in vistos[0] and "OUTROS VÍDEOS" in vistos[0]
