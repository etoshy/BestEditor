"""achar_fonte.py — 🔎 Achar a fonte (v84_289).

Cola o link de um vídeo explicativo (ou sobe o arquivo): o site baixa, acha as TROCAS DE CENA e tira 1 ou 2 prints de cada
cena. Cada print vai pro Google Lens com um clique (o arquivo é enviado direto, sem precisar salvar), também ↔ INVERTIDO
(muito canal espelha o vídeo pra não ser achado) e ✂ sem as faixas de cima/baixo (legenda, logo, título). Também TinEye,
Yandex e Bing, e 📋 copiar a imagem (cole com Ctrl+V no Lens). Você marca a fonte que achou em cada cena e baixa a lista.

Pasta: <BASE>/fontes_video/<id>/  (video.mp4, quadros/, projeto.json)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import arquivo_seguro

TAREFAS: Dict[str, Dict[str, Any]] = {}


class FonteErro(Exception):
    pass


# ---------------------------------------------------------------------------------------------------- projeto
def raiz(base: str) -> str:
    return os.environ.get("FONTES_VIDEO_DIR") or os.path.join(base, "fontes_video")


def pasta(base: str, pid: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{10}", pid or ""):
        raise FonteErro("id inválido")
    return os.path.join(raiz(base), pid)


def carregar(base: str, pid: str) -> Dict[str, Any]:
    cam = os.path.join(pasta(base, pid), "projeto.json")
    if not os.path.isfile(cam):
        raise FonteErro("não existe")
    with open(cam, encoding="utf-8") as f:
        return json.load(f)


def salvar(base: str, p: Dict[str, Any]) -> None:
    p["mudou"] = time.time()
    arquivo_seguro.gravar_json(os.path.join(pasta(base, p["id"]), "projeto.json"), p)


def novo(base: str, link: str = "", titulo: str = "") -> Dict[str, Any]:
    pid = uuid.uuid4().hex[:10]
    os.makedirs(os.path.join(pasta(base, pid), "quadros"), exist_ok=True)
    p = {"id": pid, "link": link.strip(), "titulo": (titulo or "").strip()[:120] or (link.strip()[-60:] if link else "Vídeo"),
         "criado": time.time(), "cenas": [], "video": "", "dur": 0, "sensibilidade": 0.3, "por_cena": 2}
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
        out.append({"id": pid, "titulo": p.get("titulo"), "cenas": len(p.get("cenas") or []), "criado": p.get("criado") or 0,
                    "achadas": sum(1 for c in p.get("cenas") or [] if c.get("fonte")), "link": p.get("link") or ""})
    return sorted(out, key=lambda x: -x["criado"])


# ---------------------------------------------------------------------------------------------------- vídeo
def duracao(cam: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", cam],
                       capture_output=True, text=True, timeout=60)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def baixar(link: str, destino_dir: str) -> str:
    """O mesmo baixador dos curtos: YouTube pelo cortador (qualidade alta — melhor pro Lens), TikTok/Reels/Kwai… pelo yt-dlp."""
    import curtos_comentario as CC
    import sys
    raiz_ = os.path.dirname(os.path.abspath(__file__))
    if os.path.join(raiz_, "toolkit") not in sys.path:
        sys.path.insert(0, os.path.join(raiz_, "toolkit"))

    def baixador(url: str, d: str) -> str:
        if re.search(r"(youtube\.com|youtu\.be)/", url):
            import youtube_clipper
            return (youtube_clipper.baixar_video(url, d, qualidade="1080p") or {}).get("caminho") or ""
        return CC._baixador_padrao(url, d)
    return CC.baixar_link(link, destino_dir, baixador)


def trocas_de_cena(cam: str, sensibilidade: float = 0.3, minimo_s: float = 0.6) -> List[float]:
    """Os segundos em que a cena troca (ffmpeg, filtro 'scene'); sempre começa no 0. Cortes colados (< minimo_s) viram um."""
    th = max(0.05, min(0.9, float(sensibilidade)))
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", cam, "-an", "-vf", f"scale=320:-2,select='gt(scene,{th})',showinfo",
                        "-f", "null", "-"], capture_output=True, text=True, timeout=1800)
    ts = [float(m.group(1)) for m in re.finditer(r"pts_time:([\d.]+)", r.stderr or "")]
    out = [0.0]
    for t in ts:
        if t - out[-1] >= minimo_s:
            out.append(round(t, 3))
    return out


def tirar_print(cam: str, t: float, destino: str) -> bool:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", cam, "-frames:v", "1", "-q:v", "2", destino],
                   capture_output=True, timeout=120)
    return os.path.isfile(destino) and os.path.getsize(destino) > 0


def _miniatura(src: str, dest: str, larg: int = 360) -> None:
    try:
        from PIL import Image
        im = Image.open(src).convert("RGB")
        im.thumbnail((larg, larg * 2))
        im.save(dest, "JPEG", quality=80)
    except Exception:  # noqa: BLE001
        shutil.copy(src, dest)


def _quase_preto(cam: str) -> bool:
    """Quadro de transição (preto/branco liso)? Pula pra não mandar print vazio pro Lens."""
    try:
        from PIL import Image, ImageStat
        st = ImageStat.Stat(Image.open(cam).convert("L").resize((64, 64)))
        return st.stddev[0] < 6
    except Exception:  # noqa: BLE001
        return False


def analisar(base: str, pid: str, prog: Callable[[str], None] = lambda m: None) -> Dict[str, Any]:
    p = carregar(base, pid)
    d = pasta(base, pid)
    cam = os.path.join(d, p.get("video") or "video.mp4")
    if not os.path.isfile(cam):
        if not p.get("link"):
            raise FonteErro("Mande o link ou o arquivo do vídeo.")
        prog("⬇ baixando o vídeo…")
        tmp = tempfile.mkdtemp(prefix="fonte_")
        try:
            baixado = baixar(p["link"], tmp)
            ext = os.path.splitext(baixado)[1] or ".mp4"
            cam = os.path.join(d, "video" + ext)
            shutil.move(baixado, cam)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        p["video"] = os.path.basename(cam)
    dur = duracao(cam)
    prog(f"🎬 procurando as trocas de cena ({dur:.0f} s de vídeo)…")
    cortes = trocas_de_cena(cam, p.get("sensibilidade") or 0.3)
    q = os.path.join(d, "quadros")
    shutil.rmtree(q, ignore_errors=True)
    os.makedirs(q, exist_ok=True)
    fontes_antigas = {round(c["t0"], 1): c for c in p.get("cenas") or [] if c.get("fonte") or c.get("nota")}
    cenas = []
    por = int(p.get("por_cena") or 2)
    for i, t0 in enumerate(cortes):
        t1 = cortes[i + 1] if i + 1 < len(cortes) else dur
        if t1 - t0 < 0.2:
            continue
        if i % 5 == 0:
            prog(f"📸 cena {i + 1}/{len(cortes)}…")
        # 1º print logo depois do corte (sem o quadro da transição); 2º no meio, se a cena for longa
        tempos = [min(t0 + 0.35, t0 + (t1 - t0) * 0.3)]
        if por >= 2 and t1 - t0 >= 2.0:
            tempos.append(t0 + (t1 - t0) * 0.65)
        prints = []
        for k, t in enumerate(tempos):
            nome = f"c{i + 1:03d}_{k + 1}.jpg"
            if tirar_print(cam, t, os.path.join(q, nome)) and not _quase_preto(os.path.join(q, nome)):
                _miniatura(os.path.join(q, nome), os.path.join(q, "m_" + nome))
                prints.append({"arq": nome, "t": round(t, 2)})
        if not prints:
            continue
        velha = fontes_antigas.get(round(t0, 1)) or {}
        cenas.append({"n": len(cenas) + 1, "t0": round(t0, 2), "t1": round(t1, 2), "prints": prints,
                      "fonte": velha.get("fonte", ""), "nota": velha.get("nota", "")})
    p = carregar(base, pid)
    p.update(cenas=cenas, dur=round(dur, 2), video=os.path.basename(cam), analisado=time.time())
    salvar(base, p)
    return p


# ---------------------------------------------------------------------------------------------------- imagem (inverter / recortar)
def imagem(base: str, pid: str, arq: str, inverter: bool = False, recorte: str = "") -> bytes:
    """O print como JPEG — ↔ invertido e/ou ✂ sem as faixas (recorte 'meio' = tira 18% de cima e de baixo; 'centro' = só o
    miolo, sem as bordas — bom quando o vídeo tem fundo desfocado/moldura)."""
    cam = os.path.join(pasta(base, pid), "quadros", os.path.basename(arq))
    if not os.path.isfile(cam):
        raise FonteErro("print não encontrado")
    if not inverter and not recorte:
        with open(cam, "rb") as f:
            return f.read()
    from io import BytesIO
    from PIL import Image, ImageOps
    im = Image.open(cam).convert("RGB")
    w, h = im.size
    if recorte == "meio":
        im = im.crop((0, int(h * 0.18), w, int(h * 0.82)))
    elif recorte == "centro":
        im = im.crop((int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.85)))
    if inverter:
        im = ImageOps.mirror(im)
    b = BytesIO()
    im.save(b, "JPEG", quality=92)
    return b.getvalue()


def marcar(base: str, pid: str, n: int, fonte: Optional[str] = None, nota: Optional[str] = None) -> Dict[str, Any]:
    p = carregar(base, pid)
    for c in p.get("cenas") or []:
        if c["n"] == n:
            if fonte is not None:
                c["fonte"] = str(fonte).strip()[:600]
            if nota is not None:
                c["nota"] = str(nota).strip()[:600]
            salvar(base, p)
            return c
    raise FonteErro("cena não encontrada")


def _mmss(t: float) -> str:
    t = int(t or 0)
    return f"{t // 60}:{t % 60:02d}"


def lista_texto(p: Dict[str, Any]) -> str:
    L = [f"FONTES — {p.get('titulo')}", p.get("link") or "", ""]
    for c in p.get("cenas") or []:
        L.append(f"Cena {c['n']:>3}  {_mmss(c['t0'])}-{_mmss(c['t1'])}  {c.get('fonte') or '(não achada)'}" + (f"  — {c['nota']}" if c.get("nota") else ""))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------------------------------- rotas
def registrar(app, base: str) -> None:
    from flask import Response, abort, jsonify, redirect, render_template, request, send_file
    from werkzeug.utils import secure_filename

    def _ok(**kw: Any):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: Any, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _p(pid: str) -> Dict[str, Any]:
        try:
            return carregar(base, pid)
        except FonteErro:
            abort(404)

    def _rodar(pid: str) -> None:
        t = TAREFAS.get(pid)
        if t and not t.get("fim"):
            raise FonteErro("Já está analisando.")
        TAREFAS[pid] = {"inicio": time.time(), "fim": None, "erro": None, "prog": "começando…"}

        def corpo() -> None:
            try:
                analisar(base, pid, lambda m: TAREFAS[pid].__setitem__("prog", str(m)[:200]))
            except Exception as exc:  # noqa: BLE001
                TAREFAS[pid]["erro"] = str(exc)[:500]
            finally:
                TAREFAS[pid]["fim"] = time.time()
        threading.Thread(target=corpo, daemon=True, name="fonte:" + pid).start()

    def _estado(p: Dict[str, Any]) -> Dict[str, Any]:
        t = TAREFAS.get(p["id"])
        return {"projeto": p, "tarefa": dict(t, rodando=not t.get("fim")) if t else None}

    @app.route("/achar-fonte")
    def af_lista():
        return render_template("achar_fonte.html", p=None, lista=listar(base))

    @app.route("/achar-fonte/<pid>")
    def af_ver(pid: str):
        return render_template("achar_fonte.html", p=_p(pid), lista=[])

    @app.route("/achar-fonte/novo", methods=["POST"])
    def af_novo():
        link = (request.form.get("link") or "").strip()
        arq = request.files.get("arquivo")
        if not link and not (arq and arq.filename):
            return redirect("/achar-fonte?erro=Cole o link ou suba o vídeo.")
        p = novo(base, link if link.startswith("http") else "", request.form.get("titulo") or (arq.filename if arq and arq.filename else ""))
        try:
            p["sensibilidade"] = max(0.05, min(0.9, float(request.form.get("sensibilidade") or 0.3)))
            p["por_cena"] = 1 if request.form.get("por_cena") == "1" else 2
        except ValueError:
            pass
        if arq and arq.filename:
            nome = "video" + (os.path.splitext(secure_filename(arq.filename))[1] or ".mp4")
            arq.save(os.path.join(pasta(base, p["id"]), nome))
            p["video"] = nome
        salvar(base, p)
        _rodar(p["id"])
        return redirect(f"/achar-fonte/{p['id']}")

    @app.route("/achar-fonte/<pid>/estado")
    def af_estado(pid: str):
        return _ok(**_estado(_p(pid)))

    @app.route("/achar-fonte/<pid>/refazer", methods=["POST"])
    def af_refazer(pid: str):
        p = _p(pid)
        d = request.get_json(silent=True) or {}
        try:
            if "sensibilidade" in d:
                p["sensibilidade"] = max(0.05, min(0.9, float(d["sensibilidade"])))
            if "por_cena" in d:
                p["por_cena"] = 1 if int(d["por_cena"]) == 1 else 2
            salvar(base, p)
            _rodar(pid)
        except (FonteErro, ValueError) as exc:
            return _erro(exc)
        return _ok(**_estado(carregar(base, pid)))

    @app.route("/achar-fonte/<pid>/img/<arq>")
    def af_img(pid: str, arq: str):
        _p(pid)
        if arq.startswith("m_") and not request.args.get("inverter") and not request.args.get("recorte"):
            cam = os.path.join(pasta(base, pid), "quadros", os.path.basename(arq))
            if os.path.isfile(cam):
                return send_file(cam, mimetype="image/jpeg", max_age=3600)
        try:
            dados = imagem(base, pid, arq, request.args.get("inverter") == "1", request.args.get("recorte") or "")
        except FonteErro:
            abort(404)
        r = Response(dados, mimetype="image/jpeg")
        if request.args.get("baixar"):
            suf = ("_invertida" if request.args.get("inverter") == "1" else "") + (f"_{request.args['recorte']}" if request.args.get("recorte") else "")
            r.headers["Content-Disposition"] = f"attachment; filename={os.path.splitext(arq)[0]}{suf}.jpg"
        return r

    @app.route("/achar-fonte/<pid>/cena/<int:n>", methods=["POST"])
    def af_cena(pid: str, n: int):
        _p(pid)
        d = request.get_json(silent=True) or {}
        try:
            return _ok(cena=marcar(base, pid, n, d.get("fonte"), d.get("nota")))
        except FonteErro as exc:
            return _erro(exc)

    @app.route("/achar-fonte/<pid>/lista.txt")
    def af_lista_txt(pid: str):
        p = _p(pid)
        return Response(lista_texto(p), mimetype="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=fontes_{pid}.txt"})

    @app.route("/achar-fonte/<pid>/video")
    def af_video(pid: str):
        p = _p(pid)
        cam = os.path.join(pasta(base, pid), p.get("video") or "")
        if not p.get("video") or not os.path.isfile(cam):
            abort(404)
        return send_file(cam, conditional=True)

    @app.route("/achar-fonte/<pid>/apagar", methods=["POST"])
    def af_apagar(pid: str):
        _p(pid)
        shutil.rmtree(pasta(base, pid), ignore_errors=True)
        return redirect("/achar-fonte")
