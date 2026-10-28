"""v84_184: 🧍 Personagens no 🚀 Flow — cada pose vira um pedido de FOTO na fila do Flow em massa com UMA imagem de
referência (a ficha + a ⭐ mestre numa colagem); a imagem volta com fundo verde e o PNG transparente sai no PC."""
import io
import json
import os
import threading

import numpy as np
import pytest
from PIL import Image, ImageDraw

import personagens_limpeza as L
import personagens_pod as pp
from test_v84_183_personagens_pod import JSON_POSES, _png


def _verde(caminho, cor=(40, 30, 90), degrade=True, margem=True):
    """Imagem "do Flow": personagem sobre verde (com degradê/sombra)."""
    W, H = 768, 1024
    y = np.linspace(0, 1, H)[:, None]
    g = np.zeros((H, W, 3), np.float32)
    g[..., 1] = 255 - (70 * y if degrade else 0)
    g[..., 0] = 10 + 25 * y
    g[..., 2] = 12
    im = Image.fromarray(g.astype(np.uint8))
    d = ImageDraw.Draw(im)
    x0 = 180 if margem else 0
    d.ellipse([300, 120, 470, 330], fill=(240, 220, 205), outline=(0, 0, 0), width=5)   # cabeça
    d.polygon([(x0, H), (250, 340), (520, 340), (W - x0, H)], fill=cor, outline=(0, 0, 0))  # corpo até a borda de baixo
    for k in range(6):  # fios de cabelo com verde entre eles
        d.line([(310 + k * 30, 140), (290 + k * 34, 420)], fill=(15, 15, 25), width=6)
    im.save(caminho)
    return caminho


def test_recorte_local_tira_o_verde_e_alinha(tmp_path):
    img = Image.open(_verde(str(tmp_path / "f.png")))
    out, info = L.recortar(img, (1200, 1800), 0.95)
    a = np.asarray(out).astype(int)
    vis = a[..., 3] > 128
    assert out.size == (1200, 1800) and out.mode == "RGBA"
    assert not (vis & (a[..., 1] > np.maximum(a[..., 0], a[..., 2]) + 25)).any()  # nada de verde visível
    assert not vis[:40].any() and vis[-1].any()                                  # espaço em cima, encostada embaixo
    assert info["aviso"] is None and info["limpeza"]["verde_px"] > 0
    # personagem cortada na lateral → aviso
    _o, info2 = L.recortar(Image.open(_verde(str(tmp_path / "g.png"), margem=False)))
    assert info2["cortada_lados"] and "borda" in info2["aviso"]
    # fundo que não veio verde → aviso
    _o, info3 = L.recortar(Image.new("RGB", (300, 400), (200, 200, 210)))
    assert "não veio verde" in info3["aviso"]


def test_colagem():
    a = Image.new("RGB", (300, 600), "red")
    b = Image.new("RGBA", (500, 500), (0, 0, 255, 255))
    c = L.colagem([a, b], altura=400)
    assert c.size == (200 + 24 + 400, 400) and c.getpixel((10, 10)) == (255, 0, 0) and c.getpixel((300, 10)) == (0, 0, 255)
    assert L.colagem([a]).size == (300, 600)


def test_lote_guarda_a_referencia(tmp_path, monkeypatch):
    import app  # noqa: F401 — toolkit no caminho
    import flow_lote as fl
    monkeypatch.setattr(fl, "pasta", lambda: str(tmp_path))
    lote = fl.Lote()
    ref = str(tmp_path / "ref.png")
    Image.new("RGB", (10, 10)).save(ref)
    j1, j2, j3 = lote.adicionar([{"prompt": "a", "tipo": "imagem", "referencia_arquivo": ref, "origem": "personagens"},
                                 {"prompt": "b", "tipo": "imagem"},
                                 {"prompt": "c", "tipo": "imagem", "referencia_arquivo": str(tmp_path / "nao_existe.png")}],
                                proporcao="3:4")
    assert j1["referencia_arquivo"] == os.path.abspath(ref) and j1["origem"] == "personagens" and j1["proporcao"] == "3:4"
    assert "referencia_arquivo" not in j2 and "referencia_arquivo" not in j3


class LoteFalso:
    def __init__(self):
        self.trava = threading.RLock()
        self.fila, self.rodando, self.fim_msg, self.iniciou = [], False, None, 0
        self.pedidos = []
        self.cfg = {"visivel": True}

    def adicionar(self, itens, modelo="", proporcao="16:9", quantidade="x1", **kw):
        novos = []
        for it in itens:
            j = {"id": f"fj{len(self.fila) + 1}", "prompt": it["prompt"], "tipo": it["tipo"], "estado": "pendente",
                 "referencia_arquivo": it.get("referencia_arquivo"), "proporcao": proporcao, "quantidade": quantidade,
                 "resultados": [], "criado": len(self.fila)}
            self.fila.append(j)
            novos.append(j)
        return novos

    def iniciar(self):
        self.rodando = True
        self.iniciou += 1


@pytest.fixture()
def flow(tmp_path, monkeypatch):
    import app as A
    import flow_estudio as FE
    import flow_lote
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    falso = LoteFalso()
    monkeypatch.setattr(flow_lote, "lote", lambda: falso)
    gal = tmp_path / "galeria"
    gal.mkdir()
    monkeypatch.setattr(FE, "pasta_galeria", lambda: str(gal))
    import personagens_pod as _pp
    monkeypatch.setattr(_pp, "boca_auto", lambda p: False)  # v84_221: estes testes olham a fila exata (a boca automática tem teste próprio)
    return A.app.test_client(), falso, gal


def _ok(falso, gal, jid, n=1, cor=(40, 30, 90), margem=True):
    j = next(x for x in falso.fila if x["id"] == jid)
    res = []
    for k in range(n):
        nome = f"{jid}_{k}.png"
        _verde(str(gal / nome), cor=cor, margem=margem)
        res.append({"id": f"g{k}", "arquivo": nome, "tipo": "imagem"})
    j.update(estado="ok", resultados=res)


def test_ponta_a_ponta_no_flow(flow, tmp_path):
    c, falso, gal = flow
    r = c.post("/personagens-pod/criar", data={"nome": "Vanta", "motor": "flow", "json": json.dumps(JSON_POSES),
                                                "refs": [(io.BytesIO(_png()), "ficha.png")]}, content_type="multipart/form-data")
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    pagina = c.get(f"/personagens-pod/{pid}").get_data(as_text=True)
    assert 'id="motor"' in pagina and "Flow em massa" in pagina and 'id="flowVisivel"' in pagina
    # ⭐ mestre em x2 → 2 versões
    d = c.post(f"/personagens-pod/{pid}/gerar", json={"arquivos": ["vanta_neutra_esq.png"], "quantidade": "x2"}).get_json()
    assert d["ok"] and d["com_mestre"] is False and falso.iniciou == 1
    j = falso.fila[-1]
    assert j["tipo"] == "imagem" and j["proporcao"] == "3:4" and j["quantidade"] == "x2" and os.path.isfile(j["referencia_arquivo"])
    assert "reference image is the official" in j["prompt"] and "VANTA LOCK" in j["prompt"] and "GREEN" in j["prompt"]
    e = c.get(f"/personagens-pod/{pid}/estado").get_json()
    it = next(x for x in e["itens"] if x["arquivo"] == "vanta_neutra_esq.png")
    assert it["estado"] == "fila" and "fila do Flow" in it["msg"]
    j["estado"] = "rodando"
    j["conta"] = "conta1"
    e = c.get(f"/personagens-pod/{pid}/estado").get_json()
    assert next(x for x in e["itens"] if x["arquivo"] == "vanta_neutra_esq.png")["estado"] == "gerando"
    _ok(falso, gal, j["id"], n=2)
    e = c.get(f"/personagens-pod/{pid}/estado").get_json()
    it = next(x for x in e["itens"] if x["arquivo"] == "vanta_neutra_esq.png")
    assert it["estado"] == "pronta" and it["versoes"] == 2 and not e["esperando"]
    img = Image.open(io.BytesIO(c.get(f"/personagens-pod/{pid}/img/{it['img']}").data))
    assert img.size == (600, 900) and img.mode == "RGBA" and img.getpixel((5, 5))[3] == 0
    assert c.post(f"/personagens-pod/{pid}/mestre", json={"arquivo": "vanta_neutra_esq.png"}).get_json()["ok"]
    assert pp.carregar(pid)["mestre"]["bruto"]  # a mestre lembra a original (fundo verde) pra colagem
    # ▶ resto: a cética + a boca dela (base no mesmo envio → fica pra depois) + a boca da mestre (base pronta)
    d = c.post(f"/personagens-pod/{pid}/gerar", json={"arquivos": ["vanta_cetica_esq.png", "vanta_cetica_esq_boca.png",
                                                                   "vanta_neutra_esq_boca.png"]}).get_json()
    assert d["enviadas"] == 2 and d["depois"] == ["vanta_cetica_esq_boca.png"] and "esperando" in d["aviso"]
    jc, jb = falso.fila[-2], falso.fila[-1]
    # v84_185: com a mestre, ela vai SOZINHA (a colagem com a ficha fazia o Flow devolver uma folha)
    assert "APPROVED MASTER" in jc["prompt"] and "NOT its pose" in jc["prompt"] and "NEW POSE" in jc["prompt"]
    col = Image.open(jc["referencia_arquivo"])
    assert col.width < col.height
    # "flow": {"referencia": "colagem"} → ficha + mestre lado a lado
    q = pp.carregar(pid)
    q["dados"]["flow"] = {"referencia": "colagem"}
    pp.salvar(q)
    c.post(f"/personagens-pod/{pid}/gerar", json={"arquivos": ["vanta_relogio_esq.png"]})
    jr = falso.fila.pop()
    assert "collage of 2 panels" in jr["prompt"] and Image.open(jr["referencia_arquivo"]).width > Image.open(jr["referencia_arquivo"]).height
    q = pp.carregar(pid)
    q["imagens"]["vanta_relogio_esq.png"].update(estado="nova", job=None)
    q["jobs"] = [x for x in q["jobs"] if x["id"] != jr["id"]]
    pp.salvar(q)
    assert jb["prompt"].startswith("The reference image is the finished character image to edit")
    assert Image.open(jb["referencia_arquivo"]).getpixel((2, 2))[1] > 150  # a base vai com o fundo verde
    # erro do Flow aparece na pose; refazer com correção
    jc.update(estado="erro", erro="o Flow recusou: política")
    _ok(falso, gal, jb["id"])
    e = c.get(f"/personagens-pod/{pid}/estado").get_json()
    por = {x["arquivo"]: x for x in e["itens"]}
    assert por["vanta_cetica_esq.png"]["estado"] == "erro" and "recusou" in por["vanta_cetica_esq.png"]["erro"]
    assert por["vanta_neutra_esq_boca.png"]["estado"] == "pronta"
    c.post(f"/personagens-pod/{pid}/gerar", json={"arquivos": ["vanta_cetica_esq.png"], "extra": "no cigarette"})
    assert falso.fila[-1]["prompt"].endswith("CORRECTION FOR THIS ATTEMPT: no cigarette")
    _ok(falso, gal, falso.fila[-1]["id"])
    c.get(f"/personagens-pod/{pid}/estado")
    # v84_221: a boca que estava ⏳ esperando a base foi sozinha pro Flow quando a base ficou pronta
    jbc = falso.fila[-1]
    assert jbc["prompt"].startswith("The reference image is the finished character image to edit")
    assert pp.carregar(pid)["imagens"]["vanta_cetica_esq_boca.png"]["estado"] == "fila"
    _ok(falso, gal, jbc["id"])
    c.get(f"/personagens-pod/{pid}/estado")
    c.post(f"/personagens-pod/{pid}/aprovar", json={"arquivo": "vanta_cetica_esq.png"})
    z = c.get(f"/personagens-pod/{pid}/aprovadas.zip")
    import zipfile
    assert sorted(zipfile.ZipFile(io.BytesIO(z.data)).namelist()) == ["poses.json", "vanta_cetica_esq.png", "vanta_neutra_esq.png"]
    # pedido sumiu da fila do Flow
    c.post(f"/personagens-pod/{pid}/gerar", json={"arquivos": ["vanta_relogio_esq.png"]})
    falso.fila.pop()
    e = c.get(f"/personagens-pod/{pid}/estado").get_json()
    assert "sumiu" in next(x for x in e["itens"] if x["arquivo"] == "vanta_relogio_esq.png")["erro"]
    # trocar de motor
    assert c.post(f"/personagens-pod/{pid}/motor", json={"motor": "pod"}).get_json()["ok"]
    assert pp.carregar(pid)["motor"] == "pod"
    assert "erro" in c.post(f"/personagens-pod/{pid}/motor", json={"motor": "xx"}).get_json()


def test_projeto_antigo_continua_no_pod(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    p = pp.criar("V", json.dumps(JSON_POSES), [("ficha.png", _png())], "http://127.0.0.1:9")
    assert p["motor"] == "flow"
    q = pp.carregar(p["id"])
    q.pop("motor")
    pp.salvar(q)
    assert pp.motor_de(pp.carregar(p["id"])) == "pod"


def test_flow_parado_avisa(flow):
    c, falso, gal = flow
    p = pp.criar("V", json.dumps(JSON_POSES), [("ficha.png", _png())])
    falso.iniciar = lambda: (_ for _ in ()).throw(RuntimeError("Já tem algo rodando no Flow"))
    d = c.post(f"/personagens-pod/{p['id']}/gerar", json={"arquivos": ["vanta_neutra_esq.png"]}).get_json()
    assert d["ok"] and "não ligou" in d["aviso"]
    e = c.get(f"/personagens-pod/{p['id']}/estado").get_json()
    assert "parado" in next(x for x in e["itens"] if x["arquivo"] == "vanta_neutra_esq.png")["msg"]


def test_cortada_na_borda_refaz_uma_vez(flow):
    c, falso, gal = flow
    p = pp.criar("V", json.dumps(JSON_POSES), [("ficha.png", _png())])
    c.post(f"/personagens-pod/{p['id']}/gerar", json={"arquivos": ["vanta_neutra_esq.png"]})
    _ok(falso, gal, falso.fila[-1]["id"], margem=False)
    e = c.get(f"/personagens-pod/{p['id']}/estado").get_json()
    it = next(x for x in e["itens"] if x["arquivo"] == "vanta_neutra_esq.png")
    assert len(falso.fila) == 2 and it["estado"] == "fila" and "refazendo" in it["msg"] and it["versoes"] == 1
    assert "zoom out" in falso.fila[-1]["prompt"]
    _ok(falso, gal, falso.fila[-1]["id"], margem=False)  # cortou de novo: não refaz mais, fica pra você ver
    e = c.get(f"/personagens-pod/{p['id']}/estado").get_json()
    it = next(x for x in e["itens"] if x["arquivo"] == "vanta_neutra_esq.png")
    assert len(falso.fila) == 2 and it["estado"] == "pronta" and it["versoes"] == 2 and "borda" in it["aviso"]


def test_atividade_incomum_troca_de_conta(tmp_path, monkeypatch):
    """"Notamos uma atividade incomum…" é da CONTA: o pedido volta pra fila (outra conta pega) e a conta descansa;
    quando todas as contas já deram isso, aí sim vira erro."""
    import sys
    import types
    import app  # noqa: F401
    import flow_lote as fl
    from googleflow import flow_direto as fd
    from googleflow import googleflow_client as gf
    monkeypatch.setattr(fl, "pasta", lambda: str(tmp_path))
    monkeypatch.setattr(fl, "PAUSAR_NO_INCOMUM", getattr(test_atividade_incomum_troca_de_conta, "_pausar", False))
    pw = types.ModuleType("playwright.sync_api")
    pw.sync_playwright = lambda: types.SimpleNamespace(start=lambda: types.SimpleNamespace(stop=lambda: None))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", pw)
    pagina = types.SimpleNamespace(is_closed=lambda: False, close=lambda: None, url="")
    monkeypatch.setattr(gf, "_abrir", lambda p, cfg, headless, conta: (types.SimpleNamespace(close=lambda: None), False))
    monkeypatch.setattr(gf, "salvar_sessao", lambda ctx, conta: None)
    monkeypatch.setattr(fd, "preparar_projeto", lambda *a, **k: pagina)
    puladas = []
    monkeypatch.setattr(gf, "pular_conta", lambda conta, motivo, minutos=None: puladas.append((conta, minutos)))

    def recusa(*a, **k):
        raise fd.FlowRecusou("esperar", "o Flow não gerou: Notamos uma atividade incomum. As extensões do navegador que "
                                        "modificam a página podem causar problemas.")
    monkeypatch.setattr(fd, "gerar_um", recusa)
    lote = fl.Lote()
    monkeypatch.setattr(lote, "_aguardar_vez", lambda conta: None)
    monkeypatch.setattr(lote, "_serve", lambda conta, tipo: True)
    monkeypatch.setattr(lote, "contas_do_lote", lambda: ["a", "b"])
    j = lote.adicionar([{"prompt": "x", "tipo": "imagem"}])[0]
    lote._trabalhar("a")
    assert j["estado"] == "pendente" and j["contas_incomum"] == ["a"] and "outra conta" in j["erro"]
    assert puladas == [("a", fl.MINUTOS_INCOMUM)] and "a" in lote.problema_conta
    lote._trabalhar("b")
    assert j["estado"] == "erro" and "todas as contas" in j["erro"]
    # recusa de verdade (política) continua sendo erro na hora
    monkeypatch.setattr(fd, "gerar_um", lambda *a, **k: (_ for _ in ()).throw(fd.FlowRecusou("esperar", "viola as políticas")))
    j2 = lote.adicionar([{"prompt": "y", "tipo": "imagem"}])[0]
    lote._trabalhar("a")
    assert j2["estado"] == "erro" and "recusou" in j2["erro"]


def test_referencia_sobe_uma_vez_e_nao_vira_resultado(tmp_path, monkeypatch):
    """v84_189: a imagem de referência sobe UMA vez por projeto do Flow (depois reusa pela mídia) e, quando ela
    aparece na galeria, nunca é tomada pelo resultado gerado."""
    import sys
    import types
    import app  # noqa: F401
    import flow_lote as fl
    from googleflow import flow_direto as fd
    from googleflow import googleflow_client as gf
    # 1) checar: a mídia que é a referência não conta como resultado
    pagina = types.SimpleNamespace(evaluate=lambda js: [], is_closed=lambda: False, close=lambda: None, url="")
    monkeypatch.setattr(fd, "midias_na_pagina", lambda page: [{"id": "REF1234567890ABCDEFGH", "url": "https://x/REF1234567890ABCDEFGH", "tipo": "imagem"},
                                                               {"id": "novo", "url": "https://x/n", "tipo": "imagem"}])
    monkeypatch.setattr(fd, "falhas", lambda page: [])
    monkeypatch.setattr(fd, "avisos", lambda page: "")
    est = {"antes": set(), "ref_tokens": ["REF1234567890ABCDEFGH"]}
    assert [m["id"] for m in fd.checar(pagina, est)] == ["novo"]
    monkeypatch.setattr(fd, "midias_na_pagina", lambda page: [{"id": "REF1234567890ABCDEFGH", "url": "u", "tipo": "imagem"}])
    assert fd.checar(pagina, est) is None  # só a referência apareceu: ainda gerando
    # 2) o lote reusa a mídia no mesmo projeto
    monkeypatch.setattr(fl, "pasta", lambda: str(tmp_path))
    pw = types.ModuleType("playwright.sync_api")
    pw.sync_playwright = lambda: types.SimpleNamespace(start=lambda: types.SimpleNamespace(stop=lambda: None))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", pw)
    monkeypatch.setattr(gf, "_abrir", lambda p, cfg, headless, conta: (types.SimpleNamespace(close=lambda: None), False))
    monkeypatch.setattr(gf, "salvar_sessao", lambda ctx, conta: None)
    monkeypatch.setattr(fd, "preparar_projeto", lambda *a, **k: pagina)
    vistos = []

    def gerar(page, trab, on_passo, timeout):
        vistos.append(dict(trab.get("referencia") or {}))
        trab["_ref_midia"] = {"media_id": "MIDIA_DO_PROJETO_123456", "origem": "enviada"}
        return [{"id": f"r{len(vistos)}", "url": "u", "tipo": "imagem"}]
    monkeypatch.setattr(fd, "gerar_um", gerar)
    monkeypatch.setattr(fl, "baixar_para_galeria", lambda ctx, midias, job, conta, projeto="": [{"id": "g", "arquivo": "a.png", "tipo": "imagem"}])
    lote = fl.Lote()
    monkeypatch.setattr(lote, "_aguardar_vez", lambda conta: None)
    monkeypatch.setattr(lote, "_serve", lambda conta, tipo: True)
    ref = tmp_path / "ref.png"
    Image.new("RGB", (8, 8), "red").save(ref)
    copia = tmp_path / "outra_copia.png"
    copia.write_bytes(ref.read_bytes())
    lote.adicionar([{"prompt": "a", "tipo": "imagem", "referencia_arquivo": str(ref)},
                    {"prompt": "b", "tipo": "imagem", "referencia_arquivo": str(copia)}])
    lote._trabalhar("c1")
    assert vistos[0]["media_id"] == "" and vistos[1]["media_id"] == "MIDIA_DO_PROJETO_123456"  # a 2ª não sobe de novo


def test_referencia_com_nome_pelo_conteudo(flow, tmp_path):
    c, falso, gal = flow
    p = pp.criar("V", json.dumps(JSON_POSES), [("ficha.png", _png())])
    pp.enviar(p["id"], ["vanta_neutra_esq.png"])
    pp.enviar(p["id"], ["vanta_cetica_esq.png"])
    assert falso.fila[0]["referencia_arquivo"] == falso.fila[1]["referencia_arquivo"]  # a mesma imagem, o mesmo arquivo


def test_atividade_incomum_pausa_o_lote(tmp_path, monkeypatch):
    """⏸ v84_220 (opção desde v84_269): "atividade incomum" pausa o lote e o pedido volta pra fila — nada de pular pra outra conta."""
    import sys
    import types
    import app  # noqa: F401
    import flow_lote as fl
    from googleflow import flow_direto as fd
    from googleflow import googleflow_client as gf
    monkeypatch.setattr(fl, "pasta", lambda: str(tmp_path))
    monkeypatch.setattr(fl, "PAUSAR_NO_INCOMUM", True)  # v84_269: o padrão agora é trocar de conta; pausar é opção
    pw = types.ModuleType("playwright.sync_api")
    pw.sync_playwright = lambda: types.SimpleNamespace(start=lambda: types.SimpleNamespace(stop=lambda: None))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", pw)
    pagina = types.SimpleNamespace(is_closed=lambda: False, close=lambda: None, url="")
    monkeypatch.setattr(gf, "_abrir", lambda p, cfg, headless, conta: (types.SimpleNamespace(close=lambda: None), False))
    monkeypatch.setattr(gf, "salvar_sessao", lambda ctx, conta: None)
    monkeypatch.setattr(fd, "preparar_projeto", lambda *a, **k: pagina)
    monkeypatch.setattr(gf, "pular_conta", lambda conta, motivo, minutos=None: None)
    monkeypatch.setattr(fd, "gerar_um", lambda *a, **k: (_ for _ in ()).throw(
        fd.FlowRecusou("esperar", "o Flow não gerou: Notamos uma atividade incomum.")))
    lote = fl.Lote()
    monkeypatch.setattr(lote, "_aguardar_vez", lambda conta: None)
    monkeypatch.setattr(lote, "_serve", lambda conta, tipo: True)
    monkeypatch.setattr(lote, "contas_do_lote", lambda: ["a", "b"])
    lote.rodando = True
    j = lote.adicionar([{"prompt": "x", "tipo": "imagem"}])[0]
    try:
        lote._trabalhar("a")
    except Exception:  # noqa: BLE001 — o _Parado da pausa
        pass
    assert j["estado"] == "pendente" and "pausado" in j["erro"] and not j.get("contas_incomum")
    assert lote.parar_ja is True


def test_prompt_sem_js_na_pagina():
    from googleflow import flow_direto as fd
    import inspect
    assert "dispatchEvent" not in inspect.getsource(fd.escrever_prompt) + inspect.getsource(fd._focar_editor)
