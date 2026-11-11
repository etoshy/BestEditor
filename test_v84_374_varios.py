"""v84_374: 📂 voz de vários projetos marcados + 🎬 vários vídeos de uma vez no Início."""
import app as A


def test_texto_do_projeto(monkeypatch):
    monkeypatch.setattr(A, "_texto_do_dossie", lambda pid: "Roteiro do dossiê." if pid == "abcdef1234" else "")
    c = A.app.test_client()
    d = c.get("/gerar-voz/texto-projeto?p=dossie:abcdef1234").get_json()
    assert d["texto"] == "Roteiro do dossiê." and d["campo"] == "dossie_id" and d["id"] == "abcdef1234"
    assert c.get("/gerar-voz/texto-projeto?p=dossie:0000000000").status_code == 404
    assert c.get("/gerar-voz/texto-projeto?p=xx:abc").status_code == 400


def test_paginas_tem_os_seletores(monkeypatch):
    monkeypatch.setattr(A, "_projetos_para_voz", lambda: [
        {"param": "dossie", "id": "abcdef1234", "nome": "Sócrates e a morte", "grupo": "🕵️ Modelos de vídeo", "atualizado": 2},
        {"param": "roteiro", "id": "fedcba4321", "nome": "Platão", "grupo": "📜 Roteiro do YouTube", "atualizado": 1}])
    c = A.app.test_client()
    g = c.get("/gerar-voz?varios=1").get_data(as_text=True)
    assert 'id="variosProj"' in g and 'value="dossie:abcdef1234"' in g and "Sócrates e a morte" in g
    i = c.get("/").get_data(as_text=True)
    assert 'id="nvVozes"' in i and 'multiple id="audioNovo"' in i and "const NOMES = {};" in i
