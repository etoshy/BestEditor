"""
animepexels_client.py
======================

Cliente pro banco de vídeo LOCAL "Anime Pexels Local" — diferente dos
outros 5 provedores deste toolkit (todos remotos, via scraping de
navegador ou API pública), esse roda na PRÓPRIA MÁQUINA do usuário (um
`app.py` Flask local, por padrão em http://localhost:5000) e serve
clipes de anime já processados/indexados localmente.

Não usa Selenium — não precisa, é uma API JSON HTTP simples servida
localmente. Só depende de `requests`, igual aos clientes de API oficial
(Pexels/Pixabay).

IMPORTANTE: os termos de busca desse banco são em INGLÊS (confirmado
pelo usuário) — diferente disso, segue o mesmo padrão dos outros
clientes do toolkit (`search_all()` / `download_video()` / `to_dict()`),
pra plugar direto no `ClientFactory` do site sem tratamento especial.

Baseado no cliente de referência `anime_pexels_client.py` documentado
em API.md do projeto original.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import requests

DEFAULT_BASE_URL = "http://localhost:5000"
DEFAULT_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 120



def varios(valor: Any) -> List[str]:
    """"Naruto | Death Note" -> ["Naruto", "Death Note"] (o site separa várias obras/personagens com |)."""
    if not valor:
        return []
    itens = valor if isinstance(valor, (list, tuple)) else str(valor).split("|")
    out = []
    for x in itens:
        x = str(x).strip()
        if x and x not in out:
            out.append(x)
    return out

class AnimePexelsClientError(Exception):
    """Erro genérico do cliente do Anime Pexels Local (conexão recusada,
    servidor fora do ar, clipe não encontrado, etc.)."""


@dataclass
class AnimePexelsVideo:
    id: str
    title: str
    description: str
    url: str  # identificador sintético "animepexels://clip/<id>" — ver get_video_by_url()
    clip_url: str  # URL ABSOLUTA já resolvida (base_url + caminho relativo da API)
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    orientation: Optional[str] = None
    resolution_name: Optional[str] = None
    anime_name: Optional[str] = None
    episode_number: Optional[int] = None
    tags: List[str] = field(default_factory=list)
    premium: bool = False  # nunca é premium (acervo local do usuário) — campo só por
    # compatibilidade com o resto do toolkit, que checa esse atributo em alguns lugares.
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "thumbnail": self.thumbnail_url,
            # já é o vídeo de verdade, tocável direto (acervo local do
            # próprio usuário) — alimenta o Monitor de Origem do editor
            # sem nenhuma limitação (diferente do Pixabay, que não tem
            # isso disponível na busca).
            "video_preview_url": self.clip_url,
            "duration": self.duration_seconds,
            "orientation": self.orientation,
            "resolution_name": self.resolution_name,
            "anime_name": self.anime_name,
            "episode_number": self.episode_number,
            "tags": self.tags,
        }


def _full_url(base_url: str, relative_or_absolute: Optional[str]) -> Optional[str]:
    if not relative_or_absolute:
        return None
    if relative_or_absolute.startswith("http://") or relative_or_absolute.startswith("https://"):
        return relative_or_absolute
    return base_url + relative_or_absolute


# Catálogos do MESMO servidor (anime-pexels-local >= v62): o de anime em
# /api/... e o de filmes e séries em /movie/api/... (mesmas rotas e filtros).
CATALOGOS = {
    "anime": {"prefixo": "", "esquema": "animepexels", "nome": "Anime Pexels"},
    "movie": {"prefixo": "/movie", "esquema": "moviepexels", "nome": "Filmes e Séries Pexels"},
}


class AnimePexelsClient:
    catalog = "anime"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        session: Optional[requests.Session] = None,
        timeout: int = DEFAULT_TIMEOUT,
        catalog: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        if catalog:
            if catalog not in CATALOGOS:
                raise AnimePexelsClientError(f"Catálogo desconhecido: {catalog!r} (use 'anime' ou 'movie').")
            self.catalog = catalog
        self.prefixo = CATALOGOS[self.catalog]["prefixo"]
        self.esquema = CATALOGOS[self.catalog]["esquema"]

    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        # as rotas são sempre "/api/..."; o catálogo de filmes fica em /movie/api/...
        if path.startswith("/api/"):
            path = self.prefixo + path
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise AnimePexelsClientError(
                f"Não consegui conectar em {self.base_url} — o app.py do "
                f"anime-pexels-local está rodando? ({exc})"
            ) from exc
        if resp.status_code == 404:
            raise AnimePexelsClientError(f"Não encontrado (404): {url}")
        if resp.status_code != 200:
            raise AnimePexelsClientError(f"Falha na requisição (status {resp.status_code}): {url}")
        try:
            return resp.json()
        except ValueError as exc:
            raise AnimePexelsClientError(f"Resposta não é JSON válido: {url}") from exc

    def _parse_clip(self, data: Dict[str, Any]) -> AnimePexelsVideo:
        clip_id = str(data.get("id", ""))
        title = data.get("human_caption") or data.get("description") or clip_id
        return AnimePexelsVideo(
            id=clip_id,
            title=str(title)[:120],
            description=data.get("description") or "",
            url=f"{self.esquema}://clip/{clip_id}",
            clip_url=_full_url(self.base_url, data.get("clip_url")) or "",
            thumbnail_url=_full_url(self.base_url, data.get("thumbnail_url")),
            duration_seconds=data.get("duration_seconds"),
            orientation=data.get("orientation"),
            resolution_name=data.get("resolution_name"),
            anime_name=data.get("anime_name"),
            episode_number=data.get("episode_number"),
            tags=data.get("tags") or [],
            raw=data,
        )

    def search(
        self,
        query: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        **filters: Any,
    ) -> Dict[str, Any]:
        """Uma chamada de busca. Sem `query`, funciona como a galeria
        (`/api/gallery`, filtro puro sem busca textual); com `query`,
        usa `/api/search` (busca textual + semântica, aceita os mesmos
        filtros). `tags` aceita lista OU string separada por vírgula.
        """
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if query:
            params["q"] = query
        # nomes do site (obra/personagem) -> nomes da API (anime/character)
        obra = filters.pop("obra", None) or filters.pop("work", None)
        if obra and not filters.get("anime"):
            filters["anime"] = obra
        personagem = filters.pop("personagem", None)
        if personagem and not filters.get("character"):
            filters["character"] = personagem

        tags = filters.pop("tags", None)
        if tags:
            params["tags"] = ",".join(tags) if isinstance(tags, (list, tuple)) else tags

        params.update({k: v for k, v in filters.items() if v is not None})
        path = "/api/search" if query else "/api/gallery"
        return self._request(path, params=params)

    def search_all(
        self,
        query: Optional[str] = None,
        max_pages: int = 10,
        per_page: int = 20,
        **filters: Any,
    ) -> List[AnimePexelsVideo]:
        """Pagina automaticamente via offset/has_more até `max_pages`
        páginas ou até os resultados acabarem.

        Aceita `category` como sinônimo de `query` (compatibilidade com
        o resto do toolkit, que às vezes chama `search_all(category=...)`
        pra provedores baseados em categoria, como o Mixkit) — esse
        banco busca por palavra-chave, não categoria fixa, então os dois
        nomes fazem a mesma coisa aqui.
        """
        if query is None:
            query = filters.pop("category", None)
        else:
            filters.pop("category", None)
        relaxar = filters.pop("relaxar", True)
        for k_site, k_api in (("obra", "anime"), ("work", "anime"), ("personagem", "character")):
            v = filters.pop(k_site, None)
            if v and not filters.get(k_api):
                filters[k_api] = v
        filters = {k: v for k, v in filters.items() if v not in (None, "", [])}
        animes, chars = varios(filters.get("anime")), varios(filters.get("character"))
        if len(animes) > 1 or len(chars) > 1:
            return self._varias(query, max_pages, per_page, filters, animes, chars, relaxar)

        results = self._paginar(query, max_pages, per_page, filters)
        if results or not relaxar or not (filters.get("anime") or filters.get("character")):
            return results
        # Obra/personagem escolhidos e nada achado com o texto: afrouxa aos
        # poucos, mas SEMPRE dentro da obra — uma cena da série certa sem o
        # personagem vale mais que cair num banco genérico.
        tentativas = []
        if filters.get("character"):
            tentativas.append((query, {k: v for k, v in filters.items() if k != "character"}))
        if query:
            tentativas.append((None, dict(filters)))
            if filters.get("character") and filters.get("anime"):
                tentativas.append((None, {k: v for k, v in filters.items() if k != "character"}))
        for q, f in tentativas:
            results = self._paginar(q, max_pages, per_page, f)
            if results:
                return results
        return []

    def _varias(self, query, max_pages, per_page, filters, animes, chars, relaxar) -> List[AnimePexelsVideo]:
        """Mais de uma obra e/ou personagem (separados por " | "): busca cada um e
        intercala os resultados (1º de cada, 2º de cada…), sem repetir clipe.
        Personagem já diz a obra: com vários personagens a busca vai por eles; com
        uma obra só, ela continua valendo junto."""
        base = {k: v for k, v in filters.items() if k not in ("anime", "character")}
        paginas = max(1, max_pages // max(1, len(animes or [None]) * len(chars or [None])))

        def combos(com_personagem: bool):
            if com_personagem and chars:
                return [dict(base, character=c, **({"anime": animes[0]} if len(animes) == 1 else {})) for c in chars]
            return [dict(base, anime=a) for a in animes] or [dict(base)]

        def rodada(q, lista):
            grupos = [self._paginar(q, paginas, per_page, f) for f in lista]
            out, vistos = [], set()
            for k in range(max((len(g) for g in grupos), default=0)):
                for g in grupos:
                    if k < len(g) and g[k].id not in vistos:
                        vistos.add(g[k].id)
                        out.append(g[k])
            return out

        res = rodada(query, combos(True))
        if res or not relaxar:
            return res
        if chars and animes:  # sem o personagem, ainda dentro das obras
            res = rodada(query, combos(False))
        if not res and query:
            res = rodada(None, combos(bool(chars)))
        if not res and query and chars and animes:
            res = rodada(None, combos(False))
        return res

    def _paginar(self, query: Optional[str], max_pages: int, per_page: int, filters: Dict[str, Any]) -> List[AnimePexelsVideo]:
        results: List[AnimePexelsVideo] = []
        offset = 0
        for _ in range(max_pages):
            data = self.search(query=query, limit=per_page, offset=offset, **filters)
            items = data.get("results", [])
            if not items:
                break
            results.extend(self._parse_clip(item) for item in items)
            if not data.get("has_more"):
                break
            offset += per_page
        return results

    # ---------------------------------------------------------------- listas pro site
    def list_works(self) -> List[Dict[str, Any]]:
        """Obras do catálogo (animes / filmes e séries) com os gêneros."""
        data = self._request("/api/animes")
        return [{"nome": a.get("anime_name"), "generos": a.get("genres") or []} for a in data.get("animes") or [] if a.get("anime_name")]

    def list_characters(self, obra: Optional[str] = None, q: Optional[str] = None, with_clips: bool = True,
                        limit: int = 200) -> List[Dict[str, Any]]:
        """Personagens (no catálogo de filmes: "Personagem (Ator)") com quantos
        clipes têm — `[]` se o servidor for antigo e não tiver personagens."""
        if len(varios(obra)) > 1:  # várias obras: junta os personagens de cada uma
            junto = []
            for o in varios(obra):
                junto += self.list_characters(obra=o, q=q, with_clips=with_clips, limit=limit)
            return junto[:limit * 2]
        params: Dict[str, Any] = {}
        if obra:
            params["anime"] = obra
        if q:
            params["q"] = q
        if with_clips:
            params["with_clips"] = 1
        try:
            data = self._request("/api/characters", params=params)
        except AnimePexelsClientError as exc:
            if "404" in str(exc):
                return []
            raise
        saida = []
        for c in (data.get("characters") or [])[:limit]:
            saida.append({"id": c.get("id"), "nome": c.get("name"), "obra": c.get("anime_name"),
                          "clipes": c.get("clip_count") or 0,
                          "foto": _full_url(self.base_url, c.get("photo_url"))})
        return saida

    def work_credits(self, obra: str) -> Optional[Dict[str, Any]]:
        """Ficha da obra (elenco, produção — TMDB/IMDb); None se ainda não tem."""
        from urllib.parse import quote
        try:
            return self._request(f"/api/works/{quote(obra, safe='')}/credits")
        except AnimePexelsClientError as exc:
            if "404" in str(exc):
                return None
            raise

    def get_video_by_url(self, video_url: str) -> AnimePexelsVideo:
        """Resolve a partir do identificador sintético
        "animepexels://clip/<id>" (usado internamente pelo site pra
        "fixar" um resultado específico escolhido no editor) — extrai o
        ID e busca os dados atualizados via `/api/clips/<id>`.
        """
        if "/clip/" not in video_url:
            raise AnimePexelsClientError(
                f"URL não reconhecida pro {CATALOGOS[self.catalog]['nome']}: {video_url!r} "
                f"(esperava algo como '{self.esquema}://clip/<id>')."
            )
        clip_id = video_url.rsplit("/clip/", 1)[-1]
        data = self._request(f"/api/clips/{clip_id}")
        return self._parse_clip(data)

    def download_video(
        self,
        video: Union[AnimePexelsVideo, str],
        output_dir: str = "videos",
        quality: Optional[str] = None,  # aceito por compatibilidade — esse banco não tem variação de qualidade
        **kwargs: Any,
    ) -> str:
        """Baixa o clipe. Como o arquivo já está no disco do próprio
        usuário (só sendo servido via HTTP pelo `app.py` local), isso é
        um download simples e rápido — sem Selenium, sem navegador, só
        uma requisição HTTP direta.
        """
        if isinstance(video, str):
            video = self.get_video_by_url(video) if "/clip/" in video else self._parse_clip({"id": video})

        if not video.clip_url:
            raise AnimePexelsClientError(f"Vídeo {video.id!r} não tem clip_url pra baixar.")

        os.makedirs(output_dir, exist_ok=True)
        dest = os.path.join(output_dir, f"{video.id}.mp4")
        try:
            resp = self.session.get(video.clip_url, stream=True, timeout=DOWNLOAD_TIMEOUT)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        except requests.RequestException as exc:
            raise AnimePexelsClientError(f"Falha ao baixar {video.clip_url}: {exc}") from exc

        if not os.path.exists(dest) or os.path.getsize(dest) == 0:
            raise AnimePexelsClientError(f"Download de {video.clip_url} resultou em arquivo vazio.")

        return dest


class MoviePexelsClient(AnimePexelsClient):
    """Catálogo de FILMES E SÉRIES do mesmo servidor (http://localhost:5000/movie/)."""
    catalog = "movie"
