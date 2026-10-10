"""
Teste offline: valida o parsing usando trechos reais de HTML/JSON-LD
(copiados do que o usuário forneceu), sem precisar de acesso à internet.
"""
import json
from pixabay_client import PixabayClient, PixabayClientError

# --------------------------------------------------------------------- #
# 1) Página de DETALHE de um vídeo (leopard cub) -- tem o link "_large.mp4"
# --------------------------------------------------------------------- #
detail_html = '''
<script type="application/ld+json">{"@context":"http://schema.org","license":"https://pixabay.com/service/license-summary/","acquireLicensePage":"/videos/leopard-cub-small-wildcat-106286/","name":"Leopard, Cub, Small. Free Stock Video","uploadDate":"2022-02-02T03:03:59.149Z","datePublished":"2022-02-02T03:03:59.149Z","description":"Download this free video of Leopard Cub Small from Pixabay's vast library of royalty-free stock images, videos and music.","caption":"Leopard, Cub, Small. Free Stock Video","isAccessibleForFree":true,"creator":{"@type":"Person","name":"NickyPe"},"interactionStatistic":{"@type":"InteractionCounter","interactionType":"https://schema.org/ViewAction","userInteractionCount":9024},"isFamilyFriendly":true,"@type":"VideoObject","contentUrl":"https://cdn.pixabay.com/video/2022/02/01/106286-672600280_large.mp4","thumbnailUrl":"https://cdn.pixabay.com/video/2022/02/01/106286-672600280_tiny.jpg","width":"1920","height":"1080","duration":"PT0M40S","thumbnail":{"@type":"ImageObject","url":"https://cdn.pixabay.com/video/2022/02/01/106286-672600280_tiny.jpg"}}</script>
'''

objs = PixabayClient._extract_video_objects(detail_html)
assert len(objs) == 1, f"esperava 1 objeto, veio {len(objs)}"

parsed = PixabayClient._parse_video_object(objs[0])
print("== Vídeo de detalhe (leopard cub) ==")
print(json.dumps(parsed.to_dict(), indent=2, ensure_ascii=False))
assert parsed.id == "106286"
assert parsed.slug == "leopard-cub-small-wildcat"
assert parsed.url == "https://pixabay.com/videos/leopard-cub-small-wildcat-106286/"
assert parsed.duration == 40
assert parsed.author == "NickyPe"
assert parsed.width == 1920 and parsed.height == 1080
download_url = objs[0]["contentUrl"]
assert download_url == "https://cdn.pixabay.com/video/2022/02/01/106286-672600280_large.mp4"
print("\nOK: link de download real ->", download_url)

# --------------------------------------------------------------------- #
# 2) Página de LISTAGEM (busca "gato cachorro") -- vários VideoObject +
#    blocos de qualidade/duração ligados via "external-id=video%3A<id>"
# --------------------------------------------------------------------- #
search_html = '''
<span class="h4--eMLrj">4K</span><div class="text--ifigj default--ariTz">0:06</div><div class="icon--XN9Tf lg--LRse2" role="img" aria-label="AI"><svg>...</svg></div></div><button>...</button><div class="overlayControlsRight--WaGrH"><a class="button--af32y outline--AgP6D dark--ihJXz center--aZtxo" href="https://canva.com/content-partner/?utm_medium=partner&utm_source=pixabay&utm_campaign=retouch_in_canva_edit_video&file-url=https%3A%2F%2Fcdn.pixabay.com%2Fvideo%2F2026%2F02%2F23%2F336373_large.mp4&external-id=video%3A336373" target="_blank">Edit video</a></div>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"VideoObject","contentUrl":"https://cdn.pixabay.com/video/2026/02/23/336373_tiny.mp4","thumbnailUrl":"https://cdn.pixabay.com/video/2026/02/23/336373_tiny.jpg","name":"Nature, Jaguar, Wildlife","description":"Nature, Jaguar, Wildlife, Rainforest, Animal, Mother, Cub","license":"https://pixabay.com/service/license-summary/","acquireLicensePage":"/videos/nature-jaguar-wildlife-rainforest-336373/","duration":"T0M6S","uploadDate":"2026-08-30T16:47:47.711Z","sourceOrganization":{"@type":"Organization","name":"Pixabay"}}</script>

<span class="h4--eMLrj">SD</span><div class="text--ifigj default--ariTz">0:05</div><div class="icon--XN9Tf lg--LRse2" role="img" aria-label="AI"><svg>...</svg></div></div><button>...</button><div class="overlayControlsRight--WaGrH"><a href="https://canva.com/content-partner/?...&file-url=...368422_large.mp4&external-id=video%3A368422" target="_blank">Edit video</a></div>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"VideoObject","contentUrl":"https://cdn.pixabay.com/video/2026/08/03/368422_tiny.mp4","thumbnailUrl":"https://cdn.pixabay.com/video/2026/08/03/368422_tiny.jpg","name":"Ai Generated, Cat, Ballerina","description":"Ai Generated, Cat, Ballerina, Pet, Animal, Funny Cat, Feline","license":"https://pixabay.com/service/license-summary/","acquireLicensePage":"/videos/ai-generated-cat-ballerina-pet-368422/","duration":"T0M5S","uploadDate":"2026-08-30T16:47:47.711Z","sourceOrganization":{"@type":"Organization","name":"Pixabay"}}</script>
'''

videos = PixabayClient._parse_search_page(search_html)
print(f"\n== {len(videos)} vídeos extraídos da listagem ==")
for v in videos:
    print(f"- [{v.id}] {v.title} | qualidade={v.quality_label} duração_txt={v.duration_text} "
          f"duração_seg={v.duration} url={v.url}")

assert len(videos) == 2
by_id = {v.id: v for v in videos}
assert by_id["336373"].quality_label == "4K"
assert by_id["336373"].duration_text == "0:06"
assert by_id["336373"].duration == 6
assert by_id["336373"].slug == "nature-jaguar-wildlife-rainforest"
assert by_id["368422"].quality_label == "SD"
assert by_id["368422"].duration == 5

print("\nTodos os testes offline passaram.")
