"""
Teste offline: valida o parsing usando itens reais de JSON (copiados do
que o usuário forneceu), sem precisar de acesso à internet.
"""
import json
from magnific_client import MagnificClient, MagnificClientError, WatermarkedDownloadError

# --------------------------------------------------------------------- #
# 1) Item PREMIUM (Jack Russell Terrier) -- preview só com marca d'água
# --------------------------------------------------------------------- #
premium_item = {
    "id": 3501651,
    "name": "Jack Russell Terrier feliz sentado em um campo",
    "created": "2024-10-25T20:58:29.000Z",
    "url": "/br/video-premium/jack-russell-terrier-feliz-sentado-campo_3501651",
    "quality": "4K",
    "premium": True,
    "duration": 22,
    "author": {"id": 43061619, "name": "Patramanskyi", "slug": "patramanskyi"},
    "thumbnails": [
        {"url": "https://videocdn.cdnpk.net/.../thumbnails/small.jpg", "width": 460, "height": 264},
        {"url": "https://videocdn.cdnpk.net/.../thumbnails/large.jpg", "width": 1280, "height": 720},
    ],
    "previews": [
        {"urlFallback": "https://videocdn.cdnpk.net/.../watermarked/small.mp4",
         "url": "https://videocdn.cdnpk.net/.../magnific_watermarked/small.mp4",
         "width": 455, "height": 235},
        {"urlFallback": "https://videocdn.cdnpk.net/.../watermarked/large.mp4",
         "url": "https://videocdn.cdnpk.net/.../magnific_watermarked/large.mp4",
         "width": 1364, "height": 720},
    ],
    "nativeOrientation": "horizontal",
    "nativeAspectRatio": "256:135",
    "isAIGenerated": False,
    "creditCost": 600,
}

video1 = MagnificClient._parse_item(premium_item)
print("== Item premium (Jack Russell Terrier) ==")
print(json.dumps(video1.to_dict(), indent=2, ensure_ascii=False))
assert video1.id == "3501651"
assert video1.premium is True
assert video1.watermarked is True
assert video1.download_url.endswith("magnific_watermarked/large.mp4")
assert video1.url == "https://www.magnific.com/br/video-premium/jack-russell-terrier-feliz-sentado-campo_3501651"

# --------------------------------------------------------------------- #
# 2) Item GRÁTIS (mulher com laptop e cachorro) -- preview "clear" com token
# --------------------------------------------------------------------- #
free_item = {
    "id": 167542,
    "name": "Jovem mulher trabalhando em seu laptop em casa ao lado de seu cachorro",
    "url": "/br/video-gratuito/jovem-mulher-trabalhando-laptop-casa-lado-cachorro_167542",
    "quality": "4K",
    "premium": False,
    "duration": 10,
    "author": {"id": 23, "name": "magnific", "slug": "magnific"},
    "thumbnails": [
        {"url": "https://videocdn.cdnpk.net/.../thumbnails/small.jpg", "width": 460, "height": 264},
        {"url": "https://videocdn.cdnpk.net/.../thumbnails/large.jpg", "width": 1280, "height": 720},
    ],
    "previews": [
        {"urlFallback": None,
         "url": "https://videocdn.cdnpk.net/.../clear/small.mp4?token=exp=1788112638~hmac=abc",
         "width": 455, "height": 235},
        {"urlFallback": None,
         "url": "https://videocdn.cdnpk.net/.../clear/large.mp4?token=exp=1788112638~hmac=def",
         "width": 1364, "height": 720},
    ],
    "nativeOrientation": "horizontal",
    "nativeAspectRatio": "16:9",
    "isAIGenerated": False,
    "creditCost": 150,
}

video2 = MagnificClient._parse_item(free_item)
print("\n== Item grátis (mulher com laptop) ==")
print(json.dumps(video2.to_dict(), indent=2, ensure_ascii=False))
assert video2.premium is False
assert video2.watermarked is False
assert video2.download_url.endswith("large.mp4?token=exp=1788112638~hmac=def")

# --------------------------------------------------------------------- #
# 3) Simula download_video: premium deve recusar, grátis deve "baixar"
#    (aqui só testamos a lógica de decisão, sem precisar de um Chrome de
#    verdade — por isso passamos uma sessão "falsa" mínima só pra
#    conseguir instanciar o cliente sem abrir um navegador de verdade)
# --------------------------------------------------------------------- #
class _FakeSession:
    """Substituto mínimo de ChromeSession, só pra este teste offline não
    precisar de um navegador real instalado. `download_video` só chega a
    usar isso DEPOIS de já ter decidido (com base em `watermarked`) se
    deveria ou não seguir em frente — é exatamente essa decisão que este
    bloco de teste quer validar.
    """
    def request(self, *args, **kwargs):
        raise RuntimeError("sessão falsa: sem rede de verdade neste teste offline")

    def download(self, *args, **kwargs):
        raise RuntimeError("sessão falsa: sem rede de verdade neste teste offline")


client = MagnificClient(session=_FakeSession())

try:
    client.download_video(video1)  # premium, sem allow_watermarked
    raise SystemExit("ERRO: deveria ter recusado o download do vídeo premium")
except WatermarkedDownloadError as e:
    print("\nOK: download de vídeo premium recusado por padrão:", e)

# Com allow_watermarked=True, ele passa da checagem e tenta baixar de
# verdade — aqui isso esbarra na sessão falsa (RuntimeError), o que já
# comprova que a checagem de marca d'água não bloqueou o caminho.
try:
    client.download_video(video1, allow_watermarked=True, output_dir="/tmp/_magnific_test")
    raise SystemExit("ERRO: deveria ter tentado baixar e esbarrado na sessão falsa")
except RuntimeError as e:
    print("OK: com allow_watermarked=True, passou da checagem e tentou baixar "
          f"(esbarrou na sessão falsa, como esperado neste teste offline): {e}")

# --------------------------------------------------------------------- #
# 4) Validação de filtros / parâmetros
# --------------------------------------------------------------------- #
params = MagnificClient._build_params(
    query="dog",
    page=2,
    locale="pt",
    only_free=True,
    resolutions=["1080", "4k"],
    duration_from=15,
    duration_to=20,
    fps=["24", "30", "gt60"],
    orientations=["horizontal", "square"],
)
print("\n== Params construídos ==")
print(params)
assert params["term"] == "dog"
assert params["page"] == 2
assert params["license[free]"] == 1
assert params["resolution[1080]"] == 1
assert params["resolution[4k]"] == 1
assert params["duration[from]"] == 15
assert params["duration[to]"] == 20
assert params["filters[fps][]"] == ["24", "30", "gt60"]
assert params["filters[orientations][]"] == ["horizontal", "square"]

try:
    MagnificClient._build_params(query="dog", resolutions=["9k"])
    raise SystemExit("ERRO: deveria ter rejeitado resolução inválida")
except MagnificClientError as e:
    print("OK, filtro de resolução inválido rejeitado:", e)

print("\nTodos os testes offline passaram.")
