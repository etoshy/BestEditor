"""📑 Clonar projeto (v84_146) — uma cópia independente pra trabalhar o mesmo material por outro ângulo.

  🕵️ Modelo de vídeo  → copia fontes, fotos (arquivos), elenco, perguntas, roteiro e histórico. A cópia pode ganhar
                        outro roteiro/foco sem mexer no original.
  📝 Roteiro do YouTube → copia transcrição, análise, roteiro e cenas.
  🎬 Projeto do editor  → copia a edição inteira (narração, legendas, trechos, prévias, overlays, cortes) pra testar
                        outra montagem. O vídeo final já montado NÃO é copiado (a cópia monta o dela).
O original nunca é alterado. A cópia guarda de onde veio ("clonado_de").
"""
from __future__ import annotations

import copy
import os
import re
import shutil
import time
import uuid
from typing import Any, Dict, Optional


def _nome(base_nome: str, nome: str, existentes: Any = None) -> str:
    """Nome da cópia: o que você escreveu; sem nome, o MESMO título + o próximo número (“Título 2”, “Título 3”…).
    v84_231: antes era “(cópia)”."""
    if (nome or "").strip():
        return nome.strip()[:120]
    raiz = re.sub(r"\s+(\(cópia\)|\d{1,3})$", "", (base_nome or "Projeto").strip())[:110] or "Projeto"
    maior = 1
    for n in existentes or []:
        n = str(n or "").strip()
        m = re.fullmatch(re.escape(raiz) + r"\s+(\d{1,3})", n)
        if m:
            maior = max(maior, int(m.group(1)))
    return f"{raiz} {maior + 1}"


def clonar_dossie(base: str, pid: str, nome: str = "") -> Dict[str, Any]:
    import dossies as ds
    p = ds.carregar(base, pid)
    novo = uuid.uuid4().hex[:10]
    shutil.copytree(ds._pasta(base, pid), ds._pasta(base, novo))
    q = copy.deepcopy(p)
    q.update(id=novo, criado=time.time(), apelido=_nome(ds.nome_do_projeto(p), nome, [x["nome"] for x in ds.listar(base)]),
             clonado_de=pid)
    ds.marcar_mudanca(q, "📑 clonado", f"cópia de “{ds.nome_do_projeto(p)}”")
    ds.salvar(base, q)
    return {"tipo": "dossie", "id": novo, "nome": q["apelido"], "url": f"/modelos-video/{novo}"}


def clonar_roteiro(base: str, pid: str, nome: str = "") -> Dict[str, Any]:
    import roteiros_yt as ry
    p = ry.carregar_projeto(base, pid)
    novo = uuid.uuid4().hex[:10]
    shutil.copytree(ry._pasta(base, pid), ry._pasta(base, novo))
    q = copy.deepcopy(p)
    q.update(id=novo, criado=time.time(), titulo=_nome(p.get("titulo") or p.get("url") or "", nome,
                                                      [x["titulo"] for x in ry.listar_projetos(base)]), clonado_de=pid)
    ry.marcar_mudanca(q, "📑 clonado", f"cópia de “{p.get('titulo') or pid}”")
    ry.salvar_projeto(base, q)
    return {"tipo": "roteiro", "id": novo, "nome": q["titulo"], "url": f"/roteiros-yt/{novo}"}


def _trocar_caminhos(x: Any, antigo: str, novo: str) -> Any:
    """Troca a pasta do job antigo pela nova em todos os textos do job (caminhos de arquivos)."""
    if isinstance(x, str):
        return x.replace(antigo, novo) if antigo in x else x
    if isinstance(x, list):
        return [_trocar_caminhos(v, antigo, novo) for v in x]
    if isinstance(x, dict):
        return {k: _trocar_caminhos(v, antigo, novo) for k, v in x.items()}
    return x


OCUPADO = ("transcrevendo", "buscando_previas", "montando", "renderizando", "processando")


def clonar_job(jobs: Dict[str, Any], job_dir, salvar_estado, job_id: str, nome: str = "") -> Dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise ValueError("Projeto não encontrado.")
    if job.get("status") in OCUPADO:
        raise ValueError("O projeto está ocupado (buscando prévias / montando) — espere terminar pra clonar.")
    novo = uuid.uuid4().hex[:12]
    origem, destino = job_dir(job_id), job_dir(novo)
    final = os.path.abspath(job.get("output_path") or "") if job.get("output_path") else ""

    def ignorar(pasta: str, nomes):
        return [n for n in nomes if os.path.abspath(os.path.join(pasta, n)) == final or n == "state.json"]

    if os.path.isdir(origem):
        shutil.copytree(origem, destino, ignore=ignorar)
    else:
        os.makedirs(destino, exist_ok=True)
    q = _trocar_caminhos(copy.deepcopy(dict(job)), os.path.abspath(origem), os.path.abspath(destino))
    q = _trocar_caminhos(q, origem, destino)
    for k in ("output_path", "progresso_montagem", "erro_montagem", "error"):
        q.pop(k, None)
    q.update(job_id=novo, clonado_de=job_id, criado_em=time.time(),
             nome_projeto=_nome(job.get("nome_projeto") or job.get("original_filename") or job_id, nome,
                                [j.get("nome_projeto") for j in jobs.values() if isinstance(j, dict)]))
    if q.get("status") in ("concluido", "pronto", "erro"):
        q["status"] = "pronto_para_editar"
    jobs[novo] = q
    salvar_estado(novo)
    return {"tipo": "job", "id": novo, "nome": q["nome_projeto"], "url": f"/job/{novo}/edit-segments"}


def registrar(app, base_dir: str, jobs: Dict[str, Any], job_dir, salvar_estado) -> None:
    from flask import jsonify, request

    @app.route("/clonar/<tipo>/<pid>", methods=["POST"])
    def clonar_rota(tipo: str, pid: str):
        nome = str((request.get_json(silent=True) or {}).get("nome") or "")
        try:
            if tipo == "dossie":
                r = clonar_dossie(base_dir, pid, nome)
            elif tipo == "roteiro":
                r = clonar_roteiro(base_dir, pid, nome)
            elif tipo == "job":
                r = clonar_job(jobs, job_dir, salvar_estado, pid, nome)
            else:
                return jsonify({"erro": "Tipo inválido."}), 400
        except (ValueError, OSError) as exc:
            return jsonify({"erro": str(exc)[:300]}), 400
        except Exception as exc:  # noqa: BLE001 — DossieError / RoteiroError
            return jsonify({"erro": str(exc)[:300]}), 404
        return jsonify({"ok": True, **r})
