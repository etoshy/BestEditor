"""
poker_render.py — 🃏 a mesa animada (v84_277)
==============================================

A linha do tempo do poker_mesa vira uma página HTML que desenha a mesa em QUALQUER instante (`window.render(t)` é uma
função pura do tempo — o mesmo t sempre dá o mesmo quadro). Isso serve pra:
  • a 👁 prévia no site (um laço de requestAnimationFrame chama render(t));
  • o 📤 MP4: o Chromium do Playwright desenha quadro a quadro (render(i/fps) → screenshot) e o ffmpeg junta, com os
    sons de carta e de ficha sintetizados nos instantes certos.

Visual: mesa 2D "quase 3D" — feltro com luz, borda grossa com a lateral escura embaixo (profundidade), sombra no chão,
cartas com sombra e virada em 3D (rotateY), fichas empilhadas com a borda listrada; a câmera gira a mesa pra vista de
outro jogador (os assentos deslizam pela elipse). Temas: azul, verde, preto e branco, preto e dourado, dourado e
branco, vinho.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Dict, List, Optional

import poker_mesa as PM

AQUI = os.path.dirname(os.path.abspath(__file__))
TAMANHOS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}

TEMAS_CSS = {
    "azul": dict(fundo1="#0b1030", fundo2="#1b1f5c", feltro1="#2563eb", feltro2="#0b2a7a", borda="#1e293b", borda2="#0f172a",
                 lateral="#060a18", acento="#38bdf8", texto="#e2e8f0", placa="#111827ee", placa_txt="#f8fafc", valor="#fbbf24",
                 verso1="#b91c1c", verso2="#7f1d1d", linha="#60a5fa55", naipes="quatro"),
    "verde": dict(fundo1="#0b1a10", fundo2="#132a1a", feltro1="#16a34a", feltro2="#064e1f", borda="#5b3a1e", borda2="#3b2412",
                  lateral="#1c1009", acento="#facc15", texto="#ecfdf5", placa="#0f1a12ee", placa_txt="#f0fdf4", valor="#fde047",
                  verso1="#1d4ed8", verso2="#1e3a8a", linha="#bbf7d055", naipes="duas"),
    "preto_branco": dict(fundo1="#050505", fundo2="#1a1a1a", feltro1="#3a3a3a", feltro2="#0c0c0c", borda="#e5e5e5", borda2="#a3a3a3",
                         lateral="#404040", acento="#ffffff", texto="#f5f5f5", placa="#000000ee", placa_txt="#ffffff", valor="#ffffff",
                         verso1="#262626", verso2="#000000", linha="#ffffff33", naipes="mono"),
    "preto_dourado": dict(fundo1="#050403", fundo2="#17120a", feltro1="#1f1a12", feltro2="#060504", borda="#d4af37", borda2="#8a6d1c",
                          lateral="#3d2f0c", acento="#f5d77a", texto="#f8eccb", placa="#0a0806ee", placa_txt="#f5d77a", valor="#f5d77a",
                          verso1="#1a1408", verso2="#000000", linha="#d4af3744", naipes="ouro"),
    "dourado_branco": dict(fundo1="#f5efe1", fundo2="#e8dcc0", feltro1="#fffdf7", feltro2="#ece3cc", borda="#c9a646", borda2="#9c7b22",
                           lateral="#7a5c14", acento="#b8902a", texto="#3b2f12", placa="#fffaf0f0", placa_txt="#3b2f12", valor="#9c7b22",
                           verso1="#c9a646", verso2="#8a6d1c", linha="#b8902a44", naipes="duas"),
    "vinho": dict(fundo1="#12040a", fundo2="#2a0a17", feltro1="#9f1239", feltro2="#4c0519", borda="#caa24a", borda2="#7c5c17",
                  lateral="#2b0610", acento="#fcd34d", texto="#fff1f2", placa="#1c0710ee", placa_txt="#fff1f2", valor="#fcd34d",
                  verso1="#111827", verso2="#000000", linha="#fcd34d44", naipes="duas"),
}


TEMAS_CSS.update({
    "vegas70": dict(fundo1="#1a0d05", fundo2="#3a1d0b", feltro1="#b4532a", feltro2="#5a1f0c", borda="#d9a441", borda2="#8a5a17",
                    lateral="#2a1406", acento="#f6c56b", texto="#fdebc8", placa="#2a1608ee", placa_txt="#fdebc8", valor="#ffd27a",
                    verso1="#7c2d12", verso2="#431407", linha="#f6c56b44", naipes="duas"),
    "neon80": dict(fundo1="#07001a", fundo2="#1d0440", feltro1="#3b0a6b", feltro2="#12002b", borda="#ff2bd6", borda2="#7a0f8a",
                   lateral="#1a0030", acento="#22e3ff", texto="#f5e9ff", placa="#0b0020ee", placa_txt="#f5e9ff", valor="#ff2bd6",
                   verso1="#22e3ff", verso2="#0a3a5c", linha="#22e3ff55", naipes="quatro"),
    "macau": dict(fundo1="#160304", fundo2="#3a0a0c", feltro1="#b91c1c", feltro2="#5c0a0a", borda="#e8c15a", borda2="#9a7420",
                  lateral="#2b0505", acento="#ffd56b", texto="#fff4dc", placa="#1f0607ee", placa_txt="#ffe9b0", valor="#ffd56b",
                  verso1="#111111", verso2="#3a0a0c", linha="#ffd56b44", naipes="duas"),
    "monaco": dict(fundo1="#050b18", fundo2="#0f1d38", feltro1="#14325e", feltro2="#071630", borda="#e6d5ac", borda2="#9c8a5f",
                   lateral="#040a16", acento="#f1e3bf", texto="#f6efdc", placa="#081226ee", placa_txt="#f6efdc", valor="#f1e3bf",
                   verso1="#7f1d1d", verso2="#3b0b0b", linha="#f1e3bf33", naipes="duas"),
    "brasil": dict(fundo1="#03150a", fundo2="#0a2e17", feltro1="#0f8a3c", feltro2="#05441c", borda="#f7d117", borda2="#a58a06",
                   lateral="#062810", acento="#ffdf00", texto="#f0fff4", placa="#04210ee8", placa_txt="#fff9c4", valor="#ffdf00",
                   verso1="#1d4ed8", verso2="#002776", linha="#ffdf0044", naipes="quatro"),
    "tv2000": dict(fundo1="#04060a", fundo2="#121a26", feltro1="#1e6b3a", feltro2="#0a2d17", borda="#4b3621", borda2="#2a1d10",
                   lateral="#120c06", acento="#7dd3fc", texto="#e5e7eb", placa="#0b1220ee", placa_txt="#f1f5f9", valor="#fde047",
                   verso1="#1e3a8a", verso2="#0b1d4d", linha="#ffffff22", naipes="quatro"),
})
# 🎞 estéticas de época/lugar: o tema + um acabamento por cima (grão de filme, sépia, linhas de TV, neon)
ESTETICAS = {
    "": {"nome": "— nenhuma (só o tema)", "tema": "", "filtro": "", "grao": 0, "linhas": 0, "vinheta": 0.25, "brilho": ""},
    "vegas70": {"nome": "🎰 Las Vegas anos 70 (filme quente, grão)", "tema": "vegas70", "filtro": "sepia(.35) saturate(1.15) contrast(1.05)", "grao": 0.16, "linhas": 0, "vinheta": 0.55, "brilho": "#ffb34722"},
    "tv2000": {"nome": "📺 TV anos 2000 (WSOP 2003, hole cam)", "tema": "tv2000", "filtro": "saturate(.85) contrast(1.08) blur(.4px)", "grao": 0.08, "linhas": 0.22, "vinheta": 0.4, "brilho": ""},
    "neon80": {"nome": "🌆 Anos 80 neon", "tema": "neon80", "filtro": "saturate(1.25)", "grao": 0.05, "linhas": 0.1, "vinheta": 0.5, "brilho": "#ff2bd61a"},
    "noir": {"nome": "🎩 Noir / clandestino (preto e branco)", "tema": "preto_branco", "filtro": "grayscale(1) contrast(1.25)", "grao": 0.2, "linhas": 0, "vinheta": 0.7, "brilho": ""},
    "macau": {"nome": "🏮 Macau (vermelho e ouro)", "tema": "macau", "filtro": "saturate(1.1)", "grao": 0, "linhas": 0, "vinheta": 0.45, "brilho": "#ffd56b14"},
    "monaco": {"nome": "🛥 Monte Carlo (luxo azul e champanhe)", "tema": "monaco", "filtro": "", "grao": 0.03, "linhas": 0, "vinheta": 0.4, "brilho": "#f1e3bf10"},
    "brasil": {"nome": "🇧🇷 Brasil (verde e amarelo)", "tema": "brasil", "filtro": "saturate(1.1)", "grao": 0, "linhas": 0, "vinheta": 0.35, "brilho": ""},
    "moderno": {"nome": "✨ Streaming moderno (limpo, high-tech)", "tema": "preto_dourado", "filtro": "contrast(1.04)", "grao": 0, "linhas": 0, "vinheta": 0.3, "brilho": ""},
}


def opcoes_padrao() -> Dict[str, Any]:
    return {"tema": "azul", "formato": "16:9", "mostrar": "heroi", "equidade": True, "posicoes": True, "velocidade": 1.0,
            "sons": True, "fps": 30, "titulo": True, "logo": "", "estilo": "normal", "gancho": "", "pov": "",
            "estetica": "", "tema_fixo": False, "emocoes": False, "zoom": True, "dinheiro": True, "camera": "mover", "modo": "2d", "estilo3d": "buckshot", "estrategia": False}


def normalizar(o: Any) -> Dict[str, Any]:
    out = opcoes_padrao()
    if isinstance(o, dict):
        if o.get("tema") in TEMAS_CSS:
            out["tema"] = o["tema"]
        if o.get("formato") in TAMANHOS:
            out["formato"] = o["formato"]
        if o.get("mostrar") in PM.MOSTRAR:
            out["mostrar"] = o["mostrar"]
        for k in ("equidade", "posicoes", "sons", "titulo"):  # noqa: B007
            if k in o:
                out[k] = o[k] is True or str(o[k]).lower() in ("1", "true", "on", "sim")
        try:
            out["velocidade"] = max(0.4, min(3.0, float(o.get("velocidade") or 1.0)))
        except (TypeError, ValueError):
            pass
        if o.get("fps") in (24, 30, 60, "24", "30", "60"):
            out["fps"] = int(o["fps"])
        out["logo"] = " ".join(str(o.get("logo") or "").split())[:40]
        out["estilo"] = "shorts" if o.get("estilo") == "shorts" else "normal"
        out["gancho"] = " ".join(str(o.get("gancho") or "").split())[:120]
        out["pov"] = "auto" if o.get("pov") in ("auto", True, "1") else ""
        out["estetica"] = o.get("estetica") if o.get("estetica") in ESTETICAS else ""
        out["camera"] = "girar" if o.get("camera") == "girar" else "mover"
        out["estrategia"] = o.get("estrategia") is True or str(o.get("estrategia")).lower() in ("1", "true", "on", "sim")
        out["modo"] = "3d" if o.get("modo") == "3d" else "2d"
        out["estilo3d"] = "limpo" if o.get("estilo3d") == "limpo" else "buckshot"
        for k in ("tema_fixo", "emocoes", "zoom", "dinheiro"):
            if k in o:
                out[k] = o[k] is True or str(o[k]).lower() in ("1", "true", "on", "sim")
    return out


def _fontes_css(prefixo: str) -> str:
    """As fontes do DarkPlanner (Poppins/Inter) — `prefixo` = file:///…/assets/fonts/dp ou a rota do site."""
    try:
        import dp_legendas
        mapa = dp_legendas._mapa_fontes()
    except Exception:  # noqa: BLE001
        return ""
    css = []
    for fam in ("DP Poppins", "DP Inter"):
        for peso, nome in (("400", "Regular"), ("700", "Bold"), ("800", "ExtraBold"), ("600", "SemiBold")):
            arq = (mapa.get(fam) or {}).get(nome)
            if arq:
                css.append(f"@font-face{{font-family:'{fam}';font-weight:{peso};src:url('{prefixo}/{arq}');}}")
    return "\n".join(css)


def pagina(dados: Dict[str, Any], op: Dict[str, Any], fontes_prefixo: str, avatar_url: Callable[[str], str], modo: str = "gravar") -> str:
    """O HTML completo da mesa (dados = poker_mesa.simular). modo "gravar" (sem controles) ou "previa" (com play/pausa)."""
    W, H = TAMANHOS[op["formato"]]
    est = ESTETICAS.get(op.get("estetica") or dados.get("estetica") or "")
    tema = TEMAS_CSS[est["tema"] if est and est.get("tema") and not op.get("tema_fixo") else op["tema"]]
    js = []
    for j in dados["jogadores"]:
        js.append({"nome": j["nome"], "cartas": j["cartas"], "heroi": j["heroi"], "avatar": avatar_url(j["avatar"]) if j.get("avatar") else "",
                   "pais": j.get("pais") or ""})
    payload = {"W": W, "H": H, "tema": tema, "op": op, "jogadores": js, "posicoes": dados["posicoes"], "botao": dados["botao"],
               "eventos": dados["eventos"], "duracao": dados["duracao"], "unidade": dados["unidade"], "titulo": dados.get("titulo") or "",
               "inicial": dados["inicial"], "modo": modo, "ncartas": dados.get("ncartas") or 2, "abertas": dados.get("abertas") or [], "estrategia": bool(dados.get("estrategia")), "tipo_jogo": dados.get("tipo_jogo") or "board",
               "variante": dados.get("variante") or "holdem", "variante_nome": dados.get("variante_nome") or "",
               "zooms": dados.get("zooms") or [], "emocoes": dados.get("emocoes") or [], "mostrares": dados.get("mostrares") or [],
               "mostrar": dados.get("mostrar") or "", "dinheiro": dados.get("dinheiro") or "",
               "gancho": dados.get("gancho") or "", "ritmo": dados.get("ritmo") or "normal",
               "estetica": ESTETICAS.get(op.get("estetica") or dados.get("estetica") or "", ESTETICAS[""])}
    return (HTML.replace("/*FONTES*/", _fontes_css(fontes_prefixo))
            .replace("__DADOS__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__W__", str(W)).replace("__H__", str(H)))


# ------------------------------------------------------------------ sons (sintetizados — não precisa de arquivo)
def _clacks(offsets, d: float) -> str:
    """Fichas de cerâmica batendo: cada batida = 3 ressonâncias curtas (2,2k · 3,4k · 5,1k Hz) que somem em ~20 ms."""
    termos = []
    for k, o in enumerate(offsets):
        a = 0.55 * (0.75 + 0.25 * ((k * 7) % 3) / 2)
        f1, f2, f3 = 3300 + (k * 137) % 400, 5000 + (k * 211) % 500, 2100 + (k * 97) % 300
        tt = f"(t-{o:.3f})"
        termos.append(f"gte(t,{o:.3f})*{a:.2f}*(sin(2*PI*{f1}*{tt})*exp(-210*{tt})+0.6*sin(2*PI*{f2}*{tt})*exp(-300*{tt})"
                      f"+0.45*sin(2*PI*{f3}*{tt})*exp(-150*{tt}))")
    return f"aevalsrc='{'+'.join(termos)}':d={d:.2f}:s=48000"


SONS_ASSETS = {"impacto": ("impacto", "impacto_11.m4a"), "suspense": ("impacto", "riser_5.m4a"), "whoosh": ("passagem", "passagem_3.m4a")}


def _som(tipo: str, destino: str) -> str:
    """Um efeito: o seu (poker/sons/<tipo>.wav|mp3|m4a), o da biblioteca do site, ou sintetizado (fichas/cartas)."""
    if os.path.isfile(destino):
        return destino
    pasta_user = os.path.join(os.environ.get("POKER_DIR") or os.path.join(AQUI, "poker"), "sons")
    fonte = next((os.path.join(pasta_user, tipo + e) for e in (".wav", ".mp3", ".m4a", ".ogg")
                  if os.path.isfile(os.path.join(pasta_user, tipo + e))), None)
    if not fonte and tipo in SONS_ASSETS:
        c = os.path.join(AQUI, "assets", "sons", *SONS_ASSETS[tipo])
        fonte = c if os.path.isfile(c) else None
    if fonte:
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", fonte, "-t", "3", "-ar", "48000", "-ac", "2",
                            "-af", "volume=0.7", destino], capture_output=True, timeout=60)
        if r.returncode == 0:
            return destino
    filtros = {
        # carta deslizando no feltro: um "fff" curto e suave, sem chiado agudo
        "carta": "anoisesrc=d=0.16:c=pink:a=0.35:s=48000,bandpass=f=2600:width_type=h:w=2400,afade=t=in:d=0.025,afade=t=out:st=0.04:d=0.12,volume=2.6",
        # carta virando: um estalo seco de papel
        "virar": "anoisesrc=d=0.07:c=white:a=0.5:s=48000,highpass=f=1800,lowpass=f=8000,afade=t=in:d=0.003,afade=t=out:st=0.01:d=0.06,volume=0.7",
        "ficha": _clacks([0.0, 0.045], 0.12),
        "fichas": _clacks([0.0, 0.03, 0.07, 0.095, 0.13, 0.17, 0.2], 0.3),
        "vitoria": _clacks([0.0, 0.025, 0.05, 0.08, 0.1, 0.13, 0.15, 0.19, 0.22, 0.26, 0.3], 0.42),
        "impacto": "aevalsrc='0.9*sin(2*PI*(70-40*t)*t)*exp(-4*t)':d=1.0:s=48000",
        "suspense": "aevalsrc='0.22*sin(2*PI*(180+520*t)*t)*min(1,t)':d=1.5:s=48000,afade=t=out:st=1.25:d=0.25",
        "whoosh": "anoisesrc=d=0.45:c=pink:a=0.5,bandpass=f=1200:width_type=h:w=900,afade=t=in:d=0.2,afade=t=out:st=0.2:d=0.25",
    }
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", filtros[tipo], "-ar", "48000", "-ac", "2", destino],
                   capture_output=True, timeout=60)
    return destino


def trilha_sons(dados: Dict[str, Any], destino: str, pasta: str, shorts: bool = False) -> Optional[str]:
    """Os sons nos instantes certos: carta distribuída/virada, fichas indo pra aposta e pro pot, vitória.
    shorts: + impacto no all-in, suspense no river e whoosh na troca de câmera."""
    pedacos = []
    shorts = shorts or dados.get("ritmo") == "shorts"
    for e in dados["eventos"]:
        t, tipo = e["t0"], e["tipo"]
        if shorts:
            if tipo == "acao" and "ALL-IN" in str(e["dados"].get("rotulo")):
                pedacos.append(("impacto", t + e["dur"] * 0.3))
            elif tipo == "board" and e["dados"].get("pos") == 4:
                pedacos.append(("suspense", t))
            elif tipo == "camera":
                pedacos.append(("whoosh", t + 0.05))
        if tipo == "carta_jogador":
            pedacos.append(("carta", t + 0.05))
        elif tipo == "board":
            pedacos.append(("virar", t + e["dur"] * 0.35))
        elif tipo == "acao" and e["dados"].get("valor", 0) > 0:
            pedacos.append(("fichas" if "ALL-IN" in str(e["dados"].get("rotulo")) else "ficha", t + e["dur"] * 0.55))
        elif tipo == "blinds":
            pedacos.append(("ficha", t + 0.4))
        elif tipo == "recolher":
            pedacos.append(("fichas", t + 0.25))
        elif tipo == "showdown":
            pedacos.append(("virar", t + 0.2))
        elif tipo == "fim":
            pedacos += [("impacto", t + 0.05), ("suspense", t + 0.6)]
        elif tipo == "vencedor":
            pedacos.append(("vitoria", t + e["dur"] * 0.4))  # as fichas do pot empilhando na frente de quem ganhou
    if not pedacos:
        return None
    os.makedirs(pasta, exist_ok=True)
    arqs = {k: _som(k, os.path.join(pasta, f"_som_{k}.wav")) for k in {p[0] for p in pedacos}}
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", f"{dados['duracao'] + 0.5:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
    fc, mix = [], ["[0:a]"]
    for k, (tipo, t) in enumerate(pedacos[:180], 1):
        cmd += ["-i", arqs[tipo]]
        ms = max(0, int(t * 1000))
        fc.append(f"[{k}:a]adelay={ms}|{ms}[s{k}]")
        mix.append(f"[s{k}]")
    fc.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0[a]")
    cmd += ["-filter_complex", ";".join(fc), "-map", "[a]", destino]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        r = subprocess.run([x.replace(":normalize=0", "") for x in cmd], capture_output=True, text=True, timeout=600)
    return destino if r.returncode == 0 and os.path.isfile(destino) else None


# ------------------------------------------------------------------ gravar o MP4
def gravar_pagina(html_texto: str, W: int, H: int, fps: int, duracao: float, video: str, on_log: Callable[[str], None] = lambda _m: None,
                  parar: Callable[[], bool] = lambda: False, pasta: str = "", rotulo: str = "🎞 desenhando a mesa",
                  crf: int = 18, tempo: Optional[Callable[[float], float]] = None, quadro_final: str = "") -> str:
    """Qualquer página com window.render(t) + window.pronto → MP4 (Chromium quadro a quadro → ffmpeg H.264, sem áudio)."""
    from playwright.sync_api import sync_playwright
    pasta = pasta or tempfile.mkdtemp(prefix="poker_")
    html = os.path.join(pasta, "pagina.html")
    with open(html, "w", encoding="utf-8") as f:
        f.write(html_texto)
    total = int(round(duracao * fps))
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
                           "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", video],
                          stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with sync_playwright() as pw:
            nav = pw.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security"])
            pg = nav.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
            pg.goto("file://" + html.replace("\\", "/"))
            pg.wait_for_function("window.pronto === true", timeout=30000)
            for i in range(total):
                if parar():
                    raise PM.PokerErro("⏹ parado por você")
                pg.evaluate(f"window.render({(tempo(i / fps) if tempo else i / fps):.4f})")   # tempo: vídeo → página (pausas)
                ff.stdin.write(pg.screenshot(type="jpeg", quality=92))
                if i % fps == 0:
                    on_log(f"{rotulo}: {i // fps}/{int(duracao)} s")
            if quadro_final:   # o último quadro em PNG (a montagem segura ele enquanto o narrador fala)
                pg.screenshot(path=quadro_final, type="png")
            nav.close()
        ff.stdin.close()
        if ff.wait(timeout=1800) != 0:
            raise PM.PokerErro("ffmpeg: " + (ff.stderr.read() or b"").decode("utf-8", "replace")[-400:])
    except Exception:
        try:
            ff.kill()
        except Exception:  # noqa: BLE001
            pass
        raise
    return video


def juntar_audio(video: str, audio: Optional[str], saida: str) -> str:
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", video]
    if audio:
        cmd += ["-i", audio, "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-c:v", "copy", "-movflags", "+faststart", saida]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise PM.PokerErro("ffmpeg: " + r.stderr[-400:])
    return saida


def gravar(dados: Dict[str, Any], op: Dict[str, Any], saida: str, on_log: Callable[[str], None] = lambda _m: None,
           pasta_avatares: str = "", parar: Callable[[], bool] = lambda: False) -> str:
    """Chromium desenha render(i/fps) quadro a quadro → ffmpeg (H.264) + os sons."""
    op = normalizar(op)
    W, H = TAMANHOS[op["formato"]]
    fps = int(op["fps"])
    tmp = tempfile.mkdtemp(prefix="poker_")
    fontes = "file://" + os.path.join(AQUI, "assets", "fonts", "dp").replace("\\", "/")
    av = lambda a: ("file://" + os.path.join(pasta_avatares, os.path.basename(a)).replace("\\", "/")) if a else ""  # noqa: E731
    video = os.path.join(tmp, "video.mp4")
    try:
        gravar_pagina(pagina(dados, op, fontes, av, "gravar"), W, H, fps, dados["duracao"] + 0.4, video, on_log, parar, tmp)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    audio = trilha_sons(dados, os.path.join(tmp, "sons.wav"), tmp, op.get("estilo") == "shorts") if op.get("sons") else None
    on_log("🔊 juntando os sons…" if audio else "📦 finalizando…")
    try:
        return juntar_audio(video, audio, saida)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>mesa</title>
<style>
/*FONTES*/
:root { --W: __W__px; --H: __H__px; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: var(--W); height: var(--H); overflow: hidden; background: #000; }
body.previa { width: auto; height: auto; background: #0b0b0b; overflow: auto; }
#palco { position: relative; width: var(--W); height: var(--H); overflow: hidden; font-family: 'DP Poppins', 'Segoe UI', Arial, sans-serif; }
body.previa #palco { transform-origin: 0 0; }
.abs { position: absolute; }
#mesa-sombra, #mesa-lateral, #mesa-borda, #mesa-feltro, #mesa-linha { position: absolute; border-radius: 50%; }
.carta { position: absolute; border-radius: 10%/7%; transform-style: preserve-3d; }
.carta .face, .carta .verso { position: absolute; inset: 0; border-radius: inherit; backface-visibility: hidden; }
.carta .face { background: linear-gradient(160deg, #ffffff, #eef2f7); box-shadow: 0 6px 14px #0007, inset 0 0 0 1px #0002; }
.carta .verso { transform: rotateY(180deg); box-shadow: 0 6px 14px #0007; }
.carta .r { position: absolute; left: 9%; top: 4%; font-weight: 800; line-height: 1; }
.carta .n1 { position: absolute; left: 10%; font-weight: 700; line-height: 1; }
.carta .n2 { position: absolute; right: 7%; bottom: 4%; line-height: 1; }
.placa { position: absolute; transform: translate(-50%, 0); text-align: center; border-radius: 14px; padding: 6px 14px 7px; min-width: 150px; }
.placa .nome { font-weight: 700; white-space: nowrap; }
.placa .stack { font-weight: 800; }
.av { position: absolute; border-radius: 50%; transform: translate(-50%, -50%); overflow: hidden; display: flex; align-items: center; justify-content: center; font-weight: 800; }
.av img { width: 100%; height: 100%; object-fit: cover; }
.badge { position: absolute; z-index: 8; transform: translate(-50%, -50%); border-radius: 8px; padding: 3px 10px; font-weight: 800; white-space: nowrap; letter-spacing: .02em; }
.ficha { position: absolute; border-radius: 50%; transform: translate(-50%, -50%); }
.valor { position: absolute; transform: translate(-50%, -50%); font-weight: 800; white-space: nowrap; border-radius: 999px; padding: 2px 10px; }
#nota { position: absolute; z-index: 9; left: 50%; transform: translateX(-50%); text-align: center; font-weight: 600; border-radius: 16px; padding: 14px 22px; }
#titulo { position: absolute; left: 50%; transform: translateX(-50%); font-weight: 800; text-align: center; white-space: nowrap; }
#controles { position: fixed; left: 0; right: 0; bottom: 0; display: flex; gap: 10px; align-items: center; padding: 8px 12px; background: #000c; color: #fff; font: 14px sans-serif; z-index: 10; }
#controles input[type=range] { flex: 1; }
#controles button { padding: 4px 12px; }
#cena { position: absolute; inset: 0; transform-origin: 50% 50%; }
.fx { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); font-weight: 900; white-space: nowrap; pointer-events: none; z-index: 12; letter-spacing: .02em; }
#gancho { position: absolute; left: 50%; transform: translateX(-50%); z-index: 13; text-align: center; font-weight: 900; line-height: 1.05; border-radius: 18px; padding: 16px 26px; }
#progresso { position: absolute; left: 0; bottom: 0; height: 8px; z-index: 13; }
#vinheta { position: absolute; inset: 0; pointer-events: none; z-index: 11; }
</style></head><body><div id="palco"><div id="cena"></div></div>
<script>
const D = __DADOS__;
const T = D.tema, W = D.W, H = D.H, N = D.jogadores.length, OP = D.op;
const NC = D.ncartas || 2;                         // cartas na mão (Hold'em 2 · Omaha 4/5/6)
const palco = document.getElementById('palco'), cena = document.getElementById('cena');
const SH = D.ritmo === 'shorts' || OP.estilo === 'shorts';   // ⚡ modo shorts (jogadas insanas): zoom, tremida, letreiros
const EST = D.estetica || {};
// 👁 o que mostrar ao longo da mão (a IA/você troca no meio: [mostrar: pov] / [mostrar: todas])
const MOSTRA0 = D.mostrar && D.mostrar !== '' ? D.mostrar : OP.mostrar;
function modoEm(t) { let m = MOSTRA0, de = MOSTRA0, t0 = -9; for (const x of D.mostrares || []) { if (x.t0 > t) break; de = m; m = x.modo; t0 = x.t0; } return { m, de, q: clamp((t - t0) / 0.45, 0, 1) }; }
const S = Math.min(W, H) / 1080;                 // escala geral (1080 = referência)
const VERT = H > W * 1.2, QUAD = !VERT && H > W * 0.8;
const CX = W / 2, CY = VERT ? H * 0.5 : H * (QUAD ? 0.52 : 0.535);
const RX = VERT ? W * 0.36 : (QUAD ? W * 0.36 : W * 0.33), RY = VERT ? H * 0.27 : (QUAD ? H * 0.25 : H * 0.255);
const SRX = RX * (VERT ? 1.17 : 1.2), SRY = RY * (VERT ? 1.16 : 1.3);   // elipse dos assentos
const el = (tag, css, pai) => { const e = document.createElement(tag); if (css) e.style.cssText = css; (pai || cena).appendChild(e); return e; };
const lerp = (a, b, p) => a + (b - a) * p;
const ease = p => p < 0 ? 0 : p > 1 ? 1 : (p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
// 💰 valores na unidade da história: BB, fichas (2,5M), $ / US$ / R$ / € / £ (com mil/milhão abreviado)
const UNI = String(D.unidade || 'bb'), UNI_L = UNI.toLowerCase();
const num = v => { const s = (Math.abs(v - Math.round(v)) < 1e-9 ? String(Math.round(v)) : String(Math.round(v * 100) / 100)); return s.replace('.', ','); };
const curto = v => { const a = Math.abs(v); if (a >= 1e6) return num(Math.round(v / 1e4) / 100) + 'M'; if (a >= 1e4) return num(Math.round(v / 100) / 10) + 'K'; return num(v); };
const fmt = v => { v = Math.round(v * 100) / 100;
  if (UNI_L === 'bb') return num(v) + ' BB';
  if (['$', 'us$', 'r$', '€', '£', 'eur', 'usd', 'brl'].includes(UNI_L)) { const pre = { usd: 'US$', brl: 'R$', eur: '€' }[UNI_L] || UNI; return pre + (pre.length > 1 ? ' ' : '') + curto(v); }
  return curto(v); };   // "fichas" (ou outra palavra): só o número — o foco é a jogada

// ---------------------------------------------------------------- cenário fixo
palco.style.background = `radial-gradient(ellipse at 50% ${VERT ? 40 : 35}%, ${T.fundo2}, ${T.fundo1} 70%)`;
for (let k = 0; k < 40; k++) {  // poeira de luz no fundo (fixa)
  const x = (k * 97) % 100, y = (k * 61) % 100, r = 1 + (k % 3);
  el('div', `position:absolute;left:${x}%;top:${y}%;width:${r * S * 2}px;height:${r * S * 2}px;border-radius:50%;background:${T.acento};opacity:${0.05 + (k % 5) * 0.02}`);
}
const BW = 34 * S;  // largura da borda (rail)
// 🎥 a mesa é um objeto 3D de verdade: elipse RX × WB no chão, vista por uma câmera inclinada (TILT) com perspectiva.
// Trocar de vista = a câmera dá a volta na mesa (PSI) até ficar atrás do jogador — a mesa não deforma, só é vista
// de outro lugar (o lado perto fica maior, o longe menor), e o logo/feltro giram junto como numa mesa real.
const LARGO = !VERT && !QUAD;
const WB = LARGO ? RX / 1.55 : VERT ? RX * 1.45 : RX / 1.3;
const DPERSP = 2100 * S, KV = WB / RY;
// a inclinação acompanha a volta: olhando a mesa pelo comprido, a câmera desce um pouco (a mesa não vira um "corredor")
let TILT = Math.acos(clamp(RY / WB, 0.2, 0.98));
function inclinar() { const s2 = Math.pow(Math.sin(PSI * Math.PI / 180), 2); TILT = Math.acos(clamp(lerp(RY / WB, Math.min(RY / WB, RY / RX), s2), 0.2, 0.98)); }
const gMesa = el('div', `position:absolute;left:${CX}px;top:${CY}px;width:0;height:0;transform-origin:0 0;transform-style:preserve-3d`);
const oval = (rx, ry, css, z) => el('div', `position:absolute;border-radius:50%;left:${-rx}px;top:${-ry}px;width:${rx * 2}px;height:${ry * 2}px;transform:translateZ(${z || 0}px);${css}`, gMesa);
oval(RX + BW * 1.5, WB + BW * 1.5, `background:radial-gradient(#000c, transparent 70%);filter:blur(${20 * S}px)`, -70 * S);
oval(RX + BW, WB + BW, `background:${T.lateral}`, -22 * S);
oval(RX + BW, WB + BW, `background:radial-gradient(ellipse at 50% 30%, ${T.borda}, ${T.borda2});box-shadow:inset 0 0 ${10 * S}px #0008`, 0);
oval(RX, WB, `background:radial-gradient(ellipse at 50% 38%, ${T.feltro1}, ${T.feltro2} 78%);box-shadow:inset 0 0 ${60 * S}px #0008`, 1);
oval(RX * 0.86, WB * 0.82, `border:${2 * S}px solid ${T.linha}`, 2);
if (OP.logo) el('div', `position:absolute;left:0;top:${WB * 0.45}px;transform:translate(-50%,-50%) translateZ(3px);color:${T.linha};font-weight:800;font-size:${40 * S}px;letter-spacing:.2em;opacity:.8;white-space:nowrap`, gMesa).textContent = OP.logo.toUpperCase();
let PSI = 0;   // quanto a câmera já deu a volta (graus)
function poeMesa(intro) {
  gMesa.style.transform = `scale(${lerp(0.92, 1, intro)}) perspective(${DPERSP}px) rotateX(${TILT * 180 / Math.PI}deg) rotateZ(${-PSI}deg)`;
  gMesa.style.opacity = intro;
}

// ---------------------------------------------------------------- bandeiras (desenhadas em CSS: funcionam sem fonte de emoji)
const fx3 = (a, b, c) => `linear-gradient(90deg, ${a} 33.3%, ${b} 33.3% 66.6%, ${c} 66.6%)`, fy3 = (a, b, c) => `linear-gradient(180deg, ${a} 33.3%, ${b} 33.3% 66.6%, ${c} 66.6%)`;
const BANDEIRAS = {
  BR: 'linear-gradient(to bottom right, #009c3b 50%, transparent 50%) 0 0/50% 50% no-repeat, linear-gradient(to bottom left, #009c3b 50%, transparent 50%) 100% 0/50% 50% no-repeat, linear-gradient(to top right, #009c3b 50%, transparent 50%) 0 100%/50% 50% no-repeat, linear-gradient(to top left, #009c3b 50%, transparent 50%) 100% 100%/50% 50% no-repeat, radial-gradient(circle, #002776 0 24%, #ffdf00 25%)',
  US: 'linear-gradient(90deg, #3c3b6e 40%, transparent 40%) 0 0/100% 54% no-repeat, repeating-linear-gradient(180deg, #b22234 0 7.7%, #fff 7.7% 15.4%)',
  FR: fx3('#0055a4', '#fff', '#ef4135'), IT: fx3('#009246', '#fff', '#ce2b37'), IE: fx3('#169b62', '#fff', '#ff883e'), BE: fx3('#000', '#fae042', '#ed2939'),
  DE: fy3('#000', '#dd0000', '#ffce00'), RU: fy3('#fff', '#0039a6', '#d52b1e'), NL: fy3('#ae1c28', '#fff', '#21468b'), AT: fy3('#ed2939', '#fff', '#ed2939'),
  HU: fy3('#ce2939', '#fff', '#477050'), LT: fy3('#fdb913', '#006a44', '#c1272d'), BG: fy3('#fff', '#00966e', '#d62612'), CO: 'linear-gradient(180deg, #fcd116 50%, #003893 50% 75%, #ce1126 75%)',
  AR: fy3('#74acdf', '#fff', '#74acdf'), ES: 'linear-gradient(180deg, #aa151b 25%, #f1bf00 25% 75%, #aa151b 75%)', UA: 'linear-gradient(180deg, #0057b7 50%, #ffd700 50%)',
  PL: 'linear-gradient(180deg, #fff 50%, #dc143c 50%)', CA: 'linear-gradient(90deg, #d52b1e 25%, #fff 25% 75%, #d52b1e 75%)', MX: fx3('#006847', '#fff', '#ce1126'),
  PE: fx3('#d91023', '#fff', '#d91023'), JP: 'radial-gradient(circle, #bc002d 30%, #fff 31%)', CN: 'radial-gradient(circle at 25% 30%, #ffde00 12%, transparent 13%), #de2910',
  VN: 'radial-gradient(circle, #ffcd00 22%, #da251d 23%)', KR: 'radial-gradient(circle, #cd2e3a 0 14%, #0047a0 14% 24%, #fff 25%)', GB: 'linear-gradient(90deg, transparent 42%, #c8102e 42% 58%, transparent 58%), linear-gradient(180deg, transparent 38%, #c8102e 38% 62%, transparent 62%), #012169',
  SE: 'linear-gradient(90deg, transparent 30%, #fecc00 30% 42%, transparent 42%), linear-gradient(180deg, transparent 40%, #fecc00 40% 60%, transparent 60%), #006aa7',
  NO: 'linear-gradient(90deg, transparent 28%, #fff 28% 32%, #00205b 32% 40%, #fff 40% 44%, transparent 44%), linear-gradient(180deg, transparent 36%, #fff 36% 42%, #00205b 42% 58%, #fff 58% 64%, transparent 64%), #ba0c2f',
  FI: 'linear-gradient(90deg, transparent 30%, #003580 30% 42%, transparent 42%), linear-gradient(180deg, transparent 38%, #003580 38% 62%, transparent 62%), #fff',
  DK: 'linear-gradient(90deg, transparent 30%, #fff 30% 40%, transparent 40%), linear-gradient(180deg, transparent 42%, #fff 42% 58%, transparent 58%), #c60c30',
  CH: 'linear-gradient(90deg, transparent 42%, #fff 42% 58%, transparent 58%) 0 25%/100% 50% no-repeat, linear-gradient(180deg, transparent 42%, #fff 42% 58%, transparent 58%) 33% 0/34% 100% no-repeat, #da291c',
  PT: 'linear-gradient(90deg, #006600 40%, #ff0000 40%)', IL: 'linear-gradient(180deg, #fff 12%, #0038b8 12% 24%, #fff 24% 76%, #0038b8 76% 88%, #fff 88%)',
  AU: 'linear-gradient(90deg, #012169 100%)', IN: fy3('#ff9933', '#fff', '#138808'), CL: 'linear-gradient(90deg, #0039a6 33%, transparent 33%) 0 0/100% 50% no-repeat, linear-gradient(180deg, #fff 50%, #d52b1e 50%)',
  UY: 'repeating-linear-gradient(180deg, #fff 0 11%, #0038a8 11% 22%)', PY: fy3('#d52b1e', '#fff', '#0038a8'), GR: 'repeating-linear-gradient(180deg, #0d5eaf 0 11%, #fff 11% 22%)',
  TR: 'radial-gradient(circle at 40% 50%, #fff 20%, transparent 21%), #e30a17', CZ: 'linear-gradient(180deg, #fff 50%, #d7141a 50%)', RO: fx3('#002b7f', '#fcd116', '#ce1126'),
  EE: fy3('#0072ce', '#000', '#fff'), LV: 'linear-gradient(180deg, #9e3039 40%, #fff 40% 60%, #9e3039 60%)', HR: fy3('#ff0000', '#fff', '#171796'), RS: fy3('#c6363c', '#0c4076', '#fff'),
};

// ---------------------------------------------------------------- cartas
const COR4 = { s: '#111827', h: '#dc2626', d: '#2563eb', c: '#16a34a' }, COR2 = { s: '#111', h: '#d61f1f', d: '#d61f1f', c: '#111' };
const SIMB = { s: '♠', h: '♥', d: '♦', c: '♣' };
const corNaipe = n => T.naipes === 'quatro' ? COR4[n] : T.naipes === 'mono' ? (n === 'h' || n === 'd' ? '#6b6b6b' : '#111') : T.naipes === 'ouro' ? (n === 'h' || n === 'd' ? '#b8860b' : '#111') : COR2[n];
function novaCarta(w) {
  const c = el('div', `width:${w}px;height:${w * 1.4}px;transform-origin:50% 50%`); c.className = 'carta';
  const f = el('div', '', c); f.className = 'face';
  const v = el('div', `background:repeating-linear-gradient(45deg, ${T.verso1} 0 ${w * 0.06}px, ${T.verso2} ${w * 0.06}px ${w * 0.12}px);border:${w * 0.05}px solid #fff`, c); v.className = 'verso';
  c._w = w; c._face = f; c._verso = v; c._cod = null; return c;
}
function setCarta(c, cod) {
  if (c._cod === cod) return; c._cod = cod; const w = c._w; c._face.innerHTML = '';
  if (!cod) return;
  if (cod === '??') {   // carta desconhecida: ninguém sabe qual foi
    el('div', `position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:${w * 0.8}px;font-weight:900;color:#9ca3af;background:repeating-linear-gradient(45deg,#f1f5f9 0 ${w * 0.08}px,#e2e8f0 ${w * 0.08}px ${w * 0.16}px)`, c._face).textContent = '?';
    return;
  }
  const r = cod[0] === 'T' ? '10' : cod[0], n = cod[1], cor = corNaipe(n);
  el('div', `font-size:${w * 0.42}px;color:${cor}`, c._face).className = 'r'; c._face.lastChild.textContent = r;
  el('div', `top:${w * 0.48}px;font-size:${w * 0.3}px;color:${cor}`, c._face).className = 'n1'; c._face.lastChild.textContent = SIMB[n];
  el('div', `font-size:${w * 0.62}px;color:${cor}`, c._face).className = 'n2'; c._face.lastChild.textContent = SIMB[n];
}
function poeCarta(c, x, y, aberta, rot, op, esc) {  // aberta: 0 = verso, 1 = face (meio do caminho = virando)
  c.style.left = (x - c._w / 2) + 'px'; c.style.top = (y - c._w * 0.7) + 'px';
  // virada com perspectiva: a carta levanta um pouco e cresce no meio do giro (como na mão de um dealer)
  const giro = aberta > 0.001 && aberta < 0.999 ? Math.sin(Math.PI * aberta) : 0;
  c.style.transform = `perspective(${c._w * 9}px) translateY(${-giro * c._w * 0.22}px) rotateZ(${(rot || 0) * (1 - giro * 0.5)}deg) rotateY(${(1 - aberta) * 180}deg) scale(${(esc || 1) * (1 + 0.1 * giro)})`;
  c.style.zIndex = giro ? 7 : '';
  c._face.style.boxShadow = giro ? `0 ${c._w * (0.1 + 0.25 * giro)}px ${c._w * (0.2 + 0.4 * giro)}px #0009` : '';
  c.style.opacity = op == null ? 1 : op; c.style.display = (op === 0) ? 'none' : 'block';
  // qual lado aparece não depende do backface-visibility (opacidade/filtro achatam o 3D e mostrariam a face)
  c._face.style.visibility = aberta > 0.5 ? 'visible' : 'hidden';
  c._verso.style.visibility = aberta > 0.5 ? 'hidden' : 'visible';
}

// ---------------------------------------------------------------- fichas
const CORES_FICHA = ['#e11d48', '#2563eb', '#16a34a', '#111827', '#f59e0b', '#7c3aed'];
function pilha(pai, n, r) {  // n fichas empilhadas (de pé, vistas de cima com a borda)
  pai.innerHTML = '';
  for (let k = 0; k < n; k++) {
    const cor = CORES_FICHA[(k * 3 + n) % CORES_FICHA.length];
    el('div', `left:${r}px;top:${r - k * r * 0.22}px;width:${r * 2}px;height:${r * 2}px;background:radial-gradient(circle, ${cor} 0 42%, #fff 43% 50%, ${cor} 51%);border:${r * 0.18}px dashed #fffc;box-shadow:0 ${r * 0.12}px 0 #0007`, pai).className = 'ficha';
  }
}
const nFichas = v => v <= 0 ? 0 : clamp(Math.round(Math.log2(1 + v * 2)), 1, 9);

// ---------------------------------------------------------------- assentos
const CW = (VERT ? 64 : 58) * S;               // carta dos jogadores
const BOARD_W = (VERT ? 108 : 104) * S;        // carta do board
const assentos = D.jogadores.map((j, i) => {
  const a = { i };
  a.cartas = Array.from({ length: NC }, () => novaCarta(CW));
  a.cartas.forEach((c, k) => setCarta(c, j.cartas[k] || null));
  const R = (VERT ? 62 : 58) * S;
  a.av = el('div', `width:${R * 2}px;height:${R * 2}px;background:radial-gradient(circle at 35% 30%, ${T.acento}, ${T.borda2});border:${4 * S}px solid ${T.borda};box-shadow:0 ${6 * S}px ${16 * S}px #0009;color:${T.placa_txt};font-size:${R * 0.8}px`);
  a.av.className = 'av';
  if (j.avatar) { const im = el('img', '', a.av); im.src = j.avatar; } else a.av.textContent = j.nome.slice(0, 1).toUpperCase();
  a.placa = el('div', `background:${T.placa};border:${2 * S}px solid ${T.borda2};box-shadow:0 ${8 * S}px ${18 * S}px #000a`); a.placa.className = 'placa';
  a.nome = el('div', `color:${T.placa_txt};font-size:${22 * S}px;display:flex;align-items:center;justify-content:center;gap:${7 * S}px`, a.placa); a.nome.className = 'nome';
  if (j.pais && BANDEIRAS[j.pais]) { const b = el('span', `display:inline-block;width:${30 * S}px;height:${20 * S}px;border-radius:${3 * S}px;box-shadow:0 0 0 ${1 * S}px #0006;background:${BANDEIRAS[j.pais]}`, a.nome); b.title = j.pais; }
  else if (j.pais) { const b = el('span', `font-size:${14 * S}px;padding:0 ${5 * S}px;border-radius:${4 * S}px;background:${T.acento};color:#111;font-weight:800`, a.nome); b.textContent = j.pais; }
  el('span', '', a.nome).textContent = j.nome;
  // 😰 emoção na frente da foto (entra, balança e sai)
  a.emo = el('div', `position:absolute;transform:translate(-50%,-50%);font-size:${R * 1.25}px;line-height:1;z-index:9;font-family:'Noto Color Emoji','Segoe UI Emoji','Apple Color Emoji',sans-serif;display:none;filter:drop-shadow(0 ${6 * S}px ${10 * S}px #000a)`);
  a.emoTxt = el('div', `position:absolute;transform:translate(-50%,0);z-index:9;display:none;max-width:${300 * S}px;white-space:normal;text-align:center;font-weight:700;font-size:${19 * S}px;color:#111;background:#fff;border-radius:${14 * S}px;padding:${6 * S}px ${12 * S}px;box-shadow:0 ${6 * S}px ${14 * S}px #0008`);
  a.stack = el('div', `color:${T.valor};font-size:${26 * S}px`, a.placa); a.stack.className = 'stack';
  a.barra = el('div', `height:${4 * S}px;margin-top:${4 * S}px;border-radius:4px;background:${T.acento};transform-origin:0 50%`, a.placa);
  a.badge = el('div', `font-size:${18 * S}px`); a.badge.className = 'badge';
  a.pos = el('div', `font-size:${15 * S}px;color:${T.texto};opacity:.75;background:#0006;padding:1px 8px;border-radius:6px`); a.pos.className = 'badge';
  a.pos.textContent = D.posicoes[i];
  a.eq = el('div', `font-size:${20 * S}px;color:#fff;background:#0009;border:${2 * S}px solid ${T.acento}`); a.eq.className = 'badge';
  a.jogo = el('div', `font-size:${19 * S}px;color:#111;background:${T.valor}`); a.jogo.className = 'badge';
  a.pilha = el('div', 'position:absolute;width:0;height:0');
  a.valor = el('div', `font-size:${20 * S}px;color:${T.texto};background:#000a`); a.valor.className = 'valor';
  return a;
});
const dealer = el('div', `width:${34 * S}px;height:${34 * S}px;border-radius:50%;background:#fff;color:#b91c1c;font-weight:900;font-size:${20 * S}px;display:flex;align-items:center;justify-content:center;box-shadow:0 ${3 * S}px ${6 * S}px #0008;transform:translate(-50%,-50%)`);
dealer.className = 'abs'; dealer.textContent = 'D';
const boardC = [0, 1, 2, 3, 4].map(() => novaCarta(BOARD_W));
const boardX = [0, 1].map(() => [0, 1, 2, 3, 4].map(() => novaCarta(BOARD_W)));   // 🔁 run it twice/três vezes: 2ª e 3ª fileira
const potLbl = el('div', `font-size:${28 * S}px;color:${T.texto};background:#000a;border:${2 * S}px solid ${T.acento}66`); potLbl.className = 'valor';
const potPilha = el('div', 'position:absolute;width:0;height:0');
const voo = [0, 1, 2, 3, 4, 5, 6, 7, 8].map(() => el('div', 'position:absolute;width:0;height:0'));   // fichas voando
const nota = el('div', `bottom:${(VERT ? 150 : 40) * S}px;max-width:${W * 0.86}px;font-size:${(VERT ? 34 : 30) * S}px;color:${T.placa_txt};background:${T.placa};border:${2 * S}px solid ${T.acento}`); nota.id = 'nota'; const NOTA_BOTTOM = nota.style.bottom;
const titulo = el('div', VERT ? `top:${80 * S}px;font-size:${44 * S}px;color:${T.texto};text-shadow:0 ${3 * S}px ${10 * S}px #000a;max-width:${W * 0.9}px;white-space:normal`
  : `left:${40 * S}px;transform:none;text-align:left;top:${30 * S}px;font-size:${34 * S}px;color:${T.texto};text-shadow:0 ${3 * S}px ${10 * S}px #000a;max-width:${W * 0.34}px;white-space:normal`, palco); titulo.id = 'titulo';   // fora da câmera (não gira nem dá zoom)
titulo.textContent = OP.titulo ? D.titulo : '';
if (D.variante && D.variante !== 'holdem' && D.variante_nome) { const v = el('div', `font-size:.55em;color:${T.acento};letter-spacing:.12em;margin-top:${4 * S}px`, titulo); v.textContent = D.variante_nome.toUpperCase(); }
// ---- ⚡ efeitos (shorts): letreiro grande, vinheta, gancho, barra de progresso
const vinheta = el('div', 'opacity:0;background:radial-gradient(ellipse at center, transparent 35%, #000 100%)', palco); vinheta.id = 'vinheta';
const fxTxt = el('div', `font-size:${(VERT ? 150 : 170) * S}px;color:#fff;opacity:0;text-shadow:0 0 ${30 * S}px ${T.acento}, 0 ${8 * S}px ${24 * S}px #000`, palco); fxTxt.className = 'fx';
const fxSub = el('div', `font-size:${(VERT ? 48 : 44) * S}px;color:${T.valor};opacity:0;text-shadow:0 ${4 * S}px ${14 * S}px #000`, palco); fxSub.className = 'fx';
const GANCHO = (OP.gancho || D.gancho || '').trim();
const gancho = el('div', `top:${(VERT ? 70 : 60) * S}px;max-width:${W * (VERT ? 0.92 : 0.7)}px;font-size:${(VERT ? 54 : 56) * S}px;color:#111;background:${T.valor};box-shadow:0 ${10 * S}px ${30 * S}px #000a;opacity:0`, palco); gancho.id = 'gancho';
gancho.textContent = GANCHO;
// 🎞 acabamento da estética (por cima de tudo, fora do zoom)
if (EST.filtro) cena.style.filter = EST.filtro;
if (EST.brilho) el('div', `position:absolute;inset:0;pointer-events:none;z-index:10;background:${EST.brilho};mix-blend-mode:screen`, palco);
if (EST.linhas) el('div', `position:absolute;inset:0;pointer-events:none;z-index:11;opacity:${EST.linhas};background:repeating-linear-gradient(180deg, #000 0 ${2 * S}px, transparent ${2 * S}px ${5 * S}px)`, palco);
let grao = null;
if (EST.grao) {   // ruído fixo (gerado uma vez) que "anda" a cada quadro
  const cv = document.createElement('canvas'); cv.width = cv.height = 200; const cx = cv.getContext('2d'), im = cx.createImageData(200, 200);
  let sd = 7; const rnd = () => (sd = (sd * 16807) % 2147483647) / 2147483647;
  for (let k = 0; k < im.data.length; k += 4) { const v = rnd() * 255; im.data[k] = im.data[k + 1] = im.data[k + 2] = v; im.data[k + 3] = 255; }
  cx.putImageData(im, 0, 0);
  grao = el('div', `position:absolute;inset:0;pointer-events:none;z-index:11;opacity:${EST.grao};mix-blend-mode:overlay;background-image:url(${cv.toDataURL()})`, palco);
}
// 🧠 estratégia: painel de pot odds/EV na decisão + grade de range 13×13
const ESTRAT = !!(OP.estrategia || D.estrategia);
const painel = el('div', `position:absolute;z-index:12;display:none;min-width:${340 * S}px;padding:${14 * S}px ${18 * S}px;border-radius:${14 * S}px;background:${T.placa};border:${2 * S}px solid ${T.acento};color:${T.placa_txt};font-weight:700;font-size:${(VERT ? 30 : 24) * S}px;line-height:1.35;box-shadow:0 ${10 * S}px ${30 * S}px #000a`, palco);
if (VERT) { painel.style.left = '50%'; painel.style.bottom = (300 * S) + 'px'; } else { painel.style.right = (36 * S) + 'px'; painel.style.bottom = (40 * S) + 'px'; }
const GR = (VERT ? 62 : 52) * S, gradeBox = el('div', `position:absolute;z-index:13;left:50%;top:50%;display:none;transform:translate(-50%,-50%);padding:${16 * S}px;border-radius:${16 * S}px;background:#000d;border:${2 * S}px solid ${T.acento};text-align:center;color:#fff;font-weight:800;font-size:${(VERT ? 34 : 28) * S}px`, palco);
const gradeTit = el('div', `margin-bottom:${10 * S}px`, gradeBox);
const gradeCv = el('canvas', '', gradeBox); gradeCv.width = Math.round(GR * 13); gradeCv.height = Math.round(GR * 13);
const RKD = 'AKQJT98765432';
function desenhaGrade(cels, mao, q, pulso) {
  const g = gradeCv.getContext('2d'), set = new Set(cels), c = GR;
  g.clearRect(0, 0, gradeCv.width, gradeCv.height);
  for (let i = 0; i < 13; i++) for (let j = 0; j < 13; j++) {
    const nome = i === j ? RKD[i] + RKD[j] : i < j ? RKD[i] + RKD[j] + 's' : RKD[j] + RKD[i] + 'o';
    const ordem = (i + j) / 24, on = set.has(nome) && q > ordem;
    g.fillStyle = on ? (i === j ? '#e11d48' : i < j ? T.acento : '#22c55e') : '#1f2937';
    g.globalAlpha = on ? 0.95 : 0.6; g.fillRect(j * c + 1, i * c + 1, c - 2, c - 2); g.globalAlpha = 1;
    if (nome === mao) { g.strokeStyle = '#fff'; g.lineWidth = 3 + 3 * pulso; g.strokeRect(j * c + 2, i * c + 2, c - 4, c - 4); }
    g.fillStyle = on ? '#111' : '#9ca3af'; g.font = `700 ${c * 0.3}px DP Poppins, sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(nome, j * c + c / 2, i * c + c / 2);
  }
}
// 💀 fim: a mão foi interrompida (sem showdown) — escurece tudo e o letreiro entra
const fimVeu = el('div', 'position:absolute;inset:0;z-index:14;display:none;background:radial-gradient(ellipse at center, #000a, #000f)', palco);
const fimTxt = el('div', `position:absolute;z-index:15;left:50%;top:50%;display:none;transform:translate(-50%,-50%);width:${W * 0.82}px;text-align:center;color:#fff;font-weight:900;font-size:${(VERT ? 64 : 58) * S}px;line-height:1.2;text-shadow:0 0 ${30 * S}px #000`, palco);
function fimUI(t, e, p, k) {
  const ev = e.tipo === 'fim' ? e : (e.tipo === 'final' && k > 0 && EV[k - 1].tipo === 'fim' ? EV[k - 1] : null);
  if (!ev) { fimVeu.style.display = fimTxt.style.display = 'none'; return; }
  const q = e.tipo === 'fim' ? p : 1;
  fimVeu.style.display = fimTxt.style.display = 'block';
  fimVeu.style.opacity = Math.min(1, q * 3) * 0.85;
  fimTxt.textContent = ev.dados.texto; fimTxt.style.opacity = clamp((q - 0.2) * 3, 0, 1);
  fimTxt.style.transform = `translate(-50%,-50%) scale(${1.08 - 0.08 * ease(clamp((q - 0.2) * 2, 0, 1))})`;
  if (e.tipo === 'fim' && p < 0.08) { cena.style.transform = `translate(${Math.sin(t * 97) * 14 * S}px, ${Math.cos(t * 83) * 10 * S}px)`; }
}
function estrategiaUI(t, e, p) {
  painel.style.display = 'none'; gradeBox.style.display = 'none';
  if (e.tipo === 'range') {
    const q = clamp(p / 0.35, 0, 1), sai = clamp((1 - p) / 0.12, 0, 1);
    gradeBox.style.display = 'block'; gradeBox.style.opacity = Math.min(clamp(p * 8, 0, 1), sai);
    gradeBox.style.transform = `translate(-50%,-50%) scale(${0.92 + 0.08 * ease(clamp(p * 5, 0, 1))})`;
    gradeTit.textContent = `🧠 Range de ${D.jogadores[e.dados.quem].nome} · ${String(e.dados.pct).replace('.', ',')}% das mãos` + (e.dados.mao ? ` · ele tem ${e.dados.mao}` : '');
    desenhaGrade(e.dados.celulas, e.dados.mao, q, (Math.sin(t * 8) + 1) / 2);
    return;
  }
  const dc = e.tipo === 'pensa' && e.dados.decisao;
  if (!ESTRAT || !dc || e.dur < 1) return;
  const vis = Math.min(clamp(p * 8, 0, 1), clamp((1 - p) * 8, 0, 1));
  painel.style.display = 'block'; painel.style.opacity = vis;
  painel.style.transform = (VERT ? 'translateX(-50%) ' : '') + `translateY(${(1 - ease(clamp(p * 6, 0, 1))) * 30 * S}px)`;
  const nome = D.jogadores[e.dados.quem].nome, ok = dc.eq != null ? dc.eq >= dc.precisa : null;
  const f = x => String(x).replace('.', ',');
  painel.innerHTML = `<div style="color:${T.acento};font-size:.8em;letter-spacing:.08em">🧠 DECISÃO DE ${esc(nome).toUpperCase()}</div>`
    + `<div>Paga <b style="color:${T.valor}">${fmt(dc.pagar)}</b> pra ganhar <b style="color:${T.valor}">${fmt(dc.pote)}</b></div>`
    + `<div>Precisa de <b>${f(dc.precisa)}%</b> de chance${dc.eq != null ? ` · tem <b style="color:${ok ? '#22c55e' : '#ef4444'}">${f(dc.eq)}%</b>` : ''}</div>`
    + (dc.ev != null ? `<div>EV do call: <b style="color:${dc.ev >= 0 ? '#22c55e' : '#ef4444'}">${dc.ev >= 0 ? '+' : ''}${fmt(dc.ev)}</b> ${ok ? '✅ pagar' : '❌ largar'}</div>` : '')
    + (dc.spr != null ? `<div style="opacity:.8;font-size:.85em">SPR ${f(dc.spr)}</div>` : '');
}
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const progresso = el('div', `background:${T.acento};width:0;display:${SH ? 'block' : 'none'}`, palco); progresso.id = 'progresso';
const ruaLbl = el('div', `font-size:${22 * S}px;color:${T.acento};letter-spacing:.35em;font-weight:700;opacity:.9`); ruaLbl.id = 'titulo';

// ---------------------------------------------------------------- geometria (a vista gira a mesa)
const ANG = 360 / N;
function angDiff(i, v) { let d = ((i - v) % N + N) % N; if (d > N / 2) d -= N; return d; }
// 🎥 câmera: "mover" (padrão) = a mesa fica parada e a câmera vai até o jogador (pan + zoom suave);
// "girar" = a mesa gira até ele ficar embaixo (o jeito antigo)
const GIRAR = OP.camera === 'girar';
const VISTA0 = D.eventos[0].depois.vista;
function camEm(t) {   // {de, para, q}: de quem pra quem a câmera está indo agora
  let de = VISTA0, para = VISTA0, t0 = -9, dur = 1;
  for (const e of D.eventos) { if (e.tipo !== 'camera') continue; if (e.t0 > t) break; de = para; para = e.dados.para; t0 = e.t0; dur = e.dur; }
  return { de, para, q: ease(clamp((t - t0) / dur, 0, 1)) };
}
function angAssento(i, vista) { return 90 + (i - vista) * ANG; }        // 90° = embaixo, no meio (o jogador da vista)
function ponto(ang, rx, ry) {   // ang = ângulo na VISTA atual → tela (a mesma projeção do CSS da mesa)
  const w = (ang + PSI) * Math.PI / 180, P = PSI * Math.PI / 180;
  const u = Math.cos(w) * rx, v = Math.sin(w) * ry * KV;
  const u2 = u * Math.cos(P) + v * Math.sin(P), v2 = -u * Math.sin(P) + v * Math.cos(P);
  const yy = v2 * Math.cos(TILT), zz = v2 * Math.sin(TILT), k = DPERSP / (DPERSP - zz);
  return [CX + u2 * k, CY + yy * k];
}
function vistaEm(t) {  // a vista (fracionária, durante a rotação da câmera)
  let v = D.eventos[0].depois.vista;
  for (const e of D.eventos) {
    if (e.tipo !== 'camera') continue;
    if (t < e.t0) break;
    let de = v, para = e.dados.para;
    let dif = ((para - de) % N + N) % N; if (dif > N / 2) dif -= N;      // o caminho mais curto
    const p = ease((t - e.t0) / e.dur);
    v = p >= 1 ? para : de + dif * p;
  }
  return v;
}

// ---------------------------------------------------------------- estado num instante
const EV = D.eventos;
function indice(t) { let lo = 0, hi = EV.length - 1, k = 0; while (lo <= hi) { const m = (lo + hi) >> 1; if (EV[m].t0 <= t) { k = m; lo = m + 1; } else hi = m - 1; } return k; }
const VAZIO = { stack: D.inicial, aposta: D.inicial.map(() => 0), pot: 0, board: [], fora: D.inicial.map(() => false), allin: D.inicial.map(() => false),
  ultima: D.inicial.map(() => ''), vez: null, equidade: {}, revelado: D.inicial.map(() => false), jogos: {}, ganhos: {}, rua: 'preflop' };
function cartasDadas(t) {  // quantas cartas cada jogador já recebeu
  const n = D.jogadores.map(() => 0), quando = D.jogadores.map(() => Array(NC).fill(null));
  for (const e of EV) { if (e.tipo !== 'carta_jogador') continue; if (e.t0 + e.dur <= t) n[e.dados.quem]++; quando[e.dados.quem][e.dados.k] = e; }
  return { n, quando };
}

window.render = function (t) {
  const k = indice(t), e = EV[k], antes = k > 0 ? EV[k - 1].depois : VAZIO, depois = e.depois;
  const p = clamp((t - e.t0) / Math.max(0.001, e.dur), 0, 1), pe = ease(p);
  const fim = p >= 0.999;
  const st = fim ? depois : antes;
  const vista = vistaEm(t);   // a vista sempre termina com o jogador observado embaixo (o ponto de vista dele)
  const intro = e.tipo === 'intro' ? pe : 1;
  palco.style.opacity = 1;
  PSI = GIRAR ? 0 : (vista - VISTA0) * ANG;   // modo "girar" (antigo): os lugares deslizam; padrão: a câmera gira em volta
  inclinar();
  poeMesa(intro);
  const dadas = cartasDadas(t);
  const MODO = modoEm(t);
  const heroiIdx = D.jogadores.findIndex(j => j.heroi);
  // ---- assentos
  assentos.forEach((a, i) => {
    const ang = angAssento(i, vista);
    const [x, y] = ponto(ang, SRX, SRY);
    const baixo = Math.sin(ang * Math.PI / 180) > 0.6;
    const R = parseFloat(a.av.style.width) / 2;
    const ax = x, ay = y - R * 0.35;
    a.av.style.left = ax + 'px'; a.av.style.top = ay + 'px'; a.av.style.opacity = intro;
    a.placa.style.left = x + 'px'; a.placa.style.top = (ay + R * 0.72) + 'px'; a.placa.style.opacity = intro;
    const foraAgora = st.fora[i] || (e.tipo === 'acao' && e.dados.quem === i && e.dados.acao === 'fold' && p > 0.6);
    a.av.style.filter = foraAgora ? 'grayscale(1) brightness(.55)' : 'none'; a.placa.style.filter = foraAgora ? 'brightness(.6)' : 'none';
    // stack (conta durante a ação)
    let sv = st.stack[i];
    if (!fim && ['acao', 'blinds', 'vencedor'].includes(e.tipo)) sv = lerp(antes.stack[i], depois.stack[i], clamp((p - 0.15) / 0.6, 0, 1));
    a.stack.textContent = st.allin[i] && sv <= 0.001 ? 'ALL-IN' : fmt(sv);
    // vez (anel + barra do tempo)
    const vez = (e.tipo === 'pensa' && e.dados.quem === i) || (e.tipo === 'acao' && e.dados.quem === i && p < 0.4);
    a.av.style.boxShadow = vez ? `0 0 0 ${5 * S}px ${T.acento}, 0 0 ${30 * S}px ${T.acento}` : `0 ${6 * S}px ${16 * S}px #0009`;
    a.barra.style.opacity = vez ? 1 : 0; a.barra.style.transform = `scaleX(${e.tipo === 'pensa' && e.dados.quem === i ? 1 - p : 0})`;
    // vencedor
    const venceu = e.tipo === 'vencedor' || e.tipo === 'final' ? (depois.ganhos[i] || 0) > 0 && (e.tipo === 'final' || p > 0.55) : false;
    a.placa.style.boxShadow = venceu ? `0 0 0 ${3 * S}px ${T.valor}, 0 0 ${40 * S}px ${T.valor}` : `0 ${8 * S}px ${18 * S}px #000a`;
    // ação (badge)
    let rot = st.ultima[i];
    if (e.tipo === 'acao' && e.dados.quem === i) rot = p > 0.25 ? e.dados.rotulo : antes.ultima[i];
    if (venceu) rot = '+' + fmt(depois.ganhos[i]);
    if (rot && UNI_L !== 'bb' && !venceu && /^(BET|RAISE|CALL|ALL-IN)/.test(rot)) rot = rot.replace(/(-?[\d.]+)$/, (m0) => fmt(parseFloat(m0)));   // "ALL-IN 44.5" → "ALL-IN US$ 44,5"
    a.badge.textContent = rot || '';
    a.badge.style.display = rot ? 'block' : 'none';
    const corB = /FOLD/.test(rot) ? '#6b7280' : /ALL-IN/.test(rot) ? '#dc2626' : /RAISE|BET/.test(rot) ? '#f59e0b' : /CALL/.test(rot) ? '#22c55e' : /^\+/.test(rot) ? T.valor : '#64748b';
    a.badge.style.background = corB; a.badge.style.color = /^\+/.test(rot) ? '#111' : '#fff';
    a.badge.style.left = (ax - R * 0.95) + 'px'; a.badge.style.top = (ay - R * 0.95) + 'px';
    a.pos.style.display = OP.posicoes && D.tipo_jogo !== 'stud' ? 'block' : 'none'; a.pos.style.left = (ax + R * 0.95) + 'px'; a.pos.style.top = (ay - R * 0.95) + 'px';
    // equidade
    // 👁 POV: só a mão de quem está na vista (a câmera troca → as cartas dele somem e as do outro aparecem)
    const povPeso = clamp(1 - Math.abs(angDiff(i, vista)) * 2, 0, 1);
    const peso = m => m === 'todas' ? 1 : m === 'heroi' ? (i === heroiIdx ? 1 : 0) : m === 'pov' ? povPeso : 0;
    const mostrar = lerp(peso(MODO.de), peso(MODO.m), MODO.q);
    const ehVista = MODO.m === 'pov' ? povPeso > 0.5 : i === heroiIdx;
    const eq = st.equidade[i];
    a.eq.style.display = OP.equidade && eq != null && !st.fora[i] && (MODO.m !== 'pov' || ehVista || st.revelado[i]) && !['vencedor', 'final', 'showdown'].includes(e.tipo) ? 'block' : 'none';
    if (eq != null) { a.eq.textContent = String(eq).replace('.', ',') + '%'; a.eq.style.opacity = e.tipo === 'equidade' ? pe : 1; }
    a.eq.style.left = ax + 'px'; a.eq.style.top = (ay + R * 0.72 + 104 * S) + 'px';
    // jogo no showdown
    const jogo = (k > 0 || fim) && (depois.jogos[i] || st.jogos[i]) && ['showdown', 'vencedor', 'final'].includes(e.tipo) ? (depois.jogos[i]) : '';
    a.jogo.style.display = jogo ? 'block' : 'none'; a.jogo.textContent = jogo || '';
    a.jogo.style.left = ax + 'px'; a.jogo.style.top = (ay + R * 0.72 + 104 * S) + 'px'; a.jogo.style.opacity = e.tipo === 'showdown' ? pe : 1;
    // cartas do jogador
    const cosA = Math.cos(ang * Math.PI / 180);
    const lado = Math.abs(cosA) > 0.25 ? -Math.sign(cosA) : 1;   // pro lado do centro da mesa
    let cx = ax + lado * R * 1.62, cy = ay - R * 0.15;
    a.cartas.forEach((c, kk) => {
      const q = dadas.quando[i][kk];
      const chegou = q && t >= q.t0 + q.dur;
      const voando = q && t >= q.t0 && t < q.t0 + q.dur;
      // a carta de agora (no Draw ela muda na troca)
      const trocaAgora = e.tipo === 'troca' && e.dados.quem === i && (e.dados.pos || []).includes(kk);
      const cods = (trocaAgora && p < 0.5 ? antes : st).maos;
      setCarta(c, (cods && cods[i] ? cods[i][kk] : D.jogadores[i].cartas[kk]) || null);
      const abertaSempre = (D.abertas || []).includes(kk);   // Stud: as cartas abertas todo mundo vê
      let aberta = mostrar || st.revelado[i] || abertaSempre ? 1 : 0;
      if (e.tipo === 'showdown' && depois.revelado[i] && !antes.revelado[i] && !mostrar) aberta = pe;
      const meio = kk - (NC - 1) / 2, passo = NC <= 2 ? 0.84 : 1.5 / (NC - 1);
      let ox = cx + meio * passo * CW, oy = cy, rz = NC <= 2 ? meio * 14 : meio * 22 / (NC - 1);
      if (ehVista && !foraAgora && baixo) { ox = ax + meio * (NC <= 2 ? 1.1 : 2.2 / (NC - 1)) * CW * 1.25; oy = ay - R * 1.0; rz = NC <= 2 ? meio * 10 : meio * 16 / (NC - 1); }
      let op = chegou ? 1 : 0, x2 = ox, y2 = oy, esc = ehVista && baixo ? (NC <= 2 ? 1.25 : NC <= 4 ? 1.05 : 0.92) : (NC <= 2 ? 0.82 : NC <= 4 ? 0.62 : 0.52);
      if (voando) { const pp = ease((t - q.t0) / q.dur); x2 = lerp(CX, ox, pp); y2 = lerp(CY, oy, pp); op = 1; aberta = 0; }
      // 🂠 fold: as cartas deslizam viradas pra mesa, na frente do jogador, e FICAM ali (o "muck") até o fim da mão
      const [mx0, my0] = ponto(ang + 9, RX * 0.8, RY * 0.76);
      const mx = mx0 + (kk - (NC - 1) / 2) * CW * 0.32, my = my0 + (kk % 2) * 4 * S;
      const mrot = ((i * 37 + kk * 53) % 36) - 18 + (ang - 90) * 0.5, mesc = NC <= 2 ? 0.62 : 0.5;
      const foldAgora = e.tipo === 'acao' && e.dados.quem === i && e.dados.acao === 'fold';
      const noMuck = st.fora[i] && !foldAgora && chegou;
      if (noMuck) { x2 = mx; y2 = my; rz = mrot; aberta = 0; op = 1; esc = mesc; }   // opacidade < 1 achata o 3D (mostraria a face): escurece com filtro
      if (foldAgora) {
        const q = ease(clamp((p - 0.1) / 0.75, 0, 1));
        x2 = lerp(ox, mx, q); y2 = lerp(oy, my, q) - Math.sin(Math.PI * q) * 30 * S; rz = lerp(rz, mrot + 360 * 0, q);
        esc = lerp(esc, mesc, q); aberta = aberta * (1 - clamp(q * 3, 0, 1)); op = 1;
      }
      if (trocaAgora) {   // Draw: a carta velha vai pro meio e some; a nova vem do baralho
        if (p < 0.45) { const q2 = ease(p / 0.45); x2 = lerp(ox, CX, q2); y2 = lerp(oy, CY, q2) - Math.sin(Math.PI * q2) * 30 * S; aberta = aberta * (1 - q2); op = 1 - q2 * 0.9; }
        else if (p < 0.55) op = 0;
        else { const q2 = ease((p - 0.55) / 0.45); x2 = lerp(CX, ox, q2); y2 = lerp(CY, oy, q2); aberta = q2 > 0.8 ? aberta : 0; }
      }
      if (e.tipo === 'intro') op = 0;
      poeCarta(c, x2, y2, aberta, rz, op, esc);
      c._verso.style.filter = noMuck ? 'brightness(.7)' : '';
      c.style.zIndex = 5;
    });
    // aposta na frente
    const [bx, by] = ponto(ang, RX * 0.62, RY * 0.6);
    a._bx = bx; a._by = by; a._ax = ax; a._ay = ay;
    let ap = st.aposta[i];
    if (e.tipo === 'acao' && e.dados.quem === i && !fim) ap = p > 0.8 ? depois.aposta[i] : antes.aposta[i];
    if (e.tipo === 'blinds' && !fim) ap = p > 0.75 ? depois.aposta[i] : antes.aposta[i];
    if (e.tipo === 'recolher' && !fim) ap = 0;
    pilha(a.pilha, nFichas(ap), 15 * S); a.pilha.style.left = bx + 'px'; a.pilha.style.top = by + 'px';
    a.valor.style.display = ap > 0 ? 'block' : 'none'; a.valor.textContent = fmt(ap); a.valor.style.left = bx + 'px'; a.valor.style.top = (by + 30 * S) + 'px';
  });
  // ---- botão do dealer
  { const ang = angAssento(D.botao, vista); const [x, y] = ponto(ang, RX * 0.8, RY * 0.78); dealer.style.left = (x + 34 * S) + 'px'; dealer.style.top = y + 'px'; dealer.style.opacity = intro; }
  // ---- board (+ as fileiras do run it twice: cada uma desce embaixo da anterior)
  const bw = BOARD_W * 1.08;
  const bxs = depois.boards_x || [];
  let linhas = 1;
  bxs.forEach(b => { const ent = e.tipo === 'board' && e.dados.run === b.run && e.dados.pos === b.corte && (antes.boards_x || []).length < bxs.length ? pe : 1; linhas += ent; });
  const EL = linhas > 1 ? 0.8 : 1, LH = BOARD_W * 1.45 * EL;
  const yLinha = r => CY + 6 * S + (r - (linhas - 1) / 2) * LH;
  const virar = (c, x, y, jaTem, ehAgora) => {
    let op = jaTem ? 1 : 0, aberta = 1, xx = x, yy = y, rot = 0;
    if (ehAgora) {   // o dealer desliza a carta virada do baralho até o lugar e depois vira (com easing)
      op = 1;
      const q = ease(clamp(p / 0.42, 0, 1));
      const dx0 = CX + (x - CX) * 0.35, dy0 = y - BOARD_W * 1.7;
      xx = lerp(dx0, x, q); yy = lerp(dy0, y, q); rot = (1 - q) * -14;
      aberta = ease(clamp((p - 0.48) / 0.42, 0, 1));
    }
    poeCarta(c, xx, yy, aberta, rot, op, EL);
  };
  boardC.forEach((c, j) => {
    setCarta(c, depois.board[j] || antes.board[j] || null);
    virar(c, CX + (j - 2) * bw * EL, yLinha(0), !!st.board[j], e.tipo === 'board' && !e.dados.run && e.dados.pos === j);
  });
  boardX.forEach((linha, r) => {
    const b = bxs[r], bAntes = (st.boards_x || [])[r];
    linha.forEach((c, j) => {
      const k = b ? j - b.corte : -1;
      if (!b || k < 0) { c.style.display = 'none'; return; }
      setCarta(c, b.cartas[k] || null);
      virar(c, CX + (j - 2) * bw * EL, yLinha(r + 1), !!(bAntes && bAntes.cartas[k]), e.tipo === 'board' && e.dados.run === b.run && e.dados.pos === j);
    });
  });
  const BAIXO = (linhas - 1) * LH / 2;   // o que fica embaixo do board desce junto
  // ---- pot
  let pot = st.pot;
  if (e.tipo === 'recolher' && !fim) pot = p > 0.85 ? depois.pot : antes.pot;
  if (e.tipo === 'vencedor' && !fim) pot = p > 0.8 ? 0 : antes.pot;
  const somaApostas = st.aposta.reduce((a, b) => a + b, 0);
  potLbl.textContent = 'Pot ' + fmt(pot + (e.tipo === 'recolher' ? 0 : somaApostas));
  potLbl.style.display = (pot > 0 || somaApostas > 0) && e.tipo !== 'final' ? 'block' : 'none';
  potLbl.style.left = CX + 'px'; potLbl.style.top = (CY - BAIXO - BOARD_W * 0.95 - 30 * S) + 'px';
  pilha(potPilha, nFichas(pot), 17 * S); potPilha.style.left = CX + 'px'; potPilha.style.top = (CY + BAIXO + BOARD_W * 0.95 + 20 * S) + 'px';
  potPilha.style.opacity = pot > 0 ? 1 : 0;
  // ---- fichas voando
  voo.forEach(v => { v.innerHTML = ''; v.style.opacity = 0; });
  const voar = (v, x0, y0, x1, y1, pp, n) => { pilha(v, n, 14 * S); v.style.left = lerp(x0, x1, pp) + 'px'; v.style.top = (lerp(y0, y1, pp) - Math.sin(Math.PI * pp) * 40 * S) + 'px'; v.style.opacity = 1; };
  if (e.tipo === 'acao' && e.dados.valor > 0 && p < 0.85) { const a = assentos[e.dados.quem]; const pp = ease(clamp((p - 0.2) / 0.6, 0, 1)); voar(voo[0], a._ax, a._ay, a._bx, a._by, pp, nFichas(e.dados.valor)); }
  if (e.tipo === 'blinds' && p < 0.8) e.dados.quem.forEach((q, m) => { const a = assentos[q]; voar(voo[m], a._ax, a._ay, a._bx, a._by, ease(clamp(p / 0.75, 0, 1)), 2); });
  if (e.tipo === 'recolher' && p < 0.9) e.dados.de.forEach((q, m) => { const a = assentos[q]; if (m < voo.length) voar(voo[m], a._bx, a._by, CX, CY + BOARD_W * 0.95 + 20 * S, ease(p / 0.9), nFichas(antes.aposta[q])); });
  if (e.tipo === 'vencedor' && p > 0.35 && p < 0.95) e.dados.quem.forEach((q, m) => { const a = assentos[q]; voar(voo[m], CX, CY + BOARD_W * 0.95 + 20 * S, a._ax, a._ay, ease((p - 0.35) / 0.6), nFichas(depois.ganhos[q] || 1)); });
  // ---- rua, nota, título
  const nomesRua = { preflop: 'PRÉ-FLOP', flop: 'FLOP', turn: 'TURN', river: 'RIVER', s3: '3ª RUA', s4: '4ª RUA', s5: '5ª RUA', s6: '6ª RUA', s7: '7ª RUA', troca: 'TROCA', pos: 'APOSTAS FINAIS' };
  ruaLbl.style.left = CX + 'px'; ruaLbl.style.top = (CY + BAIXO + BOARD_W * 0.78) + 'px';
  potPilha.style.top = (CY + BAIXO + BOARD_W * 1.25 + 20 * S) + 'px';
  ruaLbl.textContent = e.tipo === 'intro' ? '' : (e.tipo === 'vencedor' || e.tipo === 'final' || e.tipo === 'showdown') ? (e.dados && e.dados.sem_showdown ? '' : 'SHOWDOWN') : nomesRua[st.rua] || '';
  if (e.tipo === 'nota') { nota.style.display = 'block'; nota.textContent = e.dados.texto; nota.style.opacity = Math.min(1, p * 6, (1 - p) * 6); }
  else nota.style.display = 'none';
  titulo.style.opacity = e.tipo === 'intro' ? pe : (t < 6 ? 1 : 0.55);
  efeitos(t, e, p, pe, antes, depois);
  fimUI(t, e, p, k);
};
function alvoZoom(alvo) {   // onde a câmera aproxima: um jogador (índice), o board ou o pot
  if (typeof alvo === 'number' && assentos[alvo]) return [assentos[alvo]._ax, assentos[alvo]._ay + 40 * S];
  if (alvo === 'pot') return [CX, CY + BOARD_W * 1.1];
  return [CX, CY];
}
function zoomEm(t) {
  if (!OP.zoom) return { z: 1, x: CX, y: CY };
  let ant = { z: 1, alvo: 'board' }, cur = ant, t0 = -9, dur = 0.7;
  for (const x of D.zooms || []) { if (x.t0 > t) break; ant = cur; cur = { z: x.escala, alvo: x.alvo }; t0 = x.t0; dur = x.dur; }
  const q = ease(clamp((t - t0) / dur, 0, 1));
  const [ax, ay] = alvoZoom(ant.alvo === 'off' ? 'board' : ant.alvo), [bx, by] = alvoZoom(cur.alvo === 'off' ? 'board' : cur.alvo);
  return { z: lerp(ant.z, cur.z, q), x: lerp(ant.z > 1 ? ax : bx, bx, q), y: lerp(ant.z > 1 ? ay : by, by, q) };
}
function emocoes(t) {
  assentos.forEach(a => { a.emo.style.display = 'none'; a.emoTxt.style.display = 'none'; });
  if (!OP.emocoes) return;
  for (const x of D.emocoes || []) {
    if (t < x.t0 || t > x.t0 + x.dur) continue;
    const a = assentos[x.quem]; if (!a) continue;
    const q = (t - x.t0) / x.dur, ent = clamp(q / 0.14, 0, 1), sai = clamp((1 - q) / 0.16, 0, 1);
    const c1 = 1.70158, back = ent >= 1 ? 1 : 1 + (c1 + 1) * Math.pow(ent - 1, 3) + c1 * Math.pow(ent - 1, 2);
    const bal = Math.sin(t * 9) * 7 * (1 - Math.abs(q - 0.5));
    a.emo.style.display = 'block'; a.emo.textContent = x.emoji;
    a.emo.style.left = a._ax + 'px'; a.emo.style.top = (a._ay - (1 - sai) * 50 * S) + 'px';
    a.emo.style.opacity = Math.min(ent * 2, sai); a.emo.style.transform = `translate(-50%,-50%) scale(${back * (0.6 + 0.4 * sai)}) rotate(${bal}deg)`;
    if (x.texto) {
      a.emoTxt.style.display = 'block'; a.emoTxt.textContent = x.texto;
      a.emoTxt.style.left = a._ax + 'px'; a.emoTxt.style.top = (a._ay - 150 * S) + 'px';
      a.emoTxt.style.opacity = Math.min(clamp((q - 0.1) / 0.12, 0, 1), sai);
      a.emoTxt.style.transform = `translate(-50%, ${(1 - Math.min(1, (q - 0.1) / 0.12)) * 16 * S}px)`;
    }
  }
}
function efeitos(t, e, p, pe, antes, depois) {
  let z = 1, dx = 0, dy = 0, tremida = 0, vin = 0, txt = '', sub = '', a0 = 0, esc = 1;
  emocoes(t);
  estrategiaUI(t, e, p);
  // 🔍 zoom narrativo ([zoom: Fulano] · [zoom: board] · [zoom: off]) — junta com o zoom dos shorts
  // 📐 enquadramento automático: a câmera se afasta/centraliza pra mesa inteira caber em qualquer ângulo
  { let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
    for (let i = 0; i < N; i++) { const [x, y] = ponto(angAssento(i, vistaEm(t)), SRX, SRY); x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    for (let a = 0; a < 360; a += 30) { const [x, y] = ponto(a, RX + BW, RY + BW); x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    x0 -= 110 * S; x1 += 110 * S; y0 -= 120 * S; y1 += 175 * S;
    const topo = VERT ? 210 * S : 20 * S, base = (SH ? 30 : 16) * S;
    const k = Math.min(1, (W - 20 * S) / (x1 - x0), (H - topo - base) / (y1 - y0));
    const bx = (x0 + x1) / 2, by = (y0 + y1) / 2, tx = W / 2, ty = topo + (H - topo - base) / 2;
    z = k; dx = tx - W / 2 - (bx - W / 2) * k; dy = ty - H / 2 - (by - H / 2) * k; }
  const ZM = zoomEm(t);
  if (ZM.z > 1.001) { const w = Math.min(1, (ZM.z - 1) / 0.3) * 0.85, Z = z * ZM.z;
    dx = lerp(dx, (W / 2 - ZM.x) * Z, w); dy = lerp(dy, (H / 2 - ZM.y) * Z, w); z = Z; }
  // 🎥 a câmera dá a volta na mesa até o lugar do jogador observado (sem cortar a mesa): no meio do caminho ela
  // se afasta um pouco e inclina (sensação de câmera andando em 3D), e chega atrás dele — o ponto de vista dele
  let tilt = 0;
  if (!GIRAR) { const C = camEm(t); if (C.de !== C.para && C.q > 0 && C.q < 1) { const k = Math.sin(Math.PI * C.q); z *= 1 - 0.05 * k; tilt = 4 * k; } }
  // 💰 o valor na moeda de hoje / o que comprava na época (aparece no final)
  nota.style.top = ''; nota.style.bottom = NOTA_BOTTOM;
  if (D.dinheiro && OP.dinheiro && e.tipo === 'final') { nota.style.top = (VERT ? 260 : 110) * S + 'px'; nota.style.bottom = 'auto'; nota.style.display = 'block'; nota.textContent = '💰 ' + D.dinheiro; nota.style.opacity = Math.min(1, p * 6, (1 - p) * 6); }
  const pop = q => 1 + 0.6 * Math.pow(1 - clamp(q, 0, 1), 3);      // entra grande e assenta
  const some = q => Math.min(1, q * 8, (1 - q) * 3);
  if (SH) {
    if (e.tipo === 'acao' && /ALL-IN/.test(e.dados.rotulo || '')) {
      const a = assentos[e.dados.quem], k = Math.sin(Math.PI * clamp(p * 1.1, 0, 1));
      z *= 1 + 0.14 * k; dx += (CX - a._ax) * 0.3 * k; dy += (CY - a._ay) * 0.3 * k; tremida = p > 0.28 && p < 0.5 ? 1 : 0; vin = 0.55 * k;
      txt = 'ALL-IN'; sub = D.jogadores[e.dados.quem].nome; a0 = some(clamp((p - 0.2) / 0.8, 0, 1)); esc = pop((p - 0.2) * 4);
    } else if (e.tipo === 'board' && e.dados.pos === 4) {
      const k = Math.sin(Math.PI * p); z *= 1 + 0.12 * k; dy += -BOARD_W * 0.15 * k; vin = 0.7 * k;
      if (p < 0.45) { txt = 'RIVER…'; a0 = some(p / 0.45); esc = pop(p * 5); }
    } else if (e.tipo === 'vencedor') {
      const q = e.dados.quem[0]; tremida = p > 0.35 && p < 0.5 ? 0.6 : 0; vin = 0.35 * Math.sin(Math.PI * p);
      txt = D.jogadores[q].nome; sub = '+' + fmt(e.dados.pot) + (depois.jogos[q] ? ' · ' + depois.jogos[q] : ''); a0 = some(clamp((p - 0.3) / 0.7, 0, 1)); esc = pop((p - 0.3) * 4);
    } else if (e.tipo === 'showdown') { vin = 0.4 * Math.sin(Math.PI * p); }
  }
  const sx = tremida ? Math.sin(t * 97) * 9 * S * tremida : 0, sy = tremida ? Math.cos(t * 83) * 7 * S * tremida : 0;
  cena.style.transform = z !== 1 || dx || dy || sx || sy || tilt ? `perspective(${W * 1.4}px) translate(${dx + sx}px, ${dy + sy}px) rotateX(${tilt}deg) scale(${z})` : '';
  vinheta.style.opacity = Math.max(vin, EST.vinheta || 0);
  if (grao) { grao.style.backgroundPosition = `${(Math.floor(t * 24) * 37) % 200}px ${(Math.floor(t * 24) * 91) % 200}px`; }
  fxTxt.textContent = txt; fxTxt.style.opacity = txt ? a0 : 0; fxTxt.style.transform = `translate(-50%, -50%) scale(${esc})`;
  const fy = VERT ? H * 0.33 : H * 0.32;   // acima do board (não cobre as cartas)
  fxTxt.style.top = fy + 'px';
  fxSub.textContent = sub; fxSub.style.opacity = sub ? a0 : 0; fxSub.style.top = (fy - (VERT ? 115 : 110) * S) + 'px';   // o nome em cima do letreiro
  const g0 = EV[0].dur;   // o gancho entra depois da abertura e fica ~3 s
  const gq = (t - g0 * 0.3) / 3.2;
  gancho.style.opacity = GANCHO && gq > 0 && gq < 1 ? Math.min(1, gq * 8, (1 - gq) * 6) : 0;
  gancho.style.transform = `translateX(-50%) scale(${GANCHO ? pop(gq * 4) : 1})`;
  if (GANCHO && gq > 0 && gq < 1) titulo.style.opacity = 0;
  progresso.style.width = (100 * clamp(t / D.duracao, 0, 1)) + '%';
}
// onde cada coisa está na tela (pra quem embute a mesa num vídeo maior apontar setas e rótulos)
window.lugaresTela = () => assentos.map(a => { const r = a.av.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; });
window.botaoTela = () => { const r = dealer.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; };
window.render(0);
window.pronto = true;

if (D.modo === 'previa') {
  document.body.className = 'previa';
  const ctl = el('div', '', document.body); ctl.id = 'controles';
  const bt = el('button', '', ctl); bt.textContent = '⏸';
  const rg = el('input', '', ctl); rg.type = 'range'; rg.min = 0; rg.max = D.duracao; rg.step = 0.01; rg.value = 0;
  const lb = el('span', '', ctl);
  let tocando = true, t0 = performance.now(), base = 0;
  const ajustar = () => { const e = Math.min(innerWidth / W, (innerHeight - 44) / H); palco.style.transform = `scale(${e})`; };
  ajustar(); addEventListener('resize', ajustar);
  bt.onclick = () => { tocando = !tocando; bt.textContent = tocando ? '⏸' : '▶'; base = +rg.value; t0 = performance.now(); };
  rg.oninput = () => { base = +rg.value; t0 = performance.now(); window.render(base); };
  const laco = () => { if (tocando) { let t = base + (performance.now() - t0) / 1000; if (t > D.duracao + 0.5) { base = 0; t0 = performance.now(); t = 0; } rg.value = t; window.render(t); lb.textContent = t.toFixed(1) + ' / ' + D.duracao.toFixed(1) + ' s'; } requestAnimationFrame(laco); };
  requestAnimationFrame(laco);
}
</script></body></html>"""
