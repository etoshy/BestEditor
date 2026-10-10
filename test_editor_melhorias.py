"""
Melhorias do editor e da galeria:

- "✅ Usar esta no trecho" depois de buscar opções (foto baixada na hora;
  vídeo fixado pelo post ou pelo link direto);
- animação de imagem visível pra todo trecho de foto (botões rápidos) e
  preservada entre confirmações;
- transição global do vídeo + transição própria por trecho;
- escolha automática do YouTube (1º resultado, do começo) na montagem;
- galeria de projetos: recarrega do disco, renomeia, apaga com os arquivos.
"""
import json
import os

import pytest


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


@pytest.fixture
def client(A):
    return A.app.test_client()


def _job_editor(A, job_id, segs=None, **extra):
    os.makedirs(A._job_dir(job_id), exist_ok=True)
    A._JOBS[job_id] = {
        "job_id": job_id, "status": "pronto_para_editar", "created_at": 1.0, "original_filename": "n.wav",
        "pending_segments": segs or [
            {"start": 0.0, "end": 4.0, "provider": "bing", "query": "gojo", "media_type": "image", "override_source": None},
            {"start": 4.0, "end": 8.0, "provider": "pexels", "query": "city", "media_type": "video", "override_source": None},
            {"start": 8.0, "end": 12.0, "provider": "pexels", "query": "sky", "media_type": "video", "override_source": None},
        ],
        "segment_previews": [None, None, None], "cutaway_suggestions": [], "overlays": [],
        **extra,
    }
    return A._JOBS[job_id]


class TestUsarCandidato:
    def test_foto_e_baixada_e_vira_o_arquivo_do_trecho(self, A, client, monkeypatch, tmp_path):
        job = _job_editor(A, "ed-cand-foto")
        import buscador_imagens_unificado as bu
        recebido = {}

        def fake_baixar(img, pasta, stem=None, **k):
            recebido["img"] = img
            os.makedirs(pasta, exist_ok=True)
            p = os.path.join(pasta, stem + ".jpg")
            open(p, "wb").write(b"\xff\xd8\xff")
            return p

        monkeypatch.setattr(bu, "baixar_imagem", fake_baixar)
        r = client.post("/job/ed-cand-foto/segmento/0/usar-candidato", json={
            "provider": "brave", "media_type": "image", "image_url": "https://img/orig.jpg",
            "thumbnail": "https://img/t.jpg", "url": "https://site/p", "label": "Gojo"})
        data = r.get_json()
        assert r.status_code == 200 and data["ok"] and data["modo"] == "upload"
        assert recebido["img"].original_url == "https://img/orig.jpg"
        assert recebido["img"].thumbnail_url == "https://img/t.jpg"  # reserva se o site bloquear a original
        ov = job["pending_segments"][0]["override_source"]
        assert ov["source"] == "local_file" and ov["kind"] == "image" and os.path.exists(ov["value"])
        assert job["segment_previews"][0]["thumbnail_path"] == ov["value"]
        assert client.get("/job/ed-cand-foto/thumbnail/0").status_code == 200

    def test_video_de_banco_com_post_fica_fixado(self, A, client):
        job = _job_editor(A, "ed-cand-pin")
        r = client.post("/job/ed-cand-pin/segmento/1/usar-candidato", json={
            "provider": "pexels", "media_type": "video", "url": "https://pexels.com/video/1", "thumbnail": "https://t"})
        assert r.get_json()["modo"] == "post_url"
        assert job["pending_segments"][1]["override_source"] == {
            "source": "provider_url", "provider": "pexels", "value": "https://pexels.com/video/1"}

    def test_video_sem_post_usa_link_direto(self, A, client):
        job = _job_editor(A, "ed-cand-url")
        r = client.post("/job/ed-cand-url/segmento/1/usar-candidato", json={
            "provider": "magnific", "media_type": "video", "video_url": "https://cdn/v.mp4"})
        assert r.get_json()["modo"] == "url"
        assert job["pending_segments"][1]["override_source"]["value"] == "https://cdn/v.mp4"

    def test_sem_nada_pra_usar_da_400_e_trecho_inexistente_404(self, A, client):
        _job_editor(A, "ed-cand-erro")
        assert client.post("/job/ed-cand-erro/segmento/1/usar-candidato",
                           json={"provider": "magnific", "media_type": "video"}).status_code == 400
        assert client.post("/job/ed-cand-erro/segmento/9/usar-candidato", json={}).status_code == 404

    def test_busca_de_foto_devolve_link_da_imagem_original(self):
        from video_assembler import search_candidates

        class Foto:
            id = "1"; description = "d"; author = ""; url = "https://p"
            sizes = {"tiny": "https://t", "original": "https://o"}

        class Cli:
            def search_photos_all(self, query, max_pages=1):
                return [Foto()]

        class Fab:
            def get_photo_client(self, p):
                return Cli()

        c = search_candidates("bing", "x", media_type="image", site_cfg={}, client_factory=Fab())
        assert c[0]["image_url"] == "https://o" and c[0]["thumbnail"] == "https://t"


class TestEditorPagina:
    def test_editor_tem_animacao_transicoes_e_botao_usar(self, A, client):
        _job_editor(A, "ed-pagina")
        html = client.get("/job/ed-pagina/edit-segments?modo=classico").get_data(as_text=True)
        assert 'name="global_transition_type"' in html
        assert 'name="seg_0_transition"' in html and 'name="seg_1_transition"' in html
        assert 'name="seg_2_transition"' not in html  # o último trecho não tem "próximo"
        assert 'id="usar_candidato_btn_0"' in html
        assert 'class="kb-chip ativo" data-valor="in"' in html
        # trecho de foto: animação aparece mesmo no modo "buscar automaticamente"
        trecho0 = html[html.index('id="ken_burns_fields_0"'):][:200]
        assert "display:none" not in trecho0
        # seletor de banco de foto lista os buscadores
        assert '<option value="bing" selected>' in html

    def test_confirmar_guarda_transicoes_e_animacao(self, A, client, monkeypatch):
        job = _job_editor(A, "ed-confirma")
        capturado = {}
        monkeypatch.setattr(A, "_start_assembly", lambda jid, j, segs: capturado.setdefault("segs", segs))
        monkeypatch.setattr(A, "photo_api_configuration_error", lambda *a, **k: None)
        client.post("/job/ed-confirma/confirm-segments", data={
            "global_transition_type": "dissolve", "global_transition_duration": "0.8",
            "seg_0_transition": "wipeleft", "seg_0_transition_duration": "1.2",
            "seg_1_transition": "global", "seg_0_zoom_direction": "pan_left", "seg_0_focus_x": "0.2",
        })
        segs = capturado["segs"]
        assert segs[0].transition == "wipeleft" and segs[0].transition_duration == 1.2
        assert segs[1].transition is None
        assert segs[0].zoom_direction == "pan_left" and segs[0].focus_x == 0.2
        assert job["pending_segments"][0]["transition"] == "wipeleft"
        assert job["pending_segments"][0]["zoom_direction"] == "pan_left"
        cfg = A._job_site_cfg(job)
        assert cfg["transition_type"] == "dissolve" and cfg["transition_duration"] == 0.8

    def test_global_site_nao_mexe_na_config(self, A):
        job = _job_editor(A, "ed-site", editor_defaults={"transition_type": "site"})
        assert A._job_site_cfg(job)["transition_type"] == A.load_site_config()["transition_type"]


class TestPlanoDeTransicoes:
    def test_plano_usa_global_trecho_e_limita_duracao(self):
        from prompt_builder import VideoSegment
        from video_assembler import planejar_transicoes
        segs = [VideoSegment(0, 4, "pexels", "a"), VideoSegment(4, 5, "pexels", "b", transition="wipeleft"),
                VideoSegment(5, 9, "pexels", "c", transition="none"), VideoSegment(9, 12, "pexels", "d")]
        plano = planejar_transicoes(segs, "fade", 0.8)
        assert plano == [("fade", 0.5), ("wipeleft", 0.5), ("none", 0.0)]  # 0.5 = metade do trecho de 1s


class TestYoutubeAutomatico:
    def test_trecho_sem_escolha_usa_o_primeiro_resultado_do_comeco(self, A, monkeypatch):
        from prompt_builder import VideoSegment
        job = _job_editor(A, "ed-yt-auto", segs=[
            {"start": 0.0, "end": 6.5, "provider": "youtube", "query": "gojo", "media_type": "video", "override_source": None}])
        A._youtube_itens_sincronizar(job)
        job["youtube_itens"][0].update(status="pronto", resultados=[
            {"url": "https://yt/quebrado", "titulo": "A", "duracao_segundos": 100},
            {"url": "https://yt/bom", "titulo": "B", "duracao_segundos": 100, "miniatura_url": "m"}])
        baixados, cortes = [], []

        def baixar(url, pasta, *a, **k):
            baixados.append(url)
            if "quebrado" in url:
                raise A.YoutubeClipperError("indisponível")
            os.makedirs(pasta, exist_ok=True)
            p = os.path.join(pasta, "v.mp4"); open(p, "wb").write(b"v")
            return {"caminho": p}

        monkeypatch.setattr(A, "yt_baixar_video", baixar)
        monkeypatch.setattr(A, "yt_cortar_trecho", lambda s, a, b, out: (cortes.append((a, b)), open(out, "wb").write(b"c")))
        segs = [VideoSegment(0.0, 6.5, "youtube", "gojo")]
        assert A._youtube_escolher_automatico("ed-yt-auto", job, segs) == 1
        assert baixados == ["https://yt/quebrado", "https://yt/bom"]
        assert cortes == [(0.0, 6.5)]
        assert segs[0].override_source["source"] == "local_file"
        assert job["youtube_itens"][0]["escolha"]["automatico"] is True

    def test_caixa_desmarcada_nao_escolhe_nada(self, A, client):
        from prompt_builder import VideoSegment
        job = _job_editor(A, "ed-yt-off", segs=[
            {"start": 0.0, "end": 5.0, "provider": "youtube", "query": "x", "media_type": "video", "override_source": None}])
        assert client.post("/job/ed-yt-off/youtube/auto", json={"ativo": False}).get_json()["ativo"] is False
        assert A._youtube_escolher_automatico("ed-yt-off", job, [VideoSegment(0.0, 5.0, "youtube", "x")]) == 0

    def test_painel_tem_minimizar_termo_original_e_usar_primeiro(self, A, client):
        job = _job_editor(A, "ed-yt-painel", segs=[
            {"start": 0.0, "end": 5.0, "provider": "youtube", "query": "termo ia", "media_type": "video", "override_source": None}])
        A._youtube_itens_sincronizar(job)
        job["youtube_itens"][0].update(status="pronto", termo="outro termo")
        html = client.get("/job/ed-yt-painel/edit-segments?modo=classico").get_data(as_text=True)
        assert "ytAlternar('seg-0')" in html
        assert 'id="yt-original-seg-0"' in html and 'title="termo ia"' in html
        assert "ytUsarPrimeiro('seg-0')" in html
        assert 'id="yt-auto-escolha" checked' in html


class TestGaleria:
    def test_projetos_salvos_voltam_depois_de_reiniciar(self, A, monkeypatch, tmp_path):
        jobs_dir = tmp_path / "jobs"
        for jid, st in (("p1", {"status": "concluido"}), ("p2", {"status": "montando", "pending_segments": [{}]}),
                        ("p3", {"status": "transcrevendo"})):
            (jobs_dir / jid).mkdir(parents=True)
            (jobs_dir / jid / "state.json").write_text(json.dumps({"job_id": jid, **st}), encoding="utf-8")
        (jobs_dir / "lixo").mkdir()
        monkeypatch.setattr(A, "JOBS_DIR", str(jobs_dir))
        monkeypatch.setattr(A, "_JOBS", {})
        monkeypatch.delenv("NARRATION_SITE_NAO_CARREGAR_PROJETOS", raising=False)
        assert A._carregar_projetos_salvos() == 3
        assert A._JOBS["p1"]["status"] == "concluido"
        assert A._JOBS["p2"]["status"] == "pronto_para_editar" and "interrompida" in A._JOBS["p2"]["assembly_error"]
        assert A._JOBS["p3"]["status"] == "erro_transcricao"

    def test_renomear_e_apagar_remove_todos_os_arquivos(self, A, client, monkeypatch, tmp_path):
        jobs_dir, outputs = tmp_path / "jobs", tmp_path / "outputs"
        (jobs_dir / "proj-x" / "downloads").mkdir(parents=True)
        (jobs_dir / "proj-x" / "narracao.wav").write_bytes(b"a")
        (jobs_dir / "proj-x" / "downloads" / "c.mp4").write_bytes(b"c")
        outputs.mkdir()
        (outputs / "proj-x.mp4").write_bytes(b"v")
        (outputs / "proj-x_legendado.mp4").write_bytes(b"v")
        (outputs / "outro.mp4").write_bytes(b"v")
        monkeypatch.setattr(A, "JOBS_DIR", str(jobs_dir))
        monkeypatch.setattr(A, "OUTPUTS_DIR", str(outputs))
        A._JOBS["proj-x"] = {"job_id": "proj-x", "status": "concluido", "created_at": 5.0, "original_filename": "n.wav"}

        client.post("/jobs/proj-x/renomear", data={"nome": "Vídeo do Gojo"})
        assert A._JOBS["proj-x"]["nome_projeto"] == "Vídeo do Gojo"
        html = client.get("/jobs").get_data(as_text=True)
        assert "Vídeo do Gojo" in html and "Apagar projeto" in html

        r = client.post("/jobs/proj-x/apagar")
        assert r.status_code == 302
        assert "proj-x" not in A._JOBS
        assert not (jobs_dir / "proj-x").exists()
        assert sorted(os.listdir(outputs)) == ["outro.mp4"]

    def test_nao_apaga_projeto_em_andamento(self, A, client):
        A._JOBS["proj-rodando"] = {"job_id": "proj-rodando", "status": "montando", "created_at": 1.0}
        assert client.post("/jobs/proj-rodando/apagar").status_code == 409
        assert "proj-rodando" in A._JOBS
        A._JOBS.pop("proj-rodando")

    def test_projeto_concluido_pode_ser_editado_de_novo(self, A, client):
        _job_editor(A, "proj-concl")
        A._JOBS["proj-concl"]["status"] = "concluido"
        html = client.get("/jobs").get_data(as_text=True)
        assert "Editar de novo" in html
