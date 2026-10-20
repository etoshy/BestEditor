"""
✍️ roteiro_partes.py — roteiro LONGO escrito CAPÍTULO POR CAPÍTULO (v84_97)
==========================================================================

Por que: pedir um roteiro de 18 min (≈2.700 palavras) DENTRO de um JSON, junto com títulos, descrição, capítulos,
thumbnails, afirmações…, faz a IA de chat entregar ~40–50% do tamanho (ela "economiza" a resposta). E o prompt de
"completar" pedia o roteiro INTEIRO de novo, num JSON — o mesmo problema.

Agora, em vídeo longo (🕵️ Modelos de vídeo, a partir de ~8 min ou quando você liga "escrever em partes"):
  1º prompt  → o PLANO (JSON): títulos, descrição, thumbnails… e os capítulos com objetivo, fatos (com a fonte),
               mídias e quantas palavras cada um tem — SEM o roteiro;
  depois     → um prompt por capítulo, resposta em TEXTO PURO (sem JSON), com o tamanho daquele capítulo
               (~300–500 palavras: a IA escreve inteiro). 🤖 com a IA ligada, o site escreve todos sozinho, em sequência.
  no fim     → o site junta tudo, põe [[INSCREVA]]/[[VENDA]] entre as partes nos pontos certos e os capítulos já saem
               com o começo EXATO (pros tempos da descrição).
O 📏 "Completar" de um roteiro que ficou curto usa o mesmo caminho: corta o roteiro nos capítulos e pede pra IA
reescrever só os capítulos curtos, um por vez, em texto puro.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

PARTES_A_PARTIR_DE = 8.0  # minutos
MIN_PALAVRAS_PARTE = 120
CURTA = 0.85   # abaixo de 85% do alvo da parte = curta (reescreve expandindo)
LONGA = 1.25   # v84_99: acima de 125% = longa (reescreve enxugando) — 25 min pedidos viravam 38



REGRA = 'USE AS IMAGENS COM FREQUÊNCIA: use TODAS as imagens que têm relação com o roteiro (nenhuma útil fica de fora) e ponha a marca DE NOVO toda vez que a narração voltar a falar daquela pessoa, lugar, objeto ou documento — a mesma imagem pode (e deve) voltar várias vezes ao longo do vídeo, com pelo menos 2-3 frases entre um uso e outro; quando houver várias fotos da mesma pessoa/lugar, alterne entre elas. Mire em uma marca a cada ~3-5 frases nos trechos em que o assunto tem imagem. Não use imagem que não mostra o que a frase fala.'

def status_de(parte: Dict[str, Any]) -> str:
    """"pendente" | "curta" | "longa" | "pronta"."""
    t = parte.get("texto")
    if not t:
        return "pendente"
    n, alvo = palavras(t), int(parte.get("palavras") or 0)
    if alvo and n < alvo * CURTA:
        return "curta"
    if alvo and n > alvo * LONGA:
        return "longa"
    return "pronta"


def usa_partes(cfg: Dict[str, Any], minutos: float) -> bool:
    modo = str(cfg.get("modo_partes") or "auto")
    if modo == "nao" or cfg.get("formato") == "curto" or minutos <= 1:
        return False
    return modo == "sim" or minutos >= PARTES_A_PARTIR_DE


def n_capitulos(minutos: float) -> int:
    return max(4, min(14, int(round(minutos / 2.0))))


# ------------------------------------------------------------------ 1º prompt (o plano)
def bloco_plano(minutos: float, palavras: int, estrutura: Optional[List[str]] = None, enxuto: bool = False) -> str:
    n = n_capitulos(minutos)
    por = max(MIN_PALAVRAS_PARTE, palavras // n)
    fatos = ("  • \"fatos\": 3 a 7 pontos — SÓ os que a pessoa precisa pra entender o título (o 🎯 escopo); cada um com a fonte "
             "(F1, F2…) e o tipo (fato documentado / modelo científico / hipótese). Explicativo: menos coisas, bem explicadas — "
             "assunto vizinho não entra no plano, vai em \"escopo.fica_para_outro_video\";\n") if enxuto else (
             "  • \"fatos\": 8 a 15 fatos CONCRETOS das fontes que entram nele (datas, nomes, lugares, números, citações, o que "
             "cada pessoa disse), cada um com a fonte (F1, F2…) e o tipo (fato documentado / alegação / interpretação) — é "
             "deles que o capítulo vai ser escrito, então capriche: quanto mais detalhe aqui, mais rico o capítulo;\n")
    return (f"## ✍️ ESTE ROTEIRO É ESCRITO EM PARTES (vídeo de ~{minutos:g} min ≈ {palavras} palavras)\n"
            "AGORA você NÃO escreve o roteiro. Você faz o PLANO DETALHADO — depois eu peço cada capítulo separado, um por vez, "
            "e você escreve aquele capítulo inteiro com o tamanho dele.\n"
            f"- Em \"capitulos\", divida o vídeo em ~{n} capítulos (entre {max(4, n - 2)} e {n + 2}) seguindo a estrutura do "
            "formato e o método de roteiro (gancho no 1º, viradas, final). Cada capítulo:\n"
            "  • \"titulo\": curto e chamativo (vira o capítulo da descrição do YouTube);\n"
            "  • \"objetivo\": o que este capítulo conta, que pergunta abre/fecha e como termina (o gancho pro próximo);\n"
            + fatos +
            "  • \"midias\": TODOS os IDs das imagens/vídeos que combinam com ele (ex.: [\"I3\", \"I7\", \"I9\"]) — a mesma "
            "imagem pode (e deve) estar em vários capítulos quando a pessoa/lugar volta na história;\n"
            f"  • \"palavras\": quantas palavras o capítulo vai ter (a SOMA de todos = ~{palavras}; o gancho pode ser menor, "
            f"~{max(80, por // 2)}; os outros ~{por}).\n"
            "- Distribua os fatos: cada fato importante em UM capítulo (sem repetir), na ordem da história que você escolheu.\n"
            "- Cada ASSUNTO que atravessa o caso (ex.: a relação do criminoso com a polícia, a contagem das vítimas, o papel do "
            "cúmplice, o julgamento) tem UM capítulo DONO, que explica tudo; os outros capítulos só citam em meia frase.\n"
            "- Confira a CRONOLOGIA do plano: as datas de cada capítulo batem entre si e com as fontes.\n"
            "- As marcas [[INSCREVA]] e [[VENDA]] o site põe sozinho entre os capítulos — não precisa planejar.")


def exemplo_capitulos() -> List[Dict[str, Any]]:
    return [{"titulo": "Título curto do capítulo", "objetivo": "o que conta e como termina (gancho pro próximo)",
             "fatos": [{"fato": "fato concreto com data/nome/número", "fonte": "F2", "tipo": "fato | alegacao | interpretacao"}],
             "midias": ["I3"], "palavras": 350}]


# ------------------------------------------------------------------ as partes
def _int(v: Any, padrao: int) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return padrao


def palavras(texto: str) -> int:
    return len(re.sub(r"\[\[[^\]]*\]\]|\[[^\]]*\]", " ", str(texto or "")).split())


def eh_plano(capitulos: Any) -> bool:
    """A resposta trouxe o PLANO (capítulos com objetivo/fatos) em vez do roteiro?"""
    return isinstance(capitulos, list) and any(isinstance(c, dict) and (c.get("objetivo") or c.get("fatos")) for c in capitulos)


def _fatos(x: Any) -> List[Dict[str, str]]:
    out = []
    for f in x if isinstance(x, list) else []:
        if isinstance(f, str) and f.strip():
            f = {"fato": f}
        if isinstance(f, dict) and str(f.get("fato") or "").strip():
            t = str(f.get("tipo") or "").lower()
            t = "alegacao" if t.startswith(("aleg", "alleg", "claim")) else "interpretacao" if t.startswith("interp") else "fato"
            out.append({"fato": str(f["fato"]).strip()[:500], "fonte": str(f.get("fonte") or "").strip()[:120], "tipo": t})
    return out[:25]


def _repartir(alvos: List[int], total: int) -> List[int]:
    """Ajusta os tamanhos pedidos pra somarem o total (mantendo a proporção)."""
    soma = sum(alvos) or 1
    return [max(MIN_PALAVRAS_PARTE // 2, int(round(a * total / soma / 10.0)) * 10) for a in alvos]


def de_plano(capitulos: List[Any], total_palavras: int) -> List[Dict[str, Any]]:
    caps = [c for c in capitulos if isinstance(c, dict) and str(c.get("titulo") or c.get("objetivo") or "").strip()][:20]
    alvos = _repartir([max(60, _int(c.get("palavras"), total_palavras // max(1, len(caps)))) for c in caps], total_palavras)
    return [{"k": i + 1, "titulo": str(c.get("titulo") or f"Parte {i + 1}").strip()[:120], "objetivo": str(c.get("objetivo") or "").strip()[:800],
             "fatos": _fatos(c.get("fatos")), "midias": [str(m).strip("[] ").upper()[:6] for m in (c.get("midias") or []) if str(m).strip()][:12],
             "palavras": alvo, "texto": "", "status": "pendente"} for i, (c, alvo) in enumerate(zip(caps, alvos))]


_MARCA_CHAMADA = re.compile(r"^\s*\[\[\s*(INSCREVA|VENDA)[^\]]*\]\]\s*$", re.I | re.M)


def _achar_inicio(texto: str, inicio: str, desde: int = 0) -> int:
    """Onde o capítulo começa: a frase exata, ou as primeiras 6…3 palavras (a IA às vezes erra o resto da frase).
    Volta pro começo do parágrafo/frase em que achou."""
    palav = inicio.split()
    for n in (len(palav), 6, 5, 4, 3):
        if n > len(palav) or n < 3:
            continue
        alvo = " ".join(palav[:n])
        i = texto.find(alvo, desde)
        if i < 0:
            i = texto.lower().find(alvo.lower(), desde)
        if i >= 0:  # volta pro começo da frase (a IA às vezes cita do meio)
            j = max(texto.rfind("\n", 0, i), texto.rfind(". ", 0, i), texto.rfind("? ", 0, i), texto.rfind("! ", 0, i))
            return 0 if j < 0 else (j + 1 if texto[j] == "\n" else j + 2)
    return -1


def _subdividir(pedacos: List[Tuple[str, str]], n_desejado: int) -> List[Tuple[str, str]]:
    """Pedaço grande demais (capítulo que a IA não marcou direito) vira vários, nos parágrafos — cada parte tem que
    caber num pedido só (~250–450 palavras)."""
    total = sum(palavras(b) for _t, b in pedacos) or 1
    media = max(60, total / max(1, n_desejado))
    out: List[Tuple[str, str]] = []
    for titulo, bloco in pedacos:
        n = max(1, int(round(palavras(bloco) / media)))
        if n == 1:
            out.append((titulo, bloco))
            continue
        pars = [x for x in bloco.split("\n\n") if x.strip()]
        alvo, atual, k = palavras(bloco) / n, [], 0
        for par in pars:
            atual.append(par)
            if sum(palavras(x) for x in atual) >= alvo and len(out) < 40:
                out.append((titulo if k == 0 else f"{titulo} (cont. {k + 1})", "\n\n".join(atual)))
                atual, k = [], k + 1
        if atual:
            if k and palavras("\n\n".join(atual)) < alvo * 0.4:  # sobrinha: junta na anterior
                t, b = out.pop()
                out.append((t, b + "\n\n" + "\n\n".join(atual)))
            else:
                out.append((titulo if k == 0 else f"{titulo} (cont. {k + 1})", "\n\n".join(atual)))
    return out


def de_roteiro(roteiro: str, capitulos: List[Dict[str, Any]], total_palavras: int, n_desejado: int = 0) -> List[Dict[str, Any]]:
    """📏 Completar: corta o roteiro pronto nos começos dos capítulos (sem as marcas de chamada, que o site repõe)."""
    texto = _MARCA_CHAMADA.sub("", str(roteiro or ""))
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    cortes = []
    pos = 0
    for c in capitulos or []:
        i = _achar_inicio(texto, str(c.get("comeca_em") or ""), pos)
        if i >= 0:
            cortes.append((i, str(c.get("titulo") or "")))
            pos = i + 1
    cortes = sorted({i: t for i, t in cortes}.items())
    if not cortes or cortes[0][0] > 0:
        cortes.insert(0, (0, (capitulos[0].get("titulo") if capitulos else "") or "Começo"))
    if len(cortes) < 3:  # sem capítulos achados: divide pelos parágrafos em ~6 partes
        pars = [x for x in texto.split("\n\n") if x.strip()]
        n = max(1, min(8, len(pars) // 2 or 1))
        tam = max(1, len(pars) // n)
        blocos = ["\n\n".join(pars[i:i + tam]) for i in range(0, len(pars), tam)]
        pedacos = [(f"Parte {k + 1}", b) for k, b in enumerate(blocos)]
    else:
        pedacos = [(t, texto[i:(cortes[j + 1][0] if j + 1 < len(cortes) else len(texto))].strip()) for j, (i, t) in enumerate(cortes)]
    if n_desejado:
        pedacos = _subdividir(pedacos, n_desejado)
    alvos = _repartir([max(60, palavras(b)) for _t, b in pedacos], total_palavras)
    return [{"k": k + 1, "titulo": t or f"Parte {k + 1}", "objetivo": "", "fatos": [], "midias": sorted(set(re.findall(r"\[([MIT]\d+)\]", b))),
             "palavras": alvo, "texto": b, "status": status_de({"texto": b, "palavras": alvo})}
            for k, ((t, b), alvo) in enumerate(zip(pedacos, alvos))]


def falta(partes: List[Dict[str, Any]]) -> List[int]:
    """Quais partes ainda precisam de texto (sem texto, curta ou longa — a não ser que já tenha sido aceita como está)."""
    return [p["k"] for p in partes
            if not p.get("texto") or (not p.get("aceita_curta") and status_de(p) in ("curta", "longa"))]


def _resumo_parte(x: Dict[str, Any]) -> str:
    """O que uma parte já escrita contou (pra próxima não recontar): os fatos do plano ou, sem eles, o começo de cada parágrafo."""
    if x.get("fatos"):
        return "; ".join(f["fato"][:160] for f in x["fatos"][:10])
    pars = [re.sub(r"\[[^\]]*\]", " ", par) for par in str(x.get("texto") or "").split("\n\n") if par.strip()]
    return " / ".join(" ".join(par.split()[:14]) + "…" for par in pars[:8])


# ------------------------------------------------------------------ o prompt de cada parte
def prompt_parte(contexto: Dict[str, Any], partes: List[Dict[str, Any]], k: int, fontes: str = "") -> str:
    """contexto: tema, nome_modelo, idioma (nome), regras (lista), canal, minutos, midias {id: descrição}, plano (dict)."""
    p = next(x for x in partes if x["k"] == k)
    n = len(partes)
    alvo = int(p["palavras"])
    minimo, maximo = int(alvo * 0.9), int(alvo * 1.1)
    st = status_de(p)
    L = [f"Você está escrevendo, em PARTES, o roteiro NARRADO (alguém vai ler em voz alta) de um vídeo de {contexto.get('nome_modelo', 'documentário')} "
         f"sobre: {contexto.get('tema', '')} (~{contexto.get('minutos', 0):g} min no total).",
         f"AGORA escreva SÓ a PARTE {k} de {n}: “{p['titulo']}”.",
         f"IDIOMA: escreva em {contexto.get('idioma', 'português')}.", "",
         "## O vídeo inteiro (pra manter o fio da história — NÃO escreva as outras partes)"]
    for x in partes:
        L.append(f"{x['k']}. {x['titulo']}" + (f" — {x['objetivo']}" if x.get("objetivo") else "") + ("   ← ESTA" if x["k"] == k else ""))
    plano = contexto.get("plano") or {}
    if plano.get("problema_profundo"):
        L.append(f"Problema profundo do vídeo (plantar cedo, revelar no fim): {plano['problema_profundo']}")
    antes = [x for x in partes if x["k"] < k and (x.get("texto") or x.get("fatos"))]
    if antes:
        L += ["", "## JÁ CONTADO nas partes anteriores — NÃO reconte (no máximo meia frase de referência, e só se trouxer algo NOVO)"]
        L += [f"- {x['k']}. {x['titulo']}: {_resumo_parte(x)}" for x in antes]
    depois = [x for x in partes if x["k"] > k and x.get("fatos")]
    if depois:
        L += ["", "## Vem DEPOIS (não antecipe nem resuma isto aqui)"]
        L += [f"- {x['k']}. {x['titulo']}" for x in depois]
    ant = next((x for x in partes if x["k"] == k - 1), None)
    if ant and ant.get("texto"):
        fim = " ".join(ant["texto"].split()[-90:])
        L += ["", "## Como a parte anterior terminou (continue DAQUI, sem repetir nada dela)", f"“…{fim}”"]
    if contexto.get("promessa"):  # 🧵 v84_169: cada parte é uma prova da promessa do título
        prom = contexto["promessa"]
        papel = ("ABERTURA: depois do gancho, apresente a tese do título com as palavras dele e mostre de relance os assuntos "
                 "que vêm como provas." if k == 1 else
                 "FECHAMENTO: volte ao título e RESPONDA a ele somando as provas das partes anteriores (com os fatos; sem "
                 "inventar pra confirmar) e termine com uma pergunta ao público ligada ao título." if k == n else
                 "Comece com uma FRASE-PONTE que liga o assunto da parte anterior a este e ao título (nada de pulo seco) e "
                 "termine dizendo, numa frase, o que esta parte acrescenta à pergunta do título.")
        L += ["", f"## 🧵 O título é a promessa: “{prom}”", papel,
              "Cada frase traz informação nova — não repita a mesma frase/ideia com outras palavras."]
    if contexto.get("escopo"):  # 🎯 v84_178: o que ficou de fora no plano continua de fora em cada parte
        import metodo_roteiro as _mr
        L += ["", _mr.bloco_escopo_parte(contexto["escopo"], contexto.get("idioma_cod") or "pt")]
    if contexto.get("personagens_bloco"):  # 🎭 v84_173: as vozes/personagens/lore valem em cada parte
        L += ["", contexto["personagens_bloco"]]
    if contexto.get("referencia"):  # 📐 v84_169: modelando um roteiro exemplo — esta parte é o bloco equivalente dele
        L += ["", "## 📐 Roteiro exemplo que o vídeo modela (SÓ a estrutura e as técnicas — o assunto e os fatos dele NÃO entram)",
              f"Esta é a parte {k} de {n}: escreva-a como o bloco equivalente do exemplo (mesma função, mesmo tipo de gancho/"
              "transição/ritmo), com o MEU tema e os fatos desta parte. Não copie frases, nomes nem fatos do exemplo.",
              contexto["referencia"]]
    L += ["", f"## Esta parte: {k}. {p['titulo']}"]
    if p.get("objetivo"):
        L.append(f"Objetivo: {p['objetivo']}")
    if p.get("fatos"):
        if contexto.get("enxuto"):  # 🎯 explicativo: só o necessário, explicado simples; a fonte não é falada
            L.append("Pontos desta parte (explique cada um do jeito mais simples — analogia + uma frase do mecanismo; NÃO diga a "
                     "fonte em voz alta, ela vai na descrição; hipótese e estimativa ditas como tal, em palavras simples):")
        else:
            L.append("Fatos desta parte (use TODOS, desenvolvidos — quem/quando/onde/como/por quê; diga a fonte no texto quando for "
                     "uma afirmação importante; alegação sempre atribuída a quem alega; interpretação marcada como tal):")
        L += [f"- {f['fato']}" + (f" ({f['fonte']}" + (f", {f['tipo']})" if f.get("tipo") != "fato" else ")") if f.get("fonte") else "") for f in p["fatos"]]
    mids = contexto.get("midias") or {}
    meus = [m for m in p.get("midias") or [] if m in mids]
    outras = [m for m in mids if m not in meus][:80]
    if meus or outras:
        L.append("Imagens/vídeos que eu tenho — ponha a marca (ex.: [I3]) sozinha logo ANTES da frase em que ela aparece, "
                 "quando a frase fala MESMO daquilo (pessoa, lugar, objeto, documento). " + REGRA)
        if meus:
            L.append("Planejadas pra esta parte (prioridade):")
            L += [f"- {m}: {mids[m]}" for m in meus]
        if outras:
            L.append("Todas as outras do caso (use também sempre que a frase falar delas):")
            L += [f"- {m}: {mids[m]}" for m in outras]
    if p.get("texto") and st == "longa":
        L += ["", f"## O texto ATUAL desta parte ({palavras(p['texto'])} palavras — LONGO demais: o vídeo passa do tempo pedido)",
              f"Reescreva esta parte ENXUTA, com ~{alvo} palavras: corte o que repete outras partes ou repete a si mesma, frases de "
              "suspense vazias, fórmulas de análise e explicações em dobro. Mantenha os fatos essenciais, a ordem e as marcas de "
              "imagem.", "", p["texto"]]
    elif p.get("texto"):
        L += ["", f"## O texto ATUAL desta parte ({palavras(p['texto'])} palavras — curto demais)",
              "Reescreva esta parte expandida: mantenha os fatos, a ordem e as marcas de imagem; aprofunde cada fato com contexto, "
              "detalhes das fontes, causas e consequências, o que as pessoas disseram — sem repetir frases pra encher.", "",
              p["texto"]]
    L += ["", "## TAMANHO (o mais importante)",
          f"- Esta parte tem ENTRE {minimo} e {maximo} palavras (alvo ~{alvo}). O vídeo tem DURAÇÃO FIXA "
          f"(~{contexto.get('minutos', 0):g} min): menos que isso fica raso, mais que isso estoura o tempo do vídeo.",
          "- Não resuma nem pule fatos — mas também não encha: nada de recontar o que já foi dito, de frases de suspense "
          "vazias ou de explicar a mesma ideia duas vezes. Se sobrar espaço, aprofunde um fato com um detalhe concreto das fontes.",
          "- Antes de responder, conte as palavras e ajuste ao intervalo."]
    L += ["", "## Regras"]
    L += [f"- {r}" for r in contexto.get("regras") or []]
    L.append("- Uma ideia por frase: frases que juntam data + lugar + nome + resultado viram várias frases curtas. Varie o "
             "tamanho das frases.")
    import metodo_roteiro
    L += [f"- {r}" for r in metodo_roteiro.REGRAS_NARRACAO]
    if k == 1:
        L.append("- Esta é a ABERTURA: comece com o gancho (o momento mais intrigante, sem entregar o desfecho) e termine com uma "
                 "pergunta que faça a pessoa querer continuar.")
    elif k == n:
        L.append("- Esta é a ÚLTIMA parte: feche os laços abertos, resolva o problema profundo e termine com uma reflexão "
                 "respeitosa + uma pergunta pro público comentar.")
    else:
        L.append("- Termine esta parte com uma revelação, uma consequência concreta ou uma pergunta realmente necessária pro "
                 "próximo capítulo — nunca com frase de suspense vazia (sem anunciar \"no próximo capítulo\").")
    if contexto.get("canal") and k in (1, n):
        L.append(f"- Diga o nome do canal “{contexto['canal']}” uma vez, de forma natural"
                 + (" — logo depois do gancho, nunca na 1ª frase." if k == 1 else " — no fechamento."))
    if 1 < k:
        L.append("- Esta parte CONTINUA o MESMO vídeo, que a pessoa está assistindo agora: nada de saudar de novo (“Willkommen "
                 "zurück”, “bem-vindo de volta”), nada de “no episódio passado / vor einigen Wochen habt ihr…”, nada de retomar o "
                 "que a parte anterior acabou de contar e nada de anunciar o que “ainda não vamos contar”."
                 + (" O nome do canal NÃO aparece nesta parte." if k < n else ""))
    L += ["- NÃO escreva o título da parte, \"Parte 2\", \"Capítulo\", marcações de câmera nem as marcas [[INSCREVA]]/[[VENDA]] "
          "(o site põe entre as partes).",
          "- Não repita o que as outras partes contam e não antecipe as revelações delas.",
          "- Se esta conversa tem as FONTES (o 1º prompt), use-as pra detalhar; se não, use só os fatos acima — nunca invente."]
    if fontes:
        L += ["", "## Fontes (pra detalhar os fatos desta parte)", fontes]
    L += ["", "## Resposta", f"SOMENTE o texto narrado desta parte, em {contexto.get('idioma', 'português')} — sem JSON, sem markdown, "
          "sem título, sem comentário antes ou depois."]
    if contexto.get("personagens_bloco"):  # 🎭 v84_218: sem isto a IA mandava o texto puro, sem dizer quem fala
        L.append("MULTI VOZ: TODO parágrafo começa com a tag de quem fala — narrador, cada personagem — com a emoção quando a "
                 "fala pede (ex.: [narrador|contemplativo] …, [mira|curiosa] …, [vanta|ironica] …), inclusive o 1º parágrafo "
                 "e cada fala curta. Parágrafo sem tag = erro (a voz não sabe de quem é).")
    return "\n".join(L)


def ler_parte(texto: str, parte: Dict[str, Any]) -> str:
    """Limpa a resposta de uma parte (cercas, JSON, título repetido no começo, marcas de chamada)."""
    t = str(texto or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\s*\n|\n?```\s*$", "", t).strip()
    if t.startswith("{"):
        try:
            d = json.loads(t)
            if isinstance(d, dict):
                t = str(d.get("texto") or d.get("roteiro") or d.get("parte") or "").strip()
        except ValueError:
            pass
    linhas = t.split("\n")
    while linhas and linhas[0].strip() and len(linhas[0].split()) <= 12 and not re.search(r"[.!?…:]\s*$", linhas[0].strip()) and \
            (re.match(r"^\s*(#+|\*\*|parte|cap[ií]tulo|part|chapter|teil|kapitel)\b", linhas[0], re.I) or
             linhas[0].strip().strip("#* ").lower() == str(parte.get("titulo") or "").strip().lower()):
        linhas.pop(0)
    t = "\n".join(linhas).strip()
    t = _MARCA_CHAMADA.sub("", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if not t:
        raise ValueError("A resposta está vazia — cole o texto que a IA escreveu pra esta parte.")
    return t


# ------------------------------------------------------------------ juntar
def montar(partes: List[Dict[str, Any]], marcar_chamadas: bool = True, total_palavras: int = 0,
          max_inscreva: Optional[int] = None) -> Tuple[str, List[Dict[str, str]]]:
    """(roteiro inteiro com [[INSCREVA]]/[[VENDA]] entre as partes, capítulos com o começo exato).
    📣 v84_218: `max_inscreva=1` (o canal pede) → uma só, no 1º respiro entre partes depois de ~25% do vídeo."""
    blocos: List[str] = []
    caps: List[Dict[str, str]] = []
    total = sum(palavras(p.get("texto") or "") for p in partes) or 1
    acum = 0
    ultima_venda = 0
    inscreva_posta = False
    n = len(partes)
    for i, p in enumerate(partes):
        txt = (p.get("texto") or "").strip()
        if not txt:
            continue
        sem_marca = re.sub(r"\[[^\]]*\]", " ", txt)
        if not re.search(r"\(cont\. \d+\)$", p["titulo"]):  # continuação do mesmo capítulo não vira capítulo novo
            caps.append({"titulo": p["titulo"], "comeca_em": " ".join(sem_marca.split()[:8])})
        blocos.append(txt)
        acum += palavras(txt)
        if not marcar_chamadas or i == n - 1:
            continue
        if max_inscreva is not None and max_inscreva <= 1:
            if max_inscreva == 1 and not inscreva_posta and (acum / total >= 0.25 or i == n - 2):
                blocos.append("[[INSCREVA]]")
                inscreva_posta = True
                continue
        elif i == 0:
            blocos.append("[[INSCREVA]]")
            continue
        elif i == n - 2 and n >= 4:
            blocos.append("[[INSCREVA]]")
            continue
        if acum / total >= 0.15 and acum - ultima_venda >= max(600, total // 4):  # v84_99: ~3 no vídeo, não 6
            blocos.append("[[VENDA]]")
            ultima_venda = acum
    return "\n\n".join(blocos), caps
