"""v74: preencher inteligente (barras embutidas), qualidade de exportação, cache do YouTube colado."""
import json
import os
import subprocess
import time

import pytest

import qualidade_export as qe
import video_assembler as va


def _video(path, vf, s="320x180", d=3):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={s}:r=30:d={d}", "-vf", vf, "-pix_fmt", "yuv420p", path], check=True)
    return path


def _pixel(path, t, x, y):
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-vf", f"crop=2:2:{x}:{y},scale=1:1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return list(out)


class TestPreencherInteligente:
    def test_detecta_barras_embutidas(self, tmp_path):
        lb = _video(str(tmp_path / "lb.mp4"), "pad=320:240:0:30:black")
        assert va.detectar_bordas_pretas(lb) == (320, 180, 0, 30)
        assert va.detectar_bordas_pretas(_video(str(tmp_path / "n.mp4"), "null")) is None

    def test_sem_barra_preta_na_saida(self, tmp_path):
        pb = _video(str(tmp_path / "pb.mp4"), "pad=426:320:93:0:black", s="240x320")
        z = va._normalize_clip(pb, 2.0, str(tmp_path / "z.mp4"), 640, 360, aspect_fill="zoom")
        s = va._normalize_clip(pb, 2.0, str(tmp_path / "s.mp4"), 640, 360, aspect_fill="smart", on_screen_text="oi")
        assert sum(_pixel(z, 1, 4, 180)) < 30          # o zoom deixa a barra embutida
        assert sum(_pixel(s, 1, 4, 180)) > 60          # o inteligente põe o vídeo desfocado no lugar
        assert abs(va._probe_duration(s) - 2.0) < 0.1
        lb = _video(str(tmp_path / "lb.mp4"), "pad=320:240:0:30:black")
        s2 = va._normalize_clip(lb, 2.0, str(tmp_path / "s2.mp4"), 640, 360, aspect_fill="smart")
        assert sum(_pixel(s2, 1, 320, 3)) > 60 and sum(_pixel(s2, 1, 320, 355)) > 60


class TestQualidade:
    def test_ajustar_so_quando_definida(self):
        cmd = ["ffmpeg", "-i", "a", "-c:v", "libx264", "-preset", "veryfast", "o.mp4"]
        assert qe.ajustar(cmd) == cmd
        qe.definir("maxima")
        try:
            assert qe.ajustar(cmd)[5:7] == ["-crf", "14"]
            assert qe.ajustar(cmd + ["-crf", "20"]).count("-crf") == 1
        finally:
            qe.limpar()
        assert qe.valida("xx") == "normal"

    def test_passe_final(self, tmp_path):
        v = _video(str(tmp_path / "v.mp4"), "null", d=1)
        assert qe.passe_final(v, "normal") is False
        assert qe.passe_final(v, "alta") is True and va._probe_duration(v) > 0.9


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


class TestApp:
    def test_form_salva_exportacao(self, A):
        jid = "v74exp"
        os.makedirs(A._job_dir(jid), exist_ok=True)
        A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 4.0, "export_quality": "720p",
                        "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "a"}], "segment_previews": [{"index": 0, "ok": False}], "segments": []}
        c = A.app.test_client()
        html = c.get(f"/job/{jid}/edit-segments?modo=estudio").get_data(as_text=True)
        assert 'id="expModal"' in html and 'value="smart"' in html and 'id="ytModal"' in html
        form = {"acao": "salvar", "seg_0_start": "0", "seg_0_end": "4", "seg_0_aspect_fill": "smart", "export_quality": "1440p", "qualidade_exportacao": "maxima"}
        assert c.post(f"/job/{jid}/confirm-segments", data=form, headers={"X-Requested-With": "fetch"}).status_code == 200
        j = A._JOBS[jid]
        assert (j["export_quality"], j["qualidade_exportacao"], j["pending_segments"][0]["aspect_fill"]) == ("1440p", "maxima", "smart")

    def test_youtube_colado_usa_cache(self, A, monkeypatch):
        n = []

        def baixar(url, pasta, *a, **k):
            os.makedirs(pasta, exist_ok=True)
            p = os.path.join(pasta, "v.mp4")
            open(p, "wb").write(b"x")
            n.append(a)
            return {"caminho": p}
        monkeypatch.setattr(A, "yt_baixar_video", baixar)
        monkeypatch.setattr(A, "yt_cortar_trecho", lambda s, a, b, o: open(o, "wb").write(b"c") and o)
        jid = "v74cache"
        import shutil
        shutil.rmtree(A._job_dir(jid), ignore_errors=True)
        os.makedirs(A._job_dir(jid), exist_ok=True)
        A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 8.0, "export_quality": "2160p",
                        "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "youtube", "query": "a"}, {"start": 4.0, "end": 8.0, "provider": "youtube", "query": "b"}],
                        "segment_previews": [{"index": 0, "ok": False}, {"index": 1, "ok": False}], "segments": []}
        c = A.app.test_client()
        for linha in ("1: https://youtu.be/CCC 0:05", "2: https://youtu.be/CCC 0:20"):
            r = c.post(f"/job/{jid}/youtube/texto", json={"texto": linha, "aplicar": True}).get_json()
            for _ in range(100):
                if c.get(f"/cutaway-youtube-status/{r['yt_job_id']}").get_json()["status"] != "processando":
                    break
                time.sleep(0.05)
        assert len(n) == 1 and n[0] == ("melhor",)  # 2º trecho reaproveita o download; 4K pede a melhor qualidade
        assert all(s.get("override_source") for s in A._JOBS[jid]["pending_segments"])
