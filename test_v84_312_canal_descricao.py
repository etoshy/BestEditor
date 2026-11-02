"""v84_312: criar/editar canal com nome + descrição (no acabamento), descrição vai pro roteiro, fila retoma todas."""
import os

import curtos as CT
import curtos_comentario as CC
import curtos_rotas as CR
from flask import Flask


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    monkeypatch.setattr(CR, "CB", dict(CR.CB))
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(CT.__file__), "templates"))
    CR.registrar(app, str(tmp_path))
    return app.test_client()


def test_criar_canal_com_descricao(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    r = cl.post("/curtos/canais/novo", json={"nome": "Arte Fantasia", "descricao": "Artistas que pintam mundos fantásticos"}).get_json()
    assert r["ok"] and r["id"]
    item = [x for x in r["canais"] if x["id"] == r["id"]][0]
    assert item["nome"] == "Arte Fantasia" and item["descricao"].startswith("Artistas")
    assert CT.carregar_canal(base, r["id"])["descricao"].startswith("Artistas")


def test_criar_canal_sem_nome_recusa(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    assert cl.post("/curtos/canais/novo", json={"nome": "  ", "descricao": "x"}).status_code == 400


def test_editar_nome_e_descricao(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    c = CT.criar_canal(base, "Velho", "", "antiga")
    r = cl.post(f"/curtos/canais/{c['id']}/editar", json={"nome": "Novo nome", "descricao": "nova descrição"}).get_json()
    assert r["ok"]
    c2 = CT.carregar_canal(base, c["id"])
    assert c2["nome"] == "Novo nome" and c2["descricao"] == "nova descrição"
    assert cl.post("/curtos/canais/naoexiste/editar", json={"nome": "x"}).status_code == 400


def test_descricao_do_canal_vai_pro_roteiro(tmp_path, monkeypatch):
    base = str(tmp_path)
    c = CT.criar_canal(base, "Canal Arte", "", "Só fala de técnicas de pintura a óleo")
    p = CT.criar(base, c["id"], "t", modelo="comentario")
    texto = CC.conteudo_roteiro(base, p)
    assert "Só fala de técnicas de pintura a óleo" in texto
    q = CT.criar(base, "", "t2", modelo="comentario")
    assert "WHAT THIS CHANNEL IS ABOUT" not in CC.conteudo_roteiro(base, q)


def test_retomar_processa_todos_numa_fila(tmp_path, monkeypatch):
    import time
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    import curtos_comentario as CC2
    chamadas = []

    def falha(*a, **k):
        chamadas.append(a)
        raise CT.CurtoErro("parei (teste)")
    monkeypatch.setattr(CC2, "baixar_clipe", falha)
    ids = []
    for n in range(3):
        p = CT.criar(base, "", f"🔗 {n}", modelo="comentario")
        p["link_rapido"] = {"link": f"https://a.com/{n}", "etapa": "💬 lendo os comentários", "erro": "", "criado": n + 1}
        CT.salvar(base, p)
        ids.append(p["id"])
    r = cl.post("/curtos/link/retomar").get_json()
    assert r["ok"] and r["retomados"] == 3
    for _ in range(200):  # espera a fila terminar (uma thread só)
        time.sleep(0.02)
        lista = cl.get("/curtos/link/estado").get_json()["videos"]
        if not any(v["id"] in ids and v["pendente"] for v in lista) and len(chamadas) >= 3:
            break
    assert len(chamadas) == 3  # cada um tentado uma vez, sem loop
