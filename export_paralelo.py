"""
export_paralelo.py — ⚡ exportação em PEDAÇOS paralelos (v84_115)
===================================================================

Os passes finais da montagem (destaques de texto, legendas, filtro de cor, passe de qualidade) processam o vídeo
INTEIRO num ffmpeg só — e os filtros (legenda ASS, sobreposições) rodam praticamente num núcleo. Num vídeo de 1 hora
isso levava horas, com a CPU quase parada e a placa de vídeo esperando.

Aqui o vídeo é cortado em N pedaços de tempo, cada pedaço roda num ffmpeg PRÓPRIO ao mesmo tempo (como a ⚡ geração
rápida da voz faz com o motor de TTS), e no fim os pedaços são emendados sem recodificar (`-c copy`). Cada pedaço
codifica na placa de vídeo quando tem (NVENC/QSV/AMF — `qualidade_export`) e cai pra CPU se a placa falhar (aí TODOS os
pedaços refazem na CPU, pra emendar sem problema). Qualquer falha → o passe roda do jeito de sempre (um ffmpeg só).

O tempo dentro de cada pedaço continua o do vídeo inteiro (`setpts=...+início`), então legendas, destaques e
qualquer `enable='between(t,a,b)'` funcionam sem mudar nada.

Quantos pedaços: ⚙️ "Exportação em paralelo" (Automático = até 4, pelos núcleos da CPU, RAM livre e sessões da placa;
"1" = desligado). Deixa o PC mais pesado enquanto monta.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

MODOS = ("auto", "1", "2", "3", "4", "6", "8")
MAX_AUTO = 4
MIN_PEDACO_S = 40.0     # pedaço menor que isso não compensa abrir outro ffmpeg
RAM_POR_PEDACO_GB = 0.9
RAM_FOLGA_GB = 2.0
SESSOES_PLACA = 3       # placas de consumo aceitam poucas codificações ao mesmo tempo (= qualidade_export._sessoes_hw)
FPS = 30
AVISO = ("⚡ Exportação em paralelo: o vídeo é dividido em pedaços que rodam ao mesmo tempo (CPU e placa de vídeo) — "
         "monta bem mais rápido, mas o PC fica pesado enquanto isso.")

_estado: Dict[str, Any] = {"modo": None}
_trava = threading.Lock()


def definir(modo: Optional[str]) -> None:
    """O modo desta montagem (vem do Estúdio). None = o das ⚙️ Configurações."""
    with _trava:
        _estado["modo"] = modo if modo in MODOS else None


def limpar() -> None:
    definir(None)


def modo_atual() -> str:
    m = _estado.get("modo")
    if m in MODOS:
        return m
    try:
        import site_config
        m = str(site_config.load_site_config().get("export_paralelo") or "auto")
    except Exception:  # noqa: BLE001
        m = "auto"
    return m if m in MODOS else "auto"


def _ram() -> Optional[Dict[str, float]]:
    try:
        import tts_paralelo
        return tts_paralelo.ler_ram()
    except Exception:  # noqa: BLE001
        return None


def escolher(duracao: float, modo: Optional[str] = None, ram_fn: Optional[Callable[[], Optional[Dict[str, float]]]] = None,
             nucleos: Optional[int] = None, placa: Optional[str] = "?") -> Tuple[int, str]:
    """(quantos pedaços, por quê)."""
    modo = modo or modo_atual()
    if modo == "1":
        return 1, "exportação em paralelo desligada"
    if duracao < 2 * MIN_PEDACO_S:
        return 1, "vídeo curto: um ffmpeg só"
    pedido = MAX_AUTO if modo == "auto" else int(modo)
    limites: List[Tuple[int, str]] = [(pedido, "automático: até 4" if modo == "auto" else f"você pediu {pedido}"),
                                      (int(duracao // MIN_PEDACO_S), "tamanho do vídeo")]
    nucleos = nucleos or os.cpu_count() or 2
    limites.append((max(1, nucleos // 2), f"CPU: {nucleos} núcleos (~2 por pedaço)"))
    ram = (ram_fn or _ram)()
    if ram:
        cabe = int(max(0.0, ram["livre"] - RAM_FOLGA_GB) // RAM_POR_PEDACO_GB)
        limites.append((max(1, cabe), f"RAM: {ram['livre']:.1f} GB livres (~{RAM_POR_PEDACO_GB:g} GB por pedaço)"))
    if placa == "?":
        try:
            import qualidade_export
            placa = qualidade_export.encoder_hw()
        except Exception:  # noqa: BLE001
            placa = None
    if placa:
        limites.append((SESSOES_PLACA + 1, f"placa de vídeo ({placa}): {SESSOES_PLACA} codificações ao mesmo tempo"))
    n, motivo = min(limites, key=lambda x: x[0])
    n = max(1, min(8, n))
    return n, (f"{n} pedaços em paralelo — limite: {motivo}" if n > 1 else f"um ffmpeg só — limite: {motivo}")


def recursos() -> Dict[str, Any]:
    """Pro Estúdio mostrar no modal de montar."""
    try:
        import qualidade_export
        placa = qualidade_export.encoder_hw()
    except Exception:  # noqa: BLE001
        placa = None
    ram = _ram()
    return {"nucleos": os.cpu_count() or 0, "ram_livre": round(ram["livre"], 1) if ram else None,
            "ram_total": round(ram["total"]) if ram else None, "placa": placa, "modo": modo_atual(), "aviso": AVISO,
            "modos": [["auto", "⚡ Automático (recomendado)"], ["1", "Desligado (um ffmpeg só)"], ["2", "2 pedaços"],
                      ["3", "3 pedaços"], ["4", "4 pedaços"], ["6", "6 pedaços"], ["8", "8 pedaços"]]}


# ------------------------------------------------------------------ cortar, rodar em paralelo e emendar
def janelas(duracao: float, n: int) -> List[Tuple[float, int]]:
    """[(início em s, quadros)] — cortes em quadro inteiro (30 fps), o último leva o resto."""
    total = int(round(duracao * FPS))
    por = total // n
    out = []
    for k in range(n):
        q = por if k < n - 1 else total - por * (n - 1)
        out.append(((k * por) / FPS, q))
    return [j for j in out if j[1] > 0]


def deslocar(grafo_linhas: List[str], inicio: float) -> List[str]:
    """Põe o pedaço no tempo do vídeo inteiro: a entrada [0:v] e as imagens em loop ([n:v]…fps=30) andam `inicio`
    segundos; a saída [vout] volta pro zero (o pedaço é um arquivo próprio)."""
    off = f"{inicio:.6f}"
    out = []
    for ln in grafo_linhas:
        ln = ln.replace("[0:v]setpts=PTS-STARTPTS,", f"[0:v]setpts=PTS-STARTPTS+{off}/TB,", 1)
        ln = re.sub(r"^(\[\d+:v\]format=rgba,fps=30)", r"\1" + f",setpts=PTS-STARTPTS+{off}/TB", ln)
        if ln.rstrip().endswith("[vout]"):
            ln = ln.rstrip()[:-len("[vout]")] + ",setpts=PTS-STARTPTS[vout]"
        out.append(ln)
    return out


class PedacosFalharam(RuntimeError):
    pass


def rodar_pedacos(video_in: str, video_out: str, duracao: float, n: int, montar: Callable[[float, int, str], List[str]],
                  work_dir: str, nome: str = "pedaco", simultaneos: Optional[int] = None) -> str:
    """`montar(início, quadros, saída)` → o comando do ffmpeg (sem o encoder da placa: `qualidade_export` põe) que
    gera SÓ o vídeo daquele pedaço. Roda os N ao mesmo tempo, emenda com o áudio de `video_in` e confere a duração."""
    import progresso_ffmpeg
    import qualidade_export
    os.makedirs(work_dir, exist_ok=True)
    js = janelas(duracao, n)
    vagas = threading.BoundedSemaphore(max(1, simultaneos or len(js)))  # pedaços demais: no máximo `simultaneos` de cada vez
    saidas = [os.path.join(work_dir, f"_{nome}{k:02d}.mp4") for k in range(len(js))]
    fracs = [0.0] * len(js)
    pai = progresso_ffmpeg.ramo()  # o andamento de cada pedaço soma na barra da etapa

    def _executar(cmds: List[List[str]], hw: bool) -> List[Optional[str]]:
        erros: List[Optional[str]] = [None] * len(cmds)

        def _um(k: int) -> None:
            def _cb(f: float, _d: str) -> None:
                fracs[k] = f
                pai(sum(fracs) / len(fracs), f"{len(js)} pedaços, {min(len(js), simultaneos or len(js))} ao mesmo tempo")
            try:
                with vagas, progresso_ffmpeg.acompanhar(_cb, js[k][1] / FPS):
                    if hw:
                        with qualidade_export._sessoes_hw:
                            r = progresso_ffmpeg.rodar(cmds[k], timeout=7200)
                    else:
                        r = progresso_ffmpeg.rodar(cmds[k], timeout=7200)
                if r.returncode != 0:
                    erros[k] = r.stderr.strip()[-600:] or f"código {r.returncode}"
            except Exception as exc:  # noqa: BLE001
                erros[k] = str(exc)[-600:]
        ts = [threading.Thread(target=_um, args=(k,), daemon=True) for k in range(len(cmds))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        return erros

    base = [montar(ini, q, saidas[k]) for k, (ini, q) in enumerate(js)]
    cpu = [qualidade_export._ajustar_cpu(c) for c in base]
    hw = [qualidade_export.ajustar(c) for c in base]
    usa_placa = any(qualidade_export.usa_hw(c) for c in hw)
    erros = _executar(hw if usa_placa else cpu, usa_placa)
    if usa_placa and any(erros):  # a placa falhou em algum: TODOS na CPU (pedaços iguais emendam sem recodificar)
        print(f"[montagem] ⚡ a placa falhou num pedaço ({next(e for e in erros if e)[:160]}) — refazendo os pedaços na CPU", flush=True)
        fracs[:] = [0.0] * len(js)
        erros = _executar(cpu, False)
    if any(erros):
        _apagar(saidas)
        raise PedacosFalharam(f"pedaço falhou: {next(e for e in erros if e)}")
    lista = os.path.join(work_dir, f"_{nome}_lista.txt")
    with open(lista, "w", encoding="utf-8") as f:
        f.write("".join(f"file '{os.path.abspath(s).replace(chr(92), '/')}'\n" for s in saidas))
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lista,
                        "-i", video_in, "-map", "0:v:0", "-map", "1:a?", "-c", "copy", "-t", f"{duracao:.3f}",
                        "-movflags", "+faststart", video_out],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
    _apagar(saidas + [lista])
    if r.returncode != 0:
        raise PedacosFalharam(f"não emendei os pedaços: {r.stderr.strip()[-400:]}")
    try:
        from video_assembler import _probe_duration
        d = _probe_duration(video_out)
    except Exception as exc:  # noqa: BLE001
        raise PedacosFalharam(f"o vídeo emendado não abriu: {exc}") from exc
    if abs(d - duracao) > max(0.5, duracao * 0.002):
        raise PedacosFalharam(f"o vídeo emendado ficou com {d:.2f}s (devia ter {duracao:.2f}s)")
    pai(1.0, f"{len(js)} pedaços emendados")
    return video_out


def _apagar(caminhos: List[str]) -> None:
    for c in caminhos:
        try:
            os.remove(c)
        except OSError:
            pass


def vf_em_pedacos(video_in: str, video_out: str, vf: str, duracao: float, work_dir: str, nome: str,
                  extra: Optional[List[str]] = None, n: Optional[int] = None) -> bool:
    """Um filtro simples (-vf) no vídeo inteiro, em pedaços paralelos. False = não compensa (quem chamou roda do jeito
    de sempre); exceção = falhou (quem chamou também roda do jeito de sempre)."""
    n = n or escolher(duracao)[0]
    if n <= 1:
        return False

    def montar(ini: float, quadros: int, saida: str) -> List[str]:
        cadeia = f"setpts=PTS-STARTPTS+{ini:.6f}/TB" + (f",{vf}" if vf else "") + ",format=yuv420p,setpts=PTS-STARTPTS"
        return (["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{ini:.6f}", "-i", video_in, "-vf", cadeia,
                 "-frames:v", str(quadros), "-an"] + list(extra or ["-c:v", "libx264", "-preset", "veryfast"])
                + ["-pix_fmt", "yuv420p", "-r", str(FPS), saida])
    rodar_pedacos(video_in, video_out, duracao, n, montar, work_dir, nome)
    return True


def tentar(rotulo: str, fn: Callable[[], Any]) -> Any:
    """Roda `fn` (o caminho em pedaços); se falhar, avisa no log e devolve None (quem chamou faz do jeito de sempre)."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        print(f"[montagem] ⚡ {rotulo}: os pedaços em paralelo falharam ({str(exc)[:300]}) — fazendo do jeito de sempre", flush=True)
        return None
