"""
api_keys.py
============

Duas coisas pequenas e genéricas (não específicas do Pexels, dá pra
reusar pra qualquer provedor que tenha API com chave e rate limit):

1) `load_dotenv(path=".env")` — carrega variáveis de um arquivo `.env`
   pro `os.environ`, sem precisar da biblioteca `python-dotenv`. Só
   preenche variáveis que ainda não existem no ambiente (uma variável já
   exportada no shell sempre tem prioridade sobre o `.env`).

2) `APIKeyPool` — guarda uma ou mais chaves de API e rotaciona
   automaticamente pra próxima quando uma bate rate limit (HTTP 429, ou
   você chama `pool.mark_rate_limited()` manualmente). Chaves que
   bateram rate limit voltam a ficar disponíveis depois de um tempo
   (`cooldown_seconds`), caso a rotação dê a volta completa e precise
   reusar alguma.

Uso
---
    # no .env:
    #   PEXELS_API_KEYS=chave_um,chave_dois,chave_tres

    from api_keys import load_dotenv, APIKeyPool

    load_dotenv()  # lê o .env pro os.environ, se existir
    pool = APIKeyPool.from_env("PEXELS_API_KEYS")

    key = pool.current_key()
    # ... faz a requisição usando `key` ...
    if resposta.status_code == 429:
        pool.mark_rate_limited(key)
        key = pool.current_key()  # já é a próxima chave disponível
"""

from __future__ import annotations

import os
import time
from typing import Dict, List, Optional


def load_dotenv(path: str = ".env") -> Dict[str, str]:
    """Lê um arquivo `.env` simples (KEY=VALUE por linha, `#` para
    comentário, aspas opcionais) e preenche `os.environ` com o que ainda
    não estiver definido lá. Não falha se o arquivo não existir.

    Retorna um dict com o que foi lido do arquivo (mesmo que já existisse
    no ambiente e não tenha sido sobrescrito) — útil pra depuração.
    """
    values: Dict[str, str] = {}
    if not os.path.exists(path):
        return values

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            values[key] = value
            os.environ.setdefault(key, value)

    return values


class NoAvailableAPIKeyError(Exception):
    """Todas as chaves do pool estão em rate limit no momento."""


class APIKeyPool:
    def __init__(self, keys: List[str], cooldown_seconds: int = 3600):
        """
        keys: lista de chaves de API (ordem de uso — a primeira é usada
              primeiro). Chaves em branco/duplicadas são ignoradas.
        cooldown_seconds: quanto tempo uma chave marcada como "rate
              limited" fica de fora da rotação antes de poder ser
              reutilizada (padrão: 1 hora, o período comum de rate limit
              da API do Pexels).
        """
        seen = set()
        self._keys: List[str] = []
        for k in keys:
            k = (k or "").strip()
            if k and k not in seen:
                seen.add(k)
                self._keys.append(k)

        if not self._keys:
            raise ValueError(
                "Nenhuma chave de API fornecida. Configure PEXELS_API_KEYS no .env "
                "(uma ou mais chaves separadas por vírgula)."
            )

        self._cooldown_seconds = cooldown_seconds
        self._index = 0
        self._blocked_until: Dict[str, float] = {}

    @classmethod
    def from_env(cls, env_var: str, cooldown_seconds: int = 3600) -> "APIKeyPool":
        """Constrói o pool a partir de uma variável de ambiente com
        chaves separadas por vírgula (ex: "chave1,chave2,chave3").
        """
        raw = os.environ.get(env_var, "")
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if not keys:
            raise ValueError(
                f"A variável de ambiente {env_var} não está definida ou está vazia. "
                f"Coloque no seu .env: {env_var}=sua_chave_aqui (ou várias, separadas por vírgula)."
            )
        return cls(keys, cooldown_seconds=cooldown_seconds)

    def __len__(self) -> int:
        return len(self._keys)

    def _is_available(self, key: str, now: float) -> bool:
        return self._blocked_until.get(key, 0) <= now

    def current_key(self) -> str:
        """Devolve a chave atual, pulando automaticamente qualquer chave
        que ainda esteja em cooldown por rate limit. Levanta
        NoAvailableAPIKeyError se TODAS as chaves estiverem bloqueadas
        no momento (nesse caso, `earliest_retry_in()` diz quanto esperar).
        """
        now = time.time()
        for offset in range(len(self._keys)):
            idx = (self._index + offset) % len(self._keys)
            if self._is_available(self._keys[idx], now):
                self._index = idx
                return self._keys[idx]
        raise NoAvailableAPIKeyError(
            f"Todas as {len(self._keys)} chave(s) estão em rate limit no momento. "
            f"Tente novamente em ~{int(self.earliest_retry_in())}s, ou adicione mais chaves no .env."
        )

    def mark_rate_limited(self, key: str, retry_after_seconds: Optional[float] = None) -> Optional[str]:
        """Marca `key` como bloqueada (rate limit) e devolve a próxima
        chave disponível (já rotacionada), ou None se essa marcação
        deixou TODAS as chaves bloqueadas (nesse caso, chame
        `current_key()` quando quiser — ele levanta o erro explicando
        quanto falta esperar).

        `retry_after_seconds`, se fornecido (ex: vindo do header
        `Retry-After`), é usado no lugar do cooldown padrão.
        """
        self._blocked_until[key] = time.time() + (retry_after_seconds or self._cooldown_seconds)
        if key in self._keys:
            self._index = (self._keys.index(key) + 1) % len(self._keys)
        try:
            return self.current_key()
        except NoAvailableAPIKeyError:
            return None

    def earliest_retry_in(self) -> float:
        """Segundos até a chave mais próxima de sair do cooldown ficar
        disponível de novo. 0 se já tem alguma disponível agora.
        """
        now = time.time()
        if any(self._is_available(k, now) for k in self._keys):
            return 0.0
        return max(0.0, min(self._blocked_until.get(k, 0) for k in self._keys) - now)

    def available_count(self) -> int:
        now = time.time()
        return sum(1 for k in self._keys if self._is_available(k, now))
