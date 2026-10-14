"""v84_103 — ⚙️ Configurações → Fontes de vídeo: a ordem arrastada é salva na hora (antes só no botão lá embaixo)."""
import site_config


def test_ordem_salva_na_hora(monkeypatch, tmp_path):
    import app as _app
    monkeypatch.setattr(site_config, "CONFIG_PATH", str(tmp_path / "site_config.json"))
    c = _app.app.test_client()
    ordem = list(reversed(site_config.load_site_config()["provider_priority"]))
    d = c.post("/settings/ordem-fontes", json={"ordem": ordem}).get_json()
    assert d["ok"] and d["ordem"] == ordem and site_config.load_site_config()["provider_priority"] == ordem
    assert c.post("/settings/ordem-fontes", json={"ordem": ["xyz"]}).status_code == 400
    assert "/settings/ordem-fontes" in c.get("/settings").get_data(as_text=True)
