"""
personagens_pod.py — 🧍 Personagens no pod (v84_183, prova de conceito)
========================================================================

Gera as poses PNG de uma personagem do canal (reações, objetos, "_boca") no pod `personagens-pod`
(Qwen-Image-Edit-2511 + BiRefNet), uma personagem por projeto:

  1. Novo projeto: o JSON de poses (formato personagens_pod_v1) + as imagens de referência (a ficha, um detalhe);
  2. ⭐ gera a pose mestre (a do JSON com "mestre": true) e você refaz até ficar igual à ficha → "usar como mestre";
  3. ▶ gera o resto: cada pose vai com a ficha + a mestre (a personagem fica igual); as "_boca" são edição da pose
     pronta (só a boca aberta);
  4. galeria: ✔ aprovar, 🔁 refazer (com uma correção opcional), ◀ ▶ versões anteriores, 🗑 descartar;
  5. ⬇ baixar as aprovadas (.zip, com os nomes do JSON).

Tudo fica em personagens_pod/<id>/ (projeto.json, refs/, imagens/ com todas as versões).
"""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import threading
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple

_BASE = os.path.dirname(os.path.abspath(__file__))
FORMATO = "personagens_pod_v1"
MAX_REFS = 3          # o Qwen-Image-Edit-2511 trabalha com até 3 imagens: com a mestre, ficam 2 referências
ESTADOS_ESPERA = ("fila", "gerando")
_TRAVA = threading.RLock()


class PersErro(Exception):
    pass


def pasta_raiz(base: str = _BASE) -> str:
    return os.environ.get("PERSONAGENS_POD_DIR") or os.path.join(base, "personagens_pod")


def _pasta(pid: str, base: str = _BASE) -> str:
    if not re.fullmatch(r"[0-9a-f]{6,32}", pid or ""):
        raise PersErro("projeto inválido")
    return os.path.join(pasta_raiz(base), pid)


def _nome_ok(n: str) -> str:
    n = os.path.basename(str(n or "")).strip()
    if not re.fullmatch(r"[\w\-. ]{1,120}", n) or n.startswith("."):
        raise PersErro(f"nome de arquivo inválido: {n!r}")
    return n


# ------------------------------------------------------------------ guardar
def carregar(pid: str, base: str = _BASE) -> Dict[str, Any]:
    try:
        with open(os.path.join(_pasta(pid, base), "projeto.json"), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise PersErro("Projeto não encontrado.")


def salvar(p: Dict[str, Any], base: str = _BASE) -> None:
    d = _pasta(p["id"], base)
    os.makedirs(d, exist_ok=True)
    p["atualizado"] = time.time()
    tmp = os.path.join(d, f"projeto.json.{secrets.token_hex(3)}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    try:
        import arquivo_seguro
        arquivo_seguro.trocar(tmp, os.path.join(d, "projeto.json"))
    except ImportError:
        os.replace(tmp, os.path.join(d, "projeto.json"))


def listar(base: str = _BASE) -> List[Dict[str, Any]]:
    raiz = pasta_raiz(base)
    out = []
    for pid in os.listdir(raiz) if os.path.isdir(raiz) else []:
        try:
            p = carregar(pid, base)
        except Exception:  # noqa: BLE001
            continue
        out.append(dict(p, resumo=resumo(p)))
    return sorted(out, key=lambda x: -x.get("atualizado", 0))


def excluir(pid: str, base: str = _BASE) -> None:
    import shutil
    carregar(pid, base)
    shutil.rmtree(_pasta(pid, base), ignore_errors=True)


def resumo(p: Dict[str, Any]) -> Dict[str, int]:
    cont: Dict[str, int] = {}
    for it in p.get("imagens", {}).values():
        cont[it["estado"]] = cont.get(it["estado"], 0) + 1
    cont["total"] = len(p.get("imagens", {}))
    return cont


# ------------------------------------------------------------------ criar
def ler_json(texto: str) -> Dict[str, Any]:
    try:
        d = json.loads(texto)
    except ValueError as exc:
        raise PersErro(f"O JSON não abriu: {exc}")
    if not isinstance(d, dict) or not isinstance(d.get("poses"), list) or not d["poses"]:
        raise PersErro("O JSON precisa ter a lista \"poses\" (formato personagens_pod_v1).")
    vistos = set()
    for p in d["poses"]:
        if not isinstance(p, dict) or not p.get("arquivo") or not p.get("prompt"):
            raise PersErro("Cada pose precisa de \"arquivo\" e \"prompt\".")
        p["arquivo"] = _nome_ok(p["arquivo"] if str(p["arquivo"]).lower().endswith(".png") else p["arquivo"] + ".png")
        if p["arquivo"] in vistos:
            raise PersErro(f"Arquivo repetido no JSON: {p['arquivo']}")
        vistos.add(p["arquivo"])
        p["tipo"] = "boca" if p.get("tipo") == "boca" else "pose"
        if p["tipo"] == "boca" and not p.get("base"):
            raise PersErro(f"A pose {p['arquivo']} é \"boca\" mas não diz a \"base\".")
    return d


def criar(nome: str, texto_json: str, refs: List[Tuple[str, bytes]], pod_url: str = "", base: str = _BASE) -> Dict[str, Any]:
    dados = ler_json(texto_json)
    if not refs:
        raise PersErro("Envie pelo menos uma imagem de referência (a ficha da personagem).")
    pid = secrets.token_hex(5)
    d = _pasta(pid, base)
    os.makedirs(os.path.join(d, "refs"), exist_ok=True)
    os.makedirs(os.path.join(d, "imagens"), exist_ok=True)
    nomes = []
    for n, b in refs[:MAX_REFS]:
        n = _nome_ok(n)
        with open(os.path.join(d, "refs", n), "wb") as f:
            f.write(b)
        nomes.append(n)
    p = {"id": pid, "nome": (nome or dados.get("nome") or dados.get("personagem") or "Personagem").strip()[:80],
         "criado": time.time(), "pod_url": (pod_url or "").strip().rstrip("/"), "dados": dados, "refs": nomes,
         "mestre": None, "jobs": [], "log": [],
         "imagens": {x["arquivo"]: {"estado": "nova", "versoes": [], "atual": -1, "erro": None, "job": None}
                     for x in dados["poses"]}}
    salvar(p, base)
    return p


def trocar_json(pid: str, texto_json: str, base: str = _BASE) -> Dict[str, Any]:
    """✏ troca o JSON de um projeto que já existe: as poses que continuam (mesmo "arquivo") mantêm as imagens,
    versões e a aprovação; as novas entram como "falta gerar"; as que saíram do JSON somem da galeria
    (as imagens ficam na pasta). Os prompts novos valem pras próximas gerações."""
    dados = ler_json(texto_json)
    with _TRAVA:
        p = carregar(pid, base)
        novos = {x["arquivo"] for x in dados["poses"]}
        na_fila = [a for a, it in p["imagens"].items() if a not in novos and it.get("estado") in ESTADOS_ESPERA]
        if na_fila:
            raise PersErro("Estas poses ainda estão no pod e sumiriam do JSON: " + ", ".join(na_fila[:5]) + " — espere terminar.")
        antes = p["imagens"]
        p["imagens"] = {a: antes.get(a) or {"estado": "nova", "versoes": [], "atual": -1, "erro": None, "job": None} for a in
                        [x["arquivo"] for x in dados["poses"]]}
        p["dados"] = dados
        if p.get("mestre") and p["mestre"].get("arquivo") not in novos:
            _log(p, f"⚠ a mestre {p['mestre']['arquivo']} não está no JSON novo — ela continua valendo de referência")
        add, saiu = len(novos - set(antes)), len(set(antes) - novos)
        _log(p, f"✏ JSON trocado: {len(novos)} pose(s)" + (f", {add} nova(s)" if add else "") + (f", {saiu} saiu(saíram)" if saiu else ""))
        salvar(p, base)
        return {"ok": True, "poses": len(novos), "novas": add, "sairam": saiu}


def pose(p: Dict[str, Any], arquivo: str) -> Dict[str, Any]:
    x = next((y for y in p["dados"]["poses"] if y["arquivo"] == arquivo), None)
    if not x:
        raise PersErro(f"Pose não existe: {arquivo}")
    return x


def arquivo_atual(p: Dict[str, Any], arquivo: str, base: str = _BASE) -> Optional[str]:
    it = p["imagens"].get(arquivo) or {}
    if it.get("atual", -1) < 0 or not it.get("versoes"):
        return None
    cam = os.path.join(_pasta(p["id"], base), "imagens", it["versoes"][it["atual"]]["local"])
    return cam if os.path.isfile(cam) else None


def _log(p: Dict[str, Any], msg: str) -> None:
    p.setdefault("log", []).append(f"{time.strftime('%d/%m %H:%M:%S')} {msg}")
    p["log"] = p["log"][-60:]


# ------------------------------------------------------------------ pod
def _pod(url: str, metodo: str, caminho: str, timeout: float = 60, **kw):
    import requests
    if not re.fullmatch(r"https?://[^\s\"'<>]+", url or ""):
        raise PersErro("Cole o link do pod (https://<id>-8000.proxy.runpod.net).")
    chave = os.environ.get("PERSONAGENS_POD_CHAVE") or ""
    try:
        r = requests.request(metodo, url.rstrip("/") + caminho, timeout=timeout,
                             headers={"X-API-Key": chave} if chave else None, **kw)
    except requests.RequestException as exc:
        raise PersErro(f"O pod não respondeu ({type(exc).__name__}) — ele está ligado? rodou o start.sh?")
    if r.status_code >= 400:
        try:
            det = r.json().get("detail") or r.text[:200]
        except ValueError:
            det = r.text[:200]
        raise PersErro(f"O pod respondeu {r.status_code}: {det}")
    return r


def status_pod(url: str) -> Dict[str, Any]:
    return _pod(url, "GET", "/status", timeout=10).json()


def enviar(pid: str, arquivos: List[str], extra: str = "", base: str = _BASE, qualidade: str = "", passos: int = 0) -> Dict[str, Any]:
    """Manda as poses pro pod num job só. Poses com a mestre aprovada vão com ela de referência; "_boca" leva a
    imagem base (se ela não está no mesmo lote, sobe a versão atual dela)."""
    with _TRAVA:
        p = carregar(pid, base)
        d = _pasta(pid, base)
        alvo = [a for a in dict.fromkeys(arquivos) if a in p["imagens"] and p["imagens"][a]["estado"] not in ESTADOS_ESPERA]
        if not alvo:
            raise PersErro("Nada pra gerar (as escolhidas já estão na fila).")
        mestre = p.get("mestre") or None
        mestre_arq = os.path.join(d, "imagens", mestre["local"]) if mestre else None
        if mestre_arq and not os.path.isfile(mestre_arq):
            mestre, mestre_arq = None, None
        refs = p["refs"][: (MAX_REFS - 1) if mestre else MAX_REFS]
        arqs: List[Tuple[str, str]] = [(n, os.path.join(d, "refs", n)) for n in refs]
        if mestre:
            arqs.append(("MESTRE_" + mestre["arquivo"], mestre_arq))
        poses_job = []
        for a in alvo:
            x = dict(pose(p, a))
            if x["tipo"] == "boca" and x["base"] not in alvo:
                cam = arquivo_atual(p, x["base"], base)
                if not cam:
                    raise PersErro(f"{a}: gere (ou aprove) primeiro a imagem base {x['base']}.")
                arqs.append((x["base"], os.path.join(d, "imagens", os.path.basename(cam))))
            if extra:
                x["extra"] = extra[:600]
            poses_job.append({k: x[k] for k in ("arquivo", "tipo", "prompt", "base", "extra") if x.get(k)})
        dados = p["dados"]
        geracao = dict(dados.get("geracao") or {})
        if qualidade in ("rapida", "alta"):  # ⚡ rápida (Lightning, 4 passos) ou 🎨 alta (modelo completo, mais passos)
            geracao["qualidade"] = qualidade
        if passos:
            geracao["passos"] = max(1, min(80, int(passos)))
        pedido = {"nome": f"{p['nome']} · {len(poses_job)} pose(s)", "referencias": refs,
                  "descricoes": {n: (dados.get("descricoes_referencias") or {}).get(n) for n in refs
                                 if (dados.get("descricoes_referencias") or {}).get(n)},
                  "mestre": ("MESTRE_" + mestre["arquivo"]) if mestre else None,
                  "texto_fixo": dados.get("texto_fixo") or {}, "geracao": geracao,
                  "canvas": dados.get("canvas") or [1200, 1800], "altura_personagem": dados.get("altura_personagem") or 0.95,
                  "recortar": True, "poses": poses_job,
                  # 🟩 fundo da geração: "verde" (chroma key — o pod tira até o verde preso no cabelo) ou "branco"
                  "fundo": dados.get("fundo") if dados.get("fundo") in ("verde", "branco") else "branco",
                  **({"limpeza": dados["limpeza"]} if isinstance(dados.get("limpeza"), (dict, bool)) else {})}
        abertos = []
        try:
            files = []
            for n, cam in arqs:
                f = open(cam, "rb")
                abertos.append(f)
                files.append(("arquivos", (n, f, "image/png")))
            r = _pod(p["pod_url"], "POST", "/jobs", timeout=180,
                     data={"pedido": json.dumps(pedido, ensure_ascii=False)}, files=files).json()
        finally:
            for f in abertos:
                f.close()
        jid = r["id"]
        p["jobs"].append({"id": jid, "pod_url": p["pod_url"], "arquivos": alvo, "criado": time.time(), "final": False})
        for a in alvo:
            p["imagens"][a].update(estado="fila", job=jid, erro=None, versao_pod=0)
        _log(p, f"▶ {len(alvo)} pose(s) pro pod" + (" com a ⭐ mestre" if mestre else " (sem mestre)")
             + (f" · qualidade {qualidade}" if qualidade else "") + (f" · {geracao['passos']} passos" if passos else "")
             + (f" · correção: {extra[:80]}" if extra else ""))
        salvar(p, base)
        return {"ok": True, "job": jid, "enviadas": len(alvo), "com_mestre": bool(mestre)}


def sincronizar(pid: str, base: str = _BASE) -> Dict[str, Any]:
    """Pergunta ao pod como estão os jobs abertos e baixa as poses que ficaram prontas (cada uma vira uma versão)."""
    with _TRAVA:
        p = carregar(pid, base)
        abertos = [j for j in p["jobs"] if not j.get("final")]
        if not abertos:
            return {"mudou": False, "aviso": None}
        d = _pasta(pid, base)
        mudou, aviso = False, None
        for j in abertos:
            try:
                st = _pod(j["pod_url"], "GET", f"/jobs/{j['id']}", timeout=20).json()
            except PersErro as exc:
                aviso = str(exc)
                if "404" in str(exc):  # pod novo/apagado: esse job não existe mais
                    j["final"] = True
                    for a in j["arquivos"]:
                        it = p["imagens"].get(a) or {}
                        if it.get("job") == j["id"] and it.get("estado") in ESTADOS_ESPERA:
                            it.update(estado="erro", erro="o pod não tem mais esse pedido (pod reiniciado/trocado) — gere de novo")
                    mudou = True
                continue
            for a, ip in (st.get("itens") or {}).items():
                it = p["imagens"].get(a)
                if not it or it.get("job") != j["id"]:
                    continue
                if ip.get("estado") == "gerando" and it["estado"] != "gerando":
                    it["estado"] = "gerando"
                    mudou = True
                elif ip.get("estado") == "pronto" and int(ip.get("versao") or 0) > int(it.get("versao_pod") or 0):
                    r = _pod(j["pod_url"], "GET", f"/jobs/{j['id']}/arquivos/{a}", timeout=120)
                    local = f"{a[:-4]}_v{len(it['versoes']) + 1}_{secrets.token_hex(2)}.png"
                    with open(os.path.join(d, "imagens", local), "wb") as f:
                        f.write(r.content)
                    it["versoes"].append({"local": local, "seed": ip.get("seed"), "job": j["id"], "quando": time.time(),
                                          "aviso": ip.get("aviso"), "segundos": ip.get("segundos")})
                    it.update(atual=len(it["versoes"]) - 1, estado="pronta", erro=None, versao_pod=int(ip.get("versao") or 0))
                    mudou = True
                elif ip.get("estado") == "erro" and it["estado"] != "erro":
                    it.update(estado="erro", erro=ip.get("erro"))
                    mudou = True
            if st.get("status") in ("concluido", "concluido_com_erros", "erro", "cancelado"):
                j["final"] = True
                for a in j["arquivos"]:
                    it = p["imagens"].get(a) or {}
                    if it.get("job") == j["id"] and it.get("estado") in ESTADOS_ESPERA:
                        it.update(estado="erro", erro=st.get("mensagem") or "o pod terminou sem essa pose")
                mudou = True
            elif st.get("posicao"):
                j["posicao"] = st["posicao"]
        if mudou:
            salvar(p, base)
        return {"mudou": mudou, "aviso": aviso}


# ------------------------------------------------------------------ aprovar, mestre, versões
def aprovar(pid: str, arquivo: str, base: str = _BASE) -> Dict[str, Any]:
    with _TRAVA:
        p = carregar(pid, base)
        it = p["imagens"].get(arquivo)
        if not it or not arquivo_atual(p, arquivo, base):
            raise PersErro("Essa pose ainda não tem imagem.")
        it["estado"] = "aprovada"
        salvar(p, base)
        return p


def usar_como_mestre(pid: str, arquivo: str, base: str = _BASE) -> Dict[str, Any]:
    with _TRAVA:
        p = carregar(pid, base)
        cam = arquivo_atual(p, arquivo, base)
        if not cam:
            raise PersErro("Essa pose ainda não tem imagem.")
        if pose(p, arquivo)["tipo"] == "boca":
            raise PersErro("A mestre tem que ser uma pose (não uma _boca).")
        p["mestre"] = {"arquivo": arquivo, "local": os.path.basename(cam), "quando": time.time()}
        p["imagens"][arquivo]["estado"] = "aprovada"
        _log(p, f"⭐ mestre: {arquivo}")
        salvar(p, base)
        return p


def escolher_versao(pid: str, arquivo: str, idx: int, base: str = _BASE) -> Dict[str, Any]:
    with _TRAVA:
        p = carregar(pid, base)
        it = p["imagens"].get(arquivo)
        if not it or not (0 <= idx < len(it["versoes"])):
            raise PersErro("Versão inexistente.")
        it["atual"] = idx
        if it["estado"] in ("aprovada", "descartada", "erro"):
            it["estado"] = "pronta"
        salvar(p, base)
        return p


def descartar(pid: str, arquivo: str, base: str = _BASE) -> Dict[str, Any]:
    with _TRAVA:
        p = carregar(pid, base)
        if arquivo not in p["imagens"]:
            raise PersErro("Pose não existe.")
        p["imagens"][arquivo]["estado"] = "descartada"
        salvar(p, base)
        return p


def trocar_pod(pid: str, url: str, base: str = _BASE) -> Dict[str, Any]:
    with _TRAVA:
        p = carregar(pid, base)
        u = (url or "").strip().rstrip("/")
        if u and not re.fullmatch(r"https?://[^\s\"'<>]+", u):
            raise PersErro("Link do pod inválido.")
        p["pod_url"] = u
        salvar(p, base)
        return p


def zip_aprovadas(pid: str, base: str = _BASE) -> bytes:
    p = carregar(pid, base)
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for a, it in p["imagens"].items():
            cam = arquivo_atual(p, a, base)
            if it["estado"] == "aprovada" and cam:
                z.write(cam, a)
                n += 1
        z.writestr("poses.json", json.dumps({"personagem": p["dados"].get("personagem"), "nome": p["nome"],
                                             "canvas": p["dados"].get("canvas") or [1200, 1800],
                                             "poses": [{k: x.get(k) for k in ("arquivo", "tipo", "grupo", "lado", "descricao_pt", "base")}
                                                       for x in p["dados"]["poses"] if p["imagens"][x["arquivo"]]["estado"] == "aprovada"]},
                                            ensure_ascii=False, indent=1))
    if not n:
        raise PersErro("Nenhuma pose aprovada ainda.")
    return buf.getvalue()


def para_tela(p: Dict[str, Any]) -> Dict[str, Any]:
    """O que a página precisa: cada pose com o estado, as versões e a imagem atual."""
    itens = []
    for x in p["dados"]["poses"]:
        it = p["imagens"][x["arquivo"]]
        itens.append({"arquivo": x["arquivo"], "tipo": x["tipo"], "grupo": x.get("grupo") or "", "prioridade": x.get("prioridade") or 9,
                      "lado": x.get("lado") or "", "descricao": x.get("descricao_pt") or x["prompt"][:120],
                      "mestre_sugerida": bool(x.get("mestre")), "base": x.get("base"), "estado": it["estado"],
                      "erro": it.get("erro"), "versoes": len(it["versoes"]), "atual": it["atual"],
                      "aviso": (it["versoes"][it["atual"]].get("aviso") if it["atual"] >= 0 else None),
                      "img": (it["versoes"][it["atual"]]["local"] if it["atual"] >= 0 else None)})
    return {"id": p["id"], "nome": p["nome"], "pod_url": p.get("pod_url") or "", "mestre": p.get("mestre"),
            "refs": p["refs"], "itens": itens, "resumo": resumo(p), "log": (p.get("log") or [])[-12:],
            "esperando": any(i["estado"] in ESTADOS_ESPERA for i in itens),
            "fila": [{"id": j["id"], "posicao": j.get("posicao")} for j in p["jobs"] if not j.get("final")]}
