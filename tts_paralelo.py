"""
⚡ tts_paralelo.py — gerar UM áudio longo com VÁRIAS INSTÂNCIAS do motor de voz ao mesmo tempo (v84_103)
=======================================================================================================

Antes: um áudio = um processo do motor (XTTS, Chatterbox, Turbo, Kokoro, Piper, Fish) gerando frase por frase, do
começo ao fim. Na placa de vídeo isso deixa a GPU ociosa boa parte do tempo (a geração é sequencial).

Agora: o texto é cortado em BLOCOS (nos parágrafos/frases, nunca no meio de uma frase), e 2, 3 ou 4 instâncias do motor
— cada uma num processo, com o seu modelo carregado — vão pegando o próximo bloco da fila. No fim o site junta os
blocos na ordem (e, com [[INSCREVA]]/[[VENDA]], cada parte continua com o tempo exato dela).

Só com a opção ⚡ GERAÇÃO RÁPIDA ligada (Gerador de voz; vale também no Roteiro para Áudio). Desligada = 1 instância,
como sempre. Ligada, o site mede o PC e decide quantas cabem (até 3 no automático, ou 2/3/4 fixo):
  • VRAM livre na placa NVIDIA (nvidia-smi) ÷ o que cada instância usa na GPU (XTTS/Chatterbox/Turbo);
  • RAM livre ÷ o que cada instância usa na memória (todo motor carrega o modelo na RAM; os de CPU rodam nela);
  • núcleos de CPU (Piper/Kokoro e motores forçados na CPU) — na CPU, mais instâncias só ajudam com muitos núcleos;
  • texto curto (menos de ~1.500 caracteres): 1 — carregar outro modelo custaria mais que o ganho.
⚠ Usa mais placa/memória/CPU: o PC pode ficar um pouco lento enquanto gera. Se faltar memória numa instância, o bloco
dela volta pra fila das outras; o que falhar é gerado de novo, uma vez, numa instância só.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple

MAX_INSTANCIAS = 4
MAX_AUTO = 3
MODOS = ("auto", "1", "2", "3", "4")
TEXTO_MINIMO = 1500          # caracteres — abaixo disso, 1 instância
BLOCO_MIN, BLOCO_MAX = 350, 1600
MOTORES_GPU = ("xtts", "chatterbox", "chatterbox_turbo")
RAM_GB = {"piper": 0.6, "kokoro": 1.2, "xtts": 3.0, "chatterbox_turbo": 3.5, "chatterbox": 4.5, "fish_s2": 0.2}  # por instância
RAM_FOLGA = 2.5   # GB que ficam pro Windows / navegador / o resto do site
AVISO = ("⚠ Geração rápida: várias cópias do motor ao mesmo tempo usam mais placa de vídeo, memória e CPU — o PC pode "
         "ficar um pouco lento enquanto o áudio é gerado.")


def ler_ram() -> Optional[Dict[str, float]]:
    """RAM (GB) total e livre: psutil, ou a API do Windows, ou /proc/meminfo. None se não der pra saber."""
    try:
        import psutil  # type: ignore
        m = psutil.virtual_memory()
        return {"total": m.total / 1024 ** 3, "livre": m.available / 1024 ** 3}
    except Exception:  # noqa: BLE001
        pass
    if os.name == "nt":
        try:
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = _MS()
            ms.dwLength = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                return {"total": ms.ullTotalPhys / 1024 ** 3, "livre": ms.ullAvailPhys / 1024 ** 3}
        except Exception:  # noqa: BLE001
            return None
        return None
    try:
        info = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for linha in f:
                k, v = linha.split(":", 1)
                info[k] = float(v.split()[0]) / 1024 ** 2
        return {"total": info["MemTotal"], "livre": info.get("MemAvailable", info.get("MemFree", 0.0))}
    except Exception:  # noqa: BLE001
        return None


def escolher(engine: str, modo: str = "1", cpu: bool = False, caracteres: int = 0,
             vram_fn: Optional[Callable[[], Optional[Dict[str, float]]]] = None,
             ram_fn: Optional[Callable[[], Optional[Dict[str, float]]]] = None) -> Tuple[int, str]:
    """(quantas instâncias, por quê). modo "1" = ⚡ geração rápida DESLIGADA; "auto" ou "2"–"4" = ligada."""
    import fila_voz
    modo = str(modo or "1")
    if modo not in MODOS or modo == "1":
        return 1, "geração rápida desligada: 1 instância do motor"
    if caracteres < TEXTO_MINIMO:
        return 1, "texto curto: 1 instância (outra cópia do modelo custaria mais que o ganho)"
    teto_texto = max(1, caracteres // BLOCO_MIN)
    pedido = MAX_AUTO if modo == "auto" else int(modo)
    limites: List[Tuple[int, str]] = [(pedido, "automático: até 3" if modo == "auto" else f"você pediu {pedido}"),
                                      (teto_texto, "tamanho do texto")]
    # 🧠 RAM: todo motor carrega o modelo na memória do PC
    ram = (ram_fn or ler_ram)()
    if ram:
        por = RAM_GB.get(engine, 3.0)
        cabe = int(max(0.0, ram["livre"] - RAM_FOLGA) // por)
        limites.append((max(1, cabe), f"RAM: {ram['livre']:.1f} GB livres de {ram['total']:.0f} GB, ~{por:g} GB por cópia"))
    no_pod = fila_voz._no_pod(engine)  # 🖥️ gerando no pod: nem RAM nem VRAM deste PC
    if no_pod:
        limites = [x for x in limites if not x[1].startswith("RAM:")]
        limites.append((2, "no pod: o servidor gera um pedido por vez, 2 cópias só adiantam o envio"))
    usa_gpu = engine in MOTORES_GPU and not cpu and not no_pod
    if usa_gpu:
        v = (vram_fn or fila_voz.ler_vram)()
        if not v:
            limites.append((1, "sem placa NVIDIA detectada (o motor roda na CPU)"))
            usa_gpu = False
        else:
            por = fila_voz.VRAM_GB.get(engine, 3.5)
            cabe = int(max(0.0, v["livre"] - 0.8) // por)
            limites.append((max(1, cabe), f"VRAM: {v['livre']:.1f} GB livres na {v.get('nome') or 'placa'}, ~{por:g} GB por cópia"))
    if engine == "fish_s2":
        limites.append((2, "o servidor do Fish atende 2 pedidos bem; mais que isso ele enfileira"))
    elif not usa_gpu and not no_pod:
        nucleos = os.cpu_count() or 2
        limites.append((max(1, nucleos // 4), f"CPU: {nucleos} núcleos (na CPU cada cópia precisa de ~4)"))
    n, motivo = min(limites, key=lambda x: x[0])
    n = max(1, min(MAX_INSTANCIAS, n))
    return n, f"geração rápida: {n} instância(s) do motor — limite: {motivo}"


# ------------------------------------------------------------------ cortar o texto em blocos
_FRASE = re.compile(r"(?<=[.!?…])\s+")


def dividir_blocos(texto: str, instancias: int) -> List[str]:
    """Blocos na ordem, cortados entre parágrafos/frases (~3 blocos por instância, pra todas terminarem juntas)."""
    texto = str(texto or "").strip()
    if instancias <= 1 or len(texto) < BLOCO_MIN * 2:
        return [texto] if texto else []
    alvo = int(max(BLOCO_MIN, min(BLOCO_MAX, len(texto) / (instancias * 3))))
    pedacos: List[Tuple[str, bool]] = []  # (texto, começa parágrafo novo)
    for par in re.split(r"\n\s*\n", texto):
        par = par.strip()
        if not par:
            continue
        if len(par) <= alvo * 1.4:
            pedacos.append((par, True))
            continue
        primeira = True
        for fr in _FRASE.split(par):
            if fr.strip():
                pedacos.append((fr.strip(), primeira))
                primeira = False
    blocos: List[str] = []
    atual = ""
    for txt, novo_par in pedacos:
        junta = ("\n\n" if novo_par else " ") if atual else ""
        if atual and len(atual) + len(junta) + len(txt) > alvo:
            blocos.append(atual)
            atual = txt
        else:
            atual += junta + txt
    if atual:
        if blocos and len(atual) < BLOCO_MIN // 2:  # sobrinha: junta no último
            blocos[-1] += "\n\n" + atual
        else:
            blocos.append(atual)
    return blocos


# ------------------------------------------------------------------ gerar
def _juntar(arquivos: List[str], saida: str) -> None:
    if len(arquivos) == 1:
        shutil.copy(arquivos[0], saida)
        return
    taxa = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate",
                           "-of", "csv=p=0", arquivos[0]], capture_output=True, text=True, timeout=30).stdout.strip() or "24000"
    entradas: List[str] = []
    for a in arquivos:
        entradas += ["-i", a]
    filtro = "".join(f"[{i}:a]aresample={taxa},aformat=channel_layouts=mono[a{i}];" for i in range(len(arquivos)))
    filtro += "".join(f"[a{i}]" for i in range(len(arquivos))) + f"concat=n={len(arquivos)}:v=0:a=1[out]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + entradas + ["-filter_complex", filtro, "-map", "[out]",
                    "-c:a", "pcm_s16le", saida], check=True, capture_output=True, timeout=3600)


def gerar_partes(engine: str, textos: List[str], pasta: str, kwargs: Dict[str, Any], instancias: int,
                 log: Callable[[str], None] = lambda m: None, prefixo: str = "parte") -> List[Optional[str]]:
    """Gera cada texto de `textos` (já limpo pro TTS) num .wav próprio, com `instancias` instâncias do motor dividindo
    os BLOCOS de todos eles. Devolve o caminho de cada parte (None pra texto vazio). Erro → VoiceGeneratorError."""
    from tts.voice_generator import VoiceGeneratorError, gerar_audio_isolado_lote, gerar_audio_isolado_paralelo
    os.makedirs(pasta, exist_ok=True)
    itens: List[Tuple[str, str, str, Dict[str, Any]]] = []
    dono: List[int] = []
    for k, t in enumerate(textos):
        for j, bloco in enumerate(dividir_blocos(t, instancias) if re.search(r"\w", t or "") else []):
            itens.append((engine, bloco, os.path.join(pasta, f"{prefixo}_{k:03d}_{j:03d}.wav"), kwargs))
            dono.append(k)
    if not itens:
        raise VoiceGeneratorError("Texto vazio — nada pra narrar.")
    n = max(1, min(instancias, len(itens)))
    log(f"⚡ {n} instância(s) do motor em paralelo · {len(itens)} bloco(s) de texto.")
    feitos = {"n": 0}

    def prog(i: int, erro: Optional[str], inst: int) -> None:
        feitos["n"] += 1
        log(f"  bloco {i + 1}/{len(itens)} " + (f"⚠ {erro[:160]}" if erro else "pronto") + f" (instância {inst}) · {feitos['n']}/{len(itens)}")
    erros = gerar_audio_isolado_paralelo(itens, n, on_progresso=prog)
    if erros:  # 2ª chance numa instância só (ex.: faltou VRAM com várias juntas)
        log(f"↻ {len(erros)} bloco(s) falharam — gerando de novo numa instância só…")
        idx = sorted(erros)
        erros2 = gerar_audio_isolado_lote([itens[i] for i in idx])
        erros = {idx[j]: e for j, e in erros2.items()}
        if erros:
            raise VoiceGeneratorError("Falhou ao gerar: " + "; ".join(f"bloco {i + 1}: {e}" for i, e in sorted(erros.items()))[:800])
    saidas: List[Optional[str]] = []
    for k in range(len(textos)):
        arqs = [itens[i][2] for i in range(len(itens)) if dono[i] == k]
        if not arqs:
            saidas.append(None)
            continue
        destino = os.path.join(pasta, f"{prefixo}_{k:03d}.wav")
        _juntar(arqs, destino)
        saidas.append(destino)
    return saidas


def gerar_texto(engine: str, texto: str, saida: str, kwargs: Dict[str, Any], instancias: int,
                log: Callable[[str], None] = lambda m: None) -> str:
    """Um texto → um .wav, com várias instâncias."""
    pasta = os.path.splitext(saida)[0] + "_blocos"
    shutil.rmtree(pasta, ignore_errors=True)
    try:
        arq = gerar_partes(engine, [texto], pasta, kwargs, instancias, log)[0]
        shutil.move(arq, saida)
        return saida
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def modo_salvo() -> str:
    """"1" (padrão) = ⚡ geração rápida desligada."""
    try:
        from site_config import load_site_config
        m = str(load_site_config().get("voz_instancias") or "1")
        return m if m in MODOS else "1"
    except Exception:  # noqa: BLE001
        return "1"


def recursos() -> Dict[str, Any]:
    """O que o PC tem agora (pra mostrar na tela)."""
    import fila_voz
    return {"ram": ler_ram(), "vram": fila_voz.ler_vram(), "nucleos": os.cpu_count() or 0, "aviso": AVISO}
