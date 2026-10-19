"""
personagens_limpeza.py — 🧹 PNG transparente da personagem no PRÓPRIO PC (v84_184)
=================================================================================

A imagem do Flow vem com fundo verde (chroma key). Aqui, sem GPU e sem modelo de recorte:
  • chave de verde: todo verde sai (inclusive o preso entre os fios do cabelo), o verde escuro/sombreado que
    encosta na borda da imagem também; o reflexo verde da borda é neutralizado;
  • limpeza: pontinhos soltos, furinhos dentro do corpo, 1 px de borda, borda suave (o mesmo código do pod);
  • alinhar: canvas fixo 1200×1800, personagem a ~95% da altura, encostada embaixo (a cabeça fica no mesmo lugar);
  • colagem: o Flow aceita UMA imagem de referência — a ficha e a ⭐ mestre vão lado a lado numa imagem só.

Sem OpenCV ainda funciona (só a chave de verde, a borda e o alinhamento); com `opencv-python-headless` faz tudo.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter

PADRAO_LIMPEZA = {"fundo": "branco", "ilhas": True, "ilha_min": 0.02, "furos_px": 400, "fundo_preso": True, "branco_min": 248, "fundo_preso_px": 600,
                  "erodir": 1, "halo": True, "suavizar": 0.6}


def limpar(img: Image.Image, alfa: Image.Image, opcoes: Optional[Dict[str, Any]] = None) -> Tuple[Image.Image, Image.Image, Dict[str, Any]]:
    """🧹 Limpa o recorte. fundo "verde" (recomendado: chroma key — o verde preso entre os fios do cabelo sai também,
    e o reflexo verde da borda é neutralizado) ou "branco" (os passos 3 e 5 abaixo):
      1. ilhas  — some com os pontinhos soltos (pedaços < ilha_min do maior pedaço); objeto separado grande
                  (ex.: o buraco negro flutuando sobre a mão) fica;
      2. furos  — fecha os furinhos DENTRO da personagem (< furos_px pixels) que o recorte deixou; vão de verdade
                  (entre o braço e o corpo) é grande e continua transparente;
      3. fundo_preso — o branco PURO do fundo que o recorte marcou como personagem vira transparente: o que
                  encosta no lado de fora (entre as pernas, em volta do cabelo e de um objeto, qualquer tamanho) e mancha
                  grande fechada (≥ fundo_preso_px). Só branco puro e sem cor (média ≥ 242) — camisa marfim, babado e
                  o brilho do olho ficam;
      4. erodir — come N px da borda (onde o branco do fundo ainda gruda);
      5. halo   — "descontamina" a borda semitransparente: tira o branco que vazou na cor (cabelo sem auréola);
      6. suavizar — desfoca 0,6 px só o alfa (borda sem serrilhado).
    → (imagem RGB limpa, alfa limpo, o que fez)."""
    import numpy as np
    o = dict(PADRAO_LIMPEZA, **(opcoes or {}))
    a = np.asarray(alfa.convert("L"), dtype=np.float32) / 255.0
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    feito: Dict[str, Any] = {"ilhas_removidas": 0, "furos_fechados": 0}
    verde = o.get("fundo") == "verde"
    if verde:  # 🟩 chroma key: TODO verde do fundo sai — inclusive o preso entre os fios do cabelo
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        outro = np.maximum(r, b)
        chave = (g >= 90) & (g > outro * 1.35 + 20)
        a[chave] = 0.0
        feito["verde_px"] = int(chave.sum())
        borda_verde = (a > 0) & (g > outro + 8)
        excesso = np.clip((g - outro) / 160.0, 0, 1)
        a[borda_verde] *= 1.0 - excesso[borda_verde]          # borda esverdeada fica mais transparente
        rgb[..., 1] = np.where(g > outro, outro + (g - outro) * 0.15, g)  # tira o reflexo verde (despill)
    try:
        import cv2
    except ImportError:  # sem OpenCV: só o halo e o limiar
        cv2 = None
    if cv2 is not None and o.get("ilhas"):
        bin_ = (a > 0.5).astype(np.uint8)
        n, lab, stats, _c = cv2.connectedComponentsWithStats(bin_, connectivity=8)
        if n > 2:
            areas = stats[1:, cv2.CC_STAT_AREA]
            maior = int(areas.max())
            for k, ar in enumerate(areas, start=1):
                if ar < maior * float(o["ilha_min"]):
                    regiao = cv2.dilate((lab == k).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
                    a[regiao & (bin_ == 0) | (lab == k)] = 0.0
                    feito["ilhas_removidas"] += 1
    if cv2 is not None and int(o.get("furos_px") or 0) > 0:
        fundo = (a <= 0.5).astype(np.uint8)
        n, lab, stats, _c = cv2.connectedComponentsWithStats(fundo, connectivity=4)
        h, w = a.shape
        for k in range(1, n):
            x, y, bw, bh, ar = stats[k]
            toca_borda = x == 0 or y == 0 or x + bw >= w or y + bh >= h
            if not toca_borda and ar < int(o["furos_px"]):
                a[lab == k] = 1.0
                feito["furos_fechados"] += 1
    if verde:  # o "fechar furinhos" não pode devolver o verde que a chave tirou
        a[chave] = 0.0
    if cv2 is not None and o.get("fundo_preso") and not verde:
        lim = float(o.get("branco_min") or 248)
        mn = rgb.min(axis=2)
        claro = ((mn >= lim - 13) & ((rgb.max(axis=2) - mn) <= 8) & (a > 0.5)).astype(np.uint8)
        n, lab, stats, _c = cv2.connectedComponentsWithStats(claro, connectivity=8)
        if n > 1:
            fora = cv2.dilate((a <= 0.5).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
            toca = np.bincount(lab[fora & (claro > 0)].ravel(), minlength=n) > 0      # o pedaço encosta no lado de fora
            media = np.bincount(lab.ravel(), weights=mn.ravel(), minlength=n) / np.maximum(1, stats[:, cv2.CC_STAT_AREA])
            area = stats[:, cv2.CC_STAT_AREA]
            sai = np.zeros(n, bool)
            sai[1:] = (toca[1:] & (media[1:] >= lim - 6)) | ((area[1:] >= int(o.get("fundo_preso_px") or 600)) & (media[1:] >= lim - 2))
            tirar = sai[lab]
            if tirar.any():
                tirar = cv2.dilate(tirar.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0  # a borda clarinha junto
                quase = (mn >= lim - 30) & ((rgb.max(axis=2) - mn) <= 14)
                a[tirar & quase] = 0.0
                feito["fundo_preso_px"] = int((tirar & quase).sum())
    if cv2 is not None and int(o.get("erodir") or 0) > 0:
        r = int(o["erodir"])
        a = cv2.erode(a, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    a[a < 0.04] = 0.0
    a[a > 0.96] = 1.0
    if o.get("halo") and not verde:
        borda = (a > 0.0) & (a < 1.0)
        aa = np.clip(a[borda], 0.05, 1.0)[:, None]
        rgb[borda] = np.clip((rgb[borda] - (1.0 - aa) * 255.0) / aa, 0, 255)  # C = a·F + (1−a)·branco → F
        feito["borda_px"] = int(borda.sum())
    alfa_out = Image.fromarray((a * 255).round().astype(np.uint8), "L")
    if float(o.get("suavizar") or 0) > 0:
        alfa_out = alfa_out.filter(ImageFilter.GaussianBlur(float(o["suavizar"])))
    return Image.fromarray(rgb.round().astype(np.uint8), "RGB"), alfa_out, feito


def alinhar(img: Image.Image, alfa: Image.Image, canvas: Tuple[int, int] = (1200, 1800),
            altura_personagem: float = 0.95) -> Tuple[Image.Image, Dict[str, Any]]:
    """PNG transparente no canvas fixo: a personagem com ~95% da altura, encostada na borda de baixo (o corte do
    quadril vira a borda), centrada pelo próprio desenho. Assim todas as poses têm a cabeça no mesmo lugar."""
    rgba = img.convert("RGBA")
    rgba.putalpha(alfa)
    caixa = alfa.point(lambda v: 255 if v > 24 else 0).getbbox()
    W, H = canvas
    if not caixa:
        raise ValueError("o recorte não achou a personagem")
    fig = rgba.crop(caixa)
    k = (H * altura_personagem) / fig.height
    if fig.width * k > W * 0.98:  # braços muito abertos: diminui pra caber na largura
        k = (W * 0.98) / fig.width
    fig = fig.resize((max(1, round(fig.width * k)), max(1, round(fig.height * k))), Image.LANCZOS)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(fig, ((W - fig.width) // 2, H - fig.height), fig)
    toca_baixo = caixa[3] >= img.height - 4
    lados = [n for n, t in (("esquerda", caixa[0] <= 3), ("direita", caixa[2] >= img.width - 4), ("topo", caixa[1] <= 3)) if t]
    aviso = None
    if lados:
        aviso = "a personagem saiu cortada na borda (" + ", ".join(lados) + ") — refaça (fica um corte reto no PNG)"
    elif not toca_baixo:
        aviso = "a personagem não encosta na borda de baixo (corpo inteiro?) — confira o enquadramento"
    return out, {"escala": round(k, 3), "caixa": list(caixa), "cortada_embaixo": toca_baixo, "cortada_lados": lados, "aviso": aviso}


def alfa_do_verde(img: Image.Image) -> Image.Image:
    """Alfa inicial sem modelo de recorte: tudo é personagem, menos o verde do fundo. Além da chave forte (que o
    `limpar` aplica), o verde mais escuro/sombreado ou mais claro que ENCOSTA na borda da imagem também sai
    (degradê ou sombra que o gerador às vezes põe no fundo)."""
    import numpy as np
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    outro = np.maximum(r, b)
    a = np.ones(g.shape, np.float32)
    esverdeado = (g >= 45) & (g > outro + 22) & (g > outro * 1.25)
    try:
        import cv2
    except ImportError:
        cv2 = None
    if cv2 is not None:
        n, lab, stats, _c = cv2.connectedComponentsWithStats(esverdeado.astype(np.uint8), connectivity=8)
        h, w = g.shape
        borda = np.zeros(n, bool)
        for arr in (lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]):
            borda[np.unique(arr)] = True
        borda[0] = False
        grande = stats[:, cv2.CC_STAT_AREA] >= max(400, int(h * w * 0.002))  # mancha verde grande fechada (vão do braço)
        grande[0] = False
        a[(borda | grande)[lab]] = 0.0
    else:
        a[esverdeado & (g >= 90)] = 0.0
    return Image.fromarray((a * 255).astype(np.uint8), "L")


def recortar(img: Image.Image, canvas: Tuple[int, int] = (1200, 1800), altura_personagem: float = 0.95,
             opcoes: Optional[Dict[str, Any]] = None) -> Tuple[Image.Image, Dict[str, Any]]:
    """Imagem do Flow (fundo verde) → PNG RGBA no canvas fixo + o que foi feito (avisos)."""
    o = dict(opcoes or {})
    o["fundo"] = "verde"
    alfa = alfa_do_verde(img)
    img_l, alfa, feito = limpar(img, alfa, o)
    import numpy as np
    if float(np.asarray(alfa).mean()) > 250:  # quase nada saiu: o fundo não veio verde
        feito["aviso_fundo"] = "o fundo não veio verde — o recorte pode ter falhado (refaça)"
    final, info = alinhar(img_l, alfa, canvas, altura_personagem)
    info["limpeza"] = feito
    if feito.get("aviso_fundo"):
        info["aviso"] = feito["aviso_fundo"] + ("; " + info["aviso"] if info.get("aviso") else "")
    return final, info


def colagem(imagens: List[Image.Image], altura: int = 1024, fundo=(128, 128, 128)) -> Image.Image:
    """As referências lado a lado numa imagem só (o Flow aceita uma referência por pedido)."""
    ims = [i.convert("RGBA") for i in imagens if i is not None]
    if not ims:
        raise ValueError("sem imagens pra colagem")
    if len(ims) == 1:
        base = Image.new("RGB", ims[0].size, fundo)
        base.paste(ims[0], (0, 0), ims[0])
        return base
    esc = [i.resize((max(1, round(i.width * altura / i.height)), altura), Image.LANCZOS) for i in ims]
    gap = 24
    out = Image.new("RGB", (sum(i.width for i in esc) + gap * (len(esc) - 1), altura), fundo)
    x = 0
    for i in esc:
        out.paste(i, (x, 0), i)
        x += i.width + gap
    larg_max = 2048
    if out.width > larg_max:
        out = out.resize((larg_max, max(1, round(out.height * larg_max / out.width))), Image.LANCZOS)
    return out
