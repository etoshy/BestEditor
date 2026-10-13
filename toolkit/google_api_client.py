"""
google_api_client.py
====================

Cliente de IMAGENS do Google Imagens para o site — pelo **Modo IA do Google**.

Quem pesquisa é o app da pasta `ia_google/` (o mesmo da aba 🔎 IA do Google), pela API documentada
no README dele: `POST /api/imagens` → link da imagem ORIGINAL (não a miniatura), largura, altura e
página de origem. O site liga o app sozinho (porta 8852, ⚙️ Configurações) quando precisa.

Mesma interface dos outros buscadores de imagem (`BingAPIClient`, `BraveAPIClient`, ...):
`search_photos_all` / `search_photos_batch` / `download_photo` — ver
`buscador_imagens_unificado.BuscadorImagensClient`. O download é o mesmo dos outros (confere os
bytes, usa a página de origem como Referer e tenta a miniatura se a original bloquear).
"""

from __future__ import annotations

from buscador_imagens_unificado import BuscadorImagensClient, BuscadorImagensError, ImagemBuscador


class GoogleAPIClientError(BuscadorImagensError):
    """Erro genérico do cliente (app da IA do Google fora do ar, sem resultados, download falhou etc.)."""


GoogleImage = ImagemBuscador


class GoogleAPIClient(BuscadorImagensClient):
    engine = "google"
    error_cls = GoogleAPIClientError
