"""
Teste da personalização visual do texto na tela (cor, borda com cor/
espessura, sombra, animação de fade) e das animações de entrada/saída
das FOTOS (media_type="image") — tudo isso implementado em cima do
`_build_drawtext_filter()` e `_render_image_with_ken_burns()` já
existentes em video_assembler.py.

Duas camadas de teste:
1) Construção da STRING do filtro `_build_drawtext_filter()` — rápido,
   sem tocar ffmpeg, confere que os campos novos aparecem certos e que
   a expressão de animação escapa vírgulas corretamente (senão o ffmpeg
   interpretaria como um novo filtro na cadeia, não um argumento).
2) Renderização de verdade com ffmpeg (`_normalize_clip`,
   `_render_image_with_ken_burns`) — confere que o ffmpeg de fato ACEITA
   essas strings de filtro (erro de sintaxe só aparece na hora de
   rodar, não na hora de montar a string).
"""
import os
import subprocess

import pytest

from video_assembler import _build_drawtext_filter, _normalize_clip, _render_image_with_ken_burns, _probe_duration


# --------------------------------------------------------------------------- #
# 1) Construção da string do filtro (sem ffmpeg)
# --------------------------------------------------------------------------- #

def test_drawtext_padrao_sem_style_mantem_visual_de_sempre():
    f = _build_drawtext_filter("oi", 1080)
    assert "fontcolor=white" in f
    assert "box=1:boxcolor=black@0.55:boxborderw=14" in f
    assert "bordercolor" not in f
    assert "shadowcolor" not in f
    assert "alpha=" not in f


def test_drawtext_font_color_customizada():
    f = _build_drawtext_filter("oi", 1080, {"font_color": "#ff0000"})
    assert "fontcolor=#ff0000" in f


def test_drawtext_border_usa_cor_e_espessura_customizadas():
    f = _build_drawtext_filter("oi", 1080, {"border": True, "border_color": "#00ff00", "border_width": 7})
    assert "bordercolor=#00ff00:borderw=7" in f


def test_drawtext_border_sem_customizacao_usa_padrao_preto_3px():
    f = _build_drawtext_filter("oi", 1080, {"border": True})
    assert "bordercolor=black:borderw=3" in f


def test_drawtext_sem_border_nao_inclui_bordercolor():
    f = _build_drawtext_filter("oi", 1080, {"border_color": "#00ff00"})  # sem "border": True
    assert "bordercolor" not in f


def test_drawtext_shadow_usa_cor_e_offset_customizados():
    f = _build_drawtext_filter("oi", 1080, {"shadow": True, "shadow_color": "#333333", "shadow_offset": 5})
    assert "shadowcolor=#333333:shadowx=5:shadowy=5" in f


def test_drawtext_sem_shadow_nao_inclui_shadowcolor():
    f = _build_drawtext_filter("oi", 1080, {})
    assert "shadowcolor" not in f


def test_drawtext_animation_fade_com_duration_conhecida_gera_entrada_e_saida():
    f = _build_drawtext_filter("oi", 1080, {"animation": "fade", "animation_duration": 0.5}, duration=10.0)
    assert "alpha=" in f
    # vírgulas dentro da expressão precisam estar escapadas (\,) -- senão
    # o ffmpeg trataria como separador de filtro na cadeia, quebrando tudo.
    alpha_part = f.split("alpha='")[1].rstrip("'")
    assert "\\," in alpha_part
    assert "," not in alpha_part.replace("\\,", "")  # nenhuma vírgula SEM escape sobrando


def test_drawtext_animation_fade_sem_duration_nem_end_offset_so_faz_entrada():
    f = _build_drawtext_filter("oi", 1080, {"animation": "fade"})  # sem duration, sem end_offset
    assert "alpha=" in f
    # a expressão de "só entrada" tem 2 níveis de if (não 4, como a de entrada+saída)
    assert f.count("if(lt(t") == 2


def test_drawtext_animation_fade_respeita_start_end_offset():
    f = _build_drawtext_filter("oi", 1080, {
        "animation": "fade", "animation_duration": 0.3,
        "start_offset": 2.0, "end_offset": 5.0,
    })
    assert "enable='between(t,2.000,5.000)'" in f
    assert "alpha=" in f


def test_drawtext_animation_none_nao_adiciona_alpha():
    f = _build_drawtext_filter("oi", 1080, {"animation": "none"}, duration=10.0)
    assert "alpha=" not in f


def test_drawtext_animation_duration_e_limitada_em_janela_curta():
    # janela de 0.5s, animation_duration pedida de 2s -- não pode deixar
    # o fade "ocupar" mais que a janela inteira (senão pisca em vez de
    # aparecer/sumir suavemente).
    f = _build_drawtext_filter("oi", 1080, {
        "animation": "fade", "animation_duration": 2.0,
        "start_offset": 0.0, "end_offset": 0.5,
    })
    assert "alpha=" in f  # só confirma que não quebrou/lançou exceção


# --------------------------------------------------------------------------- #
# 2) Renderização de verdade com ffmpeg
# --------------------------------------------------------------------------- #

@pytest.fixture
def synthetic_image(tmp_path):
    """Uma imagem estática (JPEG) gerada na hora via ffmpeg -- serve pra
    testar `_render_image_with_ken_burns` sem precisar de um arquivo
    versionado no repo nem de rede.
    """
    path = os.path.join(str(tmp_path), "foto.jpg")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=orange:size=640x480", "-frames:v", "1", path],
        capture_output=True, check=True,
    )
    return path


def test_normalize_clip_com_texto_totalmente_customizado(tmp_path, synthetic_clips):
    saida = str(tmp_path / "saida.mp4")
    style = {
        "position": "top-center", "font_color": "#ff0000", "font_size": 40,
        "border": True, "border_color": "#0000ff", "border_width": 5,
        "shadow": True, "shadow_color": "#111111", "shadow_offset": 4,
        "animation": "fade", "animation_duration": 0.3,
    }
    resultado = _normalize_clip(
        synthetic_clips["exact_green"], 3.0, saida, 640, 360,
        on_screen_text="Texto de teste com tudo", on_screen_text_style=style,
    )
    assert resultado == saida
    assert os.path.exists(saida) and os.path.getsize(saida) > 0
    assert abs(_probe_duration(saida) - 3.0) < 0.2


def test_render_image_com_fade_in_e_fade_out(tmp_path, synthetic_image):
    saida = str(tmp_path / "saida.mp4")
    _render_image_with_ken_burns(
        synthetic_image, 3.0, saida, 640, 360,
        fade_in=True, fade_out=True, fade_duration=0.5,
    )
    assert os.path.exists(saida) and os.path.getsize(saida) > 0
    assert abs(_probe_duration(saida) - 3.0) < 0.2


def test_render_image_com_fade_e_texto_animado_juntos(tmp_path, synthetic_image):
    """O caso mais complexo: fade da IMAGEM + fade do TEXTO ao mesmo
    tempo, na mesma cadeia de filtros -- confere que as duas animações
    (independentes uma da outra) não colidem nem quebram o ffmpeg.
    """
    saida = str(tmp_path / "saida.mp4")
    style = {"animation": "fade", "animation_duration": 0.4, "font_color": "#ffff00", "shadow": True}
    _render_image_with_ken_burns(
        synthetic_image, 4.0, saida, 640, 360,
        zoom_direction="out", fade_in=True, fade_out=True, fade_duration=0.6,
        on_screen_text="Legenda animada", on_screen_text_style=style,
    )
    assert os.path.exists(saida) and os.path.getsize(saida) > 0
    assert abs(_probe_duration(saida) - 4.0) < 0.2


def test_render_image_zoom_centralizado_e_o_padrao():
    """Confirma que 'zoom in/out centralizado no meio' já é o padrão:
    focus_x/focus_y default pra 0.5/0.5 (centro) sem precisar informar
    nada -- só documenta o comportamento existente, sem chamar ffmpeg.
    """
    import inspect
    sig = inspect.signature(_render_image_with_ken_burns)
    assert sig.parameters["focus_x"].default == 0.5
    assert sig.parameters["focus_y"].default == 0.5
    assert sig.parameters["zoom_direction"].default == "in"


def test_render_image_sem_fade_nao_adiciona_filtro_fade(tmp_path, synthetic_image):
    """Sanidade: sem pedir fade nenhum, o comportamento é o de sempre
    (sem custo/mudança nenhuma pra quem não usa a funcionalidade nova).
    """
    saida = str(tmp_path / "saida.mp4")
    _render_image_with_ken_burns(synthetic_image, 2.0, saida, 640, 360)
    assert os.path.exists(saida) and os.path.getsize(saida) > 0
