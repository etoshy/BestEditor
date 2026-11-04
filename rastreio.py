"""
🎯 RASTREAR OBJETO (v84_252) — círculo, quadrado, seta ou holofote que SEGUE um objeto no vídeo.

Você pausa num quadro, desenha uma caixa em volta do objeto e escolhe o tipo; o rastreador segue o objeto pra frente e
pra trás dentro do trecho. Escorregou? Pause no quadro e desenhe de novo: cada caixa desenhada é um QUADRO-CHAVE e o
rastreio é refeito entre elas (sempre começa de uma caixa sua). Depois o vídeo sai com o desenho, com o som original,
e pode voltar pro trecho do Estúdio de onde veio.

Rastreador: CSRT do OpenCV quando a versão instalada tem; senão um rastreador próprio (pontos de fluxo óptico +
re-busca por modelo), que funciona em qualquer OpenCV. O trajeto é suavizado (sem tremedeira) e buracos curtos (o objeto
some atrás de algo por alguns quadros) são preenchidos.

Projetos em rastreios/<id>/ (ou RASTREIO_DIR): rastreio.json, video.<ext>, saida.mp4.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import arquivo_seguro  # noqa: F401

_AQUI = os.path.dirname(os.path.abspath(__file__))
_TRAVA = threading.RLock()
MAX_SEGUNDOS = 120          # trecho máximo rastreado de uma vez
LARGURA_RASTREIO = 640      # o rastreio roda num vídeo reduzido (rápido); as caixas voltam pro tamanho original
TIPOS = {"circulo": "⭕ Círculo", "quadrado": "⬜ Quadrado", "seta": "➡ Seta", "holofote": "🔦 Holofote (escurece o resto)",
         "mira": "🎯 Mira"}
DIRECOES_SETA = ("cima_esquerda", "cima", "cima_direita", "direita", "baixo_direita", "baixo", "baixo_esquerda", "esquerda")

Caixa = Tuple[float, float, float, float]  # x, y, largura, altura (px do vídeo ORIGINAL)


class RastreioErro(Exception):
    pass


# ------------------------------------------------------------------ projetos
def raiz(base: str) -> str:
    return os.environ.get("RASTREIO_DIR") or os.path.join(base, "rastreios")


def pasta(base: str, rid: str) -> str:
    if not (len(rid) == 10 and all(c in "0123456789abcdef" for c in rid)):
        raise RastreioErro("Rastreio inválido.")
    return os.path.join(raiz(base), rid)


def salvar(base: str, r: Dict[str, Any]) -> None:
    d = pasta(base, r["id"])
    os.makedirs(d, exist_ok=True)
    r["atualizado"] = time.time()
    import arquivo_seguro  # 🔒 v84_350: nome único + à prova do "Acesso negado" do Windows
    arquivo_seguro.gravar_json(os.path.join(d, "rastreio.json"), r, indent=None)


def carregar(base: str, rid: str) -> Dict[str, Any]:
    cam = os.path.join(pasta(base, rid), "rastreio.json")
    if not os.path.isfile(cam):
        raise RastreioErro("Rastreio não encontrado.")
    with open(cam, encoding="utf-8") as f:
        return json.load(f)


def listar(base: str) -> List[Dict[str, Any]]:
    d = raiz(base)
    out = []
    for rid in os.listdir(d) if os.path.isdir(d) else []:
        try:
            r = carregar(base, rid)
        except (RastreioErro, OSError, ValueError):
            continue
        out.append({"id": r["id"], "nome": r.get("nome") or "", "saida": bool(r.get("saida")), "job": r.get("job"),
                    "trecho": r.get("trecho"), "atualizado": r.get("atualizado") or 0})
    return sorted(out, key=lambda x: -x["atualizado"])


def excluir(base: str, rid: str) -> None:
    shutil.rmtree(pasta(base, rid), ignore_errors=True)


def sondar(video: str) -> Dict[str, Any]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,avg_frame_rate,nb_frames:format=duration", "-of", "json", video],
                       capture_output=True, text=True, timeout=60)
    try:
        d = json.loads(r.stdout or "{}")
        s = (d.get("streams") or [{}])[0]
        a, b = str(s.get("avg_frame_rate") or "30/1").split("/")
        fps = float(a) / float(b or 1) if float(b or 1) else 30.0
        dur = float((d.get("format") or {}).get("duration") or 0)
        w, h = int(s.get("width") or 0), int(s.get("height") or 0)
    except (ValueError, ZeroDivisionError, IndexError):
        raise RastreioErro("Não consegui ler esse vídeo.")
    if not w or not h or dur <= 0:
        raise RastreioErro("Isso não parece um vídeo.")
    return {"largura": w, "altura": h, "fps": round(fps if 1 <= fps <= 240 else 30.0, 3), "dur": round(dur, 3)}


def criar(base: str, video: str, nome: str = "", job: Optional[str] = None, trecho: Optional[int] = None,
          mover: bool = False) -> Dict[str, Any]:
    info = sondar(video)
    rid = uuid.uuid4().hex[:10]
    d = pasta(base, rid)
    os.makedirs(d, exist_ok=True)
    destino = os.path.join(d, "video" + (os.path.splitext(video)[1].lower() or ".mp4"))
    (shutil.move if mover else shutil.copy)(video, destino)
    r = {"id": rid, "nome": (nome or os.path.basename(video))[:120], "video": os.path.basename(destino), "info": info,
         "job": job, "trecho": trecho, "chaves": [], "faixa": [0.0, info["dur"]], "caixas": None,
         "estilo": estilo_padrao(), "saida": None, "criado": time.time()}
    salvar(base, r)
    return r


def caminho_video(base: str, r: Dict[str, Any]) -> str:
    return os.path.join(pasta(base, r["id"]), r["video"])


def estilo_padrao() -> Dict[str, Any]:
    return {"tipo": "circulo", "cor": "#FF2D2D", "espessura": 1.0, "folga": 1.0, "texto": "", "cor_texto": "#FFFFFF",
            "direcao": "cima_esquerda", "entrada": "desenhar", "sombra": True, "aparece": None, "some": None,
            "escurecer": 0.6}


def normalizar_estilo(e: Any) -> Dict[str, Any]:
    out = estilo_padrao()
    if isinstance(e, dict):
        out.update({k: v for k, v in e.items() if k in out})
    if out["tipo"] not in TIPOS:
        out["tipo"] = "circulo"
    if out["direcao"] not in DIRECOES_SETA:
        out["direcao"] = "cima_esquerda"
    if out["entrada"] not in ("desenhar", "pop", "nenhuma"):
        out["entrada"] = "desenhar"
    for k in ("cor", "cor_texto"):
        v = str(out[k] or "")
        out[k] = v.upper() if len(v) == 7 and v.startswith("#") else estilo_padrao()[k]
    for k, lo, hi in (("espessura", 0.3, 4.0), ("folga", 0.5, 3.0), ("escurecer", 0.1, 0.95)):
        try:
            out[k] = max(lo, min(hi, float(out[k])))
        except (TypeError, ValueError):
            out[k] = estilo_padrao()[k]
    for k in ("aparece", "some"):
        try:
            out[k] = None if out[k] in (None, "") else max(0.0, float(out[k]))
        except (TypeError, ValueError):
            out[k] = None
    out["texto"] = " ".join(str(out["texto"] or "").split())[:60]
    out["sombra"] = bool(out["sombra"])
    return out


# ------------------------------------------------------------------ rastreadores
def _csrt():
    import cv2
    for fab in (getattr(cv2, "TrackerCSRT_create", None), getattr(getattr(cv2, "legacy", None), "TrackerCSRT_create", None),
                getattr(cv2, "TrackerKCF_create", None), getattr(getattr(cv2, "legacy", None), "TrackerKCF_create", None)):
        if fab:
            try:
                return fab()
            except Exception:  # noqa: BLE001
                continue
    return None


class RastreadorFluxo:
    """Rastreador que roda em QUALQUER OpenCV: pontos bons dentro da caixa seguidos por fluxo óptico (Lucas-Kanade),
    movimento (deslocamento + escala) pela mediana dos pontos; se os pontos somem, procura o modelo da caixa por perto."""

    def init(self, frame, caixa: Caixa) -> bool:
        import cv2
        self.cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self.caixa = tuple(float(v) for v in caixa)
        self.modelo = self._recorte(self.cinza, self.caixa)
        self.pontos = self._pontos(self.cinza, self.caixa)
        return self.modelo is not None

    @staticmethod
    def _recorte(img, c):
        x, y, w, h = [int(round(v)) for v in c]
        H, W = img.shape[:2]
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None
        return img[y0:y1, x0:x1].copy()

    @staticmethod
    def _pontos(img, c):
        import cv2
        import numpy as np
        x, y, w, h = [int(round(v)) for v in c]
        m = np.zeros_like(img)
        m[max(0, y):max(0, y + h), max(0, x):max(0, x + w)] = 255
        p = cv2.goodFeaturesToTrack(img, maxCorners=80, qualityLevel=0.01, minDistance=3, mask=m)
        return p

    def update(self, frame):
        import cv2
        import numpy as np
        cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        x, y, w, h = self.caixa
        ok = False
        if self.pontos is not None and len(self.pontos) >= 5:
            novos, st, _e = cv2.calcOpticalFlowPyrLK(self.cinza, cinza, self.pontos, None, winSize=(21, 21), maxLevel=3)
            volta, st2, _e2 = cv2.calcOpticalFlowPyrLK(cinza, self.cinza, novos, None, winSize=(21, 21), maxLevel=3)
            bons = (st.ravel() == 1) & (st2.ravel() == 1) & (np.linalg.norm((volta - self.pontos).reshape(-1, 2), axis=1) < 1.5)
            a, b = self.pontos.reshape(-1, 2)[bons], novos.reshape(-1, 2)[bons]
            if len(a) >= 5:
                d = np.median(b - a, axis=0)
                da = np.linalg.norm(a[:, None] - a[None], axis=2)
                db = np.linalg.norm(b[:, None] - b[None], axis=2)
                sel = da > 1
                esc = float(np.median(db[sel] / da[sel])) if sel.any() else 1.0
                esc = max(0.9, min(1.1, esc))
                cx, cy = x + w / 2 + d[0], y + h / 2 + d[1]
                w, h = w * esc, h * esc
                x, y = cx - w / 2, cy - h / 2
                ok = True
                self.pontos = b.reshape(-1, 1, 2).astype("float32")
        if not ok and self.modelo is not None:  # perdeu os pontos: procura o modelo por perto (3× a caixa)
            H, W = cinza.shape[:2]
            mx, my = int(max(0, x - w)), int(max(0, y - h))
            area = cinza[my:int(min(H, y + 2 * h)), mx:int(min(W, x + 2 * w))]
            mh, mw = self.modelo.shape[:2]
            if area.shape[0] > mh and area.shape[1] > mw:
                res = cv2.matchTemplate(area, self.modelo, cv2.TM_CCOEFF_NORMED)
                _mn, mx_val, _l, loc = cv2.minMaxLoc(res)
                if mx_val > 0.55:
                    x, y = mx + loc[0], my + loc[1]
                    ok = True
        self.cinza = cinza
        if ok:
            self.caixa = (x, y, w, h)
            if self.pontos is None or len(self.pontos) < 15:
                self.pontos = self._pontos(cinza, self.caixa)
        return ok, self.caixa


def novo_rastreador(preferir: str = "auto"):
    if preferir != "fluxo":
        t = _csrt()
        if t is not None:
            return t, "csrt"
    return RastreadorFluxo(), "fluxo"


# ------------------------------------------------------------------ rastrear
def _ler_quadros(video: str, ini_q: int, fim_q: int, escala: float, on_prog=None) -> List[Any]:
    """Os quadros [ini_q, fim_q] reduzidos, guardados como JPEG na memória (um trecho de 1 min cabe folgado)."""
    import cv2
    cap = cv2.VideoCapture(video)
    if ini_q > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, ini_q)
    out = []
    i = ini_q
    while i <= fim_q:
        ok, fr = cap.read()
        if not ok:
            break
        if escala != 1:
            fr = cv2.resize(fr, (max(2, int(fr.shape[1] * escala)), max(2, int(fr.shape[0] * escala))), interpolation=cv2.INTER_AREA)
        out.append(cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 92])[1])
        i += 1
        if on_prog and i % 30 == 0:
            on_prog(f"lendo o vídeo… {i - ini_q}/{fim_q - ini_q + 1}")
    cap.release()
    return out


def trocas_de_cena(quadros: List[Any]) -> set:
    """Índices i em que há troca de plano entre o quadro i-1 e o i (o rastreio não atravessa um corte de cena)."""
    import cv2
    import numpy as np
    pequenos = [cv2.resize(cv2.imdecode(q, cv2.IMREAD_GRAYSCALE), (64, 36), interpolation=cv2.INTER_AREA).astype(np.float32)
                for q in quadros]
    d = [0.0] + [float(np.abs(pequenos[i] - pequenos[i - 1]).mean()) for i in range(1, len(pequenos))]
    out = set()
    for i in range(1, len(d)):
        viz = [d[k] for k in range(max(1, i - 4), min(len(d), i + 5)) if k != i]
        base = float(np.median(viz)) if viz else 0.0
        if d[i] >= 18 and d[i] >= 3 * base + 4:
            out.add(i)
    return out


def _seguir(quadros: List[Any], inicio: int, passo: int, ate: int, caixa: Caixa, preferir: str,
            cortes: Optional[set] = None) -> Dict[int, Optional[Caixa]]:
    """Do quadro `inicio` (com a caixa) andando `passo` (+1/-1) até `ate` (inclusive). {índice local: caixa ou None}.
    Para numa troca de cena (`cortes`)."""
    import cv2
    out: Dict[int, Optional[Caixa]] = {inicio: caixa}
    t, _nome = novo_rastreador(preferir)
    fr = cv2.imdecode(quadros[inicio], cv2.IMREAD_COLOR)
    init = t.init(fr, tuple(int(round(v)) for v in caixa))
    if init is False:
        return out
    perdidos = 0
    for i in range(inicio + passo, ate + passo, passo):
        if not (0 <= i < len(quadros)):
            break
        if cortes and ((passo > 0 and i in cortes) or (passo < 0 and (i + 1) in cortes)):
            break  # trocou de plano: o objeto não está mais ali
        fr = cv2.imdecode(quadros[i], cv2.IMREAD_COLOR)
        ok, b = t.update(fr)
        if ok and b[2] > 2 and b[3] > 2:
            out[i] = tuple(float(v) for v in b)
            perdidos = 0
        else:
            out[i] = None
            perdidos += 1
            if perdidos > 45:  # sumiu de vez (~1,5 s): para aqui
                break
    return out


def suavizar(caixas: List[Optional[Caixa]], janela_pos: int = 5, janela_tam: int = 11, max_buraco: int = 12) -> List[Optional[Caixa]]:
    """Tira a tremedeira (média móvel centrada: posição leve, tamanho forte) e preenche buracos curtos (interpolação)."""
    n = len(caixas)
    cs: List[Optional[List[float]]] = [None if c is None else [c[0] + c[2] / 2, c[1] + c[3] / 2, c[2], c[3]] for c in caixas]
    i = 0
    while i < n:  # buracos curtos → linha reta entre os vizinhos
        if cs[i] is None:
            j = i
            while j < n and cs[j] is None:
                j += 1
            if 0 < i and j < n and j - i <= max_buraco:
                a, b = cs[i - 1], cs[j]
                for k in range(i, j):
                    f = (k - i + 1) / (j - i + 1)
                    cs[k] = [a[m] + (b[m] - a[m]) * f for m in range(4)]
            i = j
        else:
            i += 1
    out: List[Optional[Caixa]] = []
    for i in range(n):
        if cs[i] is None:
            out.append(None)
            continue
        vals = []
        for m, jan in ((0, janela_pos), (1, janela_pos), (2, janela_tam), (3, janela_tam)):
            viz = [cs[k][m] for k in range(max(0, i - jan // 2), min(n, i + jan // 2 + 1)) if cs[k] is not None]
            vals.append(sum(viz) / len(viz))
        cx, cy, w, h = vals
        out.append((cx - w / 2, cy - h / 2, w, h))
    return out


def rastrear(video: str, chaves: Sequence[Dict[str, Any]], ini_t: float, fim_t: float, fps: float,
             on_prog: Callable[[str], None] = lambda _m: None, preferir: str = "auto") -> Dict[str, Any]:
    """chaves = [{"t": segundos, "caixa": [x, y, w, h] (px do vídeo original)}]. Rastreia de cada chave até a próxima
    (pra frente) e da 1ª pra trás até `ini_t`; da última pra frente até `fim_t`. Devolve
    {"q0": 1º quadro, "fps", "caixas": [[x,y,w,h] | None por quadro], "rastreador"}."""
    if not chaves:
        raise RastreioErro("Desenhe uma caixa em volta do objeto num quadro.")
    info = sondar(video)
    fim_t = min(float(fim_t), info["dur"])
    ini_t = max(0.0, float(ini_t))
    if fim_t - ini_t > MAX_SEGUNDOS:
        raise RastreioErro(f"Trecho longo demais pra rastrear de uma vez (máximo {MAX_SEGUNDOS} s) — encurte o início/fim.")
    q0, q1 = int(round(ini_t * fps)), max(int(round(ini_t * fps)), int(math.floor(fim_t * fps)) - 1)
    escala = min(1.0, LARGURA_RASTREIO / float(info["largura"]))
    quadros = _ler_quadros(video, q0, q1, escala, on_prog)
    if not quadros:
        raise RastreioErro("Não consegui ler os quadros do vídeo.")
    n = len(quadros)
    ks = sorted(({"q": min(n - 1, max(0, int(round(float(c["t"]) * fps)) - q0)),
                  "caixa": tuple(float(v) * escala for v in c["caixa"])} for c in chaves
                 if ini_t - 0.05 <= float(c["t"]) <= fim_t + 0.05 and len(c.get("caixa") or []) == 4), key=lambda c: c["q"])
    if not ks:
        raise RastreioErro("A caixa desenhada está fora do trecho escolhido.")
    caixas: List[Optional[Caixa]] = [None] * n
    _, nome = novo_rastreador(preferir)
    on_prog("✂ procurando as trocas de cena…")
    cortes = trocas_de_cena(quadros)
    on_prog("🎯 rastreando pra trás…" if ks[0]["q"] > 0 else "🎯 rastreando…")
    for k, v in _seguir(quadros, ks[0]["q"], -1, 0, ks[0]["caixa"], preferir, cortes).items():
        caixas[k] = v
    for idx, c in enumerate(ks):
        ate = ks[idx + 1]["q"] - 1 if idx + 1 < len(ks) else n - 1
        on_prog(f"🎯 rastreando {idx + 1}/{len(ks)}…")
        frente = _seguir(quadros, c["q"], +1, ate, c["caixa"], preferir, cortes)
        prox = ks[idx + 1] if idx + 1 < len(ks) else None
        for k, v in frente.items():
            if prox and v is not None:  # chegando na próxima chave: puxa suave até ela (sem pulo)
                faltam = prox["q"] - k
                if faltam <= 8:
                    f = 1 - faltam / 9
                    v = tuple(v[m] + (prox["caixa"][m] - v[m]) * f for m in range(4))
            caixas[k] = v
        caixas[c["q"]] = c["caixa"]
    lisas = suavizar(caixas)
    for c in ks:  # as suas caixas mandam
        lisas[c["q"]] = c["caixa"]
    inv = 1.0 / escala
    out = [None if c is None else [round(v * inv, 1) for v in c] for c in lisas]
    achados = sum(1 for c in out if c)
    return {"q0": q0, "fps": fps, "caixas": out, "rastreador": nome, "achados": achados, "total": n,
            "cortes": sorted(round((q0 + i) / fps, 3) for i in cortes)}


def caixa_no_tempo(r: Dict[str, Any], t: float) -> Optional[List[float]]:
    c = r.get("caixas") or {}
    if not c.get("caixas"):
        return None
    i = int(round(t * c["fps"])) - c["q0"]
    return c["caixas"][i] if 0 <= i < len(c["caixas"]) else None


# ------------------------------------------------------------------ desenhar
def _bgr(hexcor: str) -> Tuple[int, int, int]:
    h = hexcor.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def _vetor_direcao(d: str) -> Tuple[float, float]:
    m = {"cima_esquerda": (-1, -1), "cima": (0, -1), "cima_direita": (1, -1), "direita": (1, 0), "baixo_direita": (1, 1),
         "baixo": (0, 1), "baixo_esquerda": (-1, 1), "esquerda": (-1, 0)}[d]
    n = math.hypot(*m)
    return m[0] / n, m[1] / n


def _texto_rgba(texto: str, altura_px: int, cor: str):
    """O rótulo pronto (PIL, com acento e contorno) como imagem BGRA — feito uma vez, colado em todo quadro."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    fonte = None
    for cand in (os.path.join(_AQUI, "assets", "fonts", "dp", f) for f in ("poppins-Bold.ttf", "montserrat-Bold.ttf", "inter-Bold.ttf")):
        if os.path.isfile(cand):
            fonte = ImageFont.truetype(cand, altura_px)
            break
    if fonte is None:
        try:
            import glob
            ach = sorted(glob.glob(os.path.join(_AQUI, "assets", "fonts", "dp", "*Bold*.ttf")))
            fonte = ImageFont.truetype(ach[0], altura_px) if ach else ImageFont.load_default()
        except Exception:  # noqa: BLE001
            fonte = ImageFont.load_default()
    borda = max(2, altura_px // 10)
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    x0, y0, x1, y1 = tmp.textbbox((0, 0), texto, font=fonte, stroke_width=borda)
    im = Image.new("RGBA", (x1 - x0 + 4, y1 - y0 + 4), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((2 - x0, 2 - y0), texto, font=fonte, fill=cor, stroke_width=borda, stroke_fill=(0, 0, 0, 255))
    a = np.array(im)
    return a[:, :, [2, 1, 0, 3]]


def _colar(fr, img_bgra, x: int, y: int, alfa: float = 1.0) -> None:
    import numpy as np
    H, W = fr.shape[:2]
    h, w = img_bgra.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    rec = img_bgra[y0 - y:y1 - y, x0 - x:x1 - x]
    a = (rec[:, :, 3:4].astype(np.float32) / 255.0) * alfa
    fr[y0:y1, x0:x1] = (fr[y0:y1, x0:x1] * (1 - a) + rec[:, :, :3] * a).astype(np.uint8)


def desenhar_quadro(fr, caixa: Sequence[float], estilo: Dict[str, Any], prog: float, alfa: float, texto_img=None) -> None:
    """Desenha no quadro (BGR, no lugar). prog 0→1 = animação de entrada; alfa = sumindo no fim."""
    import cv2
    import numpy as np
    H, W = fr.shape[:2]
    x, y, w, h = caixa
    cx, cy = x + w / 2, y + h / 2
    esp = max(2, int(round(H * 0.008 * estilo["espessura"])))
    cor = _bgr(estilo["cor"])
    folga = estilo["folga"]
    entrada = estilo["entrada"]
    escala_pop = 1.0 + (0.35 * (1 - prog) if entrada == "pop" else 0)
    camada = fr.copy()
    tipo = estilo["tipo"]
    if tipo == "holofote":
        ax, ay = int(w / 2 * 1.25 * folga + esp * 2), int(h / 2 * 1.25 * folga + esp * 2)
        f = 0.25
        m = np.zeros((max(2, int(H * f)), max(2, int(W * f))), np.uint8)
        cv2.ellipse(m, (int(cx * f), int(cy * f)), (max(1, int(ax * f)), max(1, int(ay * f))), 0, 0, 360, 255, -1, cv2.LINE_AA)
        m = cv2.GaussianBlur(m, (0, 0), max(1.0, min(m.shape) * 0.02))
        m = cv2.resize(m, (W, H), interpolation=cv2.INTER_LINEAR).astype(np.float32)[:, :, None] / 255.0
        escuro = estilo["escurecer"] * (prog if entrada != "nenhuma" else 1.0) * alfa
        fr[:] = (fr * (m + (1 - m) * (1 - escuro))).astype(np.uint8)
    else:
        def tracar(img, c, t):
            if tipo == "circulo":
                ax, ay = int(w / 2 * 1.3 * folga * escala_pop + esp), int(h / 2 * 1.3 * folga * escala_pop + esp)
                fim = -90 + 360 * (prog if entrada == "desenhar" else 1.0)
                cv2.ellipse(img, (int(cx), int(cy)), (max(2, ax), max(2, ay)), 0, -90, fim, c, t, cv2.LINE_AA)
            elif tipo == "quadrado":
                pw, ph = w * (1.15 * folga) * escala_pop / 2 + esp, h * (1.15 * folga) * escala_pop / 2 + esp
                pts = [(cx - pw, cy - ph), (cx + pw, cy - ph), (cx + pw, cy + ph), (cx - pw, cy + ph), (cx - pw, cy - ph)]
                if entrada == "desenhar":  # desenha o contorno aos poucos
                    total = 4 * (pw + ph)
                    falta = total * prog
                    for a, b in zip(pts, pts[1:]):
                        seg = math.hypot(b[0] - a[0], b[1] - a[1])
                        if falta <= 0:
                            break
                        f = min(1.0, falta / seg)
                        cv2.line(img, (int(a[0]), int(a[1])), (int(a[0] + (b[0] - a[0]) * f), int(a[1] + (b[1] - a[1]) * f)), c, t, cv2.LINE_AA)
                        falta -= seg
                else:
                    cv2.rectangle(img, (int(pts[0][0]), int(pts[0][1])), (int(pts[2][0]), int(pts[2][1])), c, t, cv2.LINE_AA)
            elif tipo == "seta":
                vx, vy = _vetor_direcao(estilo["direcao"])
                raio = math.hypot(w, h) / 2 * folga
                ponta = (cx + vx * (raio + esp), cy + vy * (raio + esp))
                comp = max(80.0, H * 0.18) * folga
                base_ = (ponta[0] + vx * comp, ponta[1] + vy * comp)
                p = prog if entrada == "desenhar" else 1.0  # a base fica; a ponta avança até o objeto
                atual = (base_[0] + (ponta[0] - base_[0]) * p, base_[1] + (ponta[1] - base_[1]) * p)
                cv2.arrowedLine(img, (int(base_[0]), int(base_[1])), (int(atual[0]), int(atual[1])), c, t + 1, cv2.LINE_AA,
                                tipLength=min(0.45, 40.0 / max(1.0, comp * max(p, 0.2))))
            elif tipo == "mira":
                r_ = int(max(w, h) / 2 * 1.2 * folga * escala_pop + esp)
                cv2.circle(img, (int(cx), int(cy)), r_, c, t, cv2.LINE_AA)
                g = int(r_ * 0.45)
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    cv2.line(img, (int(cx + dx * (r_ - g)), int(cy + dy * (r_ - g))), (int(cx + dx * (r_ + g)), int(cy + dy * (r_ + g))), c, t, cv2.LINE_AA)
        if estilo["sombra"]:
            tracar(camada, (0, 0, 0), esp + max(2, esp // 2))
            sombra_a = 0.45 * alfa
            cv2.addWeighted(camada, sombra_a, fr, 1 - sombra_a, 0, dst=fr)
            camada = fr.copy()
        tracar(camada, cor, esp)
        a = alfa if entrada != "pop" else alfa * min(1.0, 0.3 + prog)
        cv2.addWeighted(camada, a, fr, 1 - a, 0, dst=fr)
    if texto_img is not None and prog > 0.6:
        th, tw = texto_img.shape[:2]
        if tipo == "seta":
            vx, vy = _vetor_direcao(estilo["direcao"])
            raio = math.hypot(w, h) / 2 * folga
            comp = max(80.0, H * 0.18) * folga
            bx, by = cx + vx * (raio + esp + comp), cy + vy * (raio + esp + comp)
            tx, ty = int(bx - tw / 2 + vx * tw * 0.45), int(by - th / 2 + vy * th * 0.9)
        else:
            tx, ty = int(cx - tw / 2), int(y - h * 0.15 * folga - th - esp * 2)
            if ty < 4:
                ty = int(y + h + h * 0.15 * folga + esp * 2)
        tx = max(4, min(W - tw - 4, tx))
        ty = max(4, min(H - th - 4, ty))
        _colar(fr, texto_img, tx, ty, min(1.0, (prog - 0.6) / 0.4) * alfa)


def gerar(base: str, rid: str, on_prog: Callable[[str], None] = lambda _m: None) -> str:
    """O vídeo com o desenho seguindo o objeto (o vídeo inteiro, com o som original). Devolve o caminho."""
    import cv2
    r = carregar(base, rid)
    tr = r.get("caixas") or {}
    if not tr.get("caixas"):
        raise RastreioErro("Rastreie o objeto antes (🎯 Rastrear).")
    est = normalizar_estilo(r.get("estilo"))
    video = caminho_video(base, r)
    info = r["info"]
    fps = float(tr["fps"])
    q0, cxs = int(tr["q0"]), tr["caixas"]
    achou = [k for k, c in enumerate(cxs) if c]
    if not achou:
        raise RastreioErro("O rastreio não achou o objeto em nenhum quadro — desenhe a caixa de novo.")
    aparece = est["aparece"] if est["aparece"] is not None else ((q0 + achou[0]) / fps)  # do 1º ao último quadro achado
    some = est["some"] if est["some"] is not None else ((q0 + achou[-1] + 1) / fps)
    dur_entrada, dur_saida = (0.0 if est["entrada"] == "nenhuma" else 0.4), 0.25
    texto_img = _texto_rgba(est["texto"], max(18, int(info["altura"] * 0.05)), est["cor_texto"]) if est["texto"] else None
    d = pasta(base, rid)
    saida = os.path.join(d, f"saida_{uuid.uuid4().hex[:6]}.mp4")
    W, H = info["largura"], info["altura"]
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", f"{fps:.5f}", "-i", "-",
           "-i", video, "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
           "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", saida]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    cap = cv2.VideoCapture(video)
    i = 0
    ultimo = None
    total = max(1, int(info["dur"] * fps))
    try:
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            if fr.shape[1] != W or fr.shape[0] != H:
                fr = cv2.resize(fr, (W, H))
            t = i / fps
            k = i - q0
            c = cxs[k] if 0 <= k < len(cxs) else None
            if c is None and ultimo is not None and 0 <= k < len(cxs) and ultimo[1] >= i - 5:
                c = ultimo[0]  # sumiu por 1-5 quadros: segura onde estava
            if c is not None:
                ultimo = (c, i)
            if c is not None and aparece <= t <= some:
                prog = 1.0 if dur_entrada <= 0 else min(1.0, (t - aparece) / dur_entrada)
                prog = 1 - (1 - prog) ** 3  # ease-out
                alfa = min(1.0, max(0.0, (some - t) / dur_saida))
                desenhar_quadro(fr, c, est, prog, alfa, texto_img)
            proc.stdin.write(fr.tobytes())
            i += 1
            if i % 30 == 0:
                on_prog(f"🎬 desenhando {i}/{total} quadros")
    finally:
        cap.release()
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        proc.wait(timeout=600)
    if proc.returncode != 0 or not os.path.isfile(saida):
        raise RastreioErro(f"Não consegui gerar o vídeo: {err[-300:]}")
    with _TRAVA:
        r = carregar(base, rid)
        velho = r.get("saida")
        r["saida"] = os.path.basename(saida)
        salvar(base, r)
    if velho and velho != r["saida"]:
        try:
            os.remove(os.path.join(d, velho))
        except OSError:
            pass
    return saida
