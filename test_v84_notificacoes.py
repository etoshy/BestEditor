"""v84_87 — 🔔 notificações (sininho), ⏳ tarefas de segundo plano genéricas, 🕘 histórico e captcha da IA do Google."""
import importlib
import json
import os
import sys
import threading
import time

import pytest

import notificacoes as nt
import tarefas_bg as tb


@pytest.fixture
def isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "ARQUIVO", str(tmp_path / "notificacoes.json"))
    monkeypatch.setattr(tb, "PASTA", str(tmp_path / "tarefas"))
    return tmp_path


@pytest.fixture
def cliente(isolado, monkeypatch):
    import app as A
    monkeypatch.setattr(nt, "ARQUIVO", str(isolado / "notificacoes.json"))
    monkeypatch.setattr(tb, "PASTA", str(isolado / "tarefas"))
    return A, A.app.test_client()


def test_avisar_chave_resolver_e_links_seguros(isolado):
    a = nt.avisar("✅ pronto", "msg", "/job/x/status-page", "ok", tipo="montagem")
    assert a["link"] == "/job/x/status-page" and nt.nao_lidas() == 1
    for ruim in ("https://mal.com", "//mal.com", "javascript:alert(1)", "/a\\b"):
        assert nt.avisar("x", link=ruim)["link"] == ""
    c1 = nt.avisar("🔒 captcha", link="/ia-google", nivel="aviso", chave="cap")
    c2 = nt.avisar("🔒 captcha de novo", link="/ia-google", nivel="aviso", chave="cap")
    assert c1["id"] == c2["id"] and sum(1 for x in nt.listar() if x["chave"] == "cap") == 1  # não repete
    assert nt.resolver("cap") == 1 and nt.pegar(c1["id"])["lida"]
    assert nt.marcar_lidas([a["id"]]) == 1 and nt.pegar(a["id"])["lida"]
    nt.limpar()
    assert nt.listar() == []


def test_rotas_sino_e_historico(cliente):
    A, c = cliente
    n = nt.avisar("✅ Vídeo “teste” — pronto", "assista", "/historico", "ok")
    d = c.get("/notificacoes").get_json()
    assert d["nao_lidas"] == 1 and d["itens"][0]["titulo"].startswith("✅")
    r = c.get(f"/notificacoes/ir/{n['id']}")
    assert r.status_code == 302 and r.headers["Location"].endswith("/historico")
    assert c.get("/notificacoes").get_json()["nao_lidas"] == 0
    assert c.get("/notificacoes/ir/naoexiste").status_code == 404
    h = c.get("/historico").get_data(as_text=True)
    assert "🕘 Histórico" in h and "Vídeo “teste”" in h and 'id="sinoBtn"' in h  # o sino vem do base.html
    assert c.post("/notificacoes/lidas", json={}).get_json()["ok"]
    assert c.post("/notificacoes/limpar").get_json()["ok"] and nt.listar() == []


def test_sino_no_estudio_e_nas_paginas_avulsas():
    base = os.path.dirname(os.path.abspath(__file__))
    for t in ("estudio.html", "textos.html", "base.html"):
        assert '{% include "_sino.html" %}' in open(os.path.join(base, "templates", t), encoding="utf-8").read()


def test_tarefa_roda_avisa_e_fica_no_historico(isolado):
    tid = tb.iniciar("ia_gerar", "🤖 Roteiro", lambda t: (t.progresso("escrevendo"), {"texto": "oi"})[1],
                     pagina="/roteiros-yt/abc", alvo={"resp": "p1Resp"})
    t = tb.esperar(tid, 5)
    assert t["status"] == "pronto" and t["resultado"] == {"texto": "oi"} and t["alvo"] == {"resp": "p1Resp"}
    av = nt.listar()[0]
    assert av["link"] == "/roteiros-yt/abc" and av["nivel"] == "ok" and "pronto" in av["titulo"]
    tid2 = tb.iniciar("ia_gerar", "🤖 Outro", lambda t: (_ for _ in ()).throw(RuntimeError("sem chave")), pagina="/x")
    t2 = tb.esperar(tid2, 5)
    assert t2["status"] == "erro" and "sem chave" in t2["erro"] and nt.listar()[0]["nivel"] == "erro"
    assert [x["id"] for x in tb.listar(pagina="/roteiros-yt/abc")] == [tid]
    assert tb.marcar_aplicada(tid) and tb.pegar(tid)["aplicada"]
    assert tb.pegar("../../etc") is None and not tb.apagar("../x")


def test_tarefa_de_outra_execucao_vira_interrompida(isolado):
    os.makedirs(tb.PASTA, exist_ok=True)
    with open(os.path.join(tb.PASTA, "aaaaaaaaaaaa.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "aaaaaaaaaaaa", "status": "rodando", "boot": "velho", "titulo": "x", "criado": 1}, f)
    t = tb.pegar("aaaaaaaaaaaa")
    assert t["status"] == "erro" and "fechado" in t["erro"]


def test_ia_gerar_em_segundo_plano_e_retomar(cliente, monkeypatch):
    A, c = cliente
    import ia_servico
    monkeypatch.setattr(ia_servico, "motivo_desligado", lambda rec: None)
    monkeypatch.setattr(ia_servico, "chamar", lambda *a, **k: '{"roteiro": "ok"}')
    d = c.post("/ia/gerar", json={"prompt": "faça", "bg": True, "pagina": "/roteiros-yt/abc", "titulo": "Roteiro X",
                                  "alvo": {"resp": "p1Resp", "ler": "p1Ler", "xss": "<b>"}}).get_json()
    t = tb.esperar(d["tarefa"], 5)
    assert t["status"] == "pronto" and t["resultado"]["texto"] == '{"roteiro": "ok"}' and "xss" not in t["alvo"]
    p = c.get("/tarefas?tipo=ia_gerar&pendentes=1&pagina=/roteiros-yt/abc").get_json()["tarefas"]
    assert [x["id"] for x in p] == [d["tarefa"]] and "trace" not in p[0]
    c.post(f"/tarefas/{d['tarefa']}/aplicada")
    assert c.get("/tarefas?tipo=ia_gerar&pendentes=1&pagina=/roteiros-yt/abc").get_json()["tarefas"] == []
    assert c.post("/ia/gerar", json={"prompt": "faça"}).get_json()["texto"] == '{"roteiro": "ok"}'  # o modo antigo segue
    monkeypatch.setattr(ia_servico, "chamar", lambda *a, **k: None)
    d = c.post("/ia/gerar", json={"prompt": "faça", "bg": True}).get_json()
    assert tb.esperar(d["tarefa"], 5)["status"] == "erro"


def test_checar_fatos_em_segundo_plano(cliente, monkeypatch):
    A, c = cliente
    import ia_google_rotas as igr
    monkeypatch.setattr(igr, "checar_fatos", lambda texto, timeout=420: {
        "resposta_objetiva": "1 erro", "resposta_completa": "- ERRADA", "fontes": [{"url": "javascript:x"}, {"url": "https://a.b", "titulo": "A"}]})
    d = c.post("/ia-google/checar", json={"texto": "x" * 40, "bg": True, "pagina": "/roteiros-yt/abc"}).get_json()
    t = tb.esperar(d["tarefa"], 5)
    assert t["status"] == "pronto" and t["resultado"]["objetiva"] == "1 erro" and [f["url"] for f in t["resultado"]["fontes"]] == ["https://a.b"]
    assert nt.listar()[0]["link"] == "/roteiros-yt/abc"


def test_extrair_links_em_segundo_plano(cliente, monkeypatch):
    A, c = cliente
    monkeypatch.setattr(A, "extrair_links_canal", lambda url, tipo, ordem: {"canal": "@x", "total": 1,
                                                                           "itens": [{"indice": 1, "titulo": "<b>", "link": "https://youtu.be/a"}]})
    d = c.post("/extrair-links-canal/buscar", json={"url": "youtube.com/@x", "bg": True}).get_json()
    t = tb.esperar(d["tarefa"], 5)
    assert t["status"] == "pronto" and t["resultado"]["total"] == 1 and t["pagina"] == "/extrair-links-canal"
    h = c.get("/extrair-links-canal").get_data(as_text=True)
    assert "historico-lista" in h and "esc(item.titulo)" in h


def test_thread_com_aviso_e_historico_das_ferramentas(cliente, tmp_path):
    A, c = cliente
    st = {"status": "processando", "erro": None}

    def _run():
        st.update(status="erro", erro="link quebrado")
    A._thread_com_aviso(_run, lambda: st, "📲 Download", "/redes-sociais#j-abc", "redes")
    fim = time.time() + 5
    while time.time() < fim and not nt.listar():
        time.sleep(0.02)
    assert nt.listar()[0]["nivel"] == "erro" and "link quebrado" in nt.listar()[0]["msg"]
    # histórico salvo em disco volta ao reabrir o site; o que estava rodando vira "interrompido"
    raiz = str(tmp_path / "redes")
    A._historico_salvar(raiz, {"id": "abc123abc123", "status": "pronto", "criado_em": 1, "quantidade": 2, "log": "x" * 9000})
    A._historico_salvar(raiz, {"id": "def456def456", "status": "processando", "criado_em": 2, "quantidade": 1})
    d = {}
    A._historico_carregar(raiz, d)
    assert d["abc123abc123"]["status"] == "pronto" and len(d["abc123abc123"]["log"]) == 4000
    assert d["def456def456"]["status"] == "erro" and "fechado" in d["def456def456"]["erro"]
    A._REDES_SOCIAIS_JOBS["abc123abc123"] = d["abc123abc123"]
    try:
        h = c.get("/redes-sociais").get_data(as_text=True)
        assert 'id="historico"' in h and "j-abc123abc123" in h
        assert 'id="historico"' in c.get("/transcrever").get_data(as_text=True)
    finally:
        A._REDES_SOCIAIS_JOBS.pop("abc123abc123", None)


def test_vigia_de_captcha_avisa_e_some(isolado, monkeypatch):
    import ia_google_rotas as igr
    seq = iter([False, True, True, False, False, False, False])
    monkeypatch.setattr(igr, "captcha_esperando", lambda: next(seq, False))
    parar = threading.Event()
    th = threading.Thread(target=igr._vigiar_captcha, args=(parar, 0.01))
    th.start()
    fim = time.time() + 5
    vistos = []
    while time.time() < fim:
        it = [x for x in nt.listar() if x["chave"] == igr.CHAVE_CAPTCHA]
        if it:
            vistos.append(it[0]["lida"])
            if it[0]["lida"]:
                break
        time.sleep(0.005)
    parar.set()
    th.join(2)
    av = [x for x in nt.listar() if x["chave"] == igr.CHAVE_CAPTCHA]
    assert len(av) == 1 and av[0]["link"] == "/ia-google" and av[0]["nivel"] == "aviso" and av[0]["lida"]
    assert False in vistos  # ficou não lida enquanto o captcha esperava


def test_captcha_com_navegador_oculto_reabre_visivel(monkeypatch):
    pytest.importorskip("playwright")
    pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ia_google")
    monkeypatch.syspath_prepend(pasta)
    ig = importlib.import_module("ia_google")
    ia = ig.GoogleIA(headless=True, interativo=False, log=lambda *a, **k: None)
    eventos = []

    class Pag:
        url = "https://www.google.com/sorry/index"

        def goto(self, u, **k):
            eventos.append(("goto", u))

        def bring_to_front(self):
            eventos.append(("frente",))

    ia.page = Pag()
    monkeypatch.setattr(ia, "fechar", lambda: eventos.append(("fechar", ia.headless)))
    monkeypatch.setattr(ia, "abrir", lambda: (eventos.append(("abrir", ia.headless)), setattr(ia, "page", Pag())))
    respostas = iter([True, True, True, False])
    estados = []
    monkeypatch.setattr(ia, "_tem_captcha", lambda: (estados.append(ia.esperando_captcha), next(respostas, False))[1])
    monkeypatch.setattr(ig.time, "sleep", lambda s: None)
    assert ia._checar_captcha() is True
    assert ("fechar", True) in eventos and ("abrir", False) in eventos and ("goto", Pag.url) in eventos
    assert ia.headless is False and ia.esperando_captcha is False and True in estados
    # sem a opção (ou no terminal) continua dando o erro claro de antes
    ia2 = ig.GoogleIA(headless=True, interativo=False, log=lambda *a, **k: None)
    ia2.desocultar_no_captcha = False
    monkeypatch.setattr(ia2, "_tem_captcha", lambda: True)
    with pytest.raises(ig.ErroIA):
        ia2._checar_captcha()
