"""
📺 perfis_canal.py — PERFIS DO CANAL com a biblioteca de vídeos de cada um (v84_101)
==================================================================================

Um perfil = um canal seu (ex.: "Johans Akte", "Casos Arquivados"). Cada perfil guarda VÁRIOS vídeos de cada tipo:

    🎬 Intro (abertura)  ·  👍 Inscreva-se  ·  🛒 Venda  ·  🏁 Final (encerramento)

e, em cada tipo, qual é o ⭐ padrão. O perfil ⭐ ATIVO é o que os vídeos novos usam: o padrão de cada tipo entra sozinho
(intro no começo, final no fim, inscreva-se/venda nas marcas [[INSCREVA]]/[[VENDA]] do roteiro). No editor (aba
✂️ Cortes) dá pra trocar o perfil daquele vídeo e, quando um tipo tem mais de um vídeo, escolher QUAL entra em cada
item (cada marca de venda pode ter um vídeo diferente, por exemplo).

O perfil também tem o NOME DO CANAL falado nos roteiros (o do perfil ativo vale no lugar do das Configurações).

Disco: chamadas_padrao/perfis/perfis.json (índice) + chamadas_padrao/perfis/<id do perfil>/<tipo>_xxxxxx.mp4.
Na 1ª vez, o perfil "Meu canal" nasce com os vídeos padrão que já existiam (inscreva-se, venda, abertura, final).
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import arquivo_seguro

TIPOS: Dict[str, str] = {"abertura": "🎬 Intro (início do vídeo)", "inscreva": "👍 Inscreva-se / like",
                         "venda": "🛒 Venda", "encerramento": "🏁 Final (fim do vídeo)"}
CURTO: Dict[str, str] = {"abertura": "🎬 Intro", "inscreva": "👍 Inscreva-se", "venda": "🛒 Venda", "encerramento": "🏁 Final"}
EXTENSOES = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi")
_TRAVA = threading.RLock()


class PerfilErro(ValueError):
    pass


def pasta() -> str:
    import chamadas  # a pasta acompanha chamadas.PASTA_PADRAO (os testes trocam ela)
    return os.path.join(chamadas.PASTA_PADRAO, "perfis")


def _arquivo() -> str:
    return os.path.join(pasta(), "perfis.json")


def _novo_id() -> str:
    return uuid.uuid4().hex[:8]


def _perfil_vazio(nome: str, nome_canal: str = "") -> Dict[str, Any]:
    return {"id": _novo_id(), "nome": (" ".join(str(nome or "").split()) or "Meu canal")[:60],
            "nome_canal": " ".join(str(nome_canal or "").split())[:80], "criado": time.time(),
            "videos": {t: [] for t in TIPOS}, "padrao": {t: None for t in TIPOS}}


def _duracao(caminho: str) -> float:
    try:
        import video_assembler
        return round(float(video_assembler._probe_duration(caminho)), 2)
    except Exception:  # noqa: BLE001
        return 0.0


def _migrar() -> Dict[str, Any]:
    """1ª vez: o perfil "Meu canal" com os vídeos padrão antigos (chamadas_padrao/padrao.json) e o nome do canal."""
    import chamadas
    nome_canal = ""
    try:
        from site_config import load_site_config
        nome_canal = str(load_site_config().get("nome_canal") or "")
    except Exception:  # noqa: BLE001
        pass
    import hashlib
    p = _perfil_vazio("Meu canal", nome_canal)
    p["id"] = "principal"  # ids fixos: a migração (ainda não gravada) dá sempre o mesmo resultado
    for tipo, cam in chamadas._mapa_padrao().items():
        if tipo in TIPOS and cam and os.path.isfile(cam):
            v = {"id": hashlib.md5(cam.encode("utf-8")).hexdigest()[:8], "nome": os.path.basename(cam), "arquivo": cam,
                 "duracao": 0.0, "criado": 0}
            p["videos"][tipo].append(v)
            p["padrao"][tipo] = v["id"]
    return {"perfis": [p], "ativo": p["id"]}


def _ler() -> Dict[str, Any]:
    try:
        with open(_arquivo(), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and d.get("perfis"):
            return d
    except (OSError, ValueError):
        pass
    return _migrar()  # só grava quando alguma coisa mudar


def _limpo(d: Dict[str, Any]) -> Dict[str, Any]:
    for p in d["perfis"]:
        p.setdefault("videos", {})
        p.setdefault("padrao", {})
        for t in TIPOS:
            p["videos"][t] = [v for v in p["videos"].get(t) or [] if v.get("arquivo") and os.path.isfile(v["arquivo"])]
            ids = {v["id"] for v in p["videos"][t]}
            if p["padrao"].get(t) not in ids:
                p["padrao"][t] = None
    if d.get("ativo") not in {p["id"] for p in d["perfis"]}:
        d["ativo"] = d["perfis"][0]["id"]
    return d


def carregar() -> Dict[str, Any]:
    with _TRAVA:
        return _limpo(_ler())


def _gravar(d: Dict[str, Any]) -> None:
    os.makedirs(pasta(), exist_ok=True)
    arquivo_seguro.gravar_json(_arquivo(), d)


def listar() -> List[Dict[str, Any]]:
    d = carregar()
    return [dict(copy.deepcopy(p), ativo=p["id"] == d["ativo"]) for p in d["perfis"]]


def ativo_id() -> str:
    return carregar()["ativo"]


def perfil(pid: Optional[str] = None) -> Dict[str, Any]:
    d = carregar()
    pid = pid or d["ativo"]
    p = next((x for x in d["perfis"] if x["id"] == pid), None)
    if not p:
        raise PerfilErro("Perfil não encontrado.")
    return copy.deepcopy(p)


def existe(pid: Any) -> bool:
    return bool(pid) and any(p["id"] == pid for p in carregar()["perfis"])


def do_job(job: Dict[str, Any]) -> str:
    """O perfil daquele vídeo (o escolhido no editor) ou o ativo."""
    pid = (job or {}).get("perfil_canal")
    return pid if existe(pid) else ativo_id()


# ------------------------------------------------------------------ mudar
def _mudar(fn):
    with _TRAVA:
        d = _limpo(_ler())
        r = fn(d)
        _gravar(d)
        return r


def _achar(d: Dict[str, Any], pid: str) -> Dict[str, Any]:
    p = next((x for x in d["perfis"] if x["id"] == pid), None)
    if not p:
        raise PerfilErro("Perfil não encontrado.")
    return p


def criar(nome: str, nome_canal: str = "", ativar: bool = False) -> Dict[str, Any]:
    def fn(d):
        p = _perfil_vazio(nome, nome_canal)
        d["perfis"].append(p)
        if ativar:
            d["ativo"] = p["id"]
        return copy.deepcopy(p)
    return _mudar(fn)


def editar(pid: str, nome: Optional[str] = None, nome_canal: Optional[str] = None) -> None:
    def fn(d):
        p = _achar(d, pid)
        if nome is not None and " ".join(str(nome).split()):
            p["nome"] = " ".join(str(nome).split())[:60]
        if nome_canal is not None:
            p["nome_canal"] = " ".join(str(nome_canal).split())[:80]
    _mudar(fn)


def definir_ativo(pid: str) -> None:
    def fn(d):
        _achar(d, pid)
        d["ativo"] = pid
    _mudar(fn)


def apagar(pid: str) -> None:
    def fn(d):
        p = _achar(d, pid)
        if len(d["perfis"]) <= 1:
            raise PerfilErro("Esse é o único perfil — crie outro antes de apagar este.")
        d["perfis"].remove(p)
        if d["ativo"] == pid:
            d["ativo"] = d["perfis"][0]["id"]
        return p
    p = _mudar(fn)
    minha = os.path.join(pasta(), pid)
    shutil.rmtree(minha, ignore_errors=True)  # os vídeos que vieram de fora (migração) ficam onde estavam


def adicionar_video(pid: str, tipo: str, origem: str, nome: str = "", padrao: Optional[bool] = None) -> Dict[str, Any]:
    """Guarda uma CÓPIA do vídeo no perfil. padrao=None: vira padrão se for o 1º daquele tipo."""
    if tipo not in TIPOS:
        raise PerfilErro("Tipo de vídeo desconhecido (intro, inscreva, venda ou final).")
    if not origem or not os.path.isfile(origem):
        raise PerfilErro("Arquivo de vídeo não encontrado.")
    ext = os.path.splitext(nome or origem)[1].lower()
    ext = ext if ext in EXTENSOES else ".mp4"
    destino_dir = os.path.join(pasta(), pid)
    os.makedirs(destino_dir, exist_ok=True)
    destino = os.path.join(destino_dir, f"{tipo}_{uuid.uuid4().hex[:6]}{ext}")
    shutil.copy(origem, destino)
    v = {"id": _novo_id(), "nome": (os.path.splitext(os.path.basename(nome or origem))[0] or CURTO[tipo])[:80],
         "arquivo": destino, "duracao": _duracao(destino), "criado": time.time()}

    def fn(d):
        p = _achar(d, pid)
        p["videos"][tipo].append(v)
        if padrao or (padrao is None and not p["padrao"].get(tipo)):
            p["padrao"][tipo] = v["id"]
        return dict(v)
    try:
        return _mudar(fn)
    except PerfilErro:
        os.remove(destino)
        raise


def _achar_video(p: Dict[str, Any], vid: str):
    for t in TIPOS:
        for v in p["videos"][t]:
            if v["id"] == vid:
                return t, v
    raise PerfilErro("Vídeo não encontrado.")


def editar_video(pid: str, vid: str, nome: Optional[str] = None, padrao: Optional[bool] = None) -> None:
    def fn(d):
        p = _achar(d, pid)
        t, v = _achar_video(p, vid)
        if nome is not None and str(nome).strip():
            v["nome"] = " ".join(str(nome).split())[:80]
        if padrao is True:
            p["padrao"][t] = vid
        elif padrao is False and p["padrao"].get(t) == vid:
            p["padrao"][t] = None
    _mudar(fn)


def apagar_video(pid: str, vid: str) -> None:
    def fn(d):
        p = _achar(d, pid)
        t, v = _achar_video(p, vid)
        p["videos"][t].remove(v)
        if p["padrao"].get(t) == vid:
            p["padrao"][t] = p["videos"][t][0]["id"] if p["videos"][t] else None
        return v
    v = _mudar(fn)
    if os.path.dirname(os.path.abspath(v["arquivo"])) == os.path.abspath(os.path.join(pasta(), pid)):
        try:
            os.remove(v["arquivo"])
        except OSError:
            pass


def definir_padrao(pid: str, tipo: str, vid: Optional[str]) -> None:
    if tipo not in TIPOS:
        raise PerfilErro("Tipo desconhecido.")

    def fn(d):
        p = _achar(d, pid)
        if vid and vid not in {v["id"] for v in p["videos"][tipo]}:
            raise PerfilErro("Vídeo não encontrado nesse tipo.")
        p["padrao"][tipo] = vid or None
    _mudar(fn)


# ------------------------------------------------------------------ usar
def videos(tipo: str, pid: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        p = perfil(pid)
    except PerfilErro:
        return []
    return [dict(v, padrao=v["id"] == p["padrao"].get(tipo)) for v in p["videos"].get(tipo) or []]


def caminho(pid: Optional[str], vid: str) -> Optional[str]:
    try:
        _t, v = _achar_video(perfil(pid), vid)
    except PerfilErro:
        return None
    return v["arquivo"] if os.path.isfile(v["arquivo"]) else None


def caminho_padrao(tipo: str, pid: Optional[str] = None) -> Optional[str]:
    try:
        p = perfil(pid)
    except PerfilErro:
        return None
    vid = p["padrao"].get(tipo)
    v = next((x for x in p["videos"].get(tipo) or [] if x["id"] == vid), None)
    return v["arquivo"] if v and os.path.isfile(v["arquivo"]) else None


def nome_canal_ativo() -> str:
    try:
        return perfil()["nome_canal"]
    except Exception:  # noqa: BLE001
        return ""


def resumo() -> Dict[str, Any]:
    """Pro editor: os perfis (id, nome) e o ativo."""
    d = carregar()
    return {"ativo": d["ativo"], "lista": [{"id": p["id"], "nome": p["nome"],
                                            "videos": {t: len(p["videos"][t]) for t in TIPOS}} for p in d["perfis"]]}
