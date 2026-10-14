"""v84_101 — 📺 Perfis do canal: biblioteca de vídeos de 🎬 intro / 👍 inscreva-se / 🛒 venda / 🏁 final por perfil,
⭐ padrão de cada tipo, perfil ativo, e no editor (✂️ Cortes) o perfil do vídeo + qual vídeo entra em cada item."""
import io
import json
import os
import subprocess

import pytest

import canal
import chamadas as ch
import perfis_canal as pc


def _video(caminho, dur=1.0, cor="red"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={cor}:s=160x90:d={dur}:r=25",
                    "-f", "lavfi", "-i", f"sine=f=440:d={dur}", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(caminho)], check=True)
    return str(caminho)


@pytest.fixture
def pasta(monkeypatch, tmp_path):
    monkeypatch.setattr(ch, "PASTA_PADRAO", str(tmp_path / "padrao"))
    return tmp_path


def test_migra_os_padroes_antigos_sem_gravar(pasta):
    os.makedirs(ch.PASTA_PADRAO)
    antigo = _video(pasta / "padrao" / "venda_old.mp4")
    with open(os.path.join(ch.PASTA_PADRAO, "padrao.json"), "w") as f:
        json.dump({"venda": antigo, "abertura": str(pasta / "sumiu.mp4")}, f)
    assert pc.ativo_id() == "principal" and pc.caminho_padrao("venda") == antigo
    assert pc.caminho_padrao("abertura") is None and not os.path.exists(pc._arquivo())  # só lendo: não grava
    assert ch.clipe_padrao("venda") == antigo


def test_biblioteca_padrao_e_ativo(pasta):
    a = pc.adicionar_video(pc.ativo_id(), "abertura", _video(pasta / "a.mp4"), "Intro A.mp4")
    b = pc.adicionar_video(pc.ativo_id(), "abertura", _video(pasta / "b.mp4", cor="blue"), "Intro B.mp4")
    assert a["nome"] == "Intro A" and a["duracao"] > 0.5 and os.path.dirname(a["arquivo"]).endswith(pc.ativo_id())
    assert pc.caminho_padrao("abertura") == a["arquivo"]  # o 1º do tipo vira padrão
    pc.editar_video(pc.ativo_id(), b["id"], nome="Intro nova", padrao=True)
    assert pc.caminho_padrao("abertura") == b["arquivo"] and [v["nome"] for v in pc.videos("abertura")] == ["Intro A", "Intro nova"]
    pc.apagar_video(pc.ativo_id(), b["id"])
    assert not os.path.exists(b["arquivo"]) and pc.caminho_padrao("abertura") == a["arquivo"]
    # outro perfil, ativo, com o nome do canal
    p2 = pc.criar("Johans Akte", "Johans Akte", ativar=True)
    assert pc.ativo_id() == p2["id"] and canal.nome_global() == "Johans Akte"
    assert pc.caminho_padrao("abertura") is None and pc.caminho_padrao("abertura", "principal") == a["arquivo"]
    # chamadas.definir_padrao vai pro perfil ativo
    novo = ch.definir_padrao("venda", _video(pasta / "v.mp4", cor="green"))
    assert pc.caminho_padrao("venda") == novo and ch.clipe_padrao("venda", "principal") is None
    ch.definir_padrao("venda", None)
    assert ch.clipe_padrao("venda") is None and len(pc.videos("venda")) == 1  # continua na biblioteca
    pc.apagar(p2["id"])
    assert pc.ativo_id() == "principal" and not os.path.isdir(os.path.join(pc.pasta(), p2["id"]))
    with pytest.raises(pc.PerfilErro):
        pc.apagar("principal")  # o único
    with pytest.raises(pc.PerfilErro):
        pc.adicionar_video("principal", "xyz", a["arquivo"])


def test_job_usa_o_perfil_dele(pasta):
    p2 = pc.criar("Outro")
    i1 = pc.adicionar_video("principal", "abertura", _video(pasta / "i1.mp4"), "i1.mp4")
    i2 = pc.adicionar_video("principal", "abertura", _video(pasta / "i2.mp4", cor="blue"), "i2.mp4")
    o = pc.adicionar_video(p2["id"], "abertura", _video(pasta / "o.mp4", cor="green"), "o.mp4")
    job = {}
    v = canal.do_job(job)["abertura"]
    assert v["caminho"] == i1["arquivo"] and v["video_id"] == i1["id"] and len(v["opcoes"]) == 2
    job["vinhetas"] = {"abertura": {"video_id": i2["id"]}}
    assert canal.do_job(job)["abertura"]["caminho"] == i2["arquivo"]
    job["perfil_canal"] = p2["id"]
    job["vinhetas"] = {}
    assert canal.do_job(job)["abertura"]["caminho"] == o["arquivo"]
    assert ch.para_cortes([{"tipo": "venda", "inicio": 1, "fim": 1}], p2["id"])[0]["resolved_path"] is None


# ------------------------------------------------------------------ rotas
@pytest.fixture
def A(pasta, monkeypatch):
    import app as _app
    import site_config
    monkeypatch.setattr(site_config, "CONFIG_PATH", str(pasta / "site_config.json"))
    _app.app.config["TESTING"] = True
    return _app


def test_pagina_e_rotas(A, pasta):
    c = A.app.test_client()
    assert "📺 Perfis do canal" in c.get("/perfis-canal").get_data(as_text=True)
    d = c.get("/perfis-canal/dados").get_json()
    assert d["ordem"] == ["abertura", "inscreva", "venda", "encerramento"] and d["perfis"][0]["ativo"]
    dados = open(_video(pasta / "x.mp4"), "rb").read()
    r = c.post("/perfis-canal/principal/venda/enviar", data={"arquivos": [(io.BytesIO(dados), "venda 1.mp4"), (io.BytesIO(dados), "venda 2.mp4")]},
               content_type="multipart/form-data").get_json()
    vs = r["perfis"][0]["videos"]["venda"]
    assert r["enviados"] == 2 and [v["nome"] for v in vs] == ["venda 1", "venda 2"] and vs[0]["padrao"]
    assert c.get(vs[1]["url"]).status_code == 200
    r = c.post(f"/perfis-canal/principal/video/{vs[1]['id']}", json={"padrao": True}).get_json()
    assert r["perfis"][0]["videos"]["venda"][1]["padrao"]
    r = c.post("/perfis-canal/novo", json={"nome": "Canal 2", "nome_canal": "Canal Zwei"}).get_json()
    novo = r["novo"]
    r = c.post(f"/perfis-canal/{novo}", json={"ativar": True, "nome_canal": "Canal Zwei"}).get_json()
    assert r["ativo"] == novo and canal.nome_global() == "Canal Zwei"
    assert c.post("/perfis-canal/xxx/venda/enviar", data={"arquivos": (io.BytesIO(dados), "a.mp4")},
                  content_type="multipart/form-data").status_code == 400
    assert c.post(f"/perfis-canal/principal/video/{vs[0]['id']}/apagar").get_json()["ok"]
    assert c.post(f"/perfis-canal/{novo}/apagar").get_json()["ativo"] == "principal"


def test_editor_perfil_e_escolhas(A, pasta, monkeypatch):
    v1 = pc.adicionar_video("principal", "venda", _video(pasta / "v1.mp4"), "v1.mp4")
    v2 = pc.adicionar_video("principal", "venda", _video(pasta / "v2.mp4", cor="blue"), "v2.mp4")
    i1 = pc.adicionar_video("principal", "abertura", _video(pasta / "i1.mp4"), "i1.mp4")
    i2 = pc.adicionar_video("principal", "abertura", _video(pasta / "i2.mp4", cor="blue"), "i2.mp4")
    p2 = pc.criar("Outro")
    w = pc.adicionar_video(p2["id"], "venda", _video(pasta / "w.mp4", cor="green"), "w.mp4")
    monkeypatch.setattr(A, "_save_state", lambda *_a, **_k: None)
    monkeypatch.setattr(A, "_job_dir", lambda jid: str(pasta / "jobs" / jid))
    jid = "pc-job"
    A._JOBS[jid] = {"job_id": jid, "pending_segments": [], "cutaway_suggestions": ch.para_cortes(
        [{"tipo": "venda", "inicio": 2, "fim": 2}, {"tipo": "venda", "inicio": 5, "fim": 5}])}
    try:
        c = A.app.test_client()
        cl = A._clipes_do_tipo(A._JOBS[jid], "venda")
        assert [x["caminho"] for x in cl] == [v1["arquivo"], v2["arquivo"]] and cl[0]["padrao"]
        ids = [x["id"] for x in A._JOBS[jid]["cutaway_suggestions"]]
        r = c.post(f"/job/{jid}/chamadas/escolher", json={"tipo": "venda", "escolhas": {ids[0]: cl[1]["id"], ids[1]: cl[0]["id"]}}).get_json()
        assert r["com_clipe"] == 2
        assert [x["resolved_path"] for x in A._JOBS[jid]["cutaway_suggestions"]] == [v2["arquivo"], v1["arquivo"]]
        d = c.post(f"/job/{jid}/vinhetas/abertura", json={"video_id": i2["id"]}).get_json()
        assert d["vinhetas"]["abertura"]["video_id"] == i2["id"] and len(d["vinhetas"]["abertura"]["opcoes"]) == 2
        assert canal.cortes_para_montagem(A._JOBS[jid])[0]["resolved_path"] == i2["arquivo"]
        d = c.post(f"/job/{jid}/vinhetas/abertura", json={"video_id": ""}).get_json()
        assert d["vinhetas"]["abertura"]["video_id"] == i1["id"]
        # trocar o perfil do vídeo: as vendas do perfil velho passam pro padrão do novo
        r = c.post(f"/job/{jid}/perfil-canal", json={"perfil": p2["id"]}).get_json()
        assert r["ok"] and A._JOBS[jid]["perfil_canal"] == p2["id"]
        assert [x["resolved_path"] for x in A._JOBS[jid]["cutaway_suggestions"]] == [w["arquivo"], w["arquivo"]]
        assert not canal.do_job(A._JOBS[jid])["abertura"]["usar"]
        assert c.post(f"/job/{jid}/perfil-canal", json={"perfil": "nada"}).status_code == 404
        # enviar um vídeo de venda no editor guardando no perfil do vídeo
        dados = open(_video(pasta / "z.mp4"), "rb").read()
        c.post(f"/job/{jid}/chamadas/venda/enviar", data={"arquivo": (io.BytesIO(dados), "nova venda.mp4"), "perfil": "on"},
               content_type="multipart/form-data")
        assert [v["nome"] for v in pc.videos("venda", p2["id"])] == ["w", "nova venda"]
    finally:
        A._JOBS.pop(jid, None)
