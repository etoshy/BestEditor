"""v76: prompt de edição (2ª etapa com a IA) e gráficos animados com os dados."""
import json
import os
import subprocess

import pytest

import dp_graficos as dg
import prompt_edicao as pe


class TestGraficos:
    def test_normalizar_e_formatar(self):
        g = dg.normalizar({"tipo": "barras", "dados": [["1950", "52 milhões"], {"rotulo": "2022", "valor": "203"}], "start": 1, "end": 2})
        assert [d["valor"] for d in g["dados"]] == [52.0, 203.0] and g["end"] - g["start"] >= 1.5
        assert dg.normalizar({"tipo": "barras", "dados": [["a", 1]]}) is None
        assert dg.normalizar({"tipo": "numero", "dados": [["x", "1.234,5"]], "start": 0, "end": 3})["dados"][0]["valor"] == 1234.5
        assert dg._num("3.400.000") == 3400000 and dg._num("30%") == 30 and dg._num("R$ 2,5") == 2.5
        assert dg.formatar(877, "US$ bi") == "US$ 877 bi" and dg.formatar(12.5, "%") == "12,5%" and dg.formatar(3400000) == "3.400.000"

    @pytest.mark.parametrize("tipo", list(dg.TIPOS))
    def test_todos_os_tipos_desenham(self, tipo, tmp_path):
        g = dg.normalizar({"tipo": tipo, "titulo": "T", "dados": [["a", 30], ["b", 70], ["c", 50]], "unidade": "%", "start": 0, "end": 4, "destaque": 1})
        for t in (0.0, 0.5, 2.0, 3.9):
            im, (x, y) = dg.desenhar(g, t, 640, 360)
            assert im.size[0] > 50
        p = dg.previa_png(g, 640, 360, str(tmp_path / "p.png"))
        assert os.path.getsize(p) > 1000

    def test_entra_no_tempo_certo(self, tmp_path):
        base = str(tmp_path / "b.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x0000FF:s=320x180:r=30:d=6", "-pix_fmt", "yuv420p", base], check=True)
        out = dg.aplicar_graficos(base, str(tmp_path / "o.mp4"), [{"tipo": "barras", "dados": [["a", 1], ["b", 2]], "start": 2.5, "end": 5, "posicao": "tela_cheia"}],
                                  320, 180, str(tmp_path / "w"))

        def px(t):
            return list(subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", out, "-frames:v", "1", "-vf", "crop=2:2:2:2,scale=1:1",
                                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout)
        assert px(1.0)[2] > 200 and px(3.5)[2] < 80 and px(5.6)[2] > 200


JOB = {"total_duration": 20.0,
       "pending_segments": [{"start": i * 4.0, "end": i * 4.0 + 4, "provider": "pexels", "query": "guerra", "media_type": "image"} for i in range(5)],
       "segments": [{"start": 0, "end": 4, "text": "Em 1945 a guerra acabou."}, {"start": 4, "end": 8, "text": "A população foi de 52 milhões para 203 milhões."}]}


class TestPrompt:
    def test_direcao_estrita_lista_so_o_permitido(self):
        t = pe.montar_prompt(JOB, {"direcao": "sys_dinamico", "objetivo": "mais gráficos"})
        assert "Cortes dinâmicos" in t and "mais gráficos" in t and "Transições: dp:gl_punch" in t
        assert "Cenas/takes (templates; ocupam N trechos seguidos): NÃO usar" in t
        assert "T1 [0:00.0→0:04.0]" in t and "52 milhões" in t and '"graficos"' in t

    def test_kit_e_predefinicao(self):
        t = pe.montar_prompt(JOB, {"direcao": "kit", "kit": {"transicoes": ["blinds_h"], "destaques": ["selo_ano"]}})
        assert "blinds_h" in t and "- selo_ano |" in t and "- glow_01 |" not in t

    def test_ler_resposta(self):
        ws = [{"word": w, "start": 0.2 + k * 0.4, "end": 0.5 + k * 0.4} for k, w in enumerate("Em 1945 a guerra acabou".split())]
        texto = "ok\n```json\n" + json.dumps({
            "filtro_cor": "vhs", "paleta": {"primaria": "#e0313b"}, "legenda": {"estilo": "pop"},
            "trechos": [{"trecho": 1, "transition": "gl_punch", "efeito": "zoom_rapido"}, {"trecho": 2, "transition": "xx", "template": "MOLDURA_02"},
                        {"trecho": 3, "efeito": None}, {"trecho": 99, "efeito": "zoom_in"}],
            "destaques": [{"estilo": "selo_ano", "texto": "1945", "palavra": "1945"}, {"estilo": "nada", "texto": "x"}],
            "graficos": [{"tipo": "linha", "dados": [["1950", 52], ["2022", 203]], "start": 4, "end": 8}, {"tipo": "barras", "dados": []}],
            "sons": [{"som": "transicoes/digital", "start": 3}, {"som": "nao/existe", "start": 1}], "observacoes": "x"}) + "\n```"
        r = pe.ler_resposta(texto, 5, 20.0, ws, [True, True, True, False, True])
        t = {x["indice"]: x for x in r["trechos"]}
        assert t[0] == {"indice": 0, "transition": "dp:gl_punch", "efeito": "zoom_rapido"}
        assert "transition" not in t[1] and t[1]["template"] == "MOLDURA_02" and t[2] == {"indice": 2, "efeito": None}
        assert len(r["destaques"]) == 1 and abs(r["destaques"][0]["start"] - 0.6) < 0.5
        assert len(r["graficos"]) == 1 and r["filtro_cor"] == "vhs" and r["paleta"]["primaria"] == "#E0313B" and r["paleta"]["secundaria"] != "#FF9A1F"
        assert r["legenda"] == {"estilo": "pop"} and len(r["sons"]) == 1 and len(r["avisos"]) >= 4

    def test_json_invalido(self):
        with pytest.raises(ValueError):
            pe.ler_resposta("sem json aqui", 3, 10, [])
        assert pe.extrair_json('{"a": [1, 2,],}') == {"a": [1, 2]}


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


class TestRotas:
    def test_fluxo(self, A):
        jid = "v76ia"
        os.makedirs(A._job_dir(jid), exist_ok=True)
        A._JOBS[jid] = dict(json.loads(json.dumps(JOB)), job_id=jid, status="pronto_para_editar", created_at=1.0,
                            segment_previews=[{"index": i, "ok": False} for i in range(5)])
        c = A.app.test_client()
        r = c.post(f"/job/{jid}/edicao/prompt", json={"direcao": "sys_cinema", "segmentos": A._JOBS[jid]["pending_segments"]}).get_json()
        assert r["ok"] and "Cinema premium" in r["prompt"] and 'fala: "Em 1945' in r["prompt"]
        r = c.post(f"/job/{jid}/edicao/resposta", json={"texto": json.dumps({"graficos": [{"tipo": "numero", "dados": [["x", 5]], "start": 1, "end": 4}]})}).get_json()
        assert r["ok"] and len(r["graficos"]) == 1
        assert c.post(f"/job/{jid}/edicao/resposta", json={"texto": "nada"}).status_code == 400
        img = c.post(f"/job/{jid}/grafico/previa", json={"grafico": {"tipo": "pizza", "dados": [["a", 1], ["b", 2]]}})
        assert img.status_code == 200 and img.mimetype == "image/png"
        assert c.post(f"/job/{jid}/grafico/previa", json={"grafico": {"tipo": "pizza", "dados": []}}).status_code == 400
        html = c.get(f"/job/{jid}/edit-segments?modo=estudio").get_data(as_text=True)
        assert 'id="tab-ia"' in html and 'id="layerGr"' in html
        form = {"acao": "salvar", **{f"seg_{i}_start": str(i * 4.0) for i in range(5)}, **{f"seg_{i}_end": str(i * 4.0 + 4) for i in range(5)},
                "graficos_json": json.dumps([{"tipo": "barras", "dados": [["a", 1], ["b", 2]], "start": 2, "end": 6}, {"tipo": "x", "dados": []}]),
                "destaques_json": json.dumps([{"estilo": "selo_ano", "start": 1, "end": 3, "texto": "1945", "origem": "ia"}])}
        assert c.post(f"/job/{jid}/confirm-segments", data=form, headers={"X-Requested-With": "fetch"}).status_code == 200
        assert len(A._JOBS[jid]["graficos"]) == 1 and A._JOBS[jid]["destaques"][0]["origem"] == "ia"

    def test_primeiro_prompt_aceita_graficos(self):
        from prompt_builder import parse_ai_response
        resp = json.dumps({"segments": [{"start": 0, "end": 5, "provider": "pexels", "query": "a"}],
                           "graficos": [{"tipo": "barras", "dados": [["a", 1], ["b", 2]], "start": 1, "end": 4}]})
        p = parse_ai_response(resp, ["pexels"], 5.0)
        assert len(p.graficos) == 1
