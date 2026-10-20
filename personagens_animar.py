"""
personagens_animar.py — 🎞 personagem que se mexe (v84_193)
=============================================================

A personagem por cima do vídeo não fica mais parada: cada POSE pode ganhar um clipe animado no Google Flow e o
editor guarda o clipe pra REUSAR em qualquer vídeo.

  • v84_205: o Flow NÃO faz vídeo — faz UM quadro intermediário (foto com a pose de referência: a mesma pose um
    instante depois, boca aberta / piscando); aqui ele é recortado igual às poses e ALTERNA com a pose em loop (com
    uma fusão curta) → sensação de movimento, como desenho animado com poucos quadros, entra e sai sem pulo;
  • dois tipos: "fala" (ela fala, a boca mexe — no lugar do 👄 pisca-boca) e "parada" (respira, pisca, mexe pouco);
  • o verde sai aqui no PC (a mesma chave/limpeza das poses), quadro a quadro → WebM com transparência;
  • a biblioteca fica no projeto da personagem (personagens_pod/<id>/animacoes/): a mesma pose + tipo nunca vai pro
    Flow duas vezes — pronta, entra em toda aparição dessa pose;
  • quem escolhe: a 🤖 IA (no "Colocar automaticamente", marca as aparições que mais ganham com movimento) ou você
    (🎞 Animar na aparição); "só uns frames" = usa só os primeiros N s do clipe, vai e volta (termina na pose).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

TIPOS = ("fala", "parada")
MODOS = ("repetir", "uma_vez")
ESPERA = ("fila", "gerando", "processando")
_TRAVA = threading.RLock()


class AnimErro(Exception):
    pass


# ------------------------------------------------------------------ biblioteca (por projeto da personagem)
def pasta(pid: str, base: str) -> str:
    import personagens_pod as pp
    return os.path.join(pp._pasta(pid, base), "animacoes")


def _indice_path(pid: str, base: str) -> str:
    return os.path.join(pasta(pid, base), "animacoes.json")


def carregar(pid: str, base: str) -> Dict[str, Any]:
    try:
        with open(_indice_path(pid, base), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _salvar(pid: str, base: str, d: Dict[str, Any]) -> None:
    os.makedirs(pasta(pid, base), exist_ok=True)
    tmp = _indice_path(pid, base) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _indice_path(pid, base))


def chave(caminho_png: str, tipo: str) -> str:
    """pose + tipo + o CONTEÚDO da pose (refez a pose → anima de novo)."""
    with open(caminho_png, "rb") as f:
        h = hashlib.sha1(f.read()).hexdigest()[:10]
    nome = re.sub(r"[^\w\-]", "_", os.path.splitext(os.path.basename(caminho_png))[0])[:60]
    return f"{nome}__{tipo}__{h}__q"  # __q = v84_205: quadro intermediário (imagem), não vídeo


# ------------------------------------------------------------------ o pedido pro Flow
def prompt_animacao(nome: str, descricao: str, tipo: str, fala: str = "", extra: str = "") -> str:
    acao = ("talking naturally to the viewer: the mouth opens and closes as if speaking, small expressive head and "
            "hand gestures that match the pose" if tipo == "fala" else
            "idle animation: gentle breathing, one or two natural blinks, a slight head tilt and a small hand movement")
    p = (f"Subtle 2D anime character animation of {nome}" + (f" ({descricao})" if descricao else "") + f": {acao}"
         + (f", reacting to the line \"{fala[:120]}\"" if fala and tipo == "fala" else "")
         + ". Keep exactly the same character design, outfit, colors, line art and drawing style as the first frame; "
           "the body stays in the same place and the same size, the camera is completely static (no zoom, no pan, no "
           "cut). The whole background stays a flat solid pure chroma-key green (#00FF00) in every frame, no shadows, "
           "no other objects, no particles, no text. The last frame returns to the same pose as the first frame.")
    if extra:
        p += " " + " ".join(str(extra).split())[:300]
    return p


def frame_verde(png: str, destino: str) -> str:
    """A pose (PNG transparente 2:3) sobre verde puro, 9:16 — o vídeo do Flow é 9:16 (ele CORTAVA a imagem 3:4 pra
    9:16): sobra verde em cima e embaixo, nada da pose é cortado."""
    from PIL import Image
    im = Image.open(png).convert("RGBA")
    w, h = im.size
    H = max(h, int(round(w * 16 / 9)))
    W = max(w, int(round(H * 9 / 16)))
    fundo = Image.new("RGBA", (W, H), (0, 255, 0, 255))
    fundo.alpha_composite(im, ((W - w) // 2, (H - h) // 2))
    rgb = fundo.convert("RGB")
    if rgb.height > 1280:  # 🎞 v84_202: menor e em JPEG — o Flow processa rápido (PNG grande travava a prévia)
        rgb = rgb.resize((int(rgb.width * 1280 / rgb.height), 1280))
    rgb.save(destino, quality=92)
    return destino


def _lote():
    import flow_lote
    return flow_lote.lote()


def prompt_intermediario(nome: str, descricao: str, tipo: str, texto_fixo: Optional[Dict[str, Any]] = None,
                         extra: str = "") -> str:
    """🖼 v84_205: em vez de vídeo, UM quadro intermediário (a mesma pose um instante depois) — alternando com a pose
    dá a sensação de movimento, como um desenho animado com poucos quadros."""
    tf = texto_fixo or {}
    acao = ("mid-word while talking: the mouth clearly OPEN, eyebrows slightly raised, the head tilted a few degrees and "
            "the raised hand moved a little, as the next drawing of a talking animation" if tipo == "fala" else
            "a moment later in a gentle idle motion: eyes half closed in a blink, the head tilted a few degrees, the "
            "shoulders slightly raised by a breath and the hand moved a little")
    partes = [str(tf.get("trava") or ""), str(tf.get("estilo") or ""),
              f"IN-BETWEEN ANIMATION FRAME of {nome}" + (f" ({descricao})" if descricao else "") + ": the reference "
              f"image is frame 1; draw frame 2 of the same shot — {acao}. Everything else IDENTICAL to the reference: same "
              "character, same outfit, same pose and body position, same size, same framing and same place in the image, "
              "same line art and colors. Only that small change. Plain flat solid chroma-key green background (#00FF00), "
              "no text, no extra objects.",
              str(tf.get("regras") or "")]
    if extra:
        partes.append(" ".join(str(extra).split())[:300])
    return " ".join(x.strip() for x in partes if x and x.strip())[:3900]


def frame_verde_34(png: str, destino: str) -> str:
    """A pose sobre verde puro em 3:4 (o formato das fotos do Flow; as poses também nascem assim)."""
    from PIL import Image
    im = Image.open(png).convert("RGBA")
    w, h = im.size
    W = max(w, int(round(h * 3 / 4)))
    fundo = Image.new("RGBA", (W, h), (0, 255, 0, 255))
    fundo.alpha_composite(im, ((W - w) // 2, 0))
    rgb = fundo.convert("RGB")
    if rgb.height > 1280:
        rgb = rgb.resize((int(rgb.width * 1280 / rgb.height), 1280))
    rgb.save(destino, quality=92)
    return destino


def pedir(base: str, pid: str, pose: Dict[str, Any], tipo: str = "fala", nome: str = "", fala: str = "",
          extra: str = "", refazer: bool = False) -> Dict[str, Any]:
    """Põe a animação desta pose na fila do Flow (se ainda não existe/está vindo). → o item da biblioteca."""
    tipo = tipo if tipo in TIPOS else "fala"
    if not pose.get("caminho") or not os.path.isfile(pose["caminho"]):
        raise AnimErro("A imagem da pose não existe mais.")
    k = chave(pose["caminho"], tipo)
    with _TRAVA:
        d = carregar(pid, base)
        it = d.get(k)
        if it and not refazer and (it.get("estado") in ESPERA or (it.get("estado") == "pronto" and os.path.isfile(str(it.get("webm"))))):
            return dict(it, chave=k)
        os.makedirs(pasta(pid, base), exist_ok=True)
        fr = frame_verde_34(pose["caminho"], os.path.join(pasta(pid, base), f"{k}_ref.jpg"))
        try:
            import personagens_pod as pp
            tf = (pp.carregar(pid, base).get("dados") or {}).get("texto_fixo") or {}
        except Exception:  # noqa: BLE001
            tf = {}
        p = prompt_intermediario(nome or "the character", pose.get("descricao") or "", tipo, tf, extra)
        j = _lote().adicionar([{"prompt": p, "tipo": "imagem", "referencia_arquivo": fr, "origem": "personagem"}],
                              proporcao="3:4")[0]
        it = {"estado": "fila", "flow_job": j["id"], "prompt": p, "pose": pose.get("arquivo") or os.path.basename(pose["caminho"]),
              "tipo": tipo, "frame": fr, "pose_png": pose["caminho"], "criado": time.time(), "erro": None,
              "msg": "na fila do Flow (quadro intermediário)"}
        d[k] = it
        _salvar(pid, base, d)
    try:
        _lote().iniciar()
    except Exception as exc:  # noqa: BLE001 — Flow ocupado: fica na fila
        it["msg"] = f"na fila (o Flow em massa não ligou agora: {str(exc)[:120]})"
    return dict(it, chave=k)


# ------------------------------------------------------------------ o clipe verde → WebM transparente
def processar(video: str, destino: str, opcoes: Optional[Dict[str, Any]] = None, fps: int = 24) -> Dict[str, Any]:
    """Tira o verde quadro a quadro (a mesma limpeza das poses), corta de volta pro 2:3 da pose e grava WebM VP9 com
    alfa. → {"webm", "duracao", "quadros"}."""
    from PIL import Image
    import personagens_limpeza as L
    o = dict(opcoes or {})
    o["fundo"] = "verde"
    o.setdefault("ilhas", True)
    tmp = tempfile.mkdtemp(prefix="pers_anim_")
    try:
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-an", "-vf",
                            f"fps={fps},crop='min(iw,ih*2/3)':'min(ih,iw*3/2)'", os.path.join(tmp, "q_%05d.png")],
                           capture_output=True, text=True, timeout=600)
        quadros = sorted(x for x in os.listdir(tmp) if x.startswith("q_"))
        if r.returncode != 0 or not quadros:
            raise AnimErro(f"não consegui ler o vídeo do Flow: {(r.stderr or '')[-200:]}")
        for q in quadros:
            img = Image.open(os.path.join(tmp, q)).convert("RGB")
            limpo, alfa, _f = L.limpar(img, L.alfa_do_verde(img), o)
            rgba = limpo.convert("RGBA")
            rgba.putalpha(alfa)
            rgba.save(os.path.join(tmp, "a" + q[1:]))
        # 🔁 v84_203: sem frame de Fim no Flow (travava): o clipe vai e VOLTA — começa e termina na pose, loop sem pulo
        n = len(quadros)
        for k, q in enumerate(reversed(quadros[1:-1]), start=n + 1):
            shutil.copyfile(os.path.join(tmp, "a" + q[1:]), os.path.join(tmp, f"a_{k:05d}.png"))
        total = n + max(0, n - 2)
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(tmp, "a_%05d.png"),
                            "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "30", "-auto-alt-ref", "0",
                            "-row-mt", "1", "-deadline", "good", "-cpu-used", "4", destino],
                           capture_output=True, text=True, timeout=900)
        if r.returncode != 0 or not os.path.isfile(destino):
            raise AnimErro(f"não consegui gravar o WebM transparente: {(r.stderr or '')[-200:]}")
        return {"webm": destino, "duracao": round(total / fps, 3), "quadros": total}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def montar_loop(pose_png: str, quadro2: str, destino: str, tipo: str = "fala", fps: int = 24) -> Dict[str, Any]:
    """Pose ↔ quadro intermediário em loop (com uma fusão curta entre eles) → WebM transparente. "fala" alterna rápido
    (a boca abre e fecha); "parada" fica mais tempo na pose (respira/pisca de vez em quando)."""
    from PIL import Image
    a = Image.open(pose_png).convert("RGBA")
    b = Image.open(quadro2).convert("RGBA")
    if b.size != a.size:
        b = b.resize(a.size)
    if a.width > 720:  # menor: o overlay nunca passa de ~1/3 da tela
        a = a.resize((720, int(a.height * 720 / a.width)))
        b = b.resize(a.size)
    seg = [(a, 5), ("ab", 2), (b, 5), ("ba", 2)] if tipo == "fala" else [(a, 30), ("ab", 4), (b, 12), ("ba", 4)]
    tmp = tempfile.mkdtemp(prefix="pers_loop_")
    try:
        n = 0
        for item, qtd in seg:
            for i in range(qtd):
                if item == "ab":
                    q = Image.blend(a, b, (i + 1) / (qtd + 1))
                elif item == "ba":
                    q = Image.blend(b, a, (i + 1) / (qtd + 1))
                else:
                    q = item
                n += 1
                q.save(os.path.join(tmp, f"a_{n:05d}.png"))
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(tmp, "a_%05d.png"),
                            "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "30", "-auto-alt-ref", "0",
                            "-row-mt", "1", destino], capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not os.path.isfile(destino):
            raise AnimErro(f"não consegui gravar o WebM transparente: {(r.stderr or '')[-200:]}")
        return {"webm": destino, "duracao": round(n / fps, 3), "quadros": n}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def sincronizar(pid: str, base: str) -> Dict[str, Any]:
    """Olha a fila do Flow: clipe pronto → baixa, tira o verde, guarda. → o índice atualizado."""
    with _TRAVA:
        d = carregar(pid, base)
        esperando = {k: it for k, it in d.items() if it.get("estado") in ("fila", "gerando")}
        if not esperando:
            return d
        lote = _lote()
        with lote.trava:
            fila = {j["id"]: dict(j) for j in lote.fila}
        prontos = []
        for k, it in esperando.items():
            j = fila.get(it.get("flow_job") or "")
            if j is None:
                it.update(estado="erro", erro="o pedido sumiu da fila do 🚀 Flow em massa — anime de novo")
            elif j["estado"] == "ok":
                res = next((r for r in j.get("resultados") or [] if r.get("tipo") in ("imagem", "video")), None)
                if not res:
                    it.update(estado="erro", erro="o Flow terminou mas não veio a imagem")
                else:
                    it.update(estado="processando", msg="🧹 tirando o verde…", arquivo_flow=res["arquivo"],
                              tipo_flow=res.get("tipo"))
                    prontos.append(k)
            elif j["estado"] == "erro":
                it.update(estado="erro", erro=str(j.get("erro") or "o Flow falhou")[:300])
            elif j["estado"] in ("rodando", "convertendo"):
                it.update(estado="gerando", msg="🎬 gerando no Flow")
        _salvar(pid, base, d)
    for k in prontos:  # fora da trava: tirar o verde demora
        _finalizar(pid, base, k)
    return carregar(pid, base)


def _finalizar(pid: str, base: str, k: str) -> None:
    import flow_estudio as FE
    import personagens_pod as pp
    d = carregar(pid, base)
    it = d.get(k) or {}
    try:
        origem = os.path.join(FE.pasta_galeria(), it["arquivo_flow"])
        verde = os.path.join(pasta(pid, base), f"{k}_verde" + os.path.splitext(it["arquivo_flow"])[1])
        shutil.copyfile(origem, verde)
        try:
            p = pp.carregar(pid, base)
            opl = p["dados"]["limpeza"] if isinstance(p["dados"].get("limpeza"), dict) else {}
        except Exception:  # noqa: BLE001
            opl = {}
        if it.get("tipo_flow") == "imagem":  # 🖼 v84_205: o quadro intermediário → recorta igual às poses e alterna
            from PIL import Image
            import personagens_limpeza as L
            try:
                p_ = pp.carregar(pid, base)
                canvas = tuple(p_["dados"].get("canvas") or (1200, 1800))
                alt = float(p_["dados"].get("altura_personagem") or 0.95)
                corpo = bool(p_["dados"].get("corpo_inteiro"))
            except Exception:  # noqa: BLE001
                canvas, alt, corpo = (1200, 1800), 0.95, False
            final, _info = L.recortar(Image.open(verde).convert("RGB"), canvas, alt, opl, corpo_inteiro=corpo)
            quadro = os.path.join(pasta(pid, base), f"{k}_quadro2.png")
            final.save(quadro)
            it["quadro2"] = quadro
            r = montar_loop(it.get("pose_png") or "", quadro, os.path.join(pasta(pid, base), f"{k}.webm"), it.get("tipo") or "fala")
        else:
            r = processar(verde, os.path.join(pasta(pid, base), f"{k}.webm"), opl)
        it.update(estado="pronto", webm=r["webm"], verde=verde, duracao=r["duracao"], msg="✅ pronta", erro=None,
                  pronto_em=time.time())
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        it.update(estado="erro", erro=f"o vídeo chegou mas não consegui tirar o verde: {str(exc)[:200]}")
    with _TRAVA:
        d = carregar(pid, base)
        d[k] = it
        _salvar(pid, base, d)


def pronta(pid: str, base: str, caminho_png: str, tipo: str) -> Optional[Dict[str, Any]]:
    if not pid or not caminho_png or not os.path.isfile(caminho_png):
        return None
    try:
        it = carregar(pid, base).get(chave(caminho_png, tipo))
    except OSError:
        return None
    return it if it and it.get("estado") == "pronto" and os.path.isfile(str(it.get("webm"))) else None


def item(pid: str, base: str, caminho_png: str, tipo: str) -> Optional[Dict[str, Any]]:
    if not pid or not caminho_png or not os.path.isfile(caminho_png):
        return None
    try:
        return carregar(pid, base).get(chave(caminho_png, tipo))
    except OSError:
        return None


# ------------------------------------------------------------------ no vídeo (overlay)
def preparar_clipe(webm: str, destino: str, segundos: float) -> str:
    """"Só uns frames": os primeiros `segundos` do clipe, ida e volta (termina na pose, sem pulo)."""
    if os.path.isfile(destino) and os.path.getsize(destino) > 0:
        return destino
    s = max(0.3, float(segundos))
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-c:v", "libvpx-vp9", "-i", webm, "-filter_complex",
                        f"[0:v]trim=0:{s:.3f},setpts=PTS-STARTPTS,format=yuva420p,split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0[v]",
                        "-map", "[v]", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "30",
                        "-auto-alt-ref", "0", destino], capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not os.path.isfile(destino):
        raise AnimErro(f"não consegui cortar o clipe: {(r.stderr or '')[-200:]}")
    return destino


def ligar_no_overlay(ov: Dict[str, Any], it: Dict[str, Any], job_dir: str) -> bool:
    """Põe o clipe pronto na aparição (cópia no projeto do vídeo). → True se mudou."""
    if not it or it.get("estado") != "pronto":
        return False
    pasta_j = os.path.join(job_dir, "personagens")
    os.makedirs(pasta_j, exist_ok=True)
    origem = it["webm"]
    seg = float(ov.get("anim_segundos") or 0)
    nome = os.path.basename(origem)
    if seg > 0:
        nome = nome.replace(".webm", f"_ida_volta_{int(seg * 1000)}.webm")
    destino = os.path.join(pasta_j, nome)
    if seg > 0:
        preparar_clipe(origem, destino, seg)
    elif not os.path.isfile(destino):
        shutil.copyfile(origem, destino)
    if ov.get("anim_video") == destino:
        return False
    ov["anim_video"] = destino
    return True


def aplicar_prontas(job: Dict[str, Any], base: str, job_dir: str) -> int:
    """Toda aparição com animação pedida (ou pose que já tem clipe na biblioteca) recebe o clipe pronto. → quantas
    mudaram."""
    n = 0
    vistos: Dict[str, Dict[str, Any]] = {}
    for ov in job.get("overlays") or []:
        if ov.get("origem") != "personagem" or not ov.get("projeto_id") or ov.get("anim_desligada"):
            continue
        pid = ov["projeto_id"]
        if pid not in vistos:
            try:
                vistos[pid] = sincronizar(pid, base)
            except Exception:  # noqa: BLE001
                vistos[pid] = {}
        png = ov.get("pose_original") or ((ov.get("source") or {}).get("value"))
        tipo = ov.get("anim_tipo") or ("fala" if ov.get("boca_janelas") else "parada")
        try:
            it = vistos[pid].get(chave(png, tipo)) if png and os.path.isfile(png) else None
        except OSError:
            it = None
        if not it:
            continue
        estado = it.get("estado")
        if ov.get("anim_estado") != estado or ov.get("anim_msg") != (it.get("erro") or it.get("msg")):
            ov["anim_estado"], ov["anim_msg"] = estado, it.get("erro") or it.get("msg")
            n += 1
        if estado == "pronto":
            try:
                if ligar_no_overlay(ov, it, job_dir):
                    n += 1
            except Exception as exc:  # noqa: BLE001
                ov["anim_msg"] = str(exc)[:200]
    return n
