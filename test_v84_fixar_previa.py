"""
v84 — "coloquei o JSON da IA no editor, ele aplicou tudo, mas na hora de
exportar apareceram outras cenas". Causa: trecho sem mídia escolhida fazia uma
busca NOVA na montagem, e ela trazia outros clipes que os da prévia. Agora a
montagem usa o clipe que a prévia mostrou (mesma busca, banco que baixa pelo link).
"""
import os

import pytest


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def _job(A, jid, previews, segs):
    os.makedirs(A._job_dir(jid), exist_ok=True)
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "providers": ["pexels", "pixabay", "magnific"],
                    "total_duration": float(len(segs) * 4), "pending_segments": segs, "segment_previews": previews}
    return A._JOBS[jid]


def _seg(i, q, prov="pexels", **kw):
    return dict({"start": i * 4.0, "end": i * 4.0 + 4, "provider": prov, "query": q, "media_type": "video", "override_source": None}, **kw)


def _prev(i, q, url, prov="pexels", **kw):
    return dict({"index": i, "ok": True, "thumbnail_url": "t", "result_url": url, "provider": prov, "query": q, "media_type": "video"}, **kw)


def test_montagem_usa_o_clipe_da_previa(A, monkeypatch):
    segs = [_seg(0, "dark road"), _seg(1, "old man"), _seg(2, "city", "magnific"), _seg(3, "forest"), _seg(4, "rain")]
    previews = [_prev(0, "dark road", "https://www.pexels.com/video/road-111/"),
                _prev(1, "outra busca", "https://www.pexels.com/video/man-222/"),       # busca mudou depois da prévia
                _prev(2, "city", "https://magnific.com/x", "magnific"),                 # banco que não baixa pelo link
                _prev(3, "forest", "https://pixabay.com/videos/forest-333/", "pixabay"),  # prévia caiu pro pixabay
                _prev(4, "rain", "https://www.pexels.com/video/road-111/")]             # trecho dividido: mesmo clipe
    job = _job(A, "fix-prev", previews, segs)
    montou = {}
    monkeypatch.setattr(A, "_start_assembly", lambda jid, j, s: montou.setdefault("segs", s))
    A.app.test_client().post("/job/fix-prev/confirm-segments", data={})
    s = montou["segs"]
    assert s[0].override_source == {"source": "provider_url", "provider": "pexels", "value": "https://www.pexels.com/video/road-111/", "kind": "video", "da_previa": True}
    assert s[1].override_source is None and s[2].override_source is None and s[4].override_source is None
    assert s[3].provider == "pixabay" and s[3].override_source["value"].endswith("forest-333/")
    # no editor o trecho continua automático
    assert all(not x.get("override_source") for x in job["pending_segments"])


def test_da_pra_desligar(A, monkeypatch):
    _job(A, "fix-prev-off", [_prev(0, "dark road", "https://www.pexels.com/video/road-111/")], [_seg(0, "dark road")])
    monkeypatch.setattr(A, "_job_site_cfg", lambda job: {"fixar_midias_da_previa": False})
    montou = {}
    monkeypatch.setattr(A, "_start_assembly", lambda jid, j, s: montou.setdefault("segs", s))
    A.app.test_client().post("/job/fix-prev-off/confirm-segments", data={})
    assert montou["segs"][0].override_source is None


def test_clipe_fixado_fica_reservado_pros_outros_trechos():
    import video_assembler as va
    t = va.UsedClipsTracker()
    assert t.try_claim("111", "pexels")
    assert not t.try_claim(111, "pexels")  # a busca dos outros trechos devolve o id como número


def test_clipe_da_previa_curto_repete_em_vez_de_entrar_outra_cena(tmp_path, monkeypatch):
    """Exportou com cenas que não estavam no editor: o clipe da prévia (curto)
    era completado com OUTRA cena da busca. Agora ele repete, como no Estúdio."""
    import subprocess
    import video_assembler as va
    from prompt_builder import VideoSegment
    clipe = str(tmp_path / "curto.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=red:s=320x180:r=30:d=1.5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", clipe], check=True)
    audio = str(tmp_path / "a.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=5", audio], check=True)
    chamadas = []
    monkeypatch.setattr(va, "_search_and_download_filling_duration", lambda *a, **k: chamadas.append(1) or [])
    monkeypatch.setattr(va.ClientFactory, "get_client", lambda self, provider: object())
    seg = VideoSegment(start=0.0, end=5.0, provider="pexels", query="x",
                       override_source={"source": "local_file", "value": clipe, "kind": "video", "da_previa": True})
    cfg = {"orientation": "16:9", "export_quality": "480p", "provider_priority": ["pexels"]}
    out = va.assemble_video([seg], audio, str(tmp_path / "o.mp4"), str(tmp_path / "w"), site_cfg=cfg)
    assert not chamadas and abs(va._probe_duration(out) - 5.0) < 0.2
    # escolhido à mão: continua completando com outra cena (pedido antigo)
    seg2 = VideoSegment(start=0.0, end=5.0, provider="pexels", query="x",
                        override_source={"source": "local_file", "value": clipe, "kind": "video"})
    va.assemble_video([seg2], audio, str(tmp_path / "o2.mp4"), str(tmp_path / "w2"), site_cfg=cfg)
    assert chamadas
