# Pixabay Client — busca e download de vídeos (não-oficial)

Ferramenta Python para buscar e baixar vídeos do Pixabay usando a mesma
página de busca pública do site (`/videos/search/<termo>/`), sem precisar
de chave da API oficial (que é mais restrita em filtros).

> ⚠️ Isso faz scraping de HTML público, não usa a API oficial documentada
> do Pixabay. O layout pode mudar sem aviso e está sujeito aos Termos de
> Uso do Pixabay — use com moderação (o parâmetro `delay` já coloca uma
> pausa entre requisições).

## Como funciona por baixo dos panos

Diferente do Pexels (que tem um endpoint JSON interno), o Pixabay embute
os dados de cada vídeo em blocos `<script type="application/ld+json">`
(schema.org `VideoObject`) espalhados pela própria página HTML — tanto na
listagem de busca quanto na página de detalhe de cada vídeo. O cliente:

1. **Busca** (`search` / `search_all`): monta a URL
   `https://pixabay.com/videos/search/<termo com %20>/` com os parâmetros
   de filtro e página (`pagi`), extrai **todos** os blocos JSON-LD do tipo
   `VideoObject` da página (um por vídeo listado) e complementa cada um
   com a qualidade (`SD`/`HD`/`4K`) e duração exibida no card, que são
   lidas de perto do link "Edit video" da Canva (que sempre carrega
   `external-id=video%3A<ID>`, usado como âncora confiável para casar
   qualidade/duração com o ID certo).

   **Importante**: o `contentUrl` que aparece nesses blocos da *listagem*
   é só um preview (`..._tiny.mp4`), não o vídeo completo.

2. **Detalhe de vídeo** (`get_video_by_url` / `get_video_by_id`): abre a
   página `/videos/<slug>-<id>/` e extrai o bloco JSON-LD daquela página,
   cujo `contentUrl` já é o link real e completo (`..._large.mp4`), junto
   com autor, dimensões e licença.

3. **Download** (`download_video` / `download_many`): se o vídeo veio da
   busca (sem link de download ainda), o cliente automaticamente visita a
   página de detalhe para pegar o `download_url` real antes de baixar, em
   streaming, para não carregar tudo na memória.

## Instalação

```bash
pip install requests
```

## Uso como biblioteca

```python
from pixabay_client import PixabayClient

client = PixabayClient()

# Buscar com filtros, passeando por várias páginas
videos = client.search_all(
    query="gato cachorro",
    orientation="horizontal",     # horizontal | vertical
    animation=True,               # filtros de efeito (booleanos)
    slow_motion=False,
    time_lapse=False,
    resolution_hd=False,          # resolution_hd=1 / resolution_4k=1
    resolution_4k=True,
    date_from="last_month",       # NÃO — veja a tabela abaixo (é "1y" etc.)
    content_type="authentic",     # authentic | ai
    max_pages=5,
)

for v in videos:
    print(v.id, v.title, v.quality_label, v.duration_text, v.url)

# Baixar o primeiro resultado (resolve o link real automaticamente)
client.download_video(videos[0], output_dir="videos")

# Baixar direto por URL da página do vídeo
client.download_video(
    "https://pixabay.com/videos/leopard-cub-small-wildcat-106286/",
    output_dir="videos",
)

# Baixar vários de uma vez
client.download_many(videos[:10], output_dir="videos")
```

### Filtros disponíveis (todos opcionais)

| Parâmetro        | Valores aceitos                                  |
|-------------------|--------------------------------------------------|
| `orientation`     | `horizontal`, `vertical`                          |
| `animation`       | `True` / `False`                                  |
| `slow_motion`     | `True` / `False`                                  |
| `time_lapse`      | `True` / `False`                                  |
| `resolution_hd`   | `True` / `False`                                  |
| `resolution_4k`   | `True` / `False`                                  |
| `date_from`       | `1d`, `3d`, `1w`, `6m`, `1y`                       |
| `content_type`    | `authentic`, `ai`                                 |

Passar um valor fora dessa lista levanta `PixabayClientError` na hora,
antes mesmo de fazer a requisição. Não passar nenhum filtro faz a busca
"crua", igual ao Pexels.

## Uso pela linha de comando

```bash
# Buscar e salvar em JSON
python pixabay_client.py search "gato cachorro" --pages 3 --orientation vertical --content-type ai --out resultados.json

# Baixar por URL da página do vídeo
python pixabay_client.py download "https://pixabay.com/videos/leopard-cub-small-wildcat-106286/"
```

## Limitações conhecidas

- **`get_video_by_id` é uma aposta**: assim como no Pexels, ele monta a
  URL com um slug genérico (`video-<id>`). Isso pode não funcionar no
  Pixabay se o servidor validar o slug estritamente — prefira sempre usar
  a `url` que já vem nos resultados de `search_all`.
- A listagem não traz o autor nem as dimensões exatas do vídeo (isso só
  aparece no JSON-LD da página de detalhe); por isso `author`, `width` e
  `height` só ficam preenchidos depois de baixar ou chamar
  `get_video_by_url` explicitamente.
- O cliente assume que a página de detalhe sempre expõe o vídeo completo
  como `..._large.mp4` no `contentUrl` do JSON-LD principal — é o que foi
  observado no exemplo fornecido; se o Pixabay mudar isso, o parsing pode
  precisar de ajuste.

## Integrando no seu sistema de edição de vídeo

Igual ao cliente do Pexels, `PixabayVideo.to_dict()` devolve um
dicionário "achatado" (id, título, thumbnail, duração, qualidade, autor
quando disponível) — dá pra usar isso como a lista de "fontes"
candidatas do seu sistema antes de decidir quais vídeos baixar de fato
com `download_video(...)`.
