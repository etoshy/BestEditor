"""camera_virtual.py — 🎥 Câmera virtual pro corte vertical (v84_292).

O corte 9:16 de um vídeo deitado não pode ficar parado num objeto: o que interessa MUDA (o robô quica a bola → arremessa →
a bola voa → entra na cesta → volta pro robô). Aqui o "cinegrafista" é automático:

  1. 👁 DETECTA os objetos de interesse a cada 0,5 s (Moondream `detect`; sem ele, o Claude 1-3× por plano), com papéis:
       • principal  — o assunto (o robô);
       • ação       — o que pode sair voando e roubar a cena (a bola);
       • destino    — pra onde a ação vai (a cesta).
     Quando a bola anda rápido demais entre duas amostras, procura de novo no meio (8 quadros/s nesse pedaço).
  2. 🎬 PLANEJA a câmera: segue o principal; quando a ação "dispara" (sai de perto do principal ou anda rápido) a câmera
     larga o principal e vai com a bola — e abre pra mostrar a bola E a cesta juntas; depois volta pro principal.
     O ZOOM não é fixo: o enquadramento é o tamanho do que precisa aparecer (+ folga) — abre quando o assunto é grande ou
     quando precisa mostrar dois objetos (com o próprio vídeo desfocado atrás), fecha quando dá. O começo do corte abre.
  3. 🎞 RENDERIZA quadro a quadro (OpenCV), movimento suave (mola amortecida, sem tremedeira), pulo seco no corte de cena.
  4. Devolve os RASTROS (caixas no vídeo vertical) — o círculo do destaque segue a bola certa — e os EVENTOS (lançamento,
     chegada na cesta) pros efeitos sonoros.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

Caixa = Tuple[float, float, float, float]  # x0, y0, x1, y1 em fração (0..1) do quadro original
Prog = Callable[[str], None]
SAIDA_W, SAIDA_H = 1080, 1920
FPS = 30


# ---------------------------------------------------------------------------------------------------- caixas
def _uniao(a: Optional[Caixa], b: Optional[Caixa]) -> Optional[Caixa]:
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _centro(c: Caixa) -> Tuple[float, float]:
    return (c[0] + c[2]) / 2, (c[1] + c[3]) / 2


def _crescer(c: Caixa, f: float) -> Caixa:
    cx, cy = _centro(c)
    w, h = (c[2] - c[0]) * f / 2, (c[3] - c[1]) * f / 2
    return (cx - w, cy - h, cx + w, cy + h)


def _toca(a: Caixa, b: Caixa) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _plano_de(t: float, cortes: Sequence[float]) -> int:
    return sum(1 for c in cortes if c <= t)


# ---------------------------------------------------------------------------------------------------- 1. detectar
def extrair_quadros(video: str, destino: str, fps: float = 2.0, largura: int = 640, ini: float = 0.0, dur: Optional[float] = None) -> List[Tuple[float, str]]:
    """Quadros a `fps` (uma passada só do ffmpeg) → [(t, arquivo)]."""
    os.makedirs(destino, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if ini:
        cmd += ["-ss", f"{ini:.3f}"]
    cmd += ["-i", video]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-vf", f"fps={fps},scale={largura}:-2", "-q:v", "3", os.path.join(destino, "q%05d.jpg")]
    subprocess.run(cmd, capture_output=True, timeout=1800)
    nomes = sorted(n for n in os.listdir(destino) if n.startswith("q") and n.endswith(".jpg"))
    return [(round(ini + k / fps, 3), os.path.join(destino, n)) for k, n in enumerate(nomes)]


def _melhor(caixas: List[Caixa], antes: Optional[Caixa]) -> Optional[Caixa]:
    if not caixas:
        return None
    if antes is not None:
        ca = _centro(antes)
        return min(caixas, key=lambda b: math.dist(_centro(b), ca))
    return max(caixas, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))


def detectar(visao: Any, video: str, dur: float, papeis: Dict[str, Any], cortes: Sequence[float], pasta: str,
             prog: Prog = lambda m: None, passo: float = 0.5, max_claude: int = 30, largura: int = 640) -> Dict[str, List[Tuple[float, Optional[Caixa]]]]:
    """{objeto: [(t, caixa | None)]} — `visao.achar(img, objeto)` (lista de caixas; None = não sabe detectar → o Claude acha
    todos os objetos de uma vez em 1-3 quadros por plano via `visao.achar_varios_claude`)."""
    objetos = [o for o in [papeis.get("principal")] + list(papeis.get("acao") or []) + list(papeis.get("destino") or []) if o]
    objetos = list(dict.fromkeys(objetos))
    out: Dict[str, List[Tuple[float, Optional[Caixa]]]] = {o: [] for o in objetos}
    if not objetos:
        return out
    quadros = extrair_quadros(video, os.path.join(pasta, "det"), 1.0 / passo, largura, 0.0, dur)
    sem_detect = False
    ult: Dict[str, Optional[Caixa]] = {o: None for o in objetos}
    for k, (t, img) in enumerate(quadros):
        if k % 15 == 0:
            prog(f"🎯 procurando {', '.join(objetos)} ({k + 1}/{len(quadros)})…")
        for o in objetos:
            cs = visao.achar(img, o)
            if cs is None:
                sem_detect = True
                break
            mesmo_plano = bool(out[o]) and _plano_de(out[o][-1][0], cortes) == _plano_de(t, cortes)
            b = _melhor(cs, ult[o] if mesmo_plano else None)
            out[o].append((t, b))
            if b is not None:
                ult[o] = b
        if sem_detect:
            break
    if sem_detect:
        return detectar_com_claude(visao, video, dur, objetos, cortes, pasta, prog, max_claude)
    # 🏀 a ação andou demais entre duas amostras (bola em voo): procura de novo no meio, a 8 quadros/s
    for o in papeis.get("acao") or []:
        pts = out.get(o) or []
        extra: List[Tuple[float, Optional[Caixa]]] = []
        for (ta, a), (tb, b) in zip(pts, pts[1:]):
            if a is None or b is None or _plano_de(ta, cortes) != _plano_de(tb, cortes):
                continue
            if math.dist(_centro(a), _centro(b)) < 0.12:
                continue
            for q_t, q_img in extrair_quadros(video, os.path.join(pasta, f"fino_{o[:8]}_{int(ta * 100)}"), 8.0, largura, ta + 0.125, tb - ta - 0.1):
                cs = visao.achar(q_img, o)
                extra.append((q_t, _melhor(cs or [], a)))
        if extra:
            out[o] = sorted(pts + extra, key=lambda x: x[0])
    return out


def detectar_rapido(visao: Any, video: str, dur: float, papeis: Dict[str, Any], cortes: Sequence[float], pasta: str,
                    prog: Prog = lambda m: None, passo: float = 0.5, largura: int = 960, gpu: bool = True) -> Dict[str, List[Tuple[float, Optional[Caixa]]]]:
    """⚡ Poucas buscas do Moondream (a parte cara), interpoladas entre elas:
         principal a cada 1 s (CPU 2 s) · ação a cada 0,5 s (CPU 1 s) · destino (cesta/gol, quase parado) a cada 3 s.
    Antes eram ~2-9 buscas por segundo de vídeo; agora ~1-3,5. Onde o Moondream diz que o objeto NÃO está, o rastro some."""
    principal = papeis.get("principal")
    acoes = list(dict.fromkeys(o for o in papeis.get("acao") or [] if o))
    destinos = list(dict.fromkeys(o for o in papeis.get("destino") or [] if o and o not in acoes))
    ritmo = {}
    if principal:
        ritmo[principal] = 1.0 if gpu else 2.0
    for o in acoes:
        ritmo[o] = 0.5 if gpu else 1.0
    for o in destinos:
        ritmo.setdefault(o, 3.0)
    if not ritmo:
        return {}
    menor = min(ritmo.values())
    quadros = extrair_quadros(video, os.path.join(pasta, "det"), 1.0 / menor, largura, 0.0, dur)
    chaves: Dict[str, List[Tuple[float, Optional[Caixa]]]] = {o: [] for o in ritmo}
    total = sum(1 for t, _ in quadros for o, r in ritmo.items() if abs((t / r) - round(t / r)) < 1e-3)
    feitas = 0
    for t, img in quadros:
        for o, r in ritmo.items():
            if abs((t / r) - round(t / r)) > 1e-3:
                continue
            feitas += 1
            if feitas % 10 == 1:
                prog(f"🎯 Moondream: {feitas}/{total} buscas ({', '.join(ritmo)})…")
            cs = visao.achar(img, o)
            if cs is None:  # este 👁 não detecta → o Claude faz tudo
                return detectar_com_claude(visao, video, dur, list(ritmo), cortes, pasta, prog)
            ant = next((c for tt, c in reversed(chaves[o]) if c is not None and _plano_de(tt, cortes) == _plano_de(t, cortes)), None)
            chaves[o].append((t, _melhor(cs, ant)))
    amostras = [round(k * passo, 3) for k in range(int(dur / passo) + 1)]
    # entre as buscas: interpolação (a câmera é suavizada de qualquer jeito; o rastreio fino fica pro círculo do destaque, que
    # já usa o rastreador do OpenCV só no pedaço que precisa)
    return {o: [(t, caixa_em(ks, t, cortes, max_gap=ritmo[o] * 1.6)) for t in amostras] for o, ks in chaves.items()}


def detectar_com_claude(visao: Any, video: str, dur: float, objetos: List[str], cortes: Sequence[float], pasta: str,
                        prog: Prog, max_chamadas: int = 30) -> Dict[str, List[Tuple[float, Optional[Caixa]]]]:
    out: Dict[str, List[Tuple[float, Optional[Caixa]]]] = {o: [] for o in objetos}
    planos = [0.0] + [c for c in cortes if 0 < c < dur] + [dur]
    tempos: List[float] = []
    for a, b in zip(planos, planos[1:]):
        n = 1 if b - a < 2.5 else 2 if b - a < 6 else 3
        tempos += [a + (b - a) * (k + 0.5) / n for k in range(n)]
    tempos = tempos[:max_chamadas]
    prog(f"🎯 o Claude está achando {', '.join(objetos)} em {len(tempos)} quadros…")
    for k, t in enumerate(tempos):
        d = os.path.join(pasta, f"cl{k}")
        q = extrair_quadros(video, d, 1.0, 768, t, 0.05)
        achados = visao.achar_varios_claude(q[0][1], objetos) if q else {}
        for o in objetos:
            out[o].append((t, (achados or {}).get(o)))
    return out


def caixa_em(pts: Sequence[Tuple[float, Optional[Caixa]]], t: float, cortes: Sequence[float], max_gap: float = 1.2) -> Optional[Caixa]:
    """A caixa do objeto no tempo t (interpola entre as amostras vizinhas do MESMO plano)."""
    antes = depois = None
    for tt, c in pts:
        if c is None or _plano_de(tt, cortes) != _plano_de(t, cortes):
            continue
        if tt <= t:
            antes = (tt, c)
        elif depois is None:
            depois = (tt, c)
            break
    if antes and depois and depois[0] - antes[0] <= max_gap:
        f = (t - antes[0]) / max(1e-6, depois[0] - antes[0])
        return tuple(a + (b - a) * f for a, b in zip(antes[1], depois[1]))  # type: ignore[return-value]
    for x in (antes, depois):
        if x and abs(x[0] - t) <= max_gap * 0.5:
            return x[1]
    return None


def velocidade(pts: Sequence[Tuple[float, Optional[Caixa]]], t: float, cortes: Sequence[float], dt: float = 0.25) -> float:
    a, b = caixa_em(pts, t - dt, cortes), caixa_em(pts, t + dt, cortes)
    if a is None or b is None or _plano_de(t - dt, cortes) != _plano_de(t + dt, cortes):
        return 0.0
    return math.dist(_centro(a), _centro(b)) / (2 * dt)


def limpar_saltos(pts: List[Tuple[float, Optional[Caixa]]], cortes: Sequence[float], salto: float = 0.28) -> List[Tuple[float, Optional[Caixa]]]:
    """Detecção que PULA pra longe e volta (o detector confundiu com outra coisa por um quadro) vira 'não achou'."""
    out = list(pts)
    for i in range(1, len(out) - 1):
        (ta, a), (t, b), (tc, c) = out[i - 1], out[i], out[i + 1]
        if a is None or b is None or c is None:
            continue
        if not (_plano_de(ta, cortes) == _plano_de(t, cortes) == _plano_de(tc, cortes)):
            continue
        if math.dist(_centro(a), _centro(b)) > salto and math.dist(_centro(c), _centro(b)) > salto and math.dist(_centro(a), _centro(c)) < salto:
            out[i] = (t, None)
    return out


def analisar(visao: Any, video: str, dur: float, papeis: Dict[str, Any], cortes: Sequence[float], prog: Prog = lambda m: None,
             passo: float = 0.5) -> Dict[str, Any]:
    """🗺 O MAPA de objetos do clipe (deitado): onde cada um está a cada `passo` s + os eventos (lançamento, chegada).
    → {"tracks": {obj: [[t, x0, y0, x1, y1] | [t, None]]}, "eventos": [...], "visivel": {obj: [[t0, t1], ...]}}"""
    pasta = tempfile.mkdtemp(prefix="mapa_")
    try:
        if getattr(visao, "rapido", True):
            tracks = detectar_rapido(visao, video, dur, papeis, cortes, pasta, prog, passo=0.5, largura=960,
                                     gpu=bool(getattr(visao, "gpu", True)))
        else:
            tracks = detectar(visao, video, dur, papeis, cortes, pasta, prog, passo=passo, largura=960)
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    principal = papeis.get("principal")
    if principal in tracks:
        tracks[principal] = limpar_saltos(tracks[principal], cortes)
    plano = planejar(tracks, papeis, dur, cortes, 1920, 1080)
    return {"tracks": {o: [[t, *c] if c else [t, None] for t, c in pts] for o, pts in tracks.items()},
            "eventos": plano["eventos"], "visivel": {o: janelas_visiveis(pts) for o, pts in tracks.items()}}


def janelas_visiveis(pts: Sequence[Tuple[float, Optional[Caixa]]], folga: float = 1.1) -> List[List[float]]:
    out: List[List[float]] = []
    for t, c in pts:
        if c is None:
            continue
        if out and t - out[-1][1] <= folga:
            out[-1][1] = t
        else:
            out.append([t, t])
    return [[round(a, 1), round(b, 1)] for a, b in out]


def tracks_do_mapa(mapa_tracks: Dict[str, Any]) -> Dict[str, List[Tuple[float, Optional[Caixa]]]]:
    return {o: [(float(x[0]), tuple(x[1:5]) if len(x) >= 5 and x[1] is not None else None) for x in pts]  # type: ignore[misc]
            for o, pts in (mapa_tracks or {}).items()}


def enquadrar_pedaco(video: str, ini: float, fim: float, saida: str, mapa_tracks: Dict[str, Any], foco: str, principal: str,
                     cortes: Sequence[float], prog: Prog = lambda m: None, acao: Sequence[str] = (), destino: Sequence[str] = (),
                     abrir_inicio: bool = False) -> Dict[str, Any]:
    """🎥 Um pedaço [ini, fim] do clipe DEITADO vira vertical focando `foco` (o objeto da fala); onde o foco não aparece, o
    principal; onde nada aparece, a câmera fica parada onde estava. Usa o mapa já feito (não detecta de novo)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                        video], capture_output=True, text=True, timeout=60)
    w0, h0 = (int(v) for v in r.stdout.strip().split(",")[:2])
    escala = min(1.0, 1920 / w0)
    W, H = int(w0 * escala) // 2 * 2, int(h0 * escala) // 2 * 2
    dur = max(0.1, fim - ini)
    todos = tracks_do_mapa(mapa_tracks)
    perto = {o: [(t - ini, c) for t, c in pts if ini - 2.0 <= t <= fim + 2.0] for o, pts in todos.items()}
    cortes_p = [c - ini for c in cortes if ini < c < fim]
    tem = lambda o: any(c is not None and 0 <= t <= dur for t, c in perto.get(o) or [])  # noqa: E731
    alvo = foco if foco and tem(foco) else principal if principal and tem(principal) else ""
    seguir_ = {"alvo": perto.get(alvo) or []}
    if alvo and alvo != principal and principal:  # foco some no meio do pedaço → o principal cobre o buraco
        pp = perto.get(principal) or []
        seguir_["alvo"] = [(t, c if c is not None else caixa_em(pp, t, cortes_p, 0.8)) for t, c in seguir_["alvo"]]
    for o in list(acao) + list(destino):  # modo automático (sem roteiro): a bola em voo ainda rouba a câmera
        if o in perto:
            seguir_[o] = perto[o]
    plano = planejar(seguir_, {"principal": "alvo", "acao": [o for o in acao if o in perto], "destino": [o for o in destino if o in perto]},
                     dur, cortes_p, W, H, abrir_inicio=abrir_inicio)
    caminho = suavizar(plano["alvos"], cortes_p, W, H, FPS, dur)
    renderizar(video, ini, fim, saida, caminho, W, H, prog)
    visiveis = {o: pts for o, pts in perto.items()}
    return {"rastros": rastros_no_vertical(visiveis, caminho, W, H), "foco": alvo, "eventos": plano["eventos"]}


# ---------------------------------------------------------------------------------------------------- 2. planejar
def planejar(tracks: Dict[str, List[Tuple[float, Optional[Caixa]]]], papeis: Dict[str, Any], dur: float, cortes: Sequence[float],
             W: int, H: int, abrir_inicio: bool = True, passo: float = 0.1, sem_barras: bool = True,
             segurar: bool = True) -> Dict[str, Any]:
    """→ {"alvos": [(t, cx, cy, vw)] (px do original, sem suavizar), "eventos": [...], "foco": [(t, nome)]}.
    sem_barras (padrão): o vertical SEMPRE preenche a tela — o zoom fecha quando dá, mas nunca abre além da altura inteira do
    vídeo; pra mostrar o que importa a câmera ANDA (pra frente/pra trás) em vez de abrir com barras."""
    cw = H * SAIDA_W / SAIDA_H  # a largura de um vertical que usa a altura inteira
    vw_min, vw_max = cw * 0.62, (min(float(W), cw) if sem_barras else float(W))
    principal = papeis.get("principal")
    acoes = [o for o in papeis.get("acao") or [] if o in tracks]
    destinos = [o for o in papeis.get("destino") or [] if o in tracks]
    alvos: List[Tuple[float, float, float, float]] = []
    eventos: List[Dict[str, Any]] = []
    foco_log: List[Tuple[float, str]] = []
    ultimo_reg: Optional[Caixa] = None
    acao_ativa_ate = -1.0
    ultimo_rapido: Dict[str, float] = {}
    em_voo = False
    chegou = False
    t = 0.0
    while t <= dur + 1e-6:
        P = caixa_em(tracks.get(principal) or [], t, cortes) if principal else None
        reg: Optional[Caixa] = None
        obrig: Optional[Caixa] = None  # o que NÃO pode sair do quadro (a bola em voo; senão o principal)
        nome = "principal"
        ativa = None
        for o in acoes:
            A = caixa_em(tracks[o], t, cortes)
            if A is None:
                continue
            longe = P is not None and not _toca(A, _crescer(P, 1.25))
            rapida = velocidade(tracks[o], t, cortes) > 0.35
            if rapida:
                ultimo_rapido[o] = t
            # a ação só rouba a câmera ENQUANTO anda (e um instante depois); parada longe do principal, a câmera volta
            if rapida or t < acao_ativa_ate or (longe and t - ultimo_rapido.get(o, -9) < 0.8):
                ativa = (o, A)
                break
        if ativa:
            o, A = ativa
            if not em_voo:
                eventos.append({"t": round(t, 2), "tipo": "lancamento", "objeto": o})
                em_voo, chegou = True, False
            if rapida:
                acao_ativa_ate = max(acao_ativa_ate, t + 0.5)  # segura a câmera na bola um pouco depois (até ela cair/entrar)
            reg, nome, obrig = A, o, A
            for dn in destinos:
                D = caixa_em(tracks[dn], t, cortes)
                if D is None:
                    continue
                if math.dist(_centro(A), _centro(D)) < 0.45:  # bola indo pra cesta: mostra as DUAS
                    reg = _uniao(reg, D)
                    nome = f"{o} + {dn}"
                    if _toca(_crescer(A, 1.1), D) and not chegou:
                        eventos.append({"t": round(t, 2), "tipo": "chegada", "objeto": dn})
                        chegou = True
                        acao_ativa_ate = t + 0.8  # mostra a cesta um instante antes de voltar
        else:
            em_voo = False
            reg = obrig = P
            for o in acoes:  # a bola na mão do robô entra no quadro junto
                A = caixa_em(tracks[o], t, cortes)
                if A is not None and P is not None and _toca(A, _crescer(P, 1.4)):
                    reg = _uniao(reg, A)
        if reg is None and segurar:  # sumiu da detecção: a câmera FICA onde estava (não sai passeando pela torcida)
            reg = ultimo_reg
        elif reg is None:
            reg = ultimo_reg if ultimo_reg is not None and _plano_de(t, cortes) == _plano_de(max(0.0, t - passo), cortes) else None
        if reg is None:
            cx, cy, vw = W / 2, H / 2, cw
            nome = "meio"
        else:
            ultimo_reg = reg
            rx0, ry0, rx1, ry1 = reg[0] * W, reg[1] * H, reg[2] * W, reg[3] * H
            cx, cy = (rx0 + rx1) / 2, (ry0 + ry1) / 2
            precisa_w = (rx1 - rx0) * 1.45
            precisa_h = (ry1 - ry0) * 1.30
            vw = max(precisa_w, precisa_h * SAIDA_W / SAIDA_H, vw_min)
        vw = min(vw_max, vw)
        if abrir_inicio and t < 1.4:  # 🎬 o corte começa ABERTO (o mais aberto que dá) e entra no assunto
            f = max(0.0, 1 - t / 1.4)
            vw = vw + (min(vw_max, max(vw, W * 0.95)) - vw) * f
        if obrig is not None and reg is not None and (reg[2] - reg[0]) * W > vw * 0.9:
            # não cabe tudo (bola + cesta mais largas que a tela): a câmera fica entre os dois, mas a bola nunca sai do quadro
            m = vw * 0.08
            ox0, ox1 = obrig[0] * W, obrig[2] * W
            lo, hi = ox1 - vw / 2 + m, ox0 + vw / 2 - m
            if lo <= hi:
                cx = min(max(cx, lo), hi)
        alvos.append((round(t, 3), cx, cy, vw))
        foco_log.append((round(t, 3), nome))
        t += passo
    return {"alvos": alvos, "eventos": eventos, "foco": foco_log}


def suavizar(alvos: Sequence[Tuple[float, float, float, float]], cortes: Sequence[float], W: int, H: int, fps: float = FPS,
             dur: Optional[float] = None) -> List[Tuple[float, float, float, float]]:
    """Mola amortecida (sem tremer, sem atrasar demais) a `fps`; zona morta pequena; pulo seco nos cortes de cena."""
    if not alvos:
        return []
    dur = dur if dur is not None else alvos[-1][0]
    n = int(math.ceil(dur * fps))
    out: List[Tuple[float, float, float, float]] = []
    j = 0
    x = y = z = None
    vx = vy = vz = 0.0
    plano = -1
    dt = 1.0 / fps
    for i in range(n):
        t = i * dt
        while j + 1 < len(alvos) and alvos[j + 1][0] <= t:
            j += 1
        a = alvos[j]
        if j + 1 < len(alvos):  # interpola entre as amostras do plano
            b = alvos[j + 1]
            f = (t - a[0]) / max(1e-6, b[0] - a[0])
            tx, ty, tz = (a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f)
        else:
            tx, ty, tz = a[1], a[2], a[3]
        p = _plano_de(t, cortes)
        if x is None or p != plano:  # corte de cena: a câmera pula junto
            x, y, z, vx, vy, vz, plano = tx, ty, tz, 0.0, 0.0, 0.0, p
        else:
            for eixo, alvo_, k_, zona in (("x", tx, 9.0, z * 0.03), ("y", ty, 9.0, z * 0.03), ("z", tz, 5.0, z * 0.02)):
                pos = {"x": x, "y": y, "z": z}[eixo]
                vel = {"x": vx, "y": vy, "z": vz}[eixo]
                erro = alvo_ - pos
                if abs(erro) < zona:
                    erro = 0.0
                acc = k_ * k_ * erro - 2 * k_ * vel  # amortecimento crítico
                vel += acc * dt
                pos += vel * dt
                if eixo == "x":
                    x, vx = pos, vel
                elif eixo == "y":
                    y, vy = pos, vel
                else:
                    z, vz = pos, vel
        out.append((round(t, 4), x, y, z))
    return out


def retangulo(cx: float, cy: float, vw: float, W: int, H: int) -> Tuple[float, float, float, float, bool]:
    """(x, y, w, h, aberto) do pedaço do original que aparece. aberto=True → o pedaço é mais largo que um vertical da altura
    inteira: entra no meio, com o próprio vídeo desfocado atrás."""
    vw = max(16.0, min(float(W), vw))
    vh = vw * SAIDA_H / SAIDA_W
    if vh <= H:
        x = min(max(0.0, cx - vw / 2), W - vw)
        y = min(max(0.0, cy - vh / 2), H - vh)
        return x, y, vw, vh, False
    x = min(max(0.0, cx - vw / 2), W - vw)
    return x, 0.0, vw, float(H), True


# ---------------------------------------------------------------------------------------------------- 3. renderizar
def renderizar(video: str, t0: float, t1: float, saida: str, caminho: Sequence[Tuple[float, float, float, float]], W: int, H: int,
               prog: Prog = lambda m: None, fps: int = FPS) -> str:
    """Lê o trecho [t0, t1] do vídeo original e escreve o vertical 1080x1920 seguindo o `caminho` (px no tamanho W×H)."""
    import numpy as np
    import cv2
    dur = t1 - t0
    ler = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-i", video, "-t", f"{dur:.3f}", "-vf", f"scale={W}:{H},fps={fps}",
                            "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    os.makedirs(os.path.dirname(saida) or ".", exist_ok=True)
    tmp_v = saida + ".v.mp4"
    escrever = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{SAIDA_W}x{SAIDA_H}",
                                 "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                                 tmp_v], stdin=subprocess.PIPE)
    tam = W * H * 3
    i = 0
    try:
        while True:
            buf = ler.stdout.read(tam)  # type: ignore[union-attr]
            if len(buf) < tam:
                break
            q = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
            cx, cy, vw = (caminho[min(i, len(caminho) - 1)][1:] if caminho else (W / 2, H / 2, H * SAIDA_W / SAIDA_H))
            x, y, w, h, aberto = retangulo(cx, cy, vw, W, H)
            xi, yi, wi, hi = int(round(x)), int(round(y)), max(2, int(round(w))), max(2, int(round(h)))
            wi, hi = min(wi, W - xi), min(hi, H - yi)
            pedaco = q[yi:yi + hi, xi:xi + wi]
            if not aberto:
                quadro = cv2.resize(pedaco, (SAIDA_W, SAIDA_H), interpolation=cv2.INTER_AREA if wi > SAIDA_W else cv2.INTER_CUBIC)
            else:
                fundo = _fundo_desfocado(q, cv2, np)
                fh = int(round(SAIDA_W * hi / wi))
                frente = cv2.resize(pedaco, (SAIDA_W, fh), interpolation=cv2.INTER_AREA)
                quadro = fundo
                y0 = (SAIDA_H - fh) // 2
                quadro[y0:y0 + fh] = frente
            escrever.stdin.write(quadro.tobytes())  # type: ignore[union-attr]
            i += 1
            if i % (fps * 5) == 0:
                prog(f"🎞 câmera virtual: {i / fps:.0f}/{dur:.0f} s")
    finally:
        try:
            escrever.stdin.close()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
        escrever.wait()
        ler.kill()
        ler.wait()
    if not os.path.isfile(tmp_v):
        raise RuntimeError("a câmera virtual não gerou o vídeo")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp_v, "-ss", f"{t0:.3f}", "-t", f"{dur:.3f}", "-i", video,
                        "-map", "0:v", "-map", "1:a?", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", saida],
                       capture_output=True, text=True, timeout=1800)
    os.remove(tmp_v)
    if r.returncode != 0 or not os.path.isfile(saida):
        raise RuntimeError("não consegui juntar o áudio: " + (r.stderr or "")[-300:])
    return saida


def _fundo_desfocado(q, cv2, np):
    h, w = q.shape[:2]
    escala = max(SAIDA_W / 4 / w, SAIDA_H / 4 / h)
    peq = cv2.resize(q, (max(2, int(w * escala)), max(2, int(h * escala))), interpolation=cv2.INTER_AREA)
    ph, pw = peq.shape[:2]
    x0, y0 = (pw - SAIDA_W // 4) // 2, (ph - SAIDA_H // 4) // 2
    peq = peq[max(0, y0):max(0, y0) + SAIDA_H // 4, max(0, x0):max(0, x0) + SAIDA_W // 4]
    peq = cv2.GaussianBlur(peq, (0, 0), 6)
    fundo = cv2.resize(peq, (SAIDA_W, SAIDA_H), interpolation=cv2.INTER_LINEAR)
    return (fundo * 0.55).astype(np.uint8)


# ---------------------------------------------------------------------------------------------------- 4. rastros no vertical
def rastros_no_vertical(tracks: Dict[str, List[Tuple[float, Optional[Caixa]]]], caminho: Sequence[Tuple[float, float, float, float]],
                        W: int, H: int, fps: int = FPS) -> Dict[str, List[List[float]]]:
    """As caixas de cada objeto em px do vídeo VERTICAL (1080x1920) — o círculo do destaque usa elas."""
    out: Dict[str, List[List[float]]] = {}
    for nome, pts in tracks.items():
        lst = []
        for t, c in pts:
            if c is None or not caminho:
                continue
            cx, cy, vw = caminho[min(len(caminho) - 1, int(round(t * fps)))][1:]
            x, y, w, h, aberto = retangulo(cx, cy, vw, W, H)
            esc = SAIDA_W / w
            oy = (SAIDA_H - h * esc) / 2 if aberto else 0.0
            bx0, by0 = (c[0] * W - x) * esc, (c[1] * H - y) * esc + oy
            bx1, by1 = (c[2] * W - x) * esc, (c[3] * H - y) * esc + oy
            if bx1 <= 0 or by1 <= 0 or bx0 >= SAIDA_W or by0 >= SAIDA_H:
                continue  # fora do quadro vertical nesse instante
            bx0, by0, bx1, by1 = max(0.0, bx0), max(0.0, by0), min(SAIDA_W, bx1), min(SAIDA_H, by1)
            lst.append([round(t, 3), round(bx0, 1), round(by0, 1), round(bx1 - bx0, 1), round(by1 - by0, 1)])
        if lst:
            out[nome] = lst
    return out


def seguir(visao: Any, video_cru: str, video_original: str, t0: float, t1: float, saida: str, papeis: Dict[str, Any],
           cortes: Sequence[float], prog: Prog = lambda m: None, passo: float = 0.5) -> Dict[str, Any]:
    """Tudo: detecta no `video_cru` (o trecho já recortado, leve) → planeja → renderiza do `video_original` (qualidade cheia)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                        video_original], capture_output=True, text=True, timeout=60)
    w0, h0 = (int(v) for v in r.stdout.strip().split(",")[:2])
    escala = min(1.0, 1920 / w0)
    W, H = int(w0 * escala) // 2 * 2, int(h0 * escala) // 2 * 2
    dur = t1 - t0
    pasta = tempfile.mkdtemp(prefix="cam_")
    try:
        tracks = detectar(visao, video_cru, dur, papeis, cortes, pasta, prog, passo=passo)
        if papeis.get("principal") in tracks:
            tracks[papeis["principal"]] = limpar_saltos(tracks[papeis["principal"]], cortes)
        plano = planejar(tracks, papeis, dur, cortes, W, H)
        caminho = suavizar(plano["alvos"], cortes, W, H, FPS, dur)
        renderizar(video_original, t0, t1, saida, caminho, W, H, prog)
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    achados = {o: sum(1 for _, c in pts if c is not None) for o, pts in tracks.items()}
    focos = {}
    for _, nome in plano["foco"]:
        focos[nome] = focos.get(nome, 0) + 1
    return {"rastros": rastros_no_vertical(tracks, caminho, W, H), "eventos": plano["eventos"], "achados": achados,
            "foco": {k: round(v * 0.1, 1) for k, v in focos.items()}}
