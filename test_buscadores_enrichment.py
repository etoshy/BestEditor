"""
Teste offline de buscadores_enrichment.py: confirmar termos de verdade
num (ou mais) dos 4 buscadores de imagem por navegador, sem precisar de
navegador/rede de verdade -- injeta módulos falsos em `sys.modules` no
lugar de bing_api_client/brave_api_client/yandex_api_client/
startpage_api_client, mesmo espírito de `test_wikipedia_enrichment.py`.
"""
import sys
import types

import buscadores_enrichment as be


class _FakeImagem:
    def __init__(self, description=""):
        self.description = description


def _fake_client_module(nome_modulo, nome_classe, resultados, chamadas=None):
    """`resultados`: dict termo -> [] (sem resultado) | [descricao, ...]
    (resultados encontrados). `chamadas`, se passado, recebe cada termo
    pesquisado nesse provedor (pra testar quantas vezes/quais termos
    cada provedor foi de fato consultado)."""
    mod = types.ModuleType(nome_modulo)

    class FakeClient:
        def search_photos_all(self, query, max_images=1):
            if chamadas is not None:
                chamadas.append(query)
            descricoes = resultados.get(query) or []
            return [_FakeImagem(description=d) for d in descricoes[:max_images]]

    setattr(mod, nome_classe, FakeClient)
    return mod


def _instalar_fake(monkeypatch, provider, resultados, chamadas=None):
    nome_modulo, nome_classe = be._CLIENTES_BUSCADORES[provider]
    monkeypatch.setitem(sys.modules, nome_modulo, _fake_client_module(nome_modulo, nome_classe, resultados, chamadas))


def test_confirma_termos_com_resultado_e_descarta_sem_resultado(monkeypatch):
    _instalar_fake(monkeypatch, "bing", {
        "Gojo Satoru": ["personagem de anime"],
        "SemResultado": [],
    })
    confirmados = be.buscar_confirmados_nos_buscadores(
        ["Gojo Satoru", "SemResultado"], providers=["bing"],
    )
    termos = [c["termo"] for c in confirmados]
    assert termos == ["Gojo Satoru"]
    assert confirmados[0]["provider"] == "bing"
    assert confirmados[0]["descricao"] == "personagem de anime"


def test_tenta_o_proximo_provedor_quando_o_primeiro_nao_acha(monkeypatch):
    _instalar_fake(monkeypatch, "bing", {"Termo X": []})
    _instalar_fake(monkeypatch, "brave", {"Termo X": ["achou no brave"]})
    confirmados = be.buscar_confirmados_nos_buscadores(
        ["Termo X"], providers=["bing", "brave"],
    )
    assert len(confirmados) == 1
    assert confirmados[0]["provider"] == "brave"


def test_para_no_primeiro_provedor_que_confirma_nao_tenta_os_outros(monkeypatch):
    chamadas_bing, chamadas_brave = [], []
    _instalar_fake(monkeypatch, "bing", {"Termo X": ["achou no bing"]}, chamadas=chamadas_bing)
    _instalar_fake(monkeypatch, "brave", {"Termo X": ["achou no brave também"]}, chamadas=chamadas_brave)
    be.buscar_confirmados_nos_buscadores(["Termo X"], providers=["bing", "brave"])
    assert chamadas_bing == ["Termo X"]
    assert chamadas_brave == []  # nem chegou a tentar -- o bing já confirmou


def test_erro_num_provedor_nao_derruba_a_busca_dos_outros_termos(monkeypatch):
    nome_modulo, nome_classe = be._CLIENTES_BUSCADORES["bing"]
    mod = types.ModuleType(nome_modulo)

    class ClientQueEstoura:
        def search_photos_all(self, query, max_images=1):
            if query == "Termo Com Erro":
                raise RuntimeError("falha simulada de rede")
            return [_FakeImagem(description="ok")]

    setattr(mod, nome_classe, ClientQueEstoura)
    monkeypatch.setitem(sys.modules, nome_modulo, mod)

    confirmados = be.buscar_confirmados_nos_buscadores(
        ["Termo Com Erro", "Termo OK"], providers=["bing"],
    )
    assert [c["termo"] for c in confirmados] == ["Termo OK"]


def test_respeita_max_verificacoes(monkeypatch):
    chamadas = []
    resultados = {f"Termo{i}": ["achou"] for i in range(20)}
    _instalar_fake(monkeypatch, "bing", resultados, chamadas=chamadas)
    be.buscar_confirmados_nos_buscadores(
        [f"Termo{i}" for i in range(20)], providers=["bing"], max_verificacoes=5,
    )
    assert len(chamadas) == 5


def test_provider_nao_reconhecido_e_ignorado_silenciosamente(monkeypatch):
    _instalar_fake(monkeypatch, "bing", {"Termo X": ["achou"]})
    confirmados = be.buscar_confirmados_nos_buscadores(
        ["Termo X"], providers=["provedor-que-nao-existe", "bing"],
    )
    assert len(confirmados) == 1


def test_nenhum_provider_valido_devolve_lista_vazia_sem_tentar_nada():
    confirmados = be.buscar_confirmados_nos_buscadores(
        ["qualquer termo"], providers=["pexels", "wikipedia"],  # nenhum é buscador de navegador
    )
    assert confirmados == []


def test_lista_de_candidatos_vazia_devolve_vazio(monkeypatch):
    _instalar_fake(monkeypatch, "bing", {})
    assert be.buscar_confirmados_nos_buscadores([], providers=["bing"]) == []


def test_cliente_que_falha_ao_instanciar_e_pulado_mas_outros_continuam(monkeypatch):
    nome_modulo, nome_classe = be._CLIENTES_BUSCADORES["bing"]
    mod = types.ModuleType(nome_modulo)

    class ClientQueFalhaAoInstanciar:
        def __init__(self):
            raise RuntimeError("dependência faltando")

    setattr(mod, nome_classe, ClientQueFalhaAoInstanciar)
    monkeypatch.setitem(sys.modules, nome_modulo, mod)
    _instalar_fake(monkeypatch, "brave", {"Termo X": ["achou no brave"]})

    confirmados = be.buscar_confirmados_nos_buscadores(
        ["Termo X"], providers=["bing", "brave"],
    )
    assert len(confirmados) == 1
    assert confirmados[0]["provider"] == "brave"
