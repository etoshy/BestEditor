"""v84_385: 401 numa chave → tenta a outra (salva × ANTHROPIC_API_KEY); chave colada com sujeira é limpa."""
import ia_servico as ia


def test_limpar_chave():
    assert ia._limpar_chave(' "sk-ant-api03-ab\u200bc\n def" ') == "sk-ant-api03-abcdef"
    assert ia._limpar_chave("x-api-key: sk-ant-xyz") == "sk-ant-xyz"


def test_401_na_salva_usa_a_do_windows(monkeypatch):
    cfg = {"ativo": True, "chave": "sk-ant-velha-000000000000", "provedor": "claude", "modelo": ia.PROVEDORES["claude"]["modelos"][0]["id"],
           "recursos": {"roteiros": True}, "limite_usd": 0, "sem_credito": None}
    monkeypatch.setattr(ia, "config", lambda: dict(cfg))
    monkeypatch.setattr(ia, "gasto", lambda: {"usd": 0})
    monkeypatch.setattr(ia, "_registrar", lambda *a, **k: None)
    monkeypatch.setattr(ia, "_marcar_sem_credito", lambda e: (_ for _ in ()).throw(AssertionError("não deveria travar")))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-boa-111111111111")
    monkeypatch.setattr(ia, "_CHAVE_BOA", {})
    usadas = []

    def transp(payload, k, timeout):
        usadas.append(k)
        if k.startswith("sk-ant-velha"):
            return 401, {"error": {"message": "invalid x-api-key"}}
        return 200, {"content": [{"type": "text", "text": "ok"}], "usage": {}, "stop_reason": "end_turn"}
    monkeypatch.setattr(ia, "_transporte", transp)
    assert ia.chamar("roteiros", "s", "oi", cache_local=False) == "ok"
    assert usadas == ["sk-ant-velha-000000000000", "sk-ant-boa-111111111111"]
    usadas.clear()
    assert ia.chamar("roteiros", "s", "oi de novo", cache_local=False) == "ok" and usadas == ["sk-ant-boa-111111111111"]  # lembra


def test_as_duas_recusadas_explica(monkeypatch):
    cfg = {"ativo": True, "chave": "sk-ant-velha-000000000000", "provedor": "claude", "modelo": ia.PROVEDORES["claude"]["modelos"][0]["id"],
           "recursos": {"roteiros": True}, "limite_usd": 0, "sem_credito": None}
    monkeypatch.setattr(ia, "config", lambda: dict(cfg))
    monkeypatch.setattr(ia, "gasto", lambda: {"usd": 0})
    erros = []
    monkeypatch.setattr(ia, "_registrar", lambda r, u, c, j, ok, erro="": erros.append(erro))
    monkeypatch.setattr(ia, "_marcar_sem_credito", lambda e: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-tambem-ruim-2222")
    monkeypatch.setattr(ia, "_CHAVE_BOA", {})
    monkeypatch.setattr(ia, "_transporte", lambda p, k, t: (401, {"error": {"message": "invalid x-api-key"}}))
    assert ia.chamar("roteiros", "s", "oi", cache_local=False) is None
    assert "chave salva em 🤖 IA" in erros[-1] and "ANTHROPIC_API_KEY" in erros[-1] and "platform.claude.com" in erros[-1]
