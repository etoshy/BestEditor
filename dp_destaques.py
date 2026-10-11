"""
Destaques de texto do DarkPlanner (darkplanner.json -> "highlights", 207 estilos).

Cada estilo traz no JSON: papel (abertura, seção, destaque, ênfase, info,
apoio), subtipos (ano, data, número, %, dinheiro, nome, local, bíblia…),
forma (título central, frase, selo, cartão de dado, lower third, citação,
marca-texto, digitação…), zona da tela, tratamento da cena (escurecer,
vinheta, desfoque, gradiente, grade…), fonte, caixa alta/itálico, coreografia
de entrada/saída e ritmo. Aqui isso vira legenda ASS animada (libass, com as
fontes em assets/fonts/dp) + filtros de vídeo pro tratamento da cena.

Timing (regra de ouro do DarkPlanner): o destaque entra um pouco ANTES da
primeira palavra do texto dele, cobre a fala e respira até a próxima fala;
um destaque por vez, nunca sobrepostos.
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import dp_visual

_AQUI = os.path.dirname(os.path.abspath(__file__))
FONTES_DIR = os.path.join(_AQUI, "assets", "fonts", "dp")

_FONTE = {
    "anton": "DP Anton", "playfair": "DP Playfair Display", "cinzel": "DP Cinzel", "archivo": "DP Archivo",
    "montserrat": "DP Montserrat", "mono": "DP Jetbrains Mono", "poppins": "DP Poppins", "lora": "DP Lora",
    "oswald": "DP Oswald", "barlowcond": "DP Barlow Condensed", "specialelite": "DP Special Elite",
    "garamond": "DP Eb Garamond", "abril": "DP Abril Fatface", "bebas": "DP Bebas Neue", "rajdhani": "DP Rajdhani",
    "worksans": "DP Work Sans", "merriweather": "DP Merriweather", "fjalla": "DP Fjalla One", "staatliches": "DP Staatliches",
    "teko": "DP Teko", "robotocond": "DP Roboto Condensed", "alfaslab": "DP Alfa Slab One", "default": "DP Inter",
}
_CONDENSADAS = {"anton", "bebas", "oswald", "teko", "barlowcond", "fjalla", "staatliches", "robotocond", "rajdhani"}
_CSS_FONTE = {k: v for k, v in _FONTE.items()}


def catalogo() -> Dict[str, Dict[str, Any]]:
    return dp_visual.dp()["highlights"]


def estilo(eid: str) -> Optional[Dict[str, Any]]:
    return catalogo().get(eid)


def paleta_padrao() -> Dict[str, str]:
    return dict(dp_visual.dp()["colorSystem"]["paletaDefault"])


def _classe_tempo(h: Dict[str, Any]) -> Dict[str, float]:
    classes = dp_visual.dp()["rules"]["timing"]["classes"]
    return classes.get((h.get("coreografia") or {}).get("ritmo") or h.get("ritmo") or "medio", classes["medio"])


# ------------------------------------------------------------------ catálogo pro editor / IA
def catalogo_para_editor() -> List[Dict[str, Any]]:
    cats = {c["id"]: c["labelPt"] for c in dp_visual.dp()["guidance"]["categories"]}
    out = []
    for eid, h in catalogo().items():
        tip = h.get("tipografia") or {}
        out.append({
            "id": eid, "nome": h["label"], "categoria": cats.get(h.get("categoria"), h.get("categoria")),
            "papel": h.get("papel"), "subtipos": h.get("subtipos") or [], "forma": h.get("forma"), "zona": h.get("zona"),
            "fonte": _FONTE.get(tip.get("fonte") or "default", "DP Inter"), "caixa_alta": bool(tip.get("caixaAlta")),
            "italico": bool(tip.get("italico")), "amostra": h.get("amostra"), "palavras": h.get("palavras"),
            "quando": (h.get("whenToUse") or [""])[0], "evitar": (h.get("whenNotToUse") or [""])[0],
            "tratamento": (h.get("cena") or {}).get("tratamento"), "manual": bool(h.get("manualOnly")),
            "fundo": list(__import__("dp_fundos").do_estilo(h.get("cena") or {})),
            "campos": [{"id": c["id"], "rotulo": c.get("labelPt") or c.get("label"), "principal": bool(c.get("principal")),
                        "obrigatorio": bool(c.get("required"))} for c in (h.get("texto") or {}).get("campos", [])],
        })
    ordem = [c["labelPt"] for c in dp_visual.dp()["guidance"]["categories"]]
    out.sort(key=lambda e: (ordem.index(e["categoria"]) if e["categoria"] in ordem else 99, e["nome"]))
    return out


def bloco_para_prompt() -> str:
    linhas = []
    for eid, h in catalogo().items():
        if not h.get("autoEligible") or h.get("manualOnly"):
            continue
        sub = "/".join(h.get("subtipos") or [])
        p = h.get("palavras") or [1, 12]
        linhas.append(f"- {eid} | {h.get('papel')}{('(' + sub + ')') if sub else ''} | {p[0]}-{p[1]} palavras | {(h.get('whenToUse') or [''])[0][:80]}")
    return "\n".join(linhas)


# ------------------------------------------------------------------ timing
def _norm(p: str) -> str:
    return re.sub(r"[^\wà-ÿ]", "", (p or "").lower())


def ancorar(destaques: List[Dict[str, Any]], palavras: List[Dict[str, Any]], duracao: Optional[float] = None) -> List[Dict[str, Any]]:
    """Recalcula início/fim de cada destaque pela fala (pre-roll antes da 1ª
    palavra do texto dele, tail na pausa seguinte) e tira sobreposições."""
    ws = sorted([w for w in palavras or [] if str(w.get("word", "")).strip()], key=lambda w: float(w["start"]))
    out = []
    avulsos = [dict(d) for d in destaques if d.get("avulso")]  # texto avulso: tempo é o que a pessoa escolheu
    for d in sorted([d for d in destaques if not d.get("avulso")], key=lambda x: float(x["start"])):
        d = dict(d)
        h = estilo(d.get("estilo")) or {}
        cl = _classe_tempo(h)
        ini, fim = float(d["start"]), float(d["end"])
        janela = [w for w in ws if ini - 0.6 <= float(w["start"]) < fim + 0.3]
        if janela:
            alvo = [_norm(x) for x in (d.get("texto") or "").split()[:3] if _norm(x)]
            primeira = janela[0]
            if alvo:
                for k, w in enumerate(janela):
                    if _norm(w["word"]) == alvo[0] and all(k + j < len(janela) and _norm(janela[k + j]["word"]) == a for j, a in enumerate(alvo[1:], 1)):
                        primeira = w
                        break
            ultima = [w for w in janela if float(w["start"]) < fim][-1] if [w for w in janela if float(w["start"]) < fim] else janela[-1]
            fala_ini, fala_fim = float(primeira["start"]), max(float(ultima.get("end", ultima["start"])), float(primeira["start"]) + 0.3)
            prox = next((float(w["start"]) for w in ws if float(w["start"]) > fala_fim + 0.01), None)
            pre = min(cl.get("preRollMaxS", 0.3), 0.6)
            pos = min(1.0, 0.45 * (prox - fala_fim)) if prox is not None else min(1.0, cl.get("postRollMaxS", 0.26) * 2)
            ini, fim = max(0.0, fala_ini - pre), fala_fim + max(cl.get("postRollMaxS", 0.2), pos)
        fim = max(fim, ini + max(0.6, cl.get("minTotalS", 1.0)))
        if duracao:
            fim = min(fim, duracao)
            ini = min(ini, max(0.0, fim - 0.6))
        d["start"], d["end"] = round(ini, 3), round(fim, 3)
        if out and d["start"] < out[-1]["end"] + 0.1:  # um destaque por vez
            out[-1]["end"] = round(max(out[-1]["start"] + 0.6, d["start"] - 0.1), 3)
            if d["start"] < out[-1]["end"] + 0.1:
                d["start"] = round(out[-1]["end"] + 0.1, 3)
                if d["end"] - d["start"] < 0.6:
                    continue
        out.append(d)
    return sorted(out + avulsos, key=lambda x: float(x["start"]))


# ------------------------------------------------------------------ motor local (sugestões automáticas)
_RE_ANO = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
_RE_PCT = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:%|por cento|percent)", re.I)
_RE_DIN = re.compile(r"(?:R\$|US\$|\$|€|£)\s?\d[\d.,]*(?:\s(?:milhões|milhão|bilhões|bilhão|mil)\b)?|\b\d[\d.,]*\s?(?:milhões|milhão|bilhões|bilhão|mil)?\s?(?:de\s)?(?:reais|dólares|euros|libras)\b", re.I)
_RE_DATA = re.compile(r"\b\d{1,2}\s+de\s+(?:janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\b", re.I)
_RE_CONT = re.compile(r"\b(\d+|dois|duas|três|quatro|cinco|seis|sete|oito|nove|dez)\s+(?:motivos|razões|sinais|coisas|fatos|passos|maneiras|formas|erros|segredos|dicas|regras)\b", re.I)
_RE_BIB = re.compile(r"\b(?:[1-3]\s?)?[A-ZÁÉÍÓÚ][a-zà-ÿ]+\s\d{1,3}[:.,]\d{1,3}\b")
_RE_NUM = re.compile(r"\b\d[\d.,]{2,}\b|\b\d+(?:[.,]\d+)?\s(?:milhões|milhão|bilhões|bilhão|mil|thousand|million|billion)\b", re.I)
_IMPACTO = re.compile(r"\b(nunca|ninguém|jamais|segredo|verdade|mentira|tudo mudou|o maior|a maior|inacreditável|chocante|incrível|final|pior|melhor|primeira vez|última vez)\b", re.I)


def _subtipo_do_texto(t: str) -> Optional[Tuple[str, str]]:
    for nome, rx in (("biblia", _RE_BIB), ("pct", _RE_PCT), ("dinheiro", _RE_DIN), ("data", _RE_DATA), ("contagem", _RE_CONT), ("ano", _RE_ANO), ("numero", _RE_NUM)):
        m = rx.search(t or "")
        if m:
            return nome, m.group(0)
    return None


def sugerir(blocos: List[Dict[str, Any]], kit: Optional[List[str]] = None, densidade: str = "equilibrado",
            semente: Any = 1, palavras: Optional[List[Dict[str, Any]]] = None, duracao: Optional[float] = None) -> List[Dict[str, Any]]:
    """Motor local: lê os blocos de fala ({start, end, text}) e propõe
    destaques respeitando orçamento por papel, intervalos mínimos e o kit."""
    regras = dp_visual.dp()["rules"]["selection"]
    fator = regras["densityFactors"].get(densidade, 1.0)
    rng = random.Random(f"{semente}:destaques")
    cat = catalogo()
    permitidos = [e for e in (kit or list(cat)) if e in cat and cat[e].get("autoEligible") and not cat[e].get("manualOnly")]
    por_papel: Dict[str, List[str]] = {}
    for e in permitidos:
        por_papel.setdefault(cat[e]["papel"], []).append(e)
    total = duracao or (blocos[-1]["end"] if blocos else 0)
    teto = {p: max(1, math.ceil(min(v["teto"], (total / v["aCadaS"]) if v.get("aCadaS") else v["teto"]) * fator)) for p, v in regras["ratesPerRole"].items()}
    usados = {p: 0 for p in teto}
    ultimo_papel: Dict[str, float] = {}
    ultimo_estilo: List[str] = []
    out = []

    def escolher(papel: str, subtipo: Optional[str] = None) -> Optional[str]:
        cands = []
        for e in por_papel.get(papel, []):
            h = cat[e]
            subs = h.get("subtipos") or []
            if subtipo and subs and subtipo not in subs:
                continue
            if not subtipo and h.get("exclusivo"):
                continue
            if subtipo and h.get("subtiposProibidos") and subtipo in h["subtiposProibidos"]:
                continue
            if subtipo and not subs and papel == "info":
                continue
            peso = 1.0 * (0.2 if e in ultimo_estilo[-4:] else 1.0)
            cands.append((e, peso))
        if not cands:
            return None
        tot = sum(w for _e, w in cands)
        r = rng.uniform(0, tot)
        for e, w in cands:
            r -= w
            if r <= 0:
                return e
        return cands[-1][0]

    for k, b in enumerate(blocos):
        texto = str(b.get("text") or "").strip()
        if not texto:
            continue
        ini, fim = float(b["start"]), float(b["end"])
        papel, sub, trecho = None, None, None
        st = _subtipo_do_texto(texto)
        if k == 0 and por_papel.get("abertura") and not st:
            papel = "abertura"
        elif st:
            papel, (sub, trecho) = "info", st
        elif _IMPACTO.search(texto) or texto.endswith("!"):
            papel = "destaque"
        elif len(texto.split()) <= 6 and rng.random() < 0.35:
            papel = "enfase"
        if not papel:
            continue
        rate = regras["ratesPerRole"].get(papel, {})
        if usados.get(papel, 0) >= teto.get(papel, 1):
            continue
        if ini - ultimo_papel.get(papel, -1e9) < float(rate.get("gapMinS") or 0):
            continue
        if out and ini - out[-1]["end"] < regras.get("minGapAnyS", 1.2):
            continue
        e = escolher(papel, sub)
        if not e and papel == "info":
            continue
        if not e:
            continue
        h = cat[e]
        pmin, pmax = (h.get("palavras") or [1, 12])
        txt = trecho if trecho else " ".join(texto.split()[:pmax])
        out.append({"estilo": e, "start": ini, "end": fim, "texto": txt, "campos": {}, "origem": "auto"})
        usados[papel] = usados.get(papel, 0) + 1
        ultimo_papel[papel] = ini
        ultimo_estilo.append(e)
    return ancorar(out, palavras or [], duracao) if palavras else out


# ------------------------------------------------------------------ ASS
def _cor_ass(hex_cor: str, alpha: int = 0) -> str:
    h = (hex_cor or "#FFFFFF").lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}&".upper().replace("&H", "&H", 1)


def _tempo(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t - h * 3600 - m * 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc(t: str) -> str:
    return (t or "").replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


_TAMANHO = {
    "centro_titulo": 0.12, "centro_frase": 0.082, "palavra": 0.18, "marca": 0.085, "terco": 0.055, "selo_canto": 0.05,
    "cartao_dado": 0.11, "citacao": 0.07, "cascata": 0.085, "digitacao": 0.068, "sublinhado": 0.08, "slab": 0.1,
    "painel_meio": 0.08, "carimbo": 0.095, "doc": 0.06,
}
_POS = {  # zona -> (alinhamento ASS, x, y) em fração
    "centro": (5, 0.5, 0.5), "metade": (5, 0.5, 0.5), "full_bleed": (5, 0.5, 0.5), "terco_inf": (1, 0.06, 0.86),
    "terco_sup": (7, 0.06, 0.1), "canto_bl": (1, 0.05, 0.92), "canto_tl": (7, 0.05, 0.08), "canto_tr": (9, 0.95, 0.08),
    "canto_br": (3, 0.95, 0.92), "esq": (4, 0.07, 0.5), "dir": (6, 0.93, 0.5), "painel_esq": (4, 0.06, 0.5),
    "painel_dir": (6, 0.94, 0.5), "baixo": (2, 0.5, 0.88), "alto": (8, 0.5, 0.1), "inline": (2, 0.5, 0.86),
}


def _anim(entrada: str) -> str:
    e = entrada or "fade"
    if e in ANIMS_ENTRADA:  # já é o nome de uma família (o que o guia ensina a usar nos extras)
        return e
    regras = [
        # específicos do DarkPlanner que antes caíam no fade
        ("mira", r"doc_mira|doc_radar|doc_scanner|bracket_focus"), ("linha_tempo", r"doc_tempo|cartela_epoca"),
        ("versus", r"doc_vs|^split$"), ("matchcut", r"matchcut"), ("grade", r"v2_grade|v2_blueprint"), ("pino", r"pino_mapa"),
        ("assenta", r"assenta|gancho|v2_ano|v2_pergunta|value_callout|doc_termo"),
        ("type", r"type|digit|maquina|tipagem|v2_caneta"), ("contador", r"contador|odometro|contagem|numero_monumental|doc_numero|pct|valor_callout|count_label"),
        ("glitch", r"glitch"), ("cruzado", r"cruzado|split_hierarchy"), ("cortina", r"cortina|moldura_reveal|corte_persiana|corte_iris"),
        ("letras", r"letras|onda|tracking_reveal|type_assemble"), ("flip", r"flip|3d"), ("stamp", r"stamp|carimbo|selo_data|selo_capitulo|selo_artigo|date_stamp|chapter_stamp|article_stamp|recorte"),
        ("cascata", r"cascata|palavras|escada|word_cascade|pilha"), ("marca", r"marca|marker|gradient_marker|brilho_palavra|inline_focus"),
        ("sublinha", r"underline|sublinh"), ("terco", r"lower|hera_varre|hera_desliza|faixa|local|rotulo|tag|nome|location|cracha"),
        ("punch", r"punch|soco|impacto|condensed|batida|corte_zoom|corte_flash|corte_preto|corte_lamina|corte_luz|corte_split|monumento|proclama"),
        ("pop", r"pop|elastic|elastico|bounce|scale|sfx_misto"), ("tracking", r"tracking"), ("revelar", r"revelar|mask|wipe|slide_mask|meia_tela|corte"),
        ("slide", r"slide|swipe|desliza|elevador|sobem|descem"), ("blur", r"blur|foco|sussurro|whisper|suave|flutua|letras_blur|biblia|citacao|quote|pull"),
        ("acende", r"acende|shine|brilho|glow"),
    ]
    for nome, rx in regras:
        if re.search(rx, e):
            return nome
    return "fade"


# famílias de animação que a IA / a pessoa podem escolher por destaque (sobrepõe a do estilo)
ANIMS_ENTRADA = {
    "fade": "Fade", "pop": "Pop (estoura)", "punch": "Soco (vem grande)", "blur": "Desfoque → nítido", "slide": "Desliza",
    "letras": "Letra por letra", "type": "Máquina de escrever", "cascata": "Palavra por palavra", "glitch": "Glitch",
    "flip": "Gira 3D", "tracking": "Letras se juntam", "revelar": "Revela (cortina lateral)", "cortina": "Abre do centro",
    "stamp": "Carimbo", "acende": "Acende (pisca)", "marca": "Marca-texto", "cruzado": "Linhas cruzadas",
    "mira": "Mira (cantoneiras)", "linha_tempo": "Linha do tempo", "versus": "A × B", "matchcut": "Corte seco com clarão",
    "grade": "Grade técnica", "pino": "Pino de mapa", "assenta": "Assenta", "contador": "Número contando",
}
ANIMS_SAIDA = {"fade": "Fade", "blur": "Desfoca", "zoom": "Zoom", "slide": "Desliza", "wipe": "Cortina", "riscar": "Risca"}


def _tag_palavra(anim: str, t0: int, acento: str) -> str:
    """Entrada de cada palavra nos estilos "palavra por batida" — com o sabor do estilo."""
    t1 = t0 + 180
    return {
        "blur": f"\\alpha&HFF&\\blur10\\t({t0},{t1 + 40},\\alpha&H00&\\blur0)",
        "pop": f"\\alpha&HFF&\\fscx40\\fscy40\\t({t0},{t1},\\alpha&H00&\\fscx100\\fscy100)",
        "punch": f"\\alpha&HFF&\\fscx170\\fscy170\\t({t0},{t0 + 150},\\alpha&H00&\\fscx100\\fscy100)",
        "cruzado": f"\\alpha&HFF&\\fscx160\\fscy160\\t({t0},{t0 + 150},\\alpha&H00&\\fscx100\\fscy100)",
        "flip": f"\\alpha&HFF&\\frx90\\t({t0},{t1 + 40},\\alpha&H00&\\frx0)",
        "letras": f"\\alpha&HFF&\\blur12\\fscy140\\t({t0},{t1 + 40},\\alpha&H00&\\blur0\\fscy100)",
        "acende": f"\\alpha&HFF&\\t({t0},{t0 + 60},\\alpha&H00&)\\t({t0 + 60},{t0 + 110},\\alpha&HA0&)\\t({t0 + 110},{t0 + 170},\\alpha&H00&)",
        "marca": f"\\alpha&HFF&\\fscx80\\fscy80\\t({t0},{t0 + 140},\\alpha&H00&\\fscx100\\fscy100)",
        "cortina": f"\\alpha&HFF&\\fscx20\\t({t0},{t1},\\alpha&H00&\\fscx100)",
        "revelar": f"\\alpha&HFF&\\fscx20\\t({t0},{t1},\\alpha&H00&\\fscx100)",
        "slide": f"\\alpha&HFF&\\fax0.3\\t({t0},{t1},\\alpha&H00&\\fax0)",
    }.get(anim, f"\\alpha&HFF&\\fscy60\\t({t0},{t0 + 160},\\alpha&H00&\\fscy100)")


def dp_cores_tom_claro(c: str) -> str:
    import dp_cores
    return dp_cores.tons_da_paleta(c)["claro"]


def _quebrar(texto: str, chars: int) -> List[str]:
    palavras = texto.split()
    linhas, atual = [], ""
    for p in palavras:
        if atual and len(atual) + 1 + len(p) > chars:
            linhas.append(atual)
            atual = p
        else:
            atual = (atual + " " + p).strip()
    if atual:
        linhas.append(atual)
    return linhas or [""]


# ------------------------------------------------------------------ medidas do texto IGUAIS às da telinha do Estúdio
# A telinha (estudio.html, desenharUmHl/manterNaTela) é a referência: o vídeo
# exportado tem que sair com a mesma letra, o mesmo tamanho, a mesma quebra de
# linha e no mesmo lugar. Antes o export:
#   - usava \fs do libass como se fosse o font-size do navegador — o libass mede a
#     letra pela altura da "célula" (ascendente+descendente), então ela saía
#     ~30% menor (Playfair) e até ~43% menor (Anton/Poppins);
#   - quebrava a linha numa estimativa por nº de letras a 86% da largura, mas a
#     telinha quebra pela largura real das letras no espaço que sobra à direita da
#     âncora (no centro = 50% da tela): "Built on purpose" saía em 1 linha no vídeo
#     e em 2 na telinha;
#   - punha um contorno preto grosso que a telinha não tem (lá é uma sombra suave).
HL_POS_PREVIA = {  # zona -> (x %, y %, alinhamento) — o mesmo HL_POS do estudio.html
    "centro": (50, 50, "c"), "metade": (50, 50, "c"), "full_bleed": (50, 50, "c"), "terco_inf": (6, 84, "l"),
    "terco_sup": (6, 12, "l"), "canto_bl": (5, 90, "l"), "canto_tl": (5, 9, "l"), "canto_tr": (95, 9, "r"),
    "canto_br": (95, 90, "r"), "esq": (7, 50, "l"), "dir": (93, 50, "r"), "painel_esq": (6, 50, "l"),
    "painel_dir": (94, 50, "r"), "baixo": (50, 88, "c"), "alto": (50, 10, "c"), "inline": (50, 86, "c"),
}
LARGURA_MAX_PREVIA = 0.86   # max-width:86% do .hlt
ALTURA_LINHA_PREVIA = 1.1   # line-height:1.1 do .hlt
_FORMAS_CAIXA = ("selo_canto", "cartao_dado", "slab", "marca")


def fontes_json() -> Dict[str, Dict[str, Any]]:
    """assets/fonts/dp/fontes.json + as fontes dos extras (seção "fontes")."""
    try:
        with open(os.path.join(FONTES_DIR, "fontes.json"), encoding="utf-8") as f:
            mapa = json.load(f)
    except (OSError, ValueError):
        mapa = {}
    try:
        import dp_extras
        for k, v in (dp_extras.carregar().get("fontes") or {}).items():
            if k not in mapa and isinstance(v.get("arquivos"), dict) and str(v.get("familia") or "").startswith("DP "):
                mapa[k] = {"familia": v["familia"], "arquivos": dict(v["arquivos"])}
    except Exception:  # noqa: BLE001
        pass
    return mapa


def _mapa_arquivos_fontes() -> Dict[str, Dict[str, str]]:
    try:
        return {v["familia"]: v["arquivos"] for v in fontes_json().values()}
    except (KeyError, TypeError):
        return {}


def arquivo_da_fonte(familia: str, negrito: bool = True, italico: bool = False) -> str:
    """Caminho do .ttf que o navegador e o libass usam pra essa família."""
    arqs = _mapa_arquivos_fontes().get(familia) or _mapa_arquivos_fontes().get("DP Inter") or {}
    ordem = (["Italic"] if italico else []) + (["Bold", "Regular"] if negrito else ["Regular", "Bold"])
    for k in ordem + list(arqs.keys()):
        if arqs.get(k):
            return os.path.join(FONTES_DIR, arqs[k])
    return os.path.join(FONTES_DIR, "inter-Bold.ttf")


def _escala_pelas_metricas(caminho: str) -> Optional[float]:
    """unitsPerEm / (usWinAscent + usWinDescent) lido direto do .ttf (sem fontTools)."""
    import struct
    try:
        with open(caminho, "rb") as f:
            dados = f.read()
        n = struct.unpack(">H", dados[4:6])[0]
        tabelas = {}
        for k in range(n):
            tag, _cs, off, _ln = struct.unpack(">4sIII", dados[12 + 16 * k: 28 + 16 * k])
            tabelas[tag] = off
        upm = struct.unpack(">H", dados[tabelas[b"head"] + 18: tabelas[b"head"] + 20])[0]
        o2 = tabelas[b"OS/2"]
        asc, desc = struct.unpack(">HH", dados[o2 + 74: o2 + 78])
        return upm / float(asc + desc) if asc + desc > 0 else None
    except Exception:  # noqa: BLE001
        return None


_ESCALA_LIBASS: Dict[str, float] = {}


def escala_libass(familia: str) -> float:
    """Quanto 1px de \\fs do libass vale em font-size do navegador (em px).
    Medido uma vez por família renderizando com o próprio libass; se o ffmpeg
    falhar, vem das métricas do .ttf (usWin*), que é o que o libass usa."""
    if familia in _ESCALA_LIBASS:
        return _ESCALA_LIBASS[familia]
    valor = None
    try:
        import tempfile
        from PIL import Image, ImageFont
        from video_assembler import _escape_path_for_ffmpeg_filter
        amostra = "MMMMMMMMMM"
        with tempfile.TemporaryDirectory() as tmp:
            ass = os.path.join(tmp, "c.ass")
            with open(ass, "w", encoding="utf-8") as f:
                f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: 2000\nPlayResY: 400\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                        f"Style: A,{familia},100,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                        f"Dialogue: 0,0:00:00.00,0:00:01.00,A,,0,0,0,,{{\\pos(10,10)}}{amostra}\n")
            png = os.path.join(tmp, "c.png")
            vf = f"ass='{_escape_path_for_ffmpeg_filter(ass)}':fontsdir='{_escape_path_for_ffmpeg_filter(FONTES_DIR)}'"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=2000x400:d=0.1", "-vf", vf, "-frames:v", "1", png],
                           check=True, timeout=60, capture_output=True)
            bb = Image.open(png).convert("L").point(lambda v: 255 if v > 60 else 0).getbbox()
        f100 = ImageFont.truetype(arquivo_da_fonte(familia), 100)
        bp = f100.getbbox(amostra)
        if bb and bp and bp[2] > bp[0]:
            valor = (bb[2] - bb[0]) / float(bp[2] - bp[0])
    except Exception:  # noqa: BLE001
        valor = None
    if not valor or not (0.3 < valor < 1.6):
        valor = _escala_pelas_metricas(arquivo_da_fonte(familia)) or 0.83
    _ESCALA_LIBASS[familia] = valor
    return valor


def fs_libass(familia: str, px_navegador: float) -> int:
    """\\fs que desenha a letra do MESMO tamanho que font-size:<px> no navegador."""
    return max(1, int(round(px_navegador / max(0.3, escala_libass(familia)))))


_FONTES_PIL: Dict[Tuple[str, int, bool], Any] = {}


def largura_no_navegador(texto: str, familia: str, px: float, italico: bool = False) -> float:
    """Largura (px) do texto com font-size px — o PIL usa o mesmo .ttf e a mesma
    medida (em) do navegador."""
    from PIL import ImageFont
    chave = (familia, max(4, int(round(px))), bool(italico))
    if chave not in _FONTES_PIL:
        try:
            _FONTES_PIL[chave] = ImageFont.truetype(arquivo_da_fonte(familia, True, italico), chave[1])
        except OSError:
            _FONTES_PIL[chave] = None
    f = _FONTES_PIL[chave]
    if f is None:
        return len(texto) * px * 0.56
    return float(f.getlength(texto)) * (px / chave[1])


def _quebrar_por_largura(texto: str, limite: float, familia: str, px: float, italico: bool) -> List[str]:
    """Quebra gulosa pela largura real (como o navegador faz no white-space:pre-wrap)."""
    linhas: List[str] = []
    for paragrafo in texto.split("\n"):
        atual = ""
        for p in paragrafo.split():
            teste = (atual + " " + p) if atual else p
            if atual and largura_no_navegador(teste, familia, px, italico) > limite:
                linhas.append(atual)
                atual = p
            else:
                atual = teste
        linhas.append(atual)
    return [l for l in linhas if l] or [""]


def medidas_texto(d: Dict[str, Any], W: int, H: int) -> Dict[str, Any]:
    """Fonte, tamanho, quebra de linha e posição do texto de um destaque —
    calculados com as MESMAS regras da telinha do Estúdio (desenharUmHl +
    manterNaTela). Usado pela montagem (ASS) e pelo diagnóstico pós-export."""
    h = estilo(d.get("estilo")) or {}
    tip = h.get("tipografia") or {}
    forma = h.get("forma") or "centro_frase"
    zona_d = d.get("zona")
    zona = zona_d or h.get("zona") or "centro"
    fonte_key = d.get("fonte") if d.get("fonte") in _FONTE else (tip.get("fonte") or "default")
    fonte = _FONTE.get(fonte_key, "DP Inter")
    caixa = bool(d["maiusculas"]) if isinstance(d.get("maiusculas"), bool) else bool(tip.get("caixaAlta"))
    ital = bool(d["italico"]) if isinstance(d.get("italico"), bool) else bool(tip.get("italico"))
    campos = d.get("campos") or {}
    principal = next((c["id"] for c in (h.get("texto") or {}).get("campos", []) if c.get("principal")), "text")
    texto = (campos.get(principal) or d.get("texto") or h.get("amostra") or "").strip()
    if caixa:
        texto = texto.upper()
    try:
        escala = max(0.3, min(3.0, float(d.get("escala") or 1.0)))
    except (TypeError, ValueError):
        escala = 1.0
    x_pct, y_pct, al = HL_POS_PREVIA.get(zona, HL_POS_PREVIA["centro"])
    if forma in ("terco", "doc") and zona == "centro" and not zona_d:
        x_pct, y_pct, al = 6, 84, "l"
    tam = _TAMANHO.get(forma, 0.075) * H * (0.7 if len(texto) > 40 else 1.0) * escala
    # padding/borda do .hlt (em "em"): caixa .1em .35em; terço/doc .15em .4em + borda .18em; carimbo .05em .3em + borda .08em
    if forma in _FORMAS_CAIXA:
        pad_h, pad_v = 0.35 + 0.35, 0.1 + 0.1
        pad_esq, pad_dir, pad_cima = 0.35, 0.35, 0.1
    elif forma in ("terco", "doc"):
        pad_h, pad_v = 0.18 + 0.4 + 0.4, 0.15 + 0.15
        pad_esq, pad_dir, pad_cima = 0.18 + 0.4, 0.4, 0.15
    elif forma == "carimbo":
        pad_h, pad_v = 2 * (0.08 + 0.3), 2 * (0.08 + 0.05)
        pad_esq, pad_dir, pad_cima = 0.38, 0.38, 0.13
    else:
        pad_h = pad_v = pad_esq = pad_dir = pad_cima = 0.0
    # espaço que o navegador dá pro texto: o que sobra até a borda a partir da âncora
    # (left:x% => 100-x%; nos alinhados à direita, right:(100-x)% => x%), no máximo 86%
    disponivel = (x_pct if al == "r" else 100.0 - x_pct) / 100.0 * W

    def _layout(px: float):
        limite = max(1.0, min(LARGURA_MAX_PREVIA * W, disponivel - pad_h * px))
        ls = _quebrar_por_largura(texto, limite, fonte, px, ital)
        larg = [largura_no_navegador(l, fonte, px, ital) for l in ls]
        return limite, ls, larg

    limite, linhas, larguras = _layout(tam)
    # manterNaTela: margem de 4% da altura; se não couber, diminui (até 35%)
    m = H * 0.04
    caixa_w = (max(larguras) if len(linhas) == 1 else limite) + pad_h * tam
    caixa_h = len(linhas) * ALTURA_LINHA_PREVIA * tam + pad_v * tam
    encolheu = 1.0
    if caixa_h > H - 2 * m or caixa_w > W - 2 * m:
        encolheu = max(0.35, min((H - 2 * m) / caixa_h, (W - 2 * m) / caixa_w))
        tam *= encolheu
        limite, linhas, larguras = _layout(tam)
        caixa_w = (max(larguras) if len(linhas) == 1 else limite) + pad_h * tam
        caixa_h = len(linhas) * ALTURA_LINHA_PREVIA * tam + pad_v * tam
    ax, ay = x_pct / 100.0 * W, y_pct / 100.0 * H
    # canto da caixa (como o navegador posiciona: translate -50%/-100% conforme a âncora)
    bx = ax - (caixa_w / 2 if al == "c" else caixa_w if al == "r" else 0)
    vert = "top" if y_pct < 30 else "bottom" if y_pct > 70 else "middle"
    by = ay - (0 if vert == "top" else caixa_h if vert == "bottom" else caixa_h / 2)
    dx = dy = 0.0
    if by < m:
        dy = m - by
    elif by + caixa_h > H - m:
        dy = H - m - (by + caixa_h)
    if bx < m:
        dx = m - bx
    elif bx + caixa_w > W - m:
        dx = W - m - (bx + caixa_w)
    # âncora do TEXTO no ASS (sem o padding da caixa)
    tx = ax + dx + (pad_esq * tam if al == "l" else -pad_dir * tam if al == "r" else 0)
    ty = ay + dy + (pad_cima * tam if vert == "top" else -pad_cima * tam if vert == "bottom" else 0)
    an = {"top": 7, "middle": 4, "bottom": 1}[vert] + {"l": 0, "c": 1, "r": 2}[al]
    return {
        "texto": texto, "fonte": fonte, "fonte_key": fonte_key, "arquivo_fonte": arquivo_da_fonte(fonte, True, ital),
        "italico": ital, "caixa_alta": caixa, "forma": forma, "zona": zona,
        "tam_px": tam, "fs_ass": fs_libass(fonte, tam), "linhas": linhas, "larguras": larguras,
        "largura_txt": max(larguras) if larguras else 0.0, "altura_txt": len(linhas) * ALTURA_LINHA_PREVIA * tam,
        "limite_quebra": limite, "encolheu": encolheu, "deslocou": (dx, dy),
        "an": an, "x": int(round(tx)), "y": int(round(ty)), "ancora": (x_pct, y_pct, al),
        "sombra": max(1, int(round(H * 0.005))), "sombra_blur": max(1, int(round(H * 0.004))),  # desfoque maior pesa muito no libass (cada quadro)
    }


def _eventos_de_um(d: Dict[str, Any], W: int, H: int, paleta: Dict[str, str], palavras: List[Dict[str, Any]]) -> List[str]:
    h = estilo(d["estilo"]) or {}
    cor = h.get("coreografia") or {}
    med = medidas_texto(d, W, H)
    forma = med["forma"]
    fonte, ital = med["fonte"], med["italico"]
    texto = med["texto"]
    campos = d.get("campos") or {}
    bz = 0 if (d.get("_texto_escuro") or forma in _FORMAS_CAIXA or forma in ("cartao_dado", "slab", "selo_canto")) else med["sombra_blur"]  # sombra suave volta depois das animações com blur
    ini, fim = float(d["start"]), float(d["end"])
    dur_ms = int((fim - ini) * 1000)
    cl = _classe_tempo(h)
    I = int(max(220, cl.get("introS", 0.28) * 1600))
    O = int(max(150, cl.get("outroS", 0.2) * 1300))
    acento = _cor_ass(paleta.get("primaria", "#FFD60A"))
    import dp_cores
    _r, _g, _b = dp_cores.rgb(paleta.get("primaria", "#FFD60A"))
    sobre_acento = "&H00101010&" if (0.299 * _r + 0.587 * _g + 0.114 * _b) > 140 else "&H00FFFFFF&"
    acento2 = _cor_ass(paleta.get("secundaria", "#FF9A1F"))
    branco, preto = "&H00FFFFFF&", "&H00101010&"
    if d.get("_texto_escuro"):  # fundo claro (papel, cor clara): texto escuro
        branco, preto = preto, branco

    # tamanho/quebra/posição = os da telinha (medidas_texto). `tam` = font-size do
    # navegador (px), usado nas caixas/decorações; o \fs do libass é corrigido pra
    # desenhar a letra desse mesmo tamanho.
    tam = max(1, int(round(med["tam_px"])))
    linhas = med["linhas"]
    an, x, y = med["an"], med["x"], med["y"]
    largura_txt = med["largura_txt"]
    altura_txt = med["altura_txt"]

    if d.get("_texto_escuro"):
        sombra_txt = "\\bord0\\shad0"
    else:  # a telinha usa text-shadow:0 2px 6px rgba(0,0,0,.6) — sombra suave, sem contorno
        sombra_txt = f"\\bord1\\3a&HFF&\\shad{med['sombra']}\\4c&H000000&\\4a&H66&\\blur{med['sombra_blur']}"
    base = f"\\an{an}\\pos({x},{y})\\fn{fonte}\\fs{med['fs_ass']}\\b1\\i{1 if ital else 0}{sombra_txt}\\3c&H000000&\\1c{branco}"
    anim = d["anim_entrada"] if d.get("anim_entrada") in ANIMS_ENTRADA else _anim(cor.get("entrada"))
    saida = d["anim_saida"] if d.get("anim_saida") in ANIMS_SAIDA else (cor.get("saida") or "fade")
    # ênfase: palavras do texto pintadas com a cor de acento (a IA ou a pessoa escolhe)
    _enf = {_norm(w) for e in (d.get("enfase") or []) for w in str(e).split() if _norm(w)}

    def _pinta(palavra: str, txt_esc: str) -> str:
        if not (_enf and _norm(palavra) in _enf):
            return txt_esc
        m_ = re.findall(r"\\1c(&H[0-9A-Fa-f]+&)", base)
        cor_txt = m_[-1] if m_ else branco
        if forma in _FORMAS_CAIXA or (cor_txt == sobre_acento and cor_txt != branco):
            # texto já está sobre a caixa na cor de acento: pintar sumiria (caixa escura + texto branco também) — sublinha
            return f"{{\\u1}}{txt_esc}{{\\u0}}"
        return f"{{\\1c{acento}}}{txt_esc}{{\\1c{cor_txt}}}"

    def _corpo() -> str:
        return "\\N".join(" ".join(_pinta(p, _esc(p)) for p in l.split(" ")) for l in linhas)
    fad = f"\\fad({I // 2 if anim not in ('fade', 'blur') else I},{O})"
    saida_tag = f"\\t({max(0, dur_ms - O)},{dur_ms},\\blur16)" if saida == "blur" else (f"\\t({max(0, dur_ms - O)},{dur_ms},\\fscx130\\fscy130)" if saida == "zoom" else "")
    evs: List[str] = []

    interna = d["interna"] if d.get("interna") in ("brilho", "flutua") else (None if d.get("interna") == "nenhuma" else cor.get("interna"))

    def ev(camada: int, tags: str, txt: str, t0: float = ini, t1: float = fim, estilo_ass: str = "Txt") -> None:
        if camada == 2 and abs(t1 - fim) < 1e-6:
            tags = _com_saida(tags, t0)
        evs.append(f"Dialogue: {camada},{_tempo(t0)},{_tempo(t1)},{estilo_ass},,0,0,0,,{{{tags}}}{txt}")

    def _com_saida(tags: str, t0: float) -> str:
        """Saídas slide / wipe (riscar é um evento à parte) + interna "flutua"."""
        d_ms = int((fim - t0) * 1000)
        a_out = max(0, d_ms - O)
        if saida == "slide" and "\\pos(" in tags and "\\move(" not in tags:
            m = re.search(r"\\pos\((-?\d+),(-?\d+)\)", tags)
            if m:
                px_, py_ = int(m.group(1)), int(m.group(2))
                tags = tags.replace(m.group(0), f"\\move({px_},{py_},{px_ - int(W * 0.08)},{py_},{a_out},{d_ms})")
        elif saida == "wipe":
            bx, by, bw, bh = caixa_do_texto(0.6)
            fim_clip = f"\\t({a_out},{d_ms},\\clip({int(bx + bw)},{int(by)},{int(bx + bw)},{int(by + bh)}))"
            if "\\clip(" not in tags:
                tags += f"\\clip({int(bx)},{int(by)},{int(bx + bw)},{int(by + bh)})"
            tags += fim_clip
        if interna == "flutua" and "\\frz" not in tags:
            passo = 900
            k, osc = I, []
            while k + passo < a_out:
                osc.append(f"\\t({k},{k + passo},\\frz{0.7 if (k // passo) % 2 == 0 else -0.7})")
                k += passo
            tags += f"\\org({x},{y + H})" + "".join(osc)
        return tags

    corpo = "\\N".join(_esc(l) for l in linhas)

    # caixas / decoração (forma)
    def retangulo(x0, y0, w, hh, cor_r, alpha=0, tags_extra=""):
        return f"\\an7\\pos({int(x0)},{int(y0)})\\bord0\\shad0\\1c{cor_r}\\alpha&H{alpha:02X}&\\p1{tags_extra}", f"m 0 0 l {int(w)} 0 {int(w)} {int(hh)} 0 {int(hh)}"

    def caixa_do_texto(pad=0.35):
        bx, by = x, y
        if an in (5, 2, 8):
            bx -= largura_txt / 2
        elif an in (6, 3, 9):
            bx -= largura_txt
        if an in (5, 4, 6):
            by -= altura_txt / 2
        elif an in (1, 2, 3):
            by -= altura_txt
        p = tam * pad
        return bx - p, by - p * 0.6, largura_txt + 2 * p, altura_txt + 1.2 * p

    if forma in ("selo_canto", "cartao_dado", "slab", "doc"):
        bx, by, bw, bh = caixa_do_texto()
        tg, dr = retangulo(bx, by, bw, bh, acento if forma != "doc" else "&H00151515&", 0 if forma != "doc" else 0x30,
                           f"\\fad({I // 2},{O})\\clip({int(bx)},{int(by)},{int(bx)},{int(by + bh)})\\t(0,{I},\\clip({int(bx)},{int(by)},{int(bx + bw)},{int(by + bh)}))")
        ev(0, tg, dr)
        if forma != "doc":
            base = base.replace(f"\\1c{branco}", f"\\1c{sobre_acento}").replace("\\3c&H000000&", f"\\3c{acento}") + "\\bord0\\shad0\\blur0"
        else:
            bx2 = bx
            tg2, dr2 = retangulo(bx2, by, max(4, tam * 0.12), bh, acento, 0, f"\\fad({I // 2},{O})")
            ev(1, tg2, dr2)
    elif forma == "terco":
        bx, by, bw, bh = caixa_do_texto(0.45)
        tg, dr = retangulo(bx, by, bw, bh, "&H00101010&", 0x40, f"\\fad({I // 2},{O})\\clip({int(bx)},{int(by)},{int(bx)},{int(by + bh)})\\t(0,{I},\\clip({int(bx)},{int(by)},{int(bx + bw)},{int(by + bh)}))")
        ev(0, tg, dr)
        tg2, dr2 = retangulo(bx, by, max(4, tam * 0.14), bh, acento, 0, f"\\fad({I // 3},{O})")
        ev(1, tg2, dr2)
    elif forma in ("marca", "sublinhado"):
        bx, by, bw, bh = caixa_do_texto(0.2)
        if forma == "sublinhado":
            by, bh = by + bh - tam * 0.12, tam * 0.12
        tg, dr = retangulo(bx, by, bw, bh, acento, 0x20 if forma == "marca" else 0,
                           f"\\fad(80,{O})\\clip({int(bx)},{int(by)},{int(bx)},{int(by + bh)})\\t({I // 3},{I + I // 2},\\clip({int(bx)},{int(by)},{int(bx + bw)},{int(by + bh)}))")
        ev(0, tg, dr)
        if forma == "marca":
            base = base.replace(f"\\1c{branco}", f"\\1c{sobre_acento}") + "\\bord0\\shad0\\blur0"
    elif forma == "carimbo":
        bx, by, bw, bh = caixa_do_texto(0.4)
        b = max(3, tam // 12)
        tg = f"\\an7\\pos({int(bx)},{int(by)})\\bord0\\shad0\\1c{acento}\\p1\\frz-6\\org({x},{y})\\fscx250\\fscy250\\t(0,{int(I * 0.6)},\\fscx100\\fscy100)\\fad(60,{O})"
        dr = f"m 0 0 l {int(bw)} 0 {int(bw)} {int(bh)} 0 {int(bh)} l 0 0 m {b} {b} l {b} {int(bh) - b} {int(bw) - b} {int(bh) - b} {int(bw) - b} {b}"
        ev(0, tg, dr)
        base += f"\\1c{acento}\\frz-6"
    elif forma == "citacao":
        q = int(tam * 3.6)
        qa, qx, qy = (7, x - largura_txt / 2 - q * 0.2, y - altura_txt / 2 - q * 0.55) if an == 5 else (7, x, y - altura_txt - q * 0.6)
        ev(1, f"\\an{qa}\\pos({int(qx)},{int(qy)})\\fn{_FONTE['playfair']}\\fs{q}\\b1\\bord0\\shad0\\1c{acento}\\fad({I},{O})", "“")

    corpo = _corpo()
    _m_cor = re.findall(r"\\1c(&H[0-9A-Fa-f]+&)", base)
    _cor_txt = _m_cor[-1] if _m_cor else branco

    def _enf_chars(l: str) -> List[bool]:
        """Pra cada letra da linha: está numa palavra em ênfase?"""
        out_, pos = [False] * len(l), 0
        for w_ in l.split(" "):
            if _enf and _norm(w_) in _enf:
                for j in range(pos, pos + len(w_)):
                    out_[j] = True
            pos += len(w_) + 1
        return out_

    def _cor_ch(flag: bool) -> str:
        if not _enf:
            return ""
        if forma in _FORMAS_CAIXA:  # em cima da caixa na cor de acento: pintar com ela sumia (Selo de ano "1979") — sublinha
            return "\\u1" if flag else "\\u0"
        return f"\\1c{acento}" if flag else f"\\1c{_cor_txt}"

    # texto principal + animação
    if anim == "type" or (h.get("timing") or {}).get("modo") == "tipagem":
        total_chars = max(1, len(texto))
        janela = min(dur_ms * 0.6, max(400, total_chars * 45))
        dt = janela / total_chars
        pedacos, k = [], 0
        for li, l in enumerate(linhas):
            fl = _enf_chars(l)
            for j_, ch in enumerate(l):
                t0 = int(k * dt)
                pedacos.append(f"{{{_cor_ch(fl[j_])}\\alpha&HFF&\\t({t0},{t0 + 1},\\alpha&H00&)}}{_esc(ch)}")
                k += 1
            if li < len(linhas) - 1:
                pedacos.append("\\N")
        ev(2, base + f"\\fad(0,{O}){saida_tag}", "".join(pedacos))
    elif (h.get("timing") or {}).get("modo") == "palavra" or anim == "cascata":
        # palavra por palavra — no tempo em que é dita, quando dá pra saber
        ws = [w for w in palavras if ini - 0.2 <= float(w["start"]) <= fim]
        tokens, k = [], 0
        lista = [p for l in linhas for p in (l.split() + ["\\N"])][:-1]
        n_pal = max(1, sum(1 for p in lista if p != "\\N"))
        for p in lista:
            if p == "\\N":
                tokens.append("\\N")
                continue
            t0 = int((float(ws[k]["start"]) - ini) * 1000) if k < len(ws) and len(ws) >= n_pal * 0.6 else int(k * min(220, dur_ms * 0.6 / n_pal))
            t0 = max(0, min(t0, dur_ms - 200))
            tokens.append(f"{{{_tag_palavra(anim, t0, acento)}}}{_pinta(p, _esc(p))} ")
            k += 1
        ev(2, base + f"\\fad(0,{O}){saida_tag}", "".join(tokens).rstrip())
    elif anim == "letras":
        pedacos, k = [], 0
        n = max(1, len(texto))
        passo = min(60, max(15, I * 1.5 / n))
        for li, l in enumerate(linhas):
            fl = _enf_chars(l)
            for j_, ch in enumerate(l):
                t0 = int(k * passo)
                pedacos.append(f"{{{_cor_ch(fl[j_])}\\alpha&HFF&\\blur12\\fscy140\\t({t0},{t0 + 220},\\alpha&H00&\\blur{bz}\\fscy100)}}{_esc(ch)}")
                k += 1
            if li < len(linhas) - 1:
                pedacos.append("\\N")
        ev(2, base + f"\\fad(0,{O}){saida_tag}", "".join(pedacos))
    elif anim == "contador" and re.search(r"\d", texto):
        m = re.search(r"\d[\d.,]*", texto)
        alvo_txt = m.group(0)
        try:
            alvo = float(alvo_txt.replace(".", "").replace(",", ".")) if alvo_txt.count(",") <= 1 else float(alvo_txt.replace(",", ""))
        except ValueError:
            alvo = 0
        passos = 14
        cont_ms = min(900, dur_ms * 0.5)
        for k in range(passos):
            v = alvo * (1 - (1 - (k + 1) / passos) ** 3)
            if re.fullmatch(r"1\d{3}|20\d{2}", alvo_txt):
                num = str(int(round(v)))
            else:
                num = f"{int(round(v)):,}".replace(",", ".") if alvo >= 1000 or float(alvo).is_integer() else f"{v:.1f}".replace(".", ",")
            t0 = ini + cont_ms / 1000 * k / passos
            t1 = ini + cont_ms / 1000 * (k + 1) / passos if k < passos - 1 else fim
            tx = _esc(texto.replace(alvo_txt, num, 1))
            tags = base + (f"\\fad({min(200, I)},0)" if k == 0 else "") + (f"\\fad(0,{O}){saida_tag}" if k == passos - 1 else "")
            ev(2, tags, corpo if k == passos - 1 else tx, t0, t1)
    elif anim == "cruzado" and len(linhas) > 1:
        lh = tam * 1.18
        y0 = y - altura_txt / 2 + lh / 2 if an in (5, 4, 6) else y
        for li, l in enumerate(linhas):
            sx = -W * 0.25 if li % 2 == 0 else W * 0.25
            yy = int(y0 + li * lh)
            tg = base.replace(f"\\an{an}\\pos({x},{y})", f"\\an5\\move({int(W / 2 + sx)},{yy},{int(W / 2)},{yy},0,{I})") + fad + saida_tag
            ev(2, tg, _esc(l))
    elif anim == "glitch":
        ev(2, base + fad + saida_tag, corpo)
        off = max(3, tam // 14)
        for dx_, c_ in ((off, "&H000000FF&"), (-off, "&H00FFFF00&")):
            tg = base.replace(f"\\pos({x},{y})", f"\\pos({x + dx_},{y})") + f"\\1c{c_}\\alpha&H60&\\t(0,{I * 2},\\alpha&HFF&)"
            ev(1, tg, corpo, ini, min(fim, ini + I * 2 / 1000))
    elif anim == "mira":
        # cantoneiras (colchetes) fecham sobre o texto; radar/scanner: uma linha varre
        bx, by, bw, bh = caixa_do_texto(0.55)
        k_ = max(10, int(min(bw, bh) * 0.28))
        t_ = max(2, tam // 14)
        abre = max(12, int(min(bw, bh) * 0.35))
        cantos = [(bx, by, 1, 1, -1, -1), (bx + bw, by, -1, 1, 1, -1), (bx, by + bh, 1, -1, -1, 1), (bx + bw, by + bh, -1, -1, 1, 1)]
        for (cx_, cy_, sx, sy, ox, oy) in cantos:
            pts = f"m 0 0 l {sx * k_} 0 {sx * k_} {sy * t_} {sx * t_} {sy * t_} {sx * t_} {sy * k_} 0 {sy * k_}"
            ev(1, f"\\an7\\move({int(cx_ + ox * abre)},{int(cy_ + oy * abre)},{int(cx_)},{int(cy_)},0,{int(I * 1.4)})\\bord0\\shad0\\1c{acento}\\p1\\fad({I // 2},{O})", pts)
        if re.search(r"radar|scanner", cor.get("entrada") or ""):
            tg, dr = retangulo(bx, by, bw, max(2, tam // 16), acento, 0x30, "")
            tg = tg.replace(f"\\pos({int(bx)},{int(by)})", f"\\move({int(bx)},{int(by)},{int(bx)},{int(by + bh)},0,{I * 2})") + f"\\blur2\\fad(0,{I})"
            ev(3, tg, dr, ini, min(fim, ini + I * 2.5 / 1000))
            ev(2, base + f"\\clip({int(bx)},{int(by)},{int(bx + bw)},{int(by)})\\t(0,{I * 2},\\clip({int(bx)},{int(by)},{int(bx + bw)},{int(by + bh)}))\\fad(0,{O}){saida_tag}", corpo)
        else:
            ev(2, base + f"\\blur8\\t({I // 2},{int(I * 1.4)},\\blur{bz})\\fad({I},{O}){saida_tag}", corpo)
    elif anim == "linha_tempo":
        # linha do tempo: um traço se desenha (com marcos) e o texto assenta sobre ele
        bx, by, bw, bh = caixa_do_texto(0.5)
        t_ = max(2, tam // 16)
        vert = "vert" in (cor.get("entrada") or "")
        if vert:
            lx = bx - tam * 0.4
            tg, dr = retangulo(lx, by, t_, bh, acento, 0, f"\\clip(0,{int(by)},{W},{int(by)})\\t(0,{I * 2},\\clip(0,{int(by)},{W},{int(by + bh)}))\\fad(0,{O})")
            ev(1, tg, dr)
            marcos = [(lx - t_ * 2, by + bh * f) for f in (0.0, 0.5, 1.0)]
        else:
            ly = by + bh + tam * 0.15
            tg, dr = retangulo(bx - tam * 0.3, ly, bw + tam * 0.6, t_, acento, 0,
                               f"\\clip({int(bx - tam * 0.3)},0,{int(bx - tam * 0.3)},{H})\\t(0,{I * 2},\\clip({int(bx - tam * 0.3)},0,{int(bx + bw + tam * 0.3)},{H}))\\fad(0,{O})")
            ev(1, tg, dr)
            marcos = [(bx - tam * 0.3 + (bw + tam * 0.6) * f, ly - t_ * 2) for f in (0.0, 0.33, 0.66, 1.0)]
        for k_, (mx, my) in enumerate(marcos):
            r_ = max(3, tam // 9)
            t0_ = int(I * 2 * k_ / max(1, len(marcos) - 1))
            ev(1, f"\\an5\\pos({int(mx + t_ / 2)},{int(my + t_ * 2)})\\bord0\\shad0\\1c{acento}\\p1\\alpha&HFF&\\t({t0_},{t0_ + 120},\\alpha&H00&)\\fad(0,{O})",
               f"m {-r_} 0 b {-r_} {-r_ * 1.3} {r_} {-r_ * 1.3} {r_} 0 b {r_} {r_ * 1.3} {-r_} {r_ * 1.3} {-r_} 0")
        ev(2, base.replace(f"\\pos({x},{y})", f"\\move({x},{y - int(tam * 0.4)},{x},{y},0,{I})") + f"\\fad({I},{O}){saida_tag}", corpo)
    elif anim == "versus" and an in (5, 2, 8):
        # "A vs B": cada lado entra de um lado, o "VS" estoura no meio
        m = re.split(r"\s+(vs\.?|x|versus|contra|×)\s+", texto, maxsplit=1, flags=re.I)
        if len(m) == 3:
            esq_txt, meio, dir_txt = m[0], m[1].upper().rstrip("."), m[2]
        else:
            ps = texto.split()
            meio_i = max(1, len(ps) // 2)
            esq_txt, meio, dir_txt = " ".join(ps[:meio_i]), "", " ".join(ps[meio_i:])
        gap = int(tam * (1.1 if meio else 0.3))
        b2 = base.replace(f"\\an{an}\\pos({x},{y})", "")
        ev(2, f"\\an6\\move({x - gap - int(W * 0.2)},{y},{x - gap},{y},0,{I})" + b2 + f"\\fad({I // 2},{O}){saida_tag}", _esc(esq_txt))
        ev(2, f"\\an4\\move({x + gap + int(W * 0.2)},{y},{x + gap},{y},0,{I})" + b2 + f"\\fad({I // 2},{O}){saida_tag}", _esc(dir_txt))
        if meio:
            ev(3, f"\\an5\\pos({x},{y})" + b2.replace(f"\\fs{med['fs_ass']}", f"\\fs{int(med['fs_ass'] * 0.8)}") + f"\\1c{acento}\\alpha&HFF&\\fscx250\\fscy250\\t({int(I * 0.8)},{int(I * 0.8) + 1},\\alpha&H00&)\\t({int(I * 0.8)},{int(I * 1.3)},\\fscx100\\fscy100)\\fad(0,{O})", _esc(meio))
    elif anim == "matchcut":
        # corte seco: aparece de uma vez, com um clarão branco por cima
        ev(2, base + f"\\fscx104\\fscy104\\t(0,140,\\fscx100\\fscy100)\\fad(0,{O}){saida_tag}", corpo)
        ev(3, base + f"\\1c&H00FFFFFF&\\3c&H00FFFFFF&\\3a&H00&\\blur6\\bord{max(2, tam // 10)}\\t(0,180,\\alpha&HFF&)", corpo, ini, min(fim, ini + 0.2))
    elif anim == "grade":
        # grade técnica se desenha atrás, o texto entra pelo lado indicado no nome
        e_nome = cor.get("entrada") or ""
        bx, by, bw, bh = caixa_do_texto(1.0)
        claro = _cor_ass(dp_cores_tom_claro(paleta.get("primaria", "#FFD60A")))
        n_l = 4
        for k_ in range(n_l + 1):
            yy = by + bh * k_ / n_l
            t0_ = int(I * 1.2 * k_ / n_l)
            tg, dr = retangulo(bx - tam, yy, bw + 2 * tam, max(1, tam // 30), claro, 0x70,
                               f"\\clip({int(bx - tam)},0,{int(bx - tam)},{H})\\t({t0_},{t0_ + I},\\clip({int(bx - tam)},0,{int(bx + bw + tam)},{H}))\\fad(0,{O})")
            ev(0, tg, dr)
        for k_ in range(6):
            xx = bx - tam + (bw + 2 * tam) * k_ / 5
            t0_ = int(I * 0.6 + I * 1.2 * k_ / 5)
            tg, dr = retangulo(xx, by - tam * 0.5, max(1, tam // 30), bh + tam, claro, 0x70,
                               f"\\clip(0,{int(by - tam * 0.5)},{W},{int(by - tam * 0.5)})\\t({t0_},{t0_ + I},\\clip(0,{int(by - tam * 0.5)},{W},{int(by + bh + tam * 0.5)}))\\fad(0,{O})")
            ev(0, tg, dr)
        dx_, dy_ = (0, int(H * 0.06))
        if "topo" in e_nome:
            dy_ = -int(H * 0.06)
        elif "dir" in e_nome:
            dx_, dy_ = int(W * 0.06), 0
        elif "lateral" in e_nome and "sobe" not in e_nome:
            dx_, dy_ = -int(W * 0.06), 0
        elif "centro" in e_nome or "foco" in e_nome or "tecnica" in e_nome or "blueprint" in e_nome:
            dx_, dy_ = 0, 0
        mv = f"\\move({x + dx_},{y + dy_},{x},{y},{I // 2},{int(I * 1.6)})" if (dx_ or dy_) else f"\\pos({x},{y})\\blur10\\t({I // 2},{int(I * 1.6)},\\blur{bz})"
        ev(2, base.replace(f"\\pos({x},{y})", mv) + f"\\alpha&HFF&\\t({I // 2},{int(I * 1.2)},\\alpha&H00&)\\fad(0,{O}){saida_tag}", corpo)
    elif anim == "pino":
        # pino de mapa cai e quica; o texto desliza ao lado
        bx, by, bw, bh = caixa_do_texto(0.4)
        r_ = max(6, int(tam * 0.32))
        px_, py_ = int(bx - r_ * 1.8), int(by + bh / 2)
        pino = f"m 0 {-r_ * 2.6} b {-r_ * 1.3} {-r_ * 2.6} {-r_ * 1.3} {-r_ * 1.2} 0 0 b {r_ * 1.3} {-r_ * 1.2} {r_ * 1.3} {-r_ * 2.6} 0 {-r_ * 2.6}"
        ev(1, f"\\an7\\move({px_},{py_ - int(H * 0.15)},{px_},{py_ + r_},0,{int(I * 0.8)})\\bord0\\shad0\\1c{acento}\\p1\\t({int(I * 0.8)},{int(I * 0.95)},\\fscy80)\\t({int(I * 0.95)},{int(I * 1.15)},\\fscy100)\\fad(80,{O})", pino)
        ev(1, f"\\an5\\pos({px_},{py_ - int(r_ * 0.9)})\\bord0\\shad0\\1c&H00FFFFFF&\\p1\\alpha&HFF&\\t({int(I * 0.9)},{I},\\alpha&H00&)\\fad(0,{O})",
           f"m {-r_ // 2} 0 b {-r_ // 2} {-r_ * 0.66} {r_ // 2} {-r_ * 0.66} {r_ // 2} 0 b {r_ // 2} {r_ * 0.66} {-r_ // 2} {r_ * 0.66} {-r_ // 2} 0")
        ev(2, base.replace(f"\\pos({x},{y})", f"\\move({x - int(W * 0.05)},{y},{x},{y},{int(I * 0.6)},{int(I * 1.4)})") + f"\\alpha&HFF&\\t({int(I * 0.6)},{int(I * 1.1)},\\alpha&H00&)\\fad(0,{O}){saida_tag}", corpo)
    elif anim == "assenta":
        # assenta: desce um pouco, desfocado, e firma
        ev(2, base.replace(f"\\pos({x},{y})", f"\\move({x},{y - int(tam * 0.5)},{x},{y},0,{I})") + f"\\blur9\\t(0,{I},\\blur{bz})\\fad({I},{O}){saida_tag}", corpo)
    else:
        tags = base
        if anim == "pop":
            tags += f"\\fscx30\\fscy30\\t(0,{int(I * 0.7)},\\fscx112\\fscy112)\\t({int(I * 0.7)},{I},\\fscx100\\fscy100)" + fad
        elif anim == "punch":
            tags += f"\\fscx190\\fscy190\\t(0,{I},0.6,\\fscx100\\fscy100)" + f"\\fad({I // 3},{O})"
        elif anim == "stamp":
            tags += f"\\fscx250\\fscy250\\t(0,{int(I * 0.6)},\\fscx100\\fscy100)\\fad(60,{O})"
        elif anim == "flip":
            tags += f"\\frx90\\t(0,{I},\\frx0)" + fad
        elif anim == "tracking":
            tags += f"\\fsp{int(tam * 0.5)}\\t(0,{I * 2},\\fsp0)" + fad
        elif anim == "blur":
            tags += f"\\blur18\\t(0,{I},\\blur{bz})" + fad
        elif anim == "slide":
            tags = tags.replace(f"\\pos({x},{y})", f"\\move({x - int(W * 0.06)},{y},{x},{y},0,{I})") + fad
        elif anim in ("revelar", "cortina", "marca", "sublinha", "terco"):
            bx, by, bw, bh = caixa_do_texto(0.4)
            if anim == "cortina":
                cx_ = bx + bw / 2
                tags += f"\\clip({int(cx_)},{int(by)},{int(cx_)},{int(by + bh)})\\t(0,{I * 2},\\clip({int(bx)},{int(by)},{int(bx + bw)},{int(by + bh)}))\\fad(0,{O})"
            else:
                d0 = I // 3 if anim in ("marca", "sublinha", "terco") else 0
                tags += f"\\clip({int(bx)},{int(by)},{int(bx)},{int(by + bh)})\\t({d0},{d0 + I * 2},\\clip({int(bx)},{int(by)},{int(bx + bw)},{int(by + bh)}))\\fad(0,{O})"
        elif anim == "acende":
            tags += f"\\alpha&HFF&\\t(0,70,\\alpha&H00&)\\t(70,140,\\alpha&HA0&)\\t(140,210,\\alpha&H00&)\\t(210,260,\\alpha&H80&)\\t(260,330,\\alpha&H00&)\\t(0,{I * 2},\\3c{acento})\\fad(0,{O})"
        else:
            tags += fad
        ev(2, tags + saida_tag, corpo)

    # saída "riscar": um traço atravessa o texto antes de sumir
    if saida == "riscar":
        bx, by, bw, bh = caixa_do_texto(0.15)
        d_ms = int((fim - ini) * 1000)
        t_a = max(I, d_ms - O - 380)
        ly = by + bh * 0.56
        tg, dr = retangulo(bx, ly - tam * 0.05, bw, tam * 0.1, acento, 0,
                           f"\\alpha&HFF&\\t({t_a},{t_a + 1},\\alpha&H00&)\\clip({int(bx)},0,{int(bx)},{H})\\t({t_a},{t_a + 330},\\clip({int(bx)},0,{int(bx + bw)},{H}))\\fad(0,{O})")
        ev(4, tg, dr)
    # movimento interno "brilho": um halo da cor de acento pulsando atrás do texto
    if interna == "brilho":
        d_ms = int((fim - ini) * 1000)
        pul, k = [], I
        while k + 700 < d_ms - O:
            pul.append(f"\\t({k},{k + 350},\\alpha&H40&)\\t({k + 350},{k + 700},\\alpha&HB0&)")
            k += 700
        ev(1, base.replace("\\be1", "") + f"\\1a&HFF&\\3c{acento}\\bord{max(2, tam // 9)}\\blur{max(4, tam // 6)}\\alpha&HB0&\\fad({I},{O})" + "".join(pul), corpo)

    # campos secundários (sobretítulo / rodapé)
    sec = [(c["id"], c.get("role")) for c in (h.get("texto") or {}).get("campos", []) if not c.get("principal")]
    acima = [campos.get(cid, "").strip() for cid, role in sec if role in ("label", "eyebrow", "tagLabel", "chapter", "prefix", "numeral") or cid in ("eyebrow", "eyebrowLabel", "tagLabel", "label", "chapter", "numeral", "prefix")]
    abaixo = [campos.get(cid, "").strip() for cid, role in sec if cid not in ("eyebrow", "eyebrowLabel", "tagLabel", "label", "chapter", "numeral", "prefix") and role not in ("label", "eyebrow", "tagLabel", "chapter", "prefix", "numeral")]
    ts = max(int(min(W, H) * 0.028), int(tam * 0.34))
    topo = y - (altura_txt / 2 if an in (5, 4, 6) else (altura_txt if an in (1, 2, 3) else 0))
    base_y = y + (altura_txt / 2 if an in (5, 4, 6) else (0 if an in (1, 2, 3) else altura_txt))
    al2 = {5: 2, 4: 1, 6: 3, 1: 1, 2: 2, 3: 3, 7: 1, 8: 2, 9: 3}[an]
    al8 = {5: 8, 4: 7, 6: 9, 1: 7, 2: 8, 3: 9, 7: 7, 8: 8, 9: 9}[an]
    for k, t in enumerate([a for a in acima if a][:1]):
        ev(3, f"\\an{al2}\\pos({x},{int(topo - tam * 0.15)})\\fn{_FONTE['montserrat']}\\fs{ts}\\b1\\bord0\\shad0\\1c{acento}\\fsp{max(1, ts // 6)}\\fad({I},{O})", _esc(t.upper()))
    for k, t in enumerate([a for a in abaixo if a][:2]):
        ev(3, f"\\an{al8}\\pos({x},{int(base_y + tam * 0.2 + k * ts * 1.3)})\\fn{_FONTE['default']}\\fs{ts}\\b0\\bord{max(1, ts // 18)}\\shad0\\3c&H000000&\\1c&H00D8D8D8&\\fad({I},{O})", _esc(t))
    return evs


def gerar_ass(destaques: List[Dict[str, Any]], W: int, H: int, caminho: str, paleta: Optional[Dict[str, str]] = None,
              palavras: Optional[List[Dict[str, Any]]] = None) -> str:
    paleta = paleta or paleta_padrao()
    linhas = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Txt,DP Inter,{int(min(W, H) * 0.07)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    import dp_cores
    for d in destaques:
        if estilo(d.get("estilo")):
            pal_d = paleta
            cor = str(d.get("cor") or "")
            if re.fullmatch(r"#[0-9a-fA-F]{6}", cor):  # cor própria deste destaque
                pal_d = dict(paleta, **dp_cores.derivar(cor.upper()))
            import dp_fundos
            fid, fcor, _fi = dp_fundos.resolver(d, (estilo(d["estilo"]) or {}).get("cena") or {}, paleta)
            r_, g_, b_ = dp_cores.rgb(fcor)
            if fid in ("papel", "jornal") or (fid in ("cor_solida", "cor_gradiente") and 0.299 * r_ + 0.587 * g_ + 0.114 * b_ > 165):
                d = dict(d, _texto_escuro=True)
            linhas += _eventos_de_um(d, W, H, pal_d, palavras or [])
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    return caminho


# ------------------------------------------------------------------ tratamento da cena (vídeo)
def _png_grade(tipo: str, W: int, H: int, pasta: str) -> str:
    from PIL import Image, ImageDraw
    os.makedirs(pasta, exist_ok=True)
    p = os.path.join(pasta, f"grade_{tipo}_{W}x{H}.png")
    if os.path.exists(p):
        return p
    cores = {"navy": ((14, 22, 48, 245), (60, 80, 130)), "escura": ((12, 12, 14, 240), (48, 48, 54)), "azul": ((10, 40, 90, 235), (60, 110, 190)),
             "verm": ((70, 10, 14, 235), (150, 40, 48)), "papel": ((233, 225, 206, 245), (200, 188, 160)), "ouro": ((40, 30, 8, 240), (150, 120, 40)),
             "frente": ((10, 10, 12, 150), (80, 80, 90)), "cyan": ((8, 38, 52, 240), (40, 150, 180)), "gradiente": None, "painel": None}
    if tipo == "gradiente":
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for yy in range(H):
            a = int(max(0, (yy / H - 0.35) / 0.65) ** 1.4 * 215)
            d.line([0, yy, W, yy], fill=(0, 0, 0, a))
        im.save(p)
        return p
    if tipo == "faixas":
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, W, int(H * 0.11)], fill=(0, 0, 0, 255))
        d.rectangle([0, int(H * 0.89), W, H], fill=(0, 0, 0, 255))
        im.save(p)
        return p
    fundo, linha = cores.get(tipo) or cores["escura"]
    im = Image.new("RGBA", (W, H), fundo)
    d = ImageDraw.Draw(im)
    passo = max(24, H // 14)
    for xx in range(0, W, passo):
        d.line([xx, 0, xx, H], fill=linha + (90,), width=1)
    for yy in range(0, H, passo):
        d.line([0, yy, W, yy], fill=linha + (90,), width=1)
    im.save(p)
    return p


def _tratamento(fundo: str, tratamento: str) -> str:
    f = fundo or ""
    if f.startswith("grade") or tratamento in ("front_grid", "fullscreen_grid", "tech_grid"):
        return "grade"
    if f in ("papel_arquivo", "pergaminho_epoca"):
        return "grade_papel"
    if f in ("blueprint_cyan", "mapa_rota"):
        return "grade_cyan"
    if f in ("faixas",):
        return "faixas"
    if f in ("gradiente", "banho_cor_suave", "banho_cor_grao", "luz", "nevoa", "veu_esq") or tratamento == "gradient":
        return "gradiente"
    if f in ("vinheta", "vinheta_grao", "vinheta_off") or tratamento == "vignette":
        return "vinheta"
    if f == "desfoque" or tratamento == "blur":
        return "desfoque"
    if f in ("impacto", "corte_flash", "corte_luz") or tratamento == "flash":
        return "flash"
    if f == "painel" or tratamento == "panel":
        return "painel"
    if f in ("escurecer", "escurecer_grao", "corte_preto", "corte_lamina", "corte_persiana", "corte_split", "corte_glitch", "corte_zoom", "corte_iris", "corte_batida") or tratamento == "dim":
        return "escurecer"
    return ""


def filtros_de_tratamento(destaques: List[Dict[str, Any]], W: int, H: int, pasta: str,
                          paleta: Optional[Dict[str, str]] = None) -> Tuple[List[str], List[str]]:
    """(entradas extras, etapas do filtergraph usando [base]) pro fundo de cada
    destaque — o do estilo ou o escolhido (dp_fundos: faixas, grades retas ou
    onduladas, cena desfocada, banho de cor…), com cor e intensidade."""
    import dp_fundos
    ent: List[str] = []
    etapas: List[str] = []
    usos_png: Dict[str, List[str]] = {}  # um PNG = uma entrada só (dividida), não uma por destaque
    for d in destaques:
        h = estilo(d.get("estilo")) or {}
        fid, cor, inten = dp_fundos.resolver(d, h.get("cena") or {}, paleta)
        if fid == "nenhum":
            continue
        a, b = float(d["start"]), float(d["end"])
        novas, png = dp_fundos.etapas_destaque(fid, cor, inten, a, b, W, H, pasta)
        etapas += novas
        if png:
            rot = f"g{len(etapas)}x{len(usos_png)}"
            usos_png.setdefault(png, []).append(rot)
            etapas.append(f"[base][{rot}]overlay=shortest=0:eof_action=repeat:enable='between(t,{a:.3f},{b:.3f})'[base]")
    for n_in, (png, rotulos) in enumerate(usos_png.items(), start=1):
        ent += ["-loop", "1", "-framerate", "2", "-i", png]
        saidas = "".join(f"[{r}]" for r in rotulos)
        # a imagem entra a 2 fps (decodifica pouco) e o fps=30 só repete o quadro: sem isso
        # o overlay com enable= não pega o quadro na hora certa e o fundo não aparece
        etapas.insert(0, f"[{n_in}:v]format=rgba,fps=30" + (f",split={len(rotulos)}" if len(rotulos) > 1 else "") + saidas)
    return ent, etapas


def aplicar_destaques(video_in: str, video_out: str, destaques: List[Dict[str, Any]], W: int, H: int, work_dir: str,
                      paleta: Optional[Dict[str, str]] = None, palavras: Optional[List[Dict[str, Any]]] = None) -> str:
    """Um passe do ffmpeg: tratamento da cena + legenda ASS animada. O áudio é copiado."""
    from video_assembler import _escape_path_for_ffmpeg_filter, _probe_duration
    validos = [d for d in destaques if estilo(d.get("estilo"))]
    if not validos:
        return video_in
    os.makedirs(work_dir, exist_ok=True)
    ass = gerar_ass(validos, W, H, os.path.join(work_dir, "destaques.ass"), paleta, palavras)
    ent, etapas = filtros_de_tratamento(validos, W, H, os.path.join(work_dir, "destaques_png"), paleta)
    dur = _probe_duration(video_in)
    grafo = ["[0:v]setpts=PTS-STARTPTS,format=yuv420p[base]"] + etapas + [
        f"[base]ass='{_escape_path_for_ffmpeg_filter(ass)}':fontsdir='{_escape_path_for_ffmpeg_filter(FONTES_DIR)}',format=yuv420p[vout]"
    ]
    final = dp_visual._encadear(grafo)
    script = os.path.join(work_dir, "_destaques_grafo.txt")
    with open(script, "w", encoding="utf-8") as f:
        f.write(";\n".join(final))
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video_in] + ent + [
        "-filter_complex_script", script, "-map", "[vout]", "-map", "0:a?", "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "copy", video_out,
    ]
    import qualidade_export
    cmd_cpu = qualidade_export._ajustar_cpu(cmd)
    cmd = qualidade_export.ajustar(cmd)
    r = qualidade_export.executar(cmd, timeout=3600, _original=cmd_cpu)
    if r.returncode != 0 and ("nrecognized" in r.stderr or "not found" in r.stderr) and "filter_complex_script" in r.stderr:
        k = cmd.index("-filter_complex_script")
        r = subprocess.run(cmd[:k] + ["-/filter_complex"] + cmd[k + 1:], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou nos destaques: {r.stderr.strip()[-900:]}")
    return video_out


# ------------------------------------------------------------------ texto avulso -> vídeo (página "Textos animados")
FUNDOS_AVULSO = {
    "preto": ("Fundo preto (MP4)", ".mp4"), "verde": ("Fundo verde p/ chroma key (MP4)", ".mp4"),
    "transparente_mov": ("Transparente — MOV ProRes 4444 (Premiere, DaVinci, CapCut PC)", ".mov"),
    "transparente_webm": ("Transparente — WEBM VP9 (navegador, OBS)", ".webm"),
}


def renderizar_avulso(estilo_id: str, texto: str, dur: float, W: int, H: int, fundo: str, saida_base: str, work_dir: str,
                      campos: Optional[Dict[str, str]] = None, zona: Optional[str] = None, paleta: Optional[Dict[str, str]] = None,
                      com_tratamento: bool = True) -> str:
    """Só o texto animado, num vídeo próprio (pra usar em qualquer editor)."""
    from video_assembler import _escape_path_for_ffmpeg_filter
    if not estilo(estilo_id):
        raise ValueError(f"Estilo desconhecido: {estilo_id!r}")
    if fundo not in FUNDOS_AVULSO:
        fundo = "preto"
    dur = max(0.8, min(60.0, float(dur)))
    d = {"estilo": estilo_id, "start": 0.05, "end": dur - 0.05, "texto": texto, "campos": campos or {}, "avulso": True, "zona": zona}
    os.makedirs(work_dir, exist_ok=True)
    ass = gerar_ass([d], W, H, os.path.join(work_dir, "avulso.ass"), paleta)
    transparente = fundo.startswith("transparente")
    cor = {"preto": "black", "verde": "0x00B140"}.get(fundo, "black@0.0")
    ext = FUNDOS_AVULSO[fundo][1]
    saida = saida_base + ext
    filtros = [f"color=c={cor}:s={W}x{H}:r=30:d={dur:.3f},format={'rgba' if transparente else 'yuv420p'}[base]"]
    ent: List[str] = []
    if com_tratamento and not transparente and fundo == "preto":
        e2, etapas = filtros_de_tratamento([d], W, H, os.path.join(work_dir, "png"))
        ent += e2
        filtros += [x.replace("[0:v]", "[0:v]") for x in etapas]
    filtros.append(f"[base]ass='{_escape_path_for_ffmpeg_filter(ass)}':fontsdir='{_escape_path_for_ffmpeg_filter(FONTES_DIR)}'[vout]")
    grafo = dp_visual._encadear(filtros)
    # as entradas extras (PNGs) começam no índice 0 porque o fundo é gerado no grafo
    grafo = [g.replace("[1:v]", "[0:v]").replace("[2:v]", "[1:v]") for g in grafo]
    script = os.path.join(work_dir, "avulso_grafo.txt")
    with open(script, "w", encoding="utf-8") as f:
        f.write(";\n".join(grafo))
    if fundo == "transparente_mov":
        cod = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le"]
    elif fundo == "transparente_webm":
        cod = ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "2M", "-auto-alt-ref", "0"]
    else:
        cod = ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + ent + ["-filter_complex_script", script, "-map", "[vout]", "-t", f"{dur:.3f}", "-r", "30"] + cod + [saida]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    if r.returncode != 0 and "filter_complex_script" in r.stderr and ("nrecognized" in r.stderr or "not found" in r.stderr):
        k = cmd.index("-filter_complex_script")
        r = subprocess.run(cmd[:k] + ["-/filter_complex"] + cmd[k + 1:], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou ao gerar o texto: {r.stderr.strip()[-600:]}")
    return saida


_FONTES_DE_FABRICA = dict(_FONTE)


def _aplicar_extras() -> None:
    """Fontes dos extras viram opção nos destaques (tipografia.fonte = a chave)."""
    _FONTE.clear()
    _FONTE.update(_FONTES_DE_FABRICA)
    try:
        import dp_extras
        for k, v in (dp_extras.carregar().get("fontes") or {}).items():
            fam = str(v.get("familia") or "")
            if k in _FONTES_DE_FABRICA:
                dp_extras.avisar(f"{v.get('_arquivo')}: fonte {k} já existe — escolha outra chave.")
            elif not fam.startswith("DP "):
                dp_extras.avisar(f"{v.get('_arquivo')}: fonte {k}: a \"familia\" precisa começar com \"DP \" (use  python dp_guia.py fonte).")
            else:
                _FONTE[k] = fam
    except Exception:  # noqa: BLE001
        pass
    _CSS_FONTE.clear()
    _CSS_FONTE.update(_FONTE)


_aplicar_extras()
