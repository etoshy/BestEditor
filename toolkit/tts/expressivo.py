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
ESTILOS: Dict[str, tuple] = {
    "normal": (None, None, 1.0),
    "linear": (0.30, 0.55, 1.0),
    "calma": (0.35, 0.50, 0.95),
    "soprosa": (0.40, 0.45, 0.95),
    "carinhosa": (0.50, 0.45, 0.97),
    "dramatica": (0.55, 0.35, 0.92),
    "suspense": (0.50, 0.35, 0.90),
    "plena": (0.45, 0.50, 1.0),
    "seria": (0.40, 0.55, 1.0),
    "sorridente": (0.65, 0.45, 1.03),
    "alegre": (0.70, 0.45, 1.05),
    "camarada": (0.55, 0.45, 1.0),
    "ironica": (0.60, 0.45, 1.0),
    "reportagem": (0.50, 0.50, 1.05),
    "projetada": (0.80, 0.40, 1.06),
    "agressiva": (0.85, 0.35, 1.08),
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
TURBO_SONS = {"laugh", "chuckle", "gasp", "cough", "sigh", "groan", "sniff", "shush", "clear throat"}

PAUSAS = {"pausa": 0.45, "pausa curta": 0.25, "pausa longa": 1.0, "silencio": 0.8}
PAUSA_PARAGRAFO = 0.6
PAUSA_ENFASE = 0.14
EXTRA_EMOCAO_ENFASE = 0.15
MIN_CHARS_DIVIDIR_ENFASE = 18

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


def montar_eventos(texto: str, emocao_base: float = 0.5, cfg_base: float = 0.5) -> List[Dict[str, Any]]:
    """Roteiro com tags -> lista de eventos: fala / som / respira / pausa."""
    eventos: List[Dict[str, Any]] = []
    estado = {"estilo": "normal", "emocao": emocao_base, "cfg": cfg_base, "velocidade": 1.0}

    def aplicar_estilo(nome: str) -> None:
        e, c, v = ESTILOS[nome]
        estado.update(estilo=nome, emocao=emocao_base if e is None else e, cfg=cfg_base if c is None else c, velocidade=v)

    def fala(trecho: str) -> None:
        # ênfase: *palavra* -> divide em [antes] pausinha [palavra + resto com mais emoção]
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
            if len(limpar_fala(antes)) >= MIN_CHARS_DIVIDIR_ENFASE and len(limpar_fala(dentro)) >= MIN_CHARS_DIVIDIR_ENFASE:
                _push_fala(antes)
                eventos.append({"tipo": "pausa", "s": PAUSA_ENFASE})
                _push_fala(dentro, extra=EXTRA_EMOCAO_ENFASE, enfase=p)
            else:  # curto demais pra dividir (o Chatterbox trava com texto muito curto): vírgula antes = pausinha
                _push_fala(antes.rstrip() + ", " + dentro.lstrip(), extra=EXTRA_EMOCAO_ENFASE / 2, enfase=p)
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
            else:
                fala(pendente)
                pendente = ""
                eventos.append(dict(info))
        fala(pendente + par[pos:])
    while eventos and eventos[-1]["tipo"] == "pausa":
        eventos.pop()
    return eventos


# ------------------------------------------------------------------ áudio (ffmpeg + wave, sem numpy)
def _ffmpeg_pcm(entrada: str, saida: str, filtros: List[str], max_s: Optional[float] = None) -> None:
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", entrada]
    if filtros:
        cmd += ["-af", ",".join(filtros)]
    if max_s:
        cmd += ["-t", str(max_s)]
    cmd += ["-ar", str(TAXA), "-ac", "1", "-c:a", "pcm_s16le", saida]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0 or not os.path.exists(saida):
        raise ExpressivoErro(f"ffmpeg falhou ao preparar um pedaço: {r.stderr.decode(errors='replace')[-300:]}")


def _filtro_tempo(v: float) -> List[str]:
    if abs(v - 1.0) < 0.01:
        return []
    return [f"atempo={max(0.5, min(v, 2.0)):.3f}"]


APARAR = ("silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0.03,areverse,"
          "silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0.05,areverse")


def _juntar(pedacos: List[Any], saida: str) -> None:
    """pedacos: caminho de .wav (já 24k mono s16) ou float (segundos de silêncio)."""
    with wave.open(saida, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(TAXA)
        for p in pedacos:
            if isinstance(p, (int, float)):
                out.writeframes(b"\x00\x00" * int(TAXA * float(p)))
            else:
                with wave.open(p, "rb") as w:
                    out.writeframes(w.readframes(w.getnframes()))


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
               variante: str = "") -> str:
    """Gera o .wav do roteiro com tags. `vg` = o módulo voice_generator (chatterbox_synthesize etc).
    `variante`: "pt-BR" ou "pt-PT" (no pod, pt-PT usa o modelo base em vez do pacote pt-BR)."""
    log = on_log or (lambda s: None)
    eventos = montar_eventos(texto, exaggeration, cfg_weight)
    if not any(e["tipo"] == "fala" for e in eventos):
        raise ExpressivoErro("Não sobrou nenhuma fala depois das tags — escreva o texto a ser narrado.")
    tmp = os.path.join(os.path.dirname(os.path.abspath(output_path)) or ".", f"_expressivo_{uuid.uuid4().hex[:8]}")
    os.makedirs(tmp, exist_ok=True)
    cache_som: Dict[str, str] = {}
    avisos: List[str] = []
    try:
        pedacos: List[Any] = []
        for i, ev in enumerate(eventos):
            bruto = os.path.join(tmp, f"{i:04d}_bruto.wav")
            pronto = os.path.join(tmp, f"{i:04d}.wav")
            if ev["tipo"] == "pausa":
                pedacos.append(float(ev["s"]))
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
                _ffmpeg_pcm(bruto, pronto, _filtro_tempo(ev["velocidade"]))
                pedacos.append(pronto)
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
                        vg.chatterbox_turbo_synthesize(f"[{som}]", bruto_som, **kw_t)
                        cache_som[som] = bruto_som
                    if ev["tipo"] == "respira":  # suspiro de susto bem baixinho e curto = uma inspiração
                        _ffmpeg_pcm(cache_som[som], pronto, [APARAR, "volume=-14dB", "afade=t=in:d=0.08",
                                                             "afade=t=out:st=0.35:d=0.12"], max_s=0.5)
                        pedacos += [pronto, 0.08]
                    else:
                        _ffmpeg_pcm(cache_som[som], pronto, [APARAR, "volume=-3dB", "afade=t=out:st=2.3:d=0.2"], max_s=2.5)
                        pedacos += [0.08, pronto, 0.12]
                except Exception as exc:  # noqa: BLE001 — sem Turbo: vira pausa, o resto do áudio sai
                    aviso = f"som [{som}] não saiu ({str(exc)[:120]}) — virou pausa"
                    if aviso not in avisos:
                        avisos.append(aviso)
                        log("⚠ " + aviso)
                    pedacos.append(0.35)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        _juntar(pedacos, output_path)
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
