# Busca de Imagens Unificada

Yandex + Bing + Brave + Startpage em **uma só API** (e uma só linha de comando).
Os 4 motores originais estão em `unified_images/engines/` **sem nenhuma alteração**;
a camada unificada chama o `search_images_batch()` de cada um, padroniza a saída e faz,
igual para todos, a visita aos sites de origem e o download.

## O que ela faz

- **Vários buscadores numa chamada** (`engines`): sequencial (padrão) ou em paralelo.
- **Várias buscas em sequência** (`queries`): cada buscador abre o navegador uma vez e faz as buscas
  na mesma aba (como já fazia), com `limit` e `orientation` diferentes por termo.
- **Todos os filtros existentes**: os comuns (proporção `orientation`, `limit`, `square_tolerance`)
  valem em todos; os próprios de cada buscador (Bing: `aspect`, `size`, `animated`, `transparent`…;
  Startpage: `max_pages`, `language`…) entram em `engine_options`.
- **Acesso aos sites de origem em TODOS os buscadores** (`inspect_sources`), com a mesma política do Yandex:
  Google e outros buscadores bloqueados como origem, limite por site (1–500).
- **Uma pasta com ID único por requisição**, com as imagens em `imagens/` e o `imagens.json`.

## Instalação (Windows / PowerShell)

Python 3.10 ou superior.

```powershell
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Subir a API

```powershell
python -m unified_images serve
```

Swagger: `http://127.0.0.1:8010/docs`. As pastas das requisições ficam em `.\saidas\`
(mude com a variável de ambiente `UNIFIED_IMAGES_DIR`).

### Exemplo (PowerShell)

```powershell
$body = @{
  queries = @("gojo", @{ q = "geto"; limit = 10; orientation = "vertical" })
  engines = @("yandex", "bing", "brave", "startpage")
  limit = 5
  orientation = "horizontal"
  engine_options = @{ bing = @{ aspect = "wide"; size = "large" } }
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8010/api/search -ContentType "application/json" -Body $body
```

### Por querystring (GET)

```text
/api/search?q=gojo&q=geto&engines=yandex,bing&limit=5&orientation=vertical&bing_aspect=tall
```

Filtros próprios entram com o prefixo do buscador: `bing_aspect=wide`, `startpage_max_pages=3`, `brave_click_details=false`.

### Execução longa (segundo plano)

Buscas com navegador demoram. Com `"background": true` (ou `&background=true`) a API responde na hora
`202 {"request_id": "...", "status_url": "..."}` e você acompanha em `GET /api/requests/{request_id}`
(`status`: `queued` → `running` → `ok` | `partial` | `error`, com `stage` e os buscadores já concluídos).

### Outras rotas

| Rota | O que faz |
|---|---|
| `GET /api/engines` | buscadores, filtros e valores aceitos |
| `GET /api/requests` | requisições já feitas |
| `GET /api/requests/{id}` | `imagens.json` da requisição |
| `GET /api/requests/{id}/imagens/{arquivo}` | devolve uma imagem salva |

## Linha de comando

```powershell
python -m unified_images search -q gojo -q geto --engines yandex bing --limit 5 --orientation vertical
python -m unified_images search -q gojo --opt bing.aspect=wide --opt startpage.max_pages=3
python -m unified_images search -q gojo --inspect-sources --download-mode source --max-images-per-site 20
python -m unified_images search -q gojo --no-download          # só lista
python -m unified_images engines                              # filtros de cada buscador
```

## A pasta de cada requisição

```text
saidas/
└── 20261001-110753_cf2e64ba/        <- ID único (data-hora + 8 caracteres aleatórios)
    ├── imagens/
    │   ├── 0001_yandex_gojo.jpg
    │   └── 0002_bing_foto.png
    └── imagens.json
```

Cada item de `imagens` em `imagens.json`:

```jsonc
{
  "id": 1,
  "name": "gojo.jpg",                       // nome da imagem
  "file": "imagens/0001_yandex_gojo.jpg",   // onde foi salva
  "downloaded": true,
  "original_url": "https://cdn.example/gojo.jpg",
  "og": { "og:image": "https://site-a.example/p/og.jpg" },   // og/twitter:image da página de origem
  "source_page": "https://site-a.example/p",
  "origin": ["direct"],                     // direct = imagem do resultado | source = achada no site de origem
  "engines": ["yandex", "bing"],            // quem achou (a mesma URL não é baixada duas vezes)
  "queries": ["gojo"],
  "title": "Gojo Satoru", "width": 1280, "height": 720, "orientation": "horizontal",
  "bytes": 70213, "content_type": "image/jpeg",
  "download_url_used": "https://cdn.example/gojo.jpg",
  "error": null,
  "found_by": [{ "engine": "yandex", "query": "gojo", "rank": 1 }]
}
```

Além de `imagens`, o arquivo traz `request` (parâmetros usados), `totals`, `engines` (resultado e erro de cada
buscador/busca), `warnings`, `sites` (catálogo de cada página de origem, com o `og` e as imagens achadas) e
`results` (todos os resultados dos buscadores, antes da deduplicação).

`og` só vem preenchido quando a página de origem foi aberta (`inspect_sources` ou `download_mode` `source`/`both`).

## Modos de download (`download_mode`)

| Modo | Baixa |
|---|---|
| `direct` (padrão) | a imagem de cada resultado (se falhar, tenta a thumbnail/proxy do buscador) |
| `source` | todas as imagens encontradas na página de origem de cada resultado (implica `inspect_sources`) |
| `both` | os dois |

Com `inspect_sources=true` e `direct`, as páginas de origem são abertas e catalogadas (aparecem em `sites` e
preenchem o `og`), mas só as imagens dos resultados são salvas.

## Filtros

**Comuns (todos os buscadores):** `limit` (por busca, em cada buscador), `orientation`
(`any|horizontal|vertical|square`; aceita `qualquer`, `quadrada`, `retrato`…), `square_tolerance`.
Como antes, o `limit` conta só imagens que passam no filtro de proporção.

**Próprios de cada buscador (`engine_options`):**

| Buscador | Opções |
|---|---|
| yandex | — (proporção medida pela thumbnail) |
| bing | `aspect` (wide/tall/square), `size` (large/wallpaper/medium/small), `animated`, `transparent`, `extra_qft`, `mkt`, `click_details`, `submit_method` |
| brave | `click_details` (precisa estar ligado para o Brave informar a página de origem) |
| startpage | `click`, `submit_method`, `max_pages`, `language` |

**Origens:** `inspect_sources`, `max_images_per_site`, `allow_google_source`, `allow_search_engine_sources`,
`min_source_side` (ignora imagens de origem menores que N px quando o tamanho é conhecido — ícones e pixels).

**Execução:** `headless` (padrão `false`, como nos originais: assim dá para resolver um captcha),
`pause_between_ms`, `parallel_engines`, `download_concurrency`, `keep_raw` (guarda `_bruto/` com o JSON bruto de cada motor).

## Como cada buscador entra

- Os motores são chamados com `download=False`; quem baixa é o downloader unificado (valida que o arquivo é mesmo uma
  imagem pelos bytes, nomeia pela extensão real, repete sem `Referer` em 401/403).
- **Yandex** descobre a página de origem abrindo o detalhe do resultado, o que exige a sessão dele; por isso é o único
  que cataloga as origens dentro do próprio motor. Bing, Brave e Startpage já trazem a página de origem no resultado e
  usam o mesmo catalogador (`inspect_source_page` do Yandex) na camada unificada.
- Um buscador que falha (captcha, mudança de página) **não derruba os outros**: aparece em `engines.<nome>.error` e o
  `status` fica `partial`.

## Segurança

- A API escuta só em `127.0.0.1`. Não exponha na internet sem autenticação.
- O downloader recusa URLs que apontam para endereços privados/locais (evita que uma página maliciosa faça o programa
  acessar a sua rede). Para liberar: `UNIFIED_IMAGES_ALLOW_PRIVATE_HOSTS=1`.
- Verificações anti-bot (captcha, Anubis) **não são contornadas**: resolva no navegador visível ou a busca daquele
  buscador falha com mensagem clara.
- `UNIFIED_IMAGES_MAX_CONCURRENT` (padrão 1) limita quantas requisições rodam ao mesmo tempo (cada uma abre Chromium).

## Testes

```powershell
python -m unittest discover -s tests -t .
```

Cobrem validação, adaptadores (conferidos contra o código real dos 4 motores), downloader (servidor HTTP local),
orquestrador (motores simulados), política de origens e segurança de caminhos. **Não** acessam os buscadores reais.
