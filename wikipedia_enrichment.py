"""
wikipedia_enrichment.py
=========================

Modo "este vídeo tem fontes de imagens da Wikipedia": em vez de deixar
a IA simplesmente CHUTAR quais termos buscar no provedor "wikipedia"
(arriscando escolher nomes que não têm foto nenhuma lá, ou nem
existem), esse módulo faz uma pesquisa de verdade ANTES de montar o
prompt:

    1. `extrair_entidades_candidatas(segments)` — varre o texto do
       roteiro procurando nomes próprios candidatos (sequências de
       palavras capitalizadas: "Albert Einstein", "Torre Eiffel",
       "Segunda Guerra Mundial"...), sem precisar de IA nenhuma —
       só uma heurística de texto.

    2. `buscar_entidades_confirmadas_na_wikipedia(candidatos)` —
       pesquisa CADA candidato na Wikipedia de verdade (via
       `toolkit/wikipedia_api_client.py`) e só mantém os que realmente
       têm pelo menos uma foto — os que não existem, ou existem mas
       sem foto, são descartados.

O resultado (uma lista pequena e VERIFICADA de entidades com foto
confirmada) é passado pra `prompt_builder.build_prompt()`, que monta
uma regra dizendo à IA pra usar esses termos exatos nos momentos em
que a narração falar sobre eles, e usar os outros bancos de vídeo pro
resto — em vez de arriscar um "provider: wikipedia" com um termo que
nunca vai encontrar nada.
"""

from __future__ import annotations

import os
import re
import sys
from collections import Counter
from typing import Any, Dict, List, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
_TOOLKIT_DIR = os.path.join(_DIR, "toolkit")


class WikipediaEnrichmentError(Exception):
    """Erro genérico (rede indisponível, etc.) — pensado pra ser tratado
    como best-effort: quem chama pode simplesmente seguir sem
    enriquecimento nenhum em vez de travar o pipeline inteiro."""


# Palavras de ligação que continuam uma entidade em vez de quebrar ela
# em duas (ex: "Machado de Assis", "Estados Unidos da América") — só
# junta se vierem ENTRE duas palavras capitalizadas, nunca no início
# nem no fim de uma entidade.
_LIGACOES = {"de", "da", "do", "das", "dos", "e", "of", "the", "van", "von"}

# Palavras capitalizadas comuns demais pra valerem como entidade
# sozinhas (pronomes, dias da semana etc — coisas que aparecem
# capitalizadas só por estarem no início de frase).
_PALAVRAS_IGNORADAS = {
    "eu", "ele", "ela", "eles", "elas", "nós", "você", "vocês", "isso", "isto", "aquilo",
    "hoje", "ontem", "amanhã", "aqui", "ali", "lá",
    "segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo",
    "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
    "agosto", "setembro", "outubro", "novembro", "dezembro",
}

_PALAVRA_CAPITALIZADA_RE = re.compile(
    r"\b[A-ZÀ-Ý][a-zà-ÿ]+(?:['’][A-ZÀ-Ýa-zà-ÿ]+)?\b"
)


def _tokens_do_segmento(texto: str) -> List[tuple]:
    """Devolve [(palavra, é_inicio_de_frase), ...] pra cada palavra do
    texto — usado pra não contar a primeira palavra de cada frase como
    candidata (é só maiúscula por estar no início, na maioria das
    vezes), a menos que ela se junte a outra capitalizada logo depois.
    """
    partes = re.split(r"([.!?]\s+)", texto)
    resultado = []
    inicio_de_frase = True
    for parte in partes:
        if re.fullmatch(r"[.!?]\s+", parte or ""):
            inicio_de_frase = True
            continue
        for i, palavra in enumerate(re.findall(r"\S+", parte or "")):
            resultado.append((palavra, inicio_de_frase and i == 0))
    return resultado


def extrair_entidades_candidatas(segments: List[Dict[str, Any]], max_candidatos: int = 15) -> List[str]:
    """Varre o texto de todos os segmentos procurando sequências de
    palavras capitalizadas (nomes próprios candidatos) e devolve até
    `max_candidatos`, dos mais frequentes/mais longos primeiro.

    Não usa IA nenhuma — só uma heurística de texto (Title Case runs).
    Funciona bem pra português e inglês; outros idiomas podem ter
    resultado pior (a heurística depende de maiúscula/minúscula).
    """
    contagem: Counter = Counter()

    for seg in segments:
        texto = (seg.get("text") or "").strip()
        if not texto:
            continue
        tokens = _tokens_do_segmento(texto)

        i = 0
        while i < len(tokens):
            palavra, eh_inicio = tokens[i]
            palavra_limpa = palavra.strip(".,;:!?\"'()[]{}")
            eh_capitalizada = bool(_PALAVRA_CAPITALIZADA_RE.fullmatch(palavra_limpa))

            if not eh_capitalizada:
                i += 1
                continue

            # tenta estender a entidade pras palavras seguintes,
            # incluindo palavras de ligação NO MEIO (nunca no fim) --
            # SEMPRE tenta estender antes de decidir se descarta (uma
            # palavra sozinha tipo "Segunda" pode ser só o dia da
            # semana OU o início de "Segunda Guerra Mundial"; só dá
            # pra saber depois de tentar estender).
            fim = i + 1
            partes_entidade = [palavra_limpa]
            while fim < len(tokens):
                proxima, _ = tokens[fim]
                proxima_limpa = proxima.strip(".,;:!?\"'()[]{}")
                if _PALAVRA_CAPITALIZADA_RE.fullmatch(proxima_limpa):
                    partes_entidade.append(proxima_limpa)
                    fim += 1
                elif proxima_limpa.lower() in _LIGACOES and fim + 1 < len(tokens):
                    seguinte, _ = tokens[fim + 1]
                    seguinte_limpa = seguinte.strip(".,;:!?\"'()[]{}")
                    if _PALAVRA_CAPITALIZADA_RE.fullmatch(seguinte_limpa):
                        partes_entidade.append(proxima_limpa)
                        partes_entidade.append(seguinte_limpa)
                        fim += 2
                        continue
                    break
                else:
                    break

            entidade = " ".join(partes_entidade)
            eh_uma_palavra_so = len(partes_entidade) == 1
            # descarta palavra ÚNICA quando: é comum demais (pronome,
            # dia da semana...) OU está bem no início da frase (mais
            # provável de ser só maiúscula-de-início-de-frase do que
            # um nome próprio de verdade). Entidades de 2+ palavras
            # sempre contam -- "Segunda Guerra Mundial" nunca cai aqui.
            descarta = eh_uma_palavra_so and (
                palavra_limpa.lower() in _PALAVRAS_IGNORADAS or eh_inicio
            )
            if not descarta:
                contagem[entidade] += 1

            i = fim

    candidatos_ordenados = sorted(
        contagem.items(), key=lambda item: (item[1], len(item[0].split())), reverse=True,
    )
    return [entidade for entidade, _freq in candidatos_ordenados[:max_candidatos]]


def buscar_entidades_confirmadas_na_wikipedia(
    candidatos: List[str], max_verificacoes: int = 15, min_imagens: int = 1,
) -> List[Dict[str, str]]:
    """Pesquisa cada candidato na Wikipedia DE VERDADE e devolve só os
    que têm pelo menos `min_imagens` foto encontrada — best-effort: um
    candidato que dá erro (rede, página não encontrada etc) é só pulado,
    nunca derruba a busca inteira. Se a Wikipedia estiver totalmente
    inacessível, devolve lista vazia em vez de levantar exceção (quem
    chama decide o que fazer com uma lista vazia).
    """
    if _TOOLKIT_DIR not in sys.path:
        sys.path.insert(0, _TOOLKIT_DIR)
    try:
        from wikipedia_api_client import WikipediaAPIClient, WikipediaAPIClientError
    except ImportError:
        return []

    client = WikipediaAPIClient()
    confirmadas: List[Dict[str, str]] = []
    try:
        for candidato in candidatos[:max_verificacoes]:
            try:
                titulo = client.find_page_title(candidato)
                imagens = client.get_images_from_page(titulo, max_images=min_imagens)
            except WikipediaAPIClientError:
                continue
            except Exception:  # noqa: BLE001
                continue
            if len(imagens) < min_imagens:
                continue
            primeira = imagens[0]
            confirmadas.append({
                "termo": candidato,
                "titulo_pagina": titulo,
                "descricao": (primeira.descricao or primeira.legenda or "")[:150],
            })
    finally:
        try:
            client.session.close()
        except Exception:  # noqa: BLE001
            pass
    return confirmadas


def identificar_entidades_wikipedia(
    segments: List[Dict[str, Any]], max_candidatos: int = 15, max_verificacoes: int = 15,
) -> List[Dict[str, str]]:
    """Ponto de entrada único: extrai candidatos do roteiro e devolve só
    os confirmados com foto real na Wikipedia. Nunca levanta exceção —
    qualquer problema (heurística sem candidatos, Wikipedia fora do ar)
    resulta em lista vazia, e o pipeline principal segue normalmente
    sem esse enriquecimento.
    """
    try:
        com_ia = _entidades_com_ia(segments)  # 🤖 com a IA ligada: nomes da ficha + desambiguação
        if com_ia is not None:
            return com_ia
    except Exception:  # noqa: BLE001
        pass
    try:
        candidatos = extrair_entidades_candidatas(segments, max_candidatos=max_candidatos)
        if not candidatos:
            return []
        return buscar_entidades_confirmadas_na_wikipedia(candidatos, max_verificacoes=max_verificacoes)
    except Exception:  # noqa: BLE001
        return []


def _entidades_com_ia(segments: List[Dict[str, Any]], max_entidades: int = 40) -> Optional[List[Dict[str, str]]]:
    """🤖 (LEIA-ME §8, passos B e C) Os nomes vêm da FICHA do vídeo (pessoas e lugares, com o artigo
    da Wikipedia sugerido) em vez da heurística de maiúsculas; o 1º resultado da busca só é aceito
    quando bate com a ficha — as dúvidas vão TODAS numa chamada só pra IA escolher o artigo certo.
    Confirma com imagem que passou no filtro (sem bandeira/brasão/mapa). None = sem IA (usa o de sempre)."""
    import ia_servico
    if not ia_servico.ativo("wikipedia"):
        return None
    import ia_midia
    roteiro = " ".join(str(s.get("text") or "").strip() for s in segments or [])
    ficha = ia_midia.ficha_visual(roteiro)
    if not ficha:
        return None
    if _TOOLKIT_DIR not in sys.path:
        sys.path.insert(0, _TOOLKIT_DIR)
    from wikipedia_api_client import WikipediaAPIClient, WikipediaAPIClientError
    itens = [dict(x, _tipo="pessoa") for x in ficha.get("personagens") or []] + [dict(x, _tipo="lugar") for x in ficha.get("lugares") or []]
    client = WikipediaAPIClient()
    escolhidos: Dict[str, str] = {}
    duvidas = []
    try:
        for it in itens[:max_entidades]:
            nome = (it.get("nome") or "").strip()
            if not nome:
                continue
            sugerido = (it.get("wikipedia_en") or "").strip()
            try:
                cands = client.buscar_titulos(sugerido or it.get("busca") or nome, 5)
            except WikipediaAPIClientError:
                continue
            if not cands:
                continue
            if sugerido and cands[0]["titulo"].lower() == sugerido.lower():
                escolhidos[nome] = cands[0]["titulo"]
            else:
                duvidas.append({"nome": nome, "contexto": f"{it['_tipo']}; {it.get('como_aparece') or it.get('busca') or ''}; {it.get('epoca') or ficha.get('epoca') or ''}",
                                "candidatos": cands})
        if duvidas:
            res = ia_midia.desambiguar(duvidas, ficha, roteiro)
            for d in duvidas:
                t = res.get(d["nome"]) if d["nome"] in res else d["candidatos"][0]["titulo"]
                if t:
                    escolhidos[d["nome"]] = t
        confirmadas = []
        for nome, titulo in escolhidos.items():
            try:
                imgs = client.get_images_filtradas(titulo, max_images=1)
            except WikipediaAPIClientError:
                continue
            if imgs:
                confirmadas.append({"termo": nome, "titulo_pagina": titulo, "descricao": (imgs[0].descricao or imgs[0].legenda or "")[:150]})
        return confirmadas
    finally:
        try:
            client.session.close()
        except Exception:  # noqa: BLE001
            pass
