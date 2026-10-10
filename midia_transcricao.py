"""
Transcrição (com os tempos) dos VÍDEOS que a pessoa junta num projeto de
🛒 venda ou de 🕵️ modelo de vídeo — pra IA saber o que é dito em cada trecho
e decidir se toca um pedaço com o ÁUDIO ORIGINAL (a narração pausa) ou se
mostra o vídeo SEM SOM enquanto a narração continua.

A transcrição fica num arquivo ao lado do vídeo (<video>.transcricao.json),
feita em segundo plano (um vídeo por vez, o Whisper é pesado).
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from typing import Any, Dict, List, Optional, Tuple

_FILA = threading.Semaphore(1)
_RODANDO: set = set()
_TRAVA = threading.Lock()
EXT_VIDEO = (".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi")


def eh_video(caminho: Optional[str]) -> bool:
    return bool(caminho) and os.path.splitext(caminho)[1].lower() in EXT_VIDEO


def _json(caminho: str) -> str:
    return caminho + ".transcricao.json"


def ler(caminho: Optional[str]) -> Optional[Dict[str, Any]]:
    if not caminho:
        return None
    try:
        with open(_json(caminho), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if d.get("estado") == "transcrevendo" and caminho not in _RODANDO:
        d = dict(d, estado="interrompida")
    return d


def _gravar(caminho: str, d: Dict[str, Any]) -> None:
    tmp = _json(caminho) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, _json(caminho))


def _probe(caminho: str) -> Dict[str, Any]:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", caminho],
                           capture_output=True, text=True, timeout=60)
        d = json.loads(r.stdout or "{}")
        return {"duracao": float((d.get("format") or {}).get("duration") or 0),
                "tem_audio": any(s.get("codec_type") == "audio" for s in d.get("streams") or [])}
    except Exception:  # noqa: BLE001
        return {"duracao": 0.0, "tem_audio": True}


def transcrever(caminho: str, transcrever_fn=None) -> Dict[str, Any]:
    """Transcreve AGORA (bloqueia). Grava e devolve o resultado."""
    info = _probe(caminho)
    base = {"duracao": round(info["duracao"], 2), "tem_audio": info["tem_audio"]}
    if not info["tem_audio"]:
        d = dict(base, estado="pronta", sem_fala=True, segmentos=[])
        _gravar(caminho, d)
        return d
    _gravar(caminho, dict(base, estado="transcrevendo"))
    try:
        if transcrever_fn is None:
            from whisper_transcribe import TranscriptionError, transcribe_audio
        else:
            transcribe_audio, TranscriptionError = transcrever_fn, RuntimeError
        try:
            segs = transcribe_audio(caminho)
        except TranscriptionError:
            segs = []  # sem fala (só música/ruído)
        d = dict(base, estado="pronta", sem_fala=not segs,
                 segmentos=[{"ini": round(float(s["start"]), 2), "fim": round(float(s["end"]), 2), "texto": str(s["text"]).strip()}
                            for s in segs if str(s.get("text") or "").strip()])
    except Exception as exc:  # noqa: BLE001
        d = dict(base, estado="erro", erro=str(exc)[:300])
    _gravar(caminho, d)
    return d


def agendar(caminho: Optional[str]) -> bool:
    """Transcreve em segundo plano se ainda não tem (ou se foi interrompida)."""
    if not eh_video(caminho) or not os.path.isfile(caminho):
        return False
    atual = ler(caminho)
    if atual and atual.get("estado") in ("pronta", "transcrevendo"):
        return False
    with _TRAVA:
        if caminho in _RODANDO:
            return False
        _RODANDO.add(caminho)

    def rodar():
        try:
            with _FILA:
                transcrever(caminho)
        finally:
            with _TRAVA:
                _RODANDO.discard(caminho)
    threading.Thread(target=rodar, daemon=True).start()
    return True


def tempo(s: float) -> str:
    s = max(0, int(round(float(s or 0))))
    return f"{s // 60}:{s % 60:02d}"


def resumo(caminho: Optional[str]) -> Optional[Dict[str, Any]]:
    """Pra página: estado, duração e o texto com os tempos."""
    if not eh_video(caminho):
        return None
    d = ler(caminho)
    if not d:
        return {"estado": "na fila"}
    return {"estado": d.get("estado"), "duracao": d.get("duracao"), "sem_fala": d.get("sem_fala"), "erro": d.get("erro"),
            "texto": "\n".join(f"[{tempo(x['ini'])}–{tempo(x['fim'])}] {x['texto']}" for x in d.get("segmentos") or [])}


def para_prompt(caminho: Optional[str], limite: int = 3500) -> str:
    """Linha(s) que vão no prompt da IA junto com a descrição do vídeo."""
    if not eh_video(caminho):
        return ""
    d = ler(caminho)
    if not d or d.get("estado") != "pronta":
        dur = (d or {}).get("duracao") or _probe(caminho)["duracao"]
        return f" (vídeo de {tempo(dur)}; transcrição ainda não pronta)"
    dur = tempo(d.get("duracao") or 0)
    if d.get("sem_fala") or not d.get("segmentos"):
        return f" (vídeo de {dur}, sem fala — só imagem/som ambiente)"
    linhas: List[str] = []
    total = 0
    for x in d["segmentos"]:
        ln = f"      [{tempo(x['ini'])}–{tempo(x['fim'])}] {x['texto']}"
        total += len(ln)
        if total > limite:
            linhas.append("      […]")
            break
        linhas.append(ln)
    return f" (vídeo de {dur}). O que é dito nele:\n" + "\n".join(linhas)


def instrucao_roteiro(ex: str = "M3") -> str:
    return (
        "VÍDEOS COM FALA/SOM: você decide, pra cada vídeo, como ele entra. (a) Tocar um pedaço com o ÁUDIO ORIGINAL (a "
        "narração para e o vídeo fala sozinho — bom pra depoimento, demonstração com som, reação, trecho de notícia): "
        f"escreva a marca com o trecho e a palavra áudio, ex.: [{ex} 0:12-0:25 áudio], e NÃO narre por cima desse pedaço "
        "(a frase seguinte continua depois dele). (b) Mostrar o vídeo SEM o som dele enquanto a narração continua: "
        f"[{ex} 0:12-0:25]. Os tempos são do próprio vídeo (pela transcrição). Use o áudio original só quando ele "
        "acrescenta algo que a narração não daria.")


INSTRUCAO_EDITOR = (
    "VÍDEOS do projeto — dois jeitos, você escolhe (se o roteiro marcou \"áudio\", use o (b) nesse ponto): "
    "(a) SEM o som dele, sob a narração: no segmento, `\"query\": \"<ID>@<início>-<fim>\"` com os segundos do PRÓPRIO "
    "vídeo (ex.: `\"M3@12-25\"`; sem @ usa do começo). (b) Com o ÁUDIO ORIGINAL (a narração pausa e o vídeo final fica "
    "mais longo): em \"cutaway_suggestions\", "
    "`{\"insertion_point\": <segundo da narração onde entra>, \"description\": \"<ID> — o que é\", \"audio_mode\": \"pause\", "
    "\"midia\": \"<ID>\", \"inicio\": 12.0, \"fim\": 25.0}`.")

_T = r"(\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)"
MARCA_PADRAO = r"\[\s*([MIT]\d+)(?:\s+" + _T + r"\s*[-–]\s*" + _T + r")?(?:\s+(áudio|audio|som))?\s*\]"
MARCA = __import__("re").compile(MARCA_PADRAO, __import__("re").IGNORECASE)


def segundos(v: Any) -> Optional[float]:
    if v in (None, ""):
        return None
    v = str(v).strip()
    try:
        if ":" in v:
            m, s = v.split(":", 1)
            return int(m) * 60 + float(s)
        return float(v)
    except ValueError:
        return None


def marcas(texto: str) -> List[Dict[str, Any]]:
    out = []
    for m in MARCA.finditer(texto or ""):
        out.append({"id": m.group(1).upper(), "inicio": segundos(m.group(2)), "fim": segundos(m.group(3)),
                    "audio": bool(m.group(4)), "pos": m.end()})
    return out


def tirar_marcas(texto: str) -> str:
    import re
    t = re.sub(r"^[ \t]*" + MARCA_PADRAO + r"[ \t]*\n", "", texto or "", flags=re.IGNORECASE | re.MULTILINE)
    t = MARCA.sub("", t)
    import chamadas
    t = chamadas.tirar_marcas_de_cena(t)[0]
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"[ \t]*\n[ \t]*", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def momentos_do_roteiro(rot: str, ids: set, momentos_ia: Any) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Cada marca do roteiro vira um "momento" (na ordem), com o trecho de fala que vem
    depois dela e, nos vídeos, o pedaço (início-fim) e se é com o áudio original."""
    import re
    ia = {}
    for mo in momentos_ia or []:
        if isinstance(mo, dict) and str(mo.get("midia") or "").upper() not in ia:
            ia[str(mo.get("midia") or "").upper()] = mo
    out, usados, sem = [], set(), []
    for mk in marcas(rot):
        if mk["id"] not in ids:
            if mk["id"] not in sem:
                sem.append(mk["id"])
            continue
        resto = MARCA.sub(" ", rot[mk["pos"]:]).strip().split("\n")[0].strip()
        frase = re.split(r"(?<=[.!?])\s", resto)[0][:200]
        dado = ia.get(mk["id"]) or {}
        mo = {"midia": mk["id"], "trecho": (str(dado.get("trecho") or "").strip()[:400] if mk["id"] not in usados and dado.get("trecho") else frase),
              "texto_na_tela": str(dado.get("texto_na_tela") or "").strip()[:120]}
        for k in ("inicio", "fim"):
            if mk[k] is not None:
                mo[k] = mk[k]
        if mk["audio"]:
            mo["audio"] = True
        usados.add(mk["id"])
        out.append(mo)
    for mid, dado in ia.items():
        if mid in ids and mid not in usados:
            out.append({"midia": mid, "trecho": str(dado.get("trecho") or "").strip()[:400],
                        "texto_na_tela": str(dado.get("texto_na_tela") or "").strip()[:120]})
    return out, sem


def uso_sugerido(mo: Dict[str, Any]) -> str:
    if mo.get("inicio") is None and not mo.get("audio"):
        return ""
    pedaco = f"{tempo(mo.get('inicio') or 0)}-{tempo(mo['fim'])}" if mo.get("fim") is not None else f"a partir de {tempo(mo.get('inicio') or 0)}"
    return f" [usar o pedaço {pedaco}{' COM o áudio original (corte)' if mo.get('audio') else ' sem o som, sob a narração'}]"
