"""
Fundos escolhíveis — pros DESTAQUES de texto (o "tratamento da cena" atrás do
texto) e pras CENAS/takes (o fundo atrás das janelas).

No DarkPlanner cada destaque traz um fundo fixo (faixas retas, grade
ondulada, grade 3D, banho de cor, imagem desfocada, vinheta…). Aqui dá pra
trocar por qualquer um da lista, mudar a cor e a intensidade — ou deixar o
do próprio estilo.

Cada destaque pode ter: "fundo" (id abaixo; vazio = o do estilo),
"fundo_cor" (#RRGGBB; vazio = cor do estilo/paleta) e "fundo_int" (0.15–1).
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

# id, nome, grupo, usa_cor
FUNDOS_DESTAQUE: List[Tuple[str, str, str, bool]] = [
    ("nenhum", "Sem fundo (só o texto)", "Simples", False),
    ("escurecer", "Escurecer a cena", "Simples", False),
    ("vinheta", "Vinheta (bordas escuras)", "Simples", False),
    ("gradiente", "Gradiente escuro embaixo", "Simples", False),
    ("painel", "Painel escuro na lateral", "Simples", False),
    ("flash", "Clarão na entrada", "Simples", False),
    ("veu_lateral", "Véu escuro na lateral", "Simples", False),
    ("espaco_negativo", "Espaço negativo (quase preto)", "Simples", False),
    ("pb", "Cena em preto e branco", "Tratamento da imagem", False),
    ("granulado", "Granulado de filme", "Tratamento da imagem", False),
    ("crt", "TV antiga (CRT, linhas)", "Tratamento da imagem", False),
    ("filme_queimado", "Filme queimado nas bordas", "Tratamento da imagem", True),
    ("nevoa", "Névoa", "Tratamento da imagem", False),
    ("luz", "Facho de luz", "Tratamento da imagem", True),
    ("desfoque", "Cena desfocada", "Imagem desfocada", False),
    ("desfoque_escuro", "Cena desfocada e escura", "Imagem desfocada", False),
    ("desfoque_cor", "Cena desfocada com tom de cor", "Imagem desfocada", True),
    ("faixas", "Faixas de cinema (retas, em cima e embaixo)", "Linhas e grades", False),
    ("linhas", "Linhas retas", "Linhas e grades", True),
    ("grade", "Grade reta", "Linhas e grades", True),
    ("ondas", "Linhas onduladas", "Linhas e grades", True),
    ("grade_ondulada", "Grade ondulada", "Linhas e grades", True),
    ("grade_3d", "Grade 3D (chão em perspectiva)", "Linhas e grades", True),
    ("pontos", "Grade de pontos", "Linhas e grades", True),
    ("banho_cor", "Banho de cor (cena tingida)", "Cor", True),
    ("cor_gradiente", "Gradiente de cor", "Cor", True),
    ("cor_solida", "Cor sólida (cobre a cena)", "Cor", True),
    ("papel", "Papel de arquivo", "Cor", False),
    ("jornal", "Jornal (colunas e retícula)", "Cor", False),
    ("tinta", "Mancha de tinta atrás do texto", "Cor", True),
    ("galeria", "Moldura de galeria (passe-partout)", "Cor", True),
    ("mapa", "Mapa (curvas e rota)", "Linhas e grades", True),
]
IDS_DESTAQUE = {f[0] for f in FUNDOS_DESTAQUE}
USA_COR = {f[0] for f in FUNDOS_DESTAQUE if f[3]}

# fundo do DarkPlanner (highlights.*.cena.fundo) -> (id daqui, cor padrão)
_DO_DARKPLANNER = {
    "nenhum": ("nenhum", None), "escurecer": ("escurecer", None), "escurecer_grao": ("escurecer", None),
    "vinheta": ("vinheta", None), "vinheta_grao": ("vinheta", None), "vinheta_off": ("vinheta", None),
    "gradiente": ("gradiente", None), "luz": ("luz", "#FFE2B0"), "nevoa": ("nevoa", None), "veu_esq": ("veu_lateral", None),
    "desfoque": ("desfoque", None), "faixas": ("faixas", None), "painel": ("painel", None),
    "impacto": ("flash", None), "corte_flash": ("flash", None), "corte_luz": ("flash", None),
    "banho_cor_suave": ("banho_cor", None), "banho_cor_grao": ("banho_cor", None),
    "grade_ondulada_azul": ("grade_ondulada", "#1E5BD6"), "grade_ondulada_preta": ("grade_ondulada", "#3A3A44"),
    "grade_3d_azul": ("grade_3d", "#2F7BFF"), "grade_3d_verm": ("grade_3d", "#E0313B"), "grade_3d_ouro": ("grade_3d", "#E8B04A"),
    "grade_verm": ("grade", "#C0303A"), "grade_navy": ("grade", "#3C5082"), "grade_frente": ("grade", "#50505A"),
    "grade_escura": ("grade", "#303036"), "grade_horizonte": ("grade_3d", "#4A6C8C"), "grade_papel": ("papel", None),
    "papel_arquivo": ("papel", None), "pergaminho_epoca": ("papel", None),
    "blueprint_cyan": ("grade", "#28A0C0"), "mapa_rota": ("mapa", "#28A0C0"),
}
COR_PADRAO = {"filme_queimado": "#FF7A1F", "luz": "#FFE2B0", "tinta": "#101010", "galeria": "#F2EEE6", "mapa": "#28A0C0"}
_POR_TRATAMENTO = {"dim": "escurecer", "vignette": "vinheta", "gradient": "gradiente", "blur": "desfoque", "flash": "flash",
                   "panel": "painel", "front_grid": "grade", "fullscreen_grid": "grade", "tech_grid": "grade",
                   "grain": "granulado", "light": "luz", "haze": "nevoa", "side_veil": "veu_lateral", "archive": "papel",
                   "fullscreen_texture": "papel", "desaturate": "pb", "color_wash": "banho_cor", "film_burn": "filme_queimado",
                   "ink": "tinta", "map": "mapa", "blueprint": "grade", "newspaper": "jornal", "gallery": "galeria",
                   "negative_space": "espaco_negativo", "crt": "crt"}


def _hex(c: Optional[str]) -> Optional[str]:
    c = str(c or "")
    return c.upper() if re.fullmatch(r"#[0-9a-fA-F]{6}", c) else None


def do_estilo(cena: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """(id, cor) do fundo que o estilo traz no DarkPlanner."""
    f = str((cena or {}).get("fundo") or "")
    if f in _DO_DARKPLANNER:
        return _DO_DARKPLANNER[f]
    if f.startswith("corte_"):
        return ("escurecer", None)
    if f.startswith("grade"):
        return ("grade", None)
    t = _POR_TRATAMENTO.get((cena or {}).get("tratamento") or "")
    return (t, None) if t else ("nenhum", None)


def resolver(d: Dict[str, Any], cena_estilo: Dict[str, Any], paleta: Optional[Dict[str, str]] = None,
             padrao: Optional[Dict[str, Any]] = None) -> Tuple[str, str, float]:
    """(id, cor, intensidade) do fundo de um destaque: o escolhido nele > o
    padrão do projeto > o do estilo. Cor: a escolhida > a do estilo > a
    primária da paleta."""
    if d.get("sem_fundo"):
        return ("nenhum", "#000000", 1.0)
    padrao = padrao or {}
    fid = d.get("fundo") if d.get("fundo") in IDS_DESTAQUE else None
    cor = _hex(d.get("fundo_cor"))
    inten = d.get("fundo_int")
    if not fid and padrao.get("fundo") in IDS_DESTAQUE:
        fid = padrao["fundo"]
        cor = cor or _hex(padrao.get("cor"))
        inten = inten if inten is not None else padrao.get("int")
    eid, ecor = do_estilo(cena_estilo)
    if not fid:
        fid = eid
    cor = cor or (ecor if fid == eid else None) or COR_PADRAO.get(fid) or _hex((paleta or {}).get("primaria")) or "#FFD60A"
    try:
        inten = max(0.15, min(1.0, float(inten))) if inten is not None else 1.0
    except (TypeError, ValueError):
        inten = 1.0
    return (fid, cor, inten)


def _rgb(c: str) -> Tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _escuro(c: str, k: float = 0.22) -> Tuple[int, int, int]:
    r, g, b = _rgb(c)
    return int(r * k + 6), int(g * k + 6), int(b * k + 8)


def _claro(c: str, k: float = 0.55) -> Tuple[int, int, int]:
    r, g, b = _rgb(c)
    return int(r + (255 - r) * k * 0.6), int(g + (255 - g) * k * 0.6), int(b + (255 - b) * k * 0.6)


def padrao_png(tipo: str, W: int, H: int, pasta: str, cor: str = "#3C5082", inten: float = 1.0,
               cobre: bool = True) -> str:
    """PNG RGBA com o desenho do fundo: linhas, grade, ondas, grade ondulada,
    grade 3D, pontos, faixas, gradiente, papel, cor sólida/gradiente de cor.
    `cobre`=True põe um fundo escuro da cor por baixo (o texto fica sobre um
    "cartaz"); False = só o desenho, transparente (pras cenas)."""
    from PIL import Image, ImageDraw, ImageFilter
    os.makedirs(pasta, exist_ok=True)
    chave = hashlib.md5(f"{tipo}|{W}|{H}|{cor}|{inten:.2f}|{cobre}".encode()).hexdigest()[:10]
    p = os.path.join(pasta, f"fd_{tipo}_{chave}.png")
    if os.path.exists(p):
        return p
    A = lambda a: int(max(0, min(255, a * inten)))  # noqa: E731
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    u = max(1, H // 540)
    if tipo == "vinheta":
        # igual ao CSS da telinha: radial-gradient(circle, transparent 40%, rgba(0,0,0,.7)) —
        # círculo até o canto mais distante; o centro não escurece
        pw, ph = 320, max(2, int(320 * H / W))
        pq = Image.new("L", (pw, ph), 0)
        R = math.hypot(pw / 2, ph / 2)
        pq.putdata([int(max(0.0, (math.hypot(x + 0.5 - pw / 2, y + 0.5 - ph / 2) / R - 0.4) / 0.6) * 0.7 * 255 * max(0.0, min(1.0, inten)))
                    for y in range(ph) for x in range(pw)])
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        im.putalpha(pq.resize((W, H), Image.BILINEAR))
        im.save(p)
        return p
    if tipo == "gradiente":
        for yy in range(H):
            d.line([0, yy, W, yy], fill=(0, 0, 0, A(max(0, (yy / H - 0.35) / 0.65) ** 1.4 * 215)))
    elif tipo == "faixas":
        d.rectangle([0, 0, W, int(H * 0.11)], fill=(0, 0, 0, A(255)))
        d.rectangle([0, int(H * 0.89), W, H], fill=(0, 0, 0, A(255)))
    elif tipo in ("cor_solida", "banho_cor"):
        im = Image.new("RGBA", (W, H), _rgb(cor) + (A(235 if tipo == "cor_solida" else 105),))
    elif tipo == "cor_gradiente":
        r1, g1, b1 = _escuro(cor, 0.35)
        r2, g2, b2 = _rgb(cor)
        for yy in range(H):
            k = yy / H
            d.line([0, yy, W, yy], fill=(int(r2 + (r1 - r2) * k), int(g2 + (g1 - g2) * k), int(b2 + (b1 - b2) * k), A(230)))
    elif tipo == "espaco_negativo":
        im = Image.new("RGBA", (W, H), (6, 6, 8, A(228)))
    elif tipo == "veu_lateral":
        for xx in range(W):
            d.line([xx, 0, xx, H], fill=(0, 0, 0, A(max(0, 1 - xx / (W * 0.58)) ** 1.3 * 225)))
    elif tipo in ("filme_queimado", "luz", "nevoa", "tinta", "galeria", "crt"):
        import numpy as np
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r_, g_, b_ = _rgb(cor)
        rgba = np.zeros((H, W, 4), np.float32)
        if tipo == "filme_queimado":
            dist = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
            rng = np.random.default_rng(3)
            ruido = np.array(Image.fromarray((rng.random((H // 16 + 1, W // 16 + 1)) * 255).astype("uint8")).resize((W, H), Image.BICUBIC), np.float32) / 255
            a = np.clip((dist - 0.86 + ruido * 0.22) * 3.2, 0, 1)
            esc = np.clip((a - 0.5) * 2, 0, 1)  # por fora quase preto, na frente da queima a cor
            rgba[..., 0], rgba[..., 1], rgba[..., 2] = r_ * (1 - esc * 0.85), g_ * (1 - esc * 0.9), b_ * (1 - esc * 0.95)
            rgba[..., 3] = a * 240
        elif tipo == "luz":
            faixa = np.exp(-(((xx - W * 0.3) * 0.8 + (yy - 0) * 0.6 - W * 0.12) / (W * 0.16)) ** 2)
            rgba[..., 0], rgba[..., 1], rgba[..., 2] = r_, g_, b_
            rgba[..., 3] = faixa * 150
        elif tipo == "nevoa":
            rng = np.random.default_rng(5)
            ruido = np.array(Image.fromarray((rng.random((H // 40 + 2, W // 40 + 2)) * 255).astype("uint8")).resize((W, H), Image.BICUBIC), np.float32) / 255
            a = np.clip((yy / H) * 0.9 + ruido * 0.35 - 0.2, 0, 1)
            rgba[..., :3] = 215
            rgba[..., 3] = a * 170
        elif tipo == "tinta":
            dist = np.sqrt(((xx - W / 2) / (W * 0.36)) ** 2 + ((yy - H / 2) / (H * 0.26)) ** 2)
            rng = np.random.default_rng(9)
            ruido = np.array(Image.fromarray((rng.random((H // 30 + 2, W // 30 + 2)) * 255).astype("uint8")).resize((W, H), Image.BICUBIC), np.float32) / 255
            a = np.clip((1.15 - dist - ruido * 0.35) * 3, 0, 1)
            e_ = _escuro(cor, 0.35)
            rgba[..., 0], rgba[..., 1], rgba[..., 2] = e_
            rgba[..., 3] = a * 235
        elif tipo == "galeria":
            m = int(min(W, H) * 0.07)
            borda = ((xx < m) | (xx > W - m) | (yy < m) | (yy > H - m)).astype(np.float32)
            c_ = _claro(cor, 0.95)
            rgba[..., 0], rgba[..., 1], rgba[..., 2] = c_
            rgba[..., 3] = borda * 250
            sombra = ((xx >= m) & (xx < m + m * 0.25)) | ((yy >= m) & (yy < m + m * 0.25))
            rgba[..., 3] = np.where(sombra & (borda == 0), 90, rgba[..., 3])
            rgba[..., :3] = np.where((sombra & (borda == 0))[..., None], 0, rgba[..., :3])
        elif tipo == "crt":
            linhas = ((yy.astype(int) // max(2, H // 270)) % 2 == 0).astype(np.float32)
            dist = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
            rgba[..., 3] = np.clip(linhas * 70 + np.clip(dist - 0.7, 0, 1) * 400, 0, 230)
        rgba[..., 3] *= inten
        im = Image.fromarray(np.clip(rgba, 0, 255).astype("uint8"), "RGBA")
    elif tipo == "jornal":
        import numpy as np
        rng = np.random.default_rng(11)
        base = np.zeros((H, W, 4), np.float32)
        base[..., :3] = (226, 221, 207)
        base[..., :3] -= rng.random((H, W, 1)) * 12
        base[..., 3] = 248 * inten
        im = Image.fromarray(np.clip(base, 0, 255).astype("uint8"), "RGBA")
        d = ImageDraw.Draw(im)
        col = W // 5
        for k in range(1, 5):
            d.line([k * col, int(H * 0.08), k * col, int(H * 0.92)], fill=(150, 145, 130, A(200)), width=u)
        for k in range(5):
            for yy_ in range(int(H * 0.1), int(H * 0.9), max(6, H // 60)):
                if (yy_ // max(6, H // 60) + k) % 7:
                    d.line([k * col + col * 0.08, yy_, k * col + col * 0.92, yy_], fill=(175, 170, 155, A(140)), width=u)
    elif tipo == "mapa":
        im = Image.new("RGBA", (W, H), _escuro(cor, 0.3) + (A(238),))
        d = ImageDraw.Draw(im)
        linha = _claro(cor, 0.4) + (A(110),)
        for (fx, fy) in ((0.18, 0.3), (0.45, 0.2), (0.75, 0.32), (0.3, 0.72), (0.62, 0.68), (0.9, 0.8)):
            cx_, cy_ = W * fx, H * fy
            for rr in range(1, 5):
                rx, ry = rr * W * 0.035, rr * H * 0.045
                d.ellipse([cx_ - rx, cy_ - ry, cx_ + rx, cy_ + ry], outline=linha, width=u)
        rota = [(W * 0.12, H * 0.78), (W * 0.3, H * 0.6), (W * 0.48, H * 0.7), (W * 0.66, H * 0.42), (W * 0.86, H * 0.3)]
        for (a1, a2) in zip(rota, rota[1:]):
            for t in range(0, 10, 2):
                p1 = (a1[0] + (a2[0] - a1[0]) * t / 10, a1[1] + (a2[1] - a1[1]) * t / 10)
                p2 = (a1[0] + (a2[0] - a1[0]) * (t + 1) / 10, a1[1] + (a2[1] - a1[1]) * (t + 1) / 10)
                d.line([p1, p2], fill=_rgb(cor) + (A(230),), width=u * 3)
    elif tipo == "papel":
        import numpy as np
        rng = np.random.default_rng(7)
        base = np.zeros((H, W, 4), np.float32)
        base[..., :3] = (233, 225, 206)
        base[..., :3] -= (rng.random((H, W, 1)) * 14)
        base[..., 3] = 245 * inten
        im = Image.fromarray(np.clip(base, 0, 255).astype("uint8"), "RGBA")
    else:
        if cobre:
            im = Image.new("RGBA", (W, H), _escuro(cor) + (A(238),))
            d = ImageDraw.Draw(im)
        linha = _claro(cor) + (A(120 if cobre else 150),)
        passo = max(24, H // 14)
        if tipo == "linhas":
            for yy in range(passo // 2, H, max(10, passo // 2)):
                d.line([0, yy, W, yy], fill=linha, width=u)
        elif tipo == "grade":
            for xx in range(0, W, passo):
                d.line([xx, 0, xx, H], fill=linha, width=u)
            for yy in range(0, H, passo):
                d.line([0, yy, W, yy], fill=linha, width=u)
        elif tipo in ("ondas", "grade_ondulada"):
            amp, comp = passo * 0.28, W / 3.2
            for yy in range(-passo, H + passo, max(10, passo // 2) if tipo == "ondas" else passo):
                pts = [(x, yy + amp * math.sin(2 * math.pi * x / comp + yy * 0.02)) for x in range(0, W + 8, 8)]
                d.line(pts, fill=linha, width=u + (1 if tipo == "ondas" else 0))
            if tipo == "grade_ondulada":
                for xx in range(-passo, W + passo, passo):
                    pts = [(xx + amp * math.sin(2 * math.pi * y / (H / 1.6) + xx * 0.02), y) for y in range(0, H + 8, 8)]
                    d.line(pts, fill=linha, width=u)
        elif tipo == "grade_3d":
            hz = int(H * 0.42)
            for k in range(1, 18):  # linhas horizontais se aproximando do horizonte
                yy = hz + (H - hz) * (k / 17) ** 2.2
                d.line([0, yy, W, yy], fill=linha, width=u)
            for k in range(-12, 13):  # linhas que fogem pro centro
                d.line([W / 2 + k * W * 0.02, hz, W / 2 + k * W * 0.16, H], fill=linha, width=u)
            brilho = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(brilho).rectangle([0, hz - u * 3, W, hz + u * 3], fill=_claro(cor, 0.9) + (A(160),))
            im = Image.alpha_composite(im, brilho.filter(ImageFilter.GaussianBlur(max(2, H // 90))))
        elif tipo == "pontos":
            r = max(1, u * 2)
            for yy in range(passo // 2, H, passo):
                for xx in range(passo // 2, W, passo):
                    d.ellipse([xx - r, yy - r, xx + r, yy + r], fill=linha)
    im.save(p)
    return p


def escurecer_igual_previa(alfa: float, env: str = "1", jan: Optional[str] = None, rotulo: str = "base") -> str:
    """Escurece como uma camada preta de opacidade `alfa` por cima (o que a telinha
    do Estúdio faz com CSS): cada canal × (1 - alfa). No eq: contraste K e brilho
    (K-1)×0,38 (medido no ffmpeg) dão Y' = Y×K (vídeo em faixa limitada 16-235); saturação K escurece a cor junto. `env` (0..1) faz a
    entrada/saída suave."""
    k = f"(1-{max(0.0, min(1.0, alfa)):.3f}*{env})"
    en = f":enable='{jan}'" if jan else ""
    return f"[{rotulo}]eq=contrast='{k}':brightness='({k}-1)*0.38':saturation='{k}':eval=frame{en}[{rotulo}]"


def etapas_destaque(fid: str, cor: str, inten: float, a: float, b: float, W: int, H: int, pasta: str) -> Tuple[List[str], Optional[str]]:
    """(etapas sobre [base], PNG a sobrepor ou None) do fundo `fid` entre a e b.
    Quem chama põe o PNG como entrada e liga o overlay."""
    jan = f"between(t,{a:.3f},{b:.3f})"
    env = f"clip(min(t-{a:.3f},{b:.3f}-t)/0.25,0,1)"
    if fid == "escurecer":
        # telinha: camada preta rgba(0,0,0,.35×int) por cima = MULTIPLICA a luz por 0,65.
        # Antes era brightness -0.22 (SUBTRAI): em cena já escura quase tudo ia pro preto.
        return [escurecer_igual_previa(0.35 * inten, env, jan)], None
    if fid == "vinheta":
        # telinha: só as bordas escurecem (gradiente radial até 70% nos cantos) — o centro fica
        # igual. Antes: filtro vignette (bem mais forte) + brilho -0.08 na tela toda.
        return [], padrao_png("vinheta", W, H, pasta, cor, inten)
    if fid in ("desfoque", "desfoque_escuro", "desfoque_cor"):
        et = [f"[base]gblur=sigma={max(3, int(H / 70 * (0.4 + inten)))}:enable='{jan}'[base]"]
        if fid == "desfoque_escuro":  # telinha: brightness(.75) + camada preta de 30%
            et.append(escurecer_igual_previa(1 - 0.75 * (1 - 0.3 * inten), env, jan))
        if fid == "desfoque_cor":
            r, g, bb = _rgb(cor)
            et.append(f"[base]drawbox=x=0:y=0:w=iw:h=ih:color=0x{r:02X}{g:02X}{bb:02X}@{0.38 * inten:.2f}:t=fill:enable='{jan}'[base]")
        return et, None
    if fid == "flash":
        return [f"[base]eq=brightness='{0.55 * inten:.2f}*max(0,1-(t-{a:.3f})/0.3)':eval=frame:enable='between(t,{a:.3f},{a + 0.3:.3f})'[base]",
                escurecer_igual_previa(0.15 * inten, env, jan)], None
    if fid == "pb":
        return [f"[base]hue=s=0:enable='{jan}'[base]", f"[base]eq=contrast={1 + 0.12 * inten:.2f}:enable='{jan}'[base]"], None
    if fid == "granulado":
        return [f"[base]noise=alls={max(6, int(26 * inten))}:allf=t+u:enable='{jan}'[base]"], None
    if fid == "crt":
        return [f"[base]rgbashift=rh={max(2, W // 400)}:bh=-{max(2, W // 400)}:enable='{jan}'[base]"], padrao_png("crt", W, H, pasta, cor, inten)
    if fid == "painel":
        return [f"[base]drawbox=x=0:y=0:w=iw*0.46:h=ih:color=black@{0.62 * inten:.2f}:t=fill:enable='{jan}'[base]"], None
    if fid in ("gradiente", "faixas", "linhas", "grade", "ondas", "grade_ondulada", "grade_3d", "pontos", "banho_cor", "cor_gradiente", "cor_solida", "papel",
               "espaco_negativo", "veu_lateral", "filme_queimado", "luz", "nevoa", "tinta", "galeria", "jornal", "mapa"):
        return [], padrao_png(fid, W, H, pasta, cor, inten)
    return [], None


def para_editor() -> Dict[str, Any]:
    return {"destaque": [{"id": f[0], "nome": f[1], "grupo": f[2], "cor": f[3]} for f in FUNDOS_DESTAQUE],
            "cena": [{"id": i, "nome": n, "grupo": g, "cor": c, "css": __import__("cenas_dp")._css_fundo(i)} for (i, n, g, c) in FUNDOS_CENA]}


# ------------------------------------------------------------------ cenas/takes
# além dos fundos que cada template traz (cenas_dp.fundos_do_template)
FUNDOS_CENA: List[Tuple[str, str, str, bool]] = [
    ("vidro", "A própria mídia desfocada", "Imagem desfocada", False),
    ("vidro_cor", "Mídia desfocada com tom de cor", "Imagem desfocada", True),
    ("midia", "A própria mídia (escurecida)", "Imagem desfocada", False),
    ("escuro", "Escuro com grão", "Texturas", False),
    ("concreto", "Concreto", "Texturas", False),
    ("papel", "Papel de arquivo", "Texturas", False),
    ("filme", "Película", "Texturas", False),
    ("borda_queimada", "Borda queimada", "Texturas", False),
    ("registro", "Marcas de registro", "Texturas", False),
    ("cantoneiras", "Cantoneiras", "Texturas", False),
    ("clarao", "Clarão de luz", "Luz e cor", True),
    ("luz", "Luz diagonal", "Luz e cor", True),
    ("cor_gradiente", "Gradiente de cor", "Luz e cor", True),
    ("cor_solida", "Cor sólida", "Luz e cor", True),
    ("linhas", "Linhas retas", "Linhas e grades", True),
    ("grade", "Grade reta", "Linhas e grades", True),
    ("ondas", "Linhas onduladas", "Linhas e grades", True),
    ("grade_ondulada", "Grade ondulada", "Linhas e grades", True),
    ("grade_3d", "Grade 3D (perspectiva)", "Linhas e grades", True),
    ("grade_pontos", "Grade de pontos", "Linhas e grades", True),
]
IDS_CENA = {f[0] for f in FUNDOS_CENA}
