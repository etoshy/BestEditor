"""
explicador.py — 🎬 Explicador animado (v84_278)
================================================

Narração + legenda → vídeo explicativo em motion graphics (o estilo do "How to Play Poker"):
textos cinéticos, cartas, escada de ranking, listas, dicas, comparações, fichas, ícones, marca/like/inscrever e mãos de
poker no simulador 2D (poker_mesa + poker_render), tudo sincronizado com a narração.

O PLANO é um JSON de cenas; cada coisa aparece quando o narrador fala uma FRASE (âncora). A legenda (SRT ou Whisper)
dá o tempo de cada frase. A 🤖 IA escreve o plano a partir da narração; você pode ajustar à mão.

Fluxo: projeto (narração + legenda) → 🤖 plano → 👁 prévia (com o áudio) → 🎞 renderizar (1080p ou 4K, várias cenas em
paralelo) → ⬇ MP4  ou  🎬 mandar pro editor (uma cena por trecho, narração+efeitos no áudio, música separada).
"""
from __future__ import annotations

import base64
import html as _h
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

AQUI = os.path.dirname(os.path.abspath(__file__))
MOTOR = os.path.join(AQUI, "assets", "explicador", "motor.html")
SONS = os.path.join(AQUI, "assets", "sons")
FONTES_ARQ = "file://" + os.path.join(AQUI, "assets", "fonts", "dp").replace("\\", "/")
_TRAVA = threading.RLock()
FPS = 30
RESOLUCOES = {"1080p": 1, "2160p": 2}

FUNDOS = {  # bg1, bg2, bg3, card
    "verde": ("#0f3b23", "#08200f", "#030a06", "#0b1a10"), "azul": ("#13255a", "#0a1433", "#03060f", "#0b1226"),
    "roxo": ("#3b1660", "#1d0a33", "#08030f", "#160a26"), "vermelho": ("#5a1313", "#300909", "#0c0202", "#1f0a0a"),
    "preto": ("#2a2a2a", "#121212", "#030303", "#141414"), "petroleo": ("#0f3a40", "#082125", "#020809", "#0a1a1c"),
}
CORES = {"acento": "gold", "amarelo": "gold", "vermelho": "red", "verde": "green", "branco": "white"}


class ExplicadorErro(Exception):
    pass


# ------------------------------------------------------------------ projetos
def raiz(base: str) -> str:
    return os.environ.get("EXPLICADOR_DIR") or os.path.join(base, "explicador")


def pasta(pid: str, base: str) -> str:
    if not re.fullmatch(r"[a-z0-9]{6,20}", pid or ""):
        raise ExplicadorErro("projeto inválido")
    return os.path.join(raiz(base), pid)


def opcoes_padrao() -> Dict[str, Any]:
    return {"resolucao": "2160p", "acento": "#facc15", "fundo": "verde", "simbolos": "♠♥♦♣", "musica": "sintetizada",
            "volume_musica": 0.32, "sfx": True, "barra_topo": False, "estilo": "dinamico", "trabalhadores": 2, "marca1": "", "marca2": "", "marca_simbolo": "♠",
            "idioma": "en"}


def novo(base: str, titulo: str, audio: str, srt: str = "") -> Dict[str, Any]:
    pid = uuid.uuid4().hex[:10]
    d = pasta(pid, base)
    os.makedirs(d, exist_ok=True)
    ext = os.path.splitext(audio)[1].lower() or ".wav"
    destino = os.path.join(d, "narracao" + ext)
    shutil.copyfile(audio, destino)
    p = {"id": pid, "titulo": (titulo or "Explicador").strip()[:120], "criado": time.time(), "audio": os.path.basename(destino),
         "duracao": duracao_audio(destino), "segs": [], "op": opcoes_padrao(), "plano": {"cenas": []}, "saida": {}, "editor": {},
         "musica_arquivo": "", "log": [], "trechos": [], "_dir": d}
    os.makedirs(os.path.join(d, "midia"), exist_ok=True)
    if srt.strip():
        p["segs"] = ler_srt(srt)
    salvar(p, base)
    return p


def carregar(pid: str, base: str) -> Dict[str, Any]:
    cam = os.path.join(pasta(pid, base), "projeto.json")
    if not os.path.isfile(cam):
        raise ExplicadorErro("projeto não encontrado")
    with open(cam, encoding="utf-8") as f:
        p = json.load(f)
    p["op"] = dict(opcoes_padrao(), **(p.get("op") or {}))
    p["_dir"] = pasta(pid, base)
    return p


def salvar(p: Dict[str, Any], base: str) -> None:
    d = pasta(p["id"], base)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "projeto.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in p.items() if not k.startswith("_")}, f, ensure_ascii=False, indent=1)
    p["_dir"] = d
    os.replace(tmp, os.path.join(d, "projeto.json"))


def listar(base: str) -> List[Dict[str, Any]]:
    out = []
    r = raiz(base)
    if not os.path.isdir(r):
        return out
    for pid in os.listdir(r):
        try:
            p = carregar(pid, base)
        except Exception:  # noqa: BLE001
            continue
        out.append({"id": pid, "titulo": p["titulo"], "criado": p.get("criado", 0), "duracao": p.get("duracao", 0),
                    "cenas": len((p.get("plano") or {}).get("cenas") or []), "mp4": bool((p.get("saida") or {}).get("mp4"))})
    return sorted(out, key=lambda x: -x["criado"])


def excluir(pid: str, base: str) -> None:
    shutil.rmtree(pasta(pid, base), ignore_errors=True)


def log(p: Dict[str, Any], msg: str) -> None:
    p.setdefault("log", []).append([time.time(), str(msg)[:300]])
    p["log"] = p["log"][-60:]


def caminho_audio(p: Dict[str, Any], base: str) -> str:
    return os.path.join(pasta(p["id"], base), p["audio"])


def duracao_audio(cam: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", cam],
                           capture_output=True, text=True, timeout=60)
        return round(float(r.stdout.strip()), 3)
    except Exception:  # noqa: BLE001
        return 0.0


# ------------------------------------------------------------------ legenda → tempo de cada frase
def ler_srt(texto: str) -> List[List[Any]]:
    segs = []
    for b in re.split(r"\n\s*\n", texto.replace("\r", "").strip()):
        ls = b.strip().splitlines()
        i = next((k for k, x in enumerate(ls) if "-->" in x), None)
        if i is None:
            continue
        a, c = [x.strip() for x in ls[i].split("-->")[:2]]

        def f(s: str) -> float:
            s = s.replace(",", ".").split()[0]
            h, m, r = s.split(":")
            return int(h) * 3600 + int(m) * 60 + float(r)
        try:
            txt = " ".join(ls[i + 1:]).strip()
            if txt:
                segs.append([round(f(a), 3), round(f(c), 3), re.sub(r"<[^>]+>", "", txt)])
        except (ValueError, IndexError):
            continue
    return segs


def segs_de_whisper(res: Any) -> List[List[Any]]:
    """O resultado do Whisper do site (segments com words) → [[ini, fim, texto]] (palavra por palavra quando dá)."""
    segs = res.get("segments") if isinstance(res, dict) else res
    out = []
    for s in segs or []:
        ws = s.get("words") or []
        if ws:
            for w in ws:
                t = str(w.get("word") or w.get("text") or "").strip()
                if t:
                    out.append([round(float(w["start"]), 3), round(float(w["end"]), 3), t])
        elif str(s.get("text") or "").strip():
            out.append([round(float(s["start"]), 3), round(float(s["end"]), 3), str(s["text"]).strip()])
    return out


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'")
    s = re.sub(r"[^\w']+", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


class Tempos:
    """Acha em que segundo o narrador fala uma frase (texto da legenda normalizado, char → tempo)."""

    def __init__(self, segs: List[List[Any]]):
        self.txt, self.idx = "", []
        for a, b, t in segs:
            n = _norm(str(t))
            if not n:
                continue
            if self.txt:
                self.txt += " "
                self.idx.append(a)
            for k in range(len(n)):
                self.idx.append(a + (b - a) * k / max(1, len(n)))
            self.txt += n
        self.fim = segs[-1][1] if segs else 0.0

    def quando(self, frase: Any, depois: float = 0.0) -> Optional[float]:
        if isinstance(frase, (int, float)):
            return float(frase)
        n = _norm(str(frase or ""))
        if not n or not self.txt:
            return None
        pals = n.split()
        for tam in (len(pals), 7, 5, 4, 3, 2):
            if tam > len(pals) or tam < 1:
                continue
            alvo = " ".join(pals[:tam])
            p = 0
            while True:
                i = self.txt.find(alvo, p)
                if i < 0:
                    break
                ok_ini = i == 0 or self.txt[i - 1] == " "
                if ok_ini and self.idx[i] >= depois - 0.6:
                    return round(self.idx[i], 3)
                p = i + 1
        return None

    def texto(self) -> str:
        return self.txt


def transcricao_com_tempos(segs: List[List[Any]], passo: float = 0.0) -> str:
    """Pra IA: frases com o segundo de início ([12.3] texto…), juntando palavras em linhas de ~12 palavras."""
    linhas, cur, ini = [], [], None
    for a, b, t in segs:
        if ini is None:
            ini = a
        cur.append(str(t).strip())
        if len(cur) >= 12 or re.search(r"[.!?]$", str(t).strip()):
            linhas.append(f"[{ini:.1f}] " + " ".join(cur))
            cur, ini = [], None
    if cur:
        linhas.append(f"[{ini:.1f}] " + " ".join(cur))
    return "\n".join(linhas)


# ------------------------------------------------------------------ montar a página (o vídeo inteiro é uma página)
SVG = {
    "tv": '<svg viewBox="0 0 64 64" width="150"><rect x="6" y="12" width="52" height="34" rx="5" fill="none" stroke="#fff" stroke-width="4"/><path d="M22 56h20M32 46v10" stroke="#fff" stroke-width="4"/><polygon points="27,22 27,36 39,29" fill="var(--ac)"/></svg>',
    "cassino": '<svg viewBox="0 0 64 64" width="150"><circle cx="32" cy="32" r="26" fill="#ef4444"/><circle cx="32" cy="32" r="26" fill="none" stroke="#fff" stroke-width="6" stroke-dasharray="10 10"/><circle cx="32" cy="32" r="15" fill="#fff"/><text x="32" y="38" font-size="16" text-anchor="middle" fill="#ef4444" font-weight="800">$</text></svg>',
    "online": '<svg viewBox="0 0 64 64" width="150"><rect x="10" y="12" width="44" height="30" rx="3" fill="none" stroke="#fff" stroke-width="4"/><path d="M4 50h56" stroke="#fff" stroke-width="5"/><circle cx="32" cy="27" r="7" fill="var(--ac)"/></svg>',
    "trofeu": '<svg viewBox="0 0 64 64" width="150"><path d="M18 8h28v14c0 10-6 17-14 17S18 32 18 22z" fill="var(--ac)"/><path d="M18 14H8c0 9 5 13 11 13M46 14h10c0 9-5 13-11 13" fill="none" stroke="var(--ac)" stroke-width="4"/><rect x="28" y="38" width="8" height="10" fill="var(--ac)"/><rect x="18" y="48" width="28" height="8" rx="2" fill="#fff"/></svg>',
    "bandeira": '<svg viewBox="0 0 64 64" width="150"><path d="M14 6v54" stroke="#fff" stroke-width="5"/><path d="M16 8h34l-8 10 8 10H16z" fill="#fff"/></svg>',
    "escudo": '<svg viewBox="0 0 64 64" width="150"><path d="M32 4l24 9v17c0 15-10 26-24 30C18 56 8 45 8 30V13z" fill="#22c55e"/><path d="M20 32l8 8 16-16" stroke="#fff" stroke-width="6" fill="none"/></svg>',
    "relogio": '<svg viewBox="0 0 64 64" width="150"><circle cx="32" cy="32" r="26" fill="none" stroke="#fff" stroke-width="5"/><path d="M32 16v17l11 7" stroke="var(--ac)" stroke-width="5" fill="none" stroke-linecap="round"/></svg>',
    "check": '<svg viewBox="0 0 64 64" width="150"><circle cx="32" cy="32" r="28" fill="#22c55e"/><path d="M18 33l9 9 19-19" stroke="#fff" stroke-width="7" fill="none"/></svg>',
    "x": '<svg viewBox="0 0 64 64" width="150"><circle cx="32" cy="32" r="28" fill="#ef4444"/><path d="M21 21l22 22M43 21L21 43" stroke="#fff" stroke-width="7"/></svg>',
    "dinheiro": '<svg viewBox="0 0 64 64" width="150"><rect x="4" y="16" width="56" height="32" rx="5" fill="#16a34a"/><circle cx="32" cy="32" r="10" fill="none" stroke="#fff" stroke-width="4"/><text x="32" y="38" font-size="15" text-anchor="middle" fill="#fff" font-weight="800">$</text></svg>',
    "cerebro": '<svg viewBox="0 0 64 64" width="150"><path d="M24 10c-8 0-12 6-11 12-6 2-8 10-4 15-2 7 3 14 11 14 3 4 9 4 12 0V12c-2-2-5-2-8-2zM40 10c8 0 12 6 11 12 6 2 8 10 4 15 2 7-3 14-11 14-3 4-9 4-12 0V12c2-2 5-2 8-2z" fill="#f472b6"/></svg>',
    "alvo": '<svg viewBox="0 0 64 64" width="150"><circle cx="32" cy="32" r="27" fill="#ef4444"/><circle cx="32" cy="32" r="19" fill="#fff"/><circle cx="32" cy="32" r="11" fill="#ef4444"/><circle cx="32" cy="32" r="4" fill="#fff"/></svg>',
    "estrela": '<svg viewBox="0 0 64 64" width="150"><polygon points="32,4 40,24 62,24 44,38 51,60 32,46 13,60 20,38 2,24 24,24" fill="var(--ac)"/></svg>',
    "usuarios": '<svg viewBox="0 0 64 64" width="150"><circle cx="22" cy="22" r="9" fill="#fff"/><circle cx="44" cy="22" r="9" fill="var(--ac)"/><path d="M6 54c0-10 7-16 16-16s16 6 16 16zM28 54c0-10 7-16 16-16s16 6 16 16z" fill="#fff" opacity=".9"/></svg>',
    "grafico": '<svg viewBox="0 0 64 64" width="150"><rect x="8" y="36" width="10" height="20" fill="#fff"/><rect x="26" y="24" width="10" height="32" fill="#fff"/><rect x="44" y="10" width="10" height="46" fill="var(--ac)"/></svg>',
    "cartas": '<svg viewBox="0 0 64 64" width="150"><rect x="8" y="10" width="28" height="40" rx="4" fill="#fff" transform="rotate(-12 22 30)"/><rect x="26" y="12" width="28" height="40" rx="4" fill="#fff" transform="rotate(10 40 32)"/><text x="41" y="40" font-size="20" text-anchor="middle" fill="#dc2626">♥</text></svg>',
    "fichas": '<svg viewBox="0 0 64 64" width="150"><ellipse cx="32" cy="44" rx="22" ry="9" fill="#ef4444"/><ellipse cx="32" cy="36" rx="22" ry="9" fill="#3b82f6"/><ellipse cx="32" cy="28" rx="22" ry="9" fill="var(--ac)"/></svg>',
    "lampada": '<svg viewBox="0 0 64 64" width="150"><path d="M32 6a18 18 0 00-10 33v7h20v-7A18 18 0 0032 6z" fill="var(--ac)"/><rect x="24" y="48" width="16" height="5" fill="#fff"/><rect x="26" y="55" width="12" height="4" fill="#fff"/></svg>',
    "aviso": '<svg viewBox="0 0 64 64" width="150"><polygon points="32,6 60,56 4,56" fill="var(--ac)"/><rect x="29" y="22" width="6" height="18" fill="#111"/><rect x="29" y="44" width="6" height="6" fill="#111"/></svg>',
    "olho": '<svg viewBox="0 0 64 64" width="150"><path d="M4 32C12 18 22 12 32 12s20 6 28 20c-8 14-18 20-28 20S12 46 4 32z" fill="#fff"/><circle cx="32" cy="32" r="12" fill="#ef4444"/><circle cx="32" cy="32" r="5" fill="#111"/><circle cx="36" cy="28" r="2.5" fill="#fff"/></svg>',
    "robo": '<svg viewBox="0 0 64 64" width="150"><rect x="30" y="4" width="4" height="10" fill="#fff"/><circle cx="32" cy="5" r="4" fill="var(--ac)"/><rect x="12" y="14" width="40" height="32" rx="8" fill="#94a3b8"/><circle cx="24" cy="29" r="5" fill="#22d3ee"/><circle cx="40" cy="29" r="5" fill="#22d3ee"/><rect x="22" y="38" width="20" height="3" fill="#1e293b"/><rect x="18" y="48" width="28" height="12" rx="3" fill="#64748b"/><rect x="4" y="24" width="6" height="14" rx="3" fill="#64748b"/><rect x="54" y="24" width="6" height="14" rx="3" fill="#64748b"/></svg>',
    "mascara": '<svg viewBox="0 0 64 64" width="150"><path d="M4 22c8-4 18-4 28 2 10-6 20-6 28-2 0 14-6 22-14 22-6 0-9-6-14-6s-8 6-14 6C10 44 4 36 4 22z" fill="#111" stroke="#fff" stroke-width="3"/><ellipse cx="20" cy="29" rx="6" ry="4" fill="#fff"/><ellipse cx="44" cy="29" rx="6" ry="4" fill="#fff"/></svg>',
    "celular": '<svg viewBox="0 0 64 64" width="150"><rect x="18" y="4" width="28" height="56" rx="5" fill="#fff"/><rect x="21" y="10" width="22" height="40" fill="#1e293b"/><rect x="24" y="16" width="7" height="10" rx="1" fill="#fff"/><rect x="33" y="16" width="7" height="10" rx="1" fill="#fff"/><text x="27.5" y="24" font-size="7" text-anchor="middle" fill="#dc2626">A</text><text x="36.5" y="24" font-size="7" text-anchor="middle" fill="#111">K</text><circle cx="32" cy="55" r="2.5" fill="#94a3b8"/></svg>',
    "embaralhador": '<svg viewBox="0 0 64 64" width="150"><rect x="6" y="26" width="52" height="28" rx="5" fill="#475569"/><rect x="14" y="14" width="16" height="18" rx="2" fill="#fff" transform="rotate(-8 22 23)"/><rect x="34" y="14" width="16" height="18" rx="2" fill="#fff" transform="rotate(8 42 23)"/><rect x="12" y="36" width="40" height="5" rx="2" fill="#111"/><circle cx="50" cy="47" r="3" fill="#ef4444"/><path d="M44 8l-4 8h6l-4 8" stroke="var(--ac)" stroke-width="3" fill="none"/></svg>',
    "balanca": '<svg viewBox="0 0 64 64" width="150"><rect x="30" y="8" width="4" height="46" fill="#fff"/><rect x="18" y="54" width="28" height="5" rx="2" fill="#fff"/><path d="M8 16h48" stroke="#fff" stroke-width="4"/><path d="M14 16L6 34h16zM50 16l-8 18h16z" fill="none" stroke="var(--ac)" stroke-width="3"/><path d="M6 34a8 4 0 0016 0zM42 34a8 4 0 0016 0z" fill="var(--ac)"/></svg>',
    "camera": '<svg viewBox="0 0 64 64" width="150"><rect x="4" y="18" width="56" height="36" rx="6" fill="#fff"/><rect x="20" y="10" width="22" height="10" rx="3" fill="#fff"/><circle cx="32" cy="36" r="12" fill="#1e293b"/><circle cx="32" cy="36" r="6" fill="#38bdf8"/><circle cx="51" cy="26" r="3" fill="#ef4444"/></svg>',
    "martelo": '<svg viewBox="0 0 64 64" width="150"><rect x="14" y="10" width="26" height="14" rx="3" fill="#a16207" transform="rotate(-35 27 17)"/><rect x="26" y="20" width="6" height="30" fill="#ca8a04" transform="rotate(-35 29 35)"/><rect x="8" y="52" width="40" height="8" rx="2" fill="#fff"/></svg>',
    "lupa": '<svg viewBox="0 0 64 64" width="150"><circle cx="26" cy="26" r="17" fill="none" stroke="#fff" stroke-width="6"/><circle cx="26" cy="26" r="11" fill="#38bdf833"/><path d="M38 38l18 18" stroke="var(--ac)" stroke-width="8" stroke-linecap="round"/></svg>',
    "sinal": '<svg viewBox="0 0 64 64" width="150"><circle cx="32" cy="50" r="5" fill="var(--ac)"/><path d="M20 38a17 17 0 0124 0M12 29a28 28 0 0140 0M4 20a40 40 0 0156 0" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round"/></svg>',
    "grades": '<svg viewBox="0 0 64 64" width="150"><rect x="6" y="6" width="52" height="52" rx="4" fill="#1e293b" stroke="#fff" stroke-width="4"/><path d="M18 6v52M32 6v52M46 6v52" stroke="#94a3b8" stroke-width="5"/><path d="M6 30h52" stroke="#94a3b8" stroke-width="4"/></svg>',
    "raiox": '<svg viewBox="0 0 64 64" width="150"><rect x="4" y="20" width="56" height="30" rx="4" fill="#065f46"/><rect x="10" y="26" width="14" height="18" rx="2" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-dasharray="3 2"/><rect x="28" y="26" width="14" height="18" rx="2" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-dasharray="3 2"/><text x="17" y="40" font-size="9" text-anchor="middle" fill="#22d3ee" font-weight="800">A</text><text x="35" y="40" font-size="9" text-anchor="middle" fill="#22d3ee" font-weight="800">K</text><path d="M48 8v12M44 12l4-4 4 4" stroke="#22d3ee" stroke-width="3" fill="none"/><path d="M4 58h56" stroke="#22d3ee" stroke-width="3" stroke-dasharray="4 3"/></svg>',
    "cadeado": '<svg viewBox="0 0 64 64" width="150"><path d="M20 28V20a12 12 0 0124 0v8" fill="none" stroke="#fff" stroke-width="6"/><rect x="12" y="28" width="40" height="30" rx="5" fill="var(--ac)"/><circle cx="32" cy="41" r="4" fill="#111"/><rect x="30" y="42" width="4" height="9" fill="#111"/></svg>',
    "manga": '<svg viewBox="0 0 64 64" width="150"><path d="M2 20l26-6 8 30-26 6z" fill="#1e3a8a"/><rect x="34" y="20" width="18" height="26" rx="3" fill="#fff" transform="rotate(-14 43 33)"/><text x="43" y="38" font-size="12" text-anchor="middle" fill="#dc2626" transform="rotate(-14 43 33)">A♥</text></svg>',
}
LIKE_SVG = ('<svg viewBox="0 0 24 24" width="{w}" height="{w}"><path class="thumb" d="M2 21h4V9H2v12zm20-11c0-1.1-.9-2-2-2h-6.3l1-4.6v-.3c0-.4-.2-.8-.4-1.1L13.2 1 6.6 7.6C6.2 7.9 6 8.4 6 9v10c0 1.1.9 2 2 2h9c.8 0 1.5-.5 1.8-1.2l3-7.1c.1-.2.2-.5.2-.7v-2z"/></svg>')
CURSOR = '<svg viewBox="0 0 24 24" width="90" height="90"><path d="M3 2l7 19 2.5-7.5L20 11z" fill="#fff" stroke="#000" stroke-width="1.4"/></svg>'
SUITS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
RANKING_POKER = {
    "high": ("HIGH CARD", "Nothing — your highest card plays", ["As", "Jd", "8c", "5h", "3s"], [0]),
    "pair": ("ONE PAIR", "Two cards of the same value", ["Ks", "Kh", "9d", "6c", "2s"], [0, 1]),
    "twopair": ("TWO PAIR", "Two different pairs", ["Ks", "Kh", "5d", "5c", "9s"], [0, 1, 2, 3]),
    "trips": ("THREE OF A KIND", "Three cards of the same value", ["7s", "7h", "7d", "Kc", "2s"], [0, 1, 2]),
    "straight": ("STRAIGHT", "5 in a row — suits don't matter", ["5c", "6d", "7h", "8s", "9c"], [0, 1, 2, 3, 4]),
    "flush": ("FLUSH", "5 of the same suit, any order", ["2h", "6h", "9h", "Jh", "Kh"], [0, 1, 2, 3, 4]),
    "full": ("FULL HOUSE", "Three of a kind + a pair", ["Qs", "Qh", "Qd", "4c", "4s"], [0, 1, 2, 3, 4]),
    "quads": ("FOUR OF A KIND", "All four of the same value", ["9s", "9h", "9d", "9c", "Ks"], [0, 1, 2, 3]),
    "sf": ("STRAIGHT FLUSH", "5 in a row, same suit", ["5s", "6s", "7s", "8s", "9s"], [0, 1, 2, 3, 4]),
    "royal": ("ROYAL FLUSH", "A-K-Q-J-10, same suit", ["Ah", "Kh", "Qh", "Jh", "Th"], [0, 1, 2, 3, 4]),
}
CORES_ACAO = ["#94a3b8", "#f59e0b", "#22c55e", "#f97316", "#64748b", "#ef4444", "#3b82f6", "#a855f7"]
CARTA_RE = re.compile(r"^(?:[2-9TJQKA][shdc]|\?\?)$")


def _e(s: Any) -> str:
    return _h.escape(str(s if s is not None else ""), quote=True)


def _card(c: str, w: int = 150, cls: str = "") -> str:
    c = str(c or "")
    if not CARTA_RE.match(c) or c == "??":
        return f'<div class="card back {cls}" style="--w:{w}px"></div>'
    r, s = ("10" if c[0] == "T" else c[0]), c[1]
    return (f'<div class="card {"red" if s in "hd" else ""} {cls}" style="--w:{w}px"><span class="cr">{r}</span>'
            f'<span class="cs">{SUITS[s]}</span><span class="cb">{SUITS[s]}</span></div>')


def _cartas(lista: Any) -> List[str]:
    out = []
    for c in lista or []:
        c = str(c).strip()
        if len(c) == 2:
            c = c[0].upper().replace("1", "T") + c[1].lower()
        if c.startswith("10") and len(c) == 3:
            c = "T" + c[2].lower()
        if CARTA_RE.match(c):
            out.append(c)
    return out[:13]


def _chip(color: str, sz: int = 90) -> str:
    return f'<div class="chip" style="--c:{color};--z:{sz}px"></div>'


class Construtor:
    """Plano (JSON) → cenas HTML + sons + keyframes das mãos."""

    def __init__(self, p: Dict[str, Any], tempos: Tempos, fim: float):
        self.p, self.T, self.END = p, tempos, fim
        self.op = p["op"]
        self.snd: List[Tuple[float, str]] = []
        self.avisos: List[str] = []
        self.cenas_html: List[str] = []
        self.maos: Dict[str, Dict[str, Any]] = {}
        self.capitulos: List[Tuple[str, float]] = []
        self.linha: List[Dict[str, Any]] = []
        self.cap_fim = fim
        self._tec_html, self._topo = "", 0
        self.pid_dir = p.get("_dir") or ""
        self.clipes: List[Dict[str, Any]] = []
        self.inseridos: List[Dict[str, Any]] = []
        self.audio_montado = ""

    # ---------------- tempo
    def t(self, frase: Any, depois: float, padrao: float, onde: str = "") -> float:
        if frase is None or frase == "":
            return round(padrao, 3)
        v = self.T.quando(frase, depois)
        if v is None:
            self.avisos.append(f"não achei na narração: “{str(frase)[:60]}”" + (f" ({onde})" if onde else ""))
            return round(padrao, 3)
        return v

    # ---------------- elementos
    def E(self, a: float, html: str, fx: str = "up", b: Optional[float] = None, x: Optional[float] = None, y: Optional[float] = None,
          cls: str = "", style: str = "", snd: Optional[str] = "pop", on: Optional[Tuple[float, float]] = None, extra: str = "") -> str:
        pos = (f"left:{x:.0f}px;" if x is not None else "") + (f"top:{y:.0f}px;" if y is not None else "")
        if snd:
            self.snd.append((round(a, 3), snd))
        o = f' data-on="{on[0]:.3f},{on[1]:.3f}"' if on else ""
        bb = "" if b is None else f"{b:.3f}"
        return f'<div class="e {cls}" data-a="{a:.3f}" data-b="{bb}" data-fx="{fx}"{o} style="{pos}{style}" {extra}>{html}</div>'

    ESTILOS = {  # fonte, altura do slot, efeito, som
        "titulo": (210, 240, "zoom", "impact"), "grande": (130, 160, "down", "impact"), "medio": (80, 110, "up", None),
        "pequeno": (54, 80, "up", None), "tag": (52, 110, "pop", "pop"), "aviso": (52, 110, "stamp", "stamp"),
        "ok": (52, 110, "stamp", "stamp"), "carimbo": (200, 230, "stamp", "impact"), "nota": (40, 90, "up", None),
        "relogio": (170, 440, "zoom", "impact"), "numero": (180, 210, "pop", "pop"), "marca": (70, 170, "zoom", "impact"),
        "caixa": (58, 230, "left", "pop"), "capitulo": (44, 90, "left", None),
        "caso": (52, 140, "left", "whoosh"), "contagem": (170, 210, "pop", "impact"),
    }

    def linha_html(self, ln: Dict[str, Any]) -> Tuple[str, str, str]:
        est = ln.get("estilo") or "medio"
        tx = _e(ln.get("texto") or "")
        cor = ln.get("cor") or ("acento" if est in ("titulo", "carimbo", "contagem") else "branco")
        col = {"acento": "var(--ac)", "amarelo": "var(--ac)", "branco": "#fff", "vermelho": "#ef4444", "verde": "#22c55e"}.get(cor, "#fff")
        f, _h_, fx, snd = self.ESTILOS.get(est, self.ESTILOS["medio"])
        cls = "c glow" if est in ("titulo", "carimbo", "contagem") or (est == "grande" and cor == "acento") else "c"
        if est in ("tag", "aviso", "ok"):
            k = {"tag": "gold", "aviso": "red", "ok": "green"}[est] if not ln.get("cor") else CORES.get(cor, "gold")
            html = f'<div class="tag {k}{" rot" if ln.get("girado") else ""}">{tx}</div>'
        elif est == "nota":
            html = f'<div class="note">{tx}</div>'
        elif est == "relogio":
            m = re.match(r"^\s*(\d+):(\d\d)\s*$", str(ln.get("texto") or ""))
            ini = int(m.group(1)) * 60 + int(m.group(2)) if m else 0
            html = (f'<div class="ringw" data-ini="{ini}" data-a="__A__" data-b="__B__"><svg viewBox="0 0 420 420"><circle cx="210" cy="210" r="170" class="rbg"/>'
                    f'<circle cx="210" cy="210" r="170" class="rfg"/></svg><div class="h clk">{tx}</div><small>{_e(ln.get("sub") or "")}</small></div>')
        elif est == "numero":
            html = f'<div class="h" style="font-size:{f}px;color:{col}">{tx}<span style="font-size:70px;color:#fff;margin-left:20px">{_e(ln.get("sub") or "")}</span></div>'
        elif est == "marca":
            html = self.marca_html()
        elif est == "caixa":
            html = (f'<div class="way" {self._tcls(ln)}><div class="num">{_e(ln.get("num") or "")}</div><div class="wt">{tx}'
                    + (f'<br><small>{_e(ln.get("sub"))}</small>' if ln.get("sub") else "") + "</div></div>")
        elif est == "capitulo":
            html = f'<div class="chap">{tx}</div>'
        elif est == "caso":  # "2010 · WPT BARCELONA" → selo com o ano + o lugar
            partes = [x.strip() for x in str(ln.get("texto") or "").split("·", 1)]
            html = (f'<div class="caso"><b>{_e(partes[0])}</b><span>{_e(partes[1]) if len(partes) > 1 else ""}</span></div>' if len(partes) > 1
                    else f'<div class="caso"><span>{tx}</span></div>')
        elif est == "contagem":  # "$22,000,000" conta de 0 até o valor
            m = re.match(r"^\s*([^\d]*)([\d.,]+)(.*)$", str(ln.get("texto") or ""))
            if m:
                v = float(m.group(2).replace(",", ""))
                html = (f'<div class="h" style="font-size:{f}px;color:{col}"><span class="cnt" data-v="{int(v) if v == int(v) else v}" data-pre="{_e(m.group(1))}" '
                        f'data-suf="{_e(m.group(3))}" data-a="__A__">{tx}</span>'
                        f'<span style="font-size:64px;color:#fff;margin-left:20px">{_e(ln.get("sub") or "")}</span></div>')
            else:
                html = f'<div class="h" style="font-size:{f}px;color:{col}">{tx}</div>'
        else:
            html = f'<div class="h" style="font-size:{f}px;color:{col}">{tx}</div>'
        return html, fx, cls

    def _tcls(self, ln: Dict[str, Any]) -> str:
        t = ln.get("_hot")
        return f'data-tcls="hot@{t:.3f}"' if t else ""

    def marca_html(self, big: bool = False) -> str:
        o = self.op
        n1, n2 = _e(o.get("marca1") or ""), _e(o.get("marca2") or self.p.get("titulo") or "")
        return (f'<div class="brandbox{" big" if big else ""}"><div class="logo">{_e(o.get("marca_simbolo") or "★")}</div>'
                f'<div><div class="bt1">{n1}</div><div class="bt2">{n2}</div></div></div>')

    def linhas(self, lns: List[Dict[str, Any]], a: float, b: float, y0: float, y1: float, cx: float = 960,
               fim_padrao: Optional[float] = None) -> str:
        """Empilha as linhas na faixa [y0, y1] (centralizado). substitui: ocupa o lugar da anterior; lado: esq/dir na mesma fileira."""
        if not lns:
            return ""
        if self._topo and y0 < self._topo:
            y0 = self._topo
        slots: List[Dict[str, Any]] = []
        prev_t = a
        for k, ln in enumerate(lns):
            if not isinstance(ln, dict) or not (ln.get("texto") or ln.get("estilo") == "marca"):
                continue
            t0 = self.t(ln.get("em"), prev_t, min(b - 0.6, a + 0.3 + 0.9 * k), "linha")
            t0 = max(a, t0)
            prev_t = t0
            ln = dict(ln, _t=t0)
            ln["_b"] = self.t(ln.get("ate"), t0, -1, "linha (até)") if ln.get("ate") else None
            if ln["_b"] is not None and ln["_b"] < 0:
                ln["_b"] = None
            if ln.get("destaca_em"):
                ln["_hot"] = self.t(ln["destaca_em"], t0, t0 + 2)
            est = ln.get("estilo") or "medio"
            alt = self.ESTILOS.get(est, self.ESTILOS["medio"])[1]
            if ln.get("substitui") and slots:
                s = slots[-1]
                for x in s["itens"]:
                    if x.get("_b") is None or x["_b"] > t0 - 0.05:
                        x["_b"] = t0 - 0.05
                s["itens"].append(ln)
                s["alt"] = max(s["alt"], alt)
            elif ln.get("lado") == "dir" and slots and slots[-1]["itens"][-1].get("lado") == "esq":
                slots[-1]["itens"].append(ln)
                slots[-1]["alt"] = max(slots[-1]["alt"], alt)
            else:
                slots.append({"alt": alt, "itens": [ln]})
        total = sum(s["alt"] for s in slots)
        esc = min(1.0, (y1 - y0) / max(1, total))
        y = y0 + ((y1 - y0) - total * esc) / 2
        out = []
        for s in slots:
            yc = y + s["alt"] * esc / 2
            for ln in s["itens"]:
                html, fx, cls = self.linha_html(ln)
                fx = ln.get("efeito") or fx
                est = ln.get("estilo") or "medio"
                snd = self.ESTILOS.get(est, self.ESTILOS["medio"])[3]
                bb = ln["_b"] if ln["_b"] is not None else fim_padrao
                if "__A__" in html:
                    html = html.replace("__A__", f"{ln['_t']:.3f}").replace("__B__", f"{(bb or b):.3f}")
                lado = ln.get("lado")
                x = cx - 400 if lado == "esq" else cx + 400 if lado == "dir" else cx
                if esc < 1:
                    html = f'<div style="transform:scale({esc:.3f})">{html}</div>'
                out.append(self.E(ln["_t"], html, fx, b=bb, x=x, y=yc, cls=cls, snd=snd))
            y += s["alt"] * esc
        return "".join(out)

    def cena(self, a: float, b: float, body: str, hand: Optional[Tuple[str, float, float, float, List[List[float]]]] = None) -> None:
        self.snd.append((round(a - 0.15, 3), "whoosh"))
        h = ""
        if hand:
            k, s, ox, oy, kf = hand
            h = (f'<iframe class="hand" src="maos/{k}.html" style="left:{ox}px;top:{oy}px;transform:scale({s})" '
                 f'data-s="{s}" data-ox="{ox}" data-oy="{oy}" data-kf="{_e(json.dumps(kf))}"></iframe>')
        body = (self._tec_html or "") + body
        self._tec_html = ""
        self.cenas_html.append(f'<section class="sc" data-a="{a:.3f}" data-b="{b:.3f}"><div class="in">{h}{body}</div></section>')

    def tecnica(self, tc: Dict[str, Any], a: float, b: float) -> str:
        """🔢 Cabeçalho de item numerado (\"Technique number one: collusion\"): grande no meio por ~2,6 s, depois vira etiqueta no canto."""
        t0 = self.t(tc.get("em"), a, a + 0.1, "técnica")
        n = _e(tc.get("n") or "")
        nome = _e(tc.get("nome") or "")
        rot = _e(tc.get("rotulo") or "TECHNIQUE")
        ic = SVG.get(str(tc.get("icone") or ""), "").replace('width="150"', 'width="230"')
        dur = float(tc.get("dur") or 2.6)
        out = self.E(t0, '<div class="dim"></div>', "fade", b=t0 + dur, x=0, y=0, snd=None)
        out += self.E(t0, f'<div class="tec"><div class="tec-n">#{n}</div>' + (f'<div class="tec-i">{ic}</div>' if ic else "")
                          + f'<div class="tec-t"><small>{rot}</small>{nome}</div></div>', "zoom", b=t0 + dur, x=960, y=540, cls="c", snd="impact")
        out += self.E(t0 + dur, f'<div class="chap">#{n} · {nome}</div>', "left", x=50, y=46, snd=None)
        return out

    # ---------------- tipos de cena
    def construir(self) -> None:
        cenas = [c for c in (self.p.get("plano") or {}).get("cenas") or [] if isinstance(c, dict)]
        if not cenas:
            raise ExplicadorErro("O plano não tem cenas (🤖 gere com a IA ou cole um plano).")
        inicios, ult = [], 0.0
        for k, c in enumerate(cenas):
            ins = self.trecho(c.get("trecho")) if c.get("trecho") else None
            if ins:
                t0 = max(0.0, ins["t0"] - 0.12)
            else:
                t0 = 0.0 if k == 0 and not c.get("de") else self.t(c.get("de"), ult, ult + 3 if k else 0, f"cena {k + 1}")
            if k and t0 <= ult + 0.5:
                t0 = ult + 0.5
                self.avisos.append(f"cena {k + 1}: começa cedo demais (encostei na anterior)")
            inicios.append(t0)
            ult = t0
        for k, c in enumerate(cenas):
            a = inicios[k]
            b = inicios[k + 1] + 0.3 if k + 1 < len(inicios) else self.END
            if c.get("capitulo"):
                self.capitulos.append((str(c["capitulo"]).upper()[:24], a))
            if c.get("fim_capitulos"):
                self.cap_fim = a
            tipo = c.get("tipo") or "texto"
            fn = getattr(self, "c_" + tipo, None)
            if not fn:
                self.avisos.append(f"cena {k + 1}: tipo desconhecido “{tipo}” (virou texto)")
                fn = self.c_texto
            self._tec_html, self._topo = "", 0
            if isinstance(c.get("tecnica"), dict):
                self._tec_html = self.tecnica(c["tecnica"], a, b)
                self._topo = 150
            try:
                fn(c, a, b, k)
            except ExplicadorErro:
                raise
            except Exception as exc:  # noqa: BLE001
                self.avisos.append(f"cena {k + 1} ({tipo}): {exc}")
                self.cena(a, b, self.linhas([{"texto": c.get("titulo") or "", "estilo": "grande"}], a, b, 60, 1020))
            self.linha.append({"n": k + 1, "tipo": tipo, "ini": round(a, 2), "fim": round(b, 2)})

    def trecho(self, n: Any) -> Optional[Dict[str, Any]]:
        """O trecho com som original nº n (1, 2…) depois de encaixado na narração."""
        try:
            n = int(n)
        except (TypeError, ValueError):
            return None
        for x in self.inseridos:
            if x["i"] == n - 1:
                return x
        self.avisos.append(f"trecho {n} não existe (veja a lista de trechos com som original)")
        return None

    def _titulo_topo(self, c: Dict[str, Any], a: float, b: float) -> str:
        if not c.get("titulo"):
            return ""
        return self.E(a + 0.05, f'<div class="h" style="font-size:80px;color:var(--ac)">{_e(c["titulo"])}</div>', "down", x=960, y=110, cls="c",
                      snd="impact")

    def c_texto(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        body, y0 = "", 60
        cartas = _cartas(c.get("cartas_topo"))
        if cartas:
            body += ('<div class="fanbox" style="top:300px">' + "".join(
                f'<div class="fan" data-a="{a + 0.1:.3f}" data-i="{i}" data-n="{len(cartas)}">{_card(x, 210)}</div>' for i, x in enumerate(cartas)) + "</div>")
            y0 = 520
        body += self.linhas(c.get("linhas") or ([{"texto": c.get("titulo"), "estilo": "grande"}] if c.get("titulo") else []), a, b, y0, 1030)
        self.cena(a, b, body)

    def c_marca(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        body = ""
        like_t = self.t(c.get("like"), a, -1) if c.get("like") else None
        sub_t = self.t(c.get("inscrever"), a, -1) if c.get("inscrever") else None
        like_t = like_t if like_t is not None and like_t >= 0 else None
        sub_t = sub_t if sub_t is not None and sub_t >= 0 else None
        logo = c.get("logo", True)
        if logo:
            yl = 300 if (like_t or sub_t) else 460
            body += self.E(self.t(c.get("em"), a, a + 0.2), self.marca_html(big=True), "zoom", x=960, y=yl, cls="c", snd="impact")
        pts = []
        if like_t is not None and like_t >= 0:
            if logo or sub_t:
                lx, ly, w = (700 if sub_t else 960), 620, 80
                body += self.E(like_t, f'<div class="likebtn sm" data-tcls="on@{like_t + 0.8:.3f}">{LIKE_SVG.format(w=w)}<span>LIKE</span></div>', "pop", x=lx, y=ly, cls="c")
                pts += [[like_t + 0.2, 1600, 1050, 0], [like_t + 0.8, lx + 20, ly + 20, 1]]
            else:
                lx, ly = 960, 520
                body += self.E(like_t, f'<div class="likebtn" data-tcls="on@{like_t + 0.85:.3f}">{LIKE_SVG.format(w=120)}<span>LIKE</span></div>', "pop", x=lx, y=ly, cls="c")
                body += f'<div class="burst" data-t="{like_t + 0.85:.3f}" style="left:{lx}px;top:{ly}px"></div>'
                pts += [[like_t + 0.2, 1500, 1050, 0], [like_t + 0.85, lx + 30, ly + 40, 1]]
            self.snd.append((round(like_t + 0.85, 3), "click"))
        if sub_t is not None and sub_t >= 0:
            sx, sy = (1200 if like_t else 960), 620
            body += self.E(sub_t, f'<div class="subbtn" data-tcls="on@{sub_t + 0.9:.3f}">SUBSCRIBE</div>', "pop", x=sx, y=sy, cls="c")
            if not pts:
                pts.append([sub_t + 0.2, 1600, 1050, 0])
            pts += [[sub_t + 0.9, sx + 20, sy + 20, 1]]
            self.snd.append((round(sub_t + 0.9, 3), "click"))
        if pts:
            body += f'<div class="cursor" data-p="{_e(json.dumps(pts))}">{CURSOR}</div>'
        body += self.linhas(c.get("linhas") or [], a, b, 760 if (like_t or sub_t or logo) else 120, 1040)
        self.cena(a, b, body)

    def c_icones(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        itens = [i for i in c.get("itens") or [] if isinstance(i, dict)][:4]
        n = len(itens)
        tem_linhas = bool(c.get("linhas"))
        y = 830 if tem_linhas else 560
        body = self.linhas(c.get("linhas") or [], a, b, 80, 680) if tem_linhas else self._titulo_topo(c, a, b)
        prev = a
        for i, it in enumerate(itens):
            t0 = self.t(it.get("em"), prev, a + 0.6 + i * 0.6, "ícone")
            prev = t0
            x = 960 + (i - (n - 1) / 2) * 440
            ic = SVG.get(str(it.get("icone") or "estrela"), SVG["estrela"])
            body += self.E(t0, f'<div class="icon">{ic}<b>{_e(it.get("texto") or "")}</b></div>', "pop", x=x, y=y, cls="c")
        self.cena(a, b, body)

    def c_fichas(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        t_drop = self.t(c.get("em"), a, a + 0.9)
        enc = self.t(c.get("encolhe"), t_drop, -1) if c.get("encolhe") else None
        cores = ["#ef4444", "#3b82f6", "#22c55e", "#111827", "#a855f7", "#facc15"]
        chips = "".join(f'<div class="pchip">{_chip(cores[i % 6], 150)}</div>' for i in range(16))
        body = f'<div class="pile" style="top:560px" data-a="{t_drop:.3f}" data-enc="{(enc if enc and enc > 0 else 1e9):.3f}">{chips}</div>'
        self.snd += [(round(t_drop + i * 0.11 + 0.35, 3), "ficha") for i in range(0, 16, 3)]
        if c.get("rotulo"):
            tr = self.t(c.get("rotulo_em"), t_drop, t_drop + 1.5)
            fim = enc - 0.1 if enc and enc > 0 else None
            body += self.E(tr, f'<div class="potlabel">{_e(c["rotulo"])}</div>', "stamp", b=fim, x=960, y=700, cls="c", snd="stamp")
        lns = c.get("linhas") or []
        top = [ln for ln in lns if (ln.get("pos") or "topo") == "topo"]
        base = [ln for ln in lns if (ln.get("pos") or "topo") == "base"]
        body += self.linhas(top, a, b, 50, 300) + self.linhas(base, a, b, 780, 1050)
        self.cena(a, b, body)

    def c_cartas(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        passos, prev = [], a
        for i, ps in enumerate([x for x in c.get("passos") or [] if isinstance(x, dict)]):
            cs = _cartas(ps.get("cartas"))
            if not cs:
                continue
            t0 = self.t(ps.get("em"), prev, a + 0.5 + i * 2, "cartas")
            prev = t0
            passos.append({"t": t0, "c": cs, "h": [int(x) for x in ps.get("destaque") or [] if str(x).isdigit()],
                           "seq": 0.33 if ps.get("um_a_um") else 0, "rotulo": ps.get("rotulo"), "est": ps.get("estilo_rotulo") or "tag"})
            if ps.get("um_a_um"):
                self.snd += [(round(t0 + j * 0.33, 3), "carta") for j in range(len(cs))]
            else:
                self.snd.append((round(t0, 3), "deal5"))
        n = max([len(x["c"]) for x in passos] or [5])
        w = 190 if n <= 5 else 160 if n <= 7 else 130 if n <= 10 else 118
        gap = 24 if n <= 5 else 12
        body = self._titulo_topo(c, a, b)
        slots = "".join('<div class="slot"></div>' for _ in range(n))
        body += f'<div class="rowc" style="top:560px" data-w="{w}" data-g="{gap}" data-p="{_e(json.dumps([{k_: v for k_, v in x.items() if k_ in "tchseq"} for x in passos]))}">{slots}</div>'
        for i, x in enumerate(passos):
            if x["rotulo"]:
                fim = passos[i + 1]["t"] - 0.1 if i + 1 < len(passos) else None
                html, fx, cls = self.linha_html({"texto": x["rotulo"], "estilo": x["est"]})
                body += self.E(x["t"] + 0.4 + (x["seq"] * len(x["c"]) if x["seq"] else 0), html, fx, b=fim, x=960, y=860, cls=cls)
        lns = c.get("linhas") or []
        body += self.linhas([ln for ln in lns if ln.get("pos") == "topo"], a, b, 170, 410)
        body += self.linhas([ln for ln in lns if ln.get("pos") != "topo"], a, b, 930, 1050)
        self.cena(a, b, body)

    def c_escada(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        itens = []
        prev = a
        for i, it in enumerate([x for x in c.get("itens") or [] if isinstance(x, dict)]):
            base = RANKING_POKER.get(str(it.get("chave") or ""), None)
            nome = it.get("nome") or (base[0] if base else f"#{i + 1}")
            itens.append({"t": self.t(it.get("em"), prev, a + 2 + i * 4, "escada"), "n": str(nome).upper()[:28],
                          "d": it.get("desc") or (base[1] if base else ""),
                          "c": _cartas(it.get("cartas")) or (base[2] if base else []),
                          "h": it.get("destaque") if it.get("destaque") is not None else (base[3] if base else []),
                          "brilho": bool(it.get("brilho") or it.get("chave") == "royal"), "nota": it.get("nota"), "nota_em": it.get("nota_em")})
            prev = itens[-1]["t"]
        if not itens:
            raise ExplicadorErro("escada sem itens")
        t1 = itens[0]["t"]
        body = self.linhas(c.get("linhas") or [], a, b, 80, 1000, fim_padrao=t1 - 0.1)
        n = len(itens)
        fs = 38 if n <= 10 else 30
        lad = "".join(f'<div class="lr" style="font-size:{fs}px" data-on="{itens[i]["t"]:.3f},{(itens[i + 1]["t"] if i + 1 < n else 9999):.3f}" '
                      f'data-seen="{itens[i]["t"]:.3f}"><b>{i + 1}</b><span>{_e(itens[i]["n"])}</span></div>' for i in range(n - 1, -1, -1))
        topo, fundo = (c.get("rotulos") or ["STRONGEST ▲", "WEAKEST ▼"])[:2] if isinstance(c.get("rotulos"), list) else ("STRONGEST ▲", "WEAKEST ▼")
        body += self.E(t1, f'<div class="ladder"><div class="lt">{_e(topo)}</div>{lad}<div class="lt">{_e(fundo)}</div></div>', "left", x=70, y=90, snd=None)
        P = [{"t": x["t"], "n": x["n"], "d": x["d"]} for x in itens]
        nm_size = 120 if max(len(x["n"]) for x in itens) <= 15 else 96
        body += self.E(t1, f'<div class="ladw" data-p="{_e(json.dumps(P))}"><div class="rkname" style="font-size:{nm_size}px"></div><div class="rkdesc"></div></div>',
                       "fade", x=1240, y=240, cls="c", snd=None)
        rows = [{"t": x["t"], "c": x["c"], "h": [int(h) for h in x["h"] if str(h).isdigit()], "seq": 0} for x in itens if x["c"]]
        if rows:
            body += (f'<div class="rowc" style="top:600px;left:1240px" data-w="190" data-g="24" data-p="{_e(json.dumps(rows))}">'
                     + '<div class="slot"></div>' * max(len(r["c"]) for r in rows) + "</div>")
        for x in itens:
            self.snd.append((round(x["t"], 3), "deal5" if x["c"] else "pop"))
            if x["brilho"]:
                body += f'<div class="royalfx" data-t="{x["t"]:.3f}" style="left:1240px;top:600px"></div>'
                self.snd.append((round(x["t"] + 0.1, 3), "impact"))
            if x["nota"]:
                tn = self.t(x["nota_em"], x["t"], x["t"] + 2)
                body += self.E(tn, f'<div class="tag gold">{_e(x["nota"])}</div>', "pop", x=1240, y=900, cls="c")
        self.cena(a, b, body)

    def c_comparacao(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        body = ""
        lns = c.get("linhas") or []
        body += self.linhas([ln for ln in lns if (ln.get("pos") or "topo") == "topo"], a, b, 40, 330)
        t0 = self.t(c.get("em"), a, a + 0.6)
        tr = self.t(c.get("resultado_em"), t0, t0 + 1.4) if c.get("vence") else None
        div = c.get("dividir") if isinstance(c.get("dividir"), dict) else None
        td = self.t(div.get("em"), t0, b - 3) if div else None

        def lado(d: Any, idn: str) -> str:
            d = d if isinstance(d, dict) else {"texto": str(d or "")}
            cs = _cartas(d.get("cartas"))
            perde = c.get("vence") in ("esquerda", "direita") and ((idn == "e") != (c["vence"] == "esquerda"))
            tc = f' data-tcls="lose@{tr:.3f}"' if perde and tr else ""
            inner = "".join(_card(x, 190) for x in cs) if cs else f'<div class="vtxt">{_e(d.get("texto") or "")}</div>'
            return f'<div class="vh"{tc}>{inner}</div>'
        fim_vs = td - 0.1 if td else None
        body += self.E(t0, f'<div class="vs">{lado(c.get("esquerda"), "e")}<div class="vsx">{_e(c.get("vs") or "VS")}</div>{lado(c.get("direita"), "d")}</div>',
                       "pop", x=960, y=600, b=fim_vs, cls="c")
        if tr:
            xv = 600 if c["vence"] == "esquerda" else 1320 if c["vence"] == "direita" else 960
            html = f'<div class="tag green rot">{_e(c.get("rotulo_vence") or ("TIE" if c["vence"] == "empate" else "WINS"))}</div>'
            body += self.E(tr, html, "stamp", x=xv, y=400, b=fim_vs, cls="c", snd="stamp")
        if div:
            body += (f'<div class="split" data-a="{td:.3f}" data-div="{td + 0.8:.3f}"><div>{_chip("#ef4444", 140)}{_chip("#3b82f6", 140)}</div>'
                     f'<div>{_chip("#ef4444", 140)}{_chip("#3b82f6", 140)}</div></div>')
            if div.get("texto"):
                body += self.E(self.t(div.get("texto_em"), td, td + 1.5), f'<div class="h" style="font-size:140px;color:var(--ac)">{_e(div["texto"])}</div>',
                               "stamp", x=960, y=850, cls="c glow", snd="stamp")
        body += self.linhas([ln for ln in lns if ln.get("pos") == "base"], a, b, 800, 1040)
        self.cena(a, b, body)

    def c_lista(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        body = ""
        if c.get("titulo"):
            body += self.E(a + 0.05, f'<div class="h" style="font-size:150px;color:var(--ac)">{_e(c["titulo"])}</div>', "stamp", x=960, y=150,
                           cls="c glow", snd="impact")
        itens = [i for i in c.get("itens") or [] if isinstance(i, dict)][:7]
        num = c.get("estilo") == "numerada"
        prev, rows = a, []
        for i, it in enumerate(itens):
            t0 = self.t(it.get("em"), prev, a + 1 + i * 1.2, "lista")
            prev = t0
            mark = f'<i class="num">{i + 1}</i>' if num else "<i>✓</i>"
            sub = f'<small>{_e(it["sub"])}</small>' if it.get("sub") else ""
            rows.append(f'<div class="ck" data-on="{t0:.3f},9999">{mark}<span>{_e(it.get("texto") or "")}{sub}</span></div>')
            self.snd.append((round(t0, 3), "tick"))
        cx = c.get("caixa") if isinstance(c.get("caixa"), dict) else None
        fs = 62 if len(itens) <= 5 else 50
        x0 = 260 if cx else 560
        if rows:
            first = min((float(r.split('data-on="')[1].split(",")[0]) for r in rows), default=a)
            body += self.E(first - 0.2, f'<div class="cklist" style="font-size:{fs}px">{"".join(rows)}</div>', "left", x=x0, y=300 if len(itens) <= 5 else 270, snd=None)
        if cx:
            t0 = self.t(cx.get("em"), a, b - 4)
            spans = "".join(f"<span>{_e(s)}</span>" for s in (cx.get("linhas") or [])[:3])
            body += self.E(t0, f'<div class="practice"><b>{_e(cx.get("titulo") or "")}</b>{spans}</div>', "right", x=1400, y=520, cls="c")
        br = c.get("barra") if isinstance(c.get("barra"), dict) else None
        if br:
            t0 = self.t(br.get("em"), a, b - 3)
            body += self.E(t0, f'<div style="width:700px;display:flex;flex-direction:column;gap:10px;align-items:center;font-weight:800;font-size:40px">'
                               f'<div class="fillbar" data-t="{t0 + 0.3:.3f}" data-w="700" style="height:40px;border-radius:20px;background:linear-gradient(90deg,#22c55e,var(--ac));box-shadow:0 0 30px #22c55e;width:0"></div>'
                               f'<span>{_e(br.get("texto") or "")}</span></div>', "up", x=1400 if cx else 960, y=820 if cx else 980, cls="c")
        self.cena(a, b, body)

    def c_dicas(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        itens = [i for i in c.get("itens") or [] if isinstance(i, dict)][:8]
        ts, prev = [], a
        for i, it in enumerate(itens):
            ts.append(self.t(it.get("em"), prev, a + 1.5 + i * 6, "dica"))
            prev = ts[-1]
        body = ""
        if c.get("titulo"):
            body += self.E(a - 0.1 if a > 0.2 else a, f'<div class="h" style="font-size:150px;color:var(--ac)">{_e(c["titulo"])}</div>', "zoom",
                           x=960, y=480, cls="c glow", b=(ts[0] - 0.05) if ts else None, snd="impact")
        for i, it in enumerate(itens):
            fim = ts[i + 1] - 0.05 if i + 1 < len(itens) else None
            vis = ""
            cs = _cartas(it.get("cartas"))
            if cs:
                xx = "x" if it.get("riscadas") else ""
                vis = '<div class="mrow">' + "".join(_card(x, 120, xx) + ("<i></i>" if it.get("pares") and j % 2 == 1 and j < len(cs) - 1 else "")
                                                     for j, x in enumerate(cs)) + "</div>"
            elif it.get("icone") in SVG:
                vis = SVG[it["icone"]].replace('width="150"', 'width="200"')
            body += self.E(ts[i], f'<div class="tip"><div class="tn">{i + 1}</div><div class="tt">{_e(it.get("titulo") or "")}</div>'
                                  f'<div class="td">{_e(it.get("texto") or "")}</div>' + (f'<div class="tv">{vis}</div>' if vis else "") + "</div>",
                           "right", x=960, y=540, cls="c", b=fim, snd="impact")
            if isinstance(it.get("selo"), dict) and it["selo"].get("texto"):
                tsl = self.t(it["selo"].get("em"), ts[i], ts[i] + 2)
                k_ = CORES.get(it["selo"].get("cor") or "verde", "green")
                body += self.E(tsl, f'<div class="tag {k_} rot">{_e(it["selo"]["texto"])}</div>', "stamp", x=1400, y=300, cls="c", b=fim, snd="stamp")
        self.cena(a, b, body)

    # ---------------- 🃏 a mão de poker no simulador 2D
    def c_mao(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        import poker_mesa as PM
        try:
            d = PM.simular(str(c.get("dsl") or ""))
        except Exception as exc:  # noqa: BLE001
            raise ExplicadorErro(f"cena {k + 1}: a mão não simulou — {exc}")
        nomes = [j["nome"].lower() for j in d["jogadores"]]
        ev = d["eventos"]

        def seat(nome: Any) -> Optional[int]:
            n = str(nome or "").strip().lower()
            return nomes.index(n) if n in nomes else None

        def evt(spec: Dict[str, Any]) -> Optional[float]:
            tp = str(spec.get("tipo") or "")
            n = int(spec.get("n") or 0)
            if tp == "inicio":
                return 0.0
            if tp == "distribuir":
                r = [e for e in ev if e["tipo"] == "carta_jogador"]
                return max(0.0, r[0]["t0"] - 0.05) if r else None
            if tp == "board" or tp in ("flop", "turn", "river"):
                pos = {"flop": 0, "turn": 3, "river": 4}.get(tp if tp != "board" else str(spec.get("rua") or ""), n)
                r = [e for e in ev if e["tipo"] == "board" and e["dados"].get("pos") == pos]
                return r[0]["t0"] if r else None
            if tp == "acao":
                q = seat(spec.get("quem"))
                ac = str(spec.get("acao") or "").lower().replace("-", "").replace("_", "")
                r = [e for e in ev if e["tipo"] == "acao" and (q is None or e["dados"].get("quem") == q)
                     and (not ac or e["dados"].get("acao") == ac)]
                return r[n]["t0"] - 0.3 if len(r) > n else None
            if tp in ("blinds", "showdown", "vencedor", "final", "recolher", "pensa"):
                r = [e for e in ev if e["tipo"] == tp]
                return (r[min(n, len(r) - 1)]["t0"] + (0.5 if tp == "final" else 0)) if r else None
            return None

        anc: List[Tuple[float, float]] = []
        pt0 = evt(c["comeca"]) if isinstance(c.get("comeca"), dict) else 0.0
        anc.append((a - 0.2, max(0.0, pt0 or 0.0)))
        prev = a
        for s in [x for x in c.get("ancoras") or [] if isinstance(x, dict)]:
            vt = self.t(s.get("em"), prev, -1, "âncora da mão")
            pt = evt(s.get("evento") or {})
            if vt < 0 or pt is None:
                if pt is None:
                    self.avisos.append(f"cena {k + 1}: evento da mão não existe: {json.dumps(s.get('evento'), ensure_ascii=False)[:80]}")
                continue
            vt += float(s.get("atraso") or 0)
            if vt <= anc[-1][0] + 0.05 or pt <= anc[-1][1]:
                continue
            anc.append((vt, pt))
            prev = vt
        fim_pt = evt({"tipo": "final"}) or d["duracao"]
        if c.get("ate") and isinstance(c["ate"], dict):
            fim_pt = evt(c["ate"]) or fim_pt
        if fim_pt > anc[-1][1] and b - 0.3 > anc[-1][0] + 0.1:
            anc.append((b - 0.3, fim_pt))
        kf = _keyframes(anc)
        mid = f"m{k + 1}"
        self.maos[mid] = {"dados": d, "mostrar": c.get("mostrar") or "heroi", "equidade": bool(c.get("equidade")), "tema": c.get("tema_mesa") or "verde"}
        self._sons_mao(ev, kf)
        painel = c.get("painel") if isinstance(c.get("painel"), dict) else None
        if painel and painel.get("itens"):
            s_, ox, oy, fx_ = 0.8, 370, 120, 1140
        else:
            s_, ox, oy, fx_ = 0.86, 134, 100, 960
        body = ""
        if c.get("titulo"):
            body += self.E(a + 0.05, f'<div class="chap">{_e(c["titulo"])}</div>', "left", x=40 if painel else 60, y=40 if painel else 50, snd=None)
        if painel and painel.get("itens"):
            its = [x for x in painel["itens"] if isinstance(x, dict)][:8]
            tts, pv = [], a
            for i, it in enumerate(its):
                tts.append(self.t(it.get("em"), pv, a + 2 + i * 3, "painel"))
                pv = tts[-1]
            rows = "".join(f'<div class="act" data-on="{tts[i]:.3f},{(tts[i + 1] if i + 1 < len(its) else 9999):.3f}" data-seen="{tts[i]:.3f}" '
                           f'style="--c:{it.get("cor") or CORES_ACAO[i % len(CORES_ACAO)]}"><b>{_e(it.get("texto") or "")}</b><span>{_e(it.get("sub") or "")}</span></div>'
                           for i, it in enumerate(its))
            body += self.E(min(tts) - 0.3 if tts else a + 0.4, f'<div class="acts">{rows}</div>', "left", x=40, y=150, snd=None)
            for i, it in enumerate(its):
                q = seat(it.get("jogador"))
                if q is not None:
                    fim = tts[i + 1] - 0.1 if i + 1 < len(its) else None
                    cor = it.get("cor") or CORES_ACAO[i % len(CORES_ACAO)]
                    body += self.E(tts[i] + 0.35, f'<div class="ring3" style="--c:{cor}"></div>', "pop", b=fim, cls="c pin", snd=None,
                                   extra=f'data-seat="{q}" data-dx="0" data-dy="0"')
        pv = a
        for dsq in [x for x in c.get("destaques") or [] if isinstance(x, dict)]:
            t0 = self.t(dsq.get("em"), pv, a + 1, "destaque")
            pv = t0
            t1 = self.t(dsq.get("ate"), t0, -1) if dsq.get("ate") else None
            t1 = t1 if t1 and t1 > t0 else None
            body += self._destaque(dsq, t0, t1, seat, fx_)
        self.cena(a, b, body, hand=(mid, s_, ox, oy, kf))

    def _destaque(self, dsq: Dict[str, Any], t0: float, t1: Optional[float], seat: Callable[[Any], Optional[int]], fx_: float) -> str:
        est = str(dsq.get("estilo") or "balao")
        alvo = str(dsq.get("alvo") or "")
        tx = _e(dsq.get("texto") or "")
        sub = f'<br><small>{_e(dsq["sub"])}</small>' if dsq.get("sub") else ""
        if est == "tela":  # escurece a mesa e um texto grande no meio
            out = self.E(t0, '<div class="dim"></div>', "fade", b=t1, x=0, y=0, snd=None)
            out += self.E(t0, f'<div class="h" style="font-size:220px;color:var(--ac)">{tx}</div>', "stamp", b=t1, x=960, y=440, cls="c glow", snd="impact")
            if dsq.get("sub"):
                out += self.E(t0 + 1.2, f'<div class="h" style="font-size:66px">{_e(dsq["sub"])}</div>', "up", b=t1, x=960, y=640, cls="c")
            return out
        if est == "flash":
            out = self.E(t0, '<div class="flash"></div>', "fade", b=t0 + 0.6, x=0, y=0, snd=None)
            self.snd.append((round(t0, 3), "riser_hit"))
            return out + self.E(t0, f'<div class="h" style="font-size:230px;color:var(--ac)">{tx}</div>', "stamp", b=t1, x=960, y=210, cls="c glow", snd="impact")
        if est == "carimbo":
            return self.E(t0, f'<div class="h" style="font-size:220px;color:{"#ef4444" if dsq.get("cor") == "vermelho" else "var(--ac)"}">{tx}</div>',
                          "stamp", b=t1, x=960, y=200, cls="c glow", snd="impact")
        if est in ("tag", "aviso", "ok"):
            k_ = {"tag": "gold", "aviso": "red", "ok": "green"}[est]
            html = f'<div class="tag {k_}">{tx}</div>'
        elif est == "anel":
            html = '<div class="ring2"></div>' if alvo == "botao" else '<div class="ring3" style="--c:var(--ac)"></div>'
        elif est == "caixa_board":
            html = '<div class="boardbox"></div>'
        elif est == "contador":  # ♥♥♥♥?  (n símbolos + ?) e o ? acende em "completa_em"
            n = int(dsq.get("n") or 4)
            simb = _e(dsq.get("simbolo") or "♥")
            tc = self.t(dsq.get("completa_em"), t0, -1) if dsq.get("completa_em") else -1
            q = f'<b class="q" data-tcls="ok@{tc:.3f}">?</b>' if tc > 0 else '<b class="q">?</b>'
            html = (f'<div style="display:flex;gap:14px;background:#000c;padding:14px 26px;border-radius:20px;font-family:\'DejaVu Sans\'">'
                    + f'<b style="font-size:70px;color:#ef4444;line-height:1">{simb}</b>' * n
                    + q.replace('class="q"', 'class="q" style="font-size:70px;line-height:1;color:#666"') + "</div>")
            if tc > 0:
                html = html.replace('data-tcls="ok@', 'data-tcls="okq@')
            return self.E(t0, html, "pop", b=t1, x=1560, y=170, cls="c")
        elif est == "selo":
            html = f'<div class="badge b{1 if dsq.get("cor") != "vermelho" else 2}">{tx}' + (f'<small>{_e(dsq["sub"])}</small>' if dsq.get("sub") else "") + "</div>"
        else:
            html = f'<div class="callout">{tx}{sub}</div>'
        fx = "stamp" if est in ("aviso", "ok") else "pop"
        snd = "stamp" if est in ("aviso", "ok") else "pop"
        if alvo.startswith("jogador:"):
            q = seat(alvo.split(":", 1)[1])
            if q is not None:
                dy = "0" if est == "anel" else str(dsq.get("dy", "auto"))
                return self.E(t0, html, fx, b=t1, cls="c pin", snd=snd if est != "anel" else None,
                              extra=f'data-seat="{q}" data-dx="{float(dsq.get("dx") or 0):.0f}" data-dy="{dy}"')
        if alvo == "botao":
            return self.E(t0, html, fx, b=t1, cls="c pin", snd=snd, extra=f'data-btn="1" data-dx="0" data-dy="{0 if est == "anel" else -120}"')
        if alvo == "board":
            return self.E(t0, html, fx, b=t1, cls="c pin", snd=snd, extra=f'data-p="960,451" data-dx="0" data-dy="{0 if est == "caixa_board" else -150}"')
        if alvo == "pote":
            return self.E(t0, html, fx, b=t1, cls="c pin", snd=snd, extra='data-p="960,316" data-dx="0" data-dy="-60"')
        if alvo == "topo":
            return self.E(t0, html, fx, b=t1, x=fx_, y=70, cls="c", snd=snd)
        return self.E(t0, html, fx, b=t1, x=fx_, y=1010, cls="c", snd=snd)

    def _sons_mao(self, ev: List[Dict[str, Any]], kf: List[List[float]]) -> None:
        v0, v1 = kf[0][0], kf[-1][0]
        for x in ev:
            t, tipo, som, off = x["t0"], x["tipo"], None, 0.0
            if tipo == "carta_jogador":
                som, off = "carta", 0.05
            elif tipo == "board":
                som, off = "virar", x["dur"] * 0.35
            elif tipo == "acao" and x["dados"].get("valor", 0) > 0:
                som, off = ("fichas" if "ALL-IN" in str(x["dados"].get("rotulo")) else "ficha"), x["dur"] * 0.55
            elif tipo == "blinds":
                som, off = "ficha", 0.4
            elif tipo == "recolher":
                som, off = "fichas", 0.25
            elif tipo == "showdown":
                som, off = "virar", 0.2
            elif tipo == "vencedor":
                som, off = "vitoria", x["dur"] * 0.4
            if som:
                vt = _inverso(kf, t + off)
                if vt is not None and v0 + 0.2 < vt < v1:
                    self.snd.append((round(vt, 3), som))


def _keyframes(anchors: List[Tuple[float, float]]) -> List[List[float]]:
    """[(vídeo, mão)] → pontos: entre âncoras toca a 1x e segura; se não couber, acelera."""
    pts = [[round(anchors[0][0], 3), round(anchors[0][1], 3)]]
    for (va, pa), (vb, pb) in zip(anchors, anchors[1:]):
        if pb - pa <= vb - va - 0.05:
            pts.append([round(va + (pb - pa), 3), round(pb, 3)])
        pts.append([round(vb, 3), round(pb, 3)])
    return pts


def _inverso(pts: List[List[float]], p: float) -> Optional[float]:
    for (va, pa), (vb, pb) in zip(pts, pts[1:]):
        if pb > pa and pa <= p < pb:
            return va + (p - pa) * (vb - va) / (pb - pa)
    return None


def _ac_texto(hexcor: str) -> str:
    try:
        h = hexcor.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return "#111111" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"
    except (ValueError, IndexError):
        return "#111111"


def construir(p: Dict[str, Any]) -> Construtor:
    segs = p.get("segs") or []
    if not segs:
        raise ExplicadorErro("Falta a legenda (suba o .srt ou 🎙 transcreva a narração).")
    fim = float(p.get("duracao") or 0) or segs[-1][1]
    montado = None
    if p.get("trechos") and p.get("_dir"):
        import explicador_doc as D
        try:
            montado = D.montar_audio(p["_dir"], os.path.join(p["_dir"], p["audio"]), segs, p["trechos"], Tempos)
        except Exception as exc:  # noqa: BLE001
            raise ExplicadorErro(f"não deu pra encaixar os trechos com som original: {exc}")
        segs, fim = montado["segs"], montado["dur"]
    C = Construtor(p, Tempos(segs), round(fim + 0.6, 3))
    if montado:
        C.inseridos, C.audio_montado = montado["inseridos"], montado["wav"]
    C.construir()
    return C


def audio_final(p: Dict[str, Any], base: str) -> str:
    """A narração que o vídeo usa (com os trechos de som original encaixados, se tiver)."""
    if p.get("trechos"):
        import explicador_doc as D
        segs = p.get("segs") or []
        return D.montar_audio(pasta(p["id"], base), caminho_audio(p, base), segs, p["trechos"], Tempos)["wav"]
    return caminho_audio(p, base)


def pagina(p: Dict[str, Any], C: Construtor, fontes: str, previa: bool = False, audio_url: str = "") -> str:
    import poker_render as PR
    op = p["op"]
    ac = op.get("acento") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(op.get("acento") or "")) else "#facc15"
    bg = FUNDOS.get(op.get("fundo") or "verde", FUNDOS["verde"])
    tema = (f":root{{--ac:{ac};--ac-t:{_ac_texto(ac)};--bg1:{bg[0]};--bg2:{bg[1]};--bg3:{bg[2]};--card:{bg[3]}}}")
    doc = op.get("estilo") == "documentario"
    if doc:
        import explicador_doc as D
        tema += D.DOC_CSS.replace("__F__", fontes)
    cfg = {"doc": doc, "SH": [] if doc else sorted({t for t, k in C.snd if k == "impact"}), "CH": C.capitulos if op.get("barra_topo") else [], "CH_END": C.cap_fim, "END": C.END,
           "simbolos": str(op.get("simbolos") or "")[:6], "acento": ac, "previa": previa, "audio_url": audio_url}
    return (open(MOTOR, encoding="utf-8").read().replace("/*FONTES*/", PR._fontes_css(fontes)).replace("/*TEMA*/", tema)
            .replace("__TITULO__", _e(p.get("titulo") or "explicador"))
            .replace("<!--SCENES-->", "\n".join(C.cenas_html)).replace("__BODY__", "doc" if doc else "")
            .replace("/*JSEXTRA*/", __import__("explicador_doc").GRAO_JS if doc else "")
            .replace("/*CFG*/", "const CFG=" + json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/") + ";"))


def pagina_mao(info: Dict[str, Any], fontes: str) -> str:
    import poker_render as PR
    op = PR.normalizar({"tema": info.get("tema") or "verde", "formato": "16:9", "mostrar": info.get("mostrar") or "heroi",
                        "equidade": bool(info.get("equidade")), "posicoes": True, "titulo": False, "zoom": False, "emocoes": False,
                        "sons": False, "estrategia": False})
    return PR.pagina(info["dados"], op, fontes, lambda a: "", "gravar")


def escrever_tela(p: Dict[str, Any], base: str, previa: bool = False, audio_url: str = "", fontes: str = FONTES_ARQ,
                  prog: Callable[[str], None] = lambda _m: None) -> Tuple[str, Construtor]:
    """Escreve <projeto>/tela/index.html + tela/maos/*.html. Devolve (pasta, construtor)."""
    C = construir(p)
    if C.clipes:
        import explicador_doc as D
        D.preparar_clipes(C.clipes, pasta(p["id"], base), prog)
    d = os.path.join(pasta(p["id"], base), "tela_previa" if previa else "tela")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "maos"), exist_ok=True)
    with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
        f.write(pagina(p, C, fontes, previa, audio_url))
    for k, info in C.maos.items():
        with open(os.path.join(d, "maos", f"{k}.html"), "w", encoding="utf-8") as f:
            f.write(pagina_mao(info, fontes))
    return d, C


def resumo(p: Dict[str, Any]) -> Dict[str, Any]:
    """Pra página: a linha do tempo das cenas e os avisos (frases que não achei etc.)."""
    try:
        C = construir(p)
        return {"ok": True, "cenas": C.linha, "avisos": C.avisos[:40], "duracao": C.END, "capitulos": C.capitulos}
    except ExplicadorErro as exc:
        return {"ok": False, "erro": str(exc), "cenas": [], "avisos": []}


# ------------------------------------------------------------------ 🎞 renderizar (Chromium quadro a quadro → H.264, uma cena por arquivo)
def _faixas(C: Construtor, total: int) -> List[Tuple[int, int]]:
    cortes = sorted({0} | {int(round(c["ini"] * FPS)) for c in C.linha if 0 < c["ini"] * FPS < total})
    cortes = [x for i, x in enumerate(cortes) if i == 0 or x - cortes[i - 1] >= FPS]  # cena de menos de 1 s junta na anterior
    return [(a, (cortes[i + 1] if i + 1 < len(cortes) else total)) for i, a in enumerate(cortes)]


def _gravar_faixas(html: str, faixas: List[Tuple[int, int, str]], dsf: int, crf: int, prog: Callable[[int], None],
                   parar: Callable[[], bool]) -> None:
    from playwright.sync_api import sync_playwright
    W, H = 1920 * dsf, 1080 * dsf
    with sync_playwright() as pw:
        nav = pw.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security"])
        try:
            pg = nav.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=dsf)
            pg.goto("file://" + html.replace("\\", "/"))
            pg.wait_for_function("window.pronto === true", timeout=120000)
            cdp = pg.context.new_cdp_session(pg)
            for f0, f1, saida in faixas:
                tmp = saida[:-4] + ".parte.mp4"
                ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
                                       "-vf", f"scale={W}:{H}:flags=lanczos", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                                       "-pix_fmt", "yuv420p", "-r", str(FPS), tmp], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    for i in range(f0, f1):
                        if parar():
                            raise ExplicadorErro("⏹ parado por você")
                        pg.evaluate(f"window.render({i / FPS:.4f})")
                        r = cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 92, "optimizeForSpeed": True})
                        ff.stdin.write(base64.b64decode(r["data"]))
                        prog(1)
                    ff.stdin.close()
                    if ff.wait(timeout=1800) != 0:
                        raise ExplicadorErro("ffmpeg: " + (ff.stderr.read() or b"").decode("utf-8", "replace")[-300:])
                    os.replace(tmp, saida)
                except BaseException:
                    try:
                        ff.kill()
                    except Exception:  # noqa: BLE001
                        pass
                    raise
        finally:
            nav.close()


def renderizar(pid: str, base: str, prog: Callable[[str], None] = lambda _m: None, parar: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
    with _TRAVA:
        p = carregar(pid, base)
    tela, C = escrever_tela(p, base, prog=prog)
    op = p["op"]
    dsf = RESOLUCOES.get(op.get("resolucao") or "2160p", 2)
    total = int(round(C.END * FPS))
    d = os.path.join(pasta(pid, base), "render")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    faixas = [(a, b, os.path.join(d, f"cena_{i:03d}.mp4")) for i, (a, b) in enumerate(_faixas(C, total))]
    n = max(1, min(int(op.get("trabalhadores") or 2), 6, len(faixas)))
    grupos: List[List[Tuple[int, int, str]]] = [[] for _ in range(n)]
    for f in sorted(faixas, key=lambda x: -(x[1] - x[0])):  # as maiores primeiro, no grupo mais leve
        min(grupos, key=lambda g: sum(x[1] - x[0] for x in g)).append(f)
    feitos = [0]
    t_ini = time.time()
    trava = threading.Lock()

    def um(k: int) -> None:
        with trava:
            feitos[0] += k
            if feitos[0] % (FPS * 2) == 0:
                dt = time.time() - t_ini
                fal = (total - feitos[0]) * dt / max(1, feitos[0])
                prog(f"🎞 {feitos[0] // FPS}/{total // FPS} s desenhados · faltam ~{int(fal // 60)} min {int(fal % 60)} s")
    erros: List[BaseException] = []

    def rodar(g: List[Tuple[int, int, str]]) -> None:
        try:
            _gravar_faixas(os.path.join(tela, "index.html"), sorted(g), dsf, 20 if dsf == 2 else 19, um, lambda: parar() or bool(erros))
        except BaseException as exc:  # noqa: BLE001
            erros.append(exc)
    prog(f"🎞 desenhando {len(faixas)} cena(s) em {n} trabalhador(es) — {'4K' if dsf == 2 else '1080p'}")
    ths = [threading.Thread(target=rodar, args=(g,), daemon=True) for g in grupos if g]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    if erros:
        raise erros[0] if isinstance(erros[0], ExplicadorErro) else ExplicadorErro(str(erros[0])[:400])
    prog("🔊 efeitos e música…")
    audios = mixar(p, base, C)
    lista = os.path.join(d, "lista.txt")
    with open(lista, "w", encoding="utf-8") as f:
        for _a, _b, s in faixas:
            f.write(f"file '{os.path.basename(s)}'\n")
    saida_dir = os.path.join(pasta(pid, base), "saida")
    os.makedirs(saida_dir, exist_ok=True)
    video = os.path.join(d, "video.mp4")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", video], capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise ExplicadorErro("ffmpeg (juntar): " + r.stderr[-300:])
    nome = re.sub(r"[^\w\-]+", "_", p["titulo"])[:60].strip("_") or "explicador"
    mp4 = os.path.join(saida_dir, f"{nome}_{'4K' if dsf == 2 else '1080p'}.mp4")
    prog("📦 juntando o áudio…")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-i", audios["final"], "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", mp4], capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise ExplicadorErro("ffmpeg (áudio): " + r.stderr[-300:])
    with _TRAVA:
        p = carregar(pid, base)
        p["saida"] = {"mp4": os.path.basename(mp4), "quando": time.time(), "resolucao": op.get("resolucao"), "dur": C.END,
                      "cenas": [[a / FPS, b / FPS, os.path.basename(s)] for a, b, s in faixas],
                      "voz_sfx": os.path.basename(audios["voz_sfx"]), "musica": os.path.basename(audios["musica"]) if audios.get("musica") else "",
                      "segundos": round(time.time() - t_ini)}
        log(p, f"🎞 renderizado: {os.path.basename(mp4)} ({len(faixas)} cenas, {round(time.time() - t_ini)} s)")
        salvar(p, base)
    return {"mp4": os.path.basename(mp4), "segundos": round(time.time() - t_ini)}


# ------------------------------------------------------------------ 🔊 áudio: narração + efeitos + música (com ducking)
SONS_LIB = {"whoosh": [("variados", f"whoosh_{i}.m4a") for i in (1, 10, 11, 24)], "pop": [("pop", f"pop_{i}.m4a") for i in (1, 11, 14, 17)],
            "impact": [("impacto", "impacto_11.m4a"), ("impacto", "impacto_15.m4a")], "stamp": [("impacto", "impacto_5.m4a")],
            "click": [("pop", "click_mouse_1_down.m4a")], "tick": [("pop", "pop_2.m4a")], "riser_hit": [("impacto", "impacto_subida_1.m4a")],
            "capitulo": [("cinema", "cinema_12.m4a")]}
SONS_DOC = {"whoosh": [("transicoes", "ar_suave.m4a"), ("transicoes", "passagem_curta.m4a")], "impact": [("cinema", "cinema_1.m4a"), ("cinema", "cinema_4.m4a")],
            "stamp": [("cinema", "cinema_2.m4a")], "capitulo": [("cinema", "cinema_12.m4a"), ("cinema", "cinema_6.m4a")], "tick": [("pop", "pop_2.m4a")],
            "riser_hit": [("impacto", "riser_5.m4a")]}
VOL_DOC = {"whoosh": .22, "impact": .35, "stamp": .3, "capitulo": .4, "tick": .18, "riser_hit": .3, "carta": .7, "virar": .7, "ficha": .7,
           "fichas": .6, "vitoria": .6, "deal5": .6}
VOL = {"capitulo": .5, "whoosh": .35, "pop": .45, "impact": .5, "stamp": .45, "click": .7, "tick": .5, "riser_hit": .45, "carta": .9, "virar": .9,
       "ficha": .9, "fichas": .8, "vitoria": .8, "deal5": .8}
SR = 48000


def _ler(cam: str) -> Any:
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", cam, "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"], capture_output=True, timeout=600)
    return np.frombuffer(r.stdout, np.float32).reshape(-1, 2).copy()


def _gravar_wav(x: Any, destino: str, normalizar: bool = False) -> str:
    raw = destino + ".f32"
    x.astype("float32").tofile(raw)
    af = ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"] if normalizar else []
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", raw, *af, "-ar", str(SR), destino],
                   check=True, timeout=900)
    os.remove(raw)
    return destino


def musica_sintetizada(n: int, bpm: float = 96) -> Any:
    """Uma trilha leve (Am-F-C-G): pad, baixo, bumbo, chimbal e arpejo — só pra não ficar seco."""
    import numpy as np
    t = np.arange(n) / SR
    beat = 60 / bpm
    bar = 4 * beat

    def nota(m: float) -> float:
        return 440 * 2 ** ((m - 69) / 12)
    prog_ = [[57, 60, 64], [53, 57, 60], [48, 55, 60], [55, 59, 62]]
    ci = ((t // bar).astype(int)) % 4
    pad = np.zeros(n)
    for v in range(3):
        f = np.array([nota(prog_[c][v]) for c in range(4)])[ci]
        ph, ph2 = np.cumsum(2 * np.pi * f / SR), np.cumsum(2 * np.pi * f * 1.004 / SR)
        pad += np.sin(ph) + 0.6 * np.sin(ph2) + 0.15 * np.sin(2 * ph)
    lb = (t % bar) / bar
    mus = 0.05 * pad * (0.5 + 0.5 * np.minimum(1, lb * 6) * (1 - 0.3 * lb))
    fb = np.array([nota(prog_[c][0] - 12) for c in range(4)])[ci]
    mus += 0.12 * np.sin(np.cumsum(2 * np.pi * fb / SR)) * np.exp(-((t % beat) / beat) * 3)
    kt = t % beat
    mus += 0.35 * np.sin(2 * np.pi * (50 * kt + 60 * (1 - np.exp(-kt * 30)) / 30)) * np.exp(-kt * 14)
    ruido = np.random.default_rng(1).standard_normal(n)
    mus += 0.05 * np.diff(ruido, prepend=0) * np.exp(-((t + beat / 2) % beat) * 60)
    e8 = beat / 2
    arp = np.array([prog_[c][i % 3] + 12 for c in range(4) for i in range(8)])
    fa = np.array([nota(x) for x in arp])[ci * 8 + ((t // e8).astype(int) % 8)]
    mus += 0.06 * np.sin(np.cumsum(2 * np.pi * fa / SR)) * np.exp(-(t % e8) * 9)
    return mus.astype("float32")


def mixar(p: Dict[str, Any], base: str, C: Construtor) -> Dict[str, str]:
    """→ voz_sfx.wav (narração + efeitos), musica.wav (com ducking) e final.wav (tudo, -14 LUFS)."""
    import numpy as np
    import poker_render as PR
    d = os.path.join(pasta(p["id"], base), "render")
    os.makedirs(d, exist_ok=True)
    op = p["op"]
    nar = _ler(C.audio_montado or caminho_audio(p, base))
    doc = op.get("estilo") == "documentario"
    N = int(C.END * SR) + SR
    sfx = np.zeros((N, 2), np.float32)
    if op.get("sfx", True):
        cache: Dict[str, Any] = {}

        def som(k: str, i: int) -> Any:
            if k in ("carta", "virar", "ficha", "fichas", "vitoria"):
                ch = k
                if ch not in cache:
                    cache[ch] = _ler(PR._som(k, os.path.join(d, f"_som_{k}.wav")))
                return cache[ch]
            lib = (SONS_DOC.get(k) if doc and k in SONS_DOC else SONS_LIB.get(k)) or []
            if not lib:
                return None
            sub, arq = lib[i % len(lib)]
            cam = os.path.join(SONS, sub, arq)
            if cam not in cache:
                cache[cam] = _ler(cam) if os.path.isfile(cam) else None
            return cache[cam]
        cont: Dict[str, int] = {}
        for t, k in sorted(C.snd):
            if k == "deal5":
                x = som("carta", 0)
                for j in range(5):
                    _somar(sfx, x, t + j * 0.07, VOL[k])
                continue
            if doc and k in ("pop", "click"):
                continue
            x = som(k, cont.get(k, 0))
            cont[k] = cont.get(k, 0) + 1
            _somar(sfx, x, t, (VOL_DOC if doc else VOL).get(k, 0.5))
    voz = sfx.copy()
    n = min(len(nar), N)
    voz[:n] += nar[:n]
    musica = None
    modo = op.get("musica") or "sintetizada"
    if modo == "sintetizada":
        if doc:  # a trilha se repete a cada 4 compassos: sintetiza um ciclo e repete (vídeo de 20 min estourava a memória)
            import explicador_doc as D
            ciclo = D.musica_doc(int(round(4 * 4 * 60 / 66 * SR)))
        else:
            ciclo = musica_sintetizada(int(round(4 * 4 * 60 / 96 * SR)))
        f = min(240, len(ciclo) // 4)
        ciclo[:f] *= np.linspace(0, 1, f, dtype=np.float32)
        ciclo[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
        mus = np.tile(ciclo, int(math.ceil(N / len(ciclo))))[:N]
        musica = np.stack([mus, mus], axis=1)
        del mus
    elif modo == "arquivo" and p.get("musica_arquivo"):
        cam = os.path.join(pasta(p["id"], base), p["musica_arquivo"])
        if os.path.isfile(cam):
            m = _ler(cam)
            if len(m):
                rep = int(math.ceil(N / len(m)))
                musica = np.tile(m, (rep, 1))[:N] * 0.6
    res = {"voz_sfx": _gravar_wav(np.clip(voz, -1, 1), os.path.join(d, "voz_sfx.wav"))}
    final = voz.copy()
    if musica is not None:
        env = np.sqrt(np.maximum(_media_movel(nar[:, 0].astype(np.float64) ** 2, 2400), 0))
        env = np.pad(env, (0, max(0, N - len(env))))[:N]
        duck = _media_movel(np.clip(env / 0.03, 0, 1), 9600)
        t = np.arange(N) / SR
        g = (1 - 0.45 * duck) * np.clip(t / 1.5, 0, 1) * np.clip((C.END - t) / 3, 0, 1) * float(op.get("volume_musica") or 0.32)
        musica = (musica * g[:, None]).astype(np.float32)
        res["musica"] = _gravar_wav(np.clip(musica, -1, 1), os.path.join(d, "musica.wav"))
        final += musica
    res["final"] = _gravar_wav(np.clip(final, -1, 1), os.path.join(d, "final.wav"), normalizar=True)
    return res


def _media_movel(x: Any, k: int) -> Any:
    """Média móvel centrada em O(n) (np.convolve com janela grande levava minutos num vídeo de 20 min)."""
    import numpy as np
    c = np.cumsum(np.concatenate([[0.0], x]))
    h = k // 2
    i0 = np.clip(np.arange(len(x)) - h, 0, len(x))
    i1 = np.clip(np.arange(len(x)) + h + 1, 0, len(x))
    return ((c[i1] - c[i0]) / np.maximum(1, i1 - i0)).astype(np.float32)


def _somar(dst: Any, x: Any, t: float, v: float) -> None:
    if x is None or not len(x):
        return
    i = int(t * SR)
    if i < 0 or i >= len(dst):
        return
    n = min(len(x), len(dst) - i)
    dst[i:i + n] += x[:n] * v


# ------------------------------------------------------------------ 🎬 pro editor
def montar_editor(p: Dict[str, Any], base: str, job_dir: str) -> Dict[str, Any]:
    """Uma cena renderizada por trecho (vídeo), a narração + efeitos como áudio e a música separada (dá pra trocar no editor)."""
    s = p.get("saida") or {}
    rd = os.path.join(pasta(p["id"], base), "render")
    if not s.get("cenas") or not all(os.path.isfile(os.path.join(rd, c[2])) for c in s["cenas"]):
        raise ExplicadorErro("Renderize primeiro (🎞 Renderizar) — o editor recebe as cenas prontas.")
    mid = os.path.join(job_dir, "explicador")
    os.makedirs(mid, exist_ok=True)
    segs = []
    for k, (a, b, arq) in enumerate(s["cenas"]):
        dst = os.path.join(mid, arq)
        shutil.copyfile(os.path.join(rd, arq), dst)
        segs.append({"start": round(a, 3), "end": round(b, 3), "provider": "material", "query": f"🎬 cena {k + 1}"[:150],
                     "on_screen_text": None, "media_type": "video", "zoom_direction": "static", "efeito": None,
                     "override_source": {"source": "local_file", "value": dst, "kind": "video"}})
    audio = os.path.join(job_dir, "narracao.wav")
    shutil.copyfile(os.path.join(rd, s["voz_sfx"]), audio)
    musica = None
    if s.get("musica") and os.path.isfile(os.path.join(rd, s["musica"])):
        musica = os.path.join(job_dir, "musica.wav")
        shutil.copyfile(os.path.join(rd, s["musica"]), musica)
    return {"segmentos": segs, "audio": audio, "musica": musica, "duracao": float(s.get("dur") or segs[-1]["end"]),
            "qualidade": s.get("resolucao") or "1080p"}


# ------------------------------------------------------------------ 🤖 o plano com a IA
TIPOS_DOC = r"""
TIPOS DE CENA (campo "tipo"). Toda cena tem "de" = a FRASE EXATA da narração onde ela começa (copie 3–8 palavras
seguidas da transcrição, sem mudar nada). Campo opcional "capitulo" (nome curto, MAIÚSCULAS) marca a
seção (a barra de progresso no topo só aparece se o usuário ligar nas opções); "fim_capitulos": true na cena final (outro) esconde a barra. Todo "em" é também uma frase exata da narração (o
momento em que aquilo aparece). Textos na tela CURTOS (2–6 palavras), em MAIÚSCULAS, na língua da narração.

LINHAS (usadas por vários tipos): [{"texto","estilo","em","cor"?,"substitui"?,"ate"?,"lado"?,"girado"?,"sub"?,"num"?,"pos"?}]
  estilo: titulo (enorme, cor do acento) · grande · medio · pequeno · tag (etiqueta) · aviso (etiqueta vermelha carimbada)
          · ok (verde carimbada) · carimbo (palavra gigante carimbada) · nota · relogio ("texto":"6:00","sub":"MINUTES" — conta regressiva; SÓ quando o vídeo é sobre tempo/duração, ex. "em 6 minutos")
          · numero ("texto":"52","sub":"CARDS") · marca (logo do canal) · caixa (cartão com "num" e "texto"/"sub"; use "lado":"esq"/"dir" pra 2 lado a lado)
          · caso ("texto":"2010 · WPT BARCELONA" — selo com o ano/data + o lugar/evento, pra abrir um caso real)
          · contagem ("texto":"$22,000,000","sub":"PAID BACK" — o número sobe de 0 até o valor; aceita $ € + e vírgulas)
  substitui: true → ocupa o lugar da linha anterior (troca). ate: frase em que some. cor: acento|branco|vermelho|verde.
  destaca_em (só caixa): frase em que a caixa fica vermelha/acesa.

QUALQUER cena aceita "tecnica":{"n":1,"nome":"COLLUSION","icone":"usuarios","em":"Technique number one","rotulo"?:"TECHNIQUE"} →
  cabeçalho grande numerado (vídeos de lista/top N: "number one…"), que depois vira uma etiqueta no canto.

1. texto — {"linhas":[...], "cartas_topo":["As","Kh","Qd","Jc","Ts"]?}  textos cinéticos (abertura, frases de impacto, regras).
2. marca — {"em","like"?: frase do pedido de like, "inscrever"?: frase do inscreva-se, "logo"?: true/false, "linhas"?}
   logo do canal + botão LIKE/SUBSCRIBE com o cursor clicando. Sem logo e só like = botão grande no meio.
3. icones — {"linhas"?, "itens":[{"icone","texto","em"}] (até 4)}  ícones: tv cassino online trofeu bandeira escudo relogio
   check x dinheiro cerebro alvo estrela usuarios grafico cartas fichas lampada aviso olho robo mascara celular embaralhador
   balanca camera martelo lupa sinal grades raiox cadeado manga
4. fichas — {"em","rotulo"?:"THE POT","rotulo_em"?,"encolhe"?: frase (a pilha diminui e sobe), "linhas" (pos "topo" ou "base")}
5. cartas — {"titulo"?, "passos":[{"cartas":["Ah","Kh"],"em","destaque":[0,1]?,"um_a_um"?:true,"rotulo"?,"estilo_rotulo"?}], "linhas"?}
   uma fileira de cartas que vira a cada passo (cartas: rank 2-9 T J Q K A + naipe s h d c; "??" = carta virada).
6. escada — {"linhas"? (intro antes do 1º item), "itens":[{"nome","desc","cartas"?,"destaque"?,"em","brilho"?,"nota"?,"nota_em"?}],
   "rotulos"?:["STRONGEST ▲","WEAKEST ▼"]}  ranking que sobe degrau por degrau. Pro poker Texas Hold'em use "chave" em vez de
   nome/desc/cartas: high pair twopair trips straight flush full quads sf royal (ex.: {"chave":"pair","em":"One pair."}).
7. comparacao — {"linhas" (pos topo|base), "esquerda":{"cartas":[..]} ou {"texto"}, "direita":{...}, "vs"?:"VS", "em",
   "vence":"esquerda"|"direita"|"empate", "resultado_em", "rotulo_vence"?, "dividir"?:{"em","texto","texto_em"} (fichas se dividem)}
8. lista — {"titulo","estilo":"check"|"numerada","itens":[{"texto","sub"?,"em"}], "caixa"?:{"titulo","linhas":[..],"em"},
   "barra"?:{"texto","em"}}  checklist/recapitulação.
9. dicas — {"titulo"?:"4 QUICK TIPS", "itens":[{"titulo","texto","em","cartas"?:[..],"riscadas"?:true,"pares"?:true,"icone"?,
   "selo"?:{"texto","em","cor"}}]}  um cartão grande por dica.
11. foto — {"fotos":[{"arquivo","em"?,"efeito"?:"zoom_in|zoom_out|pan_dir|pan_esq|pan_cima","foco"?:[x,y],"pb"?,"rotulo"?:"LUGAR · DATA"}],"linhas"?}
   (Ken Burns; foto que não é 16:9 ganha fundo desfocado; "rotulo" = plaquinha embaixo à esquerda). Os arquivos estão em 📁 Fotos e vídeos.
12. video — {"cortes":[{"arquivo","ini": segundo no vídeo original,"em"?,"zoom"?,"foco"?,"velocidade"?,"enquadrar"?:"moldura|cheia","pb"?,"rotulo"?}],
   "selo"?:"ARCHIVAL FOOTAGE","destaques"?} — vídeo de arquivo SEM o som (a narração fala por cima); bordas pretas saem sozinhas.
   {"trecho": n} = mostra a imagem do trecho com som original nº n (a lista "trechos" corta a narração e põe o som da época).
13. capitulo — {"numero":"CHAPTER ONE","titulo","sub"?,"arquivo"? (foto de fundo escurecida)}
14. citacao — {"texto": a fala REAL (entre aspas no vídeo),"autor","arquivo"?}
15. linha_tempo — {"titulo"?,"itens":[{"ano","texto","em"}]}
ESTILO "documentario" (opção): serifas, grão de filme, cor quente, transições calmas, trilha lenta — use capitulo/foto/video/citacao.

10. mao — uma mão de poker no simulador 2D: {"titulo"?, "dsl": "...", "mostrar":"heroi"|"todas", "equidade"?:bool,
   "comeca"?:{evento}, "ancoras":[{"em", "evento":{...}}], "painel"?:{"itens":[{"texto","sub","em","jogador"?,"cor"?}]},
   "destaques":[{"em","ate"?,"texto","sub"?,"alvo","estilo"}]}
   DSL da mão: linhas "mesa: blinds=0.5/1 unidade=bb" · "jogador: Nome 100 As Kd heroi" (um por jogador; o herói é você)
   · "botao: Nome" · "preflop: Ana call; Ben raise 3; You fold" · "flop: Jd 8h 3s | Eva check; You bet 4" · "turn: 2h | …"
   · "river: Kd | …". Ações: check bet raise call fold allin (bet/raise com valor). Ordem dos jogadores = sentido do jogo.
   evento: {"tipo":"inicio"|"distribuir"|"blinds"|"flop"|"turn"|"river"|"showdown"|"vencedor"|"final"} ou
           {"tipo":"acao","quem":"Nome","acao":"raise","n":0} — a mão anda sozinha a 1x entre as âncoras e espera na próxima.
   alvo dos destaques: "jogador:Nome" | "botao" | "board" | "pote" | "topo" | "rodape".
   estilo: balao · tag · aviso · ok · anel · caixa_board · selo · carimbo (palavra grande no alto) · flash (clarão + palavra)
           · tela (escurece a mesa + palavra gigante; "sub" embaixo) · contador ({"n":4,"simbolo":"♥","completa_em": frase})
"""

SISTEMA_IA = ("Você é diretor de motion graphics de vídeos explicativos do YouTube (ritmo rápido, muita informação visual, "
              "estilo 'dopamina' mas didático). Recebe a narração com os segundos e devolve SÓ um JSON {\"cenas\":[...]} "
              "seguindo o catálogo. Regras: uma cena a cada 6–30 s, troque de cena quando o assunto muda; algo novo na tela "
              "a cada 2–4 s; textos curtos; nunca escreva a legenda/transcrição inteira na tela (o vídeo NÃO tem legenda); "
              "toda frase de 'de'/'em' tem que existir IGUAL na transcrição (copie); use 'mao' com o simulador quando "
              "exemplificar jogadas de poker; abertura com texto + marca/like se o narrador pedir like; feche com marca + "
              "like/inscrever. Não invente dados nem números que o narrador não disse.\n" + TIPOS_DOC)


def plano_ia(pid: str, base: str, instrucoes: str = "", chamar: Optional[Callable[..., Any]] = None,
             prog: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    with _TRAVA:
        p = carregar(pid, base)
    if not p.get("segs"):
        raise ExplicadorErro("Falta a legenda (suba o .srt ou 🎙 transcreva).")
    import json_ia
    if chamar is None:
        import ia_servico
        chamar = ia_servico.chamar
    op = p["op"]
    conteudo = (f"TÍTULO: {p['titulo']}\nCANAL: {op.get('marca1', '')} {op.get('marca2', '')}\nDURAÇÃO: {p.get('duracao', 0):.0f} s\n"
                + (f"INSTRUÇÕES DO USUÁRIO: {instrucoes.strip()[:2000]}\n" if instrucoes.strip() else "")
                + "\nNARRAÇÃO (com o segundo de início de cada frase):\n" + transcricao_com_tempos(p["segs"]))
    prog("🤖 a IA está montando o plano das cenas…")
    r = chamar("explicador", SISTEMA_IA, conteudo, max_tokens=24000, timeout=400, job=pid, effort="medium")
    if r is None:
        raise ExplicadorErro("A IA não respondeu (🤖 ligue a IA e o recurso “Explicador animado” nas configurações).")
    try:
        plano = r if isinstance(r, dict) else json_ia.carregar(str(r), aceitar_cortado=True)
    except Exception as exc:  # noqa: BLE001
        raise ExplicadorErro(f"A IA devolveu um JSON quebrado: {exc}")
    if isinstance(plano, list):
        plano = {"cenas": plano}
    if not isinstance(plano, dict) or not isinstance(plano.get("cenas"), list) or not plano["cenas"]:
        raise ExplicadorErro("A IA não devolveu cenas.")
    with _TRAVA:
        p = carregar(pid, base)
        p["plano"] = {"cenas": plano["cenas"]}
        log(p, f"🤖 plano da IA: {len(plano['cenas'])} cenas")
        salvar(p, base)
    return {**resumo(p), "n_cenas": len(plano["cenas"])}


def plano_simples(p: Dict[str, Any]) -> Dict[str, Any]:
    """Sem IA: uma cena de texto por parágrafo (frase de ~4 palavras como título) + marca no fim. Ponto de partida."""
    segs = p.get("segs") or []
    frases, cur = [], []
    for a, b, t in segs:
        cur.append(str(t))
        if re.search(r"[.!?]$", str(t).strip()):
            frases.append(" ".join(cur))
            cur = []
    if cur:
        frases.append(" ".join(cur))
    cenas: List[Dict[str, Any]] = []
    for i in range(0, len(frases), 3):
        bloco = frases[i:i + 3]
        de = " ".join(bloco[0].split()[:6])
        linhas = [{"texto": " ".join(f.split()[:4]).upper().strip(".,!?"), "estilo": "grande" if j == 0 else "tag",
                   "em": " ".join(f.split()[:5])} for j, f in enumerate(bloco)]
        cenas.append({"tipo": "texto", "de": de, "linhas": linhas})
    if cenas:
        cenas[0]["linhas"][0]["estilo"] = "titulo"
    return {"cenas": cenas}


import explicador_doc as _doc  # noqa: E402  🎞 cenas de documentário (foto, vídeo de arquivo, capítulo, citação, linha do tempo)
_doc.instalar(Construtor, None)
