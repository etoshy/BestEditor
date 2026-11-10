"""
🎭 Chatterbox pt-BR expressivo (v84_372) — tags no texto, em português.

O Chatterbox multilíngue NÃO entende tags (só o Turbo, e só em inglês). Aqui
o texto é lido como um roteiro de locução e montado em pedaços:

  [soprosa] [dramatica] [plena] [sorridente] [projetada] ...  estilo da voz
      (vale até a próxima tag de estilo ou [normal]). Cada estilo = emoção +
      aderência + velocidade. Se existir um perfil de voz "<perfil>_<estilo>"
      (ex: minhavoz_soprosa), a referência dele é usada nesse trecho — é o que
      mais muda o jeito da voz.
  [risada] [risadinha] [suspiro] [tosse] [pigarro] [susto] [gemido] [fungada] [shh]
      sons: gerados pelo Chatterbox Turbo (inglês, mas som não tem idioma)
      com a MESMA voz de referência e colados no lugar.
  [respira]       respiração curta antes da frase (o "INSPIRE" da locução).
  [pausa] [pausa curta] [pausa longa] [pausa 1.5]   silêncio.
  *palavra*       palavra de valor: micro-pausa antes e mais energia nela.
  [emocao 0.7] [cfg 0.3] [velocidade 1.1]   ajuste fino manual (até o próximo estilo).
  linha em branco = pausa de parágrafo.

Tudo que não é tag é narrado pelo Chatterbox multilíngue normal (pt-BR).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
import wave
from typing import Any, Callable, Dict, List, Optional

TAXA = 24000  # Chatterbox (multilíngue e Turbo) gera em 24 kHz

# estilo -> (emoção/exaggeration, aderência/cfg_weight, velocidade)
ESTILOS: Dict[str, tuple] = {  # v84_372c: um pouco mais de emoção (o teste saiu "sem emoção" na voz plena)
    "normal": (None, None, 1.0),
    "linear": (0.35, 0.55, 1.0),
    "calma": (0.40, 0.50, 0.95),
    "soprosa": (0.45, 0.45, 0.95),
    "carinhosa": (0.55, 0.45, 0.97),
    "dramatica": (0.65, 0.35, 0.92),
    "suspense": (0.55, 0.35, 0.90),
    "plena": (0.55, 0.45, 1.0),
    "seria": (0.50, 0.50, 1.0),
    "sorridente": (0.70, 0.40, 1.03),
    "alegre": (0.75, 0.40, 1.05),
    "camarada": (0.62, 0.42, 1.0),
    "ironica": (0.65, 0.42, 1.0),
    "reportagem": (0.55, 0.45, 1.05),
    "projetada": (0.85, 0.35, 1.06),
    "agressiva": (0.90, 0.32, 1.08),
}
SINONIMOS_ESTILO = {
    "soproso": "soprosa", "sussurro": "soprosa", "sussurrada": "soprosa",
    "dramatico": "dramatica", "soprosa dramatica": "dramatica", "soprosa-dramatica": "dramatica",
    "plena seria": "seria", "plena-seria": "seria", "serio": "seria",
    "sorrindo": "sorridente", "sorriso": "sorridente", "feliz": "alegre",
    "ironico": "ironica", "intimo": "camarada", "intima": "camarada",
    "rua": "reportagem", "reporter": "reportagem", "noticia": "reportagem", "jornal": "reportagem",
    "varejo": "projetada", "vendedor": "projetada", "agressivo": "agressiva",
    "calmo": "calma", "neutra": "linear", "neutro": "linear", "padrao": "normal",
    # 🇵🇹 pt-PT
    "cumplice": "camarada", "projectada": "projetada", "projectado": "projetada", "ternurenta": "carinhosa",
    "ternura": "carinhosa", "sussurrado": "soprosa", "pivot": "reportagem", "telejornal": "reportagem",
}

# som em pt -> tag do Turbo
SONS: Dict[str, str] = {
    "risada": "laugh", "rindo": "laugh", "gargalhada": "laugh",
    "risadinha": "chuckle", "riso": "chuckle",
    "suspiro": "sigh", "suspira": "sigh",
    "tosse": "cough", "tossindo": "cough",
    "pigarro": "clear throat", "pigarreia": "clear throat",
    "susto": "gasp", "espanto": "gasp",
    "gemido": "groan", "resmungo": "groan",
    "fungada": "sniff", "fungando": "sniff",
    "shh": "shush", "psiu": "shush",
    # 🇵🇹 pt-PT
    "risota": "chuckle", "risinho": "chuckle", "tossidela": "cough", "pigarrear": "clear throat",
    "pigarreio": "clear throat", "fungadela": "sniff", "chiu": "shush", "gemer": "groan", "suspirar": "sigh",
}
# 🗣 modo "falado": o som vira texto na MESMA frase, narrado pelo próprio Chatterbox pt (mesma voz e clima;
# soa menos "colado" que o som do Turbo, mas é uma leitura do som, não o som de verdade)
SONS_FALADOS = {"laugh": "Ha ha ha!", "chuckle": "He he.", "sigh": "Ahh...", "cough": "Cof, cof.",
                "clear throat": "Hum, hum.", "gasp": "Ah!", "groan": "Hmm...", "shush": "Shhh!"}
MODOS_SONS = ("falado", "turbo")  # v84_372c: falado é o padrão (o Turbo solto saiu chiado/baixo no teste)
TURBO_SONS = {"laugh", "chuckle", "gasp", "cough", "sigh", "groan", "sniff", "shush", "clear throat"}

PAUSAS = {"pausa": 0.45, "pausa curta": 0.25, "pausa longa": 1.0, "silencio": 0.8}
PAUSA_PARAGRAFO = 0.6
PAUSA_ENFASE = 0.14
EXTRA_EMOCAO_ENFASE = 0.12

TAG = re.compile(r"\[([^\[\]\n]{1,40})\]")
ENFASE = re.compile(r"\*([^*\n]{1,60})\*")


class ExpressivoErro(Exception):
    pass


def _sem_acento(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _chave(s: str) -> str:
    return " ".join(_sem_acento(s).lower().replace("_", " ").split())


def classificar_tag(conteudo: str) -> Optional[Dict[str, Any]]:
    """'[soprosa]' -> {'tipo': 'estilo', ...}; None = não é tag nossa (fica no texto como colchete comum)."""
    k = _chave(conteudo)
    k_hifen = k.replace("-", " ")
    if k in ESTILOS or k in SINONIMOS_ESTILO or k_hifen in SINONIMOS_ESTILO:
        return {"tipo": "estilo", "estilo": SINONIMOS_ESTILO.get(k, SINONIMOS_ESTILO.get(k_hifen, k))}
    if k in SONS:
        return {"tipo": "som", "som": SONS[k]}
    if k in TURBO_SONS:
        return {"tipo": "som", "som": k}
    if k in ("respira", "respiracao", "inspira", "inspire", "breath", "respirar", "inspirar", "inspiracao"):
        return {"tipo": "respira"}
    if k in PAUSAS:
        return {"tipo": "pausa", "s": PAUSAS[k]}
    m = re.fullmatch(r"(?:pausa|silencio)\s+(\d+(?:[.,]\d+)?)\s*s?", k)
    if m:
        return {"tipo": "pausa", "s": max(0.05, min(float(m.group(1).replace(",", ".")), 10.0))}
    m = re.fullmatch(r"(emocao|exagero|cfg|aderencia|velocidade|ritmo)\s*[=:]?\s*(\d+(?:[.,]\d+)?)", k)
    if m:
        nome = {"exagero": "emocao", "aderencia": "cfg", "ritmo": "velocidade"}.get(m.group(1), m.group(1))
        v = float(m.group(2).replace(",", "."))
        v = max(0.6, min(v, 1.6)) if nome == "velocidade" else max(0.0, min(v, 1.2 if nome == "emocao" else 1.0))
        return {"tipo": "ajuste", "nome": nome, "valor": v}
    return None


def tem_tags(texto: str) -> bool:
    return bool(ENFASE.search(texto or "")) or any(classificar_tag(m.group(1)) for m in TAG.finditer(texto or ""))


def texto_sem_tags(texto: str) -> str:
    """O que é FALADO (pra legenda): sem as tags e sem os asteriscos da ênfase."""
    t = TAG.sub(lambda m: "" if classificar_tag(m.group(1)) else m.group(0), texto or "")
    t = ENFASE.sub(r"\1", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n[ \t]+", "\n", t)
    return t.strip()


def limpar_fala(t: str) -> str:
    """Limpeza leve do trecho falado (aspas, colchetes que sobraram, marcas de markdown)."""
    t = re.sub(r"[\"“”‘’„«»`´]", "", t)
    t = re.sub(r"[\[\]{}()*_~#]", "", t)
    t = t.replace("…", "...")
    t = re.sub(r"\s+([.,;:!?])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip(" \t\n,;")


def montar_eventos(texto: str, emocao_base: float = 0.5, cfg_base: float = 0.5, sons: str = "falado") -> List[Dict[str, Any]]:
    """Roteiro com tags -> lista de eventos: fala / som / respira / pausa."""
    eventos: List[Dict[str, Any]] = []
    estado = {"estilo": "normal", "emocao": emocao_base, "cfg": cfg_base, "velocidade": 1.0}

    def aplicar_estilo(nome: str) -> None:
        e, c, v = ESTILOS[nome]
        estado.update(estilo=nome, emocao=emocao_base if e is None else e, cfg=cfg_base if c is None else c, velocidade=v)

    def fala(trecho: str) -> None:
        # ênfase: *palavra* -> vírgula antes (pausinha) + mais emoção só na frase dela
        partes = ENFASE.split(trecho)  # [texto, enfase, texto, enfase, texto...]
        buffer = ""
        for i, p in enumerate(partes):
            if i % 2 == 0:
                buffer += p
                continue
            antes, resto = buffer, p + (partes[i + 1] if i + 1 < len(partes) else "")
            # o resto só até o fim da frase -- o que vem depois volta pro normal
            m_fim = re.search(r"[.!?…](\s|$)", resto)
            dentro, depois = (resto[:m_fim.end()], resto[m_fim.end():]) if m_fim else (resto, "")
            if i + 1 < len(partes):
                partes[i + 1] = ""
            # v84_372b: NÃO divide mais em duas gerações (a 2ª parte, gerada sozinha, saía com entonação de frase
            # solta — "produtos orgânicos." estranho). A frase fica inteira: vírgula antes da palavra = pausinha
            # natural do próprio modelo, e só ESSA frase ganha um pouco mais de emoção.
            corte = max((m.end() for m in re.finditer(r"(?<![.…])[.!?](\s|$)", antes)), default=0)
            _push_fala(antes[:corte])
            atual = antes[corte:].rstrip()
            sep = "" if not atual or atual[-1] in ",;:—-" else ","
            _push_fala(atual + sep + " " + dentro.lstrip(), extra=EXTRA_EMOCAO_ENFASE, enfase=p)
            buffer = depois
        _push_fala(buffer)

    def _push_fala(t: str, extra: float = 0.0, enfase: Optional[str] = None) -> None:
        t = limpar_fala(t)
        if not re.search(r"\w", t):
            return
        ev = {"tipo": "fala", "texto": t, "estilo": estado["estilo"], "velocidade": estado["velocidade"],
              "emocao": round(min(1.2, estado["emocao"] + extra), 3), "cfg": estado["cfg"]}
        if enfase:
            ev["enfase"] = enfase
        # junta com a fala anterior se for a mesma configuração (menos cortes = prosódia mais natural)
        if eventos and eventos[-1]["tipo"] == "fala" and not enfase and not eventos[-1].get("enfase") and all(
                eventos[-1][k] == ev[k] for k in ("estilo", "velocidade", "emocao", "cfg")):
            eventos[-1]["texto"] += " " + t
        else:
            eventos.append(ev)

    paragrafos = re.split(r"\n\s*\n", (texto or "").replace("\r\n", "\n"))
    for n, par in enumerate(paragrafos):
        if n and eventos and eventos[-1]["tipo"] != "pausa":
            eventos.append({"tipo": "pausa", "s": PAUSA_PARAGRAFO})
        pos = 0
        pendente = ""
        for m in TAG.finditer(par):
            info = classificar_tag(m.group(1))
            if not info:
                continue
            pendente += par[pos:m.start()]
            pos = m.end()
            if info["tipo"] in ("estilo", "ajuste"):
                fala(pendente)
                pendente = ""
                if info["tipo"] == "estilo":
                    aplicar_estilo(info["estilo"])
                else:
                    estado[info["nome"]] = info["valor"]
            elif info["tipo"] == "som" and sons == "falado" and info["som"] in SONS_FALADOS:
                pendente = pendente.rstrip() + " " + SONS_FALADOS[info["som"]] + " "
            else:
                fala(pendente)
                pendente = ""
                eventos.append(dict(info))
        fala(pendente + par[pos:])
    while eventos and eventos[-1]["tipo"] == "pausa":
        eventos.pop()
    return eventos


# ------------------------------------------------------------------ áudio (v84_372b: aparar, nivelar, sem clip)
# O que a 1ª versão errava (medido num áudio de teste): cada fala do Chatterbox vem com ~0,3-1 s de silêncio/ruído
# nas pontas, que somava com as nossas pausas (a pausinha da ênfase virava 0,8 s); os sons eram aparados com um
# limiar fixo (-42 dB) que comia suspiro e risada inteiros; as pausas eram zero digital (o ruído de fundo da fala
# "desligava" de repente); e picos em 0 dBFS (clip).
QUADRO = 0.01            # análise em quadros de 10 ms
MARGEM_INICIO = 0.04     # o que fica antes da 1ª sílaba
MARGEM_FIM = 0.12        # o fim da palavra decai devagar
FADE_IN, FADE_OUT = 0.008, 0.03
RUIDO_SALA_DB = -68.0    # "ar" nas pausas em vez de zero digital
PICO_MAX_DB = -1.5
SOM_DB_ABAIXO_DA_FALA = 6.0
RESPIRA_DB_ABAIXO_DA_FALA = 13.0


def _carregar(entrada: str, filtros: Optional[List[str]] = None):
    """Qualquer áudio -> numpy float32 mono 24 kHz (ffmpeg converte taxa, canais e velocidade)."""
    import numpy as np
    cmd = ["ffmpeg", "-v", "error", "-i", entrada]
    if filtros:
        cmd += ["-af", ",".join(filtros)]
    cmd += ["-ar", str(TAXA), "-ac", "1", "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        raise ExpressivoErro(f"ffmpeg falhou ao ler um pedaço: {r.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def _filtro_tempo(v: float) -> List[str]:
    if abs(v - 1.0) < 0.01:
        return []
    return [f"atempo={max(0.5, min(v, 2.0)):.3f}"]


def _db(v: float) -> float:
    import math
    return 20 * math.log10(max(v, 1e-9))


def _energia(x):
    import numpy as np
    h = int(TAXA * QUADRO)
    n = len(x) // h
    if n == 0:
        return np.zeros(0)
    q = x[:n * h].reshape(n, h)
    return np.sqrt(np.mean(q ** 2, axis=1))


def aparar(x, abaixo_do_pico_db: float = 38.0, piso_db: float = -55.0, margem_fim: float = MARGEM_FIM,
           nucleo_db: float = 20.0, max_antes: float = 0.12, max_depois: float = 0.25):
    """Corta silêncio/ruído das pontas com limiar RELATIVO ao pico do próprio pedaço (som baixo não some).
    Acha o "núcleo" (quadros a até `nucleo_db` do pico) e só estende pra fora enquanto ainda há som acima de
    `abaixo_do_pico_db` — no máximo `max_antes`/`max_depois` s (ruído/respiração longa do modelo fica de fora)."""
    import numpy as np
    e = _energia(x)
    if not len(e) or e.max() <= 0:
        return x[:0]
    limiar = max(e.max() * 10 ** (-abaixo_do_pico_db / 20), 10 ** (piso_db / 20))
    nucleo = np.where(e >= max(e.max() * 10 ** (-nucleo_db / 20), limiar))[0]
    if not len(nucleo):
        return x[:0]
    i0, i1 = int(nucleo[0]), int(nucleo[-1])
    lim_i0 = max(0, i0 - int(max_antes / QUADRO))
    while i0 > lim_i0 and e[i0 - 1] >= limiar:
        i0 -= 1
    lim_i1 = min(len(e) - 1, i1 + int(max_depois / QUADRO))
    while i1 < lim_i1 and e[i1 + 1] >= limiar:
        i1 += 1
    ini = max(0, int((i0 * QUADRO - MARGEM_INICIO) * TAXA))
    fim = min(len(x), int(((i1 + 1) * QUADRO + margem_fim) * TAXA))
    y = x[ini:fim].copy()
    fi, fo = min(len(y), int(FADE_IN * TAXA)), min(len(y), int(FADE_OUT * TAXA))
    if fi:
        y[:fi] *= np.linspace(0, 1, fi, dtype=np.float32)
    if fo:
        y[-fo:] *= np.linspace(1, 0, fo, dtype=np.float32)
    return y


def limites_falados(caminho: str, idioma: str = "pt"):
    """(início da 1ª palavra, fim da última) pelo Whisper — o Chatterbox às vezes solta ~1 s de ruído/"resmungo"
    antes ou depois da frase (medido: antes de "produtos orgânicos", depois de "Voltamos ao estúdio"), alto
    demais pra sair só pelo volume. None = sem Whisper (fica só o corte por volume)."""
    if os.environ.get("EXPRESSIVO_SEM_WHISPER") == "1":
        return None
    try:
        import sys
        raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if raiz not in sys.path:
            sys.path.insert(0, raiz)
        import whisper_transcribe as wt  # type: ignore
        segs = wt.transcribe_audio(caminho, model_size=os.environ.get("EXPRESSIVO_WHISPER", "base"),
                                   language=(idioma or "pt")[:2], word_timestamps=True)
        palavras = [w for sg in segs for w in sg.get("words", [])]
        if not palavras:
            return None
        return float(palavras[0]["start"]), float(palavras[-1]["end"])
    except Exception:  # noqa: BLE001
        return None


def recortar(x, limites, antes: float = 0.15, depois: float = 0.3):
    """Recorta a janela das palavras (com folga: o Whisper costuma marcar o fim um pouco cedo)."""
    if not limites:
        return x
    ini = max(0, int((limites[0] - antes) * TAXA))
    fim = min(len(x), int((limites[1] + depois) * TAXA))
    return x[ini:fim] if fim - ini > int(0.2 * TAXA) else x


def parece_chiado(x) -> bool:
    """Som "de verdade" (risada, tosse) tem rajadas: o volume sobe e desce. Chiado/ruído é contínuo
    (medido no teste: a [risadinha] do Turbo saiu 1,8 s de chiado constante a -30 dB)."""
    import numpy as np
    e = _energia(x)
    if len(e) < 8:
        return False
    d = 20 * np.log10(np.maximum(e, 10 ** (-70 / 20)))
    return float(np.percentile(d, 90) - np.percentile(d, 25)) < 6.0 and len(e) * QUADRO > 0.6


def nivel_voz(x) -> float:
    """RMS da parte FALADA (quadros acima de -30 dB do pico) — referência pra nivelar sons e respiração."""
    import numpy as np
    e = _energia(x)
    if not len(e) or e.max() <= 0:
        return 0.0
    voz = e[e >= e.max() * 10 ** (-30 / 20)]
    return float(np.sqrt(np.mean(voz ** 2)))


def _ajustar_nivel(x, alvo_rms: float):
    if alvo_rms <= 0:
        return x
    atual = nivel_voz(x)
    return x * (alvo_rms / atual) if atual > 0 else x


def _ruido_sala(segundos: float):
    import numpy as np
    n = int(TAXA * float(segundos))
    rng = np.random.default_rng(len(_RUIDO_SEMENTE) + n)
    return (rng.standard_normal(n).astype(np.float32) * 10 ** (RUIDO_SALA_DB / 20))


_RUIDO_SEMENTE = "expressivo"


def _salvar(x, saida: str, limitar: bool = True) -> None:
    import numpy as np
    pico = float(np.abs(x).max()) if len(x) else 0.0
    teto = 10 ** (PICO_MAX_DB / 20) if limitar else 1.0
    if pico > teto:
        x = x * (teto / pico)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(saida, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(TAXA)
        out.writeframes(pcm.tobytes())


def referencia_do_estilo(vg: Any, perfil: Optional[str], estilo: str) -> Optional[str]:
    """Perfil 'minhavoz' + estilo 'soprosa' -> usa o perfil 'minhavoz_soprosa' se ele existir."""
    if not perfil or estilo == "normal":
        return None
    try:
        existentes = {p.lower(): p for p in vg.listar_perfis_de_voz()}
    except Exception:  # noqa: BLE001
        return None
    for sep in ("_", "-", " "):
        achado = existentes.get(f"{perfil}{sep}{estilo}".lower())
        if achado:
            return achado
    return None


def sintetizar(vg: Any, texto: str, output_path: str, idioma: str = "pt", speaker_wav: Optional[str] = None,
               voice_profile: Optional[str] = None, exaggeration: float = 0.5, cfg_weight: float = 0.5,
               use_gpu: Optional[bool] = None, on_log: Optional[Callable[[str], None]] = None,
               variante: str = "", sons: str = "falado") -> str:
    """Gera o .wav do roteiro com tags. `vg` = o módulo voice_generator (chatterbox_synthesize etc).
    `variante`: "pt-BR" ou "pt-PT" (no pod, pt-PT usa o modelo base em vez do pacote pt-BR)."""
    import numpy as np
    log = on_log or (lambda s: None)
    eventos = montar_eventos(texto, exaggeration, cfg_weight, sons=sons if sons in MODOS_SONS else "falado")
    if not any(e["tipo"] == "fala" for e in eventos):
        raise ExpressivoErro("Não sobrou nenhuma fala depois das tags — escreva o texto a ser narrado.")
    tmp = os.path.join(os.path.dirname(os.path.abspath(output_path)) or ".", f"_expressivo_{uuid.uuid4().hex[:8]}")
    os.makedirs(tmp, exist_ok=True)
    cache_som: Dict[str, Any] = {}
    avisos: List[str] = []
    try:
        # 1) gera tudo (fala aparada nas pontas; som aparado com limiar relativo)
        pedacos: List[Any] = []  # ("audio", array) | ("pausa", s) | ("som", array, tipo)
        prog = getattr(vg, "informar_progresso", None) or (lambda *a, **k: None)
        estado_prog = getattr(vg, "_PROGRESSO", {})
        estado_prog["silenciar_trechos"] = True  # quem conta é o expressivo: trecho N de M
        total_ev = sum(1 for e in eventos if e["tipo"] != "pausa") or 1
        feitos = 0
        prog(0, total_ev, "gerando")
        for i, ev in enumerate(eventos):
            if ev["tipo"] != "pausa" and i:
                prog(feitos, total_ev, "gerando")
            bruto = os.path.join(tmp, f"{i:04d}_bruto.wav")
            if ev["tipo"] == "pausa":
                pedacos.append(("pausa", float(ev["s"])))
            elif ev["tipo"] == "fala":
                kw: Dict[str, Any] = {"idioma": idioma, "exaggeration": ev["emocao"], "cfg_weight": ev["cfg"], "use_gpu": use_gpu}
                if variante:
                    kw["variante"] = variante
                ref_estilo = referencia_do_estilo(vg, voice_profile, ev["estilo"])
                if ref_estilo:
                    kw["voice_profile"] = ref_estilo
                elif speaker_wav:
                    kw["speaker_wav"] = speaker_wav
                elif voice_profile:
                    kw["voice_profile"] = voice_profile
                vg.chatterbox_synthesize(ev["texto"], bruto, **kw)
                lim = limites_falados(bruto, idioma)
                bruto_x = recortar(_carregar(bruto), lim)
                if abs(ev["velocidade"] - 1.0) >= 0.01:  # velocidade depois do recorte (os tempos do Whisper são do original)
                    bruto_v = os.path.join(tmp, f"{i:04d}_rec.wav")
                    _salvar(bruto_x, bruto_v, limitar=False)
                    bruto_x = _carregar(bruto_v, _filtro_tempo(ev["velocidade"]))
                pedacos.append(("audio", aparar(bruto_x)))
            else:  # som / respira: Turbo com a mesma voz
                som = "gasp" if ev["tipo"] == "respira" else ev["som"]
                try:
                    if som not in cache_som:
                        bruto_som = os.path.join(tmp, f"som_{len(cache_som)}_bruto.wav")
                        kw_t: Dict[str, Any] = {"use_gpu": use_gpu}
                        if speaker_wav:
                            kw_t["speaker_wav"] = speaker_wav
                        elif voice_profile:
                            kw_t["voice_profile"] = voice_profile
                        a = None
                        for tentativa in range(2):  # o Turbo é aleatório: se sair chiado/silêncio, tenta mais uma vez
                            vg.chatterbox_turbo_synthesize(f"[{som}]", bruto_som, **kw_t)
                            a = aparar(_carregar(bruto_som), abaixo_do_pico_db=45, piso_db=-65, margem_fim=0.2)
                            if len(a) and (som in ("shush", "sigh") or not parece_chiado(a)):  # "shh" é chiado mesmo
                                break
                            a = None
                        if a is None:
                            raise ExpressivoErro("o Turbo devolveu chiado/silêncio duas vezes")
                        cache_som[som] = a
                    pedacos.append(("som", cache_som[som], ev["tipo"]))
                except Exception as exc:  # noqa: BLE001 — sem Turbo: vira pausa, o resto do áudio sai
                    aviso = f"som [{som}] não saiu ({str(exc)[:120]}) — virou pausa"
                    if aviso not in avisos:
                        avisos.append(aviso)
                        log("⚠ " + aviso)
                    pedacos.append(("pausa", 0.35))

            if ev["tipo"] != "pausa":
                feitos += 1
        prog(total_ev, total_ev, "montando")
        estado_prog["silenciar_trechos"] = False
        # 2) nivela sons e respiração pelo volume da fala (o Turbo sai com outro volume)
        niveis = [nivel_voz(p[1]) for p in pedacos if p[0] == "audio" and len(p[1])]
        ref = float(np.median(niveis)) if niveis else 0.1
        partes: List[Any] = []
        anterior = None
        for p in pedacos:
            if p[0] == "pausa":
                partes.append(_ruido_sala(p[1]))
            elif p[0] == "audio":
                if anterior == "audio":  # fala colada em fala (troca de estilo sem pausa): respiro mínimo
                    partes.append(_ruido_sala(0.12))
                partes.append(p[1])
            elif p[2] == "respira":  # o "susto" bem baixo e curto = uma inspiração antes da frase
                r = _ajustar_nivel(p[1][: int(TAXA * 0.55)], ref * 10 ** (-RESPIRA_DB_ABAIXO_DA_FALA / 20))
                n_fade = min(len(r), int(TAXA * 0.12))
                if n_fade:
                    r = r.copy()
                    r[-n_fade:] *= np.linspace(1, 0, n_fade, dtype=np.float32)
                partes += [r, _ruido_sala(0.06)]
            else:
                som_x = _ajustar_nivel(p[1][: int(TAXA * 3.0)], ref * 10 ** (-SOM_DB_ABAIXO_DA_FALA / 20)).copy()
                n_fade = min(len(som_x), int(TAXA * 0.15))  # som termina suave, não "corta"
                if n_fade:
                    som_x[-n_fade:] *= np.linspace(1, 0, n_fade, dtype=np.float32)
                partes += [_ruido_sala(0.1), som_x, _ruido_sala(0.15)]
            anterior = p[0]
        x = np.concatenate([np.asarray(p, dtype=np.float32) for p in partes]) if partes else np.zeros(0, np.float32)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        _salvar(x, output_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return output_path


TEXTO_TESTE = """[linear] Olá! Este é um teste do modo expressivo do Chatterbox em português. Esta primeira parte é linear: leitura reta, sem valorizar nenhuma palavra.

[respira] [plena] Agora, voz plena. O aposentado leu a notícia no jornal, tirou os óculos e disse para a esposa: a partir de hoje, só *produtos orgânicos*. [pausa] São mais caros? São. Não importa.

[soprosa] [respira] Cinco e meia da manhã. Lorena respirou fundo e atravessou a rua em direção à praia. [pausa longa] Nunca mais foi vista.

[dramatica] Ninguém imaginava o que estava por vir. [suspiro] E aquela noite... mudou *tudo*.

[sorridente] Mas calma, hoje a história é outra! [risadinha] Ele pigarreou, ajeitou a gravata [pigarro] e pediu a mão dela em casamento. [pausa] Recebeu um sonoro não. [risada]

[camarada] Carro lindo, hein? Pintura estalando de nova. [pausa curta] Mas... e o motor? Quando foi a última vez que você trocou o óleo?

[reportagem] Trânsito lento na avenida principal até o centro. Quem está chegando agora deve ter paciência. Voltamos ao estúdio.

[projetada] É hoje! É agora! Liquidação com preços que você *nunca viu*! [tosse] Corre que acaba!

[normal] E assim termina o nosso teste. [respira] Se gostou, deixa o like. Até a próxima!"""


TEXTO_TESTE_PT = """[linear] Olá! Isto é um teste do modo expressivo do Chatterbox em português de Portugal. Esta primeira parte é linear: leitura direita, sem valorizar nenhuma palavra.

[respirar] [plena] Agora, voz plena. O reformado leu a notícia no jornal, tirou os óculos e disse à mulher: a partir de hoje, só *produtos biológicos*. [pausa] São mais caros? São. Não faz mal.

[sussurrada] [respirar] Cinco e meia da manhã. A Leonor respirou fundo e atravessou a rua em direção à praia. [pausa longa] Nunca mais foi vista.

[dramática] Ninguém imaginava o que estava para vir. [suspiro] E aquela noite... mudou *tudo*.

[sorridente] Mas calma, hoje a história é outra! [risota] Ele pigarreou, endireitou a gravata [pigarrear] e pediu-a em casamento. [pausa] Levou com um rotundo não. [gargalhada]

[cúmplice] Carro bonito, hã? A pintura ainda a brilhar. [pausa curta] Mas... e o motor? Quando foi a última vez que mudaste o óleo?

[reportagem] Trânsito lento na segunda circular, em direção ao centro. Quem está a chegar agora deve ter paciência. Regressamos ao estúdio.

[projectada] É hoje! É já! Saldos com preços que *nunca viu*! [tossidela] Despache-se, que acaba!

[normal] E assim termina o nosso teste. [respirar] Se gostou, deixe o seu gosto. Até à próxima!"""

TEXTOS_TESTE = {"pt-BR": TEXTO_TESTE, "pt-PT": TEXTO_TESTE_PT}

# ajuda da tela: variante -> [(grupo, [(tag, explicação)])]
AJUDA: Dict[str, List[tuple]] = {
    "pt-BR": [
        ("Estilo da voz — vale até a próxima tag de estilo", [
            ("[linear]", "leitura reta, sem valorizar palavra nenhuma; a base da narração"),
            ("[calma]", "tranquila e um pouco mais lenta; meditação, explicação"),
            ("[soprosa]", "voz com ar, suave, próxima; suspense leve, intimidade"),
            ("[carinhosa]", "soprosa + afeto; produto de bebê, beleza, mensagem gentil"),
            ("[dramatica]", "soprosa sem sorriso, frase descendo; tragédia, mistério"),
            ("[suspense]", "contida e lenta; antes de uma revelação"),
            ("[plena]", "volume normal de conversa, clara, chega fácil ao ouvido"),
            ("[seria]", "plena sem sorriso nenhum; notícia, assunto grave"),
            ("[sorridente]", "sorriso na voz; leve, simpática"),
            ("[alegre]", "animada e um pouco mais rápida; celebração"),
            ("[camarada]", "tom de amigo, íntimo, conversa sem interlocutor"),
            ("[ironica]", "sorridente com ironia; humor"),
            ("[reportagem]", "repórter de rua: direta, ágil, informativa"),
            ("[projetada]", "varejo: alta, forte, pra cima; promoção"),
            ("[agressiva]", "intensa e rápida; luta, ação, chamada de impacto"),
            ("[normal]", "volta à emoção e aderência que estão nos campos acima"),
        ]),
        ("Sons — Chatterbox Turbo com a mesma voz", [
            ("[risada]", "gargalhada"), ("[risadinha]", "risinho curto"), ("[suspiro]", "suspiro"),
            ("[tosse]", "tosse"), ("[pigarro]", "limpar a garganta"), ("[susto]", "puxar o ar de susto"),
            ("[gemido]", "gemido / resmungo"), ("[fungada]", "fungar"), ("[shh]", "pedir silêncio"),
        ]),
        ("Respiração e pausas", [
            ("[respira]", "inspiração curta e baixinha antes da frase (o “INSPIRE” da locução)"),
            ("[pausa]", "0,45 s"), ("[pausa curta]", "0,25 s"), ("[pausa longa]", "1 s"),
            ("[pausa 1.5]", "o tempo que você quiser, em segundos"),
            ("linha em branco", "pausa de parágrafo (0,6 s)"),
        ]),
        ("Palavra de valor e ajuste fino", [
            ("*palavra*", "pausinha antes e mais energia na palavra (ou trecho) entre asteriscos"),
            ("[emocao 0.7]", "intensidade emocional, de 0 a 1.2"),
            ("[cfg 0.3]", "aderência à voz de referência; mais baixo = mais pausado"),
            ("[velocidade 1.1]", "velocidade, de 0.6 a 1.6, sem mudar o tom"),
        ]),
    ],
    "pt-PT": [
        ("Estilo da voz — vale até à próxima etiqueta de estilo", [
            ("[linear]", "leitura direita, sem valorizar nenhuma palavra; a base da narração"),
            ("[calma]", "tranquila e um pouco mais lenta; meditação, explicação"),
            ("[sussurrada]", "voz com ar, suave, próxima; suspense leve, intimidade"),
            ("[ternurenta]", "sussurrada com afeto; produtos de bebé, beleza, mensagem gentil"),
            ("[dramática]", "sem sorriso, frase a descer; tragédia, mistério"),
            ("[suspense]", "contida e lenta; antes de uma revelação"),
            ("[plena]", "volume normal de conversa, clara, chega facilmente ao ouvido"),
            ("[séria]", "plena e sem sorriso nenhum; notícia, assunto grave"),
            ("[sorridente]", "sorriso na voz; leve, simpática"),
            ("[alegre]", "animada e um pouco mais rápida; celebração"),
            ("[cúmplice]", "tom de amigo, próximo, conversa sem interlocutor"),
            ("[irónica]", "sorridente com ironia; humor"),
            ("[reportagem]", "repórter de exterior / pivot: direta, ágil, informativa"),
            ("[projectada]", "comércio: alta, forte, para cima; promoções e saldos"),
            ("[agressiva]", "intensa e rápida; combate, ação, anúncio de impacto"),
            ("[normal]", "volta à emoção e aderência que estão nos campos acima"),
        ]),
        ("Sons — Chatterbox Turbo com a mesma voz", [
            ("[gargalhada]", "riso alto"), ("[risota]", "risinho curto"), ("[suspiro]", "suspiro"),
            ("[tossidela]", "tosse"), ("[pigarrear]", "aclarar a garganta"), ("[susto]", "inspirar de susto"),
            ("[gemido]", "gemido / resmungo"), ("[fungadela]", "fungar"), ("[chiu]", "pedir silêncio"),
        ]),
        ("Respiração e pausas", [
            ("[respirar]", "inspiração curta e baixinha antes da frase"),
            ("[pausa]", "0,45 s"), ("[pausa curta]", "0,25 s"), ("[pausa longa]", "1 s"),
            ("[pausa 1.5]", "o tempo que quiser, em segundos"),
            ("linha em branco", "pausa de parágrafo (0,6 s)"),
        ]),
        ("Palavra de valor e ajuste fino", [
            ("*palavra*", "pausinha antes e mais energia na palavra (ou excerto) entre asteriscos"),
            ("[emoção 0.7]", "intensidade emocional, de 0 a 1.2"),
            ("[cfg 0.3]", "aderência à voz de referência; mais baixo = mais pausado"),
            ("[velocidade 1.1]", "velocidade, de 0.6 a 1.6, sem mudar o tom"),
        ]),
    ],
}
