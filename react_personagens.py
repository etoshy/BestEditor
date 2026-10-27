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
    "cinema_costas": "🎬 Cinema — câmera atrás das poltronas (as costas no escuro e o telão)",
    "cinema_frente": "🎬 Cinema — de frente pra plateia (2 fileiras, a de trás nos vãos da da frente)",
    "cinema_plateia": "🎬 Cinema de perto — a fileira grande na frente, encostos no primeiro plano (estilo encerramento de anime)",
}
CINEMA = ("cinema_costas", "cinema_frente", "cinema_plateia")
# 🎬 quantos por fileira e quantas fileiras no cinema
POR_FILEIRA = 6
FILEIRAS_MAX = 3
FILEIRAS = {"cinema_costas": 2, "cinema_frente": 2, "cinema_plateia": 2}  # 2 fileiras, a de trás INTERCALADA (cada um no vão da da frente)
ESTILOS = {"auto": "Automático (pelo elenco)", "anime": "Anime / cartoon", "realista": "Realista"}
DENSIDADES = {"pouca": 15.0, "normal": 9.0, "muita": 6.0}  # 1 fala a cada N segundos (mais ou menos)
# ⚡ intrigas: quanto drama entre os personagens (provocação → briga com imagem estilo visual novel, sair de cena…)
INTRIGAS = {
    "nenhuma": "⚪ nenhuma (só reagem ao vídeo)",
    "leve": "🟡 leve (provocações; briga só se for MUITO merecida)",
    "media": "🟠 média (provocações frequentes; 1 briga a cada ~3 min)",
    "caos": "🔴 caos (todo mundo se provoca; brigas, gente saindo e voltando)",
}
TIPOS_EVENTO = {
    "briga": "👊 Briga (imagem da luta)",
    "interacao": "🤝 Interação (abraço, toca aqui, consolar…)",
    "cena": "🎬 Cena especial (imagem)",
    "foto": "🖼 Foto / exemplo (um quadro que aparece)",
    "estilo": "🎨 Desenhado diferente (no lugar dele)",
    "sai": "🚪 Sai de cena",
    "volta": "↩ Volta pra cena (sem 'sai' antes = chegou atrasado)",
    "gesto": "🍿 Gesto natural (pega pipoca, dá na boca, cochicha, olha pra trás)",
    "passa": "🚶 Alguém passa na frente (silhueta ou inteiro)",
}
# 🎬 cinema de perto: os movimentos naturais (sem imagem — pose própria no lugar dele, por uns segundos)
GESTOS = {
    "pega_pipoca": ("🍿 pega pipoca do vizinho", "leaning toward the viewer's RIGHT and reaching out sideways with the right "
                    "hand into the popcorn bucket of the person in the next seat, sneaky playful look"),
    "oferece": ("🤲 dá pipoca na boca do vizinho", "turned toward the viewer's RIGHT, holding out ONE piece of popcorn between "
                "the fingers toward the mouth of the person in the next seat, playful caring smile"),
    "cochicha": ("🤫 cochicha pro vizinho", "leaning toward the viewer's RIGHT with a hand cupped beside the mouth, whispering "
                 "a secret to the person in the next seat"),
    "olha_tras": ("👀 olha pra trás", "the upper body twisted and the head turned to look BACK over the shoulder toward the "
                  "rows behind (we see the face in profile), curious or annoyed"),
}
ANDANDO = ("🚶 andando pela fileira", "STANDING UP (this one is NOT sitting): walking sideways toward the viewer's RIGHT "
           "through a narrow cinema row, slightly crouched so as not to block the screen, apologetic face, FULL BODY from "
           "head to feet with margin")
PASSANTE = {"silhueta": "🌑 só a silhueta (sombra escura)", "inteiro": "🧍 inteiro (alguém qualquer)"}
EVENTO_COM_IMAGEM = ("briga", "interacao", "cena", "foto", "estilo")
# 📌 marcações suas num segundo do vídeo — a IA do roteiro obedece
TIPOS_NOTA = {
    "video": "🎬 sobre o vídeo (o que acontece aqui)",
    "quem_fala": "🎤 quem fala/canta no vídeo aqui",
    "aparece": "👤 personagem que aparece no vídeo",
    "fala": "💬 fala pra um personagem do elenco",
}
# como a imagem aparece: a tela toda (visual novel), um quadro por cima (foto pra exemplificar) ou no lugar do personagem
EXIBICAO = {"briga": "tela", "interacao": "tela", "cena": "tela", "foto": "quadro", "estilo": "no_lugar"}
# 🎨 quebra de expectativa: o personagem (ou a cena) num estilo de arte bem diferente, de propósito
ESTILOS_ARTE = {
    "": "— o estilo normal do react",
    "mal_desenhado": "✏ mal desenhado (paint, rabisco)",
    "pintura_antiga": "🖼 pintura antiga (óleo renascentista)",
    "hiper_detalhado": "💪 hiper detalhado e sério (rosto 'gigachad')",
    "chibi": "🍡 chibi fofo",
    "manga_pb": "📖 mangá preto e branco dramático",
    "giz_de_cera": "🖍 desenho de criança com giz de cera",
    "pixel_art": "👾 pixel art",
    "realista": "📷 realista (foto)",
    "meme_3d": "🧊 3D tosco (PS1)",
}
ESTILO_ARTE_EN = {
    "mal_desenhado": "deliberately badly drawn in MS Paint, wobbly lines, crude proportions, flat bucket-fill colors, funny low-effort meme drawing",
    "pintura_antiga": "classical Renaissance oil painting, dramatic chiaroscuro, ornate and highly detailed, museum masterpiece look",
    "hiper_detalhado": "hyper-detailed serious dramatic artwork, sharp jawline, intense eyes, heavy shading, 'gigachad' meme style",
    "chibi": "cute chibi style, big head small body, sparkly eyes, pastel colors",
    "manga_pb": "dramatic black and white manga panel, screentones, heavy ink, speed lines",
    "giz_de_cera": "child's crayon drawing on paper, scribbly, naive proportions",
    "pixel_art": "16-bit pixel art sprite",
    "realista": "photorealistic, real-life photo",
    "meme_3d": "low-poly PS1-era 3D render, blurry textures, awkward pose",
}

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
CAMADAS_LAYOUT = {"sofa_tv": ("fundo", "sofa", "mesa"), "dois_sofas": ("fundo", "sofa", "mesa"),
                  "cinema_costas": ("cine_costas_fundo", "cine_costas_fileira"),
                  "cinema_frente": ("cine_frente_fundo", "cine_frente_fileira"),
                  # 🎬 de perto: a sala com as fileiras indo pro fundo, a fileira de frente (atrás de quem senta), os
                  # encostos vistos de trás no primeiro plano e quem passa na frente
                  "cinema_plateia": ("cine_plateia_fundo", "cine_frente_fileira", "cine_costas_fileira", "cine_passante")}
CAMADAS = ("fundo", "sofa", "mesa", "cine_costas_fundo", "cine_costas_fileira", "cine_frente_fundo", "cine_frente_fileira",
           "cine_plateia_fundo", "cine_passante")
# a ficha de cada personagem (o que a IA preenche e você corrige)
CAMPOS_FICHA_TXT = ("obra", "personalidade", "jeito_de_falar", "cronologia", "relacoes", "aparencia_en", "busca_imagem",
                    "poderes", "poderes_en")
ROTULO_CAMADA = {"fundo": "🧱 Fundo (sala)", "sofa": "🛋 Sofá", "mesa": "🪵 Mesa da frente",
                 "cine_costas_fundo": "🎬 Sala de cinema (vista de trás, com o telão)",
                 "cine_costas_fileira": "💺 Fileira de poltronas (de costas)",
                 "cine_frente_fundo": "🎬 Sala de cinema (vista do telão, plateia em degraus)",
                 "cine_frente_fileira": "💺 Fileira de poltronas (de frente)",
                 "cine_plateia_fundo": "🎬 Sala de cinema (as fileiras indo pro fundo e a luz do projetor)",
                 "cine_passante": "🚶 Quem passa na frente (alguém qualquer andando de lado)"}


def layout_de(p: Dict[str, Any]) -> str:
    return p.get("layout") if p.get("layout") in LAYOUTS else "sofa_tv"


def camadas_do_layout(p: Dict[str, Any]) -> Tuple[str, ...]:
    return CAMADAS_LAYOUT[layout_de(p)]


def camada_papel(p: Dict[str, Any], papel: str, base: str = "") -> Optional[str]:
    """A camada do PAPEL (fundo / assento / mesa) na disposição atual: no cinema, a sala de cinema e a fileira."""
    nomes = camadas_do_layout(p)
    if layout_de(p) in CINEMA:  # sem mesa; de perto: 'plano' = os encostos do primeiro plano, 'passante' = quem passa
        q = {"fundo": nomes[0], "assento": nomes[1], "plano": nomes[2] if len(nomes) > 2 else None,
             "passante": nomes[3] if len(nomes) > 3 else None}.get(papel)
    else:
        q = {"fundo": nomes[0], "assento": nomes[1], "mesa": nomes[2] if len(nomes) > 2 else None}.get(papel)
    return camada_arquivo(p, q, base or _BASE) if q else None
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
    p.setdefault("objetos", [])  # 🍿 os itens da mesa (react_objetos)
    p.setdefault("notas", [])
    p.setdefault("imagens_destaque", True)
    p.setdefault("movimentos", False)  # 🍿 cinema de perto: gestos, chegar atrasado andando, alguém passando (opcional)
    p.setdefault("abertura", False)  # 🚪 abertura: chegam um por um e cumprimentam (desligada por padrão)
    p.setdefault("encerramento", False)  # 👋 encerramento: despedidas e saem um por um (desligado por padrão)  # 🖼 brigas/interações/cenas/fotos/estilos com imagem (desligado = só sai/volta)  # 📌 marcações num segundo do vídeo (observações e falas pedidas)
    p.setdefault("mesa_por_sofa", True)  # 🛋🛋 dois sofás: uma mesa pra cada
    p.setdefault("densidade", "normal")
    p.setdefault("intriga", "leve")
    p.setdefault("biblia", {})
    p.setdefault("expressoes", list(EXPRESSOES_PADRAO))
    p.setdefault("sugestoes", {})
    p.setdefault("personagens", [])
    p.setdefault("roteiro", {})
    p.setdefault("cenario", {})
    p["cenario"].setdefault("camadas", {})
    p.setdefault("editor", {})
    p.setdefault("checagem", {})
    p.setdefault("cortes", {"inicio": None, "fim": None, "meio": []})
    p.setdefault("destaques", [])
    p.setdefault("escutar", True)  # 👂 v84_245
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
            n = dict(f, t=t)
            if "t_ia" in f:  # 👂 o segundo da IA anda junto
                t_ia = mapear(inverso(float(f["t_ia"]), rem_antes), rem)
                if t_ia is None:
                    n.pop("t_ia")
                else:
                    n["t_ia"] = t_ia
            ficam.append(n)
        if falas:
            p["roteiro"]["falas"] = ficam
        evs = []
        for e in (p.get("roteiro") or {}).get("eventos") or []:
            t = mapear(inverso(float(e["t"]), rem_antes), rem)
            if t is not None:
                evs.append(dict(e, t=t))
        if (p.get("roteiro") or {}).get("eventos"):
            p["roteiro"]["eventos"] = evs
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
        # v84_244: na taxa ORIGINAL do vídeo (sem reamostrar) — a música chega igual no editor
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", video, "-vn", "-ac", "2", "-c:a", "pcm_s16le", destino]
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


def analisar_edicao(p: Dict[str, Any], base: str = _BASE, on_log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """🎬 Onde a edição do vídeo é FORTE (muitos cortes seguidos — transição, efeito, sequência rápida): detecção de
    troca de cena do ffmpeg. Guarda em p["edicao"] (refaz só se o vídeo mudou). → {"cortes": [...], "momentos": [...]}"""
    video = _video_local(p, base)
    if not video:
        return {}
    chave = f"{os.path.basename(video)}|{os.path.getsize(video)}|{int(os.path.getmtime(video))}"
    ed = p.get("edicao") or {}
    if ed.get("chave") == chave:
        return ed
    on_log("analisando a edição do vídeo (cortes e transições)…")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-v", "info", "-i", video, "-an", "-vf",
                        "scale=320:-2,select='gt(scene,0.32)',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=1800)
    cortes = sorted({round(float(m), 2) for m in re.findall(r"pts_time:([\d.]+)", r.stderr or "")})
    dur = float((p.get("video") or {}).get("duracao") or 0) or (cortes[-1] if cortes else 0)
    momentos: List[Dict[str, Any]] = []
    jan = 6.0
    if cortes and dur:
        media = len(cortes) / max(dur, 1)  # cortes por segundo no vídeo todo
        k = 0
        while k < len(cortes):
            dentro = [c for c in cortes[k:] if c < cortes[k] + jan]
            # sequência rápida: bem acima da média do vídeo (e pelo menos 5 cortes em 6 s)
            if len(dentro) >= max(5, int(media * jan * 2.5) + 1):
                momentos.append({"ini": dentro[0], "fim": dentro[-1], "cortes": len(dentro)})
                k += len(dentro)
            else:
                k += 1
        momentos = sorted(momentos, key=lambda m: -m["cortes"])[:max(3, int(dur / 40))]
        momentos.sort(key=lambda m: m["ini"])
    p["edicao"] = {"chave": chave, "cortes": cortes[:3000], "momentos": momentos, "quando": time.time()}
    return p["edicao"]


def quadros_em(video: str, tempos: List[float], saida_dir: str, largura: int = 320) -> List[Tuple[float, str]]:
    os.makedirs(saida_dir, exist_ok=True)
    out = []
    for k, t in enumerate(tempos):
        cam = os.path.join(saida_dir, f"m{k:03d}.jpg")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", video, "-frames:v", "1",
                        "-vf", f"scale={largura}:-2", cam], capture_output=True, timeout=60)
        if os.path.isfile(cam):
            out.append((t, cam))
    return out


def blocos_do_video(p: Dict[str, Any], base: str = _BASE, n: int = 27, ini: Optional[float] = None,
                    fim: Optional[float] = None) -> List[Dict[str, Any]]:
    video = _video_local(p, base)
    if not video:
        return []
    tmp = os.path.join(pasta(p["id"], base), f"_quadros_ia_{secrets.token_hex(3)}")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        qs = quadros(video, tmp, n, ini=ini, fim=fim)
        if ini is not None and fim is not None:  # 🎬 + 3 quadros em cada momento de edição forte do trecho
            extra = []
            for m in [m for m in (p.get("edicao") or {}).get("momentos") or [] if ini <= m["ini"] < fim][:3]:
                extra += [m["ini"] + (m["fim"] - m["ini"]) * f for f in (0.1, 0.5, 0.9)]
            qs += quadros_em(video, extra, os.path.join(tmp, "m"))
        return mosaicos(qs)
    except Exception:  # noqa: BLE001
        return []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ 👁 leitura do vídeo (além da transcrição)
LEITURA_S = 45.0  # cada pedido lê ~45 s do vídeo (9 quadros)
SCHEMA_LEITURA = {
    "type": "object", "additionalProperties": False, "required": ["momentos"],
    "properties": {"momentos": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["tempo", "o_que_acontece", "texto_na_tela", "quem_aparece", "clima"],
        "properties": {"tempo": {"type": "number"}, "o_que_acontece": {"type": "string"}, "texto_na_tela": {"type": "string"},
                       "quem_aparece": {"type": "string"}, "clima": {"type": "string"}}}}},
}
SYS_LEITURA = (
    "Você assiste a um trecho de vídeo (música de anime, AMV, edit, cena de filme) pelos QUADROS (o segundo está escrito "
    "em amarelo em cada quadro) e pela transcrição do trecho, e anota o que acontece pra quem vai escrever um react. "
    "Pra cada momento que muda (uns 4 a 8 no trecho): 'tempo' (segundo), 'o_que_acontece' (a cena: quem faz o quê, golpe, "
    "revelação, morte, transformação, flashback, o que a imagem MOSTRA além da letra — curto e concreto), "
    "'texto_na_tela' (TUDO que estiver escrito na imagem: legenda da letra, letreiro, nome de técnica, título, crédito, "
    "tradução — copie como está; \"\" se não tiver), 'quem_aparece' (os personagens que você reconhece; diga se não tem "
    "certeza) e 'clima' (épico, triste, engraçado, tenso, romântico…). Não invente o que não dá pra ver. Português do Brasil."
)


def chave_video(p: Dict[str, Any], base: str = _BASE) -> str:
    video = _video_local(p, base)
    return f"{os.path.basename(video)}|{os.path.getsize(video)}|{int(os.path.getmtime(video))}" if video else ""


def ler_video(pid: str, base: str = _BASE, ini: Optional[float] = None, fim: Optional[float] = None, refazer: bool = False,
              on_log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """👁 A IA ASSISTE ao vídeo (quadros a cada ~5 s + a transcrição do trecho) e anota o que acontece, o texto que
    aparece na tela (legenda embutida, letreiro, nome de golpe) e quem aparece — o roteiro usa isso além da
    transcrição. Guarda por trecho de ~45 s em p["leitura"] (refaz só se o vídeo mudou ou pedir)."""
    p = carregar(pid, base)
    video = _video_local(p, base)
    if not video:
        raise ReactErro("Baixe ou envie o vídeo antes.")
    dur = sondar(video)["duracao"] or 0
    chave = chave_video(p, base)
    lei = p.get("leitura") or {}
    if lei.get("chave") != chave or refazer and ini is None:
        lei = {"chave": chave, "trechos": {}}
    a0, b0 = max(0.0, ini or 0.0), min(dur, fim if fim is not None else dur)
    n = max(1, int(math.ceil(dur / LEITURA_S)))
    tam = dur / n
    feitos, erros = 0, 0
    for k in range(n):
        a, b = k * tam, min(dur, (k + 1) * tam)
        if b <= a0 or a >= b0:
            continue
        if str(k) in lei["trechos"] and not refazer:
            continue
        on_log(f"👁 lendo o vídeo {mmss(a)}–{mmss(b)}…")
        tmp = os.path.join(pasta(pid, base), f"_leitura_{secrets.token_hex(3)}")
        try:
            qs = quadros(video, tmp, 9, largura=480, ini=a, fim=b)
            blocos = mosaicos(qs)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        trans = [e for e in p["transcricao"] if e.get("ini") is not None and a - 2 <= e["ini"] < b + 1]
        bib_r = (p.get("biblia") or {}).get("resumo") or {}
        quem_bib = ", ".join(f"{x.get('nome')} ({x.get('quem_e')})" for x in bib_r.get("personagens") or [])[:1500]
        texto = (f"TRECHO {mmss(a)}–{mmss(b)} do vídeo \"{p.get('titulo') or ''}\"" + (f" (obra: {p['obra']})" if p.get("obra") else "")
                 + (f"\nPERSONAGENS DA OBRA (da bíblia do usuário — use pra reconhecer quem aparece): {quem_bib}" if quem_bib else "")
                 + "\nTRANSCRIÇÃO DO TRECHO:\n" + (transcricao_texto(trans, 4000) or "(sem)"))
        r = _ia().chamar("react", SYS_LEITURA, [{"type": "text", "text": texto}] + blocos, schema=SCHEMA_LEITURA,
                         max_tokens=2500, effort="low", timeout=180, cache_local=False)
        if not isinstance(r, dict) or not isinstance(r.get("momentos"), list):
            erros += 1
            continue
        moms = []
        for m in r["momentos"][:12]:
            t = segundos(m.get("tempo")) if isinstance(m, dict) else None
            if t is None:
                continue
            moms.append({"t": round(min(max(t, a), b), 2),
                         **{c: " ".join(str(m.get(c) or "").split())[:300] for c in ("o_que_acontece", "texto_na_tela", "quem_aparece", "clima")}})
        lei["trechos"][str(k)] = {"ini": round(a, 2), "fim": round(b, 2), "momentos": sorted(moms, key=lambda x: x["t"])}
        feitos += 1
        with _TRAVA:
            q = carregar(pid, base)
            q["leitura"] = lei
            salvar(q, base)
    if feitos == 0 and erros:
        raise ReactErro("A IA não respondeu na leitura do vídeo (desligada, sem crédito ou erro).")
    with _TRAVA:
        q = carregar(pid, base)
        q["leitura"] = lei
        log(q, f"👁 vídeo lido: {feitos} trecho(s)" + (f" · {erros} com erro" if erros else ""))
        salvar(q, base)
    return {"feitos": feitos, "erros": erros, "trechos": len(lei["trechos"]), "total": n}


def momentos_lidos(p: Dict[str, Any], a: float, b: float, base: str = _BASE) -> List[Dict[str, Any]]:
    lei = p.get("leitura") or {}
    if not lei.get("trechos") or (lei.get("chave") and lei["chave"] != chave_video(p, base)):
        return []
    return [m for tr in lei["trechos"].values() for m in tr["momentos"] if a <= m["t"] < b]


def estado_leitura(p: Dict[str, Any], base: str = _BASE) -> Dict[str, Any]:
    lei = p.get("leitura") or {}
    dur = float((p.get("video") or {}).get("duracao") or 0)
    total = max(1, int(math.ceil(dur / LEITURA_S))) if dur else 0
    valida = bool(lei.get("trechos")) and lei.get("chave") == chave_video(p, base)
    return {"lidos": len(lei.get("trechos") or {}) if valida else 0, "total": total}


# ------------------------------------------------------------------ 🧑‍🤝‍🧑 elenco
def novo_personagem(p: Dict[str, Any], nome: str, **campos: Any) -> Dict[str, Any]:
    nome = " ".join(str(nome or "").split())[:80]
    if not nome:
        raise ReactErro("Escreva o nome do personagem.")
    if any(_norm(c["nome"]) == _norm(nome) for c in p["personagens"]):
        raise ReactErro(f"{nome} já está no elenco.")
    mx = MAXIMO_LAYOUT.get(layout_de(p), MAXIMO)
    if len(p["personagens"]) >= mx:
        raise ReactErro(f"O máximo nesta disposição é {mx} personagens (sofás: ideal até {RECOMENDADO['sofa_tv']} num sofá e "
                        f"{RECOMENDADO['dois_sofas']} nos dois; 🎬 cinema: até {MAXIMO_LAYOUT['cinema_costas']} — 6 na fileira da "
                        f"frente e 5 nos vãos da de trás). Mude pra disposição de cinema pra pôr mais gente.")
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


def guardar_cor_ref(p: Dict[str, Any], c: Dict[str, Any], dados: bytes, base: str = _BASE) -> str:
    """🌈 A foto COLORIDA do personagem (opcional — quando a referência é mangá P&B): só pras cores reais."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(dados))
        im.load()
    except Exception:  # noqa: BLE001
        raise ReactErro("Isso não é uma imagem.")
    if max(im.size) > 1600:
        k = 1600 / max(im.size)
        im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))))
    tirar_cor_ref(p, c, base)
    d = os.path.join(pasta(p["id"], base), "refs")
    os.makedirs(d, exist_ok=True)
    arq = f"{c['id']}_cor_{secrets.token_hex(3)}.png"
    im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(os.path.join(d, arq))
    c["cor_ref"] = arq
    return arq


def tirar_cor_ref(p: Dict[str, Any], c: Dict[str, Any], base: str = _BASE) -> None:
    a = c.pop("cor_ref", None)
    if a:
        try:
            os.remove(os.path.join(pasta(p["id"], base), "refs", a))
        except OSError:
            pass


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
    "poderes": {"type": "string"}, "poderes_en": {"type": "string"},
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
    "termo para achar uma imagem oficial dele no Google Imagens; " + "poderes (os PODERES/habilidades e o jeito VISUAL de interagir com coisas e pessoas, em português — ex.: Tatsumaki: telecinese, levita objetos e pessoas com brilho verde; Luffy: corpo de borracha, estica braços, cara de desenho/toon nas piadas; um personagem estressado: bufa, amassa as coisas, explode; \"nenhum\" se for gente comum), poderes_en (o mesmo em INGLÊS, curto e visual, pra desenhar — \"\" se nenhum), " "estilo: 'anime' (personagem de anime/desenho/jogo) ou "
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
    bib = biblia_bloco(p)
    if bib:
        partes.append(bib)
    partes.append("TRANSCRIÇÃO (tempo no vídeo):\n" + (transcricao_texto(p["transcricao"]) or "(sem transcrição)"))
    return "\n".join(partes)


# ------------------------------------------------------------------ 📖 bíblia da obra (v84_237)
# Obra pouco conhecida: a IA não sabe quem é quem. Você cola a descrição dos episódios (ANN, wiki, resenha) e/ou escreve a
# personalidade de cada um — vira a FONTE PRINCIPAL de tudo (sugestões, fichas, roteiro, verificador, leitura do vídeo).
BIBLIA_MAX = 80000
SCHEMA_BIBLIA = {
    "type": "object", "additionalProperties": False,
    "required": ["obra", "sinopse", "tom", "episodios", "personagens", "piadas_recorrentes"],
    "properties": {
        "obra": {"type": "string"}, "sinopse": {"type": "string"}, "tom": {"type": "string"},
        "episodios": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["ep", "o_que_acontece"],
                                                 "properties": {"ep": {"type": "string"}, "o_que_acontece": {"type": "string"}}}},
        "personagens": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                   "required": ["nome", "quem_e", "personalidade", "jeito_de_falar", "relacoes"],
                                                   "properties": {"nome": {"type": "string"}, "quem_e": {"type": "string"},
                                                                  "personalidade": {"type": "string"}, "jeito_de_falar": {"type": "string"},
                                                                  "relacoes": {"type": "string"}}}},
        "piadas_recorrentes": {"type": "array", "items": {"type": "string"}},
    },
}
SYS_BIBLIA = (
    "Você recebe um material sobre uma obra (anime, mangá, série) — descrições de episódios, resenhas, wiki, anotações "
    "do usuário — e organiza uma BÍBLIA para roteiristas de vídeos de react com personagens dessa obra. Use SÓ o que está "
    "no material (não invente; o que não estiver lá, deixe de fora). 'obra': o nome; 'sinopse': 3–5 frases; 'tom': o "
    "gênero e o humor da obra; 'episodios': o que acontece em cada episódio/capítulo citado, em ordem; 'personagens': "
    "TODOS os citados — quem é (papel, raça/classe), personalidade, jeito de falar (como fala, bordões, como reagiria), "
    "relações (com quem, como evolui); 'piadas_recorrentes': gags e situações que se repetem. Ignore a opinião do crítico "
    "(notas, 'vale a pena assistir'), fique com os FATOS da obra. Português do Brasil."
)


def biblia_bloco(p: Dict[str, Any], limite_txt: int = 9000) -> str:
    """O bloco da 📖 bíblia que vai nos pedidos pra IA (o resumo organizado + trechos do texto original)."""
    b = p.get("biblia") or {}
    txt = str(b.get("texto") or "").strip()
    r = b.get("resumo") or {}
    if not txt and not r:
        return ""
    L = ["📖 BÍBLIA DA OBRA (enviada por você) — é a FONTE PRINCIPAL: quem é quem, personalidades, relações, o que "
         "acontece em cada episódio e o tom vêm DAQUI. Obra pouco conhecida: não invente fatos fora disto; na dúvida, "
         "fique no que a bíblia diz."]
    if r:
        if r.get("obra"):
            L.append(f"Obra: {r['obra']}")
        if r.get("sinopse"):
            L.append(f"Sinopse: {r['sinopse']}")
        if r.get("tom"):
            L.append(f"Tom: {r['tom']}")
        for e in r.get("episodios") or []:
            L.append(f"- Ep. {e.get('ep')}: {e.get('o_que_acontece')}")
        for c in r.get("personagens") or []:
            L.append(f"- {c.get('nome')}: {c.get('quem_e')} | personalidade: {c.get('personalidade')} | fala: {c.get('jeito_de_falar')}"
                     f" | relações: {c.get('relacoes')}")
        if r.get("piadas_recorrentes"):
            L.append("Piadas recorrentes: " + "; ".join(r["piadas_recorrentes"]))
    if txt:
        lim = limite_txt if r else limite_txt + 6000
        L.append("TEXTO ORIGINAL" + (" (trechos)" if len(txt) > lim else "") + ":\n" + (txt if len(txt) <= lim else txt[:lim] + " […]"))
    return "\n".join(L)


def definir_biblia(p: Dict[str, Any], texto: str) -> None:
    t = str(texto or "").replace("\r\n", "\n").strip()[:BIBLIA_MAX]
    b = p.setdefault("biblia", {})
    if t != b.get("texto"):
        b["texto"] = t
        b["resumo"] = {} if not t else b.get("resumo") or {}
        b["resumo_desatualizado"] = bool(t and b.get("resumo"))
        b["quando"] = time.time()


def aplicar_biblia_nas_fichas(p: Dict[str, Any]) -> int:
    """Os personagens do elenco que estão na bíblia ganham personalidade/jeito de falar/relações (só o que está vazio)."""
    r = (p.get("biblia") or {}).get("resumo") or {}
    n = 0
    for c in p["personagens"]:
        f = next((x for x in r.get("personagens") or [] if _norm(x.get("nome")) == _norm(c["nome"])), None) \
            or next((x for x in r.get("personagens") or [] if x.get("nome") and (_norm(x["nome"]) in _norm(c["nome"]) or _norm(c["nome"]) in _norm(x["nome"]))), None)
        if not f:
            continue
        mudou = False
        for k in ("personalidade", "jeito_de_falar", "relacoes"):
            if f.get(k) and not str(c.get(k) or "").strip():
                c[k] = str(f[k])[:600]
                mudou = True
        if not c.get("obra") and r.get("obra"):
            c["obra"] = str(r["obra"])[:200]
            mudou = True
        n += mudou
    return n


def resumir_biblia(pid: str, base: str = _BASE) -> Dict[str, Any]:
    """🤖 Organiza o material colado (episódios, personagens, tom, piadas) — e preenche o que falta nas fichas."""
    p = carregar(pid, base)
    txt = str((p.get("biblia") or {}).get("texto") or "")
    if not txt.strip():
        raise ReactErro("Cole o material da obra na 📖 bíblia antes.")
    r = _ia().chamar("react", SYS_BIBLIA, [{"type": "text", "text": f"OBRA (informada): {p.get('obra') or '?'}\n\nMATERIAL:\n{txt[:60000]}"}],
                     schema=SCHEMA_BIBLIA, max_tokens=6000, effort="low", timeout=240, cache_local=False)
    if not isinstance(r, dict):
        raise ReactErro("A IA não respondeu (desligada, sem crédito ou erro) — a bíblia vai como está, sem resumo.")
    with _TRAVA:
        p = carregar(pid, base)
        p["biblia"]["resumo"] = r
        p["biblia"]["resumo_desatualizado"] = False
        if not p.get("obra") and r.get("obra"):
            p["obra"] = str(r["obra"])[:200]
        n = aplicar_biblia_nas_fichas(p)
        log(p, f"📖 bíblia organizada: {len(r.get('episodios') or [])} episódio(s), {len(r.get('personagens') or [])} personagem(ns)"
            + (f" · {n} ficha(s) completadas" if n else ""))
        salvar(p, base)
    return {"episodios": len(r.get("episodios") or []), "personagens": len(r.get("personagens") or []), "fichas": n}


def _bib_personagem(c: Dict[str, Any]) -> str:
    return f" | 📖 bíblia do personagem (siga à risca): {c['biblia']}" if str(c.get("biblia") or "").strip() else ""


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
        if len(p["personagens"]) >= MAXIMO_LAYOUT.get(layout_de(p), MAXIMO):
            break
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
    "aparencia_en (em INGLÊS: cabelo, olhos, roupa marcante, acessórios, cores — para desenhar), " + "poderes (os PODERES/habilidades e o jeito VISUAL de interagir com coisas e pessoas, em português — ex.: Tatsumaki: telecinese, levita objetos e pessoas com brilho verde; Luffy: corpo de borracha, estica braços, cara de desenho/toon nas piadas; um personagem estressado: bufa, amassa as coisas, explode; \"nenhum\" se for gente comum), poderes_en (o mesmo em INGLÊS, curto e visual, pra desenhar — \"\" se nenhum), " "busca_imagem (termo do "
    "Google Imagens), estilo ('anime' ou 'realista'). Mantenha o NOME exatamente como veio. Português do Brasil."
)


def prompt_fichas(p: Dict[str, Any], cids: List[str]) -> str:
    nomes = [personagem(p, c)["nome"] + (f" (obra: {personagem(p, c)['obra']})" if personagem(p, c).get("obra") else "") for c in cids]
    creditos = sorted({e["texto"] for e in p["transcricao"] if e["tipo"] == "credito"})
    return (f"VÍDEO DO REACT: {p.get('titulo') or ''}" + (f" — obra: {p['obra']}" if p.get("obra") else "")
            + (f"\nQUEM APARECE/CANTA NO VÍDEO (créditos na tela): {', '.join(creditos)[:1500]}" if creditos else "")
            + (f"\nRESUMO DO VÍDEO: {(p.get('sugestoes') or {}).get('resumo_video')}" if (p.get("sugestoes") or {}).get("resumo_video") else "")
            + ("\n\n" + biblia_bloco(p, 12000) if biblia_bloco(p) else "")
            + "\nPERSONAGENS:\n" + "\n".join(f"- {n}" + _bib_personagem(personagem(p, c)) for n, c in zip(nomes, cids)))


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
    cids = cids or [c["id"] for c in p["personagens"] if not c.get("personalidade") or not c.get("aparencia_en") or not c.get("poderes")]
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
        "type": "object", "additionalProperties": False, "required": ["resumo", "falas", "eventos"],
        "properties": {
            "resumo": {"type": "string"},
            "eventos": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["tempo", "tipo", "personagens", "descricao", "imagem_en", "duracao", "estilo_arte", "gesto"],
                "properties": {
                    "tempo": {"type": "number"}, "tipo": {"type": "string", "enum": list(TIPOS_EVENTO)},
                    "gesto": {"type": "string", "enum": [""] + list(GESTOS) + list(PASSANTE)},
                    "estilo_arte": {"type": "string", "enum": list(ESTILOS_ARTE)},
                    "personagens": {"type": "array", "items": {"type": "string"}},
                    "descricao": {"type": "string"}, "imagem_en": {"type": "string"}, "duracao": {"type": "number"},
                }}},
            "falas": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["tempo", "personagem", "texto", "expressao", "expressao_depois", "pedido_inscricao", "reacoes",
                             "duvida", "destaque"],
                "properties": {
                    "tempo": {"type": "number"}, "personagem": {"type": "string"}, "texto": {"type": "string"},
                    "expressao": {"type": "string", "enum": exprs}, "pedido_inscricao": {"type": "boolean"},
                    "expressao_depois": {"type": "string", "enum": [""] + list(exprs)},
                    "duvida": {"type": "string"},
                    "destaque": {"type": "string", "enum": ["", "letra", "edicao"]},
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
        "- ANALISE a transcrição (com o tempo de cada frase), o que a IA já LEU do vídeo (👁 a cena, o texto na tela, quem aparece) e os quadros do vídeo (o tempo está escrito em amarelo em "
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
        "fala aparece (número, ex.: 73.5) — logo DEPOIS do que ela comenta: o personagem ESCUTA a frase/o verso até o FIM "
        "(veja o [início–fim] de cada frase na transcrição) e só então fala; nunca no meio de um verso.\n"
        "- 'expressao' = a cara de quem fala naquele momento, de acordo com a personalidade e o que ele está sentindo: "
        f"uma de {', '.join(exprs)}. Varie — não use a mesma o tempo todo. A cara FICA depois da fala até a próxima fala ou "
        "reação dele, então pense no que ele sente nesse intervalo também.\n"
        "- 'expressao_depois' = a cara muda NO MEIO da fala (ex.: começa 'debochado' e termina 'chocado' quando percebe "
        "algo; começa 'bravo' e termina 'triste'); \"\" se não muda. Use em umas 1 a cada 4 falas — deixa mais vivo.\n"
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
        "- LETRA BOA E EDIÇÃO DIFERENTE: quando a letra tiver um verso MUITO bom (rima forte, punchline, trocadilho, "
        "referência esperta, frase profunda ou emocionante) ou a EDIÇÃO fizer algo diferente (transição criativa, efeito, "
        "corte na batida, sequência de cortes rápidos, mudança de estilo — veja os quadros e os 'momentos de edição'), "
        "um personagem COMENTA isso no jeito dele: às vezes citando o verso entre aspas ('\"mil anos de espera\"... "
        "arrepiei'), elogiando o cantor pelo nome do crédito ou o editor ('quem editou isso tá de parabéns'), ou do "
        "contra (o vilão odeia o verso sobre ele). Marque 'destaque': 'letra' ou 'edicao' nessas falas (\"\" nas outras). "
        "Os versos ⭐ marcados são OBRIGATÓRIOS (alguém comenta cada um). Sem exagero: no máximo um comentário desses a "
        "cada ~30 s, fora os ⭐.\n"
        "- 'duvida': se a fala depende de um fato da obra (quem conheceu quem, antes/depois, nome de técnica, quem morreu) "
        "e você NÃO tem certeza, escreva a dúvida aqui (ex.: 'não sei se o Itachi conheceu o Madara antes da guerra') — "
        "vai pro verificador de fatos. Com certeza: deixe \"\".\n"
        + _regra_intriga(p) + regra_lugar(p) +
        "- 📖 Se tiver BÍBLIA (da obra ou de um personagem), ela manda: cada um fala e reage como a bíblia descreve (a "
        "personalidade, o jeito de falar, as relações e o que já aconteceu entre eles) — use os acontecimentos e as piadas "
        "recorrentes dela; não invente fatos da obra que não estejam lá.\n"
        "- 📌 MARCAÇÕES DO AUTOR (se vierem no pedido): são ordens. '💬 X DIZ EXATAMENTE' = a fala sai com esse texto, "
        "dita por X, no segundo marcado (pode ajustar a pontuação, não as palavras); '💬 uma fala sobre…' = X fala "
        "disso naquele segundo, do jeito dele; '🎤 quem fala/canta' e '👤 aparece' = informação certa sobre o vídeo "
        "(use nas reações — quem é do elenco reage a si mesmo aparecendo); '🎬' = o que acontece ali (alguém comenta).\n"
        "- 'personagem' = o NOME exatamente como está no elenco.\n"
        f"- Escreva as falas em {p.get('idioma') or 'português do Brasil'}.\n"
        "- 'resumo' = 1–2 frases sobre o vídeo e a dinâmica do react."
    )


REGRA_PLATEIA = (
    "🎬 CINEMA DE PERTO (o jeito do encerramento de anime): vistos de FRENTE e de perto, numa fileira de poltronas (e uns "
    "na fileira de trás, menores); o vídeo é o filme. O que deixa vivo são os MOVIMENTOS NATURAIS — use em 'eventos' "
    "(sem imagem; 'imagem_en' = \"\", 'estilo_arte' = \"\"), espalhados, uns 1 a cada ~20–30 s, ligados ao que "
    "acontece no filme e na conversa:\n"
    "  · 'gesto' — 'personagens' = [quem faz, com quem] (o 'com quem' é o VIZINHO de poltrona) e 'gesto' = "
    "'pega_pipoca' (pega pipoca do balde do vizinho, de fininho), 'oferece' (dá uma pipoca na boca do vizinho), "
    "'cochicha' (cochicha no ouvido do vizinho — a fala dele vem logo depois, baixinho) ou 'olha_tras' (só quem faz: "
    "vira pra trás, curioso ou irritado com alguém da fileira de trás); 'duracao' 2–4. As falas combinam (\"ei, a "
    "pipoca é minha!\", \"abre a boca\", \"psiu, olha aquilo\").\n"
    "  · 'passa' — alguém de fora passa na frente da fileira, atrapalhando a visão: 'personagens' = [], 'gesto' = "
    "'silhueta' (só a sombra escura) ou 'inteiro'; 'duracao' 3–4; eles reclamam (\"sai da frente!\", \"abaixa!\").\n"
    "  · CHEGOU ATRASADO: um 'volta' de alguém SEM 'sai' antes = ele chega nesse segundo, entrando pela fileira e "
    "pedindo licença (não fala nem reage antes de chegar; os outros comentam o atraso).\n"
    "  · 'sai' — levanta e sai andando pela fileira (banheiro, mais pipoca, irritado) e 'volta' quando voltar.\n"
    "  Alguém fala alto demais → outro manda ficar quieto (\"Shhh!\").")


REGRA_PLATEIA_SIMPLES = (
    "🎬 CINEMA DE PERTO (o jeito do encerramento de anime): vistos de FRENTE e de perto, numa fileira de poltronas (e uns "
    "na fileira de trás, menores); o vídeo é o filme. Cochichos entre vizinhos de poltrona, reações de plateia, pipoca e "
    "refrigerante nas mãos; alguém fala alto demais → outro manda ficar quieto (\"Shhh!\"). Em 'eventos' NÃO use "
    "'gesto' nem 'passa'.")


def regra_lugar(p: Dict[str, Any], a: Optional[float] = None, b: Optional[float] = None) -> str:
    """🎬 O lugar (sofá × cinema) e 🚪👋 a abertura/encerramento, pro pedido do roteiro."""
    L = []
    lay = layout_de(p)
    if lay == "cinema_costas":
        L.append("🎬 ELES ESTÃO NUM CINEMA, vistos de TRÁS (as costas, no escuro, o telão na frente): o vídeo é o filme. "
                 "Falar no cinema incomoda — quando alguém fala alto ou comenta demais, OUTROS mandam ficar quieto "
                 "(\"Shhh!\", \"Cala a boca!\", \"Fala baixo!\", até um estranho da fileira de trás reclama); muitas falas "
                 "são cochichos pro vizinho; as reações são de corpo (pulam de susto, jogam pipoca, levantam o punho). "
                 "Quem fala vira o rosto pro lado (de perfil).")
    elif lay == "cinema_frente":
        L.append("🎬 ELES ESTÃO NUM CINEMA, vistos de FRENTE (a plateia em fileiras, a luz do telão no rosto): o vídeo é o "
                 "filme. Reações grandes de plateia (todos pulam juntos no susto, alguém chora, alguém dorme), cochichos "
                 "entre vizinhos de poltrona, alguém manda ficar quieto, pipoca e refrigerante de cinema nas mãos.")
    elif lay == "cinema_plateia":
        L.append(REGRA_PLATEIA if p.get("movimentos") else REGRA_PLATEIA_SIMPLES)
    if p.get("abertura") and (a is None or a < ABERTURA_S):
        ch = chegadas(p)
        nomes = {c["id"]: c["nome"] for c in p["personagens"]}
        L.append(f"🚪 ABERTURA (primeiros ~{ABERTURA_S:.0f} s): eles CHEGAM um por um — " + ", ".join(f"{nomes[c]} em {t:.1f} s"
                 for c, t in ch.items() if c in nomes) + " — e cada um, logo depois de chegar, cumprimenta/fala do vídeo que "
                 "vão assistir, no jeito dele (curto). Ninguém fala antes de chegar.")
    dur = float((p.get("video") or {}).get("duracao") or 0)
    if p.get("encerramento") and dur and (b is None or b >= dur - ENCERRAMENTO_S - 5):
        sa = saidas(p, dur)
        nomes = {c["id"]: c["nome"] for c in p["personagens"]}
        L.append(f"👋 ENCERRAMENTO (últimos ~{ENCERRAMENTO_S:.0f} s): o comentário final e as DESPEDIDAS — cada um se "
                 "despede no jeito dele e SAI um por um: " + ", ".join(f"{nomes[c]} sai em {t:.1f} s" for c, t in sa.items() if c in nomes)
                 + ". Ninguém fala depois de sair.")
    return ("\n".join("- " + x for x in L) + "\n") if L else ""


def _regra_intriga(p: Dict[str, Any]) -> str:
    nivel = p.get("intriga") if p.get("intriga") in INTRIGAS else "leve"
    if nivel == "nenhuma":
        if movimentos_ligados(p):
            return ("- 'eventos': sem brigas nem imagens nesta vez — SÓ os movimentos naturais do cinema ('gesto', "
                    "'passa', 'sai'/'volta', chegar atrasado), como nas regras do cinema.\n")
        return "- 'eventos': deixe a lista VAZIA (sem brigas, imagens nem gente saindo nesta vez).\n"
    if not p.get("imagens_destaque", True):
        return ("- ⚡ INTRIGAS SEM IMAGEM: as provocações e discussões ficam nas FALAS (com 'bravo'/'debochado'); em "
                "'eventos' use SÓ 'sai' (alguém sai da sala irritado, foi buscar pipoca) e 'volta' — nada de briga, "
                "interacao, cena, foto ou estilo (as imagens estão desligadas)"
                + (" — no cinema de perto também 'gesto' e 'passa' (os movimentos naturais)" if movimentos_ligados(p) else "")
                + ". 'imagem_en' = \"\", 'duracao' = 0 (ou os segundos do gesto), 'estilo_arte' = \"\", 'gesto' = \"\" (menos em gesto/passa).\n")
    quanto = {"leve": "RARO: no máximo 1 briga no vídeo inteiro, e só se uma provocação passar MUITO do ponto; saídas de cena raras",
              "media": "de vez em quando: umas 1 briga a cada ~3 minutos, quando a provocação esquentar; pode ter quem saia irritado e volte",
              "caos": "SEMPRE: provocação o tempo todo, brigas frequentes (mas não seguidas), gente saindo e voltando"}[nivel]
    return (
        "- ⚡ INTRIGAS ENTRE ELES (estilo visual novel) — " + quanto + ". Como funciona: alguém PROVOCA (fala debochada sobre "
        "o outro, o vídeo ou a obra dele), o outro responde; se ESQUENTA (2–4 falas de ida e volta, com 'bravo'/'debochado'), "
        "pode virar BRIGA: um evento 'briga' no segundo em que ela estoura (ex.: um dá um soco no outro, um voa no pescoço do "
        "outro, guerra de almofada) — o vídeo mostra uma IMAGEM da luta no meio da sala por 'duracao' segundos (3–6) e as "
        "falas continuam por cima (reclamação, 'PAREM!', o que apanhou xingando, os outros torcendo). Depois da briga, as "
        "falas lembram dela (alguém com raiva, rindo, de olho roxo). Use a personalidade: quem é estourado briga, o frio "
        "humilha sem levantar, o medroso se esconde.\n"
        "  NÃO É SÓ BRIGA — os momentos com imagem deixam o react diferenciado, use com criatividade e ligados ao que "
        "acontece no vídeo e na conversa:\n"
        "  · 'interacao' (tela toda): abraço emocionado numa parte triste, toca aqui num momento épico, um consolando o "
        "outro que chorou, os dois cantando juntos o refrão, um deitando no colo do outro de medo.\n"
        "  · 'foto' (um quadro aparece por cima, como foto/print pra EXEMPLIFICAR o que alguém disse): 'imagina o X de "
        "terno no escritório', o personagem mostrando a foto de quando era criança, o rosto de um trocado pelo de outro, "
        "o meme que ele citou, 'eu depois dessa cena:'.\n"
        "  · 'estilo' (QUEBRA DE EXPECTATIVA: o personagem aparece no lugar dele desenhado num estilo de arte bem "
        "diferente por uns segundos): mal desenhado quando passa vergonha, pintura antiga/renascentista quando fala algo "
        "'profundo', hiper detalhado e sério quando fica estiloso/convencido, chibi quando fofo, mangá P&B quando dramático "
        "— escolha 'estilo_arte'; só 1 personagem por evento.\n"
        "  · 'cena' = outro momento especial na sala com imagem (alguém joga pipoca, sobe no sofá, a sala inteira "
        "chorando).\n"
        "  · 'sai' (o personagem SAI da sala — irritado, nocauteado, foi buscar pipoca, foi chamado; NÃO fala nem reage "
        "enquanto estiver fora) e 'volta' (ele volta, normalmente com uma fala na volta).\n"
        + __import__("react_objetos").REGRAS_ROTEIRO +
        "  Fora 'gesto'/'passa', 'gesto' = \"\".\n"
        "  Em cada evento: 'personagens' = os NOMES do elenco envolvidos; 'descricao' = o que acontece, em português, curto; "
        "'imagem_en' = nos eventos com imagem: a descrição da IMAGEM em inglês, concreta e visual (quem faz o quê com "
        "quem, poses, expressões, o auge da ação — sem texto na imagem), \"\" em sai/volta; 'estilo_arte' = o estilo da "
        "imagem (obrigatório em 'estilo'; nos outros pode usar pra piada, ex.: a foto em pintura antiga) ou \"\" pro "
        "normal; 'duracao' = segundos que a imagem fica (3–6) ou 0. Espalhe: não mais que 1 momento com imagem a cada "
        "~40 s.\n")


def prompt_roteiro(p: Dict[str, Any]) -> str:
    elenco = []
    for c in p["personagens"]:
        elenco.append(f"- {c['nome']}" + (f" ({c['obra']})" if c.get("obra") else "")
                      + (f": {c['personalidade']}" if c.get("personalidade") else "")
                      + (f" | jeito de falar: {c['jeito_de_falar']}" if c.get("jeito_de_falar") else "")
                      + (f" | cronologia: {c['cronologia']}" if c.get("cronologia") else "")
                      + (f" | relações com o vídeo: {c['relacoes']}" if c.get("relacoes") else "")
                      + _bib_personagem(c))
    resumo = (p.get("sugestoes") or {}).get("resumo_video") or ""
    return (_contexto_video(p) + (f"\nRESUMO DO VÍDEO: {resumo}" if resumo else "")
            + "\n\nELENCO (sentados no sofá, nesta ordem da esquerda pra direita):\n" + "\n".join(elenco)
            + ("\n\n" + notas_bloco(p) if notas_bloco(p) else ""))


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
    bib = biblia_bloco(p)
    if bib:
        L += ["", bib]
    L += ["", "ELENCO (sentados no sofá, nesta ordem da esquerda pra direita):"]
    for c in p["personagens"]:
        L.append(f"- {c['nome']}" + (f" ({c['obra']})" if c.get("obra") else "")
                 + (f": {c['personalidade']}" if c.get("personalidade") else "")
                 + (f" | jeito de falar: {c['jeito_de_falar']}" if c.get("jeito_de_falar") else "")
                 + (f" | cronologia: {c['cronologia']}" if c.get("cronologia") else "")
                 + (f" | relações com o vídeo: {c['relacoes']}" if c.get("relacoes") else "")
                 + (f" | ⚡ poderes/jeito: {c['poderes']}" if (c.get("poderes") or "").strip() else "")
                 + _bib_personagem(c))
    nb = notas_bloco(p, a, b)
    if nb:
        L += ["", nb]
    rl = regra_lugar(p, a, b)
    if rl:
        L += ["", "NESTA PARTE:", rl.strip()]
    try:
        import react_objetos as RO
        L += ["", "🗺 " + RO.mapa(p, disposicao(p), ingles=False)]
    except Exception:  # noqa: BLE001
        pass
    L += ["", f"## ESTA É A PARTE {k + 1} DE {len(ps)}: do {mmss(a)} ({a:.0f} s) ao {mmss(b)} ({b:.0f} s)",
          f"Escreva umas {max(1, int(round((b - a) / passo)))} falas, com 'tempo' entre {a:.0f} e {b:.0f}, cobrindo o trecho "
          "inteiro até o fim dele.",
          ("PEDIDO DE INSCRIÇÃO: coloque NESTA parte (1 fala, num bom momento)." if _cta_aqui(p, k)
           else "PEDIDO DE INSCRIÇÃO: NÃO coloque nesta parte (fica em outra)."),
          "", "TRANSCRIÇÃO DESTE TRECHO (tempo no vídeo):", transcricao_texto(trans, 12000) or "(sem transcrição — use os quadros)"]
    marcados = [d for d in p.get("destaques") or [] if d.get("ini") is not None and a - 2 <= float(d["ini"]) < b]
    if marcados:
        L += ["", "⭐ VERSOS MARCADOS POR VOCÊ NESTE TRECHO — algum personagem TEM que comentar cada um (citar, elogiar, zoar…):"]
        L += [f"- {mmss(d['ini'])} “{d['texto']}”" for d in marcados]
    lidos = momentos_lidos(p, a, b)
    if lidos:
        L += ["", "👁 O QUE ACONTECE NO VÍDEO NESTE TRECHO (lido dos quadros — use junto da transcrição: a cena, o texto que "
              "aparece na tela e quem aparece; reaja ao que se VÊ, não só à letra):"]
        for m in lidos:
            L.append(f"- {mmss(m['t'])}: {m['o_que_acontece']}" + (f" | na tela: “{m['texto_na_tela']}”" if m["texto_na_tela"] else "")
                     + (f" | aparece: {m['quem_aparece']}" if m["quem_aparece"] else "") + (f" | clima: {m['clima']}" if m["clima"] else ""))
    momentos = [m for m in (p.get("edicao") or {}).get("momentos") or [] if a <= m["ini"] < b]
    if momentos:
        L += ["", "🎬 MOMENTOS DE EDIÇÃO FORTE NESTE TRECHO (muitos cortes seguidos — veja os quadros desses segundos):"]
        L += [f"- {mmss(m['ini'])}–{mmss(m['fim'])}: {m['cortes']} cortes em {max(1, round(m['fim'] - m['ini']))} s" for m in momentos]
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


def marcar_destaque(p: Dict[str, Any], texto: str, ini: Optional[float], marcar: bool = True) -> int:
    """⭐ Verso da letra que um personagem TEM que comentar (marcado na transcrição limpa)."""
    texto = " ".join(str(texto or "").split())[:400]
    lista = [d for d in p.get("destaques") or [] if not (_norm(d["texto"]) == _norm(texto) and d.get("ini") == ini)]
    if marcar and texto:
        lista.append({"texto": texto, "ini": ini})
    p["destaques"] = sorted(lista, key=lambda d: (d.get("ini") is None, d.get("ini") or 0))[:80]
    return len(p["destaques"])


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
        ex2 = _slug(x.get("expressao_depois")) if _slug(x.get("expressao_depois")) in exprs else ""
        falas.append({"id": "f" + secrets.token_hex(3), "t": round(t, 2), "cid": c["id"], "texto": texto, "expressao": ex,
                      "expressao_depois": "" if ex2 == ex else ex2,
                      "dur": duracao_fala(texto), "cta": bool(x.get("pedido_inscricao")), "reacoes": reacoes[:2],
                      "duvida": " ".join(str(x.get("duvida") or "").split())[:300],
                      "destaque": x.get("destaque") if x.get("destaque") in ("letra", "edicao") else ""})
    if not falas:
        raise ReactErro("Nenhuma fala aproveitável (confira os nomes dos personagens).")
    falas = depois_de_ouvir(p, falas)  # 👂 só fala depois de ouvir a frase do vídeo até o fim
    eventos = ler_eventos(p, r.get("eventos") or [], dur_video, janela)
    if janela:
        a, b = janela
        antigas = (p.get("roteiro") or {}).get("falas") or []
        ultima = b >= duracao_total(p) - 0.01
        ficam = [f for f in antigas if not (a <= float(f["t"]) < b or (ultima and float(f["t"]) >= b))]
        resumo = str(r.get("resumo") or "") if not (p.get("roteiro") or {}).get("resumo") else p["roteiro"]["resumo"]
        ev_ficam = [e for e in (p.get("roteiro") or {}).get("eventos") or []
                    if not (a <= float(e["t"]) < b or (ultima and float(e["t"]) >= b))]
        p["roteiro"] = dict(p.get("roteiro") or {}, resumo=resumo[:1000], quando=time.time(), ignoradas=ignoradas,
                            falas=sorted(ficam + falas, key=lambda f: f["t"]),
                            eventos=sorted(ev_ficam + eventos, key=lambda e: e["t"]))
        garantir_notas(p, janela)
        log(p, f"📝 roteiro, {mmss(a)}–{mmss(b)}: {len(falas)} fala(s)" + (f" · {ignoradas} ignorada(s)" if ignoradas else ""))
        return p["roteiro"]
    p["roteiro"] = {"resumo": str(r.get("resumo") or "")[:1000], "falas": falas, "quando": time.time(), "ignoradas": ignoradas,
                    "eventos": eventos}
    garantir_notas(p)
    garantir_cta(p)
    log(p, f"📝 roteiro: {len(p['roteiro']['falas'])} fala(s)" + (f" · {ignoradas} ignorada(s) (nome que não está no elenco)" if ignoradas else ""))
    return p["roteiro"]


# ------------------------------------------------------------------ 📌 marcações (observações / falas pedidas)
def nova_nota(p: Dict[str, Any], t: Any, tipo: str, texto: str, cids: Optional[List[str]] = None, exata: bool = False,
              do_original: bool = True) -> Dict[str, Any]:
    """📌 Uma marcação num segundo. `do_original`: o tempo é do vídeo ORIGINAL (o player) — vira o do vídeo cortado."""
    tt = segundos(t)
    if tt is None:
        raise ReactErro("Diga o tempo (ex.: 1:23).")
    if do_original:
        tt = mapear(tt, removidos(p))
        if tt is None:
            raise ReactErro("Esse tempo está num trecho cortado do vídeo.")
    tipo = tipo if tipo in TIPOS_NOTA else "video"
    texto = " ".join(str(texto or "").split())[:500]
    cs = [c for c in (cids or []) if any(x["id"] == c for x in p["personagens"])][:6]
    if tipo == "fala" and not cs:
        raise ReactErro("Escolha QUEM fala.")
    if not texto and tipo != "aparece":
        raise ReactErro("Escreva a observação (ou a fala).")
    n = {"id": "n" + secrets.token_hex(3), "t": round(float(tt), 2), "tipo": tipo, "texto": texto, "cids": cs,
         "exata": bool(exata) and tipo == "fala"}
    p.setdefault("notas", []).append(n)
    p["notas"].sort(key=lambda x: x["t"])
    return n


def notas_bloco(p: Dict[str, Any], a: Optional[float] = None, b: Optional[float] = None) -> str:
    """As marcações (do trecho a–b) pro pedido do roteiro."""
    ns = [n for n in p.get("notas") or [] if a is None or (a - 3 <= float(n["t"]) < (b if b is not None else 1e9) + 2)]
    if not ns:
        return ""
    nomes = {c["id"]: c["nome"] for c in p["personagens"]}
    L = ["📌 MARCAÇÕES DO AUTOR NESTE TRECHO (obrigatórias — siga cada uma no segundo indicado):"]
    for n in ns:
        quem = ", ".join(nomes.get(c, "?") for c in n.get("cids") or [])
        if n["tipo"] == "fala":
            L.append(f"- {mmss(n['t'])} ({n['t']:.1f} s) · 💬 {quem} DIZ " + (f"EXATAMENTE: “{n['texto']}”" if n.get("exata") else
                                                                            f"uma fala sobre/nessa linha: {n['texto']}"))
        elif n["tipo"] == "quem_fala":
            L.append(f"- {mmss(n['t'])} · 🎤 no vídeo, quem fala/canta aqui: {n['texto']}")
        elif n["tipo"] == "aparece":
            L.append(f"- {mmss(n['t'])} · 👤 aparece no vídeo: {n['texto'] or quem}" + (f" (do elenco: {quem} — ele reage a si mesmo)" if quem and n["texto"] else ""))
        else:
            L.append(f"- {mmss(n['t'])} · 🎬 {n['texto']}" + (f" (quem deve reagir: {quem})" if quem else ""))
    return "\n".join(L)


def garantir_notas(p: Dict[str, Any], janela: Optional[List[float]] = None) -> int:
    """💬 As falas pedidas EXATAS entram no roteiro mesmo se a IA esqueceu (no segundo marcado)."""
    falas = (p.get("roteiro") or {}).get("falas")
    if falas is None:
        return 0
    n_ok = 0
    for n in p.get("notas") or []:
        if n["tipo"] != "fala" or not n.get("exata") or not n.get("cids"):
            continue
        if janela and not (janela[0] - 3 <= n["t"] < janela[1] + 2):
            continue
        alvo = _norm(n["texto"])[:40]
        if any(f["cid"] == n["cids"][0] and abs(float(f["t"]) - n["t"]) < 8 and alvo and alvo in _norm(f["texto"]) for f in falas):
            continue
        falas.append({"id": "f" + secrets.token_hex(3), "t": round(n["t"], 2), "cid": n["cids"][0], "texto": n["texto"][:300],
                      "expressao": "neutro", "expressao_depois": "", "dur": duracao_fala(n["texto"]), "cta": False, "reacoes": [],
                      "duvida": "", "destaque": "", "nota": n["id"]})
        n_ok += 1
    if n_ok:
        falas.sort(key=lambda f: float(f["t"]))
    return n_ok


def ler_eventos(p: Dict[str, Any], lista: Any, dur_video: Optional[float] = None,
                janela: Optional[List[float]] = None) -> List[Dict[str, Any]]:
    """⚡ Os eventos da IA (ou colados): briga / cena (com imagem) e sai / volta (quem está na sala)."""
    out = []
    for x in lista if isinstance(lista, list) else []:
        if not isinstance(x, dict) or x.get("tipo") not in TIPOS_EVENTO:
            continue
        t = segundos(x.get("tempo"))
        cids = []
        for n in x.get("personagens") or []:
            c = achar_por_nome(p, str(n or ""))
            if c and c["id"] not in cids:
                cids.append(c["id"])
        if t is None or (not cids and x["tipo"] != "passa"):
            continue
        if x["tipo"] in EVENTO_COM_IMAGEM and not p.get("imagens_destaque", True):
            continue  # 🖼 imagens desligadas: só sai/volta
        if x["tipo"] in ("gesto", "passa") and not movimentos_ligados(p):
            continue  # 🎬 os movimentos naturais: cinema de perto com a opção ligada
        if dur_video:
            t = min(max(0.0, t), max(0.0, dur_video - 1.0))
        if janela and (t < janela[0] - 5 or t > janela[1] + 5):
            continue
        out.append(novo_evento(x["tipo"], t, cids, x.get("descricao"), x.get("imagem_en"), x.get("duracao"),
                               estilo_arte=x.get("estilo_arte"), gesto=x.get("gesto")))
    return sorted(out, key=lambda e: e["t"])


def novo_evento(tipo: str, t: float, cids: List[str], descricao: Any = "", imagem_en: Any = "", duracao: Any = None,
                eid: Optional[str] = None, estilo_arte: Any = "", gesto: Any = "") -> Dict[str, Any]:
    com_img = tipo in EVENTO_COM_IMAGEM
    d = segundos(duracao) if duracao is not None else None
    arte = estilo_arte if estilo_arte in ESTILOS_ARTE else ""
    if tipo == "estilo" and not arte:
        arte = "mal_desenhado"
    if tipo in ("gesto", "passa"):  # 🎬 movimento natural: sem imagem, dura uns segundos
        g = gesto if gesto in (GESTOS if tipo == "gesto" else PASSANTE) else ("pega_pipoca" if tipo == "gesto" else "silhueta")
        return {"id": eid or ("e" + secrets.token_hex(3)), "tipo": tipo, "t": round(float(t), 2),
                "cids": list(cids)[:2] if tipo == "gesto" else [], "gesto": g,
                "descricao": " ".join(str(descricao or "").split())[:400], "imagem_en": "", "estilo_arte": "",
                "dur": round(max(1.5, min(8.0, d or (3.0 if tipo == "gesto" else 3.5))), 2), "cena": {}}
    return {"id": eid or ("e" + secrets.token_hex(3)), "tipo": tipo, "t": round(float(t), 2),
            "cids": list(cids)[:1 if tipo == "estilo" else 6],
            "descricao": " ".join(str(descricao or "").split())[:400],
            "imagem_en": " ".join(str(imagem_en or "").split())[:900] if com_img else "",
            "estilo_arte": arte if com_img else "",
            "dur": round(max(1.5, min(12.0, d or 4.5)), 2) if com_img else 0.0, "cena": {}}


def eventos(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sorted((p.get("roteiro") or {}).get("eventos") or [], key=lambda e: float(e["t"]))


ABERTURA_S = 8.0     # 🚪 a abertura: os primeiros segundos (chegam um por um)
ENCERRAMENTO_S = 8.0  # 👋 o encerramento: os últimos segundos (saem um por um)


def chegadas(p: Dict[str, Any]) -> Dict[str, float]:
    """🚪 cid → o segundo em que ele chega (abertura ligada): um por um, na ordem de quem senta da esquerda pra direita."""
    if not p.get("abertura"):
        return {}
    ordem = [c for g in sofas_de(p, layout_de(p)) for c in g]
    passo = min(1.2, (ABERTURA_S - 1.5) / max(1, len(ordem)))
    return {cid: round(0.6 + passo * k, 2) for k, cid in enumerate(ordem)}


def saidas(p: Dict[str, Any], duracao: float) -> Dict[str, float]:
    """👋 cid → o segundo em que ele sai (encerramento ligado): um por um, a partir de ~7 s antes do fim."""
    if not p.get("encerramento") or duracao <= ENCERRAMENTO_S:
        return {}
    ordem = [c for g in sofas_de(p, layout_de(p)) for c in g]
    passo = min(1.0, (ENCERRAMENTO_S - 2.0) / max(1, len(ordem)))
    ini = duracao - ENCERRAMENTO_S + 2.0
    return {cid: round(ini + passo * k, 2) for k, cid in enumerate(ordem)}


def ausencias(p: Dict[str, Any], duracao: float) -> Dict[str, List[List[float]]]:
    """🚪 cid → [[saiu, voltou], …]: quando cada personagem está FORA da sala (some do sofá) — os eventos sai/volta e,
    se ligados, a abertura (antes de chegar) e o encerramento (depois de sair)."""
    out: Dict[str, List[List[float]]] = {}
    for cid, t in chegadas(p).items():
        out.setdefault(cid, []).append([0.0, t])
    for cid, t in saidas(p, duracao).items():
        out.setdefault(cid, []).append([t, max(t, duracao)])
    fora: Dict[str, float] = {}
    ja_voltou: set = set()
    for e in eventos(p):
        for cid in e["cids"]:
            if e["tipo"] == "sai" and cid not in fora:
                fora[cid] = float(e["t"])
            elif e["tipo"] == "volta" and cid in fora:
                out.setdefault(cid, []).append([fora.pop(cid), float(e["t"])])
            elif e["tipo"] == "volta" and cid not in ja_voltou and not any(x["tipo"] == "sai" and cid in x["cids"]
                                                                           and float(x["t"]) < float(e["t"]) for x in eventos(p)):
                ini0 = chegadas(p).get(cid, 0.0)  # ⏰ volta sem sai antes = CHEGOU ATRASADO: fora desde o começo
                out.setdefault(cid, []).append([ini0, float(e["t"])])
            if e["tipo"] == "volta":
                ja_voltou.add(cid)
    for cid, a in fora.items():
        out.setdefault(cid, []).append([a, max(a, duracao)])
    return out


def presente(aus: Dict[str, List[List[float]]], cid: str, t: float) -> bool:
    return not any(a <= t < b for a, b in aus.get(cid, []))


def recortar_presenca(trechos: List[Dict[str, Any]], fora: List[List[float]]) -> List[Dict[str, Any]]:
    """Tira de cada trecho [start, end] os intervalos em que o personagem está fora da sala."""
    out = []
    for e in trechos:
        pedacos = [[e["start"], e["end"]]]
        for a, b in fora:
            novo = []
            for x, y in pedacos:
                if b <= x or a >= y:
                    novo.append([x, y])
                    continue
                if a > x:
                    novo.append([x, a])
                if b < y:
                    novo.append([b, y])
            pedacos = novo
        for x, y in pedacos:
            if y - x >= 0.1:
                out.append(dict(e, start=round(x, 3), end=round(y, 3)))
    return out


def cena_ativa(p: Dict[str, Any], t: float, exibicao: str = "tela") -> Optional[Dict[str, Any]]:
    if not p.get("imagens_destaque", True):
        return None
    return next((e for e in eventos(p) if EXIBICAO.get(e["tipo"]) == exibicao
                 and float(e["t"]) <= t < float(e["t"]) + float(e["dur"])), None)


def estilos_no_lugar(p: Dict[str, Any], base: str = _BASE) -> Dict[str, List[Tuple[float, float, str]]]:
    """🎨 cid → [(ini, fim, imagem)]: quando o personagem aparece desenhado diferente no lugar dele."""
    out: Dict[str, List[Tuple[float, float, str]]] = {}
    if not p.get("imagens_destaque", True):
        return out
    for e in eventos(p):
        if e["tipo"] != "estilo" or not e["cids"]:
            continue
        cam = arquivo_cena(p, e, base)
        if cam:
            out.setdefault(e["cids"][0], []).append((float(e["t"]), float(e["t"]) + float(e["dur"]), cam))
    return out


# ------------------------------------------------------------------ 🎬 cinema de perto: gestos, quem anda, quem passa
def movimentos_ligados(p: Dict[str, Any]) -> bool:
    """🍿 Os movimentos naturais (opcional, desligado por padrão) — só no cinema de perto."""
    return layout_de(p) == "cinema_plateia" and bool(p.get("movimentos"))


def gestos_no_lugar(p: Dict[str, Any], lay: Dict[str, Any], base: str = _BASE) -> Tuple[Dict[str, List[Tuple[float, float, str, bool, str]]], List[str]]:
    """🍿 cid → [(ini, fim, pose, espelhar, gesto)]: a pose do gesto no lugar dele (virada pro vizinho com quem ele
    interage — a pose é feita olhando pra direita; o vizinho na esquerda = espelhada). + os avisos de pose que falta."""
    out: Dict[str, List[Tuple[float, float, str, bool, str]]] = {}
    faltam: List[str] = []
    if not movimentos_ligados(p):
        return out, faltam
    pos = {a["cid"]: a for a in lay.get("assentos") or []}
    for e in eventos(p):
        if e["tipo"] != "gesto" or not e["cids"] or e["cids"][0] not in pos:
            continue
        a = pos[e["cids"][0]]
        c = next((x for x in p["personagens"] if x["id"] == a["cid"]), None)
        if not c:
            continue
        x = poses_do_personagem(c, base, "frente").get(e.get("gesto") or "")
        if not x:
            faltam.append(f"{c['nome']}: sem a pose {GESTOS.get(e.get('gesto') or '', ('?',))[0]} ainda (🧍 Gerar o que falta) — "
                          f"o gesto em {mmss(e['t'])} ficou só nas falas")
            continue
        outro = pos.get(e["cids"][1]) if len(e["cids"]) > 1 else None
        esp = (outro["cx"] < a["cx"]) if outro else a["cx"] > W / 2
        out.setdefault(a["cid"], []).append((float(e["t"]), float(e["t"]) + float(e.get("dur") or 3.0), x["pose"], esp,
                                             e.get("gesto") or ""))
    return out, faltam


def faixa_andar(fila: int) -> Tuple[float, float]:
    """(cy, largura) de quem anda EM PÉ pela fileira (o quadro 2:3 da pose; a figura ocupa 95%)."""
    s = 1.0 if fila == 0 else PLATEIA["escala_tras"]
    png_h = 0.81 * H * s
    cabeca = (0.36 if fila == 0 else 0.41) * H
    return cabeca - 0.05 * png_h + png_h / 2, png_h / 1.5


def silhueta(origem: Optional[str], destino: str) -> str:
    """🌑 A sombra escura de quem passa: a figura em preto (ou um vulto genérico, sem imagem)."""
    from PIL import Image, ImageDraw, ImageFilter
    if origem and os.path.isfile(origem):
        im = Image.open(origem).convert("RGBA")
        alfa = im.getchannel("A").point(lambda v: int(v * 0.96))
        sombra = Image.new("RGBA", im.size, (10, 8, 14, 0))
        sombra.putalpha(alfa)
        sombra.filter(ImageFilter.GaussianBlur(1.2)).save(destino)
        return destino
    im = Image.new("RGBA", (1200, 1800), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cor = (10, 8, 14, 245)
    d.ellipse([500, 110, 700, 330], fill=cor)                       # cabeça
    d.rounded_rectangle([420, 330, 780, 1060], 120, fill=cor)       # tronco (meio curvado)
    d.polygon([(760, 420), (900, 700), (860, 740), (720, 520)], fill=cor)  # braço com o copo
    d.rounded_rectangle([850, 640, 930, 780], 20, fill=cor)
    d.polygon([(450, 1000), (600, 1000), (520, 1700), (400, 1700)], fill=cor)  # pernas (andando)
    d.polygon([(600, 1000), (760, 1000), (840, 1700), (700, 1700)], fill=cor)
    im.filter(ImageFilter.GaussianBlur(1.5)).save(destino)
    return destino


def _passos(a: float, b: float) -> List[Dict[str, float]]:
    """O sobe-e-desce de quem anda (um pulinho a cada passo)."""
    out, t = [], a
    while t + 0.2 < b:
        out.append({"a": round(t, 3), "b": round(min(b, t + 0.36), 3), "pulo": 0.007})
        t += 0.36
    return out


def andantes(p: Dict[str, Any], lay: Dict[str, Any], dur: float, base: str = _BASE) -> Tuple[List[Dict[str, Any]], List[str]]:
    """🚶 Cinema de perto: quem ANDA pela fileira — chegando (abertura, 'volta', chegou atrasado) da ponta mais perto até
    a poltrona, saindo (encerramento, 'sai') da poltrona até a ponta — e 🌑 quem PASSA na frente ('passa'). Cada um:
    {cid, nome, cam, fila, cx, cy, w, espelhar, a, b, de, para (fração de W somada ao cx)}."""
    out: List[Dict[str, Any]] = []
    avisos: List[str] = []
    if not movimentos_ligados(p):
        return out, avisos
    pos = {a["cid"]: a for a in lay.get("assentos") or []}
    vel = 0.42 * W
    sem_andando: set = set()

    def caminho(cid: str, t: float, chegando: bool) -> None:
        a = pos.get(cid)
        c = next((x for x in p["personagens"] if x["id"] == cid), None)
        if not a or not c:
            return
        borda = -0.12 * W if a["cx"] < W / 2 else 1.12 * W
        d = max(1.2, min(3.0, abs(a["cx"] - borda) / vel))
        ini, fim = (max(0.0, t - d), t) if chegando else (t, min(dur, t + d))
        if fim - ini < 0.3:
            return
        de, para = (borda, a["cx"]) if chegando else (a["cx"], borda)
        if chegando and t - d < 0:  # começou antes do vídeo: já entra no meio do caminho
            de = a["cx"] + (borda - a["cx"]) * (fim - ini) / d
        poses = poses_do_personagem(c, base, "frente")
        x = poses.get("andando")
        if x:
            cy, w = faixa_andar(a.get("fila", 0))
        else:
            x = poses.get("neutro") or next(iter(poses.values()), None)
            cy, w = a["cy"], a["w"]
            sem_andando.add(c["nome"])
        if not x:
            return
        out.append({"cid": cid, "nome": c["nome"], "cam": x["pose"], "fila": a.get("fila", 0), "cx": a["cx"], "cy": cy,
                    "w": w, "espelhar": para < de, "a": round(ini, 3), "b": round(fim, 3),
                    "de": (de - a["cx"]) / W, "para": (para - a["cx"]) / W})

    for cid, t in chegadas(p).items():
        caminho(cid, t, True)
    for cid, t in saidas(p, dur).items():
        caminho(cid, t, False)
    for e in eventos(p):
        if e["tipo"] in ("sai", "volta"):
            for cid in e["cids"]:
                caminho(cid, float(e["t"]), e["tipo"] == "volta")
        elif e["tipo"] == "passa":
            img = camada_papel(p, "passante", base)
            modo = e.get("gesto") if e.get("gesto") in PASSANTE else "silhueta"
            d_c = os.path.join(pasta(p["id"], base), "cenario")
            os.makedirs(d_c, exist_ok=True)
            if modo == "silhueta" or not img:
                if modo == "inteiro":
                    avisos.append(f"🚶 quem passa em {mmss(e['t'])}: sem a camada {ROTULO_CAMADA['cine_passante']} — passou a silhueta")
                nome_s = "silhueta_" + (os.path.basename(img) if img else "generica.png")
                cam = os.path.join(d_c, nome_s)
                if not os.path.isfile(cam):
                    silhueta(img, cam)
            else:
                cam = img
            cy, w = faixa_andar(0)
            iw, ih = _tam(cam, (2, 3))
            w = min(w * 1.08, 0.81 * H * 1.08 * iw / max(1, ih))
            pra_dir = int(e["id"][-1], 16) % 2 == 0 if e["id"][-1] in "0123456789abcdef" else True
            a_t = float(e["t"])
            out.append({"cid": "", "nome": "🌑 Silhueta" if cam != img else "🚶 Alguém passando", "cam": cam, "fila": 0,
                        "cx": W / 2, "cy": cy + 0.02 * H, "w": w, "espelhar": not pra_dir, "a": round(a_t, 3),
                        "b": round(min(dur, a_t + float(e.get("dur") or 3.5)), 3),
                        "de": -0.68 if pra_dir else 0.68, "para": 0.68 if pra_dir else -0.68})
    if sem_andando:
        avisos.append(f"{', '.join(sorted(sem_andando))}: ainda sem a pose 🚶 andando (🧍 Gerar o que falta) — entrou/saiu "
                      "deslizando sentado")
    return out, avisos


def arquivo_cena(p: Dict[str, Any], e: Dict[str, Any], base: str = _BASE) -> Optional[str]:
    arq = (e.get("cena") or {}).get("arquivo")
    cam = os.path.join(pasta(p["id"], base), "cenas", arq) if arq else ""
    return cam if arq and os.path.isfile(cam) else None


def evento(p: Dict[str, Any], eid: str) -> Dict[str, Any]:
    e = next((x for x in (p.get("roteiro") or {}).get("eventos") or [] if x["id"] == eid), None)
    if not e:
        raise ReactErro("Evento não encontrado.")
    return e


def salvar_eventos(p: Dict[str, Any], lista: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Os eventos editados na página (mantém a imagem de quem já tinha)."""
    velhos = {e["id"]: e for e in (p.get("roteiro") or {}).get("eventos") or []}
    ids = {c["id"] for c in p["personagens"]}
    novos = []
    for x in lista or []:
        if not isinstance(x, dict) or x.get("tipo") not in TIPOS_EVENTO:
            continue
        t = segundos(x.get("t"))
        cids = [c for c in x.get("cids") or [] if c in ids]
        if t is None or (not cids and x["tipo"] != "passa"):
            continue
        eid = str(x.get("id") or "")[:12] or None
        e = novo_evento(x["tipo"], t, cids, x.get("descricao"), x.get("imagem_en"), x.get("dur"), eid, x.get("estilo_arte"),
                        x.get("gesto"))
        if eid in velhos:
            e["cena"] = velhos[eid].get("cena") or {}
        novos.append(e)
    p.setdefault("roteiro", {})["eventos"] = sorted(novos, key=lambda e: e["t"])
    return p["roteiro"]["eventos"]


def prompt_cena(p: Dict[str, Any], e: Dict[str, Any]) -> str:
    est = estilo_final(p)
    quem = []
    for cid in e["cids"]:
        c = next((x for x in p["personagens"] if x["id"] == cid), None)
        if c:
            quem.append(f"{c['nome']}" + (f" from {c['obra']}" if c.get("obra") else "")
                        + (f" ({c['aparencia_en']})" if c.get("aparencia_en") else ""))
    outros = [c["nome"] for c in p["personagens"] if c["id"] not in e["cids"]]
    acao = e.get("imagem_en") or e.get("descricao") or "a funny moment"
    arte = ESTILO_ARTE_EN.get(e.get("estilo_arte") or "")
    estilo_txt = (f"ART STYLE (on purpose, for comedic contrast): {arte}" if arte else ESTILO_TXT[est])
    if e["tipo"] == "estilo":
        return (f"{'; '.join(quem)}, sitting (as if on a sofa seat) seen from the FRONT, knees cut at the bottom of the "
                f"image, the same outfit as in the reference image, {acao}. {estilo_txt}. The figure is isolated on a "
                "flat solid chroma-key green background (#00FF00), no sofa, no furniture, no floor, no text.")[:3900]
    if e["tipo"] == "foto":
        return ("A single picture used as a visual example inserted in a reaction video (like a photo or meme that pops "
                f"up): {acao}. Characters: {'; '.join(quem)} — each one recognizable as in the reference image (same face, "
                f"hair, outfit) unless the description says to change it. "
                + (__import__("react_objetos").poderes_en(p, e["cids"]) + " ") + f"{estilo_txt}. No text, no captions.")[:3900]
    import react_objetos as RO
    try:
        mapa = RO.mapa(p, disposicao(p)) + " "
    except Exception:  # noqa: BLE001
        mapa = ""
    if layout_de(p) in CINEMA:
        lugar = ("a scene inside the SAME dark movie theater of the reference: the BIG top image of the reference is the "
                 "CURRENT FRAME of the reaction video — keep that theater, the rows of red cinema seats, the glow of the big "
                 "screen, the cinema snacks they hold, and keep every character in their own seat unless the action moves "
                 "them (the camera may move inside the theater to show their faces). ")
    else:
        lugar = ("a scene inside the SAME cozy streamer living room of the reference: the BIG top image of the reference is "
                 "the CURRENT FRAME of the reaction video — keep that room, the sofas, the coffee tables and the items on "
                 "them, the TV, and keep every character in their own seat unless the action moves them. ")
    return ("Visual novel CG illustration, wide 16:9, " + lugar + mapa + "ACTION: " + acao + ". "
            "Characters in the action: " + "; ".join(quem) + ". " + (RO.poderes_en(p, e["cids"]) + " " if RO.poderes_en(p, e["cids"]) else "")
            + (f"In the background, the others react ({', '.join(outros)}). " if outros else "")
            + "Each character must look exactly like in the reference image (same face, hair, outfit). Expressive poses, "
            "dynamic composition; no text, no speech bubbles, no captions. " + estilo_txt + ".")[:3900]


def colagem_referencia(p: Dict[str, Any], e: Dict[str, Any], destino: str, base: str = _BASE) -> Optional[str]:
    """Uma imagem só de referência pro Flow: a sala (o fundo) em cima e os personagens do evento embaixo, lado a lado."""
    from PIL import Image
    tela = Image.new("RGB", (1920, 1080), (24, 24, 28))
    fundo = camada_arquivo(p, "fundo", base)
    if EXIBICAO.get(e["tipo"]) == "tela":  # 🗺 o QUADRO ATUAL do react (quem está onde, as mesas, os itens) em vez da sala vazia
        try:
            q = destino + ".quadro.jpg"
            previa(p, base, q, max(0.0, float(e["t"]) - 0.2), legenda=False)
            fundo = q
        except Exception:  # noqa: BLE001
            pass
    if fundo:
        tela.paste(Image.open(fundo).convert("RGB").resize((1152, 648)), (384, 0))
    fotos = []
    for cid in e["cids"]:
        c = next((x for x in p["personagens"] if x["id"] == cid), None)
        if not c:
            continue
        poses = poses_do_personagem(c, base, "dir")
        cam = (poses.get("neutro") or (next(iter(poses.values())) if poses else {}) or {}).get("pose")
        if not cam:
            cam = next((os.path.join(pasta(p["id"], base), "refs", r) for r in c.get("refs") or []
                        if os.path.isfile(os.path.join(pasta(p["id"], base), "refs", r))), None)
        if cam:
            fotos.append(cam)
    if not fotos and not fundo:
        return None
    if fotos:
        larg = 1920 // len(fotos)
        for k, cam in enumerate(fotos):
            im = Image.open(cam).convert("RGBA")
            esc = min((larg - 20) / im.width, 420 / im.height)
            im = im.resize((max(1, int(im.width * esc)), max(1, int(im.height * esc))))
            tela.paste(im, (k * larg + (larg - im.width) // 2, 1080 - im.height - 6), im)
    tela.save(destino, "PNG")
    return destino


def guardar_cena(p: Dict[str, Any], e: Dict[str, Any], img, base: str = _BASE, origem: str = "flow") -> str:
    from PIL import Image
    d = os.path.join(pasta(p["id"], base), "cenas")
    os.makedirs(d, exist_ok=True)
    if EXIBICAO.get(e["tipo"]) != "tela":
        if e["tipo"] == "estilo":  # o personagem recortado (fundo verde → transparente)
            tem_alfa = img.mode in ("RGBA", "LA") and img.getchannel("A").getextrema()[0] < 250
            if tem_alfa:
                im = img.convert("RGBA")
                caixa = im.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
                im = im.crop(caixa) if caixa else im
            else:
                try:
                    im = recortar_verde(img.convert("RGB"))
                except ReactErro:
                    im = img.convert("RGBA")
        else:
            im = img.convert("RGB")
            k = min(1600 / im.width, 1600 / im.height, 1.0)
            im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
        arq = f"{e['id']}_{secrets.token_hex(3)}.png"
        im.save(os.path.join(d, arq))
        cena = e.setdefault("cena", {})
        cena.update(arquivo=arq, estado="pronta", erro=None, msg=None, origem=origem,
                    versoes=([arq] + [v for v in cena.get("versoes") or [] if v != arq])[:6])
        return arq
    im = img.convert("RGB")
    k = max(W / im.width, H / im.height)
    im = im.resize((max(W, round(im.width * k)), max(H, round(im.height * k))), Image.LANCZOS)
    x, y = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((x, y, x + W, y + H))
    arq = f"{e['id']}_{secrets.token_hex(3)}.jpg"
    im.save(os.path.join(d, arq), "JPEG", quality=92)
    cena = e.setdefault("cena", {})
    cena.update(arquivo=arq, estado="pronta", erro=None, msg=None, origem=origem,
                versoes=([arq] + [v for v in cena.get("versoes") or [] if v != arq])[:6])
    return arq


def gerar_cenas(pid: str, base: str = _BASE, eids: Optional[List[str]] = None, pedido: str = "") -> Dict[str, Any]:
    """🚀 As imagens das brigas/cenas pro Flow em massa (com a sala e os personagens de referência)."""
    import flow_lote
    with _TRAVA:
        p = carregar(pid, base)
        if not p.get("imagens_destaque", True):
            raise ReactErro("As imagens de destaque estão desligadas (🖼 no Roteiro) — ligue pra gerar.")
        alvo = [e for e in eventos(p) if e["tipo"] in EVENTO_COM_IMAGEM
                and ((eids and e["id"] in eids) or (not eids and not arquivo_cena(p, e, base)))]
        if not alvo:
            raise ReactErro("Nenhuma cena pra gerar (as brigas/cenas já têm imagem).")
        d = os.path.join(pasta(pid, base), "cenas")
        os.makedirs(d, exist_ok=True)
        itens = []
        for e in alvo:
            pr = prompt_cena(p, e)
            if pedido:
                pr = (pr + " CHANGE FROM THE PREVIOUS VERSION: " + " ".join(str(pedido).split())[:400])[:3990]
            it = {"prompt": pr, "tipo": "imagem", "origem": "react"}
            ref = colagem_referencia(p, e, os.path.join(d, f"_ref_{e['id']}.png"), base)
            if ref:
                it["referencia_arquivo"] = ref
            itens.append(it)
        lote = flow_lote.lote()
        novos: List[Dict[str, Any]] = [{}] * len(alvo)
        for prop in ("16:9", "3:4", "4:3"):
            ks = [k for k, e in enumerate(alvo) if {"estilo": "3:4", "foto": "4:3"}.get(e["tipo"], "16:9") == prop]
            if not ks:
                continue
            try:
                feitos = lote.adicionar([itens[k] for k in ks], proporcao=prop, quantidade="x1")
            except ValueError as exc:
                raise ReactErro(str(exc))
            for k, j in zip(ks, feitos):
                novos[k] = j
        for e, j, it in zip(alvo, novos, itens):
            ev = evento(p, e["id"])
            ev.setdefault("cena", {}).update(estado="fila", job=j["id"], erro=None, prompt=it["prompt"], msg="⏳ na fila do Flow")
        log(p, f"👊 {len(alvo)} cena(s) de intriga pro Flow")
        salvar(p, base)
    aviso = ""
    try:
        lote.iniciar()
    except Exception as exc:  # noqa: BLE001
        aviso = f"o Flow em massa não ligou agora ({str(exc)[:160]}) — ▶ Continuar na aba Flow"
    return {"ok": True, "enviadas": len(alvo), "aviso": aviso}


def acompanhar_cenas(pid: str, base: str = _BASE) -> bool:
    import flow_lote
    p = carregar(pid, base)
    if not any((e.get("cena") or {}).get("estado") in ("fila", "gerando") for e in eventos(p)):
        return False
    lote = flow_lote.lote()
    with lote.trava:
        fila = {j["id"]: dict(j) for j in lote.fila}
        rodando = lote.rodando
    mudou = False
    with _TRAVA:
        p = carregar(pid, base)
        for e in (p.get("roteiro") or {}).get("eventos") or []:
            c = e.get("cena") or {}
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
                            guardar_cena(p, e, Image.open(orig), base)
                            ok = True
                            break
                    except Exception as exc:  # noqa: BLE001
                        c.update(estado="erro", erro=f"a imagem chegou mas não deu pra guardar: {str(exc)[:160]}")
                if ok:
                    log(p, f"✔ cena {mmss(e['t'])} pronta")
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
            e["cena"] = c
            if (c.get("estado"), c.get("msg")) != antes:
                mudou = True
        if mudou:
            salvar(p, base)
    return mudou


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
    try:
        with _TRAVA:
            p = carregar(pid, base)
            if analisar_edicao(p, base, on_log):
                salvar(p, base)
    except Exception:  # noqa: BLE001 — sem a análise da edição o roteiro sai do mesmo jeito
        pass
    if _video_local(p, base) and (p.get("leitura_auto", True)):
        for k in alvo:  # 👁 a IA assiste ao trecho antes de escrever (só o que ainda não foi lido)
            try:
                ler_video(pid, base, ps[k][0], ps[k][1], on_log=on_log)
            except Exception:  # noqa: BLE001 — sem a leitura o roteiro sai só com a transcrição e os quadros
                break
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


ESCUTA_FOLGA = 0.3   # 👂 depois que a frase do vídeo acaba, uma respiração e aí fala
ESCUTA_MAX = 7.0     # se a frase do vídeo é muito longa, não empurra mais que isso


def escutar_ligado(p: Dict[str, Any]) -> bool:
    return p.get("escutar", True) is not False


def depois_de_ouvir(p: Dict[str, Any], falas: List[Dict[str, Any]], forcar: bool = False) -> List[Dict[str, Any]]:
    """👂 v84_245: o personagem ESCUTA a frase do vídeo até o fim e só então comenta — a fala que caía no meio de uma
    frase (da letra/da fala do vídeo) vai pra logo depois dela. As que já passaram por aqui ("ouviu") ou que você pôs
    o tempo à mão ficam como estão (forcar=True refaz)."""
    if not escutar_ligado(p):  # desligado: volta pro segundo que a IA escolheu (o que você mexeu à mão fica)
        return sorted([dict(f, t=f["t_ia"]) if "t_ia" in f else dict(f) for f in falas], key=lambda x: float(x["t"]))
    frases = sorted([(float(e["ini"]), float(e.get("fim") or e["ini"])) for e in p.get("transcricao") or []
                     if e.get("ini") is not None and e.get("tipo") != "credito" and float(e.get("fim") or 0) > float(e["ini"])])
    out = []
    for f in falas:
        f = dict(f)
        if f.get("ouviu") and not forcar:
            out.append(f)
            continue
        t0 = float(f.get("t_ia", f["t"])) if forcar else float(f["t"])
        t = t0
        for ini, fim in frases:
            if ini + 0.05 <= t < fim - 0.05:  # caiu no meio da frase
                if fim + ESCUTA_FOLGA - t <= ESCUTA_MAX:
                    t = fim + ESCUTA_FOLGA
                break
            if ini > t:
                break
        if abs(t - t0) > 0.01:
            f["t_ia"] = round(t0, 2)
            f["t"] = round(t, 2)
        f["ouviu"] = True
        out.append(f)
    return sorted(out, key=lambda x: float(x["t"]))


def falas_no_tempo(p: Dict[str, Any], falas: List[Dict[str, Any]], dur_video: Optional[float] = None) -> List[Dict[str, Any]]:
    """As falas como vão pro vídeo: 👂 depois de ouvir a frase + uma legenda de cada vez."""
    return ajustar_falas(depois_de_ouvir(p, falas), dur_video)


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
    bib = biblia_bloco(p, 12000)
    if bib:
        L += ["", "## 📖 Bíblia (o material que o usuário juntou da obra — use como FONTE junto da internet; se a internet "
                  "contradisser a bíblia, aponte em \"problema\" mas siga a bíblia quando a obra for pouco documentada)", bib]
    L += ["", "## Fichas dos personagens"]
    for c in p["personagens"]:
        L.append(f"- {c['nome']}" + (f" ({c['obra']})" if c.get("obra") else "") + ":"
                 + "".join(f"\n    {k}: {c.get(k)}" for k in ("personalidade", "jeito_de_falar", "cronologia", "relacoes") if c.get(k))
                 + (f"\n    📖 bíblia do personagem (do usuário): {c['biblia']}" if c.get("biblia") else ""))
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
LADOS = {"dir": "olhando pra direita →", "esq": "← olhando pra esquerda", "costas": "🎬 de costas (cinema)",
         "frente": "🎬 de frente (cinema)"}
_VIRADO = {"dir": "body and face turned three-quarters toward the viewer's RIGHT, as if watching a TV on that side",
           "esq": "body and face turned three-quarters toward the viewer's LEFT, as if watching a TV on that side",
           "frente": "facing the viewer straight on, looking slightly up at a big cinema screen right above the camera, the "
                     "face lit by the cold light of the screen"}
# 🎬 de costas (cinema): só o corpo fala — poucas poses, cada expressão vira a mais parecida
EXPR_COSTAS = {
    "neutro": ("🎬 de costas, assistindo", "seen from BEHIND, sitting still and watching the big screen ahead"),
    "feliz": ("🎬 de costas, rindo", "seen from BEHIND, shoulders shaking with laughter, head tilted back a little"),
    "chocado": ("🎬 de costas, levou um susto", "seen from BEHIND, jumping back in the seat with a start, both hands raised"),
    "bravo": ("🎬 de costas, bravo", "seen from BEHIND, leaning forward and shaking a fist at the screen"),
    "falando": ("🎬 virando pro lado, falando", "seen from BEHIND but with the head turned to the side in PROFILE, talking to "
                "the person in the next seat, mouth visible"),
}
_COSTAS_DE = {"feliz": "feliz", "empolgado": "feliz", "apaixonado": "feliz", "chocado": "chocado", "assustado": "chocado",
              "bravo": "bravo"}


def expr_lado(ex: str, lado: str, falando: bool = False) -> str:
    """A pose certa pra expressão no lado: de costas, quem fala vira o rosto (perfil); o resto vira a mais parecida."""
    if lado != "costas":
        return ex
    return "falando" if falando else _COSTAS_DE.get(ex, "neutro")


def arquivo_pose(sl: str, expressao: str, lado: str = "dir") -> str:
    """O arquivo da pose: "goku_feliz.png" (virado pra direita — o padrão) / "goku_feliz_esq.png"."""
    return f"{sl}_{expressao}{'_' + lado if lado in ('esq', 'costas', 'frente') else ''}.png"


def lado_da_pose(sl: str, arquivo: str) -> Tuple[str, str]:
    """"goku_feliz_esq.png" → ("feliz", "esq")."""
    nome = arquivo[len(sl) + 1:-4] if arquivo.startswith(sl + "_") else arquivo[:-4]
    for suf in ("esq", "costas", "frente"):
        if nome.endswith("_" + suf):
            return nome[:-len(suf) - 1], suf
    return nome, "dir"


def lados_precisos(p: Dict[str, Any], cid: str, base: str = _BASE) -> List[str]:
    """Pra que lado o personagem olha na disposição atual (sofá da direita nos 2 sofás = pra esquerda; cinema: de
    costas ou de frente)."""
    if layout_de(p) == "cinema_costas":
        return ["costas"]
    if layout_de(p) in ("cinema_frente", "cinema_plateia"):
        return ["frente"]
    try:
        a = next((x for x in disposicao(p, base)["assentos"] if x["cid"] == cid), None)
    except Exception:  # noqa: BLE001
        a = None
    return ["esq" if a and a.get("espelhar") else "dir"]


def poses_json(p: Dict[str, Any], c: Dict[str, Any], lados: Optional[List[str]] = None) -> Dict[str, Any]:
    """O JSON de poses (personagens_pod_v1) do personagem SENTADO, uma pose por expressão e por LADO que ele olha
    (virado pra direita = o padrão; pra esquerda = sofá da direita nos 2 sofás). Gerar o outro lado em vez de
    espelhar: cabelo repartido, cicatriz, símbolo na roupa e texto continuam do lado certo."""
    lados = [l for l in ("dir", "esq", "frente", "costas") if l in (lados or ["dir"])] or ["dir"]
    est = estilo_final(p)
    exprs = [e for e in (p.get("expressoes") or EXPRESSOES_PADRAO) if e in EXPRESSOES]
    if "neutro" not in exprs:
        exprs = ["neutro"] + exprs
    sl = _slug(c["nome"])
    aparencia = c.get("aparencia_en") or f"the character {c['nome']}" + (f" from {c['obra']}" if c.get("obra") else "")
    trava = (f"CHARACTER LOCK: {c['nome']}" + (f" from {c['obra']}" if c.get("obra") else "") + f". Appearance: {aparencia}. "
             "Keep exactly the same face, hairstyle, eye color, outfit and colors in every image.")
    estilo = ("ART STYLE: " + ESTILO_TXT[est] + ("." if est == "anime" else ". Keep the person looking like the reference."))
    regras = ("Framing: the character is SITTING on an invisible seat as if on a couch or a cinema seat (the pose says from "
              "where we see them: three-quarters, from the front or from BEHIND); seen from the front or three-quarters: head, "
              "both arms, torso and the thighs/knees visible, cropped around the knees at the bottom edge; seen from behind: "
              "the back of the head, shoulders and upper back, cropped at the waist; whole head and hair inside the image with "
              "margin. Do NOT draw the couch, chair, seat, table, TV or any other object. ONE single figure, no text, no panels, "
              "on a flat solid chroma-key green background (#00FF00), no shadow on the background.")
    poses = []
    mestre_lado = next((l for l in lados if l != "costas"), lados[0])
    for lado in lados:
        if lado == "costas":  # 🎬 de costas: o conjunto pequeno (o corpo é que mostra a reação)
            for k, (e, (rot, en)) in enumerate(EXPR_COSTAS.items()):
                poses.append({"arquivo": arquivo_pose(sl, e, lado), "tipo": "pose", "prioridade": 1 if k < 3 else 2,
                              "grupo": "reacao", "lado": lado, "mestre": e == "neutro" and lado == mestre_lado,
                              "descricao_pt": f"sentado — {rot}", "prompt": f"sitting in a cinema seat, {en}."})
            continue
        for k, e in enumerate(exprs):
            poses.append({"arquivo": arquivo_pose(sl, e, lado), "tipo": "pose", "prioridade": 1 if k < 4 else 2,
                          "grupo": "reacao", "lado": lado, "mestre": e == "neutro" and lado == mestre_lado,
                          "descricao_pt": f"sentado — {EXPRESSOES[e][0]} · {LADOS[lado]}",
                          "prompt": f"sitting, {_VIRADO[lado]}, {EXPRESSOES[e][1]}."})
        if lado == "frente" and movimentos_ligados(p):  # 🎬 de perto + movimentos: os gestos naturais + andando
            for g, (rot, en) in GESTOS.items():
                poses.append({"arquivo": arquivo_pose(sl, g, lado), "tipo": "pose", "prioridade": 2, "grupo": "gesto",
                              "lado": lado, "mestre": False, "descricao_pt": f"sentado — {rot}",
                              "prompt": f"sitting in a cinema seat, {en}."})
            poses.append({"arquivo": arquivo_pose(sl, "andando", lado), "tipo": "pose", "prioridade": 2, "grupo": "gesto",
                          "lado": lado, "mestre": False, "descricao_pt": ANDANDO[0], "prompt": ANDANDO[1] + "."})
    refs = {r: f"a reference picture of {c['nome']}" + (f" from {c['obra']}" if c.get("obra") else "") for r in c.get("refs") or []}
    if c.get("cor_ref"):  # 🌈 a foto colorida: só as cores reais
        refs[c["cor_ref"]] = _pp().COR_REF_EN
        trava += " Use the COLORED reference for the exact real colors."
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
        lados = lados_precisos(p, cid, base)
        if (c.get("pod") or {}).get("pid"):
            try:  # ♻ os lados que o projeto já tem continuam (as imagens prontas são reaproveitadas)
                ja = _pp().carregar(c["pod"]["pid"], base)
                lados += [lado_da_pose(_slug(c["nome"]), x["arquivo"])[1] for x in ja["dados"]["poses"] if x.get("tipo") == "pose"]
            except Exception:  # noqa: BLE001
                pass
        dados = poses_json(p, c, list(dict.fromkeys(lados)))
        refs = []
        for r in ((c.get("refs") or [])[:1] + ([c["cor_ref"]] if c.get("cor_ref") else []) + (c.get("refs") or [])[1:2])[:3]:
            try:
                with open(os.path.join(pasta(pid, base), "refs", r), "rb") as f:
                    refs.append((r, f.read()))
            except OSError:
                continue
        if not refazer and not (c.get("pod") or {}).get("pid"):
            reaproveitar(p, c, base)  # ♻ já foi gerado num react anterior: usa o mesmo projeto 🧍
            if (c.get("pod") or {}).get("pid"):
                try:
                    ja = _pp().carregar(c["pod"]["pid"], base)
                    lados += [lado_da_pose(_slug(c["nome"]), x["arquivo"])[1] for x in ja["dados"]["poses"] if x.get("tipo") == "pose"]
                except Exception:  # noqa: BLE001
                    pass
            dados = poses_json(p, c, list(dict.fromkeys(lados)))
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


def refazer_pose(pid: str, cid: str, arquivo: str, pedido: str = "", base: str = _BASE) -> Dict[str, Any]:
    """🔁 Gera DE NOVO uma pose (e a 👄 boca dela, que espera a pose nova ficar pronta). `pedido` = o que mudar
    (vai junto do prompt). A versão antiga fica guardada no projeto 🧍 (dá pra voltar pra ela lá)."""
    pp = _pp()
    p = carregar(pid, base)
    c = personagem(p, cid)
    ppid = (c.get("pod") or {}).get("pid")
    if not ppid:
        raise ReactErro("Esse personagem ainda não tem as poses — 🚀 Gerar primeiro.")
    proj = pp.carregar(ppid, base)
    nomes = {x["arquivo"]: x for x in proj["dados"]["poses"]}
    arquivo = os.path.basename(str(arquivo or ""))
    if arquivo not in nomes:
        raise ReactErro("Pose não encontrada.")
    if nomes[arquivo].get("tipo") == "boca":
        alvo = [arquivo]
    else:
        boca = arquivo[:-4] + "_boca.png"
        alvo = [arquivo] + ([boca] if boca in nomes else [])
    pedido = " ".join(str(pedido or "").split())[:400]
    try:
        r = pp.enviar(ppid, alvo, pedido, base)
    except pp.PersErro as exc:
        raise ReactErro(str(exc))
    with _TRAVA:
        q = carregar(pid, base)
        log(q, f"🔁 {c['nome']}: {arquivo} de novo" + (f" ({pedido})" if pedido else ""))
        salvar(q, base)
    return r if isinstance(r, dict) else {}


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
    try:
        acompanhar_cenas(pid, base)
    except Exception as exc:  # noqa: BLE001
        avisos.append(f"cenas: {str(exc)[:160]}")
    try:
        import react_objetos as RO
        RO.acompanhar(pid, base)
    except Exception as exc:  # noqa: BLE001
        avisos.append(f"itens da mesa: {str(exc)[:160]}")
    try:
        conferir_lados_fundo(pid, base)
    except Exception:  # noqa: BLE001
        pass
    return {"avisos": avisos}


def virado(c: Dict[str, Any], arquivo: str, versao: str, lado_arquivo: str) -> str:
    """🧭 Pra que lado a imagem da pose REALMENTE olha: "dir", "esq" ou "frente". O Flow às vezes desenha virado pro
    lado errado — vale o que a IA conferiu nas imagens (ou o que você marcou ↔); sem conferir, o lado do arquivo."""
    f = (c.get("viradas") or {}).get(arquivo) or {}
    if f.get("versao") == versao and f.get("lado") in ("dir", "esq", "frente"):
        return f["lado"]
    return lado_arquivo


def poses_do_personagem(c: Dict[str, Any], base: str = _BASE, lado: str = "dir") -> Dict[str, Dict[str, Any]]:
    """expressão → {"pose", "boca", "espelhar", "arquivo", "virada"} (só as que já têm imagem) pro LADO que ele olha.
    v84_237: escolhe por expressão a imagem que de fato olha pro lado certo (🧭 conferido nas imagens); se só tem
    virada pro outro lado, espelha; de frente, usa como está."""
    todas = _poses_por_lado(c, base)
    if lado in ("costas", "frente"):  # 🎬 cinema: as poses desse lado; sem elas ainda, as de frente/3⁄4 (avisa no editor)
        if todas.get(lado):
            return {e: dict(x, espelhar=False, virada=lado) for e, x in todas[lado].items()}
        lado = "dir"
    outro = "esq" if lado == "dir" else "dir"
    out: Dict[str, Dict[str, Any]] = {}
    for e in set(todas.get(lado, {})) | set(todas.get(outro, {})):
        cands = []
        for la in (lado, outro):
            x = todas.get(la, {}).get(e)
            if not x:
                continue
            v = virado(c, x.get("arquivo") or "", os.path.basename(x["pose"]), la)
            cands.append((0 if v == lado else 1 if v == "frente" else 2, la != lado, x, v))
        cands.sort(key=lambda z: (z[0], z[1]))
        _r, _l, x, v = cands[0]
        out[e] = dict(x, espelhar=(v != lado and v != "frente"), virada=v)
    return out


SCHEMA_LADOS = {"type": "object", "additionalProperties": False, "required": ["figuras"],
                "properties": {"figuras": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["n", "lado"],
                    "properties": {"n": {"type": "integer"}, "lado": {"type": "string", "enum": ["direita", "esquerda", "frente"]}}}}}}
SYS_LADOS = ("Cada figura numerada é o MESMO personagem sentado, em expressões diferentes. Pra cada número diga pra que "
             "lado da IMAGEM o corpo e o rosto dele estão virados (de quem olha a imagem): 'direita' (virado pro lado direito "
             "da imagem), 'esquerda' (pro lado esquerdo) ou 'frente' (de frente, sem lado claro). Olhe o tronco, os joelhos "
             "e pra onde o rosto aponta — não a mão.")
_CONFERINDO: set = set()


def conferir_lados(pid: str, cid: str, base: str = _BASE, todas: bool = False) -> Dict[str, Any]:
    """🧭 A IA olha as poses prontas (numa folha numerada) e marca pra que lado cada uma está virada de verdade — o
    react espelha as que vieram viradas pro lado errado. Não mexe no que você marcou ↔ (a não ser com todas=True)."""
    from PIL import Image, ImageDraw
    p = carregar(pid, base)
    c = personagem(p, cid)
    lados = _poses_por_lado(c, base)
    fig = []
    for la in ("dir", "esq"):
        for e, x in lados.get(la, {}).items():
            arq, ver = x.get("arquivo") or "", os.path.basename(x["pose"])
            f = (c.get("viradas") or {}).get(arq) or {}
            if not todas and f.get("versao") == ver:
                continue
            fig.append((arq, ver, x["pose"]))
    if not fig:
        return {"conferidas": 0}
    cel_w, cel_h = 220, 330
    cols = min(6, len(fig))
    linhas = math.ceil(len(fig) / cols)
    folha = Image.new("RGB", (cols * cel_w, linhas * cel_h), (235, 235, 235))
    dr = ImageDraw.Draw(folha)
    for k, (_a, _v, cam) in enumerate(fig):
        im = Image.open(cam).convert("RGBA")
        esc = min((cel_w - 10) / im.width, (cel_h - 40) / im.height)
        im = im.resize((max(1, int(im.width * esc)), max(1, int(im.height * esc))))
        x0, y0 = (k % cols) * cel_w, (k // cols) * cel_h
        folha.paste(im, (x0 + (cel_w - im.width) // 2, y0 + 34), im)
        dr.rectangle([x0 + 4, y0 + 4, x0 + 40, y0 + 30], fill=(20, 20, 20))
        dr.text((x0 + 10, y0 + 6), str(k + 1), font=_fonte(22), fill=(255, 220, 0))
    buf = io.BytesIO()
    folha.save(buf, "JPEG", quality=85)
    bloco = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}
    r = _ia().chamar("react", SYS_LADOS, [{"type": "text", "text": f"{len(fig)} figuras de {c['nome']}."}, bloco],
                     schema=SCHEMA_LADOS, max_tokens=800, effort="low", timeout=120, cache_local=False)
    if not isinstance(r, dict) or not isinstance(r.get("figuras"), list):
        raise ReactErro("A IA não respondeu (desligada, sem crédito ou erro).")
    mapa = {"direita": "dir", "esquerda": "esq", "frente": "frente"}
    n = 0
    with _TRAVA:
        p = carregar(pid, base)
        c = personagem(p, cid)
        vir = c.setdefault("viradas", {})
        for f in r["figuras"]:
            k = int(f.get("n") or 0) - 1 if isinstance(f, dict) else -1
            if 0 <= k < len(fig) and f.get("lado") in mapa:
                arq, ver, _cam = fig[k]
                vir[arq] = {"versao": ver, "lado": mapa[f["lado"]], "fonte": "ia"}
                n += 1
        log(p, f"🧭 {c['nome']}: {n} pose(s) conferidas — as viradas pro lado errado são espelhadas")
        salvar(p, base)
    return {"conferidas": n}


def marcar_virada(p: Dict[str, Any], cid: str, arquivo: str, base: str = _BASE) -> str:
    """↔ Você marca: esta pose está virada pro OUTRO lado (troca dir ⇄ esq; de frente → o lado do arquivo ao contrário)."""
    c = personagem(p, cid)
    for la in ("dir", "esq"):
        x = next((y for y in _poses_por_lado(c, base).get(la, {}).values() if y.get("arquivo") == arquivo), None)
        if x:
            ver = os.path.basename(x["pose"])
            atual = virado(c, arquivo, ver, la)
            novo = {"dir": "esq", "esq": "dir"}.get(atual, "esq" if la == "dir" else "dir")
            c.setdefault("viradas", {})[arquivo] = {"versao": ver, "lado": novo, "fonte": "voce"}
            return novo
    raise ReactErro("Essa pose ainda não tem imagem.")


def conferir_lados_fundo(pid: str, base: str = _BASE) -> None:
    """Chamado pelo acompanhar: confere sozinho (numa thread) os personagens com pose nova sem conferir."""
    if not ia_ligada():
        return
    p = carregar(pid, base)
    for c in p["personagens"]:
        chave = (pid, c["id"])
        if chave in _CONFERINDO:
            continue
        lados = _poses_por_lado(c, base)
        falta = any(((c.get("viradas") or {}).get(x.get("arquivo") or "") or {}).get("versao") != os.path.basename(x["pose"])
                    for k_la, la in lados.items() if k_la in ("dir", "esq") for x in la.values())
        if not falta:
            continue
        _CONFERINDO.add(chave)

        def rodar(cid: str = c["id"], ch: Tuple[str, str] = chave) -> None:
            try:
                conferir_lados(pid, cid, base)
            except Exception:  # noqa: BLE001
                pass
            finally:
                _CONFERINDO.discard(ch)
        threading.Thread(target=rodar, daemon=True).start()


def _poses_por_lado(c: Dict[str, Any], base: str = _BASE) -> Dict[str, Dict[str, Dict[str, Optional[str]]]]:
    pod = c.get("pod") or {}
    if not pod.get("pid"):
        return {}
    pp = _pp()
    try:
        proj = pp.carregar(pod["pid"], base)
    except pp.PersErro:
        return {}
    sl = _slug(c["nome"])
    out: Dict[str, Dict[str, Dict[str, Optional[str]]]] = {"dir": {}, "esq": {}, "costas": {}, "frente": {}}
    for x in proj["dados"]["poses"]:
        if x.get("tipo") != "pose":
            continue
        e, lado = lado_da_pose(sl, x["arquivo"])
        cam = pp.arquivo_atual(proj, x["arquivo"], base)
        if not cam or (proj["imagens"].get(x["arquivo"]) or {}).get("estado") == "descartada":
            continue
        boca = next((y["arquivo"] for y in proj["dados"]["poses"] if y.get("tipo") == "boca" and y.get("base") == x["arquivo"]), None)
        out[lado][e] = {"pose": cam, "boca": pp.arquivo_atual(proj, boca, base) if boca else None, "arquivo": x["arquivo"]}
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
    sl = _slug(c["nome"])
    por_lado = {l: {"prontas": sum(1 for i in poses if i["img"] and lado_da_pose(sl, i["arquivo"])[1] == l),
                    "total": sum(1 for i in poses if lado_da_pose(sl, i["arquivo"])[1] == l)} for l in ("dir", "esq")}
    for i in itens:
        i["lado"] = lado_da_pose(sl, i["arquivo"].replace("_boca.png", ".png"))[1]
        if i["tipo"] == "pose" and i["img"]:
            i["virada"] = virado(c, i["arquivo"], i["img"], i["lado"])
            i["conferida"] = ((c.get("viradas") or {}).get(i["arquivo"]) or {}).get("versao") == i["img"]
            i["fonte"] = ((c.get("viradas") or {}).get(i["arquivo"]) or {}).get("fonte")
    return {"tem": True, "pid": pod["pid"], "fase": pod.get("fase"), "mestre": bool(proj.get("mestre")), "por_lado": por_lado,
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
    if camada == "cine_costas_fundo":
        return ("Wide 16:9 interior of a dark movie theater seen from the BACK of the audience at eye level: a huge glowing "
                "cinema screen in the upper center (keep the screen area plain and softly glowing, nothing on it), red velvet "
                "curtains at its sides, dim aisle lights and exit signs without text, soft light beams from the projector; "
                "the lower half is dark and EMPTY (the rows of seats are separate layers): NO seats, NO people. "
                + (f"Extra: {extra}. " if extra else "") + sty + ".")
    if camada == "cine_plateia_fundo":
        return ("Wide 16:9 interior of a movie theater seen from the FRONT ROWS looking back at the audience area, like the "
                "ending of an anime: many rows of EMPTY red velvet cinema seats rising toward the back wall and getting "
                "smaller with distance, the projector window glowing at the TOP CENTER of the back wall with a bright lens "
                "flare and soft light beams through hazy dusty air, warm sepia cinematic light, slight depth of field; NO "
                "people anywhere. " + (f"Extra: {extra}. " if extra else "") + sty + ".")
    if camada == "cine_passante":
        return ("ONE ordinary moviegoer (a random anonymous person, not a famous character) walking SIDEWAYS toward the "
                "viewer's RIGHT through a narrow cinema row, slightly crouched to not block the screen, holding a soda cup, "
                "an apologetic face, seen from the side/three-quarters, FULL BODY from head to feet with margin, isolated "
                "on a flat solid chroma-key green background (#00FF00), no seats, no floor, no shadow, no text. " + sty + ".")
    if camada == "cine_frente_fundo":
        return ("Wide 16:9 interior of a dark movie theater seen FROM THE SCREEN toward the audience: stadium-style stepped "
                "floor rising toward the back wall, the glowing projector window high on the back wall, cold blue light "
                "from the screen on the walls, a few dim aisle lights; EMPTY: NO seats (separate layers), NO people. "
                + (f"Extra: {extra}. " if extra else "") + sty + ".")
    if camada == "cine_costas_fileira":
        return ("a long straight row of red velvet cinema seats seen from BEHIND at eye level: we see the backs of the seats "
                "and the tops of the headrests and armrests, about 7 seats side by side, the whole row visible edge to edge "
                "with margin, empty, isolated on a flat solid chroma-key green background (#00FF00), no floor, no shadow, no "
                "people. " + sty + ".")
    if camada == "cine_frente_fileira":
        return ("a long straight row of red velvet cinema seats seen from the FRONT at eye level: seat cushions, backs and "
                "armrests with cup holders, about 7 seats side by side, the whole row visible edge to edge with margin, empty, "
                "isolated on a flat solid chroma-key green background (#00FF00), no floor, no shadow, no people. " + sty + ".")
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
    em_cima = ("with an EMPTY top (the snacks are separate layers)" if p.get("objetos") else
               "with snacks on top: popcorn bowl, soda cans, chips, a game controller and a small microphone")
    return ("a long low wooden coffee table seen from the FRONT at eye level (we see its front edge and a bit of the top), "
            f"{em_cima}; the whole table "
            "visible with margin around it, isolated on a flat solid chroma-key green background (#00FF00), no floor, no "
            "shadow on the background, no people. " + sty + ".")


# ------------------------------------------------------------------ 🖼 imagem de referência pro cenário
MODOS_REF = {"ambiente": "🏠 Recriar o ambiente (o mesmo lugar, arrumado pro react)",
             "anime": "🎨 Virar anime (o mesmo lugar no traço dos personagens)"}


def guardar_referencia(p: Dict[str, Any], camada: str, img, modo: str, base: str = _BASE) -> Dict[str, Any]:
    """🖼 Guarda a SUA imagem como REFERÊNCIA de uma camada (não usa ela direto — pra isso é o 📁 Minha imagem): o
    Flow recria o lugar a partir dela — 'ambiente' (o mesmo lugar, no visual da foto, enquadrado e vazio pro react) ou
    'anime' (o mesmo lugar redesenhado no traço dos personagens)."""
    if camada not in CAMADAS:
        raise ReactErro("Camada desconhecida.")
    if modo not in MODOS_REF:
        raise ReactErro("Escolha recriar o ambiente ou virar anime.")
    d = os.path.join(pasta(p["id"], base), "cenario")
    os.makedirs(d, exist_ok=True)
    im = img.convert("RGB")
    im.thumbnail((2048, 2048))
    arq = f"ref_{camada}_{secrets.token_hex(3)}.jpg"
    im.save(os.path.join(d, arq), quality=92)
    cam = p["cenario"]["camadas"].setdefault(camada, {})
    cam["ref"] = {"arquivo": arq, "modo": modo}
    return cam["ref"]


def arquivo_referencia(p: Dict[str, Any], camada: str, base: str = _BASE) -> Optional[str]:
    ref = ((p["cenario"]["camadas"].get(camada) or {}).get("ref") or {})
    cam = os.path.join(pasta(p["id"], base), "cenario", ref["arquivo"]) if ref.get("arquivo") else None
    return cam if cam and os.path.isfile(cam) else None


def prompt_camada_ref(p: Dict[str, Any], camada: str, modo: str) -> str:
    """O pedido da camada de sempre (enquadramento, vazio, verde…) + 'use a imagem anexada como o lugar'."""
    sty = ESTILO_TXT[estilo_final(p)]
    base_txt = prompt_camada(p, camada)
    obra = (p.get("obra") or (p.get("sugestoes") or {}).get("obra") or "").strip()
    fundo = camada.endswith("fundo")
    oque = "place" if fundo else "furniture"
    if modo == "anime":
        estilo = (ESTILO_TXT["anime"] + ", the SAME anime art style as the characters of this reaction video"
                  + (f" (the style of {obra})" if obra else "") + ", NOT a photo")
        topo = (f"REFERENCE IMAGE ATTACHED: it shows the {oque} to use. REDRAW this SAME {oque} as an ANIME illustration — keep its "
                "layout, shapes, objects, colors and mood recognizable, but drawn with clean line art and cel shading. ")
    else:
        estilo = ("keep the exact visual look of the reference image (same rendering: if it is a photo, stay photographic; "
                  "same colors, materials and lighting)")
        topo = (f"REFERENCE IMAGE ATTACHED: it shows the {oque} to use. RECREATE this SAME {oque} faithfully — same "
                "architecture, materials, colors, decorations, lighting and mood — re-framed and cleaned up for a "
                "reaction video. ")
    if base_txt.endswith(sty + "."):
        base_txt = base_txt[: -len(sty) - 1] + estilo + "."
    else:
        base_txt += " Style: " + estilo + "."
    return (topo + "Follow these composition rules (they win over what the reference shows; remove people, text and "
            "anything that breaks them): " + base_txt)[:3900]


def gerar_camadas(pid: str, base: str = _BASE, quais: Optional[List[str]] = None) -> Dict[str, Any]:
    """🚀 Manda as camadas (fundo / sofá / mesa) pra fila do Flow em massa."""
    import flow_lote
    with _TRAVA:
        p = carregar(pid, base)
        quais = [q for q in (quais or list(camadas_do_layout(p))) if q in CAMADAS]
        itens = []
        for q in quais:
            ref = arquivo_referencia(p, q, base)
            it = {"prompt": (prompt_camada_ref(p, q, p["cenario"]["camadas"][q]["ref"].get("modo") or "ambiente") if ref
                             else prompt_camada(p, q))[:3900], "tipo": "imagem", "origem": "react"}
            if ref:
                it["referencia_arquivo"] = ref  # 🖼 o Flow recria a partir da sua imagem
            itens.append(it)
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
    return {"enviadas": len(quais), "aviso": aviso}


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
    if camada.endswith("fundo"):
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


def camadas_de_outros(p: Dict[str, Any], camada: str, base: str = _BASE) -> List[Dict[str, Any]]:
    """♻ As imagens dessa camada (fundo/sofá/mesa) já feitas em OUTROS reacts — as do mesmo estilo primeiro."""
    if camada not in CAMADAS:
        return []
    est = estilo_final(p)
    out = []
    raiz = pasta_raiz(base)
    for rid in os.listdir(raiz) if os.path.isdir(raiz) else []:
        if rid == p["id"] or not RE_ID.match(rid):
            continue
        try:
            o = carregar(rid, base)
        except Exception:  # noqa: BLE001
            continue
        cam = (o["cenario"]["camadas"].get(camada) or {})
        for arq in cam.get("versoes") or ([cam["arquivo"]] if cam.get("arquivo") else []):
            if os.path.isfile(os.path.join(pasta(rid, base), "cenario", arq)):
                out.append({"projeto": rid, "titulo": o.get("titulo") or "", "arquivo": arq, "estilo": estilo_final(o),
                            "atual": arq == cam.get("arquivo"), "quando": o.get("atualizado", 0)})
    out.sort(key=lambda x: (x["estilo"] != est, not x["atual"], -x["quando"]))
    return out[:40]


def usar_camada_de_outro(p: Dict[str, Any], camada: str, projeto: str, arquivo: str, base: str = _BASE) -> str:
    """♻ Copia a imagem pronta de outro react pra esta camada (sem recortar de novo)."""
    from PIL import Image
    if camada not in CAMADAS or not RE_ID.match(projeto or "") or not re.fullmatch(r"[\w.\-]+\.png", arquivo or ""):
        raise ReactErro("imagem inválida")
    cam = os.path.join(pasta(projeto, base), "cenario", arquivo)
    if not os.path.isfile(cam):
        raise ReactErro("Essa imagem não existe mais.")
    with Image.open(cam) as im:
        im.load()
        novo = guardar_camada(p, camada, im.copy(), base, recortar=False, origem="♻ outro react")
    log(p, f"♻ {ROTULO_CAMADA[camada]} reaproveitado de outro react")
    return novo


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
    if lay in CINEMA:
        return aplicar_posicoes(p, _disposicao_cinema(p, lay, base, video_wh), base)
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
        if p.get("mesa_por_sofa", True):  # 🛋🛋 uma mesa na frente de cada sofá (a da direita é a ⧉ automática)
            mesa_w, mesa_cx = 0.30 * W, 0.17 * W
        else:
            mesa_w, mesa_cx = 0.42 * W, 0.50 * W
        grupos = sofas_de(p, "dois_sofas")
    else:
        tela_w = 0.345 * W
        tela_cx, tela_cy = 0.80 * W, 0.36 * H
        sofas_cx = [0.31 * W]
        sofa_w = 0.58 * W
        mesa_w, mesa_cx = 0.70 * W, 0.37 * W
        grupos = sofas_de(p, "sofa_tv")
    tela_h = tela_w / asp_v
    if tela_h > 0.46 * H:  # vídeo em pé: a TV fica mais estreita
        tela_h = 0.46 * H
        tela_w = tela_h * asp_v
    out["tela"] = {"cx": tela_cx, "cy": tela_cy, "w": tela_w, "h": tela_h, "espelhar": False}
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
    out["mesa"] = {"cx": mesa_cx, "cy": 1.015 * H - mesa_h / 2, "w": mesa_w, "h": mesa_h, "espelhar": False}
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
        for j, cid in enumerate(g):
            cx = (ini + fim) / 2 if len(g) == 1 else ini + (fim - ini) * j / (len(g) - 1)
            olha_esq = lay == "dois_sofas" and k == 1  # o sofá da direita olha pra TV no meio
            # os do fundo um pouco mais altos (fileira), alternando levemente pra parecer natural
            dy = (-0.012 * H) if j % 2 else 0.0
            assentos.append({"cid": cid, "cx": cx, "cy": pe - png_h / 2 + dy, "w": png_w, "h": png_h, "espelhar": olha_esq})
    out["assentos"] = assentos
    # 🖼 onde aparece a foto/exemplo (⚡ Intrigas): por cima, perto do meio
    fw = 0.30 * W
    out["foto"] = ({"cx": 0.50 * W, "cy": 0.36 * H, "w": fw, "h": fw * 0.75, "espelhar": False} if lay == "dois_sofas"
                   else {"cx": 0.42 * W, "cy": 0.33 * H, "w": fw, "h": fw * 0.75, "espelhar": False})
    out["fundo"] = {"espelhar": False}
    return aplicar_posicoes(p, out, base)


# 🛋 quantos cabem: até ~6 num sofá só e ~3–4 por sofá nos dois sofás sem ficarem espremidos (mais que isso eles
# encolhem até o mínimo e começam a se sobrepor); acima de 8 o roteiro também perde (fala demais, pouca personalidade)
RECOMENDADO = {"sofa_tv": 6, "dois_sofas": 8, "cinema_costas": 11, "cinema_frente": 11, "cinema_plateia": 9}
MINIMO = {"sofa_tv": 1, "dois_sofas": 2, "cinema_costas": 4, "cinema_frente": 5, "cinema_plateia": 3}  # 🎬 abaixo disso o cinema fica vazio
MAXIMO_LAYOUT = {"sofa_tv": 10, "dois_sofas": 10, "cinema_costas": 11, "cinema_frente": 11, "cinema_plateia": 11}
MAXIMO = 11  # o máximo absoluto (no cinema); nos sofás o ideal é bem menos


def cabe_na_fileira(k: int) -> int:
    """🎬 6 poltronas na fileira da frente; a de trás é INTERCALADA, então só tem os 5 vãos entre as 6 da frente."""
    return POR_FILEIRA - (k % 2)


def sofas_de(p: Dict[str, Any], lay: str) -> List[List[str]]:
    """🛋 Quem senta em qual sofá, na ordem da esquerda pra direita: o que você arrumou (p['assentos'][lay]) com quem
    entrou depois no sofá mais vazio; sem arrumação, a ordem do elenco (dividida ao meio nos dois sofás)."""
    ids = [c["id"] for c in p["personagens"]]
    if lay in CINEMA:  # 🎬 fileiras de até 6 (a 1ª = a mais perto da câmera)
        fm = FILEIRAS.get(lay, FILEIRAS_MAX)
        n_sofas = min(fm, max(1, math.ceil(len(ids) / POR_FILEIRA)))
        salvo = ((p.get("assentos") or {}).get(lay) or [])
        n_sofas = max(n_sofas, min(fm, len([g for g in salvo if g])))
        if not salvo:  # a de trás (nos vãos) leva até 5; a da frente o resto
            if n_sofas == 1:
                return [ids]
            atras = min(POR_FILEIRA - 1, len(ids) // 2)
            return [ids[:len(ids) - atras], ids[len(ids) - atras:]]
        grupos = [[c for c in (salvo[k] if k < len(salvo) else []) if c in ids] for k in range(n_sofas)]
        vistos = {c for g in grupos for c in g}
        grupos = [list(dict.fromkeys(g)) for g in grupos]
        for c in ids:
            if c not in vistos:
                (min([g for k, g in enumerate(grupos) if len(g) < cabe_na_fileira(k)] or grupos, key=len)).append(c)
        return grupos
    n_sofas = 2 if lay == "dois_sofas" else 1
    salvo = ((p.get("assentos") or {}).get(lay) or [])
    if salvo:
        grupos = [[c for c in (salvo[k] if k < len(salvo) else []) if c in ids] for k in range(n_sofas)]
        if n_sofas == 1 and len(salvo) > 1:  # veio dos dois sofás: junta na ordem
            grupos = [[c for g in salvo for c in g if c in ids]]
        vistos = {c for g in grupos for c in g}
        grupos = [list(dict.fromkeys(g)) for g in grupos]
        for c in ids:
            if c not in vistos:
                min(grupos, key=len).append(c)
        return grupos
    if n_sofas == 2:
        n = len(ids)
        return [ids[:math.ceil(n / 2)], ids[math.ceil(n / 2):]]
    return [ids]


def guardar_assentos(p: Dict[str, Any], sofas: Any) -> List[List[str]]:
    """Guarda a ordem/quem senta onde da disposição atual e tira os ajustes de posição à mão dos personagens dela
    (o lugar novo vem da ordem)."""
    lay = p.get("layout") if p.get("layout") in LAYOUTS else "sofa_tv"
    ids = {c["id"] for c in p["personagens"]}
    if not isinstance(sofas, list):
        raise ReactErro("Mande os sofás como listas de personagens.")
    limpo = [[str(c) for c in (g if isinstance(g, list) else []) if str(c) in ids] for g in sofas][:FILEIRAS.get(lay, 2)]
    if lay in CINEMA and any(len(g) > cabe_na_fileira(k) for k, g in enumerate(limpo)):
        raise ReactErro(f"No cinema cabem {POR_FILEIRA} na fileira da frente e {POR_FILEIRA - 1} na de trás (nos vãos).")
    p.setdefault("assentos", {})[lay] = limpo
    pos = (p.get("posicoes") or {}).get(lay) or {}
    for k in [k for k in pos if k.startswith("p:")]:
        pos.pop(k, None)
    return sofas_de(p, lay)


# 🎬 cinema de perto: alturas (fração de H) — o topo da cabeça de quem está na fileira grande e na de trás
PLATEIA = {"cabeca_frente": 0.465, "fig_frente": 0.62, "escala_tras": 0.5, "topo_fileira": 0.55, "topo_plano": 0.74}


def _disposicao_plateia(p: Dict[str, Any], base: str, video_wh: Optional[Tuple[int, int]]) -> Dict[str, Any]:
    """🎬 Cinema de perto (o jeito do encerramento de anime): a câmera numa fileira da FRENTE virada pra plateia —
    a fileira grande (até 6, da cintura pra cima), as poltronas atrás deles, a fileira de trás pequena e INTERCALADA
    (até 5, nos vãos), os ENCOSTOS da fileira da câmera no primeiro plano (sofa1, vistos de trás) e o vídeo em cima,
    no meio (a luz do projetor). Ninguém fica em cima do vídeo."""
    vw, vh = video_wh or (int((p.get("video") or {}).get("largura") or 16), int((p.get("video") or {}).get("altura") or 9))
    asp_v = (vw / vh) if vw and vh else 16 / 9
    tela_w = 0.44 * W
    tela_h = tela_w / asp_v
    if tela_h > 0.40 * H:
        tela_h = 0.40 * H
        tela_w = tela_h * asp_v
    out: Dict[str, Any] = {"layout": "cinema_plateia",
                           "tela": {"cx": W / 2, "cy": 0.02 * H + tela_h / 2, "w": tela_w, "h": tela_h, "espelhar": False},
                           "legenda": {"cx": 0.5 * W, "topo": 0.87 * H, "w": 0.62 * W}}
    limite = 0.02 * H + tela_h + 0.012 * H
    fila_img = camada_arquivo(p, "cine_frente_fileira", base)
    plano_img = camada_arquivo(p, "cine_costas_fileira", base)
    fw_, fh_ = _tam(fila_img, (2400, 520))
    pw_, ph_ = _tam(plano_img, (2400, 520))
    fw = W * 1.06
    passo = fw / POR_FILEIRA
    fh = fw * fh_ / max(1, fw_)  # (o vídeo e a prévia mantêm a proporção da imagem)
    topo_f = PLATEIA["topo_fileira"] * H
    pwid = W * 1.06 * 1.25  # os encostos do primeiro plano: mais perto da câmera, maiores
    phh = pwid * ph_ / max(1, pw_)
    out["sofas"] = [
        {"cx": W / 2, "cy": topo_f + fh / 2, "w": fw, "h": fh, "espelhar": False, "camada": "cine_frente_fileira"},
        {"cx": W / 2 + pwid / POR_FILEIRA / 2, "cy": PLATEIA["topo_plano"] * H + phh / 2, "w": pwid, "h": phh,
         "espelhar": False, "camada": "cine_costas_fileira", "plano": True}]
    filas = [f for f in sofas_de(p, "cinema_plateia") if f] or [[]]
    assentos = []
    for k, fila in enumerate(filas[:2]):
        s = 1.0 if k == 0 else PLATEIA["escala_tras"]
        png_h = PLATEIA["fig_frente"] * H * s
        png_w = png_h / 1.5
        cabeca = PLATEIA["cabeca_frente"] * H if k == 0 else max(limite, PLATEIA["cabeca_frente"] * H - 0.03 * H)
        cy = cabeca - 0.05 * png_h + png_h / 2  # a figura ocupa 95% do quadro (sobra 5% em cima)
        n = len(fila)
        cabe = cabe_na_fileira(k)
        ini = (cabe - n) // 2 if n < cabe else 0
        meio = W / 2 + (passo / 2 if k else 0.0)
        pas = passo if n <= cabe else fw / n
        for j, cid in enumerate(fila):
            cx = meio - fw / 2 + pas * (ini + j + 0.5)
            assentos.append({"cid": cid, "cx": cx, "cy": cy + ((-0.006 * H * s) if j % 2 else 0.0), "w": png_w, "h": png_h,
                             "espelhar": False, "lado": "frente", "fila": k})
    out["assentos"] = assentos
    out["mesa"] = {"cx": -2 * W, "cy": -2 * H, "w": 10.0, "h": 10.0, "espelhar": False}
    out["foto"] = {"cx": 0.5 * W, "cy": 0.45 * H, "w": 0.30 * W, "h": 0.225 * W, "espelhar": False}
    out["fundo"] = {"espelhar": False}
    return out


def _disposicao_cinema(p: Dict[str, Any], lay: str, base: str, video_wh: Optional[Tuple[int, int]]) -> Dict[str, Any]:
    """🎬 O cinema. As FILEIRAS fazem o papel dos sofás (camada 'sofa{k}' = a fileira k; k = 0 é a mais perto da câmera).
    - de costas: o telão grande em cima; as fileiras de poltronas vistas de trás NA FRENTE de quem está sentado (só a
      cabeça e os ombros aparecem); as de trás (perto do telão) menores e mais altas;
    - de frente: 2 fileiras, a de trás um pouco mais alta e menor e INTERCALADA (cada um no vão entre duas cabeças da
      frente); as poltronas ATRÁS de quem senta; o vídeo grande em cima e a legenda embaixo."""
    if lay == "cinema_plateia":
        return _disposicao_plateia(p, base, video_wh)
    vw, vh = video_wh or (int((p.get("video") or {}).get("largura") or 16), int((p.get("video") or {}).get("altura") or 9))
    asp_v = (vw / vh) if vw and vh else 16 / 9
    fw_, fh_ = _tam(camada_papel(p, "assento", base), (2400, 520))
    filas = [f for f in sofas_de(p, lay) if f] or [[]]
    out: Dict[str, Any] = {"layout": lay}
    costas = lay == "cinema_costas"
    if costas:
        tela_w, tela_cx = 0.84 * W, 0.50 * W  # 🎞 o telão GRANDE; a plateia fica toda abaixo dele
        tela_h = tela_w / asp_v
        if tela_h > 0.58 * H:
            tela_h = 0.58 * H
            tela_w = tela_h * asp_v
        tela_cy = 0.025 * H + tela_h / 2
        bases, escalas = [1.03 * H, 0.90 * H], [1.0, 0.82]
        out["legenda"] = {"cx": 0.5 * W, "topo": 0.86 * H, "w": 0.62 * W}
    else:
        tela_w = 0.90 * W  # 🎞 o vídeo GRANDE em cima, no meio; a plateia toda abaixo dele; a legenda embaixo
        tela_h = tela_w / asp_v
        if tela_h > 0.52 * H:
            tela_h = 0.52 * H
            tela_w = tela_h * asp_v
        tela_cx, tela_cy = 0.5 * W, 0.02 * H + tela_h / 2
        bases, escalas = [1.10 * H, 0.88 * H], [1.0, 0.86]  # a da frente mais baixa: os rostos de trás aparecem inteiros
        out["legenda"] = {"cx": 0.5 * W, "topo": 0.86 * H, "w": 0.62 * W}
    out["tela"] = {"cx": tela_cx, "cy": tela_cy, "w": tela_w, "h": tela_h, "espelhar": False}
    out["sofas"], assentos = [], []
    for k, fila in enumerate(filas[:FILEIRAS.get(lay, FILEIRAS_MAX)]):
        s = escalas[k]
        fw = W * 1.06  # todas as fileiras atravessam a tela com o MESMO passo de poltrona (senão a intercalação escorrega
        # nas pontas); a de trás só fica mais baixa/menor na altura e nas pessoas
        fh = fw * fh_ / max(1, fw_)  # a altura de verdade (o vídeo e a prévia mantêm a proporção da imagem)
        n = len(fila)
        passo = fw / max(POR_FILEIRA, n)  # cada um na SUA poltrona (o centro da poltrona); poucos ficam nas do meio
        # as fileiras ficam INTERCALADAS (nos dois modos): a do meio meia poltrona pro lado — cada um aparece no vão
        # entre duas cabeças da fileira da frente (a 3ª, de costas, volta pro alinhamento da 1ª)
        meio = W / 2 + (passo / 2 if k % 2 else 0.0)
        out["sofas"].append({"cx": meio, "cy": bases[k] - fh / 2, "w": fw, "h": fh, "espelhar": False})
        topo_fila = bases[k] - fh
        cabe = cabe_na_fileira(k)
        ini = (cabe - n) // 2 if n < cabe else 0
        png_h = (0.40 if costas else 0.50) * H * s / 0.95
        png_w = png_h / 1.5
        for j, cid in enumerate(fila):
            cx = meio - fw / 2 + passo * (ini + j + 0.5)
            if costas:  # a cintura fica atrás do encosto da poltrona
                cy = topo_fila + 0.07 * H * s - png_h / 2
            else:  # sentado na poltrona (de frente): o corte nos joelhos perto da base da fileira
                cy = bases[k] - 0.06 * H * s - png_h / 2
            assentos.append({"cid": cid, "cx": cx, "cy": cy + ((-0.008 * H * s) if j % 2 else 0.0), "w": png_w, "h": png_h,
                             "espelhar": False, "lado": "costas" if costas else "frente", "fila": k})
    # 🚫 nenhuma cabeça em cima do vídeo: se a plateia sobe além da base da tela, encolhe tudo de baixo pra cima
    # (as fileiras continuam atravessando a tela; cada um continua na sua poltrona)
    limite = tela_cy + tela_h / 2 + 0.012 * H
    topo = min([a["cy"] - a["h"] / 2 for a in assentos] + [f["cy"] - f["h"] / 2 for f in out["sofas"]] + [H])
    if topo < limite:
        f = (H - limite) / (H - topo)
        desce = 0.0
        if f < 0.8:  # encolhe só até 80% e DESCE o resto (a fileira da frente sai um pouco por baixo da tela — de
            f = 0.8  # costas só se vê o encosto de cima; de frente, o corte fica no peito) e os rostos continuam grandes
            desce = limite - (H - (H - topo) * f)

        def enc(d: Dict[str, Any], largura: bool) -> None:
            y0 = d["cy"] - d["h"] / 2
            d["h"] *= f
            if largura:
                d["w"] *= f
            d["cy"] = H - (H - y0) * f + desce + d["h"] / 2
        for d in out["sofas"]:
            enc(d, False)
        for a in assentos:
            enc(a, True)
    out["assentos"] = assentos
    out["mesa"] = {"cx": -2 * W, "cy": -2 * H, "w": 10.0, "h": 10.0, "espelhar": False}  # cinema: sem mesa
    out["foto"] = {"cx": 0.5 * W, "cy": 0.33 * H if costas else 0.45 * H, "w": 0.30 * W, "h": 0.225 * W, "espelhar": False}
    out["fundo"] = {"espelhar": False}
    return out


def img_sofa(p: Dict[str, Any], s: Dict[str, Any], base: str = _BASE) -> Optional[str]:
    """A imagem de um sofá/fileira: a camada dele (cinema de perto: os encostos do primeiro plano são outra) ou o assento."""
    return camada_arquivo(p, s["camada"], base) if s.get("camada") else camada_papel(p, "assento", base)


def chaves_posicao(lay: Dict[str, Any]) -> List[str]:
    return ([c["chave"] for c in lay.get("copias") or []] + [o["chave"] for o in lay.get("objetos") or []] + ["tela", "legenda", "mesa", "foto", "fundo"] + [f"sofa{k}" for k in range(len(lay["sofas"]))]
            + [f"p:{a['cid']}" for a in lay["assentos"]])


def aplicar_posicoes(p: Dict[str, Any], lay: Dict[str, Any], base: str = _BASE) -> Dict[str, Any]:
    """🎛 Os ajustes que você fez arrastando na prévia (posição, tamanho, pra que lado olha) por cima da disposição
    automática — guardados por disposição (sofa_tv e dois_sofas têm os seus)."""
    aj = ((p.get("posicoes") or {}).get(lay["layout"]) or {})

    def ap(d: Dict[str, Any], chave: str) -> None:
        o = aj.get(chave) or {}
        if not o:
            return
        if o.get("w"):
            w = max(40.0, min(4000.0, float(o["w"])))
            if d.get("w") and d.get("h"):
                d["h"] = d["h"] * w / d["w"]
            d["w"] = w
        for k in ("cx", "cy", "topo"):
            if o.get(k) is not None:
                d[k] = max(-2000.0, min(4000.0, float(o[k])))
        if o.get("lado") in ("dir", "esq") and "espelhar" in d:
            d["espelhar"] = o["lado"] == "esq"
        d["ajustado"] = True

    ap(lay["tela"], "tela")
    ap(lay["legenda"], "legenda")
    ap(lay["mesa"], "mesa")
    ap(lay["foto"], "foto")
    ap(lay["fundo"], "fundo")
    for k, sf in enumerate(lay["sofas"]):
        ap(sf, f"sofa{k}")
    for a in lay["assentos"]:
        ap(a, f"p:{a['cid']}")
    # ⧉ cópias (duplicar a mesa, um sofá, a TV, um personagem…): nascem ao lado da original e mexem sozinhas
    lay["copias"] = []
    if lay["layout"] == "dois_sofas" and p.get("mesa_por_sofa", True) and len(lay["sofas"]) > 1:
        # 🛋🛋 a mesa do sofá da direita (cópia automática da mesa — esconda com 👁 se não quiser)
        m, s2 = lay["mesa"], lay["sofas"][1]
        d = {"cx": s2["cx"] - (m["cx"] - lay["sofas"][0]["cx"]), "cy": m["cy"], "w": m["w"], "h": m["h"], "espelhar": True,
             "id": "mesa2", "de": "mesa", "chave": "c:mesa2", "auto": True}
        ap(d, d["chave"])
        lay["copias"].append(d)
    for cp in ((p.get("copias") or {}).get(lay["layout"]) or []):
        src = peca_geo(lay, cp["de"])
        if not src:
            continue
        d = {k: src[k] for k in ("cx", "cy", "w", "h", "espelhar") if k in src}
        d["cx"] = d["cx"] + 0.05 * W
        d.update(id=cp["id"], de=cp["de"], chave=f"c:{cp['id']}")
        d.setdefault("espelhar", False)
        ap(d, d["chave"])
        lay["copias"].append(d)
    import react_objetos as RO  # 🍿 os itens em cima das mesas
    lay["objetos"] = RO.geometria(p, lay, base, ap)
    return lay


DUPLICAVEIS = ("sofa", "p:", "mesa", "tela")


def peca_geo(lay: Dict[str, Any], chave: str) -> Optional[Dict[str, Any]]:
    """A geometria (cx, cy, w, h, espelhar) da peça `chave` na disposição."""
    if chave.startswith("sofa"):
        k = int(chave[4:] or 0)
        return lay["sofas"][k] if k < len(lay["sofas"]) else None
    if chave.startswith("p:"):
        return next((a for a in lay["assentos"] if a["cid"] == chave[2:]), None)
    if chave in ("mesa", "tela"):
        return lay[chave]
    return None


def duplicar(p: Dict[str, Any], chave: str, base: str = _BASE) -> str:
    """⧉ Duplica uma peça (mesa, sofá, TV com o vídeo, personagem — o clone faz as mesmas caras e falas)."""
    lay_nome = p.get("layout") if p.get("layout") in LAYOUTS else "sofa_tv"
    if chave.startswith("c:"):  # duplicar uma cópia = outra cópia da mesma original, no lugar dela
        orig = next((x for x in (p.get("copias") or {}).get(lay_nome) or [] if f"c:{x['id']}" == chave), None) \
            or ({"de": "mesa"} if chave == "c:mesa2" else None)
        if not orig:
            raise ReactErro("Cópia não encontrada.")
        de = orig["de"]
    else:
        de = chave
    if not de.startswith(DUPLICAVEIS) or not peca_geo(disposicao(p, base), de):
        raise ReactErro("Essa camada não dá pra duplicar.")
    cid = secrets.token_hex(3)
    p.setdefault("copias", {}).setdefault(lay_nome, []).append({"id": cid, "de": de})
    if chave.startswith("c:"):  # a nova nasce ao lado da cópia que você duplicou
        o = ((p.get("posicoes") or {}).get(lay_nome) or {}).get(chave) or {}
        lay = disposicao(p, base)
        x = next((c for c in lay["copias"] if c["chave"] == chave), None)
        if x:
            p.setdefault("posicoes", {}).setdefault(lay_nome, {})[f"c:{cid}"] = dict(o, cx=x["cx"] + 0.05 * W, cy=x["cy"], w=x["w"])
    return f"c:{cid}"


def apagar_copia(p: Dict[str, Any], chave: str) -> None:
    lay_nome = p.get("layout") if p.get("layout") in LAYOUTS else "sofa_tv"
    lista = (p.get("copias") or {}).get(lay_nome) or []
    if chave == "c:mesa2":
        raise ReactErro("A mesa do 2º sofá é automática — esconda com 👁 (ou desligue “uma mesa por sofá”).")
    if not any(f"c:{x['id']}" == chave for x in lista):
        raise ReactErro("Só dá pra apagar as cópias (⧉) — a original você pode esconder 👁.")
    p["copias"][lay_nome] = [x for x in lista if f"c:{x['id']}" != chave]
    ((p.get("posicoes") or {}).get(lay_nome) or {}).pop(chave, None)


def guardar_posicao(p: Dict[str, Any], chave: str, dados: Optional[Dict[str, Any]], base: str = _BASE) -> None:
    """Guarda (ou tira, com dados=None) o ajuste de uma peça na disposição atual."""
    lay = p.get("layout") if p.get("layout") in LAYOUTS else "sofa_tv"
    validas = set(chaves_posicao(disposicao(dict(p, posicoes={}), base)))
    if chave != "*" and chave not in validas:
        raise ReactErro("peça desconhecida")
    pos = p.setdefault("posicoes", {}).setdefault(lay, {})
    if chave == "*":
        p["posicoes"][lay] = {}
        return
    if not dados:
        pos.pop(chave, None)
        return
    o = {k: round(float(dados[k]), 1) for k in ("cx", "cy", "w", "topo") if isinstance(dados.get(k), (int, float))}
    if dados.get("lado") in ("dir", "esq"):
        o["lado"] = dados["lado"]
    pos[chave] = dict(pos.get(chave) or {}, **o)


def pilha(p: Dict[str, Any], lay: Dict[str, Any]) -> Dict[str, Any]:
    """🗂 As camadas como no Photoshop: a ordem (de baixo pra cima), quais estão ocultas (não vão pro vídeo) e quais
    estão travadas (não mexem no palco). Por disposição. Peça nova (personagem que entrou depois) vai pro lugar padrão."""
    if lay["layout"] == "cinema_plateia":  # 🎬 de perto: os de trás, as poltronas, a fileira grande, os encostos na frente
        padrao = ([f"p:{a['cid']}" for a in lay["assentos"] if a.get("fila") == 1] + ["sofa0"]
                  + [f"p:{a['cid']}" for a in lay["assentos"] if a.get("fila") == 0] + ["sofa1", "tela", "foto", "legenda"])
    elif lay["layout"] in CINEMA:  # 🎬 da fileira de trás pra da frente; de costas a poltrona fica NA FRENTE de quem senta
        padrao = []
        for k in range(len(lay["sofas"]) - 1, -1, -1):
            gente = [f"p:{a['cid']}" for a in lay["assentos"] if a.get("fila") == k]
            padrao += (gente + [f"sofa{k}"]) if lay["layout"] == "cinema_costas" else ([f"sofa{k}"] + gente)
        padrao += ["tela", "foto", "legenda"] if lay["layout"] == "cinema_frente" else []
        if lay["layout"] == "cinema_costas":
            padrao = ["tela"] + padrao + ["foto", "legenda"]
    else:
        padrao = ([f"sofa{k}" for k in range(len(lay["sofas"]))] + [f"p:{a['cid']}" for a in lay["assentos"]]
                  + ["mesa", "tela", "foto", "legenda"])
    # 🎬 v84_244: as imagens de destaque em tela cheia (briga/interação/cena) viram camada — dá pra esconder 👁
    padrao.insert(padrao.index("legenda") if "legenda" in padrao else len(padrao), "cena")
    for c in lay.get("copias") or []:  # a cópia entra logo acima da original
        padrao.insert(padrao.index(c["de"]) + 1 if c["de"] in padrao else len(padrao), c["chave"])
    for o in lay.get("objetos") or []:  # 🍿 o item logo acima da mesa dele (no cinema: logo acima de quem segura)
        ref = o["mesa"] if o["mesa"] in padrao else ("mesa" if "mesa" in padrao else None)
        if ref is None:
            ref = next((k for k in padrao[::-1] if k.startswith("sofa") or k.startswith("p:")), padrao[-1])
        padrao.insert(padrao.index(ref) + 1, o["chave"])
    g = ((p.get("pilha") or {}).get(lay["layout"]) or {})
    salva = [k for k in g.get("ordem") or [] if k in padrao]
    ordem = list(salva)
    for i, k in enumerate(padrao):
        if k in ordem:
            continue
        # entra logo acima da peça padrão anterior que já está na ordem
        ant = next((padrao[j] for j in range(i - 1, -1, -1) if padrao[j] in ordem), None)
        ordem.insert(ordem.index(ant) + 1 if ant else 0, k)
    return {"ordem": ordem, "ocultas": [k for k in g.get("ocultas") or [] if k in padrao],
            "travadas": [k for k in g.get("travadas") or [] if k in padrao]}


def guardar_pilha(p: Dict[str, Any], dados: Dict[str, Any], base: str = _BASE) -> Dict[str, Any]:
    lay = disposicao(p, base)
    atual = pilha(p, lay)
    validas = set(atual["ordem"])
    novo = dict(atual)
    if isinstance(dados.get("ordem"), list):
        o = [k for k in dados["ordem"] if k in validas]
        novo["ordem"] = o + [k for k in atual["ordem"] if k not in o]
    for campo in ("ocultas", "travadas"):
        if isinstance(dados.get(campo), list):
            novo[campo] = [k for k in dados[campo] if k in validas]
    p.setdefault("pilha", {})[lay["layout"]] = novo
    return pilha(p, lay)


def _pose_no_tempo(p: Dict[str, Any], c: Dict[str, Any], a: Dict[str, Any], base: str,
                   linhas: Dict[str, List[Dict[str, Any]]], t: float) -> Tuple[Optional[Dict[str, Any]], str]:
    lado = a.get("lado") or ("esq" if a["espelhar"] else "dir")
    poses = poses_do_personagem(c, base, lado)
    e = next((x for x in linhas.get(c["id"], []) if x["start"] <= t < x["end"]), None)
    ex = (e or {}).get("expressao") or "neutro"
    if lado == "costas" and any(k in poses for k in EXPR_COSTAS):
        ex = expr_lado(ex, lado, bool((e or {}).get("falando")))
    x = poses.get(ex) or poses.get("neutro") or (next(iter(poses.values())) if poses else None)
    return x, ex


def pecas_para_editar(p: Dict[str, Any], base: str = _BASE, t: Optional[float] = None) -> Dict[str, Any]:
    """🎛 O que a página precisa pra montar o palco arrastável: cada peça com a imagem e o lugar (px de 1920×1080)."""
    video = _video_local(p, base)
    info = sondar(video) if video else {"largura": 16, "altura": 9}
    lay = disposicao(p, base, (info.get("largura") or 16, info.get("altura") or 9))
    pid = p["id"]
    falas = falas_no_tempo(p, (p.get("roteiro") or {}).get("falas") or [], info.get("duracao") or None)
    if t is None:
        t = (falas[0]["t"] + 0.5) if falas else 0.0
    linhas = linhas_personagens(p, falas, max(info.get("duracao") or 0, t + 1)) if falas else {}
    ativa = next((f for f in falas if f["t"] <= t < f["t"] + f["dur"]), None)
    aus = ausencias(p, max(info.get("duracao") or 0, t + 1))
    cena = cena_ativa(p, t)
    foto = cena_ativa(p, t, "quadro")
    estilos = estilos_no_lugar(p, base)

    def url_cena(cam: str) -> str:
        return f"/react-personagens/{pid}/arquivo/cenas/{os.path.basename(cam)}"

    def url_cam(q: str) -> Optional[str]:
        q = {"fundo": camadas_do_layout(p)[0], "sofa": camadas_do_layout(p)[1]}.get(q, q)
        c = (p["cenario"]["camadas"].get(q) or {})
        return f"/react-personagens/{pid}/arquivo/cenario/{c['arquivo']}" if camada_arquivo(p, q, base) else None

    pecas = []
    for k, sf in enumerate(lay["sofas"]):
        nome_sf = ("💺 Encostos (primeiro plano)" if sf.get("plano") else f"💺 Fileira {k + 1}" if layout_de(p) in CINEMA
                   else "🛋 Sofá" + (" da direita" if k else ""))
        pecas.append(dict(sf, chave=f"sofa{k}", nome=nome_sf, img=url_cam(sf.get("camada") or "sofa"), z=3 if sf.get("plano") else 1))
    for a in lay["assentos"]:
        c = personagem(p, a["cid"])
        lado = "esq" if a["espelhar"] else "dir"
        x, ex = _pose_no_tempo(p, c, a, base, linhas, t)
        img, esp = None, a["espelhar"]
        if x:
            ppid = (c.get("pod") or {}).get("pid")
            img = f"/react-personagens/{pid}/pose/{c['id']}/{os.path.basename(x['pose'])}" if ppid else None
            esp = bool(x.get("espelhar"))
        elif c.get("refs"):
            img = f"/react-personagens/{pid}/arquivo/refs/{c['refs'][0]}"
        est_agora = next((cam for ini, fim, cam in estilos.get(c["id"], []) if ini <= t < fim), None)
        if est_agora:
            img, esp = url_cena(est_agora), False
        pecas.append(dict(a, chave=f"p:{c['id']}", nome=c["nome"], img=img, espelhar_img=esp, lado=lado, z=2, personagem=True,
                          estilo=bool(est_agora),
                          expressao=ex, falando=bool(ativa and ativa["cid"] == c["id"]), fora=not presente(aus, c["id"], t)))
    if layout_de(p) not in CINEMA:
        pecas.append(dict(lay["mesa"], chave="mesa", nome="🪵 Mesa", img=url_cam("mesa"), z=3))
    for o in lay.get("objetos") or []:  # 🍿 os itens da mesa
        pecas.append({k: o[k] for k in ("cx", "cy", "w", "h", "espelhar", "chave")} | {
            "nome": f"🍿 {o['nome']}", "img": f"/react-personagens/{pid}/arquivo/cenario/{os.path.basename(o['cam'])}", "z": 3})
    pecas.append(dict(lay["tela"], chave="tela", nome="📺 TV", z=4, tv=True))
    foto_cam = arquivo_cena(p, foto, base) if foto else None
    pecas.append(dict(lay["foto"], chave="foto", nome="🖼 Foto / exemplo", z=5, foto=True,
                      img=url_cena(foto_cam) if foto_cam else None, ativa=bool(foto_cam)))
    fala = None
    if ativa:
        c = next((x for x in p["personagens"] if x["id"] == ativa["cid"]), None)
        if c:
            fala = {"nome": c["nome"], "texto": ativa["texto"], "cor": c.get("cor") or "#ffd54a"}
    pecas.append(dict(lay["legenda"], chave="legenda", nome="💬 Legenda", z=5, legenda=True, fala=fala))
    pecas.append({"chave": "cena", "nome": "🎬 Imagens de destaque (tela cheia)", "cx": W / 2, "cy": H / 2, "w": W, "h": H, "z": 6,
                  "cena_tela": True, "img": None})
    for cp in lay.get("copias") or []:
        src = next((x for x in pecas if x["chave"] == cp["de"]), None)
        if not src:
            continue
        n = dict(src, cx=cp["cx"], cy=cp["cy"], w=cp["w"], h=cp.get("h", src.get("h")), espelhar=bool(cp.get("espelhar")),
                 chave=cp["chave"], de=cp["de"], copia=True, nome=src["nome"] + " ⧉")
        if src.get("personagem") and bool(cp.get("espelhar")) != bool(src.get("espelhar")):
            n["espelhar_img"] = not src.get("espelhar_img")
        if src.get("personagem"):
            n["lado"] = "esq" if cp.get("espelhar") else "dir"
        pecas.append(n)
    pil = pilha(p, lay)
    for pc in pecas:
        pc["z"] = pil["ordem"].index(pc["chave"]) + 1
        pc["oculta"] = pc["chave"] in pil["ocultas"]
        pc["travada"] = pc["chave"] in pil["travadas"]
    cena_info = None
    if cena:
        cena_info = {"tipo": TIPOS_EVENTO[cena["tipo"]], "descricao": cena.get("descricao") or "",
                     "img": (f"/react-personagens/{pid}/arquivo/cenas/{cena['cena']['arquivo']}" if arquivo_cena(p, cena, base) else None)}
    return {"W": W, "H": H, "t": t, "layout": lay["layout"], "fundo": url_cam("fundo"), "fundo_espelhar": bool(lay["fundo"].get("espelhar")), "pecas": pecas, "pilha": pil, "cena": cena_info,
            "ajustadas": sorted(((p.get("posicoes") or {}).get(lay["layout"]) or {}).keys())}


def _pct(v: float, total: float) -> float:
    return round(v / total * 100, 3)


# ------------------------------------------------------------------ 🎬 linha do tempo dos personagens
def linhas_personagens(p: Dict[str, Any], falas: List[Dict[str, Any]], duracao: float) -> Dict[str, List[Dict[str, Any]]]:
    """cid → [{start, end, expressao, falando, bocas}] cobrindo o vídeo inteiro, sem buraco.
    v84_237: a cara FICA — depois de falar (ou reagir) o personagem continua com a última expressão até a próxima fala
    ou reação dele (nada de voltar pro neutro a cada fala); a fala pode trocar de cara no meio ('expressao_depois');
    trechos curtos demais (< 0,5 s) se juntam com o vizinho (sem piscar). 'bocas' = os trechos com palavra."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for c in p["personagens"]:
        evs: List[Dict[str, Any]] = []
        for f in falas:
            t, d = float(f["t"]), float(f["dur"])
            ini, fim = max(0.0, t - 0.15), min(duracao, t + d + 0.1)
            if f["cid"] == c["id"]:
                depois = f.get("expressao_depois") or ""
                if depois and depois != f["expressao"] and d >= 1.6:
                    meio = t + d * 0.55
                    evs.append({"start": ini, "end": meio, "expressao": f["expressao"], "falando": True, "bocas": [[t, meio]]})
                    evs.append({"start": meio, "end": fim, "expressao": depois, "falando": True, "bocas": [[meio, t + d]]})
                else:
                    evs.append({"start": ini, "end": fim, "expressao": f["expressao"], "falando": True, "bocas": [[t, t + d]]})
            else:
                r = next((x for x in f.get("reacoes") or [] if x["cid"] == c["id"]), None)
                if r:
                    evs.append({"start": min(duracao, ini + 0.3), "end": min(duracao, fim + 0.6), "expressao": r["expressao"],
                                "falando": False, "bocas": []})
        evs.sort(key=lambda e: (e["start"], not e["falando"]))
        limpos: List[Dict[str, Any]] = []
        for e in evs:  # quem fala ganha da reação no mesmo tempo
            e = dict(e)
            if limpos and e["start"] < limpos[-1]["end"]:
                a = limpos[-1]
                if e["falando"] or not a["falando"]:
                    a["end"] = e["start"]
                    if a["end"] - a["start"] < 0.3:
                        limpos.pop()
                else:
                    e["start"] = a["end"]
                    if e["end"] - e["start"] < 0.5:
                        continue
            limpos.append(e)
        # sem buraco: cada cara fica até a próxima (começa neutro)
        linha: List[Dict[str, Any]] = []
        t = 0.0
        atual = "neutro"
        for e in limpos:
            if e["end"] <= t + 0.02:
                continue
            e["start"] = max(e["start"], t)
            if e["start"] > t:
                linha.append({"start": t, "end": e["start"], "expressao": atual, "falando": False, "bocas": []})
            linha.append(e)
            atual = e["expressao"]
            t = e["end"]
        if duracao - t > 0.02 or not linha:
            linha.append({"start": t, "end": duracao, "expressao": atual, "falando": False, "bocas": []})
        # junta vizinhos com a mesma cara (somando as bocas) e engole os pedacinhos
        juntos: List[Dict[str, Any]] = []
        for e in linha:
            if juntos and (juntos[-1]["expressao"] == e["expressao"] or e["end"] - e["start"] < 0.5 and not e["falando"]):
                juntos[-1]["end"] = e["end"]
                juntos[-1]["bocas"] = juntos[-1]["bocas"] + e["bocas"]
                juntos[-1]["falando"] = bool(juntos[-1]["bocas"])
            else:
                juntos.append(dict(e))
        if juntos:
            juntos[-1]["end"] = duracao
        out[c["id"]] = [dict(e, start=round(e["start"], 3), end=round(e["end"], 3),
                             bocas=[[round(a, 3), round(b, 3)] for a, b in e["bocas"]]) for e in juntos]
    return out


def _ancora_alfa(im) -> Optional[Tuple[float, int]]:
    """Onde o personagem 'senta' na imagem: o centro x do corpo (parte de baixo, 40%) e a linha mais baixa."""
    a = im.getchannel("A").point(lambda v: 255 if v > 40 else 0)
    caixa = a.getbbox()
    if not caixa:
        return None
    x0, y0, x1, y1 = caixa
    faixa = a.crop((x0, y0 + int((y1 - y0) * 0.6), x1, y1))
    fb = faixa.getbbox()
    cx = x0 + ((fb[0] + fb[2]) / 2 if fb else (x1 - x0) / 2)
    return cx, y1


def alinhar_pose(cam: str, ref: Optional[Tuple[Tuple[int, int], Tuple[float, int]]], destino: str) -> str:
    """Encaixa a pose no mesmo lugar da ⭐ neutra (o corpo no mesmo ponto do sofá) — sem isso, cada expressão gerada
    vinha um pouco deslocada e o personagem 'pulava' na troca de cara."""
    from PIL import Image
    if not ref:
        return cam
    (rw, rh), (rcx, rby) = ref
    im = Image.open(cam).convert("RGBA")
    if im.size != (rw, rh):
        im = im.resize((rw, rh), Image.LANCZOS)
    an = _ancora_alfa(im)
    if not an:
        return cam
    dx, dy = int(round(rcx - an[0])), int(round(rby - an[1]))
    if abs(dx) <= 2 and abs(dy) <= 2 and im.size == Image.open(cam).size:
        return cam
    tela = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
    tela.paste(im, (dx, dy), im)
    tela.save(destino)
    return destino


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

    fundo = camada_papel(p, "fundo", base)
    fundo = copiar(fundo, "fundo.png") if fundo else fundo_padrao(os.path.join(d, "fundo.png"), est)
    if not camada_papel(p, "fundo", base):
        avisos.append("sem a camada do fundo — usei uma parede lisa (gere o 🧱 Fundo e mande de novo, ou troque no editor)")
    lay = disposicao(p, base, (info["largura"] or 16, info["altura"] or 9))
    if lay["fundo"].get("espelhar"):  # ↔ o fundo espelhado
        from PIL import ImageOps
        ImageOps.mirror(Image.open(fundo).convert("RGB")).save(fundo)
    overlays: List[Dict[str, Any]] = []
    grupos: Dict[str, List[Dict[str, Any]]] = {}
    grupo_atual = [""]

    def png(oid: str, nome: str, cam: str, cx: float, cy: float, w: float, start: float, end: float, camada: str,
            espelhar: bool = False, **extra: Any) -> Dict[str, Any]:
        ov = {"id": oid, "origem": "react", "camada": camada, "personagem": f"react_{camada}", "nome_personagem": nome,
              "source": {"source": "local_file", "value": cam, "kind": "image"}, "media_type": "image",
              "start": round(start, 3), "end": round(end, 3), "position": "bottom-left", "ancora": "centro",
              "size_percent": _pct(w, W), "x_percent": _pct(cx, W), "y_percent": _pct(cy, H),
              "anim_in": "nenhuma", "anim_out": "nenhuma", "anim_dur": 0.2, "espelhar": bool(espelhar),
              "boca_path": None, "boca_janelas": [], "manual": True}
        ov.update(extra)
        ov.setdefault("pilha_chave", grupo_atual[0])
        grupos.setdefault(grupo_atual[0], []).append(ov)
        return ov

    sofa = camada_papel(p, "assento", base)
    for k, s in enumerate(lay["sofas"]):
        im_s = img_sofa(p, s, base)
        if not im_s:
            avisos.append("sem a camada " + (ROTULO_CAMADA.get(s.get("camada") or "", "") or ("da fileira de poltronas" if layout_de(p) in CINEMA else "do sofá")))
            continue
        grupo_atual[0] = f"sofa{k}"
        png(f"rsofa{k}", ("💺 Encostos (primeiro plano)" if s.get("plano") else "💺 Fileira" if layout_de(p) in CINEMA else "🛋 Sofá"),
            copiar(im_s, f"sofa{k}.png"), s["cx"], s["cy"], s["w"], 0, dur, "sofa", espelhar=s.get("espelhar", False))
    # personagens
    falas = falas_no_tempo(p, falas_proj, dur)
    linhas = linhas_personagens(p, falas, dur)
    aus = ausencias(p, dur)  # 🚪 quem saiu da sala some do sofá até voltar
    estilos = estilos_no_lugar(p, base)  # 🎨 desenhado diferente no lugar dele por uns segundos
    gestos, faltam_g = gestos_no_lugar(p, lay, base)  # 🍿 cinema de perto: o gesto no lugar dele
    avisos.extend(faltam_g)
    for a in lay["assentos"]:
        c = personagem(p, a["cid"])
        grupo_atual[0] = f"p:{c['id']}"
        lado = a.get("lado") or ("esq" if a["espelhar"] else "dir")
        fora_cid = (aus.get(c["id"], []) + [[ini, fim] for ini, fim, _cam in estilos.get(c["id"], [])]
                    + [[ini, fim] for ini, fim, *_r in gestos.get(c["id"], [])])
        for k, (ini, fim, cam_g, esp_g, g) in enumerate(gestos.get(c["id"], [])):
            if presente(aus, c["id"], ini):
                png(f"r{c['id']}_gesto{k}", f"🍿 {c['nome']}", copiar(cam_g, f"{c['id']}_gesto{k}.png"), a["cx"], a["cy"],
                    a["w"], ini, min(dur, fim), "personagem", espelhar=esp_g, cid=c["id"], expressao=g)
        for k, (ini, fim, cam_est) in enumerate(estilos.get(c["id"], [])):
            if not presente(aus, c["id"], ini):
                continue
            iw, ih = _tam(cam_est, (2, 3))
            h_fig = a["h"] * 0.95
            w_fig = min(h_fig * iw / ih, a["w"] * 1.6)
            h_fig = w_fig * ih / iw
            png(f"r{c['id']}_estilo{k}", f"🎨 {c['nome']}", copiar(cam_est, f"{c['id']}_estilo{k}.png"), a["cx"],
                a["cy"] + a["h"] / 2 - h_fig / 2, w_fig, ini, min(dur, fim), "personagem", cid=c["id"], expressao="estilo")
        poses = poses_do_personagem(c, base, lado)
        espelhadas = sorted(e for e, x in poses.items() if x.get("espelhar"))
        if espelhadas:
            avisos.append(f"{c['nome']} olha pra {'esquerda' if lado == 'esq' else 'direita'} aqui e ainda não tem essas poses "
                          f"({', '.join(espelhadas)}) — espelhei as do outro lado (🧍 Gerar o que falta faz as certas)")
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
                poses = {"neutro": {"pose": cam, "boca": None, "espelhar": a["espelhar"]}}
            else:
                continue
        copiados: Dict[str, str] = {}
        # 📐 a ⭐ neutra é a referência: as outras poses (e as bocas) se encaixam no mesmo ponto do sofá
        ref_alin = None
        try:
            neu = (poses.get("neutro") or next(iter(poses.values())))["pose"]
            im_n = Image.open(neu).convert("RGBA")
            an_n = _ancora_alfa(im_n)
            ref_alin = (im_n.size, an_n) if an_n else None
        except Exception:  # noqa: BLE001
            ref_alin = None

        de_costas = lado == "costas" and any(k in poses for k in EXPR_COSTAS)
        if lado == "costas" and not de_costas:
            avisos.append(f"{c['nome']}: ainda sem as poses de COSTAS do cinema (🧍 Gerar o que falta) — usei as de frente")

        def pose_de(ex: str, falando: bool = False) -> Tuple[str, Optional[str], bool]:
            if de_costas:
                ex = expr_lado(ex, "costas", falando)
            x = poses.get(ex) or poses.get("neutro") or next(iter(poses.values()))
            pc = x["pose"]
            for cam in [pc] + ([x["boca"]] if x.get("boca") else []):
                if cam not in copiados:
                    dst = os.path.join(d, f"{c['id']}_{os.path.basename(cam)}")
                    try:
                        feito = alinhar_pose(cam, ref_alin, dst)
                    except Exception:  # noqa: BLE001
                        feito = cam
                    copiados[cam] = dst if feito == dst else copiar(cam, os.path.basename(dst))
            bc = x.get("boca")
            return copiados[pc], (copiados[bc] if bc else None), bool(x.get("espelhar"))

        faltou = sorted({expr_lado(e["expressao"], "costas", e.get("falando")) if de_costas else e["expressao"]
                         for e in linhas.get(c["id"], [])} - set(poses))
        if faltou:
            avisos.append(f"{c['nome']}: sem a pose {', '.join(faltou)} ainda — usei a neutra nesses momentos")
        for k, e in enumerate(recortar_presenca(linhas.get(c["id"], []), fora_cid)):
            pc, bc, esp = pose_de(e["expressao"], bool(e.get("falando")))
            jan = [j for x, y in (e.get("bocas") or []) for j in _boca_janelas(x, y)] if bc else []
            jan = [[max(x, e["start"]), min(y, e["end"])] for x, y in jan if min(y, e["end"]) - max(x, e["start"]) > 0.1]
            png(f"r{c['id']}_{k}", c["nome"], pc, a["cx"], a["cy"], a["w"], e["start"], e["end"], "personagem",
                espelhar=esp, expressao=e["expressao"], falando=e["falando"], cid=c["id"],
                boca_path=bc if jan else None, boca_janelas=jan, trilha=f"p:{c['id']}")
    anda, av_anda = andantes(p, lay, dur, base)  # 🚶 quem anda pela fileira / 🌑 quem passa na frente
    avisos.extend(av_anda)
    for k, w_ in enumerate(anda):
        grupo_atual[0] = f"andar{w_['fila']}"
        png(f"randa{k}", f"🚶 {w_['nome']}", copiar(w_["cam"], f"anda{k}_{os.path.basename(w_['cam'])}"), w_["cx"], w_["cy"],
            w_["w"], w_["a"], w_["b"], "personagem", espelhar=w_["espelhar"], cid=w_["cid"] or None,
            mov=[{"a": w_["a"], "b": w_["b"], "z": w_["b"], "de": round(w_["de"], 5), "para": round(w_["para"], 5)}]
            + _passos(w_["a"], w_["b"]))
    mesa = camada_papel(p, "mesa", base)
    if mesa:
        m = lay["mesa"]
        grupo_atual[0] = "mesa"
        png("rmesa", "🪵 Mesa", copiar(mesa, "mesa.png"), m["cx"], m["cy"], m["w"], 0, dur, "mesa", espelhar=bool(m.get("espelhar")))
    elif layout_de(p) not in CINEMA:
        avisos.append("sem a camada da mesa")
    for o in lay.get("objetos") or []:  # 🍿 os itens em cima da mesa (cada um a sua camada)
        grupo_atual[0] = o["chave"]
        png(f"robj_{o['id']}", f"🍿 {o['nome']}", copiar(o["cam"], f"obj_{o['id']}.png"), o["cx"], o["cy"], o["w"], 0, dur, "objeto",
            espelhar=bool(o.get("espelhar")))
    # TV: a moldura (PNG) + o vídeo na tela
    t = lay["tela"]
    tv_png, borda = desenhar_tv(int(round(t["w"])), int(round(t["h"])), os.path.join(d, "tv.png"))
    tw, th = _tam(tv_png, (int(t["w"]), int(t["h"])))
    # o centro da moldura: a tela fica a `borda` px da esquerda/topo do PNG
    tv_cx = t["cx"] - t["w"] / 2 - borda + tw / 2
    tv_cy = t["cy"] - t["h"] / 2 - borda + th / 2
    grupo_atual[0] = "tela"
    png("rtv", "📺 TV", tv_png, tv_cx, tv_cy, tw, 0, dur, "tv")
    # legendas
    nomes = {c["id"]: c for c in p["personagens"]}
    leg = lay["legenda"]
    grupo_atual[0] = "legenda"
    for k, f in enumerate(falas):
        c = nomes.get(f["cid"])
        if not c:
            continue
        cam, lw, lh = desenhar_legenda(c["nome"], f["texto"], c.get("cor") or "#ffd54a", int(leg["w"]),
                                       os.path.join(d, f"legenda_{k:03d}.png"))
        cam, lw, lh = _legenda_na_tela(cam, int(leg["w"]))  # todas do mesmo tamanho → uma trilha só no render
        png(f"rleg{k:03d}", f"💬 {c['nome']}", cam, leg["cx"], leg["topo"] + lh / 2, lw, f["t"], f["t"] + f["dur"], "legenda",
            fala=f["texto"], cid=c["id"], cta=bool(f.get("cta")), trilha="legenda")
    # o vídeo na TV fica logo acima da moldura (a ordem das camadas é a da 🗂 pilha que você arrumou)
    grupos.setdefault("tela", []).append({"id": "rtela", "origem": "react_tela", "camada": "tela", "nome_personagem": "📺 Vídeo na TV",
                     "source": {"source": "local_file", "value": video, "kind": "video"}, "media_type": "video",
                     "start": 0.0, "end": round(dur, 3), "position": "top-right", "ancora": "centro", "sincronizar": True,
                     "size_percent": _pct(t["w"], W), "x_percent": _pct(t["cx"], W), "y_percent": _pct(t["cy"], H),
                     "espelhar": bool(t.get("espelhar"))})
    # ⚡ brigas / interações / cenas: a imagem ocupa a tela toda por uns segundos (a legenda continua por cima, como
    # visual novel); 🖼 foto/exemplo: um quadro por cima, onde a peça "Foto" está no palco
    fo = lay["foto"]
    for e in eventos(p):
        if e["tipo"] not in EVENTO_COM_IMAGEM or not p.get("imagens_destaque", True):
            continue
        cam = arquivo_cena(p, e, base)
        if not cam:
            avisos.append(f"{TIPOS_EVENTO[e['tipo']]} em {mmss(e['t'])} ainda sem imagem — ficou de fora (⚡ Intrigas → 🚀 Gerar)")
            continue
        ini = float(e["t"])
        fim = min(dur, ini + float(e["dur"]))
        if EXIBICAO[e["tipo"]] == "tela":
            grupo_atual[0] = "cena"
            png(f"rcena_{e['id']}", TIPOS_EVENTO[e["tipo"]], copiar(cam, f"cena_{e['id']}{os.path.splitext(cam)[1]}"),
                W / 2, H / 2, W, ini, fim, "cena", descricao=e.get("descricao") or "", trilha="cena")
        elif EXIBICAO[e["tipo"]] == "quadro":
            grupo_atual[0] = "foto"
            moldurada = moldura_foto(cam, os.path.join(d, f"foto_{e['id']}.png"))
            iw, ih = _tam(moldurada, (4, 3))
            png(f"rfoto_{e['id']}", TIPOS_EVENTO[e["tipo"]], moldurada, fo["cx"], fo["cy"], fo["w"], ini, fim, "foto",
                descricao=e.get("descricao") or "", anim_in="aparecer", anim_out="aparecer", anim_dur=0.25,
                espelhar=bool(fo.get("espelhar")))
    # ⧉ as cópias: as mesmas camadas da original, levadas pro lugar/tamanho (e lado) da cópia
    for cp in lay.get("copias") or []:
        src = peca_geo(lay, cp["de"])
        if not src:
            continue
        k = cp["w"] / max(1.0, src["w"])
        virar = bool(cp.get("espelhar")) != bool(src.get("espelhar"))
        for ov in grupos.get(cp["de"], []):
            n = dict(ov)
            ox, oy = float(ov["x_percent"]) * W / 100, float(ov["y_percent"]) * H / 100
            dx = (ox - src["cx"]) * (-1 if virar else 1)
            n.update(id=f"{ov['id']}_{cp['id']}", x_percent=_pct(cp["cx"] + dx * k, W), y_percent=_pct(cp["cy"] + (oy - src["cy"]) * k, H),
                     size_percent=round(float(ov["size_percent"]) * k, 4), copia=cp["chave"])
            if virar:
                n["espelhar"] = not ov.get("espelhar")
            if ov.get("trilha"):
                n["trilha"] = f"{ov['trilha']}|{cp['id']}"
            grupos.setdefault(cp["chave"], []).append(n)
    pil = pilha(p, lay)
    ordem = [k for k in pil["ordem"] if k not in pil["ocultas"]]  # a 🎬 cena também é camada da pilha (v84_244)
    for fila, antes in ((1, "sofa0"), (0, "sofa1")):  # 🚶 quem anda: logo antes das poltronas que o cobrem
        if f"andar{fila}" in grupos:
            ordem.insert(ordem.index(antes) if antes in ordem else len(ordem), f"andar{fila}")
    for chave in ordem:
        overlays.extend(grupos.get(chave, []))
    if pil["ocultas"]:
        avisos.append(f"{len(pil['ocultas'])} camada(s) oculta(s) 👁 não foram pro editor")
    seg = {"start": 0.0, "end": round(dur, 3), "provider": "material", "query": f"🎭 react — cenário ({p.get('titulo') or ''})"[:150],
           "on_screen_text": None, "media_type": "image", "zoom_direction": "static", "efeito": None,
           "override_source": {"source": "local_file", "value": fundo, "kind": "image", "zoom_direction": "static",
                               "focus_x": 0.5, "focus_y": 0.5}}
    return {"audio": audio, "duracao": dur, "segmento": seg, "overlays": overlays, "avisos": avisos,
            "falas": [{"start": f["t"], "end": round(f["t"] + f["dur"], 3), "text": f"{nomes[f['cid']]['nome']}: {f['texto']}"}
                      for f in falas if f["cid"] in nomes]}


def chave_do_overlay(ov: Dict[str, Any]) -> Optional[str]:
    """A camada da 🗂 pilha de onde veio a camada do editor (os projetos antigos não guardavam: deduz)."""
    if ov.get("copia"):
        return str(ov["copia"])
    if ov.get("pilha_chave"):
        return str(ov["pilha_chave"])
    cam = ov.get("camada")
    if cam in ("cena", "foto", "legenda", "tela", "mesa"):
        return cam
    tr = str(ov.get("trilha") or "")
    if tr.startswith("p:"):
        return tr.split("|")[0]
    if cam == "personagem" and ov.get("cid") and not str(ov.get("nome_personagem") or "").startswith("🚶"):
        return f"p:{ov['cid']}"
    if cam == "sofa" and str(ov.get("id") or "").startswith("rsofa"):
        return "sofa" + str(ov["id"])[5:]
    return None


def filtrar_ocultas_editor(pid: Optional[str], overlays: List[Dict[str, Any]], base: str = _BASE) -> List[Dict[str, Any]]:
    """🎭 Na hora de exportar: o que está escondido 👁 no palco do react AGORA não vai pro vídeo (vale pro projeto que
    já estava no editor) — e com o 🖼 imagens de destaque desligado, nem as cenas/fotos."""
    if not pid:
        return overlays
    try:
        p = carregar(pid, base)
        pil = pilha(p, disposicao(p, base))
    except Exception:  # noqa: BLE001
        return overlays
    fora = set(pil["ocultas"])
    if not p.get("imagens_destaque", True):
        fora |= {"cena", "foto"}
    if not fora:
        return overlays
    out = []
    for ov in overlays:
        if ov.get("origem") in ("react", "react_tela") and chave_do_overlay(ov) in fora:
            continue
        out.append(ov)
    return out


# ------------------------------------------------------------------ 👁 prévia (uma imagem do react pronto)
def previa(p: Dict[str, Any], base: str, destino: str, t: Optional[float] = None, legenda: bool = True) -> str:
    """Uma imagem de como o react fica (no segundo t: quem fala, a legenda, o quadro do vídeo na TV), na ordem das camadas."""
    from PIL import Image, ImageOps
    est = estilo_final(p)
    video = _video_local(p, base)
    info = sondar(video) if video else {"duracao": 0, "largura": 16, "altura": 9}
    lay = disposicao(p, base, (info.get("largura") or 16, info.get("altura") or 9))
    fundo = camada_papel(p, "fundo", base)
    tela = Image.open(fundo).convert("RGBA") if fundo else Image.open(fundo_padrao(destino + ".fundo.png", est)).convert("RGBA")
    if not fundo:
        try:
            os.remove(destino + ".fundo.png")
        except OSError:
            pass
    tela = tela.resize((W, H))
    if lay["fundo"].get("espelhar"):
        tela = ImageOps.mirror(tela)

    def colar(cam: str, cx: float, cy: float, w: float, espelhar: bool = False) -> None:
        im = Image.open(cam).convert("RGBA")
        h = w * im.height / im.width
        im = im.resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS)
        if espelhar:
            im = ImageOps.mirror(im)
        tela.alpha_composite(im, (int(cx - w / 2), int(cy - h / 2))) if cx - w / 2 >= 0 and cy - h / 2 >= 0 else \
            _colar_cortando(tela, im, int(cx - w / 2), int(cy - h / 2))

    falas = falas_no_tempo(p, (p.get("roteiro") or {}).get("falas") or [], info.get("duracao") or None)
    if t is None:
        t = (falas[0]["t"] + 0.5) if falas else 0.0
    ativa = next((f for f in falas if f["t"] <= t < f["t"] + f["dur"]), None)
    linhas = linhas_personagens(p, falas, max(info.get("duracao") or 0, t + 1)) if falas else {}
    sofa = camada_papel(p, "assento", base)
    mesa = camada_papel(p, "mesa", base)

    def desenha_sofa(k: int) -> None:
        if k < len(lay["sofas"]):
            s = lay["sofas"][k]
            im_s = img_sofa(p, s, base)
            if im_s:
                colar(im_s, s["cx"], s["cy"], s["w"], s.get("espelhar", False))

    def desenha_personagem(cid: str, geo: Optional[Dict[str, Any]] = None) -> None:
        a = next((x for x in lay["assentos"] if x["cid"] == cid), None)
        if not a:
            return
        if geo:  # ⧉ cópia: o mesmo personagem (mesma cara no segundo t) no lugar da cópia
            a = dict(a, cx=geo["cx"], cy=geo["cy"], w=geo["w"], h=geo.get("h", a["h"]), espelhar=bool(geo.get("espelhar")))
        c = personagem(p, cid)
        g_at = next((x for x in gestos.get(cid, []) if x[0] <= t < x[1]), None)  # 🍿 o gesto no lugar dele
        if g_at and not geo:
            colar(g_at[2], a["cx"], a["cy"], a["w"], g_at[3])
            return
        est_cam = next((cam for ini, fim, cam in estilos.get(cid, []) if ini <= t < fim), None)
        if est_cam:
            iw, ih = _tam(est_cam, (2, 3))
            h_fig = a["h"] * 0.95
            w_fig = min(h_fig * iw / ih, a["w"] * 1.6)
            h_fig = w_fig * ih / iw
            colar(est_cam, a["cx"], a["cy"] + a["h"] / 2 - h_fig / 2, w_fig)
            return
        x, _ex = _pose_no_tempo(p, c, a, base, linhas, t)
        cam = (x or {}).get("pose")
        esp = bool((x or {}).get("espelhar")) if x else a["espelhar"]
        if not cam:
            ref = next((os.path.join(pasta(p["id"], base), "refs", r) for r in c.get("refs") or []
                        if os.path.isfile(os.path.join(pasta(p["id"], base), "refs", r))), None)
            if not ref:
                return
            im = Image.open(ref).convert("RGBA")
            canvas = Image.new("RGBA", (1200, 1800), (0, 0, 0, 0))
            k = min(1140 / im.width, 1700 / im.height)
            im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))))
            canvas.paste(im, ((1200 - im.width) // 2, 1800 - im.height), im)
            cam = destino + f".{c['id']}.png"
            canvas.save(cam)
        colar(cam, a["cx"], a["cy"], a["w"], esp)
        if cam.startswith(destino + "."):
            os.remove(cam)

    def desenha_tela(tl: Optional[Dict[str, Any]] = None) -> None:
        tl = tl or lay["tela"]
        tv, borda = desenhar_tv(int(tl["w"]), int(tl["h"]), destino + ".tv.png")
        tw, th = _tam(tv, (1, 1))
        colar(tv, tl["cx"] - tl["w"] / 2 - borda + tw / 2, tl["cy"] - tl["h"] / 2 - borda + th / 2, tw)
        os.remove(tv)
        if video:
            q = destino + ".q.jpg"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", video, "-frames:v", "1", q],
                           capture_output=True, timeout=60)
            if os.path.isfile(q):
                colar(q, tl["cx"], tl["cy"], tl["w"], bool(tl.get("espelhar")))
                os.remove(q)

    def desenha_legenda() -> None:
        if not ativa:
            return
        c = next((x for x in p["personagens"] if x["id"] == ativa["cid"]), None)
        if c:
            leg = lay["legenda"]
            cam, lw, lh = desenhar_legenda(c["nome"], ativa["texto"], c.get("cor") or "#ffd54a", int(leg["w"]), destino + ".leg.png")
            colar(cam, leg["cx"], leg["topo"] + lh / 2, lw)
            os.remove(cam)

    aus = ausencias(p, max(info.get("duracao") or 0, t + 1))
    cena = cena_ativa(p, t)
    cena_cam = arquivo_cena(p, cena, base) if cena else None
    foto = cena_ativa(p, t, "quadro")
    foto_cam = arquivo_cena(p, foto, base) if foto else None
    estilos = estilos_no_lugar(p, base)
    gestos, _fg = gestos_no_lugar(p, lay, base)
    anda, _fa = andantes(p, lay, max(info.get("duracao") or 0, t + 1), base)

    def desenha_andantes(fila: int) -> None:
        for w_ in anda:
            if w_["fila"] == fila and w_["a"] <= t <= w_["b"]:
                k = min(1.0, max(0.0, (t - w_["a"]) / max(0.001, w_["b"] - w_["a"])))
                colar(w_["cam"], w_["cx"] + W * (w_["de"] + (w_["para"] - w_["de"]) * k), w_["cy"], w_["w"], w_["espelhar"])

    pil = pilha(p, lay)
    ordem = [k for k in pil["ordem"] if k not in pil["ocultas"]]
    for fila, antes in ((1, "sofa0"), (0, "sofa1")):
        if any(w_["fila"] == fila for w_ in anda):
            ordem.insert(ordem.index(antes) if antes in ordem else len(ordem), f"andar{fila}")
    for chave in ordem:
        if chave.startswith("andar"):
            desenha_andantes(int(chave[5:]))
            continue
        if chave == "cena":
            if cena_cam:
                colar(cena_cam, W / 2, H / 2, W)
        elif chave == "foto":
            if foto_cam:
                fo = lay["foto"]
                mold = moldura_foto(foto_cam, destino + ".foto.png")
                colar(mold, fo["cx"], fo["cy"], fo["w"], bool(fo.get("espelhar")))
                os.remove(mold)
        elif chave.startswith("c:"):
            cp = next((x for x in lay.get("copias") or [] if x["chave"] == chave), None)
            if not cp:
                continue
            if cp["de"].startswith("sofa") and sofa:
                colar(sofa, cp["cx"], cp["cy"], cp["w"], bool(cp.get("espelhar")))
            elif cp["de"] == "mesa" and mesa:
                colar(mesa, cp["cx"], cp["cy"], cp["w"], bool(cp.get("espelhar")))
            elif cp["de"] == "tela":
                desenha_tela(cp)
            elif cp["de"].startswith("p:") and presente(aus, cp["de"][2:], t):
                desenha_personagem(cp["de"][2:], cp)
        elif chave.startswith("p:") and not presente(aus, chave[2:], t):
            continue
        elif chave.startswith("sofa"):
            desenha_sofa(int(chave[4:]))
        elif chave.startswith("p:"):
            desenha_personagem(chave[2:])
        elif chave == "mesa" and mesa:
            m = lay["mesa"]
            colar(mesa, m["cx"], m["cy"], m["w"], bool(m.get("espelhar")))
        elif chave.startswith("o:"):  # 🍿 item da mesa
            o = next((x for x in lay.get("objetos") or [] if x["chave"] == chave), None)
            if o:
                colar(o["cam"], o["cx"], o["cy"], o["w"], bool(o.get("espelhar")))
        elif chave == "tela":
            desenha_tela()
        elif chave == "legenda" and legenda:
            desenha_legenda()
    tela.convert("RGB").save(destino, "JPEG", quality=88)
    return destino


def moldura_foto(cam: str, destino: str) -> str:
    """🖼 A foto/exemplo com borda branca de polaroid e sombra — parece uma foto que apareceu."""
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.open(cam).convert("RGB")
    k = min(1200 / im.width, 1200 / im.height, 1.0)
    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
    b = max(10, int(min(im.size) * 0.04))
    sombra = 18
    tela = Image.new("RGBA", (im.width + 2 * b + 2 * sombra, im.height + 3 * b + 2 * sombra), (0, 0, 0, 0))
    sb = Image.new("RGBA", tela.size, (0, 0, 0, 0))
    ImageDraw.Draw(sb).rectangle([sombra + 6, sombra + 8, tela.width - sombra + 6, tela.height - sombra + 8], fill=(0, 0, 0, 140))
    tela.alpha_composite(sb.filter(ImageFilter.GaussianBlur(9)))
    ImageDraw.Draw(tela).rectangle([sombra, sombra, tela.width - sombra - 1, tela.height - sombra - 1], fill=(250, 250, 246, 255))
    tela.paste(im, (sombra + b, sombra + b))
    tela.save(destino)
    return destino


def _legenda_na_tela(cam: str, largura: int) -> Tuple[str, int, int]:
    """A legenda numa tela transparente de tamanho fixo (a caixa em cima, centralizada): todas iguais em tamanho e
    lugar — o render junta numa trilha só."""
    from PIL import Image
    im = Image.open(cam).convert("RGBA")
    alt = max(im.height, 280)
    largura = max(largura, im.width)
    tela = Image.new("RGBA", (largura, alt), (0, 0, 0, 0))
    tela.paste(im, ((largura - im.width) // 2, 0), im)
    tela.save(cam)
    return cam, largura, alt


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
        x["lado"] = lados_precisos(p, c["id"], base)[0]
        out["personagens"].append(x)
    lay_nome = p.get("layout") if p.get("layout") in LAYOUTS else "sofa_tv"
    out["sofas"] = sofas_de(p, lay_nome)  # 🛋 quem senta onde (ordem da esquerda pra direita)
    out["recomendado"] = RECOMENDADO.get(lay_nome, 6)
    out["minimo"] = MINIMO.get(lay_nome, 1)
    out["maximo"] = MAXIMO_LAYOUT.get(lay_nome, MAXIMO)
    out["cinema"] = lay_nome in CINEMA
    out["movimentos_ok"] = movimentos_ligados(p)
    out["fileiras"] = FILEIRAS.get(lay_nome, 0)
    out["camadas_lista"] = list(camadas_do_layout(p))
    out["camadas"] = {q: dict((p["cenario"]["camadas"].get(q) or {}), tem=bool(camada_arquivo(p, q, base))) for q in CAMADAS}
    out["rotulo_camada"] = ROTULO_CAMADA
    out["ia"] = ia_ligada()
    out["partes"] = estado_partes(p)
    out["eventos"] = [dict(e, tem_imagem=bool(arquivo_cena(p, e, base))) for e in eventos(p)]
    out["leitura_estado"] = estado_leitura(p, base)
    if (p.get("roteiro") or {}).get("falas"):  # 👂 a tabela já mostra o segundo em que cada um fala (depois de ouvir)
        out["roteiro"] = dict(p["roteiro"], falas=depois_de_ouvir(p, p["roteiro"]["falas"]))
    b = p.get("biblia") or {}
    out["biblia_info"] = {"chars": len(b.get("texto") or ""), "resumo": b.get("resumo") or {},
                          "desatualizado": bool(b.get("resumo_desatualizado"))}
    out.pop("biblia", None)  # o texto (até 80 mil letras) vai só na página, não a cada atualização
    out.pop("leitura", None)
    try:
        import gemini_servico as gm
        out["gemini"] = bool(gm.chave())
    except Exception:  # noqa: BLE001
        out["gemini"] = False
    return out


# ------------------------------------------------------------------ 🖼 thumbnail do react (v84_237)
# A capa no padrão dos reacts: os personagens reagindo (alguns ou todos, com a cara escolhida) de um lado e o quadro do
# vídeo do outro. Usa o sistema de capas das 📣 Publicações (texto, fontes, versões, modificar no Flow): o react vira
# uma publicação (publicacoes/<id do react>) com o contexto guardado.
EXPR_EN_CAPA = {k: v[1] for k, v in EXPRESSOES.items()}


def ctx_publicacao(p: Dict[str, Any], base: str = _BASE) -> Dict[str, Any]:
    nomes = {c["id"]: c["nome"] for c in p["personagens"]}
    falas = "\n".join(f"{mmss(f['t'])} {nomes.get(f['cid'], '?')}: {f['texto']}" for f in (p.get("roteiro") or {}).get("falas") or [])
    pers = []
    for c in p["personagens"]:
        x, _cam = pose_capa(p, c, "neutro", "dir", base)
        pers.append({"slug": c["id"], "nome": c["nome"], "visual_en": (c.get("aparencia_en") or "")[:700],
                     "personalidade": (c.get("personalidade") or "")[:200], "ref": _cam})
    idi = p.get("idioma") or "português do Brasil"
    cod = "pt" if "portugu" in idi.lower() else "en" if "ingl" in idi.lower() or "english" in idi.lower() else "es" if "espanh" in idi.lower() else "pt"
    return {"idioma": {"codigo": cod, "nome": idi}, "canal": "",
            "narracao": ("VÍDEO REAGIDO: " + (p.get("titulo") or "") + "\nTRANSCRIÇÃO: " + transcricao_texto(p.get("transcricao") or [], 6000)
                         + "\n\nFALAS DO REACT:\n" + falas)[:14000],
            "personagens": pers, "projeto": {"tema": f"React de {', '.join(nomes.values())} a: {p.get('titulo') or ''}"[:300],
                                              "roteiro": falas[:20000]},
            "duracao": float((p.get("video") or {}).get("duracao") or 0)}


def sincronizar_publicacao(p: Dict[str, Any], base: str = _BASE) -> str:
    """O react como publicação (títulos, descrição, tags e capas no mesmo sistema da aba 📣 Publicações)."""
    import publicacao as PB
    pd = PB.pdir_de(base, p["id"])
    PB.salvar_ctx(pd, ctx_publicacao(p, base), {"titulo": f"🎭 {p.get('titulo') or 'React'}", "tem_projeto": False, "react": p["id"]})
    return pd


def pose_capa(p: Dict[str, Any], c: Dict[str, Any], expr: str, olhar: str, base: str = _BASE) -> Tuple[bool, Optional[str]]:
    """(espelhar, caminho) da pose do personagem com essa cara, olhando pra `olhar` — ou a imagem de referência."""
    poses = poses_do_personagem(c, base, olhar)
    x = poses.get(expr) or poses.get("neutro") or (next(iter(poses.values())) if poses else None)
    if x:
        return bool(x.get("espelhar")), x["pose"]
    ref = next((os.path.join(pasta(p["id"], base), "refs", r) for r in c.get("refs") or []
                if os.path.isfile(os.path.join(pasta(p["id"], base), "refs", r))), None)
    return False, ref


def _contorno(im, raio: int = 7, cor=(255, 255, 255, 255)):
    """Contorno branco em volta do recorte (o jeito das thumbs)."""
    from PIL import Image, ImageFilter
    a = im.getchannel("A")
    borda = a.filter(ImageFilter.MaxFilter(raio * 2 + 1))
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.paste(Image.new("RGBA", im.size, cor), (0, 0), borda)
    out.alpha_composite(im)
    return out


CAPA_W, CAPA_H = 1280, 720


def capa_cfg(p: Dict[str, Any], dados: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A configuração da capa (guardada no projeto) com o que veio agora por cima."""
    cfg = dict(p.get("capa") or {})
    for k, v in (dados or {}).items():
        if v is not None and k in ("cids", "exprs", "t", "lado", "seta", "pos", "ordem", "ocultas", "imagem", "quadro_off"):
            cfg[k] = v
    ids = [c["id"] for c in p["personagens"]]
    cfg["cids"] = [c for c in (cfg.get("cids") or []) if c in ids] if isinstance(cfg.get("cids"), list) else ids
    cfg["exprs"] = {k: v for k, v in (cfg.get("exprs") or {}).items() if v in EXPRESSOES}
    cfg["t"] = segundos(cfg.get("t")) or 0.0
    cfg["lado"] = "esquerda" if cfg.get("lado") == "esquerda" else "direita"
    cfg["seta"] = cfg.get("seta", True) not in (False, 0, "0", "false")
    cfg["pos"] = {k: v for k, v in (cfg.get("pos") or {}).items() if isinstance(v, dict)}
    cfg["ordem"] = [str(x) for x in cfg.get("ordem") or []]
    cfg["ocultas"] = [str(x) for x in cfg.get("ocultas") or []]
    cfg["quadro_off"] = bool(cfg.get("quadro_off"))
    return cfg


def _pasta_capa(p: Dict[str, Any], base: str) -> str:
    d = os.path.join(pasta(p["id"], base), "_capa")
    os.makedirs(d, exist_ok=True)
    return d


def _capa_fundo(p: Dict[str, Any], base: str, quadro) -> str:
    from PIL import Image, ImageEnhance, ImageFilter
    fundo = camada_papel(p, "fundo", base)
    if fundo:
        bg = Image.open(fundo).convert("RGB")
    elif quadro is not None:
        bg = quadro.copy()
    else:
        bg = Image.new("RGB", (CAPA_W, CAPA_H), (30, 24, 50))
    k = max(CAPA_W / bg.width, CAPA_H / bg.height)
    bg = bg.resize((int(bg.width * k + 0.5), int(bg.height * k + 0.5)), Image.LANCZOS)
    x0, y0 = (bg.width - CAPA_W) // 2, (bg.height - CAPA_H) // 2
    bg = bg.crop((x0, y0, x0 + CAPA_W, y0 + CAPA_H)).filter(ImageFilter.GaussianBlur(5))
    bg = ImageEnhance.Brightness(bg).enhance(0.55)
    cam = os.path.join(_pasta_capa(p, base), "fundo.jpg")
    bg.save(cam, "JPEG", quality=90)
    return cam


def _moldurada(im, inclinar: float, borda: int = 10):
    """Moldura branca + leve inclinação (o quadro do vídeo / a imagem enviada)."""
    from PIL import Image
    mold = Image.new("RGBA", (im.width + 2 * borda, im.height + 2 * borda), (255, 255, 255, 255))
    mold.paste(im.convert("RGB"), (borda, borda))
    return mold.rotate(inclinar, expand=True, resample=Image.BICUBIC) if inclinar else mold


def capa_pecas(p: Dict[str, Any], base: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """🧩 As peças da capa (em px de 1280×720, de trás pra frente): o quadro do vídeo, a imagem enviada, a seta e os
    personagens — cada uma num PNG próprio (pra arrastar/redimensionar na página) no lugar automático ou no que você
    deixou (cfg["pos"])."""
    from PIL import Image, ImageDraw, ImageOps
    d = _pasta_capa(p, base)
    video = _video_local(p, base)
    quadro = None
    if video:
        q = os.path.join(d, f"_q_{secrets.token_hex(3)}.jpg")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, cfg['t']):.2f}", "-i", video, "-frames:v", "1", q],
                       capture_output=True, timeout=60)
        if os.path.isfile(q):
            quadro = Image.open(q).convert("RGB")
            quadro.load()
            os.remove(q)
    fundo = _capa_fundo(p, base, quadro)
    direita = cfg["lado"] != "esquerda"
    pecas: List[Dict[str, Any]] = []
    caixa_video = None  # (x, y, w, h) de onde o vídeo fica
    if quadro is not None:
        fw = int(CAPA_W * 0.56)
        fh = int(fw * quadro.height / quadro.width)
        if fh > int(CAPA_H * 0.78):
            fh = int(CAPA_H * 0.78)
            fw = int(fh * quadro.width / quadro.height)
        mold = _moldurada(ImageOps.fit(quadro, (fw, fh), Image.LANCZOS), -2.5 if direita else 2.5)
        cam = os.path.join(d, "quadro.png")
        mold.save(cam)
        x = CAPA_W - mold.width - int(CAPA_W * 0.025) if direita else int(CAPA_W * 0.025)
        caixa_video = (x, int(CAPA_H * 0.47) - mold.height // 2, mold.width, mold.height)
        if not cfg["quadro_off"]:
            pecas.append({"chave": "quadro", "nome": "📺 Quadro do vídeo", "arq": cam, "x": caixa_video[0], "y": caixa_video[1],
                          "w": mold.width, "h": mold.height})
    img = cfg.get("imagem")
    cam_img = os.path.join(d, os.path.basename(img)) if img else ""
    if img and os.path.isfile(cam_img):
        im = Image.open(cam_img)
        tem_alfa = im.mode in ("RGBA", "LA", "P") and im.convert("RGBA").getchannel("A").getextrema()[0] < 250
        if tem_alfa:
            im = im.convert("RGBA")
            bb = im.getchannel("A").point(lambda v: 255 if v > 30 else 0).getbbox()
            im = _contorno(im.crop(bb) if bb else im, 6)
        else:
            im = _moldurada(im, 0, 8)
        pronta = os.path.join(d, "imagem_pronta.png")
        im.save(pronta)
        if cfg["quadro_off"] and caixa_video:  # no lugar do vídeo
            k = min(caixa_video[2] / im.width, caixa_video[3] / im.height)
            w, h = int(im.width * k), int(im.height * k)
            x, y = caixa_video[0] + (caixa_video[2] - w) // 2, caixa_video[1] + (caixa_video[3] - h) // 2
        else:
            w = int(CAPA_W * 0.30)
            h = int(w * im.height / im.width)
            if h > CAPA_H * 0.5:
                h = int(CAPA_H * 0.5)
                w = int(h * im.width / im.height)
            x = int(CAPA_W * 0.03) if direita else CAPA_W - w - int(CAPA_W * 0.03)
            y = int(CAPA_H * 0.04)
        pecas.append({"chave": "imagem", "nome": "🖼 Sua imagem", "arq": pronta, "x": x, "y": y, "w": w, "h": h})
    # os personagens: lado a lado, um pouco sobrepostos (sem cobrir o rosto do vizinho), virados pro vídeo
    olhar = "dir" if direita else "esq"
    escolhidos = [c for c in (next((x for x in p["personagens"] if x["id"] == cid), None) for cid in cfg["cids"]) if c]
    figs = []
    for i, c in enumerate(escolhidos):
        ex = cfg["exprs"].get(c["id"]) or ("chocado" if i % 2 == 0 else "empolgado")
        esp, cam = pose_capa(p, c, ex, olhar, base)
        if not cam:
            continue
        im = Image.open(cam).convert("RGBA")
        bb = im.getchannel("A").point(lambda v: 255 if v > 30 else 0).getbbox()
        if bb:
            im = im.crop(bb)
        if esp:
            im = ImageOps.mirror(im)
        im = _contorno(im, 7)
        arq = os.path.join(d, f"p_{c['id']}.png")
        im.save(arq)
        figs.append((c, im.width / im.height, arq))
    n = len(figs)
    if n:
        borda_video = (caixa_video[0] if direita else caixa_video[0] + caixa_video[2]) if caixa_video else (CAPA_W if direita else 0)
        larg_area = (borda_video + int(CAPA_W * 0.05)) if direita else (CAPA_W - borda_video + int(CAPA_W * 0.05))
        larg_area = max(int(CAPA_W * 0.42), larg_area)
        escala = [1.0 if i == 0 else 0.86 for i in range(n)]
        sobrepor = 0.30  # cada um cobre no máximo ~30% do vizinho (o rosto fica livre)
        alt = CAPA_H * 0.98
        while alt > CAPA_H * 0.40:
            larguras = [alt * escala[i] * figs[i][1] for i in range(n)]
            total = sum(larguras) - sobrepor * sum(larguras[1:])
            if total <= larg_area:
                break
            alt *= 0.95
        larguras = [alt * escala[i] * figs[i][1] for i in range(n)]
        # o 1º (maior) fica junto do vídeo; os outros vão se afastando
        pos_x = []
        cursor = (borda_video + int(CAPA_W * 0.05)) if direita else (borda_video - int(CAPA_W * 0.05))
        for i in range(n):
            w = larguras[i]
            prox = larguras[i + 1] if i + 1 < n else w
            if direita:
                x = cursor - w
                cursor = x + min(w, prox) * sobrepor
            else:
                x = cursor
                cursor = x + w - min(w, prox) * sobrepor
            pos_x.append(x)
        for i in reversed(range(n)):  # de trás (o mais longe) pra frente (o 1º)
            c, asp, arq = figs[i]
            h = alt * escala[i]
            w = h * asp
            pecas.append({"chave": f"p:{c['id']}", "nome": c["nome"], "arq": arq, "x": int(max(-w * 0.3, pos_x[i])),
                          "y": int(CAPA_H - h + CAPA_H * 0.03), "w": int(w), "h": int(h)})
    if cfg["seta"] and n and caixa_video and not cfg["quadro_off"]:
        dd = 1 if direita else -1
        sw, sh = 180, 110
        seta = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        dr = ImageDraw.Draw(seta)

        def pts(esc: float) -> List[Tuple[float, float]]:
            cx, cy = sw / 2, sh / 2
            corpo, ponta, larg, abre = 80 * esc, 52 * esc, 16 * esc, 40 * esc
            base_x = cx - (corpo + ponta) / 2
            return [(base_x, cy - larg), (base_x + corpo, cy - larg), (base_x + corpo, cy - abre), (base_x + corpo + ponta, cy),
                    (base_x + corpo, cy + abre), (base_x + corpo, cy + larg), (base_x, cy + larg)]
        dr.polygon(pts(1.2), fill=(255, 255, 255, 255))
        dr.polygon(pts(1.0), fill=(229, 29, 46, 255))
        if dd < 0:
            seta = ImageOps.mirror(seta)
        arq = os.path.join(d, "seta.png")
        seta.save(arq)
        bx = caixa_video[0] if direita else caixa_video[0] + caixa_video[2]
        pecas.append({"chave": "seta", "nome": "➜ Seta", "arq": arq, "x": int(bx - (sw + 10 if direita else -10)),
                      "y": int(CAPA_H * 0.18), "w": sw, "h": sh})
    # o que você mexeu
    for pc in pecas:
        o = cfg["pos"].get(pc["chave"])
        if o:
            if o.get("w"):
                k = max(20.0, min(3000.0, float(o["w"]))) / pc["w"]
                pc["w"], pc["h"] = int(pc["w"] * k), int(pc["h"] * k)
            for kk in ("x", "y"):
                if o.get(kk) is not None:
                    pc[kk] = int(max(-2000, min(3000, float(o[kk]))))
            pc["ajustada"] = True
        o = o or {}
        pc["rot"] = round(max(-180.0, min(180.0, float(o.get("rot") or 0))), 1)  # ⟳ v84_244: girar
        pc["esp"] = bool(o.get("esp"))  # ↔ espelhar
    padrao = [pc["chave"] for pc in pecas]
    ordem = [k for k in cfg["ordem"] if k in padrao] + [k for k in padrao if k not in cfg["ordem"]]
    pecas.sort(key=lambda pc: ordem.index(pc["chave"]))
    for pc in pecas:
        pc["oculta"] = pc["chave"] in cfg["ocultas"]
    return {"fundo": fundo, "pecas": pecas, "tem_video": quadro is not None}


def compor_capa_react(p: Dict[str, Any], base: str, cfg: Dict[str, Any], destino: str) -> str:
    """🧩 A capa 1280×720 com as peças no lugar (de trás pra frente)."""
    from PIL import Image
    pc = capa_pecas(p, base, cfg)
    bg = Image.open(pc["fundo"]).convert("RGBA")
    for x in pc["pecas"]:
        if x["oculta"]:
            continue
        from PIL import ImageOps
        im = Image.open(x["arq"]).convert("RGBA").resize((max(1, x["w"]), max(1, x["h"])), Image.LANCZOS)
        px, py = x["x"], x["y"]
        if x.get("esp"):
            im = ImageOps.mirror(im)
        if x.get("rot"):  # gira em volta do centro (como na página: graus no sentido do relógio)
            cx, cy = px + im.width / 2, py + im.height / 2
            im = im.rotate(-float(x["rot"]), expand=True, resample=Image.BICUBIC)
            px, py = int(round(cx - im.width / 2)), int(round(cy - im.height / 2))
        _colar_cortando(bg, im, px, py)
    bg.convert("RGB").save(destino, "JPEG", quality=92)
    return destino


def guardar_imagem_capa(p: Dict[str, Any], nome: str, dados: bytes, base: str = _BASE) -> str:
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(dados))
        im.load()
    except Exception:  # noqa: BLE001
        raise ReactErro("Não consegui abrir essa imagem.")
    arq = f"enviada_{secrets.token_hex(3)}.png"
    im.convert("RGBA").save(os.path.join(_pasta_capa(p, base), arq))
    return arq


def prompt_capa_react(p: Dict[str, Any], cids: List[str], exprs: Dict[str, str], lado_video: str, pedido: str = "") -> str:
    est = estilo_final(p)
    quem = []
    for cid in cids:
        c = next((x for x in p["personagens"] if x["id"] == cid), None)
        if c:
            quem.append(f"{c['nome']}" + (f" ({c['aparencia_en']})" if c.get("aparencia_en") else "")
                        + f" — {EXPR_EN_CAPA.get(exprs.get(cid) or 'chocado', 'shocked')}, exaggerated")
    lado_p = "left" if lado_video != "esquerda" else "right"
    lado_v = "right" if lado_video != "esquerda" else "left"
    return (("YouTube REACTION video thumbnail, 16:9. The reference image is a rough LAYOUT DRAFT: keep the same composition — "
             f"the characters big on the {lado_p} side, reacting to the video, and the screenshot of the video in a white frame "
             f"on the {lado_v} side (keep the screenshot content recognizable). Characters: " + "; ".join(quem) + ". "
             "Each character must look exactly like in the draft (same face, hair, outfit). Redraw everything polished: "
             "dramatic rim light, vivid saturated colors, high contrast, thick white outline around the characters, "
             "expressive faces readable at small size; no text, no letters, no logos. "
             + ESTILO_TXT[est] + "." + (f" Extra: {pedido}." if pedido else ""))[:3900])


def capa_react(pid: str, base: str, dados: Dict[str, Any]) -> Dict[str, Any]:
    """🖼 Cria a capa do react nas 📣 Publicações: 'montar' (aqui, na hora) ou 'flow' (o rascunho vai de referência)."""
    import publicacao as PB
    with _TRAVA:
        p = carregar(pid, base)
        cfg = capa_cfg(p, dados)
        p["capa"] = cfg
        salvar(p, base)
    cids, exprs, t, lado = cfg["cids"], cfg["exprs"], cfg["t"], cfg["lado"]
    if not cids and not cfg.get("imagem"):
        raise ReactErro("Escolha pelo menos um personagem pra capa.")
    pd = sincronizar_publicacao(p, base)
    d_capas = os.path.join(pd, "capas")
    os.makedirs(d_capas, exist_ok=True)
    rascunho = compor_capa_react(p, base, cfg, os.path.join(d_capas, f"react_{secrets.token_hex(4)}.jpg"))
    ctx = PB.carregar_ctx(pd).get("ctx") or {}
    estilo = PB.limpar_estilo(dict(dados.get("estilo") or {}, pos=(dados.get("estilo") or {}).get("pos") or "topo"))
    nomes = ", ".join(x["nome"] for x in p["personagens"] if x["id"] in cids)
    with PB._TRAVA:
        d = PB.carregar(pd)
        c = PB._nova_capa(d, ideia=f"🎭 react: {nomes} reagindo ao vídeo ({mmss(t)})", texto=str(dados.get("texto") or "")[:120],
                          prompt="", personalizada=True, fundo=rascunho, estilo=estilo, react=True)
        n = c["n"]
        PB.salvar(pd, d)
    if dados.get("modo") == "flow":
        import flow_lote
        item = {"prompt": prompt_capa_react(p, cids, exprs, lado, str(dados.get("pedido") or "")), "tipo": "imagem",
                "origem": "publicacao", "referencia_arquivo": rascunho}
        lote = flow_lote.lote()
        try:
            j = lote.adicionar([item], proporcao="16:9", quantidade="x1")[0]
        except ValueError as exc:
            raise ReactErro(str(exc))
        with PB._TRAVA:
            d = PB.carregar(pd)
            c = next(x for x in d["capas"] if int(x["n"]) == n)
            c.update(status="fila", flow_job=j["id"], erro="", prompt=item["prompt"], prompt_usado=item["prompt"])
            PB.salvar(pd, d)
        aviso = ""
        try:
            lote.iniciar()
        except Exception as exc:  # noqa: BLE001
            aviso = f"o Flow em massa não ligou agora ({str(exc)[:160]}) — ▶ Continuar na aba Flow"
        return {"n": n, "aviso": aviso}
    PB.montar_sem_ia(pd, ctx, n)
    return {"n": n, "aviso": ""}
