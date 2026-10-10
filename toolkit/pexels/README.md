# Pexels Client — busca e download de vídeos (não-oficial)

Ferramenta Python para buscar e baixar vídeos do Pexels usando o mesmo
endpoint interno (`/en-us/api/v3/search/videos`) que o site usa na busca
avançada, e a página HTML de detalhe (`__NEXT_DATA__`) para pegar os links
de download de um vídeo específico. Não requer chave de API oficial.

> ⚠️ Isso usa uma rota interna do site, não a API pública documentada do
> Pexels. Ela pode mudar sem aviso e está sujeita aos Termos de Uso do
> Pexels — use com moderação (o parâmetro `delay` já coloca uma pausa
> entre requisições) e para os fins de uso pessoal/produção de vídeo que
> a licença Pexels permite.

## Arquivos

- `pexels_client.py` — a biblioteca (classe `PexelsClient` + `PexelsVideo`) e uma CLI simples.
- `exemplo_uso.py` — exemplo completo: buscar → listar → baixar.
- `test_parsing.py` — testes offline do parsing (não precisa de internet).

## Instalação

```bash
pip install requests
```

## Uso como biblioteca

```python
from pexels_client import PexelsClient

client = PexelsClient()

# Buscar com filtros, passeando por várias páginas
videos = client.search_all(
    query="dog and cats",
    orientation="landscape",   # landscape | portrait | square
    people_count=2,            # 0 | 1 | 2 | 3_plus
    people_age="adult",        # baby | child | teenager | adult | senior_adult
    min_duration=10,
    max_duration=115,
    frame_rate=25,             # 24 | 25 | 30 | 50 | 60_plus
    resolution_name="4K",      # 1080p | 4K | 8K
    date_from="last_month",    # last_24_hours | last_week | last_month | last_year
    max_pages=5,
    per_page=24,
)

for v in videos:
    print(v.id, v.title, v.duration, v.url)

# Baixar o primeiro resultado, na melhor qualidade
client.download_video(videos[0], output_dir="videos", quality="best")

# Baixar direto por URL da página do vídeo
client.download_video(
    "https://www.pexels.com/video/breathtaking-view-of-massive-waterfall-38233454/",
    output_dir="videos",
    quality="hd",   # best | worst | sd | hd | uhd
)

# Baixar vários de uma vez
client.download_many(videos[:10], output_dir="videos", quality="best")
```

### Filtros disponíveis (todos opcionais)

| Parâmetro         | Valores aceitos                                              |
|-------------------|----------------------------------------------------------------|
| `orientation`     | `landscape`, `portrait`, `square`                              |
| `people_count`    | `0`, `1`, `2`, `3_plus` (aceita `3` e converte automaticamente) |
| `people_age`      | `baby`, `child`, `teenager`, `adult`, `senior_adult`            |
| `min_duration`    | inteiro (segundos)                                              |
| `max_duration`    | inteiro (segundos)                                              |
| `frame_rate`      | `24`, `25`, `30`, `50`, `60_plus` (aceita `60` também)          |
| `resolution_name` | `1080p`, `4K`, `8K`                                             |
| `date_from`       | `last_24_hours`, `last_week`, `last_month`, `last_year`         |

Passar um valor fora dessa lista levanta `PexelsClientError` na hora,
antes mesmo de fazer a requisição.

## Uso pela linha de comando

```bash
# Buscar e salvar em JSON
python pexels_client.py search "dog and cats" --pages 3 --orientation landscape --people-count 2 --out resultados.json

# Baixar por URL
python pexels_client.py download "https://www.pexels.com/video/breathtaking-view-of-massive-waterfall-38233454/" --quality hd

# Baixar só pelo ID numérico
python pexels_client.py download 38233454 --quality uhd
```

## Como funciona por baixo dos panos

1. **Busca** (`search_html` / `search_all`, padrão): navega na página
   normal de resultados (`https://www.pexels.com/search/videos/<termo>/`)
   — exatamente a mesma que você vê no navegador — e faz parsing do HTML
   dos cards de vídeo (ignorando anúncios do Canva e vídeos patrocinados
   de terceiros como iStock, que não têm o padrão de link `/video/`
   seguido de um `<video src=...>` do próprio pexels.com). Isso é mais
   confiável do que bater na API JSON interna, porque é exatamente como
   um usuário de verdade busca — sem risco de bloqueio por navegação
   direta a um endpoint de API.

   Se essa página não abrir (ex: mudança de layout), `search_all()` cai
   automaticamente para a API JSON interna
   (`https://www.pexels.com/en-us/api/v3/search/videos`) como fallback —
   dá pra forçar esse caminho direto com `search_all(..., use_api=True)`.

2. **Detalhe de vídeo** (`get_video_by_url` / `get_video_by_id`): abre a
   página `/video/<slug>-<id>/` e tenta extrair o JSON do bloco
   `<script id="__NEXT_DATA__">` (dados completos: todos os `video_files`
   em sd/hd/uhd). Se esse bloco não existir, cai num fallback que lê
   direto do HTML: a descrição (atributo `title` do `<h1>`) e o
   `<video src=...>` de maior resolução disponível na própria página.

   Vídeos que vieram da busca via HTML (só com um preview de baixa
   resolução) são automaticamente "atualizados" para a qualidade completa
   na hora de baixar, chamando `get_video_by_url()` por trás — você não
   precisa fazer nada a mais pra isso funcionar.

3. **Download** (`download_video` / `download_many`): resolve o vídeo
   (por objeto, URL ou dict), escolhe o arquivo pela qualidade pedida
   (`best`, `worst`, `sd`, `hd`, `uhd`) e baixa em streaming para
   `output_dir`, sem carregar o arquivo inteiro na memória.

Teste esse fluxo offline (usando uma amostra real de HTML, sem precisar
de rede nem Chrome) com:

```bash
python test_search_html.py
```

## Integrando no seu sistema de edição de vídeo

`PexelsVideo.to_dict()` devolve um dicionário "achatado" (id, título,
tags, thumbnail, author, duração, todos os `video_files` com link e
resolução) — dá pra salvar isso direto como a lista de "fontes"
candidatas do seu sistema, deixar o usuário escolher, e só então chamar
`download_video(...)` para os que forem realmente usados na edição.
