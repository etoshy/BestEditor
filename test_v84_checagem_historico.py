"""v84_99 — 🔎 checagem do roteiro (⏳ cronologia · 📚 alegações históricas · ✂️ repetições), 🤖 revisar + checar +
corrigir automático, 🕘 histórico de versões (tipo git) e 💾 salvar sem "[WinError 5] Acesso negado"."""
import json
import os

import pytest

import arquivo_seguro
import checagem_roteiro as ch
import dossies as ds
import historico_roteiro as hr

ROT = """Im Mai 1924 finden Kinder am Ufer der Leine einen Schädel.

Bemerkenswert ist: Haarmann arbeitete ab 1924 als Informant für die Polizei. Man drückte bei seinen Vergehen ein Auge zu.

Im September 1918 verschwand Friedel Rothe. Seine Freunde sagten, er sei mit Haarmann gesehen worden. Haarmann arbeitete damals als Informant für die Polizei.

[[VENDA]]

Das Gericht verurteilte Grans zunächst wegen Anstiftung zum Mord an Adolf Hannappel zum Tode. Dann tauchte ein Brief auf, in dem Haarmann Grans' Unschuld beteuerte. Grans erhielt schließlich zwölf Jahre Haft.

Der Prozess begann im Dezember 1924. Fast zweihundert Zeugen wurden gehört.

Die Akte umfasste sechzig Bände. Die Presse nutzte jede Einzelheit.

Auch Hans Grans musste sich verantworten. Er wurde zunächst wegen Anstiftung zum Mord an Adolf Hannappel zum Tode verurteilt. Erst ein Brief Haarmanns, in dem dieser Grans' Unschuld beteuerte, führte zu zwölf Jahren Haft.

Haarmann wurde in 24 Fällen verurteilt. Die Polizei konnte ihm 27 Vermisste zuordnen. Er selbst sprach von 50 bis 70 Opfern."""


# ------------------------------------------------------------------ análise local
def test_cronologia_acha_o_conflito_de_data():
    cr = ch.cronologia(ROT, "Fritz Haarmann")
    c = [x for x in cr["conflitos"] if x["linha"] == 3]
    assert c and c[0]["ano"] == 1924 and c[0]["linha_conflito"] == 5 and c[0]["ano_conflito"] == 1918
    assert any(d["ano"] == 1918 and d["linha"] == 5 for d in cr["linha_do_tempo"])


def test_analisar_repeticoes_e_numeros():
    a = ch.analisar(ROT, "Fritz Haarmann")
    assert any({r["a"], r["b"]} == {9, 15} for r in a["repeticoes"])
    assert {n["valor"] for n in a["numeros"]} >= {"24", "27", "50", "70"}
    assert ch.frases("Am 19. Dezember 1924 fiel das Urteil. Gut.") == ["Am 19. Dezember 1924 fiel das Urteil.", "Gut."]


def test_prompt_tres_focos():
    t = ch.prompt(ROT, "alemão", "Fritz Haarmann", "F1 — fonte x")
    for x in ("## 1. ⏳ CRONOLOGIA", "## 2. 📚 CHECAGEM DAS ALEGAÇÕES HISTÓRICAS", "## 3. ✂️ CORTE DE REPETIÇÕES",
              "linha 3 diz", "CONDENADO", "\"verificar\"", "F1 — fonte x", "## ✂️ Repetições que o site achou"):
        assert x in t, x
    assert t.rstrip().endswith("drei" * 0 + "Opfern.")
    with pytest.raises(ValueError):
        ch.prompt("  ")


def test_ler_checagem():
    d = ch.ler(json.dumps({"correcoes": [{"de": "ab 1924", "para": "spätestens ab 1918", "eixo": "Cronologia", "problema": "1918"},
                                         {"de": "x", "para": "", "eixo": "repetição"}, {"de": "", "para": "y"}],
                           "verificar": [{"afirmacao": "Brief", "por_que": "1 Quelle"}], "linha_do_tempo": [{"data": "1918", "evento": "e"}],
                           "inconsistencias": [{"descricao": "d", "linhas": [3, "5"]}], "resumo": "r"}))
    assert [t["eixo"] for t in d["trocas"]] == ["cronologia", "repeticao"] and d["trocas"][1]["para"] == ""
    assert d["verificar"][0]["conferido"] is False and d["inconsistencias"][0]["linhas"] == [3, 5] and d["linha_do_tempo"]


# ------------------------------------------------------------------ 🕘 histórico
def test_historico_versoes_e_diff(tmp_path, monkeypatch):
    pasta = str(tmp_path)
    assert hr.registrar(pasta, "Eins zwei drei.", "🤖 IA")["n"] == 1
    assert hr.registrar(pasta, "Eins zwei drei.  ", "x") is None  # igual: não cria
    v = hr.registrar(pasta, "Eins vier drei.\n\nNeu.", "🪄 revisão", "1 troca")
    assert v["n"] == 2 and v["entraram"] == 2 and v["sairam"] == 1
    assert [x["n"] for x in hr.listar(pasta)] == [2, 1] and hr.texto(pasta, 1) == "Eins zwei drei."
    d = hr.diff("Eins zwei drei.", "Eins vier drei.")
    assert {"op": "-", "t": "zwei"} in d["partes"] and {"op": "+", "t": "vier"} in d["partes"]
    longo = " ".join(f"w{i}" for i in range(300))
    d = hr.diff(longo + "\nalt", longo + "\nneu")
    assert any(x["op"] == "…" for x in d["partes"])
    monkeypatch.setattr(hr, "MAX_VERSOES", 3)
    for i in range(5):
        hr.registrar(pasta, f"Text {i}")
    assert len(hr.listar(pasta)) == 3 and hr.texto(pasta, 1) is None


def test_salvar_do_dossie_grava_versao():
    import app as _app
    base = _app.BASE_DIR
    p = ds.criar(base, "Hist")
    try:
        p["config"]["modo_partes"] = "nao"
        p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": "Erste Fassung des Textes."}), p)
        ds.marcar_mudanca(p, "🤖 resposta da IA")
        ds.salvar(base, p)
        ds.salvar(base, p)  # sem mudança: não cria versão
        assert "_mudanca" not in ds.carregar(base, p["id"])
        vs = hr.listar(ds._pasta(base, p["id"]))
        assert len(vs) == 1 and vs[0]["origem"] == "🤖 resposta da IA"
    finally:
        ds.excluir(base, p["id"])


# ------------------------------------------------------------------ 💾 WinError 5
def test_trocar_tenta_de_novo(tmp_path, monkeypatch):
    destino, tmp = tmp_path / "p.json", tmp_path / "p.json.tmp"
    destino.write_text("velho")
    tmp.write_text("novo")
    real, falhas = os.replace, []

    def replace(a, b):
        if len(falhas) < 3:
            falhas.append(1)
            raise PermissionError(13, "[WinError 5] Acesso negado")
        return real(a, b)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(arquivo_seguro, "ESPERA", 0.001)
    arquivo_seguro.trocar(str(tmp), str(destino))
    assert destino.read_text() == "novo" and len(falhas) == 3
    # sempre negado: grava direto por cima (plano B)
    tmp.write_text("novissimo")
    monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError(13, "negado")))
    monkeypatch.setattr(arquivo_seguro, "TENTATIVAS", 2)
    arquivo_seguro.trocar(str(tmp), str(destino))
    assert destino.read_text() == "novissimo" and not tmp.exists()


# ------------------------------------------------------------------ rotas
@pytest.fixture
def proj():
    import app as _app
    base = _app.BASE_DIR
    p = ds.criar(base, "Fritz Haarmann")
    p["config"].update(modo_partes="nao", minutos=2, idioma="de")
    p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": ROT, "titulos": ["T"]}), p)
    ds.salvar(base, p)
    yield _app, p
    ds.excluir(base, p["id"])


RESP = json.dumps({"correcoes": [
    {"de": "Haarmann arbeitete ab 1924 als Informant", "para": "Haarmann arbeitete spätestens ab 1918 als Informant", "eixo": "cronologia"},
    {"de": "Auch Hans Grans musste sich verantworten.", "para": "", "eixo": "repeticao"}],
    "verificar": [{"afirmacao": "Brief", "por_que": "p", "como": "c"}], "resumo": "r"})


def test_rotas_checagem_e_historico(proj):
    A, p = proj
    c = A.app.test_client()
    pid = p["id"]
    d = c.get(f"/checagem/dossie/{pid}").get_json()
    assert d["ok"] and d["cronologia"]["conflitos"] and d["local"]["repeticoes"] and d["ultima"] is None
    pr = c.post(f"/checagem/dossie/{pid}/prompt", json={"foco": "die Zahlen"}).get_json()
    assert "CRONOLOGIA" in pr["prompt"] and "die Zahlen" in pr["prompt"]
    r = c.post(f"/checagem/dossie/{pid}/ler", json={"texto": RESP}).get_json()
    assert r["ok"] and len(r["aplicadas"]) == 2 and r["por_eixo"] == {"cronologia": 1, "alegacao": 0, "repeticao": 1}
    q = ds.carregar(A.BASE_DIR, pid)
    assert "spätestens ab 1918" in q["resultado"]["roteiro"] and "Auch Hans Grans musste" not in q["resultado"]["roteiro"]
    assert q["checagem"]["verificar"][0]["afirmacao"] == "Brief"
    assert c.post(f"/checagem/dossie/{pid}/verificar/0", json={"conferido": True}).get_json()["ok"]
    assert ds.carregar(A.BASE_DIR, pid)["checagem"]["verificar"][0]["conferido"] is True
    assert c.post(f"/checagem/dossie/{pid}/verificar/9", json={}).status_code == 404
    # 🕘
    vs = c.get(f"/historico/dossie/{pid}").get_json()["versoes"]
    assert vs[0]["origem"] == "🔎 checagem" and len(vs) == 2
    v = c.get(f"/historico/dossie/{pid}/{vs[0]['n']}").get_json()
    assert v["contra"] == vs[1]["n"] and v["diff"]["sairam"] >= 6
    assert c.post(f"/historico/dossie/{pid}/{vs[1]['n']}/restaurar").get_json()["ok"]
    q = ds.carregar(A.BASE_DIR, pid)
    assert "ab 1924 als Informant" in q["resultado"]["roteiro"] and q["checagem"]
    assert c.get(f"/historico/dossie/{pid}").get_json()["versoes"][0]["origem"] == "🕘 restaurado"
    assert c.get(f"/historico/dossie/{pid}/999").status_code == 404
    h = c.get(f"/modelos-video/{pid}").get_data(as_text=True)
    assert 'id="chkCard"' in h and 'id="histCard"' in h


def test_roteiro_auto(proj, monkeypatch):
    import ia_servico
    import tarefas_bg
    A, p = proj
    chamadas = []

    def falso(recurso, system, prompt, **k):
        chamadas.append("chk" if "CHECADOR" in prompt else "rev")
        if "CHECADOR" in prompt:
            return RESP
        return json.dumps({"trocas": [{"de": "Die Presse nutzte jede Einzelheit.", "para": "Die Presse druckte jedes Detail."}]})
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: True)
    monkeypatch.setattr(ia_servico, "chamar", falso)
    c = A.app.test_client()
    t = c.post(f"/roteiro-auto/dossie/{p['id']}", json={}).get_json()
    r = tarefas_bg.esperar(t["tarefa"], 30)
    assert r["status"] == "pronto", r
    assert chamadas == ["rev", "chk"] and [x["modo"] for x in r["resultado"]["passos"]] == ["melhorar", "checagem"]
    q = ds.carregar(A.BASE_DIR, p["id"])
    assert "spätestens ab 1918" in q["resultado"]["roteiro"] and "druckte jedes Detail" in q["resultado"]["roteiro"]
    origens = [v["origem"] for v in hr.listar(ds._pasta(A.BASE_DIR, p["id"]))]
    assert "🔎 checagem" in origens and "🪄 revisão" in origens
    # passou do tempo: 1º enxuga e, se ainda ficou longo depois da checagem, enxuga de novo
    q["config"]["minutos"] = 0.5
    ds.salvar(A.BASE_DIR, q)
    chamadas.clear()
    r = tarefas_bg.esperar(c.post(f"/roteiro-auto/dossie/{p['id']}", json={}).get_json()["tarefa"], 30)
    assert chamadas == ["rev", "chk", "rev"] and [x["modo"] for x in r["resultado"]["passos"]] == ["enxugar", "checagem", "enxugar"]


def test_versao_codigo_avisa_servidor_velho(monkeypatch):
    """v84_102: a página sabe se o servidor que está rodando é o código do disco (senão os botões novos dão 404)."""
    import app as _app
    c = _app.app.test_client()
    d = c.get("/versao-codigo").get_json()
    assert d["id"] == _app._CODIGO_ID and d["desatualizado"] is False
    h = c.get("/settings").get_data(as_text=True)
    assert _app._CODIGO_ID in h and "avisoCodigoVelho" in h
    monkeypatch.setitem(_app._CODIGO_NO_INICIO, "app.py", 0.0)
    assert c.get("/versao-codigo").get_json()["arquivos"] == ["app.py"]


# ------------------------------------------------------------------ 🌐 2ª IA com internet (v84_133)
def test_prompt_web_so_trechos():
    ultima = {"verificar": [{"afirmacao": "Ein Brief Haarmanns beteuerte Grans' Unschuld", "por_que": "nur eine Quelle", "conferido": False},
                            {"afirmacao": "já ok", "conferido": True}],
              "inconsistencias": [{"descricao": "1924 × 1918", "linhas": [3, 5]}]}
    t = ch.prompt_web(ROT, "alemão", "Fritz Haarmann", ultima, [{"trecho": "Er selbst sprach von 50 bis 70 Opfern", "tipo": "alegacao", "fonte": "F1"}])
    for x in ("INTERNET", "C1 ⏳ CRONOLOGIA", "I1 🔁", "V1 📚 CONFERIR", "A1 📚 ALEGAÇÃO", "D1 📅 ANO", "N1 🔢", "R1 ✂️",
              "L3: Bemerkenswert", "\"conferidos\"", "\"fonte\": \"https://…\""):
        assert x in t, x
    assert "V2 📚" not in t  # o que já foi conferido não vai
    assert "Die Akte umfasste sechzig Bände" not in t  # parágrafo sem nada suspeito fica de fora


def test_rota_web_aplica_e_marca_conferido(proj):
    A, p = proj
    c = A.app.test_client()
    pid = p["id"]
    c.post(f"/checagem/dossie/{pid}/ler", json={"texto": json.dumps({"correcoes": [], "verificar": [{"afirmacao": "Brief", "por_que": "p"}]})})
    pr = c.post(f"/checagem/dossie/{pid}/web/prompt", json={}).get_json()
    assert pr["ok"] and "V1" in pr["prompt"]
    resp = json.dumps({"correcoes": [{"item": "C1", "de": "Haarmann arbeitete ab 1924 als Informant",
                                      "para": "Haarmann arbeitete spätestens ab 1918 als Informant", "eixo": "cronologia",
                                      "fonte": "https://example.org/haarmann"}],
                       "conferidos": [{"item": "V1", "ok": True, "fonte": "https://example.org/brief", "nota": "confirmado"}],
                       "resumo": "ok"})
    r = c.post(f"/checagem/dossie/{pid}/web/ler", json={"texto": resp}).get_json()
    assert r["ok"] and len(r["aplicadas"]) == 1 and r["verificar_marcados"] == 1
    q = ds.carregar(A.BASE_DIR, pid)
    assert "spätestens ab 1918" in q["resultado"]["roteiro"]
    assert q["checagem"]["verificar"][0]["conferido"] and q["checagem"]["verificar"][0]["fonte_web"].endswith("/brief")
    assert q["checagem"]["web"]["aplicadas"] == 1
    assert c.post(f"/checagem/dossie/{pid}/web/ler", json={"texto": "{}"}).status_code == 400
