"""🎬🔎 Animação 2D — STORYBOARD do cenário e REVISÃO dos quadros pela IA (v84_238h).

🎬 Storyboard (por cenário): o Flow recebe o fundo pronto e desenha NELE os personagens e os móveis nos lugares
planejados (um ensaio da cena, como o storyboard de um anime). O Flow sabe compor — sentar na poltrona, pisar no chão,
o tamanho certo pela perspectiva. Depois a IA (visão) LÊ esse storyboard e devolve onde cada um ficou (a caixa e os
pés) → isso vira a posição/escala dos LUGARES e dos MÓVEIS do cenário. A animação continua montada com os recortes,
mas exatamente onde o storyboard pôs cada coisa.

🔎 Revisão (o episódio todo): o motor desenha um quadro de cada corte, a IA olha em lotes (com o que cada corte devia
mostrar: a 👁 visão, quem está onde, o plano) e aponta os erros com uma CORREÇÃO de um vocabulário fechado — mover um
lugar ou um móvel, trocar o plano/foco, usar outro ângulo do cômodo, inserir um corte de reação, ou sugerir regerar uma
imagem. As correções baratas entram sozinhas; o quadro é desenhado de novo e conferido (até 2 rodadas). Regerar
imagem fica como sugestão (custa Flow) — a não ser que você peça.
"""
from __future__ import annotations

import base64
import io
import os
import time
from typing import Any, Callable, Dict, List, Optional

import anime2d as A
import anime2d_cena as C
import react_personagens as R

MAX_QUADROS = 36
LOTE = 6
RODADAS = 2
MAX_CORTES_NOVOS = 6


def _jpeg(cam: str, lado: int = 960) -> Dict[str, Any]:
    from PIL import Image
    im = Image.open(cam).convert("RGB")
    im.thumbnail((lado, lado))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=82)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b.getvalue()).decode()}}


def _dono_layout(p: Dict[str, Any], lo: Dict[str, Any]) -> Dict[str, Any]:
    """O local que GUARDA os lugares/móveis (a variante usa os do original)."""
    return A.base_do_local(p, lo) or lo


# ------------------------------------------------------------------ 🎬 storyboard do cenário
def ocupantes(p: Dict[str, Any], lo: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Quem fica em cada lugar deste cenário nas cenas (o mais frequente) e a pose mais usada ali."""
    dono = _dono_layout(p, lo)
    cont: Dict[str, Dict[str, Dict[str, int]]] = {}
    for s in p["cenas"]:
        for m in s.get("momentos") or []:
            ml = A.local_do_momento(p, s, m)
            if not ml or _dono_layout(p, ml)["id"] != dono["id"] or m.get("tipo") == "destaque":
                continue
            for e in m.get("em_cena") or []:
                c = cont.setdefault(e["posicao"], {}).setdefault(e["cid"], {})
                pose = e.get("pose_en") or (A.POSES.get(e.get("pose")) or ("", ""))[1] or e.get("pose") or ""
                c[pose] = c.get(pose, 0) + 1
    lug = A.lugares_do_local(p, A.layout_do_local(p, lo))
    out = []
    for nome, quem in cont.items():
        if nome not in lug:
            continue
        cid = max(quem, key=lambda k: sum(quem[k].values()))
        c = next((x for x in p["personagens"] if x["id"] == cid), None)
        if not c:
            continue
        pose = max(quem[cid], key=quem[cid].get)
        out.append({"lugar": nome, "c": c, "pose": pose, **lug[nome]})
    return out


def _onde(x: float, y: float) -> str:
    return f"around {round(x * 100)}% from the left edge, feet/base at {round(y * 100)}% of the image height"


def prompt_storyboard(p: Dict[str, Any], lo: Dict[str, Any], ocup: List[Dict[str, Any]]) -> str:
    lay = A.layout_do_local(p, lo) or lo
    alt = float((lay.get("chao") or {}).get("alt") or 0.62)
    L = ["STORYBOARD / LAYOUT TEST for a 2D anime TV series. EDIT the FIRST reference image — it is the EMPTY background of "
         "this exact shot: keep it EXACTLY as it is (same camera, same walls, objects, colors and light) and ADD into it, "
         f"drawn in the same art style and at the CORRECT SCALE for the perspective (an adult standing on the front floor is "
         f"about {round(alt * 100)}% of the image height, smaller further back):"]
    for pr in lay.get("props") or []:
        L.append(f"- furniture: {pr.get('prompt_en') or pr['nome']} — {_onde(float(pr.get('x', 0.5)), float(pr.get('y', 0.95)))}, "
                 "standing ON the floor.")
    for o in ocup:
        c = o["c"]
        como = ("sitting, seen from the WAIST UP behind the furniture in front of them" if o.get("corpo") == "cintura" else
                "sitting ON the seat (not on the floor)" if o.get("sentado") else "standing, both feet on the floor")
        L.append(f"- {c['nome']} ({c.get('design_en') or c.get('aparencia_en') or ''}) — {como}, {_onde(float(o['x']), float(o['y']))}, "
                 f"pose: {o['pose'] or 'neutral'}.")
    L.append("The other references show the characters' designs and the furniture. Nothing floats; feet touch the floor; "
             "whoever is behind furniture is hidden by it; nobody overlaps a wall object. " + A.SEM_TEXTO)
    return " ".join(L)[:3900]


def pedir_storyboard(pid: str, lid: str, base: str = A._BASE) -> Dict[str, Any]:
    import flow_lote
    import personagens_limpeza as L
    from PIL import Image
    with A._TRAVA:
        p = A.carregar(pid, base)
        lo = next((x for x in p["locais"] if x["id"] == lid), None)
        if not lo:
            raise A.AnimeErro("Local não encontrado.")
        fundo = A.arquivo_img(p, lo.get("img") or {}, base)
        if not fundo:
            raise A.AnimeErro("Gere (ou envie) o fundo deste cenário antes do storyboard.")
        ocup = ocupantes(p, lo)
        if not ocup:
            raise A.AnimeErro("Nenhuma cena usa este cenário com personagens ainda — escreva as cenas antes.")
        cams = [fundo] + [x for x in (A.ref_personagem(p, o["c"], base) for o in ocup) if x][:3]
        cams += [x for x in (A.arquivo_img(p, pr.get("img") or {}, base) for pr in (A.layout_do_local(p, lo) or {}).get("props") or []) if x][:2]
        ims = []
        for c in dict.fromkeys(cams):
            im = Image.open(c).convert("RGBA")
            fd = Image.new("RGBA", im.size, (128, 128, 128, 255))
            fd.alpha_composite(im)
            ims.append(fd.convert("RGB"))
        d = os.path.join(A.pasta(pid, base), "imagens")
        ref = os.path.join(d, f"_ref_story_{lid}.png")
        (L.colagem(ims) if len(ims) > 1 else ims[0]).save(ref)
        W, H = A.tamanho(p)
        j = flow_lote.lote().adicionar([{"prompt": prompt_storyboard(p, lo, ocup), "tipo": "imagem", "origem": "anime2d",
                                         "referencia_arquivo": ref}], proporcao="16:9" if W > H else "9:16", quantidade="x1")[0]
        lo.setdefault("story", {}).update(estado="fila", job=j["id"], erro=None, msg="⏳ na fila do Flow", lido=False,
                                          ocupantes=[{"lugar": o["lugar"], "personagem": o["c"]["nome"]} for o in ocup])
        A.log(p, f"🎬 storyboard de {lo['nome']} pro Flow ({len(ocup)} personagem(ns))")
        A.salvar(p, base)
    try:
        flow_lote.lote().iniciar()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True}


SCHEMA_LEITURA = {
    "type": "object", "additionalProperties": False, "required": ["lugares", "moveis"],
    "properties": {
        "lugares": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                               "required": ["lugar", "visivel", "x0", "y0", "x1", "y1", "pes_x", "pes_y"],
                                               "properties": {"lugar": {"type": "string"}, "visivel": {"type": "boolean"},
                                                              "x0": {"type": "number"}, "y0": {"type": "number"},
                                                              "x1": {"type": "number"}, "y1": {"type": "number"},
                                                              "pes_x": {"type": "number"}, "pes_y": {"type": "number"}}}},
        "moveis": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                              "required": ["nome", "visivel", "x0", "y0", "x1", "y1"],
                                              "properties": {"nome": {"type": "string"}, "visivel": {"type": "boolean"},
                                                             "x0": {"type": "number"}, "y0": {"type": "number"},
                                                             "x1": {"type": "number"}, "y1": {"type": "number"}}}}}}


def _f(v: Any, lo: float, hi: float, padrao: float) -> float:
    try:
        return round(max(lo, min(hi, float(v))), 4)
    except (TypeError, ValueError):
        return padrao


def ler_storyboard(pid: str, lid: str, base: str = A._BASE) -> str:
    """📐 A IA lê o storyboard pronto → x/y/escala dos lugares e x/y/largura dos móveis."""
    p = A.carregar(pid, base)
    lo = next((x for x in p["locais"] if x["id"] == lid), None)
    if not lo:
        raise A.AnimeErro("Local não encontrado.")
    cam = A.arquivo_img(p, lo.get("story") or {}, base)
    if not cam:
        raise A.AnimeErro("O storyboard deste cenário ainda não está pronto.")
    ocup = (lo.get("story") or {}).get("ocupantes") or []
    lay = A.layout_do_local(p, lo) or lo
    props = lay.get("props") or []
    txt = ("STORYBOARD de um cenário de anime (os personagens e os móveis desenhados no fundo). Ache cada um e responda em "
           "FRAÇÕES da imagem (x: 0 = esquerda, 1 = direita; y: 0 = topo, 1 = base): a caixa (x0,y0 = canto de cima à "
           "esquerda; x1,y1 = canto de baixo à direita) do que APARECE do corpo, e pes_x/pes_y = o ponto onde ele toca o "
           "chão (em pé: entre os pés; sentado: a base do assento; atrás de um móvel: o meio da borda de baixo do que "
           "aparece). visivel=false se não estiver na imagem.\nLUGARES (quem está em cada um): "
           + "; ".join(f"{o['lugar']} = {o['personagem']}" for o in ocup)
           + "\nMÓVEIS: " + (", ".join(pr["nome"] + (f" ({pr['prompt_en'][:80]})" if pr.get("prompt_en") else "") for pr in props) or "(nenhum)"))
    sis = "Você mede posições em imagens de anime com precisão. Responda só o JSON."
    r = A._ia().chamar("anime2d", sis, [{"type": "text", "text": txt}, _jpeg(cam, 1280)], schema=SCHEMA_LEITURA,
                       max_tokens=2000, effort="medium", timeout=180, cache_local=False)
    if not isinstance(r, dict):
        raise A.AnimeErro("A IA não respondeu — tente de novo ou ajuste no 📐 Montar o cenário.")
    feitos = []
    with A._TRAVA:
        p = A.carregar(pid, base)
        lo = next((x for x in p["locais"] if x["id"] == lid), None)
        dono = _dono_layout(p, lo)
        lugs = dono.setdefault("lugares", [])
        padrao = A.lugares_do_local(p, A.layout_do_local(p, lo))
        alt0 = float((dono.get("chao") or {}).get("alt") or C.ALT_PADRAO[A.tamanho(p)[0] > A.tamanho(p)[1]])
        for y in r.get("lugares") or []:
            if not isinstance(y, dict) or not y.get("visivel") or y.get("lugar") not in padrao:
                continue
            v = padrao[y["lugar"]]
            fator = C.MEIO_ALT if v.get("corpo") == "cintura" else C.SENTADO_ALT if v.get("sentado") else 1.0
            h = _f(y.get("y1"), 0, 1.2, 0) - _f(y.get("y0"), 0, 1.2, 0)
            if h <= 0.02:
                continue
            lg = next((z for z in lugs if R._norm(z.get("nome")) == R._norm(y["lugar"])), None)
            if lg is None:
                lg = {"nome": y["lugar"], "sentado": bool(v.get("sentado"))}
                if v.get("corpo"):
                    lg["corpo"] = v["corpo"]
                lugs.append(lg)
            lg.update(x=_f(y.get("pes_x"), 0, 1, 0.5), y=_f(y.get("pes_y"), 0.1, 1.1, 0.95),
                      escala=_f(h / max(0.05, alt0 * fator), 0.15, 2.5, 1.0))
            feitos.append(f"📍 {y['lugar']}")
        for y in r.get("moveis") or []:
            pr = next((z for z in dono.get("props") or [] if isinstance(y, dict) and y.get("visivel") and R._norm(z["nome"]) == R._norm(y.get("nome"))), None)
            if not pr:
                continue
            x0, x1 = _f(y.get("x0"), 0, 1, 0.4), _f(y.get("x1"), 0, 1, 0.6)
            if x1 - x0 <= 0.02:
                continue
            pr.update(x=round((x0 + x1) / 2, 4), y=_f(y.get("y1"), 0.1, 1.1, 0.95), w=round(x1 - x0, 4), w_manual=True)
            feitos.append(f"🪑 {pr['nome']}")
        lo.setdefault("story", {})["lido"] = True
        A.log(p, f"📐 storyboard de {lo['nome']} lido: {', '.join(feitos) or 'nada'}")
        A.salvar(p, base)
    return f"{len(feitos)} posição(ões) do storyboard: " + ", ".join(feitos)


# ------------------------------------------------------------------ 🔎 revisão dos quadros
ACOES = ["nenhuma", "lugar", "movel", "plano", "angulo", "corte_reacao", "regerar"]
SCHEMA_REVISAO = {
    "type": "object", "additionalProperties": False, "required": ["quadros"],
    "properties": {"quadros": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["n", "ok", "problemas"],
        "properties": {"n": {"type": "integer"}, "ok": {"type": "boolean"}, "problemas": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["descricao", "acao", "local", "lugar", "movel", "plano", "foco", "angulo", "personagem", "pose_en",
                         "alvo", "pedido", "x", "y", "escala", "w"],
            "properties": {"descricao": {"type": "string"}, "acao": {"type": "string", "enum": ACOES},
                           "local": {"type": "string"}, "lugar": {"type": "string"}, "movel": {"type": "string"},
                           "plano": {"type": "string"}, "foco": {"type": "string"}, "angulo": {"type": "string"},
                           "personagem": {"type": "string"}, "pose_en": {"type": "string"}, "alvo": {"type": "string"},
                           "pedido": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"},
                           "escala": {"type": "number"}, "w": {"type": "number"}}}}}}}}}

SIS_REVISAO = (
    "Você é o REVISOR de um anime 2D montado com recortes (fundo + móveis em camadas + personagens recortados em poses + "
    "destaques em tela cheia). Olhe cada QUADRO (um por corte) e compare com o que ele DEVIA mostrar. Aponte só erros "
    "visíveis e concretos: personagem flutuando ou afundado no chão, tamanho errado pra perspectiva, atravessando um "
    "objeto/móvel, sentado no chão em vez da cadeira, móvel do lado errado ou do tamanho errado, cabeça cortada, quadro "
    "vazio ou que não mostra o que a 👁 visão pede, o mesmo plano parado demais (falta um corte de reação), pose que não "
    "combina com a ação, imagem com defeito (mão deformada, texto escrito indevido, design diferente do personagem).\n"
    "Pra cada problema escolha UMA ação:\n"
    "- 'lugar': mover/escalar um LUGAR do cenário (local, lugar, x = centro, y = onde ficam os pés, escala; frações 0–1 "
    "da tela) — corrige flutuar, afundar, tamanho e atravessar;\n"
    "- 'movel': mover/redimensionar um MÓVEL (local, movel, x = centro, y = a base, w = largura);\n"
    "- 'plano': trocar o plano/foco do corte (plano geral/medio/close/reacao, foco = nome do personagem);\n"
    "- 'angulo': usar outro ÂNGULO do cômodo nesse corte (angulo = o nome de um dos ângulos listados);\n"
    "- 'corte_reacao': inserir logo depois um corte curto de reação (personagem, pose_en em inglês);\n"
    "- 'regerar': a IMAGEM está ruim (alvo = 'pose:<personagem>:<pose>', 'local:<nome>', 'item:<nome>' ou "
    "'movel:<local>:<nome>'; pedido = o que corrigir, em português);\n"
    "- 'nenhuma': só anotar.\n"
    "Campos que não se aplicam: \"\" ou 0. Use os NOMES exatamente como aparecem. Se o quadro está bom: ok=true e "
    "problemas=[]. Não invente problema.")


def _contexto_quadro(p: Dict[str, Any], f: Dict[str, Any], n: int) -> str:
    s = next((x for x in p["cenas"] if x["id"] == f["cena"]), None)
    m = next((x for x in (s or {}).get("momentos") or [] if x["id"] == f["momento"]), None)
    if not s or not m:
        return f"QUADRO {n}: (sem dados)"
    lo = A.local_do_momento(p, s, m)
    lug = A.lugares_do_local(p, A.layout_do_local(p, lo)) if lo else {}
    quem = "; ".join(f"{A.nome_de(p, e['cid'])} em “{e['posicao']}”" + (" [sentado]" if (lug.get(e["posicao"]) or {}).get("sentado") else "")
                     + (f" (x={lug[e['posicao']]['x']:.2f}, y={lug[e['posicao']]['y']:.2f}, escala={float(lug[e['posicao']].get('escala') or 1):.2f})"
                        if e["posicao"] in lug else "") + f", pose {e.get('pose_en') or e.get('pose')}"
                     for e in m.get("em_cena") or [])
    angs = [x["nome"] for x in A.familia_do_local(p, lo) if A.angulo_base(p, x) is not None] if lo else []
    props = (A.layout_do_local(p, lo) or {}).get("props") or [] if lo else []
    return (f"QUADRO {n} — cena “{s['titulo']}”, momento {m['id']} ({m['tipo']}"
            + (f", {A.nome_de(p, m['quem'])}: “{m['texto'][:90]}”" if m.get("texto") else "") + f"), plano {f['plano']}, "
            f"cenário “{(lo or {}).get('nome', '?')}”"
            + (f", ângulos disponíveis: {', '.join(angs)}" if angs else "")
            + (f". Devia mostrar (👁): {m['visao']}" if m.get("visao") else "")
            + (f". Em cena: {quem}" if quem else ". Ninguém em cena")
            + (". Móveis: " + ", ".join(f"{pr['nome']} (x={float(pr.get('x', .5)):.2f}, y={float(pr.get('y', .95)):.2f})" for pr in props) if props else "")
            + (" [destaque em tela cheia]" if m.get("destaque") else "") + ".")


def _aplicar(p: Dict[str, Any], prob: Dict[str, Any], f: Dict[str, Any], novos: List[int], sugestoes: List[str]) -> Optional[str]:
    a = prob.get("acao")
    s = next((x for x in p["cenas"] if x["id"] == f["cena"]), None)
    m = next((x for x in (s or {}).get("momentos") or [] if x["id"] == f["momento"]), None)
    if a == "lugar":
        lo = A.achar(p["locais"], prob.get("local")) or (A.local_do_momento(p, s, m) if s and m else None)
        if not lo:
            return None
        dono = _dono_layout(p, lo)
        lugs = dono.setdefault("lugares", [])
        padrao = A.lugares_do_local(p, A.layout_do_local(p, lo))
        nome = next((k for k in padrao if R._norm(k) == R._norm(prob.get("lugar"))), None)
        if not nome:
            return None
        lg = next((z for z in lugs if R._norm(z.get("nome")) == R._norm(nome)), None)
        if lg is None:
            lg = {"nome": nome, "sentado": bool(padrao[nome].get("sentado"))}
            lugs.append(lg)
        if prob.get("x"):
            lg["x"] = _f(prob["x"], 0, 1, 0.5)
        if prob.get("y"):
            lg["y"] = _f(prob["y"], 0.1, 1.1, 0.95)
        if prob.get("escala"):
            lg["escala"] = _f(prob["escala"], 0.15, 2.5, 1.0)
        return f"📍 {lo['nome']} · {nome}"
    if a == "movel":
        lo = A.achar(p["locais"], prob.get("local")) or (A.local_do_momento(p, s, m) if s and m else None)
        dono = _dono_layout(p, lo) if lo else None
        pr = next((z for z in (dono or {}).get("props") or [] if R._norm(z["nome"]) == R._norm(prob.get("movel"))), None)
        if not pr:
            return None
        if prob.get("x"):
            pr["x"] = _f(prob["x"], 0, 1, 0.5)
        if prob.get("y"):
            pr["y"] = _f(prob["y"], 0.1, 1.1, 0.95)
        if prob.get("w"):
            pr.update(w=_f(prob["w"], 0.03, 1.2, 0.3), w_manual=True)
        return f"🪑 {pr['nome']}"
    if not m:
        return None
    if a == "plano" and prob.get("plano") in A.PLANOS:
        m["plano"] = prob["plano"]
        c = A.achar(p["personagens"], prob.get("foco"))
        if c and c["id"] in [e["cid"] for e in m.get("em_cena") or []]:
            m["foco"] = c["id"]
        return f"🎥 {m['id']} → {prob['plano']}"
    if a == "angulo":
        lo = A.local_da_cena(p, s)
        alvo = next((x for x in A.familia_do_local(p, lo) if R._norm(x["nome"]) == R._norm(prob.get("angulo"))), None)
        if alvo:
            m["angulo"] = "" if alvo is lo else alvo["id"]
            return f"🎥 {m['id']} → {alvo['nome']}"
        return None
    if a == "corte_reacao" and len(novos) < MAX_CORTES_NOVOS:
        c = A.achar(p["personagens"], prob.get("personagem"))
        if not c or c["id"] not in [e["cid"] for e in m.get("em_cena") or []]:
            return None
        em = [dict(e) for e in m.get("em_cena") or []]
        for e in em:
            if e["cid"] == c["id"] and prob.get("pose_en"):
                e.update(pose="outra", pose_en=str(prob["pose_en"])[:200], poses=[])
        novo = {"id": A._id("m"), "tipo": "acao", "quem": "", "texto": f"Reação de {c['nome']}", "pose": "neutro", "pose_en": "",
                "em_cena": em, "camera": "zoom_in", "plano": "close", "foco": c["id"], "fundo_reacao": "", "destaque": "", "objeto": "",
                "duracao": 1.2, "som": "", "tempo": None, "visao": f"close na reação de {c['nome']}", "angulo": m.get("angulo") or ""}
        s["momentos"].insert(s["momentos"].index(m) + 1, novo)
        novos.append(1)
        return f"✂ reação de {c['nome']} depois de {m['id']}"
    if a == "regerar":
        sugestoes.append(f"🔁 {prob.get('alvo') or '?'}: {prob.get('pedido') or prob.get('descricao') or ''}"[:300])
        return None
    return None


def revisar(pid: str, base: str = A._BASE, on_log: Callable[[str], None] = lambda _m: None, rodadas: int = RODADAS) -> str:
    """🔎 Desenha um quadro de cada corte, a IA aponta os erros, as correções entram, e confere de novo."""
    relatorio: Dict[str, Any] = {"quando": time.time(), "rodadas": [], "sugestoes": []}
    d = os.path.join(A.pasta(pid, base), "imagens")
    total = 0
    for rodada in range(1, rodadas + 1):
        p = A.carregar(pid, base)
        pl = C.plano(p, base)
        cortes = [f for f in pl["fundos"] if f["fim"] - f["ini"] > 0.3][:MAX_QUADROS]
        if not cortes:
            raise A.AnimeErro("Sem cortes pra revisar — escreva as cenas antes.")
        quadros = []
        for n, f in enumerate(cortes, 1):
            on_log(f"rodada {rodada}: desenhando o quadro {n} de {len(cortes)}…")
            cam = os.path.join(d, f"_rev_{rodada}_{n:02d}.jpg")
            C.quadro(pl, cam, (f["ini"] + f["fim"]) / 2, legenda=False)
            quadros.append((n, f, cam))
        problemas: List[Dict[str, Any]] = []
        for i in range(0, len(quadros), LOTE):
            lote = quadros[i:i + LOTE]
            on_log(f"rodada {rodada}: a IA olhando os quadros {lote[0][0]}–{lote[-1][0]}…")
            conteudo: List[Dict[str, Any]] = [{"type": "text", "text": f"EPISÓDIO “{p['titulo']}” — {len(lote)} quadro(s):"}]
            for n, f, cam in lote:
                conteudo += [{"type": "text", "text": _contexto_quadro(p, f, n)}, _jpeg(cam)]
            r = A._ia().chamar("anime2d", SIS_REVISAO, conteudo, schema=SCHEMA_REVISAO, max_tokens=4000, effort="medium",
                               timeout=240, cache_local=False)
            for q in (r or {}).get("quadros") or []:
                f = next((x[1] for x in lote if x[0] == q.get("n")), None)
                if f is None:
                    continue
                for prob in q.get("problemas") or []:
                    problemas.append({"n": q["n"], "f": f, "prob": prob, "img": f"_rev_{rodada}_{int(q['n']):02d}.jpg"})
        feitos, novos = [], []
        with A._TRAVA:
            p = A.carregar(pid, base)
            for x in problemas:
                ok = _aplicar(p, x["prob"], x["f"], novos, relatorio["sugestoes"])
                x["feito"] = ok
                if ok:
                    feitos.append(ok)
            if feitos:
                A.log(p, f"🔎 revisão (rodada {rodada}): {len(feitos)} correção(ões)")
            A.salvar(p, base)
        relatorio["rodadas"].append({"n": rodada, "quadros": len(quadros), "problemas": [
            {"quadro": x["n"], "momento": x["f"]["momento"], "img": x["img"], "descricao": str(x["prob"].get("descricao") or "")[:300],
             "acao": x["prob"].get("acao"), "feito": x.get("feito")} for x in problemas]})
        total += len(feitos)
        if not feitos:  # nada mais pra corrigir sozinho
            break
    with A._TRAVA:
        p = A.carregar(pid, base)
        p["revisao"] = relatorio
        A.salvar(p, base)
    n_prob = sum(len(r["problemas"]) for r in relatorio["rodadas"])
    return (f"🔎 {len(relatorio['rodadas'])} rodada(s): {n_prob} problema(s) apontado(s), {total} corrigido(s) sozinho(s)"
            + (f", {len(relatorio['sugestoes'])} imagem(ns) pra regerar (veja a lista)" if relatorio["sugestoes"] else ""))
