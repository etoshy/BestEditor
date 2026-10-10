"""
Teste automatizado de `ChromeSession.download()` — resolve um bug real
relatado em produção: o método tenta baixar via `fetch()` + Blob em
JavaScript (pra evitar abrir o player do vídeo), mas isso pode falhar
SILENCIOSAMENTE por CORS (CDNs de vídeo normalmente não enviam os
headers que permitiriam ler a resposta via JS de outra origem). Sem
checar o resultado dessa tentativa, o código ficava esperando um
arquivo aparecer no disco pelo timeout inteiro, mesmo que o download
nunca tivesse começado de verdade — daí o erro real relatado:
"Chrome não concluiu o download: ...".
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest

import browser_session


@pytest.fixture
def temp_download_setup():
    work_dir = tempfile.mkdtemp()
    download_dir = os.path.join(work_dir, "downloads")
    os.makedirs(download_dir)
    dest = os.path.join(work_dir, "saida.mp4")
    yield download_dir, dest
    shutil.rmtree(work_dir, ignore_errors=True)


def _bare_session(download_dir):
    session = browser_session.ChromeSession.__new__(browser_session.ChromeSession)
    session.download_dir = Path(download_dir)
    return session


class TestDownloadFallbackOnBlobFailure:
    def test_falls_back_to_simple_click_when_blob_fetch_fails(self, temp_download_setup):
        download_dir, dest = temp_download_setup
        session = _bare_session(download_dir)

        calls = []

        class FakeDriver:
            def execute_script(self, script, *args):
                is_fallback = "a.click()" in script and "objectUrl" not in script
                calls.append("fallback" if is_fallback else "outro")
                if is_fallback:
                    with open(os.path.join(download_dir, "video_baixado.mp4"), "wb") as f:
                        f.write(b"conteudo de video fake" * 100)

            def execute_async_script(self, script, *args):
                calls.append("blob_fetch")
                return {"ok": False, "error": "TypeError: Failed to fetch (CORS)"}

        session.driver = FakeDriver()
        path = session.download(url="https://cdn.exemplo.com/video.mp4", destination=dest, timeout=5)

        assert os.path.exists(path)
        assert "blob_fetch" in calls
        assert "fallback" in calls

    def test_uses_blob_result_directly_when_it_succeeds(self, temp_download_setup):
        """Quando o fetch()+Blob funciona (caso comum, sem CORS
        bloqueando), o fallback de clique simples NÃO deveria ser
        chamado — só entra em ação quando o primeiro método falha."""
        download_dir, dest = temp_download_setup
        session = _bare_session(download_dir)

        calls = []

        class FakeDriver:
            def execute_script(self, script, *args):
                calls.append("execute_script")

            def execute_async_script(self, script, *args):
                calls.append("blob_fetch")
                with open(os.path.join(download_dir, "video_baixado.mp4"), "wb") as f:
                    f.write(b"conteudo de video fake" * 100)
                return {"ok": True, "size": 2300}

        session.driver = FakeDriver()
        path = session.download(url="https://cdn.exemplo.com/video.mp4", destination=dest, timeout=5)

        assert os.path.exists(path)
        # só a chamada de "documento ativo" + o fetch async -- nenhum
        # execute_script extra de fallback
        assert calls.count("execute_script") == 1
        assert calls.count("blob_fetch") == 1

    def test_raises_clear_error_mentioning_cors_when_both_methods_fail(self, temp_download_setup):
        download_dir, dest = temp_download_setup
        session = _bare_session(download_dir)

        class FakeDriverBothFail:
            def execute_script(self, script, *args):
                pass  # não baixa nada de verdade

            def execute_async_script(self, script, *args):
                return {"ok": False, "error": "TypeError: Failed to fetch (CORS)"}

        session.driver = FakeDriverBothFail()

        with pytest.raises(TimeoutError, match="CORS"):
            session.download(url="https://cdn.exemplo.com/video.mp4", destination=dest, timeout=2)

    def test_raises_generic_timeout_when_no_blob_result_available(self, temp_download_setup):
        """Se o `execute_async_script` levantar exceção (não apenas
        devolver ok:False), ainda cai pro fallback normalmente, sem
        quebrar com um erro do tipo errado."""
        download_dir, dest = temp_download_setup
        session = _bare_session(download_dir)

        class FakeDriverAsyncRaises:
            def execute_script(self, script, *args):
                pass

            def execute_async_script(self, script, *args):
                raise Exception("javascript error: algo quebrou")

        session.driver = FakeDriverAsyncRaises()

        with pytest.raises(TimeoutError):
            session.download(url="https://cdn.exemplo.com/video.mp4", destination=dest, timeout=2)
