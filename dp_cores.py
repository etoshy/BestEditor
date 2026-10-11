"""
Direcionamento de cores (colorSystem do DarkPlanner).

  * paleta = primária, secundária, acento (padrão do JSON: #FFD60A / #FF9A1F / #4DC3FF)
  * tons_da_paleta(primária) -> claro / vivo / médio / escuro (tom sobre tom)
  * cor NEUTRA (saturação < 28) nunca é trocada pela paleta
  * modo "projeto": a paleta veste tudo que é adaptativo (cenas, destaques,
    textos, legendas, transições de luz); "auto": cada estilo com as cores dele
"""
from __future__ import annotations

import colorsys
import re
from typing import Any, Dict, Optional, Tuple

import dp_visual


def _hex(c: str) -> Tuple[int, int, int]:
    c = (c or "").strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", c):
        c = "FFD60A"
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _para_hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(round(x)))) for x in (r, g, b)))


def saturacao(c: str) -> float:
    r, g, b = (x / 255 for x in _hex(c))
    _h, _l, s = colorsys.rgb_to_hls(r, g, b)
    return s * 100


def neutra(c: str) -> bool:
    return saturacao(c) < 28


def tons_da_paleta(primaria: str) -> Dict[str, str]:
    r, g, b = (x / 255 for x in _hex(primaria))
    h, l, s = colorsys.rgb_to_hls(r, g, b)

    def tom(l2, s2):
        rr, gg, bb = colorsys.hls_to_rgb(h, max(0, min(1, l2)), max(0, min(1, s2)))
        return _para_hex(rr * 255, gg * 255, bb * 255)
    return {"claro": tom(0.82, s * 0.85), "vivo": tom(max(0.45, min(0.6, l)), min(1, s * 1.1 + 0.05)),
            "medio": tom(0.38, s * 0.85), "escuro": tom(0.14, s * 0.6), "base": _para_hex(r * 255, g * 255, b * 255)}


def derivar(primaria: str) -> Dict[str, str]:
    """Secundária/acento a partir da primária (claro e médio da mesma cor)."""
    t = tons_da_paleta(primaria)
    return {"primaria": t["base"], "secundaria": t["claro"], "acento": t["medio"]}


PALETAS = [
    {"id": "dp_ouro", "nome": "Ouro DarkPlanner (padrão)", "primaria": "#FFD60A", "secundaria": "#FF9A1F", "acento": "#4DC3FF"},
    {"id": "ambar_doc", "nome": "Âmbar documental", "primaria": "#E8B04A", "secundaria": "#F5E1B8", "acento": "#8A5A24"},
    {"id": "sepia", "nome": "Sépia histórica", "primaria": "#C8A26B", "secundaria": "#EFE3CB", "acento": "#6B4A2B"},
    {"id": "noir_verm", "nome": "Noir vermelho", "primaria": "#E0313B", "secundaria": "#F2F2F2", "acento": "#7A1016"},
    {"id": "investigacao", "nome": "Azul investigação", "primaria": "#3E8EFF", "secundaria": "#BFD9FF", "acento": "#0E2F66"},
    {"id": "tecnico", "nome": "Ciano técnico", "primaria": "#2FD3E0", "secundaria": "#C9F6FA", "acento": "#0B4F5C"},
    {"id": "arquivo_verde", "nome": "Verde arquivo", "primaria": "#5FBF6A", "secundaria": "#D8F0D2", "acento": "#1F4D25"},
    {"id": "teal_orange", "nome": "Teal & Orange", "primaria": "#FF8A3D", "secundaria": "#FFD3AE", "acento": "#1FA3A8"},
    {"id": "neon_roxo", "nome": "Roxo neon", "primaria": "#B061FF", "secundaria": "#E7CCFF", "acento": "#FF4FD8"},
    {"id": "pop_rosa", "nome": "Rosa pop", "primaria": "#FF4F9A", "secundaria": "#FFD1E5", "acento": "#FFD60A"},
    {"id": "impacto", "nome": "Laranja impacto", "primaria": "#FF5A1F", "secundaria": "#FFC2A6", "acento": "#FFE14D"},
    {"id": "mono", "nome": "Monocromático", "primaria": "#FFFFFF", "secundaria": "#BDBDBD", "acento": "#6E6E6E"},
]

ESCOPOS = ("cenas", "textos", "legendas", "transicoes")


def padrao() -> Dict[str, Any]:
    p = dict(dp_visual.dp()["colorSystem"]["paletaDefault"])
    return {"ativa": True, "modo": "projeto", "id": "dp_ouro", **p, "escopo": {k: True for k in ESCOPOS}}


def normalizar(p: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    base = padrao()
    if not isinstance(p, dict):
        return base
    out = dict(base)
    for k in ("primaria", "secundaria", "acento"):
        v = str(p.get(k) or "")
        if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            out[k] = v.upper()
    if p.get("modo") in ("projeto", "auto"):
        out["modo"] = p["modo"]
    out["id"] = str(p.get("id") or out["id"])[:32]
    out["ativa"] = p.get("ativa", True) is not False
    esc = p.get("escopo") if isinstance(p.get("escopo"), dict) else {}
    out["escopo"] = {k: esc.get(k, True) is not False for k in ESCOPOS}
    return out


def vale_para(p: Optional[Dict[str, Any]], escopo: str) -> bool:
    p = normalizar(p) if p is not None else None
    return bool(p and p["ativa"] and p["modo"] == "projeto" and p["escopo"].get(escopo, True))


def para_ffmpeg(c: str) -> str:
    return "0x" + c.lstrip("#").upper()


def deltas_yuv(c: str, k: float = 1.0) -> Tuple[float, float, float]:
    """Cor -> deslocamento em Y/U/V (pra somar em cima da imagem nos leaks)."""
    r, g, b = _hex(c)
    y = 0.299 * r + 0.587 * g + 0.114 * b
    u = -0.169 * r - 0.331 * g + 0.5 * b
    v = 0.5 * r - 0.419 * g - 0.081 * b
    return (y * 0.35 * k, u * 0.6 * k, v * 0.6 * k)


def rgb(c: str) -> Tuple[int, int, int]:
    return _hex(c)


_PALETAS_DE_FABRICA = len(PALETAS)


def _aplicar_extras() -> None:
    """Paletas criadas em assets/darkplanner/extras (seção "paletas")."""
    del PALETAS[_PALETAS_DE_FABRICA:]
    try:
        import dp_extras
        ids = {p["id"] for p in PALETAS}
        for p in dp_extras.carregar().get("paletas") or []:
            if p["id"] in ids:
                dp_extras.avisar(f"{p['_arquivo']}: paleta {p['id']} já existe — escolha outro id.")
                continue
            PALETAS.append({"id": p["id"], "nome": str(p.get("nome") or p["id"])[:60], "primaria": p["primaria"].upper(),
                            "secundaria": p["secundaria"].upper(), "acento": p["acento"].upper()})
            ids.add(p["id"])
    except Exception:  # noqa: BLE001
        pass


_aplicar_extras()
