"""
Teste de webpage_animator.py — renderiza clipes de verdade (ffmpeg
real) a partir de imagens de teste com faixas de cor bem distintas, e
confirma o resultado por AMOSTRAGEM DE PIXEL em pontos específicos do
vídeo (mesma técnica usada em test_ken_burns_and_overrides.py) — não
só "rodou sem erro", mas "a câmera realmente foi pro lugar certo".
"""
import subprocess

import pytest
from PIL import Image

from video_assembler import VideoAssemblyError
from webpage_animator import renderizar_clipe_pagina


def _cor_no_tempo(video_path, t, pos=None):
    frame = video_path + f"._frame_{t}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(t), "-i", video_path, "-frames:v", "1", "-loglevel", "error", frame],
        check=True,
    )
    img = Image.open(frame).convert("RGB")
    x, y = pos if pos else (img.width // 2, img.height // 2)
    return img.getpixel((x, y))


@pytest.fixture
def pagina_com_faixas(tmp_path):
    """Imagem alta (1200x4000) com 4 faixas de cor bem distintas
    empilhadas -- vermelho, verde, azul, amarelo, nessa ordem de cima
    pra baixo -- pra confirmar por cor exatamente onde a câmera está
    olhando em cada momento."""
    caminho = tmp_path / "pagina_alta.png"
    img = Image.new("RGB", (1200, 4000), "white")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 1200, 1000], fill=(255, 0, 0))
    draw.rectangle([0, 1000, 1200, 2000], fill=(0, 255, 0))
    draw.rectangle([0, 2000, 1200, 3000], fill=(0, 0, 255))
    draw.rectangle([0, 3000, 1200, 4000], fill=(255, 255, 0))
    img.save(caminho)
    return str(caminho)


class TestModoScroll:
    def test_scroll_baixo_vai_do_topo_ao_fim(self, pagina_com_faixas, tmp_path):
        saida = str(tmp_path / "scroll.mp4")
        renderizar_clipe_pagina(
            pagina_com_faixas, saida, duracao=8, modo="scroll", direcao_scroll="baixo",
            target_width=640, target_height=360,
        )
        cor_inicio = _cor_no_tempo(saida, 0.2)
        cor_fim = _cor_no_tempo(saida, 7.8)
        assert cor_inicio[0] > 200 and cor_inicio[1] < 60 and cor_inicio[2] < 60  # vermelho (topo)
        assert cor_fim[0] > 200 and cor_fim[1] > 200 and cor_fim[2] < 60  # amarelo (fim)

    def test_scroll_cima_vai_do_fim_ao_topo(self, pagina_com_faixas, tmp_path):
        saida = str(tmp_path / "scroll.mp4")
        renderizar_clipe_pagina(
            pagina_com_faixas, saida, duracao=8, modo="scroll", direcao_scroll="cima",
            target_width=640, target_height=360,
        )
        cor_inicio = _cor_no_tempo(saida, 0.2)
        cor_fim = _cor_no_tempo(saida, 7.8)
        assert cor_inicio[0] > 200 and cor_inicio[1] > 200 and cor_inicio[2] < 60  # amarelo (fim)
        assert cor_fim[0] > 200 and cor_fim[1] < 60 and cor_fim[2] < 60  # vermelho (topo)

    def test_scroll_passa_pelo_meio_no_meio_do_tempo(self, pagina_com_faixas, tmp_path):
        """No meio do tempo, a câmera deveria estar em algum ponto
        intermediário (verde ou azul), não já no início nem no fim."""
        saida = str(tmp_path / "scroll.mp4")
        renderizar_clipe_pagina(
            pagina_com_faixas, saida, duracao=8, modo="scroll", direcao_scroll="baixo",
            target_width=640, target_height=360,
        )
        cor_meio = _cor_no_tempo(saida, 4.0)
        eh_vermelho = cor_meio[0] > 200 and cor_meio[1] < 60
        eh_amarelo = cor_meio[0] > 200 and cor_meio[1] > 200
        assert not eh_vermelho and not eh_amarelo, f"deveria estar no meio da rolagem, não nas pontas: {cor_meio}"

    def test_pagina_mais_curta_que_janela_nao_quebra(self, tmp_path):
        """Sem trecho nenhum pra rolar (a página inteira já cabe na
        janela final) -- não deve quebrar, usa barras pretas."""
        curta = tmp_path / "curta.png"
        Image.new("RGB", (1200, 300), (100, 200, 100)).save(curta)
        saida = str(tmp_path / "scroll_curto.mp4")
        renderizar_clipe_pagina(str(curta), saida, duracao=3, modo="scroll", target_width=640, target_height=360)
        assert (tmp_path / "scroll_curto.mp4").exists()
        assert (tmp_path / "scroll_curto.mp4").stat().st_size > 500

    def test_duracao_do_clipe_final_bate_com_o_pedido(self, pagina_com_faixas, tmp_path):
        from video_assembler import _probe_duration
        saida = str(tmp_path / "scroll.mp4")
        renderizar_clipe_pagina(pagina_com_faixas, saida, duracao=5.0, modo="scroll", target_width=640, target_height=360)
        assert abs(_probe_duration(saida) - 5.0) < 0.3


class TestModoFoco:
    def test_foco_mira_no_bloco_certo(self, pagina_com_faixas, tmp_path):
        """Bloco no meio da faixa azul (y=2000-3000) -- no meio da
        duração (fase de "segurar"), a câmera deveria estar mostrando
        azul ampliado."""
        bloco = {"x": 400, "y": 2400, "largura": 400, "altura": 200}
        saida = str(tmp_path / "foco.mp4")
        renderizar_clipe_pagina(
            pagina_com_faixas, saida, duracao=8, modo="foco", bloco=bloco,
            zoom_foco=1.8, duracao_movimento=1.0, duracao_afastamento=1.0,
            target_width=640, target_height=360,
        )
        cor_meio = _cor_no_tempo(saida, 4.0)
        assert cor_meio[2] > 200 and cor_meio[0] < 60, f"deveria estar mostrando a faixa azul: {cor_meio}"

    def test_foco_em_bloco_diferente_mira_em_lugar_diferente(self, pagina_com_faixas, tmp_path):
        bloco_verde = {"x": 400, "y": 1400, "largura": 400, "altura": 200}
        saida = str(tmp_path / "foco_verde.mp4")
        renderizar_clipe_pagina(
            pagina_com_faixas, saida, duracao=8, modo="foco", bloco=bloco_verde,
            zoom_foco=1.8, duracao_movimento=1.0, duracao_afastamento=1.0,
            target_width=640, target_height=360,
        )
        cor_meio = _cor_no_tempo(saida, 4.0)
        assert cor_meio[1] > 200 and cor_meio[0] < 60 and cor_meio[2] < 60, f"deveria estar mostrando a faixa verde: {cor_meio}"

    def test_efeito_highlight_renderiza_sem_erro(self, pagina_com_faixas, tmp_path):
        bloco = {"x": 400, "y": 2400, "largura": 400, "altura": 200}
        saida = tmp_path / "foco_highlight.mp4"
        renderizar_clipe_pagina(
            pagina_com_faixas, str(saida), duracao=6, modo="foco", bloco=bloco,
            efeito="highlight", cor_efeito=(255, 0, 255), target_width=640, target_height=360,
        )
        assert saida.exists() and saida.stat().st_size > 1000

    def test_efeito_dim_rest_renderiza_sem_erro(self, pagina_com_faixas, tmp_path):
        bloco = {"x": 400, "y": 2400, "largura": 400, "altura": 200}
        saida = tmp_path / "foco_dim.mp4"
        renderizar_clipe_pagina(
            pagina_com_faixas, str(saida), duracao=6, modo="foco", bloco=bloco,
            efeito="dim_rest", target_width=640, target_height=360,
        )
        assert saida.exists() and saida.stat().st_size > 1000

    def test_efeito_nunca_modifica_o_screenshot_original(self, pagina_com_faixas, tmp_path):
        bloco = {"x": 400, "y": 2400, "largura": 400, "altura": 200}
        saida = tmp_path / "foco_dim2.mp4"
        renderizar_clipe_pagina(
            pagina_com_faixas, str(saida), duracao=4, modo="foco", bloco=bloco,
            efeito="dim_rest", target_width=640, target_height=360,
        )
        original = Image.open(pagina_com_faixas).convert("RGB")
        assert original.getpixel((600, 2500)) == (0, 0, 255)  # ainda azul puro, sem overlay

    def test_arquivo_temporario_do_efeito_e_limpo_depois(self, pagina_com_faixas, tmp_path):
        import os
        bloco = {"x": 400, "y": 2400, "largura": 400, "altura": 200}
        saida = tmp_path / "foco_temp.mp4"
        renderizar_clipe_pagina(
            pagina_com_faixas, str(saida), duracao=4, modo="foco", bloco=bloco,
            efeito="highlight", target_width=640, target_height=360,
        )
        arquivos_restantes = os.listdir(tmp_path)
        assert not any("_efeito_tmp" in f for f in arquivos_restantes)


class TestValidacao:
    def test_modo_invalido_da_erro(self, pagina_com_faixas, tmp_path):
        with pytest.raises(VideoAssemblyError, match="modo"):
            renderizar_clipe_pagina(pagina_com_faixas, str(tmp_path / "x.mp4"), duracao=3, modo="invalido")

    def test_direcao_invalida_da_erro(self, pagina_com_faixas, tmp_path):
        with pytest.raises(VideoAssemblyError, match="direcao_scroll"):
            renderizar_clipe_pagina(pagina_com_faixas, str(tmp_path / "x.mp4"), duracao=3, direcao_scroll="lado")

    def test_efeito_invalido_da_erro(self, pagina_com_faixas, tmp_path):
        with pytest.raises(VideoAssemblyError, match="efeito"):
            renderizar_clipe_pagina(pagina_com_faixas, str(tmp_path / "x.mp4"), duracao=3, modo="foco",
                                     bloco={"x": 0, "y": 0, "largura": 10, "altura": 10}, efeito="brilho")

    def test_duracao_negativa_da_erro(self, pagina_com_faixas, tmp_path):
        with pytest.raises(VideoAssemblyError, match="duracao"):
            renderizar_clipe_pagina(pagina_com_faixas, str(tmp_path / "x.mp4"), duracao=-1)

    def test_foco_sem_bloco_da_erro(self, pagina_com_faixas, tmp_path):
        with pytest.raises(VideoAssemblyError, match="bloco"):
            renderizar_clipe_pagina(pagina_com_faixas, str(tmp_path / "x.mp4"), duracao=3, modo="foco")

    def test_bloco_incompleto_da_erro(self, pagina_com_faixas, tmp_path):
        with pytest.raises(VideoAssemblyError, match="largura"):
            renderizar_clipe_pagina(pagina_com_faixas, str(tmp_path / "x.mp4"), duracao=3, modo="foco",
                                     bloco={"x": 0, "y": 0})

    def test_screenshot_inexistente_da_erro(self, tmp_path):
        with pytest.raises(VideoAssemblyError, match="não encontrado"):
            renderizar_clipe_pagina("/nao/existe.png", str(tmp_path / "x.mp4"), duracao=3)
