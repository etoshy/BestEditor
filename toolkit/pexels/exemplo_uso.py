"""
Exemplo de uso do PexelsClient, simulando como um sistema de edição de vídeo
usaria a ferramenta para: buscar -> listar -> escolher -> baixar.
"""
import json
from pexels_client import PexelsClient

client = PexelsClient(delay=0.5)  # 0.5s de pausa entre requisições

# 1) Buscar com filtros (equivalente à URL de exemplo que você mandou)
#    https://www.pexels.com/en-us/api/v3/search/videos?query=dog%20and%20cats
#        &page=3&per_page=24&people_count=2&orientation=landscape&seo_tags=true
videos = client.search_all(
    query="dog and cats",
    orientation="landscape",
    people_count=2,
    max_pages=3,       # vai rolando as páginas até 3 (ou até acabar antes)
    per_page=24,
)

print(f"Encontrados {len(videos)} vídeos únicos.")

# 2) Salvar a lista de resultados como JSON — útil pro seu sistema de edição
#    escolher as "fontes" antes de baixar de fato.
with open("resultados_busca.json", "w", encoding="utf-8") as f:
    json.dump([v.to_dict() for v in videos], f, ensure_ascii=False, indent=2)

# 3) Mostrar um resumo de cada vídeo (o que o seu sistema veria antes de decidir)
for v in videos[:5]:
    qualidades = sorted({f.get("quality") for f in v.video_files if f.get("quality")})
    print(f"- [{v.id}] {v.title} ({v.width}x{v.height}, {v.duration}s) "
          f"qualidades: {qualidades} | {v.url}")

# 4) Baixar apenas os 3 primeiros, na melhor qualidade disponível
baixados = client.download_many(
    videos[:3],
    output_dir="videos",
    quality="best",
    on_progress=lambda i, total, path: print(f"[{i}/{total}] baixado: {path}"),
)
print("\nArquivos salvos:", baixados)

# 5) Baixar um vídeo específico direto pela URL da página (como no seu exemplo)
caminho = client.download_video(
    "https://www.pexels.com/video/breathtaking-view-of-massive-waterfall-38233454/",
    output_dir="videos",
    quality="hd",
)
print("Vídeo específico salvo em:", caminho)
