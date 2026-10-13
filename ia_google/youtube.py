"""
Análise de vídeos do YouTube pelo Modo IA do Google (que "assiste" ao vídeo).

    from ia_google import GoogleIA
    from youtube import AnalisadorYouTube

    with GoogleIA() as ia:
        yt = AnalisadorYouTube(ia)
        r = yt.executar("https://www.youtube.com/watch?v=XXXX", "resumo")
        r = yt.executar(url, "momentos", "quando ele fala do paradoxo de Simpson")
        r = yt.executar(url, "pergunta", "qual a conclusão do autor?")
        print(r["resposta_objetiva"], r["dados"])

Todo tempo (inicio/fim/tempo) vem também em segundos (inicio_seg) e com link direto (inicio_link).
Perguntas sobre o mesmo vídeo continuam na mesma conversa do Google.
"""
import re
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------- tarefas
# Cada tarefa: descrição para a IA, formato JSON esperado e se precisa de "consulta" (texto do usuário).
# ATENÇÃO: não coloque exemplos de links (https://...) nos formatos: o Google transforma em anexo.
TAREFAS = {
    "resumo": {
        "nome": "Resumo",
        "icone": "📝",
        "descricao": "Resumo do vídeo com os tópicos na ordem em que aparecem",
        "pedido": "Assista ao vídeo e faça um resumo completo, com os tópicos na ordem em que aparecem.",
        "formato": '''{
  "titulo": "título do vídeo", "canal": "nome do canal", "duracao": "mm:ss",
  "resumo_curto": "o vídeo em 1 ou 2 frases",
  "resumo_completo": "resumo detalhado em markdown",
  "topicos": [{"inicio": "mm:ss", "fim": "mm:ss", "titulo": "tópico", "resumo": "o que é dito"}],
  "pontos_chave": ["ideia principal 1", "ideia principal 2"],
  "conclusao": "a conclusão ou mensagem final do vídeo"
}''',
    },
    "pergunta": {
        "nome": "Perguntar",
        "icone": "❓",
        "consulta": "Sua pergunta sobre o vídeo",
        "descricao": "Responde uma pergunta sobre o conteúdo, mostrando os trechos",
        "pedido": "Responda a pergunta abaixo com base no conteúdo do vídeo, indicando os trechos que comprovam a resposta.\nPergunta: {consulta}",
        "formato": '''{
  "resposta_objetiva": "resposta direta em 1 ou 2 frases",
  "resposta_completa": "explicação em markdown",
  "trechos": [{"inicio": "mm:ss", "fim": "mm:ss", "citacao": "o que é dito nesse trecho", "explicacao": "por que responde a pergunta"}],
  "confianca": "alta, media ou baixa"
}''',
    },
    "momentos": {
        "nome": "Achar momentos",
        "icone": "⏱️",
        "consulta": "O que você quer encontrar no vídeo",
        "descricao": "Encontra o início e o fim de cada momento em que algo acontece",
        "pedido": "Encontre TODOS os momentos do vídeo em que acontece ou é falado o seguinte: {consulta}. "
                  "Para cada momento dê o tempo de início e de fim exatos na linha do tempo do vídeo.",
        "formato": '''{
  "encontrado": true,
  "resposta_objetiva": "resumo do que foi encontrado em 1 frase",
  "momentos": [{"inicio": "mm:ss", "fim": "mm:ss", "descricao": "o que acontece", "citacao": "frase dita nesse momento"}]
}''',
    },
    "capitulos": {
        "nome": "Capítulos",
        "icone": "📑",
        "descricao": "Divide o vídeo em capítulos com tempo de início (bom para a descrição do YouTube)",
        "pedido": "Divida o vídeo em capítulos, como os capítulos da descrição do YouTube, começando em 00:00.",
        "formato": '''{
  "duracao": "mm:ss",
  "capitulos": [{"inicio": "mm:ss", "fim": "mm:ss", "titulo": "título curto do capítulo", "resumo": "1 frase"}]
}''',
    },
    "cortes": {
        "nome": "Cortes p/ Shorts",
        "icone": "✂️",
        "consulta": "Opcional: tema ou duração desejada (ex.: até 60s)",
        "consulta_opcional": True,
        "descricao": "Sugere os melhores trechos para Shorts/Reels/TikTok, com início e fim",
        "pedido": "Sugira os melhores trechos deste vídeo para virar cortes curtos (Shorts, Reels, TikTok), "
                  "com início e fim exatos, que façam sentido sozinhos. {consulta}",
        "formato": '''{
  "cortes": [{"inicio": "mm:ss", "fim": "mm:ss", "titulo": "título chamativo", "gancho": "frase de abertura do corte",
              "motivo": "por que funciona", "nota": 8}]
}''',
    },
    "citacoes": {
        "nome": "Frases marcantes",
        "icone": "💬",
        "descricao": "As frases mais marcantes, com o tempo e quem falou",
        "pedido": "Liste as frases mais marcantes ou importantes ditas no vídeo, exatamente como foram ditas, com o tempo.",
        "formato": '''{
  "citacoes": [{"tempo": "mm:ss", "texto": "frase exata", "quem": "quem falou", "contexto": "contexto em 1 frase"}]
}''',
    },
    "fatos": {
        "nome": "Checar fatos",
        "icone": "🔎",
        "descricao": "Lista as afirmações do vídeo e verifica se são verdadeiras, com fontes",
        "pedido": "Liste as principais afirmações factuais do vídeo (dados, números, datas, estudos) e verifique cada uma "
                  "em fontes confiáveis atuais.",
        "formato": '''{
  "afirmacoes": [{"tempo": "mm:ss", "afirmacao": "o que o vídeo afirma",
                  "veredito": "verdadeiro, falso, parcialmente verdadeiro ou nao verificavel",
                  "explicacao": "o que as fontes dizem",
                  "fontes": [{"nome": "nome do site", "url": "endereço completo da página"}]}]
}''',
    },
    "passos": {
        "nome": "Passo a passo",
        "icone": "🧭",
        "descricao": "Transforma tutoriais em passo a passo com o tempo de cada etapa",
        "pedido": "Transforme o conteúdo do vídeo em um passo a passo prático, indicando em que tempo cada etapa aparece.",
        "formato": '''{
  "objetivo": "o que se aprende/faz",
  "materiais": ["item necessário"],
  "passos": [{"inicio": "mm:ss", "titulo": "etapa", "descricao": "como fazer"}],
  "dicas": ["dica importante"]
}''',
    },
    "seo": {
        "nome": "Título, descrição e tags",
        "icone": "🏷️",
        "descricao": "Sugere títulos, descrição com capítulos, tags e hashtags",
        "pedido": "Com base no conteúdo do vídeo, sugira títulos, uma descrição otimizada com capítulos, tags e hashtags.",
        "formato": '''{
  "titulos": ["sugestão de título"],
  "descricao": "descrição pronta para colar, com capítulos no formato 00:00 Título",
  "tags": ["tag"], "hashtags": ["#hashtag"]
}''',
    },
    "quiz": {
        "nome": "Quiz",
        "icone": "🎓",
        "descricao": "Perguntas de múltipla escolha sobre o vídeo, com o tempo da resposta",
        "pedido": "Crie um quiz de múltipla escolha sobre o conteúdo do vídeo, indicando o tempo em que a resposta aparece.",
        "formato": '''{
  "perguntas": [{"pergunta": "texto", "opcoes": ["a", "b", "c", "d"], "correta": "texto da opção correta",
                 "explicacao": "por quê", "tempo": "mm:ss"}]
}''',
    },
    "transcricao": {
        "nome": "Transcrição",
        "icone": "📜",
        "descricao": "Transcrição com marcação de tempo (pode vir resumida em vídeos longos)",
        "pedido": "Transcreva o que é falado no vídeo, em trechos com o tempo de início de cada um.",
        "formato": '''{
  "idioma": "idioma falado",
  "trechos": [{"inicio": "mm:ss", "texto": "o que é falado"}]
}''',
    },
    "traduzir": {
        "nome": "Resumo em outro idioma",
        "icone": "🌐",
        "consulta": "Idioma (ex.: inglês, espanhol)",
        "descricao": "Resumo e pontos principais em outro idioma",
        "pedido": "Faça um resumo do vídeo e liste os pontos principais, tudo escrito no idioma: {consulta}.",
        "formato": '''{
  "idioma": "idioma usado", "resumo": "resumo no idioma pedido",
  "pontos": [{"inicio": "mm:ss", "texto": "ponto principal no idioma pedido"}]
}''',
    },
    "comparar": {
        "nome": "Comparar 2 vídeos",
        "icone": "⚖️",
        "consulta": "Link do segundo vídeo",
        "descricao": "Compara dois vídeos: semelhanças, diferenças e qual é melhor para quê",
        "pedido": "Compare este vídeo com o segundo vídeo: {consulta}. Mostre semelhanças, diferenças e para quem cada um é melhor.",
        "formato": '''{
  "resposta_objetiva": "conclusão em 1 ou 2 frases",
  "semelhancas": ["..."], "diferencas": [{"aspecto": "...", "video_1": "...", "video_2": "..."}],
  "recomendacao": "qual assistir e por quê"
}''',
    },
    "livre": {
        "nome": "Pedido livre",
        "icone": "✨",
        "consulta": "O que você quer que a IA faça com o vídeo",
        "descricao": "Qualquer pedido sobre o vídeo; a resposta vem com os momentos citados",
        "pedido": "{consulta}",
        "formato": '''{
  "resposta_objetiva": "resposta direta",
  "resposta_completa": "resposta detalhada em markdown",
  "momentos": [{"inicio": "mm:ss", "fim": "mm:ss", "descricao": "o que acontece"}]
}''',
    },
}

MODELO_PROMPT = """{url} \n\n— Análise do vídeo do YouTube acima. {pedido}

Responda SOMENTE com um bloco de código JSON válido, sem texto antes ou depois, neste formato:
```json
{formato}
```
Regras: use os tempos reais da linha do tempo do vídeo no formato mm:ss (ou hh:mm:ss em vídeos com mais de 1 hora). Não invente trechos; se algo não aparecer no vídeo, diga isso. Responda em português (a não ser que o pedido diga outro idioma)."""

# frases que indicam que a IA NÃO conseguiu ver o vídeo
SEM_ACESSO = re.compile(r"não (consigo|posso|tenho como) (assistir|acessar|ver|reproduzir)|não tenho acesso (ao|a esse) (conteúdo|vídeo)|"
                        r"can.?t (watch|access|view) (the |this )?video|unable to (watch|access)", re.I)


# ---------------------------------------------------------------- utilidades
def id_do_video(url):
    """Extrai o ID de 11 caracteres de qualquer formato de link do YouTube."""
    url = (url or "").strip()
    if re.fullmatch(r"[\w-]{11}", url):
        return url
    u = urlparse(url if "://" in url else "https://" + url)
    if u.netloc.endswith("youtu.be"):
        vid = u.path.lstrip("/").split("/")[0]
    elif "v" in parse_qs(u.query):
        vid = parse_qs(u.query)["v"][0]
    else:
        m = re.search(r"/(?:shorts|embed|live|v)/([\w-]{11})", u.path)
        vid = m.group(1) if m else ""
    return vid if re.fullmatch(r"[\w-]{11}", vid or "") else None


def eh_youtube(texto):
    m = re.search(r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?[^\s]*v=|shorts/|live/|embed/)|youtu\.be/)[\w-]{11}[^\s]*", texto or "")
    return m.group(0) if m else None


def para_segundos(t):
    """'1:05' -> 65 | '01:02:03' -> 3723 | '65s' -> 65 | '2m30s' -> 150 | 65 -> 65"""
    if t is None:
        return None
    if isinstance(t, (int, float)):
        return int(t)
    t = str(t).strip().lower().replace(",", ".")
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:\.\d+)?", t)
    if m:
        h, mi, s = m.groups()
        return int(h or 0) * 3600 + int(mi) * 60 + int(s)
    m = re.fullmatch(r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m(?:in)?)?\s*(?:(\d+(?:\.\d+)?)\s*s(?:eg)?)?", t)
    if m and any(m.groups()):
        h, mi, s = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + int(float(s or 0))
    if re.fullmatch(r"\d+(\.\d+)?", t):
        return int(float(t))
    return None


def formatar_tempo(seg):
    if seg is None:
        return ""
    h, r = divmod(int(seg), 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def link_tempo(vid, seg):
    return f"https://youtu.be/{vid}?t={int(seg)}" if seg is not None else f"https://youtu.be/{vid}"


CHAVES_TEMPO = ("inicio", "fim", "tempo")


def normalizar_tempos(obj, vid):
    """Percorre o JSON e, para cada inicio/fim/tempo, adiciona <chave>_seg e <chave>_link."""
    if isinstance(obj, list):
        return [normalizar_tempos(x, vid) for x in obj]
    if not isinstance(obj, dict):
        return obj
    novo = {}
    for k, v in obj.items():
        novo[k] = normalizar_tempos(v, vid)
        if k in CHAVES_TEMPO and isinstance(v, (str, int, float)):
            seg = para_segundos(v)
            if seg is not None:
                novo[f"{k}_seg"] = seg
                novo[f"{k}_link"] = link_tempo(vid, seg)
    return novo


# ---------- 🔁 "olhar de novo": a IA errou o momento ----------
def normalizar_errados(errados):
    """[{"inicio": "1:05"|65, "fim": ...}, ...] -> [(65, 80), ...] (só os válidos, sem repetir)."""
    out = []
    for e in errados or []:
        if not isinstance(e, dict):
            continue
        ini = para_segundos(e.get("inicio_seg", e.get("inicio")))
        fim = para_segundos(e.get("fim_seg", e.get("fim")))
        if ini is None:
            continue
        fim = fim if fim is not None and fim > ini else ini + 5
        if (ini, fim) not in out:
            out.append((ini, fim))
    return out[:20]


def consulta_olhar_de_novo(consulta, errados):
    """O pedido de "olhar de novo" na MESMA conversa: diz que os momentos anteriores não tinham o que buscamos e
    reafirma o que estamos procurando."""
    faixas = ", ".join(f"{formatar_tempo(a)}–{formatar_tempo(b)}" for a, b in normalizar_errados(errados))
    return (f"{consulta}\n\nATENÇÃO — OLHE DE NOVO: o(s) momento(s) que você indicou antes ({faixas}) NÃO têm o que "
            f"estamos procurando. Assista o vídeo outra vez, com atenção, do começo ao fim, e encontre o momento em que "
            f"realmente acontece ou é falado isto: {consulta}. Não repita esses momentos. Se isso de fato não existir no "
            f"vídeo, responda com \"encontrado\": false.")


def tirar_errados(dados, errados, folga=3):
    """Tira da resposta os momentos que caem num dos já recusados (a IA às vezes repete)."""
    faixas = normalizar_errados(errados)
    if not faixas or not isinstance(dados, dict):
        return dados

    def repetido(it):
        ini = it.get("inicio_seg", it.get("tempo_seg"))
        return ini is not None and any(a - folga <= ini <= max(b, a + folga) for a, b in faixas)
    for k in ("momentos", "trechos"):
        if isinstance(dados.get(k), list):
            dados[k] = [it for it in dados[k] if not (isinstance(it, dict) and repetido(it))]
            if k == "momentos" and not dados[k]:
                dados["encontrado"] = False
    return dados


def _itens_com_tempo(obj, caminho=""):
    """Gera (caminho, item) de todo dict que tenha inicio/tempo."""
    if isinstance(obj, list):
        for i, x in enumerate(obj):
            yield from _itens_com_tempo(x, f"{caminho}[{i}]")
    elif isinstance(obj, dict):
        if any(f"{k}_seg" in obj for k in ("inicio", "tempo")):
            yield caminho, obj
        for k, v in obj.items():
            if isinstance(v, (list, dict)):
                yield from _itens_com_tempo(v, f"{caminho}.{k}" if caminho else k)


def validar_tempos(dados, duracao_seg=None):
    """Confere se os tempos fazem sentido (fim depois do início, dentro da duração)."""
    problemas = []
    for caminho, it in _itens_com_tempo(dados):
        ini = it.get("inicio_seg", it.get("tempo_seg"))
        fim = it.get("fim_seg")
        if fim is not None and ini is not None and fim < ini:
            problemas.append(f"{caminho}: fim ({formatar_tempo(fim)}) antes do início ({formatar_tempo(ini)})")
        if duracao_seg:
            for nome, t in (("início", ini), ("fim", fim)):
                if t is not None and t > duracao_seg + 5:
                    problemas.append(f"{caminho}: {nome} {formatar_tempo(t)} depois do fim do vídeo ({formatar_tempo(duracao_seg)})")
    return problemas


# ---------------------------------------------------------------- markdown para exibir
def _t(it, k="inicio"):
    seg = it.get(f"{k}_seg")
    return f"[▶ {formatar_tempo(seg)}]({it.get(f'{k}_link')})" if seg is not None else ""


def _faixa(it):
    a, b = _t(it, "inicio") or _t(it, "tempo"), _t(it, "fim")
    return f"{a} – {b}" if a and b else a


def montar_markdown(tarefa, d):
    L = []
    if tarefa == "resumo":
        if d.get("titulo"):
            L.append(f"### {d['titulo']}" + (f" — {d['canal']}" if d.get("canal") else ""))
        if d.get("resumo_completo"):
            L += [d["resumo_completo"], ""]
        if d.get("topicos"):
            L.append("#### Tópicos")
            L += [f"- {_faixa(t)} **{t.get('titulo', '')}** — {t.get('resumo', '')}" for t in d["topicos"]]
        if d.get("pontos_chave"):
            L += ["", "#### Pontos-chave"] + [f"- {p}" for p in d["pontos_chave"]]
        if d.get("conclusao"):
            L += ["", f"**Conclusão:** {d['conclusao']}"]
    elif tarefa in ("pergunta", "livre"):
        if d.get("resposta_completa"):
            L += [d["resposta_completa"], ""]
        for k in ("trechos", "momentos"):
            if d.get(k):
                L.append("#### Trechos do vídeo")
                L += [f"- {_faixa(t)} {t.get('citacao') or t.get('descricao', '')}"
                      + (f" — *{t['explicacao']}*" if t.get("explicacao") else "") for t in d[k]]
        if d.get("confianca"):
            L += ["", f"*Confiança: {d['confianca']}*"]
    elif tarefa == "momentos":
        if not d.get("momentos"):
            L.append("Nenhum momento encontrado.")
        for m in d.get("momentos", []):
            L.append(f"- {_faixa(m)} **{m.get('descricao', '')}**" + (f"\n  > {m['citacao']}" if m.get("citacao") else ""))
    elif tarefa == "capitulos":
        L += [f"- {_t(c)} **{c.get('titulo', '')}**" + (f" — {c['resumo']}" if c.get("resumo") else "")
              for c in d.get("capitulos", [])]
        if d.get("capitulos"):
            L += ["", "**Para colar na descrição do YouTube:**", "```",
                  *[f"{formatar_tempo(c.get('inicio_seg'))} {c.get('titulo', '')}" for c in d["capitulos"]], "```"]
    elif tarefa == "cortes":
        for c in d.get("cortes", []):
            dur = (c.get("fim_seg") or 0) - (c.get("inicio_seg") or 0)
            L.append(f"- {_faixa(c)} ({dur}s) **{c.get('titulo', '')}**" + (f" · nota {c['nota']}" if c.get("nota") else "")
                     + (f"\n  > {c['gancho']}" if c.get("gancho") else "") + (f"\n  {c['motivo']}" if c.get("motivo") else ""))
    elif tarefa == "citacoes":
        L += [f"- {_t(c, 'tempo')} “{c.get('texto', '')}”" + (f" — **{c['quem']}**" if c.get("quem") else "")
              + (f"\n  *{c['contexto']}*" if c.get("contexto") else "") for c in d.get("citacoes", [])]
    elif tarefa == "fatos":
        icones = {"verdadeiro": "✅", "falso": "❌", "parcial": "⚠️", "nao": "❔"}
        for a in d.get("afirmacoes", []):
            v = (a.get("veredito") or "").lower()
            ic = next((i for k, i in icones.items() if k in v.replace("ã", "a")), "❔")
            fontes = ", ".join(f"[{f.get('nome') or 'fonte'}]({f['url']})" for f in a.get("fontes", []) if f.get("url"))
            L.append(f"- {_t(a, 'tempo')} {ic} **{a.get('afirmacao', '')}** — *{a.get('veredito', '')}*\n  {a.get('explicacao', '')}"
                     + (f"\n  Fontes: {fontes}" if fontes else ""))
    elif tarefa == "passos":
        if d.get("objetivo"):
            L += [f"**Objetivo:** {d['objetivo']}", ""]
        if d.get("materiais"):
            L += ["**Você vai precisar:**"] + [f"- {m}" for m in d["materiais"]] + [""]
        L += [f"{i}. {_t(p)} **{p.get('titulo', '')}** — {p.get('descricao', '')}" for i, p in enumerate(d.get("passos", []), 1)]
        if d.get("dicas"):
            L += ["", "**Dicas:**"] + [f"- {x}" for x in d["dicas"]]
    elif tarefa == "seo":
        L += ["**Títulos sugeridos:**"] + [f"- {t}" for t in d.get("titulos", [])]
        if d.get("descricao"):
            L += ["", "**Descrição:**", "```", d["descricao"], "```"]
        if d.get("tags"):
            L += ["", "**Tags:** " + ", ".join(d["tags"])]
        if d.get("hashtags"):
            L += ["", "**Hashtags:** " + " ".join(d["hashtags"])]
    elif tarefa == "quiz":
        for i, q in enumerate(d.get("perguntas", []), 1):
            L.append(f"{i}. **{q.get('pergunta', '')}** {_t(q, 'tempo')}")
            L += [f"   - {'✅ ' if o == q.get('correta') else ''}{o}" for o in q.get("opcoes", [])]
            if q.get("explicacao"):
                L.append(f"   *{q['explicacao']}*")
    elif tarefa == "transcricao":
        L += [f"- {_t(t)} {t.get('texto', '')}" for t in d.get("trechos", [])]
    elif tarefa == "traduzir":
        if d.get("resumo"):
            L += [d["resumo"], ""]
        L += [f"- {_t(p)} {p.get('texto', '')}" for p in d.get("pontos", [])]
    elif tarefa == "comparar":
        if d.get("semelhancas"):
            L += ["**Semelhanças:**"] + [f"- {x}" for x in d["semelhancas"]] + [""]
        if d.get("diferencas"):
            L += ["| Aspecto | Vídeo 1 | Vídeo 2 |", "|---|---|---|"]
            L += [f"| {x.get('aspecto', '')} | {x.get('video_1', '')} | {x.get('video_2', '')} |"
                  for x in d["diferencas"] if isinstance(x, dict)]
        if d.get("recomendacao"):
            L += ["", f"**Recomendação:** {d['recomendacao']}"]
    return "\n".join(L).strip()


def resposta_objetiva_de(tarefa, d):
    for k in ("resposta_objetiva", "resumo_curto", "resumo", "objetivo"):
        if isinstance(d.get(k), str) and d[k].strip():
            return d[k].strip()
    contagens = {"momentos": "momento(s) encontrado(s)", "capitulos": "capítulos", "cortes": "cortes sugeridos",
                 "citacoes": "frases marcantes", "afirmacoes": "afirmações verificadas", "passos": "passos",
                 "perguntas": "perguntas no quiz", "trechos": "trechos transcritos", "titulos": "títulos sugeridos"}
    for k, rot in contagens.items():
        if isinstance(d.get(k), list):
            return f"{len(d[k])} {rot}."
    return ""


# ---------------------------------------------------------------- analisador
class AnalisadorYouTube:
    def __init__(self, ia):
        self.ia = ia
        self.video_atual = None

    @staticmethod
    def tarefas():
        return {k: {c: v.get(c) for c in ("nome", "icone", "descricao", "consulta", "consulta_opcional")}
                for k, v in TAREFAS.items()}

    def montar_prompt(self, url, tarefa, consulta=""):
        t = TAREFAS[tarefa]
        if t.get("consulta") and not t.get("consulta_opcional") and not (consulta or "").strip():
            raise ValueError(f"A tarefa '{t['nome']}' precisa de: {t['consulta']}")
        pedido = t["pedido"].format(consulta=(consulta or "").strip()).strip()
        return MODELO_PROMPT.format(url=url, pedido=pedido, formato=t["formato"])

    def executar(self, url, tarefa="resumo", consulta="", nova_conversa=None, errados=None):
        """`errados` (🔁 olhar de novo): momentos que a IA indicou e NÃO eram o procurado — a pergunta vai na mesma
        conversa dizendo isso e reafirmando o que buscamos; esses momentos são tirados da resposta."""
        if tarefa not in TAREFAS:
            raise ValueError(f"Tarefa desconhecida: {tarefa}. Opções: {', '.join(TAREFAS)}")
        vid = id_do_video(url)
        if not vid:
            raise ValueError("Link do YouTube inválido.")
        url_limpa = f"https://www.youtube.com/watch?v={vid}"
        # outro vídeo -> conversa nova; mesmo vídeo -> continua (a IA já "assistiu")
        if nova_conversa or (nova_conversa is None and self.video_atual != vid):
            self.ia.nova_conversa()
        self.video_atual = vid

        errados = normalizar_errados(errados) if errados and consulta else []
        envio = consulta_olhar_de_novo(consulta, [{"inicio": a, "fim": b} for a, b in errados]) if errados else consulta
        prompt = self.montar_prompt(url_limpa, tarefa, envio)
        self.ia.log(f"Vídeo {vid}: {TAREFAS[tarefa]['nome']}" + (f" — {consulta}" if consulta else "")
                    + (f" (🔁 olhando de novo: {len(errados)} momento(s) recusado(s))" if errados else ""))
        r = self.ia.perguntar(f"[{tarefa}]{' 🔁' if errados else ''} {consulta or url_limpa}", texto_personalizado=prompt)

        bruto = r.get("json") or {}
        dados = normalizar_tempos(bruto, vid)
        if errados:
            dados = tirar_errados(dados, [{"inicio": a, "fim": b} for a, b in errados])
        duracao = para_segundos(dados.get("duracao")) if isinstance(dados.get("duracao"), str) else None
        problemas = validar_tempos(dados, duracao)
        texto_todo = (r.get("resposta_bruta_md") or "")
        sem_acesso = bool(SEM_ACESSO.search(texto_todo)) and not dados

        saida = {
            "video": {"id": vid, "url": url_limpa, "titulo": dados.get("titulo", ""), "canal": dados.get("canal", ""),
                      "duracao": dados.get("duracao", ""), "duracao_seg": duracao,
                      "miniatura": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"},
            "tarefa": tarefa,
            "consulta": consulta,
            "errados": [{"inicio": a, "fim": b} for a, b in errados],
            "resposta_objetiva": resposta_objetiva_de(tarefa, dados) or r.get("resposta_objetiva", ""),
            "markdown": montar_markdown(tarefa, dados) if dados else (r.get("resposta_completa") or texto_todo),
            "dados": dados,
            "fontes": r.get("fontes", []),
            "formato_respeitado": bool(dados),
            "problemas_tempo": problemas,
            "tentativas": r.get("tentativas", 1),
            "completa": r.get("completa", True),
            "data": r.get("data"),
            "resposta_bruta_md": texto_todo,
        }
        if sem_acesso:
            saida["aviso"] = "A IA do Google disse que não conseguiu acessar este vídeo."
        elif not dados:
            saida["aviso"] = "A IA não respondeu no formato JSON esperado; veja a resposta em texto."
        elif problemas:
            saida["aviso"] = "Alguns tempos parecem inconsistentes: " + "; ".join(problemas[:3])
        return saida
