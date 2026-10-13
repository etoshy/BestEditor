"""v84_74 — 🎬 Flow no modo direto contra o Flow SIMULADO (o HTML de cada tela é o REAL que o usuário capturou)."""
import collections
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from googleflow import flow_direto as fd  # noqa: E402
from googleflow import googleflow_client as g  # noqa: E402
from googleflow.flow_simulado import simulador  # noqa: E402


def _chromium_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _chromium_ok(), reason="Playwright/Chromium não instalado")


@pytest.fixture(scope="module")
def sim():
    url, parar = simulador.iniciar()
    yield url
    parar()


@pytest.fixture
def navegador():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


def _png(tmp_path):
    from PIL import Image
    c = str(tmp_path / "frame_fim.png")
    Image.new("RGB", (320, 180), "green").save(c)
    return c


def test_passo_a_passo_imagem_video_frames_e_simular(sim, navegador, tmp_path):
    ctx = navegador.new_context(viewport={"width": 1400, "height": 900})
    passos = []
    on = lambda n, e, d: passos.append((n, e, d))  # noqa: E731
    page = fd.preparar_projeto(ctx, sim, True, {"img_proporcao": "9:16", "img_modelo": "Nano Banana Pro", "vid_modelo": "Veo 3.1 - Fast"}, on)
    assert [n for n, e, _ in passos if e == "ok"] == ["abrir", "novo_projeto", "config_agente", "desligar_agente"]
    sim_st = page.evaluate("window.__flowSim")
    assert sim_st["agente"] is False
    r = fd.gerar_um(page, {"tipo": "imagem", "prompt": "a red apple on a wooden table", "proporcao": "16:9", "modelo": "Nano Banana 2.1"}, on, 30)
    assert len(r) == 1 and r[0]["tipo"] == "imagem" and "/image/" in r[0]["url"]
    assert page.evaluate("window.__flowSim.modeloImg").endswith("Nano Banana 2.1") and "16:9" in fd.resumo(page)
    v = fd.gerar_um(page, {"tipo": "video", "prompt": "the apple rotates", "modelo": "Veo 3.1 - Lite",
                           "inicio": {"media_id": r[0]["id"]}, "fim": {"arquivo": _png(tmp_path)}}, on, 30)
    assert len(v) == 1 and v[0]["tipo"] == "video" and v[0]["id"] != r[0]["id"]
    ok = {n: d for n, e, d in passos if e == "ok"}
    assert ok["frame_inicio"] == "imagem do projeto" and ok["frame_fim"] == "imagem enviada"
    assert "Vídeo" in ok["configurar"] and "créditos" in ok["configurar"]
    n_antes = len(fd.midias_na_pagina(page))
    assert fd.gerar_um(page, {"tipo": "video", "tipo_video": "Elementos", "prompt": "a cat running", "simular": True}, on, 30) == []
    assert passos[-1][:2] == ("gerar", "pulado") and len(fd.midias_na_pagina(page)) == n_antes  # nada gerado
    ctx.close()


@pytest.mark.parametrize("q,erro,passo", [("?limite=1", fd.FlowLimite, "esperar"), ("?falha=1", fd.FlowRecusou, "esperar"),
                                          ("?login=1", fd.FlowLogin, "abrir")])
def test_erros_com_nome(sim, navegador, q, erro, passo):
    ctx = navegador.new_context(viewport={"width": 1400, "height": 900})
    with pytest.raises(erro) as e:
        page = fd.preparar_projeto(ctx, sim + q, True, None)
        fd.gerar_um(page, {"tipo": "imagem", "prompt": "x y z"}, timeout_s=20)
    assert e.value.passo == passo
    ctx.close()
    assert isinstance(g.erro_do_passo(fd.FlowLimite("esperar", "a")), g.GoogleFlowLimitReached)
    assert isinstance(g.erro_do_passo(fd.FlowLogin("abrir", "a")), g.GoogleFlowLoginRequired)
    assert "passo \"configurar\"" in str(g.erro_do_passo(fd.FlowPassoErro("configurar", "x")))


def test_modelo_que_nao_existe_diz_quais_tem(sim, navegador):
    ctx = navegador.new_context(viewport={"width": 1400, "height": 900})
    page = fd.preparar_projeto(ctx, sim, True, None)
    with pytest.raises(fd.FlowPassoErro) as e:
        fd.configurar_caixa(page, "video", "16:9", "Veo 9 Ultra")
    assert e.value.passo == "configurar" and "Veo 3.1 - Fast" in str(e.value)
    ctx.close()


def _cliente(tmp_path, monkeypatch, sim, **cfg):
    from pathlib import Path
    monkeypatch.setattr(g, "pasta_dados", lambda: Path(tmp_path / "dados"))
    monkeypatch.setattr(g, "FLOW_URL", sim)
    monkeypatch.setattr(g, "escolher_conta_disponivel", lambda *a, **k: "teste")
    for nome in ("salvar_sessao", "restaurar_sessao"):
        monkeypatch.setattr(g, nome, lambda *a, **k: None)
    monkeypatch.setattr(g, "_abrir", lambda p, c, headless, conta="x": (p.chromium.launch(headless=True).new_context(
        viewport={"width": 1400, "height": 900}), True))
    return g.GoogleFlowClient(dict({"browser_visible": False, "orientation": "16:9", "flow_modo_automacao": "direto"}, **cfg))


def test_cliente_pedidos_unicos_no_modo_direto(sim, tmp_path, monkeypatch):
    cli = _cliente(tmp_path, monkeypatch, sim, flow_modelo_imagem="Nano Banana Pro", flow_modelo_video="Veo 3.1 - Fast")
    try:
        fotos = cli.search_photos_all("a lighthouse at night")
        assert fotos and os.path.getsize(fotos[0].local_path) > 500
        assert cli.search_photos_all("a lighthouse at night")[0].local_path == fotos[0].local_path  # cache
        videos = cli.animar_imagem(fotos[0].local_path, "slow push-in", modelo="Omni 1.1 Flash", proporcao="16:9")
        assert videos and videos[0].local_path.endswith(".mp4") and os.path.getsize(videos[0].local_path) > 1000
    finally:
        g.encerrar_sessao()


def test_cliente_lote_duas_abas_no_modo_direto(sim, tmp_path, monkeypatch):
    cli = _cliente(tmp_path, monkeypatch, sim)
    frame = _png(tmp_path)
    try:
        fila = collections.deque([
            cli.preparar_trabalho({"id": "f1", "tipo": "imagem", "prompt": "a dark well", "modelo": "Nano Banana 2.1", "proporcao": "9:16"}),
            cli.preparar_trabalho({"id": "f2", "tipo": "imagem", "prompt": "a girl", "modelo": "Nano Banana 2.1", "proporcao": "9:16"}),
            cli.preparar_trabalho({"id": "a1", "tipo": "animar", "prompt": "slow push-in", "imagem": frame,
                                   "modelo": "Omni 1.1 Flash", "proporcao": "9:16"}),
        ])
        eventos = []

        def _ev(e):
            eventos.append(e)
            if e["tipo"] == "fim" and e["id"] == "f1":
                assert e["media_id"]
                fila.append(cli.preparar_trabalho({"id": "a2", "tipo": "animar", "prompt": "push-in on f1", "imagem": e["arquivo"],
                                                   "media_id": e["media_id"], "modelo": "Omni 1.1 Flash", "proporcao": "9:16"}))
        cli.gerar_lote(fila, abas=2, cooldown=(0.3, 0.6), on_evento=_ev)
        fins = {e["id"]: e for e in eventos if e["tipo"] == "fim"}
        assert set(fins) == {"f1", "f2", "a1", "a2"}, [e for e in eventos if e["tipo"] == "erro"]
        assert fins["a2"]["reaproveitou_frame"] is True and fins["a2"]["aba"] == fins["f1"]["aba"]
        assert fins["a1"]["reaproveitou_frame"] is False and fins["a1"]["arquivo"].endswith(".mp4")
        assert {e["aba"] for e in eventos if e["tipo"] == "inicio"} == {1, 2}
    finally:
        g.encerrar_sessao()


def test_janela_estreita_e_alargada_pra_achar_o_agente(sim, navegador):
    """Janela estreita: o Flow esconde o chip "Agente" (erro real do usuário). A automação alarga a página."""
    ctx = navegador.new_context(viewport={"width": 800, "height": 700})
    page = fd.preparar_projeto(ctx, sim, True, {"img_modelo": "Nano Banana Pro"})
    assert page.evaluate("window.innerWidth") >= fd.LARGURA_MIN
    assert page.evaluate("window.__flowSim")["agente"] is False
    ctx.close()


def test_janela_grande_no_navegador_visivel():
    assert "--window-size=1400,950" in g._args_chromium(False)["args"]
    assert g._args_chromium(True)["viewport"]["width"] >= fd.LARGURA_MIN


def test_projeto_sem_caixa_recarrega_uma_vez(sim, navegador):
    ctx = navegador.new_context(viewport={"width": 1400, "height": 900})
    page = fd.preparar_projeto(ctx, sim + "?semcaixa=1x", True, None)
    assert fd._primeiro(page, fd.S["editor"], 2) is not None
    ctx.close()


def test_projeto_sem_caixa_erro_traz_a_aba_e_diagnostico_sem_dados_pessoais(sim, navegador, tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(g, "pasta_dados", lambda: Path(tmp_path))
    ctx = navegador.new_context(viewport={"width": 1400, "height": 900})
    with pytest.raises(fd.FlowPassoErro) as e:
        fd.preparar_projeto(ctx, sim + "?semcaixa=1", True, None)
    assert e.value.passo == "novo_projeto" and "/project/" in e.value.page.url
    base = g.salvar_diagnostico(e.value.page, str(e.value))
    nomes = sorted(a.name[len(Path(base).name):] for a in g.arquivos_do_diagnostico(Path(base).name))
    assert nomes == [".png", ".txt", "_html.txt", "_pagina.html"]
    tudo = "".join(a.read_text(encoding="utf-8") for a in g.arquivos_do_diagnostico(Path(base).name) if a.suffix != ".png")
    assert "pessoa.teste@example.com" not in tudo and "Pessoa Teste" not in tudo and "FOTO-TESTE" not in tudo
    assert "flow-prompt-box" in tudo
    ctx.close()
