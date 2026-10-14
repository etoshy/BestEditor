"""
📺 canal.py — o SEU canal: nome (falado nos roteiros) e vídeos de ABERTURA e ENCERRAMENTO (v84_95)
=================================================================================================

Nome do canal: ⚙️ Configurações → 📺 Seu canal (vale pra todo projeto; cada projeto de 🕵️ Modelos de vídeo,
📜 Roteiro do YouTube e 🎞️ Vídeos modelados pode trocar). Os prompts de roteiro pedem pra IA dizer o nome no momento
certo (metodo_roteiro.bloco_canal).

Abertura / encerramento: como os vídeos de 👍 inscreva-se e 🛒 venda, você envia UMA vez (Configurações ou a aba
✂️ Cortes do editor) e eles entram sozinhos no começo e no fim de todo vídeo montado — dá pra desligar ou trocar por
outro em cada vídeo. Ficam em chamadas_padrao/ (padrao.json: "abertura" / "encerramento"). Na montagem viram cortes
reais (como as chamadas): a legenda e os capítulos andam junto.
"""
from __future__ import annotations

import os
import shutil
import uuid
from typing import Any, Dict, List, Optional

VINHETAS: Dict[str, str] = {"abertura": "🎬 Abertura (vídeo de início)", "encerramento": "🏁 Encerramento (vídeo final)"}
FIM = 10 ** 7  # ponto de inserção do encerramento (a montagem prende no fim do vídeo)


def nome_global() -> str:
    try:
        from site_config import load_site_config
        return str(load_site_config().get("nome_canal") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def nome_do_projeto(valor: Any) -> str:
    """O nome do projeto (se a pessoa escreveu um) ou o das Configurações. "-" = não falar o nome neste projeto."""
    v = " ".join(str(valor or "").split())[:80]
    if v == "-":
        return ""
    return v or nome_global()


# ------------------------------------------------------------------ abertura / encerramento
def clipe_padrao(tipo: str) -> Optional[str]:
    import chamadas
    return chamadas.clipe_padrao(tipo) if tipo in VINHETAS else None


def definir_padrao(tipo: str, caminho: Optional[str]) -> Optional[str]:
    """Guarda uma CÓPIA como abertura/encerramento padrão (None tira)."""
    import chamadas
    if tipo not in VINHETAS:
        raise ValueError("Tipo desconhecido (use abertura ou encerramento).")
    return chamadas.definir_padrao(tipo, caminho)


def do_job(job: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{tipo: {"usar": bool, "caminho": arquivo efetivo ou None, "proprio": é um vídeo só deste job, "nome"}}."""
    cfg = job.get("vinhetas") or {}
    out = {}
    for tipo in VINHETAS:
        c = cfg.get(tipo) or {}
        proprio = c.get("caminho") if c.get("caminho") and os.path.isfile(c["caminho"]) else None
        cam = proprio or clipe_padrao(tipo)
        out[tipo] = {"usar": bool(c.get("usar", True)) and bool(cam), "caminho": cam, "proprio": bool(proprio),
                     "nome": os.path.basename(cam) if cam else "", "rotulo": VINHETAS[tipo]}
    return out


def guardar_no_job(job: Dict[str, Any], tipo: str, pasta_job: str, origem: str, nome: str = "") -> str:
    """Vídeo de abertura/encerramento só deste job (cópia na pasta do job)."""
    if tipo not in VINHETAS:
        raise ValueError("Tipo desconhecido.")
    ext = os.path.splitext(nome or origem)[1].lower() or ".mp4"
    os.makedirs(pasta_job, exist_ok=True)
    destino = os.path.join(pasta_job, f"vinheta_{tipo}_{uuid.uuid4().hex[:6]}{ext}")
    shutil.copy(origem, destino)
    job.setdefault("vinhetas", {}).setdefault(tipo, {}).update(caminho=destino, usar=True)
    return destino


def cortes_para_montagem(job: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Os cortes reais da abertura (no segundo 0) e do encerramento (no fim) — o formato de insert_cutaways."""
    out = []
    for tipo, v in do_job(job).items():
        if v["usar"] and v["caminho"]:
            out.append({"resolved_path": v["caminho"], "insertion_point": 0.0 if tipo == "abertura" else float(FIM),
                        "audio_mode": "pause", "remove_ate": None, "vinheta": tipo})
    return out
