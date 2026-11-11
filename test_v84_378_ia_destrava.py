"""v84_378: 🔓 um 401/sem crédito não trava a IA do site pra sempre."""
import time

import ia_servico as ia


def _cfg(**sc):
    return {"ativo": True, "chave": "sk-ant-api03-boa", "provedor": "anthropic", "recursos": {"roteiros": True},
            "limite_usd": 0, "sem_credito": sc or None}


def test_bloqueio_vale_pra_mesma_chave_por_pouco_tempo(monkeypatch):
    monkeypatch.setattr(ia, "gasto", lambda: {"usd": 0})
    fp = ia._impressao_chave("sk-ant-api03-boa")
    assert ia.motivo_desligado("roteiros", _cfg(quando=time.time(), erro="401: invalid x-api-key", chave=fp))
    assert ia.motivo_desligado("roteiros", _cfg(quando=time.time() - ia.SEM_CREDITO_EXPIRA_S - 1, erro="401", chave=fp)) is None
    assert ia.motivo_desligado("roteiros", _cfg(quando=time.time(), erro="401", chave=ia._impressao_chave("outra"))) is None
    assert ia.motivo_desligado("roteiros", _cfg(quando=time.time(), erro="401")) is not None  # bloqueio antigo, sem chave gravada
