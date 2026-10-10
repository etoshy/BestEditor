"""
Cenas e takes no estilo DarkPlanner (cenas_dp.py): catálogo vindo do
message.json, grupos de trechos (slots), render com ffmpeg, shutters como
transição, IA escolhendo template no JSON e o Estúdio aplicando.
"""
import json
import os
import subprocess

import pytest
from PIL import Image

import cenas_dp as c


def _clip(path, cor, dur=4.0, w=192, h=108):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={cor}:s={w}x{h}:r=30:d={dur}",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


def _dur(p):
    import video_assembler as va
    return va._probe_duration(p)


class TestCatalogo:
    def test_catalogo_sem_avatar_e_sem_shutter(self):
        cat = c.catalogo()
        assert len(cat) >= 140
        assert not any(k.startswith("tpl_avatar") for k in cat)
        assert not any(k.startswith("SHUTTER") for k in cat)
        assert c.template("MOLDURA_02")["slots"] == 1 and c.slots_do_template("MULTITAKE_04") == 3

    def test_todo_template_tem_layout_valido(self):
        for tid in c.catalogo():
            lay = c.layout(tid)
            assert lay["janelas"], tid
            for (x, y, w, h) in lay["janelas"]:
                assert 0 <= x and 0 <= y and x + w <= 1.0001 and y + h <= 1.0001, tid
            assert c.fundos_do_template(tid), tid

    def test_rotulo_de_fabrica_nao_aparece_mas_antes_depois_sim(self):
        campos = {f["key"]: f for f in c.campos_de_texto("tpl_editorial_left")}
        assert campos["TÓPICO"]["default"] == ""
        assert {f["key"]: f["default"] for f in c.campos_de_texto("MULTITAKE_03")} == {"ANTES": "ANTES", "DEPOIS": "DEPOIS"}

    def test_catalogo_pro_editor_e_pro_prompt(self):
        ed = c.catalogo_para_editor()
        assert {"id", "nome", "slots", "janelas", "fundos", "campos", "categoria"} <= set(ed[0])
        txt = c.bloco_para_prompt()
        assert "MOLDURA_02" in txt and "tpl_avatar" not in txt and "INTRO_DOC_0" not in txt  # manual fica fora da IA


class TestGrupos:
    def test_template_de_2_slots_cobre_o_proximo_trecho(self):
        assert c.planejar_grupos([None, "MULTITAKE_06", None, None]) == [(0, 0, None), (1, 2, "MULTITAKE_06"), (3, 3, None)]

    def test_corta_no_fim_e_nao_engole_outra_cena(self):
        assert c.planejar_grupos(["MULTITAKE_04", None, "MOLDURA_02"]) == [(0, 1, "MULTITAKE_04"), (2, 2, "MOLDURA_02")]
        assert c.planejar_grupos([None, "C50_GRID_CATAVENTO"]) == [(0, 0, None), (1, 1, "C50_GRID_CATAVENTO")]

    def test_id_desconhecido_vira_trecho_normal(self):
        assert c.planejar_grupos(["NAO_EXISTE"]) == [(0, 0, None)]


class TestRender:
    @pytest.mark.parametrize("tid", sorted({v: k for k, v in {tid: c.layout(tid)["arranjo"] for tid in c.catalogo()}.items()}.values()))
    def test_cada_arranjo_renderiza_com_a_duracao_certa(self, tid, tmp_path):
        n = min(c.slots_do_template(tid), 6)
        cores = ["red", "green", "blue", "orange", "purple", "white"]
        clips = [_clip(tmp_path / f"c{k}.mp4", cores[k], 4.0 - k * 0.5) for k in range(n)]
        out = c.renderizar_cena(tid, clips, [k * 0.5 for k in range(n)], 4.0, str(tmp_path / "o.mp4"), 192, 108, str(tmp_path / "w"),
                                campos={"TÓPICO": "Gelo", "CAPÍTULO": "Parte 1"}, falas=["a expedição saiu do porto"] * n)
        assert abs(_dur(out) - 4.0) < 0.1

    def test_take_entra_no_proprio_tempo(self, tmp_path):
        clips = [_clip(tmp_path / "r.mp4", "red", 4), _clip(tmp_path / "b.mp4", "blue", 2)]
        out = c.renderizar_cena("MULTITAKE_06", clips, [0.0, 2.0], 4.0, str(tmp_path / "o.mp4"), 320, 180, str(tmp_path / "w"))

        def cor(t):
            png = tmp_path / f"f{t}.png"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", out, "-frames:v", "1", str(png)], check=True)
            return Image.open(png).convert("RGB").getpixel((int(320 * 0.73), int(180 * 0.44)))  # meio da janela da direita
        antes, depois = cor(1.0), cor(3.5)
        assert antes[2] < 120  # janela 2 ainda vazia (fundo escuro)
        assert depois[2] > 180 and depois[0] < 90  # take azul entrou

    def test_fundo_papel_gerado(self, tmp_path):
        p = c.gerar_fundo("papel", 160, 90, str(tmp_path))
        r, g, b = Image.open(p).convert("RGB").getpixel((80, 45))
        assert r > 180 and g > 170


class TestShutters:
    def test_shutters_viram_transicoes_validas(self):
        import site_config
        import video_assembler as va
        for valor, _r, _d in c.SHUTTERS.values():
            assert valor in va.TRANSICOES_VALIDAS and valor in site_config.VALID_TRANSITION_TYPES
        assert "dp_shutter" in dict(site_config.TRANSITION_LABELS)

    @pytest.mark.parametrize("tipo", ["blinds_h", "dp_shutter", "dp_shutter_foco", "wave_wipe"])
    def test_transicao_custom_vai_de_a_pra_b(self, tipo, tmp_path):
        """Bug antigo: o P do xfade custom vai de 1 a 0 — as transições
        próprias começavam mostrando o PRÓXIMO trecho e voltavam pro anterior."""
        import video_assembler as va
        out = tmp_path / "o.raw"
        expr = va.expressao_xfade_custom(tipo)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=64x64:d=2:r=10", "-f", "lavfi",
                        "-i", "color=blue:s=64x64:d=2:r=10", "-filter_complex",
                        f"[0][1]xfade=transition=custom:duration=1:offset=0.5:expr='{expr}'", "-f", "rawvideo", "-pix_fmt", "rgb24", str(out)], check=True)
        d = out.read_bytes()
        n = 64 * 64 * 3

        def media(f, canal):
            return sum(d[f * n:(f + 1) * n][canal::3]) / 4096
        assert media(6, 0) > media(6, 2)  # começo da transição: ainda vermelho
        assert media(14, 2) > media(14, 0)  # fim: já azul


class TestIA:
    def test_json_da_ia_com_template(self):
        from prompt_builder import parse_ai_response
        r = parse_ai_response(json.dumps({"segments": [
            {"start": 0, "end": 3, "provider": "pexels", "query": "a", "template": "tpl_editorial_left", "template_campos": {"TÓPICO": "GELO" * 20, "lixo": "x"}},
            {"start": 3, "end": 6, "provider": "pexels", "query": "b", "template": "NAO_EXISTE"},
            {"start": 6, "end": 9, "provider": "pexels", "query": "c", "template": "tpl_avatar_circulo"},
        ]}))
        s0, s1, s2 = r.segments
        assert s0.template == "tpl_editorial_left" and set(s0.template_campos) == {"TÓPICO"} and len(s0.template_campos["TÓPICO"]) <= 24
        assert s1.template is None and s2.template is None
        assert s0.to_dict()["template"] == "tpl_editorial_left" and "template" not in s1.to_dict()

    def test_prompt_com_e_sem_templates(self):
        from prompt_builder import build_prompt
        segs = [{"start": 0, "end": 5, "text": "oi"}]
        com = build_prompt(segs, providers=["pexels"], usar_templates=True)
        sem = build_prompt(segs, providers=["pexels"])
        assert "CENAS E TAKES" in com and "MOLDURA_02" in com and "template_campos" in com
        assert "CENAS E TAKES" not in sem


class TestMontagem:
    def test_montagem_com_cena_de_2_takes_mantem_a_sincronia(self, tmp_path, synthetic_audio):
        from prompt_builder import VideoSegment
        import video_assembler as va
        fotos = []
        for k, cor in enumerate([(200, 30, 30), (30, 200, 30), (30, 30, 200), (200, 200, 30)]):
            p = tmp_path / f"f{k}.jpg"
            Image.new("RGB", (320, 180), cor).save(p)
            fotos.append(str(p))
        bordas = [0, 2.5, 5.0, 7.2, 9.469]
        segs = [VideoSegment(bordas[k], bordas[k + 1], "pexels", f"q{k}", media_type="image",
                             override_source={"source": "local_file", "value": fotos[k], "kind": "image"}) for k in range(4)]
        segs[1].template = "MULTITAKE_06"
        segs[1].template_campos = {"_fundo": "concreto"} if "concreto" in c.fundos_do_template("MULTITAKE_06") else None
        segs[0].transition = "fade"
        segs[3 - 1].transition = "dp_shutter"  # emenda DENTRO da cena: ignorada
        out = va.assemble_video(segs, synthetic_audio, str(tmp_path / "o.mp4"), str(tmp_path / "w"),
                                site_cfg={"orientation": "16:9", "export_quality": "480p", "assembly_fetch_concurrency": 2},
                                falas_por_trecho=["um", "dois três", "quatro", "cinco"])
        assert abs(va._probe_duration(out) - 9.469) < 0.3
        assert os.path.exists(tmp_path / "w" / "clips" / "cena_0001.mp4")


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def _job(A, jid, n=3):
    os.makedirs(A._job_dir(jid), exist_ok=True)
    A._JOBS[jid] = {
        "job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 3.0 * n,
        "pending_segments": [{"start": 3.0 * k, "end": 3.0 * (k + 1), "provider": "pexels", "query": f"q{k}", "media_type": "video"} for k in range(n)],
        "segment_previews": [{"index": k, "ok": False} for k in range(n)],
        "segments": [{"start": 0.0, "end": 9.0, "text": "a expedição saiu do porto e nunca voltou"}],
        "word_timestamps": [{"word": w, "start": k * 1.0, "end": k * 1.0 + 0.8} for k, w in enumerate("a expedição saiu do porto e nunca voltou".split())],
    }
    return A._JOBS[jid]


class TestApp:
    def test_estudio_tem_aba_cenas_e_catalogo(self, A):
        _job(A, "cn-pagina")
        html = A.app.test_client().get("/job/cn-pagina/edit-segments?modo=estudio").get_data(as_text=True)
        assert 'id="tab-cenas"' in html and "MOLDURA_02" in html and "aplicarCena" in html

    def test_salvar_template_pelo_estudio_e_manter_no_classico(self, A):
        job = _job(A, "cn-salvar")
        cli = A.app.test_client()
        form = {"acao": "salvar", "seg_1_template": "MULTITAKE_06",
                "seg_1_template_campos": json.dumps({"_fala": False, "_fundo": "xx", "lixo": 1})}
        for k in range(3):
            form[f"seg_{k}_start"] = str(3.0 * k)
            form[f"seg_{k}_end"] = str(3.0 * (k + 1))
        r = cli.post("/job/cn-salvar/confirm-segments", data=form, headers={"X-Requested-With": "fetch"})
        assert r.status_code == 200
        s1 = job["pending_segments"][1]
        assert s1["template"] == "MULTITAKE_06" and s1["template_campos"] == {"_fala": False}
        # editor clássico não manda o campo -> mantém
        form2 = {k: v for k, v in form.items() if "template" not in k}
        cli.post("/job/cn-salvar/confirm-segments", data=form2, headers={"X-Requested-With": "fetch"})
        assert job["pending_segments"][1]["template"] == "MULTITAKE_06"
        # vazio no Estúdio -> tira
        form["seg_1_template"] = ""
        cli.post("/job/cn-salvar/confirm-segments", data=form, headers={"X-Requested-With": "fetch"})
        assert "template" not in job["pending_segments"][1]

    def test_fala_de_cada_trecho_e_legenda_coberta(self, A):
        from prompt_builder import VideoSegment
        job = _job(A, "cn-fala")
        segs = [VideoSegment(3.0 * k, 3.0 * (k + 1), "pexels", "q") for k in range(3)]
        falas, palavras = A._falas_por_trecho(job, segs)
        assert falas[0] == "a expedição saiu" and falas[1] == "do porto e" and len(palavras[2]) == 2
        segs[0].template = "tpl_editorial_left"
        assert A._janelas_que_cobrem_legenda(segs) == [(0.0, 3.0)]
        segs[0].template_campos = {"_fala": False}
        assert A._janelas_que_cobrem_legenda(segs) == []

    def test_dividir_nao_duplica_a_cena(self, A):
        job = _job(A, "cn-div")
        job["pending_segments"][0]["template"] = "MOLDURA_02"
        A.app.test_client().post("/job/cn-div/editor/dividir", json={"indice": 0, "tempo": 1.5})
        assert job["pending_segments"][0]["template"] == "MOLDURA_02" and "template" not in job["pending_segments"][1]
