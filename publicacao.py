"""
📣 publicacao.py — a aba "Publicação" do Estúdio (v84_229)
=========================================================

Tudo o que vai junto com o vídeo no YouTube, no IDIOMA do vídeo, a partir da narração (e do projeto/canal ligado):
  • títulos, descrições, tags e #hashtags — cada um com "➕ mais alternativas" (a IA traz opções NOVAS, sem repetir);
  • capas (thumbnails):
      - ideias da IA (cena + 2-4 palavras grandes), com a personagem do canal quando combina;
      - 📤 uma capa de REFERÊNCIA que você envia (de outro canal, por exemplo): a IA olha a imagem e escreve a mesma
        composição/fundo/clima — a pessoa que aparece vira a NOSSA personagem, o texto vira o NOSSO idioma;
      - 🎨 Gerar no Flow: vai pra fila do 🚀 Flow em massa (só no clique). A imagem vem SEM letras (o Flow erra letra)
        e o site põe o texto por cima (thumbs_flow.compor) → 1280×720 pronta pra subir.
🗂 v84_230: fica em publicacoes/<id do vídeo>/ (publicacao.json, ctx.json, refs/, capas/) — FORA do projeto: apagar o
projeto não apaga a publicação. O ctx.json guarda a narração, o roteiro, o idioma, o canal e as personagens do vídeo; com
o projeto apagado, a página 📣 Publicações continua gerando com ele.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

_TRAVA = threading.RLock()
TIPOS_TEXTO = ("titulos", "descricoes", "tags", "hashtags")
QUANTOS = {"titulos": 8, "descricoes": 2, "tags": 20, "hashtags": 8}


class PubErro(Exception):
    pass


# ------------------------------------------------------------------ guardar
RAIZ = "publicacoes"


def pasta(pdir: str) -> str:
    """A pasta da publicação (pdir já é ela — publicacoes/<id>)."""
    return pdir


def pdir_de(base: str, pid: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{3,80}", str(pid or "")):
        raise PubErro("Publicação inválida.")
    return os.path.join(base, RAIZ, pid)


def migrar(job_dir: str, pdir: str) -> None:
    """v84_229 guardava dentro do projeto (jobs/<id>/publicacao): copia pra pasta nova uma vez."""
    velha = os.path.join(job_dir, "publicacao")
    if os.path.isfile(os.path.join(velha, "publicacao.json")) and not os.path.isfile(os.path.join(pdir, "publicacao.json")):
        try:
            shutil.copytree(velha, pdir, dirs_exist_ok=True)
            d = json.load(open(os.path.join(pdir, "publicacao.json"), encoding="utf-8"))
            for c in d.get("capas") or []:  # os caminhos apontavam pra pasta velha
                for k in ("imagem", "final", "ref"):
                    if c.get(k):
                        c[k] = c[k].replace(velha, pdir)
                c["versoes"] = [v.replace(velha, pdir) for v in c.get("versoes") or []]
            salvar(pdir, d)
        except (OSError, ValueError):
            pass


def salvar_ctx(pdir: str, ctx: Dict[str, Any], meta: Dict[str, Any]) -> None:
    os.makedirs(pdir, exist_ok=True)
    antigo = carregar_ctx(pdir)
    d = {"ctx": ctx, "meta": dict(antigo.get("meta") or {}, **meta, atualizado=time.time())}
    d["meta"].setdefault("criado", time.time())
    with open(os.path.join(pdir, "ctx.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def carregar_ctx(pdir: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(pdir, "ctx.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def listar(base: str) -> List[Dict[str, Any]]:
    """🗂 O histórico: todas as publicações (com o projeto ainda existindo ou não)."""
    raiz = os.path.join(base, RAIZ)
    out = []
    try:
        nomes = os.listdir(raiz)
    except OSError:
        return []
    for pid in nomes:
        pdir = os.path.join(raiz, pid)
        cx = carregar_ctx(pdir)
        if not cx and not os.path.isfile(os.path.join(pdir, "publicacao.json")):
            continue
        d = carregar(pdir)
        meta, ctx = cx.get("meta") or {}, cx.get("ctx") or {}
        capa = next((c for c in reversed(d["capas"]) if c.get("final") and os.path.isfile(c["final"])), None)
        out.append({"id": pid, "titulo": meta.get("titulo") or ((d["textos"].get("titulos") or [""])[0]) or pid,
                    "idioma": (ctx.get("idioma") or {}).get("nome") or "", "canal": ctx.get("canal") or "",
                    "titulos": len(d["textos"].get("titulos") or []), "capas": len(d["capas"]),
                    "capa": f"/publicacoes/{pid}/api/capa/{capa['n']}/final" if capa else "",
                    "atualizado": meta.get("atualizado") or os.path.getmtime(pdir), "tem_projeto": bool(meta.get("tem_projeto"))})
    return sorted(out, key=lambda x: -float(x["atualizado"] or 0))


def carregar(job_dir: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(pasta(job_dir), "publicacao.json"), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("textos", {})
            d.setdefault("capas", [])
            return d
    except (OSError, ValueError):
        pass
    return {"textos": {}, "capas": []}


def salvar(job_dir: str, d: Dict[str, Any]) -> None:
    os.makedirs(pasta(job_dir), exist_ok=True)
    cam = os.path.join(pasta(job_dir), "publicacao.json")
    tmp = cam + f".{secrets.token_hex(3)}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, cam)


# ------------------------------------------------------------------ contexto do vídeo
def idioma_do_job(job: Dict[str, Any]) -> Dict[str, str]:
    cod = str(job.get("language") or job.get("idioma") or "pt")[:5]
    try:
        import idiomas
        cod = idiomas.normalizar(cod) or cod
        nome = idiomas.nome_para_prompt(cod)
    except Exception:  # noqa: BLE001
        nome = cod
    return {"codigo": cod, "nome": nome}


def texto_da_narracao(palavras: List[Dict[str, Any]], limite: int = 14000) -> str:
    t = " ".join(str(w.get("word") or w.get("text") or "").strip() for w in palavras or [])
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limite:  # vídeo longo: começo, meio e fim
        k = limite // 3
        t = t[:k] + " […] " + t[len(t) // 2 - k // 2: len(t) // 2 + k // 2] + " […] " + t[-k:]
    return t


def personagens(job: Dict[str, Any], base: str) -> List[Dict[str, Any]]:
    """As personagens do canal do vídeo: slug, nome, descrição visual (inglês) e a imagem de referência (pose aprovada)."""
    try:
        import marca_visual as mv
        import personagens_editor as PE
        canal = PE.canal_do_job(job, base)
        if not canal:
            return []
        m = mv.carregar(base, canal)
        try:
            with open(os.path.join(m["dir"], "personagens.json"), encoding="utf-8") as f:
                pj = json.load(f) or {}
        except (OSError, ValueError):
            pj = {}
        info = {PE._slug(p.get("slug") or p.get("nome")): p for p in pj.get("personagens") or [] if isinstance(p, dict)}
        out = []
        for p in PE.personagens_do_canal(base, canal):
            poses = [o for o in p.get("poses") or [] if not o.get("visual")]
            ref = next((o["caminho"] for o in poses if o.get("mestre")), None) or (poses[0]["caminho"] if poses else None)
            x = info.get(p["slug"]) or {}
            out.append({"slug": p["slug"], "nome": p["nome"], "visual_en": str(x.get("visual_en") or "")[:700],
                        "personalidade": ", ".join(x.get("personalidade") or [])[:200], "ref": ref})
        return out
    except Exception:  # noqa: BLE001
        return []


def contexto(job: Dict[str, Any], base: str, palavras: List[Dict[str, Any]],
             projeto: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    idi = idioma_do_job(job)
    canal_nome = ""
    try:
        import marca_visual as mv
        import personagens_editor as PE
        c = PE.canal_do_job(job, base)
        if c:
            g = mv.carregar(base, c).get("guia") or {}
            canal_nome = str((g.get("project") or {}).get("name") or c)
    except Exception:  # noqa: BLE001
        pass
    return {"idioma": idi, "narracao": texto_da_narracao(palavras), "canal": canal_nome,
            "personagens": personagens(job, base), "projeto": projeto or {},
            "duracao": float(job.get("total_duration") or 0)}


# ------------------------------------------------------------------ 📝 títulos, descrições, tags, hashtags
_SISTEMA_TEXTOS = (
    "Você é um estrategista de YouTube. Escreve, no IDIOMA DO VÍDEO (nunca em outro), o que acompanha o vídeo na publicação: "
    "títulos que dão clique sem enganar (curiosidade + promessa concreta, até ~70 caracteres, sem caixa alta inteira, sem "
    "emoji em excesso), descrições (2-3 frases de gancho no começo, depois um resumo do que o vídeo mostra, sem inventar fatos "
    "que não estão na narração, e um convite a se inscrever no canal), tags (palavras e expressões de busca reais, do "
    "específico ao amplo, sem #) e hashtags (com #, curtas, as 3 primeiras são as que aparecem acima do título). Tudo baseado "
    "na narração; nada de promessas que o vídeo não cumpre.")


def _bloco_contexto(ctx: Dict[str, Any]) -> str:
    L = [f"IDIOMA DO VÍDEO: {ctx['idioma']['nome']} — escreva TUDO nesse idioma."]
    if ctx.get("canal"):
        L.append(f"Canal: {ctx['canal']}")
    if ctx.get("duracao"):
        L.append(f"Duração: ~{round(ctx['duracao'] / 60)} min")
    pr = ctx.get("projeto") or {}
    if pr.get("titulos"):
        L.append("Títulos que o roteiro sugeriu (referência): " + " | ".join(pr["titulos"][:6]))
    if pr.get("tema"):
        L.append(f"Tema: {pr['tema']}")
    if ctx.get("personagens"):
        L.append("Personagens do canal: " + "; ".join(f"{p['nome']} ({p['personalidade']})" for p in ctx["personagens"]))
    if ctx.get("estilo_canal"):
        L += ["", bloco_estilo_canal(ctx["estilo_canal"])]
    L += ["", "NARRAÇÃO DO VÍDEO:", ctx.get("narracao") or "(sem narração transcrita)"]
    return "\n".join(L)


# ------------------------------------------------------------------ 📊 v84_235: modelar no estilo de um canal analisado
def canais_analisados(base: str) -> List[Dict[str, Any]]:
    """Os canais do 📊 Analisador de canal que já têm vídeos coletados."""
    import analisador_canal as ac
    try:
        return [{"id": a["id"], "nome": a.get("nome") or a.get("url") or a["id"], "n_videos": a.get("n_videos") or 0,
                 "tem_ia": a.get("tem_ia"), "inscritos": a.get("inscritos") or ""}
                for a in ac.listar(base) if a.get("n_videos")]
    except OSError:
        return []


def estilo_canal(base: str, aid: str) -> Optional[Dict[str, Any]]:
    """O que serve pra modelar: os títulos que mais deram view, as fórmulas e a receita de thumb da análise da IA, e
    as thumbs do canal (mais vistas primeiro)."""
    import analisador_canal as ac
    try:
        a = ac.carregar(base, aid)
    except Exception:  # noqa: BLE001
        return None
    vs = [dict(v, id=k) for k, v in (a.get("videos") or {}).items() if v.get("titulo")]
    vs.sort(key=lambda v: -(v.get("views") or 0))
    ia = a.get("ia") or {}
    tt, th = ia.get("titulos") or {}, ia.get("thumbs") or {}
    return {"id": aid, "nome": (a.get("canal") or {}).get("nome") or a.get("url") or aid,
            "titulos_top": [{"titulo": v["titulo"], "views": v.get("views")} for v in vs[:15]],
            "formulas": [{"formula": f.get("formula"), "desempenho": f.get("desempenho")} for f in (tt.get("formulas") or [])[:6]],
            "titulos_funcionam": (tt.get("funcionam") or [])[:6], "titulos_nao": (tt.get("nao_funcionam") or [])[:4],
            "thumbs_estilo": th.get("estilo") or "", "thumbs_receita": th.get("receita") or "",
            "thumbs_funcionam": (th.get("funcionam") or [])[:6], "tem_ia": bool(ia),
            "thumbs": [{"id": v["id"], "titulo": v["titulo"], "views": v.get("views"), "views_txt": ac.fmt_num(v.get("views")) if v.get("views") else (v.get("views_text") or ""),
                        "thumb": v.get("thumb") or f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg"} for v in vs[:30]]}


def bloco_estilo_canal(e: Dict[str, Any]) -> str:
    """O bloco que entra em TODOS os pedidos à IA da Publicação quando um canal está escolhido pra modelar."""
    L = [f"MODELE NO ESTILO DO CANAL “{e['nome']}” (um canal que funciona — copie o JEITO, nunca o título/capa em si):"]
    if e.get("titulos_top"):
        L.append("Títulos que mais deram view (estrutura, tamanho, palavras-gatilho, pontuação, emoção, CAIXA ALTA): " + " | ".join(
            f"{t['titulo']}" + (f" ({ac_fmt(t['views'])} views)" if t.get("views") else "") for t in e["titulos_top"][:12]))
    if e.get("formulas"):
        L.append("Fórmulas de título do canal: " + " | ".join(f"{f['formula']}" + (f" — {f['desempenho']}" if f.get("desempenho") else "")
                                                       for f in e["formulas"] if f.get("formula")))
    if e.get("titulos_funcionam"):
        L.append("Nos títulos funciona: " + "; ".join(e["titulos_funcionam"]))
    if e.get("titulos_nao"):
        L.append("Nos títulos NÃO funciona: " + "; ".join(e["titulos_nao"]))
    if e.get("thumbs_estilo") or e.get("thumbs_receita"):
        L.append(f"Estilo das capas do canal: {e.get('thumbs_estilo') or ''} RECEITA de capa: {e.get('thumbs_receita') or ''}".strip())
    if e.get("thumbs_funcionam"):
        L.append("Nas capas funciona: " + "; ".join(e["thumbs_funcionam"]))
    L.append("Adapte tudo pro IDIOMA e pro assunto do NOSSO vídeo.")
    return "\n".join(L)


def ac_fmt(n: Any) -> str:
    try:
        import analisador_canal as ac
        return ac.fmt_num(n)
    except Exception:  # noqa: BLE001
        return str(n)


def baixar_thumb_canal(job_dir: str, base: str, aid: str, vid: str, baixar: Optional[Callable[[str], bytes]] = None) -> str:
    """A thumb do vídeo do canal analisado (maior resolução que tiver) → arquivo em refs/ (pra copiar o modelo)."""
    e = estilo_canal(base, aid) or {}
    v = next((t for t in e.get("thumbs") or [] if t["id"] == vid), None)
    if not v:
        raise PubErro("Esse vídeo não está na análise do canal.")
    if baixar is None:
        def baixar(url: str) -> bytes:
            import urllib.request
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
                return r.read()
    for url in (f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg", f"https://i.ytimg.com/vi/{vid}/sddefault.jpg", v["thumb"]):
        try:
            dados = baixar(url)
        except Exception:  # noqa: BLE001
            continue
        if dados and len(dados) > 2000:
            return guardar_ref(job_dir, f"{vid}.jpg", dados)
    raise PubErro("Não consegui baixar a thumb desse vídeo (sem internet?).")


def gerar_textos(job_dir: str, ctx: Dict[str, Any], tipos: Optional[List[str]] = None, mais: bool = False,
                 pedido: str = "", job_id: Optional[str] = None) -> Dict[str, Any]:
    """🤖 Gera (ou acrescenta alternativas a) títulos/descrições/tags/hashtags. `mais` = opções NOVAS, sem repetir."""
    import ia_servico
    from ia_midia import _S, _lista, _obj
    tipos = [t for t in (tipos or list(TIPOS_TEXTO)) if t in TIPOS_TEXTO] or list(TIPOS_TEXTO)
    motivo = ia_servico.motivo_desligado("roteiros")
    if motivo:
        raise PubErro(f"IA: {motivo} (ligue em 🤖 IA → 📝 Roteiros direto na IA)")
    with _TRAVA:
        d = carregar(job_dir)
    atuais = d["textos"]
    pedir = []
    for t in tipos:
        n = QUANTOS[t]
        pedir.append(f"- \"{t}\": {n} {'NOVAS opções, diferentes de todas as que já existem' if mais else 'opções'}")
    ja = ""
    if mais:
        ja = "\n\nJÁ EXISTEM (NÃO repita nem reescreva quase igual — traga ângulos novos):\n" + "\n".join(
            f"{t}: " + " | ".join(str(x)[:160] for x in atuais.get(t) or []) for t in tipos if atuais.get(t))
    conteudo = (_bloco_contexto(ctx) + "\n\nPEÇO:\n" + "\n".join(pedir) + ja
                + (f"\n\nPEDIDO EXTRA (siga): {pedido.strip()[:800]}" if pedido.strip() else ""))
    schema = _obj({t: _lista(_S) for t in tipos})
    r = ia_servico.chamar("roteiros", _SISTEMA_TEXTOS, conteudo, schema=schema, max_tokens=4000, effort="medium",
                          job=job_id, cache_local=False, timeout=240)
    if not isinstance(r, dict):
        raise PubErro("A IA não respondeu (veja em 🤖 IA).")
    with _TRAVA:
        d = carregar(job_dir)
        for t in tipos:
            novos = [re.sub(r"\s+", " ", str(x)).strip() if t != "descricoes" else str(x).strip()
                     for x in r.get(t) or [] if str(x).strip()]
            if t == "tags":
                novos = [x.lstrip("#").strip() for x in novos]
            if t == "hashtags":
                novos = ["#" + re.sub(r"[^\w]", "", x.lstrip("#"), flags=re.UNICODE) for x in novos]
                novos = [x for x in novos if len(x) > 1]
            antes = d["textos"].get(t) or [] if mais else []
            vistos = {x.lower() for x in antes}
            d["textos"][t] = antes + [x for x in novos if x.lower() not in vistos and not vistos.add(x.lower())]
        d["idioma"] = ctx["idioma"]
        d["gerado_em"] = time.time()
        salvar(job_dir, d)
    return d


def editar_texto(job_dir: str, tipo: str, idx: int, valor: Optional[str]) -> Dict[str, Any]:
    """Edita (ou apaga, com valor None) uma opção."""
    if tipo not in TIPOS_TEXTO:
        raise PubErro("Tipo inválido.")
    with _TRAVA:
        d = carregar(job_dir)
        lista = d["textos"].setdefault(tipo, [])
        if not 0 <= idx < len(lista):
            raise PubErro("Opção não encontrada.")
        if valor is None:
            lista.pop(idx)
        else:
            lista[idx] = str(valor)[:5000]
        salvar(job_dir, d)
    return d


# ------------------------------------------------------------------ 🖼 capas
ESTILO_CAPA = ("YouTube thumbnail, 16:9, one clear focal subject, dramatic high-contrast lighting, vivid colors, strong emotion, "
               "clean uncluttered background, large empty space on the {lado} side for a big title, NO text, no letters, "
               "no words, no watermark, no logo")

_SISTEMA_CAPAS = (
    "Você cria capas (thumbnails) de YouTube que dão clique. Para cada capa: \"ideia\" (o que mostra e por que funciona, 1 "
    "frase, em português), \"texto\" (2 a 4 palavras GRANDES no IDIOMA DO VÍDEO, que completam o título sem repeti-lo), "
    "\"prompt\" (a cena da imagem EM INGLÊS pra um gerador de imagem: assunto principal, expressão/ação, lugar, luz, "
    "enquadramento, cores — SEM pedir texto escrito na imagem) e \"personagem\" (o slug de UMA personagem do canal que "
    "aparece reagindo na capa, ou vazio se a capa fica melhor sem ela). Com personagem: ela no primeiro plano de um lado, "
    "com a expressão forte que combina, o assunto do vídeo do outro.")


def _personagem_por_slug(ctx: Dict[str, Any], slug: str) -> Optional[Dict[str, Any]]:
    return next((p for p in ctx.get("personagens") or [] if p["slug"] == slug), None)


def _nova_capa(d: Dict[str, Any], **campos: Any) -> Dict[str, Any]:
    n = max([int(c.get("n") or 0) for c in d["capas"]] + [0]) + 1
    c = {"n": n, "ideia": "", "texto": "", "prompt": "", "personagem": "", "ref": "", "status": "nova", "erro": "",
         "criado": time.time()}
    c.update({k: v for k, v in campos.items() if v is not None})
    d["capas"].append(c)
    return c


def ideias_de_capa(job_dir: str, ctx: Dict[str, Any], quantas: int = 3, pedido: str = "",
                   job_id: Optional[str] = None) -> Dict[str, Any]:
    """🤖 Ideias de capa (sempre NOVAS — as que já existem vão junto pra não repetir)."""
    import ia_servico
    from ia_midia import _S, _lista, _obj
    motivo = ia_servico.motivo_desligado("roteiros")
    if motivo:
        raise PubErro(f"IA: {motivo}")
    with _TRAVA:
        d = carregar(job_dir)
    ja = [c.get("ideia") for c in d["capas"] if c.get("ideia")]
    pers = "\n".join(f"- [{p['slug']}] {p['nome']}: {p['personalidade']}" for p in ctx.get("personagens") or [])
    conteudo = (_bloco_contexto(ctx) + (f"\n\nPERSONAGENS QUE PODEM IR NA CAPA:\n{pers}" if pers else "")
                + f"\n\nPEÇO: {quantas} capas diferentes entre si."
                + ("\nJÁ EXISTEM (traga ângulos NOVOS): " + " | ".join(ja[:20]) if ja else "")
                + (f"\nPEDIDO EXTRA (siga): {pedido.strip()[:600]}" if pedido.strip() else ""))
    schema = _obj({"capas": _lista(_obj({"ideia": _S, "texto": _S, "prompt": _S, "personagem": _S}))})
    r = ia_servico.chamar("roteiros", _SISTEMA_CAPAS, conteudo, schema=schema, max_tokens=2500, effort="medium",
                          job=job_id, cache_local=False, timeout=180)
    if not isinstance(r, dict) or not r.get("capas"):
        raise PubErro("A IA não respondeu (veja em 🤖 IA).")
    slugs = {p["slug"] for p in ctx.get("personagens") or []}
    with _TRAVA:
        d = carregar(job_dir)
        for x in r["capas"][:max(1, quantas)]:
            if not isinstance(x, dict) or not str(x.get("prompt") or "").strip():
                continue
            ps = str(x.get("personagem") or "").strip().lower()
            _nova_capa(d, ideia=str(x.get("ideia") or "")[:300], texto=str(x.get("texto") or "")[:60],
                       prompt=str(x["prompt"])[:1500], personagem=ps if ps in slugs else "")
        salvar(job_dir, d)
    return d


_SISTEMA_REF = (
    "Você recria capas de YouTube. Recebe uma CAPA DE REFERÊNCIA (de outro canal) e o contexto do NOSSO vídeo. Olhe a imagem "
    "com atenção e descreva como recriar a MESMA ideia visual pra nós: mesma composição, enquadramento, fundo/cenário, luz, "
    "paleta e clima. Regras: (1) se aparece uma PESSOA (apresentador, rosto reagindo), ela é trocada pela NOSSA personagem "
    "indicada, na mesma posição, tamanho e expressão (adaptada à personalidade dela) — nunca descreva o rosto da pessoa real; "
    "(2) o TEXTO da capa vira o NOSSO idioma (tradução natural e curta, 2-4 palavras, com o mesmo efeito — não literal se não "
    "soar bem), e a imagem é gerada SEM texto (o texto entra depois); (3) logos/marcas da referência não entram. Responda: "
    "\"ideia\" (em português: o que a capa mostra), \"tem_pessoa\" (true/false), \"texto_original\", \"texto\" (no nosso "
    "idioma), \"prompt\" (EM INGLÊS, a cena completa pra um gerador de imagem, com a nossa personagem no lugar da pessoa, "
    "SEM texto na imagem).")


def capa_de_referencia(job_dir: str, ctx: Dict[str, Any], arquivo_ref: str, personagem: str = "", pedido: str = "",
                       job_id: Optional[str] = None) -> Dict[str, Any]:
    """📤 A capa de referência enviada → uma capa NOSSA (mesma ideia, nossa personagem no lugar da pessoa, nosso idioma)."""
    import ia_servico
    from ia_midia import _S, _obj
    motivo = ia_servico.motivo_desligado("roteiros")
    if motivo:
        raise PubErro(f"IA: {motivo}")
    pers = _personagem_por_slug(ctx, personagem) or (ctx.get("personagens") or [None])[0]
    bloco = ia_servico.imagem_bloco(arquivo_ref, 768)
    if not bloco:
        raise PubErro("Não consegui abrir a imagem enviada.")
    texto = (_bloco_contexto(ctx)[:6000]
             + (f"\n\nNOSSA PERSONAGEM (vai no lugar da pessoa): {pers['nome']} — aparência: {pers['visual_en']} — "
                f"personalidade: {pers['personalidade']}" if pers else "\n\nSem personagem: se tiver pessoa, troque por algo "
                "do tema (objeto, lugar) que tenha o mesmo peso visual.")
             + (f"\n\nPEDIDO EXTRA (siga): {pedido.strip()[:600]}" if pedido.strip() else ""))
    conteudo = [{"type": "text", "text": "CAPA DE REFERÊNCIA:"}, bloco, {"type": "text", "text": texto}]
    schema = _obj({"ideia": _S, "tem_pessoa": {"type": "boolean"}, "texto_original": _S, "texto": _S, "prompt": _S})
    r = ia_servico.chamar("roteiros", _SISTEMA_REF, conteudo, schema=schema, max_tokens=1500, effort="medium",
                          job=job_id, cache_local=False, timeout=180)
    if not isinstance(r, dict) or not str(r.get("prompt") or "").strip():
        raise PubErro("A IA não conseguiu ler a capa (veja em 🤖 IA).")
    with _TRAVA:
        d = carregar(job_dir)
        c = _nova_capa(d, ideia=str(r.get("ideia") or "")[:300], texto=str(r.get("texto") or "")[:60],
                       texto_original=str(r.get("texto_original") or "")[:120], prompt=str(r["prompt"])[:1500],
                       personagem=(pers or {}).get("slug", "") if r.get("tem_pessoa") or pers else "",
                       ref=arquivo_ref, da_referencia=True)
        salvar(job_dir, d)
    return {"capa": c, **d}


def guardar_ref(job_dir: str, nome: str, dados: bytes) -> str:
    ext = os.path.splitext(nome or "")[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    p = os.path.join(pasta(job_dir), "refs")
    os.makedirs(p, exist_ok=True)
    cam = os.path.join(p, f"ref_{int(time.time())}_{secrets.token_hex(3)}{ext}")
    with open(cam, "wb") as f:
        f.write(dados)
    return cam


def editar_capa(job_dir: str, n: int, campos: Dict[str, Any]) -> Dict[str, Any]:
    with _TRAVA:
        d = carregar(job_dir)
        c = next((x for x in d["capas"] if int(x["n"]) == int(n)), None)
        if not c:
            raise PubErro("Capa não encontrada.")
        for k in ("texto", "prompt", "personagem", "ideia", "descricao"):
            if k in campos:
                c[k] = str(campos[k] or "")[:1500]
        if "estilo" in campos:
            c["estilo"] = limpar_estilo(dict(c.get("estilo") or {}, **(campos["estilo"] or {}))) if campos["estilo"] is not None else None
            if c["estilo"] is None:
                c.pop("estilo")
        if ("texto" in campos or "estilo" in campos) and c.get("imagem") and os.path.isfile(c["imagem"]):
            c["final"] = _compor(c)  # o texto novo já vai pra capa pronta
        salvar(job_dir, d)
    return d


def apagar_capa(job_dir: str, n: int) -> Dict[str, Any]:
    with _TRAVA:
        d = carregar(job_dir)
        d["capas"] = [x for x in d["capas"] if int(x["n"]) != int(n)]
        salvar(job_dir, d)
    return d


def _paineis(c: Dict[str, Any], ctx: Dict[str, Any]) -> List[Tuple[str, str]]:
    """As imagens que vão (lado a lado) de referência pro Flow, na ordem: personagem, fundo, capa de referência.
    ✏️ Capa desenhada: o rascunho, a foto de exemplo de cada item e o fundo/textura."""
    if c.get("desenho"):
        out = [("desenho", c["desenho"])] if os.path.isfile(c["desenho"]) else []
        for it in c.get("itens") or []:
            f = _foto_item(it, ctx)
            if f:
                out.append((f"item:{it['n']}", f))
        if c.get("fundo") and os.path.isfile(c["fundo"]):
            out.append(("textura", c["fundo"]))
        if c.get("ref") and os.path.isfile(c["ref"]):  # 📤 a thumb copiada: só estilo/clima
            out.append(("estilo", c["ref"]))
        return out[:7]
    out = []
    pimg = _img_personagem(c, ctx)
    if pimg:
        out.append(("personagem", pimg))
    if c.get("fundo") and os.path.isfile(c["fundo"]):
        out.append(("fundo", c["fundo"]))
    if c.get("ref") and os.path.isfile(c["ref"]):
        out.append(("ref", c["ref"]))
    return out


_PAINEL_EN = {"personagem": "the CHARACTER to use (copy her/his identity exactly: face, hair, eyes, outfit, colors, art style)",
              "fundo": "the BACKGROUND photo to use as the scene/setting (keep the place recognizable)",
              "ref": "a thumbnail used ONLY as layout/mood reference (composition, light, palette) — do NOT copy any real "
                     "person, logo or text from it"}


def prompt_flow(c: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    if c.get("desenho"):
        return _prompt_desenho(c, ctx)
    pers = _personagem_por_slug(ctx, c.get("personagem") or "")
    lado = "right" if (c["n"] % 2) else "left"
    e = c.get("estilo") if isinstance(c.get("estilo"), dict) else {}
    if e.get("pos") in ("esquerda", "direita"):
        lado = "left" if e["pos"] == "esquerda" else "right"
    partes = []
    pn = _paineis(c, ctx)
    if c.get("personalizada") or c.get("pers_arquivo") or c.get("fundo"):
        if len(pn) > 1:
            nomes = ["LEFT", "MIDDLE", "RIGHT"] if len(pn) == 3 else ["LEFT", "RIGHT"]
            partes.append(f"The reference image is a collage of {len(pn)} panels: "
                          + "; ".join(f"{nomes[i]} = {_PAINEL_EN[k]}" for i, (k, _) in enumerate(pn)) + ".")
        elif pn:
            partes.append(f"The reference image is {_PAINEL_EN[pn[0][0]]}.")
        if pers and not c.get("pers_arquivo"):
            partes.append(f"The character is {pers['nome']}: {pers['visual_en']}")
        partes.append(str(c.get("prompt") or c.get("descricao") or c.get("ideia") or "").strip().rstrip("."))
        partes.append(ESTILO_CAPA.format(lado=lado if e.get("pos") not in ("topo", "base", "centro", "livre") else
                                         {"topo": "top", "base": "bottom", "centro": "center", "livre": "center"}[e["pos"]]))
        return " ".join(" ".join(partes).split())[:3900]
    if pers and pers.get("ref"):
        if c.get("ref"):
            partes.append("The reference image is a collage of 2 panels: LEFT = the CHARACTER to use (copy her identity "
                          "exactly: face, hair, eyes, outfit, colors, art style); RIGHT = a thumbnail used ONLY as layout/mood "
                          "reference (composition, background, light, palette) — do NOT copy any real person or text from it.")
        else:
            partes.append("The reference image shows the CHARACTER to use — copy her identity exactly (face, hair, eyes, "
                          "outfit, colors, art style), in a new pose and expression for this thumbnail.")
        partes.append(f"The character is {pers['nome']}: {pers['visual_en']}")
    elif c.get("ref"):
        partes.append("The reference image is a thumbnail used ONLY as layout/mood reference (composition, background, light, "
                      "palette) — do NOT copy any real person, logo or text from it.")
    partes.append(str(c.get("prompt") or c.get("ideia") or "").strip().rstrip("."))
    partes.append(ESTILO_CAPA.format(lado=lado))
    return " ".join(" ".join(partes).split())[:3900]


def _referencia_flow(c: Dict[str, Any], ctx: Dict[str, Any], job_dir: str) -> Optional[str]:
    """A imagem que vai de referência pro Flow: a personagem (sobre cinza) e/ou a capa de referência, lado a lado."""
    from PIL import Image
    ims = []
    for k, cam in _paineis(c, ctx):
        if k == "personagem":
            im = Image.open(cam).convert("RGBA")
            fundo = Image.new("RGBA", im.size, (128, 128, 128, 255))
            fundo.alpha_composite(im)
            ims.append(fundo.convert("RGB"))
        else:
            ims.append(Image.open(cam).convert("RGB"))
    if not ims:
        return None
    import personagens_limpeza as L
    col = L.colagem(ims) if len(ims) > 1 else ims[0]
    p = os.path.join(pasta(job_dir), "flow_refs")
    os.makedirs(p, exist_ok=True)
    cam = os.path.join(p, f"capa_{c['n']}_{secrets.token_hex(3)}.png")
    col.save(cam)
    return cam


def gerar_capa(job_dir: str, ctx: Dict[str, Any], n: int, quantidade: str = "x1") -> Dict[str, Any]:
    """🎨 Manda a capa pra fila do 🚀 Flow em massa (16:9). Só no clique."""
    import flow_lote
    with _TRAVA:
        d = carregar(job_dir)
        c = next((x for x in d["capas"] if int(x["n"]) == int(n)), None)
        if not c:
            raise PubErro("Capa não encontrada.")
        if c.get("status") in ("fila", "gerando"):
            raise PubErro("Essa capa já está na fila do Flow.")
        item = {"prompt": prompt_flow(c, ctx), "tipo": "imagem", "origem": "publicacao"}
        ref = _referencia_flow(c, ctx, job_dir)
        if ref:
            item["referencia_arquivo"] = ref
        lote = flow_lote.lote()
        try:
            j = lote.adicionar([item], proporcao="16:9", quantidade=quantidade if quantidade in ("x1", "x2", "x4") else "x1")[0]
        except ValueError as exc:
            raise PubErro(str(exc))
        c.update(status="fila", flow_job=j["id"], erro="", prompt_usado=item["prompt"])
        salvar(job_dir, d)
    aviso = ""
    try:
        lote.iniciar()
    except Exception as exc:  # noqa: BLE001
        aviso = f"o Flow em massa não ligou agora ({str(exc)[:160]}) — o pedido ficou na fila; ▶ Continuar na aba Flow"
    return {"ok": True, "aviso": aviso}


def _compor(c: Dict[str, Any]) -> str:
    saida = os.path.splitext(c["imagem"])[0] + f"_final_{secrets.token_hex(2)}.jpg"
    if isinstance(c.get("estilo"), dict) or c.get("graficos"):  # 🎛 v84_231: o texto do jeito que a pessoa escolheu
        return compor_custom(c["imagem"], c.get("texto") or "", c.get("estilo") or {}, saida, graficos=c.get("graficos"))
    import thumbs_flow
    return thumbs_flow.compor(c["imagem"], c.get("texto") or "", saida)


# ------------------------------------------------------------------ 🎛 v84_231: capa personalizada
PASTA_FONTES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts", "dp")
POSICOES = ("auto", "esquerda", "direita", "centro", "topo", "base", "livre")  # livre = arrastado (tx, ty)
ESTILO_PADRAO = {"pos": "auto", "cor": "#ffffff", "cor2": "#ffd600", "tamanho": 100, "fonte": "bebas-neue", "peso": "Bold",
                 "contorno": 100, "faixa": True, "maiusculas": True, "sombra": True, "caixa": False, "cor_caixa": "#e11d48"}
PESOS = ("Bold", "Regular", "Italic")


def fontes_info() -> List[Dict[str, Any]]:
    """🔤 v84_233: cada fonte e os pesos que ela tem (pro seletor com prévia)."""
    out: Dict[str, List[str]] = {}
    try:
        for f in os.listdir(PASTA_FONTES):
            if f.endswith(".ttf") and "-" in f:
                nome, peso = f[:-4].rsplit("-", 1)
                if peso in PESOS:
                    out.setdefault(nome, []).append(peso)
    except OSError:
        pass
    return [{"nome": n, "pesos": [p for p in PESOS if p in ps]} for n, ps in sorted(out.items())]


def fontes() -> List[str]:
    """As fontes que dá pra usar no texto da capa (as que têm arquivo Bold ou Regular)."""
    try:
        nomes = sorted({f.rsplit("-", 1)[0] for f in os.listdir(PASTA_FONTES) if f.endswith(".ttf")})
    except OSError:
        return ["bebas-neue"]
    return nomes or ["bebas-neue"]


def _arq_fonte(nome: str, peso: str = "Bold") -> Optional[str]:
    nome = os.path.basename(str(nome or "bebas-neue"))
    for suf in (f"-{peso if peso in PESOS else 'Bold'}.ttf", "-Bold.ttf", "-Regular.ttf"):
        cam = os.path.join(PASTA_FONTES, nome + suf)
        if os.path.isfile(cam):
            return cam
    cam = os.path.join(PASTA_FONTES, "bebas-neue-Bold.ttf")
    return cam if os.path.isfile(cam) else None


def _cor(v: Any, padrao: Tuple[int, int, int]) -> Tuple[int, int, int]:
    t = str(v or "").strip().lstrip("#")
    if len(t) == 3:
        t = "".join(ch * 2 for ch in t)
    try:
        return (int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)) if len(t) == 6 else padrao
    except ValueError:
        return padrao


def limpar_estilo(e: Any) -> Dict[str, Any]:
    e = e if isinstance(e, dict) else {}
    out = dict(ESTILO_PADRAO)
    if e.get("pos") in POSICOES:
        out["pos"] = e["pos"]
    for k in ("tx", "ty"):  # ✋ o centro do texto arrastado (0..1)
        try:
            if e.get(k) not in (None, ""):
                out[k] = round(max(0.0, min(1.0, float(e[k]))), 4)
        except (TypeError, ValueError):
            pass
    for k in ("cor", "cor2", "cor_caixa"):
        if e.get(k) is not None:
            out[k] = "#%02x%02x%02x" % _cor(e[k], _cor(out[k], (255, 255, 255)))
    for k, lo, hi in (("tamanho", 30, 200), ("contorno", 0, 300)):
        try:
            out[k] = max(lo, min(hi, int(float(e.get(k, out[k])))))
        except (TypeError, ValueError):
            pass
    if e.get("fonte") and str(e["fonte"]) in fontes():
        out["fonte"] = str(e["fonte"])
    if e.get("peso") in PESOS:
        out["peso"] = e["peso"]
    for k in ("faixa", "maiusculas", "sombra", "caixa"):
        if k in e:
            out[k] = bool(e[k]) and str(e[k]).lower() not in ("0", "false", "nao", "não")
    for k in ("pers_lado",):
        if e.get(k) in ("esquerda", "direita", "centro"):
            out[k] = e[k]
    if e.get("pers_tam") is not None:
        try:
            out["pers_tam"] = max(30, min(120, int(float(e["pers_tam"]))))
        except (TypeError, ValueError):
            pass
    return out


def _graficos(im, graficos: List[Dict[str, Any]], W: int, H: int) -> None:
    """🔴➡ v84_233: os clássicos do YouTube desenhados por cima (não pela IA): círculo e seta, com borda escura."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    for g in graficos or []:
        try:
            cor = _cor(g.get("cor"), (239, 35, 35))
            x0, y0, x1, y1 = [max(0.0, min(1.0, float(v))) for v in g.get("bbox") or [0, 0, 0, 0]]
            esp = max(6, int(W / 110))
            if g.get("tipo") == "circulo":
                caixa = [x0 * W, y0 * H, x1 * W, y1 * H]
                d.ellipse(caixa, outline=(0, 0, 0), width=esp + 6)
                d.ellipse(caixa, outline=cor, width=esp)
            elif g.get("tipo") == "seta":
                (ax, ay), (bx, by) = [(float(p[0]) * W, float(p[1]) * H) for p in (g.get("de") or [x0, y0], g.get("para") or [x1, y1])]
                import math
                ang = math.atan2(by - ay, bx - ax)
                cab = max(esp * 4, min(90, math.hypot(bx - ax, by - ay) * 0.35))
                base = (bx - cab * 0.8 * math.cos(ang), by - cab * 0.8 * math.sin(ang))
                pts = [(bx, by), (bx - cab * math.cos(ang - 0.45), by - cab * math.sin(ang - 0.45)),
                       (bx - cab * math.cos(ang + 0.45), by - cab * math.sin(ang + 0.45))]
                d.line([(ax, ay), base], fill=(0, 0, 0), width=esp * 2 + 6)
                d.polygon(pts, fill=(0, 0, 0))
                d.line([(ax, ay), base], fill=cor, width=esp * 2)
                cx, cy = sum(p[0] for p in pts) / 3, sum(p[1] for p in pts) / 3
                d.polygon([(p[0] + (cx - p[0]) * 0.18, p[1] + (cy - p[1]) * 0.18) for p in pts], fill=cor)
        except Exception:  # noqa: BLE001
            continue


def compor_custom(imagem: str, texto: str, estilo: Dict[str, Any], saida: str, W: int = 1280, H: int = 720,
                  graficos: Optional[List[Dict[str, Any]]] = None) -> str:
    """1280×720 com o texto no estilo escolhido: posição, fonte (e peso), 2 cores (a última linha destaca), tamanho,
    contorno, faixa escura, caixa colorida atrás, maiúsculas, sombra + círculos/setas. Enter (\\n) quebra a linha."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat
    e = limpar_estilo(estilo)
    im = Image.open(imagem).convert("RGB")
    k = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * k + 0.5), int(im.height * k + 0.5)), Image.LANCZOS)
    x0, y0 = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((x0, y0, x0 + W, y0 + H))
    texto = str(texto or "").replace("\r", "")
    if e["maiusculas"]:
        texto = texto.upper()
    if "\n" in texto:
        linhas = [" ".join(l.split()) for l in texto.split("\n") if l.strip()][:5]
    else:
        pal = texto.split()
        linhas = [" ".join(pal[i:i + 2]) for i in range(0, len(pal), 2)][:4]
    if linhas:
        pos = e["pos"]
        if pos == "auto":
            g = im.convert("L").filter(ImageFilter.FIND_EDGES)
            pos = "esquerda" if ImageStat.Stat(g.crop((0, 0, W // 2, H))).mean[0] <= ImageStat.Stat(g.crop((W // 2, 0, W, H))).mean[0] else "direita"
        horiz = pos in ("topo", "base", "centro", "livre")
        tx, ty = float(e.get("tx", 0.5)), float(e.get("ty", 0.5))
        area_w = W * (0.9 if horiz else 0.46)
        area_h = H * (0.42 if pos in ("topo", "base") else 0.8)
        cam_f = _arq_fonte(e["fonte"], e.get("peso") or "Bold")
        px = int(H * 0.26 * e["tamanho"] / 100)

        def fnt(n):
            return ImageFont.truetype(cam_f, n) if cam_f else ImageFont.load_default()
        f = fnt(px)
        while px > 24 and (max(f.getlength(l) for l in linhas) > area_w or px * 0.95 * len(linhas) > area_h):
            px = int(px * 0.92)
            f = fnt(px)
        if e["faixa"]:
            som = Image.new("L", (W, H), 0)
            ds = ImageDraw.Draw(som)
            if horiz and pos != "centro":
                n = int(H * 0.55)
                for i in range(n):
                    a = int(160 * (1 - i / n) ** 1.6)
                    yy = i if pos == "topo" else H - 1 - i
                    ds.line([0, yy, W, yy], fill=a)
            elif pos in ("centro", "livre"):
                cy = ty * H if pos == "livre" else H / 2
                ds.rectangle([0, cy - H * 0.25, W, cy + H * 0.25], fill=110)
                som = som.filter(ImageFilter.GaussianBlur(40))
            else:
                n = int(W * 0.55)
                for i in range(n):
                    a = int(150 * (1 - i / n) ** 1.6)
                    xx = i if pos == "esquerda" else W - 1 - i
                    ds.line([xx, 0, xx, H], fill=a)
            im = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im, som)
        _graficos(im, graficos or [], W, H)
        d = ImageDraw.Draw(im)
        alt = px * 0.95 * len(linhas)
        y = (max(H * 0.03, min(H * 0.97 - alt, ty * H - alt / 2)) if pos == "livre" else {"topo": H * 0.06, "base": H * 0.94 - alt}.get(pos, (H - alt) / 2)) + px * 0.8
        cor1, cor2 = _cor(e["cor"], (255, 255, 255)), _cor(e["cor2"], (255, 214, 0))
        borda = int(max(2, px // 14) * e["contorno"] / 100)
        for i, l in enumerate(linhas):
            w = f.getlength(l)
            x = (tx * W - w / 2 if pos == "livre" else W * 0.05 if pos == "esquerda" else W * 0.95 - w if pos == "direita"
                 else (W - w) / 2)
            if pos == "livre":  # arrastado até a borda: não deixa a letra sair da capa
                x = max(W * 0.02, min(W * 0.98 - w, x))
            cor = cor2 if i == len(linhas) - 1 and len(linhas) > 1 else cor1
            if e.get("caixa"):  # a tarja colorida atrás de cada linha (estilo "MrBeast")
                bb = d.textbbox((x, y), l, font=f, anchor="ls")
                pad = px * 0.12
                d.rounded_rectangle([bb[0] - pad, bb[1] - pad * 0.7, bb[2] + pad, bb[3] + pad * 0.7], radius=int(pad),
                                    fill=_cor(e.get("cor_caixa"), (225, 29, 72)))
            if e["sombra"]:
                d.text((x + px * 0.05, y + px * 0.06), l, font=f, fill=(0, 0, 0), anchor="ls")
            d.text((x, y), l, font=f, fill=cor, anchor="ls", stroke_width=borda, stroke_fill=(0, 0, 0))
            y += px * 0.95
    elif graficos:
        _graficos(im, graficos, W, H)
    os.makedirs(os.path.dirname(saida) or ".", exist_ok=True)
    im.save(saida, quality=92)
    return saida


def _img_personagem(c: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[str]:
    """A personagem da capa: a de fora (enviada) ou a pose aprovada da do canal."""
    if c.get("pers_arquivo") and os.path.isfile(c["pers_arquivo"]):
        return c["pers_arquivo"]
    pers = _personagem_por_slug(ctx, c.get("personagem") or "")
    return pers["ref"] if pers and pers.get("ref") and os.path.isfile(pers["ref"]) else None


def capa_personalizada(job_dir: str, ctx: Dict[str, Any], campos: Dict[str, Any], arquivos: Dict[str, str],
                       job_id: Optional[str] = None) -> Dict[str, Any]:
    """🎛 A capa do jeito da pessoa: descrição (vira a cena), personagem do canal OU uma de fora (imagem enviada),
    foto de fundo, texto e o estilo do texto. A descrição vira prompt em inglês pela IA quando ela está ligada
    (sem IA vai como está)."""
    desc = str(campos.get("descricao") or "").strip()[:1500]
    if not desc and not arquivos.get("fundo") and not arquivos.get("personagem"):
        raise PubErro("Descreva a capa (ou envie pelo menos a foto de fundo / a personagem).")
    slug = str(campos.get("personagem") or "").strip().lower()
    if slug and not _personagem_por_slug(ctx, slug):
        slug = ""
    prompt = desc
    if desc:
        try:
            import ia_servico
            from ia_midia import _S, _obj
            if not ia_servico.motivo_desligado("roteiros"):
                pers = _personagem_por_slug(ctx, slug)
                r = ia_servico.chamar(
                    "roteiros", "Transforme a descrição de capa de YouTube do usuário num prompt EM INGLÊS pra um gerador de "
                    "imagem: siga TUDO que ele pediu (composição, cores, expressão, objetos) sem inventar outra ideia; acrescente "
                    "só detalhes de luz/enquadramento que ajudem. SEM texto escrito na imagem. Responda \"prompt\" e \"ideia\" "
                    "(resumo em português, 1 frase).",
                    f"DESCRIÇÃO DO USUÁRIO: {desc}\n\nTEMA DO VÍDEO: {(ctx.get('projeto') or {}).get('tema') or ''}"
                    + (f"\nPERSONAGEM: {pers['nome']} — {pers['visual_en']}" if pers else "")
                    + ("\nPERSONAGEM DE FORA: vem numa imagem de referência (mantenha a aparência dela)." if arquivos.get("personagem") else "")
                    + ("\nFUNDO: vem numa foto de referência (use como cenário)." if arquivos.get("fundo") else ""),
                    schema=_obj({"prompt": _S, "ideia": _S}), max_tokens=900, effort="low", job=job_id,
                    cache_local=False, timeout=120)
                if isinstance(r, dict) and str(r.get("prompt") or "").strip():
                    prompt = str(r["prompt"])[:1500]
                    campos = dict(campos, ideia=r.get("ideia") or "")
        except Exception:  # noqa: BLE001 — sem IA: a descrição vai como está
            prompt = desc
    estilo = limpar_estilo(campos.get("estilo"))
    with _TRAVA:
        d = carregar(job_dir)
        c = _nova_capa(d, ideia=str(campos.get("ideia") or desc or "capa personalizada")[:300],
                       texto=str(campos.get("texto") or "")[:120], prompt=prompt, descricao=desc, personagem=slug,
                       pers_arquivo=arquivos.get("personagem") or "", fundo=arquivos.get("fundo") or "",
                       estilo=estilo, personalizada=True)
        salvar(job_dir, d)
    return {"capa": c, **d}


def montar_sem_ia(job_dir: str, ctx: Dict[str, Any], n: int) -> Dict[str, Any]:
    """🧩 Monta a capa AQUI, sem Flow: a foto de fundo (ou a de referência / um degradê) + a personagem (PNG
    recortado) no lado e tamanho escolhidos + o texto. Vira uma versão nova da capa."""
    from PIL import Image
    W, H = 1280, 720
    with _TRAVA:
        d = carregar(job_dir)
        c = next((x for x in d["capas"] if int(x["n"]) == int(n)), None)
        if not c:
            raise PubErro("Capa não encontrada.")
        fundo = next((f for f in (c.get("fundo"), c.get("ref")) if f and os.path.isfile(f)), None)
        if fundo:
            im = Image.open(fundo).convert("RGB")
            k = max(W / im.width, H / im.height)
            im = im.resize((int(im.width * k + 0.5), int(im.height * k + 0.5)), Image.LANCZOS)
            x0, y0 = (im.width - W) // 2, (im.height - H) // 2
            im = im.crop((x0, y0, x0 + W, y0 + H)).convert("RGBA")
        else:
            im = Image.new("RGBA", (W, H))
            for yy in range(H):
                t = yy / H
                im.paste((int(20 + 30 * t), int(18 + 10 * t), int(60 + 50 * t), 255), (0, yy, W, yy + 1))
        pimg = None if c.get("desenho") else _img_personagem(c, ctx)
        fotos_itens = [(it, _foto_item(it, ctx)) for it in c.get("itens") or []]
        fotos_itens = [(it, f) for it, f in fotos_itens if f]
        if not pimg and not fundo and not fotos_itens:
            raise PubErro("Pra montar sem IA, envie a foto de fundo e/ou escolha uma personagem (ou fotos dos itens).")
        e = limpar_estilo(c.get("estilo"))
        for it, f in fotos_itens:  # ✏️ cada foto de exemplo no lugar e no tamanho que foi desenhado
            try:
                x0, y0, x1, y1 = [max(0.0, min(1.0, float(v))) for v in it.get("bbox") or [0, 0, 1, 1]]
                fi = Image.open(f).convert("RGBA")
                bb = fi.getbbox()
                if bb and fi.getextrema()[3][0] < 250:
                    fi = fi.crop(bb)
                bw, bh = max(1, int((x1 - x0) * W)), max(1, int((y1 - y0) * H))
                k = min(bw / fi.width, bh / fi.height)
                fi = fi.resize((max(1, int(fi.width * k)), max(1, int(fi.height * k))), Image.LANCZOS)
                im.alpha_composite(fi, (int(x0 * W + (bw - fi.width) / 2), int(y0 * H + (bh - fi.height) / 2)))
            except Exception:  # noqa: BLE001
                continue
        if pimg:
            p = Image.open(pimg).convert("RGBA")
            bb = p.getbbox()
            if bb and p.getextrema()[3][0] < 250:  # tem transparência: corta o vazio
                p = p.crop(bb)
            alt = int(H * e.get("pers_tam", 95) / 100)
            p = p.resize((max(1, int(p.width * alt / p.height)), alt), Image.LANCZOS)
            pos_txt = e["pos"]
            lado = e.get("pers_lado") or ("esquerda" if pos_txt == "direita" else "direita")
            x = int(W * 0.03) if lado == "esquerda" else W - p.width - int(W * 0.03) if lado == "direita" else (W - p.width) // 2
            im.alpha_composite(p, (x, H - alt))
            if e["pos"] == "auto":  # o texto vai pro lado oposto da personagem
                e["pos"] = "direita" if lado == "esquerda" else "esquerda" if lado == "direita" else "topo"
                c["estilo"] = e
        dest_dir = os.path.join(pasta(job_dir), "capas")
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, f"capa_{c['n']}_{int(time.time())}_montada.png")
        im.convert("RGB").save(dest)
        c["versoes"] = (c.get("versoes") or []) + [dest]
        c["imagem"] = dest
        c.setdefault("estilo", e)
        c["final"] = _compor(c)
        c.update(status="pronta", erro="")
        salvar(job_dir, d)
    return d


# ------------------------------------------------------------------ ✏️ v84_232: capa desenhada
_CORES_ITEM = ["#ef4444", "#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#06b6d4", "#ec4899", "#84cc16"]


def onde(bbox: Any) -> str:
    """bbox normalizado [x0, y0, x1, y1] (0..1) → onde fica e o tamanho, em inglês pro prompt."""
    try:
        x0, y0, x1, y1 = [max(0.0, min(1.0, float(v))) for v in bbox]
    except (TypeError, ValueError):
        return "somewhere in the frame"
    cx, cy, area = (x0 + x1) / 2, (y0 + y1) / 2, max(0.0, (x1 - x0) * (y1 - y0))
    h = "left" if cx < 0.36 else "right" if cx > 0.64 else "center"
    v = "top" if cy < 0.36 else "bottom" if cy > 0.64 else "middle"
    lugar = "center of the frame" if (h, v) == ("center", "middle") else f"{v} {h}" if h != "center" else f"{v} center"
    tam = "huge, filling most of the frame" if area > 0.45 else "large" if area > 0.18 else "medium-sized" if area > 0.06 else "small"
    return f"{tam}, at the {lugar} (about x {int(x0 * 100)}–{int(x1 * 100)}%, y {int(y0 * 100)}–{int(y1 * 100)}% of the frame)"


def _foto_item(it: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[str]:
    if it.get("foto") and os.path.isfile(it["foto"]):
        return it["foto"]
    pers = _personagem_por_slug(ctx, it.get("personagem") or "")
    return pers["ref"] if pers and pers.get("ref") and os.path.isfile(pers["ref"]) else None


def _descr_item(it: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    pers = _personagem_por_slug(ctx, it.get("personagem") or "")
    nome = str(it.get("o_que") or "").strip()
    if pers:
        nome = (nome + " — " if nome else "") + f"the character {pers['nome']} ({pers['visual_en']})"
    return nome or "an object (see its example photo)"


def _prompt_desenho(c: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    pn = _paineis(c, ctx)
    partes = []
    if pn:
        rot = []
        for k, (tipo, _) in enumerate(pn):
            if tipo == "desenho":
                rot.append(f"PANEL {k + 1} = a rough LAYOUT SKETCH: each colored numbered blob only marks WHERE an element goes "
                           "and how big it is — do not copy the sketch style, colors or numbers")
            elif tipo.startswith("item:"):
                rot.append(f"PANEL {k + 1} = example of element #{tipo[5:]} (copy what it is and how it looks)")
            elif tipo == "estilo":
                rot.append(f"PANEL {k + 1} = a thumbnail used ONLY as STYLE/mood reference (light, palette, energy) — do NOT "
                           "copy any real person, logo or text from it")
            else:
                rot.append(f"PANEL {k + 1} = the BACKGROUND texture/photo to use behind everything")
        partes.append(f"The reference image is a collage of {len(pn)} panels, from left to right: " + "; ".join(rot) + "."
                      if len(pn) > 1 else rot[0].split("= ", 1)[1].capitalize() + ".")
    if str(c.get("prompt") or "").strip():
        partes.append(str(c["prompt"]).strip().rstrip("."))
    else:
        for it in c.get("itens") or []:
            partes.append(f"Element #{it['n']}: {_descr_item(it, ctx)} — {onde(it.get('bbox'))}.")
        if c.get("fundo_desc") or c.get("fundo"):
            partes.append("Background: " + (str(c.get("fundo_desc") or "").strip() or "the texture/photo from the reference") + ".")
    partes.append("Follow the sketch layout exactly (same positions and sizes). YouTube thumbnail, 16:9, dramatic high-contrast "
                  "lighting, vivid colors, NO text, no letters, no words, no watermark, no logo")
    return " ".join(" ".join(partes).split())[:3900]


def capa_de_desenho(job_dir: str, ctx: Dict[str, Any], desenho: str, itens: List[Dict[str, Any]], fotos: Dict[int, str],
                    fundo_desc: str = "", fundo_arq: str = "", texto: str = "", estilo: Any = None, pedido: str = "",
                    job_id: Optional[str] = None, ref: str = "") -> Dict[str, Any]:
    """✏️ O rascunho desenhado (cada contorno = um item numerado) + o que é cada item (texto e/ou foto de exemplo ou
    personagem do canal) + o fundo/textura → uma capa. A IA olha o rascunho e escreve a cena (em inglês) respeitando
    as posições; sem IA, o prompt sai montado das posições."""
    limpos, graficos = [], []
    for k, it in enumerate(itens[:12]):
        if not isinstance(it, dict):
            continue
        n = int(it.get("n") or k + 1)
        if it.get("tipo") in ("circulo", "seta"):  # 🔴➡ desenhado pelo site por cima, não vai pra IA
            try:
                graficos.append({"tipo": it["tipo"], "n": n, "cor": str(it.get("cor_grafico") or "#ef2323")[:9],
                                 "bbox": [round(float(v), 4) for v in (it.get("bbox") or [0, 0, 1, 1])][:4],
                                 "de": [round(float(v), 4) for v in (it.get("de") or [])][:2] or None,
                                 "para": [round(float(v), 4) for v in (it.get("para") or [])][:2] or None})
            except (TypeError, ValueError):
                pass
            continue
        x = {"n": n, "o_que": str(it.get("o_que") or "")[:300], "cor": str(it.get("cor") or _CORES_ITEM[k % 8])[:9],
             "bbox": [round(float(v), 4) for v in (it.get("bbox") or [0, 0, 1, 1])][:4],
             "personagem": str(it.get("personagem") or "").strip().lower(), "foto": fotos.get(n, "")}
        if x["personagem"] and not _personagem_por_slug(ctx, x["personagem"]):
            x["personagem"] = ""
        if not (x["o_que"] or x["foto"] or x["personagem"]):
            raise PubErro(f"Diga o que é o item {n} (escreva, mande uma foto de exemplo ou escolha a personagem).")
        limpos.append(x)
    if not limpos and not fundo_arq:
        raise PubErro("Desenhe pelo menos um contorno na capa (círculo e seta sozinhos não fazem a imagem).")
    prompt, ideia = "", ""
    try:
        import ia_servico
        from ia_midia import _S, _obj
        if not ia_servico.motivo_desligado("roteiros"):
            linhas = "\n".join(f"#{it['n']} (cor {it['cor']}): {_descr_item(it, ctx)}"
                                + (" [tem foto de exemplo]" if it["foto"] else "") + f" — {onde(it['bbox'])}" for it in limpos)
            conteudo: List[Dict[str, Any]] = [{"type": "text", "text": "RASCUNHO DA CAPA (cada mancha colorida numerada é um item):"}]
            b = ia_servico.imagem_bloco(desenho, 768)
            if b:
                conteudo.append(b)
            conteudo.append({"type": "text", "text":
                             f"ITENS:\n{linhas}\n\nFUNDO: {fundo_desc or ('a textura/foto enviada' if fundo_arq else 'livre, combinando com o tema')}"
                             f"\nTEMA DO VÍDEO: {(ctx.get('projeto') or {}).get('tema') or ''}"
                             + (f"\nTEXTO QUE VAI POR CIMA (não desenhar): {texto}" if texto else "")
                             + (f"\nPEDIDO EXTRA: {pedido}" if pedido else "")})
            r = ia_servico.chamar(
                "roteiros", "Você transforma o RASCUNHO de uma capa de YouTube num prompt de gerador de imagem. Respeite a "
                "posição e o tamanho de CADA item como estão no rascunho (diga onde cada um fica), o que cada item é, e o "
                "fundo. Não invente itens novos importantes. Escreva \"prompt\" EM INGLÊS (uma cena só, rica em detalhe de "
                "luz/estilo, SEM texto escrito na imagem) e \"ideia\" (resumo em português, 1 frase).",
                conteudo, schema=_obj({"prompt": _S, "ideia": _S}), max_tokens=1200, effort="low", job=job_id,
                cache_local=False, timeout=150)
            if isinstance(r, dict) and str(r.get("prompt") or "").strip():
                prompt, ideia = str(r["prompt"])[:1800], str(r.get("ideia") or "")[:300]
    except Exception:  # noqa: BLE001 — sem IA: o prompt sai das posições
        prompt = ""
    if not prompt:
        prompt = " ".join(f"Element #{it['n']}: {_descr_item(it, ctx)} — {onde(it['bbox'])}." for it in limpos) + (
            f" Background: {fundo_desc or 'the texture/photo from the reference'}." if (fundo_desc or fundo_arq) else "")
    with _TRAVA:
        d = carregar(job_dir)
        c = _nova_capa(d, ideia=ideia or "capa desenhada: " + ", ".join(_descr_item(it, ctx)[:40] for it in limpos),
                       texto=str(texto or "")[:120], prompt=prompt, desenho=desenho, itens=limpos, fundo=fundo_arq or "",
                       fundo_desc=str(fundo_desc or "")[:600], estilo=limpar_estilo(estilo), personalizada=True,
                       desenhada=True, graficos=graficos, ref=ref if ref and os.path.isfile(ref) else "")
        salvar(job_dir, d)
    return {"capa": c, **d}


# 🧩 v84_233: predefinições — os modelos de capa mais comuns no YouTube (viram um rascunho pronto pra ajustar)
def _it(papel: str, bbox: List[float], forma: str = "ret", dica: str = "", **kw: Any) -> Dict[str, Any]:
    return dict({"papel": papel, "bbox": bbox, "forma": forma, "dica": dica}, **kw)


PRESETS: List[Dict[str, Any]] = [
    {"id": "pessoa_objeto", "nome": "Pessoa + objeto", "desc": "personagem de um lado, o assunto do outro, texto em cima",
     "itens": [_it("personagem", [0.02, 0.22, 0.42, 1.0], "eli", "personagem com expressão forte"),
               _it("coisa", [0.55, 0.25, 0.97, 0.9], "ret", "o assunto do vídeo (objeto/lugar)")],
     "estilo": {"pos": "topo", "tamanho": 110}, "texto": "ISSO MUDA\nTUDO"},
    {"id": "reacao_seta", "nome": "Reação + seta", "desc": "personagem chocada à direita, seta apontando pro assunto",
     "itens": [_it("coisa", [0.04, 0.2, 0.5, 0.92], "eli", "o assunto chocante"),
               _it("personagem", [0.6, 0.18, 0.99, 1.0], "eli", "personagem chocada, boca aberta"),
               _it("seta", [0.42, 0.3, 0.6, 0.5], tipo="seta", de=[0.6, 0.35], para=[0.44, 0.5])],
     "estilo": {"pos": "topo", "caixa": True}, "texto": "OLHA ISSO"},
    {"id": "vs", "nome": "VS / comparação", "desc": "duas coisas frente a frente, VS no meio",
     "itens": [_it("coisa", [0.02, 0.12, 0.44, 0.95], "ret", "lado A"), _it("coisa", [0.56, 0.12, 0.98, 0.95], "ret", "lado B")],
     "estilo": {"pos": "centro", "tamanho": 150, "cor": "#ffd600", "faixa": False}, "texto": "VS"},
    {"id": "antes_depois", "nome": "Antes × Depois", "desc": "a tela dividida ao meio",
     "itens": [_it("coisa", [0.0, 0.0, 0.5, 1.0], "ret", "ANTES (como era)"), _it("coisa", [0.5, 0.0, 1.0, 1.0], "ret", "DEPOIS (como ficou)")],
     "estilo": {"pos": "base", "caixa": True, "tamanho": 80}, "texto": "ANTES     DEPOIS"},
    {"id": "close_rosto", "nome": "Close no rosto", "desc": "rosto grande de um lado, texto gigante do outro",
     "itens": [_it("personagem", [0.45, 0.0, 1.0, 1.0], "eli", "rosto bem de perto, emoção exagerada")],
     "estilo": {"pos": "esquerda", "tamanho": 130}, "texto": "NÃO\nACREDITO"},
    {"id": "misterio", "nome": "Mistério com círculo", "desc": "um detalhe circulado em vermelho, personagem pequena olhando",
     "itens": [_it("coisa", [0.15, 0.1, 0.85, 0.95], "ret", "a cena/foto com o detalhe misterioso"),
               _it("personagem", [0.0, 0.5, 0.28, 1.0], "eli", "personagem desconfiada"),
               _it("circulo", [0.55, 0.25, 0.78, 0.55], "eli", tipo="circulo")],
     "estilo": {"pos": "topo", "tamanho": 90}, "texto": "O QUE É ISSO?"},
    {"id": "central", "nome": "Objeto no centro", "desc": "uma coisa grande no meio, texto embaixo com tarja",
     "itens": [_it("coisa", [0.25, 0.05, 0.75, 0.78], "eli", "o objeto principal, bem iluminado")],
     "estilo": {"pos": "base", "caixa": True}, "texto": "O MAIOR DO MUNDO"},
    {"id": "top3", "nome": "Top / lista", "desc": "3 coisas lado a lado, TOP em cima",
     "itens": [_it("coisa", [0.02, 0.32, 0.33, 0.98], "ret", "item 1"), _it("coisa", [0.35, 0.32, 0.65, 0.98], "ret", "item 2"),
               _it("coisa", [0.67, 0.32, 0.98, 0.98], "ret", "item 3")],
     "estilo": {"pos": "topo", "tamanho": 120}, "texto": "TOP 3"},
    {"id": "apontando", "nome": "Personagem apontando", "desc": "personagem à esquerda apontando pro assunto, com seta",
     "itens": [_it("personagem", [0.0, 0.15, 0.4, 1.0], "eli", "personagem apontando pro lado"),
               _it("coisa", [0.52, 0.2, 0.98, 0.95], "ret", "o assunto"),
               _it("seta", [0.35, 0.45, 0.55, 0.6], tipo="seta", de=[0.36, 0.55], para=[0.54, 0.5])],
     "estilo": {"pos": "topo"}, "texto": "VOCÊ SABIA?"},
    {"id": "fundo_texto", "nome": "Fundo + texto", "desc": "só uma imagem impactante e o texto enorme",
     "itens": [_it("coisa", [0.0, 0.0, 1.0, 1.0], "ret", "a paisagem/cena de fundo")],
     "estilo": {"pos": "centro", "tamanho": 140}, "texto": "O FIM"},
]


# ------------------------------------------------------------------ 📤 v84_234: copiar o modelo de uma thumb
_SISTEMA_MODELO = (
    "Você analisa a COMPOSIÇÃO de uma capa (thumbnail) de YouTube pra ela virar um MODELO editável. Olhe a imagem e "
    "devolva onde fica cada elemento, em coordenadas normalizadas 0..1 (x da esquerda pra direita, y de cima pra baixo; "
    "x0,y0 = canto superior esquerdo, x1,y1 = inferior direito da caixa que cobre o elemento):\n"
    "- \"itens\": os elementos visuais principais (no máximo 6): papel \"personagem\" (pessoa/rosto/mascote) ou \"coisa\" "
    "(objeto, lugar, animal, produto…); forma \"eli\" (redondo/orgânico) ou \"ret\"; \"original\" = o que é na capa (pt, curto); "
    "\"nosso\" = o que colocar NO LUGAR dele na NOSSA versão (pt, curto) — veja a regra de preenchimento abaixo.\n"
    "- \"graficos\": setas e círculos/destaques desenhados (tipo \"seta\": x0,y0 = de onde SAI, x1,y1 = a PONTA; tipo "
    "\"circulo\": a caixa do círculo), com a cor em hex.\n"
    "- \"texto\": o texto grande da capa: \"original\", \"nosso\" (no IDIOMA DO VÍDEO, curto, mesma força), \"x\",\"y\" "
    "(centro do bloco), \"linhas\", \"cor\" e \"cor2\" (hex; cor2 = a cor da linha de destaque, se tiver), \"caixa\" (tem "
    "tarja colorida atrás?), \"cor_caixa\", \"tamanho\" (50 a 180, 100 = grande normal). Sem texto: original vazio.\n"
    "- \"fundo\": \"original\" e \"nosso\" (pt).\n- \"estilo\": em pt, 1 frase (cores, luz, energia).\n"
    "Pessoas reais não são identificadas: descreva só o papel (\"homem surpreso\"). Logos/marcas não entram.")


def _num(v: Any, padrao: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return padrao


def copiar_modelo(job_dir: str, ctx: Dict[str, Any], arquivo: str, pedido: str = "", preencher: bool = False,
                  job_id: Optional[str] = None) -> Dict[str, Any]:
    """📤 A thumb enviada → o MODELO (itens com posição, setas/círculos, texto com posição/cores/tarja, fundo) pra
    abrir no ✏️ desenho. preencher=True: a IA já diz o que vai em cada item na nossa versão (pelo tema do vídeo e
    pelo pedido); senão os itens vêm vazios com o original de dica, pra pessoa preencher."""
    import ia_servico
    from ia_midia import _B, _N, _S, _lista, _obj
    motivo = ia_servico.motivo_desligado("roteiros")
    if motivo:
        raise PubErro(f"IA: {motivo}")
    bloco = ia_servico.imagem_bloco(arquivo, 1024)
    if not bloco:
        raise PubErro("Não consegui abrir a imagem enviada.")
    pers = "; ".join(f"{p['nome']} ({p['personalidade']})" for p in ctx.get("personagens") or [])
    regra = ("PREENCHA \"nosso\" de cada item, do texto e do fundo pra NOSSO vídeo (abaixo): pessoa → a nossa personagem; "
             "objetos/lugar → o equivalente do nosso assunto." if preencher or pedido.strip() else
             "Deixe \"nosso\" VAZIO nos itens e no fundo (a pessoa vai preencher); no texto, \"nosso\" pode ficar vazio também.")
    texto = (f"REGRA DE PREENCHIMENTO: {regra}\n\n" + _bloco_contexto(ctx)[:5000]
             + (f"\n\nNOSSAS PERSONAGENS: {pers}" if pers else "")
             + (f"\n\nO QUE A PESSOA QUER NA VERSÃO DELA (siga): {pedido.strip()[:800]}" if pedido.strip() else ""))
    cx = {"x0": _N, "y0": _N, "x1": _N, "y1": _N}
    schema = _obj({
        "itens": _lista(_obj(dict(cx, papel={"type": "string", "enum": ["personagem", "coisa"]}, forma={"type": "string", "enum": ["eli", "ret"]},
                                  original=_S, nosso=_S))),
        "graficos": _lista(_obj(dict(cx, tipo={"type": "string", "enum": ["seta", "circulo"]}, cor=_S))),
        "texto": _obj({"original": _S, "nosso": _S, "x": _N, "y": _N, "linhas": {"type": "integer"}, "cor": _S, "cor2": _S,
                       "caixa": _B, "cor_caixa": _S, "tamanho": {"type": "integer"}}),
        "fundo": _obj({"original": _S, "nosso": _S}), "estilo": _S})
    r = ia_servico.chamar("roteiros", _SISTEMA_MODELO, [{"type": "text", "text": "A CAPA:"}, bloco, {"type": "text", "text": texto}],
                          schema=schema, max_tokens=2500, effort="medium", job=job_id, cache_local=False, timeout=180)
    if not isinstance(r, dict) or not isinstance(r.get("itens"), list):
        raise PubErro("A IA não conseguiu ler a composição (veja em 🤖 IA).")
    itens = []
    for it in r["itens"][:6]:
        if not isinstance(it, dict):
            continue
        x0, x1 = sorted((_num(it.get("x0")), _num(it.get("x1"), 1)))
        y0, y1 = sorted((_num(it.get("y0")), _num(it.get("y1"), 1)))
        if x1 - x0 < 0.02 or y1 - y0 < 0.02:
            continue
        itens.append({"papel": "personagem" if it.get("papel") == "personagem" else "coisa", "forma": "eli" if it.get("forma") == "eli" else "ret",
                      "bbox": [round(v, 4) for v in (x0, y0, x1, y1)], "dica": str(it.get("original") or "")[:120],
                      "nosso": str(it.get("nosso") or "")[:200] if (preencher or pedido.strip()) else ""})
    graficos = []
    for g in (r.get("graficos") or [])[:4]:
        if not isinstance(g, dict) or g.get("tipo") not in ("seta", "circulo"):
            continue
        a, b = [_num(g.get("x0")), _num(g.get("y0"))], [_num(g.get("x1")), _num(g.get("y1"))]
        cor = "#%02x%02x%02x" % _cor(g.get("cor"), (239, 35, 35))
        if g["tipo"] == "seta":
            graficos.append({"tipo": "seta", "de": a, "para": b, "cor": cor})
        else:
            graficos.append({"tipo": "circulo", "bbox": [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])], "cor": cor})
    t = r.get("texto") if isinstance(r.get("texto"), dict) else {}
    tem_txt = bool(str(t.get("original") or "").strip())
    estilo = limpar_estilo({"pos": "livre", "tx": _num(t.get("x"), 0.5), "ty": _num(t.get("y"), 0.2), "cor": t.get("cor") or "#ffffff",
                            "cor2": t.get("cor2") or t.get("cor") or "#ffd600", "caixa": bool(t.get("caixa")),
                            "cor_caixa": t.get("cor_caixa") or "#e11d48", "tamanho": t.get("tamanho") or 100, "faixa": False}) if tem_txt else None
    ref = guardar_ref(job_dir, os.path.basename(arquivo), open(arquivo, "rb").read()) if not os.path.dirname(arquivo).endswith("refs") else arquivo
    f = r.get("fundo") if isinstance(r.get("fundo"), dict) else {}
    return {"itens": itens, "graficos": graficos, "estilo": estilo, "texto_original": str(t.get("original") or "")[:120] if tem_txt else "",
            "texto": str(t.get("nosso") or "")[:120] if tem_txt else "", "fundo_original": str(f.get("original") or "")[:200],
            "fundo": str(f.get("nosso") or "")[:300] if (preencher or pedido.strip()) else "", "estilo_visual": str(r.get("estilo") or "")[:300],
            "ref_guia": os.path.basename(ref), "url_guia": os.path.basename(ref)}


def guardar_upload(job_dir: str, sub: str, nome: str, dados: bytes) -> str:
    ext = os.path.splitext(nome or "")[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    p = os.path.join(pasta(job_dir), sub)
    os.makedirs(p, exist_ok=True)
    cam = os.path.join(p, f"{sub}_{int(time.time())}_{secrets.token_hex(3)}{ext}")
    with open(cam, "wb") as f:
        f.write(dados)
    return cam


# ------------------------------------------------------------------ ✏️ v84_231: modificar uma capa gerada
def modificar_capa(job_dir: str, ctx: Dict[str, Any], n: int, pedido: str, quantidade: str = "x1") -> Dict[str, Any]:
    """✏️ Pede pro Flow MUDAR a capa atual (a imagem limpa, sem o texto). Se ela veio do Flow, a mesma conta volta ao
    projeto dela e edita a partir da mídia que já está lá; sem crédito (ou ocupada), outra conta pega e sobe a imagem."""
    import flow_lote
    pedido = " ".join(str(pedido or "").split())[:800]
    if not pedido:
        raise PubErro("Escreva o que mudar na capa.")
    with _TRAVA:
        d = carregar(job_dir)
        c = next((x for x in d["capas"] if int(x["n"]) == int(n)), None)
        if not c or not c.get("imagem") or not os.path.isfile(c["imagem"]):
            raise PubErro("Essa capa ainda não tem imagem pra modificar.")
        if c.get("status") in ("fila", "gerando"):
            raise PubErro("Essa capa já está na fila do Flow.")
        prompt = ("Edit the reference image (a YouTube thumbnail): keep EVERYTHING the same — composition, characters, faces, "
                  "art style, colors, lighting — and change ONLY this: " + pedido + ". Keep it 16:9. NO text, no letters, "
                  "no words, no watermark, no logo.")
        item: Dict[str, Any] = {"prompt": prompt, "tipo": "imagem", "origem": "publicacao", "referencia_arquivo": c["imagem"]}
        orig = (c.get("origens") or {}).get(os.path.basename(c["imagem"])) or {}
        if orig.get("conta") and orig.get("projeto"):
            item.update(conta_pref=orig["conta"], projeto_url=orig["projeto"], ref_media_id=orig.get("media_id") or "")
        lote = flow_lote.lote()
        try:
            j = lote.adicionar([item], proporcao="16:9", quantidade=quantidade if quantidade in ("x1", "x2", "x4") else "x1")[0]
        except ValueError as exc:
            raise PubErro(str(exc))
        c.update(status="fila", flow_job=j["id"], erro="", prompt_usado=prompt,
                 modificacoes=(c.get("modificacoes") or []) + [{"pedido": pedido, "quando": time.time(),
                                                                "mesmo_projeto": bool(item.get("projeto_url"))}])
        salvar(job_dir, d)
    aviso = ""
    try:
        lote.iniciar()
    except Exception as exc:  # noqa: BLE001
        aviso = f"o Flow em massa não ligou agora ({str(exc)[:160]}) — o pedido ficou na fila; ▶ Continuar na aba Flow"
    return {"ok": True, "aviso": aviso, "mesmo_projeto": bool(item.get("projeto_url"))}


def sincronizar(job_dir: str) -> bool:
    """O que o Flow terminou entra nas capas (+ o texto por cima). → se mudou."""
    with _TRAVA:
        d = carregar(job_dir)
        abertas = [c for c in d["capas"] if c.get("status") in ("fila", "gerando") and c.get("flow_job")]
        if not abertas:
            return False
        import flow_estudio as FE
        import flow_lote
        lote = flow_lote.lote()
        with lote.trava:
            fila = {j["id"]: dict(j) for j in lote.fila}
        mudou = False
        for c in abertas:
            fj = fila.get(c["flow_job"])
            antes = (c.get("status"), c.get("erro"))
            if fj is None:
                c.update(status="erro", erro="o pedido sumiu da fila do Flow — gere de novo")
            elif fj["estado"] == "ok":
                res = [r for r in fj.get("resultados") or [] if r.get("tipo") == "imagem"
                       and os.path.isfile(os.path.join(FE.pasta_galeria(), r.get("arquivo") or ""))]
                imgs = [os.path.join(FE.pasta_galeria(), r["arquivo"]) for r in res]
                if not imgs:
                    c.update(status="erro", erro="o Flow terminou sem imagem")
                else:
                    p = os.path.join(pasta(job_dir), "capas")
                    os.makedirs(p, exist_ok=True)
                    versoes = []
                    for k, orig in enumerate(imgs):
                        dest = os.path.join(p, f"capa_{c['n']}_{int(time.time())}_{k}{os.path.splitext(orig)[1] or '.png'}")
                        shutil.copyfile(orig, dest)
                        versoes.append(dest)
                        r = res[k]  # ✏️ de onde ela veio no Flow (pra modificar depois no mesmo projeto)
                        if r.get("projeto") and r.get("conta"):
                            c.setdefault("origens", {})[os.path.basename(dest)] = {
                                "conta": r["conta"], "projeto": r["projeto"], "media_id": r.get("media_id") or ""}
                    c["versoes"] = (c.get("versoes") or []) + versoes
                    c["imagem"] = versoes[0]
                    c["final"] = _compor(c)
                    c.update(status="pronta", erro="")
            elif fj["estado"] == "erro":
                c.update(status="erro", erro=str(fj.get("erro") or "o Flow falhou")[:300])
            elif fj["estado"] in ("rodando", "convertendo"):
                c["status"] = "gerando"
            if (c.get("status"), c.get("erro")) != antes:
                mudou = True
        if mudou:
            salvar(job_dir, d)
        return mudou


def escolher_versao(job_dir: str, n: int, idx: int) -> Dict[str, Any]:
    with _TRAVA:
        d = carregar(job_dir)
        c = next((x for x in d["capas"] if int(x["n"]) == int(n)), None)
        if not c or not 0 <= idx < len(c.get("versoes") or []):
            raise PubErro("Versão não encontrada.")
        c["imagem"] = c["versoes"][idx]
        c["final"] = _compor(c)
        salvar(job_dir, d)
    return d


def para_tela(d: Dict[str, Any], api: str, ctx_pers: List[Dict[str, Any]]) -> Dict[str, Any]:
    url = f"{api}/capa"
    capas = []
    for c in d.get("capas") or []:
        x = {k: c.get(k) for k in ("n", "ideia", "texto", "texto_original", "prompt", "personagem", "status", "erro", "da_referencia",
                                   "descricao", "personalizada", "estilo")}
        x["pers_fora"] = bool(c.get("pers_arquivo") and os.path.isfile(c["pers_arquivo"]))
        x["url_fundo"] = f"{url}/{c['n']}/fundo" if c.get("fundo") and os.path.isfile(c["fundo"]) else ""
        x["url_pers"] = f"{url}/{c['n']}/pers_arquivo" if x["pers_fora"] else ""
        x["modificacoes"] = [m.get("pedido") for m in c.get("modificacoes") or []][-5:]
        x["url_desenho"] = f"{url}/{c['n']}/desenho" if c.get("desenho") and os.path.isfile(c["desenho"]) else ""
        x["itens"] = [{"n": it["n"], "cor": it.get("cor"), "o_que": it.get("o_que"), "personagem": it.get("personagem"),
                       "tem_foto": bool(it.get("foto"))} for it in c.get("itens") or []]
        x["fundo_desc"] = c.get("fundo_desc") or ""
        x["graficos"] = [{"tipo": g["tipo"], "n": g.get("n")} for g in c.get("graficos") or []]
        x["origem_flow"] = bool((c.get("origens") or {}).get(os.path.basename(c.get("imagem") or "")))
        v = int(os.path.getmtime(c["final"])) if c.get("final") and os.path.isfile(c["final"]) else 0
        x["url_final"] = f"{url}/{c['n']}/final?v={v}" if v else ""
        x["url_ref"] = f"{url}/{c['n']}/ref" if c.get("ref") and os.path.isfile(c["ref"]) else ""
        x["versoes"] = len(c.get("versoes") or [])
        x["versao"] = (c.get("versoes") or []).index(c["imagem"]) if c.get("imagem") in (c.get("versoes") or []) else 0
        capas.append(x)
    return {"textos": {t: (d.get("textos") or {}).get(t) or [] for t in TIPOS_TEXTO}, "capas": capas,
            "idioma": d.get("idioma") or {}, "personagens": [{"slug": p["slug"], "nome": p["nome"], "tem_ref": bool(p.get("ref"))}
                                                             for p in ctx_pers],
            "esperando": any(c.get("status") in ("fila", "gerando") for c in d.get("capas") or []),
            "fontes": fontes(), "fontes_info": fontes_info(), "estilo_padrao": ESTILO_PADRAO, "presets": PRESETS}


# ------------------------------------------------------------------ rotas
def registrar(app, obter: Callable[[str], Optional[Dict[str, Any]]], job_dir: Callable[[str], str],
              palavras_de: Callable[[Dict[str, Any]], List[Dict[str, Any]]], base: str,
              projeto_de: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None) -> None:
    """As mesmas rotas em dois lugares: /job/<id>/publicacao (Estúdio e tela do vídeo) e /publicacoes/<id>/api (o
    histórico — funciona mesmo com o projeto apagado, com o contexto guardado)."""
    from flask import jsonify, redirect, render_template, request, send_file

    def _pdir(pid: str) -> str:
        pd = pdir_de(base, pid)
        job = obter(pid)
        if job:
            try:
                migrar(job_dir(pid), pd)
            except Exception:  # noqa: BLE001
                pass
        return pd

    def _ctx(pid: str) -> Dict[str, Any]:
        """Com o projeto: o contexto vivo (e guarda a cópia). Sem: a cópia guardada."""
        job = obter(pid)
        pd = _pdir(pid)
        if job:
            pr = None
            if projeto_de:
                try:
                    pr = projeto_de(job)
                except Exception:  # noqa: BLE001
                    pr = None
            ctx = contexto(job, base, palavras_de(job), pr)
            titulo = str(job.get("titulo") or job.get("nome") or job.get("title") or (pr or {}).get("tema") or "")[:160]
            try:
                salvar_ctx(pd, {k: v for k, v in ctx.items() if k != "personagens"} | {
                    "personagens": [{k: p.get(k) for k in ("slug", "nome", "visual_en", "personalidade", "ref")} for p in ctx["personagens"]]},
                    {"titulo": titulo, "tem_projeto": True, "job_id": pid})
            except OSError:
                pass
            return _com_estilo(pd, ctx)
        cx = carregar_ctx(pd)
        if not cx.get("ctx"):
            raise PubErro("Essa publicação não tem o contexto guardado (o projeto foi apagado antes da v84_230).")
        salvar_ctx(pd, cx["ctx"], {"tem_projeto": False})
        return _com_estilo(pd, cx["ctx"])

    def _com_estilo(pd: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """📊 o canal escolhido pra modelar entra no contexto de TODOS os pedidos à IA."""
        aid = carregar(pd).get("canal_estilo")
        e = estilo_canal(base, aid) if aid else None
        return dict(ctx, estilo_canal=e) if e else ctx

    def _resumo_estilo(e: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not e:
            return None
        return {k: e.get(k) for k in ("id", "nome", "tem_ia", "thumbs_receita", "thumbs_estilo", "thumbs")} | {
            "titulos_top": [t["titulo"] for t in e.get("titulos_top") or []][:6],
            "formulas": [f["formula"] for f in e.get("formulas") or [] if f.get("formula")][:4]}

    def _resp(pid: str, api: str, fn):
        try:
            pd = _pdir(pid)
            if not obter(pid) and not carregar_ctx(pd):
                return jsonify({"erro": "Publicação não encontrada."}), 404
            extra = fn(pd) or {}
        except PubErro as exc:
            return jsonify({"erro": str(exc)}), 400
        try:
            sincronizar(pd)
        except Exception:  # noqa: BLE001
            pass
        try:
            ctx = _ctx(pid)
        except PubErro:
            ctx = {}
        cx = carregar_ctx(pd)
        return jsonify(dict(para_tela(carregar(pd), api, ctx.get("personagens") or []), idioma_video=ctx.get("idioma") or {},
                            meta=cx.get("meta") or {}, canal_estilo=_resumo_estilo(ctx.get("estilo_canal")), roteiro=((ctx.get("projeto") or {}).get("roteiro") or "")[:30000],
                            narracao=(ctx.get("narracao") or "")[:30000],
                            **{k: v for k, v in extra.items() if k in ("aviso", "capa_nova", "mesmo_projeto", "modelo")}))

    def _rotas(prefixo: str, suf: str, api_de: Callable[[str], str]) -> None:
        def rota(caminho: str, nome: str, metodos: List[str], fn: Callable) -> None:
            app.add_url_rule(prefixo + caminho, endpoint=f"pub_{nome}_{suf}", view_func=fn, methods=metodos)

        def estado(pid: str):
            return _resp(pid, api_de(pid), lambda pd: None)

        def textos(pid: str):
            c = request.get_json(silent=True) or {}

            def f(pd):
                tipos = c.get("tipos") if isinstance(c.get("tipos"), list) else None
                gerar_textos(pd, _ctx(pid), tipos, bool(c.get("mais")), str(c.get("pedido") or ""), pid)
            return _resp(pid, api_de(pid), f)

        def texto_editar(pid: str, tipo: str, idx: int):
            c = request.get_json(silent=True) or {}
            return _resp(pid, api_de(pid), lambda pd: editar_texto(pd, tipo, idx, None if c.get("apagar") else str(c.get("valor") or "")) and None)

        def capas_ideias(pid: str):
            c = request.get_json(silent=True) or {}
            return _resp(pid, api_de(pid), lambda pd: ideias_de_capa(pd, _ctx(pid), int(c.get("quantas") or 3),
                                                                     str(c.get("pedido") or ""), pid) and None)

        def capa_ref(pid: str):
            arq = request.files.get("imagem")

            def f(pd):
                if not arq or not arq.filename:
                    raise PubErro("Escolha a imagem da capa de referência.")
                cam = guardar_ref(pd, arq.filename, arq.read())
                ctx = _ctx(pid)
                r = capa_de_referencia(pd, ctx, cam, str(request.form.get("personagem") or ""),
                                       str(request.form.get("pedido") or ""), pid)
                out = {"capa_nova": r["capa"]["n"]}
                if request.form.get("gerar") == "1":
                    out["aviso"] = gerar_capa(pd, ctx, r["capa"]["n"]).get("aviso") or ""
                return out
            return _resp(pid, api_de(pid), f)

        def capa_gerar(pid: str, n: int):
            c = request.get_json(silent=True) or {}
            return _resp(pid, api_de(pid), lambda pd: gerar_capa(pd, _ctx(pid), n, str(c.get("quantidade") or "x1")))

        def capa_custom(pid: str):
            def f(pd):
                arqs = {}
                for campo, sub_ in (("fundo", "fundos"), ("personagem_img", "pers_fora")):
                    a = request.files.get(campo)
                    if a and a.filename:
                        arqs["fundo" if campo == "fundo" else "personagem"] = guardar_upload(pd, sub_, a.filename, a.read())
                try:
                    estilo = json.loads(request.form.get("estilo") or "{}")
                except ValueError:
                    estilo = {}
                ctx = _ctx(pid)
                if request.form.get("acao") == "montar" and not arqs and not _personagem_por_slug(ctx, str(request.form.get("personagem") or "")):
                    raise PubErro("Pra montar sem IA, envie a foto de fundo e/ou escolha uma personagem.")
                r = capa_personalizada(pd, ctx, {"descricao": request.form.get("descricao"), "texto": request.form.get("texto"),
                                                 "personagem": request.form.get("personagem"), "estilo": estilo}, arqs, pid)
                n = r["capa"]["n"]
                out = {"capa_nova": n}
                acao = request.form.get("acao") or ""
                if acao == "montar":
                    montar_sem_ia(pd, ctx, n)
                elif acao == "flow":
                    out["aviso"] = gerar_capa(pd, ctx, n, str(request.form.get("quantidade") or "x1")).get("aviso") or ""
                return out
            return _resp(pid, api_de(pid), f)

        def _ref_guia(pd: str, nome: str) -> str:
            cam = os.path.join(pasta(pd), "refs", os.path.basename(nome)) if nome else ""
            return cam if cam and os.path.isfile(cam) else ""

        def capa_desenho(pid: str):
            def f(pd):
                a = request.files.get("desenho")
                if not a:
                    raise PubErro("Desenhe a capa primeiro.")
                desenho = guardar_upload(pd, "desenhos", "d.png", a.read())
                try:
                    itens = json.loads(request.form.get("itens") or "[]")
                    estilo = json.loads(request.form.get("estilo") or "{}")
                except ValueError:
                    raise PubErro("Dados do desenho inválidos.")
                fotos = {}
                for chave in request.files:
                    if chave.startswith("foto_") and chave[5:].isdigit() and request.files[chave].filename:
                        fotos[int(chave[5:])] = guardar_upload(pd, "itens", request.files[chave].filename, request.files[chave].read())
                fa = request.files.get("fundo")
                fundo = guardar_upload(pd, "fundos", fa.filename, fa.read()) if fa and fa.filename else ""
                ctx = _ctx(pid)
                r = capa_de_desenho(pd, ctx, desenho, itens if isinstance(itens, list) else [], fotos,
                                    str(request.form.get("fundo_desc") or ""), fundo, str(request.form.get("texto") or ""),
                                    estilo, str(request.form.get("pedido") or ""), pid,
                                    ref=_ref_guia(pd, str(request.form.get("ref_guia") or "")))
                n = r["capa"]["n"]
                out = {"capa_nova": n}
                acao = request.form.get("acao") or ""
                if acao == "montar":
                    montar_sem_ia(pd, ctx, n)
                elif acao == "flow":
                    out["aviso"] = gerar_capa(pd, ctx, n, str(request.form.get("quantidade") or "x1")).get("aviso") or ""
                return out
            return _resp(pid, api_de(pid), f)

        def capa_copiar_modelo(pid: str):
            arq = request.files.get("imagem")

            def f(pd):
                if request.form.get("video_id"):  # 📊 uma thumb do canal analisado
                    cam = baixar_thumb_canal(pd, base, str(request.form.get("aid") or carregar(pd).get("canal_estilo") or ""),
                                             str(request.form["video_id"]))
                elif not arq or not arq.filename:
                    raise PubErro("Escolha a thumb pra copiar o modelo.")
                else:
                    cam = guardar_ref(pd, arq.filename, arq.read())
                m = copiar_modelo(pd, _ctx(pid), cam, str(request.form.get("pedido") or ""),
                                  request.form.get("preencher") == "1", pid)
                m["url_guia"] = f"{api_de(pid)}/ref_guia/{m['ref_guia']}"
                return {"modelo": m}
            return _resp(pid, api_de(pid), f)

        def ref_guia(pid: str, nome: str):
            cam = os.path.join(pasta(_pdir(pid)), "refs", os.path.basename(nome))
            return send_file(cam) if os.path.isfile(cam) else ("", 404)

        def canais(pid: str):
            return jsonify({"canais": canais_analisados(base)})

        def canal_estilo(pid: str):
            c = request.get_json(silent=True) or {}

            def f(pd):
                aid = str(c.get("aid") or "")
                if aid and not estilo_canal(base, aid):
                    raise PubErro("Análise de canal não encontrada.")
                with _TRAVA:
                    d = carregar(pd)
                    d["canal_estilo"] = aid or None
                    salvar(pd, d)
            return _resp(pid, api_de(pid), f)

        def capa_montar(pid: str, n: int):
            return _resp(pid, api_de(pid), lambda pd: montar_sem_ia(pd, _ctx(pid), n) and None)

        def capa_modificar(pid: str, n: int):
            c = request.get_json(silent=True) or {}
            return _resp(pid, api_de(pid), lambda pd: modificar_capa(pd, _ctx(pid), n, str(c.get("pedido") or ""),
                                                                     str(c.get("quantidade") or "x1")))

        def capa_editar(pid: str, n: int):
            c = request.get_json(silent=True) or {}

            def f(pd):
                if c.get("apagar"):
                    apagar_capa(pd, n)
                elif c.get("versao") is not None:
                    escolher_versao(pd, n, int(c["versao"]))
                else:
                    editar_capa(pd, n, c)
            return _resp(pid, api_de(pid), f)

        def capa_arquivo(pid: str, n: int, qual: str):
            try:
                pd = _pdir(pid)
            except PubErro:
                return "", 404
            if qual not in ("final", "ref", "imagem", "fundo", "pers_arquivo", "desenho"):
                return "", 404
            c = next((x for x in carregar(pd)["capas"] if int(x["n"]) == n), None)
            cam = (c or {}).get(qual)
            if not cam or not os.path.isfile(cam):
                return "", 404
            return send_file(cam, conditional=True, as_attachment=request.args.get("baixar") == "1",
                             download_name=f"capa_{n}{os.path.splitext(cam)[1]}")

        rota("", "estado", ["GET"], estado)
        rota("/textos", "textos", ["POST"], textos)
        rota("/textos/<tipo>/<int:idx>", "texto_editar", ["POST"], texto_editar)
        rota("/capas/ideias", "capas_ideias", ["POST"], capas_ideias)
        rota("/capas/referencia", "capa_ref", ["POST"], capa_ref)
        rota("/capas/<int:n>/gerar", "capa_gerar", ["POST"], capa_gerar)
        rota("/capas/personalizada", "capa_custom", ["POST"], capa_custom)
        rota("/capas/<int:n>/montar", "capa_montar", ["POST"], capa_montar)
        rota("/capas/desenho", "capa_desenho", ["POST"], capa_desenho)
        rota("/capas/copiar_modelo", "capa_copiar_modelo", ["POST"], capa_copiar_modelo)
        rota("/canais", "canais", ["GET"], canais)
        rota("/canal_estilo", "canal_estilo", ["POST"], canal_estilo)
        rota("/ref_guia/<nome>", "ref_guia", ["GET"], ref_guia)
        rota("/capas/<int:n>/modificar", "capa_modificar", ["POST"], capa_modificar)
        rota("/capas/<int:n>", "capa_editar", ["POST"], capa_editar)
        rota("/capa/<int:n>/<qual>", "capa_arquivo", ["GET"], capa_arquivo)

    _rotas("/job/<pid>/publicacao", "job", lambda pid: f"/job/{pid}/publicacao")
    _rotas("/publicacoes/<pid>/api", "hist", lambda pid: f"/publicacoes/{pid}/api")

    @app.route("/publicacao/fonte/<nome>", methods=["GET"])
    def publicacao_fonte(nome: str):
        """🔤 a fonte (pra prévia no seletor)."""
        nome = os.path.basename(nome)
        cam = os.path.join(PASTA_FONTES, nome)
        if not nome.endswith(".ttf") or not os.path.isfile(cam):
            return "", 404
        return send_file(cam, mimetype="font/ttf", max_age=86400)

    # 🗂 o histórico (menu 📣 Publicações)
    @app.route("/publicacoes", methods=["GET"])
    def publicacoes_lista():
        return render_template("publicacoes.html", itens=listar(base))

    @app.route("/publicacoes/<pid>", methods=["GET"])
    def publicacoes_pagina(pid: str):
        try:
            pd = pdir_de(base, pid)
        except PubErro:
            return "Publicação inválida.", 404
        job = obter(pid)
        if job:
            try:
                _ctx(pid)  # guarda a cópia do contexto
            except Exception:  # noqa: BLE001
                pass
        cx = carregar_ctx(pd)
        if not job and not cx:
            return redirect("/publicacoes")
        meta = dict(cx.get("meta") or {})
        meta["titulo"] = meta.get("titulo") or ((carregar(pd)["textos"].get("titulos") or [""])[0]) or ""
        return render_template("publicacao_pagina.html", pid=pid, meta=meta, tem_projeto=bool(job),
                               pub_api=f"/publicacoes/{pid}/api")

    @app.route("/publicacoes/<pid>/excluir", methods=["POST"])
    def publicacoes_excluir(pid: str):
        try:
            shutil.rmtree(pdir_de(base, pid), ignore_errors=True)
        except PubErro:
            pass
        return redirect("/publicacoes")
