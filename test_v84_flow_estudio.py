"""v84_76 — 🎬 aba Google Flow: gerar pelo site (navegador fica aberto, mesmo projeto), 🖼 galeria e 🧪 testar o Flow.
Roda contra o Flow SIMULADO (toolkit/googleflow/flow_simulado, montado com o HTML real)."""
import io
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))


def _chromium_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    import app as A
    import flow_estudio as FE
    from googleflow import googleflow_client as gf
    A.app.config["TESTING"] = True
    monkeypatch.setitem(FE._BASE, "dir", str(tmp_path))
    monkeypatch.setattr(gf, "pasta_dados", lambda: tmp_path / "flow_dados")
    yield A.app.test_client(), FE, gf, tmp_path
    FE.fechar_navegador()
    for _ in range(100):
        if not FE._SESSAO_INFO["aberto"]:
            break
        time.sleep(0.1)


def test_rotas_sem_navegador(ctx):
    c, FE, _gf, tmp = ctx
    assert c.get("/flow").status_code == 200
    assert c.get("/flow/teste").headers["Location"].endswith("/flow#teste")
    r = c.post("/flow/iniciar", data={"modo": "gerar", "prompt": "  "})
    assert r.status_code == 400 and "prompt" in r.get_json()["erro"]
    r = c.post("/flow/iniciar", data={"modo": "gerar", "prompt": "x", "referencia": (io.BytesIO(b"x"), "a.exe")},
               content_type="multipart/form-data")
    assert r.status_code == 400
    assert c.post("/flow/iniciar", data={"modo": "gerar", "prompt": "x", "inicio_galeria": "nao-existe"}).status_code == 400
    FE.adicionar_na_galeria({"id": "g1", "tipo": "imagem", "arquivo": "g1.png", "prompt": "um farol", "criado": 1})
    (tmp / "outputs" / "flow_estudio" / "g1.png").write_bytes(b"png")
    assert c.get("/flow/galeria?q=farol").get_json()["total"] == 1
    assert c.get("/flow/galeria?tipo=video").get_json()["total"] == 0
    assert c.get("/flow/arquivo/g1.png").data == b"png"
    assert c.get("/flow/arquivo/galeria.json").status_code == 400
    assert c.get("/flow/passo/..%2Fx.jpg").status_code in (400, 404)
    assert c.post("/flow/galeria/g1/apagar").get_json()["ok"]
    assert not (tmp / "outputs" / "flow_estudio" / "g1.png").exists()
    assert c.post("/flow/galeria/g1/apagar").status_code == 404


def _esperar(c, limite=120):
    for _ in range(limite * 5):
        d = c.get("/flow/status").get_json()
        if not d["rodando"]:
            return d
        time.sleep(0.2)
    raise AssertionError("não terminou")


@pytest.mark.skipif(not _chromium_ok(), reason="Playwright/Chromium não instalado")
def test_testar_gerar_animar_e_fechar(ctx, monkeypatch):
    c, FE, gf, tmp = ctx
    from googleflow.flow_simulado import simulador
    url, parar = simulador.iniciar()
    try:
        monkeypatch.setattr(gf, "FLOW_URL", url)
        monkeypatch.setattr(gf, "_abrir", lambda p, cfg, headless, conta="x": (
            p.chromium.launch(headless=True).new_context(viewport={"width": 1400, "height": 900}), True))
        for nome in ("salvar_sessao", "restaurar_sessao"):
            monkeypatch.setattr(gf, nome, lambda *a, **k: None)
        # 🧪 teste completo: foto + vídeo + vídeo com Início/Fim, tudo na galeria
        assert c.post("/flow/iniciar", data={"modo": "teste", "visivel": "on"}).get_json()["ok"]
        assert c.post("/flow/iniciar", data={"modo": "teste"}).status_code == 409  # um de cada vez
        d = _esperar(c)
        assert d["erro"] is None, d
        assert [r["rotulo"] for r in d["resultados"]] == ["foto", "video_texto", "video_frames"]
        assert all(p["estado"] == "ok" for p in d["passos"]) and any(p["foto"] for p in d["passos"])
        assert d["sessao"]["aberto"] and gf._FLOW_LOCK.locked()  # o navegador ficou aberto (e o Flow reservado)
        # ✨ gerar 2 imagens no MESMO projeto
        assert c.post("/flow/iniciar", data={"modo": "gerar", "tipo": "imagem", "prompt": "a lighthouse", "quantidade": "x2", "visivel": "on",
                                             "modelo": "Nano Banana Pro"}).get_json()["ok"]
        d = _esperar(c)
        assert d["erro"] is None and len(d["resultados"]) == 2
        assert d["passos"][0]["nome"] == "projeto"  # reaproveitou o projeto aberto
        gal = c.get("/flow/galeria").get_json()
        assert gal["total"] == 5
        img = next(e for e in gal["itens"] if e["prompt"] == "a lighthouse")
        # 🎬 animar a imagem da galeria: está no projeto → usa a própria imagem do Flow (sem enviar)
        assert c.post("/flow/iniciar", data={"modo": "gerar", "tipo": "imagem", "prompt": "slow push in", "visivel": "on",
                                             "inicio_galeria": img["id"]}).get_json()["ok"]
        d = _esperar(c)
        assert d["erro"] is None and d["resultados"][0]["tipo"] == "video" and d["resultados"][0]["frames"]
        assert next(p for p in d["passos"] if p["nome"] == "frame_inicio")["detalhe"] == "imagem do projeto"
        # ✖ fechar → libera o Flow pro resto do site
        assert c.post("/flow/fechar").get_json()["ok"]
        for _ in range(100):
            if not gf._FLOW_LOCK.locked():
                break
            time.sleep(0.1)
        assert not gf._FLOW_LOCK.locked() and not c.get("/flow/status").get_json()["sessao"]["aberto"]
    finally:
        parar()


@pytest.mark.skipif(not _chromium_ok(), reason="Playwright/Chromium não instalado")
def test_limite_marca_conta_e_fecha_projeto(ctx, monkeypatch):
    c, FE, gf, tmp = ctx
    from googleflow.flow_simulado import simulador
    url, parar = simulador.iniciar()
    marcadas = []
    try:
        monkeypatch.setattr(gf, "FLOW_URL", url + "?limite=1")
        monkeypatch.setattr(gf, "_abrir", lambda p, cfg, headless, conta="x": (
            p.chromium.launch(headless=True).new_context(viewport={"width": 1400, "height": 900}), True))
        for nome in ("salvar_sessao", "restaurar_sessao"):
            monkeypatch.setattr(gf, nome, lambda *a, **k: None)
        monkeypatch.setattr(gf, "marcar_esgotada", lambda conta, horas=24, tipo=None: marcadas.append(conta))
        c.post("/flow/iniciar", data={"modo": "gerar", "prompt": "x y", "conta": "principal"})
        d = _esperar(c)
        assert "limite" in d["erro"].lower() and "esgotada" in d["erro"] and marcadas == ["principal"]
        assert d["sessao"]["projeto"] is None
    finally:
        parar()


@pytest.mark.skipif(not _chromium_ok(), reason="Playwright/Chromium não instalado")
def test_erro_guarda_diagnostico_pra_baixar_e_copiar(ctx, monkeypatch):
    import zipfile
    c, FE, gf, tmp = ctx
    from googleflow.flow_simulado import simulador
    url, parar = simulador.iniciar()
    try:
        monkeypatch.setattr(gf, "FLOW_URL", url + "?semcaixa=1")
        monkeypatch.setattr(gf, "_abrir", lambda p, cfg, headless, conta="x": (
            p.chromium.launch(headless=True).new_context(viewport={"width": 1400, "height": 900}), True))
        for nome in ("salvar_sessao", "restaurar_sessao"):
            monkeypatch.setattr(gf, nome, lambda *a, **k: None)
        c.post("/flow/iniciar", data={"modo": "teste"})
        d = _esperar(c, 180)
        assert "novo_projeto" in d["erro"] and d["diagnostico"]
        dg = d["diagnostico"]
        z = zipfile.ZipFile(io.BytesIO(c.get(f"/flow/diagnostico/{dg}/zip").data))
        assert sorted(n.split(dg)[1] for n in z.namelist()) == [".png", ".txt", "_html.txt", "_pagina.html"]
        html = c.get(f"/flow/diagnostico/{dg}/html").get_data(as_text=True)
        assert "flow-prompt-box" in html and "example.com" not in html
        assert c.get(f"/flow/diagnostico/{dg}/foto").mimetype == "image/png"
        assert c.get("/flow/diagnosticos").get_json()["itens"][0]["id"] == dg
        assert c.get("/flow/diagnostico/..%2F..%2Fx/zip").status_code in (400, 404)
        assert c.get("/flow/diagnostico/20990101_000000_000000/zip").status_code == 404
    finally:
        parar()


def test_sem_creditos_troca_de_conta_e_refaz(ctx, monkeypatch):
    """v84_104: a conta ficou sem créditos no meio (ex.: vídeo) → marca esgotada, abre a próxima conta e refaz o MESMO
    pedido; a mídia do projeto antigo (media_id) vira o arquivo reenviado."""
    _c, FE, gf, tmp = ctx
    from googleflow import flow_direto as fd
    s = FE._Sessao()
    s.conta, s.page = "principal", object()
    chamadas, marcadas, abertas = [], [], []

    def gerar_um(page, trab, on_passo, timeout):
        chamadas.append((s.conta, dict(trab)))
        if s.conta == "principal":
            raise fd.FlowLimite("gerar", 'a conta está SEM CRÉDITOS pra isso (“Alerta de créditos insuficientes”).')
        return [{"id": "m1", "url": "https://x/video/m1", "tipo": "video"}]
    monkeypatch.setattr(fd, "gerar_um", gerar_um)
    monkeypatch.setattr(gf, "marcar_esgotada", lambda nome, horas=24, tipo=None: marcadas.append((nome, tipo)))
    monkeypatch.setattr(gf, "escolher_conta_disponivel", lambda **k: "reserva")
    monkeypatch.setattr(gf, "salvar_diagnostico", lambda *a, **k: None)

    def garantir_nav(cfg, visivel, conta):
        abertas.append(conta)
        s.conta = conta
    monkeypatch.setattr(s, "_garantir_navegador", garantir_nav)
    monkeypatch.setattr(s, "_garantir_projeto", lambda cfg, novo, on_passo, atual: setattr(s, "page", object()))
    passos = []
    trab = {"tipo": "video", "prompt": "lago", "inicio": {"media_id": "velho", "arquivo": "/tmp/a.png"}}
    r = s._gerar(trab, {}, {"visivel": False}, lambda n, e, d: passos.append((n, e, d)), {}, 30)
    assert r[0]["id"] == "m1" and marcadas == [("principal", "video")] and abertas == ["reserva"]  # só o vídeo
    assert chamadas[1][0] == "reserva" and chamadas[1][1]["inicio"] == {"arquivo": "/tmp/a.png"}
    assert any("trocando pra “reserva”" in d for n, e, d in passos if n == "conta")
    # sem outra conta: o erro diz isso
    s.conta = "principal"
    monkeypatch.setattr(gf, "escolher_conta_disponivel", lambda **k: (_ for _ in ()).throw(gf.GoogleFlowSemContas("todas esgotadas")))
    with pytest.raises(fd.FlowLimite) as e:
        s._gerar({"tipo": "video", "prompt": "x"}, {}, {}, lambda *a: None, {}, 30)
    assert "não sobrou outra conta" in e.value.mensagem
    # opção desligada: não troca
    s.conta = "principal"
    monkeypatch.setattr(gf, "escolher_conta_disponivel", lambda **k: "reserva")
    with pytest.raises(fd.FlowLimite):
        s._gerar({"tipo": "video", "prompt": "x"}, {}, {"trocar_conta": False}, lambda *a: None, {}, 30)


def test_o_que_o_site_gera_no_flow_vai_pra_galeria(ctx, monkeypatch):
    """v84_106: imagem/vídeo gerado no Flow PRO VÍDEO (não pela aba) também entra na 🖼 galeria (uma cópia, sem repetir)."""
    c, FE, gf, tmp = ctx
    pasta = tmp / "flow_imgs"
    pasta.mkdir()
    monkeypatch.setattr(gf, "pasta_imagens", lambda: pasta)
    (pasta / "flow_abc_1.png").write_bytes(b"png")
    (pasta / "flow_def_1.mp4").write_bytes(b"mp4" * 400)
    assert FE.guardar_da_geracao in gf.AO_SALVAR
    regs = [{"arquivo": "flow_abc_1.png", "prompt": "uma maçã", "chave": "abc", "indice": 1},
            {"arquivo": "flow_def_1.mp4", "prompt": "um lago", "chave": "def", "indice": 1, "tipo": "video"}]
    gf._avisar_salvo(regs)
    gf._avisar_salvo(regs)  # de novo: não duplica
    g = FE.galeria()
    assert len(g) == 2 and {e["tipo"] for e in g} == {"imagem", "video"} and all(e["origem"] == "video" for e in g)
    assert all((tmp / "outputs" / "flow_estudio" / e["arquivo"]).exists() for e in g)
    assert (pasta / "flow_abc_1.png").exists()  # o cache do site continua com o arquivo
    assert "gerado pra um vídeo" in c.get("/flow").get_data(as_text=True)
