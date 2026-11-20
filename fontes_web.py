"""📚 v84_432 — FONTES NA DESCRIÇÃO: cada roteiro sai com os links das referências históricas que ele usa.

1. A IA (com busca na internet) lê o roteiro e lista as referências históricas/factuais — citações (autor + obra), obras,
   eventos, estudos — com UM link pra cada uma e os termos que a página TEM que ter (o nome do autor, o título da obra).
2. O site abre cada link: tem que estar no ar (sem 404, sem "página não encontrada", sem cair na home) e a página tem que
   falar daquilo (os termos aparecem no título/texto). O que não passa volta pra IA achar outro link (1 rodada a mais).
3. Os aprovados entram na descrição em "📚 Fontes e referências" (a fala cita só autor + obra; ano e página ficam aqui).
"""
from __future__ import annotations

import html as _html
import re
import time
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

RECURSO = "fontes_descricao"
MAX_FONTES = 12
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# sites sérios que barram robôs (403): vale se o próprio link já traz o assunto (ex.: /biography/Louis-Lavelle)
BLOQUEIAM_ROBO = ("britannica.com", "jstor.org", "cambridge.org", "oup.com", "academic.oup.com", "persee.fr",
                  "cairn.info", "philpapers.org", "researchgate.net", "springer.com", "tandfonline.com")
_SOFT_404 = re.compile(r"\b(404|not found|page not found|p[aá]gina n[aã]o (encontrada|existe)|introuvable|no encontrada|"
                       r"error|erro|does not exist|n[aã]o existe)\b", re.I)
# 🛡 fontes CONFIÁVEIS: só entram links destes sites (ou de universidades, governos e instituições oficiais)
CONFIAVEIS = (
    # enciclopédias e obras de referência
    "plato.stanford.edu", "iep.utm.edu", "britannica.com", "wikipedia.org", "treccani.it", "larousse.fr",
    "encyclopedia.com", "newadvent.org", "rae.es", "dbe.rah.es", "deutsche-biographie.de", "oxfordreference.com",
    # as próprias obras / bibliotecas e arquivos
    "gutenberg.org", "wikisource.org", "archive.org", "gallica.bnf.fr", "bnf.fr", "perseus.tufts.edu",
    "cervantesvirtual.com", "dominiopublico.gov.br", "bn.gov.br", "bndigital.bn.gov.br", "loc.gov", "bl.uk",
    "europeana.eu", "hathitrust.org", "vatican.va", "biblioteca.org.ar",
    # revistas e editoras acadêmicas
    "jstor.org", "persee.fr", "cairn.info", "philpapers.org", "cambridge.org", "oup.com", "springer.com",
    "tandfonline.com", "sciencedirect.com", "nature.com", "science.org", "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov",
    "scielo.br", "scielo.org", "doi.org", "wiley.com", "sagepub.com", "apa.org", "nobelprize.org",
    # jornalismo e divulgação sérios
    "bbc.com", "bbc.co.uk", "nytimes.com", "theguardian.com", "reuters.com", "apnews.com", "folha.uol.com.br",
    "estadao.com.br", "oglobo.globo.com", "elpais.com", "lemonde.fr", "smithsonianmag.com", "nationalgeographic.com",
    "scientificamerican.com", "theatlantic.com", "economist.com",
)
_RE_INSTITUCIONAL = re.compile(r"((^|\.)(edu|gov|mil|int)(\.[a-z]{2})?|(^|\.)(ac|gob)\.[a-z]{2}|\.gouv\.fr|\.museum|"
                               r"(^|\.)(usp|unicamp|unesp|unifesp|unb|fgv|puc[a-z-]*|uf[a-z]{1,5}|unirio|uerj|uel|uem)\.br)$")


def confiavel(host: str) -> bool:
    h = (host or "").lower().split(":")[0]
    h = h[4:] if h.startswith("www.") else h
    return any(h == c or h.endswith("." + c) for c in CONFIAVEIS) or bool(_RE_INSTITUCIONAL.search(h))


_PROIBIDOS_URL = ("google.", "goodreads.com", "pensador.com", "citador.pt", "bing.com", "duckduckgo.", "youtube.com", "youtu.be", "amazon.", "mercadolivre.",
                  "facebook.com", "instagram.com", "tiktok.com", "pinterest.", "x.com", "twitter.com")


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s or "").lower()).encode("ascii", "ignore").decode()


def _schema() -> Dict[str, Any]:
    from ia_midia import _S, _lista, _obj
    return _obj({"fontes": _lista(_obj({"referencia": _S, "url": _S, "trecho": _S, "termos": _lista(_S)}))})


def system(nomes_proibidos: Optional[List[str]] = None) -> str:
    proib = ("\n- NUNCA inclua nem cite: " + ", ".join(nomes_proibidos) + ".") if nomes_proibidos else ""
    return f"""Você monta as FONTES da descrição de um vídeo do YouTube. Leia o roteiro e liste as referências HISTÓRICAS e
factuais que ele usa: citações de autores (com a obra), obras citadas, poemas, diálogos, eventos e datas, experimentos e
estudos, dados. Para CADA uma, PESQUISE NA INTERNET e dê UM link que:
1. está no ar AGORA (você abriu e viu a página);
2. fala EXATAMENTE daquilo — a página da obra, do autor naquele assunto, do evento, do estudo. Nada de página inicial de
   site, resultado de busca, loja, rede social ou vídeo do YouTube;
3. é de FONTE CONFIÁVEL — SÓ destas: enciclopédias (Stanford Encyclopedia of Philosophy, Internet Encyclopedia of
   Philosophy, Britannica, Wikipedia, Treccani, Larousse), a própria obra em bibliotecas e arquivos (Projeto Gutenberg,
   Wikisource, Internet Archive, Gallica/BnF, Domínio Público, Biblioteca Nacional), revistas e editoras acadêmicas
   (JSTOR, SciELO, Cambridge, Oxford, Springer, PubMed, DOI), sites de universidades e governos (.edu, .gov, .ac.uk, USP,
   Unicamp…) e jornais sérios (BBC, NYT, Guardian, Reuters, Folha, Estadão, El País, Le Monde). NUNCA: blogs, sites de
   frases e citações (Pensador, Citador, Goodreads), sites de resumo escolar, Brainly, Quora, Reddit, Medium, Scribd.
   Para uma obra, o texto dela (Gutenberg/Wikisource/Archive) ou a página dela numa enciclopédia é o melhor.
Prefira a página em português quando houver uma boa; senão, inglês ou a língua original.
NÃO entram: ideias do próprio narrador, exemplos inventados ("imagine…", "pense numa pessoa…"), opiniões.
Junte o que é a mesma referência (a mesma obra citada duas vezes = 1 fonte). No máximo {MAX_FONTES}.{proib}
Campos de cada fonte:
- "referencia": como vai aparecer na descrição, completa (ex.: "Louis Lavelle — De l'intimité spirituelle (1955), «Témoignage», p. 281";
  "Platão — Fédon (a filosofia como preparação para a morte)"; "Antonio Machado — «Retrato», em Campos de Castilla (1912)");
- "url": o link;
- "trecho": a frase do roteiro que usa essa referência (curta, copiada do roteiro);
- "termos": 2 a 4 palavras que aparecem NA PÁGINA do link, ESCRITAS COMO NA PÁGINA (na língua dela: numa página em inglês,
  "Spinoza", não "Espinosa"). O 1º termo é SEMPRE o nome principal (o sobrenome do autor ou o nome do evento/obra).
Responda só o JSON."""


def pedir(roteiro: str, titulo: str = "", rejeitados: Optional[List[Dict[str, Any]]] = None,
          nomes_proibidos: Optional[List[str]] = None, chamar=None) -> List[Dict[str, Any]]:
    import ia_servico as ia
    chamar = chamar or ia.chamar
    conteudo = (f"Título do vídeo: {titulo}\n\n" if titulo else "") + "ROTEIRO:\n" + str(roteiro or "")[:60000]
    try:  # 🛡 v84_437: os sites que você aprovou (ou que a IA avaliou bem) também valem — e os bloqueados, nunca
        import fontes_confianca as fc
        d = fc.carregar()
        extras = [k for k, v in d["regras"].items() if v == "confiar"] + [
            h for h, x in d["dominios"].items() if int(x.get("nota") or 0) >= fc.NOTA_MIN_IA and h not in d["regras"]]
        bloq = [k for k, v in d["regras"].items() if v == "bloquear"]
        if extras:
            conteudo += "\n\nSITES QUE TAMBÉM VALEM (aprovados): " + ", ".join(extras[:40])
        if bloq:
            conteudo += "\nSITES PROIBIDOS: " + ", ".join(bloq[:40])
    except Exception:  # noqa: BLE001
        pass
    if rejeitados:
        conteudo += ("\n\nESTES LINKS NÃO SERVEM (fora do ar ou não falam do assunto) — ache OUTRO link só para estas "
                     "referências e devolva só elas:\n" + "\n".join(f"- {r['referencia']} — {r.get('url') or ''} ({r['motivo']})"
                                                                    for r in rejeitados))
    with ia.rotulo("📚 Fontes da descrição: " + (titulo or "")[:60]):
        d = chamar(RECURSO, system(nomes_proibidos), conteudo, schema=_schema(), max_tokens=6000, effort="low",
                   timeout=600, web=True)
    out = []
    for x in (d or {}).get("fontes") or [] if isinstance(d, dict) else []:
        ref = " ".join(str(x.get("referencia") or "").split())[:240]
        url = str(x.get("url") or "").strip()
        if ref and url.startswith(("http://", "https://")):
            out.append({"referencia": ref, "url": url[:600], "trecho": str(x.get("trecho") or "")[:240],
                        "termos": [str(t)[:60] for t in x.get("termos") or [] if str(t).strip()][:5]})
    return out[:MAX_FONTES]


# ------------------------------------------------------------------ conferir o link
def _texto_html(h: str) -> Tuple[str, str]:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", h)
    titulo = _html.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""
    corpo = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", h)
    corpo = _html.unescape(re.sub(r"<[^>]+>", " ", corpo))
    return titulo, re.sub(r"\s+", " ", corpo)


# 🩹 v84_436: o mesmo nome em outras línguas (a página em inglês diz "Spinoza", o roteiro diz "Espinosa")
NOMES_OUTRAS_LINGUAS = {
    "espinosa": ["spinoza", "espinoza", "spinoza"], "platao": ["plato", "platon", "platone"], "aristoteles": ["aristotle", "aristote"],
    "socrates": ["socrate"], "agostinho": ["augustine", "augustin", "agostino", "augustinus"], "aquino": ["aquinas", "aquin"],
    "epicteto": ["epictetus", "epictete"], "seneca": ["seneque"], "marco aurelio": ["marcus aurelius", "marc aurele"],
    "epicuro": ["epicurus", "epicure"], "heraclito": ["heraclitus", "heraclite"], "parmenides": ["parmenide"],
    "pitagoras": ["pythagoras", "pythagore"], "confucio": ["confucius"], "tales": ["thales"], "plotino": ["plotinus", "plotin"],
    "boecio": ["boethius", "boece"], "anselmo": ["anselm"], "ockham": ["occam"], "maquiavel": ["machiavelli", "machiavel"],
    "rousseau": [], "descartes": [], "pascal": [], "kant": [], "hegel": [], "schopenhauer": [], "nietzsche": [],
    "kierkegaard": [], "berkeley": [], "hume": [], "locke": [], "hobbes": [], "montaigne": [], "voltaire": [],
    "tomas": ["thomas"], "joao": ["john", "jean", "johann"], "guilherme": ["william", "wilhelm"], "luis": ["louis", "luigi"],
    "francisco": ["francis", "francois", "franz"], "jose": ["jose", "josep", "joseph"], "homero": ["homer", "homere"],
    "virgilio": ["virgil", "virgile"], "ovidio": ["ovid", "ovide"], "dante": [], "camoes": ["camoens"], "erasmo": ["erasmus", "erasme"],
}


def _variantes(t: str) -> List[str]:
    n = _norm(t).strip()
    out = [n] + NOMES_OUTRAS_LINGUAS.get(n, [])
    for pt, outras in NOMES_OUTRAS_LINGUAS.items():
        if n in outras:
            out.append(pt)
    return [x for x in dict.fromkeys(out) if x]


def _principal(f: Dict[str, Any]) -> str:
    """O nome principal: o 1º termo, ou o que vem antes do " — " na referência (o autor)."""
    ts = [t for t in f.get("termos") or [] if len(_norm(t)) >= 3]
    if ts:
        return ts[0]
    autor = re.split(r"\s+[—–-]\s+", f.get("referencia") or "")[0]
    nomes = re.findall(r"\b[A-ZÀ-Ý][\wÀ-ÿ'-]{2,}", autor)
    return nomes[-1] if nomes else autor


def _tem(t: str, alvo: str) -> int:
    """Quantas vezes o termo (ou o mesmo nome em outra língua) aparece; nomes compostos valem pela última palavra."""
    best = 0
    for v in _variantes(t):
        best = max(best, alvo.count(v))
        partes = v.split()
        if len(partes) > 1 and len(partes[-1]) >= 4:
            best = max(best, alvo.count(partes[-1]))
    return best


def _termos(f: Dict[str, Any]) -> List[str]:
    ts = [t for t in f.get("termos") or [] if len(_norm(t)) >= 3]
    if not ts:  # sem termos: os nomes próprios da referência
        ts = re.findall(r"\b[A-ZÀ-Ý][\wÀ-ÿ'-]{3,}", f.get("referencia") or "")[:3]
    return ts


def conferir(f: Dict[str, Any], baixar: Optional[Callable[[str], Any]] = None) -> Tuple[bool, str, str]:
    """(ok, motivo, título da página)."""
    url = f.get("url") or ""
    u = urlparse(url)
    host = (u.netloc or "").lower()
    if not host or any(b in host for b in _PROIBIDOS_URL):
        return False, "não é página de referência (busca, loja, rede social ou vídeo)", ""
    import fontes_confianca as fc  # 🛡 v84_437: a lista fixa + as suas decisões + o que a IA avaliou
    dec = fc.decidir(url, confiavel(host))
    if dec == "bloquear":
        return False, f"{host} está bloqueado (🛡 Fontes confiáveis)", ""
    if dec != "confiar":
        return False, (f"{host} ainda não é fonte confiável — ficou como candidato em 🛡 Fontes confiáveis (teste, avalie "
                       "e decida lá)"), ""
    if u.path in ("", "/") and not u.query:
        return False, "é a página inicial do site, não a página do assunto", ""
    if baixar is None:
        import requests

        def baixar(x):
            return requests.get(x, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
                                timeout=15, allow_redirects=True)
    try:
        r = baixar(url)
    except Exception as exc:  # noqa: BLE001
        return False, f"não abriu ({str(exc)[:80]})", ""
    st = int(getattr(r, "status_code", 0) or 0)
    termos = _termos(f)
    no_link = _norm(url).replace("-", " ").replace("_", " ").replace("%20", " ")
    if st in (401, 403, 429, 503) and any(host.endswith(b) for b in BLOQUEIAM_ROBO):
        if termos and any(_norm(t) in no_link for t in termos):
            return True, "", ""
        return False, f"o site barrou a conferência ({st})", ""
    if st >= 400 or st == 0:
        return False, f"fora do ar (erro {st})", ""
    final = urlparse(str(getattr(r, "url", "") or url))
    if final.path in ("", "/") and u.path not in ("", "/"):
        return False, "o link caiu na página inicial (a página não existe mais)", ""
    tipo = str((getattr(r, "headers", {}) or {}).get("content-type") or "").lower()
    if "pdf" in tipo:  # PDF no ar: o texto não dá pra ler aqui — vale por estar no ar
        return True, "", ""
    titulo, corpo = _texto_html(str(getattr(r, "text", "") or "")[:800_000])
    if _SOFT_404.search(titulo) and len(corpo) < 4000:
        return False, f"página de erro (“{titulo[:60]}”)", titulo
    alvo = _norm(titulo + " " + corpo[:400_000])
    # 🩹 v84_436: antes exigia metade dos termos (em português, numa página em inglês: "faltam: Espinosa, imaginação…").
    # Agora: o NOME PRINCIPAL (autor/obra/evento, em qualquer língua) está no título da página ou aparece 3+ vezes no texto —
    # ou aparece 1+ vez junto com outro termo.
    nome = _principal(f)
    no_titulo = _tem(nome, _norm(titulo)) > 0
    vezes = _tem(nome, alvo)
    outros = sum(1 for t in termos[1:] if _tem(t, alvo))
    if not (no_titulo or vezes >= 3 or (vezes >= 1 and outros >= 1)):
        return False, f"a página não fala de {nome}" + (f" (só cita {vezes} vez)" if vezes else ""), titulo
    return True, "", titulo


# ------------------------------------------------------------------ 🩹 v84_436: sem link bom → a Wikipedia do autor/obra
def _wikipedia(f: Dict[str, Any], baixar) -> Optional[Dict[str, Any]]:
    import json as _json
    from urllib.parse import quote
    ref = f.get("referencia") or ""
    partes = [x.strip() for x in re.split(r"\s+[—–]\s+", ref) if x.strip()]
    obra = re.sub(r"\s*\(.*?\)|[«»“”\"]", "", partes[1]).split(",")[0].strip() if len(partes) > 1 else ""
    buscas = [b for b in (obra, partes[0] if partes else "") if b and len(b) >= 3]
    for busca in buscas:
        for lang in ("pt", "en"):
            try:
                r = baixar(f"https://{lang}.wikipedia.org/w/api.php?action=opensearch&limit=1&namespace=0&format=json"
                           f"&search={quote(busca)}")
                d = r.json() if hasattr(r, "json") else _json.loads(getattr(r, "text", "") or "[]")
                url = (d[3] or [None])[0] if isinstance(d, list) and len(d) > 3 else None
            except Exception:  # noqa: BLE001
                url = None
            if not url:
                continue
            autor = _principal(dict(f, termos=[]))
            g = dict(f, url=url, termos=[obra, autor] if busca == obra else [autor])  # a página da obra cita a obra e o autor
            ok, _m, tit = conferir(g, baixar)
            if ok:
                return dict(g, titulo_pagina=tit[:160], conferido_em=time.time(), wikipedia=True)
    return None


# ------------------------------------------------------------------ o processo todo
def gerar(roteiro: str, titulo: str = "", nomes_proibidos: Optional[List[str]] = None, progresso=None,
          chamar=None, baixar=None) -> Dict[str, Any]:
    import fontes_confianca as fc
    prog = progresso or (lambda m: None)
    prog("📚 a IA está procurando as fontes do roteiro…")
    candidatos = pedir(roteiro, titulo, nomes_proibidos=nomes_proibidos, chamar=chamar)
    nomes = [_norm(n) for n in nomes_proibidos or []]
    aprovados: List[Dict[str, Any]] = []
    rejeitados: List[Dict[str, Any]] = []
    vistos = set()
    for rodada in range(2):
        rej_rodada = []
        for k, f in enumerate(candidatos, 1):
            if any(n and n in _norm(f["referencia"]) for n in nomes):
                continue
            if f["url"] in vistos:
                continue
            vistos.add(f["url"])
            prog(f"🔗 conferindo o link {k} de {len(candidatos)}…")
            mem = fc.lembrada(f["referencia"])  # 🧠 v84_437: essa referência já teve um link aprovado → tenta ele primeiro
            if mem and mem.get("url") and mem["url"] != f["url"] and mem["url"] not in vistos:
                vistos.add(mem["url"])
                g = dict(f, url=mem["url"])
                ok, motivo, tit = conferir(g, baixar)
                fc.registrar(g["url"], ok, motivo, g["referencia"])
                if ok:
                    if not any(a["referencia"].lower() == f["referencia"].lower() for a in aprovados):
                        aprovados.append(dict(g, titulo_pagina=tit[:160], conferido_em=time.time(), lembrada=True))
                    fc.lembrar(f["referencia"], g["url"])
                    continue
            ok, motivo, tit = conferir(f, baixar)
            fc.registrar(f["url"], ok, motivo, f["referencia"])
            if ok:
                if not any(a["referencia"].lower() == f["referencia"].lower() for a in aprovados):
                    aprovados.append(dict(f, titulo_pagina=tit[:160], conferido_em=time.time()))
                fc.lembrar(f["referencia"], f["url"])
            else:
                rej_rodada.append(dict(f, motivo=motivo))
        rejeitados += rej_rodada
        falta = [r for r in rej_rodada if not any(a["referencia"].lower() == r["referencia"].lower() for a in aprovados)]
        if rodada or not falta or len(aprovados) >= MAX_FONTES:
            break
        prog(f"🔁 {len(falta)} link(s) não serviram — a IA vai procurar outros…")
        candidatos = pedir(roteiro, titulo, rejeitados=falta, nomes_proibidos=nomes_proibidos, chamar=chamar)
    ok_refs = {a["referencia"].lower() for a in aprovados}
    # 🩹 v84_436: o que ficou sem link → a página da obra (ou do autor) na Wikipedia, conferida do mesmo jeito
    sem = []
    for r in rejeitados:
        if r["referencia"].lower() in ok_refs or r["referencia"].lower() in {x["referencia"].lower() for x in sem}:
            continue
        sem.append(r)
    b = baixar
    if b is None:
        import requests

        def b(x):
            return requests.get(x, headers={"User-Agent": UA}, timeout=15, allow_redirects=True)
    for r in sem:
        if len(aprovados) >= MAX_FONTES:
            break
        prog(f"📚 procurando {r['referencia'][:50]} na Wikipedia…")
        w = _wikipedia(r, b)
        if w and w["url"] not in {a["url"] for a in aprovados}:
            aprovados.append(w)
            ok_refs.add(r["referencia"].lower())
            fc.lembrar(r["referencia"], w["url"])
    return {"itens": aprovados[:MAX_FONTES], "em": time.time(),
            "sem_link": [{"referencia": r["referencia"], "url": r.get("url"), "motivo": r["motivo"]}
                         for r in sem if r["referencia"].lower() not in ok_refs][:20]}


def bloco(fw: Optional[Dict[str, Any]]) -> str:
    itens = (fw or {}).get("itens") or []
    if not itens:
        return ""
    return "📚 Fontes e referências:\n" + "\n".join(f"- {i['referencia']}: {i['url']}" for i in itens)


def para_projeto(base: str, pid: str, trava=None, progresso=None) -> Dict[str, Any]:
    """Gera e grava em resultado["fontes_web"] (só essa chave — o resto do projeto pode estar mudando ao mesmo tempo)."""
    import contextlib
    import dossies as ds
    import metodo_roteiro as mr
    trava = trava or contextlib.nullcontext()
    p = ds.carregar(base, pid)
    res = p.get("resultado") or {}
    rot = res.get("roteiro_final") or res.get("roteiro") or ""
    if not rot.strip():
        raise ValueError("ainda não tem roteiro")
    fw = gerar(rot, (p.get("config") or {}).get("titulo") or p.get("tema") or "", mr.nomes_proibidos(p.get("config")),
               progresso=progresso)
    with trava:
        p = ds.carregar(base, pid)
        p.setdefault("resultado", {})["fontes_web"] = fw
        ds.salvar(base, p)
    return fw


def ao_gerar_roteiro(base: str, pid: str, trava=None) -> Optional[str]:
    """Depois de um roteiro novo: procura as fontes em segundo plano (se o recurso está ligado)."""
    import ia_servico as ia
    if not ia.ativo(RECURSO):
        return None
    import tarefas_bg
    return tarefas_bg.iniciar("fontes_web", "📚 Fontes da descrição", lambda t: para_projeto(base, pid, trava, t.progresso),
                              pagina=f"/modelos-video/{pid}", avisar=False)
