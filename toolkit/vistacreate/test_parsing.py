"""
Teste offline: valida o parsing usando trechos reais de HTML (copiados do
que o usuário forneceu), sem precisar de acesso à internet.
"""
from vistacreate_client import VistaCreateClient, VistaCreateClientError, _slugify

# --------------------------------------------------------------------- #
# 3 itens reais: 1 sem premium (com <a href>), 2 premium (sem <a href>,
# com selo de diamante) — incluindo o "donkey walking farm enclosure"
# que foi o exemplo exato do link de download dado pelo usuário.
# --------------------------------------------------------------------- #
listing_html = '''
<div class="controlButtonWrapper-2fYDN assetWrapper-2LqKz descriptionWrapper-2-U-4 assetWrapper-O9SHq" style="width:calc(var(--row-height) * 1.7777777777777777);flex-grow:17.77777777777778"><a href="/pt/unlimited/stock-videos/549139086/stock-video-animation-spinning-bird-icon-light-pastel-background/"><div style="padding-bottom:56.25%"><div class="media-3IiMe"><div class="wrapper-1D3Pt"><div></div><img crossorigin="anonymous" src="https://cdn.create.vista.com/api/media/small/549139086/stock-video-animation-spinning-bird-icon-light-pastel-background?videoStaticPreview=true&amp;token=" alt="animação do ícone de pássaro girando no fundo pastel luz  - Filmagem, Vídeo" class="poster-y1Ut5 videoItem-3ZOQX fullWidthPoster-24fz-"/></div></div><div class="descriptionContainer-1t1uM"><p class="typography-subheading-s description-2kEqo multilineEllipsis-2Pj6T" style="-webkit-box-orient:vertical">Animação do ícone de pássaro girando no fundo pastel luz</p></div></div></a><button aria-label="Zoom Image" class="controlButton-3rojF slideFromRight-1DQCK templatePreview-3FL7P"><img alt="" width="16" height="16" src="https://static.create.vista.com/images/wing/icons/preview.svg" class=""/></button></div>

<div class="controlButtonWrapper-2fYDN assetWrapper-2LqKz descriptionWrapper-2-U-4 assetWrapper-O9SHq" style="width:calc(var(--row-height) * 1.7777777777777777);flex-grow:17.77777777777778"><div class="linkButtonWrapper-25Aec"><div style="padding-bottom:56.25%"><div class="media-3IiMe"><div class="wrapper-1D3Pt"><div></div><img crossorigin="anonymous" src="https://cdn.create.vista.com/api/media/small/849072656/stock-video-white-alpaca-standing-tree-outdoor-zoo-enclosure?videoStaticPreview=true&amp;token=" alt="Alpaca branca em pé perto da árvore no recinto zoológico ao ar livre - Filmagem, Vídeo" class="poster-y1Ut5 videoItem-3ZOQX fullWidthPoster-24fz-"/></div></div><div class="descriptionContainer-1t1uM"><p class="typography-subheading-s description-2kEqo multilineEllipsis-2Pj6T" style="-webkit-box-orient:vertical">Alpaca branca em pé perto da árvore no recinto zoológico ao ar livre</p></div></div><button class="premiumLabelWrapper-SJhTa controlButton-3rojF isVisible-1v5Qf premiumLabelBottomRight-2BPQF" aria-label="Inicie o teste gratuito do VistaCreate Pro para desbloquear este e mais de 70 milhões de recursos"><img alt="" width="16" height="16" src="https://static.create.vista.com/images/wing/icons/diamond-yellow.svg" class=""/></button></div><button aria-label="Zoom Image" class="controlButton-3rojF slideFromRight-1DQCK templatePreview-3FL7P"><img alt="" width="16" height="16" src="https://static.create.vista.com/images/wing/icons/preview.svg" class=""/></button></div>

<div class="controlButtonWrapper-2fYDN assetWrapper-2LqKz descriptionWrapper-2-U-4 assetWrapper-O9SHq" style="width:calc(var(--row-height) * 1.7777777777777777);flex-grow:17.77777777777778"><div class="linkButtonWrapper-25Aec"><div style="padding-bottom:56.25%"><div class="media-3IiMe"><div class="wrapper-1D3Pt"><div></div><img crossorigin="anonymous" src="https://cdn.create.vista.com/api/media/small/849076422/stock-video-donkey-walking-farm-enclosure?videoStaticPreview=true&amp;token=" alt="Burro andando em uma fazenda cerco - Filmagem, Vídeo" class="poster-y1Ut5 videoItem-3ZOQX fullWidthPoster-24fz-"/></div></div><div class="descriptionContainer-1t1uM"><p class="typography-subheading-s description-2kEqo multilineEllipsis-2Pj6T" style="-webkit-box-orient:vertical">Burro andando em uma fazenda cerco</p></div></div><button class="premiumLabelWrapper-SJhTa controlButton-3rojF isVisible-1v5Qf premiumLabelBottomRight-2BPQF" aria-label="Inicie o teste gratuito do VistaCreate Pro para desbloquear este e mais de 70 milhões de recursos"><img alt="" width="16" height="16" src="https://static.create.vista.com/images/wing/icons/diamond-yellow.svg" class=""/></button></div><button aria-label="Zoom Image" class="controlButton-3rojF slideFromRight-1DQCK templatePreview-3FL7P"><img alt="" width="16" height="16" src="https://static.create.vista.com/images/wing/icons/preview.svg" class=""/></button></div>
'''

videos = VistaCreateClient._parse_listing_page(listing_html)
print(f"== {len(videos)} vídeos extraídos ==")
for v in videos:
    print(f"- [{v.id}] {v.title!r} | premium={v.premium} | url={v.url} | download={v.download_url}")

assert len(videos) == 3
by_id = {v.id: v for v in videos}

v_bird = by_id["549139086"]
assert v_bird.premium is False
assert v_bird.url == (
    "https://create.vista.com/pt/unlimited/stock-videos/549139086/"
    "stock-video-animation-spinning-bird-icon-light-pastel-background/"
)
assert v_bird.title == "Animação do ícone de pássaro girando no fundo pastel luz"

v_alpaca = by_id["849072656"]
assert v_alpaca.premium is True
assert v_alpaca.url is None  # premium, sem <a href> clicável

v_donkey = by_id["849076422"]
assert v_donkey.premium is True
assert v_donkey.title == "Burro andando em uma fazenda cerco"
print("\n== Link de download do burro (deve bater com o exemplo do usuário) ==")
print(v_donkey.download_url)
assert v_donkey.download_url == (
    "https://cdn.create.vista.com/api/media/small/849076422/"
    "stock-video-donkey-walking-farm-enclosure?token="
), "não bateu com o link de download fornecido pelo usuário"
print("OK: bate exatamente com o link de download dado como exemplo.")

# --------------------------------------------------------------------- #
# Slugify do termo de busca
# --------------------------------------------------------------------- #
print("\n== Slugify ==")
print(_slugify("animal nature"))
assert _slugify("animal nature") == "animal-nature"
assert _slugify("  Gato  Cachorro  ") == "gato-cachorro"

# --------------------------------------------------------------------- #
# Validação de filtros
# --------------------------------------------------------------------- #
params = VistaCreateClient._build_params(page=2, sort="popular", people="exclude")
print("\n== Params construídos ==")
print(params)
assert params == {"page": 2, "sort": "popular", "people": "exclude"}

try:
    VistaCreateClient._build_params(sort="oldest")
    raise SystemExit("ERRO: deveria ter rejeitado sort inválido")
except VistaCreateClientError as e:
    print("OK, sort inválido rejeitado:", e)

print("\nTodos os testes offline passaram.")

# --------------------------------------------------------------------- #
# Retry de tamanho de mídia (small/medium/large) — sem rede
# --------------------------------------------------------------------- #
print("\n== Candidatos de tamanho de mídia ==")

candidates_best = VistaCreateClient._build_media_size_candidates(v_donkey.download_url, "best")
print("best:", candidates_best)
assert candidates_best[0] == (
    "https://cdn.create.vista.com/api/media/large/849076422/"
    "stock-video-donkey-walking-farm-enclosure?token=",
    "large",
)
assert candidates_best[-1] == (v_donkey.download_url, "small")
assert len(candidates_best) == 3

candidates_worst = VistaCreateClient._build_media_size_candidates(v_donkey.download_url, "worst")
print("worst:", candidates_worst)
assert candidates_worst[0][1] == "small"
assert candidates_worst[-1][1] == "large"

candidates_medium = VistaCreateClient._build_media_size_candidates(v_donkey.download_url, "medium")
print("medium (pedido específico):", candidates_medium)
assert candidates_medium[0][1] == "medium"
assert len(candidates_medium) == 3

try:
    VistaCreateClient._build_media_size_candidates(v_donkey.download_url, "8k")
    raise SystemExit("ERRO: deveria ter rejeitado quality inválida")
except VistaCreateClientError as e:
    print("OK, quality inválida rejeitada:", e)

# URL fora do padrão esperado -> só uma opção, sem quebrar
candidates_unknown = VistaCreateClient._build_media_size_candidates(
    "https://cdn.create.vista.com/other/path/123", "best"
)
assert candidates_unknown == [("https://cdn.create.vista.com/other/path/123", None)]
print("OK: URL fora do padrão não quebra, só usa como única opção.")

print("\nTodos os testes de retry de qualidade passaram.")
