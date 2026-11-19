"""v84_424 — IA local (Qwen via Ollama/LM Studio) nas partes simples + notas do texto bruto sem gravar o cache em dobro."""
import json
import threading
import time

import ia_local as il


class _R:
    def __init__(self, codigo, corpo):
        self.status_code, self._c, self.text = codigo, corpo, json.dumps(corpo)

    def json(self):
        return self._c


def _cfg(**kw):
    return {"local": dict(il.PADRAO, ativo=True, **kw)}


def test_vai_local_so_nos_recursos_marcados_e_imagem_so_com_visao():
    c = _cfg(recursos=["buscas", "juiz"])
    assert il.vai_local("buscas", "texto", c) == "qwen2.5:7b"
    assert il.vai_local("roteiros", "texto", c) is None
    img = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AAA"}}, {"type": "text", "text": "x"}]
    assert il.vai_local("juiz", img, c) is None
    assert il.vai_local("juiz", img, _cfg(recursos=["juiz"], modelo_visao="qwen2.5vl:7b")) == "qwen2.5vl:7b"
    assert il.vai_local("buscas", "x", {"local": dict(il.PADRAO, ativo=False)}) is None  # desligada


def test_chamar_com_json_e_imagem():
    pedidos = []

    def post(url, corpo):
        pedidos.append(corpo)
        if corpo["response_format"]["type"] == "json_schema":
            return _R(400, {"erro": "sem schema"})
        return _R(200, {"choices": [{"message": {"content": '<think>hmm</think>{"ok": true}'}}]})
    img = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AAA"}}, {"type": "text", "text": "x"}]
    r = il.chamar("qwen2.5vl:7b", "sys", img, {"type": "object"}, c=_cfg(), transporte=post)
    assert r == {"ok": True} and pedidos[-1]["response_format"] == {"type": "json_object"}
    assert pedidos[0]["messages"][1]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_ia_servico_usa_a_local_e_cai_na_api(monkeypatch):
    import ia_servico as ia
    cfg = dict(ia.config(), ativo=True, chave="sk-ant-x", texto_via="api", local=dict(il.PADRAO, ativo=True, recursos=["buscas"]))
    monkeypatch.setattr(ia, "config", lambda: cfg)
    monkeypatch.setattr(ia, "_registrar", lambda *a, **k: None)
    api = []
    monkeypatch.setattr(ia, "_transporte", lambda payload, k, t: (api.append(1) or 200,
                        {"content": [{"type": "text", "text": "da API"}], "usage": {}}))
    monkeypatch.setattr(il, "chamar", lambda *a, **k: "DO QWEN")
    assert ia.chamar("buscas", "s", "oi", cache_local=False) == "DO QWEN" and not api
    assert ia.chamar("roteiros", "s", "oi", cache_local=False) == "da API"

    def falha(*a, **k):
        raise il.LocalErro("desligado")
    monkeypatch.setattr(il, "chamar", falha)
    assert ia.chamar("buscas", "s", "oi", cache_local=False) == "da API"
    # sem chave da API, mas o recurso vai pra local: não fica "desligado"
    sem = dict(cfg, chave="")
    monkeypatch.setattr(ia, "chave", lambda c=None: "")
    assert ia.motivo_desligado("buscas", sem) is None and ia.motivo_desligado("roteiros", sem) == "falta a chave da API"


def test_notas_o_primeiro_grava_o_cache_e_os_outros_esperam(monkeypatch, tmp_path):
    import temas_bruto as TB
    a = {"id": "aula1", "modelo": "x", "divisao": "completo", "temas": []}
    monkeypatch.setattr(TB, "texto", lambda base, aid: "texto da aula " * 100)
    monkeypatch.setattr(TB, "system_notas", lambda a, tx: "SYS")
    ativos, maximo, ordem = [0], [0], []
    trava = threading.Lock()

    def notas(ia, a, t, tx):
        with trava:
            ativos[0] += 1
            maximo[0] = max(maximo[0], ativos[0])
            ordem.append(t["titulo"])
        time.sleep(0.15)
        with trava:
            ativos[0] -= 1
        return "notas " * 100
    monkeypatch.setattr(TB, "_notas", notas)
    TB._CACHE_NOTAS.pop("aula1", None)
    ths = [threading.Thread(target=TB.gerar_notas, args=(str(tmp_path), a, {"titulo": f"T{i}"})) for i in range(3)]
    for t in ths:
        t.start()
        time.sleep(0.02)
    for t in ths:
        t.join()
    assert ordem[0] == "T0" and len(ordem) == 3
    # o 1º rodou SOZINHO (gravando o cache); só depois os outros 2 juntos
    assert TB._CACHE_NOTAS["aula1"]["quente"] > 0 and maximo[0] == 2


def test_pagina_ia_tem_a_local():
    import app as A
    h = A.app.test_client().get("/ia").get_data(as_text=True)
    assert "locTestar" in h and "Qwen" in h
