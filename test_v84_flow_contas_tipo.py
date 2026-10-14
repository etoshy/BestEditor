"""v84_105 — 🎬 Flow: sem crédito de VÍDEO não é sem crédito de IMAGEM. A conta fica marcada só pro tipo que acabou
(continua gerando o outro); quando os dois acabam, fica esgotada de vez até liberar."""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
from googleflow import googleflow_client as gf  # noqa: E402


def test_limite_por_tipo(monkeypatch, tmp_path):
    monkeypatch.setattr(gf, "pasta_dados", lambda: tmp_path)
    monkeypatch.setattr(gf, "obter_senha", lambda nome: None)
    gf.adicionar_conta("reserva")
    agora = datetime(2026, 10, 14, 18, 0)
    gf.marcar_esgotada("principal", 24, agora=agora, tipo="animar")  # animar = vídeo
    c = {x["nome"]: x for x in gf.listar_contas(agora)}["principal"]
    assert c["esgotada_video"] and not c["esgotada_imagem"] and not c["esgotada"]
    assert gf.escolher_conta_disponivel(agora, tipo="video") == "reserva"
    assert gf.escolher_conta_disponivel(agora, tipo="imagem") in ("principal", "reserva")
    assert gf.conta_serve("principal", "imagem", agora) and not gf.conta_serve("principal", "video", agora)
    # a imagem também acabou: esgotada de vez
    gf.marcar_esgotada("principal", 24, agora=agora, tipo="imagem")
    c = {x["nome"]: x for x in gf.listar_contas(agora)}["principal"]
    assert c["esgotada"] and c["esgotada_ate"]
    assert gf.escolher_conta_disponivel(agora, tipo="imagem") == "reserva"
    # 24 h depois volta
    depois = agora + timedelta(hours=25)
    assert gf.conta_serve("principal", "video", depois)
    # todas sem vídeo: erro fala de vídeo
    gf.marcar_esgotada("reserva", 24, agora=agora, tipo="video")
    try:
        gf.escolher_conta_disponivel(agora, tipo="video")
        assert False
    except gf.GoogleFlowSemContas as exc:
        assert "de vídeo" in str(exc)
    # liberar limpa tudo
    gf.liberar_conta("principal")
    assert gf.conta_serve("principal", "video", agora) and gf.conta_serve("principal", "imagem", agora)
    # marca sem tipo = a conta toda (como antes)
    gf.marcar_esgotada("reserva", 24, agora=agora)
    assert {x["nome"]: x for x in gf.listar_contas(agora)}["reserva"]["esgotada"]
    assert gf.tipo_do_limite("lote") is None and gf.tipo_do_limite("foto") == "imagem"
