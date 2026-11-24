"""v84_470 — Raciocínio Maldito: do texto bruto sai só a IDEIA, nunca a história/o exemplo de quem fala."""
import temas_bruto as tb


def _a(modelo):
    return {"modelo": modelo, "divisao": "", "id": "x"}


def test_raciocinio_maldito_so_ideia():
    a = _a("raciocinio_maldito")
    assert tb._so_ideias(a)
    s = tb.system_analise(a, "texto")
    assert "SÓ A IDEIA, NUNCA A HISTÓRIA" in s and "PROIBIDO reaproveitar" in s
    assert "NUNCA A HISTÓRIA" in tb.system_notas(a, "texto")
    l = tb.system_lapidar(a, {"titulo": "t", "tema": "x"})
    assert "NUNCA A HISTÓRIA" in l and "EXEMPLOS CONCRETOS FICAM CONCRETOS" not in l


def test_outros_modelos_iguais():
    import dossies as ds
    outro = next(k for k, v in ds.MODELOS.items() if not v.get("exemplos_proprios"))
    a = _a(outro)
    assert not tb._so_ideias(a)
    assert "NUNCA A HISTÓRIA" not in tb.system_analise(a, "texto")
    assert "NUNCA A HISTÓRIA" not in tb.system_notas(a, "texto")
    assert "EXEMPLOS CONCRETOS FICAM CONCRETOS" in tb.system_lapidar(a, {"titulo": "t"})
