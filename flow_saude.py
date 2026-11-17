"""
🩺 v84_409 — cuidar das contas do Google Flow (pra cair menos em "atividade incomum" e perder menos trabalho):

  • ⏱ ritmo humano: uma pausa aleatória entre um pedido e outro (padrão 8–20 s) e um teto de pedidos por hora por conta;
  • 🔄 rodízio: depois de N gerações seguidas na mesma conta, a próxima conta assume (antes do Google reclamar);
  • 🩺 saúde: o histórico de cada conta (gerações, "atividade incomum", login, sem crédito, recusas, erros), quando
    volta, e "tirar do rodízio" (fica fora até você pôr de volta — sobrevive a reiniciar o site);
  • 🧩 extensões: quantas extensões o perfil do navegador de cada conta tem (o aviso do Google cita extensões);
  • 🔁 erros passageiros (tempo esgotado, a página fechou…): o que pode ser tentado de novo;
  • 🙈 anonimizar a foto base (borra os rostos) quando o Flow recusa "pessoa famosa" por causa da IMAGEM.
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional

_TRAVA = threading.Lock()
_MEM: Dict[str, Any] = {"ultimo_fim": 0.0, "seguidas": {"conta": None, "n": 0}}
TIPOS = ("geracao", "incomum", "login", "limite", "famosos", "recusa", "erro", "passageiro", "rodizio")
DIA = 24 * 3600
RE_PASSAGEIRO = re.compile(r"tempo|timeout|time ?out|não (?:apareceu|terminou|carregou|chegou)|nenhum cart[ãa]o|net::|"
                           r"target (?:page|closed)|has been closed|navigation|connection|conex[ãa]o|reset", re.I)
PADRAO = {"pausa_min": 8.0, "pausa_max": 20.0, "rodizio_cada": 6, "max_hora": 25}


def _gf():
    from googleflow import googleflow_client as gf
    return gf


def arquivo() -> str:
    return os.path.join(str(_gf().pasta_dados()), "saude_contas.json")


def _ler() -> Dict[str, Any]:
    try:
        with open(arquivo(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar(d: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(arquivo()), exist_ok=True)
    tmp = arquivo() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, arquivo())


def config(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A config do ritmo (Configurações → Imagens por IA → Google Flow), com os padrões."""
    c = dict(PADRAO)
    src = (cfg or {}).get("flow_ritmo") if cfg else None
    if src is None:
        try:
            from site_config import load_site_config
            src = load_site_config().get("flow_ritmo")
        except Exception:  # noqa: BLE001
            src = None
    for k, v in (src or {}).items():
        if k in c:
            try:
                c[k] = type(PADRAO[k])(v)
            except (TypeError, ValueError):
                pass
    c["pausa_min"] = max(0.0, min(300.0, c["pausa_min"]))
    c["pausa_max"] = max(c["pausa_min"], min(600.0, c["pausa_max"]))
    c["rodizio_cada"] = max(0, min(100, int(c["rodizio_cada"])))
    c["max_hora"] = max(0, min(500, int(c["max_hora"])))
    return c


# ------------------------------------------------------------------ eventos
def registrar(conta: Optional[str], tipo: str, detalhe: str = "", agora: Optional[float] = None) -> None:
    if not conta or tipo not in TIPOS:
        return
    agora = agora or time.time()
    with _TRAVA:
        d = _ler()
        c = d.setdefault("contas", {}).setdefault(conta, {"eventos": [], "total": {}})
        c["eventos"] = [e for e in c["eventos"] if agora - e[0] < 7 * DIA][-400:] + [[round(agora, 1), tipo, str(detalhe)[:160]]]
        c["total"][tipo] = int(c["total"].get(tipo) or 0) + 1
        _gravar(d)
        if tipo == "geracao":
            s = _MEM["seguidas"]
            if s["conta"] == conta:
                s["n"] += 1
            else:
                _MEM["seguidas"] = {"conta": conta, "n": 1}


def contar(conta: str, tipo: str, janela_s: float, agora: Optional[float] = None) -> int:
    agora = agora or time.time()
    c = (_ler().get("contas") or {}).get(conta) or {}
    return sum(1 for e in c.get("eventos") or [] if e[1] == tipo and agora - e[0] < janela_s)


def seguidas(conta: Optional[str]) -> int:
    s = _MEM["seguidas"]
    return s["n"] if conta and s["conta"] == conta else 0


# ------------------------------------------------------------------ ⏱ ritmo e 🔄 rodízio
def pausa_antes(cfg: Optional[Dict[str, Any]] = None, dormir: Callable[[float], None] = time.sleep,
                parar: Callable[[], bool] = lambda: False, agora: Optional[float] = None) -> float:
    """Espera o que falta da pausa aleatória desde o fim do último pedido. → segundos esperados."""
    c = config(cfg)
    alvo = random.uniform(c["pausa_min"], c["pausa_max"])
    falta = alvo - ((agora or time.time()) - float(_MEM["ultimo_fim"] or 0))
    if falta <= 0 or not _MEM["ultimo_fim"]:
        return 0.0
    esperou = 0.0
    while esperou < falta and not parar():
        passo = min(1.0, falta - esperou)
        dormir(passo)
        esperou += passo
    return round(esperou, 1)


def marcar_fim() -> None:
    _MEM["ultimo_fim"] = time.time()


def precisa_trocar(conta: Optional[str], cfg: Optional[Dict[str, Any]] = None) -> str:
    """Motivo pra passar a vez pra outra conta ("" = segue nesta)."""
    if not conta:
        return ""
    c = config(cfg)
    if c["rodizio_cada"] and seguidas(conta) >= c["rodizio_cada"]:
        return f"{seguidas(conta)} gerações seguidas nela"
    if c["max_hora"] and contar(conta, "geracao", 3600) >= c["max_hora"]:
        return f"{c['max_hora']} gerações na última hora"
    return ""


def proxima_conta(atual: Optional[str], tipo: Optional[str] = None) -> Optional[str]:
    """A próxima conta que serve, DEPOIS da atual na ordem da lista (dá a volta). None = só a atual serve."""
    gf = _gf()
    contas = [c["nome"] for c in gf.listar_contas()]
    if atual in contas:
        i = contas.index(atual)
        contas = contas[i + 1:] + contas[:i]
    for n in contas:
        if n != atual and gf.conta_serve(n, tipo):
            return n
    return None


# ------------------------------------------------------------------ 🩺 fora do rodízio
FORA_MIN = 60 * 24 * 365 * 5


def fora_do_rodizio() -> List[str]:
    return list(_ler().get("fora") or [])


def tirar_do_rodizio(conta: str, fora: bool = True) -> None:
    gf = _gf()
    with _TRAVA:
        d = _ler()
        lista = [x for x in d.get("fora") or [] if x != conta]
        if fora:
            lista.append(conta)
        d["fora"] = lista
        _gravar(d)
    if fora:
        gf.pular_conta(conta, "fora do rodízio (você tirou em 🩺 Saúde das contas)", minutos=FORA_MIN)
    else:
        gf.despular_conta(conta)


def aplicar_fora() -> None:
    """Depois de reiniciar o site (a lista de puladas fica na memória): as que você tirou continuam de fora."""
    gf = _gf()
    for n in fora_do_rodizio():
        try:
            if not gf.conta_pulada(n):
                gf.pular_conta(n, "fora do rodízio (você tirou em 🩺 Saúde das contas)", minutos=FORA_MIN)
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ 🧩 extensões do perfil
def extensoes(conta: str) -> Dict[str, int]:
    """{navegador: nº de extensões} nos perfis desta conta (Chrome/Edge/Brave: Default/Extensions; Firefox: extensions)."""
    gf = _gf()
    raiz = str(gf.pasta_perfis())
    out: Dict[str, int] = {}
    if not os.path.isdir(raiz):
        return out
    slug = gf._slug(conta) if conta != gf.CONTA_PADRAO else ""
    for nome in os.listdir(raiz):
        cam = os.path.join(raiz, nome)
        if not os.path.isdir(cam):
            continue
        nav, _, s = nome.partition("--")
        if (slug and s != slug) or (not slug and s):
            continue
        n = 0
        for sub in ("Default/Extensions", "Extensions", "extensions"):
            p = os.path.join(cam, sub)
            if os.path.isdir(p):
                n += len([x for x in os.listdir(p) if not x.startswith(".") and x.lower() != "temp"])
        out[nav] = n
    return out


# ------------------------------------------------------------------ o painel
def resumo(agora: Optional[float] = None) -> List[Dict[str, Any]]:
    gf = _gf()
    agora = agora or time.time()
    d = _ler().get("contas") or {}
    fora = set(fora_do_rodizio())
    out = []
    for c in gf.listar_contas():
        h = d.get(c["nome"]) or {}
        ev = h.get("eventos") or []
        ult_inc = max((e[0] for e in ev if e[1] == "incomum"), default=None)
        dia = {t: sum(1 for e in ev if e[1] == t and agora - e[0] < DIA) for t in TIPOS}
        nota = 100 - 25 * dia["incomum"] - 15 * dia["login"] - 5 * dia["erro"] - 3 * dia["passageiro"]
        out.append({"nome": c["nome"], "email": c.get("email") or "", "logada": c.get("logada"), "fora": c["nome"] in fora,
                    "pulada": c.get("pulada") or "", "pulada_ate": c.get("pulada_ate") or "",
                    "esgotada_video": c.get("esgotada_video"), "esgotada_imagem": c.get("esgotada_imagem"),
                    "video_ate": c.get("video_ate"), "imagem_ate": c.get("imagem_ate"),
                    "dia": dia, "total": h.get("total") or {}, "ultimo_incomum": ult_inc,
                    "saude": max(0, min(100, nota)), "seguidas": seguidas(c["nome"]),
                    "na_hora": sum(1 for e in ev if e[1] == "geracao" and agora - e[0] < 3600),
                    "extensoes": extensoes(c["nome"]),
                    "ultimos": [{"quando": e[0], "tipo": e[1], "detalhe": e[2]} for e in ev[-6:]][::-1]})
    return out


# ------------------------------------------------------------------ 🙈 anonimizar a foto base
SISTEMA_ROSTOS = """List every human FACE in the image as a box (x, y, w, h as fractions 0..1 of the image, from the top-left),
generous enough to cover the whole head. Do not identify anyone."""
SCHEMA_ROSTOS = {"type": "object", "additionalProperties": False, "required": ["rostos"], "properties": {"rostos": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["x", "y", "w", "h"],
                               "properties": {k: {"type": "number"} for k in ("x", "y", "w", "h")}}}}}


def rostos_pela_ia(arquivo: str, chamar: Optional[Callable[..., Any]] = None) -> List[List[float]]:
    try:
        import ia_servico
        chamar = chamar or ia_servico.chamar
        b = ia_servico.imagem_bloco(arquivo, 768)
        if not b:
            return []
        r = chamar("flow_montar", SISTEMA_ROSTOS, [b, {"type": "text", "text": "Faces?"}], schema=SCHEMA_ROSTOS, max_tokens=500,
                   effort="low", timeout=60)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for q in (r or {}).get("rostos") or [] if isinstance(r, dict) else []:
        try:
            out.append([float(q["x"]), float(q["y"]), float(q["w"]), float(q["h"])])
        except (KeyError, TypeError, ValueError):
            pass
    return out


def anonimizar(arquivo: str, saida: str, marcas: Optional[List[Dict[str, Any]]] = None,
               achar: Callable[[str], List[List[float]]] = rostos_pela_ia) -> Optional[str]:
    """Borra os rostos (pelas marcas de pessoa — o centro da cabeça — ou pela IA). None se não achou rosto nenhum."""
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.open(arquivo).convert("RGB")
    W, H = im.size
    caixas = []
    r = 0.09 * min(W, H)
    for m in marcas or []:
        if m.get("tipo", "pessoa") != "objeto":
            cx, cy = float(m["x"]) * W, float(m["y"]) * H
            caixas.append((cx - r, cy - r * 1.2, cx + r, cy + r * 1.2))
    if not caixas:
        for x, y, w, h in achar(arquivo):
            caixas.append((x * W, y * H, (x + w) * W, (y + h) * H))
    if not caixas:
        return None
    borrada = im.filter(ImageFilter.GaussianBlur(radius=max(12, min(W, H) // 25)))
    mascara = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mascara)
    for c in caixas:
        d.ellipse([int(v) for v in c], fill=255)
    mascara = mascara.filter(ImageFilter.GaussianBlur(radius=6))
    im.paste(borrada, (0, 0), mascara)
    im.save(saida)
    return saida
