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


CENTRO_LEGENDA = {"base": 0.93, "meio": 0.5, "topo": 0.06, "terco": 0.76}  # onde a legenda fica (dp_legendas)


def centro_legenda(leg: Optional[Dict[str, Any]]) -> Optional[float]:
    """Centro da legenda em fração da altura (a altura exata manda; senão a posição). None se a legenda está desligada."""
    if not leg or leg.get("ativa") is False:
        return None
    a = leg.get("altura")
    try:
        if a not in (None, "", "auto"):
            return max(0.05, min(0.95, float(a)))
    except (TypeError, ValueError):
        pass
    return CENTRO_LEGENDA.get(leg.get("posicao") or "terco", 0.76)


def ponto(cfg: Dict[str, Any], W: int, H: int, posicao_legenda: str = "", leg_y: Optional[float] = None) -> tuple:
    if (cfg.get("posicao") == "legenda") and leg_y is not None:  # 🏷 o @ LIGADO à legenda: X% (ou N px) acima/abaixo dela
        try:
            d = float(cfg.get("distancia_px") or 0) / H if cfg.get("distancia_px") else float(cfg.get("distancia") or 0.10)
        except (TypeError, ValueError):
            d = 0.10
        fy = leg_y + (-d if (cfg.get("lado") or "acima") == "acima" else d)
        return 5, int(W * 0.5), int(H * max(0.02, min(0.98, fy)))
    if cfg.get("posicao") == "livre":  # ↕ v84_334: a altura que você arrastou na prévia
        try:
            fy = float(cfg.get("altura") if cfg.get("altura") not in (None, "") else 0.5)
        except (TypeError, ValueError):
            fy = 0.5
        return 5, int(W * 0.5), int(H * max(0.02, min(0.98, fy)))
    an, fx, fy = LUGARES.get(cfg.get("posicao") or "meio", LUGARES["meio"])
    fy += float(cfg.get("desvio_y") or 0)
    if posicao_legenda and _MESMO_LUGAR_DA_LEGENDA.get(cfg.get("posicao") or "") == posicao_legenda:
        fy += -0.09 if fy > 0.15 else 0.09  # a legenda está no mesmo lugar: a marca sai de baixo dela
    return an, int(W * fx), int(H * max(0.02, min(0.98, fy)))


def gerar_ass(cfg: Dict[str, Any], W: int, H: int, dur: float, caminho: str, posicao_legenda: str = "",
              leg_y: Optional[float] = None) -> str:
    fam = cfg.get("fonte") or "DP Poppins"
    px_css = H * float(cfg.get("tamanho") or 0.035)
    fs = dp_destaques.fs_libass(fam, px_css)
    alfa = format(int(round(255 * (1 - float(cfg.get("opacidade") or 0.5)))), "02X")
    an, x, y = ponto(cfg, W, H, posicao_legenda, leg_y)
    x += int(round(float(cfg.get("desvio_x_px") or 0) * W / 1080))  # 🎨 v84_333: ajuste fino (px num 1080×1920)
    y += int(round(float(cfg.get("desvio_y_px") or 0) * H / 1920))
    escala = H / 1920.0
    if cfg.get("borda") not in (None, ""):  # 🎨 v84_333: a espessura que você escolheu (0 = sem borda)
        borda = int(round(float(cfg["borda"]) * escala))
    else:
        borda = max(1, int(round(fs / 18))) if cfg.get("contorno", True) else 0
    sombra = int(round(float(cfg.get("sombra") or 0) * escala))
    cor_borda = _cor(cfg.get("borda_cor") or "#000000")
    cor_sombra = _cor(cfg.get("sombra_cor") or "#000000").replace("&H00", "&H60", 1)
    texto = str(cfg.get("texto") or "").replace("{", "(").replace("}", ")").replace("\\", "/")
    if cfg.get("maiusculas"):  # 🎨 v84_338
        texto = texto.upper()
    italico = 1 if cfg.get("italico") else 0
    espaco = round(float(cfg.get("espaco") or 0) * escala, 1)
    estilo = cfg.get("estilo") or ""
    cor_estilo = cfg.get("estilo_cor") or ""
    borda_style = 1
    if estilo == "caixa":  # 📦 a caixa atrás do @ (BorderStyle 3 = caixa opaca na cor da borda)
        borda_style = 3
        borda = max(int(round(10 * escala)), borda)
        cor_borda = _cor(cor_estilo or cfg.get("borda_cor") or "#000000")

    def t(s: float) -> str:
        s = max(0.0, s)
        return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"
    linhas = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "ScaledBorderAndShadow: yes", "",
              "[V4+ Styles]",
              "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
              "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
              f"Style: Marca,{fam},{fs},{_cor(cfg.get('cor'))},{_cor(cfg.get('cor'))},{cor_borda},{cor_sombra},1,{italico},0,0,100,100,{espaco},0,{borda_style},{borda},{sombra},{an},0,0,0,1",
              "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    linhas += _camadas_de_baixo(estilo, cor_estilo or cfg.get("cor2") or cfg.get("cor") or "#FFFFFF", fs, borda, escala, x, y, alfa,
                                texto, t(0), t(dur + 1))
    linhas.append(f"Dialogue: 1,{t(0)},{t(dur + 1)},Marca,,0,0,0,,{{\\pos({x},{y})\\alpha&H{alfa}&}}{texto}")
    if cfg.get("gradiente") and cfg.get("cor2"):  # 🌈 v84_333: degradê — faixas finas por cima (com \clip), da cor 1 à cor 2
        linhas += _faixas_degrade(cfg, fam, px_css, an, x, y, texto, alfa, t(0), t(dur + 1))
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    return caminho


def _faixas_degrade(cfg: Dict[str, Any], fam: str, px_css: float, an: int, x: int, y: int, texto: str, alfa: str,
                    t0: str, t1: str, n: int = 28) -> list:
    """O libass não pinta degradê: o texto é redesenhado N vezes (sem borda/sombra), cada uma recortada numa faixa, com a
    cor indo da cor 1 à cor 2. A primeira camada (com a borda e a sombra) fica embaixo."""
    try:
        w = dp_destaques.largura_no_navegador(texto, fam, px_css)
    except Exception:  # noqa: BLE001
        w = len(texto) * px_css * 0.6
    h = px_css * 1.25
    col, lin = (an - 1) % 3, (an - 1) // 3  # numpad: col 0 esq/1 centro/2 dir · lin 0 base/1 meio/2 topo
    x0 = x - (0 if col == 0 else w / 2 if col == 1 else w)
    y0 = y - (h if lin == 0 else h / 2 if lin == 1 else 0)
    pad = px_css * 0.15
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x0 + w + pad, y0 + h + pad

    def rgb(hx):
        hx = str(hx or "#FFFFFF").lstrip("#")
        return int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
    c1, c2 = rgb(cfg.get("cor")), rgb(cfg.get("cor2"))
    vertical = cfg.get("grad_dir") == "vertical"
    out = []
    for k in range(n):
        u = k / max(1, n - 1)
        r, g, b = (int(round(c1[i] + (c2[i] - c1[i]) * u)) for i in range(3))
        if vertical:
            a_, b_ = y0 + (y1 - y0) * k / n, y0 + (y1 - y0) * (k + 1) / n
            clip = f"{int(x0)},{int(a_)},{int(x1) + 1},{int(b_) + 1}"
        else:
            a_, b_ = x0 + (x1 - x0) * k / n, x0 + (x1 - x0) * (k + 1) / n
            clip = f"{int(a_)},{int(y0)},{int(b_) + 1},{int(y1) + 1}"
        out.append(f"Dialogue: 2,{t0},{t1},Marca,,0,0,0,,{{\\pos({x},{y})\\alpha&H{alfa}&\\bord0\\shad0"
                   f"\\1c&H00{b:02X}{g:02X}{r:02X}&\\clip({clip})}}{texto}")
    return out


def aplicar(video: str, cfg: Optional[Dict[str, Any]], pasta_tmp: str, posicao_legenda: str = "",
            leg: Optional[Dict[str, Any]] = None) -> bool:
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
    ass = gerar_ass(cfg, W, H, float(_probe_duration(video) or 0), os.path.join(pasta_tmp, "marca.ass"), posicao_legenda,
                    centro_legenda(leg) if leg else None)
    saida = os.path.join(pasta_tmp, "_com_marca" + os.path.splitext(video)[1])
    dp_legendas.queimar(video, ass, saida)
    if not os.path.isfile(saida) or os.path.getsize(saida) < 1000:
        return False
    shutil.move(saida, video)
    return True


ESTILOS_MARCA = {"": "simples", "caixa": "📦 caixa atrás", "neon": "✨ brilho neon", "duplo": "⭕ contorno duplo", "3d": "🧱 3D (sombra longa)"}


def _camadas_de_baixo(estilo: str, cor: str, fs: float, borda: int, escala: float, x: int, y: int, alfa: str, texto: str,
                      t0: str, t1: str) -> list:
    """🎨 v84_338: o que fica EMBAIXO do @ pra dar o estilo (o texto normal vai por cima, na camada 1)."""
    h = str(cor or "#FFFFFF").lstrip("#").upper()
    c = f"&H{h[4:6]}{h[2:4]}{h[0:2]}&"
    ab = f"\\alpha&H{alfa}&"
    if estilo == "neon":  # brilho: uma borda grossa e borrada na cor do brilho, sem o recheio
        b, bl = max(4, int(fs / 7)), max(6, int(fs / 4))
        return [f"Dialogue: 0,{t0},{t1},Marca,,0,0,0,,{{\\pos({x},{y}){ab}\\1a&HFF&\\shad0\\bord{b}\\blur{bl}\\3c{c}}}{texto}",
                f"Dialogue: 0,{t0},{t1},Marca,,0,0,0,,{{\\pos({x},{y}){ab}\\1a&HFF&\\shad0\\bord{max(2, b // 2)}\\blur{max(2, bl // 3)}\\3c{c}}}{texto}"]
    if estilo == "duplo":  # um 2º contorno, mais largo, por fora do 1º
        b = max(borda, int(round(3 * escala))) * 2 + int(round(6 * escala))
        return [f"Dialogue: 0,{t0},{t1},Marca,,0,0,0,,{{\\pos({x},{y}){ab}\\shad0\\bord{b}\\3c{c}\\1c{c}}}{texto}"]
    if estilo == "3d":  # sombra longa: várias cópias deslocadas na diagonal
        n, passo = 10, max(1.0, fs / 70)
        return [f"Dialogue: 0,{t0},{t1},Marca,,0,0,0,,{{\\pos({x + round(k * passo)},{y + round(k * passo)}){ab}\\shad0\\bord{borda}"
                f"\\1c{c}\\3c{c}}}{texto}" for k in range(n, 0, -1)]
    return []
