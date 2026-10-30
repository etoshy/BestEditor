"""juntar_videos.py — 🔗 a aba Juntar vídeos (v84_282).

Você envia os vídeos, arrasta pra pôr na ordem e ele junta num arquivo só pra baixar.

• Quando todos os vídeos têm o mesmo formato (codec, resolução, fps, áudio) — por exemplo as partes de um mesmo vídeo,
  ou vídeos exportados do mesmo jeito — ele junta SEM recodificar (`-c copy`): é instantâneo e fica com a qualidade
  original, bit a bit.
• Quando os formatos são diferentes, ele recodifica tudo pro tamanho do MAIOR vídeo (os menores ganham bordas pretas,
  sem esticar), com qualidade alta (H.264 CRF 16 / AAC 320k). Vídeo sem som ganha silêncio no lugar.

Pasta: <BASE>/juntar/<id>/ com videos/, projeto.json e saida/.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from flask import abort, jsonify, redirect, render_template, request, send_file, send_from_directory

import arquivo_seguro

EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".ts", ".mts", ".flv", ".wmv", ".mpg", ".mpeg", ".3gp")
QUALIDADES = {
    "original": {"crf": "16", "preset": "medium", "rotulo": "máxima (mais lento)"},
    "rapido": {"crf": "18", "preset": "veryfast", "rotulo": "alta, bem mais rápido"},
}
TAREFAS: Dict[str, Dict[str, Any]] = {}
_PROCS: Dict[str, subprocess.Popen] = {}
_TRAVA = threading.Lock()


class JuntarErro(Exception):
    pass


# ---------------------------------------------------------------------------------------------------- projeto
def raiz(base_dir: str) -> str:
    return os.environ.get("JUNTAR_DIR") or os.path.join(base_dir, "juntar")


def pasta(pid: str, base_dir: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{10}", pid or ""):
        raise JuntarErro("id inválido")
    return os.path.join(raiz(base_dir), pid)


def novo(base_dir: str, titulo: str = "") -> Dict[str, Any]:
    pid = uuid.uuid4().hex[:10]
    d = pasta(pid, base_dir)
    os.makedirs(os.path.join(d, "videos"), exist_ok=True)
    p = {"id": pid, "titulo": (titulo or "").strip()[:80] or "Vídeos juntados", "criado": time.time(), "videos": [], "saida": None}
    salvar(p, base_dir)
    return p


def carregar(pid: str, base_dir: str) -> Dict[str, Any]:
    cam = os.path.join(pasta(pid, base_dir), "projeto.json")
    if not os.path.isfile(cam):
        raise JuntarErro("projeto não existe")
    with open(cam, encoding="utf-8") as f:
        return json.load(f)


def salvar(p: Dict[str, Any], base_dir: str) -> None:
    arquivo_seguro.gravar_json(os.path.join(pasta(p["id"], base_dir), "projeto.json"), p)


def listar(base_dir: str) -> List[Dict[str, Any]]:
    r = raiz(base_dir)
    out = []
    for pid in os.listdir(r) if os.path.isdir(r) else []:
        try:
            p = carregar(pid, base_dir)
        except Exception:  # noqa: BLE001
            continue
        out.append({"id": pid, "titulo": p.get("titulo"), "n": len(p.get("videos") or []), "criado": p.get("criado") or 0,
                    "duracao": sum(v.get("dur") or 0 for v in p.get("videos") or []), "pronto": bool(p.get("saida"))})
    return sorted(out, key=lambda x: -x["criado"])


def nome_livre(pasta_v: str, nome: str) -> str:
    base, ext = os.path.splitext(re.sub(r"[^\w.\- ()]+", "_", os.path.basename(nome)).strip().replace(" ", "_") or "video.mp4")
    cand, k = base + ext.lower(), 2
    while os.path.exists(os.path.join(pasta_v, cand)):
        cand, k = f"{base}_{k}{ext.lower()}", k + 1
    return cand


# ---------------------------------------------------------------------------------------------------- ffprobe
def _fps(s: str) -> float:
    try:
        a, b = (s or "0/1").split("/")
        return round(float(a) / float(b), 3) if float(b) else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def info(cam: str) -> Dict[str, Any]:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", cam],
                       capture_output=True, text=True, timeout=120)
    try:
        j = json.loads(r.stdout or "{}")
    except ValueError:
        j = {}
    vs = [s for s in j.get("streams") or [] if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")]
    as_ = [s for s in j.get("streams") or [] if s.get("codec_type") == "audio"]
    if not vs:
        raise JuntarErro(f"{os.path.basename(cam)}: não achei vídeo nesse arquivo")
    v = vs[0]
    rot = 0
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            rot = int(sd.get("rotation") or 0)
    rot = rot or int((v.get("tags") or {}).get("rotate") or 0)
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if abs(rot) % 180 == 90:
        w, h = h, w
    a = as_[0] if as_ else {}
    dur = float((j.get("format") or {}).get("duration") or v.get("duration") or 0)
    return {"w": w, "h": h, "fps": _fps(v.get("avg_frame_rate") or v.get("r_frame_rate")) or _fps(v.get("r_frame_rate")),
            "vcodec": v.get("codec_name"), "pix": v.get("pix_fmt"), "perfil": v.get("profile"), "rot": rot,
            "audio": bool(as_), "acodec": a.get("codec_name"), "ar": int(a.get("sample_rate") or 0), "ac": int(a.get("channels") or 0),
            "dur": round(dur, 3), "bytes": os.path.getsize(cam),
            "vbr": int(v.get("bit_rate") or (j.get("format") or {}).get("bit_rate") or 0)}


def _chave(i: Dict[str, Any]) -> tuple:
    return (i["vcodec"], i["w"], i["h"], round(i["fps"], 2), i["pix"], i.get("perfil"), i["rot"], i["audio"], i["acodec"], i["ar"], i["ac"])


def compativel(vids: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Diz se dá pra juntar sem recodificar e, se não der, o que é diferente."""
    if not vids:
        return {"copia": False, "motivo": "nenhum vídeo"}
    i0 = vids[0]["info"]
    nomes = ["codec", "resolução", "fps", "formato de cor", "perfil", "rotação", "som", "codec do som", "taxa do som", "canais"]
    dif = set()
    for v in vids[1:]:
        for n, a, b in zip(nomes, _chave(i0), _chave(v["info"])):
            if a != b:
                dif.add(n)
    if dif:
        return {"copia": False, "motivo": "formatos diferentes (" + ", ".join(sorted(dif)) + ") — vai recodificar em qualidade alta"}
    return {"copia": True, "motivo": "mesmo formato em todos — junta sem recodificar (qualidade original, rápido)"}


def destino(vids: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Tamanho e fps da saída quando precisa recodificar: o do maior vídeo (e o maior fps, até 60)."""
    m = max(vids, key=lambda v: v["info"]["w"] * v["info"]["h"])["info"]
    fps = min(60.0, max(v["info"]["fps"] or 30 for v in vids))
    return {"w": m["w"] - m["w"] % 2, "h": m["h"] - m["h"] % 2, "fps": fps}


# ---------------------------------------------------------------------------------------------------- juntar
def _rodar_ffmpeg(cmd: List[str], total: float, prog: Callable[[float], None], pid: str) -> None:
    proc = subprocess.Popen(cmd + ["-progress", "pipe:1", "-nostats"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    _PROCS[pid] = proc
    err: List[str] = []
    t = threading.Thread(target=lambda: err.extend(proc.stderr.readlines()), daemon=True)
    t.start()
    for linha in proc.stdout:
        if linha.startswith("out_time_us=") or linha.startswith("out_time_ms="):
            try:
                prog(min(0.999, int(linha.split("=")[1]) / 1e6 / max(0.1, total)))
            except ValueError:
                pass
    proc.wait()
    t.join(5)
    _PROCS.pop(pid, None)
    if proc.returncode != 0:
        if TAREFAS.get(pid, {}).get("cancelado"):
            raise JuntarErro("parado")
        raise JuntarErro("ffmpeg: " + "".join(err)[-500:])


def juntar(p: Dict[str, Any], base_dir: str, modo: str = "auto", qualidade: str = "original",
           prog: Callable[[float], None] = lambda x: None) -> Dict[str, Any]:
    vids = p.get("videos") or []
    if len(vids) < 2:
        raise JuntarErro("envie pelo menos 2 vídeos")
    d = pasta(p["id"], base_dir)
    vd = os.path.join(d, "videos")
    sd = os.path.join(d, "saida")
    os.makedirs(sd, exist_ok=True)
    total = sum(v["info"]["dur"] for v in vids)
    comp = compativel(vids)
    copia = comp["copia"] and modo != "recodificar"
    base = re.sub(r"[^\w\-]+", "_", p.get("titulo") or "juntado").strip("_")[:60] or "juntado"
    if copia:
        ext = ".mp4" if vids[0]["info"]["vcodec"] in ("h264", "hevc", "av1", "mpeg4") and vids[0]["info"]["acodec"] in (None, "aac", "mp3", "ac3", "eac3", "alac", "opus", "flac") else ".mkv"
        out = os.path.join(sd, base + ext)
        lista = os.path.join(sd, "lista.txt")
        with open(lista, "w", encoding="utf-8") as f:
            for v in vids:
                cam = os.path.join(vd, v["arq"]).replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{cam}'\n")
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lista, "-map", "0:v:0", "-map", "0:a:0?",
               "-c", "copy"] + (["-movflags", "+faststart"] if ext == ".mp4" else []) + [out]
        _rodar_ffmpeg(cmd, total, prog, p["id"])
    else:
        alvo = destino(vids)
        q = QUALIDADES.get(qualidade) or QUALIDADES["original"]
        out = os.path.join(sd, base + ".mp4")
        cmd = ["ffmpeg", "-v", "error", "-y"]
        for v in vids:
            cmd += ["-i", os.path.join(vd, v["arq"])]
        fil, ent = [], []
        for k, v in enumerate(vids):
            fil.append(f"[{k}:v:0]scale={alvo['w']}:{alvo['h']}:force_original_aspect_ratio=decrease:flags=lanczos,"
                       f"pad={alvo['w']}:{alvo['h']}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={alvo['fps']},format=yuv420p,"
                       f"trim=duration={v['info']['dur']:.3f},setpts=PTS-STARTPTS[v{k}]")
            if v["info"]["audio"]:
                fil.append(f"[{k}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                           f"apad,atrim=duration={v['info']['dur']:.3f},asetpts=PTS-STARTPTS[a{k}]")
            else:
                fil.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={v['info']['dur']:.3f}[a{k}]")
            ent.append(f"[v{k}][a{k}]")
        fil.append("".join(ent) + f"concat=n={len(vids)}:v=1:a=1[v][a]")
        cmd += ["-filter_complex", ";".join(fil), "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-crf", q["crf"], "-preset", q["preset"], "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", out]
        _rodar_ffmpeg(cmd, total, prog, p["id"])
    for f in os.listdir(sd):
        cam = os.path.join(sd, f)
        if cam != out and os.path.isfile(cam):
            os.remove(cam)
    i = info(out)
    p["saida"] = {"arq": os.path.basename(out), "copia": copia, "dur": i["dur"], "bytes": i["bytes"], "w": i["w"], "h": i["h"],
                  "quando": time.time(), "ordem": [v["arq"] for v in vids]}
    salvar(p, base_dir)
    return p["saida"]


# ---------------------------------------------------------------------------------------------------- rotas
def registrar(app, base_dir: str) -> None:
    def _ok(**kw: Any):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: str, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _p(pid: str) -> Dict[str, Any]:
        try:
            return carregar(pid, base_dir)
        except JuntarErro:
            abort(404)

    def _estado(p: Dict[str, Any]) -> Dict[str, Any]:
        vids = p.get("videos") or []
        t = TAREFAS.get(p["id"])
        s = p.get("saida") or None
        return {"projeto": p, "saida_atual": bool(s and s.get("ordem") == [v["arq"] for v in vids]), "compat": compativel(vids) if len(vids) > 1 else None,
                "destino": destino(vids) if vids else None, "total": round(sum(v["info"]["dur"] for v in vids), 2),
                "tarefa": dict(t, rodando=not t.get("fim")) if t else None,
                "qualidades": {k: v["rotulo"] for k, v in QUALIDADES.items()}}

    @app.route("/juntar")
    def juntar_lista():
        return render_template("juntar.html", p=None, projetos=listar(base_dir))

    @app.route("/juntar/novo", methods=["POST"])
    def juntar_novo():
        p = novo(base_dir, request.form.get("titulo") or "")
        return redirect(f"/juntar/{p['id']}")

    @app.route("/juntar/<pid>")
    def juntar_projeto(pid: str):
        return render_template("juntar.html", p=_p(pid), projetos=[])

    @app.route("/juntar/<pid>/estado")
    def juntar_estado(pid: str):
        return _ok(**_estado(_p(pid)))

    @app.route("/juntar/<pid>/enviar", methods=["POST"])
    def juntar_enviar(pid: str):
        p = _p(pid)
        vd = os.path.join(pasta(pid, base_dir), "videos")
        os.makedirs(vd, exist_ok=True)
        erros = []
        for arq in request.files.getlist("arquivos"):
            if not arq or not arq.filename:
                continue
            if os.path.splitext(arq.filename)[1].lower() not in EXT:
                erros.append(f"{arq.filename}: formato não aceito")
                continue
            nome = nome_livre(vd, arq.filename)
            cam = os.path.join(vd, nome)
            arq.save(cam)
            try:
                i = info(cam)
            except JuntarErro as exc:
                os.remove(cam)
                erros.append(str(exc))
                continue
            p = _p(pid)  # outro envio pode ter salvo no meio
            p.setdefault("videos", []).append({"arq": nome, "nome": os.path.basename(arq.filename), "info": i})
            salvar(p, base_dir)
        return _ok(erros=erros, **_estado(_p(pid)))

    @app.route("/juntar/<pid>/ordem", methods=["POST"])
    def juntar_ordem(pid: str):
        p = _p(pid)
        ordem = (request.get_json(silent=True) or {}).get("ordem") or []
        por = {v["arq"]: v for v in p.get("videos") or []}
        if sorted(ordem) != sorted(por):
            return _erro("a lista mudou — recarregue a página")
        p["videos"] = [por[a] for a in ordem]
        salvar(p, base_dir)
        return _ok(**_estado(p))

    @app.route("/juntar/<pid>/remover", methods=["POST"])
    def juntar_remover(pid: str):
        p = _p(pid)
        arq = os.path.basename((request.get_json(silent=True) or {}).get("arq") or "")
        p["videos"] = [v for v in p.get("videos") or [] if v["arq"] != arq]
        cam = os.path.join(pasta(pid, base_dir), "videos", arq)
        if arq and os.path.isfile(cam):
            os.remove(cam)
        salvar(p, base_dir)
        return _ok(**_estado(p))

    @app.route("/juntar/<pid>/titulo", methods=["POST"])
    def juntar_titulo(pid: str):
        p = _p(pid)
        p["titulo"] = ((request.get_json(silent=True) or {}).get("titulo") or "").strip()[:80] or p["titulo"]
        salvar(p, base_dir)
        return _ok(**_estado(p))

    @app.route("/juntar/<pid>/juntar", methods=["POST"])
    def juntar_rodar(pid: str):
        p = _p(pid)
        j = request.get_json(silent=True) or {}
        if len(p.get("videos") or []) < 2:
            return _erro("envie pelo menos 2 vídeos")
        with _TRAVA:
            t = TAREFAS.get(pid)
            if t and not t.get("fim"):
                return _erro("já está juntando", 409)
            TAREFAS[pid] = {"inicio": time.time(), "fim": None, "erro": None, "prog": 0.0, "cancelado": False}

        def prog(x: float) -> None:
            TAREFAS[pid]["prog"] = round(x, 4)

        def corpo() -> None:
            try:
                juntar(carregar(pid, base_dir), base_dir, j.get("modo") or "auto", j.get("qualidade") or "original", prog)
                TAREFAS[pid]["prog"] = 1.0
            except Exception as exc:  # noqa: BLE001
                TAREFAS[pid]["erro"] = str(exc)[:600]
            finally:
                TAREFAS[pid]["fim"] = time.time()
        threading.Thread(target=corpo, daemon=True, name="juntar:" + pid).start()
        return _ok(**_estado(p))

    @app.route("/juntar/<pid>/parar", methods=["POST"])
    def juntar_parar(pid: str):
        t = TAREFAS.get(pid)
        if t:
            t["cancelado"] = True
        pr = _PROCS.get(pid)
        if pr and pr.poll() is None:
            pr.kill()
        return _ok()

    @app.route("/juntar/<pid>/video/<path:arq>")
    def juntar_video(pid: str, arq: str):
        _p(pid)
        return send_from_directory(os.path.join(pasta(pid, base_dir), "videos"), os.path.basename(arq), conditional=True)

    @app.route("/juntar/<pid>/baixar")
    def juntar_baixar(pid: str):
        p = _p(pid)
        s = p.get("saida") or {}
        cam = os.path.join(pasta(pid, base_dir), "saida", os.path.basename(s.get("arq") or ""))
        if not s or not os.path.isfile(cam):
            abort(404)
        return send_file(cam, as_attachment=request.args.get("ver") != "1", download_name=s["arq"], conditional=True)

    @app.route("/juntar/<pid>/apagar", methods=["POST"])
    def juntar_apagar(pid: str):
        _p(pid)
        pr = _PROCS.get(pid)
        if pr and pr.poll() is None:
            pr.kill()
        shutil.rmtree(pasta(pid, base_dir), ignore_errors=True)
        return redirect("/juntar")
