"""
Google Flow SIMULADO pra testar a automação sem conta e sem gastar crédito.

O HTML de cada tela é o REAL (capturado do flow.google.com pelo usuário, sem dados pessoais) e o `sim.js` imita o
comportamento. `iniciar()` sobe um servidor local e devolve a URL base — passe ela no lugar de https://flow.google.com/.

    url, parar = iniciar()          # http://127.0.0.1:<porta>/
    url + "?limite=1"               # o Flow avisa "Você chegou ao limite de uso."
    url + "?falha=1"                # o cartão "gerando" vira "Não foi possível gerar"
    url + "?login=1"                # sem o botão "Novo projeto" (pediu login)
"""
from __future__ import annotations

import http.server
import io
import os
import re
import subprocess
import tempfile
import threading
from typing import Callable, Tuple

AQUI = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = ("painel_agente", "popup_imagem", "popup_video", "menu_modelos_imagem", "menu_modelos_video",
             "card_gerando", "menu_midia", "tile_imagem")
CSS = """body{font-family:sans-serif;background:#111;color:#eee;margin:0}
.tiles{display:flex;gap:8px;flex-wrap:wrap;padding:20px 20px 260px;min-height:300px}.tile{width:220px;border:1px solid #444}
.tile img,.tile video{width:100%;display:block}
flow-prompt-box{display:block;position:fixed;bottom:16px;left:16px;right:16px;background:#222;padding:8px;z-index:2}
.cdk-overlay-container{position:fixed;inset:0;pointer-events:none;z-index:20}
.cdk-overlay-pane{position:fixed!important;bottom:140px!important;right:30px!important;left:auto!important;top:auto!important;
  transform:none!important;background:#333;padding:10px;max-height:70vh;overflow:auto;pointer-events:auto;max-width:640px}
.cdk-overlay-pane.menu-modelos{right:340px!important}
.agent-panel-wrapper{position:fixed;top:8px;right:8px;width:440px;max-height:90vh;overflow:auto;background:#2a2a2a;padding:8px;z-index:10}
.agent-panel-prompt-box-hidden{display:none}
[hidden]{display:none!important}.mat-button-toggle-checked{outline:2px solid #6cf}
.ProseMirror{min-height:28px;border:1px solid #555;padding:4px}.error-text{color:#f66;position:fixed;top:8px;left:8px}
mat-icon{font-size:12px}.frame-trigger img{width:40px}"""


def _ler(nome: str) -> str:
    with open(os.path.join(AQUI, nome + ".html"), encoding="utf-8") as f:
        return f.read()


def pagina_inicial(login: bool = False) -> str:
    botao = "" if login else _ler("botao_novo_projeto")
    return (f'<!doctype html><html lang="pt"><head><meta charset="utf-8"><title>Google Flow (simulado)</title>'
            f'<style>{CSS}</style></head><body><flow-projects-page>{botao}</flow-projects-page>'
            "<script>document.querySelectorAll('button.new-project-button').forEach(b => b.addEventListener('click', () => "
            "{ setTimeout(() => location.href = '/project/0a1b2c3d-4e5f-6789-abcd-ef0123456789' + location.search, 300); }));</script>"
            "</body></html>")


def pagina_projeto() -> str:
    caixa = _ler("caixa_agente")
    frames = _ler("caixa_frames")
    barra = re.search(r"<flow-ingredient-bar.*?</flow-ingredient-bar>", frames, re.S).group(0)
    tpls = "".join(f'<template id="t-{n}">{_ler(n)}</template>' for n in TEMPLATES)
    tpls += f'<template id="t-barra_frames">{barra}</template>'
    return (f'<!doctype html><html lang="pt"><head><meta charset="utf-8"><title>Projeto (simulado)</title>'
            f'<style>{CSS}</style></head><body><flow-project-page><div class="tiles"></div>'
            f'<flow-prompt-box class="prompt-box-container"><flow-base-prompt-box>{caixa}</flow-base-prompt-box></flow-prompt-box>'
            f'</flow-project-page><div class="cdk-overlay-container"></div>{tpls}<script src="/sim.js"></script></body></html>')


_MIDIA_CACHE = os.path.join(tempfile.gettempdir(), "flow_simulado_midia")


def _midia(nome: str) -> Tuple[bytes, str]:
    os.makedirs(_MIDIA_CACHE, exist_ok=True)
    video = nome.startswith("video/") or nome.endswith(".mp4")
    caminho = os.path.join(_MIDIA_CACHE, ("v_" if video else "i_") + os.path.basename(nome) + (".mp4" if video else ".png"))
    if not os.path.exists(caminho):
        if video:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x180:r=24:d=2",
                            "-pix_fmt", "yuv420p", caminho], check=True)
        else:
            from PIL import Image, ImageDraw
            im = Image.new("RGB", (640, 360), (40, 90, 160))
            ImageDraw.Draw(im).text((20, 20), nome, fill="white")
            im.save(caminho)
    with open(caminho, "rb") as f:
        return f.read(), "video/mp4" if video else "image/png"


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_a):  # silencioso
        pass

    def _enviar(self, corpo: bytes, tipo: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):  # noqa: N802
        caminho, _, qs = self.path.partition("?")
        if caminho == "/":
            return self._enviar(pagina_inicial(login="login=1" in qs).encode(), "text/html; charset=utf-8")
        if caminho.startswith("/project/"):
            return self._enviar(pagina_projeto().encode(), "text/html; charset=utf-8")
        if caminho == "/sim.js":
            with open(os.path.join(AQUI, "sim.js"), "rb") as f:
                return self._enviar(f.read(), "application/javascript")
        if caminho.startswith("/media/"):
            corpo, tipo = _midia(caminho[len("/media/"):])
            return self._enviar(corpo, tipo)
        self.send_response(404)
        self.end_headers()


def iniciar(porta: int = 0) -> Tuple[str, Callable[[], None]]:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", porta), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/", srv.shutdown
