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


def test_voz_tenta_de_novo_quando_o_motor_trava(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    p = CT.criar(base, "", "x", texto="y", modelo="explicativo")
    with CT._TRAVA:
        q = CT.carregar(base, p["id"])
        q["roteiro"] = CT.ler_roteiro({"blocos": [{"fala": "uma frase curta"}, {"fala": "outra frase"}]}, q)
        CT.salvar(base, q)
    falhas = {"n": 0}

    def tts(motor, texto, saida, **kw):
        if texto.startswith("outra") and falhas["n"] < 2:  # trava 2 vezes no 2º bloco
            falhas["n"] += 1
            raise RuntimeError("O motor de voz travou o processo (código de saída 3221225477)")
        _tts(motor, texto, saida)
    monkeypatch.setattr(CT.time, "sleep", lambda s: None)
    logs = []
    info = CT.gerar_voz_guia(base, p["id"], tts, lambda t, m: t, {"slug": "v", "motor": "chatterbox_turbo", "config": {}}, on_log=logs.append)
    assert falhas["n"] == 2 and len(info["por_bloco"]) == 2 and any("tentando de novo (3/3)" in m for m in logs)
    falhas["n"] = -10  # trava sempre: aí sim desiste, com o erro do motor
    with CT._TRAVA:  # (v84_301: os blocos já gerados são reaproveitados — falas novas pra precisar do motor de novo)
        q = CT.carregar(base, p["id"])
        q["roteiro"] = CT.ler_roteiro({"blocos": [{"fala": "uma frase nova"}, {"fala": "outra nova"}]}, q)
        CT.salvar(base, q)

    def sempre(motor, texto, saida, **kw):
        raise RuntimeError("crash nativo")
    with pytest.raises(RuntimeError, match="crash nativo"):
        CT.gerar_voz_guia(base, p["id"], sempre, lambda t, m: t, {"slug": "v", "motor": "chatterbox_turbo", "config": {}})


# ------------------------------------------------------------------ v84_261: só Flow (nada da internet), parar e retomar sozinho
def test_so_flow_nao_pesquisa_na_internet(tmp_path, monkeypatch):
    import video_assembler as VA
    seg = VA.VideoSegment(start=0, end=2, provider="flow", query="a hognose snake flipping on its back", media_type="image")
    chamou_pesquisa = []
    monkeypatch.setattr(VA, "prefetch_browser_images", lambda *a, **k: chamou_pesquisa.append(1) or {})
    monkeypatch.setattr(VA, "flow_tem_conta", lambda tipo, cfg=None: False)
    monkeypatch.setattr(VA, "flow_ja_gerado", lambda *a, **k: False)
    cfg = {"flow_sem_pesquisa": True, "_providers_marcados": ["flow", "pexels", "brave"], "flow_espera_s": 0}
    with pytest.raises(VA.VideoAssemblyError, match="crédito de IMAGEM"):
        VA._pesquisa_no_lugar_do_flow(seg, str(tmp_path), None, cfg, ["pexels", "brave"])
    monkeypatch.setattr(VA, "flow_tem_conta", lambda tipo, cfg=None: None)
    tent = []

    def gera(segment, d, f, used_tracker=None):
        tent.append(segment.provider)
        if len(tent) < 3:
            raise VA.VideoAssemblyError("o Flow demorou")
        return str(tmp_path / "flow.png")
    monkeypatch.setattr(VA, "_download_image_segment_with_fallbacks", gera)
    assert VA._pesquisa_no_lugar_do_flow(seg, str(tmp_path), None, cfg, ["pexels"]) == ([str(tmp_path / "flow.png")], "image")
    assert tent == ["flow"] * 3 and not chamou_pesquisa
    tent.clear()
    monkeypatch.setattr(VA, "_download_image_segment_with_fallbacks", lambda *a, **k: (_ for _ in ()).throw(VA.VideoAssemblyError("x")))
    with pytest.raises(VA.VideoAssemblyError, match="não usa foto da internet"):
        VA._pesquisa_no_lugar_do_flow(seg, str(tmp_path), None, cfg, ["pexels"])
    assert not chamou_pesquisa


def test_projeto_flow_vai_pro_editor_so_com_flow(cliente, monkeypatch, tmp_path):
    A, cl, base = cliente
    c = CN.criar_canal_do_nicho(base, "shape_reason")
    p = CT.criar(base, c["id"], "Manhole", texto="tampa redonda", modelo="explicativo")
    with CT._TRAVA:
        q = CT.carregar(base, p["id"])
        q["config"].update(midia="flow", providers=["pexels", "brave", "flow", "google"])
        CT.salvar(base, q)
    CC.gerar_roteiro(base, p["id"], _ia(ROTEIRO_FLOW))
    CC.gerar_takes(base, p["id"], _tts, lambda t, m: t, {"slug": "v", "motor": "chatterbox_turbo", "config": {}}, 1)
    CC.usar_take(base, p["id"], 1, _whisper(base, p["id"]))
    d = CT.montar_dados_editor(base, p["id"])
    assert d["so_flow"] and d["providers"] == ["flow"] and all(x["provider"] == "flow" for x in d["planos"])
    r = cl.post(f"/curtos/{p['id']}/editor", json={}).get_json()
    job = A._JOBS[r["job_id"]]
    assert job["providers"] == ["flow"] and job["cfg_overrides"]["flow_sem_pesquisa"] is True
    assert A._job_site_cfg(job)["flow_sem_pesquisa"] is True and A._job_site_cfg(job)["_providers_marcados"] == ["flow"]


def test_parar_e_lote_pendente(cliente, monkeypatch, tmp_path):
    A, cl, base = cliente
    import curtos_rotas as R
    import threading
    c = CN.criar_canal_do_nicho(base, "saved_by_design")
    CN.gerar_ideias(base, c["id"], 10, _ia(IDEIAS))
    pode = threading.Event()

    def gerar(b, pid, chamar=None):  # o 1º vídeo fica "pensando" até a gente parar
        pode.wait(5)
        raise CT.CurtoErro("não chegou a fazer")
    monkeypatch.setattr(CC, "gerar_roteiro", gerar)
    monkeypatch.setitem(R.CB, "tts", _tts)
    r = cl.post(f"/curtos/canal/{c['id']}/rapido", json={"ideias": "todas"}).get_json()
    lid = r["lote"]
    import time as _t
    _t.sleep(0.3)
    assert cl.post(f"/curtos/lote/{lid}/parar", json={}).get_json()["ok"]
    pode.set()
    t = _esperar("lote:" + lid)
    assert "parado" in t["msg"]
    lt = CN.carregar_lote(base, lid)
    assert lt["parado"] and not lt["fim"] and all(x["estado"] == "na fila" for x in lt["itens"])
    assert lid not in [x["id"] for x in CN.lotes_pendentes(base)]  # você parou: o vigia não retoma
    # o site caiu no meio (não foi você): fica pendente pro vigia
    lt.update(parado=False)
    lt["itens"][0]["estado"] = "fazendo"
    CN.salvar_lote(base, lt)
    assert lid in [x["id"] for x in CN.lotes_pendentes(base)]
    # retomar à mão: tenta de novo e o erro conta (até 3 por ideia)
    pode.set()
    assert cl.post(f"/curtos/lote/{lid}/retomar", json={}).get_json()["ok"]
    _esperar("lote:" + lid)
    lt = CN.carregar_lote(base, lid)
    assert all(x["estado"] == "erro" and x["tentativas"] == 3 for x in lt["itens"]) and lt["fim"]
    assert lid not in [x["id"] for x in CN.lotes_pendentes(base)]  # já tentou 3 vezes: não fica tentando pra sempre
