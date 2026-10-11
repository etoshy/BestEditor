# 18 · Quadros editoriais (estilo documentário)

São 14 quadros no estilo "documentário editorial": papel bege com vinheta, fonte serifada, rótulos pequenos espaçados
e acento vermelho. Foram recriados a partir de vídeos de referência, analisados quadro a quadro.

| Quadro | Camada | Para quê |
|---|---|---|
| 🪪 `ficha` | sobre o vídeo | apresentar alguém: uma linha sai do rosto até um cartão escuro com nome e dados, que entram linha a linha |
| 🏷 `nome` | sobre o vídeo | nome serifado e cargo em versalete, com um traço vermelho, quando a pessoa aparece falando |
| 💬 `post` | sobre o vídeo | post do X, Instagram ou outra rede: o vídeo **desfoca** por baixo e a tradução aparece em itálico |
| 🔠 `titulo_video` | máscara | palavra gigante **com o vídeo dentro das letras**, que aparecem uma a uma; a definição é digitada embaixo |
| ⌨ `terminal` | tela cheia | texto mono digitando com cursor; linha com `!` no começo (ou "ERRO", "403", "NEGADO"…) fica vermelha |
| 🖥 `pagina` | tela cheia | print de uma página num navegador inclinado. Vem de uma imagem, de um **link** (o print é tirado sozinho) ou só da manchete |
| 🗓 `linha_tempo` | tela cheia | meses ou datas passando numa linha, com o atual aceso |
| ⠿ `grade_pontos` | tela cheia | centenas de pontos, alguns acendem, e contadores embaixo (o último em vermelho) |
| 📰 `recortes` | tela cheia | manchetes em papel caem numa mesa e se empilham, com um número grande vermelho no fim |
| 🖼 `mural` | tela cheia | fotos P&B com borda, a câmera deslizando e citações em etiquetas (a última em vermelho) |
| 📝 `bilhetes` | tela cheia | uma imagem (ou **o próprio vídeo do trecho**) numa moldura, com bilhetes de papel aparecendo |
| ✍ `reescrita` | tela cheia | uma frase é digitada, riscada em vermelho e digitada de novo, até a versão certa |
| 💯 `numero` | tela cheia | número grande contando (64% → 98%), com o % em vermelho |
| 💥 `explosao` | tela cheia | um texto ou equação explode em pedaços e uma mancha de tinta cresce |

## Como usar

1. No Estúdio, abra a aba **🗞 Editorial** e clique num quadro. Ele entra no cursor, na faixa **Editorial** da
   timeline.
2. No painel da direita, troque os textos. Os campos de várias linhas aceitam uma linha por item, por exemplo
   `Cargo: Primeiro-ministro` ou `JUN | o que aconteceu`. Há também:
   - o crédito no canto;
   - a cor de acento (o padrão é o vermelho editorial);
   - o fundo (escuro, papel ou mesa), nos quadros de tela cheia.
3. **Imagens** (print da página, fotos do mural, imagens dos recortes, foto dos bilhetes): primeiro envie na aba
   📁 Mídia → Biblioteca. Depois escolha no painel. Num vídeo da biblioteca, é usado o quadro de 1 s.
4. **Ficha**: com ela selecionada, **clique no monitor em cima do rosto** para marcar de onde a linha sai.
5. Arraste na timeline para mudar o tempo e as pontas para mudar a duração. A barrinha embaixo da prévia, no painel,
   mostra qualquer momento do quadro.

A prévia no monitor é o **mesmo desenho** do vídeo final, feito no servidor. Duas exceções:

- no `titulo_video`, as letras aparecem claras na prévia (o vídeo dentro delas só aparece no vídeo montado);
- no `post`, o desfoque também só aparece no vídeo montado.

## Sons

Cada quadro toca o seu som sozinho (campo **Som** no painel: `auto` ou `nenhum`; na aba 🔊 Áudios, ☑ *Sons dos
quadros editoriais* liga/desliga todos). São sons da biblioteca do site, e a tabela fica em `dp_editorial.SONS`
(troque o id ali para mudar o som de um papel):

| Papel | Som | Toca em |
|---|---|---|
| `cartao` | `cinema/cinema_14` | a ficha entrando |
| `nome` | `pop/pop_click_1_escala` | o nome do entrevistado |
| `post` | `transicoes/foco_optico` | o post aparece e o vídeo desfoca |
| `titulo` | `impacto/riser_5` | sobe até a última letra do título |
| `terminal` / `digitando` | `digital/digital_12` / `foley/digitacao_5_longa` | o terminal liga / a digitação (quadros de 4,5 s ou mais) |
| `linha` / `erro` | `foley/tecla_suave` / `transicoes/pulso_digital_curto` | cada linha nova / a 1ª linha vermelha |
| `pagina` | `transicoes/whoosh` | a página entra |
| `passo` | `foley/catraca_rolagem` | cada mês da linha do tempo, o número contando |
| `grade` | `impacto/riser_solto_3` | os pontos acendendo |
| `papel` | `transicoes/folha_seca` | cada recorte que cai, cada bilhete |
| `foto` | `foley/camera_14` | cada foto/citação do mural |
| `numero_fim` / `recortes_numero` | `impacto/impacto_5` / `impacto/impacto_11` | o número chegou / o número dos recortes |
| `digitar_frase` / `risco` | `foley/digitacao_6_curta` / `foley/escrita_giz` | cada tentativa da reescrita / o risco vermelho |
| `explosao` / `explosao_ar` | `impacto/impacto_15` / `variados/whoosh_grave_4` | o texto explode / a tinta se espalha |

Os tempos ficam em `dp_editorial.batidas()`. Num tipo novo, acrescente lá as batidas dele.

## Nas Direções

Cada Direção diz se usa quadros editoriais, com que frequência e quais tipos (🎨 Direção → editor → eixo
**Editoriais**). De fábrica:

| Direção | Frequência | Tipos |
|---|---|---|
| Padrão do sistema | 1 a cada ~40 s | todos |
| Documentário clássico | 1 a cada ~40 s | todos |
| Cinema premium | 1 a cada ~60 s | nome, título, número, explosão, página, mural, linha do tempo, reescrita |
| Cortes dinâmicos | 1 a cada ~25 s | post, página, número, terminal, recortes, grade, ficha, nome, título |

O prompt da IA lista só os tipos da Direção e a frequência dela.

## Pela IA

O prompt de edição (aba 🤖 IA) lista os 14 quadros com os campos, e a IA pode mandar `"editoriais": [...]`. A regra
para a IA:

- usar só com fatos que a narração cita;
- na frequência da Direção (ver acima);
- nunca junto com um destaque no mesmo ponto.

As imagens da biblioteca aparecem no prompt como `bib:<id>`, para a IA poder usar. **👁 Conferir** mostra os
quadros; **✅ Aplicar** troca os que a IA tinha posto antes (os seus ficam).

## Na montagem

Os quadros entram depois da censura e antes dos destaques de texto, que ficam por cima. Cada pedaço do vídeo que
tem quadro é montado separado e depois tudo é juntado com o áudio original. Assim, muitos quadros em 1080p não
estouram a memória. Cada quadro vira um vídeo ProRes 4444 com transparência (em `trabalho/editoriais/quadros`,
guardado pelo conteúdo, então não é refeito se não mudou).

## Criar um quadro novo (código)

Tudo fica em `dp_editorial.py`:

1. Em `TIPOS`, cadastre o quadro:
   - `nome`;
   - `camada`: `sobre` (o vídeo aparece), `tela` (cobre a cena) ou `mascara` (como o título);
   - `dur`;
   - `quando` (vai para a IA e para a galeria);
   - `campos`: lista de (chave, rótulo, tipo, padrão, dica). Os tipos são `texto`, `linhas`, `num`, `img`, `imgs`,
     `cor` e `escolha:a|b`.

   O painel do Estúdio é montado sozinho a partir desses campos.
2. Escreva `_d_meutipo(it, t, W, H, ctx)`. Ela devolve **um quadro** (PIL) no instante `t`, em segundos desde o
   começo. Peças prontas:
   - `_fundo("papel"|"escuro"|"mesa", W, H)`;
   - `_f("serif"|"serif_i"|"sans"|"sans_b"|"mono", px)`;
   - `_espacado()` (versalete espaçado) e `_quebrar()` (quebra de linha);
   - `_janela(t, t0, dur)` (entrada suave de 0 a 1) e `_k_tela()` (fade de entrada e saída);
   - `_cola()` (cola uma camada com transparência);
   - `_cache(ctx, "chave", fazer)` (guarda o que não muda entre um quadro e outro);
   - `_papel_retangulo()`, `_etiqueta()`, `_foto_polaroid()`, `_img(ctx, ref)`, `_credito()`.

   Use `u = _u(W, H)` para medidas: elas escalam com a resolução e com o vídeo vertical.
3. Registre em `_DESENHOS` e dê um exemplo em `EXEMPLOS` (o texto da miniatura e do quadro novo).
4. Rode `python dp_guia.py miniaturas` (gera `galeria/editorial/<tipo>.jpg`) e `pytest test_v84_editorial.py`. O
   teste desenha todos os tipos em 16:9 e 9:16.

Fontes: tudo usa as fontes DP (EB Garamond, Inter, JetBrains Mono). Símbolos que elas não têm (∂, ∇, ν…) usam a
DejaVu Serif, que vem junto em `assets/fonts/simbolos/`.
