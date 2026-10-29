"""
shorts_ia.py — 🎌 Shorts de IA (v84_263)
========================================

Shorts feitos 100% com IA (imagens e vídeos do Google Flow), em duas partes que se juntam:

  B · 🌌 o UNIVERSO da série: um elenco FIXO de personagens originais (aparência travada numa imagem de referência,
      personalidade, jeito de falar, voz), os cenários que se repetem, o tom e os bordões. Cada episódio usa esse elenco
      — é o que faz o público reconhecer o canal e voltar.
  A · 📺 MODELAR um viral: o link do vídeo que bombou → baixa, transcreve e corta nos planos (as "âncoras": um quadro
      por plano) → a 🤖 IA descreve o storyboard (o que acontece, quem fala o quê, por que viraliza) → troca o elenco
      original pelo da série e reescreve as falas no tom da série (você edita) → cenas com quadro de INÍCIO (A) e,
      quando precisa, de FIM (B), geradas no Flow com as referências das personagens (até 3 por cena) → cada cena vira
      vídeo no Flow (imagem → vídeo, com a fala) → edição: corta a ponta bugada, acelera, transição rápida + whoosh,
      zoom, filtro, legenda no meio, música, @ do canal → exporta.

  Sem viral? O episódio sai de uma 💡 ideia da série (formatos que viralizam: expectativa × realidade, mal-entendido
  que escala, reação exagerada…).

Personagens são SEMPRE originais (nada de personagem de anime existente): o estilo é descrito em palavras, sem nome de
obra/estúdio — o Flow recusa nome de obra e o canal não toma strike.

Tudo fica em shorts_ia/<serie>/ (serie.json, refs/) e shorts_ia/<serie>/eps/<ep>/ (ep.json, origem, quadros, cenas,
export). A fila do Flow é a do 🚀 Flow em massa (flow_lote): várias contas, sobrevive a reiniciar o site.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

TRAVA = threading.RLock()


class ShortsIAErro(Exception):
    pass


# ------------------------------------------------------------------ constantes
ESTILOS: Dict[str, Dict[str, str]] = {
    "anime_comedia": {
        "nome": "🎌 Anime de comédia (padrão)",
        "dica": "cel-shading limpo, cores vivas, olhos grandes, caretas chibi nas piadas, cenários aconchegantes",
        "prompt": ("2D Japanese TV anime comedy style, clean cel shading, crisp thin lineart, bright saturated colors with soft "
                   "pastel accents, big expressive eyes, exaggerated comedic reaction faces with chibi-style deformation on the "
                   "gags, sweat drops and anime comedy symbols, soft bloom lighting, detailed cozy slice-of-life backgrounds, "
                   "original characters"),
    },
    "anime_cotidiano": {
        "nome": "🌾 Anime de cotidiano (interior, aconchegante)",
        "dica": "slice-of-life no interior: luz de verão, traço limpo, cores chapadas suaves, expressões grandes e fofas",
        # v84_270: "watercolor backgrounds" puxava os cenários pra pintura semi-realista — fora do traço dos personagens
        "prompt": ("2D Japanese slice-of-life TV anime style, flat cel shading with clean thin lineart, simple flat color "
                   "fills with one soft shadow tone, the SAME simple anime look for characters and backgrounds (backgrounds "
                   "drawn with clean lines and flat colors, not painterly, not photorealistic), warm summer daylight, soft "
                   "pastel palette, Japanese countryside, big expressive eyes, cute exaggerated comedic reactions on the "
                   "gags, original characters"),
    },
    "anime_3d": {
        "nome": "🧸 3D estilizado",
        "dica": "cara de filme de animação 3D, proporções cartoon",
        "prompt": ("stylized 3D animated feature film look, soft global illumination, appealing cartoon proportions, big "
                   "expressive faces, subsurface skin, original characters"),
    },
    "realista": {
        "nome": "📷 Realista",
        "dica": "foto/filme real",
        "prompt": "photorealistic cinematic look, natural lighting, 35mm lens, realistic skin and fabric detail",
    },
}
ESTILO_PADRAO = "anime_comedia"
PROPORCOES = ("9:16", "1:1", "16:9")
LINGUAS = {"en": "English", "pt": "Português (Brasil)", "es": "Español", "it": "Italiano", "fr": "Français", "de": "Deutsch"}
NOME_LINGUA = {"en": "ENGLISH", "pt": "BRAZILIAN PORTUGUESE", "es": "SPANISH", "it": "ITALIAN", "fr": "FRENCH", "de": "GERMAN"}
QUALIDADES = {"1080p": 1080, "1440p": 1440, "4k": 2160}
FILTROS = {
    "vivo": "eq=saturation=1.14:contrast=1.04",
    "quente": "eq=saturation=1.08:contrast=1.03,colorbalance=rs=.05:gs=.01:bs=-.05",
    "frio": "eq=saturation=1.05:contrast=1.03,colorbalance=rs=-.04:bs=.05",
    "nenhum": "",
}
TRANSICOES = ("rapida", "corte")
MODOS_VIDEO = {"frames": "🎬 continuidade: quadro A → vídeo, em sequência (recomendado)",
               "elementos": "🎙 fichas + voz (voz mais igual, continuidade mais solta)"}
MODELOS_VIDEO = ("Omni 1.1 Flash", "Veo 3.1 - Lite", "Veo 3.1 - Fast", "Veo 3.1 - Quality", "")
MODELO_VIDEO_PADRAO = "Omni 1.1 Flash"  # o que a técnica da ficha de voz usa
MODELO_VIDEO_MAXIMO = "Veo 3.1 - Quality"  # a qualidade máxima do Flow
MODELOS_IMAGEM = ("Nano Banana Pro", "Nano Banana 2.1", "Nano Banana 2 Lite", "")
MAX_REFS_CENA = 3
MAX_INSPIRACOES = 6
MAX_ELENCO = 24          # o elenco cresce com os episódios (personagens novos)
DUR_PLANO_PADRAO = 6.0   # cada plano (um vídeo do Flow) — cortes rápidos, vários ângulos do mesmo momento
DUR_VIDEO_FLOW = 10.0  # o Flow faz 4, 6, 8 ou 10 s
DURACOES_FLOW = (4, 6, 8, 10)


def duracao_flow(dur: float) -> str:
    """A duração do Flow pro plano: a menor de 4/6/8/10 s que cobre o plano."""
    return f"{next((d for d in DURACOES_FLOW if d >= float(dur or 6) - 0.25), 10)}s"
ESTADOS_ESPERA = ("fila", "gerando", "parado")

FORMATOS_VIRAIS = [
    "expectativa × realidade",
    "mal-entendido que vai escalando",
    "alguém tenta uma coisa simples e dá tudo errado",
    "reação exagerada a algo banal",
    "pergunta inocente, resposta absurda",
    "POV (o público é a personagem)",
    "tutorial que desanda",
    "duelo de bordões / rivalidade boba",
    "plot twist no último segundo",
    "loop: o final emenda no começo",
]


def _pasta_base(base: str) -> str:
    p = os.environ.get("SHORTS_IA_DIR") or os.path.join(base, "shorts_ia")
    os.makedirs(p, exist_ok=True)
    return p


def _id() -> str:
    return secrets.token_hex(4)


def _ok_id(x: str) -> str:
    x = str(x or "")
    if not re.fullmatch(r"[0-9a-f]{8}", x):
        raise ShortsIAErro("Não encontrado.")
    return x


def pasta_serie(base: str, sid: str) -> str:
    return os.path.join(_pasta_base(base), _ok_id(sid))


def pasta_ep(base: str, sid: str, eid: str) -> str:
    return os.path.join(pasta_serie(base, sid), "eps", _ok_id(eid))


def _gravar(caminho: str, dados: Any) -> None:
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + f".{secrets.token_hex(3)}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def _ler(caminho: str) -> Dict[str, Any]:
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        raise ShortsIAErro("Não encontrado.") from exc


def slug_marca(nome: str) -> str:
    s = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9_.]+", "", s)
    return f"@{s}" if s else "@seucanal"


# ------------------------------------------------------------------ série (universo)
def _slot() -> Dict[str, Any]:
    return {"estado": None, "arquivo": None, "flow_job": None, "erro": None, "msg": "", "prompt": ""}


def _personagem(d: Dict[str, Any], pid: str) -> Dict[str, Any]:
    g = lambda k, n=600: " ".join(str(d.get(k) or "").split())[:n]  # noqa: E731
    return {"id": pid, "nome": g("nome", 60) or pid, "papel": g("papel", 160), "aparencia": g("aparencia", 900),
            "personalidade": g("personalidade", 500), "jeito_de_falar": g("jeito_de_falar", 400), "voz": g("voz", 300),
            "genero": g("genero", 40), "idade": g("idade", 40), "altura": g("altura", 40),
            "detalhes": g("detalhes", 500),  # 🎒 o que SEMPRE aparece nele (alça da bolsa, óculos redondos…) — em inglês
            "ref": d.get("ref") if isinstance(d.get("ref"), dict) else _slot(),
            "ficha": d.get("ficha") if isinstance(d.get("ficha"), dict) else _slot(),       # 📋 folha de personagem (várias vistas)
            "voz_ficha": d.get("voz_ficha") if isinstance(d.get("voz_ficha"), dict) else _slot(),  # 🎙 folha de voz (imagem)
            "voz_perfil": d.get("voz_perfil") if isinstance(d.get("voz_perfil"), dict) else None,
            "historico": _historico_normal(d), "estreia": d.get("estreia"), "fixo": d.get("fixo", True) is not False,
            "inspiracoes": [str(x) for x in d.get("inspiracoes") or [] if isinstance(x, str)][:MAX_INSPIRACOES],
            "preparar": bool(d.get("preparar"))}


def _historico_normal(d: Dict[str, Any]) -> List[Dict[str, Any]]:
    """O que já aconteceu com o personagem (vem dos capítulos; você edita). `historico_txt` = um fato por linha (seus)."""
    if "historico_txt" in d:
        velhos = {x.get("fato"): x for x in d.get("historico") or [] if isinstance(x, dict)}
        return [velhos.get(l.strip()) or {"fato": l.strip()[:200], "ep": None}
                for l in str(d.get("historico_txt") or "").splitlines() if l.strip()][:40]
    return [x for x in d.get("historico") or [] if isinstance(x, dict) and x.get("fato")][:40]


def _cenario(d: Dict[str, Any], lid: str) -> Dict[str, Any]:
    g = lambda k, n=600: " ".join(str(d.get(k) or "").split())[:n]  # noqa: E731
    return {"id": lid, "nome": g("nome", 60) or lid, "descricao": g("descricao", 700),
            "ref": d.get("ref") if isinstance(d.get("ref"), dict) else _slot()}


def nova_serie(base: str, nome: str = "", premissa: str = "", estilo: str = ESTILO_PADRAO, idioma: str = "en",
               proporcao: str = "9:16") -> Dict[str, Any]:
    sid = _id()
    s = {"id": sid, "nome": " ".join(str(nome or "").split())[:80] or "Nova série", "premissa": str(premissa or "").strip()[:2000],
         "estilo": estilo if estilo in ESTILOS else ESTILO_PADRAO, "idioma": idioma if idioma in LINGUAS else "en",
         "proporcao": proporcao if proporcao in PROPORCOES else "9:16", "tom": "", "bordoes": [], "regras": "",
         "elenco": [], "cenarios": [], "objetos": [], "ideias": [], "eps": [], "marca": None, "criado": time.time(),
         "padroes": padroes_normais(None), "formato_serie": "episodica"}
    s["marca"] = marca_da(s)
    salvar_serie(base, s)
    return s


def salvar_serie(base: str, s: Dict[str, Any]) -> None:
    with TRAVA:
        s["atualizado"] = time.time()
        _gravar(os.path.join(pasta_serie(base, s["id"]), "serie.json"), s)


def carregar_serie(base: str, sid: str) -> Dict[str, Any]:
    s = _ler(os.path.join(pasta_serie(base, sid), "serie.json"))
    s.setdefault("elenco", [])
    s.setdefault("cenarios", [])
    s.setdefault("ideias", [])
    s.setdefault("eps", [])
    # 🩹 v84_267: séries criadas antes de um campo novo (inspirações, histórico, fichas…) — completa tudo ao abrir
    s["elenco"] = [_personagem(p, str(p.get("id") or f"P{k}")) for k, p in enumerate(s["elenco"], 1) if isinstance(p, dict)]
    s["cenarios"] = [_cenario(c, str(c.get("id") or f"L{k}")) for k, c in enumerate(s["cenarios"], 1) if isinstance(c, dict)]
    s["objetos"] = [_cenario(c, str(c.get("id") or f"O{k}")) for k, c in enumerate(s.get("objetos") or [], 1) if isinstance(c, dict)]
    s["marca"] = marca_da(s)
    s["padroes"] = padroes_normais(s.get("padroes"))
    s.setdefault("formato_serie", "episodica")
    return s


def series(base: str) -> List[Dict[str, Any]]:
    out = []
    for nome in os.listdir(_pasta_base(base)):
        if re.fullmatch(r"[0-9a-f]{8}", nome):
            try:
                out.append(carregar_serie(base, nome))
            except ShortsIAErro:
                pass
    return sorted(out, key=lambda s: -float(s.get("criado") or 0))


def padroes_normais(d: Any) -> Dict[str, Any]:
    """O padrão de cada episódio novo da série: duração do plano e os modelos do Flow."""
    out = {"dur_plano": DUR_PLANO_PADRAO, "modelo_video": MODELO_VIDEO_PADRAO, "modo_video": "frames", "modelo_imagem": "",
           "auto_preparar": False}
    if isinstance(d, dict):
        if "auto_preparar" in d:
            out["auto_preparar"] = d["auto_preparar"] is True or str(d["auto_preparar"]).lower() in ("1", "true", "on", "sim")
        try:
            if d.get("dur_plano") not in (None, ""):
                out["dur_plano"] = round(max(2.0, min(DUR_VIDEO_FLOW, float(d["dur_plano"]))), 1)
        except (TypeError, ValueError):
            pass
        if d.get("modelo_video") in MODELOS_VIDEO:
            out["modelo_video"] = d["modelo_video"]
        if d.get("modo_video") in MODOS_VIDEO:
            out["modo_video"] = d["modo_video"]
        if d.get("modelo_imagem") in MODELOS_IMAGEM:
            out["modelo_imagem"] = d["modelo_imagem"]
    return out


def marca_da(s: Dict[str, Any]) -> Dict[str, Any]:
    import curtos as CT
    return CT.normalizar_marca(s.get("marca"), "") if s.get("marca") else dict(CT.marca_padrao(""), texto=slug_marca(s.get("nome")))


def atualizar_serie(base: str, sid: str, d: Dict[str, Any]) -> Dict[str, Any]:
    with TRAVA:
        s = carregar_serie(base, sid)
        nome_velho = s.get("nome")
        for k, n in (("nome", 80), ("tom", 600), ("regras", 1500)):
            if k in d:
                v = " ".join(str(d.get(k) or "").split())[:n]
                s[k] = v or (s.get(k) if k == "nome" else "")
        if s.get("nome") != nome_velho and (s.get("marca") or {}).get("texto") in (slug_marca(nome_velho), "@seucanal"):
            s["marca"] = dict(s["marca"], texto=slug_marca(s["nome"]))  # o @ acompanha o nome (se você não mudou o @ na mão)
        if "premissa" in d:
            s["premissa"] = str(d.get("premissa") or "").strip()[:2000]
        if "bordoes" in d:
            v = d["bordoes"]
            v = v if isinstance(v, list) else str(v or "").splitlines()
            s["bordoes"] = [" ".join(str(x).split())[:120] for x in v if str(x).strip()][:12]
        if d.get("estilo") in ESTILOS:
            s["estilo"] = d["estilo"]
        if d.get("formato_serie") in FORMATOS_SERIE:
            s["formato_serie"] = d["formato_serie"]
        if d.get("idioma") in LINGUAS:
            s["idioma"] = d["idioma"]
        if d.get("proporcao") in PROPORCOES:
            s["proporcao"] = d["proporcao"]
        if isinstance(d.get("padroes"), dict):
            s["padroes"] = padroes_normais(dict(s.get("padroes") or {}, **d["padroes"]))
        if isinstance(d.get("marca"), dict):
            import curtos as CT
            s["marca"] = CT.normalizar_marca(d["marca"], "")
        salvar_serie(base, s)
        return s


def _proximo(prefixo: str, existentes: List[Dict[str, Any]]) -> str:
    nums = [int(x["id"][1:]) for x in existentes if re.fullmatch(prefixo + r"\d+", str(x.get("id")))]
    return f"{prefixo}{(max(nums) + 1) if nums else 1}"


def salvar_personagem(base: str, sid: str, d: Dict[str, Any]) -> Dict[str, Any]:
    with TRAVA:
        s = carregar_serie(base, sid)
        pid = str(d.get("id") or "")
        velho = next((p for p in s["elenco"] if p["id"] == pid), None)
        if velho:
            novo = _personagem(dict(velho, **{k: v for k, v in d.items()
                                              if k not in ("ref", "ficha", "voz_ficha", "voz_perfil", "historico", "inspiracoes")}), pid)
            if novo["aparencia"] != velho.get("aparencia") and (velho.get("ref") or {}).get("arquivo"):
                novo["ref"] = dict(velho["ref"], desatualizada=True)  # mudou a aparência: a referência antiga ainda vale até gerar outra
            s["elenco"][s["elenco"].index(velho)] = novo
        else:
            if len(s["elenco"]) >= MAX_ELENCO:
                raise ShortsIAErro(f"O elenco tem no máximo {MAX_ELENCO} personagens.")
            novo = _personagem(d, _proximo("P", s["elenco"]))
            s["elenco"].append(novo)
        salvar_serie(base, s)
        return novo


def salvar_cenario(base: str, sid: str, d: Dict[str, Any], lista: str = "cenarios") -> Dict[str, Any]:
    """🏞 cenário (L1…) ou 🧸 objeto que se repete (O1…: o microfone, a bicicleta… com imagem de referência própria)."""
    pre = "O" if lista == "objetos" else "L"
    with TRAVA:
        s = carregar_serie(base, sid)
        lid = str(d.get("id") or "")
        velho = next((c for c in s[lista] if c["id"] == lid), None)
        if velho:
            novo = _cenario(dict(velho, **{k: v for k, v in d.items() if k != "ref"}), lid)
            s[lista][s[lista].index(velho)] = novo
        else:
            if len(s[lista]) >= 12:
                raise ShortsIAErro("No máximo 12.")
            novo = _cenario(d, _proximo(pre, s[lista]))
            s[lista].append(novo)
        salvar_serie(base, s)
        return novo


def apagar_item(base: str, sid: str, tipo: str, iid: str) -> None:
    with TRAVA:
        s = carregar_serie(base, sid)
        chave = "elenco" if tipo == "personagem" else ("objetos" if iid.startswith("O") else "cenarios")
        s[chave] = [x for x in s[chave] if x["id"] != iid]
        salvar_serie(base, s)


def item(s: Dict[str, Any], iid: str) -> Optional[Dict[str, Any]]:
    return next((x for x in s["elenco"] + s["cenarios"] + s.get("objetos", []) if x["id"] == iid), None)


def caminho_ref(base: str, s: Dict[str, Any], it: Optional[Dict[str, Any]]) -> Optional[str]:
    arq = ((it or {}).get("ref") or {}).get("arquivo")
    if not arq:
        return None
    c = os.path.join(pasta_serie(base, s["id"]), "refs", os.path.basename(arq))
    return c if os.path.isfile(c) else None


def guardar_ref(base: str, sid: str, iid: str, origem: str, por: str = "voce") -> str:
    """Uma imagem vira a referência TRAVADA da personagem/cenário (enviada por você ou gerada no Flow)."""
    from PIL import Image
    with TRAVA:
        s = carregar_serie(base, sid)
        it = item(s, iid)
        if not it:
            raise ShortsIAErro("Personagem/cenário não encontrado.")
        d = os.path.join(pasta_serie(base, sid), "refs")
        os.makedirs(d, exist_ok=True)
        nome = f"{iid}_{secrets.token_hex(3)}.png"
        try:
            Image.open(origem).convert("RGB").save(os.path.join(d, nome))
        except Exception as exc:  # noqa: BLE001
            raise ShortsIAErro("Não consegui abrir essa imagem.") from exc
        it["ref"] = dict(_slot(), estado="pronto", arquivo=nome, por=por, msg="🔒 travada")
        salvar_serie(base, s)
        return nome


# ------------------------------------------------------------------ IA
def _ia(sistema: str, conteudo: Any, schema: Dict[str, Any], chamar: Optional[Callable[..., Any]] = None, max_tokens: int = 6000,
        timeout: float = 200.0, job: str = "") -> Dict[str, Any]:
    import ia_servico
    import curtos as CT
    r = (chamar or ia_servico.chamar)("curtos", sistema, conteudo, schema=schema, max_tokens=max_tokens, timeout=timeout, job=job or None)
    if not r:
        raise ShortsIAErro(CT.motivo_ia())
    return r


def _o(props: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_S = {"type": "string"}
_N = {"type": "number"}


def _a(x: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "array", "items": x}


PERSONAGEM_SCHEMA = _o({"nome": _S, "papel": _S, "aparencia": _S, "personalidade": _S, "jeito_de_falar": _S, "voz": _S,
                        "genero": _S, "idade": _S, "altura": _S, "detalhes": _S})
PERSONAGEM_IMG_SCHEMA = _o(dict(PERSONAGEM_SCHEMA["properties"], imagem=_N))
UNIVERSO_SCHEMA = _o({"nome": _S, "premissa": _S, "tom": _S, "bordoes": _a(_S), "elenco": _a(PERSONAGEM_IMG_SCHEMA),
                      "objetos": _a(_o({"nome": _S, "descricao": _S})),
                      "cenarios": _a(_o({"nome": _S, "descricao": _S}))})
UNIVERSO_SYS = (
    "Você cria o UNIVERSO de uma série de shorts (YouTube Shorts / TikTok / Reels) feita com vídeos de IA, no formato de "
    "série curtinha de anime (comédia, cotidiano…): um elenco FIXO que o público reconhece e quer ver de novo em todo "
    "episódio. Regras:\n"
    "• Personagens 100% ORIGINAIS: nada de personagem, nome ou visual de obra existente (anime, mangá, jogo, desenho). "
    "Inspire-se só no CLIMA de comédias de convivência (uma criatura poderosa/estranha vivendo uma rotina boba com humanos, "
    "rivais que se adoram, a pessoa normal que sofre com o caos).\n"
    "• 2 a 4 personagens com CONTRASTE forte (o caótico, o certinho, o fofo-ameaçador, o que sofre). Silhuetas e cores "
    "bem diferentes entre si (dá pra reconhecer cada um num relance, em tela pequena).\n"
    "• 'aparencia' em INGLÊS, pra gerar a imagem de referência e manter IGUAL em todas as cenas: idade aparente, corpo, "
    "cabelo (cor, corte), olhos, roupa fixa com cores, 1 ou 2 detalhes marcantes (chifres, rabo, acessório). Sem pose e "
    "sem cenário.\n"
    "• Série de família/cotidiano pode ter CRIANÇAS: sempre em situações inocentes, cuidadas e seguras; a relação adulto–"
    "criança é de família, vizinho ou tutor — calorosa e respeitosa, com outros adultos da vila por perto. Nunca romance, "
    "nudez ou conteúdo sexual envolvendo qualquer personagem.\n"
    "• Se vierem IMAGENS do criador (numeradas), cada uma pode virar um personagem: descreva a 'aparencia' A PARTIR da "
    "imagem (fiel a ela) e ponha o número em 'imagem' (0 = personagem sem imagem).\n"
    "• 'voz' em INGLÊS: como a voz soa (tom, idade, energia, sotaque) — vai pro gerador de vídeo que fala.\n"
    "• 'genero' (male/female/other, em inglês), 'idade' (ex.: '25', 'looks 20, is 900 years old') e 'altura' (ex.: '171 cm').\n"
    "• 'detalhes' (INGLÊS): os detalhes que SEMPRE têm que aparecer nele em qualquer plano (ex.: 'brown crossbody bag "
    "strap across the chest, round thin glasses, sleeves rolled up') — é o que o gerador mais esquece.\n"
    "• 'personalidade' e 'jeito_de_falar' em português (o jeito_de_falar pode ter um tique/bordão próprio).\n"
    "• 'bordoes': 3 a 6 bordões curtos da série, no idioma do post — fáceis de falar em voz alta, SEM honoríficos ou "
    "expressões japonesas (nada de -san/-chan/'ara ara'); no português, jeito brasileiro.\n"
    "• 'cenarios': 1 a 3 lugares que se repetem (descrição em INGLÊS, sem personagens).\n"
    "• 'objetos': 0 a 3 objetos que aparecem sempre (o microfone dele, a bicicleta dela…) — descrição em INGLÊS bem "
    "precisa (forma, cor, tamanho, material), que vai se repetir igual em todo plano.\n"
    "• 'tom' (português): o tipo de humor e o ritmo (ex.: caos doméstico, piada visual + punchline no fim).\n"
    "• 'nome': o nome da série/canal (curto, fácil de virar @)."
)


def _blocos_imagens(imagens: List[str], texto: str) -> Any:
    if not imagens:
        return texto
    import ia_servico
    blocos: List[Dict[str, Any]] = []
    for k, c in enumerate(imagens, 1):
        b = ia_servico.imagem_bloco(c, largura=768)
        if b:
            blocos += [{"type": "text", "text": f"IMAGEM {k}:"}, b]
    return blocos + [{"type": "text", "text": texto}] if blocos else texto


def gerar_universo(base: str, sid: str, premissa: str = "", chamar: Optional[Callable[..., Any]] = None,
                   imagens: Optional[List[str]] = None) -> Dict[str, Any]:
    """🌌 nome, premissa, tom, bordões, elenco e cenários. `imagens`: referências suas — cada uma pode virar um personagem
    (a aparência é descrita a partir dela e a imagem fica TRAVADA como referência dele)."""
    s = carregar_serie(base, sid)
    premissa = (premissa or s.get("premissa") or "").strip()
    imagens = [c for c in (imagens or []) if c and os.path.isfile(c)][:8]
    texto = (f"ESTILO VISUAL: {ESTILOS[s['estilo']]['dica']}\nIDIOMA DO POST: {NOME_LINGUA[s['idioma']]}\n"
             f"IDEIA/PREMISSA (do criador): {premissa or '(livre — invente uma premissa de comédia que renda 1 episódio por dia)'}\n"
             + (f"NOME QUE O CRIADOR QUER: {s['nome']}\n" if s.get("nome") and s["nome"] != "Nova série" else "")
             + (f"PERSONAGENS QUE JÁ EXISTEM (mantenha, complete se faltar): {json.dumps(s['elenco'], ensure_ascii=False)[:3000]}\n" if s["elenco"] else ""))
    if imagens:
        texto += f"\n{len(imagens)} IMAGEM(NS) DE REFERÊNCIA do criador (acima): use cada uma pra um personagem (campo 'imagem')."
    r = _ia(UNIVERSO_SYS, _blocos_imagens(imagens, texto), UNIVERSO_SCHEMA, chamar, max_tokens=6000)
    com_imagem: List[Tuple[str, str]] = []
    with TRAVA:
        s = carregar_serie(base, sid)
        nome_velho = s.get("nome")
        if not s.get("nome") or s["nome"] == "Nova série":
            s["nome"] = " ".join(str(r.get("nome") or "").split())[:80] or s["nome"]
        s["premissa"] = premissa or str(r.get("premissa") or "")[:2000]
        if premissa and r.get("premissa"):
            s["premissa"] = str(r["premissa"])[:2000]
        s["tom"] = str(r.get("tom") or s.get("tom") or "")[:600]
        s["bordoes"] = [str(b)[:120] for b in (r.get("bordoes") or [])][:12] or s["bordoes"]
        existentes = {p["nome"].lower(): p for p in s["elenco"]}
        for p in (r.get("elenco") or [])[:8]:
            velho = existentes.get(str(p.get("nome") or "").lower())
            if velho:
                for k in ("papel", "aparencia", "personalidade", "jeito_de_falar", "voz", "genero", "idade", "altura", "detalhes"):
                    if not velho.get(k):
                        velho[k] = str(p.get(k) or "")[:900]
            elif len(s["elenco"]) < MAX_ELENCO:
                novo = _personagem(p, _proximo("P", s["elenco"]))
                s["elenco"].append(novo)
                velho = novo
            try:
                k = int(p.get("imagem") or 0)
            except (TypeError, ValueError):
                k = 0
            if velho and 1 <= k <= len(imagens):
                com_imagem.append((velho["id"], imagens[k - 1]))
        if not s.get("objetos"):
            s["objetos"] = [_cenario(o, f"O{k}") for k, o in enumerate((r.get("objetos") or [])[:4], 1)]
        if not s["cenarios"]:
            for c in (r.get("cenarios") or [])[:4]:
                s["cenarios"].append(_cenario(c, _proximo("L", s["cenarios"])))
        if (s.get("marca") or {}).get("texto") in (None, "", "@seucanal", slug_marca(nome_velho)):
            s["marca"] = dict(marca_da(s), texto=slug_marca(s["nome"]))
        salvar_serie(base, s)
    for pid, img in com_imagem:  # 🖼 a imagem vira INSPIRAÇÃO do personagem — você gera depois (🧍 com a foto / sem foto)
        try:
            guardar_inspiracoes(base, sid, pid, [img])
        except ShortsIAErro:
            pass
    return carregar_serie(base, sid)


PERFIL_IMG_SYS = (
    "Você recebe a imagem de um personagem (enviada pelo criador) e o universo de uma série de shorts de anime. Crie o "
    "PERFIL desse personagem pra série: 'aparencia' em INGLÊS descrita FIEL à imagem (idade aparente, corpo, cabelo, "
    "olhos, roupa e cores, detalhes marcantes — sem pose e sem cenário), 'voz' em INGLÊS (como soa), 'genero' em inglês, "
    "'idade', 'altura', e em português 'papel', 'personalidade' e 'jeito_de_falar' combinando com a série e com o que a "
    "imagem sugere (siga a NOTA do criador se houver). 'imagem' = 1. Personagem original; criança só em contexto "
    "inocente e seguro; nunca romance/sexual."
)


INSPIRACAO_SYS = (
    "Você recebe IMAGENS DE INSPIRAÇÃO (de outras obras ou fotos) e o universo de uma série de shorts de anime. Crie um "
    "personagem ORIGINAL que fique PRÓXIMO delas — mesmo arquétipo, idade aparente, energia, tipo de corpo e silhueta, "
    "paleta e clima — mas com design PRÓPRIO, que não seja cópia de nenhum personagem existente: mude o penteado, os "
    "traços do rosto, a roupa e os acessórios, e dê 1–2 detalhes marcantes novos. Nunca use nome, marca ou obra das "
    "imagens. 'aparencia' e 'voz' e 'genero' em INGLÊS (aparência sem pose e sem cenário); 'papel', 'personalidade' e "
    "'jeito_de_falar' em português, combinando com a série. Mantenha o NOME e o PAPEL atuais se vierem (a NOTA do criador "
    "manda). 'imagem' = 0. Criança só em contexto inocente e seguro; nunca romance/sexual."
)
INSPIRACAO_FOTO_SYS = (
    "Você recebe IMAGENS DE REFERÊNCIA de um personagem e o universo de uma série de shorts de anime. Escreva o perfil "
    "desse personagem PARECIDO com as imagens, adaptado ao mundo da série: 'aparencia' em INGLÊS descrevendo o rosto, "
    "o cabelo (corte e cor), os olhos, a pele, a idade aparente e o corpo como nas imagens, com a roupa e os acessórios "
    "que ele usaria na série (sem pose e sem cenário); 'voz' e 'genero' em INGLÊS; 'papel', 'personalidade' e "
    "'jeito_de_falar' em português combinando com a série. Mantenha o NOME, o PAPEL e o GÊNERO atuais se vierem (a NOTA "
    "do criador manda — se a nota disser gênero/idade, siga). Nunca use nome ou marca de obra existente. 'imagem' = 1. "
    "Criança só em contexto inocente e seguro; nunca romance/sexual."
)
REDESCREVER_SYS = (
    "Você recebe a(s) imagem(ns) de referência de UM personagem do criador (a primeira é a referência travada; as outras, "
    "o mesmo personagem em outros ângulos) e o perfil atual. Reescreva o perfil FIEL às imagens: 'aparencia' em INGLÊS "
    "(idade aparente, corpo, rosto, cabelo, olhos, roupa e cores, detalhes marcantes — sem pose e sem cenário), 'genero' "
    "em inglês, 'idade', 'altura', 'voz' em INGLÊS combinando com quem ele é; 'papel', 'personalidade' e 'jeito_de_falar' "
    "em português — mantenha o que o criador já escreveu e só complete/ajuste o que não bate com a imagem. Mantenha o "
    "NOME. 'imagem' = 1."
)


def pasta_refs(base: str, sid: str) -> str:
    d = os.path.join(pasta_serie(base, sid), "refs")
    os.makedirs(d, exist_ok=True)
    return d


def guardar_inspiracoes(base: str, sid: str, pid: str, arquivos: List[str]) -> List[str]:
    """🖼 imagens de inspiração do personagem (várias): a IA cria um personagem original PRÓXIMO delas."""
    from PIL import Image
    with TRAVA:
        s = carregar_serie(base, sid)
        p = item(s, pid)
        if not p or not pid.startswith("P"):
            raise ShortsIAErro("Personagem não encontrado.")
        for c in arquivos:
            if len(p["inspiracoes"]) >= MAX_INSPIRACOES:
                break
            nome = f"{pid}_insp_{secrets.token_hex(3)}.png"
            try:
                im = Image.open(c).convert("RGB")
                im.thumbnail((1600, 1600))
                im.save(os.path.join(pasta_refs(base, sid), nome))
            except Exception:  # noqa: BLE001
                continue
            p["inspiracoes"].append(nome)
        salvar_serie(base, s)
        return p["inspiracoes"]


def tirar_inspiracao(base: str, sid: str, pid: str, nome: str) -> None:
    with TRAVA:
        s = carregar_serie(base, sid)
        p = item(s, pid)
        if p and nome in p.get("inspiracoes", []):
            p["inspiracoes"].remove(nome)
            try:
                os.remove(os.path.join(pasta_refs(base, sid), os.path.basename(nome)))
            except OSError:
                pass
            salvar_serie(base, s)


def _perfil_atual_txt(p: Dict[str, Any]) -> str:
    return json.dumps({k: p.get(k) for k in PERSONAGEM_SCHEMA["properties"]}, ensure_ascii=False)


def refazer_personagem(base: str, sid: str, pid: str, modo: str = "referencia", nota: str = "",
                       chamar: Optional[Callable[..., Any]] = None, com_foto: bool = True) -> Dict[str, Any]:
    """🔁 refaz o personagem inteiro.
    modo "referencia": a imagem travada (sua) manda — a IA reescreve o perfil fiel a ela (+ inspirações como outros
      ângulos), e refaz 📋 ficha (do Flow, a partir da referência) e 🎙 voz.
    modo "inspiracao": as imagens de inspiração (de outras obras/fotos) viram um personagem ORIGINAL parecido — perfil
      novo, 🧍 referência nova gerada no Flow só pelo texto (sem copiar a imagem), depois 📋 ficha e 🎙 voz sozinhas."""
    s = carregar_serie(base, sid)
    p = item(s, pid)
    if not p or not pid.startswith("P"):
        raise ShortsIAErro("Personagem não encontrado.")
    refs_dir = pasta_refs(base, sid)
    insp = [os.path.join(refs_dir, x) for x in p.get("inspiracoes") or [] if os.path.isfile(os.path.join(refs_dir, x))]
    ref = caminho_ref(base, s, p)
    texto = (contexto_serie(s, base) + f"\n\nPERFIL ATUAL DE {p['id']}: {_perfil_atual_txt(p)}"
             + (f"\nNOTA DO CRIADOR: {nota}" if nota else ""))
    if modo == "inspiracao":
        if not insp:
            raise ShortsIAErro("Mande uma ou mais imagens de inspiração primeiro (🖼 inspirações).")
        r = _ia(INSPIRACAO_FOTO_SYS if com_foto else INSPIRACAO_SYS, _blocos_imagens(insp, texto), PERSONAGEM_IMG_SCHEMA, chamar,
                max_tokens=2000, timeout=150)
    else:
        if not ref:
            raise ShortsIAErro("Esse personagem ainda não tem referência travada (⬆ é minha / 🧍 no Flow).")
        r = _ia(REDESCREVER_SYS, _blocos_imagens([ref] + insp, texto), PERSONAGEM_IMG_SCHEMA, chamar, max_tokens=2000, timeout=150)
    dados = {k: r.get(k) for k in PERSONAGEM_SCHEMA["properties"] if str(r.get(k) or "").strip()}
    dados["nome"] = p["nome"] if p.get("nome") and not nota else dados.get("nome") or p["nome"]
    with TRAVA:
        s = carregar_serie(base, sid)
        p = item(s, pid)
        novo = _personagem(dict(p, **dados), pid)
        velha_ficha = (p.get("ficha") or {}).get("arquivo")
        novo["ficha"] = dict(_slot(), anterior=velha_ficha, arquivo=velha_ficha)  # a antiga vale até a nova chegar
        novo["ficha"]["estado"] = None
        novo["preparar"] = True
        if modo == "inspiracao":
            velha_ref = (p.get("ref") or {}).get("arquivo")
            novo["ref"] = dict(_slot(), anterior=velha_ref)  # a referência nova sai do texto (personagem original)
        s["elenco"][s["elenco"].index(p)] = novo
        salvar_serie(base, s)
    if modo == "inspiracao":
        pedir_refs(base, sid, [pid], com_foto=com_foto)  # → 🧍 pronta → 📋 ficha + 🎙 voz (sozinho, no sincronizar)
    else:
        _continuar_preparo(base, sid, [pid])  # 📋 ficha no Flow + 🎙 voz
    return item(carregar_serie(base, sid), pid)


def personagem_da_imagem(base: str, sid: str, imagem: Any, nota: str = "", chamar: Optional[Callable[..., Any]] = None,
                         modo: str = "minha") -> Dict[str, Any]:
    """➕ um personagem a partir de imagem(ns).
    "minha": é um personagem seu — a IA escreve o perfil fiel e a 1ª imagem vira a referência travada.
    "inspiracao": imagens de outras obras/fotos — a IA cria um personagem ORIGINAL próximo e a referência é gerada no Flow."""
    imagens = [imagem] if isinstance(imagem, str) else [c for c in imagem or [] if c]
    if not imagens:
        raise ShortsIAErro("Escolha a(s) imagem(ns).")
    s = carregar_serie(base, sid)
    if len(s["elenco"]) >= MAX_ELENCO:
        raise ShortsIAErro(f"O elenco tem no máximo {MAX_ELENCO} personagens.")
    texto = contexto_serie(s, base) + (f"\n\nNOTA DO CRIADOR SOBRE ESTE PERSONAGEM: {nota}" if nota else "")
    sistema = INSPIRACAO_FOTO_SYS if modo == "inspiracao" else PERFIL_IMG_SYS
    r = _ia(sistema, _blocos_imagens(imagens[:MAX_INSPIRACOES], texto), PERSONAGEM_IMG_SCHEMA, chamar, max_tokens=2000, timeout=150)
    novo = salvar_personagem(base, sid, {k: r.get(k) for k in PERSONAGEM_SCHEMA["properties"]})
    if modo == "inspiracao":
        guardar_inspiracoes(base, sid, novo["id"], imagens)
    else:
        guardar_ref(base, sid, novo["id"], imagens[0])
        if len(imagens) > 1:
            guardar_inspiracoes(base, sid, novo["id"], imagens[1:])
    return item(carregar_serie(base, sid), novo["id"])


IDEIAS_SCHEMA = _o({"ideias": _a(_o({"titulo": _S, "formato": _S, "sinopse": _S, "gancho": _S, "quem": _a(_S)}))})
IDEIAS_SYS = (
    "Você é o roteirista-chefe de uma série de shorts de comédia feita com IA. Proponha episódios de 20 a 40 s que "
    "VIRALIZAM, usando o elenco fixo (cada personagem agindo de acordo com a personalidade dele). Use formatos que "
    "comprovadamente prendem: {FORMATOS}. Cada ideia: 'titulo' (português, curto), 'formato' (um dos formatos), "
    "'sinopse' (português, 2–3 frases com começo, virada e punchline), 'gancho' (o que acontece/é dito nos 2 primeiros "
    "segundos), 'quem' (ids do elenco, no máximo 3). Varie formatos e duplas. Nada de repetir ideia já feita."
)


def gerar_ideias(base: str, sid: str, n: int = 8, chamar: Optional[Callable[..., Any]] = None) -> List[Dict[str, Any]]:
    s = carregar_serie(base, sid)
    if not s["elenco"]:
        raise ShortsIAErro("Crie o elenco primeiro (🌌 gerar universo ou ➕ personagem).")
    feitas = [i["titulo"] for i in s["ideias"]][-40:]
    texto = (contexto_serie(s, base) + f"\n\nQUANTAS: {max(3, min(15, int(n)))}\nJÁ FEITAS (não repita): {json.dumps(feitas, ensure_ascii=False)}")
    r = _ia(IDEIAS_SYS.replace("{FORMATOS}", "; ".join(FORMATOS_VIRAIS)), texto, IDEIAS_SCHEMA, chamar, max_tokens=5000)
    ids = {p["id"] for p in s["elenco"]}
    novas = []
    with TRAVA:
        s = carregar_serie(base, sid)
        for i in r.get("ideias") or []:
            if not str(i.get("titulo") or "").strip():
                continue
            novas.append({"id": _id(), "titulo": str(i["titulo"])[:140], "formato": str(i.get("formato") or "")[:80],
                          "sinopse": str(i.get("sinopse") or "")[:800], "gancho": str(i.get("gancho") or "")[:300],
                          "quem": [q for q in (i.get("quem") or []) if q in ids][:MAX_REFS_CENA], "ep": None})
        s["ideias"] = (s["ideias"] + novas)[-120:]
        salvar_serie(base, s)
    return novas


FORMATOS_SERIE = {"episodica": "📺 episódica — cada capítulo se fecha sozinho (dá pra ver em qualquer ordem)",
                  "continua": "📖 contínua — cada capítulo continua a história do anterior"}


def _historico_txt(p: Dict[str, Any]) -> str:
    h = [x.get("fato") for x in p.get("historico") or [] if x.get("fato")]
    return (" | já aconteceu/já se sabe: " + "; ".join(h[-12:])) if h else ""


def linha_do_tempo(base: str, s: Dict[str, Any], n: int = 10) -> List[Dict[str, Any]]:
    """Os capítulos já escritos, do mais antigo pro mais novo (título + resumo)."""
    out = []
    for e in reversed(eps_da_serie(base, s)):
        if e.get("resumo") or e.get("cenas"):
            out.append({"id": e["id"], "titulo": e["titulo"], "resumo": e.get("resumo") or e.get("logica") or ""})
    return out[-n:]


def contexto_serie(s: Dict[str, Any], base: str = "") -> str:
    el = "\n".join(f"- {p['id']} · {p['nome']} ({p['papel']}{', ' + p['genero'] if p.get('genero') else ''}"
                   f"{', ' + p['idade'] if p.get('idade') else ''}): aparência: {p['aparencia']} | personalidade: {p['personalidade']} | "
                   f"fala: {p['jeito_de_falar']} | voz: {p['voz']}" + ("" if p.get("fixo", True) else " | (participação: só volta se fizer sentido)")
                   + _historico_txt(p) for p in s["elenco"])
    fmt = s.get("formato_serie") or "episodica"
    tl = ""
    if base:
        caps = linha_do_tempo(base, s, 10 if fmt == "continua" else 6)
        if caps:
            tl = "\nCAPÍTULOS JÁ FEITOS (do mais antigo pro mais novo):\n" + "\n".join(f"- {c['titulo']}: {c['resumo']}" for c in caps)
    regra_fmt = ("FORMATO DA SÉRIE: CONTÍNUA — este capítulo CONTINUA do ponto em que o último parou (consequências, "
                 "relações e objetos que mudaram valem)." if fmt == "continua" else
                 "FORMATO DA SÉRIE: EPISÓDICA — o capítulo se fecha sozinho e não depende dos outros, MAS os personagens são "
                 "os mesmos: personalidade, relações e o que já aconteceu com eles (histórico) nunca são contraditos.")
    ce = "\n".join(f"- {c['id']} · {c['nome']}: {c['descricao']}" for c in s["cenarios"])
    ob = "\n".join(f"- {c['id']} · {c['nome']}: {c['descricao']}" for c in s.get("objetos") or [])
    return (f"SÉRIE: {s['nome']}\nPREMISSA: {s.get('premissa') or ''}\nTOM: {s.get('tom') or ''}\n"
            f"BORDÕES: {' | '.join(s.get('bordoes') or [])}\n" + (f"REGRAS DO CRIADOR: {s['regras']}\n" if s.get("regras") else "")
            + f"ELENCO:\n{el or '(vazio)'}\nCENÁRIOS:\n{ce or '(nenhum)'}\n"
            + (f"OBJETOS QUE SE REPETEM (use o id em 'objetos' do plano e descreva com as MESMAS palavras):\n{ob}\n" if ob else "")
            + f"IDIOMA DO POST: {NOME_LINGUA[s['idioma']]}\n"
            f"FORMATO DE TELA: {s['proporcao']}\n{regra_fmt}{tl}")


# ------------------------------------------------------------------ episódio
def novo_ep(base: str, sid: str, titulo: str = "", url: str = "", ideia: str = "") -> Dict[str, Any]:
    with TRAVA:
        s = carregar_serie(base, sid)
        eid = _id()
        idd = next((i for i in s["ideias"] if i["id"] == ideia), None) if ideia else None
        e = {"id": eid, "serie": sid, "titulo": " ".join(str(titulo or (idd or {}).get("titulo") or "").split())[:140] or "Novo episódio",
             "criado": time.time(),
             "origem": {"tipo": "viral" if url else ("ideia" if idd else "livre"), "url": str(url or "").strip()[:600],
                        "video": None, "duracao": 0.0, "transcricao": [], "storyboard": [], "analise": None,
                        "ideia": idd, "notas": ""},
             "papeis": {}, "cenas": [], "titulos": [], "export": None,
             "edicao": dict(opcoes_padrao(s.get("estilo") or ""), **{k: s["padroes"][k] for k in ("modo_video", "modelo_video")}),
             "dur_plano": s["padroes"]["dur_plano"]}
        salvar_ep(base, e)
        s["eps"] = [eid] + [x for x in s["eps"] if x != eid]
        if idd:
            idd["ep"] = eid
        salvar_serie(base, s)
        return e


MAX_BACKUPS = 25


def salvar_ep(base: str, e: Dict[str, Any]) -> None:
    """Grava o episódio — e guarda a versão anterior em backups/ (as últimas 25), pra nunca perder planos e vídeos."""
    with TRAVA:
        e["atualizado"] = time.time()
        cam = os.path.join(pasta_ep(base, e["serie"], e["id"]), "ep.json")
        if os.path.isfile(cam):
            try:
                bk = os.path.join(os.path.dirname(cam), "backups")
                os.makedirs(bk, exist_ok=True)
                velho = _ler(cam)
                if velho.get("cenas"):  # só guarda versão que tinha planos (as gravações de status não enchem a pasta)
                    assin = json.dumps([(c.get("id"), (c.get("video") or {}).get("arquivo"), (c.get("img_inicio") or {}).get("arquivo"))
                                        for c in velho["cenas"]], ensure_ascii=False)
                    ult = sorted(os.listdir(bk))
                    if not ult or _ler(os.path.join(bk, ult[-1])).get("_assin") != assin:
                        velho["_assin"] = assin
                        _gravar(os.path.join(bk, f"ep_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}.json"), velho)
                        for x in sorted(os.listdir(bk))[:-MAX_BACKUPS]:
                            os.remove(os.path.join(bk, x))
            except (OSError, ShortsIAErro, ValueError):
                pass
        _gravar(cam, e)


def _midias_da_cena(pe: str, cn: Dict[str, Any]) -> int:
    return sum(1 for k in ("img_inicio", "video") if _arquivo_ep(pe, (cn or {}).get(k) or {}))


def recuperar_planos(base: str, sid: str, eid: str) -> Dict[str, Any]:
    """🩹 os planos/vídeos sumiram? Pega a versão (atual, ↩ anterior ou um backup) com MAIS imagens/vídeos que ainda existem
    no disco e junta os arquivos órfãos da pasta midia/ (gerados mas fora de qualquer plano) como planos novos."""
    pe = pasta_ep(base, sid, eid)
    with TRAVA:
        e = carregar_ep(base, sid, eid)
        candidatos = [("atual", e.get("cenas") or []), ("anterior", e.get("cenas_anteriores") or [])]
        bk = os.path.join(pe, "backups")
        if os.path.isdir(bk):
            for x in sorted(os.listdir(bk), reverse=True):
                try:
                    candidatos.append((x, _ler(os.path.join(bk, x)).get("cenas") or []))
                except ShortsIAErro:
                    pass
        nome, melhor = max(candidatos, key=lambda c: (sum(_midias_da_cena(pe, cn) for cn in c[1]), len(c[1])))
        cenas = json.loads(json.dumps(melhor))
        usados = {(cn.get(k) or {}).get("arquivo") for cn in cenas for k in ("img_inicio", "img_fim", "video")}
        md = os.path.join(pe, "midia")
        orfaos: Dict[str, Dict[str, str]] = {}
        try:
            fila = {j["id"]: j for j in _foto_da_fila()[0].values()}
        except Exception:  # noqa: BLE001
            fila = {}
        for f in sorted(os.listdir(md)) if os.path.isdir(md) else []:
            m = re.match(r"([0-9a-f]{8})_(img_inicio|img_fim|video)_(.+)\.[a-z0-9]+$", f)
            if not m or f in usados:
                continue
            o = orfaos.setdefault(m.group(1), {})
            if m.group(2) not in o or os.path.getmtime(os.path.join(md, f)) > os.path.getmtime(os.path.join(md, o[m.group(2)])):
                o[m.group(2)] = f
            j = fila.get(m.group(3).split("_")[-1]) or fila.get(m.group(3))
            if j and m.group(2) == "video":
                o["_prompt"] = j.get("prompt") or ""
        ids = {cn.get("id") for cn in cenas}
        novos = 0
        def _quando(o: Dict[str, str]) -> float:
            return min(os.path.getmtime(os.path.join(md, v)) for k, v in o.items() if not k.startswith("_"))
        for cid, o in sorted(orfaos.items(), key=lambda x: _quando(x[1])):  # na ordem em que foram gerados
            alvo = next((cn for cn in cenas if cn.get("id") == cid), None)
            if alvo is None:
                alvo = _nova_cena({"id": cid, "duracao": 8, "acao": "(recuperado) " + o.get("_prompt", "")[:400]}, set(), set())
                cenas.append(alvo)
                novos += 1
            for k in ("img_inicio", "img_fim", "video"):
                if o.get(k) and not _arquivo_ep(pe, alvo.get(k) or {}):
                    alvo[k] = dict(_slot(), estado="pronto", arquivo=o[k], msg="🩹 recuperado")
        if e.get("cenas"):
            e["cenas_anteriores"] = e["cenas"]
        e["cenas"] = cenas
        e["export"] = None
        salvar_ep(base, e)
        return {"de": nome, "planos": len(cenas), "midias": sum(_midias_da_cena(pe, cn) for cn in cenas), "orfaos": novos, "ep": e}


def carregar_ep(base: str, sid: str, eid: str) -> Dict[str, Any]:
    e = _ler(os.path.join(pasta_ep(base, sid, eid), "ep.json"))
    e["edicao"] = normalizar_opcoes(e.get("edicao"))
    return e


def eps_da_serie(base: str, s: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for eid in s.get("eps") or []:
        try:
            out.append(carregar_ep(base, s["id"], eid))
        except ShortsIAErro:
            pass
    return out


def apagar_ep(base: str, sid: str, eid: str) -> None:
    with TRAVA:
        shutil.rmtree(pasta_ep(base, sid, eid), ignore_errors=True)
        s = carregar_serie(base, sid)
        s["eps"] = [x for x in s["eps"] if x != eid]
        for p in s["elenco"]:  # o que só esse capítulo tinha deixado na memória sai junto
            p["historico"] = [x for x in p.get("historico") or [] if x.get("ep") != eid]
        for i in s["ideias"]:
            if i.get("ep") == eid:
                i["ep"] = None
        salvar_serie(base, s)


# ------------------------------------------------------------------ A · o viral: baixar, planos, âncoras
def _ffprobe_dur(v: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", v],
                           capture_output=True, text=True, timeout=60)
        return float((r.stdout or "0").strip() or 0)
    except (subprocess.SubprocessError, ValueError, OSError):
        return 0.0


def _tem_audio(v: str) -> bool:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", v],
                           capture_output=True, text=True, timeout=60)
        return bool((r.stdout or "").strip())
    except (subprocess.SubprocessError, OSError):
        return False


def cortes_de_plano(video: str, limiar: float = 0.32) -> List[float]:
    """Os instantes em que o plano muda (detecção de cena do ffmpeg)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-vf", f"select='gt(scene,{limiar})',showinfo",
                        "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=900)
    return sorted({round(float(m), 3) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr or "")})


def planos(dur: float, cortes: List[float], minimo: float = 0.7, maximo: float = 3.5, teto: int = 30) -> List[Tuple[float, float]]:
    """Os pedaços do vídeo: cada plano; plano longo é dividido (uma âncora a cada ~3 s); curtinho junta com o anterior."""
    pts = [0.0] + [c for c in cortes if 0.0 < c < dur] + [dur]
    brutos: List[List[float]] = []
    inicio_pendente: Optional[float] = None
    for a, b in zip(pts, pts[1:]):
        if inicio_pendente is not None:
            a, inicio_pendente = inicio_pendente, None
        if b - a < minimo:
            if brutos:
                brutos[-1][1] = b
            else:
                inicio_pendente = a  # o 1º plano é curtinho: junta com o seguinte
            continue
        n = max(1, int(round((b - a) / maximo + 0.49))) if b - a > maximo else 1
        passo = (b - a) / n
        for k in range(n):
            brutos.append([a + k * passo, a + (k + 1) * passo])
    if inicio_pendente is not None:
        brutos.append([inicio_pendente, dur])
    while len(brutos) > teto:  # junta o par mais curto
        k = min(range(len(brutos) - 1), key=lambda i: brutos[i + 1][1] - brutos[i][0])
        brutos[k][1] = brutos[k + 1][1]
        del brutos[k + 1]
    return [(round(a, 2), round(b, 2)) for a, b in brutos if b - a > 0.05]


def extrair_quadro(video: str, t: float, destino: str, largura: int = 480) -> Optional[str]:
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.2f}", "-i", video, "-frames:v", "1",
                    "-vf", f"scale={largura}:-2", "-q:v", "3", destino], capture_output=True, timeout=120)
    return destino if os.path.isfile(destino) else None


def folha_de_ancoras(quadros: List[Tuple[int, float, float, str]], destino: str, colunas: int = 5) -> str:
    """As âncoras numeradas numa imagem só (a IA vê o storyboard de uma vez)."""
    from PIL import Image, ImageDraw, ImageFont
    larg = 300
    ims = []
    for n, a, b, c in quadros:
        try:
            im = Image.open(c).convert("RGB")
        except Exception:  # noqa: BLE001
            im = Image.new("RGB", (larg, int(larg * 16 / 9)), (60, 60, 60))
        im = im.resize((larg, max(1, round(im.height * larg / im.width))))
        ims.append((n, a, b, im))
    alt = max(i[3].height for i in ims) + 36
    linhas = (len(ims) + colunas - 1) // colunas
    out = Image.new("RGB", (colunas * (larg + 8), linhas * (alt + 8)), (20, 20, 20))
    dr = ImageDraw.Draw(out)
    try:
        fonte = ImageFont.truetype("DejaVuSans-Bold.ttf", 22)
    except Exception:  # noqa: BLE001
        fonte = ImageFont.load_default()
    for k, (n, a, b, im) in enumerate(ims):
        x, y = (k % colunas) * (larg + 8), (k // colunas) * (alt + 8)
        out.paste(im, (x, y + 36))
        dr.text((x + 4, y + 6), f"#{n}  {a:.1f}–{b:.1f}s", fill=(255, 220, 0), font=fonte)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    out.save(destino, quality=88)
    return destino


STORYBOARD_SCHEMA = _o({
    "resumo": _S, "por_que_viraliza": _S,
    "estrutura": _o({"gancho": _S, "desenvolvimento": _S, "virada": _S, "final": _S}),
    "personagens": _a(_o({"rotulo": _S, "descricao": _S})),
    "momentos": _a(_o({"n": _N, "o_que": _S, "quem": _a(_S), "falas": _a(_o({"quem": _S, "texto": _S})), "emocao": _S, "camera": _S})),
})
STORYBOARD_SYS = (
    "Você analisa um short VIRAL pra que ele seja MODELADO (mesma estrutura e ritmo, outra história e outros personagens). "
    "Você recebe o storyboard: um quadro por plano, numerado (#n com o tempo), e a transcrição com tempos. Para CADA "
    "âncora #n diga: 'o_que' acontece (ação, expressão, objeto, texto na tela), 'quem' aparece (rótulos A, B, C… que você "
    "define em 'personagens' com uma descrição curta de cada pessoa/personagem do vídeo ORIGINAL), 'falas' ditas nesse "
    "pedaço com quem fala (use a transcrição e a boca/posição pra atribuir), 'emocao' e 'camera' (close, plano aberto, "
    "zoom, câmera tremida…). Em 'estrutura', o esqueleto narrativo; em 'por_que_viraliza', os gatilhos (gancho, "
    "identificação, absurdo, loop…). Tudo em português, menos as falas (no idioma original)."
)


def analisar_viral(base: str, sid: str, eid: str, transcrever: Optional[Callable[..., Any]] = None,
                   chamar: Optional[Callable[..., Any]] = None, baixador: Optional[Callable[[str, str], str]] = None,
                   on_log: Callable[[str], None] = lambda _m: None, arquivo: str = "") -> Dict[str, Any]:
    e = carregar_ep(base, sid, eid)
    pe = pasta_ep(base, sid, eid)
    org = e["origem"]
    video = os.path.join(pe, "origem.mp4")
    if arquivo:
        shutil.copyfile(arquivo, video)
    elif not os.path.isfile(video):
        if not org.get("url"):
            raise ShortsIAErro("Cole o link do viral (ou envie o vídeo).")
        on_log("⬇ baixando o viral…")
        import curtos_comentario as CC
        import tempfile
        tmp = tempfile.mkdtemp(prefix="shorts_ia_")
        try:
            cam = CC.baixar_link(org["url"], tmp, baixador)
            shutil.move(cam, video)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    dur = _ffprobe_dur(video)
    if dur <= 0:
        raise ShortsIAErro("Não consegui ler o vídeo.")
    if dur > 180:
        raise ShortsIAErro(f"O vídeo tem {dur:.0f} s — modele um short (até 3 min).")
    segs: List[Dict[str, Any]] = []
    if transcrever and _tem_audio(video):
        on_log("🎙 transcrevendo a fala…")
        wav = os.path.join(pe, "origem.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", wav], capture_output=True, timeout=600)
        try:
            segs = [{"start": round(float(x["start"]), 2), "end": round(float(x["end"]), 2), "text": str(x["text"]).strip()}
                    for x in transcrever(wav, language=None, word_timestamps=False, info={}) or [] if str(x.get("text") or "").strip()]
        except Exception:  # noqa: BLE001 — vídeo sem fala (só música/efeito): segue só com a imagem
            segs = []
    on_log("✂ achando os planos…")
    pl = planos(dur, cortes_de_plano(video))
    qd = os.path.join(pe, "quadros")
    shutil.rmtree(qd, ignore_errors=True)
    quadros = []
    for n, (a, b) in enumerate(pl, 1):
        c = extrair_quadro(video, a + (b - a) * 0.5, os.path.join(qd, f"a{n:02d}.jpg"))
        if c:
            quadros.append((n, a, b, c))
    if not quadros:
        raise ShortsIAErro("Não consegui tirar os quadros do vídeo.")
    sb = [{"n": n, "de": a, "ate": b, "quadro": os.path.basename(c), "o_que": "", "quem": [], "falas": [], "emocao": "", "camera": ""}
          for n, a, b, c in quadros]
    analise = None
    on_log("👁 a IA está lendo o storyboard…")
    import ia_servico
    blocos: List[Dict[str, Any]] = []
    for k in range(0, len(quadros), 15):
        f = folha_de_ancoras(quadros[k:k + 15], os.path.join(qd, f"folha{k // 15 + 1}.jpg"))
        b = ia_servico.imagem_bloco(f, largura=1500)
        if b:
            blocos += [{"type": "text", "text": f"STORYBOARD (folha {k // 15 + 1}):"}, b]
    trans = "\n".join(f"{x['start']:.1f}-{x['end']:.1f} {x['text']}" for x in segs) or "(sem fala — só imagem/música)"
    blocos.append({"type": "text", "text": f"Duração: {dur:.1f} s. Âncoras: " + "; ".join(f"#{x['n']} {x['de']}–{x['ate']}s" for x in sb)
                   + f"\nTRANSCRIÇÃO:\n{trans}"})
    try:
        analise = _ia(STORYBOARD_SYS, blocos, STORYBOARD_SCHEMA, chamar, max_tokens=7000, job=eid)
    except ShortsIAErro as exc:
        on_log(f"⚠ a IA não analisou ({exc}) — o storyboard ficou só com os quadros; dá pra modelar assim mesmo")
    if analise:
        por_n = {int(m.get("n") or 0): m for m in analise.get("momentos") or []}
        for x in sb:
            m = por_n.get(x["n"]) or {}
            x.update(o_que=str(m.get("o_que") or "")[:500], quem=[str(q)[:20] for q in m.get("quem") or []][:6],
                     falas=[{"quem": str(f.get("quem") or "")[:20], "texto": str(f.get("texto") or "")[:400]} for f in m.get("falas") or []][:6],
                     emocao=str(m.get("emocao") or "")[:120], camera=str(m.get("camera") or "")[:120])
    with TRAVA:
        e = carregar_ep(base, sid, eid)
        e["origem"].update(video="origem.mp4", duracao=round(dur, 2), transcricao=segs, storyboard=sb,
                           analise={k: analise.get(k) for k in ("resumo", "por_que_viraliza", "estrutura", "personagens")} if analise else None)
        s = carregar_serie(base, sid)
        ids = [p["id"] for p in s["elenco"]]
        for k, p in enumerate((analise or {}).get("personagens") or []):  # papel sugerido: na ordem do elenco
            rot = str(p.get("rotulo") or "")[:20]
            if rot and rot not in e["papeis"]:
                e["papeis"][rot] = ids[k] if k < len(ids) else ""
        salvar_ep(base, e)
        return e


# ------------------------------------------------------------------ modelar → cenas
CENA_SCHEMA = _o({"momento": _S, "angulo": _S, "continua": {"type": "boolean"}, "continuidade": _S, "beats": _S, "objetos": _a(_S),
                  "quem": _a(_S), "cenario": _S, "duracao": _N, "plano": _S, "acao": _S, "inicio": _S,
                  "fim": _S, "movimento": _S,
                  "falas": _a(_o({"quem": _S, "texto": _S, "emocao": _S})), "base": _a(_N)})
OPCAO = _o({"post": _S, "pt": _S})
NOVO_PERSONAGEM_SCHEMA = _o(dict(PERSONAGEM_SCHEMA["properties"], id=_S, fixo={"type": "boolean"}))
CENAS_SCHEMA = _o({"titulo": _S, "titulos": _a(OPCAO), "logica": _S, "novos_personagens": _a(NOVO_PERSONAGEM_SCHEMA),
                   "resumo": _S, "memoria": _a(_o({"quem": _S, "fato": _S})), "cenas": _a(CENA_SCHEMA)})
REGRA_FALA = (
    "ESCRITA DAS FALAS (vão ser FALADAS por uma IA — escreva pro ouvido): frases curtas e naturais, como gente de verdade "
    "fala no idioma do post (no português: português do Brasil do dia a dia); pontuação marca as pausas (vírgula, "
    "reticências, ponto de exclamação/interrogação); nada de caixa alta, emoji, símbolo, sigla, número em algarismo "
    "(escreva por extenso), palavra estrangeira ou trava-língua. NADA de honoríficos e expressões japonesas — sem -san, "
    "-chan, -kun, -sama, senpai, sensei, onii-chan, nee-chan, 'ara ara', 'nani', 'sugoi', 'kawaii', 'baka', "
    "'itadakimasu', 'gomen': adapte pro jeito brasileiro (ex.: 'ara ara' → 'ai, ai, ai…' / 'olha só'; 'Sora-san' → "
    "'Sora' ou 'moço'; 'obaa-chan' → 'vó') mantendo os NOMES dos personagens. Onomatopeia só simples ('ai!', 'ué?', "
    "'hã?'); risada escrita 'haha'. Nada que a IA possa ler errado.\n"
)
CENAS_SYS = (
    "Você é o diretor de uma série de shorts de anime feita com IA (imagens e vídeos gerados). Escreva o EPISÓDIO em "
    "PLANOS. Cada plano vira UM vídeo curto no gerador (com as falas faladas e a boca sincronizada), e a edição corta "
    "entre eles como num anime de verdade.\n"
    "{MODO}\n" + REGRA_FALA +
    "MOMENTOS E ÂNGULOS (o que faz parecer filmado, não um slide atrás do outro):\n"
    "• Agrupe os planos em MOMENTOS ('momento' = um nome curto igual pra todos os planos do mesmo momento, ex.: "
    "'M1 · a melancia'). Um momento = o mesmo lugar e o mesmo instante, coberto por 2 a 4 ÂNGULOS diferentes que se "
    "encaixam em sequência contínua: plano de situação → close de quem fala → contraplano/reação de quem ouve → "
    "detalhe (mãos, objeto) → POV. Cada plano CONTINUA a ação exatamente de onde o anterior parou (como os cortes de "
    "uma mesma cena filmada com várias câmeras).\n"
    "• 'angulo' (INGLÊS, curto): wide establishing / medium two-shot / close-up on <nome> / over-the-shoulder from <nome> / "
    "reaction close-up on <nome> / insert detail of <objeto> / low-angle POV of <nome>…\n"
    "• CONTINUIDADE dentro do momento: mesmo lugar, mesma hora/luz, mesmas roupas, mesmas posições (regra dos 180°: quem "
    "está à esquerda continua à esquerda); repita no 'inicio' de cada plano o lugar, a luz e onde cada um está.\n"
    "• Entre momentos: muda o lugar ou o tempo (um corte maior; a edição põe uma transição).\n"
    "• 'continuidade' (INGLÊS, DETALHADO, o MESMO texto em todos os planos do momento — só atualize o que mudou): a "
    "'bíblia' do momento — o lugar com a planta (onde fica a porta, a janela, a mesa, a cerca…), a hora e a direção da "
    "luz, o clima, onde cada personagem está e pra que lado olha, a roupa e o estado de cada um (chapéu na cabeça, "
    "sujo de terra…), os objetos e com quem estão (o microfone na mão da Mame). É o que mantém os planos iguais entre si.\n"
    "• 'beats' (INGLÊS): a ação do plano em tempos, preenchendo os {DUR} s do vídeo — ex. (6 s): '0-2s: Mame peeks "
    "through the fence hole; 2-4s: she crawls in on all fours, eyes wide; 4-6s: she spots the fluffy microphone and "
    "freezes, pointing'. Cada beat com uma ação clara e visível.\n"
    "• 'objetos': ids dos OBJETOS QUE SE REPETEM que aparecem no plano (a imagem de referência deles vai junto).\n"
    "• OBJETOS e ROUPAS que se repetem: descreva SEMPRE com as MESMAS palavras, em todo plano e todo momento (ex.: 'a "
    "fluffy gray furry windscreen microphone on a short black handle' — nunca 'microfone' num plano e 'gravador' no "
    "outro). Roupa = a da aparência do personagem, igual.\n"
    "• 'continua' = true quando o plano é a MESMA câmera continuando o plano anterior do mesmo momento (a ação segue sem "
    "corte de ângulo) — o vídeo começa do último quadro do anterior. false quando muda o ângulo.\n"
    "Regras dos planos:\n"
    "• {N_PLANOS} planos; 'duracao' de cada plano = {DUR} s (o vídeo do gerador tem {DUR} s): escreva ação e reação que "
    "preencham o plano inteiro (sem ficar parado esperando).\n"
    "• Todo plano tem um personagem fazendo algo (ou um detalhe de objeto ligado à ação). NADA de plano só de paisagem "
    "vazia, a não ser UM plano de situação curto no começo de um momento — e mesmo ele com alguém entrando/se mexendo.\n"
    "• O 1º plano já é o gancho com AÇÃO (alguém entra, cai, grita, rouba algo) — nunca alguém parado sentado.\n"
    "• Atuação de anime: poses claras, expressões grandes, reações cômicas exageradas, gestos legíveis.\n"
    "• Gancho nos 2 primeiros segundos (o 1º plano já começa no conflito/na curiosidade). Final com punchline, "
    "momento fofo ou loop.\n"
    "• 'quem': ids dos personagens que APARECEM no plano (no máximo 3; em close, 1). Cada personagem age e fala do "
    "jeito dele (personalidade/jeito de falar), com os bordões quando couber.\n"
    "• 'cenario': id do cenário (ou '' se for um lugar novo — então descreva o lugar no 'inicio').\n"
    "• 'falas': curtas (até ~2,5 palavras por segundo do plano; no máximo 1 fala por plano de {DUR} s — a outra pessoa "
    "responde no PRÓXIMO plano, no contraplano), no idioma do post, 'quem' = id, 'emocao' em inglês (1–3 palavras). "
    "Plano de reação/detalhe: falas = [].\n"
    "• 'inicio' (INGLÊS): o PRIMEIRO quadro do plano como imagem parada — o ângulo da câmera, quem está onde, pose, "
    "expressão, objetos, o lugar, a luz. Cite os personagens pelo NOME. Sem texto/balão.\n"
    "• 'fim' (INGLÊS, opcional): como o plano termina, se muda bem (vai no texto do vídeo). Senão ''.\n"
    "• Plano com FALA: acústica calma (dentro de casa, varanda, loja…). Vento forte, chuva, debaixo d'água, multidão "
    "MUDAM o timbre da voz no gerador — use só em plano sem fala ou quando a história pede.\n"
    "• 'movimento' (INGLÊS): o que se mexe e a câmera (leve, cinematográfica: slow push-in, handheld sutil, pan).\n"
    "• 'plano' (português): o tipo do plano (aberto, médio, close, detalhe, POV).\n"
    "• 'base': números das âncoras do viral que esse plano modela ([] se não houver).\n"
    "PERSONAGENS NOVOS: use o elenco sempre que der. Se a história PRECISA de alguém que não existe (um vizinho, um "
    "colega, um bicho), crie em 'novos_personagens' com 'id' N1, N2… (use esses ids em 'quem' e nas falas), perfil "
    "completo (aparência/voz em inglês, o resto em português) e 'fixo' = true se ele pode voltar em outros episódios.\n"
    "• 'titulos': 5 títulos do post ('post' no idioma do post; 'pt' em português), curtos, com curiosidade.\n"
    "• 'logica': 1–2 frases (português) de como o episódio prende.\n"
    "• 'resumo': 1–2 frases (português) do que ACONTECEU neste capítulo (vai pra linha do tempo da série).\n"
    "• 'memoria': os fatos NOVOS e duradouros que os próximos capítulos devem lembrar, por personagem (id) — o que ele "
    "aprendeu, ganhou, quebrou, descobriu, um medo, uma amizade nova… (curtos, português; [] se nada mudou).\n"
    "Personagens 100% originais da série; nunca cite obra, estúdio ou personagem existente. Criança sempre em "
    "situação inocente e segura; nunca romance/sexual."
)
MODO_VIRAL = ("MODELAGEM de um viral: mantenha a ESTRUTURA, o ritmo dos planos, o tipo de virada e o final do vídeo "
              "original, mas com o ELENCO DA SÉRIE no lugar das pessoas (use o mapa de papéis) e falas NOVAS no tom da "
              "série — modelar, não copiar: nada de repetir as falas originais palavra por palavra.")
MODO_IDEIA = "EPISÓDIO A PARTIR DE UMA IDEIA da série (sem vídeo de referência)."


def _conteudo_modelar(s: Dict[str, Any], e: Dict[str, Any], base: str = "") -> str:
    org = e["origem"]
    partes = [contexto_serie(s, base)]
    if org.get("storyboard"):
        an = org.get("analise") or {}
        partes.append(f"VIRAL ORIGINAL ({org.get('duracao')} s): {an.get('resumo') or ''}\nPOR QUE VIRALIZA: {an.get('por_que_viraliza') or ''}\n"
                      f"ESTRUTURA: {json.dumps(an.get('estrutura') or {}, ensure_ascii=False)}\n"
                      f"PESSOAS DO ORIGINAL: {json.dumps(an.get('personagens') or [], ensure_ascii=False)}\n"
                      f"MAPA DE PAPÉIS (original → elenco da série): {json.dumps(e.get('papeis') or {}, ensure_ascii=False)}")
        linhas = []
        for x in org["storyboard"]:
            fal = " / ".join(f"{f['quem']}: {f['texto']}" for f in x.get("falas") or [])
            linhas.append(f"#{x['n']} {x['de']}–{x['ate']}s · {x.get('camera') or ''} · {', '.join(x.get('quem') or [])} · "
                          f"{x.get('o_que') or ''}" + (f" · falas: {fal}" if fal else "") + (f" · {x['emocao']}" if x.get("emocao") else ""))
        partes.append("STORYBOARD:\n" + "\n".join(linhas))
        if org.get("transcricao") and not any(x.get("falas") for x in org["storyboard"]):
            partes.append("TRANSCRIÇÃO:\n" + "\n".join(f"{t['start']:.1f}-{t['end']:.1f} {t['text']}" for t in org["transcricao"]))
    elif org.get("capitulo"):
        c = org["capitulo"]
        partes.append(f"PREMISSA DESTE CAPÍTULO: {c.get('titulo')}\nLOGLINE: {c.get('logline')}\nGANCHO: {c.get('gancho')}\n"
                      f"DESENVOLVIMENTO: {c.get('desenvolvimento')}\nVIRADA: {c.get('virada')}\nFINAL: {c.get('final')}\n"
                      f"QUEM: {', '.join(c.get('quem') or [])}\nCONTINUIDADE: {c.get('continuidade') or ''}\nTOM: {c.get('tom') or ''}")
    elif org.get("ideia"):
        i = org["ideia"]
        partes.append(f"IDEIA: {i['titulo']} · formato: {i.get('formato')}\nSINOPSE: {i.get('sinopse')}\nGANCHO: {i.get('gancho')}\n"
                      f"QUEM: {', '.join(i.get('quem') or [])}")
    else:
        partes.append(f"TEMA DO EPISÓDIO: {e.get('titulo')}")
    if org.get("notas"):
        partes.append(f"PEDIDO DO CRIADOR PRA ESTE EPISÓDIO: {org['notas']}")
    return "\n\n".join(partes)


_JP_SUFIXOS = re.compile(r"(?<=\w)-(?:san|chan|kun|sama|senpai|sensei|dono|tan|chin)\b", re.I)
_JP_EXPR = [(re.compile(p, re.I), b) for p, b in (
    (r"\bara[\s,]*ara\b", "ai, ai, ai"), (r"\b(?:obaa|baa|oba)-?(?:chan|san|sama)\b", "vó"),
    (r"\b(?:ojii|jii|oji)-?(?:chan|san|sama)\b", "vô"), (r"\b(?:onii|nii)-?(?:chan|san|sama)\b", "mano"),
    (r"\b(?:onee|nee)-?(?:chan|san|sama)\b", "mana"),
    (r"\bitadakimasu\b", "bom apetite"), (r"\bgomen(?:nasai)?\b", "desculpa"), (r"\barigat(?:ou|o)(?:\s+gozaimasu)?\b", "obrigado"),
    (r"\bsugoi\b", "que demais"), (r"\bkawaii\b", "que fofo"), (r"\bnani\b", "o quê"), (r"\bbaka\b", "bobo"),
    (r"\bsumimasen\b", "com licença"), (r"\bohayou?\b", "bom dia"), (r"\bkonnichiwa\b", "oi"), (r"\bsenpai\b", ""),
    (r"\bsensei\b", "professor"))]


def limpar_fala(texto: str) -> str:
    """🗣 tira honorífico/expressão japonesa que a voz lê errado ("Sora-san" → "Sora", "ara ara" → "ai, ai, ai")."""
    t = str(texto or "")
    for rx, troca in _JP_EXPR:
        t = rx.sub(troca, t)
    t = _JP_SUFIXOS.sub("", t)
    t = re.sub(r"\s+([,.!?…])", r"\1", re.sub(r"\s{2,}", " ", t)).strip(" ,")
    t = re.sub(r"^([,.;:]\s*)+", "", t)
    return t[:1].upper() + t[1:] if t else t


def nomes_citados(s: Dict[str, Any], cn: Dict[str, Any]) -> List[str]:
    """👥 os personagens citados pelo NOME no texto do plano (início, ação, ângulo, falas) — entram em 'quem' (sem a ficha
    deles o gerador inventa outra pessoa)."""
    texto = " ".join(str(cn.get(k) or "") for k in ("inicio", "acao", "angulo", "movimento", "fim")).lower()
    out = []
    for p in s["elenco"]:
        partes = [x for x in re.split(r"\s+", p["nome"].lower()) if len(x) >= 3]
        if any(re.search(r"\b" + re.escape(x) + r"\b", texto) for x in partes):
            out.append(p["id"])
    return out


def _completar_quem(s: Dict[str, Any], cn: Dict[str, Any]) -> None:
    quem = list(cn.get("quem") or [])
    for f in cn.get("falas") or []:
        if f.get("quem") and f["quem"] not in quem:
            quem.append(f["quem"])
    for q in nomes_citados(s, cn):
        if q not in quem:
            quem.append(q)
    cn["quem"] = quem[:MAX_REFS_CENA]


def _nova_cena(c: Dict[str, Any], ids_el: set, ids_ce: set) -> Dict[str, Any]:
    g = lambda k, n: " ".join(str(c.get(k) or "").split())[:n]  # noqa: E731
    try:
        dur = max(2.0, min(DUR_VIDEO_FLOW, float(c.get("duracao") or 6)))
    except (TypeError, ValueError):
        dur = 6.0
    quem = []
    for q in c.get("quem") or []:
        if q in ids_el and q not in quem:
            quem.append(q)
    falas = []
    for f in (c.get("falas") or [])[:3]:
        t = limpar_fala(" ".join(str(f.get("texto") or "").split())[:300])
        if t:
            falas.append({"quem": f.get("quem") if f.get("quem") in ids_el else (quem[0] if quem else ""), "texto": t,
                          "emocao": " ".join(str(f.get("emocao") or "").split())[:40]})
    return {"id": c.get("id") or _id(), "momento": g("momento", 60), "angulo": g("angulo", 120),
            "objetos": [str(x)[:8] for x in c.get("objetos") or [] if re.fullmatch(r"O\d+", str(x))][:3],
            "continuidade": g("continuidade", 1800), "beats": g("beats", 1200), "legenda": g("legenda", 600),
            "continua": c.get("continua") is True or str(c.get("continua")).lower() in ("1", "true", "on", "sim"),
            "quem": quem[:MAX_REFS_CENA], "cenario": c.get("cenario") if c.get("cenario") in ids_ce else "",
            "duracao": round(dur, 1), "plano": g("plano", 80), "acao": g("acao", 600), "inicio": g("inicio", 1500),
            "fim": g("fim", 1200), "movimento": g("movimento", 800), "falas": falas,
            "base": [int(x) for x in (c.get("base") or []) if isinstance(x, (int, float))][:6],
            "img_inicio": c.get("img_inicio") if isinstance(c.get("img_inicio"), dict) else _slot(),
            "img_fim": c.get("img_fim") if isinstance(c.get("img_fim"), dict) else _slot(),
            "video": c.get("video") if isinstance(c.get("video"), dict) else _slot(),
            "corte": c.get("corte") if isinstance(c.get("corte"), dict) else {"ini": 0.0, "fim": None}}


def modelar(base: str, sid: str, eid: str, notas: Optional[str] = None, chamar: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    s = carregar_serie(base, sid)
    if not s["elenco"]:
        raise ShortsIAErro("A série ainda não tem elenco — crie no 🌌 universo.")
    with TRAVA:
        e = carregar_ep(base, sid, eid)
        if notas is not None:
            e["origem"]["notas"] = str(notas).strip()[:1500]
            salvar_ep(base, e)
    modo = MODO_VIRAL if e["origem"].get("storyboard") else MODO_IDEIA
    dur = float(e.get("dur_plano") or s["padroes"]["dur_plano"])
    n_planos = "8 a 14" if dur <= 6.5 else "6 a 10"
    sistema = CENAS_SYS.replace("{MODO}", modo).replace("{DUR}", f"{dur:g}").replace("{N_PLANOS}", n_planos)
    r = _ia(sistema, _conteudo_modelar(s, e, base), CENAS_SCHEMA, chamar, max_tokens=12000, timeout=280, job=eid)
    novos = registrar_novos_personagens(base, sid, eid, r.get("novos_personagens") or [])
    for c in r.get("cenas") or []:  # N1, N2… → os ids de verdade no elenco
        c["quem"] = [novos.get(q, q) for q in c.get("quem") or []]
        for f in c.get("falas") or []:
            f["quem"] = novos.get(f.get("quem"), f.get("quem"))
    s = carregar_serie(base, sid)
    ids_el, ids_ce = {p["id"] for p in s["elenco"]}, {c["id"] for c in s["cenarios"]}
    cenas = [_nova_cena(c, ids_el, ids_ce) for c in (r.get("cenas") or [])[:18]]
    for cn in cenas:
        _completar_quem(s, cn)
    if not cenas:
        raise ShortsIAErro("A IA não devolveu nenhuma cena — tente de novo.")
    with TRAVA:
        e = carregar_ep(base, sid, eid)
        if e["cenas"]:
            e["cenas_anteriores"] = e["cenas"]  # ↩ dá pra voltar
        e["cenas"] = cenas
        if r.get("titulo") and (e["titulo"] in ("", "Novo episódio") or e["origem"]["tipo"] == "viral"):
            e["titulo"] = str(r["titulo"])[:140]
        e["titulos"] = [{"post": str(t.get("post") or "")[:200], "pt": str(t.get("pt") or "")[:200]} for t in r.get("titulos") or []][:8]
        e["logica"] = str(r.get("logica") or "")[:600]
        e["novos_personagens"] = sorted(set(novos.values()) | set(e.get("novos_personagens") or []))
        e["resumo"] = str(r.get("resumo") or "")[:600]
        e["export"] = None
        salvar_ep(base, e)
    guardar_memoria(base, sid, eid, [{"quem": novos.get(m.get("quem"), m.get("quem")), "fato": m.get("fato")} for m in r.get("memoria") or []])
    return e


def guardar_memoria(base: str, sid: str, eid: str, fatos: List[Dict[str, Any]]) -> None:
    """🧠 o histórico dos personagens: os fatos deste capítulo substituem os que ele já tinha deixado (re-modelar não duplica)."""
    with TRAVA:
        s = carregar_serie(base, sid)
        for p in s["elenco"]:
            p["historico"] = [x for x in p.get("historico") or [] if x.get("ep") != eid]
        for f in fatos[:20]:
            p = item(s, str(f.get("quem") or ""))
            fato = " ".join(str(f.get("fato") or "").split())[:200]
            if p and fato and p["id"].startswith("P"):
                p.setdefault("historico", []).append({"fato": fato, "ep": eid})
                p["historico"] = p["historico"][-40:]
        salvar_serie(base, s)


# ------------------------------------------------------------------ 📖 novo capítulo: premissa → episódio
CAPITULO_SCHEMA = _o({"titulo": _S, "logline": _S, "gancho": _S, "desenvolvimento": _S, "virada": _S, "final": _S, "quem": _a(_S),
                      "novos_personagens": _a(NOVO_PERSONAGEM_SCHEMA), "continuidade": _S, "tom": _S})
CAPITULO_SYS = (
    "Você é o roteirista-chefe de uma série de shorts de anime feita com IA. Escreva a PREMISSA do próximo capítulo "
    "(20 a 60 s de vídeo), em português:\n"
    "• 'titulo' curto; 'logline' (1 frase: quem quer o quê e o que atrapalha); 'gancho' (o que acontece/é dito nos 2 "
    "primeiros segundos); 'desenvolvimento' (2–3 frases); 'virada' (a surpresa); 'final' (punchline, momento fofo ou "
    "gancho pro próximo); 'tom' (o clima deste capítulo).\n"
    "• 'quem': ids do elenco que entram (use os que o criador marcou; pode chamar mais se a história pedir).\n"
    "• Personalidade, relações e o HISTÓRICO de cada personagem valem sempre: nada de contradizer o que já aconteceu.\n"
    "• {FORMATO}\n"
    "• 'continuidade': o que este capítulo herda dos anteriores (ou 'independente').\n"
    "• {NOVOS}\n" + REGRA_FALA +
    "Personagens originais; criança sempre em situação inocente e segura; nunca romance/sexual."
)


def gerar_premissa_capitulo(base: str, sid: str, ideia: str = "", quem: Optional[List[str]] = None, pode_novos: bool = True,
                            chamar: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """📖 a premissa do próximo capítulo (você edita antes de virar episódio)."""
    s = carregar_serie(base, sid)
    if not s["elenco"]:
        raise ShortsIAErro("Crie o elenco primeiro.")
    fmt = s.get("formato_serie") or "episodica"
    sistema = (CAPITULO_SYS
               .replace("{FORMATO}", "A série é CONTÍNUA: comece de onde o último capítulo parou." if fmt == "continua"
                        else "A série é EPISÓDICA: o capítulo se fecha sozinho (não precisa ter visto os outros).")
               .replace("{NOVOS}", "Pode criar personagens NOVOS em 'novos_personagens' (id N1, N2…, perfil completo: aparência/voz/"
                        "gênero em inglês, o resto em português; 'fixo' = se ele volta) — só se a história pedir." if pode_novos
                        else "NÃO crie personagens novos: 'novos_personagens' = []."))
    marcados = [p["nome"] for p in s["elenco"] if p["id"] in (quem or [])]
    texto = (contexto_serie(s, base) + f"\n\nIDEIA DO CRIADOR PRA ESTE CAPÍTULO: {ideia.strip() or '(livre — surpreenda, no tom da série)'}"
             + (f"\nPERSONAGENS QUE ELE QUER: {', '.join(marcados)}" if marcados else ""))
    r = _ia(sistema, texto, CAPITULO_SCHEMA, chamar, max_tokens=4000, timeout=150)
    ids = {p["id"] for p in s["elenco"]}
    novos = [n for n in r.get("novos_personagens") or [] if str(n.get("nome") or "").strip()][:4] if pode_novos else []
    tids = {str(n.get("id")) for n in novos}
    return {k: str(r.get(k) or "")[:800] for k in ("titulo", "logline", "gancho", "desenvolvimento", "virada", "final", "continuidade", "tom")} | {
        "quem": [q for q in r.get("quem") or [] if q in ids or q in tids][:8], "novos_personagens": novos, "ideia": ideia[:1500]}


def criar_capitulo(base: str, sid: str, premissa: Dict[str, Any]) -> Dict[str, Any]:
    """🎬 a premissa (editada por você) vira um episódio; os personagens novos entram no elenco e já pedem as fichas."""
    if not str(premissa.get("titulo") or "").strip():
        raise ShortsIAErro("A premissa precisa de um título.")
    e = novo_ep(base, sid, premissa["titulo"])
    mapa = registrar_novos_personagens(base, sid, e["id"], premissa.get("novos_personagens") or [])
    cap = {k: " ".join(str(premissa.get(k) or "").split())[:800]
           for k in ("titulo", "logline", "gancho", "desenvolvimento", "virada", "final", "continuidade", "tom", "ideia")}
    cap["quem"] = [mapa.get(q, q) for q in premissa.get("quem") or []]
    with TRAVA:
        e = carregar_ep(base, sid, e["id"])
        e["origem"].update(tipo="capitulo", capitulo=cap)
        e["novos_personagens"] = sorted(set(mapa.values()))
        salvar_ep(base, e)
    return e


def registrar_novos_personagens(base: str, sid: str, eid: str, lista: List[Dict[str, Any]]) -> Dict[str, str]:
    """👤 os personagens que a história pediu e não existiam: entram no elenco (com a estreia marcada) e já pedem
    🧍 referência → 📋 ficha → 🎙 voz no Flow (sozinho, em sequência). → {"N1": "P5", …}"""
    mapa: Dict[str, str] = {}
    if not lista:
        return mapa
    with TRAVA:
        s = carregar_serie(base, sid)
        por_nome = {p["nome"].lower(): p for p in s["elenco"]}
        for n in lista[:6]:
            tid = str(n.get("id") or "")
            nome = " ".join(str(n.get("nome") or "").split())
            if not nome:
                continue
            ja = por_nome.get(nome.lower())
            if ja:
                mapa[tid] = ja["id"]
                continue
            if len(s["elenco"]) >= MAX_ELENCO:
                break
            p = _personagem(n, _proximo("P", s["elenco"]))
            p.update(estreia=eid, fixo=bool(n.get("fixo", True)), preparar=bool(s["padroes"].get("auto_preparar")))
            s["elenco"].append(p)
            por_nome[nome.lower()] = p
            mapa[tid] = p["id"]
        salvar_serie(base, s)
    novos = [pid for pid in mapa.values() if (item(carregar_serie(base, sid), pid) or {}).get("preparar")]
    if novos:
        try:
            pedir_refs(base, sid, novos)
        except Exception:  # noqa: BLE001 — Flow fora: os botões da série fazem depois
            pass
    return mapa


def salvar_cenas(base: str, sid: str, eid: str, cenas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Você editou as cenas (falas, prompts, quem, duração, ordem) — guarda. Imagens/vídeos já gerados continuam."""
    s = carregar_serie(base, sid)
    ids_el, ids_ce = {p["id"] for p in s["elenco"]}, {c["id"] for c in s["cenarios"]}
    with TRAVA:
        e = carregar_ep(base, sid, eid)
        if not cenas and e["cenas"]:  # 🛡 a página mandou a lista vazia (erro de tela): nunca apaga os planos assim
            raise ShortsIAErro("Não salvei: a lista de planos veio vazia (o episódio continua como estava).")
        velhas = {c["id"]: c for c in e["cenas"]}
        novas = []
        for c in cenas[:14]:
            v = velhas.get(str(c.get("id") or ""))
            base_c = dict(v or {}, **{k: c[k] for k in c if k not in ("img_inicio", "img_fim", "video")})
            if isinstance(c.get("corte"), dict):
                try:
                    ini = max(0.0, float(c["corte"].get("ini") or 0))
                    fim = c["corte"].get("fim")
                    base_c["corte"] = {"ini": round(ini, 2), "fim": None if fim in (None, "") else round(max(ini + 0.5, float(fim)), 2)}
                except (TypeError, ValueError):
                    base_c["corte"] = (v or {}).get("corte") or {"ini": 0.0, "fim": None}
            n = _nova_cena(base_c, ids_el, ids_ce)
            if v:
                for k in ("inicio", "fim"):  # o prompt da imagem mudou: a imagem velha fica, marcada como "desatualizada"
                    slot = "img_" + k
                    if n[k] != v.get(k) and (n[slot] or {}).get("arquivo"):
                        n[slot] = dict(n[slot], desatualizada=True)
            novas.append(n)
        e["cenas"] = novas
        e["export"] = None
        salvar_ep(base, e)
        return e


def voltar_cenas(base: str, sid: str, eid: str) -> Dict[str, Any]:
    with TRAVA:
        e = carregar_ep(base, sid, eid)
        if not e.get("cenas_anteriores"):
            raise ShortsIAErro("Não há versão anterior.")
        e["cenas"], e["cenas_anteriores"] = e["cenas_anteriores"], e["cenas"]
        salvar_ep(base, e)
        return e


# ------------------------------------------------------------------ prompts do Flow
def prompt_ref_personagem(s: Dict[str, Any], p: Dict[str, Any]) -> str:
    return (f"{ESTILOS[s['estilo']]['prompt']}. Character design reference sheet of ONE original character named {p['nome']}: "
            f"{p['aparencia']}. Full body, front view, standing in a neutral relaxed pose, arms slightly away from the body, "
            "neutral friendly expression, centered, whole figure visible from head to toe, plain flat light gray background, "
            "even soft studio lighting, no other characters, no text, no logo, no watermark.")


def prompt_ref_com_foto(s: Dict[str, Any], p: Dict[str, Any], n_fotos: int) -> str:
    """🧍 com a foto: a(s) imagem(ns) de inspiração vão como REFERÊNCIA — o personagem sai parecido com elas, redesenhado no
    estilo da série e com a roupa/aparência do perfil."""
    paineis = (f"The reference image shows {n_fotos} numbered panels of the same character." if n_fotos > 1 else "")
    return (f"{ESTILOS[s['estilo']]['prompt']}. Character design reference sheet of ONE character named {p['nome']}, based on "
            f"the person in the reference image. {paineis} Keep the same face shape, facial features, hairstyle, hair color, "
            "eye shape, skin tone, age and body type as the reference, redrawn cleanly in this series' art style. "
            f"Character details: {p['aparencia']}. Full body, front view, standing in a neutral relaxed pose, arms slightly "
            "away from the body, neutral friendly expression, centered, whole figure visible from head to toe, plain flat "
            "light gray background, even soft studio lighting, no other characters, no text, no logo, no watermark.")[:3800]


def prompt_ficha_personagem(s: Dict[str, Any], p: Dict[str, Any]) -> str:
    """📋 a FOLHA DE PERSONAGEM (character sheet) a partir da referência travada: várias vistas + expressões + os dados
    escritos (nome, gênero, idade, altura). O vídeo lê isso e mantém o rosto/corpo — e o gênero explícito evita o Flow
    "trocar" a personagem (acontece)."""
    dados = [f"NAME: {p['nome'].upper()}"]
    if p.get("genero"):
        dados.append(f"GENDER: {p['genero'].upper()}")
    if p.get("idade"):
        dados.append(f"AGE: {p['idade']}")
    if p.get("altura"):
        dados.append(f"HEIGHT: {p['altura']}")
    genero = f" The character is {p['genero']} — keep the same gender." if p.get("genero") else ""
    return (f"{ESTILOS[s['estilo']]['prompt']}. CHARACTER SHEET (model sheet) of the EXACT same character as the reference "
            f"image ({p['nome']}): {p['aparencia']}.{genero} Layout on a clean light gray background: full body front view, "
            "three-quarter view, side profile and back view standing in a row, same scale, same outfit and colors in every "
            "view; plus a row of 4 head close-ups with expressions (neutral, happy, angry, surprised). A small clean text "
            f"label area with: {' · '.join(dados)}. Do not change the face, hair, eye color, outfit or proportions. No "
            "other characters, no scenery, no watermark.")[:3800]


def prompt_ref_cenario(s: Dict[str, Any], c: Dict[str, Any], com_estilo: bool = False) -> str:
    estilo = (" The reference image is ONLY a STYLE reference: match its art style EXACTLY — same lineart thickness, same "
              "flat cel shading, same color palette and saturation, same simplicity and level of detail — so this "
              "background looks like it belongs to the same anime as that image. Do NOT draw the character or any person "
              "from the reference." if com_estilo else "")
    return (f"{ESTILOS[s['estilo']]['prompt']}. Anime background art of an empty location ({c['nome']}): {c['descricao']}. "
            f"Establishing view, no characters, no people, no text, no logo.{estilo}")[:3800]


def prompt_ref_objeto(s: Dict[str, Any], o: Dict[str, Any], com_estilo: bool = False) -> str:
    estilo = (" The reference image is ONLY a STYLE reference: match its art style exactly (lineart, flat cel shading, "
              "palette). Do NOT draw the character from it." if com_estilo else "")
    return (f"{ESTILOS[s['estilo']]['prompt']}. Prop design reference sheet of ONE object ({o['nome']}): {o['descricao']}. "
            "Shown alone, centered, front view and a three-quarter view side by side, plain flat light gray background, "
            f"no people, no hands, no text, no logo.{estilo}")[:3800]


def ancora_estilo(base: str, s: Dict[str, Any]) -> Optional[str]:
    """🎨 a imagem que dita o TRAÇO da série (cenários e tudo mais seguem ela): a que você escolheu, senão a 📋 ficha /
    🧍 referência do 1º personagem que tiver."""
    if s.get("estilo_ref"):
        c = os.path.join(pasta_serie(base, s["id"]), "refs", os.path.basename(s["estilo_ref"]))
        if os.path.isfile(c):
            return c
    for p in s["elenco"]:
        c = caminho_ref(base, s, p)
        if c:
            return c
    return None


def guardar_estilo_ref(base: str, sid: str, origem: Optional[str], de_personagem: str = "") -> Optional[str]:
    """🎨 escolhe a imagem de estilo: um arquivo seu, a referência de um personagem (`de_personagem`) ou nada (volta ao padrão)."""
    from PIL import Image
    with TRAVA:
        s = carregar_serie(base, sid)
        nome = None
        if de_personagem:
            c = caminho_ref(base, s, item(s, de_personagem))
            if not c:
                raise ShortsIAErro("Esse personagem ainda não tem referência.")
            nome = os.path.basename(c)
        elif origem:
            nome = f"estilo_{secrets.token_hex(3)}.png"
            try:
                Image.open(origem).convert("RGB").save(os.path.join(pasta_refs(base, sid), nome))
            except Exception as exc:  # noqa: BLE001
                raise ShortsIAErro("Não consegui abrir essa imagem.") from exc
        s["estilo_ref"] = nome
        salvar_serie(base, s)
        return nome


def objetos_do_plano(s: Dict[str, Any], cena: Dict[str, Any]) -> List[Dict[str, Any]]:
    """🧸 os objetos que se repetem neste plano: os marcados + os citados pelo NOME no texto."""
    texto = " ".join(str(cena.get(k) or "") for k in ("inicio", "acao", "beats", "continuidade", "movimento", "fim")).lower()
    out = []
    for o in s.get("objetos") or []:
        if o["id"] in (cena.get("objetos") or []) or (len(o["nome"]) >= 3 and o["nome"].lower() in texto):
            out.append(o)
    return out


def refs_da_cena(base: str, s: Dict[str, Any], cena: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(rótulo, arquivo) das referências do plano: até 2 personagens, o 🧸 objeto que se repete, o cenário — máx. 3
    (a imagem do plano anterior entra depois, se couber)."""
    out: List[Tuple[str, str]] = []
    objs = [(f"object: {o['nome']}", caminho_ref(base, s, o)) for o in objetos_do_plano(s, cena)]
    objs = [x for x in objs if x[1]]
    vagas_p = MAX_REFS_CENA - (1 if objs else 0)
    for q in cena.get("quem") or []:
        p = item(s, q)
        c = caminho_ref(base, s, p)
        if p and c and len(out) < vagas_p:
            out.append((p["nome"], c))
    for o in objs:
        if len(out) < MAX_REFS_CENA:
            out.append(o)
    if cena.get("cenario") and len(out) < MAX_REFS_CENA:
        c = caminho_ref(base, s, item(s, cena["cenario"]))
        if c:
            out.append(("location", c))
    return out


def _proporcao_txt(s: Dict[str, Any]) -> str:
    return {"9:16": "vertical 9:16 frame", "1:1": "square 1:1 frame", "16:9": "horizontal 16:9 frame"}[s["proporcao"]]


def prompt_imagem_cena(s: Dict[str, Any], cena: Dict[str, Any], qual: str, refs: List[Tuple[str, str]]) -> str:
    texto = cena["fim"] if qual == "fim" else cena["inicio"]
    pers = [item(s, q) for q in cena.get("quem") or []]
    desc = " ".join(f"{p['nome']}: {p['aparencia']}." + (f" ALWAYS visible on {p['nome']}: {p['detalhes']}." if p.get("detalhes") else "")
                    for p in pers if p)
    lugar = item(s, cena["cenario"]) if cena.get("cenario") else None
    ref_txt = ""
    if refs:
        ref_txt = (" The reference image is a numbered sheet: " + ", ".join(f"panel {k} = {r[0]}" for k, r in enumerate(refs, 1))
                   + ". Keep every character EXACTLY as in their panel (same face, hair, eye color, outfit, colors, proportions)"
                   + (" and every object EXACTLY as in its panel (same shape, color, size)" if any(r[0].startswith("object:") for r in refs) else "")
                   + (" and use the location panel as the setting" if any(r[0] == "location" for r in refs) else "") + ".")
    cam = f"Camera: {cena['angulo']}. " if cena.get("angulo") and qual != "fim" else ""
    cont = f"Continuity (must match the other shots of this moment): {cena['continuidade']} " if cena.get("continuidade") else ""
    so = (f"Only these characters appear: {', '.join(p['nome'] for p in pers if p)} — no other people. " if any(pers) else "")
    so += " ".join(f"The {o['nome']} looks exactly like this every time: {o['descricao']}." for o in objetos_do_plano(s, cena)) + " "
    return (f"{ESTILOS[s['estilo']]['prompt']}. {_proporcao_txt(s)}, a single anime still frame. {cam}{texto} "
            + (f"Characters: {desc} " if desc else "") + so + (f"Location: {lugar['descricao']}. " if lugar else "") + cont
            + ref_txt + " No text, no speech bubbles, no subtitles, no watermark.")[:3800]


def _sempre_visivel(s: Dict[str, Any], cena: Dict[str, Any], pers: List[Optional[Dict[str, Any]]]) -> str:
    """🎒 os detalhes que o gerador esquece (a alça da bolsa, os óculos) e os 🧸 objetos com a MESMA cara em todo plano."""
    partes = [f"ALWAYS visible on {p['nome']} for the whole shot: {p['detalhes']}." for p in pers if p and p.get("detalhes")]
    partes += [f"The {o['nome']} must look exactly the same in every frame: {o['descricao']}." for o in objetos_do_plano(s, cena)]
    return " ".join(partes)


def prompt_video_elementos(s: Dict[str, Any], cena: Dict[str, Any], rotulos: List[str]) -> str:
    """🎙 vídeo com INGREDIENTES (ficha da personagem + ficha de voz + cena): a técnica de voz e rosto consistentes."""
    refs_txt = " ".join(f"Reference image {k}: {r}." for k, r in enumerate(rotulos, 1))
    falas = []
    for f in cena.get("falas") or []:
        p = item(s, f.get("quem") or "")
        quem = p["nome"] if p else "the character"
        emo = f" ({f['emocao']})" if f.get("emocao") else ""
        falas.append(f'{quem} says{emo}, using the voice from {quem}\'s voice sheet, in {LINGUAS[s["idioma"]]}: "{f["texto"]}"')
    vozes = []
    for q in dict.fromkeys(f.get("quem") for f in cena.get("falas") or []):
        p = item(s, q or "")
        vp = (p or {}).get("voz_perfil") or {}
        if p and (vp.get("resumo") or p.get("voz")):
            vozes.append(f"{p['nome']}'s voice: {vp.get('resumo') or p['voz']}")
    pers = [item(s, q) for q in cena.get("quem") or []]
    partes = [f"{ESTILOS[s['estilo']]['prompt']}. {_proporcao_txt(s)}.", refs_txt,
              "Characters must look EXACTLY like their character sheets (same face, hair, eyes, outfit, colors, body).",
              ("Characters in the scene: " + ", ".join(p["nome"] for p in pers if p) + ". Only these characters appear — no "
               "other people, no new characters.") if any(pers) else "", _sempre_visivel(s, cena, pers),
              (f"Camera: {cena['angulo']}.") if cena.get("angulo") else "",
              f"Scene: {cena.get('inicio') or ''} {cena.get('acao') or ''}".strip(),
              (f"Action, beat by beat: {cena['beats']}") if cena.get("beats") else "", cena.get("movimento") or "",
              (f"Continuity: {cena['continuidade']}") if cena.get("continuidade") else "",
              (f"The shot ends with: {cena['fim']}") if cena.get("fim") else ""]
    if vozes:
        partes.append(" ".join(vozes) + ".")
    if falas:
        partes.append("Dialogue, spoken aloud with lip sync, in this order: " + " Then ".join(falas) + ".")
    else:
        partes.append("No dialogue; only reactions and sound effects.")
    partes.append("Keep voice consistency and character consistency. Clean, close dialogue audio in a quiet room tone "
                  "(no wind, no echo), natural sound effects, no background music, no subtitles, no text on screen. "
                  f"Comedic timing, expressive acting, about {cena['duracao']:.0f} seconds.")
    return " ".join(x.strip() for x in partes if x and x.strip())[:3800]


def prompt_video_cena(s: Dict[str, Any], cena: Dict[str, Any], com_fim: bool) -> str:
    falas = []
    for f in cena.get("falas") or []:
        p = item(s, f.get("quem") or "")
        quem = p["nome"] if p else "the character"
        voz = f" ({p['voz']})" if p and p.get("voz") else ""
        emo = f", {f['emocao']}" if f.get("emocao") else ""
        falas.append(f'{quem}{voz}{emo} says in {LINGUAS[s["idioma"]]}: "{f["texto"]}"')
    vozes = []
    for q in dict.fromkeys(f.get("quem") for f in cena.get("falas") or []):
        p = item(s, q or "")
        vp = (p or {}).get("voz_perfil") or {}
        if p and (vp.get("resumo") or p.get("voz")):
            vozes.append(f"{p['nome']}'s voice (always the same): {vp.get('resumo') or p['voz']}")
    pers = [item(s, q) for q in cena.get("quem") or []]
    partes = [f"{ESTILOS[s['estilo']]['prompt']}. Animate this image in the same art style, keeping every character, the "
              "place, the light and the clothes exactly as shown in the first frame.",
              ("This shot continues seamlessly from the previous shot: same camera, same moment, the action simply goes on."
               if cena.get("continua") else ""),
              (f"Camera: {cena['angulo']}.") if cena.get("angulo") else "",
              cena.get("acao") or "", (f"Action, beat by beat: {cena['beats']}") if cena.get("beats") else "",
              cena.get("movimento") or "",
              (f"Continuity: {cena['continuidade']}") if cena.get("continuidade") else "",
              ("Only these characters appear: " + ", ".join(p["nome"] for p in pers if p) + " — no other people.") if any(pers) else "",
              _sempre_visivel(s, cena, pers), " ".join(vozes)]
    if cena.get("fim"):
        partes.append(f"The shot ends with: {cena['fim']}")
    if falas:
        partes.append("Dialogue, spoken aloud with lip sync, in this order: " + " Then ".join(falas) + ".")
    else:
        partes.append("No dialogue; only reactions and sound effects.")
    partes.append(f"About {cena['duracao']:.0f} seconds. Comedic timing, expressive anime acting. Natural sound effects. "
                  "No background music, no subtitles, no text on screen.")
    return " ".join(x.strip() for x in partes if x and x.strip())[:3800]


# ------------------------------------------------------------------ fila do Flow
def _lote():
    import flow_lote
    return flow_lote.lote()


def _iniciar_lote() -> str:
    try:
        _lote().iniciar()
        return ""
    except Exception as exc:  # noqa: BLE001
        return f"o 🚀 Flow em massa não ligou agora ({str(exc)[:160]}) — os pedidos ficam na fila; clique em ▶ Continuar na aba Flow"


def _colagem(refs: List[Tuple[str, str]], pasta: str) -> Optional[str]:
    if not refs:
        return None
    import criador_personagens as CP
    return CP.colagem_de([c for _r, c in refs], pasta)


def iid_p(it: Dict[str, Any]) -> bool:
    return str(it.get("id") or "").startswith("P")


def pedir_refs(base: str, sid: str, ids: List[str], com_foto: bool = False, preparar: bool = False) -> Dict[str, Any]:
    """🧍 a referência ISOLADA de cada personagem (corpo inteiro, fundo liso) / cenário vazio, no Flow.
    `com_foto`: as imagens de inspiração do personagem vão como referência (sai parecido com elas); sem: só pelo texto.
    `preparar`: quando ela chegar, já pede a 📋 ficha e faz a 🎙 voz."""
    with TRAVA:
        s = carregar_serie(base, sid)
        itens, alvo = [], []
        for iid in ids:
            it = item(s, iid)
            if not it or (it.get("ref") or {}).get("estado") in ESTADOS_ESPERA:
                continue
            if iid.startswith("P") and not it.get("aparencia"):
                continue
            pedido = {"tipo": "imagem", "origem": "shorts_ia"}
            fotos = [os.path.join(pasta_refs(base, sid), x) for x in it.get("inspiracoes") or []] if iid.startswith("P") and com_foto else []
            fotos = [c for c in fotos if os.path.isfile(c)][:MAX_REFS_CENA]
            if fotos:
                col = fotos[0] if len(fotos) == 1 else _colagem([(f"photo {k}", c) for k, c in enumerate(fotos, 1)],
                                                                 os.path.join(pasta_serie(base, sid), "_colagens"))
                pedido.update(prompt=prompt_ref_com_foto(s, it, len(fotos)), referencia_arquivo=col)
            elif iid.startswith("P"):
                pedido["prompt"] = prompt_ref_personagem(s, it)
            elif iid.startswith("O"):  # 🧸 objeto sozinho, fundo liso, no traço da série
                anc = ancora_estilo(base, s)
                pedido["prompt"] = prompt_ref_objeto(s, it, bool(anc))
                if anc:
                    pedido["referencia_arquivo"] = anc
            else:  # 🏞 cenário: o traço vem da imagem de estilo (o personagem), pra não sair pintura realista
                anc = ancora_estilo(base, s)
                pedido["prompt"] = prompt_ref_cenario(s, it, bool(anc))
                if anc:
                    pedido["referencia_arquivo"] = anc
            if preparar and iid.startswith("P"):
                it["preparar"] = True
                it["ficha"] = dict(_slot(), arquivo=(it.get("ficha") or {}).get("arquivo"))  # a ficha velha não vale pra ref nova
            itens.append(pedido)
            alvo.append(it)
        if not itens:
            raise ShortsIAErro("Nada pra gerar (falta a aparência, ou já está na fila).")
        novos = _lote().adicionar(itens, proporcao="9:16" if s["proporcao"] == "9:16" else "1:1")
        for it, j, pedido in zip(alvo, novos, itens):
            velho = it.get("ref") or {}
            it["ref"] = dict(_slot(), estado="fila", flow_job=j["id"], prompt=pedido["prompt"], msg="⏳ na fila do Flow"
                             + ((" (com a foto)" if iid_p(it) else " (no traço da imagem de estilo)") if pedido.get("referencia_arquivo") else ""),
                             anterior=velho.get("arquivo"), com_foto=bool(pedido.get("referencia_arquivo")))
            if velho.get("arquivo"):
                it["ref"]["arquivo"] = velho["arquivo"]  # a antiga continua valendo até a nova chegar
        salvar_serie(base, s)
    return {"enviadas": len(novos), "aviso": _iniciar_lote()}


AGUARDANDO = "aguardando"


def _anterior(e: Dict[str, Any], i: int) -> Optional[Dict[str, Any]]:
    """O plano anterior do MESMO momento (a continuidade vem dele)."""
    if i <= 0:
        return None
    cn, ant = e["cenas"][i], e["cenas"][i - 1]
    return ant if cn.get("momento") and ant.get("momento") == cn["momento"] else None


def ultimo_quadro(video: str, destino: str, corte_fim: float = 0.35) -> Optional[str]:
    """O último quadro BOM do vídeo (antes da ponta bugada) — o próximo plano começa dele."""
    d = _ffprobe_dur(video)
    if d <= 0:
        return None
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, d - corte_fim - 0.12):.3f}", "-i", video, "-frames:v", "1",
                    destino], capture_output=True, timeout=120)
    return destino if os.path.isfile(destino) else None


def _encadear(e: Dict[str, Any]) -> bool:
    return e["edicao"].get("encadear", True) is not False


def pedir_imagens(base: str, sid: str, eid: str, indices: Optional[List[int]] = None, refazer: bool = False) -> Dict[str, Any]:
    """🖼 os quadros A — com a colagem das referências do plano. ⛓ em sequência: o plano que vem depois no mesmo momento
    espera o quadro do anterior (vai como referência de continuidade); o que "continua" a mesma câmera nem pede imagem —
    começa do último quadro do vídeo anterior."""
    s = carregar_serie(base, sid)
    pe = pasta_ep(base, sid, eid)
    avisos = []
    with TRAVA:
        e = carregar_ep(base, sid, eid)
        idx = range(len(e["cenas"])) if indices is None else [i for i in indices if 0 <= i < len(e["cenas"])]
        itens, alvo = [], []
        esperando = continuou = 0
        for i in idx:
            cn = e["cenas"][i]
            slot0 = cn["img_inicio"]
            if slot0.get("estado") in ESTADOS_ESPERA or (slot0.get("arquivo") and not refazer and not slot0.get("desatualizada")
                                                         and slot0.get("estado") != AGUARDANDO):
                continue
            ant = _anterior(e, i)
            if ant and _encadear(e) and e["edicao"].get("modo_video") == "frames" and cn.get("continua"):
                if not _arquivo_ep(pe, ant["video"]):
                    cn["img_inicio"] = dict(_slot(), estado=AGUARDANDO, arquivo=slot0.get("arquivo"),
                                            msg="⛓ começa do último quadro do vídeo do plano anterior — esperando ele")
                    esperando += 1
                    continue
                q = ultimo_quadro(_arquivo_ep(pe, ant["video"]), os.path.join(pe, "midia", f"{cn['id']}_img_inicio_ult_{secrets.token_hex(3)}.png"),
                                  float(e["edicao"].get("corte_fim") or 0.35))
                if q:
                    cn["img_inicio"] = dict(_slot(), estado="pronto", arquivo=os.path.basename(q), msg="⛓ último quadro do plano anterior")
                    continuou += 1
                    continue
            if ant and _encadear(e) and not _arquivo_ep(pe, ant["img_inicio"]):
                cn["img_inicio"] = dict(_slot(), estado=AGUARDANDO, arquivo=slot0.get("arquivo"),
                                        msg="⛓ esperando o quadro do plano anterior (continuidade)")
                esperando += 1
                continue
            refs = refs_da_cena(base, s, cn)
            prev = _arquivo_ep(pe, ant["img_inicio"]) if ant else None
            if prev and len(refs) < MAX_REFS_CENA:  # 🎬 mesmo momento: o plano anterior segura o lugar, a luz e as roupas
                refs.append(("previous shot of this same moment (keep the same place, light, clothes and positions)", prev))
            faltam = [item(s, q)["nome"] for q in cn["quem"] if item(s, q) and not caminho_ref(base, s, item(s, q))]
            if faltam:
                avisos.append(f"cena {i + 1}: {', '.join(faltam)} sem imagem de referência — sai sem garantia de ficar igual")
            col = _colagem(refs, os.path.join(pe, "refs_cena"))
            for qual in ("inicio",):  # (o quadro B virou texto: o Flow em massa não manda o frame de Fim — travava, v84_203)
                slot = cn["img_" + qual]
                if slot.get("estado") in ESTADOS_ESPERA:
                    continue
                pr = prompt_imagem_cena(s, cn, qual, refs)
                it = {"prompt": pr, "tipo": "imagem", "origem": "shorts_ia"}
                if col:
                    it["referencia_arquivo"] = col
                itens.append(it)
                alvo.append((cn, qual, pr))
        if not itens:
            if esperando or continuou:
                salvar_ep(base, e)
                return {"enviadas": 0, "aguardando": esperando, "continuou": continuou, "avisos": avisos, "aviso": ""}
            raise ShortsIAErro("Nenhuma imagem pra gerar (já estão prontas — use 🔁 refazer na cena).")
        novos = _lote().adicionar(itens, proporcao=s["proporcao"], modelo=s["padroes"].get("modelo_imagem") or "")
        for (cn, qual, pr), j in zip(alvo, novos):
            velho = cn["img_" + qual]
            cn["img_" + qual] = dict(_slot(), estado="fila", flow_job=j["id"], prompt=pr, msg="⏳ na fila do Flow",
                                     arquivo=velho.get("arquivo"))
        salvar_ep(base, e)
    return {"enviadas": len(novos), "aguardando": esperando, "continuou": continuou, "avisos": avisos, "aviso": _iniciar_lote()}


def pedir_videos(base: str, sid: str, eid: str, indices: Optional[List[int]] = None, refazer: bool = False) -> Dict[str, Any]:
    """🎬 cada cena vira vídeo no Flow: quadro A como Início (+ quadro B como Fim), com as falas."""
    s = carregar_serie(base, sid)
    pe = pasta_ep(base, sid, eid)
    erros = []
    with TRAVA:
        e = carregar_ep(base, sid, eid)
        modo = e["edicao"].get("modo_video") or "elementos"
        idx = range(len(e["cenas"])) if indices is None else [i for i in indices if 0 <= i < len(e["cenas"])]
        itens, alvo = [], []
        esperando = 0
        for i in idx:
            cn = e["cenas"][i]
            v = cn["video"]
            if v.get("estado") in ESTADOS_ESPERA or (v.get("arquivo") and not refazer and v.get("estado") != AGUARDANDO):
                continue
            ini = _arquivo_ep(pe, cn["img_inicio"])
            a_estado = (cn["img_inicio"] or {}).get("estado")
            if modo == "frames" and (a_estado in ESTADOS_ESPERA or a_estado == AGUARDANDO):  # o quadro (novo) ainda não chegou
                cn["video"] = dict(_slot(), estado=AGUARDANDO, arquivo=v.get("arquivo"),
                                   msg="⛓ esperando o quadro A deste plano — o vídeo vai sozinho quando ele chegar")
                esperando += 1
                continue
            if modo == "elementos":
                arquivos, rotulos, falta = ingredientes(base, s, cn, ini, os.path.join(pe, "refs_cena"))
                if falta:
                    erros.append(f"cena {i + 1}: {falta}")
                if not arquivos:
                    erros.append(f"cena {i + 1}: nenhuma ficha pronta — gere as fichas na página da série")
                    continue
                pr = prompt_video_elementos(s, cn, rotulos)
                it = {"prompt": pr, "tipo": "video", "referencias_arquivos": arquivos, "origem": "shorts_ia"}
            else:
                if not ini:
                    erros.append(f"cena {i + 1}: falta a imagem de início")
                    continue
                pr = prompt_video_cena(s, cn, False)
                it = {"prompt": pr, "tipo": "video", "inicio_arquivo": ini, "origem": "shorts_ia"}
            itens.append(it)
            alvo.append((cn, pr))
        if not itens:
            if esperando:
                salvar_ep(base, e)
                return {"enviadas": 0, "aguardando": esperando, "erros": erros, "aviso": ""}
            raise ShortsIAErro("; ".join(erros) or "Nenhum vídeo pra gerar (já estão prontos — use 🔁 refazer na cena).")
        for it2 in itens:  # 🎞 v84_274: o Flow gera na duração do plano (4/6/8/10 s) — sem cortar a ação depois
            it2["duracao"] = duracao_flow(float(e.get("dur_plano") or s["padroes"]["dur_plano"]))
        novos = _lote().adicionar(itens, proporcao=s["proporcao"], modelo_video=e["edicao"].get("modelo_video") or "")
        for (cn, pr), j in zip(alvo, novos):
            cn["video"] = dict(_slot(), estado="fila", flow_job=j["id"], prompt=pr, msg="⏳ na fila do Flow", arquivo=cn["video"].get("arquivo"))
        e["export"] = None
        salvar_ep(base, e)
    return {"enviadas": len(novos), "aguardando": esperando, "erros": erros, "aviso": _iniciar_lote()}


def _arquivo_ep(pe: str, slot: Dict[str, Any]) -> Optional[str]:
    if not slot or not slot.get("arquivo"):
        return None
    c = os.path.join(pe, "midia", os.path.basename(slot["arquivo"]))
    return c if os.path.isfile(c) else None


def _galeria(arquivo: str) -> str:
    import flow_estudio as FE
    return os.path.join(FE.pasta_galeria(), os.path.basename(arquivo))


def _sync_slot(slot: Dict[str, Any], fila: Dict[str, Dict[str, Any]], rodando: bool, tipo: str, destino_dir: str, prefixo: str) -> bool:
    """Atualiza um pedido (imagem/vídeo) com o que a fila do Flow diz. True se mudou."""
    if (slot or {}).get("estado") not in ESTADOS_ESPERA:
        return False
    antes = (slot.get("estado"), slot.get("msg"), slot.get("erro"), slot.get("arquivo"))
    j = fila.get(slot.get("flow_job") or "")
    if j is None:
        slot.update(estado="erro", erro="o pedido sumiu da fila do 🚀 Flow em massa (limparam a fila?) — gere de novo")
    elif j["estado"] == "ok":
        r = next((x for x in j.get("resultados") or [] if x.get("tipo") == tipo), None)
        org = _galeria(r["arquivo"]) if r else ""
        if not r or not os.path.isfile(org):
            slot.update(estado="erro", erro="o Flow terminou mas não veio " + ("vídeo" if tipo == "video" else "imagem"))
        else:
            os.makedirs(destino_dir, exist_ok=True)
            ext = os.path.splitext(org)[1] or (".mp4" if tipo == "video" else ".png")
            nome = f"{prefixo}_{j['id']}{ext}"
            shutil.copyfile(org, os.path.join(destino_dir, nome))
            slot.update(estado="pronto", arquivo=nome, erro=None, msg="✅ pronto", conta=j.get("conta"), desatualizada=False, pronto_em=time.time())
    elif j["estado"] == "erro":
        slot.update(estado="erro", erro=str(j.get("erro") or "o Flow falhou")[:300])
    elif j["estado"] in ("rodando", "convertendo"):
        slot.update(estado="gerando", msg=f"🎨 gerando no Flow (conta “{j.get('conta') or '…'}”)")
    elif not rodando:
        slot.update(estado="parado", msg="⏸ o Flow em massa está parado — ▶ Continuar na aba Flow (ou ⚡ religar aqui)")
    else:
        slot.update(estado="fila", msg="⏳ na fila do Flow")
    return (slot.get("estado"), slot.get("msg"), slot.get("erro"), slot.get("arquivo")) != antes


def _foto_da_fila():
    lote = _lote()
    with lote.trava:
        return {j["id"]: dict(j) for j in lote.fila}, bool(lote.rodando)


def _algum_esperando(slots: List[Dict[str, Any]]) -> bool:
    return any((x or {}).get("estado") in ESTADOS_ESPERA for x in slots)


def tem_cadeia(e: Dict[str, Any]) -> bool:
    return any((cn.get(k) or {}).get("estado") == AGUARDANDO for cn in e.get("cenas") or [] for k in ("img_inicio", "video"))


def sincronizar_serie(base: str, sid: str) -> bool:
    with TRAVA:
        s = carregar_serie(base, sid)
        itens = s["elenco"] + s["cenarios"] + s.get("objetos", [])
        if not _algum_esperando([x.get("ref") for x in itens] + [p.get("ficha") for p in s["elenco"]]):
            return False
        fila, rodando = _foto_da_fila()
        mudou = False
        refs_dir = os.path.join(pasta_serie(base, sid), "refs")
        for it in itens:
            r = it.get("ref") or {}
            if _sync_slot(r, fila, rodando, "imagem", refs_dir, it["id"]):
                mudou = True
                if r.get("estado") == "pronto":
                    r["msg"] = "🔒 travada (gerada no Flow)"
                elif r.get("estado") == "erro" and r.get("anterior"):
                    r["arquivo"] = r["anterior"]
            if it["id"].startswith("P") and _sync_slot(it.get("ficha") or {}, fila, rodando, "imagem", refs_dir, it["id"] + "_ficha"):
                mudou = True
                if (it["ficha"] or {}).get("estado") == "erro" and it["ficha"].get("anterior"):
                    it["ficha"]["arquivo"] = it["ficha"]["anterior"]
        if mudou:
            salvar_serie(base, s)
        prontos_ref = [p["id"] for p in s["elenco"] if p.get("preparar") and caminho_ref(base, s, p)
                       and not (p.get("ficha") or {}).get("estado")]
    if mudou and prontos_ref:
        _continuar_preparo(base, sid, prontos_ref)
    return mudou


_PREPARANDO: set = set()


def _continuar_preparo(base: str, sid: str, ids: List[str]) -> None:
    """🧍 a referência chegou: pede a 📋 ficha no Flow e faz a 🎙 ficha de voz (em segundo plano, a IA leva uns segundos)."""
    try:
        pedir_fichas(base, sid, ids)
    except Exception:  # noqa: BLE001
        pass

    def vozes():
        for pid in ids:
            if (sid, pid) in _PREPARANDO:
                continue
            _PREPARANDO.add((sid, pid))
            try:
                fazer_ficha_de_voz(base, sid, pid)
                with TRAVA:
                    s = carregar_serie(base, sid)
                    p = item(s, pid)
                    if p:
                        p["preparar"] = False
                        salvar_serie(base, s)
            except Exception:  # noqa: BLE001
                pass
            finally:
                _PREPARANDO.discard((sid, pid))
    threading.Thread(target=vozes, daemon=True, name="shorts-ia-vozes").start()


def preparar_personagens(base: str, sid: str, ids: List[str]) -> Dict[str, Any]:
    """🧍📋🎙 tudo de uma vez: o que tem referência já faz ficha + voz; o que não tem pede a referência e continua sozinho."""
    with TRAVA:
        s = carregar_serie(base, sid)
        for pid in ids:
            p = item(s, pid)
            if p and pid.startswith("P"):
                p["preparar"] = True
        salvar_serie(base, s)
    s = carregar_serie(base, sid)
    com_ref = [pid for pid in ids if caminho_ref(base, s, item(s, pid))]
    sem_ref = [pid for pid in ids if pid not in com_ref and item(s, pid)]
    r: Dict[str, Any] = {"refs": 0, "fichas": 0}
    if sem_ref:  # com inspirações: a referência sai parecida com elas (com a foto)
        r["refs"] = pedir_refs(base, sid, sem_ref, com_foto=True)["enviadas"]
    if com_ref:
        _continuar_preparo(base, sid, [pid for pid in com_ref if not arquivo_serie(base, s, item(s, pid).get("ficha"))] or com_ref)
        r["fichas"] = len(com_ref)
    return r


def sincronizar_ep(base: str, sid: str, eid: str) -> bool:
    with TRAVA:
        e = carregar_ep(base, sid, eid)
        slots = [(cn, k) for cn in e["cenas"] for k in ("img_inicio", "img_fim", "video")]
        no_flow = _algum_esperando([cn[k] for cn, k in slots])
        mudou = False
        if no_flow:
            fila, rodando = _foto_da_fila()
            md = os.path.join(pasta_ep(base, sid, eid), "midia")
            for cn, k in slots:
                if _sync_slot(cn[k], fila, rodando, "video" if k == "video" else "imagem", md, f"{cn['id']}_{k}"):
                    mudou = True
            if mudou:
                salvar_ep(base, e)
        cadeia = tem_cadeia(e)
    if cadeia and (mudou or not no_flow):  # ⛓ chegou algo (ou nada mais no Flow): manda o próximo da sequência
        if despachar_cadeia(base, sid, eid):
            mudou = True
    return mudou


def despachar_cadeia(base: str, sid: str, eid: str) -> int:
    """⛓ chegou um quadro/vídeo: manda o próximo da fila de continuidade (o que estava "aguardando")."""
    e = carregar_ep(base, sid, eid)
    n = 0
    for i, cn in enumerate(e["cenas"]):
        try:
            if (cn.get("img_inicio") or {}).get("estado") == AGUARDANDO:
                r = pedir_imagens(base, sid, eid, [i])
                n += r.get("enviadas", 0) + r.get("continuou", 0)
            e2 = carregar_ep(base, sid, eid)
            if (e2["cenas"][i].get("video") or {}).get("estado") == AGUARDANDO and (e2["cenas"][i].get("img_inicio") or {}).get("estado") == "pronto" \
                    and _arquivo_ep(pasta_ep(base, sid, eid), e2["cenas"][i]["img_inicio"]):
                n += pedir_videos(base, sid, eid, [i]).get("enviadas", 0)
        except ShortsIAErro:
            pass
        except Exception:  # noqa: BLE001 — Flow fora: tenta de novo na próxima atualização
            pass
    return n


def usar_imagem_enviada(base: str, sid: str, eid: str, k: int, qual: str, origem: str) -> None:
    """Você mandou a sua própria imagem pro quadro A/B da cena."""
    from PIL import Image
    with TRAVA:
        e = carregar_ep(base, sid, eid)
        if not 0 <= k < len(e["cenas"]) or qual not in ("inicio", "fim"):
            raise ShortsIAErro("Cena não encontrada.")
        cn = e["cenas"][k]
        md = os.path.join(pasta_ep(base, sid, eid), "midia")
        os.makedirs(md, exist_ok=True)
        nome = f"{cn['id']}_img_{qual}_seu_{secrets.token_hex(3)}.png"
        try:
            Image.open(origem).convert("RGB").save(os.path.join(md, nome))
        except Exception as exc:  # noqa: BLE001
            raise ShortsIAErro("Não consegui abrir essa imagem.") from exc
        cn["img_" + qual] = dict(_slot(), estado="pronto", arquivo=nome, msg="✅ sua imagem", por="voce")
        salvar_ep(base, e)


def usar_video_enviado(base: str, sid: str, eid: str, k: int, origem: str) -> None:
    with TRAVA:
        e = carregar_ep(base, sid, eid)
        if not 0 <= k < len(e["cenas"]):
            raise ShortsIAErro("Cena não encontrada.")
        cn = e["cenas"][k]
        md = os.path.join(pasta_ep(base, sid, eid), "midia")
        os.makedirs(md, exist_ok=True)
        nome = f"{cn['id']}_video_seu_{secrets.token_hex(3)}.mp4"
        shutil.copyfile(origem, os.path.join(md, nome))
        if _ffprobe_dur(os.path.join(md, nome)) <= 0:
            os.remove(os.path.join(md, nome))
            raise ShortsIAErro("Não consegui ler esse vídeo.")
        cn["video"] = dict(_slot(), estado="pronto", arquivo=nome, msg="✅ seu vídeo", por="voce")
        e["export"] = None
        salvar_ep(base, e)


# ------------------------------------------------------------------ 📋 fichas de personagem e 🎙 fichas de voz
def arquivo_serie(base: str, s: Dict[str, Any], slot: Optional[Dict[str, Any]]) -> Optional[str]:
    arq = (slot or {}).get("arquivo")
    if not arq:
        return None
    c = os.path.join(pasta_serie(base, s["id"]), "refs", os.path.basename(arq))
    return c if os.path.isfile(c) else None


def pedir_fichas(base: str, sid: str, ids: List[str]) -> Dict[str, Any]:
    """📋 a folha de personagem de cada um, no Flow, a partir da referência travada (vai como imagem de referência)."""
    with TRAVA:
        s = carregar_serie(base, sid)
        itens, alvo, sem_ref = [], [], []
        for pid in ids:
            p = item(s, pid)
            if not p or not pid.startswith("P") or (p.get("ficha") or {}).get("estado") in ESTADOS_ESPERA:
                continue
            ref = caminho_ref(base, s, p)
            if not ref:
                sem_ref.append(p["nome"])
                continue
            itens.append({"prompt": prompt_ficha_personagem(s, p), "tipo": "imagem", "referencia_arquivo": ref, "origem": "shorts_ia"})
            alvo.append(p)
        if not itens:
            raise ShortsIAErro(("Primeiro a referência (🧍) de: " + ", ".join(sem_ref)) if sem_ref else "Nada pra gerar (já está na fila).")
        novos = _lote().adicionar(itens, proporcao="16:9")
        for p, j, it in zip(alvo, novos, itens):
            velho = p.get("ficha") or {}
            p["ficha"] = dict(_slot(), estado="fila", flow_job=j["id"], prompt=it["prompt"], msg="⏳ na fila do Flow",
                              arquivo=velho.get("arquivo"), anterior=velho.get("arquivo"))
        salvar_serie(base, s)
    return {"enviadas": len(novos), "sem_ref": sem_ref, "aviso": _iniciar_lote()}


VOZ_SCHEMA = _o({"idioma": _S, "sotaque": _S, "genero": _S, "idade_vocal": _S, "timbre": _S, "tom": _S, "ritmo": _S, "diccao": _S,
                 "atitude": _S, "maneirismos": _S, "emocoes": _a(_o({"emocao": _S, "como_soa": _S})), "frase_exemplo": _S, "resumo": _S})
VOZ_SYS = (
    "You are a voice director for an animated comedy series made with AI video (the video model reads a VOICE SHEET image "
    "and must keep the SAME voice in every clip). Write a precise, distinctive and STABLE voice profile for the character, "
    "in English: 'idioma' (language + variant), 'sotaque' (accent), 'genero' (gender of the voice), 'idade_vocal' (how old "
    "the voice sounds), 'timbre' (texture: raspy, bright, breathy, nasal, warm…), 'tom' (pitch: low/mid/high + range), "
    "'ritmo' (pace and pauses), 'diccao' (articulation), 'atitude' (vocal attitude), 'maneirismos' (verbal tics, laugh, "
    "catchphrase delivery), 'emocoes' (4–5 emotions and how THIS voice sounds in each), 'frase_exemplo' (a short typical "
    "line in the post language) and 'resumo' (ONE dense sentence with timbre + pitch + accent + pace + attitude, used inside "
    "video prompts). Concrete words only — no celebrity or existing-character voice comparisons."
)


def _perfil_por_regra(s: Dict[str, Any], p: Dict[str, Any]) -> Dict[str, Any]:
    v = p.get("voz") or "clear expressive voice"
    return {"idioma": LINGUAS[s["idioma"]], "sotaque": "neutral", "genero": p.get("genero") or "", "idade_vocal": p.get("idade") or "",
            "timbre": v, "tom": "", "ritmo": "", "diccao": "clear", "atitude": p.get("personalidade") or "",
            "maneirismos": p.get("jeito_de_falar") or "", "emocoes": [], "frase_exemplo": (s.get("bordoes") or [""])[0],
            "resumo": f"{v}, {LINGUAS[s['idioma']]}" + (f", {p['genero']}" if p.get("genero") else "")}


def _cores(img: Optional[str]) -> List[Tuple[int, int, int]]:
    """As cores da referência (a ficha de voz fica com a cara da personagem, sem a personagem)."""
    padrao = [(28, 24, 40), (70, 50, 110), (230, 80, 90), (250, 210, 120), (245, 245, 250)]
    if not img:
        return padrao
    try:
        from PIL import Image
        im = Image.open(img).convert("RGB").resize((80, 80))
        q = im.quantize(6)
        pal = q.getpalette()[:18]
        cores = sorted({tuple(pal[i:i + 3]) for i in range(0, 18, 3)}, key=lambda c: sum(c))
        cores = [c for c in cores if not (min(c) > 200 and max(c) - min(c) < 20)] or padrao  # tira o fundo cinza/branco liso
        while len(cores) < 5:
            cores.append(padrao[len(cores)])
        return cores[:5]
    except Exception:  # noqa: BLE001
        return padrao


def desenhar_ficha_voz(s: Dict[str, Any], p: Dict[str, Any], perfil: Dict[str, Any], cores: List[Tuple[int, int, int]], destino: str) -> str:
    """🎙 a FOLHA DE VOZ (16:9): nome, idioma, sotaque, timbre, tom, ritmo, emoções… — texto bem legível, nas cores da
    personagem, sem desenhar a personagem. Vai como ingrediente do vídeo junto com a ficha da personagem."""
    from PIL import Image, ImageDraw, ImageFont
    import dp_legendas
    W, H = 1920, 1080
    fundo, meio, acento, claro = cores[0], cores[1], cores[-2], (248, 248, 252)
    im = Image.new("RGB", (W, H), fundo)
    dr = ImageDraw.Draw(im)
    for y in range(H):  # degradê suave
        t = y / H
        dr.line([(0, y), (W, y)], fill=tuple(int(fundo[k] * (1 - t * .5) + meio[k] * t * .5) for k in range(3)))

    def fonte(tam: int, negrito: bool = True):
        try:
            return ImageFont.truetype(dp_legendas._arquivo_fonte("DP Poppins" if negrito else "DP Inter"), tam)
        except Exception:  # noqa: BLE001
            try:
                return ImageFont.truetype(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts",
                                                       "DejaVuSans-Bold.ttf" if negrito else "DejaVuSans.ttf"), tam)
            except Exception:  # noqa: BLE001
                return ImageFont.load_default()

    def quebrar(texto: str, f, larg: int) -> List[str]:
        linhas, atual = [], ""
        for w in str(texto or "").split():
            t = (atual + " " + w).strip()
            if dr.textlength(t, font=f) <= larg:
                atual = t
            else:
                if atual:
                    linhas.append(atual)
                atual = w
        if atual:
            linhas.append(atual)
        return linhas
    dr.rectangle([0, 0, W, 150], fill=acento)
    dr.text((60, 28), f"VOICE SHEET — {p['nome'].upper()}", font=fonte(64), fill=fundo)
    dr.text((W - 60, 52), f"{s['nome']}", font=fonte(34, False), fill=fundo, anchor="ra")
    campos = [("LANGUAGE", perfil.get("idioma")), ("ACCENT", perfil.get("sotaque")), ("GENDER", perfil.get("genero")),
              ("VOCAL AGE", perfil.get("idade_vocal")), ("TIMBRE", perfil.get("timbre")), ("PITCH", perfil.get("tom")),
              ("PACE", perfil.get("ritmo")), ("DICTION", perfil.get("diccao")), ("VOCAL ATTITUDE", perfil.get("atitude")),
              ("MANNERISMS", perfil.get("maneirismos"))]
    campos = [(k, v) for k, v in campos if str(v or "").strip()]
    col_w, x0, y0 = 880, 60, 185
    fr, fv = fonte(26), fonte(30, False)
    ys = [y0, y0]
    for k, (rot, val) in enumerate(campos):
        c = 0 if ys[0] <= ys[1] else 1
        x, y = x0 + c * (col_w + 40), ys[c]
        dr.text((x, y), rot, font=fr, fill=acento)
        y += 36
        for ln in quebrar(val, fv, col_w)[:3]:
            dr.text((x, y), ln, font=fv, fill=claro)
            y += 38
        ys[c] = y + 18
    y = max(ys) + 6
    emo = perfil.get("emocoes") or []
    if emo and y < H - 200:
        dr.text((x0, y), "EMOTIONS", font=fr, fill=acento)
        y += 40
        larg = (W - 2 * x0 - 30 * (min(5, len(emo)) - 1)) // max(1, min(5, len(emo)))
        for k, e in enumerate(emo[:5]):
            x = x0 + k * (larg + 30)
            dr.rounded_rectangle([x, y, x + larg, y + 150], radius=18, outline=acento, width=3)
            dr.text((x + 16, y + 12), str(e.get("emocao") or "").upper()[:22], font=fonte(24), fill=claro)
            for j, ln in enumerate(quebrar(e.get("como_soa"), fonte(22, False), larg - 32)[:3]):
                dr.text((x + 16, y + 50 + j * 30), ln, font=fonte(22, False), fill=claro)
        y += 175
    if perfil.get("frase_exemplo") and y < H - 70:
        dr.text((x0, min(y, H - 70)), f"SAMPLE LINE: “{perfil['frase_exemplo']}”"[:120], font=fonte(28, False), fill=claro)
    for k, c in enumerate(cores):  # a paleta da personagem
        dr.rectangle([W - 60 - (5 - k) * 46, H - 60, W - 60 - (5 - k) * 46 + 40, H - 20], fill=c, outline=claro)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    im.save(destino)
    return destino


def fazer_ficha_de_voz(base: str, sid: str, pid: str, chamar: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """🎙 o perfil de voz (🤖 IA; sem IA, pela descrição da voz) + a imagem da folha de voz, nas cores da personagem."""
    s = carregar_serie(base, sid)
    p = item(s, pid)
    if not p or not pid.startswith("P"):
        raise ShortsIAErro("Personagem não encontrada.")
    texto = (f"SERIES: {s['nome']} — tone: {s.get('tom') or ''}\nPOST LANGUAGE: {LINGUAS[s['idioma']]}\nCHARACTER: {p['nome']} "
             f"({p.get('papel')}) · gender: {p.get('genero')} · age: {p.get('idade')}\nLOOK: {p.get('aparencia')}\n"
             f"PERSONALITY: {p.get('personalidade')}\nWAY OF SPEAKING: {p.get('jeito_de_falar')}\nVOICE (creator's note): {p.get('voz')}\n"
             f"CATCHPHRASES: {' | '.join(s.get('bordoes') or [])}")
    conteudo: Any = texto
    ref = caminho_ref(base, s, p)
    if ref:
        import ia_servico
        b = ia_servico.imagem_bloco(ref, largura=512)
        if b:
            conteudo = [b, {"type": "text", "text": texto}]
    try:
        perfil = _ia(VOZ_SYS, conteudo, VOZ_SCHEMA, chamar, max_tokens=2500, timeout=120)
        perfil["por"] = "ia"
    except ShortsIAErro:
        perfil = dict(_perfil_por_regra(s, p), por="regra")
    nome = f"{pid}_voz_{secrets.token_hex(3)}.png"
    destino = os.path.join(pasta_serie(base, sid), "refs", nome)
    desenhar_ficha_voz(s, p, perfil, _cores(arquivo_serie(base, s, p.get("ficha")) or ref), destino)
    with TRAVA:
        s = carregar_serie(base, sid)
        p = item(s, pid)
        velho = arquivo_serie(base, s, p.get("voz_ficha"))
        p["voz_perfil"] = {k: perfil.get(k) for k in list(VOZ_SCHEMA["properties"]) + ["por"]}
        p["voz_ficha"] = dict(_slot(), estado="pronto", arquivo=nome, msg="🔒 voz travada" + (" (🤖)" if perfil["por"] == "ia" else " (sem IA)"))
        salvar_serie(base, s)
    if velho and os.path.isfile(velho):
        try:
            os.remove(velho)
        except OSError:
            pass
    return p["voz_perfil"]


def ingredientes(base: str, s: Dict[str, Any], cn: Dict[str, Any], quadro_a: Optional[str], pasta: str
                 ) -> Tuple[List[str], List[str], str]:
    """Os até 3 ingredientes do vídeo: as fichas de quem aparece (2 separadas; 3 numa colagem), a ficha de voz de quem
    fala (2+ numa colagem) e, se couber, o quadro A (composição). → (arquivos, rótulos, o que falta)."""
    presentes = [item(s, q) for q in cn.get("quem") or []]
    presentes = [p for p in presentes if p]
    falantes = [item(s, q) for q in dict.fromkeys(f.get("quem") for f in cn.get("falas") or [] if f.get("quem"))]
    falantes = [p for p in falantes if p]
    for p in falantes:  # quem fala aparece
        if p not in presentes:
            presentes.append(p)
    falta = []
    fichas = []
    for p in presentes[:MAX_REFS_CENA]:
        c = arquivo_serie(base, s, p.get("ficha")) or caminho_ref(base, s, p)
        if not arquivo_serie(base, s, p.get("ficha")):
            falta.append(f"{p['nome']} sem 📋 ficha" + ("" if c else " nem 🧍 referência"))
        if c:
            fichas.append((p["nome"], c))
    vozes = [(p["nome"], arquivo_serie(base, s, p.get("voz_ficha"))) for p in falantes]
    falta += [f"{n} sem 🎙 ficha de voz" for n, c in vozes if not c]
    vozes = [(n, c) for n, c in vozes if c]
    arquivos, rotulos = [], []
    if len(fichas) <= 2:
        for n, c in fichas:
            arquivos.append(c)
            rotulos.append(f"the character sheet of {n}")
    else:
        col = _colagem(fichas, pasta)
        if col:
            arquivos.append(col)
            rotulos.append("character sheets: " + ", ".join(f"panel {k} = {n}" for k, (n, _c) in enumerate(fichas, 1)))
    if len(vozes) == 1:
        arquivos.append(vozes[0][1])
        rotulos.append(f"the voice sheet of {vozes[0][0]} (how {vozes[0][0]} sounds — not a scene)")
    elif vozes:
        col = _colagem(vozes, pasta)
        if col:
            arquivos.append(col)
            rotulos.append("voice sheets (not a scene): " + ", ".join(f"panel {k} = {n}" for k, (n, _c) in enumerate(vozes, 1)))
    if quadro_a and len(arquivos) < 3:
        arquivos.append(quadro_a)
        rotulos.append("the first frame of this shot — use it for the setting, composition and poses")
    return arquivos[:3], rotulos[:3], "; ".join(falta)


# ------------------------------------------------------------------ 👁 conferir se o personagem saiu igual
CONFERIR_SCHEMA = _o({"planos": _a(_o({"n": _N, "ok": {"type": "boolean"}, "problema": _S}))})
CONFERIR_SYS = (
    "Você é o supervisor de continuidade de um anime feito com IA. Você recebe as FICHAS dos personagens (as referências "
    "oficiais) e um quadro de cada PLANO. Para cada plano diga se os personagens que deviam aparecer estão IGUAIS às fichas "
    "(rosto, cabelo — corte e cor —, olhos, roupa e cores, idade, proporções) e se não apareceu ninguém a mais. "
    "'ok' = true se está fiel; senão 'problema' curto em português (ex.: 'a Mame está com cabelo comprido e sem chapéu', "
    "'apareceu uma menina que não é do elenco', 'o traço mudou pra realista', 'sumiu a alça da bolsa do Sora', 'o "
    "microfone virou um gravador'). Confira também os detalhes 'sempre com' de cada personagem e os OBJETOS descritos. "
    "Pequenas diferenças de ângulo/expressão são ok."
)


def conferir_personagens(base: str, sid: str, eid: str, chamar: Optional[Callable[..., Any]] = None,
                         on_log: Callable[[str], None] = lambda _m: None, alvo: str = "video") -> Dict[str, Any]:
    """alvo "video" (um quadro de cada vídeo) ou "img_inicio" (os quadros A — confere ANTES de gastar crédito de vídeo)."""
    """👁 a IA compara um quadro de cada vídeo com as fichas — aponta o plano em que o personagem saiu diferente."""
    import ia_servico
    s = carregar_serie(base, sid)
    e = carregar_ep(base, sid, eid)
    pe = pasta_ep(base, sid, eid)
    tmp = os.path.join(pe, "_conferir")
    os.makedirs(tmp, exist_ok=True)
    alvo = alvo if alvo in ("video", "img_inicio") else "video"
    planos = [(k, cn, _arquivo_ep(pe, cn[alvo])) for k, cn in enumerate(e["cenas"])]
    planos = [(k, cn, v) for k, cn, v in planos if v]
    if not planos:
        raise ShortsIAErro("Nenhum plano tem " + ("vídeo" if alvo == "video" else "quadro A") + " ainda.")
    blocos: List[Dict[str, Any]] = []
    usados = []
    for k, cn, v in planos:
        for q in cn.get("quem") or []:
            if q not in usados:
                usados.append(q)
    for q in usados[:6]:
        p = item(s, q)
        c = arquivo_serie(base, s, (p or {}).get("ficha")) or caminho_ref(base, s, p)
        b = ia_servico.imagem_bloco(c, largura=900) if c else None
        if b:
            blocos += [{"type": "text", "text": f"FICHA de {p['nome']} ({q}):"}, b]
    on_log(f"👁 tirando um quadro de {len(planos)} plano(s)…")
    for k, cn, v in planos[:16]:
        q = extrair_quadro(v, max(0.5, _ffprobe_dur(v) * 0.45), os.path.join(tmp, f"p{k:02d}.jpg"), 540) if alvo == "video" else v
        b = ia_servico.imagem_bloco(q, largura=540) if q else None
        if b:
            nomes = ", ".join((item(s, x) or {}).get("nome", x) + (f" (sempre com: {(item(s, x) or {}).get('detalhes')})" if (item(s, x) or {}).get("detalhes") else "")
                              for x in cn.get("quem") or []) or "(ninguém do elenco)"
            nomes += "".join(f"; objeto {o['nome']}: {o['descricao']}" for o in objetos_do_plano(s, cn))
            blocos += [{"type": "text", "text": f"PLANO {k + 1} — devia ter: {nomes}"}, b]
    on_log("👁 a IA está comparando com as fichas…")
    r = _ia(CONFERIR_SYS, blocos, CONFERIR_SCHEMA, chamar, max_tokens=2500, timeout=150, job=eid)
    res = {int(x.get("n") or 0): x for x in r.get("planos") or []}
    ruins = []
    with TRAVA:
        e = carregar_ep(base, sid, eid)
        for k, cn in enumerate(e["cenas"]):
            x = res.get(k + 1)
            if x is not None and (cn.get(alvo) or {}).get("arquivo"):
                cn[alvo]["conferido"] = {"ok": bool(x.get("ok")), "problema": str(x.get("problema") or "")[:240], "quando": time.time()}
                if not x.get("ok"):
                    ruins.append(k + 1)
        salvar_ep(base, e)
    shutil.rmtree(tmp, ignore_errors=True)
    return {"ruins": ruins, "conferidos": len(res)}


def refazer_marcados(base: str, sid: str, eid: str) -> Dict[str, Any]:
    """🔁 refaz só o que o 👁 conferir marcou como diferente (o quadro A e, depois, o vídeo; ou só o vídeo)."""
    e = carregar_ep(base, sid, eid)
    ruins_a = [k for k, cn in enumerate(e["cenas"]) if ((cn.get("img_inicio") or {}).get("conferido") or {}).get("ok") is False]
    ruins_v = [k for k, cn in enumerate(e["cenas"]) if ((cn.get("video") or {}).get("conferido") or {}).get("ok") is False and k not in ruins_a]
    if not ruins_a and not ruins_v:
        raise ShortsIAErro("Nada marcado — rode 👁 conferir antes.")
    r = {"quadros": 0, "videos": 0}
    if ruins_a:
        r["quadros"] = pedir_imagens(base, sid, eid, ruins_a, refazer=True).get("enviadas", 0)
        with TRAVA:  # o vídeo desses sai de novo sozinho quando o quadro novo chegar
            e = carregar_ep(base, sid, eid)
            for k in ruins_a:
                cn = e["cenas"][k]
                cn["video"] = dict(_slot(), estado=AGUARDANDO, arquivo=(cn.get("video") or {}).get("arquivo"),
                                   msg="⛓ esperando o quadro A novo")
            salvar_ep(base, e)
    if ruins_v:
        r["videos"] = pedir_videos(base, sid, eid, ruins_v, refazer=True).get("enviadas", 0)
    return r


# ------------------------------------------------------------------ edição + export
CORTES = {"inteiro": "o vídeo inteiro (só tira a ponta bugada do fim)", "fala": "corta o silêncio depois da última fala",
          "plano": "corta no tempo do plano"}
ANIMACOES = {"anime": "🎌 anime (12 quadros/s, como desenho à mão)", "suave": "suave (30 quadros/s)"}


def opcoes_padrao(estilo: str = "") -> Dict[str, Any]:
    o = {"velocidade": 1.15, "corte_fim": 0.35, "transicao": "rapida", "dur_transicao": 0.16, "whoosh": True, "zoom": True,
         "filtro": "vivo", "legenda": True, "legenda_pos": "meio", "legenda_estilo": "pop", "musica": None,
         "musica_vol": 0.12, "qualidade": "1080p", "modo_video": "frames", "modelo_video": MODELO_VIDEO_PADRAO,
         "corte_modo": "inteiro", "animacao": "suave", "legenda_texto": "roteiro", "encadear": True}
    if estilo.startswith("anime_") and estilo != "anime_3d":
        o.update(PRESET_ANIME)
    return o


# 🎌 o que faz parecer ANIME de verdade e não "vídeo de IA": 12 quadros/s (animação em 2s), câmera parada (sem zoom
# digital), sem filtro de saturação, legenda de anime (frase embaixo, branca com contorno, sem caixa alta), o vídeo
# inteiro (cortar no meio quebra a ação), velocidade normal e corte seco/rápido
PRESET_ANIME = {"animacao": "anime", "zoom": False, "filtro": "nenhum", "legenda_pos": "base", "legenda_estilo": "classico",
                "velocidade": 1.0, "corte_modo": "inteiro", "whoosh": False, "transicao": "corte", "legenda_texto": "roteiro"}


def normalizar_opcoes(o: Any, estilo: str = "") -> Dict[str, Any]:
    out = opcoes_padrao(estilo)
    if not isinstance(o, dict):
        return out
    for k, lo, hi in (("velocidade", 0.8, 1.6), ("corte_fim", 0.0, 2.0), ("dur_transicao", 0.06, 0.5), ("musica_vol", 0.0, 0.6)):
        try:
            if o.get(k) not in (None, ""):
                out[k] = round(max(lo, min(hi, float(o[k]))), 3)
        except (TypeError, ValueError):
            pass
    if o.get("corte_modo") in CORTES:
        out["corte_modo"] = o["corte_modo"]
    if o.get("animacao") in ANIMACOES:
        out["animacao"] = o["animacao"]
    if o.get("legenda_texto") in ("roteiro", "ouvido"):
        out["legenda_texto"] = o["legenda_texto"]
    for k in ("whoosh", "zoom", "legenda", "encadear"):
        if k in o:
            out[k] = o[k] is True or str(o[k]).lower() in ("1", "true", "on", "sim")
    if o.get("transicao") in TRANSICOES:
        out["transicao"] = o["transicao"]
    if o.get("filtro") in FILTROS:
        out["filtro"] = o["filtro"]
    if o.get("legenda_pos") in ("meio", "base", "terco", "topo"):
        out["legenda_pos"] = o["legenda_pos"]
    if o.get("legenda_estilo") in ("pop", "palavra_unica", "classico", "contorno", "preenchimento"):
        out["legenda_estilo"] = o["legenda_estilo"]
    if o.get("modo_video") in MODOS_VIDEO:
        out["modo_video"] = o["modo_video"]
    if o.get("modelo_video") in MODELOS_VIDEO:
        out["modelo_video"] = o["modelo_video"]
    if o.get("qualidade") in QUALIDADES:
        out["qualidade"] = o["qualidade"]
    if o.get("musica") and re.fullmatch(r"musica_[0-9a-f]{6}\.[a-z0-9]{2,4}", str(o["musica"])):
        out["musica"] = o["musica"]
    return out


def salvar_opcoes(base: str, sid: str, eid: str, o: Dict[str, Any]) -> Dict[str, Any]:
    with TRAVA:
        e = carregar_ep(base, sid, eid)
        musica = e["edicao"].get("musica")
        e["edicao"] = normalizar_opcoes(dict(e["edicao"], **o))
        if "musica" not in o:
            e["edicao"]["musica"] = musica
        salvar_ep(base, e)
        return e["edicao"]


def guardar_musica(base: str, sid: str, eid: str, origem: str, nome_original: str) -> str:
    ext = (os.path.splitext(nome_original)[1].lower().lstrip(".") or "mp3")[:4]
    if not re.fullmatch(r"[a-z0-9]{2,4}", ext):
        ext = "mp3"
    nome = f"musica_{secrets.token_hex(3)}.{ext}"
    pe = pasta_ep(base, sid, eid)
    shutil.copyfile(origem, os.path.join(pe, nome))
    salvar_opcoes(base, sid, eid, {"musica": nome})
    return nome


def tamanho(proporcao: str, qualidade: str) -> Tuple[int, int]:
    q = QUALIDADES.get(qualidade, 1080)
    if proporcao == "1:1":
        return q, q
    if proporcao == "16:9":
        return round(q * 16 / 9 / 2) * 2, q
    return q, round(q * 16 / 9 / 2) * 2


def _rodar(cmd: List[str], timeout: int = 3600) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise ShortsIAErro("ffmpeg: " + (r.stderr or "").strip()[-500:])


def fim_da_fala(video: str, ini: float, fim: float) -> Optional[float]:
    """Onde a última fala termina dentro de [ini, fim] (silencedetect). None = não deu pra saber / não tem silêncio no fim."""
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{ini:.3f}", "-t", f"{fim - ini:.3f}", "-i", video,
                            "-af", "silencedetect=n=-33dB:d=0.35", "-vn", "-f", "null", "-"], capture_output=True, text=True, timeout=120)
    except (subprocess.SubprocessError, OSError):
        return None
    ini_s = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", r.stderr or "")]
    fim_s = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", r.stderr or "")]
    if not ini_s or (fim_s and fim_s[-1] > ini_s[-1]):
        return None  # termina falando (ou sem silêncio nenhum)
    return ini + ini_s[-1]


def janela(cena: Dict[str, Any], dur_video: float, corte_fim: float, modo: str = "plano", video: str = "") -> Tuple[float, float]:
    """Que pedaço do vídeo da cena entra. Sempre tira a ponta bugada do fim (o gerador costuma deformar/congelar ali).
    modo "inteiro": o resto do vídeo todo (o Flow faz 8 s — cortar no meio quebra a ação); "fala": corta o silêncio
    depois da última fala (+0,6 s de reação); "plano": no tempo do plano (+0,6 s)."""
    c = cena.get("corte") or {}
    ini = max(0.0, min(float(c.get("ini") or 0.0), max(0.0, dur_video - 1.0)))
    if c.get("fim") not in (None, ""):
        fim = min(dur_video, float(c["fim"]))
    elif modo == "inteiro":
        fim = dur_video - corte_fim
    elif modo == "fala" and video and cena.get("falas"):
        fim = dur_video - corte_fim
        fala = fim_da_fala(video, ini, fim)
        if fala is not None:
            fim = min(fim, max(ini + 1.5, fala + 0.6))
    else:
        fim = min(dur_video - corte_fim, ini + float(cena.get("duracao") or dur_video) + 0.6)
    if fim - ini < 0.8:
        fim = min(dur_video, ini + 0.8)
    return round(ini, 3), round(fim, 3)


def preparar_cena(video: str, saida: str, ini: float, fim: float, W: int, H: int, op: Dict[str, Any], k: int) -> float:
    """A cena no formato final: corte, velocidade, enquadramento, zoom suave, filtro, 30 fps, áudio 48 kHz estéreo."""
    v = float(op["velocidade"])
    dur = (fim - ini) / v
    frames = max(1, int(round(dur * 30)))
    vf = [f"setpts=(PTS-STARTPTS)/{v}"]
    if op.get("animacao") == "anime":  # 🎌 animação "em 2s": 12 desenhos por segundo (cada um repetido) — tira a cara de IA lisa
        vf.append("fps=12")
    vf += [f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos", f"crop={W}:{H}", "setsar=1", "fps=30"]
    if op.get("zoom"):
        # alterna: aproxima devagar / começa perto e abre (o "respiro" que os editores de shorts fazem)
        z = f"1+0.05*on/{frames}" if k % 2 == 0 else f"1.06-0.05*on/{frames}"
        vf.append(f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps=30")
    if FILTROS.get(op.get("filtro") or ""):
        vf.append(FILTROS[op["filtro"]])
    vf.append("format=yuv420p")
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{ini:.3f}", "-t", f"{fim - ini:.3f}", "-i", video]
    tem_a = _tem_audio(video)
    if not tem_a:
        cmd += ["-f", "lavfi", "-t", f"{fim - ini + 1:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
    af = (f"atempo={v}," if abs(v - 1.0) > 0.001 else "") + "aresample=48000,aformat=channel_layouts=stereo"
    cmd += ["-vf", ",".join(vf), "-af", af, "-map", "0:v:0", "-map", "0:a:0" if tem_a else "1:a:0",
            "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", saida]
    _rodar(cmd, 1800)
    return _ffprobe_dur(saida) or dur


def _whoosh() -> Optional[str]:
    raiz = os.path.dirname(os.path.abspath(__file__))
    for c in (os.path.join(raiz, "assets", "sons", "transicoes", "whoosh.m4a"),
              os.path.join(raiz, "assets", "sons", "variados", "whoosh_6.m4a")):
        if os.path.isfile(c):
            return c
    return None


TRANS_XFADE = ("slideleft", "slideup", "smoothleft", "slideright", "zoomin")


def juntar(clipes: List[Tuple[str, float]], saida: str, op: Dict[str, Any], musica: Optional[str] = None) -> List[float]:
    """As cenas uma depois da outra: transição rápida (xfade) + whoosh, música baixinha por baixo. → onde cada cena começa."""
    T = float(op["dur_transicao"]) if op["transicao"] == "rapida" and len(clipes) > 1 else 0.0
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for c, _d in clipes:
        cmd += ["-i", c]
    fc: List[str] = []
    inicios = [0.0]
    if len(clipes) == 1:
        fc += ["[0:v]null[v]", "[0:a]anull[a0]"]
    elif T > 0:
        ant_v, ant_a, acum = "[0:v]", "[0:a]", clipes[0][1]
        for k in range(1, len(clipes)):
            off = acum - T
            inicios.append(off)
            tr = TRANS_XFADE[(k - 1) % len(TRANS_XFADE)]
            fc.append(f"{ant_v}[{k}:v]xfade=transition={tr}:duration={T:.3f}:offset={off:.3f}[v{k}]")
            fc.append(f"{ant_a}[{k}:a]acrossfade=d={T:.3f}[a{k}]")
            ant_v, ant_a = f"[v{k}]", f"[a{k}]"
            acum = off + clipes[k][1]
        fc.append(f"{ant_v}null[v]")
        fc.append(f"{ant_a}anull[a0]")
    else:
        for k in range(1, len(clipes)):
            inicios.append(inicios[-1] + clipes[k - 1][1])
        fc.append("".join(f"[{k}:v][{k}:a]" for k in range(len(clipes))) + f"concat=n={len(clipes)}:v=1:a=1[v][a0]")
    total = (inicios[-1] + clipes[-1][1]) if clipes else 0.0
    mix = ["[a0]"]
    n_in = len(clipes)
    wh = _whoosh() if op.get("whoosh") and len(clipes) > 1 else None
    if wh:
        cmd += ["-i", wh]
        idx = n_in
        n_in += 1
        cortes = inicios[1:]
        fc.append(f"[{idx}:a]asplit={len(cortes)}" + "".join(f"[w{k}]" for k in range(len(cortes))))
        for k, t in enumerate(cortes):
            ms = max(0, int((t - 0.12) * 1000))
            fc.append(f"[w{k}]volume=0.55,adelay={ms}|{ms}[wd{k}]")
            mix.append(f"[wd{k}]")
    if musica and os.path.isfile(musica) and float(op.get("musica_vol") or 0) > 0:
        cmd += ["-stream_loop", "-1", "-i", musica]
        fc.append(f"[{n_in}:a]atrim=0:{total:.3f},volume={float(op['musica_vol']):.3f},afade=t=out:st={max(0, total - 1):.3f}:d=1[mus]")
        n_in += 1
        mix.append("[mus]")
    if len(mix) > 1:
        fc.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0[a]")
    else:
        fc.append("[a0]anull[a]")
    base_cmd = cmd + ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
                      "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", saida]
    try:
        _rodar(base_cmd, 3600)
    except ShortsIAErro as exc:
        if "normalize" not in str(exc):
            raise
        _rodar([x.replace(":normalize=0", "") for x in base_cmd], 3600)  # ffmpeg antigo (< 4.4) sem normalize
    return inicios


def palavras_do_roteiro(cenas: List[Dict[str, Any]], inicios: List[float], duracoes: List[float],
                        ouvidas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """As palavras ESCRITAS das falas de cada plano, espalhadas no trecho em que o Whisper ouviu fala dentro do plano
    (sem fala ouvida: o meio do plano)."""
    import dp_legendas
    blocos = []
    import difflib
    norm = lambda w: re.sub(r"[^\w]", "", unicodedata.normalize("NFKD", str(w)).encode("ascii", "ignore").decode().lower())  # noqa: E731
    out: List[Dict[str, Any]] = []
    for cn, t0, d in zip(cenas, inicios, duracoes):
        txt = (cn.get("legenda") or "").strip() or " ".join(f["texto"] for f in cn.get("falas") or [] if f.get("texto"))
        if not txt.strip():
            continue
        dentro = [w for w in ouvidas if t0 - 0.05 <= float(w["start"]) < t0 + d]
        if not dentro:
            out += dp_legendas.palavras_dos_blocos([{"text": txt, "start": t0 + 0.4, "end": t0 + max(1.0, d - 0.5)}])
            continue
        # 🎯 casa cada palavra ESCRITA com a palavra OUVIDA (o tempo dela); as que não casam ficam entre as vizinhas
        escritas = txt.split()
        sm = difflib.SequenceMatcher(a=[norm(w) for w in escritas], b=[norm(w["word"]) for w in dentro], autojunk=False)
        tempo: Dict[int, Tuple[float, float]] = {}
        for bl in sm.get_matching_blocks():
            for k in range(bl.size):
                w = dentro[bl.b + k]
                tempo[bl.a + k] = (float(w["start"]), float(w["end"]))
        a0, b0 = float(dentro[0]["start"]), float(dentro[-1]["end"])
        k = 0
        while k < len(escritas):
            if k in tempo:
                out.append({"word": escritas[k], "start": tempo[k][0], "end": tempo[k][1]})
                k += 1
                continue
            j = k
            while j < len(escritas) and j not in tempo:
                j += 1
            ini = tempo[k - 1][1] if k - 1 in tempo else a0
            fim = tempo[j][0] if j in tempo else b0
            if fim - ini < 0.15 * (j - k):
                fim = ini + 0.25 * (j - k)
            passo = (fim - ini) / (j - k)
            for n in range(k, j):
                out.append({"word": escritas[n], "start": round(ini + (n - k) * passo, 3), "end": round(ini + (n - k + 1) * passo, 3)})
            k = j
    return out


def _palavras_das_falas(cenas: List[Dict[str, Any]], inicios: List[float], duracoes: List[float]) -> List[Dict[str, Any]]:
    """Sem Whisper: as falas escritas espalhadas no tempo de cada cena (aproximado)."""
    import dp_legendas
    blocos = []
    for cn, t0, d in zip(cenas, inicios, duracoes):
        txt = " ".join(f["texto"] for f in cn.get("falas") or [])
        if txt.strip():
            blocos.append({"text": txt, "start": t0 + 0.3, "end": t0 + max(0.8, d - 0.4)})
    return dp_legendas.palavras_dos_blocos(blocos)


def exportar(base: str, sid: str, eid: str, transcrever: Optional[Callable[..., Any]] = None,
             on_log: Callable[[str], None] = lambda _m: None) -> str:
    sincronizar_ep(base, sid, eid)
    s = carregar_serie(base, sid)
    e = carregar_ep(base, sid, eid)
    op = e["edicao"]
    pe = pasta_ep(base, sid, eid)
    usaveis = [(k, cn, _arquivo_ep(pe, cn["video"])) for k, cn in enumerate(e["cenas"])]
    faltam = [k + 1 for k, _cn, v in usaveis if not v]
    if faltam and len(faltam) == len(usaveis):
        raise ShortsIAErro("Nenhuma cena tem vídeo ainda — 🎬 gere os vídeos primeiro.")
    if faltam:
        on_log(f"⚠ cena(s) {', '.join(map(str, faltam))} sem vídeo — ficam de fora")
    W, H = tamanho(s["proporcao"], op["qualidade"])
    tmp = os.path.join(pe, "export", "_tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    clipes, cenas_usadas = [], []
    for n, (k, cn, v) in enumerate([x for x in usaveis if x[2]]):
        on_log(f"✂ cena {k + 1}: corte, velocidade {op['velocidade']}×, zoom e filtro…")
        ini, fim = janela(cn, _ffprobe_dur(v), float(op["corte_fim"]), op.get("corte_modo") or "inteiro", v)
        c = os.path.join(tmp, f"c{n:02d}.mp4")
        d = preparar_cena(v, c, ini, fim, W, H, op, n)
        clipes.append((c, d))
        cenas_usadas.append(cn)
    # 🎬 os ângulos do MESMO momento entram em corte seco (como uma cena filmada com várias câmeras); a transição
    # rápida + whoosh fica só entre um momento e outro
    grupos: List[List[int]] = []
    for n, cn in enumerate(cenas_usadas):
        if grupos and cn.get("momento") and cenas_usadas[grupos[-1][-1]].get("momento") == cn["momento"]:
            grupos[-1].append(n)
        else:
            grupos.append([n])
    blocos, dentro = [], []
    for g, ns in enumerate(grupos):
        if len(ns) == 1:
            blocos.append(clipes[ns[0]])
            dentro.append([0.0])
            continue
        on_log(f"🎬 momento “{cenas_usadas[ns[0]].get('momento')}”: {len(ns)} ângulos em corte seco…")
        cg = os.path.join(tmp, f"m{g:02d}.mp4")
        ini_g = juntar([clipes[n] for n in ns], cg, dict(op, transicao="corte", whoosh=False), None)
        blocos.append((cg, _ffprobe_dur(cg) or sum(clipes[n][1] for n in ns)))
        dentro.append(ini_g)
    on_log("🎞 juntando os momentos (transição rápida + whoosh" + (" + música" if op.get("musica") else "") + ")…")
    junto = os.path.join(tmp, "junto.mp4")
    musica = os.path.join(pe, op["musica"]) if op.get("musica") else None
    ini_blocos = juntar(blocos, junto, op, musica)
    inicios = [ini_blocos[g] + t for g, ts in enumerate(dentro) for t in ts]
    atual = junto
    if op.get("legenda"):
        palavras: List[Dict[str, Any]] = []
        if transcrever:
            on_log("💬 legendas: ouvindo as falas…")
            wav = os.path.join(tmp, "fala.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", junto, "-vn", "-ac", "1", "-ar", "16000", wav], capture_output=True, timeout=600)
            try:
                for sg in transcrever(wav, language=s["idioma"], word_timestamps=True, info={}) or []:
                    for w in sg.get("words") or []:
                        if str(w.get("word") or "").strip():
                            palavras.append({"word": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])})
            except Exception:  # noqa: BLE001
                palavras = []
        if op.get("legenda_texto", "roteiro") == "roteiro":
            # 📝 o gerador às vezes fala torto ("Sora-chan" vira "Soraçã") e o Whisper escreve o que ouviu: a legenda usa
            # o TEXTO do roteiro, com o tempo de onde a fala aconteceu
            palavras = palavras_do_roteiro(cenas_usadas, inicios, [d for _c, d in clipes], palavras)
        if not palavras:
            palavras = _palavras_das_falas(cenas_usadas, inicios, [d for _c, d in clipes])
        if palavras:
            import dp_legendas
            anime = op.get("legenda_estilo") == "classico"
            cfg = {"ativa": True, "estilo": op["legenda_estilo"], "posicao": op["legenda_pos"],
                   "tamanho": (0.042 if anime else 0.058) if s["proporcao"] != "1:1" else (0.055 if anime else 0.075),
                   "maiusculas": not anime, "max_palavras": 7 if anime else 3,
                   "fonte": "DP Poppins" if "DP Poppins" in _fontes_ok() else "DP Inter"}
            ass = dp_legendas.gerar_ass(palavras, cfg, W, H, os.path.join(tmp, "legenda.ass"))
            com = os.path.join(tmp, "legendado.mp4")
            dp_legendas.queimar(atual, ass, com)
            atual = com
    marca = s.get("marca") or {}
    if marca.get("ativa") and marca.get("texto"):
        on_log("🏷 marca do canal…")
        import marca_canal
        marca_canal.aplicar(atual, marca, tmp, op["legenda_pos"] if op.get("legenda") else "")
    final = os.path.join(pe, "export", f"{eid}_{op['qualidade']}.mp4")
    shutil.move(atual, final)
    shutil.rmtree(tmp, ignore_errors=True)
    with TRAVA:
        e = carregar_ep(base, sid, eid)
        e["export"] = {"arquivo": os.path.basename(final), "quando": time.time(), "duracao": round(_ffprobe_dur(final), 2),
                       "qualidade": op["qualidade"], "cenas": len(clipes), "faltaram": faltam}
        salvar_ep(base, e)
    return final


def _fontes_ok() -> set:
    try:
        import dp_destaques
        return set(dp_destaques._FONTE.values())
    except Exception:  # noqa: BLE001
        return set()


def texto_titulos(e: Dict[str, Any]) -> str:
    linhas = [f"{e['titulo']}", ""]
    for k, t in enumerate(e.get("titulos") or [], 1):
        linhas.append(f"{k}. {t.get('post')}")
        if t.get("pt"):
            linhas.append(f"   ({t['pt']})")
    return "\n".join(linhas) + "\n"


def resumo_ep(e: Dict[str, Any]) -> Dict[str, Any]:
    cenas = e.get("cenas") or []
    n = len(cenas)
    return {"id": e["id"], "titulo": e["titulo"], "tipo": e["origem"]["tipo"], "cenas": n,
            "imgs": sum(1 for c in cenas if (c["img_inicio"] or {}).get("arquivo")),
            "videos": sum(1 for c in cenas if (c["video"] or {}).get("arquivo")), "exportado": bool(e.get("export")),
            "criado": e.get("criado")}
