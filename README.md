# BestEditor — Narração → Vídeo (site Flask)

Site que fecha o pipeline completo: você sobe um áudio de narração, ele
transcreve, gera um prompt pra você colar em outra IA, você cola a
resposta (JSON) de volta, e o site busca/baixa os vídeos certos de
Pexels/Pixabay/Magnific/Mixkit/VistaCreate e monta o vídeo final já
sincronizado com o áudio.

## 🚀 Como instalar e rodar (Windows)

Precisa de **Python 3.10+**, **ffmpeg** no PATH e **Git**.

```bat
git clone https://github.com/etoshy/BestEditor.git
cd BestEditor
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
:: (opcional) gerador de voz: pip install -r toolkit\tts\requirements.txt
python app.py
```

Abra http://localhost:5050. As suas configurações, cookies do YouTube, sessão do Google Flow,
vídeos gerados e modelos de voz ficam só no seu PC (estão no `.gitignore`).

Testes: `pip install -r requirements-dev.txt` e `python -m pytest -q`.

---

## ⬛ Trecho sem cena coberto pela edição da IA (v84_111)

- Na edição com a IA (Estúdio → 🤖 IA), os trechos **sem cena** (nenhum banco achou mídia, sem prévia) aparecem como
  “⬛ SEM CENA” no prompt. A IA **cobre** cada um como se fosse uma escolha de edição: escolhe um **fundo gerado**
  (`"cobrir": {"fundo": "papel", "cor": "#…"}` — escuro, concreto, papel, película, clarão, luz, grade de pontos,
  marcas de registro, cantoneiras, borda queimada, grade ondulada, grade 3D, ondas, linhas, gradiente) e põe **por cima**
  o que a fala pede: cena/template com texto, quadro editorial de tela cheia, gráfico (se tem dados) ou um destaque com a
  frase-chave. O fundo é uma foto, então câmera e efeitos de atmosfera também valem.
- O fundo é gerado na pasta `coberturas/` do projeto e entra no trecho pelo **Aplicar** (com **↩ Desfazer**).
- **Pôs uma mídia nesse trecho?** Gere a edição de novo: ele vai como um clipe normal, e a cobertura antiga sai. Trecho
  ainda coberto aparece como “coberto na edição anterior” e a IA pode refazer a cobertura.
- Testes: `test_v84_cobrir_sem_cena.py`.

## ⏭ Conta com problema é pulada; Flow sem crédito → foto → pesquisa (v84_110)

- **Conta que pede login** (sessão caiu, verificação, “faça login”…) é **pulada**: o pedido vai pra próxima conta, no
  🚀 Em massa, no ✨ Gerar da aba e nas imagens/vídeos do Flow pros vídeos do site. No Em massa, a conta também é
  pulada quando não abre o navegador, quando não abre o projeto 2× ou quando dá 3 erros seguidos. Nesses casos o pedido
  volta pra fila sem contar como erro dele.
- A conta pulada aparece com “⏭ PULADA” em 🔑 Contas Google e no Em massa. Ela volta quando você faz o login (🔑 Contas
  Google ou 🌐 Abrir navegador → ✔ Concluir), clica em **Liberar / ♻ liberar créditos**, ou depois de 60 min.
- **Vídeos do site com trechos do Flow**:
  1. tenta gerar o **vídeo**;
  2. sem conta com crédito de vídeo (nem tenta) ou o vídeo não sai, o prompt é **reescrito como prompt de foto** (🤖 IA
     do site, ou a regra simples) e a **foto** é gerada nas contas que ainda têm crédito de imagem (passando de conta
     em conta);
  3. sem crédito de imagem em nenhuma conta (ou a foto não sai), **pesquisa** a cena só nos mecanismos **marcados**
     pra aquele vídeo: trecho de vídeo → bancos de vídeo → buscadores de imagem → bancos de foto; trecho de foto →
     buscadores → bancos de foto → bancos de vídeo.
- Testes: `test_v84_pular_conta.py` e `toolkit/googleflow/test_googleflow_client.py`.

## 🚀 Flow em massa: várias contas em paralelo, cooldown e vídeo → foto (v84_109)

Na aba **🎬 Google Flow**, nova seção **🚀 Em massa** (`/flow#lote`, código em `flow_lote.py`):

- **📋 Fila de prompts**: cole vários (um por linha, ou separados por linha em branco). `foto:` / `video:` no começo
  da linha escolhe o tipo só daquele prompt. Modelo, proporção e quantidade valem pra leva toda.
- **👥 Contas em paralelo** (padrão **2**, até 4): cada conta abre o próprio navegador (o perfil dela, já logado) e o
  próprio projeto no Flow. Marque quais contas o lote usa.
- **⏱ Cooldown escalonado** (padrão **5–10 s**): uma conta envia → o site sorteia uma espera entre 5 e 10 s → a outra
  envia → espera de novo… Nunca duas contas clicam em “Iniciar geração” juntas.
- **💳 Sem crédito**: a conta fica marcada só pro tipo que acabou (vídeo ou imagem, como no v84_105) e o pedido volta
  pra fila pra outra conta pegar.
- **🔁 Vídeo → foto**: quando **todas** as contas do lote ficam sem crédito de vídeo, cada vídeo que falta vira foto. O
  prompt é reescrito pela 🤖 IA do site (recurso novo “🔁 Flow em massa: vídeo → foto” em /ia); sem ela, pela 🔎 IA do
  Google (se o app dela estiver no ar); sem as duas, por uma regra simples que tira movimento de câmera e duração. Na
  fila aparece “🔁 era vídeo” com o prompt original.
- **🌐 Abrir navegador** em cada conta: abre a janela daquela conta pra você logar, ativar o premium/teste, ver os
  créditos… Enquanto ela está aberta, o lote não usa essa conta; **✔ Concluir** (ou fechar a janela) salva a sessão e
  devolve. **♻ liberar créditos** desmarca a conta quando o crédito voltou.
- ⏸ **Pausar** termina o que está gerando e para; ⏹ **Parar agora** devolve pra fila o que estava gerando. A fila e as
  configurações ficam salvas em `flow_dados/lote/` (fechar o site não perde nada).
- **Repetir** cada prompt N× (variações), **🔗** abre a conta em outro endereço (ex.: a página de planos) e **↺ créditos de
  volta em todas** libera todas as contas de uma vez depois de recarregar.
- Tudo vai pra 🖼 **Galeria** da aba (origem “🚀 lote”). Enquanto o lote roda, o ✨ Gerar da aba e as imagens do Flow
  pros vídeos do site esperam (cada perfil só pode estar aberto uma vez). No modo CDP (o seu Chrome) roda 1 conta só.
- Testes: `test_v84_flow_lote.py` (inclui 2 contas em paralelo no Flow simulado).

## ⏸ Pausar as prévias, conta nova do Flow e recusa de “pessoa famosa” (v84_108)

- **⏸ Pausar / ▶ Retomar a busca de prévias**: na tela “Buscando uma prévia de cada trecho…”. Pausar deixa terminar o
  que já estava buscando e para o resto (status “previas_pausadas”). As prévias prontas ficam salvas, e dá pra
  fechar o site. **▶ Retomar** busca só as que faltam. Também dá pra abrir o editor com o que já tem.
- **Projeto interrompido** (servidor fechado no meio da busca, inclusive antes desta versão): ao abrir o projeto, o
  editor (Estúdio e clássico) mostra “⏸ N trecho(s) ainda sem prévia — **▶ Continuar a busca de prévias**”. Um
  projeto que estava buscando quando o servidor caiu volta como pausado.
- **Conta nova no Flow**: as boas-vindas (**Avançar** → privacidade, cujo **Continuar** só libera depois de rolar o
  texto até o fim → **Aceitar**) são passadas sozinhas.
- **“Falha — pode violar nossas políticas contra a geração de imagens de pessoas famosas”**: antes, o site esperava
  até o tempo esgotar. Agora reconhece o cartão na hora e tira a pessoa real do comando (com a IA ligada, recurso
  “🚫 Flow recusou pessoa famosa”, ela troca o nome por uma descrição genérica; sem a IA, os nomes próprios saem).
  Depois tenta **uma** vez de novo. O Google reembolsa a geração recusada.

## 🎬 Flow: “Começar”, “Concordo” e o vídeo que só aparece com o mouse em cima (v84_107)

- **Aviso de novidades** (“Ver todos os registros de alterações” / **Começar**): o site clica em **Começar** e segue —
  ao abrir o Flow, depois do “Novo projeto” e antes de cada passo, já que o aviso pode aparecer a qualquer hora.
- **“Direitos de uso desta imagem”** (ao enviar a imagem de Início/Fim ou de referência): o site clica em **Concordo**
  — antes a imagem nunca subia e dava “enviei a imagem mas ela não apareceu na lista de mídias”.
- **Vídeo pronto que não baixava**: o Flow só põe o vídeo no cartão quando o mouse passa por cima (antes é só a capa
  com o ▶). Quando a geração chega em 100% e o vídeo não aparece, o site passa o mouse por cima do cartão e baixa.

## ⛔ Lista negra de sites (marca d'água) e 🖼 galeria do Flow com o que vai pros vídeos (v84_106)

- ⚙️ Configurações → Fontes de vídeo → **⛔ Lista negra de sites** (editável, um por linha; dá pra voltar pra padrão):
  Magnific/Freepik, Vecteezy, Pngtree… e os bancos pagos (Shutterstock, Alamy, Getty, iStock, Adobe Stock,
  Dreamstime…). Imagem/vídeo de um site da lista **nunca entra**: nos buscadores (Bing, Brave, Yandex, Startpage,
  Google — a imagem, a página de origem e os endereços reserva) e como banco (o **Magnific** sai da ordem de busca, nem
  como reserva, e nem é oferecido pra IA escolher).
- 🤖 **Juiz olhando a capa**: com a IA ligada, toda miniatura (foto ou capa/quadros do vídeo) é conferida — **marca
  d'água = nota 0**, nunca entra (nem como “a menos pior”): busca outra e, se só sobrar imagem marcada, vira **cartão
  de texto** no lugar. No 🔎 Buscar do editor ela aparece no fim como “⛔ marca d'água”.
- 🎬 Tudo que o site gera no **Google Flow pros vídeos** (fotos e vídeos) também aparece na **🖼 galeria** da aba Google
  Flow (marcado “🎞 gerado pra um vídeo”).

## 🎬 Google Flow: limite de vídeo e de imagem separados por conta (v84_105)

- Sem crédito de **vídeo** não quer dizer sem crédito de **imagem**: a conta fica marcada **só pro tipo que acabou** e
  continua gerando o outro (vídeo vai pra próxima conta; foto continua nela). Quando os **dois** acabam, ela fica
  esgotada de vez e volta depois das horas de Configurações → Google Flow (24 h por padrão).
- 🔑 Contas Google mostra “🎬 sem crédito de vídeo até … (imagem ok)” / “🖼 sem crédito de imagem até … (vídeo ok)”;
  “Liberar” limpa os dois.

## 🎬 Google Flow: conta sem créditos → próxima conta sozinho (v84_104)

- Com o HTML que você mandou: quando a conta não tem crédito (pra vídeo, por exemplo), o Flow **some com o “Iniciar
  geração”** e põe no lugar o **“Alerta de créditos insuficientes”**. Antes o site dizia “não achei o botão Iniciar
  geração” e parava; agora ele reconhece isso como **sem créditos**.
- Na geração de vídeos do site: a conta fica marcada como esgotada e o pedido é refeito na **próxima conta** (como já
  acontecia com o aviso de limite).
- Na aba **🎬 Google Flow** (✨ Gerar e 🧪 Testar o Flow): mesma coisa — opção **“🔁 sem créditos → próxima conta”**
  (ligada): marca a conta, abre a próxima, cria um projeto novo e refaz o **mesmo** pedido (no teste, a foto já gerada
  é reenviada como Início). Sem outra conta com crédito, o erro diz isso.

## ⚡ Geração rápida de voz: várias cópias do motor no mesmo áudio (v84_103)

- 🎙️ Gerador de voz → **⚡ Geração rápida** (desligada por padrão). Ligada, o texto é cortado em blocos (entre frases) e
  2, 3 ou 4 cópias do motor (XTTS, Chatterbox, Turbo, Kokoro, Piper, Fish) geram **blocos diferentes ao mesmo tempo**;
  no fim o site junta na ordem (com `[[INSCREVA]]`/`[[VENDA]]` cada parte continua com o tempo exato).
- **Automático**: o site mede o PC na hora — **VRAM livre** da placa NVIDIA, **RAM livre** e **núcleos de CPU** — e usa
  quantas cópias cabem (até 3); texto curto vai com 1. Ou fixe 2, 3 ou 4 (o site nunca passa do que cabe na RAM/VRAM).
  A tela mostra o que o seu PC tem livre e quantas cópias vão rodar.
- ⚠ **Aviso**: pode deixar o PC um pouco lento enquanto gera (mais placa, memória e CPU). Se faltar memória numa cópia,
  o bloco dela volta pras outras; o que falhar é gerado de novo numa cópia só.
- **📝 Roteiro para Áudio**: as falas agora são geradas todas de uma vez — num processo só (o modelo carrega **uma**
  vez, não uma por fala) ou, com a geração rápida ligada, em várias cópias ao mesmo tempo.
- A fila do Gerador de voz conta a VRAM de todas as cópias; e a escolha “🎛 Ao mesmo tempo” agora fica salva de verdade.
- ⚙️ Configurações → **Fontes de vídeo**: a ordem arrastada agora é **salva na hora** (aparece “✔ Ordem salva”) — antes só
  valia depois de clicar em “Salvar configurações”, lá no fim da página.

## 📺 Perfis do canal: biblioteca de intro, inscreva-se, venda e final (v84_101)

- Página nova **📺 Perfis do canal** (menu do topo): cada perfil é um canal seu, com o **nome do canal** falado nos
  roteiros e uma biblioteca de vídeos de **🎬 intro**, **👍 inscreva-se**, **🛒 venda** e **🏁 final** — quantos quiser de
  cada (envie vários de uma vez ou arraste), com prévia, nome editável e um **⭐ padrão** por tipo.
- O perfil **✅ ativo** é o que os vídeos novos usam: intro no começo, final no fim, inscreva-se/venda nas marcas
  `[[INSCREVA]]`/`[[VENDA]]`.
- No editor, aba **✂️ Cortes**: **📺 Perfil do canal deste vídeo** (trocar de perfil passa as chamadas e a intro/final pro
  padrão do perfil novo); quando um tipo tem mais de um vídeo, **escolha qual entra** — na intro/final e em cada marca de
  venda/inscreva-se (dá pra alternar vídeos diferentes entre as marcas). Vídeo enviado no editor pode ir direto pra
  biblioteca do perfil.
- Os vídeos padrão que você já tinha viram o perfil **“Meu canal”** sozinhos. ⚙️ Configurações → 📺 Seu canal continua
  funcionando (vai pro perfil ativo).

## 🔎 Checagem (cronologia · alegações · repetições), 🕘 histórico de versões e 💾 fim do "WinError 5" (v84_100)

- **🔎 Checagem do roteiro** (🕵️ Modelos de vídeo e 📜 Roteiro do YouTube), com 3 focos:
  - **⏳ Cronologia** — o site monta a linha do tempo do roteiro e acha conflitos do tipo “informante *ab 1924*” × trecho
    de 1918 que já fala disso; a IA confere datas, idades e o começo/fim de cada relação contra as fontes.
  - **📚 Alegações históricas** — cada afirmação contra as fontes do projeto (no YouTube, a transcrição); fato ×
    alegação com quem afirmou; condenado × acusação × ligado pela polícia × alegado × estimado; e a lista do que precisa
    ser **conferido fora** (com caixinha “conferido”) — citar uma fonte no texto não confirma a afirmação.
  - **✂️ Repetições** — o site acha parágrafos distantes que contam a mesma coisa e assuntos que voltam demais
    (com o nº da linha, como num editor); a IA corta (`"para": ""`) ou reduz à meia frase nova.
  A IA devolve as correções como trocas e o site aplica (aspas „“ × "" toleradas).
- **🤖 Revisar + checar + corrigir (tudo automático)**: 🪄 revisão (✂️ enxuga se passou do tempo) → 🔎 checagem com
  correção → ✂️ enxuga de novo se ainda estiver longo. Roda no servidor (pode fechar a aba).
- **🕘 Histórico do roteiro** (tipo o git): toda mudança — IA, partes, revisão, checagem, TTS, edição sua, desfazer —
  vira uma versão com data, origem e +/− palavras; **👁 o que mudou** mostra o diff (riscado vermelho / novo verde,
  comparando com qualquer versão) e **↩ voltar pra esta** restaura (voltar também vira versão). Fica em
  `historico/` dentro da pasta do projeto (últimas 80).
- **💾 “[WinError 5] Acesso negado … projeto.json”**: no Windows, o antivírus/indexador/OneDrive às vezes segura o
  arquivo no instante em que o site troca o .json salvo. Agora a troca tenta de novo por alguns segundos e, se ainda
  assim não der, grava direto por cima — vale pra todos os arquivos de projeto do site.
- O plano dos capítulos dá um **capítulo “dono”** pra cada assunto que atravessa o caso, e as regras de escrita ganharam
  **cronologia coerente** e **números com nome**.

## 📏 Roteiro no tempo certo, ✂️ revisão que enxuga e 🎙/🪄 botões da IA consertados (v84_99)

- **Tamanho das partes com teto**: cada capítulo agora pede **entre 90% e 110%** do tamanho dele (antes era só “no mínimo”
  — a IA esticava e 25 min viravam 38). Capítulo acima de 125% fica **⚠ longa** e o “🤖 Escrever com a IA” reescreve ele
  enxuto (até 2 tentativas, depois aceita e avisa).
- **Sem recontar**: o prompt de cada parte traz a lista do que **JÁ FOI CONTADO** nas partes anteriores (e o que vem
  depois) — prisão, julgamento e legado não refazem o resumo do caso.
- **Aviso de roteiro LONGO** (acima de 115% do tempo) no Modelos de vídeo e no Roteiro do YouTube, apontando pra revisão.
- **🪄 Revisão — modo ✂️ enxugar** (automático quando passou de 110% do tempo, ou escolha no menu): as trocas podem
  encurtar ou **apagar** trechos (`"para": ""`) até o tamanho pedido — repetição entre capítulos, recapitulações, suspense
  vazio, fórmulas de análise. O modo 🪄 melhorar continua sem encurtar. O trecho é achado mesmo quando a IA troca as
  aspas („…“ × "…"), travessões ou reticências — antes isso fazia as trocas “não baterem”.
- **Regras de narração novas** (método, partes e revisão): fim de seção com revelação/consequência/pergunta necessária
  (nada de suspense pra encher); conclusão do tamanho da prova (motivo/acordo/omissão só com a fonte específica, senão
  suavizado); fórmulas como „Hier liegt die eigentliche Frage“ / „Man muss an dieser Stelle vorsichtig sein“ / „Eine
  mögliche Lesart ist“ no máximo 1× no vídeo; frases curtas nos momentos de tensão (voz sintética).
- **🎙 Adaptar pro TTS / 🪄 Revisão com a IA**: o 🤖 mandava o pedido de texto puro com a instrução de sistema “responda só
  JSON” — a IA embrulhava o texto num JSON com outra chave e o site dizia “resposta vazia”. Agora o site manda em texto
  puro e ainda aceita JSON com qualquer chave. E apertar 🤖 com um prompt já gerado não espera mais 30 s à toa.
- Menos `[[VENDA]]`: ~3 num vídeo longo (antes 1 a cada ~450 palavras).

## ✍️ Partes também no Roteiro do YouTube, 🪄 revisão do roteiro inteiro e 📊 analisador sem erro (v84_98)

- **📜 Roteiro do YouTube** longo (⏱ ≥ 8 min, ou o vídeo original com ≥ 8 min; escolha “✍️ em partes” no passo 2): a
  IA devolve o PLANO (capítulos com objetivo, fatos com o tempo na transcrição e as cenas de cada capítulo) e depois
  escreve um capítulo por vez, em texto puro — à mão (colando na mesma conversa) ou 🤖 todos com a IA. No fim vira UM
  roteiro inteiro, com `[[INSCREVA]]`/`[[VENDA]]` entre os capítulos. “📏 Completar o tamanho” também é por partes.
- **🪄 Revisão do roteiro inteiro** (🕵️ Modelos de vídeo e 📜 Roteiro do YouTube): uma passada no texto TODO pra ele
  soar como um roteiro só — costuras entre capítulos, frases genéricas/clichês de IA trocadas por detalhes concretos,
  repetições, ritmo, laços abertos. A IA devolve só as TROCAS (`{"de", "para"}`) e o site aplica — o roteiro não
  encolhe; o que não bater é avisado; ↩ volta ao de antes.
- **📊 Analisador de canal**: análise com vídeo sem o número de views (ou vídeo que saiu da lista) não derruba mais a
  página (era `UndefinedError: 'dict object' has no attribute 'views'`).

## ✍️ Roteiro longo escrito em partes (v84_97)

- Por que o roteiro saía pequeno: pedir ~18 min (~2.700 palavras) DENTRO de um JSON junto com títulos, descrição,
  capítulos, thumbnails e afirmações faz a IA de chat entregar ~40–50% (no exemplo: 1.228 palavras); e o 📏 completar
  pedia o roteiro inteiro de novo num JSON — o mesmo problema.
- Agora, nos 🕵️ Modelos de vídeo a partir de ~8 min (ou sempre, em “✍️ Escrever o roteiro em partes”): o 1º prompt
  devolve só o **PLANO** (títulos, descrição, thumbnails e os capítulos com objetivo, fatos com fonte, mídias e quantas
  palavras cada um tem); depois **um prompt por capítulo**, resposta em **texto puro** (cada um inteiro, ~300–450
  palavras), na mesma conversa (ela já tem as fontes) — ou **🤖 Escrever com a IA**, que faz todos em sequência.
  Com todos prontos, o site junta, põe `[[INSCREVA]]`/`[[VENDA]]` entre os capítulos e os capítulos da descrição saem
  com o começo exato.
- **📏 Completar o tamanho por partes**: o roteiro curto é cortado nos capítulos (mesmo quando a IA errou o começo
  deles) e só os trechos curtos são reescritos, um por vez, em texto puro. Texto puro colado no “Ler resposta” também
  vira o roteiro novo. No modo de um prompt só, o `"roteiro"` agora vem PRIMEIRO no JSON.

## 🖼 Thumbnails no Google Flow e 🎙 adaptar o roteiro pro TTS por idioma (v84_96)

- **🖼 Thumbnails**: onde a IA recomenda thumbnail (🕵️ Modelos de vídeo — 3 por roteiro; 📜 Roteiro do YouTube — junto com
  🔥 Títulos / 📝 Descrição; 📊 Analisador de canal — a “capa” de cada vídeo sugerido) aparece o bloco **🖼 Thumbnails**:
  cada ideia com o texto grande e o prompt da imagem (editáveis). **🎨 Gerar no Flow** (uma ou todas, em segundo plano —
  o 🔔 avisa): o Flow gera a imagem 16:9 sem letras e o site põe o texto por cima (contorno, degradê, 1280×720), pronta
  pra baixar. “🔁 Outra imagem” gera uma variação. Arquivos em `thumbs/` (`thumbs_flow.py`).
- **🎙 Adaptar o roteiro pro TTS** (`adaptar_tts.py`), nos 🕵️ Modelos de vídeo e no 📜 Roteiro do YouTube: um prompt
  prepara o texto pra voz NO IDIOMA DELE — frases naturais, pontuação que dá as pausas, números/datas/siglas do jeito
  que se fala, nada de [pausa]/[dramático] que o TTS leria — sem mudar fatos nem encurtar, mantendo as marcas do site
  ([[INSCREVA]], [[VENDA]], [I3], [CENA n]) e as frases de começo de capítulo. **Alemão** tem regras próprias
  (Hochdeutsch, compostos, ä/ö/ü/ß); os outros idiomas usam o modelo geral até ganharem o deles. A **direção narrativa**
  muda com o tipo de vídeo (true crime, história, biografia, mistério, documentário) e o motor (Chatterbox, Turbo com
  tags…). A resposta é só o texto: o site confere marcas e tamanho, troca o roteiro e guarda o anterior (↩ voltar).

## 📺 Canal: nome nos roteiros, abertura/encerramento e roteiro como guia (v84_95)

- **⚙️ Configurações → 📺 Seu canal**: o **nome do canal** (a IA fala no começo, logo depois do gancho, e no fechamento —
  nos Shorts, uma vez no fim) e os vídeos de **🎬 abertura** e **🏁 encerramento**: como os de 👍 inscreva-se e 🛒 venda,
  envia uma vez e eles entram sozinhos no começo e no fim de todo vídeo montado (legenda e capítulos andam junto). No
  editor → aba ✂️ Cortes dá pra desligar ou trocar em cada vídeo. Cada projeto de 🕵️ Modelos de vídeo, 📜 Roteiro do
  YouTube e 🎞️ Vídeos modelados pode usar outro nome (ou “-” pra não falar).
- **✍️ O roteiro/as referências são GUIA**: em todos os prompts de roteiro (🕵️ Modelos de vídeo, 📜 Roteiro do YouTube,
  🎞️ Vídeos modelados) a IA usa o seu roteiro, as anotações, a transcrição do vídeo original e a referência viral só pra
  saber os fatos — e cria a própria linha de storytelling (gancho, ângulo, ordem das revelações), sem clonar nem seguir
  ponto a ponto, mantendo a duração pedida.
- **🕵️ True crime**: a narração diferencia **fato documentado** (com a fonte: autos, laudo, reportagem), **alegação**
  (sempre atribuída: “a defesa sustentou”, “ele alegou”) e **interpretação do narrador**; a IA devolve a lista
  “🔎 Fatos, alegações e interpretações” com a fonte de cada afirmação importante (sem fonte aparece em vermelho).
  Frases que amontoam dados viram **unidades de sentido** (uma informação por frase) — principalmente na infância,
  nas avaliações médicas e na investigação policial. A regra “uma ideia por frase” vale em todo roteiro.

## ✍️ Escrita no papel, fontes de máquina/à mão e legenda com o texto do roteiro (v84_94)

- **Quadro ✍️ Escrita** (🗞 Editorial): o texto aparecendo letra por letra, de 3 jeitos:
  - **mão** — a caneta (ou o giz) escreve com a ponta andando junto; papel **branco, antigo** (amarelado, manchas,
    dobras, borda queimada), **caderno, quadriculado, carta, kraft, post-it, guardanapo** ou **quadro-negro**;
  - **máquina de escrever** — cada tecla bate a letra (tinta irregular, letra um pouco torta, batida dupla de vez em
    quando), o carro anda, no fim da linha toca o **sininho** e o carro volta, o papel sobe pelo rolo; no fim a câmera
    recua e mostra a folha;
  - **computador** — documento, bloco de notas, editor de código (cores e números de linha) ou **mensagem** (cada linha
    é digitada e ENVIADA como balão ✓✓); ritmo humano e, se quiser, um erro de digitação apagado.
  - Extras: título, data no canto, assinatura à mão e **palavras de destaque** circuladas/sublinhadas (no computador,
    marca-texto). Sons novos da máquina de escrever (datilografando, tecla, sininho, retorno do carro).
- **Fontes** (`fontes_escrita.py`): solte .ttf/.otf em `assets/fonts/maquina|manuscrita/` (livres, vão pro GitHub) ou
  `assets/fonts/pessoais/maquina|manuscrita/` (**uso pessoal — no .gitignore**, ficam só no seu PC; aparecem com ⚠).
  Fonte sem acento/número: a letra base da própria fonte + o acento desenhado por cima; o que faltar vem da reserva.
  A **letra à mão** também é escolhível no calendário do mês/ano, na folhinha e na lista riscada.
- **Calendários: idioma "auto"** = o idioma do vídeo (ou fixe pt, en, es, fr, it, de).
- **Legenda do 🗣️ Gerador de voz com o texto do roteiro**: o TTS não diz em que instante cada palavra é falada, então o
  Whisper ainda ouve o áudio — mas só pra medir o tempo; as palavras são as do texto (nomes, acentos, números e
  pontuação como você escreveu) — `legenda_texto.py`. Sem Whisper, a legenda sai com tempos estimados.

## 📅 Calendários, folhinha, placar de datas e lista riscada à mão (v84_93)

Cinco quadros novos no **🗞 Editorial** do Estúdio (e no prompt de edição da IA), tudo desenhado com traço "à mão"
(círculo com 1,1 volta e tremido, risco ondulado, X em dois traços, ✓, seta curva — a caneta andando) e letra
manuscrita (Kalam / Permanent Marker, licenças livres em `assets/fonts/manuscrita/`):

| Quadro | O que faz | Campos principais |
|---|---|---|
| 📅 `calendario_mes` | a folha do mês cai na mesa e a caneta **circula** o dia, faz um **X**, passa **marca-texto** na semana ou **risca os dias um a um** até o dia marcado; anotação à mão com seta | mês, ano, dias (`18` · `4, 18` · `10-16`), marca, anotação, idioma pt/en/es |
| 🗓 `calendario_ano` | os 12 meses; circula os meses, passa marca-texto ou risca mês a mês até o mês final | ano, meses (`3-7` · `mar, jun`), marca |
| 📆 `folhinha` | folhinha de mesa **arrancando páginas** (acelera e freia) até a data final, que fica circulada | de/até: `dd/mm/aaaa` = dias · `mm/aaaa` = meses · `aaaa` = anos |
| 🛫 `placar_datas` | placar de aeroporto (split-flap) virando MÊS e ANO até a data final (no vertical: mês em cima, ano embaixo) | de/até, rótulo |
| ✅ `lista_riscar` | lista **escrita à mão** item por item (caderno, post-it ou quadro-negro), depois riscada / ✓ / circulada | itens: `x ` = riscar · `v ` = ✓ · `! ` = circular |

Com sons próprios (papel, caneta, catraca) e funcionando em 16:9 e 9:16. O marca-texto multiplica a cor (os números
continuam legíveis) e o texto comprido diminui pra caber no papel.

## 🎧 Perfis de voz: áudio limpo × com música de fundo (v84_92)

- Cada perfil de voz (🗣️ Perfis de voz) é marcado **🎙️ limpo** ou **🎵 tem música/efeitos de fundo** — ao criar (upload
  ou YouTube) ou depois, no próprio perfil.
- Com música, o site processa os clipes **uma vez** com o **Demucs** (o mesmo da 🌐 dublagem), em segundo plano (aviso
  no 🔔): no lugar de cada clipe fica **só a voz** — é o que a clonagem (XTTS / Chatterbox / Turbo) usa. O áudio como
  veio fica em `_original/` dentro da pasta do perfil: dá pra **ouvir os originais** e **↩ voltar aos originais**.
- Clipe novo num perfil marcado 🎵 é limpo sozinho; os já limpos não são processados de novo. Precisa de
  `pip install demucs` (com placa de vídeo NVIDIA ele usa a GPU).

## 🎬 Revisão do diretor + 🖼️ nada de mídia em pé num vídeo deitado (v84_92)

- **🖼️ Formato:** a prévia agora pede o formato do vídeo aos bancos que têm esse filtro (antes só a montagem pedia — a
  prévia escolhia e FIXAVA um vídeo em pé num vídeo 16:9). Nos outros, a miniatura é conferida: em pé num vídeo deitado
  (ou o contrário) vai pro fim da fila; se a busca só tiver isso, tenta a próxima.
- **🎬 Revisão do diretor** (Estúdio → aba 🤖 IA): passa pela timeline e aponta o que não combina — sem prévia, formato
  errado, desenho/3D, nota baixa, repetida. Com a 🤖 IA ligada (recurso "🎬 Revisão do diretor" em 🤖 IA), ela **olha a
  miniatura de cada trecho com a fala de antes e de depois** e decide: **busca nova** no buscador com mais chance
  (bancos de vídeo pra cena genérica, buscadores de imagem/Wikipedia pra coisa real e específica, YouTube pra alguém
  falando — só os marcados), **📊 gráfico nativo** quando a fala cita números (dados só da fala, sobre um fundo),
  **🃏 cartão** de texto pra ideia abstrata, ou **✋ procurar na mão** (diz o quê). Você marca o que aplicar; as buscas
  novas são conferidas (pulando desenho e formato errado) e o que ainda assim não achar fica marcado **🔎 laranja na
  timeline**, com o que procurar no painel do trecho (“✓ Resolvido” tira a marca). Dá pra desfazer. Roda em segundo
  plano (pode fechar o Estúdio — chega um aviso no 🔔).

## 🎞️ Vídeo de imagens reais sem desenho no meio + buscas com contexto (v84_92)

- **Filtro de estilo (sem IA, de graça):** o site olha a miniatura de cada resultado e manda pro fim da fila o que parece
  **boneco 3D / recorte em fundo branco**, **objeto recortado em fundo preto** ou **ilustração vetorial**. Se a busca só
  tem isso, tenta a próxima busca e os outros bancos; só usa um desenho (com ⚠) se não achar nada real.
  ⚙️ Configurações → **🎞️ Estilo das imagens**: Automático (padrão) / Sempre só reais / Qualquer estilo.
  Os acervos de anime/filmes e o Flow ficam fora do filtro.
- **🤖 Com a IA ligada:** a ficha do vídeo agora diz o **estilo** (real / ilustração / misto); o juiz dá **no máximo 2**
  pra desenho/3D/vetor/recorte num vídeo de imagens reais; e quem escreve as buscas recebe a **fala de antes e a de
  depois** de cada trecho — a busca descreve a cena daquele momento da história, não palavras soltas da frase.
- O prompt principal de edição também pede isso (contexto de antes/depois e nada de "cartoon", "3d", "vector"…).

## 📏 O tempo escolhido vale de verdade (v84_92)

- Pôs 18 min e veio roteiro de 8? As IAs de chat encurtam roteiro longo. Agora o prompt tem uma seção **📏 TAMANHO**
  perto do fim, com o **mínimo de palavras** e quantas palavras cada parte da estrutura deve ter.
- Ao **ler a resposta**, o site confere: abaixo de 85% do alvo aparece o aviso e o botão **📏 Prompt pra completar o
  tamanho**. Cole esse prompt na **mesma conversa** da IA (ela já tem as fontes) e traga o JSON no “Ler resposta”: só o
  roteiro é trocado — títulos, descrição, capítulos (e as cenas, no Roteiro do YouTube) ficam.
- Vale no 🕵️ **Modelo de vídeo** (campo Minutos) e no 📝 **Roteiro do YouTube**, que ganhou o campo **⏱ min** no passo 2
  (vazio = o tamanho do vídeo original, como antes).

## 🎬 Sem a fonte youtube marcada, nada vira clipe do YouTube (v84_92)

- Escolher um projeto do **📝 Roteiro do YouTube** (ou ele vir no .zip do Gerar voz) **não marca mais o youtube
  sozinho**. Com o youtube marcado, cada [CENA n] vira trecho do YouTube, como antes. Sem ele, as cenas vão pro prompt
  só como contexto: a IA ilustra com os bancos marcados e nenhum clipe é pesquisado no YouTube.
- Os **cortes reais** sugeridos pela IA continuam (pra você enviar o seu clipe), mas sem o youtube marcado o site não
  pesquisa nada no YouTube pra eles.
- Se algum trecho ainda chegar como "youtube" num vídeo sem essa fonte, ele vira o 1º banco de vídeo marcado (mesma busca).

## 🖼️ Google Imagens como buscador de imagem + IA do Google atualizada (v84_92)

- A pasta **ia_google/** foi atualizada pra versão nova do app (aba **🖼️ Imagens**: link da imagem **original** em
  tamanho real, resolução, página de origem, “➕ Mais imagens” pelas relacionadas do painel lateral, baixar uma ou
  todas em .zip). Continua com o que só existe no site: 🔁 “olhar de novo” nos momentos do vídeo, captcha reabrindo o
  navegador visível e a porta 8852.
- **Novo buscador de imagem `google`** (ao lado de Bing/Brave/Yandex/Startpage): marque **google** nos provedores do
  vídeo. Ele pesquisa no Google Imagens pelo **Modo IA do Google**, usando a API do app (`POST /api/imagens`, ver
  `ia_google/README.md`) — o site liga o app sozinho. A IA de edição pode escolher `"provider": "google"` com
  `"media_type": "image"`, e a troca entre buscadores funciona igual: se o Google não achar ou o app não subir, o
  termo vai pros outros buscadores marcados.
- As imagens **grandes** e na **proporção** do vídeo vêm primeiro (⚙️ Configurações → 🔎 IA do Google → tamanho mínimo
  preferido: 800 px por padrão; as menores só entram se não houver outra). Imagem de banco pago com marca d'água fica
  de fora, como nos outros buscadores.
- É **um navegador só**: os termos vão um de cada vez (~10-30 s cada), em paralelo com os outros buscadores. Em vídeos
  antigos (sem a lista de provedores marcados) o Google não entra na troca entre buscadores, só se o trecho pedir.

---

## 🤖🔎 Achar com Claude + Google em todas as partes de YouTube (v84_88)

Botão **alternativo** ao lado das buscas normais: o **Claude** faz as buscas (e refaz de outro jeito se não achar, até
3) e escolhe os vídeos mais prováveis pela capa/título/canal/duração; o **link** de cada um vai pra **🔎 IA do Google**
pela API dela, que "assiste" o vídeo e devolve o **início/fim** do momento — sem depender de legenda (`yt_google.py`).

- **📜 Roteiro do YouTube → 🎬 Cenas**: "🤖🔎 Achar com Claude + Google" em cada cena e "Achar todas as cenas sem link";
  preenche link + início/fim e salva. Mostra o andamento de cada cena ("como foi").
- **Editor / Estúdio → 🎬 Vídeos do YouTube**: "🤖🔎 Claude + Google acham" (todos) e "🤖🔎 Claude + Google" em cada item;
  achou → baixa e corta sozinho, igual ao agente normal.
- **✂️ Cortar do YouTube**: em cada trecho, escreva na descrição o que a cena mostra e clique "🤖🔎 Achar com Claude +
  Google" — com link, a IA do Google acha o trecho nesse vídeo; sem link, o Claude busca o vídeo também.
- **🔁 Não é esse — olhar de novo** (v84_89): se a IA do Google errou o momento, o botão pede pra ela olhar o MESMO vídeo
  de novo, na mesma conversa, dizendo que o(s) momento(s) anterior(es) não tinham o que buscamos e reafirmando o que é.
  Os recusados vão se acumulando (e nunca voltam como resposta). Tem nas 🎬 cenas do Roteiro do YouTube (aparece quando a
  cena tem link), no painel do YouTube do editor (depois que acha) e no ✂️ Cortar do YouTube (depois do ✅), além do
  próprio app 🔎 IA do Google (embaixo do resultado de "Achar momentos"/"Perguntar").
- **▶ Prévia + 🧾 respostas da IA por clipe** (v84_90): colocou um link, aparece a miniatura e o "▶ Ver o trecho" (toca só
  do início ao fim, ali mesmo). E CADA resposta da IA fica guardada no clipe — cada vídeo que a IA do Google olhou (achou
  ou não), cada leitura de legenda e cada "olhar de novo" — com miniatura, tempo, a frase, "▶ ver" e "✔ usar esta"
  (marca a que está em uso). Nas cenas do Roteiro do YouTube aparece até enquanto ainda está procurando; no editor fica
  em "🧾 Respostas da IA pra este clipe"; no ✂️ Cortar do YouTube em cada trecho (+ "▶ ver trecho" e a miniatura/título
  do link).
- **➕ Buscar outros vídeos** (v84_91): em toda busca do YouTube (cenas do Roteiro, editor, Cortar do YouTube) dá pra
  trazer os **12 seguintes** da mesma busca, sem repetir os que já apareceram (no editor aparece quando acabam os "Outros
  vídeos").
- **🔎 Perguntar ao Google onde achar** (v84_91): pergunta pra IA do Google (pesquisando, com foco no YouTube) ONDE está a
  cena — ela indica os links e os tempos; os 3 primeiros ela **assiste** pra confirmar o momento (se nenhum confirmar, fica o
  tempo que a pesquisa indicou). Cada indicação e cada conferência entram no 🧾 histórico do clipe. Botões por cena/item/
  trecho e "pra todas sem link".
- **🔎 Achar o momento num vídeo que você já tem**: em cada resultado da busca da cena ("🔎 achar o momento") e no editor,
  com o vídeo escolhido ("🔎 Achar o momento com a IA do Google") — ela assiste ESSE vídeo e preenche início/fim.
- Tudo roda no servidor (pode fechar a aba) com aviso no 🔔 e registro no 🕘 Histórico. Precisa da pasta `ia_google/`
  (funciona mesmo com o modo da IA do Google no agente em "desligado"); sem o Claude ligado ele usa a busca direta.

## 🔔 Notificações, tudo em segundo plano e 🕘 Histórico (v84_87)

- **🔔 Sininho** no canto de cima de TODAS as páginas (inclusive o Estúdio): bolinha vermelha com o número de não lidas
  (também aparece no título da aba). Clicando abre a lista; clicando num aviso você vai direto pro lugar (o vídeo pronto,
  o áudio no histórico, o zip, o projeto…). Chega um balãozinho quando aparece aviso novo. Guardado em
  `outputs/notificacoes.json` (não vai pro git).
- Avisa quando termina ou dá erro: áudio do Gerador de voz, narração do Roteiro para Áudio, falas da Conversa,
  transcrição/prompt do vídeo, prévias, 🎞️ timeline 2, 🎬 montagem, cortes/clipes do YouTube no editor, 🤖 agente do
  YouTube, ✂️ Cortar do YouTube, 📲 Baixar de outras redes, 📝 Transcrever, 🖼️ Capturar página, 🔗 Extrair links,
  🎬 Google Flow (e login do Flow), 🎞️ Vídeos modelados, 🕵️ Modelos de vídeo, 🛒 Venda, 📜 Roteiro do YouTube,
  📊 Analisador de canal, perfil de voz do YouTube e todas as tarefas de IA abaixo.
- **🔒 Captcha**: se a 🔎 IA do Google pedir captcha com o navegador **oculto**, ela reabre o navegador **visível** na
  mesma página e espera você resolver (antes dava erro). O sininho avisa ("resolva na janela") e o aviso some sozinho
  quando você resolve; a aba 🔎 IA do Google mostra uma faixa amarela. No 🎬 Flow, login/captcha com o navegador oculto
  vira um aviso pedindo pra rodar com "navegador visível".
- **Tudo em segundo plano** (pode clicar, fechar a aba e voltar depois): o que antes precisava ficar com a aba aberta
  agora roda no servidor (`tarefas_bg.py`, salvo em `outputs/tarefas/`):
  - 🤖 **Gerar com a IA** (Modelos de vídeo, Venda, Roteiro do YouTube, Modelados, prompt das buscas) — voltando na
    página a resposta é colada e lida sozinha;
  - 🪄 **Fazer com a IA** da edição no Estúdio — a resposta fica guardada e é colada no painel ao voltar;
  - ✅ **Checar fatos** — o resultado volta sozinho no roteiro;
  - 🔗 **Extrair links de canal**.
  Continuam na aba só as coisas de edição ao vivo do Estúdio (prévias, 💬 conversa com a IA, ver/ouvir), porque mexem no
  que ainda não foi salvo.
- **🕘 Histórico** (link no menu e no sininho): todas as tarefas (com o resultado pra copiar) e todos os avisos, mais
  atalhos pros históricos de cada ferramenta. Ganharam histórico que sobrevive a fechar o site: ✂️ Cortar do YouTube,
  📲 Baixar de outras redes, 📝 Transcrever, 🖼️ Capturar página (um `_job.json` na pasta de cada um) e 🔗 Extrair links.

## 🔎 IA do Google dentro do site (v84_86)

- O app **ia_google/** (pesquisa no Modo IA do Google por um navegador automatizado: chat com fontes + análise de vídeos
  do YouTube) agora vem junto e roda **à parte**, na porta **8852** (a 5000 dele brigava com o Anime Pexels local) —
  aba **🔎 IA do Google** no menu de cima (liga sozinho ao abrir). Precisa de `pip install -r ia_google/requirements.txt`.
- **🤖 Agente do YouTube**: quando o vídeo **não tem legenda** ou a leitura da legenda **não achou** o momento, a IA do
  Google **assiste o vídeo** e dá o início/fim (⚙️ Configurações → 🔎 IA do Google: "complemento" (padrão), "sempre
  primeiro" ou "não usar"). Funciona até sem a IA do Claude ligada.
- **✅ Checar fatos** no 📜 Roteiro do YouTube (embaixo do roteiro): a IA do Google confere nomes, datas e números na web
  e diz o que está certo/errado, com as fontes.
- O perfil do navegador dela, as conversas, prints e HTMLs (`ia_google/perfil_navegador/`, `conversas/`, `debug/`,
  `erros/`, `config.json`…) são pessoais: ficam fora do git e do zip.

---

## 🪧 Cartão sobre fundo + direção "Propaganda" (v84_85)

- Nova opção de **Bordas: 🪧 Cartão sobre fundo** (no topo do Estúdio, por trecho ou nas Configurações). Imagem de
  formato diferente do vídeo (capa de livro, produto em pé, print) vira um **cartão** com cantos arredondados e sombra
  que sobe de leve, aparece e fica flutuando por cima de um **fundo em movimento**. Fotos seguidas passam sobre o
  **mesmo fundo** (ele continua de onde parou, sem pulo). Foto com o formato do vídeo continua ocupando a tela; vídeo
  de outro formato fica no mosaico.
- **O fundo** (🎨 Direção → 🪧 Cartão sobre fundo), por projeto:
  - **✨ Fundo animado**: gradiente, luz diagonal, névoa, grades, ondas, pontos, linhas ou papel, na cor que você
    escolher (padrão: a primária da paleta do projeto) — deriva devagar.
  - **🎞 Clipe de vídeo**: um vídeo que você mandou pra 📁 Mídia, ou o site busca um nos bancos na montagem (ex.:
    "abstract background bokeh") — com desfoque e escurecer ajustáveis. Se não achar, usa o fundo animado.
- **Direção "Propaganda (cartões sobre fundo)"**: liga o cartão, transições rápidas (deslizes, zoom, woosh), entradas
  com pop, cor viva e destaques grandes de oferta.
- Os clipes já montados antes são refeitos uma vez (mudou o jeito de montar fotos).

---

## 🖼 Capa/imagem em pé sem zoom gigante + 🎬 entradas que travavam (v84_84)

- Imagem com proporção bem diferente do vídeo (capa de livro em pé num vídeo 16:9, print vertical…) agora respeita as
  **Bordas** escolhidas: **Bordas pretas** ou **Mosaico** mostram a imagem **inteira** (mosaico = cópias desfocadas dela
  no fundo, igual aos vídeos) e a câmera mexe pouco (zoom de no máximo ~14%). **Zoom (preencher)** continua cortando.
  Antes toda foto era cortada pra preencher a tela + zoom de até 40%.
- **Bug corrigido**: as entradas que mudam o tamanho da imagem (Liga TV, Zoom, Estica, Pop, Gira…) ficavam TRAVADAS no
  começo do gesto o trecho inteiro — a imagem virava uma linha fina no meio da tela preta (Liga TV) ou ficava pequena.
  Agora o gesto acontece e a imagem fica inteira.

---

## 💬 Falar com a IA no editor + 🔄 Trocar / 🗑 Tirar (v84_83)

- **Sem IA**: selecione um trecho, uma transição (losango) ou um destaque — ou vários — e use os botões que aparecem no
  topo do painel da direita:
  - **🔄 Trocar** = troca por um **parecido** (mesma família e energia do catálogo do DarkPlanner; clique de novo pra
    outro). Trecho sem efeito ganha um efeito discreto que combina com a mídia (câmera só em foto).
  - **🗑 Tirar** = tira efeito/entrada/saída do trecho, vira **corte seco** na transição, remove o destaque.
  - **↩ Desfazer** volta a última troca (até 40 passos).
- **Com a IA ligada** (🤖 IA → "✂️ Prompt de edição"): botão **💬 Falar com a IA** no topo. Selecione a parte (ou nada =
  o vídeo todo) e escreva: "deixa esse mais dramático", "tira o zoom", "transição mais suave aqui", "muda o texto
  desse destaque pra …", "põe um destaque com o ano". A IA vê os trechos selecionados + 2 vizinhos de cada lado, os
  destaques e a fala daquela parte, e responde só o que muda — aplicado na hora, com **↩ desfazer** em cada resposta.
  A conversa lembra os últimos pedidos ("agora mais rápido").

---

## 🐟 Novo motor de voz: Fish Audio S2 — clonagem + tags de emoção em português (v84_82)

- Em **🎙️ Gerador de voz**, **📝 Roteiro para Áudio**, **💬 Simular Conversa**, **🎭 multi voice** e dublagem: motor
  **Fish Audio S2**. Clona a voz com 10–30s de áudio (o mesmo **perfil de voz** do XTTS/Chatterbox) e entende **tags de
  emoção em qualquer ponto do texto**, inclusive em PT: `[excited] Você não vai acreditar! [whisper] É segredo…` —
  vale também descrição livre curta (`[sussurrando bem baixinho]`, `[pitch up]`).
- O Fish clona melhor sabendo o que é dito no áudio de referência: o site **transcreve com o Whisper** na 1ª vez e guarda
  (`<clipe>.wav.txt` no perfil); no envio avulso dá pra escrever o texto.
- **Onde roda** (⚙️ Configurações → 🐟 Fish Audio S2):
  - **Servidor local**: o modelo (S2 Pro, 4B) roda no programa do [fish-speech](https://github.com/fishaudio/fish-speech),
    à parte — precisa de **~24 GB de VRAM** e **Linux/WSL**. Depois de instalar e baixar os pesos (`fishaudio/s2-pro`):
    `python tools/api_server.py --llama-checkpoint-path checkpoints/s2-pro --decoder-checkpoint-path checkpoints/s2-pro/codec.pth --listen 127.0.0.1:8080`
  - **API da Fish Audio** (paga, com chave): sem GPU; dá pra usar também o ID de uma voz salva na sua conta.
- ⚠️ **Licença**: os pesos abertos do S2 são "Fish Audio Research License" — **uso comercial (vídeo monetizado) precisa
  de licença da Fish Audio** (ou usar a API paga, nos termos dela).
- No site só precisa de `pip install requests msgpack`. A tela mostra se o servidor está no ar.

---

## 🎬 Flow com janela larga: o Agente em painel (v84_81)

- Com a janela larga o Flow não mostra o chip "Agente": o agente vira um **painel à direita** ("Sessão sem título",
  "Olá, … O que você quer criar?") com a própria caixa. A automação agora entende os dois jeitos: configura o agente
  pelo ícone ⚙ (tune) da caixa do painel e **desliga o agente fechando o painel (X)** — aí volta a caixa principal,
  onde a imagem/vídeo é gerada.

---

## 🩺 Erro do Flow: baixar ou copiar a tela pra mandar (v84_80)

- Quando um passo do Flow dá erro, aparecem os botões **⬇ Baixar diagnóstico (.zip)**, **📋 Copiar HTML** (é só colar
  na conversa) e **🖼 ver a tela**. Em **🎬 Google Flow → 🩺 Erros recentes do Flow** ficam os 20 últimos (inclusive dos
  erros gerando vídeo), com os mesmos botões.
- O diagnóstico agora guarda também a **página inteira** (`_pagina.html`, sem scripts/estilos) e a caixa de comando
  mesmo quando está escondida. **E-mail, nome da conta Google e foto do perfil são tirados** antes de salvar.
- A foto e o HTML são da aba **onde o passo falhou** (antes, num erro do "Novo projeto", podiam ser da aba errada).
- "Novo projeto" sem a caixa "O que você quer criar?": recarrega a página uma vez antes de dar erro.

---

## 🎬 Flow: janela larga pra achar o chip "Agente" (v84_78 / v84_79)

- Com a janela pequena (menos de ~900px) o Flow esconde o chip "Agente" e a automação parava em
  `[agente] não achei o chip "Agente" da caixa`. Agora o navegador visível abre com 1400×950 e, se a página estiver
  estreita, a automação alarga a janela sozinha antes de procurar o chip (e de novo se ele não aparecer).
- v84_79: com ~900px o chip já aparece (conferido no seu Flow); o chip agora também é achado pelo texto "Agente"
  (outros jeitos de o Flow montar o botão).

---

## ⛏ Niche Miner não fecha mais sozinho (v84_77)

- O site roda com o recarregador do Flask e o Niche Miner herdava a variável `WERKZEUG_SERVER_FD` dele: tentava usar o
  soquete do site e fechava na hora (`OSError: [WinError 10038] ... não é um soquete`). Agora ele sobe com essas
  variáveis limpas (no site e no próprio `niche_miner/app.py`).

---

## 🎬 Aba Google Flow: gerar pelo site + 🧪 Testar o Flow (v84_76)

- Nova aba **🎬 Google Flow** no menu de cima (`/flow`):
  - **🧪 Testar o Flow**: abre o navegador (visível) e faz o caminho inteiro — Novo projeto → Configurações do agente
    (Nunca, modelos padrão, Salvar) → desliga o Agente → gera uma **foto** → um **vídeo só com texto** → um **vídeo com
    Início (a foto gerada) e Fim**. No fim diz "✅ Flow funcionando: foto ✔ · vídeo ✔ · vídeo com Início/Fim ✔", com cada
    passo (✅/❌, tempo, foto da tela). "Sem gerar" testa sem gastar crédito.
  - **✨ Gerar**: imagem ou vídeo, modelo, proporção, quantidade (x1–x4), frames de Início/Fim, imagem de referência,
    mostrar ou esconder o navegador, conta. O navegador fica aberto no **mesmo projeto** entre um pedido e outro e fecha
    sozinho após 5 min parado (ou em **✖ Fechar navegador**). Enquanto está aberto, o resto do site espera pra usar o Flow.
  - **🖼 Galeria** (`outputs/flow_estudio/`): tudo o que saiu daqui, inclusive do teste — baixar, **🎬 animar** (vira o
    Início de um vídeo; se a imagem é do projeto aberto, usa a própria imagem do Flow sem reenviar), **🏁 como Fim**,
    **🖼 modificar** (referência), **↺ prompt**, apagar.
- Limite de uso: a conta fica marcada como esgotada e a tela pede pra escolher outra.
- O link antigo `/flow/teste` cai nessa aba.

---

## 📜 Histórico de áudios baixa o .zip (v84_75)

- Cada áudio do **📜 Histórico** (Gerador de voz) tem **⬇ ZIP** ao lado de WAV e SRT: narração + legenda + `info.json`
  (idioma, motor, projeto do Roteiro do YouTube / modelo / venda) + chamadas — o mesmo .zip que vai no **Novo vídeo**.
- Funciona também com áudios antigos e depois de reiniciar o site (antes o .zip só saía logo após gerar).

---

## 🎬 Google Flow refeito no HTML real + 🧪 área de teste (v84_74)

- A automação do Flow agora segue exatamente o caminho de quem usa: **Novo projeto → ⚙ Configurações do agente**
  ("Confirmar antes de gerar" = Nunca, modelos padrão de imagem e vídeo, Salvar) **→ desliga o Agente → popup da caixa**
  (Imagem/Vídeo, Frames/Elementos, proporção, modelo, x1) **→ clica fora → Início/Fim pelo menu de mídia**
  ("Incluir no comando") **→ prompt → Iniciar geração → espera o %** → baixa o resultado.
- Os seletores vêm do HTML que você capturou do Flow (sem dados pessoais). Quando um passo falha, o erro diz **qual passo**
  (ex.: `Flow, passo "configurar": modelo "X" não existe — tem: …`), e "limite de uso" / "precisa entrar na conta" viram avisos próprios.
- **Configurações → Automação do Flow**: `direto` (novo, padrão) ou `antigo` (a automação anterior, se precisar voltar).
- **🧪 Testar o Google Flow** (`/flow/teste`, link nas Configurações e em Contas Google):
  - navegador **visível ou oculto**;
  - **Teste completo**: imagem → vídeo só com texto (Elementos) → vídeo com Início e Fim (Frames);
  - **Gerar um**: tipo, modelo, proporção, quantidade, prompt, frames de Início/Fim e imagem de referência;
  - **💸 Sem gerar**: faz tudo até antes do "Iniciar geração" (não gasta crédito);
  - cada passo mostra ✅/❌, tempo e a foto da tela; se falhar, salva o diagnóstico em `flow_dados/diagnostico`.
- Testes: `toolkit/googleflow/test_flow_direto.py` roda contra um **Flow simulado** (`toolkit/googleflow/flow_simulado/`)
  montado com o HTML real.

---

## ✂️ Trecho longo demais vira pedaços (v84_73)

Com transcrição longa a IA às vezes "cansa" no fim e manda um trecho de 1–2 minutos com uma busca só (um clipe curto
repetido/esticado). Agora (`trechos_longos.py`):

- o prompt da 1ª IA diz que nenhum trecho passa de 2,5× o intervalo (mínimo 15 s), **até o fim do áudio**;
- se mesmo assim vier, a resposta já chega **dividida** em pedaços do tamanho do intervalo, cortados no começo das frases
  quando dá; o 1º pedaço fica com a busca/texto, os outros usam as buscas de reserva — e, com a 🤖 IA, cada um ganha a
  busca pela própria fala;
- em projetos já abertos: aviso ⚠ no painel do trecho longo com **✂️ Dividir em pedaços**, e o botão
  **✂️ Dividir trechos longos (N)** na barra da timeline (a mídia escolhida fica no 1º pedaço; os outros ganham prévia nova).
  YouTube, mídia do projeto e cenas (template) não são divididos.

## 🚫 Só os bancos e buscadores que você marcou (v84_72)

- A **reserva** (quando um banco não acha nada) vinha da prioridade das Configurações — por padrão TODOS os bancos —, então
  um vídeo só com Pexels caía em Magnific, VistaCreate… (que abrem navegador). Agora a reserva é só entre os bancos
  **marcados no vídeo**, na ordem de prioridade das Configurações.
- Os **buscadores de imagem** (Bing, Brave, Yandex, Startpage) rodavam sempre os 4 juntos, um navegador cada. Agora só os marcados.
- O 🤖 que acha os vídeos do YouTube lê as legendas **sem abrir janela** (só o botão 🎯 de um vídeo ainda tenta com o
  navegador visível quando o oculto falha).

## 📝 Projeto do Roteiro do YouTube no editor (v84_71)

No **Novo vídeo**, o seletor "📦 Projeto" agora também lista os projetos do **Roteiro do YouTube** (com roteiro pronto) —
ou use o botão **🎬 Criar o vídeo com este projeto** na página do roteiro. Com o projeto ligado:

- cada **[CENA n]** do roteiro é achada na narração deste vídeo (as palavras logo depois do marcador) e o prompt da 1ª IA
  recebe "neste ponto, YouTube, buscando X"; depois da resposta, o trecho de cada cena vira YouTube com a busca da cena;
- a cena que já tem **link + início/fim** escolhidos na página do roteiro é **baixada e cortada sozinha**; as outras ficam
  no painel 🎬 Vídeos do YouTube pro 🤖 achar o momento;
- o YouTube entra nos bancos do projeto sozinho, e os capítulos da descrição saem no tempo do vídeo final
  (`roteiro_no_editor.py`; o achador de frases no áudio virou `roteiros_yt.tempos_de_frases`).

## 🧭 Cada trecho na fonte certa + 🃏 cartão quando nada presta (v84_70)

Com a IA ligada, a etapa "buscas melhores" já dizia o tipo de cada trecho, mas isso era ignorado. Agora decide a fonte
(só entre os bancos ligados no projeto):

- **pessoa falando** (entrevista, discurso) e real → **YouTube** (o 🤖 do painel acha o momento);
- **pessoa, caso, lugar, objeto ou documento real e específico** → **foto real** (Bing/Brave/Startpage/Yandex, ou Wikipedia)
  — o banco de stock não tem isso e devolvia algo "parecido";
- pede imagem gerada → **Flow** (se ligado); **clima/ambiente** → banco de stock (sai do buscador de imagem);
- **ideia abstrata** → busca normal, mas o juiz fica **rigoroso** (só passa nota ≥ mínima).

**🃏 Sem imagem boa → cartão de texto**: quando o juiz reprova tudo (nota < 5, ou < mínima num trecho abstrato), o trecho
não usa mais "a menos pior" — vira um cartão: fundo escuro gerado no site + a frase do trecho (até 8 palavras, escrita pela
IA) num destaque de tela cheia da direção (ex.: a cartela do Dallas). Troque a mídia no editor e a frase sai junto.
Liga/desliga em 🤖 IA → "Sem imagem boa → cartão de texto".

## 🤖 A IA acha os vídeos do YouTube + 📑 capítulos do Roteiro do YouTube (v84_69)

- No painel **🎬 Vídeos do YouTube** (Estúdio, editor clássico e tela de prévias), o botão **🤖 A IA acha os vídeos**
  (ou **🤖 IA acha este** em cada item) faz, um item por vez, para os trechos e cortes sem vídeo:
  1. busca no YouTube (20 resultados) e a IA dá nota olhando as **capas**, títulos, canais e durações;
  2. lê a **transcrição** dos 3 mais prováveis e a IA acha o **momento** que a narração pede;
  3. não achou → a IA sugere **outra busca** (no máximo 3 buscas);
  4. achou → baixa e corta sozinho (completando a duração do trecho); não achou → marca ❌ "escolha à mão",
     deixa os resultados na ordem da nota e vai pro próximo. O log "o que a IA fez" mostra cada passo; ⏹ Parar interrompe.
  Usa os recursos “Ordenar os vídeos do YouTube” e “Achar o momento” da página 🤖 IA (`yt_agente.py`).
- **Roteiro do YouTube**: o .zip do Gerar voz leva o projeto, e ao montar o vídeo os capítulos vão pro tempo do vídeo
  final (com chamadas e cortes) — a página do roteiro ganhou “usar os tempos do VÍDEO FINAL”. O roteiro colado à mão no
  Gerador de voz também é reconhecido.

## 📑 Capítulos do YouTube no tempo do vídeo final (v84_68)

- Ao **montar** um vídeo de um 🕵️ modelo de vídeo, os capítulos são achados na narração do próprio vídeo e
  **deslocados pelas chamadas (inscreva-se/venda) e cortes** que entraram — a página do vídeo pronto mostra a
  descrição com os tempos certos (📋 copiar), e a descrição do modelo de vídeo também é atualizada.
- Ao **gerar a voz**, o roteiro de um modelo de vídeo **colado à mão** no Gerador de voz é reconhecido sozinho (antes só
  pelo botão "Gerar voz com este roteiro"): os capítulos vão pro tempo do áudio e o .zip leva o projeto.
- Gerar a voz de novo descarta os tempos do vídeo antigo.

## 📁 Suas mídias e 🖥 sites citados entram na edição da IA (v84_67)

Antes, o 🤖 Prompt de edição só mostrava as FOTOS da biblioteca e só pra usar dentro de quadros — a IA não tinha como pôr
um vídeo/foto que você enviou num trecho, e o quadro de página dependia da direção.

- O prompt lista **todas as mídias da biblioteca** (fotos e vídeos, inclusive as do 🕵️ modelo de vídeo e as capturas de
  página importadas), com **o que é** cada uma e onde já está; a IA responde `"midia": "bib:<id>"` no trecho e precisa usar
  todas pelo menos uma vez. Trecho com arquivo que você escolheu não é trocado.
- Na biblioteca do Estúdio cada arquivo ganhou um campo **“o que é?”** (“print do site X”, “foto do fulano”).
- **Site na tela**: quando a fala cita um site/página/notícia/post, a IA põe o vídeo da página (se você enviou) ou o quadro
  🖥 Página/print com o link (o print é tirado sozinho). Os quadros de prova (`pagina`, `post`) valem em **qualquer
  direção**. Links: as fontes do modelo de vídeo + o campo novo “🖥 Sites pra mostrar na tela” na aba 🤖 IA.
- Aplicar a resposta já salva o arquivo no trecho; **Desfazer** volta o arquivo de antes (só aceita caminho de dentro do projeto).

## 🕸 Direção e modelo "Exposição da internet" (estilo Dallas) (v84_66)

Tirado de 3 vídeos do canal Dallas (cortes, quadros, ritmo da narração e estrutura do roteiro):

- **Direção `sys_dallas`**: filtro com faixas de cinema 2,39, tarja de terminal (branco no preto) com a frase-chave,
  cartelas de terminal no preto nas viradas, cartela vermelha "NÍVEL 1/2/3", fotos flutuando com partículas, documentos,
  ficha de perfil e citações, cortes secos. Sem legenda queimada.
- **Extras** em `assets/darkplanner/extras/referencias_canais.json`: filtros `cinemascope_dallas`/`cinemascope_frio` e
  destaques `dallas_tarja`, `dallas_cartela`, `dallas_nivel` (com miniaturas na galeria).
- **`corFixa`** nos destaques dos extras: a caixa usa a cor do estilo (a tarja é sempre preta), sem herdar o acento da paleta.
- **Modelo 🕸 Exposição da internet** (Dossiês): formatos "Comunidade em NÍVEIS", "Expondo uma pessoa" e Shorts, a
  ~170 palavras/min, com regras de proteção (só fatos com fonte, sem identificar vítimas/menores, sem ensinar o crime,
  palavras sensíveis com símbolos só na tela, [CENSURAR] vira 🙈 no editor).

O estilo é copiado, a identidade do canal não (sem nome, logo, vinheta ou bordões).

## 🎙 Fila e histórico no Gerador de voz + 📁 estilos "Dossiê em colagem" (v84_65)

**Fila de áudios.** No 🎙️ Gerador de voz dá pra pedir vários áudios seguidos: cada pedido entra na **fila** e o botão
já fica livre pro próximo. Cada geração roda num processo próprio, que carrega o modelo na placa de vídeo, então:

- **🎛 Ao mesmo tempo → automático** (padrão): lê a VRAM pelo `nvidia-smi` e gera **2 juntos** quando cabe (Piper ~0,3 GB,
  Kokoro ~1 GB, XTTS e Chatterbox Turbo ~3,5 GB, Chatterbox ~5 GB por geração, usando no máximo 90% da placa). Se não
  couber, ou se não houver placa NVIDIA, gera **um depois do outro**.
- Também dá pra fixar **1, 2 ou 3** (vai pro `site_config.json`, `voz_simultaneos`).
- A caixa **🎙 Fila de geração** mostra o que está gerando e o que está esperando (com a posição). O que ainda não começou
  pode ser tirado da fila. A ordem é a de chegada.

**📜 Histórico de áudios gerados** (fim da página, fica em `outputs/vozes/historico.json` e sobrevive a reiniciar o site).
Mostra a data, o motor, a voz, o idioma, o começo do texto, as palavras, a duração e quanto tempo levou, com player,
⬇ WAV, ⬇ SRT e Apagar (apaga também os arquivos). Dá pra procurar pelo texto, pelo motor ou pela voz.

**📁 Vídeos de IA "Dossiê em colagem" virando estilo.** Vieram de 5 vídeos de true crime feitos por IA ("O Caso de Idaho",
shorts 9:16 de 2 a 3 min, em capítulos). Em 🎞️ Vídeos modelados entram dois estilos novos:

- **Dossiê em colagem de papel — true crime em capítulos**:
  - a cena tem fotos P&B recortadas com borda branca, jornal e relatório policial ao fundo, linha vermelha entre
    alfinetes, fita crepe e uma etiqueta de papel rasgado com 2 a 4 palavras;
  - a animação é stop-motion de recortes;
  - o roteiro tem "No capítulo anterior…", horários e endereços exatos, sem sensacionalismo, e termina com um gancho
    pro próximo capítulo;
  - regra: nunca pedir à IA o rosto realista de uma pessoa real; as fotos reais entram no editor.
- **Arquivo na mesa escura — abertura/teaser realista**: pastas, lupa, mapas e uma cidade de papel em miniatura numa
  mesa de madeira com luz de abajur. Serve para apresentar o canal ou abrir um caso.

Os dois abrem no Estúdio com a direção nova **"Dossiê de papel (colagem true crime)"**:

- cor sépia/creme com vermelho e câmera chegando devagar;
- peças que deslizam e assentam, e viradas de página;
- destaques de recorte, carimbo e máquina de escrever;
- quadros editoriais de recortes, mural, bilhetes e linha do tempo.

O que não dá para copiar: a IA de vídeo que fez os originais monta cada colagem com texto já "impresso" nela. O Flow
consegue escrever etiquetas curtas, mas pode errar letras. Quando errar, apague a etiqueta da cena e use um destaque
de recorte/carimbo no editor.

## 🧹 Espaço em disco (v84_64)

Link "🧹 Espaço em disco" no topo. Mostra quanto o site ocupa no total (e quanto sobra no disco) e cada categoria com o
tamanho e o número de itens: 🎬 Projetos de vídeo (com o vídeo final), 🧽 Caches dos projetos, 📤 Outras saídas
(vozes, capturas, cortes, downloads), uploads, Roteiro para Áudio, Conversas, Roteiro do YouTube, Vídeo de venda,
Modelos de vídeo, Vídeos modelados, Análises de canal, Niche Miner, cache da IA, downloads temporários, lixo do Python,
modelos/perfis de voz e a sessão do Flow.

- Clique numa categoria: lista cada item (maior primeiro) com tamanho e data. Apague um, marque vários, ou apague a
  categoria inteira.
- **🧽 Caches dos projetos** apaga só o que o site refaz sozinho (clipes pré-baixados, prévias guardadas, clipes prontos,
  arquivos intermediários da montagem): o projeto continua na Galeria e abrindo normal.
- **Apagar tudo de todas as categorias**: precisa digitar APAGAR. Não mexe nas **protegidas** (modelos e perfis de voz,
  sessão da conta Google do Flow) — essas só item por item.
- Projeto em andamento (transcrevendo, montando…) nunca é apagado. Apagar um projeto também tira ele da Galeria.

## 🔒 Subir pro GitHub sem dados pessoais (v84_63)

O `.gitignore` deixa de fora tudo que é seu ou que o site gerou: chaves (`site_config.json`, `ia_config.json`, `.env`),
cookies e sessões de navegador (inclusive a conta Google do Flow), bancos de dados, projetos, vídeos, áudios, vozes,
transcrições e análises (`jobs/`, `outputs/`, `dossies/`, `analises_canal/`, `niche_miner/data/`…).

Antes de cada envio, rode o **`verificar_antes_de_subir.py`**:

```
git add -A
python verificar_antes_de_subir.py            # confere o que vai no commit
python verificar_antes_de_subir.py --corrigir # tira do commit o que é pessoal (o arquivo fica no PC)
python verificar_antes_de_subir.py --instalar # passa a conferir sozinho em todo git commit
```

Ele acusa arquivos pessoais, chaves de API (Anthropic, Google, GitHub, OpenAI, AWS…), cookies de sessão do
YouTube/Google, o seu e-mail (o do `git config user.email`) dentro dos arquivos, e arquivos grandes demais pro
GitHub. Nunca mostra a chave inteira. **Se uma chave já subiu alguma vez, troque a chave no site do serviço**: apagar
do git não basta.

## 📊 Analisador de canal + ⛏ Niche Miner (v84_62)

**📊 Analisador de canal** (link no topo). Você cola o link de um canal (`youtube.com/@nome` ou só `@nome`) e o site:

1. lê o cabeçalho (inscritos, nº de vídeos, views totais, país) e os **20 vídeos mais recentes** e os **20 mais
   populares**, com miniatura, título, duração, views e data. Usa o mesmo leitor de página do Niche Miner
   (`niche_miner/yt_scraper.py`, Chromium invisível); se ele falhar, o yt-dlp lê a lista;
2. pega pelo yt-dlp, quando dá, a data exata, os likes, os comentários, as tags e os capítulos de cada vídeo;
3. pega a **transcrição** de cada vídeo direto do YouTube (youtube-transcript-api → painel "Mostrar transcrição"),
   com o gancho (1º minuto) e as palavras por minuto. Dá para desligar, porque é a parte mais lenta;
4. calcula as métricas: mediana de views, tração, fator outlier, views/dia, vídeos por semana, duração, padrões de
   título (mediana com × sem) e views por faixa de duração;
5. manda tudo para a 🤖 IA (recurso "📊 Analisador de canal"), **com as miniaturas como imagem**. A IA devolve o
   resumo, o que o canal faz bem e o que pode melhorar, as fórmulas de título que funcionam e as que não, o estilo das
   capas e uma "receita" de capa, os tipos de vídeo e quais performam melhor, os padrões de gancho e roteiro, os
   melhores e piores vídeos (marcados em verde e vermelho na grade) e **10 sugestões de vídeos** que o canal entregaria
   bem;
6. cada sugestão vira um **🕵️ Modelo de vídeo** com um clique (o tema, o gancho e a ideia de capa já vão juntos).

Sem a IA ligada, a coleta e as métricas funcionam igual, e a análise sai como um prompt para colar numa IA de chat
(com os links das miniaturas). Você cola o JSON de volta. As análises ficam em `analises_canal/`, fora do GitHub.

**⛏ Niche Miner** (link no topo). É o app do zip `niche_miner_v9`, inteiro em `niche_miner/`. Tem mineração de nicho
por termos, mineração por recomendações, Método Dark, Analisar canal, Ideias virais, API do YouTube e Biblioteca. A aba
liga o app sozinha na porta 8843 (`"niche_miner_porta"` no `site_config.json` muda a porta) e mostra o app dentro do
site. Os dados dele ficam em `niche_miner/data/`, também fora do GitHub. Os testes próprios dele continuam em
`niche_miner/tests/` (rode com `niche_miner\run_tests.bat`).

**🕳 Estilo Mistere com mais 2 vídeos.** "A CIA encontrou um fantasma no Brasil" e "Tutorial de como deixar alguém
esquizofrênico" confirmaram o ritmo (mediana de 2,75 s e 1,96 s por plano) e trouxeram mais coisas:

- **Dois formatos novos no modelo "🕳 Rabbit holes bizarros":**
  - 📂 *Caso de arquivo oficial*: documento → personagens → partes com datas → 3 explicações → opinião;
  - 🎓 *"Tutorial" irônico*: lições numeradas com o método real dos documentos. A regra proíbe passo a passo aplicável
    hoje.
- **A direção agora também usa:**
  - transições de luz de película no arquivo;
  - destaques de nome gigante, carimbo CONFIDENCIAL, linha do tempo e capítulo;
  - mais quadros de página de documento.

## 🕳 Modelo + direção no estilo Mistere (v84_61)

Feito analisando um vídeo do canal [Mistere](https://www.youtube.com/@Misterecore) ("Mistérios e Rabbit Holes Bizarros da
Internet", 30 min). Medido no vídeo: 480 cortes (plano médio 3,8 s, mediana 2,6 s) e narração rápida (~175 palavras/min).
A estrutura é de compilado: um teaser de 10 s ("Tu sabia que…"), depois 5 casos independentes de 4 a 10 min, cada um
aberto por uma cartela de título, sem ponte entre eles, e no fim uma chamada curta. Na imagem: vinheta forte, cor fria e
dessaturada, estática/glitch de TV nas viradas, números e anos gigantes, palavras em máquina de escrever, fotos de
arquivo com tarja e sem legenda queimada.

- **🕵️ Modelos de vídeo → "🕳 Rabbit holes bizarros"**, com 3 formatos: compilado de casos, caso único e Shorts. Calcula o
  roteiro a 170 palavras/min, usa as regras de tom do canal ("tu sabia", frases curtas, ironia seca nunca às custas das
  vítimas), põe números em algarismos (viram texto na tela) e lê citações com "abre aspas… fecha aspas".
- **🎬 Direção "Rabbit hole sombrio (estilo Mistere)"** no Estúdio: ritmo dinâmico, filtro frio com vinheta, overlays
  de vinheta/grão/VHS, maioria corte seco com estática e glitch nas viradas, destaques de números grandes + máquina de
  escrever + título serifado, e quadros editoriais de número, nome, ficha e recortes. Sem legenda queimada. Sem o pacote
  de extras, ela usa só os itens da fábrica.
- Vídeo feito a partir de um projeto desse modelo já sai com essa direção aplicada (se a IA não escolher outra).
- Copia só o **estilo**: nada de logo, vinheta, nome ou bordões do canal.

**💾 Projeto reaberto não baixa tudo de novo.** As prévias que a telinha do Estúdio mostra (vídeos e miniaturas) ficam
guardadas em `jobs/<id>/previas_cache/` junto com os clipes da montagem (`prebaixados/`) e os trechos prontos
(`clips_prontos/`). Ao reabrir o projeto, mesmo depois de reiniciar o site, tudo carrega do PC.

## ⬇ Clipes baixando enquanto você edita (v84_59)

**🔎 Conferência antes de montar.** Quando você clica em 🎬 Montar vídeo, o site salva e confere **todos os trechos de uma vez**,
antes de começar. Ele procura arquivos que sumiram ou estão corrompidos, links escolhidos que não baixam (eles já são
baixados nessa hora), bancos que não baixam pelo link, foto sem chave do banco, trecho sem busca e sem mídia, cena
(template) que não existe, trecho com duração zero, narração ausente, ffmpeg ausente e pouco espaço em disco. A lista
aparece na janela de montar: ❌ é o que faria a montagem falhar, ⚠ é só aviso. Clique num item para ir ao trecho; os
trechos com ❌ ficam marcados em vermelho na timeline. Dá para montar mesmo assim.

**♻ Montar de novo não recomeça do zero.** Cada trecho pronto (baixado, cortado e com efeito) fica guardado em
`jobs/<id>/clips_prontos/`. Se a montagem falhar num trecho e você montar de novo, os trechos que não mudaram saem dali
na hora: só o que falhou, ou o que você mudou, é refeito. Quando falha, a mensagem lista **todos** os trechos que
falharam, não só o primeiro. Para desligar: `"reaproveitar_clipes_prontos": false`.

Antes, a montagem ("4. Montando o vídeo") baixava clipe por clipe e só então juntava — em vídeos longos ficava
muito tempo em "processando 62/151". Agora, assim que as prévias ficam prontas, o site já vai **baixando em
segundo plano** os clipes que a montagem vai usar (o clipe que a telinha do Estúdio mostra, links colados,
resultados escolhidos no 🔍 Buscar e os clipes curtos extras) para `jobs/<id>/prebaixados/`.

- No Estúdio, ao lado de "tudo salvo", aparece **⬇ baixando mídias X/N** e depois **⬇ mídias prontas**.
- Trocou um clipe ou uma busca e salvou: só o que mudou baixa; o que já estava baixado é reaproveitado.
- Na montagem, o clipe já baixado sai direto do disco — sobra só cortar/normalizar e juntar. A tela da montagem
  mostra quantos clipes já vieram prontos do editor.
- Um link que falhar no pré-download não trava nada: a montagem tenta de novo (e, se for da prévia, busca outro).
- Para desligar: `"prebaixar_no_editor": false` no `site_config.json`. Quantos ao mesmo tempo: `assembly_fetch_concurrency`.
- Fotos dos buscadores por navegador (Bing/Brave/Yandex/Startpage) já vinham da prévia; as demais buscas novas
  (trecho sem prévia, foto de banco) continuam sendo feitas na montagem.

## 🤖 IA nas buscas, no editor e nos Modelos de vídeo — Claude Haiku 5.5 (v84_53)

- Página nova **🤖 IA nas buscas e modelos** (`/ia`, nos links do topo e em ⚙️ Configurações): liga a IA, chave, o que
  ela faz (cada recurso liga/desliga), nota mínima, candidatos e limite de gasto, com o gasto por recurso.
- Com ela ligada: **ficha do vídeo + buscas melhores**, **juiz visual** que escolhe a melhor miniatura (não a 1ª) e
  reescreve a busca quando nada presta, **nota no Buscar** do editor, **YouTube** com 20 resultados ordenados +
  "Outros vídeos" e **🎯 momento certo pela legenda**, **Wikipedia** com a foto principal e sem bandeira/mapa/brasão,
  **Modelos de vídeo**: ficha de cada imagem, duplicadas, PDF escaneado, dossiê condensado e conferência das marcas
  [I3]; **Vídeo de venda**: ficha das fotos do produto; **🤖 Fazer com a IA** no prompt de edição.
- **Desligada, sem chave ou sem crédito, tudo funciona como antes** (a IA se desliga sozinha quando a API recusa).
- **✂️ Prompt de edição em partes (opcional)**: vídeo longo vira N prompts (ex.: 5 × 12 min); cole cada resposta e
  confira tudo junto. A **parte 1 decide a direção de arte** (cores, fontes, estilos, transições…) e as partes 2…N
  recebem isso no prompt e seguem igual (ficam 🔒 até a parte 1 ter resposta).
- Guia: `docs/guia/19-ia-nas-buscas-e-modelos.md`.

## 🏷 Títulos nas fórmulas do Kit + 📜 transcrição do YouTube pelo painel (v84_52)

- **Títulos**: todo prompt que pede título (Roteiros do YouTube, Dossiês, Vendas, Modelados) manda a IA usar as 20
  fórmulas do *Kit Iniciante YouTube* (cap. 05): até ~60 caracteres, palavra principal no começo, promessa que o vídeo
  cumpre, cada título numa fórmula diferente, nunca mentir. As fórmulas ficam em `metodo_roteiro.FORMULAS_TITULO`.
- **Transcrição do YouTube**: o 1º caminho agora é o do projeto *transcript-youtube-video*: abre o vídeo num navegador,
  clica em "…mais" → "Mostrar transcrição" e lê o painel (o layout novo do YouTube, `transcript-segment-view-model`,
  e o antigo). Se não der escondido, tenta com a janela visível; só depois vêm o yt-dlp e os outros caminhos.
- **Sons dos quadros editoriais**: saíram os sons tirados dos vídeos de referência. Agora os quadros usam os sons da
  biblioteca do site (whoosh, folha seca, digitação, tecla, câmera, riser, impacto…) — a tabela fica em
  `dp_editorial.SONS`.

## 🔊 Sons dos quadros editoriais + 🎨 extras de referência nas Direções (v84_51)

- Cada quadro editorial toca o seu som sozinho, alinhado com a animação. No painel do quadro: **Som = auto | nenhum**.
  Na aba 🔊 Áudios: ☑ *Sons dos quadros editoriais*. A prévia do Estúdio toca junto. (Na v84_52 os sons passaram a ser
  os da biblioteca.)
- **450 extras de referência** (filmes, séries e documentários) em `assets/darkplanner/extras/referencias_*.json`,
  com miniaturas. O campo `"direcoes"` de cada item agora **vale**: o item entra nas Direções do sistema que ele
  cita (o que já existia fica com pelo menos metade do peso).
- **Editoriais nas Direções**: cada Direção diz se usa quadros editoriais, a densidade (1 a cada 60/40/25/15 s) e
  quais tipos. A IA segue isso no prompt. No editor de Direção há o eixo novo **Editoriais**.

## 🗞 Quadros editoriais — o estilo documentário dos vídeos de referência (v84_50)

14 quadros recriados quadro a quadro a partir dos vídeos que você mandou (papel bege com vinheta, serifada,
versalete espaçado, acento vermelho), numa faixa nova **Editorial** do Estúdio (aba **🗞 Editorial**):
ficha de pessoa (linha do rosto até o cartão), nome do entrevistado, post sobre o vídeo desfocado com tradução,
título com o vídeo dentro das letras, terminal digitando, print de página em 3D (de imagem, link ou só da manchete),
linha do tempo deslizante, grade de pontos com contadores, recortes caindo na mesa + número, mural de fotos com
citações, foto/vídeo + bilhetes, reescrita (riscar e refazer), número grande contando e texto que explode em tinta.
Painel montado sozinho pelos campos, prévia = o mesmo desenho do vídeo final, IA pode mandar `"editoriais"` no
prompt de edição. Montagem por pedaços (sem estourar memória em 1080p). Guia: `docs/guia/18-quadros-editoriais.md`.

## 📘 Guia: como criar efeitos, transições, destaques, textos, legendas… + ➕ extras sem programar (v84_49)

- **Guia completo** em `docs/guia/` (17 capítulos) e no site: rodapé → **📘 Guia** (`/guia`). Cada capítulo diz o que
  dá pra criar **sem programar** e, quando precisa de código, **onde mexer** (ffmpeg + prévia do Estúdio) e como testar.
- **➕ Extras** (`assets/darkplanner/extras/*.json`, ver `dp_extras.py`): transições (`xfade` nativa, fórmula `expr` ou
  `igual_a`), efeitos (`camera`, `filtro` do ffmpeg ou `igual_a`), entradas/saídas (gesto existente com outra
  duração), filtros (cadeia + CSS da prévia), destaques (`base` + o que muda: fonte, animação, fundo, som…), cenas
  (`base`, `arranjo` ou `janelas` próprias), paletas, sons e fontes. Entram nas galerias, no prompt da IA, nas
  Direções e na montagem — e atualizar o site não apaga. Exemplos prontos em `docs/guia/exemplos/`.
- **`python dp_guia.py`**: `verificar` (erros dos extras + o que falta), `miniaturas` (gera só as que faltam,
  `--refazer id`), `listar <tipo>` (ids pra `base`/`igual_a`), `som arquivo.mp3` (converte, mede o pico e registra),
  `fonte arquivo.ttf --chave x` (renomeia a família pra "DP …" e registra; precisa de `pip install fonttools`).
- Pequenas melhorias que vieram junto: prévia no monitor das transições `dp:` que são nativas (antes tudo era fade),
  `coreografia.entrada` aceita direto o nome da família de animação (mira, linha_tempo, versus, grade, pino caíam
  no fade), `cena.fundo` do estilo aceita os ids de fundo do site e `audio.assets` aceita ids de som do site.

## 🌐 Vídeo de venda com Gumroad / landing page (v84_48)

- O link do produto aceita **qualquer página de venda**, não só Amazon: Gumroad, landing page, Hotmart/Kiwify, loja
  Shopify… (`vendas.ler_pagina`). Pega nome, preço (dados do Gumroad, JSON-LD, meta de preço ou o preço escrito no texto),
  tópicos, descrição, avaliações, as fotos (com a legenda que estava na página) e o **conteúdo inteiro da página** por
  seções — fica no campo "📄 Conteúdo da página de venda" (dá pra editar ou colar na mão).
- No prompt, a IA recebe esse conteúdo e separa o que vende: promessa, pra quem é, benefícios, o que tem dentro, bônus,
  garantia, provas/depoimentos (só os que estão na página) e FAQ. Prazo/vagas da página aparecem como "segundo a página".
- Página que pede login ou bloqueia robôs: **📄 Enviar página salva (.html)** (no navegador: Ctrl+S).
- Uma página adicionada como **material** (link) também tem o conteúdo extraído e levado pro prompt.

## ⚡ Estratégia de Shorts + estrutura de referência (v84_46)

- Roteiro **curto** (Shorts/Reels/TikTok — Modelos de vídeo no formato curto, Roteiro do YouTube "mais curto", Vídeos
  modelados até 60 s, e Vídeo de venda até 60 s — Short = no máximo 60 s, ~130-160 palavras) ganha a parte de Shorts do `metodo_roteiro.py`: **gancho com o espectador
  dentro da história** ("Você é… e tem um problema") e algo em jogo · tema de dopamina rápida (curiosidade, "parece burrice
  até explicarem") · solução revelada em passos · **final com recompensa** (a revelação, não só uma piada; se der, em loop)
  · simples · frases curtas (legenda curta, cena nova a cada 1-2 s) · narração **transformadora** (nunca só descrever cena
  de outro — conteúdo reutilizado é desmonetizado) · meta: taxa de visualização > 80% e retenção > 90% · com a sua cara.
  As dicas de edição (efeito sonoro + algo chamativo no 1º segundo, legendas de 1-3 palavras…) vão no plano.
- **📐 Estrutura de referência** (Vídeo de venda e Modelos de vídeo): cole a transcrição de um vídeo que viralizou — a IA
  copia a ESTRUTURA (gancho, ordem das revelações, ritmo, final) com o seu tema, sem copiar frases.

## 🧭 Método de roteiro em todo prompt de roteiro (v84_45)

`metodo_roteiro.py` entra em TODO prompt que escreve ou reescreve roteiro: Roteiro do YouTube (1º passo e, quando
reescreve, o 2º), 🛒 Vídeo de venda, 🕵️ Modelos de vídeo e 🎞️ Vídeos modelados. A IA segue:
objetivo comum com o espectador · problema de superfície + **problema profundo** (plantado cedo, revelado no fim) ·
entregar a promessa do título · público certo · a lacuna que as fontes não explicam · começo e fim claros
(transformação) · **jornada do herói** adaptada (mini-jornada na venda e nos Shorts) · complexidade crescente ·
"mostrar sem contar" (laços abertos que se fecham) · **"mas / portanto"** · ritmo com frases de tamanhos diferentes ·
autocrítica do esboço antes da versão final · **sem manipulação** (nada de isca de raiva ou promessa falsa).
A IA devolve também um **"plano"** (objetivo, problemas, público, começo→fim, jornada, laços abertos, notas de edição),
que aparece em **🧭 Plano do roteiro** na página. Notas de edição nunca vão no texto narrado.

## 📄 Fontes por arquivo, filtro de conteúdo pessoal, marcas de like/venda e produto sugerido (v84_44)

Nos 🕵️ Modelos de vídeo:
- **Fontes por arquivo**: TXT/MD, **PDF** (com intervalo de páginas, ex.: `10-45, 50` — pra livros grandes), **EPUB**,
  **DOCX**, SRT/VTT (sem os tempos), HTML, RTF. Até 150 mil caracteres por arquivo. Precisa do `pypdf` (no requirements).
- **🙅 Tirar experiências pessoais / citações a outros vídeos / detalhes muito pessoais** das fontes (marcado por padrão).
  No Vídeo de venda virou o filtro "Sem experiências pessoais / citações a outros vídeos".
- **📣 [[INSCREVA]] e [[VENDA]] nos pontos mais oportunos** (marcado por padrão; não nos Shorts) — vão pro Gerar voz como
  as pausas dos vídeos de like e de venda. **✏️ Editar roteiro**: mude as marcas de lugar ou corrija o texto; a voz, os
  momentos das imagens e os capítulos são recalculados.
- **🛒 A IA sugere um produto** adequado ao tema (opcional): aparece separado (nome, por quê, chamada) e **não entra no
  roteiro**; botão pra criar um projeto de 🛒 Vídeo de venda com ele + busca na Amazon.

## 🌐 Idioma de saída no Vídeo de venda e nos Modelos de vídeo (v84_42)

- **🌐 Idioma de saída** (em "Como vender" / "Tema e modelo", e repetido do lado do 📝 Gerar prompt): o prompt manda a
  IA escrever TUDO nesse idioma — roteiro, títulos, descrição, capítulos, tags, CTA, textos na tela — mesmo que a
  página do produto ou as matérias estejam em outro (traduzindo os fatos; nomes próprios ficam).
- O aviso de afiliado da Amazon sai no idioma escolhido; o 🎙️ Gerar voz já abre com o idioma do projeto.
- Saída em **inglês**: o prompt também pede as **tags de voz do Chatterbox Turbo** no roteiro (`[chuckle]`, `[sigh]`,
  `[dramatic]`, `[whispering]`…, `roteiros_yt.regra_tags_turbo`). Elas ficam no texto que vai pro Gerar voz.

## 🎬 6 modelos novos + vídeos transcritos que a IA corta (v84_41)

- **Modelos de vídeo** novos (além do True Crime), cada um com formatos e regras próprias: 📜 História, 👤 Biografias,
  💼 Negócios e marcas, 🌋 Desastres e tragédias, 👽 Mistérios e inexplicáveis, 🔬 Ciência e curiosidades.
- **Vídeos dos projetos** (🛒 venda e 🕵️ modelos — do PC, de links ou das matérias) são **transcritos com os tempos**
  em segundo plano (`midia_transcricao.py`, `<vídeo>.transcricao.json`). A transcrição aparece no cartão e vai no
  prompt do roteiro e no do editor.
- A IA decide como cada vídeo entra:
  - **com o áudio original** (a narração pausa, o vídeo final fica mais longo): no roteiro `[M3 0:12-0:25 áudio]`;
    no editor, em `cutaway_suggestions` com `"midia"`, `"inicio"`, `"fim"` — o site recorta o pedaço e o corte já
    sai resolvido (não vai pra busca do YouTube);
  - **sem o som, sob a narração**: no roteiro `[M3 0:12-0:25]`; no editor, `"query": "M3@12-25"` — o site recorta
    esse pedaço (mudo) e usa no trecho.

## 🕵️ Modelos de vídeo — começando pelo True Crime (v84_40)

Aba nova **🕵️ Modelos de vídeo** (`dossies.py`, `dossies_rotas.py`, projetos em `dossies/`):

1. **Tema e modelo** — modelo (True Crime), formato (📁 caso completo, ❓ mistério não resolvido, ⚡ Shorts,
   🔢 lista), minutos, idioma, tom, pedido extra e um roteiro/anotações seus (opcional).
2. **Fontes** — links de matérias de QUALQUER site (vários de uma vez). Em segundo plano o sistema salva título,
   linha fina, autor, data, subtítulos e o texto inteiro, e **baixa todas as imagens** da matéria com a legenda
   (figcaption/alt) e a OG; ícones e logos pequenos ficam de fora. Cada imagem vira um material `I1, I2…` ligado à
   fonte `F1…`.
3. **Materiais** — fotos/vídeos do PC (descrição obrigatória), links (OG) e textos (com "o que é"). Filtro por
   fonte e apagar várias de uma vez.
4. **Prompt → JSON** — estrutura do formato + regras do modelo (só fatos das fontes, presunção de inocência,
   respeito às vítimas, sem detalhe gráfico, linguagem amigável à monetização, sem nome de menores) + o texto de
   todas as fontes + a lista de imagens. A IA devolve títulos, ideias, descrição do caso, capítulos, o roteiro com
   `[I3]` onde cada imagem entra, tags, fontes usadas e o que conferir. A descrição sai pronta: caso + `0:00`
   capítulos + lista de fontes.
5. **🎙️ Gerar voz** (`/gerar-voz?dossie=ID`) — os capítulos ganham o **tempo real do áudio**; o `.zip` leva o
   projeto → **Novo vídeo** já escolhe (seletor 📦 junta 🕵️ modelos e 🛒 vendas). O prompt do editor recebe as
   imagens do caso; trechos com `"provider": "material"` + `"query": "I4"` usam o arquivo; as imagens também ficam
   na biblioteca do Estúdio.

Vídeo de venda: nova opção **💚 comprar pelo link ajuda o criador?** (fala da comissão sem custo a mais, ou não fala).

## 🛒 Vídeo de venda (v84_39)

Aba nova **🛒 Vídeo de venda** (`vendas.py`, `vendas_rotas.py`, projetos em `vendas/`):

1. **Produto** — link da Amazon (também `amzn.to`): título, preço, tópicos, descrição, avaliação e fotos (as fotos viram
   materiais). Se a Amazon pedir captcha, tenta com o Chromium do Playwright; se ainda assim bloquear, preencha na mão.
2. **Materiais** — do PC (foto/vídeo, **descrição obrigatória**), de link (página → OG: título, descrição e imagem
   baixada; foto/vídeo direto → baixado) ou texto (com "o que é"). IDs M1, M2… e T1… Em cada um: usar a OG, a
   descrição ou as duas.
3. **Como vender** — técnicas (benefícios, dor→solução, percepção de valor, ancoragem, urgência, escassez, prova
   social, autoridade, demonstração, história, objeções, garantia, comparação, bônus, curiosidade, CTA forte), tom,
   duração, idioma, formato, pago/gratuito, onde está o link, preço (falar/só na tela/não citar), oferta real,
   público, filtros (não parecer propaganda paga, não prometer resultado, sem pressão, sem concorrentes, aviso de
   afiliado) e palavras proibidas. A IA é proibida de inventar dados, avaliações ou promoções.
4. **Prompt → JSON** — roteiro narrado com marcas `[M2]` onde cada mídia entra, momentos, CTA, descrição (com o
   link no `{LINK}`), títulos e hashtags.
5. **🎙️ Gerar voz** (`/gerar-voz?venda=ID`, sem as marcas) → o `.zip` leva o projeto no `info.json` →
   **Novo vídeo** já escolhe o projeto (ou escolha no seletor 🛒). O prompt do editor ganha o bloco das mídias do
   produto; trechos com `"provider": "produto"` + `"query": "M2"` usam o arquivo do projeto (ID que não existe cai
   pros bancos marcados). As mídias também entram na biblioteca do Estúdio. Depois, a edição com IA do Estúdio é a
   de sempre.

Também: as fontes online do Anime Pexels não entram mais como reserva de trecho de banco de estoque.

## 🌐 Anime Pexels online — duas fontes novas com chave de API (v84_38)

- Fontes novas **animepexels_online** e **moviepexels_online**: o mesmo Anime Pexels em modo servidor
  (padrão `http://84.247.133.185`). Não substituem as locais — são alternativas; dá pra marcar junto.
- Tudo das locais vale nelas: obra e personagem/ator (várias com " | "), lista de personagens no prompt,
  📋 copiar a lista, prompt dedicado quando é a única fonte, pesos da busca, Estúdio, clipes curtos.
- **Chave de API**: ao marcar uma fonte online, aparece a caixa **🌐🔑** com a chave e o endereço
  (💾 Salvar / 🔌 Testar). Uma chave só pras duas. Fica no `site_config.json` (no `.gitignore`); a página
  nunca recebe a chave inteira de volta. Também em Configurações.
- A chave vai no header `Authorization: Bearer` e, nos vídeos/miniaturas (que o navegador abre sem header),
  em `?api_key=`. Erros 401/403/429 do servidor viram mensagens claras (chave errada, sem permissão de
  ler o catálogo, limite por minuto).
- Código: `acervos.py` (qual fonte é local/online/filmes e o cliente certo), `AnimePexelsOnlineClient` /
  `MoviePexelsOnlineClient` no `toolkit/animepexels/animepexels_client.py`.

## 📣 Uma chamada por tipo + marcas de cena fora da voz (v84_36)

- Várias [[VENDA]] / [[INSCREVA]]: o vídeo padrão entra **só na 1ª marca de cada tipo**; as outras ficam
  sem vídeo (narração normal) até você ligar na aba ✂️ Cortes. Enviar um vídeo com "usar como padrão"
  também não espalha mais pelas outras marcas.
- Gerar voz: botão **🧹 Tirar marcas de cena** ([CENA 3], [Cena 2: …], [[SCENE 4]], (CENA 5)). Mesmo sem
  clicar, o site tira essas marcas antes de narrar (`chamadas.tirar_marcas_de_cena`). Tags de voz e
  [[VENDA]]/[[INSCREVA]] ficam.

## 🟥 Selo/cartão com caixa: texto sumia em cor escura (v84_35)

- Telinha: o texto em cima da caixa (Selo de ano, Selo de canto, Cartão de dado, Slab, Marca) era sempre #111 —
  com a cor do projeto escura (ex.: vermelho-escuro) o "1979" ficava invisível, só a caixa aparecia.
  Agora `sobreCor()` escolhe branco ou escuro pela luminância da caixa (mesma regra do vídeo: > 140).
- Vídeo exportado: na máquina de escrever / letra por letra, a palavra em ÊNFASE era pintada da cor da caixa
  (sumia). Dentro de caixa a ênfase agora é sublinhado — na telinha e no vídeo.

## 📋 Copiar todas as obras / personagens do acervo pra uma IA (v84_34)

No bloco 🎌 Anime Pexels / 🎬 Filmes e Séries Pexels: **📋 Copiar a lista inteira**.
- **Copiar personagens**: das obras escolhidas (ou, sem nenhuma, do acervo inteiro), agrupados por obra.
- **Copiar animes / filmes**: todas as obras do acervo, com gêneros.
- Junto vai um pedido pra IA (opcional): quais são vilões, heróis, classificar todos, ideias de vídeo, ou um escrito por você.
- Rota: `/biblioteca-local/<prov>/copiar?o=obras|personagens&obra=A | B&pedido=viloes|herois|classificar|temas|texto`.

## 🧩 JSON colado da IA é consertado sozinho (v84_33)

Novo `json_ia.py`, usado em todo lugar que recebe a resposta colada (prompt principal, revisão de buscas,
edição, Roteiro do YouTube, modelados, termos de busca, "colar JSON" da página inicial). Se o `json.loads`
falhar, ele conserta o que o botão copiar do ChatGPT/Gemini estraga:
- ```json … ```, texto antes/depois, "json" / "Copiar código" grudados;
- tudo numa linha ou quebra de linha de verdade dentro do texto; TAB;
- barras do markdown (`\[\[VENDA\]\]`, `\_`, `\*`), aspas curvas “ ”, espaço invisível;
- aspas sem escape dentro do texto, vírgula sobrando/faltando, comentários, chave sem aspas, 'aspas simples', True/None;
- link virado markdown `[https://x](https://x)`.
Resposta CORTADA no fim não é aceita pela metade: avisa pra pedir pra IA continuar.
(Se o pacote opcional `json_repair` estiver instalado, ele é a última tentativa.)

## 🕘 Histórico das opções do roteiro (v84_32)

- "O que fazer com o roteiro": o que você marcou (opções, idioma, marcas, pedido extra) fica guardado em
  `roteiros_yt/opcoes_usadas.json`. Projeto novo já abre marcado igual à última vez.
- Menu **🕘 Usar de novo uma combinação anterior** com as últimas 12 combinações diferentes (um clique marca tudo);
  **🗑 limpar histórico** apaga a lista.
- O 1º passo também lembra o modelo de prompt, o idioma do roteiro e as caixas 🙅 / 📣.

## 🙅 Roteiro sem experiências pessoais nem citações a outros vídeos (v84_31)

- 1º passo (reescrever o roteiro): caixa **🙅 Tirar do roteiro experiências pessoais…** (marcada por padrão).
  A IA remove "como falei no vídeo passado", "no meu vídeo sobre X", histórias de quem gravou
  ("quando eu era criança", "aconteceu comigo"), menções ao canal, inscritos, lives e patrocinadores.
  Se a ideia for importante, ela reescreve de forma neutra; o que saiu aparece em "✂️ O que a IA tirou/trocou".
- 2º passo: a mesma coisa como opção **🙅 Tirar experiências pessoais e citações a outros vídeos** (marcada por padrão).

## 🎙️ Capítulos com o tempo real do áudio do TTS (v84_30)

- Na página do roteiro, o botão **🎙️ Gerar voz com este roteiro** leva o roteiro junto
  (`roteiro_id`). Quando a voz termina, o site usa as palavras do Whisper pra achar onde
  cada capítulo começa DE VERDADE no áudio e grava em `capitulos[k].segundos_audio`.
- O resultado do Gerar voz mostra **📝 Capítulos com o tempo real deste áudio** (com botão copiar).
- Na página do roteiro, a caixa **usar os tempos REAIS do áudio** (marcada por padrão) troca a
  estimativa por palavras/minuto pelos tempos medidos. Sem legenda, usa a duração do áudio.
- O primeiro capítulo é sempre 0:00 e há pelo menos 10 s entre capítulos (regra do YouTube).
- Atenção: no vídeo final, clipes de [[VENDA]]/[[INSCREVA]] com vídeo próprio empurram os tempos seguintes.

## 📝 Roteiro do YouTube: descrição com capítulos (timestamps) + título traduzido + títulos alternativos (v84_29)

- O título do vídeo original é guardado na transcrição. Se o yt-dlp estiver bloqueado, vem pelo oEmbed público do YouTube, que quase nunca é bloqueado. Ele vai junto no prompt do passo 3.
- Nova opção no passo 3: **📝 Descrição com capítulos (timestamps) + títulos**. A IA devolve:
  - a **descrição** pro YouTube (2-3 parágrafos + hashtags);
  - os **capítulos** (5 a 12), cada um com o título e as primeiras palavras exatas de onde ele começa no roteiro;
  - o **título original** — traduzido, se "🌐 Traduzir" estiver marcado;
  - **5 títulos alternativos**, no mesmo idioma.
- No resultado (passo 4), o site acha onde cada capítulo começa no roteiro e calcula o tempo pela fala, a 150 palavras/min. O 1º capítulo é sempre 0:00, como o YouTube exige. Dá pra mudar as palavras por minuto ou pôr a **duração real do áudio** depois de gerar a voz: os tempos se recalculam na hora. Botões: **📋 Copiar descrição** (descrição + "0:00 Capítulo…"), 📋 em cada título e **⬇ títulos + descrição (.txt)**.

## ⚡ Montagem mais rápida (v84_28)

- **Placa de vídeo**: o vídeo é codificado na placa quando ela existe (NVIDIA NVENC, Intel Quick Sync, AMD AMF), várias vezes mais rápido que o libx264 na CPU. O site detecta sozinho com um teste de 1 quadro, e no log aparece "⚡ codificando o vídeo na placa: h264_nvenc". Vale pra todas as etapas: clipes, cenas, efeitos, destaques, gráficos, legendas, filtro e passe final. Se a placa falhar num passo (limite de sessões, driver), aquele passo é refeito na CPU sozinho. No máximo 3 codificações na placa ao mesmo tempo. Configurações → "⚡ Codificar o vídeo com": automático (padrão), só CPU, ou uma placa específica. `NARRATION_SITE_SEM_GPU=1` desliga.
- **Qualidade "⚡ Rápida"** no Montar vídeo: todas as etapas no modo mais rápido do codificador (ultrafast), bom pra conferir a edição.
- **Diagnóstico em segundo plano**: o relatório vídeo × telinha agora é gerado DEPOIS de o vídeo ficar pronto, sem atrasar a entrega. O link espera ele terminar, se precisar.
- **Sombra dos textos mais leve** pro libass desenhar (o desfoque grande da sombra pesava nos destaques).

## ➕ Clipes que completam o trecho viram trechos próprios + vários vídeos de venda/inscreva-se (v84_27)

- **⏱ Clipes curtos → ➕ Completar**: cada clipe da mesma busca (o atual, o 2º, o 3º…) agora vira um **trecho separado** na timeline (o trecho é dividido onde cada clipe acaba). Assim dá pra pôr **transição** (losango entre eles), efeito, entrada/saída e trocar a mídia de cada um, como qualquer trecho. O último pedaço fica com o resto do tempo (se ainda faltar, ele repete). O texto na tela e a cena ficam no 1º pedaço. Em lote, os trechos são resolvidos do último pro primeiro. Depois de completar, o Estúdio recarrega.
- **Vídeos de venda / like-inscreva-se**: dá pra ter **mais de um vídeo de cada tipo** no projeto. Na aba ✂️ Cortes, o quadro do tipo mostra cada marca com um seletor: escolha **qual vídeo entra em cada uma**, ou "sem vídeo". Atalhos: todas com o 1º vídeo, **alternar os vídeos** (1º, 2º, 1º…), só a 1ª e nenhuma. "➕ Enviar outro vídeo de venda" acrescenta um vídeo sem pôr em marca nenhuma. Rotas: `/job/<id>/chamadas/<tipo>/enviar` e `/job/<id>/chamadas/escolher` (`escolhas: {marca: vídeo}`).
- **Marca sem vídeo**: nada muda ali. O vídeo e a narração seguem normais, sem corte nem pausa, e legenda e destaques ficam no lugar. Só as marcas com vídeo empurram o resto pra frente.

## 🛒 Várias marcas [[VENDA]] / [[INSCREVA]]: escolher onde o clipe entra (v84_26)

Na aba **✂️ Cortes** do Estúdio, quando o texto tem 2 ou mais marcas do mesmo tipo, aparece "🛒 3 marcas de venda — onde o clipe entra?" com uma caixinha por marca (com o tempo e o texto). Marque só onde você quer o vídeo e clique **✔ Aplicar**. Atalhos: **todas**, **só a 1ª**, **só a última** e **nenhuma**. Nas desmarcadas, a narração segue normal, e o clipe padrão não volta pra elas, nem ao enviar outro vídeo com "usar em todas". O clipe usado é o que já foi enviado nesse projeto; se não houver, o padrão do tipo. Rota: `/job/<id>/chamadas/escolher`.

Transcrição do YouTube: qualquer erro do yt-dlp ("The page needs to be reloaded", formato novo do YouTube…) agora segue pros outros caminhos (youtube-transcript-api, navegador, pytubefix) em vez de parar.

## 🔁 YouTube bloqueou o yt-dlp? Outros jeitos de pegar a transcrição e baixar (v84_25)

Quando nem os cookies resolvem o “Sign in to confirm you’re not a bot”, o site não para mais no erro (`yt_alternativas.py`):

**Transcrição (Roteiro do YouTube)**, na ordem:
1. yt-dlp com **outros clientes do YouTube** (tv, web_safari, mweb, android, ios) — às vezes o bloqueio é só no cliente padrão;
2. cookies dos navegadores (como antes);
3. **youtube-transcript-api** — pega a legenda por outro caminho, sem o yt-dlp;
4. **um navegador de verdade** (o Chromium do Playwright que o site já usa): abre o vídeo como uma pessoa e lê a legenda que o próprio player baixou (ou o painel “Mostrar transcrição”). Escondido primeiro; se não der, com a janela visível;
5. sem legenda: baixa só o áudio com o **pytubefix** e transcreve com o Whisper.

Se tudo falhar, a mensagem diz o que foi tentado e como colar a transcrição à mão.

**Download de vídeo (Cortar do YouTube / painel do editor)**: se o yt-dlp for bloqueado em todos os clientes e cookies, baixa com o **pytubefix** (vídeo + áudio juntados com o ffmpeg).

Instale as duas bibliotecas novas: `pip install -U youtube-transcript-api pytubefix` (já estão no requirements.txt).

## 🎌 Várias obras e vários personagens no Anime Pexels / Filmes e Séries Pexels (v84_24)

Em "de onde tirar as cenas" (página inicial e "Mudou de ideia sobre os bancos?"), cada anime, filme, série ou personagem/ator vira uma etiqueta: digite (ou escolha da lista) e aperte **Enter** pra adicionar outro; o **×** tira. Por dentro o campo guarda `"Naruto | Death Note"`.

- **Busca**: com várias obras, busca em cada uma e **intercala** os resultados (1º de cada, 2º de cada…, sem repetir clipe); com vários personagens, só clipes em que aparece um deles. Se nada bater com o texto, afrouxa sem sair das obras escolhidas (tira o personagem → mostra cenas das obras).
- **Prompt da IA**: lista as obras escolhidas, os personagens de todas elas (com a obra de cada um) e orienta a IA a pôr `"obra"`/`"personagem"` no trecho quando ele fala de UMA delas.
- **Estúdio** (painel do trecho e aba 🔍 Buscar): os campos aceitam `A | B`; a lista de sugestões continua funcionando depois do `|`.
- Até 12 nomes por campo. Use `|` pra separar — vírgula e ponto e vírgula fazem parte de nomes como "Steins;Gate".

## ⏱ Clipes curtos: completar, trocar por um maior ou repetir — um clique por trecho (v84_23)

Aba nova **⏱ Clipes curtos** no Estúdio. O site mede sozinho a duração do clipe de cada trecho (pelos metadados do vídeo; se o navegador não conseguir, o servidor mede com o ffprobe) e marca na timeline, com borda tracejada e ⏱, os trechos em que o clipe é mais curto que o tempo do trecho (descontando os quadros cortados do início). Na aba, cada um aparece com "clipe de X s · trecho de Y s · faltam Z s" e três botões, que mexem só naquele trecho:

- **➕ Completar com 2º/3º resultado** — faz a mesma busca e põe o 2º, 3º… resultado em seguida até cobrir o trecho (pula os clipes que já estão em outros trechos). A telinha toca um depois do outro e a montagem junta na mesma ordem; a timeline mostra onde cada clipe começa. O clipe da telinha fica fixo.
- **🎯 Trocar por um ≥ Y s** — faz a mesma busca e pega o 1º resultado com duração igual ou maior que a do trecho. Se nenhum servir, avisa qual é o maior.
- **🔁 Repetir** — mantém o clipe em loop. A montagem também repete, sem completar com outra cena.
- **↩ desfazer** volta ao normal. Há também "Em todos os curtos" com os três botões, que resolvem trecho por trecho.

Por dentro: o trecho guarda `clipes_extra` (os clipes que entram depois do principal, com a duração de cada um) e `curto: "loop"`; as rotas são `/job/<id>/clipes-curtos/<i>` e `/job/<id>/duracao-clipe/<i>`. As timelines 1/2 levam esses campos junto. Trocar a mídia do trecho limpa os clipes extras.

## 🎙 Gerar voz: voltar a acompanhar um áudio que está sendo gerado (v84_23)

A geração roda no servidor; agora, se você recarregar, fechar a aba ou abrir o Gerar voz em outra janela, a página mostra **🎙 Gerações recentes** (rodando e as da última hora) com **Acompanhar / Ver resultado**. Se a sua última geração ainda estiver rodando, ela volta a acompanhar sozinha (log e progresso), sem gerar de novo. Rota: `/gerar-voz/em-andamento`.

## 🍪 YouTube: “Sign in to confirm you’re not a bot” (v84_22)

Quando o YouTube pede login, o yt-dlp precisa dos cookies de um navegador logado no YouTube. Agora o site faz isso sozinho (`yt_cookies.py`), no Roteiro do YouTube (transcrição), no Cortar do YouTube, no painel do YouTube do editor, na busca e na extração de canal:

1. Se existir um **cookies.txt** (enviado em Configurações → YouTube, fica em `cookies_youtube.txt` na pasta do site), ele é usado sempre.
2. Senão, usa o navegador escolhido em Configurações → YouTube, ou o que já funcionou antes.
3. Se mesmo assim o YouTube pedir login, tenta sozinho **Firefox, Edge, Chrome, Brave, Opera, Vivaldi** (o log mostra “🍪 tentando com os cookies do …”) e **guarda** o que funcionou (`youtube_cookies.json`).
4. Se nada funcionar, a mensagem explica o que fazer, sem os códigos de cor do terminal (`[0;31m`).

Dicas: o mais garantido é o **Firefox logado no YouTube** ou um **cookies.txt** (extensão “Get cookies.txt LOCALLY” no Chrome/Edge → Export com youtube.com aberto e logado). Com o Chrome aberto, o yt-dlp não consegue ler os cookies dele, e as versões novas do Chrome criptografam os cookies de um jeito que o yt-dlp nem sempre lê. Mantenha o yt-dlp atualizado: `pip install -U "yt-dlp[default]"`. Os dois arquivos de cookies estão no `.gitignore` (são pessoais).

## 🎌 Obra escolhida → personagens dela listados no prompt da IA (v84_21)

No Anime Pexels / Filmes e Séries Pexels, ao escolher um **anime, filme ou série** em "de onde tirar as cenas", o prompt que vai pra IA passa a trazer a **lista dos personagens dessa obra** que existem no seu acervo, um por linha, com quantos clipes cada um tem (no de filmes: "Personagem (Ator)"). A IA é orientada a pôr `"personagem": "nome"` no trecho quando a fala é sobre ele, escrito exatamente como na lista, preferindo os que têm mais clipes.

- Vale também com um personagem fixado pro vídeo inteiro: ele continua sendo o padrão, mas a lista vai junto e a IA pode trocar nos trechos em que a fala é claramente de outro.
- Se o acervo não devolver personagem com clipe, tenta a lista sem esse filtro e, no de filmes, o elenco da ficha da obra.
- Na escolha da obra (página inicial e "Mudou de ideia sobre os bancos?") aparece "📋 Vão listados no prompt pra IA (N): …".
- Na página do prompt, um quadro mostra quantos personagens entraram no prompt, ou o aviso se o servidor do acervo estava desligado. O botão **🔄 Ler de novo e atualizar o prompt** relê a lista e remonta o prompt sem transcrever de novo.
- Tempo de espera pra ler a lista do acervo: 15 s (antes 4 s, que podia estourar com acervo grande e o prompt saía sem a lista, sem aviso).

## 🩺 Diagnóstico pós-export + vídeo igual à telinha do Estúdio (v84_20)

**Diagnóstico (arquivo de texto)** — toda montagem termina gerando `jobs/<id>/diagnostico_export.txt`, que diz o que pode ter deixado o vídeo diferente da telinha. Na página do resultado: **🩺 Baixar diagnóstico** (ou "ver aqui" / "gerar de novo"). Rota: `/job/<id>/download-diagnostico` (`?ver=1` mostra no navegador, `?refazer=1` gera de novo).

Como funciona:
1. **Foto da telinha**: ao clicar em Montar, o Estúdio passa a telinha por vários momentos (meio de cada trecho, cada destaque, cada take de cena) e anota o que ela mostra — o clipe de cada trecho, fonte/tamanho/linhas/posição de cada destaque (e se a fonte estava carregada), o fundo/escurecimento, que clipe está em cada janela das cenas, a cor do fundo da cena, a legenda. Vai junto do formulário (`previa_snapshot.json` na pasta do job). No console do navegador: `estudioDiag.fotografar()`.
2. **O que a montagem fez**: o `montagem_relatorio.json` agora guarda de onde veio cada clipe (`clipe_da_previa`, `previa_nao_baixou_busca_nova`, `busca_nova`, `escolhido_a_mao`…), os arquivos, se foi completado com outra cena, e o motivo de cada trecho ter sido (ou não) fixado no clipe da telinha (`job["fixacao_previa"]`: prévia sem link, busca editada depois da prévia, banco que não fixa…).
3. **Medição no vídeo pronto**: tira quadros do vídeo final nos mesmos momentos e compara com o clipe do trecho — é o mesmo clipe? ficou mais escuro do que a telinha mostrava (simulando as camadas que a telinha põe por cima)? que take aparece em cada janela da cena? — e pergunta ao libass qual arquivo de fonte ele usou de verdade.

O relatório lista primeiro os problemas (🔴 sério, 🟡 médio, ℹ observação), cada um com a causa provável e o que fazer; depois as tabelas trecho a trecho (telinha × vídeo), destaques (fonte, % da altura, linhas), cenas, medições e duração dos pedaços. Nunca derruba a montagem: se algo falhar, fica em `job["diagnostico_erro"]`.

**Correções achadas com ele** (o vídeo agora sai como a telinha):
- **Vídeo mais escuro**: o fundo "escurecer" dos destaques era `brightness -0.22` (subtrai luz — em cena escura ia quase tudo pro preto); a telinha põe uma camada preta de 35% (multiplica). Agora o export multiplica igual (`dp_fundos.escurecer_igual_previa`), e o mesmo vale pro desfoque escuro e o flash. A **vinheta** virou o mesmo gradiente radial da telinha (antes: filtro vignette bem mais forte + brilho -0.08 na tela toda). Fundo de mídia/vidro das cenas: brilho multiplicado igual ao CSS.
- **"Fonte diferente" nos destaques**: a fonte era a mesma, mas (1) o `\fs` do libass mede a altura da "célula" da fonte, não o tamanho da letra do navegador — a letra saía ~30% menor (Playfair) e até ~43% menor (Anton/Poppins); agora é convertido (`dp_destaques.fs_libass`, medido com o próprio libass); (2) a quebra de linha usava uma estimativa por nº de letras a 86% da largura, e a telinha quebra pela largura real das letras no espaço à direita da âncora (no centro, 50% — por isso "Built on / purpose" em 2 linhas): agora o export usa as mesmas regras (`dp_destaques.medidas_texto`, cópia de `desenharUmHl` + `manterNaTela`), incluindo o 70% pra textos com mais de 40 letras e as posições da telinha; (3) o contorno preto grosso virou a sombra suave da telinha. A legenda também usa o tamanho da telinha (altura × tamanho) convertido pro libass, e as mesmas posições (7% da base, 6% do topo).
- Na telinha, destaques alinhados à direita (cantos direitos) agora ancoram pela direita — antes o navegador dava só 5% de largura e quebrava uma palavra por linha.
- **Cena com fundo de outra cor**: a paleta do projeto pintava também o fundo próprio do template (a telinha mostrava vinho e o vídeo saía amarelo). Agora segue a telinha: o fundo do template fica com a cor dele; cor escolhida no trecho sempre vale; a paleta só tinge os fundos da galeria (`cenas_dp.fundo_tom`).
- **Take de cena com o quadro da cena anterior**: a entrada/saída do trecho era aplicada também nos takes dentro de uma cena (o take entrava sobre o último quadro da cena anterior, dentro da janela). A telinha não anima take de cena; o export agora também não.
- **"Desfazer" das buscas** e a prévia atualizada pela IA guardam o link e a busca da prévia — antes a prévia restaurada não tinha link e a montagem buscava de novo (outro clipe).

Limites: o espaçamento entre linhas do libass é um pouco maior que o da telinha (o ASS não tem "line-height"); o brilho pulsante ("interna: brilho") e a animação palavra-por-palavra só existem no vídeo; clipe que a montagem não consegue baixar pelo link continua virando busca nova — o diagnóstico mostra qual trecho e o erro.

## Export = editor: clipe da prévia curto repete (não entra outra cena) + filtro "Original" respeitado (v84)

- **Cenas que não estavam no editor**: quando o clipe que o Estúdio mostrava (o da prévia, escolhido automaticamente) era mais curto que o trecho — comum nos clipes de anime, de 2-4 s —, a montagem completava o tempo com uma **2ª cena da busca** que você nunca viu (no registro de tempos aparecia `num_clipes: 2`). O Estúdio mostra esse clipe repetindo; agora a montagem faz igual. Pra voltar ao jeito antigo: `"completar_trecho_curto": "outra_cena"` no `site_config.json`. Clipe escolhido **à mão** continua sendo completado com outra cena (pedido antigo).
- **Filtro de cor**: escolher "Original" no Estúdio agora fica gravado como "sem filtro" — antes ficava "vazio" e a montagem podia cair no filtro guardado em outro lugar.

## 🎬 Ritmo livre das cenas + destaque que não sai da tela (v84)

- **Ritmo das cenas** (página inicial, abaixo de "Trocar de vídeo a cada…"): **Livre** (padrão) — o número vira só a MÉDIA e a IA decide o tamanho de cada cena como um editor: cenas curtas (~40-70% da média) em listas, ação, tensão e frases de impacto; longas (até ~2,2× a média) quando uma imagem sustenta um pensamento inteiro, numa explicação calma, num momento emocional ou quando a mesma cena de anime/filme continua sendo descrita; sempre cortando em pausas da fala e variando o ritmo. **Fixo** — o comportamento de antes (~N s cada). Vale pro prompt geral e pro do Anime/Filmes Pexels.
- **Destaque fora da tela na telinha do Estúdio**: o texto era centralizado no ponto da zona — no alto (ou embaixo), um texto de 2-3 linhas passava da borda. Agora a prévia usa a mesma âncora do vídeo exportado (no alto o texto cresce pra baixo, embaixo cresce pra cima) e uma margem de segurança: se ainda não couber, diminui e empurra pra dentro. O vídeo exportado já ancorava assim. (Não tem relação com "cortar bordas pretas" — essa opção só mexe na imagem de fundo.)

## Export: cada pedaço com a duração certa + relatório da montagem (v84)

- Antes de juntar, a montagem confere a duração de cada pedaço (trecho ou cena). Pedaço mais curto que o planejado (download que veio menor, efeito/entrada/cena que encurtou) ganha o último quadro congelado até completar; mais longo é aparado. Sem isso, um pedaço curto deslocava todas as transições seguintes — cenas fora do lugar e o vídeo acabando antes da narração. O log mostra `[montagem] pedaço N: tinha X de Y — completando…`.
- Timelines: o **banco** do trecho agora também é da timeline (a 2ª opção pode ter vindo de outro banco); antes, salvar na Timeline 2 podia trocar o banco do trecho na Timeline 1 também.
- Toda montagem grava `jobs/<id>/montagem_relatorio.json`: por trecho, a fonte usada, o banco, a busca, efeito/entrada/saída/cena e a duração esperada × real; e por pedaço juntado, a duração e a transição. É o arquivo pra mandar quando o vídeo exportado não bater com o editor.

## 📣 Pausa pra vídeo de like/inscreva-se e de venda (v84)

**No texto do TTS** (🎙 Gerar voz, Roteiro do YouTube), ponha a marca numa linha própria, onde o seu vídeo pronto deve entrar:

```
E foi assim que tudo começou.
[[INSCREVA]]
Mas a história não para por aí...
[[VENDA]]
E no final...
```

Só duas marcas: `[[INSCREVA]]` (aceita também LIKE, INSCREVA-SE, SUBSCRIBE) e `[[VENDA]]` (aceita PRODUTO, OFERTA, AD, PATROCINIO, PUBLI). Colchete **duplo** — colchete simples continua sendo tag de voz/multi voice. No Gerar voz, o quadro "📣 Pausa pra vídeo…" tem os botões que inserem a marca no cursor.

- **Geração de voz**: a marca não é lida. Com marcas no texto, o Gerar voz gera os pedaços separados (no mesmo processo, sem recarregar o modelo), junta e guarda o **ponto exato** de cada marca no áudio. No modo multi voice o ponto vem da transcrição (Whisper). O resultado lista as pausas e o **.zip** leva um `chamadas.json`.
- **Criando o vídeo com o .zip** (página inicial): as pausas aparecem sozinhas na aba **✂️ Cortes** do editor e na faixa "Cortes" da timeline (👍/🛒).
- **No editor**: clique na pausa → envie o seu vídeo (com o áudio dele). Na montagem, a narração **pausa** ali, o vídeo toca inteiro e a narração continua de onde parou (legenda e o resto andam junto). **Sem vídeo, nada muda.**
- **Vídeo padrão** (já vem marcado): o vídeo enviado vale pra todas as pausas daquele tipo sem vídeo neste projeto e entra sozinho nas dos próximos vídeos (guardado em `chamadas_padrao/`) — ou seja, você envia o de inscreva-se e o de venda uma vez só. "Parar de usar o padrão" desfaz; "Tirar clipe" tira só daquela pausa.
- **Áudio que não veio do Gerar voz**: aba ✂️ Cortes → "📣 Chamada no cursor" marca uma na mão. Também dá pra escrever a marca numa legenda `.srt` do zip.
- **Roteiro do YouTube**: no passo 2 (reescrever a partir da legenda do vídeo), a opção **📣 A IA marca [[INSCREVA]] e [[VENDA]]** (já vem ligada) faz a IA colocar as marcas nos pontos mais oportunos: `[[INSCREVA]]` = chamada pra ação (2-3: depois do gancho, no meio e perto do fim) e `[[VENDA]]` = momento de anúncio (depois de um gancho/suspense ou troca de assunto, ~a cada 3-4 min, nunca nos primeiros 15%). O texto em volta é escrito pra funcionar sem elas (a IA não escreve "deixa o like" — o seu vídeo já faz isso). No passo 3, "💰 Melhores momentos pra anúncio" põe/ajusta `[[VENDA]]` e "👍 Chamadas pra ação" põe/ajusta `[[INSCREVA]]`; qualquer ação (traduzir, adaptar, limpar…) recebe a ordem de **manter** as marcas no mesmo ponto, e se a IA tirar alguma o site avisa. A 🧹 limpeza local nunca tira as marcas, e o "Enviar pro Gerar voz" leva elas junto.
- (Avançado: `[[INSCREVA: frase]]` também funciona — a frase é narrada e, com vídeo, ela sai e o vídeo entra no lugar.)
- Os cortes normais da IA continuam iguais; o seletor "continuar a narração", que na prática fazia o mesmo que pausar, saiu.

## Tempo limite da geração de voz: 2 horas (v84)

A geração de voz (que roda isolada num processo à parte) cancelava depois de **600 s** — pouco quando o motor está baixando um modelo grande pela 1ª vez ou gerando um texto longo. Agora o limite é **2 horas** por geração (e por fala, no modo de várias falas de uma vez). Se o motor travar de verdade (crash), o site continua percebendo em segundos — não fica esperando as 2 h. Fica em `toolkit/tts/voice_generator.py` (`gerar_audio_isolado` e `gerar_audio_isolado_lote`).

## 🎞 Timelines alternativas no Estúdio: Timeline 1, Timeline 2 e 🔀 Juntar (v84)

Na barra da timeline (onde ficava o texto de ajuda — que virou o "ⓘ ajuda") agora tem três botões; só uma timeline aparece por vez:

- **🎞 Timeline 1** — a de sempre: a melhor opção de cada cena.
- **➕ Timeline 2** — no 1º clique, gera uma timeline com a **2ª melhor opção de cada cena** (o botão mostra o progresso `⏳ 3/15` e dá pra continuar editando). Ela nunca repete o que a timeline 1 mostra: vídeos de banco pegam o próximo resultado da mesma busca (e não repetem entre si), os buscadores de imagem (Bing/Brave/Yandex/Startpage) pegam outra imagem diferente, e fotos de banco baixam o próximo resultado. YouTube e imagem gerada por IA ficam iguais aos da timeline 1. O **⟳** busca a 2ª opção de novo.
- **🔀 Juntar** — trecho a trecho, você escolhe de qual timeline vem a mídia: clique no número **1**/**2** no canto do trecho na timeline (alterna), ou selecione o trecho e clique na miniatura da Timeline 1 ou da 2 no painel da direita (as duas aparecem lado a lado). "tudo da 1" / "tudo da 2" trocam todos de uma vez. Se você trocar a mídia de um trecho à mão dentro do Juntar, ele vira **✎** (fica com a escolhida lá).

**A edição é uma só pras três**: efeitos, entradas/saídas, transições, cenas, textos, destaques, sons, legenda, direção e JSON da IA, tempos dos trechos — mexeu numa timeline, vale nas outras. Só a **mídia** de cada trecho muda. Dividir ou juntar trechos também não bagunça: cada trecho pega a mídia da outra timeline que cai no mesmo tempo.

**Montar vídeo** exporta a timeline que está aberta (o modal mostra qual). Na Timeline 2, os vídeos ficam fixados pelo link do post (Pexels, Pixabay, Mixkit, Anime/Filmes Pexels) — Magnific e VistaCreate não deixam fixar um resultado, então o trecho mostra um aviso (na montagem ele busca de novo e pode vir a 1ª opção; escolha em 🔍 Ver opções pra garantir).

Por dentro (`timelines.py`): a timeline aberta continua em `pending_segments`/`segment_previews` (o resto do site não muda); as outras ficam em `job["timelines"]` como "fatias de mídia" com o tempo de cada trecho. Rotas: `/job/<id>/timeline/gerar`, `/status`, `/trocar`, `/escolher`, `/<tl>/thumb/<i>`.

## Export: imagem trocada no lugar de vídeo não corta mais o final + sem quadros pretos entre cenas (v84)

- **Quadros pretos nas emendas**: as entradas/saídas do DarkPlanner (slide, zoom, pop, fade…) animavam o clipe sobre um fundo **preto** — num corte seco, cada emenda piscava alguns quadros pretos. Agora elas rodam depois que todos os clipes existem: o clipe **entra sobre o último quadro da cena anterior** e **sai sobre o primeiro quadro da seguinte**. A saída só é aplicada quando a emenda seguinte é corte seco (com transição ela brigaria com o xfade). Só a entrada do 1º trecho e a saída do último continuam partindo/terminando no preto (abertura e fechamento do vídeo).
- **Vídeo cortando antes das imagens**: a junção final usava "copiar sem recodificar", que exige todos os clipes idênticos (fps, base de tempo, proporção do pixel, perfil). Quando um clipe sai diferente — como uma imagem trocada no Estúdio no meio de vídeos — alguns players param o vídeo ali. Agora a montagem confere os clipes antes: iguais → junta copiando (rápido, como antes); diferentes, **ou se o resultado sair mais curto que a soma dos clipes**, junta recodificando tudo num fluxo só (mesma resolução, 30 fps, áudio dos cortes preservado). No log aparece `[montagem] ... concatenando com recodificação`.

## 🎬 Filmes e Séries Pexels + obra e personagem/ator nos acervos locais (v84)

Novo banco **moviepexels**: o catálogo de **filmes e séries** do seu anime-pexels-local (v62+). É o **mesmo servidor** do Anime Pexels — o site fala com `/movie/api/...` do endereço que já está nas Configurações, então nada muda no outro HD: com o `app.py` de lá rodando, os dois funcionam. Tem tudo que o animepexels tem (busca por texto + semântica, pesos, orientação, duração, não repetir clipe, prévia tocável, fixar o clipe da prévia na exportação).

**Obra e personagem/ator** (vale pros dois acervos):
- Na página inicial (e na do prompt, ao trocar os bancos), marcando animepexels ou moviepexels aparece o quadro **"de onde tirar as cenas"**: escolha o **anime** / **filme ou série** e, se quiser, o **personagem** (no de filmes, **personagem ou ator** — o acervo guarda "Personagem (Ator)", dá pra digitar qualquer um dos dois). As listas vêm do seu acervo, com quantos clipes cada personagem tem.
- Com a obra escolhida, toda busca nesse acervo fica **só dentro dela**; com o personagem, **só clipes em que ele aparece**. Se nada bater, o site afrouxa sem sair da obra: tira o personagem → mostra cenas da obra (com o personagem, depois sem) — antes de cair num banco genérico.
- O prompt leva isso pra IA: a obra fixada, ou a **lista de obras do acervo** (pra ela usar o nome exato em `"obra"` por trecho), e a **lista de personagens/atores com clipes** (pra pôr `"personagem"` nos trechos em que a narração fala deles). Com só um acervo marcado, o prompt dedicado vale pros dois (exemplos de filme no moviepexels).
- No Estúdio, cada trecho desses acervos mostra **Anime/Filme ou série** e **Personagem/ator** no painel do trecho e na aba 🔍 Buscar (com as listas do acervo); fica salvo no trecho e vale na montagem.
- Configurações antigas ganham o moviepexels no fim da prioridade sozinhas. Servidor do acervo desligado não trava nada: o prompt sai sem as listas e as caixas avisam.

## 📜 Roteiro do YouTube (v84)

Aba nova (link vermelho no topo). **1 · Transcrição:** cole o link do vídeo — o site pega a legenda do próprio vídeo (manual, ou a automática no idioma original; sem baixar o vídeo) e, se não tiver legenda, baixa só o áudio e transcreve com o Whisper. Ou cole a transcrição (com tempos "0:12 texto", .srt/.vtt ou texto corrido). **2 · Reescrever + cenas:** escolha um **modelo de prompt** (3 de fábrica: reescrever + cenas, só cenas, versão Short; dá pra editar e criar os seus com `{transcricao}`, `{titulo}`, `{idioma}`…) e o idioma do roteiro; a IA reescreve trocando exemplos específicos demais por equivalentes, tira o que só fazia sentido no vídeo original e **lista as cenas** de filmes/séries/animes/jogos (obra, tipo, ano, momento, onde aparece no vídeo original, termo pra buscar no YouTube, certeza) em JSON. **3 · O que fazer:** marque e combine — traduzir (ex.: inglês), **tags de voz do Chatterbox Turbo** (só as que ele conhece), **momentos pra anúncio**, **chamadas pra like/inscrever/comentar** (dentro do texto ou só listadas), adaptar pra **não precisar das cenas**, **marcar [CENA n]** onde cada cena entra, títulos e gancho, e um pedido livre. **4 · Resultado:** roteiro final com as tags realçadas (tag desconhecida aparece em amarelo com ⚠), palavras e minutos, anúncios e chamadas com a posição no roteiro, títulos; **🎙️ Gerar voz com este roteiro** abre o Gerador de voz já preenchido (sem os [CENA n]); cada cena tem **🔎 Buscar no YouTube** (clique no vídeo certo, ponha início/fim) e no fim **✂️ Cortar as cenas** abre o Cortar do YouTube já preenchido — ou **✂️ Cortar do vídeo original** pelos tempos em que a cena aparecia nele. Baixa .txt e o JSON completo. Projetos ficam em `roteiros_yt/`.

**🧹 Limpar pro TTS** (pra o gerador de voz não engasgar): no passo 3, a opção **🧹 Limpar pro TTS** pede à IA pra corrigir palavras escritas errado (comum em legenda automática) e escrever por extenso número, ano, moeda, porcentagem, sigla e abreviação do jeito que se fala. E no resultado, o botão **🧹 Limpar pro TTS (caracteres estranhos)** limpa na hora, sem IA: emojis, caracteres invisíveis, [Música]/(risos), links, @menções, #hashtags, markdown, aspas e travessões tipográficos, !!!/???, "muuuito", & → e/and, ° → graus/degrees e tags entre colchetes que o Chatterbox Turbo não conhece — as tags válidas e os [CENA n] ficam. Mostra o que tirou e dá pra desfazer. Com a opção marcada no passo 3, essa limpeza também roda sozinha quando você cola a resposta da IA.

## 🔎 Buscas das cenas bem melhores (v84)

As IAs devolviam buscas fracas porque o prompt só dizia "termo em inglês, visual, 2 a 5 palavras". Agora:

- **O prompt tem uma seção inteira "Como escrever a busca"**, logo antes do formato da resposta: o banco acha clipe pelas *etiquetas* do que se vê; concreto em vez de abstrato (com exemplos de como traduzir "crise", "medo", "o tempo passou"…); o literal ganha do criativo; nada de nome de pessoa/marca/ano num banco de estoque (troque pelo tipo da coisa — e aponta Wikipedia/buscadores quando estão marcados); uma coisa por busca; sem "4k/footage/stock"; época e lugar pelo que se vê; emoção pelo rosto; **identidade visual** do vídeo inteiro; **variar o plano** (nunca a mesma busca em trechos seguidos); e exemplos fala → busca ruim → busca boa.
- **A IA escreve a imagem antes da busca** (`"visual"`, em português) — escrever a cena primeiro melhora muito a busca, e no Estúdio aparece como "💡 Ideia da IA".
- **Buscas de reserva**: cada trecho traz 1–2 `"alternativas"` (mais simples, mesma ideia) e o vídeo traz uma `"busca_reserva"` com a cara dele (ex.: "dark foggy forest at night"). Quando a busca não acha nada, a montagem tenta as reservas da IA → as 3 palavras principais → a última palavra → a reserva do vídeo — o antigo "nature background" só entra se a IA não mandou reserva. Os buscadores de imagem e o "🔧 Corrigir automaticamente" também usam as reservas.
- **Limpeza automática**: "4K stock footage", "HD", "b-roll", aspas e pontuação saem da busca ("stock market" continua).
- **Aviso no Estúdio** quando as buscas têm cara de vídeo ruim: fora do inglês, a mesma busca muitas vezes ou em trechos seguidos, busca longa demais.
- **🧠 Revisar todas as buscas com IA** (aba 🔍 Buscar do Estúdio): o primeiro prompt pede muita coisa de uma vez, então este manda **só a fala de cada trecho e a busca atual** (com o que você quer, ex.: "mais clima de terror") e pede buscas melhores. Cole a resposta, confira o antes → depois, desmarque o que não quiser e aplique: salva e já busca as prévias novas dos trechos trocados (dá pra parar e pra desfazer). Vale também pros buscadores de imagem (Bing…), onde a IA troca termos repetidos por cenas diferentes. Mídia escolhida à mão, Flow, YouTube e Wikipedia ficam como estão.
- Na aba Buscar, as reservas de cada trecho viram botões: um clique busca por elas.

## 🎯 O vídeo exportado usa as mesmas cenas do Estúdio (v84)

Antes, todo trecho sem mídia escolhida à mão fazia uma **busca nova** na hora de montar — e a busca nova (com "não repetir" e outros candidatos) trazia **outras cenas** que as da prévia: a edição feita em cima delas saía diferente. Agora, quando a prévia do trecho foi achada com a mesma busca e o banco baixa um resultado específico pelo link (Pexels, Pixabay, Mixkit, Anime Pexels), a montagem usa **exatamente aquele clipe**. Se ele for mais curto que o trecho, ainda completa com outra cena; os clipes fixados ficam reservados pra busca dos outros trechos não trazer o mesmo; e se o link falhar na hora, o trecho volta pra busca normal em vez de dar erro. No editor o trecho continua "automático" (trocar a busca depois volta a buscar). Magnific/VistaCreate não baixam por link, então continuam buscando de novo. Pra voltar ao comportamento antigo: `"fixar_midias_da_previa": false` nas configurações.

## 🧹 Textos da 1ª IA saem quando entra a edição da IA (v84)

A 1ª IA (a das buscas, na página do prompt) também põe textos: texto na tela por trecho, destaques e overlays de texto. Ao aplicar o JSON da **IA de edição** no Estúdio (aba 🤖 IA), o resumo mostra **🧹 Tirar os N textos da 1ª IA** (marcado): esses saem **antes** de entrarem os destaques novos — assim os novos não "batem" nos antigos. Texto que você editou à mão e destaques/overlays que você criou ficam. **↩ Desfazer** devolve tudo, inclusive os overlays. Vale pros projetos criados a partir de agora (os antigos não sabiam de qual IA veio cada texto).

## 🖼 Buscadores de imagem: sem imagem repetida e sem marca d'água (v84)

- **Não repete imagem**: antes cada termo pegava a 1ª imagem do Bing/Brave/Yandex/Startpage — termos parecidos (ou o mesmo termo em vários trechos) davam a mesma foto 10 vezes seguidas. Agora cada termo olha até 8 resultados e pula o que outro trecho já usa, comparando o endereço **e a própria imagem** (assinatura visual do arquivo baixado — a mesma foto em sites diferentes, recortada ou recomprimida, é reconhecida). O mesmo termo em vários trechos traz imagens diferentes pra cada um. Só se todos os buscadores tiverem apenas imagens já usadas é que uma repetida entra, pra não deixar o trecho vazio.
- **Sem marca d'água**: imagens de bancos pagos (Alamy, Shutterstock, Getty, iStock, Dreamstime, 123RF, Depositphotos, Adobe Stock e outros ~40) são descartadas pelo endereço, pela página de origem e pelo título ("… Stock Photo - Alamy"). Vale pra montagem, pras prévias e pro "Buscar opções" do editor.
- **Aviso de cookies do Bing** ("A Microsoft e nossos fornecedores… Aceitar / Rejeitar") ficava por cima da grade e atrapalhava os cliques: agora o site clica em **Aceitar** sozinho, a qualquer momento que ele aparecer.
- No Bing, com vários candidatos por termo, o site lê o endereço original direto do card em vez de abrir o detalhe de cada imagem (bem mais rápido — antes isso fazia os candidatos não chegarem).
- Imagem que só existia repetida não é aceita de cara: antes ela tenta a busca reserva da IA; só se nada achar entra a repetida, marcada na prévia como "⚠ repetida".
- O prompt agora manda a IA **nunca repetir o termo** nos buscadores e variar a cena quando a narração fica muito tempo no mesmo assunto (outra cena, personagem, pôster, bastidores…).

## 📋 Cortar do YouTube: colar um texto e pronto (v84)

Na aba **✂️ Cortar do YouTube**, o quadro **📋 Colar texto com os links e os tempos**: cole do jeito que tiver (anotação, resposta de IA, capítulos de um vídeo) e o site acha os links, os tempos e as descrições sozinho. **👁 Conferir** monta os vídeos e trechos nos campos de baixo pra revisar; **⚡ Criar e cortar tudo** já começa a baixar e cortar.

Entende: `0:15 - 0:42 descrição`, `1:10 a 1:30 | descrição`, `de 2:00 até 2:20`, `2:40 até o fim`, `a partir de 7:30`, `45s - 1m20s`, `[1:02:03 -> 1:02:30]`, `descrição: 0:10-0:20`, link e tempo na mesma linha, listas com marcadores/números, **capítulos** (`0:00 Intro` / `1:23 Parte 2` — cada um vai até o próximo), título escrito antes do link (vira a descrição) e link repetido (junta os trechos). Link sem tempo = o vídeo inteiro. Tempo inválido ou fim antes do início aparece como aviso e é ignorado.

**Qualidade do download corrigida**: antes, quando o cliente padrão do YouTube falhava, o site caía no cliente "android" — que hoje costuma entregar só **360p** — e aceitava sem conferir. Agora ele tenta os clientes padrão → tv/web_safari → mweb → android, **mede a resolução de cada download** e fica com o melhor, parando assim que atinge a qualidade pedida. Pede vídeo e áudio separados (é assim que o YouTube entrega acima de 360p), prefere H.264 e passa o caminho do ffmpeg pro yt-dlp juntar os dois. O log mostra a resolução real ("✔ baixado em 1080p") e o `info.json` também (`"resolucao"`). O corte agora usa CRF 17 (quase sem perda) em vez do padrão, que borrava. Vale também pros vídeos do YouTube usados no Estúdio. Se mesmo assim vier baixo, o log avisa: atualize o yt-dlp (`pip install -U "yt-dlp[default]"`) e instale o Deno (https://deno.com).

## 🌐 Idioma do vídeo = idioma da narração (v84)

- O **Gerador de voz** descobre o idioma da narração (o que você escolher em "🌐 Idioma da narração"; senão pela voz — Chatterbox Turbo = inglês, Piper `pt_BR-…`, Kokoro `pf_…`, idioma do XTTS/Chatterbox; senão pelo texto) e grava num `info.json` dentro do **.zip** de narração + legenda.
- Ao enviar o .zip pra gerar o vídeo, o campo "Idioma da narração" vem em **Automático**: usa o idioma do .zip (sem `info.json`, adivinha pela legenda; áudio solto, o Whisper detecta). Escolher um idioma ali força.
- Todos os prompts pra IA (roteiro do vídeo, edição pela IA no Estúdio) levam a regra: **todo texto que aparece no vídeo** — textos na tela, destaques, títulos, gráficos, cenas — no idioma da narração. Só os termos de busca e os prompts de imagem podem ficar em inglês (não aparecem). A página do prompt mostra o idioma e de onde ele veio.

## 🎞️ Vídeos modelados — Flow em várias abas, perfis de voz, áudio por personagem (v84)

- **Perfis de voz viram vozes sozinhos**: cada perfil (🗣️ Perfis de voz) aparece na lista de vozes como uma voz Chatterbox Turbo, com o gênero/idade do perfil — não precisa cadastrar slug. A voz embutida `[narrator]` continua lá (sem gênero, então não gera mais o aviso "a voz [narrator] está cadastrada como neutro").
- **Áudio agrupado por personagem**: as falas que faltam são geradas num processo só por motor, todas as de um personagem e depois as do próximo — o modelo e o perfil de voz carregam uma vez. No fim as falas são mescladas na ordem do roteiro.
- **Flow em paralelo**: 1 a 3 **abas** do Flow trabalhando juntas (cada uma um projeto), com um **intervalo sorteado** (padrão 2–9 s) entre um envio e outro. No **⚡ Frames + animação de tudo** cada cena é animada assim que o frame dela fica pronto. Clicar em gerar/animar uma cena enquanto roda **põe na fila** (em vez de "Já tem uma etapa rodando").
- **Frame pelo modo direto**: a imagem é gerada na caixa com o Agente desligado (Imagem · proporção · modelo · x1) — sem depender da resposta do agente (era o "O Flow respondeu sem gerar imagem: Gerado…").
- **Animação pelo chip "Início"**: Vídeo → Frames → modelo/720p/4s/x1 → **Início** → envia o frame (o nome do arquivo identifica a imagem na lista) → **Incluir no comando** → movimento → gerar.
- **Fluxo do Flow blindado**: cada botão é achado por várias pistas (classe, rótulo, texto em português e inglês) e só o que está **visível** é usado (o Flow deixa cópias escondidas da caixa). O chip **Agente** é opcional: se aparecer ligado, é desligado; se não aparecer, segue. Cada passo confere se deu certo (opção marcada, texto dentro da caixa, frame no "Início") e tenta de novo; se um pedido falha **antes** do clique em gerar, ele volta pra fila e é refeito num projeto novo (até 3 vezes, sem gastar crédito). O clique em gerar é um só. Depois de mudar as opções de um painel (configurações do projeto ou da caixa), o site clica em **Salvar** (procura por classe e pelos textos Salvar/Save/Aplicar/Concluído/Done) e confere que o painel fechou antes de seguir. Testado contra versões alteradas do Flow (layout com Agente, tudo em inglês sem rótulos, botão que ignora o 1º clique) em `toolkit/googleflow/test_lote_abas.py`.
- **Painel "Configurações do agente"**: nos Vídeos modelados o site NÃO abre mais esse painel (modelo, proporção e x1 são escolhidos na própria caixa a cada pedido). Se ele aparecer aberto (cobre a caixa de comando), o site clica em **Salvar**, confere que fechou e, se não fechar, usa o **X**. O botão de configurações da caixa só é procurado dentro da caixa — nunca mais "qualquer botão com 'configura'", que reabria esse painel sem parar.
- **Animação reaproveita o frame do projeto**: a imagem gerada no Flow já fica na lista de mídias daquele projeto. O site guarda o id dela (o `<id>` de `flow-content.google/image/<id>`, o mesmo da miniatura na lista) e, ao animar, escolhe a própria imagem no "Início" — sem enviar arquivo. Cada aba pega primeiro as animações dos frames gerados nela. Frame que veio de fora (arquivo seu) é enviado como antes.
- **Aviso "Direitos de uso desta imagem"**: ao enviar um arquivo, o site clica em **Concordo**.
- **📱 Janela compacta** (ligada por padrão): abre o Flow no layout estreito — o que funcionou nos testes. A lista de mídias desse layout (tela própria com "Enviar mídia") também é reconhecida.
- **Diagnóstico com o HTML que importa**: quando algo falha, além do print (`.png`) e do texto (`.txt`), o site salva `<data>_html.txt` em `flow_dados/diagnostico/` só com a caixa de comando, os painéis/pop-ups abertos e a lista de botões visíveis — sem o "lixo" do Angular. É esse arquivo que dá pra copiar e mandar. O caminho aparece no erro da cena.
- **Personagens**: acima das falas, cada personagem do roteiro aparece com a voz dele — trocar ali muda **todas** as falas daquele papel (e avisa se o gênero/idade do personagem não bate com a voz). Ainda dá pra trocar a voz de uma fala só.
- **Navegador visível** por padrão (desmarque "👁 mostrar o navegador" pra ocultar) e um painel **"GERANDO NO GOOGLE FLOW AGORA"** com capturas ao vivo de cada aba (a cada ~3 s), cronômetro por cena, fila e o próximo envio.

## 🎞️ Vídeos modelados (v84)

Nova aba **🎞️ Vídeos modelados** (no topo de todas as páginas): um Short inteiro feito de cenas geradas por IA num **estilo** fixo, com narração e diálogos.

1. **Prompt master** — escolha o estilo (vem o **Kamishibai — terror retrô** de exemplo), escreva o tema ou a lenda, a duração (60 s) e o formato (**9:16** por padrão). O site monta o prompt com o estilo, as suas **vozes com slug** (nome, **gênero**, descrição, se aceitam tags) e as **tags de áudio do Chatterbox** em inglês. A IA devolve um JSON com personagens, falas (narração / diálogo / pensamento, voz, tags, emoção, pausa) e cenas (~1 a cada 4 s: descrição da imagem + movimento, em inglês). Dá pra corrigir cada fala na tela.
2. **Áudio + .srt** — cada fala é gerada com a voz do slug; o silêncio das pontas é cortado (com 40 ms de respiro) e as falas são juntadas com as pausas pedidas, então os tempos são **exatos**. Saem `legenda.srt` (limpa, diálogo com "— ") e `legenda_personagens.srt` ("NARRADOR: …", "YUKI: …"). Gerar de novo só refaz as falas que mudaram. As tags viram som/estilo só nas vozes **Chatterbox Turbo** (que falam inglês); nas outras saem do texto e a "emoção" ajusta a intensidade (Chatterbox multilíngue).
3. **Ajuste de tempos** — um 2º prompt manda os tempos reais de cada fala; a IA devolve as cenas com início/fim (no máximo a duração do vídeo gerado, pode dividir/juntar e corrige o movimento). Ou **⚡ Distribuir automático** sem IA.
4. **Frames** no Google Flow — molde do estilo + `{cena}` + `--ar 9:16`, no modelo de imagem do estilo (ex.: Nano Banana 2.1). O projeto do Flow é configurado com a proporção e o modelo.
5. **Animação** no Flow (vídeo com frame inicial): **+** → imagem → espera a prévia → *Incluir no comando* → desliga o **Agente** → configurações da caixa → **Vídeo → Frames → Omni 1.1 Flash → 720p → 4s → x1** → digita o movimento → gerar. Por cena dá pra gerar outro frame, reanimar ou mandar um arquivo seu.
6. **Estúdio** — vira um projeto normal: áudio completo como narração, cada cena um trecho no tempo certo (vídeo mais curto que a cena é desacelerado até 2×), corte seco, formato do projeto e a legenda do estilo já ligada (troque no painel de legendas). É só montar.

**Estilos**: editar, duplicar, criar e restaurar o embutido. Cada um guarda descrição, como contar a história, os moldes `{cena}`/`{ar}` (imagem) e `{movimento}` (animação), exemplos de movimento, formato, duração da cena e do vídeo, legenda e o Flow (modelo de imagem, modelo de vídeo, resolução, duração — `auto` escolhe 4/6/8/10 s pela cena, gastando mais créditos). Ficam em `estilos_modelados.json`; os projetos em `modelados/`.

**Vozes — padrão Chatterbox Turbo (inglês, com tags)**: sem nenhuma voz com slug cadastrada, a aba usa a **voz embutida do Chatterbox Turbo** como narradora (o vídeo inteiro sai em inglês, com as tags virando som). O botão **➕ Cadastrar vozes Chatterbox Turbo** cria `[narrator]` (a embutida) e uma voz Turbo por **perfil de voz** salvo — aí é só marcar o gênero de cada uma. O Kamishibai vem com o idioma **English**; com vozes de outros motores, mude o idioma no projeto.

**Gerador de voz e Roteiro para Áudio abrindo na hora**: o diagnóstico de GPU (`import torch`, teste de CUDA, `nvidia-smi`, onnxruntime) rodava a cada abertura dessas páginas — no Windows com PyTorch, vários segundos, e travava as outras páginas enquanto o torch carregava. Agora roda uma vez em segundo plano quando o servidor sobe; a página mostra "verificando a GPU…" e atualiza sozinha.

**Gênero e idade nos Perfis de voz**: cada perfil (🗣️ Perfis de voz) tem **gênero** (masculino / feminino / neutro), **idade** (👧 criança / 🧑 jovem / 🧔 adulto / 👴 idoso) e descrição — no formulário de criar e em cada perfil salvo (salva ao mudar). As vozes com slug que usam o perfil **herdam** isso (aparece "↳ do perfil"); mudar na própria voz vale só pra ela. O prompt da IA diz "voz feminina, idosa", pede a idade de cada personagem e o site avisa se a IA der uma voz de adulto pra uma criança. Os dados ficam em `perfis_info.json`.

**Gênero das vozes**: agora toda voz com slug tem gênero (masculino / feminino / neutro) e uma descrição curta — no Gerador de voz (ao salvar e na lista) e na própria aba. Entra também na instrução do 🎭 multi voice.

⚠️ O passo de **animar com frame** foi escrito pelo passo a passo e pelo HTML que você mandou, mas não rodou contra o Flow real: o que o menu **+** oferece (envio de arquivo ou imagem do projeto), onde o vídeo pronto aparece e o editor com o Agente desligado são as partes incertas. Se falhar, o print fica em `flow_dados/diagnostico/`.

## 📐 Vídeo horizontal, vertical ou quadrado (v83)

Cada vídeo tem o seu formato: **16:9** (YouTube), **9:16** (Shorts, Reels, TikTok) ou **1:1** (feed).

- **No envio do áudio:** "Formato do vídeo" (sem escolher, vale o das Configurações, que agora também tem o 1:1). A busca de vídeos e imagens já procura no formato, e o prompt da IA pede enquadramento que funcione nele.
- **Depois, no Estúdio:** seletor 📐 no topo — o monitor muda na hora e o formato vale ao montar (o modal Montar mostra as resoluções do formato, ex.: 1080p = 1080×1920 no vertical).
- **O que se ajusta sozinho:** cenas/takes no vertical empilham as janelas (lado a lado vira um em cima do outro, texto na faixa de baixo); gráficos viram cartões largos; destaques, legendas e textos das cenas usam o mesmo tamanho de letra em qualquer formato (não estouram a largura).
- **Mídia de outro formato** (vídeo deitado num vídeo vertical): use 🔎 Zoom ou ✨ Inteligente nas Bordas pra preencher sem faixas.
- As áreas de censura ficam onde você as pôs (em fração da tela) — confira depois de trocar o formato.

## 🙈 Censura: blur, pixelado, tarja e bip (v82)

No Estúdio, botão **🙈 Censura** (barra da timeline) ou duplo clique na nova faixa **Censura**: entra no cursor e você arrasta a área direto no **monitor** (o quadradinho amarelo no canto muda o tamanho).

- **Imagem:** desfoque (blur), pixelado (mosaico) ou tarja sólida com cor e rótulo opcional ("CENSURADO", "CONFIDENCIAL"). Forma retângulo ou **elipse** (rosto), intensidade 1–10, ou **tela inteira** pra cena sensível toda.
- **Movimento:** marque "a área desliza" e ajuste o ponto inicial e o final — acompanha algo que se mexe em linha reta. Mudou de direção? "⧉ Duplicar depois" cria a próxima censura começando onde a outra terminou.
- **Áudio:** **bip** (silencia a fala/efeitos e toca o "piiii", com volume e tom ajustáveis) ou **silenciar**. A trilha de fundo continua.
- A censura de imagem é aplicada na cena **antes** dos textos, destaques e gráficos — eles continuam legíveis por cima. Funciona com a seleção múltipla (mover/apagar em grupo).

Também corrigido: reaplicar a resposta da IA duplicava os **gráficos** (mesmo problema que os sons tinham na v79).

## 🖼 Buscadores de imagem na proporção do vídeo (v81)

Bing, Brave, Yandex e Startpage agora pedem imagens na proporção do vídeo. Em **Configurações → Proporção das imagens dos buscadores**:

- **Automática** (padrão): segue a orientação da busca/exportação — **16:9 → horizontal, e quadrada se faltar**; 9:16 → vertical, e quadrada se faltar; busca "mista" → qualquer.
- Ou fixa: horizontal + quadrada, só horizontal, só quadrada, vertical + quadrada, só vertical, qualquer (o comportamento antigo).

Como funciona: cada passada usa o filtro do **próprio buscador** (no Bing, o filtro nativo de proporção `aspect-wide`/`aspect-square` da busca; nos outros, o tamanho medido em cada resultado). A passada "quadrada" só roda pros termos que não acharam horizontal. Se um termo não tiver NENHUMA imagem na proporção, uma busca sem filtro entra como reserva, com a horizontal/quadrada primeiro e a em pé por último — melhor uma foto com fundo desfocado do que trecho vazio. Vale pra montagem em lote, pras prévias e pra aba 🔍 Buscar do editor.

## 🎚 Proporção fotos × vídeos + vídeo gerado no Flow (v80)

Na escolha dos bancos (página inicial, "JSON existente" e "Mudou de ideia sobre os bancos?" na página do prompt) há a caixa opcional **🎚 Definir a proporção de fotos × vídeos**:

- **No vídeo todo** — ex.: 90% fotos / 10% vídeos. Vale pros demais bancos: um trecho de banco só de vídeo de estoque (pixabay, magnific, mixkit, vistacreate) pode virar **foto do pexels** com o mesmo termo, se o pexels estiver marcado.
- **Por banco** — **flow** (90% imagens geradas / 10% vídeos gerados, por exemplo) e **pexels**. A linha só aparece com o banco marcado.
- Botões rápidos 100/90/75/50/25/10/0% e "livre". Desmarcada, a IA decide como antes.

A regra entra no prompt, e quando a resposta da IA chega o site **confere e ajusta** os trechos que fugirem da proporção (espalhados ao longo do vídeo, nunca mexendo em trecho que você fixou). O que foi ajustado aparece num aviso 🎚 no Estúdio. Se a proporção não der (ex.: 100% fotos só com bancos de vídeo), o aviso explica.

**Flow agora gera VÍDEO também** (Veo, ~8 s, no modelo de vídeo escolhido em Configurações): trecho `"provider": "flow"` com `"media_type": "video"`. Espera no mínimo 10 min por vídeo; se não sair (limite, recusa, tela mudou), o trecho vira uma **imagem gerada** da mesma cena. O "flow" continua fora da lista de bancos reserva dos outros trechos (nunca gera nada sem você pedir). ⚠️ O HTML do cartão de vídeo do Flow não foi conferido numa página real — se o vídeo aparecer no Flow mas o site der "tempo esgotado esperando o vídeo", ajuste **Seletor CSS do VÍDEO** em Configurações (o diagnóstico com print fica em `flow_dados/diagnostico/`).

## 🎬 Correções achadas no vídeo-vitrine (v79)

Montei um vídeo inteiro só com a ferramenta (narração multi voice com Kokoro, .zip com .srt, JSON da IA aplicado no Estúdio) e isso revelou três bugs, já corrigidos:

- **Resolução do modal "Montar"** (480p…2160p) era guardada no job mas a montagem usava a das Configurações — agora vale a escolhida.
- **Reaplicar a resposta da IA duplicava os sons** extras — os sons vindos da IA são marcados (`origem: "ia"`) e trocados, não somados.
- **Gráfico Comparação (A × B)** com números grandes ("139.820 km") num cartão estreito encostava um valor no outro — a fonte agora encolhe pra caber.

## 🎭 Multi voice — [slug] no texto troca a voz (v78)

No **Gerador de voz**, em **🎭 Vozes com slug**: configure uma voz no
formulário (motor, voz/perfil, velocidade…), dê um nome ("Ricardo") e salve —
ela ganha um slug (`[ricardo]`). **▶ Testar** gera uma frase com ela; **↻
Atualizar** troca a configuração pela que está no formulário; clicar na tag
copia e insere no texto.

Marque **🎭 Modo multi voice** e escreva:

    Era uma noite fria em Berlim.
    [ricardo] Você ouviu isso?
    [ana_clara] Ouvi. Fica quieto.

A tag **não é lida**: a narração troca pra voz do Ricardo e fala o que vem
depois até a próxima tag (o texto antes da 1ª tag usa a voz escolhida no
formulário). A prévia mostra quem fala cada parte e avisa tag sem voz
cadastrada (nesse caso a geração não começa, pra nunca ler o nome). Pausa
configurável na troca de voz; volume normalizado no final; legenda .srt como
sempre. Tags do Chatterbox Turbo (`[laugh]`, `[sigh]`…) continuam valendo.

No **Roteiro para Áudio**, a caixa **🎭 Modo multi voice** na configuração do
projeto faz o mesmo em cada fala — e a voz continua de uma fala pra próxima
até aparecer outra tag. **📋 Copiar instrução pra IA** gera um texto pra pedir
à IA o roteiro já com as tags das suas vozes. As vozes ficam em
`vozes_multi.json` na pasta do site.

## Refino fino pela IA + cores dos gráficos (v77)

O JSON do **prompt de edição** agora dirige o acabamento todo:

* **Destaques**: posição na tela (`zona`), **ênfase** (palavras do texto na
  cor de acento), fonte, maiúsculas, tamanho (`escala`), animação de entrada
  e de saída (sobrepõem as do estilo), movimento interno (brilho/flutua), cor
  própria, fundo (id, cor, intensidade), som (ou "nenhum") e legenda
  manter/ocultar. **Textos livres** (`avulso: true`) com tempo próprio.
* **Trechos**: composição (`bordas` — inclusive *smart* —, `camera` e
  `foco` x/y em fotos), som de cada transição (`transition_som`), cenas com
  fundo e cor (`_fundo`, `_fundo_cor`).
* **Legenda**: estilo, posição, tamanho, maiúsculas, cor da palavra ativa.
* **Sons** extras com volume.

No Estúdio, o painel do destaque ganhou **✍ Texto, ênfase e animação** pra
ajustar tudo isso à mão (a prévia mostra ênfase, fonte e tamanho).

**Gráficos com cores editáveis** (painel 🎨 Cores do gráfico): esquema (tons
da paleta, uma cor só, monocromático, cores vivas, uma cor por item), cartão
(escuro, claro, sem cartão), cor principal, cor dos itens fora do destaque,
cor e opacidade do fundo, cor do texto e **cor de cada item** (também dá pra
escrever `rótulo: valor #RRGGBB` nos dados). A IA pode mandar tudo isso.

## Prompt de edição com a IA + gráficos animados (v76)

**🤖 IA (aba do Estúdio)** — a 2ª etapa com a IA, depois do vídeo montado.
**📝 Gerar prompt** junta: a **direção escolhida** (aba 🎨 Direção — do
sistema, sua ou o kit) com as % e os itens/pesos de cada eixo; os catálogos
filtrados por ela (só os ids permitidos); a **timeline como está agora**
(cada trecho com tempo, mídia, cena, transição, efeitos e a fala dele); os
destaques e gráficos atuais; e a **fala com os tempos** (transcrição/SRT). Dá
pra escrever o que você quer ("mais gráficos", "cortes rápidos no começo"…).
Copie, cole na IA, cole a resposta de volta → **👁 Conferir** mostra o que vai
mudar (e o que foi ignorado por id inválido) com caixinhas por categoria →
**✅ Aplicar** (com **↩ Desfazer**). A IA pode mandar: transições, efeitos,
entradas/saídas e cenas por trecho, destaques (ancorados na palavra falada),
**gráficos**, filtro, paleta, legenda e sons.

**📊 Gráficos animados** (faixa "Gráficos" da timeline): barras, barras
deitadas, linha (evolução), pizza, rosca, comparação A × B, número grande e
porcentagem em anel — barras crescendo, linha se desenhando, fatias girando e
números contando, com título, unidade (%, R$, US$ bi, mi…), fonte no rodapé,
item em destaque, posição (centro, esquerda, direita, embaixo, tela cheia) e a
cor da paleta. A IA cria pelo prompt de edição (e também pode mandar já no
primeiro JSON, campo `graficos`), ou crie à mão: 📊 Gráfico no cursor /
duplo clique na faixa. Dados no painel: uma linha por item, "rótulo: valor".

## Efeitos que faltavam do JSON (v75)

Conferido contra o `darkplanner.json`: transições (200), efeitos (28),
entradas/saídas (37), filtros (74), destaques (207) e cenas já estavam todos.
O que faltava — agora implementado:

* **Entradas específicas dos destaques** (31 que caíam num fade simples):
  cantoneiras que fecham sobre o texto (`doc_mira`, `doc_mira_quadro`,
  `hl_bracket_focus`), linha que varre (`doc_radar`, `doc_scanner`), linha do
  tempo que se desenha com marcos (`doc_tempo*`, `v2_cartela_epoca`), "A vs B"
  com cada lado entrando de um lado e o VS estourando (`doc_vs`, `split`),
  corte seco com clarão (`matchcut`), grade técnica que se desenha atrás
  (`v2_grade_cinema*`, `v2_grade_lateral*`, `v2_grade_tecnica`, `v2_blueprint`),
  pino de mapa que cai e quica (`v2_pino_mapa`) e "assenta" (`assenta_italico`,
  `gancho`, `v2_ano`, `v2_pergunta`, `doc_termo`, `hl_value_callout`).
* **Saídas** `slide`, `wipe` e `riscar` (antes só fade/blur/zoom).
* **Movimento interno**: `brilho` (halo pulsando) e `flutua` (balanço suave).
* **Palavra por batida** (49 estilos): cada palavra entra no tempo da fala
  com o jeito do estilo (pop, punch, blur, flip, letras, acende…).
* **Tratamentos v2** que não tinham fundo: preto e branco, granulado, TV
  antiga (CRT), filme queimado, névoa, facho de luz, véu lateral, espaço
  negativo, jornal, mancha de tinta, moldura de galeria e mapa — também
  escolhíveis em 🖼 Fundo.
* **Sons dos destaques**: `porBatida` (um som por palavra), `tipagem`, `cama`
  e `rolagem` (som que acompanha desde o início).

Ainda **não** feito: os 9 **Templates Avatar** (apresentador num círculo,
janela, dupla, molduras, grades) — precisam de um vídeo do apresentador.

## YouTube copiar/colar com prévia, preencher inteligente e qualidade (v74)

**Copiar o link do YouTube de um trecho pro outro.** No painel do trecho:
**📋 Copiar** (link + tempos) → selecione outro trecho → **📥 Colar**. Abre a
janela **🎬 Prévia / ajustar tempo** com o player do YouTube: **⏺ Início =
agora / Fim = agora** (tempo atual do player), **−0,5s / +0,5s**, **▶ Tocar o
trecho** (para sozinho no fim), **⇥ Duração do trecho** e **⬇ Usar neste
trecho**. O vídeo já baixado é reaproveitado (cache por vídeo), então colar o
mesmo link em outro trecho só corta de novo. Na aba YouTube, **📋 Listar os já
usados** põe todos os links na caixa de texto pra repetir em outros trechos.

**✨ Preencher inteligente** (Bordas, global ou por trecho): detecta barras
pretas que já vêm DENTRO do vídeo (comum em vídeo antigo/baixa qualidade do
YouTube), corta elas, aumenta sem distorcer (lanczos + nitidez leve quando a
fonte é pequena) e preenche a tela — corta o mínimo se a proporção é parecida,
ou põe o próprio vídeo desfocado atrás se for bem diferente (4:3, vertical).
O 🔎 Zoom de antes não tirava barra embutida. Aumentar a resolução não cria
detalhe que o vídeo não tem.

**Qualidade na exportação.** **🎬 Montar vídeo** agora pergunta a
**resolução** (480p a 2160p) e a **qualidade**: Normal (como sempre), Alta
(menos compressão em todas as etapas + passe final CRF 18) ou Máxima (CRF 15,
arquivo maior). Em 1440p/2160p os links do YouTube colados baixam na melhor
qualidade disponível.

## Fundos escolhíveis + links do YouTube em texto (v73)

**Fundo dos destaques de texto.** Cada estilo do DarkPlanner traz um fundo
(faixas retas de cinema, grade ondulada, grade 3D, banho de cor, cena
desfocada, vinheta…). Agora dá pra trocar: clique no destaque → **🖼 Fundo e
cor** e escolha numa grade de miniaturas — Simples (sem fundo, escurecer,
vinheta, gradiente, painel, clarão), Imagem desfocada (cena desfocada, desfocada
e escura, desfocada com tom de cor), Linhas e grades (faixas, linhas retas,
grade reta, linhas onduladas, grade ondulada, grade 3D, pontos) e Cor (banho de
cor, gradiente de cor, cor sólida, papel). Cada um com **cor** e
**intensidade**, e também a **cor do texto/acento** só daquele destaque.
Na aba 💬 Destaques, **🖼 Fundo dos destaques** define o padrão do projeto
(vale pra todos que não têm um próprio) e aplica nos selecionados/em todos.
Em fundo claro (papel, cor clara) o texto fica escuro sozinho.

*Correção:* fundos de imagem (faixas, grades, gradiente) às vezes não
apareciam em destaques depois dos primeiros segundos — corrigido.

**Fundo das cenas/takes.** No painel da cena, **🖼 Fundo** mostra os do
template e mais: mídia desfocada (com ou sem tom de cor), a própria mídia,
texturas, clarão/luz, gradiente/cor sólida, linhas, grade, ondas, grade
ondulada, grade 3D e pontos — com a cor que quiser.

**Links do YouTube como texto.** Aba 🎬 YouTube → **🔗 Colar links com o tempo**,
uma linha por trecho (`3: https://youtu.be/ID 1:35-1:42`, `…watch?v=ID 0:10 até
0:18`, `…?t=95`). Sem número, as linhas vão pros trechos selecionados na
timeline (ou do atual em diante); sem o fim, usa a duração do trecho.
**👁 Conferir** mostra como foi lido; **⬇ Baixar e pôr nos trechos** baixa cada
vídeo uma vez só, corta e coloca. No painel do trecho também tem o campo
**🔗 Link do YouTube + tempo**.

## Seleção múltipla na timeline + direção completa (v72)

**Selecionar vários itens:** clique e arraste no fundo vazio da timeline
(laço amarelo; perto da borda ela rola sozinha). **Ctrl/Shift+clique** soma
ou tira um item, **Ctrl+A** seleciona tudo, **Esc** limpa, **Delete** apaga os
destaques/sons/overlays selecionados. Com vários selecionados:

* clicar numa transição, efeito, animação ou overlay das abas aplica em todos;
* arrastar um destaque/som/overlay selecionado move o grupo junto;
* o painel da direita tem: aplicar a direção **só nesses trechos**, mover o
  grupo pro cursor, corte seco / global nas emendas, tirar efeitos, tirar cenas.

**Aplicar direção** agora usa tudo o que a predefinição tem, de acordo com os
pesos: templates, transições, movimento, overlays, entradas/saídas, filtro,
cores, legenda e **destaques de texto** (marcado por padrão; kit e densidade
da predefinição). Cada clique sorteia uma semente nova = uma edição
diferente; marque **🔒 repetir** pra refazer exatamente a mesma.

## Predefinições próprias (perfis de direção) + paletas salvas (v71)

Além das 4 do sistema (Padrão, Documentário clássico, Cinema premium, Cortes
dinâmicos), dá pra criar as suas no Estúdio → 🎨 Direção → **＋ Nova** (ou
**⧉ Duplicar** uma do sistema / **✎ Editar** uma sua). O editor segue o do
DarkPlanner — eixos à esquerda, cada um com % e os itens marcados (com peso):

* **Templates**, **Transições**, **Movimento** (câmera, só foto), **Filtros**,
  **Animações** (entrada), **Saídas**, **Overlays** (eixo próprio: entram nos
  trechos sem movimento) — galerias com miniatura/prévia, busca, "✓ Do meu kit".
* **Destaques**: densidade + estilos permitidos (vazio = kit do projeto).
* **Legenda**: estilo que vem junto (leva a config atual da aba Legendas).
* **Cor** (3 modos): *Cor original de cada destaque* · *Cor personalizada da
  predefinição* (escolhe a cor, os tons derivam dela; dá pra partir de uma
  paleta pronta ou sua) · *Cor selecionada no projeto*.
* **Ritmo** e **Universo**: *estrita* (só o que marcar) ou *catálogo inteiro
  onde eu não marcar*.

As suas aparecem no seletor "Minhas predefinições"; **Aplicar direção** usa
todos os eixos (inclusive paleta e legenda; ↩ Desfazer volta tudo) e a caixa
"Também sugerir destaques" roda o motor de destaques com o kit dela. A IA do
prompt também pode escolher uma predefinição sua pelo id.

Em 🎨 Cores do projeto, **💾 Salvar como minha paleta** guarda a paleta atual
(com ★ na lista; × apaga). Tudo fica em `predefinicoes_usuario.json` na pasta do
site — vale pra todos os projetos (rotas `/predefinicoes` e `/paletas`).

## Galerias com miniatura + kit "★ Minha direção" (v70)

- Os 207 destaques agora aparecem como na biblioteca do DarkPlanner: miniatura de verdade (renderizada com o texto de exemplo
  de cada estilo), por categoria com contagem ("ABERTURA & CAPÍTULOS · 16"…); passe o mouse e toca a animação (gerada na 1ª vez).
- Aba **🖼️ Biblioteca**: **Filtros** (74, a mesma foto com cada filtro), **Animações** (37 entradas/saídas + 12 movimentos de câmera,
  com prévia em vídeo) e **Overlays** (15 atmosferas com prévia). Clique aplica no trecho selecionado (Shift+clique = saída),
  ou arraste até a timeline; o filtro vale pro vídeo todo.
- **✓ Marcar kit** (Biblioteca, Destaques e Transições): o que você marca vira a direção **★ Minha direção** (aba Direção) e o
  "Sugerir automaticamente" dos destaques passa a usar só os estilos marcados.
- Miniaturas em `assets/darkplanner/galeria` (dá pra regerar com `python dp_galeria.py`).
- Montagem mais rápida com muitos destaques de grade/gradiente (uma entrada por imagem de fundo, não uma por destaque).

## Cores do projeto + legendas com karaokê (v69)

- **🎨 Cores do projeto** (aba Direção) — o colorSystem do DarkPlanner: primária, secundária, acento e os tons claro/vivo/médio/escuro
  da primária; 12 paletas prontas ou cor livre; "derivar da primária"; modo **Paleta do projeto** (tom sobre tom) ou **Automático**
  (cada estilo com as suas cores); escolha onde vale: cenas (rótulos, VS, aspas, linhas, fundos coloridos, clarão), destaques e
  textos, legendas e transições de luz (leaks, burns, brilho). Cor neutra nunca é trocada. A IA também pode mandar `"paleta"`.
- **📝 Legendas** (aba nova no Estúdio): usa o **.srt do zip** (tempo de cada palavra estimado dentro do bloco pelo tamanho dela)
  ou as palavras do Whisper. Estilos: Seguir texto, Caixa, Contorno forte, Cinema, Faixa colorida e **karaokê** Clássico,
  Destaque (caixa medida com a própria fonte), Pop, Palavra única e Preenchimento. Posição, tamanho, fonte (as do DarkPlanner),
  palavras por linha, maiúsculas, cores (ou a da paleta). **Legenda sob templates** e **sob destaques**: Automático / Manter /
  Ocultar, com ajuste por cena e por destaque. Prévia no monitor; o vídeo legendado sai como `<job>_legendado.mp4`.

## Sons do editor original + textos animados avulsos (v68)

- **Sons**: os 124 arquivos do `audios.zip` (eram .mp4) viraram áudio `.m4a` em `assets/sons/<categoria>/` — cada pasta do zip é
  uma categoria (transições, variados, passagem, cinema, impacto, pop, foley, digital, fogo, vento, respiro). `assets/sons/sons.json`
  guarda duração e onde fica o PICO de cada som (o pico é alinhado com o evento).
- **Aba 🔊 Áudios** no Estúdio: ouvir, pôr no cursor ou arrastar até a nova faixa **Sons** da timeline (mover, volume, trocar, remover).
  Sons automáticos (liga/desliga + volume): **transições** (cada uma ganha o som que combina — Film burn 4 → "Film burn 4",
  shutter → "obturador mecânico", glitch → "Digital", leaks → cinema…; dá pra trocar ou silenciar no losango), **cenas/takes**
  (os sons que o template pede no JSON: câmera, whoosh, respiro…) e **destaques** (digitação no selo de ano, clicks, hits…).
  Os nomes do JSON (camera_1, woosh_24, wh_cinema_4, pop_click_2, typing_6…) foram casados com os arquivos pelo número/família;
  matchcut_* e musica_doc não vieram no zip e usam o som mais parecido. Os sons são mixados com a narração antes do mux.
- **Textos avulsos**: aba **🔤 Textos** no Estúdio (qualquer texto, em qualquer um dos 207 estilos, no cursor, com posição, fundo do
  estilo opcional e som) e a página **/textos** ("🔤 Textos animados" no rodapé) que exporta só o texto animado como vídeo:
  fundo preto, verde (chroma key) ou TRANSPARENTE (MOV ProRes 4444 ou WEBM VP9), 16:9 / 9:16 / 1:1.

## DarkPlanner completo: Direções, efeitos, transições, filtros e destaques (v67)

Agora TODO o `darkplanner.json` está no site (guardado em `assets/darkplanner/darkplanner.json`):

| Do JSON | No site |
|---|---|
| 4 Direções (Padrão do sistema, Documentário clássico, Cinema premium, Cortes dinâmicos) | Aba **🎨 Direção** no Estúdio: aplica tudo de uma vez com as % e pesos do preset, ritmo e semente (mesma semente = mesma edição), "manter o que já escolhi" e desfazer. `dp_direcao.py` |
| 74 filtros de cor | Filtro GLOBAL do vídeo (regra: um por vídeo) — aba Direção. `dp_visual.py` |
| 28 efeitos | Câmera (zoom rápido, zoom+pan, giro, respiro… só em foto) e atmosfera (luz vazando, poeira, neblina, bokeh, scanlines, sujeira, facho, véu dourado, partículas, galáxia, aberração, tremulação) — aba Efeitos / painel do trecho |
| 37 entradas + 37 saídas | Gesto no começo/fim do trecho (pop, punch in, spin, tv on, shockwave, spring, slingshot, flip 3D, fumaça…). Saída só quando a emenda seguinte é corte seco |
| 201 transições | Todas na aba Transições (com busca), como `dp:<id>`: nativas do ffmpeg ou recriadas (film burn, light leak, splash, glitch, estática, coração, estrela, polka, blocos…) |
| 207 destaques de texto | Aba **💬 Destaques** + faixa na timeline: manchetes, selos de ano/número/%/dinheiro, citações, lower thirds, capítulos, marca-texto, carimbo, digitação, contador… Fontes do DarkPlanner (Anton, Playfair, Cinzel, Bebas, Garamond… OFL, em `assets/fonts/dp`). "✨ Sugerir automaticamente" acha anos, %, valores, datas, contagens e frases de impacto respeitando o orçamento por papel do JSON. Um destaque por vez; o tempo segue a fala |

A IA também pode pedir tudo isso no JSON (`direcao`, `filtro`, `highlights` na raiz; `efeito`, `entrada`, `saida`, `transition` por trecho).

## Cenas e takes do DarkPlanner (v66)

Os templates de CENA do DarkPlanner Studio (message.json) entraram no site — catálogo em
`assets/darkplanner/cenas_catalogo.json`, render em `cenas_dp.py`:

- **149 cenas/takes**: Molduras (Editorial I–VI, Técnica, Placas, Clarão, Vibrante, Janela Desfocada/Esmaecida),
  Retratos, Frente & Fundo, Multitake/Multigrade (Dossiê, Confronto, Antes & Depois, Tríade, Pilha, Cascata,
  Leque, Escada, Painéis), Editorial (Citação, Nome, Comparação, Triplo, Ficha, Perfil, Mosaico, Artigo),
  Cinema 50 (C30/C50), Referências e Introdução Documentary / Text Match Cut / Whoosh Studio.
- **Regra dos slots** igual ao DarkPlanner: um template de N slots aplicado no trecho X cobre X e os N-1
  seguintes — cada mídia vira um take que entra no tempo da própria fala; os anteriores continuam na tela.
  As emendas dentro da cena não têm transição.
- **Textos**: campos fixos ("TÓPICO", "CAPÍTULO", "ANTES/DEPOIS", "VS"…) são preenchidos com o roteiro (rótulo
  de fábrica não aparece). Templates que mostram a FALA escrevem o que é dito em cada take (com o tempo das
  palavras do Whisper) e a legenda queimada some nesse intervalo — nunca duplica.
- **Fundos** gerados (concreto, grão, clarão, grade de pontos, cantoneiras, registro, papel, película, cores "Auto",
  vidro = a própria mídia desfocada) e **movimentos** de entrada (assenta, desliza, ergue, revela, queda…).
- **Shutters** viraram transições: 📸 Match Cut, Lâminas, Filme de contato, Dossiê, Foco óptico, Final de impacto,
  Deslocamento lateral, Foco revelado, Pulso.
- **Estúdio**: aba **🎬 Cenas** (miniaturas, busca, filtro por nº de trechos; clique ou arraste até o trecho),
  faixa **Cenas** na timeline, painel com fundo/textos/mostrar fala, prévia aproximada no monitor.
- **IA**: o prompt lista os templates automáticos (quando usar, duração, campos) e o JSON pode trazer
  `"template"` e `"template_campos"` por trecho (desligável em Configurações: `templates_cena_ia`).
- Não entram: templates de Avatar (o site não tem avatar) e os sons do DarkPlanner.
- Correção: as transições próprias (persianas, xadrez, íris, cata-vento…) estavam INVERTIDAS — começavam mostrando o
  próximo trecho, voltavam pro anterior e cortavam seco.

## Imagens AVIF/WebP + botão "🔧 Corrigir automaticamente" (v65)

Erro real: `Trecho 6: Não consegui ler a duração de '...trecho5_02511f.avif': 'duration'`. Os buscadores de imagem
servem muito .avif/.webp, e .avif não estava na lista de imagens — o arquivo era tratado como vídeo. Agora:
- toda imagem que não é JPEG/PNG de verdade (AVIF, WebP, HEIC, TIFF, GIF...) é convertida pra .jpg assim que é
  baixada e de novo antes de ir pro ffmpeg (Pillow ≥ 11.3; se faltar, o ffmpeg converte);
- quando a montagem falha num trecho, os dois editores mostram **🔧 Corrigir automaticamente**: converte a
  imagem, repara um vídeo ilegível, ou (se não der) volta o trecho pra busca automática, simplifica o termo ou
  troca a foto de um banco que precisa de chave pros buscadores — e diz o que fez;
- trocar a mídia do trecho que falhou já tira o aviso vermelho.

## Estúdio: editor novo com timeline arrastável (v63)

O editor agora abre no **Estúdio** (tela escura, no estilo de editor de vídeo): biblioteca/abas à esquerda, monitor
no meio, propriedades à direita e timeline embaixo. O editor em lista de antes continua em "Editor clássico"
(link no topo; a escolha fica lembrada). Os dois mandam os mesmos campos pra montagem, então nada se perdeu.

- **Timeline** com faixas Vídeo/Foto (miniaturas), Texto, Overlays, Cortes e Narração (forma de onda); zoom;
  clique na régua pra posicionar; **arraste as emendas** pra mudar onde um trecho termina (o vizinho acompanha,
  sem buracos na narração); **✂️ dividir no cursor** (tecla S) e **🔗 juntar com o próximo**.
- **Transições**: losango em cada emenda (verde = global, amarelo = própria). Aba 🎞️ com os 68 modelos
  (com miniatura animada): arraste até um losango, ou selecione e clique; "aplicar em todas"; ▶ ver a transição.
- **Efeitos** (aba ✨): zoom in/out, pan nas 4 direções, foto parada, fade da foto, desfoque, bordas, animação
  do texto — arraste até um trecho ou clique com o trecho selecionado.
- **Mídia**: envie arquivos pra biblioteca e arraste até um trecho. **Buscar**: opções do banco pro trecho
  selecionado + "Usar". **YouTube**: o mesmo painel (minimizar, termo original, 1º automático).
- **Overlays**: arraste pra mudar o tempo, puxe as pontas, edite texto/posição/tamanho; adicionar texto ou
  imagem/vídeo por cima. **Cortes**: marcadores na timeline, com envio de arquivo e atalho pro YouTube.
- **Monitor** com prévia aproximada: Ken Burns, fades, texto com estilo/animação, overlays e a transição entre
  trechos (o resultado exato sai na montagem). Espaço toca/pausa (sincronizado com a narração).
- **💾 Salvar** (Ctrl+S) guarda sem montar; **🎬 Montar vídeo** monta. Aviso antes de sair com alterações não salvas.

**Transições — o que foi corrigido:** com muitos trechos, o comando do ffmpeg passava do limite de tamanho do
Windows e a montagem com transição falhava; agora o grafo vai num arquivo e os trechos são juntados em lotes de
20. As entradas são igualadas (fps/base de tempo) antes do xfade, e se o ffmpeg recusar alguma transição o vídeo
sai com corte seco (sincronizado) em vez de a montagem inteira falhar.

## Editor mais prático + galeria de projetos (v62)

- **"✅ Usar esta no trecho"**: depois de "Buscar e ver opções", clique num resultado e no botão. Foto: é
  baixada na hora (se o site bloquear a original, usa a miniatura do buscador) e vira o arquivo do trecho.
  Vídeo: fixa o post (Pexels/Pixabay/Mixkit) ou usa o link direto quando o banco entrega um.
- **Animação de imagem** sempre visível nos trechos de foto: botões rápidos (zoom in/out, pan nas 4 direções,
  parado) + foco horizontal/vertical. A escolha fica salva entre confirmações.
- **Transições no editor**: uma global pro vídeo inteiro (ou "a das Configurações") e, em cada trecho,
  "Transição para o próximo trecho" (ou "usar a global"), com duração própria. Corrigido no caminho: com
  transição ligada, o vídeo ficava mais curto que a narração (cada transição "comia" o tempo dela) e o fim
  da narração era cortado — agora cada clipe ganha um "rabo" do tamanho da transição e tudo fica sincronizado.
- **Painel do YouTube**: cada pedido minimiza sozinho depois de escolhido (clique no título pra abrir/alterar);
  "↩ Termo original" volta pra busca que a IA sugeriu; "⚡ Usar o 1º" escolhe o 1º resultado do começo.
  Caixa "Se eu não escolher, usar automaticamente o 1º resultado" (ligada por padrão): na montagem, trecho
  do YouTube sem escolha usa o 1º resultado (se não baixar, o 2º, o 3º) do segundo 0 até a duração do trecho.
- **Galeria de projetos** (`/jobs`, antes "Histórico"): cartões com capa, nome editável, "Editar de novo"
  pros concluídos, e **🗑 Apagar projeto e arquivos** (apaga a narração, clipes, imagens, cortes do YouTube e os
  vídeos finais do servidor; não deixa apagar enquanto algo está rodando). Os projetos agora voltam depois
  de reiniciar o servidor (lidos de `jobs/<id>/state.json`).

## YouTube como provedor + painel "Vídeos do YouTube" no editor

Novo provedor **`youtube`** (desmarcado por padrão na tela de upload). Quando marcado, o prompt explica à IA que
ele serve pra FILMAGEM REAL específica (trailer, cena de anime/filme/jogo, entrevista, discurso, lance esportivo,
evento noticiado) e que a `query` é o termo que se digitaria na busca do YouTube (no idioma do vídeo, com nomes
próprios). Os cortes reais (`cutaway_suggestions`) ganharam um campo opcional `query` com o mesmo papel.

Escolher QUAL trecho de um vídeo longo usar não dá pra automatizar bem, então o site faz a parte chata e deixa a
escolha com você:

1. Assim que a resposta da IA é colada, **todos os termos do YouTube** (trechos com `"provider": "youtube"` +
   cortes reais) começam a ser pesquisados em segundo plano (yt-dlp, sem navegador), junto com as prévias.
2. No editor, logo acima de "Confirmar e montar o vídeo", aparece o painel **🎬 Vídeos do YouTube pedidos pela
   IA**: um bloco por pedido, com o termo (editável + "Buscar de novo") e os resultados já prontos.
3. Clicando num resultado, abre o player do YouTube ali mesmo; "⏱ início = agora" / "⏱ fim = agora" pegam o
   tempo do player, "▶ ver o trecho" toca só a faixa marcada. Num trecho, o fim é preenchido sozinho com
   início + duração do trecho.
4. "✅ Usar esse trecho" baixa e corta em segundo plano; o clipe vira o arquivo do trecho (igual a um upload
   manual) ou o clipe do corte real. Dá pra trocar depois.

Trecho `youtube` sem vídeo escolhido não trava a montagem: cai pros bancos normais (ordem de prioridade).
Rotas: `GET /job/<id>/youtube/itens`, `POST /job/<id>/youtube/item/<item>/buscar|usar|limpar` (o status do
download continua em `/cutaway-youtube-status/<id>`). O botão antigo de busca dentro de cada corte virou um link
pro painel. 22 testes em `test_youtube_painel_app.py`.

## Buscadores de imagem: Busca de Imagens Unificada, 1 navegador por buscador

Os 4 buscadores de imagem (Bing/Brave/Yandex/Startpage) agora usam a **Busca de Imagens Unificada**
(`toolkit/unified_images/`, os motores melhorados — várias buscas na mesma aba, downloader que confere pelos
bytes se é imagem e tenta a thumbnail/proxy quando a original falha). Os motores antigos do toolkit
(`toolkit/*_image_api.py`) foram removidos; `bing_api_client.py` & cia. viraram cascas finas sobre
`toolkit/buscador_imagens_unificado.py` (mesmos nomes de classe de antes).

Como as imagens são buscadas agora (prévia e montagem):

- **Um navegador por buscador, não um por trecho.** Todos os trechos de um buscador são pesquisados de uma vez,
  um termo atrás do outro na mesma aba. Antes, cada trecho abria o próprio Chromium (vários ao mesmo tempo).
- **Pega a 1ª imagem do resultado e baixa.**
- **Se um buscador não achar o termo (ou a imagem não baixar), o termo vai pro próximo buscador**, até baixar ou
  acabar a lista (o buscador escolhido pela IA vem primeiro). Se nenhum achar, tenta uma vez uma versão mais
  simples do termo (a última palavra).
- A prévia já deixa a imagem baixada; a montagem reaproveita o arquivo sem abrir navegador nenhum (cache por
  termo no job). Termo editado no editor = busca nova só pra ele.
- Configuração nova em `/settings`: rodar os buscadores ao mesmo tempo (padrão: no máximo 1 navegador por
  buscador) ou um de cada vez (1 navegador aberto no total, menos RAM).
- O modo "buscadores de imagem" no prompt (confirmar termos antes) também ficou em lote: cada buscador recebe
  todos os termos pendentes num navegador só.
- O seletor de banco de um trecho de FOTO no editor agora lista os bancos de foto de verdade (antes listava só
  os de vídeo, e confirmar trocava um trecho do Bing pra Pexels sem avisar).

Precisa de `fastapi` e `uvicorn` instalados (os motores importam no topo do arquivo) — já estão no
`requirements.txt`. 22 testes em `test_busca_imagens_lote.py` (sem navegador/rede).

## Buscar no YouTube pra um corte sugerido pela IA, direto no editor

Os "Cortes reais sugeridos pela IA" (`cutaway_suggestions`) já existiam — a IA identifica um momento que merece
uma filmagem real específica (ex: "Gojo usando Expansão de Domínio") e antes só dava pra resolver fazendo
upload manual de um arquivo. Agora cada corte tem um botão "🎬 Buscar no YouTube" que abre uma busca (sem
precisar de chave de API — reaproveita `youtube_clipper.buscar_videos_youtube`, a mesma função já usada pela
ferramenta "Cortar do YouTube"), já com o termo pré-preenchido a partir da descrição que a IA deu pro corte.
Escolhe um resultado, ajusta início/fim do trecho em segundos, e o site baixa + corta só aquele pedaço em
segundo plano (reaproveitando `baixar_video`/`cortar_trecho`) — ao terminar, o corte já fica resolvido, do
mesmo jeito que ficaria se você tivesse subido o arquivo manualmente.

Duas rotas novas (`/job/<id>/cutaway/<id>/youtube-buscar` e `/job/<id>/cutaway/<id>/youtube`, com
`/cutaway-youtube-status/<id>` pra acompanhar), JS novo em `edit_segments.html`. Bug real que achei e corrigi
no caminho: o botão de abrir/fechar a busca (`toggleCutawayYoutube`) usava `!div.style.display` como parte da
condição, que em JS é `true` tanto quando o display nunca foi setado QUANTO quando já está em `''` (string
vazia, que é "mostrando") — ou seja, depois de abrir uma vez o botão nunca mais fechava. Peguei isso só porque
testei a lógica de verdade num DOM simulado em `node`, não só a sintaxe.

10 testes novos de integração (rotas, mutation-check na validação de fim/início incluindo o caso de fronteira
fim==início) + 14 verificações num harness de DOM simulado em `node` (busca, escolha de vídeo, corte, e os
dois caminhos do polling — sucesso e erro).

## Trocar os bancos de mídia depois de transcrever (sem re-transcrever)

Na página do prompt (passo 2, `/job/<id>/prompt`), depois de ver o prompt montado, dá pra abrir "Mudou de
ideia sobre os bancos?" e marcar outros bancos de mídia diferentes dos que foram escolhidos antes de
transcrever. O prompt é remontado na hora reaproveitando a transcrição já guardada em `job["segments"]` —
não chama o Whisper de novo (a etapa mais lenta do processo). Pensado pra quando você só percebe depois de
ver o prompt que devia ter marcado outro banco.

## Upload de .zip (áudio + legenda) — pula a transcrição

No upload principal (`/transcribe`), o campo de áudio agora também aceita um `.zip` — exatamente o formato que
o Gerador de Voz baixa (áudio + `legenda.srt` juntos). Quando detecta um `.zip`, o site extrai o áudio, lê o
`.srt` de dentro (novo `legendas.parse_srt()`) e usa esses segmentos direto — **sem chamar o Whisper**, pulando
a etapa mais lenta do processo inteiro. Se a legenda `.srt` estiver quebrada, ou faltar áudio/`.srt` no zip, o
erro aparece na hora, sem criar job nenhum. Se a pessoa também pediu legenda palavra-por-palavra nesse mesmo
upload, ela é desligada automaticamente (um `.srt` comum não tem timestamp por palavra, só por bloco) — com um
aviso visível na página do prompt explicando por quê, em vez de travar ou fingir que funcionou.

9 testes novos de integração + 10 novos do parser em si (`parse_srt`, com round-trip contra `gerar_srt`),
mutation-check confirmando que a transcrição é mesmo pulada.

## Dois gaps reais encontrados numa revisão geral (nenhum dos dois era da parte nova)

1. **Histórico de jobs sem link pros status intermediários.** `/jobs` tinha uma coluna "Ação" vazia pra
   qualquer job parado em `aguardando_termos_wikipedia`/`buscando_termos_wikipedia` (e agora os dois
   equivalentes de buscadores) — sem jeito de voltar pro fluxo a partir do histórico. Corrigido pros 4 status
   intermediários (Wikipedia + buscadores). 13 testes novos (`test_jobs_history.py`), parametrizados por todo
   status que a tela conhece.

2. **Os 4 buscadores novos ignoravam a config "Ocultar o navegador".** Essa opção em Configurações promete
   afetar "TODOS os processos" (scraping, captura de página, Google Flow), mas o Bing/Brave/Yandex/Startpage
   ficavam sempre com `headless=True` fixo, não importa o que estivesse marcado. Corrigido em
   `ClientFactory.get_photo_client` — agora deriva `headless` de `browser_visible`, igual já fazia pro Flow.
   9 testes novos (`test_client_factory_headless.py`).

## Modo "buscadores de imagem" no prompt — mesma ideia da Wikipedia, pros 4 novos

Checkbox nova na tela de upload: "🔎 Este vídeo usa buscadores de imagem (Bing/Brave/Yandex/Startpage)". Mesmo
fluxo de duas rodadas que o modo Wikipedia já tinha: depois de transcrever, o site pede pra IA sugerir termos
específicos (uma pessoa, marca, produto, lugar exato — coisa demais pra um banco de estoque genérico), você
cola a resposta, e o site PESQUISA DE VERDADE esses termos nos buscadores marcados antes de montar o prompt
principal — só os termos que realmente têm resultado entram no prompt final, como garantidos. Se os dois
checkboxes (Wikipedia e buscadores) forem marcados juntos, o Wikipedia tem prioridade (roda só uma etapa de
confirmação por vez). Novo módulo `buscadores_enrichment.py`, nova função `build_buscadores_search_terms_prompt`
e novo parâmetro `buscadores_confirmados` em `build_prompt` (prompt_builder.py), novo par de rotas
`/job/<id>/termos-buscadores`, novo template `termos_buscadores.html`.

Bug real encontrado e corrigido no caminho (não só na parte nova): a caixa de aviso "nenhuma entidade
encontrada" no `prompt.html` aparecia pra QUALQUER job, mesmo um que nunca usou o modo Wikipedia — porque
`job.wikipedia_entidades is not none` em Jinja trata chave AUSENTE como `Undefined`, que não é `None`. Troquei
pra `job.get('wikipedia_entidades') is not none` (e o mesmo pro campo novo de buscadores), que distingue
certinho "nunca usei essa etapa" de "usei e não achei nada".

22 testes novos (9 do módulo de busca isolado, 13 de integração ponta a ponta), com mutation-check confirmando
a prioridade Wikipedia-sobre-buscadores e o filtro de providers.

## 4 novos buscadores de imagem por navegador (Bing, Brave, Yandex, Startpage)

> **Atualizado:** os motores desta seção foram trocados pela Busca de Imagens Unificada (1 navegador por
> buscador, fallback entre buscadores) — veja a seção "Buscadores de imagem: Busca de Imagens Unificada" no topo.

Além do Pexels (API) e da Wikipedia (API), agora tem mais 4 provedores de imagem, todos baseados nos scripts
que o usuário enviou (cada um originalmente um servidor FastAPI + Playwright próprio) — a parte de servidor
HTTP foi removida, ficou só a raspagem em si, chamada direto via `asyncio.run()` de dentro do cliente Python
(sem precisar rodar nada separado): **Bing Images**, **Brave Images**, **Yandex Images** e **Startpage Images**.
Cada um segue a mesma interface de compatibilidade que o cliente da Wikipedia já usa (`search_photos_all`/
`download_photo`, propriedades `.id`/`.sizes`/`.description`/`.author`/`.url`) — o resto do site trata
qualquer um deles exatamente como trataria uma foto do Pexels, sem checagem especial por provedor.

Diferenças entre eles (por causa de como cada script original foi escrito):
- **Bing**: sempre abre o detalhe de cada resultado (a função original não tem um modo mais rápido pra isso)
  — então é o mais lento dos quatro.
- **Brave** e **Yandex**: usam o modo rápido por padrão (`click_details=False`/`inspect_sources=False`) — os
  cards de busca já trazem a URL original decodificada, sem precisar visitar a página de origem.
- **Startpage**: usa `click=True` (o "mecanismo comprovado" que o próprio script original documenta) — não
  arriscamos usar um modo mais rápido que o autor original não testou.

Os 4 vêm **desmarcados por padrão** na tela de upload (igual Wikipedia/Flow) — são mais lentos que os bancos
com API de verdade (Pexels/Pixabay) e dependem de raspagem de navegador, que pode quebrar se o site mudar o
HTML (mesma categoria de risco do Google Flow). 29 testes novos (mockando a função de busca async, sem
navegador/rede de verdade), cobrindo parsing dos resultados, erros de busca/download, e o comportamento
padrão específico de cada um (click_details/inspect_sources/click).

## Legenda (SRT) automática no Gerador de Voz

O **Gerador de voz** avulso (`/gerar-voz`) agora sempre gera uma legenda `.srt` junto com o áudio: depois de
sintetizar a voz, o próprio áudio é transcrito de novo (Whisper, com timestamp por palavra) e a legenda é
montada a partir daí — não depende do motor de TTS informar timing nenhum. Se a transcrição falhar por
qualquer motivo, o áudio continua disponível normalmente (só fica sem legenda dessa vez, com aviso no lugar).

Três formatos de quebra (módulo `legendas.py`), escolhidos nas "Opções avançadas de legenda" da tela:
- **Por tempo** — divide em blocos de duração alvo (3-8s, ajustável); pensado pra sincronizar com vídeo
  gerado em blocos (você cria os prompts por bloco e depois sincroniza com os vídeos).
- **Legenda** (padrão) — quebra no ritmo da fala, respeitando pausas naturais entre palavras; leitura
  confortável, recomendado pra maioria dos casos. Máximo de palavras por linha ajustável (padrão 5).
- **Por palavra** — toda linha com a MESMA quantidade de palavras, sem variar pelo ritmo da fala; visual
  uniforme. Quantidade ajustável (padrão 5).

Sem mexer nas opções avançadas, sai no formato "Legenda" com os padrões acima — a seção só existe pra quem
quer um formato diferente. Depois de pronto, dá pra baixar o áudio, a legenda, ou os dois juntos num `.zip`
(montado sob demanda, sem custo se ninguém pedir).

## Como funciona (as 4 peças)

1. **`whisper_transcribe.py`** — transcreve o áudio com Whisper (local,
   sem chave de API), devolvendo os trechos falados com timestamps.

2. **`prompt_builder.py`** — a peça que faltava: pega a transcrição e
   monta o texto do prompt pronto pra colar em outra IA. O prompt pede
   pra IA primeiro entender do que o vídeo trata como um todo (tema,
   tom, público) antes de escolher os termos — pra manter uma linha
   visual coerente entre os segmentos, em vez de tratar cada trecho
   isoladamente. Pede de volta um JSON no formato:
   ```json
   {
     "segments": [
       {"start": 0.0, "end": 6.8, "provider": "pexels", "query": "sunrise over mountains"},
       {"start": 6.8, "end": 13.5, "provider": "pixabay", "query": "person typing on laptop", "on_screen_text": "3 passos"}
     ],
     "soundtrack_suggestion": "instrumental calmo e inspirador"
   }
   ```
   `on_screen_text` (por segmento) e `soundtrack_suggestion` (raiz) são
   opcionais — a IA só inclui quando fizer sentido. **Importante:**
   esses dois campos já são capturados e validados, mas ainda **não são
   renderizados** no vídeo final (isso é a próxima fase — texto na tela
   e trilha sonora de fundo de verdade). Por enquanto, o texto sugerido
   fica salvo em `video_segments` e a sugestão de trilha aparece na
   página de resultado, pra você adicionar manualmente se quiser. O
   formato antigo (lista de segmentos sem o envelope, sem esses dois
   campos) continua funcionando normalmente — validado com teste.

   Também valida a resposta colada (`parse_ai_response`): confere que é
   JSON válido, que os campos existem, que os segmentos cobrem o áudio
   inteiro sem buracos, que os provedores são válidos, que não vêm
   segmentos demais nem segmentos curtos demais — com mensagens de erro
   claras pra mostrar na tela se algo vier errado.

3. **`video_assembler.py`** — pega os segmentos validados, busca e
   baixa um vídeo pra cada um usando o toolkit (pasta `toolkit/` —
   é exatamente o mesmo toolkit dos 6 provedores que a gente já
   construiu), ajusta cada clipe pra durar exatamente o tempo do seu
   segmento (repete em loop se for curto, corta se for longo), e
   concatena tudo sincronizado com o áudio original via `ffmpeg`.

4. **`app.py`** — o site Flask que junta as três peças acima numa
   sequência de páginas: upload → prompt pra copiar → colar JSON →
   barra de progresso → download do vídeo final.

5. **`site_config.py`** — configuração central do site, editável na
   página `/settings` (veja a seção "Página de configurações" abaixo):
   proporção do vídeo, ordem de preferência das fontes, visibilidade do
   navegador, e mais.

## Página de configurações (`/settings`)

Tudo que antes era fixo no código agora é configurável direto no site,
persistido em `site_config.json`:

- **Proporção do vídeo**: `16:9` (paisagem, YouTube normal) ou `9:16`
  (retrato, Shorts/Reels/TikTok). Isso não só muda a resolução de saída
  — também é repassado como filtro de busca pros provedores que
  suportam orientação (Pexels, Pixabay, Mixkit, Magnific), pra já vir
  vídeo do formato certo em vez de sempre depender de cortar/preencher
  com barras.
- **Ordem de preferência das fontes** (lista arrastável): se a fonte
  que a IA escolheu pra um trecho não encontrar nada (nem com os termos
  de busca alternativos), o site tenta automaticamente a próxima fonte
  desta lista antes de desistir do segmento.
- **Qualidade de exportação**: 480p / 720p / 1080p / 1440p / 2160p — a
  largura é calculada automaticamente a partir da orientação escolhida,
  mantendo sempre a proporção correta.
- **Ponto de corte do clipe**: quando o vídeo baixado é mais longo que o
  trecho necessário, de onde cortar — do início (padrão), do meio
  (evita a introdução/fade-in que muitos vídeos de banco têm no
  começo), ou um ponto aleatório (mais variedade se o mesmo vídeo
  aparecer em segmentos diferentes).
- **Magnific só gratuito**: por padrão, a busca no Magnific já pede só
  vídeos gratuitos (nunca premium/com marca d'água) — resolve o
  problema de licenciamento na raiz, em vez de aceitar baixar com marca
  d'água como último recurso.
- **Fallback automático da API do Pexels**: se você configurou
  `PEXELS_API_KEYS` (veja a seção seguinte) e ela falhar de verdade —
  chave inválida, ou todas as chaves em rate limit ao mesmo tempo — o
  site troca sozinho pro scraping por navegador em vez de falhar o
  segmento. Uma vez que isso acontece, os segmentos seguintes já vão
  direto pro navegador (não fica testando a API de novo a cada
  segmento).
- **Visibilidade do navegador**: mostrar a janela do Chrome (útil pra
  depurar) ou rodar headless (padrão, mais leve).
- **Navegador compartilhado entre fontes**: liga a economia de recursos
  mais agressiva do toolkit — um único Chrome pra todas as fontes da
  montagem, em vez de um por fonte (ao custo de perder paralelismo
  entre fontes).
- **Reaproveitar sessão vs. fechar a cada download**: por padrão, a
  mesma aba/sessão do navegador é reaproveitada entre um download e o
  próximo (mais rápido — só muda o termo de busca). A alternativa fecha
  e abre o navegador de novo depois de CADA vídeo baixado — mais lento,
  mas isola cada download por completo.

## Instalação

```bash
pip install -r requirements.txt
```

Precisa também de **`ffmpeg`** instalado no sistema (`ffmpeg -version`
pra conferir) — é usado tanto pelo Whisper (extrair áudio) quanto pela
montagem final do vídeo.

A primeira transcrição baixa o modelo do Whisper (algumas centenas de
MB, dependendo do tamanho escolhido) — isso acontece uma vez só, na
primeira vez que você transcrever algo.

## Rodando

```bash
python app.py
# abre http://localhost:5050
# (porta 5050, não 5000, de propósito — 5000 é a porta padrão do
# servidor local do Anime Pexels Local; usar a mesma aqui causaria
# conflito se você precisar rodar os dois ao mesmo tempo, que é o caso
# normal quando o provedor "animepexels" está em uso. Pra mudar a
# porta deste site, defina a variável de ambiente PORT antes de rodar,
# ex: no Windows, `set PORT=5001 && python app.py`.)
```

## O fluxo, passo a passo

1. Na página inicial, suba o áudio, escolha o intervalo de troca de
   vídeo (padrão 7s — a IA pode ajustar isso pra não cortar frases no
   meio), o idioma, quais bancos de vídeo estão disponíveis, e instruções
   extras opcionais (estilo visual, o que evitar, etc.).
2. O site transcreve o áudio e mostra o prompt pronto — copie ele
   inteiro e cole em outra IA (ChatGPT, Claude, etc.).
3. Cole a resposta da IA (o JSON) de volta no site.
4. Se o JSON tiver algum problema (formato errado, buraco no meio do
   áudio, provedor inválido), a página mostra o erro exato e deixa você
   colar de novo, sem perder o prompt já gerado.
5. Se estiver tudo certo, a montagem começa em segundo plano: pra cada
   segmento, busca no provedor indicado, baixa o primeiro resultado,
   ajusta a duração, e no final concatena tudo com o áudio sincronizado.
6. Uma barra de progresso mostra o andamento; quando terminar, aparece
   o botão de download do vídeo final (`.mp4`).

## Configuração do toolkit (chaves, .env)

A pasta `toolkit/` é o toolkit completo dos 6 provedores, já com tudo
que construímos: scraping por navegador (Chrome/Selenium), a API oficial
do Pexels (com rotação de chaves), manifesto de downloads, metadados,
etc. Pra configurar a API oficial do Pexels (recomendado — evita
Cloudflare e não precisa de Chrome pra esse provedor), copie
`toolkit/.env.example` pra `toolkit/.env` e preencha `PEXELS_API_KEYS`.
A `ClientFactory` de `video_assembler.py` detecta a chave sozinha e usa
a API automaticamente (com fallback pro navegador se ela falhar — veja
a página de configurações acima).

## Testes automatizados

```bash
pip install -r requirements-dev.txt
pytest                          # roda tudo (377 testes, ~330s — arquivos grandes, considere rodar em partes se estourar timeout)
# toolkit/ tem sua própria suíte, testada separadamente (imports
# relativos não resolvem no estilo de coleta do pytest a partir daqui):
#   cd toolkit && pytest test_mixkit_get_video_by_url.py test_pexels_api_client.py \
#     test_browser_session_wait.py test_browser_session_download.py test_pixabay_get_video_by_url.py \
#     animepexels/test_animepexels_client.py
pytest -v                       # com nome de cada teste
pytest --cov=. --cov-report=term-missing   # com cobertura de código
pytest test_prompt_builder.py   # só um arquivo específico
```

Nenhum teste precisa de rede, de Chrome, ou de baixar o modelo do
Whisper de verdade — tudo roda local e rápido:

- **`test_prompt_builder.py`** — geração do prompt e validação da
  resposta colada (JSON malformado, buraco no áudio, provedor inválido,
  segmentos demais, segmento curto demais). Lógica pura, sem I/O.
- **`test_site_config.py`** — carregar/salvar `site_config.json`,
  validação de cada campo (orientação, prioridade de provedores, modo
  de navegador, flags booleanas), e o mapeamento orientação→resolução.
- **`test_whisper_transcribe.py`** — `get_audio_duration()` testado com
  áudio sintético real (via `ffprobe`); `transcribe_audio()` testado com
  o modelo do Whisper mockado (cache de modelo, filtragem de segmentos
  vazios, erro de "nenhuma fala encontrada", erro de pacote não
  instalado) — sem precisar baixar o modelo de verdade.
- **`test_video_assembler.py`** e **`test_video_assembler_robustness.py`**
  — geram clipes de vídeo sintéticos com `ffmpeg -f lavfi` (cores
  sólidas, durações diferentes) e um cliente falso injetado via
  `get_client_fn`, validando: corte/loop de duração, ordem/sincronismo
  com o áudio (confirmado extraindo frames e checando a cor do pixel),
  reaproveitamento de sessão por provedor, fallback de busca, e
  tratamento do vídeo premium do Magnific.
- **`test_video_assembler_config.py`** — a `ClientFactory` e o caminho
  "de verdade" (orientado por `site_config`): sessão compartilhada
  entre provedores vs. uma por provedor, modo `close_each_download`,
  fallback automático da API do Pexels pro navegador (com HTML/erro
  simulado), fallback entre provedores por ordem de prioridade, filtro
  de orientação repassado pra busca, e a orientação `9:16` de fato
  gerando um vídeo vertical 1080x1920 (confirmado com `ffprobe` num
  vídeo real).
- **`test_app_integration.py`** — o pipeline Flask inteiro de ponta a
  ponta via `test_client()`: upload → transcrição em background → prompt
  → colar JSON → montagem → download, incluindo os caminhos de erro
  (JSON inválido, transcrição falhando, montagem falhando, job
  desconhecido) e todas as páginas/endpoints de status.

`conftest.py` tem as fixtures compartilhadas (`synthetic_audio`,
`synthetic_clips`, `sample_pt_segments`) que geram os arquivos de teste
na hora, sem versionar binário nenhum no repo.

`pytest.ini` ignora a pasta `toolkit/` na coleta — ela tem sua própria
suíte de testes (`cd pexels && python test_parsing.py`), já validada
separadamente; misturar os dois estilos de coleta no mesmo `pytest`
causa erro de import.

## Testando sem gastar tempo/rede de verdade

- **`prompt_builder.py`** é 100% lógica pura (sem rede) — dá pra testar
  isolado com segmentos inventados.
- **`whisper_transcribe.get_audio_duration()`** só precisa do `ffprobe`
  (sem rede).
- **`video_assembler.py`** aceita um `get_client_fn` injetável — em
  teste, dá pra substituir por um cliente falso que serve clipes de
  vídeo sintéticos (gerados com `ffmpeg -f lavfi`) em vez de baixar de
  verdade, pra validar a lógica de corte/loop/concatenação/sincronismo
  sem depender de rede.

## Robustez (corrigido após revisão)

- **Reaproveita 1 sessão por provedor**, não uma por segmento — uma
  narração de 20 segmentos usando Pexels via navegador abre 1 Chrome,
  não 20, e todos são fechados ao final (com sucesso ou erro).
- **Um segmento ruim não derruba o vídeo inteiro.** Se a busca não
  acha nada com o termo da IA, tenta automaticamente termos mais
  genéricos (a última palavra do termo, depois "nature background"/
  "background" como último recurso) antes de desistir. Se um resultado
  específico falhar ao baixar, tenta os próximos da lista antes de
  desistir do segmento.
- **Magnific premium não quebra mais o segmento.** Vídeos premium
  (marca d'água) são baixados automaticamente com `allow_watermarked=True`
  em vez de serem recusados — melhor ter o clipe com marca d'água do
  que travar o vídeo inteiro. Se isso não for aceitável pro seu caso de
  uso, ajuste `_download_first_working_result()` em `video_assembler.py`.
- **Transcrição roda em segundo plano**, igual a montagem do vídeo —
  áudio longo não trava a requisição HTTP (evita timeout do servidor).
- **`threaded=True` no `app.run()`** — sem isso, o servidor de
  desenvolvimento do Flask processa uma requisição por vez; com dois
  usuários simultâneos, um trava o outro até nas páginas mais leves,
  mesmo com o trabalho pesado já em background.
- **`interval_seconds` validado** (precisa ser um número entre 1 e
  120) — antes, um valor inválido ou fora do range gerava erro 500 feio
  em vez de mensagem clara.
- **Lista de provedores filtrada** contra a lista real de provedores
  suportados, antes de entrar no job (defesa simples contra alguém
  adulterando o formulário).
- **Limite de segmentos e duração mínima na resposta da IA**
  (`parse_ai_response(max_segments=500, min_segment_duration=0.3)`) —
  um JSON malformado ou uma IA "confusa" não consegue mais disparar
  milhares de downloads de uma vez, nem gerar segmentos absurdamente
  curtos.

## Timeline visual, edição de segmentos, Ken Burns, trilha sonora, legendas e API do Pixabay

Tudo que estava listado como "próxima fase" numa versão anterior deste
README já foi implementado:

- **Timeline visual** (`/job/<id>/edit-segments`): depois de colar o
  JSON da IA, o site busca uma **prévia real** de cada trecho (não só
  o texto do termo) — thumbnail extraído de verdade, forma de onda do
  áudio — e monta uma timeline com camadas (Vídeo / Texto na tela /
  Narração / Trilha sonora), player de áudio sincronizado com uma linha
  de playhead. Clicar num bloco abre a edição daquele trecho.
- **Trocar a fonte de um segmento**: mesmo termo em outro banco (cai
  automaticamente na ordem de prioridade configurada), termo novo,
  upload de um arquivo do seu PC, link direto de um arquivo, ou link de
  um post do Pexels/Pixabay/Mixkit (Magnific e VistaCreate não têm essa
  funcionalidade no toolkit, e o editor avisa isso). Confirmar sem
  editar reaproveita o arquivo já baixado na prévia — não busca de novo.
- **Fotos com efeito Ken Burns**: ao trocar a fonte de um segmento por
  um arquivo/link que seja uma imagem, dá pra escolher zoom in/out e o
  ponto de foco (`ffmpeg zoompan`).
- **Texto na tela renderizado de verdade**: `on_screen_text` agora é
  desenhado sobre o vídeo via `ffmpeg drawtext`, com caixa
  semi-transparente atrás pra legibilidade.
- **Trilha sonora de fundo de verdade**: upload de um arquivo de áudio
  na página inicial, mixado com a narração em volume ajustável
  (`ffmpeg amix`) — repete em loop se for mais curta, corta se for mais
  longa.
- **Legendas "uma palavra por vez"** (estilo Shorts/Reels/TikTok):
  ative o checkbox na página inicial pra pedir timestamps por palavra
  ao Whisper; a montagem gera **duas versões pra baixar** — a normal e
  uma com a legenda queimada no vídeo (`.ass` + `ffmpeg -vf ass=...`).
  Isso não é o karaokê clássico de linha inteira com destaque
  progressivo — é uma palavra de cada vez, sumindo e aparecendo no
  ritmo da fala, como você descreveu.
- **API oficial do Pixabay** (`toolkit/pixabay_api_client.py`): mesmo
  padrão do Pexels — rotação de chaves, fallback automático pro
  navegador se a API falhar. Configure `PIXABAY_API_KEYS` no
  `toolkit/.env` do mesmo jeito que `PEXELS_API_KEYS`.

## Gargalo de performance corrigido: busca de prévias em paralelo

**O problema que você relatou**: colar o JSON e esperar minutos até a
timeline aparecer, em narrações com muitos trechos. A causa raiz: a
pré-busca de prévias buscava e baixava **um trecho de cada vez, em
sequência** — com ~19 trechos e uns 8-10s por busca (comum em scraping
por navegador), isso facilmente passava de 3 minutos.

**Corrigido**: agora busca várias prévias **em paralelo**
(`preview_fetch_concurrency` nas configurações, padrão 3, ajustável até
10). Provei com um teste de tempo de relógio real que 4 segmentos que
levariam ~2.4s em sequência terminam em bem menos que isso quando
buscados em paralelo. Cada busca paralela usa sua PRÓPRIA sessão de
navegador (sessões Selenium não são seguras pra usar de várias threads
ao mesmo tempo) — por isso aumentar muito a concorrência custa mais
memória/CPU (cada uma pode abrir seu próprio Chrome), não é de graça.

Ajuste em `/settings` → "Buscar quantas prévias ao mesmo tempo". Se sua
máquina tiver pouca memória, mantenha baixo (1-2); se tiver bastante e
quiser velocidade máxima com narrações longas, suba pra 5-10.

**Bug encontrado e corrigido nessa mesma mudança**: a lista de prévias
passou a ser pré-alocada (pra manter a ordem certa mesmo com buscas
terminando fora de ordem), o que introduziu posições temporariamente
`None` — três pontos que liam essa lista (`fetching-previews-status`,
o servidor de thumbnail, e o reaproveitamento de prévia no confirm)
quebrariam com um `None` no meio. Corrigidos e testados.

## 6º provedor: Anime Pexels Local (acervo próprio, roda na sua máquina)

Diferente dos outros 5 (todos remotos, via scraping ou API pública),
esse é um banco **local** — um servidor Flask separado (`app.py` do
projeto "Anime Pexels Local") rodando na sua própria máquina, servindo
clipes de anime que você já processou/indexou. O site conversa com ele
por HTTP simples (sem Selenium, sem navegador — é só uma API JSON).

**Pra usar**:
1. O servidor do Anime Pexels Local precisa estar rodando (`python
   app.py` na pasta daquele projeto, normalmente em
   `http://localhost:5000`).
2. Marque o checkbox "animepexels" na tela inicial (ele vem
   **desmarcado por padrão** — diferente dos outros 5 — já que só faz
   sentido quando o conteúdo do vídeo realmente combina com anime).
3. Se o servidor estiver rodando noutra porta ou máquina da sua rede,
   ajuste o endereço em `/settings` → "Anime Pexels Local".

**Diferenças importantes em relação aos outros 5**:
- Termos de busca também em **inglês** (mesma convenção dos outros).
- A IA recebe uma explicação específica no prompt: só deve escolher
  esse banco quando uma cena de anime combinar de verdade com a
  narração (não só porque está disponível) — evita que clipes de anime
  apareçam aleatoriamente num vídeo sobre um assunto sério/genérico.
- Fica **por último** na ordem de prioridade padrão (só entra como
  fallback se os outros 5 falharem).
- Suporta filtro de orientação e duração (igual Pexels/Magnific/
  Mixkit), e tem vídeo tocável direto no Monitor de Origem (é o
  arquivo do seu próprio computador, sem limitação nenhuma).
- **Não** aparece na opção de "colar link de post" manual do editor —
  não existe uma página pública navegável nesse sistema local pra
  copiar um link de lá. A fixação de um resultado específico ainda
  funciona normalmente através da busca ao vivo ("Buscar e ver
  opções"), só não pelo campo de colar link manualmente.
- Erro claro se o servidor não estiver rodando: "Não consegui conectar
  em http://localhost:5000 — o app.py do anime-pexels-local está
  rodando?"

### Prompt dedicado (quando só o animepexels está marcado)

Se você marcar **só** o animepexels (nenhum outro banco junto), o site
usa um prompt totalmente diferente do genérico — pensado especificamente
pra como a busca desse acervo funciona (descrição visual literal +
vocabulário de categorias/sinônimos gerado por IA, não texto livre
qualquer). Principais diferenças:

- Orienta a IA a montar queries **concretas e filmáveis** (uma cena,
  ação ou objeto específico) em vez de conceitos abstratos soltos —
  ex: "ninja celebrated by village crowd" em vez de "recognition and
  validation", que o acervo não entende bem.
- Orienta a incluir nome de anime/personagem na query quando a
  narração mencionar um específico (ex: "Naruto training alone
  forest"), e ficar no genérico-mas-visual quando não tiver certeza.
- Introduz dois campos opcionais por segmento: `"keyword_weight"` e
  `"semantic_weight"` — ajustam o peso relativo entre correspondência
  literal de palavra-chave e correspondência semântica na busca do
  acervo. A IA é orientada a sugerir peso maior de keyword pra queries
  concretas (`keyword_weight: 2, semantic_weight: 0.5`) e o inverso
  pra queries mais sobre clima/emoção — ambos os campos são opcionais,
  e são repassados direto pro `/api/search` do seu servidor local
  quando presentes (ignorados silenciosamente pelos outros 5
  provedores, que não têm esse conceito).

Se você marcar o animepexels **junto** com outro banco, o site continua
usando o prompt genérico (com a nota condicional explicando quando usar
esse banco) — o prompt dedicado só entra quando é a única opção.

## Timeout por provedor — "se demorar muito, usa outra fonte"

Nova configuração em `/settings`: **tempo limite esperando UM banco de
vídeo antes de desistir dele e tentar o próximo** (padrão: 25s, ajustável
de 5 a 300).

Antes, o fallback entre provedores só reagia a uma FALHA de verdade
(erro, 404, etc.) — um banco lento ou momentaneamente travado podia
segurar um segmento inteiro por muito tempo (limitado só pelos timeouts
de rede/Selenium, que podem ser bem mais longos que o razoável) antes
do fallback normal entrar em ação. Agora, se um banco não responder
dentro do tempo configurado, o site desiste dele e já tenta o próximo
da lista de prioridade — tanto na prévia da timeline quanto na
montagem final.

**Detalhe técnico**: implementado com uma thread `daemon=True` própria
por chamada (não `signal.alarm`, que só existe em sistemas Unix e não
funcionaria no Windows, nem um pool compartilhado de tamanho fixo).
Como não dá pra matar uma thread Python à força, a tentativa
"abandonada" continua rodando sozinha em segundo plano até terminar ou
falhar por conta própria — o que muda é que o resto do processamento
não fica mais esperando por ela. Ser `daemon=True` importa de verdade
aqui: sem isso, se um provedor travasse pra valer (nunca respondesse),
aquela thread abandonada ficaria viva pra sempre, podendo impedir um
servidor rodando por muito tempo (processando muitos jobs ao longo do
dia) de encerrar de forma limpa.

## Log de tempo por job (`timing_log.json`) — pra identificar gargalos

Cada job agora tem um log próprio de quanto tempo cada etapa levou,
salvo em `jobs/<job_id>/timing_log.json`. Cobre: transcrição, montagem
do prompt, busca de prévia de cada segmento, e (na montagem final)
busca/download, normalização, concatenação e mixagem de áudio de cada
segmento.

**Como pegar**: um link "📊 Baixar log de tempo" aparece tanto na
timeline (disponível assim que a pré-busca termina, mesmo que a
montagem final ainda não tenha rodado ou tenha falhado) quanto na
página de resultado — ou baixe direto em
`/job/<job_id>/download-timing-log`.

**Formato do arquivo**: um bloco `totals_by_category_ordered_by_time`
já soma o tempo de todas as ocorrências do mesmo tipo de etapa (juntando
os índices de segmento — ex: todas as "buscas" de todos os segmentos
somadas) e ordena da que mais consumiu tempo pra menos, pra já mostrar
o gargalo na primeira linha sem precisar caçar. Um bloco `events` traz
a lista crua, item por item, com timestamps de início/fim — útil pra
investigar um segmento específico que demorou muito mais que os outros.
Envie esse arquivo se for pedir ajuda com lentidão — ele mostra
exatamente onde o tempo foi gasto, não só "demorou".

## Cena repetindo? Agora busca uma cena extra em vez de repetir

Pedido direto: "se a cena for muito pequena não repita e sim ache
chances de colocar além, ou use o filtro de tempo pra buscar cenas
mais adequadas". Os dois foram feitos:

1. **Filtro de duração corrigido**: já existia um filtro pra pedir
   vídeo do tamanho certo (Pexels, Magnific, Anime Pexels Local), mas
   o cálculo permitia pedir vídeo **mais curto** que o próprio
   segmento (até 30% menor + margem) — o que na prática ainda deixava
   a repetição acontecer com frequência mesmo com o filtro ativo.
   Agora o mínimo pedido nunca fica abaixo da duração do segmento.

2. **Busca de cena extra em vez de repetir**: quando o clipe encontrado
   ainda vem mais curto que o segmento (banco sem suporte a filtro de
   duração, ou nada bateu o filtro mesmo assim), o site agora busca
   automaticamente **outro resultado diferente** da mesma pesquisa
   pra completar o tempo, em vez de repetir a mesma cena em loop —
   pode encadear até 4 clipes diferentes num único segmento se
   precisar. Só recorre à repetição como **último recurso**, se mesmo
   somando todos os candidatos disponíveis ainda faltar tempo.

   Isso só vale pra busca automática — um segmento com fonte manual
   (upload, link direto, ou um resultado específico fixado no editor)
   continua se comportando como antes (repete se for curto), já que
   nesse caso a escolha foi deliberada, não algo pra "completar".

3. **Cena já usada em OUTRO trecho não é escolhida de novo**: esse foi
   o ponto principal, esclarecido depois — o pedido não era só evitar
   repetir dentro de UM trecho (item 2 acima), mas evitar que a MESMA
   cena apareça em partes DIFERENTES do vídeo inteiro. Agora existe
   um rastreador (`UsedClipsTracker`) compartilhado entre todos os
   trechos da mesma montagem: se dois segmentos fizerem buscas iguais
   ou parecidas, cada um prefere um resultado que o outro ainda não
   usou. Só recorre a repetir uma cena de outro trecho como **último
   recurso**, se a busca genuinamente não tiver mais nenhuma opção
   nova disponível (melhor reusar do que deixar o trecho sem nada).

   Detalhe técnico: como os segmentos são processados em paralelo
   (`assembly_fetch_concurrency`), "reservar" uma cena pra uso precisa
   ser atômico — testado com 20 threads disputando a mesma cena ao
   mesmo tempo, confirmando que só uma consegue, sem condição de
   corrida.

## Personalização do texto na tela

O texto na tela de cada trecho (`on_screen_text`) agora é totalmente
configurável no editor de segmentos, logo abaixo do campo de texto:

- **Posição**: 9 opções (canto/centro em cima, no meio, ou embaixo —
  o padrão, igual ao comportamento de sempre, é "Base centro").
- **Tamanho**: em pixels — sem preencher, usa o tamanho automático de
  sempre (proporcional à altura do vídeo).
- **Fonte**: Negrito (padrão, igual de sempre) ou Normal.
- **Borda**: contorno preto ao redor das letras (desligado por padrão).
- **Fundo**: caixa semi-transparente atrás do texto (ligado por
  padrão, igual de sempre) — pode desligar se preferir o texto "solto"
  sobre o vídeo.

Sem mexer em nenhum desses controles, o visual continua idêntico ao de
sempre — são só opções adicionais.

## Prévia reduzida (400px de largura)

O player do Monitor de Origem (a prévia que toca ao clicar num trecho
ou escolher um resultado de busca) agora tem largura fixa de 400px —
o vídeo completo continua tocando normalmente (não é um trecho
cortado), só o tamanho na tela é menor, pra não pesar tanto na página.

## Overlays: texto, imagem ou vídeo sobreposto ao vídeo final

Diferente do texto na tela (que pertence a UM trecho da narração), um
**overlay** tem tempo, posição e tamanho **próprios** — pode ficar
restrito a uma janela específica de alguns segundos, ou atravessar o
vídeo inteiro do início ao fim, **independente de onde os trechos da
narração começam/terminam**. Existem 2 tipos, ambos na mesma seção do
editor de segmentos (`/job/<id>/edit-segments`), com o mesmo botão de
remover:

### Overlay de imagem/vídeo (logo, marca d'água, elemento gráfico)

**De onde vem** (3 modos):
- **Upload**: um arquivo (imagem ou vídeo) do seu computador.
- **Link direto**: uma URL apontando direto pro arquivo.
- **Busca num banco**: escolhe um banco (qualquer um dos 6) e um termo
  de busca — o site busca de verdade e usa o primeiro resultado
  encontrado, sem precisar de um link específico em mente.

**Posição e tamanho**: 9 posições prontas (cantos/centro, em cima/no
meio/embaixo) ou posição livre em % (x/y), e tamanho em % da largura
do vídeo final (a altura escala proporcionalmente, preservando a
proporção original da imagem/vídeo).

**Overlay de vídeo mais curto que sua própria janela**: repete em
loop pra preencher o tempo (mesmo espírito do preenchimento de
duração dos trechos normais).

### Overlay de TEXTO puro (título, chamada)

Um formulário próprio, ao lado do de imagem/vídeo: texto, tempo
(início/fim), posição (9 presets ou livre em %), tamanho, fonte,
borda e fundo — mesmas opções do texto de um trecho, só que com tempo
independente dos segmentos. Não consome nenhum arquivo nem precisa de
download — é desenhado direto por cima do vídeo já pronto.

### Em comum aos dois tipos

**Tempo**: início e fim em segundos, absolutos no vídeo final — não
tem relação nenhuma com os limites dos trechos da narração.

**Se um overlay falhar** (link quebrado, busca sem resultado): não
trava o vídeo inteiro — só aquele overlay específico é pulado, com o
erro registrado em `job["overlay_errors"]`, e a montagem segue
normalmente com os overlays que deram certo. (Overlay de texto nunca
falha dessa forma — não tem fonte externa pra resolver.)

**Ordem de composição**: overlays são aplicados depois do áudio já
sincronizado, antes de legendas (se você tiver ativado). Sem nenhum
overlay cadastrado, o vídeo final é bit-a-bit idêntico ao que seria
sem essa funcionalidade — nada muda pra quem não usar isso.

## Bordas pretas: 3 opções (`aspect_fill` em `/settings`)

Quando o clipe encontrado tem uma proporção diferente da exportação
(ex: um vídeo quadrado ou 4:3 numa exportação 16:9), sobra espaço nas
bordas. 3 formas de lidar com isso, escolhidas em `/settings`:

- **⬛ Bordas pretas** (`black`, padrão): preenche com preto sólido.
- **🧩 Mosaico do próprio clipe** (`mosaic`): preenche as bordas com um
  mosaico borrado feito de 4 cópias do próprio clipe, com o clipe
  original nítido e completo no centro — evita a barra preta sem
  cortar nada da imagem original.
- **🔎 Zoom central** (`zoom`): amplia o clipe até preencher a tela
  inteira, cortando o excesso — sem nenhuma borda, mas perde um pouco
  das bordas da imagem original.

## Correção automática de JSON com aspas mal-escapadas

Erro real relatado: a IA às vezes escreve uma citação dentro de
`on_screen_text` sem escapar as aspas internas (ex:
`"on_screen_text": ""Ele se acha superior""`), quebrando o JSON com
`Expecting ',' delimiter`. O site agora corrige isso automaticamente
antes de desistir, preservando a citação como parte do texto (não
descarta as aspas). Se a correção não resolver (JSON quebrado por
outro motivo), o erro mostrado agora inclui um trecho do JSON perto do
problema, pra facilitar achar manualmente.

## Prompt: momentos importantes, notícia/documentário, e overlays sugeridos pela IA

Três reforços no prompt genérico (`build_prompt`):

- **Texto na tela com mais frequência em momentos importantes**: a
  regra agora orienta a IA a **procurar ativamente** por números
  marcantes, viradas, conclusões, frases de efeito — não só usar texto
  "quando ajudar".
- **`content_style="noticia_documentario"`**: parâmetro opcional que
  ativa uma regra pedindo mais uso de FOTO parada (comum nesse
  gênero), em vez de sempre vídeo.
- **IA pode sugerir overlays de verdade**: além dos segmentos, a
  resposta JSON pode incluir uma chave `"overlays"` (lista, no nível
  raiz) com título/chamada de texto puro ou imagem/vídeo buscado nos
  mesmos momentos importantes — a IA pode combinar texto + imagem/vídeo
  no mesmo ponto quando fizer sentido. `parse_ai_response()` valida e
  já monta cada overlay no formato usado pelo `apply_overlays()`.

## Validação antecipada: foto sem API do Pexels configurada

Bug real relatado: um trecho com `media_type='image'` sem
`PEXELS_API_KEYS` configurado só descobria isso **depois** de rodar a
montagem inteira (minutos, em vídeos longos) — obrigando a esperar
tudo pra só então ver o erro e confirmar de novo. Agora essa checagem
acontece **antes** de sequer começar a baixar qualquer coisa —
responde em menos de 0.1s com o mesmo aviso e destaque de trecho de
sempre. Não bloqueia trechos de foto com fonte manual (upload/link),
já que esses não dependem da API do Pexels.

## Edição em lote de overlays

Marque vários overlays (texto, imagem, ou vídeo, misturados) na
listagem do editor e aplique a mesma posição (X/Y em %) ou tamanho a
todos de uma vez — em vez de configurar um por um. Um campo em branco
no formulário de edição em lote significa "não mexer nesse aspecto",
não "zerar". O campo "Tamanho" se aplica automaticamente como tamanho
de fonte (texto) ou % da largura (imagem/vídeo), conforme o tipo de
cada overlay selecionado.

## Cortes reais: a IA identifica momentos pra você inserir filmagem de verdade

Diferente de overlay (uma camada por cima, sem mudar a duração), um
**corte** literalmente CORTA o vídeo e o áudio num ponto específico e
insere um clipe de verdade ali — o vídeo final sempre fica **mais
longo** pela duração do clipe inserido. Pensado pra quando a narração
descreve um evento real (notícia, acontecimento, declaração pública)
onde uma filmagem de verdade daquele momento faz muito mais sentido
que qualquer stock footage genérico.

**Como funciona**:
1. A IA pode incluir `"cutaway_suggestions"` na resposta JSON — cada
   sugestão tem o segundo exato (`insertion_point`), uma descrição do
   que filmar/buscar (`description`), e o comportamento do áudio
   durante o corte (`audio_mode`: `"pause"` pausa a narração e toca só
   o áudio do clipe inserido, `"continue"` mantém a narração/trilha).
2. As sugestões aparecem numa seção própria no editor de segmentos,
   junto com o restante — você faz upload do clipe real pra cada uma
   que quiser usar (ou descarta as que não fizerem sentido). Pode
   trocar o `audio_mode` sugerido pela IA na hora do upload.
3. Sem upload, a sugestão simplesmente não é aplicada — não precisa
   usar todas.
4. Na montagem, os cortes com upload são aplicados **depois** dos
   overlays, no vídeo já pronto.

**Clipe sem áudio próprio**: gera uma faixa de silêncio automaticamente
(precisa pra poder concatenar sem problema depois).

**Overlays continuam sincronizados mesmo com cortes**: overlays são
aplicados (queimados no vídeo) ANTES dos cortes reais — quando um
corte estica o vídeo depois, o overlay "viaja junto" com o trecho que
ele estava destacando, continuando sincronizado corretamente com a
narração. Testado de ponta a ponta confirmando isso visualmente
(overlay marcado pra um tempo absoluto depois de um corte aparece no
momento certo, deslocado corretamente).

## Orientação dos vídeos buscados (16:9 / 9:16 / misto)

Novo campo `search_orientation` em `/settings`, **separado** da
orientação de exportação:

- **Mesma da exportação** (padrão): busca na mesma orientação da
  exportação, como sempre foi.
- **Sempre 16:9 / Sempre 9:16**: força essa orientação na busca, mesmo
  exportando na outra — o `aspect_fill` cuida de encaixar o resultado
  na moldura final.
- **Misturado**: não filtra por orientação — aceita paisagem e retrato
  misturados entre trechos diferentes do mesmo vídeo.

## Texto na tela pra valores numéricos/financeiros

Quando o momento importante da narração for um valor numérico —
dinheiro, porcentagem, quantidade, data, estatística — a IA agora é
orientada a formatar o texto na tela como um destaque visual limpo
(ex: "R$ 1,78 milhão", "60% de queda"), não a frase inteira da
narração, inspirado no estilo comum de vídeos de economia/finanças/
dados.

## Legendas: estilo customizável e edição manual palavra por palavra

**Estilo global** (formulário de upload, nos dois fluxos — inicial e
reaproveitar JSON): cor do texto, cor da borda, espessura da borda,
sombra, brilho (glow), fonte (negrito/normal), tamanho, e posição
(base/meio/topo). Em branco, usa o visual padrão de sempre —
retrocompatível.

**Edição manual de cada palavra**: uma página própria
(`/job/<id>/edit-captions`, com link no editor de segmentos) mostra
cada palavra da legenda como um cartão editável — texto e tempo
(início/fim) individualmente. Apagar o texto de uma palavra a remove
da legenda.

**Camada própria na timeline**: uma faixa "Legenda" na timeline visual
do editor, ao lado das faixas de vídeo/texto/narração/trilha — cada
palavra vira um pequeno bloco posicionado automaticamente no tempo
certo (reaproveitando a mesma infraestrutura de posicionamento que já
existia pros trechos), clicável, levando direto pra edição manual. Só
aparece quando o job tem legenda gerada.

## Biblioteca de mídia: enviar arquivos a qualquer momento e arrastar pra onde quiser

Uma área própria no topo do editor de segmentos, sempre disponível —
envie arquivos quando quiser (não precisa ser tudo de uma vez, no
início) e arraste o cartão pra qualquer lugar que aceita upload:

- **Um trecho específico** (solta em cima do bloco do trecho na
  timeline) — vira o `override_source` daquele trecho, mesmo efeito
  de escolher "usar um arquivo" manualmente, só sem precisar reenviar.
- **A área de overlays** (solta em cima do formulário "Adicionar
  overlay de imagem/vídeo") — cria um overlay novo automaticamente
  (janela padrão de 0-5s, canto superior direito), que você pode
  ajustar depois normalmente.
- **Uma sugestão de corte** (solta em cima do card da sugestão) —
  resolve aquela sugestão, como se tivesse feito upload direto nela.

Arrastar de verdade (drag-and-drop nativo do navegador) — cada cartão
da biblioteca é arrastável, e os 3 destinos reagem ao soltar chamando
a atribuição certa automaticamente, sem reenviar o arquivo. Remover
um arquivo da biblioteca não desfaz atribuições já feitas com ele —
só tira ele da lista pra arrastar de novo.

## Bugs reais corrigidos (relatados rodando em produção, Windows)

- **Legenda fora de sincronia depois de um corte real**: a legenda era
  gerada com os tempos ORIGINAIS da transcrição, sem ajustar pelo
  deslocamento que um corte real (`insert_cutaways`) causa no vídeo
  final — uma palavra dita DEPOIS de um corte aparecia adiantada,
  fora de sincronia com a fala de verdade. Corrigido com
  `shift_timestamps_for_cutaways()`, que desloca cada palavra pela
  duração acumulada de todos os cortes antes dela. Testado com 1
  corte e com múltiplos cortes acumulados, confirmado visualmente.

### Auditoria de combinações entre recursos (nenhum bug adicional encontrado)

Depois de corrigir o bug acima, testei de ponta a ponta outras
combinações que poderiam ter o mesmo tipo de problema — todas
confirmadas corretas:
- Overlay de texto + corte real na mesma região de tempo: overlay
  fica sincronizado corretamente (é "queimado" no vídeo antes do
  corte, viaja junto com o trecho que estava destacando).
- Overlay de imagem/vídeo (caminho de código diferente do texto) +
  corte real: mesmo resultado, sincronizado corretamente.
- Overlay sugerido pela IA que falha na busca: não trava o vídeo
  inteiro, erro fica visível.
- Retry (montagem falha, depois corrigida e confirmada de novo): o
  corte real é aplicado exatamente uma vez, sem duplicar.
- Biblioteca de mídia (arrastar-e-soltar) até o vídeo final montado:
  confirmado que o arquivo atribuído aparece de verdade no resultado.

- **Erro de overlay nunca aparecia em lugar nenhum**: quando um
  overlay falhava (link quebrado, busca sem resultado), o erro era
  registrado internamente mas nunca mostrado — o overlay simplesmente
  desaparecia do vídeo final sem explicação nenhuma. Corrigido:
  aparece um aviso claro na página de resultado, listando quais
  overlays falharam e por quê, deixando claro que o resto do vídeo
  está normal. Também corrigida uma inconsistência relacionada: o
  erro antigo podia ficar "grudado" na tela se você removesse todos
  os overlays depois de uma tentativa que tinha falhado parcialmente.


- **Bug de FPS na inserção de cortes**: com mais de um corte real
  inserido, o segundo aparecia deslocado no tempo (a cena certa
  aparecia segundos depois do esperado), mesmo com a duração total do
  vídeo batendo certo. Causa: os pedaços "antes/depois" do vídeo
  original mantinham o FPS original, enquanto os clipes de corte
  normalizados forçavam um FPS diferente — o demuxer de concatenação
  (que copia sem recodificar) não lida bem com FPS inconsistente entre
  pedaços, corrompendo os timestamps internos. Corrigido forçando o
  mesmo FPS em todos os pedaços.
- **Overlays sugeridos pela IA nunca eram salvos**: `parse_ai_response`
  já validava corretamente overlays incluídos na resposta JSON da IA,
  mas faltava a conexão final que os salvava no job — a sugestão era
  processada e simplesmente descartada. Corrigido junto com a conexão
  das sugestões de corte.


- **Condição de corrida em `_save_state`**: podia falhar com
  `RuntimeError: dictionary changed size during iteration` se o job
  fosse modificado por outra thread (ex: a montagem em segundo plano)
  exatamente durante o salvamento do estado. Corrigido com uma cópia
  rasa atômica do dicionário antes de serializar.


- **"Request Entity Too Large" (413) ao confirmar segmentos**: o
  limite de tamanho de upload (`MAX_CONTENT_LENGTH`) estava em 200MB —
  generoso pra UM único áudio, mas o formulário de confirmar segmentos
  pode ter VÁRIOS vídeos enviados manualmente ao mesmo tempo (um por
  trecho, via "upload" no editor), e a soma de poucos vídeos em boa
  qualidade já estoura 200MB com facilidade. Aumentado o padrão pra
  2GB, e deixado configurável via variável de ambiente
  `MAX_UPLOAD_SIZE_MB` se ainda precisar de mais (ou menos). Também
  adicionada uma mensagem de erro amigável no lugar da página crua do
  Flask, explicando a causa e como ajustar.

- **A causa raiz de "continua repetindo o trecho"**: as duas melhorias
  anteriores (preencher com cena extra, evitar cena repetida entre
  trechos) funcionavam nos testes, mas o vídeo real continuava
  repetindo. A causa: **todo trecho não editado** (a maioria, numa
  narração normal — ninguém edita manualmente 20-30 trechos um por
  um) passava por uma "fixação automática" que travava o resultado
  exato visto na prévia via link direto — um mecanismo tratado como
  "escolha deliberada da pessoa" (igual um upload manual), então
  **nunca** passava pelas duas melhorias novas. Corrigido: removida a
  fixação automática — agora todo trecho, editado ou não, passa pela
  busca de verdade na montagem (mantendo, quando possível, o banco que
  a prévia já descobriu que funciona, sem tentar de novo à toa um
  banco que já se sabe que está fora do ar). Testado especificamente o
  cenário de confirmar **sem editar nenhum campo** — o fluxo mais
  comum de todos.

- **Condição de corrida entre o status do job e o log de tempo**:
  `job["status"]` virava `"concluido"` (ou `"cancelado"`) ANTES do log
  de tempo (`timing_log.json`) ser salvo de verdade — só acontecia
  depois, no `finally`. Isso criava uma janela real onde alguém
  observando o status (a própria pessoa no navegador, clicando em
  "baixar log de tempo" assim que vê "concluído" na tela; ou um teste
  automatizado) podia ler o arquivo ANTES dele refletir a montagem
  inteira, pegando um log incompleto. Corrigido invertendo a ordem: o
  log agora é sempre salvo primeiro, e só depois o status muda pro
  valor final — testado checando o estado exato no instante em que o
  status vira "concluido" (a cada 10ms), não só no fim do processo.

- **Conflito de porta com o Anime Pexels Local**: este site rodava na
  porta 5000 por padrão — exatamente a mesma porta padrão do servidor
  local do Anime Pexels Local (`http://localhost:5000`). Como o
  provedor "animepexels" depende dos dois servidores rodando ao mesmo
  tempo na mesma máquina, isso sempre daria conflito ("Address already
  in use"). Corrigido: porta padrão agora é **5050**, e configurável
  via variável de ambiente `PORT` se precisar mudar de novo no futuro.

- **Prompt mencionava bancos não selecionados**: mesmo já existindo uma
  validação que rejeita a resposta da IA se ela usar um banco fora dos
  marcados (`parse_ai_response(valid_providers=...)`), o TEXTO do
  prompt em si ainda mencionava bancos específicos (Mixkit, Pexels,
  Magnific) em várias regras e no exemplo de JSON, mesmo quando esses
  bancos não estavam entre os selecionados — o que podia confundir a
  IA a achar que estavam disponíveis, gerando respostas rejeitadas
  sem necessidade. Corrigido: todas as regras específicas de um banco
  agora só aparecem no prompt quando esse banco está de fato marcado;
  o exemplo de JSON usa provedores de verdade da lista selecionada (não
  nomes fixos); e a regra principal foi reforçada, citando
  explicitamente que bancos externos conhecidos pela IA (Shutterstock,
  Getty, etc.) não podem ser usados mesmo que pareçam familiares.
  Testado com 5 combinações diferentes de provedores selecionados,
  incluindo a numeração automática das regras (pra não deixar buracos
  quando uma regra condicional é omitida).

- **Correção de um trecho se perdia se outro trecho falhasse depois**:
  o bug mais sério desta leva. Com vários trechos com problema,
  corrigir o primeiro (ex: trocar a fonte de um trecho quebrado) e a
  montagem falhar DEPOIS num trecho diferente fazia a página do editor
  voltar a mostrar os valores ORIGINAIS da IA pro trecho já corrigido —
  perdendo o trabalho manual feito. Causa raiz: `pending_segments` (a
  base usada pra reconstruir os segmentos a cada confirmação) nunca
  era atualizado com os valores recém-confirmados, só lido. Corrigido
  em 3 partes: (1) salva os valores confirmados de volta assim que
  você confirma, (2) o formulário agora pré-seleciona corretamente o
  modo "upload"/"link direto" ao recarregar (antes sempre voltava pra
  "buscar automaticamente", que reverteria a correção sozinho), (3)
  upload de arquivo é reaproveitado automaticamente numa nova
  confirmação sem precisar reenviar o mesmo arquivo (não dá pra
  pré-preencher um campo de arquivo por segurança do navegador).
  Testado com o cenário completo de 3 tentativas sucessivas.

- **Chrome não concluía o download (Pixabay)**: o método de download
  tenta buscar o vídeo via `fetch()` + Blob em JavaScript (pra evitar
  abrir o player em vez de baixar) — mas isso pode falhar
  silenciosamente por CORS, já que CDNs de vídeo geralmente não
  enviam os headers que permitiriam ler a resposta via JS de outra
  origem. O código não checava esse resultado, só ficava esperando um
  arquivo aparecer no disco pelo tempo limite inteiro, mesmo que o
  download nunca tivesse começado de verdade. Corrigido: agora checa
  o resultado da tentativa via fetch+Blob e cai automaticamente pro
  método mais simples (clique direto num link) quando a primeira
  falha; se as duas falharem de verdade, a mensagem de erro explica a
  causa provável (CORS) em vez de só "timeout".

- **Pixabay: "fixar candidato" falhava em páginas sem JSON-LD**: a
  resolução por link dependia inteiramente de um bloco JSON-LD
  (`VideoObject`) que nem toda página tem — a página real que quebrou
  em produção não tinha esse bloco, só a tag `<video>` renderizada
  pelo video.js. Corrigido com uma estratégia em camadas: tenta o
  JSON-LD primeiro (mais rico), e cai pra extrair direto da tag
  `<video>` quando não encontra — testado com o HTML real que causou
  o erro, sem regressão no caminho antigo.

- **Mixkit: a correção anterior não bastava**: mesmo depois de
  corrigir a regex pra reconhecer `<video>` com atributos em qualquer
  ordem, a MESMA página continuava falhando. A causa raiz era mais
  profunda: o Selenium captura o HTML imediatamente após navegar, sem
  esperar o JavaScript (Stimulus.js) terminar de preencher o atributo
  `src` do vídeo. Corrigido na raiz, no `ChromeSession` do toolkit
  (usado por vários provedores): agora dá pra pedir uma espera
  explícita por um elemento **e um atributo específico dele** ficarem
  prontos antes de capturar o HTML, com um tempo limite de segurança
  pra nunca travar a página inteira se o layout mudou de verdade.
  Aplicado tanto no Mixkit quanto no Pixabay.

- **Monitor de Origem só aparecia depois de clicar em "Buscar"**: os
  dados da prévia inicial de cada trecho (incluindo o vídeo tocável,
  quando disponível) ficavam presos no servidor, usados só pra
  desenhar o thumbnail estático da timeline — nunca chegavam ao
  JavaScript. Agora, ao clicar num trecho, o Monitor de Origem já
  mostra automaticamente o que já foi buscado, sem precisar de um
  clique extra em "Buscar e ver opções" primeiro.

- **`PexelsAPIClient.get_video_by_url` não existia**: o mecanismo de
  "fixar candidato" do editor tentava resolver um link de post do
  Pexels via API oficial, mas esse método só existia no cliente de
  navegador (scraping) — a API sempre falhava com
  `AttributeError: 'PexelsAPIClient' object has no attribute
  'get_video_by_url'`. Corrigido extraindo o ID direto da URL (o
  número no final) e reaproveitando `get_video()`, que já existia.
  Testado com a URL exata do erro relatado, mais casos de borda (sem
  barra final, com query string, URL sem ID numérico).

- **Falha de montagem travava o job num beco sem saída**: quando um
  segmento falhava na montagem final (fonte quebrada, arquivo
  corrompido, etc.), o job ia pro status `"erro"` permanente — a única
  saída era recomeçar o processo inteiro (colar o JSON de novo, esperar
  a transcrição). Agora, uma falha de montagem volta o job pro editor
  (`pronto_para_editar`) com uma mensagem clara indicando QUAL trecho
  falhou e por quê (ex: "Trecho 18: ..."), deixando você trocar a fonte
  só daquele trecho e mandar montar de novo — sem perder o resto do
  trabalho já feito. **Além disso**, a timeline agora abre já
  **posicionada e destacada** (borda vermelha pulsante, com rolagem
  automática até o bloco) exatamente no trecho que falhou — antes você
  precisava procurar manualmente qual dos vários trechos era o
  problemático.

- **Mixkit: "fixar candidato" nunca funcionava**: a regex que extrai o
  vídeo da página de detalhe só reconhecia `<video src="...">` quando
  `src` era o PRIMEIRO atributo da tag (como na listagem/busca) — mas a
  página de detalhe real (confirmado com uma amostra de HTML de
  verdade, enviada por um usuário) tem vários atributos antes de `src`
  (class, data-controller, poster, etc), então a busca nunca encontrava
  nada e sempre falhava com "Não encontrei nenhum vídeo reconhecível".
  Corrigido com uma regex que extrai a tag `<video ...>` inteira
  primeiro, e procura `src=`/`poster=` dentro dela em qualquer ordem —
  testado com o HTML real que causou o erro.

## Whisper: GPU ou CPU (detecção automática)

Nova configuração em `/settings` → "Transcrição (Whisper)":
- **Automático** (padrão): detecta sozinho se há uma placa de vídeo
  (GPU/CUDA) instalada e usa ela pra transcrever mais rápido, sem você
  precisar saber o modelo da placa.
- **Forçar GPU**: usa a GPU mesmo que a detecção automática não a
  escolhesse — se a GPU falhar ao carregar (driver quebrado, sem
  memória suficiente), cai pra CPU sozinho, sem travar a transcrição.
- **Forçar CPU**: sempre usa a CPU, mesmo com GPU disponível — útil se
  a GPU estiver ocupada com outra coisa ou apresentando problema.

## Correções de uso real (relatadas rodando o site de verdade)

- **"Navegador compartilhado" + concorrência paralela se anulavam
  silenciosamente**: se você ligasse "navegador compartilhado entre
  fontes" (pra economizar memória, um Chrome só) mas deixasse a
  concorrência de busca/montagem no padrão (3), o resultado real era
  **3 navegadores**, não 1 — cada busca em paralelo cria sua própria
  sessão (sessões Selenium não são seguras pra compartilhar entre
  threads simultâneas), então "compartilhado" + concorrência > 1 na
  prática significa "um navegador por busca paralela", o oposto do que
  a opção promete. Agora essa combinação é bloqueada com uma mensagem
  clara: ou desliga o compartilhado (e sobe a concorrência à vontade),
  ou mantém o compartilhado com as duas concorrências em 1.

- **A montagem final também tinha o mesmo gargalo**: depois de
  paralelizar a pré-busca de prévias, a etapa de MONTAGEM final ainda
  processava um segmento de cada vez em sequência — relevante pra
  qualquer trecho que precisasse buscar de novo (termo editado no
  editor, ou a prévia daquele trecho falhou). Corrigido do mesmo jeito:
  `assembly_fetch_concurrency` nas configurações (padrão 3), cada
  worker com sua própria sessão de navegador, ordem final sempre
  preservada por índice mesmo com conclusão fora de ordem.

  **Detalhe técnico que vale registrar**: provar isso com "tempo total"
  não funciona de forma confiável em máquinas com poucos núcleos de CPU
  — a etapa de normalização (recodificar com ffmpeg) é pesada em CPU, e
  numa máquina de 1 núcleo, "paralelizar" processos que competem pelo
  mesmo núcleo não acelera nada (só a parte de rede/busca se beneficia
  de verdade). O teste que prova isso mede se as janelas de tempo das
  buscas se SOBREPÕEM, não o tempo total — funciona certo independente
  de quantos núcleos a máquina que roda tem.

- **Fontconfig quebrava no Windows**: `on_screen_text` e as legendas
  usavam `font=Sans` (drawtext) e a fonte "Arial" (legendas .ass), que
  dependem do fontconfig do sistema pra resolver o nome da fonte pra um
  arquivo de verdade — no Windows isso costuma faltar, gerando
  `Fontconfig error: Cannot load default config file` e derrubando o
  segmento inteiro. Corrigido: a fonte DejaVu Sans (licença livre, ver
  `assets/fonts/LICENSE.txt`) agora vem embutida no projeto, e tanto o
  `drawtext` (via `fontfile=`) quanto as legendas (via `fontsdir=`)
  apontam direto pro arquivo — sem depender de fontconfig nem de
  nenhuma fonte já instalada no sistema, em qualquer sistema
  operacional.
- **Busca de outro vídeo era só um campo de texto às cegas**: agora tem
  um botão "🔍 Buscar e ver opções" em cada trecho do editor, que busca
  de verdade (sem baixar nada ainda) e mostra até 6 miniaturas reais
  clicáveis. Clicar numa opção do Pexels/Pixabay/Mixkit **fixa**
  exatamente aquele resultado pra montagem (por baixo dos panos, vira
  um "link de post"); pro Magnific/VistaCreate, que não suportam buscar
  por ID específico, mostra um aviso de que é só ilustrativo.
- **Bug real corrigido nessa mesma área**: os campos de "colar link
  direto" e "colar link de post" usavam o mesmo nome no formulário —
  como os dois ficam no HTML mesmo quando escondidos, o navegador
  enviava os dois, e o servidor sempre lia o primeiro (o vazio, na
  maioria dos casos). Agora têm nomes distintos.
- **Vazamento de navegador na busca ao vivo**: `search_candidates()`
  (usada pelo botão "Buscar e ver opções") criava uma sessão nova a
  cada clique mas nunca fechava — cada busca deixaria um Chrome aberto
  pra sempre em provedores sem API configurada. Corrigido: fecha
  automaticamente quando cria a sessão internamente (mas não fecha uma
  sessão que o chamador passou de propósito pra reaproveitar).
- **Prévias só apareciam todas de uma vez, no final**: a tela de
  "buscando prévias" agora mostra cada thumbnail assim que ela fica
  pronta (ou um indicador "sem prévia" pras que falharem), em vez de só
  uma barra de porcentagem sem nenhum conteúdo visual até tudo
  terminar.

## API de fotos do Pexels e fotos sugeridas pela IA

O `pexels_api_client.py` agora também busca **fotos** (não só vídeos) —
`api.pexels.com/v1/search`, mesma chave da API de vídeo, endpoint
separado. Bônus: a API de fotos devolve uma descrição real por foto
(campo `alt`), diferente da API de vídeos, que não tem isso.

O prompt já pede pra IA usar `"media_type": "image"` (com
`"provider": "pexels"`) quando um trecho combinar melhor com uma foto
parada do que com vídeo — o site busca a foto de verdade e aplica o
efeito Ken Burns automaticamente, sem precisar de nenhuma edição manual
no editor. Só o Pexels suporta isso por enquanto (os outros 4 provedores
não têm uma API de fotos equivalente no toolkit); se a IA marcar
`media_type: "image"` com outro provedor, isso é rejeitado na validação
do JSON com uma mensagem clara. Também exige `PEXELS_API_KEYS`
configurado — sem isso, o segmento falha com um erro explicando o que
falta (não trava silenciosamente).

**Bug real corrigido nesta revisão:** `media_type` estava sendo
descartado silenciosamente em dois pontos — na pré-busca da prévia da
timeline (`fetch_segment_preview`, que sempre buscava vídeo, nunca
foto) e na reconstrução dos segmentos pelo editor (`confirm_segments`,
que sempre voltava pro padrão "video"). Como o fluxo sempre passa pelo
editor, isso fazia a IA sugerir uma foto e o site silenciosamente tratar
como vídeo, sem avisar ninguém — testado agora com um teste de
regressão específico que verifica qual método de busca foi de fato
chamado em cada etapa (não só se o job terminou com sucesso).

## Monitor de Origem e Monitor de Programa (players de vídeo reais)

O que antes era só thumbnail estático e um link de download agora tem
players de vídeo de verdade tocando, no estilo Premiere:

- **Monitor de Origem** (no editor de segmentos): ao buscar candidatos
  pra um trecho, o primeiro resultado já toca automaticamente num
  player de vídeo — não é mais só uma imagem parada. Clicar em
  qualquer outra miniatura troca o vídeo tocando. Funciona sem baixar
  nada no seu servidor: o navegador toca direto da CDN do provedor.
  Confirmado disponível pra Pexels, Mixkit, Magnific e VistaCreate —
  só o Pixabay não expõe um vídeo tocável na busca (a página de
  detalhe seria necessária), então cai pro thumbnail estático nesse
  caso — com uma mensagem explicando isso, não uma área vazia (era um
  bug real: o comentário no código dizia que mostraria a miniatura,
  mas o código de fato só escondia o player sem colocar nada no lugar).

- **Monitor de Programa** (na página de resultado): assim que o vídeo
  final fica pronto, um player de vídeo de verdade aparece na página,
  tocando o resultado — com busca/seek funcionando (via requisições
  HTTP Range) e um alternador pra trocar entre a versão com e sem
  legenda no mesmo player, sem precisar baixar nenhuma das duas antes
  de decidir qual prefere.

  **Limitação que continua honesta**: o Monitor de Programa só mostra
  o resultado DEPOIS da montagem terminar — não existe uma prévia "ao
  vivo" de como o projeto ficaria ANTES de processar (isso exigiria
  reproduzir/compor vídeo client-side em tempo real, um projeto bem
  maior que o atual).

## Google Flow (imagens geradas por IA), "Ocultar o navegador" e "Não repetir"

### 8º provedor: `flow` (Google Flow)
Gera **imagens inéditas com IA** em https://flow.google.com/ automatizando o navegador com o Playwright
(é o seu `flow_gerador.py`, mesmo fluxo e mesmos seletores, virado módulo em
`toolkit/googleflow/googleflow_client.py`). Funciona como os bancos de foto: a IA que monta o roteiro
escolhe `"provider": "flow"` + `"media_type": "image"` e a `query` é a **descrição da imagem**.

- Na página inicial ele vem **desmarcado** (é lento e usa a sua conta Google); marque quando quiser.
- O prompt da IA avisa que é lento e pede uso com moderação, só pra cenas que nenhum banco de estoque teria.
- **Cache**: o mesmo pedido (mesmo texto + mesma proporção) nunca é gerado duas vezes — a prévia gera,
  a montagem reaproveita. Fica em `flow_dados/imagens/` (+ `imagens.json`).
- **Um navegador e uma conversa para o vídeo inteiro**: na primeira imagem o site abre o Flow, cria um
  projeto e faz a configuração uma vez — abre as configurações do agente, marca **Confirmar antes de gerar =
  Nunca** e **1 imagem (x1)** e clica em **Salvar** (sem isso o agente pararia pedindo confirmação a cada
  imagem). As imagens seguintes são digitadas na **mesma conversa**, uma atrás da outra; os pedidos de vários
  trechos entram numa fila. O navegador fecha sozinho depois de 2 minutos sem pedidos. Se uma geração falhar,
  a conversa é descartada e a próxima recomeça num projeto novo (o navegador continua aberto).
- O botão que abre as configurações do agente não é conhecido com certeza: o site tenta vários candidatos e
  confere que o painel certo abriu. Se não achar, o erro **lista os botões da tela** — copie o seletor do certo
  em *Configurações → Google Flow → Seletor do botão de configurações*. Se você já deixou o Flow configurado à
  mão, desmarque *Configurar o projeto antes de gerar*.
- A proporção do pedido segue a orientação do site (`16x9` ou `9x16`).
- Tem timeout **próprio** (`flow_timeout_seconds`, padrão 300s + margem); o de 25s dos bancos derrubaria toda geração.
- Só gera imagem: um trecho de **vídeo** marcado como `flow` cai pro próximo banco da prioridade, sem gerar nada.
- Não tenta "termos alternativos" (gerar de novo com menos palavras seria outra imagem, não a mesma).
- **Login**: o primeiro login no Google precisa de janela visível — em *Configurações → Google Flow*
  há o botão **Fazer login no Flow**. A sessão fica em `flow_dados/perfis_navegador/`.
  ⚠️ Não compartilhe nem versione `flow_dados/` (quem tiver o `sessao.json` acessa sua conta; já está no `.gitignore`).
- Precisa de `pip install playwright` (e `playwright install chromium` se não usar Chrome/Edge). Sem ele,
  a validação antecipada avisa antes de começar a montagem.

### Várias contas do Google Flow (troca automática quando o limite acaba)
Em *Configurações → Google Flow → Contas* você cadastra quantas contas quiser. Cada uma tem o **seu próprio
perfil de navegador** (`flow_dados/perfis_navegador/<navegador>--<conta>`; a conta *principal* usa o perfil de
sempre, então quem já fez login não perde nada). O login de cada conta é feito **uma vez, à mão**, na janela que o
botão *Fazer login* abre — nenhuma senha é digitada nem guardada pelo site.
- Quando o Flow responde (sem imagem) algo que indica **limite/créditos esgotados**, a conta é marcada como
  *esgotada* por `flow_horas_ate_liberar` horas (padrão **24** — confirmado pelo usuário: é exatamente esse o
  tempo que o Google leva pra liberar a conta de novo; volta sozinha depois), o navegador é reaberto com o
  perfil da **próxima conta da lista** (preferindo as que já têm login) e o **mesmo pedido é refeito** lá, num
  projeto novo já configurado. As imagens seguintes continuam nessa conta.
- Se todas esgotarem, o erro diz quando cada uma volta. Dá pra marcar/liberar uma conta à mão na tabela.
- Mensagem confirmada do Flow: **"Você chegou ao limite de uso. Tente de novo mais tarde."**, na classe `.error-text`
- Duas caixas extras confirmadas via HTML real do usuário e tratadas automaticamente: as **boas-vindas** de uma
  conta nova no Flow (apresentação + política de privacidade, a 2ª só libera o botão depois de rolar até o fim) e
  o **aviso de novidades da versão** que pode aparecer logo depois de clicar em "Novo projeto" (um clique em
  "Começar" e segue o processo).
- Mais uma tela confirmada via HTML real: algumas contas caem numa **página de apresentação**
  (`flow.google.com/about`) em vez de ir direto pro app. O site detecta o botão **"Crie com o Google Flow"** e
  clica nele sozinho (a aba recarrega) antes de seguir o processo normal — em qualquer um dos quatro pontos onde
  o site chega no Flow (abrir projeto, login manual, login automático, depois de logar).

### Modelo padrão de vídeo do Flow (configuração, não geração)
Configurações → Google Flow ganhou um campo **Modelo padrão de vídeo** (padrão `Veo 3.1 - Lite`, com sugestões
`Veo 3.1 - Fast`/`Veo 3.1 - Quality`/`Omni 1.1 Flash`, texto livre pra qualquer outro nome). Na primeira vez que
uma conta usa o Flow, o mesmo passo automático que configura as imagens (Confirmar=Nunca, x1) também marca
**x1 de vídeo** e escolhe esse modelo no painel "Padrão para geração de vídeo". Escolher o modelo é *best-effort*
— se o botão ou o item do menu não forem encontrados, o site não trava a configuração inteira, só segue sem
escolher o modelo. ⚠️ **O site ainda não gera vídeo pelo Flow** (o provedor `flow` continua só imagem) — isso
deixa o projeto configurado certo pra quando essa capacidade existir, e ajuda quem usa o Flow por fora do site
com a mesma conta.

### Aviso quando o "keyring" não está instalado
Achamos a causa mais provável de "salvei a senha e não aparece em lugar nenhum": o pacote `keyring` (usado pra
guardar a senha no Gerenciador de Credenciais do Windows) **não vinha listado em nenhum `requirements.txt`** —
quem instalou o site antes dessa correção pode não ter esse pacote. Sem ele, salvar a senha falha, mas o login em
si continua funcionando normalmente (a janela abre e fecha), então parece que deu tudo certo. Agora:
- `keyring` foi adicionado ao `requirements.txt` principal.
- A página Contas Google mostra um **aviso vermelho no topo** se o pacote não estiver instalado, com o comando
  exato pra corrigir (`pip install keyring`).

### "Salvar a senha" agora vem marcado por padrão
Nos dois formulários de login automático (o do topo da página e o de cada conta), a caixinha "salvar a senha"
passou a vir **marcada** — antes vinha desmarcada, e era fácil terminar um login com sucesso (a janela abre e
fecha normalmente) sem perceber que nada tinha sido guardado, já que salvar dependia de lembrar de marcar a
caixinha antes. Desmarque se não quiser guardar a senha dessa vez.

### Ver a senha salva + a conta principal ganha e-mail e senha como qualquer outra
- Botão **"👁 Ver senha"** em qualquer conta com senha salva (inclusive a principal): mostra a senha guardada no
  cofre de credenciais direto na tela. Depois de uma **troca de senha**, a senha nova também aparece na hora, na
  própria mensagem de sucesso ("✅ Senha trocada e salva: <senha>") — sem precisar de um clique extra.
- A conta **principal** deixou de ser um caso especial: agora pode ter e-mail cadastrado, aparece no **exportar**
  (antes ficava sempre de fora), pode ser importada, e o botão **"Trocar senha no Google"** também funciona nela.
  Só a pasta do perfil de navegador continua sem sufixo (compatibilidade com quem já tinha login feito antes
  dessa mudança) — o resto do comportamento é idêntico ao de qualquer conta cadastrada.
- `contas.json` de versões antigas (sem a principal na lista) continua funcionando sem precisar editar nada: ela
  é adicionada automaticamente na leitura, com e-mail em branco.

### Cadastrar conta e fazer login num só passo
No formulário do topo da página Contas Google, agora dá pra preencher **e-mail e senha direto** e clicar em
"Adicionar conta": o site cadastra a conta (o rótulo vira o próprio e-mail se você deixar em branco), faz o
login automaticamente numa janela visível, e a sessão fica salva no perfil de navegador dessa conta — as próximas
gerações e trocas de senha já usam esse perfil sem precisar logar de novo. Marque "salvar a senha" pra também
poder repetir o login com um clique depois (vai pro cofre de credenciais do sistema, nunca num arquivo do
projeto). Deixando a senha em branco, funciona como antes: só cadastra, e o login fica pra fazer depois (manual
ou automático) na linha da conta na tabela.

### Página "Contas Google" (troca de senha automática + exportar/importar)
As contas passaram para a própria página **🔑 Contas Google** (link no menu do topo); Configurações ficou só com
os campos de horas-até-liberar e palavras extras de limite.

- **Trocar senha no Google** (botão por conta, exceto a principal): troca a senha de verdade na conta — não é só
  a credencial guardada no site. Pede a senha ATUAL (pra confirmar identidade, como o Google exige), gera uma
  senha nova de **10 caracteres, só letras minúsculas e números**, preenche os dois campos e confirma; a senha
  nova é salva no cofre de credenciais só depois de confirmar que a troca funcionou. Fluxo baseado no HTML real
  de `myaccount.google.com/intro/signinoptions/password` que o usuário forneceu.
  ⚠️ **Se o Google pedir um captcha durante a confirmação de identidade, o site NUNCA tenta resolver** — para na
  hora, avisa, e a janela fica aberta pra completar à mão.
- **Exportar (JSON)**: baixa e-mail + senha das contas que têm senha salva (a principal fica de fora — não tem
  e-mail cadastrado). ⚠️ O arquivo fica com as senhas em **texto puro** — é um documento sensível, trate com
  cuidado (não subir pra nuvem sem criptografar, apagar depois de usar).
- **Importar (JSON)**: lê um arquivo no mesmo formato e cadastra/atualiza as contas (não duplica as que já
  existem). Útil pra levar as mesmas 3+ contas pra outra instalação do site.
- O armazenamento OPERACIONAL da senha continua sendo o cofre de credenciais do sistema (`keyring`), nunca um
  arquivo do projeto — o JSON existe só como exportação explícita, sob pedido.
  — reconhecida pela palavra "limite" e capturada pelo seletor de avisos. Se a sua vier diferente, o erro
  "respondeu sem gerar imagem" mostra o texto — acrescente uma palavra dele em *Palavras extras que indicam limite*.
- O limite é detectado por: texto da resposta do agente, **avisos na tela** (toast/alerta/diálogo do Material),
  botão de enviar que fica desabilitado, e pedido que o Flow **nem aceita** (o balão da sua mensagem não aparece
  na conversa). Sempre que um pedido falha, o site salva uma **captura de tela + o texto da página** em
  `flow_dados/diagnostico/` (guarda os 20 mais recentes) e o erro diz onde — use isso pra ver o que o Flow mostrou
  e, se preciso, acrescentar uma palavra em *Palavras extras que indicam limite*.
- No modo `cdp` (seu Chrome já aberto) não há troca de conta.
- ⚠️ Usar várias contas para contornar limites pode contrariar os termos do Google e levar ao bloqueio das contas.

### Ocultar o navegador (Configurações e por vídeo)
Um único ajuste (`browser_visible`, mostrado como **"Ocultar o navegador"**) vale para **todos** os processos
que abrem navegador: buscas por scraping nos bancos (Chrome/Selenium), **captura de página** (Playwright) e
**geração no Google Flow**. Na página `/job/<id>/prompt` há um quadro **"Opções só deste vídeo"** que
sobrescreve isso (e o "não repetir") apenas naquele vídeo; os valores iniciais vêm de Configurações.
Com o Flow oculto e a sessão expirada, a geração falha na hora com uma mensagem clara (em vez de esperar
5 minutos por um login que ninguém consegue fazer). No modo `cdp` (seu Chrome já aberto) a janela é a sua.

### Não repetir vídeos/imagens de bancos de conteúdo
Com a opção ligada (padrão; `evitar_repeticao_clipes`), se o melhor resultado de uma busca **já foi usado em
outro trecho do mesmo vídeo**, usa o **2º melhor, depois o 3º**, e assim por diante — antes só a montagem final
fazia isso; agora as **prévias do editor também** (elas pediam só o 1º resultado e mostravam a mesma cena em
todo trecho parecido). Detalhes:
- **Exceção: fotos da Wikipedia podem repetir** (a foto certa de "Albert Einstein" é sempre a mesma).
- A identificação é por banco + id (o id 123 do Pexels não "queima" o id 123 do Pixabay).
- Se **todos** os candidatos já foram usados, repete o melhor em vez de deixar o trecho sem mídia.
- No Flow, repetir o mesmo pedido rende a 2ª, 3ª imagem da **mesma** geração (sem gerar de novo).
- Escopo: um vídeo por vez (não lembra o que foi usado em vídeos anteriores).
- Escolhas manuais no editor (upload, link, resultado fixado) nunca são descartadas.

## Ferramentas trazidas de outro projeto (Shortmaker): baixar de outras redes, checar qualidade, extrair links de canal, transcrever avulso

Quatro ferramentas pequenas, adaptadas de um projeto do usuário chamado Shortmaker (um pipeline de dublagem
automática com 15+ abas) — só a parte de baixar/checar/extrair/transcrever, sem o resto do pipeline (dublagem,
tradução, cortes automáticos etc., que não foram trazidos). Onde o Shortmaker usava seu próprio motor de voz, aqui
tudo continua usando o Whisper que o site já tinha (`whisper_transcribe.py`) — nada de motor de voz novo.

### 📲 Baixar de outras redes (`/redes-sociais`)
Baixa vídeos do **TikTok, Instagram, Twitter/X, Facebook e Kwai** — sempre na maior qualidade disponível (o
YouTube já tem sua própria aba, "Cortar do YouTube"). Vários links de uma vez, com um botão de **checar
qualidade** por link (resolução, fps, tamanho aproximado, duração) sem precisar baixar nada. No final, um `.zip`
com todos os vídeos baixados. Módulo novo: `toolkit/redes_sociais/` — um baixador por plataforma (o Kwai lê o
JSON embutido na própria página do vídeo; os outros usam yt-dlp) atrás de um único `baixar_video(url, pasta)` que
escolhe a fonte certa pelo domínio do link.

### 🔗 Extrair links de canal (`/extrair-links-canal`)
Cola o link de um canal do YouTube e pega título + link de todo Short (ou vídeo normal) dele, sem baixar nada —
útil pra montar rapidamente uma lista grande de URLs pra colar em "Cortar do YouTube" ou "Transcrever". Tem botão
de copiar todos os links de uma vez. Função nova: `extrair_links_canal()` em `youtube_clipper.py`.

### 📝 Transcrever (`/transcrever`)
Baixa um vídeo de qualquer fonte suportada (YouTube, TikTok, Twitter/X, Instagram, Facebook, Kwai) — ou usa um
arquivo já enviado — e opcionalmente transcreve a fala com Whisper, dividindo em trechos com início/fim. Ferramenta
**avulsa**: não usa o pipeline de "Roteiro para Áudio" nem gera vídeo nenhum, só baixa/transcreve e devolve os
arquivos (`.txt`, `.srt`, `.json`). Avisa se o vídeo baixado está em baixa resolução. Módulo novo:
`transcrever_avulso.py`. ⚠️ O idioma **detectado automaticamente** pelo Whisper não é exposto por
`whisper_transcribe.transcribe_audio()` (só o texto) — o campo `idioma` do resultado só vem preenchido quando você
força um idioma manualmente; para detecção automática, fica `None`.

## Transições: catálogo completo do ffmpeg (58 tipos, antes eram 16)

A tela de Configurações → "Transição entre os trechos do vídeo" agora lista as **58 transições nativas** do
filtro `xfade` do ffmpeg (`ffmpeg -h filter=xfade`) — antes só expúnhamos um subconjunto de 16. Todas renderizam
com o ffmpeg de fábrica, sem precisar de nenhum asset (vídeo/imagem) nem shader externo. `video_assembler.TRANSICOES_VALIDAS`
e `site_config.VALID_TRANSITION_TYPES` são duas cópias intencionais da mesma lista (pra evitar import circular) —
um teste (`test_site_config.py`) garante que elas nunca saem de sincronia sem ninguém perceber.

Isso veio de analisar um arquivo `message.json` que o usuário mandou — o "cérebro" de decisão de um sistema
separado chamado **DarkPlanner Studio** (167 templates + catálogos de 201 transições, 28 efeitos, 37
entradas/saídas, 74 filtros). Esse arquivo é metadado de DECISÃO (nomes, categorias, intensidade/energia/ritmo)
— não tem o código que desenha os efeitos na tela; a implementação visual mora no próprio DarkPlanner Studio, que
não foi enviado. Achado no meio do caminho: boa parte dos nomes do catálogo (`gl_oss_*`) batem com a biblioteca
open-source **GL Transitions** (gl-transitions.com) — portar essas exigiria um caminho técnico à parte (shader
GLSL, que o ffmpeg não roda nativamente), ainda não faz parte do site. Os outros nomes exóticos (`ft_pk2_burn1`,
`film_burn` etc.) são overlays de vídeo/imagem de verdade (queima de filme, vazamento de luz) — precisam dos
arquivos de mídia originais, que também não vieram no JSON.

A lista dos 13 arquivos de áudio referenciados pelos 167 templates (`camera_1.mp3`, `woosh_24.mp3` etc., com a
contagem de uso de cada um) foi extraída e entregue à parte, pra quando o usuário for atrás desses arquivos.

## 5 transições novas, construídas do zero (persianas, xadrez, ruído, íris)

Além das 58 transições nativas do ffmpeg, agora tem mais 9 **customizadas de verdade**, construídas com o modo
`custom` do filtro `xfade` (uma expressão matemática por pixel — sem shader GLSL, sem nenhum arquivo de vídeo/
imagem de apoio, só matemática): `blinds_h`/`blinds_v` (persianas horizontais/verticais), `checkerboard`
(xadrez), `noise_dissolve` (dissolve com textura de ruído, mais orgânico que o dissolve linear comum),
`iris_blur` (círculo que abre/fecha com borda suave, diferente do `circleopen` nativo que tem borda dura),
`diamond_iris` (a mesma ideia do `iris_blur`, mas em formato de losango), `pinwheel` (cata-vento com 6 lâminas
girando a partir do centro), `wave_wipe` (varredura horizontal com borda ondulada em vez de reta) e
`fade_grayscale` (dissolve comum que passa por um tom acinzentado no meio do caminho, em vez de misturar as
cores linearmente). Ficam registradas em `video_assembler.TRANSICOES_CUSTOMIZADAS` e aparecem no mesmo
`<select>` das outras, em Configurações. Testadas de verdade (não só "renderiza sem erro"): cada uma tem um
teste que confirma o PADRÃO VISUAL específico dela — incluindo um teste que compara `diamond_iris` com
`iris_blur` pixel a pixel pra confirmar que a forma é mesmo diferente (losango vs círculo), não só "parece igual
mas com nome diferente".

## Seletor do botão de configurações do Flow — correção

Achado por inspeção do HTML real que o usuário mandou (não por teste ao vivo): dois dos candidatos de
seletor do botão de configurações usavam a classe `.agent-panel`, que **não existe** no Flow real — a classe
verdadeira é `.agent-panel-prompt-box` (um seletor de classe CSS exige bater o nome inteiro; não é substring).
Corrigido, e adicionados dois candidatos novos, escopados dentro de `.agent-footer-actions` (o container
confirmado onde o botão realmente fica) — isso evita o risco de bater sem querer numa OUTRA engrenagem da tela
(a de configurações gerais da conta, na barra superior) antes de chegar no candidato certo. Ainda falta
confirmar o seletor do PAINEL que abre depois de clicar (`SEL_PAINEL_ROTULO`) — isso só dá pra saber vendo o
HTML de dentro do painel depois de clicar, que ainda não foi confirmado.

## Limitações conhecidas (lista única e atualizada)

- **Google Flow**: o botão de configurações do agente e o fim de cada geração com `x1` foram escritos a partir do HTML
  que você enviou, sem testar no site real (ver acima). A automação depende dos seletores da página do Flow (constantes `SEL_*` no topo de
  `googleflow_client.py`); se o Google mudar o site, é ali que se ajusta. Os testes automatizados usam um
  Playwright **falso** — eles garantem a lógica em volta (oculto, cache, fila, login), não que o Flow de verdade
  continue igual. O Google também pode bloquear login em navegador automatizado; nesse caso use o modo `cdp`.
- Prévias e montagem podem escolher imagens **diferentes** entre si em trechos parecidos quando "não repetir"
  está ligado e os trechos são processados em paralelo (a ordem de chegada decide quem fica com o melhor);
  o que é garantido é não haver duas iguais.

- **Escolhe sempre o primeiro resultado que conseguir baixar** de cada
  segmento (ou os próximos, em caso de falha) — não há lógica de
  "melhor match" além da ordem de relevância do próprio provedor.
- **Jobs ficam em memória** (dicionário Python) — se o servidor Flask
  reiniciar no meio de um processamento, o job se perde (embora o
  estado seja salvo em `jobs/<id>/state.json`, o app não recarrega
  automaticamente esses arquivos ao reiniciar). Pra produção de
  verdade, troque por um banco de dados ou fila de tarefas (Celery,
  RQ) em vez de rodar tudo em threads soltas.
- **Sem limpeza automática de arquivos temporários** — cada job deixa
  os clipes baixados e intermediários em `jobs/<id>/`. Pra produção,
  vale limpar isso periodicamente (ou logo após o download do vídeo
  final ser confirmado).
- **Transcodifica cada clipe individualmente** antes de concatenar
  (necessário pra garantir que todos tenham a mesma resolução/fps/codec
  e o `ffmpeg -c copy` do concat funcione sem erro) — isso é mais lento
  que um simples "copiar e colar" de vídeo, mas é o preço de aceitar
  clipes de fontes/resoluções diferentes.
- **Sem edição de timing por palavra**: as legendas usam os timestamps
  exatos que o Whisper devolveu — não tem uma interface pra ajustar
  manualmente onde cada palavra começa/termina antes de exportar.
- **Sem redefinição visual de início/fim de cena**: a timeline mostra e
  deixa trocar a FONTE de um segmento, mas não arrastar pra mudar
  quando ele começa/termina (isso exigiria re-validar a cobertura
  contígua do áudio inteiro, que não foi implementado).
- **Legenda é queimada, não uma faixa separada**: não dá pra ligar/
  desligar a legenda depois de gerada — por isso o site gera as duas
  versões (com e sem) desde o início.
- **Sem trilha sonora automática**: a IA só *sugere* um estilo em texto
  (`soundtrack_suggestion`) — não busca/gera a música sozinha. Pra ter
  áudio de trilha de verdade, você precisa enviar o arquivo manualmente
  no upload inicial.
- O upload de áudio tem limite de 200MB (`MAX_CONTENT_LENGTH` em
  `app.py`) — ajuste se precisar de narrações mais longas.
- **Sem autenticação nem rate limiting** — não exponha isso na internet
  pública sem adicionar essas proteções primeiro. `debug=True` em
  `app.run()` também deve ser desligado antes de qualquer deploy real.
  (`secure_filename()` já é usado nos uploads, isso está coberto.)

## Gerador de voz (texto → áudio narrado)

Aba separada (`/gerar-voz`, link no topo de todas as páginas) pra gerar
o próprio áudio de narração localmente, sem precisar gravar nem pagar
por uma API — útil quando você não tem um áudio de narração pronto pra
subir na etapa 1. Três motores à escolha, cada um baixando os próprios
arquivos de modelo sozinho na primeira vez que uma voz dele é usada:

- **Piper TTS** — leve, roda bem em CPU. `pip install piper-tts`
- **XTTS v2** (fork `coqui-tts`) — o mais expressivo, com clonagem de
  voz a partir de um áudio de referência; pesado, GPU recomendada.
  `pip install coqui-tts torch torchaudio`
- **Kokoro** (via `kokoro-onnx`) — equilíbrio entre os dois, com vozes
  prontas em vários idiomas, incluindo português do Brasil (`pf_dora`,
  `pm_alex`, `pm_santa`). `pip install kokoro-onnx soundfile`

Nenhum dos três é instalado por padrão (ver
`toolkit/tts/requirements.txt`) — instale só o(s) motor(es) que for
usar. Todos usam GPU automaticamente quando disponível (Piper/Kokoro
via `onnxruntime-gpu`, XTTS via PyTorch com CUDA) e caem pra CPU sozinhos
quando não há GPU, sem precisar mudar nada na configuração. Detalhes
completos de cada motor, parâmetros e como forçar CPU estão no
docstring de `toolkit/tts/voice_generator.py`.

O áudio gerado fica disponível pra baixar (`.wav`) — pra usar no
restante do pipeline, baixe o arquivo e suba ele normalmente na página
inicial, no campo de upload de áudio (essa aba ainda não empurra o
resultado direto pra lá).

## Roteiro para Áudio (projetos avulsos de narração)

Aba separada (`/narracoes`, link "📝 Roteiro para Áudio" no topo de
todas as páginas) — portada do projeto "shortmaker" (aba "Narrações"
do editor de dublagem) e adaptada pra usar o gerador de voz deste
projeto. Sem vídeo nenhum envolvido: você cola um texto bruto (um
roteiro escrito à mão, um script, qualquer coisa), ele separa em
falas (uma por linha, ou por frase), você edita/adiciona/remove falas
à vontade, escolhe o motor e a voz (os mesmos três do "Gerador de
voz" — Piper/XTTS v2/Kokoro), e gera um único áudio final com todas
as falas narradas e juntas.

Detalhes técnicos importantes que foram trazidos junto (não só a
"casca" da página):

- **Limpeza de texto antes do TTS** (`narracoes.limpar_texto_para_tts`)
  — remove aspas/parênteses e troca reticências/pontos soltos por
  vírgula antes de mandar pro motor de voz, pra ele não "falar" a
  pontuação em voz alta (comum em Piper/Kokoro com texto com pontuação
  incomum). O texto salvo no roteiro não muda, só o que é enviado ao TTS.
- **Normalização de volume em duas passadas** (loudnorm/EBU R128) no
  áudio final, pra ficar num volume consistente não importa o motor
  escolhido.
- **Geração em segundo plano com log ao vivo** — clicar em "Gerar
  áudio" dispara uma thread, e a página faz polling do progresso
  (mesmo padrão de "Transcrevendo o áudio..." da etapa 1 do pipeline
  principal) até o áudio final ficar pronto.

**O que NÃO foi trazido**: o modo "Minha Voz" do projeto original
(gravar a própria voz pelo microfone, com corte de silêncio e
realce/enhance por IA, fala por fala) — é um subsistema grande e
reutilizado em várias abas do shortmaker, fora do escopo desse
"roteiro para áudio" específico. Aqui todas as falas usam um dos três
motores de IA. Se fizer falta, dá pra portar depois como uma extensão
separada.
