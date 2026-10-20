"""
personagens_editor.py — 🧍 as personagens do canal por cima do vídeo (v84_185)
==============================================================================

Canal com personagens (ex.: ASTRANEBEL — Mira e Vanta): as cenas são fotos/vídeos realistas e as personagens entram
como PNG transparente (as poses ✔ aprovadas do projeto conectado na aba 🧍 Personagens), só enquanto ELAS falam:

  1. quem fala quando — o roteiro com as tags ([mira|curiosa] … [vanta] … [narrador]) é casado palavra a palavra
     com o tempo das palavras do áudio (o mesmo que a legenda usa). Narrador (ou fala sem tag) = ninguém aparece;
  2. a pose — a emoção da tag ([mira|curiosa] → a pose "curiosa"), senão uma reação neutra; virada pro centro
     (personagem na direita olha pra esquerda: a pose _esq); não repete a mesma pose seguida;
  3. a aparição — um overlay do vídeo ("origem": "personagem") no lado da personagem, encostado embaixo, com
     entrada/saída (deslizar do lado, aparecer, nenhuma) e a 👄 boca mexendo enquanto ela fala (alterna a pose com a
     "_boca" dela, se existir). Você muda pose/lado/tempo na lista ou no monitor, como qualquer overlay.

De onde vem o roteiro com as tags: o que você colar na aba 🧍 Personagens do Estúdio; senão o do .zip do Gerador de
voz (multi voz) ou o da 🏭 Produção no pod. O canal: o escolhido; senão o do lote do pod / do 🕵️ Modelo de vídeo.

O jeito de cada canal fica no pacote.json do zip do canal:
  "personagens_editor": {"ativo": true, "lados": {"mira": "esquerda", "vanta": "direita"}, "altura": 0.72,
                         "entrada": "deslizar", "saida": "deslizar", "boca": true}
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

ENTRADAS = ("deslizar", "subir", "aparecer", "nenhuma")
PADRAO = {"ativo": False, "lados": {}, "altura": 0.72, "altura_vertical": 0.46, "entrada": "deslizar", "saida": "deslizar",
          "duracao_anim": 0.35, "boca": True, "antes": 0.15, "depois": 0.45, "juntar": 1.5, "min_fala": 0.6,
          "margem": 2.0,
          # 🎯 v84_186: nem toda fala — só os MELHORES momentos (frequencia 0.6 = ~60% dos momentos; 1 = todos)
          "frequencia": 0.6, "min_intervalo": 6.0, "ia": True,
          # ↔ v84_192: as poses "_esq"/"_dir" saíram olhando pro lado contrário do nome → usa a outra
          "inverter_olhar": False,
          # 🎞 v84_193: personagem que se mexe (clipe do Flow, guardado pra reusar): "ia" = a IA marca as que mais
          # ganham com movimento; "todas"; "nao". animar_max = no máximo N poses NOVAS pro Flow por vídeo
          "animar": "ia", "animar_max": 6,
          # canal com UM mascote apresentador (sem tags no roteiro): ele ilustra frases da narração
          "narrador_personagem": ""}
_CFG_USUARIO = ("lados", "altura", "altura_vertical", "entrada", "saida", "boca", "frequencia", "ia", "inverter_olhar", "animar")
_RE_TAG = re.compile(r"\[([^\[\]\n]{1,80})\]")
_NARRADOR = {"narrador", "narrator", "erzahler", "erzaehler", "narradora", "voz", "off"}
# emoção da tag → palavras que costumam estar no nome/descrição da pose
EMOCOES = {
    "curiosa": ["curios", "pergunt", "pensativ", "duvid"], "curioso": ["curios", "pergunt", "pensativ"],
    "maravilhada": ["maravilh", "encant", "fascin", "admir", "brilh"], "maravilhado": ["maravilh", "encant", "fascin"],
    "triste": ["trist", "melanc", "saudad", "chor"], "melancolica": ["melanc", "trist", "saudad"],
    "assustada": ["assust", "medo", "susto", "surpres"], "surpresa": ["surpres", "susto", "espant"],
    "feliz": ["feliz", "sorri", "alegr", "ri"], "animada": ["animad", "feliz", "empolg"],
    "ironica": ["ironic", "provoc", "sarcas", "sorriso", "debochad"], "seca": ["cetic", "seca", "brac", "indiferen", "neutra"],
    "cetica": ["cetic", "brac", "duvid", "desconfi"], "provocando": ["provoc", "ironic", "sarcas"],
    "seria": ["seri", "determin", "firme"], "determinada": ["determin", "seri", "firme"], "cansada": ["cansad", "sonolen"],
    "preocupada": ["preocup", "tens", "apreens"], "tensa": ["tens", "preocup", "apreens"], "pensativa": ["pensativ", "curios"],
    "neutra": ["neutr", "calm", "padrao"], "neutro": ["neutr", "calm"],
}


class PersEdErro(Exception):
    pass


# ------------------------------------------------------------------ texto
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def tokens_do_roteiro(texto: str, personagens: List[str], mapa_vozes: Optional[Dict[str, str]] = None,
                      vozes: Optional[List[str]] = None) -> List[Tuple[str, Optional[str], str]]:
    """Roteiro com tags → [(palavra normalizada, slug da personagem ou None = narrador, emoção)]. Tag de voz
    cadastrada (🎭 Vozes) que não é de personagem = narrador; tags que não são nem uma coisa nem outra (emoções do
    Turbo, [excited]…) não mudam quem fala."""
    pers = {_slug(p) for p in personagens}
    mapa = {_slug(k): _slug(v) for k, v in (mapa_vozes or {}).items()}
    vozes_ok = {_slug(v) for v in vozes or []}
    texto = re.sub(r"\[\[[^\]]*\]\]", " ", texto or "")
    out: List[Tuple[str, Optional[str], str]] = []
    atual: Optional[str] = None
    emocao = ""
    pos = 0
    for m in list(_RE_TAG.finditer(texto)) + [None]:
        trecho = texto[pos:m.start()] if m else texto[pos:]
        for w in trecho.split():
            n = _norm(w)
            if n:
                out.append((n, atual, emocao))
        if m is None:
            break
        pos = m.end()
        base, _, mods = m.group(1).partition("|")
        s = _slug(base)
        quem = s if s in pers else mapa.get(s) if mapa.get(s) in pers else None
        if quem is None and s not in _NARRADOR:
            # voz com outro slug que contém o da personagem ("mira_de", "vanta_v2")
            quem = next((p for p in pers if s.startswith(p + "_") or s == p), None)
            if quem is None and s not in vozes_ok:
                continue  # tag desconhecida (emoção, chamada…): fica com quem já estava falando
        atual = quem
        emocao = next((_slug(x) for x in mods.split("|") if x.strip() and "=" not in x), "") if quem else ""
    return out


def linha_do_tempo(texto: str, palavras: List[Dict[str, Any]], personagens: List[str],
                   mapa_vozes: Optional[Dict[str, str]] = None, vozes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Quem fala quando: casa o roteiro (com as tags) com as palavras do áudio (com tempo) →
    [{"slug" (None = narrador), "emocao", "start", "end", "palavras": [[ini, fim], ...], "texto"}]."""
    toks = tokens_do_roteiro(texto, personagens, mapa_vozes, vozes)
    ws = [w for w in palavras or [] if _norm(w.get("word"))]
    if not toks or not ws:
        return []
    a = [t[0] for t in toks]
    b = [_norm(w.get("word")) for w in ws]
    dono: List[Optional[int]] = [None] * len(b)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            dono[blk.b + k] = blk.a + k
    # o que não casou (palavra que o Whisper ouviu diferente) fica com o vizinho casado mais perto
    ult = None
    for i in range(len(b)):
        if dono[i] is not None:
            ult = dono[i]
        elif ult is not None:
            dono[i] = ult
    prox = None
    for i in range(len(b) - 1, -1, -1):
        if dono[i] is not None:
            prox = dono[i]
        else:
            dono[i] = prox if prox is not None else 0
    falas: List[Dict[str, Any]] = []
    for i, w in enumerate(ws):
        _n, quem, emo = toks[min(dono[i], len(toks) - 1)]
        ini, fim = float(w.get("start", 0)), float(w.get("end", w.get("start", 0)))
        pal = str(w.get("word", "")).strip()
        if falas and falas[-1]["slug"] == quem and (quem is None or falas[-1]["emocao"] == emo or not emo):
            falas[-1]["end"] = max(falas[-1]["end"], fim)
            falas[-1]["palavras"].append([ini, fim])
            falas[-1]["texto"] += " " + pal
            falas[-1]["ws"].append([ini, fim, pal])
        else:
            falas.append({"slug": quem, "emocao": emo, "start": ini, "end": fim, "palavras": [[ini, fim]],
                          "texto": pal, "ws": [[ini, fim, pal]]})
    return falas


def falas_do_pod(lista: Any, palavras: List[Dict[str, Any]], personagens: List[str],
                 mapa_vozes: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """🎭 O <nome>.falas.json do pod ([{quem, voz, inicio, fim, texto}]) → as falas no formato da linha_do_tempo, com as
    palavras (do áudio) que caem em cada uma. `quem` pode ser o slug da personagem, da voz dela ou "narrador"."""
    pers = {_slug(p) for p in personagens}
    mapa = {_slug(k): _slug(v) for k, v in (mapa_vozes or {}).items()}
    ws = [[float(w.get("start", 0)), float(w.get("end", w.get("start", 0))), str(w.get("word", "")).strip()]
          for w in palavras or [] if _norm(w.get("word"))]
    out: List[Dict[str, Any]] = []
    for x in lista or []:
        if not isinstance(x, dict):
            continue
        try:
            ini, fim = float(x.get("inicio")), float(x.get("fim"))
        except (TypeError, ValueError):
            continue
        s = _slug(x.get("quem") or "")
        quem = s if s in pers else mapa.get(s) if mapa.get(s) in pers else next((p for p in pers if s.startswith(p + "_")), None)
        dentro = [w for w in ws if ini - 0.08 <= (w[0] + w[1]) / 2 <= fim + 0.08]
        out.append({"slug": quem, "emocao": "", "start": dentro[0][0] if dentro else ini, "end": dentro[-1][1] if dentro else fim,
                    "palavras": [[a, b] for a, b, _w in dentro] or [[ini, fim]],
                    "texto": " ".join(w for _a, _b, w in dentro) or str(x.get("texto") or ""),
                    "ws": dentro or [[ini, fim, str(x.get("texto") or "")]]})
    return out


def _emocoes_do_roteiro(falas: List[Dict[str, Any]], alinhadas: List[Dict[str, Any]]) -> None:
    """A emoção da tag ([mira|curiosa]) da fala alinhada que mais cobre cada fala exata da mesma personagem."""
    for f in falas:
        if not f["slug"]:
            continue
        melhor, cob = "", 0.0
        for a in alinhadas:
            if a["slug"] != f["slug"] or not a.get("emocao"):
                continue
            c = min(f["end"], a["end"]) - max(f["start"], a["start"])
            if c > cob:
                melhor, cob = a["emocao"], c
        f["emocao"] = melhor


def falas_sem_roteiro(palavras: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Canal com UM narrador (o mascote apresenta): tudo é narração — não precisa de roteiro com tags."""
    ws = [[float(w.get("start", 0)), float(w.get("end", w.get("start", 0))), str(w.get("word", "")).strip()]
          for w in palavras or [] if _norm(w.get("word"))]
    if not ws:
        return []
    return [{"slug": None, "emocao": "", "start": ws[0][0], "end": ws[-1][1], "palavras": [[a, b] for a, b, _w in ws],
             "texto": " ".join(w for _a, _b, w in ws), "ws": ws}]


# ------------------------------------------------------------------ canal, roteiro e config
def config_do_canal(m: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    c = dict(PADRAO)
    if m:
        try:
            with open(os.path.join(m["dir"], "pacote.json"), encoding="utf-8") as f:
                pac = json.load(f) or {}
        except (OSError, ValueError):
            pac = {}
        c.update({k: v for k, v in (pac.get("personagens_editor") or {}).items() if k in PADRAO})
    c["entrada"] = c["entrada"] if c["entrada"] in ENTRADAS else "deslizar"
    c["saida"] = c["saida"] if c["saida"] in ENTRADAS else "deslizar"
    c["lados"] = {_slug(k): ("direita" if str(v).startswith("d") else "esquerda") for k, v in (c.get("lados") or {}).items()}
    for k in ("altura", "altura_vertical", "frequencia"):
        try:
            c[k] = max(0.05 if k == "frequencia" else 0.15, min(1.0, float(c[k])))
        except (TypeError, ValueError):
            c[k] = PADRAO[k]
    c["ia"] = c.get("ia") is not False
    c["inverter_olhar"] = c.get("inverter_olhar") is True
    c["animar"] = c.get("animar") if c.get("animar") in ("ia", "todas", "nao") else ("nao" if c.get("animar") is False else "ia")
    c["narrador_personagem"] = _slug(c.get("narrador_personagem") or "")
    return c


def canal_do_job(job: Dict[str, Any], base: str) -> str:
    """O canal (slug da marca) deste projeto: o escolhido na aba; senão o do lote do pod; senão o do 🕵️ Modelo."""
    esc = str((job.get("personagens_canal") or {}).get("canal") or "")
    if esc:
        return "" if esc == "-" else esc
    pp = job.get("producao_pod") or {}
    if pp.get("lote") and pp.get("item"):
        try:
            import producao_pod
            lote = producao_pod.carregar(pp["lote"])
            it = next((x for x in lote["itens"] if x["id"] == pp["item"]), None)
            if it and it.get("canal"):
                return str(it["canal"])
        except Exception:  # noqa: BLE001
            pass
    if job.get("dossie_id"):
        try:
            import dossies
            p = dossies.carregar(base, job["dossie_id"])
            iv = (dossies.MODELOS.get(str((p.get("config") or {}).get("modelo") or "")) or {}).get("identidade_visual")
            if iv:
                return str(iv)
        except Exception:  # noqa: BLE001
            pass
    return ""


def texto_do_job(job: Dict[str, Any]) -> Tuple[str, str]:
    """(roteiro com as tags, de onde veio)."""
    pc = job.get("personagens_canal") or {}
    if str(pc.get("texto") or "").strip():
        return pc["texto"], "colado na aba"
    if str(job.get("texto_falas") or "").strip():
        return job["texto_falas"], "o roteiro do áudio (multi voz)"
    pp = job.get("producao_pod") or {}
    if pp.get("lote") and pp.get("item"):
        try:
            import producao_pod
            lote = producao_pod.carregar(pp["lote"])
            it = next((x for x in lote["itens"] if x["id"] == pp["item"]), None)
            if it and it.get("texto"):
                return it["texto"], "o roteiro da 🏭 Produção no pod"
        except Exception:  # noqa: BLE001
            pass
    return "", ""


def mapa_de_vozes(job: Dict[str, Any], base: str) -> Dict[str, str]:
    """voz → personagem (o 🕵️ Modelo de vídeo guarda qual voz cada personagem usa)."""
    if not job.get("dossie_id"):
        return {}
    try:
        import dossies
        cfg = (dossies.carregar(base, job["dossie_id"]).get("config") or {})
        return {str(v): str(k) for k, v in (cfg.get("vozes_personagens") or {}).items() if v}
    except Exception:  # noqa: BLE001
        return {}


def personagens_do_canal(base: str, canal: str) -> List[Dict[str, Any]]:
    """As personagens do canal (personagens.json) com o projeto conectado e as poses prontas dele."""
    import marca_visual as mv
    import personagens_pod as pp
    m = mv.carregar(base, canal)
    try:
        with open(os.path.join(m["dir"], "personagens.json"), encoding="utf-8") as f:
            pj = json.load(f) or {}
    except (OSError, ValueError):
        pj = {}
    ligados = mv.ligacoes_personagens(m)
    lista = [{"slug": _slug(p.get("slug") or p.get("nome")), "nome": str(p.get("nome") or p.get("slug"))}
             for p in pj.get("personagens") or [] if isinstance(p, dict) and (p.get("slug") or p.get("nome"))]
    for c in mv.personagens_png(m):
        if c["slug"] not in {x["slug"] for x in lista}:
            lista.append({"slug": c["slug"], "nome": c["nome"]})
    for x in lista:
        x["projeto"] = None
        x["poses"] = []
        pid = ligados.get(x["slug"])
        if pid:
            try:
                p = pp.carregar(pid, base)
                x["projeto"] = {"id": p["id"], "nome": p["nome"]}
                x["poses"] = poses_prontas(p, base)
            except pp.PersErro:
                pass
    return lista


def poses_prontas(p: Dict[str, Any], base: str) -> List[Dict[str, Any]]:
    """As poses com imagem (✔ aprovadas primeiro, depois 👀 pra revisar) + a _boca de cada uma, se tiver."""
    import personagens_pod as pp
    info = {x["arquivo"]: x for x in p["dados"]["poses"]}
    out, bocas = [], {}
    for a, it in p["imagens"].items():
        if it.get("estado") not in ("aprovada", "pronta"):
            continue
        cam = pp.arquivo_atual(p, a, base)
        if not cam:
            continue
        x = info.get(a) or {}
        if x.get("tipo") == "boca":
            if x.get("base"):
                bocas[x["base"]] = (cam, it["estado"] == "aprovada")
            continue
        lado = x.get("lado") or ("esq" if re.search(r"_esq(\.|_|$)", a) else "dir" if re.search(r"_dir(\.|_|$)", a) else "")
        out.append({"arquivo": a, "caminho": cam, "aprovada": it["estado"] == "aprovada", "lado": lado,
                    "descricao": str(x.get("descricao_pt") or "")[:80],
                    "grupo": x.get("grupo") or "", "texto": f"{a} {x.get('descricao_pt') or ''} {x.get('prompt') or ''}".lower(),
                    "mestre": bool((p.get("mestre") or {}).get("arquivo") == a)})
    for o in out:
        b = bocas.get(o["arquivo"])
        o["boca"] = b[0] if b else None
    out.sort(key=lambda o: (not o["aprovada"], not o["mestre"], o["arquivo"]))
    return out


def olhar_para(lado_tela: str, inverter: bool = False) -> str:
    """Pra onde a pose tem que olhar: pro CENTRO (na direita da tela → _esq). inverter = as poses do canal saíram com o
    nome trocado (a "_esq" olha pra direita)."""
    o = "esq" if lado_tela == "direita" else "dir"
    return ({"esq": "dir", "dir": "esq"}[o]) if inverter else o


def par_da_pose(poses: List[Dict[str, Any]], pose: Optional[Dict[str, Any]], olhar: str) -> Optional[Dict[str, Any]]:
    """A mesma pose olhando pro lado certo (mira_curiosa_esq → mira_curiosa_dir), se existir."""
    if not pose or not pose.get("lado") or pose["lado"] == olhar:
        return pose
    outro = re.sub(r"_(esq|dir)(?=(\.|_|$))", "_" + olhar, pose["arquivo"], count=1)
    return next((o for o in poses if o["arquivo"] == outro), pose)


def escolher_pose(poses: List[Dict[str, Any]], emocao: str, lado_tela: str, evitar: str = "",
                  inverter: bool = False) -> Optional[Dict[str, Any]]:
    """A pose da fala: a da emoção; senão uma neutra/reação; olhando pro centro (na direita da tela → pose _esq)."""
    if not poses:
        return None
    olhar = olhar_para(lado_tela, inverter)
    chaves = EMOCOES.get(_slug(emocao), [_slug(emocao)[:6]] if emocao else [])

    def nota(o: Dict[str, Any]) -> float:
        n = 0.0
        if chaves and any(k and k in o["texto"] for k in chaves):
            n += 10
        if not chaves and any(k in o["texto"] for k in ("neutr", "calm")):
            n += 4
        if o["grupo"] == "reacao":
            n += 1.5
        if o["lado"] == olhar:
            n += 3
        elif o["lado"] and o["lado"] != olhar:
            n -= 3
        if o["aprovada"]:
            n += 2
        if o["boca"]:
            n += 0.5
        if evitar and o["arquivo"] == evitar:
            n -= 5  # não repete a mesma pose seguida (se tiver outra boa)
        if o["grupo"] == "objeto":
            n -= 1  # segurando objeto só quando a emoção/assunto chama
        return n
    return max(poses, key=nota)


# ------------------------------------------------------------------ as aparições (overlays)
def _janelas(palavras: List[List[float]], juntar: float = 0.25) -> List[List[float]]:
    out: List[List[float]] = []
    for a, b in sorted(palavras):
        if out and a - out[-1][1] <= juntar:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _frases(ws: List[List[Any]], min_s: float = 1.6, max_s: float = 9.0) -> List[Dict[str, Any]]:
    """As palavras da narração em frases (fim em . ? ! ou pausa longa), com 1,6–9 s cada."""
    out: List[Dict[str, Any]] = []
    cur: List[List[Any]] = []
    for k, w in enumerate(ws):
        cur.append(w)
        prox = ws[k + 1] if k + 1 < len(ws) else None
        fim_frase = str(w[2]).rstrip().endswith((".", "?", "!", "…")) or (prox is not None and prox[0] - w[1] > 0.7)
        dur = cur[-1][1] - cur[0][0]
        if (fim_frase and dur >= min_s) or dur >= max_s or prox is None:
            out.append({"start": cur[0][0], "end": cur[-1][1], "texto": " ".join(str(x[2]) for x in cur),
                        "palavras": [[x[0], x[1]] for x in cur]})
            cur = []
    return out


def candidatos(falas: List[Dict[str, Any]], pers: List[Dict[str, Any]], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Os momentos em que uma personagem PODE aparecer: as falas dela (juntando as seguidas) e — num canal com o
    mascote como apresentador ("narrador_personagem") — as frases do narrador."""
    slugs = {p["slug"] for p in pers}
    narr = _slug(cfg.get("narrador_personagem") or "")
    out: List[Dict[str, Any]] = []
    for f in falas:
        if f.get("slug") in slugs:
            if out and out[-1]["slug"] == f["slug"] and out[-1]["tipo"] == "fala" and f["start"] - out[-1]["end"] <= float(cfg["juntar"]):
                b = out[-1]
                b["end"] = f["end"]
                b["palavras"] += f["palavras"]
                b["texto"] += " " + f["texto"]
                b["emocao"] = b["emocao"] or f.get("emocao") or ""
            else:
                out.append({"slug": f["slug"], "tipo": "fala", "emocao": f.get("emocao") or "", "start": f["start"],
                            "end": f["end"], "palavras": list(f["palavras"]), "texto": f["texto"]})
        elif not f.get("slug") and narr in slugs:
            for fr in _frases(f.get("ws") or [[a, b, ""] for a, b in f["palavras"]]):
                out.append(dict(fr, slug=narr, tipo="narracao", emocao=""))
    out = [c for c in out if c["end"] - c["start"] >= float(cfg["min_fala"])]
    for k, c in enumerate(out):
        c["id"] = k + 1
    return out


def _nota_momento(c: Dict[str, Any], primeira: bool) -> float:
    t = c["texto"]
    n = 1.0
    if c.get("emocao"):
        n += 2
    if "?" in t:
        n += 1.5
    if "!" in t:
        n += 1
    dur = c["end"] - c["start"]
    n += 1 if 2 <= dur <= 8 else (-0.5 if dur > 12 else 0)
    if c["tipo"] == "fala":
        n += 2  # personagem falando conta mais que o mascote ilustrando a narração
    if primeira:
        n += 2.5  # a 1ª vez de cada uma no vídeo
    return n


def escolher_momentos(cands: List[Dict[str, Any]], cfg: Dict[str, Any], quantos: Optional[int] = None) -> List[Dict[str, Any]]:
    """Sem IA: os melhores momentos (emoção, pergunta, exclamação, a 1ª vez de cada uma, duração boa), respeitando
    o intervalo mínimo entre as aparições da mesma personagem. `frequencia` 1 = todas as falas."""
    if not cands:
        return []
    freq = max(0.0, min(1.0, float(cfg.get("frequencia", 1))))
    n = quantos if quantos is not None else (len(cands) if freq >= 1 else max(1, round(len(cands) * freq)))
    vistos, notas = set(), {}
    for c in cands:
        notas[c["id"]] = _nota_momento(c, c["slug"] not in vistos)
        vistos.add(c["slug"])
    gap = float(cfg.get("min_intervalo") or 0)
    escolhidos: List[Dict[str, Any]] = []
    for c in sorted(cands, key=lambda c: -notas[c["id"]]):
        if len(escolhidos) >= n:
            break
        if gap and freq < 1 and any(e["slug"] == c["slug"] and (abs(c["start"] - e["end"]) < gap and abs(e["start"] - c["end"]) < gap
                                                           or not (c["end"] <= e["start"] or c["start"] >= e["end"]))
                                    for e in escolhidos):
            continue
        escolhidos.append(c)
    return sorted(escolhidos, key=lambda c: c["start"])


def _lados(pers: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[str, str]:
    lados = dict(cfg.get("lados") or {})
    for k, p in enumerate(pers):  # sem lado no pacote: 1ª personagem na esquerda, 2ª na direita…
        lados.setdefault(p["slug"], "esquerda" if k % 2 == 0 else "direita")
    return lados


def escolher_com_ia(cands: List[Dict[str, Any]], pers: List[Dict[str, Any]], cfg: Dict[str, Any], quantos: int,
                    idioma: str = "", job_id: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """🤖 A IA escolhe os MELHORES momentos (não todos), a pose de cada um, a posição (lado e tamanho) e a animação.
    → [{"id", "pose", "entrada", "saida", "lado", "tamanho"}] ou None (IA desligada/erro: fica a regra)."""
    try:
        import ia_servico
        from ia_midia import _S, _I, _lista, _obj
    except Exception:  # noqa: BLE001
        return None
    if not ia_servico.ativo("personagens") or not cands:
        return None
    lados = _lados(pers, cfg)
    cat = []
    for p in pers:
        if not p.get("poses"):
            continue
        cat.append(f"{p['nome']} [{p['slug']}] — fica na {lados.get(p['slug'])} da tela; poses: "
                   + "; ".join(f"{o['arquivo']}" + (f" ({o['descricao']})" if o.get("descricao") else "") for o in p["poses"][:80]))
    linhas = [f"[{c['id']}] {c['start']:.1f}-{c['end']:.1f}s {c['slug']} ({'fala' if c['tipo'] == 'fala' else 'narração'}"
              + (f", {c['emocao']}" if c.get("emocao") else "") + f"): {c['texto'][:160]}"
              + (f" || image on screen: {c['cena'][:140]}" if c.get("cena") else "") for c in cands[:400]]
    system = (
        "You direct the on-screen appearances of a YouTube channel's characters. Each character is a transparent PNG that "
        "slides/pops over the video at the side of the screen. You get the candidate MOMENTS (a character speaking, or — for "
        "a mascot presenter — a narration sentence it can illustrate) and each character's POSE catalog.\n"
        f"Choose about {quantos} of the BEST moments (not all — a character on screen all the time is tiring): the first time "
        "each one speaks, questions, surprise, jokes, strong emotions, turning points, conclusions. Skip neutral filler and "
        "keep them spread out (not two appearances of the same character a few seconds apart).\n"
        "For each chosen moment pick the pose (EXACT file name from that character's catalog) that best acts what is said "
        "(holding an object only when the line talks about it), and the entrance/exit animation: "
        + ", ".join(ENTRADAS) + " (deslizar = slides in from its side, subir = rises from the bottom, aparecer = fades in, "
        "nenhuma = cut). Vary the animations a little; quick lines → aparecer/nenhuma.\n"
        "Also choose the POSITION: \"lado\" = esquerda or direita (keep each character on its usual side unless the image "
        "on screen has its main subject on that side — then use the emptier side; two characters close in time stay on "
        "opposite sides) and \"tamanho\" = pequeno, medio or grande (grande for big emotional beats, pequeno for quick "
        "remarks or when the image is busy; most are medio).\n"
        "\"animar\": true for the appearances that most deserve real MOTION (an animated clip instead of a still image): "
        "longer lines, strong emotion, a gesture, a reveal — about a third of them; false for the rest.")
    conteudo = ("CHARACTERS AND POSES:\n" + "\n".join(cat) + "\n\nMOMENTS:\n" + "\n".join(linhas)
                + (f"\n\nLanguage of the video: {idioma}" if idioma else ""))
    schema = _obj({"aparicoes": _lista(_obj({"id": _I, "pose": _S, "entrada": _S, "saida": _S, "lado": _S, "tamanho": _S, "animar": {"type": "boolean"}}))})
    try:
        r = ia_servico.chamar("personagens", system, conteudo, schema=schema, max_tokens=4000, job=job_id, timeout=120)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(r, dict) or not isinstance(r.get("aparicoes"), list):
        return None
    ids = {c["id"] for c in cands}
    out = [x for x in r["aparicoes"] if isinstance(x, dict) and isinstance(x.get("id"), int) and x["id"] in ids]
    return out or None


TAMANHOS = {"pequeno": 0.8, "medio": 1.0, "grande": 1.18}


def _tamanho(altura: float, vertical: bool, fator: float = 1.0) -> float:
    """A largura (% da tela) da PNG 2:3 pra personagem ocupar `altura` da altura da tela (ela ocupa ~95% da PNG)."""
    W, H = (1080, 1920) if vertical else (1920, 1080)
    return round(min(100.0, (min(0.98, altura * fator) / 0.95) * H / 1.5 / W * 100), 2)


def posicao(lado: str, size: float, vertical: bool, margem: float) -> Tuple[float, float]:
    """📐 v84_191: o CENTRO da PNG (x %, y %) — encostada embaixo, a `margem` % da borda do lado dela.
    (O monitor do Estúdio centraliza o overlay em x/y; o render usa "ancora": "centro" — os dois batem.)"""
    W, H = (1080, 1920) if vertical else (1920, 1080)
    alt = size / 100 * W * 1.5 / H * 100  # altura da PNG em % da tela
    x = margem + size / 2
    x = x if lado == "esquerda" else 100 - x
    return round(x, 2), round(100 - alt / 2, 2)


def montar(escolhidos: List[Dict[str, Any]], pers: List[Dict[str, Any]], cfg: Dict[str, Any], duracao: float,
           vertical: bool = False, ia: Optional[Dict[int, Dict[str, Any]]] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Os momentos escolhidos → as aparições (pose, lado, tamanho, animação, janelas da boca)."""
    por = {p["slug"]: p for p in pers}
    lados = _lados(pers, cfg)
    altura = float(cfg["altura_vertical"] if vertical else cfg["altura"])
    margem = float(cfg["margem"])
    out: List[Dict[str, Any]] = []
    avisos: List[str] = []
    ultima_pose: Dict[str, str] = {}
    sem_pose = set()
    for b in escolhidos:
        p = por.get(b["slug"])
        if not p or not p.get("poses"):
            sem_pose.add(b["slug"])
            continue
        dica = (ia or {}).get(b.get("id")) or {}
        lado = dica.get("lado") if dica.get("lado") in ("esquerda", "direita") else lados.get(b["slug"], "esquerda")
        tam = dica.get("tamanho") if dica.get("tamanho") in TAMANHOS else "medio"
        size = _tamanho(altura, vertical, TAMANHOS[tam])
        xc, yc = posicao(lado, size, vertical, margem)
        pose = next((o for o in p["poses"] if o["arquivo"] == dica.get("pose")), None) \
            or escolher_pose(p["poses"], b.get("emocao") or "", lado, ultima_pose.get(b["slug"], ""),
                             bool(cfg.get("inverter_olhar")))
        pose = par_da_pose(p["poses"], pose, olhar_para(lado, bool(cfg.get("inverter_olhar"))))  # a IA pode errar o lado
        ultima_pose[b["slug"]] = pose["arquivo"]
        ini = max(0.0, b["start"] - float(cfg["antes"]))
        fim = min(duracao or b["end"] + 1, b["end"] + float(cfg["depois"]))
        fala_dela = b.get("tipo", "fala") == "fala"
        out.append({"slug": b["slug"], "nome": p["nome"], "start": round(ini, 3), "end": round(fim, 3), "lado": lado,
                    "emocao": b.get("emocao") or "", "pose": pose["arquivo"], "caminho": pose["caminho"],
                    "boca": pose["boca"] if cfg.get("boca") and fala_dela else None,
                    "boca_janelas": [[round(a, 3), round(c, 3)] for a, c in _janelas(b["palavras"])] if fala_dela else [],
                    "texto": b["texto"][:200], "size_percent": size, "altura_base": altura,
                    "entrada": dica.get("entrada") if dica.get("entrada") in ENTRADAS else cfg["entrada"],
                    "saida": dica.get("saida") if dica.get("saida") in ENTRADAS else cfg["saida"],
                    "tamanho": tam, "vertical": vertical, "x_percent": xc, "y_percent": yc,
                    "projeto_id": (p.get("projeto") or {}).get("id"), "descricao_pose": pose.get("descricao") or "",
                    "animar": bool(dica.get("animar")) if cfg.get("animar") == "ia" else cfg.get("animar") == "todas"})
    for s_ in sorted(sem_pose):
        nome = (por.get(s_) or {}).get("nome") or s_
        avisos.append(f"{nome} tem momento pra aparecer mas não tem pose pronta — conecte o projeto dela na aba 🧍 Personagens e gere/aprove as poses")
    return out, avisos


def aparicoes(falas: List[Dict[str, Any]], pers: List[Dict[str, Any]], cfg: Dict[str, Any], duracao: float,
              vertical: bool = False) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Sem IA: candidatos → os melhores momentos (frequência) → as aparições."""
    return montar(escolher_momentos(candidatos(falas, pers, cfg), cfg), pers, cfg, duracao, vertical)


def pedir_animacoes(job: Dict[str, Any], base: str, cfg: Dict[str, Any], job_dir: str, enviar_flow: bool = True) -> Tuple[int, str]:
    """🎞 As aparições marcadas pra animar: pose que já tem clipe → entra; senão vai pro Flow (no máximo animar_max
    poses NOVAS por vídeo — o resto fica parado até ter o clipe). → (quantas poses foram pro Flow, aviso)."""
    if cfg.get("animar") == "nao":
        return 0, ""
    try:
        import personagens_animar as PA
    except Exception:  # noqa: BLE001
        return 0, ""
    pedidas, erro = set(), ""
    limite = max(0, int(cfg.get("animar_max") or 0)) if enviar_flow else 0  # 🛑 automático: nunca abre o Flow sozinho
    sugeridas = sum(1 for ov in job.get("overlays") or [] if ov.get("origem") == "personagem" and ov.get("anim_pedida"))
    for ov in job.get("overlays") or []:
        if ov.get("origem") != "personagem" or not ov.get("anim_pedida") or not ov.get("projeto_id"):
            continue
        png = ov.get("pose_original") or (ov.get("source") or {}).get("value")
        tipo = ov.get("anim_tipo") or "fala"
        try:
            ja = PA.item(ov["projeto_id"], base, png, tipo)
            if ja and ja.get("estado") in ("pronto",) + PA.ESPERA:
                continue
            k = PA.chave(png, tipo)
            if k in pedidas or len(pedidas) >= limite:
                continue
            PA.pedir(base, ov["projeto_id"], {"caminho": png, "arquivo": ov.get("pose"), "descricao": ov.get("descricao_pose")},
                     tipo, ov.get("nome_personagem") or "", ov.get("fala") or "")
            pedidas.add(k)
        except Exception as exc:  # noqa: BLE001
            erro = str(exc)[:200]
    try:
        PA.aplicar_prontas(job, base, job_dir)
    except Exception:  # noqa: BLE001
        pass
    aviso = (f"🎞 {len(pedidas)} pose(s) foram pro Flow pra virar animação (o clipe entra sozinho quando chegar e fica "
             "guardado pra reusar)" if pedidas else
             f"🎞 a IA sugeriu animar {sugeridas} aparição(ões) — clique em 🎞 Animar as sugeridas (o Flow só abre quando você pede)"
             if sugeridas and not enviar_flow else "") + (f" · ⚠ animação: {erro}" if erro else "")
    return len(pedidas), aviso


def animar_uma(job: Dict[str, Any], oid: str, base: str, job_dir: str, dados: Dict[str, Any]) -> Dict[str, Any]:
    """🎞 Você pediu: anima ESTA aparição (tipo fala/parada, só os primeiros N s ida e volta, repetir ou uma vez)."""
    import personagens_animar as PA
    ov = next((x for x in job.get("overlays") or [] if x.get("id") == oid and x.get("origem") == "personagem"), None)
    if not ov:
        raise PersEdErro("Aparição não encontrada.")
    if not ov.get("projeto_id"):  # aparição de antes desta versão: acha o projeto pela personagem
        canal = canal_do_job(job, base)
        p = next((x for x in personagens_do_canal(base, canal) if x["slug"] == ov.get("personagem")), None) if canal else None
        ov["projeto_id"] = ((p or {}).get("projeto") or {}).get("id")
        if not ov["projeto_id"]:
            raise PersEdErro("Essa personagem não tem projeto conectado (aba 🧍 Personagens).")
    if dados.get("tipo") in PA.TIPOS:
        ov["anim_tipo"] = dados["tipo"]
    if dados.get("modo") in PA.MODOS:
        ov["anim_modo"] = dados["modo"]
    if "segundos" in dados:
        try:
            ov["anim_segundos"] = max(0.0, min(8.0, float(dados.get("segundos") or 0)))
        except (TypeError, ValueError):
            pass
        ov.pop("anim_video", None)  # corta de novo com o novo tamanho
    ov["anim_pedida"] = True
    ov.pop("anim_desligada", None)
    png = ov.get("pose_original") or (ov.get("source") or {}).get("value")
    if not png or not os.path.isfile(png):
        png = (ov.get("source") or {}).get("value")
    try:
        it = PA.pedir(base, ov["projeto_id"], {"caminho": png, "arquivo": ov.get("pose"), "descricao": ov.get("descricao_pose")},
                      ov.get("anim_tipo") or "fala", ov.get("nome_personagem") or "", ov.get("fala") or "",
                      str(dados.get("extra") or ""), bool(dados.get("refazer")))
    except PA.AnimErro as exc:
        raise PersEdErro(str(exc))
    ov["anim_estado"], ov["anim_msg"] = it.get("estado"), it.get("erro") or it.get("msg")
    ov["manual"] = True
    PA.aplicar_prontas(job, base, job_dir)
    return ov


def _cenas_nos_candidatos(job: Dict[str, Any], cands: List[Dict[str, Any]]) -> None:
    """A descrição da imagem que está na tela no meio de cada momento (pra 🤖 IA escolher o lado mais vazio)."""
    segs = job.get("pending_segments") or job.get("video_segments") or []
    if not isinstance(segs, list):
        return
    for c in cands:
        meio = (float(c["start"]) + float(c["end"])) / 2
        sg = next((x for x in segs if isinstance(x, dict)
                   and float(x.get("start") or 0) <= meio < float(x.get("end") or 0)), None)
        if sg:
            t = str(sg.get("visual") or sg.get("query") or sg.get("prompt") or "").strip()
            if t:
                c["cena"] = t


def aplicar(job: Dict[str, Any], job_dir: str, base: str, palavras: List[Dict[str, Any]],
            canal: str = "", texto: str = "", cfg_extra: Optional[Dict[str, Any]] = None, job_id: Optional[str] = None,
            enviar_flow: bool = True) -> Dict[str, Any]:
    """🧍 Põe (ou refaz) as aparições das personagens nos MELHORES momentos: tira as automáticas de antes (as que você
    mexeu à mão ficam) e cria as novas como overlays. Com a 🤖 IA (recurso "personagens"), ela escolhe os momentos, a
    pose e a animação; sem, a regra. → {"n", "falas", "avisos", "de_onde", "por"}."""
    import marca_visual as mv
    pc = job.setdefault("personagens_canal", {})
    if canal:
        pc["canal"] = canal
    if texto:
        pc["texto"] = texto
    canal = canal_do_job(job, base)
    if not canal:
        raise PersEdErro("Escolha o canal (o zip do canal importado em 🎨 Identidade visual).")
    try:
        m = mv.carregar(base, canal)
    except mv.MarcaErro as exc:
        raise PersEdErro(f"Canal não encontrado: {exc}")
    cfg = config_do_canal(m)
    cfg.update({k: v for k, v in (pc.get("config") or {}).items() if k in PADRAO})
    cfg.update({k: v for k, v in (cfg_extra or {}).items() if k in PADRAO})
    pc["config"] = {k: cfg[k] for k in _CFG_USUARIO}
    pers = personagens_do_canal(base, canal)
    if not pers:
        raise PersEdErro("Esse canal não tem personagens (personagens.json ou personagens/<slug>.json no zip do canal).")
    roteiro, de_onde = texto_do_job(job)
    slugs = [p["slug"] for p in pers]
    narr = _slug(cfg.get("narrador_personagem") or "")
    mapa = mapa_de_vozes(job, base)
    try:
        import multivoz
        cad = multivoz.por_slug()
    except Exception:  # noqa: BLE001
        cad = {}
    for vs, v in cad.items():  # a voz "Mira (alemã)" com slug "voz_3" → a Mira
        n = _slug((v or {}).get("nome"))
        quem = next((x for x in slugs if n == x or x in n.split("_")), None)
        if quem:
            mapa.setdefault(vs, quem)
    exatas = falas_do_pod(job.get("falas_pod"), palavras, slugs, mapa) if job.get("falas_pod") else []
    if exatas and any(f["slug"] for f in exatas):
        falas = exatas  # 🎭 v84_187: o pod disse quem falou de que segundo a que segundo
        if roteiro.strip():  # a emoção ([mira|curiosa]) vem do roteiro
            _emocoes_do_roteiro(falas, linha_do_tempo(roteiro, palavras, slugs, mapa, list(cad)))
        de_onde = "o pod (quem falou quando, exato)"
    elif not roteiro.strip():
        if narr not in slugs:
            raise PersEdErro("Falta o roteiro com as tags de quem fala ([mira] …, [vanta] …, [narrador] …) — cole na aba.")
        falas, de_onde = falas_sem_roteiro(palavras), "a narração (o mascote apresenta)"
    else:
        falas = linha_do_tempo(roteiro, palavras, slugs, mapa, list(cad))
    if not falas:
        raise PersEdErro("Não consegui casar o roteiro com as palavras do áudio (o projeto tem legenda/transcrição?).")
    cands = candidatos(falas, pers, cfg)
    _cenas_nos_candidatos(job, cands)
    if not cands:
        raise PersEdErro("Não achei momento pra personagem: as tags do roteiro precisam ser os nomes delas ("
                         + ", ".join(f"[{p['slug']}]" for p in pers) + ").")
    vertical = str(job.get("orientation") or "16:9") == "9:16"
    duracao = float(job.get("total_duration") or 0) or max(f["end"] for f in falas) + 1
    freq = max(0.0, min(1.0, float(cfg.get("frequencia", 1))))
    quantos = len(cands) if freq >= 1 else max(1, round(len(cands) * freq))
    por = "regra"
    ia = escolher_com_ia(cands, pers, cfg, quantos, str(job.get("language") or ""), job_id) if cfg.get("ia", True) else None
    if ia:
        por = "ia"
        idx = {c["id"]: c for c in cands}
        escolhidos = sorted((idx[x["id"]] for x in ia), key=lambda c: c["start"])
        novas, avisos = montar(escolhidos, pers, cfg, duracao, vertical, {x["id"]: x for x in ia})
    else:
        novas, avisos = montar(escolher_momentos(cands, cfg, quantos), pers, cfg, duracao, vertical)
    pasta = os.path.join(job_dir, "personagens")
    os.makedirs(pasta, exist_ok=True)
    ficam = [ov for ov in job.get("overlays") or [] if ov.get("origem") != "personagem" or ov.get("manual")]
    ocupados = [(ov["start"], ov["end"], ov.get("personagem")) for ov in ficam if ov.get("origem") == "personagem"]
    import uuid
    criadas = []
    for a in novas:
        if any(s_ == a["slug"] and not (a["end"] <= i or a["start"] >= f) for i, f, s_ in ocupados):
            continue  # você já ajustou uma aparição dela nesse pedaço
        criadas.append(overlay_de(a, pasta, cfg, uuid.uuid4().hex[:8]))
    job["overlays"] = ficam + criadas
    n_anim, aviso_anim = pedir_animacoes(job, base, cfg, job_dir, enviar_flow)
    if aviso_anim:
        avisos.append(aviso_anim)
    pc.update(ativo=True, canal=canal, n=len(criadas), avisos=avisos, de_onde=de_onde, por=por, candidatos=len(cands),
              falas=[{k: f[k] for k in ("slug", "emocao", "start", "end")} | {"texto": f["texto"][:120]} for f in falas][:800])
    return {"n": len(criadas), "falas": len(cands), "avisos": avisos, "de_onde": de_onde, "canal": canal, "por": por,
            "animando": n_anim}


def _copiar(origem: str, pasta: str) -> str:
    destino = os.path.join(pasta, os.path.basename(origem))
    if not os.path.isfile(destino) or os.path.getmtime(destino) < os.path.getmtime(origem):
        shutil.copyfile(origem, destino)
    return destino


def overlay_de(a: Dict[str, Any], pasta: str, cfg: Dict[str, Any], oid: str) -> Dict[str, Any]:
    png = _copiar(a["caminho"], pasta)
    return {"id": oid, "origem": "personagem", "personagem": a["slug"], "nome_personagem": a["nome"], "pose": a["pose"],
            "lado": a["lado"], "emocao": a["emocao"], "fala": a["texto"],
            "source": {"source": "local_file", "value": png, "kind": "image"},
            "start": a["start"], "end": a["end"], "position": "bottom-left" if a["lado"] == "esquerda" else "bottom-right",
            "size_percent": a["size_percent"], "x_percent": a["x_percent"], "y_percent": a["y_percent"], "ancora": "centro",
            "tamanho": a.get("tamanho") or "medio", "vertical": bool(a.get("vertical")), "altura_base": a.get("altura_base"),
            "anim_in": a.get("entrada") or cfg["entrada"], "anim_out": a.get("saida") or cfg["saida"],
            "anim_dur": float(cfg["duracao_anim"]),
            "boca_path": _copiar(a["boca"], pasta) if a.get("boca") else None, "boca_janelas": a["boca_janelas"],
            # 🎞 v84_193: a animação (personagens_animar.py)
            "projeto_id": a.get("projeto_id"), "pose_original": a.get("caminho"), "descricao_pose": a.get("descricao_pose") or "",
            "anim_tipo": "fala" if a["boca_janelas"] else "parada", "anim_modo": "repetir", "anim_segundos": 0,
            "anim_pedida": bool(a.get("animar"))}


def remover(job: Dict[str, Any]) -> int:
    antes = len(job.get("overlays") or [])
    job["overlays"] = [ov for ov in job.get("overlays") or [] if ov.get("origem") != "personagem"]
    job.setdefault("personagens_canal", {})["ativo"] = False
    return antes - len(job["overlays"])


def trocar_pose(job: Dict[str, Any], oid: str, arquivo: str, base: str, job_dir: str) -> Dict[str, Any]:
    ov = next((x for x in job.get("overlays") or [] if x.get("id") == oid and x.get("origem") == "personagem"), None)
    if not ov:
        raise PersEdErro("Aparição não encontrada.")
    canal = canal_do_job(job, base)
    p = next((x for x in personagens_do_canal(base, canal) if x["slug"] == ov["personagem"]), None) if canal else None
    pose = next((x for x in (p or {}).get("poses") or [] if x["arquivo"] == arquivo), None)
    if not pose:
        raise PersEdErro("Pose não encontrada (ela tem imagem no projeto da personagem?).")
    pasta = os.path.join(job_dir, "personagens")
    os.makedirs(pasta, exist_ok=True)
    ov["source"] = {"source": "local_file", "value": _copiar(pose["caminho"], pasta), "kind": "image"}
    ov["pose"] = arquivo
    ov["boca_path"] = _copiar(pose["boca"], pasta) if pose.get("boca") else None
    ov["manual"] = True
    return ov


def _inverter_do_job(job: Dict[str, Any], base: str) -> bool:
    pc = job.get("personagens_canal") or {}
    if "inverter_olhar" in (pc.get("config") or {}):
        return bool(pc["config"]["inverter_olhar"])
    canal = canal_do_job(job, base)
    try:
        import marca_visual as mv
        return bool(config_do_canal(mv.carregar(base, canal)).get("inverter_olhar")) if canal else False
    except Exception:  # noqa: BLE001
        return False


def virar_pose(job: Dict[str, Any], oid: str, base: str, job_dir: str) -> None:
    """Depois de trocar o lado: a mesma pose olhando pro centro (se existir a _esq/_dir dela)."""
    ov = next((x for x in job.get("overlays") or [] if x.get("id") == oid and x.get("origem") == "personagem"), None)
    canal = canal_do_job(job, base) if ov else ""
    p = next((x for x in personagens_do_canal(base, canal) if x["slug"] == ov["personagem"]), None) if canal else None
    poses = (p or {}).get("poses") or []
    atual = next((o for o in poses if o["arquivo"] == ov.get("pose")), None) if ov else None
    certa = par_da_pose(poses, atual, olhar_para(ov.get("lado") or "esquerda", _inverter_do_job(job, base))) if atual else None
    if certa and certa is not atual:
        manual = ov.get("manual")
        trocar_pose(job, oid, certa["arquivo"], base, job_dir)
        ov["manual"] = manual or True


def mudar(job: Dict[str, Any], oid: str, dados: Dict[str, Any]) -> Dict[str, Any]:
    ov = next((x for x in job.get("overlays") or [] if x.get("id") == oid and x.get("origem") == "personagem"), None)
    if not ov:
        raise PersEdErro("Aparição não encontrada.")
    if dados.get("lado") in ("esquerda", "direita") or dados.get("tamanho") in TAMANHOS:
        if dados.get("lado") in ("esquerda", "direita"):
            ov["lado"] = dados["lado"]
        vert = bool(ov.get("vertical"))
        if dados.get("tamanho") in TAMANHOS:
            ov["tamanho"] = dados["tamanho"]
            base_alt = float(ov.get("altura_base") or (PADRAO["altura_vertical"] if vert else PADRAO["altura"]))
            ov["size_percent"] = _tamanho(base_alt, vert, TAMANHOS[dados["tamanho"]])
        ov["x_percent"], ov["y_percent"] = posicao(ov.get("lado") or "esquerda", float(ov.get("size_percent") or 20), vert,
                                                   float(PADRAO["margem"]))
        ov["ancora"] = "centro"
        ov["position"] = "bottom-left" if ov["lado"] == "esquerda" else "bottom-right"
    for k in ("anim_in", "anim_out"):
        if dados.get(k) in ENTRADAS:
            ov[k] = dados[k]
    if "anim_usar" in dados:  # 🎞 usar o clipe ou a imagem parada
        if dados["anim_usar"]:
            ov.pop("anim_desligada", None)
        else:
            ov["anim_desligada"] = True
    if dados.get("anim_modo") in ("repetir", "uma_vez"):
        ov["anim_modo"] = dados["anim_modo"]
    if "boca" in dados and not dados["boca"]:
        ov["boca_desligada"] = True
    elif dados.get("boca"):
        ov.pop("boca_desligada", None)
    ov["manual"] = True
    return ov


def url_anim(job_id: str, ov: Dict[str, Any]) -> Optional[str]:
    """O clipe animado da aparição pro monitor do Estúdio (WebM com transparência), se estiver em uso."""
    if ov.get("origem") != "personagem" or ov.get("anim_desligada") or not ov.get("anim_video") \
            or not os.path.isfile(str(ov.get("anim_video"))):
        return None
    return f"/job/{job_id}/personagens/{ov['id']}/animacao.webm?v={int(os.path.getmtime(ov['anim_video']))}"


def para_render(ov: Dict[str, Any]) -> Dict[str, Any]:
    """Os campos extras que o video_assembler.apply_overlays usa pra animar a personagem."""
    anim = ov.get("anim_video") if not ov.get("anim_desligada") and ov.get("anim_video") and os.path.isfile(ov["anim_video"]) else None
    boca = None if anim else ov.get("boca_path") if not ov.get("boca_desligada") and ov.get("boca_path") and os.path.isfile(ov["boca_path"]) else None
    return {"personagem": ov.get("personagem"), "x_percent": ov.get("x_percent", 3), "y_percent": ov.get("y_percent", 100),
            "ancora": ov.get("ancora") or "",
            "anim_in": ov.get("anim_in") or "nenhuma", "anim_out": ov.get("anim_out") or "nenhuma",
            "anim_dur": float(ov.get("anim_dur") or 0.35), "lado": ov.get("lado") or "esquerda",
            "boca_path": boca, "boca_janelas": ov.get("boca_janelas") or [],
            "anim_video": anim, "anim_modo": ov.get("anim_modo") or "repetir"}


def estado(job: Dict[str, Any], base: str) -> Dict[str, Any]:
    """Pra aba 🧍 Personagens do Estúdio."""
    import marca_visual as mv
    canal = canal_do_job(job, base)
    pc = job.get("personagens_canal") or {}
    roteiro, de_onde = texto_do_job(job)
    canais = []
    for x in mv.listar(base):
        try:
            m = mv.carregar(base, x["slug"])
        except mv.MarcaErro:
            continue
        if os.path.isfile(os.path.join(m["dir"], "personagens.json")) or mv.personagens_png(m):
            canais.append({"slug": x["slug"], "nome": x.get("nome") or x["slug"]})
    pers, cfg = [], dict(PADRAO)
    if canal:
        try:
            pers = [{k: v for k, v in p.items() if k != "poses"} | {"poses": [{"arquivo": o["arquivo"], "aprovada": o["aprovada"],
                                                                                "boca": bool(o["boca"])} for o in p["poses"]]}
                    for p in personagens_do_canal(base, canal)]
            cfg = config_do_canal(mv.carregar(base, canal))
            cfg.update({k: v for k, v in (pc.get("config") or {}).items() if k in PADRAO})
        except Exception:  # noqa: BLE001
            pers = []
    aps = [{k: ov.get(k) for k in ("id", "personagem", "nome_personagem", "pose", "lado", "start", "end", "emocao", "fala",
                                    "anim_in", "anim_out", "manual", "tamanho",
                                    "anim_tipo", "anim_modo", "anim_segundos", "anim_estado", "anim_msg", "anim_pedida")}
           | {"anim_pronta": bool(ov.get("anim_video")) and os.path.isfile(str(ov.get("anim_video"))),
              "anim_usando": bool(ov.get("anim_video")) and not ov.get("anim_desligada")}
           | {"boca": bool(ov.get("boca_path")) and not ov.get("boca_desligada")}
           for ov in job.get("overlays") or [] if ov.get("origem") == "personagem"]
    try:
        import ia_servico
        ia_on = ia_servico.ativo("personagens")
    except Exception:  # noqa: BLE001
        ia_on = False
    cfg_tela = {k: cfg[k] for k in _CFG_USUARIO}
    cfg_tela["lados"] = _lados(pers, cfg)  # o lado de cada uma como vai ficar (sem lado no pacote: alterna)
    return {"canal": canal, "canais": canais, "personagens": pers, "config": cfg_tela,
            "ia_ligada": ia_on, "por": pc.get("por") or "", "candidatos": pc.get("candidatos") or 0,
            "mascote_narrador": bool(cfg.get("narrador_personagem")),
            "texto": pc.get("texto") or "", "tem_roteiro": bool(roteiro.strip()) or bool(cfg.get("narrador_personagem")),
            "roteiro_de": de_onde, "roteiro_inicio": roteiro[:400], "aparicoes": sorted(aps, key=lambda x: x["start"] or 0),
            "avisos": pc.get("avisos") or [], "ativo": bool(pc.get("ativo")), "entradas": list(ENTRADAS),
            "auto_canal": bool(cfg.get("ativo"))}


def auto(job: Dict[str, Any], job_dir: str, base: str, palavras: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Projeto novo de um canal com "personagens_editor": {"ativo": true}: já põe as personagens (sem erro se faltar algo)."""
    try:
        canal = canal_do_job(job, base)
        if not canal:
            return None
        import marca_visual as mv
        if not config_do_canal(mv.carregar(base, canal)).get("ativo") or (job.get("personagens_canal") or {}).get("auto") is False:
            return None
        r = aplicar(job, job_dir, base, palavras, enviar_flow=False)  # 🛑 v84_197: o automático não abre o Flow
        return r
    except Exception as exc:  # noqa: BLE001
        job.setdefault("personagens_canal", {})["avisos"] = [f"🧍 não deu pra pôr as personagens sozinho: {str(exc)[:200]}"]
        return None


# ------------------------------------------------------------------ rotas
def registrar(app, obter: Callable[[str], Optional[Dict[str, Any]]], salvar: Callable[[str], None],
              job_dir: Callable[[str], str], palavras_de: Callable[[Dict[str, Any]], List[Dict[str, Any]]], base: str) -> None:
    from flask import jsonify, request

    def _job(job_id: str):
        job = obter(job_id)
        if not job:
            raise PersEdErro("Projeto não encontrado.")
        return job

    def _resp(fn, job_id: str = ""):
        try:
            r = fn()
        except PersEdErro as exc:
            return jsonify({"erro": str(exc)}), 400
        job = obter(job_id) if job_id else None
        if job is not None and isinstance(r, dict):  # os overlays no formato do Estúdio (a timeline/monitor atualizam)
            r["overlays"] = [dict(ov, _anim_url=url_anim(job_id, ov), _url=(f"/job/{job_id}/overlay/{ov['id']}" if (ov.get("source") or {}).get("source") == "local_file"
                                            else (ov.get("source") or {}).get("value") if (ov.get("source") or {}).get("source") == "url" else None))
                             for ov in job.get("overlays") or []]
        return jsonify(r)

    @app.route("/job/<job_id>/personagens/estado", methods=["GET"])
    def personagens_editor_estado(job_id: str):
        def _f():
            job = _job(job_id)
            if any(ov.get("origem") == "personagem" and ov.get("anim_pedida") and not ov.get("anim_video")
                   for ov in job.get("overlays") or []):
                try:  # 🎞 clipe que chegou do Flow entra sozinho
                    import personagens_animar as PA
                    if PA.aplicar_prontas(job, base, job_dir(job_id)):
                        salvar(job_id)
                except Exception:  # noqa: BLE001
                    pass
            return estado(job, base)
        return _resp(_f, job_id)

    @app.route("/job/<job_id>/personagens/animar-sugeridas", methods=["POST"])
    def personagens_editor_animar_sugeridas(job_id: str):
        def _f():
            job = _job(job_id)
            import marca_visual as mv
            canal = canal_do_job(job, base)
            cfg = config_do_canal(mv.carregar(base, canal)) if canal else dict(PADRAO)
            cfg.update({k: v for k, v in ((job.get("personagens_canal") or {}).get("config") or {}).items() if k in PADRAO})
            if cfg.get("animar") == "nao":
                cfg["animar"] = "ia"
            n, aviso = pedir_animacoes(job, base, cfg, job_dir(job_id), True)
            salvar(job_id)
            return dict(estado(job, base), enviadas=n, aviso=aviso)
        return _resp(_f, job_id)

    @app.route("/job/<job_id>/personagens/<oid>/animar", methods=["POST"])
    def personagens_editor_animar(job_id: str, oid: str):
        def _f():
            job = _job(job_id)
            animar_uma(job, oid, base, job_dir(job_id), request.get_json(silent=True) or {})
            salvar(job_id)
            return estado(job, base)
        return _resp(_f, job_id)

    @app.route("/job/<job_id>/personagens/<oid>/animacao.webm", methods=["GET"])
    def personagens_editor_animacao(job_id: str, oid: str):
        from flask import send_file, abort
        job = obter(job_id)
        ov = next((x for x in (job or {}).get("overlays") or [] if x.get("id") == oid), None)
        if not ov or not ov.get("anim_video") or not os.path.isfile(ov["anim_video"]):
            abort(404)
        return send_file(ov["anim_video"], mimetype="video/webm", conditional=True)

    @app.route("/job/<job_id>/personagens/aplicar", methods=["POST"])
    def personagens_editor_aplicar(job_id: str):
        def _f():
            job = _job(job_id)
            c = request.get_json(silent=True) or {}
            pc = job.setdefault("personagens_canal", {})
            if "texto" in c:
                pc["texto"] = str(c.get("texto") or "")[:200000]
            if isinstance(c.get("config"), dict):
                pc["config"] = {**(pc.get("config") or {}), **{k: v for k, v in c["config"].items() if k in PADRAO}}
            r = aplicar(job, job_dir(job_id), base, palavras_de(job), canal=str(c.get("canal") or ""), job_id=job_id,
                        enviar_flow=False)  # 🎞 o Flow só abre no botão 🎞 Animar
            salvar(job_id)
            return dict(r, estado=estado(job, base))
        return _resp(_f, job_id)

    @app.route("/job/<job_id>/personagens/canal", methods=["POST"])
    def personagens_editor_canal(job_id: str):
        def _f():
            job = _job(job_id)
            job.setdefault("personagens_canal", {})["canal"] = str((request.get_json(silent=True) or {}).get("canal") or "")[:60]
            salvar(job_id)
            return estado(job, base)
        return _resp(_f)

    @app.route("/job/<job_id>/personagens/remover", methods=["POST"])
    def personagens_editor_remover(job_id: str):
        def _f():
            job = _job(job_id)
            n = remover(job)
            salvar(job_id)
            return {"removidas": n, "estado": estado(job, base)}
        return _resp(_f, job_id)

    @app.route("/job/<job_id>/personagens/<oid>", methods=["POST"])
    def personagens_editor_mudar(job_id: str, oid: str):
        def _f():
            job = _job(job_id)
            c = request.get_json(silent=True) or {}
            if c.get("pose"):
                trocar_pose(job, oid, str(c["pose"]), base, job_dir(job_id))
            mudar(job, oid, c)
            if c.get("lado") in ("esquerda", "direita") and not c.get("pose"):
                try:
                    virar_pose(job, oid, base, job_dir(job_id))  # mudou de lado: a pose olhando pro centro
                except Exception:  # noqa: BLE001 — canal/projeto sumiu: fica a pose que estava
                    pass
            salvar(job_id)
            return estado(job, base)
        return _resp(_f, job_id)

    @app.route("/job/<job_id>/personagens/<oid>/remover", methods=["POST"])
    def personagens_editor_remover_uma(job_id: str, oid: str):
        def _f():
            job = _job(job_id)
            job["overlays"] = [ov for ov in job.get("overlays") or [] if ov.get("id") != oid]
            salvar(job_id)
            return estado(job, base)
        return _resp(_f, job_id)
