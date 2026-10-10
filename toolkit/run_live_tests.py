"""
run_live_tests.py
===================

Test runner automatizado que roda testes AO VIVO (com acesso real à
internet) contra os 5 provedores do toolkit — Pexels, Pixabay, Magnific,
Mixkit e VistaCreate — e grava um relatório completo num arquivo de log
de texto, fácil de mandar para quem for corrigir o código.

Para cada provedor, o script tenta:
  1) `search_all()` com um termo/categoria de teste padrão (configurável);
  2) baixar alguns dos primeiros resultados encontrados;
  3) registrar sucesso/falha de cada etapa, com a mensagem de erro
     completa (incluindo traceback) quando algo falha.

Ao final, imprime e grava um resumo por provedor (✅/❌) e a contagem de
vídeos encontrados/baixados, além de uma seção "possíveis vídeos
removidos" para os casos em que o download falhou com HTTP 404 (o que
geralmente indica que aquele vídeo específico não existe mais na fonte —
diferente de uma falha genérica de rede ou de parsing).

Uso
---
    # Roda tudo, com os termos de teste padrão
    python run_live_tests.py

    # Só alguns provedores
    python run_live_tests.py --providers pexels pixabay

    # Baixa mais itens por provedor (padrão: 2) e mantém os arquivos
    python run_live_tests.py --download-count 5 --keep-files

    # Troca o termo/categoria de teste de um provedor específico
    python run_live_tests.py --providers mixkit --mixkit-category dog

O log completo (com tracebacks) vai para `test_errors_log.txt` na pasta
onde o script for executado. Os vídeos baixados durante o teste vão para
`test_downloads/<provedor>/` e são apagados ao final por padrão (use
`--keep-files` para mantê-los).

IMPORTANTE: este script precisa de acesso de rede real aos 5 domínios
(pexels.com, pixabay.com, magnific.com, mixkit.co, create.vista.com).
Em ambientes com a rede restrita (ex: alguns sandboxes), todas as buscas
vão falhar com erro de rede — isso é esperado nesse caso e não indica um
bug no código.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from main import get_client, PROVIDERS

LOG_FILE = "test_errors_log.txt"
DOWNLOAD_DIR = "test_downloads"

ALL_PROVIDERS = sorted(PROVIDERS)


@dataclass
class ProviderTestResult:
    provider: str
    search_ok: bool = False
    videos_found: int = 0
    download_attempts: int = 0
    download_ok: int = 0
    download_failed: int = 0
    possibly_removed: List[str] = field(default_factory=list)  # ids com erro 404
    errors: List[str] = field(default_factory=list)

    @property
    def overall_ok(self) -> bool:
        return self.search_ok and self.videos_found > 0 and self.download_failed == 0

    def status_emoji(self) -> str:
        return "✅" if self.overall_ok else "❌"


class Logger:
    """Escreve simultaneamente no console e no arquivo de log."""

    def __init__(self, path: str):
        self._fh = open(path, "w", encoding="utf-8")

    def log(self, msg: str = "") -> None:
        print(msg)
        self._fh.write(msg + "\n")

    def close(self) -> None:
        self._fh.close()


# --------------------------------------------------------------------------- #
# Configuração de teste por provedor (termo/categoria + kwargs de busca)
# --------------------------------------------------------------------------- #

def _default_test_configs(args: argparse.Namespace) -> Dict[str, Dict[str, Any]]:
    return {
        "pexels": {
            "search_kwargs": {"query": args.pexels_query},
        },
        "pixabay": {
            "search_kwargs": {"query": args.pixabay_query},
        },
        "magnific": {
            "search_kwargs": {"query": args.magnific_query, "only_free": True},
        },
        "mixkit": {
            "search_kwargs": {"category": args.mixkit_category},
        },
        "vistacreate": {
            "search_kwargs": {"query": args.vistacreate_query},
        },
    }


# --------------------------------------------------------------------------- #
# Execução do teste de um único provedor
# --------------------------------------------------------------------------- #

def _is_not_found_error(exc: Exception) -> bool:
    """Heurística simples: os clientes deste toolkit embutem o status
    HTTP na mensagem de erro (ex: "status 404"). Usamos isso para separar
    "vídeo removido/indisponível" de outros tipos de falha.
    """
    return "404" in str(exc)


def run_provider_test(
    provider: str,
    config: Dict[str, Any],
    download_count: int,
    output_root: str,
    log: Logger,
) -> ProviderTestResult:
    result = ProviderTestResult(provider=provider)
    log.log(f"\n{'=' * 60}")
    log.log(f"Provedor: {provider}")
    log.log(f"{'=' * 60}")

    try:
        client = get_client(provider)
    except Exception as exc:  # noqa: BLE001 - queremos capturar qualquer coisa aqui
        msg = f"[get_client] falhou: {exc}\n{traceback.format_exc()}"
        result.errors.append(msg)
        log.log(f"  ❌ ERRO ao criar cliente: {exc}")
        return result

    # --- busca ---
    search_kwargs = config["search_kwargs"]
    log.log(f"  Busca: search_all(max_pages=1, **{search_kwargs})")
    try:
        videos = client.search_all(max_pages=1, **search_kwargs)
        result.search_ok = True
        result.videos_found = len(videos)
        log.log(f"  ✅ Busca OK — {len(videos)} vídeo(s) encontrado(s).")
    except Exception as exc:  # noqa: BLE001
        msg = f"[search_all] falhou: {exc}\n{traceback.format_exc()}"
        result.errors.append(msg)
        log.log(f"  ❌ Busca FALHOU: {exc}")
        log.log(f"     (detalhe completo salvo no log)")
        return result

    if not videos:
        note = (
            "Busca não retornou nenhum vídeo. Pode ser: termo/categoria de teste "
            "sem resultados, filtro isolando demais, ou mudança no site que quebrou "
            "o parsing (verifique se outros termos também retornam vazio)."
        )
        result.errors.append(note)
        log.log(f"  ⚠️  {note}")
        return result

    # --- download ---
    to_download = videos[: max(0, download_count)]
    out_dir = str(Path(output_root) / provider)
    for i, video in enumerate(to_download, start=1):
        vid_id = getattr(video, "id", "?")
        result.download_attempts += 1
        log.log(f"  Download {i}/{len(to_download)} (id={vid_id})...")
        try:
            path = client.download_video(video, output_dir=out_dir)
            result.download_ok += 1
            log.log(f"    ✅ OK -> {path}")
        except Exception as exc:  # noqa: BLE001
            result.download_failed += 1
            msg = f"[download_video id={vid_id}] falhou: {exc}\n{traceback.format_exc()}"
            result.errors.append(msg)
            if _is_not_found_error(exc):
                result.possibly_removed.append(str(vid_id))
                log.log(f"    ❌ FALHOU (HTTP 404 — pode ter sido removido da fonte): {exc}")
            else:
                log.log(f"    ❌ FALHOU: {exc}")

    return result


# --------------------------------------------------------------------------- #
# Orquestração
# --------------------------------------------------------------------------- #

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Testa ao vivo os 5 provedores do toolkit e grava um log de erros em .txt"
    )
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=ALL_PROVIDERS,
        default=ALL_PROVIDERS,
        help="Quais provedores testar (padrão: todos).",
    )
    parser.add_argument("--download-count", type=int, default=2, help="Quantos vídeos baixar por provedor (padrão: 2).")
    parser.add_argument("--keep-files", action="store_true", help="Não apaga os vídeos baixados no teste ao final.")
    parser.add_argument("--log-file", default=LOG_FILE, help=f"Caminho do log de erros (padrão: {LOG_FILE}).")
    parser.add_argument("--output-dir", default=DOWNLOAD_DIR, help=f"Pasta de downloads do teste (padrão: {DOWNLOAD_DIR}).")

    parser.add_argument("--pexels-query", default="dog", help="Termo de busca de teste para o Pexels.")
    parser.add_argument("--pixabay-query", default="dog", help="Termo de busca de teste para o Pixabay.")
    parser.add_argument("--magnific-query", default="dog", help="Termo de busca de teste para o Magnific.")
    parser.add_argument("--mixkit-category", default="animal-nature", help="Categoria de teste para o Mixkit.")
    parser.add_argument("--vistacreate-query", default="dog", help="Termo de busca de teste para o VistaCreate.")

    args = parser.parse_args(argv)

    log = Logger(args.log_file)
    log.log(f"=== Teste ao vivo do Video Sources Toolkit ===")
    log.log(f"Data/hora: {datetime.now().isoformat(timespec='seconds')}")
    log.log(f"Provedores testados: {', '.join(args.providers)}")
    log.log(f"Downloads por provedor: {args.download_count}")

    configs = _default_test_configs(args)
    results: List[ProviderTestResult] = []

    for provider in args.providers:
        result = run_provider_test(
            provider=provider,
            config=configs[provider],
            download_count=args.download_count,
            output_root=args.output_dir,
            log=log,
        )
        results.append(result)

    # --- resumo final ---
    log.log(f"\n{'=' * 60}")
    log.log("RESUMO")
    log.log(f"{'=' * 60}")
    for r in results:
        log.log(
            f"{r.status_emoji()} {r.provider}: "
            f"busca={'OK' if r.search_ok else 'FALHOU'} ({r.videos_found} vídeos) | "
            f"downloads={r.download_ok}/{r.download_attempts} OK"
        )
        if r.possibly_removed:
            log.log(f"    ⚠️  possivelmente removidos (HTTP 404): {', '.join(r.possibly_removed)}")

    any_removed = [rid for r in results for rid in r.possibly_removed]
    if any_removed:
        log.log(f"\nTotal de vídeos possivelmente removidos/indisponíveis: {len(any_removed)}")

    total_errors = sum(len(r.errors) for r in results)
    log.log(f"\nTotal de erros registrados (detalhes com traceback acima): {total_errors}")

    if total_errors:
        log.log(
            "\nPara corrigir: mande o arquivo "
            f"'{args.log_file}' inteiro — ele já tem os tracebacks completos "
            "de cada falha, organizados por provedor."
        )

    log.close()
    print(f"\nLog completo salvo em: {args.log_file}")

    if not args.keep_files and Path(args.output_dir).exists():
        shutil.rmtree(args.output_dir, ignore_errors=True)
        print(f"Arquivos de teste em '{args.output_dir}' removidos (use --keep-files para mantê-los).")

    # Código de saída != 0 se algum provedor teve problema, útil para CI.
    return 0 if all(r.overall_ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
