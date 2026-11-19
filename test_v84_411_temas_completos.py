"""v84_411 — uma aula vira POUCOS vídeos completos (sem 12 vídeos quase iguais)."""
import temas_bruto as TB


def _modelo(monkeypatch):
    import dossies as ds
    monkeypatch.setitem(ds.MODELOS, "teste_fil", {"nome": "Teste", "formatos": {"ensaio": {"nome": "E", "minutos": 14}}})


def _tema(tid, titulo, pontos, refs=()):
    return {"id": tid, "titulo": titulo, "tema": titulo, "pontos": list(pontos), "referencias": list(refs)}


def test_padrao_e_poucos_completos_e_regra_no_pedido(monkeypatch):
    _modelo(monkeypatch)
    a = {"modelo": "teste_fil", "divisao": "completo"}
    s = TB.system_analise(a, "texto")
    assert "GRANDES eixos" in s and "de 2 a 5" in s and "QUALQUER parte" in s and "SOBREPOSIÇÃO" in s
    assert "de_onde" in s
    assert TB.divisao({}) == "denso"  # v84_431
    assert TB.divisao({"temas": [{"id": "x"}]}) == "maximo"  # análise antiga continua igual
    assert "de 4 a 15" in TB.system_analise({"modelo": "teste_fil", "divisao": "maximo"}, "t")


def test_parecidos_acha_os_temas_que_se_sobrepoem():
    t = [_tema("a", "Como saber quem você quer ser? O exercício do necrológio",
               ["escrever o necrológio em terceira pessoa", "sinceridade consigo mesmo", "vocação"], ["Ortega"]),
         _tema("b", "Quem você quer ser? A vocação entre desejo e realidade",
               ["vocação e circunstância", "necrológio como exercício", "sinceridade"], ["Ortega"]),
         _tema("c", "Por que a história universal não existe", ["historiografia", "Voegelin", "documentos"])]
    p = TB.parecidos(t)
    assert "b" in p.get("a", []) or any("vocação" in x for x in p.get("a", []))
    assert "c" not in p


def test_notas_juntam_o_texto_todo_e_nao_repetem_os_outros(monkeypatch):
    _modelo(monkeypatch)
    a = {"modelo": "teste_fil", "divisao": "completo"}
    assert "começo, meio e fim" in TB.system_notas(a, "x") and "1500" in TB.system_notas(a, "x")
    t = _tema("a", "Vídeo A", ["p"])
    outros = [t, dict(_tema("b", "Vídeo B", ["q"]), marcado=True), _tema("c", "Vídeo C", ["r"])]
    ped = TB.pedido_notas(t, outros)
    assert "Vídeo B" in ped and "Vídeo C" not in ped and "não repita" in ped


def test_analisar_junta_quando_veio_tema_demais(monkeypatch, tmp_path):
    _modelo(monkeypatch)
    import ia_servico as ia
    a = TB.criar(str(tmp_path), "Aula", "teste_fil", ("palavra " * 300).encode(), "aula.txt", "completo")
    assert a["divisao"] == "completo"
    chamadas = []

    def falso(recurso, system, content, **kw):
        chamadas.append(system)
        if len(chamadas) == 1:
            return {"temas": [{"titulo": f"Tema {i}", "tema": "x", "pontos": ["p"], "formato": "ensaio", "minutos": 8,
                               "forca": 5} for i in range(9)]}
        return {"temas": [{"titulo": "Eixo completo", "tema": "tudo", "pontos": ["a", "b"], "formato": "ensaio",
                           "minutos": 22, "forca": 9, "de_onde": "começo + fim"}]}
    monkeypatch.setattr(ia, "motivo_desligado", lambda r: "")
    monkeypatch.setattr(ia, "chamar", falso)
    assert TB.analisar(str(tmp_path), a["id"]) == 1
    assert "JUNTE" in chamadas[1]
    b = TB.carregar(str(tmp_path), a["id"])
    assert b["temas"][0]["de_onde"] == "começo + fim" and b["temas"][0]["minutos"] == 22
    # 🧩 juntar de novo mantém os que já viraram projeto
    TB.mexer(str(tmp_path), a["id"], lambda x: x["temas"].append(dict(x["temas"][0], id="zz", projeto="P1")))
    TB.mexer(str(tmp_path), a["id"], lambda x: x["temas"].append(dict(x["temas"][0], id="yy")))
    TB.juntar_parecidos(str(tmp_path), a["id"])
    assert any(t.get("projeto") == "P1" for t in TB.carregar(str(tmp_path), a["id"])["temas"])
