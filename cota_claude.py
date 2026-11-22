"""🟠 v84_450 — quanto ainda dá pra usar da sua ASSINATURA do Claude (a "banda" do Claude Code): o limite de 5 horas e o
da semana (geral e só do Opus), em %, e quando cada um zera.

De onde vem: o mesmo pedido que o Claude Code faz pro /usage — https://api.anthropic.com/api/oauth/usage, com o token de
login que o Claude Code guarda em ~/.claude/.credentials.json (no Windows: C:\\Users\\<você>\\.claude\\.credentials.json).
Não é uma API documentada pela Anthropic: se um dia mudar, a página só mostra "não consegui ler a cota" — nada quebra.
O token só é lido e usado nesse pedido; o site não guarda nem mostra ele.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

URL = "https://api.anthropic.com/api/oauth/usage"
_TRAVA = threading.Lock()
_CACHE: Dict[str, Any] = {"quando": 0.0, "v": None}
CACHE_S = 60  # não pergunta mais que 1x por minuto

NOMES = {"five_hour": "⏱ Limite de 5 horas", "seven_day": "📅 Semana (tudo)", "seven_day_opus": "📅 Semana (só Opus)",
         "seven_day_sonnet": "📅 Semana (só Sonnet)"}


def _arquivo_credenciais() -> str:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, ".credentials.json")


def _token() -> Optional[Dict[str, Any]]:
    try:
        with open(_arquivo_credenciais(), encoding="utf-8") as f:
            d = json.load(f) or {}
    except (OSError, ValueError):
        return None
    o = d.get("claudeAiOauth") if isinstance(d, dict) else None
    if not isinstance(o, dict) or not o.get("accessToken"):
        return None
    return o


def _janela(x: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(x, dict) or x.get("utilization") is None:
        return None
    try:
        usado = max(0.0, min(100.0, float(x["utilization"])))
    except (TypeError, ValueError):
        return None
    return {"usado": round(usado, 1), "livre": round(100 - usado, 1), "zera_em": str(x.get("resets_at") or "")}


def ler(forcar: bool = False, _abrir=None) -> Dict[str, Any]:
    """{"ok", "janelas": [{"chave","nome","usado","livre","zera_em"}], "plano", "erro"}."""
    with _TRAVA:
        if not forcar and _CACHE["v"] is not None and time.time() - _CACHE["quando"] < CACHE_S:
            return _CACHE["v"]
    tok = _token()
    if not tok:
        v = {"ok": False, "erro": "não achei o login do Claude Code neste PC — instale (npm install -g @anthropic-ai/claude-code) "
                                  "e rode claude uma vez pra entrar com a conta da assinatura"}
    elif tok.get("expiresAt") and float(tok["expiresAt"]) / 1000 < time.time():
        v = {"ok": False, "erro": "o login do Claude Code venceu — use o Claude Code uma vez (ou gere algo pela assinatura) "
                                  "que ele renova sozinho"}
    else:
        req = urllib.request.Request(URL, headers={"Authorization": "Bearer " + tok["accessToken"],
                                                   "anthropic-beta": "oauth-2025-04-20", "Accept": "application/json",
                                                   "User-Agent": "BestEditor"})
        try:
            with (_abrir or urllib.request.urlopen)(req, timeout=15) as r:
                d = json.loads(r.read().decode("utf-8", "replace") or "{}")
            jan = []
            for k, nome in NOMES.items():
                j = _janela(d.get(k))
                if j:
                    jan.append(dict(j, chave=k, nome=nome))
            v = {"ok": bool(jan), "janelas": jan, "plano": str(tok.get("subscriptionType") or ""),
                 **({} if jan else {"erro": "a resposta veio sem os limites (a Anthropic pode ter mudado o formato)"})}
        except urllib.error.HTTPError as exc:
            v = {"ok": False, "erro": f"a Anthropic recusou ({exc.code}) — rode claude uma vez pra renovar o login"
                 if exc.code in (401, 403) else f"não consegui ler a cota ({exc.code})"}
        except Exception as exc:  # noqa: BLE001
            v = {"ok": False, "erro": f"não consegui ler a cota: {exc}"[:200]}
    v["quando"] = time.time()
    with _TRAVA:
        _CACHE.update(quando=time.time(), v=v)
    return v
