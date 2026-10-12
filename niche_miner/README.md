# Niche Miner — versão corrigida

Esta versão corrige a execução com vários nichos/subnichos e amplia os resultados da interface.

## O que foi corrigido

- O navegador passa corretamente `nicho` + `subnichos` + `termos` para a API.
- Termos são associados ao subnicho sem depender de maiúsculas/minúsculas.
- Uma falha em um termo não encerra toda a pesquisa: o próximo termo continua sendo processado.
- O ranking geral consolida o canal uma única vez, mas preserva todas as associações de nicho, subnicho e termos.
- Ranking separado por:
  - geral;
  - nicho;
  - subnicho;
  - país;
  - idioma;
  - verificados.
- A regra do ranking permanece: mais inscritos, menos vídeos e maior recência do primeiro vídeo. O campo de inscritos mínimos vem com 0 por padrão (sem corte).
- A interface mostra país, idioma provável, nicho, subnicho, vídeo mais antigo e TOP 3 vídeos populares.
- Patrocinados e vídeos fora do mês configurado continuam sendo descartados após validação da página do vídeo.
- Falhas ao ler a aba Sobre não eliminam o canal: campos desconhecidos permanecem visíveis e o score recebe penalização conservadora.
- O detalhamento do vídeo mais antigo e do TOP 3 é tentado para todos os canais não verificados encontrados.
- Correção do parser de números: `234 mil` não é mais interpretado como `234 milhões`.

## Testes automatizados

No Windows:

```powershell
.\run_tests.ps1
```

ou:

```bat
run_tests.bat
```

Os testes verificam parsing de views, conteúdo patrocinado, validação de data, idioma provável, consolidação de canais, ranking por grupo, contrato do JavaScript/API e isolamento de falhas por termo.

## Execução

```powershell
python app.py
```

Abra `http://127.0.0.1:8843`.

Requisitos:

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

## Filtros configuráveis pela interface

Na etapa "Configurar e rodar", os filtros deixaram de ficar fixos no código:

- duração mínima e máxima em minutos (máximo `0` = sem limite);
- data de upload: Hoje, Esta semana, Este mês, Este ano ou Todas as datas;
- ordenação: Popularidade ou Relevância (padrão do YouTube);
- opção para **mutar o áudio do Chromium** aberto pela automação.

Quando o YouTube oferece uma faixa nativa equivalente, o scraper usa o filtro nativo. Para faixas personalizadas, a duração é conferida exatamente nos cards coletados. A data real do vídeo também é validada na página do vídeo para evitar resultados fora do período por falhas do filtro do YouTube.

As preferências dos filtros ficam salvas no navegador (localStorage) para a próxima execução.

## Ranking de nichos mais promissores

Após a coleta, o Niche Miner também ordena os nichos e subnichos pelo potencial dos canais encontrados. O índice de oportunidade combina:

- o score do melhor canal do grupo;
- a média dos 3 melhores canais;
- a média de todos os canais do grupo.

O score de cada canal segue a regra principal: mais inscritos, menos vídeos e maior recência do primeiro vídeo. Um canal com dados incompletos continua no ranking com penalização conservadora.

A interface mostra o nicho #1, o subnicho #1 e tabelas dos grupos ordenadas pelo índice de oportunidade. Os seletores das abas de nicho/subnicho seguem a mesma ordem.

## Janela de idade do canal (canal novo = melhor canal)

Na etapa "Configurar e rodar" você define **"Primeiro vídeo do canal há no máximo N meses"** (padrão 3; `0` = sem limite). O ranking dá mais nota a canais cujo primeiro vídeo é recente, e:

- canais **fora da janela** ficam salvos, mas são marcados (`fora_da_janela`), ocultados por padrão e **não entram** no índice de oportunidade do nicho;
- canais cuja idade não pôde ser confirmada ficam como `idade_desconhecida` — nunca são tratados como "novos" nem como "fora da janela";
- com a opção "Pular a análise detalhada de canais fora da janela" ligada, o app não gasta navegações lendo os últimos 50 vídeos de canais velhos.

## O que é coletado por canal

- **Link, nome, nº de vídeos, inscritos** e, na aba **Sobre**, o **total de visualizações** e a data de criação do canal;
- os **5 vídeos mais antigos** (título, data, views, link), usando o filtro "Mais antigos" da aba Vídeos; se ele não existir, a lista inteira é carregada e invertida — só é considerada confiável quando chegou ao fim;
- os **3 mais recentes** e os **3 mais populares**;
- data do **primeiro** e do **último** vídeo;
- **frequência de postagem**, calculada sobre os últimos 50 vídeos da página do canal, com rótulos como `todo dia`, `2–3 por semana`, `1 por semana`, `a cada 2 semanas`, `1 por mês`, `menos de 1 por mês`. Também guarda vídeos/semana, vídeos nos últimos 30 dias e se o canal está `ativo` ou `parado`.

Datas relativas do YouTube ("há 3 semanas") são aproximadas pelo ponto médio da faixa; as datas do vídeo mais novo e do mais antigo são lidas exatas na página do vídeo.

## Biblioteca

Cada pesquisa (uma execução por palavras-chave de um nicho) é salva automaticamente em um banco SQLite (`data/biblioteca.db`, ou o caminho da variável `NICHE_MINER_DB`), organizada por **tema**. Para cada busca ficam salvos os canais e os vídeos (título, data, views, link). A aba **Biblioteca** permite reabrir, pesquisar (sem diferenciar acentos/maiúsculas), excluir e exportar CSV (canais ou vídeos).

## Layout novo do YouTube

O parser dos cards da aba Vídeos foi reescrito para o layout `yt-lockup-view-model` (o do HTML de exemplo), com fallback para o layout antigo. Views e data são identificados pelo texto, não pela posição, e o `video_id` é extraído mesmo com parâmetros extras (`&pp=...`) e ids que começam com `-`. O HTML de exemplo está em `tests/fixtures/`.

Novos parâmetros de linha de comando: `--janela-meses`, `--manter-fora-da-janela`, `--n-frequencia`.


## Ordenar canais (inscritos, vídeos, views e combinações)

Todas as tabelas de canais (aba **Minerar**: Geral, por nicho, subnicho, país e idioma; e aba **Biblioteca**) têm uma barra **Ordenar canais por** e cabeçalhos clicáveis. Clique num cabeçalho para ordenar e clique de novo para inverter; a escolha vale para todas as tabelas ao mesmo tempo e fica salva no navegador.

| Opção | O que ordena |
|---|---|
| Regra do app (padrão) | Ordem original da coleta (canais dentro da janela primeiro e, em cada faixa, maior score). |
| Inscritos / Views totais | Maior primeiro. |
| Vídeos publicados | **Menos vídeos primeiro** (inverta para ver os maiores). |
| Views por vídeo | Views totais ÷ vídeos. |
| Inscritos por vídeo | Inscritos ÷ vídeos. |
| **Combinada** | Média da posição do canal em três listas: mais inscritos, mais views totais e menos vídeos (1 = melhor). |
| Score | Score da regra principal do app. |

Detalhes que valem saber:

- **Dado ausente nunca ajuda o canal.** Nas ordenações simples, canais sem o dado ficam sempre no fim (nos dois sentidos). Na *Combinada*, dado ausente conta como a pior posição daquele critério. Razões (por vídeo) só existem quando o canal tem vídeos publicados.
- A *Combinada* compara só os canais que estão na tabela naquele momento; ao mostrar ou ocultar canais fora da janela, as posições mudam. Ela usa posições, não valores, então um canal com 10 milhões de views não "esmaga" os demais.
- A coluna **#** mostra a posição na ordenação atual; no modo padrão continua sendo o rank original. Os detalhes abertos de um canal fecham ao reordenar.
- A lógica fica em `static/ordenacao.js` (sem DOM) e é testada no Node por `tests/test_ordenacao.py`; `tests/test_ordenacao_navegador.py` confere as tabelas no Chromium.

## Minerar pelas recomendações de um vídeo

Quando um vídeo está indo bem, a lateral dele ("recomendados") costuma mostrar canais pequenos, ainda não
monetizados, que estão indo bem também. No bloco **"Ou: recomendações de um vídeo"** (barra lateral, abaixo do
passo 3) você cola um ou mais links de vídeos, um por linha, e o app faz a triagem sozinho:

1. abre cada vídeo e lê os primeiros **15** recomendados (configurável de 5 a 40);
2. mantém só canais **não verificados** com vídeo **postado há no máximo N meses** (padrão 3), de vídeo comum
   (shorts, playlists, lives e patrocinados ficam de fora) e dentro da duração do passo 3;
3. calcula a **média** de views desses elegíveis e guarda quem está **na média ou acima** dela;
4. abre só os aprovados para confirmar a data real, checar patrocínio e descobrir o canal (a lateral do YouTube
   não traz o link do canal);
5. manda os canais para a **mesma análise da busca por nicho**: inscritos, nº de vídeos, idade do primeiro vídeo,
   frequência, score e ranking, com janela de "canal novo", abas por país/idioma e gravação na Biblioteca.

**Ajustes da triagem**

- *Referência*: **média** (padrão) ou **mediana**. Um único vídeo viral puxa a média para cima e faz o resto parecer
  fraco; a mediana é menos sensível a isso.
- *Guardar quem tiver*: na referência ou acima (100%), até 20% abaixo, ou até metade dela.
- *A referência é calculada sobre*: cada vídeo de origem separado (padrão, porque cada lateral é um universo
  diferente) ou todos os vídeos de origem juntos.
- A referência usa **só os elegíveis**. Canais verificados e vídeos antigos virais entram no relatório, mas não na conta.
- Com poucos elegíveis (menos de 3) o relatório avisa que a referência é frágil.

**Relatório da triagem**: acima do resultado aparece, por vídeo de origem, quantos foram elegíveis, o valor da
referência, o corte e quantos passaram, com uma tabela vídeo a vídeo dizendo por que cada um entrou ou saiu.

**Da descoberta para uma nova busca (o prompt)**: o botão **"Gerar prompt a partir destes canais"** (aparece em
todo resultado salvo na Biblioteca) monta um prompt com os canais achados e seus vídeos. Cole na IA de sua preferência;
ela responde no **mesmo JSON do passo 1** (`{"subnichos": [{"nome", "termos"}]}`). Cole essa resposta no
**passo 2** e rode a busca por nicho normal: você sai de "canais que já estão funcionando" para "mais canais parecidos".

**"Usar vídeos de exemplo do último resultado"** preenche a caixa com o vídeo de exemplo dos melhores canais do último
resultado, para você repetir o processo a partir deles (efeito bola de neve).

**Limites e cuidados**

- Uma coleta por vez (Minerar, Recomendações ou Ideias), como antes; máximo de 20 vídeos de origem por rodada.
- Os seletores da lateral foram escritos e testados contra o HTML real de um vídeo (layout `yt-lockup-view-model`, com
  o layout antigo como reserva). O YouTube muda isso sem aviso: se um dia a triagem vier vazia, o log diz que a lateral
  não apareceu.
- A idade dos recomendados vem do texto relativo do YouTube ("há 3 dias"), que é aproximado; a data real é
  conferida ao abrir cada aprovado.
- Vídeos "só para membros" não mostram views e ficam de fora.
- Os canais dessa fonte entram como "Sem subnicho" e o termo de busca mostra o vídeo de origem; o prompt acima serve
  justamente para descobrir o nicho.

Arquivos: `recomendados.py` (leitura da lateral, seleção pela média, prompt), a rota `/api/iniciar-recomendados` e
`/api/gerar-prompt-canais` em `app.py`, o bloco em `templates/index.html` e `static/app.js`, e os testes
`tests/test_recomendados*.py` (lógica pura, Chromium contra páginas simuladas, API e interface).
A extração `analisar_canais_nao_verificados` em `yt_scraper.py` é a etapa de análise de canais compartilhada com a busca por termo.

### Recomendados automáticos (sem colar link nenhum)

Na aba Minerar (busca por termo), o checkbox **"Também aproveitar a lateral de recomendados de cada vídeo
encontrado"** (logo acima do botão "Iniciar automação") liga a mesma triagem acima, mas **durante a mineração
normal**: para cada vídeo que a busca encontra, o app já abre a página dele para checar data e patrocínio — nesse
momento, com a opção ligada, ele também lê a lateral, sem navegação extra. No fim de cada termo, os recomendados
lidos passam pela mesma seleção por média/mediana e os aprovados (canal não verificado, vídeo recente, view na
referência ou acima) entram como candidatos a mais no ranking daquele termo, junto com os vídeos achados na busca.

As opções (quantos recomendados por vídeo, referência, fator e "postado há no máximo") são as mesmas da triagem
manual, só que aplicadas por vídeo da busca em vez de por link colado. As duas formas convivem: dá para colar
links na aba de recomendações e, ao mesmo tempo, deixar a busca por termo aproveitando a lateral sozinha.

Por baixo do capô, `yt_scraper.processar_termo` recebe um `recomendados_auto` opcional; quando presente, chama
`recomendados._ler_lateral_atual` (a mesma leitura de `coletar_recomendados`, mas sem repetir a navegação) e depois
`recomendados.processar_lateral_inline`, que reaproveita a validação (`_validar_aprovados`) da triagem manual.

## Navegadores simultâneos (1 a 5)

O seletor **"Navegadores simultâneos"**, na aba Minerar, vale tanto para a busca por termo quanto para a
mineração por recomendações. Com mais de 1, o app abre esse tanto de Chromium ao mesmo tempo (cada um em sua
própria thread) e distribui os termos — ou, no modo recomendações, os vídeos de origem — em fatias, uma por
navegador (round-robin, preservando a ordem dentro de cada fatia). No fim, os resultados de todos são
consolidados no mesmo ranking, exatamente como se tivessem vindo de um navegador só.

- Com **1** (padrão) o comportamento é idêntico ao de sempre — um Chromium só, sem threads.
- Com menos termos do que navegadores pedidos, o app roda com menos navegadores (não abre um Chromium para não
  fazer nada) e avisa no log.
- Cada navegador tem seu **próprio cache de canal já analisado**: um canal encontrado em dois navegadores
  diferentes é analisado duas vezes (o ranking final não duplica, só custa um pouco mais de tempo). Dentro do
  mesmo navegador, a mesma economia de sempre continua valendo.
- O log de cada navegador vem prefixado (`[navegador 1] `, `[navegador 2] `...) para não misturar o que cada um
  está fazendo; a falha isolada de um termo (ou de um navegador inteiro, se o Chromium travar) não derruba os
  demais — mesma filosofia da falha isolada por termo que já existia.
- Mais navegadores usam mais RAM e, com "headless" desligado, abrem várias janelas ao mesmo tempo.

Arquivos: `app._dividir` (a distribuição round-robin), `app.LogStream` (agora thread-safe, com prefixo por
thread via `threading.local`) e o bloco novo dentro de `app.rodar_pipeline`; os testes ficam em
`tests/test_multi_navegador.py` (divisão, logs, falha isolada, cache por navegador, modo recomendados) e
`tests/test_minerar_ui_navegador.py` (a tela em Chromium real, sem rodar o pipeline de verdade).

## Aba "Método Dark" (o que o criador ensina e como aplicar)

Baseada na transcrição de um vídeo de cerca de 1h10 em que o criador (o público o chama de "Dark"; o nome do canal não aparece na transcrição) explica por que pedir nicho e título a uma IA não funciona e como validar o mercado no próprio YouTube. A aba tem cinco blocos:

| Bloco | O que traz |
|---|---|
| 1. O que ele explica | A tese em 8 pontos, cada um com a minutagem do trecho no vídeo. |
| 2. Como seguir | Checklist de 21 itens: mudar o processo + as 6 etapas dele (ler o mercado, achar outliers, emoção e promessa, saturação, variar o ângulo, validar título/thumbnail). As marcações ficam salvas no navegador. A etapa 6 não tem itens porque ele não a aprofundou. |
| 3. Ferramentas | **Planilha automática** (mediana dos últimos N vídeos, tração, vídeos outliers, para o último resultado ou qualquer busca da Biblioteca, com CSV), **calculadora rápida** (para canais vistos fora do app) e **semáforo de saturação**. |
| 4. Cobertura | O que o app já faz, o que a aba calcula, o que não existe, e onde o app diverge do método. Inclui o botão que muda a referência das recomendações de média para **mediana**. |
| 5. Limites e cuidados | O que são heurísticas dele e o que não foi verificado. |

**Fórmulas** (as do vídeo): tração = mediana das views dos últimos 10 vídeos ÷ inscritos; fator outlier = views do vídeo ÷ mediana dos últimos 10 do canal; saturação = vídeos sobre o mesmo título ou ângulo no mês (menos de 5 = campo aberto, 5 a 20 = saturando, mais de 30 = abandone). Ele usa **mediana, não média**, porque um único vídeo viral infla a média e esconde os outros outliers.

**Pontos que merecem atenção**

- Os limites de tração (0,05 e 3) vêm de uma fala que a transcrição registra como "5 centés"; a leitura como 0,05 é interpretação e por isso os valores são ajustáveis. O fator mínimo de outlier (2) é padrão do app, o criador não dá número. Ele mesmo diz para não levar as faixas tão a sério.
- A planilha usa a lista de vídeos recentes que o app já coleta (`amostra_videos`, até 50 por canal). Buscas salvas antes dessa coleta não têm a lista e aparecem como "sem dado".
- O **VPH** dele é o ritmo atual do vídeo, medido pelo VidIQ. O app só guarda a data, então não mede isso; na aba aparece apenas a média de views por hora desde a postagem, com esse nome, e o filtro "últimos 30 dias" é o que mais se aproxima da recomendação dele.
- Os passos 1 e 2 do app (prompt de subnichos) pedem termos a uma IA, e o criador diria que isso tende ao genérico e saturado. A aba registra essa divergência em vez de escondê-la.

Arquivos: `static/metodo.js` (fórmulas, sem DOM), `static/metodo_ui.js` (interface), bloco `view-metodo` em `templates/index.html`, testes `tests/test_metodo.py` (fórmulas no Node), `tests/test_metodo_navegador.py` (Chromium real) e `tests/test_metodo_contrato.py`.

## Aba "Analisar canal" (as ferramentas do NextLEV, de graça)

Baseada na transcrição de um vídeo em que o autor mostra o NextLEV (extensão paga). Você cola o link de um canal; o app abre o Chromium local, lê o cabeçalho e os últimos vídeos (10 a 200) e monta o painel. Tudo que é número vem dos dados do YouTube. Onde o NextLEV usa IA, o app segue o padrão das outras abas: monta o prompt, você roda em qualquer IA de chat e cola o JSON de volta. **Nenhuma rota usa API paga.**

| Seção | O que faz |
|---|---|
| 1. Mapa | Cada ferramenta do vídeo, com a minutagem, e onde ela está no app (ou por que não está). |
| 2. Analisar um canal | Job com log ao vivo. A análise fica salva; dá para abrir, trocar e excluir. |
| 3. Painel | Inscritos, views totais, views por vídeo, **mediana dos últimos 10 e tração**, idade, vídeos por mês, duração média, título médio, melhores e piores vídeos, **estruturas de título** (compara a mediana com e sem cada uma) e palavras mais repetidas. |
| 4. Vídeos | Filtros por título, período, views, fator outlier e categoria; ordenação; exportação CSV/JSON do que está filtrado. |
| 5. IA externa | **Categorias** (a IA agrupa, o app calcula contagem e views), **estratégia** (fórmula, público, oportunidades, tópicos, roteiro) e **comentários** (você cola os comentários). |
| 6. Pontes | Manda os 3 vídeos mais vistos (ou um vídeo da tabela) para a mineração por recomendações; cria uma pesquisa na aba Ideias com as palavras-chave do canal. |

**O que não foi replicado, e por quê**

- **"% de saturação"** do NextLEV: é um score que não mostra como é calculado, e uma IA não mede mercado. Para isso use o semáforo da aba Método, com a contagem real de vídeos no mês. O prompt de estratégia proíbe a IA de inventar porcentagem ou saturação.
- **Shorts e monetizado**: o YouTube não mostra isso de forma confiável na página. Aparecem como "não coletado", nunca como zero.
- **Palavras por minuto**: exige a transcrição de cada vídeo (o próprio autor do vídeo disse que não entendeu).
- **Canais dark em alta, Faceless Outliers, busca de outliers**: dependem do banco de canais que o NextLEV já coletou. O equivalente aqui é a aba Minerar e o radar da aba Ideias.
- **% de similaridade e views por hora atuais**: números do NextLEV. Aqui há "views por dia" (média desde a publicação).
- **Comentários**: o app não os lê sozinho; você cola os que quiser analisar.

**Cuidados ao ler o painel**

- Os padrões de título são **correlação em amostra pequena**, não prova de causa. A tabela marca "poucos vídeos" quando um lado tem menos de 5.
- Vídeos com menos de 14 dias ficam fora dos "piores" e dos padrões de título, porque ainda não juntaram views.
- A tração usa os limites ajustados na aba Método (0,05 e 3, com a ressalva da transcrição ambígua descrita lá).
- O que a IA devolve são hipóteses. Confirme no YouTube antes de decidir por um nicho.

Arquivos: `canal.py` (métricas, padrões, prompts, validação e banco), `canal_api.py` (rotas `/api/canal/*` e o job), `static/canal.js` (filtros e exportação, sem DOM), `static/canal_ui.js`, bloco `view-canal` em `templates/index.html` e os testes `tests/test_canal.py`, `test_canal_api.py`, `test_canal_js.py`, `test_canal_navegador.py` e `test_canal_contrato.py`.

## Aba "Ideias virais" (pesquisa de nichos e ideias)

Fluxo em 5 etapas, montado a partir dos vídeos de referência. **Nenhuma etapa usa API paga ou chave**: o que é de IA segue o mesmo padrão da aba Minerar (o app monta o prompt, você cola numa IA de chat e cola o JSON de volta para o app validar). Cada pesquisa fica salva no SQLite (mesmo arquivo da biblioteca, tabela `pesquisas_ideias`), então dá para fechar o navegador entre uma etapa e outra.

| Etapa | O que faz | Como roda |
|---|---|---|
| 1. Radar | Busca os termos no YouTube (período + popularidade), calcula **views por dia** e lê os inscritos dos canais pequenos com mais views. Marca como *outlier* o vídeo com mais views do que o canal tem de inscritos. | Automático (Playwright) |
| 1b. Expandir tema (opcional) | Públicos adjacentes, ranking de buscas/problemas e termos para validar; clique no termo para levá-lo ao radar. | Prompt manual |
| 2. Decompor | Emoção, estrutura do título, personagem, cenário, público adjacente e **amplitude** (0–5) de cada vídeo; agrupa em padrões (o que é fixo x variável). | Prompt manual |
| 3. Gerar ideias | Mesma emoção/estrutura, **ângulo novo** (personagem/cenário) e/ou **outro mercado** (brecha dupla); título em 3 níveis (micro, sub, amplo) e termos de validação. Ideias novas são somadas às existentes sem duplicar. | Prompt manual |
| 4. Validar | Autocomplete do Google e do YouTube (opção de expandir a–z), "As pessoas também perguntam" e "Pesquisas relacionadas" do Google, Google Trends (12 meses, distingue **evergreen x sazonal** e subindo/caindo) e concorrência no YouTube (mediana de views/dia e concentração nos 3 canais que mais aparecem). | Automático |
| 5. Ranking e decisão | Score 0–100 com pesos editáveis, CSV, e a regra dos vídeos para **continuar / revisar / escalar / descartar** um canal (alerta com 15–20 vídeos, corte aos 30). | Cálculo local |

### Como a pontuação funciona

Cinco critérios de 0 a 5: amplitude, demanda, pouca concorrência, repetibilidade e produção. Amplitude, repetibilidade e produção começam com a estimativa da IA e você pode corrigir na tabela. Demanda e concorrência são calculadas a partir da etapa 4:

- **Demanda** = média de (a) sugestões do autocomplete, (b) nível no Trends e (c) views/dia no YouTube. Trends e views/dia são **relativos às demais ideias do mesmo mercado** (não se comparam Alemanha e Brasil).
- **Pouca concorrência** = 5 × (1 − parcela dos resultados que pertence aos 3 canais mais frequentes). Precisa de pelo menos 8 vídeos coletados.
- Critério **sem dado não vira zero**: fica de fora do cálculo e a coluna *confiança* mostra que fração do peso tem dado. Uma ideia com pouca validação pode ter score alto e confiança baixa.

Os limiares da decisão de canal (impressões, CTR e retenção) são padrões ajustáveis; só a regra dos 15–20 / 30 vídeos vem dos vídeos de referência.

### Limites e cuidados

- **Os seletores do Google e do YouTube não foram testados contra os sites reais** (o ambiente de desenvolvimento não tem rede). Os testes usam páginas simuladas em Chromium real e validam a lógica, não o HTML de produção; se o Google mudar o layout, "perguntas" e "relacionadas" podem vir vazias. Confira numa execução real com poucos termos antes de confiar.
- O Google pode pedir CAPTCHA em buscas automatizadas. Ao detectar, o app **pula a SERP nos demais termos** (autocomplete, Trends e YouTube continuam) e mostra o aviso no log. O consentimento de cookies é respondido com "Rejeitar tudo".
- O autocomplete usa o mesmo endpoint público da caixa de busca (`suggestqueries.google.com`), sem chave.
- O Trends usa `pytrends` (opcional, biblioteca não oficial que também pode tomar limite de requisições). Sem ele, cada termo ganha um link "Trends ↗" para conferir manualmente. Os termos são comparados entre lotes usando o primeiro termo como âncora.
- Só **uma coleta por vez** (Minerar ou Ideias): os logs vêm do mesmo `stdout`. Uma segunda coleta recebe 409.
- O app não faz aquecimento de contas, proxy ou multilogin, e não copia roteiro, título ou thumbnail de terceiros: o prompt de ideias pede para manter emoção/estrutura e **mudar** personagem, cenário e mercado.

### Arquivos novos

`ideias.py` (prompts, leitura tolerante do JSON da IA, sinais, pontuação, decisão, persistência), `ideias_scraper.py` (Playwright), `ideias_api.py` (rotas `/api/ideias/*` e jobs), `static/ideias.js`, e os testes `tests/test_ideias*.py`.

## Aba "API do YouTube" (seis ferramentas, com chave gratuita)

Diferente das outras abas, esta não lê a página do YouTube pelo navegador: fala com a **YouTube Data API v3** oficial, o que exige uma chave gratuita (Google Cloud, sem cartão) e é limitado por **cota** (10.000 unidades por dia; uma busca por palavra-chave gasta 100, as demais chamadas gastam 1 ou 2). A chave fica só no navegador (localStorage), vai apenas no corpo das requisições que falam com o YouTube e nunca aparece em URL, resposta ou log — inclusive em erros inesperados, que são registrados mascarados. Toda a parte de IA segue o mesmo padrão do resto do app: o app monta o prompt com os dados que leu, você roda em qualquer IA de chat e cola o JSON de volta para o app validar.

| Ferramenta | O que faz | Cota |
|---|---|---|
| 1. Pesquisa avançada | Com palavra-chave, usa `search.list` filtrando por país/idioma/data. Sem palavra-chave, cai em "em alta filtrado" (país, ou EUA por padrão) e aplica os mesmos filtros no navegador. Sem datas, assume os últimos 7 dias. Filtros extras (views, faixa de inscritos e de views do canal, duração exata) rodam no navegador, sem nova chamada. Exporta CSV e PDF (via impressão do navegador). | 100 + 2 (busca) ou 2 (sem palavra-chave) |
| 2. Em alta | `videos.list?chart=mostPopular` por país e categoria; mantém só vídeos com 100 mil views ou mais e filtra a duração no navegador. | 2 |
| 3. Comparar concorrentes | Resolve os dois canais e lê os últimos 10 vídeos de cada um em paralelo; mostra 11 métricas lado a lado dizendo só quem tem o número maior, sem julgar qual é "melhor". | ~7 |
| 4. Analisar canal | `channels.list` completo (snippet, estatísticas, branding); calcula views por vídeo, vídeos por semana (desde a criação) e inscritos ÷ views. | 1 a 2 |
| 5. Analisar vídeo | `videos.list` com tópicos; extrai o ID de qualquer formato de link; baixa a miniatura testando `maxresdefault` até `default`. | 2 |
| 6. Histórico do canal | Até 30 últimos vídeos com estatísticas; formato e ordenação aplicados no navegador. | 3 a 4 |

**Diferenças em relação a uma extensão paga desse tipo**

- **Resolver @handle**: usa `channels.list?forHandle` (1 unidade) em vez de busca (100 unidades); só um link `/c/nome-personalizado` cai na busca, com aviso.
- **Transcrição**: não há serviço externo de legendas. Você cola o texto do YouTube (botão "Mostrar transcrição" abaixo do vídeo); sem ela, o prompt de engenharia reversa avisa a IA para marcar tudo como hipótese.
- **Short**: a API não diz o que é Short; é uma classificação por duração, ajustável na tela (60 segundos ou 3 minutos).
- **PDF**: usa a janela de impressão do próprio navegador ("Salvar como PDF"), sem gerar arquivo no servidor.

Arquivos: `yt_api.py` (cliente HTTP puro, parsers de entrada, normalização, métricas e as seis orquestrações), `yt_ia.py` (prompts e validadores das cinco análises), `yt_rotas.py` (rotas `/api/yt/*`, sem estado no servidor), `static/ytapi.js` (filtros, ordenação, cota e exportação, sem DOM), `static/ytapi_ui.js`, bloco `view-yt` em `templates/index.html`, e os testes `tests/test_yt_api.py`, `test_yt_ia.py`, `test_yt_rotas.py`, `test_ytapi_js.py`, `test_yt_contrato.py` e `test_yt_navegador.py` (com `tests/fake_yt_api.py` simulando a API do YouTube, já que o ambiente de desenvolvimento não tem rede).
