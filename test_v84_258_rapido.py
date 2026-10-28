"""v84_258: ⚡ geração rápida — várias ideias → vídeos 📚 no Flow (foto, ou vídeo enquanto tiver crédito) → exportados sozinhos,
com os títulos e os arquivos pra baixar."""
import json
import os
import subprocess

import pytest

import curtos as CT
import curtos_comentario as CC
import curtos_nichos as CN
from test_v84_253_comentario import _tts, _whisper  # noqa: F401
from test_v84_256_nichos import IDEIAS, ROTEIRO_FLOW, _ia


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "curtos"))
    monkeypatch.setenv("DP_EXTRAS_DIR", str(tmp_path / "extras"))
    import dp_extras
    dp_extras.recarregar()
    import app as A
    import ia_servico
    base = str(tmp_path)
    monkeypatch.setattr(A, "BASE_DIR", base)
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    monkeypatch.setattr(A, "_job_dir", lambda j: os.path.join(base, "jobs", j))
    monkeypatch.setattr(ia_servico, "motivo_desligado", lambda *a, **k: None)
    import anime2d
    monkeypatch.setattr(anime2d, "vozes_disponiveis", lambda mp="xtts": [{"slug": "perfil:teste", "nome": "t", "grupo": "g"}])
    A.app.config["TESTING"] = True
    return A, A.app.test_client(), base


def _esperar(chave, n=1200):
    import time
    import curtos_rotas as R
    for _ in range(n):
        t = R.TAREFAS.get(chave) or {}
        if t.get("fim"):
            return t
        time.sleep(0.05)
    raise AssertionError("a tarefa não terminou")


def test_prompt_modo_foto_e_video(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    p = CT.criar(str(tmp_path), "", "x", texto="y", modelo="explicativo")
    p["config"]["flow_video"] = True
    assert "VIDEO MODE" in CC.sistema(p)
    p["config"]["flow_video"] = False
    assert "PHOTO MODE" in CC.sistema(p)


def test_geracao_rapida_lote(cliente, monkeypatch, tmp_path):
    A, cl, base = cliente
    import curtos_rotas as R
    c = CN.criar_canal_do_nicho(base, "shape_reason")
    CN.gerar_ideias(base, c["id"], 10, _ia(IDEIAS))
    roteiros = []

    def gerar(b, pid, chamar=None):
        roteiros.append(pid)
        return CC_gerar(b, pid, _ia(ROTEIRO_FLOW))
    CC_gerar = CC.gerar_roteiro
    monkeypatch.setattr(CC, "gerar_roteiro", gerar)
    monkeypatch.setitem(R.CB, "tts", _tts)

    def whisper(audio, language=None, word_timestamps=True, info=None):  # lê o roteiro do projeto do último gerado
        return _whisper(base, roteiros[-1])(audio, language, word_timestamps, info)
    monkeypatch.setitem(R.CB, "transcrever", whisper)
    exportados = []

    def exportar(job_id, qualidade, on_log=lambda m: None):
        job = A._JOBS[job_id]
        exportados.append((job_id, qualidade, [(s["provider"], s.get("media_type")) for s in job["pending_segments"]]))
        arq = str(tmp_path / f"{job_id}.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=108x192:d=1", arq], check=True)
        return arq
    monkeypatch.setitem(R.CB, "exportar", exportar)
    ids = [i["id"] for i in CN.ideias(base, c["id"])]
    r = cl.post(f"/curtos/canal/{c['id']}/rapido", json={"ideias": "todas", "video": False, "qualidade": "1440p", "proporcao": "1:1"}).get_json()
    assert r["ok"], r
    t = _esperar("lote:" + r["lote"])
    assert not t["erro"] and t["msg"].startswith("2 de 2"), [x["erro"] for x in CN.carregar_lote(base, r["lote"])["itens"]]
    lt = cl.get(f"/curtos/lote/{r['lote']}").get_json()["lote"]
    assert [x["estado"] for x in lt["itens"]] == ["pronto", "pronto"] and lt["fim"]
    assert all(q == "1440p" for _j, q, _s in exportados)
    assert all(mt == "image" for _j, _q, segs in exportados for _p, mt in segs)  # 🖼 modo foto: o vídeo gerado virou foto
    p = CT.carregar(base, lt["itens"][0]["pid"])
    assert p["config"]["proporcao"] == "1:1" and p["config"]["flow_video"] is False and len(p["takes"]) == 1
    assert lt["itens"][0]["titulos"][0]["pt"]
    txt = cl.get(f"/curtos/lote/{r['lote']}/titulos.txt").get_data(as_text=True)
    assert "Why manhole covers are round" in txt and "Por que a tampa é redonda" in txt
    v = cl.get(f"/curtos/{p['id']}/video.mp4")
    assert v.status_code == 200 and v.headers["Content-Disposition"].startswith("attachment")
    z = cl.get(f"/curtos/lote/{r['lote']}/todos.zip")
    assert z.status_code == 200 and len(z.data) > 500
    assert all(i.get("pid") for i in CN.ideias(base, c["id"]) if i["id"] in ids)
    assert cl.get(f"/curtos/canal/{c['id']}/lotes").get_json()["lotes"][0]["id"] == r["lote"]
    # com vídeo: o 2º plano (ia_video) vai pro Flow como VÍDEO
    CN.gerar_ideias(base, c["id"], 10, _ia({"ideias": [dict(IDEIAS["ideias"][0], titulo_en="Why traffic cones are orange")]}))
    exportados.clear()
    r = cl.post(f"/curtos/canal/{c['id']}/rapido", json={"ideias": "todas", "video": True}).get_json()
    _esperar("lote:" + r["lote"])
    assert exportados and ("flow", "video") in exportados[0][2] and exportados[0][1] == "1080p"


def test_um_erro_nao_para_o_lote(cliente, monkeypatch, tmp_path):
    A, cl, base = cliente
    import curtos_rotas as R
    c = CN.criar_canal_do_nicho(base, "bite_behind_it")
    CN.gerar_ideias(base, c["id"], 10, _ia(IDEIAS))
    monkeypatch.setattr(CC, "gerar_roteiro", lambda *a, **k: (_ for _ in ()).throw(CT.CurtoErro("IA fora do ar")))
    monkeypatch.setitem(R.CB, "tts", _tts)
    r = cl.post(f"/curtos/canal/{c['id']}/rapido", json={"ideias": "todas"}).get_json()
    t = _esperar("lote:" + r["lote"])
    assert t["msg"].startswith("0 de 2")
    lt = CN.carregar_lote(base, r["lote"])
    assert all(x["estado"] == "erro" and "IA fora do ar" in x["erro"] for x in lt["itens"])
    assert cl.post(f"/curtos/lote/{r['lote']}/retomar", json={}).get_json()["ok"]
    _esperar("lote:" + r["lote"])


def test_exportar_sem_abrir_o_editor(cliente, monkeypatch, tmp_path):
    A, _cl, base = cliente
    job_id = "j" + "1" * 11
    A._JOBS[job_id] = {"status": "pronto_para_editar", "pending_segments": [{"start": 0, "end": 1, "provider": "pexels", "query": "x"}],
                       "segment_previews": [None]}
    arq = os.path.join(A.OUTPUTS_DIR, f"{job_id}_legendado.mp4")

    def montar(jid, job, segs):
        assert len(segs) == 1 and job["export_quality"] == "2160p"
        job["status"], job["captioned_output_path"] = "concluido", arq
        open(arq, "wb").write(b"x" * 2000)
    monkeypatch.setattr(A, "_start_assembly", montar)
    try:
        assert A._curto_exportar(job_id, "2160p") == arq
        A._JOBS[job_id].update(status="pronto_para_editar")
        monkeypatch.setattr(A, "_start_assembly", lambda jid, job, segs: job.update(status="pronto_para_editar", assembly_error="trecho 3 falhou"))
        with pytest.raises(RuntimeError, match="trecho 3"):
            A._curto_exportar(job_id, "1080p")
    finally:
        A._JOBS.pop(job_id, None)
        if os.path.isfile(arq):
            os.remove(arq)
