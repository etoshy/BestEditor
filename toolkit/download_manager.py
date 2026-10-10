from __future__ import annotations
import json, logging, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List

from video_metadata import attach_metadata

class Manifest:
    def __init__(self, path):
        self.path=Path(path); self.lock=threading.Lock(); self.data={}
        if self.path.exists():
            try:self.data=json.loads(self.path.read_text(encoding='utf8'))
            except Exception:self.data={}
    def has(self,key): return key in self.data and self.data[key].get('status')=='ok'
    def set(self,key,**value):
        with self.lock:
            # Mescla com o que está em disco antes de escrever, para não
            # perder registros gravados por OUTRA instância de Manifest
            # apontando pro mesmo arquivo (defesa extra; o caminho normal
            # de uso em lote já usa uma única instância compartilhada).
            if self.path.exists():
                try:
                    on_disk = json.loads(self.path.read_text(encoding='utf8'))
                    merged = dict(on_disk)
                    merged.update(self.data)
                    self.data = merged
                except Exception:
                    pass
            self.data[key]=value; self.path.write_text(json.dumps(self.data,ensure_ascii=False,indent=2),encoding='utf8')

def configure_logging(level: int = logging.INFO):
    logging.basicConfig(level=level, format='%(asctime)s %(levelname)s %(name)s %(message)s')

def download_concurrent(jobs, max_workers=3, retries=3, backoff=2, write_metadata=True, embed_ffmpeg=True):
    manifest=Manifest(jobs[0]['manifest']) if jobs else None
    def work(job):
        key=f"{job['provider']}:{getattr(job['video'],'id',job['index'])}"
        if job.get('skip_existing',True) and manifest.has(key): return key,'skipped',None
        last=None
        for attempt in range(1,retries+1):
            try:
                path=job['client'].download_video(job['video'],output_dir=job['output_dir'])
                if write_metadata or embed_ffmpeg:
                    try:
                        attach_metadata(job['video'], path, provider=job['provider'], sidecar=write_metadata, embed=embed_ffmpeg)
                    except Exception as meta_exc:
                        logging.getLogger("download_manager").warning("Falha ao anexar metadados em %s: %s", path, meta_exc)
                manifest.set(key,status='ok',path=str(path),provider=job['provider'],timestamp=time.time())
                return key,'ok',str(path)
            except Exception as e:
                last=e; time.sleep(backoff*attempt)
        manifest.set(key,status='failed',error=str(last),provider=job['provider'],timestamp=time.time())
        return key,'failed',str(last)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures=[ex.submit(work,j) for j in jobs]
        return [f.result() for f in as_completed(futures)]


def download_concurrent_grouped(
    jobs_by_provider: Dict[str, List[dict]],
    max_workers: int = 3,
    per_provider_workers: int = 1,
    retries: int = 3,
    backoff: int = 2,
    manifest_path: str = "downloads_manifest.json",
    write_metadata: bool = True,
    embed_ffmpeg: bool = True,
):
    """Baixa vídeos de VÁRIOS provedores ao mesmo tempo, mas com dois
    cuidados importantes:

    1) Cada provedor usa UMA sessão de navegador (Chrome) reaproveitada
       entre downloads, e essa sessão só processa uma navegação por vez.
       Por isso: até `max_workers` provedores rodando em paralelo (cada
       um com seu próprio navegador, sem conflito entre si), mas dentro
       do MESMO provedor só `per_provider_workers` downloads simultâneos
       (o padrão, 1, é o mais seguro — pedir dois downloads ao mesmo
       tempo na mesma aba do Chrome pode fazer um atropelar o outro).

    2) O manifesto é UMA instância compartilhada entre todos os
       provedores (não uma por provedor) — importante porque, se cada
       provedor tivesse seu próprio objeto `Manifest` apontando pro mesmo
       arquivo, o último a terminar escreveria o arquivo inteiro por
       cima, apagando os registros que os outros provedores já tinham
       salvo (foi um bug real, pego em teste, ao tentar delegar isso pra
       `download_concurrent()` — por isso esta função não a reusa
       diretamente, e sim reimplementa a mesma lógica de job com UM
       manifesto só).

    `jobs_by_provider`: {"pexels": [job, job, ...], "mixkit": [...]}
    Cada job precisa ter: provider, client, video, output_dir, index.

    `write_metadata`: grava um .json + .txt com título/descrição do lado
    de cada vídeo baixado (veja `video_metadata.py`).
    `embed_ffmpeg`: além do sidecar, tenta embutir título/descrição no
    próprio .mp4 via ffmpeg (silenciosamente ignorado se não tiver
    ffmpeg instalado).

    Retorna a lista combinada de resultados (key, status, detalhe) de
    todos os provedores, no mesmo formato que `download_concurrent`
    devolveria sozinho.
    """
    logger = logging.getLogger("download_manager")
    manifest = Manifest(manifest_path)

    def work(job: dict):
        key = f"{job['provider']}:{getattr(job['video'], 'id', job['index'])}"
        if job.get("skip_existing", True) and manifest.has(key):
            return key, "skipped", None
        last = None
        for attempt in range(1, retries + 1):
            try:
                path = job["client"].download_video(job["video"], output_dir=job["output_dir"])
                if write_metadata or embed_ffmpeg:
                    try:
                        attach_metadata(
                            job["video"], path, provider=job["provider"],
                            sidecar=write_metadata, embed=embed_ffmpeg,
                        )
                    except Exception as meta_exc:  # noqa: BLE001
                        logger.warning("Falha ao anexar metadados em %s: %s", path, meta_exc)
                manifest.set(key, status="ok", path=str(path), provider=job["provider"], timestamp=time.time())
                return key, "ok", str(path)
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(backoff * attempt)
        manifest.set(key, status="failed", error=str(last), provider=job["provider"], timestamp=time.time())
        return key, "failed", str(last)

    def run_provider(jobs: List[dict]):
        with ThreadPoolExecutor(max_workers=per_provider_workers) as inner_ex:
            futures = [inner_ex.submit(work, job) for job in jobs]
            return [f.result() for f in as_completed(futures)]

    active = {p: j for p, j in jobs_by_provider.items() if j}
    all_results: List[tuple] = []
    if not active:
        return all_results

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(run_provider, jobs): provider for provider, jobs in active.items()}
        for future in as_completed(futures):
            provider = futures[future]
            try:
                all_results.extend(future.result())
            except Exception as exc:  # noqa: BLE001
                logger.exception("Download em lote do provedor %s falhou: %s", provider, exc)

    return all_results
