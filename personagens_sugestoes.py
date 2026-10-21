"""🆕👗 v84_221 — poses que FALTAM e o VISUAL do vídeo (personagens no editor).

Quando a 🤖 IA do editor põe as personagens no vídeo, ela pode dizer:
  • "nenhuma pose serve pra esta fala" → descreve a pose ideal (pose_nova). A aparição usa a mais parecida por enquanto.
  • "o tema pede outra roupa" (lugar quente → roupa de praia; frio → casaco…) → o visual do vídeo, um que a personagem já
    tem ou um novo (nome + descrição da roupa/penteado). As aparições passam a usar a versão da pose nesse visual; a que
    ainda não existe fica sugerida.

Nada vai pro Flow sozinho: o botão "🎨 Gerar as poses sugeridas" do Estúdio cria o visual / as poses no projeto da
personagem (galeria 🧍 Personagens — ficam lá pra outros vídeos) e manda gerar. A boca de cada uma sai junto (👄 boca
automática do projeto). Quando a pose fica pronta, a aparição troca sozinha (o Estúdio confere ao atualizar a aba).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple


def sugestoes(job: Dict[str, Any]) -> List[Dict[str, Any]]:
    """As aparições com pose sugerida (ainda não geradas) e as que estão esperando a pose ficar pronta."""
    out = []
    for ov in job.get("overlays") or []:
        if ov.get("origem") != "personagem":
            continue
        s = ov.get("sugestao")
        if isinstance(s, dict) or isinstance(ov.get("pendente"), dict):
            out.append({"oid": ov["id"], "personagem": ov.get("personagem"), "nome": ov.get("nome_personagem"),
                        "start": ov.get("start"), "sugestao": s if isinstance(s, dict) else None,
                        "pendente": ov.get("pendente") if isinstance(ov.get("pendente"), dict) else None})
    return out


def resumo(job: Dict[str, Any]) -> Dict[str, Any]:
    sg = sugestoes(job)
    vis = (job.get("personagens_canal") or {}).get("visuais_video") or {}
    return {"n_sugeridas": sum(1 for x in sg if x["sugestao"]), "n_pendentes": sum(1 for x in sg if x["pendente"]),
            "novas": sum(1 for x in sg if (x["sugestao"] or {}).get("tipo") == "nova"),
            "visual": sum(1 for x in sg if (x["sugestao"] or {}).get("tipo") == "visual"),
            "fantasias": [(x["sugestao"].get("visual_novo") or {}).get("nome") for x in sg if (x["sugestao"] or {}).get("tipo") == "fantasia"],
            "visuais": {k: (v.get("novo") or {}).get("nome") or v.get("nome") or v.get("slug") for k, v in vis.items()
                        if v.get("slug") or v.get("novo")}}


def gerar(job: Dict[str, Any], base: str, quantidade: str = "x1") -> Dict[str, Any]:
    """🎨 Cria no projeto de cada personagem o visual / as poses sugeridas e manda gerar (o botão do Estúdio).
    → {"enviadas", "poses", "avisos"}"""
    import personagens_pod as pp
    por_pid: Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]] = {}
    for ov in job.get("overlays") or []:
        s = ov.get("sugestao")
        if ov.get("origem") == "personagem" and isinstance(s, dict) and ov.get("projeto_id"):
            por_pid.setdefault(ov["projeto_id"], []).append((ov, s))
    if not por_pid:
        return {"enviadas": 0, "poses": 0, "avisos": ["Nenhuma pose sugerida neste vídeo."]}
    avisos: List[str] = []
    total_env = total_poses = 0
    for pid, lista in por_pid.items():
        try:
            p = pp.carregar(pid, base)
        except pp.PersErro as exc:
            avisos.append(f"projeto {pid}: {exc}")
            continue
        criadas: List[str] = []
        visual_slug: Dict[str, str] = {}  # nome/slug sugerido → slug real no projeto

        def _visual(s: Dict[str, Any]) -> str:
            novo = s.get("visual_novo") if isinstance(s.get("visual_novo"), dict) else None
            chave = s.get("visual") or (novo or {}).get("nome") or ""
            if not chave:
                return ""
            if chave in visual_slug:
                return visual_slug[chave]
            if s.get("visual") and pp.visual(pp.carregar(pid, base), s["visual"]):
                visual_slug[chave] = s["visual"]
            elif novo:
                r = pp.criar_visual(pid, novo.get("nome") or "visual", novo.get("descricao_en") or "", novo.get("descricao_pt") or "",
                                    None, base)
                visual_slug[chave] = r["visual"]
                criadas.extend(r["novas"])
            else:
                visual_slug[chave] = ""
            return visual_slug[chave]

        for ov, s in lista:
            try:
                if s.get("tipo") == "fantasia":  # 🎭 v84_222: a fantasia de piada (só a mestra, na pose da piada)
                    nv = s.get("visual_novo") or {}
                    r = pp.criar_visual(pid, nv.get("nome") or "fantasia", nv.get("descricao_en") or "", nv.get("descricao_pt") or "",
                                        None, base, tipo="fantasia", pose_mestra=s.get("pose_base") or "")
                    arq = pp.visual(pp.carregar(pid, base), r["visual"])["mestra"]
                    criadas.extend(a for a in r["novas"] if a not in criadas)  # já existe com imagem: só troca
                    ov["pendente"] = {"projeto_id": pid, "arquivo": arq}
                    ov.pop("sugestao", None)
                    continue
                vs = _visual(s)
                if s.get("tipo") == "nova":
                    arq = pp.adicionar_pose(pid, s.get("descricao_en") or "", s.get("descricao_pt") or "", vs, base=base)
                elif s.get("tipo") == "visual" and vs and s.get("pose_base"):
                    r = pp.criar_visual(pid, pp.visual(pp.carregar(pid, base), vs)["nome"], "", "", [s["pose_base"]], base)
                    arq = f"{s['pose_base'][:-4]}__{vs}.png"
                    criadas.extend(a for a in r["novas"] if a not in criadas)
                else:
                    continue
            except pp.PersErro as exc:
                avisos.append(f"{ov.get('nome_personagem') or pid}: {exc}")
                continue
            criadas.append(arq)
            ov["pendente"] = {"projeto_id": pid, "arquivo": arq}
            ov.pop("sugestao", None)
        criadas = list(dict.fromkeys(criadas))
        if not criadas:
            continue
        total_poses += len(criadas)
        try:
            r = pp.enviar(pid, criadas, "", base, quantidade=quantidade)
            total_env += int(r.get("enviadas") or 0)
            if r.get("aviso"):
                avisos.append(r["aviso"])
        except pp.PersErro as exc:
            avisos.append(f"{p.get('nome')}: {exc}")
    return {"enviadas": total_env, "poses": total_poses, "avisos": avisos}


def atualizar_pendentes(job: Dict[str, Any], base: str, job_dir: str, job_id: Optional[str] = None) -> int:
    """A pose sugerida ficou pronta → a aparição troca pra ela (olhando pro centro; a boca vem quando ficar pronta).
    → quantas trocaram."""
    import personagens_editor as PE
    import personagens_pod as pp
    n = 0
    cache: Dict[str, Any] = {}
    for ov in job.get("overlays") or []:
        pend = ov.get("pendente") if ov.get("origem") == "personagem" else None
        if not isinstance(pend, dict):
            continue
        pid, arq = pend.get("projeto_id"), pend.get("arquivo")
        try:
            if pid not in cache:
                pp.sincronizar(pid, base)  # traz o que o Flow terminou (e segue a cadeia: boca, poses do visual)
                cache[pid] = pp.carregar(pid, base)
            p = cache[pid]
        except Exception:  # noqa: BLE001
            continue
        it = p["imagens"].get(arq) or {}
        if it.get("estado") in ("erro", "descartada"):
            ov["pendente"] = dict(pend, erro=it.get("erro") or "não deu certo — gere de novo na galeria da personagem")
            continue
        if it.get("estado") not in ("pronta", "aprovada") or not pp.arquivo_atual(p, arq, base):
            continue
        poses = PE.poses_prontas(p, base)
        pose = next((o for o in poses if o["arquivo"] == arq), None)
        if not pose:
            continue
        try:
            PE.normalizar_olhar([{"poses": [pose]}], base, False, True, job_id)  # 👀 a IA olha pra que lado ela vira
        except Exception:  # noqa: BLE001
            pass
        pasta = os.path.join(job_dir, "personagens")
        os.makedirs(pasta, exist_ok=True)
        try:
            ov["source"] = {"source": "local_file", "value": PE._copiar(pose["caminho"], pasta), "kind": "image"}
        except OSError:
            continue
        ov["pose"] = arq
        ov["pose_original"] = pose["caminho"]
        ov["descricao_pose"] = pose.get("descricao") or ""
        ov["boca_path"] = PE._copiar(pose["boca"], pasta) if pose.get("boca") else None
        quer = PE.olhar_para(ov.get("lado") or "esquerda")
        ov["espelhar"] = bool(pose.get("lado") in ("esq", "dir") and pose["lado"] != quer)  # virada pro lado errado → 🪞
        if pose.get("boca"):
            ov.pop("pendente", None)
        else:
            ov["pendente"] = dict(pend, so_boca=True)  # a pose já entrou; falta a boca
        n += 1
    # a boca que chegou depois
    for ov in job.get("overlays") or []:
        pend = ov.get("pendente")
        if isinstance(pend, dict) and pend.get("so_boca") and pend.get("projeto_id") in cache:
            p = cache[pend["projeto_id"]]
            pose = next((o for o in PE.poses_prontas(p, base) if o["arquivo"] == pend["arquivo"]), None)
            if pose and pose.get("boca"):
                pasta = os.path.join(job_dir, "personagens")
                ov["boca_path"] = PE._copiar(pose["boca"], pasta)
                ov.pop("pendente", None)
                n += 1
    return n
