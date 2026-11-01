"""v84_308: fonte e cores da legenda no acabamento (padrão = o de hoje) e círculo/seta só quando precisa."""
import curtos as CT
import curtos_comentario as CC


def test_acabamento_fonte_e_cores(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    a = CT.acabamento(base)
    assert a["legenda_fonte"] == "" and a["legenda_cor"] == "" and a["destaques"] == "precisa"
    p = CT.criar(base, "", "t", modelo="comentario")
    assert not {"fonte", "cor_texto", "cor_ativa"} & set(p["config"]["legenda"])  # padrão: nada muda
    a = CT.salvar_acabamento(base, {"legenda_fonte": "DP Anton", "legenda_cor": "#ffd60a", "legenda_cor_ativa": "#FF2D55",
                                    "destaques": "nunca"})
    assert a["legenda_cor"] == "#FFD60A"
    assert CT.salvar_acabamento(base, {"legenda_fonte": "Comic Sans", "legenda_cor": "amarelo"})["legenda_fonte"] == ""
    CT.salvar_acabamento(base, {"legenda_fonte": "DP Anton", "legenda_cor": "#FFD60A"})
    p = CT.criar(base, "", "t2", modelo="comentario")
    leg = p["config"]["legenda"]
    assert leg["fonte"] == "DP Anton" and leg["cor_texto"] == "#FFD60A" and leg["cor_ativa"] == "#FF2D55"
    assert p["config"]["destaques"] == "nunca"
    import dp_legendas
    n = dp_legendas.normalizar(dict(dp_legendas.padrao() if hasattr(dp_legendas, "padrao") else {}, **leg))
    assert n["fonte"] == "DP Anton" and n["cor_texto"] == "#FFD60A"


def test_regra_dos_destaques():
    p = {"config": {"destaques": "precisa"}, "modelo": "comentario", "comentario": {}}
    assert "ONLY WHEN NEEDED" in CC.regra_destaques(p)
    assert "do NOT use" in CC.regra_destaques({"config": {"destaques": "nunca"}})
    assert CC.regra_destaques({"config": {}}) == ""  # projeto antigo: como era
