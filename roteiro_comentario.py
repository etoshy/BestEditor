"""roteiro_comentario.py — ✍ Roteiro de comentário SÓ COM O TEXTO (v84_283).

O jeito do tutorial "turn any clip into a commentary short with Claude": você não precisa subir o vídeo — explica a
história em palavras simples (como contaria pra um amigo) ou cola a transcrição do short, escolhe o TOM (esporte,
engraçado, emocionante…) e sai:

  • o roteiro em 3 partes — GANCHO (abre no momento mais chocante/emocionante), CORPO (conta a história rápido) e FINAL
    (o último momento numa frase forte + uma PERGUNTA que puxa comentário) — no idioma do post + tradução em português;
  • 10 ganchos e 10 perguntas finais pra trocar com um clique (e ➕ mais 10);
  • títulos, descrição e hashtags;
  • "o que a IA entendeu" (pra conferir se a história está certa) e ⚠ o que ela pode ter inventado.

Depois: 📋 copiar, ou 💬 levar pro curto de comentário (o roteiro vai como referência, com o mesmo tamanho e ritmo).
Pasta: <BASE>/roteiros_comentario/<id>.json
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import arquivo_seguro
import curtos as CT

TONS = {
    "auto": "🤖 a IA escolhe pelo clipe",
    "esporte": "🏆 esporte / superação",
    "engracado": "😂 engraçado",
    "emocionante": "🥹 emocionante / fofo",
    "surpreendente": "😱 surpreendente / reviravolta",
    "polemico": "🔥 polêmico (divide opiniões)",
    "suspense": "🕵️ mistério / suspense",
}
_TOM_EN = {
    "auto": "Pick the tone that fits THIS story best (sports, funny, heartwarming, surprising, controversial or suspense) and say which in 'tom'.",
    "esporte": "Tone: SPORTS — energy, tension, the decisive moment, respect for the athletes; short punchy sentences.",
    "engracado": "Tone: FUNNY — playful, light irony, comic timing (setup → punchline), never mean; match the humor of the clip.",
    "emocionante": "Tone: HEARTWARMING — warm, gentle, let the emotional moment breathe; no cheesy exaggeration.",
    "surpreendente": "Tone: SURPRISING — build curiosity, hold the twist, then hit it.",
    "polemico": "Tone: CONTROVERSIAL — present the decision fairly, both sides, and end on the exact point people will argue about.",
    "suspense": "Tone: MYSTERY — slow build, small clues, the reveal at the end.",
}
DURACOES = {0: "🤖 o que a história pede", 15: "~15 s", 20: "~20 s", 30: "~30 s", 45: "~45 s", 60: "~60 s"}
TAGS_VOZ = ("gasp", "laugh", "chuckle", "sigh", "surprised", "sarcastic", "dramatic", "whispering", "happy")

_OP = CT._o({"en": CT._s(), "pt": CT._s()})
SCHEMA = CT._o({
    "entendi_pt": CT._s(), "tom": CT._s(),
    "gancho": _OP, "corpo": _OP, "final": _OP,
    "ganchos": {"type": "array", "items": _OP}, "perguntas": {"type": "array", "items": _OP},
    "titulos": {"type": "array", "items": _OP}, "descricao": CT._s(), "hashtags": CT._ls(),
    "conferir_pt": CT._ls(),
})
MAIS_SCHEMA = CT._o({"opcoes": {"type": "array", "items": _OP}})


class RoteiroErro(Exception):
    pass


def lingua(lp: str) -> str:
    return {"en": "ENGLISH", "pt": "BRAZILIAN PORTUGUESE", "es": "SPANISH", "it": "ITALIAN", "fr": "FRENCH", "de": "GERMAN"}.get(lp, "ENGLISH")


# ---------------------------------------------------------------------------------------------------- arquivos
def raiz(base: str) -> str:
    return os.environ.get("ROTEIROS_COMENTARIO_DIR") or os.path.join(base, "roteiros_comentario")


def _cam(base: str, rid: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{10}", rid or ""):
        raise RoteiroErro("id inválido")
    return os.path.join(raiz(base), rid + ".json")


def carregar(base: str, rid: str) -> Dict[str, Any]:
    cam = _cam(base, rid)
    if not os.path.isfile(cam):
        raise RoteiroErro("roteiro não existe")
    with open(cam, encoding="utf-8") as f:
        return json.load(f)


def salvar(base: str, r: Dict[str, Any]) -> None:
    os.makedirs(raiz(base), exist_ok=True)
    r["mudou"] = time.time()
    arquivo_seguro.gravar_json(_cam(base, r["id"]), r)


def novo(base: str, historia: str, tom: str = "auto", lingua_post: str = "en", duracao: int = 0, tags: bool = True,
         extra: str = "", titulo: str = "") -> Dict[str, Any]:
    historia = str(historia or "").strip()
    if len(historia) < 15:
        raise RoteiroErro("Conte a história (o que acontece no clipe) ou cole a transcrição.")
    r = {"id": uuid.uuid4().hex[:10], "criado": time.time(), "historia": historia[:20000],
         "tom": tom if tom in TONS else "auto", "lingua_post": lingua_post if lingua_post in CT.LINGUAS else "en",
         "duracao": int(duracao) if int(duracao or 0) in DURACOES else 0, "tags": bool(tags), "extra": str(extra or "")[:2000],
         "titulo": (titulo or "").strip()[:90] or " ".join(historia.split()[:8]), "res": None}
    salvar(base, r)
    return r


def listar(base: str) -> List[Dict[str, Any]]:
    d = raiz(base)
    out = []
    for f in os.listdir(d) if os.path.isdir(d) else []:
        if f.endswith(".json"):
            try:
                r = carregar(base, f[:-5])
            except Exception:  # noqa: BLE001
                continue
            m = r.get("minerador") or {}
            out.append({"id": r["id"], "titulo": r.get("titulo"), "tom": r.get("tom"), "pronto": bool(r.get("res")), "mudou": r.get("mudou") or 0,
                        "minerado": bool(m), "nota": m.get("nota"), "modelo": m.get("modelo") or "", "status": r.get("status") or ("novo" if m else "")})
    return sorted(out, key=lambda x: -x["mudou"])


def apagar(base: str, rid: str) -> None:
    cam = _cam(base, rid)
    for c in (cam, cam[:-5] + ".jpg"):
        if os.path.isfile(c):
            os.remove(c)


STATUS = {"novo": "🆕 novo", "usado": "✅ usado", "depois": "⏳ depois", "descartado": "🗑 descartado"}


def marcar(base: str, rid: str, status: str) -> Dict[str, Any]:
    if status not in STATUS:
        raise RoteiroErro("status inválido")
    r = carregar(base, rid)
    r["status"] = status
    salvar(base, r)
    return r


# ---------------------------------------------------------------------------------------------------- prompt
def sistema(r: Dict[str, Any]) -> str:
    L = lingua(r["lingua_post"])
    tags = (f" You may add 1 to 3 voice tags at natural moments, from: {', '.join(f'[{t}]' for t in TAGS_VOZ)} — it will be read "
            "by Chatterbox Turbo; never other brackets." if r["lingua_post"] == "en" and r.get("tags") else " No brackets or tags.")
    return (
        "You write scripts for COMMENTARY SHORTS (YouTube Shorts / TikTok / Reels): a narrator retells and comments a viral clip "
        "while the clip plays. The creator did NOT send the video — only the story in simple words, or the transcript of a short "
        "(it may be messy: [music] marks, song lyrics, the same story told twice — keep only what happens).\n"
        "THE FORMULA:\n"
        "1. GANCHO (hook, 1 sentence): OPEN WITH THE MOST SHOCKING OR EMOTIONAL MOMENT — curiosity, contradiction or a surprising "
        "claim. Under 15 words.\n"
        "2. CORPO (body): REVEAL THE STORY QUICKLY — what happens, in order, the twist; short spoken sentences, one flowing "
        "paragraph, no lists. Add the narrator's own point of view (the commentary) — that is the creative value, not a plain "
        "description.\n"
        "3. FINAL: DELIVER THE FINAL MOMENT IN ONE STRONG LINE, then ONE engaging QUESTION that makes viewers comment — ideally "
        "the point where people have different opinions (e.g. was his decision right?).\n"
        "RULES: only facts the story supports — never invent names, numbers, places or reasons; if something important is "
        "unclear, keep it vague and list it in 'conferir_pt'. Rewrite everything in your own words (never copy the transcript's "
        "sentences). The script must sound natural read aloud.\n"
        f"LANGUAGE: 'en' fields in {L} (the language of the post){tags} 'pt' fields = the same in natural Brazilian Portuguese "
        "(no tags).\n"
        "ALSO: 'ganchos' = 10 alternative hooks (the first = the one you used), 'perguntas' = 10 alternative final lines "
        "(final moment + question; the first = the one you used), 'titulos' = 5 short honest post titles, 'descricao' (short, "
        f"in {L}), 3-6 'hashtags', 'entendi_pt' = 1-3 sentences in Portuguese with the story as you understood it (so the creator "
        "can check it), 'tom' = the tone in Portuguese, 'conferir_pt' = 0-4 short notes in Portuguese about anything the "
        "creator should check before posting (unclear facts, a detail you assumed).")


def conteudo(r: Dict[str, Any]) -> str:
    d = int(r.get("duracao") or 0)
    L = [_TOM_EN.get(r.get("tom") or "auto", _TOM_EN["auto"]),
         f"LENGTH: about {d} seconds of narration ≈ {int(d * 2.6)} words in total (hook + body + final)." if d else
         "LENGTH: what this story needs — usually 15-35 seconds (≈ 40-90 words); a simple clip with one twist is shorter. Never pad.",
         f"POST LANGUAGE: {lingua(r['lingua_post'])}.", "", "## THE STORY / TRANSCRIPT", r["historia"]]
    if r.get("extra"):
        L += ["", "## EXTRA REQUEST FROM THE CREATOR", r["extra"]]
    return "\n".join(L)


def prompt(r: Dict[str, Any]) -> str:
    return (sistema(r) + "\n\n" + conteudo(r) + "\n\nAnswer ONLY with JSON in this format (no ```):\n"
            + json.dumps(CT._exemplo_schema(SCHEMA), ensure_ascii=False, indent=1))


def _op(o: Any) -> Optional[Dict[str, str]]:
    if isinstance(o, str):
        o = {"en": o, "pt": ""}
    if not isinstance(o, dict) or not (o.get("en") or o.get("pt")):
        return None
    return {"en": str(o.get("en") or o.get("pt") or "").strip()[:600], "pt": str(o.get("pt") or "").strip()[:600]}


def ler(resp: Any) -> Dict[str, Any]:
    if isinstance(resp, str):
        import json_ia
        try:
            resp = json_ia.carregar(resp)
        except Exception as exc:  # noqa: BLE001
            raise RoteiroErro(f"Não entendi o JSON: {exc}") from exc
    if not isinstance(resp, dict):
        raise RoteiroErro("A resposta precisa ser um objeto JSON.")
    partes = {k: _op(resp.get(k)) for k in ("gancho", "corpo", "final")}
    if not partes["corpo"] and not partes["gancho"]:
        raise RoteiroErro("A resposta veio sem o roteiro (gancho/corpo/final).")
    out: Dict[str, Any] = {k: v or {"en": "", "pt": ""} for k, v in partes.items()}
    for k, n in (("ganchos", 40), ("perguntas", 40), ("titulos", 20)):
        out[k] = [x for x in (_op(o) for o in resp.get(k) or []) if x][:n]
    for k, parte in (("ganchos", "gancho"), ("perguntas", "final")):  # o que está no roteiro é sempre a 1ª opção
        if out[parte]["en"] and out[parte]["en"] not in [o["en"] for o in out[k]]:
            out[k].insert(0, dict(out[parte]))
    out["descricao"] = str(resp.get("descricao") or "")[:1500]
    out["hashtags"] = [("#" + str(h).lstrip("#").replace(" ", ""))[:40] for h in resp.get("hashtags") or [] if str(h).strip()][:8]
    out["entendi_pt"] = str(resp.get("entendi_pt") or "")[:1200]
    out["tom"] = str(resp.get("tom") or "")[:60]
    out["conferir_pt"] = [str(x)[:300] for x in resp.get("conferir_pt") or [] if str(x).strip()][:6]
    out["escolhido"] = {"ganchos": 0, "perguntas": 0, "titulos": 0}
    return out


def texto(res: Dict[str, Any], lado: str = "en", sem_tags: bool = False) -> str:
    """O roteiro inteiro (gancho + corpo + final) num parágrafo só."""
    t = " ".join(x for x in (res[p].get(lado) or "" for p in ("gancho", "corpo", "final")) if x).strip()
    return CT.sem_tags(t) if sem_tags else t


def segundos(res: Dict[str, Any]) -> float:
    return round(len(texto(res, "en", True).split()) / 2.6, 1)


# ---------------------------------------------------------------------------------------------------- IA
def gerar(base: str, rid: str, chamar: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    r = carregar(base, rid)
    import ia_servico
    resp = (chamar or ia_servico.chamar)("curtos", sistema(r), conteudo(r), schema=SCHEMA, max_tokens=6000,
                                         **({} if chamar else {"timeout": 180.0}), effort="medium", job="rc_" + rid, cache_local=False)
    if not resp:
        raise RoteiroErro(CT.motivo_ia() + " Use o 📋 prompt numa outra IA e cole a resposta.")
    r = carregar(base, rid)
    r["res"] = ler(resp)
    salvar(base, r)
    return r


def colar(base: str, rid: str, resposta: str) -> Dict[str, Any]:
    r = carregar(base, rid)
    r["res"] = ler(resposta)
    salvar(base, r)
    return r


def mais(base: str, rid: str, qual: str, chamar: Optional[Callable[..., Any]] = None) -> List[Dict[str, str]]:
    """➕ mais 10 ganchos / perguntas finais (ou 5 títulos), diferentes dos que já tem."""
    if qual not in ("ganchos", "perguntas", "titulos"):
        raise RoteiroErro("Pedido inválido.")
    r = carregar(base, rid)
    res = r.get("res") or {}
    if not res:
        raise RoteiroErro("Gere o roteiro antes.")
    L = lingua(r["lingua_post"])
    tag = " (may use one voice tag like [gasp])" if r["lingua_post"] == "en" and r.get("tags") and qual != "titulos" else ""
    pedido = {"ganchos": "Write 10 NEW, stronger HOOKS (first sentence; open with the most shocking or emotional moment; under 15 words).",
              "perguntas": "Write 10 NEW FINAL LINES: the final moment in one strong line + ONE question people will argue about in the comments.",
              "titulos": "Write 5 NEW short, honest post TITLES (curiosity, no fake claims)."}[qual]
    ja = "\n".join(f"- {o['en']}" for o in res.get(qual) or [])
    txt = (f"{pedido}\nDifferent from these:\n{ja or '(none)'}\n\nSCRIPT:\n{texto(res, 'en', True)}\n\nSTORY:\n{r['historia'][:3000]}\n\n"
           f"Each with 'en' (in {L}{tag}) and 'pt' (Brazilian Portuguese).")
    import ia_servico
    resp = (chamar or ia_servico.chamar)("curtos", sistema(r), txt, schema=MAIS_SCHEMA, max_tokens=2500, job="rc_" + rid, cache_local=False)
    if not resp:
        raise RoteiroErro(CT.motivo_ia())
    novas = [x for x in (_op(o) for o in resp.get("opcoes") or []) if x]
    r = carregar(base, rid)
    r["res"][qual] = (r["res"].get(qual) or []) + novas
    salvar(base, r)
    return novas


def escolher(base: str, rid: str, qual: str, i: int) -> Dict[str, Any]:
    r = carregar(base, rid)
    res = r.get("res") or {}
    if qual == "angulo":  # 🔀 troca o roteiro inteiro pelo 2º ângulo (o atual vira o 2º)
        b = res.get("angulo_b") or {}
        if not (b.get("corpo") or {}).get("en"):
            raise RoteiroErro("Não tem outro ângulo.")
        atual = {"angulo": res.get("angulo") or "", **{p: dict(res[p]) for p in ("gancho", "corpo", "final")}}
        for p in ("gancho", "corpo", "final"):
            res[p] = dict(b[p])
        res["angulo"], res["angulo_b"] = b.get("angulo") or "", atual
        for k, p in (("ganchos", "gancho"), ("perguntas", "final")):
            if res[p]["en"] not in [o["en"] for o in res.get(k) or []]:
                res.setdefault(k, []).insert(0, dict(res[p]))
            res.setdefault("escolhido", {})[k] = [o["en"] for o in res[k]].index(res[p]["en"])
        salvar(base, r)
        return r
    ops = res.get(qual) or []
    if qual not in ("ganchos", "perguntas", "titulos") or not (0 <= i < len(ops)):
        raise RoteiroErro("Opção não encontrada.")
    if qual != "titulos":
        res["gancho" if qual == "ganchos" else "final"] = dict(ops[i])
    res.setdefault("escolhido", {})[qual] = i
    salvar(base, r)
    return r


def editar(base: str, rid: str, partes: Dict[str, Any]) -> Dict[str, Any]:
    """✏ Você reescreveu uma parte (o tutorial: nunca use o roteiro sem ler e ajustar)."""
    r = carregar(base, rid)
    res = r.get("res")
    if not res:
        raise RoteiroErro("Gere o roteiro antes.")
    for p in ("gancho", "corpo", "final"):
        for lado in ("en", "pt"):
            v = ((partes.get(p) or {}) if isinstance(partes.get(p), dict) else {}).get(lado)
            if isinstance(v, str):
                res[p][lado] = v.strip()[:3000]
    salvar(base, r)
    return r


# ---------------------------------------------------------------------------------------------------- ⛏ minerador
MODELOS_MINERADOR = {
    "comentario": "💬 comentário", "explicativo": "📚 explicativo", "noticia": "📰 notícia",
    "explicador_poker": "🃏 explicador de poker", "documentario": "🎞 documentário", "descartar": "🗑 descartar",
}
_TOM_DE = {"engracado": "engracado", "engraçado": "engracado", "funny": "engracado", "emocionante": "emocionante", "fofo": "emocionante",
           "heartwarming": "emocionante", "esporte": "esporte", "sports": "esporte", "surpreendente": "surpreendente", "chocante": "surpreendente",
           "polemico": "polemico", "polêmico": "polemico", "suspense": "suspense", "tenso": "suspense", "curioso": "surpreendente"}


def _tom_de(t: str) -> str:
    t = str(t or "").lower()
    return next((v for k, v in _TOM_DE.items() if k in t), "auto")


def importar(base: str, item: Dict[str, Any]) -> Dict[str, Any]:
    """📥 Um vídeo aprovado pelo minerador.py vira um roteiro aqui (com o link, os números, o momento forte, os comentários
    úteis, o 2º ângulo e o plano de edição). O mesmo link de novo atualiza o que já existe."""
    if not isinstance(item, dict) or not isinstance(item.get("res"), dict):
        raise RoteiroErro("item do minerador sem roteiro")
    res = ler(item["res"])
    bruto = item["res"]
    b = bruto.get("angulo_b") or {}
    res["angulo"] = str(bruto.get("angulo") or "")[:80]
    res["angulo_b"] = {"angulo": str(b.get("angulo") or "")[:80], **{p: (_op(b.get(p)) or {"en": "", "pt": ""}) for p in ("gancho", "corpo", "final")}}
    coms = [c for c in item.get("comentarios") or [] if isinstance(c, dict)]
    uteis = []
    for cr in bruto.get("comentarios_relevantes") or []:
        try:
            c = coms[int(cr.get("indice"))]
        except (TypeError, ValueError, IndexError):
            continue
        uteis.append({"tipo": str(cr.get("tipo") or ""), "uso": str(cr.get("uso") or "")[:300], "texto": str(c.get("texto") or "")[:400],
                      "curtidas": c.get("curtidas"), "respostas": c.get("respostas", 0), "usuario": c.get("usuario") or ""})
    m = {k: item.get(k) for k in ("link", "autor", "autor_href", "modelo", "nota", "motivo", "nicho", "duracao_s", "metricas", "razoes",
                                  "momento_forte", "coletado_em")}
    m["modelo"] = m["modelo"] if m.get("modelo") in MODELOS_MINERADOR else "comentario"
    m.update({k: bruto.get(k) for k in ("reviravolta", "detalhe_escondido", "discussao_principal", "plano_edicao",
                                        "assunto_explicativo", "ideia_longa", "alertas")})
    m["comentarios_uteis"] = uteis
    m["perguntas_publico"] = [c["texto"] for c in coms if c.get("pergunta")][:8]
    link = str(m.get("link") or "")
    existente = next((x for x in listar(base) if link and (carregar(base, x["id"]).get("minerador") or {}).get("link") == link), None)
    historia = str(item.get("historia") or res.get("entendi_pt") or "").strip() or "(do minerador)"
    if existente:
        r = carregar(base, existente["id"])
    else:
        r = novo(base, historia if len(historia) >= 15 else historia + " — vídeo minerado do TikTok.",
                 _tom_de(res.get("tom")), item.get("lingua_post") or "en", 0, True, "", str(item.get("titulo") or "")[:90])
    m["video_id"] = str(item.get("video_id") or "")[:40]
    mini = str(item.get("miniatura") or "")
    if ";" in mini:  # "image/jpeg;<base64>" → <id>.jpg do lado do json
        import base64
        try:
            dados = base64.b64decode(mini.split(";", 1)[1])
            if len(dados) < 600_000:
                with open(os.path.join(raiz(base), r["id"] + ".jpg"), "wb") as fm:
                    fm.write(dados)
                m["miniatura"] = True
        except (ValueError, OSError):
            pass
    elif (r.get("minerador") or {}).get("miniatura"):
        m["miniatura"] = True
    r.setdefault("status", "novo")
    r.update(res=res, minerador=m, historia=historia[:20000])
    if m.get("discussao_principal") or m["perguntas_publico"]:
        r["extra"] = ("People in the comments argue about: " + str(m.get("discussao_principal") or "")
                      + (" | They ask: " + " / ".join(m["perguntas_publico"][:4]) if m["perguntas_publico"] else ""))[:2000]
    salvar(base, r)
    return r


def importar_texto(base: str, texto: str) -> Dict[str, Any]:
    """aprovados.jsonl / pendentes_site.jsonl (uma linha por vídeo) ou um JSON {itens:[…]} / […]."""
    texto = str(texto or "").strip()
    itens: List[Any] = []
    try:
        j = json.loads(texto)
        itens = j.get("itens") if isinstance(j, dict) and "itens" in j else (j if isinstance(j, list) else [j])
    except ValueError:
        for linha in texto.splitlines():
            if linha.strip():
                try:
                    itens.append(json.loads(linha))
                except ValueError:
                    pass
    feitos, erros = [], []
    for it in itens:
        if isinstance(it, dict) and "triagem" in it and "roteiro" in it and "res" not in it:  # linha do aprovados.jsonl
            d, t = it.get("video") or {}, it["triagem"]
            it = {"link": d.get("link"), "autor": d.get("autor_nome"), "autor_href": d.get("autor_href"), "modelo": t.get("modelo"),
                  "nota": t.get("nota"), "motivo": t.get("motivo"), "nicho": t.get("nicho"), "duracao_s": d.get("duracao_s"),
                  "metricas": {k: d.get(k) for k in ("curtidas", "comentarios", "salvos", "compartilh")}, "razoes": d.get("razoes"),
                  "momento_forte": t.get("momento_forte"), "historia": t.get("resumo_historia"), "comentarios": it.get("comentarios"),
                  "res": it["roteiro"], "titulo": ((it["roteiro"].get("titulos") or [{}])[0] or {}).get("pt") or "",
                  "coletado_em": d.get("coletado_em")}
        try:
            feitos.append(importar(base, it)["id"])
        except RoteiroErro as exc:
            erros.append(str(exc))
    return {"importados": feitos, "erros": erros}


def destino(r: Dict[str, Any]) -> Dict[str, str]:
    """Pra onde o 💬 levar manda, pelo modelo que o minerador escolheu."""
    mod = (r.get("minerador") or {}).get("modelo") or "comentario"
    if mod == "explicativo":
        return {"url": f"/curtos/modelo/explicativo?roteiro={r['id']}#novo-explicativo", "rotulo": "📚 levar pro curto explicativo"}
    if mod == "explicador_poker":
        return {"url": "/explicador", "rotulo": "🃏 abrir o Explicador animado (use a história como base)"}
    return {"url": f"/curtos/modelo/comentario?roteiro={r['id']}#novo-comentario", "rotulo": "💬 levar pro curto de comentário"}


def configurar(base: str, rid: str, d: Dict[str, Any]) -> Dict[str, Any]:
    r = carregar(base, rid)
    if str(d.get("historia") or "").strip():
        r["historia"] = str(d["historia"]).strip()[:20000]
    if d.get("tom") in TONS:
        r["tom"] = d["tom"]
    if d.get("lingua_post") in CT.LINGUAS:
        r["lingua_post"] = d["lingua_post"]
    try:
        if int(d.get("duracao", -1)) in DURACOES:
            r["duracao"] = int(d["duracao"])
    except (TypeError, ValueError):
        pass
    if "tags" in d:
        r["tags"] = bool(d["tags"])
    if "extra" in d:
        r["extra"] = str(d.get("extra") or "")[:2000]
    if str(d.get("titulo") or "").strip():
        r["titulo"] = str(d["titulo"]).strip()[:90]
    salvar(base, r)
    return r


# ---------------------------------------------------------------------------------------------------- rotas
def registrar(app, base: str) -> None:
    from flask import Response, abort, jsonify, redirect, render_template, request

    def _r(rid: str) -> Dict[str, Any]:
        try:
            return carregar(base, rid)
        except RoteiroErro:
            abort(404)

    def _ok(r: Dict[str, Any], **kw: Any):
        res = r.get("res")
        extra = {"texto_en": texto(res, "en"), "texto_pt": texto(res, "pt"), "segundos": segundos(res)} if res else {}
        return jsonify(dict(ok=True, r=r, destino=destino(r), modelos=MODELOS_MINERADOR, **extra, **kw))

    def _erro(msg: Any, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _pagina(r: Optional[Dict[str, Any]]):
        try:
            import ia_servico
            ia = ia_servico.motivo_desligado("curtos") is None
        except Exception:  # noqa: BLE001
            ia = False
        return render_template("roteiro_comentario.html", r=r, lista=listar(base), tons=TONS, duracoes=DURACOES, modelos=MODELOS_MINERADOR,
                               linguas=CT.LINGUAS, ia=ia, erro=request.args.get("erro"))

    @app.route("/curtos/roteiro-comentario")
    def rc_lista():
        return _pagina(None)

    @app.route("/curtos/roteiro-comentario/importar", methods=["POST"])
    def rc_importar():
        """⛏ o minerador.py manda JSON {itens:[…]}; a página manda o arquivo aprovados.jsonl."""
        arq = request.files.get("arquivo")
        if arq and arq.filename:
            r = importar_texto(base, arq.read().decode("utf-8", "replace"))
            n = len(r["importados"])
            return redirect("/curtos/roteiro-comentario?erro=" + (f"📥 {n} vídeo(s) do minerador importado(s)" if n else
                                                                 "Nada importado: " + "; ".join(r["erros"][:3])))
        j = request.get_json(silent=True)
        if j is None:
            return _erro("mande JSON {itens:[…]} ou o arquivo")
        r = importar_texto(base, json.dumps(j))
        return jsonify(dict(ok=bool(r["importados"]) or not r["erros"], **r))

    @app.route("/curtos/roteiro-comentario/<rid>")
    def rc_ver(rid: str):
        return _pagina(_r(rid))

    @app.route("/curtos/roteiro-comentario/novo", methods=["POST"])
    def rc_novo():
        f = request.form
        try:
            r = novo(base, f.get("historia") or "", f.get("tom") or "auto", f.get("lingua_post") or "en", int(f.get("duracao") or 0),
                     bool(f.get("tags")), f.get("extra") or "", f.get("titulo") or "")
        except (RoteiroErro, ValueError) as exc:
            return redirect(f"/curtos/roteiro-comentario?erro={exc}")
        return redirect(f"/curtos/roteiro-comentario/{r['id']}?gerar=1")

    @app.route("/curtos/roteiro-comentario/<rid>/estado")
    def rc_estado(rid: str):
        return _ok(_r(rid))

    @app.route("/curtos/roteiro-comentario/<rid>/config", methods=["POST"])
    def rc_config(rid: str):
        _r(rid)
        return _ok(configurar(base, rid, request.get_json(silent=True) or {}))

    @app.route("/curtos/roteiro-comentario/<rid>/gerar", methods=["POST"])
    def rc_gerar(rid: str):
        _r(rid)
        d = request.get_json(silent=True) or {}
        if d:
            configurar(base, rid, d)
        try:
            return _ok(gerar(base, rid))
        except RoteiroErro as exc:
            return _erro(exc)

    @app.route("/curtos/roteiro-comentario/<rid>/prompt")
    def rc_prompt(rid: str):
        return Response(prompt(_r(rid)), mimetype="text/plain; charset=utf-8")

    @app.route("/curtos/roteiro-comentario/<rid>/colar", methods=["POST"])
    def rc_colar(rid: str):
        _r(rid)
        try:
            return _ok(colar(base, rid, (request.get_json(silent=True) or {}).get("resposta") or ""))
        except RoteiroErro as exc:
            return _erro(exc)

    @app.route("/curtos/roteiro-comentario/<rid>/mais", methods=["POST"])
    def rc_mais(rid: str):
        _r(rid)
        try:
            novas = mais(base, rid, (request.get_json(silent=True) or {}).get("qual") or "")
            return _ok(carregar(base, rid), novas=len(novas))
        except RoteiroErro as exc:
            return _erro(exc)

    @app.route("/curtos/roteiro-comentario/<rid>/escolher", methods=["POST"])
    def rc_escolher(rid: str):
        _r(rid)
        d = request.get_json(silent=True) or {}
        try:
            return _ok(escolher(base, rid, d.get("qual") or "", int(d.get("i", -1))))
        except (RoteiroErro, ValueError) as exc:
            return _erro(exc)

    @app.route("/curtos/roteiro-comentario/<rid>/editar", methods=["POST"])
    def rc_editar(rid: str):
        _r(rid)
        try:
            return _ok(editar(base, rid, request.get_json(silent=True) or {}))
        except RoteiroErro as exc:
            return _erro(exc)

    @app.route("/curtos/roteiro-comentario/<rid>/apagar", methods=["POST"])
    def rc_apagar(rid: str):
        _r(rid)
        apagar(base, rid)
        return redirect("/curtos/roteiro-comentario")
