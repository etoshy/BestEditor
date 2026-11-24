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
