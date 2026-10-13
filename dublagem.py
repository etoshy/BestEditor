"""
dublagem.py
============

Dublagem automática: baixa um vídeo (qualquer fonte suportada — YouTube,
TikTok, Twitter/X, Instagram, Facebook, Kwai — ou usa um arquivo já
enviado), separa a voz da música/efeitos (Demucs), transcreve a fala
original (Whisper), traduz (Argos Translate), gera uma narração nova
segmento a segmento — com QUALQUER motor de voz que o site já tem
(Piper/XTTS/Chatterbox/Chatterbox Turbo/Kokoro; XTTS e Chatterbox podem
CLONAR a voz original), ajustando a velocidade de cada trecho pra caber
na janela de tempo do trecho original — mistura essa narração com o
áudio de fundo, queima legenda (palavra a palavra) e remonta tudo no
vídeo final.

Adaptado de um pipeline externo do usuário (projeto "Shortmaker") — só a
parte de DUBLAGEM em si foi trazida, reaproveitando o máximo do que o
site já tinha (Whisper, motores de TTS, legenda .ass, mixagem loudnorm).
NÃO foram trazidos nessa primeira versão (o pipeline original tinha):
  - Blur/tarja da legenda embutida no vídeo original (OCR via Tesseract).
  - Inversão/espelhamento de cena, recorte 1:1, marca d'água customizada,
    upscale final.
  - "Minha Voz" (gravar a própria narração, com múltiplos takes) — a
    narração aqui é sempre gerada por IA.
  - Cache fino por segmento (o pipeline original reaproveitava trechos
    já gerados entre execuções; aqui cada execução gera tudo de novo).
Cada um desses pode ser trazido depois, sob pedido.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from narracoes import limpar_texto_para_tts, _duracao_audio as _duracao_audio_ou_none

MOTORES_QUE_CLONAM_VOZ = ("xtts", "chatterbox", "fish_s2")
VELOCIDADE_MIN_PADRAO = 0.75
VELOCIDADE_MAX_PADRAO = 1.6
IDIOMAS_SUGERIDOS = {
    "en": "Inglês", "es": "Espanhol", "fr": "Francês", "de": "Alemão",
    "it": "Italiano", "ja": "Japonês", "ko": "Coreano", "zh": "Chinês",
    "ru": "Russo", "ar": "Árabe", "hi": "Hindi",
}


class DublagemError(Exception):
    """Falha em qualquer etapa da dublagem automática."""


def _log(on_log: Optional[Callable[[str], None]], linha: str) -> None:
    if on_log:
        on_log(linha)


def _run(cmd: List[str], erro_prefixo: str, timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    try:
        resultado = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise DublagemError(f"{erro_prefixo}: tempo esgotado.") from exc
    if resultado.returncode != 0:
        raise DublagemError(f"{erro_prefixo}: {(resultado.stderr or resultado.stdout or '')[-800:]}")
    return resultado


def _duracao_audio_segundos(caminho: str) -> float:
    duracao = _duracao_audio_ou_none(caminho)
    if duracao is None:
        raise DublagemError(f"Não consegui medir a duração de {caminho} (ffprobe).")
    return duracao


# --------------------------------------------------------------------------- #
# Passo 3: separar voz de música/efeitos (Demucs)
# --------------------------------------------------------------------------- #
def separar_voz_musica(
    audio_path: str, out_dir: str, modelo: str = "htdemucs", device: str = "cpu",
    on_log: Optional[Callable[[str], None]] = None, demucs_runner: Any = None,
) -> Tuple[str, str]:
    """Separa `audio_path` em voz (`vocals.wav`) e música/efeitos
    (`no_vocals.wav`) usando o Demucs, dentro de `out_dir`. Devolve
    `(caminho_vocals, caminho_no_vocals)`.

    `demucs_runner`: injeta uma função alternativa a `subprocess.run`
    (só pra teste — em uso normal, não passe nada).
    """
    import sys

    audio_path = str(audio_path)
    executar = demucs_runner or subprocess.run
    _log(on_log, f"Separando voz de música/efeitos (Demucs, modelo {modelo!r})...")
    resultado = executar(
        [sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", modelo, "-d", device,
         "-o", str(out_dir), audio_path],
        capture_output=True, text=True,
    )
    if resultado.returncode != 0:
        raise DublagemError(
            "Falha ao separar voz/música (Demucs): " + (resultado.stderr or resultado.stdout or "")[-800:]
        )
    stem_dir = Path(out_dir) / modelo / Path(audio_path).stem
    vocals, no_vocals = stem_dir / "vocals.wav", stem_dir / "no_vocals.wav"
    if not vocals.exists() or not no_vocals.exists():
        raise DublagemError(f"Demucs terminou sem erro, mas não encontrei os arquivos esperados em {stem_dir}.")
    return str(vocals), str(no_vocals)


# --------------------------------------------------------------------------- #
# Passo 5: traduzir (Argos Translate)
# --------------------------------------------------------------------------- #
def garantir_pacote_traducao(origem: str, destino: str, argostranslate_module: Any = None) -> None:
    """Garante que exista um caminho de tradução instalado de `origem`
    pra `destino` — tenta primeiro um pacote DIRETO; se não existir,
    tenta um caminho via inglês (`origem`->`en`->`destino`), que o Argos
    Translate encadeia sozinho quando as duas pontas estão instaladas.
    Só falha se nenhum dos dois caminhos existir."""
    if origem == destino:
        return
    if argostranslate_module is not None:
        argospackage = argostranslate_module.package
    else:
        try:
            import argostranslate.package as argospackage  # type: ignore
        except ImportError as exc:
            raise DublagemError(
                "O pacote 'argostranslate' não está instalado. Rode: pip install argostranslate"
            ) from exc

    argospackage.update_package_index()
    disponiveis = argospackage.get_available_packages()
    instalados = {(p.from_code, p.to_code) for p in argospackage.get_installed_packages()}

    def _instalar_par(de: str, para: str) -> bool:
        if (de, para) in instalados:
            return True
        candidatos = [p for p in disponiveis if p.from_code == de and p.to_code == para]
        if not candidatos:
            return False
        caminho = candidatos[0].download()
        argospackage.install_from_path(caminho)
        instalados.add((de, para))
        return True

    if _instalar_par(origem, destino):
        return
    if origem != "en" and destino != "en":
        if _instalar_par(origem, "en") and _instalar_par("en", destino):
            return
    raise DublagemError(
        f"Não há pacote de tradução Argos de '{origem}' para '{destino}' (nem direto, nem via inglês)."
    )


def traduzir_segmentos(
    segmentos: List[Dict[str, Any]], idioma_origem: str, idioma_destino: str = "pt",
    on_log: Optional[Callable[[str], None]] = None, argostranslate_module: Any = None,
) -> List[Dict[str, Any]]:
    """Traduz cada segmento (com `start`/`end`/`text`) individualmente,
    preservando o alinhamento de tempo — devolve uma cópia com o campo
    novo `text_traduzido`."""
    if argostranslate_module is not None:
        argostranslate = argostranslate_module
    else:
        try:
            import argostranslate.translate  # type: ignore
            import argostranslate as argostranslate_mod  # type: ignore
            argostranslate = argostranslate_mod
        except ImportError as exc:
            raise DublagemError(
                "O pacote 'argostranslate' não está instalado. Rode: pip install argostranslate"
            ) from exc

    if idioma_origem != idioma_destino:
        _log(on_log, f"Instalando pacote de tradução '{idioma_origem}'→'{idioma_destino}' (se precisar)...")
        garantir_pacote_traducao(idioma_origem, idioma_destino, argostranslate_module=argostranslate)

    _log(on_log, f"Traduzindo {len(segmentos)} trecho(s) para {idioma_destino!r}...")
    saida = []
    for seg in segmentos:
        texto = seg["text"]
        if idioma_origem == idioma_destino or not texto.strip():
            texto_traduzido = texto
        else:
            texto_traduzido = argostranslate.translate.translate(texto, idioma_origem, idioma_destino)
        saida.append({**seg, "text_traduzido": texto_traduzido})
    return saida


# --------------------------------------------------------------------------- #
# Ajuste de velocidade (atempo, preserva o tom da voz)
# --------------------------------------------------------------------------- #
def _cadeia_filtros_atempo(fator: float) -> str:
    """O filtro `atempo` do ffmpeg só aceita fatores entre 0.5 e 2.0 por
    instância — fatores fora disso encadeiam vários `atempo` em sequência."""
    fator = max(0.05, fator)
    partes = []
    restante = fator
    while restante < 0.5 or restante > 2.0:
        if restante > 2.0:
            partes.append(2.0)
            restante /= 2.0
        else:
            partes.append(0.5)
            restante /= 0.5
    partes.append(restante)
    return ",".join(f"atempo={p:.6f}" for p in partes)


def ajustar_velocidade(wav_in: str, wav_out: str, fator: float) -> None:
    """Reescala a velocidade de `wav_in` por `fator` (>1 = mais rápido/
    curto; <1 = mais devagar/longo) sem alterar o tom da voz."""
    if abs(fator - 1.0) < 0.01:
        shutil.copy(wav_in, wav_out)
        return
    _run(
        ["ffmpeg", "-y", "-i", str(wav_in), "-filter:a", _cadeia_filtros_atempo(fator), str(wav_out)],
        "Falha ao ajustar a velocidade do áudio (ffmpeg/atempo)",
    )


# --------------------------------------------------------------------------- #
# Passo 10: gerar a narração nova, segmento a segmento, alinhada no tempo
# --------------------------------------------------------------------------- #
def gerar_narracao_sincronizada(
    segmentos_traduzidos: List[Dict[str, Any]], saida_wav: str, duracao_total_segundos: float,
    engine: str = "xtts", voz_referencia: Optional[str] = None, idioma_destino: str = "pt",
    velocidade_min: float = VELOCIDADE_MIN_PADRAO, velocidade_max: float = VELOCIDADE_MAX_PADRAO,
    on_log: Optional[Callable[[str], None]] = None, tts_kwargs: Optional[Dict[str, Any]] = None,
    gerar_audio_fn: Any = None,
) -> str:
    """Gera a narração em `idioma_destino` SEGMENTO A SEGMENTO, casando o
    ritmo de fala com o do vídeo original: cada trecho é sintetizado,
    acelerado/desacelerado (mantendo o tom) pra caber na janela
    `[start, end]` do segmento original correspondente, e posicionado
    exatamente nesse ponto da linha do tempo (via `adelay`+`amix` do
    ffmpeg — os trechos nunca ficam simplesmente um atrás do outro).

    `engine`: motor de voz do site (`toolkit/tts/voice_generator.py`) —
        "piper", "xtts", "chatterbox", "chatterbox_turbo" ou "kokoro".
        `voz_referencia` (um áudio de alguém falando) CLONA a voz nesse
        áudio quando o motor suporta (`xtts`/`chatterbox`); nos outros,
        é ignorado.
    `tts_kwargs`: parâmetros extras repassados ao motor escolhido (ex:
        `{"speaker": "..."}` pro xtts sem clonagem, `{"nome_voz": "..."}`
        pro Kokoro) — ver `gerar_audio()` em voice_generator.py.
    `gerar_audio_fn`: injeta uma função alternativa a
        `tts.voice_generator.gerar_audio_isolado` (só pra teste).
    """
    if gerar_audio_fn is None:
        import sys
        toolkit_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit")
        if toolkit_dir not in sys.path:
            sys.path.insert(0, toolkit_dir)
        from tts.voice_generator import gerar_audio_isolado
        gerar_audio_fn = gerar_audio_isolado

    tts_kwargs = dict(tts_kwargs or {})
    if voz_referencia and engine in MOTORES_QUE_CLONAM_VOZ:
        tts_kwargs.setdefault("speaker_wav", voz_referencia)
    if engine in ("xtts", "fish_s2"):
        tts_kwargs.setdefault("idioma", idioma_destino)

    duracao_total_ms = int(duracao_total_segundos * 1000) + 2000

    with tempfile.TemporaryDirectory(prefix="dublagem_narracao_") as tmp:
        tmp_dir = Path(tmp)
        trechos_gerados: List[Tuple[str, int]] = []  # (caminho, posicao_ms)

        for i, seg in enumerate(segmentos_traduzidos, start=1):
            texto = limpar_texto_para_tts(seg.get("text_traduzido", seg.get("text", "")).strip())
            if not texto or not any(c.isalpha() for c in texto):
                continue

            bruto_wav = str(tmp_dir / f"seg_{i:04d}_bruto.wav")
            ajustado_wav = str(tmp_dir / f"seg_{i:04d}_ajustado.wav")

            _log(on_log, f"  [{i}/{len(segmentos_traduzidos)}] Gerando fala: {texto[:60]!r}...")
            gerar_audio_fn(engine, texto, bruto_wav, **tts_kwargs)

            duracao_gerada = _duracao_audio_segundos(bruto_wav)
            duracao_alvo = max(0.05, seg["end"] - seg["start"])
            fator = duracao_gerada / duracao_alvo if duracao_alvo > 0 else 1.0
            fator_aplicado = min(max(fator, velocidade_min), velocidade_max)
            ajustar_velocidade(bruto_wav, ajustado_wav, fator_aplicado)

            trechos_gerados.append((ajustado_wav, int(seg["start"] * 1000)))

        if not trechos_gerados:
            raise DublagemError("Nenhum trecho traduzido tinha texto pra narrar — a dublagem ficaria em silêncio total.")

        _montar_trilha_com_posicoes(trechos_gerados, duracao_total_ms, saida_wav)

    return saida_wav


def _montar_trilha_com_posicoes(trechos: List[Tuple[str, int]], duracao_total_ms: int, saida_wav: str) -> None:
    """Monta UMA trilha de áudio de `duracao_total_ms` colocando cada
    `(caminho, posicao_ms)` de `trechos` exatamente nessa posição
    (`adelay`), depois mistura tudo (`amix`) — sem depender de pydub."""
    with tempfile.TemporaryDirectory(prefix="dublagem_base_") as tmp:
        base_silenciosa = str(Path(tmp) / "base.wav")
        _run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={duracao_total_ms / 1000:.3f}",
             base_silenciosa],
            "Falha ao criar a trilha base (silêncio) pra narração",
        )

        entradas = [base_silenciosa] + [caminho for caminho, _ in trechos]
        partes_filtro = []
        rotulos = []
        for idx, (_, posicao_ms) in enumerate(trechos, start=1):  # entrada 0 = base silenciosa
            rotulo = f"a{idx}"
            partes_filtro.append(f"[{idx}:a]adelay={max(0, posicao_ms)}:all=1[{rotulo}]")
            rotulos.append(f"[{rotulo}]")
        filtro = ";".join(partes_filtro)
        mix_entrada = "[0:a]" + "".join(rotulos)
        filtro += f";{mix_entrada}amix=inputs={len(trechos) + 1}:duration=first:dropout_transition=0:normalize=0[out]"

        cmd = ["ffmpeg", "-y"]
        for caminho in entradas:
            cmd += ["-i", caminho]
        cmd += ["-filter_complex", filtro, "-map", "[out]", str(saida_wav)]
        _run(cmd, "Falha ao montar a trilha de narração (ffmpeg/adelay+amix)")


# --------------------------------------------------------------------------- #
# Passo 11: misturar narração com o áudio de fundo (loudnorm 2 passadas)
# --------------------------------------------------------------------------- #
def misturar_audios(
    no_vocals_path: str, narracao_path: str, saida_mix: str,
    alvo_lufs_fundo: float = -20.0, alvo_lufs_voz: float = -16.0, normalizar: bool = True,
) -> str:
    """Mistura o áudio de fundo (música/efeitos, sem a voz original) com
    a narração nova. Com `normalizar=True` (padrão), aplica loudnorm de
    2 passadas nas duas trilhas separadamente antes de misturar, pra
    ficarem numa relação de volume equilibrada e previsível — a voz um
    pouco mais "na frente" (-16 LUFS) que o fundo (-20 LUFS)."""
    from narracoes import _filtro_loudnorm_duas_passadas

    if normalizar:
        filtro_fundo = _filtro_loudnorm_duas_passadas(Path(no_vocals_path), alvo_lufs_fundo, tp=-2)
        filtro_voz = _filtro_loudnorm_duas_passadas(Path(narracao_path), alvo_lufs_voz, tp=-1.5)
    else:
        filtro_fundo = filtro_voz = "anull"

    _run([
        "ffmpeg", "-y", "-i", str(no_vocals_path), "-i", str(narracao_path),
        "-filter_complex",
        f"[0:a]{filtro_fundo}[fundo];[1:a]{filtro_voz}[voz];"
        "[fundo][voz]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[mixado];"
        "[mixado]alimiter=limit=0.9[a]",
        "-map", "[a]", str(saida_mix),
    ], "Falha ao misturar narração com o áudio de fundo")
    return saida_mix


# --------------------------------------------------------------------------- #
# Passo 12: remontar o vídeo com o áudio final
# --------------------------------------------------------------------------- #
def remontar_video_com_audio(video_path: str, audio_path: str, saida: str) -> str:
    _run([
        "ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(saida),
    ], "Falha ao remontar o vídeo com o áudio final")
    return saida
