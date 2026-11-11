"""v84_382: histórico do Gerador de voz mostra o projeto de origem com link."""
import app as A


def test_historico_tem_nome_e_link_do_projeto(monkeypatch):
    monkeypatch.setattr(A._hist_voz, "listar", lambda pasta, q="", limite=50, pagina=0: {"total": 2, "itens": [
        {"id": "a1", "texto_inicio": "Imagine", "projeto": "dossie_id:abcdef1234"},
        {"id": "a2", "texto_inicio": "Sem projeto"}]})
    monkeypatch.setattr(A, "_nomes_projetos_voz", lambda: {"dossie_id:abcdef1234": ("🕵️ Kant e o elefante", "/modelos-video/abcdef1234")})
    d = A.app.test_client().get("/gerar-voz/historico").get_json()
    assert d["itens"][0]["projeto_nome"] == "🕵️ Kant e o elefante" and d["itens"][0]["projeto_url"] == "/modelos-video/abcdef1234"
    assert "projeto_nome" not in d["itens"][1]
    assert "Ir para o projeto" in A.app.test_client().get("/gerar-voz").get_data(as_text=True)


def test_nomes_dos_projetos_reais(monkeypatch):
    import dossies
    monkeypatch.setattr(dossies, "listar", lambda base: [{"id": "abcdef1234", "nome": "Platão"}])
    assert A._nomes_projetos_voz()["dossie_id:abcdef1234"] == ("🕵️ Platão", "/modelos-video/abcdef1234")
