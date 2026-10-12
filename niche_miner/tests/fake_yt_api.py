"""API do YouTube falsa para testes: substitui ``yt_api._urlopen`` e responde como a real (partes, lotes, cota, erros)."""
import io
import json
import threading
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

CHAVE = "AIzaFakeChaveDeTeste1234567890abcdefg"
AGORA = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
CUSTO = {"search": 100, "videos": 1, "channels": 1, "playlistItems": 1}


def uc(letra):
    return "UC" + letra * 22


def vid_id(n):
    return f"vid{n:08d}"[-11:]


def iso(dias_atras, hora=10):
    return (AGORA - timedelta(days=dias_atras)).replace(hour=hora, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def canal_item(cid, titulo, inscritos, views, n_videos, criado, handle="", pais="BR", ocultos=False, keywords="", descricao=""):
    return {"id": cid, "snippet": {"title": titulo, "description": descricao or f"Descrição de {titulo}", "customUrl": handle, "publishedAt": criado, "country": pais,
                                   "thumbnails": {"default": {"url": f"https://yt3.example/{cid}/d.jpg"}, "high": {"url": f"https://yt3.example/{cid}/h.jpg"}}},
            "statistics": {"viewCount": str(views), "subscriberCount": str(inscritos), "hiddenSubscriberCount": ocultos, "videoCount": str(n_videos)},
            "brandingSettings": {"channel": {"title": titulo, "keywords": keywords, "country": pais}},
            "contentDetails": {"relatedPlaylists": {"uploads": "UU" + cid[2:]}}}


def video_item(vid, titulo, canal_id, canal, dias_atras, views, likes, comentarios, duracao, tags=None, categoria="27", idioma="pt", ao_vivo="none", topicos=None,
               thumbs=("high", "medium", "default")):
    it = {"id": vid, "snippet": {"publishedAt": iso(dias_atras), "channelId": canal_id, "channelTitle": canal, "title": titulo, "description": f"Descrição completa de {titulo}. " * 3,
                                 "thumbnails": {n: {"url": f"https://i.ytimg.com/vi/{vid}/{n}.jpg", "width": 480, "height": 360} for n in thumbs},
                                 "tags": tags or [], "categoryId": categoria, "defaultAudioLanguage": idioma, "liveBroadcastContent": ao_vivo},
          "statistics": {"viewCount": str(views), "commentCount": str(comentarios)}, "contentDetails": {"duration": duracao}}
    if likes is not None:
        it["statistics"]["likeCount"] = str(likes)
    if topicos:
        it["topicDetails"] = {"topicCategories": [f"https://en.wikipedia.org/wiki/{t}" for t in topicos]}
    return it


class _Resp:
    def __init__(self, corpo, tipo="application/json"):
        self._corpo = corpo
        self.headers = {"Content-Type": tipo}

    def read(self):
        return self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_erro(url, codigo, mensagem, razao, status_txt="", detalhes=None):
    corpo = {"error": {"code": codigo, "message": mensagem, "errors": [{"message": mensagem, "domain": "youtube.quota", "reason": razao}], "status": status_txt}}
    if detalhes:
        corpo["error"]["details"] = [{"reason": detalhes}]
    return HTTPError(url, codigo, mensagem, {}, io.BytesIO(json.dumps(corpo).encode()))


class FakeYouTube:
    """Uso: ``mock.patch.object(yt_api, "_urlopen", fake)``. Guarda cada chamada em ``chamadas``."""

    def __init__(self, cota=10000, chave=CHAVE):
        self.chave, self.cota = chave, cota
        self.canais, self.videos, self.playlists = {}, {}, {}
        self.em_alta = {}                    # regionCode -> ids
        self.busca_ids = []                  # ids devolvidos por search.list type=video
        self.busca_canais = {}               # q -> channelId
        self.handles, self.usuarios = {}, {}
        self.miniaturas = {}                 # video_id -> [nomes disponíveis]
        self.chamadas = []
        self.falha_rede = False
        self.erro_forcado = None             # (recurso, HTTPError-like args) para simular falhas
        self._lock = threading.Lock()

    # ---- montagem
    def add_canal(self, item, handle=""):
        self.canais[item["id"]] = item
        if handle:
            self.handles[handle.lower()] = item["id"]
        self.playlists.setdefault("UU" + item["id"][2:], [])
        return item["id"]

    def add_video(self, item):
        self.videos[item["id"]] = item
        canal_id = item["snippet"]["channelId"]
        lista = self.playlists.setdefault("UU" + canal_id[2:], [])
        lista.append(item["id"])
        lista.sort(key=lambda i: self.videos[i]["snippet"]["publishedAt"], reverse=True)   # uploads: mais novo primeiro
        return item["id"]

    def por_recurso(self, recurso):
        return [p for r, p in self.chamadas if r == recurso]

    def unidades_gastas(self):
        return sum(CUSTO.get(r, 1) for r, _ in self.chamadas)

    # ---- transporte
    def __call__(self, req, timeout=20):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        u = urlparse(url)
        if u.hostname == "i.ytimg.com":
            partes = u.path.strip("/").split("/")
            vid, nome = partes[1], partes[2].rsplit(".", 1)[0]
            if self.falha_rede:
                raise URLError("sem rede")
            if nome in self.miniaturas.get(vid, []):
                return _Resp(b"\xff\xd8\xff" + nome.encode() * 10, "image/jpeg")
            raise HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
        recurso = u.path.rsplit("/", 1)[-1]
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        with self._lock:
            if self.falha_rede:
                raise URLError("sem rede")
            self.chamadas.append((recurso, {k: v for k, v in q.items() if k != "key"}))
            if q.get("key") != self.chave:
                raise _http_erro(url, 400, "API key not valid. Please pass a valid API key.", "badRequest", "INVALID_ARGUMENT", "API_KEY_INVALID")
            if self.erro_forcado and self.erro_forcado[0] == recurso:
                raise _http_erro(url, *self.erro_forcado[1:])
            custo = CUSTO.get(recurso, 1)
            if self.cota < custo:
                raise _http_erro(url, 403, "The request cannot be completed because you have exceeded your quota.", "quotaExceeded", "PERMISSION_DENIED")
            self.cota -= custo
            return _Resp(json.dumps(getattr(self, f"_r_{recurso}")(q, url)).encode())

    # ---- recursos
    def _partes(self, item, q, campos):
        pedidas = set((q.get("part") or "").split(","))
        return {k: v for k, v in item.items() if k == "id" or k not in campos or k in pedidas}

    def _r_channels(self, q, url):
        if "forHandle" in q:
            cid = self.handles.get(q["forHandle"].lower())
            return {"items": [{"id": cid}]} if cid else {}
        if "forUsername" in q:
            cid = self.usuarios.get(q["forUsername"].lower())
            return {"items": [{"id": cid}]} if cid else {}
        ids = q.get("id", "").split(",")
        if len(ids) > 50:
            raise _http_erro(url, 400, "Too many ids", "badRequest")
        itens = [self._partes(self.canais[i], q, ("snippet", "statistics", "brandingSettings", "contentDetails")) for i in ids if i in self.canais]
        if q.get("part") == "id":
            itens = [{"id": i["id"]} for i in itens]
        return {"items": itens}

    def _r_videos(self, q, url):
        campos = ("snippet", "statistics", "contentDetails", "topicDetails")
        if q.get("chart") == "mostPopular":
            regiao = q.get("regionCode", "US")
            if regiao == "ZZ" or (q.get("videoCategoryId") == "99"):
                raise _http_erro(url, 400, "The requested video chart is not supported or is not available.", "videoChartNotFound")
            ids = self.em_alta.get(regiao, [])
            if q.get("videoCategoryId"):
                ids = [i for i in ids if self.videos[i]["snippet"]["categoryId"] == q["videoCategoryId"]]
            return {"items": [self._partes(self.videos[i], q, campos) for i in ids][:int(q.get("maxResults", 5))]}
        if "maxResults" in q:
            raise _http_erro(url, 400, "The request specifies an invalid filter parameter.", "incompatibleParameters")   # maxResults só vale com chart
        ids = q.get("id", "").split(",")
        if len(ids) > 50:
            raise _http_erro(url, 400, "Too many ids", "badRequest")
        return {"items": [self._partes(self.videos[i], q, campos) for i in ids if i in self.videos]}

    def _r_search(self, q, url):
        if q.get("type") == "channel":
            cid = self.busca_canais.get(q.get("q", "").lower())
            return {"items": [{"id": {"kind": "youtube#channel", "channelId": cid}, "snippet": {"channelId": cid}}]} if cid else {"items": []}
        return {"items": [{"id": {"kind": "youtube#video", "videoId": i}, "snippet": {}} for i in self.busca_ids][:int(q.get("maxResults", 5))]}

    def _r_playlistItems(self, q, url):
        if q.get("playlistId") not in self.playlists:
            raise _http_erro(url, 404, "The playlist identified with the request's playlistId parameter cannot be found.", "playlistNotFound")
        ids = self.playlists[q["playlistId"]][:int(q.get("maxResults", 5))]
        return {"items": [{"contentDetails": {"videoId": i, "videoPublishedAt": self.videos[i]["snippet"]["publishedAt"]}} for i in ids]}


def mundo(cota=10000):
    """Três canais e vídeos com datas relativas a ``AGORA``. Devolve o falso já populado."""
    f = FakeYouTube(cota)
    a = f.add_canal(canal_item(uc("a"), "Canal Alfa", 8500, 400000, 40, "2025-04-14T10:00:00Z", handle="@alfa", keywords='estoicismo "vida diária" calma'), "@alfa")
    b = f.add_canal(canal_item(uc("b"), "Canal Beta", 120000, 9000000, 300, "2020-01-10T10:00:00Z", handle="@beta", pais="US"), "@beta")
    c = f.add_canal(canal_item(uc("c"), "Canal Gama", 0, 250000, 60, "2024-06-01T10:00:00Z", handle="@gama", ocultos=True), "@gama")
    f.usuarios["antigo"] = a
    f.busca_canais["nomecustom"] = b
    # (n, título, canal, dias atrás, views, likes, comentários, duração)
    dados = [
        (1, "Como ter um dia mais produtivo", a, "Canal Alfa", 3, 900, 60, 12, "PT9M"),
        (2, "12 lições estoicas para ouvir toda manhã", a, "Canal Alfa", 6, 9000, 700, 90, "PT10M"),
        (3, "Pare de esperar agora", a, "Canal Alfa", 13, 8000, 500, 60, "PT15M"),
        (4, "Sêneca em 45 segundos", a, "Canal Alfa", 20, 30000, 3000, 150, "PT45S"),
        (5, "Marco Aurélio explicado", a, "Canal Alfa", 27, 1500, 100, 10, "PT1H2M10S"),
        (6, "Como controlar suas emoções", a, "Canal Alfa", 34, 7000, 400, 40, "PT11M"),
        (7, "Documentário sobre Roma", b, "Canal Beta", 2, 500000, 30000, 4000, "PT35M"),
        (8, "Trailer curto de Roma", b, "Canal Beta", 4, 1200000, 60000, 5000, "PT58S"),
        (9, "Roma em 8 minutos", b, "Canal Beta", 9, 300000, 9000, 700, "PT8M"),
        (10, "Bastidores da série", b, "Canal Beta", 40, 90000, 2000, 300, "PT19M"),
        (11, "Live sobre filosofia", c, "Canal Gama", 1, 12000, None, 800, "PT3H", "27"),
        (12, "Filosofia rápida", c, "Canal Gama", 5, 150000, 8000, 900, "PT2M30S", "27"),
    ]
    for n, titulo, cid, cnome, dias, views, likes, com, dur, *cat in dados:
        f.add_video(video_item(vid_id(n), titulo, cid, cnome, dias, views, likes, com, dur, tags=["filosofia", "estoicismo"] if n <= 6 else ["roma"],
                               categoria=cat[0] if cat else ("24" if cid == b else "27"), ao_vivo="live" if n == 11 else "none", idioma="pt" if cid != b else "en",
                               topicos=["Philosophy", "Knowledge"] if n == 2 else None, thumbs=("maxres", "high", "default") if n == 2 else ("high", "default")))
    f.busca_ids = [vid_id(n) for n in (2, 4, 8, 12, 999, 1)]           # 999 não existe: some do resultado sem erro
    f.em_alta = {"BR": [vid_id(n) for n in (8, 7, 12, 4, 2)], "US": [vid_id(n) for n in (7, 9, 10)], "PT": []}
    f.miniaturas = {vid_id(2): ["maxresdefault", "hqdefault", "default"], vid_id(4): ["hqdefault", "default"], vid_id(1): ["default"]}
    return f
