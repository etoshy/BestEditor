import dossies as ds


def test_modelo_psicologia(tmp_path):
    m = ds.MODELOS["raciocinio_maldito"]
    assert ds.canal_do_modelo("raciocinio_maldito") == "Raciocínio Maldito" and ds.escopo_enxuto(m)
    p = ds.criar(str(tmp_path), "Por que a gente se sabota", "raciocinio_maldito")
    assert p["config"]["modelo"] == "raciocinio_maldito" and p["config"]["formato"] == "ensaio"
    ds.adicionar_midia(p, tipo="texto", origem="pc", conteudo="Aula: autossabotagem, medo do sucesso, procrastinação." * 20)
    pr = ds.prompt_roteiro(p)
    assert "Raciocínio Maldito" in pr and "diagnóstico" in pr and "não cite o professor" in pr


def test_texto_bruto_aceita_o_modelo():
    import temas_bruto
    assert "raciocinio_maldito" in ds.MODELOS
    assert hasattr(temas_bruto, "DIVISOES")


def test_exemplos_do_zero(tmp_path):
    m = ds.MODELOS["raciocinio_maldito"]
    assert m["exemplos_proprios"] and "EXEMPLOS DO ZERO" in m["regras"][0]
    r = ds.regra_fala(m)
    assert "EXEMPLOS NOVOS" in r and "EXEMPLO COM NOME FICA COM NOME" not in r
    assert ds.regra_fala(ds.MODELOS["true_crime"]) == ds.REGRA_FALA  # os outros canais não mudam
    p = ds.criar(str(tmp_path), "Autossabotagem", "raciocinio_maldito")
    ds.adicionar_midia(p, tipo="texto", origem="pc", conteudo="Aula sobre autossabotagem com o exemplo do João no vestibular. " * 20)
    pr = ds.prompt_roteiro(p)
    assert "EXEMPLOS DO ZERO" in pr and "EXEMPLOS NOVOS" in pr and "EXEMPLO COM NOME FICA COM NOME" not in pr
    ctx = ds._contexto_partes(p)
    assert any("EXEMPLOS NOVOS" in str(x) for x in ctx.get("regras") or [])
