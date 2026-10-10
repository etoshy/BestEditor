"""
Exemplo: usando o main.py como ponto único de entrada para buscar e
baixar vídeos de qualquer um dos cinco provedores, misturando resultados
das fontes numa lista só de "candidatos" para um sistema de edição.
"""
import json
from main import get_client

# --- Pexels ---
pexels = get_client("pexels", delay=0.5)
pexels_videos = pexels.search_all(
    query="dog and cats",
    orientation="landscape",
    people_count=2,
    max_pages=2,
)

# --- Pixabay ---
pixabay = get_client("pixabay", delay=0.6)
pixabay_videos = pixabay.search_all(
    query="gato cachorro",
    orientation="horizontal",
    content_type="authentic",
    max_pages=2,
)

# --- Magnific (só vídeos grátis, pra não esbarrar em marca d'água) ---
magnific = get_client("magnific", delay=0.5)
magnific_videos = magnific.search_all(
    query="dog",
    only_free=True,
    orientations=["horizontal"],
    max_pages=2,
)

# --- Mixkit (busca por categoria, não por termo livre) ---
mixkit = get_client("mixkit", delay=0.5)
mixkit_videos = mixkit.search_all(
    category="animal-nature",
    orientation="horizontal",
    max_pages=2,
)

# --- VistaCreate (download sempre vem em ~480p) ---
vistacreate = get_client("vistacreate", delay=0.5)
vistacreate_videos = vistacreate.search_all(
    query="animal nature",
    sort="popular",
    people="exclude",
    max_pages=2,
)

# --- Junta tudo numa lista única de "fontes" para o sistema de edição,
#     marcando de onde cada uma veio ---
fontes = (
    [{"provider": "pexels", **v.to_dict()} for v in pexels_videos]
    + [{"provider": "pixabay", **v.to_dict()} for v in pixabay_videos]
    + [{"provider": "magnific", **v.to_dict()} for v in magnific_videos]
    + [{"provider": "mixkit", **v.to_dict()} for v in mixkit_videos]
    + [{"provider": "vistacreate", **v.to_dict()} for v in vistacreate_videos]
)

print(f"Total de fontes combinadas: {len(fontes)}")
with open("fontes_combinadas.json", "w", encoding="utf-8") as f:
    json.dump(fontes, f, ensure_ascii=False, indent=2)

# --- Baixa só os 2 primeiros de cada provedor, usando o cliente certo
#     para cada um ---
clients = {
    "pexels": pexels,
    "pixabay": pixabay,
    "magnific": magnific,
    "mixkit": mixkit,
    "vistacreate": vistacreate,
}
grupos = {
    "pexels": pexels_videos[:2],
    "pixabay": pixabay_videos[:2],
    "magnific": magnific_videos[:2],
    "mixkit": mixkit_videos[:2],
    "vistacreate": vistacreate_videos[:2],
}

for provider, items in grupos.items():
    client = clients[provider]
    for item in items:
        path = client.download_video(item, output_dir=f"videos/{provider}")
        print(f"[{provider}] baixado em: {path}")
