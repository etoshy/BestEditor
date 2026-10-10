"""Galerias com miniatura (destaques, filtros, animações, overlays) e o kit "★ Minha direção"."""
import json
import os

import pytest

import dp_destaques as dd
import dp_direcao as dr
import dp_galeria as dg
import dp_visual as dv


class TestMiniaturas:
    def test_todas_as_miniaturas_existem(self):
        for eid in dd.catalogo():
            assert dg.existe("destaques", f"{eid}.jpg"), eid
        for f in dv.filtros():
            assert dg.existe("filtros", f"{f['id']}.jpg"), f["id"]
        for g in dv.entradas():
            if g["id"] != "none":
                assert dg.existe("animacoes", f"entrada_{g['id']}.mp4") and dg.existe("animacoes", f"entrada_{g['id']}.jpg"), g["id"]
        for e in dv.efeitos():
            if e["id"] == "none":
                continue
            if dv.efeito_e_movimento(e["id"]):
                assert dg.existe("animacoes", f"camera_{e['id']}.mp4"), e["id"]
            else:
                assert dg.existe("overlays", f"{e['id']}.mp4") and dg.existe("overlays", f"{e['id']}.jpg"), e["id"]

    def test_previa_animada_de_destaque(self, tmp_path):
        p = dg.previa_destaque("selo_ano", str(tmp_path))
        assert p.endswith(".mp4") and os.path.getsize(p) > 1000
        assert dg.previa_destaque("selo_ano", str(tmp_path)) == p  # guardada
        with pytest.raises(ValueError):
            dg.previa_destaque("nao_existe", str(tmp_path))

    def test_tratamento_usa_uma_entrada_por_imagem(self, tmp_path):
        ds = [{"estilo": "marca_azul", "start": k * 2, "end": k * 2 + 1.5, "texto": "x"} for k in range(6)]
        ent, etapas = dd.filtros_de_tratamento(ds, 320, 180, str(tmp_path))
        assert ent.count("-i") == 1 and "split=6" in etapas[0]


class TestKit:
    def test_minha_direcao_usa_so_o_kit(self):
        segs = [{"start": i * 3.0, "end": i * 3.0 + 3, "foto": True} for i in range(20)]
        kit = {"filtros": ["noir"], "transicoes": ["dp:gl_flash", "blinds_h"], "animacoes_camera": ["zoom_giro"], "overlays": ["ov_poeira"], "entradas": ["pop"]}
        p = dr.planejar(segs, "kit", 3, kit=kit)
        assert p["filtro_cor"] == "noir"
        assert {t["transition"] for t in p["trechos"][:-1]} - {"none"} <= {"dp:gl_flash", "blinds_h"}
        assert {t["efeito"] for t in p["trechos"]} - {None} <= {"zoom_giro", "ov_poeira"}
        assert {t["entrada"] for t in p["trechos"]} - {None} <= {"pop"}
        assert dr.planejar(segs, "kit", 3, kit={})["filtro_cor"] is None

    def test_valor_transicao(self):
        assert dv.valor_transicao("gl_flash") == "dp:gl_flash" and dv.valor_transicao("dp:gl_flash") == "dp:gl_flash"
        assert dv.valor_transicao("blinds_h") == "blinds_h" and dv.valor_transicao("none") == "none"


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


class TestApp:
    def test_rotas_e_kit(self, A):
        c = A.app.test_client()
        assert c.get("/dp-galeria/destaques/glow_01.jpg").status_code == 200
        assert c.get("/dp-galeria/overlays/ov_leak.mp4").status_code == 200
        assert c.get("/dp-galeria/previa/nao_existe.mp4").status_code == 404
        jid = "kit-app"
        os.makedirs(A._job_dir(jid), exist_ok=True)
        A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 6.0,
                        "pending_segments": [{"start": 0.0, "end": 3.0, "provider": "pexels", "query": "a"}, {"start": 3.0, "end": 6.0, "provider": "pexels", "query": "b"}],
                        "segment_previews": [{"index": 0, "ok": False}, {"index": 1, "ok": False}],
                        "segments": [{"start": 0.0, "end": 3.0, "text": "Em 1945 a guerra acabou"}]}
        html = c.get(f"/job/{jid}/edit-segments?modo=estudio").get_data(as_text=True)
        assert 'id="tab-biblioteca"' in html and "btn-kit" in html and "/dp-galeria/" in html
        form = {"acao": "salvar", "seg_0_start": "0", "seg_0_end": "3", "seg_1_start": "3", "seg_1_end": "6", "destaques_json": "[]",
                "kit_json": json.dumps({"destaques": ["selo_ano"], "filtros": ["noir"]})}
        assert c.post(f"/job/{jid}/confirm-segments", data=form, headers={"X-Requested-With": "fetch"}).status_code == 200
        assert A._JOBS[jid]["editor_defaults"]["kit"]["destaques"] == ["selo_ano"]
        s = c.post(f"/job/{jid}/destaques/sugerir", json={}).get_json()
        assert s["ok"] and {d["estilo"] for d in s["destaques"]} <= {"selo_ano"}
        p = c.post(f"/job/{jid}/direcao/plano", json={"direcao": "kit", "segmentos": [{"start": 0, "end": 3}, {"start": 3, "end": 6}]}).get_json()
        assert p["filtro_cor"] == "noir"
