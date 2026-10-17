import checagem_roteiro as ch


def _texto():
    nomes = "Sheri Elliott Robert Schultz Joyce Michigan Flint Ermittler"
    pars = [f"{nomes} {extra}" for extra in (
        "fuhr morgens zur Schule durch den Park", "kaufte Brot beim Bäcker an der Ecke", "spielte Klavier im Keller abends",
        "malte Bilder vom Fluss im Sommer", "schrieb Briefe an eine Freundin weit weg", "reparierte das alte Fahrrad im Hof",
        "sammelte Steine am Ufer des Sees", "las Romane unter der großen Eiche", "kochte Suppe für die Nachbarn nebenan",
        "fotografierte Vögel mit der Kamera")]
    return "\n\n".join(pars)


def test_nomes_do_caso_nao_viram_repeticao():
    assert ch.analisar(_texto())["repeticoes"] == []


def test_par_ignorado_some():
    t = "\n\n".join(["Die Polizei fand das Fahrrad verlassen am Waldrand neben der Straße bei Nacht"] +
                    [f"Absatz {i} über etwas völlig anderes hier {i}" for i in range(4)] +
                    ["Die Polizei fand das Fahrrad verlassen am Waldrand neben der Straße am Morgen"])
    reps = ch.analisar(t)["repeticoes"]
    assert reps and reps[0]["chave"]
    assert ch.analisar(t, ignorar={reps[0]["chave"]})["repeticoes"] == []


def test_ler_web_guarda_o_item_e_aceita_lista_de_textos():
    d = ch.ler_web('{"correcoes": [{"item": "v 3", "de": "a", "para": "b"}], "conferidos": ["R2", {"item": "V1", "ok": true}]}')
    assert d["trocas"][0]["item"] == "V3" and [c["item"] for c in d["conferidos"]] == ["R2", "V1"]


def test_rota_web_ler_com_resposta_torta():
    import json
    import os
    import shutil
    import app as a
    import dossies as ds
    c = a.app.test_client()
    p = ds.criar(a.BASE_DIR, "teste web ler")
    try:
        pars = ["Am 31. März 1922 wurden sechs Menschen ermordet."] + [f"Absatz {i}: Die Ermittler prüften Spuren {i}." for i in range(10)]
        p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": "\n\n".join(pars), "titulos": ["x"]}), p)
        p["checagem"] = {"verificar": [{"afirmacao": "a"}], "web_itens": ["C1", "V1", "R1", "D1"]}
        ds.salvar(a.BASE_DIR, p)
        resp = {"correcoes": [{"item": "V1", "de": "Absatz 3: Die Ermittler", "para": "Absatz 3: Die Polizei", "status": None, "fonte": None}],
                "conferidos": [{"item": "R1", "ok": True}, {"item": "C1", "ok": "false"}, "V9", {"item": 5}]}
        r = c.post(f"/checagem/dossie/{p['id']}/web/ler", json={"texto": json.dumps(resp)})
        assert r.status_code == 200, r.get_data(as_text=True)[:300]
        d = r.get_json()
        assert len(d["aplicadas"]) == 1 and "D1" in d["sem_resposta"]
    finally:
        shutil.rmtree(os.path.join(a.BASE_DIR, "dossies", p["id"]), ignore_errors=True)
