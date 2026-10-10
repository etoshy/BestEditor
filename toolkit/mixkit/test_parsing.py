"""
Teste offline: valida o parsing usando trechos reais de HTML (copiados do
que o usuário forneceu), sem precisar de acesso à internet.
"""
from mixkit_client import MixkitClient, MixkitClientError

# --------------------------------------------------------------------- #
# HTML com: 1 item "normal" (padrão -360.mp4), 1 item com asset tipo hash
# (sem sufixo de resolução) e o bloco de banner da Envato no meio.
# --------------------------------------------------------------------- #
listing_html = '''
<div class="item-grid-card item-grid-card--show-meta" data-algolia-analytics-object-id="video-1484">
  <div class="item-grid-video-player item-grid-video-player--4k" data-item-grid--video-player-item-id-value="1484">
    <div class="item-grid-video-player__thumb-wrapper">
      <picture>
        <img src="https://assets.mixkit.co/videos/1484/1484-thumb-360-0.jpg" class="item-grid-video-player__thumb" alt="Lizard looking for dinner in nature .">
      </picture>
    </div>
    <div class="item-grid-video-player__video-wrapper">
      <video src="https://assets.mixkit.co/videos/1484/1484-360.mp4" playsinline="" loop="" muted="" preload="none" class="item-grid-video-player__video"></video>
    </div>
    <div class="item-grid-video-player__overlay-wrapper">
      <a href="/free-stock-video/lizard-looking-for-dinner-in-nature-1484/" class="item-grid-video-player__overlay-link">
        Lizard looking for dinner in nature 
      </a>
    </div>
  </div>
  <div class="item-grid-card__meta">
    <h2 class="item-grid-card__title">
      <a href="/free-stock-video/lizard-looking-for-dinner-in-nature-1484/">Lizard looking for dinner in nature </a>
    </h2>
    <p class="item-grid-card__description">Brown lizard walking and looking for dinner over a trunk in nature. Animals in their habitat. Agama, small dragon, iguana. Brown lizard.</p>
  </div>
</div>

<div class="item-grid__banner item-grid__ordering--banner-middle">
  <turbo-frame id="banner-frame" src="/free-stock-video/discover/animal-nature/banner-frame/">
    <div class="elements-video-items">
      <a rel="noopener" target="_blank" href="https://elements.envato.com/c/stock-video?utm_source=mixkit">Envato Elements banner, sem object-id de video</a>
    </div>
  </turbo-frame>
</div>

<div class="item-grid-card item-grid-card--show-meta" data-algolia-analytics-object-id="video-101217">
  <div class="item-grid-video-player item-grid-video-player--4k" data-item-grid--video-player-item-id-value="101217">
    <div class="item-grid-video-player__thumb-wrapper">
      <picture>
        <img src="https://assets.mixkit.co/4muvc4av8s0pfr9d1pdx82pw3mq4" class="item-grid-video-player__thumb" alt="Dog Resting with a Sweet Look.">
      </picture>
    </div>
    <div class="item-grid-video-player__video-wrapper">
      <video src="https://assets.mixkit.co/228xstitup4u61qtx66ervy2js74" playsinline="" loop="" muted="" preload="none" class="item-grid-video-player__video"></video>
    </div>
    <div class="item-grid-video-player__overlay-wrapper">
      <a href="/free-stock-video/dog-resting-with-a-sweet-look-101217/" class="item-grid-video-player__overlay-link">
        Dog Resting with a Sweet Look
      </a>
    </div>
  </div>
  <div class="item-grid-card__meta">
    <h2 class="item-grid-card__title">
      <a href="/free-stock-video/dog-resting-with-a-sweet-look-101217/">Dog Resting with a Sweet Look</a>
    </h2>
    <p class="item-grid-card__description">A close-up of a dog resting on the floor, looking absolutely adorable. Perfect for pet content, heartwarming moments, or any project looking to highlight the calm, loving nature of dogs.</p>
  </div>
</div>
'''

videos = MixkitClient._parse_listing_page(listing_html)
print(f"== {len(videos)} vídeos extraídos (esperado: 2, banner ignorado) ==")
for v in videos:
    print(f"- [{v.id}] {v.title!r} | preview={v.preview_url} | 4k_badge={v.has_4k_badge} | url={v.url}")

assert len(videos) == 2, "o banner da Envato não deveria ter sido capturado como vídeo"
by_id = {v.id: v for v in videos}

v1 = by_id["1484"]
assert v1.title == "Lizard looking for dinner in nature"
assert v1.url == "https://mixkit.co/free-stock-video/lizard-looking-for-dinner-in-nature-1484/"
assert v1.preview_url == "https://assets.mixkit.co/videos/1484/1484-360.mp4"
assert v1.has_4k_badge is True
assert "Brown lizard" in v1.description

v2 = by_id["101217"]
assert v2.preview_url == "https://assets.mixkit.co/228xstitup4u61qtx66ervy2js74"
print("\nOK: banner da Envato excluído e os dois vídeos reais foram parseados corretamente.")

# --------------------------------------------------------------------- #
# Lógica de candidatos de qualidade (sem rede)
# --------------------------------------------------------------------- #
candidates_best = MixkitClient._build_quality_candidates(v1.preview_url, "best")
print("\n== Candidatos 'best' para vídeo com padrão -360.mp4 ==")
print(candidates_best)
assert candidates_best[0] == ("https://assets.mixkit.co/videos/1484/1484-2160.mp4", 2160)
assert candidates_best[-1] == ("https://assets.mixkit.co/videos/1484/1484-360.mp4", 360)
assert len(candidates_best) == 4

candidates_specific = MixkitClient._build_quality_candidates(v1.preview_url, 720)
print("\n== Candidatos pedindo 720 especificamente ==")
print(candidates_specific)
assert candidates_specific[0] == ("https://assets.mixkit.co/videos/1484/1484-720.mp4", 720)
assert len(candidates_specific) == 4  # 720 primeiro, depois as outras 3

candidates_hash = MixkitClient._build_quality_candidates(v2.preview_url, "best")
print("\n== Candidatos para asset tipo hash (sem sufixo de resolução) ==")
print(candidates_hash)
assert candidates_hash == [(v2.preview_url, None)], "asset tipo hash só deve ter 1 candidato: ele mesmo"

# --------------------------------------------------------------------- #
# Validação de filtros (sem rede)
# --------------------------------------------------------------------- #
params = MixkitClient._build_params(page=2, orientation="horizontal", duration="20s-", sort="newest")
print("\n== Params construídos ==")
print(params)
assert params == {"page": 2, "orientation": "horizontal", "duration": "20s-", "sort": "newest"}

try:
    MixkitClient._build_params(orientation="diagonal")
    raise SystemExit("ERRO: deveria ter rejeitado orientação inválida")
except MixkitClientError as e:
    print("OK, orientação inválida rejeitada:", e)

print("\nTodos os testes offline passaram.")
