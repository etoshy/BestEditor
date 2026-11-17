"""
📊 v84_403 — o jeito de escrever dos canais que estão bombando, pra usar nos roteiros do SEU canal.

Você cola o link de 3 a 5 canais do mesmo nicho → o site lista os shorts de cada um, pega os ~20 MAIS VISTOS, puxa a
legenda (a do YouTube, pelo yt-dlp; sem legenda, o Whisper ouve o áudio) e a IA escreve o "manual de escrita" deles:
como abrem, o ritmo, o tamanho, as viradas, como fecham, o tom. O roteiro do canal passa a seguir a TÉCNICA (nunca
copia frase).

Fica no canal: canal["estilo_concorrentes"] = {"canais": [...], "manual": "...", "quando", "n_transcricoes", "exemplos"}.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional

MAX_CANAIS = 5
POR_CANAL = 20


def url_shorts(url: str) -> str:
    """https://www.youtube.com/@canal → …/@canal/shorts (a aba de shorts, onde dá pra ordenar pelos vistos)."""
    u = str(url or "").strip().split("?")[0].rstrip("/")
    if not re.match(r"https?://(www\.|m\.)?youtube\.com/", u):
        raise ValueError(f"Link de canal do YouTube inválido: {url}")
    u = re.sub(r"/(videos|streams|featured|shorts|playlists|community)$", "", u)
    return u + "/shorts"


def _yt_dlp(args: List[str], timeout: float = 240.0) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "yt_dlp", "--no-warnings"] + args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def listar_shorts(url_canal: str, n: int = POR_CANAL, rodar: Callable[..., Any] = _yt_dlp) -> List[Dict[str, Any]]:
    """Os shorts do canal (até 300 mais recentes) → os `n` mais vistos: [{id, titulo, views, url}]."""
    r = rodar(["--flat-playlist", "--dump-single-json", "--playlist-end", "300", url_shorts(url_canal)])
    try:
        d = json.loads(r.stdout or "{}")
    except ValueError:
        d = {}
    itens = []
    for e in d.get("entries") or []:
        vid = e.get("id")
        if not vid:
            continue
        itens.append({"id": vid, "titulo": str(e.get("title") or "")[:150], "views": int(e.get("view_count") or 0),
                      "url": e.get("url") or f"https://www.youtube.com/shorts/{vid}"})
    itens.sort(key=lambda x: -x["views"])  # sem contagem (raro): fica a ordem do canal
    return itens[:n]


def texto_do_vtt(vtt: str) -> str:
    """Legenda .vtt (a automática repete cada linha 2-3 vezes, rolando) → texto corrido sem repetição."""
    linhas: List[str] = []
    for l in (vtt or "").splitlines():
        l = l.strip()
        if not l or l.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or "-->" in l or re.fullmatch(r"\d+", l):
            continue
        l = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", l)).strip()
        if not l:
            continue
        cauda = " ".join(linhas[-3:])
        if cauda.endswith(l):  # a legenda automática repete o que já rolou
            continue
        if linhas and l.startswith(linhas[-1]):  # a mesma linha, só que maior
            linhas[-1] = l
        else:
            linhas.append(l)
    t = " ".join(linhas)
    return re.sub(r"\s+", " ", t).strip()


def transcricao(video_url: str, pasta: str, rodar: Callable[..., Any] = _yt_dlp,
                transcrever: Optional[Callable[..., Any]] = None) -> str:
    """A legenda do short (manual ou automática; en/pt/es) — sem legenda e com o Whisper: baixa só o áudio e transcreve."""
    os.makedirs(pasta, exist_ok=True)
    antes = set(os.listdir(pasta))
    rodar(["--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", "en.*,pt.*,es.*", "--sub-format", "vtt",
           "-o", os.path.join(pasta, "%(id)s.%(ext)s"), video_url], 120)
    novos = sorted(f for f in set(os.listdir(pasta)) - antes if f.endswith(".vtt"))
    if novos:
        prefer = next((f for f in novos if ".en" in f and "orig" in f), None) or next((f for f in novos if ".en" in f), None) or novos[0]
        with open(os.path.join(pasta, prefer), encoding="utf-8", errors="replace") as f:
            t = texto_do_vtt(f.read())
        if t:
            return t
    if transcrever is None:
        return ""
    rodar(["-x", "--audio-format", "mp3", "-o", os.path.join(pasta, "audio_%(id)s.%(ext)s"), video_url], 240)
    aud = next((os.path.join(pasta, f) for f in sorted(set(os.listdir(pasta)) - antes) if f.startswith("audio_")), None)
    if not aud:
        return ""
    segs = transcrever(aud, language=None, word_timestamps=False, info={})
    return " ".join(str(s.get("text") or "").strip() for s in segs or []).strip()


SISTEMA = """Você analisa roteiros de SHORTS que viralizaram (transcrições dos vídeos mais vistos de canais do mesmo nicho)
e escreve um MANUAL DE ESCRITA pra outro canal usar a mesma TÉCNICA — sem copiar frases, ideias específicas nem bordões.

Escreva em português, direto, em tópicos curtos:
1. ABERTURA: como as primeiras 1-2 frases prendem (tipos de gancho, tamanho em palavras, o que vem primeiro). Dê 5 MOLDES
   genéricos com <lacunas> (ex.: "Este <pessoa> fez <ação comum> — mas <detalhe inesperado>.").
2. ESTRUTURA: o caminho típico do começo ao fim (quantas viradas, onde fica a revelação, como o meio segura).
3. RITMO: frases curtas ou longas, palavras por segundo aproximadas, uso de pausa, quantas frases no total.
4. VOZ: pessoa (eu/você/ele), tom (sério, irônico, maravilhado…), gírias, humor, nível de detalhe.
5. FECHAMENTO: como terminam (pergunta, opinião, chamada pra comentar, loop) — 3 moldes genéricos.
6. O QUE ELES EVITAM e O QUE REPETEM (padrões que mais aparecem nos vídeos com mais views).
7. 3 erros que fariam um roteiro parecer CÓPIA ou molde (pra não cair neles).
Baseie tudo no que está nos textos; não invente. Até ~2500 caracteres."""

SCHEMA = {"type": "object", "properties": {"manual": {"type": "string"}}, "required": ["manual"], "additionalProperties": False}


def analisar(amostras: List[Dict[str, Any]], chamar: Optional[Callable[..., Any]] = None, rotulo: str = "") -> str:
    """amostras = [{canal, titulo, views, texto}] → o manual (texto)."""
    if chamar is None:
        import ia_servico
        chamar = ia_servico.chamar
    boas = [a for a in amostras if len(str(a.get("texto") or "")) > 40]
    if len(boas) < 3:
        raise ValueError("Poucas transcrições (menos de 3) — confira os links dos canais.")
    L = []
    for a in sorted(boas, key=lambda a: -int(a.get("views") or 0))[:100]:
        L.append(f"### {a.get('canal') or ''} · {int(a.get('views') or 0):,} views · {a.get('titulo') or ''}\n{str(a['texto'])[:1500]}")
    r = chamar("curtos", SISTEMA, "\n\n".join(L)[:120000], schema=SCHEMA, max_tokens=3000, effort="medium", timeout=300,
               job=rotulo or None)
    manual = str((r or {}).get("manual") or "").strip() if isinstance(r, dict) else ""
    if not manual:
        raise RuntimeError("A IA não respondeu (veja as últimas chamadas em 🤖 IA).")
    return manual[:4000]


def aprender(canais: List[str], pasta: str, prog: Callable[[str], None] = lambda s: None, n: int = POR_CANAL,
             rodar: Callable[..., Any] = _yt_dlp, transcrever: Optional[Callable[..., Any]] = None,
             chamar: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """O caminho todo: lista → legendas → manual. Devolve o que vai pro canal."""
    canais = [c for c in dict.fromkeys(str(x).strip() for x in canais or []) if c][:MAX_CANAIS]
    if not canais:
        raise ValueError("Cole o link de pelo menos 1 canal do YouTube (o ideal é 3 a 5).")
    amostras: List[Dict[str, Any]] = []
    for k, c in enumerate(canais, 1):
        prog(f"📊 canal {k}/{len(canais)}: listando os shorts mais vistos…")
        try:
            shorts = listar_shorts(c, n, rodar)
        except ValueError as exc:
            prog(f"⚠ {exc}")
            continue
        for j, s in enumerate(shorts, 1):
            prog(f"📝 canal {k}/{len(canais)} · short {j}/{len(shorts)}: {s['titulo'][:60]}")
            try:
                t = transcricao(s["url"], os.path.join(pasta, f"c{k}"), rodar, transcrever)
            except Exception:  # noqa: BLE001 — um short sem legenda não para os outros
                t = ""
            if t:
                amostras.append({"canal": c, "titulo": s["titulo"], "views": s["views"], "texto": t})
    prog(f"🤖 a IA está lendo {len(amostras)} transcrições…")
    manual = analisar(amostras, chamar)
    return {"canais": canais, "manual": manual, "quando": time.time(), "n_transcricoes": len(amostras),
            "exemplos": [{"titulo": a["titulo"], "views": a["views"], "canal": a["canal"]} for a in
                         sorted(amostras, key=lambda a: -a["views"])[:10]]}


def bloco_roteiro(canal: Dict[str, Any]) -> str:
    """O que entra no prompt do roteiro do canal."""
    e = (canal or {}).get("estilo_concorrentes") or {}
    if not e.get("manual") or e.get("desligado"):
        return ""
    return ("## WRITING STYLE THAT WORKS IN THIS NICHE (learned from the most-viewed shorts of top channels — follow the "
            "TECHNIQUE: hook shapes, rhythm, structure, tone. NEVER copy their lines, ideas or catchphrases; this video's facts "
            "and wording are its own; the rules above still win)\n" + e["manual"])


def pasta_tmp() -> str:
    return tempfile.mkdtemp(prefix="estilo_conc_")
