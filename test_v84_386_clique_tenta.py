"""v84_386: clicar em "Gerar com a IA" tenta de verdade mesmo com o erro de chave guardado."""
import time

import ia_servico as ia


def test_clique_limpa_a_trava_e_tenta(monkeypatch):
    import app as A
    ia.salvar_config({"ativo": True, "chave": "sk-ant-api03-boaaaaaaaaaaaaaaaa"})
    c = ia.config()
    c["sem_credito"] = {"quando": time.time(), "erro": "401: invalid x-api-key", "chave": ia._impressao_chave(ia.chave(c))}
    ia._gravar(ia.CONFIG_PATH, c)
    assert ia.motivo_desligado("roteiros")
    chamou = []
    monkeypatch.setattr(ia, "_transporte", lambda p, k, t: chamou.append(k) or (200, {"content": [{"type": "text", "text": "{}"}],
                                                                                      "usage": {}, "stop_reason": "end_turn"}))
    r = A.app.test_client().post("/ia/gerar", json={"prompt": "Gere o JSON."})
    assert r.status_code == 200 and r.get_json()["ok"] and chamou
    assert ia.motivo_desligado("roteiros") is None
    ia.salvar_config({"ativo": False, "chave": ""})
