"""
v84_51/52 — 🔊 sons dos quadros editoriais (os da biblioteca do site) + 🎨 direções: os extras com "direcoes" entram nas direções do
sistema e cada direção diz quais quadros editoriais a IA usa (e com que frequência).
"""
import json
import os
import subprocess

import pytest

import dp_direcao
import dp_editorial as E
import dp_sons

def test_sons_editoriais_sao_da_biblioteca():
    # v84_52: os sons tirados dos vídeos de referência saíram; tudo usa os sons que o site já tinha
    assert "editorial" not in {c["nome"] for c in dp_sons.categorias()}
    for papel, sid in E.SONS.items():
        assert dp_sons.som(sid) and os.path.isfile(dp_sons.caminho(sid)), (papel, sid)


@pytest.mark.parametrize("tipo", sorted(E.TIPOS))
def test_cada_quadro_tem_som(tipo):
    q = E.exemplo(tipo, 10.0)
    b = E.batidas(q)
    assert b, tipo
    dur = q["end"] - q["start"]
    for t, sid, vol, al in b:
        assert dp_sons.som(sid) and 0 <= t <= dur and 0 < vol <= 1 and al in ("pico", "inicio")
    assert E.batidas(dict(q, som="nenhum")) == []
    ev = E.eventos_sonoros([q])
    assert len(ev) == len(b) and all(e["inicio"] >= 0 for e in ev)


def test_som_e_campo_do_painel_e_normaliza():
    assert any(c["k"] == "som" for c in E.para_editor()["ficha"]["campos"])
    assert any(c["k"] == "fundo" for c in E.para_editor()["terminal"]["campos"])
    assert not any(c["k"] == "fundo" for c in E.para_editor()["ficha"]["campos"])
    assert E.normalizar({"tipo": "numero", "som": "xyz"})["som"] == "auto"
    assert E.normalizar({"tipo": "numero", "som": "nenhum"})["som"] == "nenhum"


def test_terminal_linha_vermelha_ganha_alerta():
    q = E.normalizar({"tipo": "terminal", "start": 0, "end": 8, "linhas": "a\nb\n!ERRO"})
    sons = [s for _t, s, _v, _a in E.batidas(q)]
    assert sons.count(E.SONS["erro"]) == 1 and sons.count(E.SONS["linha"]) == 2 and E.SONS["digitando"] in sons
    q2 = E.normalizar({"tipo": "terminal", "start": 0, "end": 3, "linhas": "a\nb"})
    sons2 = [s for _t, s, _v, _a in E.batidas(q2)]
    assert E.SONS["erro"] not in sons2 and E.SONS["digitando"] not in sons2  # curto: sem a digitação de 5 s


def test_eventos_automaticos_inclui_editoriais():
    eds = [E.exemplo("numero", 5.0), E.exemplo("explosao", 20.0)]
    ev = dp_sons.eventos_automaticos([], [], [], [], {"transicoes": False, "cenas": False, "destaques": False}, editoriais=eds)
    assert {e["som"] for e in ev} == {E.SONS["passo"], E.SONS["numero_fim"], E.SONS["explosao"], E.SONS["explosao_ar"]}
    assert dp_sons.eventos_automaticos([], [], [], [], {"editoriais": False}, editoriais=eds) == []


def test_mixa_de_verdade(tmp_path):
    nar = str(tmp_path / "n.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "6", nar], check=True)
    ev = E.eventos_sonoros([E.exemplo("numero", 1.0)])
    out = dp_sons.mixar(nar, ev, str(tmp_path / "o.wav"))
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", out, "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    assert "max_volume" in r.stderr and float(r.stderr.split("max_volume:")[1].split("dB")[0]) > -20


# ------------------------------------------------------------------ direções
@pytest.fixture
def extras(tmp_path, monkeypatch):
    import dp_extras
    import dp_visual
    pasta = tmp_path / "extras"
    pasta.mkdir()
    (pasta / "ref.json").write_text(json.dumps({
        "transicoes": [{"id": "t_ref_a", "rotulo": "A", "xfade": "wiperight", "direcoes": ["sys_cinema", "sys_tudo"]},
                       {"id": "t_ref_b", "rotulo": "B", "xfade": "fade", "direcoes": ["sys_cinema"]}],
        "filtros": [{"id": "f_ref", "rotulo": "F", "cadeia": "eq=contrast=1.1", "css": "contrast(1.1)", "direcoes": ["sys_doc_classico"]}],
        "entradas": [{"id": "e_ref", "rotulo": "E", "igual_a": "punch_in", "direcoes": ["sys_doc_classico"]}],
        "_direcoes": {"sys_cinema": {"transicoes": [{"id": "t_ref_a"}]}},
    }), encoding="utf-8")
    monkeypatch.setenv("DP_EXTRAS_DIR", str(pasta))
    dp_extras.recarregar()
    yield pasta
    monkeypatch.undo()  # volta o DP_EXTRAS_DIR de antes
    dp_extras.recarregar()


def test_extras_entram_nas_direcoes(extras):
    import dp_visual
    orig = {p["id"]: p for p in dp_visual.dp()["presets"]["system"]}
    cin = dp_direcao.direcao("sys_cinema")
    ids = [i["id"] for i in cin["transicoes"]["itens"]]
    assert ids[-2:] == ["t_ref_a", "t_ref_b"]
    w_orig = sum(i["peso"] for i in cin["transicoes"]["itens"] if i.get("original"))
    w_ext = sum(i["peso"] for i in cin["transicoes"]["itens"] if i.get("extra"))
    assert w_orig >= w_ext  # o que já existia continua com pelo menos metade
    assert [i["id"] for i in orig["sys_cinema"]["transicoes"]["itens"]] == ids[:-2]  # o JSON de fábrica não muda
    doc = dp_direcao.direcao("sys_doc_classico")
    assert "f_ref" in [i["id"] for i in doc["filtros"]["itens"]]
    assert doc["entradas"]["pct"] == 15 and [i["id"] for i in doc["entradas"]["itens"]] == ["e_ref"]
    # Padrão do sistema: lista vazia = catálogo inteiro (que já tem os extras) — não vira lista
    assert dp_direcao.direcao("sys_tudo")["transicoes"]["itens"] == []
    assert "dp:t_ref_a" in [dp_visual.valor_transicao(t) for t, _w in dp_direcao._itens(dp_direcao.direcao("sys_tudo"), "transicoes")]
    lst = {d["id"]: d for d in dp_direcao.direcoes(com_usuario=False)}
    assert lst["sys_cinema"]["extras"] == 2 and lst["sys_tudo"]["extras"] == 0
    # o plano usa os extras
    segs = [{"start": i * 3.0, "end": i * 3 + 3.0, "foto": True} for i in range(60)]
    trs = {t["transition"] for t in dp_direcao.planejar(segs, "sys_cinema", semente=7)["trechos"]}
    assert trs & {"dp:t_ref_a", "dp:t_ref_b"}


def test_editoriais_de_cada_direcao():
    ed = {d["id"]: d["editoriais"] for d in dp_direcao.direcoes(com_usuario=False)}
    assert ed["sys_tudo"]["tipos"] == [] and ed["sys_tudo"]["ativo"]
    assert ed["sys_cinema"]["segundos"] == 60 and "terminal" not in ed["sys_cinema"]["tipos"]
    assert ed["sys_dinamico"]["segundos"] == 25 and "post" in ed["sys_dinamico"]["tipos"]
    assert all(set(e["tipos"]) <= set(E.TIPOS) for e in ed.values())
    p = dp_direcao.normalizar_predefinicao({"nome": "Minha", "editoriais": {"ativo": False, "densidade": "maximo", "tipos": ["numero", "xx"]}})
    assert p["editoriais"] == {"ativo": False, "densidade": "maximo", "tipos": ["numero"]}
    assert dp_direcao.normalizar_predefinicao({"nome": "Velha"})["editoriais"]["ativo"] is True
    assert dp_direcao.editoriais_da({"nome": "antiga sem o campo"})["segundos"] == 40
    assert dp_direcao.planejar([{"start": 0, "end": 3, "foto": True}], "sys_cinema")["editoriais"]["densidade"] == "minimal"


def test_prompt_segue_a_direcao(monkeypatch):
    import prompt_edicao
    job = {"pending_segments": [{"start": 0, "end": 4}], "total_duration": 4.0, "segments": []}
    pr = prompt_edicao.montar_prompt(job, {"direcao": "sys_cinema"})
    assert "Quadros editoriais: ~1 a cada 60 s — use SÓ estes tipos: nome, titulo_video" in pr
    assert "- numero = " in pr and "- terminal = " not in pr
    monkeypatch.setattr(dp_direcao, "editoriais_da", lambda p: {"ativo": False, "densidade": "minimal", "tipos": [], "segundos": 60})
    pr = prompt_edicao.montar_prompt(job, {"direcao": "sys_cinema"})
    assert "Quadros editoriais: NÃO usar" in pr and "- numero = " not in pr


def test_extras_do_zip_estao_limpos(monkeypatch):
    import dp_extras
    monkeypatch.setenv("DP_EXTRAS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "darkplanner", "extras"))
    dp_extras.recarregar()
    if not any(n.startswith("referencias_") for n in dp_extras.resumo()["arquivos"]):
        pytest.skip("pasta de extras sem os extras de referência")
    r = dp_extras.resumo()
    assert r["erros"] == [] and r["contagem"]["transicoes"] >= 90 and r["contagem"]["filtros"] >= 99
    import dp_guia
    v = dp_guia.verificar()
    assert v["erros"] == [], v["erros"][:5]
    # e entram nas direções do sistema
    assert sum(1 for c in dp_direcao.EIXOS for i in (dp_direcao.direcao("sys_cinema").get(c) or {}).get("itens", []) if i.get("extra")) > 100
    monkeypatch.undo()
    dp_extras.recarregar()


def test_rota_sons_e_estudio():
    import app as A
    A.app.config["TESTING"] = True
    c = A.app.test_client()
    r = c.post("/editorial/sons", json={"itens": [E.exemplo("explosao", 3.0), {"tipo": "?"}]}).get_json()
    assert [e["som"] for e in r["eventos"]] == [E.SONS["explosao"], E.SONS["explosao_ar"]]
    html = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "estudio.html"), encoding="utf-8").read()
    assert 'id="sEd"' in html and "atualizarSonsEd" in html and "k: 'editoriais'" in html
