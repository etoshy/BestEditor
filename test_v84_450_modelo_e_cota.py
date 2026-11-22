import io
import json
import time

import cota_claude
import ia_servico as ia
import thumbs_flow as tf


def test_ideias_marcam_o_modelo(monkeypatch):
    monkeypatch.setattr(ia, "motivo_desligado", lambda r=None, c=None: None)

    def chamar(rec, system, conteudo, **kw):
        ia._marcar_modelo("Claude Code · Opus (assinatura)")
        return {"thumbnails": [{"ideia": f"cena {k}", "texto": f"P{k}", "prompt": "s", "modo": "albert"} for k in range(3)]}
    monkeypatch.setattr(ia, "chamar", chamar)
    out = tf.pedir_ideias("T", "roteiro", [], 0, "pt", albert=3)
    assert {t["modelo_ia"] for t in out} == {"Claude Code · Opus (assinatura)"}
    j = tf.para_json({"itens": [dict(out[0], n=1)]}, "/x")
    assert j["itens"][0]["modelo_ia"].startswith("Claude Code")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_cota(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert not cota_claude.ler(forcar=True)["ok"]
    (tmp_path / ".credentials.json").write_text(json.dumps(
        {"claudeAiOauth": {"accessToken": "tok", "expiresAt": (time.time() + 3600) * 1000, "subscriptionType": "max"}}))
    vistos = {}

    def abrir(req, timeout=15):
        vistos["auth"] = req.get_header("Authorization")
        return _Resp(json.dumps({"five_hour": {"utilization": 30, "resets_at": "2030-01-01T00:00:00Z"},
                                 "seven_day": {"utilization": 55.5, "resets_at": None},
                                 "seven_day_opus": {"utilization": 80}}).encode())
    d = cota_claude.ler(forcar=True, _abrir=abrir)
    assert d["ok"] and vistos["auth"] == "Bearer tok"
    assert [(j["chave"], j["livre"]) for j in d["janelas"]] == [("five_hour", 70.0), ("seven_day", 44.5), ("seven_day_opus", 20.0)]
    assert d["plano"] == "max"
