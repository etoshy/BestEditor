"""Aba ⏱ Clipes curtos (completar com 2º/3º resultado, trocar por um maior, repetir)
+ montagem com os clipes escolhidos + Gerar voz: voltar a acompanhar."""
import os
import subprocess
import time

import pytest


@pytest.fixture
def A(monkeypatch):
    import app as _app
    _app.app.config["TESTING"] = True
    cands = [{"id": str(k), "url": f"https://www.pexels.com/video/c-{k}00/", "thumbnail": f"t{k}", "label": f"c{k}",
              "video_preview_url": f"https://cdn/c{k}.mp4", "duracao": d} for k, d in enumerate([2.0, 3.0, 1.5, 9.0], start=1)]
    monkeypatch.setattr(_app, "search_candidates", lambda *a, **k: [dict(c) for c in cands])
    return _app


def _job(A, jid):
    os.makedirs(A._job_dir(jid), exist_ok=True)
    segs = [{"start": 0.0, "end": 8.0, "provider": "pexels", "query": "cat", "media_type": "video", "override_source": None},
            {"start": 8.0, "end": 12.0, "provider": "pexels", "query": "dog", "media_type": "video", "override_source": None}]
    prevs = [{"index": 0, "ok": True, "result_url": "https://www.pexels.com/video/atual-1/", "provider": "pexels", "query": "cat",
              "video_preview_url": "https://cdn/atual.mp4", "thumbnail_url": "x"},
             {"index": 1, "ok": True, "result_url": "https://www.pexels.com/video/c-100/", "provider": "pexels", "query": "dog"}]
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 12.0,
                    "pending_segments": segs, "segment_previews": prevs, "overlays": [], "cutaway_suggestions": [], "media_library": []}
    return A._JOBS[jid]


def test_completar_vira_trechos_independentes(A):
    job = _job(A, "cc1")
    r = A.app.test_client().post("/job/cc1/clipes-curtos/0", json={"acao": "completar", "dur_atual": 3.0})
    d = r.get_json()
    assert r.status_code == 200 and d["recarregar"], d
    segs = job["pending_segments"]
    # trecho 1 (0–8s, clipe de 3s) -> 0–3 (clipe atual) + 3–6 (c-200, 3s) + 6–8 (c-300…): cada um é um trecho
    assert segs[0]["end"] == 3.0 and segs[0]["override_source"]["value"] == "https://www.pexels.com/video/atual-1/"
    assert segs[1]["start"] == 3.0 and segs[1]["override_source"]["value"] == "https://www.pexels.com/video/c-200/"
    assert segs[-2]["end"] == 8.0 and segs[-1]["query"] == "dog"  # o trecho seguinte continua igual
    assert len(job["segment_previews"]) == len(segs) and job["segment_previews"][1]["result_url"].endswith("c-200/")
    assert all("clipes_extra" not in sg for sg in segs)


def test_completar_no_mesmo_trecho(A):
    job = _job(A, "cc1b")
    d = A.app.test_client().post("/job/cc1b/clipes-curtos/0", json={"acao": "completar", "dur_atual": 3.0, "separados": False}).get_json()
    assert d["ok"] and len(job["pending_segments"]) == 2 and job["pending_segments"][0]["clipes_extra"]


def test_trocar_por_um_maior(A):
    job = _job(A, "cc2")
    d = A.app.test_client().post("/job/cc2/clipes-curtos/0", json={"acao": "maior"}).get_json()
    assert d["ok"] and job["pending_segments"][0]["override_source"]["value"] == "https://www.pexels.com/video/c-400/"
    assert d["preview"]["duracao"] == 9.0


def test_maior_sem_resultado_avisa(A):
    job = _job(A, "cc3")
    job["pending_segments"][0]["end"] = 30.0
    r = A.app.test_client().post("/job/cc3/clipes-curtos/0", json={"acao": "maior"})
    assert r.status_code == 404 and "Completar" in r.get_json()["erro"]


def test_repetir_e_desfazer(A):
    job = _job(A, "cc4")
    c = A.app.test_client()
    assert c.post("/job/cc4/clipes-curtos/0", json={"acao": "loop"}).get_json()["ok"]
    assert job["pending_segments"][0]["curto"] == "loop" and job["pending_segments"][0]["override_source"]
    assert c.post("/job/cc4/clipes-curtos/0", json={"acao": "padrao"}).get_json()["ok"]
    assert "curto" not in job["pending_segments"][0]


def test_form_do_estudio_guarda_os_campos(A):
    job = _job(A, "cc5")
    c = A.app.test_client()
    r = c.post("/job/cc5/confirm-segments", data={
        "acao": "salvar", "seg_0_source_mode": "post_url", "seg_0_post_url": "https://www.pexels.com/video/atual-1/", "seg_0_post_provider": "pexels",
        "seg_0_clipes_extra": '[{"source":"provider_url","provider":"pexels","value":"https://www.pexels.com/video/c-200/","duracao":3}]',
        "seg_1_curto": "loop"}, headers={"X-Requested-With": "fetch"})
    assert r.status_code == 200
    assert job["pending_segments"][0]["clipes_extra"][0]["value"].endswith("c-200/")
    assert job["pending_segments"][1]["curto"] == "loop"


def _clipe(path, cor, dur):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color={cor}:s=320x180:d={dur}:r=25", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", path], check=True)
    return path


def test_montagem_usa_os_clipes_escolhidos_na_ordem(tmp_path, monkeypatch):
    import video_assembler as V
    from video_assembler import VideoSegment
    a = _clipe(str(tmp_path / "a.mp4"), "red", 2)
    b = _clipe(str(tmp_path / "b.mp4"), "blue", 2)
    mapa = {"https://x/a": a, "https://x/b": b}
    monkeypatch.setattr(V, "_resolve_override_source", lambda ov, d, g: (mapa[ov["value"]], "video"))
    monkeypatch.setattr(V, "_search_and_download_filling_duration", lambda *a, **k: pytest.fail("não devia buscar outra cena"))
    seg = VideoSegment(start=0, end=4, provider="pexels", query="x",
                       override_source={"source": "provider_url", "provider": "pexels", "value": "https://x/a", "kind": "video"},
                       clipes_extra=[{"source": "provider_url", "provider": "pexels", "value": "https://x/b", "duracao": 2}])
    audio = str(tmp_path / "n.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=d=4", audio], check=True)
    out = str(tmp_path / "o.mp4")
    V.assemble_video([seg], audio, out, str(tmp_path / "w"), site_cfg={"transition_type": "none"})

    def cor(t):
        px = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", out, "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            capture_output=True).stdout
        return px[0], px[2]
    r1, b1 = cor(1.0)
    r2, b2 = cor(3.0)
    assert r1 > 150 and b2 > 150  # vermelho e depois azul


def test_gerar_voz_lista_o_que_esta_rodando(A):
    A._GERAR_VOZ_STATUS["gv-x"] = {"running": True, "log": "", "erro": None, "pronto": False, "engine": "kokoro",
                                   "criado_em": time.time(), "texto_inicio": "Era uma vez", "palavras": 3}
    d = A.app.test_client().get("/gerar-voz/em-andamento").get_json()
    assert d["geracoes"][0]["job_id"] == "gv-x" and d["geracoes"][0]["running"]
    html = A.app.test_client().get("/gerar-voz").get_data(as_text=True)
    assert "gerarVozUltimo" in html and "Acompanhar" in html


def test_varios_videos_de_venda_e_qual_em_cada_marca(tmp_path, A):
    import io
    os.makedirs(A._job_dir("ch2"), exist_ok=True)
    cs = [{"id": f"v{k}", "chamada": True, "tipo": "venda", "insertion_point": 10.0 * k, "resolved_path": None,
           "description": "Venda", "audio_mode": "pause"} for k in range(3)]
    A._JOBS["ch2"] = {"job_id": "ch2", "status": "pronto_para_editar", "pending_segments": [], "cutaway_suggestions": cs}
    c = A.app.test_client()
    for nome in ("oferta_a.mp4", "oferta_b.mp4"):
        r = c.post("/job/ch2/chamadas/venda/enviar", data={"arquivo": (io.BytesIO(b"x"), nome)}, content_type="multipart/form-data")
        assert r.status_code == 302
    clipes = A._clipes_do_tipo(A._JOBS["ch2"], "venda")
    assert [x["nome"] for x in clipes] == ["oferta_a.mp4", "oferta_b.mp4"]
    d = c.post("/job/ch2/chamadas/escolher", json={"tipo": "venda", "escolhas": {"v0": clipes[1]["id"], "v1": "", "v2": clipes[0]["id"]}}).get_json()
    assert d["com_clipe"] == 2
    assert cs[0]["resolved_path"].endswith("oferta_b.mp4") and cs[1]["resolved_path"] is None and cs[2]["resolved_path"].endswith("oferta_a.mp4")
