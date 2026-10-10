"""
buscadores_enrichment.py
==========================

Modo "este vídeo usa buscadores de imagem" (Bing/Brave/Yandex/Startpage
Images): mesma ideia de `wikipedia_enrichment.py`, mas pros 4 buscadores
de imagem por navegador que o toolkit tem hoje. Em vez de deixar a IA
simplesmente CHUTAR quais termos vão dar resultado bom nesses buscadores,
esse módulo pesquisa de verdade ANTES de montar o prompt principal:

    `buscar_confirmados_nos_buscadores(candidatos, providers)` —
    pesquisa cada candidato de verdade (via `toolkit/bing_api_client.py`,
    `brave_api_client.py`, `yandex_api_client.py`, `startpage_api_client.py`
    — só os que estiverem em `providers`) e só mantém os que realmente
    têm pelo menos um resultado de imagem. Pra cada termo confirmado,
    tenta os provedores NA ORDEM dada até um funcionar (não pesquisa nos
    4 pra cada termo — pára no primeiro que confirmar, pra não gastar
    tempo à toa).

O resultado (lista pequena e VERIFICADA de termos com imagem confirmada,
cada um já sabendo qual provedor funcionou) é passado pra
`prompt_builder.build_prompt()` via `buscadores_confirmados`, que monta
uma regra dizendo à IA pra usar esses termos exatos com o provedor já
confirmado, em vez de arriscar um termo que pode não trazer nada.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List

_DIR = os.path.dirname(os.path.abspath(__file__))
_TOOLKIT_DIR = os.path.join(_DIR, "toolkit")

# provedor -> (nome do módulo, nome da classe) -- mesmo padrão de
# `video_assembler._PHOTO_PROVIDER_MODULES`, mas só os 4 buscadores por
# navegador (não repete pexels/wikipedia/flow aqui).
_CLIENTES_BUSCADORES = {
    "bing": ("bing_api_client", "BingAPIClient"),
    "brave": ("brave_api_client", "BraveAPIClient"),
    "yandex": ("yandex_api_client", "YandexAPIClient"),
    "startpage": ("startpage_api_client", "StartpageAPIClient"),
}


class BuscadoresEnrichmentError(Exception):
    """Erro genérico — pensado pra ser tratado como best-effort: quem
    chama pode simplesmente seguir sem enriquecimento nenhum em vez de
    travar o pipeline inteiro."""


def _criar_clientes(providers: List[str]) -> Dict[str, Any]:
    """Instancia um cliente por provedor válido em `providers` (só os
    que existem em `_CLIENTES_BUSCADORES`). Um provedor que falhar ao
    importar/instanciar (dependência faltando etc.) é só pulado -- os
    outros continuam disponíveis."""
    if _TOOLKIT_DIR not in sys.path:
        sys.path.insert(0, _TOOLKIT_DIR)

    import importlib

    clientes: Dict[str, Any] = {}
    for provider in providers:
        entry = _CLIENTES_BUSCADORES.get(provider)
        if not entry:
            continue
        module_name, class_name = entry
        try:
            module = importlib.import_module(module_name)
            client_cls = getattr(module, class_name)
            clientes[provider] = client_cls()
        except Exception:  # noqa: BLE001
            continue
    return clientes


def buscar_confirmados_nos_buscadores(
    candidatos: List[str],
    providers: List[str],
    max_verificacoes: int = 15,
    min_imagens: int = 1,
) -> List[Dict[str, str]]:
    """Pesquisa cada candidato DE VERDADE num dos buscadores de imagem
    por navegador (só os que estiverem em `providers`, tentados nessa
    mesma ordem pra cada termo) e devolve só os que têm pelo menos
    `min_imagens` resultado encontrado — best-effort: um candidato ou
    provedor que dá erro (rede, bloqueio anti-bot etc.) é só pulado,
    nunca derruba a busca inteira. Se nenhum provedor válido estiver em
    `providers`, ou nenhum cliente conseguir ser criado, devolve lista
    vazia em vez de levantar exceção.
    """
    providers_validos = [p for p in providers if p in _CLIENTES_BUSCADORES]
    if not providers_validos or not candidatos:
        return []

    clientes = _criar_clientes(providers_validos)
    if not clientes:
        return []

    candidatos = [c for c in candidatos[:max_verificacoes] if c and c.strip()]
    achados: Dict[str, Dict[str, str]] = {}
    pendentes = list(candidatos)

    # Rodadas: cada buscador recebe DE UMA VEZ todos os termos que ainda
    # faltam confirmar — com o cliente unificado (`search_photos_batch`),
    # isso é UM navegador pesquisando todos os termos na mesma aba, em vez
    # de abrir um Chromium por termo. O que esse buscador não achar passa
    # pro próximo da lista. (Cliente sem lote -> um termo por vez, como antes.)
    for provider in providers_validos:
        client = clientes.get(provider)
        if not client or not pendentes:
            continue
        resultados: Dict[str, List[Any]] = {}
        if hasattr(client, "search_photos_batch"):
            try:
                resultados = client.search_photos_batch(pendentes, max_images=min_imagens) or {}
            except Exception:  # noqa: BLE001
                resultados = {}
        else:
            for candidato in pendentes:
                try:
                    resultados[candidato] = client.search_photos_all(candidato, max_images=min_imagens)
                except Exception:  # noqa: BLE001
                    continue
        for candidato in list(pendentes):
            imagens = resultados.get(candidato) or resultados.get(" ".join(candidato.split())) or []
            if len(imagens) < min_imagens:
                continue
            primeira = imagens[0]
            achados[candidato] = {
                "termo": candidato,
                "provider": provider,
                "descricao": (getattr(primeira, "description", "") or "")[:150],
            }
            pendentes.remove(candidato)

    # mantém a ordem original dos candidatos
    return [achados[c] for c in candidatos if c in achados]
