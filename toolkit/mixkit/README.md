# Mixkit Client — busca e download de vídeos (não-oficial)

Ferramenta Python para buscar e baixar vídeos do Mixkit (mixkit.co) usando
as páginas de descoberta por categoria que o próprio site usa
(`/free-stock-video/discover/<categoria>/`), sem precisar de chave de API.

> ⚠️ Isso faz scraping de HTML público, não usa uma API oficial. O
> layout pode mudar sem aviso e está sujeito aos Termos de Uso do
> Mixkit — use com moderação (o parâmetro `delay` já coloca uma pausa
> entre requisições).

## Duas particularidades importantes deste provedor

### 1. Não é busca por palavra-chave, é navegação por categoria

Diferente do Pexels/Pixabay/Magnific, a página usada como referência
(`/free-stock-video/discover/animal-nature/`) navega por **categoria**
(`animal-nature` é o slug da categoria, não um termo de busca livre). Por
isso os métodos usam `category` em vez de `query`. Se o Mixkit tiver uma
busca por palavra-chave livre em outro endpoint, ela não foi mapeada
aqui.

### 2. A qualidade real do vídeo precisa ser descoberta por tentativa

O HTML da listagem sempre mostra o preview em **360p**
(`.../videos/<id>/<id>-360.mp4`). O arquivo em qualidade maior — 720p,
1080p ou 2160p (4K) — pode ou não existir para aquele vídeo específico
(alguns vídeos mais novos, inclusive, usam nomes de arquivo tipo hash sem
nenhum sufixo de resolução, ex: `assets.mixkit.co/228xstitup...`, e nesse
caso não há variação para tentar).

Por isso, `download_video()` **testa as variações em ordem de
preferência** (por padrão: 2160 → 1080 → 720 → 360) e salva a primeira
que responder com sucesso, sem baixar o arquivo duas vezes. Você pode:

- pedir `quality="best"` (padrão) ou `quality="worst"`;
- pedir uma qualidade específica como `quality=1080` — nesse caso ela é
  tentada primeiro, e se não existir, cai para as próximas melhores
  disponíveis automaticamente;
- para vídeos com asset tipo hash (sem sufixo de resolução), só existe
  uma opção e ela é usada diretamente, ignorando o parâmetro `quality`.

O bloco de banner promocional da Envato Elements que aparece no meio da
grade de resultados é **automaticamente ignorado** — ele não tem os
atributos `data-algolia-analytics-object-id="video-..."` que identificam
um card de vídeo de verdade, então nunca é capturado pelo parser (e o
cliente ainda tem uma checagem extra de segurança contra qualquer link
que aponte para `elements.envato.com`).

## Instalação

```bash
pip install requests
```

## Uso como biblioteca

```python
from mixkit_client import MixkitClient, QualityNotFoundError

client = MixkitClient()

# Buscar com filtros, passeando por várias páginas de uma categoria
videos = client.search_all(
    category="animal-nature",
    orientation="horizontal",     # horizontal | vertical
    resolution="4k",              # único valor confirmado
    duration="10-20s",            # "0-5s" | "5-10s" | "10-20s" | "20s-"
    sort="newest",
    max_pages=5,
)

for v in videos:
    print(v.id, v.title, v.has_4k_badge, v.url)

# Baixar tentando a melhor qualidade disponível (com retry automático)
client.download_video(videos[0], output_dir="videos")

# Pedindo uma qualidade específica, com fallback automático
client.download_video(videos[0], output_dir="videos", quality=1080)

try:
    client.download_video(videos[0], output_dir="videos")
except QualityNotFoundError as e:
    print("Nenhuma variação respondeu:", e)

# Baixar vários de uma vez (pula, com aviso, os que falharem em todas as qualidades)
client.download_many(videos[:10], output_dir="videos")
```

### Filtros disponíveis (todos opcionais)

| Parâmetro     | Valores aceitos                                          |
|----------------|-----------------------------------------------------------|
| `orientation`  | `horizontal`, `vertical`                                   |
| `resolution`   | `4k` (confirmado); outros valores podem funcionar mas não foram testados |
| `duration`     | `0-5s`, `5-10s`, `10-20s`, `20s-` (confirmados)             |
| `sort`         | `newest` (confirmado)                                       |

Não passar nenhum filtro faz a busca "crua", igual aos outros clientes.

## Uso pela linha de comando

```bash
# Buscar e salvar em JSON
python mixkit_client.py search "animal-nature" --pages 3 --orientation horizontal --duration 10-20s --out resultados.json

# Baixar por URL da página do vídeo (melhor esforço — veja limitações abaixo)
python mixkit_client.py download "https://mixkit.co/free-stock-video/lizard-looking-for-dinner-in-nature-1484/" --quality best
```

## Limitações conhecidas

- **`get_video_by_url` é melhor esforço, não confirmado.** O parsing da
  página de detalhe reaproveita a mesma lógica da listagem, assumindo que
  o Mixkit usa o mesmo componente `item-grid-video-player` lá também.
  Isso **não foi verificado** com uma amostra real dessa página — se o
  layout for diferente, o método pode não encontrar nada. Prefira sempre
  guardar os objetos `MixkitVideo` retornados por `search_all()` em vez
  de depender de re-visitar a página do vídeo.
- **Não há endpoint de busca por palavra-chave confirmado** — só
  navegação por categoria (`category`).
- **A qualidade real só é conhecida depois do download.** Antes de
  baixar, `resolved_quality` e `download_url` ficam `None` no
  `MixkitVideo`; eles só são preenchidos depois de uma tentativa de
  download bem-sucedida.
- Vídeos com asset tipo hash (sem sufixo de resolução no nome do arquivo)
  não têm variações de qualidade para tentar — o cliente baixa o único
  link disponível.

## Integrando no seu sistema de edição de vídeo

Igual aos outros clientes, `MixkitVideo.to_dict()` devolve um dicionário
"achatado" (id, título, thumbnail, preview, badge de 4K) — dá pra usar
isso como lista de "fontes" candidatas do seu sistema. Como a qualidade
real só é confirmada no momento do download, é normal que
`download_url`/`resolved_quality` só apareçam preenchidos depois de
baixar pelo menos uma vez.
