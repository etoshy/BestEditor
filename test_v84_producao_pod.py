"""v84_122 — 🏭 Produção no pod: roteiros → narração/transcrição/imagens no pod → projeto com cenas ⏳ pendentes."""
import json
import os
import time

import pytest

import cenas_lote as cl


def _transcricao(n_frases=12, dur=2.6):
    segs, t = [], 0.0
    for k in range(n_frases):
        palavras = f"Frase número {k} com algumas palavras aqui.".split()
        passo = dur / len(palavras)
        ws = [{"word": w, "start": round(t + i * passo, 3), "end": round(t + (i + 1) * passo - 0.02, 3)} for i, w in enumerate(palavras)]
        segs.append({"start": t, "end": t + dur, "text": " ".join(palavras), "words": ws})
        t += dur + 0.3
    return segs


# ------------------------------------------------------------------ cenas
def test_cortar_cenas_cobre_tudo_sem_buraco_e_no_ritmo():
    segs = _transcricao()
    cenas = cl.cortar_cenas(segs, 5.0, total=35.0)
    assert cenas[0]["start"] == 0.0 and cenas[-1]["end"] == 35.0
    assert all(abs(a["end"] - b["start"]) < 1e-6 for a, b in zip(cenas, cenas[1:]))
    assert all(2.9 <= c["end"] - c["start"] <= 7.5 for c in cenas[:-1])
    assert all(c["fala"] for c in cenas)


def test_escolher_pega_as_dificeis_espacadas():
    notas = [9, 9, 9, 9, 1, 1, 8, 8, 0, 0, 7, 2, 2, 2, 6, 6, 1, 1, 9, 2]
    esc = cl.escolher(notas, 0.30)
    assert len(esc) == 6
    assert not any(i + 1 in esc for i in esc)  # nunca duas seguidas
    assert all(notas[i] >= 3 for i in esc)
    assert {0, 18}.issubset(esc)
    assert cl.escolher([1] * 20, 0.3) == set()  # nada difícil: nada vai pro pod
    sem = cl.escolher_sem_ia(30, 0.3)
    assert len(sem) == 9 and not any(i + 1 in sem for i in sem)


def test_descrever_usa_a_ia_em_blocos(monkeypatch):
    import ia_servico
    chamadas = []
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: r == "producao_pod")

    def chamar(recurso, system, conteudo, schema=None, **kw):
        chamadas.append(recurso)
        ns = [int(x) for x in __import__("re").findall(r"^\[(\d+)\]", conteudo, __import__("re").M)]
        return {"cenas": [{"n": n, "visual": f"v{n}", "busca": f"ship {n}", "dificil": n % 10,
                           "prompt_imagem": f"a ghost ship {n}"} for n in ns]}

    monkeypatch.setattr(ia_servico, "chamar", chamar)
    monkeypatch.setattr(cl, "BLOCO_IA", 5)
    cenas = [{"start": i * 5.0, "end": i * 5.0 + 5, "fala": f"fala {i}"} for i in range(12)]
    info = cl.descrever(cenas, "roteiro", "pt")
    assert len(chamadas) == 3 and set(chamadas) == {"producao_pod"} and len(info) == 12
    esc = cl.escolher([info[i + 1]["dificil"] for i in range(12)], 0.3)
    js = cl.montar_json(cenas, info, esc, "film grain")
    rp = [s for s in js["segments"] if s["provider"] == "runpod"]
    assert len(rp) == len(esc) and all(s["media_type"] == "image" and s["query"].endswith("film grain") for s in rp)
    ad = [s for s in js["segments"] if s["provider"] == "adiado"]
    assert all(s["query"].startswith("ship") and s["visual"].startswith("v") for s in ad)


def test_json_passa_na_validacao_do_site():
    from prompt_builder import parse_ai_response
    cenas = cl.cortar_cenas(_transcricao(), 5.0, total=35.0)
    js = cl.montar_json(cenas, {}, cl.escolher_sem_ia(len(cenas), 0.3))
    parsed = parse_ai_response(json.dumps(js), valid_providers=["runpod", "adiado"], total_duration=35.0)
    assert {s.provider for s in parsed.segments} == {"runpod", "adiado"}


# ------------------------------------------------------------------ o lote inteiro (pod falso)
@pytest.fixture
def pod_falso(monkeypatch, tmp_path):
    import pod_studio
    import producao_pod as pp
    import runpod_gerador as rp
    monkeypatch.setattr(pp, "PASTA", str(tmp_path / "pp"))
    monkeypatch.setenv("RUNPOD_DADOS_DIR", str(tmp_path / "rp"))
    monkeypatch.setattr(pp, "INTERVALO_TICK", 0.05)
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: False)
    estado = {"jobs": {}, "n": 0, "pedidos": []}

    def novo(tipo, **dados):
        estado["n"] += 1
        jid = f"{tipo}-{estado['n']}"
        estado["jobs"][jid] = dict(dados, tipo=tipo, consultas=0)
        estado["pedidos"].append((tipo, dados))
        return jid

    monkeypatch.setattr(pod_studio, "enviar_narracao", lambda texto, **kw: novo("voz", texto=texto, **kw))
    monkeypatch.setattr(pod_studio, "enviar_imagens", lambda itens, **kw: novo("img", itens=itens, **kw))

    def job(jid, cfg=None):
        j = estado["jobs"][jid]
        j["consultas"] += 1
        if j["consultas"] < 2:
            return {"status": "em_andamento", "progresso": {"feito": 0, "total": 1}}
        if j["tipo"] == "voz":
            return {"status": "concluido", "arquivos": ["narracao.wav", "narracao.transcricao.json", "resumo.json"]}
        return {"status": "concluido", "arquivos": [it["nome"] + ".png" for it in j["itens"]]}

    def baixar(jid, arquivo, destino, cfg=None):
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        if arquivo.endswith(".json"):
            with open(destino, "w", encoding="utf-8") as f:
                json.dump(_transcricao(), f)
        elif arquivo.endswith(".wav"):
            import wave
            with wave.open(destino, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(b"\0\0" * 8000 * 35)
        else:
            open(destino, "wb").write(b"PNG")
        return destino

    monkeypatch.setattr(pod_studio, "job", job)
    monkeypatch.setattr(pod_studio, "baixar", baixar)
    criados = []

    def registrar(item, lote, wav, segments):
        return {"gv_id": "gv" + item["id"], "zip": str(tmp_path / f"{item['id']}.zip"), "total": 35.0}

    def criar_projeto(item, lote, zip_path, resposta, ficha=None):
        criados.append({"item": item, "resposta": resposta, "zip": zip_path})
        return "job" + item["id"]

    pp.configurar(criar_projeto, registrar)
    return {"pp": pp, "estado": estado, "criados": criados, "rp": rp}


def _esperar(pp, lid, segundos=10):
    fim = time.time() + segundos
    while time.time() < fim:
        if pp.carregar(lid)["status"] != "rodando":
            return pp.carregar(lid)
        time.sleep(0.05)
    raise AssertionError("o lote não terminou")


def test_lote_completo_com_dois_roteiros(pod_falso):
    pp, est = pod_falso["pp"], pod_falso["estado"]
    lote = pp.criar([{"origem": "texto", "titulo": "A", "texto": "Era uma vez um navio. [[INSCREVA]] Ninguém a bordo.",
                      "idioma": "pt", "exaggeration": 0.8, "cfg_weight": 0.3},
                     {"origem": "texto", "titulo": "B", "texto": "Once upon a time [sigh] a ship drifted away.",
                      "motor": "chatterbox_turbo", "idioma": "pt"}],
                    {"intervalo": 5, "pct": 30, "orientacao": "9:16"}, pod_url="https://x-8000.proxy.runpod.net")
    l = _esperar(pp, lote["id"])
    assert l["status"] == "concluido" and all(it["estado"] == "pronto" for it in l["itens"])
    vozes = [d for t, d in est["pedidos"] if t == "voz"]
    assert vozes[0]["exaggeration"] == 0.8 and vozes[0]["cfg_weight"] == 0.3 and vozes[0]["idioma"] == "pt"
    assert "[[" not in vozes[0]["texto"] and "INSCREVA" not in vozes[0]["texto"]  # o marcador não é narrado
    assert vozes[1]["motor"] == "chatterbox_turbo" and vozes[1]["idioma"] == "en" and "[sigh]" in vozes[1]["texto"]
    imgs = [d for t, d in est["pedidos"] if t == "img"]
    assert imgs and imgs[0]["largura"] == 720 and imgs[0]["altura"] == 1280
    cr = pod_falso["criados"]
    assert len(cr) == 2 and cr[0]["resposta"]["segments"][0]["start"] == 0.0
    assert cr[0]["resposta"]["segments"][-1]["end"] == 35.0 and cr[0]["zip"].endswith(".zip")
    assert all(it["gv_id"] for it in l["itens"])
    # as imagens do pod entram no cache da fonte runpod: o editor acha pronta, sem gerar de novo
    rp = pod_falso["rp"]
    s = next(x for x in cr[0]["resposta"]["segments"] if x["provider"] == "runpod")
    r = rp.gerar(s["query"], "imagem", {"orientation": "9:16", "runpod_api_key": "", "runpod_modo": "endpoints"})
    assert r["reaproveitado"] and r["modelo"] == "pod:z-image-turbo"


def test_erro_no_pod_e_tentar_de_novo(pod_falso, monkeypatch):
    pp = pod_falso["pp"]
    import pod_studio
    real = pod_studio.job
    monkeypatch.setattr(pod_studio, "job", lambda jid, cfg=None: {"status": "erro", "mensagem": "sem VRAM", "erros": []}
                        if jid.startswith("voz") else real(jid, cfg))
    lote = pp.criar([{"origem": "texto", "titulo": "A", "texto": "Uma frase qualquer com palavras suficientes aqui."}], {})
    l = _esperar(pp, lote["id"])
    assert l["itens"][0]["estado"] == "erro" and "sem VRAM" in l["itens"][0]["erro"]
    monkeypatch.setattr(pod_studio, "job", real)
    pp.tentar_de_novo(lote["id"], l["itens"][0]["id"])
    assert _esperar(pp, lote["id"])["itens"][0]["estado"] == "pronto"


# ------------------------------------------------------------------ no site: projeto, editor e completar
@pytest.fixture
def site(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNPOD_DADOS_DIR", str(tmp_path / "rp"))
    import site_config
    monkeypatch.setattr(site_config, "CONFIG_PATH", str(tmp_path / "cfg.json"))
    import app as A
    monkeypatch.setattr(A, "_job_dir", lambda jid: str(tmp_path / "jobs" / jid))
    monkeypatch.setattr(A, "VOZES_DIR", str(tmp_path / "vozes"))
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: False)
    vistos = []

    def falso(segment, **kw):
        vistos.append((segment.provider, segment.query))
        return {"ok": True, "thumbnail_url": "/t.jpg", "result_url": "u", "label": segment.provider, "error": None,
                "provider": segment.provider}

    monkeypatch.setattr(A, "fetch_segment_preview_lightweight", falso)

    def imagens_falso(itens, pasta, cfg, cache=None, on_result=None):  # buscadores de imagem (bing…): todos de uma vez
        for i, s in itens:
            vistos.append((s.provider, s.query))
            on_result(i, {"ok": True, "path": "/x.jpg", "engine": s.provider, "title": s.query})

    monkeypatch.setattr(A, "prefetch_browser_images", imagens_falso)
    monkeypatch.setattr(A, "generate_waveform_image", lambda *a, **k: None)
    monkeypatch.setattr(A, "_prebaixar_iniciar", lambda *a, **k: None)
    return A, vistos


def _wav(caminho, segundos=35):
    import wave
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 8000 * segundos)
    return str(caminho)


def _esperar_job(job):
    fim = time.time() + 10
    while job["status"] == "buscando_previas" and time.time() < fim:
        time.sleep(0.05)


def _texto_roteiro():
    return " ".join(f"Frase número {k} com algumas palavras aqui." + (" [[INSCREVA]]" if k == 3 else "") for k in range(12))


def test_narracao_vira_geracao_do_gerador_de_voz_com_zip(site, tmp_path):
    A, _ = site
    import zipfile
    item = {"id": "i1", "titulo": "T", "idioma": "pt", "texto": _texto_roteiro(), "origem": "texto", "motor": "chatterbox",
            "perfil": "joao"}
    r = A._registrar_narracao_do_pod(item, {"config": {"legenda": {"max_palavras": 4}}}, _wav(tmp_path / "a.wav"),
                                      _transcricao())
    nomes = zipfile.ZipFile(r["zip"]).namelist()
    assert set(nomes) == {"narracao.wav", "info.json", "legenda.srt", "chamadas.json"}
    z = zipfile.ZipFile(r["zip"])
    assert json.loads(z.read("info.json"))["idioma"] == "pt"
    srt = z.read("legenda.srt").decode()
    assert "Frase número 0" in srt and "[[" not in srt
    assert json.loads(z.read("chamadas.json"))["chamadas"][0]["tipo"] == "inscreva"
    assert abs(r["total"] - _transcricao()[-1]["words"][-1]["end"]) < 0.1  # fim da legenda = fim da fala
    import historico_voz
    h = historico_voz.obter(A.VOZES_DIR, r["gv_id"])
    assert h and h["srt"] and h["voz"].startswith("🖥️ pod")
    assert A.app.test_client().get(f"/gerar-voz/baixar-zip/{r['gv_id']}").status_code == 200


def test_projeto_criado_com_pendentes_e_completar(site, tmp_path):
    A, vistos = site
    segs = _transcricao()
    item = {"id": "i1", "titulo": "Mary Celeste", "idioma": "pt", "texto": _texto_roteiro(), "origem": "texto"}
    lote = {"id": "l1", "config": {"intervalo": 5, "orientacao": "16:9"}}
    reg = A._registrar_narracao_do_pod(item, lote, _wav(tmp_path / "a.wav"), segs)
    cenas = cl.cortar_cenas(segs, 5.0, total=reg["total"])
    esc = cl.escolher_sem_ia(len(cenas), 0.3)
    resposta = cl.montar_json(cenas, {}, esc)
    jid = A._criar_job_producao(item, lote, reg["zip"], resposta, ficha={"tema": "navio"})
    job = A._JOBS[jid]
    _esperar_job(job)
    pend, pv = job["pending_segments"], job["segment_previews"]
    assert job["status"] == "pronto_para_editar" and job["nome_projeto"] == "Mary Celeste"
    assert job["providers"] == ["runpod"] and job["ia"]["ficha"] == {"tema": "navio"}
    assert job["segments"][0]["text"].startswith("Frase número 0")  # a legenda pronta do .zip (sem transcrever de novo)
    assert {p for p, q in vistos} == {"runpod"}  # só as cenas do pod foram buscadas
    assert all(p.get("adiado") for s, p in zip(pend, pv) if s["provider"] == "adiado")
    assert job["chamadas"] and job["chamadas"][0]["tipo"] == "inscreva"
    assert A.pendentes_info(job)["n"] == len(cenas) - len(esc)

    # a página do editor mostra o quadro "Completar cenas pendentes"
    c = A.app.test_client()
    html = c.get(f"/job/{jid}/edit-segments").get_data(as_text=True)
    assert "Completar cenas pendentes" in html

    vistos.clear()
    r = c.post(f"/job/{jid}/completar-pendentes", json={"fontes": ["pexels", "bing"]})
    assert r.status_code == 200 and r.get_json()["cenas"] == len(cenas) - len(esc)
    _esperar_job(job)
    assert {p for p, q in vistos} == {"pexels", "bing"} and len(vistos) == len(cenas) - len(esc)
    assert all(s["media_type"] == "image" for s in job["pending_segments"] if s["provider"] == "bing")
    assert A.pendentes_info(job)["n"] == 0 and all((p or {}).get("ok") for p in job["segment_previews"])
    assert c.post(f"/job/{jid}/completar-pendentes", json={"fontes": ["pexels"]}).status_code == 400


def test_completar_com_ia_manda_pro_youtube_so_se_marcado(site, tmp_path, monkeypatch):
    A, vistos = site
    import ia_midia
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: r == "buscas")
    monkeypatch.setattr(ia_midia, "ficha_visual", lambda *a, **k: {"tema": "x"})
    monkeypatch.setattr(ia_midia, "buscas_melhores", lambda trechos, *a, **k: {
        t["n"]: {"buscas": ["captain speech interview", "old captain"], "midia": "youtube", "real": True, "visual": "capitão"}
        for t in trechos})
    monkeypatch.setattr(A, "_youtube_buscar_pendentes", lambda jid: None)
    segs = _transcricao()
    item = {"id": "i2", "titulo": "T", "idioma": "pt", "texto": _texto_roteiro(), "origem": "texto"}
    reg = A._registrar_narracao_do_pod(item, {"config": {}}, _wav(tmp_path / "b.wav"), segs)
    cenas = cl.cortar_cenas(segs, 5.0, total=reg["total"])
    jid = A._criar_job_producao(item, {"id": "l1", "config": {}}, reg["zip"], cl.montar_json(cenas, {}, set()), None)
    job = A._JOBS[jid]
    _esperar_job(job)
    A._completar_pendentes(jid, ["pexels"])  # sem youtube marcado: fica no pexels com a busca da IA
    _esperar_job(job)
    assert all(s["provider"] == "pexels" and s["query"] == "captain speech interview" for s in job["pending_segments"])


def test_paginas_da_producao(site, tmp_path, monkeypatch):
    A, _ = site
    import producao_pod as pp
    monkeypatch.setattr(pp, "PASTA", str(tmp_path / "pp2"))
    monkeypatch.setattr(pp, "garantir_runner", lambda: None)
    c = A.app.test_client()
    html = c.get("/producao-pod").get_data(as_text=True)
    assert "Produção no pod" in html and "Aplicar a todos" in html
    r = c.post("/producao-pod/criar", json={"itens": [{"origem": "texto", "titulo": "X", "texto": "um dois três quatro cinco seis"}],
                                            "config": {"pct": 99}, "pod_url": "https://p-8000.proxy.runpod.net",
                                            "nome": "Meu lote"})
    lid = r.get_json()["id"]
    assert pp.carregar(lid)["config"]["pct"] == 99  # teto de 100% (v84_141)
    assert "Meu lote" in c.get(f"/producao-pod/{lid}").get_data(as_text=True)
    est = c.get(f"/producao-pod/{lid}/estado").get_json()
    assert est["itens"][0]["estado"] == "aguardando"
    assert c.post("/producao-pod/criar", json={"itens": []}).status_code == 400
    assert c.post(f"/producao-pod/{lid}/excluir").status_code == 400  # rodando
    c.post(f"/producao-pod/{lid}/cancelar")
    assert c.post(f"/producao-pod/{lid}/excluir").get_json()["ok"]


def test_juiz_nao_troca_imagem_do_pod_por_cartao(monkeypatch):
    import video_assembler as va
    from prompt_builder import VideoSegment
    monkeypatch.setattr(va, "_ia_pode", lambda r: True)
    monkeypatch.setattr(va, "julgar_candidatos_ia", lambda *a, **k: pytest.fail("o juiz não pode julgar a imagem do pod"))
    monkeypatch.setattr(va, "search_candidates", lambda *a, **k: [{"thumbnail": "/t.png", "url": "/runpod/midias/x.png",
                                                                  "label": "runpod", "id": "x"}])
    sg = VideoSegment(start=0, end=5, provider="runpod", query="a ghost ship", media_type="image")
    r = va.fetch_segment_preview_lightweight(sg, site_cfg={"evitar_repeticao_clipes": False}, ia_ctx={"fala": "x"})
    assert r["ok"] and r["provider"] == "runpod" and not r.get("cartao")


def test_por_as_imagens_do_pod_de_volta(site, tmp_path):
    A, vistos = site
    segs = _transcricao()
    item = {"id": "i9", "titulo": "R", "idioma": "pt", "texto": _texto_roteiro(), "origem": "texto"}
    reg = A._registrar_narracao_do_pod(item, {"config": {}}, _wav(tmp_path / "c.wav"), segs)
    cenas = cl.cortar_cenas(segs, 5.0, total=reg["total"])
    esc = cl.escolher_sem_ia(len(cenas), 0.3)
    jid = A._criar_job_producao(item, {"id": "l9", "config": {}}, reg["zip"], cl.montar_json(cenas, {}, esc), None)
    job = A._JOBS[jid]
    _esperar_job(job)
    k = sorted(esc)[0]
    # como ficava antes: o juiz trocou a imagem do pod por um cartão
    job["pending_segments"][k].update(override_source={"source": "local_file", "value": "/x.png", "kind": "image", "cartao": True},
                                      cartao={"texto": "x"})
    job["segment_previews"][k] = {"ok": True, "cartao": True, "provider": "cartao"}
    job["destaques"] = [{"origem": "cartao", "trecho": k, "texto": "x"}]
    assert A.pendentes_info(job)["pod_refazer"] == 1
    vistos.clear()
    assert A.app.test_client().post(f"/job/{jid}/refazer-cenas-pod").get_json()["cenas"] == 1
    _esperar_job(job)
    assert vistos == [("runpod", job["pending_segments"][k]["query"])]
    assert job["segment_previews"][k]["ok"] and not job["segment_previews"][k].get("cartao")
    assert not job["pending_segments"][k].get("override_source") and not job.get("destaques")
    assert A.pendentes_info(job)["pod_refazer"] == 0


def test_galeria_e_imagens_parciais(monkeypatch, tmp_path):
    """👀 v84_144: imagens prontas do pod já vêm pro PC enquanto ele gera, e a galeria mostra com o prompt."""
    import json as _json
    import os as _os
    import time as _time
    import pod_studio
    import producao_pod as pp
    from PIL import Image
    monkeypatch.setattr(pp, "PASTA", str(tmp_path))
    lid, iid = "lotex", "itemx"
    lote = {"id": lid, "nome": "L", "config": {"orientacao": "16:9"}, "pod_url": "http://x",
            "itens": [{"id": iid, "titulo": "T", "estado": "imagens", "pod_img": "img-1", "log": []}]}
    monkeypatch.setattr(pp, "carregar", lambda l: lote)
    monkeypatch.setattr(pp, "_mudar", lambda l, i, **kw: lote["itens"][0].update({k: v for k, v in kw.items() if not k.startswith("_")}))
    monkeypatch.setattr(pp, "_cfg_pod", lambda l: {})
    pasta = pp.pasta_item(lid, iid)
    with open(_os.path.join(pasta, "cenas.json"), "w", encoding="utf-8") as f:
        _json.dump({"segments": [{"start": 0, "end": 5, "provider": "runpod", "query": "a house at night 1971", "visual": "a casa"},
                                 {"start": 5, "end": 10, "provider": "runpod", "query": "face prompt", "rostos": ["John List"]}]}, f)
    with open(_os.path.join(pasta, "rostos.json"), "w", encoding="utf-8") as f:
        _json.dump({"1": [["I1.jpg", "/x"]]}, f)

    def baixar(jid, nome, destino, cfg=None):
        Image.new("RGB", (16, 9)).save(destino)
        return destino
    monkeypatch.setattr(pod_studio, "baixar", baixar)
    pp._BAIXANDO.pop(iid, None)
    pp._baixar_parciais_bg(lid, iid, {"arquivos": ["cena-0001.png", "cena-0002.png", "metadados.json"]})
    for _ in range(50):
        if lote["itens"][0].get("baixadas") == 2:
            break
        _time.sleep(0.05)
    assert lote["itens"][0]["baixadas"] == 2 and len(lote["itens"][0]["recentes"]) == 2
    g = pp.galeria(lid, iid)
    assert [x["cena"] for x in g] == [1, 2] and g[1]["com_referencia"] and g[1]["rostos"] == ["John List"]
    assert g[0]["prompt"] == "a house at night 1971"
