"""
video_assembler.py
====================

Última etapa do pipeline: pega a lista de `VideoSegment` (já validada
por `prompt_builder.parse_ai_response()`), busca e baixa um vídeo pra
cada segmento usando o toolkit (Magnific/Mixkit/Pexels/Pixabay/
VistaCreate), ajusta cada clipe pra durar exatamente o tempo do seu
segmento, concatena tudo em ordem, e sincroniza com o áudio da
narração original — gerando o vídeo final pronto.

Uso
----
    from video_assembler import assemble_video

    final_path = assemble_video(
        segments=video_segments,       # lista de VideoSegment
        audio_path="uploads/narracao.mp3",
        output_path="outputs/final.mp4",
        work_dir="jobs/abc123",
    )
"""

from __future__ import annotations

import concurrent.futures
import importlib
import json
import os
import tempfile
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import nullcontext
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))

from prompt_builder import PHOTO_SEARCH_PROVIDERS as _PHOTO_SEARCH_PROVIDERS
from prompt_builder import BROWSER_IMAGE_SEARCH_PROVIDERS as _BROWSER_IMAGE_SEARCH_PROVIDERS
_SO_SE_MARCADO = ("google",)  # buscador de imagem que só entra na troca entre buscadores se estiver marcado no vídeo
from prompt_builder import VideoSegment
from site_config import load_site_config, resolution_for_orientation
from perf_log import PerfLog

TARGET_WIDTH = 1920  # usado como padrão quando nenhuma orientação é passada explicitamente
TARGET_HEIGHT = 1080
TARGET_FPS = 30

# Fonte embutida no projeto (assets/fonts/) pra desenhar texto/legendas
# sem depender do fontconfig do sistema operacional estar configurado —
# em especial no Windows, onde isso costuma faltar e quebra qualquer
# filtro do ffmpeg que dependa de resolver uma fonte "pelo nome" (como
# `font=Sans`), com o erro "Fontconfig error: Cannot load default
# config file". Usando o arquivo .ttf diretamente (`fontfile=`), isso
# funciona igual em qualquer sistema operacional.
_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
_FONT_FILE_REGULAR = os.path.join(_FONT_DIR, "DejaVuSans.ttf")
_FONT_FILE_BOLD = os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")
_FONT_FAMILY_NAME = "DejaVu Sans"  # nome interno da fonte, usado no Style do .ass


def _escape_path_for_ffmpeg_filter(path: str) -> str:
    """Escapa um caminho de arquivo pra usar como valor de opção dentro
    de um filtro do ffmpeg (`fontfile=...`, `ass=...`) — ':' e '\\' têm
    significado especial na sintaxe de filtros. Isso é particularmente
    importante no Windows, onde os caminhos já vêm com barra invertida
    E dois-pontos depois da letra do drive (ex: `E:\\pasta\\arquivo`).
    """
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

# Nome do parâmetro de orientação aceito por search_all() em cada provedor,
# e o valor pra pedir paisagem/retrato — só incluído aqui quando o site
# realmente suporta esse filtro (confirmado no toolkit); provedores fora
# desse dict simplesmente não recebem filtro de orientação na busca (o
# corte/preenchimento em _normalize_clip ainda garante a proporção final
# de qualquer forma, só que sem o benefício de já vir do jeito certo).
_ORIENTATION_FILTERS = {
    "pexels": {"16:9": {"orientation": "landscape"}, "9:16": {"orientation": "portrait"}},
    "pixabay": {"16:9": {"orientation": "horizontal"}, "9:16": {"orientation": "vertical"}},
    "mixkit": {"16:9": {"orientation": "horizontal"}, "9:16": {"orientation": "vertical"}},
    "magnific": {"16:9": {"orientations": ["horizontal"]}, "9:16": {"orientations": ["vertical"]}},
    "animepexels": {"16:9": {"orientation": "horizontal"}, "9:16": {"orientation": "vertical"}},
    "moviepexels": {"16:9": {"orientation": "horizontal"}, "9:16": {"orientation": "vertical"}},
    "animepexels_online": {"16:9": {"orientation": "horizontal"}, "9:16": {"orientation": "vertical"}},
    "moviepexels_online": {"16:9": {"orientation": "horizontal"}, "9:16": {"orientation": "vertical"}},
    # vistacreate não expõe filtro de orientação na busca (confirmado no toolkit)
}


class VideoAssemblyError(Exception):
    """Erro genérico de montagem (busca sem resultado, ffmpeg falhou, etc.)."""


def _orientation_filter_kwargs(provider: str, orientation: Optional[str]) -> Dict[str, Any]:
    if not orientation:
        return {}
    return _ORIENTATION_FILTERS.get(provider, {}).get(orientation, {})


# Nome dos parâmetros de duração mínima/máxima aceitos por search_all()
# em cada provedor que suporta esse filtro (confirmado no toolkit) — usar
# isso pede vídeo já do tamanho certo em vez de sempre depender de cortar
# ou repetir em loop depois de baixar.
_DURATION_FILTER_PARAMS = {
    "pexels": ("min_duration", "max_duration"),
    "magnific": ("duration_from", "duration_to"),
    "animepexels": ("min_duration", "max_duration"),
    "moviepexels": ("min_duration", "max_duration"),
    "animepexels_online": ("min_duration", "max_duration"),
    "moviepexels_online": ("min_duration", "max_duration"),
}

# Acervos LOCAIS (anime-pexels-local): um servidor, dois catálogos. Entendem
# os pesos da busca e os filtros de obra (anime/filme/série) e personagem/ator.
# + as versões ONLINE do mesmo projeto (modo servidor, com chave de API) — ver acervos.py
BIBLIOTECAS_LOCAIS = ("animepexels", "moviepexels", "animepexels_online", "moviepexels_online")


def _weight_filter_kwargs(segment: VideoSegment) -> Dict[str, Any]:
    """Repassa `keyword_weight`/`semantic_weight` do segmento pra busca,
    quando definidos — só tem efeito de verdade com o "animepexels"
    (que entende esses parâmetros no `/api/search`), mas é seguro
    incluir pra qualquer provedor: os outros clientes do toolkit
    aceitam `**kwargs` genericamente e simplesmente ignoram parâmetros
    que não reconhecem.
    """
    kwargs: Dict[str, Any] = {}
    if segment.keyword_weight is not None:
        kwargs["keyword_weight"] = segment.keyword_weight
    if segment.semantic_weight is not None:
        kwargs["semantic_weight"] = segment.semantic_weight
    # obra e personagem/ator: só pros acervos locais (num banco genérico,
    # "anime=Naruto" não significa nada)
    if segment.provider in BIBLIOTECAS_LOCAIS:
        if getattr(segment, "obra", None):
            kwargs["obra"] = segment.obra
        if getattr(segment, "personagem", None):
            kwargs["personagem"] = segment.personagem
    return kwargs


def _duration_filter_kwargs(provider: str, target_duration: float) -> Dict[str, Any]:
    """Monta os parâmetros de duração mínima/máxima pra pedir um vídeo
    que já cubra o segmento inteiro sozinho — o mínimo pedido nunca é
    menor que a duração do próprio segmento (evita a necessidade de
    repetir em loop, que fica visualmente óbvio quando acontece). O
    máximo tem uma folga generosa pra cima, já que um vídeo mais longo
    só é cortado (sem perda de qualidade visual), enquanto um mais
    curto exigiria repetir a cena.

    Só se aplica aos provedores que o toolkit confirma suportar esse
    filtro; os outros simplesmente não recebem nada aqui (o
    preenchimento com cenas extras, ou o corte/loop como último
    recurso, continuam garantindo a duração final de qualquer forma).
    """
    params = _DURATION_FILTER_PARAMS.get(provider)
    if not params:
        return {}
    min_param, max_param = params
    min_duration = max(1, round(target_duration))
    max_duration = round(target_duration + max(4.0, target_duration * 0.6))
    return {min_param: min_duration, max_param: max_duration}


def _run_ffmpeg(args: List[str], timeout: int = 300) -> None:
    import qualidade_export
    base = ["ffmpeg", "-y", "-loglevel", "error"] + args
    cmd = qualidade_export.ajustar(base)
    try:
        # encoder da placa (NVENC/QSV/AMF) quando tem; se ela falhar, o mesmo passo roda na CPU
        result = qualidade_export.executar(cmd, timeout=timeout, _original=qualidade_export._ajustar_cpu(base))
    except subprocess.TimeoutExpired as exc:
        raise VideoAssemblyError(f"ffmpeg excedeu o tempo limite: {' '.join(cmd)}") from exc
    if result.returncode != 0:
        raise VideoAssemblyError(f"ffmpeg falhou ({' '.join(cmd)}):\n{result.stderr[-1000:]}")


def _probe_duration(path: str) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return float(json.loads(result.stdout)["format"]["duration"])
    except (subprocess.SubprocessError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise VideoAssemblyError(f"Não consegui ler a duração de '{path}': {exc}") from exc


def _has_audio_stream(path: str) -> bool:
    """Confere se o arquivo tem alguma faixa de áudio — usado pra saber
    se um clipe de corte (inserção real) já vem com som próprio, ou se
    precisa gerar uma faixa de silêncio pra poder concatenar sem
    recodificar de novo depois (todo pedaço concatenado precisa ter a
    MESMA estrutura de faixas).
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-select_streams", "a", path],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return bool(json.loads(result.stdout).get("streams"))
    except (subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return False  # se não conseguir nem checar, assume que não tem (mais seguro: gera silêncio)


def _get_or_create_client(provider: str, clients: dict, get_client_fn):
    """Reaproveita UM cliente (uma sessão de navegador, se aplicável) por
    provedor, em vez de abrir um novo a cada segmento — abrir um Chrome
    por segmento numa narração de 20 segmentos abriria 20 navegadores e
    nunca fecharia nenhum.
    """
    if provider not in clients:
        clients[provider] = get_client_fn(provider)
    return clients[provider]


BUSCADORES_PROPORCOES = ("auto", "horizontal_quadrada", "horizontal", "quadrada", "vertical_quadrada", "vertical", "qualquer")


def proporcao_dos_buscadores(cfg: Dict[str, Any]) -> str:
    """Proporção das imagens pedidas ao Bing/Brave/Yandex/Startpage. "auto"
    segue a orientação da BUSCA (= a do vídeo exportado, salvo se a pessoa
    mudou "orientação da busca"): 16:9 -> horizontal ou quadrada; 9:16 ->
    vertical ou quadrada; busca "mista" -> qualquer."""
    v = str(cfg.get("buscadores_proporcao") or "auto")
    if v in BUSCADORES_PROPORCOES and v != "auto":
        return v
    busca = cfg.get("search_orientation", "match_export")
    if busca == "mixed":
        return "qualquer"
    ori = cfg.get("orientation", "16:9") if busca in (None, "", "match_export") else busca
    return {"9:16": "vertical_quadrada", "1:1": "quadrada"}.get(ori, "horizontal_quadrada")


def _sem_bloqueados(provedores: List[str], cfg: Optional[Dict[str, Any]] = None) -> List[str]:
    """⛔ tira os bancos cujo site está na lista negra (ex.: "magnific") — v84_106."""
    try:
        import lista_negra
        return lista_negra.sem_bloqueados(provedores, lista_negra.sites(cfg) if cfg is not None and "sites_bloqueados" in cfg else None)
    except Exception:  # noqa: BLE001
        return list(provedores)


# 🤖 provedores que GERAM a mídia com IA (não buscam): nunca entram de reserva, não têm busca alternativa
GERADORES_IA = ("flow", "runpod")


def _sem_flow_no_fallback(provider_priority: List[str], provider_do_trecho: str) -> List[str]:
    """Bancos reserva de um trecho de vídeo: a prioridade sem o próprio banco do
    trecho e SEM o "flow" (gerar vídeo com IA leva minutos e gasta créditos —
    só quando o trecho pediu "flow" de propósito)."""
    # acervos ONLINE (anime/filmes com chave) não entram de reserva pra um trecho de banco de
    # estoque — senão uma cena de anime aparecia num vídeo que não é de anime só porque o
    # Pexels falhou. Entre acervos (local <-> online) continua valendo.
    acervo = provider_do_trecho in BIBLIOTECAS_LOCAIS
    return [p for p in (provider_priority or []) if p != provider_do_trecho and p not in GERADORES_IA
            and (acervo or not p.endswith("_online"))]


def _provider_timeout_seconds(cfg: Dict[str, Any], provider: str) -> float:
    """Quanto esperar UMA tentativa desse provedor. O Google Flow gera
    imagem com IA (leva de dezenas de segundos a minutos), então o limite
    padrão de uma busca em banco (25s) o derrubaria toda vez."""
    base = cfg.get("provider_attempt_timeout_seconds", 25)
    if provider == "runpod":  # 🟣 gera em segundos; vídeo pode passar de 1 min na fila
        return max(base, 600)
    if provider == "flow":
        try:
            flow_s = int(cfg.get("flow_timeout_seconds") or 300)
        except (TypeError, ValueError):
            flow_s = 300
        # vídeo (Veo) demora mais que imagem: o cliente espera até 600 s por ele
        return max(base, max(flow_s, 600) + 90)  # + abrir/fechar navegador e baixar
    return base


def _run_with_timeout(func: "callable", timeout_seconds: float):
    """Roda `func()` com um limite de tempo — se não terminar dentro do
    prazo, levanta `TimeoutError` e o CHAMADOR desiste de esperar (a
    tentativa continua rodando sozinha em segundo plano até terminar ou
    falhar por conta própria — não dá pra matar uma thread Python à
    força — mas isso libera o resto do processamento pra seguir sem
    ficar preso nela).

    De propósito cross-platform (funciona igual no Windows): não usa
    `signal.alarm`, que só existe em sistemas Unix e não funcionaria
    pro público real deste site.

    Usa uma thread `daemon=True` própria por chamada (não um
    `ThreadPoolExecutor` compartilhado com tamanho fixo) por dois
    motivos: (1) threads de um `ThreadPoolExecutor` NÃO são daemon por
    padrão — se um provedor travar de verdade, aquela thread abandonada
    ficaria viva pra sempre, impedindo o processo de encerrar de forma
    limpa num servidor rodando por muito tempo; (2) um pool
    compartilhado de tamanho fixo pode se esgotar ao longo do tempo se
    várias tentativas travadas se acumularem (cada uma ocupando um
    "worker" permanentemente), fazendo chamadas NOVAS ficarem
    esperando por um worker livre — justamente o oposto do que esse
    mecanismo deveria garantir.
    """
    result: Dict[str, Any] = {}

    def _worker():
        try:
            result["value"] = func()
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        # ainda rodando depois do prazo — desiste de esperar (a thread
        # continua sozinha, mas como é daemon, nunca prende o processo).
        raise TimeoutError(f"Excedeu o tempo limite de {timeout_seconds:.0f}s")

    if "error" in result:
        raise result["error"]
    return result.get("value")


def _validate_downloaded_file(path: str) -> None:
    """Confirma que o arquivo baixado é de verdade um vídeo/imagem
    LEGÍVEL — não só que o download "terminou sem erro de rede". Um
    provedor pode devolver uma página de erro HTML salva com extensão
    .mp4, ou a conexão pode cair no meio, deixando um arquivo vazio ou
    truncado; sem essa checagem, isso só seria descoberto muito mais
    tarde (na hora de montar o vídeo final), derrubando o job inteiro
    por causa de UM segmento — em vez de já tentar o próximo candidato
    da busca automaticamente, como acontece com qualquer outra falha de
    download.
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise VideoAssemblyError(f"Arquivo baixado está vazio ou não existe: {path}")

    if _infer_media_kind(path) == "image":
        try:
            convertido = garantir_imagem_compativel(path)  # AVIF/WebP/... -> JPG
        except VideoAssemblyError as exc:
            raise VideoAssemblyError(f"Arquivo de imagem baixado está corrompido/inválido: {path} ({exc})") from exc
        try:
            from PIL import Image
            with Image.open(convertido) as img:
                img.verify()
        except Exception as exc:  # noqa: BLE001
            raise VideoAssemblyError(f"Arquivo de imagem baixado está corrompido/inválido: {path} ({exc})") from exc
    else:
        duration = _probe_duration(path)  # já levanta VideoAssemblyError com mensagem clara se ilegível
        if duration <= 0:
            raise VideoAssemblyError(f"Arquivo de vídeo baixado tem duração zero/inválida: {path}")


def _download_first_working_result(segment: VideoSegment, videos: list, client, download_dir: str, max_attempts: int = 3, quality: Optional[str] = None):
    """Tenta baixar, em ordem, até `max_attempts` resultados da busca
    (não só o primeiro) — se um resultado específico falhar (link
    quebrado, vídeo premium recusado no Magnific, arquivo baixado vier
    corrompido/inválido, etc.), tenta o próximo antes de desistir do
    segmento inteiro.
    """
    last_error: Optional[Exception] = None
    for video in videos[:max_attempts]:
        kwargs = {}
        # Magnific recusa vídeo premium por padrão (marca d'água) —
        # em vez de deixar isso quebrar o segmento sempre que a IA
        # escolher um resultado premium, permite baixar o preview
        # com marca d'água como último recurso, e loga isso.
        if getattr(video, "premium", False) and hasattr(video, "watermarked"):
            kwargs["allow_watermarked"] = True
        try:
            if quality:
                try:
                    path = client.download_video(video, output_dir=download_dir, quality=quality, **kwargs)
                except TypeError:
                    # esse cliente não tem parâmetro 'quality' (Pixabay,
                    # Magnific, VistaCreate) — cai de volta pra chamada sem
                    # ele, em vez de falhar o segmento inteiro por isso.
                    path = client.download_video(video, output_dir=download_dir, **kwargs)
            else:
                path = client.download_video(video, output_dir=download_dir, **kwargs)
            _validate_downloaded_file(path)
            return path
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    raise VideoAssemblyError(
        f"Nenhum dos {min(len(videos), max_attempts)} resultados pra '{segment.query}' "
        f"em {segment.provider} pôde ser baixado. Último erro: {last_error}"
    )


def _search_and_download_photo(
    segment: VideoSegment,
    download_dir: str,
    photo_client,
    fallback_queries: Optional[List[str]] = None,
    used_tracker: Optional["UsedClipsTracker"] = None,
) -> str:
    """Busca uma FOTO (não vídeo) pro termo do segmento e baixa a
    primeira que funcionar — usado quando `segment.media_type ==
    "image"`. Mesmo espírito de `_search_and_download_one`: tenta
    termos alternativos e os primeiros resultados antes de desistir.

    used_tracker: mesmo mecanismo usado pelos segmentos de vídeo (ver
        `UsedClipsTracker`) — evita repetir a MESMA foto em trechos
        diferentes do vídeo, preferindo sempre uma foto nova primeiro e
        só recorrendo a uma já usada como último recurso (melhor que
        falhar o segmento por completo).
    """
    used_tracker = _tracker_para(segment.provider, used_tracker)  # Wikipedia pode repetir
    queries_to_try = [segment.query] + (fallback_queries or [])
    last_error: Optional[Exception] = None

    for query in queries_to_try:
        try:
            photos = photo_client.search_photos_all(query=query, max_pages=1)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue

        if not photos:
            last_error = VideoAssemblyError(f"nenhuma foto encontrada pra '{query}'")
            continue
        photos = _ordenar_resultados_estilo(photos, segment.provider)  # 🎞️ imagens reais: desenho/3D/recorte por último

        already_used_candidates: List[Any] = []
        tentativas = 0
        for photo in photos:
            if tentativas >= 3:
                break
            photo_id = getattr(photo, "id", None)
            claimed = True
            if used_tracker is not None and photo_id is not None:
                claimed = used_tracker.try_claim(photo_id, segment.provider)
                if not claimed:
                    already_used_candidates.append(photo)
                    continue
            tentativas += 1
            try:
                path = photo_client.download_photo(photo, output_dir=download_dir)
                _validate_downloaded_file(path)
                return path
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if used_tracker is not None and photo_id is not None and claimed:
                    used_tracker.release(photo_id, segment.provider)  # reserva não virou uso de verdade
                continue

        # esgotou as fotos NOVAS pra essa query sem conseguir baixar
        # nenhuma -- só agora recorre às que já foram usadas em outro
        # trecho, em vez de simplesmente desistir dessa query.
        for photo in already_used_candidates[:3]:
            try:
                path = photo_client.download_photo(photo, output_dir=download_dir)
                _validate_downloaded_file(path)
                return path
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

    raise VideoAssemblyError(
        f"Não consegui achar/baixar nenhuma foto pra '{segment.query}' "
        f"(tentei {queries_to_try}). Último erro: {last_error}"
    )


# Provedores em que repetir a MESMA foto em trechos diferentes é normal e
# desejado: a Wikipedia devolve a foto de uma entidade específica (uma pessoa,
# um monumento...) — se a narração volta a falar do mesmo assunto, a foto certa
# é a mesma, e "pular pra próxima" traria uma foto de outra coisa.
NO_REPEAT_EXEMPT_PROVIDERS = frozenset({"wikipedia"})


def _tracker_para(provider: Optional[str], used_tracker: Optional["UsedClipsTracker"]) -> Optional["UsedClipsTracker"]:
    """O tracker a usar pra esse provedor: `None` (= sem controle de
    repetição) quando ele é isento (ver `NO_REPEAT_EXEMPT_PROVIDERS`)."""
    return None if provider in NO_REPEAT_EXEMPT_PROVIDERS else used_tracker


class UsedClipsTracker:
    """Rastreia quais vídeos já foram usados em QUALQUER segmento desta
    montagem — evita que a mesma cena apareça repetida em partes
    diferentes do vídeo final, não só dentro de um único segmento.

    Thread-safe de propósito: os segmentos são processados em paralelo
    (`assembly_fetch_concurrency`), então "reservar" um vídeo pra uso
    precisa ser uma operação atômica (checar e marcar de uma vez, sob
    lock) — senão dois segmentos concorrentes poderiam escolher a
    MESMA cena ao mesmo tempo, antes de qualquer um dos dois ter
    registrado o uso.
    """

    def __init__(self):
        self._used: set = set()
        self._lock = threading.Lock()

    @staticmethod
    def _chave(video_id: Any, provider: Optional[str]) -> str:
        # com o provedor na chave, o id 123 do Pexels e o id 123 do Pixabay
        # não se confundem (antes, só o id valia).
        return f"{provider}:{video_id}" if provider else str(video_id)

    def try_claim(self, video_id: Any, provider: Optional[str] = None) -> bool:
        """Tenta reservar esse vídeo pra uso — devolve True se
        conseguiu (ninguém tinha usado ainda, inclusive nenhum outro
        segmento rodando em paralelo agora mesmo), False se já estava
        reservado/em uso.
        """
        key = self._chave(video_id, provider)
        with self._lock:
            if key in self._used:
                return False
            self._used.add(key)
            return True

    def release(self, video_id: Any, provider: Optional[str] = None) -> None:
        """Libera uma reserva que acabou não virando um uso de
        verdade (ex: o download falhou depois de reservar) — sem isso,
        uma reserva feita mas nunca concretizada bloquearia esse vídeo
        pra sempre, mesmo sem ele nunca ter aparecido no vídeo final.
        """
        with self._lock:
            self._used.discard(self._chave(video_id, provider))


def _search_and_download_filling_duration(
    segment: VideoSegment,
    download_dir: str,
    client,
    fallback_queries: Optional[List[str]] = None,
    orientation: Optional[str] = None,
    magnific_only_free: bool = False,
    quality: Optional[str] = None,
    max_clips: int = 4,
    used_tracker: Optional["UsedClipsTracker"] = None,
    initial_duration: float = 0.0,
) -> List[str]:
    """Busca e baixa um ou mais clipes DIFERENTES até acumular pelo
    menos a duração do segmento inteiro — em vez de aceitar um único
    clipe curto e repeti-lo em loop (visualmente óbvio, a mesma cena
    "piscando" de novo), tenta completar o tempo com cenas diferentes
    da mesma busca quando possível.

    initial_duration: quantos segundos já estão "garantidos" antes
        mesmo dessa busca começar (ex: um clipe escolhido manualmente
        no editor que já baixamos, mas veio mais curto que o trecho).
        Os clipes buscados aqui só precisam completar o que falta —
        útil pra complementar um clipe manual curto em vez de repeti-lo
        em loop/pausar no último frame.

    Sempre pede com o filtro de duração ativo (quando o provedor
    suportar) — isso já prioriza clipes longos o bastante sozinhos, e
    normalmente resolve o caso comum sem precisar de um segundo clipe.
    Isso só entra em ação de verdade quando o provedor não suporta esse
    filtro, ou os resultados vieram mais curtos que o pedido mesmo
    assim.

    used_tracker: quando fornecido, PREFERE candidatos que ainda não
        foram usados em NENHUM outro trecho desta mesma montagem —
        evita que a mesma cena apareça repetida em partes diferentes
        do vídeo final, não só dentro de um único segmento. Só recorre
        a um candidato já usado como ÚLTIMO recurso, se não sobrar
        nenhuma opção nova (melhor repetir uma cena de outro trecho do
        que não conseguir completar o tempo de jeito nenhum).

    Devolve uma lista de caminhos (na ordem em que devem aparecer no
    segmento final), sempre com pelo menos 1 item se a busca encontrar
    QUALQUER coisa baixável. Se mesmo usando até `max_clips` candidatos
    diferentes a duração total ainda não bater, quem chama essa função
    decide se repete o ÚLTIMO clipe da lista em loop pro tempo restante
    — isso vira o último recurso, não o caminho normal.
    """
    queries_to_try = [segment.query] + (fallback_queries or [])
    last_error: Optional[Exception] = None
    extra_kwargs = dict(_orientation_filter_kwargs(segment.provider, orientation))
    extra_kwargs.update(_duration_filter_kwargs(segment.provider, segment.duration))
    extra_kwargs.update(_weight_filter_kwargs(segment))
    if segment.provider == "magnific" and magnific_only_free:
        extra_kwargs["only_free"] = True

    def _try_download(video) -> Optional[tuple]:
        """Tenta baixar UM candidato. Devolve (path, duração) em caso
        de sucesso, ou None se falhar (e já atualiza `last_error`)."""
        nonlocal last_error
        kwargs: Dict[str, Any] = {}
        if getattr(video, "premium", False) and hasattr(video, "watermarked"):
            kwargs["allow_watermarked"] = True
        try:
            if quality:
                try:
                    path = client.download_video(video, output_dir=download_dir, quality=quality, **kwargs)
                except TypeError:
                    path = client.download_video(video, output_dir=download_dir, **kwargs)
            else:
                path = client.download_video(video, output_dir=download_dir, **kwargs)
            _validate_downloaded_file(path)
            return path, _probe_duration(path)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            return None

    for query in queries_to_try:
        try:
            if segment.provider == "mixkit":
                videos = client.search_all(category=query, max_pages=1, **extra_kwargs)
            else:
                videos = client.search_all(query=query, max_pages=1, **extra_kwargs)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue

        if not videos:
            last_error = VideoAssemblyError(f"nenhum resultado pra '{query}'")
            continue
        videos = _ordenar_resultados_estilo(videos, segment.provider, orientation)  # 🎞️🖼️ imagens reais: desenho/3D/recorte por último

        collected: List[str] = []
        accumulated = initial_duration
        already_used_candidates: List[Any] = []  # candidatos pulados por já estarem em uso em outro trecho

        for video in videos:
            if len(collected) >= max_clips:
                break
            video_id = getattr(video, "id", None)
            claimed = True
            if used_tracker is not None and video_id is not None:
                claimed = used_tracker.try_claim(video_id, segment.provider)
                if not claimed:
                    # já usado em outro trecho desta montagem — guarda como
                    # opção de último recurso, mas prefere achar algo novo primeiro.
                    already_used_candidates.append(video)
                    continue

            result = _try_download(video)
            if result is None:
                if used_tracker is not None and video_id is not None and claimed:
                    used_tracker.release(video_id, segment.provider)  # reserva não virou uso de verdade
                continue

            path, clip_duration = result
            collected.append(path)
            accumulated += clip_duration
            if accumulated >= segment.duration - 0.05:
                return collected

        # esgotou os candidatos NOVOS sem completar o tempo — só agora
        # recorre aos que já foram usados em outro trecho, como último
        # recurso (preferível a repetir a MESMA cena em loop, ou a não
        # completar a duração de jeito nenhum).
        if accumulated < segment.duration - 0.05 and already_used_candidates:
            for video in already_used_candidates:
                if len(collected) >= max_clips:
                    break
                result = _try_download(video)
                if result is None:
                    continue
                path, clip_duration = result
                collected.append(path)
                accumulated += clip_duration
                if accumulated >= segment.duration - 0.05:
                    return collected

        if collected:
            # essa busca rendeu pelo menos 1 clipe usável, mesmo sem
            # completar o tempo todo — devolve o que conseguiu (quem
            # chama decide se repete o último em loop pro resto).
            return collected
        # nenhum candidato dessa query funcionou -- tenta a proxima query

    raise VideoAssemblyError(
        f"Não consegui achar/baixar nada pra '{segment.query}' em {segment.provider} "
        f"(tentei {queries_to_try}). Último erro: {last_error}"
    )


def _search_and_download_one(
    segment: VideoSegment,
    download_dir: str,
    client,
    fallback_queries: Optional[List[str]] = None,
    orientation: Optional[str] = None,
    match_duration: bool = False,
    magnific_only_free: bool = False,
    quality: Optional[str] = None,
):
    """Busca o termo/categoria do segmento e baixa o primeiro resultado
    que funcionar de verdade. Se a busca não trouxer nada (ou nada
    baixável), tenta `fallback_queries` em ordem antes de desistir —
    por padrão, uma versão mais genérica do próprio termo (só a última
    palavra), já que um termo específico demais é o motivo mais comum
    de zero resultados.

    orientation: "16:9" ou "9:16" — se o provedor suportar filtro de
        orientação na busca, já pede vídeo do formato certo (evita
        depender só do corte/preenchimento na normalização).
    match_duration: se True, pede (aos provedores que suportam) vídeo
        com duração próxima da do segmento, em vez de aceitar qualquer
        duração e cortar/repetir depois.
    magnific_only_free: se True, busca no Magnific só considera vídeos
        gratuitos (nunca premium/com marca d'água) — evita o problema
        de licenciamento na raiz, em vez de aceitar baixar com marca
        d'água como último recurso.
    quality: passado pro `download_video()` do cliente, quando ele
        aceitar esse parâmetro (Pexels e Mixkit aceitam; os outros 3
        provedores ignoram — a chamada cai de volta pra sem esse
        parâmetro automaticamente nesse caso, sem quebrar). Usado pelas
        prévias da timeline pra baixar em qualidade baixa ("worst"),
        bem mais rápido e leve do que a qualidade máxima usada na
        montagem final.
    """
    queries_to_try = [segment.query] + (fallback_queries or [])
    last_error: Optional[Exception] = None
    extra_kwargs = dict(_orientation_filter_kwargs(segment.provider, orientation))
    if match_duration:
        extra_kwargs.update(_duration_filter_kwargs(segment.provider, segment.duration))
    extra_kwargs.update(_weight_filter_kwargs(segment))
    if segment.provider == "magnific" and magnific_only_free:
        extra_kwargs["only_free"] = True

    for query in queries_to_try:
        try:
            if segment.provider == "mixkit":
                videos = client.search_all(category=query, max_pages=1, **extra_kwargs)
            else:
                videos = client.search_all(query=query, max_pages=1, **extra_kwargs)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue

        if not videos:
            last_error = VideoAssemblyError(f"nenhum resultado pra '{query}'")
            continue

        try:
            return _download_first_working_result(segment, videos, client, download_dir, quality=quality)
        except VideoAssemblyError as exc:
            last_error = exc
            continue

    raise VideoAssemblyError(
        f"Não consegui achar/baixar nada pra '{segment.query}' em {segment.provider} "
        f"(tentei {queries_to_try}). Último erro: {last_error}"
    )


def _escape_drawtext(text: str) -> str:
    """Escapa um texto pra usar dentro do valor de `text=` do filtro
    `drawtext` do ffmpeg — que tem sua própria sintaxe de escape (bem
    diferente de shell ou de aspas normais): backslash, dois-pontos,
    aspas simples e o símbolo de porcentagem precisam de tratamento
    especial, ou o parser do filtro quebra ou interpreta errado.
    """
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\u2019")  # troca aspas simples por aspas tipográficas (evita quebrar o parser)
    text = text.replace("%", "\\%")
    return text


_TEXT_POSITION_PRESETS = {
    "top-left": ("20", "20"),
    "top-center": ("(w-text_w)/2", "20"),
    "top-right": ("w-text_w-20", "20"),
    "middle-left": ("20", "(h-text_h)/2"),
    "middle-center": ("(w-text_w)/2", "(h-text_h)/2"),
    "middle-right": ("w-text_w-20", "(h-text_h)/2"),
    "bottom-left": ("20", "h-(h/5)-text_h"),
    "bottom-center": ("(w-text_w)/2", "h-(h/5)-(text_h/2)"),  # padrão — igual ao comportamento de sempre
    "bottom-right": ("w-text_w-20", "h-(h/5)-text_h"),
}


def _build_drawtext_filter(
    text: str, target_height: int, style: Optional[Dict[str, Any]] = None, duration: Optional[float] = None,
) -> str:
    """Monta o filtro `drawtext` pra sobrepor `text` no vídeo — totalmente
    personalizável via `style` (posição, tamanho, cor, borda, sombra,
    fonte, animação de entrada/saída). Sem `style` (ou com campos
    ausentes), usa os padrões de sempre: texto branco, fonte negrito,
    proporcional à resolução, caixa semi-transparente atrás, centralizado
    horizontalmente, perto do terço inferior, sem animação.

    `style` (todos os campos opcionais):
        "position": uma das 9 posições em _TEXT_POSITION_PRESETS
            (padrão: "bottom-center").
        "font_size": tamanho em pixels (padrão: ~5.5% da altura do vídeo).
        "font_color": cor do texto, "#RRGGBB" ou nome ffmpeg (padrão:
            "white").
        "border": True/False — contorno ao redor das letras (padrão:
            False).
        "border_color": cor do contorno, só com border=True (padrão:
            "black").
        "border_width": pixels de contorno, só com border=True (padrão: 3).
        "background": True/False — caixa semi-transparente atrás do
            texto (padrão: True, igual ao comportamento de sempre).
        "shadow": True/False — sombra projetada atrás das letras
            (padrão: False).
        "shadow_color": cor da sombra, só com shadow=True (padrão:
            "black").
        "shadow_offset": deslocamento da sombra em pixels, pra baixo e
            pra direita, só com shadow=True (padrão: 2).
        "font": "regular" ou "bold" (padrão: "bold", igual ao de sempre)
            — as duas únicas fontes embutidas no projeto (DejaVu Sans),
            escolhidas de propósito pra nunca depender de fontconfig do
            sistema (o que quebrava no Windows antes dessa correção).
        "animation": "none" (padrão) ou "fade" — com "fade", o texto
            aparece e desaparece suavemente (opacidade) em vez de surgir
            e sumir de repente.
        "animation_duration": segundos que o fade de entrada/saída dura
            (padrão: 0.4). Só tem efeito com animation="fade".

    `duration`: duração TOTAL do clipe em segundos — usado só pra
    calcular o fade de SAÍDA quando o texto não tem "end_offset" próprio
    (nesse caso a saída acontece perto do fim do clipe inteiro). Sem
    isso nem "end_offset", só o fade de ENTRADA é aplicado (não dá pra
    saber quando desenhar a saída).
    """
    style = style or {}
    escaped_text = _escape_drawtext(text)

    font_key = style.get("font", "bold")
    font_path = _FONT_FILE_REGULAR if font_key == "regular" else _FONT_FILE_BOLD
    escaped_font_path = _escape_path_for_ffmpeg_filter(font_path)

    fontsize = style.get("font_size") or max(18, round(target_height * 0.055))
    if style.get("font_size_pct") and not style.get("font_size"):  # 🤖 v84_145: tamanho em % da altura (selo de IA)
        fontsize = max(12, round(target_height * float(style["font_size_pct"]) / 100))
    font_color = style.get("font_color") or "white"

    position = style.get("position", "bottom-center")
    if "x_percent" in style or "y_percent" in style:
        xp = max(0.0, min(100.0, float(style.get("x_percent", 50))))
        yp = max(0.0, min(100.0, float(style.get("y_percent", 88))))
        x_expr = f"(w-text_w)*{xp/100:.5f}"
        y_expr = f"(h-text_h)*{yp/100:.5f}"
    else:
        x_expr, y_expr = _TEXT_POSITION_PRESETS.get(position, _TEXT_POSITION_PRESETS["bottom-center"])

    parts = [f"drawtext=fontfile='{escaped_font_path}':text='{escaped_text}':fontcolor={font_color}:fontsize={fontsize}"]

    if style.get("background", True):
        parts.append("box=1:boxcolor=black@0.55:boxborderw=14")
    if style.get("border", False):
        border_color = style.get("border_color") or "black"
        try:
            border_width = max(0, int(style.get("border_width", 3)))
        except (TypeError, ValueError):
            border_width = 3
        parts.append(f"bordercolor={border_color}:borderw={border_width}")
    if style.get("shadow", False):
        shadow_color = style.get("shadow_color") or "black"
        try:
            shadow_offset = max(0, int(style.get("shadow_offset", 2)))
        except (TypeError, ValueError):
            shadow_offset = 2
        parts.append(f"shadowcolor={shadow_color}:shadowx={shadow_offset}:shadowy={shadow_offset}")

    parts.append(f"x={x_expr}:y={y_expr}")

    # Janela de tempo PRÓPRIA do texto dentro do trecho (em segundos,
    # relativa ao início do clipe já normalizado — 0 é o começo do
    # trecho) — permite que o texto apareça só numa PARTE do trecho,
    # independente da duração do vídeo. Sem os dois campos (ou com
    # end_offset <= start_offset), o texto continua cobrindo o trecho
    # inteiro, como sempre foi.
    start_offset = style.get("start_offset")
    end_offset = style.get("end_offset")
    window_start, window_end = 0.0, None
    if start_offset is not None and end_offset is not None:
        try:
            so, eo = float(start_offset), float(end_offset)
            if eo > so:
                parts.append(f"enable='between(t,{so:.3f},{eo:.3f})'")
                window_start, window_end = so, eo
        except (TypeError, ValueError):
            pass
    if window_end is None and duration is not None:
        window_end = float(duration)

    # Animação de entrada/saída — três tipos disponíveis:
    #   "fade": opacidade (0 -> 1 -> 1 -> 0)
    #   "slide": desliza de uma direção até a posição final (e volta a
    #       deslizar pra fora na saída)
    #   "zoom": cresce de pequeno até o tamanho normal (e encolhe de
    #       novo na saída)
    # Todos os três reaproveitam a MESMA curva de "presença" (0 nas
    # pontas, 1 no meio) — só o que cada um FAZ com essa curva muda.
    animation_type = style.get("animation")
    if animation_type in ("fade", "slide", "zoom"):
        try:
            anim_dur = max(0.05, float(style.get("animation_duration", 0.4)))
        except (TypeError, ValueError):
            anim_dur = 0.4
        ws = window_start
        if window_end is not None:
            we = window_end
            # evita as duas metades da animação se sobreporem numa
            # janela muito curta (efeito "piscando" em vez de
            # aparecer/sumir direito).
            anim_dur = min(anim_dur, max(0.05, (we - ws) / 2))
            presence_expr = (
                f"if(lt(t\\,{ws:.3f})\\,0\\,"
                f"if(lt(t\\,{ws + anim_dur:.3f})\\,(t-{ws:.3f})/{anim_dur:.3f}\\,"
                f"if(lt(t\\,{we - anim_dur:.3f})\\,1\\,"
                f"if(lt(t\\,{we:.3f})\\,({we:.3f}-t)/{anim_dur:.3f}\\,0))))"
            )
        else:
            # sem duração conhecida nenhuma (nem end_offset, nem duration
            # do clipe) -- só dá pra animar a ENTRADA; o texto continua
            # visível/no lugar dali em diante (sem animação de saída).
            presence_expr = (
                f"if(lt(t\\,{ws:.3f})\\,0\\,"
                f"if(lt(t\\,{ws + anim_dur:.3f})\\,(t-{ws:.3f})/{anim_dur:.3f}\\,1))"
            )

        if animation_type == "fade":
            parts.append(f"alpha='{presence_expr}'")
        elif animation_type == "zoom":
            # tamanho cresce de 30% até 100% do fontsize normal durante
            # a entrada (e encolhe de volta na saída) -- nunca chega a
            # zero, então o texto nunca "some" de vez por causa do
            # tamanho (só fica pequeno).
            parts[0] = parts[0].replace(f"fontsize={fontsize}", f"fontsize='{fontsize}*(0.3+0.7*({presence_expr}))'")
        elif animation_type == "slide":
            # desloca a posição final por uma distância que DIMINUI até
            # zero durante a entrada (e cresce de novo na saída) -- a
            # distância é medida em unidades do próprio texto (text_w/
            # text_h, que o drawtext calcula sozinho em tempo de
            # execução), então funciona proporcionalmente pra qualquer
            # tamanho de fonte, sem precisar saber o tamanho de
            # antemão.
            slide_direction = style.get("slide_direction", "bottom")
            deslocamento = f"(1-({presence_expr}))"
            if slide_direction == "left":
                x_expr = f"({x_expr})-text_w*{deslocamento}"
            elif slide_direction == "right":
                x_expr = f"({x_expr})+text_w*{deslocamento}"
            elif slide_direction == "top":
                y_expr = f"({y_expr})-text_h*{deslocamento}"
            else:  # "bottom" (padrão)
                y_expr = f"({y_expr})+text_h*{deslocamento}"
            # substitui o "x=.../y=..." já adicionado em `parts` (foi
            # calculado ANTES dessa seção) pela versão animada.
            for i, p in enumerate(parts):
                if p.startswith("x=") or p.startswith("y="):
                    parts[i] = f"x={x_expr}:y={y_expr}"
                    break

    return ":".join(parts)


def _normalize_clip(
    input_path: str,
    target_duration: float,
    output_path: str,
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
    trim_position: str = "start",
    on_screen_text: Optional[str] = None,
    on_screen_text_style: Optional[Dict[str, Any]] = None,
    aspect_fill: str = "black",
    trim_start_frames: int = 0,
    blur_sigma: float = 0.0,
) -> str:
    """Ajusta um clipe baixado pra durar EXATAMENTE `target_duration`
    segundos, na mesma resolução/fps/codec pra todos os clipes (pré-
    requisito pra concatenar sem re-codificar de novo depois), e sem
    áudio (o áudio final vem só da narração).

    Se o clipe original for mais curto que o segmento, ele é repetido em
    loop até preencher o tempo. Se for mais longo, um trecho de
    `target_duration` é cortado dele — de onde exatamente depende de
    `trim_position`:
        "start"  (padrão): desde o começo do vídeo.
        "middle": do meio do vídeo (evita a introdução/fade-in que
                  muitos vídeos de banco de imagem têm no início).
        "random": um ponto aleatório válido (mais variedade quando o
                  mesmo vídeo acaba sendo reaproveitado em segmentos
                  diferentes).

    target_width/target_height: resolução de saída — calculada por
    `site_config.resolution_for_orientation()` conforme a orientação e
    a qualidade de exportação escolhidas.

    on_screen_text: se fornecido, desenha esse texto sobre o clipe
    inteiro (via `drawtext`).
    on_screen_text_style: personalização opcional do texto acima — ver
    `_build_drawtext_filter()` pros campos aceitos (posição, tamanho,
    borda, fundo, fonte). Sem isso, usa o visual padrão de sempre.
    """
    input_duration = _probe_duration(input_path)
    if aspect_fill == "cartao":  # 🪧 cartão sobre fundo é pra IMAGEM; vídeo de outra proporção fica no mosaico
        aspect_fill = "mosaic"
    if aspect_fill not in ("black", "zoom", "mosaic", "smart"):
        aspect_fill = "black"
    if aspect_fill == "smart":
        return _normalize_clip_smart(input_path, input_duration, target_duration, output_path, target_width, target_height,
                                     trim_position, on_screen_text, on_screen_text_style, trim_start_frames, blur_sigma)
    try:
        blur_sigma = float(blur_sigma or 0)
    except (TypeError, ValueError):
        blur_sigma = 0.0
    if blur_sigma < 0:
        raise VideoAssemblyError(f"blur_sigma não pode ser negativo (recebi {blur_sigma}).")

    # Como o material dos bancos pode ter proporção diferente da saída,
    # existem três formas de preencher o espaço que sobraria: manter as
    # barras pretas, cortar com zoom central, ou criar um mosaico dinâmico
    # usando cópias do próprio clipe como fundo e manter o clipe original
    # encaixado no centro.
    if aspect_fill == "zoom":
        fill_filter = (
            f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={target_width}:{target_height}:(iw-ow)/2:(ih-oh)/2,setsar=1"
        )
    elif aspect_fill == "mosaic":
        tile_w, tile_h = target_width // 2, target_height // 2
        fill_filter = (
            "[0:v]split=4[m1][m2][m3][m4];"
            f"[m1]scale={tile_w}:{tile_h}:force_original_aspect_ratio=increase,crop={tile_w}:{tile_h}:(iw-ow)/2:(ih-oh)/2[m1c];"
            f"[m2]scale={tile_w}:{tile_h}:force_original_aspect_ratio=increase,crop={tile_w}:{tile_h}:(iw-ow)/2:(ih-oh)/2[m2c];"
            f"[m3]scale={tile_w}:{tile_h}:force_original_aspect_ratio=increase,crop={tile_w}:{tile_h}:(iw-ow)/2:(ih-oh)/2[m3c];"
            f"[m4]scale={tile_w}:{tile_h}:force_original_aspect_ratio=increase,crop={tile_w}:{tile_h}:(iw-ow)/2:(ih-oh)/2[m4c];"
            f"[m1c][m2c][m3c][m4c]xstack=inputs=4:layout=0_0|{tile_w}_0|0_{tile_h}|{tile_w}_{tile_h}[bg];"
            f"[bg]boxblur=12:2[bgblur];"
            f"[{0}:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease[fg];"
            "[bgblur][fg]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )
    else:
        fill_filter = (
            f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )

    # O filtro de mosaico acima usa o mesmo input e precisa de um
    # filter_complex; os demais podem continuar no -vf simples.
    trim_start_frames = max(0, int(trim_start_frames or 0))
    if trim_start_frames:
        fill_filter = f"trim=start_frame={trim_start_frames},setpts=PTS-STARTPTS," + fill_filter

    if aspect_fill == "mosaic":
        video_filter = fill_filter
    else:
        filters = [fill_filter]
        if blur_sigma > 0:
            filters.append(f"gblur=sigma={blur_sigma:.2f}")
        if on_screen_text:
            filters.append(_build_drawtext_filter(on_screen_text, target_height, on_screen_text_style, duration=target_duration))
        video_filter = ",".join(filters)
    args = []
    needs_loop = input_duration < target_duration - 0.05
    if needs_loop:
        args += ["-stream_loop", "-1"]
    elif trim_position != "start" and input_duration > target_duration + 0.05:
        # só faz sentido escolher onde cortar quando o clipe é mais
        # longo que o necessário (e não vai entrar em loop de qualquer forma)
        max_start = input_duration - target_duration
        if trim_position == "middle":
            start_offset = max_start / 2
        elif trim_position == "random":
            import random
            start_offset = random.uniform(0, max_start)
        else:
            start_offset = 0.0
        args += ["-ss", f"{start_offset:.3f}"]

    args += ["-i", input_path, "-t", f"{target_duration:.3f}"]
    if aspect_fill == "mosaic":
        if on_screen_text:
            text_filter = _build_drawtext_filter(on_screen_text, target_height, on_screen_text_style, duration=target_duration)
            # O drawtext entra depois do overlay final.
            video_filter = video_filter.rsplit(",setsar=1", 1)[0] + ",setsar=1," + text_filter
        if blur_sigma > 0:
            # Aplicado por ÚLTIMO de propósito, DEPOIS de já ter tratado
            # o texto acima (se não fizesse isso aqui e sim antes, o
            # rsplit(",setsar=1",...) do bloco de texto acharia o
            # ",setsar=1" que o PRÓPRIO blur adicionou e descartaria o
            # gblur inteiro ao reconstruir a string em volta do texto).
            video_filter = video_filter + f",gblur=sigma={blur_sigma:.2f}"
        args += ["-filter_complex", video_filter, "-map", "[vout]"] if "[vout]" in video_filter else ["-filter_complex", video_filter]
    else:
        args += ["-vf", video_filter]
    args += ["-r", str(TARGET_FPS), "-an"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", output_path]

    _run_ffmpeg(args)
    return output_path


def _probe_video_size(path: str) -> Optional[tuple]:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0:s=x", path], capture_output=True, text=True, timeout=30)
        w, h = r.stdout.strip().split("\n")[0].split("x")[:2]
        return int(w), int(h)
    except (subprocess.SubprocessError, ValueError, IndexError):
        return None


def detectar_bordas_pretas(path: str, duracao: Optional[float] = None) -> Optional[tuple]:
    """(w, h, x, y) da imagem útil quando o vídeo tem barras pretas EMBUTIDAS
    (comum em vídeo antigo/baixa qualidade do YouTube: 4:3 dentro de 16:9,
    letterbox). None se não tiver barra relevante (< 4% de cada lado)."""
    tam = _probe_video_size(path)
    if not tam:
        return None
    W0, H0 = tam
    dur = duracao if duracao is not None else _probe_duration(path)
    achados = []
    for frac in (0.2, 0.5, 0.8):  # 3 pontos do vídeo: não se engana com uma cena escura
        ss = max(0.0, dur * frac - 0.5)
        r = subprocess.run(["ffmpeg", "-hide_banner", "-ss", f"{ss:.2f}", "-i", path, "-t", "1.2", "-vf", "cropdetect=limit=24:round=2:reset=0",
                            "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=120)
        m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
        if m:
            achados.append(tuple(int(v) for v in m[-1]))
    if not achados:
        return None
    # o MAIOR retângulo entre as amostras (uma cena escura não pode comer imagem)
    x0 = min(a[2] for a in achados)
    y0 = min(a[3] for a in achados)
    x1 = max(a[2] + a[0] for a in achados)
    y1 = max(a[3] + a[1] for a in achados)
    w, h = x1 - x0, y1 - y0
    if w < W0 * 0.3 or h < H0 * 0.3:
        return None
    if w >= W0 * 0.96 and h >= H0 * 0.96:
        return None
    return (w - w % 2, h - h % 2, x0, y0)


def _normalize_clip_smart(input_path: str, input_duration: float, target_duration: float, output_path: str,
                          target_width: int, target_height: int, trim_position: str, on_screen_text, on_screen_text_style,
                          trim_start_frames: int, blur_sigma: float) -> str:
    """"Preencher inteligente": tira as barras pretas que já vêm DENTRO do
    vídeo, aumenta sem distorcer (lanczos + nitidez leve quando a fonte é
    pequena) e preenche a tela: se a proporção é parecida, corta o mínimo;
    se é bem diferente (vídeo vertical/4:3), põe o próprio vídeo desfocado
    atrás em vez de barra preta."""
    import math
    tam = _probe_video_size(input_path) or (target_width, target_height)
    corte = detectar_bordas_pretas(input_path, input_duration)
    w, h = (corte[0], corte[1]) if corte else tam
    pre = []
    trim_start_frames = max(0, int(trim_start_frames or 0))
    if trim_start_frames:
        pre.append(f"trim=start_frame={trim_start_frames},setpts=PTS-STARTPTS")
    if corte:
        pre.append(f"crop={corte[0]}:{corte[1]}:{corte[2]}:{corte[3]}")
    pre.append("setsar=1")
    fator = max(target_width / max(1, w), target_height / max(1, h))
    nitidez = ",unsharp=5:5:0.7:5:5:0.0" if fator > 1.5 else ""
    dif = abs(math.log((w / max(1, h)) / (target_width / target_height)))
    if dif <= math.log(1.28):
        grafo = (f"[0:v]{','.join(pre)},scale={target_width}:{target_height}:force_original_aspect_ratio=increase:flags=lanczos,"
                 f"crop={target_width}:{target_height}:(iw-ow)/2:(ih-oh)/2{nitidez},setsar=1[base]")
    else:
        pw, ph = max(2, target_width // 6), max(2, target_height // 6)
        grafo = (f"[0:v]{','.join(pre)},split=2[a][b];"
                 f"[a]scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph},gblur=sigma=4,"
                 f"scale={target_width}:{target_height},eq=brightness=-0.12:saturation=0.85[bg];"
                 f"[b]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease:flags=lanczos{nitidez}[fg];"
                 f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[base]")
    fim = "[base]"
    if blur_sigma and float(blur_sigma) > 0:
        grafo += f";{fim}gblur=sigma={float(blur_sigma):.2f}[bl]"
        fim = "[bl]"
    if on_screen_text:
        grafo += f";{fim}{_build_drawtext_filter(on_screen_text, target_height, on_screen_text_style, duration=target_duration)}[tx]"
        fim = "[tx]"
    grafo += f";{fim}format=yuv420p[vout]"
    args = []
    if input_duration < target_duration - 0.05:
        args += ["-stream_loop", "-1"]
    elif trim_position != "start" and input_duration > target_duration + 0.05:
        import random
        max_start = input_duration - target_duration
        args += ["-ss", f"{(max_start / 2 if trim_position == 'middle' else random.uniform(0, max_start) if trim_position == 'random' else 0.0):.3f}"]
    args += ["-i", input_path, "-t", f"{target_duration:.3f}", "-filter_complex", grafo, "-map", "[vout]",
             "-r", str(TARGET_FPS), "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", output_path]
    _run_ffmpeg(args)
    return output_path


def _normalize_multi_clip(
    input_paths: List[str],
    target_duration: float,
    output_path: str,
    work_dir: str,
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
    trim_position: str = "start",
    on_screen_text: Optional[str] = None,
    on_screen_text_style: Optional[Dict[str, Any]] = None,
    aspect_fill: str = "black",
    trim_start_frames: int = 0) -> str:
    """Monta UM segmento a partir de VÁRIOS clipes diferentes,
    concatenados em sequência até somar `target_duration` — usado
    quando `_search_and_download_filling_duration()` trouxe mais de um
    clipe pra completar um segmento, em vez de repetir uma única cena
    em loop (visualmente óbvio).

    Cada clipe usa sua própria duração (ou é cortado, se sobrar tempo
    menor que ele) — só o ÚLTIMO da lista absorve o tempo restante por
    completo, inclusive repetindo em loop internamente (via
    `_normalize_clip`) se mesmo depois de somar todos os clipes
    disponíveis ainda faltar tempo — isso é o último recurso, não o
    caminho normal (só acontece se a busca não encontrou clipes
    suficientes pra cobrir o segmento inteiro).

    Com só 1 clipe na lista, se comporta EXATAMENTE como chamar
    `_normalize_clip()` direto (mesmo resultado, sem overhead de
    concatenar por nada).
    """
    if len(input_paths) == 1:
        return _normalize_clip(
            input_paths[0], target_duration, output_path,
            target_width, target_height, trim_position, on_screen_text, on_screen_text_style, aspect_fill, trim_start_frames,
        )

    intermediate_paths: List[str] = []
    remaining = target_duration
    for i, path in enumerate(input_paths):
        is_last = i == len(input_paths) - 1
        piece_output = os.path.join(work_dir, f"_multiclip_piece_{i}_{uuid.uuid4().hex[:8]}.mp4")
        if is_last:
            piece_duration = remaining
        else:
            clip_duration = _probe_duration(path)
            piece_duration = min(clip_duration, remaining)

        # o texto na tela aparece em TODOS os pedaços (não só no
        # último) — o segmento inteiro é uma única "unidade" de tempo
        # pra narração, então o texto deveria ficar visível o tempo
        # todo, mesmo que internamente sejam cenas diferentes.
        _normalize_clip(
            path, piece_duration, piece_output, target_width, target_height,
            trim_position, on_screen_text, on_screen_text_style, aspect_fill, trim_start_frames,
        )
        intermediate_paths.append(piece_output)
        remaining -= piece_duration
        if remaining <= 0.05 and not is_last:
            break  # já completou o tempo antes de chegar no último clipe disponível

    try:
        _concat_clips(intermediate_paths, output_path, work_dir)
    finally:
        # limpa os pedaços intermediários — sem isso, cada segmento
        # preenchido com múltiplas cenas deixaria vários arquivos
        # (cada um já recodificado na resolução final) pra trás pra
        # sempre, um jeito NOVO de acumular lixo em disco que não
        # existia antes dessa funcionalidade (antes, cada segmento só
        # gerava o próprio arquivo final, nada intermediário).
        for piece_path in intermediate_paths:
            try:
                os.remove(piece_path)
            except OSError:
                pass
    return output_path


def _concat_clips(clip_paths: List[str], output_path: str, work_dir: str) -> str:
    """Concatena clipes já normalizados (mesmo codec/resolução/fps) sem
    re-codificar, usando o concat demuxer do ffmpeg.
    """
    list_path = os.path.join(work_dir, "_concat_list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for path in clip_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")

    assinaturas = {_assinatura_stream(p) for p in clip_paths}
    if len(assinaturas) <= 1:
        _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_path])
        esperado = sum(_duracao_ou_zero(p) for p in clip_paths)
        obtido = _duracao_ou_zero(output_path)
        if esperado <= 0 or obtido <= 0 or obtido >= esperado - max(0.5, esperado * 0.01):
            return output_path
        print(f"[montagem] concat sem recodificar saiu com {obtido:.2f}s de {esperado:.2f}s — refazendo recodificando", flush=True)
    else:
        print(f"[montagem] clipes com parâmetros diferentes ({len(assinaturas)} variações) — concatenando com recodificação: {sorted(a[0] for a in assinaturas)}", flush=True)
    # Rede de segurança: com "-c copy", um clipe com parâmetros um pouco
    # diferentes (timebase, SAR, perfil — p.ex. uma imagem trocada no
    # Estúdio no meio de vídeos) faz o vídeo final "acabar" antes dele em
    # alguns players. Recodificando, todos viram um fluxo só.
    _concat_recodificando(clip_paths, output_path)
    return output_path


def _duracao_ou_zero(path: str) -> float:
    try:
        return max(0.0, _probe_duration(path))
    except Exception:
        return 0.0


def _assinatura_stream(path: str) -> tuple:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_name,profile,width,height,pix_fmt,r_frame_rate,time_base,sample_aspect_ratio",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30)
        return (r.stdout.strip(),)
    except Exception:
        return ("?",)


def _concat_recodificando(clip_paths: List[str], output_path: str) -> None:
    w, h = (_probe_video_size(clip_paths[0]) or (None, None)) if clip_paths else (None, None)
    args: List[str] = []
    for p in clip_paths:
        args += ["-i", p]
    partes = []
    for i in range(len(clip_paths)):
        escala = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2," if w and h else ""
        partes.append(f"[{i}:v]{escala}setsar=1,fps={TARGET_FPS},format=yuv420p,settb=AVTB,setpts=PTS-STARTPTS[v{i}]")
    n = len(clip_paths)
    com_audio = all(_tem_audio_seguro(p) for p in clip_paths)
    if com_audio:
        partes += [f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}]" for i in range(n)]
        filtro = ";".join(partes) + ";" + "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[out][aout]"
        saida = ["-map", "[out]", "-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    else:
        filtro = ";".join(partes) + ";" + "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[out]"
        saida = ["-map", "[out]", "-an"]
    _run_ffmpeg(args + ["-filter_complex", filtro] + saida + ["-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(TARGET_FPS), output_path], timeout=3600)


def _tem_audio_seguro(path: str) -> bool:
    try:
        return _has_audio_stream(path)
    except Exception:
        return False


TRANSICOES_CUSTOMIZADAS: Dict[str, str] = {
    # Transições NOVAS, construídas com o modo "custom" do filtro `xfade`
    # (expressão matemática por pixel — sem precisar de shader GLSL nem
    # de nenhum arquivo de vídeo/imagem de apoio). Vieram de uma sessão
    # em que o usuário pediu "coisas simples" além das 58 nativas.
    # Variáveis disponíveis na expressão: X,Y (posição do pixel), W,H
    # (dimensões do quadro), A,B (cor do pixel de entrada 1/2), P
    # (progresso da transição, 0 a 1).
    "blinds_h": "if(lt(mod(Y,30)/30,P),B,A)",  # persianas horizontais
    "blinds_v": "if(lt(mod(X,30)/30,P),B,A)",  # persianas verticais
    "checkerboard": "if(lt(mod(floor(X/30)+floor(Y/30),2),1),if(lt(P,0.35),A,B),if(lt(P,0.65),A,B))",  # xadrez
    "noise_dissolve": "if(lt(abs(sin(X*12.9898+Y*78.233)*43758.5453-floor(sin(X*12.9898+Y*78.233)*43758.5453)),P),B,A)",  # dissolve com textura de ruído
    "iris_blur": "clip((P-hypot(X-W/2,Y-H/2)/hypot(W/2,H/2)+0.06)/0.12,0,1)*B+(1-clip((P-hypot(X-W/2,Y-H/2)/hypot(W/2,H/2)+0.06)/0.12,0,1))*A",  # íris circular com borda suave
    "diamond_iris": "clip((P-(abs(X-W/2)+abs(Y-H/2))/(W/2+H/2)+0.06)/0.12,0,1)*B+(1-clip((P-(abs(X-W/2)+abs(Y-H/2))/(W/2+H/2)+0.06)/0.12,0,1))*A",  # íris em losango (mesma ideia da iris_blur, mas com distância em "L" em vez de euclidiana)
    "pinwheel": "if(lt(mod((atan2(Y-H/2,X-W/2)+PI)/(2*PI)*6,1),P),B,A)",  # cata-vento -- 6 lâminas girando a partir do centro
    "wave_wipe": "if(lt(X/W+0.06*sin(Y/H*6.283*3),P),B,A)",  # varredura horizontal com borda ondulada (em vez de reta)
    "fade_grayscale": "(A*(1-P)+B*P)*(1-0.6*(1-2*abs(P-0.5)))+128*0.6*(1-2*abs(P-0.5))",  # dissolve comum, mas passando por um tom acinzentado no meio do caminho
}
# "Shutter" do DarkPlanner (obturador, lâminas, íris…) — ver cenas_dp.py
from cenas_dp import TRANSICOES_SHUTTER as _TRANSICOES_SHUTTER  # noqa: E402
TRANSICOES_CUSTOMIZADAS.update(_TRANSICOES_SHUTTER)


_PALETA_TRANSICOES: Dict[str, Any] = {}  # paleta da montagem em andamento (ver assemble_video)


def _transicao_xfade(tipo: str) -> str:
    """Trecho do filtro xfade (sem duração/offset) pra qualquer transição
    válida: nativa do ffmpeg, nossa (custom) ou do catálogo DarkPlanner ("dp:...")."""
    import dp_visual
    tipo_r, valor = dp_visual.resolver_transicao(tipo, _PALETA_TRANSICOES.get("atual"))
    if tipo_r == "expr":
        expr = re.sub(r"\bP\b", "(1-P)", valor).replace(",", "\\,")
        return f"transition=custom:expr='{expr}'"
    if tipo_r == "nossa" or valor in TRANSICOES_CUSTOMIZADAS:
        return f"transition=custom:expr='{expressao_xfade_custom(valor)}'"
    return f"transition={valor}"


def expressao_xfade_custom(tipo: str) -> str:
    """Expressão pronta pro xfade. As nossas são escritas com P indo de 0
    (só o clipe A) a 1 (só o B), mas no ffmpeg o P do modo custom vai de 1
    a 0 — sem inverter, a transição começava mostrando o PRÓXIMO trecho,
    voltava pro anterior e cortava seco no fim."""
    expr = re.sub(r"\bP\b", "(1-P)", TRANSICOES_CUSTOMIZADAS[tipo])
    return expr.replace(",", "\\,")

TRANSICOES_VALIDAS = {
    "none",  # sem transição -- corte seco (padrão, igual sempre foi)
    # Lista completa de transições NATIVAS do filtro `xfade` do ffmpeg
    # (`ffmpeg -h filter=xfade`) -- antes só usávamos um subconjunto de
    # 16; essas são robustas e vêm de fábrica com o ffmpeg, sem precisar
    # de nenhum asset (vídeo/imagem) nem shader externo.
    "fade", "fadeblack", "fadewhite", "fadegrays", "fadefast", "fadeslow",
    "dissolve", "pixelize", "distance", "radial", "hblur",
    "wipeleft", "wiperight", "wipeup", "wipedown",
    "wipetl", "wipetr", "wipebl", "wipebr",
    "slideleft", "slideright", "slideup", "slidedown",
    "smoothleft", "smoothright", "smoothup", "smoothdown",
    "circleopen", "circleclose", "circlecrop", "rectcrop",
    "vertopen", "vertclose", "horzopen", "horzclose",
    "diagtl", "diagtr", "diagbl", "diagbr",
    "hlslice", "hrslice", "vuslice", "vdslice",
    "hlwind", "hrwind", "vuwind", "vdwind",
    "squeezeh", "squeezev", "zoomin",
    "coverleft", "coverright", "coverup", "coverdown",
    "revealleft", "revealright", "revealup", "revealdown",
} | set(TRANSICOES_CUSTOMIZADAS)
# catálogo de transições do DarkPlanner ("dp:<id>", ver dp_visual.py)
import dp_visual as _dp_visual  # noqa: E402
TRANSICOES_VALIDAS |= {t["id"] for t in _dp_visual.transicoes()}


def _concat_clips_with_transitions(
    clip_paths: List[str],
    durations: List[float],
    output_path: str,
    work_dir: str,
    transition_type: str = "none",
    transition_duration: float = 0.6,
) -> str:
    """Concatena os clipes com uma TRANSIÇÃO entre cada par consecutivo
    (crossfade, wipe, slide, etc — ver `TRANSICOES_VALIDAS`), usando o
    filtro `xfade` do ffmpeg em cadeia.

    `transition_type="none"` (padrão) cai pro `_concat_clips` de sempre
    — corte seco, sem re-codificar (mais rápido). Qualquer outro tipo
    PRECISA re-codificar (o `xfade` mistura de verdade os quadros de um
    clipe com o próximo, então não dá pra só "colar" os arquivos como
    o modo rápido faz).

    `durations`: a duração de CADA clipe em `clip_paths`, na mesma
    ordem — usada pra calcular o `offset` (o instante, na linha do
    tempo ACUMULADA, em que cada transição começa) sem precisar rodar
    `ffprobe` em cada arquivo de novo (os clipes já foram normalizados
    pra durar exatamente isso).
    """
    if transition_type not in TRANSICOES_VALIDAS:
        raise VideoAssemblyError(f"transition_type precisa ser um de {sorted(TRANSICOES_VALIDAS)} (recebi {transition_type!r}).")
    if len(clip_paths) != len(durations):
        raise VideoAssemblyError(
            f"clip_paths ({len(clip_paths)}) e durations ({len(durations)}) precisam ter o mesmo tamanho."
        )
    if transition_type == "none" or len(clip_paths) < 2:
        return _concat_clips(clip_paths, output_path, work_dir)
    try:
        transition_duration = max(0.05, float(transition_duration))
    except (TypeError, ValueError):
        transition_duration = 0.6

    args: List[str] = []
    for p in clip_paths:
        args += ["-i", p]

    filtro_partes = []
    tempo_acumulado = durations[0]
    rotulo_anterior = "0:v"
    for i in range(1, len(clip_paths)):
        # a transição não pode durar mais que a METADE do clipe mais
        # curto dos dois envolvidos -- senão ela "comeria" o clipe
        # inteiro (ou pior, um offset negativo, que o xfade rejeita).
        d = min(transition_duration, durations[i - 1] / 2, durations[i] / 2)
        d = max(0.05, d)
        offset = max(0.0, tempo_acumulado - d)
        rotulo_saida = f"v{i}" if i < len(clip_paths) - 1 else "vout"
        filtro_partes.append(
            f"[{rotulo_anterior}][{i}:v]xfade={_transicao_xfade(transition_type)}:duration={d:.3f}:offset={offset:.3f}[{rotulo_saida}]"
        )
        tempo_acumulado = tempo_acumulado - d + durations[i]
        rotulo_anterior = rotulo_saida

    args += [
        "-filter_complex", ";".join(filtro_partes), "-map", "[vout]",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        output_path,
    ]
    _run_ffmpeg(args, timeout=600)
    return output_path


def planejar_transicoes(
    segments: List[VideoSegment],
    transition_type: str = "none",
    transition_duration: float = 0.6,
) -> List[tuple]:
    """Uma transição por EMENDA (entre o trecho i e o i+1): [(tipo, duração)].

    Cada trecho pode escolher a sua (`segment.transition` = transição PARA o
    próximo trecho; None/"global" = usa a global do vídeo). A duração é
    limitada à metade do menor dos dois trechos envolvidos; "none" = corte seco.
    """
    plano = []
    for i in range(len(segments) - 1):
        seg = segments[i]
        tipo = getattr(seg, "transition", None) or "global"
        if tipo == "global":
            tipo = transition_type or "none"
        if tipo not in TRANSICOES_VALIDAS:
            tipo = "none"
        dur = getattr(seg, "transition_duration", None)
        try:
            dur = float(dur) if dur is not None else float(transition_duration)
        except (TypeError, ValueError):
            dur = 0.6
        if tipo == "none":
            plano.append(("none", 0.0))
            continue
        dur = min(dur, segments[i].duration / 2, segments[i + 1].duration / 2)
        plano.append((tipo, max(0.05, round(dur, 3))))
    return plano


TRANSICOES_POR_LOTE = 20  # quantos clipes cada comando do ffmpeg junta de uma vez


def _xfade_lote(clip_paths: List[str], durations: List[float], plano: List[tuple], output_path: str, work_dir: str) -> float:
    """Junta UM lote de clipes com as transições do plano (uma cadeia xfade/
    concat). O grafo vai num arquivo (`-filter_complex_script`) — com dezenas
    de trechos, a linha de comando passava do limite do Windows (~32 mil
    caracteres) e a montagem com transição falhava. Cada entrada é igualada
    (fps, base de tempo, SAR, formato) antes, porque o xfade recusa entradas
    com base de tempo diferente. Devolve a duração do resultado."""
    partes = []
    for i in range(len(clip_paths)):
        partes.append(f"[{i}:v]fps={TARGET_FPS},settb=AVTB,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[in{i}]")
    acumulado = durations[0]
    anterior = "in0"
    for i in range(1, len(clip_paths)):
        tipo, d = plano[i - 1]
        saida = f"v{i}" if i < len(clip_paths) - 1 else "vout"
        if tipo == "none" or d <= 0:
            partes.append(f"[{anterior}][in{i}]concat=n=2:v=1:a=0[{saida}]")
            acumulado += durations[i]
        else:
            offset = max(0.0, acumulado - d)
            partes.append(f"[{anterior}][in{i}]xfade={_transicao_xfade(tipo)}:duration={d:.3f}:offset={offset:.3f}[{saida}]")
            acumulado = acumulado - d + durations[i]
        anterior = saida
    if len(clip_paths) == 1:
        partes.append("[in0]null[vout]")
    script = os.path.join(work_dir, f"_transicoes_{uuid.uuid4().hex[:8]}.txt")
    with open(script, "w", encoding="utf-8") as f:
        f.write(";\n".join(partes))
    args: List[str] = []
    for pth in clip_paths:
        args += ["-i", pth]
    args += [
        "-filter_complex_script", script, "-map", "[vout]",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", str(TARGET_FPS),
        output_path,
    ]
    try:
        try:
            _run_ffmpeg(args, timeout=1800)
        except VideoAssemblyError as exc:
            # ffmpeg 8+ trocou `-filter_complex_script arq` por `-/filter_complex arq`
            if "filter_complex_script" not in str(exc) or "nrecognized option" not in str(exc) and "not found" not in str(exc):
                raise
            k = args.index("-filter_complex_script")
            _run_ffmpeg(args[:k] + ["-/filter_complex"] + args[k + 1:], timeout=1800)
    finally:
        try:
            os.remove(script)
        except OSError:
            pass
    return acumulado


def _concat_clips_com_plano(clip_paths: List[str], durations: List[float], plano: List[tuple], output_path: str, work_dir: str) -> str:
    """Igual a `_concat_clips_with_transitions`, mas com uma transição
    própria por emenda (`plano`, ver `planejar_transicoes`) — emendas "none"
    viram corte seco dentro da mesma cadeia.

    `durations` = duração REAL de cada clipe. A montagem estica cada clipe
    pela duração da transição que vem depois dele, então a sobreposição sai
    desse "rabo" extra e o vídeo final continua com a duração do áudio
    (antes, cada transição encurtava o vídeo e a narração era cortada no fim).

    Muitos trechos: junta em lotes de `TRANSICOES_POR_LOTE` e depois junta os
    lotes (com a transição da emenda entre eles). Se o ffmpeg recusar alguma
    transição, cai pro corte seco em vez de perder a montagem inteira.
    """
    if len(clip_paths) != len(durations) or len(plano) != max(0, len(clip_paths) - 1):
        raise VideoAssemblyError("clip_paths, durations e plano de transições com tamanhos incompatíveis.")
    if len(clip_paths) < 2 or all(t == "none" for t, _d in plano):
        return _concat_clips(clip_paths, output_path, work_dir)

    try:
        caminhos, duracoes, emendas = list(clip_paths), list(durations), list(plano)
        rodada = 0
        while len(caminhos) > TRANSICOES_POR_LOTE:
            novos, novas_dur, novas_emendas = [], [], []
            for ini in range(0, len(caminhos), TRANSICOES_POR_LOTE):
                fim = min(ini + TRANSICOES_POR_LOTE, len(caminhos))
                saida = os.path.join(work_dir, f"_lote_{rodada}_{ini:04d}.mp4")
                dur = _xfade_lote(caminhos[ini:fim], duracoes[ini:fim], emendas[ini:fim - 1], saida, work_dir)
                novos.append(saida)
                novas_dur.append(dur)
                if fim < len(caminhos):
                    novas_emendas.append(emendas[fim - 1])  # a emenda entre um lote e o próximo
            caminhos, duracoes, emendas = novos, novas_dur, novas_emendas
            rodada += 1
        _xfade_lote(caminhos, duracoes, emendas, output_path, work_dir)
        return output_path
    except VideoAssemblyError as exc:
        # transição recusada pelo ffmpeg (versão antiga, nome desconhecido...):
        # monta com corte seco, cortando o "rabo" extra de cada clipe pra não
        # dessincronizar da narração.
        print(f"[transições] falhou, usando corte seco: {str(exc)[-300:]}", flush=True)
        extras = [d for _t, d in plano] + [0.0]
        cortados = []
        for i, (pth, dur) in enumerate(zip(clip_paths, durations)):
            if extras[i] > 0:
                cortado = os.path.join(work_dir, f"_sem_transicao_{i:04d}.mp4")
                _run_ffmpeg(["-i", pth, "-t", f"{dur - extras[i]:.3f}", "-c:v", "libx264", "-preset", "veryfast",
                             "-pix_fmt", "yuv420p", "-an", cortado])
                cortados.append(cortado)
            else:
                cortados.append(pth)
        return _concat_clips(cortados, output_path, work_dir)


def _mux_audio(video_only_path: str, audio_path: str, output_path: str) -> str:
    """Junta o vídeo concatenado (sem áudio) com a narração original."""
    _run_ffmpeg([
        "-i", video_only_path, "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", output_path,
    ])
    return output_path


def _mux_audio_with_music(
    video_only_path: str,
    narration_path: str,
    music_path: str,
    output_path: str,
    music_volume: float = 0.18,
) -> str:
    """Junta o vídeo concatenado (sem áudio) com a narração ORIGINAL em
    volume cheio, misturada com uma trilha sonora de fundo em volume bem
    mais baixo (padrão: 18% do volume) — pra não cobrir a voz. A trilha
    é repetida em loop se for mais curta que a narração, e cortada no
    tamanho certo se for mais longa.

    music_volume: 0.0 a 1.0 — quanto mais perto de 0, mais discreta a
    trilha fica atrás da narração.
    """
    narration_duration = _probe_duration(narration_path)
    _run_ffmpeg([
        "-i", video_only_path,
        "-i", narration_path,
        "-stream_loop", "-1", "-i", music_path,
        "-filter_complex",
        f"[2:a]volume={music_volume:.3f}[music];"
        f"[1:a][music]amix=inputs=2:duration=first:dropout_transition=0[aout]",
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", f"{narration_duration:.3f}",
        output_path,
    ])
    return output_path


_OVERLAY_POSITION_EXPRESSIONS = {
    "top-left": ("20", "20"),
    "top-center": ("(main_w-overlay_w)/2", "20"),
    "top-right": ("main_w-overlay_w-20", "20"),
    "middle-left": ("20", "(main_h-overlay_h)/2"),
    "middle-center": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
    "middle-right": ("main_w-overlay_w-20", "(main_h-overlay_h)/2"),
    "bottom-left": ("20", "main_h-overlay_h-20"),
    "bottom-center": ("(main_w-overlay_w)/2", "main_h-overlay_h-20"),
    "bottom-right": ("main_w-overlay_w-20", "main_h-overlay_h-20"),
}


def _normalize_cutaway_clip(
    input_path: str,
    output_path: str,
    target_width: int,
    target_height: int,
    has_own_audio: bool,
) -> str:
    """Ajusta o clipe de CORTE (inserção real, não overlay) pra mesma
    resolução/fps/codec do resto do vídeo, preservando a duração
    ORIGINAL do clipe (diferente de `_normalize_clip`, que estica/corta
    pra bater com um trecho — aqui é o clipe que dita quanto tempo o
    corte dura, não o contrário). Sempre gera uma faixa de áudio (AAC),
    mesmo quando o clipe original não tem som (silêncio), pra poder
    concatenar sem re-codificar de novo depois.
    """
    scale_pad = (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )
    args = ["-i", input_path]
    if not has_own_audio:
        args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    args += ["-vf", scale_pad, "-r", str(TARGET_FPS)]
    if has_own_audio:
        args += ["-map", "0:v", "-map", "0:a?", "-c:a", "aac", "-shortest"]
    else:
        args += ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-shortest"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", output_path]
    _run_ffmpeg(args)
    return output_path


def shift_timestamps_for_cutaways(
    items: List[Dict[str, Any]],
    cutaways_with_duration: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Ajusta uma lista de itens com tempo (`start`/`end`, ex: as
    palavras da legenda) pra refletir o deslocamento causado por
    cortes reais já inseridos no vídeo final.

    Bug real encontrado: um corte real (`insert_cutaways`) empurra tudo
    que vem DEPOIS do seu ponto de inserção pra frente, pela duração
    do próprio clipe inserido — mas qualquer coisa com tempo ABSOLUTO
    calculado a partir do áudio ORIGINAL (como a legenda, gerada a
    partir da transcrição do áudio antes de qualquer corte) não sabia
    disso, e ficava fora de sincronia depois que um corte era aplicado
    (uma palavra dita em t=8s no áudio original aparecia ainda em t=8s
    na legenda, mesmo que um corte de 5s antes desse ponto tivesse
    empurrado a fala de verdade pra t=13s no vídeo final).

    cutaways_with_duration: mesma lista usada em `insert_cutaways`,
    mas cada item precisa ter também uma chave "duration" (segundos)
    com a duração do próprio clipe inserido.
    """
    if not cutaways_with_duration:
        return items

    sorted_cuts = sorted(cutaways_with_duration, key=lambda c: c["insertion_point"])
    adjusted = []
    for item in items:
        shift = 0.0
        removido = False
        for cut in sorted_cuts:
            ponto = float(cut["insertion_point"])
            fim = float(cut.get("remove_ate") or ponto)
            if fim > ponto:
                # chamada que SUBSTITUI um trecho da narração: o que estava
                # dentro dele some; o que vem depois anda (clipe - trecho tirado)
                if ponto <= item["start"] < fim:
                    removido = True
                    break
                if item["start"] >= fim:
                    shift += cut["duration"] - (fim - ponto)
            elif ponto <= item["start"]:
                shift += cut["duration"]
        if not removido:
            adjusted.append({**item, "start": item["start"] + shift, "end": item["end"] + shift})
    return adjusted


def insert_cutaways(
    base_video_path: str,
    cutaways: List[Dict[str, Any]],
    output_path: str,
    work_dir: str,
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
) -> str:
    """Insere um ou mais CORTES REAIS num ponto específico do vídeo já
    pronto (com narração) — diferente de `apply_overlays()` (que só
    sobrepõe uma camada por cima, sem mudar a duração), isso literalmente
    CORTA o vídeo e o áudio naquele ponto e insere o clipe indicado
    inteiro ali, empurrando tudo que vem depois pra frente. O vídeo
    final sempre fica MAIS LONGO pela duração do clipe inserido.

    Cada item de `cutaways`:
        {"resolved_path": str, "insertion_point": float (segundos,
         absoluto no vídeo ORIGINAL, antes de qualquer corte já
         processado — não precisa recalcular deslocamento entre cortes
         diferentes, a função cuida disso processando em ordem),
         "audio_mode": "pause" | "continue",
         "remove_ate": float opcional — chamada de inscreva-se/venda/link
            (ver chamadas.py): o trecho [insertion_point, remove_ate] do
            vídeo base (imagem E narração) sai, e o clipe entra no lugar}

        "pause": a narração fica em silêncio durante o corte — toca só
            o áudio do próprio clipe inserido, se tiver (senão,
            silêncio mesmo).
        "continue": mesma lógica de áudio do clipe inserido — a
            diferença entre os dois modos é só semântica/documentação
            por enquanto (v1); os dois tocam o áudio do próprio clipe
            quando existe. Distinguidos como campos separados desde já
            pra não quebrar compatibilidade quando "continue" ganhar um
            comportamento diferente de verdade (ex: manter a trilha
            sonora de fundo tocando por cima do corte).

    Sem cortes, só copia o vídeo base sem recodificar.
    """
    if not cutaways:
        if os.path.abspath(base_video_path) != os.path.abspath(output_path):
            shutil.copy(base_video_path, output_path)
        return output_path

    ordered = sorted(cutaways, key=lambda c: c["insertion_point"])

    pieces: List[str] = []
    cursor = 0.0
    base_duration = _probe_duration(base_video_path)

    for idx, cut in enumerate(ordered):
        point = max(cursor, min(base_duration, float(cut["insertion_point"])))
        if point > cursor:
            piece_path = os.path.join(work_dir, f"_cutaway_before_{idx}_{uuid.uuid4().hex[:8]}.mp4")
            _run_ffmpeg([
                "-i", base_video_path, "-ss", f"{cursor:.3f}", "-to", f"{point:.3f}",
                "-r", str(TARGET_FPS),
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", piece_path,
            ])
            pieces.append(piece_path)

        cutaway_path = cut["resolved_path"]
        has_audio = _has_audio_stream(cutaway_path)
        normalized_cutaway = os.path.join(work_dir, f"_cutaway_clip_{idx}_{uuid.uuid4().hex[:8]}.mp4")
        _normalize_cutaway_clip(cutaway_path, normalized_cutaway, target_width, target_height, has_audio)
        pieces.append(normalized_cutaway)

        fim = cut.get("remove_ate")
        cursor = max(point, min(base_duration, float(fim))) if fim is not None else point

    if cursor < base_duration:
        final_piece = os.path.join(work_dir, f"_cutaway_after_{uuid.uuid4().hex[:8]}.mp4")
        _run_ffmpeg([
            "-i", base_video_path, "-ss", f"{cursor:.3f}",
            "-r", str(TARGET_FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", final_piece,
        ])
        pieces.append(final_piece)

    try:
        _concat_clips(pieces, output_path, work_dir)
    finally:
        for piece_path in pieces:
            try:
                os.remove(piece_path)
            except OSError:
                pass

    return output_path


def apply_overlays(
    base_video_path: str,
    overlays: List[Dict[str, Any]],
    output_path: str,
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
) -> str:
    """Compõe uma lista de overlays (imagem, vídeo, ou TEXTO puro) sobre
    o vídeo base já pronto (com áudio), cada um ativo só durante sua
    PRÓPRIA janela de tempo — pode ser um trecho específico, ou
    atravessar o vídeo inteiro, independente dos segmentos da narração.

    Cada item de `overlays`, pra imagem/vídeo:
        {"resolved_path": str (arquivo já baixado/localizado),
         "media_type": "image" | "video",
         "start": float, "end": float (segundos, absolutos no vídeo final),
         "position": uma das 9 chaves de _OVERLAY_POSITION_EXPRESSIONS
             (padrão: "top-right"), OU "x_percent"/"y_percent" (0-100,
             posicionamento livre — tem prioridade sobre "position" se
             algum dos dois estiver presente),
         "size_percent": largura do overlay como % da largura do vídeo
             final (padrão: 20) — a altura escala proporcionalmente,
             preservando a proporção original da imagem/vídeo.}

    Pra TEXTO puro (título/chamada independente de um trecho da
    narração — diferente do `on_screen_text` de um segmento, esse tem
    tempo/posição PRÓPRIOS, podendo atravessar vários trechos ou o
    vídeo inteiro):
        {"media_type": "text", "text": str,
         "start": float, "end": float,
         "style": {...} (mesmo formato de `on_screen_text_style` — ver
             `_build_drawtext_filter()`: position/x_percent/y_percent/
             font_size/border/background/font)}

    Overlays de VÍDEO mais curtos que sua própria janela [start, end]
    repetem em loop pra preencher o tempo (mesmo espírito do loop nos
    clipes de fundo). Sem overlays, só copia o vídeo base sem
    recodificar.
    """
    if not overlays:
        if os.path.abspath(base_video_path) != os.path.abspath(output_path):
            shutil.copy(base_video_path, output_path)
        return output_path

    base_duration = _probe_duration(base_video_path)
    trilhas_tmp: List[str] = []
    # 🎭 v84_237: as camadas do react (cada pose/legenda de um mesmo personagem no mesmo lugar) viram UMA trilha só
    # (lista do concat) — no Windows centenas de "-i arquivo.png" estouravam a linha de comando (WinError 206) e a
    # troca de pose entre duas camadas separadas piscava
    overlays = _juntar_trilhas(overlays, target_width, os.path.dirname(os.path.abspath(output_path)), trilhas_tmp)
    inputs: List[str] = ["-i", base_video_path]
    filter_parts: List[str] = []
    current_label = "[0:v]"
    next_input_index = 1

    for idx, ov in enumerate(overlays):
        media_type = ov.get("media_type", "video")
        next_label = f"[tmp{idx}]" if idx < len(overlays) - 1 else "[vout]"
        start = max(0.0, float(ov["start"]))
        end = max(start, float(ov["end"]))

        if media_type == "text":
            # texto puro não consome nenhum input novo — desenha direto
            # em cima do vídeo atual, só ativo na sua própria janela.
            st_ov = dict(ov.get("style") or {})
            if st_ov.get("animation") in ("fade", "slide", "zoom"):
                # animação na janela do PRÓPRIO overlay (tempo do vídeo inteiro): o drawtext já põe o enable
                st_ov["start_offset"], st_ov["end_offset"] = start, end
                text_filter = _build_drawtext_filter(ov.get("text", ""), target_height, st_ov)
                filter_parts.append(f"{current_label}{text_filter}{next_label}")
            else:
                text_filter = _build_drawtext_filter(ov.get("text", ""), target_height, ov.get("style"))
                filter_parts.append(
                    f"{current_label}{text_filter}:enable='between(t,{start:.3f},{end:.3f})'{next_label}"
                )
            current_label = next_label
            continue

        if media_type == "trilha":
            k = next_input_index
            next_input_index += 1
            inputs += ["-f", "concat", "-safe", "0", "-i", ov["lista"]]
            xp, yp = ov["x_percent"] / 100, ov["y_percent"] / 100
            if ov.get("ancora") == "centro":
                x_expr, y_expr = f"(main_w*{xp:.5f}-overlay_w/2)", f"(main_h*{yp:.5f}-overlay_h/2)"
            else:
                x_expr, y_expr = f"(main_w-overlay_w)*{xp:.5f}", f"(main_h-overlay_h)*{yp:.5f}"
            x_expr, y_expr = x_expr + _mov_expr(ov.get("mov"), "x"), y_expr + _mov_expr(ov.get("mov"), "y")
            # 🧠 sem "fps": cada imagem é UM quadro com o tempo dela e o overlay segura o último até o próximo. Com fps=25
            # o ffmpeg duplicava de uma vez todos os quadros de um trecho parado longo (ex.: 5 min sem cena = 7500
            # quadros 1920×1080 na fila) → "Cannot allocate memory"
            filter_parts.append(f"[{k}:v]format=rgba,setpts=PTS-STARTPTS+{start:.3f}/TB[tr{idx}]")
            filter_parts.append(f"{current_label}[tr{idx}]overlay=x='{x_expr}':y='{y_expr}':"
                                f"enable='between(t,{start:.3f},{end:.3f})':eof_action=pass{next_label}")
            current_label = next_label
            continue

        if ov.get("personagem"):  # 🧍 v84_185: personagem do canal (PNG transparente) com entrada/saída e boca
            next_input_index = _overlay_personagem(ov, idx, start, end, current_label, next_label, inputs, filter_parts,
                                                   next_input_index, target_width)
            current_label = next_label
            continue

        media_path = ov["resolved_path"]
        is_video = media_type == "video"
        overlay_width = max(2, round(target_width * ov.get("size_percent", 20) / 100))
        # largura sempre PAR (requisito do libx264 com yuv420p) — ímpar
        # causa erro do ffmpeg em alguns casos de escala.
        if overlay_width % 2 != 0:
            overlay_width += 1

        input_index = next_input_index
        next_input_index += 1
        if is_video:
            inputs += ["-stream_loop", "-1", "-i", media_path]
        else:
            inputs += ["-i", media_path]  # 🧠 v84_237: um quadro só (o overlay repete) — sem gerar 25 quadros/s

        scale_label = f"[ov{idx}]"
        espelho = ",hflip" if ov.get("espelhar") else ""  # 🎭 v84_237: a TV do react espelhada
        filter_parts.append(f"[{input_index}:v]scale={overlay_width}:-2{espelho}{scale_label}")

        if "x_percent" in ov or "y_percent" in ov:
            xp = max(0.0, min(100.0, float(ov.get("x_percent", 80))))
            yp = max(0.0, min(100.0, float(ov.get("y_percent", 20))))
            if ov.get("ancora") == "centro":  # 🎭 v84_236: x/y = o CENTRO do overlay (igual ao monitor do Estúdio)
                x_expr = f"(main_w*{xp/100:.5f}-overlay_w/2)"
                y_expr = f"(main_h*{yp/100:.5f}-overlay_h/2)"
            else:
                x_expr = f"(main_w-overlay_w)*{xp/100:.5f}"
                y_expr = f"(main_h-overlay_h)*{yp/100:.5f}"
        else:
            x_expr, y_expr = _OVERLAY_POSITION_EXPRESSIONS.get(
                ov.get("position", "top-right"), _OVERLAY_POSITION_EXPRESSIONS["top-right"]
            )
        if ov.get("mov"):  # 🌄 parallax
            x_expr, y_expr = f"'{x_expr}{_mov_expr(ov['mov'], 'x')}'", f"'{y_expr}{_mov_expr(ov['mov'], 'y')}'"
        filter_parts.append(
            f"{current_label}{scale_label}overlay={x_expr}:{y_expr}:"
            f"enable='between(t,{start:.3f},{end:.3f})'{'' if is_video else ':eof_action=repeat'}{next_label}"
        )
        current_label = next_label

    filter_complex = ";".join(filter_parts)

    # 🎭 v84_236: com muitas camadas (o react tem uma por expressão/legenda) o grafo passa do limite da linha de
    # comando do Windows (~32 mil caracteres) — vai num arquivo
    script = None
    if len(filter_complex) > 6000:
        script = os.path.join(os.path.dirname(os.path.abspath(output_path)), f"_overlays_{uuid.uuid4().hex[:8]}.txt")
        with open(script, "w", encoding="utf-8") as f:
            f.write(";\n".join(filter_parts))
    args = inputs + (["-filter_complex_script", script] if script else ["-filter_complex", filter_complex]) + [
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-t", f"{base_duration:.3f}",  # nunca deixa um overlay em loop esticar o video final
        output_path,
    ]
    # ⏱ v84_228: o limite acompanha o tamanho do trabalho (vídeo de 13 min com 40 camadas não cabe em 5 min)
    limite = tempo_limite_overlays(base_duration, len(overlays))
    try:
        try:
            _run_ffmpeg(args, timeout=limite)
        except VideoAssemblyError as exc:
            # ffmpeg 8+ trocou `-filter_complex_script arq` por `-/filter_complex arq`
            if not script or "filter_complex_script" not in str(exc) or ("nrecognized option" not in str(exc) and "not found" not in str(exc)):
                raise
            k = args.index("-filter_complex_script")
            _run_ffmpeg(args[:k] + ["-/filter_complex"] + args[k + 1:], timeout=limite)
    finally:
        for tmp in ([script] if script else []) + trilhas_tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return output_path


RESP_W = 2 * 3.14159265 / 2.6  # 🫁 um ciclo de respiração a cada 2,6 s


def _mov_expr(movs: Any, eixo: str) -> str:
    """🌄 v84_237: o deslocamento da camada no tempo (parallax da 🎞 Animação 2D / câmera tremida), somado ao x ou y do
    overlay. Cada mov: {"a","b","dx","dy"} (fração de W/H na cena toda, de -d/2 a +d/2) ou {"a","b","tremor"}
    (tremida que some em 0,8 s). "" = parado. Mesma conta do anime2d.deslocamento (a prévia)."""
    termos = []
    for m in (movs or [])[:120]:
        try:
            a, b = float(m["a"]), float(m["b"])
        except (KeyError, TypeError, ValueError):
            continue
        if b <= a:
            continue
        if m.get("resp"):  # 🫁 v84_238c: o personagem "respira" (sobe e desce de leve, sem parar) — tipo Jashin-chan
            if eixo == "y":
                termos.append(f"between(t,{a:.3f},{b:.3f})*main_h*{float(m['resp']):.5f}*sin(t*{RESP_W:.4f}+{float(m.get('f') or 0):.3f})")
            continue
        if m.get("pulo"):  # 🦘 o pulinho de reação quando a emoção muda (sobe e volta em `b - a`)
            if eixo == "y":
                termos.append(f"between(t,{a:.3f},{b:.3f})*main_h*{-float(m['pulo']):.5f}*sin(PI*(t-{a:.3f})/{b - a:.3f})")
            continue
        if "de" in m:  # 🚶 v84_238: andar — de `de` até `para` (fração da largura) entre a e b, parado até z
            if eixo != "x":
                continue
            z = float(m.get("z") or b)
            de, para = float(m["de"]), float(m.get("para") or 0)
            termos.append(f"between(t,{a:.3f},{z:.3f})*main_w*({de:.5f}+({para - de:.5f})*min(1,max(0,(t-{a:.3f})/{b - a:.3f})))")
            continue
        if m.get("tremor"):
            amp = float(m["tremor"]) * (1 if eixo == "x" else 0.6)
            onda = f"sin(t*47)" if eixo == "x" else "sin(t*31+1)"
            termos.append(f"between(t,{a:.3f},{b:.3f})*main_w*{amp:.5f}*max(0,1-(t-{a:.3f})/0.8)*{onda}")
            continue
        d = float(m.get("dx" if eixo == "x" else "dy") or 0)
        if abs(d) < 1e-5:
            continue
        lado = "main_w" if eixo == "x" else "main_h"
        termos.append(f"between(t,{a:.3f},{b:.3f})*{lado}*{d:.5f}*((t-{a:.3f})/{b - a:.3f}-0.5)")
    return "".join("+" + x for x in termos)


def _trilha_de(ov: Dict[str, Any]) -> str:
    """A trilha do overlay — os do react feitos antes da v84_237 não têm a chave: usa o tipo da camada (o lugar e o
    tamanho iguais é que decidem se juntam)."""
    t = ov.get("trilha") or ""
    if not t and str(ov.get("personagem") or "").startswith("react_"):
        t = str(ov["personagem"])
    return t


def _trilha_ok(ov: Dict[str, Any]) -> bool:
    return (bool(_trilha_de(ov)) and bool(ov.get("personagem")) and ov.get("media_type", "image") == "image"
            and not ov.get("anim_video") and (ov.get("anim_in") or "nenhuma") == "nenhuma"
            and (ov.get("anim_out") or "nenhuma") == "nenhuma" and os.path.isfile(str(ov.get("resolved_path") or "")))


def _png_valido(caminho: str) -> bool:
    """O PNG abre de verdade (um arquivo pela metade — montagem interrompida no meio — não serve de cache)."""
    try:
        from PIL import Image
        with Image.open(caminho) as im:
            im.verify()
        return True
    except Exception:  # noqa: BLE001
        return False


def _salvar_png(im: Any, destino: str) -> None:
    """Salva num temporário e troca de uma vez — nunca fica um PNG pela metade com o nome do cache."""
    tmp = f"{destino}.{uuid.uuid4().hex[:6]}.tmp.png"
    im.save(tmp)
    os.replace(tmp, destino)


def _png_na_tela(caminho: str, largura: int, espelhar: bool, w: int, h: int) -> str:
    """A imagem no tamanho da trilha (todas do mesmo tamanho: centralizada numa tela transparente w×h)."""
    from PIL import Image
    pronto = _png_no_tamanho(caminho, largura, espelhar) or caminho
    base, _ext = os.path.splitext(pronto)
    destino = f"{base}__t{w}x{h}.png"
    if os.path.isfile(destino) and os.path.getmtime(destino) >= os.path.getmtime(pronto) and _png_valido(destino):
        return destino
    with Image.open(pronto) as im:
        im = im.convert("RGBA")
        if im.size == (w, h):
            return pronto
        tela = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        tela.paste(im, ((w - im.width) // 2, (h - im.height) // 2), im)
        _salvar_png(tela, destino)
    return destino


def _juntar_trilhas(overlays: List[Dict[str, Any]], target_width: int, pasta: str, tmp: List[str]) -> List[Dict[str, Any]]:
    """Camadas com a mesma `trilha` e o mesmo lugar/tamanho → um overlay "trilha" (concat de imagens com duração).
    Mantém a ordem (a trilha entra onde estava a 1ª camada dela). A 👄 boca alterna a cada 0,12 s nas janelas de fala,
    igual ao overlay normal; onde duas camadas se cruzam ganha a que vem depois (a que ficava por cima)."""
    from PIL import Image
    import math
    # 🛡 PNG estragado (montagem anterior interrompida no meio de salvar) não derruba a montagem: a camada sai
    ruins = [ov for ov in overlays if ov.get("media_type", "image") == "image" and str(ov.get("resolved_path") or "").lower().endswith(".png")
             and os.path.isfile(str(ov.get("resolved_path"))) and not _png_valido(str(ov["resolved_path"]))]
    if ruins:
        print(f"[overlays] {len(ruins)} imagem(ns) estragada(s) ignorada(s): " + ", ".join(os.path.basename(str(o["resolved_path"])) for o in ruins[:5]))
        overlays = [ov for ov in overlays if ov not in ruins]
    grupos: Dict[Any, List[int]] = {}
    for i, ov in enumerate(overlays):
        if _trilha_ok(ov):
            chave = (_trilha_de(ov), round(float(ov.get("size_percent", 30)), 3), round(float(ov.get("x_percent", 0)), 3),
                     round(float(ov.get("y_percent", 0)), 3), ov.get("ancora") or "", bool(ov.get("espelhar")))
            grupos.setdefault(chave, []).append(i)
    grupos = {k: v for k, v in grupos.items() if len(v) >= 2}
    if not grupos:
        return overlays
    trocar: Dict[int, Dict[str, Any]] = {}
    tirar = set()
    for n, (chave, idxs) in enumerate(grupos.items()):
        membros = [overlays[i] for i in idxs]
        largura = max(2, round(target_width * float(membros[0].get("size_percent", 30)) / 100))
        largura += largura % 2
        esp = bool(membros[0].get("espelhar"))
        # pedaços (a, b, imagem, prioridade)
        pedacos = []
        for pr, ov in enumerate(membros):
            a, b = max(0.0, float(ov["start"])), float(ov["end"])
            if b - a < 0.02:
                continue
            pedacos.append((a, b, ov["resolved_path"], pr * 2))
            boca = ov.get("boca_path") if ov.get("boca_path") and os.path.isfile(str(ov.get("boca_path"))) else None
            if boca:
                for ja, jb in ov.get("boca_janelas") or []:
                    ja, jb = max(a, float(ja)), min(b, float(jb))
                    k = math.floor((ja - a) / 0.24)
                    while a + 0.24 * k < jb:
                        x, y = max(ja, a + 0.24 * k), min(jb, a + 0.24 * k + 0.12)
                        if y > x:
                            pedacos.append((x, y, boca, pr * 2 + 1))
                        k += 1
        if not pedacos:
            continue
        t0, t1 = min(p[0] for p in pedacos), max(p[1] for p in pedacos)
        pontos = sorted({round(t, 4) for p in pedacos for t in (p[0], p[1])})
        seq: List[List[Any]] = []  # [img|None, a, b]
        # varredura: em cada intervalo elementar, a imagem do pedaço de maior prioridade que cobre o meio
        ativos = sorted(pedacos, key=lambda p: p[0])
        for a, b in zip(pontos, pontos[1:]):
            m = (a + b) / 2
            melhor = None
            for p in ativos:
                if p[0] > m:
                    break
                if p[0] <= m < p[1] and (melhor is None or p[3] > melhor[3]):
                    melhor = p
            img = melhor[2] if melhor else None
            if seq and seq[-1][0] == img:
                seq[-1][2] = b
            else:
                seq.append([img, a, b])
        # todas do mesmo tamanho (uma imagem que não abre — arquivo estragado — sai da trilha em vez de derrubar a montagem)
        tams = []
        ruins = set()
        for img in {x[0] for x in seq if x[0]}:
            pronto = _png_no_tamanho(img, largura, esp) or img
            try:
                with Image.open(pronto) as im:
                    tams.append(im.size)
            except Exception:  # noqa: BLE001
                ruins.add(img)
        if ruins:
            seq = [[None if x[0] in ruins else x[0], x[1], x[2]] for x in seq]
        if not tams:
            continue
        w = max(t[0] for t in tams)
        h = max(t[1] for t in tams)
        h += h % 2
        w += w % 2
        vazio = os.path.join(pasta, f"_trilha_vazia_{w}x{h}.png")
        if not os.path.isfile(vazio):
            Image.new("RGBA", (w, h), (0, 0, 0, 0)).save(vazio)
        prontos = {img: _png_na_tela(img, largura, esp, w, h) for img in {x[0] for x in seq if x[0]}}
        lista = os.path.join(pasta, f"_trilha_{n}_{uuid.uuid4().hex[:6]}.txt")
        linhas = ["ffconcat version 1.0"]
        ultimo = None
        # durações no passo dos quadros (25 fps), acumuladas a partir do início — pedacinho menor que 1 quadro some
        # sem empurrar o resto (a trilha não atrasa)
        for img, a, b in seq:
            qa, qb = round((a - t0) * 25), round((b - t0) * 25)
            if qb <= qa:
                continue
            arq = prontos[img] if img else vazio
            linhas.append("file '" + os.path.abspath(arq).replace("\\", "/").replace("'", "'\\''") + "'")
            linhas.append(f"duration {(qb - qa) / 25:.4f}")
            ultimo = arq
        if ultimo is None:
            continue
        linhas.append("file '" + os.path.abspath(ultimo).replace("\\", "/").replace("'", "'\\''") + "'")
        with open(lista, "w", encoding="utf-8") as f:
            f.write("\n".join(linhas) + "\n")
        tmp.append(lista)
        ov0 = membros[0]
        trocar[idxs[0]] = {"media_type": "trilha", "lista": lista, "start": t0, "end": t1,
                           "x_percent": float(ov0.get("x_percent", 0)), "y_percent": float(ov0.get("y_percent", 0)),
                           "ancora": ov0.get("ancora") or "",
                           # 🌄 cada cena com o seu movimento (as janelas não se cruzam: uma vez cada)
                           "mov": [dict(t) for t in {tuple(sorted(m.items())) for o in membros for m in (o.get("mov") or [])}]}
        tirar.update(idxs[1:])
    return [trocar.get(i, ov) for i, ov in enumerate(overlays) if i not in tirar]


def tempo_limite_overlays(duracao: float, n_overlays: int) -> int:
    """Segundos pro passo dos overlays: no mínimo 5 min; ~3x a duração do vídeo + 20 s por camada."""
    return int(max(300, float(duracao or 0) * 3 + 20 * max(0, n_overlays)))


def _png_no_tamanho(caminho: str, largura: int, espelhar: bool) -> Optional[str]:
    """A pose redimensionada (largura par) e espelhada uma vez só, guardada ao lado da original. None = deixa pro ffmpeg."""
    try:
        from PIL import Image, ImageOps
        base, _ext = os.path.splitext(caminho)
        destino = f"{base}__{largura}{'f' if espelhar else ''}.png"
        if os.path.isfile(destino) and os.path.getmtime(destino) >= os.path.getmtime(caminho) and _png_valido(destino):
            return destino
        with Image.open(caminho) as im:
            im = im.convert("RGBA")
            alt = max(2, round(im.height * largura / max(1, im.width)))
            alt += alt % 2
            im = im.resize((largura, alt), Image.LANCZOS)
            if espelhar:
                im = ImageOps.mirror(im)
            _salvar_png(im, destino)
        return destino
    except Exception:  # noqa: BLE001
        return None


def _overlay_personagem(ov: Dict[str, Any], idx: int, start: float, end: float, atual: str, proximo: str,
                        inputs: List[str], partes: List[str], n_in: int, target_width: int) -> int:
    """🧍 A personagem (PNG com transparência) só na janela dela: a imagem entra no ffmpeg SÓ por esse tempo
    (-t + setpts — não decodifica o PNG o vídeo inteiro), desliza do lado dela / aparece / some, e a 👄 boca alterna
    com a pose "_boca" enquanto ela fala (boca_janelas = os trechos com palavra). → o próximo índice de entrada."""
    dur = max(0.05, end - start)
    d = max(0.05, min(float(ov.get("anim_dur") or 0.35), dur / 3))
    largura = max(2, round(target_width * float(ov.get("size_percent", 30)) / 100))
    largura += largura % 2
    xp = max(0.0, min(100.0, float(ov.get("x_percent", 3)))) / 100
    yp = max(0.0, min(100.0, float(ov.get("y_percent", 100)))) / 100
    esquerda = (ov.get("lado") or ("esquerda" if xp < 0.5 else "direita")) == "esquerda"
    espelho = ",hflip" if ov.get("espelhar") else ""  # 🪞 v84_207
    centro = ov.get("ancora") == "centro"  # 📐 v84_191: x/y = o CENTRO da imagem (igual ao monitor do Estúdio)
    alvo = f"(main_w*{xp:.5f}-overlay_w/2)" if centro else f"(main_w-overlay_w)*{xp:.5f}"
    fora = "(-overlay_w)" if esquerda else "main_w"
    e_in, e_out = ov.get("anim_in") or "nenhuma", ov.get("anim_out") or "nenhuma"
    def _prog(tipo: str) -> str:
        p_in = f"min(1,(t-{start:.3f})/{d:.3f})" if e_in == tipo else "1"
        p_out = f"min(1,({end:.3f}-t)/{d:.3f})" if e_out == tipo else "1"
        prog = f"max(0,min({p_in},{p_out}))"
        return f"(1-(1-{prog})*(1-{prog}))"  # suaviza (ease-out)
    x = alvo
    if e_in == "deslizar" or e_out == "deslizar":  # do lado dela
        x = f"({fora}+(({alvo})-({fora}))*{_prog('deslizar')})"
    y_alvo = f"(main_h*{yp:.5f}-overlay_h/2)" if centro else f"(main_h-overlay_h)*{yp:.5f}"
    y = y_alvo
    if e_in == "subir" or e_out == "subir":  # de baixo pra cima
        y = f"(main_h+(({y_alvo})-main_h)*{_prog('subir')})"

    x, y = x + _mov_expr(ov.get("mov"), "x"), y + _mov_expr(ov.get("mov"), "y")  # 🌄 parallax / tremida
    parada = e_in != "aparecer" and e_out != "aparecer" and e_in != "deslizar" and e_out != "deslizar" \
        and e_in != "subir" and e_out != "subir"

    def _entrada(caminho: str, rot: str) -> int:
        nonlocal n_in
        # ⚡ v84_228: a pose já vai no tamanho e no lado certos (PNG pronto) — o ffmpeg não redimensiona/espelha
        # cada quadro (com ~40 poses num vídeo longo isso estourava o tempo da montagem)
        pronto = _png_no_tamanho(caminho, largura, bool(espelho))
        if parada:
            # 🧠 v84_237: imagem parada entra como UM quadro só (o overlay repete) — com "-loop 1" o ffmpeg fazia 25
            # quadros por segundo de cada camada e, num vídeo de 10 min, estourava a memória ("Cannot allocate memory")
            inputs.extend(["-i", pronto or caminho])
        else:
            inputs.extend(["-loop", "1", "-framerate", "25", "-t", f"{dur:.3f}", "-i", pronto or caminho])
        k = n_in
        n_in += 1
        fade = ""
        if e_in == "aparecer":
            fade += f",fade=t=in:st=0:d={d:.3f}:alpha=1"
        if e_out == "aparecer":
            fade += f",fade=t=out:st={max(0.0, dur - d):.3f}:d={d:.3f}:alpha=1"
        escala = "" if pronto else f"scale={largura}:-2{espelho},"
        partes.append(f"[{k}:v]{escala}format=rgba{fade},setpts=PTS+{start:.3f}/TB{rot}")
        return k

    anim = ov.get("anim_video") if ov.get("anim_video") and os.path.isfile(str(ov.get("anim_video"))) else None
    if anim:  # 🎞 v84_193: o clipe animado (WebM VP9 com alfa); a boca já mexe nele
        k = n_in
        n_in += 1
        loop = ["-stream_loop", "-1"] if (ov.get("anim_modo") or "repetir") == "repetir" else []
        inputs.extend(["-c:v", "libvpx-vp9"] + loop + ["-t", f"{dur:.3f}", "-i", anim])
        fade = ""
        if e_in == "aparecer":
            fade += f",fade=t=in:st=0:d={d:.3f}:alpha=1"
        if e_out == "aparecer":
            fade += f",fade=t=out:st={max(0.0, dur - d):.3f}:d={d:.3f}:alpha=1"
        # clipe mais curto que a aparição ("uma vez"): segura o último quadro (= a pose) até o fim — o fade de saída também
        partes.append(f"[{k}:v]fps=25,tpad=stop_mode=clone:stop_duration={dur:.3f},trim=duration={dur:.3f},"
                      f"scale={largura}:-2{espelho},format=rgba{fade},setpts=PTS-STARTPTS+{start:.3f}/TB[pp{idx}]")
        partes.append(f"{atual}[pp{idx}]overlay=x='{x}':y='{y}':enable='between(t,{start:.3f},{end:.3f})':eof_action=repeat{proximo}")
        return n_in
    _entrada(ov["resolved_path"], f"[pp{idx}]")
    janelas = [(max(start, float(a)), min(end, float(b))) for a, b in ov.get("boca_janelas") or [] if float(b) > float(a)]
    boca = ov.get("boca_path") if ov.get("boca_path") and os.path.isfile(str(ov.get("boca_path"))) else None
    enable = f"enable='between(t,{start:.3f},{end:.3f})':eof_action={'repeat' if parada else 'pass'}"
    if boca and janelas:
        meio = f"[pm{idx}]"
        partes.append(f"{atual}[pp{idx}]overlay=x='{x}':y='{y}':{enable}{meio}")
        _entrada(boca, f"[pb{idx}]")
        falando = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in janelas[:200])
        # a boca abre e fecha ~4x por segundo só enquanto tem palavra
        partes.append(f"{meio}[pb{idx}]overlay=x='{x}':y='{y}':enable='between(t,{start:.3f},{end:.3f})*gt({falando},0)*lt(mod(t-{start:.3f},0.24),0.12)'"
                      f":eof_action={'repeat' if parada else 'pass'}{proximo}")
    else:
        partes.append(f"{atual}[pp{idx}]overlay=x='{x}':y='{y}':{enable}{proximo}")
    return n_in


_ZOOM_DIRECTIONS_VALIDAS = {"in", "out", "pan_left", "pan_right", "pan_up", "pan_down", "static",
                            # efeitos de câmera do DarkPlanner (dp_visual.EFEITO_PARA_ZOOM)
                            "rapido", "zoom_pan_left", "zoom_pan_right", "zoom_pan_up", "giro", "respiro"}


# ------------------------------------------------------------------ 🪧 cartão sobre fundo (v84_85)
FUNDOS_CARTAO = ("cor_gradiente", "luz", "nevoa", "grade", "ondas", "grade_ondulada", "grade_3d", "pontos", "linhas", "papel")


def proporcao_diferente(image_path: str, W: int, H: int) -> bool:
    """A imagem tem proporção BEM diferente do vídeo (a mesma regra das bordas pretas/mosaico)?"""
    try:
        from PIL import Image
        with Image.open(image_path) as im:
            iw, ih = im.size
    except Exception:  # noqa: BLE001
        return False
    if iw < 2 or ih < 2:
        return False
    r = (iw / ih) / (W / H)
    return not (0.88 <= r <= 1.14)


def preparar_fundo_cartao(conf: Optional[Dict[str, Any]], W: int, H: int, pasta: str,
                          baixar_video: Optional[Callable[[str], Optional[str]]] = None) -> Dict[str, Any]:
    """O fundo que roda atrás dos cartões. conf = {"modo": "gerado"|"video", "estilo", "cor", "video_path", "busca",
    "desfocar", "escurecer"}. Vídeo que não deu (sem arquivo / a busca falhou) → fundo gerado."""
    conf = conf if isinstance(conf, dict) else {}
    os.makedirs(pasta, exist_ok=True)
    if conf.get("modo") == "video":
        p = conf.get("video_path")
        if (not p or not os.path.isfile(p)) and conf.get("busca") and baixar_video:
            try:
                p = baixar_video(str(conf["busca"]))
            except Exception as exc:  # noqa: BLE001
                print(f"[montagem] fundo dos cartões: a busca '{conf.get('busca')}' falhou ({exc}) — uso o fundo gerado", flush=True)
                p = None
        if p and os.path.isfile(p):
            try:
                dur = _probe_duration(p)
            except Exception:  # noqa: BLE001
                dur = 0.0
            if dur and dur > 0.5:
                def _num(k, padrao, a, b):
                    try:
                        return max(a, min(b, float(conf.get(k, padrao))))
                    except (TypeError, ValueError):
                        return padrao
                return {"tipo": "video", "path": p, "dur": float(dur), "desfocar": _num("desfocar", 4.0, 0.0, 30.0),
                        "escurecer": _num("escurecer", 0.15, 0.0, 0.6)}
    estilo = conf.get("estilo") if conf.get("estilo") in FUNDOS_CARTAO else "cor_gradiente"
    cor = conf.get("cor") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(conf.get("cor") or "")) else "#3C5082"
    import cenas_dp
    return {"tipo": "gerado", "png": cenas_dp._fundo_desenhado(estilo, W * 2, H * 2, pasta, cor)}


def _cartao_png(image_path: str, W: int, H: int) -> str:
    """A imagem como um CARTÃO: cantos arredondados + sombra, no tamanho que cabe no vídeo (78% × 84%)."""
    from PIL import Image, ImageDraw, ImageFilter
    with Image.open(image_path) as im0:
        im = im0.convert("RGB")
    iw, ih = im.size
    esc = min(W * 0.78 / iw, H * 0.84 / ih)
    cw, ch = max(4, int(iw * esc)), max(4, int(ih * esc))
    card = im.resize((cw, ch), Image.LANCZOS)
    raio = max(6, int(min(cw, ch) * 0.035))
    pad = max(8, int(H * 0.045))
    tela = Image.new("RGBA", (cw + 2 * pad, ch + 2 * pad), (0, 0, 0, 0))
    sombra = Image.new("L", tela.size, 0)
    ImageDraw.Draw(sombra).rounded_rectangle((pad, pad + pad // 3, pad + cw, pad + ch + pad // 3), raio, fill=150)
    sombra = sombra.filter(ImageFilter.GaussianBlur(pad / 2.2))
    tela.paste((0, 0, 0, 255), (0, 0), sombra)
    mascara = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mascara).rounded_rectangle((0, 0, cw - 1, ch - 1), raio, fill=255)
    tela.paste(card, (pad, pad), mascara)
    destino = os.path.join(tempfile.gettempdir(), f"_cartao_{uuid.uuid4().hex[:10]}.png")
    tela.save(destino)
    return destino


def _render_imagem_cartao(image_path: str, duration: float, output_path: str, W: int, H: int, fundo: Dict[str, Any],
                          t0: float = 0.0, on_screen_text: Optional[str] = None,
                          on_screen_text_style: Optional[Dict[str, Any]] = None) -> str:
    """🪧 A imagem como cartão (cantos arredondados + sombra) por cima de um fundo em movimento — fundo gerado
    (que deriva devagar) ou um clipe de vídeo em loop. O movimento do fundo segue o tempo do VÍDEO (`t0` = início
    do trecho): cartões seguidos parecem passar sobre o MESMO fundo, sem pulo. O cartão sobe de leve e aparece
    (0,45 s) e fica flutuando."""
    image_path = garantir_imagem_compativel(image_path)
    fps = TARGET_FPS
    frames = max(1, round(duration * fps))
    card = _cartao_png(image_path, W, H)
    try:
        if fundo.get("tipo") == "video":
            ss = float(t0) % max(0.5, float(fundo["dur"]))
            entradas = ["-stream_loop", "-1", "-ss", f"{ss:.3f}", "-i", fundo["path"]]
            bg = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={fps}"
                  + (f",gblur=sigma={fundo['desfocar']:.1f}" if fundo.get("desfocar") else "")
                  + (f",eq=brightness=-{fundo['escurecer']:.2f}" if fundo.get("escurecer") else "") + ",format=yuv420p[bg]")
        else:
            Tz = f"({float(t0):.3f}+on/{fps})"
            entradas = ["-loop", "1", "-i", fundo["png"]]
            bg = (f"[0:v]zoompan=z='1.10+0.04*sin({Tz}/5)':x='(iw-iw/zoom)*(0.5+0.45*sin({Tz}/9))':"
                  f"y='(ih-ih/zoom)*(0.5+0.45*cos({Tz}/11))':d={frames}:s={W}x{H}:fps={fps},setsar=1,format=yuv420p[bg]")
        entradas += ["-loop", "1", "-i", card]
        T = f"(t+{float(t0):.3f})"
        e = "min(1,t/0.45)"
        x = f"(W-w)/2+{W * 0.006:.1f}*sin(2*PI*{T}/8)"
        y = f"(H-h)/2+{H * 0.06:.1f}*pow(1-{e},3)+{H * 0.012:.1f}*sin(2*PI*{T}/6)"
        grafo = [bg, "[1:v]format=rgba,fade=t=in:st=0:d=0.35:alpha=1[cd]", f"[bg][cd]overlay=x='{x}':y='{y}':eval=frame,setsar=1[v]"]
        saida = "[v]"
        if on_screen_text:
            grafo.append("[v]" + _build_drawtext_filter(on_screen_text, H, on_screen_text_style, duration=duration) + "[vt]")
            saida = "[vt]"
        _run_ffmpeg(entradas + ["-filter_complex", ";".join(grafo), "-map", saida, "-t", f"{duration:.3f}", "-r", str(fps),
                                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an", output_path])
    finally:
        try:
            os.remove(card)
        except OSError:
            pass
    return output_path


def _compor_imagem_nas_bordas(image_path: str, W: int, H: int, aspect_fill: Optional[str]):
    """Imagem com proporção BEM diferente do vídeo + bordas "black"/"mosaic"/"smart": monta (2× o tamanho final,
    pro zoom não pixelar) a imagem INTEIRA encaixada no centro, com fundo preto (black) ou um mosaico desfocado
    dela mesma (mosaic/smart — igual ao dos vídeos). Devolve (caminho_png, mapa_do_foco) ou None (= preencher
    cortando, como sempre: bordas "zoom" ou proporção parecida)."""
    if aspect_fill not in ("black", "mosaic", "smart"):
        return None
    try:
        from PIL import Image, ImageEnhance, ImageFilter
        with Image.open(image_path) as im0:
            im = im0.convert("RGB")
    except Exception:  # noqa: BLE001
        return None
    iw, ih = im.size
    if iw < 2 or ih < 2:
        return None
    razao = (iw / ih) / (W / H)
    if 0.88 <= razao <= 1.14:  # quase a mesma proporção: preencher cortando perde pouco
        return None
    CW, CH = W * 2, H * 2
    esc = min(CW / iw, CH / ih)
    fw, fh = max(2, int(iw * esc)), max(2, int(ih * esc))
    frente = im.resize((fw, fh), Image.LANCZOS)
    if aspect_fill == "black":
        fundo = Image.new("RGB", (CW, CH), (0, 0, 0))
    else:
        tw, th = CW // 2, CH // 2
        e2 = max(tw / iw, th / ih)
        lad = im.resize((max(tw, int(iw * e2) + 1), max(th, int(ih * e2) + 1)), Image.LANCZOS)
        lx, ly = (lad.width - tw) // 2, (lad.height - th) // 2
        lad = lad.crop((lx, ly, lx + tw, ly + th))
        fundo = Image.new("RGB", (CW, CH))
        for x, y in ((0, 0), (tw, 0), (0, th), (tw, th)):
            fundo.paste(lad, (x, y))
        fundo = ImageEnhance.Brightness(fundo.filter(ImageFilter.GaussianBlur(radius=max(12, CH // 40)))).enhance(0.7)
    ox, oy = (CW - fw) // 2, (CH - fh) // 2
    fundo.paste(frente, (ox, oy))
    destino = os.path.join(tempfile.gettempdir(), f"_img_bordas_{uuid.uuid4().hex[:10]}.png")
    fundo.save(destino)

    def foco(fx: float, fy: float):
        return (max(0.0, min(1.0, (ox + fx * fw) / CW)), max(0.0, min(1.0, (oy + fy * fh) / CH)))
    return destino, foco


def _render_image_with_ken_burns(
    image_path: str,
    duration: float,
    output_path: str,
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
    zoom_direction: str = "in",
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    on_screen_text: Optional[str] = None,
    on_screen_text_style: Optional[Dict[str, Any]] = None,
    fade_in: bool = False,
    fade_out: bool = False,
    fade_duration: float = 0.5,
    blur_sigma: float = 0.0,
    aspect_fill: Optional[str] = None,
) -> str:
    """Transforma uma imagem parada num clipe de `duration` segundos com
    uma animação de câmera (ou nenhuma), no mesmo formato dos clipes de
    vídeo normais (pronto pra concatenar com eles).

    zoom_direction — a animação de câmera:
        "in": zoom lento aproximando (começa afastado, termina próximo
            — padrão clássico "Ken Burns").
        "out": zoom lento afastando (começa próximo, termina afastado).
        "pan_left"/"pan_right"/"pan_up"/"pan_down": câmera desliza na
            direção indicada, com um zoom leve e CONSTANTE (não anima o
            zoom em si — só a posição) só pra sobrar imagem suficiente
            pra deslizar sem mostrar borda.
        "static": nenhuma animação — quadro parado o clipe inteiro
            (útil combinado com `blur_sigma`, ou quando a animação
            constante estaria distraindo demais).
    focus_x/focus_y: de 0.0 a 1.0 — em "in"/"out", o ponto que o zoom
        foca; em "pan_*", a posição fixa no eixo QUE NÃO está sendo
        percorrido (ex: em pan_left/pan_right, controla a altura Y do
        enquadramento).
    fade_in/fade_out: se True, a IMAGEM (não o texto) surge/desaparece
        suavemente a partir de preto, em vez de aparecer/cortar de
        repente — dura `fade_duration` segundos (padrão 0.5s), tirado
        do começo/fim do próprio tempo do clipe (curto o bastante não
        chega a se sobrepor: os dois juntos são limitados a no máximo a
        duração inteira do clipe).
    blur_sigma: 0 (padrão) = sem desfoque; qualquer valor > 0 aplica um
        desfoque gaussiano nessa intensidade (valores típicos úteis:
        5-15 pra um desfoque leve, 20+ pra bem forte/irreconhecível).
    """
    if not (0.0 <= focus_x <= 1.0) or not (0.0 <= focus_y <= 1.0):
        raise VideoAssemblyError(f"focus_x/focus_y precisam estar entre 0.0 e 1.0 (recebi {focus_x}, {focus_y}).")
    image_path = garantir_imagem_compativel(image_path)  # todo ffmpeg lê JPG/PNG; AVIF/WebP nem sempre
    if zoom_direction not in _ZOOM_DIRECTIONS_VALIDAS:
        raise VideoAssemblyError(f"zoom_direction precisa ser um de {sorted(_ZOOM_DIRECTIONS_VALIDAS)} (recebi {zoom_direction!r}).")
    try:
        blur_sigma = float(blur_sigma or 0)
    except (TypeError, ValueError):
        blur_sigma = 0.0
    if blur_sigma < 0:
        raise VideoAssemblyError(f"blur_sigma não pode ser negativo (recebi {blur_sigma}).")

    fps = TARGET_FPS
    total_frames = max(1, round(duration * fps))
    # 🖼 v84_84: imagem de proporção bem diferente do vídeo (capa de livro em pé num vídeo 16:9…) respeita as
    # BORDAS escolhidas (pretas / mosaico): a imagem inteira aparece encaixada, e a câmera mexe pouco. Antes ela
    # sempre era cortada pra preencher a tela (+ zoom de até 40%) — sobrava só um pedaço gigante da imagem.
    k_mov = 1.0
    composta = _compor_imagem_nas_bordas(image_path, target_width, target_height, aspect_fill)
    if composta:
        image_path, (focus_x, focus_y) = composta[0], composta[1](focus_x, focus_y)
        k_mov = 0.35
    max_zoom = 1.0 + 0.4 * k_mov
    zoom_step = (max_zoom - 1.0) / total_frames
    pan_zoom = 1.0 + 0.15 * k_mov  # zoom fixo pros modos "pan_*" -- só o suficiente pra sobrar imagem nas bordas pra deslizar

    if zoom_direction == "in":
        zoom_expr = f"min(zoom+{zoom_step:.6f},{max_zoom})"
        x_expr = f"(iw-iw/zoom)*{focus_x:.3f}"
        y_expr = f"(ih-ih/zoom)*{focus_y:.3f}"
    elif zoom_direction == "out":
        zoom_expr = f"if(eq(on,1),{max_zoom},max(1.0,zoom-{zoom_step:.6f}))"
        x_expr = f"(iw-iw/zoom)*{focus_x:.3f}"
        y_expr = f"(ih-ih/zoom)*{focus_y:.3f}"
    elif zoom_direction == "static":
        zoom_expr = "1.0"
        x_expr = f"(iw-iw/zoom)*{focus_x:.3f}"
        y_expr = f"(ih-ih/zoom)*{focus_y:.3f}"
    elif zoom_direction in ("rapido", "giro", "respiro", "zoom_pan_left", "zoom_pan_right", "zoom_pan_up"):
        prog = f"((on-1)/{max(1, total_frames - 1)})"
        k = k_mov
        if zoom_direction == "rapido":  # zoom forte no começo e segura
            zoom_expr = f"1+{0.5 * k:.3f}*(1-pow(1-min(1,{prog}*2.5),3))"
        elif zoom_direction == "respiro":  # aproxima e volta, suave
            zoom_expr = f"{1 + 0.06 * k:.3f}+{0.1 * k:.3f}*sin(PI*{prog})"
        elif zoom_direction == "giro":
            zoom_expr = f"{1 + 0.2 * k:.3f}+{0.15 * k:.3f}*{prog}"
        else:
            zoom_expr = f"{1 + 0.12 * k:.3f}+{0.2 * k:.3f}*{prog}"
        x_expr = f"(iw-iw/zoom)*{focus_x:.3f}"
        y_expr = f"(ih-ih/zoom)*{focus_y:.3f}"
        if zoom_direction == "zoom_pan_left":
            x_expr = f"(iw-iw/zoom)*(1-{prog})"
        elif zoom_direction == "zoom_pan_right":
            x_expr = f"(iw-iw/zoom)*{prog}"
        elif zoom_direction == "zoom_pan_up":
            y_expr = f"(ih-ih/zoom)*(1-{prog})"
    else:
        # pan_left/pan_right/pan_up/pan_down -- zoom CONSTANTE (não
        # anima), só a posição (x ou y) se move de uma ponta à outra
        # ao longo dos frames, na direção pedida.
        zoom_expr = f"{pan_zoom:.3f}"
        progresso = f"(on-1)/{max(1, total_frames - 1)}"
        if zoom_direction == "pan_left":
            x_expr = f"(iw-iw/zoom)*(1-{progresso})"
            y_expr = f"(ih-ih/zoom)*{focus_y:.3f}"
        elif zoom_direction == "pan_right":
            x_expr = f"(iw-iw/zoom)*{progresso}"
            y_expr = f"(ih-ih/zoom)*{focus_y:.3f}"
        elif zoom_direction == "pan_up":
            x_expr = f"(iw-iw/zoom)*{focus_x:.3f}"
            y_expr = f"(ih-ih/zoom)*(1-{progresso})"
        else:  # pan_down
            x_expr = f"(iw-iw/zoom)*{focus_x:.3f}"
            y_expr = f"(ih-ih/zoom)*{progresso}"

    # super-amostra a imagem antes do zoompan (senão o zoom aplicado
    # sobre a resolução final costuma ficar visivelmente "quadriculado"
    # ao ampliar) — depois o próprio zoompan já entrega no tamanho certo.
    filters = [
        f"scale={target_width * 2}:{target_height * 2}:force_original_aspect_ratio=increase,"
        f"crop={target_width * 2}:{target_height * 2}",
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d={total_frames}:s={target_width}x{target_height}:fps={fps}",
    ]
    if zoom_direction == "static":
        # ⚡ v84_236: parado não precisa do zoompan (nem da super-amostra em 2x) — o fundo do 🎭 react tem o vídeo
        # inteiro (5–10 min) e o zoompan em 4K levava mais que o limite do passo
        filters = [f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
                   f"crop={target_width}:{target_height},setsar=1,fps={fps}"]

    if zoom_direction == "giro":  # leve rotação (o zoom de 1.2+ esconde os cantos)
        filters.append(f"rotate=a='0.05*sin(2*PI*t/{max(1.0, duration):.3f})':c=black")

    if blur_sigma > 0:
        filters.append(f"gblur=sigma={blur_sigma:.2f}")

    if fade_in or fade_out:
        try:
            fd = max(0.05, float(fade_duration))
        except (TypeError, ValueError):
            fd = 0.5
        # evita as duas metades se sobreporem num clipe muito curto.
        fd = min(fd, max(0.05, duration / 2)) if (fade_in and fade_out) else min(fd, max(0.05, duration))
        if fade_in:
            filters.append(f"fade=t=in:st=0:d={fd:.3f}")
        if fade_out:
            fade_out_start = max(0.0, duration - fd)
            filters.append(f"fade=t=out:st={fade_out_start:.3f}:d={fd:.3f}")

    if on_screen_text:
        filters.append(_build_drawtext_filter(on_screen_text, target_height, on_screen_text_style, duration=duration))

    try:
        _run_ffmpeg([
            "-loop", "1", "-i", image_path,
            "-vf", ",".join(filters),
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            output_path,
        ], timeout=int(max(300, duration * 3)))  # 🎭 v84_236: uma imagem só cobrindo um vídeo longo (o fundo do react)
    finally:
        if composta:
            try:
                os.remove(composta[0])
            except OSError:
                pass
    return output_path


def _extract_video_preview_url(provider: str, data: Dict[str, Any]) -> str:
    if provider == "pexels":
        files = data.get("video_files") or []
        return (files[0].get("link") or "") if files else ""
    if provider == "mixkit":
        return data.get("preview_url") or ""
    if provider in ("magnific", "vistacreate"):
        return data.get("download_url") or ""
    if provider in BIBLIOTECAS_LOCAIS:
        return data.get("video_preview_url") or ""
    return ""  # pixabay e qualquer outro sem preview tocável direto da busca


def search_candidates(
    provider: str,
    query: str,
    media_type: str = "video",
    max_results: int = 6,
    site_cfg: Optional[Dict[str, Any]] = None,
    client_factory: Optional["ClientFactory"] = None,
    keyword_weight: Optional[float] = None,
    semantic_weight: Optional[float] = None,
    obra: Optional[str] = None,
    personagem: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Busca "de verdade" (sem baixar nada) e devolve uma lista de
    candidatos com thumbnail — usado pelo editor de segmentos pra deixar
    a pessoa VER algumas opções reais antes de escolher qual usar num
    segmento, em vez de trocar o termo às cegas e só descobrir se deu
    certo depois de montar o vídeo inteiro.

    keyword_weight/semantic_weight: repassados direto pro
    "animepexels" (único provedor que entende esses parâmetros);
    ignorados pelos outros 5.

    Cada item devolvido: {"id": str, "thumbnail": str (url), "label": str,
    "video_preview_url": str (pode ser vazio)}. "video_preview_url" é uma
    URL de vídeo tocável direto no navegador (sem baixar) — alimenta o
    "Monitor de Origem" do editor; fica vazio quando o provedor não
    expõe isso na busca (hoje, só o Pixabay).
    """
    cfg = site_cfg or load_site_config()
    owns_factory = client_factory is None
    factory = client_factory or ClientFactory(cfg)
    weight_kwargs: Dict[str, Any] = {}
    if keyword_weight is not None:
        weight_kwargs["keyword_weight"] = keyword_weight
    if semantic_weight is not None:
        weight_kwargs["semantic_weight"] = semantic_weight
    if provider in BIBLIOTECAS_LOCAIS:  # obra / personagem-ator (acervos locais)
        if obra:
            weight_kwargs["obra"] = obra
        if personagem:
            weight_kwargs["personagem"] = personagem

    # 🖼️ (v84_92) a prévia também pede o FORMATO do vídeo aos bancos que têm esse filtro — antes só a montagem pedia,
    # e a prévia escolhia (e fixava) um vídeo em pé num vídeo deitado
    orient_kwargs = _orientation_filter_kwargs(provider, cfg.get("orientation")) if media_type != "image" else {}
    foto_orient = {"16:9": "landscape", "9:16": "portrait", "1:1": "square"}.get(str(cfg.get("orientation") or ""))

    try:
        if media_type == "image":
            if provider not in _PHOTO_SEARCH_PROVIDERS:
                raise VideoAssemblyError(f"'{provider}' não suporta busca de fotos.")
            client = factory.get_photo_client(provider)
            if provider == "pexels" and foto_orient:
                try:
                    results = client.search_photos_all(query=query, max_pages=1, orientation=foto_orient)[:max_results]
                except TypeError:  # cliente sem o filtro
                    results = client.search_photos_all(query=query, max_pages=1)[:max_results]
            else:
                results = client.search_photos_all(query=query, max_pages=1)[:max_results]
            return [
                {
                    "id": r.id, "thumbnail": r.sizes.get("tiny") or r.sizes.get("small") or "",
                    "label": r.description or r.author or r.id, "url": r.url or "",
                    "video_preview_url": "",
                    "image_url": r.sizes.get("original") or r.sizes.get("large") or r.sizes.get("small") or "",
                }
                for r in results
            ]

        client = factory.get_client(provider)

        def _buscar(extra):
            if provider == "mixkit":
                return client.search_all(category=query, max_pages=1, **weight_kwargs, **extra)[:max_results]
            return client.search_all(query=query, max_pages=1, **weight_kwargs, **extra)[:max_results]
        try:
            results = _buscar(orient_kwargs)
        except TypeError:  # cliente sem o filtro de orientação
            results = _buscar({})
        candidates = []
        for r in results:
            data = r.to_dict() if hasattr(r, "to_dict") else {}
            thumb = data.get("thumbnail") or ""
            label = data.get("title") or data.get("name") or data.get("author") or data.get("id", "")
            _dur = data.get("duration") or data.get("duration_seconds") or data.get("duracao") or getattr(r, "duration", None) or getattr(r, "duration_seconds", None)
            try:
                _dur = float(_dur) if _dur else None
            except (TypeError, ValueError):
                _dur = None
            candidates.append({
                "id": str(data.get("id", "")), "thumbnail": thumb, "label": str(label)[:60],
                "url": data.get("url") or "",
                "video_preview_url": _extract_video_preview_url(provider, data),
                "duracao": _dur,
            })
        return candidates
    except VideoAssemblyError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VideoAssemblyError(f"Busca falhou pra '{query}' em {provider}: {exc}") from exc
    finally:
        # se a fábrica foi criada aqui dentro (chamada sem `client_factory`
        # explícito, como acontece na rota do Flask), fecha a sessão/navegador
        # antes de devolver — sem isso, cada clique em "Buscar" no editor
        # abriria um Chrome novo que nunca seria fechado.
        if owns_factory:
            factory.close_all()


def _fallback_queries_for(segment: VideoSegment) -> List[str]:
    """Gera termos de busca alternativos, do mais específico pro mais
    genérico, pra tentar quando o termo original da IA não trouxer nada
    (o motivo mais comum é o termo ser específico ou pouco comum demais
    no banco de imagens escolhido).
    """
    if segment.provider in GERADORES_IA:
        # gerar imagem com IA custa minutos e créditos: "tentar de novo com
        # menos palavras" seria gerar OUTRA imagem, não achar a mesma.
        return []
    alternativas = [a for a in (getattr(segment, "alternativas", None) or []) if a and a.strip()]
    reserva = (getattr(segment, "busca_reserva", None) or "").strip()
    if segment.provider == "mixkit":
        # categorias: as alternativas da IA (também categorias) e, por fim,
        # uma genérica quase sempre disponível
        return _sem_repetir(alternativas + ["background"], segment.query)

    fallbacks = list(alternativas)  # da IA: mais simples, mas ainda sobre a cena
    nucleo = _nucleo_da_busca(segment.query)
    if nucleo:
        fallbacks.append(nucleo)  # as 3 primeiras palavras que importam
    words = segment.query.split()
    if len(words) > 1:
        fallbacks.append(words[-1])  # so a ultima palavra, mais generica
    # último recurso: a busca com a cara do vídeo que a IA sugeriu (ex.: "dark
    # foggy forest" num vídeo de terror) — "nature background" só sem ela
    fallbacks.append(reserva or "nature background")
    return _sem_repetir(fallbacks, segment.query)


_PALAVRAS_DE_PLANO = {
    "close", "up", "closeup", "close-up", "shot", "wide", "medium", "extreme", "macro", "view", "angle",
    "the", "a", "an", "of", "on", "in", "at", "with", "while", "and", "over", "under", "by", "into", "from",
}


def _nucleo_da_busca(query: str) -> Optional[str]:
    """As 3 primeiras palavras que dizem O QUE aparece (sem "close up", "shot",
    artigos/preposições) — "old man reading letter by candlelight" vira "old
    man reading". Só quando a busca tem mais de 3 palavras úteis."""
    uteis = [w for w in (query or "").split() if w.lower().strip(",.") not in _PALAVRAS_DE_PLANO]
    return " ".join(uteis[:3]) if len(uteis) > 3 else None


def _sem_repetir(termos: List[str], original: str) -> List[str]:
    vistos = {" ".join((original or "").lower().split())}
    saida = []
    for t in termos:
        n = " ".join((t or "").lower().split())
        if n and n not in vistos:
            vistos.add(n)
            saida.append(t)
    return saida


_PROVIDER_MODULES = {
    "pexels": ("pexels.pexels_client", "PexelsClient"),
    "pixabay": ("pixabay.pixabay_client", "PixabayClient"),
    "magnific": ("magnific.magnific_client", "MagnificClient"),
    "mixkit": ("mixkit.mixkit_client", "MixkitClient"),
    "vistacreate": ("vistacreate.vistacreate_client", "VistaCreateClient"),
    "animepexels": ("animepexels.animepexels_client", "AnimePexelsClient"),
    "moviepexels": ("animepexels.animepexels_client", "MoviePexelsClient"),
    "animepexels_online": ("animepexels.animepexels_client", "AnimePexelsOnlineClient"),
    "moviepexels_online": ("animepexels.animepexels_client", "MoviePexelsOnlineClient"),
}


_API_ENABLED_PROVIDERS = {
    "pexels": ("pexels_api_client", "PexelsAPIClient"),
    "pixabay": ("pixabay_api_client", "PixabayAPIClient"),
}

# Provedores que suportam busca de FOTO (`media_type: "image"`), e o
# módulo/classe do cliente correspondente — usado por `get_photo_client()`.
# Diferente de `_API_ENABLED_PROVIDERS`/`_PROVIDER_MODULES` (vídeo): aqui
# não existe fallback pra navegador, já que nenhum dos dois faz scraping
# de foto (a API oficial do Pexels e a API pública da Wikipedia/Wikimedia
# são REST puro, sem Chrome envolvido).
_PHOTO_PROVIDER_MODULES = {
    "pexels": ("pexels_api_client", "PexelsAPIClient"),
    "wikipedia": ("wikipedia_api_client", "WikipediaAPIClient"),
    # buscadores de imagem por navegador (Playwright) -- adaptados dos
    # scripts que o usuário enviou (bing_image_api.py/brave_image_api.py,
    # com a parte de servidor HTTP removida). Cada busca abre e fecha o
    # próprio Chromium; não precisam de chave de API.
    "bing": ("bing_api_client", "BingAPIClient"),
    "brave": ("brave_api_client", "BraveAPIClient"),
    "yandex": ("yandex_api_client", "YandexAPIClient"),
    "startpage": ("startpage_api_client", "StartpageAPIClient"),
    # 🖼️ Google Imagens pelo Modo IA do Google (app ia_google/, API POST /api/imagens)
    "google": ("google_api_client", "GoogleAPIClient"),
    # imagens GERADAS por IA no Google Flow (automação de navegador; ver
    # toolkit/googleflow/googleflow_client.py) — recebe a config do site.
    "flow": ("googleflow.googleflow_client", "GoogleFlowClient"),
    # 🟣 imagens geradas por IA no Runpod (API paga; runpod_gerador.py)
    "runpod": ("runpod_gerador", "RunpodClient"),
}

_API_FALLBACK_CONFIG_KEY = {
    "pexels": "pexels_api_fallback_to_browser",
    "pixabay": "pixabay_api_fallback_to_browser",
}


def photo_api_configuration_error(site_cfg: Optional[Dict[str, Any]] = None, provider: str = "pexels") -> Optional[str]:
    """Confere se a API de fotos (oficial do Pexels — único provedor
    com busca de fotos de verdade no toolkit) está configurada, SEM
    precisar rodar nenhuma busca de verdade — usado pra validação
    ANTECIPADA, antes de sequer começar a montagem.

    Bug real relatado: um trecho com `media_type="image"` sem
    `PEXELS_API_KEYS` configurado só descobria isso DEPOIS de rodar a
    montagem inteira (minutos, em vídeos longos), obrigando a pessoa a
    esperar tudo pra só então ver o erro. Chamando isso ANTES de
    iniciar a montagem, o aviso aparece na hora.

    Devolve None se está tudo certo, ou uma mensagem de erro clara se
    não estiver (pra incluir direto na mensagem mostrada à pessoa).

    Função separada de propósito (não inline em `app.py`) pra poder ser
    facilmente substituída em teste, quando o teste já injeta seu
    próprio cliente de foto por outro caminho (o legado `get_client_fn`,
    que essa checagem antecipada não tem como saber que existe).

    provider: qual provedor de foto checar — "pexels" (padrão, precisa de
        PEXELS_API_KEYS) ou "wikipedia" (não precisa de chave nenhuma,
        então isso praticamente nunca devolve erro pra ele).
    """
    try:
        ClientFactory(site_cfg or load_site_config()).get_photo_client(provider)
        return None
    except Exception as exc:  # noqa: BLE001
        return str(exc)


class ClientFactory:
    """Cria e reaproveita clientes de acordo com a configuração do site
    (`site_config.py`): visibilidade do navegador, sessão compartilhada
    entre provedores ou uma por provedor, modo de fechar a cada download
    ou reaproveitar, e o fallback automático das APIs oficiais (Pexels e
    Pixabay) pro scraping por navegador quando a API falha.
    """

    def __init__(self, site_cfg: Dict[str, Any]):
        self.cfg = site_cfg
        self._clients: Dict[str, Any] = {}
        self._shared_session = None
        self._use_browser_for: set = set()  # provedores API que já falharam e viraram navegador

    def is_api_client(self, client, provider: str) -> bool:
        entry = _API_ENABLED_PROVIDERS.get(provider)
        if not entry:
            return False
        module_name, class_name = entry
        try:
            module = importlib.import_module(module_name)
            api_cls = getattr(module, class_name)
            return isinstance(client, api_cls)
        except (ImportError, AttributeError, TypeError):
            # TypeError pode acontecer se algo (ex: um teste, ou uma
            # extensão futura) substituir a classe por algo que não é um
            # tipo de verdade — nesse caso, mais seguro assumir "não é a
            # API" e seguir o fluxo normal do que derrubar a montagem
            # inteira por causa dessa checagem auxiliar.
            return False

    def force_browser_fallback(self, provider: str) -> None:
        """Chamado quando a API oficial de `provider` falhou de verdade —
        a partir daqui, todo pedido de cliente pra esse provedor vem via
        navegador (é 'pegajoso': não tenta a API de novo nos segmentos
        seguintes, pra não ficar re-testando uma chave que já sabemos
        que não funciona).
        """
        old = self._clients.pop(provider, None)
        if old is not None:
            try:
                old.session.close()
            except Exception:  # noqa: BLE001
                pass
        self._use_browser_for.add(provider)

    def get_client(self, provider: str):
        reuse = self.cfg.get("browser_mode", "reuse_session") != "close_each_download"
        if reuse and provider in self._clients:
            return self._clients[provider]

        client = self._create_client(provider)
        if reuse:
            self._clients[provider] = client
        return client

    def get_photo_client(self, provider: str = "pexels"):
        """Cliente pra busca de FOTOS (não vídeos). Dois provedores
        suportam isso no toolkit atual (ver `_PHOTO_PROVIDER_MODULES`):
        a API oficial do Pexels (precisa de `PEXELS_API_KEYS`) e a
        Wikipedia/Wikimedia Commons (sem chave nenhuma, mas só serve pra
        coisas reais/documentadas — não é um banco de foto genérico).
        Levanta exceção clara se `provider` não tiver cliente de fotos
        (ex: pediram foto de um banco que só tem vídeo), ou — no caso do
        Pexels — se `PEXELS_API_KEYS` não estiver configurado.
        """
        cache_key = f"{provider}_photos"
        if cache_key not in self._clients:
            entry = _PHOTO_PROVIDER_MODULES.get(provider)
            if not entry:
                raise VideoAssemblyError(
                    f"'{provider}' não tem busca de fotos (media_type='image') — só "
                    f"{sorted(_PHOTO_PROVIDER_MODULES)} suportam isso."
                )
            module_name, class_name = entry
            module = importlib.import_module(module_name)
            client_cls = getattr(module, class_name)
            # o Flow precisa da config (navegador oculto/visível, proporção...)
            # Flow precisa da config inteira (navegador oculto/visível,
            # proporção...). Os 4 buscadores por navegador (bing/brave/
            # yandex/startpage) só precisam saber se ocultam ou não --
            # mesma config "Ocultar o navegador" que já vale pra tudo
            # mais (era um gap real: eles ignoravam essa config e
            # ficavam sempre ocultos, mesmo com a pessoa desmarcando a
            # opção pra depurar).
            if provider in GERADORES_IA:
                self._clients[cache_key] = client_cls(site_cfg=self.cfg)
            elif provider in _BROWSER_IMAGE_SEARCH_PROVIDERS:
                _headless = not self.cfg.get("browser_visible", False)
                try:
                    self._clients[cache_key] = client_cls(headless=_headless, proporcao=proporcao_dos_buscadores(self.cfg))
                except TypeError:  # cliente sem filtro de proporção (antigo/de teste)
                    self._clients[cache_key] = client_cls(headless=_headless)
            else:
                self._clients[cache_key] = client_cls()
        return self._clients[cache_key]

    def _create_client(self, provider: str):
        if provider == "runpod":  # 🟣 vídeo gerado no Runpod (Pruna Video)
            return importlib.import_module("runpod_gerador").RunpodClient(site_cfg=self.cfg)
        if provider == "flow":
            # vídeo GERADO com IA (Veo) no Google Flow — mesmo cliente das
            # imagens, no modo vídeo (`search_all`/`download_video`). Ele só
            # entra quando o PRÓPRIO trecho pediu "flow": as cadeias de
            # fallback de vídeo tiram o "flow" (ver `_sem_flow_no_fallback`),
            # pra nunca disparar uma geração de minutos à toa.
            module = importlib.import_module("googleflow.googleflow_client")
            return module.GoogleFlowClient(site_cfg=self.cfg)
        if provider == "youtube":
            # YouTube não tem busca+download automático: a pessoa escolhe o
            # vídeo e a faixa de tempo no editor (painel "Vídeos do YouTube").
            # Sem escolha, o trecho cai pros bancos normais (prioridade).
            raise VideoAssemblyError(
                "'youtube' não é buscado automaticamente — escolha o vídeo e o trecho no painel "
                "\"Vídeos do YouTube\" do editor (sem isso, o trecho usa os outros bancos)."
            )
        if provider == "wikipedia":
            # "wikipedia" só existe pro caminho de FOTO (media_type=
            # "image", via get_photo_client) — não tem busca de vídeo, e
            # esse método só é chamado no caminho de vídeo. Erro claro em
            # vez de deixar cair no KeyError genérico de `_PROVIDER_MODULES`
            # lá embaixo.
            raise VideoAssemblyError(
                "'wikipedia' só busca FOTOS (media_type='image') — não tem busca de vídeo. "
                "Um segmento com provider='wikipedia' precisa também ter media_type='image'."
            )
        if provider in ("produto", "material"):
            # 🛒 mídia do projeto de venda: o trecho usa o arquivo do projeto (override); sem ele não tem o que buscar
            raise VideoAssemblyError("'produto' é uma mídia do projeto de venda — esse trecho perdeu o arquivo; "
                                     "escolha outra mídia na biblioteca do Estúdio.")
        if provider in BIBLIOTECAS_LOCAIS:
            # banco LOCAL (roda na própria máquina do usuário) — sempre
            # o mesmo cliente HTTP simples, nunca navegador, nunca
            # fallback API->browser (não existe essa distinção aqui).
            # Filmes/séries = o MESMO servidor, catálogo /movie.
            # As versões "_online" vão no servidor online, com a chave de API.
            import acervos
            return acervos.cliente(provider, self.cfg)

        if provider in _API_ENABLED_PROVIDERS and provider not in self._use_browser_for:
            module_name, class_name = _API_ENABLED_PROVIDERS[provider]
            try:
                module = importlib.import_module(module_name)
                api_cls = getattr(module, class_name)
                return api_cls()
            except Exception:  # noqa: BLE001
                # sem chave configurada (ou .env ausente) -> direto pro navegador,
                # sem nem contar como "falha" de uma API que nunca foi tentada.
                self._use_browser_for.add(provider)

        from browser_session import ChromeSession

        module_name, class_name = _PROVIDER_MODULES[provider]
        module = importlib.import_module(module_name)
        client_cls = getattr(module, class_name)
        headers = getattr(module, "DEFAULT_HEADERS", {})
        headless = not self.cfg.get("browser_visible", False)

        if self.cfg.get("browser_shared_across_providers", False):
            if self._shared_session is None:
                self._shared_session = ChromeSession(headless=headless, headers=headers)
            session = self._shared_session
        else:
            session = ChromeSession(headless=headless, headers=headers)

        return client_cls(session=session)

    def close_client(self, provider: str, client) -> None:
        """Fecha um cliente específico — usado no modo
        'close_each_download' logo depois de cada download, e também
        chamado internamente quando um cliente não está mais em cache.
        Não fecha a sessão compartilhada entre provedores enquanto ainda
        houver outros provedores pendentes de usá-la (só `close_all()`
        no final faz isso).
        """
        if self.cfg.get("browser_shared_across_providers", False) and client.session is self._shared_session:
            return  # sessão compartilhada: só fecha em close_all()
        try:
            client.session.close()
        except Exception:  # noqa: BLE001
            pass

    def close_all(self) -> None:
        seen_sessions = set()
        for client in self._clients.values():
            session = getattr(client, "session", None)
            if session is not None and id(session) in seen_sessions:
                continue
            if session is not None:
                seen_sessions.add(id(session))
            try:
                client.session.close()
            except Exception:  # noqa: BLE001
                pass
        if self._shared_session is not None and id(self._shared_session) not in seen_sessions:
            try:
                self._shared_session.close()
            except Exception:  # noqa: BLE001
                pass


_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif", ".heic", ".heif", ".tif", ".tiff", ".jfif", ".ico"}


def garantir_imagem_compativel(path: str) -> str:
    """Converte pra .jpg qualquer imagem que não seja JPEG/PNG de verdade (AVIF,
    WebP, HEIC...) e devolve o caminho que deve ser usado. Levanta
    VideoAssemblyError com mensagem clara se a imagem for ilegível."""
    from buscador_imagens_unificado import converter_para_jpg
    try:
        return converter_para_jpg(path)
    except ValueError as exc:
        raise VideoAssemblyError(f"Não consegui ler a imagem {os.path.basename(path)!r}: {exc}") from exc
_PROVIDERS_WITH_URL_RESOLUTION = {"pexels", "pixabay", "mixkit", "animepexels", "moviepexels", "animepexels_online", "moviepexels_online"}


def _infer_media_kind(path_or_url: str) -> str:
    ext = os.path.splitext(path_or_url.split("?")[0])[1].lower()
    return "image" if ext in _IMAGE_EXTENSIONS else "video"


def _download_generic_url(url: str, dest_dir: str) -> str:
    """Baixa um arquivo de uma URL qualquer (não é um dos 5 provedores —
    é um link direto pra um arquivo de vídeo/imagem, dado manualmente no
    editor de segmentos)."""
    import requests

    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(url.split("?")[0])[1] or ".bin"
    dest_path = os.path.join(dest_dir, f"override_download{ext}")
    try:
        resp = requests.get(url, stream=True, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise VideoAssemblyError(f"Falha ao baixar {url}: {exc}") from exc
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    return dest_path


def generate_waveform_image(audio_path: str, output_path: str, width: int = 1400, height: int = 100) -> str:
    """Gera uma imagem PNG da forma de onda do áudio inteiro — usada como
    fundo da faixa de narração na timeline visual do editor.
    """
    _run_ffmpeg([
        "-i", audio_path,
        "-filter_complex", f"showwavespic=s={width}x{height}:colors=0x2563eb",
        "-frames:v", "1",
        output_path,
    ])
    return output_path


def generate_thumbnail(media_path: str, output_path: str, at_seconds: float = 0.3, width: int = 320) -> str:
    """Gera uma miniatura (thumbnail) de um vídeo (frame extraído perto
    do início) ou de uma imagem (só redimensionada) — usada nos blocos
    da timeline visual do editor.
    """
    kind = _infer_media_kind(media_path)
    if kind == "image":
        _run_ffmpeg(["-i", media_path, "-vf", f"scale={width}:-2", output_path])
    else:
        duration = _probe_duration(media_path)
        safe_t = min(at_seconds, max(0.0, duration - 0.05))
        _run_ffmpeg(["-ss", f"{safe_t:.3f}", "-i", media_path, "-frames:v", "1", "-vf", f"scale={width}:-2", output_path])
    return output_path


def _seconds_to_ass_timestamp(seconds: float) -> str:
    """Formato de timestamp exigido pelo .ass: H:MM:SS.CC (centésimos)."""
    total_centiseconds = round(max(0.0, seconds) * 100)
    hours, rem = divmod(total_centiseconds, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _escape_ass_text(text: str) -> str:
    """Escapa uma palavra pro campo de texto de uma linha `Dialogue` do
    .ass — chaves têm significado especial (abrem tags de estilo), e
    barra invertida também.
    """
    return text.replace("\\", "").replace("{", "").replace("}", "").strip()


def _hex_to_ass_color(hex_color: str, alpha: int = 0) -> str:
    """Converte uma cor "#RRGGBB" (formato web comum) pro formato de
    cor do ASS/libass, que é "&HAABBGGRR" — alpha e canais invertidos
    (azul-verde-vermelho) em relação ao formato web. `alpha` vai de 0
    (opaco) a 255 (totalmente transparente) — 0 é o padrão de sempre.
    """
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        raise VideoAssemblyError(f"Cor inválida: {hex_color!r} — esperava um hex de 6 dígitos, tipo 'FFFFFF'.")
    r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
    return f"&H{alpha:02X}{b}{g}{r}"


_CAPTION_ALIGNMENTS = {"bottom": 2, "middle": 5, "top": 8}


def generate_word_captions_ass(
    words: List[Dict[str, Any]],
    output_path: str,
    video_width: int = TARGET_WIDTH,
    video_height: int = TARGET_HEIGHT,
    fontsize: Optional[int] = None,
    style: Optional[Dict[str, Any]] = None,
) -> str:
    """Gera um arquivo de legenda .ass no estilo "uma palavra por vez":
    cada palavra falada vira uma linha de legenda própria, visível só
    durante a janela de tempo em que foi dita — é o estilo comum em
    vídeos curtos (Shorts/Reels/TikTok), diferente do karaokê clássico
    de linha inteira com destaque progressivo.

    words: lista de {"word": str, "start": float, "end": float} — o
        mesmo formato que `whisper_transcribe.transcribe_audio(...,
        word_timestamps=True)` devolve dentro de cada segmento (pode
        vir de vários segmentos concatenados numa lista só).

    style: personalização visual opcional (todos os campos têm um
        padrão que reproduz o visual de sempre):
        "primary_color": "#RRGGBB" (padrão branco "#FFFFFF") — cor do
            texto.
        "border_color": "#RRGGBB" (padrão preto "#000000") — cor do
            contorno ao redor das letras.
        "border_width": pixels de contorno (padrão 4).
        "shadow_depth": pixels de sombra projetada (padrão 0 — sem
            sombra).
        "glow": 0-20, intensidade de um brilho suave ao redor do texto
            (padrão 0 — sem brilho; usa desfoque do contorno via
            libass, não é um efeito nativo do ASS por si só).
        "font": "regular" ou "bold" (padrão "bold").
        "font_size": pixels (padrão: ~8% da altura do vídeo).
        "position": "bottom" (padrão) | "middle" | "top" — onde a
            legenda aparece verticalmente.
        "position_y_percent": 0-100, opcional — margem vertical exata
            (em % da altura, a partir da borda mais próxima conforme
            "position") em vez do padrão automático.
    """
    if not words:
        raise VideoAssemblyError("Lista de palavras vazia — nada pra gerar de legenda.")

    style = style or {}
    fontsize = fontsize or style.get("font_size") or max(24, round(video_height * 0.08))
    # a fonte em negrito NÃO é um nome de fonte diferente — é a MESMA
    # família ("DejaVu Sans"), com a flag Bold do estilo ligada (-1) ou
    # desligada (0); o libass escolhe a variante certa dos 2 arquivos
    # de fonte embutidos (DejaVuSans.ttf / DejaVuSans-Bold.ttf) com
    # base nessa flag, não no nome.
    font_name = _FONT_FAMILY_NAME
    bold_flag = -1 if style.get("font", "bold") == "bold" else 0

    primary_colour = _hex_to_ass_color(style.get("primary_color", "#FFFFFF"))
    outline_colour = _hex_to_ass_color(style.get("border_color", "#000000"))
    # BackColour serve pra cor da SOMBRA quando BorderStyle=1 (o que
    # usamos aqui) — sem sombra configurada, mantém preto opaco (não
    # importa a cor exata já que Shadow=0 não desenha nada mesmo).
    back_colour = _hex_to_ass_color(style.get("border_color", "#000000"))

    outline_width = max(0, style.get("border_width", 4))
    shadow_depth = max(0, style.get("shadow_depth", 0))

    position = style.get("position", "bottom")
    alignment = _CAPTION_ALIGNMENTS.get(position, 2)
    if "position_y_percent" in style:
        margin_v = round(video_height * max(0.0, min(100.0, style["position_y_percent"])) / 100)
    else:
        margin_v = round(video_height * 0.12)

    # "brilho" (glow): libass não tem um parâmetro de estilo nativo pra
    # isso — a forma prática de simular é aplicar `\blur` (desfoque do
    # contorno/sombra) via override tag direto no texto de cada linha,
    # não no cabeçalho de estilo. Guardamos aqui e aplicamos abaixo.
    glow = max(0, min(20, style.get("glow", 0)))
    blur_tag = f"{{\\blur{glow}}}" if glow > 0 else ""

    header = (
        "[Script Info]\n"
        "Title: Word Captions\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {video_width}\n"
        f"PlayResY: {video_height}\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Word,{font_name},{fontsize},{primary_colour},&H0000FFFF,{outline_colour},{back_colour},{bold_flag},0,0,0,"
        f"100,100,0,0,1,{outline_width},{shadow_depth},{alignment},10,10,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = [header]
    for w in words:
        text = _escape_ass_text(w["word"])
        if not text:
            continue
        start = _seconds_to_ass_timestamp(w["start"])
        end = _seconds_to_ass_timestamp(w["end"])
        lines.append(f"Dialogue: 0,{start},{end},Word,,0,0,0,,{blur_tag}{text}\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return output_path


def burn_captions(video_path: str, ass_path: str, output_path: str) -> str:
    """Queima a legenda .ass no vídeo (sobrepõe visualmente, permanente
    — não é uma faixa de legenda separada/opcional no player). O áudio é
    copiado sem recodificar.

    `fontsdir` aponta pro nosso `assets/fonts/` — sem isso, o libass
    (que renderiza o .ass) também dependeria do fontconfig do sistema
    pra achar a fonte pelo nome, e quebraria do mesmo jeito que o
    drawtext quebrava sem `fontfile=`.
    """
    escaped_ass_path = _escape_path_for_ffmpeg_filter(os.path.abspath(ass_path))
    escaped_fonts_dir = _escape_path_for_ffmpeg_filter(_FONT_DIR)
    import export_paralelo  # ⚡ v84_115: em pedaços paralelos (o tempo da legenda continua o do vídeo inteiro)
    try:
        _dur = _probe_duration(video_path)
    except VideoAssemblyError:
        _dur = 0.0
    if export_paralelo.tentar("legenda", lambda: export_paralelo.vf_em_pedacos(
            video_path, output_path, f"ass={escaped_ass_path}:fontsdir={escaped_fonts_dir}", _dur,
            os.path.join(os.path.dirname(os.path.abspath(output_path)), "_pedacos_legenda"), "legenda")):
        return output_path
    _run_ffmpeg([
        "-i", video_path,
        "-vf", f"ass={escaped_ass_path}:fontsdir={escaped_fonts_dir}",
        "-c:a", "copy",
        output_path,
    ], timeout=4 * 3600)  # vídeo longo queimando legenda num passe só passa fácil dos 5 min do padrão
    return output_path


def _escolher_candidato_previa(candidates: List[Dict[str, Any]], tracker: Optional["UsedClipsTracker"], provider: str,
                               evitar: Optional[set] = None) -> Optional[Dict[str, Any]]:
    """Qual candidato mostrar na prévia. Sem tracker: o melhor (o 1º), se
    tiver thumbnail — comportamento de sempre. Com tracker ("não repetir"):
    o melhor que AINDA NÃO foi usado em outro trecho — se o 1º já foi, olha o
    2º, o 3º... e assim por diante; só se TODOS já foram usados é que repete
    o melhor (preferível a deixar o trecho sem prévia)."""
    if evitar:
        # timeline 2 ("2ª opção"): o que a timeline 1 já mostra fica de fora
        candidates = [c for c in candidates if (c.get("url") or c.get("id")) not in evitar and c.get("url") not in evitar]
    if tracker is None:
        return candidates[0] if candidates and candidates[0].get("thumbnail") else None
    com_thumb = [c for c in candidates if c.get("thumbnail")]
    for c in com_thumb:
        cid = c.get("id")
        if not cid or tracker.try_claim(cid, provider):
            return c
    return com_thumb[0] if com_thumb else None


def _estilo_conta(provider: Optional[str]) -> bool:
    """Acervos de anime/filmes (desenho de propósito) e o Flow (imagem gerada por IA) ficam fora do filtro de estilo."""
    return provider not in BIBLIOTECAS_LOCAIS and provider not in GERADORES_IA + ("produto", "material")


def _ordenar_resultados_estilo(resultados: List[Any], provider: Optional[str] = None,
                               orientacao: Optional[str] = None) -> List[Any]:
    """Na montagem (busca de novo): os resultados do toolkit com desenho/3D/recorte vão pro fim
    (config do site; a escolha da prévia — que já usa a ficha do vídeo — fica fixada quando dá)."""
    if not _estilo_conta(provider):
        return list(resultados or [])
    try:
        import estilo_imagem
        return estilo_imagem.ordenar_resultados(resultados, load_site_config(), orientacao=orientacao)
    except Exception:  # noqa: BLE001
        return list(resultados or [])


def _filtro_estilo(cfg: Optional[Dict[str, Any]]) -> bool:
    """Tem o que conferir na miniatura? (🎞️ imagens reais e/ou 🖼️ o formato do vídeo)."""
    try:
        import estilo_imagem
        return estilo_imagem.filtro_ativo(cfg)
    except Exception:  # noqa: BLE001
        return False


def _so_real(cfg: Optional[Dict[str, Any]]) -> bool:
    """🎞️ O vídeo é de imagens reais? (estilo_imagem.py; desligável em Configurações → Estilo das imagens)."""
    try:
        import estilo_imagem
        return estilo_imagem.modo_real(cfg)
    except Exception:  # noqa: BLE001
        return False


def _ordenar_por_estilo(candidates: List[Dict[str, Any]], cfg: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    try:
        import estilo_imagem
        return estilo_imagem.ordenar_candidatos(candidates, cfg)
    except Exception:  # noqa: BLE001
        return candidates


def _ia_pode(recurso: str) -> bool:
    try:
        import ia_servico
        return ia_servico.ativo(recurso)
    except Exception:  # noqa: BLE001
        return False


def _ia_cfg() -> Dict[str, Any]:
    try:
        import ia_servico
        return ia_servico.config()
    except Exception:  # noqa: BLE001
        return {"nota_minima": 7, "candidatos": 10}


def julgar_candidatos_ia(candidates: List[Dict[str, Any]], ia_ctx: Optional[Dict[str, Any]], busca: str,
                         recurso: str = "juiz", miniatura: str = "thumbnail") -> Optional[Dict[str, Any]]:
    """🤖 Fase 2 (juiz visual): None sem IA; senão {"lista": candidatos na ordem da nota (com ia_nota/ia_motivo),
    "nova_busca": str}."""
    if not candidates or not ia_ctx or not _ia_pode(recurso):
        return None
    try:
        import ia_midia
        j = ia_midia.julgar(candidates, ia_ctx.get("fala") or "", ia_ctx.get("ficha"), ia_ctx.get("anterior") or "",
                            ia_ctx.get("seguinte") or "", ia_ctx.get("visual") or "", busca, recurso, ia_ctx.get("job"), miniatura)
    except Exception:  # noqa: BLE001
        return None
    if not j:
        return None
    return {"lista": ia_midia.reordenar(candidates, j), "nova_busca": j.get("nova_busca") or ""}


def fetch_segment_preview_lightweight(
    segment: VideoSegment,
    site_cfg: Optional[Dict[str, Any]] = None,
    client_factory: Optional["ClientFactory"] = None,
    used_tracker: Optional["UsedClipsTracker"] = None,
    evitar: Optional[set] = None,
    ia_ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Versão RÁPIDA da prévia: busca (sem baixar nada) e devolve a URL
    do thumbnail já hospedado no próprio provedor (CDN de imagens) —
    o navegador da pessoa carrega essa imagem direto de lá, sem nosso
    servidor precisar baixar o vídeo inteiro só pra tirar um frame.

    Isso substitui `fetch_segment_preview()` (que baixa o arquivo de
    verdade) na etapa de PRÉVIA da timeline — a etapa de MONTAGEM final
    continua baixando o arquivo completo normalmente, só que agora só
    acontece uma vez (ou de novo, se a pessoa editar o segmento),
    nunca duas vezes à toa.

    Tenta, em ordem: o termo original no provedor da IA, os termos de
    fallback no mesmo provedor, e SÓ DEPOIS os outros provedores (na
    ordem de prioridade configurada) — do mesmo jeito que a montagem
    final já faz. Sem isso, um provedor fora do ar/bloqueado fazia a
    prévia mostrar "sem prévia" mesmo quando a montagem final (que
    sempre tentou os outros bancos) daria certo tranquilamente —
    mostrando uma falsa impressão de que aquele trecho não tem solução.

    🤖 `ia_ctx` ({"ficha", "fala", "anterior", "seguinte", "visual", "job"}) com a IA ligada: pede
    mais candidatos e o JUIZ escolhe pela miniatura (nota ≥ mínima = usa; 5–6 = usa com ⚠;
    < 5 = busca de novo com a sugestão dele, no máximo 2 vezes, e no fim a melhor das
    reprovadas com ⚠). Sem IA, igual a antes.

    Devolve: {"ok": bool, "thumbnail_url": str|None, "result_url": str|None,
    "label": str|None, "error": str|None, "video_preview_url": str|None,
    "provider": str|None} (+ "ia_nota"/"ia_motivo"/"ia_aviso"/"ia_busca" quando a IA julgou). "provider" é o banco que de fato funcionou —
    pode ser DIFERENTE do banco original do segmento, se esse tiver
    falhado e a busca caiu pro próximo da lista de prioridade.
    "result_url" é a URL da página do resultado escolhido — guardada
    pra "fixar" essa exata escolha na hora de montar (via link de
    post), sem precisar buscar de novo se o segmento não foi editado.
    Só funciona pra fixar em Pexels/Pixabay/Mixkit (os únicos com
    resolução por URL no toolkit); pros outros dois, a prévia mostra
    igual, mas a montagem faz uma busca nova (pode trazer um resultado
    ligeiramente diferente).
    """
    media_type = getattr(segment, "media_type", "video")
    last_error: Optional[str] = None

    if media_type == "image":
        # busca de foto não tem fallback entre provedores — se o segmento
        # pediu "pexels" ou "wikipedia" (os dois únicos que suportam
        # media_type="image"), tenta só esse, nunca "cai" pra outro banco
        # que nunca teve chance de funcionar pra foto.
        providers_to_try = [segment.provider]
        cfg = site_cfg or load_site_config()
    else:
        cfg = site_cfg or load_site_config()
        provider_priority = cfg.get("provider_priority") or ["pexels", "pixabay", "magnific", "mixkit", "vistacreate", "animepexels"]
        providers_to_try = _sem_bloqueados([segment.provider] + _sem_flow_no_fallback(provider_priority, segment.provider), cfg)

    # acervo local com obra/personagem: o metadado já é confiável, pula o juiz
    acervo_confiavel = segment.provider in BIBLIOTECAS_LOCAIS and bool(getattr(segment, "obra", None) or getattr(segment, "personagem", None))
    # 🖥️ imagem gerada no SEU pod pra essa cena (Produção no pod / Meu pod): foi feita sob medida — o juiz não troca por
    # cartão nem pede "nova busca" (que geraria outra imagem no pod)
    usar_ia = bool(ia_ctx) and not acervo_confiavel and segment.provider != "runpod" and _ia_pode("juiz")
    ia_c = _ia_cfg() if usar_ia else {}
    reprovada: Optional[Dict[str, Any]] = None
    novas_buscas = 0
    rigoroso = bool(getattr(segment, "_rigoroso", False))

    def _resultado(c: Dict[str, Any], provider: str, query: str, aviso: bool = False) -> Dict[str, Any]:
        out = {
            "ok": True, "thumbnail_url": c["thumbnail"], "result_url": c.get("url") or None,
            "label": ("⚠ " if aviso else "") + (c.get("label") or ""), "error": None,
            "video_preview_url": c.get("video_preview_url") or None,
            "provider": provider,
        }
        if "ia_nota" in c:
            out.update(ia_nota=c["ia_nota"], ia_motivo=c.get("ia_motivo") or "", ia_aviso=bool(aviso),
                       ia_busca=query if query != segment.query else None)
        return out

    for provider in providers_to_try:
        provider_timeout = _provider_timeout_seconds(cfg, provider)
        # "não repetir": pede vários candidatos (não só o 1º) pra poder cair
        # no 2º, 3º... quando o melhor já foi usado em outro trecho.
        tracker = _tracker_para(provider, used_tracker)
        max_results = 8 if (tracker is not None or evitar) else 1
        if usar_ia:
            max_results = max(max_results, int(ia_c.get("candidatos") or 10))
        if _filtro_estilo(cfg) and _estilo_conta(provider):  # 🎞️🖼️ pede alguns a mais pra poder pular desenho/3D/recorte/formato errado
            max_results = max(max_results, 6)
        queries_to_try = [segment.query] + _fallback_queries_for(segment)
        qi = 0
        while qi < len(queries_to_try):
            query = queries_to_try[qi]
            qi += 1
            try:
                candidates = _run_with_timeout(
                    lambda: search_candidates(
                        provider, query, media_type=media_type, max_results=max_results,
                        site_cfg=site_cfg, client_factory=client_factory,
                        keyword_weight=segment.keyword_weight, semantic_weight=segment.semantic_weight,
                        obra=getattr(segment, "obra", None) if provider == segment.provider else None,
                        personagem=getattr(segment, "personagem", None) if provider == segment.provider else None,
                    ),
                    provider_timeout,
                )
            except (VideoAssemblyError, TimeoutError) as exc:
                # timeout aqui também conta como falha desse provedor —
                # mesmo raciocínio da montagem: um banco travado não deve
                # segurar a prévia inteira, já que o objetivo dela é
                # justamente ser rápida.
                last_error = str(exc)
                continue

            if candidates and _filtro_estilo(cfg) and _estilo_conta(provider):  # 🎞️ desenho/3D/recorte e 🖼️ formato errado pro fim
                candidates = _ordenar_por_estilo(candidates, cfg)

            if usar_ia and candidates:
                j = julgar_candidatos_ia([c for c in candidates if c.get("thumbnail")], ia_ctx, query)
                if j:
                    minima = int(ia_c.get("nota_minima") or 7)
                    # trecho abstrato (a IA disse "cartao"): só passa o que é BOM de verdade — senão vira cartão de texto
                    corte = minima if (rigoroso and _ia_pode("cartao")) else 5
                    aprovados = [c for c in j["lista"] if c.get("ia_nota", 0) >= corte]
                    if aprovados:
                        # "não repetir" vem DEPOIS da nota: entre as aprovadas, a melhor ainda não usada
                        c = _escolher_candidato_previa(aprovados, tracker, provider, evitar)
                        if c is not None:
                            return _resultado(c, provider, query, aviso=c.get("ia_nota", 0) < minima)
                    melhor = next((c for c in j["lista"] if not c.get("marca_dagua")), None)  # ⛔ marca d'água nunca é a "menos pior"
                    if melhor is not None and (reprovada is None or melhor.get("ia_nota", 0) > reprovada["nota"]):
                        reprovada = {"nota": melhor.get("ia_nota", 0), "res": _resultado(melhor, provider, query, aviso=True)}
                    nova = (j.get("nova_busca") or "").strip()
                    if nova and novas_buscas < 2 and _ia_pode("nova_busca") and nova not in queries_to_try:
                        queries_to_try.insert(qi, nova)  # Fase 3: a busca reescrita pelo juiz, logo em seguida
                        novas_buscas += 1
                    last_error = f"a IA reprovou os resultados de '{query}' em {provider}"
                    continue
            c = _escolher_candidato_previa(candidates, tracker, provider, evitar)
            if c is not None:
                if (c.get("estilo_problema") or c.get("formato_errado")) and qi < len(queries_to_try):
                    # 🎞️🖼️ só sobrou desenho/recorte (ou mídia no formato errado) nessa busca: reserva e tenta a próxima
                    if tracker is not None and c.get("id"):
                        try:
                            tracker.release(c["id"], provider)  # não usou: libera pra outro trecho
                        except Exception:  # noqa: BLE001
                            pass
                    if reprovada is None:
                        reprovada = {"nota": -1, "res": _resultado(c, provider, query, aviso=True), "estilo": True}
                    last_error = f"só ilustração/recorte ou formato errado em '{query}' ({provider})"
                    continue
                return _resultado(c, provider, query, aviso=bool(c.get("estilo_problema") or c.get("formato_errado")))
            last_error = f"nenhum resultado com thumbnail pra '{query}' em {provider}"

    if reprovada is not None:
        if _ia_pode("cartao") and not reprovada.get("estilo"):  # 🃏 nada prestou: em vez da "menos pior", um cartão de texto (o app monta)
            return {"ok": False, "cartao": True, "thumbnail_url": None, "result_url": None, "label": None,
                    "error": f"nenhuma imagem boa (melhor nota {reprovada['nota']})", "video_preview_url": None,
                    "provider": None, "ia_nota": reprovada["nota"],
                    "ia_motivo": (reprovada["res"].get("ia_motivo") or "")}
        return reprovada["res"]  # nada passou: a melhor das reprovadas, com ⚠ pra você trocar

    return {
        "ok": False, "thumbnail_url": None, "result_url": None, "label": None,
        "error": last_error, "video_preview_url": None, "provider": None,
    }


def fetch_segment_preview(
    segment: VideoSegment,
    downloads_dir: str,
    site_cfg: Optional[Dict[str, Any]] = None,
    get_client_fn=None,
    client_factory: Optional["ClientFactory"] = None,
) -> Dict[str, Any]:
    """Busca e baixa (sem normalizar/cortar ainda) o resultado padrão de
    um segmento — usado pra popular a timeline do editor com uma prévia
    de verdade antes da montagem final. Devolve um dict com o caminho
    baixado, o tipo de mídia, e se algo deu errado (nesse caso o editor
    mostra "sem prévia" pro usuário e deixa ele escolher manualmente, em
    vez de travar tudo por causa de 1 segmento sem prévia).
    """
    try:
        if get_client_fn is not None:
            client = _get_or_create_client(segment.provider, {}, get_client_fn)
            if getattr(segment, "media_type", "video") == "image":
                raw_path = _search_and_download_photo(segment, downloads_dir, client, fallback_queries=_fallback_queries_for(segment))
            else:
                raw_path = _search_and_download_one(
                    segment, downloads_dir, client, fallback_queries=_fallback_queries_for(segment), quality="worst",
                )
        else:
            cfg = site_cfg or load_site_config()
            factory = client_factory or ClientFactory(cfg)
            if getattr(segment, "media_type", "video") == "image":
                raw_path = _download_image_segment_with_fallbacks(segment, downloads_dir, factory)
            else:
                provider_priority = cfg.get("provider_priority") or ["pexels", "pixabay", "magnific", "mixkit", "vistacreate", "animepexels"]
                raw_paths = _download_segment_with_fallbacks(
                    segment, downloads_dir, factory, provider_priority, cfg.get("orientation", "16:9"),
                    magnific_only_free=cfg.get("magnific_only_free", True), quality="worst",
                )
                # é só uma PRÉVIA (thumbnail representativo) — não precisa
                # preencher a duração toda com cenas extras como a
                # montagem final faz; o primeiro clipe encontrado já serve.
                raw_path = raw_paths[0]
        return {"ok": True, "raw_path": raw_path, "kind": _infer_media_kind(raw_path), "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "raw_path": None, "kind": None, "error": str(exc)}


def _resolve_override_source(override: Dict[str, Any], downloads_dir: str, get_client_for_provider) -> (str, str):
    """Resolve a fonte de mídia definida manualmente pra um segmento
    (editor de segmentos), pulando a busca por completo. Devolve
    (caminho_local, "video"|"image").

    get_client_for_provider: função (provider_str) -> cliente, usada só
    quando `source == "provider_url"` (funciona com o `get_client_fn` do
    caminho legado ou com `ClientFactory.get_client` do caminho real).
    """
    source = override.get("source")
    kind = override.get("kind")

    if source == "local_file":
        path = override.get("value")
        if not path or not os.path.exists(path):
            raise VideoAssemblyError(f"Arquivo local não encontrado: {path!r}")
        # a extensão manda mais que um "kind" antigo: uma .avif marcada como
        # vídeo era mandada pro ffprobe e a montagem falhava ("duration")
        tipo_real = _infer_media_kind(path)
        if tipo_real == "image":
            kind = "image"
        _validate_downloaded_file(path)
        if (kind or tipo_real) == "image":
            path = garantir_imagem_compativel(path)
        return path, kind or tipo_real

    if source == "url":
        url = override.get("value")
        if not url:
            raise VideoAssemblyError("override_source do tipo 'url' precisa de 'value' com o link.")
        local_flow = flow_arquivo_local(url)  # v84_112: mídia do Flow que já está no disco — nada de baixar/gerar
        if local_flow:
            if _infer_media_kind(local_flow) == "image":
                return garantir_imagem_compativel(local_flow), "image"
            return local_flow, "video"
        local_path = _download_generic_url(url, downloads_dir)
        _validate_downloaded_file(local_path)
        kind = kind or _infer_media_kind(local_path) or _infer_media_kind(url)
        if kind == "image" or _infer_media_kind(local_path) == "image":
            return garantir_imagem_compativel(local_path), "image"
        return local_path, kind

    if source == "provider_url":
        provider = override.get("provider")
        url = override.get("value")
        if provider not in _PROVIDERS_WITH_URL_RESOLUTION:
            raise VideoAssemblyError(
                f"'{provider}' não suporta resolver um link de post diretamente — só "
                f"{sorted(_PROVIDERS_WITH_URL_RESOLUTION)} suportam isso por enquanto "
                f"(Magnific e VistaCreate não têm essa funcionalidade no toolkit)."
            )
        try:
            client = get_client_for_provider(provider)
            video = client.get_video_by_url(url)
            local_path = client.download_video(video, output_dir=downloads_dir)
            _validate_downloaded_file(local_path)
        except VideoAssemblyError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VideoAssemblyError(f"Falha ao resolver/baixar {url} em {provider}: {exc}") from exc
        return local_path, "video"

    raise VideoAssemblyError(f"override_source com 'source' desconhecido: {source!r}")


# ------------------------------------------------------------------ #
# ⬇ Pré-download: as mídias já escolhidas (clipe da prévia, link,
# resultado fixado) são baixadas EM SEGUNDO PLANO enquanto a pessoa está
# no Estúdio. Na montagem, o mesmo link sai da pasta `prebaixados/` do job
# em vez de ser baixado de novo — a montagem só normaliza e junta.
# ------------------------------------------------------------------ #
_PREBAIXADOS_LOCK = threading.Lock()
PREBAIXADOS_INDICE = "indice.json"
CLIPES_PRONTOS_VERSAO = 2  # v84_84/85: imagem nas bordas, entradas corrigidas, cartão sobre fundo — suba quando o jeito de cortar/normalizar mudar (invalida os clipes guardados)
_TRAVAS_CHAVE: Dict[str, Any] = {}


def chave_prebaixado(override: Optional[Dict[str, Any]]) -> Optional[str]:
    """Identidade de uma mídia baixável: (fonte, banco, link). Arquivo do PC
    (`local_file`) não precisa — já está no disco."""
    if not isinstance(override, dict):
        return None
    source = override.get("source")
    value = str(override.get("value") or "").strip()
    if source not in ("url", "provider_url") or not value:
        return None
    import hashlib
    bruto = f"{source}|{override.get('provider') or ''}|{value}"
    return hashlib.sha1(bruto.encode("utf-8")).hexdigest()[:20]


def _indice_prebaixados(cache_dir: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(cache_dir, PREBAIXADOS_INDICE), encoding="utf-8") as f:
            dados = json.load(f)
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def prebaixado(override: Optional[Dict[str, Any]], cache_dir: Optional[str]) -> Optional[tuple]:
    """(caminho, tipo) se essa mídia já foi baixada e o arquivo ainda existe."""
    chave = chave_prebaixado(override)
    if not chave or not cache_dir:
        return None
    with _PREBAIXADOS_LOCK:
        hit = _indice_prebaixados(cache_dir).get(chave)
    if isinstance(hit, dict) and hit.get("path") and os.path.exists(hit["path"]) and os.path.getsize(hit["path"]) > 0:
        return hit["path"], hit.get("kind") or _infer_media_kind(hit["path"]) or "video"
    return None


def resolver_override_cacheado(override: Dict[str, Any], downloads_dir: str, get_client_for_provider,
                               cache_dir: Optional[str] = None) -> tuple:
    """Igual a `_resolve_override_source`, mas reaproveita/guarda o arquivo em
    `cache_dir` (cada link na sua própria subpasta: dois downloads ao mesmo
    tempo nunca escrevem no mesmo arquivo)."""
    hit = prebaixado(override, cache_dir)
    if hit:
        return hit
    chave = chave_prebaixado(override)
    if not chave or not cache_dir:
        return _resolve_override_source(override, downloads_dir, get_client_for_provider)
    with _PREBAIXADOS_LOCK:
        trava = _TRAVAS_CHAVE.setdefault(os.path.abspath(cache_dir) + "|" + chave, threading.Lock())
    with trava:  # o Estúdio e a montagem pedindo o mesmo link ao mesmo tempo: o 2º espera e reaproveita
        hit = prebaixado(override, cache_dir)
        if hit:
            return hit
        return _baixar_para_cache(override, chave, cache_dir, get_client_for_provider)


def _baixar_para_cache(override, chave, cache_dir, get_client_for_provider) -> tuple:
    destino = os.path.join(cache_dir, chave)
    os.makedirs(destino, exist_ok=True)
    path, kind = _resolve_override_source(override, destino, get_client_for_provider)
    with _PREBAIXADOS_LOCK:
        idx = _indice_prebaixados(cache_dir)
        idx[chave] = {"path": os.path.abspath(path), "kind": kind, "link": override.get("value"),
                      "provider": override.get("provider"), "quando": time.time()}
        tmp = os.path.join(cache_dir, PREBAIXADOS_INDICE + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False)
        os.replace(tmp, os.path.join(cache_dir, PREBAIXADOS_INDICE))
    return path, kind


def prebaixar_midias(overrides: List[Dict[str, Any]], cache_dir: str, cfg: Optional[Dict[str, Any]] = None,
                     on_item=None, cancel_check=None, factory_fn=None) -> Dict[str, Any]:
    """Baixa em paralelo (`assembly_fetch_concurrency`) todas as mídias da
    lista que ainda não estão em `cache_dir`. Nunca levanta erro: um link que
    falha fica pra montagem tentar de novo (e, se for da prévia, buscar outro).

    `on_item(feitos, total, ok)` a cada item. Devolve {total, baixados, ja_tinha, falhas, erros}."""
    cfg = cfg if cfg is not None else load_site_config()
    vistos, fila = set(), []
    for ov in overrides:
        k = chave_prebaixado(ov)
        if k and k not in vistos:
            vistos.add(k)
            fila.append(ov)
    res = {"total": len(fila), "baixados": 0, "ja_tinha": 0, "falhas": 0, "erros": []}
    pendentes = []
    for ov in fila:
        if prebaixado(ov, cache_dir):
            res["ja_tinha"] += 1
        else:
            pendentes.append(ov)
    feitos = res["ja_tinha"]
    if on_item:
        on_item(feitos, res["total"], True)
    if not pendentes:
        return res
    os.makedirs(cache_dir, exist_ok=True)
    trava = threading.Lock()
    fabrica = factory_fn or (lambda: ClientFactory(cfg))

    def _um(ov):
        if cancel_check and cancel_check():
            return False, "cancelado"
        f = fabrica()
        try:
            resolver_override_cacheado(ov, cache_dir, f.get_client, cache_dir=cache_dir)
            return True, None
        except Exception as exc:  # noqa: BLE001
            return False, f"{ov.get('value')}: {str(exc)[:200]}"
        finally:
            try:
                f.close_all()
            except Exception:  # noqa: BLE001
                pass

    n = max(1, min(int(cfg.get("assembly_fetch_concurrency", 3) or 3), len(pendentes)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        for fut in concurrent.futures.as_completed([ex.submit(_um, ov) for ov in pendentes]):
            ok, erro = fut.result()
            with trava:
                feitos += 1
                if ok:
                    res["baixados"] += 1
                else:
                    res["falhas"] += 1
                    if erro and len(res["erros"]) < 20:
                        res["erros"].append(erro)
            if on_item:
                on_item(feitos, res["total"], ok)
    return res


def resolve_overlay_source(overlay_source: Dict[str, Any], downloads_dir: str, get_client_for_provider) -> "tuple[str, str]":
    """Resolve a fonte de mídia de um OVERLAY (imagem/vídeo sobreposto
    ao vídeo final, com posição/tamanho/janela de tempo próprios) —
    reaproveita `_resolve_override_source` pros modos "local_file",
    "url" e "provider_url" (upload, link direto, ou link de um post
    específico já conhecido), e adiciona um modo NOVO, "provider_search":
    busca de verdade num banco de vídeo (Pexels, Pixabay, etc.) e usa o
    primeiro resultado encontrado — pra quando a pessoa não tem um link
    específico em mente, só uma ideia do que procurar.

    Formato de `overlay_source` pro modo novo:
        {"source": "provider_search", "provider": "pexels", "query": "logo animation"}
    (média sempre tratada como vídeo por enquanto — busca de FOTO pra
    overlay ainda não suportada; use "local_file"/"url" pra uma imagem.)

    Devolve (caminho_local, "video"|"image"), igual a
    `_resolve_override_source`.
    """
    if overlay_source.get("source") != "provider_search":
        return _resolve_override_source(overlay_source, downloads_dir, get_client_for_provider)

    provider = overlay_source.get("provider")
    query = overlay_source.get("query")
    if not provider or not query:
        raise VideoAssemblyError("overlay do tipo 'provider_search' precisa de 'provider' e 'query'.")

    try:
        client = get_client_for_provider(provider)
        if provider == "mixkit":
            results = client.search_all(category=query, max_pages=1)
        else:
            results = client.search_all(query=query, max_pages=1)
        if not results:
            raise VideoAssemblyError(f"Nenhum resultado pra '{query}' em {provider} (busca do overlay).")
        chosen = results[0]
        local_path = client.download_video(chosen, output_dir=downloads_dir)
        _validate_downloaded_file(local_path)
    except VideoAssemblyError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VideoAssemblyError(f"Falha ao buscar/baixar overlay '{query}' em {provider}: {exc}") from exc

    return local_path, "video"


# ------------------------------------------------------------------ v84_110: Flow esgotado → foto → pesquisa
def _etapa_inteira(antes: str, depois: str, etapa: str, work_dir: str) -> bool:
    """v84_119: a etapa devolveu a IMAGEM do vídeo inteira? Se ela acabar antes (o áudio segue e a imagem congela
    no último quadro), a etapa é PULADA — o vídeo fica sem ela, mas não congela — e isso vai pros avisos da montagem."""
    import export_paralelo
    da, dd = export_paralelo.duracao_do_video(antes), export_paralelo.duracao_do_video(depois)
    if da is None or dd is None or dd >= da - 1.0:
        return True
    aviso = (f"A etapa “{etapa}” cortou a imagem do vídeo em {int(dd // 60)}:{dd % 60:04.1f} (devia ir até "
             f"{int(da // 60)}:{da % 60:04.1f}) — ela foi PULADA pra o vídeo não congelar no fim. Monte de novo; se repetir, "
             "mande o diagnóstico.")
    print(f"[montagem] ⚠ {aviso}", flush=True)
    try:
        caminho = os.path.join(work_dir, "avisos_montagem.json")
        avisos = json.load(open(caminho, encoding="utf-8")) if os.path.exists(caminho) else []
        avisos.append(aviso)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(avisos, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass
    return False


def flow_tem_conta(tipo: str, cfg: Optional[Dict[str, Any]] = None) -> Optional[bool]:
    """Alguma conta do Google Flow ainda serve pra `tipo` ("video"/"imagem")? None = não dá pra saber (segue tentando)."""
    if str((cfg or {}).get("flow_navegador") or "auto").lower() == "cdp":
        return None  # o Chrome do próprio usuário: não tem troca de contas pra conferir
    try:
        from googleflow import googleflow_client as gf
        gf.escolher_conta_disponivel(tipo=tipo)
        return True
    except Exception as exc:  # noqa: BLE001
        return False if type(exc).__name__ == "GoogleFlowSemContas" else None


def flow_arquivo_local(url: Any) -> Optional[str]:
    """v84_112: link de mídia do Flow que JÁ está no disco ("/flow/imagens/<arq>" = gerada pros vídeos;
    "/flow/arquivo/<arq>" = galeria da aba 🎬 Google Flow) → o caminho do arquivo (ou None)."""
    u = str(url or "").split("?", 1)[0].split("#", 1)[0]
    if "/runpod/midias/" in u:  # 🟣 gerada no Runpod
        try:
            return importlib.import_module("runpod_gerador").arquivo_local(u)
        except Exception:  # noqa: BLE001
            return None
    m = re.search(r"/flow/(imagens|arquivo)/([^/]+)$", u)
    if not m:
        return None
    try:
        if m.group(1) == "imagens":
            from googleflow import googleflow_client as gf
            caminho = os.path.join(str(gf.pasta_imagens()), os.path.basename(m.group(2)))
        else:
            import flow_estudio
            caminho = os.path.join(flow_estudio.pasta_galeria(), os.path.basename(m.group(2)))
    except Exception:  # noqa: BLE001
        return None
    return caminho if os.path.isfile(caminho) else None


def flow_ja_gerado(query: str, cfg: Optional[Dict[str, Any]], tipo: str) -> bool:
    """Esse pedido JÁ foi gerado no Flow (está no cache do site)? Aí a montagem usa ele mesmo sem crédito nenhum."""
    try:
        from googleflow import googleflow_client as gf
        prop = gf.proporcao_para_orientacao((cfg or {}).get("orientation"))
        if tipo == "video":
            return bool(gf._videos_do_cache(gf.chave_do_prompt(gf.montar_prompt_video(query, prop))))
        return bool(gf._fotos_do_cache(gf.chave_do_prompt(gf.montar_prompt(query, prop))))
    except Exception:  # noqa: BLE001
        return False


def _termo_de_pesquisa(segment: VideoSegment) -> str:
    """O prompt do Flow é uma descrição longa: pra PESQUISAR usa a alternativa curta da IA, a busca reserva ou o núcleo."""
    for t in list(getattr(segment, "alternativas", None) or []) + [getattr(segment, "busca_reserva", None) or ""]:
        if t and t.strip():
            return t.strip()
    return _nucleo_da_busca(segment.query) or " ".join((segment.query or "").split()[:6])


def prompt_de_foto(prompt: str) -> str:
    """O prompt de VÍDEO reescrito como prompt de FOTO (tira movimento de câmera, duração…) — pra gerar a imagem da
    cena numa conta que não tem mais crédito de vídeo. 🤖 IA do site se ligada; senão a regra simples (sem esperar a
    🔎 IA do Google, que demora minutos por trecho)."""
    try:
        import flow_lote
        return flow_lote.reescrever_para_foto(prompt, ia_google=False)["prompt"]
    except Exception:  # noqa: BLE001
        return prompt


def gerar_no_runpod(segment: VideoSegment, downloads_dir: str, client_factory: "ClientFactory", cfg: Dict[str, Any],
                    orientation: Optional[str] = None, video: bool = False, used_tracker=None) -> Tuple[List[str], str, str]:
    """🟣 Gera a cena no Runpod: VÍDEO (Pruna) se pedido e o saldo paga; senão (ou se o vídeo falhar) a FOTO
    (Z-Image/Flux) com o prompt de vídeo reescrito como foto. → (arquivos, "video"|"image", o que aconteceu).
    Levanta erro se não deu nem foto (sem chave, sem saldo, recusa…)."""
    rp = importlib.import_module("runpod_gerador")
    if not rp.configurado(cfg):
        raise VideoAssemblyError("Runpod sem chave (⚙️ Configurações → 🟣 Runpod).")
    seg_rp = replace(segment, provider="runpod")
    motivo = ""
    if video:
        if rp.ja_gerado(segment.query, "video", cfg) or rp.tem_saldo("video", cfg) is not False:
            try:
                return _download_segment_with_fallbacks(seg_rp, downloads_dir, client_factory, [], orientation,
                                                        used_tracker=used_tracker), "video", "vídeo do Runpod"
            except Exception as exc:  # noqa: BLE001
                motivo = f"o vídeo do Runpod não saiu ({str(exc)[:160]})"
        else:
            motivo = "sem saldo no Runpod pra vídeo"
    q = segment.query
    if video and not rp.ja_gerado(q, "imagem", cfg):
        q = prompt_de_foto(segment.query)
    caminho = _download_image_segment_with_fallbacks(replace(seg_rp, media_type="image", query=q), downloads_dir,
                                                     client_factory, used_tracker=used_tracker)
    return [caminho], "image", ("foto do Runpod no lugar do vídeo (" + motivo + ")" if video else "foto do Runpod")


def _pesquisa_no_lugar_do_flow(segment: VideoSegment, downloads_dir: str, client_factory: "ClientFactory",
                               cfg: Dict[str, Any], provider_priority: Optional[List[str]] = None,
                               orientation: Optional[str] = None, video: bool = False, used_tracker=None,
                               motivo: str = "") -> Tuple[List[str], str]:
    """Nenhuma conta do Flow consegue gerar mais nada (nem vídeo nem foto): PESQUISA a cena nos mecanismos de busca
    MARCADOS pro vídeo (`cfg["_providers_marcados"]`, os que você marcou ao criar; sem isso, a prioridade das
    Configurações). Trecho de vídeo: bancos de vídeo → buscadores de imagem → bancos de foto. Trecho de foto:
    buscadores de imagem → bancos de foto → bancos de vídeo. → (arquivos, "video"|"image")."""
    termo = _termo_de_pesquisa(segment)
    marcados = [p for p in (cfg.get("_providers_marcados") or provider_priority or []) if p not in GERADORES_IA]
    ordem = [p for p in (provider_priority or []) if p in marcados] + [p for p in marcados if p not in (provider_priority or [])]
    ordem = _sem_bloqueados(ordem, cfg)
    bancos_video = [b for b in ordem if b not in ("youtube", "produto", "material", "wikipedia")
                    and b not in _BROWSER_IMAGE_SEARCH_PROVIDERS]
    buscadores = [b for b in ordem if b in _BROWSER_IMAGE_SEARCH_PROVIDERS]
    bancos_foto = [b for b in ordem if b in _PHOTO_PROVIDER_MODULES and b not in GERADORES_IA and b not in _BROWSER_IMAGE_SEARCH_PROVIDERS]
    erros: List[str] = []

    def _videos():
        if not bancos_video:
            return None
        try:
            return _download_segment_with_fallbacks(
                replace(segment, provider=bancos_video[0], query=termo, alternativas=[], media_type="video"), downloads_dir,
                client_factory, bancos_video, orientation, used_tracker=used_tracker), "video"
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{', '.join(bancos_video)}: {exc}")
            return None

    def _buscadores():
        if not buscadores:
            return None
        try:
            res = prefetch_browser_images([(0, replace(segment, provider=buscadores[0], query=termo, media_type="image"))],
                                          downloads_dir, cfg).get(0) or {}
            if res.get("ok") and res.get("path"):
                return [res["path"]], "image"
            erros.append(f"{', '.join(buscadores)}: {res.get('erro') or 'nada'}")
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{', '.join(buscadores)}: {exc}")
        return None

    def _fotos():
        for b in bancos_foto:
            try:
                return [_download_image_segment_with_fallbacks(replace(segment, provider=b, query=termo, media_type="image"),
                                                               downloads_dir, client_factory, used_tracker=used_tracker)], "image"
            except Exception as exc:  # noqa: BLE001
                erros.append(f"{b} (fotos): {exc}")
        return None

    for etapa in ((_videos, _buscadores, _fotos) if video else (_buscadores, _fotos, _videos)):
        r = etapa()
        if r:
            return r
    if not (bancos_video or buscadores or bancos_foto):
        erros.append("nenhum mecanismo de busca marcado pra este vídeo além do Flow")
    raise VideoAssemblyError(f"Flow: {motivo or 'não gerou'} — e a pesquisa por '{termo}' nos mecanismos marcados também "
                             f"não achou ({'; '.join(erros)}).")


def _download_image_segment_with_fallbacks(
    segment: VideoSegment,
    downloads_dir: str,
    client_factory: ClientFactory,
    used_tracker: Optional["UsedClipsTracker"] = None,
) -> str:
    """Busca/baixa uma foto pro segmento (`media_type == "image"`),
    usando o provedor de foto do PRÓPRIO segmento — hoje, "pexels" (API
    oficial) ou "wikipedia" (Wikipedia/Wikimedia Commons, sem chave).
    Não tem fallback pro navegador aqui, já que o scraping não busca
    fotos em nenhum dos dois.
    """
    try:
        photo_client = client_factory.get_photo_client(segment.provider)
    except Exception as exc:  # noqa: BLE001
        raise VideoAssemblyError(
            f"Não consigo buscar fotos (media_type='image') com '{segment.provider}': {exc}"
        ) from exc
    return _search_and_download_photo(
        segment, downloads_dir, photo_client, fallback_queries=_fallback_queries_for(segment), used_tracker=used_tracker,
    )


def _consulta_simplificada(query: str, alternativas: Optional[List[str]] = None) -> Optional[str]:
    """Termo reserva pros buscadores de imagem: a 1ª alternativa que a IA
    sugeriu pro trecho; sem ela, a última palavra (mais genérica) quando o
    termo tem várias — mesma ideia de `_fallback_queries_for`, sem o "nature
    background" (que num buscador da web aberta traria uma foto qualquer, sem
    relação com o trecho)."""
    for alt in alternativas or []:
        if alt and alt.strip() and " ".join(alt.lower().split()) != " ".join((query or "").lower().split()):
            return alt.strip()
    words = (query or "").split()
    return words[-1] if len(words) > 1 else None


def _variante_da_imagem(res: Dict[str, Any], k: int) -> Dict[str, Any]:
    """O mesmo termo em vários trechos: o k-ésimo trecho fica com a k-ésima
    imagem diferente que a busca trouxe (`extras`); se vieram menos imagens
    que trechos, recomeça da 1ª."""
    variantes = [v for v in [None] + list(res.get("extras") or [])
                 if v is None or (v.get("path") and os.path.exists(v["path"]))]
    v = variantes[k % len(variantes)] if variantes else None
    if v is None:
        return res
    return dict(res, **{c: v.get(c) for c in ("path", "engine", "title", "original_url", "thumbnail_url", "source_page", "assinatura")})


def prefetch_browser_images(
    items: List[tuple],
    downloads_dir: str,
    site_cfg: Optional[Dict[str, Any]] = None,
    cache: Optional[Dict[str, Dict[str, Any]]] = None,
    on_result: Optional[callable] = None,
    lote_fn=None,
    evitar_extra: Optional[List[Any]] = None,
) -> Dict[int, Dict[str, Any]]:
    """Busca+baixa, EM LOTE, a imagem de todos os trechos que usam um dos
    buscadores de imagem por navegador (bing/brave/yandex/startpage).

    `items`: lista de (índice, VideoSegment). Em vez de cada trecho abrir o
    próprio Chromium (era o que acontecia antes — um navegador por trecho,
    vários ao mesmo tempo), usa `buscador_imagens_unificado.
    buscar_e_baixar_primeira`: UM navegador por buscador, que pesquisa
    todos os termos dele na mesma aba; pega a 1ª imagem de cada resultado e
    baixa; o que um buscador não achar/baixar vai pro próximo buscador.
    Se nenhum dos 4 achar o termo, tenta uma vez uma versão mais simples dele
    (a última palavra), de novo em todos.

    `cache`: dict termo -> resultado (o mesmo formato devolvido aqui),
        atualizado no lugar — a prévia preenche e a montagem reaproveita sem
        abrir navegador nenhum quando o arquivo ainda existe.
    `on_result(indice, resultado)`: chamado assim que cada trecho resolve.

    Devolve {índice: resultado}; `resultado["ok"]`/`["path"]`/`["engine"]`/
    `["erro"]` dizem o que aconteceu.
    """
    cfg = site_cfg or load_site_config()
    cache = cache if cache is not None else {}
    if lote_fn is None:
        from buscador_imagens_unificado import buscar_e_baixar_primeira as lote_fn  # noqa: N811

    def _norm(q: str) -> str:
        return " ".join((q or "").split())

    resultados: Dict[int, Dict[str, Any]] = {}
    por_termo: Dict[str, List[int]] = {}
    preferido: Dict[str, str] = {}
    alternativas: Dict[str, List[str]] = {}
    posicao_no_cache: Dict[str, int] = {}
    for i, seg in items:
        termo = _norm(seg.query)
        alternativas.setdefault(termo, list(getattr(seg, "alternativas", None) or []))
        hit = cache.get(termo)
        if hit and hit.get("ok") and hit.get("path") and os.path.exists(hit["path"]):
            k = posicao_no_cache.get(termo, 0)
            posicao_no_cache[termo] = k + 1
            res = _variante_da_imagem(hit, k)
            resultados[i] = res
            if on_result:
                on_result(i, res)
            continue
        por_termo.setdefault(termo, []).append(i)
        preferido.setdefault(termo, seg.provider)

    if not por_termo:
        return resultados

    # não repetir: o que outros trechos do vídeo já usam (endereço e assinatura
    # visual) fica de fora das buscas novas
    evitar: List[Any] = list(evitar_extra or [])  # p.ex. as imagens da timeline 1 (a 2 quer outras)
    for termo_c, hit in cache.items():
        if termo_c in por_termo or not isinstance(hit, dict) or not hit.get("ok"):
            continue
        for v in [hit] + list(hit.get("extras") or []):
            evitar += [x for x in (v.get("original_url"), v.get("thumbnail_url"), v.get("assinatura")) if x]

    headless = not cfg.get("browser_visible", False)
    paralelo = bool(cfg.get("buscadores_imagem_paralelo", True))
    # só os buscadores marcados no vídeo (cada um abre um navegador); sem a lista, os dos próprios trechos
    permitidos = cfg.get("provedores_do_job")
    no_trecho = {getattr(s, "provider", None) for _i, s in items}
    # sem a lista do job (vídeos antigos): os 4 de antes — o "google" (Modo IA, liga o app ia_google/ e é bem
    # mais lento) só entra quando foi marcado no vídeo ou quando o próprio trecho pede
    engines = [p for p in _BROWSER_IMAGE_SEARCH_PROVIDERS
               if (p in permitidos if permitidos is not None else (p not in _SO_SE_MARCADO or p in no_trecho))] \
        or [p for p in _BROWSER_IMAGE_SEARCH_PROVIDERS if p in no_trecho]

    def _entregar(termo: str, res: Dict[str, Any], inicio: int = 0) -> None:
        cache[termo] = res
        for k, idx in enumerate(por_termo.get(termo, [])):
            r = _variante_da_imagem(res, inicio + k)
            resultados[idx] = r
            if on_result:
                on_result(idx, r)

    # 1ª passada: termo original, buscador escolhido pela IA primeiro.
    falhas: Dict[str, Dict[str, Any]] = {}

    def _on_primeira(termo: str, res: Dict[str, Any]) -> None:
        if res.get("ok") and not res.get("repetida"):
            _entregar(termo, res)
        else:
            # repetida (só achou imagem que outro trecho já usa): antes de
            # aceitar, a 2ª passada tenta a busca reserva/alternativa da IA
            falhas[termo] = res

    proporcao = proporcao_dos_buscadores(cfg)
    lote_fn(
        [{"query": t, "engine": preferido[t], "quantidade": len(por_termo[t])} for t in por_termo],
        downloads_dir, engines=engines, headless=headless, paralelo=paralelo, on_result=_on_primeira,
        log=lambda m: print(m, flush=True), proporcao=proporcao, evitar=evitar,
    )

    # 2ª passada (só pros que nenhum buscador achou): termo simplificado.
    reserva = {t: _consulta_simplificada(t, alternativas.get(t)) for t in falhas}
    reserva = {t: r for t, r in reserva.items() if r and _norm(r) != t}
    if reserva:
        alvo_para_original: Dict[str, List[str]] = {}
        for original, simples in reserva.items():
            alvo_para_original.setdefault(_norm(simples), []).append(original)

        def _on_reserva(termo_simples: str, res: Dict[str, Any]) -> None:
            inicio = 0
            for original in alvo_para_original.get(termo_simples, []):
                if res.get("ok") and not (res.get("repetida") and falhas.get(original, {}).get("ok")):
                    _entregar(original, dict(res, query_usada=termo_simples, query=original), inicio)
                    inicio += len(por_termo.get(original, []))
                    falhas.pop(original, None)

        evitar_2 = evitar + [x for r in cache.values() if isinstance(r, dict) and r.get("ok")
                             for v in [r] + list(r.get("extras") or [])
                             for x in (v.get("original_url"), v.get("assinatura")) if x]
        lote_fn(
            [{"query": s, "engine": preferido[o], "quantidade": sum(len(por_termo.get(x, [])) for x in os_)}
             for s, os_ in alvo_para_original.items() for o in os_[:1]],
            downloads_dir, engines=engines, headless=headless, paralelo=paralelo, on_result=_on_reserva,
            proporcao=proporcao, evitar=evitar_2,
        )

    for termo, res in falhas.items():
        if res.get("ok"):  # repetida mesmo depois da reserva: melhor que trecho sem imagem
            print(f"[buscadores de imagem] “{termo}”: só achou imagem já usada em outro trecho — repetida", flush=True)
            _entregar(termo, res)
            continue
        # falha definitiva NÃO entra no cache (a próxima tentativa pesquisa de novo)
        for idx in por_termo.get(termo, []):
            resultados[idx] = res
            if on_result:
                on_result(idx, res)
    return resultados


def _download_segment_with_fallbacks(
    segment: VideoSegment,
    downloads_dir: str,
    client_factory: ClientFactory,
    provider_priority: List[str],
    orientation: Optional[str],
    match_duration: bool = True,
    magnific_only_free: bool = True,
    quality: Optional[str] = None,
    used_tracker: Optional["UsedClipsTracker"] = None,
) -> List[str]:
    """Tenta baixar o segmento no provedor que a IA escolheu; se isso
    falhar completamente (mesmo com os termos de busca alternativos),
    tenta os outros provedores em ordem de prioridade antes de desistir
    do segmento. Também trata o caso da API do Pexels falhar (chave
    inválida/rate limit): troca pro navegador automaticamente e tenta de
    novo, sem gastar uma tentativa de provedor "extra" por isso.

    used_tracker: compartilhado entre TODOS os segmentos do mesmo vídeo
        — evita que a mesma cena apareça repetida em trechos diferentes
        (ver `UsedClipsTracker` e `_search_and_download_filling_duration`).

    Devolve uma LISTA de um ou mais caminhos — mais de um quando o
    primeiro resultado veio mais curto que o segmento e a busca
    encontrou cenas diferentes pra completar o tempo (ver
    `_search_and_download_filling_duration`), em vez de depender de
    repetir uma única cena em loop.
    """
    providers_to_try = _sem_bloqueados([segment.provider] + _sem_flow_no_fallback(provider_priority, segment.provider))
    last_error: Optional[Exception] = None
    close_after = client_factory.cfg.get("browser_mode", "reuse_session") == "close_each_download"

    for provider in providers_to_try:
        provider_timeout = _provider_timeout_seconds(client_factory.cfg, provider)
        try:
            client = client_factory.get_client(provider)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue

        seg = replace(segment, provider=provider) if provider != segment.provider else segment

        try:
            paths = _run_with_timeout(
                lambda: _search_and_download_filling_duration(
                    seg, downloads_dir, client,
                    fallback_queries=_fallback_queries_for(seg), orientation=orientation,
                    magnific_only_free=magnific_only_free, quality=quality, used_tracker=used_tracker,
                ),
                provider_timeout,
            )
            return paths
        except (VideoAssemblyError, TimeoutError) as exc:
            # timeout conta igual a uma falha comum: desiste desse
            # provedor (mesmo que ele pudesse eventualmente responder) e
            # tenta o próximo — sem isso, um banco lento/travado podia
            # segurar o segmento inteiro por muito tempo antes de trocar.
            last_error = exc
            fallback_key = _API_FALLBACK_CONFIG_KEY.get(provider)
            if fallback_key and client_factory.is_api_client(client, provider) and client_factory.cfg.get(fallback_key, True):
                client_factory.force_browser_fallback(provider)
                browser_client = None
                try:
                    browser_client = client_factory.get_client(provider)
                    paths = _run_with_timeout(
                        lambda: _search_and_download_filling_duration(
                            seg, downloads_dir, browser_client,
                            fallback_queries=_fallback_queries_for(seg), orientation=orientation,
                            magnific_only_free=magnific_only_free, quality=quality, used_tracker=used_tracker,
                        ),
                        provider_timeout,
                    )
                    return paths
                except (VideoAssemblyError, TimeoutError) as exc2:
                    last_error = exc2
                finally:
                    if close_after and browser_client is not None:
                        client_factory.close_client(provider, browser_client)
            continue
        finally:
            if close_after:
                client_factory.close_client(provider, client)

    raise VideoAssemblyError(
        f"Nenhum provedor da lista de prioridade {providers_to_try} conseguiu entregar "
        f"um vídeo pra esse segmento ('{segment.query}'). Último erro: {last_error}"
    )


def _garantir_duracoes(paths: List[str], duracoes: List[float], pasta: str) -> List[str]:
    """Clipe mais curto que o esperado ganha o último quadro congelado até
    completar; mais longo (>0.5s) é aparado. Assim o xfade/concat nunca desloca."""
    def _um(k):
        p, alvo = paths[k], float(duracoes[k])
        try:
            real = _probe_duration(p)
        except Exception:  # noqa: BLE001
            return p
        if real < alvo - 0.08:
            out = os.path.join(pasta, f"_ajuste_{k:04d}_{uuid.uuid4().hex[:6]}.mp4")
            print(f"[montagem] pedaço {k + 1}: tinha {real:.2f}s de {alvo:.2f}s — completando com o último quadro", flush=True)
            _run_ffmpeg(["-i", p, "-vf", f"tpad=stop_mode=clone:stop_duration={alvo - real + 0.1:.3f},format=yuv420p", "-t", f"{alvo:.3f}",
                         "-r", str(TARGET_FPS), "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out], timeout=1800)
            return out
        if real > alvo + 0.5:
            out = os.path.join(pasta, f"_ajuste_{k:04d}_{uuid.uuid4().hex[:6]}.mp4")
            print(f"[montagem] pedaço {k + 1}: tinha {real:.2f}s de {alvo:.2f}s — aparando", flush=True)
            _run_ffmpeg(["-i", p, "-t", f"{alvo:.3f}", "-r", str(TARGET_FPS), "-an", "-c:v", "libx264", "-preset", "veryfast",
                         "-pix_fmt", "yuv420p", out], timeout=1800)
            return out
        return p
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        return list(ex.map(_um, range(len(paths))))


def _relatorio_montagem(work_dir, segments, brutos, com_gestos, duracoes_alvo, grupos, final_paths, final_duracoes, final_plano, extra=None) -> None:
    """montagem_relatorio.json na pasta do job: o que entrou em cada trecho
    (fonte, duração esperada × real, efeitos) — pra achar na hora qualquer
    diferença entre o que o editor mostrava e o vídeo exportado."""
    def _d(p):
        try:
            return round(_probe_duration(p), 3) if p else None
        except Exception:  # noqa: BLE001
            return None
    try:
        trechos = []
        for i, sg in enumerate(segments):
            ov = sg.override_source or {}
            trechos.append({"trecho": i + 1, "inicio": sg.start, "fim": sg.end, "banco": sg.provider, "busca": sg.query,
                            "midia": sg.media_type, "fonte": ov.get("value") if ov else "(busca automática)",
                            "efeito": getattr(sg, "efeito", None), "entrada": getattr(sg, "entrada", None), "saida": getattr(sg, "saida", None),
                            "cena": getattr(sg, "template", None), "duracao_esperada": round(duracoes_alvo[i], 3) if i < len(duracoes_alvo) else None,
                            "duracao_clipe": _d(brutos[i] if i < len(brutos) else None),
                            "duracao_com_entrada_saida": _d(com_gestos[i]) if i < len(com_gestos) and com_gestos[i] != brutos[i] else None,
                            "origem": (extra or {}).get("origens", {}).get(i),
                            "clipe_normalizado": os.path.abspath(brutos[i]) if i < len(brutos) and brutos[i] else None,
                            "corta_quadros_inicio": getattr(sg, "trim_start_frames", 0), "bordas": getattr(sg, "aspect_fill", None),
                            "campos_cena": getattr(sg, "template_campos", None) or None})
        pedacos = [{"pedaco": k + 1, "arquivo": os.path.basename(p), "esperado": round(d, 3), "real": _d(p),
                    "transicao_depois": list(final_plano[k]) if k < len(final_plano) else None}
                   for k, (p, d) in enumerate(zip(final_paths, final_duracoes))]
        with open(os.path.join(work_dir, "montagem_relatorio.json"), "w", encoding="utf-8") as f:
            ex = dict(extra or {})
            ex.pop("origens", None)
            json.dump({"trechos": trechos, "pedacos": pedacos, "duracao_narracao": segments[-1].end if segments else 0,
                       "grupos_cena": [{"de": a + 1, "ate": b + 1, "template": t} for (a, b, t) in grupos if t],
                       "config": ex}, f, ensure_ascii=False, indent=2, default=str)
    except Exception as exc:  # noqa: BLE001
        print(f"[montagem] não consegui escrever o relatório: {exc}", flush=True)


def _quadro(video: str, destino: str, ultimo: bool) -> Optional[str]:
    """Primeiro ou último quadro de um clipe, como .jpg (fundo dos gestos)."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error"] + (["-sseof", "-0.15"] if ultimo else []) + [
        "-i", video, "-frames:v", "1", "-q:v", "3", destino]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60)
    except Exception:  # noqa: BLE001
        return None
    return destino if os.path.exists(destino) and os.path.getsize(destino) > 0 else None


def _aplicar_gestos(segments, paths, duracoes, plano_transicoes, ultimo_do_grupo, W, H, clips_dir, work_dir, concurrency=3, em_cena=None):
    """Entrada/saída do DarkPlanner (slide, zoom, pop…), depois que TODOS os
    clipes existem: o clipe entra sobre o último quadro da cena anterior e sai
    sobre o primeiro quadro da seguinte. Antes o fundo era preto e, num corte
    seco, cada emenda piscava alguns quadros de preto. A saída só entra quando
    a emenda seguinte é corte seco (com transição ela brigaria com o xfade)."""
    import dp_visual as _dpv
    tarefas = []
    for i, seg in enumerate(segments):
        if em_cena and i in em_cena:
            # take de uma cena (template): a telinha não anima a entrada/saída do take
            # (ele entra na janela da cena) — no export a entrada punha o quadro da
            # cena ANTERIOR atrás do take, e ele aparecia dentro da janela da cena
            continue
        entrada = getattr(seg, "entrada", None)
        saida = getattr(seg, "saida", None)
        if ultimo_do_grupo.get(i, i) != i or (i < len(plano_transicoes) and plano_transicoes[i][0] != "none"):
            saida = None
        entrada = entrada if entrada and entrada != "none" else None
        saida = saida if saida and saida != "none" else None
        if (entrada or saida) and paths[i]:
            tarefas.append((i, entrada, saida))
    if not tarefas:
        return paths
    pasta_q = os.path.join(work_dir, "quadros_vizinhos")
    os.makedirs(pasta_q, exist_ok=True)
    novos = list(paths)

    def _um(i, entrada, saida):
        fundo_in = fundo_out = None
        if entrada and i > 0 and paths[i - 1]:
            fundo_in = _quadro(paths[i - 1], os.path.join(pasta_q, f"{i:04d}_antes.jpg"), ultimo=True)
        if saida and i + 1 < len(paths) and paths[i + 1]:
            fundo_out = _quadro(paths[i + 1], os.path.join(pasta_q, f"{i:04d}_depois.jpg"), ultimo=False)
        destino = os.path.join(clips_dir, f"segment_{i:04d}_gesto.mp4")
        try:
            if _dpv.pos_processar_clipe(paths[i], destino, duracoes[i] or segments[i].duration, W, H,
                                        os.path.join(work_dir, "dp_tex"), entrada=entrada, saida=saida,
                                        fundo_entrada=fundo_in, fundo_saida=fundo_out):
                return destino
        except Exception as exc:  # noqa: BLE001
            err = VideoAssemblyError(f"Trecho {i + 1}: entrada/saída do DarkPlanner falhou ({str(exc)[-300:]}) — tire a animação desse trecho")
            err.segment_index = i
            raise err from exc
        return paths[i]

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futuros = {ex.submit(_um, *t): t[0] for t in tarefas}
        for f in concurrent.futures.as_completed(futuros):
            novos[futuros[f]] = f.result()
    return novos


def assemble_video(
    segments: List[VideoSegment],
    audio_path: str,
    output_path: str,
    work_dir: str,
    get_client_fn=None,
    on_progress: Optional[callable] = None,
    site_cfg: Optional[Dict[str, Any]] = None,
    music_path: Optional[str] = None,
    music_volume: float = 0.18,
    perf_log: Optional["PerfLog"] = None,
    cancel_check: Optional[callable] = None,
    overlays: Optional[List[Dict[str, Any]]] = None,
    image_search_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    falas_por_trecho: Optional[List[str]] = None,
    palavras_por_trecho: Optional[List[Optional[List[Dict[str, Any]]]]] = None,
    destaques: Optional[List[Dict[str, Any]]] = None,
    palavras_narracao: Optional[List[Dict[str, Any]]] = None,
    graficos: Optional[List[Dict[str, Any]]] = None,
    editoriais: Optional[List[Dict[str, Any]]] = None,
    imagens_editorial: Optional[Dict[str, str]] = None,
    paleta: Optional[Dict[str, str]] = None,
    sfx: Optional[List[Dict[str, Any]]] = None,
    censura: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Executa o pipeline completo: busca+baixa cada segmento, normaliza,
    concatena, sincroniza com o áudio. Retorna o caminho do vídeo final.

    cancel_check: função sem argumentos que devolve True se a pessoa
        pediu pra cancelar o job — checada entre um segmento e outro no
        caminho "de verdade" (paralelo). Se True, cancela os segmentos
        ainda não iniciados e levanta `VideoAssemblyError` com uma
        mensagem clara de cancelamento (não é uma falha de verdade, mas
        precisa parar a montagem do mesmo jeito). Segmentos já em
        andamento no momento do cancelamento terminam normalmente (não
        dá pra matar uma thread no meio de um download/ffmpeg à força).

    overlays: lista opcional de overlays (imagem/vídeo sobreposto ao
        vídeo final, com posição/tamanho/janela de tempo PRÓPRIOS,
        independentes dos segmentos — pode ser um trecho específico ou
        atravessar o vídeo inteiro). Cada item já precisa vir com
        "resolved_path" preenchido (a resolução de onde vem a mídia —
        upload, link, ou busca — acontece ANTES de chamar
        `assemble_video`, não aqui). Aplicado depois do áudio já
        sincronizado, só no caminho "de verdade" (não no legado via
        `get_client_fn`). Ver `apply_overlays()`.

    get_client_fn: função (provider_str) -> cliente, injetável pra teste
        (ou pra qualquer uso que queira ignorar a configuração do site
        por completo e controlar os clientes manualmente). Quando
        fornecida, o fallback entre provedores por prioridade, o
        fallback automático da API do Pexels, e o filtro de orientação
        na busca NÃO se aplicam — é o caminho "simples", direto.

    site_cfg: quando `get_client_fn` NÃO é fornecido (o caso normal, real,
        do site), usa essa configuração (ou lê de `site_config.py` se
        não for passada) pra decidir orientação do vídeo, ordem de
        prioridade das fontes, visibilidade do navegador, sessão
        compartilhada, modo de abrir/fechar, e fallback da API do Pexels.

    music_path: caminho de um arquivo de áudio pra usar como trilha
        sonora de fundo (opcional). Se fornecido e existir, é mixado com
        a narração em volume bem mais baixo (`music_volume`, 0.0-1.0) —
        repetido em loop se for mais curto que a narração, cortado se
        for mais longo.

    on_progress: opcional, chamado como on_progress(etapa, i, total)
        pra você atualizar uma barra de progresso no site.

    image_search_cache: opcional, dict termo -> resultado dos buscadores
        de imagem por navegador (ver `prefetch_browser_images`). Os trechos
        com bing/brave/yandex/startpage são resolvidos TODOS JUNTOS antes do
        resto (um navegador por buscador, não um por trecho); o que já está
        no cache (baixado na etapa de prévia) nem abre navegador.
    """
    if not segments:
        raise VideoAssemblyError("Lista de segmentos vazia — nada pra montar.")

    os.makedirs(work_dir, exist_ok=True)
    downloads_dir = os.path.join(work_dir, "downloads")
    clips_dir = os.path.join(work_dir, "clips")
    os.makedirs(downloads_dir, exist_ok=True)
    os.makedirs(clips_dir, exist_ok=True)

    normalized_paths = []
    total = len(segments)

    if get_client_fn is not None:
        # Caminho simples/legado — usado por testes e por quem quiser
        # controlar os clientes na mão. Sem fallback entre provedores,
        # sem filtro de orientação, sem fallback de API.
        target_width, target_height = TARGET_WIDTH, TARGET_HEIGHT
        legacy_cfg = site_cfg or load_site_config()
        legacy_transition_type = legacy_cfg.get("transition_type", "none")
        legacy_transition_duration = legacy_cfg.get("transition_duration", 0.6)
        clients: dict = {}
        try:
            for i, segment in enumerate(segments):
                if on_progress:
                    on_progress("buscando", i, total)

                ja_resolvido = None
                if (segment.override_source or {}).get("da_previa"):
                    try:  # clipe da prévia: se o link falhar, volta pra busca normal
                        ja_resolvido = _resolve_override_source(
                            segment.override_source, downloads_dir,
                            lambda p: _get_or_create_client(p, clients, get_client_fn),
                        )
                    except Exception:  # noqa: BLE001
                        segment = replace(segment, override_source=None)
                if segment.override_source:
                    raw_path, kind = ja_resolvido or _resolve_override_source(
                        segment.override_source, downloads_dir,
                        lambda p: _get_or_create_client(p, clients, get_client_fn),
                    )
                elif getattr(segment, "media_type", "video") == "image":
                    client = _get_or_create_client(segment.provider, clients, get_client_fn)
                    raw_path = _search_and_download_photo(
                        segment, downloads_dir, client, fallback_queries=_fallback_queries_for(segment)
                    )
                    kind = "image"
                else:
                    client = _get_or_create_client(segment.provider, clients, get_client_fn)
                    raw_path = _search_and_download_one(
                        segment, downloads_dir, client, fallback_queries=_fallback_queries_for(segment)
                    )
                    kind = "video"

                if on_progress:
                    on_progress("normalizando", i, total)
                normalized_path = os.path.join(clips_dir, f"segment_{i:04d}.mp4")
                if kind == "image":
                    override = segment.override_source or {}
                    _render_image_with_ken_burns(
                        raw_path, segment.duration, normalized_path, target_width, target_height,
                        zoom_direction=override.get("zoom_direction", segment.zoom_direction),
                        focus_x=override.get("focus_x", segment.focus_x), focus_y=override.get("focus_y", segment.focus_y),
                        on_screen_text=segment.on_screen_text,
                        fade_in=getattr(segment, "image_fade_in", False),
                        fade_out=getattr(segment, "image_fade_out", False),
                        fade_duration=getattr(segment, "image_fade_duration", 0.5),
                        blur_sigma=override.get("blur_sigma", segment.blur_sigma),
                        aspect_fill=getattr(segment, "aspect_fill", None),
                    )
                else:
                    _normalize_clip(raw_path, segment.duration, normalized_path, target_width, target_height, on_screen_text=segment.on_screen_text, aspect_fill=segment.aspect_fill, trim_start_frames=getattr(segment, "trim_start_frames", 0), blur_sigma=segment.blur_sigma)
                normalized_paths.append(normalized_path)

            if on_progress:
                on_progress("concatenando", total, total)
            concat_path = os.path.join(work_dir, "_concat_video_only.mp4")
            _concat_clips_with_transitions(
                normalized_paths, [s.duration for s in segments], concat_path, work_dir,
                transition_type=legacy_transition_type, transition_duration=legacy_transition_duration,
            )

            if on_progress:
                on_progress("sincronizando_audio", total, total)
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            if music_path and os.path.exists(music_path):
                _mux_audio_with_music(concat_path, audio_path, music_path, output_path, music_volume)
            else:
                _mux_audio(concat_path, audio_path, output_path)

            return output_path
        finally:
            for client in clients.values():
                try:
                    client.session.close()
                except Exception:  # noqa: BLE001
                    pass

    # Caminho "de verdade" do site — respeita a configuração completa.
    cfg = site_cfg or load_site_config()
    orientation = cfg.get("orientation", "16:9")
    target_width, target_height = resolution_for_orientation(orientation, cfg.get("export_quality", "1080p"))
    # search_orientation controla o filtro de busca dos CLIPES, separado
    # da orientação de EXPORTAÇÃO acima — "mixed" busca sem filtro (pode
    # trazer paisagem e retrato misturados entre trechos), "match_export"
    # (padrão) usa a mesma orientação da exportação, como sempre foi.
    search_orientation_setting = cfg.get("search_orientation", "match_export")
    transition_type = cfg.get("transition_type", "none")
    transition_duration = cfg.get("transition_duration", 0.6)
    if search_orientation_setting == "mixed":
        search_orientation = None
    elif search_orientation_setting == "match_export":
        search_orientation = orientation
    else:
        search_orientation = search_orientation_setting
    provider_priority = cfg.get("provider_priority") or ["pexels", "pixabay", "magnific", "mixkit", "vistacreate", "animepexels"]
    trim_position = cfg.get("clip_trim_position", "start")
    magnific_only_free = cfg.get("magnific_only_free", True)
    concurrency = max(1, min(cfg.get("assembly_fetch_concurrency", 3), total))
    # UMA instância compartilhada entre TODOS os segmentos deste vídeo —
    # evita que a mesma cena/foto apareça repetida em trechos diferentes
    # do vídeo final (não só dentro de um único segmento). Thread-safe
    # de propósito, já que os segmentos são processados em paralelo.
    # Controlável via config ("evitar_repeticao_clipes", ligado por
    # padrão) -- desligar volta ao comportamento de sempre escolher
    # livremente o melhor resultado da busca, mesmo que ele já tenha
    # aparecido em outro trecho.
    used_clips_tracker = UsedClipsTracker() if cfg.get("evitar_repeticao_clipes", True) else None
    if used_clips_tracker is not None:
        # clipes fixados da prévia (app._fixar_midias_da_previa) já estão
        # "usados": a busca dos outros trechos não pode trazer o mesmo de novo
        for _s in segments:
            _ov = getattr(_s, "override_source", None) or {}
            if _ov.get("da_previa"):
                _m = re.search(r"(\d+)/?(?:[?#].*)?$", str(_ov.get("value") or ""))
                if _m:
                    used_clips_tracker.try_claim(_m.group(1), _ov.get("provider"))
                    used_clips_tracker.try_claim(int(_m.group(1)), _ov.get("provider"))

    # transição de cada emenda + quanto cada clipe precisa durar a mais pra
    # que a sobreposição não encurte o vídeo (e não corte a narração no fim)
    # paleta de cores do projeto (dp_cores): cenas, destaques, legendas e transições de luz
    import dp_cores
    paleta = paleta or cfg.get("paleta")
    _PALETA_TRANSICOES["atual"] = paleta
    paleta_textos = dp_cores.normalizar(paleta) if dp_cores.vale_para(paleta, "textos") else None
    plano_transicoes = planejar_transicoes(segments, transition_type, transition_duration)
    # Cenas/takes (DarkPlanner): um template de N slots junta N trechos
    # seguidos num clipe só — as emendas DENTRO da cena não têm transição.
    import cenas_dp
    grupos = cenas_dp.planejar_grupos([getattr(s, "template", None) for s in segments])
    ultimo_do_grupo: Dict[int, int] = {}
    for (g_ini, g_fim, g_tid) in grupos:
        for k in range(g_ini, g_fim + 1):
            ultimo_do_grupo[k] = g_fim
        if g_tid:
            for k in range(g_ini, g_fim):
                plano_transicoes[k] = ("none", 0.0)
    extras = [d for _t, d in plano_transicoes] + [0.0]

    # Trechos com buscador de imagem por navegador: resolvidos em LOTE antes
    # do processamento paralelo (1 navegador por buscador, todos os termos
    # na mesma aba) — sem isso, cada trecho abriria o próprio Chromium.
    browser_image_items = [
        (i, s) for i, s in enumerate(segments)
        if not s.override_source and getattr(s, "media_type", "video") == "image"
        and s.provider in _BROWSER_IMAGE_SEARCH_PROVIDERS
    ]
    prefetched_images: Dict[int, Dict[str, Any]] = {}
    if browser_image_items:
        if on_progress:
            on_progress("buscando_imagens", 0, len(browser_image_items))
        with (perf_log.timed("montagem:buscadores_imagem_lote", trechos=len(browser_image_items)) if perf_log else nullcontext()):
            prefetched_images = prefetch_browser_images(
                browser_image_items, downloads_dir, cfg, cache=image_search_cache,
            )

    origens: Dict[int, Dict[str, Any]] = {}
    flow_trocas: Dict[int, str] = {}  # v84_110: trecho do Flow que virou foto / pesquisa (vai no "origens")
    # ⬇ mídias que o Estúdio já baixou em segundo plano (app._prebaixar_iniciar)
    prebaixados_dir = cfg.get("prebaixados_dir") or os.path.join(work_dir, "prebaixados")
    # ♻ clipes já prontos (baixados + cortados + com efeito) de uma montagem anterior:
    # se a montagem falhar num trecho e você montar de novo, os trechos que não
    # mudaram saem daqui na hora — só o trecho que mudou é refeito.
    prontos_dir = os.path.join(work_dir, "clips_prontos")
    reaproveitar_prontos = bool(cfg.get("reaproveitar_clipes_prontos", True))
    import dataclasses as _dc
    import hashlib as _hl
    try:
        import qualidade_export as _qe
        _estado_qe = dict(_qe._estado)
    except Exception:  # noqa: BLE001
        _estado_qe = {}
    _base_assinatura = {
        "v": CLIPES_PRONTOS_VERSAO, "w": target_width, "h": target_height, "trim": trim_position,
        "ori": search_orientation, "prio": list(provider_priority or []), "mof": magnific_only_free,
        "completar": cfg.get("completar_trecho_curto", "repetir"), "paleta": paleta, "qe": _estado_qe,
        "rep": cfg.get("evitar_repeticao_clipes", True), "cartao": cfg.get("cartao_fundo"),
    }
    # 🪧 fundo dos cartões: preparado UMA vez (o clipe de fundo é baixado uma vez só) e dividido entre os trechos
    _fundo_cartao_estado: Dict[str, Any] = {}
    _fundo_cartao_trava = threading.Lock()

    def _fundo_cartao(fabrica) -> Dict[str, Any]:
        with _fundo_cartao_trava:
            if "f" not in _fundo_cartao_estado:
                pasta_fc = os.path.join(work_dir, "fundo_cartao")

                def _baixar(q: str) -> Optional[str]:
                    for prov in [p for p in provider_priority if p not in BIBLIOTECAS_LOCAIS][:3]:
                        try:
                            seg_fc = VideoSegment(start=0.0, end=12.0, provider=prov, query=q, media_type="video")
                            return _run_with_timeout(lambda: _search_and_download_one(seg_fc, pasta_fc, fabrica.get_client(prov),
                                                                                       orientation=orientation),
                                                     max(30, cfg.get("provider_attempt_timeout_seconds", 25) * 2))
                        except Exception as exc:  # noqa: BLE001
                            print(f"[montagem] fundo dos cartões: {prov} não trouxe '{q}' ({exc})", flush=True)
                    return None
                _fundo_cartao_estado["f"] = preparar_fundo_cartao(cfg.get("cartao_fundo"), target_width, target_height, pasta_fc, _baixar)
            return _fundo_cartao_estado["f"]

    def _arquivo_id(valor: Any) -> Any:
        # arquivo do PC/gerado: o mesmo caminho com outro conteúdo não pode reaproveitar
        try:
            if isinstance(valor, str) and valor and os.path.isfile(valor):
                st = os.stat(valor)
                return [valor, st.st_size, int(st.st_mtime)]
        except OSError:
            pass
        return valor

    def _assinatura_clipe(i: int, segment: VideoSegment, alvo: float) -> str:
        campos = {f.name: getattr(segment, f.name, None) for f in _dc.fields(segment)}
        ov = dict(campos.get("override_source") or {})
        if ov.get("source") == "local_file":
            ov["value"] = _arquivo_id(ov.get("value"))
        campos["override_source"] = ov
        bruto = json.dumps({"seg": campos, "alvo": round(float(alvo), 3), "base": _base_assinatura},
                           sort_keys=True, default=str, ensure_ascii=False)
        return _hl.sha1(bruto.encode("utf-8")).hexdigest()[:24]

    assinaturas: Dict[int, str] = {}

    def _pegar_pronto(i: int, assin: str) -> Optional[str]:
        if not reaproveitar_prontos:
            return None
        arq = os.path.join(prontos_dir, assin + ".mp4")
        try:
            if os.path.getsize(arq) <= 0:
                return None
            with open(os.path.join(prontos_dir, assin + ".json"), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            return None
        destino = os.path.join(clips_dir, f"segment_{i:04d}_pronto.mp4")
        shutil.copyfile(arq, destino)
        duracoes_alvo[i] = float(meta.get("alvo") or 0.0)
        origens[i] = dict(meta.get("origem") or {}, reaproveitado_da_montagem_anterior=True)
        return destino

    def _guardar_pronto(i: int, assin: str, caminho: str, alvo: float) -> None:
        if not reaproveitar_prontos:
            return
        try:
            os.makedirs(prontos_dir, exist_ok=True)
            tmp = os.path.join(prontos_dir, assin + ".tmp.mp4")
            shutil.copyfile(caminho, tmp)
            os.replace(tmp, os.path.join(prontos_dir, assin + ".mp4"))
            with open(os.path.join(prontos_dir, assin + ".json"), "w", encoding="utf-8") as f:
                json.dump({"alvo": alvo, "origem": origens.get(i) or {}, "trecho": i + 1}, f, ensure_ascii=False, default=str)
        except OSError:
            pass  # sem espaço etc.: só não reaproveita da próxima vez

    def _process_one(i: int, segment: VideoSegment) -> str:
        """Busca/baixa e normaliza UM segmento por completo, com sua
        própria `ClientFactory` (sessão de navegador independente — não
        é seguro compartilhar uma sessão Selenium entre threads
        concorrentes). Devolve o caminho do clipe já normalizado, pronto
        pra concatenar.
        """
        worker_factory = ClientFactory(cfg)
        pl = perf_log.timed if perf_log else (lambda *a, **k: nullcontext())
        try:
            _fim = ultimo_do_grupo.get(i, i)
            _alvo = segments[_fim].end - segment.start + extras[_fim]
            assin = assinaturas[i] = _assinatura_clipe(i, segment, _alvo)
            pronto = _pegar_pronto(i, assin)
            if pronto:
                return pronto
            with pl(f"montagem:segmento_{i}:busca_download", provider=segment.provider, query=segment.query):
                ja_resolvido = None
                erro_previa = None
                ov_original = dict(segment.override_source or {})
                veio_prebaixado = bool(prebaixado(ov_original, prebaixados_dir))
                if (segment.override_source or {}).get("da_previa"):
                    # clipe da prévia (não foi a pessoa que escolheu): se o link
                    # não resolver/baixar, o trecho volta pra busca normal em vez de falhar
                    try:
                        ja_resolvido = resolver_override_cacheado(segment.override_source, downloads_dir, worker_factory.get_client, cache_dir=prebaixados_dir)
                    except Exception as exc:  # noqa: BLE001
                        erro_previa = str(exc)[:300]
                        print(f"[montagem] trecho {i + 1}: o clipe da prévia não baixou ({exc}); buscando de novo", flush=True)
                        segment = replace(segment, override_source=None)
                if segment.override_source:
                    # override é uma escolha DELIBERADA (upload, link
                    # direto, ou fixação de um resultado específico) —
                    # esse clipe SEMPRE entra primeiro e nunca é
                    # descartado. Mas se ele vier mais curto que o
                    # trecho, em vez de deixar o clipe sozinho pro
                    # loop/pausa no último frame cobrir o resto,
                    # tentamos complementar com uma busca de verdade
                    # (mesmo espírito de _search_and_download_filling_
                    # duration) — só volta a ser "um clipe só" se essa
                    # busca de complemento falhar ou não achar nada.
                    raw_path, kind = ja_resolvido or resolver_override_cacheado(
                        segment.override_source, downloads_dir, worker_factory.get_client, cache_dir=prebaixados_dir,
                    )
                    raw_paths = [raw_path]
                    extras_escolhidos = list(getattr(segment, "clipes_extra", None) or []) if kind == "video" else []
                    for c_extra in extras_escolhidos:
                        # aba ⏱ Clipes curtos: o 2º/3º resultado escolhido completa o trecho, na ordem
                        try:
                            p_extra, k_extra = resolver_override_cacheado(dict(c_extra, kind="video"), downloads_dir, worker_factory.get_client, cache_dir=prebaixados_dir)
                        except Exception as exc:  # noqa: BLE001
                            print(f"[montagem] trecho {i + 1}: clipe extra {c_extra.get('value')} não baixou ({exc})", flush=True)
                            continue
                        if k_extra == "video":
                            raw_paths.append(p_extra)
                    if kind == "video" and not extras_escolhidos and getattr(segment, "curto", None) != "loop":
                        try:
                            override_duration = _probe_duration(raw_path)
                        except Exception:  # noqa: BLE001
                            override_duration = None
                        # Clipe da PRÉVIA (escolha automática que o Estúdio mostrou)
                        # mais curto que o trecho: o Estúdio mostra ele repetindo
                        # (loop) — a montagem faz igual, pro vídeo bater com o que você
                        # editou (antes entrava uma 2ª cena da busca que você nunca viu).
                        # `completar_trecho_curto: "outra_cena"` volta ao jeito antigo.
                        # Clipe escolhido À MÃO continua sendo completado com outra cena.
                        da_previa = bool((segment.override_source or {}).get("da_previa"))
                        if (override_duration is not None and override_duration < segment.duration - 0.05
                                and (not da_previa or cfg.get("completar_trecho_curto", "repetir") == "outra_cena")):
                            try:
                                supplement_client = worker_factory.get_client(segment.provider)
                                extra_paths = _run_with_timeout(
                                    lambda: _search_and_download_filling_duration(
                                        segment, downloads_dir, supplement_client,
                                        fallback_queries=_fallback_queries_for(segment),
                                        orientation=orientation, magnific_only_free=magnific_only_free,
                                        used_tracker=used_clips_tracker, initial_duration=override_duration,
                                    ),
                                    cfg.get("provider_attempt_timeout_seconds", 25),
                                )
                                raw_paths.extend(extra_paths)
                            except Exception:  # noqa: BLE001
                                # sem complemento -> segue só com o clipe manual
                                # (loop cobre o resto, como era antes dessa mudança).
                                pass
                elif i in prefetched_images:
                    res = prefetched_images[i]
                    if not res.get("ok") or not res.get("path"):
                        raise VideoAssemblyError(
                            f"Nenhum buscador de imagem (bing/brave/yandex/startpage/google) conseguiu achar e baixar "
                            f"uma imagem pra '{segment.query}' — {res.get('erro') or 'sem detalhes'}. Troque o "
                            "termo no editor, ou envie um arquivo/link pra esse trecho."
                        )
                    raw_paths = [res["path"]]
                    kind = "image"
                elif getattr(segment, "media_type", "video") == "image" and segment.provider == "flow":
                    # 🖼 foto do Flow. v84_110: sem conta com crédito de imagem (ou o Flow falhou) → PESQUISA a cena
                    if flow_tem_conta("imagem", cfg) is False and not flow_ja_gerado(segment.query, cfg, "imagem"):
                        kind = ""
                        if cfg.get("runpod_reserva_flow"):  # 🟣 v84_116: o Runpod gera antes de ir pra pesquisa
                            try:
                                raw_paths, kind, oque = gerar_no_runpod(segment, downloads_dir, worker_factory, cfg,
                                                                        search_orientation, used_tracker=used_clips_tracker)
                                flow_trocas[i] = f"{oque} (contas do Flow esgotadas)"
                            except Exception:  # noqa: BLE001
                                kind = ""
                        if not kind:
                            raw_paths, kind = _pesquisa_no_lugar_do_flow(
                                segment, downloads_dir, worker_factory, cfg, provider_priority, search_orientation,
                                used_tracker=used_clips_tracker, motivo="todas as contas sem crédito de imagem")
                            flow_trocas[i] = "pesquisa (contas do Flow esgotadas)"
                    else:
                        try:
                            raw_paths = [_download_image_segment_with_fallbacks(segment, downloads_dir, worker_factory, used_tracker=used_clips_tracker)]
                            kind = "image"
                        except Exception as exc_flow:  # noqa: BLE001
                            raw_paths, kind = _pesquisa_no_lugar_do_flow(
                                segment, downloads_dir, worker_factory, cfg, provider_priority, search_orientation,
                                used_tracker=used_clips_tracker, motivo=f"a foto não saiu ({str(exc_flow)[:200]})")
                            flow_trocas[i] = "pesquisa (a foto do Flow não saiu)"
                elif getattr(segment, "media_type", "video") == "image" and segment.provider != "runpod":
                    raw_paths = [_download_image_segment_with_fallbacks(segment, downloads_dir, worker_factory, used_tracker=used_clips_tracker)]
                    kind = "image"
                elif segment.provider == "flow":
                    # vídeo gerado no Flow (Veo). Se não sair (limite, recusa,
                    # tela mudou), gera a IMAGEM da mesma cena no Flow em vez de
                    # cair num banco de estoque com uma descrição em português.
                    # v84_110: sem conta com crédito de VÍDEO nem tenta (vai direto pra foto); sem crédito de
                    # IMAGEM também (ou a foto não sai) → PESQUISA a cena nos bancos/buscadores.
                    tem_video, tem_foto = flow_tem_conta("video", cfg), flow_tem_conta("imagem", cfg)
                    # v84_112: o que JÁ foi gerado (prévia, edição) entra sem gerar de novo, com ou sem crédito
                    if flow_ja_gerado(segment.query, cfg, "video"):
                        tem_video = True
                    q_foto = segment.query if flow_ja_gerado(segment.query, cfg, "imagem") else None
                    exc_flow: Any = "todas as contas sem crédito de vídeo"
                    raw_paths, kind = [], ""
                    if tem_video is not False:
                        try:
                            raw_paths = _download_segment_with_fallbacks(
                                segment, downloads_dir, worker_factory, [], search_orientation,
                                magnific_only_free=magnific_only_free, used_tracker=used_clips_tracker,
                            )
                            kind = "video"
                        except VideoAssemblyError as exc_v:
                            exc_flow = exc_v
                            tem_foto = flow_tem_conta("imagem", cfg)
                    if not kind and q_foto is None:
                        q_foto = prompt_de_foto(segment.query)
                        if flow_ja_gerado(q_foto, cfg, "imagem"):
                            tem_foto = True
                    elif not kind:
                        tem_foto = True
                    if not kind and tem_foto is not False:
                        try:
                            # 🔁 o prompt de VÍDEO vira prompt de FOTO e gera nas contas que ainda têm crédito de imagem
                            raw_paths = [_download_image_segment_with_fallbacks(
                                replace(segment, media_type="image", query=q_foto), downloads_dir,
                                worker_factory, used_tracker=used_clips_tracker)]
                            kind = "image"
                            flow_trocas[i] = f"foto no lugar do vídeo ({str(exc_flow)[:120]})"
                        except Exception as exc_img:  # noqa: BLE001
                            exc_flow = f"o vídeo não saiu ({exc_flow}) e a imagem reserva também não ({exc_img})"
                    if not kind and cfg.get("runpod_reserva_flow"):  # 🟣 v84_116: o Runpod gera antes de ir pra pesquisa
                        try:
                            raw_paths, kind, oque = gerar_no_runpod(segment, downloads_dir, worker_factory, cfg, search_orientation,
                                                                    video=True, used_tracker=used_clips_tracker)
                            flow_trocas[i] = f"{oque} (o Flow não gerou)"
                        except Exception:  # noqa: BLE001
                            kind = ""
                    if not kind:
                        raw_paths, kind = _pesquisa_no_lugar_do_flow(
                            segment, downloads_dir, worker_factory, cfg, provider_priority, search_orientation, video=True,
                            used_tracker=used_clips_tracker,
                            motivo=("todas as contas sem crédito (vídeo e imagem)" if tem_foto is False else str(exc_flow))[:300])
                        flow_trocas[i] = "pesquisa (contas do Flow esgotadas)" if tem_foto is False else "pesquisa (o Flow não gerou)"
                elif segment.provider == "runpod":
                    # 🟣 v84_116: gerado no Runpod (vídeo → foto); sem chave/saldo ou recusa → PESQUISA a cena
                    try:
                        raw_paths, kind, oque = gerar_no_runpod(
                            segment, downloads_dir, worker_factory, cfg, search_orientation,
                            video=getattr(segment, "media_type", "video") != "image", used_tracker=used_clips_tracker)
                        if oque.startswith("foto do Runpod no lugar"):
                            flow_trocas[i] = oque
                    except Exception as exc_rp:  # noqa: BLE001
                        raw_paths, kind = _pesquisa_no_lugar_do_flow(
                            segment, downloads_dir, worker_factory, cfg, provider_priority, search_orientation,
                            video=getattr(segment, "media_type", "video") != "image", used_tracker=used_clips_tracker,
                            motivo=f"Runpod: {str(exc_rp)[:200]}")
                        flow_trocas[i] = "pesquisa (o Runpod não gerou)"
                else:
                    raw_paths = _download_segment_with_fallbacks(
                        segment, downloads_dir, worker_factory, provider_priority, search_orientation,
                        magnific_only_free=magnific_only_free, used_tracker=used_clips_tracker,
                    )
                    kind = "video"

            _ov_now = segment.override_source or {}
            if _ov_now.get("da_previa"):
                _modo = "clipe_da_previa"
            elif ov_original.get("da_previa"):
                _modo = "previa_nao_baixou_busca_nova"
            elif _ov_now:
                _modo = "escolhido_a_mao:" + str(_ov_now.get("source") or "?")
            elif i in prefetched_images:
                _modo = "buscador_de_imagem"
            else:
                _modo = "busca_nova" if kind == "video" else "busca_nova_" + kind
            origens[i] = {"modo": _modo, "kind": kind, "arquivos": [os.path.abspath(r) for r in raw_paths],
                          "link": _ov_now.get("value") or ov_original.get("value"), "erro_previa": erro_previa,
                          "completado_com_outra_cena": kind == "video" and len(raw_paths) > 1,
                          "banco": segment.provider, "busca": segment.query, "prebaixado": veio_prebaixado,
                          **({"flow_troca": flow_trocas[i]} if i in flow_trocas else {})}
            normalized_path = os.path.join(clips_dir, f"segment_{i:04d}.mp4")
            # + rabo da transição pro próximo trecho; dentro de uma cena com
            # vários takes, o take fica na tela até o fim da cena
            fim_k = ultimo_do_grupo.get(i, i)
            alvo_duracao = segments[fim_k].end - segment.start + extras[fim_k]
            with pl(f"montagem:segmento_{i}:normalizar", kind=kind, num_clipes=len(raw_paths)):
                if kind == "image":
                    override = segment.override_source or {}
                    _zoom = override.get("zoom_direction", segment.zoom_direction)
                    if _dp_visual.efeito_e_movimento(getattr(segment, "efeito", None)):
                        _zoom = _dp_visual.EFEITO_PARA_ZOOM[segment.efeito]  # efeito de câmera do DarkPlanner manda
                    if getattr(segment, "aspect_fill", None) == "cartao" and proporcao_diferente(raw_paths[0], target_width, target_height):
                        _render_imagem_cartao(raw_paths[0], alvo_duracao, normalized_path, target_width, target_height,
                                              _fundo_cartao(worker_factory), t0=segment.start, on_screen_text=segment.on_screen_text,
                                              on_screen_text_style=segment.on_screen_text_style)
                    else:
                        _render_image_with_ken_burns(
                            raw_paths[0], alvo_duracao, normalized_path, target_width, target_height,
                            zoom_direction=_zoom,
                            focus_x=override.get("focus_x", segment.focus_x), focus_y=override.get("focus_y", segment.focus_y),
                            on_screen_text=segment.on_screen_text, on_screen_text_style=segment.on_screen_text_style,
                            fade_in=getattr(segment, "image_fade_in", False),
                            fade_out=getattr(segment, "image_fade_out", False),
                            fade_duration=getattr(segment, "image_fade_duration", 0.5),
                            blur_sigma=override.get("blur_sigma", segment.blur_sigma),
                            aspect_fill=getattr(segment, "aspect_fill", None),
                        )
                elif len(raw_paths) > 1:
                    # busca automática trouxe mais de uma cena diferente
                    # pra completar a duração do segmento (em vez de
                    # repetir uma única cena em loop) — concatena todas.
                    _normalize_multi_clip(
                        raw_paths, alvo_duracao, normalized_path, clips_dir,
                        target_width, target_height, trim_position, segment.on_screen_text, segment.on_screen_text_style, segment.aspect_fill, getattr(segment, "trim_start_frames", 0),
                    )
                else:
                    _normalize_clip(raw_paths[0], alvo_duracao, normalized_path, target_width, target_height, trim_position, segment.on_screen_text, segment.on_screen_text_style, segment.aspect_fill, getattr(segment, "trim_start_frames", 0), blur_sigma=segment.blur_sigma)
            # atmosfera + entrada/saída (catálogo DarkPlanner). A saída só entra
            # quando a emenda seguinte é corte seco (com transição ela brigaria
            # com o xfade) e nunca dentro de uma cena com vários takes.
            # (entrada/saída ficam pra uma 2ª passada, quando os clipes vizinhos
            # já existem — o gesto acontece sobre o quadro da cena ao lado,
            # não sobre preto; ver _aplicar_gestos abaixo)
            efeito = getattr(segment, "efeito", None)
            duracoes_alvo[i] = alvo_duracao
            if efeito and efeito != "none" and not _dp_visual.efeito_e_movimento(efeito):
                pos_path = os.path.join(clips_dir, f"segment_{i:04d}_dp.mp4")
                with pl(f"montagem:segmento_{i}:efeitos_dp", efeito=efeito):
                    try:
                        if _dp_visual.pos_processar_clipe(normalized_path, pos_path, alvo_duracao, target_width, target_height,
                                                          os.path.join(work_dir, "dp_tex"), efeito=efeito):
                            normalized_path = pos_path
                    except Exception as exc:  # noqa: BLE001
                        raise VideoAssemblyError(f"efeito/entrada/saída do DarkPlanner falhou ({str(exc)[-300:]}) — tire o efeito desse trecho") from exc
            _guardar_pronto(i, assin, normalized_path, alvo_duracao)
            return normalized_path
        except VideoAssemblyError as exc:
            # anota QUAL trecho falhou antes de propagar — sem isso, o
            # erro final só diz "algo deu errado numa busca", sem indicar
            # que trecho especificamente precisa de outra fonte.
            wrapped = VideoAssemblyError(f"Trecho {i + 1}: {exc}")
            wrapped.segment_index = i
            raise wrapped from exc
        except Exception as exc:  # noqa: BLE001
            wrapped = VideoAssemblyError(f"Trecho {i + 1}: erro inesperado — {exc}")
            wrapped.segment_index = i
            raise wrapped from exc
        finally:
            worker_factory.close_all()

    # busca/baixa/normaliza vários segmentos em paralelo
    # (`assembly_fetch_concurrency` nas configurações) — antes disso, um
    # segmento de cada vez, o que deixava a montagem lenta pra qualquer
    # trecho que precisasse buscar de novo (termo editado, ou a prévia
    # não foi reaproveitada). A ORDEM final é sempre preservada pelo
    # índice, mesmo que a ordem de conclusão seja diferente.
    results_by_index: List[Optional[str]] = [None] * total
    duracoes_alvo: List[float] = [0.0] * total
    completed = 0
    first_error: Optional[BaseException] = None
    cancelled = False
    falhas: List[tuple] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_index = {executor.submit(_process_one, i, seg): i for i, seg in enumerate(segments)}
        for future in concurrent.futures.as_completed(future_to_index):
            if cancel_check and cancel_check():
                cancelled = True
                # cancela os segmentos que ainda não começaram (os já em
                # andamento continuam até terminar — não dá pra matar
                # uma thread no meio de um download/ffmpeg à força).
                for f in future_to_index:
                    f.cancel()
                break
            i = future_to_index[future]
            try:
                results_by_index[i] = future.result()
            except concurrent.futures.CancelledError:
                continue
            except Exception as exc:  # noqa: BLE001
                falhas.append((i, exc))
                if first_error is None:
                    first_error = exc
                continue
            completed += 1
            if on_progress:
                on_progress("processando", completed, total)

    # limpa clipes prontos de versões antigas dos trechos (só fica o que vale agora)
    if reaproveitar_prontos and assinaturas and not cancelled:
        try:
            vale = set(assinaturas.values())
            for nome in os.listdir(prontos_dir) if os.path.isdir(prontos_dir) else []:
                if nome.split(".")[0] not in vale:
                    os.remove(os.path.join(prontos_dir, nome))
        except OSError:
            pass

    if cancelled:
        raise VideoAssemblyError("Montagem cancelada pelo usuário.")

    if first_error is not None:
        falhas.sort(key=lambda t: t[0])
        i0, exc0 = falhas[0]
        err = exc0 if isinstance(exc0, VideoAssemblyError) else VideoAssemblyError(f"Falha ao processar um segmento: {exc0}")
        msg = str(err)
        if len(falhas) > 1:
            msg += "\n\nTambém falharam: " + "; ".join(f"{e}" for _k, e in falhas[1:6]) + (" …" if len(falhas) > 6 else "")
        prontos = total - len(falhas)
        if reaproveitar_prontos and prontos > 0:
            msg += (f"\n\n♻ Os outros {prontos} trechos já ficaram prontos e foram guardados: ao montar de novo, "
                    "só o que falhou (ou o que você mudar) é refeito.")
        final = VideoAssemblyError(msg)
        final.segment_index = getattr(err, "segment_index", i0)
        final.segment_indices = [k for k, _e in falhas]
        raise final from (exc0 if exc0 is not err else None)

    normalized_paths = results_by_index
    with (perf_log.timed("montagem:entradas_saidas") if perf_log else nullcontext()):
        normalized_paths = _aplicar_gestos(
            segments, normalized_paths, duracoes_alvo, plano_transicoes, ultimo_do_grupo,
            target_width, target_height, clips_dir, work_dir, concurrency,
            em_cena={k for (g_a, g_b, g_t) in grupos if g_t for k in range(g_a, g_b + 1)}
            # 🪧 foto em cartão: o próprio cartão já entra (sobe + aparece); o gesto mexeria o FUNDO junto
            | {k for k, sg in enumerate(segments) if getattr(sg, "aspect_fill", None) == "cartao"
               and ((sg.override_source or {}).get("kind") or sg.media_type) == "image"},
        )

    # junta os takes de cada cena com template num clipe só
    final_paths: List[str] = []
    final_duracoes: List[float] = []
    final_plano: List[tuple] = []
    n_cenas = sum(1 for g in grupos if g[2])
    feitas = 0
    for gi, (g_ini, g_fim, g_tid) in enumerate(grupos):
        dur = segments[g_fim].end - segments[g_ini].start + extras[g_fim]
        if g_tid:
            if on_progress:
                on_progress("compondo_cenas", feitas, n_cenas)
            base = segments[g_ini].start
            palavras_rel = []
            for k in range(g_ini, g_fim + 1):
                pal = (palavras_por_trecho or [None] * total)[k] if palavras_por_trecho and k < len(palavras_por_trecho) else None
                palavras_rel.append([
                    {"word": w.get("word", ""), "start": float(w.get("start", 0)) - base, "end": float(w.get("end", 0)) - base}
                    for w in (pal or [])
                ] or None)
            saida_cena = os.path.join(clips_dir, f"cena_{g_ini:04d}.mp4")
            try:
                with (perf_log.timed(f"montagem:cena_{g_ini}", template=g_tid) if perf_log else nullcontext()):
                    cenas_dp.renderizar_cena(
                        g_tid, normalized_paths[g_ini:g_fim + 1],
                        [segments[k].start - base for k in range(g_ini, g_fim + 1)], dur, saida_cena,
                        target_width, target_height, os.path.join(work_dir, "cenas"),
                        campos=getattr(segments[g_ini], "template_campos", None) or {},
                        falas=[(falas_por_trecho[k] if falas_por_trecho and k < len(falas_por_trecho) else "") for k in range(g_ini, g_fim + 1)],
                        palavras=palavras_rel, paleta=paleta,
                    )
            except Exception as exc:  # noqa: BLE001
                err = VideoAssemblyError(
                    f"Trecho {g_ini + 1}: não consegui montar a cena '{g_tid}' ({exc}). Tire o template desse "
                    "trecho no editor (ou troque por outro) e monte de novo."
                )
                err.segment_index = g_ini
                raise err from exc
            feitas += 1
            final_paths.append(saida_cena)
        else:
            final_paths.append(normalized_paths[g_ini])
        final_duracoes.append(dur)
        if gi < len(grupos) - 1:
            final_plano.append(plano_transicoes[g_fim])

    # cada pedaço PRECISA ter a duração que o plano espera: um clipe mais curto
    # (download que veio menor, efeito/gesto/cena que encurtou) deslocava todas
    # as transições seguintes — cenas fora do lugar e vídeo final mais curto.
    final_paths = _garantir_duracoes(final_paths, final_duracoes, clips_dir)
    _relatorio_montagem(work_dir, segments, results_by_index, normalized_paths, duracoes_alvo, grupos, final_paths, final_duracoes, final_plano,
                        extra={"origens": origens, "W": target_width, "H": target_height, "trim_position": trim_position,
                               "filtro_cor": cfg.get("filtro_cor"), "paleta": paleta, "plano_transicoes": [list(p) for p in plano_transicoes]})

    import progresso_ffmpeg
    dur_video = float(sum(final_duracoes) or 0)

    def _acomp(etapa: str):
        """v84_114: o andamento do ffmpeg desta etapa (fração do vídeo já processada) vai pra tela."""
        def _cb(frac: float, detalhe: str) -> None:
            if not on_progress:
                return
            try:
                on_progress(etapa, int(round(frac * 1000)), 1000, detalhe=detalhe)
            except TypeError:  # on_progress antigo (3 argumentos)
                on_progress(etapa, int(round(frac * 1000)), 1000)
        _cb(0.0, "")  # v84_118: a etapa começa em 0% (antes mostrava 208/208 = cheia antes de começar)
        return progresso_ffmpeg.acompanhar(_cb, dur_video)

    if on_progress:
        on_progress("concatenando", total, total)
    concat_path = os.path.join(work_dir, "_concat_video_only.mp4")
    with (perf_log.timed("montagem:concatenar") if perf_log else nullcontext()), _acomp("concatenando"):
        _concat_clips_com_plano(final_paths, final_duracoes, final_plano, concat_path, work_dir)

    # filtro de cor: identidade GLOBAL do vídeo (regra do DarkPlanner — um só)
    cadeia_cor = _dp_visual.cadeia_filtro(cfg.get("filtro_cor"))
    if cadeia_cor:
        if on_progress:
            on_progress("filtro_cor", total, total)
        filtrado = os.path.join(work_dir, "_concat_filtrado.mp4")
        with (perf_log.timed("montagem:filtro_cor", filtro=cfg.get("filtro_cor")) if perf_log else nullcontext()), _acomp("filtro_cor"):
            import export_paralelo  # ⚡ v84_115: em pedaços paralelos
            if not export_paralelo.tentar("filtro de cor", lambda: export_paralelo.vf_em_pedacos(
                    concat_path, filtrado, cadeia_cor, dur_video or _probe_duration(concat_path), os.path.join(work_dir, "pedacos"), "filtro")):
                _run_ffmpeg(["-i", concat_path, "-vf", cadeia_cor + ",format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                         "-pix_fmt", "yuv420p", "-r", str(TARGET_FPS), "-an", filtrado], timeout=4 * 3600)
        concat_path = filtrado

    # censura de IMAGEM (blur/pixelado/tarja): na imagem crua, antes dos textos e
    # gráficos — assim legendas e destaques continuam legíveis por cima
    import dp_censura
    censura = dp_censura.normalizar(censura or [])
    if dp_censura.de_video(censura):
        if on_progress:
            on_progress("censura", total, total)
        censurado = os.path.join(work_dir, "_concat_censurado.mp4")
        with (perf_log.timed("montagem:censura", quantidade=len(dp_censura.de_video(censura))) if perf_log else nullcontext()), _acomp("censura"):
            try:
                dp_censura.aplicar_video(concat_path, censurado, censura, target_width, target_height,
                                         os.path.join(work_dir, "censura"), _probe_duration(concat_path),
                                         run=lambda cmd: _run_ffmpeg(cmd, timeout=4 * 3600))
            except Exception as exc:  # noqa: BLE001
                raise VideoAssemblyError(f"A censura (blur/tarja) falhou: {str(exc)[-400:]} — confira as áreas na faixa Censura.") from exc
        concat_path = censurado

    # efeitos sonoros (sons do editor original): automáticos + os da timeline
    import dp_sons
    opcoes_sons = cfg.get("sons_auto") or {"transicoes": True, "cenas": True, "destaques": True, "editoriais": True}
    eventos_sons = dp_sons.eventos_automaticos(segments, plano_transicoes, grupos, destaques, dict(opcoes_sons, palavras=palavras_narracao or []),
                                               editoriais=editoriais)
    for item in sfx or []:
        if dp_sons.som(item.get("som")):
            eventos_sons.append({"som": item["som"], "inicio": max(0.0, float(item.get("start", 0))), "volume": float(item.get("volume", 1.0))})
    if eventos_sons:
        if on_progress:
            on_progress("sons", total, total)
        with (perf_log.timed("montagem:sons", quantidade=len(eventos_sons)) if perf_log else nullcontext()):
            try:
                audio_path = dp_sons.mixar(audio_path, eventos_sons, os.path.join(work_dir, "_narracao_com_sons.wav"),
                                           volume_sfx=float(cfg.get("sons_volume", 0.55)))
            except Exception as exc:  # noqa: BLE001
                raise VideoAssemblyError(f"Falha ao mixar os efeitos sonoros: {str(exc)[-300:]}") from exc

    # censura de ÁUDIO (bip/mudo) na narração + efeitos; a trilha de fundo continua
    if dp_censura.de_audio(censura):
        try:
            com_bip = os.path.join(work_dir, "_narracao_censurada.wav")
            if dp_censura.aplicar_audio(audio_path, com_bip, censura, _probe_duration(audio_path)):
                audio_path = com_bip
        except Exception as exc:  # noqa: BLE001
            raise VideoAssemblyError(f"A censura de áudio (bip) falhou: {str(exc)[-300:]}") from exc

    if on_progress:
        on_progress("sincronizando_audio", total, total)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with (perf_log.timed("montagem:mux_audio", com_trilha=bool(music_path)) if perf_log else nullcontext()), _acomp("sincronizando_audio"):
        if music_path and os.path.exists(music_path):
            _mux_audio_with_music(concat_path, audio_path, music_path, output_path, music_volume)
        else:
            _mux_audio(concat_path, audio_path, output_path)

    if overlays:
        if on_progress:
            on_progress("aplicando_overlays", total, total)
        overlaid_path = os.path.join(work_dir, "_with_overlays.mp4")
        with (perf_log.timed("montagem:overlays", quantidade=len(overlays)) if perf_log else nullcontext()), _acomp("aplicando_overlays"):
            apply_overlays(output_path, overlays, overlaid_path, target_width, target_height)
        if _etapa_inteira(output_path, overlaid_path, "overlays", work_dir):
            shutil.move(overlaid_path, output_path)

    # destaques de texto do DarkPlanner (legenda ASS animada + tratamento da cena)
    # 🗞 quadros editoriais (ficha, post, terminal, recortes…) — antes dos destaques (eles ficam por cima)
    if editoriais:
        import dp_editorial
        if on_progress:
            on_progress("editoriais", total, total)
        com_ed = os.path.join(work_dir, "_com_editoriais.mp4")
        with (perf_log.timed("montagem:editoriais", quantidade=len(editoriais)) if perf_log else nullcontext()), _acomp("editoriais"):
            try:
                r_ed = dp_editorial.aplicar_editoriais(output_path, com_ed, editoriais, target_width, target_height,
                                                       os.path.join(work_dir, "editoriais"), imagens=imagens_editorial, paleta=paleta_textos)
            except Exception as exc:  # noqa: BLE001
                raise VideoAssemblyError(f"Os quadros editoriais falharam: {str(exc)[-400:]} — confira o quadro no editor.") from exc
        if r_ed == com_ed and _etapa_inteira(output_path, com_ed, "quadros editoriais", work_dir):
            shutil.move(com_ed, output_path)

    if destaques:
        import dp_destaques
        if on_progress:
            on_progress("destaques", total, total)
        com_destaques = os.path.join(work_dir, "_com_destaques.mp4")
        with (perf_log.timed("montagem:destaques", quantidade=len(destaques)) if perf_log else nullcontext()), _acomp("destaques"):
            try:
                dp_destaques.aplicar_destaques(output_path, com_destaques, destaques, target_width, target_height,
                                               os.path.join(work_dir, "destaques"), paleta=paleta_textos, palavras=palavras_narracao)
            except Exception as exc:  # noqa: BLE001
                raise VideoAssemblyError(f"Os destaques de texto falharam: {str(exc)[-400:]} — tire o destaque problemático no editor.") from exc
        if _etapa_inteira(output_path, com_destaques, "destaques de texto", work_dir):
            shutil.move(com_destaques, output_path)

    # gráficos animados com os dados (barras, linha, pizza…)
    if graficos:
        import dp_graficos
        if on_progress:
            on_progress("graficos", total, total)
        com_graficos = os.path.join(work_dir, "_com_graficos.mp4")
        with (perf_log.timed("montagem:graficos", quantidade=len(graficos)) if perf_log else nullcontext()), _acomp("graficos"):
            try:
                r = dp_graficos.aplicar_graficos(output_path, com_graficos, graficos, target_width, target_height,
                                                 os.path.join(work_dir, "graficos"), paleta=paleta_textos)
            except Exception as exc:  # noqa: BLE001
                raise VideoAssemblyError(f"Os gráficos falharam: {str(exc)[-400:]} — confira os dados do gráfico no editor.") from exc
        if r == com_graficos and _etapa_inteira(output_path, com_graficos, "gráficos", work_dir):
            shutil.move(com_graficos, output_path)

    return output_path
