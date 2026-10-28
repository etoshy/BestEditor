"""
💡 NICHOS DE CANAIS + IDEIAS DE VÍDEO (v84_256) — os canais de shorts 📚 EXPLICATIVOS que dá pra tocar do zero, 1 vídeo por dia,
com as imagens geradas no Flow (realistas). Sem vídeo-fonte e sem comentário: o foco é a IDEIA.

  1. A lista (assets/curtos/nichos.json): Shape Reason, Wild Trickcraft, Saved By Design, Hidden Origins Daily, Made In Minutes,
     Bite Behind It — cada um com o tema, o público, o tom, exemplos e o que mostrar.
  2. ➕ Criar o canal do nicho: o perfil 📚 Explicativo + o tema do nicho (a marca já vem com o @ do nome).
  3. 💡 Gerar ideias: a IA propõe 10 vídeos novos pro canal (título em inglês + português, o assunto com os fatos, o gancho e o
     que mostrar), sem repetir os que já saíram. Cada ideia vira um vídeo 📚 no Flow com um clique (ou 🚀 já fazendo tudo).
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import curtos as CT

MAX_IDEIAS = 300


def nichos() -> List[Dict[str, Any]]:
    cam = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "curtos", "nichos.json")
    try:
        with open(cam, encoding="utf-8") as f:
            return [n for n in json.load(f).get("nichos") or [] if n.get("chave") and n.get("nome")]
    except (OSError, ValueError):
        return []


def nicho(chave: str) -> Optional[Dict[str, Any]]:
    return next((n for n in nichos() if n["chave"] == chave), None)


def canais_de_nicho(base: str) -> List[Dict[str, Any]]:
    out = []
    for c in CT.listar_canais(base):
        try:
            cc = CT.carregar_canal(base, c["id"])
        except CT.CurtoErro:
            continue
        if cc.get("nicho"):
            ideias = cc.get("ideias") or []
            out.append({"id": cc["id"], "nome": cc["nome"], "nicho": cc["nicho"], "ideias": len(ideias),
                        "marca": CT.normalizar_marca((cc.get("perfil") or {}).get("marca"), cc["nome"]),
                        "livres": sum(1 for i in ideias if not i.get("pid"))})
    return out


def perfil_do_nicho(n: Dict[str, Any]) -> Dict[str, Any]:
    """O perfil 📚 Explicativo pronto + o tema do nicho."""
    base_ = json.loads(json.dumps((CT.perfis_prontos().get("explicativo") or {}).get("perfil") or {}))
    base_["resumo"] = (f"Channel '{n['nome']}' — {n['nicho']}. Audience: {n.get('publico') or ''}. " + (base_.get("resumo") or ""))[:2000]
    base_["tom"] = n.get("tom") or base_.get("tom") or ""
    base_["titulos"] = {"descricao": "short curiosity question or claim about the topic", "exemplos": list(n.get("temas") or [])[:5]}
    base_["gancho"] = dict(base_.get("gancho") or {}, exemplos=list(n.get("temas") or [])[:3])
    base_["estilo_ia"] = "realista"
    base_["nicho"] = {"tema": n["nicho"], "visual": n.get("visual") or "", "hashtags": n.get("hashtags") or []}
    return base_


def criar_canal_do_nicho(base: str, chave: str) -> Dict[str, Any]:
    n = nicho(chave)
    if not n:
        raise CT.CurtoErro("Nicho não encontrado.")
    for c in canais_de_nicho(base):  # já criado: devolve o mesmo
        if c["nicho"] == chave:
            return CT.carregar_canal(base, c["id"])
    c = CT.criar_canal(base, n["nome"], "en")
    c["perfil"] = CT.aplicar_perfil(c["perfil"], perfil_do_nicho(n))
    c["perfil"]["nicho"] = perfil_do_nicho(n)["nicho"]
    c["perfil_ia"] = True
    c["modelo"] = "explicativo"
    c["nicho"] = chave
    c["ideias"] = []
    CT.salvar_canal(base, c)
    return c


IDEIAS_SCHEMA = CT._o({"ideias": {"type": "array", "items": CT._o({
    "titulo_en": CT._s(), "titulo_pt": CT._s(), "gancho_en": CT._s(),
    "tema": CT._s(), "por_que": CT._s(), "visual": CT._s()})}})
IDEIAS_SYS = (
    "You plan daily EXPLAINER / CURIOSITY shorts (YouTube Shorts / TikTok / Reels, 25-55 s, in English) for one channel. Each idea "
    "explains ONE surprising, TRUE, well-documented thing that can be shown visually (every image will be GENERATED realistically, so "
    "it must be filmable: objects, animals, places, processes, historical scenes — no charts, no famous real people). Good ideas: a "
    "clear 'why/how' question, a satisfying answer in 3-5 steps, one detail that surprises. Avoid anything already done (list "
    "below), clickbait lies, medical/financial advice and tragedies. For each idea: 'titulo_en' (the post title, English), "
    "'titulo_pt' (Brazilian Portuguese), 'gancho_en' (the first spoken sentence), 'tema' (in Portuguese: the topic and the key facts "
    "the script must use, 2-4 sentences, only well-established facts), 'por_que' (Portuguese, why it works for this audience, one "
    "sentence) and 'visual' (Portuguese: the 4-6 shots to generate).")


def gerar_ideias(base: str, cid: str, n: int = 10, chamar: Optional[Callable[..., Any]] = None, pedido: str = "") -> List[Dict[str, Any]]:
    c = CT.carregar_canal(base, cid)
    ni = nicho(c.get("nicho") or "") or {}
    ja = [i["titulo_en"] for i in c.get("ideias") or []]
    ja += [p["titulo"] for p in CT.listar(base) if p.get("modelo") == "explicativo"]
    txt = "\n".join([
        f"CHANNEL: {c['nome']} — {ni.get('nicho') or (c['perfil'].get('nicho') or {}).get('tema') or c['perfil'].get('resumo', '')[:300]}",
        f"AUDIENCE: {ni.get('publico') or ''}", f"TONE: {ni.get('tom') or c['perfil'].get('tom') or ''}",
        f"WHAT IT SHOWS: {ni.get('visual') or ''}", "EXAMPLES OF THE KIND OF VIDEO: " + "; ".join(ni.get("temas") or []),
        *( [f"EXTRA REQUEST: {pedido}"] if pedido else []),
        "", f"ALREADY DONE (do not repeat, not even reworded): {'; '.join(ja[-120:]) or '(none)'}",
        "", "Give {N} NEW ideas. Keep 'tema' to 2-3 short sentences and 'visual' to one line."])
    import ia_servico
    r = None
    for k in (max(3, min(20, int(n))), 5):  # resposta cortada (grande demais)? tenta de novo com menos ideias
        kw: Dict[str, Any] = {"schema": IDEIAS_SCHEMA, "max_tokens": 9000, "job": cid, "cache_local": False}
        if chamar is None:
            kw["timeout"] = 180.0
        r = (chamar or ia_servico.chamar)("curtos", IDEIAS_SYS, txt.replace("{N}", str(k)), **kw)
        if r or "cortada" not in CT.motivo_ia():
            break
    if not r:
        raise CT.CurtoErro(CT.motivo_ia())
    vistos = {CT.norm(t) for t in ja}
    novas = []
    for i in r.get("ideias") or []:
        t = str(i.get("titulo_en") or "").strip()
        if not t or CT.norm(t) in vistos:
            continue
        vistos.add(CT.norm(t))
        novas.append({"id": uuid.uuid4().hex[:8], "titulo_en": t[:160], "titulo_pt": str(i.get("titulo_pt") or "")[:160],
                      "gancho_en": str(i.get("gancho_en") or "")[:240], "tema": str(i.get("tema") or "")[:1500],
                      "por_que": str(i.get("por_que") or "")[:300], "visual": str(i.get("visual") or "")[:600],
                      "criada": time.time(), "pid": None})
    with CT._TRAVA:
        c = CT.carregar_canal(base, cid)
        c["ideias"] = (novas + (c.get("ideias") or []))[:MAX_IDEIAS]
        CT.salvar_canal(base, c)
    return novas


def ideias(base: str, cid: str) -> List[Dict[str, Any]]:
    return CT.carregar_canal(base, cid).get("ideias") or []


def video_da_ideia(base: str, cid: str, iid: str, proporcao: str = "9:16", voz: str = "") -> Dict[str, Any]:
    """📚 A ideia vira um vídeo explicativo do canal, com as imagens geradas no Flow (realistas)."""
    with CT._TRAVA:
        c = CT.carregar_canal(base, cid)
        i = next((x for x in c.get("ideias") or [] if x["id"] == iid), None)
        if not i:
            raise CT.CurtoErro("Ideia não encontrada.")
        if i.get("pid"):
            try:
                return CT.carregar(base, i["pid"])
            except CT.CurtoErro:
                pass
        texto = "\n".join(x for x in (i.get("tema"), f"Gancho sugerido: {i['gancho_en']}" if i.get("gancho_en") else "",
                                      f"O que mostrar: {i['visual']}" if i.get("visual") else "") if x)
        p = CT.criar(base, cid, i["titulo_en"], (), texto, modelo="explicativo")
        p["config"].update(midia="flow", so_fontes=False, estilo_ia="realista",
                           proporcao=proporcao if proporcao in CT.PROPORCOES else "9:16")
        if voz:
            p["config"]["voz_tts"] = voz[:120]
        p["comentario"].update(lingua_post="en", idioma="en")
        p["ideia"] = {"canal": cid, "id": iid, "titulo_pt": i.get("titulo_pt") or ""}
        CT.salvar(base, p)
        i["pid"] = p["id"]
        CT.salvar_canal(base, c)
    return p


# ------------------------------------------------------------------ ⚡ geração rápida (v84_258): várias ideias → vídeos exportados
QUALIDADES_RAPIDO = ("1080p", "1440p", "2160p")


def _pasta_lotes(base: str) -> str:
    d = os.path.join(CT.raiz(base), "lotes")
    os.makedirs(d, exist_ok=True)
    return d


def criar_lote(base: str, cid: str, ids: List[str], video: bool = False, qualidade: str = "1080p", proporcao: str = "9:16",
               voz: str = "") -> Dict[str, Any]:
    c = CT.carregar_canal(base, cid)
    todas = {i["id"]: i for i in c.get("ideias") or []}
    ids = [i for i in ids if i in todas]
    if not ids:
        raise CT.CurtoErro("Escolha as ideias (ou gere algumas antes).")
    lote = {"id": uuid.uuid4().hex[:10], "canal": cid, "canal_nome": c["nome"], "criado": time.time(), "fim": None,
            "opcoes": {"video": bool(video), "qualidade": qualidade if qualidade in QUALIDADES_RAPIDO else "1080p",
                       "proporcao": proporcao if proporcao in CT.PROPORCOES else "9:16", "voz": voz[:120]},
            "itens": [{"ideia": i, "titulo_en": todas[i]["titulo_en"], "titulo_pt": todas[i].get("titulo_pt") or "", "pid": None,
                       "estado": "na fila", "msg": "", "erro": None, "arquivo": None, "titulos": []} for i in ids]}
    salvar_lote(base, lote)
    return lote


def salvar_lote(base: str, lote: Dict[str, Any]) -> None:
    with CT._TRAVA:
        cam = os.path.join(_pasta_lotes(base), lote["id"] + ".json")
        with open(cam + ".tmp", "w", encoding="utf-8") as f:
            json.dump(lote, f, ensure_ascii=False, indent=1)
        os.replace(cam + ".tmp", cam)


def carregar_lote(base: str, lid: str) -> Dict[str, Any]:
    if not CT._valido(lid):
        raise CT.CurtoErro("Lote inválido.")
    cam = os.path.join(_pasta_lotes(base), lid + ".json")
    if not os.path.isfile(cam):
        raise CT.CurtoErro("Lote não encontrado.")
    with open(cam, encoding="utf-8") as f:
        return json.load(f)


def lotes_do_canal(base: str, cid: str) -> List[Dict[str, Any]]:
    out = []
    for f in os.listdir(_pasta_lotes(base)):
        if f.endswith(".json"):
            try:
                lt = carregar_lote(base, f[:-5])
            except (CT.CurtoErro, OSError, ValueError):
                continue
            if lt.get("canal") == cid:
                out.append(lt)
    return sorted(out, key=lambda x: -float(x.get("criado") or 0))


def titulos_do_projeto(p: Dict[str, Any]) -> List[Dict[str, str]]:
    r = p.get("roteiro") or {}
    ts = [{"en": t.get("en") or "", "pt": t.get("pt") or ""} for t in r.get("titulos") or []]
    if r.get("titulo_video") and not any(t["en"] == r["titulo_video"] for t in ts):
        ts.insert(0, {"en": r["titulo_video"], "pt": r.get("titulo_pt") or ""})
    return ts[:8]


def texto_dos_titulos(base: str, lote: Dict[str, Any]) -> str:
    """📋 Os títulos de cada vídeo (idioma do post + português), a descrição e as hashtags — pronto pra copiar na postagem."""
    L = [f"{lote.get('canal_nome') or ''} — geração rápida ({time.strftime('%d/%m/%Y %H:%M', time.localtime(lote.get('criado') or 0))})", ""]
    for k, it in enumerate(lote["itens"], 1):
        L.append(f"#{k} {it['titulo_en']}" + ("" if it["estado"] == "pronto" else f"   [{it['estado']}]"))
        try:
            p = CT.carregar(base, it["pid"]) if it.get("pid") else None
        except CT.CurtoErro:
            p = None
        for t in (titulos_do_projeto(p) if p else it.get("titulos") or []):
            L.append(f"   • {t['en']}" + (f"  |  {t['pt']}" if t.get("pt") else ""))
        r = (p or {}).get("roteiro") or {}
        if r.get("descricao"):
            L.append(f"   descrição: {r['descricao']}")
        if r.get("hashtags"):
            L.append("   " + " ".join(r["hashtags"]))
        L.append("")
    return "\n".join(L)
