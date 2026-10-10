"""
Painel "Vídeos do YouTube" do editor: quando a IA pede YouTube (trecho com
provider "youtube" ou corte real sugerido), o site já pesquisa os termos em
segundo plano assim que a resposta é colada; no editor a pessoa só escolhe o
vídeo + a faixa de tempo (pode trocar o termo e pesquisar de novo) e o site
baixa/corta. A busca/download/corte do YouTube são mockados aqui (já têm a
própria suíte em test_youtube_clipper.py).
"""
import json
import os
import time

import pytest


def _resultado(n=1, termo="x"):
    return [{"id": f"vid{i:08d}ab"[:11], "titulo": f"{termo} #{i}", "url": f"https://youtube.com/watch?v=v{i}",
             "duracao_segundos": 120, "duracao_formatada": "2:00", "miniatura_url": f"https://img/{i}.jpg",
             "descricao": "", "canal": "Canal"} for i in range(n)]


@pytest.fixture
def app_module(monkeypatch):
    import app as _app_module

    def _sem_previa(segment, **kwargs):
        return {"ok": False, "thumbnail_url": None, "result_url": None, "label": None, "error": "mockado"}

    monkeypatch.setattr(_app_module, "fetch_segment_preview_lightweight", _sem_previa)
    monkeypatch.setattr(_app_module, "generate_waveform_image", lambda *a, **k: None)
    yield _app_module


@pytest.fixture
def buscas(app_module, monkeypatch):
    chamadas = []

    def fake_buscar(termo, quantidade=12):
        chamadas.append((termo, quantidade))
        if termo == "quebra":
            from youtube_clipper import YoutubeClipperError
            raise YoutubeClipperError("yt-dlp falhou")
        return _resultado(3, termo)

    monkeypatch.setattr(app_module, "buscar_videos_youtube", fake_buscar)
    return chamadas


def _esperar(cond, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    raise TimeoutError("condição não ficou verdadeira a tempo")


def _job_aguardando_json(app_module, tmp_path, job_id, providers=("pexels", "youtube")):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    app_module._JOBS[job_id] = {
        "job_id": job_id, "status": "aguardando_json", "providers": list(providers),
        "total_duration": 20.0, "audio_path": str(audio), "segments": [],
    }
    return job_id


RESPOSTA_IA = {
    "segments": [
        {"start": 0.0, "end": 8.0, "provider": "pexels", "query": "city skyline"},
        {"start": 8.0, "end": 14.5, "provider": "youtube", "query": "Gojo domain expansion"},
        {"start": 14.5, "end": 20.0, "provider": "pexels", "query": "night sky"},
    ],
    "cutaway_suggestions": [
        {"insertion_point": 5.0, "description": "Coletiva do prefeito", "query": "coletiva prefeito tarifa zero"},
    ],
}


def _colar(client, job_id, resposta=RESPOSTA_IA):
    r = client.post(f"/job/{job_id}/submit-json", data={"ai_response": json.dumps(resposta)})
    assert r.status_code == 302, r.data[:500]


class TestBuscaAutomatica:
    def test_colar_resposta_ja_pesquisa_todos_os_termos_do_youtube(self, app_module, buscas, tmp_path):
        job_id = _job_aguardando_json(app_module, tmp_path, "job-yt-auto")
        client = app_module.app.test_client()
        _colar(client, job_id)
        job = app_module._JOBS[job_id]
        _esperar(lambda: all(it["status"] == "pronto" for it in job["youtube_itens"]))
        termos = sorted(t for t, _q in buscas)
        assert termos == ["Gojo domain expansion", "coletiva prefeito tarifa zero"]
        ids = [it["id"] for it in job["youtube_itens"]]
        assert "seg-1" in ids and any(i.startswith("cut-") for i in ids)
        seg_item = next(it for it in job["youtube_itens"] if it["id"] == "seg-1")
        assert seg_item["duracao_alvo"] == 6.5
        assert len(seg_item["resultados"]) == 3

    def test_trecho_youtube_nao_ganha_previa_automatica(self, app_module, buscas, tmp_path):
        job_id = _job_aguardando_json(app_module, tmp_path, "job-yt-previa")
        client = app_module.app.test_client()
        _colar(client, job_id)
        job = app_module._JOBS[job_id]
        _esperar(lambda: job["status"] == "pronto_para_editar")
        prev = job["segment_previews"][1]
        assert prev["ok"] is False and prev["provider"] == "youtube"
        assert "painel" in prev["error"]

    def test_rota_itens_lista_e_informa_quando_terminou(self, app_module, buscas, tmp_path):
        job_id = _job_aguardando_json(app_module, tmp_path, "job-yt-rota")
        client = app_module.app.test_client()
        _colar(client, job_id)
        _esperar(lambda: not client.get(f"/job/{job_id}/youtube/itens").get_json()["buscando"])
        data = client.get(f"/job/{job_id}/youtube/itens").get_json()
        assert data["ok"] and len(data["itens"]) == 2
        assert all(it["status"] == "pronto" for it in data["itens"])

    def test_erro_na_busca_fica_no_item_sem_travar_os_outros(self, app_module, buscas, tmp_path):
        job_id = _job_aguardando_json(app_module, tmp_path, "job-yt-erro")
        client = app_module.app.test_client()
        resposta = json.loads(json.dumps(RESPOSTA_IA))
        resposta["segments"][1]["query"] = "quebra"
        _colar(client, job_id, resposta)
        job = app_module._JOBS[job_id]
        _esperar(lambda: all(it["status"] in ("pronto", "erro") for it in job["youtube_itens"]))
        seg_item = next(it for it in job["youtube_itens"] if it["id"] == "seg-1")
        assert seg_item["status"] == "erro" and "yt-dlp falhou" in seg_item["erro"]
        cut_item = next(it for it in job["youtube_itens"] if it["tipo"] == "corte")
        assert cut_item["status"] == "pronto"

    def test_sem_nada_do_youtube_nao_pesquisa_nada(self, app_module, buscas, tmp_path):
        job_id = _job_aguardando_json(app_module, tmp_path, "job-yt-nada")
        client = app_module.app.test_client()
        _colar(client, job_id, {"segments": [{"start": 0, "end": 20, "provider": "pexels", "query": "x"}]})
        time.sleep(0.3)
        assert buscas == []
        assert app_module._JOBS[job_id]["youtube_itens"] == []

    def test_corte_sem_query_usa_a_descricao(self, app_module, buscas, tmp_path):
        job_id = _job_aguardando_json(app_module, tmp_path, "job-yt-desc")
        client = app_module.app.test_client()
        _colar(client, job_id, {
            "segments": [{"start": 0, "end": 20, "provider": "pexels", "query": "x"}],
            "cutaway_suggestions": [{"insertion_point": 3, "description": "Discurso do CEO"}],
        })
        _esperar(lambda: buscas)
        assert buscas[0][0] == "Discurso do CEO"


class TestEditorEEscolha:
    def _pronto(self, app_module, buscas, tmp_path, job_id):
        _job_aguardando_json(app_module, tmp_path, job_id)
        client = app_module.app.test_client()
        _colar(client, job_id)
        job = app_module._JOBS[job_id]
        _esperar(lambda: job["status"] == "pronto_para_editar"
                 and all(it["status"] == "pronto" for it in job["youtube_itens"]))
        return client, job

    def test_editor_mostra_o_painel_com_os_termos(self, app_module, buscas, tmp_path):
        client, job = self._pronto(app_module, buscas, tmp_path, "job-yt-editor")
        html = client.get(f"/job/{job['job_id']}/edit-segments?modo=classico").get_data(as_text=True)
        assert 'id="painel-youtube"' in html
        assert 'id="yt-item-seg-1"' in html
        assert 'value="Gojo domain expansion"' in html
        assert 'value="coletiva prefeito tarifa zero"' in html
        # o painel fica DENTRO do formulário, antes do botão de montar
        assert html.index('id="painel-youtube"') < html.index("Confirmar e montar o vídeo")
        # o seletor do trecho tem a opção youtube marcada
        assert '<option value="youtube" selected>' in html

    def test_editor_sem_youtube_nao_mostra_painel(self, app_module, buscas, tmp_path):
        job_id = _job_aguardando_json(app_module, tmp_path, "job-yt-sem")
        client = app_module.app.test_client()
        _colar(client, job_id, {"segments": [{"start": 0, "end": 20, "provider": "pexels", "query": "x"}]})
        _esperar(lambda: app_module._JOBS[job_id]["status"] == "pronto_para_editar")
        html = client.get(f"/job/{job_id}/edit-segments?modo=classico").get_data(as_text=True)
        assert 'id="painel-youtube"' not in html

    def test_buscar_de_novo_com_outro_termo(self, app_module, buscas, tmp_path):
        client, job = self._pronto(app_module, buscas, tmp_path, "job-yt-rebusca")
        r = client.post(f"/job/{job['job_id']}/youtube/item/seg-1/buscar", json={"termo": "gojo vs sukuna"})
        assert r.status_code == 200
        _esperar(lambda: next(it for it in job["youtube_itens"] if it["id"] == "seg-1")["status"] == "pronto")
        item = next(it for it in job["youtube_itens"] if it["id"] == "seg-1")
        assert item["termo"] == "gojo vs sukuna"
        assert item["resultados"][0]["titulo"].startswith("gojo vs sukuna")

    def test_buscar_de_novo_termo_vazio_400_e_item_inexistente_404(self, app_module, buscas, tmp_path):
        client, job = self._pronto(app_module, buscas, tmp_path, "job-yt-rebusca-erro")
        assert client.post(f"/job/{job['job_id']}/youtube/item/seg-1/buscar", json={"termo": " "}).status_code == 400
        assert client.post(f"/job/{job['job_id']}/youtube/item/seg-0/buscar", json={"termo": "x"}).status_code == 404

    def test_usar_trecho_vira_o_arquivo_do_trecho_e_sobrevive_ao_confirmar(self, app_module, buscas, tmp_path, monkeypatch):
        client, job = self._pronto(app_module, buscas, tmp_path, "job-yt-usar")
        baixados, cortes = [], []

        def fake_baixar(url, pasta, *a, **k):
            os.makedirs(pasta, exist_ok=True)
            p = os.path.join(pasta, "v.mp4")
            open(p, "wb").write(b"video")
            baixados.append(url)
            return {"caminho": p}

        def fake_cortar(src, inicio, fim, out):
            cortes.append((inicio, fim))
            open(out, "wb").write(b"trecho")
            return out

        monkeypatch.setattr(app_module, "yt_baixar_video", fake_baixar)
        monkeypatch.setattr(app_module, "yt_cortar_trecho", fake_cortar)
        r = client.post(f"/job/{job['job_id']}/youtube/item/seg-1/usar", json={
            "url": "https://youtube.com/watch?v=v1", "inicio": 30, "fim": 36.5, "titulo": "Gojo",
            "miniatura_url": "https://img/1.jpg"})
        assert r.status_code == 200
        yt_job = r.get_json()["yt_job_id"]
        _esperar(lambda: app_module._CUTAWAY_YT_JOBS[yt_job]["status"] != "processando")
        assert app_module._CUTAWAY_YT_JOBS[yt_job]["status"] == "pronto"
        assert baixados == ["https://youtube.com/watch?v=v1"] and cortes == [(30.0, 36.5)]
        seg = job["pending_segments"][1]
        assert seg["override_source"]["source"] == "local_file"
        assert open(seg["override_source"]["value"], "rb").read() == b"trecho"
        assert job["segment_previews"][1]["ok"] and job["segment_previews"][1]["thumbnail_url"] == "https://img/1.jpg"
        item = next(it for it in job["youtube_itens"] if it["id"] == "seg-1")
        assert item["escolha"]["inicio"] == 30.0

        # confirmar com o seletor ainda em "buscar automaticamente" mantém o clipe escolhido
        capturado = {}

        def fake_start(job_id, job_, segments):
            capturado["segs"] = segments

        monkeypatch.setattr(app_module, "_start_assembly", fake_start)
        monkeypatch.setattr(app_module, "photo_api_configuration_error", lambda *a, **k: None)
        form = {f"seg_{i}_source_mode": "auto" for i in range(3)}
        client.post(f"/job/{job['job_id']}/confirm-segments", data=form)
        assert capturado["segs"][1].override_source["value"] == seg["override_source"]["value"]
        assert capturado["segs"][0].override_source is None

    def test_usar_trecho_num_corte_resolve_o_corte(self, app_module, buscas, tmp_path, monkeypatch):
        client, job = self._pronto(app_module, buscas, tmp_path, "job-yt-corte")

        def fake_baixar(url, pasta, *a, **k):
            os.makedirs(pasta, exist_ok=True)
            p = os.path.join(pasta, "v.mp4")
            open(p, "wb").write(b"v")
            return {"caminho": p}

        monkeypatch.setattr(app_module, "yt_baixar_video", fake_baixar)
        monkeypatch.setattr(app_module, "yt_cortar_trecho", lambda s, a, b, out: open(out, "wb").write(b"c") and out)
        cut_item = next(it for it in job["youtube_itens"] if it["tipo"] == "corte")
        r = client.post(f"/job/{job['job_id']}/youtube/item/{cut_item['id']}/usar",
                        json={"url": "https://youtube.com/watch?v=v2", "inicio": 0, "fim": 8})
        yt_job = r.get_json()["yt_job_id"]
        _esperar(lambda: app_module._CUTAWAY_YT_JOBS[yt_job]["status"] != "processando")
        assert job["cutaway_suggestions"][0]["resolved_path"]

        # desfazer volta o corte a ficar sem clipe
        assert client.post(f"/job/{job['job_id']}/youtube/item/{cut_item['id']}/limpar").status_code == 200
        assert job["cutaway_suggestions"][0]["resolved_path"] is None

    @pytest.mark.parametrize("corpo, trecho", [
        ({"url": "", "inicio": 0, "fim": 5}, "Escolha um vídeo"),
        ({"url": "https://y/v", "inicio": 5, "fim": 5}, "precisa vir depois"),
        ({"url": "https://y/v", "inicio": -1, "fim": 5}, "negativo"),
        ({"url": "https://y/v", "inicio": "a", "fim": 5}, "números"),
    ])
    def test_usar_valida_entrada(self, app_module, buscas, tmp_path, corpo, trecho):
        client, job = self._pronto(app_module, buscas, tmp_path, f"job-yt-val-{abs(hash(str(corpo))) % 10000}")
        r = client.post(f"/job/{job['job_id']}/youtube/item/seg-1/usar", json=corpo)
        assert r.status_code == 400
        assert trecho in r.get_json()["erro"]


class TestMontagemSemEscolha:
    def test_trecho_youtube_sem_escolha_cai_pros_bancos_normais(self):
        from video_assembler import ClientFactory, VideoAssemblyError

        with pytest.raises(VideoAssemblyError) as exc:
            ClientFactory({}).get_client("youtube")
        assert "painel" in str(exc.value)


class TestPromptYoutube:
    def test_regra_do_youtube_so_aparece_quando_marcado(self):
        from prompt_builder import build_prompt
        segs = [{"start": 0.0, "end": 10.0, "text": "oi"}]
        assert '"youtube"' in build_prompt(segs, providers=["pexels", "youtube"])
        assert '"youtube" é DIFERENTE' not in build_prompt(segs, providers=["pexels"])

    def test_exemplo_do_json_nunca_usa_youtube(self):
        from prompt_builder import build_prompt
        p = build_prompt([{"start": 0.0, "end": 10.0, "text": "oi"}], providers=["youtube", "pixabay"])
        assert '"provider": "pixabay", "query": "sunrise over mountains"' in p

    def test_youtube_com_media_type_image_e_rejeitado(self):
        from prompt_builder import PromptBuilderError, parse_ai_response
        with pytest.raises(PromptBuilderError) as exc:
            parse_ai_response(json.dumps({"segments": [
                {"start": 0, "end": 10, "provider": "youtube", "query": "x", "media_type": "image"}]}),
                valid_providers=["youtube"], total_duration=10)
        assert "só traz VÍDEO" in str(exc.value)

    def test_query_do_corte_e_guardada(self):
        from prompt_builder import parse_ai_response
        r = parse_ai_response(json.dumps({
            "segments": [{"start": 0, "end": 10, "provider": "pexels", "query": "x"}],
            "cutaway_suggestions": [{"insertion_point": 2, "description": "d", "query": "  termo yt "},
                                    {"insertion_point": 3, "description": "sem query"}]}),
            valid_providers=["pexels"], total_duration=10)
        assert r.cutaway_suggestions[0]["query"] == "termo yt"
        assert "query" not in r.cutaway_suggestions[1]

    def test_youtube_aparece_desmarcado_na_tela_de_upload(self, app_module):
        html = app_module.app.test_client().get("/").get_data(as_text=True)
        assert 'value="youtube"' in html
        assert 'value="youtube" checked' not in html


class TestTelaDePrevias:
    def test_painel_do_youtube_aparece_ja_na_tela_de_previas(self, app_module, buscas, tmp_path):
        job_id = _job_aguardando_json(app_module, tmp_path, "job-yt-tela-previas")
        client = app_module.app.test_client()
        _colar(client, job_id)
        html = client.get(f"/job/{job_id}/fetching-previews").get_data(as_text=True)
        assert 'id="painel-youtube"' in html
        assert 'id="yt-item-seg-1"' in html
        assert "const temPainelYoutube = true" in html

    def test_status_das_previas_informa_youtube_e_erro(self, app_module, buscas, tmp_path):
        job_id = _job_aguardando_json(app_module, tmp_path, "job-yt-status-previas")
        client = app_module.app.test_client()
        _colar(client, job_id)
        _esperar(lambda: app_module._JOBS[job_id]["status"] == "pronto_para_editar")
        data = client.get(f"/job/{job_id}/fetching-previews-status").get_json()
        por_indice = {p["index"]: p for p in data["previews"]}
        assert por_indice[1]["provider"] == "youtube"
        assert por_indice[0]["error"] == "mockado"

    def test_sem_youtube_a_tela_de_previas_continua_indo_sozinha_pro_editor(self, app_module, buscas, tmp_path):
        job_id = _job_aguardando_json(app_module, tmp_path, "job-yt-sem-tela")
        client = app_module.app.test_client()
        _colar(client, job_id, {"segments": [{"start": 0, "end": 20, "provider": "pexels", "query": "x"}]})
        html = client.get(f"/job/{job_id}/fetching-previews").get_data(as_text=True)
        assert 'id="painel-youtube"' not in html
        assert "const temPainelYoutube = false" in html
