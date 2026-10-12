"""v84_68 — 📑 capítulos da descrição do YouTube no tempo do VÍDEO FINAL (e o roteiro colado à mão liga sozinho)."""
import json

import pytest

import capitulos_video as cv
import dossies as ds

PAL = "caso noite casa polícia carta fórum grupo vizinho juiz prova".split()


def _roteiro():
    partes = []
    for k in range(4):
        corpo = " ".join(PAL[(k * 3 + j) % len(PAL)] + str(j % 7) for j in range(120))
        partes.append(f"Parte {k + 1} começa quando tudo mudou em {1990 + k}. {corpo}.")
    return "\n\n".join(partes)


def _dossie(base):
    p = ds.criar(base, "Caso teste")
    rot = _roteiro()
    caps = [{"titulo": f"Capítulo {k + 1}", "comeca_em": f"Parte {k + 1} começa quando tudo mudou"} for k in range(4)]
    p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": rot, "capitulos": caps, "descricao": "Um caso."}), p)
    ds.salvar(base, p)
    return p


def _palavras(texto, ritmo=0.4):
    out, t = [], 0.0
    for w in texto.split():
        out.append({"word": w, "start": round(t, 2), "end": round(t + ritmo * 0.8, 2)})
        t += ritmo
    return out, t


def test_tempo_no_video():
    cortes = [{"insertion_point": 10.0, "duration": 30.0},                       # pausa: tudo depois anda 30 s
              {"insertion_point": 50.0, "remove_ate": 55.0, "duration": 20.0}]  # troca 5 s de fala por 20 s de clipe
    assert cv.tempo_no_video(5.0, cortes) == 5.0
    assert cv.tempo_no_video(10.0, cortes) == 40.0
    assert cv.tempo_no_video(52.0, cortes) == 80.0  # caiu dentro do trecho trocado: começa junto com o clipe
    assert cv.tempo_no_video(60.0, cortes) == 60.0 + 30.0 + 15.0


def test_calcular_com_a_narracao_do_video_e_os_cortes(tmp_path):
    p = _dossie(str(tmp_path))
    pal, dur = _palavras(ds.roteiro_para_voz(p))
    sem = cv.calcular(p["resultado"], pal, dur)
    assert sem[0]["segundos"] == 0 and all(b["segundos"] > a["segundos"] for a, b in zip(sem, sem[1:]))
    com = cv.calcular(p["resultado"], pal, dur, [{"insertion_point": sem[1]["segundos"] + 5, "duration": 45.0}])
    assert com[1]["segundos"] == sem[1]["segundos"] and com[2]["segundos"] == pytest.approx(sem[2]["segundos"] + 45, abs=0.2)


def test_descricao_usa_o_video_final_e_audio_novo_volta(tmp_path):
    base = str(tmp_path)
    p = _dossie(base)
    pal, dur = _palavras(ds.roteiro_para_voz(p))
    job = {"job_id": "j1", "dossie_id": p["id"], "total_duration": dur}
    caps, desc = cv.para_job(job, base, pal, [{"insertion_point": 1.0, "duration": 60.0}], dur + 60)
    assert desc.startswith("Um caso.") and "0:00 Capítulo 1" in desc
    assert f"{cv.fmt(caps[1]['segundos'], False)} Capítulo 2" in desc and caps[1]["segundos"] > 60
    assert ds.descricao_completa(ds.carregar(base, p["id"])) == desc
    ds.aplicar_tempos_do_audio(base, p["id"], pal, dur)  # gerou a voz de novo: o vídeo antigo não vale mais
    assert "capitulos_video" not in ds.carregar(base, p["id"])["resultado"]


def test_roteiro_colado_a_mao_e_reconhecido(tmp_path):
    base = str(tmp_path)
    p = _dossie(base)
    texto = ds.roteiro_para_voz(p).replace("Parte 3", "Parte três")  # pequenas mudanças não atrapalham
    assert ds.achar_pelo_texto(base, texto) == p["id"]
    assert ds.achar_pelo_texto(base, "um texto qualquer " * 40) is None
    assert ds.achar_pelo_texto(base, "curto demais") is None


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_montagem_grava_a_descricao_e_a_rota_devolve(A, tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setattr(A, "BASE_DIR", base)
    p = _dossie(base)
    pal, dur = _palavras(ds.roteiro_para_voz(p))
    job = {"job_id": "capv", "status": "concluido", "dossie_id": p["id"], "total_duration": dur, "word_timestamps": pal}
    monkeypatch.setattr(A, "_probe_media_duration", lambda c: 30.0 if c == "clipe.mp4" else dur + 30)
    A._capitulos_do_video_final("capv", job, "final.mp4", [{"resolved_path": "clipe.mp4", "insertion_point": 2.0}])
    assert job["capitulos_video"][1]["segundos"] > 30 and "Capítulo 4" in job["descricao_youtube"]
    A._JOBS["capv"] = job
    d = A.app.test_client().get("/job/capv/status").get_json()
    assert d["descricao_youtube"] == job["descricao_youtube"]
    html = A.app.test_client().get("/job/capv/status-page").get_data(as_text=True)
    assert 'id="capitulos-box"' in html
    sem = {"job_id": "x", "status": "concluido"}
    A._capitulos_do_video_final("x", sem, "final.mp4", [])
    assert "descricao_youtube" not in sem


def test_gerar_voz_com_roteiro_colado_liga_o_projeto(A, tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setattr(A, "BASE_DIR", base)
    p = _dossie(base)
    monkeypatch.setattr(A._FILA_VOZ, "iniciar", lambda *a, **k: 1)
    d = A.app.test_client().post("/gerar-voz/gerar", data={"texto": ds.roteiro_para_voz(p), "engine": "piper"}).get_json()
    st = A._GERAR_VOZ_STATUS[d["job_id"]]
    assert st["dossie_id"] == p["id"] and "roteiro do modelo de vídeo" in st["log"]
    d2 = A.app.test_client().post("/gerar-voz/gerar", data={"texto": "outro texto qualquer " * 30, "engine": "piper"}).get_json()
    assert not A._GERAR_VOZ_STATUS[d2["job_id"]].get("dossie_id")
