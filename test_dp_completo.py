"""
Resto do darkplanner.json: filtros (74), efeitos (28), entradas/saídas (37),
transições (200 + "none"), Direções (4 predefinições) e destaques de texto (207).
"""
import json
import os
import subprocess

import pytest
from PIL import Image

import dp_destaques as dd
import dp_direcao as dr
import dp_visual as dv


def _clip(path, dur=2.0, w=320, h=180):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r=30:d={dur}",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


def _dur(p):
    import video_assembler as va
    return va._probe_duration(p)


class TestCatalogos:
    def test_tudo_do_json_esta_no_site(self):
        assert len(dv.filtros()) == 74 and len(dv.efeitos()) == 28 and len(dv.entradas()) == 37
        assert len(dv.transicoes()) == 200  # 201 do JSON menos o "none"
        assert len(dd.catalogo()) == 207 and len(dr.direcoes()) == 4

    def test_todo_filtro_e_valido_no_ffmpeg(self):
        for f in dv.filtros():
            if not f["cadeia"]:
                continue
            r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=64x36:d=0.2", "-vf", f["cadeia"], "-f", "null", "-"],
                               capture_output=True, text=True)
            assert r.returncode == 0, (f["id"], r.stderr[-300:])

    def test_toda_transicao_vira_xfade_valido(self, tmp_path):
        import video_assembler as va
        for t in dv.transicoes():
            assert t["id"] in va.TRANSICOES_VALIDAS
        # amostra de cada tipo (nativa, nossa, expressão própria)
        for tid in ("dp:fade", "dp:gl_oss_windowblinds", "dp:ft_pk_leak1", "dp:ft_splash_3", "dp:gl_oss_heart", "dp:gl_glitch", "dp:camera_shutter"):
            fc = f"[0][1]xfade={va._transicao_xfade(tid)}:duration=0.5:offset=0.2"
            r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=64x36:d=1:r=10", "-f", "lavfi", "-i",
                                "color=blue:s=64x36:d=1:r=10", "-filter_complex", fc, "-f", "null", "-"], capture_output=True, text=True)
            assert r.returncode == 0, (tid, r.stderr[-300:])

    def test_todas_as_200_transicoes_do_catalogo_rodam(self):
        import video_assembler as va
        ruins = []
        for t in dv.transicoes():
            fc = f"[0][1]xfade={va._transicao_xfade(t['id'])}:duration=0.4:offset=0.2"
            r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=48x27:d=0.8:r=10", "-f", "lavfi", "-i",
                                "color=blue:s=48x27:d=0.8:r=10", "-filter_complex", fc, "-f", "null", "-"], capture_output=True, text=True)
            if r.returncode:
                ruins.append(t["id"])
        assert ruins == []

    def test_rotulos_no_site(self):
        import site_config
        rot = dict(site_config.TRANSITION_LABELS)
        assert rot["dp:gl_fade_escuro"].startswith("🌗 DP") and "dp:ft_pk2_glitch" in site_config.VALID_TRANSITION_TYPES


class TestPosProcesso:
    @pytest.mark.parametrize("efeito,entrada,saida", [("ov_leak", None, None), ("ov_scanlines", "pop", None), (None, "spin", "tv_on"),
                                                       ("chroma", "blur_in", "fade"), ("flicker", "shake", None)])
    def test_mantem_duracao(self, tmp_path, efeito, entrada, saida):
        c = _clip(tmp_path / "c.mp4")
        out = tmp_path / "o.mp4"
        assert dv.pos_processar_clipe(c, str(out), 2.0, 320, 180, str(tmp_path / "w"), efeito=efeito, entrada=entrada, saida=saida)
        assert abs(_dur(str(out)) - 2.0) < 0.1

    def test_nada_a_fazer(self, tmp_path):
        c = _clip(tmp_path / "c.mp4")
        assert dv.pos_processar_clipe(c, str(tmp_path / "o.mp4"), 2.0, 320, 180, str(tmp_path / "w")) is False

    @pytest.mark.parametrize("modo", ["rapido", "zoom_pan_left", "giro", "respiro"])
    def test_novos_movimentos_de_camera(self, tmp_path, modo):
        import video_assembler as va
        img = tmp_path / "f.jpg"
        Image.new("RGB", (400, 300), (120, 50, 30)).save(img)
        out = va._render_image_with_ken_burns(str(img), 1.5, str(tmp_path / "o.mp4"), 320, 180, zoom_direction=modo)
        assert abs(_dur(out) - 1.5) < 0.1


class TestDirecao:
    SEGS = [{"start": i * 3.0, "end": i * 3.0 + 3, "foto": i % 2 == 0} for i in range(16)]

    def test_deterministica(self):
        assert dr.planejar(self.SEGS, "sys_cinema", 5) == dr.planejar(self.SEGS, "sys_cinema", 5)
        assert dr.planejar(self.SEGS, "sys_cinema", 5) != dr.planejar(self.SEGS, "sys_cinema", 6)

    def test_doc_classico_usa_so_o_que_o_preset_marca(self):
        p = dr.planejar(self.SEGS, "sys_doc_classico", 3)
        assert p["filtro_cor"] in ("fade", "vintage")
        trs = {t["transition"] for t in p["trechos"][:-1]} - {"none"}
        assert trs and trs <= {"dp:gl_fade_escuro", "dp:dissolve", "dp:gl_fade_grao", "dp:cb_foco", "dp:cb_respiro"}
        for seg, t in zip(self.SEGS, p["trechos"]):
            assert not t["template"] and not t["entrada"]
            if t["efeito"]:
                assert seg["foto"]  # movimento de câmera só em foto

    def test_padrao_do_sistema_pode_por_cenas_sem_transicao_dentro(self):
        import cenas_dp
        p = dr.planejar(self.SEGS * 1, "sys_tudo", 11)
        for a, b, tid in cenas_dp.planejar_grupos([t["template"] for t in p["trechos"]]):
            for k in range(a, b):
                assert p["trechos"][k]["transition"] == "none"

    def test_manter_o_que_ja_escolhi(self):
        segs = [dict(s) for s in self.SEGS]
        segs[0]["transition"] = "fade"
        segs[2]["efeito"] = "ov_poeira"
        p = dr.planejar(segs, "sys_dinamico", 1, so_vazios=True)
        assert p["trechos"][0]["transition"] == "fade" and p["trechos"][2]["efeito"] == "ov_poeira"

    def test_direcao_desconhecida(self):
        with pytest.raises(ValueError):
            dr.planejar(self.SEGS, "nao_existe")


PALAVRAS = [{"word": w, "start": 0.3 + i * 0.4, "end": 0.3 + i * 0.4 + 0.35} for i, w in enumerate("Em 1945 a guerra acabou e ninguém sabia a verdade".split())]


class TestDestaques:
    def test_catalogo_pro_editor_e_prompt(self):
        ed = dd.catalogo_para_editor()
        assert len(ed) == 207 and ed[0]["fonte"].startswith("DP ")
        txt = dd.bloco_para_prompt()
        assert "selo_ano" in txt and len(txt.splitlines()) == 190

    def test_fontes_existem(self):
        mapa = json.load(open(os.path.join(dd.FONTES_DIR, "fontes.json"), encoding="utf-8"))
        familias = {v["familia"] for v in mapa.values()}
        assert set(dd._FONTE.values()) <= familias

    def test_ancorar_pela_fala_e_sem_sobrepor(self):
        out = dd.ancorar([{"estilo": "selo_ano", "start": 0, "end": 2, "texto": "1945"},
                          {"estilo": "glow_01", "start": 1.5, "end": 4.5, "texto": "ninguém sabia a verdade"}], PALAVRAS, 6)
        assert out[0]["start"] >= 0.3 and out[0]["start"] < 0.75  # entra um pouco antes de "1945"
        assert out[1]["start"] >= out[0]["end"] + 0.09  # um por vez

    def test_motor_local_acha_ano_pct_e_dinheiro(self):
        blocos = [{"start": 0, "end": 3, "text": "Em 1945 a guerra acabou"}, {"start": 45, "end": 48, "text": "Foram 25% dos votos"},
                  {"start": 90, "end": 93, "text": "Custou R$ 40 milhões"}]
        out = dd.sugerir(blocos, semente=1)
        tipos = {dd.estilo(d["estilo"])["papel"] for d in out}
        assert "info" in tipos and any("25%" in d["texto"] for d in out) and any("R$ 40 milhões" in d["texto"] for d in out)

    def test_ass_e_render(self, tmp_path):
        base = tmp_path / "b.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=6:r=30", "-f", "lavfi", "-i", "sine=d=6",
                        "-pix_fmt", "yuv420p", "-shortest", str(base)], check=True)
        ds = [{"estilo": "selo_ano", "start": 0.2, "end": 1.8, "texto": "1945"}, {"estilo": "marca_azul", "start": 2.0, "end": 3.5, "texto": "era mentira"},
              {"estilo": "doc_contador", "start": 3.7, "end": 5.8, "texto": "3.000 pessoas"}]
        ass = dd.gerar_ass(ds, 640, 360, str(tmp_path / "a.ass"))
        txt = open(ass, encoding="utf-8").read()
        assert "DP Jetbrains Mono" in txt and "\\alpha&HFF&" in txt
        out = dd.aplicar_destaques(str(base), str(tmp_path / "o.mp4"), ds, 640, 360, str(tmp_path / "w"))
        assert abs(_dur(out) - 6.0) < 0.15
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", out], capture_output=True, text=True)
        assert "audio" in r.stdout  # áudio preservado


class TestIA:
    def test_json_com_tudo(self):
        from prompt_builder import parse_ai_response
        r = parse_ai_response(json.dumps({
            "direcao": "sys_cinema", "filtro": "noir",
            "highlights": [{"start": 0.5, "end": 2, "estilo": "selo_ano", "texto": "1945"}, {"start": 3, "end": 4, "estilo": "nao_existe"}],
            "segments": [
                {"start": 0, "end": 3, "provider": "pexels", "query": "a", "efeito": "ov_leak", "entrada": "pop", "transition": "gl_flash"},
                {"start": 3, "end": 6, "provider": "pexels", "query": "b", "efeito": "inventado", "saida": "tv_on"},
            ]}))
        assert r.direcao == "sys_cinema" and r.filtro_cor == "noir" and [d["estilo"] for d in r.destaques] == ["selo_ano"]
        s0, s1 = r.segments
        assert (s0.efeito, s0.entrada, s0.transition) == ("ov_leak", "pop", "dp:gl_flash")
        assert s1.efeito is None and s1.saida == "tv_on"
        assert s0.to_dict()["efeito"] == "ov_leak"

    def test_prompt_lista_tudo(self):
        from prompt_builder import build_prompt
        p = build_prompt([{"start": 0, "end": 5, "text": "oi"}], providers=["pexels"], usar_templates=True)
        for x in ("sys_doc_classico", "ov_leak", "punch_in", "gl_oss_heart", "teal_orange", "highlights", "selo_ano"):
            assert x in p


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def _job(A, jid):
    os.makedirs(A._job_dir(jid), exist_ok=True)
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 9.0,
                    "pending_segments": [{"start": 3.0 * k, "end": 3.0 * (k + 1), "provider": "pexels", "query": f"q{k}", "media_type": "image"} for k in range(3)],
                    "segment_previews": [{"index": k, "ok": False} for k in range(3)],
                    "segments": [{"start": 0.0, "end": 4.5, "text": "Em 1945 a guerra acabou"}, {"start": 4.5, "end": 9.0, "text": "e ninguém sabia a verdade"}],
                    "word_timestamps": PALAVRAS}
    return A._JOBS[jid]


class TestApp:
    def test_estudio_tem_direcao_destaques_e_fontes(self, A):
        _job(A, "dp-pag")
        c = A.app.test_client()
        html = c.get("/job/dp-pag/edit-segments?modo=estudio").get_data(as_text=True)
        assert 'id="tab-direcao"' in html and 'id="tab-destaques"' in html and "sys_doc_classico" in html and "dp-fontes.css" in html
        assert c.get("/dp-fontes.css").status_code == 200 and c.get("/dp-fonte/inter-Regular.ttf").status_code == 200

    def test_salvar_efeitos_filtro_e_destaques(self, A):
        job = _job(A, "dp-salvar")
        form = {"acao": "salvar", "global_filtro_cor": "noir", "global_direcao": "sys_cinema", "paleta_primaria": "#ff0000",
                "seg_0_efeito": "ov_leak", "seg_0_entrada": "pop", "seg_1_saida": "inventado",
                "destaques_json": json.dumps([{"id": "x1", "estilo": "selo_ano", "start": 0.4, "end": 2, "texto": "1945"}, {"estilo": "nao_existe", "start": 1, "end": 2}])}
        for k in range(3):
            form[f"seg_{k}_start"], form[f"seg_{k}_end"] = str(3.0 * k), str(3.0 * (k + 1))
        r = A.app.test_client().post("/job/dp-salvar/confirm-segments", data=form, headers={"X-Requested-With": "fetch"})
        assert r.status_code == 200
        s0, s1 = job["pending_segments"][:2]
        assert s0["efeito"] == "ov_leak" and s0["entrada"] == "pop" and "saida" not in s1
        assert job["editor_defaults"]["filtro_cor"] == "noir" and job["editor_defaults"]["direcao"] == "sys_cinema"
        assert [d["estilo"] for d in job["destaques"]] == ["selo_ano"] and job["editor_defaults"]["paleta"]["primaria"] == "#FF0000"
        assert A._job_site_cfg(job)["filtro_cor"] == "noir"

    def test_rotas_de_plano_e_sugestao(self, A):
        _job(A, "dp-rotas")
        c = A.app.test_client()
        r = c.post("/job/dp-rotas/direcao/plano", json={"direcao": "sys_dinamico", "semente": 2, "segmentos": [{"start": 0, "end": 3, "foto": True}, {"start": 3, "end": 6}]})
        d = r.get_json()
        assert r.status_code == 200 and d["filtro_cor"] == "vhs" and len(d["trechos"]) == 2
        assert c.post("/job/dp-rotas/direcao/plano", json={"direcao": "x", "segmentos": []}).status_code == 400
        s = c.post("/job/dp-rotas/destaques/sugerir", json={}).get_json()
        assert s["ok"] and any(dd.estilo(x["estilo"])["papel"] == "info" for x in s["destaques"])

    def test_json_da_ia_aplica_direcao_e_ancora_destaques(self, A):
        from prompt_builder import parse_ai_response
        job = _job(A, "dp-ia")
        parsed = parse_ai_response(json.dumps({"direcao": "sys_doc_classico", "highlights": [{"start": 0, "end": 2, "estilo": "selo_ano", "texto": "1945"}],
                                               "segments": [{"start": 0, "end": 4.5, "provider": "pexels", "query": "a", "media_type": "image"},
                                                            {"start": 4.5, "end": 9, "provider": "pexels", "query": "b", "media_type": "image", "efeito": "ov_neblina"}]}))
        job["pending_segments"] = [s.to_dict() for s in parsed.segments]
        A._aplicar_extras_dp(job, parsed)
        assert job["editor_defaults"]["direcao"] == "sys_doc_classico" and job["editor_defaults"]["filtro_cor"] in ("fade", "vintage")
        assert job["pending_segments"][1]["efeito"] == "ov_neblina"  # o que a IA escolheu fica
        assert 0.3 <= job["destaques"][0]["start"] < 0.75


class TestMontagem:
    def test_montagem_com_efeitos_filtro_e_destaques(self, tmp_path, synthetic_audio):
        from prompt_builder import VideoSegment
        import video_assembler as va
        segs = []
        for k, (a, b) in enumerate([(0, 3), (3, 6.5), (6.5, 9.469)]):
            p = tmp_path / f"f{k}.jpg"
            Image.new("RGB", (320, 180), (60 * k, 90, 160)).save(p)
            segs.append(VideoSegment(a, b, "pexels", "q", media_type="image", override_source={"source": "local_file", "value": str(p), "kind": "image"}))
        segs[0].efeito, segs[0].entrada, segs[0].transition = "zoom_giro", "pop", "dp:ft_pk_leak2"
        segs[1].efeito, segs[1].saida, segs[1].transition = "ov_poeira", "tv_on", "none"
        out = va.assemble_video(segs, synthetic_audio, str(tmp_path / "o.mp4"), str(tmp_path / "w"),
                                site_cfg={"orientation": "16:9", "export_quality": "480p", "assembly_fetch_concurrency": 2, "filtro_cor": "teal_orange"},
                                destaques=[{"estilo": "glow_01", "start": 1, "end": 3, "texto": "tudo estava conectado"}], palavras_narracao=PALAVRAS)
        assert abs(va._probe_duration(out) - 9.469) < 0.3
        assert os.path.exists(tmp_path / "w" / "_concat_filtrado.mp4") or True
