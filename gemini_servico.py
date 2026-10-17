"""
🔷 Gemini com a busca do Google (v84_162) — usado na 🌐 checagem na internet
(cronologia, alegações e repetições): manda o prompt das inconsistências pro
Gemini com "Grounding with Google Search" ligado e devolve o texto (o JSON das
correções) + as fontes que ele consultou.

Chave: Google AI Studio (aistudio.google.com → Get API key). Fica em
gemini_config.json (fora do Git); o uso fica em gemini_uso.json.

Modelos: gemini-2.5-flash / gemini-2.5-flash-lite (o Google só libera os 2.5
pra quem já usou antes) — se a chave não tiver acesso, cai sozinho no
gemini-3.5-flash-lite, que é o indicado pra chave nova.
Os custos mostrados são ESTIMATIVAS (preço de tabela); o valor real fica no
painel de cobrança do Google.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

_AQUI = os.path.dirname(os.path.abspath(__file__))
_DADOS = os.environ.get("GEMINI_DADOS_DIR") or os.environ.get("IA_DADOS_DIR") or _AQUI
CONFIG_PATH = os.path.join(_DADOS, "gemini_config.json")
USO_PATH = os.path.join(_DADOS, "gemini_uso.json")
API = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
AI_STUDIO = "https://aistudio.google.com/apikey"
CONSOLE = "https://aistudio.google.com/usage"
_TRAVA = threading.Lock()

# preço de tabela em US$ por 1 milhão de tokens + a busca do Google (grátis até a cota)
MODELOS: Dict[str, Dict[str, Any]] = {
    "gemini-2.5-flash": {"nome": "Gemini 2.5 Flash (o melhor custo-benefício pra checar)", "entrada": 0.30, "saida": 2.50,
                         "busca_gratis": 1500, "busca_periodo": "dia", "busca_usd_mil": 35.0, "familia": "2.5"},
    "gemini-2.5-flash-lite": {"nome": "Gemini 2.5 Flash-Lite (mais barato, um pouco menos cuidadoso)", "entrada": 0.10, "saida": 0.40,
                              "busca_gratis": 1500, "busca_periodo": "dia", "busca_usd_mil": 35.0, "familia": "2.5"},
    "gemini-3.5-flash-lite": {"nome": "Gemini 3.5 Flash-Lite (o indicado pra chave nova)", "entrada": 0.30, "saida": 2.50,
                              "busca_gratis": 5000, "busca_periodo": "mês", "busca_usd_mil": 14.0, "familia": "3"},
}
RESERVA = "gemini-3.5-flash-lite"  # se a chave não tiver acesso aos 2.5
PADRAO: Dict[str, Any] = {"chave": "", "modelo": "gemini-2.5-flash", "sem_acesso": []}


class GeminiErro(Exception):
    pass


# ------------------------------------------------------------------ config
def _ler(caminho: str, padrao: Any) -> Any:
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def _gravar(caminho: str, dados: Any) -> None:
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def config() -> Dict[str, Any]:
    c = dict(PADRAO)
    salvo = _ler(CONFIG_PATH, {})
    if isinstance(salvo, dict):
        c.update({k: v for k, v in salvo.items() if k in PADRAO})
    if c["modelo"] not in MODELOS:
        c["modelo"] = PADRAO["modelo"]
    if not isinstance(c.get("sem_acesso"), list):
        c["sem_acesso"] = []
    return c


def chave(c: Optional[Dict[str, Any]] = None) -> str:
    c = c or config()
    return (c.get("chave") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def limpar_chave(v: Any) -> str:
    """Tira o que costuma vir junto ao colar: espaços/quebras de linha, aspas, "GEMINI_API_KEY=" e "key=".
    Os formatos de chave do Google mudam (AIza…, AQ.…), então aceita qualquer texto sem espaço de 20+ caracteres."""
    k = re.sub(r"\s+", "", str(v or ""))
    k = re.sub(r"^(?:export)?(?:GEMINI_API_KEY|GOOGLE_API_KEY|API_KEY|key)[:=]", "", k, flags=re.I)
    return k.strip("\"'`<>")


def salvar_config(novos: Dict[str, Any]) -> Dict[str, Any]:
    with _TRAVA:
        c = config()
        if "chave" in novos and novos["chave"] is not None:
            k = limpar_chave(novos["chave"])
            if k and not re.fullmatch(r"[\x21-\x7e]{20,300}", k):
                raise GeminiErro("Isso não parece uma chave do Gemini — copie de novo em aistudio.google.com/apikey (o botão de copiar ao lado da chave).")
            c["chave"] = k
            c["sem_acesso"] = []  # chave nova: tenta os modelos de novo
        if novos.get("modelo") in MODELOS:
            c["modelo"] = novos["modelo"]
        _gravar(CONFIG_PATH, c)
    return c


def chave_mascarada(c: Optional[Dict[str, Any]] = None) -> str:
    k = chave(c)
    return (k[:6] + "…" + k[-4:]) if len(k) > 12 else ("…" if k else "")


# ------------------------------------------------------------------ uso e custo (estimado)
def _custo(m: Dict[str, Any], entrada: int, saida: int) -> float:
    return (entrada * m["entrada"] + saida * m["saida"]) / 1_000_000


def uso() -> Dict[str, Any]:
    d = _ler(USO_PATH, {})
    if not isinstance(d, dict):
        d = {}
    d.setdefault("usd", 0.0)
    d.setdefault("chamadas", 0)
    d.setdefault("log", [])
    d.setdefault("desde", None)
    return d


def _registrar(modelo: str, entrada: int, saida: int, buscas: int, ok: bool, erro: str = "", rotulo: str = "") -> float:
    m = MODELOS.get(modelo) or MODELOS[PADRAO["modelo"]]
    custo = _custo(m, entrada, saida) if ok else 0.0
    with _TRAVA:
        d = uso()
        d["desde"] = d["desde"] or time.time()
        d["usd"] = round(float(d["usd"]) + custo, 6)
        d["chamadas"] = int(d["chamadas"]) + (1 if ok else 0)
        e = {"quando": round(time.time(), 1), "modelo": modelo, "entrada": entrada, "saida": saida, "buscas": buscas,
             "usd": round(custo, 6), "ok": ok}
        if erro:
            e["erro"] = erro[:200]
        if rotulo:
            e["rotulo"] = rotulo[:120]
        d["log"].append(e)
        del d["log"][:-300]
        try:
            _gravar(USO_PATH, d)
        except OSError:
            pass
    return custo


def _inicio_periodo(periodo: str) -> float:
    t = time.localtime()
    if periodo == "dia":
        return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))


def resumo() -> Dict[str, Any]:
    """Pro painel do 🪙 saldo e pra caixa da checagem."""
    c = config()
    d = uso()
    log = [x for x in d.get("log") or [] if isinstance(x, dict)]
    m = MODELOS[c["modelo"]]
    ini = _inicio_periodo(m["busca_periodo"])
    usadas = sum(1 for x in log if x.get("ok") and float(x.get("quando") or 0) >= ini
                 and (MODELOS.get(x.get("modelo")) or {}).get("familia") == m["familia"])
    return {"tem_chave": bool(chave(c)), "chave": chave_mascarada(c), "modelo": c["modelo"], "modelo_nome": m["nome"],
            "modelos": {k: v["nome"] for k, v in MODELOS.items()}, "sem_acesso": c.get("sem_acesso") or [],
            "gasto_usd": round(float(d.get("usd") or 0), 6), "chamadas": int(d.get("chamadas") or 0),
            "buscas_gratis": m["busca_gratis"], "buscas_periodo": m["busca_periodo"], "buscas_usadas": usadas,
            "ai_studio": AI_STUDIO, "console": CONSOLE, "log": list(reversed(log[-20:]))}


def zerar_uso() -> None:
    with _TRAVA:
        _gravar(USO_PATH, {"usd": 0.0, "chamadas": 0, "log": [], "desde": time.time()})


# ------------------------------------------------------------------ chamada
def _transporte(url: str, corpo: Dict[str, Any], chave_api: str, timeout: float) -> Tuple[int, Dict[str, Any]]:
    import requests
    r = requests.post(url, json=corpo, headers={"x-goog-api-key": chave_api, "Content-Type": "application/json"}, timeout=timeout)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"error": {"message": r.text[:300]}}


def _corpo(prompt: str, modelo: str, com_pensar: bool) -> Dict[str, Any]:
    corpo: Dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],  # 🔎 Grounding with Google Search
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 16000},
    }
    if com_pensar:  # pensar pouco: barato e suficiente pra conferir fatos
        corpo["generationConfig"]["thinkingConfig"] = ({"thinkingBudget": 1024} if modelo.startswith("gemini-2.5")
                                                       else {"thinkingLevel": "low"})
    return corpo


def _sem_acesso(status: int, msg: str) -> bool:
    return status in (403, 404) or bool(re.search(r"not found|not supported|no longer available|not have access|permission", msg, re.I))


def checar(prompt: str, rotulo: str = "", on_log: Callable[[str], None] = lambda _m: None,
           transporte: Optional[Callable[..., Tuple[int, Dict[str, Any]]]] = None, timeout: float = 240.0) -> Dict[str, Any]:
    """Manda o prompt com a busca do Google ligada. Devolve {texto, fontes:[{titulo,url}], buscas:[...], modelo, usd}.
    Se a chave não tiver acesso ao modelo escolhido, tenta o de reserva (e lembra disso)."""
    c = config()
    k = chave(c)
    if not k:
        raise GeminiErro("Falta a chave do Gemini — pegue em aistudio.google.com (Get API key) e cole na caixa da checagem.")
    if not prompt.strip():
        raise GeminiErro("O prompt veio vazio.")
    transporte = transporte or _transporte
    fila = [m for m in [c["modelo"], RESERVA] if m not in (c.get("sem_acesso") or [])] or [RESERVA]
    fila = list(dict.fromkeys(fila))
    ultimo_erro = ""
    for modelo in fila:
        on_log(f"perguntando ao {MODELOS[modelo]['nome'].split(' (')[0]} com a busca do Google…")
        url = API.format(modelo=modelo)
        status, resp = transporte(url, _corpo(prompt, modelo, True), k, timeout)
        msg = str(((resp or {}).get("error") or {}).get("message") or "")
        if status == 400 and re.search(r"thinking", msg, re.I):  # o modelo não aceita o ajuste de pensar: vai sem
            status, resp = transporte(url, _corpo(prompt, modelo, False), k, timeout)
            msg = str(((resp or {}).get("error") or {}).get("message") or "")
        if status == 200:
            return _ler_resposta(resp, modelo, rotulo)
        ultimo_erro = f"{status}: {msg[:300]}"
        _registrar(modelo, 0, 0, 0, False, ultimo_erro, rotulo)
        if status in (400, 401) and re.search(r"api key|API_KEY|invalid", msg, re.I):
            raise GeminiErro("O Google recusou a chave do Gemini (" + msg[:160] + "). Confira se copiou a chave inteira.")
        if status == 429:
            raise GeminiErro("O Gemini disse que passou do limite (" + msg[:200] + "). Espere um pouco ou veja a cota no AI Studio.")
        if _sem_acesso(status, msg) and modelo != RESERVA:
            on_log(f"a chave não tem acesso ao {modelo} — tentando o {RESERVA}…")
            with _TRAVA:
                cc = config()
                cc["sem_acesso"] = sorted(set(cc.get("sem_acesso") or []) | {modelo})
                _gravar(CONFIG_PATH, cc)
            continue
        break
    raise GeminiErro("O Gemini não respondeu: " + ultimo_erro)


def _ler_resposta(resp: Dict[str, Any], modelo: str, rotulo: str) -> Dict[str, Any]:
    cands = resp.get("candidates") or []
    if not cands:
        motivo = ((resp.get("promptFeedback") or {}).get("blockReason") or "sem resposta")
        _registrar(modelo, 0, 0, 0, False, str(motivo), rotulo)
        raise GeminiErro(f"O Gemini não devolveu nada ({motivo}).")
    cand = cands[0]
    partes = (cand.get("content") or {}).get("parts") or []
    texto = "".join(str(p.get("text") or "") for p in partes if not p.get("thought")).strip()
    meta = cand.get("groundingMetadata") or {}
    fontes, vistas = [], set()
    for ch in meta.get("groundingChunks") or []:
        w = ch.get("web") or {}
        u = w.get("uri") or ""
        if u and u not in vistas:
            vistas.add(u)
            fontes.append({"titulo": w.get("title") or u, "url": u})
    buscas = [str(q) for q in meta.get("webSearchQueries") or []]
    um = resp.get("usageMetadata") or {}
    entrada = int(um.get("promptTokenCount") or 0) + int(um.get("toolUsePromptTokenCount") or 0)
    saida = int(um.get("candidatesTokenCount") or 0) + int(um.get("thoughtsTokenCount") or 0)
    if not texto:
        _registrar(modelo, entrada, saida, len(buscas), False, "resposta vazia (" + str(cand.get("finishReason") or "") + ")", rotulo)
        raise GeminiErro("O Gemini respondeu vazio (" + str(cand.get("finishReason") or "?") + ").")
    custo = _registrar(modelo, entrada, saida, len(buscas), True, "", rotulo)
    return {"texto": texto, "fontes": fontes[:30], "buscas": buscas, "modelo": modelo, "usd": round(custo, 6),
            "entrada": entrada, "saida": saida}


def testar() -> Dict[str, Any]:
    """Botão 🔌 Testar: uma pergunta curta com busca."""
    try:
        r = checar("Responda só com o ano, em números: em que ano caiu o Muro de Berlim? Use a busca.", rotulo="teste da chave",
                   timeout=60)
        return {"ok": True, "modelo": r["modelo"], "resposta": r["texto"][:80], "fontes": len(r["fontes"])}
    except GeminiErro as exc:
        return {"ok": False, "erro": str(exc)}
