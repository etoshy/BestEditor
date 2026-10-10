"""
Exemplo de uso do MixkitClient: buscar por categoria -> listar -> baixar
(com retry automático de qualidade).
"""
import json
from mixkit_client import MixkitClient

client = MixkitClient(delay=0.5)

# 1) Buscar uma categoria com filtros
videos = client.search_all(
    category="animal-nature",
    orientation="horizontal",
    duration="10-20s",
    max_pages=3,
)

print(f"Encontrados {len(videos)} vídeos únicos na categoria.")

# 2) Salvar a lista de resultados como JSON — útil pro seu sistema de
#    edição escolher as "fontes" antes de baixar de fato.
with open("resultados_busca_mixkit.json", "w", encoding="utf-8") as f:
    json.dump([v.to_dict() for v in videos], f, ensure_ascii=False, indent=2)

# 3) Mostrar um resumo
for v in videos[:5]:
    print(f"- [{v.id}] {v.title} ({'tem badge 4K' if v.has_4k_badge else 'sem badge 4K'}) | {v.url}")

# 4) Baixar os 3 primeiros, tentando a melhor qualidade disponível
#    (2160 -> 1080 -> 720 -> 360, com retry automático)
baixados = client.download_many(
    videos[:3],
    output_dir="videos",
    quality="best",
    on_progress=lambda i, total, path: print(f"[{i}/{total}] baixado: {path}"),
)
print("\nArquivos salvos:", baixados)

# 5) Exemplo pedindo uma qualidade específica (720), com fallback
#    automático para outra qualidade se 720 não existir para aquele vídeo
if videos:
    caminho = client.download_video(videos[0], output_dir="videos", quality=720)
    print(f"\nBaixado tentando 720 primeiro: {caminho} (qualidade real: {videos[0].resolved_quality})")
