#!/usr/bin/env python3
"""
Ferramentas baseadas na YouTube Data API v3 (aba "API do YouTube"): pesquisa avançada, em alta, comparar
concorrentes, analisar canal, analisar vídeo e histórico do canal.

Precisa de uma chave de API (gratuita, criada no Google Cloud). A cota padrão é de 10.000 unidades por dia:
``search.list`` custa 100, e ``videos.list``, ``channels.list`` e ``playlistItems.list`` custam 1. Por isso cada
função aqui devolve as ``unidades`` gastas, e a resolução de @handle usa ``channels.list?forHandle`` (1 unidade)
em vez de ``search.list`` (100).

Só biblioteca padrão (``urllib``). A chave nunca é gravada nem aparece em mensagem de erro.
"""

import json
import re
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen as _urlopen_real

BASE_PADRAO = "https://www.googleapis.com/youtube/v3"
CUSTO = {"search": 100, "videos": 1, "channels": 1, "playlistItems": 1}
LOTE = 50
MAX_QUANTIDADE = 50
PADRAO_QUANTIDADE = 25
DIAS_PADRAO = 7
ORDENS_BUSCA = ("relevance", "viewCount", "date", "rating")
DURACOES = ("any", "short", "medium", "long")


def _urlopen(req, timeout=20):
    """Ponto único de rede (trocado nos testes)."""
    return _urlopen_real(req, timeout=timeout)


class YTErro(Exception):
    """Erro mostrável ao usuário, já em português e sem a chave."""

    def __init__(self, mensagem, status=400, razao=""):
        super().__init__(mensagem)
        self.mensagem, self.status, self.razao = mensagem, status, razao


def _mascarar(texto, chave):
    t = str(texto or "")
    return t.replace(chave, "***") if chave else t


def _traduzir_http(codigo, corpo, chave):
    try:
        err = json.loads(corpo.decode("utf-8", "replace")).get("error", {}) or {}
    except (ValueError, AttributeError):
        err = {}
    msg = str(err.get("message") or "")
    razoes = [str(e.get("reason") or "") for e in (err.get("errors") or []) if isinstance(e, dict)]
    razoes += [str(d.get("reason") or "") for d in (err.get("details") or []) if isinstance(d, dict)]
    razao = razoes[0] if razoes else ""
    ref = (msg + " " + " ".join(razoes)).lower()
    if any(k in ref for k in ("quotaexceeded", "dailylimitexceeded", "ratelimitexceeded")):
        return YTErro("A cota diária da API do YouTube acabou. Ela reinicia à meia-noite (horário do Pacífico). Tente depois ou use outra chave.", 429, razao)
    if any(k in ref for k in ("api_key_invalid", "keyinvalid", "api key not valid", "api key expired")):
        return YTErro("Chave da API inválida. Confira se copiou a chave inteira.", 400, razao)
    if any(k in ref for k in ("accessnotconfigured", "service_disabled", "has not been used", "is disabled")):
        return YTErro("A YouTube Data API v3 não está ativada no projeto dessa chave. Ative em console.cloud.google.com, em APIs e serviços.", 403, razao)
    if "videochartnotfound" in ref:
        return YTErro("O YouTube não tem lista de vídeos em alta para esse país ou categoria.", 400, razao)
    if codigo == 404 or any(k in ref for k in ("notfound", "not found")):
        return YTErro("Não encontrei isso no YouTube (removido, privado ou identificador errado).", 404, razao)
    if codigo == 403:
        return YTErro("A chave foi bloqueada para este uso (restrição de IP ou de site na chave). Ajuste no console do Google.", 403, razao)
    return YTErro(f"Erro da API do YouTube ({codigo}): {_mascarar(msg, chave) or 'sem detalhes'}", 502 if codigo >= 500 else 400, razao)


class Cliente:
    """Um cliente por requisição: guarda a chave e soma as unidades de cota gastas."""

    def __init__(self, chave, base=None, timeout=20):
        chave = str(chave or "").strip()
        if not chave:
            raise YTErro("Informe a chave da API do YouTube.", 400, "sem_chave")
        if re.search(r"\s", chave) or len(chave) < 10:
            raise YTErro("Essa chave não parece válida (sem espaços e com o tamanho completo).", 400, "chave_formato")
        self.chave, self.base, self.timeout = chave, (base or BASE_PADRAO).rstrip("/"), timeout
        self.unidades = 0
        self._lock = threading.Lock()

    def get(self, recurso, **params):
        limpos = {k: (",".join(v) if isinstance(v, (list, tuple)) else v) for k, v in params.items() if v not in (None, "", [], ())}
        limpos["key"] = self.chave
        url = f"{self.base}/{recurso}?{urlencode(limpos)}"
        try:
            with _urlopen(Request(url, headers={"Accept": "application/json"}), timeout=self.timeout) as r:
                bruto = r.read()
        except HTTPError as e:
            try:
                corpo = e.read()
            except Exception:
                corpo = b""
            raise _traduzir_http(e.code, corpo, self.chave) from None
        except (URLError, TimeoutError, OSError):
            raise YTErro("Não consegui falar com a API do YouTube (sem conexão ou tempo esgotado).", 502, "rede") from None
        try:
            dados = json.loads(bruto.decode("utf-8"))
        except ValueError:
            raise YTErro("A API do YouTube devolveu uma resposta que não entendi.", 502, "resposta") from None
        with self._lock:
            self.unidades += CUSTO.get(recurso, 1)
        return dados


# --------------------------------------------------------------------------
# Entradas: links, IDs e handles
# --------------------------------------------------------------------------

def extrair_video_id(texto):
    t = str(texto or "").strip()
    if not t:
        raise ValueError("Cole o link ou o ID do vídeo.")
    if re.fullmatch(r"[\w-]{11}", t):
        return t
    u = urlparse(t if re.match(r"^https?://", t, re.I) else "https://" + t.lstrip("/"))
    host = (u.hostname or "").lower()
    partes = [p for p in u.path.split("/") if p]
    if host in ("youtu.be", "www.youtu.be") and partes and re.fullmatch(r"[\w-]{11}", partes[0]):
        return partes[0]
    if host.endswith("youtube.com"):
        v = parse_qs(u.query).get("v", [""])[0]
        if re.fullmatch(r"[\w-]{11}", v):
            return v
        if len(partes) >= 2 and partes[0] in ("shorts", "embed", "live", "v") and re.fullmatch(r"[\w-]{11}", partes[1]):
            return partes[1]
    raise ValueError("Não achei o ID do vídeo nesse link. Use youtube.com/watch?v=..., youtu.be/... ou /shorts/...")


def interpretar_canal(texto):
    """Devolve (tipo, valor): id, handle, usuario ou custom."""
    t = str(texto or "").strip()
    if not t:
        raise ValueError("Informe o canal (ID, @handle ou link).")
    if re.fullmatch(r"UC[\w-]{22}", t):
        return "id", t
    if re.fullmatch(r"@[^\s/?#]+", t):
        return "handle", t
    if not re.match(r"^https?://", t, re.I):
        if re.match(r"^(www\.|m\.)?youtube\.com/", t, re.I):
            t = "https://" + t
        elif re.fullmatch(r"[^\s/?#@.]+", t):
            return "handle", "@" + t
        else:
            raise ValueError("Não entendi esse canal. Use o ID (UC...), o @handle ou o link do canal.")
    u = urlparse(t)
    if not (u.hostname or "").lower().endswith("youtube.com"):
        raise ValueError("Isso não parece um link do YouTube.")
    partes = [unquote(p) for p in u.path.split("/") if p]
    if partes and partes[0].startswith("@"):
        return "handle", partes[0]
    if len(partes) >= 2 and partes[0] == "channel" and re.fullmatch(r"UC[\w-]{22}", partes[1]):
        return "id", partes[1]
    if len(partes) >= 2 and partes[0] == "c":
        return "custom", partes[1]
    if len(partes) >= 2 and partes[0] == "user":
        return "usuario", partes[1]
    raise ValueError("Não achei o canal nesse link. Use youtube.com/@nome ou youtube.com/channel/UC...")


def resolver_canal(cli, texto):
    """(channel_id, aviso). @handle e usuário custam 1 unidade; nome personalizado (/c/) só resolve por busca (100)."""
    tipo, valor = interpretar_canal(texto)
    if tipo == "id":
        return valor, ""
    aviso = ""
    if tipo == "handle":
        r = cli.get("channels", part="id", forHandle=valor)
        if r.get("items"):
            return r["items"][0]["id"], ""
    elif tipo == "usuario":
        r = cli.get("channels", part="id", forUsername=valor)
        if r.get("items"):
            return r["items"][0]["id"], ""
    r = cli.get("search", part="snippet", type="channel", q=valor.lstrip("@"), maxResults=1)
    itens = r.get("items") or []
    cid = ((itens[0].get("id") or {}).get("channelId") or (itens[0].get("snippet") or {}).get("channelId")) if itens else ""
    if not cid:
        raise YTErro(f"Não encontrei o canal “{valor}”.", 404, "canal_nao_encontrado")
    return cid, f"Achei “{valor}” por busca de nome (100 unidades); confira se é o canal certo."


# --------------------------------------------------------------------------
# Normalização
# --------------------------------------------------------------------------

def _int(v):
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None


def _dt(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _agora(agora):
    a = agora or datetime.now(timezone.utc)
    return a if a.tzinfo else a.replace(tzinfo=timezone.utc)


_RE_DURACAO = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def duracao_segundos(iso):
    """ISO 8601 (PT1H2M10S) para segundos; ``None`` se não for válida."""
    m = _RE_DURACAO.match(str(iso or ""))
    if not m or not any(m.groups()):
        return 0 if str(iso or "") == "P0D" else None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _melhor_thumb(thumbs):
    ordem = ("maxres", "standard", "high", "medium", "default")
    for nome in ordem:
        t = (thumbs or {}).get(nome)
        if isinstance(t, dict) and t.get("url"):
            return t["url"]
    return ""


def _lista_thumbs(thumbs):
    saida = []
    for nome in ("maxres", "standard", "high", "medium", "default"):
        t = (thumbs or {}).get(nome)
        if isinstance(t, dict) and t.get("url"):
            saida.append({"nome": nome, "url": t["url"], "largura": _int(t.get("width")), "altura": _int(t.get("height"))})
    return saida


def normalizar_video(item, agora=None, descricao_max=300):
    agora = _agora(agora)
    sn, st, cd = item.get("snippet") or {}, item.get("statistics") or {}, item.get("contentDetails") or {}
    pub = _dt(sn.get("publishedAt"))
    views, likes, coments = _int(st.get("viewCount")), _int(st.get("likeCount")), _int(st.get("commentCount"))
    idade = max(0, (agora - pub).days) if pub else None
    if views and (likes is not None or coments is not None):
        engaj = round(((likes or 0) + (coments or 0)) / views * 100, 2)
    else:
        engaj = None
    vid = item.get("id") if isinstance(item.get("id"), str) else ""
    desc = str(sn.get("description") or "")
    return {
        "id": vid, "url": f"https://www.youtube.com/watch?v={vid}" if vid else "", "titulo": str(sn.get("title") or ""),
        "canal_id": str(sn.get("channelId") or ""), "canal": str(sn.get("channelTitle") or ""),
        "publicado": pub.strftime("%Y-%m-%dT%H:%M:%SZ") if pub else "", "data": pub.strftime("%Y-%m-%d") if pub else "", "idade_dias": idade,
        "views": views, "likes": likes, "comentarios": coments, "engajamento": engaj,
        "views_dia": round(views / max(idade, 1), 1) if views is not None and idade is not None else None,
        "duracao_seg": duracao_segundos(cd.get("duration")), "tags": [str(t) for t in (sn.get("tags") or [])][:40],
        "thumb": _melhor_thumb(sn.get("thumbnails")), "descricao": desc[:descricao_max] if descricao_max else desc,
        "categoria_id": str(sn.get("categoryId") or ""), "idioma": str(sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or ""),
        "ao_vivo": str(sn.get("liveBroadcastContent") or "none") != "none",
    }


def _palavras_chave(texto):
    if not texto:
        return []
    achadas = re.findall(r'"([^"]+)"|(\S+)', str(texto))
    return [a or b for a, b in achadas][:40]


def normalizar_canal(item):
    sn, st, br = item.get("snippet") or {}, item.get("statistics") or {}, (item.get("brandingSettings") or {}).get("channel") or {}
    cid = str(item.get("id") or "")
    custom = str(sn.get("customUrl") or "")
    ocultos = bool(st.get("hiddenSubscriberCount"))
    return {
        "id": cid, "titulo": str(sn.get("title") or br.get("title") or ""), "handle": custom if custom.startswith("@") else "",
        "url": f"https://www.youtube.com/{custom}" if custom.startswith("@") else f"https://www.youtube.com/channel/{cid}",
        "descricao": str(sn.get("description") or br.get("description") or ""), "pais": str(sn.get("country") or br.get("country") or ""),
        "criado_em": str(sn.get("publishedAt") or ""), "inscritos": None if ocultos else _int(st.get("subscriberCount")), "inscritos_ocultos": ocultos,
        "views_totais": _int(st.get("viewCount")), "n_videos": _int(st.get("videoCount")),
        "uploads_playlist": str(((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads") or ""),
        "thumb": _melhor_thumb(sn.get("thumbnails")), "palavras_chave": _palavras_chave(br.get("keywords")),
    }


def _mediana(v):
    v = [x for x in v if x is not None]
    return statistics.median(v) if v else None


def _media(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def metricas_canal(canal, agora=None):
    """Métricas derivadas só dos números do canal (channels.list)."""
    agora = _agora(agora)
    ins, tot, n = canal.get("inscritos"), canal.get("views_totais"), canal.get("n_videos")
    criado = _dt(canal.get("criado_em"))
    dias = max(0, (agora - criado).days) if criado else None
    semanas = max(dias / 7, 1) if dias is not None else None       # canal com menos de 1 semana conta como 1
    return {
        "idade_dias": dias, "views_por_video": round(tot / n) if tot is not None and n else None,
        "inscritos_por_video": round(ins / n, 1) if ins is not None and n else None,
        "videos_por_semana": round(n / semanas, 2) if n is not None and semanas else None,
        "inscritos_por_view_pct": round(ins / tot * 100, 3) if ins is not None and tot else None,
    }


def metricas_recentes(videos, agora=None):
    """Métricas dos últimos vídeos lidos (frequência real de postagem, mediana, tração, engajamento)."""
    agora = _agora(agora)
    views = [v["views"] for v in videos if v.get("views") is not None]
    datas = sorted(d for d in (_dt(v.get("publicado")) for v in videos) if d)
    intervalo = ((datas[-1] - datas[0]).total_seconds() / 86400 / (len(datas) - 1)) if len(datas) >= 2 else None
    return {
        "n": len(videos), "mediana_views": _mediana(views), "media_views": round(_media(views)) if views else None,
        "engajamento_medio": round(_media([v["engajamento"] for v in videos]), 2) if _media([v["engajamento"] for v in videos]) is not None else None,
        "intervalo_medio_dias": round(intervalo, 1) if intervalo else None,
        "videos_por_semana": round(7 / intervalo, 2) if intervalo else None,
        "dias_desde_o_ultimo": max(0, (agora - datas[-1]).days) if datas else None,
    }


def tracao(mediana, inscritos):
    return round(mediana / inscritos, 4) if mediana is not None and inscritos else None


# --------------------------------------------------------------------------
# Buscas em lote
# --------------------------------------------------------------------------

def _lotes(seq, n=LOTE):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def buscar_videos(cli, ids, agora=None, descricao_max=300, partes="snippet,statistics,contentDetails"):
    """Vídeos na ordem dos ``ids`` (o que o YouTube não devolve some sem erro: privado ou removido)."""
    ids = [i for i in dict.fromkeys(ids) if i]
    por_id = {}
    for lote in _lotes(ids):
        for it in cli.get("videos", part=partes, id=lote).get("items", []):
            por_id[it.get("id")] = normalizar_video(it, agora, descricao_max)
    return [por_id[i] for i in ids if i in por_id]


def buscar_canais(cli, ids, partes="snippet,statistics"):
    ids = [i for i in dict.fromkeys(ids) if i]
    saida = {}
    for lote in _lotes(ids):
        for it in cli.get("channels", part=partes, id=lote).get("items", []):
            c = normalizar_canal(it)
            saida[c["id"]] = c
    return saida


def ultimos_videos(cli, canal, n, agora=None):
    uploads = canal.get("uploads_playlist")
    if not uploads:
        return []
    r = cli.get("playlistItems", part="contentDetails", playlistId=uploads, maxResults=max(1, min(n, LOTE)))
    ids = [(it.get("contentDetails") or {}).get("videoId") for it in r.get("items", [])]
    return buscar_videos(cli, ids, agora)


# --------------------------------------------------------------------------
# 1. Pesquisa avançada
# --------------------------------------------------------------------------

def _codigo(v, tam_min, tam_max=None):
    s = str(v or "").strip()
    return s if re.fullmatch(rf"[A-Za-z]{{{tam_min},{tam_max or tam_min}}}", s) else ""


def _data(v):
    s = str(v or "").strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if s else None
    except ValueError:
        raise ValueError(f"Data inválida: “{s}”. Use o formato AAAA-MM-DD.")


def normalizar_pesquisa(dados, agora=None):
    agora = _agora(agora)
    d = dados or {}
    q = re.sub(r"\s+", " ", str(d.get("q") or "")).strip()[:200]
    de, ate = _data(d.get("de")), _data(d.get("ate"))
    assumiu = de is None and ate is None
    if assumiu:
        de = (agora - timedelta(days=DIAS_PADRAO)).date()
    if de and ate and de > ate:
        raise ValueError("A data inicial vem depois da data final.")
    try:
        quantidade = max(1, min(MAX_QUANTIDADE, int(d.get("quantidade") or PADRAO_QUANTIDADE)))
    except (TypeError, ValueError):
        quantidade = PADRAO_QUANTIDADE
    formato = d.get("formato") if d.get("formato") in ("todos", "longos", "shorts") else "todos"
    duracao = d.get("duracao") if d.get("duracao") in DURACOES else "any"
    return {
        "q": q, "modo": "busca" if q else "em_alta", "pais": _codigo(d.get("pais"), 2).upper(), "idioma": _codigo(d.get("idioma"), 2, 3).lower(),
        "duracao": duracao, "formato": formato, "quantidade": quantidade, "ordem": d.get("ordem") if d.get("ordem") in ORDENS_BUSCA else "viewCount",
        "de": de.isoformat() if de else "", "ate": ate.isoformat() if ate else "", "assumiu_7_dias": assumiu,
        "publicado_depois": f"{de.isoformat()}T00:00:00Z" if de else "", "publicado_antes": f"{ate.isoformat()}T23:59:59Z" if ate else "",
    }


def _faixa_duracao(seg, duracao):
    """Mesma definição da API: short < 4 min, medium 4 a 20 min, long > 20 min."""
    if duracao == "any" or seg is None:
        return True
    return {"short": seg < 240, "medium": 240 <= seg <= 1200, "long": seg > 1200}[duracao]


def _idioma_compativel(v, idioma):
    """Só descarta quem declara outro idioma; vídeo sem idioma declarado fica."""
    return not idioma or not v.get("idioma") or v["idioma"].lower().startswith(idioma)


def pesquisa_avancada(cli, dados, agora=None):
    p = normalizar_pesquisa(dados, agora)
    avisos = []
    if p["modo"] == "busca":
        duracao_api = "short" if p["formato"] == "shorts" and p["duracao"] == "any" else p["duracao"]
        r = cli.get("search", part="snippet", type="video", q=p["q"], maxResults=p["quantidade"], order=p["ordem"],
                    publishedAfter=p["publicado_depois"], publishedBefore=p["publicado_antes"], regionCode=p["pais"],
                    relevanceLanguage=p["idioma"], videoDuration=duracao_api if duracao_api != "any" else "")
        ids = [(it.get("id") or {}).get("videoId") for it in r.get("items", [])]
        videos = buscar_videos(cli, ids, agora)
    else:
        pais = p["pais"] or "US"
        r = cli.get("videos", part="snippet,statistics,contentDetails", chart="mostPopular", regionCode=pais, maxResults=MAX_QUANTIDADE)
        todos = [normalizar_video(it, agora) for it in r.get("items", [])]
        de, ate = _dt(p["publicado_depois"]), _dt(p["publicado_antes"])
        videos = []
        for v in todos:
            pub = _dt(v["publicado"])
            if pub and ((de and pub < de) or (ate and pub > ate)):
                continue
            if not _faixa_duracao(v["duracao_seg"], p["duracao"]) or not _idioma_compativel(v, p["idioma"]):
                continue
            videos.append(v)
        videos = videos[:p["quantidade"]]
        p["pais_usado"] = pais
        avisos.append(f"Sem palavra-chave: mostrei os vídeos em alta de {pais} e apliquei seus filtros (a API não filtra em alta por data, duração ou idioma).")
    canais = buscar_canais(cli, [v["canal_id"] for v in videos])
    return {"params": p, "videos": videos, "canais": canais, "avisos": avisos, "unidades": cli.unidades}


# --------------------------------------------------------------------------
# 2. Em alta
# --------------------------------------------------------------------------

def em_alta(cli, pais, categoria="", agora=None):
    pais = _codigo(pais, 2).upper() or "US"
    cat = str(categoria or "").strip()
    cat = cat if re.fullmatch(r"\d{1,3}", cat) else ""
    r = cli.get("videos", part="snippet,statistics,contentDetails", chart="mostPopular", regionCode=pais, videoCategoryId=cat, maxResults=MAX_QUANTIDADE)
    videos = [normalizar_video(it, agora) for it in r.get("items", [])]
    canais = buscar_canais(cli, [v["canal_id"] for v in videos])
    avisos = [] if videos else ["O YouTube não devolveu vídeos em alta para essa combinação."]
    return {"pais": pais, "categoria": cat, "videos": videos, "canais": canais, "avisos": avisos, "unidades": cli.unidades}


# --------------------------------------------------------------------------
# 3. Comparar concorrentes
# --------------------------------------------------------------------------

_LINHAS_COMPARACAO = [
    ("inscritos", "Inscritos", "canal", "inscritos"), ("views_totais", "Views totais", "canal", "views_totais"),
    ("n_videos", "Vídeos publicados", "canal", "n_videos"), ("views_por_video", "Views por vídeo (total ÷ vídeos)", "metricas", "views_por_video"),
    ("inscritos_por_video", "Inscritos por vídeo", "metricas", "inscritos_por_video"), ("videos_por_semana_vida", "Vídeos por semana (vida toda)", "metricas", "videos_por_semana"),
    ("videos_por_semana", "Vídeos por semana (últimos vídeos)", "recentes", "videos_por_semana"), ("mediana_views", "Mediana de views (últimos vídeos)", "recentes", "mediana_views"),
    ("media_views", "Média de views (últimos vídeos)", "recentes", "media_views"), ("tracao", "Tração (mediana ÷ inscritos)", "recentes", "tracao"),
    ("engajamento_medio", "Engajamento médio (%)", "recentes", "engajamento_medio"),
]


def montar_comparacao(a, b):
    """Linhas lado a lado. ``maior`` só diz quem tem o número maior, sem julgar se isso é melhor."""
    linhas = []
    for chave, rotulo, fonte, campo in _LINHAS_COMPARACAO:
        va, vb = (x[fonte].get(campo) for x in (a, b))
        maior = None if va is None or vb is None else ("empate" if va == vb else ("a" if va > vb else "b"))
        linhas.append({"chave": chave, "rotulo": rotulo, "a": va, "b": vb, "maior": maior})
    return linhas


def _perfil(canal, videos, agora):
    rec = metricas_recentes(videos, agora)
    rec["tracao"] = tracao(rec["mediana_views"], canal.get("inscritos"))
    return {"canal": canal, "metricas": metricas_canal(canal, agora), "recentes": rec, "videos": videos}


def comparar(cli, a, b, agora=None, n=10):
    with ThreadPoolExecutor(max_workers=2) as ex:                     # resolve os dois ao mesmo tempo
        (ida, av_a), (idb, av_b) = list(ex.map(lambda t: resolver_canal(cli, t), [a, b]))
    if ida == idb:
        raise ValueError("Informe dois canais diferentes.")
    canais = buscar_canais(cli, [ida, idb], "snippet,statistics,contentDetails")
    for cid in (ida, idb):
        if cid not in canais:
            raise YTErro("Um dos canais não foi encontrado.", 404, "canal_nao_encontrado")
    with ThreadPoolExecutor(max_workers=2) as ex:
        vids = list(ex.map(lambda cid: ultimos_videos(cli, canais[cid], n, agora), [ida, idb]))
    pa, pb = _perfil(canais[ida], vids[0], agora), _perfil(canais[idb], vids[1], agora)
    return {"a": pa, "b": pb, "comparacao": montar_comparacao(pa, pb), "avisos": [x for x in (av_a, av_b) if x], "unidades": cli.unidades}


# --------------------------------------------------------------------------
# 4. Analisar canal
# --------------------------------------------------------------------------

def analisar_canal(cli, texto, agora=None):
    cid, aviso = resolver_canal(cli, texto)
    canais = buscar_canais(cli, [cid], "snippet,statistics,brandingSettings,contentDetails")
    if cid not in canais:
        raise YTErro("Canal não encontrado.", 404, "canal_nao_encontrado")
    c = canais[cid]
    avisos = [aviso] if aviso else []
    if c["inscritos_ocultos"]:
        avisos.append("Esse canal esconde o número de inscritos: as métricas que dependem dele ficam em branco.")
    return {"canal": c, "metricas": metricas_canal(c, agora), "avisos": avisos, "unidades": cli.unidades}


# --------------------------------------------------------------------------
# 5. Analisar vídeo
# --------------------------------------------------------------------------

def _nome_topico(url):
    ultimo = unquote(str(url).rstrip("/").rsplit("/", 1)[-1])
    return ultimo.replace("_", " ")


def analisar_video(cli, texto, agora=None):
    vid = extrair_video_id(texto)
    r = cli.get("videos", part="snippet,statistics,contentDetails,topicDetails", id=vid)
    itens = r.get("items") or []
    if not itens:
        raise YTErro("Não encontrei esse vídeo (privado, removido ou ID errado).", 404, "video_nao_encontrado")
    it = itens[0]
    v = normalizar_video(it, agora, descricao_max=0)
    v["thumbs"] = _lista_thumbs((it.get("snippet") or {}).get("thumbnails"))
    v["topicos"] = [_nome_topico(u) for u in ((it.get("topicDetails") or {}).get("topicCategories") or [])][:12]
    canais = buscar_canais(cli, [v["canal_id"]])
    canal = canais.get(v["canal_id"])
    v["inscritos_do_canal"] = canal["inscritos"] if canal else None
    v["views_sobre_inscritos"] = round(v["views"] / canal["inscritos"], 2) if canal and canal["inscritos"] and v["views"] is not None else None
    return {"video": v, "canal": canal, "avisos": [], "unidades": cli.unidades}


# --------------------------------------------------------------------------
# 6. Histórico do canal
# --------------------------------------------------------------------------

def historico(cli, texto, n=30, agora=None):
    cid, aviso = resolver_canal(cli, texto)
    canais = buscar_canais(cli, [cid], "snippet,statistics,contentDetails")
    if cid not in canais:
        raise YTErro("Canal não encontrado.", 404, "canal_nao_encontrado")
    c = canais[cid]
    if not c["uploads_playlist"]:
        raise YTErro("Esse canal não tem lista de envios pública.", 404, "sem_uploads")
    videos = ultimos_videos(cli, c, max(1, min(int(n or 30), LOTE)), agora)
    rec = metricas_recentes(videos, agora)
    rec["tracao"] = tracao(rec["mediana_views"], c.get("inscritos"))
    return {"canal": c, "videos": videos, "recentes": rec, "avisos": [aviso] if aviso else [], "unidades": cli.unidades}


# --------------------------------------------------------------------------
# Miniatura em melhor resolução
# --------------------------------------------------------------------------

RESOLUCOES = ("maxresdefault", "sddefault", "hqdefault", "mqdefault", "default")
HOST_IMAGENS = "https://i.ytimg.com/vi"


def baixar_miniatura(video_id, abrir=None):
    """Tenta da maior resolução para a menor e devolve (bytes, tipo, nome). Só busca em i.ytimg.com com um ID de 11 caracteres."""
    if not re.fullmatch(r"[\w-]{11}", str(video_id or "")):
        raise ValueError("ID de vídeo inválido.")
    abrir = abrir or _urlopen
    for nome in RESOLUCOES:
        try:
            with abrir(Request(f"{HOST_IMAGENS}/{video_id}/{nome}.jpg"), timeout=15) as r:
                corpo = r.read()
                tipo = r.headers.get("Content-Type", "image/jpeg") if hasattr(r, "headers") else "image/jpeg"
            if corpo and tipo.startswith("image/"):
                return corpo, tipo, nome
        except HTTPError as e:
            if e.code == 404:
                continue
            raise YTErro("Não consegui baixar a miniatura.", 502, "miniatura") from None
        except (URLError, TimeoutError, OSError):
            raise YTErro("Não consegui baixar a miniatura (sem conexão).", 502, "rede") from None
    raise YTErro("O YouTube não tem miniatura para esse vídeo.", 404, "sem_miniatura")
