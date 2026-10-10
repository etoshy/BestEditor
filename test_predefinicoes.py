"""Predefinições criadas pela pessoa (perfis como Documentário/Cinema/Cortes) e paletas próprias."""
import json
import os

import pytest

import dp_direcao as dr


@pytest.fixture(autouse=True)
def arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "ARQUIVO_USUARIO", str(tmp_path / "predef.json"))
    yield


SEGS = [{"start": i * 3.0, "end": i * 3.0 + 3, "foto": True} for i in range(30)]


def _p(**kw):
    base = {"nome": "Meu noir", "ritmo": "equilibrado", "universo": "predef",
            "filtros": {"pct": 100, "itens": [{"id": "noir", "peso": 1}]},
            "efeitos": {"pct": 100, "itens": [{"id": "zoom_giro"}]},
            "overlays": {"pct": 100, "itens": [{"id": "ov_poeira"}]},
            "transicoes": {"pct": 100, "itens": [{"id": "dp:gl_flash", "peso": 3}, {"id": "blinds_h"}, {"id": "nao_existe"}]},
            "entradas": {"pct": 0, "itens": []}, "templates": {"pct": 0, "itens": []},
            "destaques": {"densidade": "dinamico", "estilos": ["selo_ano", "xx"]},
            "cores": {"modo": "predef", "primaria": "#3e8eff"}, "legenda": {"estilo": "pop"}}
    base.update(kw)
    return base


class TestCrud:
    def test_salvar_normaliza_e_lista(self):
        p = dr.salvar_predefinicao(_p())
        assert p["id"] == "u_meu_noir" and p["usuario"]
        assert [i["id"] for i in p["transicoes"]["itens"]] == ["gl_flash", "blinds_h"]  # id desconhecido sai
        assert p["destaques"]["estilos"] == ["selo_ano"] and p["destaques"]["densidade"] == "dinamico"
        assert p["cores"]["primaria"] == "#3E8EFF" and p["cores"]["secundaria"].startswith("#")
        assert p["legenda"]["estilo"] == "pop" and p["legenda"]["ativa"] is True
        ids = [d["id"] for d in dr.direcoes()]
        assert ids[:4] == ["sys_tudo", "sys_doc_classico", "sys_cinema", "sys_dinamico"] and "u_meu_noir" in ids
        # mesmo nome de novo = outra; com id = atualiza
        assert dr.salvar_predefinicao(_p())["id"] == "u_meu_noir_2"
        p2 = dr.salvar_predefinicao(dict(_p(nome="Renomeada"), id="u_meu_noir"))
        assert p2["id"] == "u_meu_noir" and dr.direcao("u_meu_noir")["nome"] == "Renomeada"
        assert dr.apagar_predefinicao("u_meu_noir") and not dr.apagar_predefinicao("u_meu_noir")
        assert not dr.apagar_predefinicao("sys_cinema")

    def test_sem_nome_e_invalida(self):
        with pytest.raises(ValueError):
            dr.salvar_predefinicao(_p(nome="  "))
        with pytest.raises(ValueError):
            dr.salvar_predefinicao("x")

    def test_arquivo_corrompido_nao_quebra(self):
        with open(dr.ARQUIVO_USUARIO, "w") as f:
            f.write("{nada")
        assert [d["id"] for d in dr.direcoes()][:1] == ["sys_tudo"]


class TestPlano:
    def test_plano_usa_os_eixos_e_devolve_cor_e_legenda(self):
        p = dr.salvar_predefinicao(_p())
        pl = dr.planejar(SEGS, p["id"], 2)
        assert pl["filtro_cor"] == "noir"
        assert {t["transition"] for t in pl["trechos"][:-1]} <= {"dp:gl_flash", "blinds_h"}
        efs = {t["efeito"] for t in pl["trechos"]}
        assert efs <= {"zoom_giro", "ov_poeira"} and "zoom_giro" in efs
        assert pl["cores"]["modo"] == "projeto" and pl["cores"]["primaria"] == "#3E8EFF"
        assert pl["legenda"]["estilo"] == "pop" and pl["destaques"]["densidade"] == "dinamico"
        assert pl == dr.planejar(SEGS, p["id"], 2)  # determinístico

    def test_overlays_entram_onde_nao_tem_movimento(self):
        p = dr.salvar_predefinicao(_p(efeitos={"pct": 0, "itens": []}, overlays={"pct": 100, "itens": [{"id": "ov_leak"}]}))
        pl = dr.planejar([dict(s, foto=False) for s in SEGS], p["id"], 1)
        assert {t["efeito"] for t in pl["trechos"]} == {"ov_leak"}

    def test_modos_de_cor(self):
        a = dr.salvar_predefinicao(_p(nome="a", cores={"modo": "auto"}))
        b = dr.salvar_predefinicao(_p(nome="b", cores={"modo": "projeto"}))
        assert dr.planejar(SEGS, a["id"])["cores"] == {"modo": "auto"}
        assert dr.planejar(SEGS, b["id"])["cores"] is None
        assert dr.planejar(SEGS, "sys_cinema")["cores"] is None

    def test_universo_catalogo_preenche_eixo_vazio(self):
        p = dr.salvar_predefinicao(_p(universo="sistema", transicoes={"pct": 100, "itens": []}, efeitos={"pct": 100, "itens": []}, overlays={"pct": 0, "itens": []}))
        pl = dr.planejar(SEGS, p["id"], 1)
        assert len({t["transition"] for t in pl["trechos"][:-1]}) > 5
        import dp_visual
        assert all(dp_visual.efeito_e_movimento(t["efeito"]) for t in pl["trechos"] if t["efeito"])  # movimento = só câmera

    def test_duplicar_do_sistema_separa_overlays(self):
        e = dr.para_edicao("sys_doc_classico")
        assert e["nome"].startswith("Cópia de") and "id" not in e
        import dp_visual
        assert all(dp_visual.efeito_e_movimento(i["id"]) for i in e["efeitos"]["itens"])
        assert all(not dp_visual.efeito_e_movimento(i["id"]) for i in (e.get("overlays") or {}).get("itens", []))
        salvo = dr.salvar_predefinicao(e)
        assert salvo["id"].startswith("u_copia_de_documentario")


class TestPaletas:
    def test_paletas(self):
        p = dr.salvar_paleta({"nome": "Minha azul", "primaria": "#112233"})
        assert p["id"] == "up_minha_azul" and p["secundaria"].startswith("#")
        assert [x["id"] for x in dr.paletas_usuario()] == ["up_minha_azul"]
        with pytest.raises(ValueError):
            dr.salvar_paleta({"nome": "x", "primaria": "azul"})
        assert dr.apagar_paleta("up_minha_azul") and dr.paletas_usuario() == []


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


class TestRotas:
    def test_rotas(self, A):
        c = A.app.test_client()
        r = c.post("/predefinicoes", json=_p())
        assert r.status_code == 200 and r.get_json()["predefinicao"]["id"] == "u_meu_noir"
        assert any(d["id"] == "u_meu_noir" for d in c.get("/predefinicoes").get_json()["direcoes"])
        assert c.post("/predefinicoes", json={"nome": ""}).status_code == 400
        e = c.post("/predefinicoes/edicao", json={"id": "sys_cinema"}).get_json()
        assert e["ok"] and e["predefinicao"]["nome"] == "Cópia de Cinema premium"
        e = c.post("/predefinicoes/edicao", json={"id": "kit", "kit": {"filtros": ["noir"]}}).get_json()
        assert e["predefinicao"]["filtros"]["itens"] == [{"id": "noir", "peso": 1}]
        assert c.post("/predefinicoes/edicao", json={"id": "nada"}).status_code == 404
        jid = "predef-app"
        os.makedirs(A._job_dir(jid), exist_ok=True)
        A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 6.0,
                        "pending_segments": [{"start": 0.0, "end": 3.0, "provider": "pexels", "query": "a"}, {"start": 3.0, "end": 6.0, "provider": "pexels", "query": "b"}],
                        "segment_previews": [{"index": 0, "ok": False}, {"index": 1, "ok": False}], "segments": []}
        p = c.post(f"/job/{jid}/direcao/plano", json={"direcao": "u_meu_noir", "segmentos": [{"start": 0, "end": 3, "foto": True}, {"start": 3, "end": 6, "foto": True}]}).get_json()
        assert p["filtro_cor"] == "noir" and p["cores"]["primaria"] == "#3E8EFF"
        html = c.get(f"/job/{jid}/edit-segments?modo=estudio").get_data(as_text=True)
        assert 'id="pdModal"' in html and "u_meu_noir" in html and 'id="pcSalvar"' in html
        assert c.post("/paletas", json={"nome": "Azul", "primaria": "#0000FF"}).get_json()["paleta"]["id"] == "up_azul"
        assert c.delete("/paletas/up_azul").status_code == 200 and c.delete("/paletas/up_azul").status_code == 404
        assert c.delete("/predefinicoes/u_meu_noir").status_code == 200
        assert c.delete("/predefinicoes/sys_cinema").status_code == 404

    def test_ia_escolhe_predefinicao_da_pessoa(self, A):
        dr.salvar_predefinicao(_p())
        job = {"pending_segments": [{"start": 0.0, "end": 3.0}, {"start": 3.0, "end": 6.0}], "segments": []}

        class P:
            direcao = "u_meu_noir"; filtro_cor = None; paleta = None; destaques = None
        A._aplicar_extras_dp(job, P())
        assert job["editor_defaults"]["paleta"]["primaria"] == "#3E8EFF" and job["legendas"]["estilo"] == "pop"


class TestSugerirComPredefinicao:
    def test_estilos_da_predefinicao_mandam_e_semente_varia(self, A):
        dr.salvar_predefinicao(_p(destaques={"densidade": "maximo", "estilos": ["selo_ano"]}))
        c = A.app.test_client()
        jid = "predef-hl"
        os.makedirs(A._job_dir(jid), exist_ok=True)
        frases = ["Em 1945 a guerra acabou", "Em 1950 veio a reconstrução", "Em 1961 o muro subiu", "Em 1989 o muro caiu", "Em 1990 a Alemanha se uniu"]
        A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 50.0,
                        "pending_segments": [{"start": 0.0, "end": 50.0, "provider": "pexels", "query": "a"}], "segment_previews": [{"index": 0, "ok": False}],
                        "segments": [{"start": i * 10.0, "end": i * 10.0 + 9, "text": f} for i, f in enumerate(frases)],
                        "editor_defaults": {"kit": {"destaques": ["glow_01"]}}}
        r = c.post(f"/job/{jid}/destaques/sugerir", json={"direcao": "u_meu_noir", "semente": 7}).get_json()
        assert r["destaques"] and {d["estilo"] for d in r["destaques"]} == {"selo_ano"}
        # kit enviado pelo Estúdio (ainda não salvo) vale pra "★ Minha direção"
        r = c.post(f"/job/{jid}/destaques/sugerir", json={"direcao": "kit", "kit": {"destaques": ["selo_ano"]}}).get_json()
        assert {d["estilo"] for d in r["destaques"]} <= {"selo_ano"}
