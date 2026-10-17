"""v84_162: 🔷 Gemini com a busca do Google na checagem pela internet (transporte falso — nada vai pra rede)."""
import json
import os

import pytest

import gemini_servico as gm

RESP_OK = {
    "candidates": [{
        "content": {"parts": [{"text": "```json\n{\"correcoes\": [], \"conferidos\": [{\"item\": \"D1\", \"ok\": true}]}\n```"}]},
        "groundingMetadata": {"webSearchQueries": ["hinterkaifeck 1922"],
                              "groundingChunks": [{"web": {"uri": "https://ex.com/a", "title": "ex.com"}},
                                                  {"web": {"uri": "https://ex.com/a", "title": "repetida"}}]},
    }],
    "usageMetadata": {"promptTokenCount": 2000, "candidatesTokenCount": 300, "thoughtsTokenCount": 200},
}


@pytest.fixture(autouse=True)
def limpo(tmp_path, monkeypatch):
    monkeypatch.setattr(gm, "CONFIG_PATH", str(tmp_path / "gemini_config.json"))
    monkeypatch.setattr(gm, "USO_PATH", str(tmp_path / "gemini_uso.json"))
    yield


def test_sem_chave_avisa():
    with pytest.raises(gm.GeminiErro, match="chave"):
        gm.checar("oi")


def test_chave_invalida_recusada():
    with pytest.raises(gm.GeminiErro):
        gm.salvar_config({"chave": "curta"})


@pytest.mark.parametrize("colado,esperado", [
    ("AIzaSyD-abc_123456789012345678901234", "AIzaSyD-abc_123456789012345678901234"),
    ("  AQ.Ab8RN6Jx-Q_abc.def/123456789\n", "AQ.Ab8RN6Jx-Q_abc.def/123456789"),
    ('GEMINI_API_KEY="AIzaSyXXXXXXXXXXXXXXXXXXXXXXXX"', "AIzaSyXXXXXXXXXXXXXXXXXXXXXXXX"),
])
def test_formatos_de_chave_aceitos(colado, esperado):
    assert gm.salvar_config({"chave": colado})["chave"] == esperado


def test_checar_com_busca_e_custo():
    gm.salvar_config({"chave": "AIzaSyTESTE_1234567890abcdef", "modelo": "gemini-2.5-flash"})
    pedidos = []

    def transporte(url, corpo, chave, timeout):
        pedidos.append((url, corpo))
        return 200, RESP_OK
    r = gm.checar("confira", rotulo="Checagem: x", transporte=transporte)
    assert "gemini-2.5-flash:generateContent" in pedidos[0][0]
    assert pedidos[0][1]["tools"] == [{"google_search": {}}]
    assert r["fontes"] == [{"titulo": "ex.com", "url": "https://ex.com/a"}] and r["buscas"] == ["hinterkaifeck 1922"]
    assert r["usd"] == pytest.approx((2000 * 0.30 + 500 * 2.50) / 1e6)
    s = gm.resumo()
    assert s["chamadas"] == 1 and s["buscas_usadas"] == 1 and s["buscas_gratis"] == 1500


def test_sem_acesso_ao_25_cai_no_reserva():
    gm.salvar_config({"chave": "AIzaSyTESTE_1234567890abcdef", "modelo": "gemini-2.5-flash"})
    urls = []

    def transporte(url, corpo, chave, timeout):
        urls.append(url)
        if "2.5" in url:
            return 404, {"error": {"message": "models/gemini-2.5-flash is not found for API version v1beta"}}
        return 200, RESP_OK
    r = gm.checar("confira", transporte=transporte)
    assert r["modelo"] == gm.RESERVA and gm.config()["sem_acesso"] == ["gemini-2.5-flash"]
    urls.clear()
    gm.checar("de novo", transporte=transporte)
    assert len(urls) == 1 and gm.RESERVA in urls[0]  # lembra: não tenta o 2.5 de novo


def test_rota_checagem_gemini(monkeypatch):
    import app as a
    import dossies as ds
    import tarefas_bg
    gm.salvar_config({"chave": "AIzaSyTESTE_1234567890abcdef"})
    monkeypatch.setattr(gm, "_transporte", lambda url, corpo, chave, timeout: (200, RESP_OK))
    p = ds.criar(a.BASE_DIR, "Hinterkaifeck")
    pars = ["Am 31. März 1922 wurden sechs Menschen auf dem Hof Hinterkaifeck ermordet."] + [f"Absatz {i}: Die Ermittler prüften Spuren {i}." for i in range(10)]
    p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": "\n\n".join(pars), "titulos": ["x"]}), p)
    ds.salvar(a.BASE_DIR, p)
    try:
        c = a.app.test_client()
        d = c.post(f"/checagem/dossie/{p['id']}/web/gemini", json={"pagina": f"/modelos-video/{p['id']}"}).get_json()
        assert d.get("tarefa"), d
        t = tarefas_bg.esperar(d["tarefa"], 20)
        assert t["status"] == "pronto", t
        assert '"conferidos"' in t["resultado"]["texto"] and t["resultado"]["fontes"]
        assert c.get("/ia/saldo").get_json()["gemini"]["chamadas"] == 1
    finally:
        import shutil
        shutil.rmtree(os.path.join(a.BASE_DIR, "dossies", p["id"]), ignore_errors=True)
