"""
prompt_builder.py
===================

A peça que faltava no pipeline: pega a transcrição do Whisper (com
timestamps) e monta o texto do prompt pronto pra colar em outra IA
(ChatGPT, Claude, etc.), pedindo de volta um JSON com um trecho de
vídeo (busca + provedor + início/fim) para cada parte do áudio.

Fluxo completo:
    áudio -> Whisper (transcribe_audio) -> segments com timestamps
        -> build_prompt(segments, ...) -> texto pra colar na outra IA
        -> [você cola na IA, ela devolve um JSON]
        -> parse_ai_response(json_text) -> lista de VideoSegment validada
        -> (fora deste arquivo) busca/baixa cada vídeo e monta o final

Uso
----
    from prompt_builder import build_prompt, parse_ai_response

    prompt_text = build_prompt(segments, interval_seconds=7, providers=["pexels", "pixabay"])
    # ... copia prompt_text, cola na IA, copia a resposta dela ...
    video_segments = parse_ai_response(resposta_da_ia)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

DEFAULT_PROVIDERS = ["pexels", "pixabay", "magnific", "mixkit", "vistacreate", "animepexels", "moviepexels", "animepexels_online", "moviepexels_online", "wikipedia", "bing", "brave", "yandex", "startpage", "flow", "youtube"]
PHOTO_SEARCH_PROVIDERS = {"pexels", "wikipedia", "bing", "brave", "yandex", "startpage", "flow"}  # provedores que suportam media_type="image" (busca de fotos de verdade)
# os 4 buscadores de imagem por navegador (bing/brave/yandex/startpage) --
# usado tanto aqui (build_prompt) quanto em app.py (checkbox "usar
# buscadores inteligente") e buscadores_enrichment.py, pra não espalhar
# essa mesma tupla em vários lugares.
BROWSER_IMAGE_SEARCH_PROVIDERS = ("bing", "brave", "yandex", "startpage")
# Provedores de VÍDEO que não são buscados/baixados automaticamente: o site
# já pesquisa os termos sozinho, mas quem escolhe o vídeo certo e a faixa de
# tempo é a pessoa, no painel "Vídeos do YouTube" do editor (escolher QUAL
# trecho de um vídeo longo usar não dá pra automatizar bem).
MANUAL_VIDEO_PROVIDERS = ("youtube",)


class PromptBuilderError(Exception):
    """Erro genérico (segmentos inválidos, JSON de resposta inválido, etc.)."""



def _regra_idioma(language_hint: str) -> str:
    """Regra "o vídeo fala um idioma só" (idiomas.py) pro idioma da narração."""
    try:
        import idiomas
        return idiomas.regra_para_prompt(language_hint)
    except Exception:  # noqa: BLE001
        return f"Todo texto que aparece no vídeo tem que estar em {language_hint}, o idioma da narração."

# Bancos de ESTOQUE: acham clipe pelas ETIQUETAS (em inglês) — é pra eles que
# vale a guia "como escrever a busca". Os outros provedores têm regra própria
# (wikipedia = nome exato, buscadores = termo preciso, flow = descrição, etc.).
STOCK_PROVIDERS = ("pexels", "pixabay", "magnific", "mixkit", "vistacreate")

# Muitos trechos = resposta longa: acima disso a guia pede "visual" mais curto
# e 1 alternativa só, pra IA não cortar o JSON no meio.
_TRECHOS_RESPOSTA_LONGA = 90


def _guia_buscas(providers: List[str], n_trechos: int = 0) -> str:
    """Seção "como escrever a busca" — o que mais decide a qualidade do vídeo.

    As IAs erram sempre do mesmo jeito: termo abstrato ("success concept"),
    nome próprio num banco de estoque, duas cenas numa busca só, palavra que
    polui ("4k footage"), a mesma busca em sequência e nenhuma identidade
    visual. A guia ataca cada um desses com regra + exemplo, e pede a imagem
    ANTES da busca ("visual") — escrever a cena primeiro melhora muito a busca.
    Vazia quando nenhum banco de estoque foi selecionado."""
    estoque = [p for p in providers if p in STOCK_PROVIDERS]
    if not estoque:
        return ""
    nomes = ", ".join(f'"{p}"' for p in estoque)
    proprios = [p for p in ("wikipedia",) + BROWSER_IMAGE_SEARCH_PROVIDERS + MANUAL_VIDEO_PROVIDERS if p in providers]
    nota_nomes = (
        " Quando o nome próprio PRECISA aparecer de verdade (o rosto daquela pessoa, aquele produto), use "
        + " / ".join(f'"{p}"' for p in proprios) + ", como explicado nas regras acima."
    ) if proprios else ""
    linhas = [
        "## Como escrever a busca de cada trecho — é o que mais decide a qualidade do vídeo",
        "",
        f"Os bancos de estoque ({nomes}) não entendem a narração: devolvem os clipes cujas ETIQUETAS (tags em inglês "
        "simples) batem com as palavras da busca. E etiqueta descreve só o que se VÊ: pessoa, objeto, ação, lugar, luz. "
        "Então uma boa busca é a legenda curta do clipe que você quer na tela, escrita do jeito que um fotógrafo "
        "etiquetaria esse clipe.",
        "",
        "Em cada trecho, nesta ordem:",
        "a) \"visual\" — decida a IMAGEM antes da busca, como um editor de documentário escolhendo o B-roll: o que o "
        "espectador deve ver enquanto ouve esse trecho? Em português, curto (até ~12 palavras). Se a fala for abstrata, "
        "escreva aqui a tradução concreta (ex.: \"fala de crise → lojas fechadas com a porta de aço baixada\").",
        "b) \"query\" — a busca em inglês, 2 a 5 palavras: [quem/o quê] + [fazendo o quê / em que estado] + [onde/quando]. "
        "Ex.: \"old man reading letter\", \"empty classroom at night\", \"hands counting cash\".",
        "c) \"alternativas\" — 1 ou 2 buscas de reserva, cada uma MAIS SIMPLES e mais comum, ainda mostrando a mesma ideia "
        "(ex.: \"old man reading letter\" → [\"man reading letter\", \"old letter close up\"]). O site usa sozinho quando "
        "a principal não acha nada — sem elas ele cai num termo genérico que quase nunca combina.",
        "",
        "Regras de ouro:",
        "- CONCRETO, nunca abstrato. Ideia não se filma (medo, sucesso, crise, liberdade, solidão, futuro, \"o tempo "
        "passou\"): mostre algo que a represente. \"a economia desabou\" → \"closed shop shutters\"; \"ele sentiu medo\" → "
        "\"man breathing heavily in the dark\"; \"anos se passaram\" → \"clock timelapse\"; \"solidão\" → \"person sitting "
        "alone on bench\".",
        "- Se a fala cita uma coisa concreta e comum (cachorro, chuva, hospital, dinheiro, criança, carro), MOSTRE essa "
        "coisa — o literal ganha do criativo.",
        "- Nada que banco de estoque não tem: nome de pessoa real, marca, produto específico, personagem, título de "
        "filme/livro, ano, número ou texto escrito. Troque pelo TIPO da coisa: \"Elon Musk\" → \"businessman speaking on "
        "stage\"; \"iPhone\" → \"smartphone in hand\"; \"em 1929\" → \"vintage black and white street\". Cidades e lugares "
        "famosos funcionam (\"tokyo street at night\", \"eiffel tower paris\")." + nota_nomes,
        "- UMA coisa por busca. Não junte duas cenas (\"man running and dog barking\") nem empilhe adjetivos (\"beautiful "
        "amazing dramatic sunset\") — o clipe mostra uma coisa só, e cada palavra a mais é mais um filtro que pode zerar "
        "a busca.",
        "- Sem palavras que só poluem: \"4k\", \"HD\", \"footage\", \"stock\", \"video\", \"clip\", \"concept\", "
        "\"background\" (a menos que queira mesmo um fundo), e nada de negação (\"no people\" acha gente).",
        "- Época e lugar pelo que se vê: passado → \"vintage\", \"old\", \"black and white\", \"medieval\", \"ancient "
        "ruins\"; lugar sem fama → o tipo dele (\"small village street\", \"desert highway\", \"hospital corridor\").",
        "- Emoção → rosto e corpo: \"woman crying by window\", \"tired man rubbing eyes\", \"child laughing\". Combine "
        "idade, gênero e época com quem a história fala.",
        "- IDENTIDADE VISUAL: decida o clima do vídeo inteiro antes de começar (terror → dark, night, fog, abandoned; "
        "motivação → sunrise, running, mountain top; finanças → office, city skyline, charts on screen) e repita essas "
        "palavras de clima nas buscas onde couber — é o que faz o vídeo parecer um vídeo só e não uma colagem. Ponha esse "
        "clima em \"busca_reserva\" (na raiz do JSON): uma busca genérica com a cara do vídeo, usada só quando nada mais "
        "achar (ex.: \"dark foggy forest at night\").",
        "- VARIE O PLANO: nunca a mesma busca em dois trechos seguidos. Quando a fala fica muito tempo no mesmo assunto, "
        "alterne geral → médio → detalhe (\"hacker in dark room\" → \"code scrolling on screen\" → \"hands typing on "
        "keyboard\" → \"server room lights\").",
        "- Tempo certo: o corte acontece no INÍCIO do trecho, então a imagem tem que combinar com o que está sendo dito "
        "ali — não com a frase seguinte.",
    ]
    if "mixkit" in estoque:
        linhas.append("- No \"mixkit\" a \"query\" e as \"alternativas\" continuam sendo CATEGORIAS do site, não frases.")
    if n_trechos > _TRECHOS_RESPOSTA_LONGA:
        linhas.append(
            f"- Este vídeo tem muitos trechos (~{n_trechos}): mantenha \"visual\" bem curto (até 8 palavras) e dê só 1 "
            "alternativa por trecho, pra resposta não ficar longa demais."
        )
    linhas += [
        "",
        "Exemplos (fala → busca ruim → busca boa):",
        "- \"A inflação corroeu o salário das famílias\" → \"inflation\" → \"family counting money at kitchen table\"",
        "- \"Ninguém sabe o que aconteceu naquela noite\" → \"mystery night unknown\" → \"empty dark road at night\"",
        "- \"Ele dedicou a vida inteira aos estudos\" → \"dedication success concept\" → \"old man studying books by lamp\"",
        "- \"Em 2008, os bancos quebraram\" → \"2008 financial crisis Lehman Brothers\" → \"stock market crash red screen\"",
        "- \"Ela sentia que ninguém a ouvia\" → \"loneliness sadness depression\" → \"woman sitting alone in crowd\"",
    ]
    return "\n".join(linhas)


def _format_timestamp(seconds: float) -> str:
    """Formata segundos como MM:SS.mmm, só pra deixar o prompt legível
    pra quem for conferir (a IA usa os números decimais mesmo)."""
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    return f"{minutes:02d}:{secs:06.3f}"


# Acervos LOCAIS (anime-pexels-local): um servidor, dois catálogos.
BIBLIOTECAS_LOCAIS = ("animepexels", "moviepexels", "animepexels_online", "moviepexels_online")  # + as online (acervos.py)
_BIB_INFO = {
    "animepexels_online": {"nome": "acervo ONLINE de clipes de ANIME", "obra": "anime", "pessoa": "personagem",
                           "pessoas": "personagens"},
    "moviepexels_online": {"nome": "acervo ONLINE de clipes de FILMES E SÉRIES, live-action", "obra": "filme/série",
                           "pessoa": "personagem/ator", "pessoas": "personagens/atores"},
    "animepexels": {"nome": "acervo local de clipes de ANIME", "obra": "anime", "pessoa": "personagem",
                    "pessoas": "personagens"},
    "moviepexels": {"nome": "acervo local de clipes de FILMES E SÉRIES, live-action", "obra": "filme/série",
                    "pessoa": "personagem/ator", "pessoas": "personagens/atores"},
}


def _regra_bibliotecas(bibliotecas: Optional[Dict[str, Any]], providers: List[str]) -> List[str]:
    """Regras de obra e personagem/ator pros acervos locais marcados.

    `bibliotecas`: {"animepexels"|"moviepexels": {"obra": str, "personagem": str,
    "obras": [nomes], "personagens": [{"nome", "clipes"}]}} — obra/personagem
    fixados pela pessoa e as listas que o próprio acervo devolveu (os nomes
    exatos que a busca entende)."""
    regras = []
    for prov in BIBLIOTECAS_LOCAIS:
        if prov not in providers:
            continue
        b = (bibliotecas or {}).get(prov) or {}
        info = _BIB_INFO[prov]
        partes = []
        obra = str(b.get("obra") or "").strip()
        obras_v = [x.strip() for x in obra.split("|") if x.strip()]
        if len(obras_v) > 1:
            nomes_v = "; ".join(f"**\"{x}\"**" for x in obras_v)
            partes.append(f"a pessoa escolheu {len(obras_v)} obras: {nomes_v} — todo segmento \"{prov}\" já busca SÓ dentro delas "
                          f"(misturando cenas das {len(obras_v)}). Quando um trecho fala claramente de UMA delas, ponha `\"obra\": \"nome\"` "
                          "no segmento com o nome EXATO dela, pra buscar só nela; não repita o nome da obra na query")
        elif obra:
            partes.append(f"a pessoa escolheu a obra **\"{obra}\"** — todo segmento \"{prov}\" já busca SÓ dentro dela, "
                          "então não precisa (nem deve) repetir o nome da obra na query")
        elif b.get("obras"):
            nomes = "; ".join(f"\"{n}\"" for n in list(b["obras"])[:80])
            partes.append(f"pra buscar só dentro de um(a) {info['obra']}, ponha `\"obra\": \"nome\"` no segmento — com o nome "
                          f"EXATO de uma destas obras que existem no acervo: {nomes}")
        personagem = str(b.get("personagem") or "").strip()
        lista_obra = ""
        if obra and b.get("personagens"):
            # obra escolhida: os personagens DELA vão listados, um por linha, com os nomes exatos do acervo
            itens = [c for c in list(b["personagens"])[:150] if c.get("nome")]
            linhas_p = "\n".join(
                f"   - {c['nome']}" + (f" ({c.get('clipes')} clipes)" if c.get("clipes") else (" (do elenco)" if c.get("do_elenco") else ""))
                for c in itens)
            extra_ator = (" No acervo de filmes o nome vem como \"Personagem (Ator)\" — dá pra usar só o personagem ou só o "
                          "ator.") if prov in ("moviepexels", "moviepexels_online") else ""
            def _linha_p(c):
                return (f"   - {c['nome']}" + (f" — {c['obra']}" if len(obras_v) > 1 and c.get("obra") else "")
                        + (f" ({c.get('clipes')} clipes)" if c.get("clipes") else (" (do elenco)" if c.get("do_elenco") else "")))
            linhas_p = "\n".join(_linha_p(c) for c in itens)
            de_quem = " e ".join(f"\"{x}\"" for x in obras_v) if obras_v else f"\"{obra}\""
            lista_obra = (f"\n\n   {info['pessoas'].capitalize()} de {de_quem} que existem no acervo ({len(itens)}):\n{linhas_p}\n\n"
                          f"   Quando o trecho falar de um deles (ou mostrar a cena dele), ponha `\"personagem\": \"nome\"` no segmento, "
                          "escrito EXATAMENTE como na lista — o site traz só clipes em que ele aparece; se não tiver nenhum com aquela "
                          "ação, cai pra outra cena da mesma obra. Prefira os que têm mais clipes. Não invente nome fora da lista."
                          + extra_ator)
        pers_v = [x.strip() for x in personagem.split("|") if x.strip()]
        if len(pers_v) > 1:
            partes.append(f"e só clipes em que aparece um destes {info['pessoas']} escolhidos pela pessoa: "
                          + ", ".join(f"**\"{x}\"**" for x in pers_v)
                          + " (o site mistura as cenas deles). Quando o trecho fala de UM deles, ponha `\"personagem\": \"nome\"` só com ele")
        elif personagem:
            partes.append(f"e só clipes em que aparece **\"{personagem}\"** ({info['pessoa']} escolhido pela pessoa"
                          + (" pro vídeo inteiro — nos trechos em que a fala é claramente de OUTRO personagem da lista abaixo, "
                             "ponha o nome dele no `\"personagem\"` do trecho)" if lista_obra else ")"))
        elif lista_obra:
            pass
        elif b.get("personagens"):
            lista = ", ".join(f"{c['nome']} ({c.get('clipes', 0)})" for c in list(b["personagens"])[:60] if c.get("nome"))
            extra_ator = (" No acervo de filmes o nome vem como \"Personagem (Ator)\" — dá pra usar só o personagem ou só o "
                          "ator.") if prov in ("moviepexels", "moviepexels_online") else ""
            partes.append(f"{info['pessoas']} identificados nos clipes{' dessa obra' if obra else ''} (com quantos clipes cada "
                          f"um tem): {lista}. Quando o trecho falar de um deles, ponha `\"personagem\": \"nome\"` no segmento "
                          "(como está na lista) — o site traz só clipes em que ele aparece; se não tiver nenhum com aquela ação, "
                          "ele cai pra outra cena da mesma obra." + extra_ator)
        if partes or lista_obra:
            regras.append(
                f"Acervo \"{prov}\" ({info['nome']}): " + "; ".join(partes).rstrip(".") + ". A query continua sendo a AÇÃO/cena em inglês "
                "(\"man cooking in lab\", \"two friends arguing in car\") — o filtro de obra/personagem cuida do resto." + lista_obra
            )
    return regras


RITMOS = ("livre", "fixo")


def regra_ritmo(interval_seconds: float, ritmo: str = "livre") -> str:
    """Regra do tamanho das cenas. "fixo": ~N s cada (como sempre foi).
    "livre": N é só a média — a IA decide cena a cena, como um editor."""
    n = float(interval_seconds or 7.0)
    if (ritmo or "livre") == "fixo":
        return (f"Por padrão, troque de vídeo a cada ~{n:.0f} segundos — mas você tem liberdade pra ajustar o início/fim de "
                "cada segmento pra não cortar no meio de uma frase ou ideia da narração. Prefira cortar em pausas naturais da fala.")
    curto, longo = max(1.5, round(n * 0.4, 1)), round(n * 2.2, 1)
    return (f"RITMO LIVRE — você é o editor: ~{n:.0f} segundos por cena é só a MÉDIA do vídeo, não uma regra. Decida o "
            "tamanho de cada cena pelo que a narração pede, cortando sempre em pausas naturais da fala (nunca no meio de "
            f"uma frase ou ideia): cenas CURTAS (~{curto:.0f}-{max(curto + 1, n * 0.7):.0f}s) em listas, enumerações, ação, "
            "tensão subindo, frases de impacto e viradas — o corte rápido dá energia; cenas LONGAS (até ~"
            f"{longo:.0f}s) quando uma única imagem sustenta um pensamento inteiro, numa explicação calma, num momento "
            "emocional/contemplativo ou quando a mesma cena de anime/filme continua sendo descrita. Varie o ritmo ao longo "
            "do vídeo (não deixe tudo do mesmo tamanho) e combine com o tom de cada parte; só não deixe uma cena parada "
            f"mais de ~{longo:.0f}s sem motivo.")


def build_animepexels_prompt(
    segments: List[Dict[str, Any]],
    interval_seconds: float = 7.0,
    language_hint: str = "português",
    extra_instructions: str = "",
    provider: str = "animepexels",
    bibliotecas: Optional[Dict[str, Any]] = None,
    ritmo: str = "livre",
) -> str:
    """Versão DEDICADA do prompt pra quando o único banco disponível é
    o "Anime Pexels Local" (acervo próprio de clipes de anime) — usada
    em vez de `build_prompt()` quando `providers == ["animepexels"]`.

    Refinada com orientação bem específica sobre como o mecanismo de
    busca do acervo funciona (descrição visual literal + vocabulário de
    categorias/sinônimos gerado por IA) — evita queries abstratas
    demais (ex: "sense of determination") em favor de cenas concretas e
    filmáveis (ex: "ninja celebrated by village crowd").

    Introduz dois campos opcionais por segmento, `keyword_weight` e
    `semantic_weight`, que ajustam o peso relativo entre correspondência
    literal de palavra-chave e correspondência semântica na busca —
    úteis quando a query é claramente concreta (prioriza keyword) ou
    claramente abstrata/emocional (prioriza semântica).

    segments/interval_seconds/language_hint/extra_instructions: mesmo
    significado de `build_prompt()`.
    """
    if not segments:
        raise PromptBuilderError("Lista de segmentos vazia — nada pra transcrever/prompt-ar.")

    total_duration = segments[-1]["end"]

    transcript_lines = []
    for seg in segments:
        transcript_lines.append(
            f"[{_format_timestamp(seg['start'])} -> {_format_timestamp(seg['end'])}] "
            f"({seg['start']:.2f}s - {seg['end']:.2f}s) {seg['text'].strip()}"
        )
    transcript_block = "\n".join(transcript_lines)

    filmes = provider in ("moviepexels", "moviepexels_online")
    tipo_clipe = "filmes e séries (live-action)" if filmes else "anime"
    ex_nome = ("**Nomes de filme/série/personagem ajudam quando você tem certeza** (ex: a narração já cita \"Breaking Bad\") — se a "
               "obra não estiver fixada abaixo, inclua o nome na query quando tiver confiança razoável na cena (ex: \"Walter White "
               "cooking in lab\"). Se não tiver certeza de qual obra/cena combina, fique no genérico-mas-visual (ex: \"man cooking "
               "in makeshift lab\") em vez de arriscar um nome errado.") if filmes else (
               "**Nomes de anime/personagem ajudam quando você tem certeza** (ex: a narração já cita \"Naruto\") — inclua o nome do "
               "personagem/anime na query se for conhecido e você tiver confiança razoável na cena (ex: \"Naruto training alone "
               "forest\"). Se não tiver certeza de qual anime/cena específica combina, fique no genérico-mas-visual (ex: \"ninja "
               "training alone forest\") em vez de arriscar um nome errado.")
    ex_concreto = ("\"man running down dark alley\" funciona muito melhor que \"sense of danger\"" if filmes
                   else "\"ninja running through forest\" funciona muito melhor que \"sense of determination\"")
    ex_abstrato = ("Errado: \"recognition and validation\". Certo: \"crowd applauding man on stage\"" if filmes
                   else "Errado: \"recognition and validation\". Certo: \"ninja celebrated by village crowd\"")
    ex_estrutura = ("\"woman reading letter\", \"car chase at night\", \"man crying alone in room\"" if filmes
                    else "\"boy reading old book\", \"warrior sword fight arena\", \"girl crying alone room\"")
    ex_alt = ("\"Walter White cooking in lab\" → [\"man cooking in lab\", \"chemistry lab\"]" if filmes
              else "\"Naruto training alone forest\" → [\"ninja training forest\", \"ninja training\"]")
    if filmes:
        ex_json = (f'    {{{{"start": 0.0, "end": 4.2, "visual": "homem olhando a cidade à noite", "provider": "{provider}", "query": "man looking at city at night", "alternativas": ["city at night"]}}}},\n'
                   f'    {{{{"start": 4.2, "end": 9.1, "visual": "o químico cozinhando no laboratório", "provider": "{provider}", "query": "man cooking in lab", "personagem": "Walter White", "alternativas": ["chemistry lab"], "keyword_weight": 2, "semantic_weight": 0.5}}}},\n'
                   f'    {{{{"start": 9.1, "end": {total_duration:.2f}, "provider": "{provider}", "query": "tense standoff in desert", "on_screen_text": "O ponto sem volta"}}}}')
    else:
        ex_json = (f'    {{{{"start": 0.0, "end": 4.2, "visual": "ninja olhando a vila com determinação", "provider": "{provider}", "query": "ninja looking determined village", "alternativas": ["ninja looking at village"]}}}},\n'
                   f'    {{{{"start": 4.2, "end": 9.1, "visual": "treino sozinho na floresta", "provider": "{provider}", "query": "ninja training alone forest", "alternativas": ["ninja training forest", "ninja training"], "keyword_weight": 2, "semantic_weight": 0.5}}}},\n'
                   f'    {{{{"start": 9.1, "end": {total_duration:.2f}, "provider": "{provider}", "query": "epic sword battle anime", "on_screen_text": "Batalhas épicas"}}}}')
    ex_json = ex_json.replace("{{", "{").replace("}}", "}")
    regras_bib = _regra_bibliotecas(bibliotecas, [provider])
    regra_bib = ("\n\n4b. " + regras_bib[0] + " Campos opcionais no segmento: `\"obra\"` e `\"personagem\"`.") if regras_bib else ""

    prompt = f"""Você vai me ajudar a montar um roteiro de vídeo usando SOMENTE clipes de {tipo_clipe} de um acervo {"online" if provider.endswith("_online") else "local"} ({provider}), sincronizado com uma narração em áudio.

## Contexto

Abaixo está a transcrição completa de um áudio de narração em {language_hint}, com timestamps (em segundos) de cada trecho falado. A duração total do áudio é de {total_duration:.2f}s.

**{_regra_idioma(language_hint)}**

Antes de decidir qualquer coisa, leia a transcrição INTEIRA e entenda do que o vídeo trata como um todo: o tema geral, o tom (sério, leve, educativo, promocional, emocional...), {'a obra e os personagens/atores envolvidos' if filmes else 'o anime/personagem envolvido'} (se houver um específico) e o público provável. Use esse entendimento do vídeo inteiro pra escolher termos de busca coerentes entre si ao longo de todos os segmentos — evite que a estética pule de um estilo pra outro sem motivo entre um trecho e o próximo.

## Transcrição com timestamps

{transcript_block}

## O que eu preciso que você faça

Divida a duração TOTAL do áudio (de 0.00s até {total_duration:.2f}s, sem nenhum buraco entre um trecho e o próximo) em segmentos de vídeo. Cada segmento vai virar um clipe puxado do acervo local de {tipo_clipe}.

Regras:

1. {regra_ritmo(interval_seconds, ritmo)}

2. Os segmentos precisam ser contínuos e cobrir o áudio inteiro: o "end" de um segmento é sempre igual ao "start" do próximo, o primeiro "start" é 0.0, e o último "end" é {total_duration:.2f}.

3. Todo segmento usa `"provider": "{provider}"` — é a única opção, não existe escolha de provedor aqui.

4. **A query é o ponto mais importante deste prompt — leia com atenção.** O acervo é buscado por descrição visual literal + um vocabulário de categorias/sinônimos gerado por IA (objetos, animais, comida, roupa, armas, emoções). Ele NÃO entende bem conceitos abstratos soltos sem âncora visual. Na prática:

   - **Prefira uma CENA CONCRETA e filmável**: um personagem fazendo uma ação específica, um objeto específico, um cenário específico. {ex_concreto}.
   - **Evite adjetivo abstrato sozinho sem sujeito/ação/objeto.** Se a narração fala de um conceito (ex: "reconhecimento", "coragem", "poder"), traduza isso pra uma cena que SUGIRA esse conceito visualmente, não pro conceito em si. {ex_abstrato}.
   - {ex_nome}
   - **2 a 5 palavras, sempre em inglês.** Estrutura que funciona bem: [personagem/tipo] + [ação/pose] + [cenário/objeto]. Ex: {ex_estrutura}.
   - Mantenha coerência visual com os segmentos vizinhos (mesma obra/estilo/paleta quando fizer sentido, pra não pular de estética a cada 5 segundos sem motivo), mas nunca repita a mesma query em dois trechos seguidos — varie o plano (geral, rosto, detalhe da mão/objeto).
   - **Pense na imagem antes da busca:** escreva em "visual" (português, curto) o que o espectador deve ver naquele trecho, e só então a query.
   - **Dê 1 ou 2 "alternativas"**: buscas de reserva cada vez mais simples, com a mesma ideia (ex: {ex_alt}). O site usa sozinho quando a principal não acha nada.

5. **(Opcional) `keyword_weight` / `semantic_weight`** — inclua esses dois campos no segmento SÓ quando a query for claramente concreta (uma ação/objeto bem específico) ou claramente abstrata/emocional (um clima/sentimento sem ação clara). Quando concreta, sugira `"keyword_weight": 2, "semantic_weight": 0.5` (prioriza achar exatamente aquele objeto/ação). Quando for mais sobre clima/emoção que uma ação específica, sugira o inverso: `"keyword_weight": 0.5, "semantic_weight": 2`. Se não tiver certeza, omita os dois campos (o sistema usa 1.0/1.0 por padrão).{regra_bib}

6. **(Opcional) `on_screen_text`** — só inclua quando um texto na tela reforçar de verdade a mensagem (um número, uma palavra-chave, um destaque). Não abuse; a maioria dos segmentos deve ficar sem isso.

7. **(Opcional) `soundtrack_suggestion`** — no nível raiz da resposta, uma sugestão de estilo de trilha (ex: "instrumental calmo e inspirador"). Direção geral, não precisa ser específico.

## Formato de resposta — IMPORTANTE

Responda **apenas** com um JSON válido (sem texto antes ou depois, sem \\`\\`\\`json, sem comentários), no formato exato abaixo:

{{
  "segments": [
{ex_json}
  ],
  "soundtrack_suggestion": "instrumental épico e inspirador"
}}

"segments" é obrigatório e precisa cobrir o áudio inteiro como explicado acima. "visual"/"alternativas" (por segmento, fortemente recomendados), "keyword_weight"/"semantic_weight" (por segmento), "on_screen_text" (por segmento) e "soundtrack_suggestion" (raiz) são opcionais — inclua só quando fizer sentido, e omita completamente quando não tiver nada a sugerir.

{extra_instructions}
""".strip()

    return prompt


def build_wikipedia_search_terms_prompt(
    segments: List[Dict[str, Any]],
    language_hint: str = "português",
) -> str:
    """Primeira etapa do modo "este vídeo tem fontes da Wikipedia":
    monta um prompt PEDINDO PRA IA (não pra nossa heurística) listar
    termos de busca — nomes de pessoas, lugares, objetos, eventos ou
    obras REAIS e específicas mencionadas (ou claramente relacionadas
    ao que está sendo narrado) que provavelmente têm foto disponível na
    Wikipedia/Wikimedia Commons.

    Por que pedir pra IA em vez de usar só uma heurística de texto: a
    IA lê o roteiro INTEIRO com contexto — entende que "o físico alemão
    que revolucionou a relatividade" está falando de Albert Einstein
    mesmo sem o nome aparecer literalmente, o que uma heurística de
    "Palavras Capitalizadas" nunca pegaria.

    O JSON que a IA devolver aqui é o que vai pra
    `parse_wikipedia_search_terms_response()`, e os termos daquela
    lista são então PESQUISADOS DE VERDADE na Wikipedia (ver
    `wikipedia_enrichment.buscar_entidades_confirmadas_na_wikipedia`)
    antes de entrar no prompt principal de edição — então um termo que
    a IA sugerir aqui mas que não existir de verdade na Wikipedia
    simplesmente não aparece na etapa seguinte, sem problema nenhum.
    """
    if not segments:
        raise PromptBuilderError("Lista de segmentos vazia — nada pra analisar.")

    transcript_lines = []
    for seg in segments:
        transcript_lines.append(
            f"[{_format_timestamp(seg['start'])} -> {_format_timestamp(seg['end'])}] {seg['text'].strip()}"
        )
    transcript_block = "\n".join(transcript_lines)

    return f"""Analise o roteiro de narração abaixo (idioma: {language_hint}) e liste TERMOS DE BUSCA pra Wikipedia — nomes de pessoas, lugares, objetos, eventos, obras ou organizações REAIS e específicas, mencionadas no roteiro ou claramente relacionadas ao que está sendo narrado, que provavelmente têm uma foto real disponível na Wikipedia/Wikimedia Commons.

Regras:
1. Só inclua entidades REAIS e ESPECÍFICAS (não conceitos abstratos, não termos genéricos como "tecnologia" ou "cidade grande") — o tipo de coisa que teria seu próprio artigo com foto na Wikipedia: uma pessoa nomeada, um lugar específico (cidade, monumento, prédio), um evento histórico com nome próprio, uma obra (livro, filme, pintura), uma organização/empresa.
2. Prefira o nome mais específico e correto possível (ex: "Torre Eiffel" em vez de só "torre"; "Segunda Guerra Mundial" em vez de só "guerra").
3. Não invente nomes que não têm certeza que existem — é melhor listar menos termos e todos plausíveis do que muitos chutes.
4. No máximo 20 termos, dos mais relevantes/centrais ao vídeo primeiro.
5. Se o roteiro não menciona (nem se relaciona claramente a) nenhuma entidade real específica, devolva uma lista vazia — não force termos genéricos só pra preencher.

Roteiro:
{transcript_block}

Responda SOMENTE com um JSON neste formato exato, sem nenhum texto antes ou depois:
{{"termos": ["Nome do Termo 1", "Nome do Termo 2", ...]}}"""


def build_buscadores_search_terms_prompt(
    segments: List[Dict[str, Any]],
    language_hint: str = "português",
) -> str:
    """Mesma ideia de `build_wikipedia_search_terms_prompt`, mas pro modo
    "este vídeo usa buscadores de imagem por navegador" (Bing/Brave/
    Yandex/Startpage Images) — que pesquisam a web aberta inteira, não só
    a Wikipedia. Por isso a regra é mais ampla: não precisa ser uma
    entidade histórica/enciclopédica, só algo ESPECÍFICO E CONCRETO o
    bastante pra valer a pena confirmar com uma busca de verdade antes de
    montar o prompt principal (uma pessoa, marca, produto, lugar exato,
    obra) — em vez de um termo genérico que qualquer banco de estoque já
    resolveria bem.

    O JSON devolvido aqui usa o MESMO parser de
    `build_wikipedia_search_terms_prompt` (`parse_wikipedia_search_terms_response`)
    — o formato de resposta esperado é idêntico, só muda o que está
    sendo pedido no prompt em si.
    """
    if not segments:
        raise PromptBuilderError("Lista de segmentos vazia — nada pra analisar.")

    transcript_lines = []
    for seg in segments:
        transcript_lines.append(
            f"[{_format_timestamp(seg['start'])} -> {_format_timestamp(seg['end'])}] {seg['text'].strip()}"
        )
    transcript_block = "\n".join(transcript_lines)

    return f"""Analise o roteiro de narração abaixo (idioma: {language_hint}) e liste TERMOS DE BUSCA pra buscadores de imagem (Bing/Brave/Yandex/Startpage Images) — coisas ESPECÍFICAS E CONCRETAS mencionadas no roteiro ou claramente relacionadas ao que está sendo narrado, que provavelmente têm uma foto real disponível numa busca de imagem comum (não precisa ser uma entidade histórica/enciclopédica — pode ser uma pessoa, marca, produto, empresa, lugar exato, captura de tela, logotipo, objeto específico).

Regras:
1. Só inclua coisas ESPECÍFICAS (não conceitos abstratos, não termos genéricos que qualquer banco de imagem de estoque já resolveria bem, como "pessoa feliz" ou "paisagem bonita") — o tipo de busca que só faz sentido nesses buscadores porque é concreta e particular demais pra um banco de estoque ter.
2. Prefira o nome/termo mais específico e correto possível (ex: "iPhone 15 Pro" em vez de só "celular"; "Elon Musk" em vez de só "bilionário de tecnologia").
3. Não invente nomes que não tem certeza que existem — é melhor listar menos termos e todos plausíveis do que muitos chutes.
4. No máximo 20 termos, dos mais relevantes/centrais ao vídeo primeiro.
5. Se o roteiro não menciona (nem se relaciona claramente a) nada específico o bastante, devolva uma lista vazia — não force termos genéricos só pra preencher.

Roteiro:
{transcript_block}

Responda SOMENTE com um JSON neste formato exato, sem nenhum texto antes ou depois:
{{"termos": ["Nome do Termo 1", "Nome do Termo 2", ...]}}"""


def parse_wikipedia_search_terms_response(raw_text: str) -> List[str]:
    """Valida e converte o JSON colado (resposta da IA pro prompt de
    `build_wikipedia_search_terms_prompt`) numa lista de termos —
    string vazias/repetidas são descartadas, mas a lista pode legitima-
    mente vir vazia (roteiro sem entidade real nenhuma pra buscar).
    """
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    if not text:
        raise PromptBuilderError("Colou uma resposta vazia — cole o JSON que a IA devolveu.")

    try:
        data = _json_loads_colado(text)
    except json.JSONDecodeError as exc:
        repaired = _try_repair_common_json_issues(text)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            raise PromptBuilderError(
                f"O texto colado não é um JSON válido (erro perto de '...{text[max(0, exc.pos - 40):exc.pos + 40]}...'). "
                f"Confira se copiou a resposta inteira, sem cortar nenhuma parte."
            ) from exc

    if isinstance(data, dict):
        termos_brutos = data.get("termos", data.get("terms"))
        if termos_brutos is None:
            raise PromptBuilderError(
                'O JSON precisa ter uma chave "termos" com a lista de termos — ex: {"termos": ["Albert Einstein"]}.'
            )
    elif isinstance(data, list):
        termos_brutos = data  # aceita também uma lista "nua", sem o envelope -- mais tolerante
    else:
        raise PromptBuilderError('O JSON precisa ser um objeto com "termos" (lista) ou uma lista direto.')

    if not isinstance(termos_brutos, list):
        raise PromptBuilderError('"termos" precisa ser uma lista de strings.')

    vistos = set()
    termos: List[str] = []
    for item in termos_brutos:
        if not isinstance(item, str):
            continue
        termo = item.strip()
        if not termo or termo.lower() in vistos:
            continue
        vistos.add(termo.lower())
        termos.append(termo)
    return termos


def build_prompt(
    segments: List[Dict[str, Any]],
    interval_seconds: float = 7.0,
    providers: Optional[List[str]] = None,
    language_hint: str = "português",
    extra_instructions: str = "",
    content_style: Optional[str] = None,
    wikipedia_entidades_confirmadas: Optional[List[Dict[str, str]]] = None,
    buscadores_confirmados: Optional[List[Dict[str, str]]] = None,
    usar_templates: bool = False,
    mix_midia: Optional[Dict[str, Any]] = None,
    formato: Optional[str] = None,
    bibliotecas: Optional[Dict[str, Any]] = None,
    ritmo: str = "livre",
) -> str:
    """Monta o texto do prompt a partir dos segmentos transcritos.

    mix_midia: proporção fotos × vídeos escolhida pela pessoa (ver
        `mix_midia.py`) — vira uma regra no prompt.

    segments: lista de {"start": float, "end": float, "text": str} —
        exatamente o formato que `whisper_transcribe.transcribe_audio()`
        devolve (é o mesmo formato que a biblioteca `whisper` já usa
        internamente pra `result["segments"]`).
    interval_seconds: de quanto em quanto tempo, em média, a IA deve
        trocar de vídeo — mas ela tem liberdade pra ajustar o corte pra
        não cortar no meio de uma frase/palavra.
    providers: quais bancos de vídeo estão disponíveis pra essa busca
        (por padrão, os 5 do toolkit). A IA escolhe o mais adequado pra
        cada trecho dentre essas opções.
    language_hint: idioma da narração (só informativo pro prompt).
    extra_instructions: qualquer instrução extra sua (estilo visual,
        coisas a evitar, etc.) — anexada ao final do prompt.
    content_style: opcional, "noticia_documentario" ativa uma regra
        extra orientando a IA a preferir FOTOS com mais frequência
        (mais comum nesse gênero — manchete/foto de arquivo/still) em
        vez de sempre vídeo. Sem isso (padrão None), o comportamento é
        o de sempre.
    wikipedia_entidades_confirmadas: lista de entidades JÁ VERIFICADAS
        como tendo foto real na Wikipedia (ver
        `wikipedia_enrichment.identificar_entidades_wikipedia()`) —
        cada item é um dict com pelo menos "termo" (o nome a usar como
        query) e opcionalmente "descricao". Quando informado (e
        "wikipedia" está em `providers`), o prompt ganha uma regra
        extra listando esses termos como confirmados, pra IA usá-los
        com confiança nos momentos certos em vez de arriscar um nome
        que ela não tem certeza que existe.
    buscadores_confirmados: mesma ideia de `wikipedia_entidades_confirmadas`,
        mas pros buscadores de imagem por navegador (bing/brave/yandex/
        startpage — ver `buscadores_enrichment.py`). Cada item é um dict
        com "termo", e opcionalmente "provider" (qual buscador confirmou)
        e "descricao". Só entra no prompt se pelo menos um desses
        provedores estiver em `providers`.

    Retorna o texto completo do prompt, pronto pra copiar e colar.
    """
    if not segments:
        raise PromptBuilderError("Lista de segmentos vazia — nada pra transcrever/prompt-ar.")

    providers = providers or DEFAULT_PROVIDERS
    total_duration = segments[-1]["end"]

    transcript_lines = []
    for seg in segments:
        transcript_lines.append(
            f"[{_format_timestamp(seg['start'])} -> {_format_timestamp(seg['end'])}] "
            f"({seg['start']:.2f}s - {seg['end']:.2f}s) {seg['text'].strip()}"
        )
    transcript_block = "\n".join(transcript_lines)

    providers_list = ", ".join(providers)

    # Constrói a lista de regras dinamicamente e numera automaticamente
    # ao final — algumas regras só fazem sentido quando um banco
    # ESPECÍFICO está na lista de bancos selecionados (mixkit, pexels,
    # animepexels); numerar isso manualmente quebraria a sequência
    # sempre que uma regra condicional fosse omitida.
    rules = [
        regra_ritmo(interval_seconds, ritmo),
        f"Os segmentos precisam ser contínuos e cobrir o áudio inteiro: o \"end\" de um segmento é sempre igual ao \"start\" do próximo, o primeiro \"start\" é 0.0, e o último \"end\" é {total_duration:.2f}.",
        (
            "Para cada segmento, escreva primeiro \"visual\" (o que vai aparecer na tela), depois a busca em \"query\" "
            "**em inglês** e 1 ou 2 \"alternativas\" de reserva — seguindo a seção \"Como escrever a busca\" logo depois "
            "destas regras, que é o que mais decide se o vídeo fica bom. Mantenha coerência visual entre trechos vizinhos. "
            "(Em provedores com regra própria abaixo — nome exato, descrição pra gerar imagem, busca do YouTube — vale a "
            "regra deles pra \"query\"; \"alternativas\" só fazem sentido nos bancos e buscadores de imagem.)"
            if any(p in STOCK_PROVIDERS for p in providers) else
            "Para cada segmento, escreva um termo de busca **em inglês** (os bancos de imagem são todos em inglês) que descreva visualmente o que a narração está dizendo naquele trecho — pense em uma cena real e filmável, não em conceitos abstratos. Prefira termos curtos e específicos (2 a 5 palavras), mas mantendo coerência visual com os segmentos vizinhos (mesma \"linguagem\" de imagem sempre que fizer sentido). Quando der, inclua 1 ou 2 \"alternativas\" (buscas de reserva mais simples, usadas se a principal não achar nada)."
        ),
        f"Escolha um provedor **exclusivamente** dentre estes, EXATAMENTE como escritos, pra cada segmento: {providers_list}. Não use nenhum outro banco de imagem/vídeo que você conheça (ex: Shutterstock, Getty, Unsplash, Freepik, ou qualquer um fora da lista acima) — mesmo que pareça um nome familiar, se não estiver nessa lista, a pessoa não tem acesso configurado a ele e o segmento vai falhar. Você pode repetir provedores, e pode variar conforme achar melhor o tipo de conteúdo esperado entre os que estão disponíveis.",
    ]
    if "mixkit" in providers:
        rules.append("Se um provedor específico for \"mixkit\", o campo \"query\" deve ser uma CATEGORIA válida desse site (ex: \"animal-nature\", \"business\", \"technology\") em vez de um termo de busca livre.")
    if "magnific" in providers:
        rules.append("O provedor \"magnific\" tem bastante conteúdo genérico e gerado por IA — pode ser uma boa opção pra conceitos mais abstratos, mas prefira os outros bancos quando precisar de uma cena real/filmada de verdade.")
    rules.append("(Opcional, mas ATIVAMENTE recomendado) Identifique os MOMENTOS IMPORTANTES da narração — um número/estatística marcante, uma virada, uma conclusão, uma frase de efeito, um nome/data específico — e reforce esses momentos com texto na tela (\"on_screen_text\") com mais frequência do que o resto do vídeo. Não é só \"quando ajudar\": procure ativamente esses pontos de destaque em vez de esperar que apareçam sozinhos. Fora desses momentos, a maioria dos segmentos continua sem texto — o objetivo é destacar o que importa, não preencher a tela o tempo todo.")
    rules.append(
        "Quando o momento importante for um VALOR NUMÉRICO — dinheiro, porcentagem, quantidade, data, "
        "estatística — escreva o texto de um jeito que funcione como destaque visual de verdade (como em "
        "vídeos de economia/finanças/dados), não uma frase corrida: normalmente só o número formatado "
        "de forma limpa, com a unidade (ex: \"R$ 1,78 milhão\", \"60% de queda\", \"3 meses\"), OU o número "
        "acompanhado de uma palavra bem curta de contexto (ex: \"R$ 1,78 milhão em ativos\") — nunca a frase "
        "inteira da narração. Se o número tiver uma casa decimal/vírgula longa faltando contexto (ex: um "
        "valor \"no vermelho\", uma queda, um recorde), pode incluir isso como uma segunda linha bem curta "
        "seguindo o mesmo espírito (rótulo, não frase)."
    )
    if content_style == "noticia_documentario":
        rules.append("Este vídeo é de NOTÍCIA/DOCUMENTÁRIO — gênero onde foto parada (still, foto de arquivo, retrato) é tão comum quanto vídeo, às vezes mais. Use `\"media_type\": \"image\"` com bem mais frequência do que faria num vídeo genérico — sempre que uma foto transmitir a mesma informação que um vídeo (um rosto, um lugar, um documento, um gráfico), prefira a foto.")
    rules.append("(Opcional) Se você tiver uma sugestão de estilo de trilha sonora de fundo pro vídeo inteiro (ex: \"instrumental calmo e inspirador\" ou \"eletrônica energética, sem vocal\"), inclua em \"soundtrack_suggestion\" no nível raiz da resposta. Isso é só uma sugestão de direção — não precisa ser um link nem um nome de música específica.")
    rules.append(
        "(Opcional) Nos MESMOS momentos importantes identificados acima, além (ou em vez) do texto no "
        "segmento, você pode sugerir um OVERLAY — um elemento extra por cima do vídeo, com tempo/posição "
        "próprios, independente dos limites do segmento. Inclua isso em \"overlays\" (lista, no nível raiz "
        "da resposta, junto de \"segments\"), com um objeto por overlay: "
        "`{\"media_type\": \"text\", \"text\": \"3 MILHÕES\", \"start\": 12.5, \"end\": 15.0}` pra um título/chamada "
        f"de texto puro, ou `{{\"media_type\": \"image\", \"provider\": \"{providers[0]}\", \"query\": \"stock market chart\", "
        "\"start\": 20.0, \"end\": 24.0}` pra uma foto ou vídeo sobreposto (mesmas regras de provedor/query dos "
        "segmentos, EXCLUSIVAMENTE dentre os bancos já listados acima, nunca \"youtube\") — pode combinar os dois tipos ao mesmo "
        "tempo (texto + imagem/vídeo) pra um momento que merece bastante destaque. \"start\"/\"end\" são "
        "segundos ABSOLUTOS no vídeo final (não relativos a um segmento). Use com moderação — só nos pontos "
        "que realmente pedem esse destaque extra, a maioria do vídeo não precisa de overlay nenhum."
    )
    rules.append(
        "(Opcional) Se a narração descreve um EVENTO REAL específico (uma notícia, um acontecimento, uma "
        "declaração pública) onde uma filmagem de verdade daquele momento faria muito mais sentido do que "
        "qualquer stock footage genérico, sugira um CORTE em \"cutaway_suggestions\" (lista, no nível raiz da "
        "resposta): `{\"insertion_point\": 45.2, \"description\": \"Coletiva de imprensa real do prefeito "
        "anunciando a medida\", \"audio_mode\": \"pause\"}`. Isso é DIFERENTE de um overlay — em vez de uma "
        "camada por cima, gera um espaço no editor pra pessoa fazer upload de um vídeo de verdade daquele "
        "momento, que substitui o trecho ali (o vídeo final fica mais longo). \"insertion_point\" é o segundo "
        "exato (absoluto) onde o corte deveria entrar; \"description\" explica em poucas palavras o que "
        "filmar/buscar pra colocar ali (seja específico: \"entrevista do CEO anunciando a fusão\", não só "
        "\"vídeo relacionado\"); \"query\" (opcional, mas recomendado) é o termo pra achar esse vídeo no YouTube "
        "(no idioma em que ele provavelmente foi publicado, com os nomes próprios — ex: \"coletiva prefeito "
        "anuncia tarifa zero 2024\"), o site pesquisa esse termo sozinho e mostra os resultados pra pessoa "
        "escolher; \"audio_mode\" é \"pause\" (a narração para durante o corte, toca só o áudio "
        "do clipe inserido) ou \"continue\" (padrão \"pause\" se omitido). Use isso raramente — a maioria dos "
        "vídeos não tem nenhum momento que peça isso; não force um corte só por ter a opção disponível."
    )
    if "youtube" in providers:
        rules.append(
            "O provedor \"youtube\" é DIFERENTE dos bancos de estoque: é o YouTube, pra quando o trecho pedir "
            "uma FILMAGEM REAL e ESPECÍFICA que só existe lá — um trailer, uma cena específica de anime/filme/"
            "série/jogo, uma entrevista ou discurso de alguém real, um lance esportivo, um evento noticiado, um "
            "produto sendo demonstrado. Nesse provedor a \"query\" NÃO é uma descrição visual genérica em "
            "inglês: é o termo que você digitaria na busca do YouTube pra achar aquele vídeo, no idioma em que "
            "ele provavelmente foi publicado e com os nomes próprios (ex: \"Jujutsu Kaisen Gojo domain "
            "expansion\", \"discurso de posse presidente 2023\", \"iPhone 15 Pro keynote titanium\"). O site "
            "pesquisa esses termos sozinho e a PESSOA escolhe o vídeo e o trecho exato (início/fim) — por isso "
            "use com moderação, só onde a filmagem real faz diferença de verdade; pra cenas genéricas, use "
            "sempre os bancos de estoque. Segmentos \"youtube\" são sempre vídeo (nunca use "
            "`\"media_type\": \"image\"` com ele)."
        )
    if "pexels" in providers:
        _extras_foto = [f'\"{_p}\"' for _p in ("wikipedia",) + BROWSER_IMAGE_SEARCH_PROVIDERS + ("flow",) if _p in providers]
        _photo_providers_note = (" ou " + " ou ".join(_extras_foto)) if _extras_foto else ""
        rules.append(f"(Opcional) Se um trecho combinar mais com uma FOTO parada (com efeito de zoom lento) do que com um vídeo — ex: um conceito, um produto específico, um retrato — pode usar `\"media_type\": \"image\"` nesse segmento, com `\"provider\": \"pexels\"` e o termo de busca da foto em \"query\". Sem essa chave, o padrão é sempre vídeo. Busca de foto só funciona com \"pexels\"{_photo_providers_note} — não use `\"media_type\": \"image\"` com nenhum outro provedor.")
    if "wikipedia" in providers:
        rules.append(
            "O provedor \"wikipedia\" é DIFERENTE dos demais: não é banco de vídeo/foto de estoque — é a "
            "Wikipedia/Wikimedia Commons, e só devolve FOTOS REAIS de coisas que existem ou existiram de "
            "verdade (pessoas, lugares/monumentos, quadros e outras obras de arte, objetos históricos, "
            "espécies, eventos documentados). Escolha esse provedor SÓ quando a narração citar uma entidade "
            "específica e real que valha a pena ilustrar com uma foto de verdade dela — nunca pra cenas "
            "genéricas, conceitos abstratos, ou algo que não tenha um nome próprio identificável (pra isso, "
            "prefira sempre um dos outros bancos). A \"query\" precisa ser o NOME PRECISO dessa entidade, "
            "exatamente como ela é conhecida (ex: \"Albert Einstein\", \"Eiffel Tower\", \"Mona Lisa\", "
            "\"Great Barrier Reef\") — nunca invente um nome, e nunca use um termo genérico só porque soa "
            "relacionado; se você não tiver certeza razoável de que aquele nome existe de verdade, use outro "
            "provedor em vez de arriscar. Todo segmento com `\"provider\": \"wikipedia\"` PRECISA também "
            "incluir `\"media_type\": \"image\"` (esse banco não tem vídeo, só foto — sem essa chave a busca "
            "vai falhar)."
        )
    if wikipedia_entidades_confirmadas and "wikipedia" in providers:
        itens = []
        for item in wikipedia_entidades_confirmadas:
            termo = item.get("termo", "").strip()
            if not termo:
                continue
            desc = (item.get("descricao") or "").strip()
            itens.append(f"\"{termo}\"" + (f" ({desc})" if desc else ""))
        if itens:
            rules.append(
                "Antes deste prompt, o ROTEIRO JÁ FOI PESQUISADO na Wikipedia de verdade, e estas "
                "entidades foram CONFIRMADAS como tendo foto real disponível lá: "
                + "; ".join(itens) + ". Use provider \"wikipedia\" com query EXATAMENTE um desses termos "
                "(cópia fiel, sem alterar) nos trechos em que a narração falar especificamente sobre essa "
                "entidade — são termos garantidos, não precisa ter receio de usá-los. Fora dessa lista, "
                "continue seguindo a regra acima do \"wikipedia\" (só usar se tiver certeza razoável que "
                "existe) — e pra qualquer trecho que NÃO tenha uma dessas entidades confirmadas relevante, "
                "use os outros bancos de vídeo disponíveis normalmente, sem forçar Wikipedia onde não cabe."
            )
    _buscadores_navegador = [p for p in BROWSER_IMAGE_SEARCH_PROVIDERS if p in providers]
    if _buscadores_navegador:
        _nomes = " / ".join(f'"{p}"' for p in _buscadores_navegador)
        rules.append(
            f"Os provedores {_nomes} são DIFERENTES dos bancos de estoque: são buscadores de imagem de "
            "verdade (Bing/Brave/Yandex/Startpage Images), que pesquisam a web aberta inteira em vez de um "
            "acervo curado — então encontram praticamente qualquer coisa específica que um banco de estoque "
            "não teria (uma pessoa real, uma marca, um produto específico, um lugar exato, uma captura de "
            "tela de algo), mas o resultado não é curado/profissional como um banco de estoque. Use um "
            "desses SÓ quando o trecho pedir algo específico demais pra um banco de estoque genérico "
            "resolver — pra cenas genéricas (natureza, gente trabalhando, paisagem urbana comum), prefira "
            "sempre os bancos de estoque normais. A \"query\" deve ser o termo de busca mais preciso possível "
            "(nome próprio, termo específico) — evite termos vagos, que tendem a trazer resultado ruim nesses "
            "buscadores. NUNCA repita o mesmo termo (nem um quase igual) em trechos diferentes: o buscador devolve a "
            "MESMA imagem e o vídeo fica parado nela. Quando a narração fica muito tempo no mesmo assunto (um filme, "
            "uma pessoa, um lugar), varie o que pede a cada trecho — outra cena, outro personagem, o pôster, os "
            "bastidores, o diretor no set, um objeto marcante, a época (ex.: \"Reservoir Dogs diner scene\", "
            "\"Reservoir Dogs warehouse\", \"Mr. Blonde Michael Madsen\", \"Tarantino on set 1992\"). Todo segmento que usar um desses provedores PRECISA também incluir "
            "`\"media_type\": \"image\"` (são buscadores de imagem, não têm vídeo)."
        )
    if buscadores_confirmados and _buscadores_navegador:
        itens = []
        for item in buscadores_confirmados:
            termo = item.get("termo", "").strip()
            if not termo:
                continue
            provider = item.get("provider", "").strip()
            desc = (item.get("descricao") or "").strip()
            sufixo = f" (via \"{provider}\"" + (f": {desc}" if desc else "") + ")" if provider else ""
            itens.append(f"\"{termo}\"{sufixo}")
        if itens:
            rules.append(
                "Antes deste prompt, o ROTEIRO JÁ FOI PESQUISADO de verdade nesses buscadores de imagem, e "
                "estes termos foram CONFIRMADOS como tendo resultado de imagem disponível: "
                + "; ".join(itens) + ". Use o provider indicado entre parênteses (ou qualquer um dos "
                f"buscadores disponíveis {_nomes}, se não indicado) com query EXATAMENTE um desses termos "
                "(cópia fiel, sem alterar) nos trechos em que a narração falar especificamente sobre isso — "
                "são termos garantidos, não precisa ter receio de usá-los. Fora dessa lista, continue "
                "seguindo a regra acima (só usar quando um banco de estoque genérico não resolveria) — e pra "
                "qualquer trecho que NÃO tenha um desses termos confirmados relevante, use os outros bancos "
                "disponíveis normalmente, sem forçar um buscador de imagem onde não cabe."
            )
    if "flow" in providers:
        rules.append(
            "O provedor \"flow\" é DIFERENTE dos demais: ele não BUSCA em um banco — GERA uma mídia inédita "
            "com inteligência artificial (Google Flow) a partir de uma descrição: IMAGEM (`\"media_type\": \"image\"`, "
            "o normal) ou um VÍDEO curto de ~8 s (`\"media_type\": \"video\"`, bem mais demorado — só quando o "
            "MOVIMENTO for essencial à cena, ou quando a proporção de fotos × vídeos pedida abaixo mandar). Todo segmento "
            "\"flow\" deve trazer o \"media_type\" explícito. A \"query\" desse provedor é a DESCRIÇÃO DA CENA que você quer "
            "gerar, em português, como um pedido detalhado (assunto, cenário, estilo, luz, enquadramento) — "
            "por exemplo \"astronauta caminhando num deserto de areia roxa sob duas luas, estilo fotográfico "
            "cinematográfico\" — e NÃO um termo curto de busca como nos outros bancos. Não peça pessoas reais "
            "ou famosas, marcas, logotipos nem texto escrito dentro da imagem. Cada geração é LENTA (de "
            "dezenas de segundos a alguns minutos) e gasta créditos, então use \"flow\" com MODERAÇÃO: só nos "
            "trechos em que nenhum banco de estoque teria a cena (algo fantástico, hipotético, muito "
            "específico, ilustrativo, ou um conceito abstrato que precisa de uma imagem sob medida). Para "
            "cenas comuns (natureza, cidade, pessoas trabalhando, objetos), prefira SEMPRE os outros bancos."
        )
    if "animepexels" in providers:
        rules.append(
            "O provedor \"animepexels\" é DIFERENTE dos outros: é um acervo LOCAL de clipes de ANIME "
            "(roda na própria máquina de quem monta o vídeo), não um banco de vídeo de estoque genérico. "
            "Só escolha esse provedor pra segmentos onde uma cena de anime realmente combina com o que a "
            "narração está dizendo (ex: a narração é sobre anime, cultura otaku, ou menciona um "
            "personagem/cena específica) — NUNCA escolha ele só porque está na lista disponível; pra "
            "conteúdo genérico (natureza, pessoas reais, negócios, tutoriais, etc.), sempre prefira um dos "
            "outros provedores. O termo de busca pra esse provedor também é em inglês, e pode incluir nome "
            "de anime/personagem quando for conhecido (ex: \"ninja running through forest\", \"sword fight "
            "anime scene\")."
        )
    if "moviepexels" in providers:
        rules.append(
            "O provedor \"moviepexels\" é DIFERENTE dos bancos de estoque: é um acervo LOCAL de clipes de FILMES E SÉRIES "
            "(cenas reais de obras específicas, com atores), não um banco genérico. Escolha ele quando a narração fala de um "
            "filme/série, de uma cena famosa, de um personagem ou ator — ou quando uma cena de filme ilustra o trecho melhor que "
            "um vídeo de estoque. A query é em inglês e descreve a AÇÃO/cena (\"man cooking in lab\", \"car chase at night\"); "
            "pode incluir o nome do filme/personagem quando você tiver certeza."
        )
    for _on, _base in (("animepexels_online", "animepexels"), ("moviepexels_online", "moviepexels")):
        if _on in providers:
            rules.append(
                f"O provedor \"{_on}\" é o MESMO tipo de acervo do \"{_base}\" ("
                + ("clipes de FILMES E SÉRIES, cenas reais de obras específicas" if _base == "moviepexels" else "clipes de ANIME")
                + "), só que num servidor ONLINE. Mesmas regras: só escolha quando uma cena "
                + ("de filme/série" if _base == "moviepexels" else "de anime")
                + " realmente combina com o trecho; a query é em inglês e descreve a AÇÃO/cena; aceita \"obra\", \"personagem\", "
                "\"keyword_weight\" e \"semantic_weight\". Escreva o provider exatamente \"" + _on + "\".")
    rules.extend(_regra_bibliotecas(bibliotecas, providers))
    if usar_templates:
        try:
            import cenas_dp
            _catalogo_txt = cenas_dp.bloco_para_prompt()
        except Exception:  # noqa: BLE001
            _catalogo_txt = ""
        if _catalogo_txt:
            rules.append(
                "(Opcional) CENAS E TAKES no estilo DarkPlanner: em alguns trechos você pode pedir um template de "
                "composição colocando `\"template\": \"ID\"` no segmento (e, se o template tiver campos de texto, "
                "`\"template_campos\": {\"CAMPO\": \"texto\"}`). REGRAS: (a) \"trechos=N\" quer dizer que o template "
                "cobre ESTE segmento e os N-1 SEGUINTES (cada um continua com a própria query/provider — cada mídia "
                "vira um take que entra no tempo da própria fala), então só ponha template quando os N segmentos "
                "seguidos combinarem entre si e não ponha outro template dentro desses N; (b) a soma da duração dos "
                "N segmentos deve ficar dentro do intervalo \"dur\" do template; (c) use com moderação — no máximo "
                "1 template a cada 4-5 segmentos, variando as famílias, e deixe a maioria dos trechos normal; "
                "(d) campos fixos como \"TÓPICO\", \"CAPÍTULO\", \"PERFIL\" são ESPAÇOS pro texto do roteiro — "
                "preencha com 1-3 palavras tiradas da fala daquele trecho, no mesmo idioma (nunca deixe o rótulo "
                "de fábrica); \"ANTES\"/\"DEPOIS\" podem ser trocados pelos termos reais da comparação (ex: "
                "\"1990\"/\"HOJE\"); (e) templates que \"mostram a fala\" já exibem o que está sendo dito "
                "— não repita a mesma frase em on_screen_text nesses trechos. Templates disponíveis "
                "(ID | nome | trechos | duração | campos | quando usar):\n" + _catalogo_txt
            )
    if usar_templates:
        try:
            import dp_destaques
            import dp_direcao
            import dp_visual
            _dirs = "; ".join(f"\"{d['id']}\" = {d['nome']}" for d in dp_direcao.direcoes())
            _efs = ", ".join(e["id"] + ("(só foto)" if e["so_foto"] else "") for e in dp_visual.efeitos() if e["id"] != "none")
            _ents = ", ".join(e["id"] for e in dp_visual.entradas() if e["id"] != "none")
            _fams: Dict[str, List[str]] = {}
            for t in dp_visual.transicoes():
                _fams.setdefault(t["familia"] or "outras", []).append(t["dp_id"])
            _trs = " | ".join(f"{f}: {', '.join(ids)}" for f, ids in _fams.items())
            _fil = ", ".join(f["id"] for f in dp_visual.filtros())
            _hl = dp_destaques.bloco_para_prompt()
        except Exception:  # noqa: BLE001
            _hl = ""
        if _hl:
            rules.append(
                "(Opcional) ESTILO DE EDIÇÃO DarkPlanner. Na RAIZ do JSON você pode pôr `\"direcao\"` (um destes: " + _dirs + ") "
                "— ela preenche sozinha filtro, efeitos de câmera, transições e entradas nos trechos que você não especificar; "
                "e `\"filtro\"` (UM só pro vídeo inteiro, um destes: " + _fil + "), e `\"paleta\": {\"primaria\": \"#RRGGBB\", \"secundaria\": \"#RRGGBB\", \"acento\": \"#RRGGBB\"}` "
                "(cores do projeto, coerentes com o tema — secundária/acento = tons claro/médio da primária). Em cada segmento você pode pôr, se fizer sentido: "
                "`\"efeito\"` (" + _efs + "), `\"entrada\"`/`\"saida\"` (" + _ents + ") e `\"transition\"` = transição PARA o "
                "próximo segmento (" + _trs + "). Use pouco: a maioria dos trechos sem nada; efeitos de câmera só em media_type image."
            )
            rules.append(
                "(Opcional) GRÁFICOS ANIMADOS com dados que a narração CITA (nunca invente números): na RAIZ do JSON, "
                "`\"graficos\": [{\"tipo\": \"barras|barras_h|linha|pizza|rosca|comparacao|numero|progresso\", \"titulo\": \"...\", "
                "\"dados\": [{\"rotulo\": \"2010\", \"valor\": 191}], \"unidade\": \"%|R$|US$ bi|mi|km\", \"fonte\": \"...\", "
                "\"start\": 40.2, \"end\": 46.0, \"posicao\": \"centro|esquerda|direita|baixo|tela_cheia\"}]` — linha pra evolução no tempo, "
                "barras pra comparar categorias, pizza/rosca pra partes de um todo, comparacao pra A × B, numero/progresso pra um dado só."
            )
            rules.append(
                "(Opcional, recomendado) DESTAQUES DE TEXTO animados: na RAIZ do JSON, `\"highlights\": [{\"start\": 12.4, "
                "\"end\": 15.0, \"estilo\": \"ID\", \"texto\": \"...\"}]`. REGRAS (DarkPlanner): um destaque por vez, nunca "
                "sobrepostos, mínimo ~1,2s entre eles; start/end = o trecho da fala que ele cobre (o site ajusta o tempo exato "
                "pelas palavras); o texto vem da própria fala, no mesmo idioma, respeitando a faixa de palavras do estilo (pode "
                "encurtar ou escrever uma tese curta ligada ao trecho); estilos \"info\" SÓ quando o trecho tem aquele tipo de "
                "dado (ano, data, número, %, dinheiro, nome, local, bíblia…); 1 \"abertura\" no máximo, só no início; "
                "\"secao\" só em mudança de assunto; \"destaque\" pra frase mais importante de uma região (~1 a cada 30s), "
                "\"enfase\" pra uma palavra/frase forte (~1 a cada 15s). Estilos (ID | papel(subtipos) | palavras | quando):\n" + _hl
            )
    if formato in ("9:16", "1:1"):
        rules.append(
            ("O vídeo final é VERTICAL (9:16 — Shorts/Reels/TikTok): prefira cenas com o assunto no CENTRO e enquadramento "
             "fechado (retrato, close, objeto único, gente em pé), que funcionam recortadas na vertical; evite paisagens muito "
             "largas e cenas com o assunto nas laterais. Trechos mais curtos (2–4 s) costumam render mais nesse formato.")
            if formato == "9:16" else
            ("O vídeo final é QUADRADO (1:1 — feed): prefira cenas com o assunto no centro, que aguentam o recorte quadrado.")
        )
    if mix_midia:
        import mix_midia as _mm
        _regra_mix = _mm.regra_prompt(mix_midia, providers)
        if _regra_mix:
            rules.append(_regra_mix)
    rules_block = "\n".join(f"{i}. {rule}" for i, rule in enumerate(rules, start=1))
    _guia = _guia_buscas(providers, int(round(total_duration / max(1.0, float(interval_seconds or 7.0)))))
    guia_block = f"\n{_guia}\n" if _guia else ""

    # exemplo de JSON usa provedores DE VERDADE da lista selecionada — um
    # exemplo com nomes fixos (sempre "pexels"/"pixabay") sugeriria bancos
    # disponíveis mesmo quando não foram marcados, contradizendo a regra
    # de só usar os bancos da lista.
    # Pra escolher os provedores do EXEMPLO no JSON, evita "wikipedia" quando
    # possível — os exemplos genéricos ("sunrise over mountains", "person
    # typing on laptop") não são entidades reais/nomeadas, então usá-lo
    # como exemplo contradiria a própria regra que acabamos de dar sobre
    # ele (nome preciso de algo real + media_type "image" obrigatório).
    _non_wiki_providers = [p for p in providers if p not in (("wikipedia", "flow", "moviepexels", "moviepexels_online") + BROWSER_IMAGE_SEARCH_PROVIDERS + MANUAL_VIDEO_PROVIDERS)] or providers
    example_provider_a = _non_wiki_providers[0]
    example_provider_b = _non_wiki_providers[1] if len(_non_wiki_providers) > 1 else _non_wiki_providers[0]
    example_photo_line = (
        ',\n    {"start": 13.5, "end": 18.0, "visual": "detalhe: câmera antiga sobre a mesa", "provider": "pexels", "query": "vintage camera on wooden table", "media_type": "image", "alternativas": ["vintage camera"]}'
        if "pexels" in providers else ""
    )
    optional_fields = ["\"visual\" e \"alternativas\" (por segmento — fortemente recomendados)", "\"on_screen_text\" (por segmento)"]
    if "pexels" in providers or "wikipedia" in providers or "flow" in providers or _buscadores_navegador:
        optional_fields.append("\"media_type\" (por segmento, padrão \"video\")")
    optional_fields.append("\"busca_reserva\" (no nível raiz)")
    optional_fields.append("\"soundtrack_suggestion\" (no nível raiz)")
    optional_fields.append("\"overlays\" (lista, no nível raiz)")
    optional_fields_text = ", ".join(optional_fields)

    prompt = f"""Você vai me ajudar a montar um roteiro de vídeo de stock footage sincronizado com uma narração em áudio.

## Contexto

Abaixo está a transcrição completa de um áudio de narração em {language_hint}, com timestamps (em segundos) de cada trecho falado. A duração total do áudio é de {total_duration:.2f} segundos.

**{_regra_idioma(language_hint)}**

Antes de decidir qualquer coisa, leia a transcrição INTEIRA e entenda do que o vídeo trata como um todo: o tema geral, o tom (sério, leve, educativo, promocional, emocional...), e o público provável. Use esse entendimento do vídeo inteiro pra escolher termos de busca coerentes entre si ao longo de todos os segmentos — evite que a estética pule de um estilo pra outro sem motivo entre um trecho e o próximo.

## Transcrição com timestamps

{transcript_block}

## O que eu preciso que você faça

Divida a duração TOTAL do áudio (de 0.00s até {total_duration:.2f}s, sem nenhum buraco entre um trecho e o próximo) em segmentos de vídeo. Cada segmento vai virar um clipe de vídeo de banco de imagens diferente.

Regras:
{rules_block}
{guia_block}
## Formato de resposta — IMPORTANTE

Responda **apenas** com um JSON válido (sem texto antes ou depois, sem \\`\\`\\`json, sem comentários), no formato exato abaixo:

{{
  "busca_reserva": "calm morning landscape",
  "segments": [
    {{"start": 0.0, "end": 6.8, "visual": "abertura calma: nascer do sol nas montanhas", "provider": "{example_provider_a}", "query": "sunrise over mountains", "alternativas": ["mountain sunrise", "sunrise sky"]}},
    {{"start": 6.8, "end": 13.5, "visual": "fala de excesso de trabalho → homem exausto no notebook à noite", "provider": "{example_provider_b}", "query": "tired man on laptop at night", "alternativas": ["man working late", "laptop in dark room"], "on_screen_text": "12 horas por dia"}}{example_photo_line}
  ],
  "soundtrack_suggestion": "instrumental calmo e inspirador",
  "overlays": [
    {{"media_type": "text", "text": "3 MILHÕES", "start": 6.8, "end": 9.5}}
  ]
}}

"segments" é obrigatório e precisa cobrir o áudio inteiro como explicado acima. {optional_fields_text} são opcionais — inclua só quando fizer sentido, e omita completamente quando não tiver nada a sugerir.

{extra_instructions}
""".strip()

    return prompt


@dataclass
class VideoSegment:
    start: float
    end: float
    provider: str
    query: str
    on_screen_text: Optional[str] = None
    on_screen_text_style: Optional[Dict[str, Any]] = None
    """Personalização visual do texto acima — todos os campos
    opcionais, sem nenhum usa o visual padrão de sempre:
        "position": uma de "top-left", "top-center", "top-right",
            "middle-left", "middle-center", "middle-right",
            "bottom-left", "bottom-center" (padrão), "bottom-right".
        "font_size": tamanho em pixels (padrão: ~5.5% da altura do vídeo).
        "font_color": cor do texto, "#RRGGBB" (padrão: branco).
        "border": True/False — contorno ao redor das letras (padrão: False).
        "border_color"/"border_width": cor e espessura do contorno, só
            com "border": True (padrão: preto / 3px).
        "background": True/False — caixa semi-transparente atrás do
            texto (padrão: True).
        "shadow": True/False — sombra projetada atrás das letras
            (padrão: False).
        "shadow_color"/"shadow_offset": cor e deslocamento (px) da
            sombra, só com "shadow": True (padrão: preto / 2px).
        "font": "regular" ou "bold" (padrão: "bold").
        "animation": "none" (padrão) ou "fade" — texto surge/desaparece
            suavemente em vez de aparecer/sumir de repente.
        "animation_duration": segundos do fade de entrada/saída
            (padrão: 0.4), só com "animation": "fade".
    Ver `_build_drawtext_filter()` em video_assembler.py.
    """
    media_type: str = "video"
    aspect_fill: str = "black"
    trim_start_frames: Optional[int] = None
    """"video" (padrão) ou "image" — quando "image", `query` é usado pra
    buscar uma FOTO (não vídeo) no provedor indicado, aplicando o efeito
    Ken Burns (zoom lento) automaticamente pra preencher a duração do
    segmento. Só "pexels" suporta busca de fotos por enquanto."""
    image_fade_in: bool = False
    image_fade_out: bool = False
    image_fade_duration: float = 0.5
    """Só tem efeito com media_type="image": a FOTO (não o texto) surge/
    desaparece suavemente a partir de preto, em vez de aparecer/cortar
    de repente — dura `image_fade_duration` segundos (padrão 0.5).
    Independente da animação de texto ("animation" em
    on_screen_text_style acima)."""
    blur_sigma: float = 0.0
    """0 (padrão) = sem desfoque; qualquer valor > 0 aplica um desfoque
    gaussiano nessa intensidade ao clipe/foto inteiro (funciona tanto
    pra media_type="video" quanto "image"). Valores típicos úteis:
    5-15 pra um desfoque leve, 20+ pra bem forte/irreconhecível."""
    zoom_direction: str = "in"
    focus_x: float = 0.5
    focus_y: float = 0.5
    """Só tem efeito com media_type="image": a animação de câmera sobre
    a foto parada. "in"/"out" (zoom clássico), "pan_left"/"pan_right"/
    "pan_up"/"pan_down" (desliza sem mudar o zoom), ou "static" (parado,
    sem animação nenhuma). focus_x/focus_y (0.0 a 1.0) — em "in"/"out",
    o ponto que o zoom foca; em "pan_*", a posição fixa no eixo que NÃO
    está sendo percorrido. Pode ser sobrescrito por `override_source`
    (que tem prioridade quando os dois estão presentes)."""
    keyword_weight: Optional[float] = None
    semantic_weight: Optional[float] = None
    """Peso relativo entre correspondência literal de palavra-chave e
    correspondência semântica na busca — só tem efeito com o provedor
    "animepexels" (repassado direto pro `/api/search` do acervo local).
    Sem esses campos, o próprio acervo usa 1.0/1.0 (equilibrado) por
    padrão. Ignorado silenciosamente pelos outros 5 provedores, que não
    têm esse conceito."""
    transition: Optional[str] = None
    transition_duration: Optional[float] = None
    transition_som: Optional[str] = None
    """Transição deste trecho PARA o próximo (tipo do xfade, "none" = corte
    seco, None/"global" = usa a transição global do vídeo) e sua duração em
    segundos (None = a global). Definido no editor."""
    efeito: Optional[str] = None
    entrada: Optional[str] = None
    saida: Optional[str] = None
    """Catálogo do DarkPlanner (dp_visual.py): efeito do trecho (movimento de
    câmera em foto ou atmosfera em qualquer mídia), gesto de entrada e de saída."""
    template: Optional[str] = None
    template_campos: Optional[Dict[str, Any]] = None
    """Cena/take no estilo DarkPlanner (id do catálogo em cenas_dp.py). Um
    template de N slots aplicado neste trecho cobre ele e os N-1 seguintes;
    `template_campos` = textos dos campos fixos ("TÓPICO", "ANTES"…), mais
    "_fundo" (estilo do fundo) e "_fala" (False = não mostrar a fala)."""
    visual: Optional[str] = None
    alternativas: Optional[List[str]] = None
    busca_reserva: Optional[str] = None
    texto_da_ia: Optional[str] = None
    obra: Optional[str] = None
    personagem: Optional[str] = None
    """Só nos acervos locais (animepexels/moviepexels): busca só dentro dessa
    obra (anime, filme, série) e/ou só clipes com esse personagem/ator."""
    """Busca: "visual" = a imagem que a IA quis pôr ali (anotação em português,
    não aparece no vídeo); "alternativas" = buscas de reserva, da mais
    específica pra mais simples, tentadas quando `query` não acha nada;
    "busca_reserva" = busca genérica com a cara do vídeo inteiro (raiz do
    JSON da IA), o último recurso no lugar do antigo "nature background"."""
    clipes_extra: Optional[List[Dict[str, Any]]] = None
    """Clipe curto completado (aba ⏱ Clipes curtos do Estúdio): os clipes que
    entram DEPOIS do principal, na ordem, até cobrir o trecho — cada um
    {"source": "provider_url"|"url"|"local_file", "provider", "value", "duracao"}."""
    curto: Optional[str] = None
    """Clipe mais curto que o trecho: "loop" = repete o clipe (não completa com
    outra cena). Sem valor = o comportamento padrão da montagem."""
    override_source: Optional[Dict[str, Any]] = None
    """Define manualmente de onde vem a mídia desse segmento, pulando a
    busca por completo — usado pelo editor de segmentos do site, não faz
    parte do JSON gerado pela IA. Formato:
        {"kind": "video"|"image", "source": "local_file"|"url"|"provider_url",
         "value": "<caminho ou url>", "provider": "pexels" (só p/ provider_url),
         "zoom_direction": "in"|"out", "focus_x": 0.5, "focus_y": 0.5 (só p/ imagem)}
    """

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "start": self.start, "end": self.end, "provider": self.provider,
            "query": self.query, "on_screen_text": self.on_screen_text,
            "on_screen_text_style": self.on_screen_text_style,
            "media_type": self.media_type, "override_source": self.override_source,
            "keyword_weight": self.keyword_weight, "semantic_weight": self.semantic_weight,
            "trim_start_frames": self.trim_start_frames,
        }
        # Não adiciona as chaves novas nos JSONs antigos enquanto
        # estiverem no padrão; isso preserva compatibilidade com
        # estados/testes existentes. O editor/montador usa o padrão
        # (False/False/0.5) quando as chaves não existem.
        if self.aspect_fill != "black":
            data["aspect_fill"] = self.aspect_fill
        if self.image_fade_in:
            data["image_fade_in"] = self.image_fade_in
        if self.image_fade_out:
            data["image_fade_out"] = self.image_fade_out
        if self.image_fade_duration != 0.5:
            data["image_fade_duration"] = self.image_fade_duration
        if self.blur_sigma:
            data["blur_sigma"] = self.blur_sigma
        if self.zoom_direction != "in":
            data["zoom_direction"] = self.zoom_direction
        if self.focus_x != 0.5:
            data["focus_x"] = self.focus_x
        if self.focus_y != 0.5:
            data["focus_y"] = self.focus_y
        if self.transition:
            data["transition"] = self.transition
        if self.transition_duration is not None:
            data["transition_duration"] = self.transition_duration
        if self.transition_som:
            data["transition_som"] = self.transition_som
        for chave in ("efeito", "entrada", "saida"):
            valor = getattr(self, chave)
            if valor and valor != "none":
                data[chave] = valor
        if self.clipes_extra:
            data["clipes_extra"] = self.clipes_extra
        if self.curto:
            data["curto"] = self.curto
        if self.template:
            data["template"] = self.template
            if self.template_campos:
                data["template_campos"] = self.template_campos
        if self.visual:
            data["visual"] = self.visual
        if self.alternativas:
            data["alternativas"] = list(self.alternativas)
        if self.busca_reserva:
            data["busca_reserva"] = self.busca_reserva
        if self.obra:
            data["obra"] = self.obra
        if self.personagem:
            data["personagem"] = self.personagem
        if self.texto_da_ia:
            data["texto_da_ia"] = self.texto_da_ia  # texto na tela original da 1ª IA (ver app._marcar_textos_da_1a_ia)
        return data


@dataclass
class ParsedAIResponse:
    segments: List[VideoSegment]
    soundtrack_suggestion: Optional[str] = None
    overlays: List[Dict[str, Any]] = None
    cutaway_suggestions: List[Dict[str, Any]] = None
    direcao: Optional[str] = None
    filtro_cor: Optional[str] = None
    destaques: List[Dict[str, Any]] = None
    paleta: Optional[Dict[str, Any]] = None
    graficos: List[Dict[str, Any]] = None
    busca_reserva: Optional[str] = None

    def __post_init__(self):
        if self.overlays is None:
            self.overlays = []
        if self.cutaway_suggestions is None:
            self.cutaway_suggestions = []
        if self.destaques is None:
            self.destaques = []


def _json_loads_colado(text: str) -> Any:
    """json.loads que, se falhar, tenta consertar o que o copiar/colar da IA
    estraga (json_ia.py: tudo numa linha, quebra de linha dentro do texto,
    barras do markdown, aspas curvas, vírgulas…). Se nem assim der, solta o
    erro ORIGINAL do json.loads (as mensagens de erro de cada leitor usam ele)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        import json_ia
        try:
            return json_ia.carregar(text)
        except ValueError:
            raise exc from None


def _try_repair_common_json_issues(text: str) -> str:
    """Tenta consertar automaticamente erros comuns que a IA às vezes
    comete ao gerar JSON, antes de desistir e mostrar o erro pro
    usuário. Best-effort: se a correção não resolver, o parsing
    simplesmente falha de novo com o erro original (ver chamador).

    Caso coberto hoje: aspas duplicadas dentro de um valor de string —
    a IA tenta representar uma citação dentro do texto (ex:
    `"on_screen_text": ""Ele se acha superior""`) mas esquece de
    escapar as aspas internas. O JSON válido seria
    `"on_screen_text": "\\"Ele se acha superior\\""` — escapa as aspas
    internas em vez de deixá-las soltas, preservando a citação no
    texto (em vez de simplesmente descartar as aspas).
    """
    # Só mexe em `""conteúdo""` que apareça logo depois de `: ` (valor
    # de uma chave) — evita mexer em `""` legítimo (string vazia) ou em
    # outros lugares do JSON por engano.
    pattern = re.compile(r'(:\s*)""([^"]+)""')
    return pattern.sub(lambda m: f'{m.group(1)}"\\"{m.group(2)}\\""', text)


def _efeitos_dp_do_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """efeito/entrada/saida/transition do catálogo DarkPlanner num trecho da
    IA. Valor desconhecido é ignorado (não derruba o JSON)."""
    try:
        import dp_visual
    except Exception:  # noqa: BLE001
        return {}
    out: Dict[str, Any] = {}
    efeitos = {e["id"] for e in dp_visual.efeitos()} - {"none"}
    gestos = {e["id"] for e in dp_visual.entradas()} - {"none"}
    for chave, validos in (("efeito", efeitos), ("entrada", gestos), ("saida", gestos)):
        v = str(item.get(chave) or "").strip()
        if v in validos:
            out[chave] = v
    tr = str(item.get("transition") or "").strip()
    if tr:
        ids = {t["dp_id"] for t in dp_visual.transicoes()}
        if tr in ids:
            out["transition"] = dp_visual.valor_transicao(tr)
        elif tr.startswith("dp:") and tr[3:] in ids:
            out["transition"] = tr
    return out


def _destaques_da_ia(raw: Any) -> List[Dict[str, Any]]:
    """Lista "highlights"/"destaques" da raiz do JSON -> [{estilo, start, end, texto, campos}]."""
    if not isinstance(raw, list):
        return []
    try:
        import dp_destaques
        validos = set(dp_destaques.catalogo())
    except Exception:  # noqa: BLE001
        return []
    out = []
    for h in raw:
        if not isinstance(h, dict):
            continue
        estilo = str(h.get("estilo") or h.get("style") or "").strip()
        if estilo not in validos:
            continue
        try:
            ini, fim = float(h.get("start")), float(h.get("end"))
        except (TypeError, ValueError):
            continue
        if fim <= ini:
            continue
        campos = h.get("campos") if isinstance(h.get("campos"), dict) else {}
        out.append({"estilo": estilo, "start": ini, "end": fim, "texto": str(h.get("texto") or h.get("text") or "").strip(),
                    "campos": {str(k): str(v) for k, v in campos.items() if v is not None}})
    return out


def _template_do_item(item: Dict[str, Any]):
    """Lê "template"/"template_campos" que a IA pode mandar num trecho. Id
    desconhecido (ou de Avatar/Shutter) é simplesmente ignorado — não vale
    recusar o JSON inteiro por causa de um enfeite."""
    tid = str(item.get("template") or "").strip()
    if not tid:
        return None, None
    try:
        import cenas_dp
    except Exception:  # noqa: BLE001
        return None, None
    if not cenas_dp.template(tid):
        return None, None
    campos = item.get("template_campos") or item.get("campos") or {}
    if not isinstance(campos, dict):
        campos = {}
    validos = {c["key"]: c["maxChars"] for c in cenas_dp.campos_de_texto(tid)}
    limpos = {}
    for k, v in campos.items():
        if k in validos and v is not None:
            limpos[k] = str(v).strip()[: int(validos[k] or 120)]
    return tid, (limpos or None)


def _graficos_da_ia(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    lista = data.get("graficos") or data.get("charts") or []
    if not isinstance(lista, list):
        return []
    import dp_graficos
    return [g for g in (dp_graficos.normalizar(x) for x in lista[:30]) if g]


# ------------------------------------------------------------------ qualidade das buscas
# Provedores em que a "query" é uma busca por etiquetas (dá pra tirar o lixo
# tipo "4k footage" sem mudar o sentido) e onde não existe busca de reserva
# (flow gera, youtube a pessoa escolhe, wikipedia é o nome exato).
_PROVEDORES_COM_LIMPEZA = STOCK_PROVIDERS + ("animepexels", "moviepexels", "animepexels_online", "moviepexels_online")
_PROVEDORES_SEM_ALTERNATIVA = ("flow", "youtube", "wikipedia")

_RUIDO_BUSCA = re.compile(
    r"\b(?:4k|8k|uhd|full\s*hd|hd|1080p|720p|stock\s+(?:footage|videos?|clips?|photos?|images?)|footage|b-?roll|royalty[\s-]*free)\b",
    re.IGNORECASE,
)


def limpar_query(query: str) -> str:
    """Tira o que só atrapalha a busca num banco de estoque: aspas em volta,
    "4k", "HD", "stock footage", "b-roll", pontuação no fim, espaços
    repetidos. Devolve "" se não sobrar nada (quem chama mantém o original)."""
    q = str(query or "").strip().strip("\"'`“”‘’").strip()
    q = _RUIDO_BUSCA.sub(" ", q)
    q = re.sub(r"\s+", " ", q).strip(" .,;:-–—")
    return q


def _norm_busca(q: str) -> str:
    return " ".join(str(q or "").lower().split())


def alternativas_do_item(item: Dict[str, Any], query: str = "", limite: int = 3) -> List[str]:
    """Lê "alternativas" (lista, ou texto separado por | ou ;) de um trecho da
    IA: limpa, tira repetidas e a igual à query principal, no máximo `limite`."""
    raw = item.get("alternativas", item.get("alternatives"))
    if isinstance(raw, str):
        raw = re.split(r"[|;\n]", raw)
    if not isinstance(raw, list):
        return []
    saida: List[str] = []
    vistos = {_norm_busca(query)}
    for x in raw:
        if not isinstance(x, (str, int, float)) or isinstance(x, bool):
            continue
        t = limpar_query(str(x))[:100]
        if t and _norm_busca(t) not in vistos:
            saida.append(t)
            vistos.add(_norm_busca(t))
        if len(saida) >= limite:
            break
    return saida


_PALAVRAS_NAO_INGLES = {
    "de", "da", "do", "das", "dos", "com", "para", "pra", "uma", "um", "na", "nas", "nos", "em", "que", "sobre",
    "homem", "mulher", "pessoa", "pessoas", "cidade", "noite", "casa", "crianca", "criança", "rua", "floresta",
    "del", "los", "las", "con", "por", "una", "el",
}


def _parece_nao_ingles(q: str) -> bool:
    if re.search(r"[ãõçáéíóúâêôàüñ]", q.lower()):
        return True
    palavras = re.findall(r"[a-zA-Zçãõáéíóú]+", q.lower())
    return sum(1 for w in palavras if w in _PALAVRAS_NAO_INGLES) >= 1 and len(palavras) >= 2


def avisos_buscas(segmentos: List[Dict[str, Any]]) -> List[str]:
    """Confere as buscas que a IA mandou (dicts de `pending_segments`) e aponta
    o que costuma dar vídeo ruim: busca fora do inglês num banco de estoque,
    a mesma busca repetida muitas vezes ou em trechos seguidos, busca longa
    demais. Só olha trechos que vão MESMO ser buscados (sem mídia escolhida)."""
    estoque = set(_PROVEDORES_COM_LIMPEZA) | set(BROWSER_IMAGE_SEARCH_PROVIDERS)
    nao_ingles: List[int] = []
    longas: List[int] = []
    seguidas: List[int] = []
    contagem: Dict[str, int] = {}
    anterior = None
    for i, s in enumerate(segmentos or []):
        if not isinstance(s, dict) or s.get("override_source") or s.get("provider") not in estoque:
            anterior = None
            continue
        q = str(s.get("query") or "")
        n = _norm_busca(q)
        if s.get("provider") in _PROVEDORES_COM_LIMPEZA and s.get("provider") != "mixkit":
            if _parece_nao_ingles(q):
                nao_ingles.append(i + 1)
            if len(q.split()) > 7:
                longas.append(i + 1)
        if n and n == anterior:
            seguidas.append(i + 1)
        anterior = n
        if n:
            contagem[n] = contagem.get(n, 0) + 1

    def _lista(nums: List[int]) -> str:
        return ", ".join(str(x) for x in nums[:8]) + ("…" if len(nums) > 8 else "")

    avisos: List[str] = []
    if nao_ingles:
        avisos.append(f"{len(nao_ingles)} busca(s) não parecem estar em inglês (trechos {_lista(nao_ingles)}) — os bancos só entendem inglês.")
    repetidas = sorted(((c, q) for q, c in contagem.items() if c >= 3), reverse=True)
    if repetidas:
        avisos.append("Buscas repetidas: " + "; ".join(f"“{q}” {c}×" for c, q in repetidas[:3]) + " — o vídeo fica monótono.")
    if seguidas:
        avisos.append(f"Mesma busca em trechos seguidos (trechos {_lista(seguidas)}).")
    if longas:
        avisos.append(f"{len(longas)} busca(s) longas demais (trechos {_lista(longas)}) — muitas palavras costumam zerar o resultado.")
    return avisos


def parse_ai_response(
    raw_text: str,
    valid_providers: Optional[List[str]] = None,
    total_duration: Optional[float] = None,
    max_segments: int = 500,
    min_segment_duration: float = 0.3,
) -> ParsedAIResponse:
    """Valida e converte o JSON colado (resposta da outra IA) num
    `ParsedAIResponse` (segmentos + sugestão de trilha sonora, se a IA
    tiver incluído uma). Levanta `PromptBuilderError` com uma mensagem
    clara se algo estiver errado — isso é o que você vai mostrar pro
    usuário no site se ele colar algo inválido.

    Aceita dois formatos de resposta:
      1) O formato novo (o que `build_prompt` pede agora): um objeto
         `{"segments": [...], "soundtrack_suggestion": "..."}` — a
         sugestão de trilha é opcional.
      2) O formato antigo: uma lista de segmentos direto, sem o
         envelope — continua funcionando, só sem sugestão de trilha.

    Cada segmento pode opcionalmente ter um `"on_screen_text"` (texto
    pra exibir na tela durante aquele trecho) — ainda não é renderizado
    de verdade no vídeo final (isso vem numa fase seguinte), mas já é
    capturado e guardado, pra não perder a sugestão da IA.

    valid_providers: se fornecido, rejeita qualquer segmento com um
        provedor fora dessa lista.
    total_duration: se fornecido, confere que os segmentos cobrem o
        áudio inteiro sem buracos nem sobreposição (com uma tolerância
        pequena para arredondamento).
    max_segments: teto de segurança — uma resposta com mais segmentos
        que isso é rejeitada antes de tentar buscar/baixar nada (evita
        um JSON malformado ou uma IA "confusa" tentar disparar milhares
        de downloads de uma vez).
    min_segment_duration: segmentos mais curtos que isso (em segundos)
        são rejeitados — durações fracionárias minúsculas não fazem
        sentido pra um clipe de vídeo e tendem a indicar um erro da IA
        ao dividir o áudio.
    """
    text = raw_text.strip()
    # Às vezes a IA obedece mas ainda embrulha em ```json ... ``` — tira
    # isso automaticamente em vez de rejeitar, já que é um erro comum e
    # fácil de corrigir sem incomodar o usuário.
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()

    try:
        data = _json_loads_colado(text)
    except json.JSONDecodeError as exc:
        repaired = _try_repair_common_json_issues(text)
        if repaired != text:
            try:
                data = json.loads(repaired)
            except json.JSONDecodeError:
                data = None  # a correção não resolveu — cai pro erro original abaixo
        else:
            data = None
        if data is None:
            context_start = max(0, exc.pos - 60)
            context_end = min(len(text), exc.pos + 60)
            snippet = text[context_start:context_end]
            raise PromptBuilderError(
                f"O texto colado não é um JSON válido: {exc}. "
                f"Trecho perto do erro: ...{snippet}... "
                "Confira se copiou a resposta inteira da IA, sem cortar nada — um erro comum é a IA "
                "colocar aspas dentro de uma frase sem escapar (ex: \"on_screen_text\": \"\"Ele disse isso\"\" "
                "em vez de \"on_screen_text\": \"Ele disse isso\")."
            ) from exc

    soundtrack_suggestion: Optional[str] = None
    raw_overlays: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        if "segments" not in data:
            raise PromptBuilderError(
                "Esperava um objeto com a chave \"segments\" (lista de segmentos), "
                f"mas não encontrei essa chave. Chaves recebidas: {list(data.keys())}."
            )
        raw_segments = data["segments"]
        suggestion = data.get("soundtrack_suggestion")
        if suggestion is not None:
            soundtrack_suggestion = str(suggestion).strip() or None
        raw_overlays = data.get("overlays") or []
        if not isinstance(raw_overlays, list):
            raise PromptBuilderError(f"'overlays' precisa ser uma lista, recebi {type(raw_overlays).__name__}.")
        raw_cutaways = data.get("cutaway_suggestions") or []
        if not isinstance(raw_cutaways, list):
            raise PromptBuilderError(f"'cutaway_suggestions' precisa ser uma lista, recebi {type(raw_cutaways).__name__}.")
        direcao_ia = str(data.get("direcao") or "").strip() or None
        filtro_ia = str(data.get("filtro") or data.get("filtro_cor") or "").strip() or None
        destaques_ia = _destaques_da_ia(data.get("highlights") or data.get("destaques"))
        paleta_ia = data.get("paleta") if isinstance(data.get("paleta"), dict) else None
        busca_reserva = limpar_query(str(data.get("busca_reserva") or data.get("fallback_query") or ""))[:100] or None
    else:
        raw_segments = data  # formato antigo: lista direto, sem envelope
        raw_cutaways = []
        direcao_ia = filtro_ia = None
        destaques_ia = []
        paleta_ia = None
        busca_reserva = None

    if not isinstance(raw_segments, list) or not raw_segments:
        raise PromptBuilderError("Esperava uma lista JSON não-vazia de segmentos.")

    if len(raw_segments) > max_segments:
        raise PromptBuilderError(
            f"A resposta tem {len(raw_segments)} segmentos, mais que o limite de {max_segments}. "
            "Isso geralmente indica um erro no JSON (ou a IA dividiu o áudio em pedaços "
            "pequenos demais) — confira a resposta antes de colar de novo."
        )

    valid_providers_set = set(p.lower() for p in valid_providers) if valid_providers else None
    segments: List[VideoSegment] = []

    for i, item in enumerate(raw_segments):
        if not isinstance(item, dict):
            raise PromptBuilderError(f"Item {i} não é um objeto JSON válido: {item!r}")

        missing = [k for k in ("start", "end", "provider", "query") if k not in item]
        if missing:
            raise PromptBuilderError(f"Item {i} está faltando campo(s): {missing} — item: {item!r}")

        try:
            start = float(item["start"])
            end = float(item["end"])
        except (TypeError, ValueError) as exc:
            raise PromptBuilderError(f"Item {i}: 'start'/'end' precisam ser números — {item!r}") from exc

        provider = str(item["provider"]).strip().lower()
        query = str(item["query"]).strip()
        if provider in _PROVEDORES_COM_LIMPEZA:
            query = limpar_query(query) or query
        alternativas = alternativas_do_item(item, query) if provider not in _PROVEDORES_SEM_ALTERNATIVA else []
        visual = str(item.get("visual") or "").strip()[:240] or None
        obra = personagem = None
        if provider in BIBLIOTECAS_LOCAIS:
            obra = str(item.get("obra") or item.get("work") or item.get("anime") or "").strip()[:600] or None
            personagem = str(item.get("personagem") or item.get("character") or item.get("ator") or "").strip()[:600] or None
        on_screen_text = item.get("on_screen_text")
        if on_screen_text is not None:
            on_screen_text = str(on_screen_text).strip() or None
        media_type = str(item.get("media_type", "video")).strip().lower() or "video"

        keyword_weight = item.get("keyword_weight")
        semantic_weight = item.get("semantic_weight")
        if keyword_weight is not None:
            try:
                keyword_weight = float(keyword_weight)
            except (TypeError, ValueError) as exc:
                raise PromptBuilderError(f"Item {i}: 'keyword_weight' precisa ser um número, recebi {keyword_weight!r}.") from exc
            if keyword_weight <= 0:
                raise PromptBuilderError(f"Item {i}: 'keyword_weight' precisa ser maior que 0, recebi {keyword_weight}.")
        if semantic_weight is not None:
            try:
                semantic_weight = float(semantic_weight)
            except (TypeError, ValueError) as exc:
                raise PromptBuilderError(f"Item {i}: 'semantic_weight' precisa ser um número, recebi {semantic_weight!r}.") from exc
            if semantic_weight <= 0:
                raise PromptBuilderError(f"Item {i}: 'semantic_weight' precisa ser maior que 0, recebi {semantic_weight}.")

        if end <= start:
            raise PromptBuilderError(f"Item {i}: 'end' ({end}) deve ser maior que 'start' ({start}).")
        if (end - start) < min_segment_duration:
            raise PromptBuilderError(
                f"Item {i}: duração de {end - start:.3f}s é menor que o mínimo de "
                f"{min_segment_duration}s — provavelmente um erro ao dividir o áudio."
            )
        if not query:
            raise PromptBuilderError(f"Item {i}: 'query' está vazio.")
        if valid_providers_set and provider not in valid_providers_set:
            raise PromptBuilderError(
                f"Item {i}: provedor {provider!r} não está entre os permitidos {sorted(valid_providers_set)}."
            )
        if media_type not in ("video", "image"):
            raise PromptBuilderError(f"Item {i}: media_type precisa ser 'video' ou 'image', recebi {media_type!r}.")
        if media_type == "image" and provider in MANUAL_VIDEO_PROVIDERS:
            raise PromptBuilderError(
                f"Item {i}: o provedor {provider!r} só traz VÍDEO — tire o media_type='image' desse segmento "
                "(ou troque o provedor por um que busque fotos)."
            )
        if media_type == "image" and provider not in PHOTO_SEARCH_PROVIDERS:
            raise PromptBuilderError(
                f"Item {i}: media_type='image' só é suportado com provider em "
                f"{sorted(PHOTO_SEARCH_PROVIDERS)} (recebi provider={provider!r})."
            )

        template_id, template_campos = _template_do_item(item)
        extras_dp = _efeitos_dp_do_item(item)

        segments.append(VideoSegment(
            start=start, end=end, provider=provider, query=query,
            on_screen_text=on_screen_text, media_type=media_type,
            keyword_weight=keyword_weight, semantic_weight=semantic_weight,
            template=template_id, template_campos=template_campos,
            visual=visual, alternativas=alternativas or None, obra=obra, personagem=personagem,
            busca_reserva=busca_reserva if provider not in _PROVEDORES_SEM_ALTERNATIVA else None,
            **extras_dp,
        ))

    segments.sort(key=lambda s: s.start)

    # Confere continuidade (sem buracos/sobreposição grande) — tolerância
    # de 0.05s pra não rejeitar por arredondamento inofensivo.
    tolerance = 0.05
    for i in range(1, len(segments)):
        gap = segments[i].start - segments[i - 1].end
        if abs(gap) > tolerance:
            raise PromptBuilderError(
                f"Buraco/sobreposição entre os segmentos {i - 1} e {i}: "
                f"segmento {i - 1} termina em {segments[i - 1].end:.2f}s, "
                f"segmento {i} começa em {segments[i].start:.2f}s."
            )

    if total_duration is not None:
        if segments[0].start > tolerance:
            raise PromptBuilderError(
                f"O primeiro segmento começa em {segments[0].start:.2f}s, deveria começar em 0.0s."
            )
        if abs(segments[-1].end - total_duration) > tolerance:
            raise PromptBuilderError(
                f"O último segmento termina em {segments[-1].end:.2f}s, mas o áudio dura "
                f"{total_duration:.2f}s — a resposta da IA não cobre o áudio inteiro."
            )

    parsed_overlays: List[Dict[str, Any]] = []
    for i, ov in enumerate(raw_overlays):
        if not isinstance(ov, dict):
            raise PromptBuilderError(f"Overlay {i}: esperava um objeto, recebi {type(ov).__name__}.")
        try:
            ov_start = float(ov["start"])
            ov_end = float(ov["end"])
        except KeyError as exc:
            raise PromptBuilderError(f"Overlay {i}: falta o campo {exc}.") from None
        except (TypeError, ValueError) as exc:
            raise PromptBuilderError(f"Overlay {i}: 'start'/'end' precisam ser números. {exc}") from exc
        if ov_end <= ov_start:
            raise PromptBuilderError(f"Overlay {i}: 'end' ({ov_end}) deve ser maior que 'start' ({ov_start}).")

        ov_media_type = str(ov.get("media_type", "text")).strip().lower()
        if ov_media_type == "text":
            text = str(ov.get("text", "")).strip()
            if not text:
                raise PromptBuilderError(f"Overlay {i}: media_type='text' precisa de 'text' não-vazio.")
            parsed_overlays.append({
                "media_type": "text", "text": text, "start": ov_start, "end": ov_end,
                "style": ov.get("style") if isinstance(ov.get("style"), dict) else None,
            })
        elif ov_media_type in ("image", "video"):
            ov_provider = str(ov.get("provider", "")).strip().lower()
            ov_query = str(ov.get("query", "")).strip()
            if not ov_provider or not ov_query:
                raise PromptBuilderError(f"Overlay {i}: media_type={ov_media_type!r} precisa de 'provider' e 'query'.")
            if ov_provider in MANUAL_VIDEO_PROVIDERS:
                raise PromptBuilderError(
                    f"Overlay {i}: o provedor {ov_provider!r} não é buscado automaticamente — overlays precisam "
                    "de um banco de imagem/vídeo comum (pexels, pixabay...)."
                )
            if valid_providers_set and ov_provider not in valid_providers_set:
                raise PromptBuilderError(
                    f"Overlay {i}: provedor {ov_provider!r} não está entre os permitidos {sorted(valid_providers_set)}."
                )
            parsed_overlays.append({
                "media_type": ov_media_type,
                "source": {"source": "provider_search", "provider": ov_provider, "query": ov_query},
                "start": ov_start, "end": ov_end,
                "position": ov.get("position", "top-right"),
                "size_percent": ov.get("size_percent", 20),
            })
        else:
            raise PromptBuilderError(f"Overlay {i}: media_type precisa ser 'text', 'image' ou 'video', recebi {ov_media_type!r}.")

    parsed_cutaways: List[Dict[str, Any]] = []
    valid_audio_modes = {"pause", "continue"}
    for i, cut in enumerate(raw_cutaways):
        if not isinstance(cut, dict):
            raise PromptBuilderError(f"Corte sugerido {i}: esperava um objeto, recebi {type(cut).__name__}.")
        try:
            insertion_point = float(cut["insertion_point"])
        except KeyError as exc:
            raise PromptBuilderError(f"Corte sugerido {i}: falta o campo {exc}.") from None
        except (TypeError, ValueError) as exc:
            raise PromptBuilderError(f"Corte sugerido {i}: 'insertion_point' precisa ser um número. {exc}") from exc
        if insertion_point < 0:
            raise PromptBuilderError(f"Corte sugerido {i}: 'insertion_point' não pode ser negativo, recebi {insertion_point}.")
        if total_duration is not None and insertion_point > total_duration:
            raise PromptBuilderError(
                f"Corte sugerido {i}: 'insertion_point' ({insertion_point}) é maior que a duração do áudio "
                f"({total_duration:.2f})."
            )
        description = str(cut.get("description", "")).strip()
        if not description:
            raise PromptBuilderError(f"Corte sugerido {i}: 'description' não pode ficar vazio — diga o que deveria ser inserido ali.")
        audio_mode = str(cut.get("audio_mode", "pause")).strip().lower()
        if audio_mode not in valid_audio_modes:
            raise PromptBuilderError(f"Corte sugerido {i}: 'audio_mode' precisa ser 'pause' ou 'continue', recebi {audio_mode!r}.")
        cut_entry = {
            "insertion_point": insertion_point, "description": description, "audio_mode": audio_mode,
        }
        cut_query = str(cut.get("query") or "").strip()
        if cut_query:
            cut_entry["query"] = cut_query
        parsed_cutaways.append(cut_entry)

    try:
        import dp_direcao
        import dp_visual
        if direcao_ia and not dp_direcao.direcao(direcao_ia):
            direcao_ia = None
        if filtro_ia and not dp_visual.cadeia_filtro(filtro_ia):
            filtro_ia = None
    except Exception:  # noqa: BLE001
        direcao_ia = filtro_ia = None

    return ParsedAIResponse(
        segments=segments, soundtrack_suggestion=soundtrack_suggestion,
        overlays=parsed_overlays, cutaway_suggestions=parsed_cutaways,
        direcao=direcao_ia, filtro_cor=filtro_ia, destaques=destaques_ia,
        paleta=(__import__("dp_cores").normalizar(paleta_ia) if paleta_ia else None),
        graficos=_graficos_da_ia(data),
        busca_reserva=busca_reserva,
    )


# ------------------------------------------------------------------ revisão das buscas (2ª passada, no Estúdio)
# O prompt principal pede MUITA coisa de uma vez (tempos, provedores, textos,
# overlays, cenas, destaques, gráficos...), e a atenção da IA pras buscas se
# dilui. Esta segunda passada manda só a fala de cada trecho + a busca atual e
# pede uma coisa só: buscas melhores.

def trecho_revisavel(seg: Dict[str, Any]) -> bool:
    """A busca desse trecho pode ser trocada pela revisão? Só nos bancos de
    estoque e sem mídia escolhida à mão."""
    return seg.get("provider") in STOCK_PROVIDERS + BROWSER_IMAGE_SEARCH_PROVIDERS and not seg.get("override_source")


def _motivo_fixo(seg: Dict[str, Any]) -> str:
    if seg.get("override_source"):
        return "mídia escolhida à mão"
    prov = seg.get("provider")
    if prov == "flow":
        return "imagem gerada por IA"
    if prov == "youtube":
        return "vídeo do YouTube"
    if prov == "wikipedia":
        return "foto real da Wikipedia"
    if prov == "animepexels":
        return "acervo de anime"
    if prov == "moviepexels":
        return "acervo de filmes e séries"
    if prov == "animepexels_online":
        return "acervo online de anime"
    if prov == "moviepexels_online":
        return "acervo online de filmes e séries"
    return f"provedor {prov}"


def build_revisao_buscas_prompt(
    trechos: List[Dict[str, Any]],
    language_hint: str = "português",
    formato: Optional[str] = None,
    objetivo: str = "",
) -> str:
    """Prompt da revisão de buscas. `trechos`: dicts com start, end, provider,
    query, media_type, override_source (opcional), alternativas, visual e
    "fala" (o que é dito naquele trecho)."""
    if not trechos:
        raise PromptBuilderError("Sem trechos pra revisar.")
    editaveis = [i for i, t in enumerate(trechos) if trecho_revisavel(t)]
    if not editaveis:
        raise PromptBuilderError(
            "Nenhum trecho busca em banco de estoque (pexels, pixabay…) ou buscador de imagem (bing…) sem mídia escolhida — não há busca pra revisar."
        )
    provs = sorted({trechos[i].get("provider") for i in editaveis})
    linhas = []
    for i, t in enumerate(trechos):
        fala = " ".join(str(t.get("fala") or "").split())
        if len(fala) > 260:
            fala = fala[:257] + "…"
        tempo = f"[{_format_timestamp(float(t.get('start', 0)))}–{_format_timestamp(float(t.get('end', 0)))}]"
        if i not in editaveis:
            linhas.append(f"#{i} {tempo} (FIXO — {_motivo_fixo(t)}; não devolva) fala: \"{fala}\"")
            continue
        tipo = "foto" if t.get("media_type") == "image" else "vídeo"
        extra = ""
        if t.get("alternativas"):
            extra = " | reservas: " + ", ".join(f"\"{a}\"" for a in t["alternativas"][:3])
        linhas.append(f"#{i} {tempo} {t.get('provider')} · {tipo} | fala: \"{fala}\" | busca atual: \"{t.get('query', '')}\"{extra}")
    formato_txt = ""
    if formato == "9:16":
        formato_txt = "\nO vídeo é VERTICAL (9:16): prefira assunto único no centro e enquadramento fechado (close, retrato, objeto)."
    elif formato == "1:1":
        formato_txt = "\nO vídeo é QUADRADO (1:1): prefira assunto no centro."
    objetivo_txt = f"\n\nPedido de quem está editando (siga com prioridade): {objetivo.strip()}" if (objetivo or "").strip() else ""
    guia = _guia_buscas(provs, len(editaveis))
    buscadores = [p for p in provs if p in BROWSER_IMAGE_SEARCH_PROVIDERS]
    if buscadores:
        guia += ("\n\n" if guia else "") + (
            "## Trechos de buscador de imagem (" + ", ".join(buscadores) + ")\n\n"
            "Esses pesquisam a web inteira (Bing Imagens etc.), então aqui nome próprio é bem-vindo (filme, ator, "
            "personagem, lugar, produto) e a busca pode ficar no idioma em que o assunto é conhecido. O problema "
            "deles é outro: termo igual ou parecido em trechos diferentes devolve a MESMA imagem, e o vídeo fica "
            "parado nela. Cada trecho precisa de um termo DIFERENTE — outra cena, outro personagem, o pôster, os "
            "bastidores, o diretor no set, um objeto marcante, a época (ex.: \"Reservoir Dogs diner scene\" → "
            "\"Reservoir Dogs warehouse standoff\" → \"Michael Madsen Mr. Blonde\" → \"Tarantino on set 1992\"). "
            "Evite termos que puxam banco pago (\"stock photo\"), que vêm com marca d'água."
        )
    return f"""Você é um editor de vídeo escolhendo o B-roll de um vídeo narrado. A mídia de cada trecho é buscada AUTOMATICAMENTE num banco de vídeo/foto de estoque pela busca ("query") de cada trecho — e muitas buscas atuais estão fracas: abstratas, genéricas, repetidas ou sem relação com o que está sendo dito. Sua tarefa é SÓ melhorar as buscas. Não mude tempos, provedores, textos nem mais nada.

A narração está em {language_hint}; as buscas são sempre em inglês.{formato_txt}{objetivo_txt}

Antes de começar, leia todos os trechos e entenda o tema e o tom do vídeo inteiro — a identidade visual vem daí.

## Trechos (fala → busca atual)

{chr(10).join(linhas)}

{guia}

## Formato de resposta — IMPORTANTE

Devolva TODOS os trechos que não são FIXOS ({len(editaveis)} trechos), cada um com a busca final — pode repetir a atual se ela já estiver boa, mas sempre com "visual" e "alternativas". Responda **apenas** com um JSON válido (sem texto antes ou depois, sem comentários), assim:

{{
  "busca_reserva": "dark foggy forest at night",
  "trechos": [
    {{"i": {editaveis[0]}, "visual": "estrada vazia no escuro, clima de mistério", "query": "empty dark road at night", "alternativas": ["dark road at night", "night road"]}}
  ]
}}

"i" é o número do trecho (o que vem depois do # na lista)."""


def ler_revisao_buscas(texto: str, trechos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Lê a resposta da revisão de buscas. Devolve {"trechos": [{"i", "query",
    "alternativas", "visual", "antes", "mudou"}], "busca_reserva", "avisos"}.
    Trecho fixo/inexistente/sem busca é ignorado com aviso."""
    bruto = re.sub(r"^```(?:json)?\s*|\s*```$", "", (texto or "").strip(), flags=re.MULTILINE).strip()
    if not bruto:
        raise PromptBuilderError("Cole a resposta da IA.")
    try:
        data = _json_loads_colado(bruto)
    except json.JSONDecodeError:
        ini, fim = bruto.find("{"), bruto.rfind("}")
        try:
            data = json.loads(_try_repair_common_json_issues(bruto[ini:fim + 1])) if 0 <= ini < fim else None
        except json.JSONDecodeError:
            data = None
        if data is None:
            raise PromptBuilderError("A resposta não é um JSON válido — confira se copiou ela inteira.")
    if isinstance(data, list):
        itens, reserva_raw = data, None
    elif isinstance(data, dict):
        itens = data.get("trechos") or data.get("segments") or data.get("buscas") or []
        reserva_raw = data.get("busca_reserva")
    else:
        itens, reserva_raw = [], None
    if not isinstance(itens, list):
        raise PromptBuilderError("Esperava uma lista em \"trechos\".")
    avisos: List[str] = []
    por_indice: Dict[int, Dict[str, Any]] = {}
    for k, item in enumerate(itens):
        if not isinstance(item, dict):
            continue
        idx_raw = item.get("i", item.get("indice", item.get("trecho")))
        try:
            i = int(str(idx_raw).lstrip("#"))
        except (TypeError, ValueError):
            avisos.append(f"Item {k + 1} sem número de trecho — ignorado.")
            continue
        if not (0 <= i < len(trechos)):
            avisos.append(f"Trecho #{i} não existe — ignorado.")
            continue
        if not trecho_revisavel(trechos[i]):
            avisos.append(f"Trecho #{i} é fixo ({_motivo_fixo(trechos[i])}) — ignorado.")
            continue
        query = limpar_query(str(item.get("query") or ""))[:120]
        if not query:
            avisos.append(f"Trecho #{i} veio sem busca — ignorado.")
            continue
        if _parece_nao_ingles(query):
            avisos.append(f"Trecho #{i}: “{query}” não parece estar em inglês.")
        antes = str(trechos[i].get("query") or "")
        por_indice[i] = {
            "i": i, "query": query, "antes": antes,
            "alternativas": alternativas_do_item(item, query),
            "visual": str(item.get("visual") or "").strip()[:240] or None,
            "mudou": _norm_busca(query) != _norm_busca(antes),
        }
    if not por_indice:
        raise PromptBuilderError("Nenhum trecho válido na resposta" + (f" ({avisos[0]})" if avisos else "") + ".")
    faltando = [i for i, t in enumerate(trechos) if trecho_revisavel(t) and i not in por_indice]
    if faltando:
        avisos.append(f"{len(faltando)} trecho(s) não vieram na resposta e ficam como estão.")
    return {
        "trechos": [por_indice[i] for i in sorted(por_indice)],
        "busca_reserva": limpar_query(str(reserva_raw or ""))[:100] or None,
        "avisos": avisos,
    }
