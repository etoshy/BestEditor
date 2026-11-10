"""
voice_generator.py
====================

Gerador de voz LOCAL com três motores diferentes, escolhíveis por nome —
`"piper"`, `"xtts"` ou `"kokoro"`. Você escolhe o motor e a voz, manda o
texto, e ele devolve um `.wav` já com entonação/prosódia do modelo
escolhido. Cada motor baixa os próprios arquivos de modelo sozinho, na
primeira vez que uma voz dele é usada — não precisa preparar nada antes.

Motores
-------
- **"piper"** (Piper TTS — projeto OHF Voice/rhasspy): o mais leve dos
  três, roda bem até só em CPU. Cada voz é um arquivo `.onnx` pequeno
  (alguns MB a ~60MB), baixado do repositório `rhasspy/piper-voices` no
  Hugging Face. Boa entonação para um modelo desse tamanho, mas é o que
  menos varia prosódia entre frases.
  Instalação: `pip install piper-tts`

- **"xtts"** (Coqui ⓍTTS v2, mantido hoje pelo fork `idiap/coqui-ai-TTS`):
  o mais pesado e o mais expressivo — multi-idioma, com CLONAGEM DE VOZ
  (dá pra mandar um áudio de referência de alguém falando ~6-10s e ele
  imita aquela voz) ou usar uma das vozes prontas que já vêm no modelo.
  Precisa de MUITO mais recursos que os outros dois; se tiver GPU, use —
  em CPU a geração é bem mais lenta. Modelo pesa alguns GB e baixa
  sozinho no primeiro uso (fica em `~/.local/share/tts`).
  Instalação: `pip install coqui-tts torch torchaudio`
  (⚠️ note o nome do pacote: é `coqui-tts`, não `TTS` — o pacote `TTS`
  original no PyPI é o repositório antigo da Coqui AI, que fechou em
  2024 e não recebe mais atualizações; o fork é o caminho oficial hoje,
  mas continua importável como `from TTS.api import TTS`, sem mudar
  nada no código abaixo.)
  Licença do modelo: Coqui Public Model License (CPML) — dá uma olhada
  nela antes de usar em algo comercial.

- **"kokoro"** (Kokoro-82M, via `kokoro-onnx`): equilíbrio entre os dois
  de cima — pequeno (82M parâmetros, ~300MB o modelo completo), rápido,
  com uma boa variedade de vozes prontas (inclusive DUAS vozes femininas
  e masculinas em português do Brasil: `pf_dora`, `pm_alex`, `pm_santa`),
  mas sem clonagem de voz. Os dois arquivos do modelo (`kokoro-v1.0.onnx`
  + `voices-v1.0.bin`) baixam sozinhos do GitHub Releases do projeto na
  primeira vez.
  Instalação: `pip install kokoro-onnx soundfile`

Uso via GPU
-----------
Nenhum dos três PRECISA de GPU — todos funcionam em CPU. Mas se houver
uma GPU NVIDIA disponível, usar ela deixa a geração bem mais rápida
(principalmente o XTTS, que é o mais pesado dos três):

- Piper e Kokoro usam onnxruntime por baixo dos panos: instale
  `onnxruntime-gpu` (em vez do `onnxruntime` comum, ou junto — o pacote
  GPU inclui os dois provedores) e a GPU passa a ser usada sozinha,
  sem precisar mudar nada no código. `onnx_gpu_available()` abaixo
  confere isso.
- XTTS usa PyTorch: instale `torch`/`torchaudio` com suporte a CUDA
  (ver https://pytorch.org/get-started/locally/ pra montar o comando
  certo pra sua versão de CUDA) e ele já roda na GPU sozinho.
  `torch_gpu_available()` abaixo confere isso.

Por padrão, todas as funções de síntese abaixo detectam sozinhas se dá
pra usar GPU (`use_gpu=None`, o padrão, significa "detecta e usa se
tiver"); passe `use_gpu=False` pra forçar CPU mesmo com GPU disponível.

Uso
----
    from voice_generator import gerar_audio, gpu_status

    print(gpu_status())  # {'onnx_gpu (piper/kokoro)': True, 'torch_gpu (xtts)': False, ...}

    gerar_audio("piper", "Olá, isso é um teste.", "saida.wav",
                nome_voz="pt_BR-faber-medium")

    gerar_audio("kokoro", "Olá, isso é um teste.", "saida.wav",
                voz="pf_dora")

    gerar_audio("xtts", "Olá, isso é um teste.", "saida.wav",
                idioma="pt", speaker_wav="minha_voz_referencia.wav")
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
import uuid
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(_DIR, "models")
PIPER_MODELS_DIR = os.path.join(MODELS_DIR, "piper")
KOKORO_MODELS_DIR = os.path.join(MODELS_DIR, "kokoro")


class VoiceGeneratorError(Exception):
    """Erro genérico (motor não instalado, download falhou, voz inválida etc.)."""


# ============================================================ #
# FFmpeg / torchcodec (Windows) — desde o Python 3.8, ctypes e
# extensões não usam mais o PATH do processo pra achar DLLs de
# dependência (mudança de segurança). Isso faz o torchcodec (usado
# por baixo dos panos pelo torchaudio/coqui-tts pra ler arquivos de
# áudio, incluindo o speaker_wav do XTTS) não achar as DLLs do
# FFmpeg mesmo com `ffmpeg` funcionando normalmente no terminal.
# `os.add_dll_directory()` resolve isso registrando a pasta pro
# PROCESSO Python atual — precisa ser chamado antes de qualquer
# carregamento de biblioteca que dependa do FFmpeg.
# ============================================================ #

_ffmpeg_dll_dir_registered = False


def ensure_ffmpeg_dll_directory() -> Optional[str]:
    """No Windows, localiza o `ffmpeg.exe` no PATH e registra a pasta
    dele com `os.add_dll_directory()`, pra bibliotecas como o
    torchcodec conseguirem achar as DLLs do FFmpeg (avcodec-*.dll
    etc.) em tempo de execução. Idempotente — seguro chamar várias
    vezes. Não faz nada em Linux/macOS ou se o FFmpeg não for
    encontrado. Devolve o caminho registrado (ou None).
    """
    global _ffmpeg_dll_dir_registered
    if _ffmpeg_dll_dir_registered:
        return None
    if not hasattr(os, "add_dll_directory"):  # só existe no Windows, Python 3.8+
        return None

    ffmpeg_exe = shutil.which("ffmpeg")
    if not ffmpeg_exe:
        return None

    ffmpeg_bin_dir = os.path.dirname(os.path.abspath(ffmpeg_exe))
    try:
        os.add_dll_directory(ffmpeg_bin_dir)
    except (OSError, FileNotFoundError):
        return None

    _ffmpeg_dll_dir_registered = True
    return ffmpeg_bin_dir


# ============================================================ #
# Detecção de GPU — cada motor usa um runtime diferente, então
# "tem GPU" é checado de um jeito diferente pra cada um.
# ============================================================ #

def onnx_gpu_available() -> bool:
    """True se o onnxruntime enxergar uma GPU (CUDAExecutionProvider) —
    usado pelo Piper e pelo Kokoro. Precisa do pacote `onnxruntime-gpu`
    instalado (o `onnxruntime` comum, CPU-only, nunca devolve True aqui).
    """
    try:
        import onnxruntime as ort
    except ImportError:
        return False
    try:
        return "CUDAExecutionProvider" in ort.get_available_providers()
    except Exception:  # noqa: BLE001
        return False


def torch_gpu_available() -> bool:
    """True se o PyTorch enxergar uma GPU CUDA — usado pelo XTTS."""
    try:
        import torch
    except ImportError:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


def gpu_status() -> Dict[str, bool]:
    """Resumo rápido do que está disponível — útil pra mostrar na UI
    ('usando GPU' / 'usando CPU') antes mesmo de gerar qualquer áudio.
    """
    return {
        "onnx_gpu (piper/kokoro)": onnx_gpu_available(),
        "torch_gpu (xtts)": torch_gpu_available(),
    }


def detectar_gpu_nvidia() -> List[str]:
    """Detecta se existe uma GPU NVIDIA de verdade na máquina — SEM
    depender de torch/onnxruntime nem de nenhuma delas estar instalada
    corretamente com suporte a CUDA. Usa o `nvidia-smi` (instalado
    junto com o driver da NVIDIA, funciona independente de qual
    framework Python você tem) — se o driver estiver instalado, isso
    funciona mesmo que o PyTorch/onnxruntime instalados sejam a versão
    CPU-only. Devolve a lista de nomes das GPUs encontradas (vazia se
    não achar nenhuma ou se `nvidia-smi` não existir no PATH).
    """
    try:
        resultado = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        if resultado.returncode != 0:
            return []
        return [linha.strip() for linha in resultado.stdout.splitlines() if linha.strip()]
    except Exception:  # noqa: BLE001
        return []


def diagnosticar_gpu() -> Dict[str, Any]:
    """Diagnóstico completo de GPU — pensado pro caso mais comum de
    dúvida ("tenho placa de vídeo mas o XTTS/Piper/Kokoro não estão
    usando ela"): a causa quase sempre é que o `torch`/`onnxruntime`
    instalados são a build CPU-ONLY (o `pip install torch` "pelado",
    sem indicar o índice de pacotes certo, instala essa build por
    padrão em muita instalação), não que falte GPU de verdade.

    Devolve um dict com cada camada checada separadamente (hardware,
    pacote instalado, pacote COM suporte a CUDA, CUDA disponível em
    tempo de execução) pra dar pra apontar EXATAMENTE onde está o
    problema, em vez de só dizer "GPU: não".
    """
    gpus_nvidia = detectar_gpu_nvidia()
    tem_gpu_nvidia = len(gpus_nvidia) > 0

    # --- PyTorch (usado pelo XTTS) ---
    torch_instalado = False
    torch_build_tem_cuda = False
    torch_versao = None
    torch_versao_cuda_do_build = None
    try:
        import torch
        torch_instalado = True
        torch_versao = getattr(torch, "__version__", None)
        torch_versao_cuda_do_build = getattr(getattr(torch, "version", None), "cuda", None)
        torch_build_tem_cuda = torch_versao_cuda_do_build is not None
    except ImportError:
        pass
    torch_cuda_runtime_ok = torch_gpu_available()

    # --- onnxruntime (usado pelo Piper e pelo Kokoro) ---
    onnx_instalado = False
    onnx_eh_build_gpu = False
    try:
        import onnxruntime as ort
        onnx_instalado = True
        # o pacote `onnxruntime-gpu` registra o provider mesmo sem GPU
        # disponível em tempo de execução -- então "a build tem CUDA"
        # é checado pelo NOME do provider aparecer na lista de
        # providers COMPILADOS, não só nos disponíveis agora.
        onnx_eh_build_gpu = "CUDAExecutionProvider" in ort.get_available_providers()
    except ImportError:
        pass

    # --- monta o diagnóstico em português, focado em AÇÃO ---
    linhas: List[str] = []
    if not tem_gpu_nvidia:
        linhas.append(
            "Não encontrei nenhuma GPU NVIDIA nesta máquina (via nvidia-smi) — só GPUs NVIDIA são "
            "suportadas pelos três motores. Se você TEM uma GPU NVIDIA e mesmo assim isso não "
            "apareceu, o driver da NVIDIA pode não estar instalado/atualizado."
        )
    else:
        linhas.append(f"GPU(s) NVIDIA detectada(s): {', '.join(gpus_nvidia)}.")
        if not torch_instalado:
            linhas.append("XTTS: PyTorch não está instalado (pip install coqui-tts torch torchaudio).")
        elif not torch_build_tem_cuda:
            linhas.append(
                f"XTTS: o PyTorch instalado (versão {torch_versao}) é a build CPU-ONLY, sem suporte "
                "a CUDA nenhum — é essa a causa mais comum de 'tenho GPU mas não está sendo usada'. "
                "Resolve com: pip uninstall torch torchaudio -y && pip install torch torchaudio "
                "--index-url https://download.pytorch.org/whl/cu121 (troque cu121 pela versão de CUDA "
                "do seu driver — confira em https://pytorch.org/get-started/locally/). Esse mesmo "
                "PyTorch também é usado pela transcrição (Whisper) — corrigir isso acelera as duas coisas."
            )
        elif not torch_cuda_runtime_ok:
            linhas.append(
                f"XTTS: o PyTorch instalado JÁ tem suporte a CUDA (build cu{torch_versao_cuda_do_build}), "
                "mas não conseguiu enxergar a GPU em tempo de execução — confira se o driver da NVIDIA "
                "está atualizado e se a versão de CUDA do driver é compatível com essa build do PyTorch."
            )
        else:
            linhas.append("XTTS: usando a GPU normalmente. ✅")

        if not onnx_instalado:
            linhas.append("Piper/Kokoro: onnxruntime não está instalado.")
        elif not onnx_eh_build_gpu:
            linhas.append(
                "Piper/Kokoro: o pacote instalado é o `onnxruntime` comum (CPU-only) — troque pelo "
                "`onnxruntime-gpu`: pip uninstall onnxruntime -y && pip install onnxruntime-gpu"
            )
        else:
            linhas.append("Piper/Kokoro: usando a GPU normalmente. ✅")

    return {
        "gpu_nvidia_detectada": tem_gpu_nvidia,
        "nomes_gpu": gpus_nvidia,
        "torch_instalado": torch_instalado,
        "torch_versao": torch_versao,
        "torch_build_tem_cuda": torch_build_tem_cuda,
        "torch_cuda_runtime_ok": torch_cuda_runtime_ok,
        "onnx_instalado": onnx_instalado,
        "onnx_eh_build_gpu": onnx_eh_build_gpu,
        "diagnostico": "\n".join(linhas),
    }


# ============================================================ #
# PIPER
# ============================================================ #

# Um punhado de vozes conhecidas/testadas pra aparecer como sugestão na
# UI — a lista COMPLETA de vozes (várias dezenas de idiomas) está em
# https://rhasspy.github.io/piper-samples/ ; qualquer nome de lá
# funciona em `piper_synthesize(nome_voz=...)`, mesmo não estando nesta
# lista (ela baixa sozinha do Hugging Face na hora).
PIPER_VOZES_SUGERIDAS: Dict[str, str] = {
    "pt_BR-faber-medium": "Português (Brasil), masculina, qualidade média",
    "pt_BR-edresson-low": "Português (Brasil), masculina, qualidade baixa (mais rápida de gerar)",
    "en_US-lessac-medium": "Inglês (EUA), neutra, qualidade média",
    "en_US-amy-medium": "Inglês (EUA), feminina, qualidade média",
    "en_GB-alan-medium": "Inglês (Reino Unido), masculina, qualidade média",
    "es_ES-davefx-medium": "Espanhol, masculina, qualidade média",
}


# ============================================================ #
# Catálogo de vozes do Piper — busca/download sob demanda
# ============================================================ #
# O Piper tem CENTENAS de vozes prontas (dezenas de idiomas, várias
# qualidades cada) hospedadas no repositório oficial do Hugging Face —
# `PIPER_VOZES_SUGERIDAS` acima é só um punhado curado pra aparecer
# direto na interface. As funções abaixo buscam o catálogo COMPLETO de
# verdade (o mesmo `voices.json` que o `piper-tts` oficial usa),
# guardam em cache local (não precisa baixar de novo toda hora), e
# deixam procurar por idioma/nome antes de decidir qual baixar.

PIPER_VOICES_JSON_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json?download=true"
_PIPER_CATALOG_CACHE_FILE = os.path.join(PIPER_MODELS_DIR, "_catalogo_vozes.json")
_piper_catalog_memoria: Dict[str, Any] = {}  # cache em memória (1x por processo)


def piper_fetch_catalog(forcar_atualizacao: bool = False) -> Dict[str, Any]:
    """Baixa (ou reaproveita do cache) o catálogo COMPLETO de vozes do
    Piper — um dict grande, `{nome_da_voz: {...metadados...}}`, direto
    do repositório oficial. Guarda em disco (`_PIPER_CATALOG_CACHE_FILE`)
    pra não precisar baixar de novo toda vez que o processo reinicia —
    só baixa de novo se o cache não existir ainda, ou se
    `forcar_atualizacao=True`.
    """
    if not forcar_atualizacao and _piper_catalog_memoria.get("dados"):
        return _piper_catalog_memoria["dados"]

    if not forcar_atualizacao and os.path.exists(_PIPER_CATALOG_CACHE_FILE):
        try:
            with open(_PIPER_CATALOG_CACHE_FILE, "r", encoding="utf-8") as f:
                dados = json.load(f)
            _piper_catalog_memoria["dados"] = dados
            return dados
        except Exception:  # noqa: BLE001
            pass  # cache corrompido -- baixa de novo

    try:
        import requests
        resp = requests.get(PIPER_VOICES_JSON_URL, timeout=30)
        resp.raise_for_status()
        dados = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise VoiceGeneratorError(
            f"Não consegui baixar o catálogo de vozes do Piper (precisa de internet na primeira "
            f"vez). Erro original: {exc}"
        ) from exc

    os.makedirs(PIPER_MODELS_DIR, exist_ok=True)
    try:
        with open(_PIPER_CATALOG_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(dados, f)
    except Exception:  # noqa: BLE001
        pass  # não crítico -- só perde o cache em disco, ainda funciona
    _piper_catalog_memoria["dados"] = dados
    return dados


def piper_search_voices(
    busca: str = "", idioma: str = "", qualidade: str = "", max_resultados: int = 50,
) -> List[Dict[str, Any]]:
    """Procura no catálogo completo do Piper por `busca` (bate contra o
    nome da voz, o código/nome do idioma e o país — sem diferenciar
    maiúsculas/acentos) e opcionalmente filtra por `idioma` (prefixo do
    código, ex: "pt" pega "pt_BR" e "pt_PT") e/ou `qualidade` exata
    ("x_low"/"low"/"medium"/"high"). Devolve uma lista enxuta (sem os
    detalhes pesados como speaker_id_map/hashes de arquivo) — cada item
    já pronto pra mostrar na UI e pra usar direto em `nome_voz=`.
    """
    catalogo = piper_fetch_catalog()

    def normaliza(s: str) -> str:
        import unicodedata
        s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
        return s.lower().strip()

    busca_norm = normaliza(busca)
    idioma_norm = normaliza(idioma)
    qualidade_norm = normaliza(qualidade)

    resultados = []
    for chave, info in catalogo.items():
        lang = info.get("language", {})
        if idioma_norm and not normaliza(lang.get("code", "")).startswith(idioma_norm):
            continue
        if qualidade_norm and normaliza(info.get("quality", "")) != qualidade_norm:
            continue
        if busca_norm:
            campos_busca = " ".join([
                chave, info.get("name", ""), lang.get("code", ""),
                lang.get("name_english", ""), lang.get("country_english", ""),
            ])
            if busca_norm not in normaliza(campos_busca):
                continue

        tamanho_bytes = 0
        for caminho, meta in (info.get("files") or {}).items():
            if caminho.endswith(".onnx"):
                tamanho_bytes = meta.get("size_bytes", 0)
                break

        resultados.append({
            "key": chave,
            "nome": info.get("name", chave),
            "idioma_codigo": lang.get("code", ""),
            "idioma_nome": lang.get("name_english", ""),
            "pais": lang.get("country_english", ""),
            "qualidade": info.get("quality", ""),
            "num_falantes": info.get("num_speakers", 1),
            "tamanho_mb": round(tamanho_bytes / (1024 * 1024), 1) if tamanho_bytes else None,
        })
        if len(resultados) >= max_resultados:
            break

    resultados.sort(key=lambda r: (r["idioma_codigo"], r["nome"], r["qualidade"]))
    return resultados


def piper_download_voice_now(nome_voz: str, models_dir: str = PIPER_MODELS_DIR) -> Dict[str, Any]:
    """Baixa a voz `nome_voz` AGORA (sem gerar áudio nenhum) — útil pra
    um botão de "baixar essa voz" na busca do catálogo, deixando ela já
    pronta pra próxima geração não ter que esperar o download. Devolve
    um resumo com o tamanho final em disco.
    """
    onnx_path, config_path = piper_ensure_voice(nome_voz, models_dir)
    tamanho_bytes = os.path.getsize(onnx_path) if os.path.exists(onnx_path) else 0
    return {
        "nome_voz": nome_voz, "onnx_path": onnx_path, "config_path": config_path,
        "tamanho_mb": round(tamanho_bytes / (1024 * 1024), 1),
    }


def piper_ensure_voice(nome_voz: str, models_dir: str = PIPER_MODELS_DIR) -> Tuple[str, str]:
    """Garante que os arquivos `<nome_voz>.onnx` e `<nome_voz>.onnx.json`
    existem em `models_dir`, baixando do Hugging Face
    (`rhasspy/piper-voices`) se ainda não existirem. Devolve os dois
    caminhos prontos pra passar pro `PiperVoice.load()`.
    """
    os.makedirs(models_dir, exist_ok=True)
    onnx_path = os.path.join(models_dir, f"{nome_voz}.onnx")
    config_path = onnx_path + ".json"

    if os.path.exists(onnx_path) and os.path.exists(config_path):
        return onnx_path, config_path

    try:
        from piper.download_voices import download_voice
    except ImportError as exc:
        raise VoiceGeneratorError(
            "Piper TTS não está instalado. Rode: pip install piper-tts"
        ) from exc

    try:
        # A função download_voice() de algumas versões do piper-tts faz
        # aritmética de caminho (`pasta / arquivo`) por dentro, o que só
        # funciona se `download_dir` for um pathlib.Path — mandando uma
        # string comum, ela quebra com "unsupported operand type(s) for
        # /: 'str' and 'str'". Path() aqui resolve pros dois casos (some
        # versões aceitam string também, sem problema nenhum).
        download_voice(nome_voz, Path(models_dir))
    except Exception as exc:  # noqa: BLE001
        raise VoiceGeneratorError(
            f"Falha ao baixar a voz Piper {nome_voz!r} — confira se o nome está certo "
            f"(veja a lista completa em https://rhasspy.github.io/piper-samples/) e se "
            f"há internet disponível. Erro original: {exc}"
        ) from exc

    if not (os.path.exists(onnx_path) and os.path.exists(config_path)):
        raise VoiceGeneratorError(
            f"O download da voz Piper {nome_voz!r} terminou mas os arquivos esperados "
            f"não apareceram em {models_dir} — o nome da voz provavelmente está errado."
        )
    return onnx_path, config_path


def piper_synthesize(
    texto: str,
    output_path: str,
    nome_voz: str = "pt_BR-faber-medium",
    velocidade: float = 1.0,
    use_gpu: Optional[bool] = None,
    models_dir: str = PIPER_MODELS_DIR,
) -> str:
    """Gera um `.wav` com o Piper TTS. `velocidade`: 1.0 é o ritmo padrão
    da voz, >1.0 fala mais rápido, <1.0 mais devagar (convertido pro
    `length_scale` do Piper por baixo dos panos, que funciona ao
    contrário: menor length_scale = mais rápido).
    """
    try:
        from piper import PiperVoice
    except ImportError as exc:
        raise VoiceGeneratorError(
            "Piper TTS não está instalado. Rode: pip install piper-tts"
        ) from exc

    onnx_path, config_path = piper_ensure_voice(nome_voz, models_dir)

    if use_gpu is None:
        use_gpu = onnx_gpu_available()

    try:
        voice = PiperVoice.load(onnx_path, config_path=config_path, use_cuda=use_gpu)
    except Exception as exc:  # noqa: BLE001
        raise VoiceGeneratorError(f"Falha ao carregar a voz Piper {nome_voz!r}: {exc}") from exc

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    length_scale = (1.0 / velocidade) if velocidade and velocidade > 0 else None

    syn_config = None
    if length_scale is not None:
        try:
            from piper import SynthesisConfig
            syn_config = SynthesisConfig(length_scale=length_scale)
        except Exception:  # noqa: BLE001
            syn_config = None

    with wave.open(output_path, "wb") as wav_file:
        wav_file.setframerate(voice.config.sample_rate)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setnchannels(1)  # mono

        # A API do piper-tts mudou entre versões — na atual (piper1-gpl,
        # projeto mantido hoje pela Open Home Foundation), `.synthesize()`
        # virou um GERADOR que só devolve os pedaços de áudio (não escreve
        # em lugar nenhum sozinho), e quem escreve direto num wav_file é
        # `.synthesize_wav()`. Em versões mais antigas era o contrário
        # (`.synthesize()` escrevia direto). Se o código chama o método
        # errado pra versão instalada, nenhuma exceção acontece — ele só
        # devolve (ou cria, sem executar nada) um generator que nunca é
        # consumido, e o .wav sai com cabeçalho válido mas ZERO frames de
        # áudio (som "zerado"/mudo). Por isso cada tentativa abaixo
        # confere quantos FRAMES DE VERDADE foram escritos (`wav_file.tell()`)
        # em vez de só "não deu erro" — uma chamada que "funciona" sem
        # escrever nada (como cair sem querer no branch errado) não conta
        # como sucesso, e o código cai pra próxima tentativa.
        def _frames_escritos() -> int:
            return wav_file.tell()

        synthesized = False

        if hasattr(voice, "synthesize_wav"):
            antes = _frames_escritos()
            try:
                if syn_config is not None:
                    voice.synthesize_wav(texto, wav_file, syn_config=syn_config)
                else:
                    voice.synthesize_wav(texto, wav_file)
                synthesized = _frames_escritos() > antes
            except (TypeError, AttributeError):
                synthesized = False

        if not synthesized:
            # API antiga: `.synthesize()` escrevendo direto no wav_file.
            antes = _frames_escritos()
            try:
                if length_scale is not None:
                    voice.synthesize(texto, wav_file, length_scale=length_scale)
                else:
                    voice.synthesize(texto, wav_file)
                synthesized = _frames_escritos() > antes
            except (TypeError, AttributeError):
                synthesized = False

        if not synthesized:
            # Último recurso: `.synthesize()` como GERADOR (API atual sem
            # `.synthesize_wav()` disponível, ou as duas tentativas acima
            # "passaram" sem escrever nada de verdade) — escreve cada
            # pedaço manualmente.
            try:
                gerador = voice.synthesize(texto, syn_config=syn_config) if syn_config is not None else voice.synthesize(texto)
                escreveu_algo = False
                for pedaco in gerador:
                    dados = getattr(pedaco, "audio_int16_bytes", None)
                    if dados is None:
                        array = getattr(pedaco, "audio_int16_array", None)
                        dados = array.tobytes() if array is not None else None
                    if dados:
                        wav_file.writeframes(dados)
                        escreveu_algo = True
                synthesized = escreveu_algo
            except Exception:  # noqa: BLE001
                synthesized = False

    # Confere de verdade que o arquivo tem áudio, em vez de só confiar
    # que uma das chamadas acima "não deu erro" — é exatamente essa
    # checagem que teria pego o bug do áudio zerado antes de devolver
    # um arquivo quebrado pro resto do pipeline.
    with wave.open(output_path, "rb") as conferencia:
        se_tem_frames = conferencia.getnframes() > 0
    if not se_tem_frames:
        raise VoiceGeneratorError(
            f"O Piper gerou um arquivo de áudio VAZIO (sem nenhum frame) pra voz {nome_voz!r} "
            f"— isso costuma acontecer quando a versão do piper-tts instalada mudou a API e "
            f"nenhum dos métodos conhecidos (.synthesize_wav / .synthesize) bateu certo. Tente "
            f"`pip install -U piper-tts` pra pegar a versão mais recente."
        )

    return output_path


# ============================================================ #
# XTTS v2 (Coqui, fork idiap/coqui-ai-TTS)
# ============================================================ #

XTTS_MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"

# Idiomas suportados pelo XTTS v2 (17 no total) — usado só pra validação
# amigável antes de mandar pro modelo.
XTTS_IDIOMAS = {
    "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl",
    "cs", "ar", "zh-cn", "ja", "hu", "ko", "hi",
}

# Diferente do Piper, NÃO existe um catálogo único/pesquisável de
# checkpoints do XTTS — a comunidade publica fine-tunes espalhados em
# repositórios independentes no Hugging Face, cada um com seu próprio
# nome de arquivo e convenção. Isso aqui é só uma lista CURADA de
# alguns exemplos conhecidos (não é uma busca ao vivo, como a do
# Piper) — sirva de ponto de partida; qualquer outro checkpoint que
# você encontrar funciona do mesmo jeito via `xtts_load(model_path=...,
# config_path=...)` ou `xtts_download_checkpoint(repo_id=...)`.
XTTS_CHECKPOINTS_CONHECIDOS: Dict[str, Dict[str, str]] = {
    "padrao": {
        "label": "XTTS v2 padrão (oficial, multi-idioma) — o de sempre",
        "repo_id": "",  # usa o carregamento normal via nome do modelo, não repo_id
    },
    "hindi": {
        "label": "Fine-tune em hindi (Abhinay45/XTTS-Hindi-finetuned)",
        "repo_id": "Abhinay45/XTTS-Hindi-finetuned",
    },
    "chines": {
        "label": "Fine-tune em chinês/mandarim-Taiwan (sandy1990418/xtts-v2-chinese)",
        "repo_id": "sandy1990418/xtts-v2-chinese",
    },
}

_xtts_cache: Dict[str, Any] = {}  # cache_key -> instância TTS carregada
_torchaudio_patch_applied = False


def _patch_torchaudio_load_via_soundfile() -> None:
    """Segunda linha de defesa contra o problema do torchcodec no
    Windows (a primeira é `ensure_ffmpeg_dll_directory()` acima) —
    útil principalmente quando o FFmpeg instalado é a build "essentials"
    (um `.exe` autocontido, sem as DLLs separadas que o torchcodec
    procura) em vez da build "full-shared" que o torchcodec espera:
    nesse caso, registrar a pasta do FFmpeg com `add_dll_directory` não
    adianta, porque as DLLs simplesmente não existem lá.

    A correção: troca a função `torchaudio.load` por uma implementação
    via `soundfile` (biblioteca leve, sem depender de DLLs externas de
    FFmpeg/torchcodec) ANTES do XTTS carregar — daí não importa como
    ele tente carregar o áudio de referência por baixo dos panos,
    sempre passa pela nossa versão. Aplicado só uma vez por processo.
    """
    global _torchaudio_patch_applied
    if _torchaudio_patch_applied:
        return
    try:
        import numpy as np
        import soundfile as sf
        import torch
        import torchaudio

        def _carregar_audio_via_soundfile(
            caminho, frame_offset=0, num_frames=-1, normalize=True, channels_first=True, format=None, **kwargs
        ):
            dados, taxa_amostragem = sf.read(str(caminho), dtype="float32", always_2d=True)
            if num_frames is not None and num_frames > 0:
                dados = dados[frame_offset:frame_offset + num_frames]
            elif frame_offset:
                dados = dados[frame_offset:]
            forma_onda = torch.from_numpy(np.ascontiguousarray(dados.T if channels_first else dados))
            return forma_onda, taxa_amostragem

        torchaudio.load = _carregar_audio_via_soundfile
        _torchaudio_patch_applied = True
    except Exception:
        pass  # sem soundfile/torch(audio) compatíveis -- segue o fluxo normal


def xtts_download_checkpoint(repo_id: str, models_dir: Optional[str] = None) -> Tuple[str, str]:
    """Baixa um checkpoint customizado do XTTS a partir de um repositório
    do Hugging Face (`repo_id`, ex: "Abhinay45/XTTS-Hindi-finetuned") —
    os três arquivos que a maioria desses fine-tunes publica:
    `model.pth`, `config.json` e (se existir) `vocab.json`. Devolve
    `(model_path, config_path)`, prontos pra usar em
    `xtts_load(model_path=..., config_path=...)`.

    Cada repositório da comunidade usa uma convenção própria de nome
    de arquivo pro checkpoint (`model.pth` na maioria, mas alguns usam
    `best_model.pth` etc) — se o download do `model.pth` falhar,
    tenta `best_model.pth` como alternativa antes de desistir.
    """
    import requests

    pasta = os.path.join(models_dir or os.path.join(MODELS_DIR, "xtts_checkpoints"), repo_id.replace("/", "__"))
    os.makedirs(pasta, exist_ok=True)

    base_url = f"https://huggingface.co/{repo_id}/resolve/main/"
    model_path = os.path.join(pasta, "model.pth")
    config_path = os.path.join(pasta, "config.json")
    vocab_path = os.path.join(pasta, "vocab.json")

    def _baixa_se_faltar(nome_arquivo: str, destino: str, obrigatorio: bool) -> bool:
        if os.path.exists(destino):
            return True
        try:
            resp = requests.get(base_url + nome_arquivo, timeout=120, stream=True)
            if resp.status_code == 404:
                return False
            resp.raise_for_status()
            with open(destino, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
            return True
        except Exception as exc:  # noqa: BLE001
            if obrigatorio:
                raise VoiceGeneratorError(
                    f"Falha ao baixar {nome_arquivo!r} do repositório {repo_id!r}: {exc}"
                ) from exc
            return False

    if not _baixa_se_faltar("model.pth", model_path, obrigatorio=False):
        # convenção alternativa usada por alguns fine-tunes da comunidade
        if not _baixa_se_faltar("best_model.pth", model_path, obrigatorio=True):
            raise VoiceGeneratorError(
                f"Não encontrei 'model.pth' nem 'best_model.pth' no repositório {repo_id!r} — "
                f"confira o nome do arquivo do checkpoint na página do modelo no Hugging Face."
            )
    _baixa_se_faltar("config.json", config_path, obrigatorio=True)
    _baixa_se_faltar("vocab.json", vocab_path, obrigatorio=False)  # nem todo fine-tune publica um vocab próprio

    return model_path, config_path


def xtts_load(
    use_gpu: Optional[bool] = None,
    model_path: Optional[str] = None,
    config_path: Optional[str] = None,
):
    """Carrega (ou reaproveita, se já carregado com os mesmos
    parâmetros) o modelo XTTS v2. Sem `model_path`/`config_path`, usa o
    modelo oficial padrão (baixa sozinho na primeira vez, alguns GB,
    fica guardado em `~/.local/share/tts`). Com os dois preenchidos,
    carrega um CHECKPOINT CUSTOMIZADO em vez do padrão — veja
    `xtts_download_checkpoint()` pra baixar um fine-tune da comunidade
    a partir do Hugging Face.
    """
    # Duas defesas contra o torchcodec no Windows, aplicadas ANTES de
    # importar/usar qualquer coisa que dependa dele: primeiro tenta
    # achar as DLLs do FFmpeg (funciona se for a build "full-shared"),
    # e troca `torchaudio.load` por uma versão via soundfile por cima
    # (funciona mesmo se a build for a "essentials", sem DLLs separadas
    # — cobre o caso mais comum de instalação no Windows).
    ensure_ffmpeg_dll_directory()
    _patch_torchaudio_load_via_soundfile()

    try:
        from TTS.api import TTS
    except ImportError as exc:
        raise VoiceGeneratorError(
            "XTTS v2 não está instalado. Rode: pip install coqui-tts torch torchaudio"
        ) from exc

    if use_gpu is None:
        use_gpu = torch_gpu_available()
    device = "cuda" if use_gpu else "cpu"

    cache_key = f"{model_path or XTTS_MODEL_NAME}:{device}"
    if cache_key in _xtts_cache:
        return _xtts_cache[cache_key]

    try:
        if model_path and config_path:
            tts = TTS(model_path=model_path, config_path=config_path).to(device)
        else:
            tts = TTS(XTTS_MODEL_NAME).to(device)
    except Exception as exc:  # noqa: BLE001
        mensagem = str(exc)
        if "torchcodec" in mensagem.lower() or "libtorchcodec" in mensagem.lower():
            raise VoiceGeneratorError(
                "Falha ao carregar o XTTS v2 por causa do torchcodec (comum no Windows — "
                "o torchaudio exige DLLs específicas do FFmpeg que costumam faltar, "
                "principalmente se o FFmpeg instalado for a build \"essentials\" em vez da "
                "\"full-shared\"). Já tentamos contornar automaticamente e não funcionou nesse "
                "ambiente. Formas de resolver: (1) baixe a build \"full-shared\" do FFmpeg "
                "(ex: em https://www.gyan.dev/ffmpeg/builds/, a versão \"shared\") e garanta "
                "que ela está no PATH antes de qualquer outra instalação de FFmpeg; ou "
                "(2) rode `pip install \"torch==2.8.*\" \"torchaudio==2.8.*\"` (uma dupla mais "
                "antiga e estável que não depende do torchcodec). "
                f"Erro original: {exc}"
            ) from exc
        raise VoiceGeneratorError(f"Falha ao carregar/baixar o modelo XTTS v2: {exc}") from exc

    _xtts_cache[cache_key] = tts
    return tts


def xtts_list_speakers(
    use_gpu: Optional[bool] = None, model_path: Optional[str] = None, config_path: Optional[str] = None,
) -> List[str]:
    """Lista as vozes PRONTAS que já vêm com o modelo (sem precisar de
    áudio de referência) — lidas do próprio modelo carregado, não uma
    lista fixa aqui, pra nunca ficar desatualizada. Passe
    `model_path`/`config_path` pra listar as vozes de um checkpoint
    customizado em vez do padrão.
    """
    tts = xtts_load(use_gpu=use_gpu, model_path=model_path, config_path=config_path)
    return list(getattr(tts, "speakers", None) or [])


def _preparar_audio_referencia(caminho: str, duracao_max_segundos: float = 25.0) -> str:
    """Pré-processa o áudio de referência (clonagem de voz) ANTES de
    mandar pro XTTS: converte pro formato mais simples e compatível
    possível (WAV PCM 16-bit, mono, 22050Hz) e CORTA pros primeiros
    `duracao_max_segundos` segundos — via ffmpeg, que a esta altura já
    sabemos que funciona no ambiente, diferente do torchcodec.

    Por quê cortar: o XTTS v2 foi feito pra clonar voz a partir de uns
    6-20 segundos de referência — um áudio de vários MINUTOS não deixa
    o resultado melhor (o modelo só usa uma janela curta mesmo por
    baixo dos panos), só deixa TUDO mais lento e mais sujeito a esse
    tipo de erro de decodificação (mp3 grande = mais chance de esbarrar
    num trecho que o decodificador não gosta).

    Se o ffmpeg falhar por qualquer motivo, usa o arquivo original
    mesmo (melhor tentar com o original do que travar por causa só
    desse passo extra de segurança).
    """
    import subprocess
    import tempfile
    import uuid

    destino = os.path.join(tempfile.gettempdir(), f"_xtts_ref_{uuid.uuid4().hex[:8]}.wav")
    try:
        resultado = subprocess.run(
            ["ffmpeg", "-y", "-i", caminho, "-t", str(duracao_max_segundos),
             "-ac", "1", "-ar", "22050", "-c:a", "pcm_s16le", destino],
            capture_output=True, timeout=60,
        )
        if resultado.returncode == 0 and os.path.exists(destino):
            return destino
    except Exception:  # noqa: BLE001
        pass
    return caminho


# ============================================================ #
# Perfis de voz salvos (clonagem XTTS reutilizável) — grava o(s)
# áudio(s) de referência UMA vez, com um nome, e reusa em quantas
# gerações quiser sem precisar reenviar o arquivo — útil pra "treinar"
# (no sentido de CLONAR, não de treinar/ajustar pesos — ver nota
# abaixo) mais de uma voz e trocar entre elas.
#
# IMPORTANTE sobre "treinar com mais tempo de voz": o XTTS v2 não
# TREINA nada aqui — ele faz clonagem por CONDICIONAMENTO (lê um
# trechinho de referência e extrai as características da voz dali, na
# hora). Por isso um único áudio de MINUTOS não ajuda (só deixa mais
# lento) — mas o modelo aceita VÁRIOS áudios de referência ao mesmo
# tempo, sem custo de velocidade, e isso sim costuma melhorar a
# clonagem de verdade: 2-4 clipes curtos (5-15s cada) de frases
# DIFERENTES, com entonações diferentes, dão ao modelo uma amostra mais
# rica da voz do que um clipe único, por mais longo que seja. Por isso
# um perfil pode ter MAIS DE UM arquivo de áudio.
#
# (Treinar de verdade — ajustar os pesos do modelo com um fine-tune,
# tipo os que aparecem em XTTS_CHECKPOINTS_CONHECIDOS — é outra coisa
# bem mais pesada: precisa de GPU, horas de processamento e minutos ou
# horas de áudio transcrito. Não é isso que essa função faz.)
# ============================================================ #

VOICE_PROFILES_DIR = os.path.join(MODELS_DIR, "perfis_de_voz")

# Quantos clipes de referência um perfil aceita no máximo -- mais que
# isso não costuma ajudar (e deixa a clonagem mais lenta à toa).
MAX_CLIPES_POR_PERFIL = 5


def _duracao_audio_segundos(caminho: str) -> Optional[float]:
    import subprocess
    try:
        resultado = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", caminho],
            capture_output=True, text=True, timeout=15,
        )
        return float(resultado.stdout.strip())
    except Exception:  # noqa: BLE001
        return None


def dividir_audio_em_clipes(
    caminho: str, duracao_por_clipe: float = 10.0, quantidade: int = 4,
) -> List[str]:
    """Divide UM áudio (potencialmente longo) em até `quantidade`
    trechos de `duracao_por_clipe` segundos cada, espalhados pelo
    áudio inteiro (começo, meio, fim — pulando uma pequena margem nas
    pontas, que costuma ter silêncio/introdução) em vez de pegar só o
    começo. Pra clonagem de voz, alguns trechos curtos e VARIADOS
    tendem a representar melhor a voz da pessoa do que um clipe único
    mais longo — é a mesma ideia de mandar vários áudios separados,
    só que automática, a partir de UM arquivo só.

    Se o áudio já for curto (não sobra muito pra dividir), devolve ele
    mesmo, sem cortar nada. Devolve caminhos de arquivos TEMPORÁRIOS —
    quem chama é responsável por apagar depois de usar.
    """
    duracao_total = _duracao_audio_segundos(caminho)
    if not duracao_total or duracao_total <= duracao_por_clipe * 1.3:
        return [caminho]  # curto demais pra valer a pena dividir -- usa inteiro

    quantidade = max(1, min(quantidade, MAX_CLIPES_POR_PERFIL))
    margem = min(duracao_total * 0.05, 3.0)  # pula uma margenzinha do começo/fim
    inicio_util = margem
    fim_util = max(inicio_util + duracao_por_clipe, duracao_total - margem)
    janela_disponivel = fim_util - inicio_util

    if janela_disponivel <= duracao_por_clipe or quantidade == 1:
        pontos_inicio = [inicio_util]
    else:
        passo = (janela_disponivel - duracao_por_clipe) / (quantidade - 1)
        pontos_inicio = [inicio_util + i * passo for i in range(quantidade)]

    import subprocess
    import tempfile
    pasta_tmp = tempfile.mkdtemp(prefix="voz_dividida_")
    clipes = []
    for i, inicio in enumerate(pontos_inicio):
        destino = os.path.join(pasta_tmp, f"trecho_{i + 1:02d}.wav")
        resultado = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{inicio:.2f}", "-i", caminho, "-t", str(duracao_por_clipe),
             "-ac", "1", "-ar", "22050", "-c:a", "pcm_s16le", destino],
            capture_output=True, timeout=60,
        )
        if resultado.returncode == 0 and os.path.exists(destino):
            clipes.append(destino)

    return clipes or [caminho]  # se TUDO falhar, cai pro áudio original


def _nome_perfil_seguro(nome: str) -> str:
    nome = (nome or "").strip()
    if not nome:
        raise VoiceGeneratorError("Dê um nome pro perfil de voz (ex: \"minha_voz\", \"locutor_joao\").")
    seguro = "".join(c for c in nome if c.isalnum() or c in ("_", "-", " ")).strip()
    seguro = seguro.replace(" ", "_")
    if not seguro:
        raise VoiceGeneratorError(f"Nome de perfil inválido: {nome!r}.")
    return seguro


def _pasta_perfil(nome_seguro: str) -> str:
    return os.path.join(VOICE_PROFILES_DIR, nome_seguro)


def _arquivo_perfil_antigo(nome_seguro: str) -> str:
    """Perfis salvos ANTES desta função aceitar múltiplos áudios ficam
    como um `.wav` solto (`<nome>.wav`), não uma pasta — mantido pra
    compatibilidade: continuam funcionando normalmente, só não dá pra
    adicionar um segundo clipe a eles sem recriar o perfil."""
    return os.path.join(VOICE_PROFILES_DIR, f"{nome_seguro}.wav")


def salvar_perfil_de_voz(
    nome: str,
    caminhos_audio_origem,
    duracao_max_segundos: float = 25.0,
    dividir_audio_longo: bool = True,
) -> List[str]:
    """Processa um ou mais áudios de referência e salva como um PERFIL
    DE VOZ reutilizável, guardado com o `nome` dado. Devolve a lista de
    caminhos salvos.

    `caminhos_audio_origem`: um único caminho, ou uma lista de até
        `MAX_CLIPES_POR_PERFIL` (vários clipes separados que você já
        tem prontos).
    `dividir_audio_longo` (padrão True, só tem efeito com um ÚNICO
        caminho — não uma lista): em vez de só cortar os primeiros
        `duracao_max_segundos` segundos do áudio (que podem cair no
        meio de uma pausa, introdução etc — nem sempre é o trecho mais
        representativo da voz), DIVIDE automaticamente um áudio longo
        em vários trechos curtos espalhados por ele inteiro (começo,
        meio, fim) via `dividir_audio_em_clipes()`. Um áudio já curto
        não é dividido (processado como um clipe só, como sempre foi).
        Se você já mandar uma LISTA de arquivos, essa divisão automática
        não entra em ação — cada arquivo da lista é processado como
        está (você já escolheu os trechos, nesse caso).

    Pra clonar melhor, alguns trechos CURTOS (5-15s) e variados —
    vindos da divisão automática de um áudio longo, ou enviados à mão
    como uma lista — tendem a representar melhor a voz do que um único
    clipe, mesmo que mais longo. O XTTS usa todos os clipes do perfil
    juntos, sem ficar mais lento por isso.

    Depois de salvo, use com `xtts_synthesize(..., voice_profile=nome)`
    em vez de reenviar os áudios de referência toda vez.
    """
    eh_caminho_unico = isinstance(caminhos_audio_origem, str)
    caminhos = [caminhos_audio_origem] if eh_caminho_unico else list(caminhos_audio_origem)
    if not caminhos:
        raise VoiceGeneratorError("Mande pelo menos um áudio de referência pro perfil de voz.")
    if len(caminhos) > MAX_CLIPES_POR_PERFIL:
        raise VoiceGeneratorError(
            f"No máximo {MAX_CLIPES_POR_PERFIL} áudios por perfil (mais que isso não costuma "
            f"melhorar a clonagem, só deixa mais lento) — você mandou {len(caminhos)}."
        )
    for caminho in caminhos:
        if not os.path.exists(caminho):
            raise VoiceGeneratorError(f"Áudio de referência não encontrado: {caminho!r}")

    # Divide um ÚNICO áudio longo em vários trechos, em vez de só
    # cortar o começo -- só faz sentido quando NÃO veio uma lista já
    # escolhida à mão (aí quem mandou já decidiu os trechos).
    arquivos_temporarios = []
    if eh_caminho_unico and dividir_audio_longo:
        duracao_por_clipe = min(10.0, duracao_max_segundos)
        divididos = dividir_audio_em_clipes(caminhos[0], duracao_por_clipe=duracao_por_clipe)
        if len(divididos) > 1:
            caminhos = divididos
            arquivos_temporarios = divididos
            duracao_max_segundos = duracao_por_clipe  # os trechos já saíram do tamanho certo

    seguro = _nome_perfil_seguro(nome)
    pasta = _pasta_perfil(seguro)
    os.makedirs(pasta, exist_ok=True)

    import subprocess
    salvos = []
    try:
        for indice, caminho_origem in enumerate(caminhos, start=1):
            destino = os.path.join(pasta, f"ref_{indice:02d}.wav")
            resultado = subprocess.run(
                ["ffmpeg", "-y", "-i", caminho_origem, "-t", str(duracao_max_segundos),
                 "-ac", "1", "-ar", "22050", "-c:a", "pcm_s16le", destino],
                capture_output=True, timeout=60,
            )
            if resultado.returncode != 0 or not os.path.exists(destino):
                raise VoiceGeneratorError(
                    f"Não consegui processar o áudio {indice} de referência com o ffmpeg (voltou "
                    f"código {resultado.returncode}). Confira se o arquivo é um áudio válido e se o "
                    f"ffmpeg está instalado e no PATH."
                )
            salvos.append(destino)
    finally:
        # limpa os trechos temporários da divisão automática (se
        # houve) -- não são o resultado final, já foram copiados/
        # reconvertidos pra dentro da pasta do perfil acima.
        for tmp in arquivos_temporarios:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if arquivos_temporarios:
            try:
                os.rmdir(os.path.dirname(arquivos_temporarios[0]))
            except OSError:
                pass

    # remove um eventual perfil ANTIGO (arquivo solto) com o mesmo nome,
    # pra não ficar um .wav órfão duplicando o que agora é uma pasta.
    antigo = _arquivo_perfil_antigo(seguro)
    if os.path.exists(antigo):
        os.remove(antigo)

    return salvos


def listar_perfis_de_voz() -> List[str]:
    """Nomes de todos os perfis de voz salvos, em ordem alfabética —
    tanto os novos (uma pasta com 1+ áudios) quanto os antigos (um
    único .wav solto, de antes desta função aceitar vários)."""
    if not os.path.isdir(VOICE_PROFILES_DIR):
        return []
    nomes = set()
    for item in os.listdir(VOICE_PROFILES_DIR):
        caminho = os.path.join(VOICE_PROFILES_DIR, item)
        if os.path.isdir(caminho):
            nomes.add(item)
        elif item.lower().endswith(".wav"):
            nomes.add(os.path.splitext(item)[0])
    return sorted(nomes)


def caminho_perfil_de_voz(nome: str) -> List[str]:
    """Caminho(s) do(s) áudio(s) salvo(s) pra esse perfil, em ordem —
    sempre uma LISTA (com um item só, pros perfis antigos de um único
    áudio). O clipe ⭐ principal (`_principal.txt`) vem PRIMEIRO — é o
    único que o Chatterbox/Turbo/pod usam. Levanta erro claro (com a
    lista dos perfis que existem) se o nome não existir."""
    seguro = _nome_perfil_seguro(nome)
    pasta = _pasta_perfil(seguro)
    if os.path.isdir(pasta):
        arquivos = sorted(
            os.path.join(pasta, f) for f in os.listdir(pasta) if f.lower().endswith(".wav")
        )
        if arquivos:
            principal = _ler_principal(pasta)
            if principal:
                arquivos.sort(key=lambda a: os.path.basename(a) != principal)
            return arquivos
    antigo = _arquivo_perfil_antigo(seguro)
    if os.path.exists(antigo):
        return [antigo]

    existentes = listar_perfis_de_voz()
    raise VoiceGeneratorError(
        f"Não existe nenhum perfil de voz salvo com o nome {nome!r}. "
        f"Perfis disponíveis: {existentes or '(nenhum ainda — use salvar_perfil_de_voz() primeiro)'}"
    )


def excluir_perfil_de_voz(nome: str) -> None:
    seguro = _nome_perfil_seguro(nome)
    pasta = _pasta_perfil(seguro)
    if os.path.isdir(pasta):
        shutil.rmtree(pasta)
    antigo = _arquivo_perfil_antigo(seguro)
    if os.path.exists(antigo):
        os.remove(antigo)


# ------------------------------------------------------------------ ✂ clipe a clipe (v84_174)
# Somando os clipes que vão sendo ADICIONADOS (outro vídeo, outro áudio) — o envio de uma vez continua até
# MAX_CLIPES_POR_PERFIL. Mais que isso não melhora a voz: o Chatterbox usa só o clipe ⭐ principal (~10 s dele) e o
# XTTS ~30 s somando todos. Ter mais serve pra ESCOLHER o melhor e apagar os ruins.
MAX_CLIPES_TOTAL = 12
ARQ_PRINCIPAL = "_principal.txt"


def _ler_principal(pasta: str) -> str:
    try:
        with open(os.path.join(pasta, ARQ_PRINCIPAL), encoding="utf-8") as f:
            nome = f.read().strip()
    except OSError:
        return ""
    return nome if nome and os.path.isfile(os.path.join(pasta, nome)) else ""


def _pasta_do_perfil_existente(nome: str) -> str:
    """A pasta do perfil (o perfil antigo de um .wav solto vira pasta). Erro claro se não existir."""
    seguro = _nome_perfil_seguro(nome)
    pasta = _pasta_perfil(seguro)
    antigo = _arquivo_perfil_antigo(seguro)
    if not os.path.isdir(pasta) and os.path.isfile(antigo):
        os.makedirs(pasta, exist_ok=True)
        shutil.move(antigo, os.path.join(pasta, f"{seguro}.wav"))  # igual ao perfis_limpeza
    if not os.path.isdir(pasta):
        caminho_perfil_de_voz(nome)  # levanta o erro com a lista dos perfis que existem
    return pasta


def duracao_wav(caminho: str) -> float:
    """Duração (s) de um .wav do perfil — lida do cabeçalho (rápido), com o ffprobe de reserva."""
    import wave
    try:
        with wave.open(caminho, "rb") as w:
            return round(w.getnframes() / float(w.getframerate() or 1), 1)
    except Exception:  # noqa: BLE001
        return round(_duracao_audio_segundos(caminho) or 0.0, 1)


def adicionar_clipes_ao_perfil(
    nome: str,
    caminhos_audio_origem,
    duracao_max_segundos: float = 25.0,
    dividir_audio_longo: bool = True,
) -> List[str]:
    """➕ Junta mais áudio(s)/vídeo(s) num perfil que JÁ EXISTE, sem apagar os clipes que ele tem (o
    `salvar_perfil_de_voz` regrava do zero). Mesmo processamento: um áudio longo sozinho é dividido em trechos
    espalhados. Os novos entram com o próximo número livre (ref_06.wav…). Devolve só os caminhos novos."""
    eh_caminho_unico = isinstance(caminhos_audio_origem, str)
    caminhos = [caminhos_audio_origem] if eh_caminho_unico else list(caminhos_audio_origem)
    if not caminhos:
        raise VoiceGeneratorError("Mande pelo menos um áudio pra adicionar ao perfil.")
    for caminho in caminhos:
        if not os.path.exists(caminho):
            raise VoiceGeneratorError(f"Áudio de referência não encontrado: {caminho!r}")
    pasta = _pasta_do_perfil_existente(nome)
    atuais = caminho_perfil_de_voz(nome)

    temporarios: List[str] = []
    if eh_caminho_unico and dividir_audio_longo:
        por_clipe = min(10.0, duracao_max_segundos)
        divididos = dividir_audio_em_clipes(caminhos[0], duracao_por_clipe=por_clipe)
        if len(divididos) > 1:
            caminhos, temporarios, duracao_max_segundos = divididos, divididos, por_clipe
    try:
        if len(atuais) + len(caminhos) > MAX_CLIPES_TOTAL:
            raise VoiceGeneratorError(
                f"O perfil ficaria com {len(atuais) + len(caminhos)} clipes — o máximo é {MAX_CLIPES_TOTAL}. "
                f"Apague os clipes ruins (🗑) antes de adicionar mais (mais áudio não melhora a voz: o Chatterbox "
                f"usa só o ⭐ principal e o XTTS uns 30 s somando todos)."
            )
        import re
        import subprocess
        usados = [int(m.group(1)) for a in atuais for m in [re.match(r"ref_(\d+)\.wav$", os.path.basename(a))] if m]
        prox = max(usados + [len(atuais)]) + 1
        novos: List[str] = []
        for k, origem in enumerate(caminhos):
            destino = os.path.join(pasta, f"ref_{prox + k:02d}.wav")
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", origem, "-t", str(duracao_max_segundos),
                 "-ac", "1", "-ar", "22050", "-c:a", "pcm_s16le", destino],
                capture_output=True, timeout=60,
            )
            if r.returncode != 0 or not os.path.exists(destino):
                for n in novos:  # nada de perfil pela metade
                    try:
                        os.remove(n)
                    except OSError:
                        pass
                raise VoiceGeneratorError(
                    f"Não consegui processar o áudio {k + 1} com o ffmpeg (código {r.returncode}). "
                    f"Confira se o arquivo é um áudio/vídeo válido."
                )
            novos.append(destino)
        return novos
    finally:
        for tmp in temporarios:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if temporarios:
            try:
                os.rmdir(os.path.dirname(temporarios[0]))
            except OSError:
                pass


def excluir_clipe_do_perfil(nome: str, indice: int) -> str:
    """🗑 Apaga UM clipe (o índice é o da lista de `caminho_perfil_de_voz`, a mesma da página) e a cópia
    original dele em `_original/`. O último clipe não sai — pra isso, exclua o perfil. Devolve o nome do arquivo."""
    pasta = _pasta_do_perfil_existente(nome)
    lista = caminho_perfil_de_voz(nome)
    if not (0 <= indice < len(lista)):
        raise VoiceGeneratorError("Clipe não encontrado.")
    if len(lista) == 1:
        raise VoiceGeneratorError("É o único clipe do perfil — adicione outro antes, ou exclua o perfil inteiro.")
    alvo = lista[indice]
    base = os.path.basename(alvo)
    os.remove(alvo)
    original = os.path.join(pasta, "_original", base)
    if os.path.isfile(original):
        os.remove(original)
    if _ler_principal(pasta) == "" and os.path.isfile(os.path.join(pasta, ARQ_PRINCIPAL)):
        os.remove(os.path.join(pasta, ARQ_PRINCIPAL))  # o ⭐ era esse — volta pro primeiro
    return base


def definir_clipe_principal(nome: str, indice: int) -> str:
    """⭐ Marca o clipe que vai PRIMEIRO na lista — o único que o Chatterbox/Turbo/pod usam."""
    pasta = _pasta_do_perfil_existente(nome)
    lista = caminho_perfil_de_voz(nome)
    if not (0 <= indice < len(lista)):
        raise VoiceGeneratorError("Clipe não encontrado.")
    base = os.path.basename(lista[indice])
    with open(os.path.join(pasta, ARQ_PRINCIPAL), "w", encoding="utf-8") as f:
        f.write(base)
    return base


# O XTTS v2 tem um limite de tokens POR CHAMADA (o modelo trunca ou
# falha se passar disso — "XTTS can only generate text with a maximum
# of 400 tokens", e o Coqui já avisa antes com "text length exceeds
# the character limit of ... for language 'pt'"). O limite real varia
# por idioma (o aviso do Coqui mostrou 203 caracteres pro português) —
# usamos uma margem bem conservadora abaixo disso, que funciona pra
# qualquer um dos 17 idiomas suportados.
#
# Isso NÃO limita o tamanho do áudio final que dá pra gerar (o Roteiro
# para Áudio já gera narrações de dezenas de minutos há tempos) — só
# controla quanto texto vai em CADA chamada individual ao modelo.
# Textos maiores que isso são divididos em pedaços (por frase, e por
# vírgula/palavra como último recurso se uma frase sozinha já estourar
# o limite), cada pedaço gerado separadamente, e os áudios concatenados
# no arquivo final — tudo isso automático e transparente, tanto faz se
# quem chamou mandou "Oi" ou um texto de 5 parágrafos.
XTTS_LIMITE_CARACTERES_POR_CHAMADA = 180


def _dividir_texto_para_xtts(texto: str, limite: int = XTTS_LIMITE_CARACTERES_POR_CHAMADA) -> List[str]:
    """Divide `texto` em pedaços que cabem no limite por chamada do
    XTTS, tentando ao máximo cortar em fronteiras de FRASE (preserva a
    entonação natural bem melhor que cortar no meio de uma frase) —
    só quebra por vírgula, e por último por palavra, se uma frase
    sozinha já for maior que o limite."""
    texto = (texto or "").strip()
    if not texto:
        return []
    if len(texto) <= limite:
        return [texto]

    frases = re.split(r"(?<=[.!?])\s+", texto)
    pedacos: List[str] = []
    atual = ""
    for frase in frases:
        frase = frase.strip()
        if not frase:
            continue
        if len(frase) > limite:
            if atual:
                pedacos.append(atual)
                atual = ""
            pedacos.extend(_dividir_fragmento_longo(frase, limite))
            continue
        candidato = f"{atual} {frase}".strip() if atual else frase
        if len(candidato) <= limite:
            atual = candidato
        else:
            if atual:
                pedacos.append(atual)
            atual = frase
    if atual:
        pedacos.append(atual)
    return pedacos


def _dividir_fragmento_longo(fragmento: str, limite: int) -> List[str]:
    """Último recurso pra uma FRASE sozinha maior que o limite -- tenta
    quebrar por vírgula primeiro (preserva mais naturalidade que cortar
    no meio de uma oração), e por PALAVRA se nem isso bastar."""
    partes = re.split(r"(?<=,)\s+", fragmento)
    pedacos: List[str] = []
    atual = ""
    for parte in partes:
        candidato = f"{atual} {parte}".strip() if atual else parte
        if len(candidato) <= limite:
            atual = candidato
            continue
        if atual:
            pedacos.append(atual)
            atual = ""
        if len(parte) <= limite:
            atual = parte
            continue
        # nem a "vírgula" sozinha cabe -- quebra palavra por palavra.
        palavras = parte.split()
        sub = ""
        for palavra in palavras:
            candidato_sub = f"{sub} {palavra}".strip() if sub else palavra
            if len(candidato_sub) <= limite:
                sub = candidato_sub
            else:
                if sub:
                    pedacos.append(sub)
                sub = palavra
        if sub:
            pedacos.append(sub)
    if atual:
        pedacos.append(atual)
    return pedacos


def _concatenar_wavs(caminhos: List[str], output_path: str) -> str:
    """Concatena vários .wav (mesmo formato — vêm todos do mesmo
    modelo/chamada, sem risco de incompatibilidade) num arquivo só,
    sem recodificar."""
    if len(caminhos) == 1:
        shutil.copy(caminhos[0], output_path)
        return output_path
    diretorio = os.path.dirname(output_path) or "."
    lista_path = os.path.join(diretorio, f"_concat_{uuid.uuid4().hex[:8]}.txt")
    with open(lista_path, "w", encoding="utf-8") as f:
        for caminho in caminhos:
            escapado = os.path.abspath(caminho).replace("'", "'\\''")
            f.write(f"file '{escapado}'\n")
    try:
        resultado = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lista_path, "-c", "copy", output_path],
            capture_output=True, timeout=120,
        )
        if resultado.returncode != 0 or not os.path.exists(output_path):
            raise VoiceGeneratorError(
                f"ffmpeg não conseguiu juntar os pedaços do áudio: {resultado.stderr.decode(errors='replace')[-300:]}"
            )
    finally:
        if os.path.exists(lista_path):
            os.remove(lista_path)
    return output_path


def xtts_synthesize(
    texto: str,
    output_path: str,
    idioma: str = "pt",
    speaker: Optional[str] = None,
    speaker_wav: Optional[str] = None,
    voice_profile: Optional[str] = None,
    use_gpu: Optional[bool] = None,
    model_path: Optional[str] = None,
    config_path: Optional[str] = None,
    checkpoint_conhecido: Optional[str] = None,
) -> str:
    """Gera um `.wav` com o XTTS v2. Três jeitos de escolher a voz —
    use só UM deles (nessa ordem de prioridade se mais de um vier
    preenchido: speaker_wav > voice_profile > speaker):
      - `speaker_wav`: caminho de um áudio (~6-20s, limpo, sem ruído de
        fundo) de alguém falando — o modelo CLONA aquela voz pro texto
        novo. Áudios mais longos são cortados automaticamente pros
        primeiros 25s — mandar um arquivo de minutos de duração não
        melhora o resultado, só deixa tudo mais lento.
      - `voice_profile`: nome de um perfil salvo antes com
        `salvar_perfil_de_voz()` — reusa o mesmo áudio de referência
        (já processado) sem precisar reenviar o arquivo de novo. Veja
        `listar_perfis_de_voz()` pra saber quais existem.
      - `speaker`: nome de uma das vozes PRONTAS que já vêm com o
        modelo (veja `xtts_list_speakers()`), sem clonagem nenhuma.
      Se nenhum dos três for informado, usa a primeira voz pronta da
      lista do modelo.

    `checkpoint_conhecido`: chave de `XTTS_CHECKPOINTS_CONHECIDOS`
    (ex: "hindi") — baixa (se precisar) e usa esse fine-tune da
    comunidade em vez do modelo padrão. Alternativa manual:
    `model_path`+`config_path` apontando pra um checkpoint já baixado
    (o seu ou qualquer outro que você tenha encontrado no Hugging Face
    — ver `xtts_download_checkpoint()`).
    """
    if idioma not in XTTS_IDIOMAS:
        raise VoiceGeneratorError(
            f"Idioma {idioma!r} não é suportado pelo XTTS v2 — use um de {sorted(XTTS_IDIOMAS)}."
        )

    if checkpoint_conhecido and checkpoint_conhecido != "padrao":
        info = XTTS_CHECKPOINTS_CONHECIDOS.get(checkpoint_conhecido)
        if not info:
            raise VoiceGeneratorError(
                f"Checkpoint {checkpoint_conhecido!r} desconhecido — use um de "
                f"{sorted(XTTS_CHECKPOINTS_CONHECIDOS)}."
            )
        model_path, config_path = xtts_download_checkpoint(info["repo_id"])

    tts = xtts_load(use_gpu=use_gpu, model_path=model_path, config_path=config_path)

    kwargs: Dict[str, Any] = {"text": texto, "language": idioma, "file_path": output_path}
    if speaker_wav:
        if not os.path.exists(speaker_wav):
            raise VoiceGeneratorError(f"Áudio de referência não encontrado: {speaker_wav!r}")
        kwargs["speaker_wav"] = _preparar_audio_referencia(speaker_wav)
    elif voice_profile:
        kwargs["speaker_wav"] = caminho_perfil_de_voz(voice_profile)  # já processado ao salvar
    else:
        if not speaker:
            speakers = list(getattr(tts, "speakers", None) or [])
            if not speakers:
                raise VoiceGeneratorError(
                    "Nenhuma voz pronta disponível nesse modelo XTTS e nenhum áudio de "
                    "referência (speaker_wav) foi enviado — informe um dos dois."
                )
            speaker = speakers[0]
        kwargs["speaker"] = speaker

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    pedacos = _dividir_texto_para_xtts(texto)
    if not pedacos:
        raise VoiceGeneratorError("Texto vazio — nada pra narrar.")

    def _gerar_um_pedaco(texto_pedaco: str, destino: str, numero: Optional[int] = None) -> None:
        kwargs_pedaco = dict(kwargs)
        kwargs_pedaco["text"] = texto_pedaco
        kwargs_pedaco["file_path"] = destino
        try:
            tts.tts_to_file(**kwargs_pedaco)
        except Exception as exc:  # noqa: BLE001
            mensagem = str(exc)
            prefixo_pedaco = f"(pedaço {numero} de {len(pedacos)}) " if numero is not None else ""
            if "torchcodec" in mensagem.lower() or "libtorchcodec" in mensagem.lower() or "AudioDecoder" in mensagem:
                raise VoiceGeneratorError(
                    f"{prefixo_pedaco}Falha ao decodificar o áudio de referência por causa do torchcodec "
                    "(mesmo problema de sempre no Windows — veja a mensagem de `xtts_load` pra soluções). "
                    "Se o áudio de referência já tinha passado pelo pré-processamento automático e "
                    "ainda assim falhou, tente converter ele manualmente antes de enviar: um .wav "
                    "PCM 16-bit mono de uns 10-15 segundos costuma ser o mais confiável. "
                    f"Erro original: {exc}"
                ) from exc
            raise VoiceGeneratorError(f"{prefixo_pedaco}Falha ao gerar áudio com o XTTS v2: {exc}") from exc

    if len(pedacos) == 1:
        _gerar_um_pedaco(pedacos[0], output_path)
        return output_path

    # texto maior que o limite por chamada do modelo -- gera cada
    # pedaço num .wav temporário e concatena tudo no arquivo final.
    # Isso é completamente transparente pra quem chamou: o resultado é
    # um único áudio contínuo, do mesmo jeito que sempre foi.
    diretorio_tmp = os.path.join(os.path.dirname(output_path) or ".", f"_xtts_pedacos_{uuid.uuid4().hex[:8]}")
    os.makedirs(diretorio_tmp, exist_ok=True)
    try:
        caminhos_pedacos = []
        for i, pedaco in enumerate(pedacos, start=1):
            caminho_pedaco = os.path.join(diretorio_tmp, f"pedaco_{i:03d}.wav")
            _gerar_um_pedaco(pedaco, caminho_pedaco, numero=i)
            caminhos_pedacos.append(caminho_pedaco)
        _concatenar_wavs(caminhos_pedacos, output_path)
    finally:
        shutil.rmtree(diretorio_tmp, ignore_errors=True)
    return output_path


# ============================================================ #
# CHATTERBOX TTS (Resemble AI, via chatterbox-tts)
# ============================================================ #

# Sempre usa a variante MULTILÍNGUE (`ChatterboxMultilingualTTS`), que
# cobre os 23 idiomas abaixo (incluindo português) — a variante
# "inglês só" (`ChatterboxTTS`, sem `language_id`) não é usada aqui,
# pra não precisar trocar de classe/modelo por idioma.
CHATTERBOX_IDIOMAS = {
    "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it",
    "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh",
}

# Assim como o XTTS, o Chatterbox tem uma "janela acústica" limitada
# por chamada -- textos mais longos que isso arriscam estourar o
# contexto interno do modelo e travar a GPU com um erro de índice fora
# dos limites. Não existe um número oficial documentado, mas 250
# caracteres é o valor mais usado como padrão seguro pela comunidade
# (ex: pacote "text-to-audio", vários forks do Chatterbox-TTS-Server).
CHATTERBOX_LIMITE_CARACTERES_POR_CHAMADA = 250

_chatterbox_cache: Dict[str, Any] = {}  # cache_key -> instância ChatterboxMultilingualTTS carregada


def _checar_perth_watermarker() -> None:
    """Checagem PROATIVA de um problema real e bem comum: a lib do
    "watermarker" que o Chatterbox usa (`resemble-perth`) importa
    `pkg_resources` internamente, um módulo que o `setuptools`
    REMOVEU a partir da versão 81. Como o `resemble-perth` engole
    esse erro de import silenciosamente (só deixa
    `PerthImplicitWatermarker = None` em vez de avisar), o
    `chatterbox-tts` só quebra bem mais tarde, com um
    `TypeError: 'NoneType' object is not callable` completamente
    sem contexto — checar aqui na frente dá um erro claro em vez
    dessa mensagem confusa. Compartilhado entre `chatterbox_load` e
    `chatterbox_turbo_load` — os dois usam o mesmo watermarker.
    """
    try:
        import perth  # type: ignore
        if getattr(perth, "PerthImplicitWatermarker", None) is None:
            raise VoiceGeneratorError(
                "O Chatterbox TTS está instalado, mas a lib do \"watermarker\" que ele usa "
                "(resemble-perth) não carregou direito — provavelmente por causa de uma versão "
                "recente do setuptools (a partir da 81, ele removeu o módulo pkg_resources, que o "
                "resemble-perth ainda usa por baixo dos panos). Resolve com: "
                'pip install "setuptools<81" wheel'
                " -- depois disso, reinicie o site (pare e rode de novo) pra garantir que o "
                "processo Python carregue a versão certa."
            )
    except ImportError:
        pass  # se nem o perth importar, o erro do ChatterboxMultilingualTTS/ChatterboxTurboTTS abaixo já é claro o bastante


def _pod_studio():
    """🖥️ Meu pod (v84_121): o cliente do servidor studio-ia fica na raiz do site (pod_studio.py)."""
    raiz = os.path.dirname(os.path.dirname(_DIR))
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    import pod_studio  # type: ignore
    return pod_studio


def _no_pod(engine: str) -> bool:
    """Esse motor está configurado pra gerar no pod (⚙️ Configurações → 🟣 Runpod → Meu pod)?"""
    try:
        return bool(_pod_studio().motor_no_pod(engine))
    except Exception:  # noqa: BLE001 — sem o módulo/config: roda local como sempre
        return False


def _narrar_no_pod(engine: str, texto: str, output_path: str, speaker_wav: Optional[str] = None,
                   voice_profile: Optional[str] = None, idioma: str = "pt", exaggeration: float = 0.5,
                   cfg_weight: float = 0.5, variante: str = "") -> str:
    """Mesma voz (áudio enviado ou 1º clipe do perfil, igual ao local), só que gerada na GPU do pod."""
    if not (texto or "").strip():
        raise VoiceGeneratorError("Texto vazio — nada pra narrar.")
    referencia, temporaria = None, False
    if speaker_wav:
        if not os.path.exists(speaker_wav):
            raise VoiceGeneratorError(f"Áudio de referência não encontrado: {speaker_wav!r}")
        referencia = _preparar_audio_referencia(speaker_wav)
        temporaria = referencia != speaker_wav
    elif voice_profile:
        referencia = caminho_perfil_de_voz(voice_profile)[0]
    pod = _pod_studio()
    try:
        extra = {"pacote_dedicado": False} if (variante or "").lower() == "pt-pt" and idioma == "pt" else {}
        pod.narrar(texto, output_path, motor=engine, idioma=idioma, referencia=referencia,
                   exaggeration=exaggeration, cfg_weight=cfg_weight, **extra)
    except pod.PodErro as exc:
        raise VoiceGeneratorError(f"🖥️ Pod: {exc}") from exc
    finally:
        if temporaria and referencia:
            try:
                os.remove(referencia)
            except OSError:
                pass
    return output_path


# ------------------------------------------------------------------ 🪟 Windows: "arquivo de paginação muito pequeno" (v84_175)
def _falta_memoria_virtual(exc: BaseException) -> bool:
    """WinError 1455: o Windows não conseguiu reservar memória virtual pra abrir os pesos do modelo. No arquivo de
    paginação "gerenciado pelo sistema", ele CRESCE depois dessa falha — por isso a 2ª tentativa costuma funcionar."""
    m = str(exc).lower()
    return "1455" in m or "paging file" in m or "arquivo de paginação" in m or "arquivo de paginacao" in m


def _carregar_com_nova_tentativa(carregar, nome_motor: str, tentativas: int = 3, espera: float = 3.0):
    """Roda `carregar()`; no erro 1455 libera memória, espera e tenta de novo (até `tentativas` vezes)."""
    import gc
    for k in range(tentativas):
        try:
            return carregar()
        except Exception as exc:  # noqa: BLE001
            if not _falta_memoria_virtual(exc):
                raise
            if k == tentativas - 1:
                raise VoiceGeneratorError(
                    f"O Windows ficou sem memória virtual pra abrir o {nome_motor} (erro 1455 — \"arquivo de paginação "
                    f"muito pequeno\"), mesmo tentando {tentativas} vezes. Resolve de vez aumentando o arquivo de "
                    "paginação: Iniciar → \"Ajustar a aparência e o desempenho do Windows\" → Avançado → Memória "
                    "virtual → Alterar → desmarque \"Gerenciar automaticamente\" → no disco mais rápido (SSD), "
                    "Tamanho personalizado: inicial 16384 e máximo 32768 MB (ou mais) → Definir → OK → reinicie o PC. "
                    "Fechar o navegador e outros programas pesados antes também ajuda. "
                    f"Erro original: {exc}"
                ) from exc
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(espera)


def chatterbox_load(use_gpu: Optional[bool] = None):
    """Carrega (ou reaproveita, se já carregado com os mesmos
    parâmetros) o modelo multilíngue do Chatterbox TTS — baixa sozinho
    na primeira vez (fica guardado no cache padrão do Hugging Face,
    `~/.cache/huggingface`)."""
    # Mesma dupla defesa contra o torchcodec no Windows que já existe
    # pro XTTS (ver `xtts_load`) -- o Chatterbox também usa
    # torch/torchaudio por baixo dos panos (tanto pra carregar o áudio
    # de referência da clonagem quanto, por tabela, em qualquer outro
    # ponto que dependa de `torchaudio.load`), e cai exatamente no
    # mesmo problema sem isso.
    ensure_ffmpeg_dll_directory()
    _patch_torchaudio_load_via_soundfile()

    try:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    except ImportError as exc:
        raise VoiceGeneratorError(
            "Chatterbox TTS não está instalado. Rode: pip install chatterbox-tts"
        ) from exc

    _checar_perth_watermarker()

    if use_gpu is None:
        use_gpu = torch_gpu_available()
    device = "cuda" if use_gpu else "cpu"

    cache_key = f"chatterbox-multilingual:{device}"
    if cache_key in _chatterbox_cache:
        return _chatterbox_cache[cache_key]

    try:
        modelo = _carregar_com_nova_tentativa(lambda: ChatterboxMultilingualTTS.from_pretrained(device=device), "Chatterbox")
    except VoiceGeneratorError:
        raise
    except Exception as exc:  # noqa: BLE001
        mensagem = str(exc)
        if "nonetype" in mensagem.lower() and "callable" in mensagem.lower():
            raise VoiceGeneratorError(
                "Falha ao carregar o Chatterbox TTS com um erro típico do resemble-perth "
                "desatualizado/quebrado (\"NoneType não é chamável\") — tente rodar "
                'pip install "setuptools<81" wheel'
                " e reiniciar o site. Se isso não resolver, tente reinstalar com "
                "pip install --force-reinstall resemble-perth. "
                f"Erro original: {exc}"
            ) from exc
        raise VoiceGeneratorError(f"Falha ao carregar/baixar o Chatterbox TTS: {exc}") from exc

    _chatterbox_cache[cache_key] = modelo
    return modelo


def _salvar_audio_chatterbox(wav: Any, output_path: str, sample_rate: int) -> None:
    """Salva o tensor de áudio que `modelo.generate()` devolve — extraído
    numa função à parte só pra dar pra substituir em teste (o
    `torchaudio` é uma dependência pesada, puxada pelo próprio
    `chatterbox-tts`; sem ele instalado, não dá pra testar essa linha
    específica sem mockar ela).

    Usa `soundfile` em vez de `torchaudio.save()` de propósito: em
    versões recentes do torchaudio, `save()` tenta criar um
    "AudioEncoder" baseado no torchcodec por baixo dos panos — o MESMO
    problema de DLL do FFmpeg no Windows que afeta `torchaudio.load()`
    (ver `_patch_torchaudio_load_via_soundfile`), só que essa segunda
    função só troca o `load`, não o `save`. `soundfile` não depende
    dessas DLLs de jeito nenhum, então evita o problema por completo
    em vez de só contornar.
    """
    try:
        import numpy as np
        import soundfile as sf

        dados = wav.detach().cpu().numpy() if hasattr(wav, "detach") else np.asarray(wav)
        if dados.ndim == 2:
            dados = dados.T  # torch usa (canais, amostras) -- soundfile espera (amostras, canais)
            if dados.shape[1] == 1:
                dados = dados[:, 0]  # mono: soundfile prefere 1D a uma coluna só
        pico = float(np.abs(dados).max()) if dados.size else 0.0
        if pico > 0.97:  # 🎭 v84_372: o modelo passa de 1.0 às vezes -> o WAV de 16 bits cortava (clip audível)
            dados = dados * (0.94 / pico)
        sf.write(output_path, dados, sample_rate)
    except Exception:
        # soundfile indisponível ou tensor num formato inesperado --
        # tenta do jeito padrão como último recurso (é o comportamento
        # de antes dessa correção; melhor tentar do que travar aqui).
        import torchaudio as ta
        ta.save(output_path, wav, sample_rate)


def _modulo_expressivo():
    """toolkit/tts/expressivo.py, importado como pacote (site) ou solto (testes)."""
    try:
        from tts import expressivo as exp  # type: ignore
    except ImportError:
        import expressivo as exp  # type: ignore
    return exp


def chatterbox_synthesize(
    texto: str,
    output_path: str,
    idioma: str = "pt",
    speaker_wav: Optional[str] = None,
    voice_profile: Optional[str] = None,
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,
    use_gpu: Optional[bool] = None,
    expressivo: bool = False,
    variante: str = "",
    sons: str = "turbo",
) -> str:
    """Gera um `.wav` com o Chatterbox TTS (Resemble AI) — clona voz
    por zero-shot igual o XTTS v2 (um áudio de referência curto), só
    que de um jeito diferente por baixo dos panos. Open-source (MIT),
    23 idiomas incluindo português.

    Dois jeitos de clonar a voz — use só UM (se os dois vierem
    preenchidos, `speaker_wav` tem prioridade):
      - `speaker_wav`: caminho de um áudio de referência (~6-20s,
        limpo, sem ruído de fundo) — passa pelo mesmo pré-processamento
        (corte + conversão) que já existe pro XTTS.
      - `voice_profile`: nome de um perfil salvo antes com
        `salvar_perfil_de_voz()` — o MESMO perfil que já funciona pro
        XTTS (usa o primeiro áudio salvo nele, se o perfil tiver mais
        de um).
    Sem nenhum dos dois, gera com a voz "neutra" padrão do modelo (sem
    clonagem nenhuma).

    Texto mais longo que `CHATTERBOX_LIMITE_CARACTERES_POR_CHAMADA` é
    dividido automaticamente (preferindo cortar em fronteiras de
    frase) e cada pedaço é gerado e concatenado no `.wav` final — isso
    é transparente pra quem chama; o resultado é um único áudio
    contínuo. Sem isso, texto longo demais numa chamada só arrisca
    estourar o contexto do modelo e travar a GPU.

    `exaggeration` (0.0 a 1.0, padrão 0.5): intensidade emocional da
    fala — valores mais altos deixam a fala mais expressiva/dramática
    (e tendem a acelerar a fala).
    `cfg_weight` (0.0 a 1.0, padrão 0.5): quanto o resultado gruda no
    estilo/sotaque do áudio de referência — valores mais baixos (ex:
    0.3) ajudam quando a voz de referência fala rápido, ou quando o
    idioma do TEXTO é diferente do idioma da voz de referência (evita
    herdar o sotaque errado do áudio de referência).

    Os áudios gerados pelo Chatterbox saem com uma marca d'água
    imperceptível da Resemble AI (o "Perth" watermarker) — não afeta a
    qualidade nem é removível de propósito, é assim que o modelo
    funciona (identifica áudio sintético gerado por ele mesmo).
    """
    if idioma not in CHATTERBOX_IDIOMAS:
        raise VoiceGeneratorError(
            f"Idioma {idioma!r} não é suportado pelo Chatterbox TTS — use um de {sorted(CHATTERBOX_IDIOMAS)}."
        )

    if expressivo:  # 🎭 v84_372: [soprosa] [risada] [pausa] *ênfase* ... (ver expressivo.py)
        exp = _modulo_expressivo()
        if exp.tem_tags(texto):
            try:
                return exp.sintetizar(sys.modules[__name__], texto, output_path, idioma=idioma, speaker_wav=speaker_wav,
                                      voice_profile=voice_profile, exaggeration=exaggeration, cfg_weight=cfg_weight,
                                      use_gpu=use_gpu, on_log=lambda s: print(s, flush=True), variante=variante,
                                      sons=sons)
            except exp.ExpressivoErro as exc:
                raise VoiceGeneratorError(f"🎭 Modo expressivo: {exc}") from exc
        texto = exp.texto_sem_tags(texto)

    if _no_pod("chatterbox"):  # 🖥️ Meu pod: gera na GPU do pod (pt usa o modelo dedicado pt-BR, se marcado)
        return _narrar_no_pod("chatterbox", texto, output_path, speaker_wav=speaker_wav, voice_profile=voice_profile,
                              idioma=idioma, exaggeration=exaggeration, cfg_weight=cfg_weight, variante=variante)

    modelo = chatterbox_load(use_gpu=use_gpu)

    audio_prompt_path = None
    if speaker_wav:
        if not os.path.exists(speaker_wav):
            raise VoiceGeneratorError(f"Áudio de referência não encontrado: {speaker_wav!r}")
        audio_prompt_path = _preparar_audio_referencia(speaker_wav)
    elif voice_profile:
        audio_prompt_path = caminho_perfil_de_voz(voice_profile)[0]

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    kwargs_geracao: Dict[str, Any] = {
        "language_id": idioma, "exaggeration": exaggeration, "cfg_weight": cfg_weight,
    }
    if audio_prompt_path:
        kwargs_geracao["audio_prompt_path"] = audio_prompt_path

    pedacos = _dividir_texto_para_xtts(texto, limite=CHATTERBOX_LIMITE_CARACTERES_POR_CHAMADA)
    if not pedacos:
        raise VoiceGeneratorError("Texto vazio — nada pra narrar.")

    def _gerar_um_pedaco(texto_pedaco: str, destino: str, numero: Optional[int] = None) -> None:
        try:
            wav = modelo.generate(texto_pedaco, **kwargs_geracao)
            _salvar_audio_chatterbox(wav, destino, modelo.sr)
        except Exception as exc:  # noqa: BLE001
            mensagem = str(exc)
            prefixo_pedaco = f"(pedaço {numero} de {len(pedacos)}) " if numero is not None else ""
            if "device-side assert" in mensagem.lower() or "cuda error" in mensagem.lower():
                raise VoiceGeneratorError(
                    f"{prefixo_pedaco}Falha ao gerar áudio com o Chatterbox TTS: erro de GPU (CUDA). "
                    "A causa mais comum é um bug conhecido do próprio Chatterbox — TEXTO CURTO DEMAIS "
                    "pode travar a GPU (issues #435 e #201 no repositório oficial do projeto). Tente: "
                    "(1) juntar essa fala com a fala vizinha ou escrever uma frase um pouco mais longa, "
                    "ou (2) usar outro motor (XTTS, Piper ou Kokoro) só nessa fala específica. Como cada "
                    "geração roda num processo isolado, a próxima tentativa já parte de um contexto de "
                    "GPU limpo — não deveria precisar reiniciar o site inteiro por causa disso. "
                    f"Erro original: {exc}"
                ) from exc
            raise VoiceGeneratorError(f"{prefixo_pedaco}Falha ao gerar áudio com o Chatterbox TTS: {exc}") from exc

    if len(pedacos) == 1:
        _gerar_um_pedaco(pedacos[0], output_path)
        return output_path

    # texto maior que o limite seguro por chamada (a "janela acústica"
    # do Chatterbox) -- gera cada pedaço num .wav temporário e
    # concatena tudo no arquivo final. Sem isso, textos longos (vários
    # parágrafos) arriscam estourar o contexto do modelo e travar a
    # GPU com um erro de índice fora dos limites -- o mesmo tipo de
    # problema que o XTTS tem, só que com uma janela ainda mais curta.
    diretorio_tmp = os.path.join(os.path.dirname(output_path) or ".", f"_chatterbox_pedacos_{uuid.uuid4().hex[:8]}")
    os.makedirs(diretorio_tmp, exist_ok=True)
    try:
        caminhos_pedacos = []
        for i, pedaco in enumerate(pedacos, start=1):
            caminho_pedaco = os.path.join(diretorio_tmp, f"pedaco_{i:03d}.wav")
            _gerar_um_pedaco(pedaco, caminho_pedaco, numero=i)
            caminhos_pedacos.append(caminho_pedaco)
        _concatenar_wavs(caminhos_pedacos, output_path)
    finally:
        shutil.rmtree(diretorio_tmp, ignore_errors=True)
    return output_path


# ============================================================ #
# CHATTERBOX TURBO (Resemble AI, via chatterbox-tts) — SÓ INGLÊS
# ============================================================ #

# O Turbo é uma variante diferente do Chatterbox multilíngue acima:
# mais leve/rápido, mas SÓ INGLÊS, e sem `idioma`/`exaggeration`/
# `cfg_weight` (a própria Resemble AI recomenda usar o modelo
# multilíngue se esses controles importam — ver discussão oficial:
# https://huggingface.co/ResembleAI/chatterbox-turbo/discussions/22).
# Em troca, é o único que aceita TAGS PARALINGUÍSTICAS (`[laugh]`,
# `[sigh]`, `[whispering]` etc) direto no texto — não fazem parte do
# vocabulário do modelo multilíngue (ficam soletradas letra por letra
# em vez de virarem o som/estilo pedido).
CHATTERBOX_TURBO_TAGS_SOM = {
    "laugh", "chuckle", "gasp", "cough", "sigh", "groan", "sniff", "shush", "clear throat",
}
CHATTERBOX_TURBO_TAGS_ENTREGA = {
    "angry", "crying", "dramatic", "fear", "happy", "narration",
    "sarcastic", "surprised", "whispering", "advertisement",
}
CHATTERBOX_TURBO_TAGS = CHATTERBOX_TURBO_TAGS_SOM | CHATTERBOX_TURBO_TAGS_ENTREGA

# Mesma ideia do limite do Chatterbox multilíngue (janela acústica por
# chamada) -- o Turbo é mais leve, mas não documenta um número maior,
# então usa o mesmo valor conservador por segurança.
CHATTERBOX_TURBO_LIMITE_CARACTERES_POR_CHAMADA = 250

_chatterbox_turbo_cache: Dict[str, Any] = {}  # cache_key -> instância ChatterboxTurboTTS carregada


def _eh_erro_dtype_float_double(exc: BaseException) -> bool:
    """Reconhece o erro "expected scalar type Float but found Double"
    (ou o inverso) do PyTorch -- mensagem genérica de tipo de tensor."""
    m = str(exc).lower()
    return "scalar type" in m and "float" in m and "double" in m


def _blindar_norm_loudness_turbo(modelo: Any) -> None:
    """Bug conhecido do Chatterbox Turbo com numpy >= 2.0 (issue #499 do
    repositório oficial): `norm_loudness()` multiplica o áudio de
    referência (float32) por um ganho `np.float64`, e pelas regras novas
    de promoção de tipos do numpy 2 o resultado vira float64 -- que
    depois estoura no PyTorch com "expected scalar type Float but found
    Double". Envolve o método pra devolver sempre float32, mantendo a
    normalização de volume em vez de desligá-la. Sem o método (versão
    diferente do pacote), não faz nada -- o retry com
    `norm_loudness=False` em `chatterbox_turbo_synthesize` cobre esse caso.
    """
    original = getattr(modelo, "norm_loudness", None)
    if original is None or getattr(original, "_blindado_float32", False):
        return

    def _norm_loudness_float32(*args: Any, **kwargs: Any) -> Any:
        resultado = original(*args, **kwargs)
        try:
            import numpy as np
            return np.asarray(resultado, dtype=np.float32)
        except Exception:  # noqa: BLE001
            return resultado

    _norm_loudness_float32._blindado_float32 = True  # type: ignore[attr-defined]
    try:
        modelo.norm_loudness = _norm_loudness_float32
    except Exception:  # noqa: BLE001
        pass


def chatterbox_turbo_load(use_gpu: Optional[bool] = None):
    """Carrega (ou reaproveita) o modelo Chatterbox Turbo — baixa
    sozinho na primeira vez (fica guardado no cache padrão do Hugging
    Face, `~/.cache/huggingface`)."""
    ensure_ffmpeg_dll_directory()
    _patch_torchaudio_load_via_soundfile()

    try:
        from chatterbox.tts_turbo import ChatterboxTurboTTS
    except ImportError as exc:
        raise VoiceGeneratorError(
            "Chatterbox Turbo não está instalado. Rode: pip install chatterbox-tts "
            "(o mesmo pacote do Chatterbox multilíngue já inclui o Turbo)."
        ) from exc

    _checar_perth_watermarker()

    if use_gpu is None:
        use_gpu = torch_gpu_available()
    device = "cuda" if use_gpu else "cpu"

    cache_key = f"chatterbox-turbo:{device}"
    if cache_key in _chatterbox_turbo_cache:
        return _chatterbox_turbo_cache[cache_key]

    try:
        modelo = _carregar_com_nova_tentativa(lambda: ChatterboxTurboTTS.from_pretrained(device=device), "Chatterbox Turbo")
    except VoiceGeneratorError:
        raise
    except Exception as exc:  # noqa: BLE001
        mensagem = str(exc)
        if "nonetype" in mensagem.lower() and "callable" in mensagem.lower():
            raise VoiceGeneratorError(
                "Falha ao carregar o Chatterbox Turbo com um erro típico do resemble-perth "
                "desatualizado/quebrado (\"NoneType não é chamável\") — tente rodar "
                'pip install "setuptools<81" wheel'
                " e reiniciar o site. Se isso não resolver, tente reinstalar com "
                "pip install --force-reinstall resemble-perth. "
                f"Erro original: {exc}"
            ) from exc
        raise VoiceGeneratorError(f"Falha ao carregar/baixar o Chatterbox Turbo: {exc}") from exc

    _blindar_norm_loudness_turbo(modelo)
    _chatterbox_turbo_cache[cache_key] = modelo
    return modelo


def chatterbox_turbo_synthesize(
    texto: str,
    output_path: str,
    speaker_wav: Optional[str] = None,
    voice_profile: Optional[str] = None,
    use_gpu: Optional[bool] = None,
) -> str:
    """Gera um `.wav` com o Chatterbox Turbo (Resemble AI) — variante
    mais leve/rápida do Chatterbox, mas **SÓ EM INGLÊS** (sem
    parâmetro de idioma nenhum). Não aceita `exaggeration`/
    `cfg_weight` (o Turbo ignora os dois — a própria Resemble AI
    recomenda o modelo multilíngue, `chatterbox_synthesize()`, se
    esses controles importam pro seu caso).

    O que o Turbo tem de diferente: **TAGS PARALINGUÍSTICAS** direto
    no texto, faladas na voz clonada, sem edição de áudio nenhuma:
      - Tags de SOM: [laugh] [chuckle] [gasp] [cough] [sigh] [groan]
        [sniff] [shush] [clear throat]
      - Tags de ESTILO (mudam a interpretação da frase — funcionam
        melhor no INÍCIO da frase): [angry] [crying] [dramatic] [fear]
        [happy] [narration] [sarcastic] [surprised] [whispering]
        [advertisement]
    Exemplo: `"Hi there [chuckle], how can I help you today?"`. Essas
    tags só existem no vocabulário do Turbo — mandadas pro modelo
    multilíngue, saem soletradas letra por letra em vez de virarem o
    som/estilo pedido.

    Clonagem de voz: mesmo esquema dos outros dois motores —
    `speaker_wav` (áudio de referência) ou `voice_profile` (perfil
    salvo, compartilhado com XTTS/Chatterbox multilíngue). Sem
    nenhum dos dois, usa a voz "neutra" padrão do modelo.

    Texto mais longo que `CHATTERBOX_TURBO_LIMITE_CARACTERES_POR_CHAMADA`
    é dividido automaticamente, igual o modelo multilíngue.
    """
    if _no_pod("chatterbox_turbo"):  # 🖥️ Meu pod
        return _narrar_no_pod("chatterbox_turbo", texto, output_path, speaker_wav=speaker_wav,
                              voice_profile=voice_profile, idioma="en")

    modelo = chatterbox_turbo_load(use_gpu=use_gpu)

    audio_prompt_path = None
    if speaker_wav:
        if not os.path.exists(speaker_wav):
            raise VoiceGeneratorError(f"Áudio de referência não encontrado: {speaker_wav!r}")
        audio_prompt_path = _preparar_audio_referencia(speaker_wav)
    elif voice_profile:
        audio_prompt_path = caminho_perfil_de_voz(voice_profile)[0]

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    kwargs_geracao: Dict[str, Any] = {}
    if audio_prompt_path:
        kwargs_geracao["audio_prompt_path"] = audio_prompt_path

    pedacos = _dividir_texto_para_xtts(texto, limite=CHATTERBOX_TURBO_LIMITE_CARACTERES_POR_CHAMADA)
    if not pedacos:
        raise VoiceGeneratorError("Texto vazio — nada pra narrar.")

    def _gerar_um_pedaco(texto_pedaco: str, destino: str, numero: Optional[int] = None) -> None:
        try:
            try:
                wav = modelo.generate(texto_pedaco, **kwargs_geracao)
            except Exception as exc_dtype:  # noqa: BLE001
                # Rede de segurança do bug do numpy 2 (ver
                # `_blindar_norm_loudness_turbo`): se mesmo assim der o
                # erro Float/Double, refaz SEM a normalização de volume
                # da referência -- e mantém desligada nos próximos
                # pedaços (kwargs_geracao é compartilhado), em vez de
                # falhar e refazer em cada um dos pedaços.
                if _eh_erro_dtype_float_double(exc_dtype) and kwargs_geracao.get("norm_loudness", True):
                    kwargs_geracao["norm_loudness"] = False
                    wav = modelo.generate(texto_pedaco, **kwargs_geracao)
                else:
                    raise
            _salvar_audio_chatterbox(wav, destino, modelo.sr)
        except Exception as exc:  # noqa: BLE001
            mensagem = str(exc)
            prefixo_pedaco = f"(pedaço {numero} de {len(pedacos)}) " if numero is not None else ""
            if _eh_erro_dtype_float_double(exc):
                raise VoiceGeneratorError(
                    f"{prefixo_pedaco}Falha ao gerar áudio com o Chatterbox Turbo: erro de tipo de dado "
                    "(Float/Double). É um bug conhecido do Turbo com numpy >= 2.0 quando há áudio de "
                    "referência (issue #499 do repositório oficial). Já tentei contornar, sem sucesso — "
                    "tente gerar SEM perfil/áudio de referência (voz padrão do modelo), ou use o "
                    f"Chatterbox multilíngue. Erro original: {exc}"
                ) from exc
            if "device-side assert" in mensagem.lower() or "cuda error" in mensagem.lower():
                raise VoiceGeneratorError(
                    f"{prefixo_pedaco}Falha ao gerar áudio com o Chatterbox Turbo: erro de GPU (CUDA) "
                    "— provavelmente texto curto demais nesse pedaço específico (bug conhecido do "
                    "Chatterbox). Tente juntar com a fala vizinha, ou escrever uma frase mais longa."
                ) from exc
            raise VoiceGeneratorError(f"{prefixo_pedaco}Falha ao gerar áudio com o Chatterbox Turbo: {exc}") from exc

    if len(pedacos) == 1:
        _gerar_um_pedaco(pedacos[0], output_path)
        return output_path

    diretorio_tmp = os.path.join(os.path.dirname(output_path) or ".", f"_chatterbox_turbo_pedacos_{uuid.uuid4().hex[:8]}")
    os.makedirs(diretorio_tmp, exist_ok=True)
    try:
        caminhos_pedacos = []
        for i, pedaco in enumerate(pedacos, start=1):
            caminho_pedaco = os.path.join(diretorio_tmp, f"pedaco_{i:03d}.wav")
            _gerar_um_pedaco(pedaco, caminho_pedaco, numero=i)
            caminhos_pedacos.append(caminho_pedaco)
        _concatenar_wavs(caminhos_pedacos, output_path)
    finally:
        shutil.rmtree(diretorio_tmp, ignore_errors=True)
    return output_path


# ============================================================ #
# KOKORO (via kokoro-onnx)
# ============================================================ #

# Releases oficiais do kokoro-onnx — hoje existem DUAS variantes de
# modelo, cada uma em TRÊS precisões (qualidade x tamanho/velocidade):
#   "v1.0"     -- inglês + outros idiomas, 54 vozes
#   "v1.1-zh"  -- tudo do v1.0 MAIS chinês (mandarim) + 3 vozes extras
#                 em inglês, 103 vozes no total (arquivo maior)
# Cada variante tem um arquivo de vozes PRÓPRIO (não são intercambiáveis
# entre variantes). Fonte: github.com/thewh1teagle/kokoro-onnx/releases
# (release "model-files-v1.1", a mais recente das duas no momento).
KOKORO_RELEASE_BASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"

KOKORO_MODEL_VARIANTS: Dict[str, Dict[str, str]] = {
    "v1.0": {
        "label": "v1.0 — 54 vozes (inglês + outros idiomas)",
        "model_prefix": "kokoro-v1.0",
        "voices_file": "voices-v1.0.bin",
    },
    "v1.1-zh": {
        "label": "v1.1-zh — 103 vozes (adiciona chinês/mandarim + mais 3 em inglês)",
        "model_prefix": "kokoro-v1.1-zh",
        "voices_file": "voices-v1.1-zh.bin",
    },
}

# Mesma variante, três arquivos .onnx diferentes -- mesmas vozes, troca
# só qualidade por tamanho/velocidade (números de correlação espectral
# contra o fp32, direto da nota oficial do release).
KOKORO_PRECISIONS: Dict[str, Dict[str, str]] = {
    "fp32": {"label": "Completa (fp32) — melhor qualidade, ~326MB", "suffix": ""},
    "fp16": {"label": "Meia precisão (fp16) — quase idêntica à completa, ~164MB", "suffix": ".fp16"},
    "int8": {"label": "Leve (int8) — mais rápida e menor (~114MB), qualidade um pouco menor", "suffix": ".int8"},
}

DEFAULT_KOKORO_VARIANT = "v1.0"
DEFAULT_KOKORO_PRECISION = "fp32"

# voz -> (código de idioma esperado pelo kokoro-onnx, descrição) -- as
# vozes abaixo existem na variante "v1.0" (e continuam funcionando na
# "v1.1-zh", que é um superconjunto). A "v1.1-zh" tem mais ~50 vozes
# em mandarim (zf_*/zm_*) e mais 3 em inglês que não estão listadas
# aqui (lista curada, não exaustiva) — qualquer nome de voz válido do
# arquivo .bin da variante escolhida funciona em `voz=`, mesmo fora
# desta lista.
KOKORO_VOZES: Dict[str, Tuple[str, str]] = {
    "pf_dora": ("pt-br", "Português (Brasil), feminina"),
    "pm_alex": ("pt-br", "Português (Brasil), masculina"),
    "pm_santa": ("pt-br", "Português (Brasil), masculina (tom Papai Noel)"),
    "af_heart": ("en-us", "Inglês (EUA), feminina — voz padrão do modelo"),
    "af_bella": ("en-us", "Inglês (EUA), feminina"),
    "af_sarah": ("en-us", "Inglês (EUA), feminina"),
    "am_michael": ("en-us", "Inglês (EUA), masculina"),
    "am_adam": ("en-us", "Inglês (EUA), masculina"),
    "bf_emma": ("en-gb", "Inglês (Reino Unido), feminina"),
    "bm_george": ("en-gb", "Inglês (Reino Unido), masculina"),
    "ef_dora": ("es", "Espanhol, feminina"),
    "em_alex": ("es", "Espanhol, masculina"),
    "ff_siwis": ("fr-fr", "Francês, feminina"),
    "if_sara": ("it", "Italiano, feminina"),
    "jf_alpha": ("ja", "Japonês, feminina"),
    "zf_xiaobei": ("cmn", "Chinês (mandarim), feminina"),
}


def _download_file(url: str, dest_path: str) -> None:
    """Baixa `url` pra `dest_path` em streaming (arquivos de modelo
    costumam ter dezenas/centenas de MB) — escreve num `.part` primeiro
    e só renomeia pro nome final no fim, pra nunca deixar um arquivo
    pela metade se a conexão cair no meio do download.
    """
    import requests

    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    tmp_path = dest_path + ".part"
    try:
        with requests.get(url, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    # No Windows, o antivírus costuma abrir o arquivo recém-baixado
    # pra escanear bem na hora em que o download termina, e o
    # os.replace() pode esbarrar num WinError 32 (arquivo em uso) por
    # uma fração de segundo. Tenta de novo algumas vezes antes de
    # desistir, em vez de falhar o download inteiro por causa disso.
    last_exc: Optional[Exception] = None
    for attempt in range(6):
        try:
            os.replace(tmp_path, dest_path)
            return
        except OSError as exc:
            last_exc = exc
            time.sleep(0.5 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def kokoro_ensure_model(
    models_dir: str = KOKORO_MODELS_DIR,
    variante: str = DEFAULT_KOKORO_VARIANT,
    precisao: str = DEFAULT_KOKORO_PRECISION,
) -> Tuple[str, str]:
    """Garante que os arquivos do modelo Kokoro pra essa combinação de
    `variante` ("v1.0" ou "v1.1-zh") + `precisao` ("fp32"/"fp16"/"int8")
    existem em `models_dir`, baixando do GitHub Releases do kokoro-onnx
    se faltar algum dos dois (cada combinação fica salva com um nome de
    arquivo próprio, então trocar de variante/precisão depois não
    baixa tudo de novo — só a combinação nova que ainda não existir).
    """
    if variante not in KOKORO_MODEL_VARIANTS:
        raise VoiceGeneratorError(
            f"Variante do Kokoro {variante!r} desconhecida — use uma de {sorted(KOKORO_MODEL_VARIANTS)}."
        )
    if precisao not in KOKORO_PRECISIONS:
        raise VoiceGeneratorError(
            f"Precisão do Kokoro {precisao!r} desconhecida — use uma de {sorted(KOKORO_PRECISIONS)}."
        )

    info_variante = KOKORO_MODEL_VARIANTS[variante]
    sufixo = KOKORO_PRECISIONS[precisao]["suffix"]
    nome_arquivo_modelo = f"{info_variante['model_prefix']}{sufixo}.onnx"
    nome_arquivo_vozes = info_variante["voices_file"]

    model_path = os.path.join(models_dir, nome_arquivo_modelo)
    voices_path = os.path.join(models_dir, nome_arquivo_vozes)
    try:
        if not os.path.exists(model_path):
            _download_file(KOKORO_RELEASE_BASE_URL + nome_arquivo_modelo, model_path)
        if not os.path.exists(voices_path):
            _download_file(KOKORO_RELEASE_BASE_URL + nome_arquivo_vozes, voices_path)
    except Exception as exc:  # noqa: BLE001
        raise VoiceGeneratorError(f"Falha ao baixar os arquivos do modelo Kokoro ({variante}/{precisao}): {exc}") from exc
    return model_path, voices_path


_kokoro_cache: Dict[str, Any] = {}  # "{variante}:{precisao}" -> instância Kokoro carregada


def _patch_kokoro_speed_dtype_bug(kokoro_instance: Any) -> None:
    """Corrige um bug do `kokoro-onnx` nas versões < 0.4.8 — a ÚNICA
    faixa que ainda funciona no Python 3.14 (a partir da 0.4.8 o
    pacote passou a exigir `Python <3.14`, então `pip install -U`
    acaba instalando a 0.4.7 mesmo pedindo a versão mais nova).

    Nessas versões antigas, quando o modelo usa o input `"input_ids"`
    (caso do `kokoro-v1.0.onnx` baixado por este script), o método
    `Kokoro._create_audio` manda o parâmetro `"speed"` pro ONNX Runtime
    como `int32`, mas o modelo espera `float32` — causando exatamente
    o erro "Unexpected input data type. Actual: (tensor(int32)),
    expected: (tensor(float))". Versões mais novas já corrigem isso
    lendo o dtype certo direto do modelo (função `input_dtypes` em
    `kokoro_onnx.session`); aqui a gente detecta se essa correção já
    existe e, se não existir, substitui só esse método com bug por uma
    cópia corrigida — sem precisar mexer no pacote instalado.
    """
    try:
        from kokoro_onnx.session import input_dtypes  # noqa: F401

        return  # versão já corrigida (>= 0.4.8) — nada a fazer
    except ImportError:
        pass

    import types

    import kokoro_onnx as _kokoro_pkg
    import numpy as np

    def _patched_create_audio(self, phonemes: str, voice, speed: float):
        log = _kokoro_pkg.log
        max_len = _kokoro_pkg.MAX_PHONEME_LENGTH
        sample_rate = _kokoro_pkg.SAMPLE_RATE

        if len(phonemes) > max_len:
            log.warning(f"Phonemes are too long, truncating to {max_len} phonemes")
        phonemes = phonemes[:max_len]
        start_t = time.time()
        tokens = np.array(self.tokenizer.tokenize(phonemes), dtype=np.int64)
        assert len(tokens) <= max_len, (
            f"Context length is {max_len}, but leave room for the pad token 0 "
            "at the start & end"
        )

        voice_row = voice[len(tokens)]
        tokens_list = [[0, *tokens, 0]]
        if "input_ids" in [i.name for i in self.sess.get_inputs()]:
            inputs = {
                "input_ids": tokens_list,
                "style": np.array(voice_row, dtype=np.float32),
                "speed": np.array([speed], dtype=np.float32),  # <- era np.int32
            }
        else:
            inputs = {
                "tokens": tokens_list,
                "style": voice_row,
                "speed": np.ones(1, dtype=np.float32) * speed,
            }

        audio = self.sess.run(None, inputs)[0]
        audio_duration = len(audio) / sample_rate
        create_duration = time.time() - start_t
        rtf = (create_duration / audio_duration) if audio_duration else 0.0
        log.debug(
            f"Created audio in length of {audio_duration:.2f}s for "
            f"{len(tokens)} tokens in {create_duration:.2f}s (RTF: {rtf:.2f})"
        )
        return audio, audio_duration

    kokoro_instance._create_audio = types.MethodType(_patched_create_audio, kokoro_instance)


def kokoro_load(
    models_dir: str = KOKORO_MODELS_DIR,
    variante: str = DEFAULT_KOKORO_VARIANT,
    precisao: str = DEFAULT_KOKORO_PRECISION,
):
    """Carrega (ou reaproveita, se já carregado com a mesma variante+
    precisão) o modelo Kokoro. Trocar `variante`/`precisao` carrega uma
    instância NOVA (cada combinação fica no cache separadamente, já que
    são arquivos .onnx diferentes — trocar de uma pra outra não é
    gratuito, mas também não precisa recarregar toda vez que você volta
    pra combinação anterior)."""
    cache_key = f"{variante}:{precisao}"
    if cache_key in _kokoro_cache:
        return _kokoro_cache[cache_key]
    try:
        from kokoro_onnx import Kokoro
    except ImportError as exc:
        raise VoiceGeneratorError(
            "Kokoro TTS não está instalado. Rode: pip install kokoro-onnx soundfile"
        ) from exc
    model_path, voices_path = kokoro_ensure_model(models_dir, variante=variante, precisao=precisao)
    try:
        instance = Kokoro(model_path, voices_path)
    except Exception as exc:  # noqa: BLE001
        raise VoiceGeneratorError(f"Falha ao carregar o modelo Kokoro ({variante}/{precisao}): {exc}") from exc
    _patch_kokoro_speed_dtype_bug(instance)
    _kokoro_cache[cache_key] = instance
    return instance


def kokoro_synthesize(
    texto: str,
    output_path: str,
    voz: str = "pf_dora",
    velocidade: float = 1.0,
    idioma: Optional[str] = None,
    models_dir: str = KOKORO_MODELS_DIR,
    variante: str = DEFAULT_KOKORO_VARIANT,
    precisao: str = DEFAULT_KOKORO_PRECISION,
) -> str:
    """Gera um `.wav` com o Kokoro. `idioma`: código esperado pelo
    kokoro-onnx (ex: "pt-br", "en-us") — se omitido, usa o idioma
    associado à voz escolhida em `KOKORO_VOZES` (qualquer voz fora
    dessa lista precisa informar `idioma` manualmente).

    `variante`: "v1.0" (padrão, 54 vozes) ou "v1.1-zh" (103 vozes,
    adiciona chinês/mandarim + mais 3 em inglês — arquivo maior).
    `precisao`: "fp32" (padrão, melhor qualidade), "fp16" (quase
    idêntica, menor) ou "int8" (mais leve/rápida, qualidade um pouco
    menor). Ver `KOKORO_MODEL_VARIANTS`/`KOKORO_PRECISIONS`.

    GPU: automática — se `onnxruntime-gpu` estiver instalado (em vez do
    `onnxruntime` comum), o Kokoro já roda na GPU sozinho, sem precisar
    de nenhum parâmetro aqui. Use `onnx_gpu_available()` pra conferir.
    """
    try:
        import soundfile as sf
    except ImportError as exc:
        raise VoiceGeneratorError("Faltou instalar 'soundfile'. Rode: pip install soundfile") from exc

    kokoro = kokoro_load(models_dir, variante=variante, precisao=precisao)

    lang = idioma or KOKORO_VOZES.get(voz, (None, None))[0] or "en-us"

    try:
        samples, sample_rate = kokoro.create(texto, voice=voz, speed=velocidade, lang=lang)
    except Exception as exc:  # noqa: BLE001
        raise VoiceGeneratorError(
            f"Falha ao gerar áudio com o Kokoro (voz={voz!r}, idioma={lang!r}): {exc}"
        ) from exc

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    sf.write(output_path, samples, sample_rate)
    return output_path


# ============================================================ #
# Realce de áudio ("audio enhance") pra gravações da própria voz —
# portado do recurso "Minha Voz" do projeto shortmaker. Deixa a
# gravação com um som mais limpo/"profissional" (tipo locução/podcast),
# tudo local via ffmpeg, sem nenhum serviço externo pago.
# ============================================================ #

_ARNNDN_MODEL_URL = "https://raw.githubusercontent.com/richardpl/arnndn-models/master/std.rnnn"
_ARNNDN_MODEL_CACHE = os.path.join(MODELS_DIR, "_cache_modelos", "std.rnnn")


def _caminho_modelo_arnndn() -> Optional[str]:
    """Modelo de rede neural treinado especificamente pra remover ruído
    de FALA, usado pelo filtro nativo `arnndn` do ffmpeg — bem mais
    eficaz e menos "abafante" que um denoiser clássico por FFT (tipo
    `afftdn`), porque foi treinado especificamente em voz humana em vez
    de aplicar um corte genérico de espectro. Baixa uma vez só (~300KB)
    e reaproveita pra sempre depois. Se não conseguir baixar (sem
    internet, por exemplo), devolve None — quem chama cai pro `afftdn`
    clássico como reserva, em vez de falhar.
    """
    if os.path.exists(_ARNNDN_MODEL_CACHE):
        return _ARNNDN_MODEL_CACHE
    try:
        import requests
        os.makedirs(os.path.dirname(_ARNNDN_MODEL_CACHE), exist_ok=True)
        resp = requests.get(_ARNNDN_MODEL_URL, timeout=30)
        resp.raise_for_status()
        with open(_ARNNDN_MODEL_CACHE, "wb") as f:
            f.write(resp.content)
        return _ARNNDN_MODEL_CACHE
    except Exception:  # noqa: BLE001
        return None


def cortar_silencio_pontas(audio_in: str, audio_out: str, limiar_db: float = -40.0, duracao_minima: float = 0.1) -> str:
    """Remove o silêncio do INÍCIO e do FIM de uma gravação (ex: aquele
    segundo de silêncio antes/depois de falar, comum em gravação de
    microfone), sem mexer em pausas no MEIO da fala.

    Técnica: aplica `silenceremove` pra tirar o silêncio do começo,
    inverte o áudio, aplica de nome (agora tirando o que era o final),
    e inverte de volta.

    Se o filtro falhar por qualquer motivo (ex: áudio 100% silencioso,
    sem nada pra "ancorar" o corte), copia o áudio original sem cortar
    nada em vez de levantar exceção — melhor manter o silêncio do que
    perder a gravação inteira.
    """
    filtro = (
        f"silenceremove=start_periods=1:start_duration={duracao_minima}:"
        f"start_threshold={limiar_db}dB:detection=peak,"
        "areverse,"
        f"silenceremove=start_periods=1:start_duration={duracao_minima}:"
        f"start_threshold={limiar_db}dB:detection=peak,"
        "areverse"
    )
    os.makedirs(os.path.dirname(audio_out) or ".", exist_ok=True)
    resultado = subprocess.run(
        ["ffmpeg", "-y", "-i", audio_in, "-af", filtro, audio_out],
        capture_output=True, timeout=60,
    )
    if resultado.returncode != 0 or not os.path.exists(audio_out):
        if not os.path.exists(audio_in):
            raise VoiceGeneratorError(f"Áudio de origem não encontrado: {audio_in!r}")
        import shutil as _shutil
        try:
            _shutil.copy(audio_in, audio_out)
        except OSError as exc:
            raise VoiceGeneratorError(f"Falha ao cortar o silêncio das pontas: {exc}") from exc
    return audio_out


def aplicar_realce_de_voz(audio_in: str, audio_out: str) -> str:
    """"Audio enhance" pra gravação própria — deixa a voz com um som
    mais limpo e "profissional" (tipo locução/podcast/Adobe Enhance
    Speech), aplicando uma cadeia de filtros, tudo local:

      1. Passa-alta em 80Hz — corta ruído grave de fundo (zumbido de
         ventilador, trânsito etc) sem afetar a voz.
      2. `arnndn` — redutor de ruído por REDE NEURAL (mesma categoria
         técnica usada por ferramentas tipo Adobe Enhance Speech),
         nativo do ffmpeg. Bem mais eficaz que um denoiser clássico, e
         sem o efeito colateral de "abafar" a voz que denoisers por FFT
         costumam ter. Sem conseguir baixar o modelo, cai
         automaticamente pro `afftdn` clássico como reserva.
      3. Equalização de clareza — realça a faixa de presença (3kHz,
         onde a inteligibilidade da voz mora) e a faixa de "ar"/brilho
         (7kHz+, resolve a sensação de "abafado" quando a gravação tem
         pouco agudo), e reduz um pouco a faixa grave (200Hz) que
         costuma soar "encaixotada" em microfones de celular/notebook.
      4. `acompressor` — compressão de faixa dinâmica, deixa o volume
         mais consistente ao longo da fala (menos picos e vales),
         parecido com o que rádio/podcast usam.
      5. `loudnorm` — normalização de loudness pro padrão de streaming
         (-16 LUFS), deixando o nível final consistente.

    Devolve `audio_out`. Levanta `VoiceGeneratorError` se o ffmpeg
    falhar (o original NUNCA é sobrescrito — sempre grava num arquivo
    separado).
    """
    modelo_rnn = _caminho_modelo_arnndn()

    partes_filtro = ["highpass=f=80"]
    diretorio_trabalho = None
    if modelo_rnn is not None:
        # só o NOME do arquivo (não o caminho completo) + roda o ffmpeg
        # com a pasta do modelo como diretório de trabalho -- evita
        # problema de escapar caracteres especiais do caminho (ex:
        # letra de unidade do Windows, "E:") dentro da string de filtro.
        partes_filtro.append(f"arnndn=model={os.path.basename(modelo_rnn)}:mix=1")
        diretorio_trabalho = os.path.dirname(modelo_rnn)
    else:
        partes_filtro.append("afftdn=nr=12:nf=-25")
    partes_filtro += [
        "equalizer=f=3000:t=q:w=1.5:g=3",
        "treble=g=4:f=7000",
        "equalizer=f=200:t=q:w=1.5:g=-2",
        "acompressor=threshold=-18dB:ratio=3:attack=5:release=80:makeup=2",
        "loudnorm=I=-16:TP=-1.5:LRA=11",
    ]
    filtro = ",".join(partes_filtro)

    os.makedirs(os.path.dirname(audio_out) or ".", exist_ok=True)
    resultado = subprocess.run(
        ["ffmpeg", "-y", "-i", os.path.abspath(audio_in), "-af", filtro,
         "-ar", "44100", "-ac", "1", os.path.abspath(audio_out)],
        capture_output=True, cwd=diretorio_trabalho, timeout=120,
    )
    if resultado.returncode != 0 or not os.path.exists(audio_out):
        raise VoiceGeneratorError(
            f"ffmpeg não conseguiu aplicar o realce de voz: "
            f"{resultado.stderr.decode(errors='replace')[-400:]}"
        )
    return audio_out


# ==================================================================== #
# 🐟 Fish Audio S2 (fish-speech) — clonagem de voz + tags de emoção ([whisper], [excited]…) em 80+ idiomas (PT incluso)
# ==================================================================== #
# O modelo (S2 Pro, 4B parâmetros) NÃO roda dentro do site: ou você sobe o servidor do fish-speech
# (github.com/fishaudio/fish-speech, `python tools/api_server.py ... --listen 127.0.0.1:8080`; pede ~24 GB de
# VRAM e Linux/WSL) ou usa a API paga da Fish Audio (fish.audio, com chave). O site só manda o texto + a voz de
# referência por HTTP (mesmo formato nos dois: POST /v1/tts).
#
# ⚠️ LICENÇA: os pesos do S2 são "Fish Audio Research License" — uso COMERCIAL (ex.: vídeo monetizado) precisa de
# licença à parte da Fish Audio. A API paga (modo "nuvem") segue os termos/planos da Fish Audio.

FISH_URL_PADRAO = "http://127.0.0.1:8080"
FISH_URL_NUVEM = "https://api.fish.audio"
FISH_MODELOS_NUVEM = ("s2-pro", "s2.1-pro", "s1")
FISH_LIMITE_CARACTERES_POR_CHAMADA = 400   # pedaços menores = voz mais estável (o servidor tem limite de tokens)
FISH_MAX_REFERENCIAS = 3
# Exemplos de tags (o S2 aceita QUALQUER descrição curta entre colchetes, ex.: [sussurrando bem baixinho]).
FISH_TAGS_EXEMPLO = ("[whisper]", "[excited]", "[angry]", "[sad]", "[laughing]", "[sigh]", "[shouting]",
                     "[pause]", "[emphasis]", "[pitch up]", "[pitch down]", "[clearing throat]")


FISH_TAGS_CONHECIDAS = {
    "whisper", "whispering", "excited", "angry", "sad", "laughing", "laugh", "chuckle", "sigh", "shouting", "pause",
    "emphasis", "pitch up", "pitch down", "clearing throat", "happy", "surprised", "scared", "crying", "sarcastic",
    "calm", "serious", "nervous", "disgusted", "tired", "gasp", "breath", "inhale", "exhale", "low voice", "loud",
    "sussurrando", "sussurro", "animado", "empolgado", "bravo", "irritado", "triste", "rindo", "risada", "suspiro",
    "gritando", "pausa", "ênfase", "feliz", "surpreso", "assustado", "chorando", "sarcástico", "calmo", "sério",
    "nervoso", "cansado", "respiração",
}


def fish_config(**sobrepor: Any) -> Dict[str, Any]:
    """Modo/URL/chave do Fish: o que vier em `sobrepor` > a config do site (site_config.json) > variáveis de ambiente."""
    cfg: Dict[str, Any] = {}
    try:
        from site_config import load_site_config  # roda dentro do site (também no processo filho: sys.path vem junto)
        cfg = load_site_config() or {}
    except Exception:  # noqa: BLE001
        cfg = {}
    modo = str(sobrepor.get("modo") or cfg.get("fish_modo") or os.environ.get("FISH_MODO") or "local").lower()
    modo = modo if modo in ("local", "nuvem") else "local"
    url = str(sobrepor.get("url") or (cfg.get("fish_url") if modo == "local" else "") or os.environ.get("FISH_URL") or "")
    url = (url or (FISH_URL_NUVEM if modo == "nuvem" else FISH_URL_PADRAO)).rstrip("/")
    chave = str(sobrepor.get("api_key") or (cfg.get("fish_api_key") if modo == "nuvem" else cfg.get("fish_api_key_local"))
                or os.environ.get("FISH_API_KEY") or "")
    modelo = str(sobrepor.get("modelo") or cfg.get("fish_modelo") or "s2-pro")
    return {"modo": modo, "url": url, "api_key": chave, "modelo": modelo}


def _fish_cabecalhos(c: Dict[str, Any], msgpack_: bool = True) -> Dict[str, str]:
    h = {"Content-Type": "application/msgpack" if msgpack_ else "application/json"}
    if c.get("api_key"):
        h["Authorization"] = f"Bearer {c['api_key']}"
    if c.get("modo") == "nuvem" and c.get("modelo"):
        h["model"] = c["modelo"]
    return h


def fish_status(timeout: float = 5.0, **sobrepor: Any) -> Dict[str, Any]:
    """Confere se o Fish responde (servidor local: GET /v1/health · nuvem: só confere que tem chave)."""
    c = fish_config(**sobrepor)
    if c["modo"] == "nuvem":
        return {"ok": bool(c["api_key"]), "modo": "nuvem", "url": c["url"],
                "msg": "chave configurada" if c["api_key"] else "falta a chave da API da Fish Audio (Configurações)"}
    try:
        import requests
        r = requests.get(c["url"] + "/v1/health", headers=_fish_cabecalhos(c), timeout=timeout)
        return {"ok": r.ok, "modo": "local", "url": c["url"], "msg": "servidor no ar" if r.ok else f"HTTP {r.status_code}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "modo": "local", "url": c["url"],
                "msg": f"o servidor do fish-speech não respondeu em {c['url']} ({type(exc).__name__})"}


def _fish_texto_da_referencia(audio: str, idioma: Optional[str] = None) -> str:
    """O Fish clona melhor sabendo O QUE é dito no áudio de referência: usa `<audio>.txt` se existir; se não,
    transcreve com o Whisper do site (uma vez só — guarda no `.txt` do lado)."""
    lado = audio + ".txt"
    if os.path.exists(lado):
        try:
            with open(lado, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""
    texto = ""
    try:
        from whisper_transcribe import transcribe_audio
        texto = " ".join(str(s.get("text") or "").strip() for s in transcribe_audio(audio, language=idioma or None)).strip()
    except Exception:  # noqa: BLE001 — sem Whisper: manda sem o texto (clona um pouco pior, mas funciona)
        texto = ""
    if texto:
        try:
            with open(lado, "w", encoding="utf-8") as f:
                f.write(texto)
        except OSError:
            pass
    return texto


def _fish_referencias(speaker_wav: Any, voice_profile: Optional[str], texto_referencia: str,
                      idioma: Optional[str]) -> List[Dict[str, Any]]:
    if speaker_wav:
        arquivos = list(speaker_wav) if isinstance(speaker_wav, (list, tuple)) else [speaker_wav]
    elif voice_profile:
        arquivos = caminho_perfil_de_voz(voice_profile)
    else:
        return []
    refs = []
    for k, a in enumerate(arquivos[:FISH_MAX_REFERENCIAS]):
        pronto = _preparar_audio_referencia(a, duracao_max_segundos=30.0)
        with open(pronto, "rb") as f:
            dados = f.read()
        if pronto != a:
            try:
                os.remove(pronto)
            except OSError:
                pass
        txt = texto_referencia.strip() if (texto_referencia and k == 0 and len(arquivos) == 1) else _fish_texto_da_referencia(a, idioma)
        refs.append({"audio": dados, "text": txt})
    return refs


def _fish_pedir(c: Dict[str, Any], corpo: Dict[str, Any], timeout: float) -> bytes:
    import requests
    try:
        import msgpack
        dados, usa_msgpack = msgpack.packb(corpo, use_bin_type=True), True
    except ImportError:
        if c["modo"] == "nuvem" and corpo.get("references"):
            raise VoiceGeneratorError("Pra clonar voz pela API da Fish Audio instale o msgpack: pip install msgpack")
        import base64
        corpo = dict(corpo, references=[{"audio": base64.b64encode(r["audio"]).decode(), "text": r["text"]}
                                        for r in corpo.get("references") or []])
        dados, usa_msgpack = json.dumps(corpo).encode(), False
    try:
        r = requests.post(c["url"] + "/v1/tts", data=dados, headers=_fish_cabecalhos(c, usa_msgpack), timeout=timeout)
    except requests.exceptions.ConnectionError:
        if c["modo"] == "nuvem":
            raise VoiceGeneratorError("Não consegui falar com a API da Fish Audio (sem internet?).")
        raise VoiceGeneratorError(
            f"O servidor do Fish Audio S2 não está rodando em {c['url']}. Suba o fish-speech "
            "(python tools/api_server.py --llama-checkpoint-path checkpoints/s2-pro --decoder-checkpoint-path "
            "checkpoints/s2-pro/codec.pth --listen 127.0.0.1:8080) ou troque pra API da Fish Audio nas Configurações.")
    except requests.exceptions.Timeout:
        raise VoiceGeneratorError(f"O Fish Audio S2 demorou mais de {int(timeout)}s pra responder um pedaço do texto.")
    if r.status_code == 401:
        raise VoiceGeneratorError("O Fish recusou a chave (401) — confira a chave da API nas Configurações.")
    if r.status_code == 402:
        raise VoiceGeneratorError("A conta da Fish Audio está sem créditos (402).")
    if not r.ok:
        raise VoiceGeneratorError(f"O Fish Audio S2 deu erro HTTP {r.status_code}: {r.text[:300]}")
    if len(r.content) < 100:
        raise VoiceGeneratorError("O Fish Audio S2 devolveu um áudio vazio.")
    return r.content


def fish_s2_synthesize(
    texto: str,
    output_path: str,
    speaker_wav: Any = None,
    voice_profile: Optional[str] = None,
    texto_referencia: str = "",
    reference_id: str = "",
    idioma: Optional[str] = "pt",
    velocidade: float = 1.0,
    temperatura: float = 0.8,
    top_p: float = 0.8,
    seed: Optional[int] = 1234,
    timeout_por_pedaco: float = 600.0,
    use_gpu: Optional[bool] = None,  # ignorado (quem usa a GPU é o servidor do Fish)
    **config: Any,
) -> str:
    """Gera um `.wav` com o Fish Audio S2 — clonagem zero-shot (10–30s de referência) e TAGS de emoção/efeito
    entre colchetes no próprio texto, em qualquer ponto: "[excited] Você não vai acreditar! [whisper] É segredo."

    Voz: `speaker_wav` (áudio enviado), `voice_profile` (o mesmo perfil de voz do XTTS/Chatterbox) ou
    `reference_id` (uma voz salva na conta da Fish Audio, modo nuvem). Sem nada: voz padrão do modelo.
    `texto_referencia`: o que é dito no áudio de referência (sem ele, o Whisper do site transcreve sozinho).
    `config` (opcional): modo="local"/"nuvem", url, api_key, modelo — senão vem das Configurações do site.
    Texto longo é dividido em pedaços (frases inteiras) e juntado num áudio só; a mesma `seed` em todos os
    pedaços deixa a voz igual do começo ao fim."""
    texto = (texto or "").strip()
    if not texto:
        raise VoiceGeneratorError("Texto vazio — nada pra narrar.")
    c = fish_config(**config)
    refs = _fish_referencias(speaker_wav, voice_profile, texto_referencia, idioma)
    pedacos = _dividir_texto_para_xtts(texto, FISH_LIMITE_CARACTERES_POR_CHAMADA)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    pasta_tmp = tempfile.mkdtemp(prefix="fish_")
    try:
        partes = []
        for i, pedaco in enumerate(pedacos):
            corpo: Dict[str, Any] = {"text": pedaco, "format": "wav", "references": refs, "normalize": True,
                                     "chunk_length": 200, "temperature": float(temperatura), "top_p": float(top_p),
                                     "max_new_tokens": 2048}
            if seed is not None:
                corpo["seed"] = int(seed)
            if reference_id and not refs:
                corpo["reference_id"] = reference_id
            if c["modo"] == "nuvem":
                corpo["prosody"] = {"speed": max(0.5, min(2.0, float(velocidade or 1.0)))}
            destino = os.path.join(pasta_tmp, f"p{i:04d}.wav")
            with open(destino, "wb") as f:
                f.write(_fish_pedir(c, corpo, timeout_por_pedaco))
            partes.append(destino)
        if len(partes) > 1:  # pedaços podem vir com cabeçalhos diferentes: normaliza antes de juntar
            normalizados = []
            for pth in partes:
                n = pth[:-4] + "_n.wav"
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", pth, "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", n],
                               capture_output=True, timeout=120)
                normalizados.append(n if os.path.exists(n) else pth)
            partes = normalizados
        bruto = os.path.join(pasta_tmp, "junto.wav")
        _concatenar_wavs(partes, bruto)
        vel = float(velocidade or 1.0)
        if c["modo"] == "local" and abs(vel - 1.0) > 0.01:  # o servidor local não tem "velocidade": ajusta no ffmpeg
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", bruto, "-filter:a", f"atempo={max(0.5, min(2.0, vel))}",
                                output_path], capture_output=True, timeout=300)
            if r.returncode != 0:
                shutil.copy(bruto, output_path)
        else:
            shutil.copy(bruto, output_path)
    finally:
        shutil.rmtree(pasta_tmp, ignore_errors=True)
    return output_path


ENGINES: Dict[str, Dict[str, Any]] = {
    "piper": {
        "label": "Piper TTS",
        "descricao": "Leve e rápido, roda bem em CPU. Menos expressivo que os outros.",
        "instalar": "pip install piper-tts",
    },
    "xtts": {
        "label": "XTTS v2 (Coqui)",
        "descricao": "O mais expressivo, com clonagem de voz — mas pesado; GPU muito recomendada.",
        "instalar": "pip install coqui-tts torch torchaudio",
    },
    "chatterbox": {
        "label": "Chatterbox TTS (Resemble AI)",
        "descricao": "Clonagem de voz por zero-shot igual o XTTS v2, com controle de intensidade "
                      "emocional — open-source (MIT), 23 idiomas incluindo português. GPU recomendada.",
        "instalar": "pip install chatterbox-tts",
    },
    "chatterbox_turbo": {
        "label": "Chatterbox Turbo (Resemble AI) — só inglês",
        "descricao": "Variante mais leve/rápida do Chatterbox, SÓ EM INGLÊS — mas é a única com tags "
                      "paralinguísticas (ex: [laugh], [sigh], [whispering]) direto no texto. "
                      "GPU recomendada.",
        "instalar": "pip install chatterbox-tts",
    },
    "fish_s2": {
        "label": "Fish Audio S2 (clonagem + tags de emoção)",
        "descricao": "Clona a voz (10–30s de referência) e entende TAGS de emoção em qualquer ponto do texto — "
                      "[whisper], [excited], [angry], [laughing], [sigh]… — em 80+ idiomas, português incluso. "
                      "Roda num servidor à parte (fish-speech, ~24 GB de VRAM, Linux/WSL) ou pela API paga da Fish Audio. "
                      "⚠️ Os pesos abertos são só pra uso NÃO comercial.",
        "instalar": "pip install requests msgpack  (+ o servidor: github.com/fishaudio/fish-speech, ou a API da Fish Audio)",
    },
    "kokoro": {
        "label": "Kokoro",
        "descricao": "Equilíbrio entre leveza e qualidade, com vozes prontas em vários idiomas (incl. PT-BR).",
        "instalar": "pip install kokoro-onnx soundfile",
    },
}


def gerar_audio(engine: str, texto: str, output_path: str, **kwargs: Any) -> str:
    """Ponto de entrada único: gera o áudio com o motor pedido.

    `engine`: "piper", "xtts", "chatterbox", "chatterbox_turbo" ou "kokoro".
    `texto`: o que vai ser narrado.
    `output_path`: caminho do `.wav` de saída.
    `**kwargs`: repassado pra função específica do motor — ver
        `piper_synthesize`, `xtts_synthesize`, `chatterbox_synthesize`,
        `chatterbox_turbo_synthesize` e `kokoro_synthesize` acima pra
        saber quais parâmetros cada um aceita (`nome_voz`/`voz`/
        `speaker`, `velocidade`, `idioma`, `use_gpu` etc — os nomes
        variam um pouco de motor pra motor porque cada biblioteca usa
        termos próprios).
    """
    if not texto or not texto.strip():
        raise VoiceGeneratorError("Texto vazio — nada pra narrar.")

    engine = (engine or "").strip().lower()
    if engine == "teste" and os.environ.get("VOICE_GENERATOR_TESTE_MOTOR_FALSO") == "1":  # só nos testes automatizados
        _gerar_teste_falso(texto, output_path)
        return output_path
    if engine == "piper":
        return piper_synthesize(texto, output_path, **kwargs)
    if engine == "xtts":
        return xtts_synthesize(texto, output_path, **kwargs)
    if engine == "chatterbox":
        return chatterbox_synthesize(texto, output_path, **kwargs)
    if engine == "chatterbox_turbo":
        return chatterbox_turbo_synthesize(texto, output_path, **kwargs)
    if engine == "fish_s2":
        return fish_s2_synthesize(texto, output_path, **kwargs)
    if engine == "kokoro":
        return kokoro_synthesize(texto, output_path, **kwargs)
    raise VoiceGeneratorError(
        f"Motor de voz desconhecido: {engine!r} — use um de {sorted(ENGINES)}."
    )

def _processo_gerar_audio(engine: str, texto: str, output_path: str, kwargs: Dict[str, Any], fila) -> None:
    """Alvo do processo filho em `gerar_audio_isolado()` — PRECISA ser
    uma função de nível de módulo (não uma closure/lambda) pra funcionar
    com `multiprocessing` no modo "spawn" (obrigatório no Windows, e o
    mais seguro em qualquer sistema aqui — evita herdar estado de
    threads/contexto de GPU já aberto no processo pai, que o modo
    "fork" herdaria e podia deixar tudo instável)."""
    if os.environ.get("VOICE_GENERATOR_TESTE_FORCAR_CRASH") == "1":
        # gancho SÓ pra teste automatizado (ver test_voice_generator.py)
        # -- simula um crash nativo de verdade (sem exceção Python
        # nenhuma pra capturar, igual um segfault do PyTorch faria) pra
        # provar que `gerar_audio_isolado()` protege o processo pai
        # disso. Nunca ativa sozinho: precisa dessa variável de
        # ambiente específica, que nada no site define.
        os._exit(139)
    if os.environ.get("VOICE_GENERATOR_TESTE_FORCAR_TRAVAMENTO") == "1":
        # mesma ideia acima, mas simulando um motor que TRAVA sem
        # nunca terminar (nem sucesso, nem crash) -- testa o caminho
        # de timeout de `gerar_audio_isolado()`.
        import time as _time
        _time.sleep(3600)
    try:
        gerar_audio(engine, texto, output_path, **kwargs)
        fila.put(("ok", None))
    except VoiceGeneratorError as exc:
        fila.put(("erro", str(exc)))
    except Exception as exc:  # noqa: BLE001
        fila.put(("erro", f"{type(exc).__name__}: {exc}"))


def _duracao_legivel(seg: float) -> str:
    seg = float(seg)
    if seg >= 3600:
        h, resto = divmod(int(round(seg)), 3600)
        return f"{h}h" + (f"{resto // 60:02d}" if resto >= 60 else "")
    if seg >= 120:
        return f"{seg / 60:.0f} min"
    return f"{seg:.0f}s"


def _memoria_antes_do_processo() -> None:
    """🧠 v84_313: o motor de voz roda num processo novo (carrega o modelo do zero): espera RAM livre e solta os outros modelos antes."""
    try:
        import os as _o
        import sys as _s
        _raiz = _o.path.dirname(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
        if _raiz not in _s.path:
            _s.path.insert(0, _raiz)
        import memoria_ram
        memoria_ram.espera_ram()
    except Exception:  # noqa: BLE001  (controle de memória nunca derruba a geração)
        pass


def gerar_audio_isolado(engine: str, texto: str, output_path: str, timeout: float = 7200.0, **kwargs: Any) -> str:
    """Mesma coisa que `gerar_audio()`, mas rodando o motor num
    PROCESSO SEPARADO — se o motor travar o interpretador Python
    inteiro (ex: um crash nativo do PyTorch/XTTS, sem exceção Python
    nenhuma pra capturar — acontece de verdade com combinações
    incompatíveis de versão do Python com as libs nativas), só esse
    processo FILHO morre; o processo principal (o servidor Flask)
    continua de pé e devolve um erro claro em vez de cair junto.

    Use isso em vez de `gerar_audio()` direto em qualquer lugar que
    rode dentro do servidor (evita que uma geração de voz travada
    derrube o site inteiro); `gerar_audio()` continua existindo pra uso
    direto via CLI/scripts, onde isolar em processo não traz benefício
    nenhum.
    """
    if os.environ.get("VOICE_GENERATOR_DESATIVAR_ISOLAMENTO") == "1":
        # SÓ pra suíte de testes automatizados (ver conftest.py) --
        # roda direto no mesmo processo, sem isolar, porque um
        # `monkeypatch`/mock de `gerar_audio()` feito no processo do
        # teste não é visto por um processo FILHO de verdade (o
        # isolamento por multiprocessing cria um interpretador Python
        # novo do zero -- o mock simplesmente não existe lá). Nunca
        # definida em produção -- lá sempre isola de verdade.
        return gerar_audio(engine, texto, output_path, **kwargs)

    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    fila: Any = ctx.Queue()
    processo = ctx.Process(target=_processo_gerar_audio, args=(engine, texto, output_path, kwargs, fila))
    _memoria_antes_do_processo()
    processo.start()
    processo.join(timeout)

    if processo.is_alive():
        processo.terminate()
        processo.join(5)
        raise VoiceGeneratorError(
            f"A geração travou e não terminou em {_duracao_legivel(timeout)} — foi cancelada. "
            f"Isso pode indicar um texto longo demais pro motor escolhido, ou o motor preso "
            f"esperando algo (ex: baixando um modelo grande pela primeira vez)."
        )

    if processo.exitcode != 0:
        if processo.exitcode in (3221225477, -1073741819, 3221226505, -1073740791, 3221225725, -1073741571):
            raise VoiceGeneratorError(  # 🎙 v84_364: acesso inválido à memória / estouro de pilha (Windows)
                f"O motor de voz travou o processo (código de saída {processo.exitcode}: acesso inválido à memória) antes de "
                f"conseguir gerar o áudio. Quase sempre é a placa de vídeo com DUAS gerações ao mesmo tempo (2 processos de "
                f"PyTorch na mesma GPU às vezes derrubam um ao outro) ou a memória (RAM/VRAM) acabando. O site tenta de novo "
                f"sozinho, uma de cada vez. Se continuar: no Gerador de voz, em 'quantos ao mesmo tempo', escolha 1 e feche "
                f"outros programas que usam a placa (jogos, navegador com muitas abas de vídeo)."
            )
        raise VoiceGeneratorError(
            f"O motor de voz travou o processo (código de saída {processo.exitcode}) antes de "
            f"conseguir gerar o áudio — geralmente é um crash NATIVO (não uma exceção Python), "
            f"comum quando a versão do Python instalada é mais nova do que o PyTorch suporta "
            f"oficialmente ainda. Se você está numa versão de Python bem recente (ex: 3.14+), tente "
            f"rodar o site com Python 3.11 ou 3.12 — são as versões com suporte mais maduro do "
            f"PyTorch hoje."
        )

    try:
        status, detalhe = fila.get_nowait()
    except Exception:  # noqa: BLE001
        # o processo terminou com código 0 mas não colocou nada na fila
        # -- não deveria acontecer, mas não trava o site por causa disso.
        return output_path
    if status == "erro":
        raise VoiceGeneratorError(detalhe)
    return output_path


def _processo_gerar_lote(itens, fila) -> None:
    """Alvo do processo filho em `gerar_audio_isolado_lote()`: gera TODAS as
    falas no mesmo processo — o modelo (e o perfil de voz) é carregado na 1ª
    fala e fica no cache do processo pras seguintes (`_chatterbox_turbo_cache`,
    `_xtts_cache`...). Avisa o pai a cada fala pronta."""
    for i, (engine, texto, output_path, kwargs) in enumerate(itens):
        try:
            gerar_audio(engine, texto, output_path, **kwargs)
            fila.put(("ok", i, ""))
        except BaseException as exc:  # noqa: BLE001 -- uma fala ruim não derruba o lote
            fila.put(("erro", i, f"{type(exc).__name__}: {exc}"))
    fila.put(("fim", -1, ""))


def gerar_audio_isolado_lote(itens, timeout_por_item: float = 7200.0, on_progresso=None) -> Dict[int, str]:
    """Gera várias falas NUM PROCESSO SÓ (isolado do servidor, como
    `gerar_audio_isolado`), sem recarregar o modelo a cada fala.

    `itens`: lista de (engine, texto, output_path, kwargs). Ordene por voz
    (todas as falas de um personagem juntas) pra trocar de perfil o mínimo.
    `on_progresso(i, erro_ou_None)` é chamado a cada fala terminada.
    Devolve {indice: mensagem_de_erro} das falas que falharam ({} = tudo certo)."""
    itens = list(itens)
    erros: Dict[int, str] = {}
    if not itens:
        return erros
    if os.environ.get("VOICE_GENERATOR_DESATIVAR_ISOLAMENTO") == "1":  # só nos testes (ver gerar_audio_isolado)
        for i, (engine, texto, output_path, kwargs) in enumerate(itens):
            try:
                gerar_audio(engine, texto, output_path, **kwargs)
                if on_progresso:
                    on_progresso(i, None)
            except Exception as exc:  # noqa: BLE001
                erros[i] = str(exc)
                if on_progresso:
                    on_progresso(i, erros[i])
        return erros

    import multiprocessing
    import queue as _queue

    ctx = multiprocessing.get_context("spawn")
    fila: Any = ctx.Queue()
    processo = ctx.Process(target=_processo_gerar_lote, args=(itens, fila))
    _memoria_antes_do_processo()
    processo.start()
    pendentes = set(range(len(itens)))
    try:
        ultimo = time.monotonic()
        while pendentes:
            try:
                # espera em fatias curtas: com o limite de 2h por fala, um crash
                # do processo não pode deixar a tela esperando as 2h inteiras
                status, i, detalhe = fila.get(timeout=min(5.0, max(0.1, timeout_por_item)))
            except _queue.Empty:
                vivo = processo.is_alive()
                if vivo and time.monotonic() - ultimo < timeout_por_item:
                    continue
                motivo = (f"travou (passou de {_duracao_legivel(timeout_por_item)} numa fala)" if vivo
                          else f"fechou sozinho (código {processo.exitcode} — crash nativo do motor?)")
                for k in sorted(pendentes):
                    erros[k] = f"O motor de voz {motivo}."
                break
            ultimo = time.monotonic()
            if status == "fim":
                for k in sorted(pendentes):
                    erros.setdefault(k, "O motor de voz terminou sem gerar esta fala.")
                break
            pendentes.discard(i)
            if status == "erro":
                erros[i] = detalhe
            if on_progresso:
                on_progresso(i, erros.get(i))
    finally:
        processo.join(5)
        if processo.is_alive():
            processo.terminate()
            processo.join(5)
    return erros


# ---------------------------------------------------------------------------
# ⚡ VÁRIAS INSTÂNCIAS DO MOTOR AO MESMO TEMPO (v84_103)
# ---------------------------------------------------------------------------
def _gerar_teste_falso(texto: str, output_path: str) -> None:
    """Motor "teste" — SÓ com VOICE_GENERATOR_TESTE_MOTOR_FALSO=1 (testes automatizados): um seno com duração
    proporcional ao texto, pra testar o paralelismo em processos de verdade sem modelo nenhum."""
    dur = max(0.2, min(20.0, len(texto) / 60.0))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=f=330:d={dur:.2f}", "-ar", "24000",
                    "-ac", "1", output_path], check=True, capture_output=True, timeout=60)
    if os.environ.get("VOICE_GENERATOR_TESTE_LENTO"):
        time.sleep(float(os.environ["VOICE_GENERATOR_TESTE_LENTO"]))


def _gerar_ou_teste(engine: str, texto: str, output_path: str, kwargs: Dict[str, Any]) -> None:
    if engine == "teste" and os.environ.get("VOICE_GENERATOR_TESTE_MOTOR_FALSO") == "1":
        _gerar_teste_falso(texto, output_path)
        return
    gerar_audio(engine, texto, output_path, **kwargs)


def _processo_trabalhador(itens, tarefas, fila, wid: int) -> None:
    """Uma INSTÂNCIA do motor: carrega o modelo uma vez (na 1ª fala) e vai pegando o próximo pedaço da fila de
    tarefas até ela acabar — as instâncias rápidas pegam mais pedaços (balanceamento sozinho)."""
    import queue as _queue
    while True:
        try:
            i = tarefas.get(timeout=2)
        except _queue.Empty:
            break
        if i is None:
            break
        engine, texto, output_path, kwargs = itens[i]
        fila.put(("inicio", i, wid, ""))
        try:
            _gerar_ou_teste(engine, texto, output_path, kwargs)
            fila.put(("ok", i, wid, ""))
        except BaseException as exc:  # noqa: BLE001 -- um pedaço ruim não derruba a instância
            fila.put(("erro", i, wid, f"{type(exc).__name__}: {exc}"))
    fila.put(("fim", -1, wid, ""))


def gerar_audio_isolado_paralelo(itens, instancias: int = 2, timeout_por_item: float = 7200.0, on_progresso=None,
                                 intervalo_inicio: float = 3.0) -> Dict[int, str]:
    """Como `gerar_audio_isolado_lote`, mas com VÁRIAS instâncias do motor (processos separados, cada um com o seu
    modelo carregado) gerando pedaços diferentes AO MESMO TEMPO. As instâncias começam com `intervalo_inicio`
    segundos de diferença (não carregam o modelo todas juntas — pico de memória/disco).

    `on_progresso(i, erro_ou_None, instancia)` a cada pedaço terminado. Devolve {indice: erro} ({} = tudo certo).
    Se uma instância cai (ex.: faltou VRAM), o pedaço que ela estava gerando volta pra fila das outras."""
    itens = list(itens)
    erros: Dict[int, str] = {}
    if not itens:
        return erros
    instancias = max(1, min(int(instancias or 1), len(itens), 8))
    if instancias == 1:
        return gerar_audio_isolado_lote(itens, timeout_por_item, on_progresso=(lambda i, e: on_progresso(i, e, 1)) if on_progresso else None)
    if os.environ.get("VOICE_GENERATOR_DESATIVAR_ISOLAMENTO") == "1" and os.environ.get("VOICE_GENERATOR_TESTE_MOTOR_FALSO") != "1":
        for i, (engine, texto, output_path, kwargs) in enumerate(itens):  # só nos testes com mock (ver gerar_audio_isolado)
            try:
                gerar_audio(engine, texto, output_path, **kwargs)
            except Exception as exc:  # noqa: BLE001
                erros[i] = str(exc)
            if on_progresso:
                on_progresso(i, erros.get(i), 1 + i % instancias)
        return erros

    import multiprocessing
    import queue as _queue

    ctx = multiprocessing.get_context("spawn")
    tarefas: Any = ctx.Queue()
    fila: Any = ctx.Queue()
    for i in range(len(itens)):
        tarefas.put(i)
    procs: Dict[int, Any] = {}
    fazendo: Dict[int, int] = {}       # instância -> pedaço que ela está gerando
    desde: Dict[int, float] = {}       # instância -> quando começou o pedaço atual
    pendentes = set(range(len(itens)))
    terminaram: set = set()
    proximo_inicio = 0.0

    reinicios = 0

    def iniciar() -> None:
        wid = len(procs) + 1
        pr = ctx.Process(target=_processo_trabalhador, args=(itens, tarefas, fila, wid))
        _memoria_antes_do_processo()
        pr.start()
        procs[wid] = pr

    iniciar()
    proximo_inicio = time.monotonic() + intervalo_inicio
    try:
        while pendentes:
            vivos = [w for w, pr in procs.items() if w not in terminaram]
            if len(procs) < instancias and time.monotonic() >= proximo_inicio:
                iniciar()
                proximo_inicio = time.monotonic() + intervalo_inicio
            elif not vivos and len(procs) >= instancias:
                if reinicios >= instancias:  # já reabriu instâncias demais: desiste do que sobrou
                    for k in sorted(pendentes):
                        erros[k] = "Todas as instâncias do motor de voz fecharam (crash nativo ou falta de memória da placa?)."
                    break
                reinicios += 1
                iniciar()
            try:
                status, i, wid, detalhe = fila.get(timeout=1.0)
            except _queue.Empty:
                agora = time.monotonic()
                for w, pr in list(procs.items()):
                    if w in terminaram:
                        continue
                    travou = w in fazendo and agora - desde.get(w, agora) > timeout_por_item
                    if not pr.is_alive() or travou:
                        if travou:
                            pr.terminate()
                        terminaram.add(w)
                        k = fazendo.pop(w, None)
                        if k is not None and k in pendentes:
                            if travou:
                                erros[k] = f"A instância {w} travou (passou de {_duracao_legivel(timeout_por_item)} neste pedaço)."
                                pendentes.discard(k)
                                if on_progresso:
                                    on_progresso(k, erros[k], w)
                            else:
                                tarefas.put(k)  # caiu no meio: outra instância gera de novo
                continue
            if status == "inicio":
                fazendo[wid] = i
                desde[wid] = time.monotonic()
                continue
            if status == "fim":
                terminaram.add(wid)
                k = fazendo.pop(wid, None)
                if k is not None and k in pendentes:
                    tarefas.put(k)
                continue
            fazendo.pop(wid, None)
            pendentes.discard(i)
            if status == "erro":
                erros[i] = detalhe
            if on_progresso:
                on_progresso(i, erros.get(i), wid)
    finally:
        for _ in procs:
            try:
                tarefas.put(None)
            except Exception:  # noqa: BLE001
                pass
        for pr in procs.values():
            pr.join(5)
            if pr.is_alive():
                pr.terminate()
                pr.join(5)
    return erros


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Gerador de voz local (Piper / XTTS v2 / Kokoro).")
    parser.add_argument("engine", choices=sorted(ENGINES) + ["salvar-perfil", "listar-perfis"], help="Motor de voz a usar, ou 'salvar-perfil'/'listar-perfis' pra gerenciar vozes clonadas do XTTS.")
    parser.add_argument("texto", nargs="?", default="", help="Texto a narrar (ou o nome do perfil, em 'salvar-perfil').")
    parser.add_argument("--out", default="saida.wav", help="Caminho do .wav de saída.")
    parser.add_argument("--voz", help="Nome da voz (piper: --voz / xtts: --speaker / kokoro: --voz).")
    parser.add_argument("--speaker-wav", help="Áudio de referência para clonagem (só XTTS) — em 'salvar-perfil', o áudio de origem a processar.")
    parser.add_argument("--voice-profile", help="Nome de um perfil de voz salvo antes (só XTTS, alternativa ao --speaker-wav).")
    parser.add_argument("--idioma", help="Código de idioma (xtts e kokoro).")
    parser.add_argument("--velocidade", type=float, default=1.0)
    parser.add_argument("--cpu", action="store_true", help="Força CPU mesmo com GPU disponível.")
    args = parser.parse_args()

    if args.engine == "listar-perfis":
        perfis = listar_perfis_de_voz()
        print("Perfis de voz salvos:" if perfis else "Nenhum perfil de voz salvo ainda.")
        for p in perfis:
            print(f"  - {p}")
        return

    if args.engine == "salvar-perfil":
        if not args.speaker_wav:
            parser.error("salvar-perfil precisa de --speaker-wav apontando pro áudio de origem.")
        nome = args.texto or args.voz
        if not nome:
            parser.error("salvar-perfil precisa de um nome (como argumento de texto, ou --voz).")
        caminho = salvar_perfil_de_voz(nome, args.speaker_wav)
        print(f"Perfil {nome!r} salvo em: {caminho}")
        return

    use_gpu = False if args.cpu else None
    kwargs: Dict[str, Any] = {}

    if args.engine == "piper":
        if args.voz:
            kwargs["nome_voz"] = args.voz
        kwargs["velocidade"] = args.velocidade
        kwargs["use_gpu"] = use_gpu
    elif args.engine == "xtts":
        if args.voz:
            kwargs["speaker"] = args.voz
        if args.speaker_wav:
            kwargs["speaker_wav"] = args.speaker_wav
        if args.voice_profile:
            kwargs["voice_profile"] = args.voice_profile
        if args.idioma:
            kwargs["idioma"] = args.idioma
        kwargs["use_gpu"] = use_gpu
    else:  # kokoro
        if args.voz:
            kwargs["voz"] = args.voz
        if args.idioma:
            kwargs["idioma"] = args.idioma
        kwargs["velocidade"] = args.velocidade

    print(f"Gerando com {args.engine}... (GPU: {gpu_status()})")
    path = gerar_audio(args.engine, args.texto, args.out, **kwargs)
    print(f"Pronto: {path}")


if __name__ == "__main__":
    _cli()
