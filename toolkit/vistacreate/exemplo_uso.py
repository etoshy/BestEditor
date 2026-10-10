"""
Exemplo de uso do VistaCreateClient: buscar -> listar -> baixar.
"""
import json
from vistacreate_client import VistaCreateClient

client = VistaCreateClient(delay=0.5)

# 1) Buscar com filtros
videos = client.search_all(
    query="animal nature",
    sort="popular",
    people="exclude",
    max_pages=3,
)

print(f"Encontrados {len(videos)} vídeos únicos.")

# 2) Salvar a lista de resultados como JSON — útil pro seu sistema de
#    edição escolher as "fontes" antes de baixar de fato.
with open("resultados_busca_vistacreate.json", "w", encoding="utf-8") as f:
    json.dump([v.to_dict() for v in videos], f, ensure_ascii=False, indent=2)

# 3) Mostrar um resumo
for v in videos[:5]:
    print(f"- [{v.id}] {v.title} ({'premium' if v.premium else 'grátis'}) | {v.url or '(sem link direto)'}")

# 4) Baixar os 3 primeiros — todos vêm em ~480p ("small"), grátis ou premium
baixados = client.download_many(
    videos[:3],
    output_dir="videos",
    on_progress=lambda i, total, path: print(f"[{i}/{total}] baixado: {path}"),
)
print("\nArquivos salvos:", baixados)
