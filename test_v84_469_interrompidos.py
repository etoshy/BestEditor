import json
import os


def test_sobras_continuar_apagar(tmp_path, monkeypatch):
    import app as A
    A.app.config["TESTING"] = True
    monkeypatch.setattr(A, "TRANSCRICOES_AVULSAS_DIR", str(tmp_path))
    monkeypatch.setattr(A, "_TRANSCRICOES_AVULSAS_JOBS", {})
    iniciados = []
    monkeypatch.setattr(A, "_transcrever_iniciar", lambda jid: iniciados.append(jid))
    # 1) envio antigo (sem _job.json) com o vídeo inteiro; 2) pedido salvo que estava na fila
    os.makedirs(tmp_path / "aaaaaaaaaaaa")
    (tmp_path / "aaaaaaaaaaaa" / "enviado_007-COMO-DORMIR.mp4").write_bytes(b"x" * 5000)
    os.makedirs(tmp_path / "bbbbbbbbbbbb")
    (tmp_path / "bbbbbbbbbbbb" / "_job.json").write_text(json.dumps({"id": "bbbbbbbbbbbb", "status": "na_fila", "nome": "006.mp4",
                                                                       "params": {"arquivo_path": None}}))
    A._historico_carregar(str(tmp_path), A._TRANSCRICOES_AVULSAS_JOBS)
    A._transcricoes_sobras()
    J = A._TRANSCRICOES_AVULSAS_JOBS
    assert J["aaaaaaaaaaaa"]["status"] == "interrompido" and J["aaaaaaaaaaaa"]["nome"] == "007-COMO-DORMIR.mp4"
    assert J["bbbbbbbbbbbb"]["status"] == "interrompido"
    c = A.app.test_client()
    assert c.get("/transcrever/interrompidos").get_json()["n"] == 2
    assert "continuar todos" in c.get("/transcrever").get_data(as_text=True)
    assert c.post("/transcrever/bbbbbbbbbbbb/continuar").status_code == 400  # o arquivo não está lá
    assert c.post("/transcrever/aaaaaaaaaaaa/continuar").get_json()["ok"] and iniciados == ["aaaaaaaaaaaa"]
    r = c.post("/transcrever/interrompidos", json={"acao": "apagar"}).get_json()
    assert r["feitos"] == 1 and not os.path.exists(tmp_path / "bbbbbbbbbbbb")
    J["aaaaaaaaaaaa"]["status"] = "pronto"
    assert c.post("/transcrever/aaaaaaaaaaaa/apagar").get_json()["liberado_mb"] >= 0 and not os.path.exists(tmp_path / "aaaaaaaaaaaa")
