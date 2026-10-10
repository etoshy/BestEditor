"""v84 — timelines alternativas no Estúdio: Timeline 2 com a 2ª melhor opção
de cada cena (mesma edição da 1) e "Juntar", que escolhe trecho a trecho."""
import os
import re
import shutil
import subprocess
import time

import pytest

import timelines as tl


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def _seg(i, q, prov="pexels", **kw):
    return dict({"start": i * 4.0, "end": i * 4.0 + 4, "provider": prov, "query": q, "media_type": "video", "override_source": None}, **kw)


def _prev(i, q, url, prov="pexels"):
    return {"index": i, "ok": True, "thumbnail_url": "https://cdn/" + q, "result_url": url, "provider": prov, "query": q, "media_type": "video"}


def _job(A, jid, segs, previews):
    os.makedirs(A._job_dir(jid), exist_ok=True)
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "providers": ["pexels"],
                    "audio_path": "", "total_duration": float(len(segs) * 4), "pending_segments": segs, "segment_previews": previews}
    return A._JOBS[jid]


# ------------------------------------------------------------------ lógica pura
def _job_puro():
    segs = [_seg(0, "road", efeito="zoom_lento"), _seg(1, "man"), _seg(2, "city")]
    prevs = [_prev(i, s["query"], f"https://www.pexels.com/video/{s['query']}-1/") for i, s in enumerate(segs)]
    job = {"pending_segments": segs, "segment_previews": prevs}
    t2 = []
    for i, s in enumerate(segs):
        f = tl.fatia(s, _prev(i, s["query"], f"https://www.pexels.com/video/{s['query']}-2/"))
        f["override_source"] = {"source": "provider_url", "provider": "pexels", "value": f"https://www.pexels.com/video/{s['query']}-2/"}
        t2.append(f)
    tl.guardar_gerada(job, "2", t2)
    return job


def test_trocar_muda_so_a_midia_e_mantem_a_edicao():
    job = _job_puro()
    tl.trocar(job, "2")
    assert job["pending_segments"][1]["override_source"]["value"].endswith("man-2/")
    job["pending_segments"][2]["efeito"] = "vhs"  # edição feita NA timeline 2
    tl.trocar(job, "1")
    assert job["pending_segments"][1]["override_source"] is None
    assert job["segment_previews"][1]["result_url"].endswith("man-1/")
    assert job["pending_segments"][2]["efeito"] == "vhs" and job["pending_segments"][0]["efeito"] == "zoom_lento"


def test_dividir_numa_timeline_nao_bagunca_a_outra():
    job = _job_puro()
    segs = job["pending_segments"]
    a, b = dict(segs[1], end=6.0), dict(segs[1], start=6.0)
    job["pending_segments"] = [segs[0], a, b, segs[2]]
    job["segment_previews"] = [job["segment_previews"][0], job["segment_previews"][1], dict(job["segment_previews"][1]), job["segment_previews"][2]]
    tl.trocar(job, "2")
    vals = [s["override_source"]["value"] for s in job["pending_segments"]]
    assert vals[1] == vals[2] and vals[1].endswith("man-2/") and vals[3].endswith("city-2/")


def test_juntar_escolhe_trecho_a_trecho_e_guarda_troca_manual():
    job = _job_puro()
    tl.trocar(job, "3")
    assert tl.escolhas(job) == ["1", "1", "1"]
    tl.escolher(job, [1], "2")
    assert job["pending_segments"][1]["override_source"]["value"].endswith("man-2/")
    assert job["pending_segments"][0]["override_source"] is None
    # troca à mão dentro do Juntar
    job["pending_segments"][2]["override_source"] = {"source": "local_file", "value": "/x/meu.mp4", "kind": "video"}
    tl.trocar(job, "1")
    assert job["pending_segments"][2]["override_source"] is None
    tl.trocar(job, "3")
    assert tl.escolhas(job) == ["1", "2", "proprio"]
    assert job["pending_segments"][2]["override_source"]["value"] == "/x/meu.mp4"
    tl.escolher(job, [0, 1, 2], "1")
    assert all(s["override_source"] is None for s in job["pending_segments"])


def test_sem_timeline_2_nao_troca():
    job = {"pending_segments": [_seg(0, "a")], "segment_previews": [None]}
    with pytest.raises(LookupError):
        tl.trocar(job, "2")
    with pytest.raises(ValueError):
        tl.escolher(job, [0], "2")


def test_preview_evita_o_que_a_timeline_1_usa():
    import video_assembler as va
    cands = [{"id": 1, "url": "u1", "thumbnail": "t"}, {"id": 2, "url": "u2", "thumbnail": "t"}]
    assert va._escolher_candidato_previa(cands, None, "pexels")["url"] == "u1"
    assert va._escolher_candidato_previa(cands, None, "pexels", {"u1"})["url"] == "u2"
    assert va._escolher_candidato_previa(cands, va.UsedClipsTracker(), "pexels", {"u1", "u2"}) is None


# ------------------------------------------------------------------ rotas
def _esperar(A, jid):
    for _ in range(100):
        g = A._JOBS[jid].get("timelines", {}).get("gerando")
        if not g:
            return
        assert not g.get("erro"), g
        time.sleep(0.05)
    raise AssertionError("não terminou")


def test_gerar_trocar_juntar_e_montar(A, monkeypatch, tmp_path):
    segs = [_seg(0, "road"), _seg(1, "man", "magnific"), _seg(2, "cat", "bing", media_type="image"),
            _seg(3, "yt", "youtube", override_source={"source": "local_file", "value": "/x/yt.mp4", "kind": "video"})]
    prevs = [_prev(0, "road", "https://www.pexels.com/video/road-1/"), _prev(1, "man", "https://magnific.com/m1", "magnific"),
             {"index": 2, "ok": True, "thumbnail_url": "/job/tl-rotas/thumbnail/2", "thumbnail_path": "/x/cat1.jpg", "provider": "bing"},
             {"index": 3, "ok": True, "thumbnail_url": None}]
    job = _job(A, "tl-rotas", segs, prevs)
    job["imagens_buscadores"] = {"cat": {"ok": True, "path": "/x/cat1.jpg", "original_url": "https://img/cat1.jpg"}}
    pedidos = {}

    def falso_preview(seg, site_cfg=None, client_factory=None, used_tracker=None, evitar=None):
        pedidos.setdefault("evitar", set()).update(evitar or ())
        return {"ok": True, "thumbnail_url": "https://cdn/2", "result_url": f"https://www.pexels.com/video/{seg.query}-2/" if seg.provider == "pexels" else "https://magnific.com/m2",
                "label": "segunda", "provider": seg.provider, "video_preview_url": None, "error": None}

    def falso_lote(items, pasta, cfg, cache=None, on_result=None, evitar_extra=None, **kw):
        pedidos["evitar_img"] = list(evitar_extra or [])
        for i, _s in items:
            on_result(i, {"ok": True, "path": str(tmp_path / "cat2.jpg"), "engine": "bing", "title": "gato 2"})

    monkeypatch.setattr(A, "fetch_segment_preview_lightweight", falso_preview)
    monkeypatch.setattr(A, "prefetch_browser_images", falso_lote)
    monkeypatch.setattr(A, "ClientFactory", lambda cfg: type("F", (), {"close_all": lambda self: None})())
    c = A.app.test_client()

    assert c.post("/job/tl-rotas/timeline/trocar", json={"para": "2"}).status_code == 409  # ainda não gerada
    assert c.post("/job/tl-rotas/timeline/gerar").get_json()["ok"]
    _esperar(A, "tl-rotas")
    assert "https://www.pexels.com/video/road-1/" in pedidos["evitar"] and "https://img/cat1.jpg" in pedidos["evitar_img"]
    assert c.get("/job/tl-rotas/timeline/status").get_json()["tem_2"]

    assert c.post("/job/tl-rotas/timeline/trocar", json={"para": "2"}).get_json()["ativa"] == "2"
    p = job["pending_segments"]
    assert p[0]["override_source"]["value"].endswith("road-2/")
    assert p[1]["override_source"] is None and job["segment_previews"][1].get("nao_fixa")  # magnific não fixa
    assert p[2]["override_source"]["value"].endswith("cat2.jpg")
    assert p[3]["override_source"]["value"] == "/x/yt.mp4"  # YouTube: igual à 1
    html = c.get("/job/tl-rotas/edit-segments?modo=estudio").get_data(as_text=True)
    assert 'id="tlSel"' in html and '"ativa": "2"' in html.replace("'", '"') or '"ativa":"2"' in html

    assert c.post("/job/tl-rotas/timeline/trocar", json={"para": "3"}).get_json()["ativa"] == "3"
    r = c.post("/job/tl-rotas/timeline/escolher", json={"indices": [0], "de": "2"}).get_json()
    assert r["escolhas"][:2] == ["2", "1"] and r["segmentos"]["0"]["override_source"]["value"].endswith("road-2/")

    montou = {}
    monkeypatch.setattr(A, "_start_assembly", lambda jid, j, s: montou.setdefault("segs", s))
    c.post("/job/tl-rotas/confirm-segments", data={})
    s = montou["segs"]
    assert s[0].override_source["value"].endswith("road-2/")       # da timeline 2
    assert s[1].override_source is None or s[1].override_source["value"] == "https://magnific.com/m1"  # da 1 (magnific: busca)


def test_script_do_estudio_compila(A, tmp_path):
    if not shutil.which("node"):
        pytest.skip("sem node")
    _job(A, "tl-js", [_seg(0, "a"), _seg(1, "b")], [None, None])
    html = A.app.test_client().get("/job/tl-js/edit-segments?modo=estudio").get_data(as_text=True)
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    alvo = tmp_path / "s.js"
    alvo.write_text("\n;\n".join(scripts), encoding="utf-8")
    r = subprocess.run(["node", "--check", str(alvo)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
