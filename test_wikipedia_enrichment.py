"""
Teste de wikipedia_enrichment.py: a heurística de extração de nomes
próprios candidatos do roteiro (sem IA nenhuma) e a verificação desses
candidatos contra a Wikipedia de verdade (mockada aqui — o cliente em
si já tem sua própria suíte em toolkit/test_wikipedia_api_client.py).
"""
import sys
import types

import pytest

import wikipedia_enrichment as we


def _segs(*textos):
    return [{"text": t} for t in textos]


# --------------------------------------------------------------------------- #
# extrair_entidades_candidatas — heurística de texto, sem rede nenhuma
# --------------------------------------------------------------------------- #

def test_extrai_nomes_de_duas_palavras():
    candidatos = we.extrair_entidades_candidatas(_segs("Albert Einstein nasceu na Alemanha."))
    assert "Albert Einstein" in candidatos


def test_extrai_nomes_com_palavra_de_ligacao_no_meio():
    candidatos = we.extrair_entidades_candidatas(_segs("Machado de Assis escreveu Dom Casmurro."))
    assert "Machado de Assis" in candidatos


def test_extrai_nomes_de_tres_palavras():
    candidatos = we.extrair_entidades_candidatas(_segs("A Segunda Guerra Mundial começou em 1939."))
    assert "Segunda Guerra Mundial" in candidatos


def test_repeticao_ao_longo_dos_segmentos_da_prioridade():
    segments = _segs(
        "A Torre Eiffel foi construída em 1889.",
        "Milhões visitam a Torre Eiffel todo ano.",
        "A Torre Eiffel fica em Paris.",
        "Paris é a capital da França.",
    )
    candidatos = we.extrair_entidades_candidatas(segments, max_candidatos=10)
    # "Torre Eiffel" aparece 3x -- deve vir antes de "Paris" (1x nomeada sozinha)
    assert candidatos.index("Torre Eiffel") < candidatos.index("Paris")


def test_nao_extrai_palavra_unica_no_inicio_de_frase():
    candidatos = we.extrair_entidades_candidatas(_segs("Hoje vamos falar sobre história."))
    assert "Hoje" not in candidatos


def test_nao_extrai_pronomes_e_dias_da_semana_sozinhos():
    candidatos = we.extrair_entidades_candidatas(_segs(
        "Ele disse que a reunião é Segunda.",  # "Segunda" sozinho no fim, sem extensão -- descartado
    ))
    assert "Segunda" not in candidatos
    assert "Ele" not in candidatos


def test_extrai_substantivo_proprio_unico_fora_do_inicio_da_frase():
    candidatos = we.extrair_entidades_candidatas(_segs("Einstein nasceu na Alemanha em 1879."))
    assert "Alemanha" in candidatos


def test_respeita_max_candidatos():
    textos = [f"Fulano{i} De Tal{i} fez alguma coisa importante." for i in range(30)]
    candidatos = we.extrair_entidades_candidatas(_segs(*textos), max_candidatos=5)
    assert len(candidatos) <= 5


def test_segmentos_sem_texto_nao_quebram():
    candidatos = we.extrair_entidades_candidatas([{"text": ""}, {}, {"text": "   "}])
    assert candidatos == []


def test_lista_vazia_de_segmentos():
    assert we.extrair_entidades_candidatas([]) == []


def test_liga_apenas_no_meio_nunca_estende_alem_do_fim():
    # "de" no fim (sem palavra capitalizada depois) não deve virar parte
    # da entidade nem quebrar a extração do resto.
    candidatos = we.extrair_entidades_candidatas(_segs("Vamos falar de São Paulo e também de coisas."))
    assert "São Paulo" in candidatos


# --------------------------------------------------------------------------- #
# buscar_entidades_confirmadas_na_wikipedia — cliente mockado
# --------------------------------------------------------------------------- #

class _FakeImage:
    def __init__(self, descricao="", legenda=""):
        self.descricao = descricao
        self.legenda = legenda


class _FakeWikipediaAPIClientError(Exception):
    pass


class _FakeSession:
    def close(self):
        pass


def _fake_wikipedia_api_client_module(paginas):
    """`paginas`: dict termo -> None (não encontrado) | [] (sem imagem) |
    [descrição, ...] (imagens encontradas, uma por descrição)."""
    mod = types.ModuleType("wikipedia_api_client")

    class FakeClient:
        def __init__(self):
            self.session = _FakeSession()

        def find_page_title(self, termo):
            if termo not in paginas or paginas[termo] is None:
                raise _FakeWikipediaAPIClientError(f"não encontrado: {termo}")
            return termo

        def get_images_from_page(self, titulo, max_images=1):
            descricoes = paginas.get(titulo) or []
            return [_FakeImage(descricao=d) for d in descricoes[:max_images]]

    mod.WikipediaAPIClient = FakeClient
    mod.WikipediaAPIClientError = _FakeWikipediaAPIClientError
    return mod


def test_busca_confirmadas_filtra_inexistentes_e_sem_imagem(monkeypatch):
    fake_mod = _fake_wikipedia_api_client_module({
        "Albert Einstein": ["físico alemão"],
        "SemFoto": [],
        # "Inexistente" nem está no dict -> find_page_title levanta erro
        "Torre Eiffel": ["monumento em Paris"],
    })
    monkeypatch.setitem(sys.modules, "wikipedia_api_client", fake_mod)

    confirmadas = we.buscar_entidades_confirmadas_na_wikipedia(
        ["Albert Einstein", "SemFoto", "Inexistente", "Torre Eiffel"]
    )
    termos = [c["termo"] for c in confirmadas]
    assert termos == ["Albert Einstein", "Torre Eiffel"]
    assert confirmadas[0]["descricao"] == "físico alemão"


def test_busca_confirmadas_respeita_max_verificacoes(monkeypatch):
    chamadas = []
    fake_mod = _fake_wikipedia_api_client_module({f"Termo{i}": ["desc"] for i in range(20)})
    original_find = fake_mod.WikipediaAPIClient.find_page_title

    def find_com_contagem(self, termo):
        chamadas.append(termo)
        return original_find(self, termo)

    fake_mod.WikipediaAPIClient.find_page_title = find_com_contagem
    monkeypatch.setitem(sys.modules, "wikipedia_api_client", fake_mod)

    we.buscar_entidades_confirmadas_na_wikipedia([f"Termo{i}" for i in range(20)], max_verificacoes=5)
    assert len(chamadas) == 5


def test_busca_confirmadas_sem_lib_disponivel_devolve_vazio(monkeypatch):
    # simula o módulo não instalado -- remove do sys.modules e garante
    # que um ImportError não quebra a função (devolve lista vazia).
    monkeypatch.delitem(sys.modules, "wikipedia_api_client", raising=False)
    monkeypatch.delitem(sys.modules, "toolkit.wikipedia_api_client", raising=False)
    import builtins
    original_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "wikipedia_api_client":
            raise ImportError("simulado: lib ausente")
        return original_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    resultado = we.buscar_entidades_confirmadas_na_wikipedia(["Qualquer Coisa"])
    assert resultado == []


def test_busca_confirmadas_lista_vazia_de_candidatos(monkeypatch):
    fake_mod = _fake_wikipedia_api_client_module({})
    monkeypatch.setitem(sys.modules, "wikipedia_api_client", fake_mod)
    assert we.buscar_entidades_confirmadas_na_wikipedia([]) == []


# --------------------------------------------------------------------------- #
# identificar_entidades_wikipedia — ponto de entrada único, nunca quebra
# --------------------------------------------------------------------------- #

def test_identificar_entidades_fluxo_completo(monkeypatch):
    fake_mod = _fake_wikipedia_api_client_module({
        "Albert Einstein": ["físico"],
    })
    monkeypatch.setitem(sys.modules, "wikipedia_api_client", fake_mod)

    resultado = we.identificar_entidades_wikipedia(
        _segs("Albert Einstein nasceu na Alemanha em 1879.")
    )
    assert any(c["termo"] == "Albert Einstein" for c in resultado)


def test_identificar_entidades_sem_candidatos_devolve_vazio():
    resultado = we.identificar_entidades_wikipedia(_segs("isso não tem nome próprio nenhum aqui."))
    assert resultado == []


def test_identificar_entidades_nunca_levanta_excecao(monkeypatch):
    def quebra_tudo(*a, **k):
        raise RuntimeError("falha proposital")

    monkeypatch.setattr(we, "extrair_entidades_candidatas", quebra_tudo)
    resultado = we.identificar_entidades_wikipedia(_segs("Albert Einstein nasceu na Alemanha."))
    assert resultado == []
