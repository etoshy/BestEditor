"""
react_personagens.py — 🎭 React de personagens (v84_236)
=======================================================

Vídeo no estilo dos "reacts de Gacha Life": personagens famosos (de anime, filme, série… ou pessoas reais) sentados
num sofá assistindo a um vídeo (música de anime, AMV, cena de filme) numa TV, e as falas deles aparecem escritas
embaixo da TV, como legenda. Fica na aba 🕵️ Modelos de vídeo → 🎭 React de personagens.

Passo a passo de um projeto (react_personagens/<id>/projeto.json):

  1. 🎬 Vídeo — título + link (YouTube/qualquer rede) OU o arquivo; a transcrição com tempo (o formato "0:13 frase",
     SRT, VTT ou "[00:13] frase"; linhas repetidas e créditos "Personagem - Cantor" são limpos). Sem transcrição:
     🎙 Whisper.
  2. 🤖 Sugerir personagens — a IA lê a transcrição e olha quadros do vídeo e sugere quem combina: personagens da
     PRÓPRIA obra, personagens hypados na internet que rendem um bom roteiro e um contraste (alguém de fora que reage
     diferente). Você marca os que quer, mistura com os seus (digita o nome), troca ou apaga qualquer um.
  3. 🧑‍🤝‍🧑 Elenco — cada personagem tem personalidade, jeito de falar, aparência (pro desenho) e a imagem de referência:
     🧲 pesquisada no navegador das imagens (o Brave do site — a mesma busca do 🎭 Elenco), enviada do PC ou por link.
  4. 📝 Roteiro — a IA analisa a transcrição e o vídeo (quadros com o tempo) e escreve as falas: QUEM fala, QUANDO
     (segundo do vídeo), a EXPRESSÃO (de acordo com a personalidade e o momento) e as reações de quem está ouvindo.
     O pedido de like/inscrição é UMA fala de um dos personagens (sem corte de inscreva-se). Tudo editável.
  5. 🏠 Cenário em CAMADAS (no 🚀 Flow em massa): fundo (a parede/sala), sofá(s) e a mesa da frente (essas duas com
     fundo verde, recortadas aqui no PC) — a mesa por cima dos personagens dá a sensação de proximidade. Estilo:
     anime/cartoon (personagens de anime) ou realista (pessoas reais) — automático pelo elenco.
     Disposições: "sofa_tv" (sofá na esquerda com todos sentados, TV na direita) ou "dois_sofas" (um sofá de cada
     lado, a TV no meio). A legenda vai embaixo da TV.
  6. 🧍 Personagens — cada um vira um projeto da aba 🧍 Personagens (personagens_pod, motor Flow): SENTADO, uma pose
     por expressão (a ⭐ neutra é a mestre, as outras saem dela) + a "_boca" de cada uma (a animação de fala).
  7. 🎬 Mandar pro editor — cria o projeto do Estúdio com tudo posicionado: o áudio é o do vídeo, o fundo é o trecho,
     e as camadas (sofá → personagens → mesa → TV → legendas → o vídeo na tela) são overlays "origem": "react".
     Quem fala troca de expressão e mexe a boca enquanto a fala está na tela; quem ouve pode reagir.
"""
from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

_BASE = os.path.dirname(os.path.abspath(__file__))
_TRAVA = threading.RLock()
RE_ID = re.compile(r"^rp[0-9a-f]{10}$")
W, H = 1920, 1080  # o react é sempre 16:9

LAYOUTS = {
    "sofa_tv": "🛋 Sofá na esquerda com todos sentados · 📺 TV na direita",
    "dois_sofas": "🛋📺🛋 Um sofá de cada lado · TV no meio",
}
ESTILOS = {"auto": "Automático (pelo elenco)", "anime": "Anime / cartoon", "realista": "Realista"}
DENSIDADES = {"pouca": 15.0, "normal": 9.0, "muita": 6.0}  # 1 fala a cada N segundos (mais ou menos)

# expressão → (nome na tela, como desenhar — o personagem SENTADO, virado pra TV)
EXPRESSOES: Dict[str, Tuple[str, str]] = {
    "neutro": ("😐 Neutro", "calm neutral expression, relaxed, attentively watching"),
    "feliz": ("😄 Feliz / rindo", "big happy smile, laughing, eyes squinting with joy"),
    "chocado": ("😱 Chocado", "shocked, eyes wide open, jaw dropped, leaning slightly back"),
    "bravo": ("😠 Bravo", "angry, furrowed brows, gritted teeth, clenched fist"),
    "pensativo": ("🤔 Pensativo / desconfiado", "thinking, skeptical, one eyebrow raised, hand on chin"),
    "empolgado": ("🤩 Empolgado / hypado", "hyped and excited, sparkling eyes, both fists raised"),
    "debochado": ("😏 Debochado", "smug sarcastic smirk, half-closed eyes, arms crossed"),
    "triste": ("😢 Triste / emocionado", "sad and emotional, teary eyes, frowning mouth"),
    "assustado": ("😨 Assustado", "scared and nervous, sweat drop, shoulders raised"),
    "confuso": ("😕 Confuso", "confused, head tilted, question-mark face"),
    "entediado": ("🥱 Entediado", "bored, half-closed eyes, cheek resting on hand"),
    "apaixonado": ("😍 Encantado", "starry-eyed, blushing, hands together, in awe"),
}
EXPRESSOES_PADRAO = ["neutro", "feliz", "chocado", "bravo", "pensativo", "empolgado", "debochado", "triste"]
CORES = ["#ff5c5c", "#4fc3ff", "#ffd54a", "#7cff8a", "#ff8ad8", "#c49bff", "#ffa64d", "#5effe0"]
CAMADAS = ("fundo", "sofa", "mesa")
# a ficha de cada personagem (o que a IA preenche e você corrige)
CAMPOS_FICHA_TXT = ("obra", "personalidade", "jeito_de_falar", "cronologia", "relacoes", "aparencia_en", "busca_imagem")
ROTULO_CAMADA = {"fundo": "🧱 Fundo (sala)", "sofa": "🛋 Sofá", "mesa": "🪵 Mesa da frente"}
ESTILO_TXT = {
    "anime": ("2D anime / cartoon illustration style like a Gacha Life reaction video, clean line art, flat cel shading, "
              "vibrant colors"),
    "realista": "photorealistic, real photograph, natural cinematic lighting, high detail",
}


class ReactErro(Exception):
    pass


# ------------------------------------------------------------------ guardar
def pasta_raiz(base: str = _BASE) -> str:
    return os.environ.get("REACT_PERSONAGENS_DIR") or os.path.join(base, "react_personagens")


def pasta(pid: str, base: str = _BASE) -> str:
    if not RE_ID.match(pid or ""):
        raise ReactErro("projeto inválido")
    return os.path.join(pasta_raiz(base), pid)


def carregar(pid: str, base: str = _BASE) -> Dict[str, Any]:
    try:
        with open(os.path.join(pasta(pid, base), "projeto.json"), encoding="utf-8") as f:
            p = json.load(f)
    except FileNotFoundError:
        raise ReactErro("Projeto não encontrado.")
    return _completar(p)


def salvar(p: Dict[str, Any], base: str = _BASE) -> None:
    d = pasta(p["id"], base)
    os.makedirs(d, exist_ok=True)
    p["atualizado"] = time.time()
    tmp = os.path.join(d, f"projeto.json.{secrets.token_hex(3)}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    try:
        import arquivo_seguro
        arquivo_seguro.trocar(tmp, os.path.join(d, "projeto.json"))
    except ImportError:  # pragma: no cover
        os.replace(tmp, os.path.join(d, "projeto.json"))


def _completar(p: Dict[str, Any]) -> Dict[str, Any]:
    p.setdefault("video", {})
    p.setdefault("transcricao_bruta", "")
    p.setdefault("transcricao", [])
    p.setdefault("obra", "")
    p.setdefault("contexto", "")
    p.setdefault("idioma", "português do Brasil")
    p.setdefault("estilo", "auto")
    p.setdefault("layout", "sofa_tv")
    p.setdefault("densidade", "normal")
    p.setdefault("expressoes", list(EXPRESSOES_PADRAO))
    p.setdefault("sugestoes", {})
    p.setdefault("personagens", [])
    p.setdefault("roteiro", {})
    p.setdefault("cenario", {})
    p["cenario"].setdefault("camadas", {})
    p.setdefault("editor", {})
    p.setdefault("checagem", {})
    p.setdefault("cortes", {"inicio": None, "fim": None, "meio": []})
    p.setdefault("log", [])
    return p


def log(p: Dict[str, Any], msg: str) -> None:
    p.setdefault("log", []).append(f"{time.strftime('%d/%m %H:%M:%S')} {msg}")
    p["log"] = p["log"][-80:]


def criar(titulo: str, base: str = _BASE) -> Dict[str, Any]:
    pid = "rp" + secrets.token_hex(5)
    os.makedirs(os.path.join(pasta(pid, base), "refs"), exist_ok=True)
    p = _completar({"id": pid, "titulo": (titulo or "").strip()[:200] or "React sem título", "criado": time.time()})
    log(p, "projeto criado")
    salvar(p, base)
    return p


def listar(base: str = _BASE) -> List[Dict[str, Any]]:
    raiz = pasta_raiz(base)
    out = []
    for n in os.listdir(raiz) if os.path.isdir(raiz) else []:
        if not RE_ID.match(n):
            continue
        try:
            p = carregar(n, base)
        except Exception:  # noqa: BLE001
            continue
        out.append({"id": n, "titulo": p.get("titulo"), "atualizado": p.get("atualizado", 0),
                    "personagens": len(p["personagens"]), "falas": len((p["roteiro"] or {}).get("falas") or []),
                    "tem_video": bool(_video_local(p, base)), "job": (p.get("editor") or {}).get("job_id")})
    return sorted(out, key=lambda x: -x["atualizado"])


def excluir(pid: str, base: str = _BASE) -> None:
    shutil.rmtree(pasta(pid, base), ignore_errors=True)


def _slug(s: Any) -> str:
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:30] or "personagem"


def _norm(s: Any) -> str:
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", t)


def mmss(s: Any) -> str:
    try:
        s = max(0.0, float(s))
    except (TypeError, ValueError):
        return "?"
    m, x = divmod(int(round(s)), 60)
    return f"{m // 60}:{m % 60:02d}:{x:02d}" if m >= 60 else f"{m}:{x:02d}"


def segundos(v: Any) -> Optional[float]:
    """"1:23" / "01:02:03" / "83" / 83.5 → segundos."""
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v or "").strip().replace(",", ".")
    if not t:
        return None
    try:
        partes = [float(x) for x in t.split(":")]
    except ValueError:
        return None
    s = 0.0
    for x in partes:
        s = s * 60 + x
    return s


# ------------------------------------------------------------------ 📝 transcrição
_ZW = re.compile("[​-‏⁠﻿­]")
_RE_SRT = re.compile(r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}|\d{1,2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}|\d{1,2}:\d{2}[,.]\d{1,3})")
_RE_LINHA = re.compile(r"^\s*[\[(]?\s*(\d{1,2}(?::\d{1,2}){1,2}(?:[.,]\d+)?)\s*[\])]?\s*(?:[-–—:|]\s*)?(.*)$")
# "Yhwach - Lucas A.R.T": quem canta/fala aquele trecho (crédito) — curto, com " - " e sem pontuação de frase
_RE_CREDITO = re.compile(r"^[^.!?,]{2,40}?\s[-–—]\s[^.!?,\s][^!?,]{1,39}$")


def colapsar_repeticoes(texto: str) -> str:
    """"A A A B B" → "A B" (o mesmo trecho de palavras repetido em seguida, comum em legenda extraída da tela)."""
    toks = texto.split()
    mudou = True
    while mudou and len(toks) > 1:
        mudou = False
        n = len(toks)
        for L in range(n // 2, 0, -1):
            i = 0
            out: List[str] = []
            while i < n:
                if i + 2 * L <= n and [_norm(x) for x in toks[i:i + L]] == [_norm(x) for x in toks[i + L:i + 2 * L]]:
                    j = i + L
                    while j + L <= n and [_norm(x) for x in toks[i:i + L]] == [_norm(x) for x in toks[j:j + L]]:
                        j += L
                    out.extend(toks[i:i + L])
                    i = j
                    mudou = True
                else:
                    out.append(toks[i])
                    i += 1
            if mudou:
                toks = out
                break
    return " ".join(toks)


def _frases_novas(texto: str, conhecidas: List[str]) -> List[str]:
    """Uma linha pode juntar o fim da frase anterior com a próxima ("A B"): devolve só as frases dela que são novas,
    tirando do começo/fim o que já é conhecido."""
    t = texto
    mudou = True
    while mudou and t:
        mudou = False
        for c in sorted(conhecidas, key=len, reverse=True):
            if c and _norm(t).startswith(_norm(c)) and len(_norm(t)) > len(_norm(c)):
                # corta pelo número de palavras de c
                t = " ".join(t.split()[len(c.split()):]).strip()
                mudou = True
                break
    return [t] if t else []


def parse_transcricao(texto: str) -> List[Dict[str, Any]]:
    """Texto colado → [{"ini", "fim", "texto", "tipo": "fala"|"credito"}], sem repetição.

    Aceita SRT/VTT ("00:00:13,000 --> 00:00:16,000" + texto), "0:13 frase", "[00:13] frase", "00:13 - frase" e texto
    sem tempo (uma linha por frase, sem tempo). Na legenda extraída da tela (a mesma frase em dezenas de linhas, às
    vezes duplicada na mesma linha e intercalada com o crédito), cada frase vira UMA entrada com o 1º e o último
    segundo em que apareceu (se ela volta depois de 6 s — refrão — é outra entrada)."""
    texto = _ZW.sub("", texto or "").replace("\r\n", "\n").replace("\r", "\n")
    linhas = texto.split("\n")
    brutas: List[Tuple[Optional[float], Optional[float], str]] = []
    if _RE_SRT.search(texto):
        atual: Optional[Tuple[float, float]] = None
        buf: List[str] = []
        for ln in linhas + [""]:
            m = _RE_SRT.search(ln)
            if m:
                if atual and buf:
                    brutas.append((atual[0], atual[1], " ".join(buf)))
                atual = (segundos(m.group(1)) or 0.0, segundos(m.group(2)) or 0.0)
                buf = []
            elif not ln.strip():
                if atual and buf:
                    brutas.append((atual[0], atual[1], " ".join(buf)))
                atual, buf = None if not ln.strip() else atual, []
            elif atual is not None and not re.fullmatch(r"\d+", ln.strip()) and ln.strip().upper() != "WEBVTT":
                buf.append(re.sub(r"<[^>]+>", "", ln.strip()))
    else:
        for ln in linhas:
            ln = ln.strip()
            if not ln:
                continue
            m = _RE_LINHA.match(ln)
            if m and m.group(2).strip():
                brutas.append((segundos(m.group(1)), None, m.group(2)))
            elif m:
                continue  # só o tempo (formato do YouTube: tempo numa linha, texto na outra) → o texto vem na próxima
            else:
                ant = brutas[-1] if brutas else None
                if ant is not None and ant[0] is not None and not ant[2]:
                    brutas[-1] = (ant[0], None, ln)
                else:
                    brutas.append((None, None, ln))
    # formato do YouTube "0:13\nfrase": junta o tempo sozinho com a linha seguinte
    if not _RE_SRT.search(texto):
        juntas: List[Tuple[Optional[float], Optional[float], str]] = []
        pend: Optional[float] = None
        for ln in linhas:
            ln = ln.strip()
            m = _RE_LINHA.match(ln) if ln else None
            if m and not m.group(2).strip():
                pend = segundos(m.group(1))
            elif ln and pend is not None and not m:
                juntas.append((pend, None, ln))
                pend = None
        if juntas and len(juntas) >= len(brutas) * 0.6:
            brutas = juntas
    out: List[Dict[str, Any]] = []
    ultimo: Dict[str, Dict[str, Any]] = {}  # frase normalizada → a entrada aberta dela
    creditos: set = set()
    for ini, fim, txt in brutas:
        txt = " ".join(colapsar_repeticoes(" ".join(str(txt).split())).split())
        if not txt:
            continue
        for cr in creditos:  # "Kyoraku - Teaga Se esse é o caso…": o crédito grudado na frase sai dela
            if txt != cr and txt.startswith(cr + " "):
                txt = txt[len(cr):].strip()
            elif txt != cr and txt.endswith(" " + cr):
                txt = txt[:-len(cr)].strip()
        credito = bool(_RE_CREDITO.match(txt)) and len(txt.split()) <= 7
        if credito:
            creditos.add(txt)
        conhecidas = [e["texto"] for e in out[-6:] if e["tipo"] == "fala"]
        frases = [txt] if credito or ini is None else _frases_novas(txt, conhecidas)
        if not frases:  # só repetiu o que já estava (estende o fim da frase)
            for e in reversed(out[-6:]):
                if ini is not None and _norm(txt).startswith(_norm(e["texto"])):
                    e["fim"] = max(e["fim"] or 0, ini + 1.0)
                    break
            continue
        for fr in frases:
            k = ("C|" if credito else "F|") + _norm(fr)
            e = ultimo.get(k)
            if e is not None and ini is not None and e["fim"] is not None and ini - e["fim"] <= 6.0 and e in out[-8:]:
                e["fim"] = max(e["fim"], (fim if fim is not None else ini + 1.0))
                continue
            nova = {"ini": ini, "fim": fim if fim is not None else (ini + 1.0 if ini is not None else None),
                    "texto": fr[:400], "tipo": "credito" if credito else "fala"}
            out.append(nova)
            ultimo[k] = nova
    out = [e for e in out if e["texto"]]
    # o fim de cada fala não passa do começo da próxima fala
    falas = [e for e in out if e["tipo"] == "fala" and e["ini"] is not None]
    for a, b in zip(falas, falas[1:]):
        if a["fim"] is not None and b["ini"] is not None and a["fim"] > b["ini"]:
            a["fim"] = max(a["ini"], b["ini"])
    for e in out:
        if e["ini"] is not None:
            e["ini"] = round(float(e["ini"]), 2)
            e["fim"] = round(float(e["fim"] if e["fim"] is not None else e["ini"] + 1.0), 2)
    return out


def transcricao_texto(itens: List[Dict[str, Any]], limite: int = 14000) -> str:
    """Pra IA: "[0:13–0:16] frase" e "(crédito: Yhwach - Lucas A.R.T)"."""
    linhas = []
    for e in itens:
        tempo = f"[{mmss(e['ini'])}–{mmss(e['fim'])}] " if e.get("ini") is not None else ""
        linhas.append(f"{tempo}(crédito na tela: {e['texto']})" if e["tipo"] == "credito" else f"{tempo}{e['texto']}")
    t = "\n".join(linhas)
    if len(t) > limite:
        t = t[:limite] + "\n[…transcrição cortada]"
    return t


# ------------------------------------------------------------------ 🎬 vídeo
def _video_local(p: Dict[str, Any], base: str = _BASE) -> Optional[str]:
    v = p.get("video") or {}
    if v.get("arquivo"):
        cam = os.path.join(pasta(p["id"], base), v["arquivo"])
        if os.path.isfile(cam):
            return cam
    return None


def video_local(p: Dict[str, Any], base: str = _BASE) -> Optional[str]:
    return _video_local(p, base)


def sondar(caminho: str) -> Dict[str, Any]:
    """Duração, tamanho e se tem áudio."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                            "-of", "json", caminho], capture_output=True, text=True, timeout=60)
        d = json.loads(r.stdout or "{}")
    except Exception:  # noqa: BLE001
        d = {}
    vs = [s for s in d.get("streams") or [] if s.get("codec_type") == "video"]
    return {"duracao": float((d.get("format") or {}).get("duration") or 0),
            "largura": int((vs[0] if vs else {}).get("width") or 0), "altura": int((vs[0] if vs else {}).get("height") or 0),
            "tem_audio": any(s.get("codec_type") == "audio" for s in d.get("streams") or [])}


def guardar_video(p: Dict[str, Any], origem: str, base: str = _BASE, url: str = "", nome: str = "") -> Dict[str, Any]:
    """O vídeo baixado/enviado já está em `origem` → move pra pasta do projeto e lê as informações."""
    d = pasta(p["id"], base)
    ext = os.path.splitext(origem)[1].lower() or ".mp4"
    destino = os.path.join(d, "video" + ext)
    for velho in os.listdir(d):
        if (velho.startswith("video.") or velho == "video_cortado.mp4") and os.path.join(d, velho) != destino:
            try:
                os.remove(os.path.join(d, velho))
            except OSError:
                pass
    if os.path.abspath(origem) != os.path.abspath(destino):
        shutil.move(origem, destino)
    info = sondar(destino)
    antes = p.get("video") or {}
    p["video"] = dict(antes, arquivo=os.path.basename(destino), original=os.path.basename(destino), estado="pronto", erro=None,
                      url=url or antes.get("url") or "", nome=nome or antes.get("nome") or "", original_info=dict(info), **info)
    if any((p.get("cortes") or {}).get(k) for k in ("inicio", "fim", "meio")):
        log(p, "✂ vídeo novo: os cortes do vídeo anterior foram tirados")
    p["cortes"] = {"inicio": None, "fim": None, "meio": []}
    definir_transcricao(p, p.get("transcricao_bruta") or "")
    return p["video"]


def video_original(p: Dict[str, Any], base: str = _BASE) -> Optional[str]:
    v = p.get("video") or {}
    nome = v.get("original") or v.get("arquivo")
    if nome:
        cam = os.path.join(pasta(p["id"], base), nome)
        if os.path.isfile(cam):
            return cam
    return None


# ------------------------------------------------------------------ ✂ cortes (começo, cenas do meio, final)
def removidos(p: Dict[str, Any]) -> List[List[float]]:
    """Os trechos que SAEM do vídeo, no tempo do vídeo ORIGINAL, em ordem e sem sobreposição."""
    c = p.get("cortes") or {}
    dur = float(((p.get("video") or {}).get("original_info") or {}).get("duracao") or (p.get("video") or {}).get("duracao") or 0)
    rs: List[List[float]] = []
    ini = segundos(c.get("inicio"))
    if ini and ini > 0:
        rs.append([0.0, ini])
    for a, b in c.get("meio") or []:
        a, b = segundos(a), segundos(b)
        if a is not None and b is not None and b > a:
            rs.append([a, b])
    fim = segundos(c.get("fim"))
    if fim and (not dur or fim < dur):
        rs.append([fim, max(dur, fim) + 1e6 if not dur else dur])
    rs.sort()
    juntos: List[List[float]] = []
    for a, b in rs:
        if juntos and a <= juntos[-1][1] + 0.01:
            juntos[-1][1] = max(juntos[-1][1], b)
        else:
            juntos.append([a, b])
    return [[round(a, 3), round(b, 3)] for a, b in juntos]


def mapear(t: Optional[float], rem: List[List[float]]) -> Optional[float]:
    """Segundo do vídeo ORIGINAL → segundo do vídeo cortado (None = caiu num trecho cortado)."""
    if t is None:
        return None
    tira = 0.0
    for a, b in rem:
        if t < a:
            break
        if t < b:
            return None
        tira += b - a
    return round(t - tira, 3)


def inverso(t: float, rem: List[List[float]]) -> float:
    """Segundo do vídeo cortado → segundo do ORIGINAL."""
    for a, b in rem:
        if t >= a - 1e-9:
            t += b - a
        else:
            break
    return round(t, 3)


def definir_transcricao(p: Dict[str, Any], texto: str) -> None:
    """A transcrição colada/puxada está no tempo do vídeo ORIGINAL; a que a IA lê segue os cortes."""
    p["transcricao_bruta"] = str(texto or "")[:600000]
    rem = removidos(p)
    out = []
    for e in parse_transcricao(p["transcricao_bruta"]):
        if e.get("ini") is None or not rem:
            out.append(e)
            continue
        ini = mapear(e["ini"], rem)
        if ini is None:  # começou num trecho cortado: fica se ainda aparece depois do corte
            ini = mapear(next((b for a, b in rem if a <= e["ini"] < b), e["ini"]), rem)
            if ini is None or e["fim"] <= next((b for a, b in rem if a <= e["ini"] < b), e["fim"]):
                continue
        fim = mapear(e["fim"], rem)
        if fim is None:
            fim = mapear(next((a for a, b in rem if a <= e["fim"] < b), e["fim"]), rem) or ini
        out.append(dict(e, ini=ini, fim=max(ini, fim)))
    p["transcricao"] = out


def cortar_video(entrada: str, saida: str, rem: List[List[float]], tem_audio: bool = True) -> str:
    """Tira os trechos (re-encoda — o corte fica exato no segundo)."""
    expr = "+".join(f"between(t,{a:.3f},{min(b, 1e7):.3f})" for a, b in rem)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", entrada,
           "-vf", f"fps=30,select='not({expr})',setpts=N/30/TB"]
    if tem_audio:
        cmd += ["-af", f"aselect='not({expr})',asetpts=N/SR/TB", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", saida]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0 or not os.path.isfile(saida):
        raise ReactErro(f"o corte falhou: {r.stderr[-300:]}")
    return saida


def aplicar_cortes(pid: str, base: str = _BASE, cortes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """✂ Corta o começo, cenas do meio e o final. As falas que já existem andam junto (as que caem num trecho cortado
    saem) e a transcrição segue os cortes. Sem cortes: volta pro vídeo inteiro."""
    with _TRAVA:
        p = carregar(pid, base)
        orig = video_original(p, base)
        if not orig:
            raise ReactErro("Baixe ou envie o vídeo antes.")
        info_o = (p["video"].get("original_info") or sondar(orig))
        dur = float(info_o.get("duracao") or 0)
        c = cortes if cortes is not None else (p.get("cortes") or {})
        novo = {"inicio": segundos(c.get("inicio")) or None, "fim": segundos(c.get("fim")) or None, "meio": []}
        for x in c.get("meio") or []:
            a, b = (segundos(x[0]), segundos(x[1])) if isinstance(x, (list, tuple)) and len(x) == 2 else (None, None)
            if a is None or b is None or b <= a:
                raise ReactErro(f"Corte do meio inválido: {x}")
            novo["meio"].append([round(a, 2), round(b, 2)])
        if novo["fim"] and dur and novo["fim"] >= dur - 0.05:
            novo["fim"] = None
        if novo["inicio"] and novo["fim"] and novo["fim"] <= novo["inicio"]:
            raise ReactErro("O fim tem que vir depois do começo.")
        rem_antes = removidos(p)
        p["cortes"] = novo
        rem = removidos(p)
        sobra = dur - sum(min(b, dur) - a for a, b in rem) if dur else 1
        if sobra < 3:
            raise ReactErro("Os cortes tiram quase o vídeo inteiro.")
    d = pasta(pid, base)
    saida = os.path.join(d, "video_cortado.mp4")
    if rem:
        tmp = os.path.join(d, "_cortando.mp4")
        cortar_video(orig, tmp, rem, bool(info_o.get("tem_audio", True)))
        os.replace(tmp, saida)
    with _TRAVA:
        p = carregar(pid, base)
        p["cortes"] = novo
        if rem:
            p["video"].update(arquivo="video_cortado.mp4", **sondar(saida))
        else:
            p["video"].update(arquivo=p["video"].get("original") or p["video"]["arquivo"], **info_o)
            try:
                os.remove(saida)
            except OSError:
                pass
        p["video"]["original_info"] = info_o
        definir_transcricao(p, p.get("transcricao_bruta") or "")
        falas = (p.get("roteiro") or {}).get("falas") or []
        ficam, sairam = [], 0
        for f in falas:  # a fala estava no tempo dos cortes de ANTES → original → tempo dos cortes novos
            t = mapear(inverso(float(f["t"]), rem_antes), rem)
            if t is None:
                sairam += 1
                continue
            ficam.append(dict(f, t=t))
        if falas:
            p["roteiro"]["falas"] = ficam
        total = sum(min(b, dur or b) - a for a, b in rem)
        log(p, (f"✂ {len(rem)} corte(s) — saíram {mmss(total)}; o vídeo ficou com {mmss(p['video'].get('duracao'))}" if rem
                else "✂ sem cortes: o vídeo inteiro") + (f" · {sairam} fala(s) caíram num trecho cortado e saíram" if sairam else ""))
        salvar(p, base)
    return {"duracao": p["video"].get("duracao"), "cortes": len(rem), "falas_sairam": sairam}


# ------------------------------------------------------------------ 📺 transcrição do YouTube (o sistema dos Roteiros do YouTube)
def eh_youtube(url: str) -> bool:
    return bool(re.match(r"^https?://(?:[\w-]+\.)*(?:youtube\.com|youtu\.be)/", str(url or "").strip(), re.I))


def transcrever_youtube(pid: str, base: str = _BASE, on_log: Callable[[str], None] = lambda _m: None) -> int:
    """📺 A transcrição do link do YouTube pelo mesmo sistema do 📝 Roteiro do YouTube (painel "Mostrar transcrição",
    legenda do vídeo pelo yt-dlp, youtube-transcript-api… e, sem legenda, o Whisper) — linha a linha, com o tempo."""
    import roteiros_yt as ry
    p = carregar(pid, base)
    url = str((p.get("video") or {}).get("url") or "").strip()
    if not eh_youtube(url):
        raise ReactErro("A transcrição automática é pra link do YouTube — cole o link no campo do vídeo.")
    tmp = os.path.join(pasta(pid, base), "_transcricao_yt")
    os.makedirs(tmp, exist_ok=True)
    try:
        tr = ry.extrair_transcricao(url, tmp, on_log=on_log)
    except Exception as exc:  # noqa: BLE001
        raise ReactErro(f"não consegui a transcrição do YouTube: {str(exc)[:300]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    linhas = tr.get("linhas") or tr.get("blocos") or []
    texto = "\n".join(f"{int(float(x['inicio']) // 60)}:{float(x['inicio']) % 60:04.1f} {' '.join(str(x.get('texto') or '').split())}"
                      for x in linhas if str(x.get("texto") or "").strip() and x.get("inicio") is not None)
    if not texto:
        raise ReactErro("o vídeo não tem fala/legenda")
    with _TRAVA:
        p = carregar(pid, base)
        definir_transcricao(p, texto)
        p["video"]["transcricao_fonte"] = tr.get("fonte") or ""
        if not p.get("titulo") or p["titulo"] == "React sem título":
            p["titulo"] = (tr.get("titulo") or p.get("titulo") or "")[:200]
        log(p, f"📺 transcrição do YouTube ({tr.get('fonte') or '?'}): {len(p['transcricao'])} linha(s)")
        salvar(p, base)
    return len(p["transcricao"])


def baixar_video(pid: str, base: str = _BASE, on_log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """⬇ Baixa o link do projeto (YouTube ou outra rede) — até 720p (é só pra caber na TV)."""
    p = carregar(pid, base)
    url = str((p.get("video") or {}).get("url") or "").strip()
    if not re.match(r"^https?://", url):
        raise ReactErro("Cole o link do vídeo (https://…).")
    tmp = os.path.join(pasta(pid, base), "_baixando")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    try:
        import transcrever_avulso
        try:
            import yt_texto
            url = getattr(yt_texto, "normalizar", lambda u: u)(url)
        except Exception:  # noqa: BLE001
            pass
        cam = transcrever_avulso.baixar_de_qualquer_fonte(url, tmp, "video.mp4", max_height=720, on_log=on_log)
        with _TRAVA:
            p = carregar(pid, base)
            v = guardar_video(p, cam, base, url=url)
            log(p, f"⬇ vídeo baixado ({mmss(v.get('duracao'))})")
            salvar(p, base)
        return v
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def extrair_audio(video: str, destino: str, duracao: float = 0) -> str:
    """O áudio do vídeo (o som do react) — sem áudio: silêncio do mesmo tamanho."""
    info = sondar(video)
    if info["tem_audio"]:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", video, "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", destino]
    else:
        dur = duracao or info["duracao"] or 1
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{dur:.3f}",
               "-c:a", "pcm_s16le", destino]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not os.path.isfile(destino):
        raise ReactErro(f"não consegui tirar o áudio do vídeo: {r.stderr[-300:]}")
    return destino


def transcrever_whisper(pid: str, base: str = _BASE) -> int:
    """🎙 Sem transcrição colada: o Whisper ouve o vídeo (letra cantada sai pior que fala — confira)."""
    p = carregar(pid, base)
    video = video_original(p, base)
    if not video:
        raise ReactErro("Baixe ou envie o vídeo antes.")
    wav = os.path.join(pasta(pid, base), "_audio_whisper.wav")
    extrair_audio(video, wav)
    try:
        from whisper_transcribe import transcribe_audio
        segs = transcribe_audio(wav)
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass
    texto = "\n".join(f"{mmss(s['start'])} {str(s['text']).strip()}" for s in segs if str(s.get("text") or "").strip())
    with _TRAVA:
        p = carregar(pid, base)
        definir_transcricao(p, texto)
        log(p, f"🎙 Whisper: {len(p['transcricao'])} linha(s)")
        salvar(p, base)
    return len(p["transcricao"])


def quadros(video: str, saida_dir: str, n: int = 24, largura: int = 320, ini: Optional[float] = None,
            fim: Optional[float] = None) -> List[Tuple[float, str]]:
    """N quadros espalhados pelo vídeo — ou só pelo trecho [ini, fim] — → [(segundo, caminho)]."""
    info = sondar(video)
    dur = info["duracao"] or 0
    if dur <= 0:
        return []
    os.makedirs(saida_dir, exist_ok=True)
    out = []
    a = max(0.0, ini or 0.0) if ini is not None else dur * 0.03
    b = min(dur, fim) if fim is not None else dur * 0.97
    if b <= a:
        return []
    for k in range(n):
        t = a + (b - a) * (k + 0.5) / n
        cam = os.path.join(saida_dir, f"q{k:03d}.jpg")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
                        "-vf", f"scale={largura}:-2", cam], capture_output=True, timeout=60)
        if os.path.isfile(cam):
            out.append((t, cam))
    return out


def _fonte(tamanho: int, negrito: bool = True):
    from PIL import ImageFont
    for nome in (("montserrat-Bold.ttf", "dp") if negrito else ("montserrat-Regular.ttf", "dp"),
                 ("DejaVuSans-Bold.ttf" if negrito else "DejaVuSans.ttf", "")):
        cam = os.path.join(_BASE, "assets", "fonts", nome[1], nome[0]) if nome[1] else os.path.join(_BASE, "assets", "fonts", nome[0])
        if os.path.isfile(cam):
            try:
                return ImageFont.truetype(cam, tamanho)
            except OSError:
                continue
    return ImageFont.load_default()


def mosaicos(qs: List[Tuple[float, str]], por: int = 9) -> List[Dict[str, Any]]:
    """Os quadros em mosaicos 3×3 com o tempo escrito em cada um → blocos de imagem pra IA."""
    from PIL import Image, ImageDraw
    blocos = []
    for k in range(0, len(qs), por):
        grupo = qs[k:k + por]
        ims = [(t, Image.open(c).convert("RGB")) for t, c in grupo]
        if not ims:
            continue
        cw = max(i.width for _t, i in ims)
        ch = max(i.height for _t, i in ims)
        cols = 3
        linhas = math.ceil(len(ims) / cols)
        tela = Image.new("RGB", (cols * cw, linhas * ch), (0, 0, 0))
        dr = ImageDraw.Draw(tela)
        f = _fonte(22)
        for j, (t, im) in enumerate(ims):
            x, y = (j % cols) * cw, (j // cols) * ch
            tela.paste(im, (x, y))
            rot = mmss(t)
            dr.rectangle([x, y, x + 74, y + 28], fill=(0, 0, 0))
            dr.text((x + 6, y + 2), rot, fill=(255, 230, 0), font=f)
        buf = io.BytesIO()
        tela.save(buf, "JPEG", quality=80)
        blocos.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                   "data": base64.b64encode(buf.getvalue()).decode()}})
    return blocos


def blocos_do_video(p: Dict[str, Any], base: str = _BASE, n: int = 27, ini: Optional[float] = None,
                    fim: Optional[float] = None) -> List[Dict[str, Any]]:
    video = _video_local(p, base)
    if not video:
        return []
    tmp = os.path.join(pasta(p["id"], base), f"_quadros_ia_{secrets.token_hex(3)}")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        return mosaicos(quadros(video, tmp, n, ini=ini, fim=fim))
    except Exception:  # noqa: BLE001
        return []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ 🧑‍🤝‍🧑 elenco
def novo_personagem(p: Dict[str, Any], nome: str, **campos: Any) -> Dict[str, Any]:
    nome = " ".join(str(nome or "").split())[:80]
    if not nome:
        raise ReactErro("Escreva o nome do personagem.")
    if any(_norm(c["nome"]) == _norm(nome) for c in p["personagens"]):
        raise ReactErro(f"{nome} já está no elenco.")
    usadas = {c.get("cor") for c in p["personagens"]}
    c = {"id": "c" + secrets.token_hex(3), "nome": nome, "obra": "", "personalidade": "", "jeito_de_falar": "",
         "cronologia": "", "relacoes": "", "aparencia_en": "", "busca_imagem": "", "estilo": "", "origem": "manual", "refs": [],
         "cor": next((x for x in CORES if x not in usadas), CORES[len(p["personagens"]) % len(CORES)]), "pod": None}
    for k, v in campos.items():
        if k in CAMPOS_FICHA_TXT + ("estilo", "origem", "motivo", "cor"):
            c[k] = str(v or "").strip()[:600]
    if not c["busca_imagem"]:
        c["busca_imagem"] = f"{nome} {c['obra']}".strip()
    p["personagens"].append(c)
    return c


def personagem(p: Dict[str, Any], cid: str) -> Dict[str, Any]:
    c = next((x for x in p["personagens"] if x["id"] == cid), None)
    if not c:
        raise ReactErro("Personagem não encontrado.")
    return c


def achar_por_nome(p: Dict[str, Any], nome: str) -> Optional[Dict[str, Any]]:
    n = _norm(nome)
    if not n:
        return None
    for c in p["personagens"]:
        if _norm(c["nome"]) == n:
            return c
    for c in p["personagens"]:  # "Itachi" ↔ "Itachi Uchiha"
        cn = _norm(c["nome"])
        if n in cn or cn in n:
            return c
    primeiro = {_norm(c["nome"].split()[0]): c for c in p["personagens"] if c["nome"].split()}
    return primeiro.get(_norm(str(nome).split()[0])) if str(nome).split() else None


def guardar_ref(p: Dict[str, Any], c: Dict[str, Any], dados: bytes, base: str = _BASE, nome: str = "") -> str:
    """Uma imagem de referência do personagem (no máximo 3; a mais nova entra na frente)."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(dados))
        im.load()
    except Exception:  # noqa: BLE001
        raise ReactErro("Isso não é uma imagem.")
    if im.width < 64 or im.height < 64:
        raise ReactErro("Imagem pequena demais.")
    if max(im.size) > 1600:
        k = 1600 / max(im.size)
        im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))))
    d = os.path.join(pasta(p["id"], base), "refs")
    os.makedirs(d, exist_ok=True)
    arq = f"{c['id']}_{secrets.token_hex(3)}.png"
    im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(os.path.join(d, arq))
    c["refs"] = [arq] + [r for r in c.get("refs") or [] if r != arq]
    for velho in c["refs"][3:]:
        try:
            os.remove(os.path.join(d, velho))
        except OSError:
            pass
    c["refs"] = c["refs"][:3]
    return arq


def baixar_ref(p: Dict[str, Any], c: Dict[str, Any], url: str, base: str = _BASE, dados_b64: str = "") -> str:
    if dados_b64:
        return guardar_ref(p, c, base64.b64decode(str(dados_b64).split(",")[-1]), base)
    url = str(url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        raise ReactErro("o link tem que começar com http:// ou https://")
    tmp = os.path.join(pasta(p["id"], base), "_ref_tmp")
    os.makedirs(tmp, exist_ok=True)
    try:
        cam = None
        try:
            import vendas as vd
            cam, tipo = vd.baixar_arquivo(url, tmp, "ref")
            if tipo != "foto":
                cam = None
        except Exception:  # noqa: BLE001
            cam = None
        if not cam:
            try:
                import buscador_imagens_unificado as bu
                im = bu.ImagemBuscador(title="", description="", source_page="", original_url=url, thumbnail_url="",
                                       width=None, height=None, query="", engine="")
                cam = bu.baixar_imagem(im, tmp, stem="ref", timeout_s=40)
            except Exception as exc:  # noqa: BLE001
                raise ReactErro(f"não consegui baixar a imagem ({str(exc)[:120]})")
        with open(cam, "rb") as f:
            return guardar_ref(p, c, f.read(), base)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def estilo_final(p: Dict[str, Any]) -> str:
    """anime | realista: o escolhido; no automático, realista só se TODO o elenco é de gente real."""
    if p.get("estilo") in ("anime", "realista"):
        return p["estilo"]
    ests = [c.get("estilo") for c in p["personagens"] if c.get("estilo") in ("anime", "realista")]
    if ests and all(e == "realista" for e in ests):
        return "realista"
    if not ests and (p.get("sugestoes") or {}).get("estilo") == "realista":
        return "realista"
    return "anime"


# ------------------------------------------------------------------ 🤖 IA
def _ia():
    import ia_servico
    return ia_servico


def ia_ligada() -> bool:
    try:
        return _ia().ativo("react")
    except Exception:  # noqa: BLE001
        return False


_CAMPOS_FICHA = {
    "nome": {"type": "string"}, "obra": {"type": "string"},
    "tipo": {"type": "string", "enum": ["da_obra", "hypado", "contraste"]},
    "motivo": {"type": "string"}, "personalidade": {"type": "string"}, "jeito_de_falar": {"type": "string"},
    "cronologia": {"type": "string"}, "relacoes": {"type": "string"},
    "aparencia_en": {"type": "string"}, "busca_imagem": {"type": "string"},
    "estilo": {"type": "string", "enum": ["anime", "realista"]},
}
SCHEMA_SUGESTOES = {
    "type": "object", "additionalProperties": False,
    "required": ["obra", "estilo", "resumo_video", "personagens"],
    "properties": {
        "obra": {"type": "string"}, "estilo": {"type": "string", "enum": ["anime", "realista"]},
        "resumo_video": {"type": "string"},
        "personagens": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                   "required": list(_CAMPOS_FICHA), "properties": _CAMPOS_FICHA}},
    },
}
SCHEMA_FICHAS = {
    "type": "object", "additionalProperties": False, "required": ["personagens"],
    "properties": {"personagens": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": [k for k in _CAMPOS_FICHA if k not in ("tipo", "motivo")],
        "properties": {k: v for k, v in _CAMPOS_FICHA.items() if k not in ("tipo", "motivo")}}}},
}

SYS_SUGESTOES = (
    "Você é roteirista de canais de REACT no estilo dos vídeos de Gacha Life: personagens famosos sentados num sofá "
    "assistindo a um vídeo (música de anime, AMV, rap de anime, cena de filme) numa TV, e as falas deles aparecem como "
    "legenda. Seu trabalho agora é SUGERIR O ELENCO que rende o melhor react para o vídeo descrito.\n"
    "Regras:\n"
    "- Leia a transcrição (com os tempos e os créditos de quem canta/aparece) e olhe os quadros do vídeo.\n"
    "- Descubra a obra (anime/filme/série) e o assunto do vídeo.\n"
    "- Sugira de 6 a 10 personagens, misturando: (a) 'da_obra' — personagens da PRÓPRIA obra que têm ligação com o que "
    "acontece no vídeo (o vilão reagindo à própria música, o rival, quem morreu na cena…); (b) 'hypado' — personagens "
    "muito populares/hypados na internet agora que geram engajamento e boas piadas; (c) 'contraste' — 1 ou 2 de fora que "
    "reagem de um jeito engraçado/oposto. Diga o MOTIVO de cada um em 1 frase (a dinâmica que ele traz pro roteiro).\n"
    "- cronologia: EM QUE PONTO DA HISTÓRIA dele o personagem está assistindo e se o que acontece no vídeo é ANTES, "
    "DURANTE ou DEPOIS disso (ex.: 'Itachi já morreu quando isso acontece — vê pela 1ª vez'; 'Ichigo viveu essa guerra — "
    "lembra'; 'de outra obra — não sabe nada'). relacoes: se ele JÁ INTERAGIU com quem aparece/canta no vídeo (lutou, "
    "foi aluno, matou, foi morto, é parente…) — ou 'nenhuma'. Se não tiver CERTEZA de um fato da obra, escreva "
    "'(não tenho certeza)' junto — vai pro verificador de fatos.\n"
    "- personalidade: 1–2 frases de como ele é; jeito_de_falar: bordões, gírias, como xinga/elogia; aparencia_en: em "
    "INGLÊS, a aparência para desenhar (cabelo, olhos, roupa, acessórios, cores) — sem o nome da obra; busca_imagem: o "
    "termo para achar uma imagem oficial dele no Google Imagens; estilo: 'anime' (personagem de anime/desenho/jogo) ou "
    "'realista' (pessoa real/ator/personagem de série live-action).\n"
    "- estilo (geral): 'anime' se o react tem personagens de anime/desenho; 'realista' só se forem todos pessoas reais.\n"
    "- Escreva em português do Brasil (menos aparencia_en)."
)


def _contexto_video(p: Dict[str, Any]) -> str:
    v = p.get("video") or {}
    partes = [f"TÍTULO DO VÍDEO: {p.get('titulo') or ''}"]
    if v.get("nome") and v.get("nome") != p.get("titulo"):
        partes.append(f"NOME DO ARQUIVO/VÍDEO: {v['nome']}")
    if v.get("url"):
        partes.append(f"LINK: {v['url']}")
    if v.get("duracao"):
        partes.append(f"DURAÇÃO: {mmss(v['duracao'])} ({float(v['duracao']):.0f} s)")
    if p.get("obra"):
        partes.append(f"OBRA (informada por você): {p['obra']}")
    if p.get("contexto"):
        partes.append(f"CONTEXTO / PEDIDOS: {p['contexto']}")
    partes.append("TRANSCRIÇÃO (tempo no vídeo):\n" + (transcricao_texto(p["transcricao"]) or "(sem transcrição)"))
    return "\n".join(partes)


def prompt_sugestoes(p: Dict[str, Any]) -> str:
    ja = [c["nome"] for c in p["personagens"]]
    extra = f"\nJÁ ESCOLHIDOS (não repita, sugira OUTROS que combinem com eles): {', '.join(ja)}" if ja else ""
    return _contexto_video(p) + extra


def _limpar_fichas(lista: Any) -> List[Dict[str, Any]]:
    out = []
    for x in lista or []:
        if not isinstance(x, dict) or not str(x.get("nome") or "").strip():
            continue
        out.append({k: " ".join(str(x.get(k) or "").split())[:600] for k in _CAMPOS_FICHA} | {"nome": " ".join(str(x["nome"]).split())[:80]})
    return out


def aplicar_sugestoes(p: Dict[str, Any], r: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(r, dict):
        raise ReactErro("A resposta não veio no formato esperado (um objeto JSON com \"personagens\").")
    sug = {"obra": str(r.get("obra") or "")[:200], "estilo": r.get("estilo") if r.get("estilo") in ("anime", "realista") else "anime",
           "resumo_video": str(r.get("resumo_video") or "")[:1500], "personagens": _limpar_fichas(r.get("personagens")),
           "quando": time.time()}
    if not sug["personagens"]:
        raise ReactErro("A IA não sugeriu nenhum personagem.")
    p["sugestoes"] = sug
    if not p.get("obra") and sug["obra"]:
        p["obra"] = sug["obra"]
    log(p, f"🤖 {len(sug['personagens'])} personagem(ns) sugerido(s)")
    return sug


def sugerir(pid: str, base: str = _BASE) -> Dict[str, Any]:
    p = carregar(pid, base)
    if not p["transcricao"] and not _video_local(p, base):
        raise ReactErro("Cole a transcrição (ou mande o vídeo) antes de pedir as sugestões.")
    conteudo = [{"type": "text", "text": prompt_sugestoes(p)}] + blocos_do_video(p, base, 18)
    r = _ia().chamar("react", SYS_SUGESTOES, conteudo, schema=SCHEMA_SUGESTOES, max_tokens=5000, effort="medium",
                     timeout=180, cache_local=False)
    if r is None:
        raise ReactErro("A IA não respondeu (desligada, sem crédito ou erro) — copie o prompt e cole a resposta de outra IA.")
    with _TRAVA:
        p = carregar(pid, base)
        sug = aplicar_sugestoes(p, r)
        salvar(p, base)
    return sug


def usar_sugestoes(p: Dict[str, Any], nomes: List[str], editados: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Os marcados entram no elenco (com a ficha da IA; o nome pode ter sido trocado na tela)."""
    novos = []
    for x in (p.get("sugestoes") or {}).get("personagens") or []:
        if x["nome"] not in nomes:
            continue
        ed = (editados or {}).get(x["nome"]) or {}
        nome = str(ed.get("nome") or x["nome"]).strip()
        if any(_norm(c["nome"]) == _norm(nome) for c in p["personagens"]):
            continue
        mudou_nome = _norm(nome) != _norm(x["nome"])
        campos = {} if mudou_nome else {k: x.get(k) for k in CAMPOS_FICHA_TXT + ("estilo", "motivo")}
        c = novo_personagem(p, nome, origem="manual" if mudou_nome else "ia", **campos)
        novos.append(c)
    if novos:
        log(p, f"🧑‍🤝‍🧑 {len(novos)} sugerido(s) no elenco: " + ", ".join(c["nome"] for c in novos))
    return novos


SYS_FICHAS = (
    "Você monta a ficha de personagens famosos (anime, desenho, jogo, filme, série ou pessoa real) para um vídeo de REACT "
    "estilo Gacha Life. Para cada nome: obra, personalidade (1–2 frases), jeito_de_falar (bordões, gírias), "
    "cronologia (em que ponto da história dele está e se o que o vídeo mostra é ANTES, DURANTE ou DEPOIS — ex.: 'já "
    "morreu quando isso acontece, vê pela 1ª vez'), relacoes (se já interagiu com quem aparece/canta no vídeo, ou "
    "'nenhuma'; '(não tenho certeza)' quando não souber), "
    "aparencia_en (em INGLÊS: cabelo, olhos, roupa marcante, acessórios, cores — para desenhar), busca_imagem (termo do "
    "Google Imagens), estilo ('anime' ou 'realista'). Mantenha o NOME exatamente como veio. Português do Brasil."
)


def prompt_fichas(p: Dict[str, Any], cids: List[str]) -> str:
    nomes = [personagem(p, c)["nome"] + (f" (obra: {personagem(p, c)['obra']})" if personagem(p, c).get("obra") else "") for c in cids]
    creditos = sorted({e["texto"] for e in p["transcricao"] if e["tipo"] == "credito"})
    return (f"VÍDEO DO REACT: {p.get('titulo') or ''}" + (f" — obra: {p['obra']}" if p.get("obra") else "")
            + (f"\nQUEM APARECE/CANTA NO VÍDEO (créditos na tela): {', '.join(creditos)[:1500]}" if creditos else "")
            + (f"\nRESUMO DO VÍDEO: {(p.get('sugestoes') or {}).get('resumo_video')}" if (p.get("sugestoes") or {}).get("resumo_video") else "")
            + "\nPERSONAGENS:\n" + "\n".join(f"- {n}" for n in nomes))


def aplicar_fichas(p: Dict[str, Any], r: Any, cids: List[str]) -> int:
    fichas = _limpar_fichas((r or {}).get("personagens") if isinstance(r, dict) else r)
    n = 0
    for cid in cids:
        c = personagem(p, cid)
        f = next((x for x in fichas if _norm(x["nome"]) == _norm(c["nome"])), None) \
            or next((x for x in fichas if _norm(x["nome"]) in _norm(c["nome"]) or _norm(c["nome"]) in _norm(x["nome"])), None)
        if not f:
            continue
        for k in CAMPOS_FICHA_TXT + ("estilo",):
            if f.get(k) and not str(c.get(k) or "").strip():
                c[k] = f[k]
        n += 1
    return n


def completar_fichas(pid: str, base: str = _BASE, cids: Optional[List[str]] = None) -> int:
    """🤖 Os personagens que VOCÊ digitou ganham personalidade, aparência e o termo de busca."""
    p = carregar(pid, base)
    cids = cids or [c["id"] for c in p["personagens"] if not c.get("personalidade") or not c.get("aparencia_en")]
    if not cids:
        return 0
    r = _ia().chamar("react", SYS_FICHAS, prompt_fichas(p, cids), schema=SCHEMA_FICHAS, max_tokens=3000, timeout=120)
    if r is None:
        raise ReactErro("A IA não respondeu — preencha a ficha à mão ou cole a resposta de outra IA.")
    with _TRAVA:
        p = carregar(pid, base)
        n = aplicar_fichas(p, r, [c for c in cids if any(x["id"] == c for x in p["personagens"])])
        log(p, f"🤖 ficha de {n} personagem(ns) completada")
        salvar(p, base)
    return n


def _schema_roteiro(exprs: List[str]) -> Dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False, "required": ["resumo", "falas"],
        "properties": {
            "resumo": {"type": "string"},
            "falas": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["tempo", "personagem", "texto", "expressao", "pedido_inscricao", "reacoes", "duvida"],
                "properties": {
                    "tempo": {"type": "number"}, "personagem": {"type": "string"}, "texto": {"type": "string"},
                    "expressao": {"type": "string", "enum": exprs}, "pedido_inscricao": {"type": "boolean"},
                    "duvida": {"type": "string"},
                    "reacoes": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                           "required": ["personagem", "expressao"],
                                                           "properties": {"personagem": {"type": "string"},
                                                                          "expressao": {"type": "string", "enum": exprs}}}},
                }}},
        },
    }


def sys_roteiro(p: Dict[str, Any]) -> str:
    exprs = p.get("expressoes") or EXPRESSOES_PADRAO
    passo = DENSIDADES.get(p.get("densidade") or "normal", 9.0)
    return (
        "Você escreve o ROTEIRO de um vídeo de REACT estilo Gacha Life: os personagens abaixo estão sentados no sofá "
        "assistindo ao vídeo na TV. As falas aparecem ESCRITAS embaixo da TV (como legenda, uma de cada vez) — não tem voz.\n"
        "Como escrever:\n"
        "- ANALISE a transcrição (com o tempo de cada frase) e os quadros do vídeo (o tempo está escrito em amarelo em "
        "cada quadro) e reaja ao que está ACONTECENDO naquele segundo: a frase da letra, a cena, o golpe, a revelação.\n"
        "- Cada personagem fala com a PERSONALIDADE e o JEITO DE FALAR dele, e reage ao que o vídeo diz sobre ele ou "
        "sobre gente que ele conhece (o vilão se defende, o rival provoca, o fã fica hypado, o de fora não entende nada). "
        "Entre eles: provocações, discussões, piadas internas da obra, memes — tudo curto e engraçado, como os reacts do "
        "YouTube. Pode ter briga e zoeira, mas sem ofensa pesada.\n"
        f"- Mais ou menos uma fala a cada {passo:.0f} segundos (não precisa ser regular — mais falas nos momentos fortes, "
        "silêncio quando a cena fala sozinha). Nada de fala antes do primeiro segundo com conteúdo.\n"
        "- 'texto' = SÓ o que o personagem diz — sem numerar (nada de 'Fala 1:'), sem o nome dele na frente (o balão já "
        "mostra 'Nome:'), sem aspas.\n"
        "- Cada fala: no máximo ~22 palavras (cabe em 2–3 linhas embaixo da TV). 'tempo' = o segundo do vídeo em que a "
        "fala aparece (número, ex.: 73.5) — logo DEPOIS do que ela comenta.\n"
        "- 'expressao' = a cara de quem fala naquele momento, de acordo com a personalidade e o que ele está sentindo: "
        f"uma de {', '.join(exprs)}. Varie — não use a mesma o tempo todo.\n"
        "- 'reacoes' = 0 a 2 outros personagens que mudam a cara ao ouvir/ver (ex.: um fica chocado com o que o outro "
        "disse). Só quando faz sentido.\n"
        "- O roteiro é escrito em PARTES (trechos de poucos minutos): escreva SÓ as falas do trecho pedido, com 'tempo' "
        "DENTRO dele, cobrindo o trecho INTEIRO até o fim (não pare no meio), e continue a conversa das falas anteriores "
        "sem repetir piadas nem bordões já usados.\n"
        "- PEDIDO DE LIKE/INSCRIÇÃO: 1 fala no vídeo todo (no máximo 2 num vídeo longo), dita por UM dos personagens, no "
        "jeito dele e ligada ao momento — marque 'pedido_inscricao': true. Siga o que o pedido diz sobre ESTA parte "
        "(colocar aqui ou não). Não existe corte de 'inscreva-se': o pedido é só essa fala.\n"
        "- CRONOLOGIA E RELAÇÕES (muito importante): cada personagem só LEMBRA do que viveu até o ponto da história dele "
        "(veja 'cronologia' no elenco). Se o que o vídeo mostra acontece DEPOIS do ponto dele, ele reage como quem vê pela "
        "1ª vez (surpresa, spoiler, 'eu morri?!'); se ele VIVEU aquilo, pode lembrar e comentar de dentro ('eu estava lá'). "
        "Use as relações (quem lutou com quem, quem matou quem, mestre/aluno, família) para as falas mais fortes. Não "
        "invente encontros que não aconteceram na obra.\n"
        "- 'duvida': se a fala depende de um fato da obra (quem conheceu quem, antes/depois, nome de técnica, quem morreu) "
        "e você NÃO tem certeza, escreva a dúvida aqui (ex.: 'não sei se o Itachi conheceu o Madara antes da guerra') — "
        "vai pro verificador de fatos. Com certeza: deixe \"\".\n"
        "- 'personagem' = o NOME exatamente como está no elenco.\n"
        f"- Escreva as falas em {p.get('idioma') or 'português do Brasil'}.\n"
        "- 'resumo' = 1–2 frases sobre o vídeo e a dinâmica do react."
    )


def prompt_roteiro(p: Dict[str, Any]) -> str:
    elenco = []
    for c in p["personagens"]:
        elenco.append(f"- {c['nome']}" + (f" ({c['obra']})" if c.get("obra") else "")
                      + (f": {c['personalidade']}" if c.get("personalidade") else "")
                      + (f" | jeito de falar: {c['jeito_de_falar']}" if c.get("jeito_de_falar") else "")
                      + (f" | cronologia: {c['cronologia']}" if c.get("cronologia") else "")
                      + (f" | relações com o vídeo: {c['relacoes']}" if c.get("relacoes") else ""))
    resumo = (p.get("sugestoes") or {}).get("resumo_video") or ""
    return (_contexto_video(p) + (f"\nRESUMO DO VÍDEO: {resumo}" if resumo else "")
            + "\n\nELENCO (sentados no sofá, nesta ordem da esquerda pra direita):\n" + "\n".join(elenco))


PARTE_S = 150.0  # o roteiro sai em partes de ~2,5 min (num pedido só, a IA parava no meio de vídeos longos)


def duracao_total(p: Dict[str, Any]) -> float:
    d = float((p.get("video") or {}).get("duracao") or 0)
    if d <= 0:
        d = max([float(e.get("fim") or e.get("ini") or 0) for e in p.get("transcricao") or [] if e.get("ini") is not None] or [0])
    return d


def partes_roteiro(p: Dict[str, Any]) -> List[List[float]]:
    dur = duracao_total(p)
    if dur <= 0:
        return [[0.0, 1e6]]
    n = max(1, int(round(dur / PARTE_S)))
    tam = dur / n
    return [[round(k * tam, 2), round(dur if k == n - 1 else (k + 1) * tam, 2)] for k in range(n)]


def estado_partes(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Cada parte com quantas falas tem e quantas deveria ter (pela quantidade de falas escolhida)."""
    passo = DENSIDADES.get(p.get("densidade") or "normal", 9.0)
    falas = (p.get("roteiro") or {}).get("falas") or []
    out = []
    for k, (a, b) in enumerate(partes_roteiro(p)):
        n = sum(1 for f in falas if a <= float(f["t"]) < b or (k == len(out) and float(f["t"]) >= b and b >= duracao_total(p) - 0.01))
        esperado = max(1, int(round((b - a) / passo)))
        out.append({"k": k, "ini": a, "fim": b, "falas": n, "esperado": esperado,
                    "vazia": n < max(1, esperado * 0.35)})
    return out


def _cta_aqui(p: Dict[str, Any], k: int) -> bool:
    """O pedido de inscrição vai na parte que tem ~25% do vídeo (se ainda não tem um fora dela)."""
    ps = partes_roteiro(p)
    a, b = ps[k]
    if any(f.get("cta") and not (a <= float(f["t"]) < b) for f in (p.get("roteiro") or {}).get("falas") or []):
        return False
    alvo = duracao_total(p) * 0.25
    return a <= alvo < b or (k == 0 and len(ps) == 1)


def prompt_roteiro_parte(p: Dict[str, Any], k: int) -> str:
    ps = partes_roteiro(p)
    if not 0 <= k < len(ps):
        raise ReactErro("Parte inexistente.")
    a, b = ps[k]
    passo = DENSIDADES.get(p.get("densidade") or "normal", 9.0)
    v = p.get("video") or {}
    trans = [e for e in p["transcricao"] if e.get("ini") is None or (a - 12 <= e["ini"] < b + 4)]
    falas = (p.get("roteiro") or {}).get("falas") or []
    nomes = {c["id"]: c["nome"] for c in p["personagens"]}
    antes = [f for f in falas if float(f["t"]) < a][-10:]
    depois = [f for f in falas if float(f["t"]) >= b][:4]
    L = [f"TÍTULO DO VÍDEO: {p.get('titulo') or ''}"]
    if v.get("duracao"):
        L.append(f"DURAÇÃO DO VÍDEO: {mmss(v['duracao'])}")
    if p.get("obra"):
        L.append(f"OBRA: {p['obra']}")
    if p.get("contexto"):
        L.append(f"CONTEXTO / PEDIDOS: {p['contexto']}")
    if (p.get("sugestoes") or {}).get("resumo_video"):
        L.append(f"RESUMO DO VÍDEO: {p['sugestoes']['resumo_video']}")
    creditos = sorted({e["texto"] for e in p["transcricao"] if e["tipo"] == "credito"})
    if creditos:
        L.append("QUEM APARECE/CANTA NO VÍDEO TODO: " + ", ".join(creditos)[:1200])
    L += ["", "ELENCO (sentados no sofá, nesta ordem da esquerda pra direita):"]
    for c in p["personagens"]:
        L.append(f"- {c['nome']}" + (f" ({c['obra']})" if c.get("obra") else "")
                 + (f": {c['personalidade']}" if c.get("personalidade") else "")
                 + (f" | jeito de falar: {c['jeito_de_falar']}" if c.get("jeito_de_falar") else "")
                 + (f" | cronologia: {c['cronologia']}" if c.get("cronologia") else "")
                 + (f" | relações com o vídeo: {c['relacoes']}" if c.get("relacoes") else ""))
    L += ["", f"## ESTA É A PARTE {k + 1} DE {len(ps)}: do {mmss(a)} ({a:.0f} s) ao {mmss(b)} ({b:.0f} s)",
          f"Escreva umas {max(1, int(round((b - a) / passo)))} falas, com 'tempo' entre {a:.0f} e {b:.0f}, cobrindo o trecho "
          "inteiro até o fim dele.",
          ("PEDIDO DE INSCRIÇÃO: coloque NESTA parte (1 fala, num bom momento)." if _cta_aqui(p, k)
           else "PEDIDO DE INSCRIÇÃO: NÃO coloque nesta parte (fica em outra)."),
          "", "TRANSCRIÇÃO DESTE TRECHO (tempo no vídeo):", transcricao_texto(trans, 12000) or "(sem transcrição — use os quadros)"]
    if antes:
        L += ["", "O QUE JÁ FOI FALADO LOGO ANTES (continue a conversa, não repita):"]
        L += [f"- {mmss(f['t'])} {nomes.get(f['cid'], '?')}: {f['texto']}" for f in antes]
    if depois:
        L += ["", "O QUE VEM LOGO DEPOIS (não contradiga):"]
        L += [f"- {mmss(f['t'])} {nomes.get(f['cid'], '?')}: {f['texto']}" for f in depois]
    return "\n".join(L)


def prompt_copiar(p: Dict[str, Any], tipo: str, parte: Optional[int] = None) -> str:
    """O prompt inteiro pra colar em outra IA (sem os quadros do vídeo) + o formato da resposta."""
    if tipo == "sugestoes":
        sis, txt, sch = SYS_SUGESTOES, prompt_sugestoes(p), SCHEMA_SUGESTOES
    elif tipo == "fichas":
        cids = [c["id"] for c in p["personagens"]]
        sis, txt, sch = SYS_FICHAS, prompt_fichas(p, cids), SCHEMA_FICHAS
    else:
        txt = prompt_roteiro_parte(p, parte) if parte is not None else prompt_roteiro(p)
        sis, sch = sys_roteiro(p), _schema_roteiro(p.get("expressoes") or EXPRESSOES_PADRAO)
    return (sis + "\n\n" + txt + "\n\nResponda SÓ com um JSON neste formato (JSON Schema):\n"
            + json.dumps(sch, ensure_ascii=False))


_RE_NUMERACAO = re.compile(r"^\s*(?:(?:fala|linha|line|cena)\s*(?:n[úu]mero|n[º°o]\.?|#)?\s*\d+\s*[:.)\-–—]*|#\s*\d+\s*[:.)\-–—]*|\d+\s*[:.)\-–—]+)\s*", re.I)


def limpar_texto_fala(texto: Any, nome: str = "") -> str:
    """O balão é só "Nome: fala" — tira numeração ("Fala número 3:", "#3", "3.") e o nome repetido no começo."""
    t = " ".join(str(texto or "").split())
    for _ in range(2):
        t = _RE_NUMERACAO.sub("", t, count=1)
        if nome and _norm(t[:len(nome) + 1]).startswith(_norm(nome)) and t[len(nome):len(nome) + 2].strip().startswith(":"):
            t = t[len(nome):].lstrip(" :")
    return t.strip().strip('"“”').strip()


def duracao_fala(texto: str) -> float:
    n = len(str(texto or "").split())
    return round(max(2.2, min(7.0, 1.5 + 0.36 * n)), 2)


def garantir_cta(p: Dict[str, Any]) -> bool:
    """A IA esqueceu o pedido de inscrição: o personagem que mais fala pede, lá pelo primeiro quarto do vídeo."""
    falas = (p.get("roteiro") or {}).get("falas") or []
    if not falas or any(f.get("cta") for f in falas):
        return False
    cont: Dict[str, int] = {}
    for f in falas:
        cont[f["cid"]] = cont.get(f["cid"], 0) + 1
    quem = max(cont, key=lambda k: cont[k])
    alvo = falas[min(len(falas) - 1, max(0, len(falas) // 4))]
    texto = "Pausa rápida: se tá curtindo o react, deixa o like e se inscreve no canal!"
    falas.append({"id": "f" + secrets.token_hex(3), "t": round(alvo["t"] + alvo["dur"] + 0.3, 2), "cid": quem, "cta": True,
                  "reacoes": [], "texto": texto, "expressao": "empolgado", "dur": duracao_fala(texto), "duvida": ""})
    falas.sort(key=lambda f: f["t"])
    return True


def aplicar_roteiro(p: Dict[str, Any], r: Any, janela: Optional[List[float]] = None) -> Dict[str, Any]:
    """A resposta da IA (ou colada) → as falas do projeto: o nome casado com o elenco, o tempo no vídeo, a
    expressão válida, o tempo de leitura. Com `janela` (uma parte): troca só as falas daquele trecho. Sem janela
    (o roteiro inteiro): garante 1 pedido de inscrição."""
    if isinstance(r, list):
        r = {"falas": r}
    if not isinstance(r, dict) or not isinstance(r.get("falas"), list):
        raise ReactErro("A resposta precisa ter a lista \"falas\".")
    if not p["personagens"]:
        raise ReactErro("Monte o elenco antes do roteiro.")
    exprs = set(EXPRESSOES)
    dur_video = float((p.get("video") or {}).get("duracao") or 0) or None
    falas = []
    ignoradas = 0
    for x in r["falas"]:
        if not isinstance(x, dict):
            continue
        c = achar_por_nome(p, str(x.get("personagem") or ""))
        texto = limpar_texto_fala(x.get("texto"), (c or {}).get("nome") or "")[:300]
        t = segundos(x.get("tempo"))
        if not c or not texto or t is None:
            ignoradas += 1
            continue
        if dur_video:
            t = min(max(0.0, t), max(0.0, dur_video - 1.5))
        if janela:
            if t < janela[0] - 5 or t > janela[1] + 5:  # bem fora do trecho: a IA errou a parte
                ignoradas += 1
                continue
            t = min(max(t, janela[0]), max(janela[0], janela[1] - 0.3))
        ex = _slug(x.get("expressao")) if _slug(x.get("expressao")) in exprs else "neutro"
        reacoes = []
        for y in x.get("reacoes") or []:
            cy = achar_por_nome(p, str((y or {}).get("personagem") or "")) if isinstance(y, dict) else None
            ey = _slug((y or {}).get("expressao")) if isinstance(y, dict) else ""
            if cy and cy["id"] != c["id"] and ey in exprs and all(z["cid"] != cy["id"] for z in reacoes):
                reacoes.append({"cid": cy["id"], "expressao": ey})
        falas.append({"id": "f" + secrets.token_hex(3), "t": round(t, 2), "cid": c["id"], "texto": texto, "expressao": ex,
                      "dur": duracao_fala(texto), "cta": bool(x.get("pedido_inscricao")), "reacoes": reacoes[:2],
                      "duvida": " ".join(str(x.get("duvida") or "").split())[:300]})
    if not falas:
        raise ReactErro("Nenhuma fala aproveitável (confira os nomes dos personagens).")
    falas.sort(key=lambda f: f["t"])
    if janela:
        a, b = janela
        antigas = (p.get("roteiro") or {}).get("falas") or []
        ultima = b >= duracao_total(p) - 0.01
        ficam = [f for f in antigas if not (a <= float(f["t"]) < b or (ultima and float(f["t"]) >= b))]
        resumo = str(r.get("resumo") or "") if not (p.get("roteiro") or {}).get("resumo") else p["roteiro"]["resumo"]
        p["roteiro"] = dict(p.get("roteiro") or {}, resumo=resumo[:1000], quando=time.time(), ignoradas=ignoradas,
                            falas=sorted(ficam + falas, key=lambda f: f["t"]))
        log(p, f"📝 roteiro, {mmss(a)}–{mmss(b)}: {len(falas)} fala(s)" + (f" · {ignoradas} ignorada(s)" if ignoradas else ""))
        return p["roteiro"]
    p["roteiro"] = {"resumo": str(r.get("resumo") or "")[:1000], "falas": falas, "quando": time.time(), "ignoradas": ignoradas}
    garantir_cta(p)
    log(p, f"📝 roteiro: {len(p['roteiro']['falas'])} fala(s)" + (f" · {ignoradas} ignorada(s) (nome que não está no elenco)" if ignoradas else ""))
    return p["roteiro"]


def gerar_roteiro(pid: str, base: str = _BASE, parte: Optional[int] = None, so_vazias: bool = False,
                  on_log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """🤖 O roteiro em PARTES de ~2,5 min (cada uma com a transcrição e os quadros do trecho dela e as falas de antes,
    pra continuar a conversa). Cada parte pronta já é salva. `parte` = só uma; `so_vazias` = só as que faltam."""
    p = carregar(pid, base)
    if not p["personagens"]:
        raise ReactErro("Monte o elenco antes do roteiro.")
    if not p["transcricao"] and not _video_local(p, base):
        raise ReactErro("Cole a transcrição (ou mande o vídeo) antes.")
    exprs = p.get("expressoes") or EXPRESSOES_PADRAO
    ps = partes_roteiro(p)
    if parte is not None:
        alvo = [parte] if 0 <= parte < len(ps) else []
    elif so_vazias:
        alvo = [x["k"] for x in estado_partes(p) if x["vazia"]]
    else:
        alvo = list(range(len(ps)))
    if not alvo:
        return {"feitas": 0, "erros": [], "falas": len((p.get("roteiro") or {}).get("falas") or []), "msg": "nenhuma parte faltando"}
    feitas, erros = 0, []
    for n, k in enumerate(alvo, 1):
        a, b = ps[k]
        on_log(f"parte {n} de {len(alvo)} ({mmss(a)}–{mmss(b)})…")
        p = carregar(pid, base)
        conteudo = [{"type": "text", "text": prompt_roteiro_parte(p, k)}] + blocos_do_video(p, base, 9, a, b)
        r = None
        for _tentativa in range(2):
            r = _ia().chamar("react", sys_roteiro(p), conteudo, schema=_schema_roteiro(exprs), max_tokens=8000,
                             effort="medium", timeout=240, cache_local=False)
            if r is not None and isinstance(r, dict) and r.get("falas"):
                break
        if r is None:
            erros.append(f"{mmss(a)}–{mmss(b)}")
            continue
        with _TRAVA:
            p = carregar(pid, base)
            try:
                aplicar_roteiro(p, r, janela=[a, b])
                feitas += 1
            except ReactErro as exc:
                erros.append(f"{mmss(a)}–{mmss(b)} ({exc})")
            salvar(p, base)
    with _TRAVA:
        p = carregar(pid, base)
        if garantir_cta(p):
            log(p, "📣 a IA não pôs o pedido de inscrição — entrou uma fala padrão (troque se quiser)")
        salvar(p, base)
    total = len((p.get("roteiro") or {}).get("falas") or [])
    if not feitas:
        raise ReactErro("A IA não respondeu (desligada, sem crédito ou erro) — copie o prompt de cada parte e cole a resposta "
                        "de outra IA." + (f" Faltaram: {', '.join(erros)}" if erros else ""))
    return {"feitas": feitas, "erros": erros, "falas": total,
            "msg": f"{feitas} parte(s), {total} fala(s)" + (f" · ⚠ faltaram {', '.join(erros)} — use 🤖 Completar" if erros else "")}


def ajustar_falas(falas: List[Dict[str, Any]], dur_video: Optional[float] = None) -> List[Dict[str, Any]]:
    """Uma legenda de cada vez: se uma fala começa antes de a anterior sair, a anterior encurta (até 1,4 s) e,
    se não der, a seguinte espera."""
    out = [dict(f) for f in sorted(falas, key=lambda f: float(f["t"]))]
    for a, b in zip(out, out[1:]):
        fim_a = float(a["t"]) + float(a["dur"])
        if fim_a > float(b["t"]) - 0.08:
            curto = float(b["t"]) - 0.08 - float(a["t"])
            if curto >= 1.4:
                a["dur"] = round(curto, 2)
            else:
                a["dur"] = max(a["dur"], 1.4) if curto < 1.4 else a["dur"]
                b["t"] = round(float(a["t"]) + float(a["dur"]) + 0.08, 2)
    if dur_video:
        for f in out:
            f["dur"] = round(max(0.5, min(float(f["dur"]), dur_video - float(f["t"]))), 2)
        out = [f for f in out if float(f["t"]) < dur_video - 0.4]
    return out


# ------------------------------------------------------------------ 🔎 verificador de fatos (lore, cronologia, personalidade)
ALVOS_CHECAGEM = {"tudo": "fichas + roteiro", "fichas": "só as fichas dos personagens", "roteiro": "só as falas"}
SCHEMA_CHECAGEM = {
    "type": "object", "additionalProperties": False, "required": ["fichas", "falas", "conferidos", "resumo"],
    "properties": {
        "fichas": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                              "required": ["personagem", "campo", "para", "problema", "fonte"],
                                              "properties": {"personagem": {"type": "string"},
                                                             "campo": {"type": "string", "enum": list(CAMPOS_FICHA_TXT[:6])},
                                                             "para": {"type": "string"}, "problema": {"type": "string"},
                                                             "fonte": {"type": "string"}}}},
        "falas": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                             "required": ["id", "para", "expressao", "problema", "fonte"],
                                             "properties": {"id": {"type": "string"}, "para": {"type": "string"},
                                                            "expressao": {"type": "string"}, "problema": {"type": "string"},
                                                            "fonte": {"type": "string"}}}},
        "conferidos": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                  "required": ["item", "nota"],
                                                  "properties": {"item": {"type": "string"}, "nota": {"type": "string"}}}},
        "resumo": {"type": "string"},
    },
}


def prompt_checagem(p: Dict[str, Any], alvo: str = "tudo", foco: str = "") -> str:
    """O prompt do 🔎 verificador: pra uma IA com busca na internet (Gemini com o Google, ChatGPT/Perplexity) ou a IA do
    site. Confere a lore da obra — quem conheceu quem, o que acontece ANTES/DEPOIS (cronologia), nomes, mortes,
    técnicas — e a personalidade de cada um; devolve as correções (você aceita uma a uma)."""
    alvo = alvo if alvo in ALVOS_CHECAGEM else "tudo"
    if not p["personagens"]:
        raise ReactErro("Monte o elenco antes de checar.")
    falas = (p.get("roteiro") or {}).get("falas") or []
    if alvo == "roteiro" and not falas:
        raise ReactErro("Ainda não tem roteiro pra checar.")
    nomes = {c["id"]: c["nome"] for c in p["personagens"]}
    creditos = sorted({e["texto"] for e in p["transcricao"] if e["tipo"] == "credito"})
    L = ["Você é um CHECADOR DE FATOS de LORE (anime, mangá, filme, série, jogo) com acesso à INTERNET (wikis oficiais e de fãs "
         "como Fandom, sites oficiais, Wikipedia). O material é de um vídeo de REACT estilo Gacha Life: personagens famosos sentados "
         "num sofá assistindo a um vídeo numa TV e comentando (as falas aparecem escritas). É FICÇÃO e é comédia — personagens de "
         "obras diferentes juntos e a piada estão OK. O que NÃO pode é errar a obra.",
         "", "## O que conferir"]
    if alvo in ("tudo", "fichas"):
        L += ["- FICHAS: personalidade e jeito de falar batem com o personagem? A CRONOLOGIA está certa (o que o vídeo mostra "
              "acontece ANTES, DURANTE ou DEPOIS do ponto da história dele — ele viveu aquilo, morreu antes, ainda não sabe)? "
              "As RELAÇÕES estão certas (ele já interagiu/lutou/conviveu com quem aparece ou canta no vídeo, ou nunca se viram)? "
              "Corrija o campo errado com o texto inteiro novo (\"para\")."]
    if alvo in ("tudo", "roteiro"):
        L += ["- FALAS: contradizem a obra? Cronologia errada (lembra de algo que ainda não viveu, ou reage como novidade a algo que "
              "viveu)? Encontro/relação que não existiu? Nome de técnica, lugar, golpe, quem matou quem? Fala muito fora da "
              "personalidade? Corrija com o texto novo no MESMO tom e tamanho (\"para\"; \"\" = apagar a fala) e, se precisar, outra "
              "expressão (uma de: " + ", ".join(EXPRESSOES) + "; \"\" = manter). As falas com ⚠ DÚVIDA são prioridade.",
              "- Não mexa no humor nem no estilo do que está certo."]
    if foco:
        L.append(f"- Pedido extra (prioridade): {foco.strip()[:800]}")
    L += ["- Tudo o que você conferiu e está CERTO vai em \"conferidos\" (item = nome do personagem ou o id da fala) com uma nota curta.",
          "- \"fonte\": o link que confirma a correção (ou o nome da wiki/episódio).",
          "", "## O vídeo",
          f"Título: {p.get('titulo') or ''}" + (f" — obra: {p['obra']}" if p.get("obra") else ""),
          ]
    if (p.get("sugestoes") or {}).get("resumo_video"):
        L.append(f"Resumo: {p['sugestoes']['resumo_video']}")
    if creditos:
        L.append("Quem aparece/canta (créditos na tela): " + ", ".join(creditos)[:1500])
    if p["transcricao"]:
        L.append("Transcrição (resumida):\n" + transcricao_texto(p["transcricao"], 6000))
    L += ["", "## Fichas dos personagens"]
    for c in p["personagens"]:
        L.append(f"- {c['nome']}" + (f" ({c['obra']})" if c.get("obra") else "") + ":"
                 + "".join(f"\n    {k}: {c.get(k)}" for k in ("personalidade", "jeito_de_falar", "cronologia", "relacoes") if c.get(k)))
    if alvo in ("tudo", "roteiro") and falas:
        L += ["", "## Falas (id · segundo do vídeo · quem · cara: texto)"]
        for f in falas:
            L.append(f"- {f['id']} · {mmss(f['t'])} · {nomes.get(f['cid'], '?')} · {f.get('expressao')}: {f['texto']}"
                     + (f"   ⚠ DÚVIDA: {f['duvida']}" if f.get("duvida") else ""))
    L += ["", "## Resposta — SOMENTE um JSON válido, assim (sem texto antes ou depois):",
          json.dumps({"fichas": [{"personagem": "nome exato", "campo": "cronologia", "para": "o texto inteiro corrigido",
                                  "problema": "o que estava errado", "fonte": "https://…"}],
                      "falas": [{"id": "f1a2b3", "para": "a fala corrigida (ou \"\" pra apagar)", "expressao": "",
                                 "problema": "o que estava errado", "fonte": "https://…"}],
                      "conferidos": [{"item": "Itachi Uchiha", "nota": "cronologia certa: morre antes da guerra"}],
                      "resumo": "1-3 frases"}, ensure_ascii=False, indent=1)]
    return "\n".join(L)


def aplicar_checagem(p: Dict[str, Any], r: Any, origem: str, alvo: str = "tudo") -> Dict[str, Any]:
    """A resposta do verificador → a lista de correções pendentes (você aceita ou ignora cada uma)."""
    if not isinstance(r, dict):
        raise ReactErro("A resposta não veio no formato esperado (um objeto JSON com \"fichas\" e \"falas\").")
    falas = {f["id"]: f for f in (p.get("roteiro") or {}).get("falas") or []}
    itens: List[Dict[str, Any]] = []
    for x in r.get("fichas") or []:
        if not isinstance(x, dict):
            continue
        c = achar_por_nome(p, str(x.get("personagem") or ""))
        campo = str(x.get("campo") or "")
        para = " ".join(str(x.get("para") or "").split())[:600]
        if not c or campo not in CAMPOS_FICHA_TXT or not para or para == c.get(campo):
            continue
        itens.append({"id": "k" + secrets.token_hex(3), "tipo": "ficha", "cid": c["id"], "nome": c["nome"], "campo": campo,
                      "de": c.get(campo) or "", "para": para, "problema": str(x.get("problema") or "")[:400],
                      "fonte": str(x.get("fonte") or "")[:300], "estado": "pendente"})
    for x in r.get("falas") or []:
        if not isinstance(x, dict) or str(x.get("id") or "") not in falas:
            continue
        f = falas[str(x["id"])]
        para = " ".join(str(x.get("para") or "").split())[:300]
        ex = _slug(x.get("expressao")) if _slug(x.get("expressao")) in EXPRESSOES else ""
        if para == f["texto"] and (not ex or ex == f.get("expressao")):
            continue
        itens.append({"id": "k" + secrets.token_hex(3), "tipo": "fala", "fid": f["id"], "t": f["t"],
                      "nome": next((c["nome"] for c in p["personagens"] if c["id"] == f["cid"]), "?"),
                      "de": f["texto"], "para": para, "expressao": ex, "apagar": not para,
                      "problema": str(x.get("problema") or "")[:400], "fonte": str(x.get("fonte") or "")[:300], "estado": "pendente"})
    conf = [{"item": str(x.get("item") or "")[:80], "nota": str(x.get("nota") or "")[:300]}
            for x in r.get("conferidos") or [] if isinstance(x, dict) and x.get("item")]
    for x in conf:  # a dúvida da fala foi conferida e está certa
        if x["item"] in falas:
            falas[x["item"]]["duvida"] = ""
    p["checagem"] = {"quando": time.time(), "origem": origem, "alvo": alvo, "resumo": str(r.get("resumo") or "")[:1000],
                     "itens": itens, "conferidos": conf[:120]}
    log(p, f"🔎 verificador ({origem}): {len(itens)} correção(ões), {len(conf)} conferido(s)")
    return p["checagem"]


def resolver_checagem(p: Dict[str, Any], iid: str, acao: str) -> int:
    """✔ aplicar / ✕ ignorar uma correção ("*" = todas as pendentes). → quantas."""
    ch = p.get("checagem") or {}
    falas = (p.get("roteiro") or {}).get("falas") or []
    n = 0
    for it in ch.get("itens") or []:
        if it["estado"] != "pendente" or (iid != "*" and it["id"] != iid):
            continue
        if acao == "aplicar":
            if it["tipo"] == "ficha":
                c = next((x for x in p["personagens"] if x["id"] == it["cid"]), None)
                if c:
                    c[it["campo"]] = it["para"]
            else:
                f = next((x for x in falas if x["id"] == it["fid"]), None)
                if f and it.get("apagar"):
                    falas.remove(f)
                elif f:
                    f["texto"] = it["para"] or f["texto"]
                    f["dur"] = duracao_fala(f["texto"])
                    if it.get("expressao"):
                        f["expressao"] = it["expressao"]
                    f["duvida"] = ""
            it["estado"] = "aplicado"
        else:
            it["estado"] = "ignorado"
        n += 1
    if n:
        log(p, f"🔎 {n} correção(ões) {'aplicada(s)' if acao == 'aplicar' else 'ignorada(s)'}")
    return n


def checar(pid: str, base: str = _BASE, alvo: str = "tudo", foco: str = "", motor: str = "claude") -> int:
    """Roda o verificador: 🔷 Gemini (com a busca do Google) ou 🤖 a IA do site (sem internet — o que ela sabe da obra)."""
    p = carregar(pid, base)
    texto = prompt_checagem(p, alvo, foco)
    if motor == "gemini":
        import gemini_servico as gm
        import json_ia
        r = gm.checar(texto, rotulo="React: " + str(p.get("titulo") or "")[:60])
        try:
            dados = json_ia.carregar(str(r.get("texto") or ""), aceitar_cortado=True)
        except ValueError:
            raise ReactErro("O Gemini respondeu sem o JSON — tente de novo ou use outra IA.")
        fontes = [f.get("url") for f in r.get("fontes") or [] if f.get("url")]
        if isinstance(dados, dict) and fontes:
            dados.setdefault("resumo", "")
            dados["resumo"] = (str(dados["resumo"]) + " · fontes da busca: " + ", ".join(fontes[:5]))[:1000]
    else:
        dados = _ia().chamar("react", "Você é um checador de fatos de lore. Siga as instruções do usuário.", texto,
                             schema=SCHEMA_CHECAGEM, max_tokens=8000, effort="medium", timeout=240, cache_local=False)
        if dados is None:
            raise ReactErro("A IA não respondeu (desligada, sem crédito ou erro) — use o Gemini ou copie o prompt.")
    with _TRAVA:
        p = carregar(pid, base)
        ch = aplicar_checagem(p, dados, "🔷 Gemini + Google" if motor == "gemini" else "🤖 IA do site", alvo)
        salvar(p, base)
    return len(ch["itens"])


# ------------------------------------------------------------------ 🧍 personagens (poses no Flow)
def poses_json(p: Dict[str, Any], c: Dict[str, Any]) -> Dict[str, Any]:
    """O JSON de poses (personagens_pod_v1) do personagem SENTADO, uma pose por expressão."""
    est = estilo_final(p)
    exprs = [e for e in (p.get("expressoes") or EXPRESSOES_PADRAO) if e in EXPRESSOES]
    if "neutro" not in exprs:
        exprs = ["neutro"] + exprs
    sl = _slug(c["nome"])
    aparencia = c.get("aparencia_en") or f"the character {c['nome']}" + (f" from {c['obra']}" if c.get("obra") else "")
    trava = (f"CHARACTER LOCK: {c['nome']}" + (f" from {c['obra']}" if c.get("obra") else "") + f". Appearance: {aparencia}. "
             "Keep exactly the same face, hairstyle, eye color, outfit and colors in every image.")
    estilo = ("ART STYLE: " + ESTILO_TXT[est] + ("." if est == "anime" else ". Keep the person looking like the reference."))
    regras = ("Framing: the character is SITTING on an invisible seat as if on a couch, seen from the front, body turned "
              "slightly (three-quarters) toward the viewer's right as if watching a TV there; head, both arms, torso and the "
              "thighs/knees visible, cropped around the knees at the bottom edge; whole head and hair inside the image with "
              "margin. Do NOT draw the couch, chair, table, TV or any other object. ONE single figure, no text, no panels, "
              "on a flat solid chroma-key green background (#00FF00), no shadow on the background.")
    poses = []
    for k, e in enumerate(exprs):
        poses.append({"arquivo": f"{sl}_{e}.png", "tipo": "pose", "prioridade": 1 if k < 4 else 2, "grupo": "reacao",
                      "mestre": e == "neutro", "descricao_pt": f"sentado — {EXPRESSOES[e][0]}",
                      "prompt": f"sitting, {EXPRESSOES[e][1]}."})
    refs = {r: f"a reference picture of {c['nome']}" + (f" from {c['obra']}" if c.get("obra") else "") for r in c.get("refs") or []}
    return {"formato": "personagens_pod_v1", "personagem": sl, "nome": c["nome"], "react": True,
            "descricoes_referencias": refs, "texto_fixo": {"trava": trava, "estilo": estilo, "regras": regras},
            "fundo": "verde", "canvas": [1200, 1800], "altura_personagem": 0.95, "boca_auto": True,
            "flow": {"proporcao": "3:4"}, "poses": poses}


def _pp():
    import personagens_pod as pp
    return pp


def criar_poses(pid: str, cid: str, base: str = _BASE, refazer: bool = False) -> Dict[str, Any]:
    """Cria (ou reaproveita) o projeto 🧍 do personagem e manda a ⭐ neutra (a mestre) pro Flow. Quando ela fica
    pronta, `acompanhar` usa ela de mestre e manda o resto (as bocas seguem sozinhas)."""
    pp = _pp()
    with _TRAVA:
        p = carregar(pid, base)
        c = personagem(p, cid)
        dados = poses_json(p, c)
        refs = []
        for r in (c.get("refs") or [])[:2]:
            try:
                with open(os.path.join(pasta(pid, base), "refs", r), "rb") as f:
                    refs.append((r, f.read()))
            except OSError:
                continue
        if not refazer and not (c.get("pod") or {}).get("pid"):
            reaproveitar(p, c, base)  # ♻ já foi gerado num react anterior: usa o mesmo projeto 🧍
            dados = poses_json(p, c)
        pod = c.get("pod") or {}
        existe = None
        if pod.get("pid") and not refazer:
            try:
                existe = pp.carregar(pod["pid"], base)
            except pp.PersErro:
                existe = None
        if existe is None:
            np_ = pp.criar(f"🎭 {c['nome']} (react)", json.dumps(dados, ensure_ascii=False), refs, base=base, motor="flow")
            c["pod"] = {"pid": np_["id"], "fase": "mestre", "criado": time.time()}
        else:
            # as poses que o projeto já tinha (outras expressões de outro react, as bocas) continuam
            novos = {x["arquivo"] for x in dados["poses"]}
            dados["poses"] += [x for x in existe["dados"].get("poses") or [] if x["arquivo"] not in novos]
            dados["descricoes_referencias"] = dict(existe["dados"].get("descricoes_referencias") or {}, **dados["descricoes_referencias"])
            pp.trocar_json(pod["pid"], json.dumps(dados, ensure_ascii=False), base)
            c["pod"] = dict(pod, fase="resto" if existe.get("mestre") else (pod.get("fase") or "mestre"))
        ppid = c["pod"]["pid"]
        mestre = next(x["arquivo"] for x in dados["poses"] if x.get("mestre"))
        log(p, f"🧍 {c['nome']}: poses no Flow (a ⭐ neutra primeiro)")
        salvar(p, base)
    proj = pp.carregar(ppid, base)
    if proj.get("mestre"):
        c_fase = "resto"
        r = _mandar_resto(ppid, base)
    else:
        c_fase = "mestre"
        it = proj["imagens"].get(mestre) or {}
        r = pp.enviar(ppid, [mestre], "", base) if it.get("estado") not in ("fila", "gerando") and not pp.arquivo_atual(proj, mestre, base) else {"ok": True}
    with _TRAVA:
        p = carregar(pid, base)
        personagem(p, cid)["pod"]["fase"] = c_fase
        salvar(p, base)
    return {"ok": True, "pod": ppid, "aviso": (r or {}).get("aviso") or ""}


def ja_existente(nome: str, base: str = _BASE, fora: str = "") -> Dict[str, Any]:
    """♻ O personagem já foi feito num react anterior? → {"pod": o projeto 🧍 dele com mais poses prontas,
    "ficha": a ficha mais completa (personalidade, aparência, referências) de outro react}."""
    pp = _pp()
    n = _norm(nome)
    out: Dict[str, Any] = {}
    if not n:
        return out
    melhor = None
    for proj in pp.listar(base):
        d = proj.get("dados") or {}
        if not d.get("react") or _norm(d.get("nome")) != n:
            continue
        prontas = sum(1 for x in d.get("poses") or [] if x.get("tipo") == "pose" and pp.arquivo_atual(proj, x["arquivo"], base))
        if melhor is None or prontas > melhor[0]:
            melhor = (prontas, proj)
    if melhor:
        out["pod"] = {"pid": melhor[1]["id"], "prontas": melhor[0], "mestre": bool(melhor[1].get("mestre"))}
    raiz = pasta_raiz(base)
    melhor_f = None
    for rid in os.listdir(raiz) if os.path.isdir(raiz) else []:
        if rid == fora or not RE_ID.match(rid):
            continue
        try:
            outro = carregar(rid, base)
        except Exception:  # noqa: BLE001
            continue
        for c in outro["personagens"]:
            if _norm(c["nome"]) != n:
                continue
            nota = sum(1 for k in ("personalidade", "jeito_de_falar", "cronologia", "aparencia_en") if c.get(k)) + len(c.get("refs") or [])
            if melhor_f is None or nota > melhor_f[0]:
                melhor_f = (nota, rid, c)
    if melhor_f and melhor_f[0]:
        out["ficha"] = {"projeto": melhor_f[1], **{k: melhor_f[2].get(k) for k in CAMPOS_FICHA_TXT + ("estilo", "refs", "cor")}}
    return out


def reaproveitar(p: Dict[str, Any], c: Dict[str, Any], base: str = _BASE) -> str:
    """♻ Personagem que já foi gerado/usado antes: liga o projeto 🧍 com as poses prontas (não gera de novo) e completa
    a ficha e as imagens de referência com as do react anterior. → o que foi reaproveitado ("" = nada)."""
    ex = ja_existente(c["nome"], base, fora=p["id"])
    feito = []
    f = ex.get("ficha")
    if f:
        for k in CAMPOS_FICHA_TXT + ("estilo",):
            if k in ("cronologia", "relacoes"):
                continue  # a cronologia e as relações dependem do vídeo de cada react
            if f.get(k) and not str(c.get(k) or "").strip():
                c[k] = f[k]
        if not c.get("refs"):
            for r in (f.get("refs") or [])[:3]:
                cam = os.path.join(pasta(f["projeto"], base), "refs", r)
                if os.path.isfile(cam):
                    with open(cam, "rb") as fh:
                        try:
                            guardar_ref(p, c, fh.read(), base)
                        except ReactErro:
                            continue
        feito.append("a ficha")
    if ex.get("pod") and not (c.get("pod") or {}).get("pid"):
        c["pod"] = {"pid": ex["pod"]["pid"], "fase": "resto" if ex["pod"]["mestre"] else "mestre", "criado": time.time(),
                    "reaproveitado": True}
        feito.append(f"as {ex['pod']['prontas']} pose(s) já geradas")
    if feito:
        c["reaproveitado"] = " e ".join(feito)
        log(p, f"♻ {c['nome']} já existia: reaproveitei " + c["reaproveitado"])
    return c.get("reaproveitado") or ""


def _mandar_resto(ppid: str, base: str) -> Dict[str, Any]:
    pp = _pp()
    proj = pp.carregar(ppid, base)
    faltam = [x["arquivo"] for x in proj["dados"]["poses"] if x.get("tipo") == "pose"
              and (proj["imagens"].get(x["arquivo"]) or {}).get("estado") in ("nova", "erro", None)
              and not pp.arquivo_atual(proj, x["arquivo"], base)]
    if not faltam:
        # as bocas que faltam (as das poses que já existem)
        return pp.animar_todas(ppid, base)
    return pp.enviar(ppid, faltam, "", base)


def acompanhar(pid: str, base: str = _BASE) -> Dict[str, Any]:
    """⏱ Chamado pela página: sincroniza os projetos 🧍 com o Flow; a neutra ficou pronta → vira a ⭐ mestre e o resto
    vai pro Flow sozinho. Também acompanha as camadas do cenário."""
    pp = _pp()
    p = carregar(pid, base)
    avisos = []
    for c in p["personagens"]:
        pod = c.get("pod") or {}
        if not pod.get("pid"):
            continue
        try:
            r = pp.sincronizar(pod["pid"], base)
            if r.get("aviso"):
                avisos.append(f"{c['nome']}: {r['aviso']}")
            proj = pp.carregar(pod["pid"], base)
        except pp.PersErro as exc:
            avisos.append(f"{c['nome']}: {exc}")
            continue
        if pod.get("fase") == "mestre" and not proj.get("mestre"):
            mestre = next((x["arquivo"] for x in proj["dados"]["poses"] if x.get("mestre")), None)
            if mestre and pp.arquivo_atual(proj, mestre, base) and (proj["imagens"].get(mestre) or {}).get("estado") == "pronta":
                try:
                    pp.usar_como_mestre(pod["pid"], mestre, base)
                    _mandar_resto(pod["pid"], base)
                    with _TRAVA:
                        q = carregar(pid, base)
                        personagem(q, c["id"])["pod"]["fase"] = "resto"
                        log(q, f"⭐ {c['nome']}: a neutra virou a mestre — o resto das expressões foi pro Flow")
                        salvar(q, base)
                except Exception as exc:  # noqa: BLE001
                    avisos.append(f"{c['nome']}: {str(exc)[:160]}")
    try:
        acompanhar_cenario(pid, base)
    except Exception as exc:  # noqa: BLE001
        avisos.append(f"cenário: {str(exc)[:160]}")
    return {"avisos": avisos}


def poses_do_personagem(c: Dict[str, Any], base: str = _BASE) -> Dict[str, Dict[str, Optional[str]]]:
    """expressão → {"pose": caminho, "boca": caminho} (só as que já têm imagem)."""
    pod = c.get("pod") or {}
    if not pod.get("pid"):
        return {}
    pp = _pp()
    try:
        proj = pp.carregar(pod["pid"], base)
    except pp.PersErro:
        return {}
    sl = _slug(c["nome"])
    out: Dict[str, Dict[str, Optional[str]]] = {}
    for x in proj["dados"]["poses"]:
        if x.get("tipo") != "pose":
            continue
        e = x["arquivo"][len(sl) + 1:-4] if x["arquivo"].startswith(sl + "_") else x["arquivo"][:-4]
        cam = pp.arquivo_atual(proj, x["arquivo"], base)
        if not cam or (proj["imagens"].get(x["arquivo"]) or {}).get("estado") == "descartada":
            continue
        boca = next((y["arquivo"] for y in proj["dados"]["poses"] if y.get("tipo") == "boca" and y.get("base") == x["arquivo"]), None)
        out[e] = {"pose": cam, "boca": pp.arquivo_atual(proj, boca, base) if boca else None}
    return out


def estado_poses(c: Dict[str, Any], base: str = _BASE) -> Dict[str, Any]:
    pod = c.get("pod") or {}
    if not pod.get("pid"):
        return {"tem": False}
    pp = _pp()
    try:
        proj = pp.carregar(pod["pid"], base)
    except pp.PersErro:
        return {"tem": False, "erro": "o projeto 🧍 foi apagado"}
    itens = []
    for x in proj["dados"]["poses"]:
        it = proj["imagens"].get(x["arquivo"]) or {}
        itens.append({"arquivo": x["arquivo"], "tipo": x.get("tipo"), "estado": it.get("estado"), "erro": it.get("erro"),
                      "msg": it.get("msg"), "img": (it["versoes"][it["atual"]]["local"] if it.get("atual", -1) >= 0 and it.get("versoes") else None)})
    poses = [i for i in itens if i["tipo"] == "pose"]
    return {"tem": True, "pid": pod["pid"], "fase": pod.get("fase"), "mestre": bool(proj.get("mestre")),
            "prontas": sum(1 for i in poses if i["img"]), "total": len(poses),
            "bocas": sum(1 for i in itens if i["tipo"] == "boca" and i["img"]),
            "esperando": sum(1 for i in itens if i["estado"] in ("fila", "gerando")),
            "erros": sum(1 for i in itens if i["estado"] == "erro"), "itens": itens}


# ------------------------------------------------------------------ 🏠 cenário em camadas
def prompt_camada(p: Dict[str, Any], camada: str) -> str:
    est = estilo_final(p)
    sty = ESTILO_TXT[est]
    obra = (p.get("obra") or (p.get("sugestoes") or {}).get("obra") or "").strip()
    extra = str((p.get("cenario") or {}).get("pedido") or "").strip()
    n = max(1, len(p["personagens"]))
    if camada == "fundo":
        deco = (f"posters, figures and decorations inspired by {obra}" if obra else "anime posters, shelves with figures")
        return (f"Wide 16:9 background of a cozy streamer living room seen straight from the front: a textured wall with {deco}, "
                "a framed picture, LED strip lights, warm moody lighting; the lower third is plain floor. The middle of the "
                "image is EMPTY: NO people, NO sofa, NO couch, NO table, NO TV, NO furniture in front of the wall. "
                + (f"Extra: {extra}. " if extra else "") + sty + ".")
    if camada == "sofa":
        lugares = n if p.get("layout") != "dois_sofas" else max(1, math.ceil(n / 2))
        tam = "a long sectional sofa for " + str(lugares) + " people" if lugares >= 4 else f"a {max(2, lugares)}-seat sofa"
        return (f"{tam}, comfortable fabric couch with cushions, seen straight from the FRONT at eye level, the whole sofa "
                "visible with margin around it, empty (no people), isolated on a flat solid chroma-key green background "
                "(#00FF00), no floor, no shadow on the background, no other objects. " + sty + ".")
    return ("a long low wooden coffee table seen from the FRONT at eye level (we see its front edge and a bit of the top), "
            "with snacks on top: popcorn bowl, soda cans, chips, a game controller and a small microphone; the whole table "
            "visible with margin around it, isolated on a flat solid chroma-key green background (#00FF00), no floor, no "
            "shadow on the background, no people. " + sty + ".")


def gerar_camadas(pid: str, base: str = _BASE, quais: Optional[List[str]] = None) -> Dict[str, Any]:
    """🚀 Manda as camadas (fundo / sofá / mesa) pra fila do Flow em massa."""
    import flow_lote
    quais = [q for q in (quais or list(CAMADAS)) if q in CAMADAS]
    with _TRAVA:
        p = carregar(pid, base)
        itens = [{"prompt": prompt_camada(p, q)[:3900], "tipo": "imagem", "origem": "react"} for q in quais]
        lote = flow_lote.lote()
        try:
            novos = lote.adicionar(itens, proporcao="16:9", quantidade="x1")
        except ValueError as exc:
            raise ReactErro(str(exc))
        for q, j in zip(quais, novos):
            cam = p["cenario"]["camadas"].setdefault(q, {})
            cam.update(estado="fila", job=j["id"], erro=None, prompt=itens[quais.index(q)]["prompt"], msg="⏳ na fila do Flow")
        log(p, "🏠 " + ", ".join(ROTULO_CAMADA[q] for q in quais) + " pro Flow")
        salvar(p, base)
    aviso = ""
    try:
        lote.iniciar()
    except Exception as exc:  # noqa: BLE001
        aviso = f"o Flow em massa não ligou agora ({str(exc)[:160]}) — ▶ Continuar na aba Flow"
    return {"ok": True, "enviadas": len(quais), "aviso": aviso}


def recortar_verde(img) -> "Any":
    """Camada com fundo verde → PNG transparente recortado na caixa do objeto."""
    import personagens_limpeza as L
    alfa = L.alfa_do_verde(img)
    img_l, alfa, _f = L.limpar(img, alfa, {"fundo": "verde", "erodir": 1})
    rgba = img_l.convert("RGBA")
    rgba.putalpha(alfa)
    caixa = alfa.point(lambda v: 255 if v > 24 else 0).getbbox()
    if not caixa:
        raise ReactErro("o recorte não achou o objeto (o fundo não veio verde?)")
    return rgba.crop(caixa)


def guardar_camada(p: Dict[str, Any], camada: str, img, base: str = _BASE, recortar: Optional[bool] = None, origem: str = "flow") -> str:
    """Guarda a imagem de uma camada. Sofá/mesa: tira o fundo verde (se ela já vem com transparência, fica)."""
    from PIL import Image
    d = os.path.join(pasta(p["id"], base), "cenario")
    os.makedirs(d, exist_ok=True)
    if camada == "fundo":
        im = img.convert("RGB")
        # preenche 16:9 (corta o que sobra, sem distorcer)
        k = max(W / im.width, H / im.height)
        im = im.resize((max(W, round(im.width * k)), max(H, round(im.height * k))), Image.LANCZOS)
        x, y = (im.width - W) // 2, (im.height - H) // 2
        im = im.crop((x, y, x + W, y + H))
    else:
        tem_alfa = img.mode in ("RGBA", "LA") and img.getchannel("A").getextrema()[0] < 250
        if recortar is False or (recortar is None and tem_alfa):
            im = img.convert("RGBA")
            caixa = im.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
            im = im.crop(caixa) if caixa else im
        else:
            im = recortar_verde(img.convert("RGB"))
    arq = f"{camada}_{secrets.token_hex(3)}.png"
    im.save(os.path.join(d, arq))
    cam = p["cenario"]["camadas"].setdefault(camada, {})
    velhas = cam.get("versoes") or []
    cam.update(arquivo=arq, estado="pronta", erro=None, msg=None, origem=origem, versoes=([arq] + velhas)[:6])
    return arq


def acompanhar_cenario(pid: str, base: str = _BASE) -> bool:
    import flow_lote
    p = carregar(pid, base)
    abertas = {q: c for q, c in p["cenario"]["camadas"].items() if c.get("estado") in ("fila", "gerando") and c.get("job")}
    if not abertas:
        return False
    lote = flow_lote.lote()
    with lote.trava:
        fila = {j["id"]: dict(j) for j in lote.fila}
        rodando = lote.rodando
    mudou = False
    with _TRAVA:
        p = carregar(pid, base)
        for q, c in p["cenario"]["camadas"].items():
            if c.get("estado") not in ("fila", "gerando") or not c.get("job"):
                continue
            fj = fila.get(c["job"])
            antes = (c.get("estado"), c.get("msg"))
            if fj is None:
                c.update(estado="erro", erro="o pedido sumiu da fila do 🚀 Flow em massa — gere de novo")
            elif fj["estado"] == "ok":
                ok = False
                for r in fj.get("resultados") or []:
                    try:
                        import flow_estudio as FE
                        from PIL import Image
                        orig = os.path.join(FE.pasta_galeria(), r.get("arquivo") or "")
                        if r.get("tipo") == "imagem" and os.path.isfile(orig):
                            guardar_camada(p, q, Image.open(orig), base)
                            ok = True
                            break
                    except Exception as exc:  # noqa: BLE001
                        c.update(estado="erro", erro=f"a imagem chegou mas o recorte falhou: {str(exc)[:160]}")
                if ok:
                    log(p, f"✔ {ROTULO_CAMADA[q]} pronto")
                elif c.get("estado") != "erro":
                    c.update(estado="erro", erro="o Flow terminou sem imagem")
            elif fj["estado"] == "erro":
                c.update(estado="erro", erro=str(fj.get("erro") or "o Flow falhou")[:300])
            elif fj["estado"] in ("rodando", "convertendo"):
                c.update(estado="gerando", msg=f"🎨 gerando no Flow (conta “{fj.get('conta')}”)")
            elif not rodando:
                c.update(msg="⏸ o Flow em massa está parado — ▶ Continuar na aba Flow")
            else:
                c.update(msg="⏳ na fila do Flow")
            if (c.get("estado"), c.get("msg")) != antes:
                mudou = True
        if mudou:
            salvar(p, base)
    return mudou


def camada_arquivo(p: Dict[str, Any], camada: str, base: str = _BASE) -> Optional[str]:
    c = (p.get("cenario") or {}).get("camadas", {}).get(camada) or {}
    if c.get("arquivo"):
        cam = os.path.join(pasta(p["id"], base), "cenario", c["arquivo"])
        if os.path.isfile(cam):
            return cam
    return None


def fundo_padrao(destino: str, estilo: str = "anime") -> str:
    """Sem a camada do fundo: uma parede escura com degradê (o vídeo sai mesmo assim)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (W, H), (24, 20, 32))
    dr = ImageDraw.Draw(im)
    for y in range(H):
        k = y / H
        cor = (int(30 + 25 * (1 - k)), int(22 + 12 * (1 - k)), int(40 + 30 * (1 - k))) if estilo == "anime" else (int(40 - 12 * k), int(36 - 10 * k), int(34 - 10 * k))
        dr.line([(0, y), (W, y)], fill=cor)
    dr.rectangle([0, int(H * 0.80), W, H], fill=(36, 26, 22))
    im.save(destino)
    return destino


# ------------------------------------------------------------------ 📺 TV e legenda
def desenhar_tv(larg_tela: int, alt_tela: int, destino: str) -> Tuple[str, int]:
    """A moldura da TV (PNG) pro tamanho da tela do vídeo → (caminho, borda em px)."""
    from PIL import Image, ImageDraw, ImageFilter
    b = max(10, round(larg_tela * 0.025))
    w, h = larg_tela + 2 * b, alt_tela + 2 * b
    pad = 24
    im = Image.new("RGBA", (w + 2 * pad, h + 2 * pad + b), (0, 0, 0, 0))
    sombra = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sombra).rounded_rectangle([pad + 6, pad + 10, pad + w + 6, pad + h + 10], radius=b, fill=(0, 0, 0, 150))
    im.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(10)))
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle([pad, pad, pad + w, pad + h], radius=b, fill=(18, 18, 22, 255), outline=(70, 70, 80, 255), width=2)
    dr.rounded_rectangle([pad + b - 3, pad + b - 3, pad + b + larg_tela + 3, pad + b + alt_tela + 3], radius=4, fill=(4, 4, 6, 255))
    dr.line([(pad + b, pad + 4), (pad + w - b, pad + 4)], fill=(120, 120, 135, 200), width=2)  # brilho em cima
    led_r = max(2, b // 5)
    dr.ellipse([pad + w // 2 - led_r, pad + h - b // 2 - led_r, pad + w // 2 + led_r, pad + h - b // 2 + led_r], fill=(255, 60, 60, 230))
    im.save(destino)
    return destino, b + pad


def _quebrar(texto: str, fonte, largura: int, dr) -> List[str]:
    linhas, atual = [], ""
    for w in texto.split():
        t = (atual + " " + w).strip()
        if dr.textlength(t, font=fonte) <= largura or not atual:
            atual = t
        else:
            linhas.append(atual)
            atual = w
    if atual:
        linhas.append(atual)
    return linhas


def desenhar_legenda(nome: str, texto: str, cor: str, largura: int, destino: str, tam: int = 34) -> Tuple[str, int, int]:
    """A fala como legenda (PNG): "Nome:" na cor do personagem + o texto, numa caixa escura arredondada."""
    from PIL import Image, ImageDraw
    fn, ft = _fonte(tam, True), _fonte(tam, True)
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    pad = round(tam * 0.55)
    prefixo = f"{nome}: "
    linhas = _quebrar(prefixo + texto, ft, largura - 2 * pad, tmp)
    while len(linhas) > 4 and tam > 20:
        tam -= 3
        fn = ft = _fonte(tam, True)
        pad = round(tam * 0.55)
        linhas = _quebrar(prefixo + texto, ft, largura - 2 * pad, tmp)
    alt_l = round(tam * 1.28)
    h = 2 * pad + alt_l * len(linhas)
    lw = max(tmp.textlength(l, font=ft) for l in linhas) if linhas else 0
    w = int(min(largura, lw + 2 * pad + 2))
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle([0, 0, w - 1, h - 1], radius=round(tam * 0.5), fill=(8, 8, 12, 205), outline=(255, 255, 255, 60), width=2)
    y = pad - round(tam * 0.08)
    for k, l in enumerate(linhas):
        x = (w - tmp.textlength(l, font=ft)) / 2
        if k == 0 and l.startswith(prefixo.strip()):
            n_txt = prefixo if l.startswith(prefixo) else prefixo.strip()
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                dr.text((x + dx, y + dy), n_txt, font=fn, fill=(0, 0, 0, 255))
            dr.text((x, y), n_txt, font=fn, fill=cor)
            x2 = x + dr.textlength(n_txt, font=fn)
            resto = l[len(n_txt):]
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                dr.text((x2 + dx, y + dy), resto, font=ft, fill=(0, 0, 0, 255))
            dr.text((x2, y), resto, font=ft, fill=(255, 255, 255, 255))
        else:
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                dr.text((x + dx, y + dy), l, font=ft, fill=(0, 0, 0, 255))
            dr.text((x, y), l, font=ft, fill=(255, 255, 255, 255))
        y += alt_l
    im.save(destino)
    return destino, w, h


# ------------------------------------------------------------------ 📐 disposição
def _tam(cam: Optional[str], padrao: Tuple[int, int]) -> Tuple[int, int]:
    if not cam:
        return padrao
    try:
        from PIL import Image
        with Image.open(cam) as im:
            return im.size
    except Exception:  # noqa: BLE001
        return padrao


def disposicao(p: Dict[str, Any], base: str = _BASE, video_wh: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
    """Onde fica cada camada (em pixels de 1920×1080: centro x/y, largura, altura).
    → {"tv": {...}, "tela": {...}, "legenda": {...}, "sofas": [...], "mesa": {...}, "assentos": [{cid, ...}]}"""
    lay = p.get("layout") if p.get("layout") in LAYOUTS else "sofa_tv"
    vw, vh = video_wh or (int((p.get("video") or {}).get("largura") or 16), int((p.get("video") or {}).get("altura") or 9))
    asp_v = (vw / vh) if vw and vh else 16 / 9
    sw, sh = _tam(camada_arquivo(p, "sofa", base), (2200, 1000))
    mw, mh = _tam(camada_arquivo(p, "mesa", base), (2400, 700))
    n = max(1, len(p["personagens"]))
    out: Dict[str, Any] = {"layout": lay}
    if lay == "dois_sofas":
        tela_w = 0.34 * W
        tela_cx, tela_cy = 0.50 * W, 0.33 * H
        sofas_cx = [0.155 * W, 0.845 * W]
        sofa_w = 0.29 * W
        mesa_w, mesa_cx = 0.42 * W, 0.50 * W
        grupos = [list(range(0, math.ceil(n / 2))), list(range(math.ceil(n / 2), n))]
    else:
        tela_w = 0.345 * W
        tela_cx, tela_cy = 0.80 * W, 0.36 * H
        sofas_cx = [0.31 * W]
        sofa_w = 0.58 * W
        mesa_w, mesa_cx = 0.70 * W, 0.37 * W
        grupos = [list(range(n))]
    tela_h = tela_w / asp_v
    if tela_h > 0.46 * H:  # vídeo em pé: a TV fica mais estreita
        tela_h = 0.46 * H
        tela_w = tela_h * asp_v
    out["tela"] = {"cx": tela_cx, "cy": tela_cy, "w": tela_w, "h": tela_h}
    out["legenda"] = {"cx": tela_cx, "topo": tela_cy + tela_h / 2 + 0.045 * H, "w": max(tela_w * 1.05, 0.30 * W)}
    sofa_h = sofa_w * sh / sw
    if sofa_h > 0.50 * H:
        sofa_h = 0.50 * H
        sofa_w_real = sofa_h * sw / sh
    else:
        sofa_w_real = sofa_w
    sofa_base = 0.90 * H
    out["sofas"] = [{"cx": cx, "cy": sofa_base - sofa_h / 2, "w": sofa_w_real, "h": sofa_h, "espelhar": k == 1}
                    for k, cx in enumerate(sofas_cx) if grupos[k]]
    mesa_h = mesa_w * mh / mw
    if mesa_h > 0.27 * H:
        mesa_h = 0.27 * H
        mesa_w = mesa_h * mw / mh
    out["mesa"] = {"cx": mesa_cx, "cy": 1.015 * H - mesa_h / 2, "w": mesa_w, "h": mesa_h}
    # personagens: PNG 2:3 (a figura ocupa ~95% da altura, encostada embaixo)
    maior = max(len(g) for g in grupos)
    alt_pers = min(0.56 * H, (sofa_w_real * 0.92 / max(1, maior)) * 1.5 * 1.45)
    alt_pers = max(0.34 * H, alt_pers)
    png_h = alt_pers / 0.95
    png_w = png_h / 1.5
    pe = sofa_base - 0.05 * H  # onde o corte dos joelhos fica (a mesa cobre)
    assentos = []
    for k, g in enumerate(grupos):
        if not g:
            continue
        s = out["sofas"][min(k, len(out["sofas"]) - 1)]
        ini, fim = s["cx"] - s["w"] * 0.40, s["cx"] + s["w"] * 0.40
        for j, idx in enumerate(g):
            cx = (ini + fim) / 2 if len(g) == 1 else ini + (fim - ini) * j / (len(g) - 1)
            olha_esq = lay == "dois_sofas" and k == 1  # o sofá da direita olha pra TV no meio
            # os do fundo um pouco mais altos (fileira), alternando levemente pra parecer natural
            dy = (-0.012 * H) if j % 2 else 0.0
            if idx < len(p["personagens"]):
                assentos.append({"cid": p["personagens"][idx]["id"], "cx": cx, "cy": pe - png_h / 2 + dy, "w": png_w, "h": png_h,
                                 "espelhar": olha_esq})
    out["assentos"] = assentos
    return out


def _pct(v: float, total: float) -> float:
    return round(v / total * 100, 3)


# ------------------------------------------------------------------ 🎬 linha do tempo dos personagens
def linhas_personagens(p: Dict[str, Any], falas: List[Dict[str, Any]], duracao: float) -> Dict[str, List[Dict[str, Any]]]:
    """cid → [{start, end, expressao, falando}] cobrindo o vídeo inteiro: quem fala usa a expressão da fala (e mexe a
    boca), quem reage usa a da reação, o resto do tempo fica neutro. Trechos curtos demais entre duas caras iguais
    se juntam (sem piscar)."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for c in p["personagens"]:
        evs: List[Dict[str, Any]] = []
        for f in falas:
            ini, fim = max(0.0, float(f["t"]) - 0.15), min(duracao, float(f["t"]) + float(f["dur"]) + 0.35)
            if f["cid"] == c["id"]:
                evs.append({"start": ini, "end": fim, "expressao": f["expressao"], "falando": True,
                            "fala_ini": float(f["t"]), "fala_fim": float(f["t"]) + float(f["dur"])})
            else:
                r = next((x for x in f.get("reacoes") or [] if x["cid"] == c["id"]), None)
                if r:
                    evs.append({"start": ini + 0.3, "end": fim + 0.6, "expressao": r["expressao"], "falando": False})
        evs.sort(key=lambda e: (e["start"], not e["falando"]))
        limpos: List[Dict[str, Any]] = []
        for e in evs:  # quem fala ganha da reação no mesmo tempo
            if limpos and e["start"] < limpos[-1]["end"]:
                a = limpos[-1]
                if e["falando"] and not a["falando"]:
                    a["end"] = e["start"]
                    if a["end"] - a["start"] < 0.3:
                        limpos.pop()
                elif not e["falando"]:
                    e["start"] = a["end"]
                    if e["end"] - e["start"] < 0.5:
                        continue
                else:
                    a["end"] = e["start"]
            limpos.append(dict(e))
        linha: List[Dict[str, Any]] = []
        t = 0.0
        for e in limpos:
            e["start"], e["end"] = max(e["start"], t), min(e["end"], duracao)
            if e["end"] - e["start"] < 0.2:
                continue
            if e["start"] - t >= 0.05:
                if e["start"] - t < 0.45 and linha and linha[-1]["expressao"] == e["expressao"] and not linha[-1]["falando"] and not e["falando"]:
                    linha[-1]["end"] = e["start"]
                else:
                    linha.append({"start": t, "end": e["start"], "expressao": "neutro", "falando": False})
            linha.append(e)
            t = e["end"]
        if duracao - t > 0.05:
            linha.append({"start": t, "end": duracao, "expressao": "neutro", "falando": False})
        # junta vizinhos com a mesma cara (e sem boca)
        juntos: List[Dict[str, Any]] = []
        for e in linha:
            if juntos and juntos[-1]["expressao"] == e["expressao"] and not juntos[-1]["falando"] and not e["falando"]:
                juntos[-1]["end"] = e["end"]
            else:
                juntos.append(e)
        out[c["id"]] = [dict(e, start=round(e["start"], 3), end=round(e["end"], 3)) for e in juntos]
    return out


def _boca_janelas(ini: float, fim: float) -> List[List[float]]:
    """A boca mexe enquanto a fala está na tela — com pausas curtas, como quem fala frases."""
    jan, t = [], ini
    while t < fim - 0.2:
        dur = min(fim - t, 1.6)
        jan.append([round(t, 3), round(t + dur, 3)])
        t += dur + 0.25
    return jan


def montar_editor(p: Dict[str, Any], base: str, job_dir: str) -> Dict[str, Any]:
    """Tudo que o projeto do Estúdio precisa: áudio, o trecho do fundo e as camadas (overlays). Não registra o job —
    quem chama (a rota) põe no _JOBS do app."""
    from PIL import Image
    video = _video_local(p, base)
    if not video:
        raise ReactErro("Baixe ou envie o vídeo primeiro.")
    falas_proj = (p.get("roteiro") or {}).get("falas") or []
    if not falas_proj:
        raise ReactErro("Gere (ou cole) o roteiro primeiro.")
    if not p["personagens"]:
        raise ReactErro("Monte o elenco primeiro.")
    info = sondar(video)
    dur = info["duracao"]
    if dur <= 0:
        raise ReactErro("Não consegui ler a duração do vídeo.")
    d = os.path.join(job_dir, "react")
    os.makedirs(d, exist_ok=True)
    audio = extrair_audio(video, os.path.join(job_dir, "narracao.wav"), dur)
    avisos: List[str] = []
    est = estilo_final(p)

    def copiar(cam: str, nome: str) -> str:
        dst = os.path.join(d, nome)
        shutil.copyfile(cam, dst)
        return dst

    fundo = camada_arquivo(p, "fundo", base)
    fundo = copiar(fundo, "fundo.png") if fundo else fundo_padrao(os.path.join(d, "fundo.png"), est)
    if not camada_arquivo(p, "fundo", base):
        avisos.append("sem a camada do fundo — usei uma parede lisa (gere o 🧱 Fundo e mande de novo, ou troque no editor)")
    lay = disposicao(p, base, (info["largura"] or 16, info["altura"] or 9))
    overlays: List[Dict[str, Any]] = []

    def png(oid: str, nome: str, cam: str, cx: float, cy: float, w: float, start: float, end: float, camada: str,
            espelhar: bool = False, **extra: Any) -> Dict[str, Any]:
        ov = {"id": oid, "origem": "react", "camada": camada, "personagem": f"react_{camada}", "nome_personagem": nome,
              "source": {"source": "local_file", "value": cam, "kind": "image"}, "media_type": "image",
              "start": round(start, 3), "end": round(end, 3), "position": "bottom-left", "ancora": "centro",
              "size_percent": _pct(w, W), "x_percent": _pct(cx, W), "y_percent": _pct(cy, H),
              "anim_in": "nenhuma", "anim_out": "nenhuma", "anim_dur": 0.2, "espelhar": bool(espelhar),
              "boca_path": None, "boca_janelas": [], "manual": True}
        ov.update(extra)
        overlays.append(ov)
        return ov

    sofa = camada_arquivo(p, "sofa", base)
    if sofa:
        sc = copiar(sofa, "sofa.png")
        for k, s in enumerate(lay["sofas"]):
            png(f"rsofa{k}", "🛋 Sofá", sc, s["cx"], s["cy"], s["w"], 0, dur, "sofa", espelhar=s.get("espelhar", False))
    else:
        avisos.append("sem a camada do sofá")
    # personagens
    falas = ajustar_falas(falas_proj, dur)
    linhas = linhas_personagens(p, falas, dur)
    for a in lay["assentos"]:
        c = personagem(p, a["cid"])
        poses = poses_do_personagem(c, base)
        if not poses:
            ref = next((os.path.join(pasta(p["id"], base), "refs", r) for r in c.get("refs") or []
                        if os.path.isfile(os.path.join(pasta(p["id"], base), "refs", r))), None)
            avisos.append(f"{c['nome']} ainda não tem as poses (🧍 Gerar personagens)" + (" — usei a imagem de referência" if ref else ""))
            if ref:
                im = Image.open(ref).convert("RGBA")
                canvas = Image.new("RGBA", (1200, 1800), (0, 0, 0, 0))
                k = min(1140 / im.width, 1700 / im.height)
                im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))))
                canvas.paste(im, ((1200 - im.width) // 2, 1800 - im.height), im)
                cam = os.path.join(d, f"{c['id']}_ref.png")
                canvas.save(cam)
                poses = {"neutro": {"pose": cam, "boca": None}}
            else:
                continue
        copiados: Dict[str, str] = {}

        def pose_de(ex: str) -> Tuple[str, Optional[str]]:
            x = poses.get(ex) or poses.get("neutro") or next(iter(poses.values()))
            pc = x["pose"]
            if pc not in copiados:
                copiados[pc] = copiar(pc, f"{c['id']}_{os.path.basename(pc)}")
            bc = x.get("boca")
            if bc and bc not in copiados:
                copiados[bc] = copiar(bc, f"{c['id']}_{os.path.basename(bc)}")
            return copiados[pc], (copiados[bc] if bc else None)

        faltou = sorted({e["expressao"] for e in linhas.get(c["id"], []) if e["expressao"] not in poses})
        if faltou:
            avisos.append(f"{c['nome']}: sem a pose {', '.join(faltou)} ainda — usei a neutra nesses momentos")
        for k, e in enumerate(linhas.get(c["id"], [])):
            pc, bc = pose_de(e["expressao"])
            jan = _boca_janelas(e.get("fala_ini", e["start"]), e.get("fala_fim", e["end"])) if e["falando"] and bc else []
            png(f"r{c['id']}_{k}", c["nome"], pc, a["cx"], a["cy"], a["w"], e["start"], e["end"], "personagem",
                espelhar=a["espelhar"], expressao=e["expressao"], falando=e["falando"], cid=c["id"],
                boca_path=bc if jan else None, boca_janelas=jan)
    mesa = camada_arquivo(p, "mesa", base)
    if mesa:
        m = lay["mesa"]
        png("rmesa", "🪵 Mesa", copiar(mesa, "mesa.png"), m["cx"], m["cy"], m["w"], 0, dur, "mesa")
    else:
        avisos.append("sem a camada da mesa")
    # TV: a moldura (PNG) + o vídeo na tela
    t = lay["tela"]
    tv_png, borda = desenhar_tv(int(round(t["w"])), int(round(t["h"])), os.path.join(d, "tv.png"))
    tw, th = _tam(tv_png, (int(t["w"]), int(t["h"])))
    # o centro da moldura: a tela fica a `borda` px da esquerda/topo do PNG
    tv_cx = t["cx"] - t["w"] / 2 - borda + tw / 2
    tv_cy = t["cy"] - t["h"] / 2 - borda + th / 2
    png("rtv", "📺 TV", tv_png, tv_cx, tv_cy, tw, 0, dur, "tv")
    # legendas
    nomes = {c["id"]: c for c in p["personagens"]}
    leg = lay["legenda"]
    for k, f in enumerate(falas):
        c = nomes.get(f["cid"])
        if not c:
            continue
        cam, lw, lh = desenhar_legenda(c["nome"], f["texto"], c.get("cor") or "#ffd54a", int(leg["w"]),
                                       os.path.join(d, f"legenda_{k:03d}.png"))
        png(f"rleg{k:03d}", f"💬 {c['nome']}", cam, leg["cx"], leg["topo"] + lh / 2, lw, f["t"], f["t"] + f["dur"], "legenda",
            fala=f["texto"], cid=c["id"], cta=bool(f.get("cta")))
    # o vídeo na TV (o último: por cima de tudo, igual no monitor do Estúdio)
    overlays.append({"id": "rtela", "origem": "react_tela", "camada": "tela", "nome_personagem": "📺 Vídeo na TV",
                     "source": {"source": "local_file", "value": video, "kind": "video"}, "media_type": "video",
                     "start": 0.0, "end": round(dur, 3), "position": "top-right", "ancora": "centro", "sincronizar": True,
                     "size_percent": _pct(t["w"], W), "x_percent": _pct(t["cx"], W), "y_percent": _pct(t["cy"], H)})
    seg = {"start": 0.0, "end": round(dur, 3), "provider": "material", "query": f"🎭 react — cenário ({p.get('titulo') or ''})"[:150],
           "on_screen_text": None, "media_type": "image", "zoom_direction": "static", "efeito": None,
           "override_source": {"source": "local_file", "value": fundo, "kind": "image", "zoom_direction": "static",
                               "focus_x": 0.5, "focus_y": 0.5}}
    return {"audio": audio, "duracao": dur, "segmento": seg, "overlays": overlays, "avisos": avisos,
            "falas": [{"start": f["t"], "end": round(f["t"] + f["dur"], 3), "text": f"{nomes[f['cid']]['nome']}: {f['texto']}"}
                      for f in falas if f["cid"] in nomes]}


# ------------------------------------------------------------------ 👁 prévia (uma imagem do react pronto)
def previa(p: Dict[str, Any], base: str, destino: str, t: Optional[float] = None) -> str:
    """Uma imagem de como o react fica (no segundo t: quem fala, a legenda, o quadro do vídeo na TV)."""
    from PIL import Image, ImageOps
    est = estilo_final(p)
    video = _video_local(p, base)
    info = sondar(video) if video else {"duracao": 0, "largura": 16, "altura": 9}
    lay = disposicao(p, base, (info.get("largura") or 16, info.get("altura") or 9))
    fundo = camada_arquivo(p, "fundo", base)
    tela = Image.open(fundo).convert("RGBA") if fundo else Image.open(fundo_padrao(destino + ".fundo.png", est)).convert("RGBA")
    if not fundo:
        try:
            os.remove(destino + ".fundo.png")
        except OSError:
            pass
    tela = tela.resize((W, H))

    def colar(cam: str, cx: float, cy: float, w: float, espelhar: bool = False) -> None:
        im = Image.open(cam).convert("RGBA")
        h = w * im.height / im.width
        im = im.resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS)
        if espelhar:
            im = ImageOps.mirror(im)
        tela.alpha_composite(im, (int(cx - w / 2), int(cy - h / 2))) if cx - w / 2 >= 0 and cy - h / 2 >= 0 else \
            _colar_cortando(tela, im, int(cx - w / 2), int(cy - h / 2))

    sofa = camada_arquivo(p, "sofa", base)
    if sofa:
        for s in lay["sofas"]:
            colar(sofa, s["cx"], s["cy"], s["w"], s.get("espelhar", False))
    falas = ajustar_falas((p.get("roteiro") or {}).get("falas") or [], info.get("duracao") or None)
    if t is None:
        t = (falas[0]["t"] + 0.5) if falas else 0.0
    ativa = next((f for f in falas if f["t"] <= t < f["t"] + f["dur"]), None)
    linhas = linhas_personagens(p, falas, max(info.get("duracao") or 0, t + 1)) if falas else {}
    for a in lay["assentos"]:
        c = personagem(p, a["cid"])
        poses = poses_do_personagem(c, base)
        e = next((x for x in linhas.get(c["id"], []) if x["start"] <= t < x["end"]), None)
        ex = (e or {}).get("expressao") or "neutro"
        x = poses.get(ex) or poses.get("neutro") or (next(iter(poses.values())) if poses else None)
        cam = (x or {}).get("pose")
        if not cam:
            ref = next((os.path.join(pasta(p["id"], base), "refs", r) for r in c.get("refs") or []
                        if os.path.isfile(os.path.join(pasta(p["id"], base), "refs", r))), None)
            if not ref:
                continue
            im = Image.open(ref).convert("RGBA")
            canvas = Image.new("RGBA", (1200, 1800), (0, 0, 0, 0))
            k = min(1140 / im.width, 1700 / im.height)
            im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))))
            canvas.paste(im, ((1200 - im.width) // 2, 1800 - im.height), im)
            cam = destino + f".{c['id']}.png"
            canvas.save(cam)
        colar(cam, a["cx"], a["cy"], a["w"], a["espelhar"])
        if cam.startswith(destino + "."):
            os.remove(cam)
    mesa = camada_arquivo(p, "mesa", base)
    if mesa:
        m = lay["mesa"]
        colar(mesa, m["cx"], m["cy"], m["w"])
    tl = lay["tela"]
    tv, borda = desenhar_tv(int(tl["w"]), int(tl["h"]), destino + ".tv.png")
    tw, th = _tam(tv, (1, 1))
    colar(tv, tl["cx"] - tl["w"] / 2 - borda + tw / 2, tl["cy"] - tl["h"] / 2 - borda + th / 2, tw)
    os.remove(tv)
    if video:
        q = destino + ".q.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", video, "-frames:v", "1", q],
                       capture_output=True, timeout=60)
        if os.path.isfile(q):
            colar(q, tl["cx"], tl["cy"], tl["w"])
            os.remove(q)
    if ativa:
        c = next((x for x in p["personagens"] if x["id"] == ativa["cid"]), None)
        if c:
            leg = lay["legenda"]
            cam, lw, lh = desenhar_legenda(c["nome"], ativa["texto"], c.get("cor") or "#ffd54a", int(leg["w"]), destino + ".leg.png")
            colar(cam, leg["cx"], leg["topo"] + lh / 2, lw)
            os.remove(cam)
    tela.convert("RGB").save(destino, "JPEG", quality=88)
    return destino


def _colar_cortando(tela, im, x: int, y: int) -> None:
    """alpha_composite não aceita posição negativa: corta o pedaço que sai da tela."""
    cx0, cy0 = max(0, -x), max(0, -y)
    pedaco = im.crop((cx0, cy0, min(im.width, tela.width - x), min(im.height, tela.height - y)))
    if pedaco.width > 0 and pedaco.height > 0:
        tela.alpha_composite(pedaco, (max(0, x), max(0, y)))


# ------------------------------------------------------------------ pra página
def para_tela(p: Dict[str, Any], base: str = _BASE) -> Dict[str, Any]:
    out = dict(p)
    out["video_ok"] = bool(_video_local(p, base))
    out["estilo_final"] = estilo_final(p)
    out["personagens"] = []
    for c in p["personagens"]:
        x = dict(c)
        x["poses"] = estado_poses(c, base)
        out["personagens"].append(x)
    out["camadas"] = {q: dict((p["cenario"]["camadas"].get(q) or {}), tem=bool(camada_arquivo(p, q, base))) for q in CAMADAS}
    out["ia"] = ia_ligada()
    out["partes"] = estado_partes(p)
    try:
        import gemini_servico as gm
        out["gemini"] = bool(gm.chave())
    except Exception:  # noqa: BLE001
        out["gemini"] = False
    return out
