# Magnific Client — busca e download de vídeos (não-oficial)

Ferramenta Python para buscar e baixar vídeos do Magnific (magnific.com,
Freepik) usando o mesmo endpoint de busca que o site usa
(`/api/videos?format[search]=1`), sem precisar de chave de API oficial.

> ⚠️ Isso usa um endpoint interno do site, não uma API pública
> documentada. Está sujeito aos Termos de Uso do Magnific/Freepik — use
> com moderação (o parâmetro `delay` já coloca uma pausa entre
> requisições).

## Como funciona, e a diferença importante: grátis vs. premium

Diferente do Pexels e do Pixabay, aqui **a própria resposta da busca já
contém os links de preview/download** — não é preciso visitar uma página
de detalhe separada. Mas o link disponível **depende da licença do
vídeo**:

- **Vídeos grátis** (`"premium": false`): o preview retornado é um MP4
  **sem marca d'água** (pasta `clear/` na URL), com um token de acesso
  temporário — é o arquivo completo, pronto pra usar.
- **Vídeos premium** (`"premium": true`): o preview retornado está
  **sempre com marca d'água** (pasta `watermarked/` ou
  `magnific_watermarked/` na URL). O arquivo final sem marca d'água só é
  liberado dentro do site, mediante login e consumo de créditos — isso
  está **fora do escopo deste cliente**, que não faz nenhum tipo de
  bypass de paywall.

Por isso, `download_video()` **recusa por padrão** baixar vídeos
premium (levanta `WatermarkedDownloadError`), a não ser que você passe
`allow_watermarked=True` explicitamente — aí ele baixa o preview com
marca d'água mesmo, como o site expõe publicamente.

## Instalação

```bash
pip install requests
```

## Uso como biblioteca

```python
from magnific_client import MagnificClient, WatermarkedDownloadError

client = MagnificClient()

# Buscar com filtros, passeando por várias páginas
videos = client.search_all(
    query="dog",
    only_free=True,                       # só vídeos grátis (recomendado)
    resolutions=["1080", "4k"],           # 720 | 1080 | 2k | 4k | 8k
    orientations=["horizontal"],          # horizontal | vertical | square
    fps=["24", "30"],                     # 24 | 25 | 30 | 60 | gt60
    duration_from=10, duration_to=60,     # em segundos
    ai_generated="excluded",              # "excluded" | "only"
    max_pages=5,
)

for v in videos:
    print(v.id, v.name, v.quality, v.premium, v.url)

# Baixar o primeiro resultado
client.download_video(videos[0], output_dir="videos")

# Tentando baixar um vídeo premium sem autorização explícita:
try:
    client.download_video(video_premium, output_dir="videos")
except WatermarkedDownloadError as e:
    print("Recusado:", e)

# Baixando o preview com marca d'água mesmo assim:
client.download_video(video_premium, output_dir="videos", allow_watermarked=True)

# Baixar vários de uma vez (pula premium automaticamente por padrão)
client.download_many(videos[:10], output_dir="videos")
```

### Filtros disponíveis (todos opcionais)

| Parâmetro        | Valores aceitos                                   |
|-------------------|---------------------------------------------------|
| `only_free`       | `True` / `False` — só vídeos com licença grátis    |
| `only_premium`    | `True` / `False` — só vídeos premium               |
| `ai_generated`    | `excluded`, `only`                                 |
| `resolutions`     | lista com `720`, `1080`, `2k`, `4k`, `8k`          |
| `duration_from`   | inteiro (segundos)                                 |
| `duration_to`     | inteiro (segundos)                                 |
| `fps`             | lista com `24`, `25`, `30`, `60`, `gt60`           |
| `orientations`    | lista com `horizontal`, `vertical`, `square`       |
| `locale`          | código de idioma, ex: `pt`, `en` (padrão: `pt`)    |

Não passar nenhum filtro faz a busca "crua", igual aos outros clientes.

## Uso pela linha de comando

```bash
# Buscar e salvar em JSON
python magnific_client.py search "dog" --pages 3 --only-free --resolution 1080 --resolution 4k --out resultados.json

# Baixar um vídeo específico pelo ID (a API não tem endpoint de detalhe
# por ID, então o cliente re-busca pelo termo e filtra pelo ID encontrado)
python magnific_client.py download "dog" 167542 --output-dir videos
python magnific_client.py download "dog" 3501651 --output-dir videos --allow-watermarked
```

## Limitações conhecidas

- **Não existe endpoint de detalhe por ID.** Para baixar um vídeo
  específico sem repetir a busca inteira, guarde o objeto `MagnificVideo`
  (ou o resultado de `.to_dict()`) que veio da busca — ele já tem tudo
  (`download_url` incluso), então normalmente você **não precisa**
  buscar de novo. A CLI `download` só faz isso porque recebe apenas
  texto na linha de comando.
- **Sem descrição autoral.** O site só expõe um "nome" curto — não há
  descrição escrita por quem enviou o vídeo em lugar nenhum.
  `download_video()` busca automaticamente a meta-tag `description` da
  página do vídeo e preenche `MagnificVideo.description`, mas essa frase
  é **gerada pelo próprio site** em cima do nome (algo como "Download
  this free video of `<nome>` and explore millions of professional
  stock videos on Magnific."), não uma descrição distinta e autoral.
  Confirmado com HTML real da página, mas ainda assim é só um texto
  templated — não espere mais informação do que o nome já dá.
- Termos de busca "especiais" vistos em alguns exemplos (tipo
  `dog --variety` ou `dog --variety:50`) parecem ser comandos internos
  do site (possivelmente ligados a geração por IA) e não têm efeito
  documentado — o cliente só repassa o texto do `term` como está, sem
  interpretar esse tipo de sintaxe.
- Os links de preview (grátis ou com marca d'água) carregam um token
  temporário na URL; se demorar muito entre buscar e baixar, o link pode
  expirar e será preciso buscar de novo.

## Integrando no seu sistema de edição de vídeo

Igual aos outros dois clientes, `MagnificVideo.to_dict()` devolve um
dicionário "achatado" (id, nome, thumbnail, duração, se é premium, se o
download disponível tem marca d'água) — dá pra usar isso como a lista de
"fontes" candidatas do seu sistema. Recomendado filtrar por
`only_free=True` na busca se o objetivo é automatizar downloads sem
intervenção manual, já que vídeos premium sempre exigem a decisão
explícita `allow_watermarked=True`.
