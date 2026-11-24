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
    assert "@version      1.5.0" in s and "__SITE__" not in s and "/transcrever/lote" in s
    TL.LOTES.pop(d["id"], None)


def test_aba_baixar_youtube(tmp_path, monkeypatch):
    import app as A
    import navegador_imagens as ni
    A.app.config["TESTING"] = True
    monkeypatch.setattr(TL, "rodar", lambda base, lid, baixar=None: None)
    abertas = []
    monkeypatch.setattr(ni, "abrir", lambda base, urls, cfg=None, **k: abertas.extend(urls) or {"ok": True})
    c = A.app.test_client()
    assert "byFormato" in c.get("/baixar-youtube").get_data(as_text=True)
    d = c.post("/baixar-youtube/novo", json={"links": "https://youtu.be/DDDDDDDDDDD\nhttps://www.youtube.com/watch?v=EEEEEEEEEEE",
                                             "formato": "mp3", "transcricao": True}).get_json()
    lid = d["lote"]["id"]
    assert d["lote"]["modo"] == "mp3" and d["lote"]["total"] == 2
    g = c.post(f"/baixar-youtube/{lid}/guias", json={"quantas": 5}).get_json()
    assert g["abertas"] == 2 and "#bestyt=" in abertas[0] and abertas[0].startswith("https://www.youtube.com/watch?v=DDDDDDDDDDD")
    r = c.post(f"/baixar-youtube/{lid}/transcricao", data=json.dumps({"idx": 1, "titulo": "Vídeo Dois", "txt": "oi", "txt_ts": "[0:00] oi"}),
               content_type="text/plain")
    assert r.get_json()["nome"] == "Vídeo Dois" and r.headers["Access-Control-Allow-Origin"] == "*"
    z = c.get(f"/transcrever/lote/{lid}/zip")
    import io
    nomes = zipfile.ZipFile(io.BytesIO(z.data)).namelist()
    assert "Vídeo Dois.txt" in nomes and "Vídeo Dois (com timestamps).txt" in nomes and "_resumo.txt" in nomes
    TL.LOTES.pop(lid, None)


def test_mp3_320(tmp_path):
    import subprocess
    src = str(tmp_path / "a.opus")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=1", "-c:a", "libopus", src], check=True)
    out = TL._para_mp3(src, lambda m: None)
    br = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,bit_rate", "-of", "csv=p=0", out],
                        capture_output=True, text=True).stdout
    assert out.endswith(".mp3") and br.startswith("mp3")
