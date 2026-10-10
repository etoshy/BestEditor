"""
buscador_imagens_unificado.py
===============================

Ponte entre o site e a "Busca de Imagens Unificada" (pacote
`unified_images/`, que veio do zip `busca_imagens_unificada.zip`):
Bing + Brave + Yandex + Startpage Images, os 4 motores com navegador
(Playwright) já melhorados — várias buscas seguidas NA MESMA ABA, filtro
de proporção, downloader que confere pelos bytes se o arquivo é mesmo
uma imagem e tenta a thumbnail/proxy quando a original falha.

Duas formas de usar:

1. `BuscadorImagensClient` (e as subclasses por buscador em
   `bing_api_client.py`, `brave_api_client.py`, ...): mesma interface de
   compatibilidade do cliente de fotos do Pexels/Wikipedia
   (`search_photos_all` / `download_photo`, propriedades `.id`/`.sizes`/
   `.description`/`.author`/`.url`) — o resto do site trata como trata
   qualquer outro provedor de foto.

2. `buscar_e_baixar_primeira(...)`: o modo "lote", que é o que o site usa
   pra prévia e montagem. Regras:

   - **UM navegador por buscador**: cada buscador recebe TODOS os termos
     que estão com ele de uma vez só e pesquisa um atrás do outro na
     mesma aba (`search_images_batch` do motor) — nunca um Chromium por
     termo. Bem mais leve em RAM.
   - **Pega a 1ª imagem do resultado e baixa.**
   - **Se um buscador não achou (ou a imagem não baixou), o termo vai pro
     próximo buscador**, e assim por diante até baixar ou acabar a lista.
   - Os buscadores de uma mesma rodada podem rodar ao mesmo tempo
     (`paralelo=True`: no máximo 1 navegador por buscador) ou um de cada
     vez (`paralelo=False`: no máximo 1 navegador aberto no total).
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Union, Tuple

ENGINES = ("bing", "brave", "yandex", "startpage")

ENGINE_HOME = {
    "bing": "https://www.bing.com/",
    "brave": "https://search.brave.com/",
    "yandex": "https://yandex.com/",
    "startpage": "https://www.startpage.com/",
}


class BuscadorImagensError(Exception):
    """Busca/download falhou (sem resultado, buscador bloqueou, arquivo não é imagem...)."""


# --------------------------------------------------------------------------- #
# Resultado no formato que o site espera
# --------------------------------------------------------------------------- #


@dataclass
class ImagemBuscador:
    title: str = ""
    description: str = ""
    source_page: str = ""
    original_url: str = ""
    thumbnail_url: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    query: str = ""
    engine: str = ""
    fallback_urls: List[str] = field(default_factory=list)
    raw: Optional[Dict[str, Any]] = None

    # -- propriedades de compatibilidade (mesmo padrão de WikipediaImage) -- #
    @property
    def id(self) -> str:  # noqa: A003
        return self.original_url or self.thumbnail_url or self.title

    @property
    def sizes(self) -> Dict[str, str]:
        sizes: Dict[str, str] = {}
        if self.thumbnail_url:
            sizes["tiny"] = sizes["small"] = self.thumbnail_url
        if self.original_url:
            sizes["original"] = self.original_url
        return sizes

    @property
    def author(self) -> str:
        return ""

    @property
    def url(self) -> str:
        return self.source_page

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title, "description": self.description, "source_page": self.source_page,
            "original_url": self.original_url, "thumbnail_url": self.thumbnail_url,
            "width": self.width, "height": self.height, "query": self.query, "engine": self.engine,
        }


def _imagem_de_hit(hit: Dict[str, Any]) -> ImagemBuscador:
    """`hit` = resultado já normalizado por `unified_images.adapters.normalize_result`."""
    return ImagemBuscador(
        title=hit.get("title") or "",
        description=hit.get("title") or hit.get("alt") or "",
        source_page=hit.get("source_page") or "",
        original_url=hit.get("original_url") or "",
        thumbnail_url=hit.get("thumbnail_url") or "",
        width=hit.get("width"),
        height=hit.get("height"),
        query=hit.get("query") or "",
        engine=hit.get("engine") or "",
        fallback_urls=list(hit.get("fallback_urls") or []),
        raw=hit,
    )


# --------------------------------------------------------------------------- #
# asyncio: o site roda em threads comuns (Flask/ThreadPool) -- cada chamada
# abre o próprio loop. Se por acaso já existir um loop rodando nesta thread,
# executa numa thread nova em vez de quebrar com "asyncio.run() cannot be
# called from a running event loop".
# --------------------------------------------------------------------------- #


def _run_async(factory: Callable[[], Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    box: Dict[str, Any] = {}

    def _worker() -> None:
        try:
            box["value"] = asyncio.run(factory())
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _norm(termo: str) -> str:
    return " ".join((termo or "").split())


# --------------------------------------------------------------------------- #
# Marca d'água: bancos de imagem pagos servem a prévia com a marca por cima
# (Alamy, Shutterstock, Getty...). Os buscadores da web acham muito disso —
# essas imagens nunca entram no vídeo.
# --------------------------------------------------------------------------- #

SITES_COM_MARCA_DAGUA = (
    "alamy.", "shutterstock.", "gettyimages.", "istockphoto.", "dreamstime.", "123rf.", "depositphotos.",
    "stock.adobe.", "adobestock.", "ftcdn.net", "fotolia.", "bigstockphoto.", "canstockphoto.", "vectorstock.",
    "pond5.", "agefotostock.", "superstock.", "masterfile.", "fotosearch.", "colourbox.", "storyblocks.",
    "featurepics.", "panthermedia.", "mostphotos.", "zoonar.", "stockfresh.", "pixtastock.", "imago-images.",
    "dissolve.com", "offset.com", "bridgemanimages.", "granger.com", "mediastorehouse.", "lookandlearn.",
    "sciencephoto.", "pictorialpress.", "photodune.", "elements.envato.", "wavebreakmedia.", "stocksy.",
    "megapixl.", "crushpixel.", "yayimages.", "lightstock.",
)
_TITULO_MARCA_DAGUA = re.compile(
    r"\b(?:stock\s+(?:photo|image|picture|footage|illustration|vector)s?|alamy|shutterstock|getty\s*images|istock|"
    r"dreamstime|123rf|depositphotos|adobe\s+stock)\b",
    re.IGNORECASE,
)


def _url_com_marca_dagua(url: str) -> bool:
    u = (url or "").lower()
    if not u:
        return False
    try:
        from urllib.parse import urlparse
        host = urlparse(u).netloc
    except Exception:  # noqa: BLE001
        host = u
    return any(site in host for site in SITES_COM_MARCA_DAGUA)


def tem_marca_dagua(img: "ImagemBuscador") -> bool:
    """A imagem vem de um banco pago (prévia com marca d'água)? Olha o
    endereço da imagem, a página de origem e o título ("... Stock Photo - Alamy")."""
    if _url_com_marca_dagua(img.original_url) or _url_com_marca_dagua(img.source_page):
        return True
    return bool(_TITULO_MARCA_DAGUA.search(f"{img.title or ''} {img.description or ''}"))


def sem_marca_dagua(imagens: List["ImagemBuscador"]) -> List["ImagemBuscador"]:
    """Tira as imagens de banco pago e, das que sobram, os endereços reserva
    que apontam pra um banco pago (o download nunca cai numa prévia marcada)."""
    saida = []
    for img in imagens:
        if tem_marca_dagua(img):
            continue
        img.fallback_urls = [u for u in img.fallback_urls if not _url_com_marca_dagua(u)]
        saida.append(img)
    return saida


# --------------------------------------------------------------------------- #
# "Mesma imagem": a web tem a mesma foto/cena em dezenas de sites, com
# endereços diferentes — comparar URL não basta. dHash de 64 bits do arquivo
# baixado: imagens iguais (ou o mesmo quadro recortado/recomprimido) ficam a
# poucos bits de distância; imagens diferentes ficam perto de 32.
# --------------------------------------------------------------------------- #

LIMITE_PARECIDAS = 12


def assinatura_visual(path: str) -> Optional[int]:
    try:
        from PIL import Image
        with Image.open(path) as im:
            g = im.convert("L").resize((9, 8))
            px = list(g.getdata())
    except Exception:  # noqa: BLE001
        return None
    bits = 0
    for lin in range(8):
        for col in range(8):
            bits = (bits << 1) | (1 if px[lin * 9 + col] > px[lin * 9 + col + 1] else 0)
    return bits


def parecidas(a: Optional[int], b: Optional[int], limite: int = LIMITE_PARECIDAS) -> bool:
    return a is not None and b is not None and bin(int(a) ^ int(b)).count("1") <= limite


# --------------------------------------------------------------------------- #
# Busca: UM navegador por buscador, todos os termos na mesma aba
# --------------------------------------------------------------------------- #


def _opcoes_do_motor(engine: str, engine_options: Optional[Dict[str, Any]], limit: int) -> Dict[str, Any]:
    """No Bing, abrir o detalhe de cada resultado (clique + voltar) custa ~2 s
    por imagem; com vários candidatos por termo (pra não repetir imagem), o
    endereço original que já vem no card basta."""
    opts = dict(engine_options or {})
    if engine == "bing" and int(limit) > 1:
        opts.setdefault("click_details", False)
    return opts


def buscar_lote(
    engine: str,
    queries: Iterable[str],
    limit: int = 1,
    headless: bool = True,
    orientation: str = "any",
    pause_between_ms: int = 800,
    engine_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pesquisa todos os `queries` num único navegador do `engine`.

    Devolve {"por_termo": {termo: [ImagemBuscador, ...]}, "erros": {termo: str},
    "erro_geral": str|None}. Nunca levanta exceção por falha de busca — um
    buscador que cai (captcha, mudança de HTML, Playwright ausente) vira
    `erro_geral` + erro em cada termo, pra quem chama poder tentar outro.
    """
    if engine not in ENGINES:
        raise BuscadorImagensError(f"Buscador desconhecido: {engine!r}. Use: {', '.join(ENGINES)}.")
    termos: List[str] = []
    for q in queries:
        q = _norm(q)
        if q and q not in termos:
            termos.append(q)
    out: Dict[str, Any] = {"por_termo": {t: [] for t in termos}, "erros": {}, "erro_geral": None}
    if not termos:
        return out

    try:
        from unified_images._compat import garantir_imports_dos_motores

        garantir_imports_dos_motores()  # fastapi/pydantic/uvicorn ausentes não podem derrubar a busca
        from unified_images.adapters import ADAPTERS
        from unified_images.spec import SearchSpec

        spec = SearchSpec.from_dict({
            "queries": termos,
            "engines": [engine],
            "limit": max(1, min(50, int(limit) + 6)),  # folga: as de marca d'água saem logo abaixo
            "orientation": orientation or "any",
            "download": False,
            "inspect_sources": False,
            "headless": bool(headless),
            "pause_between_ms": int(pause_between_ms),
            "engine_options": {engine: _opcoes_do_motor(engine, engine_options, limit)},
        })
        adapter = ADAPTERS[engine]
        with tempfile.TemporaryDirectory(prefix=f"busca_{engine}_") as raw_dir:
            from pathlib import Path

            run = _run_async(lambda: adapter.run(spec, Path(raw_dir)))
    except Exception as exc:  # noqa: BLE001
        msg = f"{type(exc).__name__}: {exc}"
        out["erro_geral"] = msg
        out["erros"] = {t: msg for t in termos}
        return out

    if not run.ok and run.error:
        out["erro_geral"] = run.error
    for hit in run.results:
        termo = _norm(hit.get("query") or "")
        if termo not in out["por_termo"]:
            out["por_termo"][termo] = []
        if hit.get("original_url"):
            out["por_termo"][termo].append(_imagem_de_hit(hit))
    for s in run.searches:
        termo = _norm(s.get("query") or "")
        if not s.get("ok") and s.get("error"):
            out["erros"][termo] = str(s["error"])
    for termo in list(out["por_termo"]):
        todas = out["por_termo"][termo]
        limpas = sem_marca_dagua(todas)
        if todas and not limpas:
            out["erros"][termo] = "só achou imagens de banco pago (com marca d'água)"
        out["por_termo"][termo] = limpas[:max(1, int(limit))]
    for termo in termos:
        if not out["por_termo"].get(termo) and termo not in out["erros"]:
            out["erros"][termo] = out["erro_geral"] or "nenhuma imagem encontrada"
    return out


# --------------------------------------------------------------------------- #
# Proporção das imagens (o vídeo é 16:9: foto em pé vira barra/desfoque nas laterais)
# --------------------------------------------------------------------------- #

# proporção pedida -> orientações nativas dos buscadores, na ordem de preferência
PROPORCOES: Dict[str, Tuple[str, ...]] = {
    "qualquer": ("any",),
    "horizontal": ("horizontal",),
    "quadrada": ("square",),
    "vertical": ("vertical",),
    "horizontal_quadrada": ("horizontal", "square"),
    "vertical_quadrada": ("vertical", "square"),
}
_TOLERANCIA_QUADRADA = 0.1
_ASPECTO_BING = {"horizontal": "wide", "square": "square", "vertical": "tall"}


def proporcao_valida(valor: Optional[str]) -> str:
    v = str(valor or "qualquer").strip().lower()
    return v if v in PROPORCOES else "qualquer"


def proporcao_para_orientacao(orientation: Optional[str]) -> str:
    """Proporção automática a partir da orientação do VÍDEO exportado."""
    return {"16:9": "horizontal_quadrada", "9:16": "vertical_quadrada", "1:1": "quadrada"}.get(str(orientation or ""), "horizontal_quadrada")


def tipo_da_imagem(img: ImagemBuscador) -> Optional[str]:
    """'horizontal' | 'vertical' | 'square' | None (tamanho desconhecido)."""
    try:
        w, h = int(img.width or 0), int(img.height or 0)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    r = w / h
    if abs(r - 1.0) <= _TOLERANCIA_QUADRADA:
        return "square"
    return "horizontal" if r > 1 else "vertical"


def ordenar_por_proporcao(imagens: List[ImagemBuscador], proporcao: str) -> List[ImagemBuscador]:
    """Põe primeiro as imagens na proporção pedida (na ordem de preferência),
    depois as de tamanho desconhecido e por último as fora da proporção."""
    prefs = PROPORCOES.get(proporcao_valida(proporcao), ("any",))
    if prefs == ("any",):
        return list(imagens)

    def peso(img: ImagemBuscador) -> int:
        t = tipo_da_imagem(img)
        if t in prefs:
            return prefs.index(t)
        return len(prefs) if t is None else len(prefs) + 1
    return sorted(imagens, key=peso)  # sorted é estável: mantém a relevância do buscador dentro do grupo


def buscar_lote_proporcao(
    engine: str,
    queries: Iterable[str],
    limit: int = 1,
    headless: bool = True,
    proporcao: str = "qualquer",
    engine_options: Optional[Dict[str, Any]] = None,
    buscar: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Como `buscar_lote`, mas respeitando uma proporção que pode ter mais de
    uma orientação ("horizontal_quadrada" = horizontal, e se faltar, quadrada).
    Cada passada usa o filtro NATIVO do buscador (Bing: qft aspect-wide/square;
    os outros: classificam pelo tamanho), só pros termos que ainda não têm
    `limit` imagens. Se um termo não achar nada em nenhuma orientação pedida,
    uma última busca sem filtro entra como reserva (ordenada: proporção certa
    primeiro, fora da proporção por último) — melhor uma foto em pé com fundo
    desfocado do que trecho sem imagem."""
    buscar = buscar or buscar_lote
    proporcao = proporcao_valida(proporcao)
    termos: List[str] = []
    for q in queries:
        q = _norm(q)
        if q and q not in termos:
            termos.append(q)
    out: Dict[str, Any] = {"por_termo": {t: [] for t in termos}, "erros": {}, "erro_geral": None}
    if not termos:
        return out
    passadas = list(PROPORCOES[proporcao])
    if passadas != ["any"]:
        passadas.append("any")  # reserva
    vistos: Dict[str, set] = {t: set() for t in termos}
    for k, ori in enumerate(passadas):
        reserva = ori == "any" and k > 0
        if reserva:  # sem filtro: só pra quem não achou NADA na proporção pedida
            faltam = [t for t in termos if not out["por_termo"][t]]
        else:
            faltam = [t for t in termos if len(out["por_termo"][t]) < limit]
        if not faltam:
            break
        opts = dict(engine_options or {})
        if engine == "bing" and ori in _ASPECTO_BING and "aspect" not in opts:
            opts["aspect"] = _ASPECTO_BING[ori]  # filtro do próprio Bing (qft aspect-wide/square/tall)
        res = buscar(engine, faltam, limit=limit if not reserva else max(limit, 3), headless=headless,
                     orientation=ori, engine_options=opts or None)
        if res.get("erro_geral") and not out["erro_geral"]:
            out["erro_geral"] = res["erro_geral"]
        for t in faltam:
            for img in (res.get("por_termo") or {}).get(t) or []:
                chave = img.original_url or img.thumbnail_url
                if chave in vistos[t]:
                    continue
                vistos[t].add(chave)
                out["por_termo"][t].append(img)
            if (res.get("erros") or {}).get(t):
                out["erros"][t] = res["erros"][t]
    for t in termos:
        out["por_termo"][t] = ordenar_por_proporcao(out["por_termo"][t], proporcao)
        if out["por_termo"][t]:
            out["erros"].pop(t, None)
        elif t not in out["erros"]:
            out["erros"][t] = out["erro_geral"] or "nenhuma imagem encontrada"
    if any(out["por_termo"].values()):
        out["erro_geral"] = None if all(out["por_termo"].values()) else out["erro_geral"]
    return out


# --------------------------------------------------------------------------- #
# Download (downloader unificado: confere bytes, tenta URLs reserva)
# --------------------------------------------------------------------------- #


def _slug(texto: str, max_len: int = 60) -> str:
    texto = re.sub(r"[^\w.\-]+", "_", (texto or "").strip(), flags=re.UNICODE)
    return re.sub(r"_+", "_", texto).strip("._- ")[:max_len] or "imagem"


def _assinatura_segura(path: str) -> bool:
    """True se os bytes são JPEG ou PNG de verdade (independente da extensão)."""
    try:
        with open(path, "rb") as f:
            h = f.read(8)
    except OSError:
        return False
    return h.startswith(b"\xff\xd8\xff") or h.startswith(b"\x89PNG\r\n\x1a\n")


def converter_para_jpg(path: str) -> str:
    """Garante uma imagem que qualquer ffmpeg/Pillow lê: se o arquivo não for
    JPEG/PNG de verdade (AVIF, WebP, HEIC, TIFF, BMP, GIF, ICO... — muito
    comum nos buscadores, que servem .avif/.webp), converte para .jpg ao lado
    do original e devolve o caminho novo. JPEG/PNG voltam como estão.
    Tenta Pillow (com o plugin AVIF/HEIF, se houver) e depois o ffmpeg.
    Levanta ValueError se nenhum dos dois conseguir ler."""
    if _assinatura_segura(path):
        return path
    destino = os.path.splitext(path)[0] + "_convertida.jpg"
    if os.path.exists(destino) and os.path.getmtime(destino) >= os.path.getmtime(path):
        return destino
    erros = []
    try:
        try:
            import pillow_avif  # noqa: F401  (Pillow < 11.3 lê AVIF só com este plugin)
        except ImportError:
            pass
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            pass
        from PIL import Image

        with Image.open(path) as im:
            im.seek(0)  # GIF/WebP animado: primeiro quadro
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                fundo = Image.new("RGB", im.size, (0, 0, 0))
                fundo.paste(im, mask=im.split()[-1])
                im = fundo
            else:
                im = im.convert("RGB")
            im.save(destino, "JPEG", quality=92)
        return destino
    except Exception as exc:  # noqa: BLE001
        erros.append(f"Pillow: {exc}")
    try:
        import subprocess

        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-frames:v", "1", "-q:v", "2", destino],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and _assinatura_segura(destino):
            return destino
        erros.append(f"ffmpeg: {r.stderr.strip()[-200:]}")
    except Exception as exc:  # noqa: BLE001
        erros.append(f"ffmpeg: {exc}")
    raise ValueError("formato de imagem não suportado (" + "; ".join(erros) + ")")


def baixar_imagem(img: ImagemBuscador, output_dir: str, stem: Optional[str] = None, timeout_s: float = 45) -> str:
    """Baixa a imagem (original; se falhar, thumbnail/proxy do buscador).
    Devolve o caminho do arquivo. Levanta `BuscadorImagensError` se nada baixar."""
    from unified_images.downloader import DownloadJob, download_images

    urls = [u for u in [img.original_url, *img.fallback_urls, img.thumbnail_url] if u]
    urls = list(dict.fromkeys(urls))
    if not urls:
        raise BuscadorImagensError(f"Resultado sem URL de imagem pra baixar ({img.title!r}).")
    os.makedirs(output_dir, exist_ok=True)
    referer = img.source_page or ENGINE_HOME.get(img.engine, "")
    stem = stem or f"{img.engine or 'busca'}_{_slug(img.query or img.title)}"
    job = DownloadJob(id=1, urls=urls, referer=referer, stem=stem)
    from pathlib import Path

    res = _run_async(lambda: download_images([job], Path(output_dir), concurrency=1, timeout_s=timeout_s)).get(1) or {}
    if not res.get("ok"):
        raise BuscadorImagensError(f"Falha baixando a imagem de {img.engine}: {res.get('error') or 'erro desconhecido'}")
    caminho = os.path.join(output_dir, res["file"])
    try:
        return converter_para_jpg(caminho)  # .avif/.webp/... viram .jpg na hora
    except ValueError as exc:
        raise BuscadorImagensError(f"A imagem baixada de {img.engine} está num formato que não deu pra ler: {exc}") from exc


# --------------------------------------------------------------------------- #
# Cliente compatível com o resto do site (um por buscador)
# --------------------------------------------------------------------------- #


class BuscadorImagensClient:
    engine: str = ""
    error_cls = BuscadorImagensError

    def __init__(self, headless: bool = True, engine_options: Optional[Dict[str, Any]] = None,
                 proporcao: str = "qualquer", **_ignorado: Any):
        self.headless = headless
        self.engine_options = engine_options or {}
        self.proporcao = proporcao_valida(proporcao)

    def _buscar(self, queries: List[str], limit: int) -> Dict[str, Any]:
        if self.proporcao == "qualquer":
            return buscar_lote(self.engine, queries, limit=limit, headless=self.headless, engine_options=self.engine_options)
        return buscar_lote_proporcao(self.engine, queries, limit=limit, headless=self.headless,
                                     proporcao=self.proporcao, engine_options=self.engine_options)

    def search_images(self, query: str, max_images: int = 5) -> List[ImagemBuscador]:
        if not query or not query.strip():
            raise self.error_cls("Termo de busca vazio.")
        res = self._buscar([query], max_images)
        imagens = res["por_termo"].get(_norm(query)) or []
        if not imagens and res["erro_geral"]:
            raise self.error_cls(f"Falha buscando {query!r} em {self.engine}: {res['erro_geral']}")
        return imagens[:max_images]

    def search_photos_all(self, query: str, max_pages: int = 1, max_images: Optional[int] = None) -> List[ImagemBuscador]:
        """Mesma assinatura de `PexelsAPIClient.search_photos_all` (max_pages é ignorado)."""
        return self.search_images(query, max_images=max_images or 5)

    def search_photos_batch(self, queries: List[str], max_images: int = 1) -> Dict[str, List[ImagemBuscador]]:
        """Vários termos num navegador só. Devolve {termo: [imagens]} (lista vazia = não achou)."""
        res = self._buscar(list(queries), max_images)
        return {_norm(q): (res["por_termo"].get(_norm(q)) or [])[:max_images] for q in queries}

    def download_image(
        self,
        imagem: Union[ImagemBuscador, Dict[str, Any]],
        output_dir: str = "imagens",
        filename: Optional[str] = None,
        overwrite: bool = False,
        **_ignorado: Any,
    ) -> str:
        img = imagem if isinstance(imagem, ImagemBuscador) else ImagemBuscador(**{
            k: v for k, v in imagem.items() if k in ImagemBuscador.__dataclass_fields__
        })
        if not img.engine:
            img.engine = self.engine
        stem = os.path.splitext(filename)[0] if filename else None
        try:
            return baixar_imagem(img, output_dir, stem=stem)
        except BuscadorImagensError as exc:
            raise self.error_cls(str(exc)) from exc

    def download_photo(self, photo, output_dir: str = "imagens", filename: Optional[str] = None, overwrite: bool = False) -> str:
        return self.download_image(photo, output_dir=output_dir, filename=filename, overwrite=overwrite)

    def close(self) -> None:  # nada a fechar: cada busca abre e fecha o próprio navegador
        pass


# --------------------------------------------------------------------------- #
# Lote com fallback entre buscadores: 1ª imagem de cada termo, baixada
# --------------------------------------------------------------------------- #


BuscarFn = Callable[[str, List[str]], Dict[str, Any]]          # (engine, termos) -> saída de buscar_lote
BaixarFn = Callable[[ImagemBuscador, str, str], str]            # (imagem, pasta, stem) -> caminho


def buscar_e_baixar_primeira(
    pedidos: Iterable[Union[str, Dict[str, Any]]],
    output_dir: str,
    engines: Iterable[str] = ENGINES,
    headless: bool = True,
    paralelo: bool = True,
    on_result: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    log: Callable[[str], None] = lambda _m: None,
    buscar_fn: Optional[BuscarFn] = None,
    baixar_fn: Optional[BaixarFn] = None,
    baixar: bool = True,
    termos_por_navegador: int = 5,
    proporcao: str = "qualquer",
    evitar: Optional[Iterable[Any]] = None,
    candidatos_por_termo: int = 8,
    downloads_por_termo: int = 5,
) -> Dict[str, Dict[str, Any]]:
    """Pra cada termo, baixa a 1ª imagem do resultado, tentando os buscadores
    em ordem até um conseguir.

    pedidos: termos (str) ou {"query": termo, "engine": buscador_preferido}.
        O buscador preferido (o que a IA escolheu) é tentado primeiro; depois
        os outros de `engines`, na ordem.
    baixar: False = só pesquisa (pra confirmar que existe imagem), sem baixar.
    termos_por_navegador: quantos termos cada sessão do navegador pesquisa antes
        de entregar os resultados (e baixar as imagens). O navegador de cada
        buscador continua sendo um só por vez; dividir em blocos só faz as
        imagens irem aparecendo aos poucos em vez de tudo no final — numa
        narração com 100+ trechos, esperar o lote inteiro parecia travado.

    Devolve {termo: {"ok", "path", "engine", "query", "title", "original_url",
    "thumbnail_url", "source_page", "tentativas": [{"engine", "erro"}], "erro"}}.

    NÃO REPETIR: os buscadores da web devolvem a mesma foto/cena pra termos
    parecidos (e pro mesmo termo em vários trechos). Cada termo olha até
    `candidatos_por_termo` resultados e pula o que já foi usado neste lote —
    por endereço e pela assinatura visual do arquivo baixado (a mesma imagem
    em sites diferentes). `evitar`: endereços (str) e assinaturas (int) já
    usados antes (em outros trechos do vídeo). Pedido com "quantidade": k
    (o mesmo termo em k trechos) traz k imagens diferentes: a 1ª no resultado
    e as outras em "extras". Se só sobrar imagem repetida, ela entra como
    último recurso ("repetida": True) — melhor que trecho sem imagem.
    Imagem de banco pago (marca d'água) nunca entra.
    """
    ordem_global = [e for e in engines if e in ENGINES] or list(ENGINES)
    # proporção ("horizontal_quadrada" etc.): cada passada usa o filtro nativo
    # do buscador e a lista volta ordenada por ela — a 1ª já é a da proporção certa
    if buscar_fn is None:
        _lim = max(1, int(candidatos_por_termo)) if baixar else 1
        if proporcao_valida(proporcao) == "qualquer":
            buscar_fn = lambda eng, termos: buscar_lote(eng, termos, limit=_lim, headless=headless)  # noqa: E731
        else:
            buscar_fn = lambda eng, termos: buscar_lote_proporcao(eng, termos, limit=_lim, headless=headless,  # noqa: E731
                                                                  proporcao=proporcao)
    baixar_fn = baixar_fn or (lambda img, pasta, stem: baixar_imagem(img, pasta, stem=stem))

    # estado por termo
    estado: Dict[str, Dict[str, Any]] = {}
    for p in pedidos:
        termo = _norm(p if isinstance(p, str) else p.get("query", ""))
        if not termo or termo in estado:
            continue
        pref = None if isinstance(p, str) else (p.get("engine") or "").strip().lower()
        ordem = ([pref] if pref in ENGINES else []) + [e for e in ordem_global if e != pref]
        try:
            qtd = max(1, min(12, int((p.get("quantidade") if isinstance(p, dict) else 1) or 1)))
        except (TypeError, ValueError):
            qtd = 1
        estado[termo] = {"ordem": ordem, "tentativas": [], "resultado": None, "quantidade": qtd, "reserva": None}

    lock = threading.Lock()
    usadas_urls: set = set()
    usadas_assin: List[int] = []
    for x in evitar or []:
        if isinstance(x, bool):
            continue
        if isinstance(x, int):
            usadas_assin.append(x)
        elif isinstance(x, str) and x:
            usadas_urls.add(x)

    def _ja_usada_url(img: ImagemBuscador) -> bool:
        return any(u and u in usadas_urls for u in (img.original_url, img.thumbnail_url))

    def _ja_usada_assin(a: Optional[int]) -> bool:
        return any(parecidas(a, b) for b in usadas_assin)

    def _marcar_usada(img: ImagemBuscador, a: Optional[int]) -> None:
        usadas_urls.update(u for u in (img.original_url, img.thumbnail_url) if u)
        if a is not None:
            usadas_assin.append(a)

    def _apagar(path: Optional[str]) -> None:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def _item(img: ImagemBuscador, path: Optional[str], assin: Optional[int], engine: str) -> Dict[str, Any]:
        return {"path": path, "engine": engine, "title": img.title, "original_url": img.original_url,
                "thumbnail_url": img.thumbnail_url, "source_page": img.source_page, "assinatura": assin}

    def _finalizar(termo: str, resultado: Dict[str, Any]) -> None:
        with lock:
            estado[termo]["resultado"] = resultado
        if on_result:
            try:
                on_result(termo, resultado)
            except Exception:  # noqa: BLE001
                pass

    def _processar_bloco(engine: str, termos: List[str]) -> Optional[str]:
        """Pesquisa um bloco de termos numa sessão do navegador e já baixa as
        imagens. Devolve o erro geral do buscador (se ele caiu por inteiro)."""
        try:
            res = buscar_fn(engine, termos)
        except Exception as exc:  # noqa: BLE001
            res = {"por_termo": {}, "erros": {t: f"{type(exc).__name__}: {exc}" for t in termos},
                   "erro_geral": f"{type(exc).__name__}: {exc}"}
        achou_algum = False
        for termo in termos:
            imagens = (res.get("por_termo") or {}).get(termo) or []
            erro = (res.get("erros") or {}).get(termo)
            if not imagens:
                with lock:
                    estado[termo]["tentativas"].append({"engine": engine, "erro": erro or "nenhuma imagem encontrada"})
                continue
            achou_algum = True
            imagens = sem_marca_dagua(list(imagens))
            if not imagens:
                with lock:
                    estado[termo]["tentativas"].append({"engine": engine, "erro": "só imagens de banco pago (marca d'água)"})
                continue
            if not baixar:  # só confirmando que existe imagem
                img = imagens[0]
                with lock:
                    estado[termo]["tentativas"].append({"engine": engine, "erro": None})
                    tentativas = list(estado[termo]["tentativas"])
                _finalizar(termo, dict(_item(img, None, None, engine), ok=True, query=termo, tentativas=tentativas, erro=None))
                continue
            qtd = estado[termo]["quantidade"]
            escolhidas: List[Dict[str, Any]] = []
            ultimo_erro = None
            baixadas = 0
            for img in imagens:
                if len(escolhidas) >= qtd or baixadas >= downloads_por_termo + qtd - 1:
                    break
                img.engine = img.engine or engine
                with lock:
                    if _ja_usada_url(img):
                        continue
                stem = f"{engine}_{_slug(termo)}" + (f"_{baixadas}" if baixadas else "")
                baixadas += 1
                try:
                    path = baixar_fn(img, output_dir, stem)
                except Exception as exc:  # noqa: BLE001
                    ultimo_erro = f"download falhou: {exc}"
                    continue
                assin = assinatura_visual(path) if path else None
                with lock:
                    repetida = _ja_usada_url(img) or _ja_usada_assin(assin)
                    if not repetida:
                        _marcar_usada(img, assin)
                if repetida:
                    with lock:
                        if estado[termo]["reserva"] is None:
                            estado[termo]["reserva"] = _item(img, path, assin, engine)
                        else:
                            _apagar(path)
                    continue
                escolhidas.append(_item(img, path, assin, engine))
            if not escolhidas:
                with lock:
                    estado[termo]["tentativas"].append({
                        "engine": engine,
                        "erro": ultimo_erro if (ultimo_erro and estado[termo]["reserva"] is None) else "só imagens repetidas de outros trechos",
                    })
                continue
            with lock:
                estado[termo]["tentativas"].append({"engine": engine, "erro": None})
                tentativas = list(estado[termo]["tentativas"])
                reserva = estado[termo]["reserva"]
            if reserva and reserva.get("path") not in {e["path"] for e in escolhidas}:
                _apagar(reserva.get("path"))
            principal = escolhidas[0]
            _finalizar(termo, dict(principal, ok=True, query=termo, tentativas=tentativas, erro=None,
                                   extras=escolhidas[1:]))
        return res.get("erro_geral") if not achou_algum else None

    def _processar_buscador(engine: str, termos: List[str]) -> None:
        tamanho = max(1, int(termos_por_navegador or len(termos)))
        blocos = [termos[i:i + tamanho] for i in range(0, len(termos), tamanho)]
        for n, bloco in enumerate(blocos, start=1):
            log(f"[buscadores de imagem] {engine}: bloco {n}/{len(blocos)} ({len(bloco)} termo(s))…")
            erro_geral = _processar_bloco(engine, bloco)
            if erro_geral and n < len(blocos):
                # o buscador caiu por inteiro (Playwright ausente, bloqueio, sem
                # internet...): não adianta abrir o navegador de novo pros
                # próximos blocos — passa todos eles pro próximo buscador.
                log(f"[buscadores de imagem] {engine} falhou ({erro_geral[:150]}); os termos restantes vão pro próximo buscador")
                for resto in blocos[n:]:
                    for termo in resto:
                        with lock:
                            estado[termo]["tentativas"].append({"engine": engine, "erro": erro_geral})
                break

    while True:
        grupos: Dict[str, List[str]] = {}
        for termo, st in estado.items():
            if st["resultado"] is not None:
                continue
            tentados = {t["engine"] for t in st["tentativas"]}
            proximo = next((e for e in st["ordem"] if e not in tentados), None)
            if proximo is None and st.get("reserva"):
                # todos os buscadores só tinham imagem já usada: a repetida entra (melhor que nada)
                _finalizar(termo, dict(st["reserva"], ok=True, query=termo, tentativas=list(st["tentativas"]),
                                       erro=None, repetida=True, extras=[]))
                continue
            if proximo is None:
                erros = "; ".join(f"{t['engine']}: {t['erro']}" for t in st["tentativas"])
                _finalizar(termo, {
                    "ok": False, "path": None, "engine": None, "query": termo, "title": "",
                    "original_url": "", "thumbnail_url": "", "source_page": "",
                    "tentativas": list(st["tentativas"]),
                    "erro": f"nenhum buscador conseguiu ({erros})" if erros else "nenhum buscador disponível",
                })
                continue
            grupos.setdefault(proximo, []).append(termo)
        if not grupos:
            break
        if paralelo and len(grupos) > 1:
            threads = [threading.Thread(target=_processar_buscador, args=(eng, ts), daemon=True) for eng, ts in grupos.items()]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        else:
            for eng, ts in grupos.items():
                _processar_buscador(eng, ts)

    return {termo: st["resultado"] for termo, st in estado.items()}
