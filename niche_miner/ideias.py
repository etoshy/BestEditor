#!/usr/bin/env python3
"""
Ideias virais — lógica pura (sem navegador e sem rede)
======================================================

Implementa o fluxo de pesquisa de ideias descrito nos vídeos, no mesmo estilo
do resto do app (sem API paga):

  1. Radar      -> vídeos em alta no YouTube (coleta com Playwright, em ideias_scraper.py)
  2. IA         -> o app monta o PROMPT, você cola numa IA de chat e cola o JSON de volta
  3. Validação  -> autocomplete, "as pessoas também perguntam", Trends, concorrência
  4. Pontuação  -> ranking das ideias (pesos editáveis)
  5. Decisão    -> regra de "matar ou escalar" um canal (15-20 / 30 vídeos)

Este módulo guarda tudo o que dá para testar sem rede: montagem de prompts,
leitura tolerante do JSON devolvido pela IA, cálculo de sinais/pontuação,
classificação de séries do Trends e a persistência em SQLite (mesmo arquivo da
biblioteca, tabela própria).
"""

import csv
import io
import json
import re
import sqlite3
import statistics
import threading
import time
import uuid
from collections import Counter
from contextlib import closing
from datetime import datetime
from urllib.parse import quote

import biblioteca

# --------------------------------------------------------------------------
# Mercados (país + idioma) usados em YouTube, Google e Trends
# --------------------------------------------------------------------------

MERCADOS = {
    "BR": {"nome": "Brasil", "gl": "BR", "hl": "pt-BR", "idioma": "português (Brasil)"},
    "PT": {"nome": "Portugal", "gl": "PT", "hl": "pt-PT", "idioma": "português (Portugal)"},
    "US": {"nome": "Estados Unidos", "gl": "US", "hl": "en", "idioma": "inglês"},
    "GB": {"nome": "Reino Unido", "gl": "GB", "hl": "en-GB", "idioma": "inglês"},
    "MX": {"nome": "México", "gl": "MX", "hl": "es-419", "idioma": "espanhol"},
    "ES": {"nome": "Espanha", "gl": "ES", "hl": "es", "idioma": "espanhol"},
    "DE": {"nome": "Alemanha", "gl": "DE", "hl": "de", "idioma": "alemão"},
    "FR": {"nome": "França", "gl": "FR", "hl": "fr", "idioma": "francês"},
    "IT": {"nome": "Itália", "gl": "IT", "hl": "it", "idioma": "italiano"},
    "PL": {"nome": "Polônia", "gl": "PL", "hl": "pl", "idioma": "polonês"},
    "JP": {"nome": "Japão", "gl": "JP", "hl": "ja", "idioma": "japonês"},
}
MERCADO_PADRAO = "BR"


def mercado(codigo):
    """Dados do mercado; código desconhecido cai no padrão (Brasil)."""
    return MERCADOS.get(str(codigo or "").strip().upper()) or MERCADOS[MERCADO_PADRAO]


def codigo_mercado(valor, padrao=MERCADO_PADRAO):
    """Aceita o código (``DE``) ou o nome (``Alemanha``) e devolve o código."""
    v = biblioteca.normalizar(valor)
    if not v:
        return padrao
    for cod, m in MERCADOS.items():
        if v == biblioteca.normalizar(cod) or v == biblioteca.normalizar(m["nome"]):
            return cod
    return padrao


# --------------------------------------------------------------------------
# Leitura tolerante do JSON devolvido pela IA
# --------------------------------------------------------------------------

def extrair_json(texto):
    """Extrai o maior objeto/lista JSON de um texto colado.

    Tolera cercas de markdown, frases antes/depois do JSON e aspas tipográficas.
    Levanta ``ValueError`` com mensagem em português.
    """
    if texto is None or not str(texto).strip():
        raise ValueError("Cole o JSON devolvido pela IA.")
    t = str(texto).strip()
    t = re.sub(r"```[a-zA-Z]*", "", t)
    variantes = [t, t.replace("\u201c", '"').replace("\u201d", '"').replace("\u2019", "'")]
    dec = json.JSONDecoder()
    erro = None
    for v in variantes:
        melhor, melhor_len, pos = None, 0, 0
        while True:
            m = re.search(r"[\{\[]", v[pos:])
            if not m:
                break
            ini = pos + m.start()
            try:
                obj, fim = dec.raw_decode(v[ini:])
            except ValueError as e:
                erro = e
                pos = ini + 1
                continue
            if isinstance(obj, (dict, list)) and fim > melhor_len:
                melhor, melhor_len = obj, fim
            pos = ini + fim
        if melhor is not None:
            return melhor
    raise ValueError(f"JSON inválido: {erro}" if erro else "Não encontrei JSON no texto colado.")


def _chaves(d):
    """Dicionário com chaves normalizadas (sem acento/caixa, espaço -> _)."""
    return {re.sub(r"\s+", "_", biblioteca.normalizar(k)): v for k, v in d.items()} if isinstance(d, dict) else {}


def _txt(d, *chaves, padrao=""):
    for c in chaves:
        v = d.get(c)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return padrao


def _nota(valor):
    """Nota 0-5 (aceita 4, '4', '4/5', '4,5'); None se não for número."""
    if valor is None or isinstance(valor, bool):
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(valor))
    if not m:
        return None
    return round(min(5.0, max(0.0, float(m.group(0).replace(",", ".")))), 1)


def _lista_txt(valor, limite=12):
    if valor is None:
        return []
    if isinstance(valor, str):
        itens = re.split(r"[;\n]|,(?!\s*\d)", valor)
    elif isinstance(valor, (list, tuple, set)):
        itens = valor
    else:
        itens = [valor]
    saida = []
    for i in itens:
        s = str(i.get("nome") or i.get("termo") or i.get("busca") or i) if isinstance(i, dict) else str(i)
        s = s.strip()
        if s and s not in saida:
            saida.append(s)
    return saida[:limite]


# --------------------------------------------------------------------------
# Prompts (para colar em qualquer IA de chat — sem API)
# --------------------------------------------------------------------------

def _num(n):
    return f"{int(n):,}".replace(",", ".") if isinstance(n, (int, float)) else "?"


def _linha_video(i, v):
    meta = []
    if v.get("canal"):
        meta.append(f"canal: {v['canal']}")
    if v.get("views_num") is not None:
        meta.append(f"{_num(v['views_num'])} views")
    if v.get("quando"):
        meta.append(str(v["quando"]))
    if v.get("inscritos_num"):
        meta.append(f"canal com {_num(v['inscritos_num'])} inscritos")
    if v.get("razao_views_inscritos"):
        meta.append(f"{v['razao_views_inscritos']}x os inscritos")
    extra = f" ({'; '.join(meta)})" if meta else ""
    return f'{i}. "{v.get("titulo", "").strip()}"{extra}'


def montar_prompt_decomposicao(tema, videos, mercado_cod=MERCADO_PADRAO, refs_extra=None, limite=30):
    """Prompt 1: decompor vídeos em alta (emoção, estrutura, público, amplitude)."""
    m = mercado(mercado_cod)
    itens = list(videos or [])[:limite]
    linhas = [_linha_video(i, v) for i, v in enumerate(itens, 1)]
    for t in _lista_txt(refs_extra, limite=20):
        linhas.append(f'{len(linhas) + 1}. "{t}"')
    if not linhas:
        raise ValueError("Não há vídeos nem títulos de referência para montar o prompt.")
    return (
        "Você é um analista de títulos e formatos virais do YouTube.\n"
        f'Tema pesquisado: "{tema}". Mercado: {m["nome"]} ({m["idioma"]}).\n\n'
        "Vídeos que estão performando bem agora:\n" + "\n".join(linhas) + "\n\n"
        "Para CADA vídeo, decomponha o que faz uma pessoa clicar. Depois agrupe os vídeos em "
        "PADRÕES, separando o que é FIXO (o sentimento e a estrutura do título) do que é "
        "VARIÁVEL (personagem, cenário, mercado).\n\n"
        "Responda ESTRITAMENTE em JSON válido, sem markdown, sem texto antes ou depois, "
        "exatamente neste formato:\n"
        '{"videos": [{"indice": 1, "emocao": "", "estrutura_titulo": "", "personagem": "", '
        '"cenario": "", "promessa": "", "publico_obvio": "", "publicos_adjacentes": ["", ""], '
        '"por_que_fora_do_nicho_clica": "", "amplitude": 0}], '
        '"padroes": [{"nome": "", "emocao": "", "estrutura": "", "elementos_fixos": [""], '
        '"elementos_variaveis": [""], "indices": [1]}]}\n\n'
        'Regras: use o mesmo número de índice da lista acima. "amplitude" é um número de 0 a 5 '
        "(5 = qualquer pessoa consegue clicar no título, mesmo fora do nicho; 0 = só quem "
        "domina o jargão do nicho). Descreva a estrutura do título em uma frase curta "
        '(ex.: "tempo como prova + negação absoluta + primeira pessoa").'
    )


def montar_prompt_expansao(tema, mercado_cod=MERCADO_PADRAO, n=10):
    """Prompt 2: expandir um tema em alta (públicos adjacentes, buscas e problemas)."""
    m = mercado(mercado_cod)
    n = max(3, min(30, int(n or 10)))
    return (
        f'O tema "{tema}" está em alta no YouTube no mercado {m["nome"]} ({m["idioma"]}).\n\n'
        f"1. Liste públicos adjacentes: quem mais, além do público óbvio, se interessaria por esse tema, e por quê.\n"
        f"2. Liste as {n} buscas/problemas mais comuns das pessoas ligadas a esse tema, em ordem de "
        "volume provável, no idioma do mercado.\n"
        "3. Liste termos e sinônimos que valem ser pesquisados no Google e no Google Trends para "
        "confirmar volume real.\n\n"
        "Responda ESTRITAMENTE em JSON válido, sem markdown, sem texto antes ou depois, "
        "exatamente neste formato:\n"
        '{"publicos_adjacentes": [{"publico": "", "por_que": ""}], '
        '"problemas_e_buscas": [{"busca": "", "intencao": "", "motivo": ""}], '
        '"termos_para_validar": [""], "sinonimos": [""]}\n\n'
        "Trate tudo como hipótese: você não tem acesso a dados reais de volume."
    )


MODOS_IDEIAS = {
    "mesmo_mercado": "mesmo mercado (ângulo novo: mudar personagem e/ou cenário)",
    "outro_mercado": "outro mercado (levar o formato validado para outro país/idioma)",
    "ambos": "as duas coisas (ângulo novo E adaptação para outros mercados)",
}


def montar_prompt_ideias(tema, padroes, n=10, modo="ambos", mercado_base=MERCADO_PADRAO, mercados_alvo=None):
    """Prompt 3: gerar ideias — mesma emoção/estrutura, ângulo novo, título em 3 níveis."""
    base = mercado(mercado_base)
    modo = modo if modo in MODOS_IDEIAS else "ambos"
    n = max(3, min(30, int(n or 10)))
    alvos = []
    for c in (mercados_alvo or []):
        cod = codigo_mercado(c, padrao="")
        if cod and cod not in alvos:
            alvos.append(cod)
    if not alvos:
        alvos = [codigo_mercado(mercado_base)]
    lista_mercados = "; ".join(f'{c} = {MERCADOS[c]["nome"]} ({MERCADOS[c]["idioma"]})' for c in alvos)

    if padroes:
        blocos = []
        for p in padroes:
            fixos = ", ".join(p.get("elementos_fixos") or []) or "-"
            vari = ", ".join(p.get("elementos_variaveis") or []) or "-"
            blocos.append(f'- {p.get("nome") or "padrão"}: emoção = {p.get("emocao") or "-"}; '
                          f'estrutura = {p.get("estrutura") or "-"}; fixo = {fixos}; variável = {vari}')
        secao = "Padrões que já funcionam (extraídos de vídeos em alta):\n" + "\n".join(blocos)
    else:
        secao = "Não há padrões extraídos: identifique você mesmo 2 ou 3 padrões emocionais que costumam funcionar nesse tema."

    return (
        "Você é um estrategista de conteúdo para YouTube.\n"
        f'Tema: "{tema}". Mercado de origem: {base["nome"]} ({base["idioma"]}).\n\n'
        f"{secao}\n\n"
        f"Gere {n} ideias de vídeo para: {MODOS_IDEIAS[modo]}.\n"
        f"Mercados permitidos (use o CÓDIGO no campo \"mercado\"): {lista_mercados}.\n\n"
        "Regras:\n"
        "- Mantenha a emoção e a estrutura do padrão e MUDE o personagem, o cenário e/ou o mercado. "
        "Não copie títulos existentes.\n"
        "- Cada ideia traz o mesmo título em 3 níveis de amplitude: micro (só quem é do nicho entende), "
        "sub (subnicho) e amplo (qualquer pessoa consegue clicar; prefira palavras amplas, "
        'ex.: "inseto" em vez de "mosquito").\n'
        '- Escreva os títulos no idioma do mercado escolhido para a ideia.\n'
        '- "tipo_brecha": "simples" (ângulo novo no mesmo mercado) ou "dupla" (ângulo novo + outro mercado).\n'
        '- "termos_validacao": 2 a 3 buscas curtas, no idioma do mercado, que uma pessoa digitaria no '
        "Google/YouTube sobre esse assunto.\n"
        '- "amplitude", "repetibilidade" (dá para fazer 30+ vídeos assim?) e "producao" (5 = fácil de produzir '
        "com qualidade e originalidade) são suas estimativas de 0 a 5.\n\n"
        "Responda ESTRITAMENTE em JSON válido, sem markdown, sem texto antes ou depois, exatamente neste formato:\n"
        '{"ideias": [{"titulo_micro": "", "titulo_sub": "", "titulo_amplo": "", "emocao": "", '
        '"estrutura": "", "personagem": "", "cenario": "", "mercado": "BR", "tipo_brecha": "simples", '
        '"padrao_origem": "", "termos_validacao": ["", ""], "amplitude": 0, "repetibilidade": 0, '
        '"producao": 0, "observacao": ""}]}'
    )


# --------------------------------------------------------------------------
# Validação do JSON colado
# --------------------------------------------------------------------------

def validar_decomposicao(texto, n_videos=None):
    dados = extrair_json(texto)
    if isinstance(dados, list):
        dados = {"videos": dados}
    d = _chaves(dados)
    brutos = d.get("videos") if isinstance(d.get("videos"), list) else []
    videos = []
    for i, item in enumerate(brutos, 1):
        v = _chaves(item)
        if not v:
            continue
        try:
            indice = int(v.get("indice") or i)
        except (TypeError, ValueError):
            indice = i
        if n_videos and not (1 <= indice <= n_videos):
            continue
        videos.append({
            "indice": indice,
            "emocao": _txt(v, "emocao", "emocao_principal"),
            "estrutura_titulo": _txt(v, "estrutura_titulo", "estrutura"),
            "personagem": _txt(v, "personagem"),
            "cenario": _txt(v, "cenario"),
            "promessa": _txt(v, "promessa"),
            "publico_obvio": _txt(v, "publico_obvio", "publico"),
            "publicos_adjacentes": _lista_txt(v.get("publicos_adjacentes")),
            "por_que_fora_do_nicho_clica": _txt(v, "por_que_fora_do_nicho_clica", "por_que_clica"),
            "amplitude": _nota(v.get("amplitude")),
        })
    padroes = []
    for item in (d.get("padroes") if isinstance(d.get("padroes"), list) else []):
        p = _chaves(item)
        if not p:
            continue
        nome = _txt(p, "nome", "padrao")
        emocao = _txt(p, "emocao")
        estrutura = _txt(p, "estrutura", "estrutura_titulo")
        if not (nome or emocao or estrutura):
            continue
        indices = []
        for x in (p.get("indices") if isinstance(p.get("indices"), list) else []):
            try:
                indices.append(int(x))
            except (TypeError, ValueError):
                pass
        padroes.append({
            "nome": nome or emocao or estrutura, "emocao": emocao, "estrutura": estrutura,
            "elementos_fixos": _lista_txt(p.get("elementos_fixos")),
            "elementos_variaveis": _lista_txt(p.get("elementos_variaveis")),
            "indices": indices,
        })
    if not videos and not padroes:
        raise ValueError("O JSON não tem 'videos' nem 'padroes' válidos.")
    return {"videos": videos, "padroes": padroes}


def validar_expansao(texto):
    d = _chaves(extrair_json(texto))
    publicos = []
    for item in (d.get("publicos_adjacentes") if isinstance(d.get("publicos_adjacentes"), list) else []):
        p = _chaves(item) if isinstance(item, dict) else {"publico": item}
        nome = _txt(p, "publico", "nome")
        if nome:
            publicos.append({"publico": nome, "por_que": _txt(p, "por_que", "motivo")})
    buscas = []
    for item in (d.get("problemas_e_buscas") if isinstance(d.get("problemas_e_buscas"), list) else []):
        b = _chaves(item) if isinstance(item, dict) else {"busca": item}
        termo = _txt(b, "busca", "termo", "problema")
        if termo:
            buscas.append({"busca": termo, "intencao": _txt(b, "intencao"), "motivo": _txt(b, "motivo", "por_que")})
    termos = _lista_txt(d.get("termos_para_validar"), limite=40)
    for b in buscas:
        if b["busca"] not in termos:
            termos.append(b["busca"])
    if not termos:
        raise ValueError("O JSON não tem 'problemas_e_buscas' nem 'termos_para_validar'.")
    return {"publicos_adjacentes": publicos, "problemas_e_buscas": buscas,
            "termos_para_validar": termos[:40], "sinonimos": _lista_txt(d.get("sinonimos"), limite=30)}


def _novo_id():
    return uuid.uuid4().hex[:8]


def validar_ideias(texto, mercado_padrao=MERCADO_PADRAO):
    dados = extrair_json(texto)
    if isinstance(dados, list):
        dados = {"ideias": dados}
    d = _chaves(dados)
    brutas = d.get("ideias") if isinstance(d.get("ideias"), list) else []
    ideias = []
    for item in brutas:
        i = _chaves(item)
        micro, sub, amplo = _txt(i, "titulo_micro"), _txt(i, "titulo_sub"), _txt(i, "titulo_amplo")
        if not (micro or sub or amplo):
            continue
        amplo = amplo or sub or micro
        tipo = biblioteca.normalizar(_txt(i, "tipo_brecha"))
        ideias.append({
            "id": _novo_id(),
            "titulo_micro": micro, "titulo_sub": sub, "titulo_amplo": amplo,
            "emocao": _txt(i, "emocao"), "estrutura": _txt(i, "estrutura"),
            "personagem": _txt(i, "personagem"), "cenario": _txt(i, "cenario"),
            "mercado": codigo_mercado(_txt(i, "mercado", "mercado_codigo"), padrao=codigo_mercado(mercado_padrao)),
            "tipo_brecha": "dupla" if tipo.startswith("dupla") else "simples",
            "padrao_origem": _txt(i, "padrao_origem", "padrao"),
            "termos_validacao": _lista_txt(i.get("termos_validacao"), limite=5),
            "amplitude": _nota(i.get("amplitude")),
            "repetibilidade": _nota(i.get("repetibilidade")),
            "producao": _nota(i.get("producao")),
            "observacao": _txt(i, "observacao"),
            "descartada": False, "favorita": False,
            "sinais": {}, "criterios": {}, "score": None, "confianca": 0.0,
        })
    if not ideias:
        raise ValueError("O JSON não tem uma lista 'ideias' com pelo menos um título.")
    return ideias


def mesclar_ideias(existentes, novas):
    """Acrescenta ideias novas sem duplicar (compara o título amplo, sem acento/caixa)."""
    vistos = {biblioteca.normalizar(i.get("titulo_amplo")) for i in existentes}
    saida = list(existentes)
    adicionadas = 0
    for i in novas:
        k = biblioteca.normalizar(i.get("titulo_amplo"))
        if k in vistos:
            continue
        vistos.add(k)
        saida.append(i)
        adicionadas += 1
    return saida, adicionadas


# --------------------------------------------------------------------------
# Autocomplete (parser das respostas do endpoint de sugestões)
# --------------------------------------------------------------------------

def parse_sugestoes(texto):
    """Lê a resposta do endpoint de sugestões (JSON puro ou embrulhada em JSONP)."""
    t = (texto or "").strip()
    if not t:
        return []
    m = re.match(r"^[\w.$]+\(\s*(.*)\)\s*;?\s*$", t, re.S)
    if m:
        t = m.group(1)
    try:
        dados = json.loads(t)
    except ValueError:
        return []
    if not isinstance(dados, list) or len(dados) < 2 or not isinstance(dados[1], list):
        return []
    saida = []
    for item in dados[1]:
        s = item[0] if isinstance(item, list) and item else item
        s = str(s).strip() if isinstance(s, str) else ""
        if s and s not in saida:
            saida.append(s)
    return saida


# --------------------------------------------------------------------------
# Google Trends
# --------------------------------------------------------------------------

def url_trends(termos, geo="", periodo="today 12-m", gprop=""):
    q = ",".join(quote(t) for t in termos[:5])
    url = f"https://trends.google.com/trends/explore?q={q}&date={quote(periodo)}"
    if geo:
        url += f"&geo={quote(geo)}"
    if gprop:
        url += f"&gprop={quote(gprop)}"
    return url


def classificar_serie(valores):
    """Classifica uma série do Trends: tendência (subindo/estável/caindo) e perfil
    (evergreen/sazonal/irregular). Séries curtas ficam 'indefinida'."""
    v = [float(x) for x in (valores or []) if x is not None]
    if not v:
        return {"media": 0.0, "tendencia": "indefinida", "perfil": "indefinido"}
    media = sum(v) / len(v)
    if len(v) < 8:
        return {"media": round(media, 1), "tendencia": "indefinida", "perfil": "indefinido"}
    terco = max(1, len(v) // 3)
    ini, fim = sum(v[:terco]) / terco, sum(v[-terco:]) / terco
    if ini < 1:
        tendencia = "subindo" if fim >= 5 else "estavel"
    elif fim / ini >= 1.25:
        tendencia = "subindo"
    elif fim / ini <= 0.8:
        tendencia = "caindo"
    else:
        tendencia = "estavel"
    total = sum(v)
    topo = sum(sorted(v, reverse=True)[:4])
    cv = (statistics.pstdev(v) / media) if media > 0 else 0
    if total > 0 and len(v) >= 26 and topo / total >= 0.30:
        perfil = "sazonal"
    elif cv < 0.4:
        perfil = "evergreen"
    else:
        perfil = "irregular"
    return {"media": round(media, 1), "tendencia": tendencia, "perfil": perfil}


def _reduzir(serie, maximo=60):
    if len(serie) <= maximo:
        return [round(x, 1) for x in serie]
    passo = len(serie) / maximo
    return [round(serie[int(i * passo)], 1) for i in range(maximo)]


def coletar_trends(termos, geo="", periodo="today 12-m", gprop="", fabrica=None, pausa=1.2, log=print):
    """Interesse relativo no Google Trends via ``pytrends`` (opcional, sem chave).

    O Trends só compara termos dentro de uma mesma consulta (até 5). Para os
    termos ficarem comparáveis entre lotes, o primeiro termo entra em todos os
    lotes como âncora e cada lote é reescalado pela média da âncora.

    Retorna ``{"disponivel", "motivo", "termos": {termo: {nivel, media, tendencia, perfil, serie}}}``.
    ``nivel`` está em unidades da âncora (âncora = 100).
    """
    termos = [t for t in dict.fromkeys(str(x).strip() for x in termos) if t]
    vazio = {"disponivel": False, "motivo": "", "termos": {}}
    if not termos:
        return {**vazio, "motivo": "sem termos"}
    if fabrica is None:
        try:
            from pytrends.request import TrendReq
        except ImportError:
            return {**vazio, "motivo": "pytrends não instalado (pip install pytrends)"}

        def fabrica():
            return TrendReq(hl="pt-BR", tz=180)

    ancora = termos[0]
    restantes = termos[1:]
    lotes = [[ancora] + restantes[i:i + 4] for i in range(0, len(restantes), 4)] or [[ancora]]
    saida, media_ancora_ref = {}, None
    try:
        cliente = fabrica()
        for n, lote in enumerate(lotes):
            cliente.build_payload(lote, timeframe=periodo, geo=geo, gprop=gprop)
            df = cliente.interest_over_time()
            if df is None or getattr(df, "empty", True):
                log(f"  Trends: sem dados para {lote}")
                continue
            series = {t: [float(x) for x in df[t].tolist()] for t in lote if t in df.columns}
            media_anc = (sum(series[ancora]) / len(series[ancora])) if series.get(ancora) else 0
            if media_ancora_ref is None and media_anc > 0:
                media_ancora_ref = media_anc
            escala = (media_ancora_ref / media_anc) if (media_anc > 0 and media_ancora_ref) else 1.0
            for t, serie in series.items():
                if t in saida:
                    continue
                info = classificar_serie(serie)
                saida[t] = {"nivel": round(info["media"] * escala, 1), "media": info["media"],
                            "tendencia": info["tendencia"], "perfil": info["perfil"],
                            "serie": _reduzir(serie)}
            if n < len(lotes) - 1:
                time.sleep(pausa)
    except Exception as exc:  # 429, rede, formato novo...
        return {"disponivel": bool(saida), "motivo": f"{type(exc).__name__}: {exc}", "termos": saida}
    return {"disponivel": bool(saida), "motivo": "" if saida else "sem dados", "termos": saida}


# --------------------------------------------------------------------------
# Concorrência (métricas sobre os resultados do YouTube)
# --------------------------------------------------------------------------

def metricas_concorrencia(videos):
    vs = [v for v in (videos or []) if v.get("views_num") is not None]
    n = len(vs)
    canais = Counter((v.get("canal_url") or v.get("canal") or "") for v in vs if (v.get("canal_url") or v.get("canal")))
    views = [v["views_num"] for v in vs]
    vd = [v["views_dia"] for v in vs if v.get("views_dia") is not None]
    return {
        "n_videos": n,
        "n_canais": len(canais),
        "concentracao_top3": round(sum(c for _, c in canais.most_common(3)) / n, 3) if n and canais else None,
        "mediana_views": int(statistics.median(views)) if views else None,
        "mediana_views_dia": round(statistics.median(vd), 1) if vd else None,
        "maior_views": max(views) if views else None,
        "insuficiente": n < 8,
    }


def resumo_radar(videos):
    """Resumo por termo: quantos vídeos, mediana de views e quantos são outliers."""
    por_termo = {}
    for v in videos or []:
        por_termo.setdefault(v.get("termo_busca") or "?", []).append(v)
    saida = []
    for termo, lista in por_termo.items():
        views = [x["views_num"] for x in lista if x.get("views_num") is not None]
        saida.append({
            "termo": termo, "n_videos": len(lista),
            "mediana_views": int(statistics.median(views)) if views else None,
            "outliers": sum(1 for x in lista if (x.get("razao_views_inscritos") or 0) >= 1),
        })
    return saida


def selecionar_para_ia(videos, n=20):
    """Vídeos mais promissores para a IA: maior razão views/inscritos, depois views/dia."""
    def chave(v):
        return (v.get("razao_views_inscritos") or 0, v.get("views_dia") or 0, v.get("views_num") or 0)
    return sorted(videos or [], key=chave, reverse=True)[:n]


# --------------------------------------------------------------------------
# Sinais, critérios e pontuação
# --------------------------------------------------------------------------

CRITERIOS = ("amplitude", "demanda", "concorrencia", "repetibilidade", "producao")
PESOS_PADRAO = {"amplitude": 25, "demanda": 30, "concorrencia": 20, "repetibilidade": 15, "producao": 10}


def chave_validacao(termo, mercado_cod):
    return f"{biblioteca.normalizar(termo)}|{codigo_mercado(mercado_cod)}"


def normalizar_pesos(pesos):
    saida = {}
    for c in CRITERIOS:
        try:
            v = float((pesos or {}).get(c, PESOS_PADRAO[c]))
        except (TypeError, ValueError):
            v = PESOS_PADRAO[c]
        saida[c] = max(0.0, v)
    return saida if sum(saida.values()) > 0 else dict(PESOS_PADRAO)


def _media(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def sinais_da_ideia(ideia, validacao):
    regs = [validacao[k] for k in (chave_validacao(t, ideia.get("mercado")) for t in ideia.get("termos_validacao") or [])
            if k in validacao]
    if not regs:
        return {}
    sinais = {
        "termos_validados": len(regs),
        "sugestoes_google": _media([len(r["sugestoes_google"]) for r in regs if r.get("sugestoes_google") is not None]),
        "sugestoes_youtube": _media([len(r["sugestoes_youtube"]) for r in regs if r.get("sugestoes_youtube") is not None]),
    }
    serp = [r for r in regs if r.get("serp_status") == "ok"]
    sinais["serp_perguntas"] = sum(len(r.get("paa") or []) for r in serp) if serp else None
    sinais["serp_relacionadas"] = sum(len(r.get("relacionadas") or []) for r in serp) if serp else None
    com_trends = [r for r in regs if isinstance(r.get("trends"), dict) and r["trends"].get("nivel") is not None]
    if com_trends:
        melhor = max(com_trends, key=lambda r: r["trends"]["nivel"])
        sinais.update({"trends_nivel": melhor["trends"]["nivel"], "trends_tendencia": melhor["trends"].get("tendencia"),
                       "trends_perfil": melhor["trends"].get("perfil"), "trends_termo": melhor.get("termo")})
    yt = [r["yt"] for r in regs if isinstance(r.get("yt"), dict) and r["yt"].get("n_videos")]
    if yt:
        sinais["yt_n_videos"] = sum(y["n_videos"] for y in yt)
        sinais["yt_mediana_views_dia"] = _media([y.get("mediana_views_dia") for y in yt])
        suficientes = [y for y in yt if not y.get("insuficiente")]
        sinais["yt_concentracao_top3"] = _media([y.get("concentracao_top3") for y in suficientes]) if suficientes else None
    def unicos(chave):
        vistos = []
        for r in regs:
            for x in (r.get(chave) or []):
                if x not in vistos:
                    vistos.append(x)
        return vistos

    # exemplos para exibir: perguntas reais viram ganchos de vídeo
    sinais["perguntas_exemplo"] = unicos("paa")[:6] or None
    sinais["relacionadas_exemplo"] = unicos("relacionadas")[:6] or None
    sinais["sugestoes_exemplo"] = unicos("sugestoes_google")[:8] or None
    sinais["trends_url"] = next((r.get("trends_url") for r in regs if r.get("trends_url")), None)
    return {k: v for k, v in sinais.items() if v is not None}


def _maximos(ideias):
    """Maiores valores de Trends/views por dia, POR MERCADO: esses números só são
    comparáveis dentro do mesmo país (o Trends é relativo e os públicos diferem)."""
    saida = {}
    for i in ideias:
        if i.get("descartada") or not i.get("sinais"):
            continue
        m = saida.setdefault(codigo_mercado(i.get("mercado")), {"trends_nivel": 0, "yt_mediana_views_dia": 0})
        for k in m:
            v = i["sinais"].get(k)
            if v and v > m[k]:
                m[k] = v
    return saida


def criterios_da_ideia(ideia, maximos):
    """Critérios 0-5. Os que não têm dado ficam None (não viram zero)."""
    s = ideia.get("sinais") or {}
    partes = []
    sug = _media([s.get("sugestoes_google"), s.get("sugestoes_youtube")])
    if sug is not None:
        partes.append(min(5.0, sug / 2))
    if s.get("trends_nivel") is not None and maximos.get("trends_nivel"):
        p = 5.0 * s["trends_nivel"] / maximos["trends_nivel"]
        p += 0.5 if s.get("trends_tendencia") == "subindo" else (-0.5 if s.get("trends_tendencia") == "caindo" else 0)
        partes.append(min(5.0, max(0.0, p)))
    if s.get("yt_mediana_views_dia") is not None and maximos.get("yt_mediana_views_dia"):
        partes.append(min(5.0, 5.0 * s["yt_mediana_views_dia"] / maximos["yt_mediana_views_dia"]))
    conc = s.get("yt_concentracao_top3")
    return {
        "amplitude": ideia.get("amplitude"),
        "demanda": round(sum(partes) / len(partes), 2) if partes else None,
        "concorrencia": round(5.0 * (1 - conc), 2) if conc is not None else None,
        "repetibilidade": ideia.get("repetibilidade"),
        "producao": ideia.get("producao"),
    }


def pontuar(criterios, pesos):
    """Score 0-100 sobre os critérios disponíveis + confiança (fração do peso com dado)."""
    pesos = normalizar_pesos(pesos)
    total = sum(pesos.values())
    usados = {c: pesos[c] for c in CRITERIOS if criterios.get(c) is not None and pesos[c] > 0}
    if not usados:
        return None, 0.0
    soma = sum(pesos_c * (criterios[c] / 5.0) for c, pesos_c in usados.items())
    return round(100.0 * soma / sum(usados.values()), 1), round(sum(usados.values()) / total, 2)


def recalcular_estado(estado):
    """Atualiza sinais, critérios, score e ranking de todas as ideias do estado."""
    ideias = estado.get("ideias") or []
    validacao = estado.get("validacao") or {}
    for i in ideias:
        i["sinais"] = sinais_da_ideia(i, validacao)
    mx = _maximos(ideias)
    for i in ideias:
        i["criterios"] = criterios_da_ideia(i, mx.get(codigo_mercado(i.get("mercado")), {}))
        i["score"], i["confianca"] = pontuar(i["criterios"], estado.get("pesos"))
    ativas = sorted((i for i in ideias if not i.get("descartada")),
                    key=lambda i: (i["score"] is not None, i["score"] or 0, i["confianca"]), reverse=True)
    for pos, i in enumerate(ativas, 1):
        i["rank"] = pos
    for i in ideias:
        if i.get("descartada"):
            i["rank"] = None
    return estado


# --------------------------------------------------------------------------
# Decisão de canal (regra dos 15-20 / 30 vídeos)
# --------------------------------------------------------------------------

LIMIARES_PADRAO = {"corte_alerta": 15, "corte_final": 30,
                   "impressoes_baixas": 500, "ctr_baixo": 3.0, "retencao_baixa": 30.0}


def _num_ou_none(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def decidir_canal(n_videos, impressoes=None, ctr=None, retencao=None, limiares=None):
    """Sugere continuar, revisar, escalar ou descartar um canal.

    A regra dos 15-20 vídeos (alerta) e 30 vídeos (corte) vem dos vídeos de
    referência; os limiares de impressão/CTR/retenção são padrões ajustáveis.
    """
    L = dict(LIMIARES_PADRAO)
    for k, v in (limiares or {}).items():
        f = _num_ou_none(v)
        if k in L and f is not None and f >= 0:
            L[k] = f
    n = int(_num_ou_none(n_videos) or 0)
    imp, c, ret = _num_ou_none(impressoes), _num_ou_none(ctr), _num_ou_none(retencao)

    diag = []
    if imp is not None and imp < L["impressoes_baixas"]:
        diag.append({"causa": "Impressão quase zero",
                     "acao": "Suspeite da conta (pouca confiança do YouTube) ou de erro na pesquisa: revise demanda e ângulo antes de mexer em título."})
    elif imp is not None and c is not None and c < L["ctr_baixo"]:
        diag.append({"causa": "O YouTube mostra, mas quase ninguém clica",
                     "acao": "Problema de embalagem: torne o título mais amplo e revise a capa."})
    if imp is not None and c is not None and imp >= L["impressoes_baixas"] and c >= L["ctr_baixo"] \
            and ret is not None and ret < L["retencao_baixa"]:
        diag.append({"causa": "Clicam, mas saem cedo",
                     "acao": "Revise gancho, roteiro e ritmo de edição."})

    tracao = None
    if imp is not None and c is not None:
        tracao = imp >= L["impressoes_baixas"] and c >= L["ctr_baixo"] and (ret is None or ret >= L["retencao_baixa"])

    if tracao:
        veredito, titulo = "escalar", "Sinal de tração: escale"
        texto = ("Impressões, CTR e retenção estão acima dos limiares. Escale com outros idiomas, "
                 "outros ângulos ou novos canais, sem abandonar o critério.")
    elif n >= L["corte_final"]:
        veredito, titulo = "descartar", f"Descarte (já são {n} vídeos)"
        texto = "Com 30 vídeos ou mais e sem tração, a regra é seguir para o próximo canal em vez de insistir."
    elif n >= L["corte_alerta"]:
        veredito, titulo = "alerta", f"Alerta ({n} vídeos): revise antes do corte"
        texto = f"Faixa de alerta. Corrija o que o diagnóstico apontar; o corte definitivo é aos {int(L['corte_final'])} vídeos."
    else:
        veredito, titulo = "continuar", f"Cedo demais para decidir ({n} vídeos)"
        texto = f"Com menos de {int(L['corte_alerta'])} vídeos ainda não dá para matar o canal. Continue publicando e otimizando."
    if tracao is None:
        texto += " Informe impressões e CTR para receber um diagnóstico."
    return {"veredito": veredito, "titulo": titulo, "explicacao": texto, "diagnosticos": diag,
            "tracao": tracao, "limiares": L}


# --------------------------------------------------------------------------
# Persistência (SQLite, mesmo arquivo da biblioteca)
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS pesquisas_ideias (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tema          TEXT NOT NULL,
    tema_norm     TEXT NOT NULL,
    criado_em     TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    estado_json   TEXT NOT NULL
);
"""

_LOCK = threading.RLock()

CHAVES_CLIENTE = ("tema", "mercado", "termos", "refs_extra", "pesos", "radar_selecao", "config")


def _conectar(db_path=None):
    caminho = biblioteca.caminho_banco(db_path)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(caminho), timeout=15)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _agora():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def estado_inicial(tema, mercado_cod=MERCADO_PADRAO, termos=None):
    return {
        "tema": tema, "mercado": codigo_mercado(mercado_cod),
        "termos": _lista_txt(termos, limite=60), "refs_extra": [],
        "pesos": dict(PESOS_PADRAO), "config": {},
        "radar": None, "radar_selecao": None,
        "decomposicao": None, "expansao": None,
        "ideias": [], "validacao": {},
    }


def _limpar_termos(termos):
    if isinstance(termos, str):
        termos = termos.splitlines()
    return _lista_txt(termos, limite=60)


def criar_pesquisa(tema, mercado_cod=MERCADO_PADRAO, termos=None, db_path=None):
    tema = (tema or "").strip()
    if not tema:
        raise ValueError("Informe o tema da pesquisa.")
    estado = estado_inicial(tema, mercado_cod, _limpar_termos(termos))
    with _LOCK, closing(_conectar(db_path)) as con, con:
        cur = con.execute(
            "INSERT INTO pesquisas_ideias (tema, tema_norm, criado_em, atualizado_em, estado_json) VALUES (?,?,?,?,?)",
            (tema, biblioteca.normalizar(tema), _agora(), _agora(), json.dumps(estado, ensure_ascii=False)))
        return cur.lastrowid


def _linha_para_estado(r):
    estado = json.loads(r["estado_json"])
    estado.update({"id": r["id"], "criado_em": r["criado_em"], "atualizado_em": r["atualizado_em"]})
    return estado


def obter_pesquisa(pid, db_path=None):
    with closing(_conectar(db_path)) as con:
        r = con.execute("SELECT * FROM pesquisas_ideias WHERE id = ?", (int(pid),)).fetchone()
    return _linha_para_estado(r) if r else None


def listar_pesquisas(db_path=None):
    with closing(_conectar(db_path)) as con:
        linhas = con.execute("SELECT * FROM pesquisas_ideias ORDER BY atualizado_em DESC, id DESC").fetchall()
    saida = []
    for r in linhas:
        e = json.loads(r["estado_json"])
        saida.append({"id": r["id"], "tema": r["tema"], "criado_em": r["criado_em"], "atualizado_em": r["atualizado_em"],
                      "mercado": e.get("mercado"), "n_ideias": len(e.get("ideias") or []),
                      "n_videos": len((e.get("radar") or {}).get("videos") or [])})
    return saida


def mutar_pesquisa(pid, fn, db_path=None):
    """Lê o estado, aplica ``fn(estado)`` e grava — tudo sob lock (jobs e API podem escrever juntos)."""
    with _LOCK, closing(_conectar(db_path)) as con, con:
        r = con.execute("SELECT * FROM pesquisas_ideias WHERE id = ?", (int(pid),)).fetchone()
        if not r:
            raise KeyError(pid)
        estado = json.loads(r["estado_json"])
        resultado = fn(estado)
        estado = resultado if isinstance(resultado, dict) else estado
        tema = (estado.get("tema") or r["tema"]).strip() or r["tema"]
        con.execute("UPDATE pesquisas_ideias SET tema=?, tema_norm=?, atualizado_em=?, estado_json=? WHERE id=?",
                    (tema, biblioteca.normalizar(tema), _agora(), json.dumps(estado, ensure_ascii=False, default=str), int(pid)))
    estado.update({"id": int(pid)})
    return estado


def atualizar_config(pid, dados, db_path=None):
    """Mescla apenas as chaves que o navegador pode editar (nunca radar/validação)."""
    dados = dados or {}

    def aplicar(e):
        if "tema" in dados and str(dados["tema"]).strip():
            e["tema"] = str(dados["tema"]).strip()
        if "mercado" in dados:
            e["mercado"] = codigo_mercado(dados["mercado"], padrao=e.get("mercado") or MERCADO_PADRAO)
        if "termos" in dados:
            e["termos"] = _limpar_termos(dados["termos"])
        if "refs_extra" in dados:
            e["refs_extra"] = _limpar_termos(dados["refs_extra"])
        if "pesos" in dados:
            e["pesos"] = normalizar_pesos(dados["pesos"])
        if "radar_selecao" in dados:
            sel = dados["radar_selecao"]
            e["radar_selecao"] = [str(x) for x in sel] if isinstance(sel, list) else None
        if "config" in dados and isinstance(dados["config"], dict):
            e["config"] = {**(e.get("config") or {}), **dados["config"]}
        return recalcular_estado(e)

    return mutar_pesquisa(pid, aplicar, db_path)


CAMPOS_IDEIA_EDITAVEIS = ("amplitude", "repetibilidade", "producao", "descartada", "favorita", "termos_validacao", "observacao")


def atualizar_ideia(pid, ideia_id, dados, db_path=None):
    dados = dados or {}
    achou = {"ok": False}

    def aplicar(e):
        for i in e.get("ideias") or []:
            if i.get("id") != ideia_id:
                continue
            achou["ok"] = True
            for k in ("amplitude", "repetibilidade", "producao"):
                if k in dados:
                    i[k] = _nota(dados[k])
            for k in ("descartada", "favorita"):
                if k in dados:
                    i[k] = bool(dados[k])
            if "termos_validacao" in dados:
                i["termos_validacao"] = _limpar_termos(dados["termos_validacao"])[:5]
            if "observacao" in dados:
                i["observacao"] = str(dados["observacao"] or "").strip()
        return recalcular_estado(e)

    estado = mutar_pesquisa(pid, aplicar, db_path)
    return estado if achou["ok"] else None


def excluir_pesquisa(pid, db_path=None):
    with _LOCK, closing(_conectar(db_path)) as con, con:
        return con.execute("DELETE FROM pesquisas_ideias WHERE id = ?", (int(pid),)).rowcount > 0


CSV_COLUNAS = ["rank", "score", "confianca", "titulo_amplo", "titulo_sub", "titulo_micro", "mercado", "tipo_brecha",
               "emocao", "estrutura", "personagem", "cenario", "padrao_origem", "termos_validacao",
               "amplitude", "demanda", "concorrencia", "repetibilidade", "producao",
               "sugestoes_google", "sugestoes_youtube", "trends_nivel", "trends_tendencia", "trends_perfil",
               "yt_mediana_views_dia", "yt_concentracao_top3", "serp_perguntas", "favorita", "descartada", "observacao"]


def exportar_csv(pid, db_path=None):
    estado = obter_pesquisa(pid, db_path)
    if estado is None:
        return None
    saida = io.StringIO()
    w = csv.DictWriter(saida, fieldnames=CSV_COLUNAS, extrasaction="ignore")
    w.writeheader()
    ideias = sorted(estado.get("ideias") or [], key=lambda i: (i.get("rank") is None, i.get("rank") or 0))
    for i in ideias:
        linha = {**i, **(i.get("criterios") or {}), **(i.get("sinais") or {})}
        linha["termos_validacao"] = " | ".join(i.get("termos_validacao") or [])
        linha["amplitude"] = (i.get("criterios") or {}).get("amplitude", i.get("amplitude"))
        w.writerow({k: ("" if linha.get(k) is None else linha.get(k)) for k in CSV_COLUNAS})
    return saida.getvalue()
