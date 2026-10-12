"""
v84_62 — 📊 Analisador de canal: link do canal → 20 recentes + 20 populares (miniatura, título, duração,
views, data, transcrição do YouTube) → métricas → 🤖 IA diz o que funciona e sugere vídeos.
E o ⛏ Niche Miner numa aba do site (roda como app à parte).
"""
import json
import os
import shutil
import time
from datetime import date

import pytest

import analisador_canal as ac


def _card(vid, titulo, views, dur="12:30", data="2026-09-01"):
    return {"id": vid, "titulo": titulo, "url": f"https://www.youtube.com/watch?v={vid}", "views": views,
            "views_text": f"{views} visualizações", "data_aprox": data, "duracao_s": ac.duracao_s(dur),
            "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}


def _coletor_fake(url, n, log):
    rec = [_card(f"rec{k:08d}", f"O caso {k} que ninguém explica" if k % 2 else f"Tutorial de como sumir {k}",
                 10000 + 1000 * k, data=f"2026-09-{28 - k:02d}") for k in range(n)]
    pop = [_card(f"pop{k:08d}", f"A CIA escondeu {k} segredos?", 900000 - 10000 * k, dur="30:00", data="2025-01-10")
           for k in range(n)]
    pop[0] = dict(rec[0], views=950000)  # um vídeo nas duas listas
    log("coletado (fake)")
    return {"canal": {"nome": "Canal Teste", "inscritos": 200000, "inscritos_text": "200 mil inscritos", "n_videos": 120},
            "recentes": rec, "populares": pop, "fonte": "fake"}


def _transcritor_fake(url, pasta):
    if url.endswith("rec00000003"):
        return {"linhas": [], "erro": "sem legenda"}
    return {"linhas": [{"inicio": 0.0, "fim": 5.0, "texto": "Tu sabia que existe um documento secreto?"},
                       {"inicio": 5.0, "fim": 60.0, "texto": " ".join(["palavra"] * 150)},
                       {"inicio": 70.0, "fim": 120.0, "texto": "fim do vídeo [música]"}]}


def test_link_do_canal():
    assert ac.normalizar_url_canal("@Misterecore") == "https://www.youtube.com/@Misterecore"
    assert ac.normalizar_url_canal("youtube.com/@Misterecore/videos") == "https://www.youtube.com/@Misterecore"
    assert ac.normalizar_url_canal("https://www.youtube.com/channel/UCabcdefghij123/about") == "https://www.youtube.com/channel/UCabcdefghij123"
    for ruim in ("", "https://vimeo.com/x", "https://www.youtube.com/watch?v=abc"):
        with pytest.raises(ac.AnaliseError):
            ac.normalizar_url_canal(ruim)


def test_coleta_metricas_e_transcricoes(tmp_path):
    a = ac.nova(str(tmp_path), "@canal", n=20)
    r = ac.executar(str(tmp_path), a["id"], coletor=_coletor_fake, detalhes=lambda vid: {"likes": 10, "comentarios": 2},
                    transcritor=_transcritor_fake)
    assert r["estado"] == "pronto", r.get("erro")
    a = ac.carregar(str(tmp_path), a["id"])
    assert len(a["recentes"]) == 20 and len(a["populares"]) == 20 and len(a["videos"]) == 39  # 1 repetido
    v0 = a["videos"]["rec00000000"]
    assert v0["listas"] == ["recentes", "populares"] and v0["views"] == 950000 and v0["likes"] == 10
    assert v0["transcricao"]["gancho"].startswith("Tu sabia") and v0["transcricao"]["palavras"] > 150
    assert v0["transcricao"]["ppm"] and "[música]" not in v0["transcricao"]["texto"]
    assert a["videos"]["rec00000003"]["transcricao_erro"] == "sem legenda"
    m = a["metricas"]
    assert m["mediana_recentes"] and m["tracao"] == round(m["mediana_recentes"] / 200000, 3)
    assert m["com_transcricao"] == 38 and m["por_semana"] and m["outliers"][0] == "rec00000000"  # o que está nas duas listas (950 mil)
    assert any(p["id"] == "pergunta" for p in m["padroes_titulo"])


def test_metricas_outlier_e_views_por_dia():
    a = {"canal": {"inscritos": 1000}, "recentes": ["a", "b", "c"], "populares": ["c"],
         "videos": {"a": {"id": "a", "titulo": "A", "views": 100, "data": "2026-09-01"},
                    "b": {"id": "b", "titulo": "B?", "views": 200, "data": "2026-09-08"},
                    "c": {"id": "c", "titulo": "C 3", "views": 1000, "data": "2026-09-15"}}}
    m = ac.metricas(a, hoje=date(2026, 9, 25))
    assert m["mediana_recentes"] == 200 and a["videos"]["c"]["outlier"] == 5.0 and a["videos"]["c"]["views_dia"] == 100.0
    assert m["por_semana"] == 1.0 and m["tracao"] == 0.2 and m["outliers"] == ["c"]


def test_falha_na_coleta_vira_erro_claro(tmp_path):
    a = ac.nova(str(tmp_path), "@vazio")
    r = ac.executar(str(tmp_path), a["id"], coletor=lambda u, n, log: {"canal": {}, "recentes": [], "populares": []})
    assert r["estado"] == "erro" and "Não consegui ler" in r["erro"]


def test_validar_resposta_da_ia():
    texto = "```json\n" + json.dumps({
        "resumo": "Canal de mistérios.", "faz_bem": ["ganchos fortes"], "pode_melhorar": [],
        "titulos": {"formulas": [{"formula": "A [instituição] escondeu [coisa]", "exemplos": ["x"], "desempenho": "×3"}]},
        "thumbs": {"estilo": "rosto + texto vermelho"}, "tipos_de_video": [{"tipo": "Tutorial irônico", "videos": ["ok", "inventado"]}],
        "melhores": [{"id": "ok", "por_que": "outlier ×5"}, {"id": "inventado", "por_que": "?"}],
        "sugestoes": [{"titulo": "Novo vídeo", "tipo": "caso", "por_que": "p", "gancho": "g", "thumb": "t"}, {"tipo": "sem título"}],
    }) + "\n```"
    r = ac.validar_ia(texto, {"ok"})
    assert r["tipos_de_video"][0]["videos"] == ["ok"] and [m["id"] for m in r["melhores"]] == ["ok"]
    assert len(r["sugestoes"]) == 1 and r["titulos"]["nao_funcionam"] == [] and r["thumbs"]["receita"] == ""
    with pytest.raises(ac.AnaliseError):
        ac.validar_ia("não tem json aqui")
    with pytest.raises(ac.AnaliseError):
        ac.validar_ia({"tipos_de_video": []})


def test_prompt_manual_tem_dados_miniaturas_e_formato(tmp_path):
    a = ac.nova(str(tmp_path), "@canal", n=5)
    ac.executar(str(tmp_path), a["id"], coletor=_coletor_fake, detalhes=lambda v: {}, transcritor=_transcritor_fake)
    p = ac.prompt_manual(ac.carregar(str(tmp_path), a["id"]))
    assert "Canal Teste" in p and "MAIS RECENTES" in p and "MAIS POPULARES" in p and "hqdefault.jpg" in p
    assert "Gancho: Tu sabia" in p and '"sugestoes"' in p and "Padrões de título" in p


@pytest.fixture
def ia_on(tmp_path, monkeypatch):
    import ia_servico as ia
    monkeypatch.setattr(ia, "CONFIG_PATH", str(tmp_path / "ia_config.json"))
    monkeypatch.setattr(ia, "USO_PATH", str(tmp_path / "ia_uso.json"))
    monkeypatch.setattr(ia, "CACHE_DIR", str(tmp_path / "ia_cache"))
    monkeypatch.setattr(ia, "_SEM_PARAM", set())
    ia.salvar_config({"ativo": True, "chave": "sk-ant-teste"})
    pedidos = []
    resposta = {"resumo": "Canal de mistérios com tutoriais irônicos.", "faz_bem": ["a"], "pode_melhorar": ["b"],
                "titulos": {"formulas": [], "funcionam": [], "nao_funcionam": []},
                "thumbs": {"estilo": "s", "funcionam": [], "nao_funcionam": [], "receita": "r"},
                "tipos_de_video": [], "ganchos_e_roteiro": [], "melhores": [{"id": "pop00000001", "por_que": "x"}], "piores": [],
                "sugestoes": [{"titulo": "A Stasi tinha um manual", "tipo": "tutorial", "por_que": "p", "gancho": "g", "thumb": "t"}]}

    def _t(payload, chave, timeout):
        pedidos.append(payload)
        return 200, {"content": [{"type": "text", "text": json.dumps(resposta)}], "stop_reason": "end_turn",
                     "usage": {"input_tokens": 5000, "output_tokens": 800}}
    monkeypatch.setattr(ia, "_transporte", _t)
    monkeypatch.setattr(ia, "imagem_bloco", lambda fonte, largura=320, timeout=12.0: {
        "type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}})
    return pedidos


def test_ia_recebe_numeros_miniaturas_e_transcricoes(tmp_path, ia_on):
    a = ac.nova(str(tmp_path), "@canal", n=5)
    ac.executar(str(tmp_path), a["id"], coletor=_coletor_fake, detalhes=lambda v: {}, transcritor=_transcritor_fake)
    r = ac.analisar_com_ia(ac.carregar(str(tmp_path), a["id"]))
    assert r and r["sugestoes"][0]["titulo"] == "A Stasi tinha um manual"
    conteudo = ia_on[0]["messages"][0]["content"]
    imgs = [b for b in conteudo if b["type"] == "image"]
    textos = "\n".join(b["text"] for b in conteudo if b["type"] == "text")
    assert len(imgs) == 9 and "[pop00000001]" in textos and "Gancho: Tu sabia" in textos
    assert ia_on[0]["output_config"]["format"]["type"] == "json_schema"


def test_ia_desligada_nao_chama(tmp_path, monkeypatch):
    import ia_servico as ia
    monkeypatch.setattr(ia, "ativo", lambda r: False)
    assert ac.analisar_com_ia({"videos": {}}) is None


# ------------------------------------------------------------------ rotas
@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_rotas_do_analisador(A, monkeypatch):
    import analisador_rotas as ar
    real = ac.executar
    monkeypatch.setattr(ar.ac, "executar", lambda base, aid, depois=None: real(
        base, aid, coletor=_coletor_fake, detalhes=lambda v: {"likes": 1}, transcritor=_transcritor_fake, depois=depois))
    c = A.app.test_client()
    assert "Analisador de canal" in c.get("/analisador-canal").get_data(as_text=True)
    r = c.post("/analisador-canal/novo", data={"url": "https://www.youtube.com/@Misterecore", "n": "6", "transcricoes": "on"})
    assert r.status_code == 302
    aid = r.headers["Location"].rstrip("/").split("/")[-1]
    try:
        for _ in range(100):
            e = c.get(f"/analisador-canal/{aid}/estado").get_json()
            if e["estado"] == "pronto" and not e["rodando"]:
                break
            time.sleep(0.05)
        assert e["estado"] == "pronto"
        html = c.get(f"/analisador-canal/{aid}").get_data(as_text=True)
        assert "Canal Teste" in html and "i.ytimg.com/vi/rec00000000/hqdefault.jpg" in html and "mais populares" in html
        assert "📋 Copiar o prompt" in html
        assert "Canal Teste" in c.get(f"/analisador-canal/{aid}/prompt").get_json()["prompt"]
        # IA desligada nos testes -> 400 com o motivo
        assert c.post(f"/analisador-canal/{aid}/ia").status_code == 400
        # resposta colada
        resp = {"resumo": "Bom canal.", "faz_bem": ["x"], "sugestoes": [{"titulo": "Vídeo novo X", "tipo": "caso", "por_que": "p",
                                                                         "gancho": "Tu sabia…", "thumb": "rosto"}]}
        assert c.post(f"/analisador-canal/{aid}/colar", json={"texto": "nada"}).status_code == 400
        assert c.post(f"/analisador-canal/{aid}/colar", json={"texto": json.dumps(resp)}).get_json()["ok"]
        html = c.get(f"/analisador-canal/{aid}").get_data(as_text=True)
        assert "Vídeo novo X" in html and "Criar projeto com essa ideia" in html
        # sugestão -> 🕵️ Modelo de vídeo
        r = c.post(f"/analisador-canal/{aid}/sugestao/0/projeto", data={"modelo": "rabbit_holes"})
        assert r.status_code == 302 and "/modelos-video/" in r.headers["Location"]
        pid = r.headers["Location"].rstrip("/").split("/")[-1]
        import dossies
        p = dossies.carregar(A.BASE_DIR, pid)
        assert p["tema"] == "Vídeo novo X" and p["config"]["modelo"] == "rabbit_holes" and "Gancho (1ª frase): Tu sabia" in p["roteiro_base"]
        shutil.rmtree(os.path.join(A.BASE_DIR, "dossies", pid), ignore_errors=True)
        assert "Canal Teste" in c.get("/analisador-canal").get_data(as_text=True)
        assert c.post(f"/analisador-canal/{aid}/apagar").status_code == 302
        assert c.get(f"/analisador-canal/{aid}").status_code == 404
    finally:
        ac.apagar(A.BASE_DIR, aid)


def test_link_ruim_volta_com_erro(A):
    r = A.app.test_client().post("/analisador-canal/novo", data={"url": "https://vimeo.com/x"})
    assert r.status_code == 302 and "erro=" in r.headers["Location"]


def test_ids_de_analise_nao_saem_da_pasta(A):
    c = A.app.test_client()
    assert c.get("/analisador-canal/..%2F..%2Fapp").status_code == 404
    assert c.get("/analisador-canal/abc").status_code == 404


# ------------------------------------------------------------------ ⛏ Niche Miner
def test_niche_miner_sobe_como_app_a_parte(A, monkeypatch):
    import analisador_rotas as ar
    chamadas = []

    class _Proc:
        def poll(self):
            return None

    monkeypatch.setattr(ar, "_porta_aberta", lambda porta, host="127.0.0.1": False)
    monkeypatch.setattr(ar, "_NM", {"proc": None, "porta": None, "erro": None, "log": None})
    r = ar.nm_iniciar(popen=lambda cmd, **kw: chamadas.append((cmd, kw)) or _Proc())
    assert r["ok"] and r["porta"] == 8843
    cmd, kw = chamadas[0]
    assert cmd[1:] == ["app.py", "--port", "8843", "--host", "127.0.0.1"] and kw["cwd"].endswith("niche_miner")
    assert ar.nm_iniciar(popen=lambda *a, **k: pytest.fail("subiu duas vezes"))["iniciando"]
    c = A.app.test_client()
    html = c.get("/niche-miner").get_data(as_text=True)
    assert "nmFrame" in html and ":8843/" in html
    assert c.get("/niche-miner/status").get_json()["no_ar"] is False


def test_niche_miner_veio_inteiro():
    for arq in ("app.py", "yt_scraper.py", "canal.py", "templates/index.html", "static/app.js", "README.md"):
        assert os.path.isfile(os.path.join(ac.NICHE_MINER_DIR, arq)), arq


def test_leitor_do_niche_miner_le_os_cards_do_canal():
    """O mesmo leitor de cards do Niche Miner, no HTML real da aba Vídeos (fixture), vira o formato do analisador."""
    pw = pytest.importorskip("playwright.sync_api")
    core = ac.nm_scraper()
    html = open(os.path.join(ac.NICHE_MINER_DIR, "tests", "fixtures", "canal_videos_grid_novo_layout.html"), encoding="utf-8").read()
    try:
        with pw.sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.set_content(html)
            cards = [core._card_video_data(x) for x in pg.query_selector_all(core.CARDS_CANAL_SEL)]
            b.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"sem Chromium: {exc}")
    vs = [ac._video_do_card(c) for c in cards if c]
    assert len(vs) == 10 and vs[0]["id"] == "cbloz65iVVM"
    assert all(v["thumb"].startswith("https://i.ytimg.com/vi/") for v in vs)
    assert all(v["views"] for v in vs) and all(v["duracao_s"] for v in vs)
