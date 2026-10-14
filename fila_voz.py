"""
fila_voz.py
===========

🎙 FILA DO GERADOR DE VOZ — vários áudios pedidos de uma vez entram numa fila e são gerados
um depois do outro, ou VÁRIOS AO MESMO TEMPO quando a placa de vídeo tem memória (VRAM) pra isso.

Cada geração roda num processo separado (voice_generator.gerar_audio_isolado), que carrega o seu
próprio modelo na GPU — por isso o limite depende da VRAM e do motor:

    motor               VRAM aprox. por geração
    Piper               ~0,3 GB  (ONNX, leve)
    Kokoro              ~1 GB
    XTTS v2             ~3,5 GB
    Chatterbox Turbo    ~3,5 GB
    Chatterbox (multi)  ~5 GB

Modo "auto" (padrão, `voz_simultaneos` no site_config.json): lê a VRAM pelo nvidia-smi e só
começa a próxima se a soma do que já está rodando + a próxima couber em ~90% da placa (e nunca
mais que 2 de uma vez). Sem placa NVIDIA (ou forçando CPU): 1 de cada vez — na CPU, rodar duas
juntas só deixa as duas mais lentas. Também dá pra fixar 1, 2 ou 3.

A ordem é a de chegada (quem pediu primeiro começa primeiro).
"""
from __future__ import annotations

import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional

VRAM_GB = {"piper": 0.3, "kokoro": 1.0, "xtts": 3.5, "chatterbox_turbo": 3.5, "chatterbox": 5.0,
           "fish_s2": 0.2}  # Fish: a GPU é do servidor dele (outro programa); aqui é só um pedido HTTP
MAX_SIMULTANEOS = 3
MAX_AUTO = 2
MODOS = ("auto", "1", "2", "3")


def ler_vram() -> Optional[Dict[str, float]]:
    """VRAM (GB) da 1ª placa NVIDIA pelo nvidia-smi; None se não tiver."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=8)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        nome, total, livre = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")[:3]]
        return {"nome": nome, "total": float(total) / 1024.0, "livre": float(livre) / 1024.0}
    except Exception:  # noqa: BLE001
        return None


class Fila:
    """Fila com despachante. `iniciar(id, motor, fn, cpu=False)` põe na fila; `fn()` roda numa thread
    quando couber. `modo_fn()` devolve "auto"|"1"|"2"|"3"; `vram_fn()` devolve {"total","livre"} ou None."""

    def __init__(self, modo_fn: Callable[[], str] = lambda: "auto", vram_fn: Callable[[], Optional[Dict[str, float]]] = ler_vram,
                 ao_mudar: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        self.modo_fn = modo_fn
        self.vram_fn = vram_fn
        self.ao_mudar = ao_mudar or (lambda _id, _it: None)
        self._cv = threading.Condition()
        self._fila: List[Dict[str, Any]] = []
        self._rodando: Dict[str, Dict[str, Any]] = {}
        self._vram_cache: Dict[str, Any] = {"quando": 0.0, "v": None}
        self._thread: Optional[threading.Thread] = None

    # ---------------------------------------------------------------- consulta
    def vram(self) -> Optional[Dict[str, float]]:
        if time.time() - self._vram_cache["quando"] > 60:
            self._vram_cache = {"quando": time.time(), "v": self.vram_fn()}
        return self._vram_cache["v"]

    def limite(self) -> int:
        modo = str(self.modo_fn() or "auto")
        if modo in ("1", "2", "3"):
            return int(modo)
        # auto: com placa NVIDIA até 2 ao mesmo tempo (a conta da VRAM em _cabe decide); sem placa, 1
        return MAX_AUTO if self.vram() else 1

    def _cabe(self, item: Dict[str, Any]) -> bool:
        if not self._rodando:
            return True
        if len(self._rodando) >= self.limite():
            return False
        if str(self.modo_fn() or "auto") != "auto":
            return True  # número fixo escolhido pela pessoa
        v = self.vram()
        if not v:
            return False
        usado = sum(r["vram"] for r in self._rodando.values())
        return usado + item["vram"] <= v["total"] * 0.9

    def posicao(self, jid: str) -> Optional[int]:
        with self._cv:
            for k, it in enumerate(self._fila, 1):
                if it["id"] == jid:
                    return k
        return None

    def estado(self) -> Dict[str, Any]:
        with self._cv:
            v = self._vram_cache["v"]
            return {"modo": str(self.modo_fn() or "auto"), "limite": self.limite(), "vram": v,
                    "rodando": [{"id": r["id"], "motor": r["motor"], "desde": r["inicio"]} for r in self._rodando.values()],
                    "fila": [{"id": f["id"], "motor": f["motor"], "posicao": k} for k, f in enumerate(self._fila, 1)]}

    # ---------------------------------------------------------------- ações
    def iniciar(self, jid: str, motor: str, fn: Callable[[], None], cpu: bool = False, instancias: int = 1) -> int:
        """instancias: quantas cópias do motor ESTA geração usa ao mesmo tempo (⚡ tts_paralelo) — conta na VRAM."""
        item = {"id": jid, "motor": motor, "fn": fn, "vram": 0.0 if cpu else VRAM_GB.get(motor, 3.5) * max(1, int(instancias or 1)),
                "criado": time.time()}
        with self._cv:
            self._fila.append(item)
            pos = len(self._fila)
            self._garantir_thread()
            self._cv.notify_all()
        return pos

    def cancelar(self, jid: str) -> bool:
        """Só o que ainda está na fila (o que já está gerando termina)."""
        with self._cv:
            for k, it in enumerate(self._fila):
                if it["id"] == jid:
                    self._fila.pop(k)
                    self._cv.notify_all()
                    return True
        return False

    # ---------------------------------------------------------------- despachante
    def _garantir_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="fila-voz", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._fila or not self._cabe(self._fila[0]):
                    if not self._fila and not self._rodando:
                        self._cv.wait(timeout=30)
                        if not self._fila and not self._rodando:
                            self._thread = None
                            return
                    else:
                        self._cv.wait(timeout=5)
                        if self._fila:
                            self._vram_cache["quando"] = 0.0  # relê a VRAM livre antes de tentar de novo
                item = self._fila.pop(0)
                item["inicio"] = time.time()
                self._rodando[item["id"]] = item
                fila_ids = [f["id"] for f in self._fila]
            for k, fid in enumerate(fila_ids, 1):  # avisa as posições novas
                self.ao_mudar(fid, {"posicao": k})
            self.ao_mudar(item["id"], {"posicao": None, "iniciou": item["inicio"]})
            threading.Thread(target=self._rodar, args=(item,), name=f"voz-{item['id'][:8]}", daemon=True).start()

    def _rodar(self, item: Dict[str, Any]) -> None:
        try:
            item["fn"]()
        finally:
            with self._cv:
                self._rodando.pop(item["id"], None)
                self._cv.notify_all()

    def esperar_vazia(self, timeout: float = 10.0) -> bool:
        """Pros testes: espera a fila e as gerações terminarem."""
        fim = time.time() + timeout
        while time.time() < fim:
            with self._cv:
                if not self._fila and not self._rodando:
                    return True
            time.sleep(0.02)
        return False
