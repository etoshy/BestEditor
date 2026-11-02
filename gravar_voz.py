"""🎤 v84_325: a SUA voz num curto (canal de voz própria) — grava aos poucos, por parte do roteiro (ou tudo de uma vez),
com takes, editor de forma de onda (static/editor_audio.js) e realce opcional; depois junta as partes escolhidas num
áudio só, que segue o caminho normal (Whisper tira pausas/repetições e alinha ao roteiro → câmera → editor → MP4).

Arquivos: curtos/<pid>/minha_voz/<parte>_<take>.wav (+ _realce.wav) e minha_voz/estado.json
  {"partes": {"B1": {"ativo": "t3", "takes": [{"id", "arquivo", "dur", "realce": bool, "usar_realce": bool, "quando"}]}}}
A parte "TUDO" é uma gravação do roteiro inteiro (se tiver um take ativo, ela vale no lugar das partes).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import curtos as CT

TUDO = "TUDO"
_TRAVA = threading.Lock()
PAUSA_ENTRE_PARTES_S = 0.25


# ------------------------------------------------------------------ 🎙 sessões AVULSAS (texto livre, sem curto) — v84_325
PREFIXO_AVULSA = "av_"


def avulsa(pid: str) -> bool:
    return str(pid or "").startswith(PREFIXO_AVULSA)


def raiz_avulsas(base: str) -> str:
    return os.environ.get("GRAVAR_VOZ_DIR") or os.path.join(base, "gravar_voz")


def _sessao_cam(base: str, sid: str) -> str:
    return os.path.join(raiz_avulsas(base), _valida(sid), "sessao.json")


def separar_texto(texto: str, modo: str = "linha") -> List[str]:
    """O texto colado em partes: uma por linha (linhas vazias saem) ou uma por frase (. ! ? …)."""
    t = str(texto or "").replace("\r", "")
    if modo == "frase":
        t = " ".join(t.split())
        pedacos = re.split(r"(?<=[.!?…])\s+(?=[^\s])", t)
    elif modo == "paragrafo":
        pedacos = re.split(r"\n\s*\n", t)
    else:
        pedacos = t.split("\n")
    return [" ".join(x.split()) for x in pedacos if x.strip()][:300]


def criar_avulsa(base: str, titulo: str, texto: str, modo: str = "linha") -> Dict[str, Any]:
    falas = separar_texto(texto, modo)
    if not falas:
        raise CT.CurtoErro("Cole o texto que você vai ler.")
    sid = PREFIXO_AVULSA + uuid.uuid4().hex[:10]
    s = {"id": sid, "titulo": " ".join(str(titulo or "").split())[:120] or " ".join(falas[0].split()[:8]), "modo": modo,
         "texto": str(texto or "")[:100000], "partes": [{"id": f"P{k}", "texto": x} for k, x in enumerate(falas, 1)], "criado": time.time()}
    os.makedirs(os.path.dirname(_sessao_cam(base, sid)), exist_ok=True)
    _gravar_json(_sessao_cam(base, sid), s)
    return s


def sessao(base: str, sid: str) -> Dict[str, Any]:
    try:
        with open(_sessao_cam(base, sid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        raise CT.CurtoErro("Sessão não encontrada.")


def trocar_texto(base: str, sid: str, texto: str, modo: str = "linha") -> Dict[str, Any]:
    """✏ texto novo: as partes são refeitas na ordem (a parte P3 continua P3, com os takes que já tinha)."""
    s = sessao(base, sid)
    falas = separar_texto(texto, modo)
    if not falas:
        raise CT.CurtoErro("O texto ficou vazio.")
    s.update(texto=str(texto or "")[:100000], modo=modo, partes=[{"id": f"P{k}", "texto": x} for k, x in enumerate(falas, 1)])
    _gravar_json(_sessao_cam(base, sid), s)
    return s


def listar_avulsas(base: str) -> List[Dict[str, Any]]:
    out = []
    try:
        nomes = os.listdir(raiz_avulsas(base))
    except OSError:
        return []
    for n in nomes:
        if avulsa(n):
            try:
                s = sessao(base, n)
                out.append({"id": n, "titulo": s.get("titulo") or n, "partes": len(s.get("partes") or []), "criado": s.get("criado") or 0,
                            "final": os.path.isfile(os.path.join(raiz_avulsas(base), n, "minha_voz", "final.wav"))})
            except CT.CurtoErro:
                continue
    return sorted(out, key=lambda x: -x["criado"])


def apagar_avulsa(base: str, sid: str) -> None:
    import shutil
    sessao(base, sid)
    shutil.rmtree(os.path.join(raiz_avulsas(base), _valida(sid)), ignore_errors=True)


def _gravar_json(cam: str, d: Dict[str, Any]) -> None:
    tmp = cam + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, cam)


def pasta(base: str, pid: str) -> str:
    raiz = os.path.join(raiz_avulsas(base), _valida(pid)) if avulsa(pid) else CT.pasta(base, pid)
    d = os.path.join(raiz, "minha_voz")
    os.makedirs(d, exist_ok=True)
    return d


def partes_de(base: str, pid: str) -> List[Dict[str, Any]]:
    """As partes pra ler: as do texto colado (avulsa) ou as do roteiro do curto."""
    if avulsa(pid):
        return [{"id": x["id"], "texto": x["texto"], "traducao": "", "funcao": ""} for x in sessao(base, pid).get("partes") or []]
    return partes(CT.carregar(base, pid))


def _estado_cam(base: str, pid: str) -> str:
    return os.path.join(pasta(base, pid), "estado.json")


def estado(base: str, pid: str) -> Dict[str, Any]:
    try:
        with open(_estado_cam(base, pid), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {"partes": {}}
    except (OSError, ValueError):
        return {"partes": {}}


def _salvar(base: str, pid: str, d: Dict[str, Any]) -> None:
    _gravar_json(_estado_cam(base, pid), d)


def _valida(x: str) -> str:
    x = str(x or "")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,40}", x):
        raise CT.CurtoErro("Parte/take inválido.")
    return x


def partes(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    """O roteiro em partes pra ler: o bloco narrado + a tradução do lado."""
    out = []
    idioma = (p.get("roteiro") or {}).get("idioma") or "en"
    for k, b in enumerate((p.get("roteiro") or {}).get("blocos") or [], 1):
        fala = CT.sem_tags(b.get("fala") or "")
        outra = CT.sem_tags((b.get("fala_pt") if idioma == "en" else b.get("fala_en")) or "")
        out.append({"id": str(b.get("id") or f"B{k}"), "texto": fala, "traducao": outra if outra and outra != fala else "", "funcao": b.get("funcao") or ""})
    return out


def _dur(cam: str) -> float:
    try:
        return round(float(CT.duracao_audio(cam) or 0), 2)
    except Exception:  # noqa: BLE001
        return 0.0


def adicionar_take(base: str, pid: str, parte: str, arquivo_enviado: str) -> Dict[str, Any]:
    """⏺ um take novo da parte (webm/ogg/wav → wav 48k mono). Vira o take ativo."""
    parte = _valida(parte)
    tid = "t" + uuid.uuid4().hex[:8]
    destino = os.path.join(pasta(base, pid), f"{parte}_{tid}.wav")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", arquivo_enviado, "-ac", "1", "-ar", "48000", destino],
                       capture_output=True, timeout=300)
    if r.returncode != 0 or not os.path.isfile(destino):
        raise CT.CurtoErro("Não consegui ler esse áudio.")
    dur = _dur(destino)
    if dur < 0.2:
        os.remove(destino)
        raise CT.CurtoErro("A gravação ficou vazia (curta demais) — grave de novo.")
    with _TRAVA:
        d = estado(base, pid)
        pt = d.setdefault("partes", {}).setdefault(parte, {"ativo": None, "takes": []})
        pt["takes"].append({"id": tid, "arquivo": os.path.basename(destino), "dur": dur, "realce": False, "usar_realce": False,
                            "quando": time.time()})
        pt["ativo"] = tid
        _salvar(base, pid, d)
    return {"takeId": tid, "duracaoSegundos": dur, "usar": True}


def _take(d: Dict[str, Any], parte: str, tid: str) -> Dict[str, Any]:
    t = next((x for x in ((d.get("partes") or {}).get(parte) or {}).get("takes") or [] if x["id"] == tid), None)
    if not t:
        raise CT.CurtoErro("Take não encontrado.")
    return t


def caminho_take(base: str, pid: str, parte: str, tid: str, realce: Optional[bool] = None) -> str:
    d = estado(base, pid)
    t = _take(d, _valida(parte), _valida(tid))
    usar = t.get("usar_realce") if realce is None else realce
    nome = t["arquivo"].replace(".wav", "_realce.wav") if usar and t.get("realce") else t["arquivo"]
    return os.path.join(pasta(base, pid), nome)


def usar_take(base: str, pid: str, parte: str, tid: str) -> None:
    with _TRAVA:
        d = estado(base, pid)
        _take(d, _valida(parte), _valida(tid))
        d["partes"][parte]["ativo"] = tid
        _salvar(base, pid, d)


def apagar_take(base: str, pid: str, parte: str, tid: str) -> None:
    with _TRAVA:
        d = estado(base, pid)
        t = _take(d, _valida(parte), _valida(tid))
        pt = d["partes"][parte]
        pt["takes"] = [x for x in pt["takes"] if x["id"] != tid]
        if pt.get("ativo") == tid:
            pt["ativo"] = pt["takes"][-1]["id"] if pt["takes"] else None
        _salvar(base, pid, d)
    for nome in (t["arquivo"], t["arquivo"].replace(".wav", "_realce.wav")):
        try:
            os.remove(os.path.join(pasta(base, pid), nome))
        except OSError:
            pass


def _realcar(origem: str, destino: str) -> None:
    raiz = os.path.dirname(os.path.abspath(__file__))
    tk = os.path.join(raiz, "toolkit")
    if tk not in sys.path:
        sys.path.insert(0, tk)
    from tts.voice_generator import aplicar_realce_de_voz
    aplicar_realce_de_voz(origem, destino)


def realce(base: str, pid: str, parte: str, tid: str, usar: bool = True) -> Dict[str, Any]:
    """✨ gera (se ainda não tem) a versão com realce — o original nunca é apagado — e liga/desliga o uso dela."""
    parte, tid = _valida(parte), _valida(tid)
    d = estado(base, pid)
    t = _take(d, parte, tid)
    orig = os.path.join(pasta(base, pid), t["arquivo"])
    dest = orig.replace(".wav", "_realce.wav")
    if usar and not os.path.isfile(dest):
        try:
            _realcar(orig, dest)
        except Exception as exc:  # noqa: BLE001
            raise CT.CurtoErro(f"Não consegui fazer o realce: {str(exc)[:200]}")
    with _TRAVA:
        d = estado(base, pid)
        t = _take(d, parte, tid)
        t["realce"] = os.path.isfile(dest)
        t["usar_realce"] = bool(usar and t["realce"])
        _salvar(base, pid, d)
    return t


def faltando(base: str, pid: str) -> List[str]:
    """As partes do roteiro sem take ativo (vazio = dá pra enviar). Com um take ativo do TUDO, nada falta."""
    d = estado(base, pid)
    if ((d.get("partes") or {}).get(TUDO) or {}).get("ativo"):
        return []
    return [x["id"] for x in partes_de(base, pid) if not ((d.get("partes") or {}).get(x["id"]) or {}).get("ativo")]


def juntar(base: str, pid: str, realce_em_tudo: bool = False) -> str:
    """🧩 os takes ativos, na ordem do roteiro (ou o TUDO), com uma pausa curta entre as partes → minha_voz/final.wav."""
    d = estado(base, pid)
    falta = faltando(base, pid)
    if falta:
        raise CT.CurtoErro(f"Falta gravar {len(falta)} parte(s): " + ", ".join(falta[:8]))
    ordem = [TUDO] if ((d.get("partes") or {}).get(TUDO) or {}).get("ativo") else [x["id"] for x in partes_de(base, pid)]
    arquivos = []
    for parte in ordem:
        tid = d["partes"][parte]["ativo"]
        if realce_em_tudo and not _take(d, parte, tid).get("usar_realce"):
            realce(base, pid, parte, tid, True)
            d = estado(base, pid)
        arquivos.append(caminho_take(base, pid, parte, tid))
    saida = os.path.join(pasta(base, pid), "final.wav")
    if len(arquivos) == 1:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", arquivos[0], "-ac", "1", "-ar", "48000", saida], capture_output=True,
                       timeout=300, check=True)
        return saida
    entradas, filtro = [], []
    for k, a in enumerate(arquivos):
        entradas += ["-i", a]
        filtro.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=mono,apad=pad_dur={PAUSA_ENTRE_PARTES_S}[a{k}]")
    filtro.append("".join(f"[a{k}]" for k in range(len(arquivos))) + f"concat=n={len(arquivos)}:v=0:a=1[s]")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *entradas, "-filter_complex", ";".join(filtro), "-map", "[s]",
                        "-ac", "1", "-ar", "48000", saida], capture_output=True, timeout=600)
    if r.returncode != 0 or not os.path.isfile(saida):
        raise CT.CurtoErro("Não consegui juntar as partes: " + (r.stderr or b"").decode("utf-8", "replace")[-200:])
    return saida


def resumo(base: str, pid: str) -> Dict[str, Any]:
    d = estado(base, pid)
    ps = partes_de(base, pid)
    out = []
    for x in [{"id": TUDO, "texto": " ".join(y["texto"] for y in ps), "traducao": "", "funcao": "tudo"}] + ps:
        pt = (d.get("partes") or {}).get(x["id"]) or {}
        out.append(dict(x, ativo=pt.get("ativo"), takes=pt.get("takes") or []))
    return {"partes": out, "faltando": faltando(base, pid), "total_s": round(sum(
        next((t["dur"] for t in y["takes"] if t["id"] == y["ativo"]), 0) for y in out[1:]), 1),
            "final": os.path.isfile(os.path.join(pasta(base, pid), "final.wav"))}
