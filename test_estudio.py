"""
Estúdio (editor novo com timeline arrastável) + transições robustas.

O Estúdio é só uma interface nova: ele manda os MESMOS campos do editor
clássico pro mesmo `confirm-segments`, então aqui o foco é nas rotas novas
(salvar sem montar, dividir/juntar, biblioteca em JSON, miniatura do trecho,
overlay de texto) e na montagem com transição em lotes.
"""
import io
import os
import subprocess

import pytest


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


@pytest.fixture
def client(A):
    return A.app.test_client()


def _job(A, job_id, n=3, dur=4.0):
    os.makedirs(A._job_dir(job_id), exist_ok=True)
    segs = [{"start": i * dur, "end": (i + 1) * dur, "provider": "pexels", "query": f"q{i}", "media_type": "video",
             "override_source": None} for i in range(n)]
    A._JOBS[job_id] = {"job_id": job_id, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": n * dur,
                       "pending_segments": segs, "segment_previews": [None] * n, "overlays": [],
                       "cutaway_suggestions": [], "media_library": []}
    return A._JOBS[job_id]


class TestPagina:
    def test_estudio_e_o_padrao_e_classico_continua_disponivel(self, A, client):
        _job(A, "est-pag")
        html = client.get("/job/est-pag/edit-segments").get_data(as_text=True)
        assert "Estúdio" in html and 'id="tracks"' in html and "Editor clássico" in html
        assert '"job_id": "est-pag"' in html
        classico = client.get("/job/est-pag/edit-segments?modo=classico")
        assert 'id="segments-form"' in classico.get_data(as_text=True)
        # a escolha fica lembrada (redirecionamentos voltam pro mesmo editor)
        assert "editor_modo=classico" in classico.headers.get("Set-Cookie", "")
        assert 'id="segments-form"' in client.get("/job/est-pag/edit-segments").get_data(as_text=True)
        assert 'id="tracks"' in client.get("/job/est-pag/edit-segments?modo=estudio").get_data(as_text=True)

    def test_estudio_traz_youtube_overlays_cortes_e_transicoes(self, A, client):
        job = _job(A, "est-tudo")
        job["pending_segments"][1]["provider"] = "youtube"
        job["overlays"] = [{"id": "o1", "media_type": "text", "text": "Inscreva-se", "start": 1, "end": 3, "style": {}}]
        job["cutaway_suggestions"] = [{"id": "c1", "insertion_point": 2.0, "description": "Coletiva", "audio_mode": "pause", "resolved_path": None}]
        html = client.get("/job/est-tudo/edit-segments").get_data(as_text=True)
        assert 'id="painel-youtube"' in html
        assert "Inscreva-se" in html and "Coletiva" in html
        assert "circleopen" in html and "blinds_h" in html  # catálogo de transições
        assert 'name="text"' in html  # adicionar texto por cima


class TestRotasNovas:
    def test_salvar_sem_montar(self, A, client, monkeypatch):
        job = _job(A, "est-salvar")
        monkeypatch.setattr(A, "_start_assembly", lambda *a: pytest.fail("não deveria montar"))
        r = client.post("/job/est-salvar/confirm-segments", data={
            "acao": "salvar", "seg_0_query": "novo termo", "seg_0_transition": "wipeleft", "seg_0_end": "5", "seg_1_start": "5",
        }, headers={"X-Requested-With": "fetch"})
        d = r.get_json()
        assert r.status_code == 200 and d["ok"]
        assert job["pending_segments"][0]["query"] == "novo termo"
        assert job["pending_segments"][0]["transition"] == "wipeleft"
        assert job["pending_segments"][0]["end"] == 5.0 and job["pending_segments"][1]["start"] == 5.0
        assert job["status"] == "pronto_para_editar"
        r2 = client.post("/job/est-salvar/confirm-segments", data={"acao": "salvar"})
        assert r2.status_code == 302 and r2.headers["Location"].endswith("/edit-segments")

    def test_dividir_e_juntar(self, A, client):
        job = _job(A, "est-div")
        job["pending_segments"][1]["override_source"] = {"source": "local_file", "value": "/x.mp4"}
        job["pending_segments"][1]["transition"] = "fade"
        r = client.post("/job/est-div/editor/dividir", json={"indice": 1, "tempo": 5.5})
        assert r.status_code == 200
        segs = job["pending_segments"]
        assert [(s["start"], s["end"]) for s in segs] == [(0, 4), (4, 5.5), (5.5, 8), (8, 12)]
        assert segs[1]["override_source"]["value"] == "/x.mp4" and segs[2]["override_source"] is None
        assert "transition" not in segs[1] and segs[2]["transition"] == "fade"  # a transição fica na emenda de saída
        assert len(job["segment_previews"]) == 4
        assert client.post("/job/est-div/editor/dividir", json={"indice": 0, "tempo": 0.1}).status_code == 400

        r = client.post("/job/est-div/editor/juntar", json={"indice": 1})
        assert r.status_code == 200
        assert [(s["start"], s["end"]) for s in job["pending_segments"]] == [(0, 4), (4, 8), (8, 12)]
        assert job["pending_segments"][1]["transition"] == "fade"
        assert client.post("/job/est-div/editor/juntar", json={"indice": 2}).status_code == 400

    def test_biblioteca_em_json_e_atribuir_ao_trecho(self, A, client):
        job = _job(A, "est-bib")
        r = client.post("/job/est-bib/upload-to-library?json=1",
                        data={"library_file": (io.BytesIO(b"\xff\xd8\xff"), "foto.jpg")}, content_type="multipart/form-data")
        item = r.get_json()["item"]
        assert item["media_type"] == "image" and item["filename"] == "foto.jpg"
        r = client.post(f"/job/est-bib/assign-library-to-segment/2?json=1", data={"item_id": item["id"]})
        seg = r.get_json()["segmento"]
        assert seg["override_source"]["source"] == "local_file" and seg["media_type"] == "image"
        assert job["pending_segments"][2]["media_type"] == "image"

    def test_miniatura_do_arquivo_do_trecho(self, A, client, tmp_path):
        job = _job(A, "est-thumb")
        v = tmp_path / "v.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=red:size=320x180:duration=1",
                        "-pix_fmt", "yuv420p", str(v)], check=True)
        job["pending_segments"][0]["override_source"] = {"source": "local_file", "value": str(v), "kind": "video"}
        r = client.get("/job/est-thumb/segment-thumb/0")
        assert r.status_code == 200 and r.data[:3] == b"\xff\xd8\xff"
        assert client.get("/job/est-thumb/segment-thumb/1").status_code == 404

    def test_overlay_de_texto_editavel(self, A, client):
        job = _job(A, "est-ov")
        job["overlays"] = [{"id": "t1", "media_type": "text", "text": "A", "start": 0, "end": 2, "style": {}}]
        r = client.post("/job/est-ov/update-overlay/t1", json={"text": "Novo", "font_size": "72", "x_percent": 30, "start": 1, "end": 3})
        assert r.status_code == 200
        ov = job["overlays"][0]
        assert ov["text"] == "Novo" and ov["style"]["font_size"] == 72 and ov["style"]["x_percent"] == 30
        assert (ov["start"], ov["end"]) == (1.0, 3.0)


class TestTransicoesEmLote:
    @pytest.fixture
    def clipes(self, tmp_path):
        cores = ["red", "lime", "blue", "yellow", "white", "cyan", "magenta"]
        out = []
        for i, c in enumerate(cores):
            p = tmp_path / f"c{i}.mp4"
            rate = 24 if i % 2 else 30  # bases de tempo diferentes de propósito
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color={c}:size=160x90:duration=2:rate={rate}",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)], check=True)
            out.append(str(p))
        return out

    def test_varios_lotes_mantem_a_duracao_certa(self, clipes, tmp_path, monkeypatch):
        import video_assembler as va
        monkeypatch.setattr(va, "TRANSICOES_POR_LOTE", 3)  # força 3 lotes + junção dos lotes
        plano = [("fade", 0.5), ("none", 0.0), ("blinds_h", 0.5), ("wipeleft", 0.5), ("none", 0.0), ("circleopen", 0.5)]
        saida = str(tmp_path / "out.mp4")
        va._concat_clips_com_plano(clipes, [2.0] * 7, plano, saida, str(tmp_path))
        esperado = 2.0 * 7 - sum(d for _t, d in plano)
        assert abs(va._probe_duration(saida) - esperado) < 0.15

    def test_se_o_ffmpeg_recusar_a_transicao_monta_com_corte_seco_sincronizado(self, clipes, tmp_path, monkeypatch):
        import video_assembler as va

        def recusa(*a, **k):
            raise va.VideoAssemblyError("No such transition")

        monkeypatch.setattr(va, "_xfade_lote", recusa)
        plano = [("fade", 0.5)] * 6
        saida = str(tmp_path / "out.mp4")
        va._concat_clips_com_plano(clipes, [2.0] * 7, plano, saida, str(tmp_path))
        assert abs(va._probe_duration(saida) - (14.0 - 3.0)) < 0.2  # o "rabo" de cada transição foi cortado

    def test_grafo_vai_em_arquivo_e_nao_na_linha_de_comando(self, clipes, tmp_path, monkeypatch):
        import video_assembler as va
        comandos = []
        original = va._run_ffmpeg

        def espiao(args, timeout=300):
            comandos.append(list(args))
            return original(args, timeout=timeout)

        monkeypatch.setattr(va, "_run_ffmpeg", espiao)
        va._concat_clips_com_plano(clipes[:3], [2.0] * 3, [("fade", 0.4), ("dissolve", 0.4)], str(tmp_path / "o.mp4"), str(tmp_path))
        assert any("-filter_complex_script" in c for c in comandos)
        assert not any("-filter_complex" in c for c in comandos)
