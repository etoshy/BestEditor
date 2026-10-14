"""
legenda_texto.py — ✍️ legenda com o TEXTO DO ROTEIRO (v84_94)
==============================================================

Os motores de voz (Kokoro, Piper, XTTS, Chatterbox…) devolvem só o áudio: não dizem em que instante cada palavra é
falada. Por isso o site ainda passa o áudio pelo Whisper — mas agora só pra MEDIR O TEMPO de cada palavra. O texto
da legenda é o do roteiro que foi pro TTS (nomes, acentos, números e pontuação do jeito que você escreveu), em vez
do que o Whisper "achou que ouviu".

  com_texto(segmentos_do_whisper, texto)  → segmentos com as palavras do roteiro nos tempos do áudio
  estimar(texto, duracao)                  → sem Whisper: tempos estimados pelo tamanho das palavras e pausas

Como casa: as palavras dos dois lados são comparadas sem acento/maiúscula (difflib), e depois, dentro de cada
buraco entre palavras casadas, por semelhança ("Ezequiel" × "e zequiel"); o que sobra (um número que o TTS leu por
extenso, uma palavra que o Whisper engoliu) recebe o tempo do buraco, dividido pelo tamanho das palavras.
Se quase nada casar (o áudio não é desse texto), devolve a transcrição como veio.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

_TAG = re.compile(r"\[[^\[\]\n]{1,60}\]")  # [laugh], [voz_2], [[INSCREVA]] (já sem o marcador)
_FIM_FRASE = re.compile(r"[.!?…]+[\"'”»)]*$")
MIN_CASADAS = 0.35


def _norm(s: str) -> List[str]:
    s = unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9]+", s)


def texto_para_legenda(texto: str) -> str:
    """O texto que vai pra legenda: sem marcadores de chamada, tags de voz/emoção e espaços sobrando."""
    try:
        import chamadas
        texto = chamadas.remover_marcadores(texto or "")
    except Exception:  # noqa: BLE001
        pass
    texto = _TAG.sub(" ", texto or "")
    return re.sub(r"\s+", " ", texto).strip()


def _palavras_do_texto(texto: str) -> List[str]:
    """Palavras de exibição (com a pontuação grudada). Pontuação solta ("—", "…") gruda na anterior."""
    out: List[str] = []
    for tk in texto.split():
        if _norm(tk) or not out:
            out.append(tk)
        else:
            out[-1] = out[-1] + " " + tk if tk in ("—", "–", "-") else out[-1] + tk
    return [w for w in out if _norm(w)]


def _achatar(segmentos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ws = []
    for sg in segmentos or []:
        for w in sg.get("words") or []:
            if str(w.get("word", "")).strip():
                ws.append({"word": str(w["word"]).strip(), "start": float(w["start"]), "end": float(w["end"])})
    return ws


def _segmentar(palavras: List[Dict[str, Any]], max_palavras: int = 40) -> List[Dict[str, Any]]:
    """Palavras → segmentos (frase a frase), no formato do Whisper."""
    segs: List[Dict[str, Any]] = []
    atual: List[Dict[str, Any]] = []
    for w in palavras:
        atual.append(w)
        if _FIM_FRASE.search(w["word"]) or len(atual) >= max_palavras:
            segs.append(atual)
            atual = []
    if atual:
        segs.append(atual)
    return [{"start": s[0]["start"], "end": s[-1]["end"], "text": " ".join(w["word"] for w in s), "words": s} for s in segs]


def _distribuir(palavras: List[str], ini: float, fim: float) -> List[Tuple[float, float]]:
    """Divide [ini, fim] entre as palavras, pelo tamanho de cada uma."""
    if not palavras:
        return []
    fim = max(fim, ini + 0.12 * len(palavras))
    pesos = [max(1, len("".join(_norm(p)))) + 1 for p in palavras]
    tot = float(sum(pesos))
    out, t = [], ini
    for p in pesos:
        d = (fim - ini) * p / tot
        out.append((round(t, 3), round(t + d * 0.92, 3)))
        t += d
    return out


def com_texto(segmentos: List[Dict[str, Any]], texto: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Troca as palavras do Whisper pelas do roteiro, mantendo os tempos do áudio.
    Devolve (segmentos, info) — info = {"casadas": %, "usou_texto": bool}."""
    ditas = _achatar(segmentos)
    texto = texto_para_legenda(texto)
    exib = _palavras_do_texto(texto)
    if not ditas or not exib:
        return segmentos, {"casadas": 0, "usou_texto": False}
    # tokens normalizados dos dois lados (uma palavra pode virar 2 tokens: "d'água", "covid-19")
    a_tok, a_dono = [], []
    for i, w in enumerate(exib):
        for tk in _norm(w):
            a_tok.append(tk)
            a_dono.append(i)
    b_tok, b_dono = [], []
    for j, w in enumerate(ditas):
        for tk in _norm(w["word"]):
            b_tok.append(tk)
            b_dono.append(j)
    par: Dict[int, int] = {}  # token do roteiro -> token dito
    for a, b, n in difflib.SequenceMatcher(None, a_tok, b_tok, autojunk=False).get_matching_blocks():
        for k in range(n):
            par[a + k] = b + k
    # 2ª passada: nos buracos entre casados, casa por semelhança e na ordem ("ezequiel" × "zequiel")
    limites = [(-1, -1)] + sorted(par.items()) + [(len(a_tok), len(b_tok))]
    for (a0, b0), (a1, b1) in zip(limites, limites[1:]):
        bj = b0 + 1
        for ai in range(a0 + 1, a1):
            melhor, onde = 0.0, None
            for bk in range(bj, min(b1, bj + 3)):
                r = difflib.SequenceMatcher(None, a_tok[ai], b_tok[bk]).ratio()
                if r > melhor:
                    melhor, onde = r, bk
            if onde is not None and melhor >= 0.6:
                par[ai] = onde
                bj = onde + 1
    casa = {ai: b_dono[bk] for ai, bk in par.items()}  # token do roteiro -> palavra dita
    casadas = len(casa) / max(1, len(a_tok))
    if casadas < MIN_CASADAS:
        return segmentos, {"casadas": round(100 * casadas), "usou_texto": False}
    # tempos de cada palavra do roteiro
    tempos: List[Optional[Tuple[float, float]]] = [None] * len(exib)
    por_palavra: Dict[int, List[int]] = {}
    for ai, j in casa.items():
        por_palavra.setdefault(a_dono[ai], []).append(j)
    faixa: List[Optional[Tuple[int, int]]] = [None] * len(exib)  # palavras ditas que cada uma usou
    for i, js in por_palavra.items():
        tempos[i] = (ditas[min(js)]["start"], ditas[max(js)]["end"])
        faixa[i] = (min(js), max(js))
    # garante ordem crescente (um casamento fora de ordem vira buraco)
    ultimo = -1.0
    for i, tp in enumerate(tempos):
        if tp is not None:
            if tp[0] < ultimo - 0.01:
                tempos[i] = faixa[i] = None
            else:
                ultimo = tp[1]
    # buracos: dividem o tempo entre a palavra anterior e a próxima
    total = ditas[-1]["end"]
    i = 0
    while i < len(exib):
        if tempos[i] is not None:
            i += 1
            continue
        k = i
        while k < len(exib) and tempos[k] is None:
            k += 1
        ini = tempos[i - 1][1] if i > 0 else max(0.0, (tempos[k][0] if k < len(exib) else total) - 0.35 * (k - i))
        fim = tempos[k][0] if k < len(exib) else total
        # as palavras ditas no buraco (ex.: "mil novecentos e quarenta e dois" no lugar de "1942") dão o tempo exato
        j0 = (faixa[i - 1][1] + 1) if i > 0 and faixa[i - 1] else (0 if i == 0 else None)
        j1 = faixa[k][0] if k < len(exib) and faixa[k] else (len(ditas) if k == len(exib) else None)
        if j0 is not None and j1 is not None and j1 > j0:
            ini, fim = ditas[j0]["start"], ditas[j1 - 1]["end"]
        if fim - ini < 0.1 * (k - i):  # sem espaço: rouba um pouco da vizinha
            fim = ini + 0.1 * (k - i)
        for n, tp in enumerate(_distribuir(exib[i:k], ini, fim)):
            tempos[i + n] = tp
        i = k
    palavras = [{"word": w, "start": float(tp[0]), "end": float(max(tp[1], tp[0] + 0.05))} for w, tp in zip(exib, tempos)]
    return _segmentar(palavras), {"casadas": round(100 * casadas), "usou_texto": True}


def estimar(texto: str, duracao: float, inicio: float = 0.15) -> List[Dict[str, Any]]:
    """Sem Whisper: tempos pelo tamanho das palavras, com pausa maior depois de vírgula e de ponto."""
    exib = _palavras_do_texto(texto_para_legenda(texto))
    if not exib or duracao <= 0:
        return []
    pesos = []
    for w in exib:
        p = len("".join(_norm(w))) + 1.5
        if re.search(r"[,;:]$", w):
            p += 3
        elif _FIM_FRASE.search(w):
            p += 6
        pesos.append(p)
    util = max(0.5, duracao - inicio - 0.2)
    tot = sum(pesos)
    t, palavras = inicio, []
    for w, p in zip(exib, pesos):
        d = util * p / tot
        fala = d * (1 - (0.35 if _FIM_FRASE.search(w) else 0.18 if re.search(r"[,;:]$", w) else 0.08))
        palavras.append({"word": w, "start": round(t, 3), "end": round(t + fala, 3)})
        t += d
    return _segmentar(palavras)
