"""
Teste offline de api_keys.py: rotação de chaves em rate limit, cooldown,
e o carregador simples de .env.
"""
import os
import time

from api_keys import APIKeyPool, NoAvailableAPIKeyError, load_dotenv


def test_rotates_to_next_key_on_rate_limit():
    pool = APIKeyPool(["k1", "k2", "k3"], cooldown_seconds=10)
    assert pool.current_key() == "k1"
    assert pool.mark_rate_limited("k1") == "k2"
    assert pool.current_key() == "k2"
    assert pool.mark_rate_limited("k2") == "k3"
    print("OK: rotaciona para a próxima chave disponível quando a atual bate rate limit.")


def test_mark_rate_limited_does_not_raise_when_all_exhausted():
    pool = APIKeyPool(["a", "b"], cooldown_seconds=100)
    assert pool.mark_rate_limited("a") == "b"
    result = pool.mark_rate_limited("b")
    assert result is None, "mark_rate_limited não deve propagar erro; deve devolver None"
    try:
        pool.current_key()
        raise AssertionError("deveria ter levantado NoAvailableAPIKeyError")
    except NoAvailableAPIKeyError:
        pass
    print("OK: mark_rate_limited nunca lança exceção; current_key() lança quando chamado explicitamente sem chaves.")


def test_key_becomes_available_again_after_cooldown():
    pool = APIKeyPool(["x", "y"], cooldown_seconds=0.2)
    pool.mark_rate_limited("x")
    assert pool.current_key() == "y"
    time.sleep(0.3)
    assert pool.available_count() == 2
    print("OK: uma chave volta a ficar disponível depois que o cooldown expira.")


def test_ignores_blank_and_duplicate_keys():
    pool = APIKeyPool(["a", "", "a", "  ", "b"])
    assert len(pool) == 2
    print("OK: ignora chaves vazias/só-espaço e duplicadas.")


def test_raises_clear_error_with_no_keys():
    try:
        APIKeyPool([])
        raise AssertionError("deveria ter levantado ValueError")
    except ValueError:
        pass
    print("OK: erro claro quando nenhuma chave é fornecida.")


def test_load_dotenv_fills_environ_and_respects_existing_vars(tmp_path="/tmp/_test_api_keys_dotenv"):
    os.makedirs(tmp_path, exist_ok=True)
    dotenv_path = os.path.join(tmp_path, ".env")
    with open(dotenv_path, "w", encoding="utf-8") as f:
        f.write('# comentário\nPEXELS_API_KEYS=chaveA,chaveB\nOUTRA_VAR="valor com espaço"\n\n')

    for k in ("PEXELS_API_KEYS", "OUTRA_VAR"):
        os.environ.pop(k, None)
    load_dotenv(dotenv_path)
    assert os.environ["PEXELS_API_KEYS"] == "chaveA,chaveB"
    assert os.environ["OUTRA_VAR"] == "valor com espaço"
    print("OK: load_dotenv lê o arquivo, preenche os.environ e remove aspas.")

    os.environ["PEXELS_API_KEYS"] = "ja_definida_no_shell"
    load_dotenv(dotenv_path)
    assert os.environ["PEXELS_API_KEYS"] == "ja_definida_no_shell"
    print("OK: uma variável já definida no ambiente tem prioridade sobre o .env.")

    os.environ.pop("PEXELS_API_KEYS", None)
    os.environ.pop("OUTRA_VAR", None)


def test_from_env_builds_pool():
    os.environ["PEXELS_API_KEYS"] = "k1,k2, k3 ,"
    pool = APIKeyPool.from_env("PEXELS_API_KEYS")
    assert len(pool) == 3
    print("OK: from_env constrói o pool a partir da variável de ambiente.")
    os.environ.pop("PEXELS_API_KEYS", None)


if __name__ == "__main__":
    test_rotates_to_next_key_on_rate_limit()
    test_mark_rate_limited_does_not_raise_when_all_exhausted()
    test_key_becomes_available_again_after_cooldown()
    test_ignores_blank_and_duplicate_keys()
    test_raises_clear_error_with_no_keys()
    test_load_dotenv_fills_environ_and_respects_existing_vars()
    test_from_env_builds_pool()
    print("\nTodos os testes de api_keys.py passaram.")
