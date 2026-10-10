"""v84: Cortar do YouTube — colar um texto com links, tempos e descrições opcionais."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))

import youtube_clipper as y  # noqa: E402


def _t(r):
    return {i["url"]: [(t["inicio"], t["fim"], t["descricao"]) for t in i["trechos"]] for i in r["itens"]}


def test_formatos_de_tempo_e_descricao():
    r = y.interpretar_texto("""https://youtu.be/abc
0:15 - 0:42 chegada do herói
1:10 a 1:30 | a luta
de 2:00 até 2:20 - final
2:40 até o fim
explosão: 45s - 1m20s
[1:02:03 -> 1:02:30] epílogo
a partir de 7:30 créditos
3:00 - 2:00 errado""")
    assert _t(r)["https://youtu.be/abc"] == [
        ("00:00:15", "00:00:42", "chegada do herói"), ("00:01:10", "00:01:30", "a luta"),
        ("00:02:00", "00:02:20", "final"), ("00:02:40", "", ""), ("00:00:45", "00:01:20", "explosão"),
        ("01:02:03", "01:02:30", "epílogo"), ("00:07:30", "", "créditos")]
    assert any("vem antes do início" in a for a in r["avisos"])


def test_links_na_mesma_linha_sem_tempo_e_repetidos():
    r = y.interpretar_texto("""• https://www.youtube.com/watch?v=xyz 00:05-00:20 abertura
2. youtu.be/qqq trailer oficial
https://youtu.be/sem
https://www.youtube.com/watch?v=xyz 1:00-1:10 extra""")
    t = _t(r)
    assert t["https://www.youtube.com/watch?v=xyz"] == [("00:00:05", "00:00:20", "abertura"), ("00:01:00", "00:01:10", "extra")]
    assert t["https://youtu.be/qqq"] == [("", "", "trailer oficial")]   # sem tempo = vídeo inteiro
    assert t["https://youtu.be/sem"] == [("", "", "vídeo inteiro")]
    assert r["resumo"] == {"videos": 3, "trechos": 4}


def test_capitulos_e_titulos():
    r = y.interpretar_texto("""Entrevista com a Ana
https://youtu.be/aaa
Capítulos:
0:00 Introdução
1:23 A infância
5:40 Carreira
Melhores momentos
https://youtu.be/g2 1:00-2:00""")
    t = _t(r)
    assert t["https://youtu.be/aaa"] == [("00:00:00", "00:01:23", "Introdução"), ("00:01:23", "00:05:40", "A infância"),
                                         ("00:05:40", "", "Carreira")]
    assert t["https://youtu.be/g2"] == [("00:01:00", "00:02:00", "Melhores momentos")]


def test_tempo_sem_link_e_texto_vazio():
    r = y.interpretar_texto("0:10 - 0:20 sem link")
    assert not r["itens"] and any("nenhum link" in a for a in r["avisos"])


def test_rota(monkeypatch):
    monkeypatch.setenv("NARRATION_SITE_NAO_CARREGAR_PROJETOS", "1")
    import app
    c = app.app.test_client()
    d = c.post("/cortar-youtube/interpretar", json={"texto": "https://youtu.be/a 0:01-0:05 oi"}).get_json()
    assert d["ok"] and d["itens"][0]["trechos"][0]["descricao"] == "oi"
    assert c.post("/cortar-youtube/interpretar", json={"texto": " "}).status_code == 400
    assert "Colar texto" in c.get("/cortar-youtube").get_data(as_text=True)
