"""
Exemplo de uso do MagnificClient: buscar -> listar -> baixar.
"""
import json
from magnific_client import MagnificClient

client = MagnificClient(delay=0.5)

# 1) Buscar só vídeos GRÁTIS (assim o download sempre traz o clipe sem
#    marca d'água), com filtros de resolução/orientação
videos = client.search_all(
    query="dog",
    only_free=True,
    resolutions=["1080", "4k"],
    orientations=["horizontal"],
    max_pages=3,
)

print(f"Encontrados {len(videos)} vídeos únicos (só grátis).")

# 2) Salvar a lista de resultados como JSON — útil pro seu sistema de
#    edição escolher as "fontes" antes de baixar de fato.
with open("resultados_busca_magnific.json", "w", encoding="utf-8") as f:
    json.dump([v.to_dict() for v in videos], f, ensure_ascii=False, indent=2)

# 3) Mostrar um resumo
for v in videos[:5]:
    print(f"- [{v.id}] {v.name} ({v.quality}, {v.duration}s, "
          f"{'PREMIUM' if v.premium else 'grátis'}) | {v.url}")

# 4) Baixar os 3 primeiros (todos grátis, então baixa liso)
baixados = client.download_many(
    videos[:3],
    output_dir="videos",
    on_progress=lambda i, total, path: print(f"[{i}/{total}] baixado: {path}"),
)
print("\nArquivos salvos:", baixados)

# 5) Exemplo buscando COM premium incluso, mostrando como lidar com a
#    marca d'água: download_many pula premium por padrão e avisa.
videos_mistos = client.search_all(query="dog", max_pages=1)
print(f"\nBuscando sem filtro de licença: {len(videos_mistos)} vídeos "
      f"({sum(v.premium for v in videos_mistos)} premium, "
      f"{sum(not v.premium for v in videos_mistos)} grátis).")

client.download_many(videos_mistos[:5], output_dir="videos/mistos")
# Para baixar os premium mesmo com marca d'água:
# client.download_many(videos_mistos[:5], output_dir="videos/mistos", allow_watermarked=True)
