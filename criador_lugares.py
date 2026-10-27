"""
criador_lugares.py — 🗺 Lugares e mundos (v84_241, parte do 🧬 Criador)
=======================================================================

Criar LUGARES fictícios em qualquer escala — do quarto ao universo — com:
  • 📥 entrada como no criador de personagens: descrição, imagens de referência numeradas (o que pegar de cada uma:
    arquitetura, terreno, luz, clima, mobília, cultura, traço…), inspirações, 🎨 estilo e 🕰 época (+ "outro");
  • 🧭 hierarquia: cada lugar pode estar DENTRO de outro (quarto → casa → bairro → cidade → estado → país → continente →
    mundo → sistema → galáxia → universo) — a página navega pelo caminho e pelos sub-lugares;
  • 📝 ficha (🤖 IA): nomes, descrição visual travada (inglês), história, linha do tempo, pessoas importantes (cada uma
    vira um personagem no 🧬 com 1 clique), cultura, clima, economia/recursos, curiosidades, segredos e os PONTOS do mapa
    (com a posição);
  • 📷 fotos no Flow (16:9): as vistas que fazem sentido pra escala (fachada, rua, skyline, paisagem, vista do espaço…);
  • 🗺 MAPA de verdade: gerado no Flow (planta baixa, mapa ilustrado, atlas, carta estelar…) ou o seu; na página dá pra
    arrastar/dar zoom, clicar nos 📍 pinos (nome, descrição, abrir o sub-lugar), criar/mover pinos, 📏 medir distâncias
    (a escala do mapa: largura em m / km / UA / anos-luz…) e descer pro mapa do sub-lugar.
  • ⬇ zip: fotos, mapa, pinos (json) e a ficha.
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import secrets
import shutil
import threading
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import criador_personagens as C

_BASE = C._BASE
_TRAVA = threading.RLock()
RE_ID = re.compile(r"^lg[0-9a-f]{10}$")
ESPERA = ("fila", "gerando")


class LugarErro(Exception):
    pass


# escala → (rótulo, tipo do mapa em inglês, (largura padrão do mapa, unidade), vistas [(chave, rótulo, inglês)])
ESCALAS: Dict[str, Tuple[str, str, Tuple[float, str], List[Tuple[str, str, str]]]] = {
    "comodo": ("🛏 Cômodo / quarto", "a clean top-down architectural FLOOR PLAN of the room, furniture drawn from above",
               (6, "m"), [("geral", "vista geral", "wide interior shot of the whole room from the doorway, eye level"),
                          ("canto", "um canto / detalhe", "a characteristic corner of the room, details and objects"),
                          ("noite", "à noite", "the same room at night with its own lights on")]),
    "casa": ("🏠 Casa / construção", "a top-down architectural FLOOR PLAN of the building with its rooms, seen from above",
             (25, "m"), [("fachada", "fachada", "the front facade of the building seen from the street"),
                         ("interior", "interior principal", "the main interior space, wide shot"),
                         ("arredores", "quintal / arredores", "the surroundings, garden or yard"),
                         ("noite", "à noite", "the facade at night, windows lit")]),
    "bairro": ("🏘 Bairro / vila / distrito", "an illustrated top-down NEIGHBORHOOD MAP with streets, blocks, squares and green areas",
               (2, "km"), [("rua", "rua principal", "the main street at street level, daily life"),
                           ("praca", "praça / ponto de encontro", "the main square or meeting point"),
                           ("alto", "vista do alto", "an aerial view over the neighborhood"),
                           ("noite", "à noite", "the main street at night")]),
    "cidade": ("🏙 Cidade", "an illustrated top-down CITY MAP with districts, main avenues, rivers, parks and landmarks",
               (15, "km"), [("panorama", "panorama / skyline", "a wide panoramic view of the whole city"),
                            ("rua", "rua movimentada", "a busy street at eye level with people"),
                            ("marco", "ponto marcante", "the most famous landmark of the city"),
                            ("mercado", "mercado / centro", "the market or downtown"),
                            ("noite", "à noite", "the city skyline at night")]),
    "regiao": ("🏞 Estado / região / província", "a REGIONAL MAP with terrain relief, rivers, roads, forests and towns as dots",
               (300, "km"), [("paisagem", "paisagem típica", "a typical landscape of the region"),
                             ("capital", "capital", "the capital town of the region"),
                             ("campo", "campo / interior", "the countryside with its people"),
                             ("marco", "marco natural", "the most famous natural landmark")]),
    "pais": ("🏳 País / reino / império", "a fantasy-ATLAS style COUNTRY MAP with borders, mountain ranges, rivers, coasts, forests and cities as dots",
             (1200, "km"), [("capital", "capital", "the capital city, grand wide view"),
                            ("paisagem", "paisagem", "an iconic landscape of the country"),
                            ("povo", "o povo no dia a dia", "ordinary people in daily life, typical clothing"),
                            ("monumento", "monumento / símbolo", "the national monument or symbol")]),
    "continente": ("🌍 Continente", "a CONTINENT MAP in atlas style, nations' borders, mountain ranges, seas and climate zones",
                   (5000, "km"), [("vista", "vista geral", "a sweeping aerial view of the continent's landscapes"),
                                  ("contraste", "regiões contrastantes", "two contrasting regions of the continent"),
                                  ("costa", "litoral", "its most striking coastline")]),
    "mundo": ("🪐 Mundo / planeta", "a WORLD MAP projection with continents, oceans, ice caps and major features",
              (40000, "km"), [("espaco", "vista do espaço", "the planet seen from space"),
                              ("paisagem", "paisagem típica", "a typical landscape on the surface"),
                              ("ceu", "o céu (luas, sol)", "the sky as seen from the surface (moons, sun, rings)"),
                              ("civilizacao", "civilização", "the greatest city or civilization of the world")]),
    "sistema": ("☀ Sistema estelar", "a top-down ORBITAL CHART of the star system, orbits as thin rings, planets and belts",
                (60, "UA"), [("estrela", "a estrela", "the star of the system, close view"),
                             ("planeta", "planeta principal", "the main planet seen from orbit"),
                             ("cinturao", "cinturão / estação", "an asteroid belt or space station")]),
    "galaxia": ("🌌 Galáxia", "a GALAXY CHART seen from above, spiral arms, sectors, nebulae, a glowing core",
                (100000, "anos-luz"), [("vista", "vista da galáxia", "the whole galaxy seen from outside"),
                                       ("nebulosa", "nebulosa", "a colorful nebula of the galaxy"),
                                       ("setor", "setor habitado", "an inhabited sector with ships and stations")]),
    "universo": ("✨ Universo / multiverso / plano", "a cosmic DIAGRAM MAP of the universe / planes of existence and how they connect",
                 (93, "bilhões de anos-luz"), [("cosmos", "visão cósmica", "a breathtaking cosmic vista of this universe"),
                                               ("fronteira", "fronteira / borda", "the edge or boundary of this universe"),
                                               ("plano", "outro plano / dimensão", "another plane or dimension of it")]),
    "outro": ("✍ Outro", "an illustrated top-down MAP of this place", (10, "km"),
              [("geral", "vista geral", "a wide establishing view of the place"),
               ("detalhe", "detalhe", "a characteristic detail of the place")]),
}
ORDEM_ESCALAS = list(ESCALAS)
ASPECTOS_LUGAR: Dict[str, Tuple[str, str]] = {
    "tudo": ("🧬 tudo (recriar)", "the WHOLE place — recreate it recognizably"),
    "arquitetura": ("🏛 arquitetura", "the ARCHITECTURE and building style"),
    "terreno": ("⛰ terreno / paisagem", "the TERRAIN and landscape"),
    "luz": ("💡 luz / cores", "the LIGHTING and color palette"),
    "clima": ("🌫 clima / atmosfera", "the WEATHER and atmosphere"),
    "objetos": ("🪑 mobília / objetos", "the FURNITURE and objects"),
    "cultura": ("👘 cultura / pessoas", "the culture, people and clothing"),
    "traco": ("✒ traço / estilo", "the ART STYLE of the picture"),
    "mapa": ("🗺 estilo do mapa", "the STYLE of the MAP (for the map only)"),
}


# ------------------------------------------------------------------ guardar
def pasta(lid: str, base: str = _BASE) -> str:
    if not RE_ID.match(lid or ""):
        raise LugarErro("Lugar inválido.")
    return os.path.join(C.pasta_raiz(base), "lugares", lid)


def _completar(p: Dict[str, Any]) -> Dict[str, Any]:
    p.setdefault("escala", "cidade")
    p.setdefault("pai", None)
    e = p.setdefault("entrada", {})
    for k, v in (("descricao", ""), ("inspiracoes", ""), ("estilo", "anime"), ("estilo_livre", ""), ("epoca", ""),
                 ("epoca_livre", ""), ("evitar", ""), ("escala_livre", ""), ("original", True)):
        e.setdefault(k, v)
    e.setdefault("refs", [])
    p.setdefault("ficha", {})
    p.setdefault("fotos", [])
    p.setdefault("mapa", {"variacoes": [], "aprovado": None, "largura": None, "unidade": None})
    p.setdefault("pinos", [])
    p.setdefault("log", [])
    return p


def criar(nome: str = "", escala: str = "cidade", pai: str = "", base: str = _BASE, **entrada: Any) -> Dict[str, Any]:
    escala = escala if escala in ESCALAS else "cidade"
    p = _completar({"id": "lg" + secrets.token_hex(5), "nome": C._txt(nome, 80) or "Lugar novo", "criado": time.time(),
                    "escala": escala, "pai": pai if pai and RE_ID.match(pai) else None})
    if p["pai"]:
        try:  # herda o estilo e a época do lugar de cima
            pp_ = carregar(p["pai"], base)
            for k in ("estilo", "estilo_livre", "epoca", "epoca_livre"):
                p["entrada"][k] = pp_["entrada"].get(k) or p["entrada"][k]
        except LugarErro:
            p["pai"] = None
    editar_entrada(p, entrada)
    salvar(p, base)
    return p


def carregar(lid: str, base: str = _BASE) -> Dict[str, Any]:
    try:
        with open(os.path.join(pasta(lid, base), "lugar.json"), encoding="utf-8") as f:
            return _completar(json.load(f))
    except FileNotFoundError:
        raise LugarErro("Lugar não encontrado.")


def salvar(p: Dict[str, Any], base: str = _BASE) -> None:
    d = pasta(p["id"], base)
    os.makedirs(d, exist_ok=True)
    p["atualizado"] = time.time()
    tmp = os.path.join(d, f"lugar.json.{secrets.token_hex(3)}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(d, "lugar.json"))


def todos(base: str = _BASE) -> List[Dict[str, Any]]:
    raiz = os.path.join(C.pasta_raiz(base), "lugares")
    out = []
    for n in sorted(os.listdir(raiz)) if os.path.isdir(raiz) else []:
        if RE_ID.match(n):
            try:
                out.append(carregar(n, base))
            except Exception:  # noqa: BLE001
                continue
    return out


def listar(base: str = _BASE) -> List[Dict[str, Any]]:
    out = []
    for p in todos(base):
        foto = next((v.get("arquivo") for f in p["fotos"] for v in [f] if v.get("arquivo") and v.get("aprovada")), None) \
            or next((f.get("arquivo") for f in p["fotos"] if f.get("arquivo")), None)
        out.append({"id": p["id"], "nome": p["nome"], "escala": ESCALAS[p["escala"]][0], "pai": p["pai"],
                    "miniatura": foto, "atualizado": p.get("atualizado") or 0, "nivel": ORDEM_ESCALAS.index(p["escala"])})
    return sorted(out, key=lambda x: (-x["nivel"], -x["atualizado"]))


def excluir(lid: str, base: str = _BASE) -> None:
    """Apaga o lugar; os sub-lugares sobem um nível (ficam dentro do lugar de cima dele)."""
    p = carregar(lid, base)
    for f in filhos(lid, base):
        f["pai"] = p.get("pai")
        salvar(f, base)
    shutil.rmtree(pasta(lid, base), ignore_errors=True)


def filhos(lid: str, base: str = _BASE) -> List[Dict[str, Any]]:
    return [x for x in todos(base) if x.get("pai") == lid]


def caminho(p: Dict[str, Any], base: str = _BASE) -> List[Dict[str, str]]:
    """🧭 Do maior pro menor: universo › galáxia › … › este lugar."""
    out, vistos, cur = [], set(), p
    while cur and cur["id"] not in vistos:
        vistos.add(cur["id"])
        out.append({"id": cur["id"], "nome": cur["nome"], "escala": ESCALAS[cur["escala"]][0]})
        try:
            cur = carregar(cur["pai"], base) if cur.get("pai") else None
        except LugarErro:
            cur = None
    return out[::-1]


def log(p: Dict[str, Any], msg: str) -> None:
    p["log"] = (p.get("log") or [])[-60:] + [{"t": time.time(), "msg": msg}]


# ------------------------------------------------------------------ 📥 entrada
CAMPOS = {"descricao": 4000, "inspiracoes": 1500, "estilo_livre": 300, "epoca_livre": 200, "evitar": 800, "escala_livre": 100}


def editar_entrada(p: Dict[str, Any], dados: Dict[str, Any]) -> None:
    e = p["entrada"]
    for k, n in CAMPOS.items():
        if k in dados and dados[k] is not None:
            e[k] = str(dados[k]).strip()[:n]
    if dados.get("estilo") is not None:
        e["estilo"] = dados["estilo"] if dados["estilo"] in C.ESTILOS or dados["estilo"] == C.ESTILO_OUTRO else "anime"
    if dados.get("epoca") is not None:
        e["epoca"] = dados["epoca"] if dados["epoca"] in C.EPOCAS or dados["epoca"] == C.EPOCA_OUTRO else ""
    if "original" in dados:
        e["original"] = bool(dados["original"])
    if dados.get("nome"):
        p["nome"] = C._txt(dados["nome"], 80)
    if dados.get("escala") in ESCALAS:
        p["escala"] = dados["escala"]
    if "pai" in dados:
        pai = str(dados["pai"] or "")
        if pai and (not RE_ID.match(pai) or pai == p["id"]):
            raise LugarErro("Lugar de cima inválido.")
        p["pai"] = pai or None


def guardar_ref(p: Dict[str, Any], img, pegar: Optional[List[str]] = None, nota: str = "", base: str = _BASE) -> Dict[str, Any]:
    if len(p["entrada"]["refs"]) >= C.MAX_REFS:
        raise LugarErro(f"No máximo {C.MAX_REFS} imagens de referência.")
    d = os.path.join(pasta(p["id"], base), "refs")
    os.makedirs(d, exist_ok=True)
    im = img.convert("RGB")
    im.thumbnail((1600, 1600))
    arq = f"ref_{secrets.token_hex(3)}.jpg"
    im.save(os.path.join(d, arq), quality=92)
    r = {"arquivo": arq, "pegar": [a for a in (pegar or ["tudo"]) if a in ASPECTOS_LUGAR] or ["tudo"], "nota": C._txt(nota, 300)}
    p["entrada"]["refs"].append(r)
    return r


def editar_ref(p: Dict[str, Any], arquivo: str, dados: Dict[str, Any], base: str = _BASE) -> None:
    refs = p["entrada"]["refs"]
    r = next((x for x in refs if x["arquivo"] == arquivo), None)
    if not r:
        raise LugarErro("Imagem não encontrada.")
    if dados.get("apagar"):
        refs.remove(r)
        try:
            os.remove(os.path.join(pasta(p["id"], base), "refs", arquivo))
        except OSError:
            pass
        return
    if "pegar" in dados:
        r["pegar"] = [a for a in dados["pegar"] or [] if a in ASPECTOS_LUGAR] or ["tudo"]
    if "nota" in dados:
        r["nota"] = C._txt(dados["nota"], 300)


def estilo_en(p: Dict[str, Any]) -> str:
    return C.estilo_en({"entrada": p["entrada"]})


def escala_nome(p: Dict[str, Any]) -> str:
    return ("✍ " + p["entrada"]["escala_livre"]) if p["escala"] == "outro" and p["entrada"].get("escala_livre") else ESCALAS[p["escala"]][0]


def mapa_refs(p: Dict[str, Any], so_mapa: bool = False) -> List[str]:
    out = []
    for k, r in enumerate(p["entrada"]["refs"]):
        pegar = [a for a in r.get("pegar") or ["tudo"] if (a == "mapa") == so_mapa or a == "tudo"]
        if not pegar:
            continue
        out.append(f"panel {k + 1}: take ONLY " + "; ".join(ASPECTOS_LUGAR[a][1] for a in pegar)
                   + (f" (note: {r['nota']})" if r.get("nota") else ""))
    return out


def _colagem(p: Dict[str, Any], base: str) -> Optional[str]:
    d = os.path.join(pasta(p["id"], base), "refs")
    return C.colagem_de([os.path.join(d, r["arquivo"]) for r in p["entrada"]["refs"]], os.path.join(pasta(p["id"], base), "flow_refs"))


# ------------------------------------------------------------------ 📝 ficha
CAMPOS_FICHA = {"nome": 80, "descricao_en": 2500, "descricao_pt": 2000, "historia": 5000, "cultura": 2000, "clima": 800,
                "economia": 1200, "curiosidades": 2000, "segredos": 1500, "mapa_en": 1500, "originalidade": 600}
SCHEMA_FICHA = {
    "type": "object", "additionalProperties": False,
    "required": ["nomes", "descricao_en", "descricao_pt", "historia", "linha_do_tempo", "pessoas", "cultura", "clima",
                 "economia", "curiosidades", "segredos", "pontos", "mapa_en", "originalidade"],
    "properties": {
        "nomes": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["nome", "porque"],
                                             "properties": {"nome": {"type": "string"}, "porque": {"type": "string"}}}},
        "descricao_en": {"type": "string"}, "descricao_pt": {"type": "string"}, "historia": {"type": "string"},
        "linha_do_tempo": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                      "required": ["quando", "evento"],
                                                      "properties": {"quando": {"type": "string"}, "evento": {"type": "string"}}}},
        "pessoas": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                               "required": ["nome", "papel", "descricao", "aparencia_en"],
                                               "properties": {"nome": {"type": "string"}, "papel": {"type": "string"},
                                                              "descricao": {"type": "string"}, "aparencia_en": {"type": "string"}}}},
        "cultura": {"type": "string"}, "clima": {"type": "string"}, "economia": {"type": "string"},
        "curiosidades": {"type": "string"}, "segredos": {"type": "string"},
        "pontos": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                              "required": ["nome", "tipo", "descricao", "x", "y", "escala"],
                                              "properties": {"nome": {"type": "string"}, "tipo": {"type": "string"},
                                                             "descricao": {"type": "string"}, "x": {"type": "number"},
                                                             "y": {"type": "number"},
                                                             "escala": {"type": "string", "enum": [""] + ORDEM_ESCALAS}}}},
        "mapa_en": {"type": "string"}, "originalidade": {"type": "string"},
    },
}
SYS_FICHA = (
    "Você é um WORLDBUILDER (criador de mundos) e diretor de arte. Crie um LUGAR fictício e original, coerente com a "
    "escala (de um quarto a um universo), a época, o estilo e o lugar de cima (se tiver). Você recebe o pedido, imagens "
    "de referência NUMERADAS (com o que pegar de cada uma), inspirações e os sub-lugares que já existem. Escreva:\n"
    "- nomes: 5 ideias de nome com o porquê (o 1º é o seu favorito);\n"
    "- descricao_en: em INGLÊS, a descrição VISUAL travada pra desenhar sempre igual (arquitetura/terreno, materiais, "
    "cores, luz, clima, vegetação, tecnologia da época, detalhes únicos) — 70–150 palavras, sem nomes de obras "
    "existentes; descricao_pt: o mesmo em português, curto;\n"
    "- historia: a história do lugar (origem, fatos marcantes, como está hoje), 5–12 frases; linha_do_tempo: 4–10 "
    "marcos {quando, evento} em ordem;\n"
    "- pessoas: 3–8 pessoas importantes (governante, herói, vilão, figura popular, alguém do dia a dia…) com papel, "
    "descrição curta (personalidade e o que fez) e aparencia_en (em INGLÊS, visual, coerente com a época);\n"
    "- cultura (costumes, religião, festas, língua, comida), clima, economia (recursos, comércio, moeda), curiosidades, "
    "segredos (mistérios/ganchos de história);\n"
    "- pontos: 5–14 pontos do MAPA (sub-lugares e marcos: bairros, prédios, cidades, montanhas, planetas… conforme a "
    "escala) com tipo, descrição curta, posição x,y (0–1, x da esquerda pra direita, y de cima pra baixo — espalhe "
    "pelo mapa de forma coerente: rio cortando, costa de um lado…) e 'escala' = a escala do ponto se ele virar um "
    "sub-lugar (ou \"\" se é só um marco);\n"
    "- mapa_en: em INGLÊS, como desenhar o MAPA (o que fica em cada região — norte, sul, centro, a costa a leste… — "
    "batendo com as posições dos pontos), SEM nomes escritos (o site põe os pinos);\n"
    "- originalidade: se ficou parecido demais com um lugar famoso de alguma obra, diga qual e o que mudar; senão "
    "'ok — original'. Português do Brasil nos campos em português."
)


def _pedido(p: Dict[str, Any], base: str) -> str:
    e = p["entrada"]
    L = [f"ESCALA: {escala_nome(p)}", f"NOME: {p['nome']}" if p["nome"] != "Lugar novo" else "NOME: (sugira)"]
    cam = caminho(p, base)[:-1]
    if cam:
        L.append("FICA DENTRO DE: " + " › ".join(f"{x['nome']} ({x['escala']})" for x in cam))
        try:
            pai = carregar(p["pai"], base)
            if (pai.get("ficha") or {}).get("descricao_pt"):
                L.append(f"COMO É O LUGAR DE CIMA: {pai['ficha']['descricao_pt'][:600]}")
            pino = next((x for x in pai["pinos"] if x.get("lugar") == p["id"]), None)
            if pino and pino.get("descricao"):
                L.append(f"O QUE O LUGAR DE CIMA DIZ DESTE: {pino['descricao']}")
        except LugarErro:
            pass
    if e.get("descricao"):
        L.append(f"O QUE O USUÁRIO QUER: {e['descricao']}")
    for k, r in enumerate(e["refs"]):
        L.append(f"IMAGEM {k + 1}: pegar " + ", ".join(ASPECTOS_LUGAR[a][0] for a in r.get("pegar") or ["tudo"]
                                                   if a in ASPECTOS_LUGAR) + (f" — {r['nota']}" if r.get("nota") else ""))
    if e.get("inspiracoes"):
        L.append(f"INSPIRAÇÕES: {e['inspiracoes']}")
    L.append(f"ESTILO DE ARTE: {C.estilo_nome({'entrada': e})}")
    if C.epoca_en(e):
        L.append(f"ÉPOCA: {C.epoca_nome(e)} ({C.epoca_en(e)})")
    if e.get("evitar"):
        L.append(f"EVITAR: {e['evitar']}")
    fs = filhos(p["id"], base)
    if fs:
        L.append("SUB-LUGARES QUE JÁ EXISTEM (use nos pontos): " + "; ".join(f"{f['nome']} ({ESCALAS[f['escala']][0]})" for f in fs))
    if e.get("original"):
        L.append("QUER UM LUGAR BEM ORIGINAL.")
    return "\n".join(L)


def aplicar_ficha(p: Dict[str, Any], r: Dict[str, Any]) -> None:
    f = p["ficha"]
    for k, n in CAMPOS_FICHA.items():
        if k in r and r[k] is not None:
            f[k] = str(r[k]).strip()[:n]
    if isinstance(r.get("nomes"), list):
        f["nomes"] = [{"nome": C._txt(x.get("nome"), 60), "porque": C._txt(x.get("porque"), 200)}
                      for x in r["nomes"] if isinstance(x, dict) and x.get("nome")][:8]
        if f["nomes"] and p["nome"] == "Lugar novo":
            p["nome"] = f["nomes"][0]["nome"]
    if isinstance(r.get("linha_do_tempo"), list):
        f["linha_do_tempo"] = [{"quando": C._txt(x.get("quando"), 60), "evento": C._txt(x.get("evento"), 300)}
                               for x in r["linha_do_tempo"] if isinstance(x, dict) and x.get("evento")][:20]
    if isinstance(r.get("pessoas"), list):
        f["pessoas"] = [{"id": "ps" + secrets.token_hex(3), "nome": C._txt(x.get("nome"), 60), "papel": C._txt(x.get("papel"), 120),
                         "descricao": C._txt(x.get("descricao"), 600), "aparencia_en": C._txt(x.get("aparencia_en"), 800),
                         "personagem": None}
                        for x in r["pessoas"] if isinstance(x, dict) and x.get("nome")][:12]
    if isinstance(r.get("pontos"), list):  # 📍 os pinos da IA (os que você já mexeu ficam)
        meus = [x for x in p["pinos"] if x.get("manual") or x.get("lugar")]
        nomes = {x["nome"].lower() for x in meus}
        novos = [novo_pino(x.get("nome"), x.get("x"), x.get("y"), x.get("tipo"), x.get("descricao"),
                           x.get("escala") if x.get("escala") in ESCALAS else "")
                 for x in r["pontos"][:20] if isinstance(x, dict) and x.get("nome") and str(x["nome"]).lower() not in nomes]
        p["pinos"] = meus + novos
    if f.get("nome"):
        p["nome"] = f["nome"]


def ficha_sem_ia(p: Dict[str, Any]) -> Dict[str, Any]:
    return {"descricao_en": C._txt(p["entrada"].get("descricao"), 2500)}


def montar_ficha(lid: str, base: str = _BASE) -> str:
    p = carregar(lid, base)
    if not C.ia_ligada():
        with _TRAVA:
            p = carregar(lid, base)
            aplicar_ficha(p, ficha_sem_ia(p))
            log(p, "📝 ficha dos campos (a 🤖 IA está desligada)")
            salvar(p, base)
        return "sem IA"
    conteudo: List[Dict[str, Any]] = [{"type": "text", "text": _pedido(p, base)}]
    for k, r in enumerate(p["entrada"]["refs"]):
        b = C._ia().imagem_bloco(os.path.join(pasta(lid, base), "refs", r["arquivo"]), 512)
        if b:
            conteudo += [{"type": "text", "text": f"IMAGEM {k + 1}:"}, b]
    r = C._ia().chamar("criador", SYS_FICHA, conteudo, schema=SCHEMA_FICHA, max_tokens=6000, effort="medium", timeout=180)
    if not isinstance(r, dict):
        raise LugarErro("A IA não respondeu — tente de novo (ou escreva à mão).")
    with _TRAVA:
        p = carregar(lid, base)
        aplicar_ficha(p, r)
        log(p, "🤖 ficha montada pela IA")
        salvar(p, base)
    return "ficha pronta"


def editar_ficha(p: Dict[str, Any], dados: Dict[str, Any]) -> None:
    aplicar_ficha(p, {k: v for k, v in dados.items() if k in CAMPOS_FICHA or k in ("linha_do_tempo",)})
    if isinstance(dados.get("pessoas"), list):  # editar/apagar/adicionar pessoas (mantém o vínculo com o personagem)
        velhas = {x["id"]: x for x in p["ficha"].get("pessoas") or []}
        novas = []
        for x in dados["pessoas"][:20]:
            if not isinstance(x, dict) or not C._txt(x.get("nome"), 60):
                continue
            v = velhas.get(str(x.get("id") or ""), {})
            novas.append({"id": v.get("id") or "ps" + secrets.token_hex(3), "nome": C._txt(x.get("nome"), 60),
                          "papel": C._txt(x.get("papel"), 120), "descricao": C._txt(x.get("descricao"), 600),
                          "aparencia_en": C._txt(x.get("aparencia_en"), 800), "personagem": v.get("personagem")})
        p["ficha"]["pessoas"] = novas


def pessoa_vira_personagem(lid: str, psid: str, base: str = _BASE) -> str:
    """👤 → 🧬: a pessoa importante vira um personagem no criador (com a época, o estilo e o lugar de origem)."""
    with _TRAVA:
        p = carregar(lid, base)
        ps = next((x for x in p["ficha"].get("pessoas") or [] if x["id"] == psid), None)
        if not ps:
            raise LugarErro("Pessoa não encontrada.")
        if ps.get("personagem"):
            try:
                C.carregar(ps["personagem"], base)
                return ps["personagem"]
            except C.CriadorErro:
                pass
        c = C.criar(ps["nome"], base)
        C.editar_entrada(c, {"descricao": f"{ps['papel']}. {ps['descricao']}", "estilo": p["entrada"]["estilo"],
                             "estilo_livre": p["entrada"].get("estilo_livre") or "", "epoca": p["entrada"].get("epoca") or "",
                             "epoca_livre": p["entrada"].get("epoca_livre") or "", "lugar": p["id"]})
        if ps.get("aparencia_en"):
            C.aplicar_ficha(c, {"aparencia_en": ps["aparencia_en"], "personalidade": ps["descricao"]})
        c["nome"] = ps["nome"]
        C.salvar(c, base)
        ps["personagem"] = c["id"]
        log(p, f"👤 {ps['nome']} virou personagem no 🧬")
        salvar(p, base)
        return c["id"]


def personagens_daqui(lid: str, base: str = _BASE) -> List[Dict[str, Any]]:
    out = []
    for x in C.listar(base):
        try:
            if C.carregar(x["id"], base)["entrada"].get("lugar") == lid:
                out.append(x)
        except Exception:  # noqa: BLE001
            continue
    return out


# ------------------------------------------------------------------ 📍 pinos e escala do mapa
def novo_pino(nome: Any, x: Any, y: Any, tipo: Any = "", descricao: Any = "", escala: str = "", manual: bool = False) -> Dict[str, Any]:
    def f(v):
        try:
            return round(max(0.0, min(1.0, float(v))), 4)
        except (TypeError, ValueError):
            return 0.5
    return {"id": "pn" + secrets.token_hex(3), "nome": C._txt(nome, 80) or "ponto", "tipo": C._txt(tipo, 40),
            "descricao": C._txt(descricao, 500), "x": f(x), "y": f(y), "escala": escala if escala in ESCALAS else "",
            "lugar": None, "manual": manual}


def pino(p: Dict[str, Any], pnid: str) -> Dict[str, Any]:
    x = next((y for y in p["pinos"] if y["id"] == pnid), None)
    if not x:
        raise LugarErro("Pino não encontrado.")
    return x


def editar_pino(p: Dict[str, Any], pnid: str, dados: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if pnid == "novo":
        x = novo_pino(dados.get("nome"), dados.get("x"), dados.get("y"), dados.get("tipo"), dados.get("descricao"),
                      dados.get("escala") or "", True)
        p["pinos"].append(x)
        return x
    x = pino(p, pnid)
    if dados.get("apagar"):
        p["pinos"].remove(x)
        return None
    for k, n in (("nome", 80), ("tipo", 40), ("descricao", 500)):
        if k in dados:
            x[k] = C._txt(dados[k], n) or x[k]
    for k in ("x", "y"):
        if k in dados:
            try:
                x[k] = round(max(0.0, min(1.0, float(dados[k]))), 4)
            except (TypeError, ValueError):
                pass
    if dados.get("escala") in ESCALAS or dados.get("escala") == "":
        x["escala"] = dados["escala"]
    x["manual"] = True
    return x


def sub_lugar_do_pino(lid: str, pnid: str, base: str = _BASE) -> str:
    """📍 → 🗺: o pino vira um lugar DENTRO deste (ou abre o que já existe)."""
    with _TRAVA:
        p = carregar(lid, base)
        x = pino(p, pnid)
        if x.get("lugar"):
            try:
                carregar(x["lugar"], base)
                return x["lugar"]
            except LugarErro:
                x["lugar"] = None
        i = ORDEM_ESCALAS.index(p["escala"]) if p["escala"] in ORDEM_ESCALAS[:-1] else 4
        escala = x.get("escala") or ORDEM_ESCALAS[max(0, i - 1)]
        f = criar(x["nome"], escala, lid, base, descricao=x.get("descricao") or "")
        x["lugar"] = f["id"]
        log(p, f"📍 {x['nome']} virou um sub-lugar")
        salvar(p, base)
        return f["id"]


def escala_mapa(p: Dict[str, Any]) -> Tuple[float, str]:
    """(largura do mapa inteiro, unidade) — o padrão da escala ou o que você pôs."""
    padrao = ESCALAS[p["escala"]][2]
    m = p["mapa"]
    return (float(m.get("largura") or padrao[0]), str(m.get("unidade") or padrao[1]))


def distancia(p: Dict[str, Any], a: Tuple[float, float], b: Tuple[float, float], proporcao: float = 16 / 9) -> float:
    """📏 A distância entre dois pontos do mapa (x,y de 0 a 1; o mapa é `proporcao` largura/altura)."""
    larg, _u = escala_mapa(p)
    dx = (b[0] - a[0]) * larg
    dy = (b[1] - a[1]) * larg / proporcao
    return math.hypot(dx, dy)


# ------------------------------------------------------------------ 📷 fotos e 🗺 mapa no Flow
def _base_prompt(p: Dict[str, Any], base: str, ingles_pai: bool = True) -> List[str]:
    e, f = p["entrada"], p["ficha"]
    L = []
    desc = f.get("descricao_en") or e.get("descricao") or ""
    L.append(f"{'An ORIGINAL fictional place' if e.get('original') else 'The place'}"
             + (f" called {p['nome']}" if p["nome"] != "Lugar novo" else "") + f" — {ESCALAS[p['escala']][0].split(' ', 1)[1]}"
             + (f" ({e['escala_livre']})" if p["escala"] == "outro" and e.get("escala_livre") else "") + f": {desc}")
    if C.epoca_en(e):
        L.append(f"Era: {C.epoca_en(e)}.")
    if p.get("pai"):
        try:
            pai = carregar(p["pai"], base)
            if (pai.get("ficha") or {}).get("descricao_en"):
                L.append(f"It is inside {pai['nome']}: {pai['ficha']['descricao_en'][:400]}")
        except LugarErro:
            pass
    if e.get("evitar"):
        L.append(f"Avoid: {e['evitar']}.")
    return L


def prompt_foto(p: Dict[str, Any], vista: str, correcao: str = "", base: str = _BASE, com_refs: bool = True) -> str:
    vistas = {k: (r, en) for k, r, en in ESCALAS[p["escala"]][3]}
    en = vistas.get(vista, ("", vista))[1]
    L = []
    refs = mapa_refs(p) if com_refs else []
    if refs:
        L.append(f"The reference image is a collage of {len(p['entrada']['refs'])} NUMBERED panels. Use: "
                 + "; ".join(refs) + ". Everything else comes from the description below.")
    L += _base_prompt(p, base)
    L.append(f"SHOT: {en}. Wide 16:9 cinematic establishing image, no text, no captions, no watermark, no UI.")
    L.append(f"ART STYLE: {estilo_en(p)}.")
    if correcao:
        L.append(f"CHANGES FOR THIS ATTEMPT: {correcao}")
    return " ".join(" ".join(L).split())[:3900]


def prompt_mapa(p: Dict[str, Any], correcao: str = "", base: str = _BASE) -> str:
    f = p["ficha"]
    L = []
    refs = mapa_refs(p, so_mapa=True)
    if refs:
        L.append(f"The reference image is a collage of NUMBERED panels. Use: " + "; ".join(refs) + ".")
    L.append(f"{ESCALAS[p['escala']][1]}, seen from directly above, filling the whole 16:9 image.")
    L += _base_prompt(p, base)
    if f.get("mapa_en"):
        L.append(f"Layout: {f['mapa_en']}")
    pins = [x for x in p["pinos"]][:16]
    if pins:
        L.append("Important places to show (as small icons/markers WITHOUT labels): "
                 + "; ".join(f"{x['nome']} ({x.get('tipo') or 'place'}) at the {_rosa(x['x'], x['y'])}" for x in pins) + ".")
    L.append(f"Map rendering: {estilo_en(p)}, cartographic and readable. ABSOLUTELY NO TEXT, no letters, no labels, no "
             "names, no legend, no compass text (the app adds the labels).")
    if correcao:
        L.append(f"CHANGES FOR THIS ATTEMPT: {correcao}")
    return " ".join(" ".join(L).split())[:3900]


def _rosa(x: float, y: float) -> str:
    v = "north" if y < 0.34 else "south" if y > 0.66 else ""
    h = "west" if x < 0.34 else "east" if x > 0.66 else ""
    return (f"{v}-{h}" if v and h else v or h or "center") + f" (x {x:.2f}, y {y:.2f})"


def _mandar(itens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    import flow_lote
    lote = flow_lote.lote()
    try:
        novos = lote.adicionar(itens, proporcao="16:9", quantidade="x1")
    except ValueError as exc:
        raise LugarErro(str(exc))
    return novos


def _iniciar() -> str:
    try:
        import flow_lote
        flow_lote.lote().iniciar()
        return ""
    except Exception as exc:  # noqa: BLE001
        return f"o Flow em massa não ligou agora ({str(exc)[:160]}) — ▶ Continuar na aba Flow"


def gerar_fotos(lid: str, vistas: Optional[List[str]] = None, correcao: str = "", base: str = _BASE) -> Dict[str, Any]:
    with _TRAVA:
        p = carregar(lid, base)
        if not (p["ficha"].get("descricao_en") or p["entrada"].get("descricao") or p["entrada"]["refs"]):
            raise LugarErro("Descreva o lugar ou mande uma imagem de referência.")
        validas = [k for k, _r, _e in ESCALAS[p["escala"]][3]]
        vistas = [v for v in (vistas or validas) if v in validas] or validas[:1]
        ref = _colagem(p, base) if mapa_refs(p) else None
        itens = []
        for v in vistas:
            it = {"prompt": prompt_foto(p, v, C._txt(correcao, 800), base), "tipo": "imagem", "origem": "criador"}
            if ref:
                it["referencia_arquivo"] = ref
            itens.append(it)
        for v, it, j in zip(vistas, itens, _mandar(itens)):
            p["fotos"].append({"id": "f" + secrets.token_hex(3), "vista": v, "estado": "fila", "job": j["id"], "erro": None,
                               "msg": "⏳ na fila do Flow", "correcao": C._txt(correcao, 300), "criado": time.time()})
        log(p, f"📷 {len(vistas)} foto(s) pro Flow")
        salvar(p, base)
    return {"enviadas": len(vistas), "aviso": _iniciar()}


def gerar_mapa(lid: str, n: int = 2, correcao: str = "", base: str = _BASE) -> Dict[str, Any]:
    with _TRAVA:
        p = carregar(lid, base)
        if not (p["ficha"].get("descricao_en") or p["entrada"].get("descricao")):
            raise LugarErro("Descreva o lugar (ou monte a ficha) antes do mapa.")
        n = max(1, min(4, int(n or 1)))
        ref = _colagem(p, base) if mapa_refs(p, so_mapa=True) else None
        itens = []
        for _k in range(n):
            it = {"prompt": prompt_mapa(p, C._txt(correcao, 800), base), "tipo": "imagem", "origem": "criador"}
            if ref:
                it["referencia_arquivo"] = ref
            itens.append(it)
        for j in _mandar(itens):
            p["mapa"]["variacoes"].append({"id": "m" + secrets.token_hex(3), "estado": "fila", "job": j["id"], "erro": None,
                                           "msg": "⏳ na fila do Flow", "correcao": C._txt(correcao, 300), "criado": time.time()})
        log(p, f"🗺 {n} mapa(s) pro Flow")
        salvar(p, base)
    return {"enviadas": n, "aviso": _iniciar()}


def _guardar_img(p: Dict[str, Any], item: Dict[str, Any], img, base: str, pasta_nome: str) -> None:
    d = os.path.join(pasta(p["id"], base), pasta_nome)
    os.makedirs(d, exist_ok=True)
    im = img.convert("RGB")
    if max(im.size) > 2560:
        im.thumbnail((2560, 2560))
    arq = f"{item['id']}.jpg"
    im.save(os.path.join(d, arq), quality=92)
    item.update(estado="pronta", arquivo=arq, erro=None, msg=None, largura=im.width, altura=im.height)


def enviar_imagem(lid: str, img, tipo: str, base: str = _BASE, vista: str = "") -> Dict[str, Any]:
    """📤 Uma imagem sua como foto ou como o mapa (o mapa enviado já fica aprovado)."""
    with _TRAVA:
        p = carregar(lid, base)
        if tipo == "mapa":
            it = {"id": "m" + secrets.token_hex(3), "origem": "upload", "criado": time.time()}
            p["mapa"]["variacoes"].append(it)
            _guardar_img(p, it, img, base, "mapa")
            p["mapa"]["aprovado"] = it["id"]
        else:
            it = {"id": "f" + secrets.token_hex(3), "vista": vista or "minha", "origem": "upload", "criado": time.time()}
            p["fotos"].append(it)
            _guardar_img(p, it, img, base, "fotos")
        salvar(p, base)
        return it


def item(p: Dict[str, Any], iid: str) -> Tuple[str, Dict[str, Any]]:
    for x in p["fotos"]:
        if x["id"] == iid:
            return "fotos", x
    for x in p["mapa"]["variacoes"]:
        if x["id"] == iid:
            return "mapa", x
    raise LugarErro("Imagem não encontrada.")


def acao_imagem(lid: str, iid: str, acao: str, base: str = _BASE) -> None:
    with _TRAVA:
        p = carregar(lid, base)
        tipo, x = item(p, iid)
        if acao == "apagar":
            (p["fotos"] if tipo == "fotos" else p["mapa"]["variacoes"]).remove(x)
            if p["mapa"].get("aprovado") == iid:
                p["mapa"]["aprovado"] = None
        elif acao == "aprovar":
            if not x.get("arquivo"):
                raise LugarErro("Ainda sem imagem.")
            if tipo == "mapa":
                p["mapa"]["aprovado"] = iid
            else:
                x["aprovada"] = not x.get("aprovada")
        else:
            raise LugarErro("Ação desconhecida.")
        salvar(p, base)


def mapa_aprovado(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    a = p["mapa"].get("aprovado")
    return next((x for x in p["mapa"]["variacoes"] if x["id"] == a and x.get("arquivo")), None)


def acompanhar(lid: str, base: str = _BASE) -> bool:
    p = carregar(lid, base)
    pend = [x for x in p["fotos"] + p["mapa"]["variacoes"] if x.get("estado") in ESPERA and x.get("job")]
    if not pend:
        return False
    import flow_lote
    lote = flow_lote.lote()
    with lote.trava:
        fila = {j["id"]: dict(j) for j in lote.fila}
        rodando = lote.rodando
    mudou = False
    with _TRAVA:
        p = carregar(lid, base)
        for tipo, lista in (("fotos", p["fotos"]), ("mapa", p["mapa"]["variacoes"])):
            for x in lista:
                if x.get("estado") not in ESPERA or not x.get("job"):
                    continue
                fj = fila.get(x["job"])
                antes = (x.get("estado"), x.get("msg"))
                if fj is None:
                    x.update(estado="erro", erro="o pedido sumiu da fila do 🚀 Flow em massa — gere de novo")
                elif fj["estado"] == "ok":
                    ok = False
                    for r in fj.get("resultados") or []:
                        try:
                            import flow_estudio as FE
                            from PIL import Image
                            orig = os.path.join(FE.pasta_galeria(), r.get("arquivo") or "")
                            if r.get("tipo") == "imagem" and os.path.isfile(orig):
                                _guardar_img(p, x, Image.open(orig), base, tipo)
                                ok = True
                                break
                        except Exception as exc:  # noqa: BLE001
                            x.update(estado="erro", erro=f"a imagem chegou mas não deu pra guardar: {str(exc)[:160]}")
                    if ok and tipo == "mapa" and not mapa_aprovado(p):
                        p["mapa"]["aprovado"] = x["id"]  # o 1º mapa que chega já vale (dá pra trocar)
                    if not ok and x.get("estado") != "erro":
                        x.update(estado="erro", erro="o Flow terminou sem imagem")
                elif fj["estado"] == "erro":
                    x.update(estado="erro", erro=str(fj.get("erro") or "o Flow falhou")[:300])
                elif fj["estado"] in ("rodando", "convertendo"):
                    x.update(estado="gerando", msg=f"🎨 gerando no Flow (conta “{fj.get('conta')}”)")
                elif not rodando:
                    x.update(msg="⏸ o Flow em massa está parado — ▶ Continuar na aba Flow")
                else:
                    x.update(msg="⏳ na fila do Flow")
                mudou = mudou or antes != (x.get("estado"), x.get("msg"))
        if mudou:
            salvar(p, base)
    return mudou


# ------------------------------------------------------------------ ⬇ zip / texto / tela
def ficha_txt(p: Dict[str, Any], base: str = _BASE) -> str:
    f, e = p["ficha"], p["entrada"]
    L = [f"🗺 {p['nome']} — {escala_nome(p)}", " › ".join(x["nome"] for x in caminho(p, base)),
         f"Estilo: {C.estilo_nome({'entrada': e})}" + (f" · Época: {C.epoca_nome(e)}" if C.epoca_nome(e) else ""), ""]
    for k, rot in (("descricao_pt", "Como é"), ("historia", "História"), ("cultura", "Cultura"), ("clima", "Clima"),
                   ("economia", "Economia / recursos"), ("curiosidades", "Curiosidades"), ("segredos", "Segredos"),
                   ("descricao_en", "Descrição (inglês, pros prompts)")):
        if f.get(k):
            L += [f"{rot}:", f[k], ""]
    if f.get("linha_do_tempo"):
        L += ["Linha do tempo:"] + [f"- {x['quando']}: {x['evento']}" for x in f["linha_do_tempo"]] + [""]
    if f.get("pessoas"):
        L += ["Pessoas importantes:"] + [f"- {x['nome']} ({x['papel']}): {x['descricao']}" for x in f["pessoas"]] + [""]
    if p["pinos"]:
        L += ["Pontos do mapa:"] + [f"- {x['nome']} ({x.get('tipo') or 'ponto'}): {x.get('descricao') or ''}" for x in p["pinos"]] + [""]
    larg, u = escala_mapa(p)
    L.append(f"Escala do mapa: {larg:g} {u} de largura")
    return "\n".join(L).strip() + "\n"


def zip_lugar(lid: str, base: str = _BASE) -> bytes:
    p = carregar(lid, base)
    sl = C._slug(p["nome"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{sl}/ficha.txt", ficha_txt(p, base))
        larg, u = escala_mapa(p)
        z.writestr(f"{sl}/lugar.json", json.dumps({"nome": p["nome"], "escala": p["escala"], "dentro_de": caminho(p, base)[:-1],
                                                   "ficha": p["ficha"], "pinos": p["pinos"],
                                                   "escala_mapa": {"largura": larg, "unidade": u}}, ensure_ascii=False, indent=1))
        m = mapa_aprovado(p)
        if m:
            z.write(os.path.join(pasta(lid, base), "mapa", m["arquivo"]), f"{sl}/mapa.jpg")
            try:
                z.writestr(f"{sl}/mapa_com_pinos.png", mapa_com_pinos(p, base))
            except Exception:  # noqa: BLE001
                pass
        for x in p["fotos"]:
            if x.get("arquivo"):
                z.write(os.path.join(pasta(lid, base), "fotos", x["arquivo"]), f"{sl}/fotos/{x.get('vista') or 'foto'}_{x['id']}.jpg")
    return buf.getvalue()


def mapa_com_pinos(p: Dict[str, Any], base: str = _BASE) -> bytes:
    """O mapa aprovado com os 📍 pinos e os nomes desenhados (pra levar pra fora do site)."""
    from PIL import Image, ImageDraw, ImageFont
    m = mapa_aprovado(p)
    if not m:
        raise LugarErro("Sem mapa ainda.")
    im = Image.open(os.path.join(pasta(p["id"], base), "mapa", m["arquivo"])).convert("RGB")
    d = ImageDraw.Draw(im)
    tam = max(14, im.width // 70)
    try:
        fonte = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", tam)
    except Exception:  # noqa: BLE001
        fonte = ImageFont.load_default()
    for x in p["pinos"]:
        cx, cy = x["x"] * im.width, x["y"] * im.height
        r = tam * 0.45
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(220, 38, 38), outline=(255, 255, 255), width=max(2, tam // 8))
        tx, ty = cx + r * 1.4, cy - tam * 0.6
        d.text((tx, ty), x["nome"], fill=(255, 255, 255), font=fonte, stroke_width=max(2, tam // 6), stroke_fill=(0, 0, 0))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def para_tela(p: Dict[str, Any], base: str = _BASE) -> Dict[str, Any]:
    out = dict(p)
    out["caminho"] = caminho(p, base)
    out["filhos"] = [{"id": f["id"], "nome": f["nome"], "escala": ESCALAS[f["escala"]][0]} for f in filhos(p["id"], base)]
    out["personagens"] = personagens_daqui(p["id"], base)
    out["escala_nome"] = escala_nome(p)
    out["vistas"] = [{"chave": k, "rotulo": r} for k, r, _e in ESCALAS[p["escala"]][3]]
    larg, u = escala_mapa(p)
    out["escala_mapa"] = {"largura": larg, "unidade": u}
    m = mapa_aprovado(p)
    out["mapa_img"] = m["arquivo"] if m else None
    out["mapa_prop"] = (m["largura"] / m["altura"]) if m and m.get("largura") and m.get("altura") else 16 / 9
    out["ia"] = C.ia_ligada()
    out["mapa_refs"] = mapa_refs(p)
    return out
