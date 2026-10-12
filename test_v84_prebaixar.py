"""
v84_59 — "coloca pra baixar os conteúdos logo na hora de busca/editor, depois
pra baixar é complicado, demora muito pra processar". Os clipes que a montagem
vai usar (clipe da prévia, link, resultado escolhido) já baixam em segundo
plano enquanto a pessoa edita; a montagem acha o arquivo e não baixa de novo.
"""
import os
import subprocess
import time

import pytest


def _fake_resolver(chamadas, falhar=()):
    def _r(ov, destino, get_client):
        chamadas.append(ov["value"])
        if ov["value"] in falhar:
            raise RuntimeError("link quebrado")
        p = os.path.join(destino, "clipe.mp4")
        with open(p, "wb") as f:
            f.write(b"x" * 10)
        return p, "video"
    return _r


class _Fab:
    def get_client(self, p):
        return object()

    def close_all(self):
        pass


def _ov(n, prov="pexels"):
    return {"source": "provider_url", "provider": prov, "value": f"https://www.pexels.com/video/c-{n}/", "kind": "video", "da_previa": True}


def test_chave_ignora_arquivo_local_e_e_estavel():
    import video_assembler as va
    assert va.chave_prebaixado({"source": "local_file", "value": "/x.mp4"}) is None
    assert va.chave_prebaixado(None) is None
    a = va.chave_prebaixado(_ov(1))
    assert a and a == va.chave_prebaixado(dict(_ov(1), da_previa=False)) and a != va.chave_prebaixado(_ov(2))


def test_prebaixa_uma_vez_e_reaproveita(tmp_path, monkeypatch):
    import video_assembler as va
    chamadas = []
    monkeypatch.setattr(va, "_resolve_override_source", _fake_resolver(chamadas))
    progresso = []
    res = va.prebaixar_midias([_ov(1), _ov(2), _ov(1)], str(tmp_path), {"assembly_fetch_concurrency": 2},
                              on_item=lambda f, t, ok: progresso.append((f, t)), factory_fn=_Fab)
    assert res["total"] == 2 and res["baixados"] == 2 and res["falhas"] == 0
    assert sorted(chamadas) == sorted([_ov(1)["value"], _ov(2)["value"]])
    assert progresso[-1] == (2, 2)
    # 2ª vez: nada baixa
    res2 = va.prebaixar_midias([_ov(1), _ov(2)], str(tmp_path), {}, factory_fn=_Fab)
    assert res2["ja_tinha"] == 2 and len(chamadas) == 2
    # a montagem pega o arquivo do cache sem chamar o download
    p, k = va.resolver_override_cacheado(_ov(1), str(tmp_path / "dl"), None, cache_dir=str(tmp_path))
    assert os.path.exists(p) and k == "video" and len(chamadas) == 2
    # cada link na sua própria pasta (dois downloads nunca escrevem no mesmo arquivo)
    assert va.prebaixado(_ov(1), str(tmp_path))[0] != va.prebaixado(_ov(2), str(tmp_path))[0]


def test_falha_nao_trava_e_fica_pra_montagem(tmp_path, monkeypatch):
    import video_assembler as va
    chamadas = []
    monkeypatch.setattr(va, "_resolve_override_source", _fake_resolver(chamadas, falhar={_ov(2)["value"]}))
    res = va.prebaixar_midias([_ov(1), _ov(2)], str(tmp_path), {}, factory_fn=_Fab)
    assert res["baixados"] == 1 and res["falhas"] == 1 and "link quebrado" in res["erros"][0]
    assert va.prebaixado(_ov(2), str(tmp_path)) is None


def test_arquivo_apagado_baixa_de_novo(tmp_path, monkeypatch):
    import video_assembler as va
    chamadas = []
    monkeypatch.setattr(va, "_resolve_override_source", _fake_resolver(chamadas))
    p, _ = va.resolver_override_cacheado(_ov(1), str(tmp_path), None, cache_dir=str(tmp_path))
    os.remove(p)
    va.resolver_override_cacheado(_ov(1), str(tmp_path), None, cache_dir=str(tmp_path))
    assert len(chamadas) == 2


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def _job(A, jid):
    os.makedirs(A._job_dir(jid), exist_ok=True)
    segs = [
        {"start": 0.0, "end": 4.0, "provider": "pexels", "query": "road", "media_type": "video", "override_source": None},
        {"start": 4.0, "end": 8.0, "provider": "pexels", "query": "man", "media_type": "video",
         "override_source": {"source": "url", "value": "https://x.com/a.mp4", "kind": "video"},
         "clipes_extra": [{"source": "provider_url", "provider": "pexels", "value": "https://www.pexels.com/video/extra-9/"}]},
        {"start": 8.0, "end": 12.0, "provider": "pexels", "query": "pc", "media_type": "video",
         "override_source": {"source": "local_file", "value": "/x.mp4", "kind": "video"}},
    ]
    previews = [{"index": 0, "ok": True, "result_url": "https://www.pexels.com/video/road-1/", "provider": "pexels",
                 "query": "road", "media_type": "video"}, None, None]
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "providers": ["pexels"],
                    "total_duration": 12.0, "pending_segments": segs, "segment_previews": previews,
                    "fixacao_previa": ["diag antigo"]}
    return A._JOBS[jid]


def test_lista_e_o_que_a_montagem_baixaria(A):
    job = _job(A, "pre-lista")
    valores = [o["value"] for o in A._prebaixar_lista(job)]
    assert valores == ["https://www.pexels.com/video/road-1/", "https://x.com/a.mp4", "https://www.pexels.com/video/extra-9/"]
    assert job["fixacao_previa"] == ["diag antigo"]  # não mexe no diagnóstico da montagem


def test_roda_em_segundo_plano_e_mostra_andamento(A, monkeypatch):
    import video_assembler as va
    monkeypatch.delenv("NARRATION_SEM_PREBAIXAR", raising=False)
    vistos = []

    def _fake(lista, cache_dir, cfg, on_item=None, cancel_check=None, **k):
        vistos.append((len(lista), cache_dir))
        on_item(1, len(lista), True)
        return {"total": len(lista), "baixados": len(lista), "ja_tinha": 0, "falhas": 0, "erros": []}
    monkeypatch.setattr(va, "prebaixar_midias", _fake)
    _job(A, "pre-bg")
    c = A.app.test_client()
    assert c.post("/job/pre-bg/prebaixar").status_code == 200
    for _ in range(50):
        d = c.get("/job/pre-bg/prebaixar").get_json()
        if d.get("estado") == "pronto" and not d["rodando"]:
            break
        time.sleep(0.05)
    assert d["estado"] == "pronto" and d["total"] == 3 and d["feitos"] == 3
    assert vistos[0][1] == os.path.join(A._job_dir("pre-bg"), "prebaixados")
    assert c.get("/job/pre-bg/status").get_json()["prebaixar"]["total"] == 3


def test_da_pra_desligar_e_testes_nao_baixam(A, monkeypatch):
    job = _job(A, "pre-off")
    assert A._prebaixar_iniciar("pre-off", job) is False  # conftest: NARRATION_SEM_PREBAIXAR
    monkeypatch.delenv("NARRATION_SEM_PREBAIXAR", raising=False)
    monkeypatch.setattr(A, "_job_site_cfg", lambda j: {"prebaixar_no_editor": False})
    assert A._prebaixar_iniciar("pre-off", job) is False


def test_montagem_usa_o_arquivo_prebaixado(tmp_path, monkeypatch):
    """O clipe da prévia já estava em <job>/prebaixados: a montagem não chama o download."""
    import video_assembler as va
    from prompt_builder import VideoSegment
    work = tmp_path / "w"
    cache = work / "prebaixados"
    clipe_tmp = str(tmp_path / "c.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=blue:s=320x180:r=30:d=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", clipe_tmp], check=True)
    audio = str(tmp_path / "a.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=3", audio], check=True)

    def _copia(ov, destino, gc):
        import shutil
        p = os.path.join(destino, "c.mp4")
        shutil.copy(clipe_tmp, p)
        return p, "video"
    monkeypatch.setattr(va, "_resolve_override_source", _copia)
    va.prebaixar_midias([_ov(5)], str(cache), {}, factory_fn=_Fab)

    def _proibido(*a, **k):
        raise AssertionError("baixou de novo na montagem")
    monkeypatch.setattr(va, "_resolve_override_source", _proibido)
    monkeypatch.setattr(va.ClientFactory, "get_client", lambda self, provider: object())
    seg = VideoSegment(start=0.0, end=3.0, provider="pexels", query="x", override_source=_ov(5))
    cfg = {"orientation": "16:9", "export_quality": "480p", "provider_priority": ["pexels"]}
    out = va.assemble_video([seg], audio, str(tmp_path / "o.mp4"), str(work), site_cfg=cfg)
    assert os.path.exists(out)


def test_previas_ficam_guardadas_e_o_estudio_usa_do_disco(A, monkeypatch):
    """'se o projeto já baixou os arquivos uma vez, mantém salvos pra não baixar tudo de novo ao abrir'."""
    job = _job(A, "pre-previas")
    job["segment_previews"][0].update(thumbnail_url="https://images.pexels.com/t/1.jpeg?w=320",
                                      video_preview_url="https://videos.pexels.com/v/1.mp4")
    baixados = []

    def _fake(url, destino):
        baixados.append(url)
        with open(destino, "wb") as f:
            f.write(b"0123456789" * 100)
        return True
    monkeypatch.setattr(A, "_baixar_previa", _fake)
    pb = {}
    A._guardar_previas("pre-previas", job, pb)
    assert pb == {"previas_total": 2, "previas": 2} and len(baixados) == 2
    p = A._seg_estudio("pre-previas", job, 0)["_preview"]
    assert p["video_preview_url"].startswith("/job/pre-previas/cache-previa/") and p["video_preview_url"].endswith(".mp4")
    assert p["thumbnail_url"].startswith("/job/pre-previas/cache-previa/")
    assert p["video_remoto"] == "https://videos.pexels.com/v/1.mp4" and p["thumb_remoto"].startswith("https://images.pexels.com/")
    c = A.app.test_client()
    r = c.get(p["video_preview_url"], headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.data == b"0123456789"
    assert c.get("/job/pre-previas/cache-previa/..%2Fstate.json").status_code == 404
    # 2ª vez (reabrir o projeto): nada baixa de novo
    A._guardar_previas("pre-previas", job, pb)
    assert len(baixados) == 2 and pb["previas"] == 2


def test_previa_que_nao_baixa_continua_pelo_link(A, monkeypatch):
    job = _job(A, "pre-previas2")
    job["segment_previews"][0].update(video_preview_url="https://videos.pexels.com/v/2.mp4")
    monkeypatch.setattr(A, "_baixar_previa", lambda u, d: False)
    A._guardar_previas("pre-previas2", job, {})
    p = A._seg_estudio("pre-previas2", job, 0)["_preview"]
    assert p["video_preview_url"] == "https://videos.pexels.com/v/2.mp4" and p["video_remoto"] is None
