"""
Exemplo de uso do PixabayClient: buscar -> listar -> escolher -> baixar.
"""
import json
from pixabay_client import PixabayClient

client = PixabayClient(delay=0.6)

# 1) Buscar com filtros (equivalente à URL de exemplo que você mandou)
#    https://pixabay.com/videos/search/gato%20cachorro/
#        ?content_type=ai&date=1y&orientation=vertical
videos = client.search_all(
    query="gato cachorro",
    orientation="vertical",
    content_type="ai",
    date_from="1y",
    max_pages=3,
)

print(f"Encontrados {len(videos)} vídeos únicos.")

# 2) Salvar a lista de resultados como JSON — útil pro seu sistema de edição
#    escolher as "fontes" antes de baixar de fato.
with open("resultados_busca_pixabay.json", "w", encoding="utf-8") as f:
    json.dump([v.to_dict() for v in videos], f, ensure_ascii=False, indent=2)

# 3) Mostrar um resumo de cada vídeo
for v in videos[:5]:
    print(f"- [{v.id}] {v.title} ({v.quality_label}, {v.duration_text}) | {v.url}")

# 4) Baixar os 3 primeiros (o cliente resolve o link real de download
#    automaticamente, visitando a página de cada vídeo)
baixados = client.download_many(
    videos[:3],
    output_dir="videos",
    on_progress=lambda i, total, path: print(f"[{i}/{total}] baixado: {path}"),
)
print("\nArquivos salvos:", baixados)

# 5) Baixar um vídeo específico direto pela URL da página (como no seu exemplo)
caminho = client.download_video(
    "https://pixabay.com/videos/leopard-cub-small-wildcat-106286/",
    output_dir="videos",
)
print("Vídeo específico salvo em:", caminho)
