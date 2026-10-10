# Video Sources Toolkit — Pexels + Pixabay + Magnific + Mixkit + VistaCreate

Toolkit em Python para buscar e baixar vídeos de estoque de cinco
provedores diferentes — **Pexels**, **Pixabay**, **Magnific**, **Mixkit**
e **VistaCreate** — usando um ponto de entrada único (`main.py`) para
escolher qual usar, sem precisar de chave de API oficial em nenhum deles.

```
video_sources_toolkit/
├── main.py                  <- ponto de entrada único (escolhe o provedor, 1 por vez)
├── run_batch.py             <- roda busca + download em lote nos 5, via toolkit_config.json
├── generate_config.py       <- gera/mostra o toolkit_config.json (config por site)
├── download_manager.py      <- manifesto de downloads + concorrência + retry + metadados
├── video_metadata.py        <- liga título/descrição ao vídeo (sidecar .json/.txt + embed via ffmpeg)
├── browser_session.py       <- sessão de Chrome real (Selenium) usada pelos 5 clientes
├── pexels_api_client.py     <- Pexels via API oficial (sem Chrome, imune a Cloudflare)
├── api_keys.py              <- pool de chaves de API com rotação + loader de .env
├── .env.example             <- template do .env (PEXELS_API_KEYS)
├── test_resource_optimization.py <- teste offline: sessão compartilhada + flags low_resource
├── test_api_keys.py         <- teste offline: rotação de chaves + loader de .env
├── test_pexels_api_client.py <- teste offline: cliente da API oficial do Pexels
├── test_description_enrichment.py <- teste offline: descrição/tags via páginas públicas
├── toolkit_config.json      <- config gerada (edite os valores por site aqui)
├── run_live_tests.py        <- teste ao vivo (rede real) dos 5 provedores, log em .txt
├── exemplo_combinado.py     <- exemplo usando os provedores juntos
├── pexels/
│   ├── pexels_client.py     <- cliente completo do Pexels (scraping por navegador)
│   ├── exemplo_uso.py       <- exemplo isolado, só Pexels
│   ├── test_parsing.py      <- testes offline do parsing
│   ├── test_search_html.py  <- teste offline: busca via página HTML real
│   └── README.md            <- documentação completa do cliente Pexels
├── pixabay/
│   ├── pixabay_client.py    <- cliente completo do Pixabay
│   ├── exemplo_uso.py       <- exemplo isolado, só Pixabay
│   ├── test_parsing.py      <- testes offline do parsing
│   └── README.md            <- documentação completa do cliente Pixabay
├── magnific/
│   ├── magnific_client.py   <- cliente completo do Magnific
│   ├── exemplo_uso.py       <- exemplo isolado, só Magnific
│   ├── test_parsing.py      <- testes offline do parsing
│   └── README.md            <- documentação completa do cliente Magnific
├── mixkit/
│   ├── mixkit_client.py     <- cliente completo do Mixkit
│   ├── exemplo_uso.py       <- exemplo isolado, só Mixkit
│   ├── test_parsing.py      <- testes offline do parsing
│   └── README.md            <- documentação completa do cliente Mixkit
└── vistacreate/
    ├── vistacreate_client.py <- cliente completo do VistaCreate
    ├── exemplo_uso.py         <- exemplo isolado, só VistaCreate
    ├── test_parsing.py        <- testes offline do parsing
    └── README.md              <- documentação completa do cliente VistaCreate
```

Cada cliente é **independente e completo** — pode ser usado sozinho,
como antes (veja o `README.md` de cada pasta para a documentação
detalhada, incluindo a tabela de filtros aceitos por cada provedor). O
`main.py` só adiciona uma camada fina por cima para quem quer trocar de
fonte sem trocar de script.

**Arquitetura: sessão de Chrome real (Selenium), não `requests` cru.**
Os 5 clientes navegam usando um Chrome de verdade (`browser_session.py` →
`ChromeSession`), em vez de fazer requisições HTTP diretas. Isso existe
porque os sites têm proteção anti-bot que bloqueia clientes HTTP crus —
um navegador real executa JavaScript e se comporta como um usuário de
verdade, o que reduz bem mais o risco de bloqueio do que qualquer truque
de header. Por isso é necessário ter o Google Chrome instalado na
máquina (o Selenium baixa o driver correspondente sozinho, na primeira
execução, desde que haja acesso à internet para isso).

> Não usamos rotação de proxy/IP nem spoofing de origem — de propósito.
> Um navegador real já resolve a maior parte do problema de bloqueio de
> forma legítima; rotação de IP só adia o problema e incentiva bater mais
> forte no servidor. Veja mais sobre essa decisão mais abaixo.

**Robustez:** todas as requisições dos 5 clientes fazem retry automático
com backoff exponencial em erros transitórios (timeout, falha de
navegação, HTTP 429/500/502/503/504) — até 3 tentativas antes de
desistir. Erros definitivos (404, 403) não são re-tentados.

**Pexels e Magnific usam `fetch()` em vez de navegação direta pra
API.** Esses dois provedores buscam vídeos via endpoint JSON interno
(não HTML). Em vez de `driver.get(url_da_api)` — que faz o Chrome
navegar a aba inteira pra uma URL de API, algo que nenhum usuário real
faz e que pode disparar bloqueio anti-bot — o cliente carrega uma
página normal do domínio primeiro e chama a API com `fetch()` de
DENTRO dela (`ChromeSession.fetch_api()`), exatamente como o
JavaScript do próprio site faz. Se esse ainda for o motivo de algum
erro específico do Pexels que você viu, me manda o texto exato que
aparece na aba (ou a mensagem de erro impressa no terminal) que eu
ajusto mais.

## Instalação

```bash
pip install -r requirements.txt   # inclui o selenium
```

Você também precisa ter o **Google Chrome** instalado (o
`webdriver-manager` embutido no Selenium 4 baixa o chromedriver
compatível automaticamente na primeira execução).

> ⚠️ Nenhum dos cinco usa a API oficial documentada dos respectivos
> sites (que exigem chave e são mais restritas em filtros); todos
> replicam a navegação/busca pública normal do site. Estão sujeitos aos
> Termos de Uso de cada plataforma e podem quebrar se o layout mudar —
> use com moderação (todos já colocam uma pequena pausa, com variação
> aleatória, entre requisições).
>
> **Exceção: o Pexels tem uma API oficial gratuita**, e este toolkit usa
> ela automaticamente quando você configura uma chave (veja a seção
> "Pexels via API oficial" abaixo) — nesse caso não precisa nem de
> Chrome pra esse provedor.
>
> O **Magnific** tem uma particularidade importante: vídeos marcados
> como `premium` só têm preview **com marca d'água** disponível
> publicamente (o arquivo final exige login e créditos no site, fora do
> escopo deste toolkit). Por isso `download_video()` recusa baixar
> vídeos premium por padrão — veja `magnific/README.md`.
>
> O **Mixkit** busca por **categoria** (não por termo livre) e a
> qualidade real do vídeo (720p/1080p/4K) só é confirmada **na hora do
> download**, por tentativa e erro — veja `mixkit/README.md`.
>
> O **VistaCreate** sempre entrega o vídeo em **~480p** ("small"), tanto
> para itens grátis quanto premium — não há como obter resolução maior
> sem autenticação/assinatura no site — veja `vistacreate/README.md`.

## Pexels via API oficial (recomendado — evita o Cloudflare)

O Pexels tem uma API oficial gratuita, pensada exatamente pra
automação — sem Cloudflare, sem precisar de Chrome, só HTTP + JSON.
Peça sua chave (grátis) em **https://www.pexels.com/api/**.

**1) Configure uma ou mais chaves** — copie `.env.example` para `.env`
e preencha:

```bash
# .env
PEXELS_API_KEYS=sua_chave_aqui

# ou várias, separadas por vírgula — o toolkit alterna automaticamente
# pra próxima assim que uma bater o limite de requisições (rate limit):
PEXELS_API_KEYS=chave_um,chave_dois,chave_tres
```

**2) Pronto.** `main.py` e `run_batch.py` detectam a chave sozinhos e
passam a usar `pexels_api_client.py` em vez do scraping por navegador —
nenhuma mudança de código necessária. Sem chave configurada, tudo
continua funcionando exatamente como antes (scraping por navegador).

```python
# uso direto, se preferir (sem passar pelo main.py/run_batch.py)
from pexels_api_client import PexelsAPIClient

client = PexelsAPIClient()  # lê PEXELS_API_KEYS do .env
videos = client.search_all(query="dog and cats", max_pages=3)
client.download_video(videos[0], output_dir="videos")
```

**Rotação automática de chaves:** se você colocar mais de uma chave, o
cliente detecta automaticamente quando uma bate rate limit (HTTP 429,
respeitando o header `Retry-After` se o Pexels mandar um) e passa pra
próxima chave disponível, sem você precisar fazer nada. Só levanta erro
se **todas** as chaves estiverem em rate limit ao mesmo tempo.

**Limitação (parcialmente resolvida):** a API oficial não devolve
título/descrição curados nem tags. Título legível é gerado a partir do
slug da URL. Para a descrição, o cliente faz automaticamente uma
requisição HTTP simples e leve (sem chave, sem Chrome) à própria página
pública do vídeo, e extrai a mesma frase que aparece no Google/redes
sociais para aquele vídeo — em `search_all()` e `get_video()`, ligado
por padrão (`fetch_descriptions=True`). Isso é uma requisição HTTP extra
por vídeo; desligue com `fetch_descriptions=False` se quiser mais
velocidade e não precisar da descrição. Nunca quebra a busca — se a
página não responder por qualquer motivo, a descrição fica vazia.

Teste esse fluxo offline (sem chave de verdade, sem rede) com:

```bash
python test_api_keys.py
python test_pexels_api_client.py
python test_description_enrichment.py
```

## Uso programático (recomendado para integrar no seu sistema)

```python
from main import get_client

# Escolhe o provedor só trocando a string
client = get_client("pexels")     # ou "pixabay" / "magnific"

videos = client.search_all(query="dog and cats", max_pages=3)
client.download_video(videos[0], output_dir="videos")
```

Os três clientes expõem quase a mesma "forma" (`search_all`,
`download_video`, `download_many`, e cada vídeo tem `.to_dict()`), então
o resto do código — por exemplo, seu sistema de edição escolhendo fontes
antes de baixar — pode tratar qualquer um deles de forma praticamente
intercambiável. **O que muda entre eles são os nomes dos filtros aceitos**
por `search_all(**filtros)`:

| | Pexels | Pixabay | Magnific | Mixkit | VistaCreate |
|---|---|---|---|---|---|
| Como busca | termo livre (`query`) | termo livre (`query`) | termo livre (`query`) | **categoria** (`category`) | termo livre (`query`) |
| Orientação | `orientation`: `landscape`/`portrait`/`square` | `orientation`: `horizontal`/`vertical` | `orientations`: lista com `horizontal`/`vertical`/`square` | `orientation`: `horizontal`/`vertical` | — |
| Nº de pessoas | `people_count`: `0`/`1`/`2`/`3_plus` | — | — | — | — |
| Presença de pessoas | — | — | — | — | `people`: `include`/`exclude` |
| Fundo isolado | — | — | — | — | `isolated`: `include`/`exclude` |
| Idade das pessoas | `people_age`: `baby`/`child`/`teenager`/`adult`/`senior_adult` | — | — | — | — |
| Duração | `min_duration`, `max_duration` (segundos) | — | `duration_from`, `duration_to` (segundos) | `duration`: `0-5s`/`5-10s`/`10-20s`/`20s-` | — |
| FPS | `frame_rate`: `24`/`25`/`30`/`50`/`60_plus` | — | `fps`: lista com `24`/`25`/`30`/`60`/`gt60` | — | — |
| Resolução | `resolution_name`: `1080p`/`4K`/`8K` | `resolution_hd`/`resolution_4k` (booleanos) | `resolutions`: lista com `720`/`1080`/`2k`/`4k`/`8k` | `resolution`: `4k` (confirmado) | `quality` no download: `small`(confirmado)/`medium`/`large`(experimentais) |
| Data | `date_from`: `last_24_hours`/`last_week`/`last_month`/`last_year` | `date_from`: `1d`/`3d`/`1w`/`6m`/`1y` | — | — | — |
| Ordenação | — | — | — | `sort`: `newest` (confirmado) | `sort`: `newest`/`popular` |
| Efeitos | — | `animation`/`slow_motion`/`time_lapse` (booleanos) | — | — | — |
| Tipo de conteúdo (IA) | — | `content_type`: `authentic`/`ai` | `ai_generated`: `excluded`/`only` | — | — |
| Licença | — | — | `only_free`/`only_premium` (booleanos) | — | — |

Não passar nenhum filtro faz a busca "crua" em todos — todo filtro é
opcional. Veja `exemplo_combinado.py` para um exemplo completo buscando
nos cinco provedores e juntando os resultados numa lista só de "fontes"
candidatas, ou use a função `search_multiple()` do `main.py` para o
mesmo padrão de forma reutilizável:

```python
from main import search_multiple

resultados = search_multiple({
    "pexels": {"query": "dog and cats", "orientation": "landscape", "max_pages": 2},
    "pixabay": {"query": "gato cachorro", "max_pages": 2},
    "mixkit": {"category": "animal-nature", "max_pages": 2},
})
# resultados = {"pexels": [...], "pixabay": [...], "mixkit": [...]}
# Provedores que falharem (rede, filtro inválido) voltam com lista vazia
# e o erro é impresso, sem derrubar a busca dos outros.
```

### A particularidade do Magnific: vídeos premium

No Magnific, vídeos `premium=True` só têm preview **com marca d'água**
publicamente disponível. `download_video()` recusa baixar esses vídeos
por padrão (levanta `WatermarkedDownloadError`); use
`only_free=True` na busca para evitar esse problema, ou passe
`allow_watermarked=True` no download se quiser mesmo assim o preview
com marca d'água. Detalhes em `magnific/README.md`.

### A particularidade do Mixkit: qualidade descoberta por retry

No Mixkit, a listagem só expõe o preview em 360p. `download_video()`
testa automaticamente as variações de qualidade (2160 → 1080 → 720 →
360, por padrão) e salva a primeira que responder com sucesso — nem todo
vídeo tem todas as variações, e alguns nem têm variação nenhuma (assets
com nome tipo hash). `resolved_quality` só fica preenchido depois de um
download bem-sucedido. Detalhes em `mixkit/README.md`.

### A particularidade do VistaCreate: qualidade sempre ~480p (com retry experimental)

No VistaCreate, o link de download é montado a partir da própria URL de
thumbnail da listagem (removendo o parâmetro `videoStaticPreview=true`),
sem precisar visitar nenhuma página extra. O tamanho `small` (~480p) é o
único **confirmado** e funciona tanto para itens grátis quanto premium.
`download_video(quality="best")` tenta experimentalmente `large` →
`medium` → `small`, mas como só `small` foi confirmado, use
`run_live_tests.py` para descobrir se `medium`/`large` existem de
verdade no seu caso. Itens `premium` também não têm `url` de página (só
`download_url`). Detalhes em `vistacreate/README.md`.

## Metadados: título e descrição ligados ao vídeo baixado

Todo download feito por `run_batch.py` ou pela CLI de `main.py`
(`python main.py download ...`) agora anexa automaticamente o
título/descrição daquele vídeo a ele:

1. **Sidecar** — sempre grava `<nome-do-video>.json` e
   `<nome-do-video>.txt` do lado do `.mp4`, com título, descrição, autor
   (quando o provedor expõe), URL original e o provedor. Não depende de
   nada além do Python.
2. **Embutido no próprio arquivo** — se você tiver `ffmpeg` instalado
   (`ffmpeg -version` pra conferir), o título/descrição também são
   escritos dentro do container do `.mp4` (via `ffmpeg -c copy
   -metadata ...`, sem recodificar — rápido e sem perda de qualidade).
   Isso faz o título/descrição aparecerem no "Detalhes"/"Propriedades"
   do próprio arquivo em qualquer player ou explorador de arquivos. Sem
   `ffmpeg`, essa parte é pulada silenciosamente e só o sidecar é usado.

### O que cada site realmente tem pra dar

Nem todo site expõe uma descrição de verdade — isso é uma limitação de
cada plataforma, não do toolkit. Depois de investigar cada uma (com
requisições reais, não suposição), esse é o quadro:

| Site | Descrição? | De onde vem |
|---|---|---|
| **Pexels** (scraping) | ✅ Sim | Descrição autoral real, via dados internos da página do vídeo (`__NEXT_DATA__`) ou o `<h1>` da página, como fallback |
| **Pexels** (API oficial) | ✅ Sim (enriquecida) | A API em si não tem — o cliente busca a meta-tag `description` da página pública do vídeo automaticamente (`fetch_descriptions=True`, ligado por padrão) |
| **Pixabay** | ✅ Sim | Descrição autoral real, direto na página de busca (JSON-LD) |
| **Mixkit** | ✅ Sim | Descrição autoral real, direto na página de busca |
| **Magnific** | ⚠️ Parcial | O site não tem descrição autoral — só um "nome". O cliente busca a meta-tag da página do vídeo, que é uma frase **gerada pelo próprio site** ("Download this free video of X..."), não escrita por quem enviou o vídeo |
| **VistaCreate** | ❌ Não | O site não expõe descrição em prosa em lugar nenhum. Em vez disso, o cliente busca **tags** e o nome do **autor** na página do vídeo — não é uma descrição, mas é a informação mais próxima disso disponível |

Pra Magnific e VistaCreate, essa busca extra acontece automaticamente em
`download_video()` (não durante a busca, pra não fazer uma requisição
por item na listagem inteira) — só quando você efetivamente baixa o
vídeo. Pra Pexels via API, acontece durante `search_all()` (ligado por
padrão, desligável com `fetch_descriptions=False`).

> O parser de tags do VistaCreate é melhor esforço — testei a lógica,
> mas não confirmei contra o HTML bruto real da página de detalhe (só
> tive acesso ao texto renderizado). Se notar que nunca captura tags de
> verdade no seu uso, me manda um trecho do HTML real de uma página de
> vídeo que eu ajusto o regex.

Em `toolkit_config.json`, controle isso em `downloads.write_metadata`
(sidecar) e `downloads.embed_ffmpeg_metadata` (embutido) — ambos `true`
por padrão. Pela CLI de um provedor só, use `--no-metadata` (desliga
tudo) ou `--no-embed-metadata` (mantém o sidecar, só não mexe no
arquivo de vídeo em si):

```bash
python main.py download pexels 38233454 --output-dir videos
# -> videos/algum-video.mp4
# -> videos/algum-video.json   (título, descrição, autor, url, provider)
# -> videos/algum-video.txt    (mesma coisa, em texto simples)
# -> título/descrição também embutidos no .mp4, se tiver ffmpeg
```

Pra usar isso manualmente em outros fluxos (fora do `run_batch.py`/`main.py`):

```python
from video_metadata import attach_metadata

path = client.download_video(video, output_dir="videos")
attach_metadata(video, path, provider="pexels")
```

`attach_metadata` aceita qualquer objeto de vídeo dos 5 clientes (todos
têm `.to_dict()`) ou um dict cru — inclusive do Magnific, que chama o
título de `name` em vez de `title` (isso é normalizado automaticamente).

Teste isso offline (não precisa de rede, só opcionalmente de `ffmpeg`
instalado pra testar o embed de verdade):

```bash
python test_video_metadata.py
```

> `ffmpeg` é um binário externo, não uma dependência Python — instale
> pelo gerenciador de pacotes do seu sistema (`apt install ffmpeg`,
> `brew install ffmpeg`, etc.) se quiser a parte do embed. Sem ele, o
> toolkit funciona normalmente, só usando o sidecar `.json`/`.txt`.

## Uso em lote (config por site + manifesto + concorrência)

Pra rodar os 5 provedores de uma vez, com controle fino por site, sem
escrever código:

```bash
# 1) gera toolkit_config.json (não sobrescreve se já existir)
python generate_config.py

# 2) edite o arquivo gerado — um bloco por site (query/category, quantas
#    páginas, quantos baixar, se está habilitado), mais as seções
#    "browser" (Chrome) e "downloads" (concorrência, retries, manifesto)

# 3) roda busca + download em todos os sites habilitados
python run_batch.py

# só alguns sites, ignorando o "enabled" do config pra esses:
python run_batch.py --providers pexels mixkit
```

`toolkit_config.json` tem esta forma:

```json
{
  "browser": {
    "headless": false,
    "show_browser": true,
    "download_dir": "downloads",
    "shared_session": false,
    "low_resource": false
  },
  "downloads": {
    "enabled": true,
    "max_workers": 3,
    "per_provider_workers": 1,
    "skip_existing": true,
    "retries": 3,
    "retry_backoff_seconds": 2,
    "manifest": "downloads_manifest.json",
    "output_dir": "videos"
  },
  "providers": {
    "pexels":      {"enabled": true, "query": "dog", "max_pages": 1, "download_count": 2},
    "pixabay":     {"enabled": true, "query": "dog", "max_pages": 1, "download_count": 2},
    "magnific":    {"enabled": true, "query": "dog", "only_free": true, "max_pages": 1, "download_count": 2},
    "mixkit":      {"enabled": true, "category": "animal-nature", "max_pages": 1, "download_count": 2},
    "vistacreate": {"enabled": true, "query": "dog", "max_pages": 1, "download_count": 2}
  }
}
```

Qualquer filtro extra do site (`orientation`, `only_free`, `duration`
etc. — veja a tabela acima) pode ser colocado direto dentro do bloco
daquele provedor; `run_batch.py` repassa tudo que não for
`enabled`/`max_pages`/`download_count`/`query`/`category` como filtro de
busca.

**Concorrência:** `max_workers` controla quantos **sites diferentes**
rodam em paralelo (cada um com sua própria janela do Chrome, sem
conflito entre si); `per_provider_workers` controla quantos downloads
simultâneos **dentro do mesmo site** — o padrão (1) é o mais seguro,
porque uma única sessão de Chrome não processa duas navegações ao mesmo
tempo sem risco de uma atrapalhar a outra.

**Manifesto:** com `skip_existing: true` (padrão), `run_batch.py` grava
em `downloads_manifest.json` cada vídeo baixado com sucesso — rodar de
novo pula automaticamente o que já foi baixado antes, mesmo em execuções
diferentes ou depois de reiniciar o script. Vídeos que falharam ficam
marcados como `failed` no manifesto e são tentados de novo na próxima
execução (só os que tiveram sucesso são pulados).

**Retries:** cada download que falhar é re-tentado até `retries` vezes,
esperando `retry_backoff_seconds × tentativa` segundos entre elas.

## Otimizando o consumo de recursos (múltiplos Chromes pesam)

Por padrão, `run_batch.py` abre **um Chrome por site habilitado** — com
os 5 provedores ligados ao mesmo tempo, isso pode passar de 1GB de RAM
só de navegadores. Três ajustes em `toolkit_config.json` → `browser`
resolvem isso, do mais impactante pro menos:

| Opção | O que faz | Economia | Custo |
|---|---|---|---|
| `"shared_session": true` | Usa **1 único Chrome** pra todos os sites, em vez de um por site | A maior de longe — de N navegadores pra 1 | Os sites deixam de rodar em paralelo entre si (um de cada vez, já que é o mesmo navegador); `max_workers` é ignorado nesse modo |
| `"low_resource": true` | Bloqueia carregamento de imagens e desliga sync/extensões/tradução/áudio/GPU no Chrome | Reduz bastante RAM/CPU por navegador | Nenhum — a busca só precisa do HTML/JSON, nunca da imagem renderizada |
| `"headless": true` | Roda sem abrir janela visível | Economiza CPU de renderização | Nenhum pra uso automatizado; só não dá pra ver o navegador funcionando |

**Recomendado para máquinas com pouca RAM ou rodando em servidor** (a
combinação mais econômica, tudo junto):

```json
{
  "browser": {
    "headless": true,
    "shared_session": true,
    "low_resource": true,
    "download_dir": "downloads"
  }
}
```

Isso reduz de "N Chromes pesados" pra "1 Chrome leve, headless,
processando um site de cada vez" — bem mais devagar no total (perde o
paralelismo entre sites), mas o pico de memória fica uma fração do que
seria com os 5 provedores abertos ao mesmo tempo. Se sua máquina aguenta
alguns Chromes simultâneos mas ainda assim quer economizar RAM por
navegador, dá pra usar só `low_resource: true` e manter
`shared_session: false` — aí você mantém o paralelismo entre sites, só
com cada Chrome individualmente mais leve.

> Se usar `shared_session: true`, mantenha `per_provider_workers: 1`
> (já é o padrão) — com um navegador só, pedir mais de um download
> simultâneo faria duas navegações brigarem pela mesma aba.

Teste essa lógica offline (sem precisar de Chrome instalado, usa uma
sessão falsa) com:

```bash
python test_resource_optimization.py
```

## Uso pela linha de comando (um provedor por vez)

```bash
# Buscar
python main.py search pexels "dog and cats" --pages 3 \
    --filter orientation=landscape --filter people_count=2 --out resultados.json

python main.py search pixabay "gato cachorro" --pages 3 \
    --filter orientation=vertical --filter content_type=ai --out resultados.json

python main.py search magnific "dog" --pages 3 \
    --filter only_free=true --out resultados.json

python main.py search mixkit "animal-nature" --pages 3 \
    --filter orientation=horizontal --filter duration=10-20s --out resultados.json

python main.py search vistacreate "animal nature" --pages 3 \
    --filter sort=popular --filter people=exclude --out resultados.json

# Baixar
python main.py download pexels "<url_ou_id>" --quality hd --output-dir videos
python main.py download pixabay "<url>" --output-dir videos
python main.py download magnific 167542 --query dog --output-dir videos
python main.py download mixkit "<url_da_pagina>" --quality best --output-dir videos
python main.py download vistacreate 849076422 --query "animal nature" --output-dir videos
```

`--filter chave=valor` pode ser repetido; `true`/`false` viram booleano e
valores só-dígitos viram inteiro automaticamente. Para o Magnific e o
VistaCreate, o `download` exige `--query` porque a busca não tem um
endpoint de detalhe por ID sozinho (o cliente re-busca pelo termo e
filtra pelo ID). Para o Mixkit, o `--quality` pode ser `best`, `worst`,
ou um número específico (`360`, `720`, `1080`, `2160`).

Cada cliente também mantém sua própria CLI standalone, se preferir usá-los
separados:

```bash
cd pexels && python pexels_client.py search "dog and cats" --pages 3 --out out.json
cd pixabay && python pixabay_client.py search "gato cachorro" --pages 3 --out out.json
cd magnific && python magnific_client.py search "dog" --pages 3 --only-free --out out.json
cd mixkit && python mixkit_client.py search "animal-nature" --pages 3 --out out.json
cd vistacreate && python vistacreate_client.py search "animal nature" --pages 3 --out out.json
```

## Testes offline

Cada cliente tem um `test_parsing.py` que valida a lógica de parsing
usando dados reais (sem precisar de acesso à internet nem de um Chrome
instalado — usam uma sessão falsa onde é preciso instanciar o cliente):

```bash
cd pexels && python test_parsing.py
cd pixabay && python test_parsing.py
cd magnific && python test_parsing.py
cd mixkit && python test_parsing.py
cd vistacreate && python test_parsing.py
```

## Teste ao vivo automatizado (todos os provedores de uma vez)

`run_live_tests.py`, na raiz do projeto, testa os 5 provedores **de
verdade** (com acesso real à internet): busca um termo/categoria padrão
em cada um, baixa alguns resultados, e grava um relatório completo em
`test_errors_log.txt` — incluindo o traceback completo de qualquer
falha, organizados por provedor. Também sinaliza separadamente vídeos
que falharam com HTTP 404 (que geralmente indica que aquele vídeo
específico foi removido da fonte, diferente de um bug de parsing).

```bash
# Roda tudo com os termos de teste padrão
python run_live_tests.py

# Só alguns provedores, baixando mais itens e mantendo os arquivos
python run_live_tests.py --providers pexels mixkit --download-count 5 --keep-files

# Trocando o termo/categoria de teste de um provedor específico
python run_live_tests.py --mixkit-category dog --vistacreate-query "gato"
```

Ao final, imprime um resumo por provedor (✅/❌) e sai com código `1` se
algum provedor teve problema (útil pra rodar em CI). Se algo falhar,
mande o `test_errors_log.txt` inteiro — ele já vem com tudo que é
preciso pra investigar o que quebrou.

> Este script precisa de acesso de rede real aos 5 domínios. Em
> ambientes com rede restrita, todas as buscas falham com erro de rede
> — isso é esperado nesse caso e não indica um bug no código em si.

## Sobre bloqueio de IP (e por que não tem rotação de proxy aqui)

A defesa principal contra bloqueio já está embutida na arquitetura: uma
sessão de Chrome real (não `requests` cru), retry com backoff, e um
pequeno atraso com variação aleatória entre requisições. O que
**deliberadamente não existe** é rotação de proxy/IP ou qualquer técnica
de mascarar de onde as requisições vêm — isso cruzaria a linha de
"cliente educado" para "infraestrutura desenhada pra driblar a proteção
anti-abuso do site", que preferimos não construir. Na prática, rotação
de IP também não resolve o problema de verdade: só adia, e incentiva
bater mais forte no servidor. Se um site bloquear mesmo com Chrome real
e delays razoáveis, o caminho é reduzir `max_workers`/aumentar o delay
naquele provedor, não trocar de IP.

## Possíveis próximos passos (não implementados de propósito)

Uma melhoria maior ficou de fora por ser opcional e mais trabalhosa — se
fizer sentido pro seu uso, é só pedir:

- **Classe-base compartilhada entre provedores.** Os 5 clientes têm
  bastante código repetido (sessão, headers, retry, padrão de
  dataclass). Uma classe-base reduziria essa duplicação e formalizaria
  o "contrato" que um provedor novo precisa seguir — vale a pena
  principalmente se você for adicionar mais bancos de vídeo (veja a
  seção abaixo).

O manifesto de downloads, a concorrência (entre e dentro de sites) e o
logging estruturado (`download_manager.configure_logging()`) já estão
implementados — veja a seção "Uso em lote" acima.

## Bancos de vídeo que dá pra adicionar depois

O mesmo método usado aqui (buscar por HTML público/endpoint interno,
extrair id + link de mídia, montar um cliente com `search_all` +
`download_video`) funciona bem para outros sites de vídeo gratuito com
licença permissiva. Alguns candidatos razoáveis:

| Site | Por que é um bom candidato |
|---|---|
| **Coverr** (coverr.co) | 100% grátis, sem marca d'água, catálogo menor mas curado; página de busca simples. |
| **Videezy** (videezy.com) | Grande catálogo grátis (com opção premium separada, fácil de distinguir como no Magnific). |
| **Videvo** (videvo.net) | Mistura grátis + premium, parecido em estrutura com o Pixabay/Mixkit. |
| **Mazwai** (mazwai.com) | Catálogo pequeno e 100% CC0, bom para testar rápido um cliente novo. |
| **Vecteezy** (vecteezy.com) | Catálogo grande, mas boa parte é premium/com marca d'água — precisaria da mesma lógica do Magnific. |

Para eu montar o cliente de qualquer um desses (ou de outro que você já
tenha em mente), o processo é o mesmo que usamos até aqui: você abre a
página de busca do site, copia a URL com os filtros que quiser suportar,
e cola aqui um trecho do HTML (ou da resposta da API, se o site tiver
uma) com pelo menos 2–3 resultados de vídeo — isso já é suficiente pra eu
extrair o padrão e construir o parser, os testes e o README, do mesmo
jeito que fiz com os cinco atuais.

## Documentação completa de cada provedor

- [`pexels/README.md`](pexels/README.md) — como funciona a API interna do
  Pexels, tabela completa de filtros, limitações.
- [`pixabay/README.md`](pixabay/README.md) — como funciona o scraping do
  HTML do Pixabay (blocos JSON-LD), tabela completa de filtros,
  limitações conhecidas.
- [`magnific/README.md`](magnific/README.md) — como funciona a busca do
  Magnific, a diferença crítica entre preview grátis (sem marca d'água) e
  premium (com marca d'água), tabela completa de filtros, limitações.
- [`mixkit/README.md`](mixkit/README.md) — como funciona a navegação por
  categoria do Mixkit, a lógica de retry para descobrir a qualidade real
  do vídeo, tabela completa de filtros, limitações conhecidas.
- [`vistacreate/README.md`](vistacreate/README.md) — como o link de
  download é montado direto a partir da thumbnail da listagem, por que a
  qualidade fica sempre em ~480p, tabela completa de filtros, limitações.
