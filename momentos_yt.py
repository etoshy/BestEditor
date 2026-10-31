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
ATE = {"revisar": "👀 parar pra eu revisar os cortes", "cortes": "✂ só cortar (sem roteiro)",
       "editor": "📝 roteiro + voz → editor", "exportar": "🎬 até o MP4 pronto"}
CONFIG_PADRAO = {"n_cortes": 3, "dur_min": 20, "dur_max": 60, "modo": "auto", "enquadrar": "seguir", "ate": "revisar",
                 "lingua_post": "en", "idioma": "en", "voz": "", "qualidade": "1080p", "alvo": "", "extra": "",
                 "transcricao_colada": "", "heatmap_colado": "", "usar_navegador": True}


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
                              gancho=c.get("ideia_gancho_pt") or "", candidato=int(c.get("candidato", -1) or -1)))
        if len(out) >= int(cfg["n_cortes"]):
            break
    return out or None


def novo_corte(n: int, t0: float, t1: float, **kw: Any) -> Dict[str, Any]:
    c = {"n": n, "t0": round(t0, 2), "t1": round(t1, 2), "titulo": "", "motivo": "", "alvo": "", "alvo_pt": "", "modo": "comentario",
         "gancho": "", "candidato": -1, "usar": True, "enquadrar": "", "estado": "", "erro": "", "arquivo": "", "curto": "",
         "visual": [], "enquadramento": {}}
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


def _moondream_hf(vc: Dict[str, Any]):
    with _MD_TRAVA:
        if _MD["modelo"] is None:
            import torch
            from transformers import AutoModelForCausalLM
            kw: Dict[str, Any] = {"trust_remote_code": True}
            if vc.get("revisao_hf"):
                kw["revision"] = vc["revisao_hf"]
            if torch.cuda.is_available():
                kw.update(device_map={"": "cuda"}, torch_dtype=torch.float16)
            _MD["modelo"] = AutoModelForCausalLM.from_pretrained("vikhyatk/moondream2", **kw)
        return _MD["modelo"]


class Visao:
    """O 👁 que olha os quadros. descrever(img) → frase; achar(img, alvo) → [(x0,y0,x1,y1) em fração] ou None (não sabe)."""

    def __init__(self, base: str, chamar: Optional[Callable[..., Any]] = None):
        self.vc = config_visao(base)
        self.chamar = chamar
        self.erro = ""

    @property
    def nome(self) -> str:
        return {"hf": "Moondream2", "ollama": "Moondream (Ollama)"}.get(self.vc["backend"], "Claude")

    def descrever(self, img: str, contexto: str = "") -> Optional[str]:
        q = ("Describe what is happening in this video frame in one or two concrete sentences: who/what is there, the action, "
             "important objects, and any text visible on screen." + (f" Context: {contexto}" if contexto else ""))
        try:
            if self.vc["backend"] == "hf":
                from PIL import Image
                return str(_moondream_hf(self.vc).query(Image.open(img).convert("RGB"), q)["answer"]).strip()
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
            self.erro = str(exc)[:200]
        return None

    def achar(self, img: str, alvo: str) -> Optional[List[Tuple[float, float, float, float]]]:
        """Lista de caixas (pode ser vazia = não achou). None = este 👁 não sabe achar (cai pro Claude)."""
        if self.vc["backend"] != "hf" or self.erro:
            return None
        try:
            from PIL import Image
            objs = _moondream_hf(self.vc).detect(Image.open(img).convert("RGB"), alvo).get("objects") or []
            return [(float(o["x_min"]), float(o["y_min"]), float(o["x_max"]), float(o["y_max"])) for o in objs]
        except Exception as exc:  # noqa: BLE001
            self.erro = str(exc)[:200]
            return None

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
        trajeto: List[Tuple[float, float]] = []
        achados = 0
        if modo == "seguir":
            if alvo:
                pts = trajeto_do_alvo(visao, cru, dur, alvo, os.path.join(tmp, "alvo"), cenas, prog)
                achados = sum(1 for _, x in pts if x is not None)
                cw_frac = (int(info["h"] * 1080 / 1920) // 2 * 2) / max(1, info["w"])
                trajeto = suavizar_trajeto(pts, dur, cenas, cw_frac) if achados else []
            if not trajeto:
                prog("🎯 alvo não achado — corte no meio do quadro" if alvo else "🎯 sem alvo — corte no meio do quadro")
        prog("✂ cortando" + (" em vertical seguindo o alvo…" if trajeto else "…"))
        nome = f"corte_{n:02d}.mp4"
        cortar(video, c["t0"], c["t1"], os.path.join(d, "cortes", nome), filtro_vertical(info, modo, trajeto))
        visual = []
        if visao.vc["backend"] != "nenhum":
            ctx = (p.get("titulo") or "")[:150]
            visual = descrever_trecho(visao, cru, dur, os.path.join(tmp, "desc"), ctx, prog)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    def guarda(q: Dict[str, Any]) -> None:
        for x in q["cortes"]:
            if x["n"] == n:
                x.update(arquivo=nome, visual=visual, estado="✂ cortado", erro="", feito=time.time(),
                         enquadramento={"modo": modo, "alvo": alvo, "achados": achados, "pontos": len(trajeto), "visao": visao.nome})
    mudar(base, pid, guarda)
    return next(x for x in carregar(base, pid)["cortes"] if x["n"] == n)


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
        CT.adicionar_midia(base, q, copia, "video", (c.get("titulo") or "")[:300], "M", origem=link_t)
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
        q["config"]["extra"] = "\n".join(extra)[:2000]
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
    alvo = [c for c in p["cortes"] if c.get("usar", True) and (so is None or c["n"] in so)]
    if not alvo:
        raise MomentoErro("nenhum corte marcado")
    visao = Visao(base, chamar)
    feitos = 0
    for k, c in enumerate(alvo, 1):
        n = c["n"]
        pr = lambda m, k=k: prog(f"[{k}/{len(alvo)}] {m}")  # noqa: E731

        def estado(e: str, erro: str = "", n=n) -> None:
            mudar(base, pid, lambda q: [x.update(estado=e, erro=erro) for x in q["cortes"] if x["n"] == n])
        try:
            estado("✂ cortando")
            atual = next(x for x in carregar(base, pid)["cortes"] if x["n"] == n)
            if not (atual.get("arquivo") and os.path.isfile(os.path.join(pasta(base, pid), "cortes", atual["arquivo"]))):
                produzir_corte(base, pid, n, pr, baixador, chamar, visao)
            if ate == "cortes":
                estado("✅ cortado")
                feitos += 1
                continue
            estado("💬 virando curto")
            cid = criar_curto(base, pid, n, transcrever, pr)
            if rodar_link is None:
                estado("✅ curto criado (abra pra continuar)")
                feitos += 1
                continue
            estado("📝 roteiro → 🎙 voz → 🎬 edição" + (" → MP4" if ate == "exportar" else ""))
            rodar_link(cid, p["config"].get("voz") or "", p["config"].get("qualidade") or "1080p", ate == "exportar", pr)
            estado("✅ pronto" if ate == "exportar" else "✅ no editor")
            feitos += 1
        except Exception as exc:  # noqa: BLE001  (um corte ruim não para os outros)
            estado("❌ erro", str(exc)[:500])
            pr(f"❌ corte {n}: {exc}")
    mudar(base, pid, lambda q: q.update(etapa=f"✅ {feitos}/{len(alvo)} prontos"))
    return f"{feitos}/{len(alvo)} prontos"


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
        TAREFAS[pid] = {"rotulo": rotulo, "inicio": time.time(), "fim": None, "erro": None, "prog": "começando…"}

        def corpo() -> None:
            try:
                fn(lambda m: TAREFAS[pid].__setitem__("prog", str(m)[:300]))
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)[:600]
                TAREFAS[pid]["erro"] = msg
                try:
                    mudar(base, pid, lambda q: q.update(etapa="❌ erro", erro=msg))
                except Exception:  # noqa: BLE001
                    pass
            finally:
                TAREFAS[pid]["fim"] = time.time()
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
            x = dict(c, visual=len(c.get("visual") or []))
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
        return {"projeto": dict(p, cortes=cortes, legenda=len(p.get("legenda") or [])),
                "tarefa": dict(t, rodando=not t.get("fim")) if t else None}

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
        return render_template("momentos_yt.html", lista=listar(base), modos=MODOS, enquadrar=ENQUADRAR, ate=ATE, linguas=linguas,
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
        for k in ("lingua_post", "idioma", "voz", "qualidade", "alvo", "extra"):
            cfg[k] = str(d.get(k) or CONFIG_PADRAO[k])[:2000]
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
                antes = (c["t0"], c["t1"], c.get("alvo"), c.get("enquadrar"))
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
                if (c["t0"], c["t1"], c.get("alvo"), c.get("enquadrar")) != antes and c.get("arquivo"):
                    try:
                        os.remove(os.path.join(pasta(base, pid), "cortes", c["arquivo"]))
                    except OSError:
                        pass
                    c.update(arquivo="", estado="✏ mudou — cortar de novo", visual=[], curto="")
                return
            raise MomentoErro("corte não encontrado")
        try:
            mudar(base, pid, up)
        except (MomentoErro, ValueError) as exc:
            return _erro(exc)
        return _ok(**_estado(carregar(base, pid)))

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
        cam = os.path.join(pasta(base, pid), "cortes", (c or {}).get("arquivo") or "_")
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

    @app.route("/momentos-yt/visao", methods=["POST"])
    def mom_visao():
        return _ok(visao=salvar_config_visao(base, request.get_json(silent=True) or {}))
