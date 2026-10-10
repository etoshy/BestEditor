"""
Cores do projeto (colorSystem do DarkPlanner) e legendas do Estúdio (do .srt
do zip ou do Whisper, estilos de bloco e karaokê, regras sob templates/destaques).
"""
import json
import os
import subprocess

import pytest
from PIL import Image

import dp_cores as dc
import dp_legendas as dl

AZUL = {"primaria": "#3E8EFF", "secundaria": "#BFD9FF", "acento": "#0E2F66", "modo": "projeto"}


class TestCores:
    def test_padrao_do_json_e_tons(self):
        p = dc.padrao()
        assert (p["primaria"], p["secundaria"], p["acento"]) == ("#FFD60A", "#FF9A1F", "#4DC3FF")
        t = dc.tons_da_paleta("#3E8EFF")
        assert set(t) >= {"claro", "vivo", "medio", "escuro"}
        assert sum(dc.rgb(t["claro"])) > sum(dc.rgb(t["medio"])) > sum(dc.rgb(t["escuro"]))

    def test_neutra_e_normalizar(self):
        assert dc.neutra("#808080") and not dc.neutra("#3E8EFF")
        n = dc.normalizar({"primaria": "#abcdef", "modo": "auto", "escopo": {"cenas": False}, "lixo": 1})
        assert n["primaria"] == "#ABCDEF" and n["modo"] == "auto" and n["escopo"]["cenas"] is False and n["escopo"]["textos"] is True
        assert not dc.vale_para(n, "textos")  # automático: cada estilo com as cores dele
        assert dc.vale_para(AZUL, "cenas") and not dc.vale_para(dict(AZUL, escopo={"cenas": False}), "cenas")

    def test_paletas_prontas(self):
        assert len(dc.PALETAS) >= 10 and all(p["primaria"].startswith("#") for p in dc.PALETAS)

    def test_fundo_da_cena_tinge_com_a_paleta(self, tmp_path):
        import cenas_dp
        a = Image.open(cenas_dp.gerar_fundo("cor3", 160, 90, str(tmp_path))).getpixel((80, 45))
        b = Image.open(cenas_dp.gerar_fundo("cor3", 160, 90, str(tmp_path), tom="#3E8EFF")).getpixel((80, 45))
        assert a != b and b[2] > b[0]  # azul domina

    def test_cena_com_paleta_renderiza(self, tmp_path):
        import cenas_dp
        clip = tmp_path / "c.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=30:d=2", "-pix_fmt", "yuv420p", str(clip)], check=True)
        out = cenas_dp.renderizar_cena("tpl_editorial_left", [str(clip)], [0.0], 2.0, str(tmp_path / "o.mp4"), 320, 180, str(tmp_path / "w"),
                                       campos={"TÓPICO": "GELO"}, paleta=AZUL)
        assert os.path.exists(out)

    def test_transicao_de_luz_muda_de_cor(self):
        import dp_visual
        assert dp_visual.resolver_transicao("dp:ft_pk_leak1", AZUL)[1] != dp_visual.resolver_transicao("dp:ft_pk_leak1")[1]
        assert dp_visual.resolver_transicao("dp:ft_pk_leak1", dict(AZUL, modo="auto"))[1] == dp_visual.resolver_transicao("dp:ft_pk_leak1")[1]
        assert dp_visual.resolver_transicao("dp:fade", AZUL) == ("nativa", "fade")


BLOCOS = [{"start": 0.0, "end": 2.0, "text": "a palavra ativa vem agora"}, {"start": 2.2, "end": 4.0, "text": "e tudo mudou"}]


class TestLegendas:
    def test_palavras_do_srt_proporcionais(self):
        ws = dl.palavras_dos_blocos(BLOCOS)
        assert [w["word"] for w in ws][:3] == ["a", "palavra", "ativa"]
        assert (ws[1]["end"] - ws[1]["start"]) > (ws[0]["end"] - ws[0]["start"])  # palavra maior = mais tempo
        assert abs(ws[4]["end"] - 2.0) < 0.01 and ws[5]["start"] == 2.2

    def test_agrupar_respeita_bloco_e_limite(self):
        g = dl.agrupar(dl.palavras_dos_blocos(BLOCOS), 3)
        assert [len(x) for x in g] == [3, 2, 3]

    @pytest.mark.parametrize("estilo", [e["id"] for e in dl.ESTILOS])
    def test_todos_os_estilos_renderizam(self, tmp_path, estilo):
        ass = dl.gerar_ass(dl.palavras_dos_blocos(BLOCOS), {"ativa": True, "estilo": estilo}, 640, 360, str(tmp_path / "l.ass"), AZUL)
        txt = open(ass, encoding="utf-8").read()
        assert "Dialogue:" in txt
        if estilo == "preenchimento":
            assert "\\kf" in txt
        if estilo == "destaque":
            assert "\\p1" in txt and "FF8E3E" in txt.upper()  # caixa na cor da paleta (BGR)
        base = tmp_path / "b.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=4.2", "-f", "lavfi", "-i", "sine=d=4.2",
                        "-pix_fmt", "yuv420p", "-shortest", str(base)], check=True)
        out = dl.queimar(str(base), ass, str(tmp_path / "o.mp4"))
        assert os.path.exists(out)

    def test_regras_sob_templates_e_destaques(self):
        cfg = dl.normalizar({"sob_templates": "auto", "sob_destaques": "auto"})
        grupos = [(0, 3, True, None), (3, 6, False, None), (6, 9, False, "ocultar"), (9, 12, True, "manter")]
        dest = [{"estilo": "glow_01", "start": 12, "end": 13}, {"estilo": "selo_ano", "start": 13, "end": 14},
                {"estilo": "selo_ano", "start": 14, "end": 15, "legenda": "ocultar"}, {"estilo": "glow_01", "start": 15, "end": 16, "avulso": True}]
        assert dl.janelas_ocultas(cfg, grupos, dest) == [(0, 3), (6, 9), (12.0, 13.0), (14.0, 15.0)]
        assert dl.janelas_ocultas(dl.normalizar({"sob_templates": "manter", "sob_destaques": "manter"}), grupos, dest) == [(6, 9), (14.0, 15.0)]
        tudo = dl.janelas_ocultas(dl.normalizar({"sob_templates": "ocultar", "sob_destaques": "ocultar"}), grupos, dest)
        assert (3, 6) in tudo and (13.0, 14.0) in tudo and (9, 12) not in tudo


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


class TestApp:
    def test_salvar_paleta_e_legendas_e_queimar(self, A, tmp_path):
        jid = "leg-app"
        os.makedirs(A._job_dir(jid), exist_ok=True)
        A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 4.0,
                        "pending_segments": [{"start": 0.0, "end": 2.0, "provider": "pexels", "query": "a"}, {"start": 2.0, "end": 4.0, "provider": "pexels", "query": "b"}],
                        "segment_previews": [{"index": 0, "ok": False}, {"index": 1, "ok": False}], "segments": BLOCOS}
        c = A.app.test_client()
        html = c.get(f"/job/{jid}/edit-segments?modo=estudio").get_data(as_text=True)
        assert 'id="tab-legendas"' in html and "investigacao" in html and "Preenchimento" in html
        form = {"acao": "salvar", "seg_0_start": "0", "seg_0_end": "2", "seg_1_start": "2", "seg_1_end": "4",
                "seg_0_template": "tpl_editorial_left", "seg_0_template_campos": json.dumps({"_legenda": "manter"}),
                "destaques_json": "[]", "paleta_json": json.dumps(AZUL), "legendas_json": json.dumps({"ativa": True, "estilo": "pop", "posicao": "topo"})}
        assert c.post(f"/job/{jid}/confirm-segments", data=form, headers={"X-Requested-With": "fetch"}).status_code == 200
        job = A._JOBS[jid]
        assert job["legendas"]["estilo"] == "pop" and job["legendas"]["posicao"] == "topo"
        assert job["editor_defaults"]["paleta"]["primaria"] == "#3E8EFF" and A._job_site_cfg(job)["paleta"]["primaria"] == "#3E8EFF"
        assert job["pending_segments"][0]["template_campos"] == {"_legenda": "manter"}
        # queima: gera o _legendado.mp4
        video = tmp_path / "v.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=4", "-f", "lavfi", "-i", "sine=d=4",
                        "-pix_fmt", "yuv420p", "-shortest", str(video)], check=True)
        from prompt_builder import VideoSegment
        segs = [VideoSegment(**{k: v for k, v in s.items() if k in ("start", "end", "provider", "query", "template", "template_campos")}) for s in job["pending_segments"]]
        A._gerar_legendas_dp(jid, job, segs, str(video), [])
        assert os.path.exists(job["captioned_output_path"])
        os.remove(job["captioned_output_path"])
