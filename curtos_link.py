"""curtos_link.py — 🔗 Link → vídeo pronto (v84_286).

Cola o link (TikTok, Shorts, Reels, Kwai…) e espera: o site baixa o vídeo, lê os COMENTÁRIOS e a descrição (yt-dlp),
a IA olha o vídeo e entende o que acontece, escreve o roteiro (no idioma do post — inglês com as tags de voz do
Chatterbox por padrão — + português, ganchos, finais com pergunta e títulos), gera a narração, alinha, põe os destaques,
monta no editor e EXPORTA o MP4. Usa o curto de 💬 comentário por baixo — dá pra abrir e ajustar qualquer passo depois.

Modo do roteiro:
  auto       — a IA escolhe o que rende mais pra esse clipe
  comentario — narrador comenta/opina (gancho no momento mais forte → a história → final + pergunta)
  explicar   — narrador EXPLICA o que está acontecendo (o como/por quê: a técnica, a regra, a física, o comportamento)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import Any, Dict, List

MODOS = {
    "auto": "🤖 a IA escolhe",
    "comentario": "💬 comentar (opinião, reviravolta, pergunta polêmica)",
    "explicar": "🔍 explicar o que está acontecendo",
}
REGRA_MODO = {
    "auto": ("APPROACH: choose what makes THIS clip perform best — COMMENTARY (retell + the narrator's opinion, the twist, a "
             "question people argue about) or EXPLAIN (tell viewers HOW/WHY what they see happens: the technique, the rule, the "
             "physics, the animal behavior, the trick — step by step in sync with the clip, ending with the most surprising detail "
             "+ a question). Prefer EXPLAIN when the comments are full of 'how?'/'why?' questions or the clip shows a skill/trick/"
             "phenomenon; prefer COMMENTARY when people argue about a decision or a reaction. Start 'descricao' with "
             "'[COMMENTARY]' or '[EXPLAIN]'."),
    "comentario": ("APPROACH: COMMENTARY — retell what happens with the narrator's own opinion, the twist nobody noticed, and end "
                   "with the question people argue about."),
    "explicar": ("APPROACH: EXPLAIN WHAT IS HAPPENING — tell viewers HOW/WHY what they see happens (the technique, the rule, the "
                 "physics, the animal behavior, the trick), step by step and in sync with the clip; the hook is the curious "
                 "question ('How did he…?' / 'Why does this…?'); end with the most surprising detail + a question. Only "
                 "well-established facts; if the reason is not clear from the clip and comments, say what it most likely is."),
}


def regra_modo(modo: str) -> str:
    return REGRA_MODO.get(modo, REGRA_MODO["auto"])


def modo_escolhido(descricao: str, pedido: str) -> str:
    """O modo que a IA usou (no auto ela marca [COMMENTARY]/[EXPLAIN] no começo da descrição)."""
    if pedido in ("comentario", "explicar"):
        return pedido
    d = str(descricao or "").upper()
    return "explicar" if "[EXPLAIN]" in d else "comentario" if "[COMMENTARY]" in d else ""


def limpar_marca(descricao: str) -> str:
    return re.sub(r"^\s*\[(COMMENTARY|EXPLAIN)\]\s*", "", str(descricao or ""))


# ---------------------------------------------------------------------------------------------------- comentários
def _fmt_n(v: Any) -> str:
    try:
        v = int(v)
    except (TypeError, ValueError):
        return "?"
    return f"{v / 1e6:.1f}M" if v >= 1e6 else f"{v / 1e3:.1f}K" if v >= 1e3 else str(v)


def ler_info_ytdlp(j: Dict[str, Any], n: int = 60) -> Dict[str, Any]:
    """JSON do yt-dlp → descrição, números e os comentários principais (só os de 1º nível, os mais curtidos)."""
    coms = []
    vistos = set()
    for c in j.get("comments") or []:
        if not isinstance(c, dict) or (c.get("parent") not in (None, "root")):
            continue
        t = " ".join(str(c.get("text") or "").split())
        if len(t) < 2 or t.lower()[:80] in vistos:
            continue
        vistos.add(t.lower()[:80])
        coms.append({"texto": t[:400], "curtidas": int(c.get("like_count") or 0), "autor": str(c.get("author") or "")[:40]})
    coms.sort(key=lambda c: -c["curtidas"])
    return {"titulo": str(j.get("title") or "")[:300], "descricao": str(j.get("description") or "")[:1500],
            "autor": str(j.get("uploader") or j.get("channel") or j.get("uploader_id") or "")[:80],
            "views": j.get("view_count"), "curtidas": j.get("like_count"), "n_comentarios": j.get("comment_count"),
            "duracao": j.get("duration"), "comentarios": coms[:n]}


def baixar_info(url: str, n: int = 60, timeout: float = 90.0) -> Dict[str, Any]:
    """yt-dlp sem baixar o vídeo: a descrição, os números e os comentários. Demorou/falhou → volta vazio (o vídeo segue)."""
    cmd = [sys.executable, "-m", "yt_dlp", "--skip-download", "--dump-single-json", "--no-warnings", "--write-comments",
           "--extractor-args", f"youtube:max_comments={max(20, n * 2)},all,0,0;comment_sort=top", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            return dict(ler_info_ytdlp(json.loads(r.stdout), n), ok=True)
        erro = (r.stderr or "").strip().splitlines()[-1:] or ["sem resposta"]
        return {"comentarios": [], "ok": False, "erro": erro[0][:200]}
    except subprocess.TimeoutExpired:
        # TikTok com muitos comentários demora: tenta de novo SEM os comentários (pelo menos a descrição e os números)
        try:
            r = subprocess.run([c for c in cmd if c != "--write-comments"], capture_output=True, text=True, timeout=45,
                               encoding="utf-8", errors="replace")
            if r.returncode == 0 and r.stdout.strip():
                return dict(ler_info_ytdlp(json.loads(r.stdout), n), ok=True, erro="os comentários demoraram demais — cole os principais à mão")
        except (subprocess.TimeoutExpired, ValueError, OSError):
            pass
        return {"comentarios": [], "ok": False, "erro": "demorou demais"}
    except (ValueError, OSError) as exc:
        return {"comentarios": [], "ok": False, "erro": str(exc)[:200]}


def comentarios_colados(texto: str) -> List[Dict[str, Any]]:
    """Os comentários que você colou (um por linha; '1.2K' / '340 curtidas' no fim ou no começo viram as curtidas)."""
    out = []
    for linha in str(texto or "").replace("\r", "").split("\n"):
        t = " ".join(linha.split()).strip("-•* ")
        if len(t) < 2:
            continue
        m = re.search(r"(?:^|\s)(\d+(?:[.,]\d+)?)\s*([kKmM]|mil)?\s*(?:curtidas|likes|❤️?)?\s*$", t)
        curt = 0
        if m and len(t) > len(m.group(0)) + 3:
            v = float(m.group(1).replace(",", "."))
            curt = int(v * (1000 if (m.group(2) or "").lower() in ("k", "mil") else 1_000_000 if (m.group(2) or "").lower() == "m" else 1))
            t = t[:m.start()].strip()
        out.append({"texto": t[:400], "curtidas": curt, "autor": ""})
    return out[:80]


def texto_para_ia(info: Dict[str, Any]) -> str:
    """O bloco que entra no prompt do roteiro: o que o post original diz e o que o público fala."""
    if not info or not (info.get("comentarios") or info.get("descricao") or info.get("titulo")):
        return ""
    L = ["## THE ORIGINAL POST (context — may be wrong or clickbait; the clip timeline above is what happens)"]
    if info.get("titulo") or info.get("descricao"):
        L.append(f"Caption: {(info.get('titulo') or '')} {(info.get('descricao') or '')}".strip()[:1500])
    nums = [f"{_fmt_n(info[k])} {r}" for k, r in (("views", "views"), ("curtidas", "likes"), ("n_comentarios", "comments")) if info.get(k)]
    if nums:
        L.append("Numbers: " + " · ".join(nums))
    coms = info.get("comentarios") or []
    if coms:
        L += ["", "## WHAT VIEWERS SAY — top comments (most liked first). Use them: the QUESTIONS people ask are what the script "
              "must answer (or the hook); the point where people ARGUE is the best final question; repeated jokes show the right "
              "tone; context they add is UNCONFIRMED (never state it as fact)."]
        for c in coms[:50]:
            L.append(f"- ({_fmt_n(c.get('curtidas'))} likes){' [?]' if '?' in c['texto'] else ''} {c['texto']}")
    return "\n".join(L)
