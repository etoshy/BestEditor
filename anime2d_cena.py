"""🎬 Animação 2D — o motor que monta cada momento como um PLANO de anime (v84_238).

O que mudou em relação ao "personagens parados em fila sobre o fundo":
- 🎥 Cada momento é um CORTE de câmera: 'geral' (o cenário inteiro), 'medio' (da cintura pra cima de quem está em foco),
  'close' (o rosto — usa o 🙂 busto do personagem) e 'reacao' (o rosto num fundo abstrato: linhas, brilho, sombrio,
  impacto). O plano médio/close é um RECORTE do mesmo cenário em volta de quem está em foco — então cada corte mostra
  uma parte diferente do mesmo lugar (a constância do cenário vem do recorte + câmera, como num anime).
- 🪑 Móveis em camadas: a cadeira ATRÁS de quem senta, a mesa NA FRENTE — o fundo vem sem eles. Os LUGARES do cenário
  (onde cada um fica em pé ou sentado, com a escala da perspectiva) vêm do 📐 Montar o cenário.
- 👣 Ninguém flutua: cada pose é recortada rente ao desenho (os pés no chão do lugar) e ganha uma sombra suave no chão.
- 🚶 Quem muda de lugar ANDA até lá (quadros de andar enquanto desliza) e quem entra no meio da cena entra andando.
- 🔁 Sem loop: a pose fica parada (como num anime), com o 2º quadro só na TRANSIÇÃO de uma pose pra outra, as
  'poses_seguintes' tocando em sequência, a boca mexendo só na fala e uma piscada de vez em quando.
A mesma lista de camadas alimenta o editor (render) e a 👁 prévia — o que você vê é o que sai.
"""
from __future__ import annotations

import hashlib
import math
import os
import random
import shutil
from typing import Any, Dict, List, Optional, Tuple

import anime2d as A
import react_personagens as R

ZOOM_PLANO = {"geral": 1.0, "medio": 1.75, "close": 2.6}
ALT_PADRAO = {True: 0.62, False: 0.40}   # altura de quem está em pé no chão da frente (fração da altura do vídeo; 16:9 / 9:16)
SENTADO_ALT = 0.70                        # sentado ≈ 70% da altura em pé
MEIO_ALT = 0.50                           # da cintura pra cima (atrás da mesa) ≈ metade da altura em pé
SOMBRA_PAD = 0.045
TRANSICAO = 0.14                          # s do 2º quadro na troca de pose
PASSO = 0.16                              # s de cada quadro do andar
PISCA = 0.11
# 🎬 v84_238c — ritmo de anime (Jashin-chan): nenhum plano fica parado muito tempo; uma fala longa vira cobertura
# (quem fala → quem escuta → o plano aberto), todo mundo "respira" e reage com um pulinho, impacto pisca branco.
CORTE_MAX = 3.4                           # s: um plano mais longo que isso vira 2–4 cortes
CORTE_ALVO = 2.3                          # s: o tamanho de cada corte da cobertura
RESP = 0.0035                             # 🫁 amplitude da respiração (fração da altura do vídeo)
PULO = 0.03                               # 🦘 altura do pulinho de reação
PULO_DUR = 0.28
ABERTURA_DUR = 2.5                        # 🔤 s em que o texto de abertura (p['abertura_texto']) fica na tela
FLASH = 0.07                              # 💥 s do quadro branco no impacto (câmera tremida)
_REAGE = ("choc", "assust", "surpre", "feliz", "rindo", "bravo", "irrit", "envergonh", "shock", "surpris", "startl",
          "jump", "excit", "angry", "pleading", "slamm", "flust")


def cobertura(p: Dict[str, Any], ms: List[Dict[str, Any]], ts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """🎬 Os momentos → os CORTES. Fala/narração longa num plano parado vira cobertura de anime: o plano pedido, o close
    de quem fala, o médio de quem escuta (reação), o aberto. Cada corte = cópia do momento com 'corte_ini' e 'corte'
    (0 = o original; os outros não repetem legenda, tremida, som). Desliga com p['cobertura'] = False ou
    momento['cobertura'] = False."""
    out: List[Dict[str, Any]] = []
    for j, m in enumerate(ms):
        ini = float(ts["ini"]) if j == 0 else float(m["ini"])
        fim = float(ms[j + 1]["ini"]) if j + 1 < len(ms) else float(ts["fim"])
        m0 = dict(m, corte_ini=ini, corte=0)
        em = [e["cid"] for e in m.get("em_cena") or []]
        dur = fim - ini
        if (not p.get("cobertura", True) or m.get("cobertura") is False or dur <= CORTE_MAX or not em
                or m["tipo"] not in ("fala", "narracao") or m.get("destaque") or m.get("plano") == "reacao"
                or (m.get("video") or {}).get("estado") == "pronta"):
            out.append(m0)
            continue
        n = min(4, max(2, round(dur / CORTE_ALVO)))
        foco = A.foco_do_momento(m)
        outros = [c for c in em if c != foco]
        pl0 = m.get("plano") if m.get("plano") in A.PLANOS else "geral"
        if m["tipo"] == "fala" and outros:
            cand = [("close" if pl0 != "close" else "medio", foco), ("medio", outros[0]), ("geral" if pl0 != "geral" else "close", foco)]
        else:
            cand = [("medio" if pl0 != "medio" else "close", foco), ("close" if pl0 != "close" else "geral", foco), ("geral", foco)]
        seq = [(pl0, foco)]
        for x in cand:
            if len(seq) >= n:
                break
            if x != seq[-1]:
                seq.append(x)
        for k, (pl, f) in enumerate(seq):
            sub = dict(m0, plano=pl, foco=f, corte_ini=round(ini + dur * k / len(seq), 3), corte=k)
            if k:
                sub["camera"] = "zoom_in" if pl == "close" else "fixa"
                sub["som"] = ""
            out.append(sub)
    return out


TROCA_ANGULO = 10.0                       # 🎥 s no mesmo ângulo antes de trocar sozinho (p['troca_angulo_s']; 0 = não troca)


def _lugares_proprios(p: Dict[str, Any], lo: Optional[Dict[str, Any]]) -> set:
    lay = A.layout_do_local(p, lo) or {}
    return {A.R._norm(x.get("nome")) for x in lay.get("lugares") or []}


def angulos_auto(p: Dict[str, Any], s: Dict[str, Any], ts: Dict[str, Any], ms: List[Dict[str, Any]]) -> List[Optional[Dict[str, Any]]]:
    """🎥 O cenário de cada corte. O 'angulo' do momento manda; sem ele, depois de ~10 s no mesmo ângulo a câmera troca
    pra outro ÂNGULO do MESMO cômodo e estado (nunca pra uma variante — fumaça/noite é outra coisa), num corte que não
    é destaque — e só pra um ângulo que CONDIZ com o momento: os lugares de quem está em cena existem nele (os lugares
    próprios, ex. “na poltrona”; os padrões esquerda/centro… existem em todos) e, de preferência, o de quem está em foco
    é um lugar próprio dele (a câmera vai pra onde a ação está). Pode repetir ângulo; escolhe o menos usado."""
    lo0 = A.local_da_cena(p, s)
    lim = float(p.get("troca_angulo_s", TROCA_ANGULO) or 0)
    angs = [x for x in p.get("locais") or [] if lo0 is not None and A.angulo_base(p, x) is lo0]
    padrao = {A.R._norm(k) for k in A.POSICOES}

    def condiz(x: Dict[str, Any], m: Dict[str, Any]) -> bool:
        proprios = _lugares_proprios(p, x)
        return all(A.R._norm(e["posicao"]) in proprios or A.R._norm(e["posicao"]) in padrao for e in m.get("em_cena") or [])

    out: List[Optional[Dict[str, Any]]] = []
    atual, desde, usados = lo0, float(ts["ini"]), {}
    for j, m in enumerate(ms):
        ini = float(ts["ini"]) if j == 0 else float(m["corte_ini"])
        if m.get("angulo"):  # escolhido à mão / pela IA
            escolhido = A.local_do_momento(p, s, m)
        else:
            escolhido = atual
            if atual is not lo0 and atual is not None and not condiz(atual, m):
                escolhido = lo0  # quem está em cena não cabe nesse ângulo: volta pra câmera principal
            elif lim > 0 and angs and j > 0 and m.get("tipo") != "destaque" and ini - desde >= lim:
                foco = A.foco_do_momento(m)
                pos_foco = next((A.R._norm(e["posicao"]) for e in m.get("em_cena") or [] if e["cid"] == foco), "")
                cands = [((0 if pos_foco and pos_foco in _lugares_proprios(p, x) else 1), usados.get(x["id"], 0), k, x)
                         for k, x in enumerate([lo0] + angs) if x is not atual and condiz(x, m)]
                if cands:
                    escolhido = min(cands, key=lambda c: c[:3])[3]
        if escolhido is not atual:
            atual, desde = escolhido, ini
            if escolhido is not None:
                usados[escolhido["id"]] = usados.get(escolhido["id"], 0) + 1
        out.append(escolhido)
    return out


def _nu(k: Any) -> str:
    """A pose sem o enquadramento (busto_/meio_) — trocar de plano não é trocar de emoção."""
    k = str(k or "")
    return k[6:] if k.startswith("busto_") else k[5:] if k.startswith("meio_") else k


def _flash(p: Dict[str, Any], base: str, W: int, H: int) -> str:
    from PIL import Image
    dst = os.path.join(_dir(p, base), f"flash_{W}x{H}.png")
    if not os.path.isfile(dst):
        Image.new("RGB", (W, H), (255, 255, 255)).save(dst)
    return dst


# ------------------------------------------------------------------ cache de imagens
def _dir(p: Dict[str, Any], base: str) -> str:
    d = os.path.join(A.pasta(p["id"], base), "imagens", "_cena")
    os.makedirs(d, exist_ok=True)
    return d


def _chave(*partes: Any) -> str:
    h = hashlib.sha1()
    for x in partes:
        if isinstance(x, str) and os.path.isfile(x):
            h.update(f"{x}:{os.path.getmtime(x)}".encode())
        else:
            h.update(repr(x).encode())
    return h.hexdigest()[:16]


def _png_ok(cam: str) -> bool:
    try:
        from PIL import Image
        with Image.open(cam) as im:
            im.verify()
        return True
    except Exception:  # noqa: BLE001
        return False


def recorte_grupo(p: Dict[str, Any], base: str, imgs: Dict[str, Optional[str]], sombra: bool) -> Dict[str, Any]:
    """As imagens de UMA pose (a pose, o 2º quadro, a boca, a piscada — mesmo quadro) recortadas juntas rente ao desenho
    (a mesma caixa: encaixam umas nas outras) e, em pé, com a sombra no chão. → {"img": {k: caminho}, "pad": fração
    da altura que é sombra embaixo dos pés, "ar": largura/altura}."""
    from PIL import Image, ImageDraw, ImageFilter
    imgs = {k: v for k, v in imgs.items() if v and os.path.isfile(v)}
    if not imgs:
        return {"img": {}, "pad": 0.0, "ar": 0.5}
    k0 = "pose" if "pose" in imgs else next(iter(imgs))
    chave = _chave(sorted(imgs.items()), sombra, "v3")
    d = _dir(p, base)
    meta = os.path.join(d, f"g_{chave}.txt")
    alvo = {k: os.path.join(d, f"g_{chave}_{k}.png") for k in imgs}
    if os.path.isfile(meta) and all(os.path.isfile(v) and _png_ok(v) for v in alvo.values()):
        pad, ar = (float(x) for x in open(meta).read().split())
        return {"img": alvo, "pad": pad, "ar": ar}
    ims = {k: Image.open(v).convert("RGBA") for k, v in imgs.items()}
    tam = ims[k0].size
    caixa = None
    for k, im in ims.items():
        if im.size != tam:
            continue
        bb = im.getchannel("A").point(lambda a: 255 if a > 24 else 0).getbbox()
        if bb:
            caixa = bb if caixa is None else (min(caixa[0], bb[0]), min(caixa[1], bb[1]), max(caixa[2], bb[2]), max(caixa[3], bb[3]))
    caixa = caixa or (0, 0, tam[0], tam[1])
    w, h = caixa[2] - caixa[0], caixa[3] - caixa[1]
    pad = int(h * SOMBRA_PAD) if sombra else 0
    base_im = ims[k0].crop(caixa)
    camada_sombra = None
    if sombra:  # a largura dos pés (o desenho nas linhas de baixo)
        a = base_im.getchannel("A")
        faixa = a.crop((0, int(h * 0.94), w, h)).point(lambda v: 255 if v > 24 else 0).getbbox()
        x0, x1 = (faixa[0], faixa[2]) if faixa else (int(w * 0.3), int(w * 0.7))
        cx, larg = (x0 + x1) / 2, max(w * 0.35, (x1 - x0) * 1.35)
        camada_sombra = Image.new("RGBA", (w, h + pad), (0, 0, 0, 0))
        ry = max(2.0, pad * 0.55)
        ImageDraw.Draw(camada_sombra).ellipse([cx - larg / 2, h - ry * 0.7, cx + larg / 2, h + ry], fill=(0, 0, 0, 70))
        camada_sombra = camada_sombra.filter(ImageFilter.GaussianBlur(max(2, ry * 0.6)))
    for k, im in ims.items():
        c = im.crop(caixa) if im.size == tam else im
        tela = Image.new("RGBA", (w, h + pad), (0, 0, 0, 0))
        if camada_sombra is not None:
            tela.alpha_composite(camada_sombra)
        tela.alpha_composite(c, (0, 0))
        tmp = alvo[k] + ".tmp.png"  # salva inteiro e troca de uma vez (nunca um PNG pela metade no cache)
        tela.save(tmp)
        os.replace(tmp, alvo[k])
    frac = pad / float(h + pad)
    with open(meta, "w") as f:
        f.write(f"{frac} {w / float(h + pad)}")
    return {"img": alvo, "pad": frac, "ar": w / float(h + pad)}


def fundo_cortado(p: Dict[str, Any], base: str, cam: Optional[str], x0: float, y0: float, z: float, W: int, H: int) -> Optional[str]:
    """O pedaço do cenário que o plano mostra (o mesmo fundo, outra parte — como um anime faz)."""
    if not cam:
        return None
    if z <= 1.001:
        return cam
    from PIL import Image
    d = _dir(p, base)
    dst = os.path.join(d, f"f_{_chave(cam, round(x0), round(y0), round(z, 3), W, H)}.jpg")
    if os.path.isfile(dst):
        return dst
    im = Image.open(cam).convert("RGB")
    k = max(W / im.width, H / im.height)
    im = im.resize((max(W, round(im.width * k)), max(H, round(im.height * k))), Image.LANCZOS)
    im = im.crop(((im.width - W) // 2, (im.height - H) // 2, (im.width - W) // 2 + W, (im.height - H) // 2 + H))
    im.crop((round(x0), round(y0), round(x0 + W / z), round(y0 + H / z))).resize((W, H), Image.LANCZOS).save(dst, quality=92)
    return dst


def fundo_reacao(p: Dict[str, Any], base: str, tipo: str, W: int, H: int) -> str:
    """💥 O fundo abstrato das reações (desenhado aqui, igual em todo o episódio): linhas de velocidade, brilho, sombrio,
    impacto — colorido ou P&B conforme o estilo."""
    from PIL import Image, ImageDraw, ImageFilter
    mono = p.get("estilo") in ("manga_pb", "manga_tinta")
    tipo = tipo if tipo in A.FUNDOS_REACAO else "linhas"
    dst = os.path.join(_dir(p, base), f"r_{tipo}_{'m' if mono else 'c'}_{W}x{H}_v1.jpg")
    if os.path.isfile(dst):
        return dst
    rnd = random.Random(f"{tipo}{W}{H}")
    cores = {"linhas": ((70, 130, 230), (190, 225, 255)), "brilho": ((255, 190, 220), (255, 245, 210)),
             "sombrio": ((40, 30, 70), (95, 80, 140)), "impacto": ((220, 60, 30), (255, 210, 90))}[tipo]
    if mono:
        cores = {"linhas": ((60, 60, 60), (230, 230, 230)), "brilho": ((200, 200, 200), (255, 255, 255)),
                 "sombrio": ((15, 15, 15), (90, 90, 90)), "impacto": ((20, 20, 20), (245, 245, 245))}[tipo]
    im = Image.new("RGB", (W, H))
    dr = ImageDraw.Draw(im)
    for y in range(H):  # degradê
        t = y / H
        dr.line([(0, y), (W, y)], fill=tuple(int(cores[0][i] + (cores[1][i] - cores[0][i]) * t) for i in range(3)))
    cx, cy = W / 2, H * 0.45
    if tipo in ("linhas", "impacto"):  # raios do centro
        n = 90 if tipo == "linhas" else 48
        for i in range(n):
            ang = 2 * math.pi * i / n + rnd.uniform(-0.03, 0.03)
            r0 = rnd.uniform(0.18, 0.32) * W
            larg = rnd.uniform(0.004, 0.012 if tipo == "linhas" else 0.03)
            pts = [(cx + math.cos(ang) * r0, cy + math.sin(ang) * r0),
                   (cx + math.cos(ang - larg) * W * 1.2, cy + math.sin(ang - larg) * W * 1.2),
                   (cx + math.cos(ang + larg) * W * 1.2, cy + math.sin(ang + larg) * W * 1.2)]
            dr.polygon(pts, fill=(255, 255, 255) if tipo == "linhas" else (255, 240, 200) if not mono else (255, 255, 255))
    elif tipo == "sombrio":  # linhas verticais caindo
        for _ in range(160):
            x = rnd.uniform(0, W)
            y0 = rnd.uniform(-H * 0.2, H * 0.5)
            dr.line([(x, y0), (x, y0 + rnd.uniform(H * 0.2, H * 0.7))], fill=(200, 200, 230) if not mono else (170, 170, 170),
                    width=rnd.choice((1, 2, 2, 3)))
        im = im.filter(ImageFilter.GaussianBlur(0.6))
    else:  # brilho: bolhas e estrelinhas
        camada = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dc = ImageDraw.Draw(camada)
        for _ in range(70):
            r = rnd.uniform(W * 0.01, W * 0.06)
            x, y = rnd.uniform(0, W), rnd.uniform(0, H)
            dc.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, rnd.randint(50, 140)))
        for _ in range(40):
            x, y, r = rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(W * 0.006, W * 0.018)
            dc.polygon([(x, y - r * 2.5), (x + r * 0.5, y), (x, y + r * 2.5), (x - r * 0.5, y)], fill=(255, 255, 255, 220))
            dc.polygon([(x - r * 2.5, y), (x, y - r * 0.5), (x + r * 2.5, y), (x, y + r * 0.5)], fill=(255, 255, 255, 220))
        camada = camada.filter(ImageFilter.GaussianBlur(1.2))
        im = Image.alpha_composite(im.convert("RGBA"), camada).convert("RGB")
    im.save(dst, quality=90)
    return dst


# ------------------------------------------------------------------ geometria
def alt_base(p: Dict[str, Any], lo: Optional[Dict[str, Any]]) -> float:
    W, H = A.tamanho(p)
    return float(((lo or {}).get("chao") or {}).get("alt") or ALT_PADRAO[W > H])


def props_do_local(p: Dict[str, Any], lo: Optional[Dict[str, Any]], base: str) -> List[Dict[str, Any]]:
    """🪑 Os móveis com imagem pronta: {nome, arquivo, camada, x, y (base), w} (frações). A 'camada da frente' antiga
    entra como um móvel da frente embaixo, no meio."""
    out = []
    if not lo:
        return out
    W, H = A.tamanho(p)
    alt0 = alt_base(p, lo)
    ab = A.angulo_base(p, lo)
    for pr in lo.get("props") or []:
        cam = A.arquivo_img(p, pr.get("img") or {}, base)
        if not cam and ab is not None:  # 🎥 o mesmo móvel do ângulo principal
            q = next((q for q in ab.get("props") or [] if A.R._norm(q["nome"]) == A.R._norm(pr["nome"])), None)
            cam = A.arquivo_img(p, (q or {}).get("img") or {}, base) if q else None
        if cam:
            y = float(pr.get("y", 1.0 if pr.get("camada") != "atras" else 0.8))
            if pr.get("w_manual") and pr.get("w"):
                w = float(pr["w"])
            else:  # 📏 do tamanho real: largura em metros ÷ 1,65 m (uma pessoa) × a altura de quem está em pé ali
                real = float(pr.get("real") or tamanho_real(pr))
                w = real / 1.65 * alt0 * A.escala_em(lo, y) * H / W
            out.append({"id": pr["id"], "nome": pr["nome"], "arquivo": cam, "camada": pr.get("camada") or "frente",
                        "x": float(pr.get("x", 0.5)), "y": y, "w": w})
    fr = A.arquivo_img(p, lo.get("frente") or {}, base)
    if fr:
        W, H = A.tamanho(p)
        w, h = A._tam_frente(fr, W, H)
        out.append({"id": "frente", "nome": "frente", "arquivo": fr, "camada": "frente", "x": 0.5, "y": 1.01, "w": w / W})
    return out


REAIS = (("mesa|desk|escrivaninha|table", 1.4), ("cadeira|chair|banco|stool", 0.6), ("poltrona|armchair", 0.85),
         ("sofa|sofá|couch", 1.9), ("balc|counter", 2.0), ("cama|bed", 1.1), ("estante|shelf|armario|cabinet", 1.0))


def tamanho_real(pr: Dict[str, Any]) -> float:
    import re
    t = (pr.get("nome") or "") + " " + (pr.get("prompt_en") or "")
    for padrao, m in REAIS:
        if re.search(padrao, t, re.I):
            return m
    return 0.8


def _enquadrar(plano: str, foco: Optional[Dict[str, float]], W: int, H: int) -> Tuple[float, float, float]:
    """(x0, y0, z) da câmera: o recorte do cenário que o plano mostra (geral = tudo)."""
    z = ZOOM_PLANO.get(plano, 1.0)
    if z <= 1.0 or not foco:
        return 0.0, 0.0, 1.0
    topo = foco["base_y"] - foco["alt"]
    fy = topo + foco["alt"] * (0.42 if plano == "medio" else 0.12)
    vw, vh = W / z, H / z
    x0 = min(max(foco["cx"] - vw / 2, 0), W - vw)
    y0 = fy - vh * (0.40 if plano == "medio" else 0.45)
    y0 = min(y0, topo - vh * (0.07 if plano == "medio" else 0.04))  # a cabeça nunca corta
    y0 = min(max(y0, 0), H - vh)
    return x0, y0, z


def _e_sentado(lug: Dict[str, Any], e: Dict[str, Any], pose_key: str) -> bool:
    v = lug.get(e.get("posicao")) or {}
    return bool(v.get("sentado")) or pose_key == "sentado" or ("sitting" in pose_key or "seated" in pose_key or "sit_" in pose_key)


# ------------------------------------------------------------------ o plano (tudo o que entra no vídeo)
def plano(p: Dict[str, Any], base: str) -> Dict[str, Any]:
    W, H = A.tamanho(p)
    tl = A.linha_do_tempo(p, base)
    poses = {c["id"]: A.poses_prontas(c, base) for c in p["personagens"]}
    pers = {c["id"]: c for c in p["personagens"]}
    out: Dict[str, Any] = {"W": W, "H": H, "duracao": tl["duracao"], "tl": tl, "fundos": [], "figs": [], "objetos": [], "frentes": [],
                           "destaques": [], "legendas": [], "avisos": [], "videos": [], "tremidas": [],
                           "paralaxe": bool(p.get("paralaxe", True)), "camadas": []}
    faltando: Dict[str, set] = {}
    grupos: Dict[Any, Dict[str, Any]] = {}

    def grupo(cid: str, key: str, sombra: bool) -> Optional[Dict[str, Any]]:
        pc = poses.get(cid) or {}
        x = pc.get(key)
        if not x:
            return None
        g = (cid, key, sombra)
        if g not in grupos:
            grupos[g] = recorte_grupo(p, base, {"pose": x.get("pose"), "b": x.get("b"), "boca": x.get("boca"), "pisca": x.get("pisca")}, sombra)
        return grupos[g] if grupos[g]["img"].get("pose") else None

    camadas = out["camadas"]
    for s, ts in zip(p["cenas"], tl["cenas"]):
        ctx_cache: Dict[Any, Tuple[Any, ...]] = {}

        def ctx(lo_: Optional[Dict[str, Any]]) -> Tuple[Any, ...]:
            """O cenário do momento já pronto: arranjo, lugares, fundo, móveis e a altura de quem está em pé."""
            k_ = (lo_ or {}).get("id")
            if k_ not in ctx_cache:
                lay_ = A.layout_do_local(p, lo_)  # 🌫 a variante usa os móveis/lugares/chão do original
                bg_ = A.arquivo_img(p, (lo_ or {}).get("img") or {}, base) if lo_ else None
                if lo_ and not bg_:
                    av = f"🏞 {lo_['nome']}: sem a imagem do fundo — usei um degradê"
                    if av not in out["avisos"]:
                        out["avisos"].append(av)
                ctx_cache[k_] = (lay_, A.lugares_do_local(p, lay_), bg_, props_do_local(p, lay_, base), alt_base(p, lay_) * H)
            return ctx_cache[k_]
        antes: Dict[str, Dict[str, Any]] = {}  # cid → {"lugar", "key", "x"}
        ms = cobertura(p, ts["momentos"], ts)
        los = angulos_auto(p, s, ts, ms)  # 🎥 o cenário de cada corte (o escolhido ou a troca automática de ângulo)
        lo_ant = None
        for j, m in enumerate(ms):
            lo = los[j]
            lay, lug, bg, props, alt0 = ctx(lo)
            troca_angulo = j > 0 and (lo or {}).get("id") != (lo_ant or {}).get("id")
            if troca_angulo:  # outro ângulo: ninguém "anda" de um lugar do outro ângulo
                antes = {}
            lo_ant = lo
            # o plano vai do começo do corte até o começo do próximo (sem buraco nas pausas entre as falas)
            ini = float(ts["ini"]) if j == 0 else float(m["corte_ini"])
            fim = float(ms[j + 1]["corte_ini"]) if j + 1 < len(ms) else float(ts["fim"])
            corte = int(m.get("corte") or 0)
            pl = m.get("plano") if m.get("plano") in A.PLANOS else "geral"
            if m["tipo"] == "destaque":
                pl = "geral"
            foco_cid = A.foco_do_momento(m)
            # onde cada um está (no cenário inteiro)
            geo: Dict[str, Dict[str, Any]] = {}
            for e in m.get("em_cena") or []:
                if e["cid"] not in pers:
                    continue
                v = lug.get(e["posicao"]) or lug.get("centro")
                k0 = A.chave_pose(lug, e)
                sent = _e_sentado(lug, e, k0)
                meio = v.get("corpo") == "cintura"
                alt = alt0 * float(v.get("escala") or 1.0) * (MEIO_ALT if meio else SENTADO_ALT if sent else 1.0)
                geo[e["cid"]] = {"cx": float(v["x"]) * W, "base_y": float(v["y"]) * H, "alt": alt, "sentado": sent or meio, "e": e,
                                 "lugar": e["posicao"], "meio": meio}
            foco = geo.get(foco_cid)
            if pl in ("close", "reacao") and not foco:
                pl = "geral"
            x0, y0, z = _enquadrar(pl if pl in ZOOM_PLANO else "geral", foco, W, H)
            if pl == "reacao":
                arq_fundo = fundo_reacao(p, base, m.get("fundo_reacao") or "linhas", W, H)
            else:
                arq_fundo = fundo_cortado(p, base, bg, x0, y0, z, W, H)
            out["fundos"].append({"cena": s["id"], "momento": m["id"], "ini": ini, "fim": fim, "arquivo": arq_fundo,
                                  "camera": m.get("camera") or "fixa", "nome": (lo or {}).get("nome") or "?", "plano": pl})

            def T(x: float, y: float) -> Tuple[float, float]:
                return (x - x0) * z, (y - y0) * z
            if m.get("camera") == "tremida":
                out["tremidas"].append({"ini": ini, "fim": fim})
                if not corte:  # 💥 o quadro branco do impacto
                    out["destaques"].append({"ini": ini, "fim": ini + FLASH, "arquivo": _flash(p, base, W, H), "flash": True})
            mostrar_cenario = pl in ("geral", "medio", "close") and not (pl == "close" and foco and grupo(foco_cid, "busto_" + A.expressao_busto(foco["e"]["pose"]), False))
            # 🪑 móveis de trás
            if mostrar_cenario:
                for pr in props:
                    if pr["camada"] != "atras":
                        continue
                    cx, by = T(pr["x"] * W, pr["y"] * H)
                    iw, ih = R._tam(pr["arquivo"], (1, 1))
                    w = pr["w"] * W * z
                    camadas.append({"tipo": "prop", "camada": "atras", "img": pr["arquivo"], "a": ini, "b": fim, "cx": cx,
                                    "cy": by - w * ih / iw / 2, "w": w, "esp": False, "nome": f"🪑 {pr['nome']}", "trilha": f"prop:{pr['id']}"})
            # 🧍 personagens (de trás pra frente: quem está mais no fundo primeiro)
            ordem = sorted(geo.items(), key=lambda kv: kv[1]["base_y"])
            for cid, g in ordem:
                e = g["e"]
                c = pers[cid]
                pc = poses.get(cid) or {}
                if not pc:
                    faltando.setdefault(c["nome"], set()).add("todas")
                    continue
                visivel = pl in ("geral", "medio") or cid == foco_cid
                seq = [(e["pose"], e.get("pose_en") or "")] + [(x.get("pose"), x.get("pose_en") or "") for x in e.get("poses") or []]
                keys = []
                for po, en in seq:
                    k = A.chave_pose(lug, e, po, en)
                    if k not in pc:
                        faltando.setdefault(c["nome"], set()).add(k)
                        k = next((q for q in (k[5:] if k.startswith("meio_") else "", "meio_neutro" if g["meio"] else "", "neutro") if q and q in pc),
                                 next(iter(pc)))
                    keys.append(k)
                usa_busto = pl in ("close", "reacao") and cid == foco_cid
                if usa_busto:
                    kb = "busto_" + A.expressao_busto(e["pose"])
                    if kb in pc:
                        keys = [kb]
                    elif pl == "reacao":
                        faltando.setdefault(c["nome"], set()).add(kb)
                # 🚶 andar até o lugar novo / entrar andando
                ant = antes.get(cid)
                anda_de = None
                if pl in ("geral", "medio") and not g["sentado"] and m["tipo"] != "destaque":
                    if ant and ant["lugar"] != g["lugar"] and not ant.get("sentado"):
                        anda_de = ant["x"]
                    elif not ant and j > 0 and not troca_angulo:
                        anda_de = -0.12 * W if g["cx"] < W / 2 else 1.12 * W
                # quadros no tempo
                frames: List[Dict[str, Any]] = []
                t = ini
                if anda_de is not None and visivel:
                    tw = min(max(abs(g["cx"] - anda_de) / W * 1.4, 0.45), 1.1, (fim - ini) * 0.6)
                    ga = grupo(cid, "andando", True) if "andando" in pc else None
                    esp_anda = anda_de > g["cx"]  # indo pra esquerda: espelha (as poses olham pra direita)
                    k = 0
                    while t < ini + tw - 0.02:
                        b = min(ini + tw, t + PASSO)
                        if ga:
                            frames.append({"a": t, "b": b, "g": ga, "v": "b" if (k % 2 and ga["img"].get("b")) else "pose", "esp": esp_anda,
                                           "key": "andando", "anda": True})
                        else:
                            gk = grupo(cid, keys[0], not g["sentado"])
                            frames.append({"a": t, "b": b, "g": gk, "v": "pose", "esp": e["olha"] == "esquerda", "key": keys[0], "anda": True})
                        t, k = b, k + 1
                    if not ga:
                        faltando.setdefault(c["nome"], set()).add("andando")
                    desloc = {"a": round(ini, 3), "b": round(ini + tw, 3), "z": round(fim, 3),
                              "de": round((anda_de - g["cx"]) * z / W, 4), "para": 0.0}
                else:
                    desloc = None
                # as poses em sequência (com o 2º quadro só na transição) + piscadas
                resto = fim - t
                n = len(keys)
                pulos: List[float] = []
                pose_ant = (ant or {}).get("key")
                for i, k in enumerate(keys):
                    gk = grupo(cid, k, not g["sentado"] and not k.startswith("busto_"))
                    if not gk:
                        continue
                    a_i = t + resto * i / n
                    b_i = t + resto * (i + 1) / n
                    esp = e["olha"] == "esquerda"
                    cur = a_i
                    pedida = " ".join(str(x or "") for x in (seq[i] if i < len(seq) else (k,))).lower()
                    pedida_ant = (" ".join(str(x or "") for x in seq[i - 1]) if i else (ant or {}).get("pedida", "")).lower()
                    if (ant or i) and pedida != pedida_ant and any(r in pedida for r in _REAGE):
                        pulos.append(round(a_i, 3))  # 🦘 mudou pra uma emoção forte: pulinho
                    if gk["img"].get("b") and k != pose_ant and b_i - a_i > 0.6:
                        frames.append({"a": cur, "b": cur + TRANSICAO, "g": gk, "v": "b", "esp": esp, "key": k})
                        cur += TRANSICAO
                    if gk["img"].get("pisca") and b_i - cur > 1.6:
                        rnd = random.Random(f"{cid}{m['id']}{i}")
                        tp = cur + rnd.uniform(0.9, 2.2)
                        while tp + PISCA < b_i - 0.3:
                            frames.append({"a": cur, "b": tp, "g": gk, "v": "pose", "esp": esp, "key": k})
                            frames.append({"a": tp, "b": tp + PISCA, "g": gk, "v": "pisca", "esp": esp, "key": k})
                            cur = tp + PISCA
                            tp = cur + rnd.uniform(2.4, 4.2)
                    frames.append({"a": cur, "b": b_i, "g": gk, "v": "pose", "esp": esp, "key": k})
                    pose_ant = k
                if not frames:
                    continue
                # 👄 a boca nas janelas de fala (só quando o quadro é a pose)
                falando = m["tipo"] == "fala" and m["quem"] == cid
                jan = R._boca_janelas(m["ini"], m.get("fala_fim") or m["fim"]) if falando else []
                # compat: o resumo do personagem nesse momento (a prévia antiga e os testes usam)
                kp = keys[0]
                pp_ = pc.get(kp) or {}
                out["figs"].append({"cid": cid, "nome": c["nome"], "ini": ini, "fim": fim, "pose": pp_.get("pose"), "b": pp_.get("b"),
                                    "boca": pp_.get("boca") if falando else None, "fala": [m["ini"], m.get("fala_fim") or m["fim"]] if falando else None,
                                    "cx": g["cx"], "base_y": g["base_y"], "alt": g["alt"], "espelhar": e["olha"] == "esquerda",
                                    "pose_nome": kp, "plano": pl})
                if not visivel:
                    continue
                for f in frames:
                    gk = f["g"]
                    if not gk:
                        continue
                    img = gk["img"].get(f["v"]) or gk["img"]["pose"]
                    if usa_busto and f["key"].startswith("busto_"):
                        h = H * 0.95
                        w = h * gk["ar"]
                        cx = min(max(T(g["cx"], 0)[0], W * 0.3), W * 0.7) if pl == "close" else W * 0.5
                        cy = H - h / 2 + H * 0.02
                    else:
                        h = g["alt"] / max(0.05, 1 - gk["pad"]) * z
                        w = h * gk["ar"]
                        if pl == "reacao":  # sem busto: o corpo grande, de baixo pra cima
                            h, w = H * 1.6, H * 1.6 * gk["ar"]
                            cx, cy = W * 0.5, H * 0.8
                        else:
                            cx, by = T(g["cx"], g["base_y"])
                            cy = by - h / 2 + h * gk["pad"]
                    jan_f = []
                    if jan and f["v"] == "pose" and gk["img"].get("boca"):
                        jan_f = [[max(x, f["a"]), min(y, f["b"])] for x, y in jan if min(y, f["b"]) - max(x, f["a"]) > 0.05]
                    camadas.append({"tipo": "fig", "camada": "personagem", "img": img, "a": f["a"], "b": f["b"], "cx": cx, "cy": cy,
                                    "w": w, "esp": f["esp"], "nome": c["nome"], "cid": cid, "expressao": f["key"],
                                    "boca": gk["img"].get("boca") if jan_f else None, "janelas": jan_f,
                                    "desloc": desloc, "anda": bool(f.get("anda")), "pulos": pulos,
                                    "trilha": f"p:{cid}:{round(cx)}:{round(cy)}:{round(w)}:{f['esp']}"})
            # 📦 objeto do momento (no chão, na frente, perto de quem está em foco)
            if m.get("objeto") and pl in ("geral", "medio"):
                it = next((i for i in p["itens"] if i["id"] == m["objeto"]), None)
                cam = A.arquivo_img(p, (it or {}).get("img") or {}, base) if it else None
                if cam:
                    iw, ih = R._tam(cam, (1, 1))
                    onde = A.R._norm((it or {}).get("onde") or "")
                    pr_on = next((q for q in props if onde and A.R._norm(q["nome"]) == onde), None)
                    lg_on = next((v for k_, v in lug.items() if onde and A.R._norm(k_) == onde), None)
                    if pr_on:  # em cima do móvel (no tampo)
                        piw, pih = R._tam(pr_on["arquivo"], (1, 1))
                        pw = pr_on["w"] * W
                        w = pw * 0.3
                        ox, oy = pr_on["x"] * W + pw * 0.12, pr_on["y"] * H - pw * pih / piw * 0.9
                    elif lg_on:
                        w = W * 0.12 * float(lg_on.get("escala") or 1)
                        ox, oy = float(lg_on["x"]) * W, float(lg_on["y"]) * H
                    else:
                        fx = (foco or {}).get("cx", W * 0.5)
                        w = W * 0.12
                        ox = min(max(fx + (W * 0.12 if fx < W * 0.5 else -W * 0.12), W * 0.15), W * 0.85)
                        oy = float((lay or {}).get("chao", {}).get("y") or 0.97) * H
                    cx, by = T(ox, oy)
                    w = w * z
                    camadas.append({"tipo": "obj", "camada": "objeto", "img": cam, "a": ini, "b": fim, "cx": cx, "cy": by - w * ih / iw / 2,
                                    "w": w, "esp": False, "nome": f"📦 {it['nome']}", "trilha": f"obj:{it['id']}:{round(cx)}"})
                    out["objetos"].append({"ini": ini, "fim": fim, "arquivo": cam, "cx": cx, "base_y": by, "w": w})
            # 🪑 móveis da frente
            if mostrar_cenario:
                for pr in props:
                    if pr["camada"] == "atras":
                        continue
                    cx, by = T(pr["x"] * W, pr["y"] * H)
                    iw, ih = R._tam(pr["arquivo"], (1, 1))
                    w = pr["w"] * W * z
                    camadas.append({"tipo": "prop", "camada": "frente", "img": pr["arquivo"], "a": ini, "b": fim, "cx": cx,
                                    "cy": by - w * ih / iw / 2, "w": w, "esp": False, "nome": f"🪑 {pr['nome']}", "trilha": f"prop:{pr['id']}"})
                    if pr["id"] == "frente":
                        out["frentes"].append({"ini": ini, "fim": fim, "arquivo": pr["arquivo"]})
            # 🌟 destaque / 🎞 vídeo / 💬 legenda
            if m.get("destaque"):  # 🌟 também durante uma fala/narração (a imagem cinematográfica, o exemplo)
                it = next((i for i in p["itens"] if i["id"] == m["destaque"]), None)
                cam = A.arquivo_img(p, (it or {}).get("img") or {}, base) if it else None
                if cam:
                    out["destaques"].append({"ini": ini, "fim": fim if m["tipo"] != "destaque" else m["fim"], "arquivo": cam})
                elif it:
                    out["avisos"].append(f"🌟 {it['nome']}: sem imagem — o destaque ficou de fora")
            v = m.get("video") or {}
            if v.get("estado") == "pronta" and v.get("arquivo") and os.path.isfile(os.path.join(A.pasta(p["id"], base), "imagens", v["arquivo"])):
                out["videos"].append({"ini": ini, "fim": m["fim"], "arquivo": os.path.join(A.pasta(p["id"], base), "imagens", v["arquivo"])})
            if m["tipo"] in ("fala", "narracao") and p.get("legendas", True) and not corte:
                cq = pers.get(m["quem"])
                out["legendas"].append({"ini": m["ini"], "fim": (m.get("fala_fim") or m["fim"]) + 0.2, "nome": A.nome_de(p, m["quem"]),
                                        "texto": m["texto"], "cor": (cq or {}).get("cor") or "#ffffff"})
            antes = {cid: {"lugar": g["lugar"], "x": g["cx"], "key": A.chave_pose(lug, g["e"]),
                           "pedida": " ".join(str(x or "") for x in (g["e"]["pose"], g["e"].get("pose_en") or "")),
                           "sentado": g["sentado"]} for cid, g in geo.items()}
    for nome, f in faltando.items():
        f = {x for x in f if x}
        out["avisos"].append(f"🧍 {nome}: " + ("ainda sem poses (🚀 Gerar)" if "todas" in f else
                                                f"sem {', '.join(sorted(f))} — usei outra pose no lugar (🔁 Gerar o que falta)"))
    # 🌄 parallax / tremida por camada (os planos são os momentos)
    for cm in camadas:
        prof = "frente" if cm["camada"] == "frente" else "objeto" if cm["camada"] == "objeto" else "personagem"
        cm["mov"] = A.movimento(out, prof, cm["a"], cm["b"], cm["cx"] / W) + ([cm["desloc"]] if cm.get("desloc") else [])
        if cm["tipo"] == "fig" and not cm.get("anda"):  # 🫁 vivo o tempo todo (fase por personagem; mesma janela → junta na trilha)
            fase = (sum(map(ord, cm.get("cid") or "")) % 628) / 100
            cm["mov"].append({"a": 0.0, "b": 99999.0, "resp": RESP * (0.6 if cm["w"] > W * 0.5 else 1.0), "f": round(fase, 2)})
            for t0 in cm.get("pulos") or []:
                if cm["a"] - PULO_DUR < t0 < cm["b"]:
                    cm["mov"].append({"a": t0, "b": round(t0 + PULO_DUR, 3), "pulo": PULO})
    return out


# ------------------------------------------------------------------ editor e prévia
def montar_editor(p: Dict[str, Any], base: str, job_dir: str) -> Dict[str, Any]:
    if not any(s.get("momentos") for s in p["cenas"]):
        raise A.AnimeErro("Escreva as cenas primeiro.")
    pl = plano(p, base)
    W, H = pl["W"], pl["H"]
    d = os.path.join(job_dir, "anime2d")
    os.makedirs(d, exist_ok=True)
    audio = A.montar_audio(p, pl["tl"], os.path.join(job_dir, "narracao.wav"), base)
    copiados: Dict[str, str] = {}

    def copiar(cam: str) -> str:
        if cam not in copiados:
            dst = os.path.join(d, f"{len(copiados):04d}_{os.path.basename(cam)}")
            tmp = f"{dst}.{os.getpid()}.tmp"
            shutil.copyfile(cam, tmp)  # copia inteiro e troca de uma vez (duas montagens ao mesmo tempo não se atropelam)
            os.replace(tmp, dst)
            copiados[cam] = dst
        return copiados[cam]

    segs = []
    for k, f in enumerate(pl["fundos"]):
        if f["fim"] - f["ini"] < 0.02:
            continue
        cam = copiar(f["arquivo"]) if f["arquivo"] else A._fundo_degrade(os.path.join(d, f"degrade_{k}.png"), W, H)
        zd = A.CAMERAS.get(f["camera"], "static")
        abre = (p.get("abertura_texto") or "").strip()  # 🔤 o texto do começo (ex.: "Prólogo") — editável no editor
        segs.append({"start": f["ini"], "end": f["fim"], "provider": "material", "query": f"🎞 {f['nome']} · {f['plano']}"[:150],
                     "on_screen_text": abre if abre and f["ini"] < ABERTURA_DUR else None,
                     **({"on_screen_text_style": {"position": "top-center"}} if abre and f["ini"] < ABERTURA_DUR else {}), "media_type": "image", "zoom_direction": zd, "efeito": None,
                     "override_source": {"source": "local_file", "value": cam, "kind": "image", "zoom_direction": zd,
                                         "focus_x": 0.5, "focus_y": 0.5}})
    overlays: List[Dict[str, Any]] = []

    def png(oid: str, nome: str, cam: str, cx: float, cy: float, w: float, ini: float, fim: float, camada: str, **extra: Any) -> None:
        ov = {"id": oid, "origem": "react", "camada": camada, "personagem": f"anime2d_{camada}", "nome_personagem": nome,
              "source": {"source": "local_file", "value": cam, "kind": "image"}, "media_type": "image",
              "start": round(ini, 3), "end": round(fim, 3), "position": "bottom-left", "ancora": "centro",
              "size_percent": R._pct(w, W), "x_percent": R._pct(cx, W), "y_percent": R._pct(cy, H),
              "anim_in": "nenhuma", "anim_out": "nenhuma", "anim_dur": 0.2, "espelhar": False, "boca_path": None,
              "boca_janelas": [], "manual": True}
        ov.update(extra)
        overlays.append(ov)

    for k, cm in enumerate(pl["camadas"]):
        if cm["b"] - cm["a"] < 0.02:
            continue
        extra: Dict[str, Any] = {"espelhar": cm["esp"], "trilha": cm["trilha"], "mov": cm.get("mov") or []}
        if cm["tipo"] == "fig":
            extra.update(cid=cm["cid"], expressao=cm["expressao"], boca_path=copiar(cm["boca"]) if cm.get("boca") else None,
                         boca_janelas=cm.get("janelas") or [])
        png(f"c{k:05d}", cm["nome"], copiar(cm["img"]), cm["cx"], cm["cy"], cm["w"], cm["a"], cm["b"], cm["camada"], **extra)
    for k, ds in enumerate(pl["destaques"]):
        png(f"adest{k}", "🌟 destaque", copiar(ds["arquivo"]), W / 2, H / 2, W, ds["ini"], ds["fim"], "destaque", trilha="destaque")
    for k, v in enumerate(pl["videos"]):
        overlays.append({"id": f"avid{k}", "origem": "react_tela", "camada": "video", "nome_personagem": "🎞 momento animado",
                         "source": {"source": "local_file", "value": copiar(v["arquivo"]), "kind": "video"}, "media_type": "video",
                         "start": round(v["ini"], 3), "end": round(v["fim"], 3), "position": "top-right", "ancora": "centro",
                         "size_percent": 100.0, "x_percent": 50.0, "y_percent": 50.0})
    lw = int(W * (0.82 if W > H else 0.9))
    for k, lg in enumerate(pl["legendas"]):
        cam, w_, h_ = R.desenhar_legenda(lg["nome"], lg["texto"], lg["cor"], lw, os.path.join(d, f"legenda_{k:03d}.png"),
                                         tam=36 if W > H else 44)
        cam, w_, h_ = R._legenda_na_tela(cam, lw)
        topo = H * (0.80 if W > H else 0.72)
        png(f"aleg{k:03d}", f"💬 {lg['nome']}", cam, W / 2, topo + h_ / 2, w_, lg["ini"], lg["fim"], "legenda",
            fala=lg["texto"], trilha="legenda")
    falas = [{"start": lg["ini"], "end": lg["fim"], "text": f"{lg['nome']}: {lg['texto']}"} for lg in pl["legendas"]]
    return {"audio": audio, "duracao": pl["duracao"], "segmentos": segs, "overlays": overlays, "avisos": pl["avisos"], "falas": falas}


def previa(p: Dict[str, Any], base: str, destino: str, t: float, legenda: bool = True) -> str:
    return quadro(plano(p, base), destino, t, legenda)


def quadro(pl: Dict[str, Any], destino: str, t: float, legenda: bool = True) -> str:
    """Um quadro do episódio no segundo t a partir de um plano já calculado (várias prévias sem recalcular o plano)."""
    from PIL import Image, ImageOps
    W, H = pl["W"], pl["H"]
    f = next((x for x in pl["fundos"] if x["ini"] <= t < x["fim"]), pl["fundos"][-1] if pl["fundos"] else None)
    if f and f["arquivo"]:
        tela = A._fundo_com_camera(f["arquivo"], W, H, f.get("camera") or "fixa", (t - f["ini"]) / max(0.001, f["fim"] - f["ini"]))
    else:
        tela = Image.open(A._fundo_degrade(destino + ".fundo.png", W, H)).convert("RGBA")
        os.remove(destino + ".fundo.png")

    def colar(cam: str, cx: float, cy: float, w: float, esp: bool = False, mov: Any = None) -> None:
        if mov:
            ox, oy = A.deslocamento(mov, t, W, H)
            cx, cy = cx + ox, cy + oy
        im = Image.open(cam).convert("RGBA")
        h = w * im.height / im.width
        im = im.resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS)
        if esp:
            im = ImageOps.mirror(im)
        if cx + w / 2 <= 0 or cx - w / 2 >= W or cy + h / 2 <= 0 or cy - h / 2 >= H:
            return  # fora da tela (entrando/saindo andando)
        R._colar_cortando(tela, im, int(cx - w / 2), int(cy - h / 2))

    for cm in pl["camadas"]:
        if not (cm["a"] <= t < cm["b"]):
            continue
        img = cm["img"]
        if cm.get("boca") and any(a <= t < b for a, b in cm.get("janelas") or []) and int((t - cm["a"]) / 0.12) % 2:
            img = cm["boca"]
        colar(img, cm["cx"], cm["cy"], cm["w"], cm["esp"], cm.get("mov"))
    for ds in pl["destaques"]:
        if ds["ini"] <= t < ds["fim"]:
            colar(ds["arquivo"], W / 2, H / 2, W)
    lg = next((x for x in pl["legendas"] if x["ini"] <= t < x["fim"]), None) if legenda else None
    if lg:
        lw = int(W * (0.82 if W > H else 0.9))
        cam, w_, h_ = R.desenhar_legenda(lg["nome"], lg["texto"], lg["cor"], lw, destino + ".leg.png", tam=36 if W > H else 44)
        colar(cam, W / 2, H * (0.80 if W > H else 0.72) + h_ / 2, w_)
        os.remove(cam)
    tela.convert("RGB").save(destino, "JPEG", quality=88)
    return destino
