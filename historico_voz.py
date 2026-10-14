"""
historico_voz.py
================

📜 HISTÓRICO DOS ÁUDIOS GERADOS no 🎙️ Gerador de voz — fica em outputs/vozes/historico.json
(sobrevive a reiniciar o site). Cada entrada: quando, motor, voz, idioma, começo do texto,
palavras, duração do áudio, quanto tempo levou, os arquivos (wav/srt/zip/chamadas) e o erro, se deu.

Apagar uma entrada apaga também os arquivos dela.
"""
from __future__ import annotations

import json
import os
import arquivo_seguro  # noqa: E402  (v84_99: os.replace sem WinError 5)
import re
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

ARQUIVO = "historico.json"
MAX_ENTRADAS = 2000
_TRAVA = threading.Lock()


def _caminho(pasta: str) -> str:
    return os.path.join(pasta, ARQUIVO)


def _ler(pasta: str) -> List[Dict[str, Any]]:
    try:
        with open(_caminho(pasta), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _gravar(pasta: str, itens: List[Dict[str, Any]]) -> None:
    os.makedirs(pasta, exist_ok=True)
    tmp = _caminho(pasta) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(itens[:MAX_ENTRADAS], f, ensure_ascii=False, indent=0)
    arquivo_seguro.trocar(tmp, _caminho(pasta))


def duracao_audio(caminho: str) -> Optional[float]:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", caminho],
                           capture_output=True, text=True, timeout=30)
        return round(float(r.stdout.strip()), 2)
    except Exception:  # noqa: BLE001
        return None


def registrar(pasta: str, jid: str, status: Dict[str, Any], voz: str = "") -> Dict[str, Any]:
    """Grava (ou atualiza) a entrada da geração `jid` a partir do status dela."""
    arq = status.get("resultado_filename")
    e = {
        "id": jid, "criado": status.get("criado_em") or time.time(), "terminou": time.time(),
        "inicio": status.get("iniciou_em"), "motor": status.get("engine") or "", "voz": voz or status.get("voz") or "",
        "idioma": status.get("idioma") or "", "texto_inicio": status.get("texto_inicio") or "",
        "palavras": status.get("palavras"), "arquivo": arq, "srt": status.get("resultado_srt_filename"),
        "chamadas": status.get("resultado_chamadas_filename"), "erro": status.get("erro"),
        "multivoz": bool(status.get("multivoz")),
        "projeto": next((f"{k}:{status[k]}" for k in ("roteiro_id", "dossie_id", "venda_id") if status.get(k)), None),
    }
    if arq and os.path.exists(os.path.join(pasta, arq)):
        e["duracao"] = duracao_audio(os.path.join(pasta, arq))
        e["bytes"] = os.path.getsize(os.path.join(pasta, arq))
    if e["inicio"]:
        e["levou"] = round(e["terminou"] - e["inicio"], 1)
    with _TRAVA:
        itens = [x for x in _ler(pasta) if x.get("id") != jid]
        itens.insert(0, e)
        _gravar(pasta, itens)
    return e


def listar(pasta: str, q: str = "", limite: int = 100, pagina: int = 0) -> Dict[str, Any]:
    itens = _ler(pasta)
    for it in itens:  # arquivo apagado por fora (ex.: 🧹 Espaço em disco)
        it["sumiu"] = bool(it.get("arquivo")) and not os.path.exists(os.path.join(pasta, it["arquivo"]))
    if q:
        qq = q.lower().strip()
        itens = [x for x in itens if qq in (x.get("texto_inicio") or "").lower() or qq in (x.get("motor") or "").lower()
                 or qq in (x.get("voz") or "").lower()]
    total = len(itens)
    return {"total": total, "itens": itens[pagina * limite:(pagina + 1) * limite]}


def obter(pasta: str, jid: str) -> Optional[Dict[str, Any]]:
    return next((x for x in _ler(pasta) if x.get("id") == jid), None)


def apagar(pasta: str, jid: str, apagar_arquivos: bool = True) -> bool:
    with _TRAVA:
        itens = _ler(pasta)
        e = next((x for x in itens if x.get("id") == jid), None)
        if not e:
            return False
        _gravar(pasta, [x for x in itens if x.get("id") != jid])
    if apagar_arquivos:
        for k in ("arquivo", "srt", "chamadas"):
            nome = e.get(k)
            if nome and re.fullmatch(r"[\w.\-]+", nome):
                try:
                    os.remove(os.path.join(pasta, nome))
                except OSError:
                    pass
        try:
            os.remove(os.path.join(pasta, f"{jid}.zip"))
        except OSError:
            pass
    return True
