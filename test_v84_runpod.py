"""v84_116 — 🟣 Runpod: outro gerador de imagem/vídeo por IA (Z-Image Turbo, Flux Schnell, Pruna Video), com o
prompt adaptado a cada modelo, o saldo conferido antes de cada pedido e cache (o mesmo pedido nunca é cobrado 2×)."""
import json
import os

import pytest

import runpod_gerador as rp


@pytest.fixture
def rpf(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNPOD_DADOS_DIR", str(tmp_path / "rp"))
    monkeypatch.setattr(rp, "_SALDO", {"valor": None, "quando": 0.0, "erro": None, "gasto_hora": None, "chave": ""})
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: False)
    chamadas = []
    estado = {"saldo": 5.0, "pendente": False}

    def http(metodo, url, chave_api, corpo=None, timeout=120):
        chamadas.append((metodo, url, corpo))
        assert chave_api == "rpa_" + "X" * 10
        if url == rp.GRAPHQL:
            return {"data": {"myself": {"clientBalance": estado["saldo"], "currentSpendPerHr": 0, "spendLimit": 80}}}
        if url.endswith("/runsync"):
            if estado["pendente"]:
                return {"id": "job1", "status": "IN_QUEUE"}
            modelo = url.split("/")[-2]
            return {"id": "s1", "status": "COMPLETED", "output": {
                ("video_url" if modelo == "p-video" else "image_url"): f"https://cdn.runpod.ai/{modelo}/out." + ("mp4" if modelo == "p-video" else "png"),
                "cost": 0.1 if modelo == "p-video" else 0.005}}
        if "/status/" in url:
            return {"id": "job1", "status": "COMPLETED", "output": {"image_url": "https://cdn.runpod.ai/z/out.png", "cost": 0.005}}
        raise AssertionError(url)

    def baixar(url, destino, timeout=300):
        if destino.endswith(".png"):
            from PIL import Image
            Image.new("RGB", (64, 36), "navy").save(destino, "PNG")
        else:
            with open(destino, "wb") as f:
                f.write(b"x" * 64)
        return destino
    monkeypatch.setattr(rp, "_http", http)
    monkeypatch.setattr(rp, "_baixar", baixar)
    monkeypatch.setattr(rp, "_miniatura", lambda v: "")
    monkeypatch.setattr(rp.time, "sleep", lambda s: None)
    cfg = {"runpod_api_key": "rpa_" + "X" * 10, "orientation": "16:9", "runpod_modelo_imagem": "z-image-turbo",
           "runpod_modelo_video": "p-video", "runpod_video_duracao": 6}
    return cfg, chamadas, estado


def test_cada_modelo_recebe_o_pedido_dele(rpf):
    cfg = rpf[0]
    z = rp.adaptar("z-image-turbo", "farol numa tempestade à noite", cfg)
    assert z["size"] == "1280*720" and "negative_prompt" not in z and "farol" in z["prompt"] and "without any text" in z["prompt"]
    f = rp.adaptar("black-forest-labs-flux-1-schnell", "farol", dict(cfg, orientation="9:16"))
    assert (f["width"], f["height"]) == (768, 1344) and f["width"] % 64 == 0 and f["height"] % 64 == 0
    assert "watermark" in f["negative_prompt"] and "cartoon" in f["negative_prompt"] and f["num_inference_steps"] == 4
    v = rp.adaptar("p-video", "ondas batendo no farol", dict(cfg, runpod_video_rascunho=True))
    assert v["duration"] == 6 and v["aspect_ratio"] == "16:9" and v["draft"] is True and v["save_audio"] is False
    assert "camera" in v["prompt"].lower() and "no text" in v["prompt"].lower()
    assert rp.MODELOS["p-video"]["custo"](v) == pytest.approx(0.03)  # 6 s × 0,02 × 25% (rascunho)
    ilus = rp.adaptar("black-forest-labs-flux-1-schnell", "dragão", dict(cfg, _estilo_ficha="ilustração em aquarela"))
    assert "cartoon" not in ilus["negative_prompt"] and "illustration" in ilus["prompt"]


def test_com_a_ia_o_prompt_e_escrito_pra_cada_modelo(rpf, monkeypatch):
    import ia_servico
    pedidos = []
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: r == "runpod_prompt")
    monkeypatch.setattr(ia_servico, "chamar", lambda recurso, sistema, conteudo, **k: pedidos.append((sistema, conteudo, k)) or
                        {"prompt": "A lone lighthouse in a violent storm at night, cinematic", "negative_prompt": "text, blur"})
    f = rp.adaptar("black-forest-labs-flux-1-schnell", "farol na tempestade", dict(rpf[0], _estilo_ficha="documentário sombrio"))
    assert f["prompt"].startswith("A lone lighthouse") and f["negative_prompt"] == "text, blur" and f["_por"] == "ia"
    assert "Flux Schnell" in pedidos[0][0] and "negative_prompt" in pedidos[0][0] and "documentário sombrio" in pedidos[0][1]
    z = rp.adaptar("z-image-turbo", "farol", rpf[0])
    assert "negative_prompt" not in z and "Z-Image" in pedidos[1][0] and "negative_prompt" not in pedidos[1][0]
    assert "Pruna" in rp._GUIA["p-video"] and "runpod_prompt" in ia_servico.RECURSOS


def test_gera_baixa_cobra_e_nao_gera_duas_vezes(rpf):
    cfg, chamadas, estado = rpf
    r = rp.gerar("farol numa tempestade", "imagem", cfg)
    assert os.path.isfile(r["caminho"]) and r["url"].startswith("/runpod/midias/rp_") and r["custo"] == 0.005 and not r["reaproveitado"]
    corpo = next(c for m, u, c in chamadas if u.endswith("z-image-turbo/runsync"))
    assert corpo["input"]["size"] == "1280*720" and "farol" in corpo["input"]["prompt"]
    assert rp.saldo(cfg)["saldo"] == pytest.approx(4.995)  # saldo descontado sem perguntar de novo
    n = len(chamadas)
    r2 = rp.gerar("Farol  numa tempestade", "imagem", cfg)
    assert r2["reaproveitado"] and r2["arquivo"] == r["arquivo"] and len(chamadas) == n  # cache: nada enviado
    assert rp.ja_gerado("farol numa tempestade", "imagem", cfg) and not rp.ja_gerado("farol numa tempestade", "video", cfg)
    assert rp.arquivo_local(r["url"]) == r["caminho"]
    v = rp.gerar("ondas no farol", "video", cfg)
    assert v["arquivo"].endswith(".mp4") and v["custo"] == 0.1
    assert rp.uso()["total"] == pytest.approx(0.105) and rp.uso()["por_modelo"]["p-video"] == 0.1


def test_espera_o_pedido_na_fila(rpf):
    cfg, chamadas, estado = rpf
    estado["pendente"] = True
    r = rp.gerar("castelo", "imagem", cfg)
    assert os.path.isfile(r["caminho"]) and any("/status/job1" in u for _m, u, _c in chamadas)


def test_sem_saldo_nem_envia(rpf):
    cfg, chamadas, estado = rpf
    estado["saldo"] = 0.05
    with pytest.raises(rp.RunpodSemSaldo) as e:
        rp.gerar("ondas", "video", cfg)  # ~US$ 0,12
    assert "US$ 0.0500" in str(e.value) and not any(u.endswith("/runsync") for _m, u, _c in chamadas)
    assert rp.tem_saldo("video", cfg) is False and rp.tem_saldo("imagem", cfg) is True
    assert rp.tem_saldo("imagem", {"runpod_api_key": ""}) is False


def test_cliente_e_montagem(rpf, monkeypatch, tmp_path):
    import video_assembler as va
    from prompt_builder import VideoSegment
    cfg, chamadas, estado = rpf
    fab = va.ClientFactory(cfg)
    foto = fab.get_photo_client("runpod")
    assert isinstance(foto, rp.RunpodClient) and isinstance(fab.get_client("runpod"), rp.RunpodClient)
    fotos = foto.search_photos_all("um mapa antigo")
    assert os.path.isfile(foto.download_photo(fotos[0], str(tmp_path / "d")))
    # trecho de vídeo sem saldo pra vídeo: vira foto com o prompt reescrito (sem gastar com vídeo)
    estado["saldo"] = 0.05
    rp._SALDO.update(valor=None)
    seg = VideoSegment(start=0, end=4, provider="runpod", query="Slow push-in on a lighthouse, 8 seconds", media_type="video")
    monkeypatch.setattr(va, "garantir_imagem_compativel", lambda p: p)
    paths, kind, oque = va.gerar_no_runpod(seg, str(tmp_path / "dl"), fab, cfg, None, video=True)
    assert kind == "image" and "foto do Runpod no lugar do vídeo" in oque and "sem saldo" in oque
    prompts = [c["input"]["prompt"] for _m, u, c in chamadas if u.endswith("z-image-turbo/runsync")]
    assert "push-in" not in prompts[-1].lower() and "lighthouse" in prompts[-1]
    assert va._sem_flow_no_fallback(["pexels", "runpod", "flow", "mixkit"], "pexels") == ["mixkit"]
    assert va.flow_arquivo_local(fotos[0].url) == fotos[0].local_path  # prévia → mesmo arquivo na exportação


def test_telas_e_prompt(rpf, monkeypatch, tmp_path):
    import app as A
    import prompt_builder as pb
    import site_config
    monkeypatch.setattr(site_config, "CONFIG_PATH", str(tmp_path / "cfg.json"))
    A.app.config["TESTING"] = True
    c = A.app.test_client()
    h = c.get("/settings").get_data(as_text=True)
    assert 'id="runpod"' in h and 'name="runpod_api_key"' in h and "Sem chave ainda" in h and "Pruna Video" in h
    c.post("/settings", data={"runpod_api_key": "rpa_" + "X" * 10, "runpod_modelo_imagem": "black-forest-labs-flux-1-schnell",
                              "runpod_modelo_video": "p-video", "runpod_video_duracao": "8", "runpod_reserva_flow": "on"})
    cfg = site_config.load_site_config()
    assert cfg["runpod_api_key"] == "rpa_" + "X" * 10 and cfg["runpod_modelo_imagem"] == "black-forest-labs-flux-1-schnell"
    assert cfg["runpod_video_duracao"] == 8 and cfg["runpod_reserva_flow"] is True and "runpod" in cfg["provider_priority"]
    h = c.get("/settings").get_data(as_text=True)
    assert "rpa_XX…XXXX" in h and "conferir saldo" in h and "rpa_XXXXXXXXXX" not in h  # a chave nunca volta inteira pra tela
    d = c.get("/runpod/saldo?forcar=1").get_json()
    assert d["saldo"] == 5.0 and d["configurado"]
    t = pb.build_prompt([{"start": 0.0, "end": 5.0, "text": "um dragão"}], providers=["pexels", "runpod"])
    assert 'O provedor "runpod" também GERA' in t and "runpod" in pb.PHOTO_SEARCH_PROVIDERS
    r = pb.parse_ai_response(json.dumps({"segments": [{"start": 0, "end": 5, "provider": "runpod", "query": "um dragão", "media_type": "image"}]}),
                             allowed_providers=["pexels", "runpod"]) if "allowed_providers" in pb.parse_ai_response.__code__.co_varnames else None
    assert r is None or r.segments[0].provider == "runpod"
