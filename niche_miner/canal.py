#!/usr/bin/env python3
"""
Analisador de canal (aba "Analisar canal"): o que dá para fazer, de graça e no seu computador, com as
ferramentas que o NextLEV mostra no vídeo de referência.

Tudo que é número vem dos dados que o app já lê do YouTube (aba Sobre + os últimos vídeos do canal). A IA só
entra onde o NextLEV também usa IA (categorias, estratégia, comentários) e segue o padrão do app: o app monta o
prompt, você roda em qualquer IA de chat e cola o JSON de volta. Nas categorias a IA apenas AGRUPA os vídeos;
contagens e médias de views são calculadas aqui, então o número não é palpite.

Não replicado de propósito: o "% de saturação" do NextLEV (score opaco; use a contagem real do Método) e o WPM.
"""

import json
import re
import sqlite3
import statistics
import threading
from datetime import date, datetime

import biblioteca
import ideias
import yt_scraper as core

IDADE_MIN_PIORES = 14          # vídeo com menos de 14 dias ainda não "amadureceu": não entra em "piores" nem nos padrões
MIN_N_PADRAO = 3               # ocorrências mínimas (com e sem o padrão) para mostrar um padrão de título
TIPOS_IA = ("categorias", "estrategia", "comentarios")
LIMITE_VIDEOS_PROMPT = 100
MAX_COMENTARIOS = 200
MAX_CHARS_COMENTARIOS = 14000
MIN_COMENTARIOS = 5


# --------------------------------------------------------------------------
# Link do canal
# --------------------------------------------------------------------------

def normalizar_url_canal(texto):
    """Aceita @nome, youtube.com/@nome, /channel/UC..., /c/nome e /user/nome (com ou sem /videos, /about...).
    Devolve a URL canônica do canal. Levanta ``ValueError`` com mensagem em português."""
    t = str(texto or "").strip()
    if not t:
        raise ValueError("Informe o link do canal.")
    if re.fullmatch(r"@[^\s/?#]+", t):
        return f"https://www.youtube.com/{t}"
    if not re.match(r"^https?://", t, re.I):
        t = "https://" + t.lstrip("/")
    m = re.match(r"^https?://(?:www\.|m\.)?youtube\.com(/[^?#\s]*)?", t, re.I)
    if not m:
        raise ValueError("Isso não parece um link do YouTube. Use youtube.com/@nome do canal.")
    caminho = (m.group(1) or "").rstrip("/")
    if re.match(r"^/(watch|shorts|live|playlist|results|feed)\b", caminho):
        raise ValueError("Esse é o link de um vídeo ou de uma página do YouTube. Cole o link do CANAL (youtube.com/@nome).")
    for padrao in (r"^(/@[^/]+)", r"^(/channel/[A-Za-z0-9_-]{10,})", r"^(/c/[^/]+)", r"^(/user/[^/]+)"):
        achou = re.match(padrao, caminho)
        if achou:
            return "https://www.youtube.com" + achou.group(1)
    raise ValueError("Não encontrei o canal nesse link. Use youtube.com/@nome ou youtube.com/channel/...")


# --------------------------------------------------------------------------
# Números e vídeos
# --------------------------------------------------------------------------

def _num(v):
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n == n and n not in (float("inf"), float("-inf")) else None


def _mediana(valores):
    v = [x for x in (_num(i) for i in valores or []) if x is not None]
    return statistics.median(v) if v else None


def _media(valores):
    v = [x for x in (_num(i) for i in valores or []) if x is not None]
    return sum(v) / len(v) if v else None


def _dia(iso):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _hoje(agora):
    return (agora or datetime.now()).date()


def videos_da_amostra(canal, agora=None):
    """Vídeos lidos do canal, com idade, views por dia e duração em segundos. ``indice`` (1, 2, 3...) é a posição
    na amostra e é o número que os prompts usam."""
    hoje = _hoje(agora)
    saida = []
    for i, v in enumerate((canal or {}).get("amostra_videos") or [], 1):
        if not isinstance(v, dict):
            continue
        views = _num(v.get("views_num"))
        d = _dia(v.get("data"))
        idade = max(0, (hoje - d).days) if d else None
        saida.append({
            "indice": i, "video_id": v.get("video_id", ""), "titulo": str(v.get("titulo") or "").strip(),
            "url": v.get("url", ""), "views": int(views) if views is not None else None, "data": d.isoformat() if d else "",
            "idade_dias": idade, "views_dia": round(views / max(idade, 1), 1) if views is not None and idade is not None else None,
            "quando": v.get("quando", ""), "duracao": v.get("duracao", ""), "duracao_seg": core.parse_duration_seconds(v.get("duracao", "")),
        })
    return saida


def _ultimos_n(videos, n):
    """Os n mais recentes com views. Só ordena por data se TODOS têm data; senão mantém a ordem da coleta."""
    lista = [v for v in videos if v["views"] is not None]
    if lista and all(v["data"] for v in lista):
        lista = sorted(lista, key=lambda v: v["data"], reverse=True)
    return lista[:max(1, n)]


def _resumo_video(v):
    return {"indice": v["indice"], "titulo": v["titulo"], "url": v["url"], "views": v["views"], "data": v["data"],
            "idade_dias": v["idade_dias"], "views_dia": v["views_dia"]}


def metricas_canal(canal, agora=None, n_mediana=10):
    """Painel do canal (equivalente ao "Analisar" do NextLEV). Campo sem dado fica ``None`` — nunca 0."""
    c = canal or {}
    hoje = _hoje(agora)
    vids = videos_da_amostra(c, agora)
    com_views = [v for v in vids if v["views"] is not None]
    criado = _dia(c.get("data_criacao_canal"))
    dias_vida = max(0, (hoje - criado).days) if criado else None
    meses = dias_vida / 30.4375 if dias_vida is not None else None
    insc, n_vid, tot = _num(c.get("inscritos_num")), _num(c.get("n_videos")), _num(c.get("views_totais"))

    ult = _ultimos_n(vids, n_mediana)
    med_ult = _mediana([v["views"] for v in ult])
    duracoes = [v["duracao_seg"] for v in vids if v["duracao_seg"] is not None]
    titulos = [v["titulo"] for v in vids if v["titulo"]]
    maduros = [v for v in com_views if v["idade_dias"] is None or v["idade_dias"] >= IDADE_MIN_PIORES]

    return {
        "inscritos": int(insc) if insc is not None else None, "n_videos": int(n_vid) if n_vid is not None else None,
        "views_totais": int(tot) if tot is not None else None, "criado_em": criado.isoformat() if criado else "",
        "dias_de_vida": dias_vida, "meses_de_vida": round(meses, 1) if meses is not None else None,
        "views_por_video": round(tot / n_vid) if tot is not None and n_vid else None,
        "views_mensais_medias": round(tot / meses) if tot is not None and meses and meses >= 1 else None,
        "uploads_por_mes_vida": round(n_vid / meses, 1) if n_vid is not None and meses and meses >= 1 else None,
        "videos_ultimos_30d": c.get("videos_ultimos_30d"), "frequencia_label": c.get("frequencia_label", ""),
        "amostra_n": len(vids), "amostra_com_views": len(com_views), "amostra_completa": bool(c.get("amostra_completa")),
        "mediana_views_amostra": _mediana([v["views"] for v in com_views]), "media_views_amostra": _media([v["views"] for v in com_views]),
        "n_mediana_usados": len(ult), "mediana_ultimos": med_ult,
        "tracao": round(med_ult / insc, 4) if med_ult is not None and insc else None,
        "duracao_media_seg": round(_media(duracoes)) if duracoes else None, "duracao_mediana_seg": round(_mediana(duracoes)) if duracoes else None,
        "n_duracao": len(duracoes), "titulo_medio_chars": round(_media([len(t) for t in titulos]), 1) if titulos else None,
        "melhores": [_resumo_video(v) for v in sorted(com_views, key=lambda v: -v["views"])[:5]],
        "piores": [_resumo_video(v) for v in sorted(maduros, key=lambda v: v["views"])[:5]],
        "idade_min_piores_dias": IDADE_MIN_PIORES,
        # o YouTube não mostra isso de forma confiável na página; o NextLEV usa dados próprios
        "monetizado": None, "shorts": None,
        "pais": c.get("pais_canal", ""), "idioma": c.get("idioma_canal", ""),
    }


# --------------------------------------------------------------------------
# Padrões de título (100% dados, sem IA)
# --------------------------------------------------------------------------

_DETECTORES = [
    ("como", 'Começa com "Como" / "How"', lambda t: bool(re.match(r"^\W*(como|how)\b", t, re.I))),
    ("numero_inicio", "Começa com número (ex.: 12 lições...)", lambda t: bool(re.match(r"^\W*\d", t))),
    ("tem_numero", "Tem número no título", lambda t: bool(re.search(r"\d", t))),
    ("pergunta", "É uma pergunta", lambda t: "?" in t or bool(re.match(r"^\W*(por ?que|porqu[eê]|o que|quem|qual|quais|quando|why|what|who|which|when)\b", t, re.I))),
    ("comando", "Começa com comando ou negação (Pare, Nunca, Não...)", lambda t: bool(re.match(r"^\W*(pare|nunca|n[aã]o|stop|never|don'?t|do not)\b", t, re.I))),
    ("longo", "Título longo (60+ caracteres)", lambda t: len(t) >= 60),
    ("curto", "Título curto (até 40 caracteres)", lambda t: len(t) <= 40),
    ("maiuscula", "Tem palavra em MAIÚSCULAS", lambda t: bool(re.search(r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{4,}\b", t))),
    ("primeira_pessoa", "Fala em primeira pessoa (eu, meu, I, my)", lambda t: bool(re.search(r"\b(eu|meu|minha|meus|minhas|comigo|i|my|me)\b", t, re.I))),
]

_STOP = set("""para como mais sobre você voce porque quando onde essa esse esta este isso isto aqui muito todos todas cada tudo nada mesmo
seus suas dele dela depois antes ainda sempre nunca apenas entre desde também tambem será sera fazer ficar quem qual quais
that this with from your have what when were will just about into their they them then than been more most some does only every
never always after before there these those would could should because while where which""".split())


def palavras_chave(titulos, top=8, min_titulos=3):
    """Palavras que mais aparecem nos títulos (quantidade de títulos que as contêm)."""
    cont = {}
    for t in titulos or []:
        for p in set(re.findall(r"[^\W\d_]{4,}", str(t).lower())):
            if p not in _STOP:
                cont[p] = cont.get(p, 0) + 1
    ordem = sorted(((p, n) for p, n in cont.items() if n >= min_titulos), key=lambda x: (-x[1], x[0]))
    return [{"palavra": p, "titulos": n} for p, n in ordem[:top]]


def padroes_de_titulo(videos, min_n=MIN_N_PADRAO, idade_min=IDADE_MIN_PIORES):
    """Para cada estrutura de título: quantos vídeos a usam e como a MEDIANA de views deles se compara com a dos que
    não usam. É correlação em amostra pequena, não prova de causa. Vídeos muito recentes ficam de fora porque ainda
    não juntaram views (se sobrarem poucos, usa todos e avisa)."""
    com_views = [v for v in videos or [] if v.get("views") is not None and v.get("titulo")]
    maduros = [v for v in com_views if v.get("idade_dias") is None or v["idade_dias"] >= idade_min]
    usados, idade_aplicada = (maduros, idade_min) if len(maduros) >= 12 else (com_views, 0)
    saida, conjuntos = [], []
    for chave, rotulo, fn in _DETECTORES:
        pegos = frozenset(i for i, v in enumerate(usados) if fn(v["titulo"]))
        com = [usados[i]["views"] for i in pegos]
        sem = [v["views"] for i, v in enumerate(usados) if i not in pegos]
        if len(com) < min_n or len(sem) < min_n:
            continue
        if pegos in conjuntos:            # outra estrutura, já listada, pega exatamente os mesmos vídeos: seria a mesma linha repetida
            continue
        conjuntos.append(pegos)
        mc, ms = _mediana(com), _mediana(sem)
        saida.append({"chave": chave, "rotulo": rotulo, "n_com": len(com), "n_sem": len(sem), "mediana_com": mc, "mediana_sem": ms,
                      "razao": round(mc / ms, 2) if ms else None, "amostra_pequena": min(len(com), len(sem)) < 5})
    saida.sort(key=lambda p: (p["razao"] is None, -(p["razao"] or 0)))

    palavras = []
    for p in palavras_chave([v["titulo"] for v in usados]):
        w = p["palavra"]
        com = [v["views"] for v in usados if w in v["titulo"].lower()]
        sem = [v["views"] for v in usados if w not in v["titulo"].lower()]
        termina = sum(1 for v in usados if re.search(rf"{re.escape(w)}\W*$", v["titulo"].lower()))
        palavras.append({**p, "mediana_com": _mediana(com), "mediana_sem": _mediana(sem), "terminam_com": termina})
    return {"padroes": saida, "palavras_chave": palavras, "n_videos_considerados": len(usados), "idade_min_dias": idade_aplicada}


# --------------------------------------------------------------------------
# Prompts (para colar em qualquer IA de chat — sem API)
# --------------------------------------------------------------------------

def _fmt(n):
    return f"{int(n):,}".replace(",", ".") if isinstance(n, (int, float)) else "?"


def _dec(x):
    """Decimal em português (vírgula), para não confundir com o ponto de milhar dos outros números do prompt."""
    return f"{x:g}".replace(".", ",")


def _dur(seg):
    if seg is None:
        return "?"
    m, s = divmod(int(seg), 60)
    return f"{m}min{s:02d}s"


def _cabecalho_canal(dados):
    c, m = dados["canal"], dados["metricas"]
    partes = [f'Canal: "{c.get("nome") or c.get("url")}"', f'inscritos: {_fmt(m["inscritos"])}']
    if m.get("meses_de_vida") is not None:
        partes.append(f'no ar há {_dec(m["meses_de_vida"])} meses')
    if m.get("views_por_video") is not None:
        partes.append(f'views por vídeo (total ÷ vídeos): {_fmt(m["views_por_video"])}')
    if m.get("mediana_ultimos") is not None:
        partes.append(f'mediana de views dos últimos {m["n_mediana_usados"]} vídeos: {_fmt(m["mediana_ultimos"])}')
    if m.get("uploads_por_mes_vida") is not None:
        partes.append(f'{_dec(m["uploads_por_mes_vida"])} vídeos por mês em média')
    if m.get("duracao_media_seg") is not None:
        partes.append(f'duração média {_dur(m["duracao_media_seg"])}')
    if m.get("titulo_medio_chars") is not None:
        partes.append(f'título médio de {_dec(m["titulo_medio_chars"])} caracteres')
    return "; ".join(partes) + "."


def _linha_video(v):
    idade = f", há {v['idade_dias']} dias" if v.get("idade_dias") is not None else ""
    return f'{v["indice"]}. "{v["titulo"]}" — {_fmt(v["views"])} views{idade}'


def montar_prompt_categorias(dados, limite=LIMITE_VIDEOS_PROMPT):
    videos = [v for v in dados["videos"] if v["titulo"]][:limite]
    if len(videos) < 6:
        raise ValueError("Poucos vídeos lidos para agrupar em categorias (mínimo 6).")
    return (
        "Você é um analista de canais do YouTube.\n"
        + _cabecalho_canal(dados) + "\n\n"
        f"Vídeos mais recentes lidos do canal ({len(videos)}):\n" + "\n".join(_linha_video(v) for v in videos) + "\n\n"
        "Agrupe os vídeos em categorias de conteúdo (os subtemas reais do canal), usando SOMENTE o que os títulos mostram.\n\n"
        "Responda ESTRITAMENTE em JSON válido, sem markdown, sem texto antes ou depois, neste formato:\n"
        '{"categorias": [{"nome": "", "descricao": "", "indices": [1, 2]}]}\n\n'
        'Regras: entre 3 e 8 categorias; "nome" curto (até 5 palavras); "descricao" em uma frase; cada vídeo entra em NO MÁXIMO '
        'uma categoria; use exatamente os números da lista em "indices"; o vídeo que não se encaixa em nenhuma fica de fora. '
        "Não invente vídeos e não calcule views: o app calcula."
    )


def montar_prompt_estrategia(analise, mercado_cod=ideias.MERCADO_PADRAO, objetivo=""):
    dados, ia = analise["dados"], analise.get("ia") or {}
    m, pad = dados["metricas"], dados["padroes"]
    com_views = [v for v in dados["videos"] if v["views"] is not None]
    melhores = [_linha_video(v) for v in sorted(com_views, key=lambda v: -v["views"])[:10]]
    piores = [f'"{v["titulo"]}" — {_fmt(v["views"])} views, há {v["idade_dias"]} dias' if v.get("idade_dias") is not None
              else f'"{v["titulo"]}" — {_fmt(v["views"])} views' for v in m.get("piores", [])]
    blocos = [
        "Você é um estrategista de canais do YouTube. Trabalhe SOMENTE com os dados abaixo.",
        _cabecalho_canal(dados),
        "Vídeos com mais views:\n" + "\n".join(melhores),
    ]
    if piores:
        blocos.append(f'Vídeos com menos views (já com mais de {m["idade_min_piores_dias"]} dias no ar):\n' + "\n".join(piores))
    if pad["padroes"]:
        blocos.append("Estruturas de título (mediana de views com a estrutura ÷ sem a estrutura; amostra pequena, é correlação):\n" + "\n".join(
            f'- {p["rotulo"]}: {p["n_com"]} vídeos, razão {_dec(p["razao"])}×' for p in pad["padroes"][:6]))
    if pad["palavras_chave"]:
        blocos.append("Palavras mais repetidas nos títulos: " + ", ".join(f'{p["palavra"]} ({p["titulos"]})' for p in pad["palavras_chave"][:8]))
    cats = ((ia.get("categorias") or {}).get("estatisticas")) or []
    if cats:
        blocos.append("Categorias do canal (vídeos, mediana de views):\n" + "\n".join(f'- {c["nome"]}: {c["n"]} vídeos, mediana {_fmt(c["mediana_views"])}' for c in cats))
    com = ia.get("comentarios")
    if com:
        if com.get("gostaram"):
            blocos.append("O que o público elogia: " + "; ".join(x["tema"] for x in com["gostaram"][:6]))
        if com.get("nao_gostaram"):
            blocos.append("O que o público critica: " + "; ".join(x["tema"] for x in com["nao_gostaram"][:6]))
        if com.get("pedidos"):
            blocos.append("O que o público pede: " + "; ".join(x["pedido"] for x in com["pedidos"][:6]))
    mk = ideias.mercado(mercado_cod)
    alvo = f"Mercado de destino do meu canal: {mk['nome']} — títulos em {mk['idioma']}."
    if str(objetivo or "").strip():
        alvo += f"\nMeu objetivo: {str(objetivo).strip()[:600]}"
    blocos.append(alvo)
    blocos.append(
        "Responda ESTRITAMENTE em JSON válido, sem markdown, sem texto antes ou depois, neste formato:\n"
        '{"padroes_de_desempenho": [{"padrao": "", "evidencia": "", "confianca": "alta|media|baixa"}], '
        '"formula_de_conteudo": {"promessa_central": "", "estrutura_do_titulo": "", "estrutura_do_video": "", "duracao_e_ritmo": ""}, '
        '"publico": {"quem_e": "", "o_que_busca": "", "gatilhos_emocionais": [""]}, '
        '"oportunidades": [{"oportunidade": "", "por_que": "", "como_diferenciar": "", "risco": ""}], '
        '"topicos_sugeridos": [{"titulo": "", "angulo": "", "por_que_deve_funcionar": ""}], '
        '"roteiro": {"gancho": "", "desenvolvimento": "", "fechamento": ""}, '
        '"riscos_e_ressalvas": [""]}'
    )
    blocos.append(
        "Regras: baseie cada afirmação nos dados acima e, quando não houver evidência, escreva \"sem evidência nos dados\" em vez de "
        "supor. NÃO invente porcentagens, previsões de views nem \"nível de saturação\": isso o usuário mede à parte, com contagem real "
        "no YouTube. Cada oportunidade precisa dizer como se diferenciar SEM copiar o canal. Os títulos sugeridos devem estar no idioma "
        "do mercado de destino. Todo o resto em português."
    )
    return "\n\n".join(blocos)


def limpar_comentarios(texto, max_comentarios=MAX_COMENTARIOS, max_chars=MAX_CHARS_COMENTARIOS):
    """Uma linha por comentário; tira vazios e repetidos e corta no limite."""
    vistos, saida, total = set(), [], 0
    for linha in str(texto or "").splitlines():
        s = re.sub(r"\s+", " ", linha).strip()
        if len(s) < 3 or s.lower() in vistos:
            continue
        s = s[:600]
        if total + len(s) > max_chars or len(saida) >= max_comentarios:
            break
        vistos.add(s.lower())
        saida.append(s)
        total += len(s)
    return saida


def montar_prompt_comentarios(dados, texto_comentarios):
    coments = limpar_comentarios(texto_comentarios)
    if len(coments) < MIN_COMENTARIOS:
        raise ValueError(f"Cole pelo menos {MIN_COMENTARIOS} comentários (um por linha).")
    nome = dados["canal"].get("nome") or dados["canal"].get("url")
    return (
        "Você é um analista de audiência do YouTube.\n"
        f'Estes são {len(coments)} comentários de vídeos do canal "{nome}", um por linha:\n\n'
        + "\n".join(f"- {c}" for c in coments) + "\n\n"
        "Resuma o que o público diz, usando SOMENTE estes comentários.\n\n"
        "Responda ESTRITAMENTE em JSON válido, sem markdown, sem texto antes ou depois, neste formato:\n"
        '{"gostaram": [{"tema": "", "quantos_comentarios": 0, "exemplo": ""}], '
        '"nao_gostaram": [{"tema": "", "quantos_comentarios": 0, "exemplo": ""}], '
        '"pedidos": [{"pedido": "", "exemplo": ""}], "perguntas_frequentes": [""], '
        '"discussoes": [{"tema": "", "posicoes": [""]}], '
        '"ideias_de_video": [{"titulo": "", "dor_que_resolve": ""}]}\n\n'
        'Regras: "quantos_comentarios" é a contagem aproximada NESTA lista (0 se não souber); "exemplo" é um trecho curto copiado de um '
        "comentário; não invente comentários nem temas que não aparecem; omita a lista que não tiver evidência (deixe []); "
        'as ideias de vídeo devem nascer de dores ou pedidos que aparecem nos comentários.'
    )


# --------------------------------------------------------------------------
# Validação do que a IA devolve
# --------------------------------------------------------------------------

def _inteiro(v):
    m = re.search(r"\d+", str(v if v is not None else ""))
    return int(m.group(0)) if m else 0


def _objetos(valor, esquema, limite=12):
    """Lista de dicts normalizados. ``esquema`` = {campo: (aliases...)}; o primeiro campo recebe o texto se o item vier como string."""
    if not isinstance(valor, list):
        return []
    primeiro = next(iter(esquema))
    saida = []
    for item in valor:
        if isinstance(item, str):
            item = {primeiro: item}
        d = ideias._chaves(item)
        if not d:
            continue
        novo = {}
        for campo, aliases in esquema.items():
            if campo.startswith("quantos"):
                novo[campo] = next((_inteiro(d[a]) for a in aliases if d.get(a) not in (None, "")), 0)
            else:
                novo[campo] = ideias._txt(d, *aliases)
        if not novo[primeiro]:
            continue
        saida.append(novo)
        if len(saida) >= limite:
            break
    return saida


def _discussoes(valor):
    """[{tema, posicoes: [...]}] a partir do que a IA devolveu (aceita item só com o texto do tema)."""
    if not isinstance(valor, list):
        return []
    saida = []
    for item in valor:
        d = ideias._chaves(item if isinstance(item, dict) else {"tema": item})
        tema = ideias._txt(d, "tema", "topico")
        if tema:
            saida.append({"tema": tema, "posicoes": ideias._lista_txt(d.get("posicoes"), limite=4)})
        if len(saida) >= 8:
            break
    return saida


def validar_categorias(texto, n_videos):
    dados = ideias.extrair_json(texto)
    d = ideias._chaves({"categorias": dados}) if isinstance(dados, list) else ideias._chaves(dados)
    brutas = d.get("categorias") if isinstance(d.get("categorias"), list) else []
    usados, categorias = set(), []
    for i, item in enumerate(brutas, 1):
        c = ideias._chaves(item)
        nome = ideias._txt(c, "nome", "categoria", "titulo")
        indices = []
        for x in (c.get("indices") if isinstance(c.get("indices"), list) else []):
            try:
                k = int(x)
            except (TypeError, ValueError):
                continue
            if 1 <= k <= n_videos and k not in usados and k not in indices:
                indices.append(k)
        if not nome or not indices:
            continue
        usados.update(indices)
        categorias.append({"nome": nome, "descricao": ideias._txt(c, "descricao", "resumo"), "indices": indices})
    if not categorias:
        raise ValueError("O JSON não tem 'categorias' com nome e 'indices' válidos.")
    return categorias


def estatisticas_categorias(categorias, videos):
    """Contagem e views por categoria, calculadas aqui (a IA só decidiu quem entra em qual)."""
    por_indice = {v["indice"]: v for v in videos}
    saida = []
    for c in categorias or []:
        vs = [por_indice[i] for i in c["indices"] if i in por_indice]
        views = [v["views"] for v in vs if v["views"] is not None]
        melhor = max((v for v in vs if v["views"] is not None), key=lambda v: v["views"], default=None)
        saida.append({"nome": c["nome"], "descricao": c.get("descricao", ""), "n": len(vs), "share": round(len(vs) / len(videos), 3) if videos else None,
                      "mediana_views": _mediana(views), "media_views": round(_media(views)) if views else None,
                      "views_dia_mediana": _mediana([v["views_dia"] for v in vs]),
                      "melhor": {"titulo": melhor["titulo"], "url": melhor["url"], "views": melhor["views"]} if melhor else None,
                      "indices": c["indices"]})
    saida.sort(key=lambda x: (x["mediana_views"] is None, -(x["mediana_views"] or 0)))
    usados = {i for c in categorias or [] for i in c["indices"]}
    return saida, len([v for v in videos if v["indice"] not in usados])


def validar_estrategia(texto):
    d = ideias._chaves(ideias.extrair_json(texto))
    if not d:
        raise ValueError("O JSON precisa ser um objeto com as chaves pedidas no prompt.")

    def bloco(chave, esquema):
        b = ideias._chaves(d.get(chave))
        return {campo: ideias._lista_txt(b.get(campo)) if campo == "gatilhos_emocionais" else ideias._txt(b, campo) for campo in esquema}

    out = {
        "padroes_de_desempenho": _objetos(d.get("padroes_de_desempenho"), {"padrao": ("padrao", "nome"), "evidencia": ("evidencia",), "confianca": ("confianca",)}),
        "formula_de_conteudo": bloco("formula_de_conteudo", ("promessa_central", "estrutura_do_titulo", "estrutura_do_video", "duracao_e_ritmo")),
        "publico": bloco("publico", ("quem_e", "o_que_busca", "gatilhos_emocionais")),
        "oportunidades": _objetos(d.get("oportunidades"), {"oportunidade": ("oportunidade", "titulo"), "por_que": ("por_que",), "como_diferenciar": ("como_diferenciar",), "risco": ("risco",)}),
        "topicos_sugeridos": _objetos(d.get("topicos_sugeridos"), {"titulo": ("titulo", "topico"), "angulo": ("angulo",), "por_que_deve_funcionar": ("por_que_deve_funcionar", "por_que")}, limite=15),
        "roteiro": bloco("roteiro", ("gancho", "desenvolvimento", "fechamento")),
        "riscos_e_ressalvas": ideias._lista_txt(d.get("riscos_e_ressalvas"), limite=10),
    }
    tem = any([out["padroes_de_desempenho"], out["oportunidades"], out["topicos_sugeridos"], out["riscos_e_ressalvas"],
               any(out["formula_de_conteudo"].values()), out["publico"]["quem_e"] or out["publico"]["o_que_busca"], any(out["roteiro"].values())])
    if not tem:
        raise ValueError("Não achei nenhum dos campos pedidos (padroes_de_desempenho, oportunidades, topicos_sugeridos...).")
    return out


def validar_comentarios(texto):
    d = ideias._chaves(ideias.extrair_json(texto))
    if not d:
        raise ValueError("O JSON precisa ser um objeto com as chaves pedidas no prompt.")
    tema = {"tema": ("tema", "topico"), "quantos_comentarios": ("quantos_comentarios", "quantidade", "frequencia_aprox"), "exemplo": ("exemplo", "trecho")}
    out = {
        "gostaram": _objetos(d.get("gostaram"), tema), "nao_gostaram": _objetos(d.get("nao_gostaram"), tema),
        "pedidos": _objetos(d.get("pedidos"), {"pedido": ("pedido", "tema"), "exemplo": ("exemplo",)}),
        "perguntas_frequentes": ideias._lista_txt(d.get("perguntas_frequentes"), limite=12),
        "discussoes": _discussoes(d.get("discussoes")),
        "ideias_de_video": _objetos(d.get("ideias_de_video"), {"titulo": ("titulo",), "dor_que_resolve": ("dor_que_resolve", "dor")}),
    }
    if not any(out.values()):
        raise ValueError("Não achei nenhum dos campos pedidos (gostaram, nao_gostaram, pedidos...).")
    return out


# --------------------------------------------------------------------------
# Montagem e persistência
# --------------------------------------------------------------------------

def montar_dados(canal, agora=None):
    """Foto do canal no momento da coleta: dados do cabeçalho, vídeos, painel e padrões de título."""
    c = canal or {}
    videos = videos_da_amostra(c, agora)
    return {
        "canal": {"nome": c.get("canal") or c.get("nome") or "", "url": c.get("canal_url") or c.get("url") or "",
                  "inscritos_num": c.get("inscritos_num"), "inscritos_text": c.get("inscritos_text", ""), "n_videos": c.get("n_videos"),
                  "views_totais": c.get("views_totais"), "data_criacao_canal": c.get("data_criacao_canal", ""),
                  "pais": c.get("pais_canal", ""), "idioma": c.get("idioma_canal", "")},
        "videos": videos, "metricas": metricas_canal(c, agora), "padroes": padroes_de_titulo(videos),
        "coletado_em": (agora or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S"),
    }


SCHEMA = """
CREATE TABLE IF NOT EXISTS analises_canal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canal_url TEXT NOT NULL,
  canal TEXT NOT NULL,
  criado_em TEXT NOT NULL,
  dados_json TEXT NOT NULL,
  ia_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_analises_canal_url ON analises_canal(canal_url);
"""
_LOCK = threading.RLock()


def _conectar(db_path=None):
    caminho = biblioteca.caminho_banco(db_path)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(caminho), timeout=15)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def salvar_analise(canal, agora=None, db_path=None):
    dados = montar_dados(canal, agora)
    nome = dados["canal"]["nome"] or dados["canal"]["url"] or "Canal sem nome"
    with _LOCK:
        con = _conectar(db_path)
        try:
            cur = con.execute("INSERT INTO analises_canal (canal_url, canal, criado_em, dados_json) VALUES (?,?,?,?)",
                              (dados["canal"]["url"], nome, dados["coletado_em"], json.dumps(dados, ensure_ascii=False)))
            con.commit()
            return cur.lastrowid
        finally:
            con.close()


def _completar_ia(dados, ia):
    """Estatísticas das categorias sempre recalculadas dos vídeos guardados (a IA só guarda quem entra onde)."""
    ia = dict(ia or {})
    cat = ia.get("categorias")
    if cat:
        est, sem = estatisticas_categorias(cat["categorias"], dados["videos"])
        ia["categorias"] = {**cat, "estatisticas": est, "sem_categoria": sem}
    return ia


def _linha_para_analise(r):
    dados = json.loads(r["dados_json"])
    return {"id": r["id"], "canal": r["canal"], "canal_url": r["canal_url"], "criado_em": r["criado_em"], "dados": dados,
            "ia": _completar_ia(dados, json.loads(r["ia_json"] or "{}"))}


def obter_analise(analise_id, db_path=None):
    with _LOCK:
        con = _conectar(db_path)
        try:
            r = con.execute("SELECT * FROM analises_canal WHERE id = ?", (int(analise_id),)).fetchone()
        finally:
            con.close()
    return _linha_para_analise(r) if r else None


def listar_analises(db_path=None):
    with _LOCK:
        con = _conectar(db_path)
        try:
            linhas = con.execute("SELECT id, canal, canal_url, criado_em, dados_json FROM analises_canal ORDER BY id DESC").fetchall()
        finally:
            con.close()
    saida = []
    for r in linhas:
        m = json.loads(r["dados_json"]).get("metricas", {})
        saida.append({"id": r["id"], "canal": r["canal"], "canal_url": r["canal_url"], "criado_em": r["criado_em"],
                      "inscritos": m.get("inscritos"), "amostra_n": m.get("amostra_n")})
    return saida


def gravar_ia(analise_id, tipo, conteudo, db_path=None):
    """Grava (ou, com ``conteudo=None``, apaga) a parte de IA. Devolve a análise atualizada ou ``None`` se não existe."""
    if tipo not in TIPOS_IA:
        raise ValueError("Tipo de análise desconhecido.")
    with _LOCK:
        con = _conectar(db_path)
        try:
            r = con.execute("SELECT ia_json FROM analises_canal WHERE id = ?", (int(analise_id),)).fetchone()
            if r is None:
                return None
            ia = json.loads(r["ia_json"] or "{}")
            if conteudo is None:
                ia.pop(tipo, None)
            else:
                ia[tipo] = {**conteudo, "aplicado_em": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
            con.execute("UPDATE analises_canal SET ia_json = ? WHERE id = ?", (json.dumps(ia, ensure_ascii=False), int(analise_id)))
            con.commit()
        finally:
            con.close()
    return obter_analise(analise_id, db_path)


def excluir_analise(analise_id, db_path=None):
    with _LOCK:
        con = _conectar(db_path)
        try:
            cur = con.execute("DELETE FROM analises_canal WHERE id = ?", (int(analise_id),))
            con.commit()
            return cur.rowcount > 0
        finally:
            con.close()
