# VistaCreate Client — busca e download de vídeos (não-oficial)

Ferramenta Python para buscar e baixar vídeos do VistaCreate
(create.vista.com) usando a página pública de busca
(`/pt/videos/<termo>/`), sem precisar de chave de API.

> ⚠️ Isso faz scraping de HTML público, não usa uma API oficial. O
> layout pode mudar sem aviso e está sujeito aos Termos de Uso do
> VistaCreate — use com moderação (o parâmetro `delay` já coloca uma
> pausa entre requisições).

## A particularidade deste provedor: qualidade sempre em ~480p

Diferente dos outros clientes deste toolkit, aqui **não é preciso
visitar nenhuma página extra** para conseguir o link de download — a
própria listagem de busca já expõe tudo que é necessário.

Cada item na listagem tem uma imagem de preview apontando para:

```
https://cdn.create.vista.com/api/media/small/<id>/<slug>?videoStaticPreview=true&token=<token>
```

O parâmetro `videoStaticPreview=true` faz o servidor devolver uma
**imagem** estática em vez do vídeo. Removendo esse parâmetro, a mesma
URL devolve o **arquivo de vídeo de verdade**:

```
https://cdn.create.vista.com/api/media/small/<id>/<slug>?token=<token>
```

Só que esse endpoint usa o tamanho `small`, que **serve o vídeo sempre em
~480p** — tanto para itens grátis quanto para os marcados como
`premium` (selo de diamante na listagem, que normalmente indica que a
versão em resolução maior exige assinatura do VistaCreate Pro).

**Atualização: retry experimental de qualidade.** O caminho da URL tem
o padrão `/api/media/<tamanho>/<id>/<slug>`, e `small` foi o único
tamanho **confirmado** (é o que a listagem usa). É plausível que
`medium` e `large` também existam nesse mesmo endpoint (é um padrão
comum em CDNs de banco de imagem/vídeo), então `download_video()` agora
aceita um parâmetro `quality` que tenta essas variações automaticamente:

- `quality="small"` (padrão) — comportamento de sempre, garantido.
- `quality="best"` — tenta `large` → `medium` → `small`, ficando com o
  primeiro que responder com sucesso.
- `quality="large"` / `quality="medium"` — tenta esse tamanho primeiro,
  com fallback automático para os outros se não existir.
- `quality="worst"` — tenta `small` → `medium` → `large`.

**Isso é experimental e não confirmado** — se `medium`/`large` não
existirem de verdade, o cliente simplesmente cai para `small` sem erro
(a menos que nem `small` funcione, aí levanta `MediaSizeNotFoundError`).
Rode o teste ao vivo do toolkit (`run_live_tests.py`, na raiz do
projeto) para descobrir, no seu ambiente, se esses tamanhos maiores
realmente existem — o resultado fica registrado no log.

## Instalação

```bash
pip install requests
```

## Uso como biblioteca

```python
from vistacreate_client import VistaCreateClient

client = VistaCreateClient()

# Buscar com filtros, passeando por várias páginas
videos = client.search_all(
    query="animal nature",
    sort="popular",          # newest | popular
    isolated="exclude",      # include | exclude (fundo isolado)
    people="exclude",        # include | exclude (presença de pessoas)
    max_pages=5,
)

for v in videos:
    print(v.id, v.title, v.premium, v.url)

# Baixar o primeiro resultado (padrão: "small", ~480p, garantido)
client.download_video(videos[0], output_dir="videos")

# Tentativa experimental de conseguir resolução maior
client.download_video(videos[0], output_dir="videos", quality="best")
print("Qualidade que funcionou:", videos[0].resolved_quality)  # ex: "small" se large/medium não existirem

# Baixar vários de uma vez
client.download_many(videos[:10], output_dir="videos")
```

### Filtros disponíveis (todos opcionais)

| Parâmetro   | Valores aceitos            |
|-------------|------------------------------|
| `sort`      | `newest`, `popular`           |
| `isolated`  | `include`, `exclude`          |
| `people`    | `include`, `exclude`          |

Não passar nenhum filtro faz a busca "crua", igual aos outros clientes.

> Os botões de filtro de **resolução** (720p/1080p/4K) e a aba de
> ordenação **"Tendência"** aparecem na interface do site, mas os
> parâmetros de URL correspondentes não foram confirmados com um
> exemplo real — por isso não estão implementados aqui. Se descobrir os
> nomes exatos desses parâmetros, é só adicionar em `_build_params()`.

## Uso pela linha de comando

```bash
# Buscar e salvar em JSON
python vistacreate_client.py search "animal nature" --pages 3 --sort popular --people exclude --out resultados.json

# Baixar um vídeo específico pelo ID (a listagem não expõe um endpoint de
# detalhe por ID sozinho, então o cliente re-busca pelo termo e filtra)
python vistacreate_client.py download "animal nature" 849076422 --output-dir videos

# Tentativa experimental de resolução maior
python vistacreate_client.py download "animal nature" 849076422 --output-dir videos --quality best
```

## Limitações conhecidas

- **`small` é o único tamanho confirmado.** `medium`/`large` são uma
  hipótese razoável, testada via retry automático, mas não confirmada —
  veja a seção acima.
- **Itens `premium` não têm link de página (`url`).** Eles aparecem na
  listagem sem o `<a href>` clicável que os itens grátis têm (o clique
  neles abre um modal de assinatura em vez de navegar) — por isso `url`
  fica `None` para esses casos, mas o download continua funcionando
  normalmente via `download_url`.
- **Filtro de resolução (720p/1080p/4K) não implementado** — os botões
  aparecem na interface do site, mas os parâmetros de URL correspondentes
  não foram confirmados com um exemplo real.
- **Sem descrição em prosa.** O site não expõe nada parecido em lugar
  nenhum (nem na listagem, nem na página do vídeo). Em vez disso,
  `download_video()` tenta buscar automaticamente **tags** e o nome do
  **autor** na página do vídeo (campos `tags`/`author` em
  `VistaCreateVideo`) — melhor esforço, não confirmado contra o HTML
  bruto real da página de detalhe (só tive acesso ao texto renderizado
  ao investigar). Se notar que isso nunca captura nada de verdade, abra
  a página de um vídeo, salve o HTML e me manda que eu ajusto o regex
  em `_TAG_LINK_RE`/`_AUTHOR_RE`.
- O `token` que aparece na URL de mídia pode ter validade limitada; se
  demorar muito entre buscar e baixar, pode ser necessário buscar de
  novo para obter um token válido.

## Integrando no seu sistema de edição de vídeo

Igual aos outros clientes, `VistaCreateVideo.to_dict()` devolve um
dicionário "achatado" (id, título, thumbnail, se é premium, link de
download) — dá pra usar isso como lista de "fontes" candidatas do seu
sistema. Como a qualidade é sempre ~480p aqui, esse provedor é mais
adequado para rascunhos/protótipos de edição do que para entrega final
em alta resolução.
