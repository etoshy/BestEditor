"""v84_161: layout novo (menu lateral, tema), saldo do Claude, últimas escolhas e links de vídeo → transcrição nas anotações."""
import json
import os
import shutil

import pytest


def test_layout_tem_menu_tema_e_saldo():
    import app as a
    c = a.app.test_client()
    h = c.get("/modelos-video").get_data(as_text=True)
    for trecho in ('class="app-sidebar"', 'data-ui-tema-btn', 'id="saldoBox"', 'id="sinoBtn"', "ui/tema.css", "ui/ui.js",
                   "vendor/fontawesome/css/all.min.css", 'class="item ativo"'):
        assert trecho in h, trecho
    assert c.get("/static/ui/ui.js").status_code == 200
    assert c.get("/static/vendor/fontawesome/webfonts/fa-solid-900.woff2").status_code == 200


def test_saldo_e_credito():
    import app as a
    import ia_servico as ia
    ia.zerar_gasto()
    with ia.rotulo("Roteiro: teste"):
        ia._registrar("roteiros", {"input_tokens": 1000, "output_tokens": 500}, 0.002, None, True)
    ia._registrar_cache("juiz", None)
    c = a.app.test_client()
    d = c.get("/ia/saldo").get_json()
    assert d["gasto_usd"] == pytest.approx(0.002) and d["chamadas"] == 1 and d["saldo_usd"] is None
    assert d["log"][0]["cache"] and d["log"][1]["rotulo"] == "Roteiro: teste"
    assert d["por_recurso"][0]["nome"] == "Roteiros direto na IA"
    assert c.post("/ia/credito", json={"credito_usd": "10,50"}).get_json()["credito_usd"] == 10.5
    d = c.get("/ia/saldo").get_json()
    assert d["saldo_usd"] == pytest.approx(10.498)
    c.post("/ia/credito", json={"credito_usd": 0})
    ia.zerar_gasto()


def test_ultimas_escolhas(monkeypatch, tmp_path):
    import ultimas_escolhas as ue
    import dossies as ds
    import modelados as md
    monkeypatch.delenv("ULTIMAS_ESCOLHAS_DESLIGADO", raising=False)
    monkeypatch.setenv("ULTIMAS_ESCOLHAS_DIR", str(tmp_path))
    base = str(tmp_path)
    ue.lembrar(base, idioma="en", nome_canal="  Casos   Arquivados ", modelado_idioma="inglês")
    assert ue.ler(base) == {"idioma": "en", "nome_canal": "Casos Arquivados", "modelado_idioma": "inglês"}
    p = ds.criar(base, "tema")
    assert p["config"]["idioma"] == "en" and p["config"]["nome_canal"] == "Casos Arquivados"
    proj = md.criar_projeto(base, "", md.listar_estilos()[0]["id"], "uma lenda")
    assert proj["nome_canal"] == "Casos Arquivados"


def test_narracao_nova_herda_a_voz(monkeypatch, tmp_path):
    import narracoes as nr
    monkeypatch.delenv("ULTIMAS_ESCOLHAS_DESLIGADO", raising=False)
    base = str(tmp_path)
    p1 = nr.criar_projeto(base, "um")
    nr.salvar_config(base, p1["projetoId"], motor="kokoro", voz="pf_dora", idioma="pt", velocidade=1.2)
    p2 = nr.criar_projeto(base, "dois")
    assert (p2["motor"], p2["voz"], p2["velocidade"]) == ("kokoro", "pf_dora", 1.2)


def test_link_de_video_vira_transcricao_nas_anotacoes(monkeypatch):
    import app as a
    import dossies as ds
    import roteiros_yt as ry
    import tarefas_bg
    chamados = []

    def falso(url, pasta, **_k):
        chamados.append(url)
        return {"titulo": "Vídeo A", "com_tempo": True, "blocos": [{"inicio": 0, "texto": "primeira frase."}, {"inicio": 5, "texto": "segunda frase."}]}
    monkeypatch.setattr(ry, "extrair_transcricao", falso)
    monkeypatch.setattr(ds, "adicionar_fonte", lambda p, u: (_ for _ in ()).throw(AssertionError("vídeo não é matéria")))
    p = ds.criar(a.BASE_DIR, "teste vídeo")
    p["roteiro_base"] = "minhas notas"
    ds.salvar(a.BASE_DIR, p)
    try:
        c = a.app.test_client()
        d = c.post(f"/modelos-video/{p['id']}/fontes", json={"urls": "https://www.youtube.com/watch?v=abcdefghijk"}).get_json()
        assert d["videos"] == 1 and d["tarefa_videos"] and d["novas"] == []
        t = tarefas_bg.esperar(d["tarefa_videos"], 20)
        assert t and t["status"] == "pronto", t
        q = ds.carregar(a.BASE_DIR, p["id"])
        assert q["roteiro_base"].startswith("minhas notas\n\n── Transcrição: Vídeo A ──")
        assert "primeira frase.\n\nsegunda frase." in q["roteiro_base"] and "[0:00]" not in q["roteiro_base"]
        assert chamados == ["https://www.youtube.com/watch?v=abcdefghijk"]
    finally:
        shutil.rmtree(os.path.join(a.BASE_DIR, "dossies", p["id"]), ignore_errors=True)
