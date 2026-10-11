"""
Sons do editor original (audios.zip -> assets/sons, 11 categorias) e textos
animados avulsos (aba Textos no Estúdio + página /textos).
"""
import json
import os
import subprocess

import numpy as np
import pytest

import dp_destaques as dd
import dp_sons as ds
import dp_visual as dv


def _pcm(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
    return np.abs(np.frombuffer(raw, np.int16).astype(np.float32))


class TestBiblioteca:
    def test_124_sons_em_11_categorias_e_arquivos_existem(self):
        assert len(ds.sons()) == 124 and len(ds.categorias()) == 11
        assert ds.categorias()[0]["nome"] == "transições"
        for s in ds.sons():
            assert os.path.exists(os.path.join(ds.SONS_DIR, s["arquivo"])) and s["arquivo"].endswith(".m4a")
            assert 0 <= s["pico"] <= s["dur"] + 0.01

    def test_nomes_do_darkplanner_mapeados(self):
        d = dv.dp()
        nomes = set()
        for t in d["templates"].values():
            nomes.update(t["fisica"]["sons"])
        for h in d["highlights"].values():
            nomes.update((h.get("audio") or {}).get("assets") or [])
        for n in nomes:
            assert ds.do_darkplanner(n), n

    def test_toda_transicao_tem_som(self):
        import site_config
        for v, _r in site_config.TRANSITION_LABELS:
            if v != "none":
                assert ds.som(ds.som_da_transicao(v)), v
        assert ds.som_da_transicao("dp:ft_filmburn4") == "transicoes/film_burn_4"
        assert ds.som_da_transicao("dp_shutter") == "transicoes/obturador_mecanico"
        assert ds.som_da_transicao("none") is None


class TestMixagem:
    def test_som_entra_no_instante_certo_e_narracao_nao_muda_de_duracao(self, tmp_path):
        nar = tmp_path / "n.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "5", str(nar)], check=True)
        ev = ds.evento("impacto/impacto_5", 3.0)
        out = ds.mixar(str(nar), [ev], str(tmp_path / "o.wav"), volume_sfx=1.0)
        a = _pcm(out)
        assert abs(len(a) / 8000 - 5.0) < 0.05
        env = np.convolve(a, np.ones(200) / 200, "same")
        assert abs(np.argmax(env) / 8000 - 3.0) < 0.12  # o pico cai no evento
        assert env[: int(2.5 * 8000)].max() < env.max() * 0.05

    def test_sem_eventos_devolve_a_narracao(self, tmp_path):
        assert ds.mixar("/x/nar.wav", [], str(tmp_path / "o.wav")) == "/x/nar.wav"

    def test_eventos_automaticos(self):
        from prompt_builder import VideoSegment
        segs = [VideoSegment(0, 3, "p", "a"), VideoSegment(3, 6, "p", "b", transition_som="nenhum"), VideoSegment(6, 9, "p", "c")]
        plano = [("dp:ft_filmburn4", 0.6), ("fade", 0.6)]
        grupos = [(0, 0, None), (1, 2, "MULTITAKE_06")]
        dest = [{"estilo": "selo_ano", "start": 1.0, "end": 2.0}, {"estilo": "glow_01", "start": 4, "end": 5, "som": "nenhum"}]
        ev = ds.eventos_automaticos(segs, plano, grupos, dest, {"transicoes": True, "cenas": True, "destaques": True})
        sons = [e["som"] for e in ev]
        assert "transicoes/film_burn_4" in sons  # emenda 1
        assert sons.count("variados/whoosh_24") >= 1  # take da cena MULTITAKE_06 pede woosh_24
        assert "foley/digitacao_6_curta" in sons  # selo_ano -> typing_6
        assert len([s for s in sons if s == "transicoes/ar_suave"]) == 0  # emenda 2 está com "sem som"
        assert ds.eventos_automaticos(segs, plano, grupos, dest, {"transicoes": False, "cenas": False, "destaques": False}) == []


class TestMontagemComSons:
    def test_montagem_mixa_os_sons(self, tmp_path, synthetic_audio):
        from PIL import Image
        from prompt_builder import VideoSegment
        import video_assembler as va
        segs = []
        for k, (a, b) in enumerate([(0, 4.7), (4.7, 9.469)]):
            p = tmp_path / f"f{k}.jpg"
            Image.new("RGB", (320, 180), (80 * k, 60, 120)).save(p)
            segs.append(VideoSegment(a, b, "pexels", "q", media_type="image", override_source={"source": "local_file", "value": str(p), "kind": "image"}))
        segs[0].transition = "dp:gl_punch"
        out = va.assemble_video(segs, synthetic_audio, str(tmp_path / "o.mp4"), str(tmp_path / "w"),
                                site_cfg={"orientation": "16:9", "export_quality": "480p", "assembly_fetch_concurrency": 2},
                                sfx=[{"som": "pop/pop_4", "start": 1.0, "volume": 1}])
        assert abs(va._probe_duration(out) - 9.469) < 0.3
        assert os.path.exists(tmp_path / "w" / "_narracao_com_sons.wav")


class TestTextosAvulsos:
    @pytest.mark.parametrize("fundo", ["preto", "verde", "transparente_mov", "transparente_webm"])
    def test_renderiza_em_todos_os_fundos(self, tmp_path, fundo):
        out = dd.renderizar_avulso("glow_01", "Tudo estava conectado", 1.5, 640, 360, fundo, str(tmp_path / "t"), str(tmp_path / "w"))
        assert os.path.exists(out) and out.endswith(dd.FUNDOS_AVULSO[fundo][1])

    def test_avulso_nao_e_reancorado_nem_bloqueia_destaque(self):
        pal = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("um dois três quatro cinco seis".split())]
        out = dd.ancorar([{"estilo": "glow_01", "start": 0, "end": 2, "texto": "um dois"},
                          {"estilo": "capitulo", "start": 0.7, "end": 2.7, "texto": "OLÁ", "avulso": True}], pal, 4)
        av = [d for d in out if d.get("avulso")][0]
        assert (av["start"], av["end"]) == (0.7, 2.7) and len(out) == 2

    def test_zona_e_sem_fundo(self, tmp_path):
        d = {"estilo": "marca_azul", "start": 0, "end": 2, "texto": "x", "sem_fundo": True, "zona": "alto"}
        ent, etapas = dd.filtros_de_tratamento([d], 640, 360, str(tmp_path))
        assert etapas == []
        ass = open(dd.gerar_ass([d], 640, 360, str(tmp_path / "a.ass")), encoding="utf-8").read()
        assert "\\an8" in ass


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


class TestApp:
    def test_paginas_e_rotas(self, A):
        c = A.app.test_client()
        assert c.get("/sons/pop/pop_4.m4a").status_code == 200
        html = c.get("/textos").get_data(as_text=True)
        assert "Textos animados" in html and "transparente_mov" in html
        r = c.post("/textos/gerar", json={"estilo": "selo_ano", "texto": "1945", "duracao": 1.2, "qualidade": "720p", "fundo": "verde"})
        d = r.get_json()
        assert r.status_code == 200 and d["arquivo"].endswith(".mp4")
        assert c.get(d["url"]).status_code == 200
        assert c.post("/textos/gerar", json={"estilo": "x", "texto": "a"}).status_code == 400

    def test_estudio_salva_sons_e_textos(self, A):
        jid = "sons-salvar"
        os.makedirs(A._job_dir(jid), exist_ok=True)
        A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 6.0,
                        "pending_segments": [{"start": 0.0, "end": 3.0, "provider": "pexels", "query": "a"}, {"start": 3.0, "end": 6.0, "provider": "pexels", "query": "b"}],
                        "segment_previews": [{"index": 0, "ok": False}, {"index": 1, "ok": False}]}
        c = A.app.test_client()
        html = c.get(f"/job/{jid}/edit-segments?modo=estudio").get_data(as_text=True)
        assert 'id="tab-audios"' in html and 'id="tab-textos"' in html and "transicoes/film_burn_4" in html
        form = {"acao": "salvar", "seg_0_start": "0", "seg_0_end": "3", "seg_1_start": "3", "seg_1_end": "6", "seg_0_transition_som": "nenhum",
                "sfx_json": json.dumps([{"som": "pop/pop_4", "start": 1.2, "volume": 0.8}, {"som": "inexistente", "start": 1}]),
                "global_sons_enviados": "1", "global_sons_transicoes": "on", "global_sons_volume": "0.7",
                "destaques_json": json.dumps([{"estilo": "capitulo", "start": 1, "end": 3, "texto": "OI", "avulso": True, "zona": "alto", "sem_fundo": True, "som": "pop/pop_4"}])}
        r = c.post(f"/job/{jid}/confirm-segments", data=form, headers={"X-Requested-With": "fetch"})
        assert r.status_code == 200
        job = A._JOBS[jid]
        assert job["sfx"] == [{"id": job["sfx"][0]["id"], "som": "pop/pop_4", "start": 1.2, "volume": 0.8}]
        assert job["editor_defaults"]["sons_auto"] == {"transicoes": True, "cenas": False, "destaques": False, "editoriais": False}
        assert A._job_site_cfg(job)["sons_volume"] == 0.7
        assert job["pending_segments"][0]["transition_som"] == "nenhum"
        d = job["destaques"][0]
        assert d["avulso"] and d["zona"] == "alto" and d["sem_fundo"] and d["som"] == "pop/pop_4"
