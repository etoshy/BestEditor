import metodo_roteiro as mr


def test_aspas_duplas():
    assert mr.aspas_duplas("O 'Mito' da Caverna") == 'O "Mito" da Caverna'
    assert mr.aspas_duplas("Copo d'água e rock'n'roll") == "Copo d'água e rock'n'roll"
    assert mr.aspas_duplas("‘Penso, logo existo’ — mentira?") == '"Penso, logo existo" — mentira?'


def test_descricao_sem_fonte_do_material():
    import dossies
    p = {"fontes": [{"id": "f1", "titulo": "Aula 3", "url": "https://youtube.com/watch?v=aula", "site": "YouTube"}],
         "resultado": {"descricao": "Um vídeo sobre o 'mito'.", "fontes_usadas": ["f1"],
                       "fontes_web": {"itens": [{"referencia": "Platão, A República", "url": "https://plato.stanford.edu/x"}]}}}
    d = dossies.descricao_completa(p)
    assert "youtube.com/watch?v=aula" not in d and "Aula 3" not in d
    assert '"mito"' in d and "plato.stanford.edu" in d
    del p["resultado"]["fontes_web"]
    assert "youtube.com" not in dossies.descricao_completa(p)  # o vídeo de origem (a aula) nunca entra


def test_srt_do_video(monkeypatch):
    import app as A
    A.app.config["TESTING"] = True
    A._JOBS["jtest461"] = {"job_id": "jtest461", "word_timestamps": [
        {"word": "Olá", "start": 0.0, "end": 0.5}, {"word": "mundo", "start": 0.5, "end": 1.0},
        {"word": "depois", "start": 5.0, "end": 5.5}], "cortes_video": [{"insertion_point": 2.0, "duration": 10.0}]}
    r = A.app.test_client().get("/job/jtest461/legenda.srt")
    assert r.status_code == 200 and "Olá mundo" in r.get_data(as_text=True)
    assert "00:00:15" in r.get_data(as_text=True)  # "depois" foi empurrado 10 s pela chamada
    rot, nar = A._links_do_job({"dossie_id": "abc1234567", "original_filename": "voz 3ead6ef6.zip"})
    assert rot == "/modelos-video/abc1234567" and nar == "/gerar-voz?voz=3ead6ef6#historico"
    A._JOBS.pop("jtest461", None)
