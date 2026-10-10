"""
bing_api_client.py
==================

Cliente de IMAGENS do Bing Images para o site. Desde a integração da "Busca de
Imagens Unificada" (pasta `unified_images/`), é só uma casca fina sobre
`buscador_imagens_unificado.BuscadorImagensClient` — a busca usa o motor
melhorado (`unified_images/engines/bing_image_api.py`, várias buscas na
mesma aba) e o download usa o downloader unificado (confere os bytes,
tenta thumbnail/proxy se a original falhar).

Mantém os mesmos nomes de antes (`BingAPIClient`, `BingAPIClientError`,
`BingImage`) pra nada no site precisar mudar.
"""

from __future__ import annotations

from buscador_imagens_unificado import BuscadorImagensClient, BuscadorImagensError, ImagemBuscador


class BingAPIClientError(BuscadorImagensError):
    """Erro genérico do cliente (busca falhou, sem resultados, download falhou etc.)."""


BingImage = ImagemBuscador


class BingAPIClient(BuscadorImagensClient):
    engine = "bing"
    error_cls = BingAPIClientError
