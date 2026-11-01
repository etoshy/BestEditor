"""v84_309: 🎨 modo arte no Link → vídeo pronto (artista pelo @, técnica, reação; títulos sobre a obra)."""
import curtos as CT
import curtos_comentario as CC
import curtos_link as CL


def test_modo_arte_regra_e_marca():
    assert "arte" in CL.MODOS
    r = CL.regra_modo("arte")
    assert "ARTIST" in r and "TECHNIQUE" in r and "REVEAL" in r and "THE SUBJECT" in r
    assert CL.modo_escolhido("[ART] Flowers inside jelly", "auto") == "arte"
    assert CL.modo_escolhido("qualquer", "arte") == "arte"
    assert CL.limpar_marca("[ART] Flowers") == "Flowers"


def test_prompt_traz_o_artista(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    p = CT.criar(base, "", "t", modelo="comentario")
    p["link_rapido"] = {"link": "https://www.instagram.com/reel/abc/"}
    CC.dados(p)["info_link"] = {"autor_handle": "ariel.cy", "titulo": "dry pastel underwater", "comentarios": []}
    CC.dados(p)["modo_link"] = "arte"
    CT.salvar(base, p)
    txt = CC.conteudo_roteiro(base, CT.carregar(base, p["id"]))
    assert "@ariel.cy" in txt and "ART & CREATIONS" in txt
