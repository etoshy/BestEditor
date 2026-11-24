import os


def test_nome_e_feito(tmp_path, monkeypatch):
    import app as A
    A.app.config["TESTING"] = True
    monkeypatch.setattr(A, "TRANSCRICOES_AVULSAS_DIR", str(tmp_path))
    os.makedirs(tmp_path / "abc123456789")
    (tmp_path / "abc123456789" / "transcricao.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\noi\n", encoding="utf-8")
    A._TRANSCRICOES_AVULSAS_JOBS["abc123456789"] = {"id": "abc123456789", "status": "pronto", "nome": "Aula 3 - Camus.mp4", "modo": "transcrever"}
    c = A.app.test_client()
    r = c.get("/transcrever/abc123456789/arquivo/transcricao.srt")
    assert r.status_code == 200 and "Aula 3 - Camus.srt" in r.headers["Content-Disposition"]
    assert A._nome_base_transcricao({"url": "https://www.youtube.com/watch?v=XYZ123"}) == "XYZ123"
    assert A._nome_base_transcricao({"url": "https://x.com", "resultado": {"titulo": 'Vídeo: "bom"?'}}) == "Vídeo bom"
    assert c.post("/transcrever/abc123456789/feito", json={"feito": True}).get_json()["feito"] is True
    assert A._TRANSCRICOES_AVULSAS_JOBS["abc123456789"]["feito"] is True
    assert os.path.isfile(tmp_path / "abc123456789" / "_job.json")
    assert "hist-feito" in c.get("/transcrever").get_data(as_text=True)
    A._TRANSCRICOES_AVULSAS_JOBS.pop("abc123456789", None)


def test_script_youtube_servido():
    import app as A
    c = A.app.test_client()
    r = c.get("/navegador-imagens/youtube-transcricao.user.js")
    assert r.status_code == 200 and "@version      1.5.0" in r.get_data(as_text=True) and "makeZip" in r.get_data(as_text=True)
    assert "youtube-transcricao.user.js" in c.get("/navegador-imagens/instalar").get_data(as_text=True)
    assert "ytAbrir" in c.get("/transcrever").get_data(as_text=True)
