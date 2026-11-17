"""
✏️ v84_407 — RASCUNHO DA POSE: uma foto vira um rascunho a lápis da cena (bonecos sem rosto, só a pose e a composição,
como um esboço de quadrinho). Você numera cada figura (1, 2, 3…) e diz quem é quem ("personagem X"), e o rascunho vai
como POSE pra 🧩 Montar cena — aí é só pôr as fotos dos personagens novos no lugar de cada figura.
🤖 "Entender a cena" (v84_407b): a IA lê a foto INTEIRA — cada pessoa, cada objeto (o carro…), o cenário e a câmera — e
cada parte vira uma linha pra você trocar (por uma foto ou só escrevendo o que entra no lugar).

Dois jeitos de desenhar:
  🎨 pelo Flow — o Nano Banana redesenha a foto como rascunho de verdade (bonecos simples, linhas soltas);
  ⚡ rápido, no PC — um filtro de lápis (OpenCV) em cima da foto: na hora, sem crédito, mas é um "traçado" da foto.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

PROMPT_FLOW = (
    "Redraw this whole photo as a rough pencil storyboard sketch, like a comic pose reference: every person becomes a "
    "simple faceless mannequin figure (round head, no facial features, no hair or clothing detail) in EXACTLY the same "
    "pose, body angle, hand position and place; the scenery and objects (vehicles, furniture, ground, walls, background "
    "shapes) stay in the same places but as simple loose outlines, without texture or detail. Keep the same camera angle, "
    "framing and perspective. Loose confident graphite lines on plain white paper, no shading, no color, no text.")
MAX_LADO = 1280


def rascunho_local(entrada: str, saida: str) -> str:
    """Filtro de lápis: o "dodge" (cinza ÷ desfoque invertido) dá o traço, e o contraste limpa o papel."""
    import cv2
    import numpy as np
    img = cv2.imread(entrada)
    if img is None:
        raise ValueError("Não consegui abrir essa imagem.")
    h, w = img.shape[:2]
    esc = min(1.0, MAX_LADO / float(max(h, w)))
    if esc < 1.0:
        img = cv2.resize(img, (int(w * esc), int(h * esc)), interpolation=cv2.INTER_AREA)
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cinza = cv2.bilateralFilter(cinza, 9, 60, 60)  # tira a textura (pele, tecido) e deixa os contornos
    inv = 255 - cinza
    borr = cv2.GaussianBlur(inv, (0, 0), sigmaX=max(3.0, max(img.shape[:2]) / 160.0))
    dodge = cv2.divide(cinza, 255 - borr, scale=256)
    # contraste: o papel fica branco, as linhas ficam grafite
    traco = np.clip((dodge.astype(np.float32) - 200) * (255.0 / 55.0), 0, 255).astype(np.uint8)
    bordas = cv2.Canny(cv2.GaussianBlur(cinza, (5, 5), 0), 40, 110)
    bordas = cv2.dilate(bordas, np.ones((2, 2), np.uint8), 1)
    final = np.minimum(traco, 255 - (bordas // 2))  # reforça os contornos principais
    final = cv2.cvtColor(final, cv2.COLOR_GRAY2BGR)
    os.makedirs(os.path.dirname(saida) or ".", exist_ok=True)
    if not cv2.imwrite(saida, final):
        raise ValueError("Não consegui salvar o rascunho.")
    return saida


# ------------------------------------------------------------------ as figuras numeradas
def limpar_marcas(marcas: Any) -> List[Dict[str, Any]]:
    """[{x, y (0..1), nome, obs}] → numeradas na ordem (máx. 8)."""
    if isinstance(marcas, str):
        try:
            marcas = json.loads(marcas or "[]")
        except ValueError:
            marcas = []
    out = []
    for m in marcas or []:
        try:
            x, y = float(m.get("x")), float(m.get("y"))
        except (AttributeError, TypeError, ValueError):
            continue
        if 0 <= x <= 1 and 0 <= y <= 1:
            out.append({"n": len(out) + 1, "x": round(x, 4), "y": round(y, 4),
                        "tipo": "objeto" if m.get("tipo") == "objeto" else "pessoa",
                        "troca": m.get("troca") if m.get("troca") in ("rosto", "inteira") else "auto",
                        "nome": " ".join(str(m.get("nome") or "").split())[:80],
                        "obs": " ".join(str(m.get("obs") or "").split())[:300]})
        if len(out) >= 12:
            break
    return out


def lugar(m: Dict[str, Any]) -> str:
    h = "à esquerda" if m["x"] < 0.36 else "à direita" if m["x"] > 0.64 else "no meio"
    v = "no alto" if m["y"] < 0.3 else "embaixo" if m["y"] > 0.7 else ""
    return h + (", " + v if v else "")


def texto_marcas(marcas: List[Dict[str, Any]]) -> str:
    """O que vai na observação da pose: quem fica no lugar de cada figura e o que troca em cada objeto."""
    partes = []
    for m in marcas:
        if m.get("tipo") == "objeto":
            partes.append(f"elemento {m['n']} (objeto{': ' + m['obs'] if m['obs'] else ''}, {lugar(m)}) → "
                          + (f"trocar por: {m['nome']}" if m["nome"] else "mantém"))
        else:
            partes.append(f"figura {m['n']} (pessoa, {lugar(m)}) = {m['nome'] or 'personagem ' + str(m['n'])}"
                          + {"rosto": " — trocar SÓ o rosto/cabeça", "inteira": " — trocar a pessoa inteira"}.get(m.get("troca") or "", "")
                          + (f" — {m['obs']}" if m["obs"] else ""))
    return "; ".join(partes)


def limpar_cena(cena: Any) -> Dict[str, str]:
    if isinstance(cena, str):
        try:
            cena = json.loads(cena or "{}")
        except ValueError:
            cena = {}
    cena = cena if isinstance(cena, dict) else {}
    return {k: " ".join(str(cena.get(k) or "").split())[:400] for k in ("camera", "cenario", "cenario_novo")}


def texto_cena(cena: Dict[str, str]) -> str:
    t = []
    if cena.get("camera"):
        t.append("câmera: " + cena["camera"])
    if cena.get("cenario") or cena.get("cenario_novo"):
        t.append("cenário" + (f" original: {cena['cenario']}" if cena.get("cenario") else "")
                 + (f" → trocar por: {cena['cenario_novo']}" if cena.get("cenario_novo") else " → mantém"))
    return "; ".join(t)


def desenhar_marcas(entrada: str, saida: str, marcas: List[Dict[str, Any]]) -> str:
    """Uma CÓPIA com os números (e nomes) em cima de cada figura — só pra IA ler; o Flow recebe o rascunho limpo."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(entrada).convert("RGB")
    d = ImageDraw.Draw(im)
    r = max(14, int(min(im.size) * 0.035))
    try:
        fonte = ImageFont.truetype("DejaVuSans-Bold.ttf", int(r * 1.1))
    except OSError:
        fonte = ImageFont.load_default()
    for m in marcas:
        cx, cy = m["x"] * im.width, m["y"] * im.height
        cor = (37, 99, 235) if m.get("tipo") == "objeto" else (220, 38, 38)  # 🔵 objeto · 🔴 pessoa
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=cor, outline=(255, 255, 255), width=3)
        t = str(m["n"])
        bb = d.textbbox((0, 0), t, font=fonte)
        d.text((cx - (bb[2] - bb[0]) / 2, cy - (bb[3] - bb[1]) / 2 - bb[1]), t, fill="white", font=fonte)
        if m.get("nome"):
            d.text((cx + r + 4, cy - r), m["nome"], fill=cor, font=fonte, stroke_width=3, stroke_fill="white")
    im.save(saida)
    return saida


# ------------------------------------------------------------------ 🤖 entender a cena
SISTEMA_CENA = """You look at a photo (or a sketch) and break the scene into parts the user can REPLACE later: every person,
every important object (vehicles, furniture, props, animals) and the scenery/background, plus the camera angle.
For each person and object give a point ON it as x,y fractions of the image (0..1, x from the left, y from the top) — for
people, the center of the head — and a short description in Brazilian Portuguese of what it is and what it is doing
(pose, clothes, color; e.g. "homem de terno cinza, mão no bolso, olhando pra câmera" / "carro conversível laranja,
estacionado atrás"). Order people from left to right, then objects. Never identify real people or celebrities — describe
them only. "camera": the angle/lens in Portuguese (e.g. "de cima pra baixo, grande angular, corpo inteiro").
"cenario": the place/background in Portuguese. "estilo": the look of the image — one of foto, anime, manga, cartoon,
quadrinho, pixel, outro."""
SCHEMA_CENA = {"type": "object", "additionalProperties": False, "required": ["camera", "cenario", "estilo", "elementos"], "properties": {
    "camera": {"type": "string"}, "cenario": {"type": "string"},
    "estilo": {"type": "string", "enum": ["foto", "anime", "manga", "cartoon", "quadrinho", "pixel", "outro"]},
    "elementos": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                            "required": ["tipo", "x", "y", "descricao"],
                                            "properties": {"tipo": {"type": "string", "enum": ["pessoa", "objeto"]},
                                                           "x": {"type": "number"}, "y": {"type": "number"},
                                                           "descricao": {"type": "string"}}}}}}


def entender_cena(arquivo: str, chamar: Optional[Callable[..., Any]] = None,
                  bloco_imagem: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    """→ {marcas: [{n, x, y, tipo, nome:"", obs: descrição}], cena: {camera, cenario, cenario_novo:""}} — vazio sem a IA."""
    if chamar is None or bloco_imagem is None:
        import ia_servico
        chamar = chamar or ia_servico.chamar
        bloco_imagem = bloco_imagem or (lambda f: ia_servico.imagem_bloco(f, 1024))
    b = bloco_imagem(arquivo)
    if not b:
        return {"marcas": [], "cena": limpar_cena({}), "estilo": ""}
    try:
        r = chamar("flow_montar", SISTEMA_CENA, [b, {"type": "text", "text": "Break this scene into replaceable parts."}],
                   schema=SCHEMA_CENA, max_tokens=1500, effort="low", timeout=120)
    except Exception:  # noqa: BLE001
        r = None
    if not isinstance(r, dict):
        return {"marcas": [], "cena": limpar_cena({}), "estilo": ""}
    els = [e for e in r.get("elementos") or [] if isinstance(e, dict)]
    els.sort(key=lambda e: (0 if e.get("tipo") == "pessoa" else 1))
    return {"marcas": limpar_marcas([{"x": e.get("x"), "y": e.get("y"), "tipo": e.get("tipo"), "obs": e.get("descricao") or ""}
                                     for e in els]),
            "cena": limpar_cena({"camera": r.get("camera"), "cenario": r.get("cenario")}),
            "estilo": r.get("estilo") if r.get("estilo") in ("foto", "anime", "manga", "cartoon", "quadrinho", "pixel") else ""}


def achar_figuras(arquivo: str, chamar: Optional[Callable[..., Any]] = None,
                  bloco_imagem: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None) -> List[Dict[str, Any]]:
    """(compatível) só as marcas."""
    return entender_cena(arquivo, chamar, bloco_imagem)["marcas"]
