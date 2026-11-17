"""
🎚 v84_404 — o "acabamento" da voz gerada (Chatterbox Turbo e Chatterbox pt-BR, com ou sem o 🎭 expressivo).

Tudo DESLIGADO por padrão. Três coisas, cada uma liga separada:

1. 🎬 TAKES: cada pedaço (as 2–3 frases que o motor gera de uma vez) sai em 2 ou 3 versões; o Whisper ouve cada uma e
   fica a que falou o texto mais certinho (sem engolir, repetir ou trocar palavra, sem sopro/zumbido, sem esticar).
2. ✂ SILÊNCIO MORTO: os buracos compridos entre as frases encolhem — MAS as pausas de propósito ficam:
   "...", "…", " — ", [pausa]/[pause] no texto seguram até 1,2 s; as [pausa] do 🎭 expressivo são coladas DEPOIS
   (fora daqui), então nunca são cortadas.
3. 🎛 EQ de voz: presets de equalização (limpa, crispy, quente, rádio). Na hora de gerar (vale pro arquivo final) ou
   depois, como FAIXAS EXTRAS (uma por preset) sem mexer na original.
"""
from __future__ import annotations

import difflib
import os
import re
import subprocess
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

TAKES_MAX = 3
MOTORES = ("chatterbox", "chatterbox_turbo")  # os que ganham takes + corte de silêncio

# ------------------------------------------------------------------ 🎛 EQ
EQ_PRESETS: Dict[str, Dict[str, str]] = {
    "limpa": {"nome": "🧼 Voz limpa", "dica": "tira o grave embolado e o chiado do S, dá presença — o mais neutro",
              "filtro": "highpass=f=80,equalizer=f=250:t=q:w=1.0:g=-2.5,equalizer=f=3200:t=q:w=1.2:g=2.5,"
                        "equalizer=f=9000:t=q:w=1.0:g=1.5,deesser=i=0.4"},
    "crispy": {"nome": "✨ Crispy (YouTube)", "dica": "mais brilho e ar, corta mais grave — a voz 'na cara' dos shorts",
               "filtro": "highpass=f=100,equalizer=f=300:t=q:w=1.0:g=-3.5,equalizer=f=4500:t=q:w=1.0:g=4,"
                         "highshelf=f=10000:g=3,deesser=i=0.5,acompressor=threshold=0.125:ratio=3:attack=5:release=60"},
    "quente": {"nome": "🔥 Quente / grave", "dica": "corpo no grave, agudo suave — narração de documentário, suspense",
               "filtro": "highpass=f=60,lowshelf=f=150:g=2.5,equalizer=f=400:t=q:w=1.0:g=-1.5,equalizer=f=3000:t=q:w=1.0:g=1,"
                         "lowpass=f=13000,deesser=i=0.3"},
    "radio": {"nome": "📻 Rádio / podcast", "dica": "comprimida e presente, volume constante",
              "filtro": "highpass=f=90,equalizer=f=200:t=q:w=1.0:g=1.5,equalizer=f=2800:t=q:w=1.0:g=3,deesser=i=0.4,"
                        "acompressor=threshold=0.08:ratio=4:attack=3:release=80:makeup=2"},
}


def opcoes_eq() -> List[Dict[str, str]]:
    return [{"id": k, "nome": v["nome"], "dica": v["dica"]} for k, v in EQ_PRESETS.items()]


def aplicar_eq(entrada: str, saida: str, preset: str) -> str:
    """Grava `saida` com o preset (o limitador no fim evita estourar depois do ganho). Não mexe na entrada."""
    if preset not in EQ_PRESETS:
        raise ValueError(f"EQ desconhecido: {preset!r}")
    tmp = saida + ".eq.wav" if os.path.abspath(saida) == os.path.abspath(entrada) else saida
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", entrada, "-af", EQ_PRESETS[preset]["filtro"] + ",alimiter=limit=0.95",
                        tmp], capture_output=True, timeout=900)
    if r.returncode != 0 or not os.path.isfile(tmp):
        raise RuntimeError("ffmpeg não conseguiu aplicar o EQ: " + (r.stderr or b"").decode("utf-8", "replace")[-300:])
    if tmp != saida:
        os.replace(tmp, saida)
    return saida


def caminho_faixa(arquivo: str, preset: str) -> str:
    raiz, ext = os.path.splitext(arquivo)
    return f"{raiz}_eq_{preset}{ext or '.wav'}"


# ------------------------------------------------------------------ config
PADRAO = {"takes": 1, "cortar_silencios": False, "eq": ""}


def normalizar(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    c = dict(PADRAO)
    c.update({k: v for k, v in (cfg or {}).items() if k in PADRAO})
    try:
        c["takes"] = max(1, min(TAKES_MAX, int(c["takes"] or 1)))
    except (TypeError, ValueError):
        c["takes"] = 1
    c["cortar_silencios"] = bool(c["cortar_silencios"]) and str(c["cortar_silencios"]).lower() not in ("0", "false", "off", "")
    c["eq"] = str(c["eq"] or "") if str(c["eq"] or "") in EQ_PRESETS else ""
    return c


# ------------------------------------------------------------------ áudio
def _amostras(caminho: str, taxa: int = 16000):
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", caminho, "-ar", str(taxa), "-ac", "1", "-f", "f32le", "-"],
                       capture_output=True, timeout=300)
    return np.frombuffer(r.stdout, dtype=np.float32)


def silencios(caminho: str, abaixo_do_pico_db: float = 40.0, min_s: float = 0.2) -> Tuple[List[Tuple[float, float]], float]:
    """[(início, fim)] dos trechos em silêncio (abaixo do pico - 40 dB, ≥ 0,2 s) e a duração total."""
    import numpy as np
    x = _amostras(caminho)
    h = 160  # 10 ms
    n = len(x) // h
    if n < 10:
        return [], len(x) / 16000.0
    e = np.sqrt(np.mean(x[:n * h].reshape(n, h) ** 2, axis=1))
    db = 20 * np.log10(e + 1e-9)
    limiar = max(float(db.max()) - abaixo_do_pico_db, -60.0)
    q = db < limiar
    out, i = [], 0
    while i < n:
        if q[i]:
            j = i
            while j < n and q[j]:
                j += 1
            if (j - i) * 0.01 >= min_s:
                out.append((round(i * 0.01, 3), round(j * 0.01, 3)))
            i = j
        else:
            i += 1
    return out, n * 0.01


_PAUSA_INTENCIONAL = re.compile(r"\.\.\.|…|\s[—–-]\s|\[(?:pausa|pause)[^\]]*\]", re.I)


def pausas_intencionais(texto: str) -> int:
    return len(_PAUSA_INTENCIONAL.findall(texto or ""))


def plano_de_cortes(gaps: List[Tuple[float, float]], dur: float, n_intencionais: int, max_pausa: float = 0.55,
                    alvo: float = 0.4, max_intencional: float = 1.2, ponta: float = 0.15) -> List[Tuple[float, float]]:
    """Que pedaços tirar: pontas viram `ponta` s; as N maiores pausas (N = pausas de propósito no texto) seguram até
    `max_intencional`; as outras, se passarem de `max_pausa`, viram `alvo`. Sempre tira o MEIO do silêncio."""
    cortes = []
    meio = []
    for a, b in gaps:
        if a <= 0.011:
            if b - a > ponta:
                cortes.append((0.0, b - ponta))
        elif b >= dur - 0.011:
            if b - a > ponta:
                cortes.append((a + ponta, dur))
        else:
            meio.append((a, b))
    protegidas = set(sorted(meio, key=lambda g: -(g[1] - g[0]))[:max(0, n_intencionais)])
    for a, b in meio:
        d = b - a
        teto, novo = (max_intencional, max_intencional) if (a, b) in protegidas else (max_pausa, alvo)
        if d > teto:
            sobra = d - novo
            c = (a + b) / 2
            cortes.append((round(c - sobra / 2, 3), round(c + sobra / 2, 3)))
    return sorted(cortes)


def cortar_silencios(caminho: str, texto: str, on_log: Callable[[str], None] = lambda _m: None) -> float:
    """✂ encolhe os silêncios mortos do .wav (no lugar). Devolve quantos segundos saíram."""
    try:
        gaps, dur = silencios(caminho)
    except Exception:  # noqa: BLE001 — sem numpy/ffmpeg: deixa como está
        return 0.0
    cortes = [(a, b) for a, b in plano_de_cortes(gaps, dur, pausas_intencionais(texto)) if b - a >= 0.03]
    if not cortes:
        return 0.0
    expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in cortes)
    tmp = caminho + ".sil.wav"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", caminho, "-af", f"aselect='not({expr})',asetpts=N/SR/TB", tmp],
                       capture_output=True, timeout=300)
    if r.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) < 1000:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return 0.0
    os.replace(tmp, caminho)
    tirou = round(sum(b - a for a, b in cortes), 2)
    on_log(f"✂ {tirou:.1f} s de silêncio morto a menos")
    return tirou


# ------------------------------------------------------------------ 🎬 takes
def _palavras(t: str) -> List[str]:
    t = re.sub(r"\[[^\[\]]{1,40}\]", " ", t or "")
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+", t)


def nota_take(texto: str, ouvido: List[str], dur: float, limite: float, lixo_s: float = 0.0) -> float:
    """0–100: o quanto o take falou o texto (ordem e palavras), menos repetição, lixo e esticada."""
    ref = _palavras(texto)
    hyp = [w for w in (_palavras(" ".join(ouvido))) if w]
    if not ref:
        return 100.0
    casou = sum(b.size for b in difflib.SequenceMatcher(None, ref, hyp, autojunk=False).get_matching_blocks())
    sobra = max(0, len(hyp) - casou)  # palavra a mais (trocada, inventada, repetida)
    rep = sum(1 for a, b in zip(hyp, hyp[1:]) if a == b and len(a) > 2) - sum(1 for a, b in zip(ref, ref[1:]) if a == b)
    nota = 100.0 * casou / len(ref) - 4.0 * sobra - 6.0 * max(0, rep) - 12.0 * lixo_s - 8.0 * max(0.0, dur - limite)
    return round(max(0.0, nota), 2)


def escolher_take(texto: str, caminhos: List[str], ouvir: Callable[[str], List[str]], duracao: Callable[[str], float],
                  limite: float, lixo: Callable[[str], float] = lambda _c: 0.0) -> Tuple[int, List[float]]:
    """O índice do melhor take e as notas de todos (empate: o primeiro)."""
    notas = []
    for c in caminhos:
        try:
            notas.append(nota_take(texto, ouvir(c), duracao(c) or 0.0, limite, lixo(c)))
        except Exception:  # noqa: BLE001 — take que não deu pra ouvir conta como ruim
            notas.append(0.0)
    melhor = max(range(len(notas)), key=lambda i: (notas[i], -i)) if notas else 0
    return melhor, notas
