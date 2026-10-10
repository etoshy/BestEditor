"""
Teste do fix: `ClientFactory.get_photo_client` passa `headless` correto
(derivado de `browser_visible` na config do site) pros 4 buscadores de
imagem por navegador (bing/brave/yandex/startpage) -- igual já fazia
pro Google Flow. Gap real que existia antes desse fix: esses 4 clientes
eram sempre instanciados com `headless=True` fixo, ignorando a config
"Ocultar o navegador" (que promete afetar "TODOS os processos").
"""
import sys
import types

import pytest

import video_assembler as va


class _FakeBuscadorClient:
    """Substitui qualquer um dos 4 clientes de buscador -- só registra
    com qual `headless` foi instanciado."""
    instancias = []

    def __init__(self, headless=True):
        self.headless = headless
        _FakeBuscadorClient.instancias.append(self)


@pytest.fixture(autouse=True)
def limpar_instancias():
    _FakeBuscadorClient.instancias = []
    yield
    _FakeBuscadorClient.instancias = []


def _instalar_fake_para(monkeypatch, provider):
    nome_modulo = f"_fake_modulo_{provider}"
    mod = types.ModuleType(nome_modulo)
    mod.FakeClient = _FakeBuscadorClient
    monkeypatch.setitem(sys.modules, nome_modulo, mod)
    monkeypatch.setitem(va._PHOTO_PROVIDER_MODULES, provider, (nome_modulo, "FakeClient"))


@pytest.mark.parametrize("provider", ["bing", "brave", "yandex", "startpage"])
def test_headless_true_quando_browser_visible_false(monkeypatch, provider):
    _instalar_fake_para(monkeypatch, provider)
    factory = va.ClientFactory({"browser_visible": False})
    factory.get_photo_client(provider)
    assert _FakeBuscadorClient.instancias[0].headless is True


@pytest.mark.parametrize("provider", ["bing", "brave", "yandex", "startpage"])
def test_headless_false_quando_browser_visible_true(monkeypatch, provider):
    _instalar_fake_para(monkeypatch, provider)
    factory = va.ClientFactory({"browser_visible": True})
    factory.get_photo_client(provider)
    assert _FakeBuscadorClient.instancias[0].headless is False


def test_headless_true_por_padrao_quando_config_nao_tem_a_chave(monkeypatch):
    _instalar_fake_para(monkeypatch, "bing")
    factory = va.ClientFactory({})  # sem "browser_visible" nenhum na config
    factory.get_photo_client("bing")
    assert _FakeBuscadorClient.instancias[0].headless is True
