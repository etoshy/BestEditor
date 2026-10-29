"""
poker_doc.py — 🎬 roteiros de poker (documentário, tutorial, história de jogador) (v84_277)
==========================================================================================

Você escreve o tema e o que já sabe (ex.: "o gênio do poker" + infância, vida, torneios que jogou — detalhado ou não):
  1. 🔎 a pesquisa expande: a 🔎 IA do Google (Modo IA, com fontes) busca biografia, torneios e as MÃOS famosas
     (jogadores, stacks, cartas, ações) — e você pode colar o que achou em outras IAs/sites;
  2. ✍ a IA escreve o roteiro: narração divertida (não uma aula de 100% análise), com o contexto antes e depois de
     cada jogada e a melhor estratégia explicada simples; MÃOS só onde ajudam a entender (as decisivas), cada uma no
     formato da 🃏 mesa e marcada como ✅ real (com fonte), 🔁 reconstruída (resultado real, detalhes aproximados) ou
     💡 ilustrativa (exemplo);
  3. ✅ checagem: o prompt de checagem pra colar em outra IA (o mesmo do 🕵️ true crime) e/ou a checagem na web;
  4. cada mão vira a mesa animada (poker_render) e a narração vai junto pro editor/voz.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import poker_mesa as PM

TRAVA = threading.RLock()
STATUS_MAO = {"real": "✅ real (com fonte)", "reconstruida": "🔁 reconstruída (resultado real, detalhes aproximados)",
              "ilustrativa": "💡 ilustrativa (exemplo pra explicar)"}
TIPOS = {"documentario": "🎬 documentário / história de jogador", "tutorial": "🎓 tutorial / estratégia",
         "mao_famosa": "🃏 análise de uma mão famosa", "curiosidade": "💡 curiosidade / história do poker",
         "shorts": "⚡ shorts: jogada insana (30–60 s, 1 mão, gancho forte)"}


def _pasta(base: str) -> str:
    p = os.path.join(os.environ.get("POKER_DIR") or os.path.join(base, "poker"), "docs")
    os.makedirs(p, exist_ok=True)
    return p


def _cam(base: str, did: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{10}", str(did or "")):
        raise PM.PokerErro("Roteiro não encontrado.")
    return os.path.join(_pasta(base), f"{did}.json")


def carregar(base: str, did: str) -> Dict[str, Any]:
    try:
        with open(_cam(base, did), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        raise PM.PokerErro("Roteiro não encontrado.") from exc


def salvar(base: str, d: Dict[str, Any]) -> None:
    with TRAVA:
        d["atualizado"] = time.time()
        c = _cam(base, d["id"])
        tmp = c + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, c)


def listar(base: str) -> List[Dict[str, Any]]:
    out = []
    for f in sorted(os.listdir(_pasta(base))):
        if f.endswith(".json"):
            try:
                out.append(carregar(base, f[:-5]))
            except PM.PokerErro:
                pass
    return sorted(out, key=lambda d: -float(d.get("criado") or 0))


def novo(base: str, tema: str, infos: str = "", tipo: str = "documentario", idioma: str = "pt", minutos: float = 8.0,
         moeda: str = "R$") -> Dict[str, Any]:
    if not str(tema or "").strip():
        raise PM.PokerErro("Escreva o tema do vídeo.")
    d = {"id": secrets.token_hex(5), "tema": " ".join(str(tema).split())[:200], "infos": str(infos or "").strip()[:12000],
         "tipo": tipo if tipo in TIPOS else "documentario", "idioma": idioma or "pt",
         "minutos": max(1.0, min(40.0, float(minutos or 8))), "moeda": (str(moeda or "R$").strip() or "R$")[:6], "pesquisa": {"texto": "", "fontes": []}, "notas_pesquisa": "",
         "titulo": "", "blocos": [], "titulos": [], "checagem": None, "criado": time.time()}
    salvar(base, d)
    return d


# ------------------------------------------------------------------ 🔎 pesquisa (IA do Google, com fontes)
def pergunta_pesquisa(d: Dict[str, Any]) -> str:
    return (f"Pesquise na web, com fontes confiáveis (Wikipedia, Hendon Mob, PokerNews, sites dos torneios, entrevistas), "
            f"para um vídeo sobre: {d['tema']}.\n"
            + (f"O que eu já sei (confira e complete): {d['infos'][:3000]}\n" if d.get("infos") else "")
            + "Quero: 1) biografia (infância, como começou, vida fora do poker, momentos marcantes); 2) carreira — torneios, "
            "títulos, ganhos, rivalidades, apelidos, polêmicas; 3) as MÃOS MAIS FAMOSAS/decisivas, cada uma com: evento e ano, "
            "nível de blinds, os jogadores, stacks aproximados, as cartas de cada um, o board e as ações rua por rua — diga o "
            "que é registrado e o que é incerto; 4) estilo de jogo e o que dá pra aprender com ele. Liste as fontes.")


def pesquisar(base: str, did: str, pesquisar_fn: Optional[Callable[[str], Dict[str, Any]]] = None) -> Dict[str, Any]:
    d = carregar(base, did)
    if pesquisar_fn is None:
        import ia_google_rotas
        pesquisar_fn = lambda q: ia_google_rotas.pesquisar(q, nova_conversa=True, timeout=420)  # noqa: E731
    r = pesquisar_fn(pergunta_pesquisa(d)) or {}
    texto = str(r.get("resposta_completa") or r.get("resposta_objetiva") or "").strip()
    if not texto:
        raise PM.PokerErro("A pesquisa não voltou nada (a 🔎 IA do Google está ligada?). Dá pra colar a pesquisa à mão.")
    with TRAVA:
        d = carregar(base, did)
        d["pesquisa"] = {"texto": texto[:30000], "fontes": [{k: str(f.get(k) or "")[:300] for k in ("titulo", "site", "url", "trecho")}
                                                              for f in r.get("fontes") or []][:40], "quando": time.time()}
        salvar(base, d)
    return d


# ------------------------------------------------------------------ ✍ roteiro
MAO_SCHEMA = {"type": "object", "properties": {
    "titulo": {"type": "string"}, "por_que": {"type": "string"}, "contexto_antes": {"type": "string"},
    "contexto_depois": {"type": "string"}, "estrategia": {"type": "string"}, "status": {"type": "string"},
    "fonte": {"type": "string"}, "mao": {"type": "string"}},
    "required": ["titulo", "por_que", "contexto_antes", "contexto_depois", "estrategia", "status", "fonte", "mao"], "additionalProperties": False}
GRAF_ITEM = {"type": "object", "properties": {k: {"type": "string"} for k in ("rotulo", "valor", "ano", "texto")},
             "required": ["rotulo", "valor", "ano", "texto"], "additionalProperties": False}
GRAF_SCHEMA = {"type": "object", "properties": dict({k: {"type": "string"} for k in ("tipo", "titulo", "subtitulo", "texto", "autor", "numero", "pais")},
                                                   itens={"type": "array", "items": GRAF_ITEM}),
               "required": ["tipo", "titulo", "subtitulo", "texto", "autor", "numero", "pais", "itens"], "additionalProperties": False}
BLOCO_SCHEMA = {"type": "object", "properties": {
    "tipo": {"type": "string"}, "texto": {"type": "string"}, "visual": {"type": "string"}, "grafico": GRAF_SCHEMA, "mao": MAO_SCHEMA},
    "required": ["tipo", "texto", "visual", "grafico", "mao"], "additionalProperties": False}
ROTEIRO_SCHEMA = {"type": "object", "properties": {
    "titulo": {"type": "string"}, "titulos": {"type": "array", "items": {"type": "string"}},
    "blocos": {"type": "array", "items": BLOCO_SCHEMA}},
    "required": ["titulo", "titulos", "blocos"], "additionalProperties": False}

ROTEIRO_SYS = (
    "Você é roteirista de um canal de POKER no YouTube — divertido de assistir, como uma boa história contada por um "
    "amigo que entende muito do jogo (não uma aula seca de 100% análise). Escreva o roteiro narrado em BLOCOS:\n"
    "• tipo 'narracao': o texto que o narrador fala ('texto') e o que aparece na tela ('visual': foto/arquivo, gráfico, "
    "título na tela…). Frases curtas, ritmo de vídeo, ganchos, humor leve, curiosidades; explique termos de poker numa "
    "frase quando aparecerem pela primeira vez. 'grafico' = a PEÇA na tela enquanto o narrador fala (motion graphics): "
    "tipo 'titulo' (abertura de capítulo: titulo, subtitulo, numero = nº do capítulo) · 'jogador' (cartão: titulo = nome, "
    "subtitulo = apelido, pais = BR/US…, itens = [{rotulo, valor}] com os números dele: nascimento, títulos, ganhos) · "
    "'linha_do_tempo' (titulo, itens = [{ano, texto}]) · 'grafico' ou 'barras' (titulo, subtitulo, itens = [{rotulo, "
    "valor}] — fichas ao longo do torneio, ganhos por ano) · 'citacao' (texto = a frase, autor) · 'fato' (numero = o "
    "valor grande tipo \"US$ 2,5 milhões\", texto = o contexto) · 'midia' (quando o 'visual' é uma foto/arquivo que o "
    "criador vai colocar; texto = legenda) · '' (nenhuma: a frase-chave do bloco aparece sobre o fundo). Varie as peças; "
    "use dados SÓ da pesquisa. Nos blocos de mão, 'grafico' com campos vazios.\n"
    "• tipo 'mao': uma MÃO na mesa animada — SÓ quando ela é necessária pra entender a história (a mão decisiva, a "
    "jogada genial, o blefe famoso, o erro que custou caro). Não encha de mãos: {MAOS}. Cada mão tem: 'titulo'; "
    "'por_que' (por que mostrar essa); 'contexto_antes' (o que estava em jogo: torneio, fase, quem é quem, a pressão) "
    "e 'contexto_depois' (o que aconteceu depois, o impacto) — ambos em narração; 'estrategia' (a melhor linha / o que "
    "aprender, simples e direto); 'status' = 'real' (registrada, com fonte), 'reconstruida' (o resultado é real mas "
    "stacks/ações são aproximados) ou 'ilustrativa' (exemplo inventado pra explicar um conceito) — NUNCA apresente "
    "como real o que você não tem certeza; 'fonte' (de onde veio, ou ''); e 'mao' no FORMATO DA MESA (abaixo). No "
    "'texto' do bloco de mão, a narração DURANTE a mão (curta). Nos outros blocos, 'mao' com campos vazios.\n"
    "FORMATO DA MESA (texto, uma coisa por linha):\n"
    "mesa: blinds=50000/100000 unidade=fichas titulo=\"WSOP 2003 — mesa final\"\n"
    "jogador: Fulano 4.5 As Kd heroi      (nome, stack, cartas; 'heroi' = a vista principal)\n"
    "jogador: Ciclano 3.2 Qh Qs\n"
    "botao: Fulano\n"
    "preflop: Ciclano raise 300000; Fulano allin; Ciclano call\n"
    "flop: 7c 2d 9h | Ciclano check; Fulano bet 500000\n"
    "turn: Ks | ...      river: 3c | ...\n"
    "nota: texto curto que aparece na tela naquele momento (opcional, a qualquer hora)\n"
    "camera: Ciclano     (opcional: gira a mesa pra vista dele)\n"
    "EFEITOS NARRATIVOS (use como ferramenta de história, não enfeite — só onde deixa a mão mais imersiva/clara):\n"
    "• POV: 'mostrar: pov' = o espectador só vê as cartas de quem está na vista; junto com 'camera: Fulano' a vista "
    "troca e as cartas do outro somem — ótimo pra suspense ('o que ELE via naquele momento'). 'mostrar: todas' revela "
    "tudo (bom pra explicar a estratégia); 'mostrar: heroi' = só o herói. Pode trocar no meio da mão.\n"
    "• Dentro das ações, entre colchetes, no momento exato: [zoom: Fulano] / [zoom: board] / [zoom: pot] / [zoom: off] "
    "(aproxima a câmera — use no all-in decisivo, numa leitura, no river), [camera: Fulano], [mostrar: pov], "
    "[nota: texto], [emocao: Fulano ansioso \"frase curta do que ele pensava\"] — emoções: irritado, ansioso, nervoso, "
    "confiante, chocado, pensativo, blefando, aliviado, desesperado, comemorando (ou um emoji). Use emoção SÓ quando a "
    "pesquisa/entrevista conta como o jogador se sentiu, ou quando ajuda a contar a história (marque como dramatização "
    "no texto se não for registrado). Ex.: 'river: 7c | Ciclano check; [zoom: Fulano]; Fulano allin; [emocao: Ciclano "
    "pensativo \"ele tem o flush?\"]; Ciclano call; [zoom: off]'.\n"
    "• ESTRATÉGIA (tutorial/explicação): mesa: estrategia=sim mostra na decisão quanto paga, a % que precisa (pot "
    "odds), a que tem, o EV do call e o SPR; 'range: Fulano AA-TT, AKs, AQo+, 22+' (ou 'top 15%') mostra a grade 13×13 "
    "do range dele com a mão real marcada — use pra explicar uma leitura.\n"
    "• ACORDOS: 'acordo: dividir' / 'acordo: equidade' / 'acordo: Fulano 60 Ciclano 40' (a mão acaba ali); RUN IT TWICE: "
    "'correr: 2' depois do all-in + 'board2: …' com as cartas que faltavam (cada board vale metade).\n"
    "• Na linha mesa: jogo=holdem|plo|plo5|6+|stud|draw (modalidade; Omaha já é pot-limit; limite=pl força; "
    "straddle=sim); Stud: 'jogador: Nome 200 As Ks Ah 7d 9c Kh 2s' (as 7 na ordem, 3ª a 6ª abertas) e ruas '3a: … 4a: … "
    "até 7a:'; Draw: 'preflop: …', 'troca: Fulano 7c 2s > Ks 5d; Ciclano fica', 'pos: …'; estetica=vegas70|tv2000|neon80|noir|macau|monaco|brasil|moderno "
    "(combine com a ÉPOCA e o LUGAR da história: anos 70 em Vegas = vegas70; WSOP 2003 na TV = tv2000; jogo "
    "clandestino = noir; Macau = macau; EPT Monte Carlo = monaco); 'jogador: Nome 100 As Kd pais=BR' (bandeira).\n"
    "• DINHEIRO: se o valor importa pra história (prêmio da vida, aposta absurda), use a moeda real da época na mesa "
    "(unidade=US$ / R$ / € e os valores reais) e mesa: dinheiro=\"US$ 2,5 milhões em 2003 ≈ {MOEDA} X hoje — dava pra "
    "comprar Y\" (adaptado à moeda do canal: {MOEDA}, com um exemplo do que comprava na época). Se o dinheiro não importa "
    "(o foco é a jogada), use unidade=fichas (ou bb) e conte em fichas — sem 'dinheiro='.\n"
    "Regras: valores na unidade da mesa (use 'bb' com blinds=0.5/1 quando não souber os valores exatos); 'raise X' = "
    "aumenta PARA X; cartas As Kd Th 9c (T = 10); 2 a 9 jogadores (os que não importam podem ficar de fora); quem chega "
    "ao showdown precisa das 2 cartas; o board completo se a mão vai até o fim; sem carta repetida.\n"
    "Duração do vídeo ≈ {MIN} minutos (≈ 150 palavras de narração por minuto). Idioma: {IDIOMA}. 'titulos': 5 títulos "
    "chamativos. Fatos (nomes, datas, valores, resultados) SÓ da pesquisa/do criador — o que for incerto, diga que é "
    "incerto ou atribua ('segundo a PokerNews…')."
)


def _conteudo(d: Dict[str, Any]) -> str:
    partes = [f"TEMA: {d['tema']}", f"TIPO DE VÍDEO: {TIPOS.get(d['tipo'], d['tipo'])}"]
    if d.get("tipo") == "shorts":
        partes.append("FORMATO SHORTS: 1 mão só, a jogada insana. Comece pelo gancho (a frase que prende nos 2 primeiros "
                      "segundos — vai na mesa como gancho=\"...\" e ritmo=shorts), conte rapidinho o contexto, mostre a mão "
                      "(POV pra criar suspense, zoom no all-in) e feche com a reação/o resultado. Narração curta (≈ 130 palavras).")
    if d.get("infos"):
        partes.append(f"O QUE O CRIADOR SABE / QUER:\n{d['infos']}")
    if (d.get("pesquisa") or {}).get("texto"):
        fontes = "\n".join(f"- {f.get('titulo')} ({f.get('site') or f.get('url')})" for f in d["pesquisa"].get("fontes") or [])
        partes.append(f"PESQUISA (web, com fontes):\n{d['pesquisa']['texto'][:20000]}\nFONTES:\n{fontes}")
    if d.get("notas_pesquisa"):
        partes.append(f"PESQUISA COLADA PELO CRIADOR (outras IAs/sites):\n{d['notas_pesquisa'][:15000]}")
    return "\n\n".join(partes)


def validar_mao(texto: str) -> Dict[str, Any]:
    """Roda a mão no motor: {ok, erro, duracao, resumo}."""
    try:
        r = PM.simular(texto)
        ganhou = next((e for e in reversed(r["eventos"]) if e["tipo"] == "vencedor"), None)
        res = ""
        if ganhou:
            nomes = [r["jogadores"][i]["nome"] for i in ganhou["dados"]["quem"]]
            jogos = ganhou["depois"].get("jogos") or {}
            res = f"{' e '.join(nomes)} leva(m) {PM._fmt(ganhou['dados']['pot'])}" + (
                f" — {jogos.get(ganhou['dados']['quem'][0]) or jogos.get(str(ganhou['dados']['quem'][0]))}" if jogos else "")
        return {"ok": True, "erro": "", "duracao": r["duracao"], "resumo": res}
    except PM.PokerErro as exc:
        return {"ok": False, "erro": str(exc), "duracao": 0, "resumo": ""}


def escrever(base: str, did: str, max_maos: int = 0, chamar: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    import ia_servico
    d = carregar(base, did)
    n = max_maos or (1 if d["minutos"] <= 3 or d["tipo"] == "shorts" else 3 if d["minutos"] <= 10 else 5)
    sistema = (ROTEIRO_SYS.replace("{MAOS}", f"no máximo {n} mão(s) no vídeo inteiro").replace("{MOEDA}", d.get("moeda") or "R$")
               .replace("{MIN}", f"{d['minutos']:g}").replace("{IDIOMA}", "português do Brasil" if d["idioma"] == "pt" else d["idioma"]))
    r = (chamar or ia_servico.chamar)("curtos", sistema, _conteudo(d), schema=ROTEIRO_SCHEMA, max_tokens=16000, timeout=300, job=did)
    if not r:
        try:
            import curtos as CT
            motivo = CT.motivo_ia()
        except Exception:  # noqa: BLE001
            motivo = "a IA não respondeu"
        raise PM.PokerErro(motivo)
    blocos = []
    for b in r.get("blocos") or []:
        tipo = "mao" if b.get("tipo") == "mao" and str((b.get("mao") or {}).get("mao") or "").strip() else "narracao"
        x = {"id": secrets.token_hex(4), "tipo": tipo, "texto": str(b.get("texto") or "").strip(), "visual": str(b.get("visual") or "").strip()}
        if tipo == "narracao":
            import poker_graficos as PG
            x["grafico"] = PG.normalizar(b.get("grafico"))
        if tipo == "mao":
            m = b["mao"]
            x["mao"] = {k: str(m.get(k) or "").strip() for k in MAO_SCHEMA["properties"]}
            if x["mao"]["status"] not in STATUS_MAO:
                x["mao"]["status"] = "ilustrativa"
            x["validacao"] = validar_mao(x["mao"]["mao"])
            x["video"] = None
        blocos.append(x)
    if not blocos:
        raise PM.PokerErro("A IA não devolveu o roteiro — tente de novo.")
    with TRAVA:
        d = carregar(base, did)
        if d.get("blocos"):
            d["blocos_anteriores"] = d["blocos"]
        d["blocos"] = blocos
        d["titulo"] = str(r.get("titulo") or d["tema"])[:200]
        d["titulos"] = [str(t)[:200] for t in r.get("titulos") or []][:8]
        salvar(base, d)
    return d


def salvar_blocos(base: str, did: str, blocos: List[Dict[str, Any]]) -> Dict[str, Any]:
    with TRAVA:
        d = carregar(base, did)
        velhos = {b["id"]: b for b in d.get("blocos") or []}
        novos = []
        for b in blocos[:200]:
            v = velhos.get(str(b.get("id") or ""), {})
            x = {"id": v.get("id") or secrets.token_hex(4), "tipo": "mao" if b.get("tipo") == "mao" else "narracao",
                 "texto": str(b.get("texto") or "")[:6000], "visual": str(b.get("visual") or "")[:1000]}
            if x["tipo"] == "narracao":
                import poker_graficos as PG
                g = PG.normalizar(b["grafico"] if "grafico" in b else v.get("grafico"))
                g["arquivo"] = g.get("arquivo") or (v.get("grafico") or {}).get("arquivo") or ""
                x["grafico"] = g
            if x["tipo"] == "mao":
                m = b.get("mao") or {}
                x["mao"] = {k: str(m.get(k) or "")[:8000] for k in MAO_SCHEMA["properties"]}
                if x["mao"]["status"] not in STATUS_MAO:
                    x["mao"]["status"] = "ilustrativa"
                mudou = x["mao"]["mao"] != (v.get("mao") or {}).get("mao")
                x["validacao"] = validar_mao(x["mao"]["mao"]) if mudou or not v.get("validacao") else v["validacao"]
                x["video"] = None if mudou else v.get("video")
            novos.append(x)
        d["blocos"] = novos
        salvar(base, d)
        return d


def texto_narracao(d: Dict[str, Any]) -> str:
    """O roteiro inteiro pra narrar (o que o narrador fala, com as mãos no meio marcadas)."""
    out = [d.get("titulo") or d["tema"], ""]
    for k, b in enumerate(d.get("blocos") or [], 1):
        if b["tipo"] == "mao":
            m = b["mao"]
            out += [f"[🃏 MÃO: {m['titulo']} — {STATUS_MAO.get(m['status'], '')}]", m["contexto_antes"], b["texto"],
                    f"(estratégia) {m['estrategia']}" if m.get("estrategia") else "", m["contexto_depois"], ""]
        else:
            out += [b["texto"], ""]
    return "\n".join(x for x in out if x is not None).strip() + "\n"


def prompt_checagem(d: Dict[str, Any]) -> str:
    """✅ o prompt de checagem (o mesmo do 🕵️ true crime) pra colar em outra IA, com as mãos e as fontes."""
    import checagem_roteiro as CR
    fontes = "\n".join(f"- {f.get('titulo')} — {f.get('url')}" for f in (d.get("pesquisa") or {}).get("fontes") or [])
    p = CR.prompt(texto_narracao(d), "português do Brasil" if d.get("idioma") == "pt" else d.get("idioma"), d["tema"], fontes)
    maos = [b for b in d.get("blocos") or [] if b["tipo"] == "mao"]
    if maos:
        p += ("\n\n## 4. 🃏 AS MÃOS\nConfira também cada mão (cartas, board, quem fez o quê, stacks, resultado) contra os "
              "registros (vídeo da transmissão, PokerNews, livros). Se não bate, diga o certo; se não há registro, ela tem "
              "que ficar marcada como reconstruída ou ilustrativa.\n")
        for b in maos:
            p += f"\n### {b['mao']['titulo']} ({b['mao']['status']}; fonte: {b['mao']['fonte'] or '—'})\n{b['mao']['mao']}\n"
    return p


def checar_web(base: str, did: str, fn: Optional[Callable[[str], Dict[str, Any]]] = None) -> Dict[str, Any]:
    """✅ checa as afirmações do roteiro na web (🔎 IA do Google) — guarda a resposta com as fontes."""
    d = carregar(base, did)
    if fn is None:
        import ia_google_rotas
        fn = ia_google_rotas.checar_fatos
    r = fn(texto_narracao(d)) or {}
    texto = str(r.get("resposta_completa") or r.get("resposta_objetiva") or "").strip()
    if not texto:
        raise PM.PokerErro("A checagem não voltou nada (a 🔎 IA do Google está ligada?). Use o prompt pra colar em outra IA.")
    with TRAVA:
        d = carregar(base, did)
        d["checagem"] = {"origem": "web", "texto": texto[:20000], "quando": time.time(),
                         "fontes": [{k: str(f.get(k) or "")[:300] for k in ("titulo", "site", "url")} for f in r.get("fontes") or []][:30]}
        salvar(base, d)
    return d


def ler_checagem(base: str, did: str, resposta: str) -> Dict[str, Any]:
    """Cola a resposta (JSON) da outra IA: guarda as correções / o que verificar."""
    import checagem_roteiro as CR
    try:
        r = CR.ler(resposta)
    except ValueError as exc:
        raise PM.PokerErro(str(exc)) from exc
    with TRAVA:
        d = carregar(base, did)
        d["checagem"] = {"origem": "ia", "trocas": r.get("trocas") or [], "verificar": r.get("verificar") or [],
                         "inconsistencias": r.get("inconsistencias") or [], "resumo": r.get("resumo") or "", "quando": time.time()}
        salvar(base, d)
    return d


def aplicar_trocas(base: str, did: str, indices: Optional[List[int]] = None) -> Dict[str, Any]:
    """Aplica as correções da checagem (trecho "de" → "para") nos textos dos blocos e das mãos."""
    with TRAVA:
        d = carregar(base, did)
        trocas = (d.get("checagem") or {}).get("trocas") or []
        feitas = 0
        for k, t in enumerate(trocas):
            if indices is not None and k not in indices or t.get("aplicada"):
                continue
            for b in d.get("blocos") or []:
                alvos = [(b, "texto"), (b, "visual")] + ([(b["mao"], c) for c in ("contexto_antes", "contexto_depois", "estrategia", "por_que")]
                                                          if b.get("tipo") == "mao" else [])
                for obj, campo in alvos:
                    if t["de"] and t["de"] in (obj.get(campo) or ""):
                        obj[campo] = obj[campo].replace(t["de"], t.get("para") or "")
                        t["aplicada"] = True
            feitas += 1 if t.get("aplicada") else 0
        salvar(base, d)
    d["_feitas"] = feitas
    return d


MAO_SYS = ("Converta a descrição de uma mão de poker (Texas Hold'em) no FORMATO DA MESA. Responda só com o texto no formato, "
           "sem explicação. Se faltar algo (stacks, cartas de quem foldou), invente valores plausíveis e coerentes.\n"
           + ROTEIRO_SYS[ROTEIRO_SYS.index("FORMATO DA MESA"):ROTEIRO_SYS.index("Duração do vídeo")].replace("{MOEDA}", "R$"))


def mao_de_descricao(descricao: str, chamar: Optional[Callable[..., Any]] = None) -> str:
    """🤖 'descreva em português' → o texto da mesa (validado no motor; 1 tentativa de correção)."""
    import ia_servico
    fn = chamar or ia_servico.chamar
    schema = {"type": "object", "properties": {"mao": {"type": "string"}}, "required": ["mao"], "additionalProperties": False}
    pedido = str(descricao or "").strip()[:6000]
    if not pedido:
        raise PM.PokerErro("Descreva a mão.")
    erro = ""
    for _ in range(2):
        r = fn("curtos", MAO_SYS, pedido + (f"\n\nA versão anterior deu erro no motor: {erro} — corrija." if erro else ""),
               schema=schema, max_tokens=3000, timeout=120)
        txt = str((r or {}).get("mao") or "").strip()
        if not txt:
            raise PM.PokerErro("A IA não respondeu.")
        v = validar_mao(txt)
        if v["ok"]:
            return txt
        erro = v["erro"]
    return txt
