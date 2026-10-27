"""
anime_cine.py — 🎬 Anime quadro a quadro (cenas de ação, v84_243)
=================================================================

Cenas curtas (de uns 3 a 30 s) com animação bem trabalhada, no espírito das lutas de anime de TV de estúdio grande —
SEM vídeo de IA: o 🚀 Flow só DESENHA (imagens) e a animação é montada aqui, quadro a quadro.

  1. 📥 Entrada: o roteiro da cena e/ou páginas de mangá; os personagens vêm do 🧬 Criador, da 🎞 Animação 2D, do 🎭
     React (o design aprovado / a ⭐ mestre) ou de uma imagem sua; o cenário vem de um 🗺 lugar do Criador (ou texto).
  2. 🤖 Planejar: a IA (diretor de animação) divide a cena em PLANOS (cortes de 0,5–8 s) — tipo de plano, câmera,
     efeitos, transição, quem está, falas, sons — e, em cada plano, os DESENHOS do movimento (1 a 8, com quanto tempo
     cada um fica na tela e quais são quadros de impacto).
  3. 🎨 Storyboard no Flow: primeiro o QUADRO-CHAVE de cada plano (com os designs dos personagens e o cenário de
     referência) → você aprova/refaz; depois "🎞 os desenhos do movimento": cada desenho é feito A PARTIR DO ANTERIOR
     (a referência é o desenho de antes — o personagem, a cor e o traço não mudam), um depois do outro, sozinho.
  4. 🎞 Animação (aqui no PC): cada desenho fica X quadros na tela (em 2 / em 3, como anime de TV), câmera (zoom,
     pan, subida, chicote), tremor, linhas de velocidade, quadro de IMPACTO (negativo em alto contraste + flash +
     tremor), flash, faíscas/brasas, vinheta; transições (corte seco, flash branco, preto, dissolver); legendas.
  5. 🎙 Som: as falas no TTS do site (a voz de cada personagem) + efeitos da biblioteca (impacto, chicote de ar, fogo,
     passos…) no instante certo.
  6. 🎬 mp4 (+ mandar pro editor).

Tudo em anime_cine/<id>/ (projeto.json, refs/, quadros/, vozes/, saida/).
"""
from __future__ import annotations

import io
import json
import math
import os
import random
import re
import secrets
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

_BASE = os.path.dirname(os.path.abspath(__file__))
_TRAVA = threading.RLock()
RE_ID = re.compile(r"^ac[0-9a-f]{10}$")
ESPERA = ("fila", "gerando")
FPS = 24
MAX_PLANOS = 24
MAX_QUADROS = 8
MAX_PERSONAGENS = 8


class CineErro(Exception):
    pass


TIPOS_PLANO = {
    "estabelecimento": ("🏞 Estabelecimento (o lugar)", "wide establishing shot of the location"),
    "geral": ("🧍 Plano geral", "wide shot, full bodies in the environment"),
    "medio": ("🙂 Plano médio", "medium shot, from the waist up"),
    "close": ("👁 Close", "close-up on the face"),
    "close_extremo": ("👀 Close extremo", "extreme close-up (eyes / mouth / hand / blade)"),
    "detalhe": ("✋ Detalhe", "insert shot of a detail (hand, weapon, foot hitting the ground)"),
    "contra_plongee": ("⬆ Contra-plongée (de baixo)", "low-angle shot looking up, powerful"),
    "plongee": ("⬇ Plongée (de cima)", "high-angle shot looking down"),
    "sobre_ombro": ("🫱 Sobre o ombro", "over-the-shoulder shot"),
    "pov": ("🎥 Ponto de vista", "first-person point of view shot"),
    "aereo": ("🦅 Aéreo", "aerial bird's-eye view"),
}
CAMERAS = {"fixa": "🔒 fixa", "zoom_in": "🔍 aproxima", "zoom_out": "🔭 afasta", "pan_esq": "⬅ pan pra esquerda",
           "pan_dir": "➡ pan pra direita", "sobe": "⬆ sobe", "desce": "⬇ desce", "chicote": "💨 chicote (whip pan)",
           "orbita": "🌀 gira devagar"}
EFEITOS = {"linhas": "💨 linhas de velocidade", "tremor": "📳 tremor", "flash": "⚡ flash no começo", "brasas": "🔥 faíscas / brasas",
           "vinheta": "🌑 vinheta", "camera_lenta": "🐢 câmera lenta (desenhos seguram mais)", "chuva": "🌧 chuva",
           "foco": "🎯 linhas de foco (fundo some, centro destaca)"}
TRANSICOES = {"corte": "✂ corte seco", "flash": "⚪ flash branco", "preto": "⚫ pelo preto", "dissolver": "🌫 dissolver"}
SFX = {"impacto": ("💥 impacto / soco", ["impacto"]), "chicote": ("💨 chicote de ar / golpe rápido", ["vento", "passagem"]),
       "espada": ("🗡 lâmina / corte", ["passagem", "vento"]), "fogo": ("🔥 fogo", ["fogo"]),
       "passos": ("👣 passos / foley", ["foley"]), "tensao": ("🎻 tensão / cinema", ["cinema"]),
       "explosao": ("💣 explosão", ["impacto", "cinema"]), "magia": ("✨ poder / brilho", ["digital", "pop"]),
       "respiro": ("😮‍💨 respiração", ["respiro"])}
PROPORCOES = {"16:9": (1920, 1080), "9:16": (1080, 1920)}


# ------------------------------------------------------------------ guardar
def pasta_raiz(base: str = _BASE) -> str:
    return os.environ.get("ANIME_CINE_DIR") or os.path.join(base, "anime_cine")


def pasta(pid: str, base: str = _BASE) -> str:
    if not RE_ID.match(pid or ""):
        raise CineErro("Projeto inválido.")
    return os.path.join(pasta_raiz(base), pid)


def _completar(p: Dict[str, Any]) -> Dict[str, Any]:
    e = p.setdefault("entrada", {})
    for k, v in (("roteiro", ""), ("duracao", 15), ("estilo", "anime"), ("estilo_livre", ""), ("proporcao", "16:9"),
                 ("cenario", ""), ("lugar", ""), ("lugar_img", ""), ("legendas", True), ("motor_perfil", "xtts"),
                 ("volume_sfx", 0.7)):
        e.setdefault(k, v)
    e.setdefault("paginas", [])
    p.setdefault("personagens", [])
    p.setdefault("planos", [])
    p.setdefault("saida", {})
    p.setdefault("log", [])
    return p


def criar(titulo: str = "", base: str = _BASE, **entrada: Any) -> Dict[str, Any]:
    pid = "ac" + secrets.token_hex(5)
    for sub in ("refs", "quadros", "vozes", "saida"):
        os.makedirs(os.path.join(pasta(pid, base), sub), exist_ok=True)
    p = _completar({"id": pid, "titulo": _txt(titulo, 120) or "Cena sem título", "criado": time.time()})
    editar_entrada(p, entrada)
    salvar(p, base)
    return p


def carregar(pid: str, base: str = _BASE) -> Dict[str, Any]:
    try:
        with open(os.path.join(pasta(pid, base), "projeto.json"), encoding="utf-8") as f:
            return _completar(json.load(f))
    except FileNotFoundError:
        raise CineErro("Projeto não encontrado.")


def salvar(p: Dict[str, Any], base: str = _BASE) -> None:
    d = pasta(p["id"], base)
    os.makedirs(d, exist_ok=True)
    p["atualizado"] = time.time()
    tmp = os.path.join(d, f"projeto.json.{secrets.token_hex(3)}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(d, "projeto.json"))


def listar(base: str = _BASE) -> List[Dict[str, Any]]:
    raiz = pasta_raiz(base)
    out = []
    for n in os.listdir(raiz) if os.path.isdir(raiz) else []:
        if not RE_ID.match(n):
            continue
        try:
            p = carregar(n, base)
        except CineErro:
            continue
        out.append({"id": n, "titulo": p["titulo"], "planos": len(p["planos"]), "dur": round(duracao_total(p), 1),
                    "video": bool((p.get("saida") or {}).get("mp4")), "atualizado": p.get("atualizado") or 0})
    return sorted(out, key=lambda x: -x["atualizado"])


def excluir(pid: str, base: str = _BASE) -> None:
    shutil.rmtree(pasta(pid, base), ignore_errors=True)


def log(p: Dict[str, Any], msg: str) -> None:
    p["log"] = (p.get("log") or [])[-80:] + [{"t": time.time(), "msg": msg}]


def _txt(v: Any, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def _id(prefixo: str) -> str:
    return prefixo + secrets.token_hex(3)


# ------------------------------------------------------------------ 📥 entrada
def editar_entrada(p: Dict[str, Any], d: Dict[str, Any]) -> None:
    import criador_personagens as C
    e = p["entrada"]
    if d.get("roteiro") is not None:
        e["roteiro"] = str(d["roteiro"]).strip()[:8000]
    if d.get("titulo"):
        p["titulo"] = _txt(d["titulo"], 120)
    if d.get("duracao") is not None:
        try:
            e["duracao"] = max(2, min(60, int(float(d["duracao"]))))
        except (TypeError, ValueError):
            pass
    if d.get("estilo") is not None:
        e["estilo"] = d["estilo"] if d["estilo"] in C.ESTILOS or d["estilo"] == "outro" else "anime"
    for k, n in (("estilo_livre", 300), ("cenario", 1500)):
        if d.get(k) is not None:
            e[k] = str(d[k]).strip()[:n]
    if d.get("proporcao") in PROPORCOES:
        e["proporcao"] = d["proporcao"]
    if "legendas" in d:
        e["legendas"] = bool(d["legendas"])
    if d.get("lugar") is not None:
        e["lugar"] = str(d["lugar"]) if re.match(r"^(lg[0-9a-f]{10})?$", str(d["lugar"])) else ""
    if d.get("volume_sfx") is not None:
        try:
            e["volume_sfx"] = max(0.0, min(1.5, float(d["volume_sfx"])))
        except (TypeError, ValueError):
            pass


def estilo_en(p: Dict[str, Any]) -> str:
    import criador_personagens as C
    return C.estilo_en({"entrada": p["entrada"]})


def _guardar_img(p: Dict[str, Any], img, sub: str, prefixo: str, base: str, lado: int = 1800) -> str:
    d = os.path.join(pasta(p["id"], base), sub)
    os.makedirs(d, exist_ok=True)
    im = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
    im.thumbnail((lado, lado))
    arq = f"{prefixo}_{secrets.token_hex(3)}.png"
    im.save(os.path.join(d, arq))
    return arq


def guardar_pagina(p: Dict[str, Any], img, base: str = _BASE) -> str:
    if len(p["entrada"]["paginas"]) >= 12:
        raise CineErro("No máximo 12 páginas de mangá por cena.")
    arq = _guardar_img(p, img, "refs", "pagina", base, 2000)
    p["entrada"]["paginas"].append(arq)
    return arq


def fontes_personagens(base: str = _BASE) -> List[Dict[str, Any]]:
    """Os personagens que dá pra puxar: 🧬 Criador (design aprovado), 🎞 Animação 2D e 🎭 React (a ⭐ mestre / o design)."""
    out: List[Dict[str, Any]] = []
    try:
        import criador_personagens as C
        for x in C.listar(base):
            if x.get("miniatura"):
                out.append({"fonte": f"criador:{x['id']}", "nome": x["nome"], "grupo": "🧬 Criador"})
    except Exception:  # noqa: BLE001
        pass
    try:
        import anime2d as A
        for x in A.listar(base):
            q = A.carregar(x["id"], base)
            for c in q["personagens"]:
                if _img_de_fonte(f"anime2d:{q['id']}:{c['id']}", base)[0]:
                    out.append({"fonte": f"anime2d:{q['id']}:{c['id']}", "nome": c["nome"], "grupo": f"🎞 {q['titulo'][:40]}"})
    except Exception:  # noqa: BLE001
        pass
    try:
        import react_personagens as R
        for x in R.listar(base):
            q = R.carregar(x["id"], base)
            for c in q["personagens"]:
                if _img_de_fonte(f"react:{q['id']}:{c['id']}", base)[0]:
                    out.append({"fonte": f"react:{q['id']}:{c['id']}", "nome": c["nome"], "grupo": f"🎭 {q['titulo'][:40]}"})
    except Exception:  # noqa: BLE001
        pass
    return out


def _mestre_pod(c: Dict[str, Any], base: str) -> Optional[str]:
    try:
        import personagens_pod as pp
        pod = c.get("pod") or {}
        if not pod.get("pid"):
            return None
        proj = pp.carregar(pod["pid"], base)
        m = (proj.get("mestre") or {}).get("arquivo")
        return pp.arquivo_atual(proj, m, base) if m else None
    except Exception:  # noqa: BLE001
        return None


def _img_de_fonte(fonte: str, base: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """(a imagem, a ficha) do personagem de outra parte do site."""
    partes = fonte.split(":")
    try:
        if partes[0] == "criador":
            import criador_personagens as C
            q = C.carregar(partes[1], base)
            ap = C.aprovada(q)
            cam = os.path.join(C.pasta(q["id"], base), "design", ap["arquivo"]) if ap else None
            return cam, {"nome": q["nome"], "aparencia_en": (q["ficha"] or {}).get("aparencia_en") or "",
                         "personalidade": (q["ficha"] or {}).get("personalidade") or ""}
        if partes[0] == "anime2d":
            import anime2d as A
            q = A.carregar(partes[1], base)
            c = next(x for x in q["personagens"] if x["id"] == partes[2])
            cam = A.design_aprovado(q, c, base) or _mestre_pod(c, base) or (A.refs_de(q, c, base) or [None])[0]
            return cam, {"nome": c["nome"], "aparencia_en": c.get("aparencia_en") or "", "voz": c.get("voz") or "",
                         "personalidade": c.get("personalidade") or ""}
        if partes[0] == "react":
            import react_personagens as R
            q = R.carregar(partes[1], base)
            c = R.personagem(q, partes[2])
            cam = _mestre_pod(c, base)
            if not cam and c.get("refs"):
                cam = os.path.join(R.pasta(q["id"], base), "refs", c["refs"][0])
            return cam, {"nome": c["nome"], "aparencia_en": c.get("aparencia_en") or "", "personalidade": c.get("personalidade") or ""}
    except Exception:  # noqa: BLE001
        return None, {}
    return None, {}


def importar_personagem(p: Dict[str, Any], fonte: str, base: str = _BASE) -> Dict[str, Any]:
    from PIL import Image
    if len(p["personagens"]) >= MAX_PERSONAGENS:
        raise CineErro(f"No máximo {MAX_PERSONAGENS} personagens por cena.")
    cam, ficha = _img_de_fonte(fonte, base)
    if not cam or not os.path.isfile(cam):
        raise CineErro("Esse personagem ainda não tem imagem (aprove o design / gere a ⭐ mestre lá).")
    arq = _guardar_img(p, Image.open(cam), "refs", "pers", base)
    c = {"id": _id("c"), "nome": ficha.get("nome") or "?", "fonte": fonte, "imagem": arq,
         "aparencia_en": _txt(ficha.get("aparencia_en"), 1500), "personalidade": _txt(ficha.get("personalidade"), 600),
         "voz": ficha.get("voz") or ""}
    p["personagens"].append(c)
    return c


def personagem_seu(p: Dict[str, Any], img, nome: str, aparencia: str = "", base: str = _BASE) -> Dict[str, Any]:
    if len(p["personagens"]) >= MAX_PERSONAGENS:
        raise CineErro(f"No máximo {MAX_PERSONAGENS} personagens por cena.")
    c = {"id": _id("c"), "nome": _txt(nome, 60) or "Personagem", "fonte": "sua", "imagem": _guardar_img(p, img, "refs", "pers", base),
         "aparencia_en": _txt(aparencia, 1500), "personalidade": "", "voz": ""}
    p["personagens"].append(c)
    return c


def editar_personagem(p: Dict[str, Any], cid: str, d: Dict[str, Any], base: str = _BASE) -> None:
    c = next((x for x in p["personagens"] if x["id"] == cid), None)
    if not c:
        raise CineErro("Personagem não encontrado.")
    if d.get("apagar"):
        p["personagens"].remove(c)
        for pl in p["planos"]:
            pl["quem"] = [x for x in pl.get("quem") or [] if x != cid]
        return
    for k, n in (("nome", 60), ("aparencia_en", 1500), ("personalidade", 600), ("voz", 120)):
        if k in d:
            c[k] = _txt(d[k], n)


def lugar_info(p: Dict[str, Any], base: str = _BASE) -> Tuple[str, Optional[str]]:
    """(a descrição do cenário, a imagem dele) — do 🗺 lugar do Criador, do texto e da imagem sua."""
    e = p["entrada"]
    desc, img = e.get("cenario") or "", None
    if e.get("lugar"):
        try:
            import criador_lugares as CL
            lg = CL.carregar(e["lugar"], base)
            desc = ((lg.get("ficha") or {}).get("descricao_en") or lg["entrada"].get("descricao") or "") + (f". {desc}" if desc else "")
            foto = next((f for f in lg["fotos"] if f.get("arquivo") and f.get("aprovada")), None) or \
                next((f for f in lg["fotos"] if f.get("arquivo")), None)
            if foto:
                img = os.path.join(CL.pasta(lg["id"], base), "fotos", foto["arquivo"])
        except Exception:  # noqa: BLE001
            pass
    if e.get("lugar_img"):
        cam = os.path.join(pasta(p["id"], base), "refs", e["lugar_img"])
        if os.path.isfile(cam):
            img = cam
    return desc, img


# ------------------------------------------------------------------ 🤖 planejar (os planos e os desenhos)
SCHEMA_PLANO = {
    "type": "object", "additionalProperties": False, "required": ["titulo", "planos"],
    "properties": {
        "titulo": {"type": "string"},
        "planos": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["dur", "tipo", "camera", "efeitos", "transicao", "acao_pt", "quem", "falas", "sfx", "desenhos"],
            "properties": {
                "dur": {"type": "number"}, "tipo": {"type": "string", "enum": list(TIPOS_PLANO)},
                "camera": {"type": "string", "enum": list(CAMERAS)},
                "efeitos": {"type": "array", "items": {"type": "string", "enum": list(EFEITOS)}},
                "transicao": {"type": "string", "enum": list(TRANSICOES)},
                "acao_pt": {"type": "string"}, "quem": {"type": "array", "items": {"type": "string"}},
                "falas": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                     "required": ["quem", "texto", "t"],
                                                     "properties": {"quem": {"type": "string"}, "texto": {"type": "string"},
                                                                    "t": {"type": "number"}}}},
                "sfx": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["som", "t"],
                                                   "properties": {"som": {"type": "string", "enum": list(SFX)},
                                                                  "t": {"type": "number"}}}},
                "desenhos": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                        "required": ["prompt_en", "segura", "impacto"],
                                                        "properties": {"prompt_en": {"type": "string"},
                                                                       "segura": {"type": "number"},
                                                                       "impacto": {"type": "boolean"}}}},
            }}},
    },
}
SYS_PLANO = (
    "Você é DIRETOR DE ANIMAÇÃO de anime de ação de TV de estúdio grande (lutas com sakuga, cortes rápidos, composição "
    "forte, como as melhores séries de ação). A cena NÃO é vídeo de IA: cada plano é feito de DESENHOS (imagens) que o "
    "site anima — cada desenho fica alguns quadros na tela (em 2/em 3), com câmera (zoom, pan, chicote), tremor, linhas "
    "de velocidade, quadro de impacto, flash e partículas. Divida a cena em PLANOS:\n"
    "- a soma das durações ≈ a duração pedida; planos de 0,5–8 s (ação: 0,5–2 s, cortes secos; respiro/fala: 2–5 s); "
    "comece situando (estabelecimento ou geral), varie tipo de plano e ângulo (close no olho antes do golpe, contra-plongée "
    "no poder, detalhe da mão/arma, plano geral do impacto), corte no movimento;\n"
    "- 'desenhos': 1 a 8 por plano (plano parado/fala: 1–2 com câmera fazendo o trabalho; golpe/sakuga: 4–8). Cada um "
    "com 'prompt_en' em INGLÊS descrevendo O DESENHO (composição, pose exata, expressão, o momento do movimento, luz, "
    "efeitos desenhados como rastros de movimento, faíscas, água/fogo estilizados) — o 1º é o quadro-chave (completo: quem, "
    "onde, câmera); os seguintes dizem SÓ o que muda (\"the fist now hits the jaw, head snapping back, shockwave ring\"); "
    "'segura' = peso do tempo na tela (1 = rápido, 3 = segura); 'impacto' = true no quadro do golpe (vira quadro de "
    "impacto: negativo em alto contraste + flash + tremor);\n"
    "- 'quem' = os NOMES dos personagens no plano; 'falas' curtas (gritos de golpe, provocação), com 't' = segundos desde o "
    "início do plano; 'sfx' com 't'; 'efeitos' e 'camera' que vendem o movimento; 'transicao' pro próximo plano;\n"
    "- se vierem páginas de MANGÁ: siga os quadros na ordem (cada quadro importante vira 1+ plano, o enquadramento do "
    "quadro vira o do plano, as falas dos balões viram falas), completando o movimento entre um quadro e outro;\n"
    "- sem texto/legenda/balão desenhado nas imagens. Respeite os personagens e o cenário dados."
)


def _pedido_plano(p: Dict[str, Any], base: str) -> str:
    e = p["entrada"]
    L = [f"TÍTULO: {p['titulo']}", f"DURAÇÃO PEDIDA: {e['duracao']} s", f"PROPORÇÃO: {e['proporcao']}",
         f"ESTILO: {estilo_en(p)}"]
    if e.get("roteiro"):
        L.append(f"ROTEIRO / O QUE ACONTECE:\n{e['roteiro']}")
    if p["personagens"]:
        L.append("PERSONAGENS:\n" + "\n".join(f"- {c['nome']}: {c.get('aparencia_en') or '(veja a imagem)'}"
                                              + (f" | {c['personalidade']}" if c.get("personalidade") else "") for c in p["personagens"]))
    desc, _img = lugar_info(p, base)
    if desc:
        L.append(f"CENÁRIO: {desc}")
    if e["paginas"]:
        L.append(f"PÁGINAS DE MANGÁ: {len(e['paginas'])} (em ordem, nas imagens)")
    return "\n\n".join(L)


def planejar(pid: str, base: str = _BASE) -> str:
    """🤖 Os planos e os desenhos (sem IA: um plano por parágrafo do roteiro)."""
    import criador_personagens as C
    p = carregar(pid, base)
    if not (p["entrada"].get("roteiro") or p["entrada"]["paginas"]):
        raise CineErro("Escreva o roteiro da cena ou mande páginas de mangá.")
    r = None
    if C.ia_ligada():
        ia = C._ia()
        conteudo: List[Dict[str, Any]] = [{"type": "text", "text": _pedido_plano(p, base)}]
        for k, a in enumerate(p["entrada"]["paginas"]):
            b = ia.imagem_bloco(os.path.join(pasta(pid, base), "refs", a), 900)
            if b:
                conteudo += [{"type": "text", "text": f"PÁGINA {k + 1}:"}, b]
        for c in p["personagens"]:
            b = ia.imagem_bloco(os.path.join(pasta(pid, base), "refs", c["imagem"]), 320)
            if b:
                conteudo += [{"type": "text", "text": f"PERSONAGEM {c['nome']}:"}, b]
        r = ia.chamar("anime_cine", SYS_PLANO, conteudo, schema=SCHEMA_PLANO, max_tokens=9000, effort="high", timeout=240)
        if not isinstance(r, dict):
            raise CineErro("A IA não respondeu — tente de novo (ou monte os planos à mão).")
    else:
        partes = [x.strip() for x in re.split(r"\n\s*\n|\n", p["entrada"].get("roteiro") or "") if x.strip()][:MAX_PLANOS]
        dur = p["entrada"]["duracao"] / max(1, len(partes))
        r = {"titulo": p["titulo"], "planos": [{"dur": dur, "tipo": "medio", "camera": "zoom_in", "efeitos": [], "transicao": "corte",
                                                 "acao_pt": x, "quem": [], "falas": [], "sfx": [],
                                                 "desenhos": [{"prompt_en": x, "segura": 1, "impacto": False}]} for x in partes]}
    with _TRAVA:
        p = carregar(pid, base)
        aplicar_planos(p, r)
        log(p, f"🤖 {len(p['planos'])} plano(s) planejados")
        salvar(p, base)
    return f"{len(p['planos'])} plano(s)"


def _cid_por_nome(p: Dict[str, Any], nome: str) -> Optional[str]:
    n = _txt(nome, 60).lower()
    c = next((x for x in p["personagens"] if x["nome"].lower() == n), None) or \
        next((x for x in p["personagens"] if n and (n in x["nome"].lower() or x["nome"].lower() in n)), None)
    return c["id"] if c else None


def novo_plano(d: Optional[Dict[str, Any]] = None, p: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    d = d or {}
    p = p or {"personagens": []}

    def num(v, pad, lo, hi):
        try:
            return round(max(lo, min(hi, float(v))), 2)
        except (TypeError, ValueError):
            return pad
    quem = []
    for x in d.get("quem") or []:
        cid = x if any(c["id"] == x for c in p["personagens"]) else _cid_por_nome(p, str(x))
        if cid and cid not in quem:
            quem.append(cid)
    falas = []
    for f in (d.get("falas") or [])[:6]:
        if not isinstance(f, dict) or not _txt(f.get("texto"), 200):
            continue
        q = f.get("quem")
        cid = q if any(c["id"] == q for c in p["personagens"]) else _cid_por_nome(p, str(q or ""))
        falas.append({"quem": cid or "", "texto": _txt(f.get("texto"), 200), "t": num(f.get("t"), 0.0, 0, 30), "audio": {}})
    desenhos = []
    for x in (d.get("desenhos") or d.get("quadros") or [{}])[:MAX_QUADROS]:
        if not isinstance(x, dict):
            continue
        q = {"id": x.get("id") or _id("q"), "prompt_en": _txt(x.get("prompt_en"), 1500), "segura": num(x.get("segura"), 1, 0.3, 8),
             "impacto": bool(x.get("impacto")), "estado": x.get("estado") or "", "job": x.get("job"),
             "arquivo": x.get("arquivo"), "versoes": list(x.get("versoes") or []), "erro": x.get("erro"), "msg": x.get("msg")}
        desenhos.append(q)
    return {"id": d.get("id") or _id("pl"), "dur": num(d.get("dur"), 2.0, 0.4, 10), "tipo": d.get("tipo") if d.get("tipo") in TIPOS_PLANO else "medio",
            "camera": d.get("camera") if d.get("camera") in CAMERAS else "fixa",
            "efeitos": [x for x in d.get("efeitos") or [] if x in EFEITOS],
            "transicao": d.get("transicao") if d.get("transicao") in TRANSICOES else "corte",
            "acao_pt": _txt(d.get("acao_pt"), 600), "quem": quem, "falas": falas,
            "sfx": [{"som": x["som"], "t": num(x.get("t"), 0.0, 0, 30)} for x in d.get("sfx") or [] if isinstance(x, dict) and x.get("som") in SFX][:6],
            "quadros": desenhos or [{"id": _id("q"), "prompt_en": "", "segura": 1, "impacto": False, "estado": "", "versoes": []}],
            "chave_ok": bool(d.get("chave_ok")), "sequencia": bool(d.get("sequencia"))}


def aplicar_planos(p: Dict[str, Any], r: Dict[str, Any]) -> None:
    if r.get("titulo") and p["titulo"] == "Cena sem título":
        p["titulo"] = _txt(r["titulo"], 120)
    p["planos"] = [novo_plano(x, p) for x in (r.get("planos") or [])[:MAX_PLANOS] if isinstance(x, dict)]


def salvar_planos(p: Dict[str, Any], lista: List[Dict[str, Any]]) -> None:
    """✏ Os planos editados na página (mantém as imagens dos desenhos que continuam)."""
    velhos = {q["id"]: q for pl in p["planos"] for q in pl["quadros"]}
    novos = []
    for x in (lista or [])[:MAX_PLANOS]:
        if not isinstance(x, dict):
            continue
        qs = []
        for q in (x.get("quadros") or [])[:MAX_QUADROS]:
            v = velhos.get(str(q.get("id") or ""))
            qs.append(dict(v, prompt_en=_txt(q.get("prompt_en"), 1500), segura=q.get("segura", v.get("segura")),
                           impacto=bool(q.get("impacto"))) if v else q)
        x = dict(x, quadros=qs)
        novos.append(novo_plano(x, p))
    p["planos"] = novos


def duracao_total(p: Dict[str, Any]) -> float:
    return sum(float(pl["dur"]) for pl in p["planos"])


def plano(p: Dict[str, Any], plid: str) -> Dict[str, Any]:
    x = next((y for y in p["planos"] if y["id"] == plid), None)
    if not x:
        raise CineErro("Plano não encontrado.")
    return x


# ------------------------------------------------------------------ 🎨 os desenhos no Flow (só IMAGENS)
def _ref_chave(p: Dict[str, Any], pl: Dict[str, Any], base: str) -> Tuple[Optional[str], List[str]]:
    """A referência do quadro-chave: os designs de quem está no plano + o cenário, lado a lado (e o que é cada um)."""
    from PIL import Image
    import personagens_limpeza as L
    cams, rot = [], []
    for cid in pl.get("quem") or []:
        c = next((x for x in p["personagens"] if x["id"] == cid), None)
        cam = os.path.join(pasta(p["id"], base), "refs", c["imagem"]) if c else None
        if cam and os.path.isfile(cam):
            cams.append(cam)
            rot.append(f"the character design of {c['nome']} (copy face, hair, outfit, colors exactly)")
    _desc, img = lugar_info(p, base)
    if img and os.path.isfile(img):
        cams.append(img)
        rot.append("the location (background, lighting and colors)")
    if not cams:
        return None, []
    ims = []
    for cam in cams[:4]:
        im = Image.open(cam).convert("RGBA")
        f = Image.new("RGBA", im.size, (128, 128, 128, 255))
        f.alpha_composite(im)
        ims.append(f.convert("RGB"))
    col = L.colagem(ims) if len(ims) > 1 else ims[0]
    d = os.path.join(pasta(p["id"], base), "refs")
    import hashlib
    buf = io.BytesIO()
    col.save(buf, "PNG")
    cam = os.path.join(d, f"_ref_{hashlib.md5(buf.getvalue()).hexdigest()[:10]}.png")
    if not os.path.isfile(cam):
        with open(cam, "wb") as f:
            f.write(buf.getvalue())
    return cam, rot[:4]


def prompt_quadro(p: Dict[str, Any], pl: Dict[str, Any], k: int, correcao: str = "", rot: Optional[List[str]] = None,
                  base: str = _BASE) -> str:
    q = pl["quadros"][k]
    nomes = {c["id"]: c for c in p["personagens"]}
    estilo = estilo_en(p)
    fixo = ("ONE full single frame (a finished cel) of a high-budget TV anime ACTION scene, top studio key animation "
            "quality: dynamic composition with depth, strong perspective, dramatic cinematic lighting, clean line art, rich "
            "color. NO text, NO speech bubbles, NO captions, NO panel borders, NO watermark, NO letterbox.")
    if k == 0:
        L = []
        if rot and len(rot) > 1:
            L.append("The reference image has " + str(len(rot)) + " panels side by side, left to right: "
                     + "; ".join(f"{i + 1}) {t}" for i, t in enumerate(rot)) + ".")
        elif rot:
            L.append(f"The reference image is {rot[0]}.")
        L.append(fixo)
        L.append(f"SHOT: {TIPOS_PLANO[pl['tipo']][1]}.")
        L.append(f"THE MOMENT: {q.get('prompt_en') or pl.get('acao_pt') or ''}")
        cs = [nomes[c] for c in pl.get("quem") or [] if c in nomes]
        if cs:
            L.append("CHARACTERS (keep them exactly): " + "; ".join(f"{c['nome']}: {c.get('aparencia_en') or 'as in the reference'}" for c in cs))
        desc, _img = lugar_info(p, base)
        if desc:
            L.append(f"LOCATION: {desc[:600]}")
    else:
        L = ["The reference image is the PREVIOUS DRAWING of this same animated shot. Draw the NEXT DRAWING of the "
             "animation: keep EXACTLY the same characters (faces, outfits, colors), art style, line art, background and "
             "camera framing — change ONLY what moves:", q.get("prompt_en") or "the motion continues",
             "It is a single in-between/key drawing of a fluid sakuga motion (stretch, arcs, motion trails are fine). " + fixo]
    L.append(f"ART STYLE: {estilo}.")
    if correcao:
        L.append(f"CHANGES FOR THIS ATTEMPT: {correcao}")
    return " ".join(" ".join(L).split())[:3900]


def _cam_quadro(p: Dict[str, Any], q: Dict[str, Any], base: str) -> Optional[str]:
    cam = os.path.join(pasta(p["id"], base), "quadros", q["arquivo"]) if q.get("arquivo") else None
    return cam if cam and os.path.isfile(cam) else None


def _mandar(itens: List[Dict[str, Any]], proporcao: str) -> List[Dict[str, Any]]:
    import flow_lote
    try:
        return flow_lote.lote().adicionar(itens, proporcao=proporcao, quantidade="x1")
    except ValueError as exc:
        raise CineErro(str(exc))


def _iniciar() -> str:
    try:
        import flow_lote
        flow_lote.lote().iniciar()
        return ""
    except Exception as exc:  # noqa: BLE001
        return f"o Flow em massa não ligou agora ({str(exc)[:160]}) — ▶ Continuar na aba Flow"


def _item_quadro(p: Dict[str, Any], pl: Dict[str, Any], k: int, correcao: str, base: str) -> Dict[str, Any]:
    if k == 0:
        ref, rot = _ref_chave(p, pl, base)
    else:
        ref, rot = _cam_quadro(p, pl["quadros"][k - 1], base), []
        if not ref:
            raise CineErro("O desenho anterior ainda não está pronto.")
    it = {"prompt": prompt_quadro(p, pl, k, correcao, rot, base), "tipo": "imagem", "origem": "anime_cine"}
    if ref:
        it["referencia_arquivo"] = ref
    return it


def gerar_chaves(pid: str, plids: Optional[List[str]] = None, correcao: str = "", base: str = _BASE) -> Dict[str, Any]:
    """🎨 O QUADRO-CHAVE de cada plano (o 1º desenho) — sem plids: os que ainda não têm."""
    with _TRAVA:
        p = carregar(pid, base)
        alvo = [pl for pl in p["planos"] if (plids and pl["id"] in plids) or
                (not plids and not pl["quadros"][0].get("arquivo") and pl["quadros"][0].get("estado") not in ESPERA)]
        alvo = [pl for pl in alvo if pl["quadros"][0].get("estado") not in ESPERA]
        if not alvo:
            raise CineErro("Nada pra gerar (os quadros-chave já existem ou estão na fila).")
        itens = [_item_quadro(p, pl, 0, _txt(correcao, 800), base) for pl in alvo]
        for pl, j in zip(alvo, _mandar(itens, p["entrada"]["proporcao"])):
            pl["quadros"][0].update(estado="fila", job=j["id"], erro=None, msg="⏳ na fila do Flow", correcao=_txt(correcao, 300))
            pl["chave_ok"] = False
        log(p, f"🎨 {len(alvo)} quadro(s)-chave pro Flow")
        salvar(p, base)
    return {"enviadas": len(alvo), "aviso": _iniciar()}


def refazer_quadro(pid: str, plid: str, qid: str, correcao: str = "", base: str = _BASE) -> Dict[str, Any]:
    with _TRAVA:
        p = carregar(pid, base)
        pl = plano(p, plid)
        k = next((i for i, q in enumerate(pl["quadros"]) if q["id"] == qid), None)
        if k is None:
            raise CineErro("Desenho não encontrado.")
        if pl["quadros"][k].get("estado") in ESPERA:
            raise CineErro("Esse desenho já está na fila.")
        it = _item_quadro(p, pl, k, _txt(correcao, 800), base)
        j = _mandar([it], p["entrada"]["proporcao"])[0]
        pl["quadros"][k].update(estado="fila", job=j["id"], erro=None, msg="⏳ na fila do Flow", correcao=_txt(correcao, 300))
        if k == 0:
            pl["chave_ok"] = False
        salvar(p, base)
    return {"enviadas": 1, "aviso": _iniciar()}


def aprovar_chave(pid: str, plid: str, ok: bool = True, base: str = _BASE) -> None:
    with _TRAVA:
        p = carregar(pid, base)
        pl = plano(p, plid)
        if ok and not pl["quadros"][0].get("arquivo"):
            raise CineErro("O quadro-chave ainda não tem imagem.")
        pl["chave_ok"] = bool(ok)
        salvar(p, base)


def gerar_sequencia(pid: str, plids: Optional[List[str]] = None, base: str = _BASE) -> Dict[str, Any]:
    """🎞 Os desenhos do movimento: um de cada vez, cada um A PARTIR DO ANTERIOR (o acompanhar manda o próximo)."""
    with _TRAVA:
        p = carregar(pid, base)
        alvo = [pl for pl in p["planos"] if (not plids or pl["id"] in plids) and pl.get("chave_ok") and len(pl["quadros"]) > 1]
        if not alvo:
            raise CineErro("Aprove o quadro-chave dos planos (✔) — e o plano precisa ter mais de 1 desenho.")
        n = 0
        for pl in alvo:
            pl["sequencia"] = True
            k = next((i for i, q in enumerate(pl["quadros"]) if i > 0 and not q.get("arquivo") and q.get("estado") not in ESPERA), None)
            if k is None or any(q.get("estado") in ESPERA for q in pl["quadros"]):
                continue
            it = _item_quadro(p, pl, k, "", base)
            j = _mandar([it], p["entrada"]["proporcao"])[0]
            pl["quadros"][k].update(estado="fila", job=j["id"], erro=None, msg="⏳ na fila do Flow")
            n += 1
        log(p, f"🎞 desenhos do movimento: {n} plano(s) começaram")
        salvar(p, base)
    return {"enviadas": n, "aviso": _iniciar()}


def enviar_desenho(pid: str, plid: str, qid: str, img, base: str = _BASE) -> None:
    """📤 Um desenho seu no lugar (vira uma versão)."""
    with _TRAVA:
        p = carregar(pid, base)
        pl = plano(p, plid)
        q = next((x for x in pl["quadros"] if x["id"] == qid), None)
        if not q:
            raise CineErro("Desenho não encontrado.")
        _guardar_quadro(p, q, img, base, "sua")
        salvar(p, base)


def escolher_versao(pid: str, plid: str, qid: str, arquivo: str, base: str = _BASE) -> None:
    with _TRAVA:
        p = carregar(pid, base)
        q = next((x for x in plano(p, plid)["quadros"] if x["id"] == qid), None)
        if not q or arquivo not in (q.get("versoes") or []):
            raise CineErro("Versão não encontrada.")
        q["arquivo"] = arquivo
        salvar(p, base)


def _guardar_quadro(p: Dict[str, Any], q: Dict[str, Any], img, base: str, origem: str = "flow") -> None:
    W, H = PROPORCOES[p["entrada"]["proporcao"]]
    im = img.convert("RGB")
    k = max(W / im.width, H / im.height)  # preenche o quadro (corta o que sobra, sem distorcer)
    im = im.resize((max(W, round(im.width * k)), max(H, round(im.height * k))), _lanczos())
    x, y = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((x, y, x + W, y + H))
    arq = f"{q['id']}_{secrets.token_hex(3)}.jpg"
    d = os.path.join(pasta(p["id"], base), "quadros")
    os.makedirs(d, exist_ok=True)
    im.save(os.path.join(d, arq), quality=93)
    q.setdefault("versoes", []).append(arq)
    q.update(arquivo=arq, estado="pronta", erro=None, msg=None, origem=origem)


def _lanczos():
    from PIL import Image
    return Image.LANCZOS


def acompanhar(pid: str, base: str = _BASE) -> bool:
    """Puxa os desenhos prontos do Flow e, nos planos em sequência, manda o PRÓXIMO desenho (a partir do que chegou)."""
    p = carregar(pid, base)
    if not any(q.get("estado") in ESPERA for pl in p["planos"] for q in pl["quadros"]) and \
            not any(pl.get("sequencia") for pl in p["planos"]):
        return False
    import flow_lote
    lote = flow_lote.lote()
    with lote.trava:
        fila = {j["id"]: dict(j) for j in lote.fila}
        rodando = lote.rodando
    mudou = False
    proximos: List[Tuple[str, int]] = []
    with _TRAVA:
        p = carregar(pid, base)
        for pl in p["planos"]:
            for k, q in enumerate(pl["quadros"]):
                if q.get("estado") not in ESPERA or not q.get("job"):
                    continue
                fj = fila.get(q["job"])
                antes = (q.get("estado"), q.get("msg"))
                if fj is None:
                    q.update(estado="erro", erro="o pedido sumiu da fila do 🚀 Flow em massa — gere de novo")
                elif fj["estado"] == "ok":
                    ok = False
                    for r in fj.get("resultados") or []:
                        try:
                            import flow_estudio as FE
                            from PIL import Image
                            orig = os.path.join(FE.pasta_galeria(), r.get("arquivo") or "")
                            if r.get("tipo") == "imagem" and os.path.isfile(orig):
                                _guardar_quadro(p, q, Image.open(orig), base)
                                ok = True
                                break
                        except Exception as exc:  # noqa: BLE001
                            q.update(estado="erro", erro=f"a imagem chegou mas não deu pra guardar: {str(exc)[:160]}")
                    if not ok and q.get("estado") != "erro":
                        q.update(estado="erro", erro="o Flow terminou sem imagem")
                elif fj["estado"] == "erro":
                    q.update(estado="erro", erro=str(fj.get("erro") or "o Flow falhou")[:300])
                elif fj["estado"] in ("rodando", "convertendo"):
                    q.update(estado="gerando", msg=f"🎨 desenhando no Flow (conta “{fj.get('conta')}”)")
                elif not rodando:
                    q.update(msg="⏸ o Flow em massa está parado — ▶ Continuar na aba Flow")
                else:
                    q.update(msg="⏳ na fila do Flow")
                mudou = mudou or antes != (q.get("estado"), q.get("msg"))
            if pl.get("sequencia") and not any(q.get("estado") in ESPERA for q in pl["quadros"]):
                k = next((i for i, q in enumerate(pl["quadros"]) if i > 0 and not q.get("arquivo")), None)
                if k is None or pl["quadros"][k].get("estado") == "erro":
                    pl["sequencia"] = False  # acabou (ou parou num erro — 🔁 refaz e segue)
                    mudou = True
                elif pl["quadros"][k - 1].get("arquivo"):
                    proximos.append((pl["id"], k))
        for plid, k in proximos:
            pl = plano(p, plid)
            try:
                it = _item_quadro(p, pl, k, "", base)
                j = _mandar([it], p["entrada"]["proporcao"])[0]
                pl["quadros"][k].update(estado="fila", job=j["id"], erro=None, msg="⏳ na fila do Flow")
                mudou = True
            except CineErro as exc:
                pl["quadros"][k].update(estado="erro", erro=str(exc))
                pl["sequencia"] = False
        if mudou:
            salvar(p, base)
    if proximos:
        _iniciar()
    return mudou


# ------------------------------------------------------------------ 🎙 vozes
def gerar_vozes(pid: str, base: str, tts: Callable[..., Any], limpar: Callable[[str, str], str],
                on_log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    import anime2d as A
    import multivoz
    p = carregar(pid, base)
    mp = p["entrada"].get("motor_perfil") or "xtts"
    d = os.path.join(pasta(pid, base), "vozes")
    os.makedirs(d, exist_ok=True)
    feitas, sem_voz, erros = 0, 0, []
    vozes = {c["id"]: A.voz_por_slug(c.get("voz") or "", mp) for c in p["personagens"]}
    for i, pl in enumerate(p["planos"]):
        for j, f in enumerate(pl["falas"]):
            v = vozes.get(f.get("quem") or "")
            chave = f"{(next((c.get('voz') for c in p['personagens'] if c['id'] == f.get('quem')), '') or '')}|{f['texto']}"
            if (f.get("audio") or {}).get("chave") == chave and os.path.isfile(os.path.join(d, f["audio"].get("arquivo") or "_")):
                continue
            if not v:
                sem_voz += 1
                continue
            on_log(f"🎙 “{f['texto'][:40]}”")
            motor, kw = multivoz.kwargs_da_voz(v)
            arq = f"{pl['id']}_{j}_{secrets.token_hex(2)}.wav"
            bruto = os.path.join(d, "_" + arq)
            try:
                tts(motor, limpar(f["texto"], motor), bruto, **kw)
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", bruto, "-ar", "48000", "-ac", "2", os.path.join(d, arq)],
                               check=True, capture_output=True, timeout=120)
            except Exception as exc:  # noqa: BLE001
                erros.append(str(exc)[:120])
                continue
            finally:
                try:
                    os.remove(bruto)
                except OSError:
                    pass
            with _TRAVA:
                q = carregar(pid, base)
                q["planos"][i]["falas"][j]["audio"] = {"arquivo": arq, "dur": round(A.duracao_wav(os.path.join(d, arq)), 3), "chave": chave}
                salvar(q, base)
            feitas += 1
    return {"feitas": feitas, "sem_voz": sem_voz, "erros": erros}


# ------------------------------------------------------------------ 🎞 a animação (montada aqui, quadro a quadro)
def _tempos(pl: Dict[str, Any], n_quadros: int) -> List[Tuple[int, int]]:
    """[(índice do desenho, quantos quadros a 24 fps)] — proporcional ao 'segura', em múltiplos de 2 (anime "em 2"),
    somando exatamente a duração do plano. Desenhos demais pro tempo: 1 quadro cada (e os que não cabem saem)."""
    total = max(1, round(float(pl["dur"]) * FPS))
    pesos = [max(0.3, float(q.get("segura") or 1)) for q in pl["quadros"][:max(1, n_quadros)]]
    if len(pesos) * 2 > total:
        k = min(len(pesos), total)
        return [(i, 1) for i in range(k - 1)] + [(k - 1, total - (k - 1))]
    soma = sum(pesos)
    n = [max(2, int(round(total * w / soma / 2)) * 2) for w in pesos]
    guarda = 0
    while sum(n) != total and guarda < 400:
        guarda += 1
        diff = total - sum(n)
        if diff > 0:
            n[n.index(min(n))] += min(diff, 2)
        else:
            k = n.index(max(n))
            if n[k] <= 2:
                break
            n[k] -= min(-diff, 2)
    if sum(n) != total:
        n[-1] = max(1, n[-1] + total - sum(n))
    return list(enumerate(n))


class _Plano:
    """Gera os quadros de UM plano (sem guardar todos na memória): desenho do instante + câmera + efeitos."""

    def __init__(self, p: Dict[str, Any], pl: Dict[str, Any], base: str, W: int, H: int):
        from PIL import Image
        self.pl, self.W, self.H = pl, W, H
        self.imgs = []
        for q in pl["quadros"]:
            cam = _cam_quadro(p, q, base)
            if not cam:
                break  # o movimento para no último desenho pronto
            self.imgs.append(Image.open(cam).convert("RGB"))
        if not self.imgs:
            self.imgs = [_cartao(f"(plano sem desenho) {pl.get('acao_pt') or ''}", W, H)]
        self.mapa = []
        for k, n in _tempos(pl, len(self.imgs)):
            self.mapa += [k] * n
        self.n = len(self.mapa)
        self.impactos = []
        acc = 0
        for k, n in _tempos(pl, len(self.imgs)):
            if k < len(pl["quadros"]) and pl["quadros"][k].get("impacto"):
                self.impactos.append(acc)
            acc += n
        self.cache: Dict[Tuple[int, int, int, int, int], Any] = {}
        self.rng = random.Random(pl["id"])
        self.part = [(self.rng.random(), self.rng.random(), 0.3 + self.rng.random(), self.rng.random()) for _ in range(70)]

    def quadro(self, i: int):
        from PIL import Image, ImageChops, ImageDraw, ImageOps
        pl, W, H = self.pl, self.W, self.H
        i = max(0, min(self.n - 1, i))
        k = self.mapa[i]
        src = self.imgs[k]
        u = i / max(1, self.n - 1)
        ef = set(pl.get("efeitos") or [])
        cam = pl.get("camera") or "fixa"
        z, cx, cy = 1.0, 0.5, 0.5
        if cam == "zoom_in":
            z = 1.0 + 0.16 * _suave(u)
        elif cam == "zoom_out":
            z = 1.16 - 0.16 * _suave(u)
        elif cam in ("pan_esq", "pan_dir", "sobe", "desce", "orbita"):
            z = 1.14
            d = (_suave(u) - 0.5) * 0.12
            if cam == "pan_dir":
                cx = 0.5 + d
            elif cam == "pan_esq":
                cx = 0.5 - d
            elif cam == "sobe":
                cy = 0.5 - d
            elif cam == "desce":
                cy = 0.5 + d
            else:
                cx, cy = 0.5 + 0.05 * math.cos(u * math.pi), 0.5 + 0.04 * math.sin(u * math.pi)
        elif cam == "chicote":  # whip pan: chega rápido de lado e assenta
            z = 1.14
            cx = 0.5 + 0.07 * max(0.0, 1 - u * 4) ** 2
        # 📳 tremor: no plano todo (efeito) ou decaindo depois de cada impacto
        dx = dy = 0.0
        forca = 0.0
        if "tremor" in ef:
            forca = 0.010
        for t0 in self.impactos:
            if 0 <= i - t0 < 10:
                forca = max(forca, 0.022 * (1 - (i - t0) / 10))
        if forca:
            r = random.Random(f"{pl['id']}{i // 2}")
            dx, dy = (r.random() - 0.5) * 2 * forca, (r.random() - 0.5) * 2 * forca
            z = max(z, 1.0 + 2.2 * forca)
        chave = (k, round(z * 1000), round((cx + dx) * 4000), round((cy + dy) * 4000), 0)
        fr = self.cache.get(chave)
        if fr is None:
            fr = _enquadrar(src, W, H, z, cx + dx, cy + dy)
            if len(self.cache) > 48:
                self.cache.clear()
            self.cache[chave] = fr
        fr = fr.copy()
        # 💥 quadro de impacto: os 2 primeiros quadros do desenho de impacto em negativo de alto contraste, 1 flash antes
        for t0 in self.impactos:
            if 0 <= i - t0 < 2:
                g = ImageOps.autocontrast(ImageOps.grayscale(fr), cutoff=4)
                g = ImageOps.invert(g).point(lambda v: 255 if v > 150 else (0 if v < 90 else v))
                fr = Image.merge("RGB", (g, g, g))
            elif i - t0 == 2:
                fr = Image.blend(fr, Image.new("RGB", (W, H), (255, 255, 255)), 0.45)
        if "flash" in ef and i < 3:
            fr = Image.blend(fr, Image.new("RGB", (W, H), (255, 255, 255)), (3 - i) / 3 * 0.85)
        if "foco" in ef or "linhas" in ef:
            fr = _linhas(fr, i, pl["id"], foco="foco" in ef)
        if "brasas" in ef or "chuva" in ef:
            fr = _particulas(fr, i, self.part, "chuva" if "chuva" in ef and "brasas" not in ef else "brasas")
        if "vinheta" in ef:
            fr = _vinheta(fr)
        return fr


def _suave(u: float) -> float:
    return u * u * (3 - 2 * u)


def _enquadrar(src, W: int, H: int, z: float, cx: float, cy: float):
    """O pedaço do desenho que a câmera mostra (zoom z ≥ 1, centro cx, cy em fração)."""
    from PIL import Image
    k = max(W / src.width, H / src.height) * z
    vw, vh = W / k, H / k
    x0 = min(max(0.0, cx * src.width - vw / 2), src.width - vw)
    y0 = min(max(0.0, cy * src.height - vh / 2), src.height - vh)
    return src.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + vw, y0 + vh))


_LINHAS_CACHE: Dict[Tuple[int, int, int, bool], Any] = {}


def _linhas(fr, i: int, semente: str, foco: bool = False):
    """💨 Linhas de velocidade / de foco (radiais, nas bordas — o centro fica limpo), trocando a cada 2 quadros."""
    from PIL import Image, ImageDraw
    W, H = fr.size
    chave = (W, H, (hash(semente) + i // 2) % 6, foco)
    ov = _LINHAS_CACHE.get(chave)
    if ov is None:
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        r = random.Random(str(chave))
        cx, cy = W / 2, H / 2
        R = math.hypot(W, H) / 2
        for _ in range(110 if foco else 80):
            a = r.random() * 2 * math.pi
            r0 = R * (0.42 + r.random() * 0.25)
            larg = r.random() * (0.012 if foco else 0.008)
            cor = (0, 0, 0, 200) if foco else (255, 255, 255, 150)
            pts = [(cx + math.cos(a - larg) * R * 1.1, cy + math.sin(a - larg) * R * 1.1),
                   (cx + math.cos(a + larg) * R * 1.1, cy + math.sin(a + larg) * R * 1.1),
                   (cx + math.cos(a) * r0, cy + math.sin(a) * r0)]
            d.polygon(pts, fill=cor)
        _LINHAS_CACHE[chave] = ov
    base = fr.convert("RGBA")
    base.alpha_composite(ov)
    return base.convert("RGB")


def _particulas(fr, i: int, part, tipo: str):
    from PIL import ImageDraw
    W, H = fr.size
    fr = fr.copy()
    d = ImageDraw.Draw(fr, "RGBA")
    t = i / FPS
    for x0, y0, vel, fase in part:
        if tipo == "chuva":
            x = (x0 * W + t * 120) % W
            y = (y0 * H + t * H * 1.6 * vel) % H
            d.line([(x, y), (x - 6, y - 34)], fill=(220, 230, 255, 120), width=2)
        else:  # 🔥 brasas subindo e piscando
            x = (x0 * W + math.sin(t * 2 + fase * 6) * 30) % W
            y = (y0 * H - t * H * 0.25 * vel) % H
            a = int(140 + 110 * math.sin(t * 8 + fase * 10))
            r = 2 + 3 * vel
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 150 + int(80 * fase), 40, max(0, a)))
    return fr


_VINHETA: Dict[Tuple[int, int], Any] = {}


def _vinheta(fr):
    from PIL import Image, ImageDraw, ImageFilter
    W, H = fr.size
    m = _VINHETA.get((W, H))
    if m is None:
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).ellipse([-W * 0.15, -H * 0.2, W * 1.15, H * 1.2], fill=255)
        m = m.filter(ImageFilter.GaussianBlur(W // 10))
        _VINHETA[(W, H)] = m
    return Image.composite(fr, Image.new("RGB", (W, H), (0, 0, 0)), m)


def _cartao(txt: str, W: int, H: int):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (W, H), (20, 20, 28))
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(18, W // 50))
    except Exception:  # noqa: BLE001
        f = ImageFont.load_default()
    ImageDraw.Draw(im).text((W * 0.06, H * 0.45), txt[:90], fill=(200, 200, 210), font=f)
    return im


def _legenda(fr, nome: str, texto: str, cor: Tuple[int, int, int] = (255, 214, 74)):
    from PIL import ImageDraw, ImageFont
    W, H = fr.size
    d = ImageDraw.Draw(fr, "RGBA")
    tam = max(22, W // 48)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", tam)
    except Exception:  # noqa: BLE001
        f = ImageFont.load_default()
    linha = f"{nome}: {texto}" if nome else texto
    larg = d.textlength(linha, font=f)
    if larg > W * 0.9:  # quebra em 2 linhas
        meio = len(linha) // 2
        corte = linha.rfind(" ", 0, meio + 10)
        linhas = [linha[:corte], linha[corte + 1:]] if corte > 0 else [linha]
    else:
        linhas = [linha]
    y = H * 0.86 - (len(linhas) - 1) * tam * 1.25
    for ln in linhas:
        lw = d.textlength(ln, font=f)
        d.text(((W - lw) / 2, y), ln, font=f, fill=(255, 255, 255), stroke_width=max(2, tam // 9), stroke_fill=(0, 0, 0))
        y += tam * 1.25
    return fr


def _falas_globais(p: Dict[str, Any], base: str) -> List[Dict[str, Any]]:
    """As falas no tempo da cena (início, duração, o áudio)."""
    out, t0 = [], 0.0
    nomes = {c["id"]: c["nome"] for c in p["personagens"]}
    for pl in p["planos"]:
        for f in pl["falas"]:
            a = f.get("audio") or {}
            cam = os.path.join(pasta(p["id"], base), "vozes", a["arquivo"]) if a.get("arquivo") else None
            dur = float(a.get("dur") or 0) or max(1.0, len(f["texto"]) / 14)
            out.append({"t": t0 + float(f.get("t") or 0), "dur": dur, "texto": f["texto"], "nome": nomes.get(f.get("quem"), ""),
                        "audio": cam if cam and os.path.isfile(cam) else None})
        t0 += float(pl["dur"])
    return out


def _sfx_globais(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Os sons da biblioteca no tempo da cena (o PICO do som cai no instante)."""
    try:
        import dp_sons
    except Exception:  # noqa: BLE001
        return []
    cats: Dict[str, List[str]] = {}
    for s in dp_sons.sons():
        cats.setdefault(s["categoria"], []).append(s["id"])
    out, t0 = [], 0.0
    for pl in p["planos"]:
        r = random.Random(pl["id"])
        eventos = list(pl.get("sfx") or [])
        acc = 0
        for k, n in _tempos(pl, len([q for q in pl["quadros"] if q.get("arquivo")]) or 1):
            if k < len(pl["quadros"]) and pl["quadros"][k].get("impacto") and not any(e["som"] == "impacto" for e in eventos):
                eventos.append({"som": "impacto", "t": acc / FPS})
            acc += n
        for e in eventos:
            ids = [i for c in SFX.get(e["som"], ("", []))[1] for i in cats.get(c, [])]
            if ids:
                ev = dp_sons.evento(r.choice(sorted(ids)), t0 + float(e.get("t") or 0))
                if ev:
                    out.append(ev)
        t0 += float(pl["dur"])
    return out


def _audio(p: Dict[str, Any], base: str, total: float, destino: str) -> str:
    """As falas (TTS) nos seus instantes + os efeitos sonoros → um WAV."""
    falas = [f for f in _falas_globais(p, base) if f["audio"]]
    args = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    filtros, rot = [], ["[0:a]"]
    for k, f in enumerate(falas, start=1):
        args += ["-i", f["audio"]]
        ms = int(round(f["t"] * 1000))
        filtros.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms}[v{k}]")
        rot.append(f"[v{k}]")
    falas_wav = destino + ".falas.wav"
    if falas:
        filtros.append("".join(rot) + f"amix=inputs={len(rot)}:normalize=0:duration=first[out]")
        subprocess.run(args + ["-filter_complex", ";".join(filtros), "-map", "[out]", "-c:a", "pcm_s16le", falas_wav],
                       check=True, capture_output=True, timeout=600)
    else:
        subprocess.run(args + ["-c:a", "pcm_s16le", falas_wav], check=True, capture_output=True, timeout=120)
    eventos = _sfx_globais(p)
    if eventos:
        import dp_sons
        dp_sons.mixar(falas_wav, eventos, destino, volume_sfx=float(p["entrada"].get("volume_sfx") or 0.7))
        try:
            os.remove(falas_wav)
        except OSError:
            pass
    else:
        os.replace(falas_wav, destino)
    return destino


def montar(pid: str, base: str = _BASE, planos: Optional[List[str]] = None, escala: float = 1.0,
           on_log: Callable[[str], None] = lambda _m: None) -> str:
    """🎬 A cena animada → mp4 (com as transições, as legendas, as falas e os sons). `planos`: só esses (prévia)."""
    p = carregar(pid, base)
    lista = [pl for pl in p["planos"] if not planos or pl["id"] in planos]
    if not lista:
        raise CineErro("Sem planos — planeje a cena primeiro.")
    W0, H0 = PROPORCOES[p["entrada"]["proporcao"]]
    W, H = int(W0 * escala) // 2 * 2, int(H0 * escala) // 2 * 2
    q = dict(p, planos=lista)
    total = duracao_total(q)
    d = os.path.join(pasta(pid, base), "saida")
    os.makedirs(d, exist_ok=True)
    nome = ("previa_" + lista[0]["id"] if planos else "cena") + f"_{secrets.token_hex(2)}.mp4"
    destino = os.path.join(d, nome)
    audio = _audio(q, base, total, destino + ".wav")
    falas = _falas_globais(q, base) if p["entrada"].get("legendas", True) else []
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", audio, "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac",
           "-b:a", "192k", "-shortest", "-movflags", "+faststart", destino]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    from PIL import Image
    try:
        geradores = [_Plano(q, pl, base, W, H) for pl in lista]
        t_global = 0
        TR = 8  # quadros de transição
        for n, (pl, g) in enumerate(zip(lista, geradores)):
            on_log(f"🎞 plano {n + 1}/{len(lista)}")
            prox = geradores[n + 1] if n + 1 < len(geradores) else None
            tr = pl.get("transicao") or "corte"
            for i in range(g.n):
                fr = g.quadro(i)
                resta = g.n - i
                if prox is not None and tr == "dissolver" and resta <= TR:
                    fr = Image.blend(fr, prox.quadro(0), (TR - resta + 1) / (TR + 1) * 0.5)
                elif prox is not None and tr == "preto" and resta <= TR:
                    fr = Image.blend(fr, Image.new("RGB", (W, H), (0, 0, 0)), (TR - resta + 1) / TR)
                elif prox is not None and tr == "flash" and resta <= 2:
                    fr = Image.blend(fr, Image.new("RGB", (W, H), (255, 255, 255)), 0.9 if resta == 1 else 0.55)
                if n > 0 and (lista[n - 1].get("transicao") == "preto") and i < TR:
                    fr = Image.blend(fr, Image.new("RGB", (W, H), (0, 0, 0)), 1 - (i + 1) / TR)
                if n > 0 and (lista[n - 1].get("transicao") == "dissolver") and i < TR:
                    pass  # (o dissolver já misturou no fim do anterior)
                t = (t_global + i) / FPS
                ativa = next((f for f in falas if f["t"] <= t < f["t"] + f["dur"]), None)
                if ativa:
                    fr = _legenda(fr, ativa["nome"], ativa["texto"])
                proc.stdin.write(fr.tobytes())
            t_global += g.n
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        if proc.wait(timeout=1800) != 0:
            raise CineErro(f"o ffmpeg falhou: {err[-400:]}")
    finally:
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            os.remove(audio)
        except OSError:
            pass
    if not planos:
        with _TRAVA:
            p = carregar(pid, base)
            velho = (p.get("saida") or {}).get("mp4")
            p["saida"] = {"mp4": nome, "quando": time.time(), "dur": round(total, 2)}
            log(p, f"🎬 cena montada ({total:.1f} s)")
            salvar(p, base)
        if velho and velho != nome:
            try:
                os.remove(os.path.join(d, velho))
            except OSError:
                pass
    else:
        for x in os.listdir(d):  # as prévias antigas desse plano saem
            if x.startswith("previa_" + lista[0]["id"]) and x != nome:
                try:
                    os.remove(os.path.join(d, x))
                except OSError:
                    pass
    return nome


# ------------------------------------------------------------------ tela
def para_tela(p: Dict[str, Any], base: str = _BASE) -> Dict[str, Any]:
    out = dict(p)
    out["duracao_total"] = round(duracao_total(p), 2)
    try:
        import criador_personagens as C
        out["ia"] = C.ia_ligada()
    except Exception:  # noqa: BLE001
        out["ia"] = False
    desc, img = lugar_info(p, base)
    out["lugar_desc"] = desc
    out["lugar_tem_img"] = bool(img)
    out["prontos"] = sum(1 for pl in p["planos"] for q in pl["quadros"] if q.get("arquivo"))
    out["total_desenhos"] = sum(len(pl["quadros"]) for pl in p["planos"])
    out["falas_sem_audio"] = sum(1 for pl in p["planos"] for f in pl["falas"] if not (f.get("audio") or {}).get("arquivo"))
    return out
