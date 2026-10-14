"""v84_99 — 📏 roteiro que passa do tempo (25 min pedidos → 38 min): partes com intervalo de tamanho (mín–máx), parte
"longa", "já contado" (sem recontar), aviso de LONGO; 🪄 revisão no modo ✂️ enxugar (trocas que cortam/apagam), "de"
achado mesmo com aspas „“ × ""; regras de narração (sem suspense vazio, conclusão do tamanho da prova, sem fórmulas de
análise, frases curtas na tensão); 🤖 /ia/gerar em texto puro pro TTS e pras partes."""
import json

import adaptar_tts as at
import dossies as ds
import metodo_roteiro as mr
import revisao_roteiro as rv
import roteiro_partes as rp


def _txt(n, s="Wort"):
    return " ".join(f"{s}{i}" for i in range(n))


# ------------------------------------------------------------------ partes
def _partes():
    caps = [{"titulo": f"K{k}", "objetivo": f"o{k}", "fatos": [{"fato": f"Fakt {k}", "fonte": "F1"}], "palavras": 400} for k in range(1, 5)]
    return rp.de_plano(caps, 1600)


def test_status_e_falta():
    ps = _partes()
    assert rp.status_de(ps[0]) == "pendente"
    ps[0]["texto"] = _txt(400)
    ps[1]["texto"] = _txt(200)
    ps[2]["texto"] = _txt(700)
    ps[3]["texto"] = _txt(480)
    assert [rp.status_de(p) for p in ps] == ["pronta", "curta", "longa", "pronta"]
    assert rp.falta(ps) == [2, 3]
    ps[2]["aceita_curta"] = True
    assert rp.falta(ps) == [2]


def test_prompt_parte_intervalo_ja_contado_e_enxuto():
    ps = _partes()
    ps[0]["texto"] = _txt(400)
    ctx = {"tema": "Haarmann", "idioma": "alemão", "minutos": 25}
    t = rp.prompt_parte(ctx, ps, 3)
    assert "ENTRE 360 e 440 palavras" in t and "DURAÇÃO FIXA" in t and "NO MÍNIMO" not in t
    assert "JÁ CONTADO" in t and "Fakt 1" in t and "Fakt 2" in t
    assert "Vem DEPOIS" in t and "4. K4" in t.split("Vem DEPOIS")[1]
    assert "SEM ENCHIMENTO" in t and "Hier liegt die eigentliche Frage" in t and "suspense vazio" in t
    ps[2]["texto"] = _txt(800)
    t = rp.prompt_parte(ctx, ps, 3)
    assert "LONGO demais" in t and "ENXUTA" in t
    ps[2]["texto"] = _txt(100)
    assert "curto demais" in rp.prompt_parte(ctx, ps, 3)


def test_montar_menos_vendas():
    ps = [{"k": k, "titulo": f"K{k}", "palavras": 400, "texto": _txt(470)} for k in range(1, 13)]
    rot, _caps = rp.montar(ps)
    assert 2 <= rot.count("[[VENDA]]") <= 4


def test_aviso_longo_no_dossie():
    assert mr.aviso_longo(3000, 3750, 25) == ""
    assert "LONGO" in mr.aviso_longo(5664, 3750, 25) and "enxugar" in mr.aviso_longo(5664, 3750, 25)
    assert "SEM ENCHIMENTO" in mr.bloco("longo") and "SEM ENCHIMENTO" not in mr.bloco("curto")
    p = {"id": "x", "tema": "t", "config": dict(ds.CONFIG_PADRAO, minutos=25, modo_partes="nao")}
    res = ds.ler_resultado(json.dumps({"roteiro": _txt(5600, "Satz")}), p)
    assert res["alvo"]["longo"] and any("LONGO" in a for a in res["avisos"])
    res = ds.ler_resultado(json.dumps({"roteiro": _txt(3700, "Satz")}), p)
    assert not res["alvo"]["longo"]


# ------------------------------------------------------------------ 🪄 revisão
ROT = ("Die Zeitungen schrieben vom „Werwolf“ – und vom „Vampir“… Niemand wusste mehr.\n\n[[VENDA]]\n\n"
       "Hier liegt die eigentliche Frage. Man muss an dieser Stelle vorsichtig sein.\n\n[[VENDA]]\n\nEr wurde verhaftet.")


def test_modo_automatico_e_prompt_enxugar():
    assert rv.modo_efetivo("auto", 5664, 3750) == "enxugar"
    assert rv.modo_efetivo("auto", 3800, 3750) == "melhorar"
    assert rv.modo_efetivo("melhorar", 5664, 3750) == "melhorar"
    assert rv.modo_efetivo("xyz", 100, 0) == "melhorar"
    t = rv.prompt(_txt(5664), "alemão", "Haarmann", alvo_palavras=3750, minutos=25)
    assert "MODO ENXUGAR" in t and "corte ~1914 palavras" in t and '(vazio) pra APAGAR' in t and "NUNCA mais curta" not in t
    assert "AFIRMAÇÃO DO TAMANHO DA PROVA" in t
    t = rv.prompt(_txt(3700), "alemão", alvo_palavras=3750, minutos=25)
    assert "MODO ENXUGAR" not in t and "NUNCA mais curta" in t and "FIM DE SEÇÃO COM SUBSTÂNCIA" in t


def test_aplicar_aspas_diferentes_e_apagar():
    r = rv.aplicar(ROT, json.dumps({"trocas": [
        {"de": 'Die Zeitungen schrieben vom "Werwolf" - und vom "Vampir"... Niemand', "para": "Die Zeitungen sprachen vom „Werwolf“. Niemand"},
        {"de": "Hier liegt die eigentliche Frage. Man muss an dieser Stelle vorsichtig sein.", "para": ""}]}))
    assert len(r["aplicadas"]) == 2 and not r["nao_achadas"]
    assert r["texto"].count("[[VENDA]]") == 1 and "\n\n\n" not in r["texto"]
    assert r["palavras_depois"] < r["palavras_antes"] and "]" not in " ".join(r["texto"].replace("[[VENDA]]", "").split())


# ------------------------------------------------------------------ 🎙 TTS e 🤖 IA em texto puro
def test_tts_resposta_json_com_qualquer_chave():
    orig = "Im Mai 1924 fanden Kinder einen Schädel. " * 10
    r = at.ler_resposta(json.dumps({"roteiro_tts": orig + " Ende.", "nota": "x"}), orig)
    assert r["texto"].endswith("Ende.")
    assert "TEXTO PURO" in at.prompt(orig, "de", "true_crime", "", "chatterbox")


def test_ia_gerar_texto_puro(monkeypatch):
    import app as _app
    import ia_servico
    import tarefas_bg
    vistos = []
    monkeypatch.setattr(ia_servico, "motivo_desligado", lambda *a, **k: "")
    monkeypatch.setattr(ia_servico, "chamar", lambda recurso, system, prompt, **k: vistos.append(system) or "ok")
    c = _app.app.test_client()
    for pr in ("Adapte.\n## SAÍDA\nSomente o roteiro — TEXTO PURO (sem JSON)", 'Responda {"roteiro": "..."} — só o JSON'):
        d = c.post("/ia/gerar", json={"prompt": pr, "bg": True}).get_json()
        tarefas_bg.esperar(d["tarefa"], 10)
    assert "texto puro" in vistos[0] and "JSON pedido" in vistos[1]


def test_rotas_revisao_modo(monkeypatch):
    import app as _app
    base = _app.BASE_DIR
    p = ds.criar(base, "Caso longo")
    try:
        p["config"].update(minutos=2, modo_partes="nao")
        p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": ROT + " " + _txt(600, "Satz")}), p)
        ds.salvar(base, p)
        c = _app.app.test_client()
        i = c.get(f"/revisao/dossie/{p['id']}/info").get_json()
        assert i["ok"] and i["alvo"] == 300 and i["modo_auto"] == "enxugar"
        d = c.post(f"/revisao/dossie/{p['id']}/prompt", json={"modo": "auto"}).get_json()
        assert d["modo"] == "enxugar" and "MODO ENXUGAR" in d["prompt"]
        d = c.post(f"/revisao/dossie/{p['id']}/prompt", json={"modo": "melhorar"}).get_json()
        assert d["modo"] == "melhorar" and "MODO ENXUGAR" not in d["prompt"]
        rr = c.post(f"/revisao/dossie/{p['id']}/ler", json={"texto": json.dumps({"trocas": [
            {"de": "Hier liegt die eigentliche Frage.", "para": ""}]})}).get_json()
        assert rr["ok"] and "eigentliche Frage" not in ds.carregar(base, p["id"])["resultado"]["roteiro"]
        h = c.get(f"/modelos-video/{p['id']}").get_data(as_text=True)
        assert 'id="revModo"' in h and "⚠ longo" in h
    finally:
        ds.excluir(base, p["id"])
