"""🛡 v84_437 — FONTES QUE O SITE APRENDE: quais sites são confiáveis (e quais não), e os links de cada referência.

• Cada link que a 📚 Fontes da descrição confere fica registrado por SITE: quantas vezes passou, quantas falhou e por quê.
• Site que não está na lista fixa vira CANDIDATO (não entra sozinho). Na página 🛡 Fontes confiáveis você testa todos
  (estão no ar?), pede pra IA avaliar os candidatos (enciclopédia? blog? site de frases?) e decide: ✅ confiar / 🚫 bloquear.
  A decisão pode ser por site inteiro ("substack.com") ou por um pedaço do endereço ("fulano.substack.com",
  "site.com/autor/beltrano") — dá pra confiar nos textos de UMA pessoa sem liberar o site todo.
• REFERÊNCIAS LEMBRADAS: cada referência aprovada (autor + obra → link) fica guardada; no próximo roteiro que citar o
  mesmo autor/obra, o site tenta primeiro o link que já deu certo. Dá pra adicionar à mão ("Platão — Fédon" → link).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

BASE = os.environ.get("FONTES_CONFIANCA_DIR") or os.path.dirname(os.path.abspath(__file__))
ARQ = "fontes_confianca.json"
_TRAVA = threading.RLock()
NOTA_MIN_IA = 7  # a IA avaliou o site com nota ≥ 7 (e não é blog/frases/comercial) → vale como confiável


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s or "").lower()).encode("ascii", "ignore").decode()


def host_de(url_ou_host: str) -> str:
    h = urlparse(url_ou_host).netloc if "://" in str(url_ou_host) else str(url_ou_host or "")
    h = h.lower().split(":")[0]
    return h[4:] if h.startswith("www.") else h


def _caminho(base: Optional[str] = None) -> str:
    return os.path.join(base or BASE, ARQ)


def carregar(base: Optional[str] = None) -> Dict[str, Any]:
    try:
        with open(_caminho(base), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.setdefault("dominios", {})
    d.setdefault("referencias", {})
    d.setdefault("regras", {})  # "pedaço do endereço" → "confiar" | "bloquear"
    return d


def salvar(d: Dict[str, Any], base: Optional[str] = None) -> None:
    tmp = _caminho(base) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _caminho(base))


# ------------------------------------------------------------------ decisão
def _regra(url: str, d: Dict[str, Any]) -> str:
    """A regra mais específica que casa com o link ("confiar"/"bloquear"/"")."""
    h = host_de(url)
    alvo = h + (urlparse(url).path if "://" in str(url) else "")
    melhor, tam = "", -1
    for chave, dec in (d.get("regras") or {}).items():
        k = chave.lower().strip().rstrip("/")
        k = k[4:] if k.startswith("www.") else k
        casa = alvo.startswith(k) if "/" in k else (h == k or h.endswith("." + k))
        if casa and len(k) > tam:
            melhor, tam = dec, len(k)
    return melhor


def decidir(url: str, lista_fixa: bool, base: Optional[str] = None) -> str:
    """"confiar" | "bloquear" | "candidato" — a sua regra manda; depois a lista fixa; depois a nota da IA."""
    d = carregar(base)
    r = _regra(url, d)
    if r in ("confiar", "bloquear"):
        return r
    if lista_fixa:
        return "confiar"
    info = (d.get("dominios") or {}).get(host_de(url)) or {}
    if int(info.get("nota") or 0) >= NOTA_MIN_IA and info.get("tipo") not in ("blog", "frases", "comercial", "rede social",
                                                                               "resumo escolar", "desconhecido"):
        return "confiar"
    return "candidato"


def registrar(url: str, ok: bool, motivo: str = "", referencia: str = "", base: Optional[str] = None) -> None:
    """Guarda o resultado da conferência do link (por site)."""
    h = host_de(url)
    if not h:
        return
    with _TRAVA:
        d = carregar(base)
        x = d["dominios"].setdefault(h, {"ok": 0, "falha": 0, "motivos": [], "exemplos": []})
        x["ok" if ok else "falha"] = int(x.get("ok" if ok else "falha") or 0) + 1
        x["ultimo"] = time.time()
        if motivo:
            x["motivos"] = (x.get("motivos") or [])[-7:] + [motivo[:140]]
        if url not in (x.get("exemplos") or []):
            x["exemplos"] = (x.get("exemplos") or [])[-4:] + [url[:300]]
        if referencia and not ok and "confiável" in motivo:
            x["candidato"] = True
        try:
            salvar(d, base)
        except OSError:
            pass


def regra(chave: str, decisao: str, base: Optional[str] = None) -> Dict[str, Any]:
    chave = re.sub(r"^https?://", "", str(chave or "").strip().lower()).rstrip("/")
    if not chave or " " in chave or "." not in chave.split("/")[0]:
        raise ValueError("Escreva um site (ex.: plato.stanford.edu) ou um pedaço do endereço (ex.: fulano.substack.com).")
    with _TRAVA:
        d = carregar(base)
        if decisao in ("confiar", "bloquear"):
            d["regras"][chave] = decisao
        else:
            d["regras"].pop(chave, None)
        salvar(d, base)
        return d


# ------------------------------------------------------------------ referências lembradas
def chave_ref(referencia: str) -> str:
    """"Platão — Fédon (a filosofia…)" → "platao fedon" (autor + começo da obra, sem parênteses/aspas/ano)."""
    r = re.sub(r"\(.*?\)|[«»“”\"'’]", " ", str(referencia or ""))
    partes = [p.strip() for p in re.split(r"\s+[—–-]\s+", r) if p.strip()]
    autor = partes[0] if partes else ""
    obra = partes[1].split(",")[0] if len(partes) > 1 else ""
    pal = [w for w in re.findall(r"[a-z0-9]+", _norm(autor + " " + obra)) if len(w) > 2 and w not in ("das", "dos", "the", "les", "sobre")]
    return " ".join(pal[:6])


def lembrar(referencia: str, url: str, base: Optional[str] = None, manual: bool = False) -> None:
    k = chave_ref(referencia)
    if not k or not url:
        return
    with _TRAVA:
        d = carregar(base)
        x = d["referencias"].get(k) or {}
        if x.get("manual") and not manual and x.get("url") != url:
            return  # o que você pôs à mão não é trocado sozinho
        d["referencias"][k] = {"referencia": referencia[:240], "url": url[:600], "em": time.time(),
                               "usos": int(x.get("usos") or 0) + 1, "manual": bool(manual or x.get("manual"))}
        try:
            salvar(d, base)
        except OSError:
            pass


def lembrada(referencia: str, base: Optional[str] = None) -> Optional[Dict[str, Any]]:
    k = chave_ref(referencia)
    return (carregar(base).get("referencias") or {}).get(k) if k else None


def esquecer(chave: str, base: Optional[str] = None) -> None:
    with _TRAVA:
        d = carregar(base)
        d["referencias"].pop(chave, None)
        salvar(d, base)


# ------------------------------------------------------------------ 🔌 testar todos / 🤖 avaliar com a IA
def todos_os_sites(base: Optional[str] = None) -> List[Dict[str, Any]]:
    import fontes_web as fw
    d = carregar(base)
    hosts = set(fw.CONFIAVEIS) | set(d["dominios"]) | {k.split("/")[0] for k in d["regras"]}
    out = []
    for h in sorted(hosts):
        info = d["dominios"].get(h) or {}
        fixo = any(h == c or h.endswith("." + c) for c in fw.CONFIAVEIS) or bool(fw._RE_INSTITUCIONAL.search(h))
        url = "https://" + h + "/"
        out.append({"site": h, "fixo": fixo, "regra": d["regras"].get(h, ""), "decisao": decidir(url, fixo, base),
                    "ok": int(info.get("ok") or 0), "falha": int(info.get("falha") or 0),
                    "motivos": (info.get("motivos") or [])[-3:], "exemplos": (info.get("exemplos") or [])[-2:],
                    "nota": info.get("nota"), "tipo": info.get("tipo") or "", "por_que": info.get("por_que") or "",
                    "no_ar": info.get("no_ar"), "testado_em": info.get("testado_em"), "ms": info.get("ms")})
    for k, dec in d["regras"].items():  # regras por pedaço do endereço ("fulano.substack.com/posts")
        if "/" in k:
            out.append({"site": k, "fixo": False, "regra": dec, "decisao": dec, "ok": 0, "falha": 0, "motivos": [],
                        "exemplos": [], "nota": None, "tipo": "", "por_que": "", "no_ar": None, "testado_em": None, "ms": None})
    return out


def testar_todos(base: Optional[str] = None, progresso=None, baixar=None, so: Optional[List[str]] = None) -> Dict[str, int]:
    """Abre a página inicial de cada site (8 ao mesmo tempo): no ar? quanto demora?"""
    from concurrent.futures import ThreadPoolExecutor
    import fontes_web as fw
    sites = [s["site"] for s in todos_os_sites(base) if "/" not in s["site"] and (not so or s["site"] in so)]
    if baixar is None:
        import requests

        def baixar(u):
            return requests.get(u, headers={"User-Agent": fw.UA}, timeout=12, allow_redirects=True)
    res: Dict[str, Dict[str, Any]] = {}
    feitos = [0]

    def um(h):
        t0 = time.time()
        try:
            r = baixar("https://" + h + "/")
            st = int(getattr(r, "status_code", 0) or 0)
            no_ar = st < 400 or st in (401, 403, 429)  # 403/429 = no ar, mas barra robô
            res[h] = {"no_ar": no_ar, "status": st, "ms": int((time.time() - t0) * 1000)}
        except Exception as exc:  # noqa: BLE001
            res[h] = {"no_ar": False, "status": 0, "erro": str(exc)[:120], "ms": int((time.time() - t0) * 1000)}
        feitos[0] += 1
        if progresso:
            progresso(f"🔌 testando os sites… {feitos[0]} de {len(sites)}")
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(um, sites))
    with _TRAVA:
        d = carregar(base)
        for h, r in res.items():
            x = d["dominios"].setdefault(h, {"ok": 0, "falha": 0, "motivos": [], "exemplos": []})
            x.update(no_ar=r["no_ar"], status=r.get("status"), ms=r.get("ms"), testado_em=time.time(),
                     **({"erro_teste": r["erro"]} if r.get("erro") else {}))
        salvar(d, base)
    return {"testados": len(res), "no_ar": sum(1 for r in res.values() if r["no_ar"]),
            "fora": sum(1 for r in res.values() if not r["no_ar"])}


def avaliar_com_ia(base: Optional[str] = None, so: Optional[List[str]] = None, chamar=None) -> int:
    """A IA classifica os sites sem nota (os candidatos primeiro): tipo + nota 0–10 de confiabilidade como FONTE."""
    import ia_servico as ia
    sites = [s for s in todos_os_sites(base) if "/" not in s["site"] and (s["site"] in so if so else s["nota"] is None
                                                                       and not s["fixo"])]
    if not sites:
        return 0
    from ia_midia import _I, _S, _lista, _obj
    system = ("Você avalia SITES como FONTE de referência pra descrição de vídeos de filosofia, história e ciência. "
              "Para cada site diga o \"tipo\" — enciclopédia | acadêmico | biblioteca | universidade | governo | jornal | "
              "editora | divulgação séria | blog | frases | resumo escolar | rede social | comercial | desconhecido — e uma "
              "\"nota\" de 0 a 10: 9–10 = referência séria (revisão editorial/acadêmica); 7–8 = confiável; 4–6 = depende do "
              "autor; 0–3 = não usar (sites de frases sem fonte, resumo escolar, conteúdo gerado, opinião sem autoria). "
              "\"por_que\": 1 frase. Se não conhece o site, tipo \"desconhecido\" e nota 0. Responda só o JSON.")
    pedido = "Sites:\n" + "\n".join(f"- {s['site']}" + (f" (ex.: {s['exemplos'][-1]})" if s["exemplos"] else "") for s in sites[:60])
    with ia.rotulo("🛡 Avaliar sites das fontes"):
        r = (chamar or ia.chamar)("fontes_descricao", system, pedido,
                                  schema=_obj({"sites": _lista(_obj({"site": _S, "tipo": _S, "nota": _I, "por_que": _S}))}),
                                  max_tokens=4000, effort="low", timeout=300)
    n = 0
    with _TRAVA:
        d = carregar(base)
        for x in (r or {}).get("sites") or [] if isinstance(r, dict) else []:
            h = host_de(str(x.get("site") or ""))
            if not h:
                continue
            y = d["dominios"].setdefault(h, {"ok": 0, "falha": 0, "motivos": [], "exemplos": []})
            y.update(tipo=str(x.get("tipo") or "")[:30], nota=max(0, min(10, int(x.get("nota") or 0))),
                     por_que=str(x.get("por_que") or "")[:200], avaliado_em=time.time())
            n += 1
        salvar(d, base)
    return n
