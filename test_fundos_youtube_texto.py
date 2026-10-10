"""v73: fundos escolhíveis (destaques e cenas) e links do YouTube colados como texto."""
import json
import os
import shutil
import subprocess
import time

import pytest

import dp_destaques as dd
import dp_fundos as df
import yt_texto


class TestYtTexto:
    @pytest.mark.parametrize("linha,trecho,vid,ini,fim", [
        ("3: https://youtu.be/abc123?t=95 1:35-1:42", 3, "abc123", 95.0, 102.0),
        ("https://www.youtube.com/watch?v=xyz&t=1m5s", None, "xyz", 65.0, None),
        ("trecho 5 - https://youtube.com/shorts/qwe 12s", 5, "qwe", 12.0, None),
        ("1:02:03 - 1:02:09 https://www.youtube.com/watch?v=abc", None, "abc", 3723.0, 3729.0),
        ("#2 youtube.com/watch?v=k1 de 10 até 20", 2, "k1", 10.0, 20.0),
        ("T4 https://youtu.be/zz?start=30&end=36", 4, "zz", 30.0, 36.0),
    ])
    def test_linhas(self, linha, trecho, vid, ini, fim):
        r = yt_texto.parse_linha(linha)
        assert (r["trecho"], r["id"], r["inicio"], r["fim"], r["erro"]) == (trecho, vid, ini, fim, None)
        assert r["url"] == f"https://www.youtube.com/watch?v={vid}"

    def test_erros_e_distribuicao(self):
        assert yt_texto.parse_linha("") is None and yt_texto.parse_linha("olá")["erro"]
        assert yt_texto.parse_linha("https://youtu.be/a 50 40")["erro"]
        out = yt_texto.distribuir("https://youtu.be/a 0:10\n7: https://youtu.be/b\nhttps://youtu.be/c 5 8\nhttps://youtu.be/d\n9: https://youtu.be/e", [4, 5, 6, 3, 3, 3, 3], [2, 3])
        assert [o.get("indice") for o in out] == [2, 6, 3, None, None]
        assert out[0]["fim"] == 16.0 and out[1]["inicio"] == 0.0 and out[1]["fim"] == 3.0
        assert "aviso" not in out[2] and out[3]["erro"] and out[4]["erro"]


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def _job(A, jid, n=4):
    shutil.rmtree(A._job_dir(jid), ignore_errors=True)
    os.makedirs(A._job_dir(jid), exist_ok=True)
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": n * 4.0,
                    "pending_segments": [{"start": i * 4.0, "end": i * 4.0 + 4, "provider": "pexels", "query": "a"} for i in range(n)],
                    "segment_previews": [{"index": i, "ok": False} for i in range(n)], "segments": []}
    return A._JOBS[jid]


class TestRotaYoutubeTexto:
    def test_confere_e_aplica(self, A, tmp_path, monkeypatch):
        baixados = []

        def baixar(url, pasta, *a, **k):
            os.makedirs(pasta, exist_ok=True)
            p = os.path.join(pasta, "v.mp4")
            open(p, "wb").write(b"x")
            baixados.append(url)
            return {"caminho": p}

        def cortar(src, a, b, out):
            open(out, "wb").write(f"{a}-{b}".encode())
            return out
        monkeypatch.setattr(A, "yt_baixar_video", baixar)
        monkeypatch.setattr(A, "yt_cortar_trecho", cortar)
        job = _job(A, "yttxt")
        c = A.app.test_client()
        texto = "2: https://youtu.be/AAA 1:00-1:05\nhttps://youtu.be/AAA?t=30\nnada"
        r = c.post("/job/yttxt/youtube/texto", json={"texto": texto, "alvos": [0, 1, 2, 3]}).get_json()
        assert [l.get("indice") for l in r["linhas"]] == [1, 0, None] and r["linhas"][1]["fim"] == 34.0
        assert not job["pending_segments"][1].get("override_source")
        r = c.post("/job/yttxt/youtube/texto", json={"texto": texto, "alvos": [0, 1, 2, 3], "aplicar": True}).get_json()
        for _ in range(100):
            st = c.get(f"/cutaway-youtube-status/{r['yt_job_id']}").get_json()
            if st["status"] != "processando":
                break
            time.sleep(0.05)
        assert st["status"] == "pronto" and [i["status"] for i in st["itens"]] == ["pronto", "pronto"]
        assert baixados == ["https://www.youtube.com/watch?v=AAA"]  # mesmo vídeo baixado uma vez só
        s1 = job["pending_segments"][1]
        assert s1["override_source"]["source"] == "local_file" and open(s1["override_source"]["value"]).read() == "60.0-65.0"
        assert s1["youtube_link"]["inicio"] == 60.0
        assert c.post("/job/yttxt/youtube/texto", json={"texto": "nada", "aplicar": True}).status_code == 400


class TestFundos:
    def test_resolver(self):
        h = dd.estilo("marca_azul")
        assert df.resolver({}, h["cena"]) == ("grade_ondulada", "#1E5BD6", 1.0)
        assert df.resolver({"fundo": "faixas"}, h["cena"])[0] == "faixas"
        assert df.resolver({"fundo": "banho_cor"}, h["cena"], {"primaria": "#112233"})[1] == "#112233"
        assert df.resolver({"fundo": "ondas", "fundo_cor": "#ff0000", "fundo_int": 0.05}, {}) == ("ondas", "#FF0000", 0.15)
        assert df.resolver({}, {"fundo": "escurecer"}, padrao={"fundo": "desfoque"})[0] == "desfoque"
        assert df.resolver({"sem_fundo": True}, h["cena"])[0] == "nenhum"
        assert df.do_estilo({"fundo": "faixas"}) == ("faixas", None)

    def test_todos_os_pngs(self, tmp_path):
        for fid in ("gradiente", "faixas", "linhas", "grade", "ondas", "grade_ondulada", "grade_3d", "pontos", "banho_cor", "cor_gradiente", "cor_solida", "papel", "vinheta"):
            et, png = df.etapas_destaque(fid, "#3E8EFF", 0.8, 1.0, 2.0, 160, 90, str(tmp_path))
            assert png and os.path.exists(png), fid
        # vinheta (v84_20) virou o gradiente radial da telinha (PNG) — o resto continua sendo filtro
        for fid in ("escurecer", "desfoque", "desfoque_escuro", "desfoque_cor", "flash", "painel"):
            et, png = df.etapas_destaque(fid, "#3E8EFF", 0.8, 1.0, 2.0, 160, 90, str(tmp_path))
            assert et and png is None, fid

    def test_fundo_aparece_depois_de_2s(self, tmp_path):
        """Regressão: imagem a 2 fps + overlay com enable= não aparecia (agora fps=30 na cadeia)."""
        base = str(tmp_path / "b.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x8090A0:s=160x90:r=30:d=6", "-pix_fmt", "yuv420p", base], check=True)
        out = dd.aplicar_destaques(base, str(tmp_path / "o.mp4"), [{"estilo": "glow_01", "start": 3.05, "end": 4.5, "texto": "x", "fundo": "cor_solida", "fundo_cor": "#FF0000"}],
                                   160, 90, str(tmp_path / "w"))
        px = subprocess.run(["ffmpeg", "-v", "error", "-ss", "3.8", "-i", out, "-frames:v", "1", "-vf", "crop=4:4:2:2,scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            capture_output=True, check=True).stdout
        assert px[0] > 180 and px[1] < 90, list(px)

    def test_cena_com_fundo_novo(self, tmp_path):
        import cenas_dp
        clip = str(tmp_path / "c.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2", "-pix_fmt", "yuv420p", clip], check=True)
        for f in ("grade_ondulada", "vidro_cor", "cor_solida"):
            saida = str(tmp_path / f"{f}.mp4")
            cenas_dp.renderizar_cena("MOLDURA_02", [clip], [0.0], 1.5, saida, 320, 180, str(tmp_path / "w"), campos={"_fundo": f, "_fundo_cor": "#E0313B"})
            px = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.0", "-i", saida, "-frames:v", "1", "-vf", "crop=6:6:1:1,scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                capture_output=True, check=True).stdout
            assert px[0] > px[2], (f, list(px))  # canto avermelhado: a cor escolhida pegou

    def test_form_salva_fundo_cor_e_padrao(self, A):
        job = _job(A, "fdform", 2)
        c = A.app.test_client()
        form = {"acao": "salvar", "seg_0_start": "0", "seg_0_end": "4", "seg_1_start": "4", "seg_1_end": "8",
                "destaques_json": json.dumps([{"id": "a", "estilo": "glow_01", "start": 1, "end": 3, "texto": "x", "fundo": "ondas", "fundo_cor": "#ff0000", "fundo_int": 0.5, "cor": "#00ff00"},
                                              {"id": "b", "estilo": "glow_01", "start": 4, "end": 6, "texto": "y", "fundo": "inventado"}]),
                "hl_fundo_json": json.dumps({"fundo": "faixas", "fundo_int": 0.7})}
        assert c.post("/job/fdform/confirm-segments", data=form, headers={"X-Requested-With": "fetch"}).status_code == 200
        a, b = job["destaques"]
        assert (a["fundo"], a["fundo_cor"], a["fundo_int"], a["cor"]) == ("ondas", "#FF0000", 0.5, "#00FF00") and "fundo" not in b
        assert job["editor_defaults"]["hl_fundo"] == {"fundo": "faixas", "fundo_int": 0.7}
        m = A._destaques_para_montar(job)
        assert m[0]["fundo"] == "ondas" and m[1]["fundo"] == "faixas" and m[1]["fundo_int"] == 0.7

    def test_template_aceita_fundo_e_cor(self, A):
        tid, campos = A._template_do_form({"seg_0_template": "MOLDURA_02", "seg_0_template_campos": json.dumps({"_fundo": "grade_ondulada", "_fundo_cor": "#abcdef"})}, 0, {})
        assert tid == "MOLDURA_02" and campos == {"_fundo": "grade_ondulada", "_fundo_cor": "#ABCDEF"}
