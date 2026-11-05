"""📤 v84_355: enviar os vídeos prontos pro YouTube (API oficial do Google), com a capa, numa agenda por canal.

• Você marca os vídeos na lista do 🔗 Link e clica em "📤 YouTube": cada um ganha o próximo horário livre do canal
  (ex.: 1 por dia às 18:00, ou 3 por dia às 12:00/18:00/21:00). O site SOBE na hora marcada (o PC e o site precisam
  estar ligados; se estavam desligados, os atrasados sobem assim que o site abrir, um por vez).
• A capa vai logo depois do vídeo. Se o YouTube recusar a capa (canal sem a verificação por telefone, limite de capas
  personalizadas, imagem grande demais…), a capa é DESCARTADA e o vídeo fica no ar do mesmo jeito — o aviso fica na fila.
• Limite de envios do canal (uploadLimitExceeded) ou da cota da API (quotaExceeded): o vídeo volta pra fila e a conta
  fica pausada até o limite zerar; depois continua sozinha.
• Erro de rede / 5xx: tenta de novo em 10 min (até 3 vezes).

⚠ Projeto do Google Cloud NÃO auditado: o YouTube trava como PRIVADO todo vídeo enviado pela API (regra do Google).
  Pra sair público é preciso pedir a auditoria da API do YouTube. Cota (desde jun/2026): o envio custa 1 unidade, num balde próprio de até 100 envios por dia por projeto.

Guarda tudo em <base>/youtube/: cliente.json (a credencial OAuth), contas.json (os tokens de cada canal do YouTube),
config.json (a agenda de cada canal do site) e fila.json.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import secrets
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import arquivo_seguro

ESCOPOS = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
URL_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_CANAIS = "https://www.googleapis.com/youtube/v3/channels"
URL_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
URL_THUMB = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
PEDACO = 8 * 1024 * 1024  # múltiplo de 256 KB (exigência do upload retomável)
MAX_THUMB = 2 * 1024 * 1024
PRIVACIDADES = ("public", "unlisted", "private")
ESTADOS_ATIVOS = ("na_fila", "enviando")
TENTATIVAS = 3

_TRAVA = threading.RLock()
_ESTADOS_OAUTH: Dict[str, float] = {}
_WORKER: Dict[str, Any] = {"th": None, "parar": False}


class YtErro(Exception):
    def __init__(self, msg: str, motivo: str = "", status: int = 0):
        super().__init__(msg)
        self.motivo, self.status = motivo, status


# ------------------------------------------------------------------ guardar
def pasta(base: str) -> str:
    return os.path.join(base, "youtube")


def _ler(base: str, nome: str, padrao: Any) -> Any:
    try:
        with open(os.path.join(pasta(base), nome), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def _gravar(base: str, nome: str, dados: Any) -> None:
    os.makedirs(pasta(base), exist_ok=True)
    arquivo_seguro.gravar_json(os.path.join(pasta(base), nome), dados, indent=1)


def cliente(base: str) -> Dict[str, Any]:
    return _ler(base, "cliente.json", {})


def salvar_cliente(base: str, texto: str) -> Dict[str, Any]:
    """Aceita o JSON baixado do Google Cloud (tipo 'web' ou 'installed')."""
    try:
        d = json.loads(texto)
    except ValueError:
        raise YtErro("Esse arquivo não é um JSON — baixe de novo em Google Cloud › Credenciais › ⬇ (Fazer download do JSON).")
    bloco = d.get("web") or d.get("installed") or d
    cid, seg = str(bloco.get("client_id") or "").strip(), str(bloco.get("client_secret") or "").strip()
    if not cid.endswith(".apps.googleusercontent.com") or not seg:
        raise YtErro("Não achei client_id / client_secret nesse JSON (é o da credencial 'ID do cliente OAuth').")
    c = {"client_id": cid, "client_secret": seg, "tipo": "web" if d.get("web") else "installed"}
    with _TRAVA:
        _gravar(base, "cliente.json", c)
    return c


def contas(base: str) -> Dict[str, Dict[str, Any]]:
    return _ler(base, "contas.json", {})


def config(base: str) -> Dict[str, Any]:
    c = _ler(base, "config.json", {})
    c.setdefault("canais", {})
    return c


def fila(base: str) -> List[Dict[str, Any]]:
    return _ler(base, "fila.json", [])


# ------------------------------------------------------------------ HTTP (trocável nos testes)
def _http(metodo: str, url: str, **kw: Any):
    import requests
    kw.setdefault("timeout", 120)
    return requests.request(metodo, url, **kw)


HTTP: Callable[..., Any] = _http


def _erro_google(r: Any) -> YtErro:
    motivo, msg = "", ""
    try:
        j = r.json()
        e = j.get("error")
        if isinstance(e, dict):
            msg = e.get("message") or ""
            errs = e.get("errors") or []
            motivo = (errs[0].get("reason") if errs else "") or e.get("status") or ""
        elif isinstance(e, str):  # erro do OAuth: {"error": "invalid_grant", "error_description": "..."}
            motivo, msg = e, j.get("error_description") or e
    except Exception:  # noqa: BLE001
        msg = (getattr(r, "text", "") or "")[:300]
    return YtErro(f"YouTube {r.status_code}: {msg or motivo or 'erro'}", motivo, r.status_code)


# ------------------------------------------------------------------ OAuth
def url_conectar(base: str, redirect_uri: str) -> str:
    from urllib.parse import urlencode
    c = cliente(base)
    if not c:
        raise YtErro("Primeiro envie a credencial (o JSON do Google Cloud).")
    st = secrets.token_urlsafe(16)
    with _TRAVA:
        agora = time.time()
        for k in [k for k, t in _ESTADOS_OAUTH.items() if agora - t > 900]:
            _ESTADOS_OAUTH.pop(k, None)
        _ESTADOS_OAUTH[st] = agora
    return URL_AUTH + "?" + urlencode({"client_id": c["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
                                      "scope": ESCOPOS, "access_type": "offline", "prompt": "consent",
                                      "include_granted_scopes": "true", "state": st})


def concluir_conexao(base: str, code: str, state: str, redirect_uri: str) -> Dict[str, Any]:
    with _TRAVA:
        if not state or _ESTADOS_OAUTH.pop(state, None) is None:
            raise YtErro("Esse retorno do Google expirou ou não foi pedido por aqui — clique em conectar de novo.")
    c = cliente(base)
    r = HTTP("POST", URL_TOKEN, data={"code": code, "client_id": c.get("client_id"), "client_secret": c.get("client_secret"),
                                       "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
    if r.status_code != 200:
        raise _erro_google(r)
    tok = r.json()
    if not tok.get("refresh_token"):
        raise YtErro("O Google não mandou o refresh_token — remova o acesso do app em myaccount.google.com/permissions e conecte de novo.")
    acesso, expira = tok["access_token"], time.time() + int(tok.get("expires_in") or 3600) - 60
    r = HTTP("GET", URL_CANAIS, params={"part": "snippet", "mine": "true"}, headers={"Authorization": f"Bearer {acesso}"})
    if r.status_code != 200:
        raise _erro_google(r)
    itens = r.json().get("items") or []
    if not itens:
        raise YtErro("Essa conta Google não tem canal do YouTube (crie o canal antes, ou escolha a conta da marca certa).")
    ch = itens[0]
    conta = {"titulo": (ch.get("snippet") or {}).get("title") or ch["id"], "refresh_token": tok["refresh_token"],
             "access_token": acesso, "expira": expira, "conectada": time.time(), "pausada_ate": 0, "motivo": ""}
    with _TRAVA:
        cs = contas(base)
        cs[ch["id"]] = conta
        _gravar(base, "contas.json", cs)
    return {"id": ch["id"], "titulo": conta["titulo"]}


def desconectar(base: str, conta_id: str) -> None:
    with _TRAVA:
        cs = contas(base)
        cs.pop(conta_id, None)
        _gravar(base, "contas.json", cs)


def _token(base: str, conta_id: str, forcar: bool = False) -> str:
    with _TRAVA:
        cs = contas(base)
        ct = cs.get(conta_id)
        if not ct:
            raise YtErro("A conta do YouTube desse canal não está conectada.", "sem_conta")
        if not forcar and ct.get("access_token") and ct.get("expira", 0) > time.time():
            return ct["access_token"]
        c = cliente(base)
    r = HTTP("POST", URL_TOKEN, data={"client_id": c.get("client_id"), "client_secret": c.get("client_secret"),
                                       "refresh_token": ct.get("refresh_token"), "grant_type": "refresh_token"})
    if r.status_code != 200:
        e = _erro_google(r)
        if e.motivo == "invalid_grant":
            with _TRAVA:
                cs = contas(base)
                if conta_id in cs:
                    cs[conta_id]["motivo"] = "desconectada (reconecte — em modo 'Teste' o Google derruba o acesso em 7 dias)"
                    _gravar(base, "contas.json", cs)
            raise YtErro("O acesso à conta do YouTube caiu — reconecte na página 📤 YouTube.", "sem_conta")
        raise e
    tok = r.json()
    with _TRAVA:
        cs = contas(base)
        if conta_id in cs:
            cs[conta_id].update(access_token=tok["access_token"], expira=time.time() + int(tok.get("expires_in") or 3600) - 60, motivo="")
            _gravar(base, "contas.json", cs)
    return tok["access_token"]


# ------------------------------------------------------------------ agenda
def limpar_agenda(d: Dict[str, Any]) -> Dict[str, Any]:
    hs = []
    for h in d.get("horarios") or []:
        m = re.fullmatch(r"\s*(\d{1,2})[:h](\d{2})?\s*", str(h))
        if m and int(m.group(1)) < 24 and int(m.group(2) or 0) < 60:
            v = f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}"
            if v not in hs:
                hs.append(v)
    hs.sort()
    try:
        por_dia = max(1, min(24, int(d.get("por_dia") or len(hs) or 1)))
    except (TypeError, ValueError):
        por_dia = 1
    priv = d.get("privacidade") if d.get("privacidade") in PRIVACIDADES else "public"
    return {"conta": str(d.get("conta") or ""), "horarios": hs or ["18:00"], "por_dia": por_dia, "privacidade": priv,
            "categoria": str(d.get("categoria") or "24") if re.fullmatch(r"\d{1,3}", str(d.get("categoria") or "24")) else "24",
            "shorts_tag": bool(d.get("shorts_tag"))}


def salvar_agenda(base: str, canal_id: str, d: Dict[str, Any]) -> Dict[str, Any]:
    a = limpar_agenda(d)
    with _TRAVA:
        c = config(base)
        c["canais"][canal_id] = a
        _gravar(base, "config.json", c)
    return a


def agenda(base: str, canal_id: str) -> Optional[Dict[str, Any]]:
    a = config(base)["canais"].get(canal_id)
    return limpar_agenda(a) if a else None


def horarios_do_dia(a: Dict[str, Any]) -> List[str]:
    return a["horarios"][:a["por_dia"]] if len(a["horarios"]) >= a["por_dia"] else _espalhar(a)


def _espalhar(a: Dict[str, Any]) -> List[str]:
    """Pediu 3 por dia mas só deu 1 horário: os outros ficam a cada 3 h depois dele."""
    hs = list(a["horarios"])
    h, m = map(int, hs[-1].split(":"))
    while len(hs) < a["por_dia"]:
        h = (h + 3) % 24
        v = f"{h:02d}:{m:02d}"
        if v in hs:
            break
        hs.append(v)
    return sorted(hs)


PERTO_S = 90 * 60  # um vídeo que já saiu (ou está agendado) no canal a menos de 1h30 de um horário: esse horário já foi


def proximo_horario(a: Dict[str, Any], ocupados: set, agora: Optional[float] = None, no_canal: Optional[List[float]] = None) -> float:
    """O próximo horário livre. `no_canal`: quando saíram/vão sair os vídeos que JÁ estão no YouTube (postados por aqui ou
    à mão no Studio) — o dia que já tem os 'por dia' dele não recebe mais, e horário colado num vídeo do canal é pulado."""
    agora = agora or time.time()
    dia = _dt.date.fromtimestamp(agora)
    no_canal = [t for t in (no_canal or []) if t]
    for d in range(0, 400):
        data = dia + _dt.timedelta(days=d)
        do_dia = [t for t in no_canal if _dt.date.fromtimestamp(t) == data]
        na_fila = sum(1 for t in ocupados if _dt.date.fromtimestamp(t) == data)
        if len(do_dia) + na_fila >= a["por_dia"]:
            continue
        for h in horarios_do_dia(a):
            hh, mm = map(int, h.split(":"))
            ts = time.mktime(_dt.datetime(data.year, data.month, data.day, hh, mm).timetuple())
            if ts > agora and int(ts) not in ocupados and not any(abs(ts - t) < PERTO_S for t in do_dia):
                return float(int(ts))
    raise YtErro("A agenda está cheia por mais de um ano.")


# ------------------------------------------------------------------ fila
def adicionar(base: str, itens: List[Dict[str, Any]], agora_ja: bool = False, agora: Optional[float] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """itens: [{pid, canal_id, nome}] (só os prontos). Cada um ganha o próximo horário livre do canal (ou 'agora')."""
    agora = agora or time.time()
    novos, pulados = [], []
    no_yt: Dict[str, List[Dict[str, Any]]] = {}  # 📺 os últimos vídeos de cada canal do YouTube (fora da trava: é rede)
    for it in itens:
        a = agenda(base, it.get("canal_id") or "")
        if a and a["conta"] in contas(base) and a["conta"] not in no_yt:
            try:
                no_yt[a["conta"]] = recentes(base, a["conta"]).get("videos") or []
            except Exception:  # noqa: BLE001  (sem a lista, agenda só pela fila)
                no_yt[a["conta"]] = []
    with _TRAVA:
        f = fila(base)
        for it in itens:
            nome = it.get("nome") or it["pid"]
            if any(x["pid"] == it["pid"] and x["estado"] in ESTADOS_ATIVOS + ("enviado",) for x in f):
                pulados.append(f"{nome}: já está na fila ou já foi enviado")
                continue
            a = agenda(base, it.get("canal_id") or "")
            if not a or not a["conta"]:
                pulados.append(f"{nome}: o canal {it.get('canal') or '(sem canal)'} não tem conta do YouTube ligada — ajuste em 📤 YouTube")
                continue
            if a["conta"] not in contas(base):
                pulados.append(f"{nome}: a conta do YouTube ligada a esse canal foi desconectada")
                continue
            ja = next((v for v in no_yt.get(a["conta"]) or [] if _norm(v.get("titulo")) and _norm(v.get("titulo")) == _norm(nome)), None)
            if ja:
                pulados.append(f"{nome}: o canal já tem um vídeo com esse título ({time.strftime('%d/%m', time.localtime(ja.get('quando') or 0))}) — troque o título")
                continue
            ocupados = {int(x["quando"]) for x in f if x.get("canal_id") == it.get("canal_id") and x["estado"] not in ("cancelado", "enviado")}
            no_canal = _no_canal(no_yt.get(a["conta"]) or [], f, it.get("canal_id") or "")
            quando = agora if agora_ja else proximo_horario(a, ocupados, agora, no_canal)
            x = {"id": secrets.token_hex(6), "pid": it["pid"], "canal_id": it.get("canal_id") or "", "canal": it.get("canal") or "",
                 "nome": nome, "conta": a["conta"], "quando": quando, "estado": "na_fila", "tentativas": 0,
                 "yt_id": "", "erro": "", "aviso": "", "log": [], "criado": agora}
            f.append(x)
            novos.append(x)
        _gravar(base, "fila.json", f)
    return novos, pulados


def _mexer(base: str, iid: str, **campos: Any) -> Optional[Dict[str, Any]]:
    with _TRAVA:
        f = fila(base)
        for x in f:
            if x["id"] == iid:
                log = campos.pop("_log", None)
                x.update(campos)
                if log:
                    x.setdefault("log", []).append(f"{time.strftime('%d/%m %H:%M')} {log}")
                    x["log"] = x["log"][-12:]
                _gravar(base, "fila.json", f)
                return dict(x)
    return None


def acao(base: str, iid: str, qual: str) -> Dict[str, Any]:
    with _TRAVA:
        x = next((x for x in fila(base) if x["id"] == iid), None)
        if not x:
            raise YtErro("Esse item não está mais na fila.")
        if qual == "agora":
            if x["estado"] not in ("na_fila", "erro", "cancelado"):
                raise YtErro("Esse já está subindo ou já subiu.")
            return _mexer(base, iid, estado="na_fila", quando=time.time(), erro="", tentativas=0, _log="▶ enviar agora")
        if qual == "cancelar":
            if x["estado"] == "enviando":
                raise YtErro("Já está subindo — espere terminar.")
            return _mexer(base, iid, estado="cancelado", _log="⏹ cancelado")
        if qual == "tirar":
            if x["estado"] == "enviando":
                raise YtErro("Já está subindo — espere terminar.")
            f = [y for y in fila(base) if y["id"] != iid]
            _gravar(base, "fila.json", f)
            return x
    raise YtErro("Ação desconhecida.")


def _no_canal(vids: List[Dict[str, Any]], f: List[Dict[str, Any]], canal_id: str) -> List[float]:
    """Quando saíram/vão sair os vídeos do canal: os do YouTube (postados e AGENDADOS no Studio) + os enviados por aqui
    que a lista do YouTube ainda não mostra (sem contar o mesmo vídeo 2 vezes)."""
    ids = {v.get("id") for v in vids}
    return [v.get("quando") for v in vids] + [x.get("enviado") or x["quando"] for x in f
                                              if x.get("canal_id") == canal_id and x["estado"] == "enviado" and x.get("yt_id") not in ids]


def reagendar(base: str, canal_id: str, agora: Optional[float] = None) -> int:
    """Depois de mudar os horários: os que ainda estão na fila desse canal ganham os horários novos, na mesma ordem."""
    agora = agora or time.time()
    with _TRAVA:
        a = agenda(base, canal_id)
        f = fila(base)
        if not a:
            return 0
        mover = sorted((x for x in f if x.get("canal_id") == canal_id and x["estado"] == "na_fila"), key=lambda x: x["quando"])
        ocupados = {int(x["quando"]) for x in f if x.get("canal_id") == canal_id and x["estado"] == "enviando"}
        no_canal = _no_canal((_ler_recentes(base, a["conta"]) or {}).get("videos") or [], f, canal_id)
        for x in mover:
            x["quando"] = proximo_horario(a, ocupados, agora, no_canal)
            ocupados.add(int(x["quando"]))
        _gravar(base, "fila.json", f)
        return len(mover)


# ------------------------------------------------------------------ envio
def _texto_titulo(t: str) -> str:
    t = re.sub(r"[<>]", "", str(t or "")).strip()
    return (t[:97] + "…") if len(t) > 100 else (t or "Vídeo")


def _tags(hashtags: List[str]) -> List[str]:
    out, total = [], 0
    for h in hashtags or []:
        t = re.sub(r"[<>,]", "", str(h).lstrip("#")).strip()
        if t and t.lower() not in {o.lower() for o in out} and total + len(t) + 1 <= 480:
            out.append(t)
            total += len(t) + 1
    return out


def corpo_video(meta: Dict[str, Any], a: Dict[str, Any]) -> Dict[str, Any]:
    titulo = meta.get("titulo") or ""
    if a.get("shorts_tag") and "#shorts" not in titulo.lower():
        titulo = titulo.rstrip() + " #shorts"
    desc = str(meta.get("descricao") or "")
    tags = meta.get("hashtags") or []
    if tags:
        desc = (desc.rstrip() + "\n\n" + " ".join(t if str(t).startswith("#") else "#" + str(t) for t in tags)).strip()
    desc = re.sub(r"[<>]", "", desc)
    while len(desc.encode("utf-8")) > 4900:
        desc = desc[:-50]
    return {"snippet": {"title": _texto_titulo(titulo), "description": desc, "tags": _tags(tags), "categoryId": a.get("categoria") or "24"},
            "status": {"privacyStatus": a.get("privacidade") or "public", "selfDeclaredMadeForKids": False, "embeddable": True}}


def _com_token(base: str, conta: str, fazer: Callable[[str], Any]) -> Any:
    r = fazer(_token(base, conta))
    if getattr(r, "status_code", 0) == 401:
        r = fazer(_token(base, conta, forcar=True))
    return r


def subir_video(base: str, conta: str, arquivo: str, corpo: Dict[str, Any], progresso: Optional[Callable[[float], None]] = None) -> str:
    total = os.path.getsize(arquivo)
    r = _com_token(base, conta, lambda tk: HTTP("POST", URL_UPLOAD, params={"uploadType": "resumable", "part": "snippet,status"},
                                                  headers={"Authorization": f"Bearer {tk}", "Content-Type": "application/json; charset=UTF-8",
                                                           "X-Upload-Content-Length": str(total), "X-Upload-Content-Type": "video/mp4"},
                                                  data=json.dumps(corpo).encode("utf-8")))
    if r.status_code not in (200, 201) or not r.headers.get("Location"):
        raise _erro_google(r)
    sessao = r.headers["Location"]
    inicio = 0
    with open(arquivo, "rb") as fh:
        while True:
            fh.seek(inicio)
            dados = fh.read(PEDACO)
            fim = inicio + len(dados) - 1
            r = HTTP("PUT", sessao, data=dados, timeout=600,
                     headers={"Authorization": f"Bearer {_token(base, conta)}", "Content-Length": str(len(dados)),
                              "Content-Range": f"bytes {inicio}-{fim}/{total}"})
            if r.status_code in (200, 201):
                vid = (r.json() or {}).get("id")
                if not vid:
                    raise YtErro("O YouTube terminou o envio mas não devolveu o id do vídeo.")
                if progresso:
                    progresso(1.0)
                return vid
            if r.status_code == 308:
                m = re.search(r"bytes=0-(\d+)", r.headers.get("Range") or "")
                inicio = int(m.group(1)) + 1 if m else 0
                if progresso:
                    progresso(inicio / max(1, total))
                continue
            raise _erro_google(r)


def preparar_thumb(cam: str, pasta_tmp: str) -> Tuple[str, str]:
    """JPG/PNG até 2 MB (limite do YouTube); maior que isso, recomprime em JPG."""
    if os.path.getsize(cam) <= MAX_THUMB and cam.lower().endswith((".jpg", ".jpeg", ".png")):
        return cam, "image/png" if cam.lower().endswith(".png") else "image/jpeg"
    from PIL import Image
    os.makedirs(pasta_tmp, exist_ok=True)
    saida = os.path.join(pasta_tmp, "thumb_yt.jpg")
    im = Image.open(cam).convert("RGB")
    if max(im.size) > 1920:
        im.thumbnail((1920, 1920))
    for q in (90, 80, 70, 60, 50):
        im.save(saida, "JPEG", quality=q)
        if os.path.getsize(saida) <= MAX_THUMB:
            break
    return saida, "image/jpeg"


def subir_thumb(base: str, conta: str, video_id: str, cam: str) -> None:
    arq, tipo = preparar_thumb(cam, os.path.join(pasta(base), "tmp"))
    with open(arq, "rb") as fh:
        dados = fh.read()
    r = _com_token(base, conta, lambda tk: HTTP("POST", URL_THUMB, params={"videoId": video_id, "uploadType": "media"},
                                                  headers={"Authorization": f"Bearer {tk}", "Content-Type": tipo}, data=dados))
    if r.status_code not in (200, 201):
        raise _erro_google(r)


MOTIVOS_LIMITE_CANAL = {"uploadLimitExceeded"}
MOTIVOS_COTA = {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"}


def _meia_noite_pacifico(agora: float) -> float:
    """A cota da API zera à meia-noite do horário do Pacífico."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
        d = _dt.datetime.fromtimestamp(agora, tz) + _dt.timedelta(days=1)
        return _dt.datetime(d.year, d.month, d.day, 0, 5, tzinfo=tz).timestamp()
    except Exception:  # noqa: BLE001  (Windows sem tzdata)
        return agora + 24 * 3600


def pausar_conta(base: str, conta: str, ate: float, motivo: str) -> None:
    with _TRAVA:
        cs = contas(base)
        if conta in cs:
            cs[conta].update(pausada_ate=ate, motivo=motivo)
            _gravar(base, "contas.json", cs)


def proximo_da_fila(base: str, agora: Optional[float] = None) -> Optional[Dict[str, Any]]:
    agora = agora or time.time()
    cs = contas(base)
    prontos = [x for x in fila(base) if x["estado"] == "na_fila" and x["quando"] <= agora
               and (cs.get(x["conta"]) or {}).get("pausada_ate", 0) <= agora]
    return min(prontos, key=lambda x: x["quando"]) if prontos else None


def enviar_item(base: str, x: Dict[str, Any], meta_de: Callable[[str], Optional[Dict[str, Any]]], agora: Optional[float] = None) -> Dict[str, Any]:
    """Sobe UM item: vídeo → capa (capa com erro é descartada, o vídeo fica). Devolve o item atualizado."""
    agora = agora or time.time()
    iid, conta = x["id"], x["conta"]
    _mexer(base, iid, estado="enviando", erro="", _log="⏫ subindo o vídeo")
    try:
        meta = meta_de(x["pid"])
        if not meta or not meta.get("video") or not os.path.isfile(meta["video"]):
            return _mexer(base, iid, estado="erro", erro="O vídeo pronto não existe mais (foi apagado ou ainda não exportou).", _log="❌ sem o arquivo do vídeo")
        a = agenda(base, x.get("canal_id") or "") or limpar_agenda({})
        corpo = corpo_video(meta, a)
        yt_id = subir_video(base, conta, meta["video"], corpo,
                            progresso=lambda p: _mexer(base, iid, prog=round(p * 100)))
    except YtErro as e:
        if e.motivo in MOTIVOS_LIMITE_CANAL:
            pausar_conta(base, conta, agora + 24 * 3600, "📛 limite de envios do canal — continua em 24 h")
            return _mexer(base, iid, estado="na_fila", erro="", _log="📛 o canal chegou no limite de envios do dia — volta pra fila (pausa de 24 h)")
        if e.motivo in MOTIVOS_COTA:
            pausar_conta(base, conta, _meia_noite_pacifico(agora), "📛 cota diária da API acabou — continua quando o Google zerar")
            return _mexer(base, iid, estado="na_fila", erro="", _log="📛 cota da API do Google acabou — volta pra fila (zera à meia-noite do Pacífico)")
        if e.motivo == "sem_conta":
            return _mexer(base, iid, estado="erro", erro=str(e), _log="🔌 " + str(e))
        return _falha(base, x, str(e), temporario=e.status >= 500 or e.status == 0)
    except Exception as e:  # noqa: BLE001  (rede caiu, timeout…)
        return _falha(base, x, f"{type(e).__name__}: {e}"[:300], temporario=True)
    _mexer(base, iid, estado="enviado", yt_id=yt_id, enviado=time.time(), prog=100, _log=f"✅ no YouTube: {yt_id}")
    aviso = ""
    if meta.get("thumb") and os.path.isfile(meta["thumb"]):
        try:
            subir_thumb(base, conta, yt_id, meta["thumb"])
            _mexer(base, iid, capa="ok", _log="🖼 capa enviada")
        except Exception as e:  # noqa: BLE001  (qualquer erro na capa: descarta e segue — o vídeo já está no ar)
            motivo = getattr(e, "motivo", "")
            aviso = ("🖼 capa descartada: o canal ainda não pode usar capa personalizada (verifique o canal por telefone em youtube.com/verify)"
                     if motivo in ("forbidden", "insufficientPermissions") or getattr(e, "status", 0) == 403 else
                     "🖼 capa descartada: limite de capas personalizadas" if motivo in ("uploadRateLimitExceeded", "rateLimitExceeded") or getattr(e, "status", 0) == 429 else
                     f"🖼 capa descartada: {e}"[:300])
            _mexer(base, iid, capa="descartada", aviso=aviso, _log=aviso)
    else:
        _mexer(base, iid, capa="sem", _log="🖼 sem capa escolhida (o YouTube escolhe um quadro)")
    return _mexer(base, iid)


def _falha(base: str, x: Dict[str, Any], msg: str, temporario: bool) -> Dict[str, Any]:
    n = int(x.get("tentativas") or 0) + 1
    if temporario and n < TENTATIVAS:
        return _mexer(base, x["id"], estado="na_fila", tentativas=n, quando=time.time() + 600, erro="",
                      _log=f"⚠ {msg} — tenta de novo em 10 min ({n}/{TENTATIVAS})")
    return _mexer(base, x["id"], estado="erro", tentativas=n, erro=msg, _log="❌ " + msg)


def destravar(base: str) -> int:
    """Site reiniciou no meio de um envio: o item volta pra fila (o envio recomeça do zero)."""
    with _TRAVA:
        f = fila(base)
        n = 0
        for x in f:
            if x["estado"] == "enviando":
                x["estado"], n = "na_fila", n + 1
        if n:
            _gravar(base, "fila.json", f)
        return n


def rodada(base: str, meta_de: Callable[[str], Optional[Dict[str, Any]]], agora: Optional[float] = None) -> Optional[Dict[str, Any]]:
    x = proximo_da_fila(base, agora)
    return enviar_item(base, x, meta_de, agora) if x else None


def iniciar_worker(base: str, meta_de: Callable[[str], Optional[Dict[str, Any]]], intervalo: float = 20) -> None:
    with _TRAVA:
        if _WORKER["th"] and _WORKER["th"].is_alive():
            return
        destravar(base)

        def laco() -> None:
            while not _WORKER["parar"]:
                try:
                    while rodada(base, meta_de):  # um atrás do outro enquanto houver atrasados
                        pass
                except Exception:  # noqa: BLE001  (o laço nunca morre)
                    pass
                time.sleep(intervalo)

        _WORKER["th"] = threading.Thread(target=laco, name="youtube-envio", daemon=True)
        _WORKER["th"].start()


# ------------------------------------------------------------------ 📺 v84_356: os últimos vídeos do canal no YouTube
RECENTES_TTL = 30 * 60


def _norm(t: Any) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"#\w+", "", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _iso_ts(v: Any) -> float:
    try:
        return _dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp() if v else 0.0
    except ValueError:
        return 0.0


def _duracao(iso: str) -> int:
    m = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", str(iso or ""))
    return (int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)) if m else 0


def _ler_recentes(base: str, conta: str) -> Dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{3,64}", conta or ""):
        return {}
    return _ler(base, os.path.join("recentes", conta + ".json"), {})


def _get(base: str, conta: str, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    r = _com_token(base, conta, lambda tk: HTTP("GET", url, params=params, headers={"Authorization": f"Bearer {tk}"}, timeout=40))
    if r.status_code != 200:
        raise _erro_google(r)
    return r.json() or {}


def recentes(base: str, conta: str, forcar: bool = False, n: int = 25) -> Dict[str, Any]:
    """Os últimos vídeos do canal (inclusive os agendados e os privados — a conta é a dona), com views/likes/comentários.
    Guarda por 30 min (cada busca custa ~3 unidades da cota)."""
    c = _ler_recentes(base, conta)
    if c and not forcar and time.time() - c.get("buscado", 0) < RECENTES_TTL:
        return c
    ch = (_get(base, conta, URL_CANAIS, {"part": "contentDetails,statistics", "mine": "true"}).get("items") or [{}])[0]
    up = ((ch.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
    vids: List[Dict[str, Any]] = []
    if up:
        pl = _get(base, conta, "https://www.googleapis.com/youtube/v3/playlistItems",
                  {"part": "contentDetails", "playlistId": up, "maxResults": min(50, n)})
        ids = [i["contentDetails"]["videoId"] for i in pl.get("items") or [] if (i.get("contentDetails") or {}).get("videoId")]
        if ids:
            vs = _get(base, conta, "https://www.googleapis.com/youtube/v3/videos",
                      {"part": "snippet,statistics,status,contentDetails", "id": ",".join(ids), "maxResults": 50})
            for v in vs.get("items") or []:
                sn, st, stt = v.get("snippet") or {}, v.get("statistics") or {}, v.get("status") or {}
                agendado = _iso_ts(stt.get("publishAt"))
                pub = _iso_ts(sn.get("publishedAt"))
                vids.append({"id": v["id"], "titulo": sn.get("title") or "", "publicado": pub, "agendado": agendado,
                             "quando": agendado if agendado > time.time() else pub,
                             "privacidade": stt.get("privacyStatus") or "", "views": int(st.get("viewCount") or 0),
                             "likes": int(st.get("likeCount") or 0), "comentarios": int(st.get("commentCount") or 0),
                             "duracao": _duracao((v.get("contentDetails") or {}).get("duration") or ""),
                             "tags": (sn.get("tags") or [])[:15]})
    vids.sort(key=lambda v: v["quando"], reverse=True)
    est = ch.get("statistics") or {}
    out = {"buscado": time.time(), "videos": vids, "inscritos": int(est.get("subscriberCount") or 0),
           "total_videos": int(est.get("videoCount") or 0), "dicas": dicas(vids)}
    with _TRAVA:
        _gravar(base, os.path.join("recentes", conta + ".json"), out)
    return out


def dicas(vids: List[Dict[str, Any]], agora: Optional[float] = None) -> Dict[str, Any]:
    """O que dá pra tirar dos últimos vídeos: os que mais deram view, os horários deles e a média."""
    agora = agora or time.time()
    saidos = [v for v in vids if v["privacidade"] == "public" and v["publicado"] and agora - v["publicado"] > 6 * 3600]
    if not saidos:
        return {}
    media = sum(v["views"] for v in saidos) / len(saidos)
    top = sorted(saidos, key=lambda v: v["views"], reverse=True)[:5]
    horas: Dict[int, List[int]] = {}
    for v in saidos:
        horas.setdefault(time.localtime(v["publicado"]).tm_hour, []).append(v["views"])
    melhores_horas = sorted(horas, key=lambda h: sum(horas[h]) / len(horas[h]), reverse=True)[:3]
    return {"media_views": round(media), "top": [{"titulo": v["titulo"], "views": v["views"], "id": v["id"]} for v in top],
            "melhores_horas": [f"{h:02d}:00" for h in melhores_horas], "n": len(saidos),
            "ultimo": max(v["publicado"] for v in saidos)}


def contexto_titulos(base: str, canal_id: str) -> str:
    """Pra IA dos títulos: os que funcionaram no canal (só do que já está guardado — não busca na rede)."""
    a = agenda(base, canal_id)
    if not a or not a["conta"]:
        return ""
    r = _ler_recentes(base, a["conta"])
    d = r.get("dicas") or {}
    if not d.get("top"):
        return ""
    acima = [t for t in d["top"] if t["views"] > d["media_views"]] or d["top"][:2]
    ultimos = [v["titulo"] for v in (r.get("videos") or [])[:8]]
    return ("\nTHIS CHANNEL'S RECENT TITLES THAT PERFORMED BEST (views; channel average "
            f"{d['media_views']}):\n" + "\n".join(f"- {t['titulo']} ({t['views']} views)" for t in acima[:5])
            + "\nMatch what made these work (length, wording, curiosity), adapted to THIS video — never copy them."
            + ("\nAlready used recently (do NOT repeat or paraphrase): " + " | ".join(ultimos) if ultimos else ""))


def resumo(base: str, agora: Optional[float] = None) -> Dict[str, Any]:
    agora = agora or time.time()
    cs = contas(base)
    return {"tem_cliente": bool(cliente(base)), "tipo_cliente": cliente(base).get("tipo") or "",
            "contas": [{"id": k, "titulo": v.get("titulo") or k, "recentes": _ler_recentes(base, k), "pausada_ate": v.get("pausada_ate", 0) if v.get("pausada_ate", 0) > agora else 0,
                        "motivo": v.get("motivo") or ""} for k, v in cs.items()],
            "agendas": config(base)["canais"],
            "fila": sorted(fila(base), key=lambda x: (x["estado"] not in ESTADOS_ATIVOS, x["quando"] if x["estado"] in ESTADOS_ATIVOS else -x["quando"]))}


# ------------------------------------------------------------------ rotas
def registrar(app: Any, base_dir: str, meta_de: Callable[[str], Optional[Dict[str, Any]]],
              item_de: Callable[[str], Optional[Dict[str, Any]]], canais: Callable[[], List[Dict[str, Any]]],
              com_worker: Optional[bool] = None) -> None:
    """meta_de(pid) → {titulo, descricao, hashtags, video, thumb}; item_de(pid) → {pid, canal_id, canal, nome, pronto}."""
    from flask import jsonify, redirect, render_template, request

    if com_worker is None:
        com_worker = not os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("BESTEDITOR_YT_WORKER", "1") != "0"
    if com_worker:
        iniciar_worker(base_dir, meta_de)

    def _redir() -> str:
        return request.host_url.rstrip("/") + "/youtube/oauth"

    def _erro(e: Exception, cod: int = 400):
        return jsonify({"ok": False, "erro": str(e)}), cod

    @app.route("/youtube", methods=["GET"])
    def youtube_pagina():
        return render_template("youtube_envio.html", redirect_uri=_redir(),
                               canais=[{"id": c.get("id"), "nome": c.get("nome") or c.get("id")} for c in canais()])

    @app.route("/youtube/estado", methods=["GET"])
    def youtube_estado():
        return jsonify(dict(resumo(base_dir), ok=True))

    @app.route("/youtube/cliente", methods=["POST"])
    def youtube_cliente():
        f = request.files.get("arquivo")
        texto = f.read().decode("utf-8", "replace") if f else str((request.get_json(silent=True) or {}).get("json") or "")
        try:
            c = salvar_cliente(base_dir, texto)
        except YtErro as e:
            return _erro(e)
        return jsonify({"ok": True, "tipo": c["tipo"]})

    @app.route("/youtube/conectar", methods=["GET"])
    def youtube_conectar():
        try:
            return redirect(url_conectar(base_dir, _redir()))
        except YtErro as e:
            return redirect("/youtube?erro=" + str(e))

    @app.route("/youtube/oauth", methods=["GET"])
    def youtube_oauth():
        from urllib.parse import quote
        if request.args.get("error"):
            return redirect("/youtube?erro=" + quote("O Google recusou: " + request.args["error"]))
        try:
            ct = concluir_conexao(base_dir, request.args.get("code") or "", request.args.get("state") or "", _redir())
        except YtErro as e:
            return redirect("/youtube?erro=" + quote(str(e)))
        return redirect("/youtube?ok=" + quote(f"✅ conectado: {ct['titulo']}"))

    @app.route("/youtube/contas/<cid>/desconectar", methods=["POST"])
    def youtube_desconectar(cid: str):
        desconectar(base_dir, cid)
        return jsonify(dict(resumo(base_dir), ok=True))

    @app.route("/youtube/agenda/<canal_id>", methods=["POST"])
    def youtube_agenda(canal_id: str):
        b = request.get_json(silent=True) or {}
        a = salvar_agenda(base_dir, canal_id, b)
        n = reagendar(base_dir, canal_id) if b.get("reagendar") else 0
        return jsonify(dict(resumo(base_dir), ok=True, agenda=a, reagendados=n))

    @app.route("/youtube/fila/adicionar", methods=["POST"])
    def youtube_fila_adicionar():
        b = request.get_json(silent=True) or {}
        itens, pulados = [], []
        for pid in b.get("ids") or []:
            it = item_de(str(pid))
            if not it:
                pulados.append(f"{pid}: não achei esse vídeo")
            elif not it.get("pronto"):
                pulados.append(f"{it.get('nome') or pid}: ainda não tem o vídeo pronto")
            else:
                itens.append(it)
        novos, p2 = adicionar(base_dir, itens, agora_ja=bool(b.get("agora")))
        if com_worker:
            iniciar_worker(base_dir, meta_de)
        return jsonify({"ok": True, "novos": [{"nome": x["nome"], "quando": x["quando"], "canal": x["canal"]} for x in novos],
                        "pulados": pulados + p2})

    @app.route("/youtube/recentes/<conta>", methods=["POST"])
    def youtube_recentes(conta: str):
        if conta not in contas(base_dir):
            return _erro(YtErro("Conta não conectada."), 404)
        try:
            r = recentes(base_dir, conta, forcar=True)
        except YtErro as e:
            return _erro(e)
        return jsonify(dict(resumo(base_dir), ok=True, n=len(r["videos"])))

    @app.route("/youtube/fila/<iid>/<qual>", methods=["POST"])
    def youtube_fila_acao(iid: str, qual: str):
        try:
            acao(base_dir, iid, qual)
        except YtErro as e:
            return _erro(e)
        return jsonify(dict(resumo(base_dir), ok=True))
