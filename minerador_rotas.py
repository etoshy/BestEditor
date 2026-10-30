"""minerador_rotas.py — ⛏ a aba Minerador TikTok (v84_285).

• ▶ Roda o minerador_tiktok/minerador.py pelo site (na pasta onde está o seu tiktok_algo.py e a persona), com o log ao vivo,
  ⏹ parar (termina o vídeo atual, salva e sai) e o navegador VISÍVEL por padrão (desmarque "mostrar o navegador" pra esconder).
• ⚙ Edita o config_minerador.json dessa pasta.
• 🎞 Os vídeos minerados (que chegam em ✍ Roteiro de comentário): miniatura, nota, modelo de vídeo, gancho, momento forte,
  o que o público discute — com filtros (modelo, nota, status, nicho, busca) e status 🆕 novo / ⏳ depois / ✅ usado / 🗑.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from flask import abort, jsonify, render_template, request, send_file

import arquivo_seguro
import roteiro_comentario as RC

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(AQUI, "minerador_tiktok", "minerador.py")
CONFIG_MODELO = os.path.join(AQUI, "minerador_tiktok", "config_minerador.json")
_PROC: Dict[str, Any] = {"p": None, "inicio": None, "args": None}
_TRAVA = threading.Lock()


def _cfg_site(base: str) -> str:
    return os.path.join(base, "minerador_tiktok.json")


def config_site(base: str) -> Dict[str, Any]:
    try:
        with open(_cfg_site(base), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"pasta": "", "mostrar": True, "horas": 0, "sem_claude": False}


def salvar_config_site(base: str, d: Dict[str, Any]) -> None:
    arquivo_seguro.gravar_json(_cfg_site(base), d)


def log_cam(base: str) -> str:
    return os.path.join(base, "minerador_tiktok.log")


def cam_config(pasta: str) -> str:
    return os.path.join(pasta, "config_minerador.json")


def ler_config(pasta: str) -> str:
    for c in ([cam_config(pasta)] if pasta else []) + [CONFIG_MODELO]:
        if os.path.isfile(c):
            with open(c, encoding="utf-8") as f:
                return f.read()
    return "{}"


def pasta_saida(pasta: str) -> str:
    try:
        sd = (json.loads(ler_config(pasta)).get("saida") or {}).get("pasta") or "minerados"
    except ValueError:
        sd = "minerados"
    return sd if os.path.isabs(sd) else os.path.join(pasta, sd)


def rodando() -> bool:
    p = _PROC.get("p")
    return bool(p and p.poll() is None)


def cauda(base: str, n: int = 250) -> str:
    try:
        with open(log_cam(base), "rb") as f:
            f.seek(0, 2)
            tam = f.tell()
            f.seek(max(0, tam - 60000))
            linhas = f.read().decode("utf-8", "replace").splitlines()
        return "\n".join(linhas[-n:])
    except OSError:
        return ""


def pasta_dados(base: str) -> str:
    """📁 Onde o minerador trabalha quando você não escolheu pasta: <BASE>/minerador_dados (config, persona, minerados)."""
    d = os.path.join(base, "minerador_dados")
    os.makedirs(d, exist_ok=True)
    return d


def _candidatas(base: str) -> List[str]:
    casa = os.path.expanduser("~")
    raizes = [pasta_dados(base), base, AQUI, os.path.dirname(AQUI), os.path.dirname(os.path.dirname(AQUI))]
    raizes += [os.path.join(casa, x) for x in ("Desktop", "Área de Trabalho", "OneDrive", "OneDrive/Desktop", "OneDrive/Área de Trabalho",
                                              "Documents", "Documentos", "Downloads", "")]
    out, vistos = [], set()
    for r in raizes:
        r = os.path.abspath(r)
        if r not in vistos and os.path.isdir(r):
            vistos.add(r)
            out.append(r)
    return out


def achar_tiktok_algo(base: str, profundidade: int = 3, limite_s: float = 8.0) -> str:
    """🔎 Procura o tiktok_algo.py sozinho (pasta do site, a de cima, Área de Trabalho, Documentos, Downloads… até 3 níveis).
    Devolve a PASTA dele ('' se não achou)."""
    t0 = time.time()
    pular = {"node_modules", ".git", "__pycache__", "venv", ".venv", "env", "site-packages", "AppData", "Library", "jobs", "outputs",
             "curtos", "poker", "shorts_ia", "explicador", "juntar", "Windows", "Program Files", "Program Files (x86)"}
    for r in _candidatas(base):
        fila = [(r, 0)]
        while fila:
            d, n = fila.pop(0)
            if time.time() - t0 > limite_s:
                return ""
            if os.path.isfile(os.path.join(d, "tiktok_algo.py")):
                return d
            if n >= profundidade:
                continue
            try:
                for e in sorted(os.scandir(d), key=lambda e: e.name.lower()):
                    if e.is_dir(follow_symlinks=False) and e.name not in pular and not e.name.startswith("."):
                        fila.append((e.path, n + 1))
            except OSError:
                continue
    return ""


def pasta_auto(base: str) -> str:
    """A pasta escolhida; sem escolha (ou se sumiu), a do tiktok_algo.py que o site achar — e guarda pra próxima."""
    cs = config_site(base)
    p = cs.get("pasta") or ""
    if p and os.path.isfile(os.path.join(p, "tiktok_algo.py")):
        return p
    achou = achar_tiktok_algo(base)
    if achou:
        cs["pasta"] = achou
        salvar_config_site(base, cs)
        return achou
    return p


def _chave_ia() -> str:
    try:
        import ia_servico
        c = ia_servico.config()
        if ia_servico.PROVEDORES.get(c.get("provedor"), {}).get("chave_env") == "ANTHROPIC_API_KEY":
            return ia_servico.chave(c)
    except Exception:  # noqa: BLE001
        pass
    return ""


def iniciar(base: str, pasta: str, horas: float = 0, sem_claude: bool = False, mostrar: bool = True, reenviar: bool = False) -> Dict[str, Any]:
    with _TRAVA:
        if rodando():
            raise RC.RoteiroErro("O minerador já está rodando.")
        if not reenviar and not (pasta and os.path.isfile(os.path.join(pasta, "tiktok_algo.py"))):
            pasta = pasta_auto(base)
        if not reenviar and not (pasta and os.path.isfile(os.path.join(pasta, "tiktok_algo.py"))):
            raise RC.RoteiroErro("Não achei o tiktok_algo.py no computador. Use 📥 enviar o tiktok_algo.py (uma vez só) "
                                 "ou cole a pasta dele.")
        if not pasta or not os.path.isdir(pasta):
            raise RC.RoteiroErro("Não achei a pasta do minerador.")
        if not os.path.isfile(cam_config(pasta)):
            with open(cam_config(pasta), "w", encoding="utf-8") as f:
                f.write(ler_config(""))
        args = [sys.executable, "-u", SCRIPT, "--config", cam_config(pasta)]
        if reenviar:
            args.append("--reenviar")
        else:
            if horas and float(horas) > 0:
                args += ["--horas", str(float(horas))]
            if sem_claude:
                args.append("--sem-claude")
            args.append("--mostrar" if mostrar else "--headless")
        env = dict(os.environ, PYTHONPATH=pasta + os.pathsep + os.environ.get("PYTHONPATH", ""), PYTHONIOENCODING="utf-8",
                   PYTHONUNBUFFERED="1")
        if not env.get("ANTHROPIC_API_KEY") and _chave_ia():  # 🔑 a mesma chave da IA do site (Configurações)
            env["ANTHROPIC_API_KEY"] = _chave_ia()
        if not sem_claude and not reenviar and not env.get("ANTHROPIC_API_KEY"):
            raise RC.RoteiroErro("Falta a chave da IA: coloque a chave da Anthropic em Configurações → IA (ou marque 🧪 teste sem IA).")
        log = open(log_cam(base), "a", encoding="utf-8")
        log.write(f"\n===== {time.strftime('%d/%m %H:%M:%S')} ▶ {' '.join(args[2:])}\n")
        log.flush()
        kw: Dict[str, Any] = {}
        if os.name == "nt":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        cs = config_site(base)
        if cs.get("pasta") != pasta:
            cs["pasta"] = pasta
            salvar_config_site(base, cs)
        _PROC.update(p=subprocess.Popen(args, cwd=pasta, env=env, stdout=log, stderr=subprocess.STDOUT, **kw),
                     inicio=time.time(), args=args[2:])
        log.close()
    return estado(base)


def parar(base: str, forcar: bool = False) -> None:
    pasta = config_site(base).get("pasta") or ""
    if pasta:
        sd = pasta_saida(pasta)
        os.makedirs(sd, exist_ok=True)
        with open(os.path.join(sd, "PARAR"), "w") as f:
            f.write("site")
    p = _PROC.get("p")
    if forcar and p and p.poll() is None:
        p.kill()


def estado(base: str) -> Dict[str, Any]:
    cs = config_site(base)
    pasta = cs.get("pasta") or ""
    p = _PROC.get("p")
    cs = dict(cs, dados=pasta_dados(base), tem_chave=bool(os.environ.get("ANTHROPIC_API_KEY") or _chave_ia()))
    pend = os.path.join(pasta_saida(pasta), "pendentes_site.jsonl") if pasta else ""
    n_pend = 0
    if pend and os.path.isfile(pend):
        with open(pend, encoding="utf-8", errors="replace") as f:
            n_pend = sum(1 for l in f if l.strip())
    return {"site": cs, "rodando": rodando(), "inicio": _PROC.get("inicio"), "args": _PROC.get("args"),
            "codigo": (p.poll() if p else None), "tem_tiktok_algo": bool(pasta and os.path.isfile(os.path.join(pasta, "tiktok_algo.py"))),
            "pasta_ok": bool(pasta and os.path.isdir(pasta)), "pendentes": n_pend, "log": cauda(base)}


def videos(base: str, f: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    q = str(f.get("q") or "").lower().strip()
    nota = float(f.get("nota") or 0)
    for x in RC.listar(base):
        if not x.get("minerado"):
            continue
        r = RC.carregar(base, x["id"])
        m, res = r.get("minerador") or {}, r.get("res") or {}
        st = r.get("status") or "novo"
        if f.get("modelo") and m.get("modelo") != f["modelo"]:
            continue
        if f.get("status") and f["status"] != "todos" and st != f["status"]:
            continue
        if not f.get("status") and st == "descartado":  # padrão: esconde os descartados
            continue
        if nota and float(m.get("nota") or 0) < nota:
            continue
        if f.get("nicho") and str(m.get("nicho") or "").lower() != str(f["nicho"]).lower():
            continue
        txt = " ".join([r.get("titulo") or "", r.get("historia") or "", m.get("motivo") or "", m.get("autor") or "",
                        RC.texto(res, "en") if res else ""]).lower()
        if q and q not in txt:
            continue
        mt = m.get("metricas") or {}
        out.append({"id": r["id"], "titulo": r.get("titulo"), "status": st, "modelo": m.get("modelo"), "nota": m.get("nota"),
                    "nicho": m.get("nicho") or "", "motivo": m.get("motivo") or "", "link": m.get("link") or "", "autor": m.get("autor") or "",
                    "duracao_s": m.get("duracao_s"), "metricas": mt, "momento": (m.get("momento_forte") or {}).get("descricao") or "",
                    "momento_s": (m.get("momento_forte") or {}).get("tempo_s"), "discussao": m.get("discussao_principal") or "",
                    "gancho": (res.get("gancho") or {}).get("en") or "", "final": (res.get("final") or {}).get("en") or "",
                    "explicativo": m.get("assunto_explicativo") or "", "longo": m.get("ideia_longa") or "",
                    "miniatura": bool(m.get("miniatura")), "destino": RC.destino(r), "quando": m.get("coletado_em") or "",
                    "mudou": r.get("mudou") or 0})
    ordem = f.get("ordem") or "nota"
    if ordem == "nota":
        out.sort(key=lambda v: (-(float(v["nota"] or 0)), -v["mudou"]))
    else:
        out.sort(key=lambda v: -v["mudou"])
    return out


def registrar(app, base: str) -> None:
    def _ok(**kw: Any):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg: Any, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    @app.route("/minerador")
    def minerador_pagina():
        return render_template("minerador.html", modelos=RC.MODELOS_MINERADOR, status=RC.STATUS)

    @app.route("/minerador/estado")
    def minerador_estado():
        if not config_site(base).get("pasta") and request.args.get("achar"):
            pasta_auto(base)
        e = estado(base)
        e["config"] = ler_config(e["site"].get("pasta") or "")
        return _ok(**e)

    @app.route("/minerador/site", methods=["POST"])
    def minerador_site():
        d = request.get_json(silent=True) or {}
        cs = config_site(base)
        if str(d.get("pasta") or "").strip():  # vazio = deixa o site achar sozinho (não apaga a que ele achou)
            pasta = os.path.expanduser(str(d.get("pasta") or "").strip().strip('"'))
            if pasta and not os.path.isdir(pasta):
                return _erro("Essa pasta não existe neste computador.")
            cs["pasta"] = pasta
        for k in ("mostrar", "sem_claude"):
            if k in d:
                cs[k] = bool(d[k])
        if "horas" in d:
            try:
                cs["horas"] = max(0.0, float(d.get("horas") or 0))
            except (TypeError, ValueError):
                pass
        salvar_config_site(base, cs)
        e = estado(base)
        e["config"] = ler_config(cs.get("pasta") or "")
        return _ok(**e)

    @app.route("/minerador/achar", methods=["POST"])
    def minerador_achar():
        pasta = pasta_auto(base)
        e = estado(base)
        e["config"] = ler_config(pasta)
        return _ok(achou=bool(pasta and os.path.isfile(os.path.join(pasta, "tiktok_algo.py"))), **e)

    @app.route("/minerador/enviar-algo", methods=["POST"])
    def minerador_enviar_algo():
        """📥 O tiktok_algo.py (e, se quiser, a persona .json) vão pra pasta do minerador do site — uma vez só."""
        d = pasta_dados(base)
        n = 0
        for arq in request.files.getlist("arquivos"):
            nome = os.path.basename(arq.filename or "")
            if nome == "tiktok_algo.py" or (nome.endswith(".json") and "persona" in nome.lower()) or nome == "config_minerador.json":
                arq.save(os.path.join(d, nome))
                n += 1
        if not os.path.isfile(os.path.join(d, "tiktok_algo.py")):
            return _erro("Mande o arquivo tiktok_algo.py.")
        cs = config_site(base)
        cs["pasta"] = d
        salvar_config_site(base, cs)
        e = estado(base)
        e["config"] = ler_config(d)
        return _ok(enviados=n, **e)

    @app.route("/minerador/config", methods=["POST"])
    def minerador_config():
        pasta = config_site(base).get("pasta") or pasta_auto(base) or pasta_dados(base)
        txt = str((request.get_json(silent=True) or {}).get("texto") or "")
        try:
            j = json.loads(txt)
        except ValueError as exc:
            return _erro(f"JSON inválido: {exc}")
        if not isinstance(j, dict):
            return _erro("O config precisa ser um objeto JSON.")
        with open(cam_config(pasta), "w", encoding="utf-8") as f:
            json.dump(j, f, ensure_ascii=False, indent=2)
        return _ok()

    @app.route("/minerador/iniciar", methods=["POST"])
    def minerador_iniciar():
        d = request.get_json(silent=True) or {}
        cs = config_site(base)
        try:
            return _ok(**iniciar(base, cs.get("pasta") or "", float(d.get("horas", cs.get("horas")) or 0),
                                 bool(d.get("sem_claude", cs.get("sem_claude"))), bool(d.get("mostrar", cs.get("mostrar", True))),
                                 bool(d.get("reenviar"))))
        except (RC.RoteiroErro, OSError, ValueError) as exc:
            return _erro(exc)

    @app.route("/minerador/parar", methods=["POST"])
    def minerador_parar():
        parar(base, bool((request.get_json(silent=True) or {}).get("forcar")))
        return _ok(**estado(base))

    @app.route("/minerador/limpar-log", methods=["POST"])
    def minerador_limpar_log():
        try:
            open(log_cam(base), "w").close()
        except OSError:
            pass
        return _ok()

    @app.route("/minerador/videos")
    def minerador_videos():
        vs = videos(base, request.args.to_dict())
        todos = [RC.carregar(base, x["id"]) for x in RC.listar(base) if x.get("minerado")]
        nichos = sorted({str((r.get("minerador") or {}).get("nicho") or "") for r in todos} - {""})
        cont: Dict[str, int] = {}
        for r in todos:
            st = r.get("status") or "novo"
            cont[st] = cont.get(st, 0) + 1
        return _ok(videos=vs, nichos=nichos, contagem=cont, total=len(todos))

    @app.route("/minerador/video/<rid>/status", methods=["POST"])
    def minerador_status(rid: str):
        try:
            RC.marcar(base, rid, str((request.get_json(silent=True) or {}).get("status") or ""))
        except RC.RoteiroErro as exc:
            return _erro(exc)
        return _ok()

    @app.route("/minerador/miniatura/<rid>")
    def minerador_miniatura(rid: str):
        try:
            cam = RC._cam(base, rid)[:-5] + ".jpg"
        except RC.RoteiroErro:
            abort(404)
        if not os.path.isfile(cam):
            abort(404)
        return send_file(cam, mimetype="image/jpeg", max_age=3600)
