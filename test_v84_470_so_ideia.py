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


def test_v471_lista_historias_e_reescreve(tmp_path, monkeypatch):
    import ia_servico as ia
    hs = [{"resumo": "quem fala parou de fumar correndo", "palavras": ["cigarro", "corrida", "bronquite"]}]
    a = {"modelo": "raciocinio_maldito", "nome": "aula", "historias": hs}
    assert "cigarro" in tb.bloco_historias(a) and "cigarro" in tb.system_notas(a, "x")
    assert "cigarro" in tb.system_lapidar(a, {"titulo": "t"})
    t = {"id": "a1", "titulo": "Como o cigarro foi trocado pela corrida", "tema": "x", "pontos": [], "abertura": ""}
    assert tb.vazamentos(t, hs) == ["cigarro", "corrida"]
    chamadas = []

    def falso(rec, system, conteudo, **kw):
        chamadas.append(conteudo)
        return {"temas": [{"id": "a1", "titulo": "Por que força de vontade não larga vício",
                           "abertura": "Uma mulher tenta parar de checar o celular…", "pontos": ["o sistema de recompensa"]}]}
    monkeypatch.setattr(ia, "chamar", falso)
    out = tb.tirar_historias(a, [t])
    assert out[0]["titulo"].startswith("Por que força") and not tb.vazamentos(out[0], hs)
    assert len(chamadas) == 1
    assert tb.ler_historias({"historias": [{"resumo": "r", "palavras": ["ab", "corrida"]}]}) == [{"resumo": "r", "palavras": ["corrida"]}]


def test_v472_regras_sem_caso_especifico():
    """As regras valem pra qualquer texto: nenhum caso concreto (que a IA copiaria) dentro dos pedidos."""
    a = {"modelo": "raciocinio_maldito", "nome": "aula", "divisao": ""}
    tudo = tb.system_analise(a, "") + tb.system_notas(a, "") + tb.system_lapidar(a, {"titulo": "t"}) + tb.system_sem_historias(a)
    for w in ("cigarro", "fumar", "corrida", "bronquite"):
        assert w not in tudo.lower()


def test_v473_completar_proprios():
    import dossies as ds
    assert any("exemplos NOVOS" in r for r in ds.REGRAS_COMPLETAR_PROPRIOS)
    import inspect, temas_bruto_rotas
    src = inspect.getsource(temas_bruto_rotas)
    assert "_completar_tamanho(aid, tid, pid, t)" in src and "prompt-completar" in src


def test_v474_canal_proibidas_e_marcas(tmp_path, monkeypatch):
    import dossies as ds
    import ultimas_escolhas as ue
    monkeypatch.setattr(ue, "ler", lambda base: {"nome_canal": "CenarioM"})
    p = ds.criar(str(tmp_path), tema="x", modelo="raciocinio_maldito")
    assert p["config"]["nome_canal"] == "Raciocínio Maldito"
    cfg = {"nome_canal": "CenarioM"}
    ds.aplicar_padroes_do_modelo(cfg, "raciocinio_maldito")
    assert cfg["nome_canal"] == "Raciocínio Maldito"
    p["config"]["historias_proibidas"] = [{"resumo": "parou de fumar correndo", "palavras": ["cigarro", "corrida"]}]
    p["roteiro_base"] = "ideia " * 200
    pr = ds.prompt_roteiro(p)
    assert "PROIBIDAS" in pr and "cigarro" in pr and "AS NOTAS NÃO SÃO FALA" in pr and "EXEMPLOS VARIADOS" in pr
    p["resultado"] = {"roteiro": "bla " * 500}
    p["config"]["minutos"] = 20
    c = ds.prompt_completar(p)
    assert "PROIBIDAS" in c and "AS NOTAS NÃO SÃO FALA" in c


def test_v475_projeto_antigo_acha_historias(tmp_path):
    import dossies as ds
    p = ds.criar(str(tmp_path), tema="x", modelo="raciocinio_maldito")
    a = tb.criar(str(tmp_path), "aula", "raciocinio_maldito", ("palavra " * 300).encode(), "a.txt")
    hs = [{"resumo": "parou de fumar correndo", "palavras": ["cigarro"]}]
    tb.mexer(str(tmp_path), a["id"], lambda x: x.update(historias=hs, temas=[{"id": "t1", "titulo": "t", "projeto": p["id"]}]))
    assert tb.historias_do_projeto(str(tmp_path), p["id"]) == hs


def test_v476_um_video_so_e_criterio(tmp_path, monkeypatch):
    import ia_servico as ia
    a = tb.criar(str(tmp_path), "aula", "raciocinio_maldito", ("palavra " * 400).encode(), "a.txt", "um")
    s = tb.system_analise(tb.carregar(str(tmp_path), a["id"]), "x")
    assert "O QUE É UM BOM TEMA" in s and "público é LEIGO" in s
    tres = {"historias": [], "temas": [{"titulo": f"T{k}", "tema": "x", "pontos": [f"p{k}"], "forca": k, "minutos": 10}
                                       for k in (1, 2, 3)]}
    monkeypatch.setattr(ia, "motivo_desligado", lambda r: "")
    monkeypatch.setattr(ia, "chamar", lambda *x, **k: tres)
    assert tb.analisar(str(tmp_path), a["id"]) == 1
    t = tb.carregar(str(tmp_path), a["id"])["temas"][0]
    assert t["titulo"] == "T3" and "T1" in t["pontos"] and "p1" in t["pontos"]
