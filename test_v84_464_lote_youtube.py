import json
import os
import zipfile

import transcrever_lote as TL


def test_lote_com_video_falho_e_zip(tmp_path):
    lote = TL.criar(str(tmp_path), [
        {"url": "https://www.youtube.com/watch?v=AAAAAAAAAAA", "titulo": 'Aula: "Camus"', "txt": "texto", "txt_ts": "[0:00] texto"},
        {"url": "https://www.youtube.com/watch?v=BBBBBBBBBBB", "titulo": "Outro", "txt": ""},
        {"url": "https://evil.com/x", "titulo": "nao"}], modo="audio")
    assert len(lote["itens"]) == 2

    def baixar(it, modo, q, pasta, log):
        if "BBB" in it["url"]:
            raise RuntimeError("bloqueado")
        os.makedirs(pasta, exist_ok=True)
        cam = os.path.join(pasta, "AAAAAAAAAAA.opus")
        open(cam, "wb").write(b"opus")
        return cam
    r = TL.rodar(str(tmp_path), lote["id"], baixar=baixar)
    assert r["estado"] == "pronto" and r["itens"][0]["estado"] == "pronto" and r["itens"][1]["erro"] == "bloqueado"
    z = zipfile.ZipFile(os.path.join(str(tmp_path), "_lotes", lote["id"], r["zip"]))
    nomes = set(z.namelist())
    assert {"Aula Camus.opus", "Aula Camus.txt", "Aula Camus (com timestamps).txt", "_resumo.txt"} <= nomes
    assert "bloqueado" in z.read("_resumo.txt").decode()


def test_rotas(tmp_path, monkeypatch):
    import app as A
    A.app.config["TESTING"] = True
    monkeypatch.setattr(TL, "rodar", lambda base, lid, baixar=None: None)
    c = A.app.test_client()
    r = c.post("/transcrever/lote", data=json.dumps({"videos": [{"url": "https://www.youtube.com/watch?v=CCCCCCCCCCC"}], "modo": "video"}),
               content_type="text/plain")
    d = r.get_json()
    assert r.status_code == 200 and d["ok"] and r.headers["Access-Control-Allow-Origin"] == "*"
    assert c.get(f"/transcrever/lote/{d['id']}").get_json()["total"] == 1
    assert any(x["id"] == d["id"] for x in c.get("/transcrever/lotes").get_json()["lotes"])
    s = c.get("/navegador-imagens/youtube-transcricao.user.js").get_data(as_text=True)
    assert "@version      1.4.0" in s and "__SITE__" not in s and "/transcrever/lote" in s
    TL.LOTES.pop(d["id"], None)
