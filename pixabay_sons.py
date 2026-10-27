"""🔊 Efeitos sonoros do Pixabay (pixabay.com/pt/sound-effects) — FASE DE TESTE.

Só as partes "puras" (sem navegador), pra dar pra testar sem internet:
  - a URL da busca (página 2, 3… = ?pagi=N);
  - ler os resultados do HTML da página (título, link, id, autor, tema, tags, curtidas, capa, a forma de onda);
  - a forma de onda do Pixabay (o SVG de cada linha) → ONDE está o som (começo, pico, fim);
  - achar os links .mp3 no JSON da página (window.__BOOTSTRAP_URL__), quando ele vier com eles;
  - depois de baixar: medir o som de verdade (ffmpeg), cortar o silêncio das pontas, o espectrograma e a ficha da IA.

O navegador (abrir a busca, clicar no ▶ e pegar o .mp3 que ele pede) fica no `pixabay_sons_teste.py`.
Os itens saem no mesmo formato da base de sons do editor (assets/sons/sons.json: dur, inicio_som, pico, fim_som,
nivel_db), pra no próximo passo entrarem na base.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import subprocess
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urljoin

BASE_URL = "https://pixabay.com"
LARGURA_ONDA = 370  # o viewBox da forma de onda do Pixabay: "0 0 370 32" (meio = 15/16)
MP3_RE = re.compile(r"https?://cdn\.pixabay\.com/(?:download/)?audio/[^\s\"'<>\\]+?\.mp3", re.I)


# ------------------------------------------------------------------ busca
def url_busca(termo: str, pagina: int = 1, idioma: str = "pt") -> str:
    """https://pixabay.com/pt/sound-effects/search/whoosh%20tall/  (página 2: ...?pagi=2)."""
    termo = " ".join(str(termo or "").split())
    u = f"{BASE_URL}/{idioma}/sound-effects/search/{quote(termo, safe='')}/"
    return u + (f"?pagi={int(pagina)}" if int(pagina) > 1 else "")


def id_do_link(href: str) -> Optional[str]:
    """/pt/sound-effects/filme-e-efeitos-especiais-swoosh-1-376872/ → '376872'."""
    m = re.search(r"-(\d{3,})/?(?:[?#].*)?$", str(href or ""))
    return m.group(1) if m else None


def slug(texto: str, limite: int = 50) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "_", t).strip("_").lower()
    return t[:limite] or "som"


# ------------------------------------------------------------------ resultados da página
def _classe(nome: str) -> str:
    """As classes do Pixabay têm um sufixo que muda a cada versão do site (audioRow--et3ac): casa só o começo."""
    return r'class="(?:[^"]*\s)?' + re.escape(nome) + r'--[A-Za-z0-9_-]+'


def _texto(s: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def ler_resultados(pagina_html: str) -> List[Dict[str, Any]]:
    """Cada linha de som da página de busca, na ordem da tela."""
    s = pagina_html or ""
    inicios = [m.start() for m in re.finditer(_classe("audioRow"), s)]
    out: List[Dict[str, Any]] = []
    for k, ini in enumerate(inicios):
        if k + 1 < len(inicios):
            fim = inicios[k + 1]
        else:  # a última linha: do tamanho das outras (depois dela vem o player de baixo, com OUTRA forma de onda)
            tam = max([b - a for a, b in zip(inicios, inicios[1:])] or [8000])
            fim = ini + int(tam * 1.05)
        bloco = s[ini:fim]
        tit = re.search(r'<a href="([^"]+)" ' + _classe("title")[0:] + r'[^"]*">(.*?)</a>', bloco, re.S)
        if not tit:
            continue
        href = _html.unescape(tit.group(1))
        sid = id_do_link(href)
        aut = re.search(r'<a href="([^"]+)" ' + _classe("name") + r'[^"]*">(.*?)</a>', bloco, re.S)
        tema = re.search(r'<a href="[^"]+" ' + _classe("theme") + r'[^"]*">(.*?)</a>', bloco, re.S)
        tags_blk = re.search(_classe("tags") + r'[^"]*"[^>]*>(.*?)</div>', bloco, re.S)
        tags = [_texto(t) for t in re.findall(r"<a [^>]*>(.*?)</a>", tags_blk.group(1), re.S)] if tags_blk else []
        capa = re.search(r'<img [^>]*src="(https://cdn\.pixabay\.com/[^"]+)"', bloco)
        curt = re.search(r'counter="(\d+)"', bloco)
        dur = re.search(_classe("duration") + r'[^"]*"[^>]*>([^<]*)<', bloco)
        onda = re.search(r'<clipPath[^>]*>\s*<path d="([^"]+)"', bloco)
        mp3 = MP3_RE.search(bloco)
        env = envelope_da_onda(onda.group(1)) if onda else []
        out.append({
            "id": sid, "titulo": _texto(tit.group(2)), "pagina": urljoin(BASE_URL, href),
            "autor": _texto(aut.group(2)) if aut else "", "autor_url": urljoin(BASE_URL, _html.unescape(aut.group(1))) if aut else "",
            "tema": _texto(tema.group(1)) if tema else "", "tags": [t for t in tags if t],
            "capa": capa.group(1) if capa else "", "curtidas": int(curt.group(1)) if curt else 0,
            "duracao_txt": _texto(dur.group(1)) if dur else "",
            "onda": env, "onde": onde_esta_o_som(env) if env else None,
            "mp3": mp3.group(0) if mp3 else "",
        })
    return out


def mp3s_soltos(pagina_html: str) -> List[str]:
    """Os .mp3 que já aparecem na página (as <audio> que o site cria quando toca)."""
    vistos: List[str] = []
    for u in MP3_RE.findall(pagina_html or ""):
        u = _html.unescape(u)
        if u not in vistos:
            vistos.append(u)
    return vistos


def mp3_por_id(dados: Any, ids: Iterable[str]) -> Dict[str, str]:
    """Procura no JSON da página (bootstrap) os objetos de cada id com um link .mp3 dentro. Não depende do formato
    exato (ele muda): anda pela árvore toda."""
    alvo = {str(i) for i in ids if i}
    achados: Dict[str, str] = {}

    def mp3_dentro(o: Any, fundo: int = 0) -> Optional[str]:
        if fundo > 4:
            return None
        if isinstance(o, str):
            m = MP3_RE.search(o)
            return m.group(0) if m else None
        if isinstance(o, dict):
            for v in o.values():
                r = mp3_dentro(v, fundo + 1)
                if r:
                    return r
        if isinstance(o, list):
            for v in o[:20]:
                r = mp3_dentro(v, fundo + 1)
                if r:
                    return r
        return None

    def andar(o: Any) -> None:
        if isinstance(o, dict):
            i = str(o.get("id", ""))
            if i in alvo and i not in achados:
                r = mp3_dentro(o)
                if r:
                    achados[i] = r
            for v in o.values():
                andar(v)
        elif isinstance(o, list):
            for v in o:
                andar(v)
    andar(dados)
    return achados


# ------------------------------------------------------------------ forma de onda do Pixabay → onde está o som
def envelope_da_onda(d: str, largura: int = LARGURA_ONDA) -> List[float]:
    """O <path> da forma de onda (viewBox 370×32, o meio em 15/16) → a força do som (0..1) em cada coluna.
    O contorno vai da esquerda pra direita por CIMA (y < 15 = som) e volta por baixo."""
    nums = re.findall(r"[ML]\s*(-?[\d.]+)[ ,]+(-?[\d.]+)", d or "")
    pts = [(float(x), float(y)) for x, y in nums]
    if not pts:
        return []
    topo: List[Tuple[float, float]] = []
    for k, (x, y) in enumerate(pts):
        if k and x < pts[k - 1][0]:
            break  # começou a volta (por baixo)
        topo.append((x, y))
    env = [0.0] * largura
    for (x0, y0), (x1, y1) in zip(topo, topo[1:]):
        a, b = int(round(x0)), int(round(x1))
        for x in range(max(0, a), min(largura, b + 1)):
            t = 0.0 if b == a else (x - a) / (b - a)
            y = y0 + (y1 - y0) * t
            env[x] = max(env[x], max(0.0, min(1.0, (15.0 - y) / 15.0)))
    return [round(v, 3) for v in env]


def onde_esta_o_som(env: List[float], limiar: float = 0.07) -> Optional[Dict[str, float]]:
    """Começo, pico e fim do som (em fração da duração, 0..1) — multiplique pela duração pra ter os segundos."""
    if not env or max(env) <= 0:
        return None
    lim = max(limiar, max(env) * 0.06)
    com = [i for i, v in enumerate(env) if v >= lim]
    if not com:
        return None
    n = len(env) - 1 or 1
    pico = max(range(len(env)), key=lambda i: env[i])
    return {"inicio": round(com[0] / n, 4), "pico": round(pico / n, 4), "fim": round(min(1.0, (com[-1] + 1) / n), 4),
            "forca": round(sum(env[com[0]: com[-1] + 1]) / max(1, com[-1] + 1 - com[0]), 3)}


# ------------------------------------------------------------------ depois de baixar: medir, cortar, espectrograma
def _pcm(caminho: str, taxa: int = 22050):
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", caminho, "-ac", "1", "-ar", str(taxa), "-f", "s16le", "-"],
                       capture_output=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg não leu o áudio: {r.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768.0


def medir(caminho: str, limiar_db: float = -40.0) -> Dict[str, float]:
    """No áudio de verdade: duração, onde o som começa/acaba (acima de limiar_db do pico), o pico e o nível."""
    import numpy as np
    taxa = 22050
    a = _pcm(caminho, taxa)
    dur = len(a) / taxa
    if not len(a):
        return {"dur": 0.0, "inicio_som": 0.0, "pico": 0.0, "fim_som": 0.0, "nivel_db": -99.0}
    jan = int(taxa * 0.01)
    n = max(1, len(a) // jan)
    rms = np.sqrt(np.mean(a[: n * jan].reshape(n, jan) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    topo = float(db.max())
    acima = np.nonzero(db >= topo + limiar_db)[0]
    ini, fim = (acima[0], acima[-1] + 1) if len(acima) else (0, n)
    return {"dur": round(dur, 3), "inicio_som": round(ini * 0.01, 3), "pico": round(float(np.argmax(rms)) * 0.01, 3),
            "fim_som": round(min(dur, fim * 0.01), 3), "nivel_db": round(topo, 1)}


def cortar_silencio(entrada: str, saida: str, folga_ini: float = 0.03, folga_fim: float = 0.12,
                    limiar_db: float = -40.0) -> Dict[str, Any]:
    """Tira o silêncio das pontas (com uma folguinha e um fade curto no fim) e devolve a ficha do arquivo cortado
    (dur, inicio_som, pico, fim_som, nivel_db — como na base de sons)."""
    m = medir(entrada, limiar_db)
    a = max(0.0, m["inicio_som"] - folga_ini)
    b = min(m["dur"], m["fim_som"] + folga_fim)
    if b - a < 0.05:
        a, b = 0.0, m["dur"]
    fade = min(0.08, max(0.01, (b - a) * 0.1))
    ext = os.path.splitext(saida)[1].lower()
    cod = ["-c:a", "aac", "-b:a", "192k"] if ext in (".m4a", ".aac", ".mp4") else ["-c:a", "pcm_s16le"] if ext == ".wav" else ["-c:a", "libmp3lame", "-q:a", "2"]
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", entrada,
                        "-af", f"afade=t=out:st={max(0.0, b - a - fade):.3f}:d={fade:.3f}"] + cod + [saida],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg não cortou: {r.stderr[-300:]}")
    f = medir(saida, limiar_db)
    f.update(corte_de=round(a, 3), corte_ate=round(b, 3), dur_original=m["dur"])
    return f


def espectrograma(entrada: str, png: str) -> str:
    """A "foto" do som (frequência × tempo) — é o que a IA olha pra descrever (ela não escuta)."""
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", entrada, "-lavfi",
                        "showspectrumpic=s=640x240:legend=1:color=intensity:scale=log", png],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not os.path.isfile(png):
        raise RuntimeError(f"espectrograma falhou: {r.stderr[-300:]}")
    return png


# ------------------------------------------------------------------ ficha da IA
CATEGORIAS = ["transicoes", "passagem", "cinema", "impacto", "pop", "foley", "digital", "fogo", "vento", "respiro", "variados"]

FICHA_SCHEMA = {
    "type": "object",
    "properties": {
        "nome": {"type": "string"},
        "descricao": {"type": "string"},
        "categoria": {"type": "string", "enum": CATEGORIAS},
        "usos": {"type": "array", "items": {"type": "string"}},
        "intensidade": {"type": "string", "enum": ["suave", "media", "forte"]},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["nome", "descricao", "categoria", "usos", "intensidade", "tags"],
    "additionalProperties": False,
}

FICHA_SYS = ("Você cataloga efeitos sonoros pra um editor de vídeo (YouTube, narração, anime, react). Você NÃO ouve o som: "
             "recebe o título, as tags do Pixabay, as medidas (duração, onde começa, o pico, onde acaba, o nível) e o "
             "ESPECTROGRAMA (tempo na horizontal, frequência na vertical, mais claro = mais forte). Descreva em português, "
             "curto e concreto: como o som é (sobe/desce, grave/agudo, seco/com cauda, rápido/longo) e onde ele cai bem num "
             "vídeo. 'nome' = 2 a 4 palavras. 'usos' = 2 a 4 situações (ex.: 'transição rápida entre cenas', 'entrada de "
             "texto', 'golpe em luta'). 'tags' = 3 a 8 palavras em português.")


def ficha_ia(meta: Dict[str, Any], png: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """A descrição da IA (None se a IA estiver desligada / sem crédito)."""
    import ia_servico
    info = {k: meta.get(k) for k in ("titulo", "tema", "tags", "dur", "inicio_som", "pico", "fim_som", "nivel_db")}
    conteudo: List[Dict[str, Any]] = [{"type": "text", "text": json.dumps(info, ensure_ascii=False)}]
    if png and os.path.isfile(png):
        bloco = ia_servico.imagem_bloco(png, largura=640)
        if bloco:
            conteudo.insert(0, bloco)
    return ia_servico.chamar("sons_pixabay", FICHA_SYS, conteudo, schema=FICHA_SCHEMA, max_tokens=500)


def item_da_base(meta: Dict[str, Any], arquivo_rel: str) -> Dict[str, Any]:
    """No formato de assets/sons/sons.json (pra próxima fase: entrar na base de sons do editor)."""
    f = meta.get("ficha") or {}
    cat = f.get("categoria") if f.get("categoria") in CATEGORIAS else "variados"
    return {"id": f"pixabay/{meta['id']}", "categoria": cat, "nome": f.get("nome") or meta.get("titulo") or meta["id"],
            "arquivo": arquivo_rel, **{k: meta.get(k) for k in ("dur", "inicio_som", "pico", "fim_som", "nivel_db")},
            "descricao": f.get("descricao", ""), "usos": f.get("usos", []), "tags": f.get("tags") or meta.get("tags", []),
            "fonte": {"site": "pixabay", "pagina": meta.get("pagina"), "autor": meta.get("autor"), "mp3": meta.get("mp3")}}
