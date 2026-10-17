"""
🔎 checagem_roteiro.py — CHECAGEM de precisão e consistência do roteiro inteiro (v84_99)
======================================================================================

Depois da revisão de estilo, uma passada de "checador de fatos / continuidade" pra evitar furos de roteiro:

1. O SITE analisa sozinho (sem IA, na hora):
   • repetições — parágrafos distantes que contam a mesma coisa (ex.: linha 63 ≈ linha 97: a carta de Grans contada 2×);
   • temas que voltam demais (ex.: "Informant" em 11 parágrafos) — a relação X × polícia explicada várias vezes;
   • começos de frase repetidos e fórmulas de análise („Eine mögliche Lesart ist“ 3×);
   • frases-fragmento („Mit der Guillotine.“) — funcionam 1–2×, cansam quando viram tique;
   • datas e números citados, com a linha de cada um — pra ver "informante ab 1924" × "informante em 1918" e
     24 × 27 × 50–70 (condenado × acusado × o que ele alegou).
   As linhas são as do roteiro (1ª linha = 1), como num editor de texto.
   • ⏳ cronologia: a linha do tempo do roteiro e os conflitos "desde ANO" × trecho de antes daquele ano.
2. O PROMPT tem SÓ TRÊS FOCOS — ⏳ cronologia, 📚 checagem das alegações históricas (contra as fontes do projeto;
   fato × alegação; condenado × acusado × alegado) e ✂️ corte de repetições — e pede as CORREÇÕES como trocas
   {"de", "para"} (o site aplica, como na 🪄 revisão), a linha do tempo e a lista do que precisa ser CONFERIDO fora
   (citar uma fonte no texto não confirma a afirmação).
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from itertools import combinations
import math
from typing import Any, Dict, List, Optional, Tuple

# palavras muito comuns (pt, de, en, es) — não contam como "assunto" do parágrafo
_STOP = set("""
a o as os um uma uns umas de do da dos das e é em no na nos nas por para pra com sem que se não mais mas como foi era eram
ser seu sua seus suas ele ela eles elas isso isto esse essa este esta aquele aquela ao aos à às já também ainda só quando
onde porque pois muito muitos muita pouco tudo nada ter tinha tinham havia hoje sobre entre até depois antes mesmo então
der die das und ein eine einer eines einem einen nicht sich mit von den dem des auf für ist war waren wurde wurden hatte
hatten haben sein seine seiner seinen seinem ihm ihn ihr ihre ihren sie er es man wie was wer als auch noch nur oder aber
doch dass bis zum zur nach über unter durch beim im in an am aus bei so da dann wenn denn weil diese dieser dieses diesen
jetzt schon sehr mehr viele kein keine keinen immer wieder heute damals einmal etwas alle allen ganz gegen ohne vor wird
the and of to in is was were that this with for on as by at from it he she they his her their had have has be been not
but or which who what when where why how there than then also more most into out about after before only very
el la los las un una y en que se con por para es fue era su sus lo le les del al como pero más
""".split())

FORMULAS = [
    # de
    "Eine mögliche Lesart", "Verschiedene Lesarten", "Man muss sich fragen", "Man muss an dieser Stelle", "Man muss sich das",
    "Hier liegt die eigentliche Frage", "Hier muss man genau bleiben", "Und genau hier", "Eine Frage bleibt",
    "Was bleibt, ist", "Und hier schließt sich ein Kreis", "Eines steht fest", "Entscheidend ist",
    # pt
    "Uma leitura possível", "Uma possível leitura", "É preciso ter cuidado", "Aqui está a verdadeira questão",
    "Aqui está a questão", "Resta uma pergunta", "O que fica é", "É preciso se perguntar", "Uma coisa é certa",
    # en / es
    "One possible reading", "Here lies the real question", "We have to be careful", "One question remains",
    "Una lectura posible", "Aquí está la verdadera pregunta",
]

_MARCA = re.compile(r"^\s*\[\[[^\]]*\]\]\s*$")
_FRASE = re.compile(r"[^.!?…]+[.!?…]+[“”\"»«’']?|[^.!?…]+$")


def _sem_marcas(s: str) -> str:
    return re.sub(r"\[\[[^\]]*\]\]|\[[^\]]*\]", " ", s)


def paragrafos(texto: str) -> List[Tuple[int, str]]:
    """(nº da linha, texto) de cada parágrafo narrado (sem as linhas de marca [[…]])."""
    out = []
    for i, linha in enumerate(str(texto or "").split("\n"), 1):
        if linha.strip() and not _MARCA.match(linha):
            out.append((i, linha.strip()))
    return out


def _tokens(s: str) -> List[str]:
    return [w for w in re.findall(r"[^\W\d_]+", _sem_marcas(s).lower()) if len(w) >= 4 and w not in _STOP]


def _raiz(w: str) -> str:
    return w[:7]


def frases(s: str) -> List[str]:
    t = re.sub(r"\b(\d{1,2})\.(?=\s+\S)", r"\1§", _sem_marcas(s))  # "19. Dezember" não termina a frase
    return [f.strip().replace("§", ".") for f in _FRASE.findall(t) if f.strip()]


def _trecho(s: str, n: int = 12) -> str:
    p = s.split()
    return " ".join(p[:n]) + ("…" if len(p) > n else "")


# ------------------------------------------------------------------ análise local (sem IA)
def chave_par(ta: str, tb: str) -> str:
    """Id estável de um par de parágrafos (pra lembrar "não é repetição")."""
    import hashlib
    norm = lambda t: re.sub(r"\W+", " ", _sem_marcas(t).lower()).strip()[:160]
    return hashlib.md5((norm(ta) + "|" + norm(tb)).encode()).hexdigest()[:12]


def analisar(texto: str, tema: str = "", ignorar: Optional[set] = None) -> Dict[str, Any]:
    pars = paragrafos(texto)
    raizes = {n: {_raiz(w) for w in _tokens(t)} for n, t in pars}
    # v84_156: as palavras que estão em MUITOS parágrafos (os nomes do caso, a cidade, o assunto) não contam pra
    # "repetição" — antes 2 parágrafos que só citavam Sheri, Robert, Schultz e Michigan viravam "par parecido"
    if len(raizes) >= 8:
        _df = Counter(r for rs in raizes.values() for r in rs)
        _muito = {r for r, c in _df.items() if c > max(3, len(raizes) * 0.22)}
        raizes_rep = {n: rs - _muito for n, rs in raizes.items()}
    else:
        raizes_rep = raizes
    formas: Dict[str, Counter] = defaultdict(Counter)
    for _n, t in pars:
        for w in re.findall(r"[^\W\d_]+", _sem_marcas(t)):
            if len(w) >= 4 and w.lower() not in _STOP:
                formas[_raiz(w.lower())][w] += 1

    # 1) repetições: parágrafos distantes com o mesmo assunto (semelhança das palavras de conteúdo)
    linhas = [n for n, _t in pars]
    pos = {n: i for i, n in enumerate(linhas)}
    pares = []
    for a, b in combinations(linhas, 2):
        ta, tb = raizes_rep[a], raizes_rep[b]
        if len(ta) < 6 or len(tb) < 6 or pos[b] - pos[a] < 3:
            continue
        comum = ta & tb
        nota = len(comum) / math.sqrt(len(ta) * len(tb))
        if nota >= 0.2 and len(comum) >= 4:
            pares.append((nota, a, b, comum))
    pares.sort(key=lambda x: -x[0])
    texto_de = dict(pars)
    repeticoes, usos = [], Counter()
    for nota, a, b, comum in pares:
        if nota < 0.26 or len(comum) < 5 or usos[a] >= 2 or usos[b] >= 2:
            continue
        ch_par = chave_par(texto_de[a], texto_de[b])
        if ignorar and ch_par in ignorar:
            continue
        usos[a] += 1
        usos[b] += 1
        repeticoes.append({"a": a, "b": b, "chave": ch_par, "nota": round(nota, 2), "trecho_a": _trecho(texto_de[a]), "trecho_b": _trecho(texto_de[b]),
                           "palavras": sorted((formas[r].most_common(1)[0][0] for r in comum), key=str.lower)[:10]})
        if len(repeticoes) >= 15:
            break

    # 2) assuntos que voltam: palavras (não banais) que ligam MUITOS pares de parágrafos parecidos
    do_tema = {_raiz(w) for w in _tokens(tema)}
    df = Counter(r for n in linhas for r in raizes[n])
    teto = max(4, int(len(linhas) * 0.2))
    liga = Counter(r for _nota, a, b, comum in pares for r in comum if r not in do_tema and len(r) >= 6 and 3 <= df[r] <= teto)
    temas = []
    for r, c in liga.most_common(6):
        if c < 4:
            break
        onde = [n for n in linhas if r in raizes[n]]
        temas.append({"palavra": formas[r].most_common(1)[0][0], "paragrafos": len(onde), "linhas": onde[:30]})

    # 3) fórmulas e começos de frase repetidos
    todas = [(n, f) for n, t in pars for f in frases(t)]
    baixo = texto.lower()
    formulas = [{"texto": f, "vezes": baixo.count(f.lower())} for f in FORMULAS if baixo.count(f.lower()) >= 1]
    formulas = sorted(formulas, key=lambda f: -f["vezes"])
    inicios = Counter(" ".join(f.split()[:3]) for _n, f in todas if len(f.split()) >= 5)
    comecos = [{"texto": k, "vezes": v} for k, v in inicios.most_common(12) if v >= 3]

    # 4) frases-fragmento (até 3 palavras, sem ser pergunta)
    fragmentos = [{"linha": n, "texto": f} for n, f in todas if len(f.split()) <= 3 and not f.endswith("?")]

    # 5) seções que terminam em pergunta (gancho) — demais vira enchimento
    perguntas_fim = [n for n, t in pars if (frases(t) or [""])[-1].endswith("?")]

    # 6) datas e números
    datas: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    numeros: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for n, f in todas:
        for m in re.finditer(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3})*|\d+)(?![\d])", f):
            v = m.group(1)
            ctx = {"linha": n, "frase": f[:220]}
            if re.fullmatch(r"1[5-9]\d\d|20[0-4]\d", v):
                datas[v].append(ctx)
            else:
                numeros[v].append(ctx)
    datas_l = [{"valor": k, "vezes": len(v), "onde": v[:8]} for k, v in sorted(datas.items())]
    nums_l = sorted([{"valor": k, "vezes": len(v), "onde": v[:8]} for k, v in numeros.items()], key=lambda x: -x["vezes"])[:20]

    return {"paragrafos": len(pars), "repeticoes": repeticoes, "temas": temas, "formulas": formulas, "comecos": comecos,
            "fragmentos": fragmentos[:30], "n_fragmentos": len(fragmentos), "perguntas_fim": perguntas_fim,
            "datas": datas_l, "numeros": nums_l}


_ANO = r"(1[5-9]\d\d|20[0-4]\d)"
_DESDE = re.compile(r"\b(?:ab|seit|desde|a partir de|since|from|starting in|depuis|dal|vanaf)\s+(?:dem\s+Jahr\s+|o ano de\s+|"
                    r"el año\s+|the year\s+|[A-Za-zÀ-ÿ]+\s+)?" + _ANO + r"\b", re.I)


def cronologia(texto: str, tema: str = "") -> Dict[str, Any]:
    """⏳ Linha do tempo do roteiro e CONFLITOS de data.
    Cada parágrafo ganha o "ano da narração" (o 1º ano citado nele, ou o do parágrafo anterior). Uma frase que diz que
    algo começou "ab/seit/desde/a partir de ANO" entra em conflito com parágrafos de ANTES daquele ano que já falam da
    mesma coisa (ex.: "informante ab 1924" × "em 1918 … ele era informante da polícia")."""
    pars = paragrafos(texto)
    do_tema = {_raiz(w) for w in _tokens(tema)}
    raizes = {n: {_raiz(w) for w in _tokens(t)} for n, t in pars}
    df = Counter(r for n, _t in pars for r in raizes[n])
    teto = max(3, int(len(pars) * 0.25))
    ano_de: Dict[int, int] = {}
    atual = 0
    linha_do_tempo = []
    for n, t in pars:
        anos = [int(a) for a in re.findall(r"(?<!\d)" + _ANO + r"(?!\d)", t)]
        if anos:
            atual = anos[0]
            for f in frases(t):
                for a in re.findall(r"(?<!\d)" + _ANO + r"(?!\d)", f):
                    linha_do_tempo.append({"ano": int(a), "linha": n, "frase": f[:220]})
        ano_de[n] = atual
    conflitos = []
    for n, t in pars:
        for f in frases(t):
            for m in _DESDE.finditer(f):
                ano = int(m.group(1))
                chave = {_raiz(w) for w in _tokens(f) if len(w) >= 6} - do_tema
                chave = {r for r in chave if df[r] <= teto and not re.fullmatch(r"\d+", r)}
                if not chave:
                    continue
                antes = [(k, sorted(chave & raizes[k])) for k, _t in pars
                         if k != n and ano_de.get(k) and ano_de[k] < ano and chave & raizes[k]]
                for k, comum in antes[:4]:
                    conflitos.append({"linha": n, "frase": f[:220], "ano": ano, "linha_conflito": k, "ano_conflito": ano_de[k],
                                      "trecho_conflito": _trecho(dict(pars)[k], 16), "palavras": comum[:5]})
    return {"linha_do_tempo": linha_do_tempo[:80], "conflitos": conflitos[:20], "ano_de": ano_de}


def resumo_texto(a: Dict[str, Any], texto: str, estilo: bool = True) -> List[str]:
    """O que o site achou, em linhas curtas (vai nos prompts de revisão e checagem)."""
    pars = dict(paragrafos(texto))
    L = []
    for r in a.get("repeticoes") or []:
        L.append(f"- REPETIÇÃO: linha {r['a']} („{_trecho(pars.get(r['a'], ''), 8)}“) e linha {r['b']} („{_trecho(pars.get(r['b'], ''), 8)}“) "
                 f"contam a mesma coisa ({', '.join(r['palavras'][:6])}).")
    for t in a.get("temas") or []:
        L.append(f"- ASSUNTO QUE VOLTA DEMAIS: “{t['palavra']}” (linhas {', '.join(map(str, t['linhas'][:14]))}) — explique UMA "
                 "vez, no lugar mais forte; nas outras, só o que for novo.")
    if not estilo:
        return L
    for f in a.get("formulas") or []:
        if f["vezes"] >= 2:
            L.append(f"- FÓRMULA REPETIDA: „{f['texto']}“ {f['vezes']}×.")
    for c in a.get("comecos") or []:
        L.append(f"- COMEÇO DE FRASE REPETIDO: „{c['texto']}…“ {c['vezes']}×.")
    if a.get("n_fragmentos", 0) > 4:
        L.append(f"- {a['n_fragmentos']} frases-fragmento (ex.: " + "; ".join(f"„{x['texto']}“" for x in a["fragmentos"][:5])
                 + ") — reserve pras revelações realmente importantes.")
    if len(a.get("perguntas_fim") or []) > max(4, a.get("paragrafos", 0) // 8):
        L.append(f"- {len(a['perguntas_fim'])} parágrafos terminam em pergunta — muitos são suspense de enchimento.")
    return L


# ------------------------------------------------------------------ o prompt da checagem (3 eixos)
EIXOS = {"cronologia": "⏳ Cronologia", "alegacoes": "📚 Alegações históricas", "repeticoes": "✂️ Repetições"}


def prompt(roteiro: str, idioma: str = "o idioma do roteiro", tema: str = "", fontes: str = "", foco: str = "") -> str:
    roteiro = str(roteiro or "").strip()
    if not roteiro:
        raise ValueError("Ainda não tem roteiro pra checar.")
    a = analisar(roteiro, tema)
    cr = cronologia(roteiro, tema)
    n = len(_sem_marcas(roteiro).split())
    L = [f"Você é o CHECADOR de um roteiro narrado{(' sobre ' + tema) if tema else ''} (~{n} palavras, em {idioma}), antes de "
         "ele virar vídeo. O estilo já foi revisado. Agora o trabalho tem SÓ TRÊS FOCOS, nesta ordem — e nada além deles:",
         "", "## 1. ⏳ CRONOLOGIA",
         "- Monte (de cabeça) a linha do tempo do caso pelas FONTES e confira o roteiro contra ela: datas, idades, anos de "
         "início/fim de cada relação ou situação, ordem dos acontecimentos, quem estava onde e quando.",
         "- Contradição interna é furo: ex. o texto diz que alguém era informante da polícia „ab 1924“, mas outro trecho "
         "mostra essa relação em 1918 e de novo depois de uma pena de prisão. Reconcilie pelas fontes; se as fontes não "
         "dão a data exata, tire a data e deixe a frase atribuída/aproximada (\"pelo menos desde…\", \"segundo X…\").",
         "- Idade × ano, duração de pena × datas de saída, data do crime × data da prisão/julgamento/execução: faça a conta.",
         "", "## 2. 📚 CHECAGEM DAS ALEGAÇÕES HISTÓRICAS",
         "- Cada afirmação factual importante contra as fontes desta conversa/abaixo. Fonte diz outra coisa → corrija. Nenhuma "
         "fonte sustenta → atribua a quem diz (\"segundo o investigador X\", \"de acordo com reportagem da Y\"), suavize ou "
         "corte. NUNCA invente um dado novo pra tapar o buraco.",
         "- FATO × ALEGAÇÃO: o que o acusado, a polícia, um jornalista ou um investigador AFIRMOU é alegação — sempre com o "
         "nome de quem afirmou, nunca narrado como fato.",
         "- NÚMEROS QUE NÃO SÃO A MESMA COISA: o número pelo qual foi CONDENADO, o da ACUSAÇÃO, os casos que a polícia LIGOU, "
         "o que o acusado ALEGOU e as estimativas — cada um com o nome certo, igual no roteiro inteiro.",
         "- AFIRMAÇÃO DO TAMANHO DA PROVA: cartas, achados (crânios, objetos), métodos de interrogatório, restos guardados em "
         "instituições, motivos e acordos secretos — só como fato com fonte específica. Citar uma fonte no texto NÃO "
         "confirma a afirmação: liste em \"verificar\" o que precisa ser conferido fora (e onde conferir).",
         "", "## 3. ✂️ CORTE DE REPETIÇÕES",
         "- O mesmo fato ou a mesma explicação em capítulos diferentes (ex.: a relação do criminoso com a polícia, o "
         "julgamento recontado na execução, a contagem de vítimas, o papel do cúmplice, \"ninguém procurou os jovens\"): "
         "fica UMA vez, no lugar mais forte. Nas outras: apague (\"para\": \"\") ou reduza à meia frase que traga algo NOVO.",
         "- Comece pelas repetições — não corte as cenas importantes nem os fatos que só aparecem uma vez.",
         "- Recapitulações no fim (\"Und hier schließt sich ein Kreis\", resumo do caso no legado) saem.", ""]
    if cr["conflitos"]:
        L.append("## ⏳ Possíveis conflitos de data que o site achou (linhas do roteiro abaixo, 1ª linha = 1 — confira, pode ser "
                 "falso alarme)")
        por: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
        for c in cr["conflitos"]:
            por[(c["linha"], c["frase"])].append(c)
        for (lin, fr), cs in por.items():
            L.append(f"- linha {lin} diz „{_trecho(fr, 16)}“ (desde {cs[0]['ano']}), mas trechos ANTERIORES a esse ano já falam "
                     "disso: " + "; ".join(f"linha {c['linha_conflito']} (em {c['ano_conflito']}: {', '.join(c['palavras'])})" for c in cs) + ".")
        L.append("")
    if cr["linha_do_tempo"]:
        L.append("## ⏳ Datas na ordem em que o roteiro conta")
        L += [f"- {d['ano']} · linha {d['linha']}: {_trecho(d['frase'], 16)}" for d in cr["linha_do_tempo"][:40]]
        L.append("")
    nums = a["numeros"][:12]
    if nums:
        L.append("## 📚 Números citados (cada um com o nome certo: condenado × acusado × ligado pela polícia × alegado × estimado)")
        for d in nums:
            L.append(f"- {d['valor']}: " + " | ".join(f"linha {o['linha']}: {_trecho(o['frase'], 14)}" for o in d["onde"][:4]))
        L.append("")
    rep = resumo_texto(a, roteiro, estilo=False)
    if rep:
        L += ["## ✂️ Repetições que o site achou"] + rep + [""]
    L += ["## Regras das correções",
          "- \"de\": trecho COPIADO EXATAMENTE do roteiro (frase, poucas frases ou parágrafo inteiro); \"para\": a versão "
          "corrigida — ou \"\" (vazio) pra apagar uma repetição.",
          "- Não mexa nas marcas [[INSCREVA]], [[VENDA]], [I3], [CENA 2] (não inclua no \"de\").",
          "- Só os três focos: não reescreva o estilo.",
          "- \"eixo\" de cada correção: cronologia | alegacao | repeticao."]
    if foco:
        L.append(f"- Pedido extra (prioridade): {foco.strip()[:800]}")
    L += ["", "## Resposta — SOMENTE um JSON válido, assim:",
          json.dumps({"linha_do_tempo": [{"data": "1918-09", "evento": "o que aconteceu", "fonte": "F2"}],
                      "correcoes": [{"de": "trecho exato", "para": "trecho corrigido (ou \"\")", "eixo": "cronologia | alegacao | repeticao",
                                     "problema": "o que estava errado", "fonte": "F2 / a fonte que sustenta a correção"}],
                      "inconsistencias": [{"descricao": "o que contradiz o quê", "linhas": [23, 29]}],
                      "verificar": [{"afirmacao": "a afirmação do roteiro", "por_que": "por que precisa conferir",
                                     "como": "onde/como conferir"}],
                      "resumo": "1–3 frases: como está a cronologia, as alegações e as repetições"}, ensure_ascii=False, indent=1)]
    if fontes:
        L += ["", "## Fontes do projeto", fontes]
    L += ["", "## Roteiro (as linhas citadas acima são deste texto)", roteiro]
    return "\n".join(L)


def ler(resposta: str) -> Dict[str, Any]:
    """{"trocas": [...] (pro revisao_roteiro.aplicar), "verificar", "inconsistencias", "resumo"}."""
    import json_ia
    try:
        d = json_ia.carregar(resposta)
    except ValueError as exc:
        raise ValueError(f"Não consegui ler o JSON da checagem: {exc}") from exc
    if not isinstance(d, dict):
        raise ValueError("A checagem tem que ser um JSON com \"correcoes\".")
    trocas = []
    for c in d.get("correcoes") or d.get("trocas") or []:
        if isinstance(c, dict) and str(c.get("de") or "").strip():
            st = str(c.get("status") or "").strip().lower().replace(" ", "_")
            if c.get("para") is None and st not in ("falso", "repeticao"):
                continue  # "para": null = a IA não mandou o texto novo (não apaga o trecho por engano)
            trocas.append({"de": str(c["de"]), "para": str(c.get("para") or ""), "item": str(c.get("item") or "").replace(" ", "").upper()[:6],
                           "status": st if st in ("corrigido", "falso", "sem_fonte", "repeticao") else "corrigido",
                           "motivo": (_eixo(c.get("eixo") or c.get("tipo")) + (": " + str(c.get("problema")) if c.get("problema") else ""))[:200],
                           "eixo": _eixo(c.get("eixo") or c.get("tipo")),
                           "fonte": str(c.get("fonte") or "")[:300]})
    verificar = [{"afirmacao": str(v.get("afirmacao") or "")[:400], "por_que": str(v.get("por_que") or "")[:300],
                  "como": str(v.get("como") or "")[:300], "conferido": False}
                 for v in d.get("verificar") or [] if isinstance(v, dict) and str(v.get("afirmacao") or "").strip()][:40]
    inc = [{"descricao": str(i.get("descricao") or "")[:500], "linhas": [int(x) for x in (i.get("linhas") or []) if str(x).isdigit()][:10]}
           for i in d.get("inconsistencias") or [] if isinstance(i, dict) and str(i.get("descricao") or "").strip()][:30]
    ldt = [{"data": str(x.get("data") or "")[:20], "evento": str(x.get("evento") or "")[:300], "fonte": str(x.get("fonte") or "")[:80]}
           for x in d.get("linha_do_tempo") or [] if isinstance(x, dict) and str(x.get("evento") or "").strip()][:60]
    return {"trocas": trocas, "verificar": verificar, "inconsistencias": inc, "linha_do_tempo": ldt,
            "resumo": str(d.get("resumo") or "")[:1200]}


def _eixo(x: Any) -> str:
    t = str(x or "").lower()
    if t.startswith(("cron", "data", "date")):
        return "cronologia"
    if t.startswith(("repet", "dup")):
        return "repeticao"
    return "alegacao"


# ------------------------------------------------------------------ 🌐 2ª IA com internet (v84_133)
def _linha_de(pars: List[Tuple[int, str]], trecho: str) -> int:
    """A linha (parágrafo) que mais combina com um trecho/afirmação (0 se nenhuma)."""
    alvo = set(_tokens(trecho))
    if not alvo:
        return 0
    melhor, nota = 0, 0.0
    for n, t in pars:
        tk = set(_tokens(t))
        s = len(alvo & tk) / max(1, len(alvo))
        if s > nota:
            melhor, nota = n, s
    return melhor if nota >= 0.4 else 0


def prompt_web(roteiro: str, idioma: str = "o idioma do roteiro", tema: str = "", ultima: Dict[str, Any] = None,
               afirmacoes: List[Dict[str, Any]] = None, foco: str = "") -> str:
    """Um prompt CURTO pra uma IA com busca na internet (ChatGPT/Claude/Perplexity/Gemini com pesquisa): só os
    pontos suspeitos — conflitos de data, anos, números, alegações, o que a checagem mandou conferir e as repetições —
    com os TRECHOS do roteiro em volta (não o roteiro inteiro). Ela pesquisa e devolve só as correções {"de","para"}."""
    roteiro = str(roteiro or "").strip()
    if not roteiro:
        raise ValueError("Ainda não tem roteiro pra checar.")
    ultima = ultima or {}
    pars = paragrafos(roteiro)
    texto_de = dict(pars)
    a = analisar(roteiro, tema, set(ultima.get("rep_ignoradas") or []))
    cr = cronologia(roteiro, tema)
    itens: List[str] = []
    linhas: List[int] = []

    def usa(*ns: int) -> str:
        ok = [n for n in ns if n in texto_de]
        for n in ok:
            if n not in linhas:
                linhas.append(n)
        return ", ".join(f"L{n}" for n in ok)

    k = 0
    for c in cr["conflitos"][:12]:
        k += 1
        itens.append(f"C{k} ⏳ CRONOLOGIA — {usa(c['linha'], c['linha_conflito'])}: a L{c['linha']} diz que começou em "
                     f"{c['ano']} („{_trecho(c['frase'], 14)}“), mas a L{c['linha_conflito']} (ano {c['ano_conflito']}) já "
                     f"fala disso ({', '.join(c['palavras'])}). Qual é a data certa?")
    for k, inc in enumerate((ultima.get("inconsistencias") or [])[:12], 1):
        itens.append(f"I{k} 🔁 INCONSISTÊNCIA — {usa(*inc.get('linhas') or []) or 'ache no texto'}: {inc['descricao']}")
    pend = [(i, v) for i, v in enumerate(ultima.get("verificar") or []) if not v.get("conferido")]
    for i, v in pend[:25]:
        n = _linha_de(pars, v["afirmacao"])
        itens.append(f"V{i + 1} 📚 CONFERIR — {usa(n) if n else 'ache no texto'}: „{v['afirmacao']}“"
                     + (f" — {v['por_que']}" if v.get("por_que") else "") + (f" (sugestão: {v['como']})" if v.get("como") else ""))
    for k, af in enumerate([x for x in afirmacoes or [] if x.get("tipo") in ("alegacao", "interpretacao")][:20], 1):
        n = _linha_de(pars, af.get("trecho") or "")
        itens.append(f"A{k} 📚 {'ALEGAÇÃO' if af.get('tipo') == 'alegacao' else 'INTERPRETAÇÃO'} — {usa(n) if n else 'ache no texto'}: "
                     f"„{af.get('trecho')}“ (fonte que o roteiro usou: {af.get('fonte') or '?'}). Está atribuída a quem alega? "
                     "Os fatos dela batem?")
    anos_vistos = set()
    k = 0
    for d in cr["linha_do_tempo"]:
        if len(anos_vistos) >= 25 or (d["ano"], d["linha"]) in anos_vistos:
            continue
        anos_vistos.add((d["ano"], d["linha"]))
        k += 1
        itens.append(f"D{k} 📅 ANO — {usa(d['linha'])}: {d['ano']} em „{_trecho(d['frase'], 16)}“")
    for k, d in enumerate(a["numeros"][:12], 1):
        itens.append(f"N{k} 🔢 NÚMERO {d['valor']} — {usa(*[o['linha'] for o in d['onde'][:4]])}: confira o número e o NOME "
                     "dele (condenado × acusado × ligado pela polícia × alegado × estimado), igual em todo lugar.")
    for k, r in enumerate(a["repeticoes"][:15], 1):
        itens.append(f"R{k} ✂️ REPETIÇÃO? — {usa(r['a'], r['b'])}: parecem contar a mesma coisa "
                     f"({', '.join(r['palavras'][:6])}). Se CONTAM: fica UMA vez, no lugar mais forte (no outro apague ou reduza). "
                     "Se NÃO é repetição (cada um traz algo novo), ponha em \"conferidos\" com \"ok\": true.")
    if not itens:
        raise ValueError("O site não achou nada pra checar (rode a 🔎 checagem primeiro pra ter a lista do que conferir).")
    linhas = sorted(linhas)[:70]
    L = [f"Você é um CHECADOR DE FATOS com acesso à INTERNET. O roteiro é de um vídeo do YouTube{(' sobre ' + tema) if tema else ''}, "
         f"em {idioma}. NÃO vou mandar o roteiro inteiro — só os PONTOS SUSPEITOS e os TRECHOS em volta deles.",
         "",
         "## O que fazer",
         "1. Para cada item abaixo, PESQUISE NA INTERNET em fontes confiáveis (jornais, arquivos, documentos oficiais, "
         "processos, livros, Wikipedia só como ponto de partida) e confira: anos, datas, idades, números, nomes, lugares, "
         "e se cada alegação está atribuída a quem alega.",
         "2. Errado → corrija. Sem confirmação → atribua (\"segundo…\", \"de acordo com…\"), suavize ou tire o detalhe. "
         "NUNCA invente um dado pra tapar buraco.",
         "3. Repetições: deixe uma vez só, no lugar mais forte (no outro: apague com \"para\": \"\" ou reduza à meia frase "
         "que traga algo novo).",
         "4. Só esses três focos (ano/cronologia, alegações/fatos, repetições). Não mexa no estilo.",
         "",
         "## Regras das correções",
         "- \"de\": trecho COPIADO EXATAMENTE dos TRECHOS abaixo (uma frase ou poucas), na língua do roteiro.",
         "- NÃO inclua no \"de\" as marcas entre colchetes ([I3], [[INSCREVA]], [CENA 2]) — escolha um pedaço que não passe por elas.",
         "- \"para\": o trecho corrigido, na MESMA língua e no mesmo tom (ou \"\" pra apagar uma repetição).",
         "- \"fonte\": o LINK (URL) que confirma a correção.",
         "- \"status\" de cada correção: \"corrigido\" (dado errado, trocado pelo certo), \"falso\" (não aconteceu / não "
         "se sustenta — tirado do texto), \"sem_fonte\" (não achei confirmação — atribuído/suavizado) ou \"repeticao\".",
         "- Item que está CERTO: ponha em \"conferidos\" com o link que confirma (assim eu sei que foi checado).",
         "- RESPONDA TODOS os itens: cada um vai em \"correcoes\" (com o \"item\") OU em \"conferidos\". Item sem resposta "
         "eu mando de novo.",
         ]
    if foco:
        L.append(f"- Pedido extra (prioridade): {foco.strip()[:800]}")
    L += ["", "## Itens pra checar (L12 = linha 12 dos trechos)", *[f"- {x}" for x in itens], "",
          "## Trechos do roteiro (só os parágrafos citados — a linha é a do roteiro)",
          *[f"L{n}: {texto_de[n]}" for n in linhas], "",
          "## Resposta — SOMENTE um JSON válido, assim (sem texto antes ou depois):",
          json.dumps({"correcoes": [{"item": "C1", "de": "trecho exato", "para": "trecho corrigido (ou \"\")",
                                     "status": "corrigido | falso | sem_fonte | repeticao",
                                     "eixo": "cronologia | alegacao | repeticao", "problema": "o que estava errado",
                                     "fonte": "https://…"}],
                      "conferidos": [{"item": "V2", "ok": True, "fonte": "https://…", "nota": "o que a fonte diz"}],
                      "resumo": "1-3 frases: o que estava errado e o que foi confirmado"}, ensure_ascii=False, indent=1)]
    return "\n".join(L)


def ler_web(resposta: str) -> Dict[str, Any]:
    """{"trocas" (pro revisao_roteiro.aplicar), "conferidos": [{"item","ok","fonte","nota"}], "resumo"}."""
    d = ler(resposta)
    import json_ia
    bruto = json_ia.carregar(resposta)
    conf = []
    for c in (bruto.get("conferidos") if isinstance(bruto, dict) else None) or []:
        if isinstance(c, str) and c.strip():  # às vezes vem só ["V2", "R3"]
            c = {"item": c}
        if isinstance(c, dict) and str(c.get("item") or "").strip():
            conf.append({"item": str(c["item"]).replace(" ", "").upper()[:6], "ok": str(c.get("ok", True)).strip().lower() not in ("false", "0", "no", "nao", "não", "none"),
                         "fonte": str(c.get("fonte") or "")[:300], "nota": str(c.get("nota") or "")[:300]})
    return {"trocas": d["trocas"], "conferidos": conf[:80], "resumo": d["resumo"]}


def prompt_repeticoes(roteiro: str, reps: List[Dict[str, Any]], idioma: str = "o idioma do roteiro") -> str:
    """✂️ Todas as repetições de uma vez: a IA decide em cada par o que fica e devolve as trocas."""
    pars = dict(paragrafos(roteiro))
    if not reps:
        raise ValueError("Não tem repetição na lista.")
    L = [f"Você é editor de roteiro de documentário (em {idioma}). Abaixo vão PARES de parágrafos que parecem contar a mesma coisa.",
         "Para CADA par:",
         "- Se for repetição de verdade: a informação fica UMA vez, no lugar mais forte; no outro parágrafo apague o trecho repetido "
         "(\"para\": \"\") ou reduza à meia frase que traga algo novo. Mantenha o texto fluindo (ajuste a ligação se precisar).",
         "- Se NÃO for repetição (cada um traz algo novo, ou é um gancho/retomada de propósito): ponha o número do par em \"nao_e_repeticao\".",
         "- \"de\": trecho COPIADO EXATAMENTE do parágrafo (uma frase ou poucas), sem as marcas entre colchetes ([I3], [[INSCREVA]]).",
         "- Não mexa em nada além das repetições. Mesma língua e mesmo tom.", "", "## Pares"]
    for k, r in enumerate(reps, 1):
        L += [f"R{k}:", f"  L{r['a']}: {pars.get(r['a'], '')}", f"  L{r['b']}: {pars.get(r['b'], '')}"]
    L += ["", "## Resposta — SOMENTE este JSON:",
          json.dumps({"trocas": [{"par": "R1", "de": "trecho exato", "para": "trecho novo (ou \"\")"}], "nao_e_repeticao": ["R2"]},
                     ensure_ascii=False, indent=1)]
    return "\n".join(L)
