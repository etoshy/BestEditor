"""
Servidor do Fish Audio S2 SIMULADO (só pra teste): responde como o `tools/api_server.py` do fish-speech
(GET /v1/health · POST /v1/tts em msgpack ou JSON) e como a API da Fish Audio (cabeçalho "model", chave Bearer).
Devolve um .wav de tom puro com duração proporcional ao texto e guarda cada pedido em `pedidos`.

    url, pedidos, parar = iniciar()
"""
from __future__ import annotations

import http.server
import io
import json
import math
import struct
import threading
import wave
from typing import Any, Callable, Dict, List, Tuple


def _wav(segundos: float, taxa: int = 44100) -> bytes:
    n = max(1, int(segundos * taxa))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / taxa))) for i in range(n)))
    return buf.getvalue()


def iniciar(chave: str = "") -> Tuple[str, List[Dict[str, Any]], Callable[[], None]]:
    pedidos: List[Dict[str, Any]] = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def _resp(self, cod: int, corpo: bytes, tipo: str = "application/json") -> None:
            self.send_response(cod)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def _autorizado(self) -> bool:
            return not chave or self.headers.get("Authorization") == f"Bearer {chave}"

        def do_GET(self):  # noqa: N802
            if self.path == "/v1/health":
                return self._resp(200, b'{"status":"ok"}')
            self._resp(404, b"{}")

        def do_POST(self):  # noqa: N802
            if self.path != "/v1/tts":
                return self._resp(404, b"{}")
            if not self._autorizado():
                return self._resp(401, b'{"status":401,"message":"invalid api key"}')
            dados = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.headers.get("Content-Type") == "application/msgpack":
                import msgpack
                corpo = msgpack.unpackb(dados, raw=False)
            else:
                corpo = json.loads(dados)
            pedidos.append({"corpo": corpo, "modelo": self.headers.get("model"), "tipo": self.headers.get("Content-Type")})
            texto = str(corpo.get("text") or "")
            if not texto.strip():
                return self._resp(400, b'{"message":"empty text"}')
            self._resp(200, _wav(0.2 + len(texto) * 0.01), "audio/wav")

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", pedidos, srv.shutdown
