"""
Teste automatizado de `_run_with_timeout()` — o mecanismo por trás de
"se um banco demorar muito, desiste e usa outro". Cobre especificamente
uma revisão feita depois da primeira implementação: threads de um
`ThreadPoolExecutor` NÃO são daemon por padrão — se um provedor
travasse de verdade (nunca retorna), a thread abandonada ficaria viva
pra sempre, o que poderia impedir um servidor rodando por muito tempo
de encerrar de forma limpa. A implementação final usa uma thread
`daemon=True` própria por chamada em vez de um pool compartilhado.
"""
import threading
import time

import pytest

from video_assembler import _run_with_timeout


class TestRunWithTimeout:
    def test_raises_timeout_error_when_function_takes_too_long(self):
        def travada():
            time.sleep(10)
            return "nunca chega aqui"

        t0 = time.time()
        with pytest.raises(TimeoutError, match="1s"):
            _run_with_timeout(travada, 1)
        elapsed = time.time() - t0
        assert elapsed < 2, "deveria ter desistido perto do prazo pedido, não esperado a função inteira"

    def test_abandoned_thread_is_daemon_and_does_not_block_process_exit(self):
        """A checagem mais importante desta revisão: a thread abandonada
        precisa ser daemon, senão prenderia o processo pra sempre se o
        provedor realmente nunca responder."""
        def travada():
            time.sleep(5)

        try:
            _run_with_timeout(travada, 0.3)
        except TimeoutError:
            pass

        time.sleep(0.1)
        alive_non_main = [
            t for t in threading.enumerate()
            if t is not threading.current_thread() and t.is_alive() and "_worker" in t.name
        ]
        assert alive_non_main, "esperava encontrar a thread abandonada ainda viva pra checar"
        for t in alive_non_main:
            assert t.daemon is True, f"thread abandonada {t.name} não é daemon — prenderia o processo"

    def test_propagates_real_exceptions_not_just_timeouts(self):
        def levanta_erro():
            raise ValueError("erro de verdade, não timeout")

        with pytest.raises(ValueError, match="erro de verdade"):
            _run_with_timeout(levanta_erro, 5)

    def test_returns_result_normally_when_fast_enough(self):
        def funciona_rapido():
            return "resultado de verdade"

        assert _run_with_timeout(funciona_rapido, 5) == "resultado de verdade"

    def test_many_sequential_calls_do_not_exhaust_any_shared_pool(self):
        """Confirma que chamadas repetidas (simulando muitos segmentos
        ao longo de vários jobs) não dependem de um pool compartilhado
        de tamanho fixo que poderia se esgotar."""
        def rapido():
            return "ok"

        for _ in range(50):
            assert _run_with_timeout(rapido, 2) == "ok"
