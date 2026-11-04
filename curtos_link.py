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
    "arte": "🎨 arte e criações (o artista, a técnica, a reação)",
}
REGRA_MODO = {
    "auto": ("APPROACH: choose what makes THIS clip perform best — COMMENTARY (retell + the narrator's opinion, the twist, a "
             "question people argue about) or EXPLAIN (tell viewers HOW/WHY what they see happens: the technique, the rule, the "
             "physics, the animal behavior, the trick — step by step in sync with the clip, ending with the most surprising detail "
             "+ a question). Prefer EXPLAIN when the comments are full of 'how?'/'why?' questions or the clip shows a skill/trick/"
             "phenomenon; prefer COMMENTARY when people argue about a decision or a reaction. Start 'descricao' with "
             "'[COMMENTARY]' or '[EXPLAIN]' (or '[ART]' when the clip shows someone CREATING something: a painting, drawing, "
             "sculpture, cake/jelly art, craft — then follow the ART approach: name the artist, explain the technique, react)."),
    "comentario": ("APPROACH: COMMENTARY — retell what happens with the narrator's own opinion, the twist nobody noticed, and end "
                   "with the question people argue about."),
    "explicar": ("APPROACH: EXPLAIN WHAT IS HAPPENING — tell viewers HOW/WHY what they see happens (the technique, the rule, the "
                 "physics, the animal behavior, the trick), step by step and in sync with the clip; the hook is the curious "
                 "question ('How did he…?' / 'Why does this…?'); end with the most surprising detail + a question. Only "
                 "well-established facts; if the reason is not clear from the clip and comments, say what it most likely is."),
    "arte": ("APPROACH: ART & CREATIONS — a narrator who loves art watches an artist create and talks to the viewer like a friend "
             "next to them: genuine, casual, enthusiastic ('look at that…', 'no way…', 'that's pure talent'), never formal.\n"
             "- OPEN by presenting the ARTIST by name — the @ of the post (written so it can be read aloud: '@ariel.cy' → 'Ariel Cy') "
             "+ where they are from if the caption says so — and what they are making / the material ('…presenting this dry pastel "
             "piece'). A short catchphrase opener is fine ('Every day is a day to learn.').\n"
             "- EXPLAIN THE TECHNIQUE in sync with the clip, step by step: the material (dry pastel, acrylic pour, colored pencil, "
             "gelatin with a needle, clay…), what it is, WHY it creates this effect (light, contrast, 3D look, transparency), what "
             "the artist controls and what is left to chance. Only what you can see or what is well-established about that technique; "
             "if unsure, say 'probably'.\n"
             "- THE SUBJECT: if WHAT is being made is unusual, weird or surprising (a portrait made of toast, a sculpture of an "
             "odd creature, a hyper-real everyday object, a scene that tells a story), talk about IT too — what it is, the detail "
             "that makes it strange or funny, what it reminds you of — and let that be the hook and the title. If the subject is "
             "ordinary (a flower, a landscape), focus on the technique.\n"
             "- REACT at the turns: doubt before ('that bottom part won't turn into anything…'), the REVEAL ('look what it became!'), "
             "a light self-deprecating joke ('if I tried this it'd end up all over the floor'), a comparison people know ('like those "
             "crystal-clear waters…'). At the big reveal use FEW words — let the image breathe.\n"
             "- END: the finished piece + send people to the artist ('go check out her profile — link in the description') + a short "
             "question ('would you hang this in your house?').\n"
             "- Titles ('titulo_video', 'titulos'): catchy and about WHAT is being made or the TECHNIQUE ('She paints UNDERWATER light "
             "with dry pastel', 'This is not a photo…', 'Flowers INSIDE a jelly cake'), honest. 'descricao': what it is + the "
             "technique + credit the artist with their @. Always credit the artist; never claim the work as yours."),
}


def regra_modo(modo: str) -> str:
    return REGRA_MODO.get(modo, REGRA_MODO["auto"])


def modo_escolhido(descricao: str, pedido: str) -> str:
    """O modo que a IA usou (no auto ela marca [COMMENTARY]/[EXPLAIN] no começo da descrição)."""
    if pedido in ("comentario", "explicar"):
        return pedido
    d = str(descricao or "").upper()
    if pedido == "arte":
        return "arte"
    return "arte" if "[ART]" in d else "explicar" if "[EXPLAIN]" in d else "comentario" if "[COMMENTARY]" in d else ""


def limpar_marca(descricao: str) -> str:
    return re.sub(r"^\s*\[(COMMENTARY|EXPLAIN|ART)\]\s*", "", str(descricao or ""))


# ---------------------------------------------------------------------------------------------------- comentários
def _fmt_n(v: Any) -> str:
    try:
        v = int(v)
    except (TypeError, ValueError):
        return "?"
    return f"{v / 1e6:.1f}M" if v >= 1e6 else f"{v / 1e3:.1f}K" if v >= 1e3 else str(v)


def _handle(j: Dict[str, Any]) -> str:
    """O @ do criador (sem o @): o 1º que parece um usuário (sem espaço, não só número)."""
    for k in ("uploader_id", "channel", "uploader", "creator"):
        v = str(j.get(k) or "").strip().lstrip("@")
        if v and " " not in v and not v.isdigit() and not (v.startswith("UC") and len(v) > 20):
            return v[:60]
    return ""


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
            "autor_handle": _handle(j),
            "views": j.get("view_count"), "curtidas": j.get("like_count"), "n_comentarios": j.get("comment_count"),
            "duracao": j.get("duration"), "comentarios": coms[:n],
            "musica": musica_do_post(j), "local": local_do_post(j)}


def musica_do_post(j: Dict[str, Any]) -> str:
    """🎵 v84_351: a música do post, quando a plataforma informa (TikTok/Shorts/Reels via yt-dlp): 'Faixa · Artista'.
    O "som original" de um usuário não conta como música (não dá pra indexar)."""
    faixa = " ".join(str(j.get("track") or "").split())
    artistas = j.get("artists") if isinstance(j.get("artists"), list) else [j.get("artist")] if j.get("artist") else []
    artista = ", ".join(" ".join(str(a).split()) for a in artistas if a)
    if not faixa or re.match(r"(?i)^(original sound|som original|sonido original|son original|suono originale)\b", faixa):
        return ""
    return (f"{faixa} · {artista}" if artista and artista.lower() not in faixa.lower() else faixa)[:160]


def local_do_post(j: Dict[str, Any]) -> str:
    """📍 v84_351: o local marcado no post (quando vem)."""
    v = j.get("location")
    if isinstance(v, dict):
        v = v.get("name") or v.get("title") or ""
    return " ".join(str(v or "").split())[:120]


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
    if info.get("local"):  # 📍 v84_351: o lugar marcado pelo criador (contexto confiável de ONDE foi filmado)
        L.append(f"Location tagged by the creator: {info['local']} (use it to say where this is, if it helps)")
    if info.get("musica"):
        L.append(f"Song on the post: {info['musica']} (context only — never read lyrics; mention it only if it really matters)")
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


# ---------------------------------------------------------------------------------------------------- 📌 fonte (v84_305)
PLATAFORMAS = [("instagram.", "Instagram"), ("tiktok.", "TikTok"), ("youtube.", "YouTube"), ("youtu.be", "YouTube"),
               ("kwai", "Kwai"), ("facebook.", "Facebook"), ("fb.watch", "Facebook"), ("twitter.", "X"), ("x.com", "X"),
               ("reddit.", "Reddit"), ("vimeo.", "Vimeo"), ("threads.", "Threads"), ("pinterest.", "Pinterest")]


def plataforma(url: str) -> str:
    u = str(url or "").lower()
    return next((nome for chave, nome in PLATAFORMAS if chave in u), "")


def criador(url: str, info: Dict[str, Any]) -> str:
    """@ do criador: do link (tiktok.com/@fulano, youtube.com/@canal) ou do que o yt-dlp leu."""
    m = re.search(r"/@([A-Za-z0-9_.\-]{1,60})", str(url or ""))
    if m:
        return m.group(1)
    return str((info or {}).get("autor_handle") or "").lstrip("@") or str((info or {}).get("autor") or "").strip()


def linha_fonte(url: str, info: Dict[str, Any]) -> str:
    """'Source (Instagram): @criador' — vai no fim da descrição do post."""
    pf, quem = plataforma(url), criador(url, info)
    if not (pf or quem):
        return ""
    alvo = ("@" + quem) if quem and " " not in quem else (quem or str(url or "").split("?")[0])
    return f"Source ({pf}): {alvo}" if pf else f"Source: {alvo}"


def com_fontes(descricao: str, fontes: List[tuple]) -> str:
    """🧩 v84_349: o crédito de TODAS as fontes do vídeo composto ('Sources: @a (TikTok) · @b (Instagram)')."""
    d = str(descricao or "").rstrip()
    if re.search(r"(?im)^sources?\b", d):
        return d
    linhas = [linha_fonte(u, i).replace("Source (", "").replace("Source: ", "") for u, i in fontes]
    itens = []
    for (u, i), l in zip(fontes, linhas):
        if not l:
            continue
        pf, quem = plataforma(u), criador(u, i)
        alvo = ("@" + quem) if quem and " " not in quem else (quem or str(u).split("?")[0])
        itens.append(f"{alvo} ({pf})" if pf else alvo)
    return (d + "\n\nSources: " + " · ".join(itens)).strip() if itens else d


def com_fonte(descricao: str, url: str, info: Dict[str, Any]) -> str:
    d = str(descricao or "").rstrip()
    if not url or re.search(r"(?im)^source\b", d):
        return d
    f = linha_fonte(url, info)
    return (d + "\n\n" + f).strip() if f else d


# ---------------------------------------------------------------------------------------------------- 🖼 prints pra thumb (v84_305)
THUMB_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["escolhidos"],
                "properties": {"escolhidos": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["n", "por_que"],
                    "properties": {"n": {"type": "integer"}, "por_que": {"type": "string"}}}}}}
THUMB_SYS = ("You pick THUMBNAIL frames for a viral short. You get a contact sheet of numbered candidate frames from the video. "
             "Choose the 3 most IMPACTFUL, attention-grabbing frames: the peak of the action, a strong facial expression, the "
             "surprising moment, clear subject, sharp (no motion blur), not a transition/black/text-only frame, and the 3 different "
             "from each other. 'por_que' = a few words in Brazilian Portuguese.")


def _nota_quadro(img) -> float:
    """Nitidez + contraste + cor (quadro borrado, escuro ou chapado vale pouco)."""
    import cv2
    import numpy as np
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    nit = float(cv2.Laplacian(g, cv2.CV_64F).var())
    con = float(g.std())
    b, gr, r = [c.astype("float32") for c in cv2.split(img)]
    rg, yb = np.abs(r - gr), np.abs(0.5 * (r + gr) - b)
    cor = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    if g.mean() < 25 or g.mean() > 235:
        return 0.0
    return min(nit, 1500.0) / 15.0 + con + cor


def prints_para_thumb(video: str, pasta: str, n: int = 3, candidatos: int = 16, chamar=None) -> List[Dict[str, Any]]:
    """🖼 os n quadros mais impactantes do vídeo (pra thumb): {arquivo, t, por_que}. A IA escolhe numa folha de contato;
    sem IA, os mais nítidos/contrastados/coloridos, espalhados pelo vídeo."""
    import os
    import cv2
    cap = cv2.VideoCapture(video)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0) or 30.0
    if total <= 0:
        cap.release()
        raise ValueError("não consegui abrir o vídeo")
    quadros = []
    for k in range(candidatos):
        f = int(total * (0.04 + 0.92 * k / max(1, candidatos - 1)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(total - 1, f))
        ok, img = cap.read()
        if ok and img is not None:
            quadros.append({"t": round(f / fps, 2), "img": img, "nota": _nota_quadro(img)})
    cap.release()
    if not quadros:
        raise ValueError("não li nenhum quadro")
    escolha: List[Dict[str, Any]] = []
    if chamar is not False:
        try:
            escolha = _escolher_com_ia(quadros, n, chamar)
        except Exception:  # noqa: BLE001  (sem IA: pela nota)
            escolha = []
    if len(escolha) < n:
        dist = max(1.0, quadros[-1]["t"] / (n * 2))
        for q in sorted(quadros, key=lambda q: -q["nota"]):
            if len(escolha) >= n:
                break
            if q["nota"] > 0 and all(abs(q["t"] - e["t"]) >= dist for e in escolha):
                escolha.append(dict(q, por_que=""))
    os.makedirs(pasta, exist_ok=True)
    for velho in os.listdir(pasta):
        if velho.startswith("thumb_") and velho.endswith(".jpg"):
            os.remove(os.path.join(pasta, velho))
    out = []
    for k, q in enumerate(sorted(escolha[:n], key=lambda e: e["t"]), 1):
        nome = f"thumb_{k}.jpg"
        cv2.imwrite(os.path.join(pasta, nome), q["img"], [cv2.IMWRITE_JPEG_QUALITY, 95])
        out.append({"arquivo": nome, "t": q["t"], "por_que": q.get("por_que") or ""})
    return out


def _escolher_com_ia(quadros: List[Dict[str, Any]], n: int, chamar=None) -> List[Dict[str, Any]]:
    import base64
    import cv2
    import numpy as np
    import ia_servico
    if chamar is None and not ia_servico.ativo("curtos"):
        return []
    larg = 320
    mini = []
    for k, q in enumerate(quadros, 1):
        h, w = q["img"].shape[:2]
        m = cv2.resize(q["img"], (larg, max(1, int(h * larg / w))))
        cv2.rectangle(m, (0, 0), (46, 34), (0, 0, 0), -1)
        cv2.putText(m, str(k), (6, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        mini.append(m)
    alt = max(m.shape[0] for m in mini)
    mini = [cv2.copyMakeBorder(m, 0, alt - m.shape[0], 0, 0, cv2.BORDER_CONSTANT) for m in mini]
    col = 4
    while len(mini) % col:
        mini.append(np.zeros_like(mini[0]))
    folha = np.vstack([np.hstack(mini[i:i + col]) for i in range(0, len(mini), col)])
    ok, buf = cv2.imencode(".jpg", folha, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return []
    bloco = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(buf.tobytes()).decode()}}
    r = (chamar or ia_servico.chamar)("curtos", THUMB_SYS, [bloco, {"type": "text", "text": f"{len(quadros)} frames. Pick {n}."}],
                                      schema=THUMB_SCHEMA, max_tokens=400)
    out = []
    for e in (r or {}).get("escolhidos") or []:
        try:
            i = int(e.get("n")) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(quadros) and all(o["t"] != quadros[i]["t"] for o in out):
            out.append(dict(quadros[i], por_que=str(e.get("por_que") or "")[:120]))
    return out[:n]
