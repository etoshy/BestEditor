"""v84_409: Flow mais confiável — ritmo humano, rodízio, saúde das contas, extensões, retomar, erro passageiro, fila,
2 variações + juiz, conferir antes de animar, pessoa famosa na foto base."""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
import flow_fila as FF  # noqa: E402
import flow_juiz as FJ  # noqa: E402
import flow_saude as FS  # noqa: E402
import flow_estudio as FE  # noqa: E402
import refazer_cena as RC  # noqa: E402
from googleflow import flow_direto as fd  # noqa: E402
from googleflow import googleflow_client as gf  # noqa: E402


@pytest.fixture
def dados(monkeypatch, tmp_path):
    monkeypatch.setattr(gf, "pasta_dados", lambda: tmp_path / "flow_dados")
    os.makedirs(tmp_path / "flow_dados", exist_ok=True)
    FS._MEM.update(ultimo_fim=0.0, seguidas={"conta": None, "n": 0})
    return tmp_path


def _png(c, cor="red", tam=(200, 200)):
    from PIL import Image
    Image.new("RGB", tam, cor).save(c)
    return str(c)


# ------------------------------------------------------------------ 🩺 saúde / ritmo / rodízio
def test_eventos_seguidas_e_rodizio(dados):
    cfg = {"flow_ritmo": {"rodizio_cada": 3, "max_hora": 10, "pausa_min": 1, "pausa_max": 2}}
    for _ in range(2):
        FS.registrar("a", "geracao")
    assert FS.seguidas("a") == 2 and FS.precisa_trocar("a", cfg) == ""
    FS.registrar("a", "geracao")
    assert "3 gerações seguidas" in FS.precisa_trocar("a", cfg)
    FS.registrar("b", "geracao")
    assert FS.seguidas("a") == 0 and FS.seguidas("b") == 1  # trocou de conta: zera
    FS.registrar("a", "incomum", "Notamos uma atividade incomum")
    assert FS.contar("a", "geracao", 3600) == 3 and FS.contar("a", "incomum", 3600) == 1
    for _ in range(7):
        FS.registrar("a", "geracao")
    assert "10 gerações na última hora" in FS.precisa_trocar("a", dict(cfg, flow_ritmo={"rodizio_cada": 0, "max_hora": 10}))
    assert FS.config({"flow_ritmo": {"pausa_min": "50", "pausa_max": 5}})["pausa_max"] == 50.0  # máx nunca < mín


def test_pausa_humana(dados):
    dormiu = []
    assert FS.pausa_antes({"flow_ritmo": {"pausa_min": 5, "pausa_max": 5}}, dormir=dormiu.append) == 0  # 1º pedido: sem pausa
    FS.marcar_fim()
    esperou = FS.pausa_antes({"flow_ritmo": {"pausa_min": 5, "pausa_max": 5}}, dormir=dormiu.append)
    assert 4 <= esperou <= 5 and abs(sum(dormiu) - esperou) < 0.01
    FS._MEM["ultimo_fim"] = time.time() - 100
    assert FS.pausa_antes({"flow_ritmo": {"pausa_min": 5, "pausa_max": 5}}, dormir=dormiu.append) == 0  # já passou


def test_proxima_conta_e_fora_do_rodizio(dados, monkeypatch):
    monkeypatch.setattr(gf, "listar_contas", lambda agora=None: [{"nome": n} for n in ("a", "b", "c")])
    servem = {"a": True, "b": False, "c": True}
    monkeypatch.setattr(gf, "conta_serve", lambda n, tipo=None, agora=None: servem[n])
    assert FS.proxima_conta("a") == "c" and FS.proxima_conta("c") == "a"
    servem.update(a=False)
    assert FS.proxima_conta("c") is None
    puladas = {}
    monkeypatch.setattr(gf, "pular_conta", lambda n, motivo, minutos=None: puladas.__setitem__(n, minutos))
    monkeypatch.setattr(gf, "despular_conta", lambda n=None: puladas.pop(n, None))
    monkeypatch.setattr(gf, "conta_pulada", lambda n, agora=None: None)
    FS.tirar_do_rodizio("b")
    assert FS.fora_do_rodizio() == ["b"] and puladas["b"] == FS.FORA_MIN
    puladas.clear()
    FS.aplicar_fora()  # reiniciou o site: continua de fora
    assert "b" in puladas
    FS.tirar_do_rodizio("b", False)
    assert FS.fora_do_rodizio() == [] and "b" not in puladas


def test_extensoes_do_perfil(dados, monkeypatch):
    perfis = dados / "perfis"
    monkeypatch.setattr(gf, "pasta_perfis", lambda: perfis)
    os.makedirs(perfis / "chrome" / "Default" / "Extensions" / "abc", exist_ok=True)
    os.makedirs(perfis / "chrome" / "Default" / "Extensions" / "Temp", exist_ok=True)
    os.makedirs(perfis / f"chrome--{gf._slug('Conta 2')}" / "Default", exist_ok=True)
    assert FS.extensoes(gf.CONTA_PADRAO) == {"chrome": 1}
    assert FS.extensoes("Conta 2") == {"chrome": 0}


def test_anonimizar_rostos(dados):
    from PIL import Image
    base = _png(dados / "b.png", (250, 30, 30), (400, 300))
    im = Image.open(base)
    im.paste((10, 200, 10), (180, 100, 220, 140))  # um "rosto"
    im.save(base)
    out = FS.anonimizar(base, str(dados / "a.png"), [{"x": 0.5, "y": 0.4, "tipo": "pessoa"}], achar=lambda f: [])
    px = Image.open(out).getpixel((200, 120))
    assert px != (10, 200, 10)  # borrado
    assert Image.open(out).getpixel((10, 10)) == (250, 30, 30)  # o resto fica
    assert FS.anonimizar(base, str(dados / "c.png"), [], achar=lambda f: []) is None
    assert FS.anonimizar(base, str(dados / "d.png"), None, achar=lambda f: [[0.4, 0.3, 0.2, 0.2]])


# ------------------------------------------------------------------ 🎯 juiz
def test_juiz(dados):
    cands = [_png(dados / f"c{k}.png") for k in range(2)]
    vistos = {}

    def chamar(rec, sis, cont, **k):
        vistos["rec"], vistos["txt"] = rec, [c["text"] for c in cont if c.get("type") == "text"]
        return {"candidatos": [{"n": 1, "nota": 40, "problemas": "the mascot keeps its thumbs-up"}, {"n": 2, "nota": 88, "problemas": ""}],
                "melhor": 2, "resumo": "A 2 seguiu a pose."}
    j = FJ.julgar("P", [("BASE", cands[0])], cands, chamar, lambda f: {"type": "image"})
    assert vistos["rec"] == "flow_juiz" and "CANDIDATE 2" in vistos["txt"] and j["melhor"] == 1 and j["ok"] and j["notas"] == [40, 88]
    j = FJ.julgar("P", [], cands, lambda *a, **k: {"candidatos": [{"n": 1, "nota": 30, "problemas": "x"}], "melhor": 1, "resumo": ""},
                  lambda f: {"type": "image"})
    assert not j["ok"] and j["problemas"][0] == "x"
    assert FJ.julgar("P", [], cands, lambda *a, **k: None, lambda f: {"type": "image"})["com_ia"] is False


# ------------------------------------------------------------------ 🎬 refazer: retomar, variações, conferir
def _video(c, cores=(("red", 2), ("blue", 3))):
    import subprocess
    ins, f = [], []
    for k, (cor, d) in enumerate(cores):
        ins += ["-f", "lavfi", "-i", f"color=c={cor}:s=160x90:r=25:d={d}"]
        f.append(f"[{k}:v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", "".join(f) + f"concat=n={len(cores)}:v=1:a=0",
                    "-pix_fmt", "yuv420p", str(c)], check=True, capture_output=True)
    return str(c)


def test_refazer_variacoes_conferir_e_retomar(dados):
    base = str(dados / "rf")
    p = RC.criar(base, _video(dados / "v.mp4"))
    RC._mudar(base, p["id"], lambda q: (q.update(analisado=True), [pl.update(acao_en="x") for pl in q["planos"]]))
    pedidos = []

    def rodar(ped):
        pedidos.append(ped)
        if ped["tipo"] == "imagem":
            return [{"tipo": "imagem", "caminho": _png(dados / f"i{len(pedidos)}_{k}.png")} for k in range(2 if ped.get("quantidade") == "x2" else 1)]
        return [{"tipo": "video", "caminho": _video(dados / f"vv{len(pedidos)}.mp4", (("green", 2),))}]
    notas = iter([[30, 20], [45, 70]])  # 1ª: ruim (refaz com o motivo) · 2ª: a 2ª variação boa
    julg = lambda pr, refs, cands: (lambda ns: {"melhor": ns.index(max(ns)), "notas": ns, "problemas": ["thumbs up", "-"],  # noqa: E731
                                                 "ok": max(ns) >= 60, "resumo": "r", "com_ia": True})(next(notas))
    q = RC.gerar(base, str(dados / "gal"), p["id"], [1], "tudo", rodar, montar=lambda pac: {"prompt": "P"}, julgar=julg)
    assert [x.get("quantidade") for x in pedidos[:2]] == ["x2", "x2"] and "Fix: thumbs up" in pedidos[1]["prompt"]
    pl = q["planos"][0]
    assert pl["juiz"]["nota"] == 70 and len(pl["quadros_alt"]) == 1 and pl["video_novo"] and pedidos[2]["tipo"] == "video"
    # quadro que continua ruim não é animado
    pedidos.clear()
    q = RC.gerar(base, str(dados / "gal"), p["id"], [2], "tudo", rodar, montar=lambda pac: {"prompt": "P"},
                 julgar=lambda *a: {"melhor": 0, "notas": [10, 5], "problemas": ["wrong face", ""], "ok": False, "resumo": "", "com_ia": True})
    assert [x["tipo"] for x in pedidos] == ["imagem", "imagem"] and "não animei" in q["planos"][1]["erro"] and not q["planos"][1]["video_novo"]
    # ⏭ retomar: o plano 1 (pronto) fica; só o 2 roda
    pedidos.clear()
    RC._mudar(base, p["id"], lambda q_: q_.update(variacoes=False, conferir=False))
    q = RC.gerar(base, str(dados / "gal"), p["id"], [], "tudo", rodar, montar=lambda pac: {"prompt": "P"}, pular_prontos=True)
    assert [x["tipo"] for x in pedidos] == ["imagem", "video"]  # o 2 tinha quadro RUIM: refaz o quadro e anima
    pedidos.clear()
    RC._mudar(base, p["id"], lambda q_: q_["planos"][1].update(video_novo=""))
    q = RC.gerar(base, str(dados / "gal"), p["id"], [], "tudo", rodar, montar=lambda pac: {"prompt": "P"}, pular_prontos=True)
    assert [x["tipo"] for x in pedidos] == ["video"]  # quadro bom já existe: só anima
    assert all(pl["video_novo"] for pl in q["planos"])


# ------------------------------------------------------------------ 📥 fila
def test_fila(dados):
    feitos = []

    def rodar(ped, parar=None):
        feitos.append(ped["prompt"])
        if ped["prompt"] == "erro":
            raise RuntimeError("o Flow caiu")
        return [{"tipo": "imagem", "arquivo": f"{ped['prompt']}_{k}.png", "caminho": "x"} for k in range(2)]
    a = FF.adicionar("A", {"prompt": "a"}, escolher=True, iniciar=False)
    FF.adicionar("B", {"prompt": "erro"}, iniciar=False)
    c = FF.adicionar("C", {"prompt": "c"}, iniciar=False)
    assert FF.tirar(c["id"]) and [x["rotulo"] for x in FF.listar()] == ["A", "B"]
    while True:
        it = FF.proximo()
        if not it:
            break
        FF.processar_um(it, rodar, julgar=lambda pr, refs, imgs: {"melhor": 1, "notas": [50, 90], "resumo": "ok"})
    est = {x["rotulo"]: x for x in FF.listar()}
    assert feitos == ["a", "erro"] and est["A"]["estado"] == "pronto" and est["A"]["melhor"] == "a_1.png"
    assert est["B"]["estado"] == "erro" and "caiu" in est["B"]["erro"]
    FF.limpar_prontos()
    assert FF.listar() == []


# ------------------------------------------------------------------ 🔁 passageiro e 🙈 famosos dentro da sessão
def _sessao(monkeypatch):
    s = FE._Sessao()
    s.conta, s.page = "a", object()
    projetos = []
    monkeypatch.setattr(s, "_fechar_pagina", lambda: None)
    monkeypatch.setattr(s, "_garantir_navegador", lambda cfg, vis, conta: None)
    monkeypatch.setattr(s, "_garantir_projeto", lambda *a, **k: projetos.append(1))
    monkeypatch.setattr(gf, "salvar_diagnostico", lambda *a, **k: None)
    return s, projetos


def test_erro_passageiro_tenta_de_novo(dados, monkeypatch):
    s, projetos = _sessao(monkeypatch)
    n = []

    def gerar_um(page, trab, on, t):
        n.append(1)
        if len(n) == 1:
            raise fd.FlowPassoErro("esperar", "o resultado não apareceu em 300 s (tempo esgotado)")
        return [{"tipo": "imagem"}]
    monkeypatch.setattr(fd, "gerar_um", gerar_um)
    assert s._gerar({"tipo": "imagem", "prompt": "p"}, {}, {}, lambda *a: None, {}, 30) and len(n) == 2 and projetos == [1]
    n.clear()
    monkeypatch.setattr(fd, "gerar_um", lambda *a, **k: (n.append(1), (_ for _ in ()).throw(fd.FlowPassoErro("esperar", "tempo esgotado")))[1])
    with pytest.raises(fd.FlowPassoErro):  # 2ª vez: o erro sobe
        s._gerar({"tipo": "imagem", "prompt": "p"}, {}, {}, lambda *a: None, {}, 30)
    assert len(n) == 2 and FS.contar("a", "passageiro", 3600) == 3


def test_famoso_na_foto_base_borra_e_tenta(dados, monkeypatch):
    s, _p = _sessao(monkeypatch)
    base = _png(dados / "base.png", "blue", (300, 300))
    usadas = []

    def gerar_um(page, trab, on, t):
        usadas.append([r["arquivo"] for r in trab["referencias"]])
        if len(usadas) == 1:
            e = fd.FlowRecusou("esperar", "pode violar nossas políticas contra pessoas famosas")
            e.motivo = "famosos"
            raise e
        return [{"tipo": "imagem"}]
    monkeypatch.setattr(fd, "gerar_um", gerar_um)
    trab = {"tipo": "imagem", "prompt": "p", "referencias": [{"arquivo": base, "papel": "base", "marcas": [{"x": 0.5, "y": 0.4}]},
                                                            {"arquivo": _png(dados / "m.png"), "papel": "personagem"}]}
    assert s._gerar(trab, {}, {}, lambda *a: None, {}, 30)
    assert usadas[1][0].endswith("base_anonima.png") and usadas[1][1] == usadas[0][1]


# ------------------------------------------------------------------ rotas
def test_rotas(dados, monkeypatch):
    import app as A
    A.app.config["TESTING"] = True
    c = A.app.test_client()
    monkeypatch.setattr(gf, "listar_contas", lambda agora=None: [{"nome": "a", "email": "a@x", "logada": True}])
    monkeypatch.setattr(gf, "nomes_das_contas", lambda: ["a"])
    monkeypatch.setattr(gf, "pasta_perfis", lambda: dados / "perfis")
    FS.registrar("a", "geracao")
    FS.registrar("a", "incomum")
    j = c.get("/flow/saude").get_json()
    assert j["contas"][0]["dia"]["incomum"] == 1 and j["contas"][0]["saude"] == 75 and j["ritmo"]["rodizio_cada"] == 6
    assert c.post("/flow/saude/rodizio", json={"conta": "zz"}).status_code == 404
    monkeypatch.setattr(gf, "pular_conta", lambda *a, **k: None)
    assert c.post("/flow/saude/rodizio", json={"conta": "a", "fora": True}).get_json()["contas"][0]["fora"]
    monkeypatch.setattr(FF, "garantir_trabalhador", lambda rodar=None: None)
    assert c.get("/flow/fila").get_json()["itens"] == []
    h = c.get("/flow").get_data(as_text=True)
    assert 'id="fila"' in h and 'id="saude"' in h and 'id="mtEscolher"' in h and 'id="rcFila"' in h
