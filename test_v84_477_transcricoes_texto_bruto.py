"""v84_477 — Texto bruto escolhe as transcrições do site (1 ou várias; juntas ou separadas)."""
import json
import os

import transcricoes_fonte as TF


def _montar(tmp_path):
    raiz = tmp_path / "transc"
    for jid, titulo in (("aaa111", "Aula 1"), ("bbb222", "Aula 2")):
        d = raiz / jid
        d.mkdir(parents=True)
        (d / "transcricao.txt").write_text(("fala " * 200) + titulo, encoding="utf-8")
        (d / "_job.json").write_text(json.dumps({"id": jid, "resultado": {"titulo": titulo}, "criado_em": 1}), encoding="utf-8")
    arq = raiz / "_lotes" / "lote1" / "arquivos"
    arq.mkdir(parents=True)
    (arq / "Video X.txt").write_text("video " * 400, encoding="utf-8")
    (arq / "Video X (com timestamps).txt").write_text("x", encoding="utf-8")
    return str(raiz)


def test_listar_e_ler(tmp_path):
    raiz = _montar(tmp_path)
    L = TF.listar(raiz)
    chaves = {x["chave"] for x in L}
    assert chaves == {"a:aaa111", "a:bbb222", "l:lote1:Video X"}
    out = TF.ler(raiz, ["a:bbb222", "l:lote1:Video X", "a:../x", "l:lote1:../../a"])
    assert [n for _c, n in out] == ["Aula 2.txt", "Video X.txt"]
    assert TF.caminho(raiz, "a:..") is None


def test_rotas(tmp_path, monkeypatch):
    from flask import Flask
    import ia_servico as ia
    import temas_bruto_rotas
    raiz = _montar(tmp_path)
    feitas = []
    monkeypatch.setattr(ia, "motivo_desligado", lambda r: "desligada")
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))
    temas_bruto_rotas.registrar(app, str(tmp_path), raiz, {}, feitas.append)
    c = app.test_client()
    d = c.get("/temas-bruto/transcricoes").get_json()
    assert len(d["transcricoes"]) == 3
    r = c.post("/temas-bruto/novo", data={"modelo": "raciocinio_maldito", "transcricao": ["a:aaa111", "a:bbb222"],
                                          "separadas": "0"})
    assert r.status_code == 302 and "/temas-bruto/" in r.headers["Location"]
    import temas_bruto as TB
    a = TB.carregar(str(tmp_path), r.headers["Location"].rsplit("/", 1)[-1])
    assert a["textos"] == 2 and a["de_transcricoes"] == ["a:aaa111", "a:bbb222"]
    assert feitas == ["aaa111", "bbb222"]
    r = c.post("/temas-bruto/novo", data={"modelo": "raciocinio_maldito", "transcricao": ["a:aaa111", "l:lote1:Video X"],
                                          "separadas": "1"})
    assert "ok=" in r.headers["Location"]
    assert len(TB.listar(str(tmp_path))) == 3
    d = c.get("/temas-bruto/transcricoes").get_json()
    assert next(t for t in d["transcricoes"] if t["chave"] == "a:aaa111")["usada_em"]
