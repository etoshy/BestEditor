"""
perfis_limpeza.py — 🎧 voz limpa nos PERFIS DE VOZ (v84_92)
============================================================

Cada perfil de voz (os áudios de referência da clonagem — XTTS / Chatterbox / Chatterbox Turbo) é marcado:

  🎙️ "limpo"   — só a voz (gravação limpa): usa como está;
  🎵 "musica"  — tem música/efeitos de fundo (vídeo do YouTube, live, trailer…): o site processa os clipes UMA VEZ
                 com o Demucs (o mesmo da 🌐 dublagem) e deixa SÓ A VOZ — senão a clonagem copia o chiado/a música.

Como fica no disco (o motor de voz não muda nada — ele continua lendo os .wav da pasta do perfil):
  perfis_de_voz/<perfil>/clipe.wav             ← a voz limpa (é o que a clonagem usa)
  perfis_de_voz/<perfil>/_original/clipe.wav   ← o áudio como veio (pra ouvir / voltar)
Perfil antigo de um .wav solto vira pasta na primeira limpeza.

O que já foi limpo fica anotado (perfis_info.json → "limpeza": {"clipes": [...]}) — clipe novo que entrar depois num
perfil marcado 🎵 é limpo sozinho; os já limpos não são processados de novo.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional

TIPOS = {"limpo": "🎙️ limpo (só a voz)", "musica": "🎵 tem música/efeitos de fundo"}
PASTA_ORIGINAL = "_original"
_TRAVAS: Dict[str, threading.Lock] = {}
_TRAVA_GERAL = threading.Lock()


class LimpezaErro(Exception):
    pass


def _vg():
    aqui = os.path.dirname(os.path.abspath(__file__))
    tk = os.path.join(aqui, "toolkit")
    if tk not in sys.path:
        sys.path.insert(0, tk)
    from tts import voice_generator
    return voice_generator


def _trava(nome: str) -> threading.Lock:
    with _TRAVA_GERAL:
        return _TRAVAS.setdefault(nome, threading.Lock())


def info(nome: str) -> Dict[str, Any]:
    import perfis_info
    i = perfis_info.obter(nome)
    lp = dict(i.get("limpeza") or {})
    if lp.get("estado") == "rodando" and not _trava(nome).locked() and time.time() - float(lp.get("inicio") or 0) > 120:
        lp.update(estado="erro", erro="a limpeza foi interrompida (o site fechou?) — clique em 🧹 Limpar agora")
    return {"audio": i.get("audio") if i.get("audio") in TIPOS else "", "limpeza": lp}


def marcar(nome: str, audio: str) -> Dict[str, Any]:
    """🎧 "limpo" | "musica" | "" (não definido)."""
    import perfis_info
    if audio not in TIPOS and audio != "":
        raise LimpezaErro("Use limpo ou musica.")
    return perfis_info.atualizar(nome, audio=audio or None)


def _gravar_limpeza(nome: str, **campos: Any) -> Dict[str, Any]:
    import perfis_info
    atual = info(nome)["limpeza"]
    atual.update(campos)
    perfis_info.atualizar(nome, limpeza=atual)
    return atual


# ------------------------------------------------------------------ pasta do perfil
def _pasta_do_perfil(nome: str) -> str:
    """A pasta do perfil (o perfil antigo de um .wav solto vira pasta aqui)."""
    vg = _vg()
    seguro = vg._nome_perfil_seguro(nome)
    pasta = vg._pasta_perfil(seguro)
    antigo = vg._arquivo_perfil_antigo(seguro)
    if not os.path.isdir(pasta) and os.path.isfile(antigo):
        os.makedirs(pasta, exist_ok=True)
        shutil.move(antigo, os.path.join(pasta, f"{seguro}.wav"))
    if not os.path.isdir(pasta):
        raise LimpezaErro(f"Perfil {nome!r} não encontrado.")
    return pasta


def clipes(nome: str) -> List[str]:
    return list(_vg().caminho_perfil_de_voz(nome))


def originais(nome: str) -> List[str]:
    """Os áudios como vieram (na ordem dos clipes; só os que foram limpos)."""
    try:
        cs = clipes(nome)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for c in cs:
        o = os.path.join(os.path.dirname(c), PASTA_ORIGINAL, os.path.basename(c))
        if os.path.isfile(o):
            out.append(o)
    return out


# ------------------------------------------------------------------ áudio
def _formato(caminho: str) -> Dict[str, str]:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate,channels",
                            "-of", "default=nw=1", caminho], capture_output=True, text=True, timeout=30)
        d = dict(linha.split("=", 1) for linha in r.stdout.split() if "=" in linha)
        return {"ar": d.get("sample_rate") or "22050", "ac": d.get("channels") or "1"}
    except Exception:  # noqa: BLE001
        return {"ar": "22050", "ac": "1"}


def _converter(origem: str, destino: str, fmt: Dict[str, str]) -> None:
    """A voz separada (44,1 kHz estéreo do Demucs) volta pro formato do clipe original."""
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", origem, "-ar", fmt["ar"], "-ac", fmt["ac"],
                        "-c:a", "pcm_s16le", destino], capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not os.path.isfile(destino):
        raise LimpezaErro("ffmpeg não conseguiu converter a voz limpa: " + (r.stderr or "")[-300:])


def _dispositivo() -> str:
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        return "cpu"


def _separar_padrao(audio: str, pasta: str, log: Callable[[str], None]) -> str:
    import dublagem
    try:
        voz, _resto = dublagem.separar_voz_musica(audio, pasta, device=_dispositivo(), on_log=log)
    except dublagem.DublagemError as exc:
        msg = str(exc)
        if "No module named" in msg and "demucs" in msg:
            raise LimpezaErro("O Demucs não está instalado — rode: pip install demucs (depois tente de novo).") from exc
        raise LimpezaErro(msg[-600:]) from exc
    return voz


# ------------------------------------------------------------------ limpar / voltar
def limpar(nome: str, forcar: bool = False, log: Callable[[str], None] = lambda _m: None,
           separar: Optional[Callable[[str, str, Callable[[str], None]], str]] = None,
           converter: Optional[Callable[[str, str, Dict[str, str]], None]] = None) -> Dict[str, Any]:
    """Tira a música/os efeitos de fundo de cada clipe do perfil (uma vez por clipe): o original vai pra `_original/`
    e no lugar fica só a voz. `forcar` = refaz até os já limpos (a partir dos originais)."""
    separar = separar or _separar_padrao
    converter = converter or _converter
    with _trava(nome):
        pasta = _pasta_do_perfil(nome)
        orig_dir = os.path.join(pasta, PASTA_ORIGINAL)
        feitos = set(info(nome)["limpeza"].get("clipes") or [])
        lista = clipes(nome)
        alvo = [c for c in lista if forcar or os.path.basename(c) not in feitos]
        if not alvo:
            _gravar_limpeza(nome, estado="pronto", erro="", quando=time.time())
            return {"limpos": 0, "total": len(lista), "ja_estavam": len(lista)}
        _gravar_limpeza(nome, estado="rodando", erro="", inicio=time.time())
        os.makedirs(orig_dir, exist_ok=True)
        limpos = []
        try:
            for k, clipe in enumerate(alvo, start=1):
                base = os.path.basename(clipe)
                log(f"🧹 {nome}: clipe {k}/{len(alvo)} ({base}) — separando a voz da música…")
                original = os.path.join(orig_dir, base)
                if not os.path.isfile(original):
                    shutil.copy2(clipe, original)  # guarda o áudio como veio ANTES de mexer
                fmt = _formato(original)
                with tempfile.TemporaryDirectory(prefix="limpa_voz_") as tmp:
                    entrada = os.path.join(tmp, "entrada.wav")
                    shutil.copy2(original, entrada)
                    voz = separar(entrada, tmp, log)
                    saida = os.path.join(tmp, "voz.wav")
                    converter(voz, saida, fmt)
                    shutil.copy2(saida, clipe + ".novo")
                os.replace(clipe + ".novo", clipe)
                limpos.append(base)
                feitos.add(base)
                _gravar_limpeza(nome, clipes=sorted(feitos))
        except Exception as exc:  # noqa: BLE001
            _gravar_limpeza(nome, estado="erro", erro=str(exc)[:600], quando=time.time())
            raise
        _gravar_limpeza(nome, estado="pronto", erro="", quando=time.time(), clipes=sorted(feitos))
        log(f"✅ {nome}: {len(limpos)} clipe(s) com a voz limpa.")
        return {"limpos": len(limpos), "total": len(lista), "ja_estavam": len(lista) - len(alvo)}


def restaurar(nome: str) -> int:
    """↩ Volta os clipes pros áudios como vieram (com a música). Devolve quantos voltaram."""
    import perfis_info
    with _trava(nome):
        n = 0
        for o in originais(nome):
            destino = os.path.join(os.path.dirname(os.path.dirname(o)), os.path.basename(o))
            os.replace(o, destino)  # o original volta pro lugar (e sai de _original/)
            n += 1
        try:
            pasta = _pasta_do_perfil(nome)
            orig_dir = os.path.join(pasta, PASTA_ORIGINAL)
            if os.path.isdir(orig_dir) and not os.listdir(orig_dir):
                os.rmdir(orig_dir)
        except Exception:  # noqa: BLE001
            pass
        perfis_info.atualizar(nome, limpeza=None)
        return n


def iniciar(nome: str, forcar: bool = False, pagina: str = "/perfis-de-voz") -> str:
    """Limpeza em segundo plano (com aviso no 🔔 e registro no 🕘 Histórico). Devolve o id da tarefa."""
    import tarefas_bg
    _gravar_limpeza(nome, estado="rodando", erro="", inicio=time.time())
    return tarefas_bg.iniciar("perfil_limpeza", f"🧹 Voz limpa no perfil “{nome}”",
                              lambda t: limpar(nome, forcar=forcar, log=t.progresso), pagina=pagina)


def precisa_limpar(nome: str) -> bool:
    """Marcado 🎵 e com clipe ainda não limpo?"""
    i = info(nome)
    if i["audio"] != "musica":
        return False
    feitos = set(i["limpeza"].get("clipes") or [])
    try:
        return any(os.path.basename(c) not in feitos for c in clipes(nome))
    except Exception:  # noqa: BLE001
        return False
