"""v84_305: Pixabay numa só abertura do navegador, prints pra thumb, Source na descrição e títulos com direção."""
import json
import os
import subprocess

import curtos as CT
import curtos_comentario as CC
import curtos_link as CL


def test_linha_fonte():
    assert CL.linha_fonte("https://www.instagram.com/reel/abc/", {"autor_handle": "mourastockdogs"}) == "Source (Instagram): @mourastockdogs"
    assert CL.linha_fonte("https://www.tiktok.com/@fulano/video/1", {}) == "Source (TikTok): @fulano"
    assert CL.criador("https://youtube.com/watch?v=x", {"autor": "Canal Legal"}) == "Canal Legal"
    d = CL.com_fonte("Look at this dog!", "https://www.instagram.com/reel/abc/", {"autor_handle": "dogs"})
    assert d.endswith("\n\nSource (Instagram): @dogs")
    assert CL.com_fonte(d, "https://www.instagram.com/reel/abc/", {"autor_handle": "dogs"}) == d  # não repete
    assert CL._handle({"uploader_id": "12345", "channel": "dogs.br", "uploader": "Dogs BR"}) == "dogs.br"


def test_prints_para_thumb_sem_ia(tmp_path):
    v = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:d=6:r=10", "-pix_fmt", "yuv420p", str(v)], check=True)
    ts = CL.prints_para_thumb(str(v), str(tmp_path / "th"), chamar=False)
    assert len(ts) == 3 and all(os.path.isfile(tmp_path / "th" / t["arquivo"]) for t in ts)
    assert ts == sorted(ts, key=lambda t: t["t"])


def test_prints_com_ia_escolhe_os_numeros(tmp_path):
    v = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:d=6:r=10", "-pix_fmt", "yuv420p", str(v)], check=True)
    pedidos = []

    def ia(rec, sys_, conteudo, **k):
        pedidos.append(conteudo)
        return {"escolhidos": [{"n": 2, "por_que": "ação"}, {"n": 9, "por_que": "rosto"}, {"n": 15, "por_que": "fim"}]}
    ts = CL.prints_para_thumb(str(v), str(tmp_path / "th"), chamar=ia)
    assert [t["por_que"] for t in ts] == ["ação", "rosto", "fim"] and pedidos[0][0]["type"] == "image"


def test_titulos_com_direcao(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    p = CT.criar(base, "", "t", modelo="comentario")
    p["roteiro"] = {"blocos": [{"id": "B1", "fala": "The dog herds the sheep."}], "titulos": [{"en": "Old", "pt": "Velho"}]}
    CT.salvar(base, p)
    vistos = []

    def ia(rec, sys_, txt, **k):
        vistos.append(txt)
        return {"opcoes": [{"en": "Who trained this dog?", "pt": "Quem treinou esse cão?"}]}
    novos = CC.mais_opcoes(base, p["id"], "titulos", ia, direcao="pergunta", comentario="foca no cachorro")
    assert novos and "question" in vistos[0] and "foca no cachorro" in vistos[0]
    assert CT.carregar(base, p["id"])["roteiro"]["titulos"][0]["en"] == "Who trained this dog?"  # o novo vem primeiro


def test_pixabay_varios_termos_numa_abertura(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    monkeypatch.setenv("CURTOS_PIXABAY_DIR", str(tmp_path / "px"))
    import curtos_rotas as CR
    from flask import Flask
    base = str(tmp_path)
    aberturas = []

    def pixabay_falso(args):
        aberturas.append(list(args.termos))
        os.makedirs(args.pasta, exist_ok=True)
        itens = []
        for k, termo in enumerate(args.termos):
            f = os.path.join(args.pasta, f"s{k}.m4a")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=1", f], check=True)
            itens.append({"id": str(200 + k), "busca": termo, "arquivo_cortado": f, "titulo": termo})
        json.dump(itens, open(os.path.join(args.pasta, "catalogo.json"), "w"))
        return 0
    monkeypatch.setattr(CR, "importar_pixabay", lambda b, sid, pasta=None: f"pixabay/{sid}")
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(CT.__file__), "templates"))
    CR.registrar(app, base, rodar_pixabay=pixabay_falso)
    cl = app.test_client()
    cl.post("/curtos/acabamento", json={"sons_pixabay": True})
    p = CT.criar(base, "", "t", modelo="comentario")
    p["roteiro"] = {"blocos": [{"id": "B1", "fala": "a", "cenas": [], "sfx": [{"tipo": "impacto", "busca": "dog bark"},
                                                                         {"tipo": "whoosh", "busca": "sheep bleat"}]}]}
    CT.salvar(base, p)
    assert CR.CB["sons_pixabay"](p["id"], lambda m: None) == 2
    assert aberturas == [["dog bark", "sheep bleat"]]  # 1 navegador pros 2 termos
    html = cl.get("/curtos/link").get_data(as_text=True)
    assert "direcao" not in html or "curiosidade" in html


def test_varios_links_um_por_linha_um_de_cada_vez(tmp_path, monkeypatch):
    """🔗 v84_306: um link por linha (repetidos saem) e duas listas coladas nunca geram 2 vídeos ao mesmo tempo."""
    import threading
    import time
    import curtos_rotas as CR
    from flask import Flask
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    rodando, maximo, feitos = [0], [0], []
    trava = threading.Lock()

    def baixar_falso(b, pid, url, baixar, prog):
        with trava:
            rodando[0] += 1
            maximo[0] = max(maximo[0], rodando[0])
        time.sleep(0.15)
        with trava:
            rodando[0] -= 1
            feitos.append(url)
        raise CT.CurtoErro("parei aqui (teste)")
    monkeypatch.setattr(CC, "clipes", lambda b, p: [])
    monkeypatch.setattr(CC, "baixar_clipe", baixar_falso)
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(CT.__file__), "templates"))
    CR.registrar(app, base)
    cl = app.test_client()
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/1\nhttps://a.com/2\n\nhttps://a.com/1\nlixo\nhttps://a.com/3", "iniciar": True}).get_json()
    assert r["ok"] and len(r["criados"]) == 3
    r2 = cl.post("/curtos/link/novo", json={"link": "https://b.com/9", "iniciar": True}).get_json()
    assert r2["ok"]
    for _ in range(100):
        if len(feitos) == 4:
            break
        time.sleep(0.05)
    assert sorted(feitos) == ["https://a.com/1", "https://a.com/2", "https://a.com/3", "https://b.com/9"]
    assert maximo[0] == 1
    todos = r["criados"] + r2["criados"]
    for _ in range(200):  # espera a fila fechar (não deixa tarefa rodando pro próximo teste)
        if all((CR.TAREFAS.get(p) or {}).get("fim") for p in todos):
            break
        time.sleep(0.02)
