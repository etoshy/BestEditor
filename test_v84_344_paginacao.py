"""v84_344: a lista do Link paginada (10 por página), filtrada por canal/situação, com as contagens de tudo; o cache que só
relê o projeto que mudou; e o 🧹 limpar todos do filtro."""
import curtos as CT
import curtos_rotas as CR
from test_v84_320_lote_por_etapa import _app


_N = [0]


def _links(base, n, canal=""):
    ids = []
    for k in range(n):
        _N[0] += 1
        p = CT.criar(base, canal, f"🔗 v{k}", modelo="comentario")
        p["link_rapido"] = {"link": f"https://a.com/{canal}{k}", "criado": 1000 + _N[0], "aguardando": k % 3 == 0, "etapa": "" if k % 3 == 0 else "✅ pronto"}
        CT.salvar(base, p)
        ids.append(p["id"])
    return ids


def test_paginas_filtros_contagens_e_limpar(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    base = str(tmp_path)
    ca = cl.post("/curtos/canais/novo", json={"nome": "Canal A"}).get_json()["id"]
    a = _links(base, 23, ca)
    sem = _links(base, 4)
    j = cl.get("/curtos/link/estado").get_json()
    V = j["vista"]
    assert len(j["videos"]) == 10 and V["paginas"] == 3 and V["total"] == 27 and V["total_geral"] == 27
    assert V["canais"] == {ca: 23, "": 4} and len(V["aguardando_links"]) == 8 + 2
    assert j["videos"][0]["id"] == sem[-1]  # o mais novo primeiro
    j = cl.get("/curtos/link/estado?pagina=3&por=10").get_json()
    assert len(j["videos"]) == 7 and j["vista"]["pagina"] == 3
    assert cl.get("/curtos/link/estado?pagina=99").get_json()["vista"]["pagina"] == 3  # passou do fim: a última
    j = cl.get(f"/curtos/link/estado?canal={ca}&por=20").get_json()
    assert len(j["videos"]) == 20 and all(v["canal_id"] == ca for v in j["videos"]) and j["vista"]["total"] == 23
    j = cl.get("/curtos/link/estado?canal=_sem").get_json()
    assert sorted(v["id"] for v in j["videos"]) == sorted(sem)
    j = cl.get("/curtos/link/estado?situacao=aguardando&por=50").get_json()
    assert j["vista"]["total"] == 10 and all(v["aguardando"] for v in j["videos"])
    # os POST também respeitam a página pedida (a lista volta igual ao que está na tela)
    j = cl.post(f"/curtos/link/{a[0]}/editar?canal={ca}&por=5", json={"marca": "postado"}).get_json()
    assert j["ok"] and len(j["videos"]) == 5 and j["vista"]["canal"] == ca
    # 🧹 limpar: só o filtro, e confere a quantidade
    r = cl.post("/curtos/link/limpar", json={"acao": "tirar", "canal": "_sem", "quantos": 3})
    assert r.status_code == 409  # a lista "mudou" (são 4)
    j = cl.post("/curtos/link/limpar", json={"acao": "tirar", "canal": "_sem", "quantos": 4}).get_json()
    assert j["ok"] and j["feitos"] == 4 and j["vista"]["total_geral"] == 23
    assert all(not CT.carregar(base, x).get("link_rapido") for x in a[:0])
    CR.TAREFAS[a[1]] = {"fim": None}  # rodando: fica
    try:
        j = cl.post("/curtos/link/limpar", json={"acao": "tirar", "canal": ca, "quantos": 22}).get_json()
        assert j["ok"] and j["feitos"] == 22 and [v["id"] for v in cl.get("/curtos/link/estado").get_json()["videos"]] == [a[1]]
    finally:
        CR.TAREFAS.pop(a[1], None)
    assert cl.post("/curtos/link/limpar", json={"acao": "x"}).status_code == 400


def test_cache_so_rele_o_que_mudou(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    base = str(tmp_path)
    ids = _links(base, 5)
    cl.get("/curtos/link/estado")
    lidos = []
    orig = CT.carregar
    monkeypatch.setattr(CT, "carregar", lambda b, pid: lidos.append(pid) or orig(b, pid))
    cl.get("/curtos/link/estado")
    assert lidos.count(ids[2]) <= 1  # (só o resumo da página, não a leitura do disco de todos)
    import os
    import time
    with CT._TRAVA:
        p = orig(base, ids[2])
        p["link_rapido"]["marca"] = "planejado"
        time.sleep(0.01)
        CT.salvar(base, p)
    j = cl.get("/curtos/link/estado?situacao=planejado").get_json()
    assert [v["id"] for v in j["videos"]] == [ids[2]]  # a mudança aparece


def test_arroba_do_canal_nao_herda_do_padrao(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    CT.salvar_acabamento(base, {"arroba": "@RadicalWow"})
    food = CT.criar_canal(base, "FoodYum2", "")
    CT.salvar_canal(base, food)
    assert CT.acabamento(base)["arroba"] == "@RadicalWow"
    assert CT.acabamento(base, food["id"])["arroba"] == ""  # sem @ próprio: nada do padrão
    p0 = CT.criar(base, food["id"], "x", modelo="comentario")
    assert CT.marca_do(base, p0)["texto"].lower() == "@foodyum2"  # vale o @ do canal (o nome dele)
    CT.salvar_acabamento(base, {"arroba": "@RadicalWow"}, food["id"])  # o erro antigo (salvou o herdado)
    assert CT.acabamento(base, food["id"])["arroba"] == ""
    assert CT.marca_do(base, CT.criar(base, food["id"], "y", modelo="comentario"))["texto"].lower() == "@foodyum2"
    CT.salvar_acabamento(base, {"arroba": "@food.yum"}, food["id"])  # o seu de verdade vale
    assert CT.acabamento(base, food["id"])["arroba"] == "@food.yum"
    p = CT.criar(base, food["id"], "x", modelo="comentario")
    assert p["config"]["marca"]["texto"] == "@food.yum"


def test_v84_347_arroba_velho_no_projeto_segue_o_canal(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    food = CT.criar_canal(base, "FoodYum2", "")
    CT.salvar_canal(base, food)
    p = CT.criar(base, food["id"], "x", modelo="comentario")
    p["config"]["marca"] = {"ativa": True, "texto": "@RadicalWow", "fonte": "DP Anton"}  # criado antes da correção
    CT.salvar(base, p)
    m = CT.marca_do(base, p)
    assert m["texto"].lower() == "@foodyum2" and m["fonte"] == "DP Anton"  # o resto do estilo do projeto continua
    CT.salvar_acabamento(base, {"arroba": "@FoodYum2"}, food["id"])
    assert CT.marca_do(base, p)["texto"] == "@FoodYum2"
    p["config"]["marca"]["texto_manual"] = True  # mudou o @ deste vídeo de propósito: vale o dele
    assert CT.marca_do(base, p)["texto"] == "@RadicalWow"
    sem = CT.criar(base, "", "y", modelo="comentario")
    sem["config"]["marca"] = {"ativa": True, "texto": "@meu"}
    assert CT.marca_do(base, sem)["texto"] == "@meu"  # sem canal: o do projeto
