"""
Multi voice: vozes com SLUG que trocam no meio do texto.

Cada voz salva tem um nome ("Ricardo"), um slug ("ricardo"), o motor e a
configuração dele (mesmas chaves do Roteiro para Áudio). No modo multi voice,
escrever `[ricardo]` no texto NÃO é lido em voz alta: a narração troca pra voz
do Ricardo e fala tudo o que vem depois, até a próxima tag:

    [narrador] Era uma noite fria em Berlim.
    [ricardo] Você ouviu isso?
    [ana] Ouvi. Fica quieto.

O texto antes da primeira tag usa a voz padrão (a escolhida na tela). Tags
desconhecidas viram erro na conferência (pra nunca "ler o nome"), menos as
tags do Chatterbox Turbo ([laugh], [sigh]…), que continuam valendo.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_AQUI = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.path.join(_AQUI, "vozes_multi.json")
_TRAVA = threading.Lock()
MOTORES = ("piper", "xtts", "chatterbox", "chatterbox_turbo", "kokoro", "fish_s2")
CHAVES_CONFIG = ("voz", "idioma", "velocidade", "vozPerfil", "xttsCheckpoint", "chatterboxExaggeration",
                 "chatterboxCfgWeight", "kokoroVariante", "kokoroPrecisao", "usarGpu", "fishReferenceId", "fishTemperatura")
_RE_TAG = re.compile(r"\[\s*([^\[\]\n]{1,40}?)\s*\]\s*:?\s*")
GENEROS = {"masculino": "masculina", "feminino": "feminina", "neutro": "neutra/indefinida"}
GENERO_EN = {"masculino": "male", "feminino": "female", "neutro": "neutral"}
CORES = ["#3E8EFF", "#E0313B", "#5FBF6A", "#E8B04A", "#B061FF", "#2FD3E0", "#FF8A3D", "#FF4F9A", "#9AA0A6"]


class MultiVozError(Exception):
    pass


def slugify(nome: str) -> str:
    s = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:30]


# ------------------------------------------------------------------ cadastro
def _ler() -> List[Dict[str, Any]]:
    try:
        with open(ARQUIVO, encoding="utf-8") as f:
            d = json.load(f)
        return [v for v in (d.get("vozes") if isinstance(d, dict) else d) or [] if isinstance(v, dict) and v.get("slug")]
    except (OSError, ValueError):
        return []


def _gravar(vozes: List[Dict[str, Any]]) -> None:
    tmp = ARQUIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"vozes": vozes}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ARQUIVO)


def _com_perfil(v: Dict[str, Any]) -> Dict[str, Any]:
    """Voz que usa um PERFIL de voz herda gênero/idade/descrição dele quando não
    tem os próprios (perfis_info.py). Marca `herdado` com o que veio do perfil."""
    perfil = (v.get("config") or {}).get("vozPerfil")
    if not perfil:
        return v
    try:
        import perfis_info
        info = perfis_info.obter(perfil)
    except Exception:  # noqa: BLE001
        return v
    out, herdado = dict(v), []
    for k in ("genero", "idade", "descricao"):
        if not out.get(k) and info.get(k):
            out[k] = info[k]
            herdado.append(k)
    if herdado:
        out["herdado"] = herdado
    return out


def listar() -> List[Dict[str, Any]]:
    return [_com_perfil(v) for v in _ler()]


def por_slug() -> Dict[str, Dict[str, Any]]:
    return {v["slug"]: v for v in listar()}


def salvar(d: Dict[str, Any], slug_antigo: Optional[str] = None) -> Dict[str, Any]:
    nome = str(d.get("nome") or "").strip()[:40]
    if not nome:
        raise MultiVozError("Dê um nome pra voz (ex.: Ricardo).")
    slug = slugify(d.get("slug") or nome)
    if not slug:
        raise MultiVozError("Slug inválido — use letras e números (ex.: ricardo).")
    motor = d.get("motor")
    if motor not in MOTORES:
        raise MultiVozError(f"Motor {motor!r} inválido.")
    cfg_in = d.get("config") if isinstance(d.get("config"), dict) else {}
    config = {k: cfg_in[k] for k in CHAVES_CONFIG if k in cfg_in and cfg_in[k] not in (None, "")}
    with _TRAVA:
        vozes = _ler()
        if any(v["slug"] == slug and v["slug"] != slug_antigo for v in vozes):
            raise MultiVozError(f"Já existe uma voz com o slug [{slug}] — escolha outro.")
        antiga = next((v for v in vozes if v["slug"] == (slug_antigo or slug)), None)
        voz = {"slug": slug, "nome": nome, "motor": motor, "config": config,
               "cor": d.get("cor") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(d.get("cor") or "")) else (antiga or {}).get("cor") or CORES[len(vozes) % len(CORES)],
               "genero": normalizar_genero(d.get("genero")) or (antiga or {}).get("genero") or "",
               "idade": normalizar_idade(d.get("idade")) or (antiga or {}).get("idade") or "",
               "descricao": (str(d["descricao"]).strip()[:120] if d.get("descricao") is not None else (antiga or {}).get("descricao") or "")}
        vozes = [v for v in vozes if v["slug"] not in (slug, slug_antigo)] + [voz]
        _gravar(vozes)
    return voz


def voz_de_perfil(perfil: str, motor: str = "chatterbox", idioma: str = "") -> Dict[str, Any]:
    """🗣️ v84_176: a voz com slug de um PERFIL de voz (clonagem) — reaproveita a que já usa esse perfil nesse motor;
    senão cria uma (slug = nome do perfil). É o que o 🎭 Vozes dos personagens usa quando você escolhe um perfil."""
    perfil = str(perfil or "").strip()
    if not perfil:
        raise MultiVozError("Escolha um perfil de voz.")
    for v in _ler():
        if v.get("motor") == motor and (v.get("config") or {}).get("vozPerfil") == perfil:
            return v
    base = slugify(perfil) or "voz"
    ja = {v["slug"] for v in _ler()}
    slug, k = base, 2
    while slug in ja:
        slug = f"{base[:26]}_{k}"
        k += 1
    config = {"vozPerfil": perfil}  # sem idioma fixo: vale o idioma do projeto / da página (a mesma voz serve pra pt, de…)
    return salvar({"nome": perfil.replace("_", " ")[:40], "slug": slug, "motor": motor, "config": config})


def normalizar_genero(g: Any) -> str:
    """m/masc/male/homem -> masculino; f/female/mulher -> feminino; n -> neutro."""
    import perfis_info
    return perfis_info.normalizar_genero(g)


def normalizar_idade(i: Any) -> str:
    """criança / jovem / adulto / idoso (aceita child, teen, adult, old, velho...)."""
    import perfis_info
    return perfis_info.normalizar_idade(i)


def definir_genero(slug: str, genero: Any, descricao: Optional[str] = None, idade: Any = None) -> Dict[str, Any]:
    """Muda o gênero (e a idade/descrição, se vierem) de uma voz já salva.
    genero=None não mexe no gênero; "" limpa (volta a herdar do perfil)."""
    g = normalizar_genero(genero)
    if genero not in (None, "") and not g:
        raise MultiVozError("Gênero inválido — use masculino, feminino ou neutro.")
    a = normalizar_idade(idade)
    if idade not in (None, "") and not a:
        raise MultiVozError("Idade inválida — use criança, jovem, adulto ou idoso.")
    with _TRAVA:
        vozes = _ler()
        for v in vozes:
            if v["slug"] == slug:
                if genero is not None:
                    v["genero"] = g
                if idade is not None:
                    v["idade"] = a
                if descricao is not None:
                    v["descricao"] = str(descricao).strip()[:120]
                _gravar(vozes)
                return v
    raise MultiVozError(f"Voz [{slug}] não encontrada.")


def rotulo_genero(voz: Dict[str, Any]) -> str:
    """'voz feminina, idosa' / 'voz masculina' / 'gênero não definido'."""
    import perfis_info
    return perfis_info.rotulo(voz.get("genero") or "", voz.get("idade") or "")


def apagar(slug: str) -> bool:
    with _TRAVA:
        vozes = _ler()
        novas = [v for v in vozes if v["slug"] != slug]
        if len(novas) == len(vozes):
            return False
        _gravar(novas)
    return True


def kwargs_da_voz(voz: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """(motor, kwargs pro gerar_audio_isolado) — mesma regra do Roteiro para Áudio."""
    import narracoes
    proj = dict(narracoes.CONFIG_PADRAO)
    proj["voz"] = ""
    proj.update(voz.get("config") or {})
    proj["motor"] = voz["motor"]
    if not proj.get("voz"):
        proj["voz"] = {"piper": "pt_BR-faber-medium", "kokoro": "pf_dora"}.get(voz["motor"], "")
    return voz["motor"], narracoes._kwargs_motor(proj)


def resumo(voz: Dict[str, Any]) -> str:
    c = voz.get("config") or {}
    det = c.get("vozPerfil") or c.get("voz") or "padrão"
    vel = c.get("velocidade")
    return f"{voz['motor']} · {det}" + (f" · {float(vel):.2f}x" if vel not in (None, "", 1, 1.0) else "")


# ------------------------------------------------------------------ texto → falas
def _tags_extras() -> set:
    import sys
    pasta = os.path.join(_AQUI, "toolkit")
    if pasta not in sys.path:
        sys.path.insert(0, pasta)
    try:
        from tts.voice_generator import CHATTERBOX_TURBO_TAGS, FISH_TAGS_CONHECIDAS
        return set(CHATTERBOX_TURBO_TAGS) | set(FISH_TAGS_CONHECIDAS)
    except Exception:  # noqa: BLE001
        return set()


def _estilos() -> Dict[str, Dict[str, float]]:
    """🎭 v84_456: as tags de ESTILO do Expressivo ([dramatica], [ironica], [seria], [suspense], [agressiva], [camarada]…)
    valem no multi voice: viram a emoção/velocidade da fala (não são nome de voz)."""
    import sys
    pasta = os.path.join(_AQUI, "toolkit")
    if pasta not in sys.path:
        sys.path.insert(0, pasta)
    try:
        from tts.expressivo import ESTILOS, SINONIMOS_ESTILO
    except Exception:  # noqa: BLE001
        return {}
    out: Dict[str, Dict[str, float]] = {}
    for nome in list(ESTILOS) + list(SINONIMOS_ESTILO):
        e, c, v = ESTILOS[SINONIMOS_ESTILO.get(nome, nome)]
        out[slugify(nome)] = {k: x for k, x in (("exag", e), ("cfg", c), ("vel", v)) if x is not None}
    return out


def _perfis() -> List[str]:
    import sys
    pasta = os.path.join(_AQUI, "toolkit")
    if pasta not in sys.path:
        sys.path.insert(0, pasta)
    try:
        from tts.voice_generator import listar_perfis_de_voz
        return list(listar_perfis_de_voz())
    except Exception:  # noqa: BLE001
        return []


def perfis_das_tags(desconhecidas: List[str], perfis: Optional[List[str]] = None) -> Dict[str, str]:
    """🗣️ v84_456: [Marcio_Seixas] sem voz com slug, mas existe o PERFIL de voz "Marcio_Seixas" → dá pra criar a voz dele."""
    perfis = _perfis() if perfis is None else perfis
    por = {slugify(p): p for p in perfis}
    return {d: por[slugify(d)] for d in desconhecidas if slugify(d) in por}


def motor_dos_perfis(vozes: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    """O motor que as suas vozes de PERFIL já usam (a nova sai igual às outras); senão o Chatterbox."""
    vozes = por_slug() if vozes is None else vozes
    ms = [v.get("motor") for v in vozes.values() if (v.get("config") or {}).get("vozPerfil") and v.get("motor") in MOTORES]
    return max(set(ms), key=ms.count) if ms else "chatterbox"


def criar_vozes_dos_perfis(desconhecidas: List[str]) -> List[Dict[str, Any]]:
    """Cria (com o motor das outras vozes de perfil) as vozes das tags que têm perfil com o mesmo nome."""
    motor = motor_dos_perfis()
    feitas = []
    for _tag, perfil in perfis_das_tags(desconhecidas).items():
        feitas.append(voz_de_perfil(perfil, motor))
    return feitas


def _pausa_em_segundos(bruto: str) -> Optional[float]:
    """"pausa 3" → 3.0; "pausa 1,5s" → 1.5; "silêncio 2 segundos" → 2.0 (no máximo 10 s). None = não é pausa com número."""
    m = re.fullmatch(r"(?i)\s*(?:pausa|pause|sil[eê]ncio|silence)\s*(?:de\s*)?(\d+(?:[.,]\d+)?)\s*(?:s|seg|segundos?|seconds?)?\s*", bruto or "")
    if not m:
        return None
    return round(max(0.05, min(10.0, float(m.group(1).replace(",", ".")))), 2)


_PAUSAS_SLUG = {"pausa": 0.45, "pausa_curta": 0.25, "pausa_longa": 1.0, "pausa_media": 0.45, "silencio": 0.8,
                "pausa_dramatica": 1.4, "pausa_bem_longa": 1.6, "pause": 0.45, "short_pause": 0.25, "long_pause": 1.0}
_SONS_EXTRA = {"respira": "breath", "respirando": "breath", "respiracao": "breath", "respiro": "breath", "inspira": "breath",
               "respiração": "breath", "ofegante": "breath", "bocejo": "breath"}
_FISH_SOM = {"laugh": "laughing", "chuckle": "chuckle", "sigh": "sigh", "cough": "cough", "clear throat": "clearing throat",
             "gasp": "gasp", "groan": "sigh", "sniff": "breath", "shush": "whisper", "breath": "breath"}


def _sons() -> Tuple[Dict[str, str], Dict[str, str]]:
    """🔊 v84_457: tags de SOM em português ([tosse], [pigarro], [respira], [risada]…) → (som em pt → tag em inglês, falados)."""
    import sys
    pasta = os.path.join(_AQUI, "toolkit")
    if pasta not in sys.path:
        sys.path.insert(0, pasta)
    try:
        from tts.expressivo import SONS, SONS_FALADOS
    except Exception:  # noqa: BLE001
        SONS, SONS_FALADOS = {}, {}
    sons = {slugify(k): v for k, v in SONS.items()}
    sons.update({slugify(k): v for k, v in _SONS_EXTRA.items()})
    return sons, dict(SONS_FALADOS)


def som_para_motor(som: str, motor: str, falados: Dict[str, str]) -> str:
    """O som do jeito que cada motor entende: Fish S2 = [tag em inglês]; Chatterbox Turbo = [tag do Turbo];
    os outros não fazem som → vira a leitura do som ("Cof, cof.") ou some (respiração)."""
    if motor == "fish_s2":
        return f"[{_FISH_SOM.get(som, som)}] "
    if motor == "chatterbox_turbo" and som != "breath":
        return f"[{som}] "
    return (falados.get(som, "") + " ") if falados.get(som) else ""


def sugerir(desconhecidas: List[str], vozes: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, str]:
    """[Marcio_Seixas] sem voz → a voz cadastrada mais parecida (pelo slug ou pelo nome), se houver uma bem parecida."""
    import difflib
    vozes = por_slug() if vozes is None else vozes
    alvos = {slugify(v.get("nome") or s): s for s, v in vozes.items()} | {s: s for s in vozes}
    out = {}
    for d in desconhecidas:
        sd = slugify(d)
        m = difflib.get_close_matches(sd, list(alvos), n=1, cutoff=0.6)
        if not m:  # "marcio" ⊂ "marcio_seixas" e vice-versa
            m = [a for a in alvos if sd and (sd in a or a in sd) and min(len(a), len(sd)) >= 4][:1]
        if m:
            out[d] = alvos[m[0]]
    return out


def dividir(texto: str, vozes: Optional[Dict[str, Dict[str, Any]]] = None, padrao: Optional[str] = None,
            voz_inicial: Optional[str] = None) -> Dict[str, Any]:
    """Quebra o texto nas tags de voz. Devolve {"falas": [{"slug", "texto"}],
    "desconhecidas": [...], "usadas": [...], "ultima": slug} — `slug` None =
    voz padrão da tela. `voz_inicial` = quem estava falando antes (o Roteiro
    para Áudio continua a voz de uma fala pra próxima)."""
    vozes = por_slug() if vozes is None else vozes
    import chamadas as _ch
    texto = _ch.remover_marcadores(texto or "")  # [[INSCREVA: ...]] não é tag de voz (ver chamadas.py)
    extras = _tags_extras()
    estilos = _estilos()
    sons, falados = _sons()
    falas: List[Dict[str, Any]] = []
    desconhecidas: List[str] = []
    atual = voz_inicial
    pos = 0
    buf = ""

    ajustes: Dict[str, float] = {}
    pausa_pendente = 0.0  # ⏸ v84_459: [pausa] / [pausa curta] / [pausa longa] viram SILÊNCIO de verdade entre as falas

    def fecha():
        nonlocal buf, pausa_pendente
        t = re.sub(r"\s+", " ", buf).strip()
        if t and re.search(r"\w", t):
            if falas and falas[-1]["slug"] == atual and falas[-1].get("ajustes", {}) == ajustes and not pausa_pendente:
                falas[-1]["texto"] += " " + t
            else:
                falas.append({"slug": atual, "texto": t, **({"ajustes": dict(ajustes)} if ajustes else {}),
                              **({"pausa_antes": round(pausa_pendente, 2)} if pausa_pendente and falas else {})})
                pausa_pendente = 0.0
        buf = ""

    for m in _RE_TAG.finditer(texto or ""):
        bruto = m.group(1).strip()
        base, _, mods = bruto.partition("|")
        s = slugify(base)
        if s in vozes:
            buf += texto[pos:m.start()]
            fecha()
            atual = s
            ajustes = ler_ajustes(mods)  # 🎭 v84_173: emoção desta fala — [mira|exag=0.7|cfg=0.3|vel=1.05]
            pos = m.end()
        elif s in estilos and not mods:  # 🎭 v84_456: [dramatica] → a emoção desta fala (até a próxima tag)
            buf += texto[pos:m.start()]
            fecha()
            ajustes = dict(estilos[s])
            pos = m.end()
            if atual and (vozes.get(atual) or {}).get("motor") == "fish_s2":
                buf += m.group(0)  # o Fish S2 entende instrução entre colchetes: a tag fica no texto dele
        elif _pausa_em_segundos(bruto) is not None and not mods:  # ⏸ [pausa 3] / [pausa 1.5s] / [silêncio 2]
            buf += texto[pos:m.start()]
            fecha()
            pausa_pendente += _pausa_em_segundos(bruto)
            pos = m.end()
        elif slugify(bruto) in _PAUSAS_SLUG and not mods:  # ⏸ v84_459: silêncio de verdade (antes o colchete sumia e a pausa junto)
            buf += texto[pos:m.start()]
            fecha()
            pausa_pendente += _PAUSAS_SLUG[slugify(bruto)]
            pos = m.end()
        elif s in sons and not mods:  # 🔊 v84_457: [tosse] [pigarro] [respira] — som, não voz
            buf += texto[pos:m.start()]
            motor = (vozes.get(atual) or {}).get("motor") if atual else (padrao or "")
            buf += som_para_motor(sons[s], str(motor or ""), falados)
            pos = m.end()
        elif re.fullmatch(r"(?i)(velocidade|vel|speed)\s*[=:]?\s*\d+(?:[.,]\d+)?x?", bruto):  # [velocidade 0.9]
            buf += texto[pos:m.start()]
            fecha()
            ajustes = dict(ajustes, **ler_ajustes("vel=" + re.search(r"\d+(?:[.,]\d+)?", bruto).group(0)))
            pos = m.end()
        elif (bruto.lower() in extras or " " in bruto.strip()) and \
                ((vozes.get(atual) or {}).get("motor") if atual else (padrao or "")) not in ("", None, "fish_s2", "chatterbox_turbo"):
            # 🧹 v84_460: tag de emoção/efeito que ESTE motor não entende — sai do texto (senão ele lê "pausa 3" em voz alta)
            buf += texto[pos:m.start()]
            pos = m.end()
        elif bruto.lower() in extras or " " in bruto.strip():
            continue  # tag de emoção (Chatterbox Turbo / Fish S2, ex.: [excited], [whisper in small voice]): fica no texto
        else:
            desconhecidas.append(bruto)
    buf += (texto or "")[pos:]
    fecha()
    usadas = []
    for f in falas:
        if f["slug"] and f["slug"] not in usadas:
            usadas.append(f["slug"])
    return {"falas": falas, "desconhecidas": sorted(set(desconhecidas)), "usadas": usadas, "ultima": atual}


AJUSTES = {"exag": ("exaggeration", 0.0, 1.5), "emo": ("exaggeration", 0.0, 1.5), "cfg": ("cfg_weight", 0.0, 1.0),
           "vel": ("velocidade", 0.5, 2.0)}


def ler_ajustes(mods: str) -> Dict[str, float]:
    """"exag=0.7|cfg=0.3|vel=1.1" → {"exag": 0.7, "cfg": 0.3, "vel": 1.1} (o que não for número/conhecido é ignorado)."""
    out: Dict[str, float] = {}
    for parte in re.split(r"[|,;]", str(mods or "")):
        k, _, v = parte.partition("=")
        k = k.strip().lower()
        if k not in AJUSTES:
            continue
        try:
            _n, lo, hi = AJUSTES[k]
            out["exag" if k == "emo" else k] = round(max(lo, min(hi, float(v.strip().replace(",", ".")))), 2)
        except ValueError:
            continue
    return out


def aplicar_ajustes(motor: str, kw: Dict[str, Any], ajustes: Optional[Dict[str, float]]) -> Dict[str, Any]:
    """Os ajustes da fala nos kwargs do motor: emoção (exaggeration) e cfg só no Chatterbox; velocidade nos que têm."""
    if not ajustes:
        return kw
    kw = dict(kw)
    if motor == "chatterbox":
        if "exag" in ajustes:
            kw["exaggeration"] = ajustes["exag"]
        if "cfg" in ajustes:
            kw["cfg_weight"] = ajustes["cfg"]
    if "vel" in ajustes and "velocidade" in kw:
        kw["velocidade"] = ajustes["vel"]
    return kw


def tem_tags(texto: str, vozes: Optional[Dict[str, Dict[str, Any]]] = None) -> bool:
    vozes = por_slug() if vozes is None else vozes
    return any(slugify(m.group(1)) in vozes for m in _RE_TAG.finditer(texto or ""))


# ------------------------------------------------------------------ geração
def _wav_padrao(origem: str, destino: str) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", origem, "-ar", "24000", "-ac", "1", destino], capture_output=True, timeout=300)
    if r.returncode != 0 or not os.path.exists(destino):
        raise MultiVozError("ffmpeg não conseguiu preparar o áudio de uma fala.")


def concatenar(arquivos: List[str], saida: str, pausas: List[float], pasta: str) -> None:
    """Junta os wavs com a pausa ANTES de cada um (pausas[0] é ignorada)."""
    lista = os.path.join(pasta, "lista.txt")
    silencios: Dict[float, str] = {}
    linhas = []
    for k, a in enumerate(arquivos):
        p = round(pausas[k], 2) if k else 0
        if p > 0:
            if p not in silencios:
                sp = os.path.join(pasta, f"silencio_{int(p * 100)}.wav")
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(p), sp], capture_output=True)
                silencios[p] = sp
            linhas.append(silencios[p])
        linhas.append(a)
    with open(lista, "w", encoding="utf-8") as f:
        for c in linhas:
            f.write("file '" + str(Path(c).resolve()).replace("'", "'\\''") + "'\n")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lista, "-ar", "24000", "-ac", "1", saida],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise MultiVozError(f"Falha ao juntar as falas: {r.stderr[-300:]}")


def gerar(texto: str, saida: str, motor_padrao: str, kwargs_padrao: Dict[str, Any],
          gerar_fn: Callable[..., Any], limpar_fn: Callable[[str, bool], str],
          pausa_troca: float = 0.35, pausa_mesma: float = 0.12, on_log: Optional[Callable[[str], None]] = None,
          normalizar_fn: Optional[Callable[[str, str], None]] = None, lote_fn: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """Gera o texto inteiro trocando de voz nas tags. `gerar_fn(motor, texto, saida, **kwargs)`.
    ⚡ v84_458 `lote_fn` (gerar_audio_isolado_lote): todas as falas num processo só, com o modelo carregado UMA vez
    (antes: um processo novo e o modelo carregado de novo em CADA fala — era o que deixava o multi voice lento)."""
    log = on_log or (lambda _m: None)
    vozes = por_slug()
    d = dividir(texto, vozes, padrao=motor_padrao)  # padrao = o motor da voz padrão (pros sons [tosse]…)
    if d["desconhecidas"] and perfis_das_tags(d["desconhecidas"]):  # 🗣️ v84_456: tem perfil com esse nome → cria a voz
        for v in criar_vozes_dos_perfis(d["desconhecidas"]):
            log(f"🗣️ criei a voz [{v['slug']}] a partir do perfil {v['config'].get('vozPerfil')} ({v['motor']})")
        vozes = por_slug()
        d = dividir(texto, vozes, padrao=motor_padrao)
    if d["desconhecidas"]:
        raise MultiVozError("Tag(s) sem voz cadastrada: " + ", ".join(f"[{x}]" for x in d["desconhecidas"])
                            + ". Cadastre a voz com esse slug (🎭 Vozes) ou corrija o texto — senão o nome seria lido em voz alta.")
    if not d["falas"]:
        raise MultiVozError("Não sobrou texto pra narrar depois das tags.")
    pasta = os.path.splitext(saida)[0] + "_multi"
    shutil.rmtree(pasta, ignore_errors=True)
    os.makedirs(pasta, exist_ok=True)
    cache = pasta_cache(saida)
    reaproveitadas = 0
    try:
        arquivos, pausas, anterior = [], [], "__inicio__"
        pend: List[Dict[str, Any]] = []
        for k, f in enumerate(d["falas"], start=1):
            if f["slug"]:
                motor, kw = kwargs_da_voz(vozes[f["slug"]])
                quem = vozes[f["slug"]]["nome"]
            else:
                motor, kw, quem = motor_padrao, kwargs_padrao, "voz padrão"
            kw = aplicar_ajustes(motor, kw, f.get("ajustes"))
            texto_limpo = limpar_fn(f["texto"], motor)
            # 💾 v84_458: cada fala pronta fica guardada (voz + configuração + texto): se o motor travar no meio, a nova
            # tentativa — ou você clicando em gerar de novo — continua de onde parou
            guardada = os.path.join(cache, chave_fala(motor, kw, texto_limpo) + ".wav")
            wav = os.path.join(pasta, f"f{k:04d}.wav")
            if os.path.isfile(guardada) and os.path.getsize(guardada) > 1000:
                shutil.copy(guardada, wav)
                reaproveitadas += 1
            else:
                pend.append({"k": k, "motor": motor, "kw": kw, "texto": texto_limpo, "quem": quem, "wav": wav,
                             "guardada": guardada, "bruto": os.path.join(pasta, f"f{k:04d}_bruto.wav"),
                             "aj": " ".join(f"{a}={v}" for a, v in (f.get("ajustes") or {}).items())})
            arquivos.append(wav)
            pausas.append((pausa_troca if f["slug"] != anterior else pausa_mesma) + float(f.get("pausa_antes") or 0))
            anterior = f["slug"]
        total = len(d["falas"])
        if reaproveitadas:
            log(f"♻ {reaproveitadas} de {total} fala(s) já estavam prontas (de uma tentativa anterior) — gerando só as {len(pend)} que faltam.")
        if pend and lote_fn is not None:
            _gerar_em_lote(pend, lote_fn, total, log)
        else:
            for p in pend:
                log(f"[{p['k']}/{total}] {p['quem']} ({p['motor']}{' · ' + p['aj'] if p['aj'] else ''}): \"{p['texto'][:60]}\"")
                _gerar_fala_com_retentativa(gerar_fn, p["motor"], p["texto"], p["bruto"], p["kw"], log)
                _guardar_fala(p)
        log(f"Juntando {len(arquivos)} fala(s) de {len(set(f['slug'] for f in d['falas']))} voz(es)...")
        juntado = os.path.join(pasta, "juntado.wav")
        concatenar(arquivos, juntado, pausas, pasta)
        if normalizar_fn:
            normalizar_fn(juntado, saida)
        else:
            shutil.copy(juntado, saida)
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    return {"falas": len(d["falas"]), "vozes": d["usadas"], "reaproveitadas": reaproveitadas}


CACHE_DIAS = 5


def pasta_cache(saida: str) -> str:
    """As falas prontas do multi voice (ao lado dos áudios). As de mais de CACHE_DIAS dias são apagadas."""
    import time as _t
    c = os.environ.get("MULTIVOZ_CACHE_DIR") or os.path.join(os.path.dirname(os.path.abspath(saida)), "_falas_prontas")
    os.makedirs(c, exist_ok=True)
    limite = _t.time() - CACHE_DIAS * 86400
    try:
        for n in os.listdir(c):
            a = os.path.join(c, n)
            if os.path.getmtime(a) < limite:
                os.remove(a)
    except OSError:
        pass
    return c


def info_cache(pasta_audios: str) -> Dict[str, Any]:
    c = os.environ.get("MULTIVOZ_CACHE_DIR") or os.path.join(pasta_audios, "_falas_prontas")
    n, tam = 0, 0
    try:
        for x in os.listdir(c):
            if x.endswith(".wav"):
                n += 1
                tam += os.path.getsize(os.path.join(c, x))
    except OSError:
        pass
    return {"falas": n, "mb": round(tam / 1e6, 1), "pasta": c}


def limpar_cache(pasta_audios: str) -> int:
    """🗑 v84_460: apaga as falas guardadas (pra gerar tudo do zero)."""
    c = info_cache(pasta_audios)["pasta"]
    n = 0
    try:
        for x in os.listdir(c):
            try:
                os.remove(os.path.join(c, x))
                n += 1
            except OSError:
                pass
    except OSError:
        pass
    return n


def chave_fala(motor: str, kw: Dict[str, Any], texto: str) -> str:
    import hashlib
    cfg = json.dumps({k: kw[k] for k in sorted(kw) if k not in ("on_progresso", "on_log", "progresso_arquivo")},
                     sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(f"{motor}\n{cfg}\n{texto}".encode("utf-8")).hexdigest()[:24]


def _guardar_fala(p: Dict[str, Any]) -> None:
    _wav_padrao(p["bruto"], p["wav"])
    try:
        shutil.copy(p["wav"], p["guardada"] + ".tmp")
        os.replace(p["guardada"] + ".tmp", p["guardada"])
    except OSError:
        pass


def _eh_crash(txt: str) -> bool:
    t = str(txt or "").lower()
    return any(x in t for x in ("travou", "3221225477", "fechou sozinho", "crash", "memória", "memory", "terminou sem gerar"))


def _gerar_em_lote(pend: List[Dict[str, Any]], lote_fn, total: int, log, rodadas: int = 4) -> None:
    """As falas que faltam num processo só, AGRUPADAS POR VOZ (troca de perfil o mínimo). Se o motor travar, as que já
    saíram ficam guardadas e uma rodada nova (processo novo) faz só as que faltaram."""
    import gc
    import time as _t
    faltam = sorted(pend, key=lambda p: (p["motor"], json.dumps(p["kw"], sort_keys=True, default=str), p["k"]))
    for rodada in range(1, rodadas + 1):
        feitas = {"n": 0}
        log(f"⚡ gerando {len(faltam)} fala(s) num processo só (o modelo carrega uma vez)"
            + (f" — rodada {rodada}/{rodadas}" if rodada > 1 else "") + "…")

        def prog(i, erro, lista=faltam):
            p = lista[i]
            if erro:
                log(f"   ⚠ [{p['k']}/{total}] {p['quem']}: {str(erro)[:160]}")
                return
            try:
                _guardar_fala(p)
            except Exception as exc:  # noqa: BLE001
                log(f"   ⚠ [{p['k']}/{total}] não consegui preparar o áudio: {exc}")
                return
            feitas["n"] += 1
            log(f"[{p['k']}/{total}] ✔ {p['quem']} ({p['motor']}{' · ' + p['aj'] if p['aj'] else ''}): \"{p['texto'][:50]}\"")
        erros = lote_fn([(p["motor"], p["texto"], p["bruto"], p["kw"]) for p in faltam], on_progresso=prog) or {}
        ruins = [faltam[i] for i in sorted(erros) if 0 <= i < len(faltam)]
        ruins += [p for p in faltam if p not in ruins and not os.path.isfile(p["wav"])]
        if not ruins:
            return
        if not all(_eh_crash(erros.get(faltam.index(p), "terminou sem gerar")) for p in ruins) or rodada == rodadas:
            raise MultiVozError(f"{len(ruins)} fala(s) não saíram: " + str(next(iter(erros.values()), "o motor parou"))[:300]
                                + " — as que já saíram ficaram guardadas: clique em gerar de novo que ele continua de onde parou.")
        espera = 10 * rodada
        log(f"🔁 o motor travou ({len(ruins)} fala(s) faltando). {sum(1 for p in pend if os.path.isfile(p['wav']))} já estão "
            f"guardadas. Esperando {espera} s a placa liberar e continuando só com as que faltam…")
        gc.collect()
        _t.sleep(espera)
        faltam = ruins


def _gerar_fala_com_retentativa(gerar_fn, motor: str, texto: str, saida: str, kw: Dict[str, Any], log, tentativas: int = 4) -> None:
    """🔁 v84_458: o motor travou (crash nativo da placa/memória) NUMA fala → tenta de novo SÓ essa fala (processo novo),
    esperando a placa esvaziar. Antes, o crash de uma fala jogava fora as horas de falas já prontas."""
    import gc
    import time as _t
    for n in range(1, tentativas + 1):
        try:
            gerar_fn(motor, texto, saida, **kw)
            return
        except Exception as exc:  # noqa: BLE001
            txt = str(exc)
            crash = "travou o processo" in txt or "3221225477" in txt or "memória" in txt.lower() or "out of memory" in txt.lower()
            if not crash or n == tentativas:
                raise
            espera = 10 * n
            log(f"   🔁 o motor travou nesta fala (tentativa {n}/{tentativas}) — esperando {espera} s a placa liberar e "
                "tentando de novo SÓ esta fala (as anteriores estão guardadas)")
            gc.collect()
            _t.sleep(espera)


def instrucao_para_ia(vozes: Optional[List[Dict[str, Any]]] = None) -> str:
    """Trecho pra colar no pedido de roteiro: a IA escreve já com as tags."""
    vozes = listar() if vozes is None else vozes
    if not vozes:
        return ""
    linhas = "\n".join(f"- [{v['slug']}] = {v['nome']}" + (f" ({rotulo_genero(v)})" if v.get("genero") or v.get("idade") else "")
                        + (f" — {v['descricao']}" if v.get("descricao") else "") for v in vozes)
    return ("Escreva o roteiro no formato MULTI VOZ: antes de cada fala, coloque a tag da voz entre colchetes — a tag não é lida, "
            "ela só troca a voz, e a voz continua até a próxima tag. Use SÓ estas vozes:\n" + linhas +
            "\nExemplo:\n[" + vozes[0]["slug"] + "] Primeira fala.\n" + (f"[{vozes[1]['slug']}] Resposta.\n" if len(vozes) > 1 else "")
            + "Não use colchetes pra mais nada, nem escreva o nome da voz fora da tag.")
