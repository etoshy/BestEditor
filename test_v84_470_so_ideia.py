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
