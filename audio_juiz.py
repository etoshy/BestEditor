"""
🎯 v84_400 — o "ouvido" local do sound design: CLAP (LAION), um modelo aberto que compara um ÁUDIO com FRASES.

Roda no seu PC (PyTorch — o mesmo do Whisper/Chatterbox; a placa NVIDIA é usada se tiver), sem API externa.
O modelo (~600 MB) baixa sozinho do Hugging Face na 1ª vez e fica no cache; depois funciona offline.

Pra que serve:
  • escolher, entre os candidatos de uma busca, o que MAIS soa como a emoção do bloco (não o que tem o título certo);
  • barrar o desconexo: uma "sad piano" que soa alegre perde pra emoção errada e é recusada;
  • dizer "soa como: …" (as etiquetas mais parecidas) no painel.

Precisa de: pip install transformers  (o torch já vem com o Whisper). Sem isso, o sound design escolhe como antes.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence

MODELO_PADRAO = os.environ.get("BESTEDITOR_CLAP", "laion/clap-htsat-unfused")
TAXA = 48000
JANELA_S = 10.0

# etiquetas pro "soa como" (inglês: o CLAP foi treinado assim)
ETIQUETAS = ["rain", "wind", "thunder storm", "fire crackling", "water stream", "ocean waves", "birds", "crickets night",
             "city traffic", "crowd talking", "people cheering", "office room tone", "dark drone", "eerie horror sound",
             "heartbeat", "clock ticking", "whoosh", "impact hit", "deep boom", "riser", "explosion", "glass breaking",
             "piano", "strings orchestra", "epic orchestral", "electronic beat", "acoustic guitar", "ukulele", "synth pad",
             "happy upbeat music", "sad melancholic music", "tense suspense music", "scary horror music", "calm relaxing music",
             "mysterious music", "funny cartoon sound", "meme sound", "speech talking", "singing vocals", "silence"]

_TRAVA = threading.Lock()
_CACHE_MODELO: Dict[str, Any] = {}


def disponivel() -> Optional[str]:
    """None = dá pra usar; senão o motivo (pra mostrar no painel)."""
    try:
        import torch  # noqa: F401
    except ImportError:
        return "falta o PyTorch (vem com o Whisper: pip install openai-whisper)"
    try:
        import transformers  # noqa: F401
    except ImportError:
        return "falta o pacote transformers (pip install transformers)"
    return None


class Juiz:
    """Encapsula o modelo. `codificar_audio(lista de arrays float32 48 kHz) → embeddings` e
    `codificar_texto(lista de frases) → embeddings` (normalizados). Os testes trocam isso por um falso."""

    def __init__(self, modelo: str = MODELO_PADRAO):
        import torch
        from transformers import ClapModel, ClapProcessor
        self.torch = torch
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        self.modelo = ClapModel.from_pretrained(modelo).to(self.dev).eval()
        self.proc = ClapProcessor.from_pretrained(modelo)
        escala = getattr(self.modelo, "logit_scale_a", None)
        self.escala = float(escala.exp().item()) if escala is not None else 30.0
        self.nome = modelo

    def codificar_audio(self, audios: Sequence[Any]):
        t = self.torch
        try:
            inp = self.proc(audio=list(audios), sampling_rate=TAXA, return_tensors="pt")
        except TypeError:  # versões antigas do transformers: "audios="
            inp = self.proc(audios=list(audios), sampling_rate=TAXA, return_tensors="pt")
        inp = {k: v.to(self.dev) for k, v in inp.items()}
        with t.no_grad():
            e = self.modelo.get_audio_features(**inp)
        return t.nn.functional.normalize(e, dim=-1).cpu().numpy()

    def codificar_texto(self, textos: Sequence[str]):
        t = self.torch
        inp = self.proc(text=list(textos), return_tensors="pt", padding=True)
        inp = {k: v.to(self.dev) for k, v in inp.items()}
        with t.no_grad():
            e = self.modelo.get_text_features(**inp)
        return t.nn.functional.normalize(e, dim=-1).cpu().numpy()


def juiz(modelo: str = MODELO_PADRAO) -> Optional[Juiz]:
    """O modelo carregado UMA vez (fica na memória). None se não der (sem transformers, sem internet na 1ª vez…)."""
    if disponivel():
        return None
    with _TRAVA:
        if modelo in _CACHE_MODELO:
            return _CACHE_MODELO[modelo]
        try:
            _CACHE_MODELO[modelo] = Juiz(modelo)
        except Exception as exc:  # noqa: BLE001
            _CACHE_MODELO[modelo] = None
            _CACHE_MODELO["_erro"] = str(exc)[:300]
        return _CACHE_MODELO[modelo]


def ultimo_erro() -> str:
    return str(_CACHE_MODELO.get("_erro") or "")


# ------------------------------------------------------------------ áudio → janelas
def janelas(caminho: str, max_janelas: int = 3):
    """O áudio em 48 kHz mono; arquivo longo (música/ambiente) = até 3 janelas de 10 s (20 %, 50 %, 80 %) — a nota é a
    média (uma música que muda no meio não engana)."""
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", caminho, "-t", "600", "-ac", "1", "-ar", str(TAXA), "-f", "f32le", "-"],
                       capture_output=True, timeout=300)
    x = np.frombuffer(r.stdout, dtype=np.float32)
    n = int(JANELA_S * TAXA)
    if len(x) <= n * 1.5:
        return [x.copy()] if len(x) else []
    out = []
    for frac in (0.2, 0.5, 0.8)[:max_janelas]:
        meio = int(len(x) * frac)
        a = max(0, min(len(x) - n, meio - n // 2))
        out.append(x[a:a + n].copy())
    return out


# ------------------------------------------------------------------ notas (com cache em disco)
class Ouvido:
    """Cache dos embeddings de áudio (por arquivo+tamanho+data+modelo) e das frases."""

    def __init__(self, j: Any, cache_json: Optional[str] = None):
        self.j = j
        self.cache_json = cache_json
        self._txt: Dict[str, Any] = {}
        self._aud: Dict[str, List[float]] = {}
        if cache_json and os.path.isfile(cache_json):
            try:
                with open(cache_json, encoding="utf-8") as f:
                    self._aud = json.load(f)
            except (OSError, ValueError):
                self._aud = {}

    def _chave(self, caminho: str) -> str:
        st = os.stat(caminho)
        return f"{getattr(self.j, 'nome', 'clap')}|{os.path.abspath(caminho)}|{st.st_size}|{int(st.st_mtime)}"

    def audio(self, caminho: str):
        import numpy as np
        k = self._chave(caminho)
        if k not in self._aud:
            js = janelas(caminho)
            if not js:
                raise ValueError("áudio vazio")
            e = np.asarray(self.j.codificar_audio(js)).mean(axis=0)
            e = e / (np.linalg.norm(e) or 1.0)
            self._aud[k] = [float(v) for v in e]
        return np.asarray(self._aud[k], dtype=np.float32)

    def texto(self, frases: Sequence[str]):
        import numpy as np
        falta = [f for f in frases if f not in self._txt]
        if falta:
            for f, e in zip(falta, self.j.codificar_texto(falta)):
                self._txt[f] = np.asarray(e, dtype=np.float32)
        return np.stack([self._txt[f] for f in frases])

    def salvar(self) -> None:
        if not self.cache_json:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_json) or ".", exist_ok=True)
            tmp = self.cache_json + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dict(list(self._aud.items())[-3000:]), f)
            os.replace(tmp, self.cache_json)
        except OSError:
            pass

    def nota(self, caminho: str, alvo: str, contra: Sequence[str]) -> Dict[str, Any]:
        """{"nota": 0–100 (o quanto soa como o alvo, comparado às alternativas), "vence": a frase que mais combina,
        "soa_como": as 3 etiquetas mais parecidas, "sim": a similaridade crua com o alvo}."""
        import numpy as np
        a = self.audio(caminho)
        frases = [alvo] + [c for c in contra if c and c != alvo]
        T = self.texto(frases)
        sims = T @ a
        escala = float(getattr(self.j, "escala", 30.0))
        z = np.exp((sims - sims.max()) * escala)
        prob = z / z.sum()
        E = self.texto(ETIQUETAS)
        top = np.argsort(-(E @ a))[:3]
        return {"nota": int(round(float(prob[0]) * 100)), "vence": frases[int(np.argmax(sims))],
                "soa_como": [ETIQUETAS[i] for i in top], "sim": round(float(sims[0]), 4)}


def ouvido(cache_json: Optional[str] = None, fabrica: Optional[Callable[[], Any]] = None) -> Optional[Ouvido]:
    j = (fabrica or juiz)()
    return Ouvido(j, cache_json) if j is not None else None
