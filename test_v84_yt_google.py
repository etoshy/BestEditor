"""v84_88 — 🤖🔎 "Achar com Claude + Google": o Claude busca no YouTube e escolhe os vídeos, o link vai pra IA do Google
(pela API dela) que assiste e acha o momento. Botão alternativo no Roteiro do YouTube, no editor e no Cortar do YouTube."""
import pytest

import notificacoes as nt
import tarefas_bg as tb
import yt_agente
import yt_google

from test_v84_roteiro_yt import _ANALISE


def test_agente_so_google_nao_le_legenda_e_claude_faz_a_primeira_busca():
    legendas, assistidos, buscas = [], [], []
    v = [{"url": f"https://youtu.be/v{i}", "titulo": f"vídeo {i}", "ia_nota": 9 - i} for i in range(3)]

    def assistir(video):
        assistidos.append(video["url"])
        if video["url"].endswith("v1"):
            return {"achou": True, "inicio": 30.0, "fim": 38.0, "frase": "rawr", "confianca": 0.7, "fonte": "google"}
        return None
    r = yt_agente.procurar("o T-Rex ataca no banheiro", "", None, so_google=True,
                           buscar=lambda t: (buscas.append(t), v)[1], ordenar=lambda *a: None,
                           legenda=lambda u: (legendas.append(u), {"linhas": [{"t": 0, "texto": "x"}]})[1],
                           achar=lambda l, vv: {"achou": True, "inicio": 1, "fim": 2, "confianca": 1},
                           nova_busca=lambda feitas, motivos: "Jurassic Park T-Rex bathroom" if not feitas else "",
                           assistir=assistir)
    assert r["achou"] and r["fonte"] == "google" and r["video"]["url"].endswith("v1") and r["inicio"] == 30.0
    assert legendas == [] and assistidos == ["https://youtu.be/v0", "https://youtu.be/v1"]
    assert buscas == ["Jurassic Park T-Rex bathroom"]
    r = yt_agente.procurar("x", "termo", None, so_google=True, buscar=lambda t: v, ordenar=lambda *a: None,
                           legenda=lambda u: {}, achar=lambda *a: None, nova_busca=lambda *a: "", assistir=None)
    assert not r["achou"] and "Google" in r["motivo"]


def test_achar_completa_a_duracao(monkeypatch):
    monkeypatch.setattr(yt_google, "disponivel", lambda: None)
    import ia_google_rotas as igr
    import youtube_clipper
    monkeypatch.setattr(youtube_clipper, "buscar_videos_youtube", lambda t, quantidade=20: [
        {"url": "https://youtu.be/a", "titulo": "Cena", "duracao_segundos": 100, "miniatura_url": "https://i/x.jpg"}])
    monkeypatch.setattr(igr, "momento", lambda url, fala, dur=None: {"achou": True, "inicio": 10.0, "fim": 12.0, "frase": "f",
                                                                     "confianca": 0.7, "fonte": "google"})
    r = yt_google.achar("a cena", "termo", 8)
    assert r["achou"] and r["url"] == "https://youtu.be/a" and (r["inicio"], r["fim"]) == (10.0, 18.0)
    assert yt_google.mmss(65) == "1:05" and yt_google.mmss(3725) == "1:02:05"


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    import app as A
    monkeypatch.setattr(nt, "ARQUIVO", str(tmp_path / "n.json"))
    monkeypatch.setattr(tb, "PASTA", str(tmp_path / "t"))
    monkeypatch.setattr(yt_google, "disponivel", lambda: None)
    return A, A.app.test_client()


def test_roteiro_acha_as_cenas_sem_link_e_preenche(cliente, monkeypatch):
    A, c = cliente
    pedidos = []

    def achar(descr, termo="", dur=None, **k):
        pedidos.append((descr, termo))
        if "Reservoir" in descr:
            return {"achou": True, "url": "https://youtu.be/rd", "titulo": "Stuck in the middle", "inicio": 65.0, "fim": 80.0}
        return {"achou": False, "motivo": "não achei"}
    monkeypatch.setattr(yt_google, "achar", achar)
    r = c.post("/roteiros-yt/novo", data={"texto": "0:00 Oi\n0:12 Em Cães de Aluguel o Mr. Blonde dança", "titulo": "T"})
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    try:
        c.post(f"/roteiros-yt/{pid}/analise", json={"texto": _ANALISE})
        d = c.post(f"/roteiros-yt/{pid}/achar-google", json={}).get_json()
        t = tb.esperar(d["tarefa"], 10)
        assert t["status"] == "pronto" and t["resultado"]["achadas"] == 1 and d["total"] == 2
        cenas = c.get(f"/roteiros-yt/{pid}/baixar/json").get_json()["analise"]["cenas"]
        rd = next(x for x in cenas if "Reservoir" in x["obra"])
        assert (rd["link"], rd["link_inicio"], rd["link_fim"]) == ("https://youtu.be/rd", "1:05", "1:20")
        assert len(pedidos) == 2 and nt.listar()[0]["link"] == f"/roteiros-yt/{pid}"
        # tudo com link agora só se pedir a cena
        assert c.post(f"/roteiros-yt/{pid}/achar-google", json={"cenas": [rd["id"]]}).get_json()["ok"]
        h = c.get(f"/roteiros-yt/{pid}").get_data(as_text=True)
        assert "Achar com Claude + Google" in h and "acharComGoogle" in h
    finally:
        tb.esperar(tb.listar(1)[0]["id"], 10)
        c.post(f"/roteiros-yt/{pid}/excluir")


def test_cortar_com_link_e_sem_link(cliente, monkeypatch):
    A, c = cliente
    monkeypatch.setattr(yt_google, "momento_no_link", lambda url, d, dur=None: {"achou": True, "inicio": 5.0, "fim": 9.0, "frase": "oi"})
    monkeypatch.setattr(yt_google, "achar", lambda d, t="", dur=None, **k: {"achou": True, "url": "https://youtu.be/z", "titulo": "Z",
                                                                             "inicio": 61.0, "fim": 70.0, "video": {}, "resultados": []})
    assert c.post("/cortar-youtube/achar-google", json={"url": "https://mal.com/x", "descricao": "a cena"}).status_code == 400
    assert c.post("/cortar-youtube/achar-google", json={"descricao": "x"}).status_code == 400
    t = tb.esperar(c.post("/cortar-youtube/achar-google", json={"url": "https://youtu.be/abc", "descricao": "a cena"}).get_json()["tarefa"], 5)
    assert t["resultado"]["inicio_txt"] == "0:05" and t["resultado"]["url"] == "https://youtu.be/abc"
    t = tb.esperar(c.post("/cortar-youtube/achar-google", json={"descricao": "o T-Rex no banheiro"}).get_json()["tarefa"], 5)
    assert t["resultado"]["url"] == "https://youtu.be/z" and t["resultado"]["fim_txt"] == "1:10" and "video" not in t["resultado"]
    assert "btn-google-trecho" in c.get("/cortar-youtube").get_data(as_text=True)


def test_editor_modo_google(cliente, monkeypatch):
    A, c = cliente
    import uuid
    jid = "tst" + uuid.uuid4().hex[:8]
    A._JOBS[jid] = {"job_id": jid, "youtube_itens": [], "pending_segments": []}
    itens = [{"id": "seg-0", "termo": "t-rex", "descricao": "x"}]
    chamados = []
    monkeypatch.setattr(A, "_youtube_itens_sincronizar", lambda job: itens)
    monkeypatch.setattr(A, "_youtube_ia_rodar", lambda job_id, ids, modo="": chamados.append((ids, modo)))
    monkeypatch.setattr(A, "_save_state", lambda j: None)
    try:
        d = c.post(f"/job/{jid}/youtube/ia", json={"modo": "google", "itens": ["seg-0"]}).get_json()
        assert d["ok"]
        import time
        fim = time.time() + 3
        while not chamados and time.time() < fim:
            time.sleep(0.01)
        assert chamados == [(["seg-0"], "google")]
        monkeypatch.setattr(yt_google, "disponivel", lambda: "a pasta ia_google/ não está no site")
        A._JOBS[jid]["youtube_ia"] = {}
        assert c.post(f"/job/{jid}/youtube/ia", json={"modo": "google"}).status_code == 400
    finally:
        A._JOBS.pop(jid, None)


# ------------------------------------------------------------------ 🔁 olhar de novo (v84_89)
def _yt_mod(monkeypatch):
    pytest.importorskip("playwright")
    import importlib
    import os
    monkeypatch.syspath_prepend(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ia_google"))
    return importlib.import_module("youtube")


def test_app_do_google_olha_de_novo_na_mesma_conversa(monkeypatch):
    yt = _yt_mod(monkeypatch)
    q = yt.consulta_olhar_de_novo("o T-Rex no banheiro", [{"inicio": 65, "fim": 80}, {"inicio": "2:00", "fim": "2:10"}])
    assert "1:05–1:20" in q and "2:00–2:10" in q and "NÃO têm o que estamos procurando" in q and q.count("o T-Rex no banheiro") == 2
    d = {"encontrado": True, "momentos": [{"inicio_seg": 66, "fim_seg": 79}, {"inicio_seg": 300, "fim_seg": 310}]}
    assert [m["inicio_seg"] for m in yt.tirar_errados(d, [{"inicio": 65, "fim": 80}])["momentos"]] == [300]
    assert yt.tirar_errados({"momentos": [{"inicio_seg": 64}]}, [{"inicio": 65, "fim": 80}])["encontrado"] is False

    class IA:
        def __init__(self):
            self.novas, self.prompts = 0, []

        def nova_conversa(self):
            self.novas += 1

        def log(self, *a, **k):
            pass

        def perguntar(self, rotulo, texto_personalizado=None):
            self.prompts.append(texto_personalizado)
            return {"json": {"encontrado": True, "momentos": [{"inicio": "1:06", "fim": "1:15"}, {"inicio": "4:00", "fim": "4:08"}]}}
    ia = IA()
    a = yt.AnalisadorYouTube(ia)
    a.executar("https://youtu.be/abcdefghijk", "momentos", "o T-Rex no banheiro")
    r = a.executar("https://youtu.be/abcdefghijk", "momentos", "o T-Rex no banheiro", errados=[{"inicio": 65, "fim": 80}])
    assert ia.novas == 1  # a 2ª pergunta foi na MESMA conversa
    assert "OLHE DE NOVO" in ia.prompts[-1] and "OLHE DE NOVO" not in ia.prompts[0]
    assert [m["inicio_seg"] for m in r["dados"]["momentos"]] == [240] and r["errados"] == [{"inicio": 65, "fim": 80}]


def test_cliente_manda_os_errados_e_pula_os_repetidos(monkeypatch):
    import ia_google_rotas as igr
    vistos = []

    def video(url, tarefa, consulta, timeout=480, errados=None):
        vistos.append(errados)
        return {"dados": {"momentos": [{"inicio_seg": 66, "fim_seg": 70, "citacao": "a"}, {"inicio_seg": 200, "fim_seg": 210, "citacao": "b"}]}}
    monkeypatch.setattr(igr, "video", video)
    assert igr.momento("https://youtu.be/x", "f")["inicio"] == 66.0
    m = igr.momento("https://youtu.be/x", "f", evitar=[{"inicio": 65, "fim": 80}])
    assert m["inicio"] == 200.0 and vistos[-1] == [{"inicio": 65, "fim": 80}] and vistos[0] is None


def test_roteiro_olhar_de_novo(cliente, monkeypatch):
    A, c = cliente
    pedidos = []

    def momento(url, descr, dur=None, evitar=None):
        pedidos.append((url, evitar))
        return {"achou": True, "inicio": 200.0, "fim": 210.0, "frase": "rawr"} if len(pedidos) == 1 else None
    monkeypatch.setattr(yt_google, "momento_no_link", momento)
    r = c.post("/roteiros-yt/novo", data={"texto": "0:00 Oi\n0:12 Em Cães de Aluguel", "titulo": "T"})
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    try:
        c.post(f"/roteiros-yt/{pid}/analise", json={"texto": _ANALISE})
        assert c.post(f"/roteiros-yt/{pid}/cena/1/olhar-de-novo", json={}).status_code == 400  # sem link
        c.post(f"/roteiros-yt/{pid}/cena/1", json={"link": "https://youtu.be/rd", "link_inicio": "1:05", "link_fim": "1:20"})
        t = tb.esperar(c.post(f"/roteiros-yt/{pid}/cena/1/olhar-de-novo", json={"inicio": "1:05", "fim": "1:20"}).get_json()["tarefa"], 5)
        assert t["resultado"]["achadas"] == 1 and pedidos[0] == ("https://youtu.be/rd", [{"inicio": 65.0, "fim": 80.0}])
        cena = c.get(f"/roteiros-yt/{pid}/baixar/json").get_json()["analise"]["cenas"][0]
        assert (cena["link_inicio"], cena["link_fim"]) == ("3:20", "3:30") and len(cena["google_errados"]) == 1
        t = tb.esperar(c.post(f"/roteiros-yt/{pid}/cena/1/olhar-de-novo", json={"inicio": "3:20", "fim": "3:30"}).get_json()["tarefa"], 5)
        assert t["resultado"]["achadas"] == 0 and len(pedidos[1][1]) == 2  # acumula os recusados
        c.post(f"/roteiros-yt/{pid}/cena/1", json={"link": "https://youtu.be/outro"})
        assert c.get(f"/roteiros-yt/{pid}/baixar/json").get_json()["analise"]["cenas"][0]["google_errados"] == []
        assert "cDeNovo" in c.get(f"/roteiros-yt/{pid}").get_data(as_text=True)
    finally:
        c.post(f"/roteiros-yt/{pid}/excluir")


def test_cortar_olhar_de_novo(cliente, monkeypatch):
    A, c = cliente
    pedidos = []
    monkeypatch.setattr(yt_google, "momento_no_link", lambda url, d, dur=None, evitar=None: (pedidos.append(evitar),
                        {"achou": True, "inicio": 90.0, "fim": 95.0})[1])
    assert c.post("/cortar-youtube/achar-google", json={"descricao": "a cena", "errados": [{"inicio": "1:05"}]}).status_code == 400
    t = tb.esperar(c.post("/cortar-youtube/achar-google", json={"url": "https://youtu.be/abc", "descricao": "a cena",
                                                               "errados": [{"inicio": "0:05", "fim": "0:09"}, {"inicio": "lixo"}]}).get_json()["tarefa"], 5)
    assert pedidos == [[{"inicio": 5.0, "fim": 9.0}]] and t["resultado"]["inicio_txt"] == "1:30" and t["titulo"].startswith("🔁")
    assert "btn-google-denovo" in c.get("/cortar-youtube").get_data(as_text=True)


def test_editor_olhar_de_novo(cliente, monkeypatch):
    A, c = cliente
    import time
    import uuid
    jid = "tst" + uuid.uuid4().hex[:8]
    item = {"id": "seg-0", "tipo": "segmento", "indice": 0, "termo": "t", "duracao_alvo": 6,
            "escolha": {"url": "https://youtu.be/rd", "inicio": 65, "fim": 71, "titulo": "RD"}}
    A._JOBS[jid] = {"job_id": jid, "youtube_itens": [item], "pending_segments": []}
    aplicados, pedidos = [], []
    monkeypatch.setattr(A, "_save_state", lambda j: None)
    monkeypatch.setattr(A, "_youtube_fala_do_item", lambda job, it: "o T-Rex")
    monkeypatch.setattr(A, "_youtube_baixar_e_aplicar", lambda j, i, esc, tag="": (aplicados.append(esc), item.update(escolha=esc))[0])
    monkeypatch.setattr(yt_google, "momento_no_link", lambda url, d, dur=None, evitar=None: (pedidos.append(evitar),
                        {"achou": True, "inicio": 200.0, "fim": 202.0, "frase": "x"})[1])
    try:
        d = c.post(f"/job/{jid}/youtube/item/seg-0/olhar-de-novo").get_json()
        assert d["ok"] and d["errados"] == [{"inicio": 65.0, "fim": 71.0}]
        fim = time.time() + 5
        while A._JOBS[jid]["youtube_ia"].get("rodando") and time.time() < fim:
            time.sleep(0.01)
        assert aplicados and (aplicados[0]["inicio"], aplicados[0]["fim"]) == (200.0, 206.0)  # completa a duração do trecho
        assert item["ia"]["estado"] == "pronto" and pedidos == [[{"inicio": 65.0, "fim": 71.0}]]
        c.post(f"/job/{jid}/youtube/item/seg-0/olhar-de-novo")
        fim = time.time() + 5
        while A._JOBS[jid]["youtube_ia"].get("rodando") and time.time() < fim:
            time.sleep(0.01)
        assert len(pedidos[1]) == 2  # o 1º recusado continua na lista
    finally:
        A._JOBS.pop(jid, None)
