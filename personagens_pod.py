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

🚀 v84_184 — motor "flow" (padrão nos projetos novos): em vez do pod, cada pose vai pra fila do 🚀 Flow em massa
(as contas Google do editor) como FOTO com UMA imagem de referência — a ficha + a ⭐ mestre lado a lado numa
colagem (flow_refs/). A imagem volta com fundo verde e o PNG transparente sai aqui mesmo, no PC
(personagens_limpeza.py: chave de verde, limpeza, canvas 1200×1800). A original fica em brutos/.
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
    p = carregar(pid, base)
    if p.get("canal"):
        try:
            desligar_canal(pid, base)
        except Exception:  # noqa: BLE001
            pass
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


MOTORES = ("flow", "pod")
FLOW_PROPORCOES = ("3:4", "9:16", "1:1", "4:3", "16:9")


def criar(nome: str, texto_json: str, refs: List[Tuple[str, bytes]], pod_url: str = "", base: str = _BASE,
          motor: str = "flow") -> Dict[str, Any]:
    dados = ler_json(texto_json)
    motor = motor if motor in MOTORES else "flow"
    if not refs and motor == "pod":
        raise PersErro("No pod, envie pelo menos uma imagem de referência (a ficha da personagem).")
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
         "motor": motor, "canal": None,
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


def enviar(pid: str, arquivos: List[str], extra: str = "", base: str = _BASE, qualidade: str = "", passos: int = 0,
           quantidade: str = "x1") -> Dict[str, Any]:
    """▶ Gera as poses no motor do projeto: 🚀 Flow (padrão) ou o pod."""
    if motor_de(carregar(pid, base)) == "flow":
        return _enviar_flow(pid, arquivos, extra, base, quantidade)
    return _enviar_pod(pid, arquivos, extra, base, qualidade, passos)


def motor_de(p: Dict[str, Any]) -> str:
    return p.get("motor") if p.get("motor") in MOTORES else "pod"  # projetos antigos (v84_183) eram do pod


def _enviar_pod(pid: str, arquivos: List[str], extra: str = "", base: str = _BASE, qualidade: str = "", passos: int = 0) -> Dict[str, Any]:
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
        abertos = [j for j in p["jobs"] if not j.get("final") and j.get("motor") != "flow"]
        mudou_flow, aviso_flow = _sincronizar_flow(p, base)
        if mudou_flow:
            salvar(p, base)
        if not abertos:
            return {"mudou": mudou_flow, "aviso": aviso_flow}
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
        return {"mudou": mudou or mudou_flow, "aviso": aviso or aviso_flow}


# ------------------------------------------------------------------ 🚀 motor Flow
def _flow_cfg(p: Dict[str, Any]) -> Dict[str, Any]:
    f = p["dados"].get("flow") if isinstance(p["dados"].get("flow"), dict) else {}
    return {"proporcao": f.get("proporcao") if f.get("proporcao") in FLOW_PROPORCOES else "3:4",
            "modelo": str(f.get("modelo") or "")[:60],
            "referencia": "colagem" if f.get("referencia") == "colagem" else "mestre"}


def _sobre_verde(cam: str):
    """PNG transparente (versão/mestre) → RGB sobre o verde do chroma key (o Flow continua no mesmo fundo)."""
    from PIL import Image
    im = Image.open(cam).convert("RGBA")
    fundo = Image.new("RGBA", im.size, (0, 255, 0, 255))
    fundo.alpha_composite(im)
    return fundo.convert("RGB")


def _bruto_ou_png(p: Dict[str, Any], arquivo: str, base: str):
    """A imagem atual de uma pose como o Flow deve ver: a original (fundo verde) se tiver, senão o PNG sobre verde."""
    from PIL import Image
    it = p["imagens"].get(arquivo) or {}
    if it.get("atual", -1) >= 0 and it.get("versoes"):
        v = it["versoes"][it["atual"]]
        bruto = os.path.join(_pasta(p["id"], base), "brutos", v.get("bruto") or "")
        if v.get("bruto") and os.path.isfile(bruto):
            return Image.open(bruto).convert("RGB")
    cam = arquivo_atual(p, arquivo, base)
    return _sobre_verde(cam) if cam else None


def _mestre_img(p: Dict[str, Any], base: str):
    from PIL import Image
    m = p.get("mestre") or None
    if not m:
        return None
    d = _pasta(p["id"], base)
    if m.get("bruto") and os.path.isfile(os.path.join(d, "brutos", m["bruto"])):
        return Image.open(os.path.join(d, "brutos", m["bruto"])).convert("RGB")
    cam = os.path.join(d, "imagens", m.get("local") or "")
    return _sobre_verde(cam) if m.get("local") and os.path.isfile(cam) else None


def prompt_flow(p: Dict[str, Any], x: Dict[str, Any], paineis: List[str], extra: str = "") -> str:
    """O texto de uma pose pro Flow (uma imagem de referência = a colagem dos `paineis`)."""
    dados = p["dados"]
    fixo = dados.get("texto_fixo") or {}
    if x["tipo"] == "boca":
        partes = ["The reference image is the finished character image to edit.", x["prompt"]]
    else:
        if not paineis:
            partes = []
        elif len(paineis) == 1:
            partes = [f"The reference image is {paineis[0]}."]
        else:
            nomes = ["left", "middle", "right"] if len(paineis) == 3 else ["left", "right"]
            partes = ["The reference image is a collage of " + str(len(paineis)) + " panels side by side: "
                      + "; ".join(f"{nomes[k] if k < len(nomes) else f'panel {k + 1}'} = {t}" for k, t in enumerate(paineis)) + "."]
        if paineis:
            partes.append("Draw ONE new single image of this same character, alone, in a NEW POSE that is clearly different "
                          "from the pose in the reference image(s) — change the body, arms, hands, head angle and facial "
                          f"expression exactly as described here: {x['prompt']}")
            partes.append("Do NOT reproduce the layout of the reference: no character sheet, no turnaround, no several views or "
                          "poses side by side, no panels, no white background — ONE figure only, one single full-frame picture.")
        else:
            partes.append(f"Draw ONE single image of this character, alone: {x['prompt']}")
        for chave in ("trava", "estilo", "regras"):
            if fixo.get(chave):
                partes.append(str(fixo[chave]))
    if extra:
        partes.append(f"CORRECTION FOR THIS ATTEMPT: {extra}")
    return " ".join(" ".join(partes).split())[:3900]


def _enviar_flow(pid: str, arquivos: List[str], extra: str, base: str, quantidade: str) -> Dict[str, Any]:
    from PIL import Image
    import personagens_limpeza as L
    with _TRAVA:
        p = carregar(pid, base)
        d = _pasta(pid, base)
        alvo = [a for a in dict.fromkeys(arquivos) if a in p["imagens"] and p["imagens"][a]["estado"] not in ESTADOS_ESPERA]
        if not alvo:
            raise PersErro("Nada pra gerar (as escolhidas já estão na fila).")
        os.makedirs(os.path.join(d, "flow_refs"), exist_ok=True)
        desc = p["dados"].get("descricoes_referencias") or {}
        mestre = _mestre_img(p, base)
        # com a ⭐ mestre aprovada, por padrão ela vai SOZINHA (a ficha/colagem às vezes faz o Flow devolver uma folha
        # com várias poses); "flow": {"referencia": "colagem"} no JSON manda a ficha + a mestre lado a lado
        so_mestre = mestre is not None and _flow_cfg(p)["referencia"] != "colagem"
        refs = [] if so_mestre else (p["refs"][:2] if mestre is not None else p["refs"][:3])
        ims, paineis = [], []
        for n in refs:
            try:
                ims.append(Image.open(os.path.join(d, "refs", n)))
                paineis.append(desc.get(n) or "the official character reference sheet")
            except Exception:  # noqa: BLE001
                continue
        if mestre is not None:
            ims.append(mestre)
            paineis.append("the APPROVED MASTER image of this character — copy its identity exactly (face, hair, eyes, "
                           "outfit, colors, line art, art style) and its scale, but NOT its pose")
        col_pose = None  # sem ficha e sem mestre: a 1ª geração sai só do texto (a trava do JSON)
        if ims:
            # 🧍 v84_189: o nome vem do CONTEÚDO — a mesma referência é o mesmo arquivo, e o Flow reusa a mídia que já
            # subiu no projeto (não sobe a mesma imagem a cada pose)
            col_pose = _salvar_ref(L.colagem(ims), os.path.join(d, "flow_refs"), "ref")
        itens, por_item, depois = [], [], []
        for a in alvo:
            x = dict(pose(p, a))
            ref = col_pose
            if x["tipo"] == "boca":
                # a _boca é edição da base PRONTA: base no mesmo envio (ainda vai mudar) ou sem imagem → fica pra depois
                bimg = None if x["base"] in alvo else _bruto_ou_png(p, x["base"], base)
                if bimg is None:
                    depois.append(a)
                    continue
                ref = _salvar_ref(bimg, os.path.join(d, "flow_refs"), f"base_{a[:-4]}")
            item = {"prompt": prompt_flow(p, x, paineis, extra), "tipo": "imagem", "origem": "personagens"}
            if ref:
                item["referencia_arquivo"] = ref
            itens.append(item)
            por_item.append(a)
        if not itens:
            raise PersErro("; ".join(f"{a}: gere (ou aprove) primeiro a imagem base {pose(p, a)['base']}." for a in depois[:3]))
        alvo = por_item
        fc = _flow_cfg(p)
        import flow_lote
        lote = flow_lote.lote()
        try:
            novos = lote.adicionar(itens, modelo=fc["modelo"], proporcao=fc["proporcao"],
                                   quantidade=quantidade if quantidade in ("x1", "x2", "x3", "x4") else "x1")
        except ValueError as exc:
            raise PersErro(str(exc))
        for a, j in zip(por_item, novos):
            p["jobs"].append({"id": j["id"], "motor": "flow", "arquivos": [a], "criado": time.time(), "final": False,
                              "extra": extra[:300] or None})
            p["imagens"][a].update(estado="fila", job=j["id"], erro=None)
        _log(p, f"🚀 {len(alvo)} pose(s) pro Flow" + (" com a ⭐ mestre" if mestre is not None else " (sem mestre)")
             + (f" · {quantidade}" if quantidade and quantidade != "x1" else "") + (f" · correção: {extra[:80]}" if extra else ""))
        salvar(p, base)
    aviso = (f"{len(depois)} “_boca” ficaram pra depois: a base delas ainda não tem imagem (ou está neste envio) — "
             "gere as _boca quando as bases estiverem prontas. ") if depois else ""
    try:
        lote.iniciar()
    except Exception as exc:  # noqa: BLE001
        aviso += f"o Flow em massa não ligou agora ({str(exc)[:200]}) — os pedidos ficam na fila; ▶ Continuar na aba Flow"
    return {"ok": True, "enviadas": len(alvo), "com_mestre": mestre is not None, "aviso": aviso.strip(), "depois": depois}


def _salvar_ref(img, pasta: str, prefixo: str) -> str:
    """Salva a referência com o nome pelo conteúdo (a mesma imagem → o mesmo arquivo, sem duplicar)."""
    import hashlib
    buf = io.BytesIO()
    img.save(buf, "PNG")
    dados = buf.getvalue()
    cam = os.path.join(pasta, f"{prefixo}_{hashlib.sha1(dados).hexdigest()[:12]}.png")
    if not os.path.isfile(cam):
        with open(cam, "wb") as f:
            f.write(dados)
    return cam


def _galeria_flow(arquivo: str) -> str:
    import flow_estudio as FE
    return os.path.join(FE.pasta_galeria(), arquivo)


def _sincronizar_flow(p: Dict[str, Any], base: str) -> Tuple[bool, Optional[str]]:
    """Olha a fila do 🚀 Flow em massa: imagem pronta → recorta o fundo verde aqui e vira uma versão."""
    abertos = [j for j in p["jobs"] if not j.get("final") and j.get("motor") == "flow"]
    if not abertos:
        return False, None
    from PIL import Image
    import flow_lote
    import personagens_limpeza as L
    lote = flow_lote.lote()
    with lote.trava:
        fila = {j["id"]: dict(j) for j in lote.fila}
        rodando, fim_msg = lote.rodando, lote.fim_msg
    d = _pasta(p["id"], base)
    canvas = tuple(p["dados"].get("canvas") or (1200, 1800))
    alt = float(p["dados"].get("altura_personagem") or 0.95)
    opl = p["dados"]["limpeza"] if isinstance(p["dados"].get("limpeza"), dict) else {}
    mudou, aviso = False, None
    for jb in abertos:
        a = jb["arquivos"][0]
        it = p["imagens"].get(a)
        fj = fila.get(jb["id"])
        if it is None or it.get("job") != jb["id"]:
            jb["final"] = True
            mudou = True
            continue
        antes = (it.get("estado"), it.get("erro"), it.get("msg"))
        if fj is None:
            jb["final"] = True
            it.update(estado="erro", erro="o pedido sumiu da fila do 🚀 Flow em massa (limparam a fila?) — gere de novo")
        elif fj["estado"] == "ok":
            jb["final"] = True
            novas = 0
            for r in fj.get("resultados") or []:
                orig = _galeria_flow(r.get("arquivo") or "")
                if r.get("tipo") != "imagem" or not os.path.isfile(orig):
                    continue
                try:
                    n = len(it["versoes"]) + 1
                    os.makedirs(os.path.join(d, "brutos"), exist_ok=True)
                    img = Image.open(orig).convert("RGB")
                    bruto = f"{a[:-4]}_v{n}_{secrets.token_hex(2)}_flow.png"
                    img.save(os.path.join(d, "brutos", bruto))
                    final, info = L.recortar(img, canvas, alt, opl, corpo_inteiro=bool(p["dados"].get("corpo_inteiro")))
                    local = f"{a[:-4]}_v{n}_{secrets.token_hex(2)}.png"
                    final.save(os.path.join(d, "imagens", local), optimize=True)
                    it["versoes"].append({"local": local, "bruto": bruto, "job": jb["id"], "motor": "flow", "quando": time.time(),
                                          "aviso": info.get("aviso"), "conta": fj.get("conta"), "limpeza": info.get("limpeza"),
                                          "cortada": bool(info.get("cortada_lados")), "defeito": bool(info.get("defeito"))})
                    novas += 1
                except Exception as exc:  # noqa: BLE001
                    aviso = f"{a}: a imagem chegou mas o recorte falhou ({type(exc).__name__}: {str(exc)[:160]})"
            ruins = it["versoes"][-novas:] if novas else []
            cortadas = bool(ruins) and all(v.get("cortada") or v.get("defeito") for v in ruins)
            if cortadas and not jb.get("auto_refeito"):
                # ✂ veio cortada na borda / folha com várias poses / fundo branco: refaz UMA vez sozinho, com a correção
                if any(v.get("defeito") for v in ruins):
                    corr = ("CORRECTION FOR THIS ATTEMPT: the previous result copied the reference sheet — draw ONE single figure "
                            "only, no panels, no several poses, no white background: plain flat chroma-key green background.")
                else:
                    corr = ("CORRECTION FOR THIS ATTEMPT: the previous image cut the character at the edge — zoom out: the whole "
                            "head, all the hair and both sides must be inside the image with clear green margin.")
                try:
                    item = {"prompt": (fj["prompt"] + " " + corr)[:3990], "tipo": "imagem", "origem": "personagens"}
                    if fj.get("referencia_arquivo") and os.path.isfile(fj["referencia_arquivo"]):
                        item["referencia_arquivo"] = fj["referencia_arquivo"]
                    nj = lote.adicionar([item],
                                        modelo=fj.get("modelo") or "", proporcao=fj.get("proporcao") or "3:4",
                                        quantidade=fj.get("quantidade") or "x1")[0]
                    p["jobs"].append({"id": nj["id"], "motor": "flow", "arquivos": [a], "criado": time.time(), "final": False,
                                      "auto_refeito": True})
                    it.update(atual=len(it["versoes"]) - 1, estado="fila", job=nj["id"], erro=None,
                              msg="✂ veio com defeito (cortada / folha / fundo errado) — refazendo sozinho (1x)")
                    _log(p, f"✂ {a}: veio com defeito ({(ruins[-1].get('aviso') or '')[:80]}) — refazendo 1x")
                    try:
                        lote.iniciar()
                    except Exception:  # noqa: BLE001
                        pass
                    mudou = True
                    continue
                except Exception:  # noqa: BLE001
                    pass
            if novas:
                it.update(atual=len(it["versoes"]) - 1, estado="pronta", erro=None, msg=None)
            else:
                it.update(estado="erro", erro=aviso or "o Flow terminou mas não veio imagem")
        elif fj["estado"] == "erro":
            jb["final"] = True
            it.update(estado="erro", erro=str(fj.get("erro") or "o Flow falhou")[:300])
        elif fj["estado"] in ("rodando", "convertendo"):
            it.update(estado="gerando", msg=f"🎨 gerando no Flow (conta “{fj.get('conta')}”)")
        elif not rodando:
            it.update(estado="fila", msg="⏸ o Flow em massa está parado" + (f": {fim_msg}" if fim_msg else "") + " — ▶ Continuar na aba Flow")
            aviso = aviso or it["msg"]
        else:
            pos = 1 + sum(1 for x in fila.values() if x["estado"] == "pendente" and x.get("criado", 0) < fj.get("criado", 0))
            it.update(estado="fila", msg=f"⏳ na fila do Flow ({pos}º)")
        if (it.get("estado"), it.get("erro"), it.get("msg")) != antes:
            mudou = True
    return mudou, aviso


# ------------------------------------------------------------------ 🔗 v84_185: personagens do canal (zip do canal)
def personagens_dos_canais(base: str = _BASE) -> List[Dict[str, Any]]:
    """Todas as personagens com JSON de poses nos canais importados (🎨 Identidade visual) → pra escolher/conectar."""
    import marca_visual as mv
    out = []
    for x in mv.listar(base):
        try:
            m = mv.carregar(base, x["slug"])
        except mv.MarcaErro:
            continue
        for c in mv.personagens_png(m):
            proj = None
            if c.get("projeto"):
                try:
                    proj = {"id": c["projeto"], "nome": carregar(c["projeto"], base)["nome"]}
                except PersErro:
                    proj = None
            out.append(dict(c, canal=x["slug"], canal_nome=x.get("nome") or x["slug"], projeto=proj))
    return out


def _json_do_canal(canal: str, personagem: str, base: str) -> Tuple[Any, Dict[str, Any], str]:
    import marca_visual as mv
    try:
        m = mv.carregar(base, canal)
    except mv.MarcaErro as exc:
        raise PersErro(f"Canal não encontrado: {exc}")
    c = next((x for x in mv.personagens_png(m) if x["slug"] == personagem), None)
    if not c:
        raise PersErro(f"O canal {canal} não tem o JSON de poses da personagem {personagem} (personagens/<slug>.json).")
    with open(mv.arquivo(m, c["arquivo"]), encoding="utf-8-sig") as f:
        texto = f.read()
    return m, c, texto


def criar_do_canal(canal: str, personagem: str, refs: List[Tuple[str, bytes]], motor: str = "flow", pod_url: str = "",
                   nome: str = "", base: str = _BASE) -> Dict[str, Any]:
    """➕ Personagem nova a partir do zip do canal: o JSON de poses vem do canal; a ficha é opcional no Flow (sem ela a
    ⭐ mestre sai só do texto da trava)."""
    import marca_visual as mv
    m, c, texto = _json_do_canal(canal, personagem, base)
    if not refs:  # a ficha que veio no zip do canal (personagens/<slug>_ficha.png)
        for cam in c.get("fichas") or []:
            with open(cam, "rb") as f:
                refs.append((os.path.basename(cam), f.read()))
    p = criar(nome or f"{c['nome']} ({m['guia'].get('project', {}).get('name') or canal})", texto, refs, pod_url, base, motor=motor)
    return ligar_canal(p["id"], canal, personagem, base=base)


def ligar_canal(pid: str, canal: str, personagem: str, usar_json: bool = False, base: str = _BASE) -> Dict[str, Any]:
    """🔗 Este projeto É a personagem `personagem` do canal `canal` (o editor vai usar as aprovadas dele nos vídeos do
    canal). `usar_json`: troca as poses pelo JSON do canal (as imagens das poses que continuam ficam)."""
    import marca_visual as mv
    m, c, texto = _json_do_canal(canal, personagem, base)
    if usar_json:
        trocar_json(pid, texto, base)
    with _TRAVA:
        p = carregar(pid, base)
        velho = p.get("canal") or {}
        if velho.get("slug") and (velho.get("slug"), velho.get("personagem")) != (canal, personagem):
            try:
                mv.ligar_personagem(mv.carregar(base, velho["slug"]), velho["personagem"], None)
            except Exception:  # noqa: BLE001
                pass
        anterior = mv.ligacoes_personagens(m).get(personagem)
        if anterior and anterior != pid:  # a personagem estava em outro projeto: aquele fica solto
            try:
                q = carregar(anterior, base)
                q["canal"] = None
                _log(q, f"🔗 desconectado de {canal}/{personagem} (outro projeto foi conectado)")
                salvar(q, base)
            except PersErro:
                pass
        mv.ligar_personagem(m, personagem, pid)
        p["canal"] = {"slug": canal, "personagem": personagem, "nome": c["nome"], "arquivo": c["arquivo"],
                      "canal_nome": (m["guia"].get("project") or {}).get("name") or canal}
        _log(p, f"🔗 conectado ao canal {p['canal']['canal_nome']} → {c['nome']}" + (" (poses do JSON do canal)" if usar_json else ""))
        salvar(p, base)
        return p


def desligar_canal(pid: str, base: str = _BASE) -> Dict[str, Any]:
    import marca_visual as mv
    with _TRAVA:
        p = carregar(pid, base)
        c = p.get("canal") or {}
        if c.get("slug"):
            try:
                m = mv.carregar(base, c["slug"])
                if mv.ligacoes_personagens(m).get(c["personagem"]) == pid:
                    mv.ligar_personagem(m, c["personagem"], None)
            except Exception:  # noqa: BLE001
                pass
            _log(p, f"🔗 desconectado do canal {c.get('canal_nome') or c['slug']}")
        p["canal"] = None
        salvar(p, base)
        return p


# ------------------------------------------------------------------ 📦 v84_188: levar as personagens no zip do canal
PASTA_NO_PACOTE = "personagens_projetos"


def exportar_para_pacote(z: "zipfile.ZipFile", m: Dict[str, Any], base: str, so_aprovadas: bool = True) -> int:
    """Põe no zip do canal (<slug>/personagens_projetos/<personagem>/) o projeto conectado de cada personagem: o JSON
    das poses, as referências, a ⭐ mestre e a imagem atual das poses aprovadas (ou também das pra revisar)."""
    import marca_visual as mv
    n = 0
    for pslug, pid in mv.ligacoes_personagens(m).items():
        try:
            p = carregar(pid, base)
        except PersErro:
            continue
        d = _pasta(pid, base)
        raiz = f"{m['slug']}/{PASTA_NO_PACOTE}/{pslug}/"
        imagens: Dict[str, Any] = {}
        for a, it in p["imagens"].items():
            mestre = (p.get("mestre") or {}).get("arquivo") == a
            if not (it.get("estado") == "aprovada" or mestre or (not so_aprovadas and it.get("estado") == "pronta")):
                continue
            cam = arquivo_atual(p, a, base)
            if not cam:
                continue
            v = it["versoes"][it["atual"]]
            z.write(cam, raiz + "imagens/" + os.path.basename(cam))
            ent = {"estado": it["estado"], "local": os.path.basename(cam)}
            bruto = os.path.join(d, "brutos", v.get("bruto") or "")
            if v.get("bruto") and os.path.isfile(bruto):  # a original (fundo verde): o Flow continua as poses a partir dela
                z.write(bruto, raiz + "brutos/" + os.path.basename(bruto))
                ent["bruto"] = os.path.basename(bruto)
            imagens[a] = ent
        for r in p.get("refs") or []:
            cam = os.path.join(d, "refs", r)
            if os.path.isfile(cam):
                z.write(cam, raiz + "refs/" + r)
        try:  # 🎞 v84_193: os clipes animados prontos (WebM transparente) vão junto pra reusar no outro PC
            import personagens_animar as PA
            anims = {}
            for k, a in PA.carregar(pid, base).items():
                if a.get("estado") == "pronto" and os.path.isfile(str(a.get("webm"))):
                    z.write(a["webm"], raiz + "animacoes/" + os.path.basename(a["webm"]))
                    anims[k] = {x: a.get(x) for x in ("pose", "tipo", "prompt", "duracao")} | {"webm": os.path.basename(a["webm"])}
            if anims:
                z.writestr(raiz + "animacoes/animacoes.json", json.dumps(anims, ensure_ascii=False, indent=1))
        except Exception:  # noqa: BLE001
            pass
        z.writestr(raiz + "projeto.json", json.dumps({
            "formato": "personagens_projeto_v1", "nome": p["nome"], "motor": motor_de(p), "dados": p["dados"],
            "refs": p.get("refs") or [], "mestre": (p.get("mestre") or {}).get("arquivo"), "imagens": imagens},
            ensure_ascii=False, indent=1))
        n += 1
    return n


def importar_do_pacote(z: "zipfile.ZipFile", raiz: str, canal: str, base: str = _BASE) -> List[str]:
    """O contrário: cada <raiz>/personagens_projetos/<personagem>/projeto.json do zip vira um projeto da aba 🧍
    Personagens já conectado ao canal. Se a personagem já tem projeto conectado neste PC, junta: as poses que aqui
    ainda não estão aprovadas recebem a imagem do zip (como uma versão nova) e a mestre entra se faltar."""
    import marca_visual as mv
    pre = (raiz + "/" if raiz else "") + PASTA_NO_PACOTE + "/"
    nomes = z.namelist()
    feitos = []
    for pj in sorted(n for n in nomes if n.startswith(pre) and n.endswith("/projeto.json") and n.count("/") == pre.count("/") + 1):
        pslug = pj[len(pre):].split("/")[0]
        try:
            info = json.loads(z.read(pj).decode("utf-8-sig"))
        except (ValueError, KeyError):
            continue
        if not isinstance(info, dict) or not isinstance(info.get("dados"), dict):
            continue
        dirz = pj[: -len("projeto.json")]

        def ler(rel: str) -> Optional[bytes]:
            try:
                return z.read(dirz + rel)
            except KeyError:
                return None
        m = mv.carregar(base, canal)
        pid = mv.ligacoes_personagens(m).get(pslug)
        p = None
        if pid:
            try:
                p = carregar(pid, base)
            except PersErro:
                p = None
        if p is None:
            refs = [(r, ler("refs/" + r)) for r in info.get("refs") or []]
            p = criar(str(info.get("nome") or pslug), json.dumps(info["dados"], ensure_ascii=False),
                      [(r, b) for r, b in refs if b], "", base, motor=info.get("motor") or "flow")
        with _TRAVA:
            p = carregar(p["id"], base)
            d = _pasta(p["id"], base)
            for a, ent in (info.get("imagens") or {}).items():
                if a not in p["imagens"] or p["imagens"][a].get("estado") == "aprovada":
                    continue
                dados = ler("imagens/" + str(ent.get("local") or ""))
                if not dados:
                    continue
                n = len(p["imagens"][a]["versoes"]) + 1
                local = f"{a[:-4]}_v{n}_{secrets.token_hex(2)}.png"
                with open(os.path.join(d, "imagens", local), "wb") as f:
                    f.write(dados)
                v: Dict[str, Any] = {"local": local, "quando": time.time(), "veio_do_pacote": True}
                b = ler("brutos/" + str(ent.get("bruto") or "")) if ent.get("bruto") else None
                if b:
                    os.makedirs(os.path.join(d, "brutos"), exist_ok=True)
                    v["bruto"] = f"{a[:-4]}_v{n}_{secrets.token_hex(2)}_flow.png"
                    with open(os.path.join(d, "brutos", v["bruto"]), "wb") as f:
                        f.write(b)
                it = p["imagens"][a]
                it["versoes"].append(v)
                it.update(atual=len(it["versoes"]) - 1, estado="aprovada" if ent.get("estado") == "aprovada" else "pronta",
                          erro=None, job=None)
            ma = info.get("mestre")
            if ma and not p.get("mestre") and ma in p["imagens"] and arquivo_atual(p, ma, base):
                it = p["imagens"][ma]
                v = it["versoes"][it["atual"]]
                p["mestre"] = {"arquivo": ma, "local": v["local"], "quando": time.time(), "bruto": v.get("bruto")}
                it["estado"] = "aprovada"
            _log(p, f"📦 poses que vieram no zip do canal {canal}")
            salvar(p, base)
        try:  # 🎞 os clipes animados que vieram no zip (os que este PC ainda não tem)
            import personagens_animar as PA
            anims = json.loads((ler("animacoes/animacoes.json") or b"{}").decode("utf-8"))
            if isinstance(anims, dict) and anims:
                with PA._TRAVA:
                    idx = PA.carregar(p["id"], base)
                    for k, a in anims.items():
                        if (idx.get(k) or {}).get("estado") == "pronto" or not re.fullmatch(r"[\w\-]{1,140}", k):
                            continue
                        dados = ler("animacoes/" + str(a.get("webm") or ""))
                        if not dados:
                            continue
                        os.makedirs(PA.pasta(p["id"], base), exist_ok=True)
                        destino = os.path.join(PA.pasta(p["id"], base), f"{k}.webm")
                        with open(destino, "wb") as f:
                            f.write(dados)
                        idx[k] = {"estado": "pronto", "webm": destino, "pose": a.get("pose"), "tipo": a.get("tipo"),
                                  "prompt": a.get("prompt"), "duracao": a.get("duracao"), "veio_do_pacote": True}
                    PA._salvar(p["id"], base, idx)
        except Exception:  # noqa: BLE001
            pass
        ligar_canal(p["id"], canal, pslug, base=base)
        feitos.append(p["id"])
    return feitos


def projeto_da_personagem(canal: str, personagem: str, base: str = _BASE) -> Optional[Dict[str, Any]]:
    """O projeto conectado à personagem do canal (pro editor pôr os PNG aprovados por cima do vídeo) ou None."""
    import marca_visual as mv
    try:
        pid = mv.ligacoes_personagens(mv.carregar(base, canal)).get(personagem)
        return carregar(pid, base) if pid else None
    except Exception:  # noqa: BLE001
        return None


def trocar_motor(pid: str, motor: str, base: str = _BASE) -> Dict[str, Any]:
    if motor not in MOTORES:
        raise PersErro("Motor inválido (flow ou pod).")
    with _TRAVA:
        p = carregar(pid, base)
        if any(it.get("estado") in ESTADOS_ESPERA for it in p["imagens"].values()):
            raise PersErro("Espere as poses que estão na fila terminarem antes de trocar o motor.")
        p["motor"] = motor
        _log(p, "🚀 motor: Flow" if motor == "flow" else "🖥 motor: pod")
        salvar(p, base)
        return p


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
        it = p["imagens"][arquivo]
        v = it["versoes"][it["atual"]] if it.get("versoes") and it.get("atual", -1) >= 0 else {}
        p["mestre"] = {"arquivo": arquivo, "local": os.path.basename(cam), "quando": time.time(), "bruto": v.get("bruto")}
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
                      "erro": it.get("erro"), "msg": it.get("msg") if it["estado"] in ESTADOS_ESPERA else None,
                      "versoes": len(it["versoes"]), "atual": it["atual"],
                      "aviso": (it["versoes"][it["atual"]].get("aviso") if it["atual"] >= 0 else None),
                      "img": (it["versoes"][it["atual"]]["local"] if it["atual"] >= 0 else None)})
    return {"id": p["id"], "nome": p["nome"], "pod_url": p.get("pod_url") or "", "mestre": p.get("mestre"),
            "motor": motor_de(p), "flow": _flow_cfg(p), "canal": p.get("canal"),
            "refs": p["refs"], "itens": itens, "resumo": resumo(p), "log": (p.get("log") or [])[-12:],
            "esperando": any(i["estado"] in ESTADOS_ESPERA for i in itens),
            "fila": [{"id": j["id"], "posicao": j.get("posicao")} for j in p["jobs"] if not j.get("final")]}
