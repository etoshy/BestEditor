"""
main.py
=======

Ponto de entrada único do toolkit de fontes de vídeo. Permite escolher
qual provedor usar — Pexels, Pixabay, Magnific, Mixkit ou VistaCreate —
tanto programaticamente (função `get_client`) quanto pela linha de
comando.

Os cinco clientes (`pexels/pexels_client.py`, `pixabay/pixabay_client.py`,
`magnific/magnific_client.py`, `mixkit/mixkit_client.py` e
`vistacreate/vistacreate_client.py`) continuam completos e utilizáveis
sozinhos (com suas próprias CLIs e READMEs); este arquivo só adiciona
uma camada fina por cima para quem quer trocar de provedor sem trocar de
script.

Uso programático
-----------------
    from main import get_client

    client = get_client("pexels")   # ou "pixabay" / "magnific" / "mixkit" / "vistacreate"
    videos = client.search_all(query="dog and cats", max_pages=3)
    client.download_video(videos[0], output_dir="videos")

    # Trocar de provedor é só mudar a string:
    client2 = get_client("pixabay")
    videos2 = client2.search_all(query="gato cachorro", max_pages=3)

    client3 = get_client("magnific")
    videos3 = client3.search_all(query="dog", only_free=True, max_pages=3)

    client4 = get_client("mixkit")
    videos4 = client4.search_all(category="animal-nature", max_pages=3)

    client5 = get_client("vistacreate")
    videos5 = client5.search_all(query="animal nature", max_pages=3)

Os cinco clientes expõem quase a mesma "forma" de uso (`search_all`,
`download_video`, `download_many`), então o resto do seu código (o
sistema de edição de vídeo) pode tratar qualquer um deles de forma
praticamente intercambiável — só os nomes dos filtros aceitos por
`search_all(**filtros)` mudam de um provedor para o outro, o Mixkit busca
por `category` em vez de `query`, o Magnific tem a particularidade de
recusar baixar vídeos premium por padrão, e o VistaCreate sempre entrega
o vídeo em ~480p (veja os READMEs de cada pasta para os detalhes
completos).

Buscar em vários provedores de uma vez
----------------------------------------
    from main import search_multiple

    resultados = search_multiple({
        "pexels": {"query": "dog and cats", "orientation": "landscape", "max_pages": 2},
        "pixabay": {"query": "gato cachorro", "max_pages": 2},
        "mixkit": {"category": "animal-nature", "max_pages": 2},
    })
    for provider, videos in resultados.items():
        print(provider, len(videos))

Cada provedor que falhar (rede, filtro inválido etc.) é reportado no
stderr e devolve uma lista vazia, em vez de derrubar a busca dos outros.

Robustez de rede
------------------
Todas as requisições HTTP dos 5 clientes passam por um retry automático
com backoff exponencial (até 3 tentativas) para erros transitórios —
timeout, falha de conexão, ou respostas HTTP 429/500/502/503/504. Erros
"definitivos" como 404 (vídeo não existe) ou 403 (bloqueio) não são
re-tentados, já que insistir não adianta.

Uso pela linha de comando
--------------------------
    # Buscar
    python main.py search pexels "dog and cats" --pages 3 \\
        --filter orientation=landscape --filter people_count=2 --out resultados.json

    python main.py search pixabay "gato cachorro" --pages 3 \\
        --filter orientation=vertical --filter content_type=ai --out resultados.json

    # Baixar
    python main.py download pexels "<url_ou_id>" --quality hd --output-dir videos
    python main.py download pixabay "<url>" --output-dir videos

`--filter chave=valor` pode ser repetido quantas vezes forem necessárias;
os valores "true"/"false" viram booleano e valores só-dígitos viram
inteiro automaticamente — o resto fica como string. Veja o README de
cada provedor para a lista de filtros válidos.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Union

from pexels.pexels_client import PexelsClient, PexelsClientError
from pixabay.pixabay_client import PixabayClient, PixabayClientError
from magnific.magnific_client import MagnificClient, MagnificClientError
from mixkit.mixkit_client import MixkitClient, MixkitClientError
from vistacreate.vistacreate_client import VistaCreateClient, VistaCreateClientError
from pexels_api_client import PexelsAPIClient, PexelsAPIClientError
from api_keys import load_dotenv

PROVIDERS = {"pexels", "pixabay", "magnific", "mixkit", "vistacreate"}


class ProviderError(Exception):
    """Erro de uso do toolkit (provedor inválido, etc.)."""


def pexels_api_keys_configured() -> bool:
    """True se houver ao menos uma chave em PEXELS_API_KEYS (carrega o
    .env primeiro, se existir, sem sobrescrever variáveis já definidas).
    """
    load_dotenv()
    return bool(os.environ.get("PEXELS_API_KEYS", "").strip())


def get_client(
    provider: str, **kwargs: Any
) -> Union[PexelsClient, PexelsAPIClient, PixabayClient, MagnificClient, MixkitClient, VistaCreateClient]:
    """Fábrica simples: devolve um cliente já instanciado para o provedor
    pedido. `kwargs` são repassados ao construtor do cliente (ex: `delay`).

        get_client("pexels")
        get_client("pixabay", delay=1.0)
        get_client("magnific")
        get_client("mixkit")
        get_client("vistacreate")

    Para "pexels": se `PEXELS_API_KEYS` estiver configurado no ambiente
    ou no `.env` (e nenhum `session` de navegador for passado
    explicitamente), usa a API oficial do Pexels (`PexelsAPIClient`, sem
    precisar de Chrome) em vez do scraping por navegador. Passe
    `force_browser=True` para pular essa checagem e usar sempre o
    scraping, mesmo com chaves configuradas.
    """
    provider = provider.lower().strip()
    if provider == "pexels":
        force_browser = kwargs.pop("force_browser", False)
        if not force_browser and "session" not in kwargs and pexels_api_keys_configured():
            return PexelsAPIClient(**kwargs)
        return PexelsClient(**kwargs)
    if provider == "pixabay":
        return PixabayClient(**kwargs)
    if provider == "magnific":
        return MagnificClient(**kwargs)
    if provider == "mixkit":
        return MixkitClient(**kwargs)
    if provider == "vistacreate":
        return VistaCreateClient(**kwargs)
    raise ProviderError(f"Provedor desconhecido: {provider!r} (use um de {sorted(PROVIDERS)})")


def _coerce_filter_value(raw: str) -> Any:
    """Converte o valor textual de um --filter chave=valor para bool/int
    quando possível, senão mantém como string.
    """
    low = raw.lower()
    if low in ("true", "false"):
        return low == "true"
    if raw.isdigit():
        return int(raw)
    return raw


def _parse_filters(pairs: list) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ProviderError(f"--filter inválido (esperado chave=valor): {pair!r}")
        key, _, value = pair.partition("=")
        filters[key.strip()] = _coerce_filter_value(value.strip())
    return filters


def search_multiple(providers_config: Dict[str, Dict[str, Any]], tag_provider: bool = True, max_workers: int = 5) -> Dict[str, list]:
    """Busca simultaneamente em múltiplos provedores."""
    results: Dict[str, list] = {}
    def work(provider, kwargs):
        client=get_client(provider); kwargs=dict(kwargs); pages=kwargs.pop("max_pages",1)
        return provider, client.search_all(max_pages=pages, **kwargs)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures=[ex.submit(work,p,k) for p,k in providers_config.items()]
        for f in as_completed(futures):
            try:p,v=f.result(); results[p]=v
            except Exception as exc: logging.exception("search_multiple falhou: %s",exc)
    return results


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Toolkit unificado de fontes de vídeo (Pexels + Pixabay).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- search ---
    p_search = sub.add_parser("search", help="Buscar vídeos em um dos provedores.")
    p_search.add_argument("provider", choices=sorted(PROVIDERS))
    p_search.add_argument(
        "query",
        help='Termo de busca (Pexels/Pixabay/Magnific) ou slug de categoria '
        '(Mixkit, ex: "animal-nature")',
    )
    p_search.add_argument("--pages", type=int, default=1, help="Quantidade de páginas a buscar.")
    p_search.add_argument(
        "--filter",
        action="append",
        dest="filters",
        metavar="chave=valor",
        help="Filtro específico do provedor (repetível). Ex: --filter orientation=landscape",
    )
    p_search.add_argument("--out", help="Salvar resultado em um arquivo .json")

    # --- download ---
    p_dl = sub.add_parser("download", help="Baixar um vídeo específico.")
    p_dl.add_argument("provider", choices=sorted(PROVIDERS))
    p_dl.add_argument(
        "target",
        help="URL da página do vídeo (Pexels/Pixabay/Mixkit), ID (Pexels), ou ID numérico "
        "(Magnific/VistaCreate, combinado com --query).",
    )
    p_dl.add_argument("--output-dir", default="videos")
    p_dl.add_argument(
        "--quality",
        default="best",
        help="Pexels: best/worst/sd/hd/uhd. Mixkit: best/worst/360/720/1080/2160. "
        "VistaCreate: small/medium/large/best/worst (medium/large experimentais). "
        "Pixabay e Magnific sempre usam a melhor qualidade disponível.",
    )
    p_dl.add_argument(
        "--query",
        help="Obrigatório para o Magnific: termo de busca para localizar o vídeo pelo ID "
        "(a API do Magnific não tem endpoint de detalhe por ID).",
    )
    p_dl.add_argument(
        "--allow-watermarked",
        action="store_true",
        help="Só para o Magnific: permite baixar vídeos premium (preview com marca d'água).",
    )
    p_dl.add_argument(
        "--no-metadata",
        action="store_true",
        help="Não gera os arquivos .json/.txt com título/descrição do lado do vídeo baixado.",
    )
    p_dl.add_argument(
        "--no-embed-metadata",
        action="store_true",
        help="Não tenta embutir título/descrição dentro do próprio .mp4 via ffmpeg "
        "(o sidecar .json/.txt continua sendo gerado, a não ser que --no-metadata também seja usado).",
    )

    return parser


def _run_search(args: argparse.Namespace) -> None:
    filters = _parse_filters(args.filters)
    client = get_client(args.provider)

    if args.provider == "mixkit":
        videos = client.search_all(category=args.query, max_pages=args.pages, **filters)
    else:
        videos = client.search_all(query=args.query, max_pages=args.pages, **filters)
    result = [v.to_dict() for v in videos]  # pexels/pixabay/magnific/vistacreate all use query=

    print(f"[{args.provider}] {len(result)} vídeos encontrados.")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"Salvo em {args.out}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def _run_download(args: argparse.Namespace) -> None:
    client = get_client(args.provider)
    video = None

    if args.provider == "pexels":
        target = args.target
        if isinstance(client, PexelsAPIClient):
            # A API oficial só busca por ID numérico; se vier uma URL,
            # extrai o ID do final dela (".../algo-123456/" -> "123456").
            video_id = target if target.isdigit() else target.rstrip("/").rsplit("-", 1)[-1]
            if not video_id.isdigit():
                raise ProviderError(
                    f"Não consegui extrair um ID numérico de {target!r} para usar com a API oficial."
                )
            video = client.get_video(video_id)
        elif target.isdigit():
            video = client.get_video_by_id(target)
        else:
            video = client.get_video_by_url(target)
        path = client.download_video(video, output_dir=args.output_dir, quality=args.quality)
    elif args.provider == "pixabay":
        video = client.get_video_by_url(args.target)
        path = client.download_video(video, output_dir=args.output_dir)
    elif args.provider == "magnific":
        if not args.query:
            raise ProviderError(
                "Para o Magnific, informe --query com o termo de busca usado para "
                "localizar o vídeo pelo ID (ex: --query dog)."
            )
        videos = client.search_all(query=args.query, max_pages=5)
        video = next((v for v in videos if v.id == str(args.target)), None)
        if not video:
            raise ProviderError(
                f"Não achei o vídeo id={args.target} buscando por {args.query!r}."
            )
        path = client.download_video(
            video, output_dir=args.output_dir, allow_watermarked=args.allow_watermarked
        )
    elif args.provider == "mixkit":
        video = client.get_video_by_url(args.target)
        quality = args.quality
        if isinstance(quality, str) and quality.isdigit():
            quality = int(quality)
        path = client.download_video(video, output_dir=args.output_dir, quality=quality)
    else:  # vistacreate
        if not args.query:
            raise ProviderError(
                "Para o VistaCreate, informe --query com o termo de busca usado para "
                "localizar o vídeo pelo ID (ex: --query 'animal nature')."
            )
        videos = client.search_all(query=args.query, max_pages=5)
        video = next((v for v in videos if v.id == str(args.target)), None)
        if not video:
            raise ProviderError(
                f"Não achei o vídeo id={args.target} buscando por {args.query!r}."
            )
        quality = args.quality if args.quality in ("small", "medium", "large", "best", "worst") else "small"
        path = client.download_video(video, output_dir=args.output_dir, quality=quality)

    if not args.no_metadata:
        try:
            from video_metadata import attach_metadata

            result = attach_metadata(
                video, path, provider=args.provider, embed=not args.no_embed_metadata
            )
            if result["sidecar_files"]:
                print(f"[{args.provider}] Metadados salvos em: {', '.join(result['sidecar_files'])}")
            if result["embedded"]:
                print(f"[{args.provider}] Título/descrição embutidos no próprio arquivo (ffmpeg).")
        except Exception as exc:  # noqa: BLE001
            print(f"[{args.provider}] Aviso: não consegui anexar metadados ({exc}).", file=sys.stderr)

    print(f"[{args.provider}] Baixado em: {path}")


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "search":
            _run_search(args)
        elif args.command == "download":
            _run_download(args)
    except (
        ProviderError,
        PexelsClientError,
        PexelsAPIClientError,
        PixabayClientError,
        MagnificClientError,
        MixkitClientError,
        VistaCreateClientError,
    ) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
