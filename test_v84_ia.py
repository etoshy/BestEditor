"""
v84_53 — 🤖 IA nas buscas, no editor e nos Modelos de vídeo (Claude Haiku 5.5), sem rede:
um transporte falso faz o papel da API. Desligada/sem crédito, tudo segue como antes.
"""
import json
import os

import pytest

import ia_servico as ia


class FakeAPI:
    """Fila de respostas (ou uma função) no lugar de api.anthropic.com."""

    def __init__(self):
        self.pedidos = []
        self.respostas = []
        self.fn = None

    def __call__(self, payload, chave, timeout):
        self.pedidos.append(json.loads(json.dumps(payload)))
        if self.fn:
            return self.fn(payload)
        r = self.respostas.pop(0) if self.respostas else (200, ok({}))
        return r


def ok(obj, entrada=1000, saida=100, cache=0, stop="end_turn"):
    texto = obj if isinstance(obj, str) else json.dumps(obj)
    return {"content": [{"type": "text", "text": texto}], "stop_reason": stop,
            "usage": {"input_tokens": entrada, "output_tokens": saida, "cache_read_input_tokens": cache}}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(ia, "CONFIG_PATH", str(tmp_path / "ia_config.json"))
    monkeypatch.setattr(ia, "USO_PATH", str(tmp_path / "ia_uso.json"))
    monkeypatch.setattr(ia, "CACHE_DIR", str(tmp_path / "ia_cache"))
    monkeypatch.setattr(ia, "_SEM_PARAM", set())
    monkeypatch.setattr(ia.time, "sleep", lambda s: None)
    f = FakeAPI()
    monkeypatch.setattr(ia, "_transporte", f)
    ia.salvar_config({"ativo": True, "chave": "sk-ant-teste-123456789"})
    return f


# ------------------------------------------------------------------ serviço
def test_desligada_por_padrao(tmp_path, monkeypatch):
    monkeypatch.setattr(ia, "CONFIG_PATH", str(tmp_path / "x.json"))
    assert not ia.ativo() and "desligada" in ia.motivo_desligado()
    chamado = []
    monkeypatch.setattr(ia, "_transporte", lambda *a: chamado.append(1))
    assert ia.chamar("juiz", "s", "u") is None and not chamado


def test_chamada_json_custo_e_cache(api):
    api.respostas = [(200, ok({"ok": True}, entrada=2000, saida=200, cache=10000))]
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
    assert ia.chamar("juiz", "instruções", "oi", schema) == {"ok": True}
    p = api.pedidos[0]
    assert p["model"] == "claude-haiku-5-5" and p["output_config"]["format"]["type"] == "json_schema"
    assert p["output_config"]["effort"] == "low" and p["thinking"] == {"type": "disabled"}
    assert p["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    g = ia.gasto()
    assert g["chamadas"] == 1 and abs(g["usd"] - (2000 * 0.10 + 10000 * 0.01 + 200 * 0.50) / 1e6) < 1e-9
    assert ia.chamar("juiz", "instruções", "oi", schema) == {"ok": True} and len(api.pedidos) == 1  # cache local


def test_sem_credito_desliga_e_nada_trava(api):
    api.respostas = [(400, {"error": {"message": "Your credit balance is too low to access the Anthropic API."}})]
    assert ia.chamar("juiz", "s", "u", cache_local=False) is None
    assert not ia.ativo("juiz") and "sem crédito" in ia.motivo_desligado()
    assert ia.chamar("juiz", "s", "u2") is None and len(api.pedidos) == 1
    ia.salvar_config({"limpar_sem_credito": True})
    assert ia.ativo("juiz")


def test_parametro_recusado_tenta_sem_ele(api):
    api.respostas = [(400, {"error": {"message": "thinking: unexpected value"}}), (200, ok("texto"))]
    assert ia.chamar("edicao", "s", "u", cache_local=False) == "texto"
    assert "thinking" in api.pedidos[0] and "thinking" not in api.pedidos[1]


def test_erros_temporarios_recusa_e_limite(api):
    api.respostas = [(529, {"error": {"message": "overloaded"}}), (200, ok("x"))]
    assert ia.chamar("juiz", "s", "a", cache_local=False) == "x"
    api.respostas = [(200, ok("x", stop="refusal"))]
    assert ia.chamar("juiz", "s", "b", cache_local=False) is None
    ia.salvar_config({"limite_usd": 0.01})
    ia._gravar(ia.USO_PATH, dict(ia.gasto(), usd=0.02))
    assert not ia.ativo("juiz") and "limite" in ia.motivo_desligado()
    ia.salvar_config({"limite_usd": 0, "recursos": {"juiz": False}})
    assert ia.ativo("buscas") and not ia.ativo("juiz")


def test_chave_nunca_vai_inteira(api):
    r = ia.resumo_publico()
    assert r["chave"] == "sk-ant-t…" and "123456789" not in json.dumps(r)


def test_imagem_bloco_reduz(tmp_path):
    from PIL import Image
    cam = tmp_path / "f.png"
    Image.new("RGB", (1280, 720), (200, 10, 10)).save(cam)
    b = ia.imagem_bloco(str(cam), 320)
    import base64
    import io
    im = Image.open(io.BytesIO(base64.b64decode(b["source"]["data"])))
    assert b["type"] == "image" and im.size == (320, 180)
    assert ia.imagem_bloco(str(tmp_path / "nada.png")) is None


# ------------------------------------------------------------------ busca de mídia
def test_juiz_ordena_pela_nota(api, tmp_path):
    import ia_midia
    api.respostas = [(200, ok({"notas": [{"n": 1, "nota": 3, "motivo": "moderna", "problemas": ["epoca_errada"]},
                                          {"n": 2, "nota": 9, "motivo": "perfeita", "problemas": []}], "melhor": 2, "nova_busca": ""}))]
    cands = [{"id": "a", "thumbnail": "", "label": "A"}, {"id": "b", "thumbnail": "", "label": "B"}, {"id": "c", "thumbnail": "", "label": "C"}]
    j = ia_midia.julgar(cands, "Escobar foi preso", {"tema": "x"}, "antes", "depois", "prisão", "escobar prison")
    lista = ia_midia.reordenar(cands, j)
    assert [c["id"] for c in lista] == ["b", "a", "c"] and lista[0]["ia_nota"] == 9 and "ia_nota" not in lista[2]
    txt = json.dumps(api.pedidos[0]["messages"][0]["content"], ensure_ascii=False)
    assert "TRECHO ATUAL: Escobar foi preso" in txt and "FICHA DO VÍDEO" in api.pedidos[0]["system"][0]["text"]


def _seg(**k):
    from prompt_builder import VideoSegment
    return VideoSegment(start=0, end=4, provider=k.pop("provider", "pexels"), query=k.pop("query", "prison"), **k)


def test_previa_com_juiz(api, monkeypatch):
    import video_assembler as va
    buscas = []

    def fake_busca(provider, query, **kw):
        buscas.append((query, kw.get("max_results")))
        return [{"id": f"{query}-{i}", "thumbnail": f"http://t/{query}{i}.jpg", "label": f"{query} {i}", "url": f"http://p/{query}{i}"} for i in range(3)]
    monkeypatch.setattr(va, "search_candidates", fake_busca)
    notas = {"prison": [2, 3, 1], "la catedral prison 1991": [4, 8, 6]}

    def fake_julgar(cands, ctx, busca, recurso="juiz", miniatura="thumbnail"):
        q = cands[0]["id"].rsplit("-", 1)[0]
        ns = notas[q]
        lista = sorted([dict(c, ia_nota=n, ia_motivo="m") for c, n in zip(cands, ns)], key=lambda c: -c["ia_nota"])
        return {"lista": lista, "nova_busca": "la catedral prison 1991" if q == "prison" else ""}
    monkeypatch.setattr(va, "julgar_candidatos_ia", fake_julgar)
    r = va.fetch_segment_preview_lightweight(_seg(), site_cfg={"provider_priority": ["pexels"]}, ia_ctx={"fala": "x"})
    assert r["ok"] and r["result_url"] == "http://p/la catedral prison 19911" and r["ia_nota"] == 8 and not r["ia_aviso"]
    assert r["ia_busca"] == "la catedral prison 1991" and buscas[0] == ("prison", 10)
    # tudo reprovado e sem busca nova: a melhor das reprovadas, com ⚠
    notas["prison"] = [2, 4, 1]
    monkeypatch.setattr(va, "julgar_candidatos_ia", lambda c, *a, **k: {"lista": sorted([dict(x, ia_nota=n) for x, n in zip(c, notas["prison"])],
                                                                                       key=lambda x: -x["ia_nota"]), "nova_busca": ""})
    monkeypatch.setattr(va, "_fallback_queries_for", lambda s: [])
    r = va.fetch_segment_preview_lightweight(_seg(), site_cfg={"provider_priority": ["pexels"]}, ia_ctx={"fala": "x"})
    assert r.get("cartao") and r["ia_nota"] == 4  # v84_70: 🃏 nada prestou → cartão de texto
    _pode = va._ia_pode
    monkeypatch.setattr(va, "_ia_pode", lambda rec: rec != "cartao" and _pode(rec))  # cartão desligado: como antes
    r = va.fetch_segment_preview_lightweight(_seg(), site_cfg={"provider_priority": ["pexels"]}, ia_ctx={"fala": "x"})
    assert r["ok"] and r["ia_aviso"] and r["label"].startswith("⚠") and r["ia_nota"] == 4
    # sem IA (sem contexto): o 1º, como sempre, 1 resultado só
    buscas.clear()
    r = va.fetch_segment_preview_lightweight(_seg(), site_cfg={"provider_priority": ["pexels"]})
    assert r["result_url"] == "http://p/prison0" and "ia_nota" not in r and buscas == [("prison", 1)]


def test_fases_0_e_1_trocam_as_buscas(api, monkeypatch):
    import app as A
    api.fn = lambda p: (200, ok({"tema": "Escobar", "epoca": "1980s", "tom": "sério", "personagens": [], "lugares": [], "glossario": [],
                                 "evitar_sempre": [], "visual_geral": ""}) if "FICHA VISUAL" in p["system"][0]["text"] else
                        ok({"trechos": [{"n": 1, "buscas": ["Pablo Escobar 1980s", "drug lord portrait"], "midia": "foto", "visual": "retrato"}]}))
    job = {"segments": [{"start": 0, "end": 4, "text": "Ele era o maior traficante."}], "pending_segments": [{"start": 0, "end": 4, "query": "man"}],
           "language": "pt"}
    segs = [_seg(query="man"), _seg(query="x", provider="youtube")]
    job["pending_segments"].append({"start": 0, "end": 4, "query": "x"})
    ctxs = A._ia_preparar_buscas("j1", job, segs)
    assert segs[0].query == "Pablo Escobar 1980s" and segs[0].alternativas == ["drug lord portrait", "man"] and segs[1].query == "x"
    assert job["pending_segments"][0]["ia_busca_original"] == "man" and job["ia"]["ficha"]["tema"] == "Escobar"
    assert ctxs[0]["ficha"]["tema"] == "Escobar" and "traficante" in ctxs[0]["fala"]


def test_sem_ia_preparar_nao_faz_nada(tmp_path, monkeypatch):
    import app as A
    monkeypatch.setattr(ia, "CONFIG_PATH", str(tmp_path / "x.json"))
    segs = [_seg(query="man")]
    assert A._ia_preparar_buscas("j", {"segments": []}, segs) is None and segs[0].query == "man"


# ------------------------------------------------------------------ YouTube
def test_youtube_ordem_e_momento(api):
    import ia_midia
    api.respostas = [(200, ok({"videos": [{"n": 1, "nota": 2, "motivo": "react"}, {"n": 2, "nota": 9, "motivo": "canal oficial"}], "busca_melhor": "x"}))]
    r = ia_midia.ordenar_youtube([{"titulo": "REACT"}, {"titulo": "Entrevista oficial"}], "ele disse", "termo")
    assert [v["titulo"] for v in r["resultados"]] == ["Entrevista oficial", "REACT"] and r["resultados"][0]["ia_nota"] == 9
    api.respostas = [(200, ok({"achou": True, "inicio": 751.2, "fim": 759.8, "frase": "eu não me arrependo", "traducao": "",
                               "confianca": 0.85, "outros_momentos": []}))]
    m = ia_midia.achar_momento([{"inicio": 750.0, "fim": 760.0, "texto": "eu não me arrependo"}], "ele disse que não se arrepende")
    assert m["achou"] and m["inicio"] == 750.8 and m["fim"] == 760.2  # folga de 0,4 s
    assert "[12:30 = 750.0s]" in json.dumps(api.pedidos[-1]["messages"], ensure_ascii=False)


def test_rota_momento(api, monkeypatch):
    import app as A
    A.app.config["TESTING"] = True
    jid = "iayt"
    A._JOBS[jid] = {"job_id": jid, "segments": [{"start": 0, "end": 5, "text": "ele falou da guerra"}],
                    "pending_segments": [{"start": 0, "end": 5, "provider": "youtube", "query": "discurso", "media_type": "video"}]}
    A._youtube_itens_sincronizar(A._JOBS[jid])
    monkeypatch.setattr(A, "_legenda_com_tempos", lambda url, pasta, **k: {"linhas": [{"inicio": 10.0, "fim": 14.0, "texto": "a guerra acabou"}], "fonte": "teste"})
    api.respostas = [(200, ok({"achou": True, "inicio": 10, "fim": 14, "frase": "a guerra acabou", "traducao": "", "confianca": 0.9, "outros_momentos": []}))]
    r = A.app.test_client().post(f"/job/{jid}/youtube/item/seg-0/momento", json={"url": "https://youtu.be/abcdefghijk"}).get_json()
    assert r["ok"] and r["achou"] and r["inicio"] == 9.6 and r["fonte_legenda"] == "teste"


# ------------------------------------------------------------------ Modelos de vídeo
def test_duplicadas_por_hash(tmp_path):
    from PIL import Image
    import ia_dossies
    a = tmp_path / "a.png"
    im = Image.new("RGB", (400, 300))
    for x in range(400):
        for y in range(0, 300, 7):
            im.putpixel((x, y), (x % 255, 90, 200))
    im.save(a)
    im.resize((200, 150)).save(tmp_path / "b.png")
    Image.new("RGB", (400, 300), (250, 250, 250)).save(tmp_path / "c.png")
    d = ia_dossies.duplicadas({"I1": str(a), "I2": str(tmp_path / "b.png"), "I3": str(tmp_path / "c.png")})
    assert d == {"I2": "I1"}


def test_dossie_ficha_das_imagens(api, tmp_path, monkeypatch):
    from PIL import Image
    import dossies as ds
    p = ds.criar(str(tmp_path), "Caso X")
    pasta = ds.pasta_midias(str(tmp_path), p["id"])
    os.makedirs(pasta, exist_ok=True)
    for nome, cor in (("f1.png", (10, 20, 30)), ("f2.png", (200, 100, 10))):
        img = Image.new("RGB", (300, 200), cor)
        for x in range(0, 300, 3):
            img.putpixel((x, x % 200), (255 - cor[0], 0, 0))
        img.save(os.path.join(pasta, nome))
    ds.adicionar_midia(p, tipo="foto", origem="url", arquivo="f1.png", legenda="o suspeito João X", og={"titulo": "Matéria"}, usar="og")
    ds.adicionar_midia(p, tipo="foto", origem="url", arquivo="f2.png", og={"titulo": "Matéria"}, usar="og")
    p["fontes"] = [{"id": "F1", "texto": "texto da matéria", "titulo": "Matéria"}]
    ds.salvar(str(tmp_path), p)
    api.respostas = [(200, ok({"imagens": [
        {"id": "I1", "descricao": "foto policial de homem de bigode", "quem_ou_o_que": "provavelmente o suspeito João X", "tipo": "foto_real",
         "texto_na_imagem": "POLÍCIA 1987", "epoca": "anos 80", "util": True, "sensivel": "nao", "qualidade": "boa"},
        {"id": "I2", "descricao": "banner de assinatura", "quem_ou_o_que": "", "tipo": "anuncio", "texto_na_imagem": "ASSINE",
         "epoca": "", "util": False, "sensivel": "nao", "qualidade": "boa"}]}))]
    r = ds.ia_analisar_imagens(str(tmp_path), p["id"])
    assert r["ok"] and r["fichas"] == 2 and r["descartadas"] == 1
    p = ds.carregar(str(tmp_path), p["id"])
    i1, i2 = ds.midia(p, "I1"), ds.midia(p, "I2")
    assert "foto policial" in ds.o_que_e(i1) and "POLÍCIA 1987" in ds.o_que_e(i1) and i2["descartada"]
    pr = ds.prompt_roteiro(p)
    assert "- I1 (" in pr and "- I2 (" not in pr
    api.respostas = [(200, ok({"problemas": [{"marca": "I1", "frase": "a vítima", "motivo": "é o suspeito", "sugestao": ""}]}))]
    p["resultado"] = {"roteiro": "[I1] A vítima chegou em casa."}
    assert ds.ia_conferir_marcas(p)[0]["motivo"] == "é o suspeito"


def test_pdf_escaneado_lido_pela_ia(api, tmp_path, monkeypatch):
    import dossies as ds
    import ia_dossies
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(200, 200)
    w.add_blank_page(200, 200)
    cam = tmp_path / "F1_laudo.pdf"
    with open(cam, "wb") as f:
        w.write(f)
    with pytest.raises(ds.DossieError):  # sem IA: o erro de sempre
        ia.salvar_config({"ativo": False})
        ds.ler_arquivo(str(cam))
    ia.salvar_config({"ativo": True})
    api.respostas = [(200, ok({"paginas": [{"pagina": 1, "texto": "LAUDO PERICIAL nº 12"}, {"pagina": 2, "texto": "conclusão: homicídio"}]}))]
    d = ds.ler_arquivo(str(cam))
    assert "[pág. 1] LAUDO PERICIAL nº 12" in d["texto"] and "IA" in d["site"]
    assert api.pedidos[-1]["messages"][0]["content"][0]["type"] == "document"
    api.respostas = [(200, ok({"fatos": [{"data": "1987", "fato": "prisão", "pagina": "41"}], "pessoas": [], "lugares": [], "citacoes": [],
                               "contradicoes": [], "imagens_uteis": []}))]
    c = ia_dossies.condensar("[pág. 41] foi preso em 1987")
    assert "prisão (pág. 41)" in ia_dossies.condensado_para_prompt(c)


# ------------------------------------------------------------------ prompt de edição em partes (opcional)
def test_partes_do_prompt_de_edicao():
    import prompt_edicao as pe
    segs = [{"start": i * 30.0, "end": i * 30.0 + 30} for i in range(120)]  # 1 hora
    partes = pe.dividir_partes(segs, 3600, 12)
    assert len(partes) == 5 and partes[0]["ini"] == 0 and partes[-1]["fim"] == 3600 and all(p["n"] == 5 for p in partes)
    assert all(abs((p["fim"] - p["ini"]) - 720) <= 30 for p in partes)
    assert len(pe.dividir_partes(segs[:20], 600, 12)) == 1  # vídeo curto: um prompt só
    j = pe.juntar_planos([{"trechos": [{"indice": 1, "efeito": "a"}], "destaques": [{"start": 50}], "filtro_cor": "noir", "avisos": ["x"]},
                          {"trechos": [{"indice": 30, "efeito": "b"}], "destaques": [{"start": 900}], "filtro_cor": "vhs", "observacoes": "ok"}])
    assert [t["indice"] for t in j["trechos"]] == [1, 30] and len(j["destaques"]) == 2 and j["filtro_cor"] == "noir"
    assert j["avisos"] == ["Parte 1: x"] and "Parte 2: ok" in j["observacoes"]


def test_rotas_de_partes(api):
    import app as A
    A.app.config["TESTING"] = True
    jid = "iaed"
    segs = [{"start": i * 30.0, "end": i * 30.0 + 30, "provider": "pexels", "query": f"q{i}", "media_type": "video"} for i in range(60)]
    A._JOBS[jid] = {"job_id": jid, "total_duration": 1800.0, "pending_segments": segs, "segments":
                    [{"start": i * 30.0, "end": i * 30.0 + 30, "text": f"fala {i}"} for i in range(60)], "media_library": []}
    c = A.app.test_client()
    d = c.post(f"/job/{jid}/edicao/prompt", json={"direcao": "sys_tudo", "segmentos": segs, "partes_min": 10}).get_json()
    assert len(d["partes"]) == 3
    p2 = d["partes"][1]["prompt"]
    assert "PARTE 2 de 3" in p2 and "T25 [" in p2 and "T5 [" not in p2 and "NÃO mande filtro_cor" in p2 and "fala 25" in p2 and "fala 3]" not in p2
    r = c.post(f"/job/{jid}/edicao/resposta", json={"textos": [json.dumps({"trechos": [{"trecho": 2, "efeito": "zoom_in"}]}),
                                                                 json.dumps({"trechos": [{"trecho": 30, "efeito": "zoom_in"}]})], "n_trechos": 60}).get_json()
    assert r["ok"] and [t["indice"] for t in r["trechos"]] == [1, 29]
    api.respostas = [(200, ok('{"trechos": []}'))]
    r = c.post(f"/job/{jid}/edicao/ia", json={"prompt": "edite"}).get_json()
    assert r["ok"] and r["texto"] == '{"trechos": []}' and "output_config" in api.pedidos[-1]


# ------------------------------------------------------------------ página e links
def test_pagina_ia_e_links(api):
    import app as A
    A.app.config["TESTING"] = True
    c = A.app.test_client()
    html = c.get("/ia").get_data(as_text=True)
    assert "Claude Haiku 5.5" in html and "sk-ant-t…" in html and "123456789" not in html and "Juiz visual" in html
    r = c.post("/ia", data={"ativo": "on", "provedor": "claude", "modelo": "claude-haiku-5-5", "chave": "", "rec_juiz": "on",
                            "nota_minima": "6", "candidatos": "8", "limite_usd": "3"})
    assert r.status_code == 200 and ia.config()["chave"] == "sk-ant-teste-123456789" and ia.config()["nota_minima"] == 6
    assert ia.config()["recursos"]["juiz"] and not ia.config()["recursos"]["buscas"]
    st = c.get("/ia/status").get_json()
    assert st["pode"]["juiz"] and not st["pode"]["buscas"]
    assert "🤖 IA nas buscas e modelos" in c.get("/").get_data(as_text=True)
    assert "IA na edição e nos Modelos de vídeo" in c.get("/settings").get_data(as_text=True)
    api.respostas = [(200, ok({"ok": True}))]
    assert c.post("/ia/testar").get_json()["ok"]


# ------------------------------------------------------------------ Wikipedia (caminho melhorado)
def test_wikipedia_filtrada():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
    from wikipedia_api_client import WikipediaAPIClient

    class R:
        def __init__(self, d):
            self.d = d

        def raise_for_status(self):
            pass

        def json(self):
            return self.d

    def info(w, h, cat=""):
        return {"imageinfo": [{"url": "u", "thumburl": "t", "width": w, "height": h, "mime": "image/jpeg",
                               "extmetadata": {"Categories": {"value": cat}}}]}
    respostas = [
        R({"query": {"pages": {"1": {"pageimage": "Escobar_mugshot.jpg"}}}}),
        R({"query": {"pages": {"1": {"images": [{"title": "File:Flag of Colombia.svg"}, {"title": "File:Coat of arms of Medellin.png"},
                                                  {"title": "File:A street.jpg"}, {"title": "File:Escobar mugshot.jpg"}, {"title": "File:Tiny.jpg"}]}}}}),
        R({"query": {"normalized": [], "pages": {"1": dict(info(800, 1000), title="File:Escobar mugshot.jpg"),
                                                  "2": dict(info(1200, 800), title="File:A street.jpg"), "3": dict(info(100, 80), title="File:Tiny.jpg")}}}),
    ]

    class S:
        headers = {}

        def get(self, url, params=None, timeout=None):
            return respostas.pop(0)
    c = WikipediaAPIClient(delay=0)
    c.session = S()
    imgs = c.get_images_filtradas("Pablo Escobar")
    assert [i.arquivo for i in imgs] == ["File:Escobar mugshot.jpg", "File:A street.jpg"]


def test_direcao_de_arte_da_parte1_vai_pras_outras(api):
    import app as A
    import prompt_edicao as pe
    A.app.config["TESTING"] = True
    jid = "iaarte"
    segs = [{"start": i * 30.0, "end": i * 30.0 + 30, "provider": "pexels", "query": f"q{i}", "media_type": "video"} for i in range(60)]
    A._JOBS[jid] = {"job_id": jid, "total_duration": 1800.0, "pending_segments": segs, "segments":
                    [{"start": i * 30.0, "end": i * 30.0 + 30, "text": f"fala {i}"} for i in range(60)], "media_library": []}
    c = A.app.test_client()
    d = c.post(f"/job/{jid}/edicao/prompt", json={"direcao": "sys_tudo", "segmentos": segs, "partes_min": 10}).get_json()
    assert '"direcao_arte"' in d["partes"][0]["prompt"] and "ainda não veio" in d["partes"][1]["prompt"] and d["arte"] == ""
    import dp_destaques
    est = next(iter(dp_destaques.catalogo()))
    r1 = json.dumps({"filtro_cor": "noir", "paleta": {"primaria": "#E50914", "secundaria": "#FFFFFF", "acento": "#B81D24"},
                     "trechos": [{"trecho": 2, "transition": "dissolve"}, {"trecho": 5, "transition": "dissolve"}],
                     "destaques": [{"estilo": est, "texto": "fala 3", "palavra": "fala", "start": 90.0, "fonte": "anton", "zona": "terco_inf"}],
                     "direcao_arte": {"resumo": "documental vermelho e preto", "regras": ["só caixa alta nos números"]}})
    d = c.post(f"/job/{jid}/edicao/prompt", json={"direcao": "sys_tudo", "segmentos": segs, "partes_min": 10, "resposta_parte1": r1}).get_json()
    p2 = d["partes"][1]["prompt"]
    assert "DIREÇÃO DE ARTE JÁ DECIDIDA NA PARTE 1" in p2 and "noir" in p2 and "#E50914" in p2 and "dissolve (2x)" in p2
    assert est in p2 and "anton" in p2 and "terco_inf" in p2 and "documental vermelho e preto" in p2 and "só caixa alta nos números" in p2
    assert "DIREÇÃO DE ARTE JÁ DECIDIDA" not in d["partes"][0]["prompt"]
    d = c.post(f"/job/{jid}/edicao/prompt", json={"direcao": "sys_tudo", "segmentos": segs, "partes_min": 10, "resposta_parte1": "isso não é json {"}).get_json()
    assert d["erro_arte"] and d["arte"] == ""
    assert pe.arte_da_parte1({}) == ""


def test_chave_errada_do_navegador_nao_substitui_a_boa(api):
    import app as A
    A.app.config["TESTING"] = True
    c = A.app.test_client()
    html = c.post("/ia", data={"ativo": "on", "provedor": "claude", "modelo": "claude-haiku-5-5", "chave": "AQ.Ab8RNsenhaDoNavegador"}).get_data(as_text=True)
    assert ia.config()["chave"] == "sk-ant-teste-123456789" and "não parece uma chave" in html
    ia.salvar_config({"chave": "AQ.Ab8RNantiga"})
    assert "não parece uma chave do Claude" in c.get("/ia").get_data(as_text=True)
    c.post("/ia", data={"ativo": "on", "provedor": "claude", "modelo": "claude-haiku-5-5", "chave": "sk-ant-nova-chave"})
    assert ia.config()["chave"] == "sk-ant-nova-chave" and 'type="password"' not in c.get("/ia").get_data(as_text=True)


def test_gerar_roteiro_com_a_ia(api):
    import app as A
    A.app.config["TESTING"] = True
    c = A.app.test_client()
    api.respostas = [(200, ok('{"roteiro": "Era uma vez."}'))]
    r = c.post("/ia/gerar", json={"prompt": "escreva o roteiro"}).get_json()
    assert r["ok"] and r["texto"] == '{"roteiro": "Era uma vez."}' and api.pedidos[-1]["max_tokens"] == 64000
    ia.salvar_config({"recursos": {"roteiros": False}})
    assert c.post("/ia/gerar", json={"prompt": "x"}).status_code == 400
    raiz = os.path.dirname(os.path.abspath(__file__))
    for t in ("dossie_detalhe.html", "venda_detalhe.html", "roteiro_yt_detalhe.html", "modelado_detalhe.html"):
        assert "data-ia-gerar" in open(os.path.join(raiz, "templates", t), encoding="utf-8").read(), t
    assert "/ia/gerar" in open(os.path.join(raiz, "templates", "base.html"), encoding="utf-8").read()


def test_idioma_de_saida_no_fim_e_no_system(api):
    import app as A
    import dossies as ds
    import vendas as vd
    d = {"tema": "Caso", "config": {"modelo": "true_crime", "formato": "caso_completo", "idioma": "en"}, "fontes": [], "midias": [], "roteiro_base": "notas"}
    pr = ds.prompt_roteiro(d)
    assert pr.rstrip().endswith("(output language code: en)") and "Write EVERY text value of the JSON in English" in pr
    pv = vd.prompt_roteiro({"id": "x", "produto": {"titulo": "Garrafa"}, "config": {"idioma": "es"}, "midias": [], "link": ""})
    assert pv.rstrip().endswith("(output language code: es)")
    assert "(output language code: pt)" in ds.prompt_roteiro(dict(d, config=dict(d["config"], idioma="pt")))
    A.app.config["TESTING"] = True
    api.respostas = [(200, ok('{"roteiro": "Once upon a time."}'))]
    A.app.test_client().post("/ia/gerar", json={"prompt": pr})
    assert "OUTPUT LANGUAGE: English" in api.pedidos[-1]["system"][0]["text"]
    api.respostas = [(200, ok('{"roteiro": "Era uma vez."}'))]
    A.app.test_client().post("/ia/gerar", json={"prompt": "sem idioma"})
    assert "OUTPUT LANGUAGE" not in api.pedidos[-1]["system"][0]["text"]
