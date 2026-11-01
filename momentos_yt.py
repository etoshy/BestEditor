"""momentos_yt.py — 🔥 Momentos mais vistos → curtos (v84_291).

Cola o link de um vídeo LONGO do YouTube e o site acha os trechos que o público mais assiste e transforma cada um num curto:

  1. 📈 GRÁFICO "MAIS REPETIDOS" (a onda branca em cima da barra vermelha do player). Vem de 3 jeitos, nessa ordem:
       • yt-dlp (campo "heatmap" — o mesmo gráfico, sem abrir nada);
       • o navegador do site abre o vídeo, passa o mouse na barra e LÊ o desenho do gráfico (o caminho do SVG) já
         convertido pro tempo do vídeo;
       • você cola o HTML do gráfico (botão direito na onda → Inspecionar → copiar o <svg>/<path>).
     Sem gráfico (vídeo novo/pouco visto)? o Claude escolhe pela transcrição.
  2. 📝 TRANSCRIÇÃO: a que você colou (YouTube → "Mostrar transcrição" → copiar), ou a legenda do YouTube (yt-dlp), ou o
     Whisper só nos trechos candidatos (não precisa transcrever 1 h de vídeo).
  3. 🔥 CANDIDATOS: os picos do gráfico viram janelas (começa um pouco antes do pico — a preparação — e termina depois da
     virada), encaixadas no começo/fim das frases. Comentários que citam o tempo ("2:40 😂") contam também.
  4. 🤖 CLAUDE ESCOLHE os N melhores cortes: ajusta o começo/fim pra história fechar, dá um título, diz o que manter no
     CENTRO do vertical (ex.: "red humanoid robot") e se o curto rende mais 💬 comentando ou 🔍 explicando.
  5. ✂ CORTE VERTICAL 9:16 seguindo o alvo: o 👁 Moondream2 acha o alvo em vários quadros (detect) e o recorte anda junto
     (suave dentro do plano, pula no corte de cena). Ou "fundo desfocado" (o vídeo inteiro no meio).
  6. 👁 MOONDREAM2 descreve o trecho quadro a quadro (o que acontece, quem, objetos, texto na tela) → linha do tempo.
  7. 💬 Vira um curto de COMENTÁRIO (o mesmo do 🔗 Link → vídeo pronto): o Claude escreve gancho + roteiro + final com
     pergunta (5 de cada pra trocar), voz, edição, destaques e o MP4 — ou para no editor, ou só entrega o corte.

Moondream2: "hf" (transformers, vikhyatk/moondream2 — faz caption E detect), "ollama" (moondream — só descreve; o alvo
o Claude acha) ou "nenhum" (o Claude olha os quadros). Configuração na página.

Pasta: <BASE>/momentos_yt/<id>/  (projeto.json, video.*, cortes/)
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import arquivo_seguro

TAREFAS: Dict[str, Dict[str, Any]] = {}
_TRAVA = threading.RLock()
Prog = Callable[[str], None]


class MomentoErro(Exception):
    pass


MODOS = {"auto": "🤖 a IA escolhe por corte", "comentario": "💬 comentar", "explicar": "🔍 explicar o que acontece"}
ENQUADRAR = {"seguir": "🎯 vertical seguindo o alvo", "desfocado": "🌫 vertical com fundo desfocado", "original": "▭ manter o formato original"}
FORMATOS = {"separados": "🎬 um short pra cada momento", "compilacao": "🎞 um short só com os melhores momentos (narrado)"}
ATE = {"revisar": "👀 parar pra eu revisar os cortes", "cortes": "✂ só cortar (sem roteiro)",
       "editor": "📝 roteiro + voz → editor", "exportar": "🎬 até o MP4 pronto"}
CONFIG_PADRAO = {"n_cortes": 3, "dur_min": 20, "dur_max": 60, "modo": "auto", "enquadrar": "seguir", "ate": "revisar",
                 "lingua_post": "en", "idioma": "en", "voz": "", "qualidade": "1080p", "alvo": "", "extra": "",
                 "transcricao_colada": "", "heatmap_colado": "", "usar_navegador": True, "formato": "separados", "assunto": "",
                 "referencia": "", "referencia_link": "", "duracao_short": 0, "arroba": "",
                 "legenda_estilo": "", "legenda_tamanho": 0.05, "legenda_posicao": "terco", "legenda_maiusculas": True,
                 "legenda_altura": None, "legenda_margem": 0.10}


# ---------------------------------------------------------------------------------------------------- projeto
def raiz(base: str) -> str:
    return os.environ.get("MOMENTOS_YT_DIR") or os.path.join(base, "momentos_yt")


def pasta(base: str, pid: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{10}", pid or ""):
        raise MomentoErro("id inválido")
    return os.path.join(raiz(base), pid)


def carregar(base: str, pid: str) -> Dict[str, Any]:
    cam = os.path.join(pasta(base, pid), "projeto.json")
    if not os.path.isfile(cam):
        raise MomentoErro("não existe")
    with open(cam, encoding="utf-8") as f:
        return json.load(f)


def salvar(base: str, p: Dict[str, Any]) -> None:
    p["mudou"] = time.time()
    arquivo_seguro.gravar_json(os.path.join(pasta(base, p["id"]), "projeto.json"), p)


def mudar(base: str, pid: str, fn: Callable[[Dict[str, Any]], Any]) -> Dict[str, Any]:
    with _TRAVA:
        p = carregar(base, pid)
        fn(p)
        salvar(base, p)
        return p


def id_youtube(link: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([\w-]{11})", link or "")
    return m.group(1) if m else ""


def novo(base: str, link: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    vid = id_youtube(link)
    if not vid:
        raise MomentoErro("Cole o link de um vídeo do YouTube.")
    pid = uuid.uuid4().hex[:10]
    os.makedirs(os.path.join(pasta(base, pid), "cortes"), exist_ok=True)
    cfg = dict(CONFIG_PADRAO)
    cfg.update({k: v for k, v in (config or {}).items() if k in CONFIG_PADRAO})
    p = {"id": pid, "link": f"https://www.youtube.com/watch?v={vid}", "yt_id": vid, "titulo": "", "criado": time.time(),
         "config": cfg, "dur": 0, "heatmap": [], "heat_fonte": "", "legenda": [], "legenda_fonte": "", "capitulos": [],
         "info": {}, "candidatos": [], "cortes": [], "video": "", "etapa": "na fila", "erro": ""}
    salvar(base, p)
    return p


def listar(base: str) -> List[Dict[str, Any]]:
    r = raiz(base)
    out = []
    for pid in os.listdir(r) if os.path.isdir(r) else []:
        try:
            p = carregar(base, pid)
        except Exception:  # noqa: BLE001
            continue
        out.append({"id": pid, "titulo": p.get("titulo") or p.get("link"), "criado": p.get("criado") or 0, "etapa": p.get("etapa") or "",
                    "cortes": len(p.get("cortes") or []), "yt_id": p.get("yt_id") or "",
                    "rodando": bool(TAREFAS.get(pid)) and not TAREFAS[pid].get("fim")})
    return sorted(out, key=lambda x: -x["criado"])


def mmss(t: float) -> str:
    t = int(round(float(t or 0)))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def ler_tempo(s: str) -> Optional[float]:
    s = str(s or "").strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?::\d{1,2}(?:\.\d+)?){0,2}|\d+\.\d+", s):
        return None
    v = 0.0
    for parte in s.split(":"):
        v = v * 60 + float(parte)
    return v


# ---------------------------------------------------------------------------------------------------- 1. info (yt-dlp)
def _ytdlp():
    import yt_dlp  # noqa: F401
    return yt_dlp


def info_ytdlp(link: str, comentarios: int = 120, ytdlp_module: Any = None, prog: Prog = lambda m: None) -> Dict[str, Any]:
    """Título, duração, capítulos, o gráfico 'mais repetidos' (heatmap), as legendas disponíveis e os comentários do topo."""
    mod = ytdlp_module or _ytdlp()

    def pegar(extra: Dict[str, Any], com: bool) -> Dict[str, Any]:
        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, **extra}
        if com:
            opts.update(getcomments=True, extractor_args={"youtube": {"max_comments": [str(comentarios), "all", "0", "0"],
                                                                      "comment_sort": ["top"]}})
        with mod.YoutubeDL(opts) as y:
            return y.extract_info(link, download=False) or {}

    def acao(extra: Dict[str, Any]) -> Dict[str, Any]:
        if comentarios:
            try:
                return pegar(extra, True)
            except Exception as exc:  # noqa: BLE001  (comentário travou/falhou: pega o resto sem eles)
                if "bot" in str(exc).lower() or "sign in" in str(exc).lower():
                    raise
                prog("💬 os comentários não vieram — seguindo sem eles")
        return pegar(extra, False)
    try:
        import yt_cookies
        j = yt_cookies.tentar(acao, prog) if ytdlp_module is None else acao({})
    except ImportError:
        j = acao({})
    return j or {}


def heatmap_do_info(j: Dict[str, Any]) -> List[List[float]]:
    out = []
    for h in j.get("heatmap") or []:
        try:
            out.append([round(float(h["start_time"]), 2), round(float(h["end_time"]), 2), round(float(h["value"]), 4)])
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out)


_TEMPO_RX = re.compile(r"(?<![\d:])(\d{1,2}:\d{2}(?::\d{2})?)(?![\d:])")


def comentarios_com_tempo(j: Dict[str, Any], dur: float) -> List[Dict[str, Any]]:
    """Comentários que citam um momento ("2:40 o robô 😂") — sinal forte de trecho que rende."""
    out = []
    for c in j.get("comments") or []:
        if not isinstance(c, dict) or c.get("parent") not in (None, "root"):
            continue
        txt = " ".join(str(c.get("text") or "").split())
        for m in _TEMPO_RX.finditer(txt):
            t = ler_tempo(m.group(1))
            if t is not None and 0 < t < (dur or 1e9):
                out.append({"t": t, "texto": txt[:300], "curtidas": int(c.get("like_count") or 0)})
    return sorted(out, key=lambda x: -x["curtidas"])[:80]


def comentarios_topo(j: Dict[str, Any], n: int = 40) -> List[Dict[str, Any]]:
    import curtos_link as CL
    return CL.ler_info_ytdlp(j, n).get("comentarios") or []


# ---------------------------------------------------------------------------------------------------- 1b. heatmap: colado / navegador
def _pares(d: str) -> List[Tuple[float, float]]:
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", d or "")]
    return list(zip(nums[0::2], nums[1::2]))


def heatmap_de_pontos(pts: List[Tuple[float, float]], dur: float, bins: int = 100) -> List[List[float]]:
    """Pontos (fração do tempo 0..1, valor 0..1) → 100 faixas [t0, t1, valor] (o maior valor de cada faixa, normalizado)."""
    if not pts or dur <= 0:
        return []
    caixa = [None] * bins
    for x, v in pts:
        if not (-0.01 <= x <= 1.01):
            continue
        i = min(bins - 1, max(0, int(x * bins)))
        caixa[i] = v if caixa[i] is None else max(caixa[i], v)
    for i in range(bins):  # buraco (faixa sem ponto) → o vizinho
        if caixa[i] is None:
            viz = [caixa[k] for k in (i - 1, i + 1) if 0 <= k < bins and caixa[k] is not None]
            caixa[i] = sum(viz) / len(viz) if viz else 0.0
    top = max(caixa) or 1.0
    passo = dur / bins
    return [[round(i * passo, 2), round((i + 1) * passo, 2), round(max(0.0, caixa[i]) / top, 4)] for i in range(bins)]


def heatmap_colado(texto: str, dur: float) -> List[List[float]]:
    """O HTML/caminho do gráfico que você copiou do YouTube (Inspecionar → <svg …> ou o atributo d do <path>).
    O desenho do YouTube usa viewBox 0 0 1000 100 (x = tempo, y = 100 - engajamento)."""
    t = str(texto or "")
    vb = re.search(r'viewBox="\s*([-\d.]+)[\s,]+([-\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)', t)
    x0, y0, W, H = (float(vb.group(i)) for i in range(1, 5)) if vb else (0.0, 0.0, 1000.0, 100.0)
    ds = re.findall(r'\sd="([^"]+)"', t) or ([t] if re.search(r"[MC]\s*[-\d]", t) else [])
    pts: List[Tuple[float, float]] = []
    for d in ds:
        for x, y in _pares(d):
            pts.append(((x - x0) / W, 1 - (y - y0) / H))
    return heatmap_de_pontos(pts, dur)


_JS_HEAT = r"""() => {
  const bar = document.querySelector('.ytp-progress-bar'); const v = document.querySelector('video.html5-main-video, video');
  if (!bar) return {erro: 'sem barra'};
  const r = bar.getBoundingClientRect();
  const paths = [...document.querySelectorAll('[class*="heat-map"] path, path[class*="heat-map"]')];
  const pts = [];
  for (const p of paths) {
    let len = 0; try { len = p.getTotalLength(); } catch (e) {}
    const svg = p.ownerSVGElement; if (!len || !svg) continue;
    const sr = svg.getBoundingClientRect(); const m = p.getScreenCTM(); if (!m || !sr.height || !r.width) continue;
    for (let k = 0; k <= 400; k++) { const q = p.getPointAtLength(len * k / 400); const s = new DOMPoint(q.x, q.y).matrixTransform(m);
      pts.push([(s.x - r.left) / r.width, 1 - (s.y - sr.top) / sr.height]); }
  }
  return {dur: v ? v.duration : 0, pts, n: paths.length};
}"""


def heatmap_pelo_navegador(base: str, link: str, dur: float, prog: Prog = lambda m: None) -> List[List[float]]:
    """Abre o vídeo num navegador de verdade, passa o mouse na barra (o gráfico aparece) e lê o desenho do gráfico já no
    tempo do vídeo (funciona com capítulos: cada pedaço do gráfico é medido na tela em relação à barra inteira)."""
    from playwright.sync_api import sync_playwright
    perfil = os.path.join(raiz(base), "_navegador")
    os.makedirs(perfil, exist_ok=True)
    opc = dict(headless=os.environ.get("MOMENTOS_NAVEGADOR_OCULTO", "1") == "1", locale="pt-BR",
               viewport={"width": 1400, "height": 900}, args=["--disable-blink-features=AutomationControlled", "--mute-audio"])
    prog("🌐 abrindo o vídeo no navegador pra ler o gráfico…")
    with sync_playwright() as pw:
        ctx = None
        for canal in ("chrome", "msedge", None):
            try:
                ctx = pw.chromium.launch_persistent_context(perfil, **(dict(opc, channel=canal) if canal else opc))
                break
            except Exception:  # noqa: BLE001
                continue
        if ctx is None:
            raise MomentoErro("não consegui abrir o navegador (python -m playwright install chromium)")
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(link, wait_until="domcontentloaded", timeout=60000)
            for t in ("Aceitar tudo", "Accept all", "Rejeitar tudo", "Reject all"):
                try:
                    bt = page.get_by_role("button", name=re.compile(rf"^{t}$", re.I)).first
                    if bt.count() and bt.is_visible():
                        bt.click(timeout=2000)
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                        break
                except Exception:  # noqa: BLE001
                    pass
            page.wait_for_selector(".ytp-progress-bar", timeout=30000)
            melhor: Dict[str, Any] = {}
            for k in range(40):  # propaganda antes do vídeo: pula/espera; o gráfico só aparece no vídeo de verdade
                try:
                    pular = page.locator(".ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern").first
                    if pular.count() and pular.is_visible():
                        pular.click(timeout=1500)
                    anuncio = page.locator(".ad-showing").count() > 0
                    bar = page.locator(".ytp-progress-bar").first
                    caixa = bar.bounding_box()
                    if caixa and not anuncio:
                        page.mouse.move(caixa["x"] + caixa["width"] * 0.5, caixa["y"] + caixa["height"] / 2)
                        page.wait_for_timeout(700)
                        d = page.evaluate(_JS_HEAT)
                        if d.get("pts"):
                            melhor = d
                            break
                except Exception:  # noqa: BLE001
                    pass
                if k == 2:
                    prog("🌐 esperando o player (propaganda?)…")
                page.wait_for_timeout(1000)
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
    if not melhor.get("pts"):
        return []
    try:
        d_pag = float(melhor.get("dur") or 0)
    except (TypeError, ValueError):
        d_pag = 0.0
    d_final = d_pag if math.isfinite(d_pag) and d_pag > 0 else float(dur or 0)
    return heatmap_de_pontos([(float(x), float(v)) for x, v in melhor["pts"]], d_final)


# ---------------------------------------------------------------------------------------------------- 2. transcrição
def legenda_colada(texto: str) -> List[Dict[str, Any]]:
    """A transcrição que você copiou do YouTube ("0:13" numa linha e a frase na outra, ou "0:13 frase"), SRT ou VTT."""
    linhas = [l.strip() for l in str(texto or "").replace("\r", "").split("\n")]
    if any("-->" in l for l in linhas):  # SRT/VTT: o número de cada legenda não é fala
        linhas = [l for l in linhas if not l.isdigit()]
    out: List[Dict[str, Any]] = []
    t_atual: Optional[float] = None
    fim_srt: Optional[float] = None
    for l in linhas:
        if not l:
            continue
        m = re.match(r"^(\d{1,2}:)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*(\d{1,2}:)?(\d{1,2}):(\d{2})[.,](\d{1,3})", l)
        if m:  # SRT/VTT
            def _t(h, mi, s, ms):
                return int((h or "0:")[:-1]) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000
            t_atual = _t(*m.group(1, 2, 3, 4))
            fim_srt = _t(*m.group(5, 6, 7, 8))
            continue
        m = re.match(r"^(\d{1,2}:\d{2}(?::\d{2})?)\s*(.*)$", l)
        if m and ler_tempo(m.group(1)) is not None:
            t_atual = ler_tempo(m.group(1))
            fim_srt = None
            if m.group(2).strip():
                out.append({"t0": t_atual, "t1": None, "texto": m.group(2).strip()})
                t_atual = None
            continue
        if t_atual is not None:
            if out and out[-1]["t0"] == t_atual:
                out[-1]["texto"] += " " + l
            else:
                out.append({"t0": t_atual, "t1": fim_srt, "texto": l})
        elif out and not re.match(r"^(WEBVTT|Kind:|Language:)", l):
            out[-1]["texto"] += " " + l
    out = [x for x in out if re.sub(r"<[^>]+>", "", x["texto"]).strip()]
    for x in out:
        x["texto"] = re.sub(r"<[^>]+>", "", x["texto"]).strip()[:500]
    out.sort(key=lambda x: x["t0"])
    for i, x in enumerate(out):
        if x["t1"] is None:
            x["t1"] = out[i + 1]["t0"] if i + 1 < len(out) else x["t0"] + 4.0
    return [dict(x, t0=round(x["t0"], 2), t1=round(max(x["t1"], x["t0"] + 0.3), 2)) for x in out]


def legenda_json3(dados: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Legenda json3 do YouTube (manual ou automática) → frases com tempo (junta os pedacinhos da automática)."""
    out: List[Dict[str, Any]] = []
    for ev in dados.get("events") or []:
        segs = ev.get("segs")
        if not segs:
            continue
        txt = "".join(s.get("utf8") or "" for s in segs).replace("\n", " ").strip()
        if not txt:
            continue
        t0 = float(ev.get("tStartMs") or 0) / 1000
        t1 = t0 + float(ev.get("dDurationMs") or 2000) / 1000
        if out and t0 - out[-1]["t1"] < 0.6 and len(out[-1]["texto"]) < 90 and not re.search(r"[.!?。！？]$", out[-1]["texto"]):
            out[-1]["texto"] += ("" if re.search(r"[぀-ヿ一-鿿]$", out[-1]["texto"]) else " ") + txt
            out[-1]["t1"] = round(max(out[-1]["t1"], t1), 2)
        else:
            out.append({"t0": round(t0, 2), "t1": round(t1, 2), "texto": txt})
    for i in range(len(out) - 1):  # a automática sobrepõe as linhas: corta no começo da próxima
        out[i]["t1"] = round(min(out[i]["t1"], max(out[i]["t0"] + 0.3, out[i + 1]["t0"])), 2)
    return out


def escolher_lingua_legenda(j: Dict[str, Any]) -> Tuple[str, bool]:
    """(código, automática?) — a legenda no idioma ORIGINAL do vídeo (a manual se tiver)."""
    lang = (j.get("language") or "").split("-")[0]
    subs, auto = j.get("subtitles") or {}, j.get("automatic_captions") or {}
    for k in ([lang] if lang else []) + [x for x in subs if x != "live_chat"]:
        if k in subs:
            return k, False
    for k in ([f"{lang}-orig", lang] if lang else []) + [x for x in auto if x.endswith("-orig")] + ["en"]:
        if k in auto:
            return k, True
    return "", False


def baixar_legenda(link: str, j: Dict[str, Any], destino: str, ytdlp_module: Any = None) -> List[Dict[str, Any]]:
    lang, _auto = escolher_lingua_legenda(j)
    if not lang:
        return []
    mod = ytdlp_module or _ytdlp()
    os.makedirs(destino, exist_ok=True)

    def acao(extra: Dict[str, Any]) -> None:
        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
                "subtitleslangs": [lang], "subtitlesformat": "json3", "outtmpl": os.path.join(destino, "legenda.%(ext)s"), **extra}
        with mod.YoutubeDL(opts) as y:
            y.download([link])
    try:
        if ytdlp_module is None:
            import yt_cookies
            yt_cookies.tentar(acao)
        else:
            acao({})
    except Exception:  # noqa: BLE001  (sem legenda → Whisper nos trechos)
        return []
    for nome in os.listdir(destino):
        if nome.startswith("legenda") and nome.endswith(".json3"):
            try:
                with open(os.path.join(destino, nome), encoding="utf-8") as f:
                    return legenda_json3(json.load(f))
            except (OSError, ValueError):
                return []
    return []


def trecho_da_legenda(leg: List[Dict[str, Any]], t0: float, t1: float) -> List[Dict[str, Any]]:
    return [x for x in leg if x["t1"] > t0 and x["t0"] < t1]


# ---------------------------------------------------------------------------------------------------- 3. candidatos (picos)
def _suavizar(v: List[float], r: int = 1) -> List[float]:
    return [sum(v[max(0, i - r):i + r + 1]) / len(v[max(0, i - r):i + r + 1]) for i in range(len(v))]


def candidatos(heat: List[List[float]], dur: float, dur_min: float = 20, dur_max: float = 60, n: int = 8,
               leg: Optional[List[Dict[str, Any]]] = None, coment: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Os picos do gráfico → janelas [t0, t1] com começo antes do pico (a preparação) e fim depois (a virada/reação)."""
    if not heat or dur <= 0:
        return []
    v = _suavizar([h[2] for h in heat])
    meio = [(h[0] + h[1]) / 2 for h in heat]
    ordenado = sorted(v)
    base = ordenado[len(v) // 2]  # mediana = o "normal" do vídeo
    picos = []
    for i in range(len(v)):
        if v[i] < base * 1.08 or meio[i] < min(15.0, dur * 0.02) or meio[i] > dur - 3:
            continue  # pula o comecinho (todo mundo vê) e o fim
        if (i == 0 or v[i] >= v[i - 1]) and (i == len(v) - 1 or v[i] >= v[i + 1]):
            picos.append(i)
    # 💬 comentários com tempo dão um bônus no pico mais perto
    bonus = {}
    for c in coment or []:
        i = min(range(len(meio)), key=lambda k: abs(meio[k] - c["t"]))
        bonus[i] = bonus.get(i, 0) + 1 + math.log10(1 + c["curtidas"])
    picos.sort(key=lambda i: -(v[i] + 0.04 * sum(b for k, b in bonus.items() if abs(k - i) <= 2)))
    out: List[Dict[str, Any]] = []
    for i in picos:
        corte = base + (v[i] - base) * 0.45
        a = i
        while a > 0 and v[a - 1] >= corte:
            a -= 1
        z = i
        while z < len(v) - 1 and v[z + 1] >= corte:
            z += 1
        t0, t1 = heat[a][0], heat[z][1]
        tp = meio[i]
        if t1 - t0 < dur_min:  # curto demais: abre em volta do pico (65% antes — a preparação; 35% depois)
            falta = dur_min - (t1 - t0)
            t0, t1 = t0 - falta * 0.65, t1 + falta * 0.35
        if t1 - t0 > dur_max:
            t0, t1 = max(t0, tp - dur_max * 0.6), min(t1, tp + dur_max * 0.4)
        t0, t1 = max(0.0, t0), min(dur, t1)
        if leg:
            t0, t1 = encaixar_nas_frases(leg, t0, t1, dur_max)
        if any(min(t1, o["t1"]) - max(t0, o["t0"]) > 0.3 * min(t1 - t0, o["t1"] - o["t0"]) for o in out):
            continue
        out.append({"t0": round(t0, 2), "t1": round(t1, 2), "pico": round(tp, 2), "valor": round(v[i], 3),
                    "comentarios": [c for c in coment or [] if t0 - 5 <= c["t"] <= t1 + 5][:5]})
        if len(out) >= n:
            break
    return out


def encaixar_nas_frases(leg: List[Dict[str, Any]], t0: float, t1: float, dur_max: float = 90) -> Tuple[float, float]:
    """Não começa nem termina no meio da frase: o começo vai pro início da frase em andamento, o fim pro fim dela."""
    for x in leg:
        if x["t0"] <= t0 < x["t1"] and t0 - x["t0"] <= 6:
            t0 = x["t0"]
            break
    for x in leg:
        if x["t0"] < t1 <= x["t1"] and x["t1"] - t1 <= 6 and x["t1"] - t0 <= dur_max + 8:
            t1 = x["t1"]
            break
    return round(t0, 2), round(t1, 2)


# ---------------------------------------------------------------------------------------------------- 4. Claude escolhe
def _o(props: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


S, N = {"type": "string"}, {"type": "number"}
ESCOLHA_SCHEMA = _o({"cortes": {"type": "array", "items": _o({
    "candidato": N, "inicio": N, "fim": N, "titulo_pt": S, "motivo_pt": S, "alvo_en": S, "alvo_pt": S,
    "acao_en": {"type": "array", "items": S}, "destino_en": {"type": "array", "items": S},
    "modo": {"type": "string", "enum": ["comentario", "explicar"]}, "ideia_gancho_pt": S})}})
ESCOLHA_SYS = (
    "You pick the best moments of a LONG YouTube video to turn into vertical SHORTS (YouTube Shorts / TikTok / Reels). Each short is "
    "a narrated clip: a narrator comments on it or explains it.\n"
    "You get the video info, the CANDIDATES (windows around the peaks of YouTube's 'Most replayed' graph — 'heat' 0..1, higher = "
    "more people re-watched it — and comments that cite those timestamps) with the TRANSCRIPT around each one.\n"
    "Rules:\n"
    "1. Pick the requested number of clips, best first. Prefer high heat, but a lower-heat candidate with a clear, self-contained "
    "moment (setup → payoff, a surprise, a skill, a funny reaction, a reveal) beats a high-heat one that needs the rest of the video.\n"
    "2. 'inicio'/'fim' in SECONDS of the long video: start at the setup (never mid-sentence), end right after the payoff/reaction; "
    "stay inside the requested length. You may move the window a little outside the candidate if the story needs it.\n"
    "3. 'candidato' = the index of the candidate you used (-1 if you built a window from the transcript).\n"
    "4. 'alvo_en' = WHAT TO KEEP CENTERED when cropping to vertical 9:16 — a short, visual English noun phrase an object detector "
    "understands ('red humanoid robot', 'man in white shirt', 'basketball hoop'); 'alvo_pt' the same in Portuguese.\n"
"4b. The vertical crop is a VIRTUAL CAMERA that follows what matters and changes focus. Give it the roles, as short visual English "
    "noun phrases an object detector understands: 'acao_en' = 0-2 objects that may LEAVE the subject and steal the scene while they "
    "move (a thrown ball, a frisbee, a kicked ball, a skateboard flying off, a car leaving the frame); "
    "'destino_en' = 0-2 places that action goes to (the hoop, the goal, the net, the landing ramp, the owner catching it). Empty "
    "lists when the scene has nothing like that (a talk, a close-up, a slow scene) — then the camera just follows 'alvo_en'. "
    "Examples: basketball shot → alvo 'red humanoid robot', acao ['basketball'], destino ['basketball hoop']; dog fetching → alvo "
    "'brown dog', acao ['frisbee'], destino ['man in blue shirt']; interview → alvo 'man speaking', acao [], destino [].\n"
    "5. 'modo': 'explicar' when people would ask HOW/WHY (a skill, a machine, a trick, a phenomenon, a rule); 'comentario' when the "
    "fun is the reaction, a decision, drama or something to argue about.\n"
    "6. 'ideia_gancho_pt': one line with the hook idea in Portuguese. 'titulo_pt' short; 'motivo_pt' why this moment works.")


def texto_escolha(p: Dict[str, Any]) -> str:
    cfg = p["config"]
    info = p.get("info") or {}
    leg = p.get("legenda") or []
    L = [f"VIDEO: {p.get('titulo')}", f"Length: {mmss(p.get('dur'))} ({int(p.get('dur') or 0)} s). Channel: {info.get('canal') or '?'}"]
    if info.get("descricao"):
        L.append("Description: " + info["descricao"][:1200])
    if p.get("capitulos"):
        L.append("Chapters: " + " | ".join(f"{mmss(c['t0'])} {c['titulo']}" for c in p["capitulos"][:40]))
    if cfg.get("formato") == "compilacao":
        L += ["", "WANT: ONE short with the best moments (see the rules)."]
    else:
        L += ["", f"WANT: {cfg['n_cortes']} clips, each {cfg['dur_min']}-{cfg['dur_max']} s."]
    if cfg.get("alvo"):
        L.append(f"The creator wants this kept centered when possible: {cfg['alvo']}")
    if cfg.get("modo") in ("comentario", "explicar"):
        L.append(f"The creator chose the mode: {cfg['modo']} (use it for all clips).")
    if cfg.get("extra"):
        L.append("Creator's note: " + cfg["extra"][:800])
    cands = p.get("candidatos") or []
    if cands:
        L += ["", "## CANDIDATES (from the Most-replayed graph)"]
        for k, c in enumerate(cands):
            L.append(f"\n### Candidate {k}: {c['t0']:.1f}-{c['t1']:.1f} s ({mmss(c['t0'])}-{mmss(c['t1'])}), peak at {mmss(c['pico'])}, heat {c['valor']:.2f}")
            for cm in c.get("comentarios") or []:
                L.append(f"  comment ({cm['curtidas']} likes): {cm['texto'][:200]}")
            trecho = trecho_da_legenda(leg, c["t0"] - 20, c["t1"] + 15)
            L += [f"  [{x['t0']:.1f}] {x['texto']}" for x in trecho] or ["  (no transcript here — judge by heat, comments and chapters)"]
    else:
        L += ["", "## NO 'Most replayed' graph for this video — choose from the transcript (candidato = -1).", "## TRANSCRIPT"]
        L += [f"[{x['t0']:.1f}] {x['texto']}" for x in leg][:2500]
    return "\n".join(L)


def escolher_com_ia(p: Dict[str, Any], chamar: Optional[Callable[..., Any]] = None) -> Optional[List[Dict[str, Any]]]:
    import ia_servico
    r = (chamar or ia_servico.chamar)("curtos", ESCOLHA_SYS, texto_escolha(p), schema=ESCOLHA_SCHEMA, max_tokens=3000, job=p["id"])
    if not r or not r.get("cortes"):
        return None
    cfg = p["config"]
    dur = float(p.get("dur") or 0) or 1e9
    out = []
    for c in r["cortes"]:
        try:
            t0, t1 = max(0.0, float(c["inicio"])), min(dur, float(c["fim"]))
        except (TypeError, ValueError, KeyError):
            continue
        if t1 - t0 < 3:
            continue
        if t1 - t0 > cfg["dur_max"] + 15:
            t1 = t0 + cfg["dur_max"]
        if any(min(t1, o["t1"]) - max(t0, o["t0"]) > 0.5 * (t1 - t0) for o in out):
            continue
        out.append(novo_corte(len(out) + 1, t0, t1, titulo=c.get("titulo_pt") or "", motivo=c.get("motivo_pt") or "",
                              alvo=c.get("alvo_en") or "", alvo_pt=c.get("alvo_pt") or "",
                              modo=cfg["modo"] if cfg["modo"] != "auto" else (c.get("modo") or "comentario"),
                              acao=[str(x)[:60] for x in c.get("acao_en") or []][:2], destino=[str(x)[:60] for x in c.get("destino_en") or []][:2],
                              gancho=c.get("ideia_gancho_pt") or "", candidato=int(c.get("candidato", -1) or -1)))
        if len(out) >= int(cfg["n_cortes"]):
            break
    return out or None


def novo_corte(n: int, t0: float, t1: float, **kw: Any) -> Dict[str, Any]:
    c = {"n": n, "t0": round(t0, 2), "t1": round(t1, 2), "titulo": "", "motivo": "", "alvo": "", "alvo_pt": "", "modo": "comentario",
         "gancho": "", "candidato": -1, "usar": True, "enquadrar": "", "estado": "", "erro": "", "arquivo": "", "curto": "",
         "visual": [], "enquadramento": {}, "acao": [], "destino": [], "rastros": {}, "eventos": []}
    c.update({k: v for k, v in kw.items() if k in c})
    return c


def escolher_sem_ia(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    cfg = p["config"]
    out = []
    for k, c in enumerate((p.get("candidatos") or [])[:int(cfg["n_cortes"])]):
        out.append(novo_corte(k + 1, c["t0"], c["t1"], titulo=f"Pico {k + 1} ({mmss(c['pico'])})", candidato=k,
                              motivo=f"pico do gráfico (força {c['valor']:.2f})", alvo=cfg.get("alvo") or "",
                              modo=cfg["modo"] if cfg["modo"] != "auto" else "comentario"))
    return out


LEGENDA_TAMANHOS = {"0.04": "pequena", "0.05": "média", "0.062": "grande"}
EVENTO_SOM = {"lancamento": ("whoosh", "fast whoosh throw"), "chegada": ("impacto", "basketball net swish hit")}


def _altura_margem(d: Dict[str, Any]) -> Tuple[Optional[float], float]:
    """Altura (o form manda em %: 70 → 0.70; vazio = pela posição) e margem dos lados (0..0.25)."""
    try:
        a = d.get("legenda_altura")
        alt = None if a in (None, "", "0", 0) else round(max(0.05, min(0.95, float(a) / (100 if float(a) > 1 else 1))), 3)
    except (TypeError, ValueError):
        alt = None
    try:
        m = float(d.get("legenda_margem", 0.10))
        mar = round(max(0.0, min(0.25, m / (100 if m > 1 else 1))), 3)
    except (TypeError, ValueError):
        mar = 0.10
    return alt, mar


def aplicar_visual(q: Dict[str, Any], cfg: Dict[str, Any]) -> None:
    """A legenda (estilo, tamanho, posição) e o @ do canal escolhidos aqui valem pro curto (por cima do perfil do canal)."""
    try:
        tam = max(0.03, min(0.09, float(cfg.get("legenda_tamanho") or 0.05)))
    except (TypeError, ValueError):
        tam = 0.05
    ant = q["config"].get("legenda") or {}  # 🎨 a fonte/cores do acabamento continuam
    q["config"]["legenda"] = {**{k: ant[k] for k in ("fonte", "cor_texto", "cor_ativa") if ant.get(k)}, "tamanho": tam, "posicao": cfg.get("legenda_posicao") or "terco",
                              "maiusculas": bool(cfg.get("legenda_maiusculas", True)),
                              "altura": cfg.get("legenda_altura"), "margem": cfg.get("legenda_margem", 0.10)}
    if cfg.get("legenda_estilo"):  # vazio = o estilo do canal
        q["config"]["legenda"].update(estilo=cfg["legenda_estilo"], max_palavras=1 if cfg["legenda_estilo"] == "palavra_unica" else 3)
    arroba = str(cfg.get("arroba") or "").strip()
    if arroba:
        q["config"]["marca"] = {"ativa": True, "texto": arroba if arroba.startswith("@") else "@" + arroba}


def rastros_e_sons(q: Dict[str, Any], mid: str, c: Dict[str, Any]) -> List[str]:
    """Guarda no curto o que a câmera virtual mediu: as caixas de cada objeto (o círculo do destaque segue a coisa CERTA) e os
    eventos (lançamento, chegada) pros efeitos sonoros. Devolve os nomes dos objetos rastreados."""
    if c.get("deitado") and (c.get("mapa") or {}).get("tracks"):
        q.setdefault("rastros_h", {})[mid] = {k: c["mapa"].get(k) for k in ("tracks", "cenas", "principal", "visivel")}
    elif c.get("rastros"):
        q.setdefault("rastros", {})[mid] = c["rastros"]
    for e in c.get("eventos") or []:
        tipo, busca = EVENTO_SOM.get(e.get("tipo"), ("whoosh", ""))
        q.setdefault("eventos_som", []).append({"mid": mid, "t": float(e["t"]), "tipo": tipo, "busca": busca, "o_que": e.get("tipo")})
    return list(((c.get("mapa") or {}).get("tracks") or c.get("rastros") or {}).keys())


def regra_foco(q: Dict[str, Any]) -> str:
    """🎥 O roteiro decide o enquadramento: em cada cena de clipe, 'foco' = o objeto que a fala está mostrando."""
    rh = q.get("rastros_h") or {}
    if not rh:
        return ""
    L = ["VERTICAL FRAMING: the clips are WIDE (16:9) and will be cropped to vertical AFTER the script, following each cena's 'foco'. "
         "In every clip cena set 'foco' = the EXACT name of the object the line is about at that moment (from the list below) — "
         "'' = the main subject. Talk about the shot/pass/throw/ball → foco on the ball; about the hoop/goal → that; about the "
         "crowd/people → '' unless listed. Pick de/ate where that object is VISIBLE (windows below, seconds of each clip)."]
    for mid, m in rh.items():
        vis = m.get("visivel") or {}
        L.append(f"{mid}: main subject = '{m.get('principal') or '?'}'; " + "; ".join(
            f"'{o}' visible " + (", ".join(f"{a:.1f}-{b:.1f}s" for a, b in js[:8]) or "never") for o, js in vis.items()))
    return "\n".join(L)


def regra_objetos(nomes: List[str]) -> str:
    if not nomes:
        return ""
    return ("TRACKED OBJECTS in the clip(s): " + ", ".join(sorted(set(nomes))) + ". A 'destaque' (circle/arrow) can ONLY point at one "
            "of these — use the EXACT name (e.g. talk about the shot/pass/throw → point at the ball, not at the player's legs). "
            "Point at what the line is about at that moment.")


# ---------------------------------------------------------------------------------------------------- 4b. 🎞 compilação (um short só)
COMP_SCHEMA = _o({
    "assunto_pt": S, "alvo_en": S, "gancho_pt": S, "fatos_pt": S,
    "cortes": {"type": "array", "items": _o({"inicio": N, "fim": N, "titulo_pt": S, "mostra_pt": S, "alvo_en": S,
                                             "acao_en": {"type": "array", "items": S}, "destino_en": {"type": "array", "items": S}})},
    "climax": _o({"corte": N, "inicio": N, "fim": N, "por_que_pt": S})})
COMP_SYS = (
    "You plan ONE narrated SHORT (YouTube Shorts / TikTok / Reels, ~40-70 s) built from the BEST MOMENTS of a long YouTube video — "
    "the format of viral 'curiosity' shorts: a narrator tells the story of ONE subject (e.g. a basketball robot) over a FAST collage "
    "of the video's moments (a new shot every 1-3 s: wide shots, close-ups of details, the action, the crowd reacting), and at the "
    "CLIMAX the narration STOPS and the key moment plays with its ORIGINAL SOUND for a few seconds, then the narrator comes back with "
    "the twist/facts and ends with a provocative question for the comments.\n"
    "You get the video info, candidates from YouTube's 'Most replayed' graph (heat 0..1) and the transcript.\n"
    "Return:\n"
    "- 'assunto_pt': what the short is about, one line in Portuguese (the creator may have told you).\n"
    "- 'alvo_en': what to keep CENTERED when cropping to vertical (short visual English noun phrase an object detector understands).\n"
    "- 'cortes': 4-10 SOURCE windows (seconds of the long video), each 6-30 s, that together give the narrator everything to show: "
    "the entrance/setup, close-ups of the subject's details, the key action, the reaction, other skills. Prefer high-heat moments, "
    "but cover the whole story; no overlaps. 'mostra_pt' = what is seen; 'alvo_en' per window (may differ: 'basketball', 'crowd').\n"
    "- per window 'acao_en'/'destino_en': the VIRTUAL CAMERA roles — objects that may leave the subject and steal the scene while "
    "they move (a thrown/kicked ball, a frisbee…) and where they go (the hoop, the goal, the person catching); [] when nothing like "
    "that happens in the window.\n"
    "- 'climax': THE single most impressive moment (index in 'cortes', and 'inicio'/'fim' in seconds of the long video, 3-8 s, "
    "INSIDE that window): the payoff people re-watch (the shot going in, the trick landing). It will play with its original sound.\n"
    "- 'fatos_pt': the concrete facts the narrator can use, in Portuguese — what the video/transcript/description says (names, "
    "numbers, records, how it works) plus well-established public facts you are SURE about; mark anything uncertain with '(conferir)'.\n"
    "- 'gancho_pt': the hook idea in Portuguese (e.g. 'O novo robô da Toyota simplesmente fez isso').")

ESTILO_COMPILACAO = (
    "FORMAT (follow this structure): 1) HOOK in the first 2 s over the most striking shot — a short claim that creates curiosity "
    "('Toyota's new robot just did THIS.'). 2) BUILD-UP: tell what happened step by step with suspense, short sentences ('He walked "
    "to the middle of the court, stopped in silence, faced the hoop and started calculating. Everyone in the arena thought it would "
    "be just another clumsy tech demo…'). 3) NAME IT: who/what it is with 1-2 concrete facts. 4) The line that ANNOUNCES the climax "
    "({CLIMAX}) — right after this line the narrator STOPS and the moment plays with its original sound; the cena of this line must "
    "use material {MAT} with de/ate inside {DE:.1f}-{ATE:.1f}. 5) TWIST with facts ('And it wasn't luck: …'), one impressive number "
    "per line. 6) WHAT'S NEW / bigger picture. 7) ENDING: a provocative, slightly unsettling question that makes people comment "
    "('…what happens if one day they swap the ball for something else?') + a call to comment ('Tell me in the comments.'). "
    "Cut fast: change the picture every 1-3 s, mixing wide shots and close-ups of the details the line mentions.")


def escolher_compilacao(p: Dict[str, Any], chamar: Optional[Callable[..., Any]] = None) -> Optional[Dict[str, Any]]:
    import ia_servico
    cfg = p["config"]
    texto = texto_escolha(p)
    if cfg.get("assunto"):
        texto += f"\n\nTHE SHORT IS ABOUT: {cfg['assunto']}"
    if cfg.get("referencia"):
        texto += "\n\nREFERENCE SHORT the creator wants to imitate (structure/tone — never copy):\n" + cfg["referencia"][:3000]
    r = (chamar or ia_servico.chamar)("curtos", COMP_SYS, texto, schema=COMP_SCHEMA, max_tokens=3500, job=p["id"])
    if not r or not r.get("cortes"):
        return None
    dur = float(p.get("dur") or 0) or 1e9
    cortes: List[Dict[str, Any]] = []
    mapa: Dict[int, int] = {}
    for k, c in enumerate(r["cortes"]):
        try:
            t0, t1 = max(0.0, float(c["inicio"])), min(dur, float(c["fim"]))
        except (TypeError, ValueError, KeyError):
            continue
        if t1 - t0 < 2 or any(min(t1, o["t1"]) - max(t0, o["t0"]) > 0.5 * (t1 - t0) for o in cortes):
            continue
        mapa[k] = len(cortes) + 1
        cortes.append(novo_corte(len(cortes) + 1, t0, t1, titulo=c.get("titulo_pt") or "", motivo=c.get("mostra_pt") or "",
                                 alvo=c.get("alvo_en") or r.get("alvo_en") or cfg.get("alvo") or "", modo="explicar",
                                 acao=[str(x)[:60] for x in c.get("acao_en") or []][:2],
                                 destino=[str(x)[:60] for x in c.get("destino_en") or []][:2]))
    if not cortes:
        return None
    cl = r.get("climax") or {}
    try:
        n = mapa.get(int(cl.get("corte", -1)))
        a, b = float(cl["inicio"]), float(cl["fim"])
    except (TypeError, ValueError, KeyError):
        n, a, b = None, 0.0, 0.0
    if n is None:  # o Claude errou o índice: o corte que contém o momento (ou o 1º)
        n = next((c["n"] for c in cortes if c["t0"] <= a < c["t1"]), cortes[0]["n"])
    c = next(x for x in cortes if x["n"] == n)
    a, b = max(c["t0"], a), min(c["t1"], b if b > a else a + 5)
    if b - a < 2:
        a, b = c["t0"] + (c["t1"] - c["t0"]) * 0.4, min(c["t1"], c["t0"] + (c["t1"] - c["t0"]) * 0.4 + 5)
    return {"cortes": cortes, "assunto": r.get("assunto_pt") or cfg.get("assunto") or "", "fatos": r.get("fatos_pt") or "",
            "gancho": r.get("gancho_pt") or "", "climax": {"n": n, "t0": round(a, 2), "t1": round(b, 2), "por_que": cl.get("por_que_pt") or ""}}


def compilacao_sem_ia(p: Dict[str, Any]) -> Dict[str, Any]:
    cs = (p.get("candidatos") or [])[:6]
    cortes = [novo_corte(k + 1, c["t0"], c["t1"], titulo=f"Pico {k + 1} ({mmss(c['pico'])})", alvo=p["config"].get("alvo") or "",
                         modo="explicar") for k, c in enumerate(cs)]
    top = cs[0] if cs else {"pico": 0}
    return {"cortes": cortes, "assunto": p["config"].get("assunto") or p.get("titulo") or "", "fatos": "", "gancho": "",
            "climax": {"n": 1, "t0": round(max(cortes[0]["t0"], top["pico"] - 2.5), 2) if cortes else 0,
                       "t1": round(min(cortes[0]["t1"], top["pico"] + 2.5), 2) if cortes else 0, "por_que": "o pico do gráfico"}}


def criar_compilacao(base: str, pid: str, transcrever: Optional[Callable[..., Any]] = None, prog: Prog = lambda m: None) -> str:
    """🎞 Os cortes (já verticais) viram as FONTES (M1, M2…) de um curto 📚 explicativo; o momento-chave entra cortado LARGO (W1)
    pra tocar com o som original no meio da narração."""
    import curtos as CT
    import curtos_comentario as CC
    p = carregar(base, pid)
    cfg = p["config"]
    comp = p.get("compilacao") or {}
    if comp.get("curto"):
        try:
            CT.carregar(base, comp["curto"])
            return comp["curto"]
        except Exception:  # noqa: BLE001
            pass
    usar = [c for c in p["cortes"] if c.get("usar", True) and c.get("arquivo")]
    if not usar:
        raise MomentoErro("corte os trechos primeiro")
    d = pasta(base, pid)
    titulo = (comp.get("assunto") or p.get("titulo") or "melhores momentos")[:100]
    q = CT.criar(base, CT.canal_do_modelo(base, "explicativo"), "🎞 " + titulo, [], "", modelo="explicativo")
    cid = q["id"]
    tmp = tempfile.mkdtemp(prefix="mom_comp_")
    mids: Dict[int, str] = {}
    try:
        with CT._TRAVA:
            q = CT.carregar(base, cid)
            for c in usar:
                cp = os.path.join(tmp, f"c{c['n']}.mp4")
                shutil.copy(os.path.join(d, "cortes", c["arquivo"]), cp)
                m = CT.adicionar_midia(base, q, cp, "video", f"{c.get('titulo') or ''} — {c.get('motivo') or ''}"[:300], "M",
                                       origem=f"https://youtu.be/{p['yt_id']}?t={int(c['t0'])}", aparar=False)
                mids[c["n"]] = m["id"]
            cl = comp.get("climax") or {}
            largo = os.path.join(d, "cortes", "climax_largo.mp4")
            if cl.get("t1", 0) > cl.get("t0", 0) and os.path.isfile(largo):
                cp = os.path.join(tmp, "climax.mp4")
                shutil.copy(largo, cp)
                w = CT.adicionar_midia(base, q, cp, "video", "🔊 momento-chave com o som original", "W")
                c_cl = next((c for c in usar if c["n"] == cl.get("n")), None)
                mat = mids.get(cl.get("n"), "")
                de = max(0.0, cl["t0"] - c_cl["t0"]) if c_cl else 0.0
                q["momento_original"] = {"midia": w["id"], "material": mat, "de": round(de, 2),
                                         "ate": round(de + cl["t1"] - cl["t0"], 2), "descricao": cl.get("por_que") or "momento-chave"}
            cc = CC.dados(q)
            cc["lingua_post"] = cfg["lingua_post"] if cfg["lingua_post"] in CT.LINGUAS else "en"
            cc["idioma"] = "pt" if cfg.get("idioma") == "pt" else "en"
            narrada = "pt" if cc["idioma"] == "pt" else cc["lingua_post"]
            q["config"].update(motor_perfil="chatterbox_turbo" if narrada == "en" else "chatterbox", proporcao="9:16", takes=1, midia="minhas")
            if cfg.get("voz"):
                q["config"]["voz_tts"] = str(cfg["voz"])[:120]
            try:
                q["config"]["duracao_alvo_s"] = max(0, min(180, int(cfg.get("duracao_short") or 0)))
            except (TypeError, ValueError):
                pass
            mo = q.get("momento_original") or {}
            estilo = ESTILO_COMPILACAO.replace("{CLIMAX}", cl.get("por_que") or "the key moment").replace("{MAT}", mo.get("material") or "M1")
            estilo = estilo.replace("{DE:.1f}", f"{mo.get('de', 0):.1f}").replace("{ATE:.1f}", f"{mo.get('ate', 0):.1f}")
            if not mo:
                estilo = estilo.split(" 4) ")[0] + " 5) TWIST with facts, 6) bigger picture, 7) provocative question + call to comment."
            extra = [estilo]
            nomes = []
            for c in usar:
                nomes += rastros_e_sons(q, mids[c["n"]], c)
            if regra_objetos(nomes):
                extra.append(regra_objetos(nomes))
            if regra_foco(q):
                extra.append(regra_foco(q))
            aplicar_visual(q, cfg)
            if comp.get("gancho"):
                extra.append(f"Hook idea (Portuguese): {comp['gancho']}")
            if cfg.get("extra"):
                extra.append(cfg["extra"])
            q["config"]["extra"] = "\n".join(extra)[:4500]
            topico = [f"ASSUNTO: {comp.get('assunto') or p.get('titulo')}", f"Vídeo original: {p.get('titulo')} — canal {(p.get('info') or {}).get('canal') or '?'}"]
            if comp.get("fatos"):
                topico += ["", "FATOS (do vídeo e conhecidos):", comp["fatos"]]
            if (p.get("info") or {}).get("descricao"):
                topico += ["", "Descrição do vídeo original:", p["info"]["descricao"][:1500]]
            coms = [x["texto"] for x in (p.get("info") or {}).get("comentarios") or []][:12]
            if coms:
                topico += ["", "O que o público comenta:", *[f"- {x[:200]}" for x in coms]]
            q["noticia"]["texto"] = "\n".join(topico)[:12000]
            if cfg.get("referencia"):
                cc["referencia"] = cfg["referencia"][:8000]
            q["link_rapido"] = {"link": p["link"], "modo": "explicar", "criado": time.time(), "qualidade": cfg.get("qualidade") or "1080p",
                                "exportar": cfg.get("ate") == "exportar", "comentarios_colados": "", "etapa": "✂ cortado",
                                "momentos": {"projeto": pid, "compilacao": True}}
            cc["info_link"] = {"titulo": p.get("titulo") or "", "comentarios": [], "ok": True}
            CT.salvar(base, q)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for c in usar:  # a linha do tempo de cada fonte: a fala do vídeo + o que o 👁 Moondream viu
        fala, vis = linhas_do_corte(p, c)
        if fala:
            CC.salvar_texto_do_clipe(base, cid, fala, mids[c["n"]], "fala")
        if vis:
            CC.salvar_texto_do_clipe(base, cid, vis, mids[c["n"]], "visual")
        else:  # sem Moondream: o Claude olha a fonte (o roteiro precisa saber o que cada pedaço MOSTRA)
            try:
                CC.descrever_clipe(base, cid, mids[c["n"]], on_log=prog)
            except Exception as exc:  # noqa: BLE001
                prog(f"👁 não deu pra descrever a fonte {c['n']}: {exc}")
    mudar(base, pid, lambda pp: pp.setdefault("compilacao", {}).update(curto=cid))
    return cid


def cortar_climax(base: str, pid: str, prog: Prog = lambda m: None, baixador: Optional[Callable[[str, str], str]] = None) -> Optional[str]:
    """O momento-chave com o som original — tirado do PRÓPRIO corte vertical (a câmera virtual já segue a ação; sem barras).
    Se aquele corte ainda não existe em vertical, sai do vídeo longo no meio do quadro."""
    p = carregar(base, pid)
    cl = (p.get("compilacao") or {}).get("climax") or {}
    if not cl or cl.get("t1", 0) - cl.get("t0", 0) < 1:
        return None
    d = pasta(base, pid)
    saida = os.path.join(d, "cortes", "climax_largo.mp4")
    c = next((x for x in p.get("cortes") or [] if x["n"] == cl.get("n")), None)
    prog("🔊 cortando o momento-chave (com o som original)…")
    if c and c.get("arquivo") and os.path.isfile(os.path.join(d, "cortes", c["arquivo"])):
        a = max(0.0, cl["t0"] - c["t0"])
        return vertical_automatico(base, pid, c["n"], a, a + (cl["t1"] - cl["t0"]), saida, prog)
    video = garantir_video(base, pid, prog, baixador)
    return cortar(video, cl["t0"], cl["t1"], saida, filtro_vertical(sondar(video), "seguir", []))


def referencia_do_link(base: str, link: str, transcrever: Optional[Callable[..., Any]], prog: Prog = lambda m: None) -> str:
    """📺 Short de referência (ex.: um viral do mesmo assunto): baixa e transcreve (Whisper) — a estrutura/tom que o roteiro imita."""
    if not link or not transcrever:
        return ""
    import curtos_comentario as CC
    tmp = tempfile.mkdtemp(prefix="mom_ref_")
    try:
        prog("📺 baixando e transcrevendo o short de referência…")
        cam = CC.baixar_link(link, tmp)
        segs = transcrever(cam, language=None, word_timestamps=False, info={}) or []
        return "\n".join(f"{float(s['start']):.1f} {str(s['text']).strip()}" for s in segs if str(s.get("text") or "").strip())
    except Exception as exc:  # noqa: BLE001
        prog(f"📺 não deu pra pegar a referência: {exc}")
        return ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------------------------------- 5/6. 👁 Moondream2
_MD: Dict[str, Any] = {"modelo": None}
_MD_TRAVA = threading.Lock()
CONFIG_VISAO = {"backend": "hf", "revisao_hf": "2025-06-21", "modelo_ollama": "moondream", "url_ollama": "http://localhost:11434"}


def config_visao(base: str) -> Dict[str, Any]:
    cam = os.path.join(raiz(base), "_visao.json")
    c = dict(CONFIG_VISAO)
    try:
        with open(cam, encoding="utf-8") as f:
            c.update({k: v for k, v in json.load(f).items() if k in CONFIG_VISAO})
    except (OSError, ValueError):
        pass
    return c


def salvar_config_visao(base: str, novos: Dict[str, Any]) -> Dict[str, Any]:
    c = config_visao(base)
    c.update({k: str(v)[:200] for k, v in (novos or {}).items() if k in CONFIG_VISAO})
    if c["backend"] not in ("hf", "ollama", "nenhum"):
        c["backend"] = "hf"
    os.makedirs(raiz(base), exist_ok=True)
    arquivo_seguro.gravar_json(os.path.join(raiz(base), "_visao.json"), c)
    _MD["modelo"] = None
    return c


class _ChavesAmarradas:
    """transformers 5 lê `model.all_tied_weights_keys`, que ele mesmo cria no `post_init()`. O Moondream2 (código remoto feito
    pro transformers 4) não chama isso → "'HfMoondream' object has no attribute 'all_tied_weights_keys'". Aqui o atributo é
    calculado na primeira leitura (descritor sem __set__: quando o post_init existe, o valor da instância vence)."""

    def __get__(self, obj, tipo=None):
        if obj is None:
            return self
        try:
            v = obj.get_expanded_tied_weights_keys(all_submodels=False)
        except Exception:  # noqa: BLE001
            v = {}
        obj.__dict__["all_tied_weights_keys"] = v
        return v


def _compat_transformers() -> None:
    try:
        from transformers import PreTrainedModel
    except Exception:  # noqa: BLE001
        return
    if hasattr(PreTrainedModel, "get_expanded_tied_weights_keys") and "all_tied_weights_keys" not in PreTrainedModel.__dict__:
        PreTrainedModel.all_tied_weights_keys = _ChavesAmarradas()


def _moondream_hf(vc: Dict[str, Any]):
    """Carrega o Moondream2 uma vez. GPU → float16; CPU → bfloat16 (metade da memória do float32: ~4 GB em vez de ~8 GB —
    o float32 na CPU enchia a RAM e derrubava o site com MemoryError). Se o bfloat16 der erro nessa CPU, volta pro float32."""
    with _MD_TRAVA:
        if _MD["modelo"] is None:
            import torch
            from transformers import AutoModelForCausalLM
            _compat_transformers()
            kw: Dict[str, Any] = {"trust_remote_code": True, "low_cpu_mem_usage": True}
            if vc.get("revisao_hf"):
                kw["revision"] = vc["revisao_hf"]
            if torch.cuda.is_available():
                kw.update(device_map={"": "cuda"}, dtype=torch.float16)
                _MD["dispositivo"] = "GPU (" + torch.cuda.get_device_name(0) + ")"
            else:
                kw["dtype"] = torch.float32 if _MD.get("cpu_fp32") else torch.bfloat16
                _MD["dispositivo"] = "CPU " + ("float32" if _MD.get("cpu_fp32") else "bfloat16")
            try:
                _MD["modelo"] = AutoModelForCausalLM.from_pretrained("vikhyatk/moondream2", **kw)
            except TypeError:  # transformers antigo: o parâmetro é torch_dtype
                kw["torch_dtype"] = kw.pop("dtype")
                _MD["modelo"] = AutoModelForCausalLM.from_pretrained("vikhyatk/moondream2", **kw)
            _MD["gpu"] = torch.cuda.is_available()
        return _MD["modelo"]


def liberar_moondream() -> None:
    """Tira o Moondream da memória (no fim de cada análise/produção) — a RAM volta pro resto do site."""
    with _MD_TRAVA:
        if _MD.get("modelo") is None:
            return
        _MD["modelo"] = None
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def _chamar_md(vc: Dict[str, Any], fn: Callable[[Any], Any]) -> Any:
    try:
        return fn(_moondream_hf(vc))
    except Exception as exc:  # noqa: BLE001
        if "bfloat16" in str(exc).lower() and not _MD.get("gpu") and not _MD.get("cpu_fp32"):
            _MD["cpu_fp32"] = True  # essa CPU não roda bfloat16: recarrega em float32
            liberar_moondream()
            return fn(_moondream_hf(vc))
        raise


def explicar_erro(exc: Exception) -> str:
    """Os erros do Windows/torch que aparecem ao carregar o Moondream, em português e com o que fazer."""
    t = str(exc)
    if "1455" in t or "paginação" in t.lower() or "paging file" in t.lower():
        return ("a memória virtual do Windows acabou ao carregar o modelo (erro 1455). Aumente o arquivo de paginação: Iniciar → "
                "“Exibir configurações avançadas do sistema” → Desempenho → Configurações → Avançado → Memória virtual → Alterar → "
                "“Tamanho gerenciado pelo sistema” (ou 16000–32000 MB) no disco com espaço → OK e reinicie o PC. Enquanto isso, "
                "feche o que usa muita memória (voz/Whisper rodando, muitas abas).")
    if "out of memory" in t.lower() or "cuda error: out of memory" in t.lower():
        return "a memória da placa de vídeo acabou — feche o que estiver usando a GPU (voz, Whisper, outro modelo) e tente de novo."
    return t[:300]


def explicar_erro_voz(exc: Exception) -> str:
    t = str(exc)
    if "3221225477" in t or "travou o processo" in t:
        return ("O motor de voz travou (falta de memória/placa de vídeo na hora de gerar o áudio). O que já estava pronto ficou "
                "salvo — clique de novo em 🎞/✂ fazer: ele continua da voz. Se repetir: feche outros programas pesados e confira "
                "a memória virtual do Windows (o mesmo ajuste do erro 1455).")
    return t[:500]


class Visao:
    """O 👁 que olha os quadros. descrever(img) → frase; achar(img, alvo) → [(x0,y0,x1,y1) em fração] ou None (não sabe)."""

    def __init__(self, base: str, chamar: Optional[Callable[..., Any]] = None):
        self.vc = config_visao(base)
        self.chamar = chamar
        self.erro = ""

    rapido = True  # ⚡ poucas buscas + rastreador entre elas (camera_virtual.detectar_rapido)

    @property
    def gpu(self) -> bool:
        if self.vc["backend"] != "hf":
            return True
        g = _MD.get("gpu")
        if g is None:
            try:
                import torch
                g = torch.cuda.is_available()
            except Exception:  # noqa: BLE001
                g = False
        return bool(g)

    @property
    def passo(self) -> float:
        """De quanto em quanto tempo procurar os objetos: GPU 0,5 s; CPU 1 s (cada busca na CPU leva segundos)."""
        if self.vc["backend"] != "hf":
            return 0.5
        gpu = _MD.get("gpu")
        if gpu is None:
            try:
                import torch
                gpu = torch.cuda.is_available()
            except Exception:  # noqa: BLE001
                gpu = False
        return 0.5 if gpu else 1.0

    @property
    def nome(self) -> str:
        return {"hf": "Moondream2", "ollama": "Moondream (Ollama)"}.get(self.vc["backend"], "Claude")

    def descrever(self, img: str, contexto: str = "") -> Optional[str]:
        q = ("Describe what is happening in this video frame in one or two concrete sentences: who/what is there, the action, "
             "important objects, and any text visible on screen." + (f" Context: {contexto}" if contexto else ""))
        try:
            if self.vc["backend"] == "hf":
                from PIL import Image
                im = Image.open(img).convert("RGB")
                return str(_chamar_md(self.vc, lambda m: m.query(im, q))["answer"]).strip()
            if self.vc["backend"] == "ollama":
                import urllib.request
                with open(img, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                corpo = json.dumps({"model": self.vc["modelo_ollama"], "prompt": q, "images": [b64], "stream": False,
                                    "options": {"temperature": 0}}).encode()
                req = urllib.request.Request(self.vc["url_ollama"].rstrip("/") + "/api/generate", corpo, {"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=180) as r:
                    return str(json.loads(r.read())["response"]).strip()
        except Exception as exc:  # noqa: BLE001  (Moondream fora do ar → o Claude olha depois, no curto)
            self.erro = explicar_erro(exc)
        return None

    def achar(self, img: str, alvo: str) -> Optional[List[Tuple[float, float, float, float]]]:
        """Lista de caixas (pode ser vazia = não achou). None = este 👁 não sabe achar (cai pro Claude)."""
        if self.vc["backend"] != "hf" or self.erro:
            return None
        try:
            from PIL import Image
            im = Image.open(img).convert("RGB")
            objs = _chamar_md(self.vc, lambda m: m.detect(im, alvo)).get("objects") or []
            return [(float(o["x_min"]), float(o["y_min"]), float(o["x_max"]), float(o["y_max"])) for o in objs]
        except Exception as exc:  # noqa: BLE001
            self.erro = explicar_erro(exc)
            return None

    def achar_varios_claude(self, img: str, objetos: List[str]) -> Dict[str, Tuple[float, float, float, float]]:
        """Sem detect (Ollama/nenhum): o Claude acha TODOS os objetos de uma vez nesse quadro → {objeto: (x0,y0,x1,y1)}."""
        import ia_servico
        b = ia_servico.imagem_bloco(img, largura=768)
        if not b:
            return {}
        schema = _o({"objetos": {"type": "array", "items": _o({"nome": S, "achou": {"type": "boolean"}, "x": N, "y": N, "w": N, "h": N})}})
        sys_ = ("You locate objects in a video frame for a virtual camera. For EACH requested object return its tight bounding box as "
                "FRACTIONS of the image (x,y = top-left, w,h = size, 0..1); achou=false when it is not clearly visible. Use the exact "
                "names you were given.")
        r = (self.chamar or ia_servico.chamar)("curtos", sys_, [b, {"type": "text", "text": "Objects: " + " | ".join(objetos)}],
                                               schema=schema, max_tokens=500)
        out: Dict[str, Tuple[float, float, float, float]] = {}
        for o in (r or {}).get("objetos") or []:
            try:
                if not o.get("achou") or o.get("nome") not in objetos:
                    continue
                x, y, w, h = (max(0.0, min(1.0, float(o[k]))) for k in ("x", "y", "w", "h"))
            except (TypeError, ValueError, KeyError):
                continue
            if w > 0.005 and h > 0.005:
                out[o["nome"]] = (x, y, min(1.0, x + w), min(1.0, y + h))
        return out

    def testar(self) -> Dict[str, Any]:
        """🧪 Carrega o Moondream e acha um objeto numa imagem de teste — mostra o erro de verdade se não der."""
        import time as _t
        from PIL import Image, ImageDraw
        if self.vc["backend"] == "hf" and _MD.get("modelo") is None and any(not t.get("fim") for t in TAREFAS.values()):
            return {"ok": False, "msg": "⏳ tem uma análise/produção rodando — teste quando ela terminar (carregar o modelo 2× "
                                         "ao mesmo tempo enche a memória)."}
        tmp = tempfile.mktemp(suffix=".jpg")
        im = Image.new("RGB", (640, 360), (120, 120, 120))
        ImageDraw.Draw(im).ellipse((280, 140, 360, 220), fill=(230, 120, 20))
        im.save(tmp)
        t0 = _t.time()
        try:
            if self.vc["backend"] == "nenhum":
                return {"ok": True, "msg": "Moondream desligado — o Claude olha os quadros (mais lento e gasta IA)."}
            d = self.descrever(tmp)
            if d is None:
                return {"ok": False, "msg": f"❌ {self.nome} não respondeu: {self.erro or 'sem resposta'}"}
            caixas = self.achar(tmp, "orange ball")
            det = ("acha objetos ✅" if caixas else "não achou a bola de teste ⚠") if caixas is not None else "não acha objetos (o Claude faz essa parte)"
            onde = f" · rodando na {_MD.get('dispositivo')}" if self.vc["backend"] == "hf" and _MD.get("dispositivo") else ""
            aviso = (" — ⚠ na CPU é lento (alguns segundos por quadro) e usa ~4 GB de RAM; com placa de vídeo NVIDIA + torch com CUDA "
                     "fica muito mais rápido") if "CPU" in onde else ""
            return {"ok": True, "msg": f"✅ {self.nome} funcionando ({_t.time() - t0:.1f} s){onde} — descreve ✅ · {det} · “{d[:80]}”{aviso}"}
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def achar_claude(self, img: str, alvo: str) -> Optional[Tuple[float, float, float, float]]:
        import ia_servico
        import curtos_comentario as CC
        b = ia_servico.imagem_bloco(img, largura=768)
        if not b:
            return None
        r = (self.chamar or ia_servico.chamar)("curtos", CC.CAIXA_SYS, [b, {"type": "text", "text": f"Object: {alvo}"}],
                                               schema=CC.CAIXA_SCHEMA, max_tokens=200)
        if not r or not r.get("achou"):
            return None
        try:
            x, y, w, h = (max(0.0, min(1.0, float(r[k]))) for k in ("x", "y", "w", "h"))
        except (TypeError, ValueError, KeyError):
            return None
        return (x, y, min(1.0, x + w), min(1.0, y + h))


def tirar_quadros(video: str, tempos: List[float], destino: str, largura: int = 768) -> List[Tuple[float, str]]:
    os.makedirs(destino, exist_ok=True)
    out = []
    for k, t in enumerate(tempos):
        cam = os.path.join(destino, f"q{k:04d}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", video, "-frames:v", "1",
                        "-vf", f"scale={largura}:-2", "-q:v", "3", cam], capture_output=True, timeout=120)
        if os.path.isfile(cam) and os.path.getsize(cam) > 0:
            out.append((t, cam))
    return out


def descrever_trecho(visao: Visao, video: str, dur: float, pasta_tmp: str, contexto: str = "", prog: Prog = lambda m: None,
                     passo: float = 1.0, maximo: int = 60) -> List[Dict[str, Any]]:
    """👁 Um quadro por segundo (até `maximo`) → frases; frases repetidas viram um momento só."""
    passo = max(passo, dur / maximo)
    tempos = [round(t, 2) for t in frange(0.2, max(0.3, dur - 0.1), passo)]
    out: List[Dict[str, Any]] = []
    for k, (t, img) in enumerate(tirar_quadros(video, tempos, pasta_tmp)):
        if k % 10 == 0:
            prog(f"👁 {visao.nome} olhando o trecho ({k + 1}/{len(tempos)})…")
        d = visao.descrever(img, contexto)
        if d is None:
            if visao.erro:
                prog(f"👁 {visao.nome} falhou ({visao.erro}) — o Claude olha o vídeo no lugar")
                return []
            continue
        if out and _parecido(out[-1]["o_que"], d):
            out[-1]["ate"] = round(t + passo, 2)
        else:
            out.append({"de": round(t, 2), "ate": round(min(dur, t + passo), 2), "o_que": d[:400]})
    return out


def frange(a: float, b: float, passo: float) -> List[float]:
    out, t = [], a
    while t < b:
        out.append(t)
        t += passo
    return out


def _parecido(a: str, b: str) -> bool:
    A, B = set(re.findall(r"\w+", a.lower())), set(re.findall(r"\w+", b.lower()))
    return bool(A and B) and len(A & B) / len(A | B) >= 0.7


# ---------------------------------------------------------------------------------------------------- 5. ✂ corte vertical seguindo o alvo
def sondar(video: str) -> Dict[str, Any]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                        "-of", "json", video], capture_output=True, text=True, timeout=60)
    try:
        d = json.loads(r.stdout or "{}")
        s = (d.get("streams") or [{}])[0]
        return {"w": int(s.get("width") or 0), "h": int(s.get("height") or 0), "dur": float((d.get("format") or {}).get("duration") or 0)}
    except (ValueError, IndexError):
        return {"w": 0, "h": 0, "dur": 0.0}


def _escolher_caixa(caixas: List[Tuple[float, float, float, float]], antes: Optional[float]) -> Optional[float]:
    """Mais de um alvo no quadro: o mais perto de onde a câmera estava; senão o maior."""
    if not caixas:
        return None
    if antes is not None:
        c = min(caixas, key=lambda b: abs((b[0] + b[2]) / 2 - antes))
    else:
        c = max(caixas, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    return (c[0] + c[2]) / 2


def trajeto_do_alvo(visao: Visao, video: str, dur: float, alvo: str, pasta_tmp: str, cortes_cena: List[float],
                    prog: Prog = lambda m: None, passo: float = 0.5, max_claude: int = 14) -> List[Tuple[float, Optional[float]]]:
    """[(t, centro_x em fração ou None)] — o 👁 procura o alvo a cada `passo` s. Sem detect (Ollama/nenhum): o Claude acha o
    alvo 1 vez por plano (no meio do plano)."""
    if not alvo:
        return []
    tempos = [round(t, 2) for t in frange(0.1, max(0.2, dur - 0.05), passo)]
    quadros = tirar_quadros(video, tempos, pasta_tmp, largura=640)
    pts: List[Tuple[float, Optional[float]]] = []
    ultimo: Optional[float] = None
    sem_detect = False
    for k, (t, img) in enumerate(quadros):
        if k % 20 == 0:
            prog(f"🎯 procurando “{alvo}” nos quadros ({k + 1}/{len(quadros)})…")
        caixas = visao.achar(img, alvo)
        if caixas is None:  # este 👁 não sabe achar objeto → o Claude acha, 1 vez por plano
            sem_detect = True
            break
        cx = _escolher_caixa(caixas, ultimo)
        if cx is not None:
            ultimo = cx
        pts.append((t, cx))
    if not sem_detect:
        return pts
    # 🤖 Claude: 1 quadro por plano
    planos = [0.0] + [c for c in cortes_cena if 0 < c < dur] + [dur]
    out: List[Tuple[float, Optional[float]]] = []
    for i in range(len(planos) - 1):
        if i >= max_claude:
            break
        a, b = planos[i], planos[i + 1]
        t = a + (b - a) / 2
        q = tirar_quadros(video, [t], os.path.join(pasta_tmp, f"c{i}"), largura=768)
        caixa = visao.achar_claude(q[0][1], alvo) if q else None
        cx = (caixa[0] + caixa[2]) / 2 if caixa else None
        out += [(a + 0.05, cx), (max(a + 0.06, b - 0.05), cx)]
    return out


def suavizar_trajeto(pts: List[Tuple[float, Optional[float]]], dur: float, cortes_cena: List[float], larg_frac: float,
                     vel_max: float = 0.35) -> List[Tuple[float, float]]:
    """Centro do recorte (fração 0..1 da largura) suave: cada plano é tratado sozinho (no corte de cena a câmera PULA, dentro
    do plano ela anda devagar, com zona morta pra não tremer). Plano sem o alvo → o centro do plano anterior (ou o meio)."""
    meio_min, meio_max = larg_frac / 2, 1 - larg_frac / 2
    planos = [0.0] + sorted(c for c in cortes_cena if 0.2 < c < dur - 0.2) + [dur + 0.01]
    out: List[Tuple[float, float]] = []
    anterior = 0.5
    for i in range(len(planos) - 1):
        a, b = planos[i], planos[i + 1]
        dentro = [(t, x) for t, x in pts if a <= t < b]
        achados = [x for _, x in dentro if x is not None]
        if not achados:
            out += [(a, anterior), (max(a, b - 0.02), anterior)]
            continue
        # buracos → o valor achado mais perto; mediana de 3 tira os pulos de detecção errada
        xs = []
        for k, (t, x) in enumerate(dentro):
            if x is None:
                viz = [(abs(t2 - t), x2) for t2, x2 in dentro if x2 is not None]
                x = min(viz)[1]
            xs.append(x)
        xs = [sorted(xs[max(0, k - 1):k + 2])[len(xs[max(0, k - 1):k + 2]) // 2] for k in range(len(xs))]
        cam = xs[0]
        zona = larg_frac * 0.12
        seq = []
        t_ant = dentro[0][0]
        for (t, _), x in zip(dentro, xs):
            dt = max(0.01, t - t_ant)
            if abs(x - cam) > zona:  # só anda quando o alvo sai da zona do meio; anda no máx vel_max da largura por segundo
                alvo_cam = x - math.copysign(zona, x - cam)
                passo = max(-vel_max * dt, min(vel_max * dt, alvo_cam - cam))
                cam += passo * 0.8
            seq.append((t, min(meio_max, max(meio_min, cam))))
            t_ant = t
        seq[0] = (a, seq[0][1])
        seq.append((max(seq[-1][0] + 0.01, b - 0.02), seq[-1][1]))
        out += seq
        anterior = seq[-1][1]
    return simplificar(out, 0.004)


def simplificar(pts: List[Tuple[float, float]], eps: float) -> List[Tuple[float, float]]:
    """Ramer–Douglas–Peucker: menos pontos = expressão do ffmpeg curta (plano parado vira 2 pontos)."""
    if len(pts) < 3:
        return pts
    (t0, x0), (t1, x1) = pts[0], pts[-1]
    pior, k = 0.0, 0
    for i in range(1, len(pts) - 1):
        t, x = pts[i]
        esperado = x0 + (x1 - x0) * ((t - t0) / (t1 - t0) if t1 > t0 else 0)
        d = abs(x - esperado)
        if d > pior:
            pior, k = d, i
    if pior <= eps:
        return [pts[0], pts[-1]]
    return simplificar(pts[:k + 1], eps)[:-1] + simplificar(pts[k:], eps)


def expressao_x(trajeto: List[Tuple[float, float]], W: int, cw: int) -> str:
    """O x do crop do ffmpeg (em px) como função de t: linear entre os pontos, pulo seco no corte de cena."""
    def xpx(f: float) -> float:
        return max(0.0, min(W - cw, f * W - cw / 2))
    if not trajeto:
        return str(int((W - cw) / 2))
    if len(trajeto) == 1:
        return f"{xpx(trajeto[0][1]):.1f}"
    termos = []
    for (ta, fa), (tb, fb) in zip(trajeto, trajeto[1:]):
        xa, xb = xpx(fa), xpx(fb)
        if tb - ta < 0.03:  # pulo (corte de cena): sem rampa
            continue
        if abs(xb - xa) < 0.5:
            termos.append(f"gte(t,{ta:.3f})*lt(t,{tb:.3f})*{xa:.1f}")
        else:
            termos.append(f"gte(t,{ta:.3f})*lt(t,{tb:.3f})*({xa:.1f}+{(xb - xa) / (tb - ta):.3f}*(t-{ta:.3f}))")
    termos.append(f"gte(t,{trajeto[-1][0]:.3f})*{xpx(trajeto[-1][1]):.1f}")
    termos.insert(0, f"lt(t,{trajeto[0][0]:.3f})*{xpx(trajeto[0][1]):.1f}")
    return "+".join(termos)


def filtro_vertical(info: Dict[str, Any], modo: str, trajeto: List[Tuple[float, float]], saida_w: int = 1080, saida_h: int = 1920) -> str:
    W, H = info["w"], info["h"]
    if modo == "original" or not W or not H:
        return "null"
    if modo == "desfocado" or W / H <= saida_w / saida_h + 0.01:
        return (f"split[a][b];[a]scale={saida_w}:{saida_h}:force_original_aspect_ratio=increase,crop={saida_w}:{saida_h},boxblur=30:3,"
                f"eq=brightness=-0.08[fundo];[b]scale={saida_w}:-2[frente];[fundo][frente]overlay=0:(H-h)/2")
    cw = int(H * saida_w / saida_h) // 2 * 2
    x = expressao_x(trajeto, W, cw)
    return f"crop={cw}:{H}:x='{x}':y=0,scale={saida_w}:{saida_h}:flags=lanczos,setsar=1"


def cortar(video: str, t0: float, t1: float, saida: str, filtro: str) -> str:
    """Corta [t0, t1] do vídeo longo já aplicando o enquadramento (uma passada só, re-codificando — corte exato)."""
    os.makedirs(os.path.dirname(saida) or ".", exist_ok=True)
    script = None
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-i", video, "-t", f"{t1 - t0:.3f}"]
    if filtro and filtro != "null":
        if len(filtro) > 3000:  # o Windows limita a linha de comando: filtro grande vai num arquivo
            fd, script = tempfile.mkstemp(suffix=".txt", prefix="filtro_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(f"[0:v]{filtro}[v]")
            cmd += ["-filter_complex_script", script, "-map", "[v]", "-map", "0:a?"]
        else:
            cmd += ["-filter_complex", f"[0:v]{filtro}[v]", "-map", "[v]", "-map", "0:a?"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", saida]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if (r.returncode != 0 or not os.path.isfile(saida)) and script:  # ffmpeg novo sem -filter_complex_script
            cmd[cmd.index("-filter_complex_script")] = "-/filter_complex"
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    finally:
        if script:
            try:
                os.remove(script)
            except OSError:
                pass
    if r.returncode != 0 or not os.path.isfile(saida):
        raise MomentoErro("o ffmpeg não conseguiu cortar: " + (r.stderr or "")[-400:])
    return saida


# ---------------------------------------------------------------------------------------------------- etapas
def analisar(base: str, pid: str, prog: Prog = lambda m: None, ytdlp_module: Any = None, transcrever: Optional[Callable[..., Any]] = None,
             baixador: Optional[Callable[[str, str], str]] = None, chamar: Optional[Callable[..., Any]] = None,
             navegador: Optional[Callable[..., List[List[float]]]] = None) -> Dict[str, Any]:
    """📈 gráfico + 📝 transcrição → 🔥 candidatos → 🤖 o Claude escolhe os cortes. Para em 'revisar'."""
    p = carregar(base, pid)
    cfg = p["config"]
    d = pasta(base, pid)
    etapa = lambda e: mudar(base, pid, lambda q: q.update(etapa=e, erro=""))  # noqa: E731
    # 1. info
    etapa("📈 lendo o vídeo")
    prog("📈 lendo o vídeo, o gráfico de mais repetidos e os comentários (yt-dlp)…")
    j: Dict[str, Any] = {}
    try:
        j = info_ytdlp(p["link"], 120, ytdlp_module, prog)
    except Exception as exc:  # noqa: BLE001
        prog(f"⚠ yt-dlp: {str(exc)[:200]}")
    dur = float(j.get("duration") or p.get("dur") or 0)
    heat = heatmap_do_info(j)
    fonte = "yt-dlp" if heat else ""
    if not heat and cfg.get("heatmap_colado") and dur:
        heat, fonte = heatmap_colado(cfg["heatmap_colado"], dur), "colado"
    if not heat and cfg.get("usar_navegador", True):
        try:
            heat = (navegador or heatmap_pelo_navegador)(base, p["link"], dur, prog)
            fonte = "navegador" if heat else ""
        except Exception as exc:  # noqa: BLE001
            prog(f"⚠ navegador: {str(exc)[:200]}")
    if heat and not dur:
        dur = heat[-1][1]
    coment = comentarios_com_tempo(j, dur)

    def guarda_info(q: Dict[str, Any]) -> None:
        q.update(titulo=str(j.get("title") or q.get("titulo") or "")[:200], dur=round(dur, 2), heatmap=heat, heat_fonte=fonte,
                 capitulos=[{"t0": float(c.get("start_time") or 0), "titulo": str(c.get("title") or "")[:120]} for c in j.get("chapters") or []],
                 info={"canal": str(j.get("uploader") or j.get("channel") or "")[:120], "descricao": str(j.get("description") or "")[:3000],
                       "views": j.get("view_count"), "lingua": j.get("language") or "", "comentarios_tempo": coment,
                       "comentarios": comentarios_topo(j, 40) if j.get("comments") else []})
    p = mudar(base, pid, guarda_info)
    prog(f"📈 gráfico: {'✅ ' + fonte if heat else '❌ não veio (o Claude escolhe pela transcrição)'} · 💬 {len(coment)} comentários com tempo")
    # 2. transcrição
    etapa("📝 transcrição")
    leg: List[Dict[str, Any]] = []
    lfonte = ""
    if cfg.get("transcricao_colada"):
        leg, lfonte = legenda_colada(cfg["transcricao_colada"]), "colada"
    if not leg and j:
        prog("📝 baixando a legenda do YouTube…")
        leg = baixar_legenda(p["link"], j, os.path.join(d, "_legenda"), ytdlp_module)
        lfonte = "youtube" if leg else ""
    p = mudar(base, pid, lambda q: q.update(legenda=leg, legenda_fonte=lfonte))
    # 3. candidatos
    cands = candidatos(heat, dur, cfg["dur_min"], cfg["dur_max"], max(6, int(cfg["n_cortes"]) * 2), leg, coment)
    p = mudar(base, pid, lambda q: q.update(candidatos=cands))
    if not leg:  # sem legenda: Whisper SÓ nos candidatos (ou no vídeo todo, se não tem gráfico)
        if transcrever is None:
            prog("📝 sem legenda e sem Whisper aqui — segue só com o gráfico")
        else:
            garantir_video(base, pid, prog, baixador)
            p = carregar(base, pid)
            janelas = [(max(0, c["t0"] - 20), min(dur, c["t1"] + 15)) for c in cands] or [(0.0, dur)]
            leg = []
            for k, (a, b) in enumerate(janelas):
                prog(f"🎙 Whisper no trecho {k + 1}/{len(janelas)} ({mmss(a)}–{mmss(b)})…")
                leg += whisper_trecho(os.path.join(d, p["video"]), a, b, transcrever)
            leg = sorted({(x["t0"], x["texto"]): x for x in leg}.values(), key=lambda x: x["t0"])
            cands = [dict(c, **dict(zip(("t0", "t1"), encaixar_nas_frases(leg, c["t0"], c["t1"], cfg["dur_max"])))) for c in cands]
            p = mudar(base, pid, lambda q: q.update(legenda=leg, legenda_fonte="whisper", candidatos=cands))
    if not cands and not leg:
        raise MomentoErro("Sem o gráfico de mais repetidos e sem transcrição — cole a transcrição ou o gráfico (HTML) e refaça.")
    # 4. o Claude escolhe
    etapa("🤖 escolhendo os cortes")
    if cfg.get("formato") == "compilacao":
        if cfg.get("referencia_link") and not cfg.get("referencia"):
            ref = referencia_do_link(base, cfg["referencia_link"], transcrever, prog)
            if ref:
                p = mudar(base, pid, lambda q: q["config"].update(referencia=ref))
        prog("🤖 o Claude está montando o short com os melhores momentos…")
        comp = escolher_compilacao(p, chamar)
        if not comp:
            if not cands:
                raise MomentoErro("A IA não respondeu e o vídeo não tem gráfico — ligue a IA (Configurações) ou cole o gráfico.")
            prog("🤖 IA indisponível — usando os picos do gráfico")
            comp = compilacao_sem_ia(p)
        cortes = comp.pop("cortes")
        p = mudar(base, pid, lambda q: q.update(cortes=cortes, compilacao=comp, etapa="👀 revise os cortes"))
        return p
    prog("🤖 o Claude está escolhendo os melhores cortes…")
    cortes = escolher_com_ia(p, chamar)
    if not cortes:
        if not cands:
            raise MomentoErro("A IA não respondeu e o vídeo não tem gráfico — ligue a IA (Configurações) ou cole o gráfico.")
        prog("🤖 IA indisponível — usando os picos do gráfico")
        cortes = escolher_sem_ia(p)
    p = mudar(base, pid, lambda q: q.update(cortes=cortes, etapa="👀 revise os cortes"))
    return p


def whisper_trecho(video: str, a: float, b: float, transcrever: Callable[..., Any]) -> List[Dict[str, Any]]:
    wav = tempfile.mktemp(suffix=".wav", prefix="mom_")
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.2f}", "-i", video, "-t", f"{b - a:.2f}", "-vn", "-ac", "1",
                        "-ar", "16000", wav], capture_output=True, timeout=900)
        if not os.path.isfile(wav):
            return []
        segs = transcrever(wav, language=None, word_timestamps=False, info={}) or []
        return [{"t0": round(a + float(s["start"]), 2), "t1": round(a + float(s["end"]), 2), "texto": str(s["text"]).strip()}
                for s in segs if str(s.get("text") or "").strip()]
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass


def garantir_video(base: str, pid: str, prog: Prog = lambda m: None, baixador: Optional[Callable[[str, str], str]] = None) -> str:
    p = carregar(base, pid)
    d = pasta(base, pid)
    if p.get("video") and os.path.isfile(os.path.join(d, p["video"])):
        return os.path.join(d, p["video"])
    prog(f"⬇ baixando o vídeo ({mmss(p.get('dur'))})… — vídeo longo demora")
    mudar(base, pid, lambda q: q.update(etapa="⬇ baixando o vídeo"))
    tmp = tempfile.mkdtemp(prefix="mom_dl_", dir=d)
    try:
        if baixador:
            cam = baixador(p["link"], tmp)
        else:
            import sys
            raiz_ = os.path.dirname(os.path.abspath(__file__))
            if os.path.join(raiz_, "toolkit") not in sys.path:
                sys.path.insert(0, os.path.join(raiz_, "toolkit"))
            import youtube_clipper
            cam = (youtube_clipper.baixar_video(p["link"], tmp, qualidade=p["config"].get("qualidade") or "1080p",
                                                on_log=prog) or {}).get("caminho") or ""
        if not cam or not os.path.isfile(cam):
            raise MomentoErro("não consegui baixar o vídeo")
        final = os.path.join(d, "video" + (os.path.splitext(cam)[1] or ".mp4"))
        shutil.move(cam, final)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    mudar(base, pid, lambda q: q.update(video=os.path.basename(final)))
    return final


def produzir_corte(base: str, pid: str, n: int, prog: Prog = lambda m: None, baixador: Optional[Callable[[str, str], str]] = None,
                   chamar: Optional[Callable[..., Any]] = None, visao: Optional[Visao] = None) -> Dict[str, Any]:
    """✂ corta (já vertical seguindo o alvo) + 👁 Moondream descreve o trecho."""
    import achar_fonte as AF
    video = garantir_video(base, pid, prog, baixador)
    p = carregar(base, pid)
    c = next((x for x in p["cortes"] if x["n"] == n), None)
    if not c:
        raise MomentoErro("corte não encontrado")
    d = pasta(base, pid)
    visao = visao or Visao(base, chamar)
    modo = c.get("enquadrar") or p["config"]["enquadrar"]
    alvo = (c.get("alvo") or p["config"].get("alvo") or "").strip()
    tmp = tempfile.mkdtemp(prefix=f"c{n}_", dir=d)
    try:
        # o trecho cru primeiro (o 👁 olha ele; o corte final sai do vídeo longo, sem perder qualidade)
        cru = cortar(video, c["t0"], c["t1"], os.path.join(tmp, "cru.mp4"), "scale=-2:720")
        dur = sondar(cru)["dur"] or (c["t1"] - c["t0"])
        info = sondar(video)
        cenas = AF.trocas_de_cena(cru, 0.3)[1:]
        nome = f"corte_{n:02d}.mp4"
        saida = os.path.join(d, "cortes", nome)
        cam: Dict[str, Any] = {}
        mapa: Dict[str, Any] = {}
        papeis = {"principal": alvo, "acao": [a for a in c.get("acao") or [] if a], "destino": [x for x in c.get("destino") or [] if x]}
        if modo == "seguir":
            # 🎥 v84_296: o corte fica na proporção ORIGINAL + o MAPA de onde está cada objeto. O vertical sai DEPOIS do roteiro,
            # focando o que cada fala mostra (curtos_comentario.enquadrar_planos)
            import camera_virtual as CV
            import curtos as CT
            cortar(video, c["t0"], c["t1"], saida, "scale='min(1920,iw)':-2")
            if CT.aparar_bordas(saida):  # ⬛ v84_302: faixas pretas fixas fora ANTES do mapa (as posições valem pro vídeo sem elas)
                prog("⬛ bordas pretas cortadas")
                cru = cortar(saida, 0, dur, os.path.join(tmp, "cru2.mp4"), "scale=-2:720")
                cenas = AF.trocas_de_cena(cru, 0.3)[1:]
            if alvo or papeis["acao"]:
                prog("🗺 mapeando " + ", ".join([alvo] + papeis["acao"] + papeis["destino"]) + "…")
                mapa = CV.analisar(visao, cru, dur, papeis, cenas, prog, passo=getattr(visao, "passo", 0.5))
                mapa.update(cenas=cenas, principal=alvo)
                cam = {"eventos": mapa.get("eventos") or [],
                       "achados": {o: sum(1 for x in pts if x[1] is not None) for o, pts in (mapa.get("tracks") or {}).items()}}
        else:
            cortar(video, c["t0"], c["t1"], saida, filtro_vertical(info, modo, []))
        visual = []
        if visao.vc["backend"] != "nenhum" and not _ia_ligada():
            # ⚡ com a IA ligada, quem descreve o trecho é o Claude (1 chamada, folhas de quadros) quando vira curto — antes eram
            # ~16 perguntas ao Moondream por corte. Sem a IA, o Moondream descreve.
            ctx = (p.get("titulo") or "")[:150]
            visual = descrever_trecho(visao, cru, dur, os.path.join(tmp, "desc"), ctx, prog, passo=2.0, maximo=40)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    achados = sum((cam.get("achados") or {}).values())

    def guarda(q: Dict[str, Any]) -> None:
        for x in q["cortes"]:
            if x["n"] == n:
                x.update(arquivo=nome, visual=visual, estado="✂ cortado", erro="", feito=time.time(), mapa=mapa, arquivo_vertical="",
                         rastros={}, eventos=cam.get("eventos") or [], deitado=modo == "seguir",
                         enquadramento={"modo": modo, "alvo": alvo, "achados": achados, "por_objeto": cam.get("achados") or {},
                                        "visivel": (mapa or {}).get("visivel") or {}, "visao": visao.nome, "visao_erro": visao.erro})
    mudar(base, pid, guarda)
    return next(x for x in carregar(base, pid)["cortes"] if x["n"] == n)


def vertical_automatico(base: str, pid: str, n: int, ini: Optional[float] = None, fim: Optional[float] = None,
                        saida: Optional[str] = None, prog: Prog = lambda m: None) -> str:
    """Sem roteiro (✂ só cortar / o momento-chave): o vertical sai do corte deitado com a câmera automática (segue o principal;
    a ação em movimento rouba a câmera) usando o mapa — sem barras."""
    import camera_virtual as CV
    p = carregar(base, pid)
    c = next(x for x in p["cortes"] if x["n"] == n)
    d = pasta(base, pid)
    arq = os.path.join(d, "cortes", c["arquivo"])
    mapa = c.get("mapa") or {}
    dur = sondar(arq)["dur"]
    ini = 0.0 if ini is None else ini
    fim = dur if fim is None else fim
    saida = saida or os.path.join(d, "cortes", f"corte_{n:02d}_vertical.mp4")
    if not c.get("deitado"):  # já é vertical (enquadramento desfocado/original): só recorta
        return cortar(arq, ini, fim, saida, "null")
    prog("🎥 vertical automático…")
    CV.enquadrar_pedaco(arq, ini, fim, saida, mapa.get("tracks") or {}, mapa.get("principal") or "", mapa.get("principal") or "",
                        mapa.get("cenas") or [], prog, acao=c.get("acao") or [], destino=c.get("destino") or [], abrir_inicio=ini == 0)
    return saida


def _ia_ligada() -> bool:
    try:
        import ia_servico
        return ia_servico.motivo_desligado("curtos") is None
    except Exception:  # noqa: BLE001
        return False


def linhas_do_corte(p: Dict[str, Any], c: Dict[str, Any]) -> Tuple[str, str]:
    """(fala, visual) no formato de linha do tempo do curto ("1.2 - 3.4 texto"), em segundos DO CORTE."""
    fala = []
    for x in trecho_da_legenda(p.get("legenda") or [], c["t0"], c["t1"]):
        a, b = max(0.0, x["t0"] - c["t0"]), min(c["t1"] - c["t0"], x["t1"] - c["t0"])
        fala.append(f"{a:.1f} - {b:.1f} {x['texto']}")
    vis = [f"{float(v['de']):.1f} - {float(v['ate']):.1f} {v['o_que']}" for v in c.get("visual") or []]
    return "\n".join(fala), "\n".join(vis)


def criar_curto(base: str, pid: str, n: int, transcrever: Optional[Callable[..., Any]] = None, prog: Prog = lambda m: None) -> str:
    """O corte vira um curto de 💬 comentário (com a linha do tempo da fala + o que o Moondream viu + os comentários)."""
    import curtos as CT
    import curtos_comentario as CC
    p = carregar(base, pid)
    c = next(x for x in p["cortes"] if x["n"] == n)
    cfg = p["config"]
    if c.get("curto"):
        try:
            CT.carregar(base, c["curto"])
            return c["curto"]
        except Exception:  # noqa: BLE001  (apagaram o curto: faz outro)
            pass
    arq = os.path.join(pasta(base, pid), "cortes", c["arquivo"])
    if not c.get("arquivo") or not os.path.isfile(arq):
        raise MomentoErro("corte o trecho primeiro")
    titulo = (c.get("titulo") or f"Momento {mmss(c['t0'])}")[:110]
    q = CT.criar(base, CT.canal_do_modelo(base, "comentario"), "🔥 " + titulo, [], "", modelo="comentario")
    cid = q["id"]
    link_t = f"https://youtu.be/{p['yt_id']}?t={int(c['t0'])}"
    copia = os.path.join(tempfile.mkdtemp(prefix="mom_c_"), "clipe.mp4")
    shutil.copy(arq, copia)
    with CT._TRAVA:
        q = CT.carregar(base, cid)
        CT.adicionar_midia(base, q, copia, "video", (c.get("titulo") or "")[:300], "M", origem=link_t, aparar=False)
        cc = CC.dados(q)
        cc["lingua_post"] = cfg["lingua_post"] if cfg["lingua_post"] in CT.LINGUAS else "en"
        cc["idioma"] = "pt" if cfg.get("idioma") == "pt" else "en"
        narrada = "pt" if cc["idioma"] == "pt" else cc["lingua_post"]
        q["config"]["motor_perfil"] = "chatterbox_turbo" if narrada == "en" else "chatterbox"
        q["config"]["proporcao"] = "9:16"
        q["config"]["takes"] = 1
        if cfg.get("voz"):
            q["config"]["voz_tts"] = str(cfg["voz"])[:120]
        extra = [f"This clip is a moment from a longer video ('{p.get('titulo')}', at {mmss(c['t0'])}) that viewers re-watch the most."]
        if c.get("gancho"):
            extra.append(f"Hook idea from the editor (Portuguese): {c['gancho']}")
        if c.get("motivo"):
            extra.append(f"Why this moment works (Portuguese): {c['motivo']}")
        if cfg.get("extra"):
            extra.append(cfg["extra"])
        nomes = rastros_e_sons(q, "M1", c)
        if regra_objetos(nomes):
            extra.append(regra_objetos(nomes))
        if regra_foco(q):
            extra.append(regra_foco(q))
        aplicar_visual(q, cfg)
        q["config"]["extra"] = "\n".join(extra)[:3500]
        comentarios = [{"texto": x["texto"], "curtidas": x["curtidas"], "autor": ""}
                       for x in (p.get("info") or {}).get("comentarios_tempo") or [] if c["t0"] - 5 <= x["t"] <= c["t1"] + 5]
        comentarios += [x for x in (p.get("info") or {}).get("comentarios") or [] if x["texto"] not in {y["texto"] for y in comentarios}][:30]
        cc["info_link"] = {"titulo": p.get("titulo") or "", "descricao": ((p.get("info") or {}).get("descricao") or "")[:1200],
                           "autor": (p.get("info") or {}).get("canal") or "", "views": (p.get("info") or {}).get("views"),
                           "comentarios": comentarios, "ok": True}
        cc["modo_link"] = c.get("modo") or "comentario"
        q["link_rapido"] = {"link": link_t, "modo": c.get("modo") or "comentario", "criado": time.time(),
                            "qualidade": cfg.get("qualidade") or "1080p", "exportar": cfg.get("ate") == "exportar",
                            "comentarios_colados": "", "etapa": "✂ cortado", "momentos": {"projeto": pid, "corte": n}}
        CT.salvar(base, q)
    shutil.rmtree(os.path.dirname(copia), ignore_errors=True)
    fala, vis = linhas_do_corte(p, c)
    if fala:
        CC.salvar_texto_do_clipe(base, cid, fala, "M1", "fala")
    elif transcrever:
        try:
            CC.transcrever_clipe(base, cid, "M1", transcrever, prog)
        except Exception as exc:  # noqa: BLE001
            prog(f"🎙 não deu pra transcrever: {exc}")
    if vis:
        CC.salvar_texto_do_clipe(base, cid, vis, "M1", "visual")
    else:
        try:
            CC.descrever_clipe(base, cid, "M1", on_log=prog)
        except Exception as exc:  # noqa: BLE001
            prog(f"👁 não deu pra descrever o corte: {exc}")
    mudar(base, pid, lambda pp: [x.update(curto=cid) for x in pp["cortes"] if x["n"] == n])
    return cid


def produzir(base: str, pid: str, prog: Prog = lambda m: None, so: Optional[List[int]] = None, ate: str = "",
             transcrever: Optional[Callable[..., Any]] = None, rodar_link: Optional[Callable[..., str]] = None,
             baixador: Optional[Callable[[str, str], str]] = None, chamar: Optional[Callable[..., Any]] = None) -> str:
    """Pra cada corte marcado: ✂ corta → 👁 descreve → 💬 curto → (roteiro → voz → editor → MP4)."""
    p = carregar(base, pid)
    ate = ate or p["config"].get("ate") or "exportar"
    if ate == "revisar":
        ate = "exportar"
    if p["config"].get("formato") == "compilacao":
        return produzir_compilacao(base, pid, prog, ate, transcrever, rodar_link, baixador, chamar)
    alvo = [c for c in p["cortes"] if c.get("usar", True) and (so is None or c["n"] in so)]
    if not alvo:
        raise MomentoErro("nenhum corte marcado")
    visao = Visao(base, chamar)
    feitos = 0
    ok: List[int] = []

    def estado(n: int, e: str, erro: str = "") -> None:
        mudar(base, pid, lambda q: [x.update(estado=e, erro=erro) for x in q["cortes"] if x["n"] == n])
    # FASE 1 — ✂ corta tudo (usa o Moondream)
    for k, c in enumerate(alvo, 1):
        n = c["n"]
        pr = lambda m, k=k: prog(f"[corte {k}/{len(alvo)}] {m}")  # noqa: E731
        try:
            estado(n, "✂ cortando")
            atual = next(x for x in carregar(base, pid)["cortes"] if x["n"] == n)
            if not (atual.get("arquivo") and os.path.isfile(os.path.join(pasta(base, pid), "cortes", atual["arquivo"]))):
                produzir_corte(base, pid, n, pr, baixador, chamar, visao)
            if ate == "cortes":
                atual = next(x for x in carregar(base, pid)["cortes"] if x["n"] == n)
                if atual.get("deitado"):
                    estado(n, "🎥 vertical automático")
                    v = vertical_automatico(base, pid, n, prog=pr)
                    mudar(base, pid, lambda q, n=n, v=v: [x.update(arquivo_vertical=os.path.basename(v)) for x in q["cortes"] if x["n"] == n])
                estado(n, "✅ cortado")
                feitos += 1
                continue
            estado(n, "✂ cortado — esperando a voz")
            ok.append(n)
        except Exception as exc:  # noqa: BLE001  (um corte ruim não para os outros)
            estado(n, "❌ erro", str(exc)[:500])
            pr(f"❌ corte {n}: {exc}")
    # 🧹 o Moondream sai da memória ANTES da voz: o motor de voz (outro processo) precisa da RAM/placa de vídeo — com os dois
    # carregados ele travava (código 3221225477)
    liberar_moondream()
    # FASE 2 — 💬 curto → roteiro → voz → editor/MP4
    for k, n in enumerate(ok, 1):
        pr = lambda m, k=k: prog(f"[curto {k}/{len(ok)}] {m}")  # noqa: E731
        try:
            estado(n, "💬 virando curto")
            cid = criar_curto(base, pid, n, transcrever, pr)
            if rodar_link is None:
                estado(n, "✅ curto criado (abra pra continuar)")
                feitos += 1
                continue
            estado(n, "📝 roteiro → 🎙 voz → 🎬 edição" + (" → MP4" if ate == "exportar" else ""))
            rodar_link(cid, p["config"].get("voz") or "", p["config"].get("qualidade") or "1080p", ate == "exportar", pr)
            estado(n, "✅ pronto" if ate == "exportar" else "✅ no editor")
            feitos += 1
        except Exception as exc:  # noqa: BLE001
            estado(n, "❌ erro", explicar_erro_voz(exc))
            pr(f"❌ corte {n}: {exc}")
    mudar(base, pid, lambda q: q.update(etapa=f"✅ {feitos}/{len(alvo)} prontos"))
    return f"{feitos}/{len(alvo)} prontos"


def produzir_compilacao(base: str, pid: str, prog: Prog = lambda m: None, ate: str = "exportar",
                        transcrever: Optional[Callable[..., Any]] = None, rodar_link: Optional[Callable[..., str]] = None,
                        baixador: Optional[Callable[[str, str], str]] = None, chamar: Optional[Callable[..., Any]] = None) -> str:
    """🎞 corta todas as fontes (verticais, seguindo o alvo) + o momento-chave largo → UM curto 📚 narrado → editor/MP4."""
    def estado(e: str, erro: str = "") -> None:
        mudar(base, pid, lambda q: q.setdefault("compilacao", {}).update(estado=e, erro=erro))
    p = carregar(base, pid)
    usar = [c for c in p["cortes"] if c.get("usar", True)]
    if not usar:
        raise MomentoErro("nenhum corte marcado")
    visao = Visao(base, chamar)
    try:
        for k, c in enumerate(usar, 1):
            estado(f"✂ cortando {k}/{len(usar)}")
            mudar(base, pid, lambda q, n=c["n"]: [x.update(estado="✂ cortando", erro="") for x in q["cortes"] if x["n"] == n])
            atual = next(x for x in carregar(base, pid)["cortes"] if x["n"] == c["n"])
            if not (atual.get("arquivo") and os.path.isfile(os.path.join(pasta(base, pid), "cortes", atual["arquivo"]))):
                produzir_corte(base, pid, c["n"], lambda m, k=k: prog(f"[fonte {k}/{len(usar)}] {m}"), baixador, chamar, visao)
            mudar(base, pid, lambda q, n=c["n"]: [x.update(estado="✅ cortado") for x in q["cortes"] if x["n"] == n])
        if not os.path.isfile(os.path.join(pasta(base, pid), "cortes", "climax_largo.mp4")):
            cortar_climax(base, pid, prog, baixador)
        liberar_moondream()  # 🧹 antes da voz (ver produzir)
        if ate == "cortes":
            estado("✅ fontes cortadas")
            mudar(base, pid, lambda q: q.update(etapa="✅ fontes cortadas"))
            return "fontes cortadas"
        estado("🎞 montando o short")
        cid = criar_compilacao(base, pid, transcrever, prog)
        if rodar_link is None:
            estado("✅ curto criado (abra pra continuar)")
            return "curto criado"
        estado("📝 roteiro → 🎙 voz → 🎬 edição" + (" → MP4" if ate == "exportar" else ""))
        rodar_link(cid, p["config"].get("voz") or "", p["config"].get("qualidade") or "1080p", ate == "exportar", prog)
        estado("✅ pronto" if ate == "exportar" else "✅ no editor")
        mudar(base, pid, lambda q: q.update(etapa="✅ short pronto" if ate == "exportar" else "✅ no editor"))
        return "pronto"
    except Exception as exc:
        estado("❌ erro", explicar_erro_voz(exc))
        raise


# ---------------------------------------------------------------------------------------------------- 📊 barra de andamento
_FRACAO = re.compile(r"(\d+)\s*/\s*(\d+)")
_PREFIXO = re.compile(r"^\[(corte|curto|fonte) (\d+)/(\d+)\]\s*")
ETAPAS_ANALISE = [(r"lendo o vídeo|yt-dlp", 0.00, 0.10), (r"gráfico|navegador|propaganda", 0.10, 0.15), (r"legenda", 0.15, 0.20),
                  (r"⬇|baixando o vídeo|baixando", 0.20, 0.35), (r"whisper|transcrev", 0.35, 0.70), (r"referência", 0.70, 0.74),
                  (r"🤖|claude|escolhendo|montando o short", 0.74, 0.97)]
ETAPAS_CORTE = [(r"⬇|baixando", 0.00, 0.35), (r"cortando|mapeando|moondream|procurando|🗺|🎥|câmera|vertical", 0.35, 0.98)]
ETAPAS_CURTO = [(r"alinhando", 0.50, 0.55), (r"virando curto|olhando|descrev|👁", 0.00, 0.05), (r"🎙|take|voz", 0.15, 0.50),
                (r"roteiro|📝", 0.05, 0.15), (r"🎥|vertical|enquadr", 0.55, 0.68), (r"🎯|destaque|rastreando|procurando", 0.68, 0.74),
                (r"montando no editor|🎬 montando no", 0.74, 0.77), (r"mídias", 0.77, 0.90), (r"exportando|montando e exportando", 0.90, 0.99)]


def _na_tabela(msg: str, tabela: List[Tuple[str, float, float]]) -> Optional[float]:
    m = msg.lower()
    for rx, a, b in tabela:
        if re.search(rx, m):
            f = None
            for x in _FRACAO.finditer(m):  # a última fração da mensagem ("bloco 3/12", "mídias 14/40")
                k, n = int(x.group(1)), int(x.group(2))
                if 0 < n < 100000 and 0 <= k <= n:
                    f = k / n
            return a + (b - a) * (f if f is not None else 0.3)
    return None


def estimar_andamento(msg: str, t: Dict[str, Any]) -> Optional[float]:
    """0..100 a partir das mensagens de progresso (as etapas + as frações "3/12" que cada uma já escreve). Nunca volta."""
    msg = str(msg or "")
    p = _PREFIXO.match(msg)
    resto = msg[p.end():] if p else msg
    if p:
        t["fase"] = "producao"
        k, n = int(p.group(2)), max(1, int(p.group(3)))
        if p.group(1) in ("corte", "fonte"):
            f = _na_tabela(resto, ETAPAS_CORTE)
            x = 0.30 * ((k - 1 + (f if f is not None else 0.3)) / n)
        else:
            f = _na_tabela(resto, ETAPAS_CURTO)
            x = 0.30 + 0.70 * ((k - 1 + (f if f is not None else 0.0)) / n)
    elif t.get("fase") == "producao" or t.get("so_producao"):
        t["fase"] = "producao"
        if re.search(r"🔊|momento-chave", resto.lower()):
            x = 0.30
        else:
            f = _na_tabela(resto, ETAPAS_CURTO)
            if f is None:
                return t.get("pct")
            x = 0.30 + 0.70 * f
    else:
        f = _na_tabela(resto, ETAPAS_ANALISE)
        if f is None:
            return t.get("pct")
        x = f
        if t.get("depois_produz"):
            x *= 0.20
    if t.get("depois_produz") and t.get("fase") == "producao":
        x = 0.20 + 0.80 * x
    pct = round(max(float(t.get("pct") or 0), min(99.0, x * 100)), 1)
    t["pct"] = pct
    return pct


# ---------------------------------------------------------------------------------------------------- rotas
def registrar(app, base: str, transcrever: Optional[Callable[..., Any]] = None) -> None:
    from flask import abort, jsonify, render_template, request, send_file

    def _ok(**kw: Any):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: Any, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _p(pid: str) -> Dict[str, Any]:
        try:
            return carregar(base, pid)
        except MomentoErro:
            abort(404)

    def _transcrever():
        if transcrever:
            return transcrever
        try:
            import curtos_rotas as CR
            return CR.CB.get("transcrever")
        except Exception:  # noqa: BLE001
            return None

    def _rodar_link():
        try:
            import curtos_rotas as CR
            return CR.CB.get("rodar_link")
        except Exception:  # noqa: BLE001
            return None

    def _rodar(pid: str, rotulo: str, fn: Callable[[Prog], Any]) -> None:
        t = TAREFAS.get(pid)
        if t and not t.get("fim"):
            raise MomentoErro(f"Espere terminar: {t['rotulo']}")
        TAREFAS[pid] = {"rotulo": rotulo, "inicio": time.time(), "fim": None, "erro": None, "prog": "começando…", "pct": 0.0,
                        "so_producao": rotulo.startswith("✂"),
                        "depois_produz": not rotulo.startswith("✂") and carregar(base, pid)["config"].get("ate") != "revisar"}

        def anda(m: str) -> None:
            TAREFAS[pid]["prog"] = str(m)[:300]
            estimar_andamento(str(m), TAREFAS[pid])

        def corpo() -> None:
            try:
                fn(anda)
                TAREFAS[pid]["pct"] = 100.0
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)[:600]
                TAREFAS[pid]["erro"] = msg
                try:
                    mudar(base, pid, lambda q: q.update(etapa="❌ erro", erro=msg))
                except Exception:  # noqa: BLE001
                    pass
            finally:
                TAREFAS[pid]["fim"] = time.time()
                if not any(not t.get("fim") for k, t in TAREFAS.items() if k != pid):
                    liberar_moondream()  # 🧹 a RAM volta pro resto do site (voz, Whisper, editor)
        threading.Thread(target=corpo, daemon=True, name="momentos:" + pid).start()

    def _tudo(pid: str, analisar_antes: bool) -> Callable[[Prog], Any]:
        def fn(prog: Prog) -> None:
            if analisar_antes:
                analisar(base, pid, prog, transcrever=_transcrever())
                if carregar(base, pid)["config"].get("ate") == "revisar":
                    return
            produzir(base, pid, prog, transcrever=_transcrever(), rodar_link=_rodar_link() if carregar(base, pid)["config"].get("ate") in
                     ("editor", "exportar") else None)
        return fn

    def _estado(p: Dict[str, Any]) -> Dict[str, Any]:
        t = TAREFAS.get(p["id"])
        cortes = []
        try:
            import curtos as CT
            import curtos_rotas as CR
        except Exception:  # noqa: BLE001
            CT = CR = None  # type: ignore
        for c in p.get("cortes") or []:
            x = dict(c, visual=len(c.get("visual") or []), rastros=list((c.get("rastros") or {}).keys()))
            if c.get("curto") and CT:
                try:
                    q = CT.carregar(base, c["curto"])
                    tc = (CR.TAREFAS.get(c["curto"]) or {}) if CR else {}
                    exp = q.get("exportado") or {}
                    r = q.get("roteiro") or {}
                    x["curto_info"] = {"pronto": bool(exp.get("arquivo") and os.path.isfile(exp.get("arquivo") or "")),
                                       "editor": (q.get("editor") or {}).get("job_id") or "",
                                       "etapa": (q.get("link_rapido") or {}).get("etapa") or "", "prog": tc.get("prog") or "",
                                       "roteiro": " ".join(CT.sem_tags(b.get("fala") or "") for b in r.get("blocos") or [])[:700]}
                except Exception:  # noqa: BLE001
                    pass
            cortes.append(x)
        comp = dict(p.get("compilacao") or {})
        if comp.get("curto") and CT:
            try:
                q = CT.carregar(base, comp["curto"])
                tc = (CR.TAREFAS.get(comp["curto"]) or {}) if CR else {}
                exp = q.get("exportado") or {}
                r = q.get("roteiro") or {}
                comp["curto_info"] = {"pronto": bool(exp.get("arquivo") and os.path.isfile(exp.get("arquivo") or "")),
                                      "editor": (q.get("editor") or {}).get("job_id") or "", "prog": tc.get("prog") or "",
                                      "roteiro": " ".join(CT.sem_tags(b.get("fala") or "") for b in r.get("blocos") or [])[:1500]}
            except Exception:  # noqa: BLE001
                pass
        comp["tem_climax"] = os.path.isfile(os.path.join(pasta(base, p["id"]), "cortes", "climax_largo.mp4"))
        return {"projeto": dict(p, cortes=cortes, legenda=len(p.get("legenda") or []), compilacao=comp),
                "tarefa": dict(t, rodando=not t.get("fim")) if t else None}

    def _estilos_legenda() -> List[Dict[str, str]]:
        try:
            import dp_legendas
            return [{"id": e["id"], "nome": e["nome"]} for e in dp_legendas.ESTILOS]
        except Exception:  # noqa: BLE001
            return [{"id": "pop", "nome": "Pop"}]

    def _acab() -> Dict[str, Any]:
        try:
            import curtos as CT
            return CT.acabamento(base)
        except Exception:  # noqa: BLE001
            return {}

    @app.route("/momentos-yt")
    def mom_pagina():
        try:
            import anime2d as A
            vozes_en, vozes = A.vozes_disponiveis("chatterbox_turbo"), A.vozes_disponiveis("chatterbox")
        except Exception:  # noqa: BLE001
            vozes_en, vozes = [], []
        try:
            import curtos as CT
            linguas = CT.LINGUAS
        except Exception:  # noqa: BLE001
            linguas = {"en": "English", "pt": "Português (Brasil)"}
        return render_template("momentos_yt.html", lista=listar(base), formatos=FORMATOS, estilos_legenda=_estilos_legenda(), acab=_acab(), modos=MODOS, enquadrar=ENQUADRAR, ate=ATE, linguas=linguas,
                               vozes_en=vozes_en, vozes=vozes, visao=config_visao(base), padrao=CONFIG_PADRAO, pid=request.args.get("p") or "")

    @app.route("/momentos-yt/lista")
    def mom_lista():
        return _ok(lista=listar(base))

    @app.route("/momentos-yt/novo", methods=["POST"])
    def mom_novo():
        d = request.get_json(silent=True) or {}
        cfg: Dict[str, Any] = {}
        try:
            cfg["n_cortes"] = max(1, min(10, int(d.get("n_cortes") or 3)))
            cfg["dur_min"] = max(5, min(170, int(d.get("dur_min") or 20)))
            cfg["dur_max"] = max(cfg["dur_min"] + 5, min(180, int(d.get("dur_max") or 60)))
        except (TypeError, ValueError):
            return _erro("números inválidos")
        for k, opc in (("modo", MODOS), ("enquadrar", ENQUADRAR), ("ate", ATE)):
            cfg[k] = d.get(k) if d.get(k) in opc else CONFIG_PADRAO[k]
        for k in ("lingua_post", "idioma", "voz", "qualidade", "alvo", "extra", "assunto", "referencia_link"):
            cfg[k] = str(d.get(k) or CONFIG_PADRAO[k])[:2000]
        cfg["formato"] = d.get("formato") if d.get("formato") in FORMATOS else "separados"
        cfg["arroba"] = str(d.get("arroba") or "").strip()[:40]
        cfg["legenda_estilo"] = str(d.get("legenda_estilo") or "")[:20]
        cfg["legenda_posicao"] = d.get("legenda_posicao") if d.get("legenda_posicao") in ("base", "meio", "topo", "terco") else "terco"
        try:
            cfg["legenda_tamanho"] = max(0.03, min(0.09, float(d.get("legenda_tamanho") or 0.05)))
        except (TypeError, ValueError):
            cfg["legenda_tamanho"] = 0.05
        cfg["legenda_maiusculas"] = d.get("legenda_maiusculas", True) not in (False, "0", "false")
        cfg["legenda_altura"], cfg["legenda_margem"] = _altura_margem(d)
        cfg["referencia"] = str(d.get("referencia") or "")[:20000]
        try:
            cfg["duracao_short"] = max(0, min(180, int(d.get("duracao_short") or 0)))
        except (TypeError, ValueError):
            cfg["duracao_short"] = 0
        cfg["transcricao_colada"] = str(d.get("transcricao") or "")[:400000]
        cfg["heatmap_colado"] = str(d.get("heatmap") or "")[:400000]
        cfg["usar_navegador"] = d.get("usar_navegador", True) not in (False, "0", "false")
        try:
            p = novo(base, str(d.get("link") or ""), cfg)
            _rodar(p["id"], "🔥 analisando", _tudo(p["id"], True))
        except MomentoErro as exc:
            return _erro(exc)
        return _ok(id=p["id"])

    @app.route("/momentos-yt/<pid>/estado")
    def mom_estado(pid: str):
        return _ok(**_estado(_p(pid)))

    @app.route("/momentos-yt/<pid>/reanalisar", methods=["POST"])
    def mom_reanalisar(pid: str):
        _p(pid)
        d = request.get_json(silent=True) or {}

        def up(q: Dict[str, Any]) -> None:
            if "transcricao" in d:
                q["config"]["transcricao_colada"] = str(d["transcricao"] or "")[:400000]
            if "heatmap" in d:
                q["config"]["heatmap_colado"] = str(d["heatmap"] or "")[:400000]
            q["config"]["ate"] = "revisar"
        try:
            mudar(base, pid, up)
            _rodar(pid, "🔁 analisando de novo", _tudo(pid, True))
        except MomentoErro as exc:
            return _erro(exc)
        return _ok(**_estado(carregar(base, pid)))

    @app.route("/momentos-yt/<pid>/corte/<int:n>", methods=["POST"])
    def mom_corte(pid: str, n: int):
        """Muda o corte (início/fim/alvo/modo/enquadrar/usar). Mudou o que afeta o vídeo → o corte é refeito."""
        _p(pid)
        d = request.get_json(silent=True) or {}

        def up(q: Dict[str, Any]) -> None:
            for c in q["cortes"]:
                if c["n"] != n:
                    continue
                antes = (c["t0"], c["t1"], c.get("alvo"), c.get("enquadrar"), tuple(c.get("acao") or []), tuple(c.get("destino") or []))
                for k in ("t0", "t1"):
                    if k in d:
                        v = ler_tempo(d[k]) if isinstance(d[k], str) else float(d[k])
                        if v is None:
                            raise MomentoErro("tempo inválido (use 2:40 ou 160)")
                        c[k] = round(max(0.0, min(float(q.get("dur") or 1e9), v)), 2)
                if c["t1"] - c["t0"] < 2:
                    raise MomentoErro("o fim tem que vir depois do começo")
                for k in ("alvo", "titulo", "gancho"):
                    if k in d:
                        c[k] = str(d[k] or "").strip()[:200]
                if d.get("modo") in ("comentario", "explicar"):
                    c["modo"] = d["modo"]
                if d.get("enquadrar") in ENQUADRAR or d.get("enquadrar") == "":
                    c["enquadrar"] = d["enquadrar"]
                if "usar" in d:
                    c["usar"] = bool(d["usar"])
                for k in ("acao", "destino"):
                    if k in d:
                        v = d[k] if isinstance(d[k], list) else str(d[k] or "").split(",")
                        c[k] = [str(x).strip()[:60] for x in v if str(x).strip()][:2]
                if (c["t0"], c["t1"], c.get("alvo"), c.get("enquadrar"), tuple(c.get("acao") or []), tuple(c.get("destino") or [])) != antes \
                        and c.get("arquivo"):
                    try:
                        os.remove(os.path.join(pasta(base, pid), "cortes", c["arquivo"]))
                    except OSError:
                        pass
                    c.update(arquivo="", estado="✏ mudou — cortar de novo", visual=[], curto="")
                    q.get("compilacao", {}).pop("curto", None)
                return
            raise MomentoErro("corte não encontrado")
        try:
            mudar(base, pid, up)
        except (MomentoErro, ValueError) as exc:
            return _erro(exc)
        return _ok(**_estado(carregar(base, pid)))

    @app.route("/momentos-yt/<pid>/climax", methods=["POST"])
    def mom_climax(pid: str):
        """🔊 O momento que toca com o som original (compilação): qual corte e os segundos (do vídeo longo)."""
        _p(pid)
        d = request.get_json(silent=True) or {}
        t0, t1 = ler_tempo(str(d.get("t0") or "")), ler_tempo(str(d.get("t1") or ""))

        def up(q: Dict[str, Any]) -> None:
            comp = q.setdefault("compilacao", {})
            cl = comp.setdefault("climax", {})
            if d.get("n") not in (None, ""):
                cl["n"] = int(d["n"])
            if t0 is not None:
                cl["t0"] = round(t0, 2)
            if t1 is not None:
                cl["t1"] = round(t1, 2)
            if "por_que" in d:
                cl["por_que"] = str(d["por_que"] or "")[:300]
            if cl.get("t1", 0) - cl.get("t0", 0) < 1:
                raise MomentoErro("o momento precisa ter pelo menos 1 s")
            try:
                os.remove(os.path.join(pasta(base, pid), "cortes", "climax_largo.mp4"))
            except OSError:
                pass
            comp.pop("curto", None)
        try:
            mudar(base, pid, up)
        except (MomentoErro, ValueError) as exc:
            return _erro(exc)
        return _ok(**_estado(carregar(base, pid)))

    @app.route("/momentos-yt/<pid>/climax.mp4")
    def mom_climax_video(pid: str):
        _p(pid)
        cam = os.path.join(pasta(base, pid), "cortes", "climax_largo.mp4")
        if not os.path.isfile(cam):
            abort(404)
        return send_file(cam, conditional=True)

    @app.route("/momentos-yt/<pid>/corte/novo", methods=["POST"])
    def mom_corte_novo(pid: str):
        _p(pid)
        d = request.get_json(silent=True) or {}
        t0, t1 = ler_tempo(str(d.get("t0") or "")), ler_tempo(str(d.get("t1") or ""))
        if t0 is None or t1 is None or t1 - t0 < 2:
            return _erro("diga o começo e o fim (ex.: 2:30 e 3:10)")

        def up(q: Dict[str, Any]) -> None:
            n = max([c["n"] for c in q["cortes"]] + [0]) + 1
            q["cortes"].append(novo_corte(n, t0, t1, titulo=str(d.get("titulo") or f"Meu corte {mmss(t0)}")[:120],
                                          alvo=str(d.get("alvo") or q["config"].get("alvo") or "")[:200],
                                          modo=d.get("modo") if d.get("modo") in ("comentario", "explicar") else "comentario"))
        mudar(base, pid, up)
        return _ok(**_estado(carregar(base, pid)))

    @app.route("/momentos-yt/<pid>/corte/<int:n>/apagar", methods=["POST"])
    def mom_corte_apagar(pid: str, n: int):
        _p(pid)
        mudar(base, pid, lambda q: q.update(cortes=[c for c in q["cortes"] if c["n"] != n]))
        return _ok(**_estado(carregar(base, pid)))

    @app.route("/momentos-yt/<pid>/produzir", methods=["POST"])
    def mom_produzir(pid: str):
        _p(pid)
        d = request.get_json(silent=True) or {}
        ate = d.get("ate") if d.get("ate") in ("cortes", "editor", "exportar") else "exportar"
        so = [int(x) for x in d.get("so") or []] or None
        if ate in ("editor", "exportar") and not _rodar_link():
            return _erro("O pipeline dos curtos não está disponível aqui (abra o site pelo app.py).")

        def fn(prog: Prog) -> None:
            mudar(base, pid, lambda q: q["config"].update(ate=ate))
            produzir(base, pid, prog, so=so, ate=ate, transcrever=_transcrever(), rodar_link=_rodar_link() if ate != "cortes" else None)
        try:
            _rodar(pid, "✂ produzindo", fn)
        except MomentoErro as exc:
            return _erro(exc)
        return _ok(**_estado(carregar(base, pid)))

    @app.route("/momentos-yt/<pid>/corte/<int:n>/video")
    def mom_corte_video(pid: str, n: int):
        p = _p(pid)
        c = next((x for x in p["cortes"] if x["n"] == n), None)
        cam = os.path.join(pasta(base, pid), "cortes", ((c or {}).get("arquivo_vertical") if request.args.get("vertical") else (c or {}).get("arquivo")) or "_")
        if not c or not os.path.isfile(cam):
            abort(404)
        nome = re.sub(r"[^\w]+", "_", c.get("titulo") or "")[:40]
        return send_file(cam, conditional=True, as_attachment=bool(request.args.get("baixar")), download_name=f"corte_{n:02d}_{nome}.mp4")

    @app.route("/momentos-yt/<pid>/apagar", methods=["POST"])
    def mom_apagar(pid: str):
        _p(pid)
        t = TAREFAS.get(pid)
        if t and not t.get("fim"):
            return _erro("Espere terminar.")
        shutil.rmtree(pasta(base, pid), ignore_errors=True)
        return _ok(lista=listar(base))

    @app.route("/momentos-yt/visao/testar", methods=["POST"])
    def mom_visao_testar():
        try:
            r = Visao(base).testar()
            return jsonify({"ok": True, "funcionou": bool(r.get("ok")), "msg": r.get("msg") or ""})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": True, "funcionou": False, "msg": f"❌ {str(exc)[:400]}"})
        finally:
            if not any(not t.get("fim") for t in TAREFAS.values()):
                liberar_moondream()

    @app.route("/momentos-yt/<pid>/visual", methods=["POST"])
    def mom_visual(pid: str):
        """🔤 legenda e @ do canal do projeto — valem pros curtos novos e já vão pros curtos que ele criou."""
        _p(pid)
        d = request.get_json(silent=True) or {}

        def up(q: Dict[str, Any]) -> None:
            cfg = q["config"]
            if "arroba" in d:
                cfg["arroba"] = str(d["arroba"] or "").strip()[:40]
            if "legenda_estilo" in d:
                cfg["legenda_estilo"] = str(d["legenda_estilo"] or "")[:20]  # vazio = o do canal
            if d.get("legenda_posicao"):
                cfg["legenda_posicao"] = str(d["legenda_posicao"])[:20]
            if d.get("legenda_tamanho"):
                cfg["legenda_tamanho"] = max(0.03, min(0.09, float(d["legenda_tamanho"])))
            if "legenda_maiusculas" in d:
                cfg["legenda_maiusculas"] = bool(d["legenda_maiusculas"])
            if "legenda_altura" in d or "legenda_margem" in d:
                cfg["legenda_altura"], cfg["legenda_margem"] = _altura_margem(dict({"legenda_margem": cfg.get("legenda_margem", 0.1)}, **d))
        try:
            p = mudar(base, pid, up)
        except (TypeError, ValueError) as exc:
            return _erro(exc)
        import curtos as CT
        ids = [c.get("curto") for c in p.get("cortes") or [] if c.get("curto")] + [(p.get("compilacao") or {}).get("curto")]
        for cid in [x for x in ids if x]:
            try:
                with CT._TRAVA:
                    q = CT.carregar(base, cid)
                    aplicar_visual(q, p["config"])
                    CT.salvar(base, q)
            except Exception:  # noqa: BLE001
                pass
        return _ok(**_estado(carregar(base, pid)))

    @app.route("/momentos-yt/visao", methods=["POST"])
    def mom_visao():
        return _ok(visao=salvar_config_visao(base, request.get_json(silent=True) or {}))
