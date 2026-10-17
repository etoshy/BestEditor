"""
🔁 Últimas escolhas (v84_161) — o idioma e o nome do canal que você usou por último
viram o padrão dos projetos NOVOS (Modelos de vídeo, Vídeo de venda, Roteiro do
YouTube e Vídeos modelados), até você mudar de novo.

Fica em ultimas_escolhas.json, na pasta do site (fora do Git: é configuração sua).
As escolhas de voz do 🎙️ Gerador de voz e do 🎙 Adaptar pro TTS ficam no navegador
(static/ui/ui.js, data-lembrar); as do 📝 Roteiro para Áudio vêm do último projeto
(narracoes.ultima_config_de_voz).
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict

ARQUIVO = "ultimas_escolhas.json"
CAMPOS = {
    "idioma": 20,            # código do idioma de saída (pt, en, es…) — Modelos de vídeo e Vídeo de venda
    "nome_canal": 80,        # 📺 nome do canal — Modelos de vídeo, Roteiro do YouTube e Vídeos modelados
    "modelado_idioma": 60,   # idioma da narração dos Vídeos modelados (texto livre: "português do Brasil")
}
_TRAVA = threading.Lock()


def desligado() -> bool:
    """Os testes desligam (cada teste começa com os padrões de fábrica)."""
    return bool(os.environ.get("ULTIMAS_ESCOLHAS_DESLIGADO"))


def _caminho(base: str) -> str:
    return os.path.join(os.environ.get("ULTIMAS_ESCOLHAS_DIR") or base, ARQUIVO)


def ler(base: str) -> Dict[str, Any]:
    if desligado():
        return {}
    try:
        with open(_caminho(base), encoding="utf-8") as f:
            d = json.load(f)
        return {k: v for k, v in d.items() if k in CAMPOS and isinstance(v, str)} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def pegar(base: str, chave: str, padrao: str = "") -> str:
    v = ler(base).get(chave)
    return v if isinstance(v, str) else padrao


def lembrar(base: str, **campos: Any) -> None:
    """Guarda as escolhas (None = não mexe; "" = guarda vazio, ex.: voltou a usar o canal das Configurações)."""
    novos = {k: " ".join(str(v).split())[:CAMPOS[k]] for k, v in campos.items() if k in CAMPOS and v is not None}
    if not novos or desligado():
        return
    with _TRAVA:
        d = ler(base)
        if all(d.get(k) == v for k, v in novos.items()):
            return
        d.update(novos)
        tmp = _caminho(base) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, _caminho(base))
        except OSError:
            pass
