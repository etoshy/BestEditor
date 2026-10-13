"""
Direções (predefinições) do DarkPlanner — darkplanner.json -> presets.system:

  * Padrão do sistema  (catálogo inteiro, 25% de templates)
  * Documentário clássico
  * Cinema premium
  * Cortes dinâmicos

Aplicar uma Direção monta um plano DETERMINÍSTICO (mesma semente = mesma
edição): cada categoria tem uma porcentagem (de trechos, de emendas ou de
regiões) e itens com peso; o ritmo multiplica as porcentagens. Regras físicas
do JSON respeitadas: movimento de câmera só em foto, filtro é UM por vídeo,
emenda dentro de template não ganha transição, template precisa de N trechos
livres seguidos e respeita o intervalo mínimo entre templates (gapTplS).
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from typing import Any, Dict, List, Optional

import dp_visual

_AQUI = os.path.dirname(os.path.abspath(__file__))
# Predefinições e paletas criadas pela pessoa (valem pra todos os projetos)
ARQUIVO_USUARIO = os.path.join(_AQUI, "predefinicoes_usuario.json")
_TRAVA = threading.Lock()
EIXOS = ("filtros", "efeitos", "overlays", "transicoes", "entradas", "saidas", "templates")
RITMOS = ("calmo", "equilibrado", "dinamico", "muito_dinamico")
DENSIDADES = ("minimal", "equilibrado", "dinamico", "maximo")
MODOS_COR = ("auto", "predef", "projeto")

# 🗞 quadros editoriais em cada direção: liga/desliga, densidade (1 quadro a cada N s) e os tipos (vazio = todos)
EDITORIAL_SEGUNDOS = {"minimal": 60, "equilibrado": 40, "dinamico": 25, "maximo": 15}
_EDITORIAIS_SISTEMA = {
    "sys_tudo": {"ativo": True, "densidade": "equilibrado", "tipos": []},
    "sys_doc_classico": {"ativo": True, "densidade": "equilibrado", "tipos": []},
    "sys_cinema": {"ativo": True, "densidade": "minimal",
                   "tipos": ["nome", "titulo_video", "numero", "explosao", "pagina", "mural", "linha_tempo", "reescrita"]},
    "sys_dinamico": {"ativo": True, "densidade": "dinamico",
                     "tipos": ["post", "pagina", "numero", "terminal", "recortes", "grade_pontos", "ficha", "nome", "titulo_video"]},
}
# extras com "direcoes": [...] entram nas direções do sistema. O que já existia fica com
# pelo menos metade do peso (os extras não engolem a cara da direção).
_EIXO_DA_SECAO = {"transicoes": "transicoes", "filtros": "filtros", "efeitos": "efeitos", "entradas": "entradas", "cenas": "templates"}
PCT_MINIMO_EXTRAS = {"entradas": 15}


def editoriais_da(p: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """{"ativo", "densidade", "tipos", "segundos"} de uma direção (as antigas, sem o campo, usam todos)."""
    import dp_editorial
    e = (p or {}).get("editoriais")
    if not isinstance(e, dict):
        e = _EDITORIAIS_SISTEMA.get((p or {}).get("id") or "", {"ativo": True, "densidade": "equilibrado", "tipos": []})
    dens = e.get("densidade") if e.get("densidade") in DENSIDADES else "equilibrado"
    return {"ativo": e.get("ativo", True) is not False, "densidade": dens,
            "tipos": [t for t in dict.fromkeys(e.get("tipos") or []) if t in dp_editorial.TIPOS], "segundos": EDITORIAL_SEGUNDOS[dens]}


def _com_extras(p: Dict[str, Any]) -> Dict[str, Any]:
    """Cópia de uma direção do sistema com os extras que pedem ela ("direcoes": ["sys_cinema"…])."""
    out = json.loads(json.dumps(p))
    out["editoriais"] = editoriais_da(p)
    try:
        import dp_extras
        ex = dp_extras.carregar()
    except Exception:  # noqa: BLE001
        return out
    novos: Dict[str, List[str]] = {}
    for sec, eixo in _EIXO_DA_SECAO.items():
        itens = ex.get(sec) or []
        pares = itens.items() if isinstance(itens, dict) else [(i.get("id"), i) for i in itens]
        for iid, it in pares:
            if p["id"] in (it.get("direcoes") or []) and iid:
                novos.setdefault(eixo, []).append(iid)
    for eixo, ids in novos.items():
        cat = out.get(eixo) if isinstance(out.get(eixo), dict) else {"pct": 0, "itens": []}
        cat.setdefault("itens", [])
        if not cat["itens"] and (p.get("universo") == "sistema"):
            continue  # lista vazia = catálogo inteiro, que já tem os extras
        validos = _ids_validos(eixo) if eixo != "efeitos" else (set(dp_visual.EFEITO_PARA_ZOOM) | {e["id"] for e in dp_visual.efeitos()})
        if eixo == "templates":
            import cenas_dp
            validos = set(cenas_dp.catalogo())
        ja = {i["id"] for i in cat["itens"]}
        add = [i for i in dict.fromkeys(ids) if i in validos and i not in ja]
        if not add:
            continue
        w0 = sum(max(1, int(i.get("peso") or 1)) for i in cat["itens"])
        fator = max(1, -(-len(add) // max(1, w0))) if w0 else 1
        for i in cat["itens"]:
            i["peso"] = max(1, int(i.get("peso") or 1)) * fator
            i["original"] = True
        cat["itens"] += [{"id": i, "peso": 1, "extra": True} for i in add]
        if not cat.get("pct") and eixo in PCT_MINIMO_EXTRAS:
            cat["pct"] = PCT_MINIMO_EXTRAS[eixo]
        out[eixo] = cat
    return out


def sistema() -> List[Dict[str, Any]]:
    """As direções do sistema já com os extras e os quadros editoriais."""
    import direcoes_canais
    return [_com_extras(p) for p in list(dp_visual.dp()["presets"]["system"]) + direcoes_canais.todas()]


def direcoes(com_usuario: bool = True) -> List[Dict[str, Any]]:
    out = []
    lista = sistema() + (predefinicoes_usuario() if com_usuario else [])
    for p in lista:
        out.append({
            "id": p["id"], "nome": p["nome"], "ritmo": p.get("ritmo") or "equilibrado",
            "universo": p.get("universo"), "sistema": bool(p.get("sistema")), "usuario": bool(p.get("usuario")),
            "resumo": _resumo(p),
            "categorias": {c: {"pct": (p.get(c) or {}).get("pct", 0), "itens": [(i["id"], i.get("peso", 1)) for i in (p.get(c) or {}).get("itens", [])]}
                           for c in EIXOS},
            "destaques": p.get("destaques"), "cores": p.get("cores"), "legenda": p.get("legenda"),
            "editoriais": editoriais_da(p),
            "extras": sum(1 for c in EIXOS for i in (p.get(c) or {}).get("itens", []) if i.get("extra")),
        })
    return out


# ---------------------------------------------------------------- do usuário
def _ler() -> Dict[str, Any]:
    try:
        with open(ARQUIVO_USUARIO, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar(d: Dict[str, Any]) -> None:
    tmp = ARQUIVO_USUARIO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ARQUIVO_USUARIO)


def predefinicoes_usuario() -> List[Dict[str, Any]]:
    return [p for p in _ler().get("predefinicoes") or [] if isinstance(p, dict) and p.get("id")]


def paletas_usuario() -> List[Dict[str, Any]]:
    return [p for p in _ler().get("paletas") or [] if isinstance(p, dict) and p.get("id")]


def _ids_validos(eixo: str) -> set:
    if eixo == "filtros":
        return {f["id"] for f in dp_visual.filtros() if f["id"] != "original"}
    if eixo == "efeitos":
        return set(dp_visual.EFEITO_PARA_ZOOM)
    if eixo == "overlays":
        return {e["id"] for e in dp_visual.efeitos() if e["id"] != "none" and not dp_visual.efeito_e_movimento(e["id"])}
    if eixo in ("entradas", "saidas"):
        return {e["id"] for e in dp_visual.entradas() if e["id"] != "none"}
    if eixo == "transicoes":
        import site_config
        return {t["dp_id"] for t in dp_visual.transicoes()} | {v for v, _r in site_config.TRANSITION_LABELS if v != "none" and not v.startswith("dp:")}
    if eixo == "templates":
        import cenas_dp
        return {tid for tid, t in cenas_dp.catalogo().items() if not t.get("manualOnly")}
    return set()


def _cor(v: Any, padrao: str) -> str:
    v = str(v or "")
    return v.upper() if re.fullmatch(r"#[0-9a-fA-F]{6}", v) else padrao


def _slug(nome: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:28] or "predef"


def normalizar_predefinicao(d: Dict[str, Any]) -> Dict[str, Any]:
    """Valida uma predefinição vinda do editor (ids desconhecidos saem)."""
    if not isinstance(d, dict):
        raise ValueError("Predefinição inválida.")
    nome = str(d.get("nome") or "").strip()[:60]
    if not nome:
        raise ValueError("Dê um nome à predefinição.")
    out: Dict[str, Any] = {"nome": nome, "usuario": True, "sistema": False, "v": 3,
                           "ritmo": d.get("ritmo") if d.get("ritmo") in RITMOS else "equilibrado",
                           "universo": "sistema" if d.get("universo") == "sistema" else "predef"}
    for eixo in EIXOS:
        c = d.get(eixo) if isinstance(d.get(eixo), dict) else {}
        validos = _ids_validos(eixo)
        itens, vistos = [], set()
        for it in c.get("itens") or []:
            iid = str((it.get("id") if isinstance(it, dict) else it) or "")
            if eixo == "transicoes" and iid.startswith("dp:"):
                iid = iid[3:]
            if iid in validos and iid not in vistos:
                vistos.add(iid)
                peso = it.get("peso", 1) if isinstance(it, dict) else 1
                itens.append({"id": iid, "peso": max(1, min(100, int(float(peso or 1))))})
        try:
            pct = max(0, min(100, int(float(c.get("pct", 0) or 0))))
        except (TypeError, ValueError):
            pct = 0
        out[eixo] = {"pct": pct, "itens": itens}
    ds = d.get("destaques") if isinstance(d.get("destaques"), dict) else {}
    import dp_destaques
    cat = dp_destaques.catalogo()
    out["destaques"] = {"densidade": ds.get("densidade") if ds.get("densidade") in DENSIDADES else "equilibrado",
                        "estilos": [e for e in dict.fromkeys(ds.get("estilos") or []) if e in cat],
                        "ativo": ds.get("ativo", True) is not False}
    cs = d.get("cores") if isinstance(d.get("cores"), dict) else {}
    import dp_cores
    prim = _cor(cs.get("primaria"), "#FFD60A")
    der = dp_cores.derivar(prim)
    out["cores"] = {"ativa": True, "modo": cs.get("modo") if cs.get("modo") in MODOS_COR else "projeto", "primaria": prim,
                    "secundaria": _cor(cs.get("secundaria"), der["secundaria"]), "acento": _cor(cs.get("acento"), der["acento"])}
    if isinstance(d.get("legenda"), dict):
        import dp_legendas
        out["legenda"] = dict(dp_legendas.normalizar(d["legenda"]), ativa=True)
    else:
        out["legenda"] = None
    ed = d.get("editoriais") if isinstance(d.get("editoriais"), dict) else {}
    out["editoriais"] = {k: v for k, v in editoriais_da({"editoriais": ed}).items() if k != "segundos"}
    out["som_transicoes"] = d.get("som_transicoes") if d.get("som_transicoes") in ("auto", "nenhum") else "auto"
    out["descricao"] = str(d.get("descricao") or "")[:200]
    return out


def salvar_predefinicao(d: Dict[str, Any]) -> Dict[str, Any]:
    p = normalizar_predefinicao(d)
    with _TRAVA:
        dados = _ler()
        lista = [x for x in dados.get("predefinicoes") or [] if isinstance(x, dict)]
        pid = str(d.get("id") or "")
        if not pid.startswith("u_") or not any(x.get("id") == pid for x in lista):
            base = "u_" + _slug(p["nome"])
            pid, k = base, 2
            while any(x.get("id") == pid for x in lista):
                pid, k = f"{base}_{k}", k + 1
        p["id"] = pid
        p["atualizada"] = time.time()
        lista = [x for x in lista if x.get("id") != pid] + [p]
        dados["predefinicoes"] = lista
        _gravar(dados)
    return p


def apagar_predefinicao(pid: str) -> bool:
    with _TRAVA:
        dados = _ler()
        lista = dados.get("predefinicoes") or []
        nova = [x for x in lista if x.get("id") != pid]
        if len(nova) == len(lista):
            return False
        dados["predefinicoes"] = nova
        _gravar(dados)
    return True


def para_edicao(did: str, kit: Optional[Dict[str, List[str]]] = None) -> Optional[Dict[str, Any]]:
    """Cópia completa (todos os eixos separados) pra abrir no editor —
    serve pra duplicar uma do sistema ou editar uma da pessoa."""
    p = direcao(did, kit)
    if not p:
        return None
    out = json.loads(json.dumps(p))
    if not p.get("usuario"):
        # no JSON do sistema os overlays vêm misturados com os efeitos: separa
        efs = (out.get("efeitos") or {}).get("itens") or []
        mov = [i for i in efs if dp_visual.efeito_e_movimento(i["id"])]
        ovs = [i for i in efs if not dp_visual.efeito_e_movimento(i["id"])]
        pct = (out.get("efeitos") or {}).get("pct", 0)
        out["efeitos"] = {"pct": pct, "itens": mov}
        if ovs:
            out["overlays"] = {"pct": max((out.get("overlays") or {}).get("pct", 0), pct // 2 if ovs else 0), "itens": ovs}
        if out.get("cores") is None:
            out["cores"] = {"modo": "projeto", "primaria": "#FFD60A"}
        out["nome"] = ("Cópia de " + p["nome"]) if did != "kit" else "Minha direção"
        out.pop("id", None)
    return out


def salvar_paleta(d: Dict[str, Any]) -> Dict[str, Any]:
    nome = str((d or {}).get("nome") or "").strip()[:40]
    if not nome:
        raise ValueError("Dê um nome à paleta.")
    prim = _cor(d.get("primaria"), "")
    if not prim:
        raise ValueError("Cor primária inválida.")
    import dp_cores
    der = dp_cores.derivar(prim)
    p = {"nome": nome, "primaria": prim, "secundaria": _cor(d.get("secundaria"), der["secundaria"]),
         "acento": _cor(d.get("acento"), der["acento"]), "usuario": True}
    with _TRAVA:
        dados = _ler()
        lista = [x for x in dados.get("paletas") or [] if isinstance(x, dict)]
        pid = str(d.get("id") or "")
        if not pid.startswith("up_") or not any(x.get("id") == pid for x in lista):
            base = "up_" + _slug(nome)
            pid, k = base, 2
            while any(x.get("id") == pid for x in lista):
                pid, k = f"{base}_{k}", k + 1
        p["id"] = pid
        dados["paletas"] = [x for x in lista if x.get("id") != pid] + [p]
        _gravar(dados)
    return p


def apagar_paleta(pid: str) -> bool:
    with _TRAVA:
        dados = _ler()
        lista = dados.get("paletas") or []
        nova = [x for x in lista if x.get("id") != pid]
        if len(nova) == len(lista):
            return False
        dados["paletas"] = nova
        _gravar(dados)
    return True


_KIT: Dict[str, Any] = {}


def preset_do_kit(kit: Optional[Dict[str, List[str]]]) -> Dict[str, Any]:
    """"★ Minha direção": só o que a pessoa marcou nas galerias (peso 1 cada)."""
    kit = kit or {}
    efeitos = list(kit.get("animacoes_camera") or []) + list(kit.get("overlays") or [])

    def cat(ids, pct):
        return {"pct": pct if ids else 0, "itens": [{"id": i, "peso": 1} for i in ids]}
    return {
        "id": "kit", "nome": "★ Minha direção (o que eu marquei)", "ritmo": "equilibrado", "universo": "predef",
        "filtros": cat(list(kit.get("filtros") or []), 100), "efeitos": cat(efeitos, 55),
        "transicoes": cat(list(kit.get("transicoes") or []), 55), "entradas": cat(list(kit.get("entradas") or []), 30),
        "saidas": cat([], 0), "templates": cat(list(kit.get("templates") or []), 20),
        "destaques": {"densidade": "equilibrado", "estilos": list(kit.get("destaques") or [])},
        "editoriais": {"ativo": True, "densidade": "equilibrado", "tipos": list(kit.get("editoriais") or [])},
    }


def direcao(did: str, kit: Optional[Dict[str, List[str]]] = None) -> Optional[Dict[str, Any]]:
    if did == "kit":
        return preset_do_kit(kit)
    p = next((p for p in sistema() if p["id"] == did), None)
    if p is None and did.startswith("u_"):
        p = next((x for x in predefinicoes_usuario() if x.get("id") == did), None)
    return p


def _resumo(p: Dict[str, Any]) -> str:
    partes = []
    for c, nome in (("filtros", "filtro"), ("efeitos", "movimento" if p.get("usuario") else "efeitos"), ("overlays", "overlays"),
                    ("transicoes", "transições"), ("entradas", "entradas"), ("saidas", "saídas"), ("templates", "templates")):
        cat = p.get(c) or {}
        if cat.get("pct"):
            itens = ", ".join(i["id"] for i in cat.get("itens", [])[:5]) or "catálogo todo"
            partes.append(f"{nome} {cat['pct']}% ({itens})")
    return " · ".join(partes)


def _ritmos() -> Dict[str, Dict[str, float]]:
    return dp_visual.dp()["rules"]["plan"]["rhythms"]


def _catalogo_cheio(cat: str) -> List[tuple]:
    if cat == "filtros":
        return [(f["id"], 1) for f in dp_visual.filtros() if f["id"] != "original"]
    if cat == "efeitos":
        return [(e["id"], 1) for e in dp_visual.efeitos() if e["id"] != "none"]
    if cat == "overlays":
        return [(e["id"], 1) for e in dp_visual.efeitos() if e["id"] != "none" and not dp_visual.efeito_e_movimento(e["id"])]
    if cat in ("entradas", "saidas"):
        return [(e["id"], 1) for e in dp_visual.entradas() if e["id"] != "none"]
    if cat == "transicoes":
        return [(t["dp_id"], 1) for t in dp_visual.transicoes()]
    if cat == "templates":
        import cenas_dp
        return [(tid, 1) for tid, t in cenas_dp.catalogo().items() if t.get("autoEligible") and not t.get("manualOnly")]
    return []


def _itens(p: Dict[str, Any], cat: str) -> List[tuple]:
    itens = [(i["id"], max(1, int(i.get("peso") or 1))) for i in (p.get(cat) or {}).get("itens", [])]
    if not itens and (p.get("sistema") or p.get("universo") == "sistema"):
        itens = _catalogo_cheio(cat)
        if cat == "efeitos" and p.get("usuario"):  # nas da pessoa "Movimento" é só câmera (overlays é eixo próprio)
            itens = [x for x in itens if dp_visual.efeito_e_movimento(x[0])]
    return itens


def _sorteia(rng: random.Random, itens: List[tuple], evitar: Optional[str] = None) -> Optional[str]:
    if not itens:
        return None
    pool = [x for x in itens if x[0] != evitar] or itens
    total = sum(w for _i, w in pool)
    r = rng.uniform(0, total)
    acc = 0.0
    for iid, w in pool:
        acc += w
        if r <= acc:
            return iid
    return pool[-1][0]


def planejar(segmentos: List[Dict[str, Any]], did: str, semente: Any = 1, ritmo: Optional[str] = None,
             so_vazios: bool = False, kit: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """segmentos: [{start, end, foto: bool, template?, transition?, efeito?, entrada?, saida?}]
    Devolve {"filtro_cor": id|None, "trechos": [{transition, efeito, entrada, saida, template}], "direcao": id}."""
    p = direcao(did, kit)
    if not p:
        raise ValueError(f"Direção desconhecida: {did!r}")
    rng = random.Random(f"{semente}:{did}")
    ritmo = ritmo or p.get("ritmo") or "equilibrado"
    r = _ritmos().get(ritmo) or _ritmos()["equilibrado"]
    fator = float(r.get("fator", 1))

    def pct(cat):
        return min(100.0, float((p.get(cat) or {}).get("pct", 0)) * fator) / 100.0

    n = len(segmentos)
    plano = [{"transition": None, "efeito": None, "entrada": None, "saida": None, "template": None} for _ in range(n)]

    # ---- templates (regiões de N trechos livres, com intervalo mínimo)
    import cenas_dp
    tpl_itens = _itens(p, "templates")
    gap = float(r.get("gapTplS", 16))
    if tpl_itens and pct("templates") > 0:
        ultimo_fim = -1e9
        i = 0
        while i < n:
            existente = segmentos[i].get("template")
            if existente:
                plano[i]["template"] = existente
                i += cenas_dp.slots_do_template(existente)
                ultimo_fim = segmentos[min(i, n) - 1]["end"]
                continue
            if so_vazios or segmentos[i]["start"] - ultimo_fim < gap or rng.random() >= pct("templates"):
                i += 1
                continue
            candidatos = []
            for tid, w in tpl_itens:
                t = cenas_dp.template(tid)
                if not t:
                    continue
                k = cenas_dp.slots_do_template(tid)
                if i + k > n or any(segmentos[j].get("template") for j in range(i, i + k)):
                    continue
                dur = segmentos[i + k - 1]["end"] - segmentos[i]["start"]
                if (t.get("durMinS") and dur < t["durMinS"]) or (t.get("durMaxS") and dur > t["durMaxS"]):
                    continue
                if any(segmentos[j]["end"] - segmentos[j]["start"] < 1.0 for j in range(i, i + k)):
                    continue
                candidatos.append((tid, w))
            escolhido = _sorteia(rng, candidatos)
            if escolhido:
                plano[i]["template"] = escolhido
                k = cenas_dp.slots_do_template(escolhido)
                ultimo_fim = segmentos[i + k - 1]["end"]
                i += k
            else:
                i += 1
    grupos = cenas_dp.planejar_grupos([pl["template"] for pl in plano])
    dentro = set()
    for a, b, tid in grupos:
        if tid:
            dentro.update(range(a, b))  # emendas a..b-1 ficam dentro da cena

    # ---- transições (por emenda)
    tr_itens = _itens(p, "transicoes")
    anterior = None
    for i in range(n - 1):
        if so_vazios and segmentos[i].get("transition"):
            plano[i]["transition"] = segmentos[i]["transition"]
            continue
        if i in dentro:
            plano[i]["transition"] = "none"
            continue
        if tr_itens and rng.random() < pct("transicoes"):
            tid = _sorteia(rng, tr_itens, anterior)
            plano[i]["transition"] = dp_visual.valor_transicao(tid)
            anterior = tid
        else:
            plano[i]["transition"] = "none"

    # ---- efeitos / entradas / saídas (por trecho)
    for cat, chave in (("efeitos", "efeito"), ("entradas", "entrada"), ("saidas", "saida")):
        itens = _itens(p, cat)
        anterior = None
        for i, s in enumerate(segmentos):
            if so_vazios and s.get(chave):
                plano[i][chave] = s[chave]
                continue
            if not itens or rng.random() >= pct(cat):
                continue
            validos = itens
            if cat == "efeitos" and not s.get("foto"):
                validos = [x for x in itens if not dp_visual.efeito_e_movimento(x[0])]
            escolhido = _sorteia(rng, validos, anterior)
            if escolhido:
                plano[i][chave] = escolhido
                anterior = escolhido

    # ---- overlays (eixo próprio nas predefinições da pessoa): vão nos trechos
    # que ficaram sem efeito (um efeito por trecho no site)
    ov_itens = _itens(p, "overlays") if p.get("usuario") else []
    if ov_itens and pct("overlays") > 0:
        anterior = None
        for i, s in enumerate(segmentos):
            if plano[i]["efeito"] or (so_vazios and s.get("efeito")) or rng.random() >= pct("overlays"):
                continue
            escolhido = _sorteia(rng, ov_itens, anterior)
            plano[i]["efeito"] = escolhido
            anterior = escolhido

    # ---- filtro: UM por vídeo (identidade global)
    filtro = None
    f_itens = _itens(p, "filtros")
    if f_itens and ((p.get("filtros") or {}).get("itens") or rng.random() < pct("filtros")):
        filtro = _sorteia(rng, f_itens)
    return {"direcao": did, "ritmo": ritmo, "semente": semente, "filtro_cor": filtro, "trechos": plano,
            "cores": cores_do_plano(p), "legenda": p.get("legenda"), "destaques": p.get("destaques"), "editoriais": editoriais_da(p),
            "som_transicoes": p.get("som_transicoes") or (p.get("transicoes") or {}).get("som") or "auto",
            # 🪧 a direção pode escolher as bordas (ex.: Propaganda = cartão sobre fundo) e o fundo dos cartões
            "bordas": p.get("bordas") if p.get("bordas") in ("black", "mosaic", "zoom", "smart", "cartao") else None,
            "cartao_fundo": p.get("cartao_fundo") if isinstance(p.get("cartao_fundo"), dict) else None}


def cores_do_plano(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """O que a predefinição faz com a paleta do projeto:
    auto    -> cada destaque/texto com a cor original (paleta.modo = auto)
    predef  -> a cor da predefinição vira a paleta do projeto (tons derivam dela)
    projeto -> mantém a cor escolhida no projeto (None = não mexe)."""
    cs = p.get("cores")
    if not isinstance(cs, dict) or cs.get("modo") not in ("auto", "predef"):
        return None
    if cs["modo"] == "auto":
        return {"modo": "auto"}
    import dp_cores
    prim = _cor(cs.get("primaria"), "#FFD60A")
    der = dp_cores.derivar(prim)
    return {"modo": "projeto", "id": "predef:" + str(p.get("id") or ""), "primaria": prim,
            "secundaria": _cor(cs.get("secundaria"), der["secundaria"]), "acento": _cor(cs.get("acento"), der["acento"])}
