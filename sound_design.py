"""
🎧 v84_399 — Sound design automático no Estúdio (vídeo longo), pelos fundamentos dos cursos de sound design:

  1. 🎯 EMOÇÃO POR TRECHO — a IA lê a narração (com os tempos) e divide o vídeo em blocos com uma emoção-alvo
     (tensão, tristeza, alegria…). Tudo o que entra de som serve a essa emoção. Você troca no painel.
  2. 🌫 AMBIENTE — uma cama de ambiente por bloco (buscada no Pixabay pela emoção + o lugar), baixinha, que também
     tapa os "buracos mortos" entre as frases (o papel do room tone).
  3. 🎵 MÚSICA POR EMOÇÃO — troca de faixa quando a emoção muda (com fade), "🤫 silêncio" onde a cena pede; a música
     abaixa sozinha quando a voz fala (ducking).
  4. 💥 ACENTOS COM EQUILÍBRIO — antecipação (riser/reverse) → respiro (as camadas abaixam meio segundo) → impacto,
     só nos poucos momentos-chave ("se todo momento é especial, nenhum é").
  5. 🎚 MIXAGEM POR NÍVEIS — voz na frente; efeitos -10 a -30 dB; música -20 a -30 dB debaixo da voz; ambiente bem
     baixo; reverb leve nos efeitos (som de estúdio soa "seco"); limitador no fim (nada estoura).

Fonte de áudio: só o Pixabay (efeitos e música), pelo navegador do site (pixabay_sons_teste.py).
O plano fica em job["sound_design"]; a montagem usa `para_montar` → `eventos_acentos` + `aplicar`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from typing import Any, Callable, Dict, List, Optional

RECURSO = "sound_design"

# emoção → como ela soa (buscas em inglês pro Pixabay: termo largo + adjetivo simples, como nos bancos clássicos)
EMOCOES: Dict[str, Dict[str, Any]] = {
    "neutro": {"nome": "😐 Neutro / explicativo", "cor": "#64748b",
               "ambiente_en": "room tone quiet", "musica_en": "calm documentary background"},
    "tensao": {"nome": "😬 Tensão / suspense", "cor": "#b45309",
               "ambiente_en": "dark drone ambience", "musica_en": "suspense tension dark"},
    "medo": {"nome": "😨 Medo / terror", "cor": "#7f1d1d",
             "ambiente_en": "eerie horror ambience", "musica_en": "horror dark ambient"},
    "tristeza": {"nome": "😢 Tristeza / emoção", "cor": "#1d4ed8",
                 "ambiente_en": "light rain ambience", "musica_en": "sad piano emotional"},
    "alegria": {"nome": "😄 Alegria / leveza / humor", "cor": "#ca8a04",
                "ambiente_en": "birds park ambience", "musica_en": "happy playful upbeat"},
    "energia": {"nome": "🔥 Energia / épico", "cor": "#dc2626",
                "ambiente_en": "crowd cheering ambience", "musica_en": "epic cinematic energetic"},
    "calma": {"nome": "😌 Calma / reflexão", "cor": "#059669",
              "ambiente_en": "stream water nature", "musica_en": "calm ambient relaxing"},
    "misterio": {"nome": "🕵️ Mistério / curiosidade", "cor": "#7c3aed",
                 "ambiente_en": "mysterious ambience drone", "musica_en": "mysterious curious"},
    "silencio": {"nome": "🤫 Silêncio (sem música)", "cor": "#111827",
                 "ambiente_en": "room tone quiet", "musica_en": ""},
}

# momento-chave → as peças (antecipação + impacto), por força 1–3
ACENTOS_BUSCA = {"riser": "cinematic riser", "reverse": "reverse whoosh", "impacto": "cinematic hit impact",
                 "boom": "cinematic boom"}
TIPOS_MOMENTO = {"revelacao": "💡 revelação", "virada": "🔀 virada", "impacto": "💥 impacto"}

# 🎚 níveis (multiplicador sobre a narração, que fica em 1.0) — o guia dos vídeos em dB, convertido
NIVEIS = {  # os arquivos chegam normalizados em -20 LUFS (audio_qualidade) — os ganhos partem daí
    "musica": 0.28,      # ~ -11 dB → ~ -31 LUFS; com a voz falando o ducking leva uns -8 dB a mais (o "-20 a -30" dos vídeos)
    "ambiente": 0.12,    # ~ -18 dB → ~ -38 LUFS: só uma cama
    "acento_forte": 0.85,  # efeitos: -1 a -10 dB nos momentos-chave
    "acento_fraco": 0.42,
    "respiro": 0.25,     # as camadas caem pra 25% no meio segundo antes do impacto
}
FADE = 1.5
CAMADAS_PADRAO = {"ambiente": True, "musica": True, "acentos": True, "mix": True, "juiz": True, "memes": True}


def vazio() -> Dict[str, Any]:
    return {"blocos": [], "momentos": [], "camadas": dict(CAMADAS_PADRAO), "audios": {}, "log": []}


def estado(job: Dict[str, Any]) -> Dict[str, Any]:
    sd = job.get("sound_design")
    if not isinstance(sd, dict):
        sd = vazio()
        job["sound_design"] = sd
    for k, v in vazio().items():
        sd.setdefault(k, v)
    for k, v in CAMADAS_PADRAO.items():
        sd["camadas"].setdefault(k, v)
    return sd


# ------------------------------------------------------------------ 1. 🎯 a IA lê as emoções
SCHEMA = {
    "type": "object",
    "properties": {
        "blocos": {"type": "array", "items": {"type": "object", "properties": {
            "inicio": {"type": "number"}, "fim": {"type": "number"},
            "emocao": {"type": "string", "enum": list(EMOCOES)},
            "lugar": {"type": "string"}, "ambiente_en": {"type": "string"}, "musica_en": {"type": "string"},
            "por_que": {"type": "string"}},
            "required": ["inicio", "fim", "emocao", "ambiente_en", "musica_en"], "additionalProperties": False}},
        "momentos": {"type": "array", "items": {"type": "object", "properties": {
            "t": {"type": "number"}, "tipo": {"type": "string", "enum": list(TIPOS_MOMENTO)},
            "forca": {"type": "integer"}, "frase": {"type": "string"}},
            "required": ["t", "tipo", "forca"], "additionalProperties": False}},
    },
    "required": ["blocos", "momentos"], "additionalProperties": False,
}

SISTEMA = """Você é o sound designer de um vídeo narrado do YouTube. Recebe a narração com os tempos (segundos).

REGRA Nº 1 (a mais importante): antes de qualquer som, decida a EMOÇÃO-ALVO de cada parte. Todo som vai servir a ela.

1) "blocos": divida o vídeo INTEIRO em blocos contínuos (o 1º começa em 0, cada um começa onde o outro termina, o último
   termina no fim da narração), cada um com UMA emoção. Blocos longos (30 s a 3 min; nunca menos de 15 s) — só troque
   quando o clima muda de verdade. Emoções: {emocoes}.
   Use "silencio" (sem música) só num momento de peso (luto, choque, uma frase que precisa ficar sozinha), e curto.
   Para cada bloco:
   - "lugar": onde a cena se passa, se a narração diz (ex.: "floresta à noite", "escritório", "mar") — senão "";
   - "ambiente_en": a busca do AMBIENTE no banco de efeitos (inglês, 2 a 4 palavras): termo LARGO e universal + um
     adjetivo simples (light/heavy, soft/hard, slow/fast, big/small) — ex.: "rain light", "wind heavy", "city night",
     "forest birds", "fire crackling", "office hum", "dark drone". Pense no SOM do lugar/clima, não na cena.
   - "musica_en": a busca da MÚSICA no banco de música (inglês, 2 a 4 palavras): humor + instrumento/gênero — ex.:
     "sad piano", "dark suspense drone", "epic orchestral", "happy ukulele", "mysterious ambient". Vazio no "silencio".
2) "momentos": os momentos-chave que ganham acento (antecipação → impacto): uma revelação, uma virada, um número
   chocante, o clímax. EQUILÍBRIO: se todo momento é especial, nenhum é — no máximo {max_momentos} no vídeo todo.
   "t" = o segundo EXATO em que a palavra/frase-chave começa; "forca": 1 (sutil), 2 (médio), 3 (o clímax — no
   máximo 1 ou 2 no vídeo); "frase": as palavras do momento.
Responda só o JSON."""


def _blocos_narracao(job: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for b in job.get("segments") or []:
        txt = " ".join(str(b.get("text") or "").split())
        if txt:
            try:
                out.append({"start": float(b.get("start") or 0), "end": float(b.get("end") or 0), "text": txt})
            except (TypeError, ValueError):
                continue
    return out


def texto_com_tempos(job: Dict[str, Any], limite: int = 60000) -> str:
    return "\n".join(f"[{b['start']:.1f}–{b['end']:.1f}] {b['text']}" for b in _blocos_narracao(job))[:limite]


def duracao(job: Dict[str, Any]) -> float:
    try:
        d = float(job.get("total_duration") or 0)
    except (TypeError, ValueError):
        d = 0.0
    if d <= 0:
        bl = _blocos_narracao(job)
        d = max([b["end"] for b in bl] or [0.0])
    return d


def max_momentos(dur: float) -> int:
    return max(2, min(12, int(round(dur / 90.0)) + 1))


def ler_resposta(r: Any, dur: float) -> Dict[str, Any]:
    """Limpa o que a IA mandou: blocos contínuos de 0 ao fim, emoções válidas, momentos espaçados e no limite."""
    blocos_in = (r or {}).get("blocos") if isinstance(r, dict) else None
    blocos: List[Dict[str, Any]] = []
    for x in sorted([b for b in blocos_in or [] if isinstance(b, dict)], key=lambda b: float(b.get("inicio") or 0)):
        try:
            a, b = float(x.get("inicio") or 0), float(x.get("fim") or 0)
        except (TypeError, ValueError):
            continue
        emo = x.get("emocao") if x.get("emocao") in EMOCOES else "neutro"
        if blocos and (emo == blocos[-1]["emocao"] or b - a < 8):  # mesma emoção seguida / pedacinho: junta
            blocos[-1]["end"] = max(blocos[-1]["end"], b)
            continue
        blocos.append(novo_bloco(a, b, emo, x.get("ambiente_en"), x.get("musica_en"), x.get("lugar"), x.get("por_que")))
    if not blocos:
        blocos = [novo_bloco(0, dur, "neutro")]
    blocos[0]["start"] = 0.0
    for k in range(1, len(blocos)):  # contínuos: cada um começa onde o outro termina
        blocos[k]["start"] = blocos[k - 1]["end"] = round(max(blocos[k - 1]["start"] + 1, blocos[k]["start"]), 2)
    if dur > 0:
        blocos[-1]["end"] = round(dur, 2)
    momentos: List[Dict[str, Any]] = []
    for x in sorted([m for m in ((r or {}).get("momentos") or []) if isinstance(m, dict)],
                    key=lambda m: -int(m.get("forca") or 1)):  # os mais fortes primeiro
        try:
            t = float(x.get("t") or 0)
        except (TypeError, ValueError):
            continue
        if t < 2 or (dur and t > dur - 0.5) or any(abs(t - m["t"]) < 12 for m in momentos):
            continue
        momentos.append(novo_momento(t, x.get("tipo"), x.get("forca"), x.get("frase")))
        if len(momentos) >= max_momentos(dur):
            break
    fortes = [m for m in sorted(momentos, key=lambda m: -m["forca"]) if m["forca"] == 3]
    for m in fortes[2:]:  # clímax de verdade: no máximo 2
        m["forca"] = 2
    momentos.sort(key=lambda m: m["t"])
    return {"blocos": blocos, "momentos": momentos}


def novo_bloco(a: float, b: float, emo: str = "neutro", amb: Any = None, mus: Any = None, lugar: Any = None,
               por_que: Any = None) -> Dict[str, Any]:
    e = EMOCOES.get(emo) or EMOCOES["neutro"]
    limpa = lambda s, lim=60: " ".join(str(s or "").split())[:lim]  # noqa: E731
    return {"id": uuid.uuid4().hex[:8], "start": round(float(a), 2), "end": round(float(b), 2), "emocao": emo,
            "ambiente_en": limpa(amb) or e["ambiente_en"],
            "musica_en": "" if emo == "silencio" else (limpa(mus) or e["musica_en"]),
            "lugar": limpa(lugar, 80), "por_que": limpa(por_que, 200)}


def novo_momento(t: float, tipo: Any = "impacto", forca: Any = 2, frase: Any = "") -> Dict[str, Any]:
    try:
        f = max(1, min(3, int(forca or 2)))
    except (TypeError, ValueError):
        f = 2
    return {"id": uuid.uuid4().hex[:8], "t": round(float(t), 2), "tipo": tipo if tipo in TIPOS_MOMENTO else "impacto",
            "forca": f, "frase": " ".join(str(frase or "").split())[:120]}


def analisar(job: Dict[str, Any], chamar: Optional[Callable[..., Any]] = None, job_id: str = "") -> Dict[str, Any]:
    if chamar is None:
        import ia_servico
        chamar = ia_servico.chamar
    texto = texto_com_tempos(job)
    if not texto.strip():
        raise ValueError("Esse vídeo não tem a narração com os tempos (transcrição).")
    dur = duracao(job)
    sis = SISTEMA.replace("{emocoes}", ", ".join(f"{k} ({v['nome']})" for k, v in EMOCOES.items())) \
                 .replace("{max_momentos}", str(max_momentos(dur)))
    r = chamar(RECURSO, sis, f"DURAÇÃO TOTAL: {dur:.1f} s\n\nNARRAÇÃO (com os tempos em segundos):\n\n" + texto,
               schema=SCHEMA, max_tokens=6000, effort="medium", timeout=300, job=job_id or None)
    if r is None:
        import ia_servico
        raise RuntimeError("A IA não respondeu: " + (ia_servico.motivo_desligado(RECURSO) or ia_servico.ultimo_erro(RECURSO)
                                                      or "veja as últimas chamadas em 🤖 IA"))
    return ler_resposta(r, dur)


def salvar_plano(job: Dict[str, Any], corpo: Dict[str, Any]) -> Dict[str, Any]:
    """O que você mudou no painel (emoções, buscas, momentos, camadas)."""
    sd = estado(job)
    dur = duracao(job)
    if isinstance(corpo.get("blocos"), list):
        velhos = {b["id"]: b for b in sd["blocos"]}
        novos = []
        for x in corpo["blocos"]:
            try:
                a, b = float(x.get("start") or 0), float(x.get("end") or 0)
            except (TypeError, ValueError):
                continue
            emo = x.get("emocao") if x.get("emocao") in EMOCOES else "neutro"
            v = velhos.get(x.get("id")) or {}
            nb = novo_bloco(a, b, emo, x.get("ambiente_en"), x.get("musica_en") if emo != "silencio" else "", x.get("lugar"),
                            v.get("por_que"))
            nb["id"] = v.get("id") or nb["id"]
            if emo != "silencio" and "musica_en" in x and not str(x.get("musica_en") or "").strip():
                nb["musica_en"] = ""  # você apagou a música deste bloco de propósito
            novos.append(nb)
        sd["blocos"] = ler_resposta({"blocos": [dict(b, inicio=b["start"], fim=b["end"]) for b in novos]}, dur)["blocos"] \
            if novos else []
        for nb, x in zip(sd["blocos"], novos):  # mantém ids e buscas (o ler_resposta só arruma tempos)
            nb.update(id=x["id"], ambiente_en=x["ambiente_en"], musica_en=x["musica_en"])
    if isinstance(corpo.get("momentos"), list):
        sd["momentos"] = sorted([novo_momento(m.get("t") or 0, m.get("tipo"), m.get("forca"), m.get("frase"))
                                 for m in corpo["momentos"] if isinstance(m, dict)], key=lambda m: m["t"])
    if isinstance(corpo.get("camadas"), dict):
        sd["camadas"] = {k: bool(corpo["camadas"].get(k, v)) for k, v in CAMADAS_PADRAO.items()}
    return sd


# ------------------------------------------------------------------ 2–4. 🔊 os áudios (Pixabay; 📣 MyInstants de reserva)
# o que o 🎯 juiz (CLAP) compara: a frase do alvo × as alternativas (quem vence diz se combina)
CLAP_EMOCAO = {
    "neutro": "neutral calm background music for a documentary", "tensao": "tense suspenseful dark music",
    "medo": "scary horror creepy music", "tristeza": "sad melancholic emotional music",
    "alegria": "happy upbeat cheerful playful music", "energia": "epic energetic powerful music",
    "calma": "calm peaceful relaxing music", "misterio": "mysterious curious enigmatic music", "silencio": "silence",
}
CLAP_ACENTO = {"riser": "rising tension riser sound effect", "reverse": "reverse whoosh sound effect",
               "impacto": "cinematic hit impact sound effect", "boom": "deep cinematic boom sound effect"}
CONTRA_EFEITO = ["music with melody", "people talking speech", "funny cartoon meme sound", "silence"]
NOTA_MINIMA = 35        # abaixo disso o candidato soa como outra coisa: recusado (se tiver outro)
BONUS_PIXABAY = 12      # o MyInstants só ganha se combinar MUITO mais


def pedidos(sd: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Cada áudio que o plano precisa: {chave, tipo (efeitos/musica), termo, uso, alvo, contra}."""
    out: Dict[str, Dict[str, Any]] = {}
    cam = sd["camadas"]
    for b in sd["blocos"]:
        if cam.get("ambiente") and b.get("ambiente_en"):
            out.setdefault("efeitos:" + b["ambiente_en"], {
                "chave": "efeitos:" + b["ambiente_en"], "tipo": "efeitos", "termo": b["ambiente_en"], "uso": "ambiente",
                "alvo": f"{b['ambiente_en']} ambience background sound", "contra": CONTRA_EFEITO})
        if cam.get("musica") and b.get("musica_en"):
            outras = [v for k, v in CLAP_EMOCAO.items() if k not in (b["emocao"], "silencio", "neutro")]
            out.setdefault("musica:" + b["musica_en"], {
                "chave": "musica:" + b["musica_en"], "tipo": "musica", "termo": b["musica_en"], "uso": "musica",
                "alvo": f"{b['musica_en']}, {CLAP_EMOCAO.get(b['emocao'], '')}", "contra": outras})
    if cam.get("acentos") and sd.get("momentos"):
        for nome, termo in ACENTOS_BUSCA.items():
            out.setdefault("efeitos:" + termo, {
                "chave": "efeitos:" + termo, "tipo": "efeitos", "termo": termo, "uso": "acento",
                "alvo": CLAP_ACENTO[nome], "contra": CONTRA_EFEITO + [v for k, v in CLAP_ACENTO.items() if k != nome]})
    return list(out.values())


def buscas_necessarias(sd: Dict[str, Any]) -> Dict[str, List[str]]:
    """{"efeitos": [...], "musica": [...]} — só as que ainda não têm áudio escolhido."""
    aud = sd.get("audios") or {}
    falta: Dict[str, List[str]] = {"efeitos": [], "musica": []}
    for pd in pedidos(sd):
        a = aud.get(pd["chave"]) or {}
        if not (a.get("arquivo") and os.path.isfile(a["arquivo"])):
            falta[pd["tipo"]].append(pd["termo"])
    return falta


def _catalogo(pasta_p: str) -> List[Dict[str, Any]]:
    try:
        with open(os.path.join(pasta_p, "catalogo.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def candidatos(pastas: List[str], termo: str, tipo: str) -> List[Dict[str, Any]]:
    t = " ".join(termo.lower().split())
    out = []
    for pasta in pastas:
        for x in _catalogo(pasta):
            if " ".join(str(x.get("busca") or "").lower().split()) == t and (x.get("tipo") or "efeitos") == tipo \
                    and x.get("arquivo_cortado") and os.path.isfile(x["arquivo_cortado"]):
                out.append(dict(x, fonte=x.get("fonte") or "pixabay"))
    return out


def escolher(pd: Dict[str, Any], cands: List[Dict[str, Any]], ouvido: Any = None,
             qualidade: Optional[Callable[[str], Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """O melhor candidato pra um pedido:
      1) 🔊 fora os estourados/mudos (checagem técnica — vale pra qualquer fonte);
      2) 🎯 com o juiz (CLAP): a maior nota contra as alternativas; abaixo de NOTA_MINIMA = soa como outra coisa
         (fica só se não tiver nada melhor, marcado ⚠); o Pixabay leva um bônus (o MyInstants é reserva);
      3) sem juiz: cama (ambiente/música) = a mais longa (≥ 20 s), acento = o 1º, Pixabay antes.
    Devolve o candidato com "nota", "soa_como", "aviso"."""
    if qualidade is None:
        import audio_qualidade as AQ
        qualidade = AQ.avaliar
    longo = pd["uso"] in ("ambiente", "musica")
    avaliados = []
    for c in cands:
        q = c.get("qualidade") or qualidade(c["arquivo_cortado"])
        avaliados.append(dict(c, qualidade=q))
    bons = [c for c in avaliados if (c["qualidade"] or {}).get("ok", True)] or []
    if not bons:
        return None
    if ouvido is not None:
        notas = []
        for c in bons:
            try:
                n = ouvido.nota(c["arquivo_cortado"], pd["alvo"], pd["contra"])
            except Exception:  # noqa: BLE001
                n = {"nota": 0, "soa_como": [], "vence": ""}
            extra = (BONUS_PIXABAY if c["fonte"] == "pixabay" else 0) + (5 if longo and float(c.get("dur") or 0) >= 20 else 0)
            notas.append((n["nota"] + extra, n, c))
        notas.sort(key=lambda x: -x[0])
        _s, n, c = notas[0]
        return dict(c, nota=n["nota"], soa_como=n.get("soa_como") or [],
                    aviso="" if n["nota"] >= NOTA_MINIMA else f"soa mais como “{n.get('vence') or '?'}” — confira")
    pix = [c for c in bons if c["fonte"] == "pixabay"] or bons
    if longo:
        com20 = [x for x in pix if float(x.get("dur") or 0) >= 20] or pix
        c = max(com20, key=lambda x: (int(x.get("curtidas") or 0), float(x.get("dur") or 0)))
    else:
        c = pix[0]
    return dict(c, nota=None, soa_como=[], aviso="")


def pico_musica(caminho: str, ignorar_inicio: float = 3.0) -> Optional[float]:
    """🎵 v84_403: o segundo do "drop" — onde a música fica mais forte (energia média em 2 s, depois da introdução)."""
    try:
        import numpy as np
        r_ = subprocess.run(["ffmpeg", "-v", "error", "-i", caminho, "-t", "600", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                            capture_output=True, timeout=300)
        x = np.frombuffer(r_.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception:  # noqa: BLE001
        return None
    q = 4000  # janelas de 0,5 s
    n = len(x) // q
    if n < 8:
        return None
    rms = np.sqrt((x[: n * q].reshape(n, q) ** 2).mean(axis=1) + 1e-9)
    suave = np.convolve(rms, np.ones(4) / 4, mode="same")
    ini = min(n - 1, int(ignorar_inicio * 2))
    # o drop = a maior SUBIDA de energia (não só o mais alto): compara cada janela com a de 2 s antes
    idx = np.arange(ini, n)
    antes = suave[np.maximum(0, idx - 4)]
    subida = suave[ini:] - antes
    k = int(np.argmax(subida + 0.5 * suave[ini:]))
    return round((ini + k) * 0.5, 2)


def guardar(sd: Dict[str, Any], pd: Dict[str, Any], c: Dict[str, Any], pasta_job: str,
            normalizar: Optional[Callable[[str, str], str]] = None) -> None:
    """Copia o escolhido pra pasta do projeto JÁ NORMALIZADO (volume de referência) — os níveis da mixagem valem pra
    qualquer fonte."""
    if normalizar is None:
        import audio_qualidade as AQ
        normalizar = AQ.normalizar
    destino = os.path.join(pasta_job, "sound_design")
    os.makedirs(destino, exist_ok=True)
    base = f"{pd['tipo']}_{re.sub(r'[^a-z0-9]+', '_', pd['termo'].lower())[:40]}_{c.get('id')}"
    arq = os.path.join(destino, base + ".m4a")
    try:
        normalizar(c["arquivo_cortado"], arq)
    except Exception:  # noqa: BLE001 — sem normalizar: vai como veio
        arq = os.path.join(destino, base + (os.path.splitext(c["arquivo_cortado"])[1] or ".m4a"))
        shutil.copy(c["arquivo_cortado"], arq)
    q = c.get("qualidade") or {}
    sd.setdefault("audios", {})[pd["chave"]] = {
        "arquivo": arq, "titulo": str(c.get("titulo") or "")[:120], "autor": str(c.get("autor") or "")[:80],
        "pagina": str(c.get("pagina") or ""), "dur": float(c.get("dur") or 0), "pico": float(c.get("pico") or 0),
        "id": str(c.get("id") or ""), "fonte": c.get("fonte") or "pixabay", "nota": c.get("nota"),
        "soa_como": c.get("soa_como") or [], "aviso": c.get("aviso") or "",
        "lufs": q.get("lufs"), "estourado": bool(q.get("estourado")),
        "pico_musica": pico_musica(arq) if pd["tipo"] == "musica" else None}


def buscar_audios(sd: Dict[str, Any], pasta_p: str, pasta_job: str, prog: Callable[[str], None] = lambda s: None,
                  rodar: Optional[Callable[..., int]] = None, pasta_memes: str = "",
                  rodar_memes: Optional[Callable[..., int]] = None, ouvido: Any = None,
                  qualidade: Optional[Callable[[str], Dict[str, Any]]] = None,
                  normalizar: Optional[Callable[[str, str], str]] = None) -> Dict[str, Any]:
    """1) Pixabay (o navegador abre UMA vez por tipo) → 2) checagem + 🎯 juiz → 3) 📣 MyInstants pros efeitos que
    ficaram sem nada que preste → 4) guarda normalizado."""
    import argparse
    cam = sd["camadas"]
    if ouvido is None and cam.get("juiz", True):
        try:
            import audio_juiz
            ouvido = audio_juiz.ouvido(os.path.join(pasta_p, "_clap_cache.json"))
            prog("🎯 juiz de áudio (CLAP) ligado" if ouvido else
                 "🎯 juiz de áudio desligado: " + (audio_juiz.disponivel() or audio_juiz.ultimo_erro() or "?"))
        except Exception as exc:  # noqa: BLE001
            prog(f"🎯 juiz de áudio indisponível: {str(exc)[:120]}")
            ouvido = None
    recus = sd.get("recusados") or {}

    def livres(pastas: List[str], termo: str, tipo: str) -> List[Dict[str, Any]]:  # sem os que você já trocou (🔁)
        fora = set(recus.get(f"{tipo}:{termo}") or [])
        return [c for c in candidatos(pastas, termo, tipo) if str(c.get("id")) not in fora]
    falta = buscas_necessarias(sd)
    for tipo, termos in falta.items():
        termos = [t for t in termos if not livres([pasta_p], t, tipo)]
        if not termos:
            continue
        prog(f"🔊 Pixabay ({'música' if tipo == 'musica' else 'efeitos'}): " + ", ".join(f"“{t}”" for t in termos))
        if rodar is None:
            import pixabay_sons_teste as PT
            rodar_fn = PT.rodar
        else:
            rodar_fn = rodar
        segunda = any(recus.get(f"{tipo}:{t}") for t in termos)  # já trocou todos da 1ª página: vai pra 2ª
        args = argparse.Namespace(termo=termos[0], termos=termos, paginas=2 if segunda else 1, limite=4, pasta=pasta_p, oculto=False,
                                  chrome=False, ia=False, sem_baixar=False, html=None,
                                  tipo="music" if tipo == "musica" else "sound-effects")
        try:
            rodar_fn(args)
        except Exception as exc:  # noqa: BLE001 — uma busca que falha não derruba as outras
            prog(f"⚠ Pixabay falhou: {str(exc)[:160]}")
    n, sem_nada = 0, []
    aud = sd.setdefault("audios", {})
    for pd in pedidos(sd):
        if aud.get(pd["chave"]) and os.path.isfile(aud[pd["chave"]].get("arquivo") or ""):
            continue
        c = escolher(pd, livres([pasta_p], pd["termo"], pd["tipo"]), ouvido, qualidade)
        if c and (c.get("nota") is None or c["nota"] >= NOTA_MINIMA):
            guardar(sd, pd, c, pasta_job, normalizar)
            n += 1
            prog(f"✔ {pd['termo']}: {c.get('titulo') or c.get('id')}" + (f" · 🎯 {c['nota']}%" if c.get("nota") is not None else ""))
        else:
            sem_nada.append((pd, c))
    # 📣 reserva: MyInstants só pros EFEITOS (nunca música) que o Pixabay não resolveu
    memes = [pd for pd, _c in sem_nada if pd["tipo"] == "efeitos"]
    if memes and cam.get("memes", True) and pasta_memes:
        prog("📣 MyInstants (reserva): " + ", ".join(f"“{pd['termo']}”" for pd in memes))
        try:
            if rodar_memes is None:
                import myinstants_sons as MI
                rodar_memes = MI.rodar
            rodar_memes([pd["termo"] for pd in memes], pasta_memes, 4, prog)
        except Exception as exc:  # noqa: BLE001
            prog(f"⚠ MyInstants falhou: {str(exc)[:160]}")
    for pd, c_pix in sem_nada:
        pastas = [pasta_p] + ([pasta_memes] if pd["tipo"] == "efeitos" and cam.get("memes", True) and pasta_memes else [])
        c = escolher(pd, livres(pastas, pd["termo"], pd["tipo"]), ouvido, qualidade) or c_pix
        if c:  # mesmo abaixo da nota mínima: entra marcado ⚠ (melhor que nada — você troca a busca no painel)
            guardar(sd, pd, c, pasta_job, normalizar)
            n += 1
            prog(f"{'⚠' if c.get('aviso') else '✔'} {pd['termo']}: {c.get('titulo') or c.get('id')} ({c.get('fonte')})"
                 + (f" · 🎯 {c['nota']}% — {c['aviso']}" if c.get("aviso") else ""))
    if ouvido is not None:
        try:
            ouvido.salvar()
        except Exception:  # noqa: BLE001
            pass
    faltando = buscas_necessarias(sd)
    return {"novos": n, "faltando": faltando["efeitos"] + faltando["musica"]}


def trocar(sd: Dict[str, Any], chave: str) -> None:
    """🔁 esquece o áudio escolhido dessa busca (o próximo 🔊 escolhe outro / busca de novo)."""
    a = (sd.get("audios") or {}).pop(chave, None)
    if a:
        sd.setdefault("recusados", {}).setdefault(chave, []).append(a.get("id"))


# ------------------------------------------------------------------ 🎬 montagem
def para_montar(job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """O plano com só o que tem arquivo (ou None: sem sound design)."""
    sd = job.get("sound_design")
    if not isinstance(sd, dict) or not sd.get("blocos"):
        return None
    sd = estado(job)
    aud = sd.get("audios") or {}

    def arq(chave: str) -> str:
        a = (aud.get(chave) or {}).get("arquivo") or ""
        return a if a and os.path.isfile(a) else ""
    def climax(b: Dict[str, Any]) -> Optional[float]:  # 🎵 v84_403: o momento mais forte do bloco (o drop da música cai nele)
        ms = [m for m in sd.get("momentos") or [] if b["start"] <= float(m["t"]) < b["end"] and int(m.get("forca") or 1) >= 2]
        if not ms:
            return None
        m = max(ms, key=lambda m: (int(m.get("forca") or 1), float(m["t"])))
        return round(float(m["t"]) - float(b["start"]), 2)
    blocos = [{"start": b["start"], "end": b["end"], "emocao": b["emocao"],
               "ambiente": arq("efeitos:" + b["ambiente_en"]) if sd["camadas"]["ambiente"] and b.get("ambiente_en") else "",
               "musica": arq("musica:" + b["musica_en"]) if sd["camadas"]["musica"] and b.get("musica_en") else "",
               "climax": climax(b) if sd["camadas"]["musica"] else None,
               "pico_musica": (aud.get("musica:" + b["musica_en"]) or {}).get("pico_musica") if b.get("musica_en") else None}
              for b in sd["blocos"]]
    acentos = {k: dict(aud.get("efeitos:" + v) or {}) for k, v in ACENTOS_BUSCA.items() if arq("efeitos:" + v)}
    plano = {"blocos": blocos, "momentos": list(sd["momentos"]) if sd["camadas"]["acentos"] else [],
             "acentos": acentos, "mix": bool(sd["camadas"]["mix"])}
    if not any(b["ambiente"] or b["musica"] for b in blocos) and not (plano["momentos"] and acentos):
        return None
    return plano


def eventos_acentos(plano: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Os momentos-chave → eventos de som (no formato do dp_sons.mixar, com "arquivo"):
    força 1 = só um impacto sutil · 2 = reverse que termina no momento + impacto · 3 = riser + boom (o clímax)."""
    ac = plano.get("acentos") or {}
    ev: List[Dict[str, Any]] = []
    for m in plano.get("momentos") or []:
        t, f = float(m["t"]), int(m.get("forca") or 2)
        ante = ac.get("riser") if f == 3 else ac.get("reverse") if f == 2 else None
        if ante:  # a antecipação TERMINA no momento (o "suck back" antes do impacto)
            ev.append({"arquivo": ante["arquivo"], "inicio": max(0.0, t - float(ante.get("dur") or 1.5)),
                       "volume": NIVEIS["acento_fraco"] if f == 2 else NIVEIS["acento_forte"] * 0.8})
        imp = (ac.get("boom") or ac.get("impacto")) if f == 3 else ac.get("impacto") or ac.get("boom")
        if imp:  # o pico do impacto cai no instante
            ev.append({"arquivo": imp["arquivo"], "inicio": max(0.0, t - float(imp.get("pico") or 0)),
                       "volume": NIVEIS["acento_forte"] if f >= 2 else NIVEIS["acento_fraco"]})
    return ev


def _filtro_camadas(plano: Dict[str, Any], tem_trilha: bool, entradas: List[str]) -> List[str]:
    """Monta o filtro: cada bloco = [i] em loop → corte → fade → atraso → volume. Devolve as partes do filter_complex
    e enche `entradas` com os arquivos (a entrada 0 é a narração)."""
    partes: List[str] = []
    rot_amb, rot_mus = [], []
    for b in plano["blocos"]:
        dur_b = max(0.5, float(b["end"]) - float(b["start"]))
        atraso = int(round(float(b["start"]) * 1000))
        for tipo, rot, vol in (("ambiente", rot_amb, NIVEIS["ambiente"]), ("musica", rot_mus, NIVEIS["musica"])):
            if not b.get(tipo) or (tipo == "musica" and tem_trilha):
                continue
            entradas.append(b[tipo])
            k = len(entradas)
            fd = min(FADE, dur_b / 3)
            nome = f"{tipo[0]}{k}"
            ini, curva = 0.0, ""
            if tipo == "musica" and b.get("climax") is not None:  # 🎵 v84_403: o drop da música cai no clímax
                pico = b.get("pico_musica")
                if pico is None:
                    pico = pico_musica(b[tipo])
                if pico is not None:
                    ini = max(0.0, float(pico) - float(b["climax"]))  # (a entrada está em loop: começar depois do 0 é seguro)
                    c_ = float(b["climax"])
                    # antes do clímax a música fica mais baixa e sobe nele (segura uns segundos e volta ao normal)
                    curva = (f",volume='if(lt(t,{max(0.0, c_ - 0.3):.2f}),0.7,if(lt(t,{c_ + 4:.2f}),1.25,1.0))':eval=frame")
            partes.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,atrim={ini:.3f}:{ini + dur_b:.3f},asetpts=PTS-STARTPTS"
                          f"{curva},afade=t=in:d={fd:.2f},afade=t=out:st={max(0.0, dur_b - fd):.3f}:d={fd:.2f},"
                          f"volume={vol:.3f},adelay={atraso}|{atraso}[{nome}]")
            rot.append(f"[{nome}]")
    return partes, rot_amb, rot_mus


def _respiros(momentos: List[Dict[str, Any]]) -> str:
    """As camadas abaixam no meio segundo antes de cada momento-chave (o silêncio curto antes do impacto)."""
    janelas = [f"between(t,{max(0.0, float(m['t']) - 0.55):.2f},{float(m['t']):.2f})" for m in momentos
               if int(m.get("forca") or 2) >= 2]
    return f",volume={NIVEIS['respiro']}:enable='{'+'.join(janelas)}'" if janelas else ""


def aplicar(narracao: str, plano: Dict[str, Any], saida: str, tem_trilha: bool = False) -> str:
    """Narração (já com os efeitos) + ambiente + música por bloco, com ducking e os respiros → `saida` (wav)."""
    entradas: List[str] = []
    partes, rot_amb, rot_mus = _filtro_camadas(plano, tem_trilha, entradas)
    if not rot_amb and not rot_mus:
        return narracao
    resp = _respiros(plano.get("momentos") or [])
    partes.append("[0:a]aresample=48000,aformat=channel_layouts=stereo,asplit=2[nar][sc]")
    camas = []
    if rot_mus:
        partes.append("".join(rot_mus) + f"amix=inputs={len(rot_mus)}:normalize=0:dropout_transition=0{resp}[mus0]")
        # 🎚 ducking: a música abaixa quando a voz fala (sidechain) e volta nas pausas
        partes.append("[mus0][sc]sidechaincompress=threshold=0.03:ratio=6:attack=30:release=600:makeup=1[mus]")
        camas.append("[mus]")
    else:
        partes.append("[sc]anullsink")
    if rot_amb:
        partes.append("".join(rot_amb) + f"amix=inputs={len(rot_amb)}:normalize=0:dropout_transition=0{resp}[amb]")
        camas.append("[amb]")
    final = "alimiter=limit=0.95" if plano.get("mix", True) else "alimiter=limit=0.98"
    partes.append("[nar]" + "".join(camas) + f"amix=inputs={1 + len(camas)}:duration=first:normalize=0:dropout_transition=0,{final}[out]")
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", narracao]
    for e in entradas:
        args += ["-stream_loop", "-1", "-i", e]
    script = saida + ".filtro.txt"
    with open(script, "w", encoding="utf-8") as f:
        f.write(";\n".join(partes))
    cmd = args + ["-filter_complex_script", script, "-map", "[out]", "-c:a", "pcm_s16le", saida]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
    if r.returncode != 0 and "filter_complex_script" in r.stderr and ("nrecognized" in r.stderr or "not found" in r.stderr):
        k = cmd.index("-filter_complex_script")
        r = subprocess.run(cmd[:k] + ["-/filter_complex"] + cmd[k + 1:], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=3600)
    try:
        os.remove(script)
    except OSError:
        pass
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou no sound design: {r.stderr.strip()[-600:]}")
    return saida


def resumo(job: Dict[str, Any]) -> Dict[str, Any]:
    """Pro painel do Estúdio."""
    sd = estado(job)
    aud = sd.get("audios") or {}
    blocos = []
    for b in sd["blocos"]:
        a = aud.get("efeitos:" + b["ambiente_en"]) or {}
        m = aud.get("musica:" + b["musica_en"]) or {}
        info = lambda x: {k: x.get(k) for k in ("titulo", "fonte", "nota", "soa_como", "aviso", "pagina")}  # noqa: E731
        blocos.append(dict(b, ambiente_ok=bool(a.get("arquivo") and os.path.isfile(a["arquivo"])),
                           musica_ok=bool(m.get("arquivo") and os.path.isfile(m["arquivo"])),
                           ambiente_titulo=a.get("titulo", ""), musica_titulo=m.get("titulo", ""),
                           ambiente_info=info(a), musica_info=info(m)))
    acentos_ok = [k for k, v in ACENTOS_BUSCA.items() if (aud.get("efeitos:" + v) or {}).get("arquivo")]
    acentos = [{"nome": k, "termo": v, "chave": "efeitos:" + v,
                **{x: (aud.get("efeitos:" + v) or {}).get(x) for x in ("titulo", "fonte", "nota", "soa_como", "aviso")}}
               for k, v in ACENTOS_BUSCA.items() if (aud.get("efeitos:" + v) or {}).get("arquivo")]
    try:
        import audio_juiz
        juiz_st = audio_juiz.disponivel() or ""
    except Exception as exc:  # noqa: BLE001
        juiz_st = str(exc)[:120]
    return {"blocos": blocos, "momentos": sd["momentos"], "camadas": sd["camadas"], "duracao": duracao(job),
            "emocoes": {k: {"nome": v["nome"], "cor": v["cor"]} for k, v in EMOCOES.items()},
            "tipos_momento": TIPOS_MOMENTO, "acentos_ok": acentos_ok, "acentos": acentos, "juiz_falta": juiz_st, "faltando": buscas_necessarias(sd),
            "status": sd.get("status") or "", "erro": sd.get("erro") or "", "log": (sd.get("log") or [])[-12:],
            "max_momentos": max_momentos(duracao(job))}
