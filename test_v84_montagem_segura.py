"""
v84_59 — "deu um erro num clip, voltou pro editor, foi exportar de novo do zero"
e "ao clicar em exportar já olha todos os possíveis erros de uma vez".
1) a montagem guarda os clipes prontos: ao montar de novo só refaz o que falhou/mudou;
2) quando falha, diz TODOS os trechos que falharam (não só o 1º);
3) 🔎 checagem antes de montar: confere todos os trechos de uma vez.
"""
import os
import subprocess

import pytest


def _clipe(caminho, cor="red", d=2):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color={cor}:s=320x180:r=30:d={d}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(caminho)], check=True)
    return str(caminho)


def _audio(caminho, d=6):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=d={d}", str(caminho)], check=True)
    return str(caminho)


def _seg(i, arq):
    from prompt_builder import VideoSegment
    return VideoSegment(start=i * 2.0, end=i * 2.0 + 2, provider="pexels", query=f"q{i}",
                        override_source={"source": "local_file", "value": arq, "kind": "video"})


CFG = {"orientation": "16:9", "export_quality": "480p", "provider_priority": ["pexels"], "transition_type": "none"}


def test_falha_lista_todos_e_remontagem_reaproveita(tmp_path, monkeypatch):
    import video_assembler as va
    monkeypatch.setattr(va, "_search_and_download_filling_duration", lambda *a, **k: [])
    bom = _clipe(tmp_path / "a.mp4")
    audio = _audio(tmp_path / "n.wav")
    work = tmp_path / "w"
    segs = [_seg(0, bom), _seg(1, str(tmp_path / "sumiu1.mp4")), _seg(2, str(tmp_path / "sumiu2.mp4"))]
    with pytest.raises(va.VideoAssemblyError) as e:
        va.assemble_video(segs, audio, str(tmp_path / "o.mp4"), str(work), site_cfg=CFG)
    assert e.value.segment_indices == [1, 2] and e.value.segment_index == 1
    msg = str(e.value)
    assert msg.startswith("Trecho 2:") and "Trecho 3:" in msg and "♻" in msg
    # corrigiu os dois: o trecho 1 (que já tinha ficado pronto) não é refeito
    norm = []
    orig = va._normalize_clip
    monkeypatch.setattr(va, "_normalize_clip", lambda *a, **k: norm.append(a[0]) or orig(*a, **k))
    b2, b3 = _clipe(tmp_path / "b.mp4", "blue"), _clipe(tmp_path / "c.mp4", "green")
    out = va.assemble_video([_seg(0, bom), _seg(1, b2), _seg(2, b3)], audio, str(tmp_path / "o.mp4"), str(work), site_cfg=CFG)
    assert os.path.exists(out) and sorted(norm) == sorted([b2, b3])
    # 3ª vez sem mudar nada: nenhum trecho refeito; e só ficam os clipes que valem agora
    norm.clear()
    va.assemble_video([_seg(0, bom), _seg(1, b2), _seg(2, b3)], audio, str(tmp_path / "o.mp4"), str(work), site_cfg=CFG)
    assert norm == []
    assert len([n for n in os.listdir(work / "clips_prontos") if n.endswith(".mp4")]) == 3


def test_mudou_o_trecho_ou_o_arquivo_refaz(tmp_path, monkeypatch):
    import time
    from dataclasses import replace
    import video_assembler as va
    monkeypatch.setattr(va, "_search_and_download_filling_duration", lambda *a, **k: [])
    a = _clipe(tmp_path / "a.mp4")
    audio = _audio(tmp_path / "n.wav", 2)
    work = str(tmp_path / "w")
    va.assemble_video([_seg(0, a)], audio, str(tmp_path / "o.mp4"), work, site_cfg=CFG)
    norm = []
    orig = va._normalize_clip
    monkeypatch.setattr(va, "_normalize_clip", lambda *x, **k: norm.append(1) or orig(*x, **k))
    va.assemble_video([replace(_seg(0, a), on_screen_text="OLÁ")], audio, str(tmp_path / "o.mp4"), work, site_cfg=CFG)
    assert norm == [1]  # texto novo -> refaz
    time.sleep(1.1)
    _clipe(tmp_path / "a.mp4", "yellow", 3)  # mesmo caminho, outro conteúdo
    va.assemble_video([replace(_seg(0, a), on_screen_text="OLÁ")], audio, str(tmp_path / "o.mp4"), work, site_cfg=CFG)
    assert norm == [1, 1]
    va.assemble_video([replace(_seg(0, a), on_screen_text="OLÁ")], audio, str(tmp_path / "o.mp4"), work,
                      site_cfg=dict(CFG, reaproveitar_clipes_prontos=False))
    assert norm == [1, 1, 1]


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_checagem_antes_de_montar_acha_tudo_de_uma_vez(A, tmp_path, monkeypatch):
    import video_assembler as va
    jid = "verif-1"
    os.makedirs(A._job_dir(jid), exist_ok=True)
    bom = _clipe(tmp_path / "ok.mp4")
    lixo = tmp_path / "lixo.mp4"
    lixo.write_bytes(b"<html>erro</html>")
    segs = [
        {"start": 0.0, "end": 2.0, "provider": "pexels", "query": "a", "media_type": "video", "override_source": {"source": "local_file", "value": bom}},
        {"start": 2.0, "end": 4.0, "provider": "pexels", "query": "b", "media_type": "video", "override_source": {"source": "local_file", "value": "/nao/existe.mp4"}},
        {"start": 4.0, "end": 6.0, "provider": "pexels", "query": "c", "media_type": "video", "override_source": {"source": "local_file", "value": str(lixo)}},
        {"start": 6.0, "end": 8.0, "provider": "pexels", "query": "", "media_type": "video", "override_source": None},
        {"start": 8.0, "end": 10.0, "provider": "pexels", "query": "d", "media_type": "video",
         "override_source": {"source": "url", "value": "https://x.com/quebrado.mp4", "kind": "video"}},
        {"start": 10.0, "end": 12.0, "provider": "magnific", "query": "e", "media_type": "video",
         "override_source": {"source": "provider_url", "provider": "magnific", "value": "https://magnific.com/x"}},
        {"start": 12.0, "end": 14.0, "provider": "pexels", "query": "f", "media_type": "video", "override_source": None, "template": "nao_existe_xyz"},
        {"start": 14.0, "end": 16.0, "provider": "pexels", "query": "g", "media_type": "video",
         "override_source": {"source": "url", "value": "https://x.com/bom.mp4", "kind": "video"}},
    ]
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "providers": ["pexels"], "total_duration": 16.0,
                    "pending_segments": segs, "segment_previews": [None] * len(segs), "audio_path": _audio(tmp_path / "n.wav", 1)}

    def _resolver(ov, destino, gc):
        if "quebrado" in ov["value"]:
            raise va.VideoAssemblyError("404")
        p = os.path.join(destino, "x.mp4")
        open(p, "wb").write(b"x" * 10)
        return p, "video"
    monkeypatch.setattr(va, "_resolve_override_source", _resolver)
    d = A.app.test_client().post(f"/job/{jid}/verificar-montagem").get_json()
    com_erro = sorted({p["trecho"] for p in d["problemas"] if p["tipo"] == "erro"})
    assert com_erro == [2, 3, 4, 5, 6, 7], d
    assert not d["ok"] and d["erros"] == 6
    # o link bom já ficou baixado pra montagem
    assert va.prebaixado(segs[7]["override_source"], os.path.join(A._job_dir(jid), "prebaixados"))


def test_checagem_tudo_certo(A, tmp_path):
    jid = "verif-2"
    os.makedirs(A._job_dir(jid), exist_ok=True)
    bom = _clipe(tmp_path / "ok.mp4")
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "providers": ["pexels"], "total_duration": 2.0,
                    "pending_segments": [{"start": 0.0, "end": 2.0, "provider": "pexels", "query": "a", "media_type": "video",
                                          "override_source": {"source": "local_file", "value": bom}}],
                    "segment_previews": [None], "audio_path": _audio(tmp_path / "n.wav", 1)}
    d = A.app.test_client().post(f"/job/{jid}/verificar-montagem").get_json()
    assert d["ok"] and d["erros"] == 0
