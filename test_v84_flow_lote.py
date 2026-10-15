"""🚀 Flow em massa (aba 🎬 Google Flow → #lote): várias contas em paralelo, cooldown escalonado entre os envios,
sem crédito → a conta fica marcada e o pedido vai pra outra, todas sem crédito de vídeo → vídeo vira foto (prompt
reescrito), e abrir o navegador de uma conta na mão."""
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
    import flow_lote as FL
    from googleflow import googleflow_client as gf
    A.app.config["TESTING"] = True
    monkeypatch.setitem(FE._BASE, "dir", str(tmp_path))
    monkeypatch.setattr(gf, "pasta_dados", lambda: tmp_path / "flow_dados")
    monkeypatch.setattr(gf, "obter_senha", lambda nome: None)
    monkeypatch.setattr(FL, "_LOTE", None)
    monkeypatch.setattr(FL, "_site_cfg", lambda: {"flow_navegador": "chromium", "flow_timeout_seconds": 60})
    for nome in ("salvar_sessao", "restaurar_sessao"):
        monkeypatch.setattr(gf, nome, lambda *a, **k: None)
    monkeypatch.setattr(gf, "salvar_diagnostico", lambda *a, **k: None)
    gf.adicionar_conta("reserva")
    yield A.app.test_client(), FL, FE, gf, tmp_path
    L = FL._LOTE
    if L is not None:
        L.pausar(agora=True)
        for c in list(L.manuais):
            L.concluir_manual(c)
        for _ in range(300):
            if not L.rodando and not L.manuais:
                break
            time.sleep(0.1)
    assert not FL._DONOS, FL._DONOS
    assert not gf._FLOW_LOCK.locked()


def _esperar_fim(FL, limite=180):
    for _ in range(limite * 10):
        if not FL.lote().rodando:
            return FL.lote().estado()
        time.sleep(0.1)
    raise AssertionError("o lote não terminou: " + str(FL.lote().estado()["log"][-5:]))


# ------------------------------------------------------------------ sem navegador
def test_separar_prompts_e_config():
    import flow_lote as FL
    itens = FL.separar_prompts("um farol\n\nvideo: um lago ao amanhecer\nFOTO - um mapa antigo\n   ", "imagem")
    assert itens == [{"prompt": "um farol", "tipo": "imagem"}, {"prompt": "um lago ao amanhecer", "tipo": "video"},
                     {"prompt": "um mapa antigo", "tipo": "imagem"}]
    blocos = FL.separar_prompts("cena 1\ncontinua\n\ncena 2", "video", "bloco")
    assert [b["prompt"] for b in blocos] == ["cena 1 continua", "cena 2"] and all(b["tipo"] == "video" for b in blocos)
    c = FL.normalizar_config({"paralelo": 9, "cooldown_min": 12, "cooldown_max": 3, "visivel": "on", "lixo": 1})
    assert c["paralelo"] == FL.PARALELO_MAX and c["cooldown_max"] == 12 and c["visivel"] is True and "lixo" not in c
    assert FL.normalizar_config({})["paralelo"] == 2 and FL.normalizar_config({})["cooldown_min"] == 5


def test_video_vira_foto_sem_ia(monkeypatch):
    import flow_lote as FL
    import ia_google_rotas as IG
    monkeypatch.setattr(IG, "no_ar", lambda: False)
    r = FL.reescrever_para_foto("Slow cinematic push-in on a calm lake at sunrise, gentle mist, 8 seconds")
    assert r["por"] == "regra"
    p = r["prompt"].lower()
    assert "push-in" not in p and "8 seconds" not in p and "calm lake" in p and "still" in p
    pt = FL.prompt_foto_simples("A câmera se aproxima de um farol na tempestade, câmera lenta")
    assert pt.startswith("Foto:") and "farol" in pt and "câmera lenta" not in pt


def test_video_vira_foto_com_a_ia_do_site(monkeypatch):
    import flow_lote as FL
    import ia_servico
    pedidos = []
    monkeypatch.setattr(ia_servico, "ativo", lambda recurso=None: recurso == "flow_foto")
    monkeypatch.setattr(ia_servico, "chamar", lambda recurso, system, conteudo, **k: pedidos.append((recurso, system)) or
                        "Still photo of a calm lake at sunrise, mist over the water")
    r = FL.reescrever_para_foto("Slow push-in on a calm lake at sunrise")
    assert r == {"prompt": "Still photo of a calm lake at sunrise, mist over the water", "por": "ia_site"}
    assert pedidos[0][0] == "flow_foto" and "FOTO" in pedidos[0][1]
    assert "flow_foto" in ia_servico.RECURSOS


def test_sem_credito_troca_conta_e_video_vira_foto(ctx, monkeypatch):
    """Nenhuma conta tem crédito de vídeo: as duas ficam marcadas SÓ pra vídeo, os vídeos viram foto (regra simples,
    sem IA) e são gerados como imagem; as imagens continuam normais."""
    c, FL, FE, gf, tmp = ctx
    from googleflow import flow_direto as fd
    import ia_google_rotas as IG
    monkeypatch.setattr(IG, "no_ar", lambda: False)

    class _Ctx:
        pages = []

        def close(self):
            pass

    class _Page:
        url = "https://flow/proj"

        def is_closed(self):
            return False

        def close(self):
            pass
    monkeypatch.setattr(gf, "_abrir", lambda p, cfg, headless, conta="x": (_Ctx(), True))
    monkeypatch.setattr(fd, "preparar_projeto", lambda *a, **k: _Page())
    enviados = []

    def gerar_um(page, trab, on_passo, timeout):
        on_passo("gerar", "andando", "")
        enviados.append((time.monotonic(), trab["tipo"], trab["prompt"]))
        if trab["tipo"] == "video":
            raise fd.FlowLimite("gerar", "Alerta de créditos insuficientes")
        return [{"id": "m", "url": "https://x/image/m", "tipo": "imagem"}]
    monkeypatch.setattr(fd, "gerar_um", gerar_um)
    monkeypatch.setattr(FL, "baixar_para_galeria", lambda ctx_, midias, job, conta, projeto="": [
        {"id": job["id"], "arquivo": job["id"] + ".png", "tipo": "imagem"}])
    FL.lote().salvar_config({"paralelo": 2, "cooldown_min": 0.3, "cooldown_max": 0.5})
    r = c.post("/flow/lote/fila", json={"texto": "video: slow push-in on a lake\nvideo: drone shot over a city\num farol\num mapa",
                                        "tipo": "imagem", "iniciar": True})
    assert r.get_json()["adicionados"] == 4
    d = _esperar_fim(FL)
    assert d["contagem"]["ok"] == 4, d["log"]
    convertidos = [j for j in d["fila"] if j["convertido"]]
    assert len(convertidos) == 2 and all(j["tipo"] == "imagem" and j["reescrito_por"] == "regra" for j in convertidos)
    assert all("push-in" not in j["prompt"].lower() and "drone shot" not in j["prompt"].lower() for j in convertidos)
    assert {j["prompt_original"] for j in convertidos} == {"slow push-in on a lake", "drone shot over a city"}
    contas = {x["nome"]: x for x in gf.listar_contas()}
    assert all(contas[n]["esgotada_video"] and not contas[n]["esgotada_imagem"] for n in ("principal", "reserva"))
    # cooldown escalonado: nunca dois envios mais perto que o mínimo
    tempos = sorted(t for t, _, _ in enviados)
    assert all(b - a >= 0.29 for a, b in zip(tempos, tempos[1:])), tempos
    assert "terminou" in d["fim_msg"]


def test_todas_sem_credito_para_e_avisa(ctx, monkeypatch):
    c, FL, FE, gf, tmp = ctx
    for n in ("principal", "reserva"):
        gf.marcar_esgotada(n, 24)
    FL.lote().salvar_config({"converter_para_foto": True})
    FL.lote().adicionar([{"prompt": "um farol", "tipo": "imagem"}])
    assert c.post("/flow/lote/iniciar").get_json()["ok"]
    d = _esperar_fim(FL, 30)
    assert d["contagem"]["pendente"] == 1 and "nenhuma conta com crédito" in d["fim_msg"]
    assert c.post("/flow/lote/iniciar", json={}).status_code == 200  # tenta de novo (continua sem crédito)
    _esperar_fim(FL, 30)


def test_rotas_fila(ctx):
    c, FL, FE, gf, tmp = ctx
    assert c.post("/flow/lote/fila", json={"texto": "  "}).status_code == 400
    assert c.post("/flow/lote/iniciar").status_code == 400  # nada pendente
    c.post("/flow/lote/fila", json={"texto": "a\nb\nc", "tipo": "video", "proporcao": "9:16", "quantidade": "x2"})
    d = c.get("/flow/lote/estado").get_json()
    assert d["total"] == 3 and all(j["tipo"] == "video" and j["proporcao"] == "9:16" and j["quantidade"] == "x2" for j in d["fila"])
    assert {x["nome"] for x in d["contas"]} == {"principal", "reserva"} and d["config"]["paralelo"] == 2
    jid = d["fila"][0]["id"]
    assert c.post(f"/flow/lote/fila/{jid}/remover").get_json()["ok"]
    assert c.get("/flow/lote/estado").get_json()["total"] == 2
    assert c.post("/flow/lote/config", json={"contas": ["reserva"], "cooldown_min": 7}).get_json()["config"]["contas"] == ["reserva"]
    assert FL.lote().contas_do_lote() == ["reserva"]
    # a fila fica salva no disco
    FL._LOTE = None
    assert FL.lote().estado()["total"] == 2 and FL.lote().cfg["cooldown_min"] == 7
    assert c.post("/flow/lote/limpar", json={"quais": "tudo"}).get_json()["removidos"] == 2
    # 🔁 repetir cada prompt N vezes
    assert c.post("/flow/lote/fila", json={"texto": "um farol\num mapa", "repetir": 3}).get_json()["adicionados"] == 6
    # ↺ créditos de volta em todas
    gf.marcar_esgotada("principal", 24, tipo="video")
    gf.marcar_esgotada("reserva", 24)
    assert c.post("/flow/lote/liberar-todas").get_json()["ok"]
    assert not any(x["esgotada_video"] or x["esgotada"] for x in gf.listar_contas())
    assert "Em massa" in c.get("/flow").get_data(as_text=True)


@pytest.mark.skipif(not _chromium_ok(), reason="Playwright/Chromium não instalado")
def test_duas_contas_em_paralelo_no_flow_simulado(ctx, monkeypatch):
    """O caminho de verdade (flow_direto) contra o Flow SIMULADO: 2 contas, cada uma com o próprio navegador e
    projeto; 4 imagens + 1 vídeo vão pra galeria; os envios respeitam o cooldown."""
    c, FL, FE, gf, tmp = ctx
    from googleflow.flow_simulado import simulador
    url, parar = simulador.iniciar()
    abertas = []
    try:
        monkeypatch.setattr(gf, "FLOW_URL", url)

        def abrir(p, cfg, headless, conta="x"):
            abertas.append(conta)
            return p.chromium.launch(headless=True).new_context(viewport={"width": 1400, "height": 900}), True
        monkeypatch.setattr(gf, "_abrir", abrir)
        FL.lote().salvar_config({"paralelo": 2, "cooldown_min": 1.0, "cooldown_max": 1.5})
        c.post("/flow/lote/fila", json={"texto": "a lighthouse\nan old map\na red apple\na kitten\nvideo: a calm lake", "tipo": "imagem"})
        assert c.post("/flow/lote/iniciar").get_json()["ok"]
        assert gf._FLOW_LOCK.locked()
        # enquanto o lote roda, o ✨ Gerar da aba espera
        r = c.post("/flow/iniciar", data={"modo": "gerar", "prompt": "x"})
        assert r.status_code == 409 and "Em massa" in r.get_json()["erro"]
        d = _esperar_fim(FL, 240)
        assert d["contagem"]["ok"] == 5, [(j["estado"], j["erro"]) for j in d["fila"]] + d["log"][-8:]
        assert sorted(set(abertas)) == ["principal", "reserva"]
        assert {j["conta"] for j in d["fila"]} == {"principal", "reserva"}
        gal = c.get("/flow/galeria").get_json()
        assert gal["total"] == 5 and {e["origem"] for e in gal["itens"]} == {"lote"}
        assert sum(1 for e in gal["itens"] if e["tipo"] == "video") == 1
        enviados = [l["t"] for l in d["log"] if "enviou" in l["msg"]]
        assert len(enviados) == 5 and all(b - a >= 0.9 for a, b in zip(enviados, enviados[1:])), enviados
        assert not gf._FLOW_LOCK.locked()  # terminou: libera o Flow pro resto do site
    finally:
        parar()


@pytest.mark.skipif(not _chromium_ok(), reason="Playwright/Chromium não instalado")
def test_abrir_navegador_da_conta_na_mao(ctx, monkeypatch):
    c, FL, FE, gf, tmp = ctx
    from googleflow.flow_simulado import simulador
    url, parar = simulador.iniciar()
    try:
        monkeypatch.setattr(gf, "FLOW_URL", url)
        monkeypatch.setattr(gf, "_abrir", lambda p, cfg, headless, conta="x": (
            p.chromium.launch(headless=True).new_context(), True))
        assert c.post("/flow/lote/contas/naoexiste/abrir").status_code == 400
        assert c.post("/flow/lote/contas/reserva/abrir").get_json()["ok"]
        assert c.post("/flow/lote/contas/reserva/abrir").status_code == 400  # já aberta
        for _ in range(50):
            d = c.get("/flow/lote/estado").get_json()
            if next(x for x in d["contas"] if x["nome"] == "reserva")["manual"]:
                break
            time.sleep(0.1)
        assert d["reservado"] and gf._FLOW_LOCK.locked()
        assert c.post("/flow/iniciar", data={"modo": "gerar", "prompt": "x"}).status_code == 409
        # outra conta ao mesmo tempo também pode
        assert c.post("/flow/lote/contas/principal/abrir", json={"url": url + "?planos=1"}).get_json()["ok"]  # 🔗 outro endereço
        c.post("/flow/lote/contas/reserva/concluir")
        c.post("/flow/lote/contas/principal/concluir")
        for _ in range(100):
            if not FL.lote().manuais:
                break
            time.sleep(0.1)
        assert not FL.lote().manuais and not gf._FLOW_LOCK.locked()
        assert any("sessão salva" in l["msg"] for l in FL.lote().estado()["log"])
    finally:
        parar()
