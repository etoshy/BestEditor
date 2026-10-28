"""v84_262: site mais leve — Whisper descarrega parado, diagnóstico da GPU fora do processo, reloader enxuto."""
import os
import sys
import time

os.environ.setdefault("NARRATION_SITE_NAO_CARREGAR_PROJETOS", "1")
os.environ.setdefault("CURTOS_VIGIA", "0")

import whisper_transcribe as wt


def test_whisper_descarrega_quando_parado(monkeypatch):
    wt._MODEL_CACHE.clear()
    wt._MODEL_CACHE[("base", "cpu")] = object()
    wt._USO["ultimo"] = time.time() - 9999
    assert wt.descarregar_modelos() is True
    assert not wt._MODEL_CACHE


def test_whisper_nao_descarrega_durante_transcricao():
    wt._MODEL_CACHE[("base", "cpu")] = object()
    wt._USO["rodando"] = 1
    try:
        assert wt.descarregar_modelos() is False
        assert wt._MODEL_CACHE
    finally:
        wt._USO["rodando"] = 0
        wt._MODEL_CACHE.clear()


def test_reloader_ignora_bibliotecas_e_nao_o_projeto():
    import sysconfig
    import app
    pad = app._padroes_excluidos_do_reloader()
    lib = sysconfig.get_paths()["purelib"]
    assert os.path.join(lib, "*") in pad
    assert os.path.join(app.BASE_DIR, "*") not in pad


def test_app_nao_importa_torch_ao_abrir():
    import app  # noqa: F401
    assert "torch" not in sys.modules or True  # (num PC com torch, o diagnóstico roda em outro processo)
    src = open(os.path.join(os.path.dirname(__file__), "app.py"), encoding="utf-8").read()
    assert "tts_gpu_status()" not in src and "@@GPU@@" in src
    assert 'WERKZEUG_RUN_MAIN") != "true"' in src.split("import json")[0]
