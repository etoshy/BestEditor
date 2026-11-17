"""v84_408e: na aba 🎬 Google Flow (Gerar, Montar cena, Rascunho, Refazer cena) — "Notamos uma atividade incomum" →
a conta descansa e o MESMO pedido vai pra próxima conta (antes só o resto do site trocava)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
import flow_estudio as FE  # noqa: E402
from googleflow import flow_direto as fd  # noqa: E402
from googleflow import googleflow_client as gf  # noqa: E402

MSG = "o Flow não gerou: Notamos uma atividade incomum. As extensões do navegador que modificam a página podem causar problemas."


def _sessao(monkeypatch, contas, proximas):
    s = FE._Sessao()
    s.conta, s.page = contas[0], object()
    abertas = []
    monkeypatch.setattr(s, "_fechar_pagina", lambda: None)
    monkeypatch.setattr(s, "_garantir_navegador", lambda cfg, vis, conta: (abertas.append(conta), setattr(s, "conta", conta)))
    monkeypatch.setattr(s, "_garantir_projeto", lambda *a, **k: None)
    monkeypatch.setattr(gf, "nomes_das_contas", lambda: list(contas))
    fila = list(proximas)

    def escolher(tipo=None):
        if not fila:
            raise gf.GoogleFlowSemContas("nenhuma")
        return fila.pop(0)
    monkeypatch.setattr(gf, "escolher_conta_disponivel", escolher)
    monkeypatch.setattr(gf, "salvar_diagnostico", lambda *a, **k: None)
    puladas = []
    monkeypatch.setattr(gf, "pular_conta", lambda nome, motivo, minutos=None, **k: puladas.append((nome, minutos)))
    return s, abertas, puladas


def test_incomum_troca_de_conta_e_refaz(monkeypatch):
    s, abertas, puladas = _sessao(monkeypatch, ["a", "b"], ["b"])
    chamadas = []

    def gerar_um(page, trab, on, t):
        chamadas.append(s.conta)
        if len(chamadas) == 1:
            raise fd.FlowRecusou("esperar", MSG)
        return [{"tipo": "imagem", "id": "x", "url": "u"}]
    monkeypatch.setattr(fd, "gerar_um", gerar_um)
    passos = []
    trab = {"tipo": "imagem", "prompt": "p", "referencias": [{"arquivo": "/x/a.png", "_media_id": "m1"}]}
    r = s._gerar(trab, {}, {"trocar_conta": True}, lambda n, e, d: passos.append((n, e, d)), {}, 30)
    assert r and chamadas == ["a", "b"] and abertas == ["b"]
    assert puladas == [("a", gf.MINUTOS_INCOMUM)]
    assert any("atividade incomum" in d for n, e, d in passos if n == "conta")
    assert trab["referencias"] == [{"arquivo": "/x/a.png"}]


def test_incomum_sem_outra_conta_diz_espere(monkeypatch):
    s, _a, _p = _sessao(monkeypatch, ["a", "b"], [])
    monkeypatch.setattr(fd, "gerar_um", lambda *a, **k: (_ for _ in ()).throw(fd.FlowRecusou("esperar", MSG)))
    with pytest.raises(fd.FlowPassoErro) as e:
        s._gerar({"tipo": "imagem", "prompt": "p"}, {}, {"trocar_conta": True}, lambda *a: None, {}, 30)
    assert "todas as contas deram" in str(e.value)


def test_outros_erros_e_uma_conta_so_nao_trocam(monkeypatch):
    s, abertas, puladas = _sessao(monkeypatch, ["a"], ["b"])
    monkeypatch.setattr(fd, "gerar_um", lambda *a, **k: (_ for _ in ()).throw(fd.FlowRecusou("esperar", MSG)))
    with pytest.raises(fd.FlowRecusou):  # só uma conta: o erro sobe como antes
        s._gerar({"tipo": "imagem", "prompt": "p"}, {}, {"trocar_conta": True}, lambda *a: None, {}, 30)
    s, abertas, puladas = _sessao(monkeypatch, ["a", "b"], ["b"])
    monkeypatch.setattr(fd, "gerar_um", lambda *a, **k: (_ for _ in ()).throw(fd.FlowRecusou("esperar", "falhou: política")))
    with pytest.raises(fd.FlowRecusou):
        s._gerar({"tipo": "imagem", "prompt": "p"}, {}, {"trocar_conta": True}, lambda *a: None, {}, 30)
    assert not abertas and not puladas
