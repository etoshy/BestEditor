"""v84_73 — ✂️ trecho longo demais (a IA cansou no fim e mandou 2 min com um clipe só) vira pedaços."""
import json
import os

import pytest

import trechos_longos as tl
from prompt_builder import VideoSegment


def test_cortes_nas_pausas():
    pts = tl.cortes(0.0, 30.0, 7, [6.2, 8.0, 14.9, 21.0, 23.5])
    assert pts == [6.2, 12.0, 18.0, 23.5]  # puxa pra pausa mais perto (até 40% do passo); longe demais, fica no alvo
    assert all(b - a >= 1.5 for a, b in zip([0.0] + pts, pts + [30.0]))


def test_pedacos_e_buscas():
    s = {"start": 740.0, "end": 860.0, "provider": "pexels", "query": "dark cinema screen fade", "on_screen_text": "FIM",
         "alternativas": ["empty theater", "film projector"], "transition": "fade"}
    ps = tl.pedacos(s, 7, [])
    assert len(ps) == 18 and ps[0]["start"] == 740.0 and ps[-1]["end"] == 860.0
    assert all(abs(a["end"] - b["start"]) < 1e-9 for a, b in zip(ps, ps[1:]))
    assert ps[0]["query"] == "dark cinema screen fade" and ps[0]["on_screen_text"] == "FIM"
    assert ps[1]["query"] == "empty theater" and ps[2]["query"] == "film projector" and ps[1]["on_screen_text"] is None
    assert "transition" not in ps[0] and ps[-1]["transition"] == "fade"


def test_quem_nao_divide():
    assert not tl.pode_dividir({"start": 0, "end": 14, "provider": "pexels"}, 7)  # 14 s: ainda ok
    assert tl.pode_dividir({"start": 0, "end": 20, "provider": "pexels"}, 7)
    assert not tl.pode_dividir({"start": 0, "end": 120, "provider": "youtube"}, 7)
    assert not tl.pode_dividir({"start": 0, "end": 120, "provider": "pexels", "template": "X"}, 7)
    assert tl.pode_dividir({"start": 0, "end": 120, "provider": "pexels", "override_source": {"source": "local_file"}}, 7)
    ps = tl.pedacos({"start": 0, "end": 30, "provider": "pexels", "query": "q", "override_source": {"source": "url", "value": "u"}}, 7, [])
    assert ps[0]["override_source"]["value"] == "u" and all(p["override_source"] is None for p in ps[1:])
    assert not tl.pode_dividir({"start": 0, "end": 40, "provider": "pexels"}, 20)  # intervalo grande escolhido: 50 s de limite


def test_dividir_videosegment():
    segs = [VideoSegment(start=0.0, end=5.0, provider="pexels", query="a"),
            VideoSegment(start=5.0, end=65.0, provider="pixabay", query="b", alternativas=["c"])]
    out = tl.dividir_segmentos(segs, 7, [])
    assert out[0] is segs[0] and len(out) == 1 + 9 and all(isinstance(x, VideoSegment) for x in out)
    assert [x.query for x in out[1:4]] == ["b", "c", "b"] and out[-1].end == 65.0


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def _job(A, jid, segs=None):
    os.makedirs(A._job_dir(jid), exist_ok=True)
    A._JOBS[jid] = {"job_id": jid, "status": "aguardando_json", "created_at": 1.0, "total_duration": 100.0, "providers": ["pexels"],
                    "interval_seconds": 7, "segments": [{"start": float(k * 10), "end": float(k * 10 + 10), "text": f"frase {k}"} for k in range(10)],
                    "overlays": [], "cutaway_suggestions": []}
    if segs is not None:
        A._JOBS[jid].update(status="pronto_para_editar", pending_segments=segs, segment_previews=[None] * len(segs))
    return A._JOBS[jid]


def test_resposta_da_ia_com_trecho_longo_ja_chega_dividida(A, monkeypatch):
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    job = _job(A, "longo-ia")
    resp = json.dumps([{"start": 0.0, "end": 30.0, "provider": "pexels", "query": "a"},
                       {"start": 30.0, "end": 100.0, "provider": "pexels", "query": "dark cinema screen fade"}])
    A.app.test_client().post("/job/longo-ia/submit-json", data={"ai_response": resp})
    segs = job["pending_segments"]
    assert len(segs) > 10 and segs[-1]["end"] == 100.0 and job["trechos_longos_divididos"] == len(segs) - 2
    assert all(s["end"] - s["start"] <= 17.5 for s in segs)  # nenhum pedaço longo demais
    assert sum(1 for s in segs[1:] if s["start"] % 10 == 0) >= len(segs) // 2  # a maioria cortada no começo de uma frase


def test_rota_divide_um_ou_todos(A, monkeypatch):
    feitos = []
    monkeypatch.setattr(A, "_previas_dos_pedacos", lambda jid, idx: feitos.append(idx))
    segs = [{"start": 0.0, "end": 5.0, "provider": "pexels", "query": "a"},
            {"start": 5.0, "end": 45.0, "provider": "pexels", "query": "b", "override_source": {"source": "local_file", "value": "/x.mp4"}},
            {"start": 45.0, "end": 100.0, "provider": "pexels", "query": "c"}]
    job = _job(A, "longo-rota", segs)
    c = A.app.test_client()
    assert c.post("/job/longo-rota/editor/dividir-longo", json={"indice": 0}).status_code == 400
    d = c.post("/job/longo-rota/editor/dividir-longo", json={"indice": 1}).get_json()  # um só: o 1º pedaço fica com o arquivo
    assert d["novos"] == 5 and job["pending_segments"][1]["override_source"]["value"] == "/x.mp4"
    assert not job["pending_segments"][2].get("override_source") and job["pending_segments"][6]["end"] == 45.0
    assert feitos[-1] == [2, 3, 4, 5, 6]
    d = c.post("/job/longo-rota/editor/dividir-longo", json={}).get_json()  # todos os longos que sobraram
    assert d["divididos"] == 1 and len(job["pending_segments"]) == 7 + 8 and job["pending_segments"][-1]["end"] == 100.0
    assert len(job["segment_previews"]) == len(job["pending_segments"]) and feitos[-1] == list(range(8, 15))
    html = c.get("/job/longo-rota/edit-segments?modo=estudio").get_data(as_text=True)
    assert 'id="btnLongos"' in html and '"intervalo": 7' in html
