"""v84_421 — Formatos de vídeo: a fórmula do canal aprendida dos roteiros + vídeo só com o tema."""
import json
import time

import pytest

import formatos_video as FV

ROT = ("Imagine uma pessoa sentada numa mesa. " * 60).strip()


def _ia_falsa(monkeypatch, pedidos):
    import ia_servico as ia
    monkeypatch.setattr(ia, "motivo_desligado", lambda r, c=None: None)

    def chamar(rec, system, conteudo, **k):
        pedidos.append((system[:60], k.get("web")))
        if "FICHA DO FORMATO" in system:
            return {"resumo": "gancho concreto → pergunta → base → exemplo → passos → pergunta final", "palavras": 1400,
                    "estrutura": [{"bloco": "Gancho", "funcao": "prende", "pct": 10, "como": "cena em 2ª pessoa"},
                                  {"bloco": "Fechamento", "funcao": "fecha", "pct": 8, "como": "pergunta ao público"}],
                    "recursos_sempre": ["personagem imaginário"], "evitar": ["segundo as notas"], "pesquisa": "3 pensadores"}
        if "UM roteiro" in system:
            return {"estrutura": [{"bloco": "Gancho", "funcao": "prende", "pct": 10, "como": "cena"}], "nota": 8}
        if "PESQUISADOR" in system:
            return "Notas de pesquisa. " + "Aristóteles diz que a inveja é dor pelo bem alheio. " * 80
        return None
    monkeypatch.setattr(ia, "chamar", chamar)


@pytest.fixture
def projeto(tmp_path):
    import dossies as ds
    import app as A
    modelo = next(k for k, m in ds.MODELOS.items() if m.get("formatos"))
    ps = []
    for i in range(2):
        p = ds.criar(A.BASE_DIR, tema=f"Teste formato {i}", modelo=modelo)
        p["resultado"] = {"roteiro": ROT + f" fim {i}."}
        p["roteiro_base"] = "base do teste"
        ds.salvar(A.BASE_DIR, p)
        ps.append(p["id"])
    yield A, modelo, ps
    for pid in ps:
        ds.excluir(A.BASE_DIR, pid)
    import os
    try:
        os.remove(FV._arq(A.BASE_DIR, modelo))
    except OSError:
        pass




def test_fluxo_completo(monkeypatch, projeto):
    A, modelo, ps = projeto
    import dossies as ds
    pedidos = []
    _ia_falsa(monkeypatch, pedidos)
    orig = FV.roteiros
    monkeypatch.setattr(FV, "roteiros", lambda base, m: [r for r in orig(base, m) if r["pid"] in ps])
    assert len(FV.pendentes(A.BASE_DIR, modelo)) == 2
    d = FV.atualizar(A.BASE_DIR, modelo)
    assert len(d["amostras"]) == 2 and d["ficha"]["n_roteiros"] == 2 and not FV.pendentes(A.BASE_DIR, modelo)
    t = FV.bloco_prompt(A.BASE_DIR, modelo)
    assert "FORMATO DO CANAL" in t and "Gancho" in t and "segundo as notas" in t
    p = ds.carregar(A.BASE_DIR, ps[0])
    assert "FORMATO DO CANAL" in ds.prompt_roteiro(p, base=A.BASE_DIR)
    # editado à mão vale por cima; "usar" desligado tira do pedido
    c = A.app.test_client()
    c.post(f"/formatos/{modelo}/salvar", json={"texto": "MINHA FICHA"})
    assert "MINHA FICHA" in FV.bloco_prompt(A.BASE_DIR, modelo)
    c.post(f"/formatos/{modelo}/salvar", json={"usar": False})
    assert FV.bloco_prompt(A.BASE_DIR, modelo) == ""
    c.post(f"/formatos/{modelo}/salvar", json={"usar": True, "texto": ""})
    h = c.get(f"/formatos?modelo={modelo}").get_data(as_text=True)
    assert "Ficha do formato" in h and "Gancho" in h and "fvAtivo" in h


def test_aprender_sozinho_so_quando_ativo(monkeypatch, projeto):
    A, modelo, ps = projeto
    chamados = []
    monkeypatch.setattr(FV.threading, "Thread", lambda target, **k: type("T", (), {"start": lambda s: chamados.append(1)})())
    import dossies as ds
    p = ds.carregar(A.BASE_DIR, ps[0])
    FV.mexer(A.BASE_DIR, modelo, lambda d: d.update(ativo=False))
    FV.ao_gerar_roteiro(A.BASE_DIR, p)
    assert chamados == []
    FV.mexer(A.BASE_DIR, modelo, lambda d: d.update(ativo=True))
    FV.ao_gerar_roteiro(A.BASE_DIR, p)
    assert chamados == [1]


def test_pesquisa_usa_internet(monkeypatch, projeto):
    A, modelo, _ps = projeto
    pedidos = []
    _ia_falsa(monkeypatch, pedidos)
    notas = FV.pesquisar(A.BASE_DIR, modelo, "Inveja")
    assert "Aristóteles" in notas and any(w for s, w in pedidos if "PESQUISADOR" in s)


def test_rota_criar_poe_na_fila(monkeypatch, projeto):
    A, modelo, _ps = projeto
    import ia_servico as ia
    import formatos_rotas
    monkeypatch.setattr(ia, "motivo_desligado", lambda r, c=None: None)
    monkeypatch.setattr(formatos_rotas.threading, "Thread", lambda target, **k: type("T", (), {"start": lambda s: None})())
    r = A.app.test_client().post(f"/formatos/{modelo}/criar", json={"temas": "Inveja\nMedo da morte\n", "minutos": 10})
    assert r.status_code == 200 and r.get_json()["novos"] == 2
    assert [x["tema"] for x in FV.carregar(A.BASE_DIR, modelo)["criados"]][-2:] == ["Inveja", "Medo da morte"]
