"""v80 — proporção fotos × vídeos na escolha dos bancos + vídeo gerado no Flow."""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "toolkit"))

import mix_midia  # noqa: E402
from prompt_builder import build_prompt  # noqa: E402
from googleflow import googleflow_client as gf  # noqa: E402

_TRANS = [{"start": 0.0, "end": 5.0, "text": "Um teste."}, {"start": 5.0, "end": 10.0, "text": "Outro."}]


def _segs(provs, tipo="video"):
    return [{"start": i, "end": i + 1, "provider": p, "query": f"q{i}", "media_type": tipo} for i, p in enumerate(provs)]


class F(dict):
    def getlist(self, k):
        v = self.get(k)
        return v if isinstance(v, list) else ([v] if v else [])


# ---------------------------------------------------------------- formulário
def test_do_form_so_vale_com_a_caixa_marcada():
    assert mix_midia.do_form(F(mix_global="90")) == {}
    m = mix_midia.do_form(F(mix_ativo="on", mix_global="90", mix_flow="75%", mix_pexels=""))
    assert m == {"global": 90, "provedores": {"flow": 75}}
    assert mix_midia.do_form(F(mix_ativo_reuse="on", mix_pexels_reuse="10"), sufixo="_reuse") == {"provedores": {"pexels": 10}}
    assert mix_midia.normalizar({"global": 140, "provedores": {"pixabay": 50, "flow": -3}}) == {"global": 100, "provedores": {"flow": 0}}


def test_regra_no_prompt():
    com = build_prompt(_TRANS, providers=["pexels", "flow"], mix_midia={"global": 90, "provedores": {"flow": 90}})
    assert "PROPORÇÃO FOTOS × VÍDEOS" in com and "cerca de 90%" in com and '"provider": "flow"' in com
    sem = build_prompt(_TRANS, providers=["pexels", "flow"])
    assert "PROPORÇÃO FOTOS × VÍDEOS" not in sem
    # banco não selecionado não entra na regra
    assert "provider\": \"flow\"`, cerca" not in mix_midia.regra_prompt({"provedores": {"flow": 50}}, ["pexels"])


# ---------------------------------------------------------------- ajuste da resposta
def test_flow_90_por_cento_fotos():
    segs = _segs(["flow"] * 10, "image")
    n, av = mix_midia.aplicar(segs, {"provedores": {"flow": 90}}, ["flow"])
    tipos = [s["media_type"] for s in segs]
    assert tipos.count("image") == 9 and tipos.count("video") == 1 and n == 1
    assert "ajustei 1" in av[0]


def test_flow_meio_a_meio_espalhado():
    segs = _segs(["flow"] * 8, "image")
    mix_midia.aplicar(segs, {"provedores": {"flow": 50}}, ["flow"])
    videos = [i for i, s in enumerate(segs) if s["media_type"] == "video"]
    assert len(videos) == 4 and videos != [0, 1, 2, 3]  # distribuídos, não amontoados no começo


def test_global_transforma_banco_so_video_em_foto_do_pexels():
    segs = _segs(["pixabay"] * 8 + ["mixkit"] * 2)
    mix_midia.aplicar(segs, {"global": 90}, ["pixabay", "mixkit", "pexels"])
    fotos = [s for s in segs if s["media_type"] == "image"]
    assert len(fotos) == 9 and all(s["provider"] == "pexels" for s in fotos)


def test_global_impossivel_avisa():
    segs = _segs(["pixabay"] * 4)
    n, av = mix_midia.aplicar(segs, {"global": 100}, ["pixabay"])
    assert n == 0 and any("só deu 0%" in a for a in av)


def test_global_menos_fotos_e_trecho_fixo_intocado():
    segs = _segs(["pexels"] * 4, "image")
    segs[0]["override_source"] = {"source": "local_file", "value": "/x.jpg"}
    mix_midia.aplicar(segs, {"global": 0}, ["pexels"])
    assert segs[0]["media_type"] == "image"  # a pessoa fixou esse
    assert [s["media_type"] for s in segs[1:]] == ["video"] * 3


def test_por_provedor_tem_prioridade_sobre_o_global():
    segs = _segs(["flow"] * 4 + ["pexels"] * 4, "image")
    mix_midia.aplicar(segs, {"global": 0, "provedores": {"flow": 100}}, ["flow", "pexels"])
    assert all(s["media_type"] == "image" for s in segs[:4])
    assert all(s["media_type"] == "video" for s in segs[4:])


# ---------------------------------------------------------------- integração com o site
@pytest.fixture
def cliente(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "_fetch_previews", lambda *a, **k: None)
    app_module.app.config["TESTING"] = True
    return app_module, app_module.app.test_client()


def test_submit_json_aplica_a_proporcao(cliente, tmp_path):
    app_module, c = cliente
    jid = "mixteste0001"
    os.makedirs(app_module._job_dir(jid), exist_ok=True)
    app_module._JOBS[jid] = {"job_id": jid, "providers": ["flow", "pexels"], "total_duration": 10.0, "status": "aguardando_json",
                             "segments": _TRANS, "mix_midia": {"provedores": {"flow": 90}}}
    resp = [{"start": i, "end": i + 1, "provider": "flow", "query": f"cena {i}", "media_type": "video"} for i in range(10)]
    r = c.post(f"/job/{jid}/submit-json", data={"ai_response": json.dumps(resp)})
    assert r.status_code == 302
    tipos = [s["media_type"] for s in app_module._JOBS[jid]["pending_segments"]]
    assert tipos.count("image") == 9 and tipos.count("video") == 1
    assert "ajustei 9" in app_module._JOBS[jid]["aviso_mix_midia"]
    app_module._JOBS.pop(jid, None)


def test_pagina_inicial_e_prompt_tem_o_bloco(cliente):
    app_module, c = cliente
    html = c.get("/").get_data(as_text=True)
    assert 'name="mix_ativo"' in html and 'name="mix_flow"' in html and 'name="mix_ativo_reuse"' in html
    assert "imagens e vídeos gerados por IA" in html


def test_atualizar_providers_guarda_a_proporcao(cliente):
    app_module, c = cliente
    jid = "mixteste0002"
    app_module._JOBS[jid] = {"job_id": jid, "providers": ["pexels"], "total_duration": 10.0, "segments": _TRANS,
                             "interval_seconds": 5, "language": "pt", "extra_instructions": ""}
    r = c.post(f"/job/{jid}/atualizar-providers", data={"providers": ["pexels", "flow"], "mix_enviado": "1",
                                                       "mix_ativo": "on", "mix_flow": "90", "mix_global": "75"})
    assert r.status_code == 302
    j = app_module._JOBS[jid]
    assert j["mix_midia"] == {"global": 75, "provedores": {"flow": 90}}
    assert "PROPORÇÃO FOTOS × VÍDEOS" in j["prompt"]
    html = c.get(f"/job/{jid}/prompt").get_data(as_text=True)
    assert 'value="90"' in html
    app_module._JOBS.pop(jid, None)


# ---------------------------------------------------------------- Flow: vídeo
def test_prompt_de_video_do_flow():
    assert gf.montar_prompt_video("um gato correndo") == "gere um vídeo de um gato correndo proporção 16x9"
    assert gf.montar_prompt_video("gere a imagem de um gato", "9x16") == "gere um vídeo de um gato proporção 9x16"
    assert gf.montar_prompt_video("gere um vídeo de ondas 16x9") == "gere um vídeo de ondas 16x9"
    assert gf.chave_do_prompt(gf.montar_prompt_video("x")) != gf.chave_do_prompt(gf.montar_prompt("x"))


class _PaginaVideo:
    def __init__(self, urls_por_chamada):
        self.urls = urls_por_chamada
        self.n = 0
        self.scripts = []

    def evaluate(self, script, arg=None):
        self.scripts.append(script)
        if script == gf.JS_BAIXAR_BASE64:
            import base64
            return base64.b64encode(b"\x00" * 4096).decode()
        u = self.urls[min(self.n, len(self.urls) - 1)]
        self.n += 1
        return {"mensagens": 1, "urls": u, "ultima_e_texto": bool(u), "texto": "Aqui está o vídeo.", "avisos": ""}


def test_esperar_video_usa_o_script_de_video(monkeypatch):
    monkeypatch.setattr(gf, "PAUSA_POLLING_S", 0)
    pg = _PaginaVideo([[], ["blob:https://flow/v1"]])
    urls = gf.esperar_geracao(pg, 0, 5, script=gf.JS_ESTADO_VIDEO, seletor=gf.SEL_VIDEO, graca_s=30, oque="vídeo")
    assert urls == ["blob:https://flow/v1"] and gf.JS_ESTADO_VIDEO in pg.scripts


def test_resposta_so_texto_espera_a_graca_do_video(monkeypatch):
    monkeypatch.setattr(gf, "PAUSA_POLLING_S", 0)
    pg = _PaginaVideo([[]])
    pg.evaluate = lambda s, a=None: {"mensagens": 1, "urls": [], "ultima_e_texto": True, "texto": "Gerando...", "avisos": ""}
    t0 = time.monotonic()
    with pytest.raises(gf.GoogleFlowError, match="sem gerar vídeo"):
        gf.esperar_geracao(pg, 0, 30, script=gf.JS_ESTADO_VIDEO, seletor=gf.SEL_VIDEO, graca_s=0.3, oque="vídeo")
    assert time.monotonic() - t0 < 5


def test_baixar_video_blob_e_cache_vira_cliente_de_video(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLEFLOW_DATA_DIR", str(tmp_path / "flow"))
    monkeypatch.setattr(gf, "PLAYWRIGHT_DISPONIVEL", True)
    prompt = gf.montar_prompt_video("ondas do mar")
    chave = gf.chave_do_prompt(prompt)
    regs = gf.baixar_videos(None, _PaginaVideo([[]]), ["blob:https://flow/v1"], prompt, chave)
    assert regs[0]["tipo"] == "video" and regs[0]["arquivo"].endswith(".mp4")
    # imagem com a mesma chave nunca confunde com vídeo
    assert gf._fotos_do_cache(chave) == []
    cli = gf.GoogleFlowClient(site_cfg={"orientation": "16:9"})
    vids = cli.search_all(query="ondas do mar")  # já está no cache: não abre navegador
    assert len(vids) == 1 and vids[0].to_dict()["video_preview_url"].startswith(gf.URL_PREFIXO_IMAGENS)
    destino = cli.download_video(vids[0], output_dir=str(tmp_path / "dl"))
    assert os.path.getsize(destino) == 4096


def test_montador_flow_video_cai_pra_imagem_quando_o_video_falha():
    import video_assembler as va
    import inspect
    src = inspect.getsource(va.assemble_video)
    assert 'elif segment.provider == "flow":' in src and 'replace(segment, media_type="image")' in src
