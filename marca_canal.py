"""🏷 Marca do canal (v84_255): o "@canal" por cima do vídeo inteiro, com posição, tamanho, opacidade, fonte e cor.

Padrão: ligada, no MEIO do vídeo, 50% de opacidade, por cima da imagem (abaixo da legenda). Se a legenda também está no
meio (ou no mesmo lugar), a marca sobe um pouco pra não ficar embaixo da palavra.
Queimada na exportação (no vídeo com e sem legenda) — curtos.marca_do() diz a configuração; o Estúdio guarda em job["marca"].
"""
from __future__ import annotations

import os
import shutil
from typing import Any, Dict, Optional

import dp_destaques

# posição → (alinhamento ASS, x, y) em fração da tela
LUGARES = {
    "meio": (5, 0.5, 0.5), "topo": (8, 0.5, 0.05), "base": (2, 0.5, 0.95), "terco": (5, 0.5, 0.76),
    "sup_esq": (7, 0.04, 0.04), "sup_dir": (9, 0.96, 0.04), "inf_esq": (1, 0.04, 0.96), "inf_dir": (3, 0.96, 0.96),
}
_MESMO_LUGAR_DA_LEGENDA = {"meio": "meio", "topo": "topo", "base": "base", "terco": "terco"}


def _cor(hexa: str) -> str:
    h = (hexa or "#FFFFFF").lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def ponto(cfg: Dict[str, Any], W: int, H: int, posicao_legenda: str = "") -> tuple:
    an, fx, fy = LUGARES.get(cfg.get("posicao") or "meio", LUGARES["meio"])
    fy += float(cfg.get("desvio_y") or 0)
    if posicao_legenda and _MESMO_LUGAR_DA_LEGENDA.get(cfg.get("posicao") or "") == posicao_legenda:
        fy += -0.09 if fy > 0.15 else 0.09  # a legenda está no mesmo lugar: a marca sai de baixo dela
    return an, int(W * fx), int(H * max(0.02, min(0.98, fy)))


def gerar_ass(cfg: Dict[str, Any], W: int, H: int, dur: float, caminho: str, posicao_legenda: str = "") -> str:
    fam = cfg.get("fonte") or "DP Poppins"
    fs = dp_destaques.fs_libass(fam, H * float(cfg.get("tamanho") or 0.035))
    alfa = format(int(round(255 * (1 - float(cfg.get("opacidade") or 0.5)))), "02X")
    an, x, y = ponto(cfg, W, H, posicao_legenda)
    borda = max(1, int(round(fs / 18))) if cfg.get("contorno", True) else 0
    texto = str(cfg.get("texto") or "").replace("{", "(").replace("}", ")").replace("\\", "/")

    def t(s: float) -> str:
        s = max(0.0, s)
        return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"
    linhas = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "ScaledBorderAndShadow: yes", "",
              "[V4+ Styles]",
              "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
              "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
              f"Style: Marca,{fam},{fs},{_cor(cfg.get('cor'))},{_cor(cfg.get('cor'))},&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,{borda},0,{an},0,0,0,1",
              "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
              f"Dialogue: 0,{t(0)},{t(dur + 1)},Marca,,0,0,0,,{{\\pos({x},{y})\\alpha&H{alfa}&}}{texto}"]
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    return caminho


def aplicar(video: str, cfg: Optional[Dict[str, Any]], pasta_tmp: str, posicao_legenda: str = "") -> bool:
    """Queima a marca NO PRÓPRIO arquivo (troca no fim). False se está desligada / não deu."""
    if not cfg or not cfg.get("ativa") or not str(cfg.get("texto") or "").strip() or not os.path.isfile(video):
        return False
    import dp_legendas
    import subprocess
    from video_assembler import _probe_duration
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                        video], capture_output=True, text=True, timeout=60)
    try:
        W, H = (int(v) for v in r.stdout.strip().split(",")[:2])
    except ValueError:
        return False
    ass = gerar_ass(cfg, W, H, float(_probe_duration(video) or 0), os.path.join(pasta_tmp, "marca.ass"), posicao_legenda)
    saida = os.path.join(pasta_tmp, "_com_marca" + os.path.splitext(video)[1])
    dp_legendas.queimar(video, ass, saida)
    if not os.path.isfile(saida) or os.path.getsize(saida) < 1000:
        return False
    shutil.move(saida, video)
    return True
