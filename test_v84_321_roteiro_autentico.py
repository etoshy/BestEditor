"""v84_321: roteiro ✨ autêntico por padrão (fatos + opinião, gancho/final variados); o 📜 clássico só se você escolher."""
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


def test_padrao_e_autentico(tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    p = CT.criar(base, "", "t", modelo="comentario")
    assert CC.estilo_roteiro(p) == "autentico"
    s = CC.sistema(p)
    assert "AUTHENTIC MODE" in s and "NO PLAY-BY-PLAY" in s and "Everyone thought" in s.split("AUTHENTIC MODE")[1]
    c = CC.conteudo_roteiro(base, p)
    g, f = CC.tipos_do_video(p)
    assert "HOOK TYPE" in c and CC.TIPOS_GANCHO[g] in c and CC.TIPOS_FINAL[f] in c


def test_classico_so_quando_escolhido(tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    p = CT.criar(base, "", "t", modelo="comentario")
    p["config"]["estilo_roteiro"] = "classico"
    assert "AUTHENTIC MODE" not in CC.sistema(p) and "HOOK TYPE" not in CC.conteudo_roteiro(base, p)
    e = CT.criar(base, "", "t", modelo="explicativo")
    assert "AUTHENTIC MODE" not in CC.sistema(e)  # o explicativo já é informativo: não muda


def test_tipos_variam_no_lote(tmp_path, monkeypatch):
    ganchos = {CC.tipos_do_video({"id": f"x{k}"})[0] for k in range(30)}
    finais = {CC.tipos_do_video({"id": f"x{k}"})[1] for k in range(30)}
    assert len(ganchos) >= 4 and len(finais) >= 3
    assert CC.tipos_do_video({"id": "abc"}) == CC.tipos_do_video({"id": "abc"})  # fixo pro mesmo vídeo


def test_link_novo_desligado_por_padrao_e_opcao(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    a = cl.post("/curtos/link/novo", json={"link": "https://a.com/1"}).get_json()["criados"][0]
    b = cl.post("/curtos/link/novo", json={"link": "https://a.com/2", "roteiro_classico": True}).get_json()["criados"][0]
    assert CT.carregar(base, a)["config"]["estilo_roteiro"] == "autentico"
    assert CT.carregar(base, b)["config"]["estilo_roteiro"] == "classico"
    assert cl.post(f"/curtos/{a}/config", json={"estilo_roteiro": "classico"}).status_code == 200
    assert CT.carregar(base, a)["config"]["estilo_roteiro"] == "classico"
    cl.post(f"/curtos/{a}/config", json={"estilo_roteiro": "lixo"})
    assert CT.carregar(base, a)["config"]["estilo_roteiro"] == "classico"
    html = cl.get("/curtos/link").get_data(as_text=True)
    assert 'id="roteiro_classico"' in html and 'id="roteiro_classico" checked' not in html


def test_mais_ganchos_pede_tipos_diferentes(tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    p = CT.criar(base, "", "t", modelo="comentario")
    p["roteiro"] = {"blocos": [{"id": "b1", "fala": "Sloths almost never drink water."}], "ganchos": [], "finais": []}
    CT.salvar(base, p)
    pedidos = []

    def chamar(_area, _sys, txt, **k):
        pedidos.append(txt)
        return {"opcoes": [{"en": "x", "pt": "x"}]}
    CC.mais_opcoes(base, p["id"], "ganchos", chamar=chamar)
    assert "DIFFERENT type" in pedidos[0] and "contradicao" in pedidos[0]
