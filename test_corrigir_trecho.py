"""
Erro real relatado: "Trecho 6: Não consegui ler a duração de
'...escolhas_editor/trecho5_02511f.avif': 'duration'". Os buscadores de
imagem servem muito .avif/.webp; a extensão .avif não estava na lista de
imagens, então o arquivo era tratado como VÍDEO e ia pro ffprobe.

Aqui: (1) toda imagem que não é JPEG/PNG de verdade vira .jpg antes de ir pro
ffmpeg; (2) o botão "🔧 Corrigir automaticamente" conserta sozinho o trecho que
derrubou a montagem; (3) trocar a mídia do trecho com erro limpa o aviso.
"""
import os
import subprocess

import pytest
from PIL import Image


def _avif(path):
    Image.new("RGB", (64, 36), (200, 30, 30)).save(path, "AVIF")
    return str(path)


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


@pytest.fixture
def client(A):
    return A.app.test_client()


def _job(A, job_id, override=None, media_type="image", provider="bing", query="gojo satoru domain expansion"):
    os.makedirs(A._job_dir(job_id), exist_ok=True)
    A._JOBS[job_id] = {
        "job_id": job_id, "status": "pronto_para_editar", "created_at": 1.0,
        "pending_segments": [{"start": 0.0, "end": 4.0, "provider": provider, "query": query,
                              "media_type": media_type, "override_source": override}],
        "segment_previews": [{"index": 0, "ok": True, "thumbnail_url": "x"}],
        "assembly_error": "Trecho 1: Não consegui ler a duração de 'x.avif': 'duration'",
        "assembly_error_segment_index": 0,
    }
    return A._JOBS[job_id]


class TestConversao:
    def test_avif_e_webp_viram_jpg_e_jpg_fica_como_esta(self, tmp_path):
        import video_assembler as va
        avif = _avif(tmp_path / "a.avif")
        webp = tmp_path / "w.webp"
        Image.new("RGBA", (40, 40), (0, 255, 0, 128)).save(webp, "WEBP")
        jpg = tmp_path / "j.jpg"
        Image.new("RGB", (40, 40)).save(jpg, "JPEG")
        for origem in (avif, str(webp)):
            novo = va.garantir_imagem_compativel(origem)
            assert novo.endswith(".jpg") and open(novo, "rb").read(3) == b"\xff\xd8\xff"
        assert va.garantir_imagem_compativel(str(jpg)) == str(jpg)

    def test_avif_com_extensao_errada_tambem_e_convertido(self, tmp_path):
        import video_assembler as va
        disfarcado = tmp_path / "foto.jpg"
        Image.new("RGB", (32, 32)).save(disfarcado, "AVIF")  # bytes AVIF, nome .jpg
        assert va.garantir_imagem_compativel(str(disfarcado)).endswith("_convertida.jpg")

    def test_arquivo_ilegivel_da_erro_claro(self, tmp_path):
        import video_assembler as va
        lixo = tmp_path / "x.avif"
        lixo.write_bytes(b"isso nao e imagem")
        with pytest.raises(va.VideoAssemblyError, match="Não consegui ler a imagem"):
            va.garantir_imagem_compativel(str(lixo))

    def test_override_avif_e_tratado_como_foto_mesmo_marcado_como_video(self, tmp_path):
        import video_assembler as va
        avif = _avif(tmp_path / "trecho5.avif")
        caminho, kind = va._resolve_override_source({"source": "local_file", "value": avif, "kind": "video"}, str(tmp_path), None)
        assert kind == "image" and caminho.endswith(".jpg")

    def test_montagem_com_trecho_avif_funciona(self, tmp_path, synthetic_audio):
        from prompt_builder import VideoSegment
        import video_assembler as va
        avif = _avif(tmp_path / "trecho5_02511f.avif")
        seg = VideoSegment(0.0, 9.469, "bing", "x", media_type="image",
                           override_source={"source": "local_file", "value": avif, "kind": "image"})
        out = va.assemble_video([seg], synthetic_audio, str(tmp_path / "o.mp4"), str(tmp_path / "w"),
                                site_cfg={"orientation": "16:9", "export_quality": "480p", "assembly_fetch_concurrency": 1})
        assert abs(va._probe_duration(out) - 9.469) < 0.3

    def test_baixar_imagem_ja_entrega_jpg(self, tmp_path, monkeypatch):
        import buscador_imagens_unificado as bu
        import unified_images.downloader as dl
        avif_bytes = open(_avif(tmp_path / "src.avif"), "rb").read()
        monkeypatch.setattr(dl, "fetch_url", lambda *a, **k: (avif_bytes, "image/avif"))
        p = bu.baixar_imagem(bu.ImagemBuscador(original_url="https://x/a.avif", engine="bing"), str(tmp_path / "out"))
        assert p.endswith(".jpg")


class TestBotaoCorrigir:
    def test_avif_escolhido_e_convertido_e_aviso_some(self, A, client, tmp_path):
        avif = _avif(tmp_path / "trecho5.avif")
        job = _job(A, "fix-avif", override={"source": "local_file", "value": avif, "kind": "video"})
        r = client.post("/job/fix-avif/corrigir-trecho", json={"indice": 0})
        d = r.get_json()
        assert r.status_code == 200 and "convertida pra JPG" in d["mensagem"]
        ov = job["pending_segments"][0]["override_source"]
        assert ov["value"].endswith(".jpg") and ov["kind"] == "image"
        assert job["assembly_error_segment_index"] is None and "assembly_error" not in job

    def test_arquivo_sumido_volta_pra_busca(self, A, client):
        job = _job(A, "fix-sumiu", override={"source": "local_file", "value": "/nao/existe.jpg"})
        d = client.post("/job/fix-sumiu/corrigir-trecho", json={"indice": 0}).get_json()
        assert "não existe mais" in d["mensagem"] and job["pending_segments"][0]["override_source"] is None

    def test_link_quebrado_volta_pra_busca(self, A, client):
        job = _job(A, "fix-link", override={"source": "url", "value": "https://x/quebrado.jpg"})
        client.post("/job/fix-link/corrigir-trecho", json={"indice": 0})
        assert job["pending_segments"][0]["override_source"] is None

    def test_foto_do_pexels_sem_chave_vira_buscador(self, A, client):
        job = _job(A, "fix-pexels", provider="pexels")
        d = client.post("/job/fix-pexels/corrigir-trecho", json={"indice": 0}).get_json()
        assert job["pending_segments"][0]["provider"] == "bing" and "buscadores" in d["mensagem"]

    def test_termo_longo_que_ninguem_achou_e_simplificado(self, A, client):
        job = _job(A, "fix-termo")
        job["imagens_buscadores"] = {"gojo satoru domain expansion": {"ok": False}}
        client.post("/job/fix-termo/corrigir-trecho", json={"indice": 0})
        assert job["pending_segments"][0]["query"] == "gojo satoru domain"
        assert "gojo satoru domain expansion" not in job["imagens_buscadores"]

    def test_video_ilegivel_e_reparado_ou_volta_pra_busca(self, A, client, tmp_path):
        ruim = tmp_path / "ruim.mp4"
        ruim.write_bytes(b"nao e video")
        job = _job(A, "fix-video", override={"source": "local_file", "value": str(ruim), "kind": "video"}, media_type="video")
        d = client.post("/job/fix-video/corrigir-trecho", json={"indice": 0}).get_json()
        assert job["pending_segments"][0]["override_source"] is None and "ilegível" in d["mensagem"]

    def test_formulario_do_editor_classico_redireciona(self, A, client, tmp_path):
        _job(A, "fix-form", override={"source": "local_file", "value": _avif(tmp_path / "a.avif")})
        r = client.post("/job/fix-form/corrigir-trecho", data={"indice": "0"})
        assert r.status_code == 302
        html = client.get("/job/fix-form/edit-segments?modo=classico").get_data(as_text=True)
        assert "convertida pra JPG" in html

    def test_botao_aparece_nos_dois_editores(self, A, client):
        _job(A, "fix-botao")
        assert "corrigir-auto" in client.get("/job/fix-botao/edit-segments?modo=estudio").get_data(as_text=True)
        assert "Corrigir automaticamente" in client.get("/job/fix-botao/edit-segments?modo=classico").get_data(as_text=True)

    def test_trocar_a_midia_do_trecho_com_erro_limpa_o_aviso(self, A, client, monkeypatch, tmp_path):
        job = _job(A, "fix-troca")
        import buscador_imagens_unificado as bu

        def fake(img, pasta, stem=None, **k):
            os.makedirs(pasta, exist_ok=True)
            p = os.path.join(pasta, stem + ".jpg")
            Image.new("RGB", (8, 8)).save(p, "JPEG")
            return p

        monkeypatch.setattr(bu, "baixar_imagem", fake)
        client.post("/job/fix-troca/segmento/0/usar-candidato", json={"provider": "bing", "media_type": "image", "image_url": "https://i/x.jpg"})
        assert job["assembly_error_segment_index"] is None and "assembly_error" not in job
