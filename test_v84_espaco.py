"""v84_64 — 🧹 Espaço em disco: total, categorias, itens e apagar (um, vários, a categoria, tudo)."""
import os

import pytest

import espaco as es


def _arq(caminho, n=1000):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "wb") as f:
        f.write(b"x" * n)


@pytest.fixture
def base(tmp_path):
    b = str(tmp_path)
    _arq(f"{b}/jobs/aaa/state.json", 100)
    _arq(f"{b}/jobs/aaa/narracao.wav", 5000)
    _arq(f"{b}/jobs/aaa/prebaixados/x/c.mp4", 20000)
    _arq(f"{b}/jobs/aaa/clips_prontos/s.mp4", 10000)
    _arq(f"{b}/jobs/aaa/_concat_video_only.mp4", 3000)
    _arq(f"{b}/jobs/bbb/state.json", 100)
    _arq(f"{b}/jobs/bbb/clips/s.mp4", 7000)
    _arq(f"{b}/outputs/aaa.mp4", 40000)
    _arq(f"{b}/outputs/aaa_legendado.mp4", 40000)
    _arq(f"{b}/outputs/vozes/v1.wav", 8000)
    _arq(f"{b}/dossies/p1/projeto.json", 1500)
    _arq(f"{b}/ia_cache/ab.json", 300)
    _arq(f"{b}/toolkit/tts/models/perfis_de_voz/eu.wav", 9000)
    _arq(f"{b}/flow_dados/sessao.json", 200)
    _arq(f"{b}/__pycache__/app.cpython-313.pyc", 400)
    _arq(f"{b}/app.py", 50)
    return b


def _ctx(base, ocupados=()):
    jobs = {"aaa": {"nome_projeto": "Meu vídeo", "status": "pronto_para_editar"},
            "bbb": {"status": "montando" if "bbb" in ocupados else "concluido"}}
    apagados = []

    def _apagar(jid):
        apagados.append(jid)
        import shutil
        shutil.rmtree(os.path.join(base, "jobs", jid), ignore_errors=True)
        for n in os.listdir(os.path.join(base, "outputs")):
            if n.startswith(jid) and os.path.isfile(os.path.join(base, "outputs", n)):
                os.remove(os.path.join(base, "outputs", n))
    c = es.Contexto(base, jobs, lambda j: j.get("status") in ("montando", "transcrevendo"), apagar_projeto=_apagar)
    c.apagados = apagados
    return c


def test_resumo_e_itens(base):
    ctx = _ctx(base)
    r = es.resumo(ctx)
    cats = {c["id"]: c for c in r["categorias"]}
    assert cats["projetos"]["bytes"] == 100 + 5000 + 20000 + 10000 + 3000 + 100 + 7000 + 80000
    assert cats["caches"]["bytes"] == 20000 + 10000 + 3000 + 7000
    assert cats["saidas"]["bytes"] == 8000  # os vídeos finais contam no projeto, não aqui
    assert cats["modelos_voz"]["protegido"] and cats["ia_cache"]["regeneravel"]
    assert cats["python"]["bytes"] == 400
    assert r["total"] == sum(c["bytes"] for c in r["categorias"] if c["id"] != "caches")
    proj = es.itens(ctx, "projetos")
    assert proj[0]["id"] == "aaa" and proj[0]["nome"] == "Meu vídeo" and "vídeo final" in proj[0]["detalhe"]


def test_apagar_so_os_caches_mantem_o_projeto(base):
    ctx = _ctx(base)
    b = es.apagar_item(ctx, "caches", "aaa")
    assert b == 33000
    assert os.path.exists(f"{base}/jobs/aaa/state.json") and os.path.exists(f"{base}/jobs/aaa/narracao.wav")
    assert not os.path.exists(f"{base}/jobs/aaa/prebaixados") and not os.path.exists(f"{base}/jobs/aaa/_concat_video_only.mp4")
    assert os.path.exists(f"{base}/outputs/aaa.mp4")


def test_apagar_projeto_tira_da_galeria_e_os_finais(base):
    ctx = _ctx(base)
    es.apagar_item(ctx, "projetos", "aaa")
    assert ctx.apagados == ["aaa"] and not os.path.exists(f"{base}/jobs/aaa") and not os.path.exists(f"{base}/outputs/aaa.mp4")
    assert os.path.exists(f"{base}/outputs/vozes/v1.wav")


def test_projeto_em_andamento_nao_e_apagado(base):
    ctx = _ctx(base, ocupados=("bbb",))
    with pytest.raises(es.EspacoError):
        es.apagar_item(ctx, "projetos", "bbb")
    with pytest.raises(es.EspacoError):
        es.apagar_item(ctx, "caches", "bbb")
    r = es.apagar_categoria(ctx, "projetos")
    assert r["apagados"] == 1 and any("bbb" in p or p for p in r["pulados"]) and os.path.exists(f"{base}/jobs/bbb")


def test_nao_sai_da_pasta(base):
    ctx = _ctx(base)
    for ruim in ("../app.py", "..", "/etc/passwd", "a/../../app.py", ""):
        with pytest.raises(es.EspacoError):
            es.apagar_item(ctx, "dossies", ruim)
    with pytest.raises(es.EspacoError):
        es.apagar_item(ctx, "python", "app.py")
    assert os.path.exists(f"{base}/app.py")


def test_protegidas_ficam_fora_do_apagar_tudo(base):
    ctx = _ctx(base)
    with pytest.raises(es.EspacoError):
        es.apagar_categoria(ctx, "modelos_voz")
    r = es.apagar_tudo(ctx)
    assert r["liberado"] > 0
    assert os.path.exists(f"{base}/toolkit/tts/models/perfis_de_voz/eu.wav") and os.path.exists(f"{base}/flow_dados/sessao.json")
    assert os.path.exists(f"{base}/app.py")
    assert not os.listdir(f"{base}/dossies") and not os.listdir(f"{base}/jobs") and not os.path.exists(f"{base}/__pycache__")
    # item a item a protegida pode
    assert es.apagar_item(ctx, "modelos_voz", "perfis_de_voz") == 9000


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_rotas(A, tmp_path, monkeypatch):
    base = str(tmp_path)
    _arq(f"{base}/dossies/p1/projeto.json", 1500)
    _arq(f"{base}/dossies/p2/projeto.json", 2500)
    _arq(f"{base}/ia_cache/ab.json", 300)
    import espaco
    real = espaco.Contexto
    monkeypatch.setattr(espaco, "Contexto", lambda b, jobs=None, em_andamento=lambda j: False, apagar_projeto=None:
                        real(base, {}, em_andamento, apagar_projeto))
    c = A.app.test_client()
    html = c.get("/espaco").get_data(as_text=True)
    assert "Espaço em disco" in html and "Modelos de vídeo" in html and "Apagar tudo" in html
    assert "p2" in c.get("/espaco/dossies").get_data(as_text=True)
    assert c.get("/espaco/naoexiste").status_code == 404
    d = c.post("/espaco/dossies/apagar", json={"ids": ["p1", "../x"]}).get_json()
    assert d["apagados"] == 1 and d["pulados"] and not os.path.exists(f"{base}/dossies/p1")
    assert c.post("/espaco/ia_cache/apagar", json={"tudo": True}).get_json()["liberado"] == 300
    assert c.post("/espaco/modelos_voz/apagar", json={"tudo": True}).status_code == 400
    assert c.post("/espaco/apagar-tudo", json={"confirmar": "sim"}).status_code == 400
    d = c.post("/espaco/apagar-tudo", json={"confirmar": "APAGAR"}).get_json()
    assert d["ok"] and not os.path.exists(f"{base}/dossies/p2")
