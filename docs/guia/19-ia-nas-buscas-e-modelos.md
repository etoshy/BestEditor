# 19 · 🤖 IA nas buscas, no editor e nos Modelos de vídeo

Uma página nova, **🤖 IA nas buscas e modelos** (endereço `/ia`, link junto dos outros no topo e um atalho em
⚙️ Configurações), liga uma IA que **entende o roteiro** antes de buscar e **olha** o que achou.

Por enquanto a IA é o **Claude Haiku 5.5** (`claude-haiku-5-5`). A página já está pronta para outras IAs (a lista
`PROVEDORES` em `ia_servico.py`).

**Desligada, sem chave, sem crédito, acima do limite de gasto ou com erro, o site faz tudo como antes.** A IA melhora,
mas nunca trava nada: se a API recusar a chave ou disser que acabou o crédito, ela se desliga sozinha e a página mostra
um botão 🔁 *Tentar de novo*.

## Como ligar

1. Crie uma chave em platform.claude.com → API keys (e, se quiser, ponha um limite de gasto mensal lá).
2. Em 🤖 IA: marque **Ligar a IA**, cole a chave, **💾 Salvar** e **🔌 Testar a chave**.
3. Escolha o que ela faz (cada item liga/desliga sozinho).

A chave fica em `ia_config.json` (fora do GitHub). A variável de ambiente `ANTHROPIC_API_KEY` também vale.
O gasto fica em `ia_uso.json` e aparece na página, por recurso, com as últimas chamadas.

## O que ela faz

| Recurso | Onde | O que muda |
|---|---|---|
| 🧭 Ficha + buscas melhores | ao buscar as prévias | lê o roteiro uma vez (quem é quem, lugares, época, duplo sentido, o que evitar) e reescreve as buscas de cada trecho (2–4, em inglês, da específica pra genérica). A busca original vira a última alternativa |
| ⚖️ Juiz visual | prévias da timeline (bancos e buscadores Bing/Brave/Yandex/Startpage) | olha 10 miniaturas e escolhe a melhor. Nota ≥ mínima = usa; 5–6 = usa com ⚠ no nome; abaixo de 5 = busca de novo |
| 🔁 Reescrever a busca | junto do juiz | com tudo abaixo de 5, tenta a busca sugerida pelo juiz (no máximo 2 vezes); no fim, a melhor das reprovadas com ⚠ |
| 🔎 Nota no Buscar | Estúdio → painel do trecho → Buscar | resultados na ordem da nota, com a nota no canto e o motivo ao passar o mouse |
| 🎬 YouTube | painel "Vídeos do YouTube" | busca 20, mostra os 8 melhores (nota no canto) + ➕ Outros vídeos |
| 🎯 Momento pela legenda | painel do YouTube, depois de escolher o vídeo | lê a legenda do vídeo e preenche início e fim (com folga de 0,4 s) e a frase dita |
| 📚 Wikipedia | termos da Wikipedia + fotos da Wikipedia | nomes vindos da ficha (sem o limite de 15), o artigo certo quando há vários, a **foto principal** do artigo primeiro, sem bandeira/brasão/mapa/logo, nada menor que 400 px |
| 🕵️ Ficha das imagens | 🕵️ Modelos de vídeo | cada imagem ganha descrição, quem/o quê (pela legenda), texto na imagem, tipo, sensível. Lixo/anúncio e duplicadas saem do prompt (dá pra voltar com ♻). Fotos do PC podem ir sem descrição |
| 📄 PDF e dossiê condensado | fontes por arquivo | PDF escaneado (ou só as páginas sem texto) lido pela IA em partes de 25 páginas; arquivo com mais de 40 mil caracteres vira um **dossiê condensado** (fatos com a página de cada um) |
| ✅ Conferir as marcas | resultado do roteiro do dossiê | aponta as marcas [I3] em frases que não combinam com a imagem |
| 🛒 Fotos do produto | 🛒 Vídeo de venda | ângulo, em uso, embalagem, texto/preço na imagem |
| 📝 Roteiros direto na IA | 🕵️ Modelos de vídeo, 🛒 Vídeo de venda, 📜 Roteiro do YouTube (passos 1 e 2), 🎞️ Vídeos modelados (roteiro e ajuste) | botão **🤖 Gerar com a IA** ao lado do Gerar prompt: gera o prompt, manda pra IA, cola a resposta e já lê |
| ✂️ Edição direto na IA | Estúdio → 🤖 IA | botão **🤖 Fazer com a IA** (no prompt inteiro ou em cada parte) |

O que **pula** a IA: escolhas manuais, acervos locais com obra/personagem (o metadado já é confiável), Flow, mídia do
produto e trechos do YouTube (que têm o painel próprio).

## ✂️ Prompt de edição em partes (opcional)

Na aba 🤖 IA do Estúdio, marque **✂️ Dividir em partes de 12 min**. Um vídeo de 1 hora vira 5 prompts. Cada um
cobre só a sua parte (os números T… continuam os do vídeo inteiro); filtro, paleta e legenda vêm só da parte 1.
Cole a resposta de cada parte no seu lugar e clique em **👁 Conferir**: o site junta tudo num plano só. Funciona com
qualquer IA (copiar e colar) e não precisa da IA do site ligada.

**Uma cara só pro vídeo inteiro:** a **parte 1 decide a direção de arte** (o prompt dela pede um `"direcao_arte"`).
Quando você cola a resposta da parte 1, o site lê o que ela escolheu — filtro, paleta, legenda, estilos de destaque,
fontes, animações, zonas, transições, efeitos, gráficos, quadros e as regras que ela listou — e põe isso nos prompts
das partes 2…N ("🎨 DIREÇÃO DE ARTE JÁ DECIDIDA NA PARTE 1 — siga igual"). Até a parte 1 ter resposta, as outras
ficam 🔒 travadas.

## Custo

Com o cache (instruções + ficha no cache de 1 hora da API, mais as respostas guardadas em `ia_cache/`), um vídeo de
25 minutos fica perto de **US$ 0,10–0,20**. Com os US$ 5 dá para algumas dezenas de vídeos. O limite de gasto da
página para a IA sozinha quando chega lá.

## Para programadores

- `ia_servico.py`: config, `ativo(recurso)`, `chamar(recurso, system, conteudo, schema)` (JSON garantido por
  `output_config.format`, thinking desligado onde não precisa, retentativas, custo, cache), `imagem_bloco()`.
- `ia_midia.py`: `ficha_visual`, `buscas_melhores`, `julgar`, `ordenar_youtube`, `achar_momento`, `desambiguar`.
- `ia_dossies.py`: `duplicadas`, `fichar_imagens`, `ler_pdf`, `condensar`, `conferir_marcas`.
- Testes: `test_v84_ia.py` (um transporte falso no lugar da API). A suíte roda com a IA desligada
  (`IA_DADOS_DIR` aponta pra uma pasta vazia).
