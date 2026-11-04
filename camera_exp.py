"""🎥 v84_322: câmera EXPERIMENTAL dos curtos de comentário (ligada por padrão nos vídeos novos; desligada = a montagem anterior).

1. 🔍 zoom no detalhe da fala — a cena traz 'zoom_detalhe' (o objeto em inglês); a IA acha o objeto, o rastreio segue e a
   câmera aproxima NELE (suave, seguindo o movimento) → um pedaço pronto Z1, Z2… que o plano usa.
2. 🎯 seta/círculo amarrados aos fatos — no máximo 2 por vídeo, só em detalhe pequeno, 1-3 palavras (o rastreio de sempre).
3. ⏸ congelar no momento-chave — 'congelar': {'texto'} → a imagem para (com um respiro de zoom) e entra um cartão de informação
   → pedaço pronto F1.
4. ritmo por nicho — a regra do prompt (a descrição do canal guia: radical/esporte/fails = impacto; animais/locais = lento;
   arte = revelar).
5. teto — aplicar_teto() corta o excesso depois da IA (entradas, efeito repetido, zooms, congelamentos, destaques).
"""
from __future__ import annotations

import os
import subprocess
from typing import Any, Callable, Dict, List, Optional

MAX_ZOOMS = 3  # 🔍 v84_324: o zoom no detalhe é o efeito principal (o preferido nas prévias)
MAX_CONGELAR = 1
MAX_DESTAQUES = 2
MAX_ENTRADAS = 3

REGRA_CAMERA = (
    "\n\n🎥 CAMERA DIRECTION (experimental) — the camera must SHOW what the narrator says; effects serve the story, never decoration:\n"
    "1. 'zoom_detalhe' (clip cenas only): when the line states a fact about a SPECIFIC DETAIL visible in that moment (the green on "
    "its back, the claw, the brush tip, the cracked board), write that detail in ENGLISH (shape: '<the detail> on/in <the subject>', with THIS clip's own words) — the "
    "camera pushes in on it and follows it. This is your MAIN camera tool — use it on the lines whose fact is about something "
    "visible (usually 1-3 per video, max 3). Only if it is clearly visible in that cena's seconds; otherwise ''.\n"
    "2. 'destaque' (circle/arrow): max 2 per video and ONLY when the detail is small or easy to miss AND the line points at it; "
    "'texto' = 1-3 words naming it ('algae', 'claw'). Never on the same cena as zoom_detalhe or congelar.\n"
    "3. 'congelar': at most ONE per video — the key moment (the impact, the twist, the most surprising fact): {'texto': a 2-7 word "
    "fact card in {LINGUA}, no emoji} and the image freezes while that line is said. Use it RARELY — only when the "
    "video is 20 s or longer AND the fact is the payoff; prefer a zoom_detalhe. Otherwise texto ''.\n"
    "4. RHYTHM BY NICHE — read the channel description and the clip: HIGH ENERGY (extreme sports, sports, fails, feats of "
    "strength): entrada punch_in or shake ON the impact, zoom_rapido at the peak, flash only on the single biggest hit. CALM "
    "(animals, nature, amazing places, travel): efeito zoom_respiro, pan_esq/pan_dir/pan_cima or a slow zoom_in, entrada none / "
    "blur_in / slide_up — no shake, no flash. ART & CRAFTS: slow zoom_in on the technique, zoom_out to REVEAL the finished piece, "
    "pop on the reveal.\n"
    "5. LIMITS: at most 3 entradas other than 'none' per video; never the same efeito on 3 cenas in a row; '' is a good efeito "
    "when the image already moves a lot.")


def ligada(p: Dict[str, Any]) -> bool:
    """Vídeos novos nascem com config.camera_exp = True; projeto antigo (sem a chave) fica como era."""
    return bool((p.get("config") or {}).get("camera_exp"))


def schema_cena_extra(CT) -> Dict[str, Any]:
    return {"zoom_detalhe": CT._s(), "congelar": CT._o({"texto": CT._s()})}


def _limpo(v: Any, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def aplicar_teto(roteiro: Dict[str, Any]) -> Dict[str, Any]:
    """✂ Corta o excesso que a IA pôs (na ordem do vídeo; os primeiros ficam)."""
    zooms = cong = dests = entr = 0
    ultimos: List[str] = []
    for b in roteiro.get("blocos") or []:
        for cn in b.get("cenas") or []:
            clipe = bool(cn.get("material")) and cn.get("de") not in (None, "")
            z = _limpo(cn.get("zoom_detalhe"), 120)
            cg = _limpo((cn.get("congelar") or {}).get("texto") if isinstance(cn.get("congelar"), dict) else "", 60)
            d = (cn.get("destaque") or {}).get("alvo") if isinstance(cn.get("destaque"), dict) else ""
            # 🔍 v84_324: um efeito por cena, nesta ordem — zoom no detalhe (o preferido) > seta/círculo > congelar
            if z and clipe and zooms < MAX_ZOOMS:
                cn["zoom_detalhe"] = z
                zooms += 1
                if d:
                    cn.pop("destaque", None)
                    d = ""
                cg = ""
            else:
                cn.pop("zoom_detalhe", None)
            if d:
                if dests < MAX_DESTAQUES:
                    dests += 1
                    cg = ""
                else:
                    cn.pop("destaque", None)
            if cg and clipe and cong < MAX_CONGELAR:
                cn["congelar"] = {"texto": cg}
                cong += 1
            else:
                cn.pop("congelar", None)
            e = cn.get("entrada") or "none"
            if e != "none":
                if entr >= MAX_ENTRADAS:
                    cn["entrada"] = "none"
                else:
                    entr += 1
            ef = cn.get("efeito") or ""
            if ef and len(ultimos) >= 2 and ultimos[-1] == ultimos[-2] == ef:
                cn["efeito"] = ""
                ef = ""
            ultimos.append(ef)
    return roteiro


def chave(x: Dict[str, Any]) -> str:
    """O pedaço pronto de um plano de clipe com zoom/congelar (muda se o trecho, o alvo ou o texto mudarem)."""
    c = x.get("clipe") or {}
    if not c or "ini" not in c:
        return ""
    if x.get("congelar"):
        return f"F|{c.get('mid')}|{c['ini']}|{c['fim']}|{x['congelar']}|{x.get('enquadrado') or ''}"
    if x.get("zoom_detalhe"):
        return f"Z|{c.get('mid')}|{c['ini']}|{c['fim']}|{x['zoom_detalhe']}|{x.get('enquadrado') or ''}"
    return ""


# ------------------------------------------------------------------ render
def _ease(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)  # smoothstep


def _escritor(saida: str, w: int, h: int, fps: float):
    return subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.3f}",
                             "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", saida],
                            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)


def _suavizar(pts: List[Optional[tuple]], janela: int) -> List[tuple]:
    """Preenche os buracos do rastro e tira o tremido (média móvel larga: a câmera não pode tremer)."""
    n = len(pts)
    ult = next((p for p in pts if p), None)
    cheio = []
    for p in pts:
        if p:
            ult = p
        cheio.append(ult)
    out = []
    for i in range(n):
        a, b = max(0, i - janela), min(n, i + janela + 1)
        viz = [cheio[k] for k in range(a, b)]
        out.append(tuple(sum(v[j] for v in viz) / len(viz) for j in range(len(viz[0]))))
    return out


def render_zoom(entrada: str, saida: str, caixas: List[Optional[List[float]]], fps: float) -> str:
    """🔍 aproxima no objeto (caixas = [x,y,w,h] px por quadro, None onde perdeu): 0→45% do pedaço vai de 1x ao zoom que
    deixa o objeto com ~55% do quadro (1.4x–2.0x), centrando nele; depois segue o objeto com um respiro bem leve."""
    import cv2
    cap = cv2.VideoCapture(entrada)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or len(caixas)
    if not w or not h:
        raise RuntimeError("não li o pedaço")
    caixas = (list(caixas) + [None] * n)[:max(n, 1)]
    if not any(caixas):
        raise RuntimeError("sem caixa")
    centros = _suavizar([((c[0] + c[2] / 2), (c[1] + c[3] / 2), c[2], c[3]) if c else None for c in caixas],
                        max(3, int(fps * 0.35)))
    bw = sorted(c[2] for c in centros)[len(centros) // 2]
    bh = sorted(c[3] for c in centros)[len(centros) // 2]
    zmax = max(1.4, min(2.0, min(w * 0.55 / max(1.0, bw), h * 0.55 / max(1.0, bh))))
    ida = max(1, int(n * 0.45))
    proc = _escritor(saida, w, h, fps)
    i = 0
    try:
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            cx, cy = centros[min(i, len(centros) - 1)][:2]
            u = _ease(i / ida)
            z = 1.0 + (zmax - 1.0) * u + 0.04 * max(0.0, (i - ida) / max(1, n - ida))
            px = w / 2 + (cx - w / 2) * u
            py = h / 2 + (cy - h / 2) * u
            meia_w, meia_h = w / (2 * z), h / (2 * z)  # o recorte nunca sai do quadro
            px = min(max(px, meia_w), w - meia_w)
            py = min(max(py, meia_h), h - meia_h)
            m = [[z, 0, w / 2 - px * z], [0, z, h / 2 - py * z]]
            import numpy as np
            out = cv2.warpAffine(fr, np.float32(m), (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
            proc.stdin.write(out.tobytes())
            i += 1
    finally:
        cap.release()
        if proc.stdin:
            proc.stdin.close()
        proc.wait(timeout=600)
    if not os.path.isfile(saida) or i == 0:
        raise RuntimeError("o zoom não saiu")
    return saida


def _fonte(px: int):
    from PIL import ImageFont
    raiz = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
    for f in ("dp/montserrat-Bold.ttf", "dp/poppins-Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(os.path.join(raiz, f), px)
        except OSError:
            continue
    return ImageFont.load_default()


def cartao_png(texto: str, w: int, h: int, cor: str = "#FFD23F"):
    """🃏 o cartão de informação (RGBA do tamanho do quadro, só o cartão desenhado): fundo escuro translúcido, barra de cor
    à esquerda, texto branco em até 3 linhas que cabe na largura."""
    from PIL import Image, ImageDraw, ImageFilter
    lado = min(w, h)
    larg_max = int(w * 0.80)
    tam = int(lado * 0.07)
    pal = texto.split()
    while True:
        f = _fonte(tam)
        linhas, atual = [], ""
        for p_ in pal:
            t = (atual + " " + p_).strip()
            if f.getlength(t) <= larg_max - int(lado * 0.11) or not atual:
                atual = t
            else:
                linhas.append(atual)
                atual = p_
        if atual:
            linhas.append(atual)
        if len(linhas) <= 3 or tam < lado * 0.035:
            break
        tam = int(tam * 0.9)
    alt_l = int(tam * 1.22)
    pad = int(lado * 0.035)
    barra = int(lado * 0.014)
    cw = min(larg_max, int(max(f.getlength(l) for l in linhas)) + 2 * pad + barra + pad // 2)
    ch = alt_l * len(linhas) + 2 * pad - int(tam * 0.2)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sombra = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    x0, y0 = (w - cw) // 2, 0
    ImageDraw.Draw(sombra).rounded_rectangle([x0 + 6, y0 + 10, x0 + cw + 6, y0 + ch + 10], radius=int(pad * 0.8), fill=(0, 0, 0, 120))
    sombra = sombra.filter(ImageFilter.GaussianBlur(lado * 0.012))
    img.alpha_composite(sombra)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y0, x0 + cw, y0 + ch], radius=int(pad * 0.8), fill=(14, 16, 22, 222))
    rgb = tuple(int(cor.lstrip("#")[k:k + 2], 16) for k in (0, 2, 4))
    d.rounded_rectangle([x0, y0, x0 + barra, y0 + ch], radius=barra // 2, fill=rgb + (255,))
    for k, l in enumerate(linhas):
        d.text((x0 + barra + pad, y0 + pad - int(tam * 0.1) + k * alt_l), l, font=f, fill=(255, 255, 255, 255))
    return img.crop((0, 0, w, ch + int(lado * 0.04))), ch


def render_congelar(entrada: str, saida: str, texto: str, fps: float, dur: float, y_frac: float = 0.12,
                    movimento_s: float = 0.35) -> str:
    """⏸ o pedaço anda ~0,35 s, CONGELA (flash curtinho + leve dessaturação + respiro de zoom 1→1.06) e o cartão entra
    deslizando; fica até o fim do plano."""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(entrada)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not w or not h:
        raise RuntimeError("não li o pedaço")
    total = max(2, int(round(dur * fps)))
    anda = min(int(movimento_s * fps), total // 3)
    quadros = []
    while len(quadros) <= anda:
        ok, fr = cap.read()
        if not ok:
            break
        quadros.append(fr)
    cap.release()
    if not quadros:
        raise RuntimeError("pedaço vazio")
    parado = quadros[-1].astype(np.float32)
    cinza = cv2.cvtColor(cv2.cvtColor(quadros[-1], cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR).astype(np.float32)
    parado = (parado * 0.8 + cinza * 0.2) * 0.93  # levemente dessaturado e mais escuro: o cartão é o foco
    card, ch = cartao_png(texto, w, h)
    card_np = np.array(card)  # RGBA
    card_bgr = card_np[:, :, [2, 1, 0]].astype(np.float32)
    card_a = card_np[:, :, 3:4].astype(np.float32) / 255.0
    y_base = int(h * y_frac)
    proc = _escritor(saida, w, h, fps)
    try:
        for i in range(total):
            if i < len(quadros) - 1:
                proc.stdin.write(quadros[i].tobytes())
                continue
            k = i - (len(quadros) - 1)  # quadros desde o congelamento
            z = 1.0 + 0.06 * _ease(k / max(1, total - len(quadros)))
            m = np.float32([[z, 0, w / 2 * (1 - z)], [0, z, h / 2 * (1 - z)]])
            fr = cv2.warpAffine(parado, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            flash = max(0.0, 1.0 - k / max(1.0, fps * 0.12)) * 0.55
            if flash > 0:
                fr = fr * (1 - flash) + 255 * flash
            u = _ease(max(0.0, k - fps * 0.06) / (fps * 0.28))  # o cartão entra deslizando de cima
            if u > 0:
                y = y_base - int((1 - u) * h * 0.03)
                y0, y1 = max(0, y), min(h, y + card_np.shape[0])
                if y1 > y0:
                    cy0 = y0 - y
                    a = card_a[cy0:cy0 + (y1 - y0)] * u
                    fr[y0:y1] = fr[y0:y1] * (1 - a) + card_bgr[cy0:cy0 + (y1 - y0)] * a
            proc.stdin.write(np.clip(fr, 0, 255).astype(np.uint8).tobytes())
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.wait(timeout=600)
    if not os.path.isfile(saida):
        raise RuntimeError("o congelamento não saiu")
    return saida


# ------------------------------------------------------------------ preparar (depois do alinhamento, antes do editor)
def _y_cartao(base: str, p: Dict[str, Any], CT) -> float:
    """O cartão foge da legenda: legenda embaixo/meio → cartão no alto; legenda no alto → cartão mais pra baixo."""
    try:
        perfil = CT.perfil_do(base, p)
    except Exception:  # noqa: BLE001
        perfil = {}
    leg = dict((perfil.get("legenda") or {}), **((p.get("config") or {}).get("legenda") or {}))
    pos = str(leg.get("posicao") or "")
    try:
        alt = float(leg.get("altura")) if leg.get("altura") not in (None, "") else None
    except (TypeError, ValueError):
        alt = None
    if pos in ("topo", "cima", "alto") or (alt is not None and alt < 0.4):
        return 0.60
    return 0.12


def preparar(base: str, pid: str, providers: Optional[List[str]] = None, chamar: Optional[Callable[..., Any]] = None,
             on_log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """Pra cada plano com zoom_detalhe/congelar: recorta o pedaço (o vertical já enquadrado, se tiver), faz o efeito e
    guarda como mídia Z/F do projeto. Não achou o objeto / sem IA → o plano fica como era (sem erro)."""
    import curtos as CT
    import curtos_comentario as CC
    import rastreio
    p = CT.carregar(base, pid)
    if not ligada(p):
        return {"feitos": [], "pulados": []}
    perfil = CT.perfil_do(base, p)
    providers = providers or (p.get("config") or {}).get("providers") or CT.PROVIDERS_PADRAO
    planos_v = CT.planos_do_video(p, providers, perfil)
    CT.fixar_trechos_do_clipe(planos_v, {m["id"]: float(m.get("dur") or 0) for m in p.get("midias") or []})
    prontos = dict(p.get("camera_prontos") or {})
    feitos, pulados = [], []
    tmp = os.path.join(CT.pasta(base, pid), "_camera")
    os.makedirs(tmp, exist_ok=True)
    for x in planos_v:
        if not (x.get("zoom_detalhe") or x.get("congelar")):
            continue
        enq = (p.get("enquadrados") or {}).get(CT.chave_enquadrado(x)) or {}
        if enq.get("mid"):
            x["enquadrado"] = enq["mid"]
        k = chave(x)
        if not k:
            continue
        if k in prontos and any(m["id"] == prontos[k] for m in p.get("midias") or []):
            feitos.append(prontos[k])
            continue
        c = x["clipe"]
        if enq.get("mid"):
            mv = next((mm for mm in p.get("midias") or [] if mm["id"] == enq["mid"]), None)
            fonte = CT.caminho_midia(base, p, mv) if mv else None
            ini, fim = 0.0, float((mv or {}).get("dur") or (c["fim"] - c["ini"]))
        else:
            m = next((mm for mm in CC.clipes(base, p) if mm["id"] == c["mid"]), None)
            fonte = m["caminho"] if m else None
            ini, fim = float(c["ini"]), float(c["fim"])
        if not fonte:
            continue
        pedaco = os.path.join(tmp, "pedaco.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ini:.3f}", "-i", fonte, "-t", f"{max(0.3, fim - ini):.3f}", "-an",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", pedaco], capture_output=True, timeout=600)
        if not os.path.isfile(pedaco):
            continue
        try:
            info = rastreio.sondar(pedaco)
        except Exception:  # noqa: BLE001
            continue
        saida = os.path.join(tmp, "saida.mp4")
        try:
            if x.get("congelar"):
                on_log(f"⏸ congelando: “{x['congelar']}”…")
                render_congelar(pedaco, saida, x["congelar"], info["fps"], float(x["end"]) - float(x["start"]), _y_cartao(base, p, CT))
                letra, rot = "F", f"⏸ {x['congelar']}"
            else:
                alvo = x["zoom_detalhe"]
                on_log(f"🔍 procurando “{alvo}” pro zoom…")
                t0 = round(min(info["dur"] * 0.3, max(0.1, info["dur"] - 0.2)), 2)
                caixa = CC.achar_objeto(pedaco, t0, alvo, tmp, chamar, base=base)
                if not caixa:
                    pulados.append({"alvo": alvo, "motivo": "não achei o detalhe"})
                    continue
                try:
                    r = rastreio.rastrear(pedaco, [{"t": t0, "caixa": caixa}], 0, info["dur"], info["fps"])
                    caixas = r.get("caixas") or []
                except Exception:  # noqa: BLE001  (sem rastro: zoom no lugar onde achou)
                    caixas = []
                if not any(caixas):
                    caixas = [caixa] * max(1, int(info["dur"] * info["fps"]))
                on_log(f"🔍 aproximando em “{alvo}”…")
                render_zoom(pedaco, saida, caixas, info["fps"])
                letra, rot = "Z", f"🔍 {alvo}"
        except Exception as exc:  # noqa: BLE001  (o efeito não sai → o plano fica como era)
            pulados.append({"alvo": x.get("zoom_detalhe") or x.get("congelar"), "motivo": str(exc)[:160]})
            continue
        with CT._TRAVA:
            q = CT.carregar(base, pid)
            novo = os.path.join(tmp, f"{letra.lower()}.mp4")
            import shutil
            shutil.copy(saida, novo)
            mm = CT.adicionar_midia(base, q, novo, "video", f"{rot} ({c['mid']} {c['ini']:.1f}-{c['fim']:.1f}s)", letra)
            q.setdefault("camera_prontos", {})[k] = mm["id"]
            CT.salvar(base, q)
            prontos[k] = mm["id"]
            feitos.append(mm["id"])
    return {"feitos": feitos, "pulados": pulados}
