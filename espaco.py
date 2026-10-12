"""
espaco.py
=========

🧹 ESPAÇO EM DISCO — quanto cada parte do site ocupa e o que dá pra apagar.

Cada CATEGORIA é uma pasta (ou um grupo de coisas) que o site enche enquanto você usa:
projetos de vídeo, caches de montagem, vozes geradas, capturas, Modelos de vídeo,
análises de canal, cache da IA, lixo do Python… A página lista o total e cada categoria;
dentro dela, cada item com o tamanho — e dá pra apagar um item, a categoria inteira ou
tudo de todas as categorias de uma vez.

Regras de segurança:
  • só apaga DENTRO da pasta da categoria (nada de "..", link ou caminho de fora);
  • projeto em andamento (transcrevendo, montando…) nunca é apagado;
  • categorias PROTEGIDAS (perfis de voz e modelos baixados, sessão da conta Google do Flow)
    não entram no "apagar tudo" — só item por item, com aviso;
  • "🧽 caches" apaga só o que o site refaz sozinho (clipes pré-baixados, prévias guardadas,
    clipes prontos da montagem, arquivos intermediários): o projeto continua abrindo e montando.
"""
from __future__ import annotations

import os
import shutil
import time
from typing import Any, Callable, Dict, List, Optional

# dentro de jobs/<id>: o que é cache (o site refaz) — o resto (estado, narração, uploads) é o projeto
CACHES_DO_PROJETO = ("prebaixados", "previas_cache", "clips_prontos", "clips", "downloads", "dp_tex", "cenas",
                     "destaques", "editoriais", "graficos", "censura", "graficos_previa", "editorial_previa")
_PREFIXOS_INTERMEDIARIOS = ("_concat", "_com_", "_with_", "_narracao_", "_video_only")

CATEGORIAS: List[Dict[str, Any]] = [
    {"id": "projetos", "nome": "🎬 Projetos de vídeo", "pasta": "jobs",
     "desc": "Cada projeto da 🗂️ Galeria: narração, uploads, estado do editor, caches e o vídeo final (outputs/<id>…). "
             "Apagar um projeto tira ele da Galeria."},
    {"id": "caches", "nome": "🧽 Caches dos projetos", "pasta": "jobs", "virtual": True, "regeneravel": True,
     "desc": "Só o que o site refaz sozinho dentro de cada projeto: clipes pré-baixados, prévias guardadas, clipes prontos "
             "da montagem e arquivos intermediários. O projeto continua abrindo; a próxima montagem baixa de novo."},
    {"id": "saidas", "nome": "📤 Outras saídas", "pasta": "outputs",
     "desc": "Vozes geradas, capturas de página, cortes do YouTube, downloads de redes sociais, transcrições avulsas, "
             "textos animados… (os vídeos finais dos projetos contam em 🎬 Projetos)."},
    {"id": "uploads", "nome": "⬆️ Uploads", "pasta": "uploads", "desc": "Arquivos enviados pelo site."},
    {"id": "narracoes", "nome": "📝 Roteiro para Áudio", "pasta": "narracoes", "desc": "Projetos de narração e os áudios deles."},
    {"id": "conversas", "nome": "💬 Conversas / dublagem", "pasta": "conversas", "desc": "Projetos de conversa e dublagem."},
    {"id": "roteiros_yt", "nome": "📜 Roteiro do YouTube", "pasta": "roteiros_yt", "desc": "Projetos, áudios baixados e transcrições."},
    {"id": "vendas", "nome": "🛒 Vídeo de venda", "pasta": "vendas", "desc": "Projetos de venda e as fotos baixadas."},
    {"id": "dossies", "nome": "🕵️ Modelos de vídeo", "pasta": "dossies", "desc": "Projetos com as matérias, imagens e PDFs baixados."},
    {"id": "modelados", "nome": "🎞️ Vídeos modelados", "pasta": "modelados", "desc": "Projetos com frames e animações."},
    {"id": "analises_canal", "nome": "📊 Análises de canal", "pasta": "analises_canal", "desc": "Dados e transcrições coletados dos canais."},
    {"id": "niche_miner", "nome": "⛏ Niche Miner", "pasta": "niche_miner/data", "desc": "Banco da biblioteca de buscas e o log do Niche Miner."},
    {"id": "ia_cache", "nome": "🤖 Cache da IA", "pasta": "ia_cache", "regeneravel": True,
     "desc": "Respostas guardadas da IA (pra não pagar duas vezes pela mesma pergunta). Apagar só faz perguntar de novo."},
    {"id": "downloads", "nome": "⬇️ Downloads temporários", "pasta": "downloads", "regeneravel": True, "desc": "Arquivos baixados de passagem."},
    {"id": "chrome_downloads", "nome": "🌐 Downloads do navegador", "pasta": ".chrome_downloads", "regeneravel": True,
     "desc": "O que o navegador automático baixou de passagem."},
    {"id": "chamadas", "nome": "📣 Chamadas padrão", "pasta": "chamadas_padrao", "desc": "Vídeos de 'inscreva-se' e de venda salvos."},
    {"id": "python", "nome": "🐍 Lixo do Python", "pasta": ".", "virtual": True, "regeneravel": True,
     "desc": "__pycache__ e .pytest_cache: o Python refaz sozinho."},
    {"id": "modelos_voz", "nome": "🗣️ Modelos de voz e perfis de voz", "pasta": "toolkit/tts/models", "protegido": True,
     "desc": "Modelos baixados (Piper/Kokoro/XTTS) e os PERFIS DE VOZ que você gravou. Apagar um modelo obriga a baixar de novo; "
             "um perfil de voz apagado não volta."},
    {"id": "flow", "nome": "🔑 Sessão do Google Flow", "pasta": "flow_dados", "protegido": True,
     "desc": "O login da conta Google usada no Flow. Apagar = entrar na conta de novo."},
]
CAT = {c["id"]: c for c in CATEGORIAS}


class EspacoError(Exception):
    pass


# ------------------------------------------------------------------ tamanho
def tamanho(caminho: str) -> int:
    """Bytes de um arquivo ou pasta (sem seguir links)."""
    try:
        if os.path.islink(caminho):
            return 0
        if os.path.isfile(caminho):
            return os.path.getsize(caminho)
    except OSError:
        return 0
    total = 0
    pilha = [caminho]
    while pilha:
        p = pilha.pop()
        try:
            with os.scandir(p) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            pilha.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def fmt(b: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024 or u == "TB":
            return (f"{b:.0f} {u}" if u in ("B", "KB") else f"{b:.1f} {u}").replace(".", ",")
        b /= 1024.0
    return f"{b:.1f} TB"


def _mtime(caminho: str) -> float:
    try:
        return os.path.getmtime(caminho)
    except OSError:
        return 0.0


def _dentro(base: str, raiz: str, caminho: str) -> bool:
    raiz_r = os.path.realpath(os.path.join(base, raiz))
    alvo = os.path.realpath(caminho)
    return alvo != raiz_r and os.path.commonpath([alvo, raiz_r]) == raiz_r


def _apagar_caminho(caminho: str) -> int:
    b = tamanho(caminho)
    try:
        if os.path.isdir(caminho) and not os.path.islink(caminho):
            shutil.rmtree(caminho, ignore_errors=True)
        elif os.path.lexists(caminho):
            os.remove(caminho)
    except OSError:
        return 0
    return b if not os.path.lexists(caminho) else 0


# ------------------------------------------------------------------ contexto vindo do app
class Contexto:
    """O que o espaço precisa saber do app: projetos em memória e quem está rodando."""

    def __init__(self, base: str, jobs: Optional[Dict[str, Dict[str, Any]]] = None,
                 em_andamento: Callable[[Dict[str, Any]], bool] = lambda j: False,
                 apagar_projeto: Optional[Callable[[str], None]] = None):
        self.base = base
        self.jobs = jobs if jobs is not None else {}
        self.em_andamento = em_andamento
        self.apagar_projeto = apagar_projeto

    def job_ocupado(self, jid: str) -> bool:
        j = self.jobs.get(jid)
        return bool(j) and self.em_andamento(j)

    def nome_job(self, jid: str) -> str:
        j = self.jobs.get(jid) or {}
        return j.get("nome_projeto") or j.get("original_filename") or j.get("audio_filename") or jid


def _pasta(ctx: Contexto, cat: Dict[str, Any]) -> str:
    return os.path.join(ctx.base, cat["pasta"])


def _finais_do_job(ctx: Contexto, jid: str) -> List[str]:
    out = os.path.join(ctx.base, "outputs")
    try:
        return [os.path.join(out, n) for n in os.listdir(out) if n.startswith(jid) and os.path.isfile(os.path.join(out, n))]
    except OSError:
        return []


def _caches_do_job(pasta_job: str) -> List[str]:
    out = []
    try:
        for n in os.listdir(pasta_job):
            c = os.path.join(pasta_job, n)
            if (n in CACHES_DO_PROJETO and os.path.isdir(c)) or (os.path.isfile(c) and n.startswith(_PREFIXOS_INTERMEDIARIOS)):
                out.append(c)
    except OSError:
        pass
    return out


def _pycaches(base: str) -> List[str]:
    out = []
    for raiz, pastas, _ in os.walk(base):
        rel = os.path.relpath(raiz, base).replace("\\", "/")
        if rel.split("/")[0] in ("jobs", "outputs", "uploads", ".git", "flow_dados"):
            pastas[:] = []
            continue
        for p in list(pastas):
            if p in ("__pycache__", ".pytest_cache"):
                out.append(os.path.join(raiz, p))
                pastas.remove(p)
    return out


# ------------------------------------------------------------------ itens de cada categoria
def itens(ctx: Contexto, cid: str) -> List[Dict[str, Any]]:
    cat = CAT.get(cid)
    if not cat:
        raise EspacoError("Categoria não encontrada.")
    pasta = _pasta(ctx, cat)
    out: List[Dict[str, Any]] = []
    if cid == "python":
        for p in _pycaches(ctx.base):
            out.append({"id": os.path.relpath(p, ctx.base).replace("\\", "/"), "nome": os.path.relpath(p, ctx.base),
                        "bytes": tamanho(p), "quando": _mtime(p)})
    elif cid == "caches":
        if os.path.isdir(pasta):
            for jid in os.listdir(pasta):
                pj = os.path.join(pasta, jid)
                if not os.path.isdir(pj):
                    continue
                cs = _caches_do_job(pj)
                b = sum(tamanho(c) for c in cs)
                if b:
                    out.append({"id": jid, "nome": ctx.nome_job(jid), "bytes": b, "quando": _mtime(pj),
                                "detalhe": ", ".join(sorted(os.path.basename(c) for c in cs))[:200],
                                "em_uso": ctx.job_ocupado(jid)})
    else:
        if not os.path.isdir(pasta):
            return []
        finais_de_jobs = set()
        if cid == "saidas":
            ids = set(os.listdir(os.path.join(ctx.base, "jobs"))) if os.path.isdir(os.path.join(ctx.base, "jobs")) else set()
            finais_de_jobs = {n for n in os.listdir(pasta) if any(n.startswith(j) for j in ids)}
        for n in os.listdir(pasta):
            if n in finais_de_jobs:
                continue
            c = os.path.join(pasta, n)
            if os.path.islink(c):
                continue
            b = tamanho(c)
            it = {"id": n, "nome": n, "bytes": b, "quando": _mtime(c), "pasta": os.path.isdir(c)}
            if cid == "projetos" and os.path.isdir(c):
                finais = _finais_do_job(ctx, n)
                it["bytes"] = b + sum(tamanho(f) for f in finais)
                it["nome"] = ctx.nome_job(n)
                it["detalhe"] = (f"vídeo final {fmt(sum(tamanho(f) for f in finais))} · " if finais else "") + \
                                f"caches {fmt(sum(tamanho(x) for x in _caches_do_job(c)))}"
                it["em_uso"] = ctx.job_ocupado(n)
            out.append(it)
    return sorted(out, key=lambda x: -x["bytes"])


def resumo(ctx: Contexto) -> Dict[str, Any]:
    cats = []
    for c in CATEGORIAS:
        its = itens(ctx, c["id"])
        cats.append({"id": c["id"], "nome": c["nome"], "desc": c["desc"], "pasta": c["pasta"],
                     "protegido": bool(c.get("protegido")), "regeneravel": bool(c.get("regeneravel")),
                     "virtual": bool(c.get("virtual")), "bytes": sum(i["bytes"] for i in its), "n": len(its)})
    # "caches" está DENTRO de "projetos": não soma duas vezes no total
    total = sum(c["bytes"] for c in cats if c["id"] != "caches")
    try:
        disco = shutil.disk_usage(ctx.base)
        disco_d = {"total": disco.total, "livre": disco.free, "usado": disco.used}
    except OSError:
        disco_d = None
    return {"categorias": cats, "total": total, "disco": disco_d, "quando": time.time()}


# ------------------------------------------------------------------ apagar
def apagar_item(ctx: Contexto, cid: str, iid: str) -> int:
    cat = CAT.get(cid)
    if not cat:
        raise EspacoError("Categoria não encontrada.")
    iid = str(iid or "").replace("\\", "/")
    if not iid or iid.startswith("/") or ".." in iid.split("/"):
        raise EspacoError("Item inválido.")
    if cid == "python":
        alvo = os.path.join(ctx.base, iid)
        if os.path.basename(alvo) not in ("__pycache__", ".pytest_cache") or not _dentro(ctx.base, ".", alvo):
            raise EspacoError("Item inválido.")
        return _apagar_caminho(alvo)
    if "/" in iid:
        raise EspacoError("Item inválido.")
    pasta = _pasta(ctx, cat)
    alvo = os.path.join(pasta, iid)
    if not _dentro(ctx.base, cat["pasta"], alvo) or not os.path.lexists(alvo):
        raise EspacoError("Item não encontrado.")
    if cid in ("projetos", "caches") and ctx.job_ocupado(iid):
        raise EspacoError("Esse projeto está em andamento — espere terminar (ou cancele) antes de apagar.")
    if cid == "caches":
        return sum(_apagar_caminho(c) for c in _caches_do_job(alvo))
    if cid == "projetos":
        b = tamanho(alvo) + sum(tamanho(f) for f in _finais_do_job(ctx, iid))
        if ctx.apagar_projeto:
            ctx.apagar_projeto(iid)  # tira da Galeria e apaga jobs/<id> + outputs/<id>*
        else:
            _apagar_caminho(alvo)
            for f in _finais_do_job(ctx, iid):
                _apagar_caminho(f)
        return b if not os.path.exists(alvo) else 0
    return _apagar_caminho(alvo)


def apagar_categoria(ctx: Contexto, cid: str, incluir_protegidas: bool = False) -> Dict[str, Any]:
    cat = CAT.get(cid)
    if not cat:
        raise EspacoError("Categoria não encontrada.")
    if cat.get("protegido") and not incluir_protegidas:
        raise EspacoError("Categoria protegida: apague item por item.")
    liberado, pulados, apagados = 0, [], 0
    for it in itens(ctx, cid):
        if it.get("em_uso"):
            pulados.append(it["nome"])
            continue
        try:
            liberado += apagar_item(ctx, cid, it["id"])
            apagados += 1
        except EspacoError as exc:
            pulados.append(f"{it['nome']} ({exc})")
    return {"liberado": liberado, "apagados": apagados, "pulados": pulados}


def apagar_tudo(ctx: Contexto) -> Dict[str, Any]:
    """Todas as categorias, MENOS as protegidas (perfis de voz/modelos e a sessão do Flow).
    'caches' fica de fora porque 'projetos' já apaga os projetos inteiros."""
    total = {"liberado": 0, "apagados": 0, "pulados": []}
    for c in CATEGORIAS:
        if c.get("protegido") or c["id"] == "caches":
            continue
        r = apagar_categoria(ctx, c["id"])
        total["liberado"] += r["liberado"]
        total["apagados"] += r["apagados"]
        total["pulados"] += r["pulados"]
    return total


# ------------------------------------------------------------------ rotas
def registrar(app, base_dir: str, ctx_fn: Callable[[], Contexto]) -> None:
    from flask import jsonify, render_template, request

    @app.route("/espaco")
    def espaco_page():
        return render_template("espaco.html", r=resumo(ctx_fn()), fmt=fmt, categorias=CATEGORIAS)

    @app.route("/espaco/resumo")
    def espaco_resumo():
        return jsonify(resumo(ctx_fn()))

    @app.route("/espaco/<cid>")
    def espaco_categoria(cid: str):
        if cid not in CAT:
            return "Categoria não encontrada.", 404
        its = itens(ctx_fn(), cid)
        return render_template("espaco_categoria.html", cat=CAT[cid], itens=its, total=sum(i["bytes"] for i in its), fmt=fmt,
                               time=time)

    @app.route("/espaco/<cid>/apagar", methods=["POST"])
    def espaco_apagar(cid: str):
        corpo = request.get_json(silent=True) or request.form
        ctx = ctx_fn()
        try:
            if corpo.get("tudo") in (True, "1", "on", "true"):
                r = apagar_categoria(ctx, cid)
            else:
                ids = corpo.get("ids") if isinstance(corpo.get("ids"), list) else [corpo.get("id")]
                r = {"liberado": 0, "apagados": 0, "pulados": []}
                for iid in ids:
                    try:
                        r["liberado"] += apagar_item(ctx, cid, iid)
                        r["apagados"] += 1
                    except EspacoError as exc:
                        r["pulados"].append(f"{iid}: {exc}")
        except EspacoError as exc:
            return jsonify({"erro": str(exc)}), 400
        r["liberado_fmt"] = fmt(r["liberado"])
        return jsonify(dict(r, ok=True))

    @app.route("/espaco/apagar-tudo", methods=["POST"])
    def espaco_apagar_tudo():
        corpo = request.get_json(silent=True) or request.form
        if (corpo.get("confirmar") or "").strip().upper() != "APAGAR":
            return jsonify({"erro": "Digite APAGAR pra confirmar."}), 400
        r = apagar_tudo(ctx_fn())
        r["liberado_fmt"] = fmt(r["liberado"])
        return jsonify(dict(r, ok=True))
