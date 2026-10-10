"""
webpage_animator.py
=====================

Transforma o PRINT de uma página (de `webpage_capture.py`) num clipe
de vídeo — a "câmera" se move sobre a imagem parada, do mesmo jeito
que um efeito Ken Burns, só que com dois modos pensados especificamente
pra ler conteúdo de uma página capturada:

  - "scroll": rolagem vertical suave do topo até o fim da página (ou
    o inverso), pra mostrar a matéria/post inteiro sendo "lido".
  - "foco": aproxima suavemente num bloco de texto específico (um dos
    itens de `mapa["blocos"]`, ver `webpage_capture.py`), segura ali
    um tempo (o efeito visual de destaque, se pedido, também entra
    nessa hora), e afasta de novo — pensado pra "marcar um trecho
    específico" durante a leitura.

O resultado é um `.mp4` comum, do mesmo jeito que qualquer outro clipe
do site — dá pra usar como origem manual (override) de um segmento no
editor, encaixando na timeline na posição que você quiser.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, Optional, Tuple

from video_assembler import VideoAssemblyError, _run_ffmpeg  # reaproveita o mesmo runner/erro do resto do site

EFEITOS_VALIDOS = {"highlight", "dim_rest"}
MODOS_VALIDOS = {"scroll", "foco"}
DIRECOES_VALIDAS = {"baixo", "cima"}  # "baixo" = rola de cima pra baixo; "cima" = de baixo pra cima


def _dimensoes_imagem(caminho: str) -> Tuple[int, int]:
    from PIL import Image
    with Image.open(caminho) as img:
        return img.size


def _aplicar_efeito_visual(
    screenshot_path: str, bloco: Dict[str, Any], efeito: str, cor: Tuple[int, int, int], output_path: str,
) -> str:
    """Desenha o efeito de destaque (`highlight`: uma tarja semi-
    transparente atrás do texto; `dim_rest`: escurece tudo, MENOS a
    área do bloco) numa CÓPIA do screenshot -- o original nunca é
    modificado. Devolve o caminho da cópia com o efeito aplicado.
    """
    from PIL import Image, ImageDraw

    with Image.open(screenshot_path).convert("RGBA") as base:
        largura, altura = base.size
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        margem = 8
        x0 = max(0, bloco["x"] - margem)
        y0 = max(0, bloco["y"] - margem)
        x1 = min(largura, bloco["x"] + bloco["largura"] + margem)
        y1 = min(altura, bloco["y"] + bloco["altura"] + margem)

        if efeito == "highlight":
            draw.rectangle([x0, y0, x1, y1], fill=(cor[0], cor[1], cor[2], 110))
        elif efeito == "dim_rest":
            draw.rectangle([0, 0, largura, altura], fill=(0, 0, 0, 150))
            draw.rectangle([x0, y0, x1, y1], fill=(0, 0, 0, 0))  # "recorta" a área do bloco de volta transparente

        composta = Image.alpha_composite(base, overlay).convert("RGB")
        composta.save(output_path)
    return output_path


def renderizar_clipe_pagina(
    screenshot_path: str,
    output_path: str,
    duracao: float,
    modo: str = "scroll",
    direcao_scroll: str = "baixo",
    bloco: Optional[Dict[str, Any]] = None,
    efeito: Optional[str] = None,
    cor_efeito: Tuple[int, int, int] = (255, 210, 0),
    zoom_foco: float = 1.4,
    duracao_movimento: float = 1.5,
    duracao_afastamento: float = 1.2,
    target_width: int = 1920,
    target_height: int = 1080,
    fps: int = 30,
) -> str:
    """Renderiza `screenshot_path` (o print alto de uma página, ver
    `webpage_capture.capturar_pagina`) num clipe `.mp4` de `duracao`
    segundos.

    `modo="scroll"`: rola verticalmente a página inteira. `direcao_
        scroll`: "baixo" (do topo pro fim, padrão) ou "cima" (do fim
        pro topo).
    `modo="foco"`: aproxima em `bloco` (um item de `mapa["blocos"]` —
        precisa ter `x`/`y`/`largura`/`altura`), segura, e afasta de
        novo. `zoom_foco` controla o quanto aproxima (1.0 = sem zoom
        nenhum). `duracao_movimento`/`duracao_afastamento`: quanto
        tempo (em segundos, dentro da `duracao` total) a aproximação e
        o afastamento levam — o resto do tempo fica parado no bloco.
    `efeito` (só em `modo="foco"`, opcional): "highlight" (tarja de
        destaque atrás do texto) ou "dim_rest" (escurece tudo ao
        redor, deixando só o bloco em destaque natural).

    Devolve `output_path`.
    """
    if modo not in MODOS_VALIDOS:
        raise VideoAssemblyError(f"modo precisa ser um de {sorted(MODOS_VALIDOS)} (recebi {modo!r}).")
    if direcao_scroll not in DIRECOES_VALIDAS:
        raise VideoAssemblyError(f"direcao_scroll precisa ser um de {sorted(DIRECOES_VALIDAS)} (recebi {direcao_scroll!r}).")
    if efeito is not None and efeito not in EFEITOS_VALIDOS:
        raise VideoAssemblyError(f"efeito precisa ser um de {sorted(EFEITOS_VALIDOS)} ou None (recebi {efeito!r}).")
    if duracao <= 0:
        raise VideoAssemblyError(f"duracao precisa ser positiva (recebi {duracao}).")
    if not os.path.exists(screenshot_path):
        raise VideoAssemblyError(f"Screenshot não encontrado: {screenshot_path!r}")

    if modo == "foco":
        if not bloco:
            raise VideoAssemblyError('modo="foco" precisa de um `bloco` (com x/y/largura/altura).')
        for chave in ("x", "y", "largura", "altura"):
            if chave not in bloco:
                raise VideoAssemblyError(f'`bloco` precisa ter a chave "{chave}".')

    entrada = screenshot_path
    arquivo_temporario_efeito = None
    if modo == "foco" and efeito:
        arquivo_temporario_efeito = output_path + "._efeito_tmp.png"
        entrada = _aplicar_efeito_visual(screenshot_path, bloco, efeito, cor_efeito, arquivo_temporario_efeito)

    try:
        largura_original, altura_original = _dimensoes_imagem(entrada)
        if modo == "scroll":
            _renderizar_scroll(
                entrada, output_path, duracao, direcao_scroll, largura_original, altura_original,
                target_width, target_height, fps,
            )
        else:
            _renderizar_foco(
                entrada, output_path, duracao, bloco, zoom_foco, duracao_movimento, duracao_afastamento,
                largura_original, altura_original, target_width, target_height, fps,
            )
    finally:
        if arquivo_temporario_efeito and os.path.exists(arquivo_temporario_efeito):
            os.remove(arquivo_temporario_efeito)

    return output_path


def _renderizar_scroll(
    imagem_path: str, output_path: str, duracao: float, direcao: str,
    largura_original: int, altura_original: int, target_width: int, target_height: int, fps: int,
) -> None:
    # Escala a LARGURA pro tamanho final (preserva proporção) -- depois
    # é só cortar uma janela de target_height de altura e mover essa
    # janela verticalmente ao longo do tempo.
    altura_escalada = max(target_height, round(altura_original * (target_width / largura_original)))

    if altura_escalada <= target_height:
        # página mais curta que a janela final -- não sobra o que
        # rolar; centraliza com barras pretas em vez de tentar cortar
        # uma janela maior do que a imagem tem.
        filtro = (
            f"scale={target_width}:-1,"
            f"pad={target_width}:{target_height}:0:(oh-ih)/2:color=black"
        )
    else:
        y_max = altura_escalada - target_height
        if direcao == "baixo":
            y_expr = f"min(t/{duracao:.4f}*{y_max},{y_max})"
        else:
            y_expr = f"max({y_max}-t/{duracao:.4f}*{y_max},0)"
        filtro = (
            f"scale={target_width}:{altura_escalada},"
            f"crop=w={target_width}:h={target_height}:x=0:y='{y_expr}'"
        )

    _run_ffmpeg([
        "-loop", "1", "-i", imagem_path,
        "-vf", filtro,
        "-t", f"{duracao:.3f}", "-r", str(fps),
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        output_path,
    ])


def _renderizar_foco(
    imagem_path: str, output_path: str, duracao: float, bloco: Dict[str, Any], zoom_foco: float,
    duracao_movimento: float, duracao_afastamento: float,
    largura_original: int, altura_original: int, target_width: int, target_height: int, fps: int,
) -> None:
    duracao_movimento = max(0.1, min(duracao_movimento, duracao / 2))
    duracao_afastamento = max(0.1, min(duracao_afastamento, duracao / 2))
    total_frames = max(1, round(duracao * fps))
    frame_fim_aproximacao = max(1, round(duracao_movimento * fps))
    frame_inicio_afastamento = max(frame_fim_aproximacao + 1, total_frames - round(duracao_afastamento * fps))

    # Ponto focal do bloco, em fração (0..1) da imagem ORIGINAL --
    # usado pra calcular onde a "janela" de crop deve mirar quando
    # totalmente aproximada.
    centro_x_frac = min(1.0, max(0.0, (bloco["x"] + bloco["largura"] / 2) / largura_original))
    centro_y_frac = min(1.0, max(0.0, (bloco["y"] + bloco["altura"] / 2) / altura_original))

    # progresso: 0 no início, sobe até 1 ao fim da aproximação, fica em
    # 1 durante a espera, desce de volta a 0 durante o afastamento.
    progresso = (
        f"if(lte(on,{frame_fim_aproximacao}),on/{frame_fim_aproximacao},"
        f"if(lt(on,{frame_inicio_afastamento}),1,"
        f"max(0,1-(on-{frame_inicio_afastamento})/max(1,{total_frames}-{frame_inicio_afastamento}))))"
    )
    zoom_expr = f"(1+({zoom_foco - 1})*({progresso}))"
    x_expr = f"(iw-iw/zoom)*{centro_x_frac:.4f}"
    y_expr = f"(ih-ih/zoom)*{centro_y_frac:.4f}"

    filtro = (
        f"scale={target_width * 2}:{target_height * 2}:force_original_aspect_ratio=increase,"
        f"crop={target_width * 2}:{target_height * 2},"
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d={total_frames}:s={target_width}x{target_height}:fps={fps}"
    )

    _run_ffmpeg([
        "-loop", "1", "-i", imagem_path,
        "-vf", filtro,
        "-t", f"{duracao:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        output_path,
    ])
