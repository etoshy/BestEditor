"""
Teste automatizado de:
  - _render_image_with_ken_burns(): efeito de zoom em imagem, confirmado
    visualmente (não só que o comando roda sem erro).
  - _resolve_override_source(): os três tipos de fonte manual de um
    segmento (arquivo local, URL genérica, link de post de um provedor).
"""
import http.server
import os
import shutil
import subprocess
import threading

import pytest
from PIL import Image

from video_assembler import (
    VideoAssemblyError,
    _build_drawtext_filter,
    _download_generic_url,
    _infer_media_kind,
    _normalize_clip,
    _probe_duration,
    _render_image_with_ken_burns,
    _resolve_override_source,
)


def _count_red_pixels(video_path, at_seconds):
    frame = video_path + f"_frame_{at_seconds}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(at_seconds), "-i", video_path, "-frames:v", "1", "-loglevel", "error", frame],
        check=True,
    )
    img = Image.open(frame).convert("RGB")
    w, h = img.size
    count = 0
    for x in range(0, w, 4):
        for y in range(0, h, 4):
            r, g, b = img.getpixel((x, y))
            if r > 150 and g < 100 and b < 100:
                count += 1
    return count


@pytest.fixture
def centered_square_image(tmp_path):
    """Imagem azul com um quadrado vermelho pequeno bem no centro — dá
    pra medir objetivamente se um zoom no centro aumenta/diminui a área
    ocupada pelo quadrado ao longo do tempo.
    """
    img = Image.new("RGB", (800, 600), (0, 0, 255))
    size = 80
    cx, cy = 400, 300
    for x in range(cx - size // 2, cx + size // 2):
        for y in range(cy - size // 2, cy + size // 2):
            img.putpixel((x, y), (255, 0, 0))
    path = str(tmp_path / "test_image.png")
    img.save(path)
    return path


class TestKenBurnsEffect:
    def test_zoom_in_increases_central_element_over_time(self, tmp_path, centered_square_image):
        out = str(tmp_path / "out_zoom_in.mp4")
        _render_image_with_ken_burns(centered_square_image, 4.0, out, 640, 480, zoom_direction="in")

        assert abs(_probe_duration(out) - 4.0) < 0.2
        red_start = _count_red_pixels(out, 0.1)
        red_end = _count_red_pixels(out, 3.8)
        assert red_end > red_start * 1.3, "zoom in deveria aumentar o elemento central ao longo do tempo"

    def test_zoom_out_decreases_central_element_over_time(self, tmp_path, centered_square_image):
        out = str(tmp_path / "out_zoom_out.mp4")
        _render_image_with_ken_burns(centered_square_image, 4.0, out, 640, 480, zoom_direction="out")

        red_start = _count_red_pixels(out, 0.1)
        red_end = _count_red_pixels(out, 3.8)
        assert red_start > red_end * 1.3, "zoom out deveria começar maior e terminar menor"

    def test_rejects_invalid_focus(self, tmp_path, centered_square_image):
        with pytest.raises(VideoAssemblyError, match="focus_x"):
            _render_image_with_ken_burns(centered_square_image, 2.0, str(tmp_path / "x.mp4"), focus_x=1.5)

    def test_rejects_invalid_zoom_direction(self, tmp_path, centered_square_image):
        with pytest.raises(VideoAssemblyError, match="zoom_direction"):
            _render_image_with_ken_burns(centered_square_image, 2.0, str(tmp_path / "x.mp4"), zoom_direction="sideways")


class TestInferMediaKind:
    def test_image_extensions(self):
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            assert _infer_media_kind(f"foto{ext}") == "image"

    def test_video_extensions(self):
        for ext in (".mp4", ".mov", ".webm"):
            assert _infer_media_kind(f"video{ext}") == "video"

    def test_ignores_query_string(self):
        assert _infer_media_kind("https://x.com/foto.jpg?token=abc123") == "image"


class TestResolveOverrideSource:
    def test_local_file_video(self, tmp_path):
        video_path = str(tmp_path / "meu_video.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=100x100:rate=25:duration=1", "-loglevel", "error", video_path],
            check=True,
        )
        path, kind = _resolve_override_source({"source": "local_file", "value": video_path}, str(tmp_path), None)
        assert path == video_path and kind == "video"

    def test_local_file_image(self, tmp_path):
        image_path = str(tmp_path / "minha_foto.jpg")
        Image.new("RGB", (200, 150), (0, 128, 0)).save(image_path)
        _, kind = _resolve_override_source({"source": "local_file", "value": image_path}, str(tmp_path), None)
        assert kind == "image"

    def test_local_file_missing_raises_clear_error(self, tmp_path):
        with pytest.raises(VideoAssemblyError, match="não encontrado"):
            _resolve_override_source({"source": "local_file", "value": "/tmp/nao_existe_de_verdade.mp4"}, str(tmp_path), None)

    def test_unknown_source_raises_clear_error(self, tmp_path):
        with pytest.raises(VideoAssemblyError, match="desconhecido"):
            _resolve_override_source({"source": "teleporte_quantico", "value": "x"}, str(tmp_path), None)

    def test_provider_url_with_unsupported_provider_raises_clear_error(self, tmp_path):
        with pytest.raises(VideoAssemblyError, match="não suporta"):
            _resolve_override_source(
                {"source": "provider_url", "provider": "magnific", "value": "https://magnific.com/x"},
                str(tmp_path), lambda p: None,
            )

    def test_provider_url_with_supported_provider_resolves_and_downloads(self, tmp_path):
        downloaded_clip = str(tmp_path / "_downloaded.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=100x100:rate=25:duration=1", "-loglevel", "error", downloaded_clip],
            check=True,
        )

        calls = {"resolve": [], "download": []}

        class FakeVideo:
            id = "v1"

        class FakePexelsClient:
            def get_video_by_url(self, url):
                calls["resolve"].append(url)
                return FakeVideo()

            def download_video(self, video, output_dir):
                calls["download"].append(output_dir)
                return downloaded_clip

        path, kind = _resolve_override_source(
            {"source": "provider_url", "provider": "pexels", "value": "https://www.pexels.com/video/x-123/"},
            str(tmp_path), lambda p: FakePexelsClient(),
        )
        assert path == downloaded_clip and kind == "video"
        assert calls["resolve"] == ["https://www.pexels.com/video/x-123/"]

    def test_generic_url_network_error_becomes_clear_video_assembly_error(self, tmp_path):
        with pytest.raises(VideoAssemblyError, match="Falha ao baixar"):
            _resolve_override_source(
                {"source": "url", "value": "https://dominio-que-nao-existe-de-verdade-12345.com/x.mp4"},
                str(tmp_path), None,
            )


class TestGenericUrlDownloadWithRealHttpServer:
    """Sobe um servidor HTTP local de verdade (sem depender de rede
    externa) pra confirmar que o download genérico funciona com uma
    requisição HTTP real, não só mockada."""

    @pytest.fixture
    def local_http_server(self, tmp_path):
        video_path = tmp_path / "video_para_servir.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=100x100:rate=25:duration=1",
             "-loglevel", "error", str(video_path)],
            check=True,
        )

        handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(*args, directory=str(tmp_path), **kwargs)
        server = http.server.HTTPServer(("localhost", 0), handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield f"http://localhost:{port}/video_para_servir.mp4"
        server.shutdown()

    def test_downloads_real_file_over_http(self, tmp_path, local_http_server):
        dest_dir = str(tmp_path / "downloads")
        local_path = _download_generic_url(local_http_server, dest_dir)
        assert os.path.exists(local_path)
        assert abs(_probe_duration(local_path) - 1.0) < 0.2


class TestTransitionTypeEndToEnd:
    """assemble_video aplicando a transição configurada via site_cfg,
    de ponta a ponta (não só a função interna isolada) — a peça que
    faltava conectar depois de escrever `_concat_clips_with_transitions`."""

    def test_transicao_configurada_via_site_cfg_e_aplicada(self, tmp_path):
        from video_assembler import assemble_video, _probe_duration
        from prompt_builder import VideoSegment

        cores = ["red", "lime", "blue"]
        caminhos = []
        for i, cor in enumerate(cores):
            c = str(tmp_path / f"origem{i}.mp4")
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color={cor}:size=640x360:duration=3:rate=30",
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", c], capture_output=True, check=True)
            caminhos.append(c)

        segs = [
            VideoSegment(start=0.0, end=3.0, provider="pexels", query="x", override_source={"kind": "video", "source": "local_file", "value": caminhos[0]}),
            VideoSegment(start=3.0, end=6.0, provider="pexels", query="x", override_source={"kind": "video", "source": "local_file", "value": caminhos[1]}),
            VideoSegment(start=6.0, end=9.0, provider="pexels", query="x", override_source={"kind": "video", "source": "local_file", "value": caminhos[2]}),
        ]
        audio_teste = str(tmp_path / "audio.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "9", audio_teste], capture_output=True, check=True)
        saida = str(tmp_path / "final.mp4")

        assemble_video(segs, audio_teste, saida, work_dir=str(tmp_path), site_cfg={
            "transition_type": "fade", "transition_duration": 1.0, "orientation": "16:9", "export_quality": "480p",
        })

        # a duração continua a do áudio (9s): antes cada transição encurtava o
        # vídeo (9s - 2x1s = 7s) e o fim da narração era cortado; agora cada
        # clipe ganha um "rabo" do tamanho da transição seguinte.
        assert abs(_probe_duration(saida) - 9.0) < 0.5

        frame = str(tmp_path / "frame.png")
        subprocess.run(["ffmpeg", "-y", "-ss", "3.5", "-i", saida, "-frames:v", "1", "-loglevel", "error", frame], capture_output=True, check=True)
        cor = Image.open(frame).convert("RGB").getpixel((320, 180))
        assert not (cor[0] > 200 or cor[1] > 200)  # mistura vermelho+verde, nenhum puro

    def test_sem_transicao_configurada_comportamento_de_sempre(self, tmp_path):
        """transition_type="none" (padrão) continua com o corte seco de
        sempre -- sem regressão pra quem não mexeu nessa configuração."""
        from video_assembler import assemble_video, _probe_duration
        from prompt_builder import VideoSegment

        caminhos = []
        for i, cor in enumerate(["red", "lime"]):
            c = str(tmp_path / f"origem{i}.mp4")
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color={cor}:size=640x360:duration=3:rate=30",
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", c], capture_output=True, check=True)
            caminhos.append(c)

        segs = [
            VideoSegment(start=0.0, end=3.0, provider="pexels", query="x", override_source={"kind": "video", "source": "local_file", "value": caminhos[0]}),
            VideoSegment(start=3.0, end=6.0, provider="pexels", query="x", override_source={"kind": "video", "source": "local_file", "value": caminhos[1]}),
        ]
        audio_teste = str(tmp_path / "audio.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "6", audio_teste], capture_output=True, check=True)
        saida = str(tmp_path / "final.mp4")

        assemble_video(segs, audio_teste, saida, work_dir=str(tmp_path), site_cfg={
            "orientation": "16:9", "export_quality": "480p",
        })
        assert abs(_probe_duration(saida) - 6.0) < 0.3  # sem sobreposição nenhuma



    def test_mixed_video_and_ken_burns_image_segments_in_assemble_video(self, tmp_path, synthetic_audio):
        from prompt_builder import VideoSegment
        from video_assembler import assemble_video

        image_path = str(tmp_path / "minha_foto.jpg")
        Image.new("RGB", (800, 600), (0, 200, 0)).save(image_path)

        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=640x360:rate=25:duration=9.469",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        class FakeVideo:
            id = "v1"
            premium = False

        class FakeClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

        segments = [
            VideoSegment(start=0.0, end=4.5, provider="pexels", query="x"),
            VideoSegment(start=4.5, end=9.469, provider="pexels", query="ignorado", override_source={
                "kind": "image", "source": "local_file", "value": image_path, "zoom_direction": "in",
            }),
        ]
        output_path = str(tmp_path / "out" / "final.mp4")
        assemble_video(segments, synthetic_audio, output_path, str(tmp_path / "job"), get_client_fn=lambda p: FakeClient())

        def sample(path, t):
            frame = path + f"_f{t}.png"
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img = Image.open(frame).convert("RGB")
            w, h = img.size
            return img.getpixel((w // 2, h // 2))

        color_video_segment = sample(output_path, 2.0)
        color_image_segment = sample(output_path, 7.0)
        assert color_video_segment[2] > 100 and color_video_segment[0] < 50, "primeiro segmento deveria ser o vídeo azul"
        assert color_image_segment[1] > 100 and color_image_segment[0] < 50, "segundo segmento deveria ser a imagem verde"


class TestMediaTypeImageSegments:
    """Cobre `media_type='image'`: a IA pede uma foto (não vídeo) pra um
    segmento, o site busca de verdade via API de fotos e aplica Ken
    Burns automaticamente, coexistindo com segmentos de vídeo normais
    no mesmo vídeo final."""

    def test_image_segment_searches_photo_and_applies_ken_burns(self, tmp_path, synthetic_audio):
        from prompt_builder import VideoSegment
        from video_assembler import assemble_video, _probe_duration

        # imagem real com um quadrado vermelho no centro, pra confirmar zoom de verdade
        image_path = str(tmp_path / "foto.jpg")
        img = Image.new("RGB", (800, 600), (0, 0, 255))
        for x in range(360, 440):
            for y in range(260, 340):
                img.putpixel((x, y), (255, 0, 0))
        img.save(image_path)

        clip = str(tmp_path / "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=640x360:rate=25:duration=4.5",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True,
        )

        class FakeVideo:
            id = "v1"
            premium = False

        class FakePhoto:
            id = "p1"

        photo_search_calls = []

        class FakeClient:
            session = type("S", (), {"close": lambda self: None})()

            def search_all(self, query=None, category=None, max_pages=1, **kw):
                return [FakeVideo()]

            def download_video(self, video, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "d.mp4")
                shutil.copy(clip, dest)
                return dest

            def search_photos_all(self, query=None, max_pages=1, **kw):
                photo_search_calls.append(query)
                return [FakePhoto()]

            def download_photo(self, photo, output_dir, **kw):
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, "p.jpg")
                shutil.copy(image_path, dest)
                return dest

        segments = [
            VideoSegment(start=0.0, end=4.5, provider="pexels", query="dog", media_type="video"),
            VideoSegment(start=4.5, end=9.469, provider="pexels", query="vintage camera", media_type="image"),
        ]
        output_path = str(tmp_path / "out" / "final.mp4")
        assemble_video(segments, synthetic_audio, output_path, str(tmp_path / "job"), get_client_fn=lambda p: FakeClient())

        assert abs(_probe_duration(output_path) - 9.469) < 0.2
        assert photo_search_calls == ["vintage camera"], "deveria ter buscado foto só pro segmento de imagem"

        def count_red(path, t):
            frame = f"{path}_r{t}.png"
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", path, "-frames:v", "1", "-loglevel", "error", frame], check=True)
            img2 = Image.open(frame).convert("RGB")
            w, h = img2.size
            count = 0
            for x in range(0, w, 4):
                for y in range(0, h, 4):
                    r, g, b = img2.getpixel((x, y))
                    if r > 150 and g < 50:
                        count += 1
            return count

        red_start = count_red(output_path, 4.7)
        red_end = count_red(output_path, 9.2)
        assert red_start != red_end, "o segmento de imagem deveria ter zoom de verdade (Ken Burns), não ficar estático"

    def test_raises_clear_error_when_pexels_api_not_configured(self, tmp_path, monkeypatch):
        from prompt_builder import VideoSegment
        from video_assembler import ClientFactory, VideoAssemblyError, _download_image_segment_with_fallbacks

        monkeypatch.delenv("PEXELS_API_KEYS", raising=False)
        cfg = {"browser_shared_across_providers": False, "browser_visible": False, "browser_mode": "reuse_session"}
        factory = ClientFactory(cfg)
        segment = VideoSegment(start=0.0, end=3.0, provider="pexels", query="x", media_type="image")

        with pytest.raises(VideoAssemblyError, match="PEXELS_API_KEYS"):
            _download_image_segment_with_fallbacks(segment, str(tmp_path), factory)


# --------------------------------------------------------------------------- #
# Novas animações de foto: pan (sem zoom) e estático, além do zoom in/out
# que já existia — e a opção de desfoque (blur_sigma).
# --------------------------------------------------------------------------- #

def _mean_color_video(video_path, at_seconds):
    """Cor MÉDIA do quadro inteiro nesse instante -- mais sensível a
    movimento de câmera (pan) do que amostrar um pixel só, já que o
    ponto central pode ficar dentro da mesma faixa de cor mesmo com a
    câmera se movendo."""
    frame = video_path + f"_meanframe_{at_seconds}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(at_seconds), "-i", video_path, "-frames:v", "1", "-loglevel", "error", frame],
        capture_output=True, check=True,
    )
    import numpy as np
    arr = np.array(Image.open(frame).convert("RGB")).astype(float)
    return arr.mean(axis=(0, 1))


@pytest.fixture
def imagem_com_faixas_verticais(tmp_path):
    """Imagem larga com 3 faixas de cor VERTICAIS lado a lado --
    vermelho, verde, azul -- pra confirmar por cor média que um "pan"
    horizontal realmente se move de um lado pro outro."""
    from PIL import ImageDraw
    caminho = tmp_path / "faixas_verticais.png"
    img = Image.new("RGB", (1200, 800), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 400, 800], fill=(255, 0, 0))
    draw.rectangle([400, 0, 800, 800], fill=(0, 255, 0))
    draw.rectangle([800, 0, 1200, 800], fill=(0, 0, 255))
    img.save(caminho)
    return str(caminho)


class TestNovasAnimacoesDeFoto:
    def test_pan_left_vai_da_direita_pra_esquerda(self, imagem_com_faixas_verticais, tmp_path):
        saida = str(tmp_path / "pan_left.mp4")
        _render_image_with_ken_burns(imagem_com_faixas_verticais, 6, saida, target_width=640, target_height=360, zoom_direction="pan_left")
        c0 = _mean_color_video(saida, 0.2)
        c1 = _mean_color_video(saida, 5.8)
        assert c1[0] > c0[0]  # vermelho aumenta (a faixa vermelha, à esquerda, entra no quadro)
        assert c1[2] < c0[2]  # azul diminui (a faixa azul, à direita, sai do quadro)

    def test_pan_right_vai_da_esquerda_pra_direita(self, imagem_com_faixas_verticais, tmp_path):
        saida = str(tmp_path / "pan_right.mp4")
        _render_image_with_ken_burns(imagem_com_faixas_verticais, 6, saida, target_width=640, target_height=360, zoom_direction="pan_right")
        c0 = _mean_color_video(saida, 0.2)
        c1 = _mean_color_video(saida, 5.8)
        assert c1[2] > c0[2]  # azul aumenta
        assert c1[0] < c0[0]  # vermelho diminui

    def test_static_nao_se_move(self, imagem_com_faixas_verticais, tmp_path):
        saida = str(tmp_path / "static.mp4")
        _render_image_with_ken_burns(imagem_com_faixas_verticais, 4, saida, target_width=640, target_height=360, zoom_direction="static")
        c0 = _mean_color_video(saida, 0.2)
        c1 = _mean_color_video(saida, 3.8)
        assert abs(c0[0] - c1[0]) < 3 and abs(c0[1] - c1[1]) < 3 and abs(c0[2] - c1[2]) < 3

    def test_zoom_direction_invalido_da_erro(self, imagem_com_faixas_verticais, tmp_path):
        with pytest.raises(VideoAssemblyError, match="zoom_direction"):
            _render_image_with_ken_burns(imagem_com_faixas_verticais, 3, str(tmp_path / "x.mp4"), zoom_direction="diagonal")

    def test_blur_suaviza_a_borda_entre_cores(self, imagem_com_faixas_verticais, tmp_path):
        saida = str(tmp_path / "desfocado.mp4")
        _render_image_with_ken_burns(imagem_com_faixas_verticais, 3, saida, target_width=640, target_height=360, zoom_direction="static", blur_sigma=20)
        frame = saida + "_frame.png"
        subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", saida, "-frames:v", "1", "-loglevel", "error", frame], capture_output=True, check=True)
        cor = Image.open(frame).convert("RGB").getpixel((Image.open(frame).width // 3, Image.open(frame).height // 2))
        eh_vermelho_puro = cor[0] > 240 and cor[1] < 15
        eh_verde_puro = cor[1] > 240 and cor[0] < 15
        assert not eh_vermelho_puro and not eh_verde_puro

    def test_blur_zero_nao_aplica_filtro_nenhum(self, imagem_com_faixas_verticais, tmp_path):
        """blur_sigma=0 (padrão) continua com a borda nítida de sempre --
        não regride o comportamento existente pra quem não pediu blur."""
        saida = str(tmp_path / "sem_blur.mp4")
        _render_image_with_ken_burns(imagem_com_faixas_verticais, 3, saida, target_width=640, target_height=360, zoom_direction="static", blur_sigma=0)
        frame = saida + "_frame.png"
        subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", saida, "-frames:v", "1", "-loglevel", "error", frame], capture_output=True, check=True)
        img = Image.open(frame).convert("RGB")
        # amostra bem no MEIO de uma faixa (não perto de nenhuma borda,
        # pra não pegar um pixel de transição/reamostragem por acidente)
        cor = img.getpixel((img.width // 6, img.height // 2))
        assert cor[0] > 240 or cor[1] > 240 or cor[2] > 240

    def test_blur_negativo_da_erro(self, imagem_com_faixas_verticais, tmp_path):
        with pytest.raises(VideoAssemblyError, match="blur_sigma"):
            _render_image_with_ken_burns(imagem_com_faixas_verticais, 3, str(tmp_path / "x.mp4"), blur_sigma=-1)


class TestBlurEmClipesDeVideo:
    @pytest.fixture
    def video_com_faixas(self, tmp_path):
        caminho = str(tmp_path / "video_faixas.mp4")
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=red:size=640x360:duration=3",
            "-f", "lavfi", "-i", "color=blue:size=640x360:duration=3",
            "-filter_complex", "[0][1]hstack",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", caminho,
        ], capture_output=True, check=True)
        return caminho

    def test_blur_funciona_com_aspect_fill_black(self, video_com_faixas, tmp_path):
        saida = str(tmp_path / "normalizado_blur.mp4")
        _normalize_clip(video_com_faixas, 3, saida, target_width=640, target_height=360, aspect_fill="black", blur_sigma=15)
        frame = saida + "_frame.png"
        subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", saida, "-frames:v", "1", "-loglevel", "error", frame], capture_output=True, check=True)
        img = Image.open(frame).convert("RGB")
        cor_meio = img.getpixel((img.width // 2, img.height // 2))
        assert not (cor_meio[0] > 240 and cor_meio[2] < 15)
        assert not (cor_meio[2] > 240 and cor_meio[0] < 15)

    def test_blur_funciona_com_mosaico_e_texto_juntos(self, video_com_faixas, tmp_path):
        """Bug real encontrado e corrigido: o blur era descartado em
        silêncio quando aspect_fill="mosaic" E on_screen_text estavam
        presentes ao mesmo tempo (o código de inserção do texto
        reconstruía a string em volta do ponto errado). Confirma que
        os dois juntos realmente aplicam o blur."""
        com_blur = str(tmp_path / "mosaico_texto_blur.mp4")
        sem_blur = str(tmp_path / "mosaico_texto_sem_blur.mp4")
        _normalize_clip(video_com_faixas, 3, com_blur, target_width=640, target_height=360, aspect_fill="mosaic", on_screen_text="Teste", blur_sigma=15)
        _normalize_clip(video_com_faixas, 3, sem_blur, target_width=640, target_height=360, aspect_fill="mosaic", on_screen_text="Teste", blur_sigma=0)

        import numpy as np
        frame_com = com_blur + "_frame.png"
        frame_sem = sem_blur + "_frame.png"
        subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", com_blur, "-frames:v", "1", "-loglevel", "error", frame_com], capture_output=True, check=True)
        subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", sem_blur, "-frames:v", "1", "-loglevel", "error", frame_sem], capture_output=True, check=True)
        arr_com = np.array(Image.open(frame_com).convert("RGB")).astype(float)
        arr_sem = np.array(Image.open(frame_sem).convert("RGB")).astype(float)
        gradiente_com = np.abs(np.diff(arr_com, axis=1)).mean()
        gradiente_sem = np.abs(np.diff(arr_sem, axis=1)).mean()
        assert gradiente_com < gradiente_sem, "o blur deveria reduzir a nitidez das bordas mesmo com mosaico+texto"

    def test_blur_negativo_da_erro(self, video_com_faixas, tmp_path):
        with pytest.raises(VideoAssemblyError, match="blur_sigma"):
            _normalize_clip(video_com_faixas, 3, str(tmp_path / "x.mp4"), blur_sigma=-1)


# --------------------------------------------------------------------------- #
# Novas animações de texto: "slide" (desliza de uma direção) e "zoom"
# (cresce até o tamanho normal), além do "fade" que já existia.
# --------------------------------------------------------------------------- #

def _renderiza_com_filtro_texto(filtro, saida, duracao=3, tamanho="640x360"):
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=black:size={tamanho}:duration={duracao}",
        "-vf", filtro, "-c:v", "libx264", "-pix_fmt", "yuv420p", saida,
    ], capture_output=True, check=True)


def _posicao_media_do_texto(video_path, at_seconds):
    frame = video_path + f"_textpos_{at_seconds}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(at_seconds), "-i", video_path, "-frames:v", "1", "-loglevel", "error", frame],
        capture_output=True, check=True,
    )
    import numpy as np
    arr = np.array(Image.open(frame).convert("L"))
    ys, xs = (arr > 150).nonzero()
    if len(ys) == 0:
        return None, None
    return xs.mean(), ys.mean()


def _contagem_pixels_texto(video_path, at_seconds):
    frame = video_path + f"_textcount_{at_seconds}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(at_seconds), "-i", video_path, "-frames:v", "1", "-loglevel", "error", frame],
        capture_output=True, check=True,
    )
    import numpy as np
    arr = np.array(Image.open(frame).convert("L"))
    return int((arr > 150).sum())


class TestNovasAnimacoesDeTexto:
    def test_zoom_texto_comeca_pequeno_e_cresce(self, tmp_path):
        filtro = _build_drawtext_filter("TESTE", 360, {
            "animation": "zoom", "animation_duration": 0.8, "background": False, "font_size": 60,
        }, duration=3)
        saida = str(tmp_path / "anim_zoom.mp4")
        _renderiza_com_filtro_texto(filtro, saida)
        pixels_inicio = _contagem_pixels_texto(saida, 0.05)
        pixels_meio = _contagem_pixels_texto(saida, 1.5)
        assert pixels_meio > pixels_inicio * 1.5

    def test_slide_bottom_comeca_embaixo_e_sobe(self, tmp_path):
        filtro = _build_drawtext_filter("TESTE", 360, {
            "animation": "slide", "slide_direction": "bottom", "animation_duration": 0.8,
            "background": False, "position": "middle-center", "font_size": 60,
        }, duration=3)
        saida = str(tmp_path / "anim_slide_bottom.mp4")
        _renderiza_com_filtro_texto(filtro, saida)
        _, y_inicio = _posicao_media_do_texto(saida, 0.05)
        _, y_final = _posicao_media_do_texto(saida, 1.5)
        assert y_inicio > y_final  # Y maior = mais embaixo na imagem

    def test_slide_top_comeca_em_cima_e_desce(self, tmp_path):
        filtro = _build_drawtext_filter("TESTE", 360, {
            "animation": "slide", "slide_direction": "top", "animation_duration": 0.8,
            "background": False, "position": "middle-center", "font_size": 60,
        }, duration=3)
        saida = str(tmp_path / "anim_slide_top.mp4")
        _renderiza_com_filtro_texto(filtro, saida)
        _, y_inicio = _posicao_media_do_texto(saida, 0.05)
        _, y_final = _posicao_media_do_texto(saida, 1.5)
        assert y_inicio < y_final

    def test_slide_left_comeca_a_esquerda(self, tmp_path):
        filtro = _build_drawtext_filter("TESTE", 360, {
            "animation": "slide", "slide_direction": "left", "animation_duration": 0.8,
            "background": False, "position": "middle-center", "font_size": 60,
        }, duration=3)
        saida = str(tmp_path / "anim_slide_left.mp4")
        _renderiza_com_filtro_texto(filtro, saida)
        x_inicio, _ = _posicao_media_do_texto(saida, 0.05)
        x_final, _ = _posicao_media_do_texto(saida, 1.5)
        assert x_inicio < x_final

    def test_slide_right_comeca_a_direita(self, tmp_path):
        filtro = _build_drawtext_filter("TESTE", 360, {
            "animation": "slide", "slide_direction": "right", "animation_duration": 0.8,
            "background": False, "position": "middle-center", "font_size": 60,
        }, duration=3)
        saida = str(tmp_path / "anim_slide_right.mp4")
        _renderiza_com_filtro_texto(filtro, saida)
        x_inicio, _ = _posicao_media_do_texto(saida, 0.05)
        x_final, _ = _posicao_media_do_texto(saida, 1.5)
        assert x_inicio > x_final

    def test_slide_sem_direcao_usa_bottom_como_padrao(self, tmp_path):
        filtro = _build_drawtext_filter("TESTE", 360, {
            "animation": "slide", "animation_duration": 0.8,
            "background": False, "position": "middle-center", "font_size": 60,
        }, duration=3)
        saida = str(tmp_path / "anim_slide_padrao.mp4")
        _renderiza_com_filtro_texto(filtro, saida)
        _, y_inicio = _posicao_media_do_texto(saida, 0.05)
        _, y_final = _posicao_media_do_texto(saida, 1.5)
        assert y_inicio > y_final  # mesmo comportamento do "bottom" explícito

    def test_fade_continua_funcionando_sem_regressao(self, tmp_path):
        filtro = _build_drawtext_filter("TESTE", 360, {
            "animation": "fade", "animation_duration": 0.5, "background": False,
        }, duration=3)
        saida = str(tmp_path / "anim_fade.mp4")
        _renderiza_com_filtro_texto(filtro, saida)
        pixels_inicio = _contagem_pixels_texto(saida, 0.05)
        pixels_meio = _contagem_pixels_texto(saida, 1.5)
        assert pixels_meio > pixels_inicio * 2

    def test_sem_animacao_texto_aparece_direto(self, tmp_path):
        filtro = _build_drawtext_filter("TESTE", 360, {"background": False, "font_size": 60}, duration=3)
        saida = str(tmp_path / "sem_anim.mp4")
        _renderiza_com_filtro_texto(filtro, saida)
        pixels_inicio = _contagem_pixels_texto(saida, 0.05)
        assert pixels_inicio > 100  # já visível desde o primeiro frame, sem esperar nada


class TestCamposDeSegmentoSemOverride:
    """`zoom_direction`/`blur_sigma` do PRÓPRIO VideoSegment (sem
    override_source nenhum) precisam chegar até o ffmpeg -- antes só
    dava pra configurar isso via override; agora também são campos do
    segmento em si (uteis pro JSON gerado pela IA, não só pro editor
    manual)."""

    class _FakePhoto:
        id = "foto1"

    class _FakePhotoClient:
        def search_photos_all(self, query=None, max_pages=1, **kw):
            return [TestCamposDeSegmentoSemOverride._FakePhoto()]

        def download_photo(self, photo, output_dir, **kw):
            os.makedirs(output_dir, exist_ok=True)
            dest = os.path.join(output_dir, "foto.jpg")
            img = Image.new("RGB", (1200, 800), "white")
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.rectangle([0, 0, 400, 800], fill=(255, 0, 0))
            draw.rectangle([400, 0, 800, 800], fill=(0, 255, 0))
            draw.rectangle([800, 0, 1200, 800], fill=(0, 0, 255))
            img.save(dest)
            return dest

    def test_zoom_direction_e_blur_do_segmento_sao_aplicados(self, tmp_path):
        from video_assembler import assemble_video, _probe_duration
        from prompt_builder import VideoSegment
        import numpy as np

        seg = VideoSegment(
            start=0.0, end=4.0, provider="pexels", query="x", media_type="image",
            zoom_direction="pan_left", blur_sigma=10.0,
        )
        audio_teste = str(tmp_path / "audio.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "4", audio_teste], capture_output=True, check=True)
        saida = str(tmp_path / "final.mp4")

        assemble_video(
            [seg], audio_teste, saida, work_dir=str(tmp_path),
            get_client_fn=lambda provider: self._FakePhotoClient(),
        )
        assert abs(_probe_duration(saida) - 4.0) < 0.3

        def cor_media(t):
            frame = str(tmp_path / f"frame_{t}.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", saida, "-frames:v", "1", "-loglevel", "error", frame], capture_output=True, check=True)
            return np.array(Image.open(frame).convert("RGB")).astype(float).mean(axis=(0, 1))

        c0 = cor_media(0.2)
        c1 = cor_media(3.7)
        assert c1[0] != c0[0] or c1[2] != c0[2]  # pan_left do segmento (sem override) se moveu

    def test_override_tem_prioridade_sobre_o_campo_do_segmento(self, tmp_path):
        """Quando os DOIS existem (campo do segmento E override), o
        override vence -- é o comportamento intencional (override é a
        escolha deliberada e mais recente do editor)."""
        from video_assembler import assemble_video, _probe_duration
        from prompt_builder import VideoSegment
        import numpy as np

        imagem_override = str(tmp_path / "imagem_override.png")
        img = Image.new("RGB", (1200, 800), "white")
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 400, 800], fill=(255, 0, 0))
        draw.rectangle([400, 0, 800, 800], fill=(0, 255, 0))
        draw.rectangle([800, 0, 1200, 800], fill=(0, 0, 255))
        img.save(imagem_override)

        seg = VideoSegment(
            start=0.0, end=3.0, provider="pexels", query="x", media_type="image",
            zoom_direction="pan_left",  # o segmento pede pan_left...
            override_source={"kind": "image", "source": "local_file", "value": imagem_override, "zoom_direction": "static"},  # ...mas o override pede static
        )
        audio_teste = str(tmp_path / "audio.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "3", audio_teste], capture_output=True, check=True)
        saida = str(tmp_path / "final.mp4")

        assemble_video([seg], audio_teste, saida, work_dir=str(tmp_path))

        def cor_media(t):
            frame = str(tmp_path / f"frame_ov_{t}.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", saida, "-frames:v", "1", "-loglevel", "error", frame], capture_output=True, check=True)
            return np.array(Image.open(frame).convert("RGB")).astype(float).mean(axis=(0, 1))

        c0 = cor_media(0.2)
        c1 = cor_media(2.7)
        # "static" (do override) venceu -- a cor NÃO deveria mudar (se fosse pan_left do segmento, mudaria)
        assert abs(c1[0] - c0[0]) < 3 and abs(c1[2] - c0[2]) < 3


# --------------------------------------------------------------------------- #
# Transições entre clipes (crossfade/wipe/slide/etc via xfade) — antes
# só existia corte seco entre um trecho e outro.
# --------------------------------------------------------------------------- #

class TestTransicoesEntreClipes:
    @pytest.fixture
    def tres_clipes_coloridos(self, tmp_path):
        from video_assembler import VideoAssemblyError  # noqa: F401 -- só garante que o módulo já carregou
        cores = ["red", "lime", "blue"]
        caminhos, duracoes = [], []
        for i, cor in enumerate(cores):
            caminho = str(tmp_path / f"clipe{i}.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color={cor}:size=640x360:duration=3:rate=30",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", caminho],
                capture_output=True, check=True,
            )
            caminhos.append(caminho)
            duracoes.append(3.0)
        return caminhos, duracoes

    def _cor(self, video, t, tmp_path):
        frame = str(tmp_path / f"frame_transicao_{t}.png")
        subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", video, "-frames:v", "1", "-loglevel", "error", frame], capture_output=True, check=True)
        return Image.open(frame).convert("RGB").getpixel((320, 180))

    def test_transition_none_cai_pro_concat_rapido_de_sempre(self, tres_clipes_coloridos, tmp_path):
        from video_assembler import _concat_clips_with_transitions, _probe_duration
        caminhos, duracoes = tres_clipes_coloridos
        saida = str(tmp_path / "sem_transicao.mp4")
        _concat_clips_with_transitions(caminhos, duracoes, saida, str(tmp_path), transition_type="none")
        assert abs(_probe_duration(saida) - 9.0) < 0.3  # 3+3+3, sem sobreposição nenhuma

    def test_transition_fade_encurta_a_duracao_total(self, tres_clipes_coloridos, tmp_path):
        """Cada transição SOBREPÕE o fim de um clipe com o início do
        próximo -- a duração final é menor que a soma simples."""
        from video_assembler import _concat_clips_with_transitions, _probe_duration
        caminhos, duracoes = tres_clipes_coloridos
        saida = str(tmp_path / "com_fade.mp4")
        _concat_clips_with_transitions(caminhos, duracoes, saida, str(tmp_path), transition_type="fade", transition_duration=1.0)
        assert abs(_probe_duration(saida) - 7.0) < 0.3  # 9s - 2 transições de 1s

    def test_transition_realmente_mistura_as_cores(self, tres_clipes_coloridos, tmp_path):
        from video_assembler import _concat_clips_with_transitions
        caminhos, duracoes = tres_clipes_coloridos
        saida = str(tmp_path / "com_fade.mp4")
        _concat_clips_with_transitions(caminhos, duracoes, saida, str(tmp_path), transition_type="fade", transition_duration=1.0)

        vermelho = self._cor(saida, 1.0, tmp_path)
        transicao = self._cor(saida, 2.5, tmp_path)
        verde = self._cor(saida, 3.5, tmp_path)

        assert vermelho[0] > 200 and vermelho[1] < 30
        assert verde[1] > 200 and verde[0] < 30
        # no meio da transição, nem puro vermelho nem puro verde
        assert not (transicao[0] > 200 or transicao[1] > 200)

    @pytest.mark.parametrize("tipo", ["wipeleft", "wiperight", "slideup", "slidedown", "circleopen", "dissolve", "fadeblack"])
    def test_varios_tipos_de_transicao_renderizam_com_duracao_correta(self, tres_clipes_coloridos, tmp_path, tipo):
        from video_assembler import _concat_clips_with_transitions, _probe_duration
        caminhos, duracoes = tres_clipes_coloridos
        saida = str(tmp_path / f"transicao_{tipo}.mp4")
        _concat_clips_with_transitions(caminhos, duracoes, saida, str(tmp_path), transition_type=tipo, transition_duration=0.5)
        assert abs(_probe_duration(saida) - 8.0) < 0.3  # 9s - 2 transições de 0.5s

    # as 200 do catálogo DarkPlanner ("dp:...") são testadas em baixa resolução em test_dp_completo.py
    @pytest.mark.parametrize("tipo", sorted(t for t in __import__("video_assembler").TRANSICOES_VALIDAS - {"none"} if not t.startswith("dp:")))
    def test_toda_transicao_nativa_do_xfade_renderiza_de_verdade(self, tres_clipes_coloridos, tmp_path, tipo):
        # as 58 transições nativas do filtro `xfade` do ffmpeg instalado
        # -- não só as 7 checadas acima com mais detalhe. Isso pega na
        # hora qualquer nome digitado errado ou incompatível com a
        # versão do ffmpeg do ambiente (o ffmpeg REJEITA um nome de
        # transição desconhecido, então isso é um teste real, não só
        # de forma).
        from video_assembler import _concat_clips_with_transitions, _probe_duration
        caminhos, duracoes = tres_clipes_coloridos
        saida = str(tmp_path / f"transicao_{tipo}.mp4")
        _concat_clips_with_transitions(caminhos, duracoes, saida, str(tmp_path), transition_type=tipo, transition_duration=0.4)
        assert abs(_probe_duration(saida) - 8.2) < 0.3  # 9s - 2 transições de 0.4s
        assert os.path.getsize(saida) > 0


    def test_transicao_maior_que_metade_do_clipe_curto_e_limitada_automaticamente(self, tmp_path):
        from video_assembler import _concat_clips_with_transitions, _probe_duration
        curto = str(tmp_path / "curto.mp4")
        longo = str(tmp_path / "longo.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=640x360:duration=1:rate=30", "-c:v", "libx264", "-pix_fmt", "yuv420p", curto], capture_output=True, check=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=lime:size=640x360:duration=3:rate=30", "-c:v", "libx264", "-pix_fmt", "yuv420p", longo], capture_output=True, check=True)
        saida = str(tmp_path / "limitada.mp4")
        # pede 2s de transição num clipe de só 1s -- não deveria "comer" o clipe inteiro
        _concat_clips_with_transitions([curto, longo], [1.0, 3.0], saida, str(tmp_path), transition_type="fade", transition_duration=2.0)
        assert _probe_duration(saida) > 3.0

    def test_um_clipe_so_nao_precisa_de_transicao_nenhuma(self, tmp_path):
        from video_assembler import _concat_clips_with_transitions, _probe_duration
        unico = str(tmp_path / "unico.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=640x360:duration=3:rate=30", "-c:v", "libx264", "-pix_fmt", "yuv420p", unico], capture_output=True, check=True)
        saida = str(tmp_path / "saida_unico.mp4")
        _concat_clips_with_transitions([unico], [3.0], saida, str(tmp_path), transition_type="fade")
        assert abs(_probe_duration(saida) - 3.0) < 0.3

    def test_tipo_de_transicao_invalido_da_erro(self, tres_clipes_coloridos, tmp_path):
        from video_assembler import _concat_clips_with_transitions
        caminhos, duracoes = tres_clipes_coloridos
        with pytest.raises(VideoAssemblyError, match="transition_type"):
            _concat_clips_with_transitions(caminhos, duracoes, str(tmp_path / "x.mp4"), str(tmp_path), transition_type="giratoria-3d")

    def test_quantidade_de_duracoes_diferente_da_quantidade_de_clipes_da_erro(self, tres_clipes_coloridos, tmp_path):
        from video_assembler import _concat_clips_with_transitions
        caminhos, duracoes = tres_clipes_coloridos
        with pytest.raises(VideoAssemblyError, match="mesmo tamanho"):
            _concat_clips_with_transitions(caminhos, duracoes[:2], str(tmp_path / "x.mp4"), str(tmp_path), transition_type="fade")


class TestTransicoesCustomizadas:
    """As 5 transições NOVAS (modo `custom` do xfade, sem depender de
    nenhum shader/asset) -- confirma o PADRÃO VISUAL de cada uma, não só
    que ela renderiza sem erro (isso já é coberto acima, junto com as
    nativas, pelo parametrize de TRANSICOES_VALIDAS)."""

    @pytest.fixture
    def dois_clipes(self, tmp_path):
        caminhos, duracoes = [], []
        for i, cor in enumerate(["red", "lime"]):
            caminho = str(tmp_path / f"cor{i}.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color={cor}:size=320x240:duration=2:rate=10",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", caminho],
                capture_output=True, check=True,
            )
            caminhos.append(caminho)
            duracoes.append(2.0)
        return caminhos, duracoes

    def _frame_meio(self, saida, tmp_path):
        frame = str(tmp_path / "frame_meio_custom.png")
        subprocess.run(["ffmpeg", "-y", "-ss", "1.5", "-i", saida, "-frames:v", "1", "-loglevel", "error", frame], capture_output=True, check=True)
        return Image.open(frame).convert("RGB")

    def _verde_dominante(self, img, x, y):
        r, g, b = img.getpixel((x, y))
        return g > r

    def _renderizar(self, dois_clipes, tmp_path, tipo):
        from video_assembler import _concat_clips_with_transitions
        caminhos, duracoes = dois_clipes
        saida = str(tmp_path / f"custom_{tipo}.mp4")
        _concat_clips_with_transitions(caminhos, duracoes, saida, str(tmp_path), transition_type=tipo, transition_duration=1.0)
        return saida

    def test_blinds_h_faz_faixas_horizontais_alternadas(self, dois_clipes, tmp_path):
        saida = self._renderizar(dois_clipes, tmp_path, "blinds_h")
        img = self._frame_meio(saida, tmp_path)
        resultados = [self._verde_dominante(img, 160, y) for y in range(0, 240, 5)]
        # no meio da transição tem que ter MISTURA (nem tudo verde, nem tudo vermelho) --
        # e trocar de valor mais de uma vez ao longo do eixo Y (padrão listrado, não um bloco só)
        assert 0 < sum(resultados) < len(resultados)
        trocas = sum(1 for i in range(1, len(resultados)) if resultados[i] != resultados[i - 1])
        assert trocas >= 4

    def test_blinds_v_faz_faixas_verticais_alternadas(self, dois_clipes, tmp_path):
        saida = self._renderizar(dois_clipes, tmp_path, "blinds_v")
        img = self._frame_meio(saida, tmp_path)
        resultados = [self._verde_dominante(img, x, 120) for x in range(0, 320, 5)]
        assert 0 < sum(resultados) < len(resultados)
        trocas = sum(1 for i in range(1, len(resultados)) if resultados[i] != resultados[i - 1])
        assert trocas >= 4

    def test_checkerboard_faz_padrao_xadrez(self, dois_clipes, tmp_path):
        saida = self._renderizar(dois_clipes, tmp_path, "checkerboard")
        img = self._frame_meio(saida, tmp_path)
        # amostra uma grade 2D -- tem que ter mistura nas duas direções
        linha_0 = [self._verde_dominante(img, x, 15) for x in range(0, 320, 30)]
        linha_1 = [self._verde_dominante(img, x, 45) for x in range(0, 320, 30)]
        assert 0 < sum(linha_0) < len(linha_0) or 0 < sum(linha_1) < len(linha_1)
        assert linha_0 != linha_1  # padrão xadrez -- linhas adjacentes não iguais

    def test_noise_dissolve_mistura_sem_padrao_geometrico_obvio(self, dois_clipes, tmp_path):
        saida = self._renderizar(dois_clipes, tmp_path, "noise_dissolve")
        img = self._frame_meio(saida, tmp_path)
        resultados = [self._verde_dominante(img, x, 120) for x in range(0, 320, 5)]
        assert 0 < sum(resultados) < len(resultados)  # mistura de verdade, não tudo uma cor só

    def test_iris_blur_e_mais_revelado_no_centro_ou_na_borda_de_forma_consistente(self, dois_clipes, tmp_path):
        saida = self._renderizar(dois_clipes, tmp_path, "iris_blur")
        img = self._frame_meio(saida, tmp_path)
        centro = self._verde_dominante(img, 160, 120)
        cantos = [self._verde_dominante(img, x, y) for x, y in [(5, 5), (315, 5), (5, 235), (315, 235)]]
        # a íris é radial -- o centro tem que estar num estado DIFERENTE
        # dos 4 cantos (todos iguais entre si) no meio da transição
        assert all(c == cantos[0] for c in cantos)
        assert centro != cantos[0]

    def test_transicoes_customizadas_tambem_respeitam_o_limite_de_duracao(self, dois_clipes, tmp_path):
        from video_assembler import _concat_clips_with_transitions, _probe_duration
        caminhos, duracoes = dois_clipes  # 2s cada
        saida = str(tmp_path / "custom_limite.mp4")
        # pede 5s de transição -- tem que ser limitada a metade do clipe mais curto (1s)
        _concat_clips_with_transitions(caminhos, duracoes, saida, str(tmp_path), transition_type="blinds_h", transition_duration=5.0)
        assert abs(_probe_duration(saida) - 3.0) < 0.2  # 4s - 1s de transição (não 4s - 5s, que seria negativo)

    def test_diamond_iris_e_mais_revelado_no_centro_ou_na_borda_de_forma_consistente(self, dois_clipes, tmp_path):
        saida = self._renderizar(dois_clipes, tmp_path, "diamond_iris")
        img = self._frame_meio(saida, tmp_path)
        centro = self._verde_dominante(img, 160, 120)
        cantos = [self._verde_dominante(img, x, y) for x, y in [(5, 5), (315, 5), (5, 235), (315, 235)]]
        # losango -- igual à íris circular, o centro tem que estar num estado
        # DIFERENTE dos 4 cantos (todos iguais entre si) no meio da transição
        assert all(c == cantos[0] for c in cantos)
        assert centro != cantos[0]

    def test_diamond_iris_tem_forma_de_losango_e_nao_de_circulo(self, dois_clipes, tmp_path):
        # o teste acima (centro vs cantos) não diferencia losango de círculo --
        # os dois têm esse mesmo padrão radial, e ao longo da linha centro-canto
        # os dois dão exatamente a mesma distância normalizada (por construção).
        # A diferença real aparece fora dessa linha: no eixo horizontal puro, o
        # losango "incha" mais rápido que o círculo (é mais largo ali relativo
        # ao próprio tamanho), então um ponto nesse eixo revela bem mais cedo
        # no losango do que no círculo -- confirmado empiricamente antes de
        # escrever esta asserção.
        saida_losango = self._renderizar(dois_clipes, tmp_path, "diamond_iris")
        saida_circulo = self._renderizar(dois_clipes, tmp_path, "iris_blur")
        img_losango = self._frame_meio(saida_losango, tmp_path)
        img_circulo = self._frame_meio(saida_circulo, tmp_path)
        x, y = 270, 120  # no eixo horizontal, fora da diagonal centro-canto
        losango_revelado = self._verde_dominante(img_losango, x, y)
        circulo_revelado = self._verde_dominante(img_circulo, x, y)
        assert losango_revelado and not circulo_revelado

    def test_pinwheel_faz_padrao_de_lâminas_alternadas_ao_redor_do_centro(self, dois_clipes, tmp_path):
        saida = self._renderizar(dois_clipes, tmp_path, "pinwheel")
        img = self._frame_meio(saida, tmp_path)
        # amostra 12 pontos num círculo ao redor do centro -- girando em torno
        # do centro tem que alternar entre as duas cores várias vezes (lâminas),
        # não ficar tudo de uma cor só (o que indicaria que o cata-vento não girou)
        import math
        cx, cy, raio = 160, 120, 80
        resultados = []
        for i in range(12):
            ang = 2 * math.pi * i / 12
            x = int(cx + raio * math.cos(ang))
            y = int(cy + raio * math.sin(ang))
            resultados.append(self._verde_dominante(img, x, y))
        assert 0 < sum(resultados) < len(resultados)
        trocas = sum(1 for i in range(len(resultados)) if resultados[i] != resultados[i - 1])
        assert trocas >= 4  # várias lâminas -- várias trocas ao redor do círculo

    def test_wave_wipe_tem_borda_ondulada_nao_reta(self, dois_clipes, tmp_path):
        saida = self._renderizar(dois_clipes, tmp_path, "wave_wipe")
        img = self._frame_meio(saida, tmp_path)
        # numa varredura de borda RETA, a mesma coluna X teria a mesma cor em
        # qualquer Y. Como a borda é ondulada, colunas próximas ao limite da
        # onda têm que MUDAR de cor dependendo do Y (a onda cruza a borda
        # nesse X em alguns Y e não em outros)
        trocas_por_coluna = []
        for x in range(120, 200, 10):
            resultados = [self._verde_dominante(img, x, y) for y in range(0, 240, 15)]
            trocas_por_coluna.append(sum(1 for i in range(1, len(resultados)) if resultados[i] != resultados[i - 1]))
        assert max(trocas_por_coluna) >= 2

    def test_fade_grayscale_fica_mais_neutro_no_meio_da_transicao_do_que_dissolve_comum(self, dois_clipes, tmp_path):
        from video_assembler import _concat_clips_with_transitions
        caminhos, duracoes = dois_clipes
        saida_cinza = str(tmp_path / "custom_fade_grayscale.mp4")
        saida_comum = str(tmp_path / "custom_dissolve.mp4")
        _concat_clips_with_transitions(caminhos, duracoes, saida_cinza, str(tmp_path), transition_type="fade_grayscale", transition_duration=1.0)
        _concat_clips_with_transitions(caminhos, duracoes, saida_comum, str(tmp_path), transition_type="dissolve", transition_duration=1.0)
        img_cinza = self._frame_meio(saida_cinza, tmp_path)
        # _frame_meio sempre extrai em ss=1.5 -- reaproveita pro dissolve comum também
        import subprocess
        frame_comum = str(tmp_path / "frame_meio_dissolve.png")
        subprocess.run(["ffmpeg", "-y", "-ss", "1.5", "-i", saida_comum, "-frames:v", "1", "-loglevel", "error", frame_comum], capture_output=True, check=True)
        from PIL import Image
        img_comum = Image.open(frame_comum).convert("RGB")
        r1, g1, b1 = img_cinza.getpixel((160, 120))
        r2, g2, b2 = img_comum.getpixel((160, 120))
        # "neutralidade" = o quão perto os 3 canais estão uns dos outros
        neutralidade_cinza = max(r1, g1, b1) - min(r1, g1, b1)
        neutralidade_comum = max(r2, g2, b2) - min(r2, g2, b2)
        assert neutralidade_cinza < neutralidade_comum

