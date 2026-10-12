#!/usr/bin/env python3
"""
IA das ferramentas da API do YouTube. Mesmo padrão do resto do app: o app monta o prompt com os dados, você roda em
qualquer IA de chat e cola a resposta; aqui ela é lida com tolerância e validada. Nenhuma chamada de IA sai daqui.

Os prompts levam só os dados que o app leu e mandam a IA dizer "sem evidência nos dados" em vez de supor, porque
número inventado é o erro mais comum desse tipo de análise.
"""

import re

import ideias

TIPOS = ("oportunidades", "comparativo", "dossie", "engenharia", "auditoria")
MAX_VIDEOS_PROMPT = 40
MAX_TRANSCRICAO = 24000
MAX_CONTEXTO = 1500

REGRAS = (
    "Baseie cada afirmação nos dados acima e, quando não houver evidência, escreva \"sem evidência nos dados\" em vez de supor. "
    "NÃO invente números, porcentagens, previsões de views nem receita. Não trate correlação como causa. Responda em português."
)


# --------------------------------------------------------------------------
# Formatação
# --------------------------------------------------------------------------

def _n(v):
    return f"{int(v):,}".replace(",", ".") if isinstance(v, (int, float)) and not isinstance(v, bool) else "?"


def _dec(v, casas=2):
    return f"{v:.{casas}f}".replace(".", ",") if isinstance(v, (int, float)) and not isinstance(v, bool) else "?"


def _dur(seg):
    if not isinstance(seg, (int, float)) or isinstance(seg, bool):
        return "?"
    h, resto = divmod(int(seg), 3600)
    m, s = divmod(resto, 60)
    return f"{h}h{m:02d}min" if h else f"{m}min{s:02d}s"


def _corta(texto, n):
    t = re.sub(r"\s+", " ", str(texto or "")).strip()
    return t if len(t) <= n else t[:n].rstrip() + "…"


def _d(v):
    return v if isinstance(v, dict) else {}


def _f(v):
    """Número ou 0: os dados voltam do navegador e não dá para confiar no tipo."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _l(v):
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _contexto(contexto):
    c = _corta(contexto, MAX_CONTEXTO)
    return f"Contexto que o usuário informou: {c}" if c else ""


def _linha_video(i, v, canais=None):
    canal = _d((canais or {}).get(v.get("canal_id")))
    partes = [f'{i}. "{_corta(v.get("titulo"), 140)}"']
    if v.get("canal"):
        ins = (" (inscritos ocultos)" if canal.get("inscritos_ocultos") else f' ({_n(canal.get("inscritos"))} inscritos)') if canal else ""
        partes.append(f'canal "{_corta(v["canal"], 60)}"{ins}')
    partes.append(f'{_n(v.get("views"))} views')
    if v.get("engajamento") is not None:
        partes.append(f'engajamento {_dec(v["engajamento"])}%')
    partes.append(_dur(v.get("duracao_seg")))
    if v.get("idade_dias") is not None:
        partes.append(f'há {v["idade_dias"]} dias')
    return " — ".join(partes)


def _cabecalho_canal(c, m=None):
    m = m or {}
    p = [f'Canal: "{_corta(c.get("titulo"), 80)}"']
    if c.get("handle"):
        p.append(c["handle"])
    p.append(f'inscritos: {"ocultos" if c.get("inscritos_ocultos") else _n(c.get("inscritos"))}')
    p += [f'views totais: {_n(c.get("views_totais"))}', f'vídeos publicados: {_n(c.get("n_videos"))}']
    if c.get("pais"):
        p.append(f'país: {c["pais"]}')
    if m.get("idade_dias") is not None:
        p.append(f'no ar há {_n(m["idade_dias"])} dias')
    if m.get("views_por_video") is not None:
        p.append(f'views por vídeo (total ÷ vídeos): {_n(m["views_por_video"])}')
    if m.get("videos_por_semana") is not None:
        p.append(f'{_dec(m["videos_por_semana"])} vídeos por semana em média (vida toda)')
    return "; ".join(p) + "."


def _schema(esquema):
    return "Responda ESTRITAMENTE em JSON válido, sem markdown, sem texto antes ou depois, neste formato:\n" + esquema


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------

def prompt_oportunidades(dados, contexto=""):
    d = _d(dados)
    videos = _l(d.get("videos"))[:MAX_VIDEOS_PROMPT]
    if not videos:
        raise ValueError("Não há vídeos na lista filtrada para analisar.")
    canais = _d(d.get("canais"))
    onde = f' em {d["pais"]}' if d.get("pais") else ""
    blocos = [
        "Você é um analista de nichos do YouTube. Um canal dark (faceless) é o que não mostra o rosto de quem faz: usa narração, animação, "
        "imagens de arquivo, gravação de tela ou IA. Trabalhe SOMENTE com a lista abaixo.",
        f"Vídeos em alta{onde}, já filtrados e ordenados pelo usuário ({len(videos)}):\n" + "\n".join(_linha_video(i, v, canais) for i, v in enumerate(videos, 1)),
        _contexto(contexto),
        _schema('{"leitura_geral": "", "nichos_em_alta": [{"nicho": "", "por_que_esta_em_alta": "", "evidencia": [1, 2], "dificuldade": "baixa|media|alta", "risco": ""}], '
                '"oportunidades_dark": [{"ideia": "", "formato": "", "como_produzir_sem_aparecer": "", "exemplo_de_titulo": "", "evidencia": [1]}], '
                '"canais_pequenos_em_destaque": [{"indice": 1, "por_que_chama_atencao": ""}], "ressalvas": [""]}'),
        'Regras: "evidencia" e "indice" são os números da lista acima. Só aponte um nicho com pelo menos 2 vídeos da lista como evidência. '
        "Canais grandes ganham views por autoridade acumulada, então dê mais peso a canais pequenos com views altas. " + REGRAS,
    ]
    return "\n\n".join(b for b in blocos if b)


def prompt_comparativo(dados, contexto=""):
    d = _d(dados)
    a, b = _d(d.get("a")), _d(d.get("b"))
    if not _d(a.get("canal")) or not _d(b.get("canal")):
        raise ValueError("Faltam os dados dos dois canais.")

    def bloco(rotulo, x):
        vids = sorted(_l(x.get("videos")), key=lambda v: -_f(v.get("views")))[:6]
        return (f"CANAL {rotulo}\n" + _cabecalho_canal(x["canal"], x.get("metricas")) + "\nVídeos recentes com mais views:\n"
                + "\n".join(_linha_video(i, v) for i, v in enumerate(vids, 1)))

    linhas = []
    for l in _l(d.get("comparacao")):
        linhas.append(f'- {l.get("rotulo")}: A = {_dec(l.get("a"))}, B = {_dec(l.get("b"))}' if isinstance(l.get("a"), float) or isinstance(l.get("b"), float)
                      else f'- {l.get("rotulo")}: A = {_n(l.get("a"))}, B = {_n(l.get("b"))}')
    blocos = [
        "Você é um analista de concorrência no YouTube. Compare os dois canais abaixo usando SOMENTE estes dados.",
        bloco("A", a), bloco("B", b),
        "Números lado a lado:\n" + "\n".join(linhas), _contexto(contexto),
        _schema('{"resumo": "", "forcas_a": [""], "forcas_b": [""], "diferencas_de_estrategia": [{"tema": "", "a": "", "b": ""}], '
                '"oportunidades_para_competir": [{"oportunidade": "", "como": ""}], "veredito": "", "ressalvas": [""]}'),
        "Regras: canais de tamanhos muito diferentes não se comparam pelo total; use mediana, tração e engajamento. " + REGRAS,
    ]
    return "\n\n".join(x for x in blocos if x)


def prompt_dossie(dados, contexto=""):
    d = _d(dados)
    c = _d(d.get("canal"))
    if not c:
        raise ValueError("Faltam os dados do canal.")
    blocos = [
        "Você é um analista de canais do YouTube. Monte um dossiê do canal abaixo usando SOMENTE estes dados.",
        _cabecalho_canal(c, d.get("metricas")),
        f'Inscritos por vídeo: {_n(_d(d.get("metricas")).get("inscritos_por_video"))}; inscritos ÷ views totais: {_dec(_d(d.get("metricas")).get("inscritos_por_view_pct"), 3)}%.',
        ("Descrição do canal: " + _corta(c.get("descricao"), 800)) if c.get("descricao") else "",
        ("Palavras-chave do canal: " + ", ".join(str(x) for x in (c.get("palavras_chave") or [])[:20])) if c.get("palavras_chave") else "",
        _contexto(contexto),
        _schema('{"resumo": "", "posicionamento": "", "proposta_de_valor": "", "publico": "", "pontos_fortes": [""], "pontos_fracos": [""], '
                '"oportunidades": [{"oportunidade": "", "como_aproveitar": ""}], "riscos": [""], "proximos_passos": [""], "ressalvas": [""]}'),
        "Regras: você NÃO viu os vídeos, só os números e o texto do canal; deixe claro o que é dedução. " + REGRAS,
    ]
    return "\n\n".join(x for x in blocos if x)


def prompt_engenharia(dados, transcricao="", contexto=""):
    d = _d(dados)
    v = _d(d.get("video"))
    if not v:
        raise ValueError("Faltam os dados do vídeo.")
    trans = re.sub(r"[ \t]+", " ", str(transcricao or "")).strip()[:MAX_TRANSCRICAO]
    canal = _d(d.get("canal"))
    dados_video = [f'Título: "{_corta(v.get("titulo"), 200)}"', f'Canal: "{_corta(v.get("canal"), 80)}" ({_n(v.get("inscritos_do_canal"))} inscritos)',
                   f'{_n(v.get("views"))} views, {_n(v.get("likes"))} likes, {_n(v.get("comentarios"))} comentários, engajamento {_dec(v.get("engajamento"))}%',
                   f'Duração: {_dur(v.get("duracao_seg"))}; publicado em {v.get("data") or "?"}']
    if v.get("views_sobre_inscritos") is not None:
        dados_video.append(f'Views ÷ inscritos do canal: {_dec(v["views_sobre_inscritos"])}')
    if v.get("tags"):
        dados_video.append("Tags: " + ", ".join(str(t) for t in v["tags"][:20]))
    if v.get("topicos"):
        dados_video.append("Tópicos do YouTube: " + ", ".join(str(t) for t in v["topicos"][:8]))
    if v.get("descricao"):
        dados_video.append("Descrição: " + _corta(v["descricao"], 1200))
    aviso = ("Transcrição do vídeo:\n" + trans) if trans else (
        "SEM TRANSCRIÇÃO. Analise só título, descrição, tags e números, e marque como hipótese tudo o que dependeria de ter visto o vídeo (estrutura, gancho, ritmo).")
    blocos = [
        "Você é um analista de roteiro e retenção de vídeos do YouTube. Faça a engenharia reversa do vídeo abaixo usando SOMENTE estes dados.",
        "\n".join(dados_video), aviso, _contexto(contexto),
        _schema('{"resumo": "", "gancho": {"tecnica": "", "como_funciona": ""}, "promessa": "", "estrutura": [{"trecho": "", "funcao": "", "tecnica": ""}], '
                '"retencao": [""], "tom_e_ritmo": "", "cta": "", "o_que_replicar": [""], "o_que_evitar": [""], "ressalvas": [""]}'),
        'Regras: em "estrutura" cite o trecho da transcrição em poucas palavras. Não copie o roteiro: descreva a técnica para o usuário recriar com outro tema. ' + REGRAS,
    ]
    return "\n\n".join(x for x in blocos if x)


def prompt_auditoria(dados, contexto=""):
    d = _d(dados)
    c = _d(d.get("canal"))
    videos = _l(d.get("videos"))
    if not c or len(videos) < 3:
        raise ValueError("O histórico precisa de pelo menos 3 vídeos para uma auditoria.")
    rec = _d(d.get("recentes"))
    ordem = sorted(videos, key=lambda v: str(v.get("publicado") or ""))                     # do mais antigo ao mais novo: mostra a evolução
    blocos = [
        "Você é um consultor de crescimento de canais do YouTube. Faça uma auditoria de evolução do canal abaixo usando SOMENTE estes dados.",
        _cabecalho_canal(c),
        f'Nos {len(videos)} vídeos lidos: mediana de views {_n(rec.get("mediana_views"))}, média {_n(rec.get("media_views"))}, '
        f'engajamento médio {_dec(rec.get("engajamento_medio"))}%, {_dec(rec.get("videos_por_semana"))} vídeos por semana.',
        f"Histórico, do mais antigo ao mais novo ({len(ordem)} vídeos):\n" + "\n".join(_linha_video(i, v) for i, v in enumerate(ordem, 1)),
        _contexto(contexto),
        _schema('{"resumo": "", "fases": [{"periodo": "", "o_que_aconteceu": "", "evidencia": [1, 2]}], "padroes": [{"padrao": "", "evidencia": [1]}], '
                '"pontos_de_virada": [{"quando": "", "o_que_mudou": "", "evidencia": [1]}], "o_que_funciona": [""], "o_que_nao_funciona": [""], '
                '"recomendacoes": [{"acao": "", "por_que": ""}], "ressalvas": [""]}'),
        'Regras: "evidencia" são os números da lista acima. Vídeos recentes ainda estão juntando views, então não os compare com os antigos como se estivessem completos. '
        + REGRAS,
    ]
    return "\n\n".join(x for x in blocos if x)


def montar_prompt(tipo, dados, contexto="", transcricao=""):
    if tipo == "oportunidades":
        return prompt_oportunidades(dados, contexto)
    if tipo == "comparativo":
        return prompt_comparativo(dados, contexto)
    if tipo == "dossie":
        return prompt_dossie(dados, contexto)
    if tipo == "engenharia":
        return prompt_engenharia(dados, transcricao, contexto)
    if tipo == "auditoria":
        return prompt_auditoria(dados, contexto)
    raise ValueError("Tipo de análise desconhecido.")


# --------------------------------------------------------------------------
# Validação do que a IA devolve
# --------------------------------------------------------------------------

def _txt_lista(v, limite=12):
    return ideias._lista_txt(v, limite=limite)


def _inteiros(v, maximo=None):
    if not isinstance(v, list):
        v = [v] if isinstance(v, (int, str)) and not isinstance(v, bool) else []
    saida = []
    for x in v:
        m = re.search(r"\d+", str(x))
        if m:
            k = int(m.group(0))
            if k >= 1 and (maximo is None or k <= maximo) and k not in saida:
                saida.append(k)
    return saida


def _itens(valor, texto, indices=(), limite=12, maximo=None, obrigatorio=None):
    """Lista de dicts. ``texto`` = {campo: (aliases)}; ``indices`` = campos com números da lista do prompt (viram listas de int).
    Sem o campo ``obrigatorio`` (por padrão o 1º de texto) o item é descartado."""
    if not isinstance(valor, list):
        return []
    primeiro = next(iter(texto))
    exigido = obrigatorio or primeiro
    saida = []
    for item in valor:
        d = ideias._chaves(item if isinstance(item, dict) else {primeiro: item})
        novo = {campo: ideias._txt(d, *aliases) for campo, aliases in texto.items()}
        for campo in indices:
            novo[campo] = _inteiros(d.get(campo), maximo)
        if not novo[exigido]:
            continue
        saida.append(novo)
        if len(saida) >= limite:
            break
    return saida


def _obj(d, chave, campos):
    b = ideias._chaves(d.get(chave))
    return {c: ideias._txt(b, c) for c in campos}


def _dict(texto):
    d = ideias._chaves(ideias.extrair_json(texto))
    if not d:
        raise ValueError("O JSON precisa ser um objeto com as chaves pedidas no prompt.")
    return d


def _vazio(out):
    def cheio(x):
        if isinstance(x, dict):
            return any(cheio(v) for v in x.values())
        return bool(x)
    if not cheio(out):
        raise ValueError("Não achei nenhum dos campos pedidos no prompt. Confira se a IA seguiu o formato.")
    return out


def validar_oportunidades(texto, n_videos=MAX_VIDEOS_PROMPT):
    d = _dict(texto)
    return _vazio({
        "leitura_geral": ideias._txt(d, "leitura_geral", "resumo"),
        "nichos_em_alta": _itens(d.get("nichos_em_alta"), {"nicho": ("nicho",), "por_que_esta_em_alta": ("por_que_esta_em_alta", "por_que"), "dificuldade": ("dificuldade",), "risco": ("risco",)}, ("evidencia",), maximo=n_videos),
        "oportunidades_dark": _itens(d.get("oportunidades_dark"), {"ideia": ("ideia", "oportunidade"), "formato": ("formato",), "como_produzir_sem_aparecer": ("como_produzir_sem_aparecer", "como_produzir"), "exemplo_de_titulo": ("exemplo_de_titulo", "titulo")}, ("evidencia",), maximo=n_videos),
        "canais_pequenos_em_destaque": [{"indice": x["indice"][0], "por_que_chama_atencao": x["por_que_chama_atencao"]} for x in _itens(
            d.get("canais_pequenos_em_destaque"), {"por_que_chama_atencao": ("por_que_chama_atencao", "por_que")}, ("indice",), maximo=n_videos, obrigatorio="indice")],
        "ressalvas": _txt_lista(d.get("ressalvas"), 10),
    })


def validar_comparativo(texto):
    d = _dict(texto)
    dif = []
    for item in (d.get("diferencas_de_estrategia") if isinstance(d.get("diferencas_de_estrategia"), list) else []):
        x = ideias._chaves(item)
        tema = ideias._txt(x, "tema", "topico")
        if tema:
            dif.append({"tema": tema, "a": ideias._txt(x, "a", "canal_a"), "b": ideias._txt(x, "b", "canal_b")})
    return _vazio({
        "resumo": ideias._txt(d, "resumo"), "forcas_a": _txt_lista(d.get("forcas_a")), "forcas_b": _txt_lista(d.get("forcas_b")),
        "diferencas_de_estrategia": dif[:10],
        "oportunidades_para_competir": _itens(d.get("oportunidades_para_competir"), {"oportunidade": ("oportunidade",), "como": ("como", "como_diferenciar")}),
        "veredito": ideias._txt(d, "veredito", "conclusao"), "ressalvas": _txt_lista(d.get("ressalvas"), 10),
    })


def validar_dossie(texto):
    d = _dict(texto)
    return _vazio({
        "resumo": ideias._txt(d, "resumo"), "posicionamento": ideias._txt(d, "posicionamento"), "proposta_de_valor": ideias._txt(d, "proposta_de_valor"),
        "publico": ideias._txt(d, "publico"), "pontos_fortes": _txt_lista(d.get("pontos_fortes")), "pontos_fracos": _txt_lista(d.get("pontos_fracos")),
        "oportunidades": _itens(d.get("oportunidades"), {"oportunidade": ("oportunidade",), "como_aproveitar": ("como_aproveitar", "como")}),
        "riscos": _txt_lista(d.get("riscos")), "proximos_passos": _txt_lista(d.get("proximos_passos")), "ressalvas": _txt_lista(d.get("ressalvas"), 10),
    })


def validar_engenharia(texto):
    d = _dict(texto)
    return _vazio({
        "resumo": ideias._txt(d, "resumo"), "gancho": _obj(d, "gancho", ("tecnica", "como_funciona")), "promessa": ideias._txt(d, "promessa"),
        "estrutura": _itens(d.get("estrutura"), {"trecho": ("trecho", "parte"), "funcao": ("funcao",), "tecnica": ("tecnica",)}, limite=20),
        "retencao": _txt_lista(d.get("retencao")), "tom_e_ritmo": ideias._txt(d, "tom_e_ritmo", "tom"), "cta": ideias._txt(d, "cta"),
        "o_que_replicar": _txt_lista(d.get("o_que_replicar")), "o_que_evitar": _txt_lista(d.get("o_que_evitar")), "ressalvas": _txt_lista(d.get("ressalvas"), 10),
    })


def validar_auditoria(texto, n_videos=50):
    d = _dict(texto)
    return _vazio({
        "resumo": ideias._txt(d, "resumo"),
        "fases": _itens(d.get("fases"), {"periodo": ("periodo",), "o_que_aconteceu": ("o_que_aconteceu", "descricao")}, ("evidencia",), maximo=n_videos),
        "padroes": _itens(d.get("padroes"), {"padrao": ("padrao",)}, ("evidencia",), maximo=n_videos),
        "pontos_de_virada": _itens(d.get("pontos_de_virada"), {"quando": ("quando",), "o_que_mudou": ("o_que_mudou",)}, ("evidencia",), maximo=n_videos),
        "o_que_funciona": _txt_lista(d.get("o_que_funciona")), "o_que_nao_funciona": _txt_lista(d.get("o_que_nao_funciona")),
        "recomendacoes": _itens(d.get("recomendacoes"), {"acao": ("acao", "recomendacao"), "por_que": ("por_que",)}), "ressalvas": _txt_lista(d.get("ressalvas"), 10),
    })


VALIDADORES = {"oportunidades": validar_oportunidades, "comparativo": validar_comparativo, "dossie": validar_dossie,
               "engenharia": validar_engenharia, "auditoria": validar_auditoria}
